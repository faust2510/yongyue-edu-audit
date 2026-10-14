# -*- coding: utf-8 -*-
"""t5 HTTP 证据：/my/checkin* 的 303 目标 + 旧写路由不落库。"""
import re
import subprocess
import sys

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _dbutil   # noqa: E402  (多路回退读库: DSN / 本地 PG / docker exec)
import requests

BASE = "http://localhost:8069"
DB, LOGIN, PWD = "edu19", "stu@local", "demo123"
FAIL = []


def check(name, cond, ev):
    print(("PASS " if cond else "FAIL ") + name + "  :: " + str(ev))
    if not cond:
        FAIL.append(name)


def psql(sql):
    """读一个标量（多路回退；容器内也能跑）。"""
    val, _how = _dbutil.scalar(sql)
    return str(val)



s = requests.Session()
s.trust_env = False
r = s.post(BASE + "/web/session/authenticate", json={
    "jsonrpc": "2.0",
    "params": {"db": DB, "login": LOGIN, "password": PWD}}, timeout=30)
uid = (r.json().get("result") or {}).get("uid")
check("stu@local 登录成功", bool(uid), "uid=%s" % uid)

before_daily = psql("SELECT count(*) FROM edu_daily_checkin")
before_rec = psql("SELECT count(*) FROM edu_checkin_record")

for path, want in (("/my/checkin", "/my/checkins"),
                   ("/my/checkin/export", "/my/checkins/export"),
                   ("/my/checkin/board", "/my/checkins")):
    rr = s.get(BASE + path, timeout=30, allow_redirects=False)
    loc = rr.headers.get("Location", "")
    check("GET %s -> 303" % path, rr.status_code == 303,
          "HTTP %s Location=%s" % (rr.status_code, loc))
    check("GET %s 目标 = %s" % (path, want), loc.endswith(want),
          "Location=%s" % loc)

# 旧写路由：GET 直连也断
rr = s.get(BASE + "/my/checkin/save", timeout=30, allow_redirects=False)
check("GET /my/checkin/save -> 303（直连也断）", rr.status_code == 303,
      "HTTP %s Location=%s" % (rr.status_code, rr.headers.get("Location")))
check("GET /my/checkin/save 目标 = /my/checkins",
      rr.headers.get("Location", "").endswith("/my/checkins"),
      rr.headers.get("Location"))

# 旧写路由：POST 带 csrf（合法会话）也不得落库
page = s.get(BASE + "/my/checkins", timeout=30)
m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text)
csrf = m.group(1) if m else ""
check("从新页取到 csrf", bool(csrf), "csrf=%s" % bool(csrf))
rr = s.post(BASE + "/my/checkin/save",
            data={"csrf_token": csrf, "attend": "on",
                  "bible_passage": "创1-3章"}, timeout=30,
            allow_redirects=False)
check("POST /my/checkin/save -> 303", rr.status_code == 303,
      "HTTP %s Location=%s" % (rr.status_code, rr.headers.get("Location")))
check("POST /my/checkin/save 目标 = /my/checkins",
      rr.headers.get("Location", "").endswith("/my/checkins"),
      rr.headers.get("Location"))
check("POST 后 Location 不含 saved=1（不回旧页语义）",
      "saved=1" not in rr.headers.get("Location", ""),
      rr.headers.get("Location"))

after_daily = psql("SELECT count(*) FROM edu_daily_checkin")
after_rec = psql("SELECT count(*) FROM edu_checkin_record")
check("旧表零增长", before_daily == after_daily,
      "%s -> %s" % (before_daily, after_daily))
check("新表零增长（旧 POST 不得经新页偷偷写）", before_rec == after_rec,
      "%s -> %s" % (before_rec, after_rec))

# 新页仍 200（收口后入口没坏）
rr = s.get(BASE + "/my/checkins", timeout=30, allow_redirects=False)
check("GET /my/checkins -> 200", rr.status_code == 200, "HTTP %s" % rr.status_code)
check("新页无 Traceback", "Traceback" not in rr.text, "len=%d" % len(rr.text))
print("\nFAIL=%d %s" % (len(FAIL), FAIL))
sys.exit(1 if FAIL else 0)
