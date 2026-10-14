# -*- coding: utf-8 -*-
"""学生门户提交作业：在官方提交模型上补充附件能力 + 批改通知（辅助增强包 2a）。

op.assignment.sub.line 原生只有 description 文本；门户侧"上传作业文件"
用 Binary 字段落地（教师后台原生视图同样可见）。
批改提醒：state 流转到 accept/reject/change 或 marks 变更 → 站内信告知学生。
"""
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

_GRADE_LABEL = {'accept': '已通过', 'reject': '已驳回', 'change': '需修改'}


class OpAssignmentSubLine(models.Model):
    _inherit = 'op.assignment.sub.line'

    file = fields.Binary('作业附件')
    filename = fields.Char('附件名')

    def write(self, vals):
        watch = {'state', 'marks'} & set(vals)
        before = {r.id: (r.state, r.marks) for r in self} if watch else {}
        res = super().write(vals)
        if not watch:
            return res
        for rec in self:
            old = before.get(rec.id)
            if not old or (old[0] == rec.state and old[1] == rec.marks):
                continue
            user = rec.student_id.user_id
            if not user or user.id == self.env.uid:
                continue
            parts = []
            if old[0] != rec.state and rec.state in _GRADE_LABEL:
                parts.append('状态：%s' % _GRADE_LABEL[rec.state])
            if old[1] != rec.marks:
                parts.append('得分：%s' % rec.marks)
            if not parts:
                continue
            self.env['edu.message']._notify_event(
                'assignment_graded', user,
                '【作业批改】您的作业《%s》已批改（%s）。' % (
                    rec.assignment_id.name or '作业',
                    '；'.join(parts)))
        return res
