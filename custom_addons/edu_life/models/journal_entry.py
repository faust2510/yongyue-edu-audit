# -*- coding: utf-8 -*-
"""灵命生活：学生周记。

edu.journal.entry：学生每周一篇（ISO 周次唯一），三态流转：
draft（草稿）-> submitted（已提交）-> reviewed（已批阅）。
教师批阅填写 feedback 并记录 reviewer_id，走 mail.thread 留痕。
"""
from odoo import api, fields, models


class EduJournalEntry(models.Model):
    _name = 'edu.journal.entry'
    _description = '学生周记'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'week desc, id desc'
    _rec_name = 'name'

    name = fields.Char(string='名称', compute='_compute_name', store=True)
    student_id = fields.Many2one('op.student', string='学生',
                                 required=True, index=True,
                                 ondelete='cascade')
    week = fields.Char(string='周次', size=8, required=True, index=True,
                       help='ISO 周次，格式如 2026-W34。')
    title = fields.Char(string='标题', size=200)
    content = fields.Text(string='正文')
    state = fields.Selection(
        [('draft', '草稿'), ('submitted', '已提交'), ('reviewed', '已批阅')],
        string='状态', default='draft', required=True, tracking=True)
    feedback = fields.Text(string='教师评语', tracking=True)
    reviewer_id = fields.Many2one('res.users', string='批阅教师',
                                  readonly=True)

    # 同一学生同一周只能有一篇周记
    _journal_student_week_uniq = models.Constraint(
        'UNIQUE (student_id, week)',
        '同一学生同一周次只能有一篇周记。')

    STATE_LABELS = {'draft': '草稿', 'submitted': '已提交',
                    'reviewed': '已批阅'}
    STATE_BADGES = {'draft': 'text-bg-secondary',
                    'submitted': 'text-bg-warning',
                    'reviewed': 'text-bg-success'}

    @api.depends('student_id', 'week')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s %s' % (rec.student_id.name or '?', rec.week or '?')

    def state_label(self):
        self.ensure_one()
        return self.STATE_LABELS.get(self.state, self.state)

    def state_badge(self):
        self.ensure_one()
        return self.STATE_BADGES.get(self.state, 'text-bg-secondary')
