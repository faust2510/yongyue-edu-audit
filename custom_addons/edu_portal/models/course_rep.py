# -*- coding: utf-8 -*-
"""课代表（课程级学生干部身份）：任命 -> 在任期内拥有本课程有限权限。

设计稿：docs/plans/course-representative-design.md（§1 载体裁定 / §2 数据模型 /
§4 授予·归还·兜底到期·撤销 / §6 请假审批三护栏）。
调研：docs/research/course-representative.md。

载体裁定（照设计逐字落地）
--------------------------
- 新建 **一张表、每科目一行（槽位复用）**：归还/到期/撤销**不删行、不新建行**，
  只改 state；下一次任命覆盖同一槽位的 student_id。
- 唯一性 **必须是数据库级**：models.Constraint('UNIQUE (subject_id)')
  （Odoo 19 已废弃 _sql_constraints，会被框架**静默忽略** => 不许照抄旧写法；
  先例：edu_tg_bind/models/tg_claim.py、edu_portal/models/invite_code.py）。
- 任期历史由 edu.audit.log 承载（本文件的四个动作各写一条留痕）。

权限判定的**唯一事实源**（实现铁律，防后人漂移）
------------------------------------------------
1. **到期一律实时重算**：权限判定**只准**走 is_active_now() / active_rep_for() /
   active_subject_ids_of()，它们每次都重算期限（不读 expires_at 快照）。
   **禁止**任何地方直接写 if rep.state == 'active' 当权限依据 —— 那会绕过期限。
   （expires_at / deadline_source 是 compute+store 的**冗余快照**，只供后台展示与
   运维排查；每日 cron 也不用它，同样按实时判定收口。）
2. **deadline is None 永不等于「永久有效」**：三层阶梯 ①班结课日+宽限 /
   ②学期结束日 / ③任命日+硬上限，**第③层永远有值**（空值一律下沉，绝不 fail-open）。
   实现里禁止出现 if not deadline: return True。
3. 四件事（授予/归还/撤销/到期）都写 edu.audit.log；失败只告警、不阻断业务。
4. **不给任何「提名 / 指定 / 转交」字段** —— 归还（release）是课代表唯一的自主动作。

点名口径（队长裁定 (b+)）
-------------------------
课代表点名**仍落「一天一张整班点名表」**（op.attendance.sheet），不改教师侧任何行为；
本文件用 _inherit 加自研字段承载「为哪个科目点的 / 谁提交的 / 何时提交」。
⚠ 既有考勤统计（/student/attendance、/my/study、缺勤比例告警）**直接数
op.attendance.line，且不看 sheet.state** => 若课代表提交时就写 line，「未确认前统计
不变」（设计 §7 N8/P5）立刻不成立。故课代表的点名建议先存 rep_proposal（JSON），
**老师一键确认时才落 line 并置 state='done'** —— 见 OpAttendanceSheetExt。
"""
import datetime
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

#: ①层宽限期（天）：系统参数 edu_portal.course_rep_grace_days
PARAM_GRACE_DAYS = 'edu_portal.course_rep_grace_days'
#: ③层兜底硬上限（天）：系统参数 edu_portal.course_rep_max_days
PARAM_MAX_DAYS = 'edu_portal.course_rep_max_days'
#: 「出勤类请假」白名单：系统参数 edu_portal.course_rep_leave_types
PARAM_LEAVE_TYPES = 'edu_portal.course_rep_leave_types'

DEFAULT_GRACE_DAYS = 30
DEFAULT_MAX_DAYS = 180
DEFAULT_LEAVE_TYPES = ('sick', 'casual')

#: 课代表的动作名（留痕）—— 四件事各一条，**不改**既有「请假审批」等动作名
AUDIT_APPOINT = '课代表任命'
AUDIT_RELEASE = '课代表归还'
AUDIT_REVOKE = '课代表撤销'
AUDIT_EXPIRE = '课代表到期失效'
AUDIT_NOTIFY = '课代表发通知'
AUDIT_ATTENDANCE = '课代表点名提交'
#: 课代表审批请假：**独立动作名**（需求⑥「不能混同老师审批」）
AUDIT_LEAVE_REP = '请假审批(课代表)'


