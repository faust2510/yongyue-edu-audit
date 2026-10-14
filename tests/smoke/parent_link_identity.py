# -*- coding: utf-8 -*-
"""任务 H：基座 openeducat_parent「关联写错对象」三处缺陷的前后对照脚本。

被测缺陷（基座 openeducat_erp/openeducat_parent/models/parent.py，本仓用
custom_addons/edu_portal/models/parent_link_fix.py 覆盖）：

  ① 模糊搜索误认（数据污染）—— OpParent.create 基座 68-73 行
     ('email','=',parent_email) / ('phone','=',parent_mobile) 在参数为空时退化成
     「该字段为空的任意伙伴」，于是 name 完全对不上的无关联系人被 is_parent=True +
     回填 email/phone，op.parent 挂到它身上；第二次再撞 unique(name) → UniqueViolation。
  ② 读写对象错位 —— OpStudent.write 基座 197 读 parent_id.user_id、199 写
     parent_id.name.user_id；两个 user 不同时，写入落到别的账号上。
  ③ REPLACE 丢兄弟 —— 同一条路径：parent.user_id 为空而 name.user_id 有值时，
     起点读到空列表 → 整体 REPLACE 回写把那个账号原有的其它孩子清空。
 ④ （同型）OpStudent.unlink 基座 207 读 / 209 写 —— 删学生时清理落到别的账号上，
     家长真正的账号保留已删学生的僵尸关联。

本脚本是「红 → 绿」对照：修复前跑，②③④ 与 ① 对应用例 FAIL（即复现）；
修复后跑，全部 PASS。每处读数都打印 before/after 原值。

用法：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 \
        --db_host=db -r odoo -w odoo --no-http \
        < tests/smoke/parent_link_identity.py
"""
import traceback

TAG = '【临时·冒烟H】'
# 前缀 '!'（ASCII 33）排序在所有既有伙伴名之前 ⇒ res.partner._order = complete_name ASC
# 下，「空条件搜索」这一枪必然打在这条无关联系人身上（可复现、可断言）。
CANARY_NAME = '!。【临时·冒烟H】无关联系人（无邮箱无电话）'
USER_PREFIX = 'smoke_h_'

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


class _Rollback(Exception):
    """哨兵异常：在 savepoint 里跑完一个场景后强制回滚，避免污染后续场景。"""


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


P = env['op.parent'].sudo()
S = env['op.student'].sudo()
Partner = env['res.partner'].sudo()
Users = env['res.users'].sudo()
REL_TABLE = S._fields['parent_ids'].relation
PORTAL = env.ref('base.group_portal')
rel = env['op.parent.relationship'].sudo().search([], limit=1)
assert rel, '没有 op.parent.relationship 记录，先跑种子'

par0, stu0 = P.search_count([]), S.search_count([])
par_ids0 = set(Partner.with_context(active_test=False).search([('is_parent', '=', True)]).ids)
print('开工前计数：op.parent=%d op.student=%d res.partner=%d is_parent 伙伴=%d'
      % (par0, stu0, Partner.search_count([]), len(par_ids0)))


def mkuser(login, name):
    return Users.create({'name': name, 'login': USER_PREFIX + login,
                         'group_ids': [(6, 0, [PORTAL.id])]})


def is_parent_ids():
    return set(Partner.with_context(active_test=False).search([('is_parent', '=', True)]).ids)


print()
print('=== ⑦ 四角色读数（先跑：此时事务里只有基线数据，前后必须逐字一致）===')
ROLE_LOGINS = [('admin', 'admin'), ('backoffice@local', '教务 backoffice@local'),
               ('faculty@local', '教师 faculty@local'), ('stu@local', '学生 stu@local'),
               ('parent@local', '学生家长 parent@local')]
stu_role = S.create({'name': TAG + '学生·角色探针'})
for idx, (login, label) in enumerate(ROLE_LOGINS):
    u = Users.search([('login', '=', login)], limit=1)
    if not u:
        reading('⑦ ' + label, '账号不存在，跳过')
        continue
    e = env(user=u.id, su=False)
    seen = 0
    try:
        seen = e['op.parent'].search_count([])
    except Exception as exc:
        seen = 'ERR:%s' % type(exc).__name__
    _, exc = attempt(lambda: e['op.parent'].create({
        'name': TAG + '角色探针·' + login, 'relationship_id': rel.id,
        'student_ids': [(6, 0, [stu_role.id])],
        'email': 'h_role_%d@example.invalid' % idx,
        'mobile': '1310000010%d' % idx}))
    env.invalidate_all()
    reading('⑦ %s（uid=%s）建家长 / 可见 op.parent 数' % (label, u.id),
            '%s ｜ seen=%s' % (first_line(exc), seen))

