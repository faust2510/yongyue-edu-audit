# -*- coding: utf-8 -*-
"""群/私聊登记 —— /notify 靠 alias 找群，不靠人肉记 chat_id。"""
from odoo import api, fields, models


class EduTgAssistChat(models.Model):
    _name = 'edu.tg.assist.chat'
    _description = 'Telegram 群/私聊登记'
    _order = 'alias, id'

    chat_id = fields.Char('Telegram chat_id', required=True, index=True,
                          help='机器人收到的 chat.id。唯一：同一个群只登记一次。')
    chat_type = fields.Selection([
        ('private', '私聊'),
        ('group', '群'),
        ('supergroup', '超级群'),
        ('channel', '频道'),
    ], string='类型', required=True, default='group')
    title = fields.Char('名称', help='Telegram 里的群名，自动抓取，可手改。')
    alias = fields.Char('短名', index=True,
                        help='给 /notify 用的短名，例如「行政」「清洁能源站」。唯一。')
    note = fields.Char('备注')
    notice_enabled = fields.Boolean(
        '接收网站公告', default=False, index=True,
        help='勾上以后，网站在后台发布公告时若勾了「Telegram」，这条公告会自动发到这个群。')
    active = fields.Boolean('启用', default=True)

    # Odoo 19 新约束 API（旧 _sql_constraints 只打 WARNING、不再被消费；见 edu_portal/models/alert_read.py:29）
    _chat_id_uniq = models.Constraint(
        'unique(chat_id)', '同一个 Telegram 会话只能登记一次。')
    _alias_uniq = models.Constraint(
        'unique(alias)', '短名必须唯一，否则 /notify 不知道该发哪个群。')

    @api.model
    def upsert_from_update(self, chat):
        """webhook 收到群消息时自动登记/更新。返回 recordset（可能为空）。"""
        cid = chat.get('id')
        if not cid:
            return self.browse()
        rec = self.sudo().search([('chat_id', '=', str(cid))], limit=1)
        vals = {
            'chat_type': chat.get('type') or 'group',
            'title': chat.get('title') or chat.get('username') or '',
        }
        if rec:
            rec.write(vals)
            return rec
        return self.sudo().create(dict(vals, chat_id=str(cid)))

    @api.model
    def find_by_alias(self, alias):
        alias = (alias or '').strip()
        if not alias:
            return self.browse()
        return self.sudo().search([('alias', '=', alias), ('active', '=', True)], limit=1)
