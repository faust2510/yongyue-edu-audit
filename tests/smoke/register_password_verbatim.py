#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""注册密码「逐字保存」事故取证 / 回归（2026-09-24 生产 edu.example.org）。

现象：邀请码注册成功后无法登录。根因（controllers/register.py 旧 :25-27）——
注册把 password/confirm 也 .strip() 了，而 Odoo 登录端不 strip ⇒ 密码首尾带空格的
学生（手机输入法很常见）存进去的是「去掉空格」的值，用自己敲的密码永远登不上。

用法：
    python3 tests/smoke/register_password_verbatim.py before   # 改前基线（复现）
    python3 tests/smoke/register_password_verbatim.py after    # 改后回归
结果落 tests/smoke/register_password_verbatim_<phase>.json；
账号一律 pwv-<stamp>@pwv.local、码一律 PWV-<stamp>-*，清场见 cleanup。

判据（phase=after；before 相应取反，即复现旧行为）：
  A 尾空格密码：注册 303；用「敲的密码」（带空格）登录 303 /my/home；不带空格登录失败
  B 首空格密码：同上
  C 普通无空格密码：注册 → 用原密码登录 303，不受影响
  D 纯空格密码：明确报错（不是静默存值），且不建号
  E 两次不一致 / F 太短 / G 必填为空：原校验话术仍在
  H 小写邀请码仍按大写命中（注册路径的其他归一化没被顺手改坏）
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
EVID = {"phase": PHASE, "stamp": STAMP, "cases": {}}

common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common")
UID = common.authenticate(DB, ADMIN_LOGIN, ADMIN_PWD, {})
assert UID, "admin 认证失败"
OBJ = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object")


def orm(model, method, *args, **kw):
    return OBJ.execute_kw(DB, UID, ADMIN_PWD, model, method, list(args), kw)


def mk_code(tag):
    code = f"PWV-{STAMP}-{tag}"
    orm("edu.invite.code", "create", [{
        "code": code, "code_kind": "person", "note": "【冒烟】注册密码逐字"}])
    return code


def users_with_login(login):
    return orm("res.users", "search_count", [("login", "=", login)])


if PHASE == "cleanup":
    uids = orm("res.users", "search", [("login", "like", "pwv-%@pwv.local")])
    orm("res.users", "unlink", uids)
    cids = orm("edu.invite.code", "search", [("code", "like", "PWV-%")])
    orm("edu.invite.code", "unlink", cids)
    print("cleanup: users=%d codes=%d" % (len(uids), len(cids)))
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


def register(email, password, code, name="冒烟 pwv", confirm=None):
    """返回 {status, location, banner, account_exists}。"""
    s = requests.Session()
    r = s.post(BASE + "/register/submit", allow_redirects=False, timeout=30, data={
        "csrf_token": csrf(s, "/register"),
        "code": code,
        "name": name,
        "email": email,
        "password": password,
        "confirm": password if confirm is None else confirm,
    })
    if r.status_code in (301, 302, 303):
        loc = r.headers.get("Location", "")
        err_page = s.get(BASE + loc, timeout=30).text
        bans = banner(err_page)
    else:
        loc, bans = "", banner(r.text)
    return {"status": r.status_code, "location": loc, "banner": bans,
            "account_exists": bool(users_with_login(email))}


def login(email, password):
    """返回 {status, location, banner, home_status}。"""
    s = requests.Session()
    r = s.post(BASE + "/web/login", allow_redirects=False, timeout=30, data={
        "csrf_token": csrf(s, "/login"),
        "login": email,
        "password": password,
    })
    home = s.get(BASE + "/my/home", allow_redirects=False, timeout=30)
    return {"status": r.status_code, "location": r.headers.get("Location", ""),
            "banner": banner(r.text), "home_status": home.status_code}


def ok(d):
    return d["status"] == 303 and "/my/home" in d["location"] and d["home_status"] == 200


FAILED = []


def check(case, label, cond, payload):
    EVID["cases"].setdefault(case, {})[label] = {"pass": bool(cond), **payload}
    if not cond:
        FAILED.append("%s/%s -> %s" % (case, label, json.dumps(payload, ensure_ascii=False)))
    print("  [%s] %s: %s" % ("PASS" if cond else "FAIL", label,
                            json.dumps(payload, ensure_ascii=False)))


