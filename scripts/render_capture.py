#!/usr/bin/env python3
"""登录态下捕获原站 JS 渲染完成后的 DOM（curl 抓不到的 Kendo 表格等）。
用法：python3 scripts/render_capture.py [page ...]
输出：reference/rendered/<name>.html
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://target-site.example/zh_CN"
OUT = Path(__file__).parent.parent / "reference" / "rendered"

PAGES = {
    "exam": "/student/exam",
    "assignment": "/student/assignment/details",
    "library_media": "/library/media",
    "timetable": "/student/timetable",
    "result_overview": "/users/result-overview",
    "my_home": "/my/home",
}
# 每页等待的渲染标记（出现即认为 Kendo/异步内容已就绪）
WAIT_SELECTORS = {
    "exam": ".k-grid, table, .oe-exam-page",
    "assignment": ".k-grid, table, .oe-asg-card",
    "library_media": ".k-grid, table",
    "timetable": "#timetable_portal_kendo .k-grid, .k-calendar, .k-widget",
    "result_overview": ".k-grid, table",
    "my_home": "#oe_charts_row svg",
}


def add_cookies(ctx):
    cookies = []
    for line in open("/tmp/cj.txt").read().splitlines():
        if not line.strip():
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.startswith(("#", "$")):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies.append({"domain": parts[0], "path": parts[2],
                            "name": parts[5], "value": parts[6]})
    ctx.add_cookies(cookies)


def main(names):
    OUT.mkdir(parents=True, exist_ok=True)
    todo = {k: PAGES[k] for k in (names or PAGES)}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for name, path in todo.items():
            ctx = browser.new_context(viewport={"width": 1440, "height": 2400},
                                      locale="zh-CN")
            add_cookies(ctx)
            page = ctx.new_page()
            try:
                page.goto(BASE + path, wait_until="load", timeout=45000)
                sel = WAIT_SELECTORS.get(name)
                if sel:
                    try:
                        page.wait_for_selector(sel, timeout=15000)
                    except Exception:
                        pass
                page.mouse.wheel(0, 4000)   # 触发懒加载
                page.wait_for_timeout(3000)
                html = page.evaluate("() => document.documentElement.outerHTML")
                out = OUT / f"{name}.html"
                out.write_text(html, encoding="utf-8")
                size = out.stat().st_size
                print(f"[OK] {name:16} -> reference/rendered/{name}.html ({size//1024}KB)")
            except Exception as e:
                print(f"[FAIL] {name}: {str(e)[:120]}")
            finally:
                ctx.close()
        browser.close()


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