print()
print('=== ① 模糊搜索误认（数据污染）：空 email/mobile 的 create ===')
# 场景整体放在 savepoint 里读完即回滚：不干扰后面「正向认领路径」的场景（否则
# canary 排在最前，会把后面按 email/name 的正常认领也一并劫走，读不出正向结论）。
try:
    with env.cr.savepoint():
        pre_ids = set(Partner.with_context(active_test=False).search([]).ids)
        ip_before = is_parent_ids() & pre_ids
        canary = Partner.create({'name': CANARY_NAME})   # 无关联系人：无 email / 无 phone
        pre_ids.add(canary.id)
        stu_a = S.create({'name': TAG + '学生A'})
        probe = Partner.search(['|', '|', ('name', '=', TAG + '张三A'),
                                ('email', '=', None), ('phone', '=', None)], limit=1)
        reading('① 前置：canary（无关联系人）', 'id=%s name=%r email=%r phone=%r is_parent=%s'
                % (canary.id, canary.name, canary.email, canary.phone, canary.is_parent))
        reading('① 前置：基座那条搜索会命中谁（同域 limit=1）',
                'id=%s name=%r（≠ 请求的 %r）' % (probe.id, probe.name, TAG + '张三A'))

        par_a, exc = attempt(lambda: P.create({
            'name': TAG + '张三A', 'relationship_id': rel.id,
            'student_ids': [(6, 0, [stu_a.id])], 'mobile': '13100000001'}))
        env.invalidate_all()
        if exc:
            check('①-A 空 email 的 create 能建成家长', False, first_line(exc))
        else:
            claimed = Partner.browse(par_a.name.id)
            reading('①-A 建成后 op.parent 指向', 'op.parent id=%s → 伙伴 id=%s name=%r'
                    % (par_a.id, claimed.id, claimed.name))
            reading('①-A canary 读数（污染后）', 'is_parent=%s phone=%r'
                    % (canary.is_parent, canary.phone))
            check('①-A 没有把无关联系人认领成家长（op.parent 指向请求的名字）',
                  claimed.name == TAG + '张三A',
                  'op.parent 指向 %r（请求 %r）' % (claimed.name, TAG + '张三A'))
            # 只看「改动前就存在的伙伴」：本次新建伙伴被标 is_parent 是基座的正常语义，
            # 被污染的是既有的无关联系人。
            touched = is_parent_ids() & pre_ids
            check('①-A 无关联系人未被标记 is_parent（既有伙伴的 is_parent 集合不变）',
                  canary.id not in is_parent_ids() and touched == ip_before,
                  'canary.is_parent=%s ｜ 既有伙伴中 is_parent %d→%d'
                  % (canary.is_parent, len(ip_before), len(touched)))
            check('①-A 无关联系人 phone 未被回填', not canary.phone,
                  'canary.phone=%r' % (canary.phone,))

        # 第二次空条件 create：修复前必然再次命中同一条（已认领）→ unique(name) 撞车
        stu_b = S.create({'name': TAG + '学生B'})
        par_b, exc = attempt(lambda: P.create({
            'name': TAG + '张三B', 'relationship_id': rel.id,
            'student_ids': [(6, 0, [stu_b.id])]}))
        env.invalidate_all()
        if exc:
            check('①-B 第二次空条件 create 不撞 unique(name)', False, first_line(exc))
        else:
            check('①-B 第二次空条件 create 不撞 unique(name)',
                  par_b.name.name == TAG + '张三B', 'op.parent id=%s → %r'
                  % (par_b.id, par_b.name.name))

        raise _Rollback()
except _Rollback:
    env.invalidate_all()
    reading('① 场景回滚', 'canary 与 A/B 两段已从本事务撤回（不污染后续场景）')

# ①-C：三条搜索条件全空（name 也没给）——不得退化成「匹配任意记录」。
# 单独一个 savepoint：canary 已回滚，修复前这一枪会打在库里第一条无邮箱伙伴上。
try:
    with env.cr.savepoint():
        ip_b4 = is_parent_ids()
        stu_c = S.create({'name': TAG + '学生C'})
        par_c, exc = attempt(lambda: P.create({
            'name': None, 'relationship_id': rel.id,
            'student_ids': [(6, 0, [stu_c.id])]}))
        env.invalidate_all()
        unrelated = is_parent_ids() - ip_b4
        detail = (first_line(exc) if exc
                  else 'op.parent id=%s → 伙伴 %r' % (par_c.id, par_c.name.name))
        reading('①-C 结果', '%s ｜ 被新标记 is_parent 的既有伙伴=%s'
                % (detail, sorted(unrelated)))
        check('①-C 三条搜索都为空：不误认任意伙伴、也不产生指向别人的家长',
              not unrelated, '新增 is_parent 伙伴=%s ｜ %s' % (sorted(unrelated), detail))
        raise _Rollback()
