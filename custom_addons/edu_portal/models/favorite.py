# -*- coding: utf-8 -*-
"""门户常用应用收藏（辅助增强包 3b）。

常用区此前仅存 localStorage（跨设备不同步）；本模型把「固定/排序」
结果落到服务端，SSR 直出收藏顺序，localStorage 保留为兜底。
卡片以 href 标识（与前端 data-app-href 一致）。
"""
from odoo import fields, models


class EduFavorite(models.Model):
    _name = 'edu.favorite'
    _description = '门户常用应用收藏'
    _order = 'sequence, id'

    user_id = fields.Many2one(
        'res.users', string='用户', required=True, index=True,
        ondelete='cascade')
    card_href = fields.Char(string='入口标识', required=True, index=True)
    sequence = fields.Integer(string='顺序', default=10)

    _card_uniq = models.Constraint(
        'UNIQUE (user_id, card_href)',
        '同一入口只收藏一次。')
