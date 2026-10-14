#!/usr/bin/env python3
"""仅补拍管理员后台（跳过 networkidle，改用固定等待）。"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8069"
OUT = Path(__file__).parent.parent / "shots" / "local"
ACTION = os.environ.get("EDU_ACTION_ID", "")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                              locale="zh-CN")
    page = ctx.new_page()
    try:
        page.goto(BASE + "/web/login")
        page.fill("#login", "admin")
        page.fill("#password", "admin")
        page.locator(".oe_login_form button[type=submit]").first.click()
        page.wait_for_timeout(4000)
        page.goto(BASE + f"/web#action={ACTION}", timeout=60000)
        page.wait_for_timeout(9000)
        page.screenshot(path=str(OUT / "lms_admin_backend.png"))
        print("OK  admin_backend")
    except Exception as e:
        print(f"FAIL admin_backend: {str(e)[:160]}")
    finally:
        ctx.close()
    browser.close()
