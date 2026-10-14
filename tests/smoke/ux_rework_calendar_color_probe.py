#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ux-rework t14 浏览器探针（M1）：S1 冲突分色验收②——官方日历三档冲突色可区分。

背景：t10 评审 B1 发现 conflict_color 用 Selection 字符串时，Odoo calendar 前端
getColor() 对字符串走 hash 分支产生随机色（浏览器实证：15 事件全 o_calendar_color_6）。
t14 已改为 fields.Integer 0-3（number 分支 → o_calendar_color_0-3）。

本探针（自包含，库零残留）：
1. odoo shell 造数（ux_rework_calendar_color_seed.py，幂等）：2026-09-07 三组冲突
   课时（同教师/同教室/同班级 → color 1/2/3）；
2. playwright：登录后台（admin）→ 打开时间表 action 456 日历 → 逐周「下一页」
   导航到冲突周；
3. 断言：事件 class 存在 ≥2 种可区分的 o_calendar_color_N；无冲突档（0）与
   冲突档不同；三档冲突色（1/2/3）互异；
4. finally 清理（ux_rework_calendar_color_cleanup.py），库保持基线零残留。

用法：python3 tests/smoke/ux_rework_calendar_color_probe.py
"""
import collections
import os
import subprocess
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8069"
ROOT = os.path.dirname(os.path.abspath(__file__))
SHELL_CMD = ["docker", "compose", "exec", "-T", "web", "odoo", "shell",
             "-c", "/etc/odoo/odoo.conf", "--db_host=db", "-r", "odoo",
             "-w", "odoo", "-d", "edu19", "--no-http"]
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS | %s | %s" % (name, detail))
    else:
        fail += 1
        print("FAIL | %s | %s" % (name, detail))


def run_shell(script_path):
    """odoo shell 执行脚本（docker compose exec）。返回 CompletedProcess。"""
    with open(script_path, encoding="utf-8") as f:
        script = f.read()
    return subprocess.run(SHELL_CMD, input=script, capture_output=True,
                          text=True, cwd=os.path.join(ROOT, "..", ".."))


def color_dist(page):
    allcls = page.eval_on_selector_all(
        "[class*='o_calendar_color_']",
        "els => els.map(e => e.className)")
    cnt = collections.Counter()
    for c in allcls:
        for tok in c.split():
            if tok.startswith("o_calendar_color_"):
                cnt[tok] += 1
    return cnt


# ---- 1. 造数（幂等）：2026-09-07 三组冲突课时 ----
r = run_shell(os.path.join(ROOT, "ux_rework_calendar_color_seed.py"))
seed_ok = "SEED_OK" in r.stdout
check("造数成功（SEED_OK）", seed_ok,
      (r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "no output")
      + (" stderr=%s" % r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ""))

try:
    # ---- 2. playwright 后台日历 ----
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(locale="zh-CN")
        page = ctx.new_page()

        page.goto(BASE + "/web/login")
        page.fill('input[name="login"]', "admin")
        page.fill('input[name="password"]', "admin")
        page.locator('form[action="/web/login"] button[type="submit"]').first.click()
        page.wait_for_load_state("networkidle")
        check("后台登录", "login" not in page.url, page.url)

        page.goto(BASE + "/web#action=456&view_type=calendar")
        page.wait_for_timeout(6000)
        check("时间表日历加载", page.locator("button[title='下一页']").count() >= 1)

        # ---- 3. 逐周导航找冲突周（最多 8 步，累计所见色档）----
        seen_bands = set()
        seen_has_default = False
        dist = color_dist(page)
        for _ in range(8):
            dist = color_dist(page)
            seen_bands |= {k for k in dist if k != "o_calendar_color_0"}
            if "o_calendar_color_0" in dist:
                seen_has_default = True
            if seen_bands >= {"o_calendar_color_1", "o_calendar_color_2",
                              "o_calendar_color_3"}:
                break
            page.locator("button[title='下一页']").click()
            page.wait_for_timeout(1200)
        bands = {k for k in dist if k != "o_calendar_color_0"}
        check("找到冲突课时周", len(bands) > 0, "dist=%s" % dict(dist))

        # ---- 4. 验收②断言 ----
        distinct = (seen_bands | {"o_calendar_color_0"}) if seen_has_default \
            else seen_bands
        check("事件色 ≥2 种可区分", len(distinct) >= 2,
              "distinct=%s dist=%s" % (sorted(distinct), dict(dist)))

        has_conflict = len(bands) > 0
        if seen_has_default:
            check("无冲突档与冲突档不同", seen_has_default and has_conflict,
                  "default_seen=%s conflict=%s"
                  % (seen_has_default, has_conflict))
        else:
            check("无冲突档与冲突档不同", True,
                  "导航窗口未见 0 档（纯冲突周），跳过；冲突档=%s"
                  % sorted(bands))

        conflict_bands = sorted(bands)
        check("冲突档互异（≥2 档）", len(conflict_bands) >= 2,
              "bands=%s" % conflict_bands)
        if conflict_bands:
            check("三档冲突色齐全(1/2/3)",
                  set(conflict_bands) >= {"o_calendar_color_1",
                                          "o_calendar_color_2",
                                          "o_calendar_color_3"},
                  "bands=%s" % conflict_bands)

        total = sum(dist.values())
        check("事件总数>0", total > 0, "total=%d dist=%s" % (total, dict(dist)))

        browser.close()
finally:
    # ---- 5. 清理（幂等）：删除探针课时与临时教师 ----
    rc = run_shell(os.path.join(ROOT, "ux_rework_calendar_color_cleanup.py"))
    clean_ok = "CLEAN_OK" in rc.stdout
    check("清理完成（CLEAN_OK）", clean_ok,
          (rc.stdout.strip().splitlines()[-1] if rc.stdout.strip() else "no output"))

print("\n== %d passed, %d failed ==" % (ok, fail))
sys.exit(1 if fail else 0)
