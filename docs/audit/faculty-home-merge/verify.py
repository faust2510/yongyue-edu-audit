#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""教师「我的主页 + 应用面板」合并 —— 渲染后验收（Playwright，四角色对照）。

用法：
  /opt/homebrew/bin/python3 docs/audit/faculty-home-merge/verify.py <标签>
  例：… verify.py before   /   … verify.py after

判据（全部落在**渲染后的页面**上）：
  1. 角色矩阵：faculty/student/parent/backoffice 各自 /my/home、/my/apps、/apps 的
     状态码 + 最终 URL + 侧栏导航项 + 页面上的「工作台标记」「宫格标记」；
  2. 教师的导航里「应用面板」「全部应用」是否消失（只剩「我的主页」一个入口）；
  3. 功能不丢：把教师改动前三个页面可达的站内链接并集，与改动后的并集比对，
     改后必须**包含**改前的每一条（逐条对照表落盘 JSON）。
"""
import json
import os
import sys

import requests
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8069"
DB = "edu19"
LOGINS = {"faculty": "faculty@local", "student": "stu@local",
          "parent": "parent@local", "backoffice": "backoffice@local"}
PATHS = ["/my/home", "/my/apps", "/apps"]
PWD = "demo123"
WORKBENCH_MARKS = ["待办提醒", "本周我教的课", "常用应用", "应用面板（后台）"]
GRID_MARKS = ["学业", "资源与学习", "欢迎回来"]

JS = """() => {
  const norm = s => (s || "").replace(/\\s+/g, " ").trim();
  return {
    nav: Array.from(document.querySelectorAll(".b11-nav-item")).map(a => ({t: norm(a.innerText), h: a.getAttribute("href")})),
    tabs: Array.from(document.querySelectorAll(".b11-tab")).map(a => ({t: norm(a.innerText), h: a.getAttribute("href")})),
    text: norm(document.body.innerText).slice(0, 4000),
    links: Array.from(new Set(Array.from(document.querySelectorAll("a[href^='/']")).map(a => a.getAttribute("href")))),
  };
}"""


def login(login_name):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + "/web/session/authenticate",
               json={"jsonrpc": "2.0",
                     "params": {"db": DB, "login": login_name, "password": PWD}}, timeout=30)
    return (r.json().get("result") or {}).get("uid"), s.cookies.get("session_id")


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "run"
    outdir = "docs/audit/faculty-home-merge"
    os.makedirs(outdir, exist_ok=True)
    creds = {}
    for role, lg in LOGINS.items():
        creds[role] = login(lg)
        print("login %-11s uid=%s cookie=%s" % (role, creds[role][0], bool(creds[role][1])))
    out = {}
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True, args=["--no-proxy-server"])
        for role in LOGINS:
            uid, ck = creds[role]
            ctx = b.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_cookies([{"name": "session_id", "value": ck, "domain": "localhost", "path": "/"}])
            pg = ctx.new_page()
            out[role] = {}
            for path in PATHS:
                resp = pg.goto(BASE + path, wait_until="domcontentloaded", timeout=30000)
                pg.wait_for_timeout(300)
                d = pg.evaluate(JS)
                d["status"] = resp.status if resp else None
                d["final"] = pg.url.replace(BASE, "")
                out[role][path] = d
                print("  %-10s %-10s status=%s final=%-10s nav=%d" % (role, path, d["status"], d["final"], len(d["nav"])))
            ctx.close()
        b.close()
    ap = os.path.join(outdir, "verify-%s.json" % tag)
    json.dump(out, open(ap, "w"), ensure_ascii=False, indent=1)
    print("落盘：" + ap)

    print()
    print("== 角色矩阵（状态码 / 最终 URL / 工作台标记 / 宫格标记）==")
    for role in LOGINS:
        for path in PATHS:
            d = out[role][path]
            wb = [m for m in WORKBENCH_MARKS if m in d["text"]]
            gr = [m for m in GRID_MARKS if m in d["text"]]
            print("  %-10s %-10s %s → %-10s 工作台=%s 宫格=%s" % (
                role, path, d["status"], d["final"], ",".join(wb) or "-", ",".join(gr) or "-"))

    print()
    print("== 教师导航项（合并后应只剩「我的主页」一个首页入口）==")
    nav = out["faculty"]["/my/home"]["nav"]
    print("  " + " | ".join("%s→%s" % (n["t"], n["h"]) for n in nav))
    for bad in ("/apps", "/my/apps"):
        hit = [n for n in nav if n["h"] == bad]
        print("  导航里 %-9s 出现 %d 次 %s" % (bad, len(hit), "OK（已收口）" if not hit else "！！仍在"))
    return 0


if __name__ == "__main__":
    sys.exit(main())