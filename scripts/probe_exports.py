#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出/下载探针：**每个「导出」按钮都要真的给出文件**。

**为什么立它**（2026-10-04 第 90 轮）：
  接着「逐条验 UI 上写着的承诺」往下走 —— 页面上那些「导出 CSV」「下载报告」按钮，
  此前只被 `check_ui_surface` 登记成 endpoint（「路由存在」），**从没人验过点下去真的出文件**。
  导出坏了是最典型的「按了没反应」：用户不会报错，只会以为系统卡了。

判据（三条硬信号）：
  ① HTTP ≥ 400；
  ② **返回的是 HTML**（`text/html`）—— 导出接口返回网页 = 渲染了错误页/被弹回，
     这是最关键的一条：状态码可能还是 200；
  ③ 体积过小（< 20 字节）—— 空文件。

用法：probe_exports.py [--selftest]
退出码：0=全部出文件 ｜ 1=有坏的 ｜ 2=ENV
"""
import argparse
import sys

BASE = "http://127.0.0.1:8069"
LOGINS = {"student": ("stu@local", "demo123"),
          "faculty": ("faculty@local", "demo123"),
          "backoffice": ("backoffice@local", "demo123")}

# (路径, 角色, 期望的内容类型关键词)
EXPORTS = [
    ("/my/fees/export", "student", ("csv", "text")),
    ("/my/checkins/export", "student", ("csv", "text")),
    ("/student/attendance/export", "student", ("csv", "text")),
    ("/my/time_off/export", "student", ("csv", "text")),
    ("/my/grievances/export", "student", ("csv", "text")),
    ("/grade-book/report/download", "student", ("pdf", "csv", "octet")),
    ("/downloads/mine/export", "student", ("csv", "text")),
    ("/my/certificate/download/3", "student", ("pdf",)),
    ("/checkins/stats/export", "faculty", ("csv", "text")),
    ("/ledger/export", "backoffice", ("csv", "text")),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("ENV：playwright 不可用 %s" % e)
        return 2
    if a.selftest:
        # 2026-10-04（第 101 轮）：**这个 --selftest 原先只是声明了、根本没实现** ——
        #   传了它照样跑正常检查（第 100 轮审计 --list 时发现的同一类问题）。
        #   现在让它真的自证：拿一个**普通页面**当「导出」来查，必须被判红。
        EXPORTS[:] = [("/my/home", "student", ("csv", "text"))]
    bad, ok = [], 0
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            sessions = {}
            for path, role, wants in EXPORTS:
                if role not in sessions:
                    ctx = b.new_context(viewport={"width": 1440, "height": 1000},
                                        locale="zh-CN")
                    pg = ctx.new_page()
                    pg.goto(BASE + "/web/login", timeout=45000)
                    pg.wait_for_selector("form.oe_login_form", timeout=30000)
                    u, pw = LOGINS[role]
                    pg.fill("form.oe_login_form input[name=login]", u)
                    pg.fill("form.oe_login_form input[name=password]", pw)
                    pg.click("form.oe_login_form button[type=submit]", timeout=30000)
                    pg.wait_for_load_state("load", timeout=45000)
                    sessions[role] = ctx
                req = sessions[role].request
                try:
                    r = req.get(BASE + path, timeout=60000)
                    ctype = (r.headers.get("content-type") or "").lower()
                    body = r.body() or b""
                    why = ""
                    if r.status >= 400:
                        why = "HTTP %d" % r.status
                    elif "text/html" in ctype:
                        why = "返回的是 HTML（不是文件）"
                    elif len(body) < 20:
                        why = "体积 %d 字节（空文件）" % len(body)
                    elif wants and not any(w in ctype for w in wants):
                        why = "内容类型 %s 不是期望的 %s" % (ctype[:30], "/".join(wants))
                    if why:
                        bad.append("%-34s [%-10s] %s" % (path, role, why))
                    else:
                        ok += 1
                        print("  ✅ %-34s [%-10s] %s  %d 字节"
                              % (path, role, ctype.split(";")[0][:26], len(body)))
                except Exception as e:
                    bad.append("%-34s [%-10s] 请求失败 %s" % (path, role, str(e)[:40]))
            b.close()
    except Exception as e:
        print("ENV：%s" % str(e)[:150])
        return 2
    for line in bad:
        print("  ⛔ " + line)
    if a.selftest:
        caught = any("HTML" in x for x in bad)
        print("  自证：拿普通页面冒充导出，%s" % ("被抓到（对）" if caught else "**没抓到 —— 量具坏了**"))
        return 0 if caught else 1
    if bad:
        print("结论：FAIL（%d 个导出坏 / 共查 %d 个）" % (len(bad), len(EXPORTS)))
        return 1
    print("结论：OK（%d 个导出全部给出文件）" % ok)
    return 0


if __name__ == "__main__":
    sys.exit(main())