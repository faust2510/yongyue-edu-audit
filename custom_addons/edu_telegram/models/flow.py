# -*- coding: utf-8 -*-
from odoo import api, fields, models


class EduTelegramFlow(models.Model):
    """每会话的进行中多步对话状态（一次一个流）。"""
    _name = 'edu.telegram.flow'
    _description = 'Telegram 会话流程状态'

    chat_id = fields.Char(required=True, index=True)
    flow = fields.Char(required=True)      # hw / rsv / leave
    step = fields.Char(default='')
    data = fields.Text(default='{}')       # JSON 草稿

    _sql_constraints = [('chat_uniq', 'unique(chat_id)',
                        '每会话同时只能有一个进行中的流程')]

    @api.model
    def start(self, chat_id, flow, step='', data=None):
        import json
        F = self.env['edu.telegram.flow'].sudo()
        rec = F.search([('chat_id', '=', chat_id)], limit=1)
        vals = {'flow': flow, 'step': step,
                'data': json.dumps(data or {})}
        if rec:
            rec.write(vals)
        else:
            F.create(dict(vals, chat_id=chat_id))
        return True

    @api.model
    def get(self, chat_id):
        return self.env['edu.telegram.flow'].sudo().search(
            [('chat_id', '=', chat_id)], limit=1)

    @api.model
    def drop(self, chat_id):
        self.search([('chat_id', '=', chat_id)]).unlink()

    @api.model
    def set(self, rec, step=None, **data):
        import json
        d = json.loads(rec.data or '{}')
        d.update(data)
        rec.write({'data': json.dumps(d),
                   'step': step or rec.step})
