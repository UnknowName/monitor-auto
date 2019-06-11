from threading import Thread
from subprocess import run, PIPE, STDOUT


class _BaseActionThread(Thread):
    def __init__(self, site: str, host: str):
        Thread.__init__(self)
        self.site = site
        self.host = host

    @staticmethod
    def execute_action(playbook: str) -> str:
        cmd = "ansible-playbook {}".format(playbook)
        stdout = run(cmd, shell=True, stdout=PIPE, stderr=STDOUT).stdout
        try:
            return stdout.decode("utf8")
        except UnicodeDecodeError:
            return stdout.decode("gbk")

    def _create_task_yaml(self, yaml_tmp: str, host: str, site: str) -> str:
        task_str = yaml_tmp.format(host=host, site=site)
        yaml_name = "{}_{}.yml".format(host, site)
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
        stdout = self.execute_action(ansible_playbook)
        print(stdout)


class NgxActionThread(_BaseActionThread):
    _DOWN_YAML_TMP = r"""
    - hosts:
      - {host}
      gather_facts: False
      tasks:
      - name: {site} down {host}
        lineinfile:
          path: /etc/nginx/conf.d/{site}.conf
          regexp: '(\s+?server\s+?{host}.*)'
          line: '#\1'
          backrefs: yes
        
      - name: Reload NGINX
        shell: systemctl reload nginx || nginx -s reload
    """

    _UP_YAML_TMP = r"""
    - hosts:
      - {host}
      gather_facts: False
      tasks:
      - name: {site}  Up {host}
        lineinfile:
          path: /etc/nginx/conf.d/{site}.conf
          regexp: '#(\s+?server\s+?{host}.*)'
          line: '\1'
          backrefs: yes
        
      - name: Reload NGINX
        shell: systemctl reload nginx || nginx -s reload
    """

    def start(self) -> None:
        ansible_playbook = self._create_task_yaml(self._DOWN_YAML_TMP, self.host, self.site)
        stdout = self.execute_action(ansible_playbook)
        print(stdout)


if __name__ == '__main__':
    t = NgxActionThread("www.aaa.com", "128.0.100.170")
    t.start()