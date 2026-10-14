# -*- coding: utf-8 -*-
"""t3 攻击脚本（HTTP 侧，**手动运行**，不在 run_smoke.sh 里）。

攻击目标：
  L1b 旧打卡写入口（已收口）——重复 POST 不得产生任何写入，也不得靠缺 csrf 报 500；
  L6 越权探测 /my/fees & /my/assets（不得泄露别人的账单/借还单）。

运行：python3 tests/smoke/attack_checkin_replay.py   (stu@local/demo123)
期望结果：L1b 全部 PASS（旧写入口 303 且两张表行数不变）；L6 无泄露。
退出码：0 = 全部 PASS；1 = 存在 FAIL。
"""
import os
import re
import sys

import requests

BASE = "http://localhost:8069"
DB, LOGIN, PASSWORD = "edu19", "stu@local", "demo123"
CSRF_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')
LEAK_MARKERS = ["【冒烟】学生B", "【冒烟】B-账单", "冒烟"]

s = requests.Session()
s.trust_env = False  # 绕过系统代理直连
r = s.post(f"{BASE}/web/session/authenticate", json={
    "jsonrpc": "2.0",
    "params": {"db": DB, "login": LOGIN, "password": PASSWORD}})
uid = r.json().get("result", {}).get("uid")
print("[login] HTTP %s uid=%s session=%s"
      % (r.status_code, uid, "session_id" in s.cookies.get_dict()))
if not uid:
    print("LOGIN_FAIL"); sys.exit(1)

print("\n===== L1b 旧打卡写入口（收口后必须只读）=====")
_L1B_FAIL = []


def _l1b(name, ok, ev):
    print(("%s %s  :: %s" % ("PASS" if ok else "FAIL", name, ev)))
    if not ok:
        _L1B_FAIL.append(name)


def _count(table, where="true"):
    import subprocess
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "odoo",
         "-d", DB, "-tAc", "SELECT count(*) FROM %s WHERE %s" % (table, where)],
        capture_output=True, text=True, timeout=60,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))))
    return out.stdout.strip()


_sid = s.get(f"{BASE}/my/checkins", timeout=25)
_m = CSRF_RE.search(_sid.text)
csrf = _m.group(1) if _m else ""

# (a) 旧页必须 303 到 /my/checkins（不再渲染旧表单）
r0 = s.get(f"{BASE}/my/checkin", timeout=25, allow_redirects=False)
_l1b("GET /my/checkin -> 303 /my/checkins",
     r0.status_code == 303 and r0.headers.get("Location", "").endswith("/my/checkins"),
     "HTTP %s Location=%s" % (r0.status_code, r0.headers.get("Location")))
_l1b("旧页不再渲染旧表单（无 /my/checkin/save 动作）",
     "/my/checkin/save" not in r0.text, "len=%d" % len(r0.text))

# (b) 旧写入口重复 POST：不得落库、不得 500
_d0 = _count("edu_daily_checkin")
_r0 = _count("edu_checkin_record")
for i in (1, 2):
    r = s.post(f"{BASE}/my/checkin/save",
               data={"attend": "on", "bible_passage": "创1-3章",
                     "csrf_token": csrf},
               timeout=25, allow_redirects=False)
    loc = r.headers.get("Location", "")
    _l1b("POST#%d /my/checkin/save -> 303 /my/checkins" % i,
         r.status_code == 303 and loc.endswith("/my/checkins"),
         "HTTP %s Location=%s" % (r.status_code, loc))
_d1 = _count("edu_daily_checkin")
_r1 = _count("edu_checkin_record")
_l1b("重复 POST 后 edu_daily_checkin 行数不变",
     _d0 == _d1, "%s -> %s" % (_d0, _d1))
_l1b("重复 POST 后 edu_checkin_record 行数不变",
     _r0 == _r1, "%s -> %s" % (_r0, _r1))

