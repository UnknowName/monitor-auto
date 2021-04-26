import os
import time
from threading import Thread
from abc import ABCMeta, abstractmethod
from subprocess import run, PIPE, STDOUT

import jinja2

from config import SiteConfig
from utils import SimpleLog, _Single

log = SimpleLog(__name__).log


class AbstractAction(Thread, metaclass=ABCMeta):
    def __init__(self, conf: SiteConfig, host: str):
        Thread.__init__(self)
        self.conf = conf
        # host是错误的主机
        self.host = host

    @staticmethod
    def run_playbook(playbook: str) -> str:
        cmd = "ansible-playbook {}".format(playbook)
        stdout = run(cmd, shell=True, stdout=PIPE, stderr=STDOUT).stdout
        output = stdout.decode("utf8", errors="ignore")
        return output

    @abstractmethod
    def run(self) -> None:
        pass


class AbstractActionFactory(_Single, metaclass=ABCMeta):
    @staticmethod
    @abstractmethod
    def create_action(site_conf: SiteConfig, host: str) -> AbstractAction:
        pass


class RestartProcessAction(AbstractAction):
    _tmpl = r"""        
              - hosts:
                - {{ host }}
                gather_facts: False
                tasks:
                - name: Restart Process {{ name }}
                  win_shell: |
                    $fileInfo=Get-Process -Name {{ name }} -FileVersionInfo
                    Stop-Process -Name {{ name }}
                    Start-Sleep –s 5
                    try {
                        _ = Get-Process -Name {{ name }}
                    } catch [System.SystemException] {
                        Start-Process -FilePath $fileInfo.FileName
                    }
              """

    def __repr__(self) -> str:
        return f"RestartProcessAction({self.conf.recover.name})"

    def run(self) -> None:
        _filename = "{}_{}_{}.yml".format(self.conf.name, self.host, time.time())
        task_file = os.path.join(os.path.pardir, "tasks_yaml", _filename)
        with open(task_file, 'w') as f:
            f.write(jinja2.Template(self._tmpl).render(host=self.host, name=self.conf.name))
        logs = self.run_playbook(task_file)
        log.debug(f"action log: {logs}")


class RestartIISWebsiteAction(AbstractAction):
    _tmpl = r"""        
           - hosts:
             - {{ host }}
             gather_facts: False
             tasks:
             - name: Restart IIS Website {{ name }}
               win_iis_website: name={{ name }} state=restarted
           """

    def run(self) -> None:
        _filename = "{}_{}_{}.yml".format(self.conf.name, self.host, time.time())
        task_file = os.path.join(os.path.pardir, "tasks_yaml", _filename)
        with open(task_file, 'w') as f:
            f.write(jinja2.Template(self._tmpl).render(name=self.conf.name, host=self.host))
        logs = self.run_playbook(task_file)
        log.debug(f"action log: {logs}")

    def __repr__(self) -> str:
        return f"RestartIISWebsiteAction({self.conf.name}, {self.host})"


class ActionFactory(AbstractActionFactory):
    @staticmethod
    def create_action(site_conf: SiteConfig, host: str) -> AbstractAction:
        if site_conf.recover.type == "restart_process":
            return RestartProcessAction(site_conf, host)
        elif site_conf.recover.type == "restart_iis":
            return RestartIISWebsiteAction(site_conf, host)
        raise Exception("No support action")
