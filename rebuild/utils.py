import os
from threading import Thread
from subprocess import run, PIPE, STDOUT

import yaml
import jinja2

from notify import AsyncNotify


class NoServersConfigError(Exception):
    def __init__(self, error: str):
        raise Exception(error)


class AppConfig(object):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, filename: str):
        filename = filename if filename else "config.yml"
        with open(filename, encoding="utf8") as f:
            self._data = yaml.safe_load(f)

    def get_attrs(self, attr: str) -> list:
        return self._data.get(attr, [])


class Option(object):
    _instance = None
    _attrs = dict()
    _notify = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, app_config: AppConfig):
        domains = app_config.get_attrs("sites")
        nginxs = app_config.get_attrs("nginxs")
        self._attrs["nginxs"] = nginxs
        for domain_config in domains:
            domain_name = domain_config.get("site")
            self._attrs[domain_name] = domain_config

    def add_notify(self, notify: AsyncNotify) -> None:
        if not self._notify:
            self._notify = notify

    def get_notify(self) -> AsyncNotify:
        return self._notify

    def get_nginxs(self) -> list:
        return self._attrs.get("nginxs")

    def get_attr(self, domain: str, key: str) -> str:
        return self._attrs.get(domain, {}).get(key, "")

    def get_config(self, domain: str) -> dict:
        return self._attrs.get(domain, {})


class _BaseActionThread(Thread):

    def __init__(self, domain: str, host: str, **kwargs):
        """
        :param domain: "dev.siss.io"
        :param host: "128.0.255.27:80"
        """
        Thread.__init__(self)
        self._host = host
        self._domain = domain
        self._kwargs = kwargs
        self._observe = None
        self._action_type = "ok"

    def set_action_type(self, name: str):
        if name in ["error", "ok"]:
            self._action_type = name
        else:
            raise Exception("Action type only error or ok")

    @staticmethod
    def execute_action(playbook: str) -> None:
        cmd = "ansible-playbook {}".format(playbook)
        stdout = run(cmd, shell=True, stdout=PIPE, stderr=STDOUT).stdout
        try:
            std = stdout.decode("utf8")
        except UnicodeDecodeError:
            std = stdout.decode("gbk")
        print(std)


class NginxAction(_BaseActionThread):
    """
    发生错误的动作,从NGINX上下线
    """

    _down_tmpl = r"""
    - hosts:
      {%- for nginx in nginxs %}
      - {{ nginx }}
      {% endfor -%}
      gather_facts: False
      tasks:
      - name: Gateway down host {{ host }}
        lineinfile:
          path: /etc/nginx/conf.d/{{ domain }}.conf
          regexp: '(\s{0,}\bserver\b\s+?\b{{ host }}\b.*)'
          line: '#\1'
          backrefs: yes
        register: stdout
        
      - name: Reload NGINX
        shell: systemctl reload nginx || nginx -s reload
        when: stdout.changed == True
        
    - hosts:
      - {{ host.split(":")[0] }}
      gather_facts: False
      tasks:
      - name: Restart IIS Website {{ domain }}
        win_iis_website: name={{ domain }} state=restarted
    """

    _up_tmpl = r"""
    - hosts:
      {%- for nginx in nginxs %}
      - {{ nginx }}
      {% endfor -%}
      gather_facts: False
      tasks:
      - name: Gateway up host {{ host }}
        lineinfile:
          path: /etc/nginx/conf.d/{{ domain }}.conf
          regexp: '(\s{0,})#(\s{0,}\bserver\b\s+?\b{{ host }}\b.*)'
          line: '\1\2'
          backrefs: yes
        register: stdout
    
      - name: Reload NGINX
        shell: systemctl reload nginx || nginx -s reload
        when: stdout.changed == True
    """

    def __repr__(self):
        return "NginxAction({}, {})".format(self._domain, self._host)

    def _create_yaml(self, host: str, domain: str) -> str:
        nginxs = self._kwargs.get("nginxs")
        if self._action_type == 'error':
            task_yaml = self._down_tmpl
        else:
            task_yaml = self._up_tmpl
        _filename = "{domain}_{host}_{action}.yml".format(domain=domain,
                                                          host=host.replace(":", "_"),
                                                          action=self._action_type)
        task_file = os.path.join(os.path.pardir, "tasks_yaml", _filename)
        with open(task_file, 'w') as f:
            f.write(jinja2.Template(task_yaml).render(nginxs=nginxs, host=host, domain=domain))
            return task_file

    def start(self) -> None:
        if not self._action_type:
            raise Exception("Before Run start, Please call set_action_type(name: str)")
        playbook = self._create_yaml(self._host, self._domain)
        self.execute_action(playbook)


if __name__ == '__main__':
    # nginx_action = NginxAction("dev.siss.io", "128.0.255.10:80", action="down", nginxs=["128.0.255.2", "128.0.255.3"])
    # nginx_action.start()
    config = AppConfig("")
    op = Option(config)
    print(op.get_config("www.aaa.com"))
    print(op.get_nginxs())