def space_case(case, tag, typed):
    """首/尾空格密码：after 期望「敲什么就能用什么登」，before 反相（复现事故）。"""
    print("[%s] 密码 = %r" % (case, typed))
    email = "pwv-%s-%s@pwv.local" % (tag, STAMP)
    reg = register(email, typed, mk_code(tag.upper()))
    check(case, "register 303 /my/home", reg["status"] == 303 and "my/home" in reg["location"], reg)
    check(case, "account exists", reg["account_exists"], {"account_exists": reg["account_exists"]})
    good = login(email, typed)          # 学生敲的那个值（带空格）
    bad = login(email, typed.strip())   # 去掉空格的那个值
    if PHASE == "after":
        check(case, "login 用「敲的密码」（带空格）→ 303 /my/home", ok(good), good)
        check(case, "login 用「去空格密码」→ 失败（不再静默改值）",
              not ok(bad) and bad["status"] == 200, bad)
    else:
        check(case, "BEFORE 复现：login 用「敲的密码」→ 失败", not ok(good), good)
        check(case, "BEFORE 复现：login 用「去空格密码」→ 303 /my/home", ok(bad), bad)


print("BASE=%s DB=%s phase=%s stamp=%s" % (BASE, DB, PHASE, STAMP))

# ---- A 尾空格 / B 首空格 ----
space_case("A", "trail", "TestPass456 ")
space_case("B", "lead", " TestPass456")

# ---- C 普通无空格密码仍可注册并登录 ----
print("[C] 普通密码（无空格）")
email_c = f"pwv-normal-{STAMP}@pwv.local"
reg_c = register(email_c, "NormalPass789", mk_code("NORMAL"))
check("C", "register 303 /my/home", reg_c["status"] == 303, reg_c)
check("C", "login 原密码 303 /my/home", ok(login(email_c, "NormalPass789")), login(email_c, "NormalPass789"))

# ---- D 纯空格密码：明确报错，不静默存值 ----
print("[D] 纯空格密码 <%s>" % (" " * 8))
email_d = f"pwv-blank-{STAMP}@pwv.local"
reg_d = register(email_d, " " * 8, mk_code("BLANK"))
# 注册路径的错误落点一贯是 303 → /register?error=…（见 E/F/G），故这里判「被拒 + 有
# 人话 + 未建号」；after 额外要求话术点名「空格」（旧实现只回笼统的「所有字段都必须填写」）。
check("D", "纯空格密码被拒且未建号（error 落点）",
      "/register?error=" in reg_d["location"] and not reg_d["account_exists"]
      and bool(reg_d["banner"]), reg_d)
if PHASE == "after":
    check("D", "话术点名「空格」（不再静默改值）", "空格" in reg_d["banner"], reg_d)
check("D", "未建号", not reg_d["account_exists"], {"account_exists": reg_d["account_exists"]})

# ---- E/F/G 原有校验话术仍在 ----
print("[E] 两次不一致 / [F] 太短 / [G] 必填为空")
email_e = f"pwv-mismatch-{STAMP}@pwv.local"
reg_e = register(email_e, "TestPass456", mk_code("MISMATCH"), confirm="TestPass457")
check("E", "两次输入不一致话术", "不一致" in reg_e["banner"], reg_e)
email_f = f"pwv-short-{STAMP}@pwv.local"
reg_f = register(email_f, "Ab1", mk_code("SHORT"))
check("F", "密码至少 6 位话术", "至少 6 位" in reg_f["banner"], reg_f)
email_g = f"pwv-empty-{STAMP}@pwv.local"
reg_g = register(email_g, "TestPass456", mk_code("EMPTY"), name="")
check("G", "所有字段都必须填写话术", "所有字段都必须填写" in reg_g["banner"], reg_g)

# ---- H 小写邀请码仍按大写命中 ----
print("[H] 小写邀请码仍命中（大写归一化未被改坏）")
email_h = f"pwv-lower-{STAMP}@pwv.local"
code_h = mk_code("LOWER")
reg_h = register(email_h, "LowerCode123", code_h.lower())
check("H", "小写码注册成功 303", reg_h["status"] == 303 and reg_h["account_exists"], reg_h)

EVID["failed"] = FAILED
out = HERE / f"register_password_verbatim_{PHASE}.json"
out.write_text(json.dumps(EVID, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n%s\nEVIDENCE -> %s" % ("ALL PASS" if not FAILED else "FAILURES:\n" + "\n".join(FAILED), out))
sys.exit(1 if FAILED else 0)
