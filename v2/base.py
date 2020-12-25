"""
基础类，不依赖程序本身的任何模块，用来给其他模块共享使用
"""
import time
import logging
import logging.handlers
from abc import ABCMeta

DEFAULT = 1


class ConfigError(Exception):
    def __init__(self, msg: str):
        Exception(msg)


class CommandError(Exception):
    def __init__(self, msg: str):
        Exception(msg)


class NoSupportGatewayError(Exception):
    pass


class _Single(metaclass=ABCMeta):
    """
    单实例基类，要实现单实例模式时，继承该类
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance


class SimpleLog(_Single):
    """
    日志模块简单封装下
    """
    _fmt = logging.Formatter(
        '%(asctime)s %(module)s %(threadName)s %(levelname)s %(message)s'
    )

    def __init__(self, name, filename=None):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(self._fmt)
        self._logger.addHandler(ch)
        if filename:
            fh = logging.handlers.TimedRotatingFileHandler(filename, 'D', 1, 7)
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(self._fmt)
            self._logger.addHandler(fh)

    @property
    def log(self):
        return self._logger


class _NGINXConfig(_Single):
    def __init__(self, data: dict):
        self._hosts = data.get("hosts")
        if not self._hosts:
            raise ConfigError("NGINX网关配置有误，地址为空")
        self._username = data.get("username", "root")

    @property
    def hosts(self) -> list:
        return self._hosts

    @property
    def username(self) -> str:
        return self._username

    def __repr__(self) -> str:
        return "NGINXConfig(hosts={}, ssh_username={})".format(self._hosts, self._username)


class _SLBConfig(_Single):
    def __init__(self, data: dict):
        self._key = data.get("key")
        self._secret = data.get("secret")
        self._region = data.get("region")
        if not self._key or not self._secret or not self._region:
            raise ConfigError("SLB配置有误，key/secret/region均为必须项")

    @property
    def key(self) -> str:
        return self._key

    @property
    def secret(self) -> str:
        return self._secret

    @property
    def region(self) -> str:
        return self._region

    def __repr__(self) -> str:
        return "SLBConfig(key=***,secret=****,region={})".format(self._region)
