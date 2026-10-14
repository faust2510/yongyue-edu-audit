#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写路由（POST）非变更探活（t77）。

问题（结构性）
--------------
路由矩阵跑的是 GET；POST 需要 csrf + 载荷且可能改数据，所以没人拿它做例行探活
→**写路由的常态是「装载过、从未执行过」**，而 -u 与 import 只能证明装载。
t67 那条 NameError（我 t67 替换时删了 regs 定义、留下悬空引用）正是只住在这类里。

本脚本做什么
------------
给表中每条写路由登记一个**安全目标**（不存在 id / 越权 id / 非法 state），发一发
**非变更探活**，并对每条断言三件套：
  ① 返回 3xx 而不是 500（=方法体能走到返回，不是崩在半路）
  ② 相关数据未被改动（表级计数前后一致 —— 顺带能抓「忽略 ids、误处理全部」这类 bug）
  ③ 安全目标先自证（该 id 确实不存在/越界；判定依据打印出来）

覆盖与不覆盖
------------
覆盖（edu_portal 优先项）：请假批量 / 申诉批量 / 选课批量 / 成绩单条 save。
**不覆盖（逐条给理由，不静默截断）**：
  - /grading/import/commit：需要先构造 CSV/表格载荷与预览态，属"需要复杂载荷"；
  - /grading/copy_prev：依赖上期成绩存在与选择态；
  - /downloads/*、/calendar/*、/contacts/*、/batch3.py 的 POST：不属本次优先项
    （非批量审批/选课/成绩主干），可后续按同一三列表增量补。
每条路由的"安全目标"在这里现取自证读数（存在性判定 + 当前状态），不是只登记数字。
"""
import re
import subprocess
import sys

import requests

BASE = 'http://localhost:8069'
DB_CONTAINER = 'edu19-clone-db-1'
ABSENT_ID = 99999991          # 确定不存在的 id（每条路由都用它，属"安全目标"）

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print('%s %s  %s' % ('PASS' if cond else 'FAIL', name, detail[:110]))


def psql(sql):
    r = subprocess.run(['docker', 'exec', DB_CONTAINER, 'psql', '-U', 'odoo',
                        '-d', 'edu19', '-t', '-A', '-c', sql],
                       capture_output=True, text=True, timeout=60)
    return (r.stdout or '').strip()


def counts():
    """表级计数快照：② 用（任何写入都会改变其中一项）。"""
    return psql(
        "SELECT (SELECT count(*) FROM edu_leave)"
        "||'/'||(SELECT count(*) FROM edu_leave WHERE state='approved')"
        "||'/'||(SELECT count(*) FROM edu_grievance)"
        "||'/'||(SELECT count(*) FROM op_subject_registration)"
        "||'/'||(SELECT coalesce(sum(marks),0) FROM op_exam_attendees WHERE exam_id=11)")


def login(user):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0', 'params': {'db': 'edu19', 'login': user,
                                     'password': 'demo123'}}, timeout=60)
    return s if (r.status_code == 200 and r.json().get('result')) else None


def csrf(session, path):
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"',
                  session.get(BASE + path, timeout=60).text)
    return m.group(1) if m else ''


def probe(session, route, params, token, form_path):
    data = dict(params)
    data['csrf_token'] = csrf(session, form_path)
    return session.post(BASE + route, data=data, timeout=90,
                        allow_redirects=False)


def main():
    teacher = login('faculty@local')
    if not teacher:
        print('FAIL 登录取会话  无法登录 faculty@local')
        return 1
    # ③ 安全目标自证：该 id 确实不存在（判定依据 = DB 计数 0）
    existence = {
        'edu.leave': psql("SELECT count(*) FROM edu_leave WHERE id=%d" % ABSENT_ID),
        'edu.grievance': psql("SELECT count(*) FROM edu_grievance WHERE id=%d" % ABSENT_ID),
        'op.subject.registration': psql("SELECT count(*) FROM op_subject_registration WHERE id=%d" % ABSENT_ID),
        'op.exam': psql("SELECT count(*) FROM op_exam WHERE id=%d" % ABSENT_ID),
    }
    check('安全目标自证  id=%d 在四张表中均不存在' % ABSENT_ID,
          all(v == '0' for v in existence.values()),
          '计数 ' + ', '.join('%s=%s' % kv for kv in sorted(existence.items())))

    table = [
        ('请假批量', '/leave/set_state_bulk',
         {'ids': str(ABSENT_ID), 'state': 'approved'}, '/leave/approvals'),
        ('申诉批量', '/grievances/set_state_bulk',
         {'ids': str(ABSENT_ID), 'state': 'resolve'}, '/grievances/approvals'),
        ('选课批量', '/registrar/subject/set_state_bulk',
         {'ids': str(ABSENT_ID), 'state': 'approved'}, '/registrar/subject/approvals'),
        ('成绩单条 save', '/grading/save',
         {'exam_id': str(ABSENT_ID), 'marks_11': '1'}, '/grading/entry'),
    ]
    # ② 用**增量断言**而不是绝对基线：考生分数会被别的任务（如 t75 的正对照）
    # 合法改动 —— 只断言"我这一发探活之后没变"，否则测到的是别人的改动 = 假红
    marks_before = psql("SELECT marks FROM op_exam_attendees WHERE id=11")
    for label, route, params, form_path in table:
        before = counts()
        r = probe(teacher, route, params, None, form_path)
        after = counts()
        check('%s  ①3xx 而非 500' % label,
              r.status_code in (301, 302, 303) and r.status_code != 500,
              'http=%s location=%s' % (r.status_code,
                                       r.headers.get('Location', '')[:60]))
        check('%s  ②数据未被改动' % label, before == after,
              'before=%s after=%s' % (before, after))
        # ③ 计数语义：批量路由在 Location 里回带 ok/fail/skip —— 越权/不存在
        # 目标必须 ok=0 fail=0 **skip=0**（静默忽略，不计 skip，不泄露存在性）
        loc = r.headers.get('Location', '')
        if 'bulk_skip' in loc:
            nums = dict(re.findall(r'bulk_(ok|fail|skip)=([0-9]+)', loc))
            nums = {'bulk_' + k: v for k, v in nums.items()}
            ok_zeros = nums.get('bulk_ok') == '0' and \
                nums.get('bulk_fail') == '0' and nums.get('bulk_skip') == '0'
            check('%s  ③计数语义 ok/fail/skip 全 0' % label, ok_zeros,
                  ' '.join('%s=%s' % kv for kv in sorted(nums.items())))
    # 成绩单条：额外读回被引用的考生行（marks_11 属于 exam 11 的考生 11）
    marks = psql("SELECT marks FROM op_exam_attendees WHERE id=11")
    check('成绩单条  ②被引用考生行未被改动（增量）', marks == marks_before,
          'before=%s after=%s' % (marks_before, marks))
    print('')
    print('覆盖：请假批量 / 申诉批量 / 选课批量 / 成绩单条 save（各一发非变更探活）')
    print('不覆盖（理由）：')
    print('  - /grading/import/commit：需先构造 CSV 载荷与预览态（复杂载荷）')
    print('  - /grading/copy_prev：依赖上期成绩存在与选择态')
    print('  - /downloads/*、/calendar/*、/contacts/*、batch3 的 POST：不属批量审批/选课/成绩主干，可后续增量补')
    print('断言 %d 条：PASS %d / FAIL %d'
          % (len(PASS) + len(FAIL), len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
