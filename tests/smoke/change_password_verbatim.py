#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改密码「逐字保存」取证 / 回归（与 register_password_verbatim.py 同源事故）。

现象（2026-09-24 注册事故的同源第二处）：Odoo core 的 res.users._change_password
（base/models/res_users.py:920，19.0 部署版）第一行就是 `new_passwd = new_passwd.strip()`，
而登录端（session.authenticate / _check_credentials）不 strip ⇒ 把密码改成 "abc "
存的是 "abc"，本人用自己敲的 "abc " 永远登不上 —— 与注册路径同一个陷阱，另一扇门。

两个门都测（同一份期望，改前/改后反相）：
  D1 门户页 POST /my/password/save（controllers/my_password.py → change_password()）
  D2 XML-RPC res.users.change_password（= 该控制器内那一行调用的同一条 core 方法）

用法：
    python3 tests/smoke/change_password_verbatim.py before   # 改前基线（复现）
    python3 tests/smoke/change_password_verbatim.py after    # 改后回归
    python3 tests/smoke/change_password_verbatim.py cleanup  # 清场
结果落 tests/smoke/change_password_verbatim_<phase>.json；
账号一律 cpw-<tag>-<stamp>@cpw.local，清场见 cleanup。

判据：
  A 尾空格 / B 首空格：after = 敲什么就能用什么登（303 /my/home），去空格值登不上（200）；
                        before = 反相（core strip 静默改值）
  C 普通无空格密码：改密成功且新密码可登录
  D 纯空格：被明确拒收（人话点名「空格」），密码未被改（旧密码仍可登录）
  E 旧密码错：被拒（AccessDenied / 「当前密码不正确」），密码未变
  F 两次不一致：被拒（「两次输入的新密码不一致」），密码未变
  G 太短：被拒（「新密码至少 8 位」），密码未变
