import time
import asyncio
from threading import Thread

import yaml
import aiohttp

from utils import Log, AsyncNotify
from action import RecycleActionThread, NgxActionThread

log = Log(__name__).get_loger()
log.level = 20
config_file = 'config.yml'
TOTAL = dict()
ACTIONED = dict()
DOWN = dict()
with open(config_file) as f:
    conf = yaml.safe_load(f)
nginxs = conf.get('nginxs')
notify = AsyncNotify(config_file)


class _AsyncCheckThread(Thread):
    """检查线程，后续还需要在主线程里面启动该线程"""
    def __init__(self, site: str, servers: list, timeout: int = 20) -> None:
        Thread.__init__(self)

        self.timeout = timeout
        self.site = site
        self.servers = servers if servers else []

    @staticmethod
    def _format_url(host: str) -> str:
        if host.startswith("http://") or host.startswith("https://"):
            return host
        return "http://{0}".format(host)

    @staticmethod
    async def _calculate_error(site: str, host: str) -> bool:
        """计算错误信息，并检查一分钟之内是否达到7次"""
        curr_time = time.time()
        if host in TOTAL:
            log.debug("主机记录已存在，检查当前异常域名站点是否之前也存在，存在计数加1")
            if site in TOTAL[host]:
                log.debug("相同主机的相同域名再次发生异常，检查上次异常时间是否在一分钟之内")
                err_time = TOTAL[host][site]['err_time']
                expire_time = err_time + (1 * 60)
                if expire_time >= curr_time:
                    log.debug("在一分钟之内的异常发生")
                    if TOTAL[host][site]['count'] > 7:
                        log.debug("一分钟之内累计达到7次，删除该KEY记录，执行Action动作设置为True")
                        del TOTAL[host][site]
                        return True
                    else:
                        log.debug("一分钟之内未达到7次，执行计数+1")
                        TOTAL[host][site]['count'] += 1
                        TOTAL[host][site]['err_time'] = curr_time
                else:
                    log.debug("异常时间是很早之前的时间,计数重置为1，更新时间")
                    TOTAL[host][site]['count'] = 1
                    TOTAL[host][site]['err_time'] = curr_time
            else:
                log.debug("主机记录已存在，并发现该主机有其他站点异常，开始记录")
                TOTAL[host][site] = dict(count=1, err_time=curr_time)
        else:
            log.debug("第一次发生异常，count初始化为1，并记录异常时间为当前时间")
            record = {
                site: {
                    'count': 1,
                    'err_time': curr_time
                }
            }
            TOTAL[host] = record
        return False

    @staticmethod
    async def _action(site: str, host: str, total_server: int) -> None:
        """action检查，检查该采取何种动作。回收还是摘除"""
        curr_time = time.time()
        expiry_time = time.time() + (3 * 60)
        if site in ACTIONED.get(host, {}):
            log.debug("执行记录中有记录，说明之前执行过回收动作，检查回收的时间是否在三分钟之内")
            action_time = ACTIONED[host][site]['action_time']
            if action_time > curr_time:
                log.info("三分钟这内执行过action操作,继续判断action的类型")
                if ACTIONED[host][site]['action_type'] == 'down':
                    recycle_t = RecycleActionThread(site, host)
                    recycle_t.start()
                    ACTIONED[host][site]['action_type'] = 'recycle'
                    ACTIONED[host][site]['action_time'] = expiry_time
                    await notify.send_msgs("主机: {0}\n站点: {1}\n动作: 回收".format(host, site))
                else:
                    log.info("三分钟内执行过摘取动作，此次忽略")
                    pass
            else:
                log.info("三分钟之前执行过action操作，此次一次介入，执行回收操作")
                r_thread = RecycleActionThread(site, host)
                r_thread.start()
                ACTIONED[host][site]['action_type'] = 'recycle'
                ACTIONED[host][site]['action_time'] = expiry_time
                await notify.send_msgs("主机: {0}\n站点: {1}\n动作: 回收".format(host, site))
        else:
            log.info("执行记录未发现有相关干预动作,开始检查摘除记录")
            count_down = len(DOWN.get(site, ()))
            if count_down <= (total_server / 2):
                log.info("下线记录中少于当前所有主机的一半，将对主机{}执行下线操作".format(host))
                for ngx in nginxs:
                    action_thread = NgxActionThread(ngx, site, host, 'down')
                    action_thread.start()
                DOWN.setdefault(site, set()).add(host)
                log.info("开始记录执行摘取操作，再次出现时，执行回收操作")
            else:
                log.info("当前有超过一半的主机已下线，对主机{}摘除操作将忽略".format(host))
                await notify.send_msgs("站点{}有超过一半的主机已下线！".format(site))
            if host not in ACTIONED:
                ACTIONED[host] = dict()
                ACTIONED[host][site] = {
                    'action_time': expiry_time,
                    'action_type': 'down'
                }
            await notify.send_msgs("主机: {0}\n站点: {1}\n动作: 摘除".format(host, site))

    async def _get_status(self, site: str, host: str) -> int:
        url = self._format_url(host)
        headers = dict(Host=site)
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=self.timeout) as resp:
                    return resp.status
        except Exception as e:
            log.warning(e)
            return 504

    async def check(self, site, host: str):
        """URL检测入口方法"""
        status = await self._get_status(site, host)
        if status >= 500:
            is_action = await self._calculate_error(site, host)
            if is_action:
                log.debug("一分钟之内已达到7次,开始执行Action流程判断。回收或者摘除动作")
                await self._action(site, host, len(self.servers))
        else:
            if site in TOTAL.get(host, []):
                log.info("删除之前的错误记录")
                del TOTAL[host][site]
            if ACTIONED.get(host, {}).get(site, {}).get('action_type'):
                await notify.send_msgs("主机: {0}\n站点: {1}\n操作: 恢复上线".format(host, site))
                log.info("之前有摘除操作，现在已恢复，将执行上线操作")
                for ngx in nginxs:
                    up_thread = NgxActionThread(ngx, site, host, 'up')
                    up_thread.start()
                DOWN[site].remove(host)
                log.info("执行上线完成，删除该KEY键")
                del ACTIONED[host][site]

    def start(self) -> None:
        global TOTAL
        global ACTIONED
        global DOWN
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        tasks = [
            asyncio.ensure_future(self.check(self.site, server))
            for server in self.servers
        ]
        if tasks:
            loop.run_until_complete(asyncio.wait(tasks))
        else:
            log.warning("{} 站点下无可检测服务器,请检查配置是否有误".format(self.site))
        loop.close()


class MainThread(Thread):
    def __init__(self, data: dict) -> None:
        Thread.__init__(self)
        self.data = data

    def start(self) -> None:
        for site, v in self.data.items():
            servers = v.get('servers')
            timeout = v.get('timeout')
            check_t = _AsyncCheckThread(site, servers, timeout)
            check_t.start()
        log.info("当前错误: {}, 摘除记录: {}".format(TOTAL, DOWN))
