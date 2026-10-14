#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task-9 视觉缺陷 before/after 取证：同视口同页截图 + 机械可判的读数。

为什么两样都要：复核报告说的是「肉眼判断型」缺陷（门禁抓不到），所以证据必须是**图**；
但「修好了没有」不能只靠我看一眼 —— 每条缺陷配一个可复算的读数：
  V1 上手清单是否渲染在页面标题之上（比较两者 top）+ 它的高度占屏比
  V2 「帮助」链接的盒子高度（折行 ⇒ 高度 > 单行）
  V3 搜索框 placeholder 是否被截断（scrollWidth > clientWidth）
  V5 同屏可见的 search 输入框个数
  V6 同屏「通知数字」角标个数（同一数字说几遍）
  V8 是否存在「已截止」提示（#enroll-overdue-notice）

用法：
  /opt/homebrew/bin/python3 docs/audit/ui-visual-review/task9_shots.py <输出目录>
"""
import json
import os
import sys

import requests
from playwright.sync_api import sync_playwright

# 必须是 localhost：会话 cookie 的 domain 是 localhost，用 127.0.0.1 打开会拿不到会话（
# 实测后果：八张截图全是登录页）。口径与 scripts/check_ui_usability.py 的 BASE 一致。
BASE = "http://localhost:8069"
DB = "edu19"
LOGIN, PWD = "stu@local", "demo123"
PAGES = [("/my/home", "home"), ("/student/timetable", "timetable"),
         ("/subject/enroll", "enroll"), ("/student/attendance", "attendance")]
VIEWPORTS = [("phone", 390, 844), ("desk", 1440, 900)]

MEASURE_JS = """() => {
  const norm = s => (s || "").replace(/\\s+/g, " ").trim();
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const help = Array.from(document.querySelectorAll('a[href="/my/help"]')).filter(vis).map(a => {
    const r = a.getBoundingClientRect();
    // 折行的机械判据：inline 元素跨行时 getClientRects() 会给出多个盒子；
    // 只看 height 不行 —— 单行也是 36px（行高+图标），实测两态一样（那是假判据）。
    // 折行的机械判据：对**文本节点**取 Range 的矩形 —— flex 子项自身只有一个盒子，
    // getClientRects() 永远返回 1（实测假阴性：截图明明「帮 / 助」两行，元素级却报 1 行）。
    // Range 会把每行文本各给一个矩形 ⇒ 行数 = 矩形数。
    var rng = document.createRange();
    rng.selectNodeContents(a);
    var lines = rng.getClientRects().length;
    rng.detach && rng.detach();
    return {text: norm(a.innerText), h: Math.round(r.height), w: Math.round(r.width),
            top: Math.round(r.top), line_boxes: a.getClientRects().length, text_lines: lines}; });
  const canvas = document.createElement("canvas");
  const c2d = canvas.getContext("2d");
  const inputs = Array.from(document.querySelectorAll('input[type="search"]')).filter(vis).map(i => {
    const cs = window.getComputedStyle(i);
    c2d.font = cs.fontStyle + " " + cs.fontWeight + " " + cs.fontSize + " " + cs.fontFamily;
    const textw = Math.round(c2d.measureText(i.placeholder || "").width);
    const inner = i.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    return {id: i.id, ph: i.placeholder, w: i.clientWidth, inner_w: Math.round(inner),
            ph_text_w: textw, clipped: textw > inner}; });
  const onb = document.getElementById("yy-onboard");
  let onboard = null;
  if (onb && onb.offsetHeight > 0) {
    const r = onb.getBoundingClientRect();
    const heads = Array.from(document.querySelectorAll("h1,h2")).filter(vis);
    const h = heads.length ? heads[0].getBoundingClientRect() : null;
    onboard = {height: Math.round(r.height), top: Math.round(r.top),
               first_heading: heads.length ? norm(heads[0].innerText).slice(0, 30) : "",
               heading_top: h ? Math.round(h.top) : null,
               above_heading: h ? (r.top < h.top) : null};
  }
  const nums = {};
  document.querySelectorAll("span,b,div").forEach(e => {
    if (e.children.length) return;
    if (!vis(e)) return;
    const t = norm(e.innerText);
    if (/^\\d{1,4}$/.test(t)) { nums[t] = (nums[t] || 0) + 1; }
  });
  const overdue = document.getElementById("enroll-overdue-notice");
  return {help: help, search_inputs: inputs, onboard: onboard, number_badges: nums,
          overdue_notice: overdue ? norm(overdue.innerText).slice(0, 120) : null,
          deadline_texts: Array.from(document.querySelectorAll("div,p,span")).filter(e =>
              /本轮报课截止/.test(norm(e.innerText)) && e.children.length <= 3)
              .map(e => norm(e.innerText).slice(0, 90)).slice(0, 3),
          overdue_badges: Array.from(document.querySelectorAll("*")).filter(e =>
              e.children.length === 0 && norm(e.innerText) === "已截止").length,
          body_h: document.body.scrollHeight, title: document.title};
}"""


def login_cookie():
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + "/web/session/authenticate",
               json={"jsonrpc": "2.0",
                     "params": {"db": DB, "login": LOGIN, "password": PWD}}, timeout=30)
    uid = (r.json().get("result") or {}).get("uid")
    ck = s.cookies.get("session_id")
    print("login uid=%s cookie=%s" % (uid, bool(ck)))
    return ck


def block_external(route):
    url = route.request.url
    if url.startswith(BASE) or url.startswith("data:") or url.startswith("blob:"):
        route.continue_()
    else:
        route.abort()


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "docs/audit/ui-visual-review/task9-shots"
    os.makedirs(outdir, exist_ok=True)
    ck = login_cookie()
    readings = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True, args=["--no-proxy-server"])
        for vpname, w, h in VIEWPORTS:
            for path, tag in PAGES:
                ctx = browser.new_context(viewport={"width": w, "height": h})
                ctx.route("**/*", block_external)
                if ck:
                    ctx.add_cookies([{"name": "session_id", "value": ck,
                                      "domain": "localhost", "path": "/"}])
                page = ctx.new_page()
                page.goto(BASE + path, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(500)
                data = page.evaluate(MEASURE_JS)
                fp = os.path.join(outdir, "%s_%s.png" % (vpname, tag))
                page.screenshot(path=fp)
                readings["%s|%s" % (vpname, path)] = data
                print("  %-6s %-22s -> %s" % (vpname, path, fp))
                ctx.close()
        browser.close()
    ap = os.path.join(outdir, "readings.json")
    with open(ap, "w", encoding="utf-8") as fh:
        json.dump(readings, fh, ensure_ascii=False, indent=1)
    print("落盘：" + ap)
    return 0


if __name__ == "__main__":
    sys.exit(main())