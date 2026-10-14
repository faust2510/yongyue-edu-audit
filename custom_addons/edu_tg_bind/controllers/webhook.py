# -*- coding: utf-8 -*-
"""Telegram 发码机器人 webhook —— /telegram/tgb/webhook（**新路径**）。

⚠ 路径选择不是小事：生产上「匿名意见箱」那个 edu_telegram 用的是 /telegram/webhook，
  本仓退役中的 v2.2 edu_telegram 也占着同一个路径。本模块**必须**另开一条，
  否则一装上就会与它们抢路由（设计 §1.3 / §13）。

鉴权（设计 §7）：官方头 X-Telegram-Bot-Api-Secret-Token + **fail-closed**
  （edu_tg_bind.webhook_secret 没配 = 一律 403，不是「没配就不校验」）。

回复形态：**正文 + inline keyboard 一起发**（正文由 edu.tg.claim.reply_text 出，
  键盘由 edu.tg.claim.reply_keyboard 单独出 —— 两者不焊死在一处，下一步加 Mini App
  的 web_app 按钮只动键盘那一处）。键盘只用 url 与 copy_text 两种按钮，**不产生任何
  callback_query 更新** ⇒ 生产 setWebhook 的 allowed_updates 无需改动（仍 ["message"]）。

处理顺序（设计 §5.6）：校验 -> 只认私聊 -> 领码（幂等 + 并发安全）
  -> **先落库 cr.commit()** -> 出网发回复 -> 记 notify_state -> 200。
  先落库的理由：任何时刻都成立「一个 TG 账号一张码」——不会出现「码已发到学生手机上、
  库里却没有记录」。出网失败保持 200（不 500）：码在库里，学生再发一条即重发同一张。
"""
import hmac
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

WEBHOOK_PATH = '/telegram/tgb/webhook'
SECRET_HEADER = 'X-Telegram-Bot-Api-Secret-Token'
SECRET_PARAM = 'edu_tg_bind.webhook_secret'

# 文案与领码流程的**唯一实现**都在 edu.tg.claim.handle_private_message：
# SCRTS 现在由前门 edu_tg_gate 分发（2026-10-08 用户裁定复用 @sctrs_bot），
# 这条自带路由与前门共用同一段代码，本文件只剩「验签 + 解包 + 转交」。


class EduTgBindWebhook(http.Controller):
    """只做三件事：验签、判私聊、把活交给模型。"""

    @http.route(WEBHOOK_PATH, type='http', auth='public', csrf=False,
                methods=['POST'], save_session=False)
    def telegram_tgb_webhook(self, **kw):
        env = request.env
        params = env['ir.config_parameter'].sudo()
        secret = (params.get_param(SECRET_PARAM) or '').strip()
        got = request.httprequest.headers.get(SECRET_HEADER) or ''
        # fail-closed：未配置 secret 时拒绝一切请求。
        # （本仓 v2.2 edu_telegram 的写法是「if secret and got != secret」——没配 secret 时
        #   谁都能打；本接口会发码，不能那样。）
        if not secret or not hmac.compare_digest(secret, got):
            _logger.warning('edu_tg_bind: webhook 鉴权失败（%s）',
                            '未配置 %s' % SECRET_PARAM if not secret else '请求头不匹配')
            return request.make_json_response({'ok': False, 'error': 'forbidden'},
                                             status=403)

        update = request.httprequest.get_json(silent=True) or {}
        message = update.get('message') or {}
        if not message:
            return request.make_json_response({'ok': True, 'ignored': 'not_private'})
        # 领码流程的唯一实现（前门 edu_tg_gate 调的也是它）
        result = env['edu.tg.claim'].sudo().handle_private_message(message)
        return request.make_json_response(result)
