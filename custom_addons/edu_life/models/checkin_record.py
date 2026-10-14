# -*- coding: utf-8 -*-
"""灵命生活：打卡记录。

edu.checkin.record：学生 x 类型 x 日期 唯一；创建时校验日期不得晚于今天。
月度统计用 Python 方法实现（校园数据量小，免 SQL 视图）；
连续天数 streak 按需求简化为「当月该类型打卡次数」。
"""
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class EduCheckinRecord(models.Model):
    _name = 'edu.checkin.record'
    _description = '打卡记录'
    _order = 'checkin_date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(string='名称', compute='_compute_name', store=True)
    student_id = fields.Many2one('op.student', string='学生',
                                 required=True, index=True,
                                 ondelete='cascade')
    type_id = fields.Many2one('edu.checkin.type', string='打卡类型',
                              required=True, index=True,
                              ondelete='cascade')
    checkin_date = fields.Date(string='打卡日期', required=True, index=True,
                               default=fields.Date.today)
    note = fields.Text(string='备注')

    # Odoo19 新约束 API：旧 _sql_constraints 会被框架静默忽略
    _rec_student_type_date_uniq = models.Constraint(
        'UNIQUE (student_id, type_id, checkin_date)',
        '同一学生同一类型同一天只能有一条打卡记录。')

    @api.depends('student_id', 'type_id', 'checkin_date')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s %s %s' % (
                rec.student_id.name or '?',
                rec.type_id.name or '?',
                rec.checkin_date or '')

    @api.model_create_multi
    def create(self, vals_list):
        today = fields.Date.context_today(self)
        for vals in vals_list:
            day = vals.get('checkin_date')
            if isinstance(day, str):
                day = fields.Date.to_date(day)
            if day and day > today:
                raise UserError('打卡日期不能晚于今天（%s）。' % day)
        return super().create(vals_list)

    @api.constrains('checkin_date')
    def _check_checkin_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.checkin_date and rec.checkin_date > today:
                raise ValidationError('打卡日期不能晚于今天。')

    @api.model
    def month_counts(self, student_id, month_start, month_end):
        """当月每类型打卡次数：返回 {type_id: count}。"""
        recs = self.sudo().search([
            ('student_id', '=', student_id),
            ('checkin_date', '>=', month_start),
            ('checkin_date', '<=', month_end),
        ])
        counts = {}
        for rec in recs:
            counts[rec.type_id.id] = counts.get(rec.type_id.id, 0) + 1
        return counts

    @api.model
    def month_done_set(self, student_id, month_start, month_end):
        """当月已打卡的 (date, type_id) 集合（月历渲染用）。"""
        recs = self.sudo().search([
            ('student_id', '=', student_id),
            ('checkin_date', '>=', month_start),
            ('checkin_date', '<=', month_end),
        ])
        return {(rec.checkin_date, rec.type_id.id) for rec in recs}

    @api.model
    def today_done_map(self, student_id, day):
        """某天已打卡的 {type_id: record}。"""
        recs = self.sudo().search([
            ('student_id', '=', student_id),
            ('checkin_date', '=', day),
        ])
        return {rec.type_id.id: rec for rec in recs}
