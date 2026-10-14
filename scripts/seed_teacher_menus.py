# -*- coding: utf-8 -*-
"""教师端后台菜单裁剪（幂等）：非教学类应用根菜单仅对「后台·完整视图」组可见。

原理：
  1) 新建 res.groups，xmlid = edu_portal.group_backend_full（名称「后台·完整视图」）；
  2) 让 base.group_system 隐含(implied_ids)该组 -> 超管/管理员天然全开；
  3) 对隐藏名单里的每个 ir.ui.menu 根菜单写 groups_id += 该组。
     Odoo 的 ir.ui.menu 按当前用户分组过滤(_filter_visible_menus)，
     不在该组的普通内部用户（如教师 faculty@local）即看不到这些应用卡；
     后续管理员在 设置>用户 里给某用户勾选「后台·完整视图」即可单独放开。
  注：superuser 不受组限制属正常现象。

用法：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
        -r odoo -w odoo -d edu19 --no-http < scripts/seed_teacher_menus.py
"""

GROUP_MODULE = 'edu_portal'
GROUP_XMLID = 'group_backend_full'
GROUP_NAME = '后台·完整视图'
GROUP_COMMENT = (
    '教师端后台裁剪标记组：被本组限制的根菜单（讨论/日历/联系人/仪表板/发票/'
    '网站/员工/活动/招聘/在线聊天/链接追踪器等非教学类应用）对不拥有该组的'
    '内部用户隐藏；base.group_system 隐含本组，故管理员天然全开。'
    '需要给个别用户放开时，在用户表单勾选「后台·完整视图」即可。'
    '由 scripts/seed_teacher_menus.py 幂等维护。'
)

# (根菜单 xmlid, 中文名) —— 用户已确认的隐藏名单
HIDDEN_MENUS = [
    ('mail.menu_root_discuss', '讨论'),
    ('calendar.mail_menu_calendar', '日历'),
    ('contacts.menu_contacts', '联系人'),
    ('spreadsheet_dashboard.spreadsheet_dashboard_menu_root', '仪表板'),
    ('account.menu_finance', '发票'),
    ('website.menu_website_configuration', '网站'),
    ('hr.menu_hr_root', '员工'),
    ('event.event_main_menu', '活动'),
    ('hr_recruitment.menu_hr_recruitment_root', '招聘'),
    ('im_livechat.menu_livechat_root', '在线聊天'),
    ('utm.menu_link_tracker_root', '链接追踪器'),  # 无本地证据，缺失自动跳过
]

S = lambda m: env[m].sudo()

# ---- 1. 组：edu_portal.group_backend_full（不存在才建）----
full_xmlid = '%s.%s' % (GROUP_MODULE, GROUP_XMLID)
group = env.ref(full_xmlid, raise_if_not_found=False)
if not group or not group.exists():
    group = S('res.groups').create({
        'name': GROUP_NAME,
        'comment': GROUP_COMMENT,
    })
    # 手工注册 xmlid（shell 脚本没有 XML data），noupdate 防升级覆盖
    S('ir.model.data').create({
        'module': GROUP_MODULE,
        'name': GROUP_XMLID,
        'model': 'res.groups',
        'res_id': group.id,
        'noupdate': True,
    })
    print("新建组:", full_xmlid, "->", group.id)
else:
    # 幂等校正：名称/说明以脚本为准
    vals = {}
    if group.name != GROUP_NAME:
        vals['name'] = GROUP_NAME
    if group.comment != GROUP_COMMENT:
        vals['comment'] = GROUP_COMMENT
    if vals:
        group.write(vals)
    print("组已存在:", full_xmlid, "->", group.id)

# ---- 2. base.group_system 隐含该组（管理员自动全开）----
sys_group = S('res.groups').browse(env.ref('base.group_system').id)
if group.id not in sys_group.implied_ids.ids:
    sys_group.implied_ids = [(4, group.id)]
    print("base.group_system 已隐含", GROUP_NAME)