def _raw_param(env, key, default=''):
    """直读 ir_config_parameter 表（**绕开 get_param 的进程内稳定缓存**）。

    为什么不能用 ir.config_parameter.get_param（design §4.3 要求「参数一改，
    权限立即生效」）：
      ir_config_parameter.get_param 带 @ormcache('key', cache='stable')
      （odoo/addons/base/models/ir_config_parameter.py:60-72），
      'stable' 缓存**跨进程不失效**：教务在网页上改了参数，只有处理该请求的
      worker 清了自己的缓存，其余 worker 仍读旧值，直到 worker 重启/模块升级。
      实测（本机 2026-09-21）：把 grace 由 30 改 0、班结课日设为 10 天前，
      shell 侧 deadline_realtime()=过去，而 web 侧仍判「在任」（HTTP 200）。
    课代表的到期判定是「实时重算 = 唯一事实源」，所以这里必须读新鲜值。
    失败一律回落默认值（与 leave.py:escalate_hours 同口径：只保底、不炸业务）。
    """
    try:
        env.cr.execute('SELECT value FROM ir_config_parameter WHERE key = %s',
                       (key,))
        row = env.cr.fetchone()
        if row and row[0] is not None and str(row[0]).strip():
            return str(row[0]).strip()
    except Exception:
        _logger.warning('read param %s failed', key, exc_info=True)
    return default


def _int_param(env, key, default):
    """读整数系统参数（容错 + 保底默认值）；见 _raw_param 为何不用 get_param。"""
    try:
        return int(_raw_param(env, key, str(default)) or default)
    except (TypeError, ValueError):
        return default


def grace_days(env):
    """①层宽限期（天），系统参数可调，默认 30。"""
    return max(0, _int_param(env, PARAM_GRACE_DAYS, DEFAULT_GRACE_DAYS))


def max_days(env):
    """③层兜底硬上限（天），系统参数可调，默认 180。

    这是「空值兜底」的关键：即使①层②层的日期全都取不到，
    任期也必须有一个终点 —— 权限永远拿不到「永久」。
    """
    return max(1, _int_param(env, PARAM_MAX_DAYS, DEFAULT_MAX_DAYS))


def rep_leave_types(env):
    """课代表可处置的请假类型白名单（出勤类），默认 sick,casual。

    legal（法定假）/ other（其他）默认**排除**（需求⑨「审批非出勤类申请」= 写死不给）；
    教务改参数即可增减，无需改代码、无需迁移数据（不改 leave_type 的 Selection）。
    """
    raw = _raw_param(env, PARAM_LEAVE_TYPES, '')
    if not raw.strip():
        return set(DEFAULT_LEAVE_TYPES)
    return {x.strip() for x in raw.split(',') if x.strip()}


