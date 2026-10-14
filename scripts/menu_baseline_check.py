# -*- coding: utf-8 -*-
"""菜单基线 JSON 的宿主侧校验（t2 用）。

为什么单独一个文件：基线文件是**回滚目标**与**验收判据**的共同来源，
半截输出或口径自相矛盾的基线比没有基线更危险 —— 校验必须在 mv 落地之前完成。

校验项（逐条对应一个"看起来像基线、其实不能用"的失败形态）：
  1. JSON 可解析（容器 stdout 混了日志 → 解析失败）；
  2. 关键字段齐（counts/root_menus/menus/roles/definitions）；
  3. 口径 A 自洽：counts.A_raw_roots_total == len(root_menus) 且 active+inactive == total；
  4. 每个目标角色都在，且 found=True（角色写错/账号缺失 → 可见性口径缺一角）；
  5. 树的父子链自洽：所有非根菜单的 parent_id 都出现在 menus 里。

用法：python3 scripts/menu_baseline_check.py <基线文件>
退出码：0 通过；1 不通过（逐条打印 FAIL）。
覆盖声明：只校验**文件内部一致性**，不校验"这份基线是否反映当前数据库"
（那要靠 menu_baseline_diff.py 拿两份基线对比，或重跑快照）。
"""
import io
import json
import sys

fails = []
path = sys.argv[1] if len(sys.argv) > 1 else ''
if not path:
    print('FAIL | 用法: python3 scripts/menu_baseline_check.py <基线文件>')
    sys.exit(1)

try:
    text = io.open(path, 'r', encoding='utf-8').read()
    payload = json.JSONDecoder().raw_decode(text[text.find('{'):])[0]
except Exception as exc:  # noqa: BLE001 - 任何解析失败都判不通过
    print('FAIL | JSON 不可解析: %s' % exc)
    sys.exit(1)

for key in ('counts', 'root_menus', 'menus', 'roles', 'definitions'):
    if key not in payload:
        fails.append('缺字段 %s' % key)
if fails:
    for f in fails:
        print('FAIL | %s' % f)
    sys.exit(1)

c = payload['counts']
checks = [
    ('口径 A 与 root_menus 长度一致',
     c['A_raw_roots_total'] == len(payload['root_menus']),
     '%d == %d' % (c['A_raw_roots_total'], len(payload['root_menus']))),
    ('口径 A 的 active+inactive == total',
     c['A_raw_roots_active'] + c['A_raw_roots_inactive'] == c['A_raw_roots_total'],
     '%d + %d == %d' % (c['A_raw_roots_active'], c['A_raw_roots_inactive'], c['A_raw_roots_total'])),
    ('menus 条数 == menus_total_incl_inactive',
     len(payload['menus']) == c['menus_total_incl_inactive'],
     '%d == %d' % (len(payload['menus']), c['menus_total_incl_inactive'])),
    ('roles 非空', bool(payload['roles']), '%d 个角色' % len(payload['roles'])),
]
missing = [lg for lg, e in payload['roles'].items() if not e.get('found')]
checks.append(('所有目标角色都存在', not missing, '缺: %s' % (','.join(missing) or '无')))

ids = {m['id'] for m in payload['menus']}
dangling = [m['id'] for m in payload['menus'] if m['parent_id'] and m['parent_id'] not in ids]
checks.append(('父子链自洽（无悬空 parent_id）', not dangling, '悬空: %s' % (','.join(map(str, dangling[:5])) or '无')))

ok = True
for name, cond, detail in checks:
    print('%s | %s | %s' % ('PASS' if cond else 'FAIL', name, detail))
    ok = ok and cond
print('%s | 基线 %s：A=%d(active %d/inactive %d) 菜单 %d 条 角色 %s' % (
    'PASS' if ok else 'FAIL', path, c['A_raw_roots_total'], c['A_raw_roots_active'],
    c['A_raw_roots_inactive'], len(payload['menus']), ','.join(payload['roles'])))
sys.exit(0 if ok else 1)
