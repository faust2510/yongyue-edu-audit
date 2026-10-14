# -*- coding: utf-8 -*-
"""请假分级审批 —— **模型逻辑（S2）**：唯一路由点 + 状态机 + 转交 + 销假 + 条例校验。

设计稿：docs/plans/leave-split-approval-design.md
  · §3 状态机 / 审批人解析 / 边界 / 空值（§3.1–§3.5）
  · §4 转交审批（§4.2 表 / §4.3 四条规则 / §4.4 动作面）
  · §5 角色映射（§5.1 班主任 / §5.3 教职身份 / §5.4 教职单链）
  · §7 条例七条的机器化落点（§7.1 销假 … §7.5 禁止事后补假）
  · §10 的 S2 卡片（范围与交付物）

谁写哪一段（防越界；S1 的字段块一个字都没动）
------------------------------------------------
S1 = 字段声明 + op.batch.homeroom_teacher_id + leave_transfer.py（本文件上半部原样保留）。
S2（本阶段）= 本文件下半部：route_of() / can_user_act() / 状态机 / 转交 / 销假 /
              各 compute 方法体 / 提交校验 / 两个 cron 方法。**只写本文件**，
              不动 __init__.py / __manifest__.py / ACL / migrations。
S3 = controllers/roles.py（门户路由，调用本文件的接口）。
S4 = views/leave_flow.xml（视图 + 新 cron 记录；cron 调 _cron_return_overdue()）。

================================================================================
【接口冻结（S3 只能调用这些名字；S2 不改名）】—— 队长清单逐条对照
================================================================================
  leave.route_of()                     -> RouteResult      实例方法
  route_of(leave)                      -> RouteResult      **模块级同名薄壳**
                                                            （设计稿 §3.2 写的是
                                                            "def route_of(leave)"）
  RouteResult(first_users, second_users, need_second, fallback_reason)  namedtuple
  leave.can_user_act(user=None)        -> bool
  leave.action_first_approve()         -> True
  leave.action_second_approve()        -> True
  leave.action_refuse(reason='')       -> True
  leave.action_send_back(reason='')    -> True
  leave.action_transfer(to_user, reason) -> edu.leave.transfer 记录
  leave.transfer(to_user, reason)      -> 同上（**别名**，同一实现）
  leave.action_confirm_return(note='') -> bool（True=已确认；False=仅提交说明）
  leave.transfer_candidates(stage)     -> res.users
  leave._cron_return_overdue()         -> int（新 cron 入口，@api.model）
  leave.can_user_transfer(user=None)   -> bool（守卫用；比 can_user_act 更严）
  leave.current_approver_label()       -> str（§3.3 的单据显示文案）

⚠ **改名告警**：设计稿 §10 的 S2 卡片写 transfer()，队长清单写 action_transfer()；
  设计稿 §3.2 写模块级 route_of(leave)，队长清单写 edu.leave.route_of(self)。
  本文件**两个名字都提供、共用同一实现**（别名是薄壳，不是第二份逻辑），
  所以任何一侧的调用都不会失败。

⚠ **留痕/通知归属（S3 请勿重复）**
  action_first_approve / action_second_approve / action_refuse 内部**已含**：
    · 审批留痕 approver_id / approver_kind / approved_at（走既有 _approver_vals()）
    · 终态时 _notify_applicant()（事件 key leave_result）
    · edu.audit.log（动作名沿用既有「请假审批」，**不改既有动作名**）
    · §7.2 口头证明确认闭环（通过时把 env.user 落成 oral_proof_confirmed_by_id）
  action_transfer 内部**已含** §4.3(4) 的四层留痕（transfer 行 + first/second_approver_id
    改写 + edu.audit.log「请假审批转交」+ 三方 edu.message「leave_transferred」）。
  action_send_back **不通知**（队长裁决 2026-09-25：可见性已足够，不加代码）。

================================================================================
【§3.2 判定表原文（实现逐条对齐）】
================================================================================
学生单：
  班 batch.homeroom_teacher_id 非空 -> 该账号            | 需要二级 = days > 阈值 或 over_quota
  homeroom_teacher_id 为空         -> 教务处组 ∪ 系统组   | 同上；fallback='未设班主任，已转教务处'
  学生无 op.student.course.batch_id -> 教务处组 ∪ 系统组  | 同上；fallback='该生未分班，已转教务处'
二级集合：① 系统参数 edu_portal.leave_principal_user_ids -> ② 教务处组 -> ③ base.group_system
开关：edu_portal.leave_always_two_stage（默认 0；置 1 即一律进 pending_second）
天数：days = (date_to - date_from).days + 1（**含头含尾**，自然日，无任何日历扣减）
阈值：edu_portal.leave_second_approval_days（默认 3）

「取哪个班」的唯一口径（**只写在本文件 _student_batch() 一处**）：
  取该生 op.student.course 中 batch_id 非空、且 batch.end_date **最晚**的一条
  （与 models/course_rep.py:181-203 的 _batch_term_layers「取最晚不早退」同一取舍）。

教职单（§5.4，设计稿唯一一处推定）：一级 = 教务处组；二级 = 系统组
  （仅当 days > 阈值 或 over_quota）。教职身份（§5.3）：applicant_kind='staff'
  <=> 经 edu_schedule/models/identity.py 反查 op.student 与 op.parent 皆空（**不看 share**）。

【§3.3 空值行为（硬要求：没有班主任也能跑）】
  有班主任 -> 班主任；无班主任 -> 教务处组 ∪ 系统组（route_note 落「未设班主任，已转教务处」）；
  未分班 -> 教务处组 ∪ 系统组（route_note「该生未分班，已转教务处」）；
  两组都空 -> **空集**（first_approver_id 留空 + route_note「无可用审批人，请先配置教务处」）。
  => 只 fail-open 到「无人可批但看得见」，**绝不** fail-open 到「任何人都能批」。

⚠ 今天上线会 100% 命中「未设班主任 -> 教务处」（本仓 op.faculty 0 在职、班主任字段全空）。
  这是**设计行为**，不是降级。
"""
import datetime
import logging
from collections import namedtuple

from odoo import api, fields, models
from odoo.exceptions import UserError

# 身份反查的唯一口径（code-map §6 第 13 条）：本文件只经它拿「档案 -> 账号」。
from odoo.addons.edu_schedule.models.identity import users_of_profile

# 既有 48h 超时升级的实现件（cron 39 语义不动，本文件只加「当前应批人」一句）。
from .leave import escalate_hours, notify_approvers

_logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# 常量：系统参数 / 组 / 审计动作名 / 事件 key / 逐字文案
# ══════════════════════════════════════════════════════════════════════
PARAM_SECOND_DAYS = 'edu_portal.leave_second_approval_days'
PARAM_ALWAYS_TWO_STAGE = 'edu_portal.leave_always_two_stage'
PARAM_PRINCIPAL_UIDS = 'edu_portal.leave_principal_user_ids'

GROUP_BACKOFFICE = 'openeducat_core.group_op_back_office_admin'
GROUP_SYSTEM = 'base.group_system'

#: 审计动作名：前两个是**既有**动作名（本文件沿用不改，§4.3(4) 明令），
#: 第三个是本设计的**新动作名**。
AUDIT_APPROVE = '请假审批'
AUDIT_TRANSFER = '请假审批转交'
AUDIT_BACKFILL = '请假事后补录'
AUDIT_RETURN = '销假'
AUDIT_RETURN_APPLY = '销假申请'

#: 站内通知事件 key。leave_transferred 是**新 key**（§4.3(4)），已登记进
#: models/notify_pref.py 的 NOTIFY_EVENTS（否则 /my/notify 偏好页看不到这一类）。
EVENT_TRANSFER = 'leave_transferred'
EVENT_RETURN_OVERDUE = 'leave_return_overdue'

#: 门户提交标记：S3/S4 在门户路由里显式置位时，§7.5 的硬拒**一定**生效。
CTX_PORTAL = 'edu_leave_portal'

#: §3.3 的 route_note 文案（**逐字**，S4 直接展示，不要在视图里改字）
FALLBACK_NO_HOMEROOM = '未设班主任，已转教务处'
FALLBACK_NO_BATCH = '该生未分班，已转教务处'
FALLBACK_NO_APPROVER = '无可用审批人，请先配置教务处'

#: §7.4 事假学期上限（条例二·4「每学期不超过 5 天」）。设计稿未要求做成系统参数。
CASUAL_TERM_QUOTA_DAYS = 5

#: §7.3 提前申请期（条例二·4 事假提前 2 天 / 二·2 婚丧假提前 1–2 周 ⇒ 取 7 天）
LEAD_DAYS_BY_TYPE = {'casual': 2, 'marriage_funeral': 7}

