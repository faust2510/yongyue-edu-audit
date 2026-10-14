#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找出「内部页面用了公开站外壳」的页面 —— **报告型工具**。

## 现象与危害

门户的内部页面应当用门户壳（顶栏搜索 + 角色导航 + 移动端底部 Tab）。
若某页 `t-call="website.layout"` 而没用 `edu_portal.edu_page`，它会渲染**公开站页头**，后果有三：
  ① 对**已登录用户**显示「登录」链接（措辞错的）；
  ② 移动端**没有底部 Tab**（门户的主要导航方式）⇒ 用户只能靠浏览器后退；
  ③ 与其余 ~90 个门户页观感割裂。

## 判据（在 375 视口，登录后逐页量）

同一批判别器自 round 6 起沿用：
  · 公开页头可见（`.o_header_standard` / `#wrapwrap > header` 有尺寸）；
  · 门户顶栏搜索 `#b11-topsearch` 不可见；
  · 页面上存在**可见的** `a[href="/login"]`；
  · 底部 Tab（`#b11-tabbar a`）为 **0**。
前两条是主判据；后两条是同一件事的旁证。

## ⚠ 关键限定：**公开页用公开壳是对的**，必须先排除它们

第一版没有这一层，于是把 `/help`（5 页）与 `/online-exams` 也报了进来，得出「13 页」。
但实测：**这些页匿名可读**（`/help` 整族匿名 200 且无登录表单；`/online-exams` 是
`edu_public` 的 `auth='public'` 路由，该模块 manifest 写明「游客可访问的公开页：课程列表 / 在线考试 / 数字图书馆」）
⇒ **对公开页来说，公开壳正是它该有的样子**。

所以判据加一条**前置过滤**：先把**匿名可读**的路径排除，再问「剩下的内部页里，谁用了公开壳」。
（教训：**「看起来不对」要先问「它本来该是什么」** —— 少了这一步，13 页里有 6 页是冤案。）

## 结论（2026-10-02 全量复核，90 条门户路径；已排除公开页）

见运行时打印。round 6 凭抽样给出 6 页，全量复核后为 **7 页**（多出 `/my-courses`）。

玩法：
    python3 scripts/find_wrong_shell.py            # 全量（约 8 分钟）
    python3 scripts/find_wrong_shell.py --path /quiz --role student
"""
import argparse
import io
import json
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8069"
LOGINS = {"student": ("stu@local", "demo123"),
          "faculty": ("faculty@local", "demo123"),
          "backoffice": ("backoffice@local", "demo123"),
          "parent": ("parent@local", "demo123")}

JS = """() => {
  const vis = e => { if (!e) return false; const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const pub = document.querySelector(".o_header_standard, #wrapwrap > header");
  const search = document.querySelector("#b11-topsearch");
  let login = false;
  for (const a of document.querySelectorAll("a")) {
    if ((a.getAttribute("href") || "") === "/login" && vis(a)) login = true;
  }
  return {pub: vis(pub), search: !!search && vis(search), login: login,
          tabs: document.querySelectorAll("#b11-tabbar a, .b11-tabbar a").length};
}"""


def login(pg, user, pwd):
    pg.goto(BASE + "/web/login", timeout=45000)
    pg.wait_for_selector("form.oe_login_form", timeout=30000)
    pg.fill("form.oe_login_form input[name=login]", user)
    pg.fill("form.oe_login_form input[name=password]", pwd)
    pg.click("form.oe_login_form button[type=submit]", timeout=30000)
    pg.wait_for_load_state("load", timeout=45000)
    if "/web/login" in pg.url:
        raise RuntimeError("登录失败（停在 %s）" % pg.url)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=None)
    ap.add_argument("--role", default="student")
    a = ap.parse_args()
    bad = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        if a.path:
            user, pwd = LOGINS[a.role]
            ctx = b.new_context(viewport={"width": 375, "height": 812}, locale="zh-CN")
            pg = ctx.new_page()
            login(pg, user, pwd)
            pg.goto(BASE + a.path, timeout=45000)
            pg.wait_for_timeout(800)
            d = pg.evaluate(JS)
            print("  %s -> %s" % (a.path, d))
            ctx.close()
            b.close()
            return 1 if d["pub"] and not d["search"] else 0
        data = json.load(io.open("tests/ui/surface.json", encoding="utf-8"))
        pages = data["pages"] if isinstance(data, dict) and "pages" in data else data
        targets = [x for x in pages if isinstance(x, dict) and x.get("scope") == "portal"
                   and isinstance(x.get("path"), str) and x["path"].startswith("/") and "<" not in x["path"]]
        # ── 前置过滤：匿名可读的路径是**公开页**，公开壳对它们是对的，先排除 ──
        public_paths = set()
        actx = b.new_context(viewport={"width": 375, "height": 812}, locale="zh-CN")
        apg = actx.new_page()
        for it in targets:
            try:
                r = apg.goto(BASE + it["path"], timeout=20000)
                if r and r.status == 200 and "oe_login_form" not in apg.content():
                    public_paths.add(it["path"])
            except Exception:
                continue
        actx.close()
        print("  匿名可读（= 公开页，不判）：%d 条" % len(public_paths))
        for role, (user, pwd) in LOGINS.items():
            ctx = b.new_context(viewport={"width": 375, "height": 812}, locale="zh-CN")
            pg = ctx.new_page()
            try:
                login(pg, user, pwd)
            except Exception as e:
                print("  登录失败 %s：%s" % (role, e))
                ctx.close()
                continue
            for it in targets:
                if role not in (it.get("roles") or []):
                    continue
                path = it["path"]
                if path in public_paths:
                    continue
                try:
                    r = pg.goto(BASE + path, timeout=25000)
                    pg.wait_for_timeout(350)
                    if not r or r.status >= 400:
                        continue
                    d = pg.evaluate(JS)
                    if d["pub"] and not d["search"]:
                        bad.setdefault(path, (role, d))
                except Exception:
                    continue
            ctx.close()
        b.close()
    print("=== 内部页用了公开壳（公开页头可见 且 门户顶栏搜索不可见）===")
    for path, (role, d) in sorted(bad.items()):
        print("  %-34s [%-10s] 登录链接=%-5s 底部Tab=%d" % (path, role, d["login"], d["tabs"]))
    print("命中页面数：%d" % len(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())