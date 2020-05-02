from abc import ABCMeta, abstractmethod


# 抽象要执行动作的基类，比如回收、重启、上线、下线等
class Action(metaclass=ABCMeta):
    @abstractmethod
    def start(self, down_result):
        pass


# 定义异常的数据结构
class DownResult(object):
    def __init__(self, domain: str):
        self.__domain = domain
        self.__hosts = list()
        self.__actions = list()

    # 增加观察者
    def add_action(self, obj: Action):
        self.__actions.append(obj)

    # 增加异常的主机
    def add_host(self, host: str):
        self.__hosts.append(host)
        self.__action()

    # 移除异常的主机
    def remove_host(self, host: str):
        self.__hosts.remove(host)
        self.__action()

    def is_action(self) -> bool:
        return len(self.__hosts) > 2

    def __action(self):
        for obj in self.__actions:
            obj.start(self)


class RecycleAction(Action):
    def start(self, down_result):
        if down_result.is_action():
            print("执行回收操作")


if __name__ == '__main__':
    recycle = RecycleAction()
    result = DownResult("test")
    result.add_action(recycle)
    result.add_host("ssss")
    result.add_host("ssss2")
    result.add_host("ssss3")