MSG_BACKFILL_DENIED = '《请假条例》一·2 规定严禁事后补假，请勿补提过去日期的申请。'
MSG_PROOF_SICK = ('《请假条例》二·3 规定：连续两天及以上病假必须出示正规医院诊断证明'
                  '（无文本证明可请家长或牧长口头证明）。请先填写「证明方式」。')
MSG_PROOF_MARRIAGE = ('《请假条例》二·2 规定：婚丧假须附证明（喜帖、讣告），'
                      '无文本证明可请家长或牧长口头证明。请先填写「证明方式」。')
MSG_PROOF_ORAL_BY = '口头证明必须填写证明人（家长或牧长），否则不算合法凭证。'
MSG_TRANSFER_ONCE = '该单据该级已转交过 1 次，不能再次转交。'

#: 审批级 -> 中文（审计/通知文案用）
STAGE_LABEL = {'first': '一级', 'second': '二级'}

#: RouteResult：route_of() 的返回结构（设计稿 §3.2 逐字定义四个字段）。
#: first_users / second_users 是 res.users 记录集（**可为空集**，见 §3.3 最后一行）。
RouteResult = namedtuple(
    'RouteResult',
    ['first_users', 'second_users', 'need_second', 'fallback_reason'])
RouteResult.__doc__ = (
    'route_of() 的返回值：first_users=当前一级应批人（res.users，可空集）；'
    'second_users=当前二级应批人（不需要二级时为空集）；need_second=bool；'
    'fallback_reason=str|None（如「未设班主任，已转教务处」）。')


# ══════════════════════════════════════════════════════════════════════
# 模块级小工具（不含业务判断，只做参数/组/集合的读写）
# ══════════════════════════════════════════════════════════════════════
def int_param(env, key, default=0):
    """系统参数取整数；取不到/非法值 ⇒ 默认值（照 leave.py:escalate_hours 的写法）。"""
    try:
        return int(env['ir.config_parameter'].sudo().get_param(key, default)
                   or default)
    except (TypeError, ValueError):
        return default


def second_approval_days(env):
    """二级阈值（天），系统参数可调，默认 3（§3.4）。"""
    return max(0, int_param(env, PARAM_SECOND_DAYS, 3))


def always_two_stage(env):
    """§1.1/§3.2 的预留开关：置 1 ⇒ 一级通过后一律进 pending_second。默认关闭。"""
    return bool(int_param(env, PARAM_ALWAYS_TWO_STAGE, 0))


def user_in_group(user, xmlid):
    """user 是否在 xmlid 组内。

    · 全程 sudo：has_group() 对「非当前用户」会抛 AccessError
      （core res_users.py:1075），不 sudo 会把「查不到」伪装成 500；
    · 组不存在 ⇒ False（core _has_group 里 get_id() 返回 None ⇒ 不抛）。
    """
    if not user:
        return False
    try:
        return bool(user.sudo().has_group(xmlid))
    except Exception:
        _logger.warning('has_group(%s) failed uid=%s', xmlid,
                        getattr(user, 'id', '?'), exc_info=True)
        return False


def group_users(env, xmlid):
    """组 -> 成员账号（组不存在 ⇒ 空集，不抛）。"""
    group = env.ref(xmlid, raise_if_not_found=False)
    if not group:
        return env['res.users'].sudo().browse()
    return group.sudo().user_ids


def active_users(users):
    """只保留在用账号（停用账号不能登录 ⇒ 不可能是「可用审批人」）。"""
    return users.filtered(lambda u: u.active)


def field_default(model, fname, fallback):
    """取字段默认值 —— **Odoo 19 的 field.default 已被归一化为可调用对象**。

    core orm/fields.py:513-516 逐字：「self.default must be either None or a
    callable」，非 callable 的声明值会被包成「lambda model: value」。
    所以「vals.get('x') or self._fields['x'].default」拿到的是一个**函数对象**
    （恒真）⇒ 所有「按默认值判断」的校验会被**静默绕过**。
    本文件 §7.2 的证明材料校验就踩过这个坑（S2 自证时被 P1/P3 用例抓出）：
    2 天病假不带 proof_kind 时 kind 变成了 lambda ⇒ 不判 'none' ⇒ 不拦。
    统一改用本 helper（callable 就用 model 调用一次，异常按取不到处理）。
    """
    default = model._fields[fname].default
    if callable(default):
        try:
            default = default(model)
        except TypeError:
            default = None
    return default if default is not None else fallback


def route_of(leave):
    """**模块级**路由入口（设计稿 §3.2 的 "def route_of(leave)" 逐字对应）。

    与实例方法 leave.route_of() 共用同一实现 —— 两条调用路径都可用，
    不存在第二份「谁该批」的计算（本设计的核心不变式：唯一事实源）。
    """
    return leave.route_of()

