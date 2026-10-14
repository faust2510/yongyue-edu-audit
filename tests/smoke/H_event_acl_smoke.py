#!/usr/bin/env python3
"""冒烟测试 H：edu.event ACL 收紧回归（评审 F1 遗留 · t16）。

目标 http://localhost:8069 (Odoo 19, docker edu19-clone, db edu19)。
账号：stu@local(学生)、parent@local(家长)、faculty@local(教师,base.group_system
成员)、admin(系统)。

背景：edu.event 在 t4 曾给 base.group_portal 只读 + base.group_user 全权，
门户用户可经 RPC search_read/read 读回全部活动数据（页面层过滤在但直读
无防线）。t16 按 t14（B9 修复轮）同口径收紧：ACL 仅保留 base.group_system
全权；calendar 控制器全程 sudo()，门户功能路径不受影响。

断言：
- S1/S2 门户账号（学生、家长）RPC search_read edu.event → 必须 AccessError
- S3  系统管理员 RPC 可读（无错误）
- S4-S6 门户功能回归：学生/家长/教师 /my/calendar 仍 200，教师含「新建活动」
输出 JSON 结果到 stdout（供写入报告）。只读冒烟，不造数、不写库。
"""
import json
import re
import sys
import requests

BASE = "http://localhost:8069"
DB = "edu19"
R = []  # (item, expect, actual, result, evidence)


def auth(login, pwd):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + "/web/session/authenticate",
               json={"jsonrpc": "2.0",
                     "params": {"db": DB, "login": login, "password": pwd}},
               timeout=60)
    uid = r.json().get("result", {}).get("uid")
    if not uid:
        raise SystemExit(f"login failed {login}")
    return s


def rec(item, expect, actual, result, evidence=""):
    R.append(dict(item=item, expect=expect, actual=actual, result=result,
                  evidence=evidence))
    print(f"[{result}] {item}: {actual}")


def rpc_call(s, model, method, args, kwargs=None):
    """JSON-RPC call_kw（与后端 web 客户端同协议）。"""
    r = s.post(BASE + "/web/dataset/call_kw", json={
        "jsonrpc": "2.0", "id": 1, "method": "call",
        "params": {"model": model, "method": method, "args": args,
                   "kwargs": kwargs or {}}}, timeout=60)
    return r.json()


def rpc_err(j):
    return str(j.get("error") or "")


def ok_get(s, path):
    r = s.get(BASE + path, timeout=60, allow_redirects=True)
    return r.status_code, r.text, "Traceback" in r.text


stu = auth("stu@local", "demo123")
par = auth("parent@local", "demo123")
fac = auth("faculty@local", "demo123")
adm = auth("admin", "admin")

# ================= S1/S2 门户直读必须 AccessError =================
j1 = rpc_call(stu, "edu.event", "search_read", [[]], {"limit": 5})
e1 = rpc_err(j1)
s1 = "AccessError" in e1
rec("S1 学生RPC search_read 拒读", "AccessError",
    e1.splitlines()[0][:90] if e1 else "未报错", "PASS" if s1 else "FAIL")

j2 = rpc_call(par, "edu.event", "search_read", [[]], {"limit": 5})
e2 = rpc_err(j2)
s2 = "AccessError" in e2
rec("S2 家长RPC search_read 拒读", "AccessError",
    e2.splitlines()[0][:90] if e2 else "未报错", "PASS" if s2 else "FAIL")

# 直读（read 方法）同口径拦截
j2b = rpc_call(stu, "edu.event", "read", [[1, 2]])
e2b = rpc_err(j2b)
s2b = "AccessError" in e2b
rec("S2b 学生RPC read 拒读", "AccessError",
    e2b.splitlines()[0][:90] if e2b else "未报错", "PASS" if s2b else "FAIL")

# ================= S3 系统账号可读 =================
j3 = rpc_call(adm, "edu.event", "search_read", [[]], {"limit": 5})
e3 = rpc_err(j3)
rows3 = j3.get("result") or []
s3 = not e3
rec("S3 系统管理员RPC 可读", "无错误",
    f"rows={len(rows3)}, err={e3.splitlines()[0][:60] if e3 else ''}",
    "PASS" if s3 else "FAIL")

# ================= S4-S6 门户功能回归（控制器 sudo，ACL 收紧不影响） =================
st, h, tb = ok_get(stu, "/my/calendar")
s4 = st == 200 and not tb
rec("S4 学生校历页 200", "200 无Traceback", f"status={st}, tb={tb}",
    "PASS" if s4 else "FAIL")

st, h, tb = ok_get(par, "/my/calendar")
s5 = st == 200 and not tb
rec("S5 家长校历页 200", "200 无Traceback", f"status={st}, tb={tb}",
    "PASS" if s5 else "FAIL")

st, h, tb = ok_get(fac, "/my/calendar")
s6 = st == 200 and not tb and "新建活动" in h and "/my/calendar/new" in h
rec("S6 教师校历页 200 含新建", "200 无Traceback含新建活动",
    f"status={st}, tb={tb}, new={('/my/calendar/new' in h)}",
    "PASS" if s6 else "FAIL")


# ================= 汇总 =================
fails = [x for x in R if x["result"] == "FAIL"]
print("\n===JSON===")
print(json.dumps(R, ensure_ascii=False, indent=1))
print("TOTAL", len(R), "FAIL", len(fails))
sys.exit(1 if fails else 0)