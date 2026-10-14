#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""层级码注册「认领既有学生档案」端到端取证 / 回归（2026-09-24）。

要治的病：层级码注册**无条件新建** op.student ⇒ 教务已经预建好（有学号、已分班、
无账号）的学生一注册就多出一条同名档案：班上同名两条、课表/点名/成绩分散。

用法：
    python3 tests/smoke/register_claim_archive.py run       # 造夹具 → 走真实注册 → 断言 → 故障注入 → 自清
    python3 tests/smoke/register_claim_archive.py counts    # 只报计数
    python3 tests/smoke/register_claim_archive.py cleanup   # 兜底清场
结果落 tests/smoke/register_claim_archive_results.json；账号一律 claim-*@claim.local。

判据（每条都断言，raw 读数进报告）：
  A 学号命中（预建档案：有 gr_no / 无账号 / edu_pending_setup=False / 注册名≠化名）
      ⇒ op.student 总数 **+0**；该档案 user_id=新账号、edu_pending_setup=False、
        化名未被注册输入覆盖
  B 姓名命中（档案名带「【待分配】」前缀）⇒ +0，且前缀被清、edu_pending_setup=False
  C 同名两条（都空着）⇒ 不认领；+1；新档案 edu_dup_suspect=True 且说明含「疑似重复」
  D 同名档案已被别人挂走 ⇒ 不抢；+1；原档案 user_id 一字不变；新档案带疑似重复信号
  E 完全不命中 ⇒ 老路不回归：+1、edu_pending_setup=True、edu_dup_suspect=False
  F 学号大小写不一致 ⇒ 兜底仍命中；+0
  G 故障注入（odoo shell 把匹配器换成抛异常）⇒ 注册不受影响、退回新建、夹具未被挂走