except _Rollback:
    env.invalidate_all()

print()
print('=== ② 正向：按 email / name 的认领路径仍然认领到正确的伙伴 ===')
stu_m = S.create({'name': TAG + '学生M'})
p_email = Partner.create({'name': TAG + '邮箱认领·伙伴', 'email': 'h_target@example.invalid'})
par_m, exc = attempt(lambda: P.create({
    'name': TAG + '名字完全不同·邮箱认领', 'relationship_id': rel.id,
    'student_ids': [(6, 0, [stu_m.id])], 'email': 'h_target@example.invalid'}))
env.invalidate_all()
if exc:
    check('②-A 按 email 认领到正确的伙伴', False, first_line(exc))
else:
    reading('②-A op.parent 指向', 'id=%s name=%r（目标伙伴 id=%s）'
            % (par_m.name.id, par_m.name.name, p_email.id))
    check('②-A 按 email 认领到正确的伙伴', par_m.name.id == p_email.id,
          'op.parent.name=%r（应为 %r）' % (par_m.name.name, p_email.name))

stu_n = S.create({'name': TAG + '学生N'})
p_same = Partner.create({'name': TAG + '同名伙伴'})
par_n, exc = attempt(lambda: P.create({
    'name': TAG + '同名伙伴', 'relationship_id': rel.id,
    'student_ids': [(6, 0, [stu_n.id])]}))
env.invalidate_all()
if exc:
    check('②-B 按 name 认领到同名伙伴（不新建重复伙伴）', False, first_line(exc))
else:
    reading('②-B op.parent 指向', 'id=%s name=%r（同名伙伴 id=%s）'
            % (par_n.name.id, par_n.name.name, p_same.id))
    check('②-B 按 name 认领到同名伙伴（不新建重复伙伴）', par_n.name.id == p_same.id,
          'op.parent.name=%r（应为 %r）' % (par_n.name.name, p_same.name))

print()
print('=== ③ OpStudent.write：读 parent.user_id 却写 parent.name.user_id（两 user 不同）===')
u_a = mkuser('ua', TAG + '账号A（伙伴 owner）')
u_b = mkuser('ub', TAG + '账号B（家长 op.parent.user_id）')
p_x = u_a.partner_id
reading('③ 前置：Odoo 19 语义', 'partner.user_id 是「销售员」字段（core res_partner.py:229-236），'
        '新建门户账号不会自动写它：u_a.partner_id.user_id=%r（user_ids=%s）'
        % (p_x.user_id.id, p_x.user_ids.ids))
# 基座自己就是这么写 partner.user_id 的（parent.py:151 create_parent_user），
# 这里照基座的写法构造「name.user_id 另有其人」的既有数据。
p_x.write({'user_id': u_a.id})
env.invalidate_all()
stu_y = S.create({'name': TAG + '学生Y'})
par_x, exc = attempt(lambda: P.create({
    'name': p_x.id, 'user_id': u_b.id, 'relationship_id': rel.id,
    'student_ids': [(6, 0, [stu_y.id])]}))
env.invalidate_all()
have_par_x = not exc
if exc:
    check('③ 前置：家长（user_id≠name.user_id）建好', False, first_line(exc))
else:
    u_a.child_ids = [(6, 0, [])]
    u_b.child_ids = [(6, 0, [])]
    env.invalidate_all()
    reading('③ 前置：两个账号不同', 'op.parent.user_id=%s / name.user_id=%s（a=%s b=%s）'
            % (par_x.user_id.id, par_x.name.user_id.id, u_a.id, u_b.id))
    u_stu_y = mkuser('ustuy', TAG + '学生Y的账号')
    stu_y.write({'user_id': u_stu_y.id})
    env.invalidate_all()
    a_after = u_a.child_ids.ids
    b_after = u_b.child_ids.ids
    reading('③ 写入后 child_ids', 'name.user_id(u_a=%s)=%s ｜ op.parent.user_id(u_b=%s)=%s'
            % (u_a.id, a_after, u_b.id, b_after))
    check('③ 学生账号挂到 op.parent.user_id（家长真正的登录账号）',
          u_stu_y.id in b_after, 'u_b.child_ids=%s 期望含 %s' % (b_after, u_stu_y.id))
    check('③ name.user_id 未被误写', a_after == [],
          'u_a.child_ids=%s 期望 []' % (a_after,))

