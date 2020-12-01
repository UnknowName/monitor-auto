import time
import aiohttp

from utils import MyLog
from record import SiteRecord
from notify import AsyncNotify
from config import AppConfig, _SiteConfig

log = MyLog(__name__).logger


class AsyncCheck(object):
    def __init__(self, site_config: _SiteConfig):
        self._conf = site_config
        self._site_record = None

    def __repr__(self) -> str:
        return "AsyncCheck(site={}, timeout={})".format(self._conf.site, self._conf.timeout)

    async def add_site_record(self, record: SiteRecord):
        self._site_record = record

    # 最终action的对象是加到SiteRecord中
    async def add_action(self, obj: SiteRecord):
        await self._site_record.add_action(obj)

    async def _get_status(self, host: str, path: str) -> (str, int):
        url = "http://{}{}".format(host, path)
        headers = dict(Host=self._conf.site)
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=self._conf.timeout)) as resp:
                    return host, resp.status
        except Exception as e:
            if not str(e):
                e = "Check Coroutine Timeout, It mean HTTP Get Timeout"
            log.info(e)
            return host, 504

    async def check_servers(self, servers: set, path: str) -> None:
        if not self._site_record:
            raise Exception("Pleas call add_site_record() method before check_servers()")
        tasks = [self._get_status(host, path) for host in servers]
        dones, _ = await asyncio.wait(tasks)
        for done in dones:
            await self._site_record.calculate(done.result())
        # return set([done.result() for done in dones])


async def main():
    config = AppConfig("config.yml")
    sites = config.get_all_sites()
    site_configs = [config.get_site_config(site) for site in sites]
    notify = AsyncNotify(config.get_notify())
    # SiteRecord要在这里初始化后，不然每次循环后计数被重置
    record = {site: SiteRecord(config.get_site_config(site), notify) for site in sites}
    while True:
        tasks = list()
        for site_config in site_configs:
            servers = site_config.servers
            log.info("Site: {} check servers {}".format(site_config.site, servers))
            if servers:
                t = AsyncCheck(site_config)
                # 将记录对象作为观察者添加进AsyncCheck对象
                await t.add_site_record(record[site_config.site])
                tasks.append(t.check_servers(servers, site_config.path))
            else:
                log.warning("{} not found servers".format(site_config.site))
        await asyncio.wait(tasks)
        time.sleep(1)


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
