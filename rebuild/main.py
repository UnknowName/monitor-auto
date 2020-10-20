import asyncio

from utils import AppConfig, MyLog
from check import DomainRecord, AsyncCheck
from notify import AsyncNotify

log = MyLog(__name__)


# TODO 动作执行时加队列！
async def main():
    app_config = AppConfig("config.yml")
    notify = AsyncNotify(app_config.get_attrs("notify"))
    domains = app_config.get_attrs("sites")
    sites = [domain.get("site") for domain in domains]
    # 在这里定义，就可以在不同协程间共享计数数据
    domain_configs = {domain: app_config.get_domain_config(domain) for domain in sites}
    records = {domain: DomainRecord(notify, domain_configs.get(domain)) for domain in sites}
    while True:
        tasks = []
        tasks_append = tasks.append
        for domain in domains:
            _domain = domain.get("site")
            t = AsyncCheck(records.get(_domain))
            servers = domain_configs.get(_domain).get_servers()
            tasks_append(t.check_servers(servers))
        await asyncio.wait(tasks)
        time.sleep(1)
        log.logger.info("start new check")


if __name__ == '__main__':
    import time
    asyncio.run(main())
