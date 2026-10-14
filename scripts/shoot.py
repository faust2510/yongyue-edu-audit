#!/usr/bin/env python3
"""双端截图：本地复刻 vs 原站，用于逐页视觉校准。
用法：python3 scripts/shoot.py [页面组名]
输出：shots/local/<name>.png 与 shots/target/<name>.png（1440 宽全页）
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

SHOTS = Path(__file__).parent.parent / "shots"

PAGES = [
    ("my_home", "/my/home"),
    ("timetable", "/student/timetable"),
    ("attendance", "/student/attendance"),
    ("profile", "/student/profile"),
    ("exam", "/student/exam"),
    ("assignment", "/student/assignment/details"),
    ("gradebook", "/grade-book"),
    ("library_media", "/library/media"),
    ("subject_details", "/subject/details"),
    ("notice_board", "/my/notice_board/notice"),
]

LOCAL = {"base": "http://localhost:8069", "user": "stu@local", "pwd": "demo123"}
TARGET = {"base": "https://target-site.example/zh_CN",
          "user": "student@openeducat.com", "pwd": "student"}


def login(page, cfg):
    page.goto(cfg["base"] + ("/web/login" if "zh_CN" not in cfg["base"] else "/web/login"))
    page.fill("#login", cfg["user"])
    page.fill("#password", cfg["pwd"])
    page.locator(".oe_login_form button[type=submit]").first.click()
    page.wait_for_load_state("networkidle")
    return page


def shoot(side, cfg, names):
    out = SHOTS / side
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  locale="zh-CN")
        page = ctx.new_page()
        login(page, cfg)
        for name, path in PAGES:
            if names and name not in names:
                continue
            try:
                page.goto(cfg["base"] + path, timeout=45000)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(800)
                page.screenshot(path=str(out / f"{name}.png"), full_page=True)
                print(f"[{side}] {name} OK -> shots/{side}/{name}.png")
            except Exception as e:
                print(f"[{side}] {name} FAIL: {str(e)[:100]}")
        browser.close()


if __name__ == "__main__":
    names = set(sys.argv[1:]) or None
    shoot("target", TARGET, names)
    shoot("local", LOCAL, names)
