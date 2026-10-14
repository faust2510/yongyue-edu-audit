# -*- coding: utf-8 -*-
"""「新建家长 / 删除有家长的学生」两条基座路径的行为级断言（任务 G，2026-09-17）。

被测缺陷（基座 openeducat_parent/models/parent.py，本仓以 edu_portal 的
models/parent_link_fix.py 覆盖）：
  ① OpParent.create 新建伙伴分支把 mobile 写进不存在的 op.parent.phone
     → ValueError: Invalid field 'phone' in 'op.parent'（基座第 93 行 → 第 95 行炸）；
  ② OpStudent.unlink 用无保护的 list.remove(record.user_id.id)
     → ValueError: list.remove(x): x not in list（基座第 208 行）。

三段模板（docs/dev-workflow.md）：
  ① 绕过被测路径造前置数据（ORM 建学生/家长/门户账号，不点后台界面）
  ② 读真正的产物（伙伴与 op.parent 的字段值、家长侧 child_ids 清理前后读数）
  ③ 清场并断言 leftover=0 + 计数回到开工前

⚠ 造数据时每条 create 都要给**互不相同**的 name/email/mobile：基座 create 的
「找伙伴」查询是 name OR email OR phone（email 缺省时 ('email','=',None) 会命中
任意无邮箱伙伴），撞上已有伙伴就会去改写别人的档案并在 unique(name) 约束上炸。

用法：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 \
        --db_host=db -r odoo -w odoo --no-http \
        < tests/smoke/parent_student_lifecycle.py
"""
import traceback

TAG = '【临时·冒烟G】'
STU_NOPORTAL = TAG + '学生·无账号'
STU_NOPARENT2 = TAG + '学生·无账号B'
STU_WITHACC = TAG + '学生·有账号'
STU_PLAIN = TAG + '学生·无家长'
USER_STU = 'smoke_g_stu_tmp'
USER_PAR = 'smoke_g_par_tmp'

ok = fail = 0
notes = []


def check(name, cond, detail=''):
    global ok, fail
    if cond:
        ok += 1
        print('PASS | %s | %s' % (name, detail))
    else:
        fail += 1
        print('FAIL | %s | %s' % (name, detail))


def reading(name, detail):
    print('读数 | %s | %s' % (name, detail))


def attempt(fn):
    """在 savepoint 里跑一条路径；失败只回滚+记录，不中断整份脚本。"""
    try:
        with env.cr.savepoint():
            return fn(), None
    except Exception as exc:
        traceback.print_exc()
        env.invalidate_all()
        return None, exc


def first_line(exc):
    return '%s: %s' % (type(exc).__name__, str(exc).splitlines()[0]) if exc else 'ok'


P = env['op.parent']
S = env['op.student']
Partner = env['res.partner']
Users = env['res.users']
REL = S._fields['parent_ids'].relation          # 家长↔学生 m2m 关联表
admin = env(user=2, su=False)
rel = env['op.parent.relationship'].search([], limit=1)
assert rel, '没有 op.parent.relationship 记录，先跑种子'
par0, stu0 = P.search_count([]), S.search_count([])
print('开工前计数：op.parent=%d op.student=%d' % (par0, stu0))

print()
print('=== ① 前置数据 ===')
stu_np = S.create({'name': STU_NOPORTAL})            # 无门户账号（本地 4 名学生有 3 名如此）
stu_np2 = S.create({'name': STU_NOPARENT2})
stu_plain = S.create({'name': STU_PLAIN})
portal_grp = env.ref('base.group_portal')
u_stu = Users.create({'name': STU_WITHACC, 'login': USER_STU,
                      'group_ids': [(6, 0, [portal_grp.id])]})
p_stu = u_stu.partner_id
u_par = Users.create({'name': TAG + '家长账号', 'login': USER_PAR,
                      'group_ids': [(6, 0, [portal_grp.id])]})
p_par = u_par.partner_id
p_par.write({'user_id': u_par.id})                    # 与基座 create_parent_user 的写法一致
stu_acc = S.create({'name': STU_WITHACC, 'partner_id': p_stu.id, 'user_id': u_stu.id})
env.cr.flush()
print('  学生 %s(无账号) / %s(有账号 user=%s) / %s(无家长)；伙伴 %s(学生侧) %s(家长侧)；账号 user=%s,%s'
      % (stu_np.id, stu_acc.id, u_stu.id, stu_plain.id, p_stu.id, p_par.id, u_stu.id, u_par.id))

