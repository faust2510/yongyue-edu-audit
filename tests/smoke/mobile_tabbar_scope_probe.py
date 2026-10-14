#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""作用域探测 + Android UA 下验证候选方案（.o-mobile 会覆盖 lift 变量）。"""
import json, os, time, xmlrpc.client
from pathlib import Path
from playwright.sync_api import sync_playwright

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
BASE = os.environ.get("SMOKE_BASE", "http://localhost:8069")
DB = os.environ.get("EDU_DB_NAME", "edu19")
LOGIN_PWD = "InitPass123"
STAMP = time.strftime("%m%d%H%M%S")
DOMAIN = "scope.local"
LOGIN = "scope-%s@%s" % (STAMP, DOMAIN)
OUT = Path(__file__).resolve().parent / "out_tabbar_overlap"; OUT.mkdir(exist_ok=True)
ANDROID_UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/203.0.113.9 Mobile Safari/537.36")

common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common")
UID = common.authenticate(DB, "admin", "admin", {}); assert UID
OBJ = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object")
def orm(m, meth, *a, **k): return OBJ.execute_kw(DB, UID, "admin", m, meth, list(a), k)
for u in orm("res.users", "search", [("login", "like", "scope-%@" + DOMAIN)]): orm("res.users", "unlink", [u])
portal = orm("ir.model.data", "check_object_reference", "base", "group_portal")[1]
orm("res.users", "create", [{"name": "作用域学生", "login": LOGIN, "email": LOGIN,
                            "password": LOGIN_PWD, "group_ids": [(6, 0, [portal])]}])

FINAL_CSS = """
@media (max-width: 991.98px){
  .o-livechat-root::part(openChatButton){
    position: fixed !important;
    right: 16px !important;
    bottom: calc(var(--h-tabbar, 56px) + env(safe-area-inset-bottom, 0px) + 10px) !important;
  }
}
"""

ENV = """
() => {
  const host=document.querySelector('.o-livechat-root'), sr=host&&host.shadowRoot;
  const bub=sr&&sr.querySelector('.o-mail-ChatHub-bubbles');
  const btn=sr&&sr.querySelector('.o-livechat-LivechatButton');
  const r=e=>{if(!e)return null;const b=e.getBoundingClientRect();return {x:Math.round(b.x),y:Math.round(b.y),w:Math.round(b.width),h:Math.round(b.height),bottom:Math.round(b.bottom)};};
  return {url:location.pathname, bodyClass:document.body.className,
          hasTabbar:!!document.getElementById('b11-tabbar'),
          ua:navigator.userAgent.slice(0,60),
          bubblesClass: bub?bub.className:null, bubblesRect:r(bub),
          btnRect:r(btn),
          tabbarTop: document.getElementById('b11-tabbar')?Math.round(document.getElementById('b11-tabbar').getBoundingClientRect().top):null,
          tabs: [...document.querySelectorAll('#b11-tabbar .b11-tab')].map(t=>{
            const b=t.getBoundingClientRect();const cx=Math.round(b.x+b.width/2),cy=Math.round(b.y+b.height/2);
            const hit=document.elementFromPoint(cx,cy);
            return {tab:t.getAttribute('data-b11-tab'),clickable:!!(hit&&t.contains(hit))};})};
}
"""

RES={}
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    ctx=b.new_context(viewport={"width":390,"height":844},user_agent=ANDROID_UA,
                      is_mobile=True,has_touch=True,device_scale_factor=2)
    p=ctx.new_page()
    p.goto(BASE+"/login", wait_until="domcontentloaded")
    p.wait_for_selector("form.oe_login_form input[name='login']",timeout=20000)
    p.eval_on_selector("form.oe_login_form","f=>f.classList.remove('d-none')")
    p.fill("form.oe_login_form input[name='login']",LOGIN)
    p.fill("form.oe_login_form input[name='password']",LOGIN_PWD)
    p.click("form.oe_login_form button[type='submit']"); p.wait_for_load_state("load")
    p.wait_for_selector("#b11-tabbar",timeout=20000); p.wait_for_timeout(2500)
    RES["portal_baseline"]=p.evaluate(ENV)
    p.screenshot(path=str(OUT/"android_before.png"),full_page=False)
    # 公开页（同一 UA）
    p.goto(BASE+"/campus/jobs", wait_until="domcontentloaded"); p.wait_for_timeout(2500)
    RES["public_baseline"]=p.evaluate(ENV)
    # 回门户，加最终 CSS
    p.goto(BASE+"/my/home", wait_until="domcontentloaded")
    p.wait_for_selector("#b11-tabbar",timeout=20000); p.wait_for_timeout(2000)
    p.add_style_tag(content=FINAL_CSS); p.wait_for_timeout(400)
    RES["portal_after_android_ua"]=p.evaluate(ENV)
    p.screenshot(path=str(OUT/"android_after.png"),full_page=False)
    ctx.close(); b.close()

for u in orm("res.users","search",[("login","like","scope-%@"+DOMAIN)]): orm("res.users","unlink",[u])
(OUT/"scope.json").write_text(json.dumps(RES,ensure_ascii=False,indent=2),encoding="utf-8")
for k,v in RES.items():
    print("==",k); print("  body:",v["bodyClass"][:120]); print("  tabbar:",v["hasTabbar"],"tabbarTop:",v["tabbarTop"],"ua:",v["ua"])
    print("  bubblesClass:",v["bubblesClass"]); print("  bubblesRect:",v["bubblesRect"],"btnRect:",v["btnRect"])
    print("  tabs:",v["tabs"])
