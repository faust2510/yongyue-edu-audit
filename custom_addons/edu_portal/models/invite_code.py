# -*- coding: utf-8 -*-
"""注册邀请码：管理员发放、访客凭码注册为对应层级 / 对应身份。

两种码（t16，2026-09-17 校长裁定；设计见 docs/plans/invite-code-tiers-design.md）：
  1) 绑人码（v2.1-B8 现状）：码绑到某位学生/家长/教师的档案，注册后自动挂接 user_id；
  2) 层级码（新）：码只带层级（学生/家长/教师/教务），注册后账号获得该层级权限；
     学生/教师/家长层在**没有可认领的既有档案**时自动建「待分配」档案（名称前缀 +
     edu_pending_setup 标记；家长档案不绑孩子、关系用「待定（层级码注册）」占位，
     见 TIER_ARCHIVE 注释）；**学生层先认领教务预建的既有档案**（按学号 → 姓名，
     认领不到才新建，见 create_pending_archive / _edu_find_claimable_student）。

次数与有效期（校长裁定②）：use_limit = 可用次数（0 = 不限；用尽即 state='used'）；
expire_at 可改（默认 7 天）；批量生成见 edu.invite.code.batch 向导（结果可全选复制）。

安全（校长裁定：教务层码仅超级管理员可发）**三层拦截**：
  ① 视图层：tier 选项按用户过滤（_tier_selection，教务看不到 backoffice 选项）；
  ② 记录规则：views/invite_code_views.xml 里的 ir.rule（全局条件域：非 system 用户读不到、
     也建不了教务层记录）；
  ③ ORM 守卫（本文件 create/write）：sudo() 会绕过 ②，所以**这一层必须有**——它判的是
     「人」而不是「权限」，在 sudo 路径下依然生效。
"""
import datetime
import logging
import random

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)

# 身份反查/正向的**唯一实现**（edu_portal 依赖 edu_schedule，无环；
# 先例：models/fees.py、controllers/ical.py 都从这里取）。
# 禁止在本文件另写 (user_id, '=', uid) / partner.user_id 单链反查。
from odoo.addons.edu_schedule.models.identity import users_of_profile

# 去掉易混字符（0/O、1/I/L）的随机码表
_ALPHABET = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'

# 「待分配」档案的人眼标记；机器可筛字段是 edu_pending_setup（见文末 op.student / op.faculty 扩展）
_PENDING_PREFIX = '【待分配】'

# 认领既有档案（学生层）时用到的 LIKE 通配符：注册输入的姓名/学号里若出现它们，
# 一律**不用** `=ilike` 召回（否则用户的输入会变成模式串，召回一堆无关档案）。
_LIKE_WILDCARDS = ('%', '_')


def _name_key(raw):
    """姓名比对键：去「【待分配】」前缀 + 去首尾空白 + 大小写归一（casefold）。

    两侧都过同一个函数，于是：
      · 存量档案名带前缀（早先层级码注册建的）与不带前缀（教务预建的）**都能对上**；
      · 手输姓名的大小写不稳（拉丁姓名）也一并对上；中文无大小写，casefold 是恒等变换。
    """
    text = (raw or '').strip()
    if text.startswith(_PENDING_PREFIX):
        text = text[len(_PENDING_PREFIX):].strip()
    return text.casefold()

# 层级 → 注册后写入的组（单一事实源；四层口径见 views/group_tuning.xml）
# student/parent = base.group_portal（门户用户）；faculty/backoffice = 内部用户
TIER_GROUPS = {
    'student': 'base.group_portal',
    'parent': 'base.group_portal',
    'faculty': 'openeducat_core.group_op_faculty',
    'backoffice': 'openeducat_core.group_op_back_office_admin',
}
_TIER_LABELS = {
    'student': '学生', 'parent': '家长', 'faculty': '教师', 'backoffice': '教务',
}

# 层级 → 是否自动建「待分配」档案（create_pending_archive）：
#   · student → op.student：必填只有 gender + partner_id，可干净创建；建完门户页面立刻可用
#     （不建的话，门户要求档案的页面会静默 redirect /my/home —— 正是 t6 设计稿 §5.1 的 C1 死角）
#   · faculty → op.faculty：校长逐条①「凭码注册自动建待分配档案」
#   · parent  → op.parent：校长 2026-09-17 裁定「家长层自动建档」（覆盖 t16 的「不建」判断）。
#     两个必填字段这样处理（t19，实测取证）：
#       - student_ids（m2m, required=True）：**不绑任何真实学生**。实测 Odoo 不强制 required m2m
#         （无孩子也能建），故字段原样保留、档案天然无孩子 ⇒ 亲子关系由教务后补。
#       - relationship_id（m2o, required=True）：DB 有 NOT NULL（实测 NotNullViolation），必须给值
#         ⇒ 用**显式占位**「待定（层级码注册）」（见 _PENDING_RELATIONSHIP）：不选任何真实关系、
#         不放宽全局 NOT NULL，占位在档案上一眼可见。
#   · backoffice → 不建：教务层没有「教务档案」这个实体，它给的是后台管理权
TIER_ARCHIVE = {'student': 'op.student', 'faculty': 'op.faculty',
                'parent': 'op.parent'}
