#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task-19 合并页验收探针：入口收口 / 拒止卡 / 同屏重复（判据全部落在渲染后的页面）。

用法：/opt/homebrew/bin/python3 docs/audit/faculty-home-merge/check_merged.py [标签]
"""
import collections
import json
import re
import sys

import requests
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8069"
DB = "edu19"
LOGINS = {"faculty": "faculty@local", "student": "stu@local",
          "parent": "parent@local", "backoffice": "backoffice@local"}
STUDENT_ONLY = ["/student/attendance", "/student/assignment/details",
                "/student/exam", "/grade-book"]

JS = """() => {
  const norm = s => (s || "").replace(/\\s+/g, " ").trim();
  return {
    nav: Array.from(document.querySelectorAll(".b11-nav-item")).map(a => a.getAttribute("href")),
    breadcrumb: Array.from(document.querySelectorAll(".o_portal_submenu.breadcrumb a")).map(a => a.getAttribute("href")),
    qa: Array.from(document.querySelectorAll(".oe-qa-side a[href]")).map(a => ({h: a.getAttribute("href"), t: norm(a.innerText)})),
    cards: Array.from(document.querySelectorAll(".o_portal_index_card a[href], a.oe-quick-btn[href], .card a[href], a.card[href]")).map(a => a.getAttribute("href")),
    text: norm(document.body.innerText),
  };
}"""


def login(lg):
    s = requests.Session()
    s.trust_env = False
    s.post(BASE + "/web/session/authenticate",
           json={"jsonrpc": "2.0", "params": {"db": DB, "login": lg, "password": "demo123"}}, timeout=30)
    return s


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "run"
    out = {}
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True, args=["--no-proxy-server"])
        for role, lg in LOGINS.items():
            s = login(lg)
            ck = s.cookies.get("session_id")
            ctx = b.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_cookies([{"name": "session_id", "value": ck, "domain": "localhost", "path": "/"}])
            pg = ctx.new_page()
            routes = {}
            for path in ("/my/home", "/my/apps", "/apps"):
                r = pg.goto(BASE + path, wait_until="domcontentloaded", timeout=30000)
                routes[path] = {"status": r.status if r else None,
                                "final": pg.url.replace(BASE, "")}
            pg.goto(BASE + "/my/home", wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(300)
            d = pg.evaluate(JS)
            d["routes"] = routes
            # 侧栏 7 项逐个请求：拒止页判定 = 文案含「仅面向」
            denials = {}
            for item in d["qa"]:
                h = s.get(BASE + item["h"], timeout=30)
                denials[item["h"]] = "仅面向" in h.text
            d["qa_denied"] = denials
            out[role] = d
            ctx.close()
        b.close()
    json.dump(out, open("docs/audit/faculty-home-merge/merged-%s.json" % tag, "w"),
              ensure_ascii=False, indent=1)
    for role in LOGINS:
        d = out[role]
        print("======== %s ========" % role)
        print("  路由:", "  ".join("%s=%s→%s" % (k, v["status"], v["final"]) for k, v in d["routes"].items()))
        print("  侧栏「快速操作」%d 项，其中拒止 %d 项: %s" % (
            len(d["qa"]), sum(1 for v in d["qa_denied"].values() if v),
            [i["t"] for i in d["qa"] if d["qa_denied"][i["h"]]]))
        print("  面包屑:", d["breadcrumb"])
        print("  导航里 /apps=%d  /my/apps=%d" % (d["nav"].count("/apps"), d["nav"].count("/my/apps")))
        cnt = collections.Counter(d["cards"])
        dup = {k: v for k, v in cnt.items() if v > 1}
        print("  同屏重复卡片链接:", dup or "（无）")
        print("  页面「常用应用」出现 %d 次" % d["text"].count("常用应用"))
        print("  学生专属路由出现在侧栏:", [x for x in STUDENT_ONLY if any(i["h"] == x for i in d["qa"])])
    return 0


if __name__ == "__main__":
    sys.exit(main())