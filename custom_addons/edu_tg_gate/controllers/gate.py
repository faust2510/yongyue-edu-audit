# -*- coding: utf-8 -*-
"""SCRTS 前门 —— /telegram/sctrs/webhook。

⚠ 路由是**新的第三条**：既不占 /telegram/webhook（生产匿名意见箱），
  也不占 /telegram/tgb/webhook（edu_tg_bind 自带那条，保留作一键回滚）。
  见本模块 __manifest__.py 的边界 B7。

鉴权照抄 edu_tg_bind：官方头 X-Telegram-Bot-Api-Secret-Token + hmac.compare_digest +
**fail-closed**（edu_tg_gate.webhook_secret 没配 = 一律 403，不是「没配就不校验」）。

处理顺序：验签 → 解包 → edu.tg.gate.router.dispatch() → 200。
  任何异常都兜住并返回 200：让 Telegram 别重投（重投 = 重复发消息 / 重复领码请求）。
"""
import hmac
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

WEBHOOK_PATH = '/telegram/sctrs/webhook'
SECRET_HEADER = 'X-Telegram-Bot-Api-Secret-Token'
SECRET_PARAM = 'edu_tg_gate.webhook_secret'


class EduTgGateWebhook(http.Controller):
    """只做三件事：验签、解包、交给 edu.tg.gate.router。"""

    @http.route(WEBHOOK_PATH, type='http', auth='public', csrf=False,
                methods=['POST'], save_session=False)
    def telegram_sctrs_webhook(self, **kw):
        params = request.env['ir.config_parameter'].sudo()
        secret = (params.get_param(SECRET_PARAM) or '').strip()
        got = request.httprequest.headers.get(SECRET_HEADER) or ''
        # fail-closed：未配置 secret 时拒绝一切请求（gh_auth 宁可不可用，也不让任何人伪造指令）。
        if not secret or not hmac.compare_digest(secret, got):
            _logger.warning('edu_tg_gate: 前门鉴权失败（%s）',
                            '未配置 %s' % SECRET_PARAM if not secret else '请求头不匹配')
            return request.make_json_response({'ok': False, 'error': 'forbidden'},
                                             status=403)

        update = request.httprequest.get_json(silent=True) or {}
        try:
            result = request.env['edu.tg.gate.router'].sudo().dispatch(update)
        except Exception as exc:  # noqa: BLE001 —— webhook 绝不能把异常抛回 Telegram
            _logger.exception('edu_tg_gate: 分发失败：%s', type(exc).__name__)
            return request.make_json_response({'ok': False, 'error': type(exc).__name__})
        return request.make_json_response(result if isinstance(result, dict) else {'ok': True})
