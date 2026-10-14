# -*- coding: utf-8 -*-
"""`scripts/check_nav_jobs_entries.py` 的回归用例（t15，**不需要数据库**）。

## 为什么要有它（队长的验收要求 + 本项目的教训）
该哨兵的第一版有两个"断言自身有缺陷"的毛病：
  1. `rows.split('\\n') if isinstance(rows, str) else []` —— 而 `audit_lib.rows()` 返回 **list**
     ⇒ 恒取空数组 ⇒ **恒 PASS 假绿**（当时库里实有 2 条 /jobs 入口）；
  2. 逐条打印假设 tuple 位置固定 ⇒ IndexError（打印路径崩溃也会让哨兵失效）。
「恒 PASS 的检查器」比没有检查器更危险：它给人虚假的安全感。因此本文件用**构造数据**证明：
  · 真实返形态（list/str）都能被正确解析；
  · 存在 /jobs 时必须 **FAIL**（不是恒 PASS）；
  · 旧的两条错误假设**可被证伪**（留作回归，防止再犯）；
  · 打印路径在字段缺失/长度不一时不崩。

用法：python3 tests/unit/check_nav_jobs_entries_test.py   （退出码 0=全通过 / 1=有失败）
"""
import importlib.util
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, 'scripts', 'check_nav_jobs_entries.py')

spec = importlib.util.spec_from_file_location('nav_jobs_sentinel', SCRIPT)
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


# ---- 夹具：与实测同形（website_menu 行：id|name(jsonb)|url|parent|sequence）----
ROW_205 = '205|{"en_US": "Jobs", "zh_CN": "工作"}|/jobs|4|59'
ROW_206 = '206|{"en_US": "Jobs", "zh_CN": "工作"}|/jobs|1|59'
FIX_LIST = [ROW_205, ROW_206]          # audit_lib.rows() 的真实返回：list[str]
FIX_STR = ROW_205 + '\n' + ROW_206     # 另一种（当调用方对返回做过 join 时）
FIX_TUPLES = [('205', 'Jobs', '/jobs', '4', '59'), ('206', 'Jobs', '/jobs', '1', '59')]

# ---- 1) 归一化：三种真实形态都要被正确解析出 2 条 ----
for label, fixture in (('list[str]', FIX_LIST), ('str（换行）', FIX_STR), ('list[tuple]', FIX_TUPLES)):
    got = S.parse_entries(fixture)
    check('parse_entries 解析 %s → 2 条' % label, len(got) == 2, 'got=%d' % len(got))
    check('parse_entries(%s) 首行含 /jobs' % label, any('/jobs' in '|'.join(c) for c in got))

# ---- 2) 空态：None / 空 list / 空串 / 空行都要得到 0 条（而不是抛异常）----
for label, fixture in (('None', None), ('[]', []), ("''", ''), ("'\\n\\n'", '\n\n')):
    got = S.parse_entries(fixture)
    check('parse_entries(%s) → 0 条且不抛异常' % label, got == [], 'got=%r' % (got,))

# ---- 3) **核心判据**：有 /jobs 入口时必须 FAIL（防"恒 PASS"）----
passed, reason = S.evaluate(S.parse_entries(FIX_LIST), hr_jobs=0)
check('有 /jobs 入口 ⇒ FAIL', passed is False, reason)
passed2, _ = S.evaluate(S.parse_entries(FIX_LIST), hr_jobs=5)
check('有 /jobs 入口（hr_job>0）也 FAIL（空壳与否不影响"重复入口"判定）', passed2 is False)

# ---- 4) 干净态：无入口 ⇒ PASS，并说明 hr.job=0 的空壳背景 ----
p_clean, r_clean = S.evaluate([], hr_jobs=0)
check('无 /jobs 入口 ⇒ PASS', p_clean is True)
check('PASS 理由里点明"hr.job=0 本就是空壳"', '空壳' in r_clean, r_clean)

# ---- 5) **回归：证伪第一版的假绿写法**（若有人改回去，本用例会红）----
def old_buggy_parse(rows):
    # 第一版实现：把 rows 当 str 处理，否则返回空
    return [r.split('|') for r in rows.split('\n') if r.strip()] if isinstance(rows, str) else []

check('旧写法在真实返回(list)下会漏掉全部条目（= 假绿根因）', len(old_buggy_parse(FIX_LIST)) == 0,
      'old=%r' % (old_buggy_parse(FIX_LIST),))
check('新写法在同一份数据下能抓到 2 条（与旧写法形成对照）', len(S.parse_entries(FIX_LIST)) == 2)

# ---- 6) **回归：证伪"假设 tuple 位置固定"的打印路径** ----
#     给出字段数不一的行，旧写法 e[3]/e[4] 会 IndexError；新写法应能安全渲染
def old_buggy_render(entries):
    return [e[1][:60] + '|' + e[3] for e in entries]   # 假设长度 ≥5

short = [['7', '/jobs']]                                # 只有 2 个字段
crashed = False
try:
    old_buggy_render(short)
except IndexError:
    crashed = True
check('旧打印写法在字段不全时确实会崩（IndexError）', crashed)

def render(entries):
    out = []
    for e in entries:
        row = e if isinstance(e, (list, tuple)) else str(e).split('|')
        cells = [str(c) for c in row]
        out.append('   ' + ' ｜ '.join(c if len(c) <= 60 else c[:57] + '…' for c in cells))
    return out

ok_render = True
try:
    rendered = render(short)
except Exception as exc:  # noqa: BLE001
    ok_render = False
    rendered = [str(exc)]
check('新写法字段不全也能安全渲染', ok_render, rendered[0] if rendered else '')

# ---- 7) 端到端（不连库）：evaluate + 渲染组合在"2 条"夹具上给出 FAIL ----
buf = io.StringIO()
passed3, reason3 = S.evaluate(S.parse_entries(FIX_LIST), 0)
buf.write(('FAIL | ' if not passed3 else 'PASS | ') + reason3)
check('端到端：夹具 → FAIL 文案', 'FAIL |' in buf.getvalue(), buf.getvalue()[:80])

# ---- 汇总 ----
fail = [r for r in results if not r[1]]
for name, ok, detail in results:
    print('%s | %s | %s' % ('PASS' if ok else 'FAIL', name, detail))
print('%s | 回归用例：%d 条断言，%d 条失败' % ('PASS' if not fail else 'FAIL', len(results), len(fail)))
sys.exit(0 if not fail else 1)
