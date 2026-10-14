#!/usr/bin/env python3
"""冒烟测试代理C - 浏览器层：admin 应用菜单回归（playwright, channel=chrome）
C6 登录落点 /openeducat/apps_menu；C7 卡片数与图标加载；
C8 抽样3卡进入真后台(/odoo/*+.o_web_client)；C9 直接访问/web 回 apps_menu 不落 discuss；
C10 收集 console error。截图 shots/smoke/C_apps_menu.png、C_web_direct.png
"""
import json, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8069"
OUT = Path(__file__).parent.parent.parent / "shots" / "smoke"
OUT.mkdir(parents=True, exist_ok=True)

console_errors = []
R = {}

def watch(page):
    def on_console(msg):
        if msg.type == "error":
            try:
                loc = msg.location or {}
                console_errors.append({
                    "text": msg.text[:300],
                    "url": (loc.get("url") or "")[-120:],
                    "line": loc.get("lineNumber"),
                })
            except Exception:
                console_errors.append({"text": str(msg)[:300]})
    page.on("console", on_console)
    return page

def run():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  locale="zh-CN", ignore_https_errors=True)
        page = watch(ctx.new_page())

        # ---- C6 登录 ----
        page.goto(BASE + "/web/login", timeout=45000, wait_until="load")
        page.wait_for_timeout(1500)
        if page.locator("#login").count() == 0:
            page.goto(BASE + "/web/login?redirect=%2Fweb%2Flogin", timeout=45000)
            page.wait_for_timeout(1000)
        page.fill("#login", "admin")
        page.fill("#password", "admin")
        page.locator(".oe_login_form button[type=submit]").first.click()
        try:
            page.wait_for_load_state("load", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(7000)
        url_after_login = page.url
        R["C6_url"] = url_after_login
        R["C6_pass"] = "/openeducat/apps_menu" in url_after_login

        # ---- C7 卡片与图标 ----
        cards = page.locator(".o_app")
        n = cards.count()
        loaded, fa_fallback, broken = 0, 0, []
        titles = []
        for i in range(n):
            c = cards.nth(i)
            t = (c.inner_text() or "").strip().split("\n")[0]
            titles.append(t)
            ok = False
            img = c.locator("img.o_app_icon")
            if img.count() > 0:
                nw = img.first.evaluate("el => el.naturalWidth")
                if nw and nw > 0:
                    ok = True
            if not ok and c.locator(".o_app_icon_fa").count() > 0:
                ok = True
                fa_fallback += 1
            if ok:
                loaded += 1
            else:
                broken.append(t or f"card#{i}")
        R["C7_count"] = n
        R["C7_loaded"] = loaded
        R["C7_fa_fallback"] = fa_fallback
        R["C7_broken"] = broken
        R["C7_titles"] = titles
        R["C7_pass"] = n >= 20 and loaded == n
        page.screenshot(path=str(OUT / "C_apps_menu.png"), full_page=False)

        # ---- C8 抽样点击 3 张卡 ----
        samples, clicked_names = [], []
        for want in ["学生", "时间表", "讨论"]:
            loc = page.locator(".o_app", has_text=want)
            name = want
            if loc.count() == 0:
                idx = len(samples)  # 兜底：按序取未点过的卡
                if idx >= n:
                    continue
                loc = cards.nth(idx)
                name = titles[idx] if idx < len(titles) else f"card#{idx}"
            else:
                loc = loc.first
            loc.click()
            try:
                page.wait_for_load_state("load", timeout=30000)
            except Exception:
                pass
            page.wait_for_timeout(8000)
            u = page.url
            has_client = page.locator(".o_web_client").count() > 0
            samples.append({"name": name, "url": u,
                            "is_odoo": "/odoo/" in u or u.startswith(BASE + "/odoo"),
                            "web_client": has_client})
            clicked_names.append(name)
            shot = OUT / f"C_card_{name}.png"
            try:
                page.screenshot(path=str(shot), full_page=False)
            except Exception:
                pass
            # 返回应用菜单再点下一张
            page.goto(BASE + "/openeducat/apps_menu", timeout=45000, wait_until="load")
            page.wait_for_timeout(3000)
        R["C8_samples"] = samples
        R["C8_pass"] = len(samples) == 3 and all(
            s["is_odoo"] and s["web_client"] for s in samples)

        # ---- C9 已登录直接访问 /web ----
        page.goto(BASE + "/web", timeout=45000, wait_until="load")
        try:
            page.wait_for_load_state("load", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(8000)
        url_web = page.url
        R["C9_url"] = url_web
        R["C9_is_apps"] = "/openeducat/apps_menu" in url_web
        R["C9_is_discuss"] = "/odoo/discuss" in url_web
        R["C9_pass"] = R["C9_is_apps"] and not R["C9_is_discuss"]
        page.screenshot(path=str(OUT / "C_web_direct.png"), full_page=False)

        browser.close()

ok = False
try:
    run()
    ok = True
except Exception as e:
    R["fatal"] = str(e)[:400]

R["C10_console_errors"] = console_errors
R["C10_pass"] = len(console_errors) == 0
R["_ran_ok"] = ok
print(json.dumps(R, ensure_ascii=False, indent=1))
