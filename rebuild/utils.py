import re
import os
from threading import Thread
from subprocess import run, PIPE, STDOUT

import yaml
import jinja2

from notify import AsyncNotify


class NoServersConfigError(Exception):
    def __init__(self, error: str):
        raise Exception(error)


class CommandError(Exception):
    def __init__(self, error: str):
        raise Exception("ERROR: {}".format(error))


# 用来获取远端NGINX中的upstream中的主机列表,这个类不要主动引用
class _RemoteNGINX(object):
    """
    # 不能用单例模式，有可能不同域名的网关是不一样的，那取的数据肯定就有误
    _instance = None

     def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance
    """
    _filter = re.compile(r".*server\s+(\d.*:\d+).*")
    _remote_fmt = "ssh {host} '{command}'"
    _cmd_fmt = r"""grep -E "\s+?#+?\bserver\b\s+.*\b:{port}\b.*;" {config_file}"""

    def __init__(self, host: str):
        self.host = host
        self._servers = None

    def _execute(self, cmd: str) -> str:
        _command = self._remote_fmt.format(host=self.host, command=cmd)
        try:
            std = run(_command, shell=True, timeout=5, stdout=PIPE, stderr=STDOUT)
            stdout = std.stdout.decode("utf8", errors="ignore")
            if std.returncode and stdout:
                raise CommandError(stdout)
        except Exception as e:
            stdout = ""
            print(e)
        return stdout

    def get_servers(self, config_file: str, backend_port: int) -> set:
        if self._servers:
            return self._servers
        result = set()
        command = self._cmd_fmt.format(port=backend_port, config_file=config_file)
        for line in self._execute(command).split(";\n"):
            if line and self._filter.match(line):
                server = self._filter.match(line).groups()[0]
                result.add(server.strip())
        self._servers = result
        return result


# 某个站点的配置对象信息，如www.aaa.com的配置
class DomainConfig(object):
    def __init__(self, domain: dict, nginxs: list):
        self.domain = domain
        # 初始化时，调用者会判断优先级
        self.nginx = nginxs[0]

    # TODO 统一返回后的类型，最好是dict,key就为传进来的KEY，VALUE就是值
    def get(self, attr: str) -> object:
        # 如果config.yml有配置静态的servers,直接返回配置的
        if (attr in self.domain) or (attr != "servers"):
            return self.domain.get(attr)
        else:
            # 只有当attr == "servers" 而且没有配置静态的servers，才从远端NGINX中读取后端信息
            _ngx = _RemoteNGINX(self.nginx)
            _servers = _ngx.get_servers(self.domain.get("config_file"), self.domain.get("backend_port"))
            return _servers


class AppConfig(object):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, filename: str):
        filename = filename if filename else "config.yml"
        with open(filename, encoding="utf8") as f:
            self._data = yaml.safe_load(f)

    def get_attrs(self, attr: str) -> list:
        return self._data.get(attr, [])


class Option(object):
    _instance = None
    _attrs = dict()
    _notify = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, app_config: AppConfig):
        domains = app_config.get_attrs("sites")
        nginxs = app_config.get_attrs("nginxs")
        self._attrs["nginxs"] = nginxs
        for domain_config in domains:
            domain_name = domain_config.get("site")
            self._attrs[domain_name] = domain_config

    def add_notify(self, notify: AsyncNotify) -> None:
        if not self._notify:
            self._notify = notify

    def get_notify(self) -> AsyncNotify:
        return self._notify

    def get_nginxs(self) -> list:
        return self._attrs.get("nginxs", [])

    def get_attr(self, domain: str, key: str) -> str:
        return self._attrs.get(domain, {}).get(key, "")

    # TODO 这个方法要重写，返回的类型不能是dict了。
    # TODO 因为获取站点的servers要从NGINX配置文件中读取，不再写死
    # TODO 返回修改为DomainConfig
    def get_domain_config(self, domain: str) -> DomainConfig:
        domain_dic = self._attrs.get(domain, {})
        domain_nginxs = domain_dic.get("nginxs") if domain_dic.get("nginxs") else self.get_nginxs()
        return DomainConfig(domain_dic, domain_nginxs)
        # return self._attrs.get(domain, {})


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
        try:
            std = stdout.decode("utf8")
        except UnicodeDecodeError:
            std = stdout.decode("gbk")
        print(std)


# 通过Ansible下线并重启IIS站点，两个动作合并成一个
class NginxAction(_BaseActionThread):
    """
    发生错误的动作,从NGINX上下线
    """

    _down_tmpl = r"""
    - hosts:
      {%- for nginx in nginxs %}
      - {{ nginx }}
      {% endfor -%}
      gather_facts: False
      tasks:
      - name: Gateway down host {{ host }}
        lineinfile:
          path: /etc/nginx/conf.d/{{ domain }}.conf
          regexp: '(\s{0,}\bserver\b\s+?\b{{ host }}\b.*)'
          line: '#\1'
          backrefs: yes
        register: stdout
        
      - name: Check NGINX Config file
        shell: nginx -t
        when: stdout.changed == True
        
      - name: Reload NGINX
        shell: systemctl reload nginx || nginx -s reload
        when: stdout.changed == True
        
      - name: Sleep 10 second
        pause: 
          seconds: 10
        
    - hosts:
      - {{ host.split(":")[0] }}
      gather_facts: False
      tasks:
      - name: Restart IIS Website {{ domain }}
        win_iis_website: name={{ domain }} state=restarted
    """

    _up_tmpl = r"""
    - hosts:
      {%- for nginx in nginxs %}
      - {{ nginx }}
      {% endfor -%}
      gather_facts: False
      tasks:
      - name: Gateway up host {{ host }}
        lineinfile:
          path: /etc/nginx/conf.d/{{ domain }}.conf
          regexp: '(\s{0,})#(\s{0,}\bserver\b\s+?\b{{ host }}\b.*)'
          line: '\1\2'
          backrefs: yes
        register: stdout
        
      - name: Check NGINX config file
        shell: nginx -t
        when: stdout.changed == True
    
      - name: Reload NGINX
        shell: systemctl reload nginx || nginx -s reload
        when: stdout.changed == True
    """

    def __repr__(self):
        return "NginxAction({}, {})".format(self._domain, self._host)

    def _create_yaml(self, host: str, domain: str) -> str:
        nginxs = self._kwargs.get("nginxs")
        if self._action_type == 'error':
            task_yaml = self._down_tmpl
        else:
            task_yaml = self._up_tmpl
        _filename = "{domain}_{host}_{action}.yml".format(domain=domain,
                                                          host=host.replace(":", "_"),
                                                          action=self._action_type)
        task_file = os.path.join(os.path.pardir, "tasks_yaml", _filename)
        with open(task_file, 'w') as f:
            f.write(jinja2.Template(task_yaml).render(nginxs=nginxs, host=host, domain=domain))
            return task_file

    def run(self) -> None:
        if not self._action_type:
            raise Exception("Before Run start, Please call set_action_type(name: str)")
        playbook = self._create_yaml(self._host, self._domain)
        self.execute_action(playbook)


if __name__ == '__main__':
    # nginx_action = NginxAction("dev.siss.io", "128.0.255.10:80", action="down", nginxs=["128.0.255.2", "128.0.255.3"])
    # nginx_action.start()
    """
    config = AppConfig("")
    op = Option(config)
    print(op.get_config("www.aaa.com"))
    print(op.get_nginxs())
    """
    nginx = _RemoteNGINX("128.0.255.10")
    servers = nginx.get_servers("/etc/nginx.conf", 80)
    print(servers)
