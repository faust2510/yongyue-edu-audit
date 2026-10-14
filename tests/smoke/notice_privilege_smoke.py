# -*- coding: utf-8 -*-
"""管理员/教务处特权冒烟：公告发布、请假审批、申诉处理（门禁型路由放行）。

口径：privileged_staff（教务处组或 system 组）可发布/审批；
学生与普通门户用户仍被重定向。临时公告用 docker psql 清理。
"""
import re
import subprocess
import sys

import requests

BASE = 'http://localhost:8069'
PASS, FAIL = [], []


def check(name, cond, extra=''):
    (PASS if cond else FAIL).append(name)
    print('%s %s%s' % ('PASS' if cond else 'FAIL', name,
                       (' | ' + str(extra)[:100]) if (extra and not cond) else ''))


def login(login_name, password):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': 'edu19', 'login': login_name,
                   'password': password}}, timeout=20)
    return s if (r.status_code == 200 and r.json().get('result')) else None


def csrf_of(session, path):
    t = session.get(BASE + path, timeout=20).text
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', t)
    return m.group(1) if m else ''


# ---------- 学生：仍被挡 ----------
stu = login('stu@local', 'demo123')
check('stu login', stu is not None)
r = stu.get(BASE + '/notice/publish', timeout=20, allow_redirects=False)
check('学生发布页被拒(303)', r.status_code in (302, 303))
r = stu.get(BASE + '/leave/approvals', timeout=20, allow_redirects=False)
check('学生请假审批被拒(303)', r.status_code in (302, 303))
r = stu.get(BASE + '/grievances/approvals', timeout=20, allow_redirects=False)
check('学生申诉处理被拒(303)', r.status_code in (302, 303))

# ---------- 教务/管理员（backoffice 未绑教师档案）：特权路径 ----------
bo = login('backoffice@local', 'demo123')
check('backoffice login', bo is not None)

r = bo.get(BASE + '/notice/publish', timeout=20)
check('管理员发布页 200', r.status_code == 200)
check('发布页含表单', 'notice/publish_save' in r.text)

r = bo.get(BASE + '/leave/approvals', timeout=20)
check('管理员请假审批 200', r.status_code == 200)
r = bo.get(BASE + '/grievances/approvals', timeout=20)
check('管理员申诉处理 200', r.status_code == 200)

t = bo.get(BASE + '/my/notice_board/notice', timeout=20).text
check('布告栏对管理员显示发布公告按钮',
      '发布公告' in t and '/notice/publish' in t)

# 发布一条【冒烟】公告（横幅开关不开，避免影响他人）
csrf = csrf_of(bo, '/notice/publish')
check('发布页取到 csrf', bool(csrf))
r = bo.post(BASE + '/notice/publish_save', data={
    'csrf_token': csrf,
    'name': '【冒烟】特权发布测试公告',
    'content': 'smoke notice body',
    'category': 'notice',
}, timeout=20, allow_redirects=False)
check('发布公告 303', r.status_code in (302, 303))

t = bo.get(BASE + '/my/notice_board/notice', timeout=20).text
check('布告栏出现冒烟公告', '【冒烟】特权发布测试公告' in t)

# 发送者应为账号名（非教师绑定名）
row = subprocess.run(
    ['docker', 'exec', 'edu19-clone-db-1', 'psql', '-U', 'odoo', '-d',
     'edu19', '-t', '-A', '-c',
     "SELECT sender FROM edu_notice WHERE name LIKE '%【冒烟】特权发布测试公告%' LIMIT 1"],
    capture_output=True, text=True, timeout=20)
check('发送者为账号名(非教师绑定)', row.stdout.strip() != '',
      row.stdout + row.stderr)

# ---------- 清理冒烟公告 ----------
subprocess.run(
    ['docker', 'exec', 'edu19-clone-db-1', 'psql', '-U', 'odoo', '-d',
     'edu19', '-c', "DELETE FROM edu_notice WHERE name LIKE '%【冒烟】特权发布测试公告%'"],
    capture_output=True, text=True, timeout=20)
t = bo.get(BASE + '/my/notice_board/notice', timeout=20).text
check('清理后布告栏无冒烟公告', '【冒烟】特权发布测试公告' not in t)

print('\n===== 特权冒烟结果: %d PASS / %d FAIL =====' % (len(PASS), len(FAIL)))
if FAIL:
    print('失败项:', *FAIL, sep='\n  - ')
    sys.exit(1)