print()
print('=== ②-A 新建家长：新伙伴分支（改前 ValueError: Invalid field phone） ===')
par_a, exc = attempt(lambda: admin['op.parent'].create({
    'name': TAG + '伙伴A（新建）', 'relationship_id': rel.id,
    'student_ids': [(6, 0, [stu_np.id])],
    'mobile': '13000000001', 'email': 'smoke_g_a@example.invalid'}))
if exc:
    check('新建家长不报错', False, first_line(exc))
else:
    env.invalidate_all()
    check('新建家长不报错', True, 'op.parent id=%s' % par_a.id)
    check('伙伴被创建且认领 is_parent', par_a.name.name == TAG + '伙伴A（新建）' and par_a.name.is_parent,
          'name=%r is_parent=%s' % (par_a.name.name, par_a.name.is_parent))
    check('伙伴 phone/email 落库正确',
          par_a.name.phone == '13000000001' and par_a.name.email == 'smoke_g_a@example.invalid',
          'phone=%r email=%r' % (par_a.name.phone, par_a.name.email))
    # ↓ 基座把 mobile 写成了不存在的 phone：这里必须读到值，不能只验「不报错」
    check('op.parent.mobile 值正确（原缺陷字段）', par_a.mobile == '13000000001',
          'mobile=%r' % par_a.mobile)
    check('op.parent.email / 学生关联正确',
          par_a.email == 'smoke_g_a@example.invalid' and par_a.student_ids.ids == [stu_np.id],
          'email=%r student_ids=%s' % (par_a.email, par_a.student_ids.ids))

print()
print('=== ②-B 已有伙伴分支（传已有伙伴 id → 回填 is_parent / email / phone） ===')
par_b, exc = attempt(lambda: admin['op.parent'].create({
    'name': p_stu.id, 'relationship_id': rel.id,
    'student_ids': [(6, 0, [stu_np.id])],
    'mobile': '13000000002', 'email': 'smoke_g_b@example.invalid'}))
if exc:
    check('已有伙伴分支可用', False, first_line(exc))
else:
    env.invalidate_all()
    check('已有伙伴分支可用', True, 'op.parent id=%s name(伙伴)=%s' % (par_b.id, par_b.name.id))
    check('既有伙伴被标记 is_parent、phone/email 回填',
          p_stu.is_parent and p_stu.phone == '13000000002' and p_stu.email == 'smoke_g_b@example.invalid',
          'is_parent=%s phone=%r email=%r' % (p_stu.is_parent, p_stu.phone, p_stu.email))

print()
print('=== ②-F 批量新建（create 一次收到多条 vals）===')
pars, exc = attempt(lambda: admin['op.parent'].create([
    {'name': TAG + '伙伴I（批量1）', 'relationship_id': rel.id,
     'student_ids': [(6, 0, [stu_np.id])], 'mobile': '13000000021',
     'email': 'smoke_g_i1@example.invalid'},
    {'name': TAG + '伙伴J（批量2）', 'relationship_id': rel.id,
     'student_ids': [(6, 0, [stu_np.id])], 'mobile': '13000000022',
     'email': 'smoke_g_i2@example.invalid'},
]))
if exc:
    check('批量新建两条家长成功', False, first_line(exc))
else:
    env.invalidate_all()
    rows = P.browse(pars.ids)
    check('批量新建两条家长成功（含各自 mobile 落库）',
          len(rows) == 2 and sorted(rows.mapped('mobile')) == ['13000000021', '13000000022'],
          'ids=%s mobile=%s' % (rows.ids, rows.mapped('mobile')))

print()
print('=== ②-C 删除有家长的学生 ===')
# C1：学生无门户账号 —— 上报的那一种（基座第 208 行 remove(False)）
par_c, exc = attempt(lambda: admin['op.parent'].create({
    'name': TAG + '伙伴C（C1用）', 'relationship_id': rel.id,
    'student_ids': [(6, 0, [stu_np2.id])], 'mobile': '13000000003'}))
if exc:
    check('C1 前置：家长建好', False, first_line(exc))
