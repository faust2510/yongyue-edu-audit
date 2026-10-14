#!/usr/bin/env python3
"""t2 真机抽查（auditor）：B5 未读引擎 + A5 搜索 + A6/A7 后台入口 + 清扫残留探查。
输出 JSON 结果到 stdout，截图存 shots/v2_review/。

凭据（t81 收口）：只在 CRED **一处**声明，可用
EDU_<KEY>_LOGIN / EDU_<KEY>_PASSWORD（KEY ∈ FAC|STU|ADMIN）覆盖；
口令不出现在任何输出里（打印/JSON 里只出现登录名）。
退出码（t81 补全）：0 = 三个小节都已登录并采集；2 = 有**未验证小节**（登录失败）
                      ——"没看成"≠"采集完成"（旧版无论登录成败都 exit 0）。
"""
import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8069"
SHOTS = Path(__file__).parent.parent / "shots" / "v2_review"
SHOTS.mkdir(parents=True, exist_ok=True)

R = {"teacher_flow": {}, "student_cards": {}, "search": {},
     "admin_backend": {}, "errors": []}
UNVERIFIED = []          # 登录失败 ⇒ 该小节未验证（进 JSON + 进退出码）

# ---- 凭据：**唯一声明点**（t81）----
# 口令只在这里出现，且**不打印**（打印只出现登录名）。admin 用 demo123：旧值
# ('admin','admin') 在本库是失效凭据 —— 而旧版据此判"URL 没有 /web/login = 成功"，
# 登录失败只是往 R['errors'] 里加一行，脚本照样 exit 0（JSON 看着像"采集完成"）。
CRED = {
    "faculty": (os.environ.get("EDU_FAC_LOGIN", "faculty@local"),
                os.environ.get("EDU_FAC_PASSWORD", "demo123")),
    "student": (os.environ.get("EDU_STU_LOGIN", "stu@local"),
                os.environ.get("EDU_STU_PASSWORD", "demo123")),
    "admin": (os.environ.get("EDU_ADMIN_LOGIN", "admin"),
              os.environ.get("EDU_ADMIN_PASSWORD", "demo123")),
}

# 判据是**会话 uid**，不是 URL 前缀：本库 /login 是友好别名，登录失败时 URL 恰好
# 不含 /web/login（旧判据靠巧合成立），DOM/URL 判据两个方向都可能读错（t81）。
SESSION_PROBE = """async () => {
  const r = await fetch('/web/session/get_session_info', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({jsonrpc:'2.0',method:'call',params:{}})});
  const j = await r.json();
  return (j.result || {}).uid || 0;
}"""


def login(page, role):
    """登录并**验证**；返回 uid（0 = 未登录 ⇒ 调用方必须显式登记未验证）。"""
    user, pwd = CRED[role]
    page.goto(BASE + "/web/login", wait_until="domcontentloaded")
    form = page.locator("form.oe_login_form").first
    form.locator("input[name=login]").fill(user)
    form.locator("input[name=password]").fill(pwd)
    form.locator("button[type=submit]").first.click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1500)
    return page.evaluate(SESSION_PROBE)


def bell_value(page):
    for sel in (".oe-mhead-badge", ".oe-hero-bell-badge"):
        loc = page.locator(sel).first
        if loc.count():
            txt = (loc.inner_text() or "").strip()
            if txt:
                return int(re.sub(r"\D", "", txt) or 0)
    return None