# (c) 旧写入口不带 csrf：也不得进入落库分支（不能 5xx）
r_nocsrf = s.post(f"{BASE}/my/checkin/save", data={"attend": "on"},
                  timeout=25, allow_redirects=False)
_l1b("旧写入口 POST 无 csrf 也不 5xx",
     r_nocsrf.status_code < 500,
     "HTTP %s" % r_nocsrf.status_code)

# (d) 新写入口：必须受 csrf 制约（无 csrf -> 400），且型号合法时幂等
r_new_nocsrf = s.post(f"{BASE}/my/checkins/check", data={"type_id": "1"},
                      timeout=25, allow_redirects=False)
_l1b("新写入口无 csrf -> 400（csrf 生效）",
     r_new_nocsrf.status_code == 400, "HTTP %s" % r_new_nocsrf.status_code)
_new_before = _count("edu_checkin_record",
                     "student_id=(SELECT s.id FROM op_student s JOIN res_users u "
                     "ON u.id=s.user_id WHERE u.login='stu@local')")
r_bad = s.post(f"{BASE}/my/checkins/check",
               data={"csrf_token": csrf, "type_id": "999999"},
               timeout=25, allow_redirects=False)
_l1b("新写入口传非法 type_id -> 303 error=1（不建行）",
     r_bad.status_code == 303
     and r_bad.headers.get("Location", "").endswith("/my/checkins?error=1"),
     "HTTP %s Location=%s" % (r_bad.status_code, r_bad.headers.get("Location")))
_new_after = _count("edu_checkin_record",
                    "student_id=(SELECT s.id FROM op_student s JOIN res_users u "
                    "ON u.id=s.user_id WHERE u.login='stu@local')")
_l1b("非法 type_id 不产生新行",
     _new_before == _new_after, "%s -> %s" % (_new_before, _new_after))

print("\nL1b_VERDICT", "PASS" if not _L1B_FAIL else "FAIL %s" % _L1B_FAIL)

print("\n===== L6 越权探测 /my/fees & /my/assets =====")
r_fees = s.get(f"{BASE}/my/fees", timeout=25)
fees_html = r_fees.text
leak_fees = [k for k in LEAK_MARKERS if k in fees_html]
own_bill_ok = "2026 春季统筹费" in fees_html or "教材资料费" in fees_html
print("GET /my/fees HTTP %s len=%d 泄漏标记=%s 自身账单可见=%s"
      % (r_fees.status_code, len(fees_html), leak_fees or "无", own_bill_ok))
# 页面上出现的所有账单名称行（粗提取）
bill_names = set(re.findall(r'【[^】]{1,20}】[^<\n]{0,20}', fees_html))
print("页面出现的【】标记:", sorted(bill_names)[:10])

r_ast = s.get(f"{BASE}/my/assets", timeout=25)
ast_html = r_ast.text
leak_ast = [k for k in LEAK_MARKERS if k in ast_html]
print("GET /my/assets HTTP %s len=%d 泄漏标记=%s"
      % (r_ast.status_code, len(ast_html), leak_ast or "无"))
loan_rows = re.findall(r'待审批|已借出|已归还', ast_html)
print("借还状态词出现次数:", {w: loan_rows.count(w) for w in set(loan_rows)})
# B 的借还单特征：requested_note「【冒烟】B 的借还单」若渲染必含该串
print("B 借还单备注泄漏=", "B 的借还单" in ast_html)

verdict_l1b = not _L1B_FAIL   # t9：旧写入口只读 + 新入口 csrf/type 制约，逐条断言后汇总
verdict_l6 = not leak_fees and not leak_ast
print("\nL6_VERDICT", "PASS(未越权)" if verdict_l6 else "FAIL(存在泄漏)")
print("L1b_VERDICT_FINAL", "PASS" if verdict_l1b else "FAIL")
print("\n总计：L1b %s / L6 %s"
      % ("PASS" if verdict_l1b else "FAIL",
         "PASS" if verdict_l6 else "FAIL"))
sys.exit(0 if (verdict_l1b and verdict_l6) else 1)
