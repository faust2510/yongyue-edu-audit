# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OpNotice(models.Model):
    """轻量公告：布告栏企业模块的 community 替身，发布即推 Telegram。"""
    _name = 'op.notice'
    _description = 'Telegram 公告'
    _order = 'id desc'

    title = fields.Char(required=True)
    body = fields.Text()
    priority = fields.Selection([('low', '低'), ('high', '高')],
                                default='low')
    pushed = fields.Boolean(default=False)

    @api.model
    def push_new(self):
        """cron：把未推送公告发给所有绑定会话。"""
        Out = self.env['edu.telegram.outbox'].sudo()
        chats = self.env['op.telegram.chat'].sudo().search([])
        last = int(self.env['ir.config_parameter'].sudo().get_param(
            'edu_telegram.last_notice_id', '0'))
        notices = self.sudo().search([('id', '>', last)], order='id asc')
        for n in notices:
            head = "📢 %s%s" % ('[重要] ' if n.priority == 'high' else '',
                                n.title)
            for c in chats:
                Out.enqueue(c.chat_id, "%s\n%s" % (head, n.body or '')[:2000])
            last = max(last, n.id)
        if notices:
            self.env['ir.config_parameter'].sudo().set_param(
                'edu_telegram.last_notice_id', str(last))
            notices.write({'pushed': True})
