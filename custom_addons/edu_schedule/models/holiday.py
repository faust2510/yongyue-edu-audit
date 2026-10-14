# -*- coding: utf-8 -*-
"""停课日：周期排课与整周复制自动避开；单节停课直接在课节列表取消。"""
from odoo import fields, models


class EduScheduleHoliday(models.Model):
    _name = 'edu.schedule.holiday'
    _description = '停课日'
    _order = 'date_start desc, id desc'

    name = fields.Char('事由', required=True)
    date_start = fields.Date('开始日期', required=True)
    date_end = fields.Date('结束日期', required=True)
    # 空 = 全校停课；指定班级 = 仅该班停课
    batch_id = fields.Many2one('op.batch', string='班级（空=全校）')
    active = fields.Boolean('启用', default=True)

    _date_order = models.Constraint(
        'CHECK (date_end >= date_start)',
        '结束日期不能早于开始日期。')

    def _matches(self, day, batch_id):
        """day(datetime.date) 是否落在停课范围且作用于该班级。"""
        self.ensure_one()
        if not self.active:
            return False
        if not (self.date_start <= day <= self.date_end):
            return False
        return not self.batch_id or not batch_id \
            or self.batch_id.id == batch_id
