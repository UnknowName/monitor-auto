from typing import List

import yaml

from gateway import GatewayFactory
from utils import _Single, SimpleLog, NotifyFactory, AbstractAsyncNotifies

CONFIG_FILE = "config.yml"
DEFAULT_TIMEOUT = 5
DEFAULT_DURATION = 60
DEFAULT_MAX_FAILED = 7
DEFAULT_MAX_INACTIVE = 1
DEFAULT_INTER = 300
DEFAULT_PATH = "/"
DEFAULT_RECOVER = False
DEFAULT_CHECK_INTERVAL = 1
log = SimpleLog(__name__).log


class _DefaultConfig(_Single):
    def __init__(self, data: dict):
        self.max_failed = data.get("max_failed", DEFAULT_MAX_FAILED)
        self.duration = data.get("duration", DEFAULT_DURATION)
        self.timeout = data.get("timeout", DEFAULT_TIMEOUT)
        self.path = data.get("path", DEFAULT_PATH)
        self.auto_interval = data.get("auto_interval", DEFAULT_INTER)
        self.max_inactive = data.get("max_inactive", DEFAULT_MAX_INACTIVE)
        self.recover = data.get("recover", DEFAULT_RECOVER)
        self.check_interval = data.get("check_interval", DEFAULT_CHECK_INTERVAL)
        assert isinstance(self.max_failed, int) \
               and isinstance(self.duration, int) \
               and isinstance(self.timeout, int)   \
               and isinstance(self.auto_interval, int) \
               and isinstance(self.max_inactive, int) \
               and isinstance(self.recover, bool) \
               and isinstance(self.check_interval, int) \
               and isinstance(self.path, str), "Config file default section error"

    def __repr__(self) -> str:
        return f"_DefaultConfig({self.max_failed}, {self.timeout}, {self.duration})"


class _RecoverConfig(object):
    def __init__(self, data: dict):
        self.enable = data.get("enable", False)
        self.type = data.get("type", "None")
        self.name = data.get("name", "None")

    def __repr__(self) -> str:
        return f"AutoRecoverConfig(auto={self.enable}, type={self.type}, name={self.name})"


class SiteConfig(object):
    def __init__(self, site_data: dict, default: _DefaultConfig, gateway_data: dict):
        self.name = site_data.get("site")
        self._servers = set(site_data.get("servers", []))
        self._fetch = True if self._servers else False
        self.max_failed = site_data.get("max_failed") if site_data.get("max_failed") else default.max_failed
        self.duration = site_data.get("duration") if site_data.get("duration") else default.duration
        self.timeout = site_data.get("timeout") if site_data.get("timeout") else default.timeout
        self.path = site_data.get("path") if site_data.get("path") else default.path
        self.max_inactive = site_data.get("inactive") if site_data.get("inactive") else default.max_inactive
        self.auto_interval = site_data.get("auto_interval") if site_data.get("auto_interval") else default.auto_interval
        recover = site_data.get("recover") if site_data.get("recover") else default.recover
        if isinstance(recover, dict):
            self.recover = _RecoverConfig(recover)
        else:
            self.recover = _RecoverConfig(dict())
        self._gateway = GatewayFactory.get_gateway(site_data, gateway_data)

    def __repr__(self) -> str:
        return f"SiteConfig(name={self.name})"

    @property
    def gateway(self):
        return self._gateway

    @property
    def servers(self):
        if self._fetch:
            return self._servers
        self._servers = self._gateway.get_servers()
        self._fetch = True
        return self._servers


class AppConfig(_Single):
    def __init__(self, file_name: str = CONFIG_FILE):
        with open(file_name, encoding="utf8") as f:
            self._data = yaml.safe_load(f)
        self._default = _DefaultConfig(self._data.get("default", {}))
        self._gateway_conf = self._data.get("gateway", {})

    def __repr__(self) -> str:
        return f"AppConfig()"

    @property
    def check_interval(self) -> int:
        return self._default.check_interval

    @property
    def sites(self) -> List[SiteConfig]:
        result = list()
        for _site_data in self._data.get("sites", []):
            _site_config = SiteConfig(_site_data, self._default, self._gateway_conf)
            result.append(_site_config)
        return result

    @property
    def notify(self) -> AbstractAsyncNotifies:
        _notify_datas = self._data.get("notify", [])
        if not _notify_datas:
            log.warning("未配置任何通知媒介，出现异常时将无法发送任何通知信息")
        return NotifyFactory.get_notify(_notify_datas)


if __name__ == '__main__':
    conf = AppConfig()
    log.info(conf.notify)
    for site in conf.sites:
        log.info(f"{site.name}")
    # assert isinstance("2", int)
