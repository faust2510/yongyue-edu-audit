#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task-12 窄屏卡片化取证：375 视口截图 + 「挤扁表」读数（改前/改后各跑一次）。

用法：
  /opt/homebrew/bin/python3 docs/audit/narrow-tables-c/shots.py <输出目录>

口径：
  · 视口 375x812（与 scripts/find_squeezed_tables.py 同口径）；BASE 用 localhost
    （会话 cookie 的 domain 是 localhost，用 127.0.0.1 打开会拿不到登录态 —— 实测踩过）；
  · 每页按**该页真正的角色**登录：/ledger 与 /timetable/bulk 与 /registrar/curriculum 用 backoffice，
    /my/fees 用 parent；
  · 同时记录每张表的 列数 / 表宽 / 容器宽 / thead 的 computed display（桌面判据另跑 1440）。
"""
import json
import os
import sys

import requests
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8069"
DB = "edu19"
ROLES = {"backoffice": ("backoffice@local", "demo123"),
         "parent": ("parent@local", "demo123"),
         "faculty": ("faculty@local", "demo123"),
         "student": ("stu@local", "demo123")}
TARGETS = [("/ledger", "backoffice", "ledger"),
           ("/registrar/curriculum", "backoffice", "curriculum"),
           ("/my/fees", "parent", "fees_parent"),
           ("/timetable/bulk", "backoffice", "timetable_bulk")]

MEASURE_JS = """() => {
  const out = [];
  for (const t of document.querySelectorAll("table")) {
    const th = t.querySelector("thead");
    const wrap = t.parentElement;
    out.push({cols: t.querySelectorAll("thead th").length,
              rows: t.querySelectorAll("tbody tr").length,
              tableW: Math.round(t.getBoundingClientRect().width),
              containerW: wrap ? Math.round(wrap.clientWidth) : 0,
              thead_display: th ? getComputedStyle(th).display : null,
              card_cls: (t.className || "").toString().indexOf("edu-card-table") >= 0,
              labels: t.querySelectorAll("tbody td[data-label]").length});
  }
  return {tables: out,
          overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth};
}"""


def login(role):
    s = requests.Session()
    s.trust_env = False
    lg, pwd = ROLES[role]
    r = s.post(BASE + "/web/session/authenticate",
               json={"jsonrpc": "2.0",
                     "params": {"db": DB, "login": lg, "password": pwd}}, timeout=30)
    uid = (r.json().get("result") or {}).get("uid")
    return uid, s.cookies.get("session_id")


def main():
    # --target=path:role:tag（可重复）：只跑给定目标；不给就用 TARGETS
    tspec = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--target=")]
    targets = [tuple(s.split(":")) for s in tspec] if tspec else list(TARGETS)
    argv = [a for a in sys.argv[1:] if not a.startswith("--target=")]
    outdir = argv[0] if argv else "docs/audit/narrow-tables-c/shots"
    os.makedirs(outdir, exist_ok=True)
    readings = {}
    resp = {}
    for role in sorted({t[1] for t in targets}):
        resp[role] = login(role)
        print("login %-11s uid=%s cookie=%s" % (role, resp[role][0], bool(resp[role][1])))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True,
                                     args=["--no-proxy-server"])
        for path, role, tag in targets:
            uid, ck = resp[role]
            for vpname, w, h in (("phone", 375, 812), ("desk", 1440, 900)):
                ctx = browser.new_context(viewport={"width": w, "height": h})
                if ck:
                    ctx.add_cookies([{"name": "session_id", "value": ck,
                                      "domain": "localhost", "path": "/"}])
                page = ctx.new_page()
                page.goto(BASE + path, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(400)
                data = page.evaluate(MEASURE_JS)
                fp = os.path.join(outdir, "%s_%s.png" % (vpname, tag))
                page.screenshot(path=fp)
                if vpname == "phone":
                    readings[path] = data
                else:
                    readings[path + "#desk"] = data
                print("  %-6s %-22s -> %s" % (vpname, path, fp))
                ctx.close()
        browser.close()
    ap = os.path.join(outdir, "readings.json")
    with open(ap, "w", encoding="utf-8") as fh:
        json.dump(readings, fh, ensure_ascii=False, indent=1)
    print("落盘：" + ap)
    for k in sorted(readings):
        d = readings[k]
        for t in d["tables"]:
            squeezed = (t["thead_display"] != "none" and t["cols"] >= 4
                        and t["tableW"] > t["containerW"] + 4)
            print("  %-26s cols=%-2d w=%-4d container=%-4d thead=%-20s card=%-5s labels=%-3d %s"
                  % (k, t["cols"], t["tableW"], t["containerW"], t["thead_display"],
                     t["card_cls"], t["labels"], "SQUEEZED" if squeezed else "ok"))
    return 0


if __name__ == "__main__":
    sys.exit(main())