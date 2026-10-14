# -*- coding: utf-8 -*-
"""Telegram 文本长度工具 —— **纯 Python，不 import odoo**（离线可单测）。

为什么单独一个文件：api.send_message 必须「发之前把正文压到 Telegram 能收的长度」，
而这段算法（UTF-16 码元计数、不切坏代理对）值得有**可执行的证据** ——
放进 models/ 就得起数据库才能测，放在这里 python3 tests/unit 就能跑。

⚠ Telegram 的长度单位是 **UTF-16 码元**，不是字符：中文算 1，emoji（代理对）算 2。
   超限时 Telegram 直接回 400 MESSAGE_TOO_LONG —— **整条消息丢掉**。
   对广播/催交这种没人盯着屏幕的场景，宁可截断也不能整条不发。
"""

TELEGRAM_TEXT_LIMIT = 4096  # sendMessage.text 的上限（UTF-16 码元）
ELLIPSIS = u'\u2026'        # …（1 个码元）


def utf16_len(text):
    """按 UTF-16 码元计数（Telegram 的口径）。"""
    return len((text or '').encode('utf-16-le')) // 2


def clamp_telegram_text(text, limit=TELEGRAM_TEXT_LIMIT):
    """把正文压进 limit 个 UTF-16 码元以内。

    :return: (text, truncated) —— truncated=True 表示发生过截断。
    截断点按码元算，绝不会切出半个代理对（那本身就是非法文本）。
    """
    text = text or ''
    if limit <= 0:
        return '', bool(text)
    if utf16_len(text) <= limit:
        return text, False
    budget = limit - utf16_len(ELLIPSIS)
    if budget < 1:
        return ELLIPSIS[:limit], True
    out = []
    used = 0
    for ch in text:
        w = 2 if ord(ch) > 0xFFFF else 1
        if used + w > budget:
            break
        out.append(ch)
        used += w
    return ''.join(out) + ELLIPSIS, True
