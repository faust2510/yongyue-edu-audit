# -*- coding: utf-8 -*-
"""「已录取」→ 发放入学码（需求 C-3）。

设计与任务书：docs/plans/admission-invite-link-design.md（**§18 为本轮实施口径**）。
硬口径（每条都有现场依据，改动前先读 §18.3）：

  · **幂等**：一张申请只有一张码（DB unique(application_id)）。重复点 = 回显同一张码，
    不新建、不出网 —— 教务连点两下不该发出两张码、两封邮件。
  · **邮件尽力而为**：本机与生产 `ir_mail_server` 实测均 0 行（2026-10-14）⇒
    `send(raise_exception=False)`，发信失败只落 `mail.mail(state=exception)` 与审计，
    **绝不**因为「发不出去」让教务点不动按钮；页面回显码 + 提示转告才是主通道。
  · **权限两层**：视图 `groups` 只挡 UI；`edu.application` 对 `base.group_user` 是只读、
    菜单也不带组 ⇒ 方法体内**必须再判一次**，否则是「看得见点得动」。
  · **不动 state**：码的 `state` 只有 unused/used（消费在注册侧），发放/重发只写
    `expire_at` 与 `application_id`；撤销 = 把 `expire_at` 改到过去，不新增状态。
"""
import datetime
import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BACKOFFICE_GROUPS = ('openeducat_core.group_op_back_office_admin', 'base.group_system')
GUARD_MSG = '只有教务处或系统管理员可以发放入学码。'
VALID_DAYS_PARAM = 'edu_admit_invite.valid_days'
REGISTER_URL_PARAM = 'edu_admit_invite.register_url'
DEFAULT_VALID_DAYS = 14
DEFAULT_REGISTER_URL = 'https://edu.example.org/register'
MAIL_SUBJECT = '【永约学坊】您的入学注册码'
NO_EMAIL_NOTE = '该申请没留邮箱，请电话/微信告知'
CODE_NOTE_PREFIX = '入学申请'


