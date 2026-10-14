#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真浏览器端到端：学生「走导航」改密码 → 逐字登录（2026-09-24）。

为什么要浏览器：HTTP 断言证不了「学生实际点的是哪扇门」。本脚本用 Chromium 真登录，
点开右上角用户菜单里那一项（**不输入 URL**），确认落点是**我们自己的** /my/password，
再用带尾空格的新密码走完 → 退出 → 用「敲的密码」登录成功、「去空格密码」登录失败。
截图落 tests/smoke/out_password_nav/。

用法：python3 tests/smoke/change_password_nav_browser.py
清场：账号/伙伴由脚本删；它产生的邮件行（安全通知）打印 id，随后用 odoo shell 的
      sudo 清（mail.mail 的 unlink 规则不让 admin 经 RPC 删，实测）。
"""
import json
import os
import re
import sys
import time
import xmlrpc.client
from pathlib import Path

from playwright.sync_api import sync_playwright

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
BASE = os.environ.get("SMOKE_BASE", "http://localhost:8069")
DB = os.environ.get("EDU_DB_NAME", "edu19")
LOGIN_PWD = "InitPass123"
TYPED = "NavPass456 "          # 学生敲的（尾空格）
STRIPPED = TYPED.strip()       # 系统若 strip 会存成这个
STAMP = time.strftime("%m%d%H%M%S")
DOMAIN = "cpwd.local"
LOGIN = "cpw-nav-%s@%s" % (STAMP, DOMAIN)
OUT = Path(__file__).resolve().parent / "out_password_nav"
OUT.mkdir(exist_ok=True)

common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common")
UID = common.authenticate(DB, "admin", "admin", {})
assert UID, "admin 认证失败"
OBJ = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object")


def orm(model, method, *args, **kw):
    return OBJ.execute_kw(DB, UID, "admin", model, method, list(args), kw)


_old = orm("res.users", "search", [("login", "like", "cpw-nav-%@" + DOMAIN)])
if _old:
    orm("res.users", "unlink", _old)
_oldp = orm("res.partner", "search", [("email", "like", "%@" + DOMAIN)])
if _oldp:
    orm("res.partner", "unlink", _oldp)
portal = orm("ir.model.data", "check_object_reference", "base", "group_portal")[1]
orm("res.users", "create", [{"name": "导航验证学生", "login": LOGIN, "email": LOGIN,
                            "password": LOGIN_PWD, "group_ids": [(6, 0, [portal])]}])

RES = {"login": LOGIN, "typed": TYPED, "shots": []}
FAILED = []


def check(label, cond, payload=""):
    if not cond:
        FAILED.append(label)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", label, payload))


def shot(page, name, full=True):
    p = OUT / name
    page.screenshot(path=str(p), full_page=full)
    RES["shots"].append({"file": p.name, "url": page.url})
    print("    shot %s @ %s" % (p.name, page.url))


def do_login(page, login, password):
    """真登录页表单（form.oe_login_form；该表单初始带 d-none，由站点脚本揭开）。"""
    page.goto(BASE + "/login", wait_until="domcontentloaded")
    page.wait_for_selector("form.oe_login_form input[name='login']", timeout=20000)
    page.eval_on_selector("form.oe_login_form", "f => f.classList.remove('d-none')")
    page.fill("form.oe_login_form input[name='login']", login)
    page.fill("form.oe_login_form input[name='password']", password)
    page.click("form.oe_login_form button[type='submit']")
    page.wait_for_load_state("load")
    page.wait_for_timeout(700)
    return page.url


with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()

    print("[1] 真登录并打开用户菜单")
    url = do_login(page, LOGIN, LOGIN_PWD)
    check("登录后落到 /my/home", "/my/home" in url, url)
    page.wait_for_selector(".b11-usermenu button", timeout=15000)
    page.click(".b11-usermenu button")
    page.wait_for_selector(".b11-usermenu .dropdown-menu.show", timeout=10000)
    nav_label = page.inner_text('.b11-usermenu a.dropdown-item[href="/my/password"]')
    RES["nav_item"] = {"href": "/my/password", "label": nav_label.strip()}
    check("用户菜单里有指向 /my/password 的项", bool(nav_label.strip()), nav_label)
    check("用户菜单里已无 /my/security 项",
          page.locator('.b11-usermenu a.dropdown-item[href="/my/security"]').count() == 0)
    shot(page, "01_user_menu_open.png", full=False)

    print("[2] 点导航（不输 URL）→ 必须是我们的 /my/password")
    page.click('.b11-usermenu a.dropdown-item[href="/my/password"]')
    page.wait_for_load_state("domcontentloaded")
    RES["landed_url"] = page.url
    check("落点 = /my/password", page.url.rstrip("/").endswith("/my/password"), page.url)
    check("落点不是 /my/security", "/my/security" not in page.url)
    check("页面标题/说明是我们自己的",
          "修改密码" in page.inner_text("h4"), page.inner_text("h4"))
    shot(page, "02_our_password_page.png")

    print("[3] 新密码带尾空格，提交")
    page.fill("#old_password", LOGIN_PWD)
    page.fill("#new_password", TYPED)
    page.fill("#confirm_password", TYPED)
    page.click('form[action="/my/password/save"] button[type="submit"]')
    page.wait_for_load_state("domcontentloaded")
    RES["after_save_url"] = page.url
    # 实测（19.0 core）：改密会让**当前会话立刻失效**（session token 由口令哈希派生），
    # 所以 303 到 /my/password?ok=1 后浏览器被弹回 /login?redirect=…（页面上的成功条
    # 因此看不到了；这是既有行为，不是本次改动引入）。判据落在 redirect 目标上。
    went_login = "/login?redirect=" in page.url and "ok%3D1" in page.url.replace("%3F", "%3f").replace("?", "%3F") or "%2Fmy%2Fpassword%3Fok%3D1" in page.url
    check("保存后落到 /login?redirect=/my/password?ok=1（会话已失效，须重新登录）",
          went_login, page.url)
    shot(page, "03_saved_relogin.png")

    print("[4] 退出 → 用「敲的密码」（带空格）登录 → 必须成功")
    page.goto(BASE + "/logout", wait_until="domcontentloaded")
    url_typed = do_login(page, LOGIN, TYPED)
    RES["login_typed_url"] = url_typed
    check("带空格密码登录成功（落到 /my/home）", "/my/home" in url_typed, url_typed)
    shot(page, "04_login_typed_ok.png", full=False)

    print("[5] 退出 → 用「去空格密码」登录 → 必须失败")
    page.goto(BASE + "/logout", wait_until="domcontentloaded")
    url_stripped = do_login(page, LOGIN, STRIPPED)
    body = page.inner_text("body")
    RES["login_stripped_url"] = url_stripped
    RES["login_stripped_error"] = "错误的登录名/密码" in body
    check("去空格密码登录失败（仍在 /login 且有错误话术）",
          "/my/home" not in url_stripped and "错误的登录名/密码" in body, url_stripped)
    shot(page, "05_login_stripped_fail.png", full=False)

    print("[6] 移动端底部 Tab 也指向 /my/password")
    mctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True,
                               has_touch=True, device_scale_factor=2)
    mpage = mctx.new_page()
    do_login(mpage, LOGIN, STRIPPED if False else TYPED)
    mpage.wait_for_selector("#b11-tabbar", timeout=15000)
    tab = mpage.locator('#b11-tabbar a[data-b11-tab="/my/password"]')
    RES["mobile_tab"] = {"count": tab.count(),
                         "label": tab.first.inner_text().strip() if tab.count() else "",
                         "href": tab.first.get_attribute("href") if tab.count() else ""}
    check("移动端 Tab 指向 /my/password", tab.count() == 1, json.dumps(RES["mobile_tab"], ensure_ascii=False))
    # ⚠ 实测发现（本次上报，不属本任务范围）：在线聊天悬浮球正好压在**最后一个**
    # 移动端 Tab 上（截图 06_mobile_overlay_blocks_tab.png），真人点不到它。
    # 测试里先隐藏这个第三方浮层，才能验证 Tab 本身的落点。
    mpage.screenshot(path=str(OUT / "06_mobile_overlay_blocks_tab.png"), full_page=False)
    mpage.add_style_tag(content="[id^='o-livechat-root']{display:none !important}")
    mpage.wait_for_timeout(300)
    mpage.click('#b11-tabbar a[data-b11-tab="/my/password"]')
    mpage.wait_for_load_state("domcontentloaded")
    RES["mobile_tab_landed"] = mpage.url
    check("移动端 Tab 落点 = /my/password", mpage.url.rstrip("/").endswith("/my/password"), mpage.url)
    shot(mpage, "06_mobile_tab_landed.png")
    mctx.close()
    ctx.close()
    browser.close()

# ---- 清场 ----
uids = orm("res.users", "search", [("login", "like", "cpw-nav-%@" + DOMAIN)])
if uids:
    orm("res.users", "unlink", uids)
pids = orm("res.partner", "search", [("email", "like", "%@" + DOMAIN)])
if pids:
    orm("res.partner", "unlink", pids)
mails = orm("mail.mail", "search", [("email_to", "like", "%@" + DOMAIN)])
RES["cleanup"] = {"users": len(uids), "partners": len(pids), "mail_ids_for_shell": mails}
print("cleanup:", json.dumps(RES["cleanup"], ensure_ascii=False))

RES["failed"] = FAILED
(OUT / "nav_result.json").write_text(json.dumps(RES, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n%s" % ("ALL PASS" if not FAILED else "FAILURES: " + "; ".join(FAILED)))
sys.exit(1 if FAILED else 0)
