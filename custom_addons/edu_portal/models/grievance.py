# -*- coding: utf-8 -*-
"""学生申诉（Grievance）轻量模型。

社区版 OpenEduCat 没有申诉模型（企业版 openeducat_grievance 才有），
这里自建轻量模型支撑 /my/grievances 页面，字段对齐原站参考 DOM：
主题 / 类别 / 状态（草稿/已提交/审查中/解决/拒绝/关闭）+ 创建日期。
"""
import datetime
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from .leave import escalate_hours, notify_approvers

_logger = logging.getLogger(__name__)


class EduGrievance(models.Model):
    _name = 'edu.grievance'
    _description = 'Student Grievance'
    _order = 'date desc, id desc'

    name = fields.Char('Reference No', size=64)
    student_id = fields.Many2one('op.student', 'Student')
    subject = fields.Char('Subject', size=256)
    category = fields.Char('Category', size=128)
    description = fields.Text('Description')
    state = fields.Selection(
        [('draft', 'Draft'),
         ('submitted', 'Submitted'),
         ('in_progress', 'In Progress'),
         ('resolve', 'Resolved'),
         ('reject', 'Rejected'),
         ('close', 'Closed')],
        string='Status', default='submitted')
    date = fields.Date('Created Date', default=fields.Date.today)
    reject_reason = fields.Text('驳回原因')
    active = fields.Boolean('Active', default=True)
    # F1 超时升级：非空即视为已升级提醒过（cron 幂等去重）
    escalated_at = fields.Datetime('升级提醒时间', readonly=True, copy=False)

    def _approval_targets(self):
        # 后台表单按钮经 @api.model 调用时 self 为空，回退到上下文 active_ids
        return self or self.browse(self.env.context.get('active_ids') or [])

    # A1：处理结果 → 通知文案（B5 通知引擎）；开始处理非审批结果，不通知
    _NOTIFY_LABEL = {'resolve': '已解决', 'reject': '已驳回'}
    _PENDING_STATES = ('submitted', 'in_progress')

    def _notify_applicant(self, new_state):
        """处理状态流转后经既有 B5 通知引擎（edu.message）告知申请人。

        - 收件人 = 申请人门户账号（op.student.user_id），无账号或就是处理人则跳过；
        - 发件人 = 当前处理人（env.user），走 sudo 写入（与 messages.py 相同方式）；
        - 通知失败只告警不回滚处理事务；
        - 仅在实际发生状态流转时由调用方触发（后台按钮/门户路由同一入口）。
        """
        label = self._NOTIFY_LABEL.get(new_state)
        if not label:
            return
        student = self.student_id.sudo() if self.student_id else None
        user = student.user_id if student else None
        if not user or user.id == self.env.uid:
            return
        body = '【处理通知】您的申诉 %s「%s」%s。' % (
            self.name or '—', self.subject or '—', label)
        if new_state == 'reject' and self.reject_reason:
            body += '\n驳回原因：%s' % self.reject_reason
        try:
            self.env['edu.message'].sudo().create({
                'sender_id': self.env.uid,
                'recipient_id': user.id,
                'body': body[:2000],
                'sent_at': fields.Datetime.now(),
            })
        except Exception:
            _logger.warning('edu.grievance %s notify applicant failed',
                            self.name or self.id, exc_info=True)

    @api.model
    def action_start(self):
        """开始处理：submitted -> in_progress。"""
        self._approval_targets().write({'state': 'in_progress'})

    @api.model
    def action_resolve(self):
        """解决：submitted/in_progress -> resolve；实际流转的记录通知申请人。"""
        targets = self._approval_targets()
        changed = targets.filtered(
            lambda r: r.state in self._PENDING_STATES)
        targets.write({'state': 'resolve'})
        for rec in changed:
            rec._notify_applicant('resolve')

    @api.model
    def action_reject(self):
        """驳回：submitted/in_progress -> reject，须填写驳回原因；流转后通知。"""
        targets = self._approval_targets()
        if any(not rec.reject_reason for rec in targets):
            raise UserError('驳回前请先填写「驳回原因」。')
        changed = targets.filtered(
            lambda r: r.state in self._PENDING_STATES)
        targets.write({'state': 'reject'})
        for rec in changed:
            rec._notify_applicant('reject')

    @api.model
    def action_close(self):
        """关闭：resolve/reject -> close。"""
        self._approval_targets().write({'state': 'close'})

    # ------------------------------------------------------------------
    # F1：超时升级 cron（ir.cron 记录见 views/roles.xml）
    # ------------------------------------------------------------------
    @api.model
    def _cron_escalate_pending(self):
        """待处理申诉超时未处理 → 提醒教务处/管理员（幂等）。

        待处理 = submitted / in_progress；阈值同请假
        （edu_portal.approval_escalate_hours，默认 48 小时）。
        """
        hours = escalate_hours(self.env)
        deadline = fields.Datetime.now() - datetime.timedelta(hours=hours)
        pending = self.sudo().search([
            ('state', 'in', self._PENDING_STATES),
            ('escalated_at', '=', False),
            ('create_date', '<=', deadline)])
        if not pending:
            return 0
        for rec in pending:
            body = ('【申诉超时提醒】申诉 %s「%s」已超过 %d 小时未处理，'
                    '请尽快跟进。') % (
                        rec.name or '—', rec.subject or '—', hours)
            notify_approvers(self.env, body)
        pending.write({'escalated_at': fields.Datetime.now()})
        return len(pending)
