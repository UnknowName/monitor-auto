import time
import asyncio

import aiohttp

from notify import AsyncNotify
from utils import NoServersConfigError
from utils import AppConfig, NginxAction, DomainConfig, MyLog

MAX_FAILED = 7
log = MyLog(__name__)


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
        self._action_obj = None

    # TODO 未达到最少要求的活跃主机时异常时，发送通知出来，或者说只要主机达到max_failed，就应该发送通知
    async def update(self, domain_record, status: int) -> None:
        now = time.time()
        # log.logger.debug("in HostRecord method------------------")
        # 异常在一分钟之内的，执行计数器加1
        if status > 400 and self._expire_time > now:
            # 如果是错误状态即可以执行动作了，达到最大失败次数后计数停止，发送通知
            # log.logger.debug("error status------------------")
            if self.is_error():
                await domain_record.add_error(self._host)
            # 还没达到触发动作的条件，计数继续加1
            else:
                self._count += 1
            # 当执行错误动作时，需要同时满足三个条件，以免进入反复重启的恶性循环,两次操作（重启/上线）间隔不能在一分钟之内
            if self.is_error() and self._can_safe_action() and domain_record.can_action(self._host):
                self._run_action("error")
                await self._init()
                # 更新非活跃主机
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
            # 加一层判断，防止整数溢出
            if self._count >= 1:
                self._count -= 1
            if self.is_ok():
                self._run_action("ok")
                await self._init()
                # 更新活跃主机记录
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
        if self._action_obj:
            self._action_obj.set_action_type(name)
            self._action_obj.start()
            self._action_obj = None
        else:
            # 如果为空，就需要重新初始化Action对象
            log.logger.warn("Action object is None")

    def __repr__(self):
        return "HostRecord(count={}, status={}, max={})".format(self._count, self._latest_status, self._max_failed)


# TODO 主机异常时，有两种状态，一种状态是下线，一种是异常
class DomainRecord(object):
    _notify = None

    def __init__(self, notify: AsyncNotify, config: DomainConfig = None):
        # 坑了好久，传递的是引用类型，不是值类型
        _servers = config.get_servers().copy()
        if not _servers:
            err_msg = """
            {} no server found! Maybe:
            1. Get Servers from remote nginx error occurd
            2. config.yml servers is blank
            """
            NoServersConfigError(err_msg.format(config.domain))
        else:
            self._actives = _servers
        self._inactives = set()
        self._total_server = len(self._actives)
        self._current_errors = set()
        self._domain = config.domain
        self.timeout = config.get("timeout")
        self._record = dict()
        self._max_failed = int(config.get("max_failed")) if config.get("max_failed") else MAX_FAILED
        self._max_inactive = int(config.get("max_inactive")) if config.get("max_inactive") else MAX_FAILED // 2
        self._nginxs = config.nginxs
        self._config = config.get("config_file") if config.get("config_file") else "/etc/nginx/conf.d/{}.conf".format(
                                                                                                        config.domain)
        # 通知对象
        if not self._notify:
            self._notify = notify

    @property
    def notify(self):
        return self._notify

    @property
    def domain(self):
        return self._domain

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
            # 异常逻辑
            if (host not in self._inactives) and (host not in self._record):
                # 这里说明不存在记录，初始化一个HostRecord
                host_record = _HostRecord(self._domain, host, self._max_failed)
                action = NginxAction(self._domain, host, nginxs=self._nginxs, config_file=self._config)
                host_record.add_action(action)
                host_record.add_notify(self._notify)
                self._record.setdefault(host, host_record)
            else:
                # 这里是之前有HostRecord记录，要获取之前的记录
                host_record = self._record.get(host)
                action = NginxAction(self._domain, host, nginxs=self._nginxs, config_file=self._config)
                host_record.add_action(action)
                host_record.add_notify(self._notify)
            await self._record[host].update(self, status)

        if self._record:
            log.logger.info("{} Errors {}".format(self._domain, self._record))


class AsyncCheck(object):
    def __init__(self, record: DomainRecord):
        # DomainRecord还是要从外面传进来，不然每次实例化后记数被重置
        self._record = record

    async def _get_status(self, host: str) -> (str, int):
        _timeout = self._record.timeout
        url = "http://{}".format(host)
        headers = dict(Host=self._record.domain)
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=_timeout)) as resp:
                    return host, resp.status
        except Exception as e:
            if not str(e):
                e = "Check Coroutine Timeout, It mean HTTP Get Timeout"
            log.logger.info(e)
            return host, 504

    async def check_servers(self, servers: list or set):
        """
        如果只返回错误的记录，那如何知道是否恢复了？还是说不管状态如何，它只是返回结果，不做判断
        """
        tasks = [self._get_status(host) for host in servers]
        dones, _ = await asyncio.wait(tasks)
        for done in dones:
            await self._record.calculate(done.result())


async def main():
    config = AppConfig("")
    print(config)


if __name__ == '__main__':
    asyncio.run(main())
    print(time.perf_counter())
