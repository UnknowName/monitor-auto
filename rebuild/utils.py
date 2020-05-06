from threading import Thread
from subprocess import run, PIPE, STDOUT

import yaml
import jinja2


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
        with open(filename) as f:
            self._data = yaml.safe_load(f)

    def get_attrs(self, attr: str) -> list:
        return self._data.get(attr, [])


class Option(object):
    _instance = None
    _attrs = dict()

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

    # 暂未用到
    def add_observe(self, observe):
        """
        增加被观察者，用来执行相关动作后，将计数重新重置为0
        :param observe:
        :return:
        """
        self._observe = observe

    @staticmethod
    def execute_action(playbook: str) -> None:
        cmd = "ansible-playbook {}".format(playbook)
        stdout = run(cmd, shell=True, stdout=PIPE, stderr=STDOUT).stdout
        try:
            std = stdout.decode("utf8")
        except UnicodeDecodeError:
            std = stdout.decode("gbk")
        print(std)


# TODO 执行完相应的动作后，要发送通知出来
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
          regexp: '(\s+?\bserver\b\s+?\b{{ host }}\b.*)'
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
        path: /etc/nginx/conf.d/{{ domain }}.conf
        regexp: '\s+?#(\s+?\bserver\b\s+?\b{{ host }}\b.*)'
        line: '\1'
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
        filename = "{domain}_{host}_{action}.yml".format(domain=domain,
                                                         host=host.replace(":", "_"),
                                                         action=self._action_type)
        with open(filename, 'w') as f:
            f.write(jinja2.Template(task_yaml).render(nginxs=nginxs, host=host, domain=domain))
            return filename

    def start(self) -> None:
        if not self._action_type:
            raise Exception("Before Run start, Please call set_action_type(name: str)")
        playbook = self._create_yaml(self._host, self._domain)
        self.execute_action(playbook)

    # 暂未用到
    # observer: DomainRecord
    def execute(self, observe):
        if observe.count > 2:
            self.start()
            # 执行下线后，不能重置为0，要看恢复没有，恢复后将计数变为0
            # observe.set_count(0)


if __name__ == '__main__':
    # nginx_action = NginxAction("dev.siss.io", "128.0.255.10:80", action="down", nginxs=["128.0.255.2", "128.0.255.3"])
    # nginx_action.start()
    config = AppConfig("")
    op = Option(config)
    print(op.get_config("www.aaa.com"))
    print(op.get_nginxs())