else:
    before = par_c.user_id.child_ids.ids
    _, exc = attempt(lambda: stu_np2.unlink())
    env.invalidate_all()
    if exc:
        check('删除「有家长、无账号」的学生成功', False, first_line(exc))
        notes.append('C1 学生 %s 未删掉（unlink 失败）' % stu_np2.id)
    else:
        after = par_c.user_id.child_ids.ids
        check('删除「有家长、无账号」的学生成功', not S.browse(stu_np2.id).exists(),
              'student %s 已删' % stu_np2.id)
        check('家长侧关联读数（无账号 ⇒ 无可清理，读数保持不变）',
              before == after == [], 'child_ids before=%s after=%s' % (before, after))

# C2：学生有门户账号、且确在家长 user 的 child_ids 里 → 删除时必须清掉这条关联
par_d, exc = attempt(lambda: admin['op.parent'].create({
    'name': p_par.id, 'relationship_id': rel.id, 'student_ids': [(6, 0, [stu_acc.id])],
    'user_id': u_par.id}))
if exc:
    check('C2 前置：家长建好（带 op.parent.user_id）', False, first_line(exc))
else:
    admin['res.users'].browse(u_par.id).write({'child_ids': [(6, 0, [u_stu.id])]})
    env.invalidate_all()
    before = par_d.user_id.child_ids.ids
    check('C2 前置：家长 user 的 child_ids 含学生账号', u_stu.id in before, 'child_ids=%s' % before)
    _, exc = attempt(lambda: stu_acc.unlink())
    env.invalidate_all()
    if exc:
        check('删除「有家长、有账号」的学生成功', False, first_line(exc))
        notes.append('C2 学生 %s 未删掉（unlink 失败）' % stu_acc.id)
    else:
        after = par_d.user_id.child_ids.ids
        check('删除「有家长、有账号」的学生成功', not S.browse(stu_acc.id).exists(),
              'student %s 已删' % stu_acc.id)
        check('家长侧关联被清理（读家长 user 的 child_ids 前后）', u_stu.id not in after,
              'before=%s → after=%s' % (before, after))

print()
print('=== ②-D 不回归：删无家长的学生 + op.student 常规写读 ===')
_, exc = attempt(lambda: stu_plain.unlink())
check('删除无家长学生仍成功', not exc and not S.browse(stu_plain.id).exists(), first_line(exc))
s_rt = S.create({'name': STU_PLAIN + '·B'})
s_rt.write({'email': 'reg@example.invalid'})
env.invalidate_all()
check('op.student 常规写/读不受影响', S.browse(s_rt.id).email == 'reg@example.invalid',
      'email=%r' % S.browse(s_rt.id).email)
s_rt.unlink()

print()
print('=== ②-E 四角色 ===')
# 教师/学生/家长：读数（只记录，不计分）—— 他们本来就进不了后台档案层
for login, tag_mail, tag_tel in [('faculty@local', 'smoke_g_fac@example.invalid', '13000000012'),
                                 ('stu@local', 'smoke_g_ss@example.invalid', '13000000013'),
                                 ('parent@local', 'smoke_g_pp@example.invalid', '13000000014')]:
    u = Users.search([('login', '=', login)], limit=1)
    if not u:
        reading(login, '账号不存在，跳过')
        continue
    e = env(user=u.id, su=False)
    _, exc = attempt(lambda: e['op.parent'].create({
        'name': TAG + '角色探针·' + login, 'relationship_id': rel.id,
        'student_ids': [(6, 0, [stu_np.id])], 'mobile': tag_tel, 'email': tag_mail}))
    env.invalidate_all()
    reading('%s（uid=%s / %s）建家长' % (login, u.id, '教务' if 'back' in login else '非教务'),
            first_line(exc))

