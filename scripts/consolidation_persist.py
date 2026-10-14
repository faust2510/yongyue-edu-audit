# -*- coding: utf-8 -*-
"""菜单收口的"防重放"守护工具（t11 / F1，宿主侧驱动，只改 ir_model_data.noupdate）。

## 问题（F1，实测复现）
`-u edu_portal` 之后，5 棵已收口的根菜单**复活**（542 邀请码 / 543 日常管理 / 576 在线课程 /
597 行政评估 / 606 老账号补挂身份），B(backoffice) 12→17 超线。原因是这些菜单的 xmlid 属于
edu_portal/edu_eval 等模块且 `noupdate=0` ⇒ 它们被升级时，自己的 XML 定义会把菜单**写回原值**。
即"谁最后跑谁赢"。

## 修法（读源码确认过，非猜测）
`odoo/orm/models.py::_load_records`：
    if not (update and d_noupdate): to_update.append(data)
`odoo/addons/base/models/ir_model.py::_build_update_xmlids_query`：
    ON CONFLICT (module, name) DO UPDATE SET (model, res_id, write_date) = (...)   -- **不含 noupdate**
⇒ 把受影响菜单的 xmlid 记录置 `noupdate=1`，则**其它模块升级时不再覆盖**这些菜单；
  且 noupdate 本身不会被后续升级重置（DO UPDATE 里没有它）。

## 覆盖范围
对 edu_nav 数据文件覆盖的全部菜单（357 条）的 xmlid 记录生效。它们分属 47 个模块，
其中 **47 个模块都是潜在重放源**（只要被 `-u` 就可能写回原值）——所以是"按菜单 id 设"，
而不是"改 47 处 XML 源码"（后者要改 Odoo 核心 / openeducat 基座，不可行）。

## 用法
    python3 scripts/consolidation_persist.py --status        # 只读：报告有多少目标 xmlid 未受保护
    python3 scripts/consolidation_persist.py --dry-run       # 只报会改哪些
    python3 scripts/consolidation_persist.py --protect       # 保护（noupdate=1；先导出备份）
    python3 scripts/consolidation_persist.py --unprotect     # 撤销保护（noupdate=0，依备份）
    # 兼容旧名：--apply = --protect，--rollback = --unprotect

## ⚠ 改动顺序（实测踩过：noupdate 也会挡住 edu_nav 自己）
    noupdate=1 之后，**edu_nav 自己写的菜单值也不再生效**（同一条 _load_records 分支）。
    所以"改菜单"必须按这个顺序：
        1) python3 scripts/consolidation_persist.py --unprotect
        2) python3 scripts/gen_menu_data.py --state=baseline
        3) bash scripts/safe_upgrade.sh edu_nav
        4) python3 scripts/consolidation_persist.py --protect
    只跑第 2/3 步会"看起来升级成功、菜单没变"（实测：收口值仍是 19/17/12 而非 14/12/9）。
备份：docs/audit/menu-consolidation/noupdate-backup.json（--apply 先写，--rollback 依它还原）

## 副作用与维护规则（必须知道）
- **副作用**：这些菜单从此**不能再靠模块 XML 改**（改了不生效）。以后要改菜单，规则是：
  1) 改 `menu-consolidation-plan.json` → 2) `python3 scripts/gen_menu_data.py --state=baseline` →
  3) `bash scripts/safe_upgrade.sh edu_nav`（edu_nav 自己的数据仍会写）。
  即"菜单口径的唯一入口变成 edu_nav 的数据文件"，这与 t2 的施工方式一致（本就要这么做）。
- 被保护的是"菜单记录"，不影响这些模块的其它数据。
"""
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XML = os.path.join(ROOT, 'custom_addons/edu_nav/data/menu_consolidation_data.xml')
BACKUP = os.path.join(ROOT, 'docs/audit/menu-consolidation/noupdate-backup.json')
MODE = 'status'
_ALIAS = {'--apply': 'protect', '--rollback': 'unprotect',
          '--protect': 'protect', '--unprotect': 'unprotect',
          '--status': 'status', '--dry-run': 'dry-run'}
