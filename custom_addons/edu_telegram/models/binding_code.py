# -*- coding: utf-8 -*-
import secrets
from datetime import timedelta

from odoo import api, fields, models

ROLE_BY_MODEL = {'op.student': 'student', 'op.faculty': 'faculty',
                 'op.parent': 'parent'}


class EduTelegramBindingCode(models.Model):
    """一次性 Telegram 绑定码：网页端生成，聊天里 /start <code> 消费。"""
    _name = 'edu.telegram.binding'
    _description = 'Telegram 绑定码'

    code = fields.Char(required=True, index=True)
    user_id = fields.Many2one('res.users', required=True, ondelete='cascade')
    expire_on = fields.Datetime(required=True)
    used = fields.Boolean(default=True)
    used_by_chat = fields.Char(readonly=True)

    _sql_constraints = [('code_uniq', 'unique(code)', '绑定码必须唯一')]

    @api.model
    def issue(self, user=None):
        user = user or request_user()
        rec = self.sudo().create({
            'code': secrets.token_hex(4).upper(),  # 8 位一次性码
            'user_id': user.id,
            'expire_on': fields.Datetime.now() + timedelta(days=7),
            'used': False,
        })
        return rec

    @api.model
    def consume(self, code, chat_id):
        """校验并消费绑定码，返回 (role, record)。失败不烧码。"""
        rec = self.sudo().search(
            [('code', '=', code.upper()), ('used', '=', False)], limit=1)
        if not rec or rec.expire_on < fields.Datetime.now():
            return None, None
        resolved = self._resolve(rec.user_id)
        if not resolved:
            return None, None
        rec.write({'used': True, 'used_by_chat': chat_id})
        return resolved

    def _resolve(self, user):
        """用户 -> (role, record)。学生/家长按自身 user_id，
        教师经 HR 档案或 partner 关联。"""
        user = user.sudo()
        r = self.env['op.student'].sudo().search(
            [('user_id', '=', user.id)], limit=1)
        if r:
            return 'student', r
        r = self.env['op.parent'].sudo().search(
            ['|', ('user_id', '=', user.id),
             ('name.user_id', '=', user.id)], limit=1)
        if r:
            return 'parent', r
        r = self.env['op.faculty'].sudo().search(
            ['|', ('emp_id.user_id', '=', user.id),
             ('partner_id', '=', user.partner_id.id)], limit=1)
        if r:
            return 'faculty', r
        return None


def request_user():
    from odoo.http import request
    return request.env.user
