#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ux-rework t4 Playwright 交互冒烟（下拉/弹窗/周导航/视图切换/常用区编辑）。

用法：python3 tests/smoke/ux_rework_playwright.py
覆盖：
- /my/home 常用应用编辑：编辑态/固定/取消固定/上移/下移 + localStorage 持久化
- 弹窗：修改头像 modal 开关
- /student/timetable：周/日切换、今天、第N周徽标、今天列高亮
- /my/calendar：月/周/列表切换、今天
- /timetable/bulk（admin）：下拉选择、周次范围/单双周表单 → 周矩阵预览

注意事项：
- 预置卡片数量以服务端为准（个别入口被 _hidden_cards 隐藏时预置数 < 4，
  断言用「固定 +1 / 取消固定 -1 / 无偏好=初始」的相对口径，数据无关）。
- 视图切换按钮含 FontAwesome 伪元素，勿用 get_by_role(exact) 判定，
  一律按 href 定位。

凭据（t81 收口）：只在 CRED **一处**声明，可用 EDU_<KEY>_LOGIN / EDU_<KEY>_PASSWORD
（KEY ∈ STU|ADMIN）覆盖；口令不出现在任何输出里（打印只出现登录名）。
顺带修两处"跑不起来/假绿"（t81 实测）：
  ① 选择器 form[action="/web/login"] 随 t4 登录页改版**失效**（现在的表单 action 是
     /login）⇒ 脚本在**第一次** login() 就 Playwright 超时崩掉（TimeoutError 30s），
     后面一行断言都没执行过；改为候选选择器逐个试 + 最后回车兜底。
  ② 旧凭据 admin/admin 在本库失效（admin 口令是 demo123）。
退出码：0 = 全部通过；1 = 有断言失败（含"某节因登录失败未验证"）；2 = 有角色没登上。
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8069"
ok = fail = 0
LOGIN_FAIL = []          # 登录失败的角色（该轮相关小节一律**未验证**）

# ---- 凭据：**唯一声明点**（t81；口令不打印）----
CRED = {
    "student": (os.environ.get("EDU_STU_LOGIN", "stu@local"),
                os.environ.get("EDU_STU_PASSWORD", "demo123")),
    # 本库 admin 的口令是 demo123；旧值 admin/admin 实测 AccessDenied
    "admin": (os.environ.get("EDU_ADMIN_LOGIN", "admin"),
              os.environ.get("EDU_ADMIN_PASSWORD", "demo123")),
}
ADMIN = CRED["admin"]

# 登录判据 = 会话 uid（本库 /login 对已登录用户也会渲染登录表单 ⇒ DOM 判据不可靠）。
SESSION_PROBE = """async () => {
  const r = await fetch('/web/session/get_session_info', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({jsonrpc:'2.0',method:'call',params:{}})});
  const j = await r.json();
  return (j.result || {}).uid || 0;
}"""


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS | %s | %s" % (name, detail))
    else:
        fail += 1
        print("FAIL | %s | %s" % (name, detail))


def login(page, role):
    """登录并**验证**：返回 uid（0 = 未登录，同时记进 LOGIN_FAIL）。"""
    user, pwd = CRED[role]
    page.goto(BASE + "/web/login")
    page.fill('input[name="login"]', user)
    page.fill('input[name="password"]', pwd)
    # 提交按钮的选择器要跟得上登录页改版：原写法写死 form[action="/web/login"]，
    # 而 t4 改版后表单 action 已是 /login ⇒ 实测 30s 超时（脚本死在第一行断言之前）。
    for sel in ('form.oe_login_form button[type="submit"]',
                'form[action="/login"] button[type="submit"]',
                'form[action="/web/login"] button[type="submit"]',
                'button[type="submit"]:visible'):
        try:
            page.click(sel, timeout=5000)
            break
        except Exception:
            continue
    else:
        page.press('input[name="password"]', "Enter")
    # 等导航**落定**：只等 load，不等 networkidle —— 后端 web client 的轮询会让
    # networkidle 永不触发（实测 t81：口令错时就在那行 TimeoutError 崩掉，
    # 把"未验证"变成 30 行堆栈 = 错误归因）。等待失败只告警，判据在下一段。
    try:
        page.wait_for_load_state("load", timeout=15000)
    except Exception as exc:
        print("[WARN] %s 登录后按 load 等页面落定超时：%s" % (role, type(exc).__name__))
    # 轮询会话 uid：跳转途中 evaluate 会因"执行上下文被销毁"抛错（实测）⇒ 计入重试；
    # 最终仍登不上就记 LOGIN_FAIL（该轮相关小节一律未验证），不静默吞掉。
    uid, errors = 0, 0
    for _ in range(16):
        try:
            uid = page.evaluate(SESSION_PROBE)
        except Exception:
            errors += 1
            uid = 0
        if uid:
            break
        page.wait_for_timeout(400)
    if not uid:
        LOGIN_FAIL.append(role)
        print("LOGIN-FAIL | %s(%s)：会话未建立（uid=0；evaluate 重试 %d 次）"
              "→ 相关小节**未验证**" % (role, user, errors))
    return uid


