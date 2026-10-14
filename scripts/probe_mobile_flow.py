#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手机端可用性探针：**375px 下核心页面还能不能用**（第 95 轮立）。

第 58 轮的 `probe_mobile_layout.py` 只查**横向溢出** ——「不溢出」不等于「用得了」。
本轮以手机视口真走一遍学生核心动作后，把能机械化的部分固化：
底栏在不在、侧栏有没有正确收起、主操作点不点得到。

判据（只报硬信号；**不判美观、不判点击目标大小** —— 第 58 轮明确决定过不判后者）：
  ① 底部 tabbar 可见且 ≥3 项；② 桌面侧栏必须不可见（模板 `d-none d-lg-block`）；
  ③ 横向不溢出（同第 58 轮口径）；④ 学生核心页主操作可见且未退化（< 8px 视为塌了）。

用法：probe_mobile_flow.py     退出码：0=无问题 ｜ 1=有问题 ｜ 2=ENV
"""
import sys

BASE = "http://127.0.0.1:8069"
ROLES = [("student", "stu@local"), ("parent", "parent@local"),
         ("faculty", "faculty@local"), ("backoffice", "backoffice@local")]
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
CORE = [
    ("/my/home", "首页", "a[href*='/my/calendar']"),
    ("/student/assignment/details", "作业列表", "a[href*='submited/assignment/list']"),
    ("/submited/assignment/list/21", "提交作业", "form[action$='/save'] button[type=submit]"),
    ("/my/fees", "费用账单", "a[href*='reimburse/apply']"),
    ("/my/messages", "私信", "a[href*='/my/messages/']"),
]


def main():
    import sys as _sys
    selftest = "--selftest" in _sys.argv
    if selftest:
        # 2026-10-04（第 102 轮）加：此前红证是拿临时副本做的（把首页选择器改成不存在的路径），
        #   下一个人复现不了。固化成开关：把首页那条主操作指向不存在的元素 ⇒ 必须报。
        CORE[:] = [("/my/home", "首页", "a[href*='/definitely-not-here']")]
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("ENV：playwright 不可用 %s" % e)
        return 2
    bad = []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            for role, user in ROLES:
                ctx = b.new_context(viewport={"width": 375, "height": 812},
                                    locale="zh-CN", is_mobile=True, has_touch=True,
                                    user_agent=UA)
                pg = ctx.new_page()
                pg.goto(BASE + "/web/login", timeout=45000)
                pg.wait_for_selector("form.oe_login_form", timeout=30000)
                pg.fill("form.oe_login_form input[name=login]", user)
                pg.fill("form.oe_login_form input[name=password]", "demo123")
                pg.click("form.oe_login_form button[type=submit]", timeout=30000)
                pg.wait_for_load_state("load", timeout=45000)
                if "/web/login" in pg.url:
                    print("ENV：%s 登录失败 —— 这不是通过" % role)
                    return 2
                pg.goto(BASE + "/my/home", timeout=45000)
                pg.wait_for_timeout(1500)
                tabs = pg.eval_on_selector_all(".b11-tabbar a, .b11-tabbar button",
                                                "els => els.filter(e => e.offsetParent !== null).length")
                if tabs < 3:
                    bad.append("%s 底部导航只有 %d 项（手机上没导航）" % (role, tabs))
                side = pg.query_selector("#b11-side")
                if side and side.is_visible():
                    bad.append("%s 桌面侧栏在手机上仍可见（应为 d-none d-lg-block）" % role)
                ov = pg.evaluate("() => ({sw: document.documentElement.scrollWidth, "
                                   "cw: document.documentElement.clientWidth})")
                if ov["sw"] > ov["cw"] + 2:
                    bad.append("%s 横向溢出 %s > %s" % (role, ov["sw"], ov["cw"]))
                if role != "student":
                    ctx.close()
                    continue
                for path, label, sel in CORE:
                    pg.goto(BASE + path, timeout=45000)
                    pg.wait_for_timeout(1100)
                    # ⚠ 必须找**可见的**那一个：同一路由在隐藏的桌面侧栏里也有一份，
                    #   `query_selector` 返回第一个匹配 ⇒ 会拿到不可见的那个，误判成「主操作不可见」
                    #   （第一版就这么报了一条假阳性：首页的「校历」在侧栏里是 d-none 的）。
                    box = None
                    for cand in pg.query_selector_all(sel):
                        if cand.is_visible():
                            box = cand.bounding_box()
                            break
                    if box is None:
                        bad.append("学生「%s」主操作在手机上不可见（%s）" % (label, path))
                        continue
                    if box and (box["width"] < 8 or box["height"] < 8):
                        bad.append("学生「%s」主操作尺寸退化 %dx%d"
                                   % (label, int(box["width"]), int(box["height"])))
                    print("  ✅ %-10s 主操作 %dx%d"
                          % (label, int(box["width"]) if box else 0,
                             int(box["height"]) if box else 0))
                ctx.close()
            b.close()
    except Exception as e:
        print("ENV：%s" % str(e)[:150])
        return 2
    for line in bad:
        print("  ⛔ " + line)
    if selftest:
        caught = any("主操作在手机上不可见" in x for x in bad)
        print("  自证：把首页主操作指向不存在的元素，%s"
              % ("被抓到（对）" if caught else "**没抓到 —— 量具坏了**"))
        return 0 if caught else 1
    if bad:
        print("结论：FAIL（%d 处手机端问题）" % len(bad))
        return 1
    print("结论：OK（四角色手机端底栏/侧栏/溢出正常；学生 5 个核心页主操作可用）")
    return 0


if __name__ == "__main__":
    sys.exit(main())