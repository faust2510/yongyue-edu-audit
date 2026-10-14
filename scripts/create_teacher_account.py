# -*- coding: utf-8 -*-
"""在生产上建一个"教师账号"（占位）—— 绑定到教师档案的 partner，
使该账号登录后即为一名教师（op.faculty.user_id 经 partner.user_id 解析）。

幂等：已存在同名 login 则只重置密码/激活，不重复创建；可回滚：把该用户 active=False 即停用。

    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 --db_host=db -r odoo -w odoo --no-http < scripts/create_teacher_account.py

可选环境变量（都不给 = 自动挑目标，见 ③）：
    TEACHER_LOGIN=teacher@local     要建 / 复用的登录名
    TEACHER_FACULTY_ID=             指定教师档案 id

2026-09-18 修（静默失效缺陷 B，本仓当日同型第二起）：
  ① 「建完账号就会认教师」**不成立**。op.faculty 对 res.partner 用 _inherits
     委托，op.faculty.user_id 实为 related=partner_id.user_id；而 Odoo 19 的
     res.partner.user_id 是「销售员」字段，只有 _compute_user_id 从 parent_id
     同步 —— 程序化 res.users.create({partner_id: p}) **不会**回填它。
     实测（本容器 odoo shell，只读探针）：新建 partner 后 user_id=False；
     create res.users(partner_id=该 partner) 之后 partner.user_id 仍是 False，
     只是 partner.user_ids 多了一条。⇒ 建完账号必须**显式回填 partner.user_id**
     （= op.faculty.user_id，与邀请码 attach_identity 同写法）。
     不修的后果就是本缺陷：账号建出来了、页面照常 200，只是教师课表里
     什么都没有（静默落成访客空表）。
  ② **绝不抢占**：partner.user_id 只能挂一个账号。若它已挂在别的在用账号上，
     回填会把它顶掉 —— 那个老账号反而解析不出教师（新造回归）。
     ⇒ 已占用则**跳过回填**并打印 [!] 警告；此时本账号仍能被门户认出来（走
      Odoo 19 规范反向关系 res.users.partner_id → res.partner.user_ids，
      见 controllers/roles.py:_profile_of_current_user 的双向并集口径）。
  ③ 目标档案优先挑「partner 两条链都没挂账号」的（即 docstring 说的「待定」占位
     档案，名字含「待定」的再优先）；一个都挑不到才退回 search([], limit=1)
     （历史行为），并明确提示"该 partner 已被占用、不会回填"。
  ④ 收尾自证：**两条链分别**复核 current_faculty 能否命中，并报该教师名下可见课节数。
     （两条链必须分开报 —— 混在一起报会把「只通了规范反向链」说成
      「partner.user_id 已正确指向」，那正是本缺陷家族的下一个静默假绿。）
"""
import os

env = env
Users = env['res.users'].sudo()
Partner = env['res.partner'].sudo()
Faculty = env['op.faculty'].sudo()

LOGIN = (os.environ.get('TEACHER_LOGIN') or 'teacher@local').strip()
FAC_ID = (os.environ.get('TEACHER_FACULTY_ID') or '').strip()


def chains(partner):
    """该 partner 两条链各自现挂的账号：(partner.user_id 链, res.users.partner_id 链)。

    两者不是同一回事：partner.user_id 在 Odoo 19 是「销售员」列（本仓把它当
    教师登录账号用，见 docstring ①），partner.user_ids 才是 res.users.partner_id
    的规范反向关系。分开返回，任何判断/打印都不许把两条链混成一条。
    """
    return partner.user_id, partner.user_ids[:1]


def pick_faculty():
    """按 ③ 的口径挑目标教师档案，返回 (记录, 挑选方式说明)。"""
    if FAC_ID:
        f = Faculty.browse(int(FAC_ID))
        if not f.exists():
            raise UserError('TEACHER_FACULTY_ID=%s 的教师档案不存在' % FAC_ID)
        return f, 'TEACHER_FACULTY_ID 指定'
    free = [f for f in Faculty.search([], order='id')
            if not any(chains(f.partner_id))]
    if free:
        placeholder = [f for f in free if '待定' in (f.name or '')]
        return (placeholder or free)[0], '两条链都没挂账号的档案中自动挑选'
    return Faculty.search([], limit=1), '退回历史行为 search([], limit=1)'


fac, how = pick_faculty()
if not fac:
    raise UserError('生产上没有 op.faculty 记录，先建教师档案')
