# -*- coding: utf-8 -*-
"""在线测验：测验 / 题目 / 作答记录。"""
from odoo import api, fields, models


class EduQuiz(models.Model):
    _name = 'edu.quiz'
    _description = 'Online Quiz'
    _inherit = ['mail.thread']

    name = fields.Char('Quiz Name', required=True)
    category = fields.Char('Category')
    course_id = fields.Many2one('op.course', 'Course')
    duration = fields.Integer('Duration (min)', default=15)
    question_ids = fields.One2many('edu.quiz.question', 'quiz_id', 'Questions')
    total_points = fields.Float(compute='_compute_total_points', store=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('published', 'Published'), ('closed', 'Closed')],
        default='draft')

    def action_publish(self):
        self.state = 'published'

    def action_close(self):
        self.state = 'closed'

    @api.depends('question_ids.points')
    def _compute_total_points(self):
        for quiz in self:
            quiz.total_points = sum(quiz.question_ids.mapped('points'))


class EduQuizQuestion(models.Model):
    _name = 'edu.quiz.question'
    _description = 'Quiz Question'
    _order = 'sequence, id'

    quiz_id = fields.Many2one('edu.quiz', required=True,
                              ondelete='cascade')
    sequence = fields.Integer(default=10)
    question = fields.Text('Question', required=True)
    qtype = fields.Selection(
        [('single', 'Single Choice'), ('multi', 'Multiple Choice'),
         ('text', 'Short Answer')], default='single', required=True)
    option_a = fields.Char('Option A')
    option_b = fields.Char('Option B')
    option_c = fields.Char('Option C')
    option_d = fields.Char('Option D')
    answer = fields.Char(
        'Correct Answer', help="正确选项字母（A/B/C/D）或简答题标准答案关键词")
    points = fields.Float('Points', default=1.0)


class EduQuizAttempt(models.Model):
    _name = 'edu.quiz.attempt'
    _description = 'Quiz Attempt'
    _order = 'create_date desc'

    quiz_id = fields.Many2one('edu.quiz', required=True)
    student_id = fields.Many2one('op.student', 'Student', required=True)
    score = fields.Float('Score')
    total = fields.Float('Total Points')
    pct_str = fields.Char('Percentage', compute='_compute_pct')
    state = fields.Selection(
        [('in_progress', 'In Progress'), ('submitted', 'Submitted')],
        default='submitted')
    answers_json = fields.Text('Answers')

    @api.depends('score', 'total')
    def _compute_pct(self):
        for r in self:
            r.pct_str = (f"{round(r.score * 100.0 / r.total)}%"
                         if r.total else '0%')