def goto_retry(page, path, tries=3):
    """导航 + 只对"被页面自己的跳转打断"重试（ERR_ABORTED / 超时），其它异常照抛。

    实测（t81）：登录**成功**后 webclient 还在做自己的跳转（→ /apps 等），紧接着的
    page.goto(...) 会被 Chrome 报 net::ERR_ABORTED —— 那是竞态，不是站点故障
    （同一 URL 用 curl 是 200 + <title>周期排课</title>）。不重试就会把竞态写成崩溃。
    只重试这两类：真实的产品/脚本问题（4xx 语义、选择器错）仍然照抛。
    """
    last = None
    for i in range(tries):
        try:
            return page.goto(BASE + path, timeout=45000)
        except Exception as exc:
            last = exc
            msg = str(exc)
            if "ERR_ABORTED" not in msg and "Timeout" not in msg:
                raise
            print("[WARN] goto %s 第 %d 次被中断（%s），重试"
                  % (path, i + 1, msg.splitlines()[0][:60]))
            page.wait_for_timeout(1000 * (i + 1))
    raise last


def fav_hrefs(page):
    return page.eval_on_selector_all(
        '[data-fav-grid] a[data-app-href]',
        "els => els.map(e => e.getAttribute('data-app-href'))")


with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(locale="zh-CN")
    page = ctx.new_page()

    # ---------------- 1. 学生首页：常用应用编辑 ----------------
    if not login(page, "student"):
        # 未登录还往下跑，只会把"停在登录页"读成一堆无关 FAIL（三节共 12 项都没验过）。
        # 这里显式给"未验证"结论并停止：退出码 2 = 没看成，既不是通过也不是发现缺陷。
        print("\nUNVERIFIED | 第 1-3 节（学生首页常用区 / 周课表 / 校历）本轮**未验证**："
              "%s(%s) 登录失败；口令可用 EDU_STU_PASSWORD 覆盖（口令不会被打印）。"
              % ("student", CRED["student"][0]))
        print("== 0 passed, 0 failed —— 本轮未验证（不是通过） ==")
        sys.exit(2)
    page.goto(BASE + "/my/home")
    check("首页常用应用区", page.locator(".ux-fav-category").count() == 1)
    hrefs0 = fav_hrefs(page)
    n0 = len(hrefs0)
    check("预置常用区非空", n0 >= 2, str(hrefs0))
    check("编辑按钮可见", page.locator(".ux-fav-edit-toggle").count() >= 1)

    # 编辑态 → 菜单常显
    page.click(".ux-fav-edit-toggle")
    page.wait_for_selector(".ux-fav-editing")
    check("编辑态开启", page.locator("[data-home-role].ux-fav-editing").count() == 1)
    check("编辑态菜单可见", page.locator(".ux-fav-menu").first.is_visible())

    # 固定一张分类卡（资源与学习 → 图书馆 library/media）
    lib_card = page.locator('.o_portal_index_card a[data-app-href="library/media"]')
    check("分类卡存在", lib_card.count() == 1)
    orig_cards = lib_card.locator(
        "xpath=ancestor::div[contains(@class,'o_portal_index_card')]")
    orig_cards.hover()
    orig_cards.locator('[data-fav-act="pin"]').click()
    page.wait_for_timeout(300)
    hrefs1 = fav_hrefs(page)
    check("固定后常用区 +1", len(hrefs1) == n0 + 1
          and "library/media" in hrefs1, str(hrefs1))

    # 持久化：刷新后仍在
    page.reload()
    page.wait_for_load_state("networkidle")
    hrefs2 = fav_hrefs(page)
    check("刷新后固定仍在", len(hrefs2) == n0 + 1
          and "library/media" in hrefs2, str(hrefs2))

    # 上移：把常用区最后一张上移 → 顺序变化并持久化
    page.click(".ux-fav-edit-toggle")
    page.wait_for_selector(".ux-fav-editing")
    before = fav_hrefs(page)
    last_card = page.locator('[data-fav-grid] .o_portal_index_card').last
    last_card.locator('[data-fav-act="up"]').click()
    page.wait_for_timeout(200)
    after = fav_hrefs(page)
    check("上移顺序变化", before != after and after[-1] == before[-2]
          and after[-2] == before[-1], "%s -> %s" % (before, after))
    page.reload()
    page.wait_for_load_state("networkidle")
    check("刷新后顺序保持", fav_hrefs(page) == after, str(fav_hrefs(page)))

    # 取消固定 → 回到预置数量 + 持久化
    page.click(".ux-fav-edit-toggle")
    page.wait_for_selector(".ux-fav-editing")
    page.locator('[data-fav-grid] a[data-app-href="library/media"]') \
        .locator("xpath=ancestor::div[contains(@class,'o_portal_index_card')]") \
        .locator('[data-fav-act="unpin"]').click()
    page.wait_for_timeout(200)
    check("取消固定回预置数", len(fav_hrefs(page)) == n0
          and "library/media" not in fav_hrefs(page), str(fav_hrefs(page)))
    page.reload()
    page.wait_for_load_state("networkidle")
    check("刷新后取消固定保持", len(fav_hrefs(page)) == n0
          and "library/media" not in fav_hrefs(page), str(fav_hrefs(page)))
    # 清空 localStorage 偏好，恢复默认渲染（避免影响后续截图对比）
    page.evaluate("localStorage.removeItem('home_favs_student')")
    page.reload()
    page.wait_for_load_state("networkidle")
    check("无偏好时回到服务端预置", fav_hrefs(page) == hrefs0, str(fav_hrefs(page)))

    # 弹窗：修改头像 modal（B11）
    page.click(".b11-user-btn")
    page.locator(".b11-user-menu a", has_text="修改头像").click()
    page.wait_for_timeout(400)
    check("修改头像弹窗打开", page.locator("#b11-avatar-modal").is_visible())
    page.locator("#b11-avatar-modal .btn-close").click()
    page.wait_for_timeout(300)
    check("弹窗关闭", not page.locator("#b11-avatar-modal .modal-content").is_visible())

    # ---------------- 2. 周课表：视图切换 / 今天 / 第N周 / 今天列 ----------------
    goto_retry(page, "/student/timetable")
    page.wait_for_load_state("networkidle")
    check("课表含第N周徽标", page.locator(".badge:has-text('第')").count() >= 1)
    check("今天按钮", page.locator('a[href*="view=week"]', has_text="今天").count() >= 1
          or page.locator("a:has-text('今天')").count() >= 1)
    check("今天列高亮", page.locator("th.ux-today-col").count() >= 1)
    page.locator('a[href*="view=day"]', has_text="日视图").first.click()
    page.wait_for_load_state("networkidle")
    check("日视图激活", page.locator('a[href*="view=day"]', has_text="日视图")
          .first.get_attribute("class").__contains__("btn-primary"))
    page.locator('a[href*="view=day"]', has_text="后一天").first.click()
    page.wait_for_load_state("networkidle")
    check("日视图翻页", "view=day&d=" in page.url, page.url)
    page.locator('a[href*="view=week"]', has_text="本周").first.click()
    page.wait_for_load_state("networkidle")
    check("回到周视图", "view=week" in page.url, page.url)
    page.locator('a[href*="view=week"]', has_text="今天").first.click()
    page.wait_for_load_state("networkidle")
    import re as _re
    _w = _re.search(r'[?&]w=(\d+)', page.url)
    check("今天定位(w=0)", "view=week" in page.url
          and (_w is None or _w.group(1) == "0"), page.url)

    # ---------------- 3. 校历三视图 ----------------
    goto_retry(page, "/my/calendar")
    page.wait_for_load_state("networkidle")
    check("校历月视图默认", page.locator(".oe-cal-mv").count() == 1)
    page.locator('a[href="/my/calendar?view=week"]').click()
    page.wait_for_load_state("networkidle")
    check("校历周视图", page.locator(".ux-cal-week").count() == 1)
    page.locator('a[href="/my/calendar?view=list"]').click()
    page.wait_for_load_state("networkidle")
    check("校历列表视图", page.locator(".ux-cal-list").count() == 1)
    page.locator('a[href="/my/calendar"]', has_text="月").first.click()
    page.wait_for_load_state("networkidle")
    check("回到月视图", page.locator(".oe-cal-mv").count() == 1)

    # ---------------- 4. 周期排课表单（admin：下拉 + 周次/单双周 → 矩阵预览） ----------------
    ctx2 = browser.new_context(locale="zh-CN")
    page2 = ctx2.new_page()
    if login(page2, "admin"):
        goto_retry(page2, "/timetable/bulk")
        page2.wait_for_load_state("networkidle")
        check("bulk 周次范围输入", page2.locator('input[name="week_ranges"]').count() == 1)
        check("bulk 单双周单选", page2.locator('input[name="parity"]').count() == 3)
        page2.select_option('select[name="batch_id"]', "8")
        page2.select_option('select[name="course_id"]', "18")
        page2.select_option('select[name="subject_id"]', "35")
        page2.select_option('select[name="faculty_id"]', "17")
        page2.select_option('select[name="timing_id"]', "10")
        page2.fill('input[name="start_date"]', "2026-06-29")
        page2.fill('input[name="end_date"]', "2026-07-12")
        page2.fill('input[name="week_ranges"]', "2-3")
        page2.check('input[name="weekday"][value="0"]')
        page2.click("button:has-text('预览将生成的课节')")
        page2.wait_for_load_state("networkidle")
        check("周矩阵预览渲染", page2.locator(".ux-week-matrix").count() == 1
              and page2.locator("th:has-text('第2周')").count() == 1)
        check("预览绿格", page2.locator("td.ux-mcell-ok").count() >= 2,
              "green=%d" % page2.locator("td.ux-mcell-ok").count())
        check("确认表单携带周次隐藏域",
              page2.locator('input[name="week_ranges"][type="hidden"]').count() == 1)
        page2.click("a:has-text('返回修改')")
        page2.wait_for_load_state("networkidle")
        check("返回表单保留", page2.locator('input[name="week_ranges"]').count() == 1)
    else:
        # 登录失败 ⇒ 这 8 项**一项都没验过**：显式记 FAIL（退出码见文件末尾），
        # 既不静默跳过，也不把"落在登录页"读成产品缺陷。
        check("§4 周期排课表单（admin，8 项）", False,
              "admin(%s) 登录失败 → 本节**未验证**，不得当作通过；"
              "口令可用 EDU_ADMIN_PASSWORD 覆盖" % ADMIN[0])

    browser.close()

print("\n== %d passed, %d failed ==" % (ok, fail))
if LOGIN_FAIL:
    # 退出码契约（t81）：1 = 有断言失败（含"该节未验证"）；
    # 2 = 登录就没成功、本轮**什么也没验证**（"没看成"≠"通过"）。
    print("UNVERIFIED | 登录失败的角色：%s —— 相关小节**未验证**（口令可用 "
          "EDU_<KEY>_PASSWORD 覆盖；口令不会被打印）" % ", ".join(LOGIN_FAIL))
sys.exit(1 if fail else 0)