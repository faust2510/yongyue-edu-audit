# -*- coding: utf-8 -*-
"""F4 打卡按钮（接通 F1 定时提醒）的回归用例 —— **不需要数据库、不需要 Odoo**。

为什么值得单测这几件事：
  · callback_data 是 Telegram 的硬约束战场：限 64 字节，超了整条消息会被拒 ⇒
    生成失败必须**放弃按钮、改发纯文本**，绝不能把坏数据发出去；
  · 前缀 p: 必须与 @提醒待办（F5）的 ck: 严格分流 —— 抢了 ck: 会让 F5 静默失效；
  · 「谁没回」是纯过滤 + 集合运算，钉住它就不必造一整套群聊来测。

用法：python3 tests/unit/tg_assist_poll_test.py   （退出码 0=全通过 / 1=有失败）
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist', 'polls.py')

_spec = importlib.util.spec_from_file_location('tg_assist_polls', SPEC)
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


# ---------- 1) 选项 spec 解析 ----------
check('默认两选项', P.parse_options('done|abnormal') == ('done', 'abnormal'))
check('去空、去重、保序', P.parse_options(' a || b |a|  ') == ('a', 'b'))
check('空 spec -> 空元组', P.parse_options('') == () and P.parse_options(None) == ())
check('有上界 MAX_OPTIONS',
      len(P.parse_options('|'.join('v%d' % i for i in range(50)))) == P.MAX_OPTIONS)
check('已知选项给中文文案', P.label_for('done') == '已完成并达标')
check('未知选项原样当文案', P.label_for('late') == 'late')

# ---------- 2) callback_data 生成（64 字节硬线）----------
check('正常生成 p:<id>:<choice>', P.build_callback(12, 'done') == 'p:12:done')
check('非法 id -> None', P.build_callback('x', 'done') is None)
check('空 id -> None', P.build_callback(None, 'done') is None)
check('超 64 字节 -> None', P.build_callback(12, 'x' * 60) is None)
_exact = P.build_callback(12, 'x' * 59)
check('恰好 64 字节可用',
      _exact is not None and len(_exact.encode('utf-8')) == 64, str(_exact))

# ---------- 3) 解析与分流（不抢 ck:）----------
check('解析自己', P.parse_callback('p:12:done') == (12, 'done'))
check('不认 ck:（F5 的）', P.parse_callback('ck:12:done') == (None, None))
check('不认两段', P.parse_callback('p:12') == (None, None))
check('不认四段', P.parse_callback('p:12:done:x') == (None, None))
check('不认非数字 id', P.parse_callback('p:abc:done') == (None, None))
check('不认空选项', P.parse_callback('p:12:') == (None, None))
check('空串 / None 安全',
      P.parse_callback('') == (None, None) and P.parse_callback(None) == (None, None))

# ---------- 4) 应回名单 ----------
ROWS = [
    {'name': '张三', 'role': 'dorm_head', 'active': True, 'tg_user_id': '1'},
    {'name': '李四', 'role': 'teacher', 'active': True, 'tg_user_id': '2'},
    {'name': '王五', 'role': 'dorm_head', 'active': False, 'tg_user_id': '3'},
]
ROSTER = P.filter_roster(ROWS, 'dorm_head')
check('只留角色相符且启用的人', [r['name'] for r in ROSTER] == ['张三'], str(ROSTER))
check('all = 全体启用的人',
      [r['name'] for r in P.filter_roster(ROWS, 'all')] == ['张三', '李四'])
check('空角色当 all', len(P.filter_roster(ROWS, '')) == 2)
check('非 dict 行不炸', P.filter_roster([None, 'x', ROWS[0]], 'all') == [ROWS[0]])
check('active=False 的人不算进应回', P.filter_roster([ROWS[2]], 'all') == [])

# ---------- 5) 谁没回 ----------
check('没回的才算未回', P.missing_uids(ROSTER, ['9']) == ['1'])
check('回了就不在未回里', P.missing_uids(ROSTER, ['1', 9]) == [])
check('回的是别人的号不算', P.missing_uids(ROSTER, ['2']) == ['1'])
check('None 安全', P.missing_uids(ROSTER, None) == ['1'] and P.missing_uids([], None) == [])

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    line = ('PASS  ' if ok else 'FAIL  ') + name
    if detail and not ok:
        line += '   <- ' + detail
    print(line)
print('----')
print('共 %s 条，失败 %s 条' % (len(results), len(failed)))
sys.exit(1 if failed else 0)
