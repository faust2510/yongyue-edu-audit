# -*- coding: utf-8 -*-
"""iCal 日历订阅：res.users 订阅令牌。

用户在校历页获取带令牌的订阅链接，手机/Outlook/Google 日历订阅后
课表、考试、停课、活动自动同步（参考 Moodle/Canvas Calendar Feed）。
"""
import secrets

from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    edu_ical_token = fields.Char(string='日历订阅令牌', copy=False)

    def _ensure_ical_token(self):
        """懒生成订阅令牌（首次访问日历页时写入，之后稳定不变）。"""
        self.ensure_one()
        if not self.edu_ical_token:
            self.sudo().write(
                {'edu_ical_token': secrets.token_hex(16)})
        return self.edu_ical_token