print()
print('=== ④ REPLACE 丢兄弟：parent.user_id 为空、name.user_id 有值且有其它孩子 ===')
u_c = mkuser('uc', TAG + '账号C（伙伴 owner，op.parent.user_id 空）')
u_lost = mkuser('ulost', TAG + '账号C原有的孩子')
u_c.child_ids = [(6, 0, [u_lost.id])]
p_z = u_c.partner_id
p_z.write({'user_id': u_c.id})            # 基座 parent.py:151 的写法（name.user_id 另有其人）
env.invalidate_all()
stu_z = S.create({'name': TAG + '学生Z'})
par_z, exc = attempt(lambda: P.create({
    'name': p_z.id, 'relationship_id': rel.id, 'student_ids': [(6, 0, [stu_z.id])]}))
env.invalidate_all()
if exc:
    check('④ 前置：op.parent.user_id 为空的家长建好', False, first_line(exc))
else:
    before = u_c.child_ids.ids
    reading('④ 前置：name.user_id 账号原有孩子', 'u_c=%s child_ids=%s' % (u_c.id, before))
    u_stu_z = mkuser('usuz', TAG + '学生Z的账号')
    stu_z.write({'user_id': u_stu_z.id})
    env.invalidate_all()
    after = u_c.child_ids.ids
    reading('④ 写入后 u_c.child_ids', '%s（原有孩子 %s / 新学生账号 %s）'
            % (after, u_lost.id, u_stu_z.id))
    check('④ REPLACE 不丢兄弟：原有孩子仍在', u_lost.id in after, 'after=%s' % (after,))
    # 家长没有 op.parent.user_id ⇒ 没有账号可同步：修好后**不动** name.user_id 那个账号
    # （「该回写」的正向证据在 ③：家长有账号时学生账号确实挂上去）。
    check('④ 未再误写 name.user_id 账号（家长无账号 ⇒ 无同步目标）',
          u_stu_z.id not in after, 'after=%s' % (after,))

print()
print('=== ⑤ OpStudent.unlink：读 parent.user_id 却写 parent.name.user_id ===')
if have_par_x:
    u_other_a = mkuser('uoa', TAG + '账号A上别的孩子')
    u_b.child_ids = [(6, 0, [u_stu_y.id])]
    u_a.child_ids = [(6, 0, [u_other_a.id])]
    env.invalidate_all()
    reading('⑤ 删前', 'u_b(op.parent.user_id) child_ids=%s ｜ u_a(name.user_id) child_ids=%s'
            % (u_b.child_ids.ids, u_a.child_ids.ids))
    _, unlink_exc = attempt(lambda: stu_y.unlink())
    env.invalidate_all()
    if unlink_exc:
        check('⑤ 删除有家长的学生成功', False, first_line(unlink_exc))
    else:
        b_after = u_b.child_ids.ids
        a_after = u_a.child_ids.ids
        reading('⑤ 删后', 'u_b child_ids=%s ｜ u_a child_ids=%s' % (b_after, a_after))
        check('⑤ 清理落在 op.parent.user_id（家长真正账号）', u_stu_y.id not in b_after,
              'u_b.child_ids=%s' % (b_after,))
        check('⑤ 未误清 name.user_id 账号上的其它孩子', u_other_a.id in a_after,
              'u_a.child_ids=%s 期望仍含 %s' % (a_after, u_other_a.id))
else:
    check('⑤ 前置缺失（③ 未建成家长）', False, '③ 失败，⑤ 无法进行')

print()
print('=== ⑥ 不回归：G 修的两条路径 + 正向读写读数 ===')
# G1：新建家长（新伙伴分支）—— 基座 vals['phone'] 缺陷由 G 修掉
stu_g = S.create({'name': TAG + '学生G'})
par_g, exc = attempt(lambda: P.create({
    'name': TAG + '伙伴G（新建）', 'relationship_id': rel.id,
    'student_ids': [(6, 0, [stu_g.id])], 'mobile': '13100000002',
    'email': 'h_g@example.invalid'}))
env.invalidate_all()
if exc:
    check('⑥-A 不回归：新建家长不报错', False, first_line(exc))
