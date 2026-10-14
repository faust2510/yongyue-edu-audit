# -*- coding: utf-8 -*-
import datetime

from odoo import api, models


class EduTelegramOutboxPush(models.AbstractModel):
    """定时推送：待缴 / 作业截止 / 考试临近。挂 ir.cron 每日执行。"""
    _name = 'edu.telegram.push'
    _description = 'Telegram 定时推送'

    @api.model
    def cron_daily(self):
        env = self.env
        Chat = env['op.telegram.chat'].sudo()
        Out = env['edu.telegram.outbox'].sudo()
        today = datetime.date.today()

        def chats_of_students(students):
            chats = Chat.search([('student_id', 'in', students.ids)])
            return chats

        # 1) 待缴提醒
        Fees = env['op.student.fees.details'].sudo().search(
            [('state', '=', 'invoice')])
        by_chat = {}
        for f in Fees:
            if f.invoice_state == 'paid':
                continue
            for ch in chats_of_students(f.student_id):
                by_chat.setdefault(ch.id, [0.0, 0])
                if f.state != 'cancel':
                    by_chat[ch.id][0] += f.amount
                    by_chat[ch.id][1] += 1
        for cid, (amount, cnt) in by_chat.items():
            chat = Chat.browse(cid)
            name = chat.student_id.name or ''
            Out.enqueue(chat.chat_id,
                        "💰 缴费提醒：%s 你有 %d 笔待缴，合计 ¥%.2f。"
                        % (name, cnt, amount))

        # 2) 作业 24 小时内截止
        soon = datetime.datetime.now() + datetime.timedelta(days=1)
        Asg = env['op.assignment'].sudo().search(
            [('state', '=', 'publish'),
             ('submission_date', '>=', datetime.datetime.now()),
             ('submission_date', '<=', soon)])
        for a in Asg:
            for ch in chats_of_students(a.allocation_ids):
                Out.enqueue(ch.chat_id,
                            "⏰ 作业《%s》将于 %s 截止，记得提交！"
                            % (a.name,
                               a.submission_date.strftime('%m-%d %H:%M')))

        # 3) 考试 72 小时内开考（按课程在读学生）
        ex_soon = now3 = datetime.datetime.now() + datetime.timedelta(days=3)
        Exams = env['op.exam'].sudo().search(
            [('start_time', '>=', datetime.datetime.now()),
             ('start_time', '<=', now3), ('state', 'in', ['open', 'held'])])
        for e in Exams:
            students = env['op.student.course'].sudo().search(
                [('course_id', '=', e.course_id.id)]
            ).mapped('student_id')
            for ch in chats_of_students(students):
                Out.enqueue(
                    ch.chat_id,
                    "📝 考试提醒：%s 将于 %s 开考（满分 %d）。"
                    % (e.subject_id.name or e.name,
                       e.start_time.strftime('%m-%d %H:%M'),
                       e.total_marks))

        # 4) 教师未录成绩提醒（考试已结束且未录入）
        import datetime as _dt
        late_exams = env['op.exam'].sudo().search(
            [('end_time', '<', _dt.datetime.now()),
             ('results_entered', '=', False),
             ('state', 'in', ['done', 'open', 'held'])])
        seen = set()
        for e in late_exams:
            for fac in e.responsible_id:
                for ch in env['op.telegram.chat'].sudo().search(
                        [('faculty_id', '=', fac.id)]):
                    key = (ch.id, e.id)
                    if key in seen:
                        continue
                    seen.add(key)
                    Out.enqueue(
                        ch.chat_id,
                        "📝 提醒：考试 %s [%s] 已结束但成绩未录入。"
                        "回复 /成绩录入 进入录分页。"
                        % (e.subject_id.name or e.name, e.exam_code))
        _ = today
        return True
