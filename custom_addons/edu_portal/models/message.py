# -*- coding: utf-8 -*-
"""v2.1-B9：轻量双向私信（edu.message）。

新表：发件人 user / 收件人 user / 正文 / 时间 / 已读 / 会话分组。
- 会话分组 thread_key：收发双方 user id 升序拼接（'12-34'），入库时自动算，
  供会话页（thread_key 等值查询）与「按收件人+已读」复合索引的常驻未读查询。
- 不做群聊、不做附件、不走 Discuss：本表只承载门户会话界面（messages.py），
  所有读写路径由控制器 sudo() + 熟人圈显式校验把关（与 B8 通讯录同一矩阵）。
- 权限交给控制器层：本模型不开放任何写权限给 portal/内部普通组，
  后台亦未见列表视图（避免绕过熟人圈直读他人私信）。
"""
from odoo import api, fields, models


class EduMessage(models.Model):
    _name = 'edu.message'
    _description = 'Lightweight Direct Message'
    _order = 'id asc'

    sender_id = fields.Many2one('res.users', string='Sender',
                                required=True, ondelete='cascade',
                                index=True)
    recipient_id = fields.Many2one('res.users', string='Recipient',
                                   required=True, ondelete='cascade',
                                   index=True)
    body = fields.Text(string='Body', required=True,
                       help='私信正文（首版纯文本，无附件）。')
    sent_at = fields.Datetime(string='Sent At', default=fields.Datetime.now,
                              index=True)
    is_read = fields.Boolean(string='Read', default=False, index=True,
                             help='收件人是否已读（打开会话即标记）。')
    # 会话分组：收发双方 user id 升序拼接，同对用户共用一组
    thread_key = fields.Char(string='Thread Key', index=True,
                             help='会话分组：双方 user id 升序拼接，'
                                  '如 "12-34"。入库时自动计算。')

    _body_not_blank = models.Constraint(
        "CHECK (body IS NOT NULL AND BTRIM(body) <> '')",
        'Private message body must not be blank.')

    @api.model_create_multi
    def create(self, vals_list):
        """入库时自动填会话分组（双方 id 升序），不依赖表单传入。"""
        for vals in vals_list:
            s_id = vals.get('sender_id')
            r_id = vals.get('recipient_id')
            if s_id and r_id:
                lo, hi = sorted((int(s_id), int(r_id)))
                vals['thread_key'] = '%d-%d' % (lo, hi)
        return super().create(vals_list)

    def _auto_init(self):
        """按收件人+已读建复合索引：未读角标与 30s 轮询的常驻查询
        （recipient_id, is_read）命中该索引，仅扫未读消息。"""
        res = super()._auto_init()
        self.env.cr.execute(
            'CREATE INDEX IF NOT EXISTS edu_message_recv_read_idx '
            'ON edu_message (recipient_id, is_read)')
        return res

    # ------------------------------------------------------------------
    # 便捷查询（仅控制器经 sudo 调用；本模型不开放对外权限）
    # ------------------------------------------------------------------
    def unread_count_for(self, user):
        """指定收件人的未读私信数。"""
        return self.search_count([
            ('recipient_id', '=', user.id), ('is_read', '=', False)])