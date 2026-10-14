# -*- coding: utf-8 -*-
"""福利系统组轻量模型：学生自助打卡 + 积分基础版。

edu.daily.checkin：学生每日打卡（到堂/灵修/读经），一人一日一条（SQL 唯一约束）。
edu.point.log：通用加减分流水，对象二选一（学生 或 教师用户），
由 Python 约束保证 person_kind 与对应目标字段配套必填。

写路径纪律：门户侧一律控制器 sudo() + 归属校验后读写本人数据，
ACL 仅放最小读权限，避免越权直写。
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EduDailyCheckin(models.Model):
    _name = 'edu.daily.checkin'
    _description = 'Edu Daily Checkin'
    _order = 'date desc, id desc'
    _rec_name = 'name'

    name = fields.Char('名称', compute='_compute_name', store=True)
    student_id = fields.Many2one('op.student', string='学生',
                                 required=True, index=True,
                                 ondelete='cascade')
    date = fields.Date(string='日期', required=True, index=True,
                       default=fields.Date.today)
    attend = fields.Boolean(string='到堂')
    devotion = fields.Boolean(string='灵修')
    devotion_note = fields.Text(string='灵修笔记')
    bible_passage = fields.Char(string='读经范围', size=128,
                                help='如：约3章、诗23篇；创1-3章')
    bible_note = fields.Text(string='读经笔记')

    # Odoo19 新约束 API：旧 _sql_constraints 会被框架静默忽略（升级日志有警告）
    _checkin_student_date_uniq = models.Constraint(
        'UNIQUE (student_id, date)',
        '同一学生同一天只能有一条打卡记录。')

    @api.depends('student_id', 'date')
    def _compute_name(self):
        for rec in self:
            stu = rec.student_id.name or '?'
            rec.name = '%s %s' % (stu, rec.date or '')


class EduPointLog(models.Model):
    _name = 'edu.point.log'
    _description = 'Edu Point Log'
    _order = 'date desc, id desc'

    name = fields.Char('摘要', compute='_compute_name', store=True)
    person_kind = fields.Selection(
        [('student', '学生'), ('teacher', '教师')],
        string='对象类型', required=True, default='student',
        help='加分/减分对象的类型：学生或教师用户。')
    student_id = fields.Many2one('op.student', string='学生',
                                 ondelete='cascade', index=True)
    teacher_user_id = fields.Many2one('res.users', string='教师用户',
                                      ondelete='cascade', index=True)
    delta = fields.Integer(string='分值',
                           help='正数加分，负数减分，不能为 0。')
    reason = fields.Char(string='原因', size=256)
    note = fields.Text(string='备注')
    granted_by = fields.Many2one('res.users', string='操作人',
                                 default=lambda self: self.env.user)
    date = fields.Datetime(string='时间', default=fields.Datetime.now)

    @api.constrains('person_kind', 'student_id', 'teacher_user_id',
                    'delta', 'reason')
    def _check_target(self):
        for rec in self:
            if rec.person_kind == 'student' and not rec.student_id:
                raise ValidationError('学生积分必须选择对应的学生。')
            if rec.person_kind == 'teacher' and not rec.teacher_user_id:
                raise ValidationError('教师积分必须选择对应的教师用户。')
            if not rec.delta:
                raise ValidationError('分值不能为 0。')

    @api.depends('student_id', 'teacher_user_id', 'delta', 'reason')
    def _compute_name(self):
        for rec in self:
            who = rec.student_id.name or rec.teacher_user_id.name or '?'
            sign = '+' if (rec.delta or 0) > 0 else ''
            rec.name = '%s %s%s %s' % (
                who, sign, rec.delta or 0, rec.reason or '')
