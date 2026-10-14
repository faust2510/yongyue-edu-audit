# -*- coding: utf-8 -*-
"""学生自主报课 + 教务审批 —— op.subject.registration 门户侧扩展。

设计：docs/plans/enroll-v2-design.md（第 2 期，基座 openeducat_core 不动）。

基座 op.subject.registration 已有状态机 draft/submitted/approved/rejected 与
action_submitted/action_approve/action_reject，但基座 action_approve 有两个缺陷：
  1. 学生若还没有该课程的 op.student.course（家长录入/漏建档）会直接抛错；
  2. 即使找到档案也只写 subject_ids，不更新班级/学期、不通知、不审计。
本模块用 _inherit 新增门户字段与方法：
  - action_enroll_approve / action_enroll_reject：自研审批动作（后台按钮与门户
    控制器共用同一入口），找不到档案自动建档，找到则更新档案并整体覆盖科目；
  - _notify_student：审批结果经 B5 通知引擎（edu.message._notify_event，
    事件 key 'subject_reg_result'，见 notify_pref.py NOTIFY_EVENTS）告知学生；
  - 审计统一写 edu.audit.log（失败不阻断）。
"""
import datetime
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# 单据类型：student.course(报课选科) 与 course/change/request 共用
# op.subject.registration 表；doc_type 区分来源（见 repair round-2）。
# 默认取 course_change：存量历史单与 /course/change/request 均为换课单。
# 判断辅助：doc_type 为空的历史单若带科目集 → 视为报课单（迁移警示展示用）。
_DOC_TYPE = [
    ('subject_registration', '选课注册'),
    ('course_change', '课程变更'),
]


