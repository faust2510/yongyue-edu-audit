# -*- coding: utf-8 -*-
"""通知气泡已读状态（每用户记录已读时的待办总数）。

D3 改造：水位从单值 last_total 升级为按类别的 seen_map
（{卡片key: 已读水位}），支持"点开某类提醒只清该类冒泡"。
last_total 字段保留兼容旧逻辑（roles.py 旧版全清路由仍会写入）。

另：edu.notice 的类别维度（B4 Circular tab）也挂在本文件——
notice.py 不在本实施代理的允许编辑清单内，用 _inherit 轻量补字段，
模块升级时 Odoo 会以默认值回填既有记录，无需数据迁移 XML。
"""
from odoo import fields, models


class EduAlertRead(models.Model):
    _name = 'edu.alert.read'
    _description = 'Per-user Alert Read State'

    user_id = fields.Many2one('res.users', required=True, index=True,
                              ondelete='cascade')
    # 旧版单值水位，保留兼容；新版按类别用下方 seen_map
    last_total = fields.Integer('Total At Last Read', default=0)
    seen_map = fields.Json(
        'Seen Watermarks Per Category', default=dict,
        help='{卡片key: 已读水位}。水位 = 最近一次标记已读时该类的计数，'
             '未读 = max(0, 当前计数 - 水位)，只升不降。')
    last_read = fields.Datetime(default=fields.Datetime.now)

    # Odoo 19 新约束 API：旧 _sql_constraints 只打一条 WARNING、约束根本不建库
    # （odoo/orm/model_classes.py:162-164 不再消费它，registry._sql_constraints
    # 只剩一个空 set）。本处自 Odoo 19 起一直没建成 —— 升级前 pg_indexes 里只有主键
    # 与 edu_alert_read__user_id_index（非唯一）。
    # 先例：edu_tg_bind/models/tg_claim.py、edu_portal/models/invite_code.py。
    _user_uniq = models.Constraint(
        'unique (user_id)', 'One read-state per user')

    def _raise_watermarks(self, counts):
        """把给定类别的已读水位提升到当前计数（只升不降）。

        :param counts: {category_key: 当前计数} dict
        """
        for rec in self:
            seen = dict(rec.seen_map or {})
            dirty = False
            for key, val in (counts or {}).items():
                val = int(val or 0)
                if val > seen.get(key, 0):
                    seen[key] = val
                    dirty = True
            if dirty:
                rec.write({'seen_map': seen})


class EduNotice(models.Model):
    """B4：布告栏类别维度（notice=通知 / circular=Circular 公告）。"""
    _inherit = 'edu.notice'

    category = fields.Selection(
        [('notice', '通知'), ('circular', 'Circular')],
        string='Category', default='notice', index=True,
        help='布告类别：通知 / Circular 公告。'
             '升级时既有记录自动回填为默认值 notice，无需数据迁移。')
