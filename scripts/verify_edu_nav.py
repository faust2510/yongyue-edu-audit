# -*- coding: utf-8 -*-
"""edu_nav 的机制级自测（t2，宿主侧；只读 + 一次可回滚的探针升级）。

为什么需要它（dev-workflow：断言必须先自证忠实）：
  「守卫没报错」不能证明守卫有效 —— 如果校验恒通过，那它稳定地绿，等于没装。
  所以本脚本先**构造一个必然被检出的漂移**（把期望条数临时改成 999），跑一次升级，
  断言日志里出现对应 ERROR；再**还原并复跑**，断言日志干净。

三段式（与仓内既有 smoke 一致）：
  ① 前置：读基线快照（口径 A），确认与收口前一致；确认工作区没有半改的文件；
  ② 探针：临时改常量 → 升级 → 断言 ERROR 出现（探针**确实命中**，不是"链路放行了"）；
  ③ 还原：写回原值 → 升级 → 断言 ERROR 消失，且菜单快照与基线逐字段一致。

用法：python3 scripts/verify_edu_nav.py
退出码：0 全部断言通过；1 有断言失败。
"""
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODEL = os.path.join(ROOT, 'custom_addons/edu_nav/models/menu_consolidation.py')
LOG_DIR = '/tmp'
CONST_RE = re.compile(r'MENU_CONSOLIDATED_COUNT = (\d+)')


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, **kw)


def latest_upgrade_log():
    logs = sorted(
        (os.path.join(LOG_DIR, f) for f in os.listdir(LOG_DIR)
         if f.startswith('edu19_upgrade.') and f.endswith('.log')),
        key=lambda p: os.path.getmtime(p))
    return logs[-1] if logs else None


def upgrade():
    run(['bash', 'scripts/safe_upgrade.sh', 'edu_nav'])
    log = latest_upgrade_log()
    text = io.open(log, encoding='utf-8', errors='replace').read() if log else ''
    return log, text


def guard_lines(text):
    return [l for l in text.split('\n') if '[edu_nav]' in l]


def snapshot(tag):
    run(['bash', 'scripts/menu_baseline.sh', 'snapshot', '--tag', tag])
    return os.path.join(ROOT, 'docs/audit/menu-consolidation/menu-tree-%s.json' % tag)


results = []
src = io.open(MODEL, encoding='utf-8').read()
m = CONST_RE.search(src)
if not m:
    print('FAIL | 找不到 MENU_CONSOLIDATED_COUNT')
    sys.exit(1)
original = int(m.group(1))

# ① 前置：模块常量必须与"数据文件里生效记录条数"一致（live = N 条、inert = 0）。
#    两种阶段都成立，所以这里不写死"应为 0"（那是惰性阶段的专用断言，落库后会假红）。
_data = io.open(os.path.join(ROOT, 'custom_addons/edu_nav/data/menu_consolidation_data.xml'),
                encoding='utf-8').read()
_live = len([l for l in _data.split('\n') if l.strip().startswith(chr(60) + 'record id=')])
results.append(('模块常量与数据文件生效条数一致', original == _live,
                '常量 %d / data 生效 %d' % (original, _live)))

# ② 探针：必然被检出的漂移
try:
    io.open(MODEL, 'w', encoding='utf-8').write(
        CONST_RE.sub('MENU_CONSOLIDATED_COUNT = 999', src, count=1))
    log, text = upgrade()
    probe_lines = guard_lines(text)
    hit = any('ERROR' in l and '999' in l for l in probe_lines)
    results.append(('探针命中：故意写错条数会被守卫报 ERROR', hit,
                    (probe_lines[-1][:120] if probe_lines else '无守卫日志')))
finally:
    io.open(MODEL, 'w', encoding='utf-8').write(src)

# ③ 还原：干净复跑 + 快照不变
log2, text2 = upgrade()
clean = not any('ERROR' in l for l in guard_lines(text2))
results.append(('还原后守卫无 ERROR', clean, (guard_lines(text2)[-1][:120] if guard_lines(text2) else '无')))

base = os.path.join(ROOT, 'docs/audit/menu-consolidation/menu-tree-before.json')
snap = snapshot('verify_edu_nav')
if os.path.exists(base) and os.path.exists(snap):
    def load(p):
        t = io.open(p, encoding='utf-8').read()
        return json.JSONDecoder().raw_decode(t[t.find('{'):])[0]
    b, a = load(base), load(snap)
    # 阶段判定：库是否已收口（口径 B 的根数是否已低于基线）。
    #   ——本脚本原先写死"应与基线一致"，那是**惰性阶段**的断言；落库后它会"正确地失败"，
    #     但那种失败容易被误读成缺陷，所以按阶段切换断言（两种阶段都必须能被证明）。
    b_roots = {k: v['visible_roots'] for k, v in b['roles'].items()}
    a_roots = {k: v['visible_roots'] for k, v in a['roles'].items()}
    applied = a_roots.get('backoffice@local', 0) < b_roots.get('backoffice@local', 0)
    if applied:
        lim = {'admin': 20, 'backoffice@local': 12}
        ok = all(a_roots.get(k, 0) <= v for k, v in lim.items())
        results.append(('已收口阶段：B(admin)≤20 且 B(backoffice)≤12', ok,
                        'B 前=%s → 后=%s' % (b_roots, a_roots)))
        results.append(('收口阶段：记录数不变（只改开关）',
                        b['counts']['menus_total_incl_inactive'] == a['counts']['menus_total_incl_inactive'],
                        '全库 %d → %d' % (b['counts']['menus_total_incl_inactive'],
                                          a['counts']['menus_total_incl_inactive'])))
    else:
        same_counts = b['counts'] == a['counts']
        same_roles = b_roots == a_roots
        results.append(('惰性阶段：菜单快照与收口前基线一致', same_counts and same_roles,
                        'A=%d/%d 根；B=%s' % (b['counts']['A_raw_roots_total'],
                                              a['counts']['A_raw_roots_total'], same_roles)))
else:
    results.append(('菜单快照与基线可比', False, '缺基线或快照文件'))

ok = True
for name, cond, detail in results:
    print('%s | %s | %s' % ('PASS' if cond else 'FAIL', name, detail))
    ok = ok and cond
print('%s | edu_nav 机制级自测（探针升级 %s）' % ('PASS' if ok else 'FAIL', log2))
sys.exit(0 if ok else 1)
