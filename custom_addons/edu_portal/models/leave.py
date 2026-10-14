# -*- coding: utf-8 -*-
"""学生请假（Time Off）轻量模型。

社区版 OpenEduCat 没有学生请假模型（企业版 openeducat_student_leave 才有），
这里自建一个轻量模型支撑 /my/time_off 页面，字段对齐原站参考 DOM：
休假类型 / 开始结束日期 / 状态（Requested/Approved/Refused）+ 请假事由。
"""
import datetime
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def escalate_hours(env):
    """超时升级阈值（小时）：系统参数可调，默认 48。"""
    try:
        return int(env['ir.config_parameter'].sudo().get_param(
            'edu_portal.approval_escalate_hours', '48') or 48)
    except (TypeError, ValueError):
        return 48


def notify_approvers(env, body):
    """提醒教务处/管理员（不建自定义组，复用基座教务处组 + 系统组）。

    对齐钉钉「限时审批」超时事件语义：超时不是静默丢弃，而是升级提醒；
    失败只告警，不打断 cron 事务。
    """
    targets = env['res.users'].sudo().browse()
    for xmlid in ('openeducat_core.group_op_back_office_admin',
                  'base.group_system'):
        group = env.ref(xmlid, raise_if_not_found=False)
        if group:
            targets |= group.user_ids
    for user in targets:
        try:
            env['edu.message']._notify_event('approval_escalate', user, body)
        except Exception:
            _logger.warning('escalate notify failed uid=%s', user.id,
                            exc_info=True)


class EduLeave(models.Model):
    _name = 'edu.leave'
    _description = 'Student Time Off / Leave Request'
    _order = 'date_from desc, id desc'

    name = fields.Char('Request Number', size=64)
    student_id = fields.Many2one('op.student', 'Student')
    leave_type = fields.Selection(
        [('sick', 'Sick Leave'),
         ('legal', 'Legal Leave'),
         ('casual', 'Casual Leave'),
         ('other', 'Other')],
        string='Leave Type', default='sick')
    date_from = fields.Date('Start Date')
    date_to = fields.Date('End Date')
    state = fields.Selection(
        [('request', 'Requested'),
         ('approved', 'Approved'),
         ('refused', 'Refused')],
        string='Status', default='request')
    reason = fields.Text('Description')
    reject_reason = fields.Text('驳回原因')
    active = fields.Boolean('Active', default=True)
    # F1 超时升级：非空即视为已升级提醒过（cron 幂等去重）
    escalated_at = fields.Datetime('升级提醒时间', readonly=True, copy=False)

    # 课代表（docs/plans/course-representative-design.md §2.2）：只加字段，
    # **不改既有行为**。四个字段**全部可空** => 既有数据不回填、老单据行为一字不变。
    # - subject_id：请假「涉及课程」；学生在 /my/time_off 选填。课代表只能批
    #   本课程的单，**subject_id 为空 => 课代表无权批**（fail-closed，见
    #   models/course_rep.py 的 rep_can_handle）。
    # - approver_id / approver_kind / approved_at：审批留痕（补既有缺口）。
    #   ⚠ 既有两条审批入口（门户 /leave/set_state、后台 action_approve/reject）
    #   也**必须**补写，否则同一张表上「有的假单显示审批人、有的不显示」。
    subject_id = fields.Many2one(
        'op.subject', '涉及课程', index=True, ondelete='set null',
        help='该请假涉及的课程（选填）。课代表只能处置本课程的单。')
    approver_id = fields.Many2one(
        'res.users', '审批人', ondelete='set null',
        help='实际审批人；既有历史单据为空（显示「—」）。')
    approver_kind = fields.Selection(
        [('student_rep', '课代表'),
         ('faculty', '任课老师'),
         ('registrar', '教务'),
         ('admin', '管理员')],
        string='审批人身份',
        help='需求⑥「不能混同老师审批」的落点：课代表审批写 student_rep。')
    approved_at = fields.Datetime('审批时刻')

    _APPROVER_LABEL = {
        'student_rep': '由课代表 %s 审批',
        'faculty': '由任课老师 %s 审批',
        'registrar': '由教务 %s 审批',
        'admin': '由教务 %s 审批',
    }

    def approver_label(self):
        """审批人文案（需求⑥逐字要求「不能混同老师审批」）。

        - 课代表 => 「由课代表 X 审批」
        - 任课老师 => 「由任课老师 X 审批」
        - 教务 / 管理员 => 「由教务 X 审批」
        - 空（既有历史单据）=> 「—」
        """
        self.ensure_one()
        if not self.approver_kind or not self.approver_id:
            return '—'
        tpl = self._APPROVER_LABEL.get(self.approver_kind)
        if not tpl:
            return '—'
        return tpl % (self.approver_id.name or '')

    def _approval_targets(self):
        # 后台表单按钮经 @api.model 调用时 self 为空，回退到上下文 active_ids
        return self or self.browse(self.env.context.get('active_ids') or [])

    # A1：审批结果 → 通知文案（B5 通知引擎）
    _NOTIFY_LABEL = {'approved': '已通过', 'refused': '已驳回'}

    def _notify_applicant(self, new_state):
        """审批状态流转后经既有 B5 通知引擎（edu.message）告知申请人。

        - 收件人 = 申请人门户账号（op.student.user_id），无账号或就是审批人则跳过；
        - 发件人 = 当前审批人（env.user），走 sudo 写入（与 messages.py 相同方式）；
        - 通知失败只告警不回滚审批事务；
        - 仅在实际发生状态流转时由调用方触发（后台按钮/门户路由同一入口）。
        """
        label = self._NOTIFY_LABEL.get(new_state)
        if not label:
            return
        student = self.student_id.sudo() if self.student_id else None
        user = student.user_id if student else None
        if not user or user.id == self.env.uid:
            return
        body = '【审批通知】您的请假申请 %s（%s ~ %s）%s。' % (
            self.name or '—',
            self.date_from.strftime('%Y/%m/%d') if self.date_from else '—',
            self.date_to.strftime('%Y/%m/%d') if self.date_to else '—',
            label)
        if new_state == 'refused' and self.reject_reason:
            body += '\n驳回原因：%s' % self.reject_reason
        self.env['edu.message']._notify_event(
            'leave_result', user, body)

    def action_approve(self):
        """通过：request -> approved；实际流转的记录通知申请人。

        Odoo19 后台 type=object 按钮以实例方法调用（self=选中记录集），
        历史 @api.model 签名会收到第二参数而 TypeError——改普通实例方法，
        _approval_targets 仍兼容空 self 的上下文回退路径。
        """
        targets = self._approval_targets()
        changed = targets.filtered(lambda r: r.state == 'request')
        # 课代表需求⑥：审批留痕（既有后台按钮也必须补写，见 models/course_rep.py
        # 的 _approver_vals —— 同一张表上审批人口径必须一致）。
        vals = {'state': 'approved'}
        vals.update(self._approver_vals())
        targets.write(vals)
        for rec in changed:
            rec._notify_applicant('approved')

    def action_reject(self):
        """驳回：request -> refused，须填写驳回原因；流转后通知申请人。"""
        targets = self._approval_targets()
        if any(not rec.reject_reason for rec in targets):
            raise UserError('驳回前请先填写「驳回原因」。')
        changed = targets.filtered(lambda r: r.state == 'request')
        vals = {'state': 'refused'}
        vals.update(self._approver_vals())
        targets.write(vals)
        for rec in changed:
            rec._notify_applicant('refused')

    # ------------------------------------------------------------------
    # F1：超时升级 cron（ir.cron 记录见 views/roles.xml）
    # ------------------------------------------------------------------
    @api.model
    def _cron_escalate_pending(self):
        """待审批超时未处理 → 提醒教务处/管理员并记升级时间（幂等）。

        阈值取系统参数 edu_portal.approval_escalate_hours（默认 48 小时）；
        escalated_at 非空即不再重复提醒，重复跑 cron 安全。
        """
        hours = escalate_hours(self.env)
        deadline = fields.Datetime.now() - datetime.timedelta(hours=hours)
        pending = self.sudo().search([
            ('state', '=', 'request'),
            ('escalated_at', '=', False),
            ('create_date', '<=', deadline)])
        if not pending:
            return 0
        for rec in pending:
            body = ('【审批超时提醒】请假申请 %s（%s，%s ~ %s）已超过 %d '
                    '小时未处理，请尽快审批。') % (
                        rec.name or '—', rec.student_id.name or '—',
                        rec.date_from or '—', rec.date_to or '—', hours)
            notify_approvers(self.env, body)
        pending.write({'escalated_at': fields.Datetime.now()})
        return len(pending)