class OpSubjectRegistration(models.Model):
    _inherit = 'op.subject.registration'

    applicant_note = fields.Char(
        '申请备注', help='学生填写的选课说明/备注')
    approved_at = fields.Datetime('审批时间')
    approved_by = fields.Many2one('res.users', '审批人')
    reject_reason = fields.Char('驳回原因', help='教务驳回时填写，将通知学生')
    submitted_at = fields.Datetime('提交时间')
    doc_type = fields.Selection(
        _DOC_TYPE, string='单据类型', default='course_change',
        help='subject_registration=学生报课选科；course_change=课程变更/换课。')

    # ------------------------------------------------------------------
    # 通用
    # ------------------------------------------------------------------
    def _subject_payload(self):
        """注册单科目并集（compulsory ∪ elective，去重升序）。"""
        ids = list(self.compulsory_subject_ids.ids) + \
            list(self.elective_subject_ids.ids)
        return sorted(set(ids))

    @api.model
    def _infer_doc_type(self):
        """存量单据迁移判定：有科目集的单视为选课注册（报课），否则课程变更。

        执行时机：_auto_init（建列后）。
        说明：Odoo 加列时会把字段默认值 course_change 回填到存量行，
        因此这里用「带科目集 ⇒ subject_registration」的修正规则——
        /course/change/request 建单从不写科目，故该规则安全且幂等。
        """
        self.env.cr.execute(
            "UPDATE op_subject_registration r SET doc_type = 'subject_registration' "
            "WHERE r.doc_type IS DISTINCT FROM 'subject_registration' "
            "AND (EXISTS ("
            "  SELECT 1 FROM subject_compulsory_rel m WHERE m.register_id = r.id) "
            " OR EXISTS ("
            "  SELECT 1 FROM op_subject_op_subject_registration_rel e "
            "  WHERE e.op_subject_registration_id = r.id))")
        return True

    def _auto_init(self):
        """建列后执行存量迁移：空 doc_type 按科目集有无回填。

        迁移幂等：UPDATE 只命中 doc_type IS NULL 的行；列不存在时
        _infer_doc_type 的 SQL 会抛 ProgrammingError，被捕获告警跳过
        （首次建表后列必然存在，此分支仅防御重复触发）。
        """
        res = super()._auto_init()
        try:
            self._infer_doc_type()
        except Exception:
            _logger.warning('registration doc_type migration failed',
                            exc_info=True)
        return res

    def _legacy_empty_subject(self):
        """历史/空科目单警示：doc_type 为空或 course_change 且无科目 → True。

        教务聚合默认只列 doc_type=subject_registration 的单；若教务仍进入
        历史 course_change（换课，本来无科目）或 0 科目单详情，前端红条提示
        「通过将清空档案科目」（见 approval_detail 视图）。
        """
        return not self._subject_payload()

    def _ccr_current_label(self):
        """学生当前在读档案的「课程 · 班」标签（只读展示；取不到返回 '—'）。

        定位口径与 _ccr_source_archive 同：只认唯一 running 档案。
        """
        if not self.student_id:
            return '—'
        scs = self.env['op.student.course'].sudo().search([
            ('student_id', '=', self.student_id.id),
            ('state', '=', 'running')], order='id desc')
        if len(scs) != 1:
            return '—'
        return '%s · %s' % (scs.course_id.name or '—',
                            scs.batch_id.name or '—')

    def _notify_student(self, result, old_label=None):
        """审批结果通知学生（对齐 models/leave.py _notify_applicant 写法）。

        - 收件人 = 学生门户账号（op.student.user_id），无账号或就是审批人跳过；
        - 事件 key 'subject_reg_result'（校长拍板 P4：**复用既有事件，不新增 key**），
          学生可在 /my/notify 静音；
        - 换班/换课单（doc_type=course_change）走独立文案：必须自证是
          「**这一次的变更**」——带「原课程/班 → 新课程/班」，不允许只发
          「课表变了」这种无法核对的话（照 C-1 §7.4 #2 的口径）；
        - 通知失败只告警，不影响审批事务。
        """
        student = self.student_id.sudo() if self.student_id else None
        user = student.user_id if student else None
        if not user or user.id == self.env.uid:
            return
        course_name = self.course_id.name or '课程'
        batch_name = self.batch_id.name or '—'
        target = '%s · %s' % (course_name, batch_name)
        if self.doc_type == 'course_change':
            old = old_label or self._ccr_current_label()
            if result == 'approved':
                body = ('【换班通知】您的换班/换课申请 %s 已通过：%s → %s。'
                        '课表、任课教师与「我的课程」已按新班生效；'
                        '原班的已录考勤与成绩仍可在门户查看。'
                        % (self.name or '—', old, target))
            else:
                body = ('【换班通知】您的换班/换课申请 %s（目标：%s）已被驳回。'
                        % (self.name or '—', target))
                if self.reject_reason:
                    body += '\n驳回原因：%s' % self.reject_reason
        elif result == 'approved':
            n = len(self._subject_payload())
            body = ('【选课通知】您的选课申请 %s（%s · %s）已通过，'
                    '共 %d 门科目已生效，可在「我的课程 / LMS」中开始学习。'
                    % (self.name or '—', course_name, batch_name, n))
        else:
            body = ('【选课通知】您的选课申请 %s（%s · %s）已被驳回。'
                    % (self.name or '—', course_name, batch_name))
            if self.reject_reason:
                body += '\n驳回原因：%s' % self.reject_reason
        try:
            self.env['edu.message']._notify_event(
                'subject_reg_result', user, body)
        except Exception:
            _logger.warning('subject_reg notify failed rec=%s',
                            self.id, exc_info=True)

    # ------------------------------------------------------------------
    # 审批动作（门户/后台共用；门禁在控制器/视图按钮处）
    # ------------------------------------------------------------------
    def action_enroll_approve(self):
        """通过注册单：建/更新 op.student.course + 科目挂靠 + 通知 + 审计。

        规避基座 action_approve 的两处缺陷：找不到档案自动建档（running +
        回填学期），找到则更新 batch 并整体覆盖 subject_ids（注册单 = 最新
        意愿，档案 subject_ids 仍是 LMS/课表读取的事实源）。
        """
        for rec in self:
            if rec.state != 'submitted':
                # 幂等/终态保护：approved/rejected 不再流转
                continue
            student = rec.student_id
            course = rec.course_id
            batch = rec.batch_id
            if not (student and course and batch) \
                    or (batch.course_id.id != course.id):
                raise ValidationError(
                    '注册单缺少学生/课程/班级，或班级不属于该课程。')
            sc_env = self.env['op.student.course'].sudo()
            # 优先取 running 在读档案；无在读再退回任意档案（finished 等）。
            sc = sc_env.search([
                ('student_id', '=', student.id),
                ('course_id', '=', course.id),
                ('state', '=', 'running')], order='id desc', limit=1) \
                or sc_env.search([
                    ('student_id', '=', student.id),
                    ('course_id', '=', course.id)], order='id', limit=1)
            subject_ids = rec._subject_payload()
            # 防呆（repair round-3，2026-09-17 校长裁定「拦住吧」）：
            # **不再限定 doc_type** —— 任何注册单只要 payload 为空、而学生档案已有科目，
            # 就拒绝整体覆盖为空。此前只对 subject_registration 生效，
            # course_change 等 doc_type 可绕过（2026-09-17 学生档案被清空即由此而来，
            # 见 docs/dev-workflow.md「夹具不得克隆语义字段」）。
            # 教务仍可先给注册单加科目再通过，或走课程变更流程。
            if not subject_ids and sc and sc.subject_ids:
                raise UserError(
                    '该报课单未包含任何科目，且学生当前档案已有 %d 门科目；'
                    '通过将清空其档案科目。请先在注册单中添加科目，'
                    '或改用课程变更流程。' % len(sc.subject_ids))
            # 学期：沿用同学生同课程档案的学期；没有则按日期取进行中学期
            # （op.subject.registration 无学期字段；op.academic.term 无
            # is_current，故用日期覆盖今天判定进行中 term）
            term = sc.academic_term_id if sc and sc.academic_term_id \
                else self._running_term()
            if not sc:
                sc = sc_env.create({
                    'student_id': student.id,
                    'course_id': course.id,
                    'batch_id': batch.id,
                    'academic_years_id': (
                        term.academic_year_id.id if term else False),
                    'academic_term_id': term.id if term else False,
                    'state': 'running',
                    'subject_ids': [(6, 0, subject_ids)],
                })
            else:
                vals = {
                    'subject_ids': [(6, 0, subject_ids)],
                    'state': 'running',
                }
                if not sc.batch_id or sc.batch_id.course_id.id == course.id:
                    # 转班/合班：更新到注册单目标班级（仅同课程班级）
                    vals['batch_id'] = batch.id
                if term and term != sc.academic_term_id:
                    vals['academic_term_id'] = term.id
                    if term.academic_year_id and \
                            term.academic_year_id != sc.academic_years_id:
                        vals['academic_years_id'] = term.academic_year_id.id
                sc.write(vals)
            rec.write({
                'state': 'approved',
                'approved_at': fields.Datetime.now(),
                'approved_by': self.env.uid,
            })
            rec._notify_student('approved')
            self.env['edu.audit.log'].sudo()._log(
                '选课审批', 'op.subject.registration', rec.id,
                rec.name or '', '通过：档案 %s（课程 %s），科目 %d 门'
                % (sc.id, course.name or '', len(subject_ids)))
        return True

    def action_enroll_reject(self):
        """驳回注册单：须已有驳回原因；通知 + 审计。

        供后台表单按钮（reject_reason 在表单上填好）与门户控制器
        （先写 reject_reason 再调用）共用。换班/换课单（doc_type=course_change）
        同样走这里，文案由 _notify_student 按 doc_type 分支。
        """
        for rec in self:
            if rec.state != 'submitted':
                continue
            if not (rec.reject_reason or '').strip():
                raise UserError('驳回前请先填写「驳回原因」。')
            rec.write({'state': 'rejected'})
            rec._notify_student('rejected')
            _ctrl = '调班审批' if rec.doc_type == 'course_change' \
                else '选课审批'
            self.env['edu.audit.log'].sudo()._log(
                _ctrl, 'op.subject.registration', rec.id,
                rec.name or '', '驳回：原因 %s' % rec.reject_reason)
        return True

    # ------------------------------------------------------------------
    # 换班 / 换课审批（设计：docs/plans/class-change-request-design.md §19）
    #
    # 载体裁定（v2）：修好既有 /course/change/request 链路（doc_type=
    # course_change）并把它收口成唯一的「归属变更」入口 —— 不新增 doc_type、
    # 不新增路由族。审批动作 = 这一个方法。
    #
    # 两条铁律（违反就是返工）：
    #   ① 只原地改写 op.student.course 的那一行，**永不新建行** —— 否则
    #      「换回原班」会永久撞 unique(student_id, course_id, batch_id)
    #      （openeducat_erp/openeducat_core/models/student.py:49-51），不可逆；
    #   ② 换课程时**必须**按目标课程重算 subject_ids（它是 LMS 的事实源，
    #      controllers/lms.py:24-37），并与 course_id / batch_id /
    #      academic_term_id 在**同一次 write** 里原子完成（§19.2.2 #1/#3）。
    #
    # ⚠ 本方法必须留在本文件（与既有唯一写库点 action_enroll_approve 同文件）：
    #   落别处会当场触发收口条件 C2 = 需求 7 §8.4 T3
    #   （「出现第二个给学生定班的写库入口」）。
    # ------------------------------------------------------------------
    def _ccr_source_archive(self):
        """定位被改写的那一行档案（**零新字段**口径，§19.2.2 #5-(a)）。

        只认「该生唯一一条 running 档案」：0 条 → 引导先分班；>1 条 → 拒绝。
        绝不猜哪一行 —— 门户多处取 running 都是 limit=1 且无 order
        （controllers/main.py:47-55、scheduling.py:100-103）。
        """
        self.ensure_one()
        student = self.student_id
        if not student:
            raise UserError('该申请单没有学生，无法变更归属，请驳回。')
        scs = self.env['op.student.course'].sudo().search([
            ('student_id', '=', student.id), ('state', '=', 'running')])
        if not scs:
            raise UserError(
                '该生尚无在读课程档案，无法变更归属。请先在学生页面为其分班，'
                '或驳回让学生重新提交。')
        if len(scs) > 1:
            raise UserError(
                '该生有 %d 条在读档案，无法确定要变更哪一条（门户取档案无排序，'
                '改错行的风险不可接受）。请先处理多余的档案，再审批本申请。'
                % len(scs))
        return scs

    def _ccr_target_check(self, sc, new_roll_number=None):
        """目标课程/班级校验 + 撞唯一约束预检（§8.3 R2/R3、§19.2.2 #4）。

        返回 (course, batch)。任一条不通过就抛人话 UserError（不抛
        IntegrityError、不写任何一行）。
        """
        self.ensure_one()
        course, batch = self.course_id, self.batch_id
        if not (course and batch):
            raise UserError(
                '该申请单缺少目标课程或目标班级，单据不自洽，请驳回让学生重新提交。')
        if batch.course_id.id != course.id:
            raise UserError(
                '目标班级「%s」属于课程「%s」，与单据上的目标课程「%s」不一致，'
                '单据不自洽，请驳回让学生重新提交。'
                % (batch.name or '', batch.course_id.name or '—',
                   course.name or ''))
        if not batch.active:
            raise UserError(
                '目标班级「%s」已停用，不能作为换班目标。请驳回让学生重新选择。'
                % (batch.name or ''))
        if sc.course_id.id == course.id and sc.batch_id.id == batch.id:
            raise UserError(
                '该生当前已在「%s · %s」，与申请目标一致，无需变更。'
                '请驳回该申请。' % (course.name or '', batch.name or ''))
        sc_env = self.env['op.student.course'].sudo()
        # 预检①：unique(student_id, course_id, batch_id)
        clash = sc_env.search([
            ('student_id', '=', sc.student_id.id),
            ('course_id', '=', course.id),
            ('batch_id', '=', batch.id),
            ('id', '!=', sc.id)], limit=1)
        if clash:
            raise UserError(
                '该生已存在一条「%s · %s」的课程档案（档案 id %d），'
                '与本次变更目标重复。直接改写会撞唯一约束，'
                '请先在学生页面处理那条档案，或驳回改为其它班级。'
                % (course.name or '', batch.name or '', clash.id))
        # 预检②：unique(roll_number, course_id, batch_id) —— 换课程后教务
        # 需填新学号（P8-(b)），学号在生产非空（含课程码）故这条是活的。
        roll = (new_roll_number or '').strip() or sc.roll_number
        if roll:
            dup = sc_env.search([
                ('roll_number', '=', roll),
                ('course_id', '=', course.id),
                ('batch_id', '=', batch.id),
                ('id', '!=', sc.id)], limit=1)
            if dup:
                raise UserError(
                    '学号「%s」在目标「%s · %s」已被学生「%s」占用，'
                    '无法直接使用。请换一个学号，或驳回让学生重新申请。'
                    % (roll, course.name or '', batch.name or '',
                       dup.student_id.name or '—'))
        return course, batch

    def _ccr_faculty_users(self, batch):
        """某班任课教师账号（本仓无「班主任」字段，取课节 faculty 去重）。

        账号解析**两种口径取并集**（实测必须）：
          ① 本仓既有口径 op.faculty.user_id —— op.faculty 是
             _inherits = {res.partner: partner_id}，该字段委托到
             res.partner.user_id（edu_schedule/models/session_ext.py:280 同款；
             本地 faculty@local 就是这样挂上的，partner_id 与 user.partner_id
             **并不相等**）；
          ② Odoo 官方反向口径 res.users.partner_id。
        只写 ② 会 0 收件人（本地实测：faculty 17 的 partner=32，而 user 11 的
        partner_id=48 ⇒ 交集为空），教师通知会静默消失。
        """
        if not batch:
            return self.env['res.users']
        facs = self.env['op.session'].sudo().search(
            [('batch_id', '=', batch.id)]).mapped('faculty_id')
        if not facs:
            return self.env['res.users']
        users = facs.mapped('user_id')            # ① 既有口径（委托字段）
        users |= self.env['res.users'].sudo().search(   # ② 官方反向口径
            [('partner_id', 'in', facs.mapped('partner_id').ids)])
        return users

    def _ccr_notify_teachers(self, old_batch, new_batch, old_label, new_label,
                             student_name):
        """通知旧班 + 新班任课教师（P9-(b)）：名单当场就变，教师是受影响方。

        事件 key 仍复用 subject_reg_result（P4：复用既有事件，不新增 key）。
        已知边界（§19.10 v2-3）：课表里没有任何课节的班取不到教师 ⇒ 0 人。
        """
        pairs = ((old_batch, '%s（该生已转出）' % old_label),
                 (new_batch, '%s（该生已转入）' % new_label))
        for batch, verb in pairs:
            body = ('【换班通知】学生 %s 的换班/换课申请已通过：%s → %s。'
                    '班级名单已即时更新 —— %s，请核对点名表与评教名单。'
                    % (student_name or '—', old_label, new_label, verb))
            for user in self._ccr_faculty_users(batch):
                if user.id == self.env.uid:
                    continue
                try:
                    self.env['edu.message']._notify_event(
                        'subject_reg_result', user, body)
                except Exception:
                    _logger.warning('ccr notify teacher failed rec=%s u=%s',
                                    self.id, user.id, exc_info=True)

    def action_course_change_approve(self, new_roll_number=None):
        """通过换班/换课单：原地改写同一行 op.student.course（永不新建行）。

        new_roll_number：教务在审批详情页填的新学号（可留空 = 保留原号），
        换课程时用（设计 P8-(b)；撞唯一约束预检见 _ccr_target_check）。
        """
        for rec in self:
            if rec.state != 'submitted':
                # 幂等/终态保护：approved/rejected 不再流转
                continue
            if rec.doc_type != 'course_change':
                raise UserError(
                    '「%s」不是换班/换课单（单据类型 %s），不能用本动作审批。'
                    % (rec.name or '', rec.doc_type or '—'))
            sc = rec._ccr_source_archive()
            course, batch = rec._ccr_target_check(sc, new_roll_number)
            old_course, old_batch = sc.course_id, sc.batch_id
            old_label = '%s · %s' % (
                old_course.name or '—', old_batch.name or '—')
            new_label = '%s · %s' % (course.name or '', batch.name or '')
            vals = {'state': 'running'}
            if old_course.id != course.id:
                # 换课程：4 个字段一次 write（原子）；subject_ids 按目标课程
                # 重算 —— 否则会留下「档案说新课程、科目还是旧课程」的半写。
                vals.update({
                    'course_id': course.id,
                    'batch_id': batch.id,
                    'subject_ids': [(6, 0, course.subject_ids.ids)],
                })
                term = rec._running_term()
                if term:
                    vals['academic_term_id'] = term.id
                    if term.academic_year_id:
                        vals['academic_years_id'] = term.academic_year_id.id
            else:
                # 只换班：绝不碰 subject_ids（科目属于课程，不属于班）
                vals['batch_id'] = batch.id
            roll = (new_roll_number or '').strip()
            if roll:
                vals['roll_number'] = roll
            sc.sudo().write(vals)
            rec.write({
                'state': 'approved',
                'approved_at': fields.Datetime.now(),
                'approved_by': self.env.uid,
            })
            rec._notify_student('approved', old_label=old_label)
            rec._ccr_notify_teachers(
                old_batch, batch, old_label, new_label,
                rec.student_id.name or '—')
            self.env['edu.audit.log'].sudo()._log(
                '调班审批', 'op.subject.registration', rec.id, rec.name or '',
                '通过：原 %s → 新 %s（档案 %d，课程 %s→%s，科目 %d 门）'
                % (old_label, new_label, sc.id,
                   old_course.id, course.id, len(course.subject_ids)))
        return True

    # ------------------------------------------------------------------
    # 学期判定（op.academic.term 无 is_current，用日期覆盖今天判定）
    # ------------------------------------------------------------------
    def _running_term(self):
        today = datetime.date.today()
        term = self.env['op.academic.term'].sudo().search([
            ('term_start_date', '<=', today),
            ('term_end_date', '>=', today),
        ], order='term_start_date desc', limit=1)
        return term


