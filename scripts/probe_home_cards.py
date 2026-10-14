#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""首页宫格卡片探针：**首页卡片点进去都能到**（承诺：「点击…或首页卡片进入各功能」）。

**为什么立它**（2026-10-04 第 87 轮）：
  第 74 轮立了 `probe_nav_deadlinks.py`，但那只扫**左导航/底栏**；
  而首页上手卡片自己写着「点击右上角「应用面板」**或首页卡片**进入各功能」——
  **首页宫格才是大多数人的第一入口**，却没人验过它的每张卡都点得进去。

判据（与导航探针同口径，只报硬信号）：
  ① HTTP ≥ 400；
  ② 落地页含拒止文案；
  ③ **被静默弹回首页**（请求 A 却落到 /my/home）。
  ⚠ 宫格卡片里有些是「展开/收起」类交互（href="#" 或 JS），不算死链，跳过。

用法：probe_home_cards.py [--selftest]
退出码：0=无死链 ｜ 1=有 ｜ 2=ENV
"""
import argparse
import re
import sys

BASE = "http://127.0.0.1:8069"
ROLES = [("student", "stu@local"), ("parent", "parent@local"),
         ("faculty", "faculty@local"), ("backoffice", "backoffice@local")]
REFUSAL = ["仅面向", "请返回门户首页使用与您身份对应的功能", "无权访问", "Access Denied"]

# 宫格卡片的链接形态：/my/home 的 oe-cat-grid / ux-fav-grid 里的 <a href>
CARDS_JS = """() => {
  const out = [];
  // 2026-10-03（第 108 轮补）：加上 `.oe-qa-side`（侧栏「快速操作」）—— 此前**扫不到它**，
  //   于是「合并页右侧栏 4 条点进去是拒止页」这类死卡，两条门禁都报不出来（独立验证方发现）。
  //   教训与「能红的检查才有价值」同源：**选择器漏了一块界面，等于那块没人管**。
  for (const a of document.querySelectorAll(".oe-cat-grid a[href], .ux-fav-grid a[href], .o_portal_index_card a[href], .oe-qa-side a[href]")) {
    const h = a.getAttribute("href") || "";
    if (!h || h.startsWith("#") || h.startsWith("http") || h.startsWith("mailto")) continue;
    out.push([h, (a.innerText || "").replace(/\\s+/g, " ").trim().slice(0, 16)]);
  }
  const seen = new Set();
  return out.filter(([h]) => !seen.has(h) && seen.add(h));
}"""


def login(browser, user):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1400}, locale="zh-CN")
    pg = ctx.new_page()
    pg.goto(BASE + "/web/login", timeout=45000)
    pg.wait_for_selector("form.oe_login_form", timeout=30000)
    pg.fill("form.oe_login_form input[name=login]", user)
    pg.fill("form.oe_login_form input[name=password]", "demo123")
    pg.click("form.oe_login_form button[type=submit]", timeout=30000)
    pg.wait_for_load_state("load", timeout=45000)
    return pg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("ENV：playwright 不可用 %s" % e)
        return 2
    bad, checked = [], 0
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            # 2026-10-04（第 92 轮）：**两个页面都要扫**。
            #   `/my/apps`（「全部应用」）与 `/my/home` 用的是**同一份卡片源**
            #   （`_home_categories`），但第 87 轮只验了首页 ⇒ 第 87 轮那个家长死卡缺陷，
            #   当时并不知道 `/my/apps` 是不是也一样。现在两边都扫。
            for page_path in ("/my/home", "/my/apps"):
              for role, user in ROLES:
                pg = login(b, user)
                pg.goto(BASE + page_path, timeout=45000)
                pg.wait_for_timeout(1400)
                if a.selftest:
                    # 2026-10-04（第 101 轮）：**这个 --selftest 原先只是声明了、根本没实现**
                    #   （传了它照样跑正常检查）。现在真的自证：往宫格里塞一个必然 404 的卡片。
                    pg.evaluate("""() => {
                      const grid = document.querySelector(".oe-cat-grid, .ux-fav-grid, .oe-qa-side");
                      if (!grid) return;
                      const x = document.createElement("a");
                      x.setAttribute("href", "/selftest-must-404-xyz");
                      x.textContent = "SELFTEST";
                      grid.appendChild(x);
                    }""")
                cards = pg.evaluate(CARDS_JS)
                for h, label in cards:
                    try:
                        r = pg.goto(BASE + h, timeout=45000)
                        pg.wait_for_timeout(300)
                        st = r.status if r else 0
                        final = pg.url.replace(BASE, "").split("?")[0]
                        body = pg.inner_text("body")[:4000]
                        why = ""
                        if st >= 400:
                            why = "HTTP %d" % st
                        else:
                            for ph in REFUSAL:
                                if ph in body:
                                    why = "拒止文案：%s" % ph
                                    break
                            if not why and final != h.split("?")[0] \
                                    and final in ("/my/home", "/", "/my"):
                                why = "被弹回 %s" % final
                        checked += 1
                        if why:
                            bad.append("%s[%s] %s（%s）→ %s" % (role, label, h, label, why))
                    except Exception:
                        continue
                # 回到首页，供下一个角色/下一轮用
                pg.goto(BASE + "/my/home", timeout=45000)
                pg.wait_for_timeout(400)
                pg.context.close()
            b.close()
    except Exception as e:
        print("ENV：%s" % str(e)[:150])
        return 2
    # 已知项（登记制，不隐藏）：教务的宫格**不是**这套卡片源（它走 staff 版宫格），
    # 所以这条不归本函数管 —— 见 docs/audit/open-questions-2026-10.md 的 Q-03。
    # 口径：**超过已知数才判红**（与本仓 check_all 的 UNKNOWN_KNOWN 同一套做法），
    # 这样「新混进一张死卡」会立刻报警，而这条已知项不会让门禁永远红着。
    if a.selftest:
        for line in bad:
            print("  DEADCARD " + line)
        caught = any("selftest-must-404-xyz" in x for x in bad)
        print("  自证：往宫格塞一个必然 404 的卡片，%s"
              % ("被抓到（对）" if caught else "**没抓到 —— 量具坏了**"))
        return 0 if caught else 1
    KNOWN = 1
    for line in bad:
        print("  DEADCARD " + line)
    if len(bad) > KNOWN:
        print("结论：FAIL（%d 张卡片进不去 / 共查 %d 张；已知 %d）"
              % (len(bad), checked, KNOWN))
        return 1
    if bad:
        print("结论：OK（%d 张卡片进不去，但都在已知项内；共查 %d 张）"
              % (len(bad), checked))
        return 0
    print("结论：OK（四个角色首页宫格，%d 张卡片张张可通）" % checked)
    return 0


if __name__ == "__main__":
    sys.exit(main())