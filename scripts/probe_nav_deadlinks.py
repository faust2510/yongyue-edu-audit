#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导航死链探针：**自己导航里给出的入口，点进去不该是拒止页**。

为什么立它（2026-10-04 第 74 轮）：
  第 73 轮以家长身份看首页时发现「出勤趋势 0%」那类**角色特有的空/误导态**；
  顺着想：还有一种更硬的坏体验 —— 导航里明明有这个入口，点进去却是
  「该页面仅面向学生账号」这种拒止页（第 54 轮在教师端就撞到过一次同款）。
  这类问题**门禁扫不到**：`check_ui_surface` 只看「路由登记没登记」，
  `check_accessibility` 只看无障碍 —— 没人问过「这个角色自己的导航，条条都通吗」。

判据（只报两种硬信号，不做主观判断）：
  ① HTTP ≥ 400；
  ② 落地页正文含**拒止文案**（「仅面向」「请返回门户首页使用与您身份对应的功能」
     「无权访问」「Access Denied」）。
  ⚠ 只看**门户导航**（.b11-side / 移动端 tabbar）里的链接 —— 页脚、网站菜单不算，
     那些本来就允许对匿名/其他角色显示。

用法：probe_nav_deadlinks.py [--selftest]
退出码：0=无死链 ｜ 1=有死链 ｜ 2=ENV
"""
import argparse
import re
import sys

BASE = "http://127.0.0.1:8069"
ROLES = [("student", "stu@local"), ("parent", "parent@local"),
         ("faculty", "faculty@local"), ("backoffice", "backoffice@local")]
REFUSAL = ["仅面向", "请返回门户首页使用与您身份对应的功能", "无权访问", "Access Denied"]

NAV_JS = """() => {
  const sel = ".b11-side a[href], .b11-tabbar a[href], aside a[href]";
  const out = [];
  for (const a of document.querySelectorAll(sel)) {
    const h = a.getAttribute("href") || "";
    if (!h || h.startsWith("#") || h.startsWith("http") || h.startsWith("/web")) continue;
    out.push(h);
  }
  return [...new Set(out)];
}"""


def login(browser, user):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1200}, locale="zh-CN")
    pg = ctx.new_page()
    pg.goto(BASE + "/web/login", timeout=45000)
    pg.wait_for_selector("form.oe_login_form", timeout=30000)
    pg.fill("form.oe_login_form input[name=login]", user)
    pg.fill("form.oe_login_form input[name=password]", "demo123")
    pg.click("form.oe_login_form button[type=submit]", timeout=30000)
    pg.wait_for_load_state("load", timeout=45000)
    if "/web/login" in pg.url:
        raise RuntimeError("登录后仍在 /web/login（%s）" % user)
    return pg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="只证量具：往导航里塞一个必拒止的链接")
    a = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("ENV：playwright 不可用 %s" % e)
        return 2
    bad = []
    checked = 0
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            for role, user in ROLES:
                pg = login(b, user)
                pg.goto(BASE + "/my/home", timeout=45000)
                pg.wait_for_timeout(1200)
                if a.selftest:
                    # 注入一个「必定拒止」的导航项：学生看教师页
                    pg.evaluate("""() => {
                      // 用**与 NAV_JS 完全相同的选择器**取容器：先前写死 .b11-side/aside，
                      // 桌面端未必命中 ⇒ 注入了却没人读，自证当然抓不到。
                      const side = document.querySelector(".b11-side a, .b11-tabbar a, aside a");
                      if (!side) return;
                      const x = document.createElement("a");
                      // ⚠ 必须用 setAttribute：JS 里 `x.href = "/x"` 会写成**绝对 URL**，
                      //   而 NAV_JS 会跳过 http 开头的链接 ⇒ 自证当时没抓到（量具自己先被证伪了一次）。
                      // 自证用**必然 404** 的路径：不依赖任何角色的权限语义。
                      //（先前用 /assignment/manage 是错的：学生访问它**不是拒止**，
                      //  而是被静默 302 回 /my/home ⇒ 当然抓不到。这条也顺带成了下面的判据 ③。）
                      x.setAttribute("href", "/selftest-must-404-xyz");
                      x.textContent = "SELFTEST";
                      side.parentElement.appendChild(x);
                    }""")
                links = pg.evaluate(NAV_JS)
                for h in links:
                    try:
                        r = pg.goto(BASE + h, timeout=45000)
                        pg.wait_for_timeout(350)
                        st = r.status if r else 0
                        body = pg.inner_text("body")[:4000]
                        why = ""
                        if st >= 400:
                            why = "HTTP %d" % st
                        elif pg.url.replace(BASE, "").split("?")[0] not in (h.split("?")[0],) \
                                and pg.url.replace(BASE, "").split("?")[0] in ("/my/home", "/", "/my"):
                            # 判据 ③（本轮补）：**被静默弹回首页** —— 请求 A 却落到首页，
                            #   等于「导航里有这个入口，点了却进不去」，正是第 54 轮那类死链。
                            #   （学生访问 /assignment/manage 就是这种：302 → /my/home，
                            #    既不报错也不给拒止文案 ⇒ 只看状态码与文案是抓不到的。）
                            why = "被弹回 %s（原请求 %s）" % (pg.url.replace(BASE, "")[:20], h)
                        else:
                            for ph in REFUSAL:
                                if ph in body:
                                    why = "拒止文案：%s" % ph
                                    break
                        checked += 1
                        if why:
                            bad.append("%s[%s] %s → %s" % (role, user.split("@")[0], h, why))
                    except Exception:
                        continue
                pg.context.close()
            b.close()
    except Exception as e:
        print("ENV：%s" % str(e)[:150])
        return 2
    for line in bad:
        print("  DEADLINK " + line)
    if a.selftest:
        ok = any("/selftest-must-404-xyz" in x for x in bad)
        print("  自证：注入的必拒止链接%s" % ("被抓到（对）" if ok else "**没被抓到 —— 量具坏了**"))
        return 0 if ok else 1
    if bad:
        print("结论：FAIL（%d 条导航死链 / 共查 %d 条链接）" % (len(bad), checked))
        return 1
    print("结论：OK（四个角色的门户导航，%d 条链接条条可通）" % checked)
    return 0


if __name__ == "__main__":
    sys.exit(main())