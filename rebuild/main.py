import asyncio

from utils import AppConfig
from check import DomainRecord, AsyncCheck, Option
from notify import AsyncNotify


async def main():
    config = AppConfig("config.yml")
    notify = AsyncNotify(config.get_attrs("notify"))
    check_option = Option(config)
    check_option.add_notify(notify)
    domains = config.get_attrs("sites")
    sites = [domain.get("site") for domain in domains]
    records = {domain: DomainRecord(domain, check_option) for domain in sites}
    while True:
        tasks = []
        tasks_append = tasks.append
        for domain in domains:
            _domain = domain.get("site")
            t = AsyncCheck(_domain, records.get(_domain), check_option)
            tasks_append(t.check_servers())
        await asyncio.wait(tasks)
        time.sleep(1)


if __name__ == '__main__':
    import time
    asyncio.run(main())
