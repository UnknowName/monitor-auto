from threading import Thread
from subprocess import run, PIPE, STDOUT

from utils import Log

log = Log(__name__).get_loger()


class _BaseActionThread(Thread):
    def __init__(self, site: str, host: str):
        Thread.__init__(self)
        self.site = site
        self.host = host.split(':')[0]

    @staticmethod
    def execute_action(playbook: str) -> None:
        cmd = "ansible-playbook {}".format(playbook)
        stdout = run(cmd, shell=True, stdout=PIPE, stderr=STDOUT).stdout
        try:
            std = stdout.decode("utf8")
        except UnicodeDecodeError:
            std = stdout.decode("gbk")
        log.info("Ansible执行日志*******\n{}".format(std))

    @staticmethod
    def _create_task_yaml(yaml_tmp: str, host: str, site: str, **kwargs) -> str:
        host_port = '_'.join(host.split(":"))
        if 'ngx' in kwargs:
            ngx = kwargs.get("ngx")
            task_str = yaml_tmp.format(host=host, site=site, ngx=ngx)
            yaml_name = "{}_{}_{}.yml".format(ngx, host_port, site)
        else:
            task_str = yaml_tmp.format(host=host, site=site)
            yaml_name = "{}_{}.yml".format(host_port, site)
        with open(yaml_name, "w") as f:
            f.write(task_str)
            return yaml_name


class RecycleActionThread(_BaseActionThread):
    _RECYCLE_YAML_TMP = """
    - hosts:
      - {host}
      gather_facts: False
      tasks:
      - name: Restart {site} IIS WebApplicationPool
        win_iis_webapppool:
          name: {site}
          state: restarted
    """

    def start(self) -> None:
        ansible_playbook = self._create_task_yaml(self._RECYCLE_YAML_TMP, self.host, self.site)
        self.execute_action(ansible_playbook)


class NgxActionThread(_BaseActionThread):
    _DOWN_YAML_TMP = r"""
    - hosts:
      - {ngx}
      gather_facts: False
      tasks:
      - name: {site} down {host}
        lineinfile:
          path: /etc/nginx/conf.d/{site}.conf
          regexp: '(\s+?\bserver\b\s+?{host}.*)'
          line: '#\1'
          backrefs: yes
        
      - name: Reload NGINX
        shell: systemctl reload nginx || nginx -s reload
    """

    _UP_YAML_TMP = r"""
    - hosts:
      - {ngx}
      gather_facts: False
      tasks:
      - name: {site}  Up {host}
        lineinfile:
          path: /etc/nginx/conf.d/{site}.conf
          # backup regexp: '#(\s+?server\s+?{host}.*)'
          regexp: '\s+?#(\s+?\bserver\b\s+?{host}.*)'
          line: '\1'
          backrefs: yes
        
      - name: Reload NGINX
        shell: systemctl reload nginx || nginx -s reload
    """

    def __init__(self, ngx: str, site: str, host: str, action: str):
        Thread.__init__(self)
        self.ngx = ngx
        self.site = site
        self.host = host
        # action is down or up
        self.action = action

    def start(self) -> None:
        if self.action == 'down':
            _TASK_YAML = self._DOWN_YAML_TMP
        else:
            _TASK_YAML = self._UP_YAML_TMP
        ansible_playbook = self._create_task_yaml(_TASK_YAML, self.host, self.site, ngx=self.ngx)
        log.info("将对站点{}的主机{}执行{}".format(self.site, self.host, self.action))
        self.execute_action(ansible_playbook)


class KillActionThread(_BaseActionThread):
    _KILL_TEM = r"""
    - hosts:
      - {host}
      gather_facts: False
      tasks:
        - name: Kill Processlist
          win_command: taskkill /F /IM SiXunMall.Web.Host.exe
    """

    def start(self) -> None:
        ansible_playbook = self._create_task_yaml(self._KILL_TEM, "128.0.255.10", "")
        self.execute_action(ansible_playbook)


if __name__ == '__main__':
    # t = NgxActionThread("128.0.100.170", "www.aa.com", "128.0.255.28:80", 'down')
    # t.start()
    k = KillActionThread("", "")
    k.start()