# ----------------------------------------------------------------------
# F6：报课前置校验（先修 / 学分 / 容量）—— 基座没有这些字段，门户侧扩展
# 放置说明：t7 只允许改在册的 edu_portal 模型文件（manifest 与 models/
# __init__.py 不在 inScope），故扩展与配置模型就近放在本文件，不改基座。
# ----------------------------------------------------------------------
class OpSubjectExt(models.Model):
    """科目扩展：学分与容量（不改基座 openeducat_erp）。"""
    _inherit = 'op.subject'

    credit_points = fields.Float('学分', digits=(6, 1), default=0.0)
    capacity = fields.Integer(
        '容量', default=0, help='0=不限；在读人数达到容量后不再放行报课')


class EduSubjectPrereq(models.Model):
    """先修科目要求：报某科目（subject_id）要求先修过 prereq_subject_id。"""
    _name = 'edu.subject.prereq'
    _description = '先修科目要求'
    _order = 'subject_id, id'

    subject_id = fields.Many2one(
        'op.subject', '科目', required=True, ondelete='cascade')
    prereq_subject_id = fields.Many2one(
        'op.subject', '先修科目', required=True, ondelete='cascade')
    min_marks = fields.Integer(
        '最低分', default=0,
        help='0=只看是否修过；大于 0 时按该分数判定是否通过与')
    note = fields.Char('说明', size=128)
    active = fields.Boolean('启用', default=True)

    _edu_prereq_uniq = models.Constraint(
        'UNIQUE (subject_id, prereq_subject_id)',
        '同一科目的同一先修要求只能配置一条。')

    @api.model
    def _edu_credits_of(self, student):
        """学生当前在读学分合计。"""
        scs = self.env['op.student.course'].sudo().search([
            ('student_id', '=', student.id), ('state', '=', 'running')])
        return sum(scs.mapped('subject_ids').mapped('credit_points'))

    @api.model
    def _edu_max_credits(self):
        """学分上限（系统参数 edu_portal.max_credits；0=不限）。"""
        try:
            return float(self.env['ir.config_parameter'].sudo().get_param(
                'edu_portal.max_credits', '0') or 0)
        except (TypeError, ValueError):
            return 0.0

    @api.model
    def _edu_enrolled_count(self, subject):
        """科目在读人数（容量校验用）。"""
        return self.env['op.student.course'].sudo().search_count([
            ('subject_ids', 'in', [subject.id]),
            ('state', '=', 'running')])

    @api.model
    def _edu_passed_subject(self, student, subject, min_marks=0):
        """学生是否修过并通过该科目（按考试成绩判定）。"""
        atts = self.env['op.exam.attendees'].sudo().search([
            ('student_id', '=', student.id),
            ('exam_id.subject_id', '=', subject.id),
            ('status', '=', 'present')])
        for att in atts:
            threshold = min_marks or (att.exam_id.min_marks or 0)
            if att.marks and att.marks >= threshold:
                return True
        return False

    @api.model
    def edu_precheck(self, student, subject_ids):
        """报课前置校验：返回 {subject_id: [拦截原因, ...]}（空则放行）。

        三类校验（先例见 docs/research/onestop-learning-and-repetitive-work.md）：
        - 先修：edu.subject.prereq 配置的要求；
        - 学分：在读 + 本次申请合计不超过 edu_portal.max_credits（0=不限）；
        - 容量：op.subject.capacity 与在读人数比较（0=不限）。
        """
        result = {}
        if not student:
            return result
        subjects = self.env['op.subject'].sudo().browse(
            list(subject_ids or []))
        current = self._edu_credits_of(student)
        new_credits = sum(subjects.mapped('credit_points'))
        max_credits = self._edu_max_credits()
        for subject in subjects:
            blockers = []
            prereqs = self.sudo().search([
                ('subject_id', '=', subject.id), ('active', '=', True)])
            for pre in prereqs:
                if not self._edu_passed_subject(
                        student, pre.prereq_subject_id, pre.min_marks):
                    blockers.append('未满足先修：%s（%s）' % (
                        pre.prereq_subject_id.name or '—',
                        pre.note or '需先修并通过'))
            if max_credits and (current + new_credits) > max_credits:
                blockers.append(
                    '学分超限：在读 %g + 本次 %g > 上限 %g'
                    % (current, new_credits, max_credits))
            cap = subject.capacity or 0
            if cap:
                enrolled = self._edu_enrolled_count(subject)
                if enrolled >= cap:
                    blockers.append('容量已满：%d/%d' % (enrolled, cap))
            result[subject.id] = blockers
        return result


