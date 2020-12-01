import time

from config import _SiteConfig
from notify import AsyncNotify
from utils import MyLog, _RestartIISAction

log = MyLog(__name__).logger


def get_time() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class _HostRecord(object):
    def __init__(self, host: str):
        self.host = host
        self.count = 1
        self.expire_time = time.time() + 60
        self.action_time = None

    def __repr__(self):
        return "HostRecord({}, {})".format(self.host, self.count)


# 通过观察者模式，作为AsyncCheck对象的一个属性
# 该对象是从外部传进来的，只会初始化一次
class SiteRecord(object):
    def __init__(self, site_conf: _SiteConfig, notify: AsyncNotify):
        self._conf = site_conf
        self._notify = notify
        # 已执行下线的主机
        self._inactive = set()
        # 错误信息记录对象
        self._record = dict()
        # 当前正发生错误的主机记录，但没有执行下线动作
        self._errors = set()
        # 记录最近一次的错误总数，根据该值决定是否发送新通知
        self._latest_total = 0

    def __repr__(self):
        return "SiteRecord(site={}, errors={}, inactive={})".format(self._conf.site, self._errors, self._inactive)

    async def __add_inactive(self, host: str):
        self._inactive.add(host)
        if host in self._errors:
            self._errors.remove(host)

    def get_total(self) -> int:
        return len(self._inactive) if not len(self._errors) else len(self._inactive | self._errors)

    async def calculate(self, result: tuple):
        host, status = result
        if status >= 400:
            await self.__calculate_error(host)
        else:
            await self.__calculate_ok(host)
        if self._conf.auto:
            await self._action()
        # log.info(self)

    async def __calculate_error(self, host: str):
        # 当前发生错误且也已下线
        if (host in self._inactive) and (host in self._record):
            log.info("{} 已下线，此次只更新异常时间".format(host))
            log.info(self)
        # 只在error记录中，不在下线记录中，判断时间是否在一分钟之内，是就加1并更新时间
        elif host in self._record and self._record[host].expire_time >= time.time():
            log.info("{} 一分钟之内连续发生,执行计数累加".format(host))
            if self._record[host].count < self._conf.max_failed:
                self._record[host].count += 1
                log.info(self)
        elif host in self._record and self._record[host].expire_time < time.time():
            log.info("{} 一分钟之前的记录，重新计数".format(host))
            self._record[host].count = 1
            log.info(self)
        else:
            # 这种情况就是初次发生，初始化HostRecord记录
            host_record = _HostRecord(host)
            self._record[host] = host_record
        # 无论如何，最终都要更新时间
        self._record[host].expire_time = time.time() + 60

    async def __calculate_ok(self, host: str):
        # 如果之前存在异常记录，那么self._record必然会有记录
        if host in self._record and self._record[host].count > 0:
            self._record[host].count -= 1
            self._record[host].expire_time = time.time() + 60
        # 至于是否恢复上线，由后续的self._action()方法实现

    async def __notify(self, info: str):
        msg_fmt = "Time:\t{time}\nDomain:\t{site}\nErrHosts:\t{hosts}\nInfo:\t{info}\nTotalError:\t{total}"
        hosts = "\n\t{}".format("\n\t".join(self._inactive | self._errors))
        if not hosts.strip():
            hosts = "None"
        msg = msg_fmt.format(
            time=get_time(), site=self._conf.site, hosts=hosts, info=info, total=self.get_total()
        )
        log.info("发送通知消息: {}".format(msg))
        await self._notify.send_msgs(msg)

    async def _action(self):
        for host, record in self._record.copy().items():
            # 先判断是执行何种类型的操作，如果是恢复，就无需要考虑时间因素
            if (host in self._inactive or host in self._errors) and record.count <= 0:
                # log.info("之前主机被干预下线，这里要恢复上线动作")
                if host in self._inactive:
                    self._inactive.remove(host)
                if host in self._errors:
                    self._errors.remove(host)
                # Step1: 网关层恢复上线即可
                self._conf.gateway.change_server(host, "ok")
                # Step2: 发送通知信息
                await self.__notify("{} Recover".format(host))
            elif record.count >= self._conf.max_failed and (not record.action_time or record.action_time < time.time()):
                self._latest_total = self.get_total()
                if len(self._inactive) + 1 <= self._conf.max_inactive:
                    # log.info("达到最大失败次数，将执行下线动作")
                    record.action_time = time.time() + self._conf.auto_inter
                    await self.__add_inactive(host)
                    # Step1: 网关层上下服务器
                    self._conf.gateway.change_server(host, "error")
                    # Step2: 针对该主机的操作
                    error_action = _RestartIISAction(self._conf.site, host)
                    error_action.start()
                    # Step3: 更新action时间
                    record.action_time = time.time() + (self._conf.auto_inter * 60)
                    # Step4: 发送通知信息
                    await self.__notify("Restart {} IIS WebSite".format(host))
                else:
                    # log.info("虽然主机产生了异常，但是不允许下线太多主机，但要发送通知出来")
                    self._errors.add(host)
                    # 当异常计数有变化时才发送通知信息
                    if self._latest_total != self.get_total():
                        await self.__notify("{} error occur".format(host))
            # 其它就为未触及触发条件，如间隔时间未到，计数未达到等


if __name__ == '__main__':
    lst = [_HostRecord("test")]
    for r in lst:
        r.count += 1
    print(lst)