for flag, mode in _ALIAS.items():
    if flag in sys.argv:
        MODE = mode


def target_ids():
    """数据文件覆盖的菜单 id（从生成的 XML 里取，保证与落库内容同源）。"""
    t = io.open(XML, encoding='utf-8').read()
    import re
    return sorted(int(x) for x in re.findall(r'field name="id" eval="(\d+)"', t))


def shell(code):
    r = subprocess.run(['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
                        '-c', '/etc/odoo/odoo.conf', '--db_host=db', '-r', 'odoo', '-w', 'odoo',
                        '-d', 'edu19', '--no-http'], input=code, text=True, capture_output=True)
    return r.stdout, r.stderr


ids = target_ids()
common = '''
import json
IDS = __IDS__
IData = env['ir.model.data'].sudo()
rows = IData.search([('model', '=', 'ir.ui.menu'), ('res_id', 'in', IDS)])
unprot = [{'xmlid': '%s.%s' % (r.module, r.name), 'res_id': r.res_id, 'noupdate': bool(r.noupdate)}
          for r in rows if not r.noupdate]
print('CP_TOTAL=' + str(len(rows)))
print('CP_UNPROTECTED=' + json.dumps(unprot))
print('CP_BACKUP=' + json.dumps([{'xmlid': '%s.%s' % (r.module, r.name), 'res_id': r.res_id} for r in rows]))
__ACTION__
'''.replace('__IDS__', repr(ids))

if MODE in ('status', 'dry-run'):
    action = ''
elif MODE == 'protect':
    action = ("for r in rows:\n"
              "    if not r.noupdate:\n"
              "        r.write({'noupdate': True})\n"
              "env.cr.commit()\n"
              "print('CP_APPLIED=1')")
else:  # rollback
    action = ("bak = json.loads(__BAK__)\n"
              "for x in bak:\n"
              "    r = IData.search([('module','=',x['xmlid'].split('.')[0]),"
              " ('name','=','.'.join(x['xmlid'].split('.')[1:]))], limit=1)\n"
              "    if r and r.noupdate:\n"
              "        r.write({'noupdate': False})\n"
              "env.cr.commit()\n"
              "print('CP_ROLLED_BACK=1')")
    if not os.path.exists(BACKUP):
        sys.stderr.write('缺少备份 %s，无法回滚\n' % BACKUP)
        sys.exit(2)
    bak = json.load(io.open(BACKUP, encoding='utf-8'))['xmlids']
    action = action.replace('__BAK__', repr(json.dumps(bak, ensure_ascii=False)))

out, err = shell(common.replace('__ACTION__', action))
for line in out.split('\n'):
    if line.startswith('CP_TOTAL='):
        print('数据文件覆盖的菜单 = %s 条' % line.split('=')[1])
    elif line.startswith('CP_UNPROTECTED='):
        unprot = json.loads(line.split('=', 1)[1])
        print('未受 noupdate 保护 = %d 条' % len(unprot))
        if MODE in ('status', 'dry-run') and unprot:
            for x in unprot[:12]:
                print('   %-46s menu=%s' % (x['xmlid'], x['res_id']))
            if len(unprot) > 12:
                print('   … 其余 %d 条' % (len(unprot) - 12))
    elif line.startswith('CP_BACKUP='):
        if MODE == 'apply':
            data = {'note': 'apply 之前的 noupdate 状态备份（rollback 依此还原）',
                    'xmlids': json.loads(line.split('=', 1)[1])}
            io.open(BACKUP, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, indent=1))
            print('已写备份 %s（%d 条）' % (BACKUP, len(data['xmlids'])))
    elif line.startswith('CP_APPLIED='):
        print('已保护（noupdate=1）；注意：此后改菜单必须先 --unprotect（见文件头"改动顺序"）')
    elif line.startswith('CP_ROLLED_BACK='):
        print('已还原（noupdate=0，依备份）')
if not out.strip():
    sys.stderr.write(err[-800:])
    sys.exit(1)