# ----------------------------------------------------------------------
# F3：成绩变更留痕（Moodle grade_grades_history 的字段语义）
# ----------------------------------------------------------------------
class EduGradeHistory(models.Model):
    """成绩变更留痕：谁、何时、把哪个学生的哪门考试分数从多少改到多少。

    对应 Moodle grade_grades_history 的 action / loggeduser / oldvalue /
    newvalue / source / timemodified 六个字段语义；国内三家教务 SaaS 均
    没有成绩留痕能力（见 docs/research/... §4.3），故按差异点做扎实。
    """
    _name = 'edu.grade.history'
    _description = '成绩变更留痕'
    _order = 'timemodified desc, id desc'

    exam_id = fields.Many2one(
        'op.exam', '考试', required=True, index=True, ondelete='cascade')
    student_id = fields.Many2one(
        'op.student', '学生', index=True, ondelete='cascade')
    subject_id = fields.Many2one(
        'op.subject', '科目', related='exam_id.subject_id', store=True)
    old_marks = fields.Integer('原分数')
    new_marks = fields.Integer('新分数')
    action = fields.Selection([
        ('create', '首次录入'),
        ('update', '修改'),
        ('import', '导入'),
        ('copy', '复制'),
    ], string='动作', required=True, default='update')
    source = fields.Selection([
        ('manual', '页面录入'),
        ('import', '文件导入'),
        ('copy', '上期复制'),
        ('system', '系统'),
    ], string='来源', default='manual', required=True)
    logged_user_id = fields.Many2one(
        'res.users', '操作人', default=lambda self: self.env.uid)
    timemodified = fields.Datetime(
        '修改时间', default=fields.Datetime.now, required=True)
    note = fields.Char('备注', size=128)

    @api.model
    def edu_apply_marks(self, att, marks=None, status=None,
                        source='manual', note=None):
        """改分/改状态的唯一入口：写 op.exam.attendees 并留痕。

        返回 'create'（首次录入）/ 'update'（修改）/ ''（无变化）；
        调用方（页面保存、CSV 导入、上期复制）共用，保证留痕无死角。
        """
        vals = {}
        if marks is not None and marks != att.marks:
            vals['marks'] = marks
        if status and status != att.status:
            vals['status'] = status
        if not vals:
            return ''
        old_marks = att.marks
        # t42：用 context 标记声明「本次写入来自受管入口」，替代 t34 的调用栈扫描
        # （栈深 > 8 或中间多包一层就会漏判 → 双记留痕；context 与调用深度无关）
        att.with_context(edu_marks_entry=True).write(vals)
        action = 'create' if old_marks in (0, False, None) else 'update'
        self.sudo().create({
            'exam_id': att.exam_id.id,
            'student_id': att.student_id.id,
            'old_marks': old_marks or 0,
            'new_marks': att.marks or 0,
            'action': action if source == 'manual' else (
                'import' if source == 'import' else 'copy'),
            'source': source,
            'logged_user_id': self.env.uid,
            'note': note,
        })
        return action