# 教务（backoffice@local）走同样两条路径
bo = Users.search([('login', '=', 'backoffice@local')], limit=1)
if bo:
    e = env(user=bo.id, su=False)
    par_e, exc = attempt(lambda: e['op.parent'].create({
        'name': TAG + '伙伴E（教务建）', 'relationship_id': rel.id,
        'student_ids': [(6, 0, [stu_np.id])],
        'mobile': '13000000015', 'email': 'smoke_g_bo@example.invalid'}))
    env.invalidate_all()
    check('教务新建家长（新伙伴分支）成功', not exc,
          first_line(exc) if exc else 'op.parent id=%s mobile=%r' % (par_e.id, par_e.mobile))
    check('教务建的家长 mobile 落库正确', not exc and par_e.mobile == '13000000015',
          'mobile=%r' % (par_e.mobile if par_e else None))
    st = S.create({'name': TAG + '学生·教务删'})
    par_f, exc = attempt(lambda: e['op.parent'].create({
        'name': TAG + '伙伴F（教务建）', 'relationship_id': rel.id,
        'student_ids': [(6, 0, [st.id])], 'mobile': '13000000016',
        'email': 'smoke_g_f2@example.invalid'}))
    if exc:
        check('教务删「有家长学生」前置', False, first_line(exc))
    else:
        _, exc = attempt(lambda: st.unlink())
        env.invalidate_all()
        check('教务删除「有家长、无账号」的学生成功',
              not exc and not S.browse(st.id).exists(), first_line(exc))
    # 读数（不计分）：家长伙伴已绑门户账号时，基座 create 末尾要写 res.users.child_ids
    # ——「同一份数据、只换身份」的对照，说明这是四层权限边界（L2 教务没有 res.users 写权限），
    # 不是本次那两个基座缺陷。
    st2 = S.create({'name': TAG + '学生·权限探针', 'partner_id': p_stu.id, 'user_id': u_stu.id})
    p_bo_admin = Partner.create({'name': TAG + '伙伴G（admin 对照）'})
    p_bo_admin.write({'user_id': u_par.id})   # 与基座 create_parent_user 同写法：伙伴 user_id = 家长账号
    _, exc = attempt(lambda: env(user=2, su=False)['op.parent'].create({
        'name': p_bo_admin.id, 'relationship_id': rel.id, 'student_ids': [(6, 0, [st2.id])],
        'user_id': u_par.id}))
    env.invalidate_all()
    reading('家长伙伴已绑账号（写 res.users）：admin', first_line(exc))
    p_bo_bo = Partner.create({'name': TAG + '伙伴H（教务 对照）'})
    p_bo_bo.write({'user_id': u_par.id})
    _, exc = attempt(lambda: e['op.parent'].create({
        'name': p_bo_bo.id, 'relationship_id': rel.id, 'student_ids': [(6, 0, [st2.id])],
        'user_id': u_par.id}))
    env.invalidate_all()
    reading('家长伙伴已绑账号（写 res.users）：教务', first_line(exc))

print()
print('=== ③ 清场 + leftover=0 ===')
env.cr.rollback()
stu_ids = S.with_context(active_test=False).search([('name', 'like', TAG + '%')]).ids
par_ids = P.with_context(active_test=False).search([('name.name', 'like', TAG + '%')]).ids
if stu_ids:
    env.cr.execute('DELETE FROM ' + REL + ' WHERE op_student_id IN %s', (tuple(stu_ids),))
if par_ids:
    env.cr.execute('DELETE FROM ' + REL + ' WHERE op_parent_id IN %s', (tuple(par_ids),))
env.invalidate_all()
S.browse(stu_ids).unlink()
P.browse(par_ids).unlink()
Users.with_context(active_test=False).search(
    [('login', 'in', [USER_STU, USER_PAR])]).unlink()
Partner.with_context(active_test=False).search([('name', 'like', TAG + '%')]).unlink()
env.cr.commit()

left_p = P.search_count([('name.name', 'like', TAG + '%')])
left_s = S.with_context(active_test=False).search_count([('name', 'like', TAG + '%')])
left_r = Partner.with_context(active_test=False).search_count([('name', 'like', TAG + '%')])
left_u = Users.with_context(active_test=False).search_count([('login', 'in', [USER_STU, USER_PAR])])
env.cr.execute('SELECT count(*) FROM ' + REL + ' rel JOIN op_parent p ON p.id = rel.op_parent_id '
               'JOIN res_partner r ON r.id = p.name WHERE r.name LIKE %s', (TAG + '%',))
left_link = env.cr.fetchone()[0]
check('残留=0（op.parent / op.student / res.partner / res.users / 关联表）',
      left_p == left_s == left_r == left_u == left_link == 0,
      'parent=%d student=%d partner=%d user=%d link=%d'
      % (left_p, left_s, left_r, left_u, left_link))
check('计数回到开工前（未污染他人数据）',
      (P.search_count([]), S.search_count([])) == (par0, stu0),
      'op.parent %d→%d / op.student %d→%d'
      % (par0, P.search_count([]), stu0, S.search_count([])))

print()
for n in notes:
    print('备注 | %s' % n)
print('合计：PASS %d / FAIL %d' % (ok, fail))
if fail:
    raise SystemExit(1)