else:
    print("base.group_system 已隐含该组（跳过）")

# ---- 3. 隐藏名单：整棵子树的 group_ids 替换为仅「后台·完整视图」----
# （菜单对"任一所属组"开放；且子菜单可见会把父链全部拉亮——所以必须把
#   根及其所有后代的组整体替换，否则教师经由无限制子菜单仍能看到根。
#   幂等：根已精确等于 [该组] 且后代均已受限则跳过。）
def _descendants(menu):
    out = []
    stack = list(menu.child_id)
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(cur.child_id)
    return out

# 例外：不覆盖由本仓其它模块「显式声明」的菜单（收口值与声明值必须对上）。
# 例：website.menu_website_add_features 已由 edu_portal 的 NARROW_RULES 收成仅系统组；
# 若本脚本仍把「网站」整棵子树写成全开组，那条收窄会在下次 seed 时被静默回滚。
SEED_GROUP_EXCEPTIONS = {'website.menu_website_add_features'}
exc_ids = set()
for _x in SEED_GROUP_EXCEPTIONS:
    _m = env.ref(_x, raise_if_not_found=False)
    if _m:
        exc_ids.add(_m.id)
if exc_ids:
    print('SEED 例外（不覆盖）:%d 个菜单 id' % len(exc_ids))

patched, already, missing = [], [], []
for xmlid, label in HIDDEN_MENUS:
    menu = env.ref(xmlid, raise_if_not_found=False)
    if not menu or not menu.exists():
        missing.append('%s(%s)' % (xmlid, label))
        continue
    nodes = [menu] + _descendants(menu)
    if all(n.group_ids.ids == [group.id] for n in nodes):
        already.append(xmlid)
        continue
    for n in nodes:
        if n.id in exc_ids:          # 显式声明的菜单：本脚本不覆盖（见上 SEED_GROUP_EXCEPTIONS）
            continue
        n.sudo().write({'group_ids': [(6, 0, [group.id])]})
    patched.append('%s(含后代%d)' % (xmlid, len(nodes)))

# ---- 3.5 backoffice 也进全开组（校友工作管理需要完整后台视野）----
bo = env['res.users'].sudo().search([('login', '=', 'backoffice@local')],
                                    limit=1)
if bo and group.id not in bo.group_ids.ids:
    bo.write({'group_ids': [(4, group.id)]})
    print('BACKOFFICE 加入全开组')

# ---- 3.6 邀请码菜单仅系统组（防御性校正）----
inv = env.ref('edu_portal.menu_edu_invite_code_root',
              raise_if_not_found=False)
if inv and inv.group_ids.ids != [env.ref('base.group_system').id]:
    inv.sudo().write({'group_ids': [(6, 0, [
        env.ref('base.group_system').id])]})
    print('邀请码菜单组校正 -> base.group_system')


# ---- 3.7 守卫：87 只允许被 base.group_system 隐含 ----
# （Odoo19 角色体系会把 87 经"角色/管理员"等传递给教师，必须摘除）
sys_gid = env.ref('base.group_system').id
for g in env['res.groups'].sudo().search([('implied_ids', 'in', group.id)]):
    if g.id != sys_gid:
        g.write({'implied_ids': [(3, group.id)]})
        print('GUARD 移除非法隐含:', g.id, g.name)

# ---- 4. 汇总 ----
print("=" * 46)
print("新增限制的根菜单 (%d):" % len(patched))
for x in patched:
    print("   +", x)
print("已带限制、跳过 (%d):" % len(already))
for x in already:
    print("   =", x)
if missing:
    print("库中未找到、跳过 (%d):" % len(missing))
    for x in missing:
        print("   -", x)
print("组:", full_xmlid, "| 管理员隐含: 是 | 教师默认: 被裁剪")
env.cr.commit()
print("TEACHER MENU SEED DONE")
