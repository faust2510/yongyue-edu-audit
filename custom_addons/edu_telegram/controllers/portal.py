# -*- coding: utf-8 -*-
"""网页端「Telegram 绑定」页：生成一次性绑定码、看绑定状态。"""
from odoo import http
from odoo.http import request


class TelegramBindingPortal(http.Controller):

    def _prepare(self):
        user = request.env.user
        Binding = request.env['edu.telegram.binding'].sudo()
        Chat = request.env['op.telegram.chat'].sudo()
        codes = Binding.search([('user_id', '=', user.id)],
                               order='id desc', limit=5)
        return {
            'user': user,
            'codes': codes,
            'chats': Chat.search(
                [('student_id.user_id', '=', user.id),
                 '|', ('faculty_id.user_id', '=', user.id),
                 ('parent_id.name.user_id', '=', user.id)]),
            'new_code': request.session.pop('tg_new_code', None),
        }

    @http.route('/my/telegram', type='http', auth='user', website=True)
    def telegram_binding(self, **kw):
        values = self._prepare()
        values['page_name'] = 'telegram'
        return request.render('edu_telegram.telegram_binding_page', values)

    @http.route('/my/telegram/new_code', type='http', auth='user',
                methods=['POST'], csrf=True)
    def telegram_new_code(self, **kw):
        rec = request.env['edu.telegram.binding'].sudo().issue()
        request.session['tg_new_code'] = rec.code
        return request.redirect('/my/telegram')
