#!/usr/bin/env python3
"""量两侧页面关键区块高度，输出差异报告。"""
from playwright.sync_api import sync_playwright

TARGETS = [
    ("my_home", "http://localhost:8069/my/home",
     "https://target-site.example/zh_CN/my/home"),
    ("timetable", "http://localhost:8069/student/timetable",
     "https://target-site.example/zh_CN/student/timetable"),
    ("profile", "http://localhost:8069/student/profile",
     "https://target-site.example/zh_CN/student/profile"),
    ("exam", "http://localhost:8069/student/exam",
     "https://target-site.example/zh_CN/student/exam"),
]

JS = """() => {
    const h = (sel) => { const el = document.querySelector(sel);
        return el ? Math.round(el.getBoundingClientRect().height) : -1; };
    return {
        header: h('header'),
        main: h('main'),
        hero: h('.o_portal_hero') || h('.o_portal_my_home') || -1,
        docs: h('.o_portal_docs'),
        sidebar: h('.oe-sidebar'),
        navbar: h('.o_portal_navbar'),
        content: h('.timetable_schedule_portal') || h('.oe-exam-page')
                 || h('.o_portal_content') || -1,
    };
}"""


def add_cookies(ctx, jar):
    """把 curl cookie jar 注入浏览器上下文。"""
    cookies = []
    for line in open(jar).read().splitlines():
        if not line.strip():
            continue
        if line.startswith('#HttpOnly_'):
            line = line[len('#HttpOnly_'):]
        elif line.startswith(('#', '$')):
            continue
        parts = line.split('\t')
        if len(parts) >= 7:
            cookies.append({'domain': parts[0], 'path': parts[2],
                            'name': parts[5], 'value': parts[6]})
    ctx.add_cookies(cookies)


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    for name, local_url, target_url in TARGETS:
        out = {}
        for side, url, jar in [("本地", local_url, "/tmp/lcj.txt"),
                               ("原站", target_url, "/tmp/cj.txt")]:
            ctx = b.new_context(viewport={"width": 1440, "height": 900})
            add_cookies(ctx, jar)
            pg = ctx.new_page()
            pg.goto(url, wait_until="load", timeout=45000)
            pg.wait_for_timeout(2500)
            out[side] = pg.evaluate(JS)
            ctx.close()
        print(f"\n== {name} ==")
        keys = out["本地"].keys()
        print(f"{'区块':10} {'本地':>6} {'原站':>6}")
        for k in keys:
            lv, tv = out["本地"][k], out["原站"][k]
            mark = "" if abs(lv - tv) < 60 or lv < 0 or tv < 0 else "  ← 差异"
            print(f"{k:10} {lv:>6} {tv:>6}{mark}")
    b.close()
