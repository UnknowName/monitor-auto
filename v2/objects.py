import os
import time
import pickle
import asyncio
from typing import List, Tuple, Set
from email.mime.text import MIMEText

import jinja2
import aiohttp
import aiosmtplib
import aiosmtplib.auth

from base import SimpleLog
from models import AbstractHostRecord, AbstractOption, AbstractActionFactory, AbstractAction, AbstractAsyncNotify

log = SimpleLog(__name__).log
DEFAULT = 1


class _HostRecord(AbstractHostRecord):
    def __init__(self):
        self.count = 1
        self.expire_time = time.time() + 60 * DEFAULT
        # 记录下次干预的时间，防止恶性循环
        self.next_action_time = None
        # 记录下次发送通知的时间，避免频繁发送
        self.next_notify_time = None

    def is_valid(self) -> bool:
        """
        记录本身是否已经失效
        :return:
        """
        return self.expire_time >= time.time()

    def is_notify(self) -> bool:
        if not self.next_notify_time:
            return True
        return self.next_notify_time <= time.time()

    def is_action(self) -> bool:
        if not self.next_action_time:
            return True
        return self.next_action_time <= time.time()

    def update(self, v: int) -> None:
        if self.is_valid():
            self.count += v
        else:
            self.count = v
        self.expire_time = time.time() + 60 * DEFAULT

    def __repr__(self):
        return "HostRecord(count={})".format(self.count)


class RestartActionOption(AbstractOption):
    def __init__(self, host: str, process_name: str):
        self._host = host
        self._process_name = process_name

    @property
    def host(self) -> str:
        return self._host

    @property
    def domain(self):
        return ""

    @property
    def process(self) -> str:
        return self._process_name

    def __repr__(self) -> str:
        return "KillActionOption(domain={}, process={})".format(self._host, self.process)


class RecycleActionOption(AbstractOption):
    def __init__(self, host: str, domain: str):
        self._host = host
        self._domain = domain

    @property
    def host(self) -> str:
        return self._host

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def process(self) -> str:
        return ""

    def __repr__(self) -> str:
        return "RecycleActionOption(host={},domain={})".format(self._host, self._domain)


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

    def run(self) -> None:
        _filename = "{}_{}_{}.yml".format(self._option.domain, self._option.host, time.time())
        task_file = os.path.join(os.path.pardir, "tasks_yaml", _filename)
        with open(task_file, 'w') as f:
            f.write(jinja2.Template(self._tmpl).render(host=self._option.host, name=self._option.process))
        self.run_playbook(task_file)


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
        _filename = "{}_{}_{}.yml".format(self._option.domain, self._option.host, time.time())
        task_file = os.path.join(os.path.pardir, "tasks_yaml", _filename)
        with open(task_file, 'w') as f:
            f.write(jinja2.Template(self._tmpl).render(host=self._option.host, name=self._option.domain))
        self.run_playbook(task_file)


class _AsyncWechat(object):
    token_fmt = 'https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={secret}'
    send_fmt = 'https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}'

    def __init__(self, corp_id: str, secret: str):
        self.token_url = self.token_fmt.format(corp_id=corp_id, secret=secret)

    @property
    async def _fetch_token(self):
        async with aiohttp.request("GET", self.token_url) as resp:
            json_data = await resp.json()
            if json_data.get("errcode", 1):
                print(json_data.get("errmsg"))
            else:
                return json_data.get("access_token")

    @staticmethod
    async def _cache_token(token: str) -> bool:
        expiry_time = time.time() + (2 * 60 * 60)
        cache_dic = dict(token=token, expiry_time=expiry_time)
        with open('token.cache', 'wb') as f:
            pickle.dump(cache_dic, f)
            return True

    async def get_token(self) -> str:
        if os.path.exists('token.cache'):
            with open('token.cache', 'rb') as f:
                token_dic = pickle.load(f)
                if token_dic.get("expiry_time", time.time()) < time.time():
                    token = await self._fetch_token
                    await self._cache_token(token=token)
                    return token
                else:
                    return token_dic.get("token")
        else:
            token = await self._fetch_token
            if token:
                await self._cache_token(token)
                return token

    async def send_msg(self, to_user: list, msg: str) -> str:
        msg_data = dict(
            touser='|'.join(to_user),
            msgtype='text', agentid=0,
            text=dict(content=msg)
        )
        token = await self.get_token()
        if not token:
            return ""
        try:
            async with aiohttp.request("POST", self.send_fmt.format(token=token), json=msg_data) as resp:
                return await resp.json()
        except Exception as e:
            print(e)
            return ""


