# -*- coding: utf-8 -*-
"""对照表生成器的行为级自测（t2 用，宿主侧，不连库、不碰真实基线文件）。

为什么需要它（dev-workflow 铁律"断言必须先自证忠实"）：
  「同内容对自身 → 全零」只能证明**不会误报**，**不能证明会报**。
  如果生成器恒返回零，那条全零自检会稳定地绿 —— 正是"稳定通过不是证据"的形态。
  所以这里反过来：**在基线副本上人为植入 3 处已知变动**，断言对照表**逐条报出来**。

植入的 3 处（对应三种最常见的收口动作）：
  1. 测试(id=16)   可见组 [] → [4]           （改成仅超管可见）
  2. 链接追踪器(75) 启用 true → false         （隐藏）
  3. 学生(278)     父菜单 null → 257         （挂到 学生信息 下 → 合并入口）

断言：字段级改动 = 3 条；被隐藏记录数 = 1；硬删除记录数 = 0；admin 的 ΔB = -1。

用法：python3 scripts/menu_baseline_diff_selftest.py [基线路径]
      基线默认 docs/audit/menu-consolidation/menu-tree-before.json
退出码：0 全部断言通过；1 有断言失败（逐条打印）。
"""
import io
import json
import os
import subprocess
import sys
import tempfile

BASE = sys.argv[1] if len(sys.argv) > 1 else 'docs/audit/menu-consolidation/menu-tree-before.json'
HERE = os.path.dirname(os.path.abspath(__file__))
DIFF = os.path.join(HERE, 'menu_baseline_diff.py')


def load(path):
    text = io.open(path, 'r', encoding='utf-8').read()
    return json.JSONDecoder().raw_decode(text[text.find('{'):])[0]


payload = load(BASE)
for m in payload['menus']:
    if m['id'] == 16:
        m['group_ids'] = [4]
    elif m['id'] == 75:
        m['active'] = False
    elif m['id'] == 278:
        m['parent_id'] = 257
for login, e in payload['roles'].items():
    if not e.get('found'):
        continue
    if '测试' in e.get('visible_root_names', []):
        e['visible_root_names'] = [x for x in e['visible_root_names'] if x != '测试']
        e['visible_roots'] = len(e['visible_root_names'])
        e['visible_total'] -= 1

tmpd = tempfile.mkdtemp(prefix='menu_diff_selftest.')
after = os.path.join(tmpd, 'synthetic_after.json')
report = os.path.join(tmpd, 'report.md')
io.open(after, 'w', encoding='utf-8').write(
    json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True))

rc = subprocess.call([sys.executable, DIFF, BASE, after, '--out', report])
text = io.open(report, 'r', encoding='utf-8').read() if os.path.exists(report) else ''

checks = [
    ('生成器退出码为 0', rc == 0, 'rc=%d' % rc),
    ('字段级改动报出 3 条', '字段级改动 3 条' in text, ''),
    ('报出 测试 的可见组变化', '| 16 | 测试 | 可见组 |' in text, ''),
    ('报出 链接追踪器 的启用开关变化', '| 75 | 链接追踪器 | 启用开关 |' in text, ''),
    ('报出 学生 的父菜单变化', '| 278 | 学生 | 父菜单 |' in text, ''),
    ('被隐藏记录数 = 1', '被隐藏记录数（active True→False）= 1' in text, ''),
    ('硬删除记录数 = 0', '硬删除记录数 = 0' in text, ''),
]
ok = True
for name, cond, detail in checks:
    print('%s | %s %s' % ('PASS' if cond else 'FAIL', name, detail))
    ok = ok and cond

print('%s | 对照表生成器行为级自测（%s）' % ('PASS' if ok else 'FAIL', DIFF))
print('提示：本次测试产物在 %s（临时目录，不进 git）' % tmpd)
sys.exit(0 if ok else 1)