"""
import json
import os
import re
import subprocess
import sys
import time
import xmlrpc.client
from pathlib import Path

import requests

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

BASE = os.environ.get("SMOKE_BASE", "http://localhost:8069")
DB = os.environ.get("EDU_DB_NAME", "edu19")
ADMIN_LOGIN = os.environ.get("EDU_ADMIN_LOGIN", "admin")
ADMIN_PWD = os.environ.get("EDU_ADMIN_PWD", "admin")
HERE = Path(__file__).resolve().parent
PHASE = (sys.argv[1] if len(sys.argv) > 1 else "run").lower()
STAMP = time.strftime("%m%d%H%M%S")
PWD_ = "demo123"
CHECKS = []
EVID = {"phase": PHASE, "stamp": STAMP, "cases": {}, "checks": CHECKS}

common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common")
# 本机 admin 口令实测是 demo123（仓内 demo 口令；register_race.py 那种只试 'admin' 的
# 写法在 2026-09-24 的本地 clone 上认证不过）。这里按候选表试，env 优先。
_CANDIDATES = [ADMIN_PWD, "demo123", "admin"]
UID = 0
for _pwd in _CANDIDATES:
    UID = common.authenticate(DB, ADMIN_LOGIN, _pwd, {})
    if UID:
        ADMIN_PWD = _pwd
        break
assert UID, "admin 认证失败（试过 %s）" % _CANDIDATES
OBJ = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object")

FIXTURES = {"codes": [], "students": [], "partners": [], "users": []}


def orm(model, method, *args, **kw):
    return OBJ.execute_kw(DB, UID, ADMIN_PWD, model, method, list(args), kw)


def check(case, label, ok, detail=None):
    CHECKS.append({"case": case, "label": label, "ok": bool(ok), "detail": detail})
    print("  [%s] %-46s %s" % ("PASS" if ok else "FAIL", label,
                               "" if detail is None else json.dumps(detail, ensure_ascii=False)[:300]))


def counts():
    return {
        "op_student": orm("op.student", "search_count", []),
        "res_users": orm("res.users", "search_count", []),
        "res_partner": orm("res.partner", "search_count", []),
        "edu_invite_code": orm("edu.invite.code", "search_count", []),
    }


def student_read(sid):
    rows = orm("op.student", "read", [sid], [
        "id", "name", "gr_no", "user_id", "partner_id", "edu_pending_setup",
        "edu_dup_suspect", "edu_claim_note"])
    return rows[0] if rows else {}


def user_of(email):
    ids = orm("res.users", "search", [("login", "=", email)])
    return ids[0] if ids else 0


def xmlid_res_id(xmlid):
    module, name = xmlid.split(".", 1)
    ids = orm("ir.model.data", "search",
              [("module", "=", module), ("name", "=", name)])
    return orm("ir.model.data", "read", ids, ["res_id"])[0]["res_id"]


def mk_archive(tag, name, gr_no=None, pending=False, owner_login=None):
    pid = orm("res.partner", "create", {"name": name})
    FIXTURES["partners"].append(pid)
    vals = {"partner_id": pid, "name": name, "gender": "m",
            "edu_pending_setup": bool(pending)}
    if gr_no:
        vals["gr_no"] = gr_no
    if owner_login:
        vals["user_id"] = user_of(owner_login)
    sid = orm("op.student", "create", vals)
    FIXTURES["students"].append(sid)
    return {"id": sid, "partner_id": pid, "name": name, "gr_no": gr_no}


def mk_code(tag):
    code = "CLAIM-%s-%s" % (tag, STAMP)
    cid = orm("edu.invite.code", "create", {
        "code": code, "code_kind": "tier", "tier": "student",
        "note": "【冒烟】认领既有档案"})
    FIXTURES["codes"].append(cid)
    return code


def mk_user(login, name):
    uid = orm("res.users", "create", {
        "login": login, "name": name, "email": login, "password": PWD_,
        "group_ids": [(6, 0, [xmlid_res_id("base.group_portal")])]})
    FIXTURES["users"].append(uid)
    return uid


# ----------------------------------------------------------------------
# 真实注册路径（HTTP，与浏览器同一入口：GET /register 取 csrf → POST /register/submit）
# ----------------------------------------------------------------------
def csrf_of(html):
    m = (re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
         or re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html))
    return m.group(1) if m else None


def form_facts():
    r = requests.get(BASE + "/register", timeout=30)
    html = r.text
    return {
        "page_status": r.status_code,
        "gr_no_input": 'name="gr_no"' in html,
        "gr_no_label_for": 'for="reg-gr-no"' in html,
        "gr_no_id": 'id="reg-gr-no"' in html,
        "has_register_form": 'action="/register/submit"' in html,
    }


def register(code, email, name, gr_no=None):
    """走真实注册：不传 gr_no 时**完全不发这个字段**（复刻旧表单行为）。"""
    s = requests.Session()
    s.trust_env = False
    page = s.get(BASE + "/register", timeout=30)
    token = csrf_of(page.text)
    assert token, "注册页取 csrf 失败 status=%s" % page.status_code
    data = {"csrf_token": token, "code": code, "name": name, "email": email,
            "password": PWD_, "confirm": PWD_}
    if gr_no is not None:
        data["gr_no"] = gr_no
    r = s.post(BASE + "/register/submit", data=data, allow_redirects=False,
               timeout=30)
    session_id = ""
    m = re.search(r"session_id=([^;]+)", r.headers.get("Set-Cookie", ""))
    if m:
        session_id = m.group(1)
    return {"status": r.status_code, "location": r.headers.get("Location", ""),
            "sent_gr_no": gr_no is not None, "session_id": session_id}


def my_home(session_id):
    if not session_id:
        return None
    r = requests.get(BASE + "/my/home", cookies={"session_id": session_id},
                     allow_redirects=False, timeout=30)
    return {"status": r.status_code, "location": r.headers.get("Location", "")}


def case(name, **data):
    EVID["cases"][name] = data
    print("\n--- %s ---" % name)
    for k, v in data.items():
        print("  %-26s %s" % (k, json.dumps(v, ensure_ascii=False)[:600]))


# ----------------------------------------------------------------------
# 清场：本脚本命名空间（STAMP）下的一切，一处不留
# ----------------------------------------------------------------------
def cleanup(extra_user_logins=None):
    before = counts()
    logins = ["claim-owner-%s@claim.local" % STAMP] + list(extra_user_logins or [])
    uids = orm("res.users", "search", [("login", "in", logins)])
    uids += orm("res.users", "search", [("login", "like", "claim-%@claim.local")])
    uids = sorted(set(uids))
    sids = list(FIXTURES["students"])
    sids += orm("op.student", "search", [("user_id", "in", uids)])
    sids += orm("op.student", "search", [("gr_no", "like", "QA%s%%" % STAMP)])
    sids += orm("op.student", "search", [("name", "ilike", STAMP)])
    sids = sorted({i for i in sids if i})
    pids = list(FIXTURES["partners"])
    # 账号自己的 partner 是 res.users.create 建出来的（名字 = 注册名，注册失败/改名后
    # 可能**不含**时间戳，例如历史缺陷下被写成 'New'）⇒ 必须在删账号**之前**把
    # partner_id 记下来，否则删完就再也不知道它是哪一条了（实测漏过：留下 12 条孤儿伙伴）。
    pids += [r["partner_id"][0] for r in orm("res.users", "read", uids, ["partner_id"])
             if r.get("partner_id")]
    pids += orm("res.partner", "search", [("name", "ilike", STAMP)])
    pids = sorted({i for i in pids if i})
    pids_captured = list(pids)
    if sids:
        orm("op.student", "unlink", sids)
    # 顺序要紧：res.partner 上有「不能删与活动用户关联的联系人」的保护（实测报错：
    # 您不能删除与活动用户关联的联系人）⇒ 先删账号，再删伙伴。
    if uids:
        orm("res.users", "unlink", uids)
    pids = [i for i in pids if orm("res.partner", "search_count", [("id", "=", i)])]
    if pids:
        orm("res.partner", "unlink", pids)
    cids = orm("edu.invite.code", "search", [("code", "like", "CLAIM-%")])
    if cids:
        orm("edu.invite.code", "unlink", cids)
    # 审计留痕也是本脚本造的数据（认领/疑似重复两类），按时间戳命名空间一并清掉，
    # 免得本地库积一堆指向已删档案的假审计行。
    aids = orm("edu.audit.log", "search", [("detail", "ilike", STAMP)])
    if aids:
        orm("edu.audit.log", "unlink", aids)
    after = counts()
    still = orm("res.partner", "search_count", [("id", "in", pids_captured)])
    return {"before": before, "after": after,
            "removed": {"op_student": len(sids), "res_partner": len(pids),
                        "res_users": len(uids), "edu_invite_code": len(cids)},
            "partners_left": still}


if PHASE == "counts":
    print(json.dumps(counts(), ensure_ascii=False, indent=1))
    sys.exit(0)

if PHASE == "cleanup":
    print(json.dumps(cleanup(), ensure_ascii=False, indent=1))
    sys.exit(0)

# ======================================================================
# 0 基线 + 注册页形态
# ======================================================================
BASE_COUNTS = counts()
FORM = form_facts()
case("0_基线", counts=BASE_COUNTS, form=FORM)
check("0", "注册页 200 且表单在",
      FORM["page_status"] == 200 and FORM["has_register_form"], FORM)
check("0", "注册页新增「学号（选填）」控件且有可访问名（label for + id）",
      FORM["gr_no_input"] and FORM["gr_no_label_for"] and FORM["gr_no_id"], FORM)

# ---- 夹具（全部无账号，除 D 的占位账号外）----
A = mk_archive("A", "甲化名" + STAMP, gr_no="QA" + STAMP + "A")           # 预建：无前缀、非待分配
B = mk_archive("B", "【待分配】乙化名" + STAMP, gr_no="QA" + STAMP + "B",
               pending=True)                                             # 存量待分配档案
C1 = mk_archive("C1", "丙化名" + STAMP, gr_no="QA" + STAMP + "C1")
C2 = mk_archive("C2", "丙化名" + STAMP, gr_no="QA" + STAMP + "C2")
OWNER_LOGIN = "claim-owner-%s@claim.local" % STAMP
OWNER_UID = mk_user(OWNER_LOGIN, "冒烟占位账号")
D = mk_archive("D", "丁化名" + STAMP, gr_no="QA" + STAMP + "D",
               owner_login=OWNER_LOGIN)                                  # 已被别人挂走
F = mk_archive("F", "己化名" + STAMP, gr_no="QA" + STAMP + "F")
case("1_夹具", A=A, B=B, C1=C1, C2=C2, D=D, F=F, owner_login=OWNER_LOGIN,
     owner_uid=OWNER_UID, counts=counts())

# ======================================================================
# A 学号命中
# ======================================================================
email_a = "claim-a-%s@claim.local" % STAMP
n0 = counts()["op_student"]
reg_a = register(mk_code("A"), email_a, "注册名与化名不同" + STAMP,
                 gr_no="QA" + STAMP + "A")
n1 = counts()["op_student"]
uid_a = user_of(email_a)
A_after = student_read(A["id"])
partner_a = orm("res.users", "read", [uid_a], ["partner_id"])[0]["partner_id"]
case("A_学号命中", email=email_a, register=reg_a,
     my_home=my_home(reg_a["session_id"]), students_before=n0,
     students_after=n1, delta=n1 - n0, archive=A_after, new_account_uid=uid_a,
     account_partner=orm("res.partner", "read", [partner_a[0]], ["name"])[0]
     if partner_a else None,
     archive_partner=orm("res.partner", "read", [A["partner_id"]],
                         ["name", "user_id"])[0])
check("A", "注册成功（303 → /my/home）",
      reg_a["status"] == 303 and "/my/home" in reg_a["location"], reg_a)
check("A", "op.student 总数只 +0（未新建档案）", n1 - n0 == 0,
      {"before": n0, "after": n1})
check("A", "命中档案 user_id = 新账号",
      bool(A_after.get("user_id")) and A_after["user_id"][0] == uid_a, A_after.get("user_id"))
check("A", "命中档案 edu_pending_setup=False", A_after.get("edu_pending_setup") is False,
      A_after.get("edu_pending_setup"))
check("A", "档案 partner 名字未被注册输入覆盖（化名保留）",
      A_after.get("name") == "甲化名" + STAMP, A_after.get("name"))
check("A", "伙伴 user_id 也挂上了（把 partner 关联上）",
      bool(orm("res.partner", "read", [A["partner_id"]], ["user_id"])[0]["user_id"]),
      orm("res.partner", "read", [A["partner_id"]], ["user_id"])[0])
check("A", "认领留痕：edu.audit.log 有「层级码注册认领」",
      orm("edu.audit.log", "search_count",
          [("action", "=", "层级码注册认领"), ("res_id", "=", A["id"])]) >= 1)

# ======================================================================
# B 姓名命中（档案名带「【待分配】」前缀）
# ======================================================================
email_b = "claim-b-%s@claim.local" % STAMP
n0 = counts()["op_student"]
reg_b = register(mk_code("B"), email_b, "乙化名" + STAMP)   # 完全不发 gr_no
n1 = counts()["op_student"]
uid_b = user_of(email_b)
B_after = student_read(B["id"])
case("B_姓名命中", email=email_b, register=reg_b, my_home=my_home(reg_b["session_id"]),
     students_before=n0, students_after=n1, delta=n1 - n0, archive=B_after,
     partner=orm("res.partner", "read", [B["partner_id"]], ["name", "user_id"])[0])
check("B", "注册成功（303 → /my/home）",
      reg_b["status"] == 303 and "/my/home" in reg_b["location"], reg_b)
check("B", "不填学号也能注册，且总数只 +0", n1 - n0 == 0, {"before": n0, "after": n1})
check("B", "命中档案 user_id = 新账号",
      bool(B_after.get("user_id")) and B_after["user_id"][0] == uid_b, B_after.get("user_id"))
check("B", "edu_pending_setup 已清 False", B_after.get("edu_pending_setup") is False,
      B_after.get("edu_pending_setup"))
check("B", "伙伴名字的「【待分配】」前缀已清",
      B_after.get("name") == "乙化名" + STAMP
      and orm("res.partner", "read", [B["partner_id"]], ["name"])[0]["name"] == "乙化名" + STAMP,
      {"student_name": B_after.get("name"),
       "partner_name": orm("res.partner", "read", [B["partner_id"]], ["name"])[0]["name"]})

# ======================================================================
# C 同名两条 → 不认领、新建、留可筛信号
# ======================================================================
email_c = "claim-c-%s@claim.local" % STAMP
n0 = counts()["op_student"]
reg_c = register(mk_code("C"), email_c, "丙化名" + STAMP)
n1 = counts()["op_student"]
uid_c = user_of(email_c)
C1_after, C2_after = student_read(C1["id"]), student_read(C2["id"])
new_c = orm("op.student", "search", [("user_id", "=", uid_c)])
C_new = student_read(new_c[0]) if new_c else {}
case("C_同名两条", email=email_c, register=reg_c, students_before=n0,
     students_after=n1, delta=n1 - n0, c1=C1_after, c2=C2_after, new_archive=C_new,
     dup_filter_count=orm("op.student", "search_count", [("edu_dup_suspect", "=", True)]),
     audit=orm("edu.audit.log", "search_read",
               [("action", "=", "注册疑似重复")], ["res_id", "detail"]))
check("C", "注册仍成功", reg_c["status"] == 303, reg_c)
check("C", "同名两条都不认领（两条 user_id 仍为空）",
      not C1_after.get("user_id") and not C2_after.get("user_id"),
      {"c1": C1_after.get("user_id"), "c2": C2_after.get("user_id")})
check("C", "退回老路新建（总数 +1）", n1 - n0 == 1, {"before": n0, "after": n1})
check("C", "新档案带可筛信号 edu_dup_suspect=True", C_new.get("edu_dup_suspect") is True,
      C_new.get("edu_dup_suspect"))
check("C", "说明含「疑似重复」与两条候选编号",
      "疑似重复" in (C_new.get("edu_claim_note") or "")
      and ("#%s" % C1["id"]) in (C_new.get("edu_claim_note") or "")
      and ("#%s" % C2["id"]) in (C_new.get("edu_claim_note") or ""),
      C_new.get("edu_claim_note"))

# ======================================================================
# D 档案已被别人认领 → 不抢
# ======================================================================
email_d = "claim-d-%s@claim.local" % STAMP
n0 = counts()["op_student"]
reg_d = register(mk_code("D"), email_d, "丁化名" + STAMP)
n1 = counts()["op_student"]
uid_d = user_of(email_d)
D_after = student_read(D["id"])
new_d = orm("op.student", "search", [("user_id", "=", uid_d)])
D_new = student_read(new_d[0]) if new_d else {}
case("D_已被认领", email=email_d, register=reg_d, students_before=n0,
     students_after=n1, delta=n1 - n0, archive_after=D_after, new_archive=D_new)
check("D", "注册仍成功", reg_d["status"] == 303, reg_d)
check("D", "原档案未被抢（user_id 仍是原账号）",
      bool(D_after.get("user_id")) and D_after["user_id"][0] == OWNER_UID,
      {"archive_user_id": D_after.get("user_id"), "owner_uid": OWNER_UID})
check("D", "退回老路新建（总数 +1）", n1 - n0 == 1, {"before": n0, "after": n1})
check("D", "新档案带疑似重复信号", D_new.get("edu_dup_suspect") is True,
      D_new.get("edu_claim_note"))

# ======================================================================
# E 完全不命中 → 老路不回归
# ======================================================================
email_e = "claim-e-%s@claim.local" % STAMP
n0 = counts()["op_student"]
reg_e = register(mk_code("E"), email_e, "戊未命中" + STAMP)
n1 = counts()["op_student"]
uid_e = user_of(email_e)
new_e = orm("op.student", "search", [("user_id", "=", uid_e)])
E_new = student_read(new_e[0]) if new_e else {}
case("E_未命中", email=email_e, register=reg_e, students_before=n0,
     students_after=n1, delta=n1 - n0, new_archive=E_new)
check("E", "注册成功", reg_e["status"] == 303, reg_e)
check("E", "老路不回归：新建「待分配」档案（+1、edu_pending_setup=True）",
      n1 - n0 == 1 and E_new.get("edu_pending_setup") is True,
      {"delta": n1 - n0, "pending": E_new.get("edu_pending_setup")})
check("E", "未命中不误报疑似重复", E_new.get("edu_dup_suspect") is False,
      E_new.get("edu_dup_suspect"))
check("E", "名字带「【待分配】」前缀", (E_new.get("name") or "").startswith("【待分配】"),
      E_new.get("name"))

# ======================================================================
# F 学号大小写不一致 → 兜底命中
# ======================================================================
email_f = "claim-f-%s@claim.local" % STAMP
n0 = counts()["op_student"]
reg_f = register(mk_code("F"), email_f, "随便的注册名" + STAMP,
                 gr_no=("QA" + STAMP + "F").lower())
n1 = counts()["op_student"]
uid_f = user_of(email_f)
F_after = student_read(F["id"])
case("F_学号大小写兜底", email=email_f, register=reg_f, students_before=n0,
     students_after=n1, delta=n1 - n0, archive=F_after)
check("F", "小写学号仍命中既定档案（总数 +0）", n1 - n0 == 0,
      {"delta": n1 - n0, "user_id": F_after.get("user_id")})
check("F", "命中档案 user_id = 新账号",
      bool(F_after.get("user_id")) and F_after["user_id"][0] == uid_f, F_after.get("user_id"))

# ======================================================================
# G 故障注入（fail-safe）：匹配器抛异常 ⇒ 照样注册得了
# ======================================================================
try:
    payload = (HERE / "register_claim_failsafe_shell.py").read_text(encoding="utf-8")
    payload = payload.replace("__STAMP__", STAMP + "FZ")
    cmd = ("cat > /tmp/claim_fault.py && odoo shell --db_host=db --db_port=5432 "
           "--db_user=odoo --db_password=odoo -c /etc/odoo/odoo.conf -d edu19 "
           "--no-http < /tmp/claim_fault.py")
    p = subprocess.run(["docker", "compose", "exec", "-T", "web", "bash", "-lc", cmd],
                       input=payload, capture_output=True, text=True, timeout=900)
    out = p.stdout + p.stderr
    fault_json = clean_json = None
    for line in out.splitlines():
        if line.startswith("FAULT_JSON="):
            fault_json = json.loads(line[len("FAULT_JSON="):])
        if line.startswith("FAULT_CLEAN="):
            clean_json = json.loads(line[len("FAULT_CLEAN="):])
    FAULT = {
        "ran": True, "exit": p.returncode, "json": fault_json, "clean": clean_json,
        "logged_warning": "认领既有学生档案失败" in out,
        "log_lines": [ln for ln in out.splitlines() if "[edu_portal]" in ln][-3:],
    }
except Exception as exc:                                          # noqa: BLE001
    FAULT = {"ran": False, "error": "%s: %s" % (type(exc).__name__, exc)}

case("G_故障注入", **FAULT)
j = (FAULT.get("json") or {})
check("G", "故障注入跑起来了", FAULT.get("ran") and bool(j), FAULT.get("error") or FAULT.get("exit"))
if j:
    check("G", "匹配器抛异常时注册路径不崩（无异常抛出）", j.get("outcome") == "no-exception",
          j.get("outcome"))
    check("G", "退回老路新建待分配档案（+1）", j.get("students_delta") == 1,
          j.get("students_delta"))
    check("G", "savepoint 生效：夹具档案未被挂上账号", j.get("fixture_claimed") is False,
          j.get("fixture_claimed"))
    check("G", "新建档案是待分配且有新账号",
          j.get("new_archive_pending") is True
          and j.get("new_archive_user_id_is_new_account") is True, j)
    check("G", "失败被记日志", FAULT.get("logged_warning") is True, FAULT.get("log_lines"))
    check("G", "自清干净（students/codes/users 残留均为 0）",
          all(v == 0 for v in (FAULT.get("clean") or {}).values()), FAULT.get("clean"))

# ======================================================================
# H 清场 + 计数对账
# ======================================================================
CLEAN = cleanup(extra_user_logins=[email_a, email_b, email_c, email_d, email_e, email_f])
# 命名空间残留自查（真正的「造的数据是否清干净」判据；与全局计数分开，因为本地库
# 同时还有别的会话在造/清数据，全局计数会被并发扰动）
LEFTOVER = {
    "students_gr_no_like": orm("op.student", "search_count",
                               [("gr_no", "like", "QA%s%%" % STAMP)]),
    "students_name_like": orm("op.student", "search_count",
                              [("name", "ilike", STAMP)]),
    "partners_name_like": orm("res.partner", "search_count",
                              [("name", "ilike", STAMP)]),
    "users_claim_login": orm("res.users", "search_count",
                             [("login", "like", "claim-%@claim.local")]),
    "codes_claim_prefix": orm("edu.invite.code", "search_count",
                              [("code", "like", "CLAIM-%")]),
    "audit_rows_like_stamp": orm("edu.audit.log", "search_count",
                                 [("detail", "ilike", STAMP)]),
    # 本脚本建过的每一伙伴（含账号自带的 partner）都必须一条不剩
    "partners_created_left": CLEAN["partners_left"],
}
CLEAN["namespace_leftover"] = LEFTOVER
case("H_清场", **CLEAN)
check("H", "清场后本脚本命名空间残留全为 0（造的数据一处不留）",
      all(v == 0 for v in LEFTOVER.values()), LEFTOVER)
check("H", "清场后 op.student 不高于基线（未净增）",
      CLEAN["after"]["op_student"] <= BASE_COUNTS["op_student"],
      {"base": BASE_COUNTS["op_student"], "after": CLEAN["after"]["op_student"]})
check("H", "清场后 res.users 不高于基线（未净增）",
      CLEAN["after"]["res_users"] <= BASE_COUNTS["res_users"],
      {"base": BASE_COUNTS["res_users"], "after": CLEAN["after"]["res_users"]})

EVID["summary"] = {
    "checks": len(CHECKS),
    "passed": sum(1 for c in CHECKS if c["ok"]),
    "failed": [c for c in CHECKS if not c["ok"]],
}
out = HERE / "register_claim_archive_results.json"
out.write_text(json.dumps(EVID, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n==== 汇总：%d/%d 通过；结果 -> %s ====" %
      (EVID["summary"]["passed"], EVID["summary"]["checks"], out))
if EVID["summary"]["failed"]:
    print(json.dumps(EVID["summary"]["failed"], ensure_ascii=False, indent=1))
    sys.exit(1)
