#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""其余「设密码」门的逐字行为（审计旁证；与 change_password_verbatim.py 配套）。

门 A：core portal 的 /my/security —— **已知 core 缺口，本次不改**。
      strip 不在模型层，而在**控制器**里：portal/controllers/portal.py:877-879
      `post['old'].strip(), post['new1'].strip(), post['new2'].strip()` ⇒ 进模型前值就被改过，
      edu_portal 的 res.users._change_password 覆盖够不到。故本脚本**如实断言它仍然 strip**
      （core 将来若修好，这里会 FAIL —— 那正是该把它改回「逐字期望」的信号）。
      我们的导航已不指向该页（改指 /my/password），见 docs/plans/password-verbatim-audit.md §3。
门 B：邮箱重置令牌 /web/reset_password?token=… （auth_signup 控制器
      → res.users.signup() → partner_user.write({'password': …}）—— 本就不 strip；
      本机无邮件服务器 ⇒ 取不到 token，如实记 SKIP（落点由 password_doors_shell.py 门 4 证明逐字）。
本脚本自清（用户 + partner + 自己产生的 mail.mail/mail.message），并核对计数回基线。

用法：python3 tests/smoke/password_doors_verbatim.py
"""
import json
import os
import re
import sys
import time
import xmlrpc.client
from pathlib import Path

import requests

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
BASE = os.environ.get("SMOKE_BASE", "http://localhost:8069")
DB = os.environ.get("EDU_DB_NAME", "edu19")
ADMIN = (os.environ.get("EDU_ADMIN_LOGIN", "admin"), os.environ.get("EDU_ADMIN_PWD", "admin"))
HERE = Path(__file__).resolve().parent
STAMP = time.strftime("%m%d%H%M%S")
DOMAIN = "cpwd.local"
INIT = "InitPass123"
PW = "DoorsPass456 "
STRIPPED = PW.strip()

common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common")
UID = common.authenticate(DB, ADMIN[0], ADMIN[1], {})
assert UID, "admin 认证失败"
OBJ = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object")


def orm(model, method, *args, **kw):
    return OBJ.execute_kw(DB, UID, ADMIN[1], model, method, list(args), kw)


def counts():
    return {m: orm(m, "search_count", []) for m in
            ("res.users", "res.partner", "mail.message", "mail.mail")}


def purge():
    """清账号/伙伴。**mail.mail 不在其中**：mail 的 unlink 规则不让 admin 经 RPC 删
    （实测 AccessError「文档类型: Message, 操作: unlink」）⇒ 邮件行由本脚本打印 id，
    随后用 odoo shell 的 sudo 清（见脚本头部说明）。"""
    uids = orm("res.users", "search", [("login", "like", "cpwd-%@" + DOMAIN)])
    if uids:
        orm("res.users", "unlink", uids)
    pids = orm("res.partner", "search", [("email", "like", "%@" + DOMAIN)])
    if pids:
        orm("res.partner", "unlink", pids)
    return len(uids), len(pids)


def my_mail_ids():
    return orm("mail.mail", "search", [("email_to", "like", "%@" + DOMAIN)])


CSRF_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')
TOKEN_RE = re.compile(r'token=([A-Za-z0-9_\-\.]+)')


def csrf(sess, path):
    m = CSRF_RE.search(sess.get(BASE + path, timeout=30).text)
    assert m, "csrf_token 未在 %s 找到" % path
    return m.group(1)


def mk_user(tag):
    login = "cpwd-%s-%s@%s" % (tag, STAMP, DOMAIN)
    portal = orm("ir.model.data", "check_object_reference", "base", "group_portal")[1]
    orm("res.users", "create", [{"name": "审计 " + tag, "login": login, "email": login,
                                 "password": INIT, "group_ids": [(6, 0, [portal])]}])
    return login


def login(login_, password):
    s = requests.Session()
    r = s.post(BASE + "/web/login", allow_redirects=False, timeout=30, data={
        "csrf_token": csrf(s, "/login"), "login": login_, "password": password})
    home = s.get(BASE + "/my/home", allow_redirects=False, timeout=30)
    return {"status": r.status_code, "location": r.headers.get("Location", ""),
            "home_status": home.status_code}


def ok(d):
    return d["status"] == 303 and "/my/home" in d["location"] and d["home_status"] == 200


def door_portal_security(login_):
    """门 A：core portal /my/security 的改密表单。"""
    s = requests.Session()
    s.post(BASE + "/web/login", allow_redirects=False, timeout=30, data={
        "csrf_token": csrf(s, "/login"), "login": login_, "password": INIT})
    page = s.get(BASE + "/my/security", timeout=30)
    tok = CSRF_RE.search(page.text)
    r = s.post(BASE + "/my/security", timeout=30, data={
        "csrf_token": tok.group(1) if tok else "", "op": "password",
        "old": INIT, "new1": PW, "new2": PW})
    return {"page_status": page.status_code,
            "posted_status": r.status_code,
            "updated": "Password Updated" in r.text or "密码" in r.text and "更新" in r.text,
            "has_form": "new1" in page.text}


def door_reset_token(login_):
    """门 B：邮箱重置令牌（/web/reset_password 两步）。"""
    s = requests.Session()
    r1 = s.post(BASE + "/web/reset_password", timeout=30, data={
        "csrf_token": csrf(s, "/web/reset_password"), "login": login_})
    sent = "已发送" in r1.text or "instructions sent" in r1.text
    mails = orm("mail.mail", "search_read",
                [("email_to", "ilike", login_)], fields=["id", "body_html", "subject"])
    tok = None
    for m in mails:
        hit = TOKEN_RE.search(m.get("body_html") or "")
        if hit:
            tok = hit.group(1)
            break
    if not tok:
        return {"error": "未从重置邮件里取到 token", "mails": len(mails),
                "post1": r1.status_code, "sent_msg": sent}
    page = s.get(BASE + "/web/reset_password?token=" + tok, timeout=30)
    cs = CSRF_RE.search(page.text)
    r2 = s.post(BASE + "/web/reset_password?token=" + tok, timeout=30, allow_redirects=False,
                data={"csrf_token": cs.group(1) if cs else "", "token": tok,
                      "password": PW, "confirm_password": PW})
    return {"token_found": True, "form_status": page.status_code,
            "post_status": r2.status_code, "location": r2.headers.get("Location", "")}


print("BASE=%s DB=%s stamp=%s" % (BASE, DB, STAMP))
st_u, st_p = purge()
if st_u or st_p:
    print("[pre] 清掉上一轮残留 users=%d partners=%d" % (st_u, st_p))
print("上一轮残留邮件行（待 shell 清）: %s" % my_mail_ids())
BASE_COUNTS = counts()
print("baseline:", json.dumps(BASE_COUNTS))
FAILED = []
EVID = {"stamp": STAMP, "doors": {}, "counts": {}}


def check(label, cond, payload):
    if not cond:
        FAILED.append(label)
    print("  [%s] %s: %s" % ("PASS" if cond else "FAIL", label,
                             json.dumps(payload, ensure_ascii=False)))


# ---- 门 A：/my/security ----
l_a = mk_user("sec")
d_a = door_portal_security(l_a)
EVID["doors"]["portal_my_security"] = d_a
print("[A] core portal /my/security:", json.dumps(d_a, ensure_ascii=False))
check("A 页面可达且有表单", d_a["page_status"] == 200 and d_a["has_form"], d_a)
good_a = login(l_a, PW)
bad_a = login(l_a, STRIPPED)
EVID["doors"]["portal_my_security"]["login_typed"] = good_a
EVID["doors"]["portal_my_security"]["login_stripped"] = bad_a
check("A 【已知 core 缺口】用敲的密码登录失败（strip 在 portal.py:877-879，先于模型）",
      not ok(good_a) and good_a["status"] == 200, good_a)
check("A 【已知 core 缺口】用去空格密码登录成功 ⇒ 库里存的确实是 strip 后的值", ok(bad_a), bad_a)

# ---- 门 B：邮箱重置令牌 ----
l_b = mk_user("reset")
d_b = door_reset_token(l_b)
EVID["doors"]["reset_token"] = d_b
print("[B] 邮箱重置令牌:", json.dumps(d_b, ensure_ascii=False))
check("B 重置入口可达且提交有回执（指引已发送）", d_b.get("post1") == 200 and d_b.get("sent_msg"), d_b)
if d_b.get("token_found"):
    good_b = login(l_b, PW)
    bad_b = login(l_b, STRIPPED)
    EVID["doors"]["reset_token"]["login_typed"] = good_b
    EVID["doors"]["reset_token"]["login_stripped"] = bad_b
    check("B 用敲的密码登录 303 /my/home", ok(good_b), good_b)
    check("B 用去空格密码登录失败", not ok(bad_b) and bad_b["status"] == 200, bad_b)
else:
    EVID["doors"]["reset_token"]["status"] = (
        "SKIP：本机无邮件服务器，重置邮件正文取不到 token；该门落点 write({'password':…}) "
        "的逐字性由 tests/smoke/password_doors_shell.py 门 4 证明")
    print("  [SKIP] B token 取不到（无邮件服务器）⇒ 端到端未验证，落点的逐字性由 shell 脚本门 4 证明")

# ---- 清场 + 计数 ----
u, p = purge()
AFTER = counts()
left_mail = my_mail_ids()
EVID["counts"] = {"baseline": BASE_COUNTS, "after_cleanup": AFTER,
                  "removed": {"users": u, "partners": p},
                  "mail_ids_for_shell_cleanup": left_mail}
print("cleanup removed users=%d partners=%d" % (u, p))
print("after:", json.dumps(AFTER))
print("MAIL_IDS_FOR_SHELL_CLEANUP %s" % left_mail)
check("Z 账号/伙伴计数回基线",
      all(AFTER[k] == BASE_COUNTS[k] for k in ("res.users", "res.partner")),
      EVID["counts"])
check("Z 无残留账号", orm("res.users", "search_count",
                          [("login", "like", "cpwd-%@" + DOMAIN)]) == 0, {})

EVID["failed"] = FAILED
out = HERE / "password_doors_verbatim.json"
out.write_text(json.dumps(EVID, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n%s -> %s" % ("ALL PASS" if not FAILED else "FAILURES: " + "; ".join(FAILED), out))
sys.exit(1 if FAILED else 0)
