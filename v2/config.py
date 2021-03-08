from typing import Set

import yaml

from objects import AsyncNotify
from models import AbstractGateway, AbstractSiteConfig
from gateway import _NGINXGateway, _SLBGateway
from base import _Single, SimpleLog, ConfigError, _SLBConfig, _NGINXConfig

CONFIG_FILE = "config.yml"
DEFAULT_TIMEOUT = 5
DEFAULT_MAX_FAILED = 7
DEFAULT_INTER = 300
log = SimpleLog(__name__).log


class _AutoRecoverConfig(object):
    def __init__(self, data: dict):
        self.enable = data.get("enable", False)
        self.type = data.get("type")
        self.name = data.get("name")

    def __repr__(self) -> str:
        return "AutoRecoverConfig(auto={}, type={}, name={})".format(self.enable, self.type, self.name)


class _SiteConfig(AbstractSiteConfig):
    def __init__(self, data: dict):
        self._name = data.get("site")
        if not self.name:
            raise ConfigError("配置有误,name属性必须配置")
        auto_data = data.get("auto_recover")
        if not isinstance(auto_data, dict):
            raise ConfigError("{}的auto_recover配置有误!".format(self.name))
        self.auto = _AutoRecoverConfig(auto_data)
        self.max_failed = data.get("max_failed") if data.get("max_failed") else DEFAULT_MAX_FAILED
        self._timeout = data.get("timeout") if data.get("timeout") else DEFAULT_TIMEOUT
        self.max_inactive = data.get("max_inactive", None)
        self._servers = set(data.get("servers", {}))
        self._path = data.get("path", "/")
        self.auto_inter = data.get("auto_inter") if data.get("auto_inter") else DEFAULT_INTER
        self._gateway = None
        self._fetch = False
        self._gateway_kwargs = None
        self.gateway_type = data.get("gateway_type", "").upper()
        if self.auto.enable and not self.gateway_type:
            raise ConfigError("{}启用了自动恢复时，网关信息必须配置".format(self.name))
        if self.gateway_type == "NGINX":
            self.config_file = data.get("config_file", None)
            self.backend_port = data.get("backend_port", 0)
            self._gateway_kwargs = dict(config_file=self.config_file)
            if not self.config_file or not self.backend_port:
                raise ConfigError("{}使用NGINX网关类型时，config_file与backend_port为必须项".format(self.name))
        elif self.gateway_type == "SLB":
            self.slb_id = data.get("slb_id")
            self.slb_listen_port = data.get("slb_listen_port")
            self._gateway_kwargs = dict(slb_id=self.slb_id, slb_listen_port=self.slb_listen_port)
            if not self.slb_id or not self.slb_listen_port:
                raise ConfigError("{}使用SLB网关类型时，slb_id与slb_listen_port为必须项".format(self.name))
        else:
            raise ConfigError("{}配置了不支持的网关类型".format(self.name))

    @property
    def name(self) -> str:
        return self._name

    @property
    def timeout(self) -> int:
        return self._timeout

    @property
    def path(self) -> str:
        return self._path

    @property
    def gateway(self) -> AbstractGateway:
        return self._gateway

    @property
    def gateway_kwargs(self) -> dict:
        return self._gateway_kwargs

    @property
    def servers(self) -> Set[str]:
        if not self._servers and not self._fetch:
            gateway_type = self.gateway_type.lower()
            if gateway_type == "nginx":
                self._servers = self.gateway.get_servers(config_file=self.config_file, backend_port=self.backend_port)
            elif gateway_type == "slb":
                self._servers = self.gateway.get_servers(slb_id=self.slb_id, listen_port=self.slb_listen_port)
            # 标记已从网关取过数据，免得一直远程去取
            self._fetch = True
        return self._servers

    def set_gateway(self, gateway: AbstractGateway) -> None:
        self._gateway = gateway

    def __repr__(self) -> str:
        return "SiteConfig(name={})".format(self.name, self.gateway_type)


class AppConfig(_Single):
    def __init__(self, file_name: str = CONFIG_FILE):
        with open(file_name, encoding="utf8") as f:
            self._data = yaml.safe_load(f)

    def __repr__(self) -> str:
        return "AppConfig(default=conf.yaml)"

    @property
    def nginx(self) -> _NGINXGateway:
        ngx_conf = _NGINXConfig(self._data.get("gateway", {}).get("nginx"))
        return _NGINXGateway(ngx_conf)

    @property
    def slb(self) -> _SLBGateway:
        slb_conf = _SLBConfig(self._data.get("gateway", {}).get("slb"))
        return _SLBGateway(slb_conf)

    @property
    def sites(self) -> Set[_SiteConfig]:
        result = set()
        for _site_data in self._data.get("sites", []):
            _site = _SiteConfig(_site_data)
            _site_gateway = getattr(self, _site.gateway_type.lower())
            _site.set_gateway(_site_gateway)
            result.add(_site)
        return result

    @property
    def notify(self) -> AsyncNotify:
        _notify_data = self._data.get("notify", [])
        if not _notify_data:
            log.warning("未配置任何通知媒介，出现异常时将无法发送任何通知信息")
        return AsyncNotify(_notify_data)


if __name__ == '__main__':
    conf = AppConfig()
    for site in conf.sites:
        print(site.max_failed)