class EduLeaveFlowExt(models.Model):
    """edu.leave 的字段层（S1）+ 逻辑层（S2）。

    ⚠ 导入顺序：本文件在 models/__init__.py 里**必须最后导入**
      （leave -> leave_transfer -> course_rep -> leave_flow）——
      同模块内「后导入的层在 MRO 里更靠前」，才能盖住 course_rep.py 的
      EduLeaveRepExt 层；顺序由 scripts/check_view_xpath.py **规则 7** 门禁。
    """

    _inherit = 'edu.leave'
    _description = 'Student Time Off / Leave Request'

    # ------------------------------------------------------------------
    # §3.1 状态机：在既有三态上**只加一个** pending_second（不引入 draft / closed）
    # ------------------------------------------------------------------
    # ⚠ 升级日志里会有两条 WARNING「selection=... overrides existing selection;
    #   use selection_add instead」—— 这是**刻意**的，不是缺陷：设计稿 §3.1/§6 要求
    #   把旧 code **全量列出并给出确定顺序**（state 的状态条顺序、类型下拉顺序）；
    #   若改用 selection_add，新态会被排到 refused **之后**，状态条顺序就错了。
    #   两条枚举的旧 code 与旧标签一字未动 ⇒ 与 selection_add 的「保留」语义等价。
    # 为什么覆盖在这里（而不是 leave.py）：本文件导入顺序在最后 ⇒ MRO 最前，
    # 覆盖后是全仓唯一的状态枚举；leave.py 保持只读（S1 冻结的既有层）。
    # ⚠ 既有三个 code 的标签**一字不动**（Requested/Approved/Refused 的汉化在
    #   edu_zh/i18n_extra，不重复翻译，也不在 edu_zh 之外新造翻译）；新态用中文标签，
    #   避免出现「中西混排的未翻译新词」。request 的**语义不变** ⇒ 既有
    #   filterby=request 与首页计数照旧。
    state = fields.Selection(
        [('request', 'Requested'),
         ('pending_second', '待二级审批'),
         ('approved', 'Approved'),
         ('refused', 'Refused')],
        string='Status', default='request')

    # ------------------------------------------------------------------
    # §6 请假类型（条例二）：**保留全部旧 code**，只新增三个条例类型
    # ------------------------------------------------------------------
    # ⚠ 为什么类型枚举在 S2 的文件里改：§7.2 的 proof_required（婚丧假必传证明）
    #   与 §7.3 的 lead_days_required（婚丧假提前 7 天）都要读 marriage_funeral，
    #   若枚举里没有这个 code，门户一选它就抛「Wrong value for leave_type」。
    #   保留 legal（历史值；课代表白名单与后台历史筛选都按老 code 走，仅门户下拉
    #   隐藏 —— 隐藏由 S4 做）；保留 casual（**不能改名 personal**：
    #   course_rep.py:117-126 的课代表会签白名单默认值是 ('sick','casual')，
    #   改 code 会让事假从会签白名单里**静默**消失）。
    leave_type = fields.Selection(
        [('sick', 'Sick Leave'),
         ('casual', 'Casual Leave'),
         ('marriage_funeral', '婚丧假'),
         ('winter_summer', '寒暑假'),
         ('practice_week', '实践周'),
         ('legal', 'Legal Leave'),
         ('other', 'Other')],
        string='Leave Type', default='sick')

    # ------------------------------------------------------------------
    # §2.1 / §5.3 申请人身份维度（S1 原样）
    # ------------------------------------------------------------------
    applicant_kind = fields.Selection(
        [('student', '学生'),
         ('staff', '教职人员')],
        string='申请人类型', required=True, default='student',
        help='学生单 / 教职单的分流维度（方案 A：一张表 + 一个维度）。'
             '教职 = 经 identity.py 反查 op.student 与 op.parent 皆空（§5.3）。'
             'required ⇒ DB 层 NOT NULL；§9.1 步1 已把全部历史行回填 student。')
    applicant_user_id = fields.Many2one(
        'res.users', string='申请人账号', ondelete='set null', index=True,
        help='教职单的申请人（学生单可留空，学生走 student_id）。'
             '§9.1 步2 从 student_id.user_id 尽力回填，取不到留空。')

    # ------------------------------------------------------------------
    # §3.2 / §4.2 分级审批：当前应批人（提交时快照；转交后改写）
    # ------------------------------------------------------------------
    first_approver_id = fields.Many2one(
        'res.users', string='一级审批人', index=True, ondelete='set null',
        help='**当前**一级应批人（提交时快照 = route_of() 的 first_users）。'
             '转交后改写成转入人；既有历史单据为空（显示「—」），**不回填**。'
             '⚠ 改动「班主任」字段**只影响新提交**的单据，在途单据不回溯。')
    second_approver_id = fields.Many2one(
        'res.users', string='二级审批人', index=True, ondelete='set null',
        help='**当前**二级应批人（进入 pending_second 时快照）；不需要二级时为'
             '空。二级退回一级时清空（§3.1）。')
    transfer_ids = fields.One2many(
        'edu.leave.transfer', 'leave_id', string='转交记录', copy=False,
        help='本单的转交留痕（§4.2）；同一审批级最多一行，'
             '由 edu_leave_transfer_transfer_once 唯一约束兜底。')
    route_note = fields.Char(
        string='路由说明', size=128, readonly=True, copy=False,
        help='可解释性文案，如「未设班主任，已转教务处」「该生未分班，已转教务处」'
             '（§3.3）。**只读**：由路由逻辑写入，不由人改。')

    # ------------------------------------------------------------------
    # §3.1 二级「退回一级」的留痕（设计稿只在正文点名、未进字段表 ⇒ S2 补声明）
    # ------------------------------------------------------------------
    second_sent_back_at = fields.Datetime(
        string='二级退回时间', readonly=True, copy=False,
        help='§3.1：二级认为信息不全 ⇒ pending_second 退回 request，写本字段'
             '（同时写 second_send_back_reason、清空 second_approver_id）。'
             '**不允许一级退回申请人**（本仓无 draft；申请人要改 ⇒ 撤回 + 重建）。')
    second_send_back_reason = fields.Text(
        string='二级退回原因', copy=False,
        help='§3.1：二级退回时填写的原因（与申请人的驳回原因 reject_reason 分开记）。')

    # ------------------------------------------------------------------
    # §7.2 证明材料（必传附件 + 口头证明双轨）（S1 原样）
    # ------------------------------------------------------------------
    proof_kind = fields.Selection(
        [('file', '文件证明'),
         ('oral', '口头证明'),
         ('none', '无')],
        string='证明方式', default='none',
        help='条例二·2 婚丧假 / 二·3 病假要求证明（§7.2）。'
             'file ⇒ 必须 attachment_ids 非空；oral ⇒ 必须 oral_proof_by 非空。')
    attachment_ids = fields.One2many(
        'ir.attachment', 'res_id',
        domain=[('res_model', '=', 'edu.leave')],
        string='证明材料附件',
        help='经 ir.attachment 的 res_model/res_id 反查（与 account.move / '
             'hr.applicant 同一写法），不自建关系表。')
    oral_proof_by = fields.Char(
        string='口头证明人', size=64,
        help='条例二·2/三·2 允许「家长或牧长口头证明」；此处记证明人姓名。')
    oral_proof_relation = fields.Char(
        string='与申请人关系', size=32)
    oral_proof_confirmed_by_id = fields.Many2one(
        'res.users', string='口头证明确认人', ondelete='set null',
        help='**审批人**点「通过」时若 proof_kind=oral 且本字段为空 ⇒ 写入 env.user'
             '（§7.2 的确认闭环），并写 edu.audit.log。'
             '问的是「谁认了这份口头证明」，不是「谁听过」。')
    proof_required = fields.Boolean(
        string='必须提交证明', compute='_compute_proof_required',
        help='§7.2：sick 且天数 ≥ 2 ⇒ True；marriage_funeral ⇒ True；其余 False。'
             '**compute 不 store**；为 True 时提交必须给「文件证明 + 附件」'
             '或「口头证明 + 证明人」，否则 UserError（文案引条例原文）。')

    # ------------------------------------------------------------------
    # §7.1 销假（**正交字段，不改 state**）（S1 原样）
    # ------------------------------------------------------------------
    return_confirmed_at = fields.Datetime(
        string='销假时间', readonly=True, copy=False,
        help='销假不是审批裁决，故**不做成第五个状态**（会打断既有三档筛选、'
             '首页提醒卡计数与 _leave_steps() 进度条）。')
    return_confirmed_by_id = fields.Many2one(
        'res.users', string='销假确认人', readonly=True, ondelete='set null',
        copy=False, help='班主任/教务确认销假的人。')
    return_note = fields.Text(
        string='行程及实践收获', copy=False,
        help='学生/家长销假时提交的说明（§7.1）。')
    return_required = fields.Boolean(
        string='待销假', compute='_compute_return_required',
        help='§7.1：state == "approved" and date_to < today。'
             '**compute 不 store**，每次读都实时重算。')
    return_overdue_alerted_at = fields.Datetime(
        string='销假逾期提醒时间', readonly=True, copy=False,
        help='新 cron 的幂等去重标记（照 escalated_at 的形状，§7.1）——'
             '非空即不再重复提醒，重复跑 cron 安全。⚠ 用**新** cron，'
             '不改既有 cron 39（超时升级）。')

    # ------------------------------------------------------------------
    # §7.3 提前申请期（**软提示不硬拦**）（S1 原样）
    # ------------------------------------------------------------------
    lead_days_required = fields.Integer(
        string='条例要求提前天数', compute='_compute_lead_days_required',
        help='§7.3：casual → 2；marriage_funeral → 7；其余 → 0。'
             '**compute 不 store**。')
    lead_days_actual = fields.Integer(
        string='实际提前天数', copy=False,
        help='§7.3：提交时快照 = date_from - 提交日。不足**不拦截**，'
             '只显示横幅 + 让「批了不达标单」可被审计查出。')
    lead_days_short = fields.Boolean(
        string='提前期不足', copy=False,
        help='§7.3：提交时快照；供筛选与审批人提示。')

    # ------------------------------------------------------------------
    # §7.4 事假学期配额（S1 原样）+ §7.6 外出长假软提示
    # ------------------------------------------------------------------
    casual_days_used_this_term = fields.Float(
        string='本学期事假已用天数', compute='_compute_casual_days_used_this_term',
        digits=(6, 1),
        help='§7.4：同 student_id + leave_type=casual + state ∈ (request,'
             'pending_second, approved) + date_from 落在本单所属学期区间内的**天数合计**'
             '（含头含尾，**不含本单**）。**compute 不 store**，实时算。'
             '取不到学期边界 ⇒ 0（fail-closed 到「不拦截」）。')
    over_quota = fields.Boolean(
        string='事假超学期配额', copy=False,
        help='§7.4：提交时快照 = 学期内事假累计 + 本单天数 > 5。'
             '**over_quota=True ⇒ 无论几天一律走二级**'
             '（need_second = need_second or over_quota）。'
             '取不到学期边界 ⇒ 不判超限（fail-closed 到「不拦截」）。')
    long_absence_flag = fields.Boolean(
        string='外出长假', compute='_compute_long_absence_flag',
        help='§7.6：practice_week 且天数 ≥ 7 ⇒ True（条例二·5「原则上不批准外出长假」'
             '的**软提示**标记，不拦截）。**compute 不 store**。')

    # ------------------------------------------------------------------
    # §7.5 禁止事后补假 —— 后台例外通道（S1 原样）
    # ------------------------------------------------------------------
    backfilled = fields.Boolean(
        string='教务事后补录', readonly=True, copy=False,
        help='§7.5：门户侧 date_from < 提交日 一律硬拒且**不落库**；'
             '后台「请假审批 → 新建」不受此校验（教务代录历史），'
             '但必须置本标记 + 写 audit（动作名「请假事后补录」），'
             '详情页红字「本条为教务事后补录」。')

    # ==================================================================
    # ▼▼▼ 以下为 S2 的可执行逻辑（S1 的字段块到此为止，一个字未改） ▼▼▼
    # ==================================================================

    # ------------------------------------------------------------------
    # 基础读数：天数 / 学期 / 集合
    # ------------------------------------------------------------------
    def days_of_leave(self):
        """请假天数（**含头含尾**，自然日）：9/1–9/3 = 3 天（§3.4 已裁决）。

        与既有 roles.py:1160-1162 的 (date_to - date_from).days + 1 同一算法
        （复用不重写）；**不扣**周末 / 停课日 / 法定节假日 —— 本仓没有节假日字典。
        单边缺日期或倒序 ⇒ 0（中性值 ⇒ 任何阈值判断都落到「不需要二级」）。
        """
        self.ensure_one()
        if not self.date_from or not self.date_to or self.date_to < self.date_from:
            return 0
        return (self.date_to - self.date_from).days + 1

    def _term_of(self, adate):
        """adate 落在哪个学期（op.academic.term）；取不到 ⇒ 空集。

        §7.4：取 term_start_date <= adate <= term_end_date 的那一条；多条命中时取
        term_start_date 最晚的一条（确定性，不靠插入顺序）。**取不到 ⇒ 不判超限**。
        """
        if not adate:
            return self.env['op.academic.term'].sudo().browse()
        return self.env['op.academic.term'].sudo().search(
            [('term_start_date', '<=', adate), ('term_end_date', '>=', adate)],
            order='term_start_date desc, id desc', limit=1)

    def _casual_days_used(self, term):
        """本单之外、该生在该学期内的**事假**天数合计（§7.4 的域）。

        域逐条对应设计稿：同 student_id + leave_type='casual' +
        state ∈ (request, pending_second, approved) + date_from 落在学期区间内；
        求和含头含尾；**排除本单**（over_quota 的公式要再加「本单天数」）。
        · 域里**没有** date_to 条件 —— 设计稿写的是 date_from 落在区间内；
        · active_test=False：归档（active=False）的老单**照样计入**，否则
          「归档一笔已批事假」就能静默绕过学期上限。
        """
        self.ensure_one()
        if not term or not self.student_id:
            return 0.0
        domain = [('student_id', '=', self.student_id.id),
                  ('leave_type', '=', 'casual'),
                  ('state', 'in', ('request', 'pending_second', 'approved')),
                  ('date_from', '>=', term.term_start_date),
                  ('date_from', '<=', term.term_end_date)]
        if self.id:
            domain.append(('id', '!=', self.id))
        rows = self.env['edu.leave'].sudo().with_context(
            active_test=False).search(domain)
        return float(sum(row.days_of_leave() for row in rows))

    def _second_users(self):
        """二级审批人集合：① 系统参数 uid 链 → ② 教务处组 → ③ 系统组（§3.2）。

        · 系统参数 edu_portal.leave_principal_user_ids（逗号分隔 uid，可选）用于
          **单点指定教务长**；给了有效 uid 就只认它（不再并入组）；
        · 不写死 backoffice@local：写死 login 在生产换人/改名时会**静默失效**，
          且用户原话「教务长 = 教务人员」⇒ **组比账号更接近语义**；
        · 停用账号一律剔除（不能登录 ⇒ 不可能是可用审批人）。
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(
            PARAM_PRINCIPAL_UIDS, '') or ''
        uids = []
        for token in str(raw).replace('，', ',').split(','):
            token = token.strip()
            if token.isdigit():
                uids.append(int(token))
        if uids:
            picked = active_users(self.env['res.users'].sudo().browse(uids))
            if picked:
                return picked
        office = active_users(group_users(self.env, GROUP_BACKOFFICE))
        return office or active_users(group_users(self.env, GROUP_SYSTEM))

    @api.model
    def _primary_user(self, users):
        """从候选集合里取一个**确定性**的「主」账号（m2o 快照只能存一个）。

        设计稿把 first_users 定义成**集合**，而 first_approver_id 是 m2o（只能一个）
        —— 这是设计稿没写的落地细节，规则如下（可解释、不依赖插入顺序）：
          ① 只挑**在用**账号（全停用 ⇒ 退回到全集合：宁可留一个登不上来的人，
             也不把「有审批人」静默变成「没人」）；
          ② 教务处组优先（无班主任时的兜底集合里，教务处才是语义上的负责人，
             避免系统组里的模板/机器账号被选成「一级审批人」）；
          ③ 同优先级内 id 最小（最老、最稳定）。
        注意：snapshot 只存**一个**账号 ≠ 只有他能批 —— 可批集合由
        can_user_act() 按「当前级应批人 + 特权例外」判定，教务处组其他人照样能批。
        """
        if not users:
            return self.env['res.users'].sudo().browse()
        users = users.sudo()
        pool = active_users(users) or users
        office = group_users(self.env, GROUP_BACKOFFICE)
        preferred = pool.filtered(lambda u: u in office)
        return (preferred or pool).sorted(lambda u: u.id)[:1]

    # ------------------------------------------------------------------
    # §3.2 审批人解析（**唯一的「谁该批」计算点**）
    # ------------------------------------------------------------------
    def _student_batch(self):
        """「取哪个班」的**唯一口径**（§3.2 表下注释）。

        取该生 op.student.course 中 batch_id 非空、且 batch.end_date **最晚**的
        那一条（与 course_rep.py:181-203 的 _batch_term_layers「取最晚不早退」
        同一取舍：一个学生属多个班时不早退）。end_date 全为空时退化为 id 最小的
        一条（仍要有确定性）。**禁止在别处再写一份取班逻辑。**
        """
        self.ensure_one()
        Batch = self.env['op.batch'].sudo()
        if self.applicant_kind != 'student' or not self.student_id:
            return Batch.browse()
        rows = self.env['op.student.course'].sudo().search(
            [('student_id', '=', self.student_id.id),
             ('batch_id', '!=', False)]).filtered(lambda sc: sc.batch_id)
        if not rows:
            return Batch.browse()
        dated = rows.filtered(lambda sc: sc.batch_id.end_date)
        if dated:
            return max(dated, key=lambda sc: (sc.batch_id.end_date,
                                             sc.batch_id.id)).batch_id
        return min(rows, key=lambda sc: sc.batch_id.id).batch_id

    def _homeroom_teacher(self):
        """一级审批人（学生单）：(班主任账号, fallback_reason)。

        §3.3 三行判定表的**唯一实现**：
          · 未分班 ⇒ 空集 + 「该生未分班，已转教务处」；
          · 有班无班主任 ⇒ 空集 + 「未设班主任，已转教务处」；
          · 有班主任且账号**在用** ⇒ 该账号 + None。
        ⚠ 班主任账号被停用（op.faculty 离职的常见操作是 archive）时按「未设班主任」
          处理并走教务处兜底 —— 否则单据会挂在一个永远登不上来的人身上
          （比 §3.3 最后一行更糟：那一行至少要求「可解释」）。
        """
        self.ensure_one()
        batch = self._student_batch()
        if not batch:
            return self.env['res.users'].sudo().browse(), FALLBACK_NO_BATCH
        teacher = batch.sudo().homeroom_teacher_id
        if teacher and teacher.active:
            return teacher.sudo(), None
        return self.env['res.users'].sudo().browse(), FALLBACK_NO_HOMEROOM

    def _need_second(self):
        """是否需要二级（§3.2 判定表）：days > 阈值 **或** over_quota **或** 开关强制。

        over_quota 读的是**提交时快照**（store 字段），不是实时值 —— 与设计稿
        「over_quota 是 store 快照」一致：学期配额在提交那一刻锁定，事后改日期不回溯。
        """
        self.ensure_one()
        if always_two_stage(self.env):
            return True
        return (self.days_of_leave() > second_approval_days(self.env)
                or bool(self.over_quota))

    def route_of(self):
        """**唯一的「谁该批」计算点**（§3.2 学生单判定表 + §5.4 教职单链）。

        :return: RouteResult(first_users, second_users, need_second, fallback_reason)

        学生单：班上有班主任 ⇒ 该账号；无班主任/未分班 ⇒ 教务处组 ∪ 系统组
                （并写出 §3.3 的逐字 route_note）。
        教职单：一级 = 教务处组（教职没有班主任）；二级 = **系统组**
                （§5.4：若两级都落教务处，同一人能连批两次 ⇒ 二级形同虚设；
                 本仓唯一可用的「更高一级」就是系统组 = 校长/管理员）。
        集合可为空集 ⇒ 单据照样可建可读，只显示「无可用审批人，请先配置教务处」；
        **绝不** fail-open 成「任何人都能批」。
        """
        self.ensure_one()
        empty = self.env['res.users'].sudo().browse()
        need_second = self._need_second()

        if self.applicant_kind == 'staff':
            first = active_users(group_users(self.env, GROUP_BACKOFFICE))
            fallback = None if first else FALLBACK_NO_APPROVER
            second = (active_users(group_users(self.env, GROUP_SYSTEM))
                      if need_second else empty)
            return RouteResult(first, second, need_second, fallback)

        first, fallback = self._homeroom_teacher()
        if not first:
            first = active_users(
                group_users(self.env, GROUP_BACKOFFICE)
                | group_users(self.env, GROUP_SYSTEM))
            if not first:
                fallback = FALLBACK_NO_APPROVER
        second = self._second_users() if need_second else empty
        return RouteResult(first, second, need_second, fallback)

    def current_approver_users(self):
        """当前这一级的**应批人集合**（S3 的待办/通知范围用；终态 ⇒ 空集）。"""
        self.ensure_one()
        stage = self._current_stage()
        if not stage:
            return self.env['res.users'].sudo().browse()
        who = self._stage_owner(stage)
        return who.sudo() if who else self.env['res.users'].sudo().browse()

    def current_approver_label(self):
        """当前应批人的**单据显示文案**（§3.3 的「单据显示」列，S3/S4 可直接用）。

        例：「张三（班主任）」「教务处（未设班主任，已转教务处）」
            「无可用审批人，请先配置教务处」。
        """
        self.ensure_one()
        if not self._current_stage():
            return self.approver_label() if self.approver_id else '—'
        who = self._stage_owner(self._current_stage())
        if not who:
            who = self._primary_user(self.route_of().first_users)
        if not who:
            return FALLBACK_NO_APPROVER
        if self.route_note:
            return '%s（%s）' % (who.name or '', self.route_note)
        return who.name or ''

    # ------------------------------------------------------------------
    # §4.3(2) 权限判定（唯一事实源）+ §8.1
    # ------------------------------------------------------------------
    @api.model
    def _is_privileged(self, user=None):
        """教务处组 or 系统组 = 最高权限（code-map §6 第 3 条，**本次不破**）。"""
        user = user or self.env.user
        return (user_in_group(user, GROUP_BACKOFFICE)
                or user_in_group(user, GROUP_SYSTEM))

    def _current_stage(self):
        """当前审批级：request ⇒ 'first'，pending_second ⇒ 'second'，终态 ⇒ None。"""
        self.ensure_one()
        if self.state == 'request':
            return 'first'
        if self.state == 'pending_second':
            return 'second'
        return None

    def _stage_owner(self, stage):
        """该级当前应批人（快照）记录集；无 ⇒ 空集。"""
        self.ensure_one()
        return (self.first_approver_id if stage == 'first'
                else self.second_approver_id)

    def _transferred_away(self, stage, user):
        """该级是否已把审批权转交给 user 之外的人（§4.3(2) 的显式判定）。

        正常路径下 first/second_approver_id 已被转交改写成转入人，本判定是
        **冗余的第二道锁**：即使有人手工把快照改回，原审批人也批不了。
        """
        self.ensure_one()
        if not user:
            return False
        row = self.transfer_ids.filtered(
            lambda t: t.stage == stage and t.from_user_id.id == user.id)
        return bool(row) and self._stage_owner(stage).id != user.id

    def can_user_act(self, user=None):
        """当前应批人判定（S3 的门户守卫**唯一**调用点）。

        口径（§4.3(2) 的判据替换 + §8.1 的权限矩阵）：
          ① 教务处组 / 系统组 ⇒ **恒可批**（既有铁律；也是 §3.3「无可用审批人」
             兜底能工作的前提）。这一条**不看** state，保持既有后台行为一字不变
             （既有 /leave/set_state 允许特权账号改任何单的状态）。
          ② 其余人：只有「本单当前这一级的 first_approver_id / second_approver_id
             **就是这个账号**」才可批 —— 判据是**快照**，**不是**「是不是班主任」。
             转交执行时快照已改写成转入人 ⇒ 原审批人到这里必然 False（§4.3(2)）。
          ③ 终态（approved/refused）没有「当前级」⇒ 非特权账号一律 False。
        """
        self.ensure_one()
        user = (user or self.env.user).sudo()
        if self._is_privileged(user):
            return True
        stage = self._current_stage()
        if not stage:
            return False
        owner = self._stage_owner(stage)
        if not owner or owner.id != user.id:
            return False
        return not self._transferred_away(stage, user)

    def can_user_transfer(self, user=None):
        """能否转交（§4.4 的守卫口径，比 can_user_act **更严**：无特权例外）。

        §8.1 的转交判据逐字：user ∈ {first_approver_id, second_approver_id}
        且该级未转过。教务处/系统组可以**批**，但转交必须由「本单当前这一级的
        应批人本人」发起 —— 否则会出现「谁都能把别人的待办转走」。
        """
        self.ensure_one()
        user = (user or self.env.user).sudo()
        stage = self._current_stage()
        if not stage:
            return False
        owner = self._stage_owner(stage)
        if not owner or owner.id != user.id:
            return False
        return not self.env['edu.leave.transfer'].sudo().search_count(
            [('leave_id', '=', self.id), ('stage', '=', stage)])

    # ------------------------------------------------------------------
    # §7.x compute（S1 的占位方法体在此被真实现替换）
    # ------------------------------------------------------------------
    @api.depends('state', 'date_to')
    def _compute_return_required(self):
        """§7.1 销假：state == 'approved' **且** date_to < today。"""
        today = fields.Date.today()
        for leave in self:
            leave.return_required = bool(
                leave.state == 'approved' and leave.date_to
                and leave.date_to < today)

    @api.depends('leave_type')
    def _compute_lead_days_required(self):
        """§7.3 提前申请期：casual → 2；marriage_funeral → 7；其余 → 0。"""
        for leave in self:
            leave.lead_days_required = LEAD_DAYS_BY_TYPE.get(
                leave.leave_type, 0)

    @api.depends('leave_type', 'date_from', 'date_to')
    def _compute_proof_required(self):
        """§7.2：sick 且天数 ≥ 2 ⇒ True；marriage_funeral ⇒ True。"""
        for leave in self:
            leave.proof_required = leave._proof_required_for(
                leave.leave_type, leave.days_of_leave())

    @api.depends('leave_type', 'date_from', 'date_to')
    def _compute_long_absence_flag(self):
        """§7.6：practice_week 且天数 ≥ 7 ⇒ True（软提示，不拦截）。"""
        for leave in self:
            leave.long_absence_flag = bool(
                leave.leave_type == 'practice_week'
                and leave.days_of_leave() >= 7)

    @api.depends('student_id', 'date_from', 'leave_type', 'state')
    def _compute_casual_days_used_this_term(self):
        """§7.4：本学期事假已用天数（实时算，**不含本单**）。"""
        Term = self.env['op.academic.term'].sudo()
        for leave in self:
            term = (leave._term_of(leave.date_from)
                    if (leave.student_id and leave.date_from)
                    else Term.browse())
            leave.casual_days_used_this_term = leave._casual_days_used(term)

    @api.model
    def _proof_required_for(self, leave_type, days):
        """证明要求（§7.2 的触发条件，create 校验与 compute 共用**一处**）。"""
        if leave_type == 'marriage_funeral':
            return True
        return leave_type == 'sick' and days >= 2

    # ------------------------------------------------------------------
    # §7.5 / §7.3 / §7.4 / §7.2 提交时校验与快照
    # ------------------------------------------------------------------
    def _portal_submission(self):
        """本次 create 是否算「门户自助提交」（§7.5 的硬拒口径）。

        判据（任一成立即门户）：
          ① context 显式置 CTX_PORTAL（S3/S4 在门户路由里写上）；
          ② 创建者**不是特权账号**（既不在教务处组、也不在系统组）。
             本仓三条门户建单路径（batch3.py 的 /my/time_off/save、roles.py 的
             家长路由、将来的教职单分流）都以门户身份运行，因此**不改控制器**
             也能被硬拒；而教务处/系统组 = §7.5 明写的「后台例外通道」。
        ⚠ sudo 不改变 env.user（core orm/environments.py:208：env.user 取的是
          self.uid）⇒ 门户路由里的 .sudo().create() 照样按**真实账号**判角色。
        """
        if self.env.context.get(CTX_PORTAL):
            return True
        return not self._is_privileged(self.env.user)

    def _prepare_create_vals(self, vals):
        """建单前处理（§5.3 身份补全 + §7.5 补假 + §7.2 证明材料）。"""
        vals = dict(vals)
        # §5.3：教职单的申请人 = 当前账号（门户分流由 S3 传 applicant_kind）
        if vals.get('applicant_kind') == 'staff' \
                and not vals.get('applicant_user_id'):
            vals['applicant_user_id'] = self.env.user.id
        # §7.5 禁止事后补假：date_from < 提交日
        date_from = fields.Date.to_date(vals.get('date_from')) \
            if vals.get('date_from') else None
        if date_from and date_from < fields.Date.today():
            if self._portal_submission():
                raise UserError(MSG_BACKFILL_DENIED)
            vals['backfilled'] = True
        # §7.2 证明材料（文案引条例原文）
        leave_type = (vals.get('leave_type')
                      or field_default(self, 'leave_type', 'sick'))
        date_to = fields.Date.to_date(vals.get('date_to')) \
            if vals.get('date_to') else date_from
        days = ((date_to - date_from).days + 1) \
            if (date_from and date_to and date_to >= date_from) else 0
        if self._proof_required_for(leave_type, days):
            kind = (vals.get('proof_kind')
                    or field_default(self, 'proof_kind', 'none'))
            if kind == 'none':
                raise UserError(MSG_PROOF_SICK if leave_type == 'sick'
                                else MSG_PROOF_MARRIAGE)
            if kind == 'oral' and not (vals.get('oral_proof_by') or '').strip():
                raise UserError(MSG_PROOF_ORAL_BY)
            # kind == 'file'：附件是 o2m 到 ir.attachment 的（建单后才有 res_id），
            # 这里**无法**判定「文件是否真传了」 ⇒ 交给 _check_proof_attachments()
            # 在上传步骤之后调用（不在这里假装判过）。
        return vals

    def _check_proof_attachments(self):
        """§7.2 的附件分支：proof_kind='file' 时必须已有附件。

        为什么不在 create 里判：附件是 o2m（ir.attachment.res_id 指向**已存在**的
        单据），建单那一刻必然还是空的 ⇒ 在 create 里判「文件证明」会 100% 误杀。
        S3/S4 在上传完成后调用本方法（文件真的没传 ⇒ UserError，不放行）。
        """
        for leave in self:
            if leave.proof_required and leave.proof_kind == 'file' \
                    and not leave.attachment_ids:
                raise UserError(
                    '证明方式选了「文件证明」，但没有上传任何附件；'
                    '请上传证明文件，或改为「口头证明」并填写证明人。')

    @api.model_create_multi
    def create(self, vals_list):
        """建单 = 提交（本模型**没有** draft 态，§3.1）⇒ 校验 + 快照都在这里。

        §7.5 门户一律**硬拒且不落库**（校验在 super().create() 之前 ⇒ 抛错时
        一条数据都不会写进去）；后台例外通道置 backfilled=True 并留审计。
        """
        records = super().create(
            [self._prepare_create_vals(vals) for vals in vals_list])
        records._snapshot_on_submit()
        records._audit_backfill()
        return records

    def _snapshot_on_submit(self):
        """提交时快照（§3.2/§7.3/§7.4）：first_approver_id / route_note /
        lead_days_* / over_quota。

        ⚠ **不回溯**：在途单据的审批人是提交那一刻的班级配置快照；之后改「班主任」
          字段只影响**新提交**的单据（§3.3「老师到位后只填数据即生效」的口径）。
        · 只对 state='request' 的单据做（历史/导入的终态行不产生应批人）；
        · over_quota 必须先落库再算 route_of()：route_of() 读的是它的**存值**。
        """
        today = fields.Date.today()
        for leave in self:
            if leave.state != 'request' or not leave.date_from:
                continue
            lead_required = LEAD_DAYS_BY_TYPE.get(leave.leave_type, 0)
            lead_actual = (leave.date_from - today).days
            leave.sudo().write({
                'lead_days_actual': lead_actual,
                'lead_days_short': bool(
                    lead_required and lead_actual < lead_required),
                'over_quota': leave._over_quota_now(),
            })
            result = leave.route_of()
            leave.sudo().write({
                'first_approver_id':
                    self._primary_user(result.first_users).id or False,
                'route_note': (result.fallback_reason or '')[:128],
            })

    def _over_quota_now(self):
        """§7.4 超限判定（提交时快照的取值口径）。

        over_quota = 本学期事假累计 + 本单天数 > 5；取不到学期边界 ⇒ False
        （fail-closed 到「不拦截」：配额是限制性规则，取不到边界就无权拦人）。
        """
        self.ensure_one()
        if self.leave_type != 'casual' or not self.student_id \
                or not self.date_from:
            return False
        term = self._term_of(self.date_from)
        if not term:
            return False
        return (self._casual_days_used(term)
                + self.days_of_leave()) > CASUAL_TERM_QUOTA_DAYS

    def _audit_backfill(self):
        """§7.5 后台例外通道留痕：动作名「请假事后补录」。"""
        for leave in self.filtered('backfilled'):
            self.env['edu.audit.log'].sudo()._log(
                AUDIT_BACKFILL, 'edu.leave', leave.id, leave.name or '',
                '教务事后补录：起始日 %s（早于提交日），已标记 backfilled'
                % (leave.date_from or '—'))

    # ------------------------------------------------------------------
    # §3.1 状态机动作（S3 调用；通知/留痕**都在动作内部**，S3 不要重复）
    # ------------------------------------------------------------------
    def _approver_write(self, vals):
        """写状态 + 补审批留痕（approver_id / approver_kind / approved_at）。

        留痕走既有 _approver_vals()（course_rep.py），保证与既有 4 处写入点
        **同一口径** —— 否则同一张表上会出现「有的单显示审批人、有的不显示」。
        """
        self.ensure_one()
        out = dict(vals)
        out.update(self._approver_vals())
        self.write(out)

    def _confirm_oral_proof(self):
        """§7.2 口头证明的确认闭环：审批人点「通过」⇒ 落 env.user + 审计。

        条例把「家长/牧长口头证明」写成**合法凭证** ⇒ 它必须能被审批人确认、
        能被审计查出「谁认了这份口头证明」；故不是普通备注字段。
        """
        self.ensure_one()
        if self.proof_kind == 'oral' and not self.oral_proof_confirmed_by_id:
            self.sudo().write(
                {'oral_proof_confirmed_by_id': self.env.user.id})
            self.env['edu.audit.log'].sudo()._log(
                AUDIT_APPROVE, 'edu.leave', self.id, self.name or '',
                '确认口头证明：证明人 %s（%s）'
                % (self.oral_proof_by or '—', self.oral_proof_relation or '—'))

    def _check_actor(self, action_label):
        """动作级守卫：调用者必须有权处置**当前这一级**（can_user_act 是唯一判据）。

        为什么控制器已经判过、动作里还要再判一次：模型层是唯一事实源 ——
        后台按钮 / 脚本 / cron / 任何调用方都必须受同一条规则约束。
        尤其「转交后原审批人不能再批」（§4.3(2)）：只有在这里判才不会因为某个
        入口忘了判而漏掉（控制器守卫是 UX 前置，不是安全边界）。
        特权账号（教务处/系统组）由 can_user_act 放行 —— 既有铁律不变。
        """
        self.ensure_one()
        if not self.can_user_act(self.env.user):
            raise UserError(
                '你无权处置本单当前审批级（%s）。若你曾把本级转交出去，'
                '则原审批人不能再批（教务处/管理员仍可批）。' % action_label)
        return True

    def action_first_approve(self):
        """一级通过（§3.1）：request → approved（不需二级）/ pending_second（需要二级）。

        需要二级时把 second_approver_id 落成**进入该级那一刻**的快照
        （§4.2：二级应批人在进入 pending_second 时快照）。
        二级集合为空的极端情况：state 照旧进 pending_second（流程不静默跳级），
        route_note 保持原值，单据显示「无可用审批人」——教务处/系统组恒可批兜底。
        """
        self.ensure_one()
        if self.state != 'request':
            raise UserError('本单当前不在「待一级审批」状态，无法执行一级通过。')
        self._check_actor('一级通过')
        self._confirm_oral_proof()
        if self._need_second():
            second = self._primary_user(self.route_of().second_users)
            self._approver_write({
                'state': 'pending_second',
                'second_approver_id': second.id or False,
            })
            self.env['edu.audit.log'].sudo()._log(
                AUDIT_APPROVE, 'edu.leave', self.id, self.name or '',
                '一级通过 -> 待二级审批（天数 %d，超配额 %s；二级应批人 %s）'
                % (self.days_of_leave(), '是' if self.over_quota else '否',
                   second.name or '无可用审批人'))
        else:
            self._approver_write({'state': 'approved'})
            self._notify_applicant('approved')
            self.env['edu.audit.log'].sudo()._log(
                AUDIT_APPROVE, 'edu.leave', self.id, self.name or '',
                '一级通过 -> 已通过（天数 %d，一级即终）' % self.days_of_leave())
        return True

    def action_second_approve(self):
        """二级通过（§3.1）：pending_second → approved（终态）。"""
        self.ensure_one()
        if self.state != 'pending_second':
            raise UserError('本单当前不在「待二级审批」状态，无法执行二级通过。')
        self._check_actor('二级通过')
        self._confirm_oral_proof()
        self._approver_write({'state': 'approved'})
        self._notify_applicant('approved')
        self.env['edu.audit.log'].sudo()._log(
            AUDIT_APPROVE, 'edu.leave', self.id, self.name or '',
            '二级通过 -> 已通过')
        return True

    def action_refuse(self, reason=''):
        """驳回（§3.1）：request / pending_second → refused（终态）。

        驳回原因**可省**：列表页的快捷驳回按钮历史上就不带原因（reason 为空时
        不覆盖既有的 reject_reason）。后台的「必须填原因」口径在 leave.py 的
        action_reject 里，本动作不改变它。
        """
        self.ensure_one()
        if self.state not in ('request', 'pending_second'):
            raise UserError('本单已终审，不能再驳回。')
        self._check_actor('驳回')
        reason = (reason or '').strip()
        vals = {'state': 'refused'}
        if reason:
            vals['reject_reason'] = reason[:500]
        self._approver_write(vals)
        self._notify_applicant('refused')
        self.env['edu.audit.log'].sudo()._log(
            AUDIT_APPROVE, 'edu.leave', self.id, self.name or '',
            '驳回 -> 已驳回（%s；原因：%s）'
            % (STAGE_LABEL.get(self._current_stage(), '—'), reason or '未填'))
        return True

    def action_send_back(self, reason=''):
        """二级退回一级（§3.1）：pending_second → request，一级重批。

        写 second_sent_back_at + second_send_back_reason，**清空 second_approver_id**
        （回到 request 后二级不再是当前级；再次一级通过时会重新快照）。
        ⚠ **不允许一级退回申请人**（本仓无 draft；申请人要改 ⇒ 撤回 + 重建）。
        ⚠ **不发通知**（队长裁决 2026-09-25：退回后该单会重新出现在一级审批人的
          request 队列里，可见性已足够，不为它加代码）。
        """
        self.ensure_one()
        if self.state != 'pending_second':
            raise UserError('只有「待二级审批」的单据可以退回一级。')
        reason = (reason or '').strip()
        self.sudo().write({
            'state': 'request',
            'second_sent_back_at': fields.Datetime.now(),
            'second_send_back_reason': reason or False,
            'second_approver_id': False,
        })
        self.env['edu.audit.log'].sudo()._log(
            AUDIT_APPROVE, 'edu.leave', self.id, self.name or '',
            '二级退回一级 -> 待一级审批（原因：%s）' % (reason or '未填'))
        return True

    # ------------------------------------------------------------------
    # §4 转交审批
    # ------------------------------------------------------------------
    def _applicant_users(self):
        """申请人本人的**账号集合**（过滤转交候选用）。

        判据（§4.3(1)）：**学生档案 id / 申请人 uid** —— 不用 res.partner
        （一个学生可能有多个登录账号，见 identity.py:64-65；按 partner 比会漏）。
        档案 -> 账号走全仓唯一口径 users_of_profile（双向并集，只加不减）。
        """
        self.ensure_one()
        users = self.env['res.users'].sudo().browse()
        if self.student_id:
            users |= users_of_profile(self.student_id.sudo())
        if self.applicant_user_id:
            users |= self.applicant_user_id.sudo()
        return users

    def _homeroom_pool(self):
        """全部「班主任」账号（op.batch.homeroom_teacher_id 非空的并集，§4.3(1)）。"""
        batches = self.env['op.batch'].sudo().search(
            [('homeroom_teacher_id', '!=', False)])
        return batches.mapped('homeroom_teacher_id')

    def transfer_candidates(self, stage='first'):
        """转交候选人（§4.3(1) 的候选范围 + 三种必过滤）。

        转哪一级 | 候选范围
        first 一级 | ① 其他班的班主任账号（op.batch.homeroom_teacher_id 非空的并集）
                   |    ∪ ② **教务处组**
        second 二级 | 教务处组 ∪ 系统组（= 二级可批集合本身）

        ⚠ **一级候选必须包含教务处组**：本仓今天 0 个班主任，若写死「一级只能转给
          一级」，该功能当天**完全不可用**；而「没有班主任 ⇒ 直接落教务处」已由用户
          裁决 ⇒ 教务处本来就是合法的一级审批人，转给它是**同层兜底，不是越权**。

        必须过滤掉：① 自己（调用者 / 该级当前应批人，§4.4 的 to_user != self）；
        ② 申请人本人（判据见 _applicant_users）；③ 「非法」= 停用账号、不在候选集合内。
        """
        self.ensure_one()
        if stage == 'second':
            pool = (group_users(self.env, GROUP_BACKOFFICE)
                    | group_users(self.env, GROUP_SYSTEM))
        else:
            pool = (self._homeroom_pool()
                    | group_users(self.env, GROUP_BACKOFFICE))
        excluded = (self._applicant_users()
                    | self._stage_owner(stage)
                    | self.env.user.sudo())
        return active_users(pool - excluded)

    def action_transfer(self, to_user, reason):
        """转交审批（§4.3 四条规则，S3 的 /leave/transfer 调它）—— **留痕四层全做**。

        ① 同角色互转：to_user 必须在 transfer_candidates(当前级) 内；
        ② 转交后原审批人不能再批：快照改写成 to_user（can_user_act 随之 False），
           并且 _transferred_away() 留了第二道锁；
        ③ 只能转 1 次：本方法先 search_count 预检并给**逐字提示**，
           数据库层由 edu_leave_transfer 的 UNIQUE(leave_id, stage) 兜底
           （并发双转由第二笔撞约束整事务回滚，不需要乐观锁）；
        ④ 留痕四层：transfer 行 / edu.audit.log「请假审批转交」/ 详情块（S4）/
           三方 edu.message（事件 key leave_transferred）。
           **队长裁决（2026-09-25）：四层全部归模型层** —— 模型是唯一事实源，
           后台按钮 / 脚本 / cron / 任何调用方都能自动拿到留痕；放控制器层一定会漏。

        :param to_user: res.users（转入人）
        :param reason: 转交原因（留痕三要素之一，**必填**）
        :return: 新建的 edu.leave.transfer 记录
        """
        self.ensure_one()
        stage = self._current_stage()
        if not stage:
            raise UserError('单据已终审（已通过/已驳回），不能再转交。')
        actor = self.env.user.sudo()
        owner = self._stage_owner(stage)
        if not owner or owner.id != actor.id:
            raise UserError(
                '只有本单当前%s审批人（%s）可以把本级转交出去。'
                % (STAGE_LABEL[stage], owner.name or '未指定'))
        reason = (reason or '').strip()
        if not reason:
            raise UserError(
                '转交必须填写原因（留痕三要素：谁转给谁 · 何时 · 为什么）。')
        to_user = to_user.sudo() if to_user else None
        if not to_user or not to_user.id:
            raise UserError('请选择转交对象。')
        if to_user.id == actor.id:
            raise UserError('不能转交给自己。')
        if to_user.id in self._applicant_users().ids:
            raise UserError('不能转交给申请人本人。')
        if to_user.id not in self.transfer_candidates(stage).ids:
            raise UserError(
                '「%s」不在本单%s级候选审批人内 —— 只能转交给同角色的人'
                '（一级：其他班班主任 ∪ 教务处；二级：教务处 ∪ 系统组）。'
                % (to_user.name or '', STAGE_LABEL[stage]))
        if self.env['edu.leave.transfer'].sudo().search_count(
                [('leave_id', '=', self.id), ('stage', '=', stage)]):
            raise UserError(MSG_TRANSFER_ONCE)

        row = self.env['edu.leave.transfer'].sudo().create({
            'leave_id': self.id,
            'stage': stage,
            'from_user_id': actor.id,
            'to_user_id': to_user.id,
            'reason': reason,
        })
        # 留痕② + 规则②：把「当前这一级的应批人」改写成转入人。
        self.sudo().write({
            'first_approver_id' if stage == 'first'
            else 'second_approver_id': to_user.id,
        })
        self.env['edu.audit.log'].sudo()._log(
            AUDIT_TRANSFER, 'edu.leave', self.id, self.name or '',
            '%s：%s -> %s；原因：%s'
            % (STAGE_LABEL[stage], actor.name or '', to_user.name or '', reason))
        self._notify_transfer(actor, to_user, stage, reason)
        return row

    def transfer(self, to_user, reason):
        """设计稿 §4.3/§10 里的名字 transfer() —— 与 action_transfer 同一实现。

        （队长清单用 action_transfer()，设计稿用 transfer()；两个名字都提供，
          避免两侧联调时因为一个名字而失败。别名是薄壳，不是第二份逻辑。）
        """
        return self.action_transfer(to_user, reason)

    def _notify_transfer(self, from_user, to_user, stage, reason):
        """留痕④：三方通知（转出人确认 / 转入人新待办 / 申请人知会）。

        失败只告警不阻断（沿用 _notify_applicant 的错误处理风格）。
        · 转出人那句**必须**写明「此后你不能再批这一级，教务处/管理员仍可批」
          （§4.3(2) 要求把这句话原样呈现，避免扯皮）。
        """
        self.ensure_one()
        base = ('【请假转交】单据 %s（%s ~ %s）的%s审批：%s 转交给 %s。原因：%s。'
                % (self.name or '—', self.date_from or '—', self.date_to or '—',
                   STAGE_LABEL[stage], from_user.name or '', to_user.name or '',
                   reason))
        targets = [(from_user,
                    '你已把该单%s审批转交出去，此后你不能再批这一级'
                    '（教务处/管理员仍可批）。%s'
                    % (STAGE_LABEL[stage], base)),
                   (to_user,
                    '该单的%s审批已转交给你，请到「请假审批」处理。%s'
                    % (STAGE_LABEL[stage], base))]
        applicant = self._applicant_users()[:1]
        if applicant:
            targets.append(
                (applicant, '你申请的单据%s审批人已变更，特此知会。%s'
                 % (STAGE_LABEL[stage], base)))
        for user, body in targets:
            if not user or (user.id == from_user.id and user == to_user):
                continue
            try:
                self.env['edu.message'].sudo()._notify_event(
                    EVENT_TRANSFER, user, body, sender_uid=self.env.uid)
            except Exception:
                _logger.warning('leave transfer notify failed uid=%s',
                                user.id, exc_info=True)

    # ------------------------------------------------------------------
    # §7.1 销假
    # ------------------------------------------------------------------
    def action_confirm_return(self, note=''):
        """销假（§7.1）：**正交字段，不改 state**；一个入口两种角色。

        · 申请人（学生/家长）调用 ⇒ 写 return_note（「行程及实践收获」），
          等待确认；单据必须**已通过且已到期**（return_required）；
        · 审批人（本单 first/second 应批人 或 教务处/系统组）调用 ⇒ 二次确认，
          写 return_confirmed_at + return_confirmed_by_id。
        :return: True = 已完成「确认」；False = 只提交了销假说明（待确认）
        """
        self.ensure_one()
        if self.state != 'approved':
            raise UserError('只有「已通过」的单据可以销假。')
        actor = self.env.user.sudo()
        note = (note or '').strip()
        is_approver = (self._is_privileged(actor)
                       or actor.id in self._stage_owner('first').ids
                       or actor.id in self._stage_owner('second').ids)
        vals = {}
        if note:
            vals['return_note'] = note[:2000]
        if is_approver:
            vals['return_confirmed_at'] = fields.Datetime.now()
            vals['return_confirmed_by_id'] = actor.id
        else:
            if not self.return_required:
                raise UserError('本单尚未到期（或未通过），现在还不能销假。')
            if not note and not self.return_note:
                raise UserError('请填写「行程及实践收获」后再提交销假。')
        self.sudo().write(vals)
        self.env['edu.audit.log'].sudo()._log(
            AUDIT_RETURN if vals.get('return_confirmed_at') else AUDIT_RETURN_APPLY,
            'edu.leave', self.id, self.name or '',
            ('确认销假（%s）' % (actor.name or ''))
            if vals.get('return_confirmed_at')
            else ('提交销假说明：%s' % (note[:80] or '—')))
        return bool(vals.get('return_confirmed_at'))

    @api.model
    def _cron_return_overdue(self):
        """销假逾期提醒（§7.1 的**新 cron** 入口，幂等；不动 cron 39）。

        扫：已通过 + 已到期未销假 + 尚未提醒过 -> 通知教务处/班主任/系统组，
        写 return_overdue_alerted_at。**重复跑安全**：非空即不再提醒。
        （return_required 是非 store compute ⇒ 这里按等价域直接搜，
          不假装能搜 compute 字段。）
        """
        today = fields.Date.today()
        pending = self.sudo().search([
            ('state', '=', 'approved'),
            ('date_to', '<', today),
            ('return_confirmed_at', '=', False),
            ('return_overdue_alerted_at', '=', False),
        ])
        if not pending:
            return 0
        office = active_users(
            group_users(self.env, GROUP_BACKOFFICE)
            | group_users(self.env, GROUP_SYSTEM))
        for rec in pending:
            targets = office | rec.current_approver_users()
            if rec.applicant_kind == 'student' and rec.student_id:
                batch = rec._student_batch()
                teacher = batch.sudo().homeroom_teacher_id if batch else None
                if teacher and teacher.active:
                    targets |= teacher.sudo()
            body = ('【销假提醒】请假申请 %s（%s，%s ~ %s）已到期但尚未销假，'
                    '请提醒学生提交「行程及实践收获」并确认销假。'
                    % (rec.name or '—', rec.student_id.name or '—',
                       rec.date_from or '—', rec.date_to or '—'))
            for user in targets:
                try:
                    self.env['edu.message'].sudo()._notify_event(
                        EVENT_RETURN_OVERDUE, user, body,
                        sender_uid=self.env.uid)
                except Exception:
                    _logger.warning('return overdue notify failed uid=%s',
                                    user.id, exc_info=True)
        pending.write({'return_overdue_alerted_at': fields.Datetime.now()})
        return len(pending)

    # ------------------------------------------------------------------
    # 通知：申请人（覆盖 leave.py 同名方法，**只补教职单收件人**）
    # ------------------------------------------------------------------
    def _notify_applicant(self, new_state):
        """审批结果通知申请人。

        学生单原样走 leave.py 的实现（收件人 = op.student.user_id；
        event key leave_result）；教职单没有 student_id ⇒ 父实现会静默 0 收件人，
        这里补上 applicant_user_id。失败只告警，不回滚审批事务。
        """
        super()._notify_applicant(new_state)
        if self.applicant_kind != 'staff' or self.student_id:
            return
        label = self._NOTIFY_LABEL.get(new_state)
        user = (self.applicant_user_id or self.create_uid).sudo()
        if not label or not user or user.id == self.env.uid:
            return
        body = '【审批通知】您的请假申请 %s（%s ~ %s）%s。' % (
            self.name or '—',
            self.date_from.strftime('%Y/%m/%d') if self.date_from else '—',
            self.date_to.strftime('%Y/%m/%d') if self.date_to else '—', label)
        if new_state == 'refused' and self.reject_reason:
            body += '\n驳回原因：%s' % self.reject_reason
        try:
            self.env['edu.message'].sudo()._notify_event(
                'leave_result', user, body)
        except Exception:
            _logger.warning('staff leave notify failed uid=%s', user.id,
                            exc_info=True)

    # ------------------------------------------------------------------
    # §3.5 超时升级（既有 cron 39）：语义一字不动，只补「当前应批人」
    # ------------------------------------------------------------------
    @api.model
    def _cron_escalate_pending(self):
        """超时升级提醒（cron 39）：**语义一字不动**，只把文案补上「当前应批人」。

        为什么以覆盖方式实现（而不是改 models/leave.py）：leave.py 是 S1 冻结的
        既有层、且不在 S2 的独占文件清单里；而 §3.5 明确要求提醒文案补上
        first_approver_id / second_approver_id。阈值（escalate_hours）、搜索域
        （state='request' + escalated_at 为空 + create_date 超期）、幂等标记写法
        与父实现逐字一致 —— 唯一差别就是多一行「当前应批人：…」。
        **不**自动改派教务处（§3.5 / §11 Q2 明令不做）。
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
                    '小时未处理，请尽快审批。\n当前应批人：%s'
                    % (rec.name or '—', rec.student_id.name or '—',
                       rec.date_from or '—', rec.date_to or '—', hours,
                       rec.current_approver_label()))
            notify_approvers(self.env, body)
        pending.write({'escalated_at': fields.Datetime.now()})
        return len(pending)


