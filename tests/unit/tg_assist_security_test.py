# -*- coding: utf-8 -*-
"""edu_tg_assist 网站侧权限（security/assist_security.xml + ir.model.access.csv）静态回归用例。

为什么要有它（用户 2026-10-13 的要求：「sarah老师可以给她开一个行政级别的账号」）：
  · 本模块原先只有 base.group_system 的 ACL —— 「用网站后台管机器人」等于「必须
    是超级管理员」，教务进不去；组与 ACL 一旦漏配，表现是**点了菜单就报错**，
    而不是「少个功能」，必须在离线门禁里拦住；
  · 组必须先于引用它的 ACL 装载，manifest 里的顺序写错会在升级时炸；
  · 记录/审计类表（发送记录 / 更新日志 / 私发审计 / 按钮回填）**只能只读**：
    教务要能查、不该能改历史；
  · Odoo 的 CSV 读取器**不跳过 # 注释行**，往 ir.model.access.csv 写注释 = 升级报错。

用法：python3 tests/unit/tg_assist_security_test.py   （退出码 0=全通过 / 1=有失败）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSIST = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist')
SEC_XML = os.path.join(ASSIST, 'security', 'assist_security.xml')
CSV = os.path.join(ASSIST, 'security', 'ir.model.access.csv')
MANIFEST = os.path.join(ASSIST, '__manifest__.py')
VIEW = os.path.join(ASSIST, 'views', 'assist_views.xml')
MODELS = os.path.join(ASSIST, 'models')

GROUP = 'edu_tg_assist.group_assist_manager'

with open(SEC_XML, encoding='utf-8') as fh:
    SEC = fh.read()
with open(CSV, encoding='utf-8') as fh:
    CSV_SRC = fh.read()
with open(MANIFEST, encoding='utf-8') as fh:
    MANIFEST_SRC = fh.read()
with open(VIEW, encoding='utf-8') as fh:
    VIEW_SRC = fh.read()

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


def concrete_models():
    """扫描 models/*.py，返回所有**具体模型**的 _name（AbstractModel 不要 ACL）。"""
    found = []
    for fname in sorted(os.listdir(MODELS)):
        if not fname.endswith('.py'):
            continue
        with open(os.path.join(MODELS, fname), encoding='utf-8') as fh:
            src = fh.read()
        if 'models.AbstractModel' in src:
            continue
        for hit in re.finditer(r"^    _name = '(edu\.tg\.assist\.[a-z_.]+)'", src, re.M):
            found.append((hit.group(1), fname))
    return found


def acl_row(model):
    for line in CSV_SRC.splitlines():
        cells = line.split(',')
        if len(cells) >= 8 and cells[2] == 'model_%s' % model.replace('.', '_') \
                and cells[3] == GROUP:
            return cells
    return None


# ---- 1) 组定义 ----
check('安全组文件存在且是 XML', '<odoo>' in SEC and 'res.groups' in SEC)
check('组 xmlid 就叫 group_assist_manager', 'id="group_assist_manager"' in SEC)
check('组名对教务说得清', '班务机器人管理员' in SEC)
check('组说明点明能管什么（含材料归档下载）',
      '人员映射' in SEC and '材料归档' in SEC and '下载' in SEC)
check('本组不隐含 base.group_system（教务≠超管）',
      'implied_ids' not in SEC)

# ---- 2) 装载顺序：组先于引用它的 ACL ----
pos_sec = MANIFEST_SRC.find("'security/assist_security.xml'")
pos_csv = MANIFEST_SRC.find("'security/ir.model.access.csv'")
check('manifest 装载了安全组', pos_sec != -1)
check('组排在 ACL 之前', pos_sec != -1 and pos_csv != -1 and pos_sec < pos_csv)

# ---- 3) 每张具体表都要有管理组 ACL（新表忘配 = 教务点菜单报错）----
models = concrete_models()
check('扫到的具体模型数 >= 14（本模块现有 14 张表）', len(models) >= 14,
      detail='扫到 %d：%s' % (len(models), [m for m, _ in models]))
missing = [m for m, _ in models if acl_row(m) is None]
check('每张具体表都有管理组 ACL', not missing, detail='缺：%s' % missing)

# ---- 4) 配置类可增删改，审计类只读 ----
FULL = ['edu.tg.assist.chat', 'edu.tg.assist.person', 'edu.tg.assist.template',
        'edu.tg.assist.reminder', 'edu.tg.assist.material', 'edu.tg.assist.bindcode',
        'edu.tg.assist.poll', 'edu.tg.assist.poll.reply', 'edu.tg.assist.mention',
        'edu.tg.assist.selfcheck']
READONLY = ['edu.tg.assist.send_log', 'edu.tg.assist.update_log', 'edu.tg.assist.dm',
            'edu.tg.assist.reply']
for model in FULL:
    row = acl_row(model)
    check('%s 管理组可增删改查' % model, row is not None and row[4:] == ['1', '1', '1', '1'],
          detail=str(row))
for model in READONLY:
    row = acl_row(model)
    check('%s 管理组只读（历史不许改）' % model,
          row is not None and row[4:] == ['1', '0', '0', '0'], detail=str(row))

# ---- 5) 老口径一条不动：超管仍有全部权限 ----
sys_rows = [ln for ln in CSV_SRC.splitlines() if ',base.group_system,' in ln]
check('base.group_system 的 ACL 仍是 9 条以上',
      len(sys_rows) >= 9, detail='实际 %d' % len(sys_rows))

# ---- 6) CSV 里不许有 # 注释（Odoo 的 CSV 读取器不跳过注释）----
check('ir.model.access.csv 无 # 注释行',
      not [ln for ln in CSV_SRC.splitlines() if ln.strip().startswith('#')])

# ---- 7) 根菜单只给管理组与超管看 ----
check('根菜单已按组收口',
      re.search(r'<menuitem id="menu_assist_root"[^>]*groups="%s,base\.group_system"' % re.escape(GROUP),
                VIEW_SRC, re.S) is not None)

failed = [n for n, ok, _ in results if not ok]
for name, ok, detail in results:
    print(('PASS  ' if ok else 'FAIL  ') + name + (('  << ' + detail) if detail and not ok else ''))
print('----')
print('%s/%s 通过' % (len(results) - len(failed), len(results)))
if failed:
    print('失败：' + '; '.join(failed))
sys.exit(1 if failed else 0)
