import time
import asyncio
from typing import List, Tuple, Dict, Set

import aiohttp

from action import ActionFactory
from utils import SimpleLog, HostRecord
from config import AppConfig, SiteConfig


log = SimpleLog(__name__).log
conf = AppConfig("config.yml")
log.setLevel(conf.log_level)


def get_time() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class ErrorRecord(object):
    def __init__(self, host: str, status: int, action: str):
        self.host = host
        self.status = status
        self.action = action


class SiteCheck(object):
    def __init__(self, hostname: str, path: str, timeout: int, method: str, servers: List[str], data: dict = None):
        self.hostname = hostname
        self.path = path
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.method = method
        self.servers = servers
        self.data = data if data else {}

    async def _get_check(self, session: aiohttp.ClientSession, server: str) -> Tuple[int, str]:
        try:
            async with session.get(f"http://{server}{self.path}") as resp:
                if resp.status > 400:
                    log.info(f"http://{server}{self.path}, {resp.status}")
                return resp.status, server
        except asyncio.exceptions.TimeoutError:
            log.debug(f"http://{server}{self.path} check timeout")
            return 504, server

    async def _post_check(self, session: aiohttp.ClientSession, server: str) -> Tuple[int, str]:
        try:
            async with session.post(f"http://{server}{self.path}", data=self.data) as resp:
                if resp.status > 400:
                    log.info(f"http://{server}{self.path}, {resp.status}")
                return resp.status, server
        except asyncio.exceptions.TimeoutError:
            log.debug(f"http://{server}{self.path} check timeout")
            return 504, server

    async def _head_check(self, session: aiohttp.ClientSession, server: str) -> Tuple[int, str]:
        try:
            async with session.head(f"http://{server}{self.path}") as resp:
                if resp.status > 400:
                    log.info(f"http://{server}{self.path}, {resp.status}")
                return resp.status, server
        except asyncio.exceptions.TimeoutError:
            log.debug(f"http://{server}{self.path} check timeout")
            return 504, server

    async def check_servers(self):
        headers = dict(Host=self.hostname)
        async with aiohttp.ClientSession(headers=headers, timeout=self.timeout) as session:
            if self.method.lower() == "get":
                _tasks = [self._get_check(session, server) for server in self.servers]
            elif self.method.lower() == "post":
                _tasks = [self._post_check(session, server) for server in self.servers]
            elif self.method.lower() == "head":
                _tasks = [self._head_check(session, server) for server in self.servers]
            else:
                raise "no support check method"
            _dones, _ = await asyncio.wait(_tasks)
            results = [_done.result() for _done in _dones]
            return results


class AsyncCheck(object):
    @staticmethod
    async def _get_status(hostname: str, host: str, path: str, timeout: int) -> Tuple[int, str]:
        url = "http://{}{}".format(host, path)
        headers = dict(Host=hostname)
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.get(url) as resp:
                    return resp.status, host
        except Exception as e:
            if not str(e):
                e = "Check Coroutine Timeout, It mean HTTP Get Timeout"
            log.warning(e)
            return 504, host

    async def checks(self, hostname: str, path: str, servers: Set[str], timeout: int) -> List[Tuple[int, str]]:
        _tasks = [self._get_status(hostname, _host, path, timeout) for _host in servers]
        _dones, _ = await asyncio.wait(_tasks)
        results = [_done.result() for _done in _dones]
        return results


