import time
import yaml

from utils import Log
from check import MainThread

log = Log(__name__).get_loger()
log.level = 20

def main():
    with open("config.yml") as f:
        yml = yaml.safe_load(f)
    # 整个sites变量传入检测函数
    sites = yml.get("sites")
    while True:
        t = MainThread(sites)
        t.setDaemon(True)
        t.start()
        time.sleep(1)
        log.info("开始新一轮循环")


if __name__ == '__main__':
    main()