class EduCourseRep(models.Model):
    """课代表槽位：**每门科目一行**（UNIQUE(subject_id) 由数据库保证）。"""
    _name = 'edu.course.rep'
    _description = '课代表（课程级学生干部身份）'
    _order = 'subject_id, id'

    subject_id = fields.Many2one(
        'op.subject', string='课程科目', required=True, index=True,
        ondelete='cascade', help='槽位键：一门课一个槽位（数据库唯一约束）')
    student_id = fields.Many2one(
        'op.student', string='现任课代表', index=True, ondelete='set null',
        help='现任 / 最近一任课代表；空闲槽位为空。'
             '归还会保留该值供教务核对，但它不参与任何权限判定。')
    state = fields.Selection(
        [('active', '在任'),
         ('vacant', '空缺'),
         ('expired', '已到期'),
         ('revoked', '已撤销')],
        string='状态', default='vacant', index=True,
        help='只表达「是否在任」与「为何离任」；唯一约束不依赖它（靠 subject_id）。')
    appointed_by_id = fields.Many2one(
        'res.users', string='任命人', ondelete='set null')
    appointed_at = fields.Datetime(
        string='任命时刻', help='同时是第③层兜底上限（任命日 + 硬上限）的起算点。')
    expires_at = fields.Date(
        string='期限', compute='_compute_deadline_stored', store=True,
        help='冗余快照 min(①班结课日+宽限, ②学期结束日, ③任命日+硬上限)。'
             '**权限判定不读它**，见 is_active_now()。')
    deadline_now = fields.Date(
        string='实时期限', compute='_compute_deadline_now',
        help='每次打开都实时重算的期限（权限判定的真实依据）。')
    deadline_source = fields.Selection(
        [('batch', '①班级结课日+宽限'),
         ('term', '②学期结束日'),
         ('cap', '③任命日+硬上限'),
         ('none', '无')],
        string='期限来源', compute='_compute_deadline_stored', store=True,
        help='可解释性：让教务一眼看出为什么是这个日期。')
    vacated_at = fields.Datetime(string='离任时刻', readonly=True)
    vacated_by_id = fields.Many2one(
        'res.users', string='离任操作人', readonly=True, ondelete='set null')
    vacate_reason = fields.Text(string='离任原因', readonly=True)
    active = fields.Boolean(string='启用', default=True)

    # 需求③的落点：**数据库级唯一约束**（不是代码 if 判断）
    _subject_uniq = models.Constraint(
        'UNIQUE (subject_id)',
        '每门课只能有一位课代表（同一科目不能有两个槽位）。')

    # ------------------------------------------------------------------
    # 期限：三层阶梯（min 取最早）
    # ------------------------------------------------------------------
    def _batch_term_layers(self):
        """取①层（班结课日）与②层（学期结束日）。

        口径：该生在这门课的 op.student.course 行（subject_ids 含本科目）。
        一个学生可能属多个班（contacts.py:130）=> ①②**都取最晚**（不早退，
        队长 2026-09-19 裁定）；取不到就返回 None 让上层下沉到下一层。
        """
        self.ensure_one()
        batch_dl = term_dl = None
        if self.subject_id and self.student_id:
            scs = self.env['op.student.course'].sudo().search([
                ('student_id', '=', self.student_id.id),
                ('subject_ids', 'in', self.subject_id.ids)])
            ends = [sc.batch_id.end_date for sc in scs
                    if sc.batch_id and sc.batch_id.end_date]
            if ends:
                batch_dl = (max(ends)
                            + datetime.timedelta(days=grace_days(self.env)))
            terms = [sc.academic_term_id.term_end_date for sc in scs
                     if sc.academic_term_id and sc.academic_term_id.term_end_date]
            if terms:
                term_dl = max(terms)
        return batch_dl, term_dl

    def _deadline_layers(self):
        """三层阶梯：①班结课日+宽限 / ②学期结束日 / ③任命日+硬上限。

        返回 (deadline, source)。**第③层永远有值** => 「无期限」状态不存在。
        ⚠ 空值只允许「下沉到下一层」，**绝不**允许解释成「永久有效」。
        """
        self.ensure_one()
        batch_dl, term_dl = self._batch_term_layers()
        # ③ 任命日 + 硬上限（永远有值）。appointed_at 缺失（历史/脏数据）时
        # 用 create_date 兜底，仍取不到就用今天 —— 三条路都给出一个日期。
        base = self.appointed_at or self.create_date or fields.Datetime.now()
        cap_dl = base.date() + datetime.timedelta(days=max_days(self.env))
        layers = [(batch_dl, 'batch'), (term_dl, 'term'), (cap_dl, 'cap')]
        avail = [(d, src) for d, src in layers if d]
        return min(avail, key=lambda item: item[0])

    # ⚠ stored 与非 stored 必须分开两个 compute：写在同一方法里，Odoo 会报
    # 「inconsistent 'store' for computed fields」（读非 stored 字段可能顺带
    # 触发 stored 字段回写，造成意料之外的 write）。
    @api.depends('subject_id', 'student_id', 'appointed_at', 'state')
    def _compute_deadline_stored(self):
        for rec in self:
            deadline, source = rec._deadline_layers()
            rec.expires_at = deadline
            rec.deadline_source = source

    @api.depends('subject_id', 'student_id', 'appointed_at', 'state')
    def _compute_deadline_now(self):
        for rec in self:
            rec.deadline_now = rec._deadline_layers()[0]

    def deadline_realtime(self):
        """实时重算的期限（**权限判定用这个**，不读 expires_at 快照）。"""
        self.ensure_one()
        return self._deadline_layers()[0]

    # ------------------------------------------------------------------
    # 权限判定：唯一事实源
    # ------------------------------------------------------------------
    def is_active_now(self):
        """实时判定在任：state == 'active' **且** 今天 <= 实时重算的期限。

        ⚠ 这是全仓唯一允许的课代表权限判据。禁止在别处直接判 state。
        宽限期参数一改、结课日一改 => 这里立刻生效（没有快照漂移）。
        """
        today = fields.Date.today()
        return self.filtered(
            lambda r: r.state == 'active' and r.deadline_realtime() >= today)

    @api.model
    def active_rep_for(self, student, subject):
        """(学生, 科目) -> 在任槽位（不在任返回空集）。"""
        if not student or not subject:
            return self.browse()
        slot = self.sudo().search([('subject_id', '=', subject.id),
                                   ('student_id', '=', student.id)], limit=1)
        return slot.is_active_now()

    @api.model
    def active_subject_ids_of(self, student):
        """该生当前在任的科目 id（学生侧「我是哪个课的课代表」）。"""
        if not student:
            return []
        slots = self.sudo().search([('student_id', '=', student.id)])
        return slots.is_active_now().mapped('subject_id').ids

    # ------------------------------------------------------------------
    # §4.0 授予（任命）：教务 / 管理员
    # ------------------------------------------------------------------
    @api.model
    def appoint(self, subject, student, by_user=None):
        """任命某生为某课课代表（教务/管理员）。

        - 候选人**必须是该课程的注册学生**（在 op.student.course.subject_ids 里）；
        - 唯一性**交给数据库**（UNIQUE(subject_id)）：并发同抢由第二笔撞约束回滚，
          不做前置 if 判断（设计 §4.0）；
        - 留痕 + 通知（event_key=course_rep_appointed）。
        """
        env = self.env
        slot = self.sudo().search([('subject_id', '=', subject.id)], limit=1)
        if not slot:
            slot = self.sudo().create({'subject_id': subject.id,
                                       'state': 'vacant'})
        enrolled = env['op.student.course'].sudo().search_count([
            ('student_id', '=', student.id),
            ('subject_ids', 'in', subject.ids)])
        if not enrolled:
            raise UserError('该学生不是「%s」的注册学生，不能任命为本科课代表。'
                            % (subject.name or ''))
        now = fields.Datetime.now()
        slot.write({
            'student_id': student.id,
            'state': 'active',
            'appointed_by_id': (by_user or env.user).id,
            'appointed_at': now,
            'vacated_at': False,
            'vacated_by_id': False,
            'vacate_reason': False,
        })
        deadline, source = slot._deadline_layers()
        env['edu.audit.log'].sudo()._log(
            AUDIT_APPOINT, 'edu.course.rep', slot.id, subject.name or '',
            '任命 %s(id) 为课代表；期限 %s（来源 %s）'
            % (student.name or '', deadline, source))
        self._notify_rep_student(
            student, 'course_rep_appointed',
            '【课代表】你已被任命为「%s」的课代表，任期至 %s。'
            % (subject.name or '', deadline))
        return slot

    @api.model
    def release(self, student, subject, reason='本人归还'):
        """§4.1 归还：**课代表唯一的自主动作**（无提名/指定/转交）。

        服务端重新判定「我是该槽位的 active 且未到期」；否则按不存在处理。
        保留 student_id（= 上一任，供教务核对，**不参与任何权限判定**）。
        """
        slot = self.active_rep_for(student, subject)
        if not slot:
            return self.browse()
        slot.write({
            'state': 'vacant',
            'vacated_at': fields.Datetime.now(),
            'vacated_by_id': self.env.user.id,
            'vacate_reason': reason,
        })
        self.env['edu.audit.log'].sudo()._log(
            AUDIT_RELEASE, 'edu.course.rep', slot.id, subject.name or '',
            '%s；上一任 %s' % (reason, student.name or ''))
        return slot

    @api.model
    def revoke(self, slot, reason, by_user=None):
        """§4.2 中途撤销（教务/管理员）：立即失效 + 必填原因 + 通知学生。"""
        slot.ensure_one()
        reason = (reason or '').strip()
        if not reason:
            raise UserError('撤销课代表必须填写原因。')
        student = slot.student_id
        subject = slot.subject_id
        slot.write({
            'state': 'revoked',
            'vacated_at': fields.Datetime.now(),
            'vacated_by_id': (by_user or self.env.user).id,
            'vacate_reason': reason,
        })
        self.env['edu.audit.log'].sudo()._log(
            AUDIT_REVOKE, 'edu.course.rep', slot.id, subject.name or '', reason)
        if student:
            self._notify_rep_student(
                student, 'course_rep_appointed',
                '【课代表】你在「%s」的课代表身份已被撤销：%s'
                % (subject.name or '', reason))
        return slot

    # ------------------------------------------------------------------
    # 后台按钮（§4.0 任命 / §4.2 撤销）—— 教务 / 管理员
    # ------------------------------------------------------------------
    def action_appoint(self):
        """后台「任命」按钮：把本槽位的 student_id 任命为课代表。

        唯一性**不做前置 if**：并发同抢由 UNIQUE(subject_id) 撞约束回滚。
        """
        for slot in self:
            if not slot.subject_id or not slot.student_id:
                raise UserError('请先选择「课程科目」与「现任课代表」再任命。')
            self.env['edu.course.rep'].sudo().appoint(
                slot.subject_id, slot.student_id)
        return True

    def action_revoke(self):
        """后台「撤销」按钮：强制解除（原因必填）。"""
        for slot in self:
            self.env['edu.course.rep'].sudo().revoke(
                slot, slot.vacate_reason or '')
        return True

    # ------------------------------------------------------------------
    # §4.3 保险二：每日 cron 收口（**cron 不是权限依据**）
    # ------------------------------------------------------------------
    @api.model
    def _cron_expire(self):
        """扫 state='active' 但**实时判定已过期**的槽位 -> 写 expired + 留痕 + 通知。

        形态照 edu_portal/views/roles.xml 的 ir_cron_edu_leave_escalate：
        active 幂等、失败不炸事务。即使本 cron 三天没跑，权限也已在
        is_active_now() 处失效 —— 这正是「双保险」的含义。
        """
        Act = self.sudo().search([('state', '=', 'active')])
        stale = Act - Act.is_active_now()
        done = 0
        for slot in stale:
            try:
                deadline = slot.deadline_realtime()
                student = slot.student_id
                subject = slot.subject_id
                slot.write({
                    'state': 'expired',
                    'vacated_at': fields.Datetime.now(),
                    'vacated_by_id': False,
                    'vacate_reason': '任期到期（%s）' % deadline,
                })
                self.env['edu.audit.log'].sudo()._log(
                    AUDIT_EXPIRE, 'edu.course.rep', slot.id, subject.name or '',
                    '实时判定已过期（期限 %s，来源 %s），收口为 expired'
                    % (deadline, slot.deadline_source))
                if student:
                    self._notify_rep_student(
                        student, 'course_rep_expired',
                        '【课代表】你在「%s」的课代表身份已于 %s 到期失效。'
                        % (subject.name or '', deadline))
                done += 1
            except Exception:
                _logger.warning('course rep expire failed id=%s', slot.id,
                                exc_info=True)
        return done

    # ------------------------------------------------------------------
    # 通知（复用 B5 引擎；动态 import 身份反查，避免模型层循环 import）
    # ------------------------------------------------------------------
    def _notify_rep_student(self, student, event_key, body):
        """通知课代表本人（失败只告警，不阻断业务事务）。"""
        try:
            from odoo.addons.edu_schedule.models.identity import users_of_profile
            users = users_of_profile(student.sudo())
            msg = self.env['edu.message'].sudo()
            for user in users:
                msg._notify_event(event_key, user, body)
        except Exception:
            _logger.warning('rep notify %s failed', event_key, exc_info=True)


