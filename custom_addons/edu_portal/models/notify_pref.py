# -*- coding: utf-8 -*-
"""站内通知偏好（第 5 批 A）。

事件×用户开关：用户在 /my/notify 自选接收哪些站内提醒。
发送统一走 edu.message._notify_event()：偏好为静音的事件不再建站内信；
其余发送点一律不经此 helper 的照旧直发（不受偏好影响）。
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# 站内提醒事件类目（key → 页面展示名）。新增提醒时同步登记到这里。
NOTIFY_EVENTS = [
    ('leave_result', '请假审批结果'),
    ('grade_result', '考试成绩录入'),
    ('assignment_graded', '作业批改'),
    ('journal_reviewed', '周记批阅'),
    ('subject_reg_result', '选课审批结果'),
    ('reimburse_result', '报销进展'),
    # C-1 改课影响面：调课通知（发件人=教务；收件人=任课教师+该班在读学生）
    ('session_change', '调课通知'),
    # 课代表（docs/plans/course-representative-design.md §3.4 / §4）：
    # 不登记 => 用户在 /my/notify 偏好页看不到这一类（静音开关失效）。
    ('course_rep_appointed', '课代表任命/撤销'),
    ('course_rep_notice', '课代表通知'),
    ('course_rep_expired', '课代表到期'),
    ('attendance_rep_submitted', '课代表点名待确认'),
    # 请假分级审批（S2，设计稿 §4.3(4)/§7.1）：转交审批 + 销假逾期提醒。
    # 不登记 => 用户在 /my/notify 偏好页看不到这两类（静音开关失效）。
    ('leave_transferred', '请假审批转交'),
    ('leave_return_overdue', '销假逾期提醒'),
]


class EduNotifyPref(models.Model):
    _name = 'edu.notify.pref'
    _description = '站内通知偏好'
    _order = 'event_key'

    user_id = fields.Many2one(
        'res.users', string='用户', required=True, index=True,
        ondelete='cascade')
    event_key = fields.Char(string='事件', required=True, index=True)
    muted = fields.Boolean(string='静音', default=False)

    _user_event_uniq = models.Constraint(
        'UNIQUE (user_id, event_key)',
        '同一事件只能有一条偏好。')


class EduMessage(models.Model):
    _inherit = 'edu.message'

    event_key = fields.Char(
        string='通知事件', index=True,
        help='由 _notify_event 写入的系统提醒的事件类目；人工私信为空。')

    @api.model
    def _notify_event(self, event_key, recipient_user, body,
                      sender_uid=None):
        """带偏好的系统提醒发送：静音则跳过，失败只告警不回滚。

        - recipient_user：res.users recordset（目标门户账号）；
        - sender_uid：默认当前用户（审批/录入的教师），可为 None（系统）。
        """
        if not recipient_user:
            return False
        try:
            muted = bool(self.env['edu.notify.pref'].sudo().search_count(
                [('user_id', '=', recipient_user.id),
                 ('event_key', '=', event_key),
                 ('muted', '=', True)]))
        except Exception:
            muted = False
        if muted:
            return False
        try:
            self.sudo().create({
                'sender_id': sender_uid or self.env.uid,
                'recipient_id': recipient_user.id,
                'body': body[:2000],
                'sent_at': fields.Datetime.now(),
                'event_key': event_key,
            })
            return True
        except Exception:
            _logger.warning('notify_event %s failed', event_key,
                            exc_info=True)
            return False
