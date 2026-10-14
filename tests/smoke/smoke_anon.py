#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""匿名公开面冒烟（项1-7）：首页品牌 / 校园岗位列表 / 详情投递表单 /
真实投递入库(psql) / honeypot 反机器人 / alumni 卡片页 / 未登录跳转登录。

运行：python3 tests/smoke/smoke_anon.py
截图：shots/local/smoke_01..07*.png
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_common import (BASE, Results, http_get, new_context, psql_count,
                          safe_text, shot, URL_RE, goto)

R = Results("anon")


def run():
    from playwright.sync_api import sync_playwright

    # ---- 1 GET / 200 且含「永约学坊」 ----
    st, url, html = http_get(BASE + "/")
    R.add(1, "GET / 返回200且含「永约学坊」",
          st == 200 and "永约学坊" in html,
          f"status={st}, brand={'永约学坊' in html}")

    with sync_playwright() as pw:
        browser, ctx = new_context(pw)
        page = ctx.new_page()

        # ---- 2 /campus/jobs ≥2 张岗位卡 ----
        goto(page, BASE + "/campus/jobs")
        page.wait_for_timeout(1200)
        html_jobs = safe_text(page)
        job_ids = sorted(set(URL_RE.findall(html_jobs)))
        has_t1 = "神学课程助教" in html_jobs
        has_t2 = "图书馆兼职管理员" in html_jobs
        ok2 = len(job_ids) >= 2 and has_t1 and has_t2
        shot(page, "02_campus_jobs")
        R.add(2, "/campus/jobs 列出≥2张岗位卡(神学课程助教/图书馆兼职管理员)",
              ok2, f"card_ids={job_ids}, 神学课程助教={has_t1}, "
                   f"图书馆兼职管理员={has_t2}")

        # ---- 3 详情页含投递表单 ----
        goto(page, BASE + "/campus/jobs/1")
        page.wait_for_timeout(1000)
        form = page.locator("form[action*='/apply']").first
        n_form = page.locator("form[action*='/apply']").count()
        shot(page, "03_job_detail_form")
        R.add(3, "/campus/jobs/1 详情页含 form[action*='/apply']",
              n_form >= 1 and form.is_visible(),
              f"apply_forms={n_form}")

        # ---- 4 正常投递：申请已提交 + edu_job_application +1 ----
        before = psql_count("edu_job_application")
        goto(page, BASE + "/campus/jobs/1")
        form = page.locator("form[action*='/apply']").first
        form.locator("input[name='name']").fill("冒烟测试员")
        form.locator("input[name='phone']").fill("13900001111")
        form.locator("select[name='education']").select_option(label="本科")
        form.locator("button[type='submit']").click()
        try:
            page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        after_url = page.url
        body4 = safe_text(page)
        submitted = "申请已提交" in body4 and after_url.rstrip("/").endswith("/sent")
        after = psql_count("edu_job_application")
        shot(page, "04_apply_sent")
        R.add(4, "表单提交→「申请已提交」且 edu_job_application 行数+1",
              submitted and after == before + 1,
              f"url={after_url}, rows {before}->{after}")

        # ---- 5 honeypot 反机器人：行数不变 ----
        before5 = psql_count("edu_job_application")
        goto(page, BASE + "/campus/jobs/1")
        form = page.locator("form[action*='/apply']").first
        form.locator("input[name='name']").fill("冒烟测试员")
        form.locator("input[name='phone']").fill("13900001111")
        form.locator("select[name='education']").select_option(label="本科")
        # 隐藏蜜罐字段（d-none，仍可 fill）
        form.locator("input[name='website_url']").evaluate(
            "el => { el.classList.remove('d-none'); }")
        form.locator("input[name='website_url']").fill("http://spam.example.com")
        form.locator("button[type='submit']").click()
        try:
            page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        after5_url = page.url
        after5 = psql_count("edu_job_application")
        rejected = not after5_url.rstrip("/").endswith("/sent")
        shot(page, "05_honeypot_rejected")
        R.add(5, "honeypot(website_url=spam) 提交后 edu_job_application 行数不变",
              rejected and after5 == before5,
              f"url={after5_url}, rows {before5}->{after5}")

        browser.close()

    # ---- 6 /alumni/job/card 200 ----
    st6, _, _ = http_get(BASE + "/alumni/job/card")
    R.add(6, "/alumni/job/card 返回200", st6 == 200, f"status={st6}")

    # ---- 7 未登录访问 /my/home → 重定向登录页 ----
    st7, final_url, _ = http_get(BASE + "/my/home")
    redirected_login = ("/web/login" in str(final_url)) or (
        st7 in (301, 302, 303) and "/web/login" in str(http_get.__doc__ or ""))
    # 再用无 cookie 浏览器确认最终落点
    with sync_playwright() as pw:
        browser, ctx = new_context(pw)
        page = ctx.new_page()
        goto(page, BASE + "/my/home")
        page.wait_for_timeout(1200)
        browser_url = page.url
        # t90：v3 的合法行为是重定向到**友好别名 /login?redirect=…**（终态 200）；
        # 旧断言只认 /web/login → 属「脚本陈旧」而非产品红。两种形态都接受。
        on_login = (("/login" in browser_url and "redirect=" in browser_url)
                    or "/web/login" in browser_url)
        shot(page, "07_my_home_redirect_login")
        browser.close()
    R.add(7, "未登录直接访问 /my/home → 落到登录页（/login?redirect=… 或 /web/login）",
          on_login and (("/login" in str(final_url)) or ("/web/login" in str(final_url))),
          f"http_final={final_url}, status={st7}, browser_url={browser_url}")


if __name__ == "__main__":
    ok = False
    try:
        run()
        ok = True
    except Exception as e:
        import traceback
        traceback.print_exc()
        R.add("FATAL", "脚本异常中断", False, repr(e)[:400])
    finally:
        R.save()
    # t86 退出码契约：原为 sys.exit(0 if ok else 0) —— 恒 0 的假绿
    # （ok 只表示没抛异常，不表示没有 FAIL）。有 FAIL 或异常中断 ⇒ 非零。
    _failed = sum(1 for it in R.items if not it.get('pass'))
    sys.exit(0 if (ok and _failed == 0) else 1)
