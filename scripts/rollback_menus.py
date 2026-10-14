# -*- coding: utf-8 -*-
"""用**收口前基线**把菜单整表还原到收口前状态（t2 的可回滚交付，宿主侧驱动）。

为什么以基线为权威、而不是用 rollback-basis.json：
  实测教训（2026-09-17）：`rollback-basis.json` 只覆盖"当次 dry-run 的 DESIRED"——
  被"折父"迁走的子菜单如果那次 dry-run 时**已经在目标父下**，就不会进入 DESIRED
  ⇒ 依据里缺它们的 parent 原值 ⇒ 回滚后它们仍留在新容器下，admin 的根数回不到基线（实测 30 vs 38）。
  基线文件（menu-tree-before.json）是全库 605 条的完整快照，**用它才可能"整表还原"**。

做法：逐条比对"当前态 vs 基线态"（active / group_ids / parent_id / sequence），只写不同的字段；
      全程单事务提交，并在提交后用**同口径回读**断言 0 条不一致。

用法：
    python3 scripts/rollback_menus.py --dry-run    # 只报告会改多少条
    python3 scripts/rollback_menus.py --apply      # 真回滚
"""
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, 'docs/audit/menu-consolidation/menu-tree-before.json')
MODE = 'apply' if '--apply' in sys.argv else 'dry-run'

t = io.open(BASE, encoding='utf-8').read()
base = json.JSONDecoder().raw_decode(t[t.find('{'):])[0]
menus = {m['id']: m for m in base['menus']}
payload = {str(i): {'active': bool(m['active']), 'group_ids': list(m['group_ids']),
                    'parent_id': m['parent_id'], 'sequence': m['sequence']}
           for i, m in menus.items()}

py = '''
import json
ORIG = json.loads(__ORIG__)
M = env['ir.ui.menu'].sudo().with_context(active_test=False)
changed = []
for mid, vals in ORIG.items():
    m = M.browse(int(mid))
    if not m.exists():
        continue
    patch = {}
    if bool(m.active) != vals['active']:
        patch['active'] = vals['active']
    if sorted(m.group_ids.ids) != sorted(vals['group_ids']):
        patch['group_ids'] = [(6, 0, list(vals['group_ids']))]
    if (m.parent_id.id or None) != vals['parent_id']:
        patch['parent_id'] = vals['parent_id']
    if m.sequence != vals['sequence']:
        patch['sequence'] = vals['sequence']
    if patch:
        changed.append(int(mid))
        if __APPLY__:
            m.write(patch)
print('RB_CHANGED=' + str(len(changed)))
if __APPLY__:
    env.cr.commit()
    bad = [int(mid) for mid, vals in ORIG.items()
           if (bool(M.browse(int(mid)).active) != vals['active']
               or sorted(M.browse(int(mid)).group_ids.ids) != sorted(vals['group_ids'])
               or (M.browse(int(mid)).parent_id.id or None) != vals['parent_id']
               or M.browse(int(mid)).sequence != vals['sequence'])]
    print('RB_MISMATCH=' + json.dumps(bad))
'''.replace('__ORIG__', repr(json.dumps(payload, ensure_ascii=False))) \
   .replace('__APPLY__', 'True' if MODE == 'apply' else 'False')

r = subprocess.run(['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
                    '-c', '/etc/odoo/odoo.conf', '--db_host=db', '-r', 'odoo', '-w', 'odoo',
                    '-d', 'edu19', '--no-http'], input=py, text=True, capture_output=True)
ok = False
for line in r.stdout.split('\n'):
    if line.startswith('RB_CHANGED='):
        print('模式 %s ｜ 与基线不一致、需还原的菜单 = %s 条' % (MODE, line.split('=')[1]))
        ok = True
    if line.startswith('RB_MISMATCH='):
        bad = json.loads(line.split('=', 1)[1])
        print('回读断言：不一致 %d 条 %s' % (len(bad), bad[:10]))
if not ok:
    sys.stderr.write(r.stdout[-1500:] + '\n' + r.stderr[-800:] + '\n')
    sys.exit(1)
sys.exit(0)
