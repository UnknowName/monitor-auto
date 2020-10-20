import os
import logging
import logging.handlers
from threading import Thread
from subprocess import run, PIPE, STDOUT, TimeoutExpired

import yaml
import jinja2


class NoServersConfigError(Exception):
    def __init__(self, error: str):
        Exception(error)


class NoDomainError(Exception):
    def __init__(self, domain: str):
        Exception("{} no found servers".format(domain))


class CommandError(Exception):
    def __init__(self, error: str):
        Exception(error)


class MyLog(object):
    """Custer Define Logger"""
    fmt = logging.Formatter(
        '%(asctime)s %(module)s %(threadName)s %(levelname)s %(message)s'
    )

    def __init__(self, name, filename=None):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(self.fmt)
        self.logger.addHandler(ch)
        if filename:
            fh = logging.handlers.TimedRotatingFileHandler(filename, 'D', 1, 7)
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(self.fmt)
            self.logger.addHandler(fh)


log = MyLog(__name__)


# 用来获取远端NGINX中的upstream中的主机列表,这个类不要主动引用
class _RemoteNGINX(object):
    # 不能用单例模式，有可能不同域名的网关是不一样的，那取的数据肯定就有误
    _remote_fmt = """ssh root@{host} '{command}'"""
    _cmd_fmt = r"""sed -rn "s/.*\bserver\b(.*\b:{port}\b).*/\1/p;" {config_file}"""

    def __init__(self, host: str):
        self.host = host
        self._servers = None

    def _execute(self, cmd: str) -> str:
        _command = self._remote_fmt.format(host=self.host, command=cmd)
        try:
            std = run(_command, shell=True, timeout=5, stdout=PIPE, stderr=PIPE)
            stdout = std.stdout.decode("utf8", errors="ignore")
            if std.returncode and std.stderr:
                err_output = std.stderr.decode("utf8", errors="ignore")
                log.logger.warning("Command output is {}**************".format(err_output))
                raise CommandError(err_output)
            elif std.returncode == 0 and stdout == "":
                stdout = "stdout no output"
        except CommandError:
            stdout = ""
        except TimeoutExpired:
            stdout = ""
            log.logger.error("Execute Remote NGINX Timeout")
        return stdout

    def get_servers(self, config_file: str, backend_port: int) -> set:
        if self._servers:
            return self._servers
        result = set()
        command = self._cmd_fmt.format(port=backend_port, config_file=config_file)
        for line in self._execute(command).split("\n"):
            if line:
                result.add(line.strip())
        self._servers = result
        return result

    def change_server(self, status: str, config_file: str, server: str) -> bool:
        """
        :param status: error/ok
        :param config_file: /etc/nginx/conf.d/test.conf
        :param server: 128.0.255.27:15672
        :return:
        """
        if status == "ok":
            _cmd = (r'sed --follow-symlinks -ri '
                    r'"s/(\s+?)#+?(.*\bserver\b\s+?\b{server}\b.*)/\1\2/g" {conf}'
                    r'&&nginx -t&&nginx -s reload')
            command = _cmd.format(server=server, conf=config_file)
        elif status == "error":
            _cmd = (r'sed --follow-symlinks -ri '
                    r'"s/(.*\bserver\b\s+?\b{server}\b.*)/#\1/g" {conf}'
                    r'&&nginx -t&&nginx -s reload')
            check_command = r'grep -e ".*#.*\bserver\b.*\b{host}\b.*" {conf}'.format(host=server, conf=config_file)
            # 先检查当前主机是否已经在下线状态,匹配成功说明已经下线，忽略，未匹配到就执行cmd
            command = "{check}||({cmd})".format(check=check_command, cmd=_cmd.format(server=server, conf=config_file))
        else:
            raise Exception("Only support up or down status")
        return bool(self._execute(command))


# 某个站点的配置对象信息，如www.aaa.com的配置
class DomainConfig(object):
    def __init__(self, domain_data: dict, nginxs: list):
        self._data = domain_data
        self._domain = domain_data.get("site", "")
        # 域名下有单独配置NGINXS，优先级高于传进来的，传入进来的是全局的
        self._nginxs = domain_data.get("nginxs") if domain_data.get("nginxs") else nginxs
        self.__servers = None

    def __repr__(self):
        return "DomainConfig(domain={})".format(self.domain)

    @property
    def domain(self):
        return self._domain

    @property
    def nginxs(self):
        return self._nginxs

    def get(self, attr: str) -> str:
        return self._data.get(attr, "")

    def get_servers(self) -> set:
        if self.__servers:
            return self.__servers
        if "servers" in self._data:
            return set(self._data.get("servers"))
        _ngx = _RemoteNGINX(self.nginxs[0])
        _servers = _ngx.get_servers(self._data.get("config_file"), self._data.get("backend_port"))
        self.__servers = _servers
        return _servers


