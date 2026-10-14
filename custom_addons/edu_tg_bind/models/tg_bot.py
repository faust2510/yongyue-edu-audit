# -*- coding: utf-8 -*-
"""Telegram Bot API 出网客户端 —— 本模块**唯一**的出网口。

设计依据（本机实测，见 docs/plans/tg-invite-bot-design.md §6）：
  · 容器内可**直连** api.telegram.org（实测 getMe 拿到 Telegram 真实 401 应答，
    DNS 203.0.113.9）⇒ 同步发送，不需要宿主中继；
  · **不走** scripts/telegram_relay.py：它认领的是 edu_telegram_outbox ——
    生产「匿名意见箱」的表，改它 = 动那个模块的投递链路（硬边界，见设计 §1.2）；
  · 本客户端**不抛异常**：出网失败只回报失败原因，由调用方记进 edu.tg.claim.notify_*，
    学生的码在库里已经落定（先落库再出网，设计 §5.6）。
"""
import logging

import requests

from odoo import api, models

_logger = logging.getLogger(__name__)

API_BASE = 'https://api.telegram.org'
TOKEN_PARAM = 'edu_tg_bind.token'
# (连接超时, 读取超时)；webhook 必须尽快返回，出网不能无限等
TIMEOUT = (5, 8)
MAX_ERROR = 500


class EduTgBot(models.AbstractModel):
    _name = 'edu.tg.bot'
    _description = 'Telegram Bot API 客户端（edu_tg_bind 专用）'

    @api.model
    def _token(self):
        return (self.env['ir.config_parameter'].sudo().get_param(TOKEN_PARAM) or '').strip()

    @api.model
    def send_message(self, chat_id, text, reply_markup=None):
        """发一条私聊消息（可选带 inline keyboard）。

        :param reply_markup: 官方 InlineKeyboardMarkup 形状的 dict（见
            edu.tg.claim.reply_keyboard()）；**None = 不带键盘**。
            默认 None 是有意的：空池 / 繁忙这类纯文本回复的请求体与改造前**逐字节一致**，
            「加按钮」不影响任何既有分支。
        :return: (ok: bool, error: str)。**任何失败都只回报，不抛异常。**
        """
        token = self._token()
        if not token:
            # 未配置 token：不是异常，是一种「还没部署好」的状态，原样回报
            return False, '未配置系统参数 %s' % TOKEN_PARAM
        payload = {
            'chat_id': str(chat_id),
            'text': text,
            'disable_web_page_preview': True,
        }
        if reply_markup:
            # 只在真有键盘时加这个键：纯文本消息的 payload 保持原样
            payload['reply_markup'] = reply_markup
        try:
            resp = requests.post('%s/bot%s/sendMessage' % (API_BASE, token),
                                 json=payload, timeout=TIMEOUT)
        except requests.RequestException as exc:
            # 网络层失败（超时/DNS/连接被拒）——注意**不要把 token 写进日志**
            _logger.warning('edu_tg_bind: 发送失败（网络）：%s', type(exc).__name__)
            return False, '%s: %s' % (type(exc).__name__, str(exc)[:MAX_ERROR])
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {}
        if resp.status_code == 200 and data.get('ok'):
            return True, ''
        detail = data.get('description') or (resp.text or '')[:200]
        return False, 'HTTP %s: %s' % (resp.status_code, detail)
