# -*- coding: utf-8 -*-
"""LMS 在线课程：课次与学习进度（自研）。

概念参照社区版 website_slides（LGPL）的「课程→课次→学员进度」三层结构，
全部代码从零实现；课程容器复用基座 op.subject。
设计文档：docs/plans/lms-design.md
"""
from odoo import fields, models


class EduLesson(models.Model):
    _name = 'edu.lesson'
    _description = 'LMS 课次'
    _order = 'subject_id, sequence, id'

    subject_id = fields.Many2one(
        'op.subject', string='课程', required=True,
        ondelete='cascade', index=True)
    name = fields.Char(string='课次标题', required=True)
    type = fields.Selection(
        [('video', '视频'), ('article', '图文')],
        string='类型', default='video', required=True)
    video_url = fields.Char(
        string='视频嵌入地址', help='仅支持 https 的可嵌入播放页地址')
    content_html = fields.Html(string='图文正文')
    sequence = fields.Integer(string='排序', default=10)
    state = fields.Selection(
        [('draft', '草稿'), ('published', '已发布')],
        string='状态', default='draft', required=True, index=True)

    # ---- 顺序解锁（语义抄 Canvas Modules：unlock_at /
    # require_sequential_progress / prerequisite + state 四态）----
    require_sequential = fields.Boolean(
        string='需按顺序解锁', default=False,
        help='勾选后必须完成上一课次（按排序）才能学习本课次。')
    unlock_at = fields.Datetime(
        string='定时解锁', help='到达该时间前保持锁定；留空表示不限时。')
    prerequisite_lesson_id = fields.Many2one(
        'edu.lesson', string='前置课次', ondelete='set null',
        help='指定后必须完成该课次才解锁；优先于「按顺序解锁」。')
    lock_state = fields.Selection(
        [('locked', '未解锁'), ('unlocked', '可学习'),
         ('started', '学习中'), ('completed', '已完成')],
        string='解锁状态', compute='_compute_lock_state', store=False)

    # 独立评审 #6/#8：课次标题同课程内唯一；视频地址必须 https 或留空
    _lesson_subject_name_uniq = models.Constraint(
        'UNIQUE (subject_id, name)',
        '同一课程下课次标题不能重复。')
    _lesson_video_url_https = models.Constraint(
        "CHECK (video_url LIKE 'https://%' OR video_url IS NULL)",
        '视频嵌入地址必须以 https:// 开头（或留空）。')

    def _compute_lock_state(self):
        """按当前登录用户的学员身份计算四态（非学员按「可学习」展示）。"""
        student = self.env['op.student'].sudo().search(
            [('user_id', '=', self.env.uid)], limit=1)
        for rec in self:
            rec.lock_state = rec.lock_state_for(student)

    def _prev_published_lesson(self):
        self.ensure_one()
        return self.sudo().search(
            [('subject_id', '=', self.subject_id.id),
             ('state', '=', 'published'),
             ('sequence', '<', self.sequence)],
            order='sequence desc, id desc', limit=1)

    def lock_state_for(self, student):
        """四态：completed > started > locked > unlocked（Canvas 口径）。

        锁定条件（任一满足即 locked）：定时未到；前置课次未完成；
        勾了顺序解锁而上一课次未完成。无学员身份（教师/教务）不锁。
        """
        self.ensure_one()
        if not student:
            return 'unlocked'
        prog = self.env['edu.lesson.progress'].sudo().search(
            [('lesson_id', '=', self.id),
             ('student_id', '=', student.id)], limit=1)
        if prog and prog.state == 'done':
            return 'completed'
        if self.unlock_at and fields.Datetime.now() < self.unlock_at:
            return 'locked'
        req = self.prerequisite_lesson_id or (
            self._prev_published_lesson() if self.require_sequential else None)
        if req:
            done = self.env['edu.lesson.progress'].sudo().search_count(
                [('lesson_id', '=', req.id),
                 ('student_id', '=', student.id),
                 ('state', '=', 'done')])
            if not done:
                return 'locked'
        return 'started' if prog else 'unlocked'

    def lock_state_map(self, student):
        """批量四态 {lesson_id: state}，避免逐条查库（列表页用）。"""
        out = {}
        for rec in self:
            out[rec.id] = rec.lock_state_for(student)
        return out

    def mark_done(self, student):
        """学生把当前课次标记为完成。

        幂等语义：已完成则不再改动 completed_date。
        并发兜底：search→create 竞态触发 UNIQUE 时经 savepoint
        捕获并回读既有记录，不向用户抛 500（独立评审 #5）。
        """
        self.ensure_one()
        # 锁定课次不可标记完成（与门户按钮门禁同口径，后端直调同样拦住）
        if self.lock_state_for(student) == 'locked':
            return None
        Prog = self.env['edu.lesson.progress'].sudo()
        domain = [('lesson_id', '=', self.id),
                  ('student_id', '=', student.id)]
        vals = {'state': 'done', 'completed_date': fields.Date.today()}
        rec = Prog.search(domain, limit=1)
        if rec:
            if rec.state != 'done':
                rec.write(vals)
            return rec
        try:
            with self.env.cr.savepoint():
                return Prog.create({
                    'lesson_id': self.id,
                    'student_id': student.id, **vals})
        except Exception:
            rec = Prog.search(domain, limit=1)
            if rec and rec.state != 'done':
                rec.write(vals)
            return rec


class EduLessonProgress(models.Model):
    _name = 'edu.lesson.progress'
    _description = 'LMS 学习进度'
    _order = 'completed_date desc, id desc'

    lesson_id = fields.Many2one(
        'edu.lesson', string='课次', required=True,
        ondelete='cascade', index=True)
    student_id = fields.Many2one(
        'op.student', string='学生', required=True,
        ondelete='cascade', index=True)
    state = fields.Selection(
        [('draft', '进行中'), ('done', '已完成')],
        string='状态', default='draft', required=True, index=True)
    completed_date = fields.Date(string='完成日期')
    subject_id = fields.Many2one(
        related='lesson_id.subject_id', string='课程', readonly=True)

    # Odoo19 新约束 API（旧 _sql_constraints 会被静默忽略）
    _progress_student_lesson_uniq = models.Constraint(
        'UNIQUE (student_id, lesson_id)',
        '同一名学生对同一门课次只能有一条学习进度记录。')
