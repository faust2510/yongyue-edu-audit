#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复现：手机宽度下在线聊天悬浮球压住底部 Tab 栏（B11）。

判据不靠肉眼：用 document.elementFromPoint() 取每个 Tab 中心的**实际命中元素**，
再打印它的选择器 / computed z-index / 位置，与 Tab 栏自身对比。
用法：python3 tests/smoke/mobile_tabbar_overlap_probe.py
"""
import json, os, time, xmlrpc.client
from pathlib import Path
from playwright.sync_api import sync_playwright

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
BASE = os.environ.get("SMOKE_BASE", "http://localhost:8069")
DB = os.environ.get("EDU_DB_NAME", "edu19")
LOGIN_PWD = "InitPass123"
STAMP = time.strftime("%m%d%H%M%S")
DOMAIN = "overlap.local"
LOGIN = "ovl-%s@%s" % (STAMP, DOMAIN)
OUT = Path(__file__).resolve().parent / "out_tabbar_overlap"
OUT.mkdir(exist_ok=True)

common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common")
UID = common.authenticate(DB, "admin", "admin", {})
assert UID, "admin 认证失败"
OBJ = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object")
def orm(model, method, *args, **kw):
    return OBJ.execute_kw(DB, UID, "admin", model, method, list(args), kw)

for uid in orm("res.users", "search", [("login", "like", "ovl-%@" + DOMAIN)]):
    orm("res.users", "unlink", [uid])
portal = orm("ir.model.data", "check_object_reference", "base", "group_portal")[1]
orm("res.users", "create", [{"name": "重叠复现学生", "login": LOGIN, "email": LOGIN,
                            "password": LOGIN_PWD, "group_ids": [(6, 0, [portal])]}])

RES = {"login": LOGIN, "shots": []}

PROBE = """
() => {
  const tabbar = document.getElementById('b11-tabbar');
  const tabs = [...document.querySelectorAll('#b11-tabbar .b11-tab')];
  const info = (el) => {
    if (!el) return null;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const chain = [];
    let n = el;
    while (n && n.nodeType === 1) {
      chain.push(n.tagName.toLowerCase() + (n.id ? '#' + n.id : '')
                 + (n.className && typeof n.className === 'string'
                    ? '.' + n.className.trim().split(/\\s+/).slice(0,4).join('.') : ''));
      n = n.parentElement;
    }
    return {sel: chain[0], chain: chain.slice(0, 8),
            zIndex: cs.zIndex, position: cs.position, display: cs.display,
            visibility: cs.visibility, pointerEvents: cs.pointerEvents,
            rect: {x: Math.round(r.x), y: Math.round(r.y),
                   w: Math.round(r.width), h: Math.round(r.height),
                   bottom: Math.round(r.bottom)}};
  };
  const rows = tabs.map(t => {
    const r = t.getBoundingClientRect();
    const cx = Math.round(r.x + r.width / 2), cy = Math.round(r.y + r.height / 2);
    const hit = document.elementFromPoint(cx, cy);
    const inside = !!(hit && t.contains(hit));
    return {tab: t.getAttribute('data-b11-tab'), label: t.innerText.trim(),
            center: {x: cx, y: cy}, tabInfo: info(t),
            hitSel: hit ? (hit.tagName.toLowerCase()
              + (hit.id ? '#' + hit.id : '')
              + (hit.className && typeof hit.className === 'string'
                 ? '.' + hit.className.trim().split(/\\s+/).slice(0,4).join('.') : '')) : null,
            hitInfo: info(hit), clickable: inside};
  });
  return {tabbar: info(tabbar),
          viewport: {w: innerWidth, h: innerHeight},
          livechatRoots: [...document.querySelectorAll('[id^="o-livechat-root"], .o-livechat-Button, [class*="livechat"]')]
            .map(e => ({sel: e.tagName.toLowerCase() + '#' + (e.id||'') + '.' + (typeof e.className==='string'?e.className.trim().split(/\\s+/).slice(0,3).join('.'):''),
                        info: info(e)})),
          rows: rows};
}
"""

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
    p.wait_for_timeout(2500)   # 等 livechat widget 挂载
    res = p.evaluate(PROBE)
    RES["probe"] = res
    p.screenshot(path=str(OUT / "probe_before.png"), full_page=False)
    RES["shots"].append("probe_before.png")
    ctx.close(); b.close()

for uid in orm("res.users", "search", [("login", "like", "ovl-%@" + DOMAIN)]):
    orm("res.users", "unlink", [uid])

(OUT / "probe.json").write_text(json.dumps(RES, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=2))