partner = fac.partner_id
sales_owner, native_owner = chains(partner)

print('[t] 目标教师档案：faculty id=%s 名=%s partner=%s（挑选方式：%s）'
      % (fac.id, fac.name, partner.id, how))
print('[t] 该档案名下课节数：%d'
      % env['op.session'].sudo().search_count([('faculty_id', '=', fac.id)]))
print('[t] 该 partner 现挂账号：partner.user_id → %s ；res.users.partner_id → %s'
      % (sales_owner.login if sales_owner else '（无）',
         native_owner.login if native_owner else '（无）'))

# ---- 建 / 复用账号 ----
bindable = True
existing = Users.with_context(active_test=False).search(
    [('login', '=', LOGIN)], limit=1)
if existing:
    existing.write({'password': 'demo123', 'active': True})
    user = existing
    print('[t] 已存在，已重置密码并激活：user id=%s login=%s' % (user.id, user.login))
    if user.partner_id.id != partner.id:
        bindable = False
        print('[!] 该账号的 partner 是 id=%s 名=%s，不是目标教师档案的 partner id=%s。'
              % (user.partner_id.id, user.partner_id.name, partner.id))
        print('[!] 不自动改绑，也**不回填** partner.user_id（那会把它挂到一份'
              '不属于它的教师档案上）；请人工确认后再跑。')
else:
    portal = env.ref('base.group_portal')
    user = Users.create({
        'login': LOGIN,
        'partner_id': partner.id,
        'password': 'demo123',
        'group_ids': [(6, 0, [portal.id])],   # Odoo19：字段是 group_ids（不是 groups_id）
        'active': True,
    })
    print('[t] 已创建：user id=%s login=%s' % (user.id, user.login))

# ---- 回填 partner.user_id（= op.faculty.user_id；见 docstring ①②）----
sales_owner = partner.user_id
native_owner = partner.user_ids[:1]
if not bindable:
    print('[!] 跳过回填：账号 partner 与目标档案不一致（见上）。')
elif sales_owner and sales_owner.id != user.id:
    print('[!] 跳过回填：partner %s(id=%s).user_id 已挂在账号 %s(id=%s) 上；'
          % (partner.name, partner.id, sales_owner.login, sales_owner.id))
    print('[!] 强写会顶掉那个账号的教师身份，故不动它。')
    print('[!] 本账号仍可被认出来：门户走双向并集口径，见下方复核链②。')
elif sales_owner and sales_owner.id == user.id:
    print('[t] partner.user_id 已指向本账号（id=%s），无需回填。' % user.id)
else:
    partner.sudo().write({'user_id': user.id})
    print('[t] 已回填 partner.user_id = %s（= op.faculty.user_id，门户老口径据此认教师）'
          % user.id)
    if native_owner:
        print('[t]  （该账号本来已可经 res.users.partner_id → partner.user_ids 命中；'
              '回填是为了让只认 partner.user_id 的既有代码也认它）')

env.cr.commit()
print('[t] 已提交')

# ---- 收尾自证（④）：两条链分开报 ----
u2 = Users.with_context(active_test=False).search([('login', '=', LOGIN)], limit=1)
print('[t] 复核：login=%s active=%s share=%s partner=%s'
      % (u2.login, u2.active, u2.share, u2.partner_id.name))
print('[t] 复核 partner.user_id → %s ；该 partner 的 res.users.partner_id → %s'
      % (u2.partner_id.user_id.login if u2.partner_id.user_id else '（无）',
         u2.partner_id.user_ids[:1].login if u2.partner_id.user_ids else '（无）'))
fac_a = env['op.faculty'].sudo().search([('user_id', '=', u2.id)], limit=1)
fac_b = env['op.faculty'].sudo().search(
    [('partner_id.user_ids', 'in', [u2.id])], limit=1)
print('[t] 复核链① op.faculty(user_id=该用户) → %s' % (fac_a.id or 'None'))
print('[t] 复核链② op.faculty(partner_id.user_ids ∋ 该用户) → %s' % (fac_b.id or 'None'))
hit = fac_a or fac_b
print('[t] 复核结论：current_faculty() 命中 = %s' % (hit.id or 'None'))
if hit:
    print('[t] 该教师名下可见课节数：%d'
          % env['op.session'].sudo().search_count([('faculty_id', '=', hit.id)]))
print('[t] 回滚：把该用户 active=False 即停用（或删除该 res.users 行）')
