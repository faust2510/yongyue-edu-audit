# -*- coding: utf-8 -*-
"""排课系统 · 并发兜底。

调研结论（docs/plans/timetable-design.md）：LGPL 基座 op.session 的冲突检测
是纯 Python @api.constrains，两个并发写入可以同时通过校验（双双穿透）。
这里用事务级 advisory lock 把课时的新增/修改串行化——学校规模极小，
全局写锁的代价可以忽略，换来的是冲突检测不可绕过。
"""
from odoo import api, models

_ADVISORY_KEY = 872401  # 固定常量：edu 排课写入锁（任意不冲突的 int）


class OpSession(models.Model):
    _inherit = 'op.session'

    @api.model_create_multi
    def create(self, vals_list):
        self.env.cr.execute('SELECT pg_advisory_xact_lock(%s)', (_ADVISORY_KEY,))
        return super().create(vals_list)

    def write(self, vals):
        self.env.cr.execute('SELECT pg_advisory_xact_lock(%s)', (_ADVISORY_KEY,))
        return super().write(vals)
