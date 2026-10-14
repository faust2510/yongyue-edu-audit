#!/usr/bin/env python3
"""t2 修复回归：学生首页死卡/财务卡指向/资产请求卡/布告详情 active 过滤。"""
import re
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8069"
SHOTS = Path(__file__).parent.parent / "shots" / "v2_review"
OUT = {}


def login(page, user, pwd):
    page.goto(BASE + "/web/login", wait_until="domcontentloaded")
    f = page.locator("form.oe_login_form").first
    f.locator("input[name=login]").fill(user)
    f.locator("input[name=password]").fill(pwd)
    f.locator("button[type=submit]").first.click()
    page.wait_for_load_state("domcontentloaded")
    return "/web/login" not in page.url


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context()
    page = ctx.new_page()
    assert login(page, "stu@local", "demo123")

    # ---- 学生首页卡片盘点 ----
    page.goto(BASE + "/my/home", wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    page.screenshot(path=str(SHOTS / "r_student_home_fixed.png"),
                    full_page=True)
    cards = page.evaluate("""() => {
        const out = [];
        document.querySelectorAll('.o_portal_index_card').forEach(c => {
            const a = c.querySelector('a');
            out.push({title: (c.textContent||'').trim().slice(0,26),
                      href: a ? a.getAttribute('href') : ''});
        });
        return out;
    }""")
    raw = [c for c in cards if re.fullmatch(r"[a-z\-/]+", c["title"] or "")]
    dead = [c for c in cards if "/openeducat-omr" in (c["href"] or "")]
    fin = [c for c in cards if c["href"] == "/my/fees"]
    asset = [c for c in cards if c["href"] == "/my/asset-request"]
    OUT["cards_total"] = len(cards)
    OUT["raw_title_cards"] = raw
    OUT["omr_dead_links"] = dead
    OUT["finance_card_present"] = bool(fin)
    OUT["finance_card"] = fin
    OUT["asset_request_card_present"] = bool(asset)

    # ---- 布告详情 active 过滤（插入 inactive 测试布告）----
    nid = subprocess.run(
        ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo",
         "-d", "edu19", "-Atc",
         "INSERT INTO edu_notice (name, content, sender, date, active, "
         "create_uid, write_uid, create_date, write_date, category) "
         "VALUES ('回归测试-归档布告', 'x', 't', CURRENT_DATE, false, "
         "2, 2, now(), now(), 'notice') RETURNING id;"],
        capture_output=True, text=True).stdout.strip().splitlines()[0]
    assert nid.isdigit(), f"bad id: {nid!r}"
    OUT["test_notice_id"] = nid
    resp = page.goto(f"{BASE}/my/notice/{nid}", wait_until="domcontentloaded")
    page.wait_for_timeout(400)
    redirected = page.url.rstrip("").endswith("/my/notice_board/notice") \
        or "/my/notice_board/notice" in page.url
    OUT["inactive_detail_redirected"] = redirected
    OUT["detail_http_status"] = resp.status
    # 归档布告不应计入未读（学生此前已全读，未读应为 0）
    page.wait_for_timeout(300)
    stat = None
    for v in page.locator(".oe-statbox").all_inner_texts():
        if "我的未读" in v:
            m = re.search(r"(\d+)", v.replace("我的未读", ""))
            stat = int(m.group(1)) if m else None
    OUT["board_unread_with_archived"] = stat

    # 清理测试数据 + 该布告可能的已读记录
    subprocess.run(
        ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo",
         "-d", "edu19", "-Atc",
         f"DELETE FROM edu_notice_read WHERE notice_id={nid};"
         f"DELETE FROM edu_notice WHERE id={nid};"],
        capture_output=True, text=True)
    OUT["cleaned_up"] = True

    # ---- 正常未读布告仍可打开（active=True 不受影响）----
    live = subprocess.run(
        ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo",
         "-d", "edu19", "-Atc",
         "SELECT id FROM edu_notice WHERE active ORDER BY id DESC LIMIT 1;"],
        capture_output=True, text=True).stdout.strip().splitlines()[0]
    r2 = page.goto(f"{BASE}/my/notice/{live}", wait_until="domcontentloaded")
    OUT["active_detail_ok"] = ("/my/notice/" in page.url
                               and r2.status == 200)

    ctx.close()
    b.close()

print(repr(OUT))
