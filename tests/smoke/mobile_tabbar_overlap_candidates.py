#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""候选方案实测：量悬浮球真实几何 + 逐个试 CSS 方案看谁能让 5 个 Tab 全可点。

只读探测，不改仓库文件。用法：python3 tests/smoke/mobile_tabbar_overlap_candidates.py
"""
import json, os, time, xmlrpc.client
from pathlib import Path
from playwright.sync_api import sync_playwright

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
BASE = os.environ.get("SMOKE_BASE", "http://localhost:8069")
DB = os.environ.get("EDU_DB_NAME", "edu19")
LOGIN_PWD = "InitPass123"
STAMP = time.strftime("%m%d%H%M%S")
DOMAIN = "cand.local"
LOGIN = "cand-%s@%s" % (STAMP, DOMAIN)
OUT = Path(__file__).resolve().parent / "out_tabbar_overlap"
OUT.mkdir(exist_ok=True)

common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common")
UID = common.authenticate(DB, "admin", "admin", {})
assert UID
OBJ = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object")
def orm(m, meth, *a, **k):
    return OBJ.execute_kw(DB, UID, "admin", m, meth, list(a), k)
for uid in orm("res.users", "search", [("login", "like", "cand-%@" + DOMAIN)]):
    orm("res.users", "unlink", [uid])
portal = orm("ir.model.data", "check_object_reference", "base", "group_portal")[1]
orm("res.users", "create", [{"name": "候选实测学生", "login": LOGIN, "email": LOGIN,
                            "password": LOGIN_PWD, "group_ids": [(6, 0, [portal])]}])

# 量：穿透 shadow DOM 拿悬浮球真实矩形 + 宿主信息 + 5 个 Tab 的可点性
MEASURE = """
() => {
  const host = document.querySelector('.o-livechat-root');
  const sr = host && host.shadowRoot;
  const btn = sr && sr.querySelector('.o-livechat-LivechatButton');
  const bubbles = sr && sr.querySelector('.o-mail-ChatHub-bubbles');
  const r = (e) => { if(!e) return null; const b=e.getBoundingClientRect();
    return {x:Math.round(b.x),y:Math.round(b.y),w:Math.round(b.width),h:Math.round(b.height),
            right:Math.round(b.right),bottom:Math.round(b.bottom)}; };
  const cs = (e) => { if(!e) return null; const s=getComputedStyle(e);
    return {zIndex:s.zIndex,position:s.position,bottom:s.bottom,right:s.right,
            marginBottom:s.marginBottom,pointerEvents:s.pointerEvents,display:s.display}; };
  const tabs = [...document.querySelectorAll('#b11-tabbar .b11-tab')].map(t=>{
    const b=t.getBoundingClientRect();
    const cx=Math.round(b.x+b.width/2), cy=Math.round(b.y+b.height/2);
    const hit=document.elementFromPoint(cx,cy);
    return {tab:t.getAttribute('data-b11-tab'),
            clickable: !!(hit && t.contains(hit)),
            hit: hit ? (hit.tagName.toLowerCase()+(hit.id?'#'+hit.id:'')
                       +(typeof hit.className==='string'&&hit.className?'.'+hit.className.trim().split(/\\s+/)[0]:'')) : null};
  });
  return {hasShadow: !!sr, hasBtn: !!btn,
          hostRect: r(host), hostCS: cs(host),
          btnRect: r(btn), btnCS: cs(btn),
          bubblesRect: r(bubbles), bubblesCS: cs(bubbles),
          tabbarRect: r(document.getElementById('b11-tabbar')),
          liftVar: getComputedStyle(document.documentElement).getPropertyValue('--h-tabbar'),
          tabs: tabs};
}
"""

CANDS = [
    ("baseline", ""),
    ("A-zindex-lower", ".o-livechat-root{z-index:1030 !important}"),
    ("B-part-margin", ".o-livechat-root::part(openChatButton){margin-bottom:64px !important}"),
    ("C-part-bottom-fixed", ".o-livechat-root::part(openChatButton){position:fixed !important;bottom:76px !important;right:16px !important}"),
    ("D-liftvar", ".o-livechat-root{--mail-ChatHub-bubbles-bottomLift:64px !important}"),
]

RES = {"candidates": {}}
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True,
                        has_touch=True, device_scale_factor=2)
    p = ctx.new_page()
    p.goto(BASE + "/login", wait_until="domcontentloaded")
    p.wait_for_selector("form.oe_login_form input[name='login']", timeout=20000)
    p.eval_on_selector("form.oe_login_form", "f => f.classList.remove('d-none')")
    p.fill("form.oe_login_form input[name='login']", LOGIN)
    p.fill("form.oe_login_form input[name='password']", LOGIN_PWD)
    p.click("form.oe_login_form button[type='submit']")
    p.wait_for_load_state("load")
    p.wait_for_selector("#b11-tabbar", timeout=20000)
    p.wait_for_timeout(2500)
    for name, css in CANDS:
        p.evaluate("(css)=>{document.querySelectorAll('style[data-probe]').forEach(e=>e.remove());"
                   "if(css){const s=document.createElement('style');s.setAttribute('data-probe','1');"
                   "s.textContent=css;document.head.appendChild(s);}}", css)
        p.wait_for_timeout(250)
        m = p.evaluate(MEASURE)
        RES["candidates"][name] = {"css": css, "m": m}
        p.screenshot(path=str(OUT / ("cand_%s.png" % name)), full_page=False)
        print("=== %s :: %s" % (name, css or "(none)"))
        print("   host z=%s pos=%s rect=%s" % (m["hostCS"]["zIndex"], m["hostCS"]["position"], m["hostRect"]))
        print("   btn  rect=%s cs=%s" % (m["btnRect"], m["btnCS"]))
        print("   bubbles rect=%s cs=%s" % (m["bubblesRect"], m["bubblesCS"]))
        print("   liftVar=%r tabs=%s" % (m["liftVar"], m["tabs"]))
    ctx.close(); b.close()

for uid in orm("res.users", "search", [("login", "like", "cand-%@" + DOMAIN)]):
    orm("res.users", "unlink", [uid])
(OUT / "candidates.json").write_text(json.dumps(RES, ensure_ascii=False, indent=2), encoding="utf-8")
print("\nALL TABS CLICKABLE per candidate:",
      {k: all(t["clickable"] for t in v["m"]["tabs"]) for k, v in RES["candidates"].items()})
