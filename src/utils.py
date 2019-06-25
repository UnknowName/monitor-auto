import os
import time
import pickle
import logging
import logging.handlers

import yaml
import aiohttp


class Log(object):
    """Custer Define Logger"""
    fmt = logging.Formatter(
        '%(asctime)s %(module)s %(threadName)s %(levelname)s %(message)s'
    )

    def __init__(self, name, filename=None):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(self.fmt)
        self.logger.addHandler(ch)
        if filename:
            fh = logging.handlers.TimedRotatingFileHandler(filename, 'D', 1, 7)
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(self.fmt)
            self.logger.addHandler(fh)

    def get_loger(self):
        return self.logger


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
            async with aiohttp.request("POST",
                                       self.send_fmt.format(token=token),
                                       json=msg_data) as resp:
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


class _EmailNotify(object):
    def __init__(self, server: str, username: str, password: str):
        self.server = server
        self.username = username
        self.password = password

    @staticmethod
    async def send_msg(users: list, msg: str):
        print("send msg {0} to user {1}".format(msg, users))


class AsyncNotify(object):
    def __init__(self, configfile: str):
        with open(configfile) as f:
            _conf = yaml.safe_load(f)
        self.conf = _conf

    async def send_msgs(self, msg: str):
        for name, v in self.conf.get("notify").items():
            users = v.get('users')
            if name == 'wechat':
                corpid = v.get('corpid')
                secret = v.get('secret')
                wx = _AsyncWechat(corpid, secret)
                coro = wx.send_msg(users, msg)
            elif name == 'email':
                server = v.get('server')
                username = v.get('username')
                password = v.get('password')
                em = _EmailNotify(server, username, password)
                coro = em.send_msg(users, msg)
            elif name == 'dingding':
                token = v.get('robot_token')
                dding = _AsyncDDing(token)
                coro = dding.send_msg(msg)
            else:
                logging.warning("发现配置文件有不支持的通知方式{}".format(name))
                continue
            await coro


if __name__ == "__main__":
    import asyncio
    loop = asyncio.get_event_loop()
    dd = _AsyncDDing("dingding_robot_toekn")
    loop.run_until_complete(dd.send_msg('hello,world'))
    loop.close()
    """
    import asyncio
    loop = asyncio.get_event_loop()
    n = AsyncNotify('config.yml')
    loop.run_until_complete(n.send_msgs("testinfo"))
    """