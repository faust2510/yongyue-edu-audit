#!/usr/bin/env python3
"""干净复测：教师对未读布告(id=15) 阅后角标 15→14；并验证 OMR 死链 404。"""
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8069"
SHOTS = Path(__file__).parent.parent / "shots" / "v2_review"


def bell(page):
    loc = page.locator(".oe-mhead-badge").first
    return int(re.sub(r"\D", "", loc.inner_text() or "0") or 0)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context()
    page = ctx.new_page()
    page.goto(BASE + "/web/login", wait_until="domcontentloaded")
    f = page.locator("form.oe_login_form").first
    f.locator("input[name=login]").fill("faculty@local")
    f.locator("input[name=password]").fill("demo123")
    f.locator("button[type=submit]").first.click()
    page.wait_for_load_state("domcontentloaded")

    page.goto(BASE + "/my/home", wait_until="domcontentloaded")
    page.wait_for_timeout(800)
    b0 = bell(page)

    resp = page.goto(BASE + "/my/notice/15", wait_until="domcontentloaded")
    page.wait_for_timeout(600)
    detail_ok = "/my/notice/15" in page.url and resp.status == 200
    page.screenshot(path=str(SHOTS / "t_detail_n15.png"), full_page=True)

    page.goto(BASE + "/my/home", wait_until="domcontentloaded")
    page.wait_for_timeout(800)
    b1 = bell(page)

    page.goto(BASE + "/my/notice_board/notice",
              wait_until="domcontentloaded")
    page.wait_for_timeout(500)
    stat = None
    for v in page.locator(".oe-statbox").all_inner_texts():
        if "我的未读" in v:
            stat = int(re.search(r"(\d+)", v.replace("我的未读", "")).group(1))

    # OMR 死链状态码（教师会话）
    r404 = page.goto(BASE + "/openeducat-omr/exam-result",
                     wait_until="domcontentloaded")

    print(f"bell_before={b0} detail_200={detail_ok} bell_after={b1} "
          f"board_stat={stat} decremented={b1 < b0}")
    print(f"omr_exam_result_status={r404.status}")
    ctx.close()
    b.close()
