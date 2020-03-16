import time


from utils import Log, AppConfig
from check import MainThread

log = Log(__name__).get_loger()
log.level = 20


def main():
    config = AppConfig()
    sites = config.get_attrs("sites")
    while True:
        t = MainThread(sites)
        t.setDaemon(True)
        t.start()
        time.sleep(1)
        log.info("开始新一轮循环")


if __name__ == '__main__':
    main()