TIER_ARCHIVE_NOTE = ('学生/教师/家长层自动建「待分配」档案；家长档案不绑孩子、关系用'
                     '「待定（层级码注册）」占位，由教务后补；教务层无档案实体')
_PENDING_RELATIONSHIP = '待定（层级码注册）'

# 教务层码的拒绝文案（验收④要求给出拦截层与文案）
_BACKOFFICE_TIER_DENIED = '教务层邀请码只能由超级管理员发放；当前账号无此权限（拦截层：ORM 守卫 edu.invite.code.create/write）'


def _random_code_body(length=6):
    return ''.join(random.choice(_ALPHABET) for _ in range(length))


def _default_gender(env, model_name):
    """取该模型 gender 字段的第一个合法选项（各模型口径不同：op.student 用 'm'/'f'）。

    写死 'male' 会直接炸：ValueError: Wrong value for op.student.gender: 'male'
    （2026-09-17 实测）。
    """
    selection = env[model_name]._fields['gender'].selection
    if isinstance(selection, list) and selection:
        return selection[0][0]
    return False


def _tier_selection(env):
    """tier 字段的选项：教务层只在系统管理员面前出现（三层拦截的第①层=视图层）。

    用「可调用 selection」而不是写死 —— 教务在界面上根本看不到也可以不选教务层；
    真正的拒绝仍由 ir.rule + ORM 守卫兜底（选项过滤只是防手滑，不是安全边界）。
    """
    opts = [('student', '学生'), ('parent', '家长'), ('faculty', '教师')]
    if env.user._is_superuser() or env.user.has_group('base.group_system'):
        opts.append(('backoffice', '教务'))
    return opts


