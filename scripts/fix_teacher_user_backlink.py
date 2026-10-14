# -*- coding: utf-8 -*-
"""补上 res.partner.user_id 反向指针 —— 程序化建用户时 Odoo 不会回填这一列，
而门户的 current_faculty() 正是靠 op.faculty.user_id（继承自 partner）解析教师身份。

⚠ 2026-09-18 加**占用守卫**（本仓当日同型第二起缺陷的收尾）：
   partner.user_id 只能挂一个账号。若它已挂在**别的**在用账号上，强写会
   把那个账号的教师身份顶掉（老账号反而解析不出教师 = 新造回归）
   ⇒ 已占用则**跳过 + 告警**，绝不抢占。
   不抢占的后路是有的：门户/通知/日历的身份解析已统一为**双向并集**
   （edu_schedule/models/identity.py），该账号仍能经
   res.users.partner_id → res.partner.user_ids 被认出来。

   新建教师账号请优先用 **scripts/create_teacher_account.py**（幂等、自带同一
   守卫、并分别复核两条链）；本脚本保留只为「已建账号，只想补一下回填」
   这一种历史场景。

    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
        -r odoo -w odoo -d edu19 --no-http < scripts/fix_teacher_user_backlink.py
"""
env = env
Users = env['res.users'].sudo()
u = Users.with_context(active_test=False).search([('login', '=', 'teacher@local')], limit=1)
if not u:
    raise UserError('未找到 teacher@local')
p = u.partner_id
print('[fix] 改前：partner %s user_id=%s' % (p.id, p.user_id.id or None))
owner = p.user_id
if owner and owner.id != u.id:
    # 占用守卫：绝不抢占（见 docstring）
    print('[!] 跳过：partner %s(id=%s).user_id 已挂在账号 %s(id=%s) 上；'
          % (p.name, p.id, owner.login, owner.id))
    print('[!] 强写会把那个账号的教师身份顶掉，故不动它。')
    print('[!] 该账号仍可被认出来：门户走双向并集口径'
          '（res.users.partner_id → partner.user_ids）。')
else:
    if owner.id != u.id:
        p.sudo().write({'user_id': u.id})
    env.cr.commit()
    p = env['res.partner'].sudo().browse(p.id)
    print('[fix] 改后：partner %s user_id=%s' % (p.id, p.user_id.id or None))
# 复核：两条链**分别**报（混在一起会把「只通了规范反向链」说成「已回填」）
fac_a = env['op.faculty'].sudo().search([('user_id', '=', u.id)], limit=1)
fac_b = env['op.faculty'].sudo().search(
    [('partner_id.user_ids', 'in', [u.id])], limit=1)
print('[fix] 链① op.faculty(user_id=%s) → %s' % (u.id, fac_a.id or 'None'))
print('[fix] 链② op.faculty(partner_id.user_ids ∋ %s) → %s' % (u.id, fac_b.id or 'None'))
hit = fac_a or fac_b
print('[fix] current_faculty 口径复核：命中 = %s' % (hit.id or 'None'))
print('[fix] 该教师课节数：%d'
      % env['op.session'].sudo().search_count([('faculty_id', '=', hit.id)])
      if hit else '[fix] n/a')
