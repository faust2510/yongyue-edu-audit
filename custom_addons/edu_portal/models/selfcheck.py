# -*- coding: utf-8 -*-
"""考勤自助签到令牌（第 5 批 B，参考 Moodle Attendance 限时 QR 防代签）。

教师为「班级+日期」开启自助签到后获得轮换令牌（默认 60 秒有效，
刷新即作废旧令牌发新令牌）；学生手机扫码在有效期内把自己在该日
点名表中的记录置为到堂。令牌表不含任何学生数据，审计走考勤行本身。
"""
import secrets

from odoo import fields, models


class EduAttendSelfToken(models.Model):
    _name = 'edu.attend.self.token'
    _description = '考勤自助签到令牌'
    _order = 'create_date desc, id desc'

    batch_id = fields.Many2one(
        'op.batch', string='班级', required=True, index=True,
        ondelete='cascade')
    checkin_date = fields.Date(string='点名日期', required=True, index=True)
    token = fields.Char(
        string='令牌', required=True, index=True, copy=False,
        default=lambda self: secrets.token_urlsafe(16))
    expire_at = fields.Datetime(
        string='过期时间', required=True,
        help='超过该时间令牌失效；教师端刷新即作废旧令牌并签发新令牌。')
    active = fields.Boolean(string='有效', default=True, index=True)

    def invalidate_batch_date(self, batch_id, checkin_date):
        """作废某班某日全部令牌（教师关闭自助签到/发新令牌前调用）。"""
        self.search([
            ('batch_id', '=', batch_id),
            ('checkin_date', '=', checkin_date),
            ('active', '=', True),
        ]).write({'active': False})