class SiteRecord(object):
    def __init__(self, _site: SiteConfig):
        self.conf = _site
        self.name = _site.name
        self.max_failed = _site.max_failed
        self.auto_inter = _site.auto_interval
        self.max_inactive = _site.max_inactive
        if not self.max_inactive:
            self.max_inactive = len(_site.servers) // 2
        # 已经下线的主机存入self._inactive
        self._inactive = set()
        # self._record有所有曾经异常的记录
        self._record: Dict[str: HostRecord] = dict()

    def __repr__(self) -> str:
        return "SiteRecord(name={},errors={})".format(self.name, self._record)

    async def update(self, _results: List[Tuple[int, str]]):
        for _result in _results:
            status, host = _result
            if status > 400:
                # 判断是不是第一次发生
                if host in self._record:
                    # 之前有记录，需要更新
                    if host in self._inactive:
                        # 已下线，更新的计数为0，实际只更新了时间
                        self._record[host].update(0)
                    else:
                        # 还未下线，继续更新记录
                        if self._record[host].count < self.max_failed:
                            # 防止整数溢出，只有小于才更新
                            self._record[host].update(1)
                        else:
                            self._record[host].update(0)
                else:
                    # 初次，之前未记录
                    self._record[host] = HostRecord(self.conf.duration, self.conf.auto_interval)
                # 更新最后状态
                self._record[host].set_status(status)
            else:
                # 状态码是正常的情况,如果存在，那就一直减少到0
                if host in self._record and self._record[host].count > 0:
                    self._record[host].update(-1)
                pass
        # 其他情况就不管
        log.info(self._record)

    def get_error_hosts(self) -> Set[str]:
        results = set()
        for host, record in self._record.items():
            if record.count >= self.max_failed:
                results.add(host)
        results.update(self._inactive)
        return results

    async def get_results(self) -> List[ErrorRecord]:
        results: List[ErrorRecord] = list()
        for host, record in self._record.copy().items():
            if record.count >= self.max_failed:
                log.info("{}超过最大失败的次数,检查是否满足下线条件".format(host))
                if host in self._inactive:
                    log.info("{}已下线的主机还未恢复，等待下个动作的周期时间再执行相关动作".format(host))
                    if record.is_action():
                        record.next_action_time = time.time() + self.auto_inter
                        error_record = ErrorRecord(host, record.last_status, "offline")
                        results.append(error_record)
                    else:
                        log.info("{}不满足条件: 操作的间隔时间未到，忽略此次动作".format(host))
                else:
                    if self.max_inactive >= len(self._inactive) + 1:
                        log.info("{}满足条件：下线主机数在范围内".format(host))
                        record.next_action_time = time.time() + self.auto_inter
                        self._inactive.add(host)
                        error_record = ErrorRecord(host, record.last_status, "offline")
                        results.append(error_record)
                    else:
                        log.info("{}不满足条件: 下线主机过多".format(host))
                        # 通知加一个间隔时间，防止太频繁
                        if record.is_notify():
                            record.next_notify_time = time.time() + self.auto_inter
                            error_record = ErrorRecord(host, record.last_status, "notify")
                            results.append(error_record)
            else:
                # 记录没有大于，有可能是等于0或者1-7，更新计数
                if record.count == 0 and host in self._inactive:
                    log.info("{}之前异常，现在恢复。将执行上线".format(host))
                    self._inactive.remove(host)
                    ok_record = ErrorRecord(host, record.last_status, "online")
                    results.append(ok_record)
                if record.count == 0:
                    del self._record[host]
        return results


async def main():
    log.info("程序启动....")
    notify = conf.notify
    sites = conf.sites
    # 检查结果记录
    records: Dict[str, SiteRecord] = {site.name: SiteRecord(site) for site in sites}
    msg_fmt = "Time:\t{time}\nDomain:\t{site}\nErrHosts:\t{hosts}\nInfo:\t{info},latest status {status}\n"
    "TotalError:\t{total}"
    while True:
        for site in sites:
            if not site.servers:
                log.warning("{} 无待检测服务器".format(site.name))
                continue
            # task = AsyncCheck().checks(site.name, site.path, site.servers, site.timeout)
            task = SiteCheck(hostname=site.name, path=site.path, timeout=site.timeout,
                             method=site.method, servers=site.servers, data=site.post_data).check_servers()
            result = await task
            await records[site.name].update(result)
            check_results = await records[site.name].get_results()
            error_hosts = records[site.name].get_error_hosts()
            hosts = "\n\t{}".format("\n\t".join(error_hosts))
            for err_record in check_results:
                if err_record.action == "offline":
                    if site.recover.enable:
                        log.info(f"使用网关{site.gateway}对主机{err_record.host}下线")
                        site.gateway.change_server_offline(err_record.host)
                        action = ActionFactory.create_action(site, err_record.host)
                        log.info("启动Action线程....")
                        action.start()
                    if not site.recover.enable:
                        site.recover.type = "error occur"
                    log.info(f"发送{err_record.host}异常通知信息")
                    await notify.send_msgs(
                        msg_fmt.format(
                            time=get_time(), site=site.name, hosts=hosts,
                            info=f"{err_record.host} {site.recover.type}",
                            status=f"{err_record.status}",
                            total=len(error_hosts)
                        )
                    )
                elif err_record.action == "notify":
                    log.info(f"发送主机{err_record.host}异常通知信息")
                    await notify.send_msgs(
                        msg_fmt.format(
                            time=get_time(), site=site.name, hosts=hosts,
                            info=f"{err_record.host} Error Occur",
                            status=f"{err_record.status}",
                            total=len(error_hosts)
                        )
                    )
                elif err_record.action == "online":
                    if site.recover.enable:
                        log.info(f"通过网关{site.gateway}对主机{err_record.host}进行上线")
                        site.gateway.change_server_online(err_record.host)
                    # 恢复后发送信息
                    await notify.send_msgs(
                        msg_fmt.format(
                            time=get_time(), site=site.name, hosts=hosts, status=200,
                            info=f"{err_record.host} Recover", total=len(error_hosts)
                        )
                    )
            # 主机上/下线，重启站点动作在这里完成，避免SiteConfig对象到处传
        time.sleep(conf.check_interval)


if __name__ == "__main__":
    asyncio.run(main())
