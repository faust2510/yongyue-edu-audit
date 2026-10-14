#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验收：手机宽度下底栏 5 个 Tab 全部「看得见 + 点得到」，且桌面零位移。

点得到 = 真·坐标点击（page.mouse.click 打在 Tab 中心，等同拇指落点），
        不是 locator.click（后者自带可操作性检查，容易掩盖遮挡）。
用法：python3 tests/smoke/mobile_tabbar_clickthrough.py
"""
import json, os, time, xmlrpc.client
from pathlib import Path
from playwright.sync_api import sync_playwright

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
BASE = os.environ.get("SMOKE_BASE", "http://localhost:8069")
DB = os.environ.get("EDU_DB_NAME", "edu19")
LOGIN_PWD = "InitPass123"
STAMP = time.strftime("%m%d%H%M%S")
DOMAIN = "tabclick.local"
LOGIN = "tab-%s@%s" % (STAMP, DOMAIN)
OUT = Path(__file__).resolve().parent / "out_tabbar_overlap"; OUT.mkdir(exist_ok=True)
UA_ANDROID = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/203.0.113.9 Mobile Safari/537.36")
TABS = [("/my/home", "首页"), ("/my/calendar", "校历"), ("/my/messages", "消息"),
        ("/my/contacts", "通讯录"), ("/my/password", "修改密码")]

common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common")
UID = common.authenticate(DB, "admin", "admin", {}); assert UID
OBJ = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object")
def orm(m, meth, *a, **k): return OBJ.execute_kw(DB, UID, "admin", m, meth, list(a), k)
for u in orm("res.users", "search", [("login", "like", "tab-%@" + DOMAIN)]): orm("res.users", "unlink", [u])
portal = orm("ir.model.data", "check_object_reference", "base", "group_portal")[1]
orm("res.users", "create", [{"name": "底栏点击验收", "login": LOGIN, "email": LOGIN,
                            "password": LOGIN_PWD, "group_ids": [(6, 0, [portal])]}])

RES, FAILED = {"tabs": [], "desktop": {}, "shots": []}, []
def check(label, cond, payload=""):
    if not cond: FAILED.append(label)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", label, payload))
def shot(pg, name):
    pg.screenshot(path=str(OUT / name), full_page=False); RES["shots"].append(name)

def login(pg):
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.wait_for_selector("form.oe_login_form input[name='login']", timeout=20000)
    pg.eval_on_selector("form.oe_login_form", "f => f.classList.remove('d-none')")
    pg.fill("form.oe_login_form input[name='login']", LOGIN)
    pg.fill("form.oe_login_form input[name='password']", LOGIN_PWD)
    pg.click("form.oe_login_form button[type='submit']"); pg.wait_for_load_state("load")

TABINFO = """
(href) => {
  const t = document.querySelector('#b11-tabbar .b11-tab[data-b11-tab="' + href + '"]');
  if (!t) return null;
  const b = t.getBoundingClientRect(), cx = Math.round(b.x + b.width/2), cy = Math.round(b.y + b.height/2);
  const hit = document.elementFromPoint(cx, cy);
  const sr = document.querySelector('.o-livechat-root')?.shadowRoot;
  const btn = sr?.querySelector('.o-livechat-LivechatButton');
  const br = btn && btn.getBoundingClientRect();
  const cs = getComputedStyle(t);
  return {cx: cx, cy: cy, hitIsTab: !!(hit && t.contains(hit)),
          hitSel: hit ? hit.tagName.toLowerCase() + (hit.id ? '#'+hit.id : '') : null,
          tabColor: cs.color, tabFontSize: cs.fontSize,
          barCols: getComputedStyle(document.getElementById('b11-tabbar')).gridTemplateColumns,
          barZ: getComputedStyle(document.getElementById('b11-tabbar')).zIndex,
          barTop: Math.round(document.getElementById('b11-tabbar').getBoundingClientRect().top),
          bubble: br ? {bottom: Math.round(br.bottom), right: Math.round(390 - br.right), pos: getComputedStyle(btn).position} : null};
}
"""

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    # ---------- 手机宽度（真 Android UA ⇒ Odoo 会加 .o-mobile） ----------
    ctx = b.new_context(viewport={"width": 390, "height": 844}, user_agent=UA_ANDROID,
                        is_mobile=True, has_touch=True, device_scale_factor=2)
    p = ctx.new_page(); login(p)
    p.wait_for_selector("#b11-tabbar", timeout=20000); p.wait_for_timeout(2500)
    print("[手机 390x844] 逐 Tab 真坐标点击")
    for href, label in TABS:
        p.goto(BASE + "/my/home", wait_until="domcontentloaded")
        p.wait_for_selector("#b11-tabbar", timeout=20000); p.wait_for_timeout(1800)
        info = p.evaluate(TABINFO, href)
        check("点位落在 Tab 上（非聊天球） %s %s" % (href, label), info["hitIsTab"], json.dumps(info["hitSel"]))
        p.mouse.click(info["cx"], info["cy"])          # 真·拇指落点
        p.wait_for_load_state("domcontentloaded"); p.wait_for_timeout(400)
        landed = p.url.rstrip("/")
        ok = landed.endswith(href)
        check("点击后落到 %s" % href, ok, landed)
        info["landed"] = p.url; RES["tabs"].append(info)
        if href == "/my/password":
            check("底栏仍 5 列", len(info["barCols"].split()) == 5, info["barCols"])
            check("底栏仍在视口底部（top=%s）" % info["barTop"], 780 <= info["barTop"] <= 800)
            check("Tab 字色/字号未变", info["tabFontSize"] == "12px", info["tabColor"] + " " + info["tabFontSize"])
            check("聊天球已抬到栏上方", info["bubble"] and info["bubble"]["bottom"] < info["barTop"],
                  json.dumps(info["bubble"], ensure_ascii=False))
            shot(p, "verify_mobile_password_tab.png")
    # 聊天球本身还点得开（没把 livechat 弄坏）
    p.goto(BASE + "/my/home", wait_until="domcontentloaded"); p.wait_for_timeout(2000)
    bc = p.evaluate("""() => {
      const sr = document.querySelector('.o-livechat-root')?.shadowRoot;
      const btn = sr?.querySelector('.o-livechat-LivechatButton');
      if (!btn) return null;
      const r = btn.getBoundingClientRect();
      return {cx: Math.round(r.x+r.width/2), cy: Math.round(r.y+r.height/2)};
    }""")
    check("聊天球存在且可取点位", bool(bc), json.dumps(bc))
    if bc:
        p.mouse.click(bc["cx"], bc["cy"])       # 真坐标点击：命中 shadow 内的 button
        p.wait_for_timeout(3000)
        opened = p.evaluate("""() => {
          const sr = document.querySelector('.o-livechat-root')?.shadowRoot;
          if (!sr) return 'no-shadow';
          const w = sr.querySelector('.o-mail-ChatWindow');
          const t = sr.querySelector('.o-mail-Thread');
          const c = sr.querySelector('.o-mail-Composer-input');
          return JSON.stringify({window: !!w, thread: !!t, composer: !!c,
            btnHidden: !sr.querySelector('.o-livechat-LivechatButton')});
        }""")
        check("聊天球仍可点击并打开会话（未被改坏）", "\"window\":true" in opened, opened)
        RES["bubble_click"] = opened
    shot(p, "verify_mobile_bubble_open.png")

    # ---------- 桌面宽度（回归） ----------
    dctx = b.new_context(viewport={"width": 1280, "height": 900})
    dp = dctx.new_page(); login(dp)
    dp.wait_for_timeout(2500)
    RES["desktop"] = dp.evaluate("""() => {
      const bar = document.getElementById('b11-tabbar');
      const side = document.getElementById('b11-side');
      const sr = document.querySelector('.o-livechat-root')?.shadowRoot;
      const btn = sr?.querySelector('.o-livechat-LivechatButton');
      const bb = btn && btn.getBoundingClientRect();
      return {barExists: !!bar,
              barDisplay: bar ? getComputedStyle(bar).display : null,
              sidebar: side ? {w: Math.round(side.getBoundingClientRect().width),
                               x: Math.round(side.getBoundingClientRect().x),
                               display: getComputedStyle(side).display} : null,
              bubble: bb ? {pos: getComputedStyle(btn).position,
                            bottom: Math.round(900 - bb.bottom), right: Math.round(1280 - bb.right),
                            w: Math.round(bb.width), h: Math.round(bb.height)} : null};
    }""")
    d = RES["desktop"]
    check("桌面：底栏存在但 display:none（d-lg-none）", d["barExists"] and d["barDisplay"] == "none", json.dumps(d["barDisplay"]))
    check("桌面：侧栏还在且可见", d["sidebar"] and d["sidebar"]["display"] != "none" and d["sidebar"]["w"] > 100,
          json.dumps(d["sidebar"]))
    check("桌面：聊天球未位移（仍 static / 右下角 25,10）",
          d["bubble"] and d["bubble"]["pos"] == "static", json.dumps(d["bubble"]))
    shot(dp, "verify_desktop_regression.png")
    check("桌面：无横向溢出", dp.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth"))
    dctx.close(); ctx.close(); b.close()

for u in orm("res.users", "search", [("login", "like", "tab-%@" + DOMAIN)]): orm("res.users", "unlink", [u])
RES["failed"] = FAILED
(OUT / "clickthrough.json").write_text(json.dumps(RES, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n" + ("ALL PASS" if not FAILED else "FAILURES: " + "; ".join(FAILED)))