class EduApprovalDelegate(models.Model):
    """审批代理设置（请假/申诉/选课共用）。

    抄钉钉「代理设置」三要素：被代理人 / 代理人 / 代理时间（可撤销）。
    仅用于门户审批路由的放行判定：处于代理期内的代理人可代被代理人审批。
    """
    _name = 'edu.approval.delegate'
    _description = '审批代理设置'
    _order = 'date_from desc, id desc'

    delegator_id = fields.Many2one(
        'res.users', '被代理人', required=True, index=True,
        ondelete='cascade', help='原审批人（请假/申诉/选课的门禁角色）')
    delegate_id = fields.Many2one(
        'res.users', '代理人', required=True, index=True,
        ondelete='cascade', help='代理期内可代被代理人审批的人')
    date_from = fields.Date('开始日期', required=True,
                            default=fields.Date.today)
    date_to = fields.Date('结束日期', required=True)
    note = fields.Char('说明', size=128, help='如：出差/休假期间')
    active = fields.Boolean('启用', default=True)

    @api.model
    def _active_domain(self):
        today = fields.Date.today()
        return [('active', '=', True),
                ('date_from', '<=', today),
                ('date_to', '>=', today)]

    @api.model
    def is_delegate_of(self, user, target_user):
        """user 是否在代理期内可代 target_user 审批。"""
        if not user or not target_user or user.id == target_user.id:
            return False
        return bool(self.sudo().search_count(
            self._active_domain() + [
                ('delegate_id', '=', user.id),
                ('delegator_id', '=', target_user.id)]))

    @api.model
    def delegators_of(self, user):
        """user 作为代理人时，当前可代理的被代理人（res.users）。"""
        if not user:
            return self.env['res.users'].sudo().browse()
        recs = self.sudo().search(
            self._active_domain() + [('delegate_id', '=', user.id)])
        return recs.mapped('delegator_id')