"""
import json
import os
import re
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
PHASE = (sys.argv[1] if len(sys.argv) > 1 else "before").lower()
STAMP = time.strftime("%m%d%H%M%S")
DOMAIN = "cpw.local"
INIT = "InitPass123"
EVID = {"phase": PHASE, "stamp": STAMP, "cases": {}, "counts": {}}

common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common")
UID_ADMIN = common.authenticate(DB, ADMIN_LOGIN, ADMIN_PWD, {})
assert UID_ADMIN, "admin 认证失败"
OBJ = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object")


def orm(model, method, *args, **kw):
    return OBJ.execute_kw(DB, UID_ADMIN, ADMIN_PWD, model, method, list(args), kw)


def counts():
    return {
        "res_users": orm("res.users", "search_count", []),
        "res_partner": orm("res.partner", "search_count", []),
        "mail_message": orm("mail.message", "search_count", []),
        "cpw_users": orm("res.users", "search_count", [["login", "like", "cpw-%@" + DOMAIN]]),
        "cpw_partners": orm("res.partner", "search_count", [["email", "like", "%@" + DOMAIN]]),
    }


def cpw_logins():
    return orm("res.users", "search", [["login", "like", "cpw-%@" + DOMAIN]])


def purge():
    """清掉本脚本的一次性账号/伙伴；返回 (users, partners)。"""
    uids = cpw_logins()
    if uids:
        orm("res.users", "unlink", uids)
    pids = orm("res.partner", "search", [["email", "like", "%@" + DOMAIN]])
    if pids:
        orm("res.partner", "unlink", pids)
    return len(uids), len(pids)


if PHASE == "cleanup":
    u, p = purge()
    print("cleanup: removed users=%d partners=%d" % (u, p))
    sys.exit(0)


CSRF_RE = re.compile(r'<input[^>]*name="csrf_token"[^>]*value="([^"]+)"')
BANNER_RE = re.compile(r'alert-danger[^>]*>(.*?)</div>', re.S)


def csrf(sess, path):
    html = sess.get(BASE + path, timeout=30).text
    m = CSRF_RE.search(html)
    assert m, "csrf_token 未在 %s 找到" % path
    return m.group(1)


def banner(html):
    out = []
    for raw in BANNER_RE.findall(html):
        txt = re.sub(r"<[^>]+>", "", raw)
        txt = re.sub(r"\s+", " ", txt).strip()
        if txt:
            out.append(txt)
    return " | ".join(out)


def mk_user(tag):
    """建一个门户组的一次性账号（初始密码 INIT，无空格）。"""
    login = "cpw-%s-%s@%s" % (tag, STAMP, DOMAIN)
    portal = orm("ir.model.data", "check_object_reference", "base", "group_portal")[1]
    uid = orm("res.users", "create", [{
        "name": "冒烟 cpw %s" % tag,
        "login": login,
        "email": login,
        "password": INIT,
        "group_ids": [(6, 0, [portal])],
    }])
    return uid, login


def login(login_, password):
    s = requests.Session()
    r = s.post(BASE + "/web/login", allow_redirects=False, timeout=30, data={
        "csrf_token": csrf(s, "/login"),
        "login": login_,
        "password": password,
    })
    home = s.get(BASE + "/my/home", allow_redirects=False, timeout=30)
    return {"status": r.status_code, "location": r.headers.get("Location", ""),
            "banner": banner(r.text), "home_status": home.status_code}


def ok(d):
    return d["status"] == 303 and "/my/home" in d["location"] and d["home_status"] == 200


def page_change(login_, password, old, new, confirm=None):
    """D1：门户页 /my/password/save（真实入口）。"""
    confirm = new if confirm is None else confirm
    s = requests.Session()
    s.post(BASE + "/web/login", allow_redirects=False, timeout=30, data={
        "csrf_token": csrf(s, "/login"), "login": login_, "password": password})
    r = s.post(BASE + "/my/password/save", allow_redirects=False, timeout=30, data={
        "csrf_token": csrf(s, "/my/password"),
        "old_password": old, "new_password": new, "confirm_password": confirm,
    })
    if r.status_code in (301, 302, 303):
        return {"status": r.status_code, "location": r.headers.get("Location", ""),
                "banner": banner(s.get(BASE + r.headers.get("Location", ""), timeout=30).text)}
    return {"status": r.status_code, "location": "", "banner": banner(r.text)}


def rpc_change(login_, password, old, new):
    """D2：XML-RPC res.users.change_password（= 控制器里那一行调的同一条 core 方法）。"""
    uid = common.authenticate(DB, login_, password, {})
    assert uid, "一次性账号 %s 认证失败" % login_
    try:
        OBJ.execute_kw(DB, uid, password, "res.users", "change_password", [old, new])
    except xmlrpc.client.Fault as e:
        return {"rpc": "fault", "error": e.faultString.strip().splitlines()[-1]}
    return {"rpc": "ok"}


def creds(login_, password):
    """_check_credentials 层证据：XML-RPC authenticate 返回 uid 或 False。"""
    return bool(common.authenticate(DB, login_, password, {}))


FAILED = []


def check(case, label, cond, payload):
    EVID["cases"].setdefault(case, {})[label] = {"pass": bool(cond), **payload}
    if not cond:
        FAILED.append("%s/%s -> %s" % (case, label, json.dumps(payload, ensure_ascii=False)))
    print("  [%s] %s: %s" % ("PASS" if cond else "FAIL", label,
                            json.dumps(payload, ensure_ascii=False)))


def space_case(case, tag, typed):
    """首/尾空格：after 期望「敲什么就能用什么登」，before 反相（复现 core strip）。"""
    print("[%s] 新密码 = %r" % (case, typed))
    uid, login_ = mk_user(tag)
    # --- D1 门户页 ---
    d1 = page_change(login_, INIT, INIT, typed)
    EVID["cases"].setdefault(case, {})["D1_page_before_fix_state"] = d1
    print("    D1 门户页: %s" % json.dumps(d1, ensure_ascii=False))
    if PHASE == "after":
        check(case, "D1 门户页 303 → ok=1（逐字收下带空格密码）",
              d1["status"] == 303 and "ok=1" in d1["location"], d1)
        good = login(login_, typed)
        bad = login(login_, typed.strip())
        check(case, "D1 login 用「敲的密码」（带空格）→ 303 /my/home", ok(good), good)
        check(case, "D1 login 用「去空格密码」→ 失败（不再静默改值）",
              not ok(bad) and bad["status"] == 200, bad)
    else:
        # 改前：控制器的新 != new.strip() 守卫先挡下（core strip 在本页不可达），
        # 如实记录为「页面拒收」——本次要修的就是它与注册/登录口径不一致。
        check(case, "D1 改前：门户页拒收（话术含「空格」）",
              "空格" in d1["banner"] and d1["status"] == 200, d1)
        check(case, "D1 改前：密码未变（旧密码仍可登录）", creds(login_, INIT),
              {"init_still_works": creds(login_, INIT)})

    # --- D2 core change_password（每例另建账号，避免上一步改变初始口令）---
    uid2, login2 = mk_user(tag + "r")
    d2 = rpc_change(login2, INIT, INIT, typed)
    EVID["cases"].setdefault(case, {})["D2_rpc"] = d2
    print("    D2 change_password(): %s" % json.dumps(d2, ensure_ascii=False))
    good = login(login2, typed)
    bad = login(login2, typed.strip())
    prov = {"typed_login": good, "stripped_login": bad,
            "check_credentials_typed": creds(login2, typed),
            "check_credentials_stripped": creds(login2, typed.strip())}
    EVID["cases"].setdefault(case, {})["D2_proof"] = prov
    if PHASE == "after":
        check(case, "D2 rpc ok", d2["rpc"] == "ok", d2)
        check(case, "D2 login 用「敲的密码」（带空格）→ 303 /my/home", ok(good), good)
        check(case, "D2 login 用「去空格密码」→ 失败（不再静默改值）",
              not ok(bad) and bad["status"] == 200, bad)
        check(case, "D2 _check_credentials：敲的密码 True / 去空格 False",
              prov["check_credentials_typed"] and not prov["check_credentials_stripped"], prov)
    else:
        check(case, "D2 改前复现：login 用「敲的密码」→ 失败", not ok(good), good)
        check(case, "D2 改前复现：login 用「去空格密码」→ 303 /my/home（core strip 静默改值）",
              ok(bad), bad)
        check(case, "D2 改前复现：_check_credentials 只认去空格值",
              prov["check_credentials_stripped"] and not prov["check_credentials_typed"], prov)


print("BASE=%s DB=%s phase=%s stamp=%s" % (BASE, DB, PHASE, STAMP))
# 先清掉上一轮（可能崩在半路）的残留，再取基线 —— 基线才可比。
stale_u, stale_p = purge()
if stale_u or stale_p:
    print("[pre] 清掉上一轮残留 users=%d partners=%d" % (stale_u, stale_p))
BASE_COUNTS = counts()
print("baseline counts:", json.dumps(BASE_COUNTS, ensure_ascii=False))

# ---- A 尾空格 / B 首空格 ----
space_case("A", "trail", "TestPass456 ")
space_case("B", "lead", " TestPass456")

# ---- C 普通无空格密码：改密成功且新密码可登录（回归） ----
print("[C] 普通密码（无空格）")
uid_c, login_c = mk_user("normal")
d1c = page_change(login_c, INIT, INIT, "NormalPass789")
new_ok = login(login_c, "NormalPass789")
old_bad = login(login_c, INIT)
EVID["cases"]["C"] = {"page": d1c, "new_login": new_ok, "old_login": old_bad}
check("C", "门户页改密 303 ok=1", d1c["status"] == 303 and "ok=1" in d1c["location"], d1c)
check("C", "新密码可登录 303 /my/home", ok(new_ok), new_ok)
check("C", "旧密码不再可用（改密真的生效）", not ok(old_bad), old_bad)
uid_c2, login_c2 = mk_user("normalr")
d2c = rpc_change(login_c2, INIT, INIT, "NormalPass789")
check("C", "D2 rpc 普通密码 ok", d2c["rpc"] == "ok", d2c)
check("C", "D2 新密码可登录", ok(login(login_c2, "NormalPass789")), {})

# ---- D 纯空格：明确拒收 + 密码未变 ----
print("[D] 纯空格密码 <8 个空格>")
uid_d, login_d = mk_user("blank")
d1d = page_change(login_d, INIT, INIT, " " * 8)
uid_d2, login_d2 = mk_user("blankr")
d2d = rpc_change(login_d2, INIT, INIT, " " * 8)
EVID["cases"]["D"] = {"page": d1d, "rpc": d2d,
                      "init_still_works": creds(login_d2, INIT)}
check("D", "门户页拒收且话术点名「空格」", "空格" in d1d["banner"] and d1d["status"] == 200, d1d)
check("D", "rpc 被拒（UserError，不是静默存值）", d2d["rpc"] == "fault", d2d)
if PHASE == "after":
    check("D", "rpc 话术点名「空格」", "空格" in d2d.get("error", ""), d2d)
check("D", "密码未变（旧密码仍可登录）", creds(login_d2, INIT),
      {"init_still_works": creds(login_d2, INIT)})

# ---- E 旧密码错 ----
print("[E] 旧密码错")
uid_e, login_e = mk_user("wrongold")
d1e = page_change(login_e, INIT, "WrongOld999", "NewPass1234")
d2e = rpc_change(login_e, INIT, "WrongOld999", "NewPass1234")
EVID["cases"]["E"] = {"page": d1e, "rpc": d2e, "init_still_works": creds(login_e, INIT)}
check("E", "门户页拒收「当前密码不正确」", "当前密码不正确" in d1e["banner"], d1e)
check("E", "rpc 抛错（AccessDenied）", d2e["rpc"] == "fault", d2e)
check("E", "密码未变", creds(login_e, INIT), {})

# ---- F 两次不一致 ----
print("[F] 新密码两次不一致")
uid_f, login_f = mk_user("mismatch")
d1f = page_change(login_f, INIT, INIT, "NewPass1234", "NewPass1235")
EVID["cases"]["F"] = {"page": d1f, "init_still_works": creds(login_f, INIT)}
check("F", "门户页拒收「两次输入的新密码不一致」", "不一致" in d1f["banner"], d1f)
check("F", "密码未变", creds(login_f, INIT), {})

# ---- G 太短 ----
print("[G] 新密码太短")
uid_g, login_g = mk_user("short")
d1g = page_change(login_g, INIT, INIT, "Ab1")
EVID["cases"]["G"] = {"page": d1g, "init_still_works": creds(login_g, INIT)}
check("G", "门户页拒收「新密码至少 8 位」", "至少 8 位" in d1g["banner"], d1g)
check("G", "密码未变", creds(login_g, INIT), {})

# ---- 清场 + 计数回基线 ----
purge()
AFTER_COUNTS = counts()
EVID["counts"] = {"baseline": BASE_COUNTS, "after_cleanup": AFTER_COUNTS,
                  "leftover_users": AFTER_COUNTS["cpw_users"],
                  "leftover_partners": AFTER_COUNTS["cpw_partners"]}
print("after cleanup counts: %s" % json.dumps(AFTER_COUNTS, ensure_ascii=False))
check("Z", "一次性账号/伙伴 0 残留",
      AFTER_COUNTS["cpw_users"] == 0 and AFTER_COUNTS["cpw_partners"] == 0, AFTER_COUNTS)
check("Z", "总量回基线（res_users/res_partner/mail_message）",
      all(AFTER_COUNTS[k] == BASE_COUNTS[k]
          for k in ("res_users", "res_partner", "mail_message")),
      {"baseline": BASE_COUNTS, "after": AFTER_COUNTS})

EVID["failed"] = FAILED
out = HERE / ("change_password_verbatim_%s.json" % PHASE)
out.write_text(json.dumps(EVID, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n%s\nEVIDENCE -> %s" % ("ALL PASS" if not FAILED else "FAILURES:\n" + "\n".join(FAILED), out))
sys.exit(1 if FAILED else 0)
