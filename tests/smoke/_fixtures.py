# -*- coding: utf-8 -*-
"""共享冒烟夹具：**教师载体**构造器（t61）。

为什么需要它（本轮的痛）
------------------------
`current_faculty()` 的实现是
    op.faculty.sudo().search([('user_id', '=', env.uid)], limit=1)
而 `op.faculty` 是 `_inherits = {'res.partner': 'partner_id'}`，所以 `op.faculty.user_id`
**委托到 `res.partner.user_id`**。

但 Odoo 自己在 `res_partner.py` 里注明：
    # Warning: user_id is a Salesperson, not the inverse of partner_id in
    # res.users. For the latter, see user_ids and main_user_id.
即 `partner.user_id` 是「销售员」字段；`res.users.create({'partner_id': p})`
**不会**自动回写它（Odoo 维护的是 `partner.user_ids`）。

漏写的后果（实测）：`op.faculty.search([('user_id', '=', uid)])` 命中 `[]` →
该账号**根本不是教师**。于是「越权被拒」与「根本没有教师身份被拒」在结果上
**完全同形**，测试会"稳定地绿"——这正是 study-eng 主动降级 t43 证据的原因。

本模块把「载体必须先被断言合法」从**每个测试作者的自觉**变成**构造器的保证**：
建号 → **显式写 partner.user_id** → 建 op.faculty → **立刻断言能被 current_faculty() 解析**。
调用方拿不到"半合法"载体。

约束（均为实测，勿删）
----------------------
* `op.faculty` 的 NOT NULL 只有 5 列：
  `partner_id` / `first_name` / `last_name` / `birth_date` / `gender`；
* **gender 只接受 male / female**（写 'm' 直接 ValueError）；
* **删除顺序必须是 faculty → users → partner**，反序会撞
  `res.partner._unlink_except_user`（"您不能删除与活动用户关联的联系人"）；
* 清场**按外键反查**，不要按 name 搜：曾有一个"名字不匹配"的引用把清场整个卡住。

用法（在 odoo shell 里，见 authz_endtoend_smoke.py 的注入方式）：
    faculty = make_teacher(env, tag='【冒烟】tXX', login='tXX@local')
    print('LOOKUP=%s' % teacher_lookup(env, faculty.user_id.id).ids)   # 显式可读
    ...
    cleanup_teachers(env, '【冒烟】tXX')
"""

TEACHER_TAG = u'【冒烟】'


class HalfLegalTeacher(AssertionError):
    """构造出的教师无法被 current_faculty() 解析 —— 即"半合法载体"。"""


def teacher_lookup(env, uid):
    """与 current_faculty() **同一判据**：按 user_id 解析教师。"""
    return env['op.faculty'].sudo().search([('user_id', '=', uid)])


def make_teacher(env, tag=TEACHER_TAG, login='smoke_teacher@local',
                 first_name=None, last_name=None, gender='male',
                 birth_date='1985-01-01', groups=None):
    """建一个**保证合法**的教师，返回 op.faculty 记录（单条）。

    内部前置断言：建完立刻校验 `teacher_lookup(env, uid)` 命中 1 条，
    否则抛 `HalfLegalTeacher` —— **漏写 partner.user_id 必然报错，不可能静默通过**。
    """
    P = env['res.partner'].sudo()
    U = env['res.users'].sudo().with_context(active_test=False)
    login = login
    # 幂等：同名/同登录的先清掉（按外键反查，见 cleanup_teachers）
    old = U.search([('login', '=', login)])
    if old:
        cleanup_teachers(env, tag, logins=[login])
    partner = P.create({'name': (first_name or '') + (last_name or u'冒烟教师')})
    if groups is None:
        grp = env.ref('openeducat_core.group_op_faculty')
        groups = [grp.id]
    user = U.create({
        'name': partner.name, 'login': login, 'password': 'demo123',
        'partner_id': partner.id, 'group_ids': [(6, 0, groups)]})
    # ★ 关键一步：op.faculty.user_id 委托到 partner.user_id，Odoo 不会自动写
    partner.sudo().write({'user_id': user.id})
    faculty = env['op.faculty'].sudo().create({
        'partner_id': partner.id,
        'first_name': first_name or (partner.name or u'冒烟'),
        'last_name': last_name or u'冒烟教师',
        'gender': gender,           # 只接受 male / female
        'birth_date': birth_date,
    })
    # ★ 前置断言：先证明"我是合法教师"，再谈越权。失败即抛，绝不静默。
    found = teacher_lookup(env, user.id)
    if len(found) != 1 or found.id != faculty.id:
        raise HalfLegalTeacher(
            'make_teacher 建出的载体不合法：teacher_lookup(uid=%s)=%s '
            '（期望恰好 [%s]）。多半是漏写 partner.user_id。'
            % (user.id, found.ids, faculty.id))
    return faculty


def cleanup_teachers(env, tag=TEACHER_TAG, logins=None):
    """按**外键反查**清场：partner 为锚点 → faculty / users → partner。

    删除顺序 faculty → users → partner（反序撞 _unlink_except_user）。
    返回 {'partners': n, 'users': n, 'faculties': n}（均应为 0）。
    """
    P = env['res.partner'].sudo().with_context(active_test=False)
    U = env['res.users'].sudo().with_context(active_test=False)
    F = env['op.faculty'].sudo().with_context(active_test=False)
    partners = P.browse()
    if logins:
        partners |= U.search([('login', 'in', list(logins))]).mapped('partner_id')
    partners |= P.search([('name', 'like', tag)])
    partners = partners.filtered(lambda p: p.id)
    F.search([('partner_id', 'in', partners.ids)]).unlink()
    U.search([('partner_id', 'in', partners.ids)]).unlink()
    partners.unlink()
    return {
        'partners': len(P.search([('name', 'like', tag)])),
        'users': len(U.search([('partner_id', 'in', partners.ids)])
                   | (U.search([('login', 'in', list(logins))]) if logins else U.browse())),
        'faculties': len(F.search([('partner_id', 'in', partners.ids)])),
    }
