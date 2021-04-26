from typing import Set
from abc import ABCMeta, abstractmethod
from subprocess import run, PIPE, TimeoutExpired

from utils import _Single, SimpleLog

log = SimpleLog(__name__).log


class AbstractGateway(metaclass=ABCMeta):
    @abstractmethod
    def get_servers(self) -> Set[str]:
        pass

    @abstractmethod
    def change_server_online(self, server: str):
        pass

    @abstractmethod
    def change_server_offline(self, server: str):
        pass


class AbstractGatewayFactory(metaclass=ABCMeta):
    @staticmethod
    def get_gateway(site_conf_data: dict, gateway_data: dict) -> AbstractGateway:
        pass


class StaticGateway(AbstractGateway):
    def __init__(self, data: dict):
        self.type = data.get("type")
        self._servers = set(data.get("servers", []))
        assert self._servers and self.type == "static", "Backend Type Error"

    def get_servers(self) -> Set[str]:
        return self._servers

    def change_server_offline(self, server: str):
        # print("static backend, nothing to do")
        pass

    def change_server_online(self, server: str):
        # print("static backend, nothing to do")
        pass

    def __repr__(self) -> str:
        return f"StaticGateway(servers={self._servers})"


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
        if status == "up":
            _cmd = (r'sed --follow-symlinks -ri '
                    r'"s/(\s+?)#+?(.*\bserver\b\s+?\b{server}\b.*)/\1\2/g" {conf}'
                    r'&&nginx -t&&nginx -s reload')
            command = _cmd.format(server=server, conf=config_file)
        elif status == "down":
            _cmd = (r'sed --follow-symlinks -ri '
                    r'"s/(.*\bserver\b\s+?\b{server}\b.*)/#\1/g" {conf}'
                    r'&&nginx -t&&nginx -s reload')
            check_cmd = r'grep -e ".*#.*\bserver\b.*\b{host}\b.*" {conf}'.format(host=server, conf=config_file)
            # 先检查当前主机是否已经在下线状态,匹配成功说明已经下线，忽略，未匹配到就执行cmd
            command = "{check}||({cmd})".format(check=check_cmd, cmd=_cmd.format(server=server, conf=config_file))
        else:
            raise Exception("Only support up or down status")
        return bool(self._run(command))


class NGINXGateway(AbstractGateway):
    def __init__(self, data: dict, gateway_data: dict):
        self._fetch = False
        self._servers = set()
        self.upstream_port = data.get("upstream_port")
        self.config_file = data.get("config_file")
        ssh_user = gateway_data.get("user", "None")
        hosts = gateway_data.get("hosts", [])
        assert data and gateway_data and hosts, "config file error, remote NGINX hosts not config"
        self._nginxs = [_RemoteNGINX(host, ssh_user) for host in hosts]
        assert self.config_file and isinstance(self.upstream_port, int), "no site NGINX config file"

    def get_servers(self) -> Set[str]:
        if self._fetch:
            return self._servers
        for ngx in self._nginxs:
            servers = ngx.get_servers(self.config_file, self.upstream_port)
            self._servers.update(servers)
        self._fetch = True
        return self._servers

    def change_server_online(self, server: str):
        for ngx in self._nginxs:
            result = ngx.change_server("up", self.config_file, server)
            log.debug(f"change server {server} online on {ngx}, result: {result}")

    def change_server_offline(self, server: str):
        for ngx in self._nginxs:
            result = ngx.change_server("down", self.config_file, server)
            log.debug(f"change server {server} offline on {ngx}, result: {result}")

    def __repr__(self) -> str:
        return f"NGINXGateway(user=root, hosts=[])"


# TODO 实现具体功能
class AliyunSLBGateway(AbstractGateway):
    def __init__(self, data: dict, gateway_data: dict):
        self._fetch = False
        self._servers = set()
        self.id = data.get("id")
        self.port = data.get("port")
        key = gateway_data.get("key")
        secret = gateway_data.get("secret")
        region = gateway_data.get("region")
        assert self.id and self.port and key and secret and region, "config file error"

    def get_servers(self) -> Set[str]:
        if self._fetch:
            return self._servers
        return set()

    def change_server_offline(self, server: str):
        pass

    def change_server_online(self, server: str):
        pass

    def __repr__(self) -> str:
        return f"AliyunSLBGateway(key=****, secret=****)"


class GatewayFactory(_Single, AbstractGatewayFactory):
    @staticmethod
    def get_gateway(site_conf_data: dict, gateway_data: dict) -> AbstractGateway:
        backend = site_conf_data.get("gateway", {})
        backend_type = backend.get("type", "None").lower()
        if backend_type == "nginx":
            nginx_data = gateway_data.get("nginx")
            return NGINXGateway(backend, nginx_data)
        elif backend_type == "static":
            return StaticGateway(backend)
        elif backend_type == "slb":
            slb_data = gateway_data.get("slb")
            return AliyunSLBGateway(backend, slb_data)
        else:
            raise Exception("what this gateway?")