# ---------------------------------------------------------------------------
# t88：报名 / 报课截止日（后台可自助修改）
#
# 铁律 0 调研（简要）：
#   · Odoo 核心的「后台设置表单」标准写法 = res.config.settings + config_parameter
#     属性（字段值经 get_values/set_values 落到 ir.config_parameter）；
#   · 本仓现有惯例 = ir.config_parameter.sudo().get_param(key, default)
#     （registration.py / leave.py / batch2.py / batch3.py / roles.py / downloads.py
#      / session_ext.py 共 7+ 处），故沿用同一存储，不引入新配置机制；
#   · OpenEduCat 侧无可复用的"招生/报课截止"字段（op.batch.end_date 是排课语义：
#     班级结束日，与"报课窗口"不是一回事），故不复用、另立两个参数。
#
# t110 修复（/odoo/settings 整页 500，任何人打不开设置页）
#   症状：打开设置页 → 前端「出了点问题」；RPC default_get 抛
#     "Field res.config.settings.edu_apply_deadline must have type 'boolean',
#      'integer', 'float', 'char', 'selection', 'many2one' or 'datetime'"
#   根因（读源码，非猜测）：res.config.settings 的 **config_parameter 字段**
#     走 odoo/addons/base/models/res_config.py:_get_classified_fields()，那里对
#     带 config_parameter 的字段做**类型白名单**（上述 7 种），fields.Date 不在
#     其中 ⇒ default_get 一进循环就抛。这是模型级错误、与用户是谁无关，
#     所以**任何人**（含管理员）都会撞上。
#   修法：字段类型改 fields.Datetime（白名单内），但**存储格式与语义一字不变**：
#     · ir.config_parameter 里仍是 'YYYY-MM-DD'（get_raw/get_cn 与
#       data/timetable_params.xml 都按它解析，两者本文件内未改动）；
#     · 视图 options show_time=False ⇒ 表单上只有日期选择，没有时间输入；
#     · 换算由 to_form_value/from_form_value 双向负责（详见其 docstring）：
#       两侧同一时区 ⇒ 任意时区的用户看到的日期 == 存下的日期，无时区漂移；
#       时间部分一律丢弃 ⇒ 无格式漂移。
# ---------------------------------------------------------------------------
class EduDeadline(models.AbstractModel):
    """截止日的读取与**中文预格式化**（QWeb 内禁 % 格式化 → 在此算好）。"""

    _name = 'edu.deadline'
    _description = '报名与报课截止日'

    DEFAULTS = {
        'edu.apply.deadline': '2026-10-01',
        'edu.enroll.deadline': '2026-10-01',
    }

    @api.model
    def get_raw(self, key):
        """★ 消费方契约（t110 修复**未动**）：返回 'YYYY-MM-DD' 字符串。"""
        return (self.env['ir.config_parameter'].sudo().get_param(key)
                or self.DEFAULTS.get(key, ''))

    @api.model
    def get_cn(self, key):
        """★ 消费方契约（t110 修复**未动**）：'2026年10月1日'。"""
        raw = self.get_raw(key)
        try:
            d = fields.Date.to_date(raw)
        except Exception:
            return raw
        return '%d年%d月%d日' % (d.year, d.month, d.day)

    # --- t110：res.config.settings 表单值 ↔ 参数值 的双向换算 ----------------
    # 时区只做**载体**、不参与语义：两侧都用同一个 self.env.tz（同一请求内的
    # 当前用户时区），所以「读出来的日期」== 「写进去的日期」，与用户时区无关。
    @api.model
    def _utc_naive_to_local(self, naive_utc):
        """朴素 UTC → 当前用户时区的 aware datetime（失败则原样返回）。"""
        try:
            return fields.Datetime.context_timestamp(self, naive_utc)
        except Exception:
            return naive_utc

    @api.model
    def _local_to_utc_naive(self, naive_local):
        """当前用户时区的朴素本地时间 → 朴素 UTC。"""
        tz = self.env.tz
        try:
            localize = getattr(tz, 'localize', None)
            aware = (localize(naive_local) if localize
                     else naive_local.replace(tzinfo=tz))
        except Exception:
            try:                      # 夏令时空洞（本地不存在这一时刻）
                aware = tz.localize(naive_local, is_dst=False)
            except Exception:
                return naive_local
        return aware.astimezone(datetime.timezone.utc).replace(tzinfo=None)

    @api.model
    def to_form_value(self, key):
        """参数 'YYYY-MM-DD' → 设置表单字段值（**朴素 UTC** datetime）。

        取「当前用户时区里该日的零点」：客户端按同一时区渲染，用户看到的日期
        恒等于存下的日期（正负时区都对），且时间位永远显示 00:00 —— 时间只是
        把日期钉在本地零点的载体，不是语义的一部分。
        """
        raw = self.get_raw(key)
        try:
            d = fields.Date.to_date(raw)
        except Exception:
            return False
        if not d:
            return False
        return self._local_to_utc_naive(
            datetime.datetime.combine(d, datetime.time.min))

    @api.model
    def from_form_value(self, value):
        """设置表单字段值（朴素 UTC）→ 参数串 'YYYY-MM-DD'。

        时间部分**有意丢弃**：截止日是「天」的语义（截止日当天仍在窗口内），
        存时间只会带来格式漂移与时区偏移，所以入库格式与 t88 时**一字未变**。
        """
        if not value:
            return ''
        dt = fields.Datetime.to_datetime(value)
        if not dt:
            return ''
        return self._utc_naive_to_local(dt).date().isoformat()