class AppConfig(object):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "AppConfig(filename=config.yml)"

    def __init__(self, filename: str):
        filename = filename if filename else "config.yml"
        with open(filename, encoding="utf8") as f:
            self._data = yaml.safe_load(f)

    def get_attrs(self, attr: str) -> list:
        return self._data.get(attr, [])

    def get_domain_config(self, domain: str) -> DomainConfig:
        _domains = self.get_attrs("sites")
        for _domain in _domains:
            if _domain.get("site") == domain:
                return DomainConfig(_domain, self.get_attrs("nginxs"))
        # 如果获取未配置的域名，抛出异常
        raise NoDomainError(domain)


class _BaseActionThread(Thread):
    def __init__(self, domain: str, host: str, **kwargs):
        """
        :param domain: "dev.siss.io"
        :param host: "128.0.255.27:80"
        """
        Thread.__init__(self)
        self._host = host
        self._domain = domain
        self._kwargs = kwargs
        self._observe = None
        self._action_type = "ok"

    def set_action_type(self, name: str):
        if name in ["error", "ok"]:
            self._action_type = name
        else:
            raise Exception("Action type only error or ok")

    @staticmethod
    def execute_action(playbook: str) -> None:
        cmd = "ansible-playbook {}".format(playbook)
        stdout = run(cmd, shell=True, stdout=PIPE, stderr=STDOUT).stdout
        output = stdout.decode("utf8", errors="ignore")
        log.logger.info("Ansible task output:\n{}".format(output))


# TODO AsyncAction 通过asyncio.create_subprocess_exec封装起来
class NginxAction(_BaseActionThread):
    _tmpl = r"""        
    - hosts:
      - {{ host }}
      gather_facts: False
      tasks:
      - name: Restart IIS Website {{ domain }}
        win_iis_website: name={{ domain }} state=restarted
    """

    def __repr__(self):
        return "NginxAction({}, {})".format(self._domain, self._host)

    # TODO 将名字修改成prepare，并创建_RemoteNGINX实例，并执行服务上/下线动作，后续就可以启动线程了
    def _prepare(self, status: str) -> bool:
        """
        :param status: error/ok
        :return:
        """
        config_file = self._get_config()
        nginxs = [_RemoteNGINX(nginx) for nginx in self._kwargs.get("nginxs")]
        results = [nginx.change_server(status, config_file, self._host) for nginx in nginxs]
        return all(results)

    def _get_config(self) -> str:
        if self._kwargs.get("config_file"):
            return self._kwargs.get("config_file")
        else:
            # 如果没有自定义的config_file，那就构造一个默认的
            return "/etc/nginx/conf.d/{}.conf".format(self._domain)

    def run(self) -> None:
        if not self._action_type:
            raise Exception("Before Run start, Please call set_action_type(name: str)")
        log.logger.info("execute {} action".format(self._action_type))
        if self._prepare(self._action_type):
            log.logger.info("Execute prepare ok-------------------------")
        else:
            log.logger.info("Execute prepare failed---------------------")
        if self._action_type == 'error':
            host, port = self._host.split(":")
            _filename = "{domain}_{host}.yml".format(domain=self._domain, host="{}_{}".format(host, port))
            task_file = os.path.join(os.path.pardir, "tasks_yaml", _filename)
            with open(task_file, 'w') as f:
                f.write(jinja2.Template(self._tmpl).render(host=host, domain=self._domain))
            self.execute_action(task_file)


if __name__ == '__main__':
    nginx_action = NginxAction("dev.siss.io",
                               "128.0.255.10:80",
                               nginxs=["128.0.255.2", "128.0.255.3"],
                               config_file="/etc/nginx/conf.d/test.conf"
                               )
    nginx_action.set_action_type("error")
    nginx_action.start()
    """
    config = AppConfig("")
    domain_configs = config.get_domain_config("www.aaa.com")
    print(domain_configs.get("max_failed"))
    # print(config.get_attrs("sites"))
    op = Option(config)
    print(op.get_config("www.aaa.com"))
    print(op.get_nginxs())
    nginx = _RemoteNGINX("128.0.255.10")
    servers = nginx.get_servers("/etc/nginx.conf", 80)
    print(servers)
    """
