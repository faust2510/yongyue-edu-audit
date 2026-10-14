# -*- coding: utf-8 -*-
"""身份档案反查的**唯一口径**：登录账号 ⇄ 学生 / 家长 / 教师档案。

为什么必须只有一套口径
----------------------
Odoo 19 里「账号 ↔ 伙伴」只有一条是规范关系，另一条是**同名陷阱**：

* 规范：res.users.partner_id → 其反向 res.partner.user_ids
  （core res_partner.py:287：user_ids = fields.One2many('res.users',
  'partner_id', ...)）。
* 陷阱：res.partner.user_id 是**销售员**字段（core res_partner.py:229
  原文："user_id is a Salesperson, not the inverse of partner_id in
  res.users"），只有 _compute_user_id 从 parent_id 同步
  （res_partner.py:419-423）⇒ **程序化 create res.users 不会回填它**。

本仓历史数据把「教师登录账号」挂在 partner.user_id 上（邀请码
attach_identity、create_teacher_account.py 的显式回填），所以：

* 只按链①「记录.user_id == uid」查 ⇒ 漏掉脚本新建的账号（教师课表、
  课前提醒/改课通知、ICS 订阅、私信熟人圈**静默为空**）；
* 只按链②「partner.user_ids ∋ uid」查 ⇒ 漏掉本仓既有数据（生产按链①挂的）。

⇒ 统一口径 = **双向并集，①优先、①落空才查②**；反向（档案 → 账号）则
取两条链的**并集**。两条都是「只加不减」：既有账号的解析结果一字不变。

本模块放在 edu_schedule（而不是 edu_portal）的理由
--------------------------------------------------
1. **models 不能引 controllers**：edu_portal/controllers/roles.py 是
   controller，模型层（edu_schedule/models/session_ext.py、
   edu_portal/models/fees.py）import 它会形成「模型 → 控制器」的环，
   且控制器 import 期会注册路由，属于分层倒挂。
2. **依赖方向只有一个可用的公共落点**：edu_portal 依赖 edu_schedule
   （manifest 明写），edu_schedule 不依赖 edu_portal ⇒ 共享代码的唯一
   无环落点就是被依赖方 edu_schedule。本仓已有同型先例：
   edu_portal/controllers/scheduling.py / calendar.py 直接
   from odoo.addons.edu_schedule.models.week_utils import ...
3. 需要本模块的模块若不在 edu_schedule 的依赖闭包里（如 edu_life /
   edu_quiz / edu_public），**请把 edu_schedule 加进 depends**，不要就地
   复制一份 —— 复制出来的一定是第二套口径（本仓已因此踩过两次）。

用法
----
反查（登录账号 → 身份档案）::

    from odoo.addons.edu_schedule.models.identity import faculty_of_user
    fac = faculty_of_user(self.env)            # 当前登录账号
    fac = faculty_of_user(request.env, uid)    # 指定账号（ICS token 反查）

正向（身份档案 → 登录账号，通知收件人 / 熟人圈用）::

    from odoo.addons.edu_schedule.models.identity import users_of_profile
    users = users_of_profile(session.faculty_id | students)

伙伴级（无身份档案，只有 res.partner 的单据，如报销受理人）::

    from odoo.addons.edu_schedule.models.identity import users_of_partner
    users = users_of_partner(bill.partner_id)

已知边界（刻意保留，不静默扩大）
--------------------------------
* partner.user_ids 只返回**在用**账号（core res_partner.py:864 注释明写）；
  链① 读的是存储列，停用账号若挂在 partner.user_id 上仍会被并集带出来
  —— 这是「只加不减」的必然结果，不视为缺陷。
* 同一 partner 挂多个账号时，反查取**第一个命中**（① 优先，② 按 id 升序），
  正向则返回**全部**账号（通知要发给每个账号，否则又会静默漏人）。
"""
from odoo.exceptions import ValidationError

