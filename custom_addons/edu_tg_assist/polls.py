# -*- coding: utf-8 -*-
"""F4 打卡按钮的**纯逻辑** —— 不 import odoo，可离线单测（tests/unit/tg_assist_poll_test.py）。

背景：F4（内联按钮回填）原本只服务 @提醒待办（edu.tg.assist.reply，callback_data 前缀 ck:）。
打卡（F1 定时提醒带按钮）是另一套语义：**一次群发 → 一群人分别点 → 统计谁回了谁没回**，
所以另立 edu.tg.assist.poll / poll.reply 两张表，回调前缀用 p:（与 ck: 分流，互不抢）。

callback_data 格式（Telegram 硬限 64 字节，中文会爆 ⇒ 只用 ASCII）：

    p:<poll_id>:<choice>     例如  p:12:done  /  p:12:abnormal
        p        = 打卡短前缀
        poll_id  = edu.tg.assist.poll 的 id
        choice   = 选项值（ASCII 短串，稳定，不随按钮文案改）
"""
import logging

_logger = logging.getLogger(__name__)

POLL_PREFIX = 'p'
CALLBACK_MAX_BYTES = 64
#: 选项 spec 默认值（竖线分隔，ASCII 短值）
DEFAULT_OPTIONS = 'done|abnormal'
#: 一条打卡最多几个按钮（Telegram 一行放不下会折行，这里只是别让人写出 50 个）
MAX_OPTIONS = 8
#: 选项值 -> 按钮文案；不在表里的值原样当文案（以后加选项不必改代码）
OPTION_LABELS = {
    'done': '已完成并达标',
    'abnormal': '有异常需上报',
}
#: 一条打卡「应回的人」按什么角色算（与 person.role 的取值同源）
ROLE_SELECTION = [
    ('dorm_head', '宿舍长'),
    ('teacher', '教师'),
    ('admin', '行政'),
    ('staff', '教职工'),
    ('all', '全体已登记的人'),
]


def parse_options(spec):
    """'done|abnormal' -> ('done', 'abnormal')：去空、去重、保序、最多 MAX_OPTIONS 个。"""
    out = []
    for raw in (spec or '').split('|'):
        value = (raw or '').strip()
        if not value or value in out:
            continue
        out.append(value)
        if len(out) >= MAX_OPTIONS:
            break
    return tuple(out)


def label_for(choice):
    """按钮/回执文案（toast 用同一套口径）。"""
    return OPTION_LABELS.get(choice) or choice


def build_callback(poll_id, choice):
    """-> callback_data；id 不合法或超 64 字节返回 None（宁可没有按钮，也不能整条被拒）。"""
    try:
        pid = int(poll_id)
    except (TypeError, ValueError):
        return None
    data = '%s:%d:%s' % (POLL_PREFIX, pid, choice or '')
    if len(data.encode('utf-8')) > CALLBACK_MAX_BYTES:
        _logger.error('edu_tg_assist: 打卡 callback_data 超过 %d 字节，按钮已放弃：%r',
                      CALLBACK_MAX_BYTES, data)
        return None
    return data


def parse_callback(data):
    """-> (poll_id, choice)；不是打卡按钮 / 不合法 -> (None, None)（交给 ck: 或别人）。"""
    parts = (data or '').strip().split(':')
    if len(parts) != 3 or parts[0] != POLL_PREFIX or not parts[2]:
        return None, None
    try:
        return int(parts[1]), parts[2]
    except (TypeError, ValueError):
        return None, None


def filter_roster(rows, expected_role):
    """应回名单：rows 是 person 的 dict（name/role/active/tg_user_id/chat_id）。

    expected_role='all' 时人人算；否则只算 role 相符的。active=False 的人不算。
    """
    role = (expected_role or 'all').strip() or 'all'
    out = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        if not row.get('active', True):
            continue
        if role != 'all' and (row.get('role') or '') != role:
            continue
        out.append(row)
    return out


def missing_uids(roster, replied_uids):
    """未回的 tg_user_id 列表（roster 为 filter_roster 的输出，replied_uids 任意可转字符串）。"""
    done = set()
    for uid in replied_uids or ():
        if uid is not None and str(uid) != '':
            done.add(str(uid))
    out = []
    for row in roster or ():
        uid = str((row or {}).get('tg_user_id') or '')
        if uid and uid not in done:
            out.append(uid)
    return out
