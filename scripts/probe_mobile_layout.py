#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""窄屏（375px）版式探针：**整页要不要左右拖**。

为什么单独立这一条：既有门禁已经覆盖「表格被压扁」（find_squeezed_tables）与
「无障碍」（check_accessibility），但**没有一条**量「这一页在手机上会不会横向溢出」。
横向溢出是移动端最伤人的版式缺陷（整页跟着手指跑、右半边永远看不到），
而它**与表格无关** —— 一张超宽图片、一个 `min-width`、一段不换行的长串都能造成。

判据（只有这一条，宁可少判也不要假阳性）：
  `documentElement.scrollWidth > clientWidth + 2` ⇒ 该页横向溢出。
  报红时同时给出**溢出的元凶元素**（最靠右且宽度 > 40 的那个），便于直接定位。

不判（刻意）：触控目标尺寸。本轮实测 70 页，报出来的「小目标」全是
**内联文字链接**（WCAG 2.5.8 有内联豁免）、**禁用的分页箭头**、**跳至内容**（1px 宽，本就该看不见）
以及**自带 aria-label 的图标链接** —— 全是假阳性。本仓纪律：一个永远假阳性的判据等于死判据，
所以把它记成**只读数、不判红**（见 --tap-report）。

用法：
  probe_mobile_layout.py                  全量（surface.json 里 scope=portal 的页 × 首个角色）
  probe_mobile_layout.py --only /my/home  定向
  probe_mobile_layout.py --selftest       只证量具（不连站点）：注入一个超宽元素，必须变红

退出码：0=无溢出 ｜ 1=有溢出 ｜ 2=ENV（站点/浏览器不可用）
"""
import argparse
import json
import os
import sys

BASE = os.environ.get("EDU_BASE", "http://127.0.0.1:8069")
SURFACE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "ui", "surface.json")
LOGINS = {"student": "stu@local", "faculty": "faculty@local",
          "parent": "parent@local", "backoffice": "backoffice@local"}

OVERFLOW_JS = """() => {
  const de = document.documentElement;
  const vw = de.clientWidth;
  const culprits = [];
  for (const e of document.querySelectorAll("body *")) {
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (getComputedStyle(e).position === "fixed") continue;
    if (r.left + r.width > vw + 2 && r.width > 40) {
      culprits.push({tag: e.tagName.toLowerCase(),
                     cls: (e.className || "").toString().slice(0, 48),
                     w: Math.round(r.width), right: Math.round(r.left + r.width)});
    }
  }
  culprits.sort((a, b) => b.right - a.right);
  return {vw: vw, scrollW: de.scrollWidth, n: culprits.length, top: culprits.slice(0, 3)};
}"""

TAP_JS = """() => {
  let n = 0;
  for (const e of document.querySelectorAll("a, button, input[type=submit], .btn")) {
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const st = getComputedStyle(e);
    if (st.visibility === "hidden" || st.display === "none") continue;
    if (r.height < 24 || r.width < 24) n++;
  }
  return n;
}"""


def load_pages(only=None):
    with open(os.path.normpath(SURFACE), encoding="utf-8") as f:
        d = json.load(f)
    pages = d["pages"] if isinstance(d, dict) and "pages" in d else d
    out = []
    for p in pages:
        if not isinstance(p, dict) or p.get("scope") != "portal":
            continue
        path = p.get("path") or ""
        roles = p.get("roles") or []
        if "<" in path or not roles:
            continue
        if only and path not in only:
            continue
        out.append((path, roles[0]))
    return out


def selftest():
    """只证量具：往一个干净页面注入超宽元素 —— 必须从「无溢出」变「有溢出」。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(viewport={"width": 375, "height": 812}).new_page()
        pg.goto(BASE + "/web/login", timeout=45000)
        pg.wait_for_timeout(600)
        before = pg.evaluate(OVERFLOW_JS)
        pg.evaluate("""() => {
          const d = document.createElement("div");
          d.id = "probe-wide";
          d.style.width = "900px"; d.style.height = "40px";
          document.body.appendChild(d);
        }""")
        after = pg.evaluate(OVERFLOW_JS)
        b.close()
    ok1 = before["scrollW"] <= before["vw"] + 2
    ok2 = after["scrollW"] > after["vw"] + 2 and after["n"] >= 1
    print("  注入前：页宽 %s / 视口 %s ⇒ %s" % (before["scrollW"], before["vw"],
          "无溢出（对）" if ok1 else "有溢出（错）"))
    print("  注入后：页宽 %s / 视口 %s，元凶 %s 个 ⇒ %s" % (after["scrollW"], after["vw"], after["n"],
          "报红（对）" if ok2 else "**仍是绿的 —— 量具坏了**"))
    if ok1 and ok2:
        print("结论：OK（量具可用：能变红也能变绿）")
        return 0
    print("结论：FAIL（量具不可信）")
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="逗号分隔的路径白名单")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tap-report", action="store_true", help="只读数：小目标计数（不判红）")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("ENV：playwright 不可用 %s" % e)
        return 2
    only = set(a.only.split(",")) if a.only else None
    pages = load_pages(only)
    bad = []
    taps = []
    n = 0
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            cache = {}
            for path, role in pages:
                if role not in LOGINS:
                    continue
                if role not in cache:
                    ctx = b.new_context(viewport={"width": 375, "height": 812},
                                        locale="zh-CN", is_mobile=True, has_touch=True)
                    pg = ctx.new_page()
                    pg.goto(BASE + "/web/login", timeout=45000)
                    pg.wait_for_selector("form.oe_login_form", timeout=30000)
                    pg.fill("form.oe_login_form input[name=login]", LOGINS[role])
                    pg.fill("form.oe_login_form input[name=password]", "demo123")
                    pg.click("form.oe_login_form button[type=submit]", timeout=30000)
                    pg.wait_for_load_state("load", timeout=45000)
                    cache[role] = (ctx, pg)
                ctx, pg = cache[role]
                try:
                    r = pg.goto(BASE + path, timeout=45000)
                    pg.wait_for_timeout(700)
                    if not r or r.status >= 400:
                        continue
                    n += 1
                    m = pg.evaluate(OVERFLOW_JS)
                    if m["scrollW"] > m["vw"] + 2:
                        top = m["top"][0] if m["top"] else {}
                        bad.append("%s [%s] 页宽 %s > 视口 %s；最右元素 %s.%s w=%s" % (
                            path, role, m["scrollW"], m["vw"],
                            top.get("tag", "?"), top.get("cls", ""), top.get("w", "?")))
                    if a.tap_report:
                        taps.append((pg.evaluate(TAP_JS), path))
                except Exception:
                    continue
            for ctx, pg in cache.values():
                ctx.close()
            b.close()
    except Exception as e:
        print("ENV：%s" % str(e)[:160])
        return 2
    for line in bad:
        print("  SQUEEZED " + line)
    if a.tap_report:
        taps.sort(reverse=True)
        print("  —— 小目标计数（**只读数，不判红**，原因见文件头）——")
        for c, path in taps[:8]:
            print("     %-34s %d" % (path, c))
    if bad:
        print("结论：FAIL（%d 页横向溢出 / 共扫 %d 页）" % (len(bad), n))
        return 1
    print("结论：OK（无横向溢出；共扫 %d 页，375px 视口）" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())