class _AsyncDDing(object):
    _send_fmt = "https://oapi.dingtalk.com/robot/send?access_token={token}"

    def __init__(self, token: str) -> None:
        self.send_api = self._send_fmt.format(token=token)

    async def send_msg(self, msg: str) -> str:
        msgs = {
            'msgtype': 'text',
            'text': {
                'content': msg
            }
        }
        async with aiohttp.request('POST', self.send_api, json=msgs) as resp:
            return await resp.json()


class _AsyncEmail(object):
    def __init__(self, server: str, port: int, username: str, password: str):
        self.server = server
        self.port = port if port else 25
        self.username = username
        self.password = password
        self._smtp = aiosmtplib.SMTP(hostname=server, port=port)

    async def send_msg(self, users: list, msg: str):
        message = MIMEText(msg)
        message['From'] = self.username
        message['To'] = ';'.join(users)
        message["Subject"] = msg
        async with self._smtp as smtp:
            await smtp.login(self.username, self.password)
            await smtp.send_message(message)


class AsyncNotify(AbstractAsyncNotify):
    def __init__(self, configs: list) -> None:
        self.configs = configs if configs else []

    def __repr__(self) -> str:
        return "AsyncNotify()"

    async def send_msgs(self, msg: str) -> None:
        for _config in self.configs:
            _notify_name = _config.get("type", "")
            if _notify_name == "dingding":
                _token = _config.get("robot_token")
                _dding = _AsyncDDing(_token)
                notify_coroutine = _dding.send_msg(msg)
            elif _notify_name == "wechat":
                _corpid = _config.get('corpid')
                _secret = _config.get('secret')
                _users = _config.get("users")
                _wx = _AsyncWechat(_corpid, _secret)
                notify_coroutine = _wx.send_msg(_users, msg)
            elif _notify_name == 'email':
                _server = _config.get('server')
                _username = _config.get('username')
                _password = _config.get('password')
                _port = _config.get('port', 25)
                _users = _config.get("users")
                _em = _AsyncEmail(_server, _port, _username, _password)
                notify_coroutine = _em.send_msg(_users, msg)
            else:
                continue
            await notify_coroutine


class AsyncCheck(object):
    @staticmethod
    async def _get_status(hostname: str, host: str, path: str, timeout: int) -> Tuple[int, str]:
        url = "http://{}{}".format(host, path)
        headers = dict(Host=hostname)
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.get(url) as resp:
                    return resp.status, host
        except Exception as e:
            if not str(e):
                e = "Check Coroutine Timeout, It mean HTTP Get Timeout"
            log.warning(e)
            return 504, host

    async def checks(self, hostname: str, path: str, servers: Set[str], timeout: int) -> List[Tuple[int, str]]:
        _tasks = [self._get_status(hostname, _host, path, timeout) for _host in servers]
        _dones, _ = await asyncio.wait(_tasks)
        results = [_done.result() for _done in _dones]
        return results


class ActionFactory(AbstractActionFactory):
    @staticmethod
    def create_action(action_name: str, host: str, **kwargs) -> AbstractAction:
        if action_name == "restart_process":
            _name = kwargs.get("name")
            assert _name, "关键参数name为必须"
            _option = RestartActionOption(host, _name)
            return RestartProcessAction(_option)
        elif action_name == "restart_website":
            _name = kwargs.get("name")
            assert _name, "关键参数name为必须"
            _option = RestartActionOption(host, _name)
            return RestartIISWebsiteAction(_option)
        else:
            raise Exception("暂不支持的操作类型")


if __name__ == '__main__':
    option = RestartActionOption(host="test", process_name="mysqld.exe")
    t = RestartIISWebsiteAction(option)
    t.start()
