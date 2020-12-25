from typing import Set
from subprocess import run, PIPE, TimeoutExpired

from models import AbstractGateway
from base import _NGINXConfig, _SLBConfig, SimpleLog, CommandError, NoSupportGatewayError

log = SimpleLog(__name__).log


class _RemoteNGINX(object):
    _cmd_fmt = """ssh {username}@{host} '{command}'"""
    _filter_fmt = r"""sed -rn "s/.*\bserver\b(.*\b:{port}\b).*/\1/p;" {config_file}"""

    def __init__(self, host: str, username: str):
        self._host = host
        self._username = username
        self._fetch_servers = set()

    def __repr__(self) -> str:
        return "RemoteNGINX(host={})".format(self._host)

    def _run(self, cmd: str) -> str:
        _command = self._cmd_fmt.format(username=self._username, host=self._host, command=cmd)
        try:
            std = run(_command, shell=True, timeout=5, stdout=PIPE, stderr=PIPE)
            stdout = std.stdout.decode("utf8", errors="ignore")
            if std.returncode and std.stderr:
                err_output = std.stderr.decode("utf8", errors="ignore")
                log.error("执行远程命令失败，原始命令输出{}".format(err_output))
                stdout = ""
            elif std.returncode == 0 and stdout == "":
                stdout = ""
        except TimeoutExpired:
            stdout = ""
            log.error("执行远程命令超时...")
        return stdout

    def get_servers(self, config_file: str, backend_port: int) -> Set[str]:
        if not self._fetch_servers:
            command = self._filter_fmt.format(port=backend_port, config_file=config_file)
            for line in self._run(command).split("\n"):
                if line:
                    self._fetch_servers.add(line.strip())
        log.debug("获取到的后端服务器信息为: {}".format(self._fetch_servers))
        return self._fetch_servers

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
            check_cmd = r'grep -e ".*#.*\bserver\b.*\b{host}\b.*" {conf}'.format(host=server, conf=config_file)
            # 先检查当前主机是否已经在下线状态,匹配成功说明已经下线，忽略，未匹配到就执行cmd
            command = "{check}||({cmd})".format(check=check_cmd, cmd=_cmd.format(server=server, conf=config_file))
        else:
            raise NoSupportGatewayError("Only support up or down status")
        return bool(self._run(command))


class _NGINXGateway(AbstractGateway):
    """
    NGINX作为网关层，一般会有多台，再封装一次，对外统一提供抽象的AbstractGateway
    """
    _cmd_fmt = """ssh {username}@{host} '{command}'"""
    _filter_fmt = r"""sed -rn "s/.*\bserver\b(.*\b:{port}\b).*/\1/p;" {config_file}"""

    def __init__(self, _conf: _NGINXConfig):
        _hosts = _conf.hosts
        if not _hosts:
            raise CommandError("全局NGINX网关配置有误，地址不能为空")
        _username = _conf.username
        self._nginxs: Set[_RemoteNGINX] = {_RemoteNGINX(_host, _username) for _host in _hosts}

    def get_servers(self, **kwargs) -> Set[str]:
        backend_port = kwargs.get("backend_port")
        config_file = kwargs.get("config_file")
        _servers = set()
        for ngx in self._nginxs:
            backend_servers = ngx.get_servers(backend_port=backend_port, config_file=config_file)
            _servers.update(backend_servers)
        return _servers

    def change_server_offline(self, server: str, **kwargs) -> None:
        _config_file = kwargs.get("config_file")
        log.info("通过NGINX网关对主机{}下线".format(server))
        assert _config_file, "当使用NGINX网关时，上/下线服务器关键字参数config_file为必须"
        for ngx in self._nginxs:
            ngx.change_server("error", _config_file, server)

    def change_server_online(self, server: str, **kwargs) -> None:
        _config_file = kwargs.get("config_file")
        assert _config_file, "当使用NGINX网关时，上/下线服务器关键字参数config_file为必须"
        for ngx in self._nginxs:
            ngx.change_server("ok", _config_file, server)

    def __repr__(self) -> str:
        return "NGINXGateway(hosts={})".format(self._nginxs)


# TODO 后续再实现
class _SLBGateway(AbstractGateway):
    def __init__(self, _conf: _SLBConfig):
        self._key = _conf.key
        self._secret = _conf.secret
        self._region = _conf.region

    def __repr__(self) -> str:
        return "SLBGateway(key=***,secret=***)"

    # TODO SLB_ID/Listen_port在获取服务时需要
    def get_servers(self, **kwargs) -> Set[str]:
        """
        :param kwargs: slb_id, slb_listen_port
        :return:
        """
        return set("")

    def change_server_offline(self, server: str, **kwargs) -> None:
        slb_id = kwargs.get("slb_id")
        slb_listen_port = kwargs.get("slb_listen_port")
        assert slb_id and slb_listen_port, "SLB网关上/下线时，slb_id与slb_listen_port关键字参数为必须"

    def change_server_online(self, server: str, **kwargs) -> None:
        slb_id = kwargs.get("slb_id")
        slb_listen_port = kwargs.get("slb_listen_port")
        assert slb_id and slb_listen_port, "SLB网关上/下线时，slb_id与slb_listen_port关键字参数为必须"