else:
    check('⑥-A 不回归：新建家长不报错（mobile 落在 op.parent.mobile）',
          par_g.mobile == '13100000002' and par_g.name.name == TAG + '伙伴G（新建）',
          'op.parent id=%s mobile=%r name=%r' % (par_g.id, par_g.mobile, par_g.name.name))

# G2：删「有家长、无账号」的学生（G 修的 remove 守卫）
stu_h = S.create({'name': TAG + '学生H'})
par_h, exc = attempt(lambda: P.create({
    'name': TAG + '伙伴H（新建）', 'relationship_id': rel.id,
    'student_ids': [(6, 0, [stu_h.id])], 'mobile': '13100000003'}))
if exc:
    check('⑥-B 不回归：删「有家长、无账号」的学生', False, first_line(exc))
else:
    _, exc = attempt(lambda: stu_h.unlink())
    env.invalidate_all()
    check('⑥-B 不回归：删「有家长、无账号」的学生', not exc and not S.browse(stu_h.id).exists(),
          first_line(exc))

# 正向：家长账号两侧同名（user_id == name.user_id）时，create 回写 / unlink 清理都要照旧
u_e = mkuser('ue', TAG + '账号E（两边同一个 user）')
p_e = u_e.partner_id
stu_e = S.create({'name': TAG + '学生E'})
u_stu_e = mkuser('ustue', TAG + '学生E的账号')
stu_e.write({'user_id': u_stu_e.id})
env.invalidate_all()
par_e, exc = attempt(lambda: P.create({
    'name': p_e.id, 'user_id': u_e.id, 'relationship_id': rel.id,
    'student_ids': [(6, 0, [stu_e.id])]}))
env.invalidate_all()
if exc:
    check('⑥-C 不回归：建家长成功', False, first_line(exc))
else:
    c_after = u_e.child_ids.ids
    # 只报告不修（同型）：基座 create 末尾 97-100 的守卫是 name.user_id（Odoo 19 的销售员），
    # 通常为 False ⇒ 这条「回写」是死代码；本任务不修它，如实读数。
    reading('⑥-C create 后 u_e.child_ids（基座守卫 name.user_id 的后果）', '%s' % (c_after,))
    notes.append('同型未修（只报告）：基座 parent.py:98 守卫 record.name.user_id '
                 '⇒ create 后家长账号 child_ids=%s（Odoo 19 下该守卫基本恒为 False）' % (c_after,))
    check('⑥-C 不回归：建家长成功', par_e.id > 0, 'op.parent id=%s' % par_e.id)
    _, exc = attempt(lambda: stu_e.unlink())
    env.invalidate_all()
    d_after = u_e.child_ids.ids
    reading('⑥-D unlink 后 u_e.child_ids', '%s' % (d_after,))
    check('⑥-D 正向：unlink 清掉家长账号上的这条关联',
          not exc and u_stu_e.id not in d_after, '%s ｜ u_e.child_ids=%s' % (first_line(exc), d_after))

print()
print('=== ⑧ 清场 + 残留=0 ===')
env.cr.rollback()
left_p = P.with_context(active_test=False).search_count([('name.name', 'like', TAG + '%')])
left_s = S.with_context(active_test=False).search_count([('name', 'like', TAG + '%')])
left_r = Partner.with_context(active_test=False).search_count([('name', 'like', TAG + '%')])
left_u = Users.with_context(active_test=False).search_count([('login', 'like', USER_PREFIX + '%')])
env.cr.execute('SELECT count(*) FROM res_user_first_rel1 rel JOIN res_users u ON u.id = rel.user_id '
               'WHERE u.login LIKE %s', (USER_PREFIX + '%',))
left_rel = env.cr.fetchone()[0]
check('⑧ 残留=0（op.parent / op.student / res.partner / res.users / child_ids 关联表）',
      left_p == left_s == left_r == left_u == left_rel == 0,
      'parent=%d student=%d partner=%d user=%d child_rel=%d'
      % (left_p, left_s, left_r, left_u, left_rel))
check('⑧ 计数回到开工前（未污染他人数据）',
      (P.search_count([]), S.search_count([]), is_parent_ids()) == (par0, stu0, par_ids0),
      'op.parent %d→%d ｜ op.student %d→%d ｜ is_parent 伙伴 %d→%d'
      % (par0, P.search_count([]), stu0, S.search_count([]), len(par_ids0), len(is_parent_ids())))
env.cr.commit()

print()
for n in notes:
    print('备注 | %s' % n)
print('合计：PASS %d / FAIL %d' % (ok, fail))
if fail:
    raise SystemExit(1)
