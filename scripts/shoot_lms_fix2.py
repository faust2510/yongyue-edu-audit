#!/usr/bin/env python3
"""LMS 补拍 v2：按 action 定位表单提交；后台用 /web#action。"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8069"
OUT = Path(__file__).parent.parent / "shots" / "local"
LESSON = os.environ.get("EDU_LESSON_ID", "")
ACTION = os.environ.get("EDU_ACTION_ID", "")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)

    ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                              locale="zh-CN")
    page = ctx.new_page()
    try:
        page.goto(BASE + "/web/login")
        page.fill("#login", "stu@local")
        page.fill("#password", "demo123")
        page.locator(".oe_login_form button[type=submit]").first.click()
        page.wait_for_load_state("networkidle")

        page.goto(BASE + f"/my/courses/lesson/{LESSON}", timeout=45000)
        page.wait_for_load_state("networkidle")
        # DOM 诊断：页面上有哪些 form/button
        info = page.evaluate(
            "() => ({forms: [...document.querySelectorAll('form')]"
            ".map(f => f.getAttribute('action')),"
            " buttons: document.querySelectorAll('button').length,"
            " doneBtn: !!document.querySelector('form[action*=\"/done\"]')"
            "})")
        print("DOM:", info)

        submitted = page.evaluate(
            "() => { const f = [...document.querySelectorAll('form')]"
            ".find(x => (x.getAttribute('action')||'')"
            ".includes('/done'));"
            " if (!f) return false;"
            " const b = f.querySelector('button[type=submit]');"
            " if (b) { b.click(); return 'click'; }"
            " f.submit(); return 'submit'; }")
        print("提交方式:", submitted)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)
        print("提交后 URL:", page.url)
        page.screenshot(path=str(OUT / "lms_student_lesson_done.png"),
                        full_page=True)
        print("OK  student_lesson_done")
    except Exception as e:
        print(f"FAIL student_lesson_done: {str(e)[:160]}")
    finally:
        ctx.close()

    ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                              locale="zh-CN")
    page = ctx.new_page()
    try:
        page.goto(BASE + "/web/login")
        page.fill("#login", "admin")
        page.fill("#password", "admin")
        page.locator(".oe_login_form button[type=submit]").first.click()
        page.wait_for_load_state("networkidle")
        page.goto(BASE + f"/web#action={ACTION}", timeout=60000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(6000)
        page.screenshot(path=str(OUT / "lms_admin_backend.png"))
        print("OK  admin_backend")
    except Exception as e:
        print(f"FAIL admin_backend: {str(e)[:160]}")
    finally:
        ctx.close()
    browser.close()
