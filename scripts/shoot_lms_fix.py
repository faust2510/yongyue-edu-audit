#!/usr/bin/env python3
"""补拍 LMS 缺失的两张：学生完成态 + 管理员后台。"""
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
    login_ok = True
    try:
        page.goto(BASE + "/web/login")
        page.fill("#login", "stu@local")
        page.fill("#password", "demo123")
        page.locator(".oe_login_form button[type=submit]").first.click()
        page.wait_for_load_state("networkidle")
        page.goto(BASE + f"/my/courses/lesson/{LESSON}", timeout=45000)
        page.wait_for_load_state("networkidle")
        # 表单直提（绕过定位器兼容问题）
        page.evaluate("() => { const f=document.querySelector('form');"
                      " if(f) f.submit(); }")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "lms_student_lesson_done.png"),
                        full_page=True)
        print("OK  student_lesson_done")
    except Exception as e:
        login_ok = False
        print(f"FAIL student_lesson_done: {str(e)[:140]}")
    finally:
        ctx.close()

    if login_ok and ACTION:
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  locale="zh-CN")
        page = ctx.new_page()
        try:
            page.goto(BASE + "/web/login")
            page.fill("#login", "admin")
            page.fill("#password", "admin")
            page.locator(".oe_login_form button[type=submit]").first.click()
            page.wait_for_load_state("networkidle")
            page.goto(BASE + f"/odoo/action-{ACTION}", timeout=45000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(5000)
            page.screenshot(path=str(OUT / "lms_admin_backend.png"))
            print("OK  admin_backend")
        except Exception as e:
            print(f"FAIL admin_backend: {str(e)[:140]}")
        finally:
            ctx.close()
    browser.close()
