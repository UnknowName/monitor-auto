import os
import time
import pickle
from email.mime.text import MIMEText

import aiohttp
import aiosmtplib
import aiosmtplib.auth

from utils import MyLog

log = MyLog(__name__)


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


class AsyncNotify(object):
    def __init__(self, configs: list) -> None:
        self.configs = configs if configs else []

    async def send_msgs(self, msg: str) -> None:
        if not self.configs:
            log.logger.warning("No Notify channel config set, Can not send any messages")
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
