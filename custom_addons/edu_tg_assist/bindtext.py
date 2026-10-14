# -*- coding: utf-8 -*-
"""身份绑定码的**纯函数**部分 —— 不 import odoo，可离线单测。

为什么单独一个文件：绑定码的格式被**两处**消费者共用，各写一份必然漂移 ——
  · models/bindcode.py —— 生成码、拼深链、兑现（写进 edu.tg.assist.person）；
  · edu_tg_gate/routing.py —— 判「/start 的载荷是不是我们签发的绑定码」。
第二处若与第一处不一致，老师点开深链会被前门当成学生领码流（实测过的坑，
见 tests/unit/tg_gate_router_test.py 的「/start 载荷」一组用例）。

码的形状：BIND- + 6 位**去掉易混字符**（无 0/O、无 1/I/L）的大写字母数字，
与学生邀请码同一套手抄友好口径。深链形如：
    https://t.me/sctrs_bot?start=BIND-7KQ2ZM
Telegram 只把 `?start=<载荷>` 塞进 `/start <载荷>`，因此前门必须认识这个格式。
"""
import random
import re

CODE_PREFIX = 'BIND-'
#: 去混淆码表（0/O、1/I/L 全部剔除）：手抄/口述不出错
ALPHABET = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'
CODE_LEN = 6
MAX_CODE_TRIES = 8

#: 默认有效期天数（参数 edu_tg_assist.bind_code_days 覆盖；<=0 = 永不过期）
DEFAULT_DAYS = 14
#: 深链里用的机器人用户名（参数 edu_tg_assist.bot_username 覆盖）
DEFAULT_USERNAME = 'sctrs_bot'

#: 深链载荷的**唯一格式来源**：edu_tg_gate 在运行时通过
#: edu.tg.assist.bindcode.payload_pattern() 取它，不另写一份。
PAYLOAD_RE = r'^BIND-[A-Z0-9]{%d,%d}$' % (CODE_LEN, CODE_LEN)

# 角色中文 → 机器值（/bindcode 用；与 person.role 的 selection 一一对应）
ROLE_WORDS = {
    '行政': 'admin', '管理员': 'admin', '管理': 'admin',
    '教师': 'teacher', '老师': 'teacher',
    '宿舍长': 'dorm_head', '宿管': 'dorm_head', '舍监': 'dorm_head',
}
ROLE_HINT = '角色写：行政 / 教师 / 宿舍长'

USAGE_BIND = '用法：/bind BIND-XXXXXX（管理员给你的那张码）'
USAGE_BINDCODE = '用法：/bindcode 教师 张三   （' + ROLE_HINT + '）'


def random_code():
    """一张新码（是否撞车由调用方查库判定，这里只负责形状）。"""
    return CODE_PREFIX + ''.join(random.choice(ALPHABET) for _ in range(CODE_LEN))


def normalize_code(text):
    """用户输入的码归一化：去空白、转大写（老师手输常带空格/小写）。"""
    return (text or '').strip().upper()


def first_code_token(text):
    """从用户发来的一串里取出**第一段**当码。

    背景（2026-10-12 用户实测）：老师手输时常把码连同别的话一起发过来，例如
    `/bind BIND-ABC123 @某人 谢谢`。整串拿去查库必然查不到，
    只会回「无效或已用过了」，看着像码本身坏了。
    """
    parts = (text or '').split()
    return normalize_code(parts[0]) if parts else ''


def is_bind_payload(text, pattern=None):
    """这个字符串是不是「我们签发的绑定码载荷」。

    :param pattern: 覆盖用的正则（前门从库里的 payload_pattern() 取）；
        给不出/坏掉时回落本文件的 PAYLOAD_RE（宁可按格式认，也不静默失效）。
    大小写不敏感：深链一律大写，但手输可能小写。
    """
    s = (text or '').strip()
    if not s:
        return False
    pat = pattern or PAYLOAD_RE
    try:
        return bool(re.match(pat, s, re.IGNORECASE))
    except re.error:
        return bool(re.match(PAYLOAD_RE, s, re.IGNORECASE))


def deep_link(bot_username, code):
    """点开即绑定的深链（用户名不带 @）。"""
    user = (bot_username or DEFAULT_USERNAME).strip().lstrip('@')
    return 'https://t.me/%s?start=%s' % (user, normalize_code(code))


def split_role_and_name(rest):
    """把 `教师 张三` 解析成 ('teacher', '张三')；认不出角色返回 (None, '')。

    只认 ROLE_WORDS 里的词（不做模糊匹配）：写错角色就让人重写一遍，
    总好过把「王老师」猜成教师 —— 角色错判会让前门把学生消息判给班务助手。
    """
    parts = (rest or '').split()
    if len(parts) < 2:
        return None, ''
    role = ROLE_WORDS.get(parts[0])
    name = ' '.join(parts[1:]).strip()
    if not role or not name:
        return None, ''
    return role, name