class EduApplication(models.Model):
    _inherit = 'edu.application'

    # ── 表单常驻展示：非存储计算字段，反查码行 ───────────────────────────
    # 为什么不落列：这些值都躺在码行上（create_date / created_by / used_login /
    # used_on），落列就要两处同改。逐条 search 而非 one2many：一张申请最多一张码，
    # 列表视图不挂这些字段（避免 N+1），只有表单读一次。
    invite_code_text = fields.Char('入学码', compute='_compute_invite_code_info')
    invite_issued_at = fields.Datetime('发放时间', compute='_compute_invite_code_info')
    invite_issued_by = fields.Char('发放人', compute='_compute_invite_code_info')
    invite_used_login = fields.Char('注册邮箱', compute='_compute_invite_code_info')
    invite_used_on = fields.Datetime('已注册', compute='_compute_invite_code_info')
    invite_email_mismatch = fields.Boolean(
        '注册邮箱与申请邮箱不一致', compute='_compute_invite_code_info')

    def _compute_invite_code_info(self):
        Code = self.env['edu.invite.code'].sudo()
        for app in self:
            code = Code.search([('application_id', '=', app.id)], limit=1)
            app.invite_code_text = code.code or ''
            app.invite_issued_at = code.create_date or False
            app.invite_issued_by = code.created_by.name or ''
            app.invite_used_login = code.used_login or ''
            app.invite_used_on = code.used_on or False
            used = (code.used_login or '').strip().lower()
            mail = (app.email or '').strip().lower()
            # P6：注册邮箱与申请邮箱不一致 ⇒ 只高亮提示，**不拦截**
            # （孩子用家长邮箱注册是常态，拦下来会把正常流程卡死）。
            app.invite_email_mismatch = bool(used and mail and used != mail)

    # ── 门禁与参数 ───────────────────────────────────────────────────────
    def _admit_invite_guard(self):
        user = self.env.user
        if not any(user.has_group(g) for g in BACKOFFICE_GROUPS):
            raise UserError(GUARD_MSG)

    def _admit_invite_days(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            VALID_DAYS_PARAM, DEFAULT_VALID_DAYS)
        try:
            days = int(raw)
        except (TypeError, ValueError):
            days = DEFAULT_VALID_DAYS
        return max(1, days)

    def _admit_invite_register_url(self):
        return (self.env['ir.config_parameter'].sudo().get_param(REGISTER_URL_PARAM)
                or DEFAULT_REGISTER_URL)

    def _admit_invite_expire_at(self):
        # **必须显式传**：不传会落到模型默认（edu_portal/models/invite_code.py
        # 的 expire_at 默认 = now + 7 天），与拍板的 14 天不符（§18.1-P3）。
        return fields.Datetime.now() + datetime.timedelta(days=self._admit_invite_days())

    def _admit_invite_code(self):
        self.ensure_one()
        return self.env['edu.invite.code'].search(
            [('application_id', '=', self.id)], limit=1)

    def _admit_invite_create_code(self):
        self.ensure_one()
        # 码文本**不自己拼**：留空 code ⇒ 既有 new_code() 生成 'EDU-' + 6 位随机
        # （edu_portal/models/invite_code.py:93/:188）。连号/可推导码 = 可枚举口令，
        # 与本仓既定口径冲突（invite_code.py:408-409）。
        return self.env['edu.invite.code'].create({
            'code_kind': 'tier',
            'tier': 'student',
            'use_limit': 1,
            'expire_at': self._admit_invite_expire_at(),
            'note': '%s %s' % (CODE_NOTE_PREFIX, self.name or self.id),
            'application_id': self.id,
        })

    def _admit_invite_audit(self, action, detail):
        self.env['edu.audit.log'].sudo()._log(
            action, 'edu.application', self.id, self.name or '', detail)

    # ── 邮件（尽力而为） ─────────────────────────────────────────────────
    def _admit_invite_mail(self, code):
        """返回投递说明（给通知与审计用）。无邮箱 ⇒ 不发信、不建 mail.mail。"""
        self.ensure_one()
        email = (self.email or '').strip()
        if not email:
            return NO_EMAIL_NOTE
        url = self._admit_invite_register_url()
        expire = code.expire_at and fields.Datetime.to_string(code.expire_at) or ''
        body = (
            '<p>%s，您好：</p>'
            '<p>您已被永约学坊录取。请用下面的注册码完成注册：</p>'
            '<p style="font-size:20px;font-weight:bold;letter-spacing:2px;">%s</p>'
            '<p>注册地址：<a href="%s">%s</a><br/>有效期至：%s</p>'
            '<p>注册码只能用一次，请勿转发他人。</p>'
            '<p>永约学坊 教务处<br/>scrtsschool@gmail.com</p>'
        ) % (self.name or '', code.code, url, url, expire)
        mail = self.env['mail.mail'].sudo().create({
            'subject': MAIL_SUBJECT,
            'body_html': body,
            'email_to': email,
        })
        try:
            mail.send(raise_exception=False)
        except Exception as exc:  # 绝不因为发信异常挡住发码
            _logger.warning('入学码邮件发送异常（application=%s）：%s', self.id, exc)
        if mail.state == 'exception':
            reason = (mail.failure_reason or '无 SMTP 配置').strip().splitlines()[0][:80]
            return '邮件已生成但未发出（%s），请把码转告本人' % reason
        return '邮件已提交发送'

    # ── 通知 ─────────────────────────────────────────────────────────────
    def _admit_invite_notify(self, code, created, note_text):
        self.ensure_one()
        expire = code.expire_at and fields.Datetime.to_string(code.expire_at) or ''
        msg = '入学码：%s（有效期至 %s）。%s' % (code.code, expire, note_text)
        if not created:
            msg = '本申请已有入学码，未重复发放。' + msg
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '发放入学码' if created else '入学码（已存在）',
                'message': msg,
                'type': 'success' if created else 'warning',
                'sticky': True,
            },
        }

    # ── 按钮 ─────────────────────────────────────────────────────────────
    def action_issue_admission_invite(self):
        """发放入学码：门禁 → 幂等快路径 → 加锁 → 建码 → 留痕 → （仅新建）出网。"""
        self.ensure_one()
        self._admit_invite_guard()
        code = self._admit_invite_code()
        created = False
        if not code:
            # 并发兜底：锁住申请行，让两个同时点击串行；DB unique 是最后一道真相层。
            # try_lock_for_update 会**跳过**已被别人锁住的行（不等待）⇒ 锁不到就别硬撞
            # unique 报 IntegrityError，给一句人话（见 docs/plans/…-design.md §8.4）。
            locked = self.try_lock_for_update()
            code = self._admit_invite_code()   # 可能是对方刚提交的那张
        if not code and not locked:
            raise UserError('本申请的入学码正在被另一个人发放，请刷新页面后重试。')
        if not code:
            code = self._admit_invite_create_code()
            created = True
            self._admit_invite_audit(
                '发放入学码',
                '入学码 %s · 有效期至 %s · 申请邮箱 %s'
                % (code.code, code.expire_at and fields.Datetime.to_string(code.expire_at) or '',
                   (self.email or '').strip() or '（未留）'))
        note_text = '（未重复发信）'
        if created:
            note_text = self._admit_invite_mail(code)
            if note_text != NO_EMAIL_NOTE:
                self._admit_invite_audit('入学码邮件', note_text)
        return self._admit_invite_notify(code, created, note_text)

    def action_reissue_admission_invite(self):
        """重新发放入学码：旧码作废并解绑，再发一张新的（否则撞 unique(application_id)）。"""
        self.ensure_one()
        self._admit_invite_guard()
        old = self._admit_invite_code()
        if old:
            self.try_lock_for_update()
            old.write({
                # 先解绑再建新码：unique(application_id) 是硬约束，顺序不能反。
                'application_id': False,
                'expire_at': fields.Datetime.now() - datetime.timedelta(days=1),
            })
            # 必须显式落库：ORM 的 create 不保证先把这条 UPDATE 刷出去，实测（2026-10-14 A9）
            # 不 flush 就在插入新码时撞 edu_invite_code_edu_admit_application_uniq（DuplicateKey）。
            old.flush_recordset(['application_id'])
            self._admit_invite_audit(
                '重新发放入学码（旧码作废）',
                '旧码 %s 已置为过期并解绑' % (old.code or ''))
        code = self._admit_invite_create_code()
        self._admit_invite_audit(
            '重新发放入学码',
            '入学码 %s · 有效期至 %s'
            % (code.code, code.expire_at and fields.Datetime.to_string(code.expire_at) or ''))
        note_text = self._admit_invite_mail(code)
        if note_text != NO_EMAIL_NOTE:
            self._admit_invite_audit('入学码邮件', note_text)
        return self._admit_invite_notify(code, True, note_text)