class EduInviteCode(models.Model):
    _name = 'edu.invite.code'
    _description = '注册邀请码'
    _order = 'create_date DESC'

    code = fields.Char('邀请码', required=True, index=True, copy=False,
                       help='可自定义（如 TEACHER-123）；留空则自动生成 EDU-XXXXXX。'
                            '统一按大写存储与校验。')
    code_kind = fields.Selection(
        [('person', '绑人码'), ('tier', '层级码')], string='码类型',
        default='person', required=True, index=True,
        help='绑人码：绑到具体学生/家长/教师档案；层级码：只带层级，不绑人（可批量发）。')
    tier = fields.Selection(
        selection='_selection_tier', string='层级',
        help='层级码专用：凭码注册后账号即属于该层级；教师/教务层会开通后台账号。')
    note = fields.Char('备注（发放对象）')
    # v2.1-B8：邀请码绑身份——发放时指定注册身份与对应人员，
    # 注册成功后新账号自动挂接到该人员的 user_id
    identity = fields.Selection(
        [('student', '学生'), ('parent', '家长'), ('faculty', '教师')],
        string='注册身份',
        help='绑人码专用：发放给对应人员时选择，注册成功后账号自动挂接到该人员的档案（user_id）。')
    student_id = fields.Many2one('op.student', string='对应学生',
                                 ondelete='set null')
    parent_id = fields.Many2one('op.parent', string='对应家长',
                                ondelete='set null')
    faculty_id = fields.Many2one('op.faculty', string='对应教师',
                                 ondelete='set null')
    state = fields.Selection(
        [('unused', '未使用'), ('used', '已使用')],
        default='unused', index=True)
    # 校长裁定②：次数可设（用尽即失效）
    use_limit = fields.Integer('可用次数', default=1, required=True,
                               help='0 = 不限次数；达到上限后自动变为「已使用」。')
    used_count = fields.Integer('已使用次数', default=0, readonly=True)
    uses_left = fields.Integer('剩余次数', compute='_compute_uses_left',
                               help='-1 表示不限次数。')
    batch_ref = fields.Char('批次', index=True, readonly=True,
                            help='批量生成时同批共用的标签（便于筛出这一批）。')
    created_by = fields.Many2one('res.users', string='发放人',
                                 default=lambda self: self.env.user)
    used_by = fields.Many2one('res.users', string='注册用户', readonly=True,
                              help='第一个使用该码的账号（多次码只记第一个）。')
    used_login = fields.Char('注册邮箱', readonly=True)
    used_on = fields.Datetime(readonly=True)
    expire_at = fields.Datetime(
        '有效期至', required=True,
        default=lambda self: fields.Datetime.now() + datetime.timedelta(days=7))

    _code_uniq = models.Constraint('unique (code)', '邀请码必须唯一（该码已存在）。')

    # ------------------------------------------------------------------
    # 字段辅助
    # ------------------------------------------------------------------
    @api.model
    def _selection_tier(self):
        return _tier_selection(self.env)

    @api.depends('use_limit', 'used_count')
    def _compute_uses_left(self):
        for rec in self:
            rec.uses_left = (rec.use_limit - (rec.used_count or 0)
                             if rec.use_limit else -1)

    @api.model
    def new_code(self):
        """生成 EDU-XXXXXX 形态随机码。"""
        return 'EDU-' + _random_code_body()

    # ------------------------------------------------------------------
    # 三层拦截之③：ORM 守卫（sudo 也绕不过）
    # ------------------------------------------------------------------
    def _is_privileged_issuer(self):
        """能发教务层码的人 = 超级管理员 / 系统管理员（settings）。"""
        return (self.env.user._is_superuser()
                or self.env.user.has_group('base.group_system'))

    def _guard_backoffice_tier(self, vals_list):
        """非超管建/改教务层码 → AccessError（第③层，也是唯一在 sudo 下仍生效的一层）。"""
        if self._is_privileged_issuer():
            return
        for vals in (vals_list or []):
            if vals.get('tier') == 'backoffice':
                raise AccessError(_BACKOFFICE_TIER_DENIED)

    @api.model_create_multi
    def create(self, vals_list):
        self._guard_backoffice_tier(vals_list)
        for vals in vals_list:
            code = (vals.get('code') or '').strip()
            vals['code'] = code.upper() if code else self.new_code()
            # 兼容：只给 identity（旧口径）的调用方 → 视为绑人码
            if vals.get('tier') and not vals.get('code_kind'):
                vals['code_kind'] = 'tier'
        return super().create(vals_list)

    def write(self, vals):
        # 只拦「把码改成教务层」；消费路径（consume 写 state/used_*）不受影响
        if vals.get('tier') == 'backoffice':
            self._guard_backoffice_tier([vals])
        if vals.get('code'):
            vals['code'] = vals['code'].strip().upper()
        return super().write(vals)

    @api.onchange('code_kind')
    def _onchange_code_kind(self):
        """切换「码类型」时清掉已失效的从属字段（体验层；约束仍是真相层）。

        现场（2026-09-17 用户截图，码 EDU-SCRTS）：先在列表行内编辑里选了
        「注册身份=学生」，之后把「码类型」改成「层级码」—— identity 留在
        原地不动，直到点保存才被 _check_kind_exclusive 拦下。这不是用户填错，
        是「切换状态后没有清理从属字段」：码类型是主开关，开关一翻，另一侧的
        值必然失效。onchange 在改字段的那一刻就把它清掉，用户不会在保存时才撞墙。

        两个方向都清（对称）：
          · 切到层级码 → 清 identity / student_id / parent_id / faculty_id ——
            约束判的就是这四个字段，留着必炸；
          · 切回绑人码 → 清 tier —— 同理，绑人码带层级同样非法；留着一个
            用户看不见的 tier 只会让他再撞一次墙。

        约束一字不移：onchange 只覆盖「人在界面上改字段」这一条路径
        （导入 / 脚本 / XML-RPC 写库都绕过它），真相层必须由
        _check_kind_exclusive 兜住 —— 两层都要。
        """
        for rec in self:
            if rec.code_kind == 'tier':
                rec.identity = False
                rec.student_id = False
                rec.parent_id = False
                rec.faculty_id = False
            else:
                rec.tier = False

    def _kind_exclusive_label(self):
        """约束文案里的「哪一条」定位（逐条取值，多记录的 self 也安全）。"""
        self.ensure_one()
        code = (self.code or '').strip()
        if code:
            return '邀请码 %s' % code
        if isinstance(self.id, int):
            return '邀请码 #%s' % self.id
        return '本条邀请码'

    @api.constrains('tier', 'identity', 'code_kind')
    def _check_kind_exclusive(self):
        """两种码语义互斥：层级码不绑人；绑人码必须有身份。

        文案必须能指认「是哪一条」：self 可能是多条记录（列表视图
        editable="bottom" 一次保存多行），而原文案不带任何定位信息 ——
        用户只看到「层级码只带层级…」，不知道是几行里的哪一行（2026-09-17
        现场）。故逐条查、逐条 raise：定位信息必定属于真正违规的那条记录。
        原有文案逐字保留，只在前面加「邀请码 XXX：」这一层定位。
        """
        for rec in self:
            who = rec._kind_exclusive_label()
            if rec.code_kind == 'tier':
                if rec.identity or rec.student_id or rec.parent_id or rec.faculty_id:
                    raise ValidationError(
                        '%s：层级码只带层级、不绑具体人员：请清空「注册身份/对应人员」。' % who)
                if not rec.tier:
                    raise ValidationError(
                        '%s：层级码必须选择层级。请补选「层级」后再保存。' % who)
            else:
                if rec.tier:
                    raise ValidationError(
                        '%s：绑人码不使用「层级」字段：请改为层级码或清空层级。' % who)

    # ------------------------------------------------------------------
    # 校验与消费（供注册控制器调用）
    # ------------------------------------------------------------------
    def _validate_view(self):
        """返回 None 表示可用；否则返回人话错误原因。"""
        self.ensure_one()
        now = fields.Datetime.now()
        if self.state != 'unused' or (self.use_limit
                                      and (self.used_count or 0) >= self.use_limit):
            return '该邀请码已被使用'
        if self.expire_at and self.expire_at < now:
            return '该邀请码已过期'
        return None

    def _used_by_login(self, login=None):
        """该码是否已被**同一个登录邮箱**消费掉（= 重复提交里的那个「输家」）。

        为什么需要这条判据（2026-09-24 生产 edu.example.org 事故）：注册表单被连点两次时，
        第一次请求真正建号并消费了码（consume 写 state='used' + used_login），第二次请求
        晚到，_validate_view() 只能回一句笼统的「该邀请码已被使用」—— 浏览器渲染的恰恰是
        这第二个响应，于是一次**成功**的注册被说成失败（校长据此怀疑一码发给了两个人）。
        「码记录 + 提交的邮箱」这两条信息只有本模型同时具备（控制器此刻手上只有码记录），
        故判据归这里；控制器只负责换落点（成功页 vs 错误页）。

        口径（三条都不得放宽）：
          * 只认 used_login —— 沿用既有语义「多次码只记第一个使用者的账号」
            （见 consume）；第二个使用者写不进 used_*，故不会被误认成「本人」。
          * 大小写与首尾空格归一：学生手输邮箱的大小写不稳定，而同一个邮箱的两次提交
            本应互认；归一**只朝「认成本人」方向放宽**，不会把本人判成他人（两个仅
            大小写不同的登录名在现实中就是同一个邮箱；且本路径**不建号**，
            「一个码一个账号」的保证不受影响）。
          * 空邮箱、未消费一律 False —— 控制器在字段校验失败时会带空邮箱进来，
            空串相等绝不能落进「已注册成功」分支。
        """
        self.ensure_one()
        used = (self.used_login or '').strip().lower()
        return bool(used) and used == (login or '').strip().lower()

    def identity_record(self):
        """返回身份对应的 op.student / op.parent / op.faculty 记录（无则 None）。"""
        self.ensure_one()
        if self.identity == 'student':
            return self.student_id
        if self.identity == 'parent':
            return self.parent_id
        if self.identity == 'faculty':
            return self.faculty_id
        return None

    def _validate_identity(self):
        """绑身份码的注册前置校验：返回 None 表示可注册，否则返回错误原因。

        这是**写入前**的守卫（此刻账号还没建），判的是「该人员有没有被别人
        占用」。占用口径 = 唯一实现 edu_schedule/models/identity.py 的
        users_of_profile（档案自身 user_id ∪ 伙伴 user_id ∪ 伙伴 user_ids）。

        原实现只查前两条（评审 F2 的 student/faculty/parent 三分支其实是同一
        条链的三种写法），漏掉 Odoo 19 的规范反向 res.partner.user_ids
        （core res_partner.py:287）⇒「账号已在该伙伴名下、但伙伴的销售员列
        是空的」这种真实形态（脚本 / 接口建的账号）判不出来：同一份学生档案
        能被第二个账号绑走（**身份被抢**，实测复现见
        tests/smoke/identity_guard_batch1.py 的 before 相位）。

        反向（一个账号挂多份档案）不在这里判：本路径每个注册都是**新账号**，
        账号侧无冲突面；既有账号的那一侧在 controllers/contacts.py 的
        relink_guard_reason。
        """
        self.ensure_one()
        if not self.identity:
            return None
        rec = self.identity_record()
        if not rec:
            return '该邀请码已指定身份但未选择对应人员，请联系管理员'
        if users_of_profile(rec):
            return '该邀请码对应的人员已绑定其他账号，请向管理员重新索取'
        return None

    def attach_identity(self, user):
        """绑人码：注册成功后把新账号挂接到对应人员的 user_id（一人一挂）。

        - 学生：op.student.user_id
        - 家长：op.parent.user_id（并同步 partner 关联，兼容
          edu.telegram.binding 的 ('name.user_id', '=', …) 解析）
        - 教师：op.faculty 无独立 user_id 字段（委托 res.partner），
          写 partner.user_id 即等价于 op.faculty.user_id，门户
          current_faculty() 可据此命中。
        """
        self.ensure_one()
        if not self.identity:
            return
        rec = self.identity_record()
        if not rec:
            return
        if self.identity == 'faculty':
            rec.partner_id.write({'user_id': user.id})
        else:
            rec.write({'user_id': user.id})
            if self.identity == 'parent' and rec.name:
                rec.name.write({'user_id': user.id})

    # ------------------------------------------------------------------
    # 层级码：组 + 「待分配」档案（t16）
    # ------------------------------------------------------------------
    def tier_group(self):
        """层级码注册后要写入的组（绑人码/未设层级 → None）。"""
        self.ensure_one()
        xmlid = TIER_GROUPS.get(self.tier) if self.code_kind == 'tier' else None
        return self.env.ref(xmlid) if xmlid else None

    def create_pending_archive(self, user, display_name, gr_no=None):
        """层级码注册：**先认领既有档案，认领不到才建**「待分配」档案并挂接。

        为什么用**账号自己的 partner**：与绑人码一致（一人一档案），
        教师层的 op.faculty.user_id 委托 partner.user_id，挂上即可被
        current_faculty() 命中；学生层直接写 op.student.user_id；
        家长层写 op.parent.user_id（+ partner.user_id，和绑人码路径一致）。
        名称加「待分配」前缀 —— 课表/点名/教师列表里一眼能看出尚未完善；
        另置 edu_pending_setup=True 供后续按字段筛（与教师层同源同名字段）。

        学生层为什么先认领（2026-09-24）：教务常常**先**按学号/姓名把学生档案
        与分班建好（无账号、edu_pending_setup=False），再发层级码让学生自己注册。
        旧实现无条件新建 ⇒ 同一个人两条档案（班上同名两条，课表/点名/成绩分散）。
        认领顺序、以及「同名多条 / 命中的档案已绑账号」两种不认领的处置，
        见 _edu_find_claimable_student。

        fail-safe（硬要求）：认领**只读** + savepoint 包裹，任何异常都退回原
        「新建待分配档案」路径并记日志 —— 匹配逻辑出错绝不能让人注册不了。

        :param gr_no: 注册页「学号（选填）」的值；填了优先按学号匹配，
            没填（或没命中）则按姓名匹配。**不填一切照旧**。
        """
        self.ensure_one()
        if self.code_kind != 'tier' or self.tier not in TIER_ARCHIVE:
            return None
        name = (display_name or '').strip() or user.login
        partner = user.partner_id.sudo()
        # 认领尝试放在**分支之前**：认领到了就直接返回（不写「【待分配】」前缀），
        # 认领不到则继续走下面各自的建档分支 + 末尾那一次共用的前缀写入。
        claimed, dup_note = None, None
        if self.tier == 'student':
            claimed, dup_note = self._edu_claim_or_none(user, name, gr_no)
        if claimed is not None:
            return claimed
        if self.tier == 'student':
            rec = self.env['op.student'].sudo().create({
                'partner_id': partner.id,
                # 名字**显式在建档时就给**（不是只靠末尾那次 partner.write）：op.student
                # 基座 create 在「没给 name」时会把 name 填成 'New'
                # （openeducat_core/models/student.py:121-131），而 name 是 _inherits 委托到
                # partner 的 ⇒ 那条 'New' 会跟着建档写进账号的 partner。实测（2026-09-24，
                # 本地 clone，HTTP 真实注册）：这条 'New' 与末尾的前缀写在 ORM 刷写顺序上
                # 有竞态 —— 曾出现「注册成功但档案名叫 New」（tests/smoke/
                # register_claim_archive.py 的 E 用例抓到）。在建档 vals 里直接给全名，
                # 无论刷写先后，落库的都是「【待分配】+ 姓名」，不再有 'New' 这一手。
                'name': _PENDING_PREFIX + name,
                'gender': _default_gender(self.env, 'op.student'),
                'user_id': user.id,
                'edu_pending_setup': True,
                # 匹配到同名/同学号的既有档案却无法自动认领（多条同名、或命中项
                # 已绑账号）⇒ 退回老路径新建，但把信号落成**可筛字段 + 审计留痕**，
                # 教务在「学生」列表筛得出来、在 /edu/audit 搜得到（见字段 help）。
                'edu_dup_suspect': bool(dup_note),
                'edu_claim_note': dup_note or False,
            })
            if dup_note:
                self.env['edu.audit.log'].sudo()._log(
                    '注册疑似重复', 'op.student', rec.id, rec.name or '', dup_note)
        elif self.tier == 'parent':
            # 家长层（t19）：**不绑任何真实学生**；relationship_id 是 DB NOT NULL，
            # 用显式占位「待定（层级码注册）」——占位可见可识别，不是真实亲属关系。
            rel = self.env['op.parent.relationship'].sudo().search(
                [('name', '=', _PENDING_RELATIONSHIP)], limit=1)
            if not rel:
                rel = self.env['op.parent.relationship'].sudo().create(
                    {'name': _PENDING_RELATIONSHIP})
            rec = self.env['op.parent'].sudo().create({
                'name': partner.id,
                'relationship_id': rel.id,
                'user_id': user.id,
                'edu_pending_setup': True,
            })
            partner.write({'user_id': user.id})
        else:
            # faculty：必填 partner_id / first_name / last_name / birth_date / gender
            # （实测 2026-09-17）——birth_date 只能给占位值，档案本身已带「待分配」标记，
            # 由教务在补全档案时一并改正。
            rec = self.env['op.faculty'].sudo().create({
                'partner_id': partner.id,
                'first_name': name,
                'last_name': '',
                'birth_date': fields.Date.today(),
                'gender': _default_gender(self.env, 'op.faculty'),
                'edu_pending_setup': True,
            })
            partner.write({'user_id': user.id})
        # 「待分配」前缀放在**建完档案之后**写：op.faculty 建档案时会按
        # first_name/last_name 重算 partner.name，先写会被覆盖（实测 2026-09-17）。
        partner.write({'name': _PENDING_PREFIX + name})
        return rec

    # ------------------------------------------------------------------
    # 学生层：认领教务预建的既有档案（2026-09-24）
    # ------------------------------------------------------------------
    def _edu_claim_or_none(self, user, name, gr_no):
        """尝试认领既有学生档案；返回 (命中的 op.student | None, 疑似重复说明 | None)。

        **fail-safe 的唯一入口**：认领的匹配（只读）与挂接（写 user_id）整体包在
        savepoint 里 —— 出任何异常都回滚到进入前、记日志、返回 (None, None)，由调用方
        走原「新建待分配档案」路径。于是「认领」这条新路径**不可能**让注册失败，
        也不可能只写一半（savepoint 保证全有或全无）。
        """
        claimed, dup_note, how = None, None, ''
        try:
            with self.env.cr.savepoint():
                claimed, dup_note, how = self._edu_find_claimable_student(name, gr_no)
                if claimed:
                    self._edu_claim_student_to_user(claimed, user)
        except Exception:
            _logger.warning(
                '[edu_portal] 邀请码 %s 注册：认领既有学生档案失败，已退回新建'
                '「待分配」档案（注册不受影响）', self.code, exc_info=True)
            return None, None
        if claimed is None:
            return None, dup_note
        # 标记收口（去「【待分配】」前缀 + 清 edu_pending_setup）**单独**包一层：
        # 它属于「档案显示对不对」而不是「人挂没挂上」—— 这一步失败绝不能反过来
        # 再建一条档案（那正是本次要治的重复），所以只记日志。
        try:
            with self.env.cr.savepoint():
                claimed._edu_clear_pending_marker()
        except Exception:
            _logger.warning(
                '[edu_portal] 学生档案 #%s 认领成功，但「待分配」标记收口失败；'
                '档案已挂上账号，请教务在本档案上手工核对名字前缀与「待分配档案」勾选',
                claimed.id, exc_info=True)
        self.env['edu.audit.log'].sudo()._log(
            '层级码注册认领', 'op.student', claimed.id, claimed.name or '',
            '邀请码 %s 按%s认领既有学生档案 #%s（未新建档案）'
            % (self.code, '学号' if how == 'gr_no' else '姓名', claimed.id))
        return claimed, None

    def _edu_find_claimable_student(self, name, gr_no):
        """在**建新档案之前**找可认领的既有 op.student；返回 (rec|None, 说明|None, 依据)。

        认领顺序（命中即定，不再往下猜）：
          ① **学号** → op.student.gr_no 精确匹配（大小写不敏感作兜底）。学号是学籍的
             唯一真身（openeducat_core/models/student.py:106 的 unique(gr_no)），
             也比姓名可靠得多，所以只要注册页给了学号就先走这条。
          ② **姓名** → 与档案的 partner_id.name 比对（本仓显示名 = 化名；带
             「【待分配】」前缀的存量档案按**去前缀后**比对，见 _name_key）。
          ③ 都没命中 → (None, None, '') = 保持既有行为（新建「待分配」档案）。

        刻意**不**认领、退回新建并留「疑似重复」信号的两种情形：
          · 同名命中**多条**且都空着 → 谁是本人无从判断。瞎认领会把甲的分班/课表/
            成绩挂到乙的账号上，比多一条待分配档案严重得多。
          · 命中的档案**已绑账号**（users_of_profile 非空，唯一口径 edu_schedule/
            models/identity.py）→ 不许抢：抢 = 把别人账号名下的档案挂到这个新账号上
            （新账号会看到别人的成绩/账单）。学号命中这种情况时**不再**退回按姓名猜：
            两个依据互相矛盾时，猜错的风险大于收益。

        本方法**只读**（写库在 _edu_claim_student_to_user），所以能整体包在
        savepoint + try 里 fail-safe（见 _edu_claim_or_none）。
        """
        gr = (gr_no or '').strip()
        if gr:
            hit = self._edu_student_by_gr_no(gr)
            if hit:
                owners = users_of_profile(hit)
                if owners:
                    return None, (
                        '疑似重复，请教务核对：注册填的学号 %s 命中已有的学生档案 #%s'
                        '（%s），但该档案已绑定其他账号（%s）；系统未抢占，已另建本'
                        '「待分配」档案。'
                        % (gr, hit.id, hit.name or '',
                           '、'.join(owners.mapped('login')))), ''
                return hit, None, 'gr_no'
        key = _name_key(name)
        if not key:
            return None, None, ''
        cands = self._edu_students_by_name(name, key)
        free = cands.filtered(lambda r: not users_of_profile(r))
        if len(free) == 1:
            return free, None, 'name'
        if len(free) > 1:
            return None, (
                '疑似重复，请教务核对：按姓名「%s」匹配到 %d 条同名档案（%s），'
                '无法判断哪一条是本人；系统未自动认领，已另建本「待分配」档案。'
                % (name, len(free),
                   '、'.join('#%s' % i for i in free.ids))), ''
        taken = cands - free
        if taken:
            return None, (
                '疑似重复，请教务核对：按姓名「%s」匹配到的档案（%s）已绑定其他账号，'
                '系统未抢占，已另建本「待分配」档案。'
                % (name, '、'.join('#%s' % i for i in taken.ids))), ''
        return None, None, ''

    def _edu_student_by_gr_no(self, gr):
        """按学号取档案（精确优先；大小写不敏感作兜底）。

        gr_no 上有唯一约束 ⇒ 命中最多多 1 条，不需要「同名多条」那套判断。
        兜底用 =ilike（大小写不敏感）是因为学生手输学号的大小写不稳；值里若含
        LIKE 通配符（% _）则**不**走兜底 —— 否则用户的输入会变成模式串。
        默认域排除 active=False 的档案（Odoo 的 active_test），停用档案不认领。
        """
        Student = self.env['op.student'].sudo()
        hit = Student.search([('gr_no', '=', gr)], limit=1)
        if not hit and not any(c in gr for c in _LIKE_WILDCARDS):
            hit = Student.search([('gr_no', '=ilike', gr)], limit=1)
        return hit

    def _edu_students_by_name(self, name, key):
        """按姓名取候选档案（域**宽召回**，最终判定在 Python 里逐字比对）。

        两步走的理由：
          · 存量档案名可能带「【待分配】」前缀 ⇒ 域要同时试「输入名」与「前缀+输入名」；
          · 手输姓名的大小写不稳 ⇒ 用 =ilike 做大小写不敏感召回；
          · 但 =ilike 的右值是 LIKE 模式（% / _ 是通配符）⇒ 输入里含这两个字符时
            退回精确 =，绝不让用户输入变成通配符。
        召回宽、判定严：最终一律用 _name_key（去前缀 + 去空白 + casefold）逐字相等。
        """
        Student = self.env['op.student'].sudo()
        raw = (name or '').strip()
        if not raw:
            return Student.browse()
        wanted = [raw, _PENDING_PREFIX + raw]
        if any(c in raw for c in _LIKE_WILDCARDS):
            domain = [('partner_id.name', 'in', wanted)]
        else:
            domain = ['|'] * (len(wanted) - 1) + [
                ('partner_id.name', '=ilike', v) for v in wanted]
        return Student.search(domain).filtered(
            lambda r: _name_key(r.partner_id.name) == key)

    def _edu_claim_student_to_user(self, student, user):
        """把既有学生档案挂到新账号上（一人一挂）。

        两件事，全部沿用本仓**既有**写入口径，不发明第二套：
          ① student.user_id = 新账号 —— 学生档案的规范链（edu_schedule/models/
             identity.py 的链①；同 controllers/contacts.py:430-434 的补挂写法）；
          ② student.partner_id.user_id = 新账号 —— 「把伙伴关联上」：本仓把账号挂在
             伙伴 user_id 列上的既有口径（attach_identity 的教师/家长分支、补挂工具
             的教师分支都这么写）；该伙伴**只在不属于任何账号时**才写（不许抢）。

        「待分配」标记的收口（edu_pending_setup + 名字前缀）不在这里 —— 它由调用方
        _edu_claim_or_none 用独立 savepoint 做（复用 models/class_batch.py:271 的
        _edu_clear_pending_marker，不另写一套）。

        **不重写姓名**：档案上的规范姓名/化名由教务维护，注册输入不得覆盖它
        （同 controllers/register.py 的评审 F1 纪律）。
        """
        student.sudo().write({'user_id': user.id})
        partner = student.partner_id
        if partner and not partner.user_id:
            partner.sudo().write({'user_id': user.id})

    def consume(self, user):
        """消费一次：累计次数；用尽则置为「已使用」（首个使用者写入 used_*）。"""
        self.ensure_one()
        count = (self.used_count or 0) + 1
        vals = {'used_count': count}
        if not self.used_by:
            vals.update({'used_by': user.id, 'used_login': user.login,
                         'used_on': fields.Datetime.now()})
        if self.use_limit and count >= self.use_limit:
            vals['state'] = 'used'
        self.write(vals)