def board_unread_stat(page):
    vals = page.locator(".oe-statbox").all_inner_texts()
    for v in vals:
        if "我的未读" in v:
            m = re.search(r"(\d+)", v.replace("我的未读", ""))
            if m:
                return int(m.group(1))
    return None


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ---------- A. 教师布告未读闭环 ----------
        ctx = browser.new_context()
        page = ctx.new_page()
        ok = login(page, "faculty")
        R["teacher_flow"]["login"] = bool(ok)
        if not ok:
            R["teacher_flow"]["verified"] = False
            UNVERIFIED.append("teacher_flow")
            R["errors"].append(
                "faculty 登录失败（login=%s）→ teacher_flow **未验证**；"
                "口令可用 EDU_FAC_PASSWORD 覆盖" % CRED["faculty"][0])
        else:
            page.goto(BASE + "/my/home", wait_until="domcontentloaded")
            page.wait_for_timeout(800)
            bell0 = bell_value(page)
            page.goto(BASE + "/my/notice_board/notice",
                      wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            stat0 = board_unread_stat(page)
            unread_badges = page.locator("a .badge", has_text="未读").count()
            cards = page.locator("a[href^='/my/notice/']").count()
            R["teacher_flow"].update({
                "bell_before": bell0, "board_unread_before": stat0,
                "unread_badges_before": unread_badges,
                "notice_links": cards})
            # 点开第一条布告（阅后即记）
            if cards:
                first = page.locator("a[href^='/my/notice/']").first
                name = first.inner_text()[:40]
                first.click()
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(600)
                detail_url = page.url
                on_detail = "/my/notice/" in detail_url
                page.screenshot(path=str(SHOTS / "t_notice_detail.png"),
                                full_page=True)
                page.goto(BASE + "/my/home", wait_until="domcontentloaded")
                page.wait_for_timeout(800)
                bell1 = bell_value(page)
                page.goto(BASE + "/my/notice_board/notice",
                          wait_until="domcontentloaded")
                page.wait_for_timeout(500)
                stat1 = board_unread_stat(page)
                R["teacher_flow"].update({
                    "clicked_card": name.strip().replace("\n", " "),
                    "on_detail_page": on_detail,
                    "bell_after": bell1, "board_unread_after": stat1,
                    "bell_decremented": (
                        bell0 is not None and bell1 is not None
                        and bell1 < bell0),
                    "stat_decremented": (
                        stat0 is not None and stat1 is not None
                        and stat1 < stat0)})
        ctx.close()

        # ---------- B. 学生首页残留卡探查 ----------
        ctx = browser.new_context()
        page = ctx.new_page()
        ok = login(page, "student")
        R["student_cards"]["login"] = bool(ok)
        if not ok:
            R["student_cards"]["verified"] = False
            R["search"]["verified"] = False
            UNVERIFIED.extend(["student_cards", "search"])
            R["errors"].append(
                "student 登录失败（login=%s）→ student_cards / search **未验证**；"
                "口令可用 EDU_STU_PASSWORD 覆盖" % CRED["student"][0])
        else:
            page.goto(BASE + "/my/home", wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            page.screenshot(path=str(SHOTS / "s_student_home.png"),
                            full_page=True)
            cards_info = page.evaluate("""() => {
                const out = [];
                document.querySelectorAll('.o_portal_index_card')
                  .forEach(c => {
                    const a = c.querySelector('a');
                    out.push({title: (c.textContent||'').trim().slice(0,30),
                              href: a ? a.getAttribute('href') : ''});
                  });
                return out;
            }""")
            bad = [c for c in cards_info if c["href"] and (
                "/openeducat-omr" in c["href"]
                or c.get("title") in ("my/invoices", "my/orders",
                                      "my/payment_method", "my/dms",
                                      "openeducat-omr/exam-result"))]
            R["student_cards"] = {
                "login": True, "card_total": len(cards_info),
                "cards": cards_info, "suspect_dangling": bad}
            # 一键全读按钮存在性（学生视角）
            page.goto(BASE + "/my/notice_board/notice",
                      wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            R["student_cards"]["all_read_btn"] = page.locator(
                "form[action='/my/notice_board/all_read'] button").count()

            # ---------- C. 统一搜索 ----------
            def search(q):
                page.goto(BASE + "/my/search?q=" + q,
                          wait_until="domcontentloaded")
                page.wait_for_timeout(500)
                groups = page.locator("h5.text-primary").all_inner_texts()
                items = page.locator(
                    ".list-group-item").all_inner_texts()
                return {"groups": [g.strip().replace("\n", " ")
                                   for g in groups],
                        "items": [i.strip() for i in items][:12]}
            R["search"]["q_assignment"] = search("%E5%A4%A9%E8%B7%AF%E5%8E%86%E7%A8%8B")   # 天路历程
            R["search"]["q_subject"] = search("%E5%B0%8F%E8%A6%81%E7%90%86%E9%97%AE%E7%AD%94")  # 小要理问答
            R["search"]["q_notice"] = search("%E5%86%92%E7%83%9F")    # 冒烟
            # 科目链接可用性
            resp = page.goto(BASE + "/my/courses/35",
                             wait_until="domcontentloaded")
            R["search"]["course_link_status"] = resp.status
            ctx.close()

        # ---------- D. 管理员后台：图标 + 应用面板 chip ----------
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        ok = login(page, "admin")
        R["admin_backend"]["login"] = bool(ok)
        if not ok:
            R["admin_backend"]["verified"] = False
            UNVERIFIED.append("admin_backend")
            R["errors"].append(
                "admin 登录失败（login=%s）→ admin_backend **未验证**；"
                "口令可用 EDU_ADMIN_PASSWORD 覆盖" % CRED["admin"][0])
        else:
            page.goto(BASE + "/openeducat/apps_menu",
                      wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            page.screenshot(path=str(SHOTS / "a_apps_menu.png"),
                            full_page=True)
            icon_imgs = page.evaluate("""() =>
              Array.from(document.querySelectorAll('.o_app img, a.o_app'))
                .map(e => e.getAttribute('src') || e.dataset.webIcon || '')
                .filter(s => s.includes('menu/') || s.includes('web_icon'))
                .slice(0, 20)""")
            apps = page.locator("a.o_app").count()
            R["admin_backend"].update({
                "apps_count": apps, "custom_icon_samples": icon_imgs[:10]})
            # 进入一个后台动作页验证 chip
            page.goto(BASE + "/web#action=", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            first_app = page.locator("a.o_app").first
            if first_app.count():
                first_app.click()
                page.wait_for_timeout(3500)
            chip = page.locator("#yy-apps-chip").count()
            navbar = page.locator(".o_main_navbar").count()
            R["admin_backend"].update({
                "navbar_present": bool(navbar),
                "apps_chip_present": bool(chip)})
            page.screenshot(path=str(SHOTS / "a_action_chip.png"),
                            full_page=False)
        ctx.close()
        browser.close()


run()
R["unverified"] = UNVERIFIED
print(json.dumps(R, ensure_ascii=False, indent=1))
if UNVERIFIED:
    # 旧版到这里仍然 exit 0 —— 登录失败的小节在 JSON 里只是 errors 多一行，
    # 读 JSON 的人很容易把它当"采集完成"。显式非 0 + 点名未验证小节。
    print("\nUNVERIFIED | 未验证小节：%s —— 登录失败的小节**不得**当作采集完成；"
          "口令可用 EDU_<KEY>_PASSWORD 覆盖（口令不会被打印）。" % ", ".join(UNVERIFIED),
          file=sys.stderr)
    sys.exit(2)
sys.exit(0)
