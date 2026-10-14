#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ux-rework t4 单元检查：week_utils 周次工具（S2/S3/S4 共用口径）。

用法：python3 tests/smoke/ux_week_utils_check.py
"""
import os
import sys
import datetime

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..',
    'custom_addons', 'edu_schedule', 'models'))

from week_utils import (monday_of, parse_week_ranges, week_no_of,   # noqa: E402
                        week_in_ranges, parity_ok)

ok = fail = 0


def check(name, cond, detail=''):
    global ok, fail
    if cond:
        ok += 1
        print('PASS | %s | %s' % (name, detail))
    else:
        fail += 1
        print('FAIL | %s | %s' % (name, detail))


D = datetime.date

# ---- 1. monday_of ----
check('monday_of 周一', monday_of(D(2026, 8, 28)) == D(2026, 8, 24),
      '2026-08-28(五) → 2026-08-24')
check('monday_of 已为周一', monday_of(D(2026, 8, 24)) == D(2026, 8, 24))

# ---- 2. parse_week_ranges ----
check('范围解析 1,3-5,8-12', parse_week_ranges('1,3-5,8-12')
      == [1, 3, 4, 5, 8, 9, 10, 11, 12])
check('范围解析 空串/None', parse_week_ranges('') is None
      and parse_week_ranges(None) is None)
check('范围解析 中文逗号 + 空白', parse_week_ranges(' 1，3-5 ') == [1, 3, 4, 5])
check('范围解析 非法输入忽略', parse_week_ranges('abc,0,99,2') == [2])
check('范围解析 倒序区间忽略', parse_week_ranges('5-2') is None)
check('范围解析 全非法 → None', parse_week_ranges('x,y') is None)

# ---- 3. week_no_of（锚点=学期起始日所在周） ----
anchor = D(2026, 6, 23)     # 第一学期 term_start_date（第一学期 2026-06-23）
# 锚点所在周 = 第 1 周：2026-06-22(周一)~06-28(周日)
check('锚点周=1', week_no_of(D(2026, 6, 24), anchor) == 1)
check('当前周(08-28)=10', week_no_of(D(2026, 8, 28), anchor) == 10,
      '2026-08-24(周一) 为第10周')
check('无锚点 None', week_no_of(D(2026, 8, 28), None) is None)

# ---- 4. week_in_ranges / parity_ok ----
r = parse_week_ranges('1,3-5,8-12')
check('命中区间', week_in_ranges(3, r) and week_in_ranges(12, r))
check('未命中区间', not week_in_ranges(6, r))
check('未限定恒 True', week_in_ranges(6, None))
check('每周=True', parity_ok(7, 'weekly') and parity_ok(2, 'weekly'))
check('单周', parity_ok(1, 'odd') and parity_ok(3, 'odd')
      and not parity_ok(2, 'odd'))
check('双周', parity_ok(2, 'even') and not parity_ok(1, 'even'))
check('空参数兼容每周', parity_ok(7, '') and parity_ok(7, None))

print('\n== %d passed, %d failed ==' % (ok, fail))
sys.exit(1 if fail else 0)