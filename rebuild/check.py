import time
import asyncio

import aiohttp

from notify import AsyncNotify
from utils import NoServersConfigError
from utils import AppConfig, NginxAction, Option


class _HostRecord(object):
    def __init__(self, domain: str, host: str, max_failed: int):
        self._host = host
        self._domain = domain
        self._max_failed = max_failed
        self._count = 0
        self._latest_status = None
        self._action_obj = None
        self._notify = None
        self._expire_time = time.time() + 60
        self._action_time = time.time()

    def add_notify(self, notify: AsyncNotify) -> None:
        self._notify = notify

    async def _init(self) -> None:
        self._count = 0
        self._action_time = time.time() + 100

    # TODO 未达到最少要求的活跃主机时异常时，发送通知出来，或者说只要主机达到max_failed，就应该发送通知
    # TODO 目前是只有执行了相关动作后才会有通知发出
    async def update(self, domain_record, status: int) -> None:
        now = time.time()
        # 异常在一分钟之内的，执行计数器加1
        if status > 400 and self._expire_time > now:
            # 如果是错误状态，计数停止，发送通知
            if self.is_error():
                await domain_record.add_error(self._host)
            # 非在错误状态中，计数加1
            else:
                self._count += 1
            # 当执行错误动作时，需要同时满足三个条件，以免进入反复重启的恶性循环,两次操作（重启/上线）间隔不能在一分钟之内
            if self.is_error() and self._can_safe_action() and domain_record.can_action(self._host):
                self._run_action("error")
                await self._init()
                domain_record.add_inactive(self._host)
                msg = "Time:\t{time}\nDomain:\t{domain}\nHost:\t{host}\nInfo:\t{action}\nTotalError:\t{total}".format(
                    time=time.strftime("%Y-%m-%d %H:%M:%S"), domain=self._domain,
                    host=self._host, action="Restart IIS Web Site", total=domain_record.get_error()
                )
                await self._notify.send_msgs(msg)
        elif status > 400 and self._expire_time < now:
            # 异常不是在一分钟之内连续发生，重新计数
            self._count = 1
        else:
            # 正常状态码就不考虑时间,将之前的计数减一，减到0时会触发上线动作
            self._count -= 1
            if self.is_ok():
                self._run_action("ok")
                await self._init()
                domain_record.add_active(self._host)
                msg = "Time:\t{time}\nDomain:\t{domain}\nHost:\t{host}\nInfo:\t{action}\nTotalError:\t{total}".format(
                    time=time.strftime("%Y-%m-%d %H:%M:%S"), domain=self._domain,
                    host=self._host, action="Recover", total=domain_record.get_error()
                )
                await self._notify.send_msgs(msg)
        # 最后都要更新最近状态和失效时间,将虽然异常，但没有执行动作的主机写回DomainRecord的total_error
        self._latest_status = status
        self._expire_time = now + (1 * 60)

    def is_error(self) -> bool:
        return self._count > self._max_failed

    def is_ok(self) -> bool:
        return self._count <= 0

    def add_action(self, action: NginxAction) -> None:
        self._action_obj = action

    # TODO 后面要取消这个方法，因为当达到max_failed时，不执行动作，但是要发送通知
    def _is_action(self, name: str) -> bool:
        if name == "error":
            return self._count >= self._max_failed
        elif name == "ok":
            return self._count <= 0
        return False

    def _can_safe_action(self) -> bool:
        # 限制两次动作的间隔时间不能在100秒之内
        now = time.time()
        if self._action_time > now:
            return False
        return True

    def _run_action(self, name: str) -> None:
        self._action_obj.set_action_type(name)
        self._action_obj.start()

    def __repr__(self):
        return "HostRecord(count={}, status={}, max={})".format(self._count, self._latest_status, self._max_failed)


# TODO 主机异常时，有两种状态，一种状态是下线，一种是异常
class DomainRecord(object):
    _notify = None

    def __init__(self, domain: str, option: Option):
        # 初始化时，活跃的主机就是配置文件的主机，这里是带端口的如: 128.0.255.2:80
        _hosts = option.get_attr(domain, "servers")
        if not _hosts:
            NoServersConfigError("the domain no servers in config.yml")
        else:
            self._actives = set(_hosts)
        self._inactives = set()
        self._total_server = len(self._actives)
        self._current_errors = set()
        self._domain = domain
        self._record = dict()
        self._max_failed = int(option.get_attr(domain, "max_failed"))
        self._max_inactive = int(option.get_attr(domain, "max_inactive"))
        self._nginxs = option.get_nginxs()
        # 通知对象
        if not self._notify:
            self._notify = option.get_notify()

    def __repr__(self):
        return "DomainRecord(domain={}, max_failed={}, {})".format(self._domain, self._max_failed, self._max_inactive)

    # 不主动调用，当调用add_error时触发
    async def _report_error(self, host: str) -> None:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        msg = "Time:  {time}\nDomain:  {domain}\nInfo: {host} Error Occur\nErrorHosts:  \n{hosts}".format(
            time=now, domain=self._domain, host=host, hosts="\n".join(self._current_errors)
        )
        await self._notify.send_msgs(msg)

    def add_inactive(self, host: str) -> None:
        self._current_errors.add(host)
        self._inactives.add(host)
        if host in self._actives:
            self._actives.remove(host)

    def get_error(self) -> int:
        return len(self._current_errors)

    def add_active(self, host: str) -> None:
        self._actives.add(host)
        if host in self._inactives:
            self._inactives.remove(host)
        if host in self._current_errors:
            self._current_errors.remove(host)

    async def add_error(self, host: str) -> None:
        if host not in self._current_errors:
            self._current_errors.add(host)
            await self._report_error(host)

    def can_action(self, host: str) -> bool:
        # 如果是之前已经下线的主机，直接返回True
        if host in self._inactives:
            return True
        # 因为本次要下线一台机器，所以要加1
        elif (len(self._inactives) + 1) > self._max_inactive:
            return False
        return True

    async def calculate(self, check_result: tuple) -> None:
        host, status = check_result
        if (status < 400) and (host not in self._current_errors) and (host not in self._inactives):
            # 说明正常，删除之前记录的对象，节省内存
            try:
                del self._record[host]
            except KeyError:
                pass
        else:
            if (host not in self._inactives) and (host not in self._record):
                host_record = _HostRecord(self._domain, host, self._max_failed)
                action = NginxAction(self._domain, host, nginxs=self._nginxs)
                host_record.add_action(action)
                host_record.add_notify(self._notify)
                self._record.setdefault(host, host_record)
            await self._record[host].update(self, status)
        if self._record:
            print("{} Current Error {}".format(self._domain, self._record))


class AsyncCheck(object):
    def __init__(self, domain: str, record: DomainRecord, option: Option):
        self._domain = domain
        self._notify = option.get_notify()
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
            await self._record.calculate(done.result())


async def main():
    config = AppConfig("")
    op = Option(config)
    domain = 'www.aaa.com'
    x = op.get_attr(domain, "max_inactive")
    print(x)


if __name__ == '__main__':
    asyncio.run(main())
    print(time.perf_counter())
