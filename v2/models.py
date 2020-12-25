"""
抽象基类
"""
from threading import Thread
from typing import List, Set, Tuple
from abc import ABCMeta, abstractmethod
from subprocess import run, PIPE, STDOUT


class AbstractOption(metaclass=ABCMeta):
    @property
    @abstractmethod
    def host(self) -> str:
        pass

    @property
    @abstractmethod
    def domain(self) -> str:
        pass

    @property
    @abstractmethod
    def process(self) -> str:
        pass


class AbstractGatewayConfig(metaclass=ABCMeta):
    def get_attr(self, attr: str, default: str = "") -> str:
        v = getattr(self, attr)
        return v if v else default

    @abstractmethod
    def name(self) -> str:
        pass


class AbstractGateway(metaclass=ABCMeta):
    """
    __init__让继承的类去实现，不同的网关初始化方法不一样
    """

    @abstractmethod
    def get_servers(self, **kwargs) -> Set[str]:
        """
        通过网关获取后端服务器
        :return:
        """
        pass

    @abstractmethod
    def change_server_offline(self, server: str, **kwargs) -> None:
        pass

    @abstractmethod
    def change_server_online(self, server: str, **kwargs) -> None:
        pass


class AbstractGatewayFactory(metaclass=ABCMeta):
    @staticmethod
    @abstractmethod
    def create_gateway(name: str) -> AbstractGateway:
        pass


class AbstractAction(Thread, metaclass=ABCMeta):
    """
    自动干预的抽象类，所有干预实现都需要基于本类
    """
    def __init__(self, option: AbstractOption):
        Thread.__init__(self)
        self._option = option

    @staticmethod
    def run_playbook(playbook: str) -> str:
        cmd = "ansible-playbook {}".format(playbook)
        stdout = run(cmd, shell=True, stdout=PIPE, stderr=STDOUT).stdout
        output = stdout.decode("utf8", errors="ignore")
        return output

    @abstractmethod
    def run(self) -> None:
        pass


class AbstractActionFactory(metaclass=ABCMeta):
    @staticmethod
    @abstractmethod
    def create_action(action_name: str, host: str, **kwargs) -> AbstractAction:
        pass


class AbstractSiteConfig(metaclass=ABCMeta):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def timeout(self) -> int:
        pass

    @property
    @abstractmethod
    def path(self) -> str:
        pass

    @property
    @abstractmethod
    def servers(self) -> Set[str]:
        pass

    @abstractmethod
    def set_gateway(self, gateway: AbstractGateway) -> None:
        pass

    @property
    @abstractmethod
    def gateway_kwargs(self) -> dict:
        pass


class AbstractAsyncCheck(metaclass=ABCMeta):
    def __init__(self, _site_conf: AbstractSiteConfig):
        self._site = _site_conf

    @abstractmethod
    async def checks(self, hostname: str, path: str, servers: Set[str], timeout: int) -> List[Tuple[int, str]]:
        pass


class AbstractAsyncNotify(metaclass=ABCMeta):
    @abstractmethod
    async def send_msgs(self, msg: str):
        pass


class AbstractHostRecord(metaclass=ABCMeta):
    @abstractmethod
    def is_valid(self) -> bool:
        pass

    def is_notify(self) -> bool:
        pass

    def is_action(self) -> bool:
        pass

    def update(self, v: int) -> None:
        pass