#: 身份模型 → (链① 记录自身 user_id 列, 链② 伙伴字段)
#: 链② 的完整域名 =「<伙伴字段>.user_ids ∋ uid」。
PROFILE_CHAINS = {
    'op.student': ('user_id', 'partner_id'),
    # op.faculty 没有自己的 user_id 列：它对 res.partner 用 _inherits 委托，
    # 所以链① 实际就是 partner_id.user_id（销售员列）—— 既是本仓既有写入口径，
    # 也是 Odoo 19 那个「同名陷阱」。链② 才是规范反向。
    'op.faculty': ('user_id', 'partner_id'),
    # op.parent 的伙伴在 name 字段（core openeducat_parent/models/parent.py:29），
    # 其 user_id 是**存储列**（:31，onchange 从 name.user_id 同步）⇒ 程序化建
    # 档案同样可能为空。
    'op.parent': ('user_id', 'name'),
}


def _chains(model):
    """取某身份模型的两条链；未知模型**响亮报错**，不静默退化成单链。"""
    if model not in PROFILE_CHAINS:
        raise ValidationError(
            '未知身份模型 %s；本仓身份模型只有 %s（见 '
            'edu_schedule/models/identity.py）'
            % (model, '、'.join(sorted(PROFILE_CHAINS))))
    return PROFILE_CHAINS[model]


def profile_of_user(env, model, uid=None):
    """由登录账号反查身份档案（**双向并集**，返回至多 1 条）。

    :param env: 任意 Environment（控制器用 request.env，模型用 self.env）
    :param model: op.student / op.faculty / op.parent
    :param uid: 账号 id；缺省 = 当前登录账号
    """
    direct, partner_field = _chains(model)
    Rec = env[model].sudo()
    uid = env.uid if uid is None else uid
    rec = Rec.search([(direct, '=', uid)], limit=1)
    if not rec:
        # 链② 只在链①落空时才查 —— 既有账号的解析结果因此一字不变
        rec = Rec.search([(partner_field + '.user_ids', 'in', [uid])], limit=1)
    return rec


def student_of_user(env, uid=None):
    """当前/指定账号对应的学生档案（无则空 recordset）。"""
    return profile_of_user(env, 'op.student', uid)


def faculty_of_user(env, uid=None):
    """当前/指定账号对应的教师档案（无则空 recordset）。"""
    return profile_of_user(env, 'op.faculty', uid)


def parent_of_user(env, uid=None):
    """当前/指定账号对应的家长档案（无则空 recordset）。"""
    return profile_of_user(env, 'op.parent', uid)


def users_of_partner(partners):
    """伙伴 → 其名下登录账号（双向并集：user_id ∪ user_ids）。

    注意：本函数只回答「这个 res.partner 名下的账号」，不含「档案自身
    user_id 列」—— 学生/家长的那一列要经 users_of_profile 才带上。

    partners 是 res.partner recordset；返回 res.users recordset。
    全程 sudo：门户账号本身对 res.users 没有读权限，不 sudo 会抛
    AccessError（那会把「查不到」伪装成 500）。
    """
    if not partners:
        return partners.env['res.users']
    partners = partners.sudo()
    Users = partners.env['res.users'].sudo()
    out = Users
    for partner in partners:
        if partner.user_id:
            out |= partner.user_id
        out |= partner.user_ids
    return out


def users_of_profile(profiles):
    """身份档案 → 其登录账号（**三条来源的并集**）：

    ① 档案自身的 user_id 列（链①的反向；学生/家长的这一列是**独立存储列**，
       与伙伴无关 —— 漏掉它就会把「按老口径挂好的学生」从收件人里删掉）；
    ② 伙伴的 user_id（销售员列，本仓挂教师账号的既有写入口径）；
    ③ 伙伴的 user_ids（Odoo 19 规范反向）。

    用于「通知收件人」「私信熟人圈」这类**必须发全**的场合：任一来源漏掉
    都等于静默漏人；同一伙伴挂多个账号时全部返回。
    """
    if not profiles:
        return profiles.env['res.users'].browse()
    users = profiles.env['res.users'].sudo().browse()
    for rec in profiles:
        direct, partner_field = _chains(rec._name)
        if direct in rec._fields and rec[direct]:
            users |= rec[direct]
        partner = rec[partner_field] if partner_field in rec._fields else None
        if partner:
            users |= users_of_partner(partner)
    return users


def user_of_profile(profile):
    """身份档案 → 单个登录账号（① 优先；一个都没有则空 recordset）。"""
    return users_of_profile(profile)[:1]
