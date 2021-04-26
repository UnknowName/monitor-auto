import time
import asyncio
import logging
import logging.handlers
from typing import List, Dict
from abc import ABCMeta, abstractmethod

import aiohttp


class _Single(metaclass=ABCMeta):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance


class AbstractHostRecord(metaclass=ABCMeta):
    @abstractmethod
    def is_valid(self) -> bool:
        pass

    @abstractmethod
    def is_notify(self) -> bool:
        pass

    @abstractmethod
    def is_action(self) -> bool:
        pass

    @abstractmethod
    def update(self, v: int) -> None:
        pass


class AbstractAsyncNotify(metaclass=ABCMeta):
    @abstractmethod
    async def send_msg(self, msg: str) -> str:
        pass


class AbstractAsyncNotifies(metaclass=ABCMeta):
    @abstractmethod
    async def send_msgs(self, msg: str):
        pass


class _AsyncDDingNotify(AbstractAsyncNotify):
    _send_fmt = "https://oapi.dingtalk.com/robot/send?access_token={token}"

    def __init__(self, token: str) -> None:
        self.send_api = self._send_fmt.format(token=token)

    async def send_msg(self, msg: str) -> str:
        msgs = {
            'msgtype': 'text',
            'text': {
                'content': msg
            }
        }
        async with aiohttp.request('POST', self.send_api, json=msgs) as resp:
            return await resp.json()


class AsyncNotify(_Single, AbstractAsyncNotifies):
    def __init__(self, notify_confs: List[Dict]):
        self._notifys: List[AbstractAsyncNotify] = list()
        for notify_conf in notify_confs:
            if notify_conf.get("type", "") == "dingding":
                _notify = _AsyncDDingNotify(notify_conf.get("token", ""))
                self._notifys.append(_notify)

    async def send_msgs(self, msg: str):
        if self._notifys:
            tasks = [obj.send_msg(msg) for obj in self._notifys]
            await asyncio.wait(tasks)
        # 用户也可以不配置任何通知媒介
        pass

    def __repr__(self) -> str:
        return "AsyncNotify()"


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


class NotifyFactory(_Single):
    @staticmethod
    def get_notify(conf_data: List[Dict]) -> AbstractAsyncNotifies:
        return AsyncNotify(conf_data)


class HostRecord(AbstractHostRecord):
    def __init__(self, duration: int, auto_interval: int):
        self.count = 1
        self.duration = duration
        self.expire_time = time.time() + duration
        self.next_action_time = time.time() + auto_interval
        self.next_notify_time = time.time() + auto_interval

    def __repr__(self) -> str:
        return f"HostRecord(count={self.count})"

    def is_valid(self) -> bool:
        return time.time() <= self.expire_time

    def is_action(self) -> bool:
        return time.time() >= self.next_action_time

    def is_notify(self) -> bool:
        return self.is_action()

    def update(self, v: int) -> None:
        if self.is_valid():
            self.count += v
        else:
            self.count = v
        self.expire_time = time.time() + self.duration


