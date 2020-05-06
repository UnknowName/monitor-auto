import asyncio

from rebuild.utils import AppConfig
from rebuild.check import DomainRecord, AsyncCheck, Option


async def main():
    config = AppConfig("config.yml")
    check_option = Option(config)
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
    print("total", time.perf_counter())