# (设置表单字段名, ir.config_parameter key)：两处截止日共用同一套换算与落库口径
EDU_DEADLINE_CONFIG = (
    ('edu_apply_deadline', 'edu.apply.deadline'),
    ('edu_enroll_deadline', 'edu.enroll.deadline'),
)


def _deadline_default(key):
    """字段默认值 = **当前已配置的截止日**（不是写死的常量）。

    为什么默认值要跟着参数走：设置页不止一个 —— 本表单（menu 617）与主设置页
    /odoo/settings。主设置页的视图里**没有**这两个字段，客户端提交时可能不带它们，
    这时记录上取到的是「默认值」；若默认值是常量，主设置页任意一次保存都会把学校
    改过的截止日悄悄改回那个常量。默认值跟着参数走 ⇒ 「没带这个字段」的提交写回
    同一个日期，幂等、不可能误改（对照读数见 tests/smoke/settings_page_probe.py
    的 no-op save 用例）。
    """
    def _get(settings):
        try:
            return settings.env['edu.deadline'].to_form_value(key)
        except Exception:              # 列初始化等无库上下文：宁可空值（= 不改）
            _logger.warning('edu.deadline 默认值不可用（key=%s）', key)
            return False
    return _get


class ResConfigSettings(models.TransientModel):
    """把两个截止日暴露成后台表单字段（学校自己改，不必手改系统参数）。"""

    _inherit = 'res.config.settings'

    # ★ 类型必须是 datetime：res.config.settings 的 config_parameter 字段只认
    #   boolean/integer/float/char/selection/many2one/datetime（文件头 t110）。
    #   语义仍是「日期」——视图 options show_time=False（表单上只有日期，无时间输入）。
    edu_apply_deadline = fields.Datetime(
        string='报名截止', config_parameter='edu.apply.deadline',
        default=_deadline_default('edu.apply.deadline'),
        help='只取日期（年月日）：截止日当天仍算在报名窗口内；时间不参与判定、不入库。')
    edu_enroll_deadline = fields.Datetime(
        string='报课截止', config_parameter='edu.enroll.deadline',
        default=_deadline_default('edu.enroll.deadline'),
        help='只取日期（年月日）：截止日当天仍算在报课窗口内；时间不参与判定、不入库。')

    @api.model
    def get_values(self):
        """表单读值：参数 'YYYY-MM-DD' → 本用户时区的当日零点（朴素 UTC）。"""
        res = super().get_values()
        D = self.env['edu.deadline']
        for fname, key in EDU_DEADLINE_CONFIG:
            res[fname] = D.to_form_value(key)
        return res

    def set_values(self):
        """表单存值：只取日期，落回 ir.config_parameter（稳定 'YYYY-MM-DD'）。

        顺序说明：基类 set_values 会按 datetime 口径先写一遍
        （'YYYY-MM-DD HH:MM:SS'）—— 本方法在其后**覆盖**成 'YYYY-MM-DD'，
        正是消费方（get_raw/get_cn）与 data/timetable_params.xml 认的格式。
        空输入 = **不改**（截止日必须始终可解析；空值不写、也不删旧值）。
        """
        D = self.env['edu.deadline']
        icp = self.env['ir.config_parameter'].sudo()
        previous = {key: icp.get_param(key) for _f, key in EDU_DEADLINE_CONFIG}
        super().set_values()
        for fname, key in EDU_DEADLINE_CONFIG:
            value = (D.from_form_value(self[fname])
                     or previous.get(key) or D.DEFAULTS.get(key, ''))
            if value and icp.get_param(key) != value:
                icp.set_param(key, value)
