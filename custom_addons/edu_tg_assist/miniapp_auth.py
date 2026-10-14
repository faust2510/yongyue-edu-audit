# -*- coding: utf-8 -*-
"""Telegram Mini App 的 initData 校验（纯函数，不 import odoo => 可离线单测）。

一手依据：官方文档 https://core.telegram.org/bots/webapps
（2026-10-13 由生产机 fetch 原文复核，原文当时落在 /tmp/tgwa.html）：

    data_check_string = 除 hash 外所有字段按 key 字母序，用换行符连成 key=value
    secret_key        = HMAC_SHA256(<bot_token>, "WebAppData")   <-- WebAppData 是 key
    if hex(HMAC_SHA256(data_check_string, secret_key)) == hash: 数据来自 Telegram

官方只要求 hash 一致；本文件另按它同一节「To prevent the use of outdated data」
校验 auth_date 时效（默认 1 小时），并给出稳定短码原因，供日志/自检使用。

本文件**绝不**打印、返回或缓存 token 与 init_data 原文；调用方也不许把它们写日志。
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

#: initData 的时效（秒）。官方说由自己定；一次点击打开面板 1 小时足够。
DEFAULT_TTL = 3600
#: 允许客户端时钟略快于服务器（秒），超了就当伪造。
FUTURE_SKEW = 300
#: initData 原文上限（字节）。实测几百字节，超限直接拒绝。
MAX_BYTES = 8192

#: check() 的 reason 闭集（日志里只出现这些短码，不出现 init_data 内容）。
REASONS = ('ok', 'empty', 'too_long', 'no_token', 'no_hash', 'bad_hash',
           'bad_date', 'stale', 'future', 'no_user')


def parse_init_data(raw):
    """ 'a=1&b=2' -> {'a': '1', 'b': '2'}（同一 key 重复时取第一个）。"""
    out = {}
    for key, value in parse_qsl(raw or '', keep_blank_values=True):
        out.setdefault(key, value)
    return out


def data_check_string(fields):
    """除 hash 外，按 key 字母序、以换行连接成 key=value（官方原文口径）。"""
    return '\n'.join('%s=%s' % (key, fields[key]) for key in sorted(fields) if key != 'hash')


def expected_hash(raw, bot_token):
    """按官方算法算出应当出现的 hash（十六进制）。"""
    secret = hmac.new(b'WebAppData', (bot_token or '').encode('utf-8'), hashlib.sha256).digest()
    body = data_check_string(parse_init_data(raw)).encode('utf-8')
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def user_of(fields):
    """initData.user 是 JSON 串；解析失败返回 {}（调用方按「没身份」处理）。"""
    try:
        data = json.loads(fields.get('user') or '')
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def check(raw, bot_token, now=None, ttl=DEFAULT_TTL):
    """:return: (ok, reason)。reason 取 REASONS 里的短码，绝不回显 init_data 内容。"""
    if not raw or not isinstance(raw, str):
        return False, 'empty'
    if len(raw.encode('utf-8', 'ignore')) > MAX_BYTES:
        return False, 'too_long'
    if not (bot_token or '').strip():
        return False, 'no_token'
    fields = parse_init_data(raw)
    got = (fields.get('hash') or '').strip()
    if not got:
        return False, 'no_hash'
    if not hmac.compare_digest(got, expected_hash(raw, bot_token)):
        return False, 'bad_hash'
    try:
        auth_date = int(fields.get('auth_date') or 0)
    except (TypeError, ValueError):
        return False, 'bad_date'
    if not auth_date:
        return False, 'bad_date'
    stamp = int(now if now is not None else time.time())
    if auth_date - stamp > FUTURE_SKEW:
        return False, 'future'
    if stamp - auth_date > ttl:
        return False, 'stale'
    user = user_of(fields)
    if not user.get('id'):
        return False, 'no_user'
    return True, 'ok'
