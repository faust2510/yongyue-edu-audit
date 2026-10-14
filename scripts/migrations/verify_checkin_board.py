# -*- coding: utf-8 -*-
"""t5 证据：内部用户看板仍 200 且数据源 = edu.checkin.record（到堂）。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _dbutil   # noqa: E402  (多路回退读库：DSN / 本地 PG / docker exec)

import requests

BASE = "http://localhost:8069"
DB = "edu19"
FAIL = []


def check(name, cond, ev):
    print(("PASS " if cond else "FAIL ") + name + "  :: " + str(ev))
    if not cond:
        FAIL.append(name)


def login(user, pwd):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + "/web/session/authenticate", json={
        "jsonrpc": "2.0",
        "params": {"db": DB, "login": user, "password": pwd}}, timeout=30)
    return s, (r.json().get("result") or {}).get("uid")


fac, uid = login("faculty@local", "demo123")
check("faculty@local 登录", bool(uid), "uid=%s" % uid)
rr = fac.get(BASE + "/my/checkin/board", timeout=30, allow_redirects=False)
check("教师 GET /my/checkin/board -> 200", rr.status_code == 200,
      "HTTP %s" % rr.status_code)
check("看板无 Traceback", "Traceback" not in rr.text, "len=%d" % len(rr.text))
check("看板标题在页内", "打卡看板" in rr.text, "打卡看板 in body")
check("看板返回链接指向 /my/checkins（不再多一跳）",
      'href="/my/checkins"' in rr.text or "/my/checkins" in rr.text,
      "found /my/checkins")

q = ("SELECT count(*) FROM edu_checkin_record r JOIN edu_checkin_type t "
     "ON t.id=r.type_id WHERE t.name='到堂打卡' AND r.checkin_date >= "
     "(CURRENT_DATE - ((EXTRACT(ISODOW FROM CURRENT_DATE)::int - 1))) "
     "AND r.checkin_date <= CURRENT_DATE")
# 数据源证明：看板勾数必须等于库内本周到堂数
# （t9：原来走 subprocess+docker，在 odoo 容器内跑就 FileNotFoundError；
#   现在走 _dbutil 多路回退，宿主/容器都能读）
n_attend_week = int(_dbutil.scalar(q)[0])
# 看板每个 done 单元 = 一个 fa-check text-success
marks = len(re.findall(r'fa fa-check text-success', rr.text))
check("看板勾数 == 本周到堂记录数", marks == n_attend_week,
      "看板勾=%d, 库内本周到堂=%d" % (marks, n_attend_week))

# 教师统计仍可用（回归）
rr2 = fac.get(BASE + "/checkins/stats", timeout=30, allow_redirects=False)
check("教师 GET /checkins/stats -> 200", rr2.status_code == 200,
      "HTTP %s" % rr2.status_code)
check("统计页无 Traceback", "Traceback" not in rr2.text, "len=%d" % len(rr2.text))
check("统计页出现「到堂」列（并集口径已生效）", "到堂" in rr2.text,
      "到堂 in stats body")
print("\nFAIL=%d %s" % (len(FAIL), FAIL))
sys.exit(1 if FAIL else 0)
