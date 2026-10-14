# -*- coding: utf-8 -*-
"""t5 证据：教师 /checkins/stats 迁移前后对照。

「迁移前」= 把到堂类型临时 active=False 后取页/取 CSV（口径回到并集前），
「迁移后」= 恢复 active=True 再取。切换只动 edu.checkin.type.active，
不动任何业务记录；取完保证 active=True。
"""
import re
import subprocess
import sys

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _dbutil   # noqa: E402  (多路回退读库: DSN / 本地 PG / docker exec)
import requests

BASE = "http://localhost:8069"
FAIL = []


def check(name, cond, ev):
    print(("PASS " if cond else "FAIL ") + name + "  :: " + str(ev))
    if not cond:
        FAIL.append(name)


def psql(sql):
    """读一个标量（多路回退；容器内也能跑）。"""
    val, _how = _dbutil.scalar(sql)
    return str(val)



def login(user, pwd):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + "/web/session/authenticate", json={
        "jsonrpc": "2.0",
        "params": {"db": "edu19", "login": user, "password": pwd}},
        timeout=30)
    return s, (r.json().get("result") or {}).get("uid")


def grab(fac):
    page = fac.get(BASE + "/checkins/stats", timeout=30)
    body = page.text
    csv = fac.get(BASE + "/checkins/stats/export", timeout=30)
    rows = [r for r in csv.text.splitlines() if r.strip()]
    return {
        'status': page.status_code,
        'headers': re.findall(r'fa-[a-z-]+', body)[:0],  # 占位
        'has_attend': '到堂' in body,
        'csv_lines': len(rows),
        'csv_head': rows[0] if rows else '',
        'csv_body': rows[1] if len(rows) > 1 else '',
        'csv_all': rows,
    }


fac, uid = login("faculty@local", "demo123")
check("faculty 登录", bool(uid), "uid=%s" % uid)

tid = psql("SELECT id FROM edu_checkin_type WHERE name='到堂打卡'")
check("到堂类型存在", bool(tid), "id=%s" % tid)

# 迁移前口径：临时停用到堂类型
psql("UPDATE edu_checkin_type SET active=false WHERE id=%s" % tid)
before = grab(fac)
# 迁移后口径：恢复
psql("UPDATE edu_checkin_type SET active=true WHERE id=%s" % tid)
after = grab(fac)

check("到堂类型已恢复 active=True",
      psql("SELECT active FROM edu_checkin_type WHERE id=%s" % tid) == 't',
      psql("SELECT active FROM edu_checkin_type WHERE id=%s" % tid))
check("迁移前页面无「到堂」列", not before['has_attend'],
      "has_attend=%s" % before['has_attend'])
check("迁移后页面有「到堂」列", after['has_attend'],
      "has_attend=%s" % after['has_attend'])
check("迁移前 stats 200", before['status'] == 200, before['status'])
check("迁移后 stats 200", after['status'] == 200, after['status'])

print("\n[迁移前 CSV 表头] %s" % before['csv_head'])
print("[迁移后 CSV 表头] %s" % after['csv_head'])
print("[迁移前 CSV 数据行] %s" % before['csv_body'])
print("[迁移后 CSV 数据行] %s" % after['csv_body'])
print("[迁移前 CSV 行数] %d" % before['csv_lines'])
print("[迁移后 CSV 行数] %d" % after['csv_lines'])

open('/tmp/t5ev/stats_before.csv', 'w', encoding='utf-8').write(
    '\n'.join(before['csv_all']) + '\n')
open('/tmp/t5ev/stats_after.csv', 'w', encoding='utf-8').write(
    '\n'.join(after['csv_all']) + '\n')
print("\nFAIL=%d %s" % (len(FAIL), FAIL))
sys.exit(1 if FAIL else 0)