class OpAttendanceSheetExt(models.Model):
    """课代表点名（队长裁定 (b+)）：**不改教师侧行为**，只加辨识字段。

    - 复用既有「一天一张整班点名表」模型与 state（提交后停在 'start'）；
    - rep_subject_id / submitted_by_rep_id / rep_submitted_at 只用于辨识与留痕，
      **绝不参与**任何唯一键（既有唯一性仍只有 register+session+date 与
      流程层的 (course,batch,date) 查重）；
    - rep_proposal：课代表提交的「点名建议」（JSON：{student_id: status}）。
      见文件头「点名口径」：既有统计直接数 op.attendance.line 且不看 state，
      所以建议**不能**在确认前落 line，否则 N8/P5「未确认前统计不变」不成立。
    """
    _inherit = 'op.attendance.sheet'

    rep_subject_id = fields.Many2one(
        'op.subject', string='课代表提交的科目',
        help='这是为哪个科目点的（课代表是 subject 级，科目辨识度不能丢）。')
    submitted_by_rep_id = fields.Many2one(
        'edu.course.rep', string='课代表提交人', ondelete='set null')
    rep_submitted_at = fields.Datetime(string='课代表提交时刻')
    rep_proposal = fields.Text(string='课代表点名建议（JSON）')

    def _rep_proposal_map(self):
        """点名建议 -> {student_id(int): 'present'|'late'|'absent'}（坏数据当空）。"""
        self.ensure_one()
        try:
            raw = json.loads(self.rep_proposal or '{}')
        except (TypeError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        out = {}
        for key, val in raw.items():
            try:
                out[int(key)] = val
            except (TypeError, ValueError):
                continue
        return out

    @api.model
    def _rep_register(self, course, batch, rep_subject_id):
        """登记簿按 (course_id, batch_id) 复用 —— 与教师侧 roles.py:498/2463 同口径。

        ⚠ 与教师侧的唯一差别：**必须补 code**。op.attendance.register.code 是
        required=True + unique(code)（openeducat_attendance/models/
        attendance_register.py:32-43），教师侧 roles.py:502 / :2467 建登记簿时
        没传 code ⇒ 在**全新** (course,batch) 上会 IntegrityError（既有缺陷，
        不在本次范围内、也不改教师侧行为，已上报）。课代表侧不复制这个缺陷。
        """
        Register = self.env['op.attendance.register'].sudo()
        register = Register.search([('course_id', '=', course.id),
                                    ('batch_id', '=', batch.id)], limit=1)
        if not register:
            # ⚠ 只用**真实存在**的字段：基座 op.attendance.register 只有
            # name / code / course_id / batch_id / subject_id / active
            # （openeducat_attendance/models/attendance_register.py:30-40）。
            # 教师侧 roles.py:502-508 与 :2467-2473 传了不存在的
            # start_date / end_date、又漏传 required 的 code ⇒ 只要该
            # (course,batch) 还没有登记簿，老师侧点名就 500（既有缺陷，
            # 不属本次范围、不改教师侧行为，已上报）。
            register = Register.create({
                'name': ('考勤登记 %s' % (batch.code or batch.name or ''))[:16],
                'code': 'R%d-%d' % (course.id, batch.id),
                'course_id': course.id,
                'batch_id': batch.id,
                'subject_id': rep_subject_id,
            })
        return register

    @api.model
    def _rep_faculty_of(self, batch, subject):
        """该课该班的任课老师（op.session.faculty_id 口径）。"""
        Sess = self.env['op.session'].sudo()
        sess = Sess.search([('batch_id', '=', batch.id),
                            ('subject_id', '=', subject.id)], limit=1)
        if not sess:
            sess = Sess.search([('batch_id', '=', batch.id)], limit=1)
        return sess.faculty_id

    @api.model
    def rep_submit(self, rep, subject, adate, proposal):
        """课代表提交点名（待老师确认）。

        返回 (result, sheet)：result ∈
          'submitted' 新建/更新了待确认表；
          'locked'    当天该班已有已落定（done/cancel）的点名表 / 该生无班。
        **不写 op.attendance.line**（确认前统计必须一字不变）。
        """
        adate = fields.Date.to_date(adate) or fields.Date.today()
        student = rep.student_id
        scs = self.env['op.student.course'].sudo().search([
            ('student_id', '=', student.id),
            ('subject_ids', 'in', subject.ids),
            ('batch_id', '!=', False)])
        sc = scs.filtered(lambda r: r.batch_id)[:1]
        if not sc:
            return 'locked', self.browse()
        course, batch = sc.course_id, sc.batch_id
        if not course or not batch:
            return 'locked', self.browse()
        Sheet = self.sudo()
        existing = Sheet.search([('course_id', '=', course.id),
                                 ('batch_id', '=', batch.id),
                                 ('attendance_date', '=', adate)], limit=1)
        if existing and existing.state in ('done', 'cancel'):
            return 'locked', existing
        register = self._rep_register(course, batch, subject.id)
        vals = {
            'rep_subject_id': subject.id,
            'submitted_by_rep_id': rep.id,
            'rep_submitted_at': fields.Datetime.now(),
            'rep_proposal': json.dumps(
                {str(k): v for k, v in proposal.items()}),
        }
        if existing:
            existing.write(vals)
            sheet = existing
            if sheet.state == 'draft':
                sheet.state = 'start'
        else:
            vals.update({
                'register_id': register.id,
                'attendance_date': adate,
                'faculty_id': self._rep_faculty_of(batch, subject).id,
                'state': 'start',
            })
            sheet = Sheet.create(vals)
        self.env['edu.audit.log'].sudo()._log(
            AUDIT_ATTENDANCE, 'op.attendance.sheet', sheet.id, sheet.name or '',
            '课代表提交待确认点名：科目 %s · 班级 %s · %s · %d 人'
            % (subject.name or '', batch.name or '', adate, len(proposal)))
        self._rep_notify_faculty(sheet, subject, rep)
        return 'submitted', sheet

    def _rep_notify_faculty(self, sheet, subject, rep):
        """给任课老师发站内信（新事件 key attendance_rep_submitted）。"""
        try:
            from odoo.addons.edu_schedule.models.identity import users_of_profile
            faculty = sheet.faculty_id
            users = users_of_profile(faculty.sudo()) if faculty \
                else self.env['res.users'].sudo().browse()
            body = ('【待确认点名】课代表 %s 已提交「%s」%s 的考勤待确认，'
                    '请到「考勤录入」页确认。'
                    % (rep.student_id.name or '', subject.name or '',
                       sheet.attendance_date or ''))
            msg = self.env['edu.message'].sudo()
            for user in users:
                msg._notify_event('attendance_rep_submitted', user, body,
                                  sender_uid=self.env.uid)
        except Exception:
            _logger.warning('rep attendance notify failed', exc_info=True)

    def rep_confirm(self):
        """老师一键确认：把课代表的点名建议落成考勤行 + state='done'。

        - 只处理「已有建议里、且尚无考勤行」的学生（幂等，不覆盖既有行）；
        - 落 line 与置 done 在同一个事务里 => **统计正好在确认这一刻才变**。
        """
        Line = self.env['op.attendance.line'].sudo()
        for sheet in self:
            proposal = sheet._rep_proposal_map()
            for stu_id, status in proposal.items():
                if Line.search_count([('attendance_id', '=', sheet.id),
                                      ('student_id', '=', stu_id)]):
                    continue
                present = status in ('present', 'late')
                Line.create({
                    'attendance_id': sheet.id,
                    'student_id': stu_id,
                    'present': present,
                    'late': status == 'late',
                    'absent': status == 'absent',
                    'excused': False,
                })
            sheet.state = 'done'
        return True


class EduLeaveRepExt(models.Model):
    """课代表审批请假所需的判定（挂既有 edu.leave，**不新建第二套请假模型**）。

    本类只加**方法**；四个新字段（subject_id / approver_id / approver_kind /
    approved_at）定义在 models/leave.py 的 EduLeave 上，避免两处 _inherit 同名
    字段带来的口径分裂。
    """
    _inherit = 'edu.leave'

    @api.model
    def approver_kind_of(self, user=None):
        """当前（或指定）账号的审批人身份：admin > registrar > faculty。

        用于既有 4 处审批写入点补写 approver_kind —— 同一张表上口径必须一致，
        否则「有的假单显示审批人、有的不显示」（设计 §6.5）。
        """
        user = user or self.env.user
        try:
            if user.has_group('base.group_system'):
                return 'admin'
            if user.has_group('openeducat_core.group_op_back_office_admin'):
                return 'registrar'
        except Exception:
            _logger.warning('approver_kind_of failed uid=%s', user.id,
                            exc_info=True)
        return 'faculty'

    def _approver_vals(self, kind=None, user=None):
        """既有 4 处写入点共用的补写值（**不改状态机**，只补留痕字段）。"""
        user = user or self.env.user
        return {
            'approver_id': user.id,
            'approver_kind': kind or self.approver_kind_of(user),
            'approved_at': fields.Datetime.now(),
        }

    @api.model
    def rep_queue_domain(self, rep):
        """课代表待批队列域（三条同时成立，设计 §3.5）。

        ① 本科目（严格相等，fail-closed：subject_id 为空 => 课代表无权批）；
        ② state='request'；
        ③ **不能批自己** —— 判据是**学生档案 id**（不是 res.users，
           一个学生可能有多个登录账号，见 edu_schedule/models/identity.py:64-65）。
        """
        if not rep or not rep.student_id:
            return [('id', '=', 0)]
        return [
            ('subject_id', '=', rep.subject_id.id),
            ('state', '=', 'request'),
            ('student_id', '!=', rep.student_id.id),
            # 出勤类白名单（系统参数 edu_portal.course_rep_leave_types，默认
            # sick,casual）：legal/other **不进队列、也不许审批**（需求⑨）。
            ('leave_type', 'in', sorted(rep_leave_types(self.env))),
        ]

    @api.model
    def rep_can_handle(self, rep, leave):
        """服务端重新判定（不信前端）：在任 + 严格同课程 + 非本人 + 出勤类。

        任一条不成立即按**不存在**处理（调用方 303 回队列，且不写任何字段）。
        """
        if not rep or not leave:
            return False
        if not rep.is_active_now():
            return False
        if not leave.subject_id or leave.subject_id.id != rep.subject_id.id:
            return False
        if leave.leave_type not in rep_leave_types(self.env):
            return False
        my_student = rep.student_id
        if not my_student or leave.student_id.id == my_student.id:
            return False
        return True

    def rep_set_state(self, rep, new_state, reason=''):
        """课代表审批（通过/驳回）：写状态 + 写审批人 + **课代表专属审计动作名**。"""
        self.ensure_one()
        if not self.rep_can_handle(rep, self):
            return False
        if reason and new_state == 'refused':
            self.write({'reject_reason': reason[:500]})
        was_pending = self.state == 'request'
        vals = {'state': new_state}
        vals.update(self._approver_vals(kind='student_rep'))
        self.write(vals)
        if was_pending:
            self._notify_applicant(new_state)
        self.env['edu.audit.log'].sudo()._log(
            AUDIT_LEAVE_REP, 'edu.leave', self.id, self.name or '',
            '状态 → %s（课代表 %s）' % (new_state, rep.student_id.name or ''))
        return True
