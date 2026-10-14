# -*- coding: utf-8 -*-
"""清本地克隆的「手挂组漂移」（默认 DRY_RUN，只读）。

背景（2026-09-17 verifier 在 t4 前置侦察中查到）：
本地 faculty@local 直挂了 15 个组（含 openeducat_admission.group_op_admission_admin、
openeducat_fees.group_op_fees_admin 等），而**全仓 .py/.xml/.csv 里没有任何授予点** ⇒ 手挂漂移。
后果：本地"教师"读数不代表生产，且造成 15 个模型上「教师权限 > 教务权限」的倒挂；
表现为「教师可见 ∩ 教务不可见 = 11 条菜单（口径 B）」。

生产不受影响（production teacher@local 实测是 base.group_portal）。

用法（容器内经 stdin 送入）：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 \
        --db_host=db -r odoo -w odoo --no-http < scripts/clean_local_group_drift.py
    # 真写：加 -e APPLY=1

环境变量：
    TARGET_LOGIN  默认 faculty@local
    KEEP          默认 "base.group_user,openeducat_core.group_op_faculty"（逗号分隔 xmlid）
    APPLY=1       真写（默认只读）
"""
import os

APPLY = os.environ.get('APPLY', '') == '1'
TARGET_LOGIN = os.environ.get('TARGET_LOGIN') or 'faculty@local'
KEEP_XMLIDS = [x.strip() for x in (os.environ.get('KEEP') or
              'base.group_user,openeducat_core.group_op_faculty').split(',') if x.strip()]

u = env['res.users'].sudo().search([('login', '=', TARGET_LOGIN)], limit=1)
assert u, '找不到账号 %s' % TARGET_LOGIN
keep = env['res.groups'].sudo().browse()
for x in KEEP_XMLIDS:
    g = env.ref(x, raise_if_not_found=False)
    assert g, '保留清单里的组不存在：%s' % x
    keep |= g

before = u.group_ids
extra = before - keep
missing = keep - before

print('== 清漂移：%s（uid %d）==' % (TARGET_LOGIN, u.id))
print('  APPLY = %s' % APPLY)
print('  保留清单 =', ', '.join(KEEP_XMLIDS))
print('  当前直挂组 (%d):' % len(before))
for g in before.sorted('id'):
    print('     %-8s %s%s' % ('[保留]' if g in keep else '[移除]',
                              g.display_name, '' ))
print('  应移除 = %d 个；保留清单里当前缺失 = %d 个（%s）'
      % (len(extra), len(missing), ', '.join(missing.mapped('display_name')) or '无'))

if not extra:
    print('  → 无漂移（幂等）')
elif not APPLY:
    print('  → DRY RUN：未写入。回滚信息（供需要时恢复）：')
    print('     u.write({'"'"'group_ids'"'"': [(4, %s)]})' % ', '.join(str(i) for i in sorted(extra.ids)))
else:
    u.write({'group_ids': [(3, gid) for gid in extra.ids]})
    env.cr.commit()
    print('  → 已移除 %d 个组并提交' % len(extra))
    print('     移除清单（xmlid 形式，供恢复）:')
    for g in extra:
        d = env['ir.model.data'].sudo().search(
            [('model', '=', 'res.groups'), ('res_id', '=', g.id)], limit=1)
        print('       %s | %s' % (('%s.%s' % (d.module, d.name)) if d else '(无 xmlid)', g.display_name))
    print('  回滚命令：对每个 xmlid 执行 u.write({'"'"'group_ids'"'"': [(4, ref(x))]})')
