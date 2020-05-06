import time
import asyncio

import aiohttp

from rebuild.utils import NoServersConfigError
from rebuild.utils import AppConfig, _BaseActionThread, NginxAction, Option


class _HostRecord(object):
    def __init__(self, host: str, max_failed: int):
        self._host = host
        self._max_failed = max_failed
        self._count = 0
        # 一开始主机为在线状态
        self._active = True
        self._actioned = False
        self._latest_status = None
        self._actions = {}
        self._action_obj = None
        self._expire_time = time.time() + 60

    def update(self, domain_record, status: int) -> None:
        now = time.time()
        # 异常在一分钟之内的，执行计数器加1
        if status > 400 and self._expire_time > now:
            self._count += 1
            # 当执行错误动作时，需要同时满足两个条件
            if self._is_action("error") and domain_record.can_action(self._host):
                self._run_action("error")
                self._actioned = True
                # 计数器重置为0
                self._count = 0
                # 从活跃主机列表中移除掉该主机
                domain_record.add_inactive(self._host)
        elif status > 400 and self._expire_time < now:
            # 异常不是在一分钟之内连续发生，重新计数
            self._count = 1
        else:
            # 正常状态码就不考虑时间,直接重置为0即可
            self._count = 0
            if self._is_action("ok"):
                self._run_action("ok")
                self._actioned = False
                # 上线后，在非活跃主机列表中移除该主机
                domain_record.add_active(self._host)
        self._latest_status = status
        self._expire_time = now + (1 * 60)

    def add_action(self, action: _BaseActionThread) -> None:
        self._action_obj = action

    def _is_action(self, name: str) -> bool:
        if name == "error":
            return self._count >= self._max_failed
        elif name == "ok":
            return self._count <= 0 and self._actioned
        return False

    def _run_action(self, name: str) -> None:
        """
        obj = self._actions.get(name)
        if obj:
            obj.start()
        else:
            print("error 异常对应的动作尚未注册")
        # 动作执行成功后，重新初始化计数
        self._count = 0
        """
        self._action_obj.set_action_type(name)
        self._action_obj.start()

    def __repr__(self):
        return "HostRecord(count={}, status={}, max={})".format(self._count, self._latest_status, self._max_failed)


class DomainRecord(object):
    def __init__(self, domain: str, option: Option):
        # 初始化时，活跃的主机就是配置文件的主机，这里是带端口的如: 128.0.255.2:80
        _hosts = option.get_attr(domain, "servers")
        if not _hosts:
            NoServersConfigError("the domain no servers in config.yml")
        else:
            self._actives = set(_hosts)
        # 当前非活跃的主机，表示已下线的
        self._inactives = set()
        self._domain = domain
        self._errors = dict()
        self._max_failed = int(option.get_attr(domain, "max_failed"))
        self._min_active = int(option.get_attr(domain, "min_active"))
        self._nginxs = option.get_nginxs()

    def __repr__(self):
        return "DomainRecord(domain={}, max_failed={}, {})".format(self._domain, self._max_failed, self._min_active)

    def add_active(self, host: str):
        self._actives.add(host)
        if host in self._inactives:
            self._inactives.remove(host)

    def add_inactive(self, host: str):
        self._inactives.add(host)
        if host in self._actives:
            self._actives.remove(host)

    def get_errors(self):
        return self._errors

    def can_action(self, host: str) -> bool:
        # 如果主机已经下线，如就不管是不是少于最少主机，直接可以执行动作了
        if host in self._inactives:
            return True
        # 如果主机不在下线主机列表中，则判断当前活跃主机数是不是少于最小要求
        return len(self._actives) > self._min_active

    def calculate(self, check_result: tuple) -> None:
        host, status = check_result
        if host not in self._errors:
            host_record = _HostRecord(host, self._max_failed)
            action = NginxAction(self._domain, host, nginxs=self._nginxs)
            host_record.add_action(action)
            self._errors.setdefault(host, host_record)
        self._errors[host].update(self, status)
        print(self._errors)
        # print("*" * 100)
        # print(self._actives, self._inactives)


class AsyncCheck(object):
    def __init__(self, domain: str, record: DomainRecord, option: Option):
        self._domain = domain
        self._config = option.get_config(domain)
        # DomainRecord还是要从外面传进来，不然每次实例化后记数被重置
        self._record = record

    async def _get_status(self, host: str) -> (str, int):
        _timeout = self._config.get("timeout")
        url = "http://{}".format(host)
        headers = dict(Host=self._domain)
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=_timeout)) as resp:
                    return host, resp.status
        except Exception as e:
            if not str(e):
                e = "Check Coroutine Timeout, It mean HTTP Get Timeout"
            print(e)
            return host, 504

    async def check_servers(self):
        """
        如果只返回错误的记录，那如何知道是否恢复了？还是说不管状态如何，它只是返回结果，不做判断
        """
        tasks = [self._get_status(host) for host in self._config.get("servers")]
        dones, _ = await asyncio.wait(tasks)
        for done in dones:
            self._record.calculate(done.result())


async def main():
    config = AppConfig("")
    op = Option(config)
    domain = 'www.aaa.com'
    t = AsyncCheck(domain, DomainRecord("dev.siss.io", op), op)
    result = await t.check_servers()


if __name__ == '__main__':
    asyncio.run(main())
    print(time.perf_counter())
    """
    record = Record("dev.siss.io")
    print(record)
    record2 = Record("dev.siss.io")
    print(record2)
    """