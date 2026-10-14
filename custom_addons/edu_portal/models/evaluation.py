# -*- coding: utf-8 -*-
"""评估中心：三大评估统一引擎（v2-P2 自研）。

PRD：docs/plans/eval-design.md 与 行政管理系统功能/方案-老师端评估中心.md
- 模板(评分项+等级线可配) → 任务(学生×模板×维度) → 逐项打分 → 自动总分/等级
- 实习三维 = 同学生多张任务按 evaluator_type 聚合
- 权限：教师/管理员建与打分；审批/删除仅管理员；intern 结果对学生隐藏
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

TYPE_CODES = [
    ('freshman', '新生综合测试'),
    ('student', '学生综合评估'),
    ('intern', '实习同工评估'),
]


class EduEvalTemplate(models.Model):
    _name = 'edu.eval.template'
    _description = '评估模板'

    name = fields.Char(string='模板名称', required=True)
    type_code = fields.Selection(
        TYPE_CODES, string='评估类型', required=True, index=True)
    total = fields.Float(string='满分', default=100.0, required=True)
    pass_line = fields.Float(string='及格线', default=60.0, required=True)
    excellent_line = fields.Float(string='优秀线', default=90.0, required=True)
    visible_to_student = fields.Boolean(string='结果对学生可见', default=True)
    line_ids = fields.One2many(
        'edu.eval.template.line', 'template_id', string='评分项')
    line_count = fields.Integer(compute='_compute_line_count')

    def _compute_line_count(self):
        for tpl in self:
            tpl.line_count = len(tpl.line_ids)

    @api.constrains('pass_line', 'excellent_line', 'total')
    def _check_lines(self):
        for tpl in self:
            if not (0 < tpl.pass_line <= tpl.excellent_line <= tpl.total):
                raise ValidationError(
                    '等级线需满足：0 < 及格线 ≤ 优秀线 ≤ 满分。')


class EduEvalTemplateLine(models.Model):
    _name = 'edu.eval.template.line'
    _description = '评估评分项'
    _order = 'sequence, id'

    template_id = fields.Many2one(
        'edu.eval.template', string='模板', required=True,
        ondelete='cascade', index=True)
    name = fields.Char(string='评分项', required=True)
    max_score = fields.Float(string='满分', default=10.0, required=True)
    sequence = fields.Integer(string='排序', default=10)

    @api.constrains('max_score')
    def _check_max(self):
        for rec in self:
            if rec.max_score <= 0:
                raise ValidationError('评分项满分必须大于零。')


class EduEvalTask(models.Model):
    _name = 'edu.eval.task'
    _description = '评估任务'
    _order = 'create_date desc, id desc'

    template_id = fields.Many2one(
        'edu.eval.template', string='评分模板', required=True, index=True)
    student_id = fields.Many2one(
        'op.student', string='被评估学生', required=True,
        index=True, ondelete='cascade')
    evaluator_type = fields.Selection(
        [('teacher', '教师评'), ('self', '自评'),
         ('ta', 'TA评'), ('pastor', '牧者评')],
        string='评估维度', default='teacher', required=True)
    period = fields.Char(
        string='评估周期', default=lambda self: '2026秋', required=True)
    state = fields.Selection(
        [('draft', '草稿'), ('scoring', '打分中'), ('done', '已完成')],
        string='状态', default='scoring', required=True, index=True)
    score_ids = fields.One2many('edu.eval.score', 'task_id', string='打分')
    total_score = fields.Float(
        string='总分', compute='_compute_totals', store=True)
    grade = fields.Selection(
        [('fail', '不合格'), ('pass', '合格'), ('excellent', '优秀')],
        string='等级', compute='_compute_totals', store=True, index=True)
    approved_by = fields.Many2one('res.users', string='批准人', readonly=True)
    approved_date = fields.Date(string='批准日期', readonly=True)
    type_code = fields.Selection(
        related='template_id.type_code', string='评估类型', store=True)
    visible_to_student = fields.Boolean(
        related='template_id.visible_to_student', readonly=True)

    @api.depends('score_ids.score', 'template_id.pass_line',
                 'template_id.excellent_line')
    def _compute_totals(self):
        for task in self:
            total = sum(task.score_ids.mapped('score'))
            task.total_score = total
            if not task.template_id:
                task.grade = False
                continue
            if total >= task.template_id.excellent_line:
                task.grade = 'excellent'
            elif total >= task.template_id.pass_line:
                task.grade = 'pass'
            else:
                task.grade = 'fail'

    def action_approve(self):
        """管理员确认完成（仅 base.group_system）。"""
        if not self.env.user.has_group('base.group_system'):
            raise ValidationError('仅系统管理员可以批准评估任务。')
        self.write({'state': 'done',
                    'approved_by': self.env.user.id,
                    'approved_date': fields.Date.today()})


class EduEvalScore(models.Model):
    _name = 'edu.eval.score'
    _description = '评估打分明细'

    task_id = fields.Many2one(
        'edu.eval.task', string='评估任务', required=True,
        ondelete='cascade', index=True)
    template_line_id = fields.Many2one(
        'edu.eval.template.line', string='评分项', required=True,
        ondelete='cascade')
    score = fields.Float(string='得分', required=True)

    # Odoo19 新约束 API：同一任务同一评分项仅一条
    _score_task_line_uniq = models.Constraint(
        'UNIQUE (task_id, template_line_id)',
        '同一任务的每个评分项只能有一条得分。')

    @api.constrains('score', 'template_line_id')
    def _check_score_range(self):
        for rec in self:
            if rec.score < 0 or rec.score > rec.template_line_id.max_score:
                raise ValidationError(
                    f'「{rec.template_line_id.name}」得分须在 0 ~ '
                    f'{rec.template_line_id.max_score:g} 之间。')
