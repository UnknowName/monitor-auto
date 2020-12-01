import yaml
from threading import Thread
from abc import abstractmethod

from utils import _RemoteNGINX


class ConfigError(Exception):
    def __init__(self, msg: str):
        Exception(msg)


class _Gateway(object):
    @abstractmethod
    def get_servers(self, **kwargs) -> set:
        pass

    @abstractmethod
    def change_server(self, host: str, _type: str):
        pass


class _Config(object):
    @abstractmethod
    def get_site_config(self, name: str) -> _Gateway:
        pass


# 这个类不要主动实例化与调用，是在_SiteConfig类中调用的
# 之所以再包装一层，是因为NGINX网关可能有多个
class _NGINXGateway(_Gateway):
    def __init__(self, site_conf, conf_data: dict):
        self._conf = site_conf
        self.hosts = conf_data.get("hosts", [])
        self.username = conf_data.get("user", "root")

    def get_servers(self) -> set:
        _port = self._conf.backend_port
        _file = self._conf.config_file
        _servers = [_RemoteNGINX(host).get_servers(config_file=_file, backend_port=_port) for host in self.hosts]
        result = set()
        for s in _servers:
            result = result | s
        return result

    def change_server(self, host: str, _type: str):
        # 在新线程内实现，不然会有阻塞
        for ngx_host in self.hosts:
            ngx = _RemoteNGINX(ngx_host)
            t = Thread(target=ngx.change_server, args=(_type, self._conf.config_file, host))
            t.start()


# 这个类不要主动实例化与调用，是在_SiteConfig类中调用的
class _SLBGateway(_Gateway):
    def __init__(self, site_conf, conf_data: dict):
        self.key = conf_data.get("key")
        self.secret = conf_data.get("secret")
        if (not self.key) or (not self.secret):
            raise ConfigError("SLB Key or secret not config")

    def get_servers(self) -> set:
        pass
        return set()
        # 还差一个SLB的ID与前端监听的端口或者虚拟组名称

    def change_server(self, host: str, _type: str):
        pass


class _SiteConfig(object):
    def __init__(self, data: dict):
        self.site = data.get("site", False)
        if not self.site:
            raise ConfigError("site name must set")
        self.gateway_type = data.get("gateway_type")
        if not self.gateway_type:
            raise ConfigError("Site {} gateway_type no config".format(self.site))
        if self.gateway_type == "nginx":
            config_file = data.get("config_file")
            if not config_file:
                raise ConfigError("When Use NGINX Gateway,The backend port and config file must present")
            _backend_port = data.get("backend_port")
            if not _backend_port:
                raise ConfigError("When Use NGINX Gateway,The backend port and config file must present")
            self.config_file = config_file
            self.backend_port = _backend_port
        elif self.gateway_type == "slb":
            self.listen_port = data.get("listen_port")
            if not self.listen_port:
                raise ConfigError("When Use SLB Gateway,The listen port and SLB ID must present")
            self.slb_id = data.get("slb_id")
            if not self.slb_id:
                raise ConfigError("When Use SLB Gateway,The listen port and SLB ID must present")
        else:
            raise ConfigError("Don't support the gateway {}".format(self.gateway_type))
        self.__servers = data.get("servers", set())
        self.timeout = int(data.get("timeout", 5))
        self.max_failed = int(data.get("max_failed", 5))
        # 如果这里没有取到值，当调用get_servers()，取获取后端的一半值
        self.max_inactive = data.get("max_inactive")
        self.auto = data.get("auto_recover", False)
        self.auto_inter = int(data.get("auto_inter", 300))
        self.path = data.get("path", "/")
        # 增加网关属性
        self._gate_obj = None

    def __repr__(self) -> str:
        return "SiteConfig(site={site})".format(site=self.site)

    @property
    def gateway(self) -> _Gateway:
        return self._gate_obj

    @property
    def servers(self):
        if self.__servers:
            return self.__servers
        return self._gate_obj.get_servers()

    def set_gateway(self, gateway: _Gateway):
        self._gate_obj = gateway


class AppConfig(_Config):
    __instance = None

    def __new__(cls, *args, **kwargs):
        if not cls.__instance:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    def __init__(self, filename: str = "config.yml"):
        with open(filename, encoding="utf8") as f:
            _data = yaml.safe_load(f)
            self.__notifies = _data.get("notify")
            self._site_configs = [_SiteConfig(site_data) for site_data in _data.get("sites")]
            self.__gateway_config = _data.get("gateway", {})

    # 不要主动调用，在调用get_site_conf时会调用，用于获取站点的网关配置信息
    def __get_site_gateway(self, site_conf: _SiteConfig) -> _Gateway:
        if site_conf.gateway:
            return site_conf.gateway
        gate_conf = self.__gateway_config.get(site_conf.gateway_type.lower())
        if not gate_conf:
            raise ConfigError("Global {} gateway not config".format(site_conf.gateway_type.upper()))
        if site_conf.gateway_type.lower() == "nginx":
            gateway = _NGINXGateway(site_conf, gate_conf)
        elif site_conf.gateway_type.lower() == "slb":
            gateway = _SLBGateway(site_conf, gate_conf)
        else:
            raise ConfigError("Don't  support {} gateway".format(site_conf.gateway_type))
        site_conf.set_gateway(gateway)
        return gateway

    def get_notify(self) -> list:
        return self.__notifies

    def get_all_sites(self) -> set:
        sites = [_site_conf.site for _site_conf in self._site_configs]
        return set(sites)

    def get_site_config(self, site: str) -> _SiteConfig:
        for _site in self._site_configs:
            if _site.site == site:
                self.__get_site_gateway(_site)
                return _site
        raise ConfigError("site {} no config".format(site))


if __name__ == '__main__':
    config = AppConfig()
    # site_config是站点的配置信息
    site_config = config.get_site_config("test.bbb.com")
    print(site_config.servers)
