# -*- coding: utf-8 -*-
"""Telegram webhook 入口 —— 只做三件事：验密钥、解包、交给 edu.tg.assist.bot。

⚠ 路由是 /telegram/assist/webhook，**刻意不占** /telegram/webhook
（那是生产上「匿名意见箱」模块在用的，见设计文档 §2 B3）。
"""
import hmac
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

WEBHOOK_PATH = '/telegram/assist/webhook'
SECRET_PARAM = 'edu_tg_assist.webhook_secret'


class EduTgAssistWebhook(http.Controller):

    @http.route(WEBHOOK_PATH, type='http', auth='public', csrf=False,
                methods=['POST'], save_session=False)
    def telegram_assist_webhook(self, **kw):
        # 鉴权：Telegram 每次都会带这个头（setWebhook 时设的 secret_token）。
        # 没配密钥 = 拒绝所有请求（宁可不可用，也不能让任何人伪造指令）。
        expected = (request.env['ir.config_parameter'].sudo()
                    .get_param(SECRET_PARAM) or '').strip()
        got = (request.httprequest.headers.get('X-Telegram-Bot-Api-Secret-Token') or '').strip()
        # 用 compare_digest 而不是 !=：比较耗时与内容无关，避免按字节猜密钥（时序侧信道）。
        # 两边都先 encode 成 bytes —— str 版 compare_digest 遇非 ASCII 会 TypeError（变成 500）。
        same = hmac.compare_digest(got.encode('utf-8'), expected.encode('utf-8'))
        if not expected or not same:
            _logger.warning('edu_tg_assist: webhook 密钥不匹配，已拒绝')
            return request.make_json_response({'ok': False, 'error': 'forbidden'}, status=403)

        update = request.httprequest.get_json(silent=True) or {}
        try:
            result = request.env['edu.tg.assist.bot'].sudo().handle_update(
                update, route='assist_webhook')
        except Exception as exc:  # noqa: BLE001 —— webhook 绝不能把异常抛回 Telegram
            _logger.exception('edu_tg_assist: 处理 update 失败：%s', type(exc).__name__)
            # 返回 200：让 Telegram 别重投（重投会重复发消息）
            return request.make_json_response({'ok': False, 'error': type(exc).__name__})
        return request.make_json_response(result if isinstance(result, dict) else {'ok': True})