class EduInviteCodeBatch(models.TransientModel):
    """批量生成邀请码（校长裁定②：一次生成 N 个同层级码，结果可复制）。

    码体仍是「前缀 + 随机体」而不是 TEACHER-001 这种连号：
    连号可被外面的人按序猜到（等于把邀请码变成可枚举口令）。
    """
    _name = 'edu.invite.code.batch'
    _description = '邀请码批量生成'

    code_kind = fields.Selection(
        [('tier', '层级码（推荐：只带层级）'), ('person', '绑人码（需逐个绑人）')],
        default='tier', required=True)
    tier = fields.Selection(selection='_selection_tier', string='层级')
    count = fields.Integer('生成数量', default=5, required=True,
                           help='单批 1–50 个。')
    prefix = fields.Char('码前缀', help='如 TEACHER- → 生成 TEACHER-XXXXXX（保证唯一、不可连号枚举）。')
    use_limit = fields.Integer('每码可用次数', default=1, required=True,
                               help='0 = 不限次数；教师/教务层建议 1。')
    valid_days = fields.Integer('有效期（天）', default=7, required=True)
    note = fields.Char('备注（发给谁/哪一批）')
    batch_ref = fields.Char('批次标签', readonly=True)
    generated_text = fields.Text('本批生成的码（可全选复制）', readonly=True)
    generated_count = fields.Integer('本批实际生成', readonly=True)

    @api.model
    def _selection_tier(self):
        return _tier_selection(self.env)

    def action_generate(self):
        self.ensure_one()
        count = min(max(int(self.count or 1), 1), 50)
        self.count = count
        days = max(int(self.valid_days or 0), 0)
        ref = 'B' + fields.Datetime.now().strftime('%Y%m%d-%H%M%S')
        prefix = (self.prefix or '').strip().upper()
        vals_list = []
        for _i in range(count):
            vals_list.append({
                'code': (prefix + _random_code_body(6)) if prefix else False,
                'code_kind': self.code_kind,
                'tier': self.tier if self.code_kind == 'tier' else False,
                'use_limit': int(self.use_limit or 0),
                'note': self.note,
                'batch_ref': ref,
                'expire_at': fields.Datetime.now() + datetime.timedelta(days=days),
            })
        codes = self.env['edu.invite.code'].create(vals_list)
        self.write({
            'batch_ref': ref,
            'generated_count': len(codes),
            'generated_text': '\n'.join(codes.mapped('code')),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


# ----------------------------------------------------------------------
# 「待分配」标记字段（人眼标记是名称前缀；这两个字段供后续按字段筛选/门禁）
# 声明在本文件是因为 t16 契约 inScope 只有三个文件（见任务卡）。
# ----------------------------------------------------------------------
class OpStudent(models.Model):
    _inherit = 'op.student'

    edu_pending_setup = fields.Boolean(
        '待分配档案', default=False, index=True,
        help='由层级码注册自动创建、尚未由教务处补全的档案。')

    # 「同名多条 / 命中的档案已绑账号」时用于**给教务留信号**的两个字段：
    # 布尔字段供筛选（学生列表 → 搜索框 → 筛选器 → 添加自定义筛选），
    # 字符字段写清是哪一条档案被命中（也出现在 /edu/audit 的明细里）。
    edu_dup_suspect = fields.Boolean(
        '疑似重复（待核对）', default=False, index=True,
        help='由层级码注册创建、且当时**匹配到同名或同学号的既有档案却未能自动认领**：'
             '要么同名档案不止一条，要么命中的那条已绑定其他账号。系统此时刻意不认领'
             '（怕把课表/成绩挂错人），只留信号请教务核对。'
             '筛选：学生列表 → 搜索框 → 筛选器 → 添加自定义筛选 → '
             '字段「疑似重复（待核对）」= 是；原因见「认领核对说明」一栏，'
             '也可在 操作审计（/edu/audit）搜索「疑似重复」。')

    edu_claim_note = fields.Char(
        '认领核对说明',
        help='层级码注册时为何没能自动认领既有档案（同名多条 / 命中的档案已绑账号），'
             '含被命中的档案编号；教务核对完可清空本说明并取消「疑似重复」勾选。')


class OpFaculty(models.Model):
    _inherit = 'op.faculty'

    edu_pending_setup = fields.Boolean(
        '待分配档案', default=False, index=True,
        help='由层级码注册自动创建、尚未由教务处补全的档案。')


class OpParent(models.Model):
    _inherit = 'op.parent'

    edu_pending_setup = fields.Boolean(
        '待分配档案', default=False, index=True,
        help='由层级码注册自动创建、尚未由教务处补全的档案（孩子与亲属关系待补）。')
