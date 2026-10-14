# -*- coding: utf-8 -*-
from odoo import api, fields, models


class EduTelegramOutbox(models.Model):
    """待发送消息队列：webhook 入队，宿主中继经代理调 API 发送。"""
    _name = 'edu.telegram.outbox'
    _description = 'Telegram 发件队列'
    _order = 'id asc'

    chat_id = fields.Char(required=True)
    method = fields.Char(default='sendMessage')
    message_id = fields.Integer()   # editMessageText 用
    text = fields.Text(required=True)
    keyboard = fields.Text()   # JSON：回复键盘或 inline 键盘
    sent = fields.Boolean(default=False, index=True)
    tries = fields.Integer(default=0)

    @api.model
    def enqueue(self, chat_id, text, keyboard=None, method='sendMessage',
                message_id=0):
        self.sudo().create({'chat_id': str(chat_id), 'text': text,
                            'keyboard': keyboard, 'method': method,
                            'message_id': message_id})