class OpBatchExt(models.Model):
    """§5.1「当班教职同工」= 班主任：**新建字段，落在班级上**。

    为什么落 op.batch（而不是 op.faculty）
    -------------------------------------
    1. 「班主任」是**班级**属性：一个班一个班主任 ⇒ 一列足够；
    2. **不落 op.faculty**：本仓 op_faculty 0 个在职行（生产实测），
       把班主任钉在它上面，老师到位时**必须先建 op.faculty 才能填班主任**
       ⇒ 多一层依赖；
    3. **不新建模型**：没有「多班主任」或「带任期」的需求；
    4. **不用 res.partner**：路由要的是**账号**，直接存 res.users
       ⇒ 零解析、零失败分支，与既有 edu.approval.delegate 的
       delegator_id/delegate_id 口径一致。

    ⚠ **可空、非 required**（硬要求，§3.3）
    --------------------------------------
    本仓今天 **0 个班主任**（字段全空）⇒ 若无班主任则一级审批直接落教务处，并在
    单据上显示「未设班主任，已转教务处」。这是**预期行为，不是降级**。
    老师到位后「只填数据」即生效（后台「班级」表单里填一个下拉框，
    不建档案、不改代码、不 -u）；**在途单据不回溯**（first_approver_id 是提交时快照）。

    ⚠ 刻意**不加 domain**（与 §5.1「字段加 domain」的缓解建议不同，理由如下）
    -----------------------------------------------------------------------
    §5.3 明确本仓 teacher@local 是门户账号且 share=True，而 §5.3 又要求身份判定
    **不看 share**。若给本字段加 domain=[('share', '=', False)]，恰恰会把这类
    真实教师账号挡在候选之外 —— 与设计意图相反。故不加 domain，改用帮助文本说清
    「填的是账号，不是人事档案」。
    """

    _inherit = 'op.batch'

    homeroom_teacher_id = fields.Many2one(
        'res.users', string='班主任', ondelete='set null',
        help='该班的班级导师（「当班教职同工」）。'
             '**留空 = 本班请假单的一级审批直接落教务处**'
             '（单据显示「未设班主任，已转教务处」）。'
             '填的是**账号**（res.users），不是人事档案；'
             '换老师换账号时本字段不会自动跟随 op.faculty（已知代价，不做双向同步）。'
             '⚠ 只影响**新提交**的请假单；在途单据的审批人是提交时快照的。')












