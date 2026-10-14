# -*- coding: utf-8 -*-
from odoo import models


class OpSessionTelegramHook(models.Model):
    """课表变更推送：session 关键字段变化时通知已绑定的学生与教师。"""
    _inherit = 'op.session'

    WATCH = {'start_datetime', 'end_datetime', 'classroom_id',
             'subject_id', 'faculty_id', 'state'}

    def write(self, vals):
        changed = self.WATCH & set(vals)
        res = super().write(vals)
        if changed:
            self._tg_notify_change()
        return res

    def _tg_notify_change(self):
        Out = self.env['edu.telegram.outbox'].sudo()
        Chat = self.env['op.telegram.chat'].sudo()
        SC = self.env['op.student.course'].sudo()
        for s in self:
            lines = ["📅 课表变更：%s" % (s.subject_id.name or '课程'),
                     "时间：%s" % s.start_datetime.strftime('%m-%d %H:%M'),
                     "教室：%s" % (s.classroom_id.name or '待定')]
            text = "\n".join(lines)[:2000]
            students = SC.search(
                [('batch_id', '=', s.batch_id.id)]
            ).mapped('student_id') if s.batch_id else self.env['op.student']
            chats = Chat.search([
                '|', ('faculty_id', '=', s.faculty_id.id),
                ('student_id', 'in', students.ids)])
            for c in chats:
                Out.enqueue(c.chat_id, text)
