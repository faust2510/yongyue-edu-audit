# -*- coding: utf-8 -*-
# 周期排课页的「乱」量化基线 —— 改完之后要拿同一把尺子复测
from playwright.sync_api import sync_playwright
import re
BASE = "http://127.0.0.1:8069"
JARGON = ["错开口径", "合班批", "循环方式", "周次范围", "口径"]
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
    pg = ctx.new_page()
    pg.goto(BASE + "/web/login", timeout=45000)
    pg.wait_for_selector("form.oe_login_form", timeout=30000)
    pg.fill("form.oe_login_form input[name=login]", "backoffice@local")
    pg.fill("form.oe_login_form input[name=password]", "demo123")
    pg.click("form.oe_login_form button[type=submit]", timeout=30000)
    pg.wait_for_load_state("load", timeout=45000)
    pg.goto(BASE + "/timetable/bulk", timeout=45000)
    pg.wait_for_timeout(1800)
    m = pg.evaluate("""() => {
      const q = s => document.querySelectorAll(s).length;
      const txt = (document.body.innerText||"").replace(/\\s+/g," ");
      // 主操作距页面顶部
      const btn = [...document.querySelectorAll("button, .btn")].find(e => (e.textContent||"").indexOf("预览") >= 0);
      const r = btn ? btn.getBoundingClientRect() : null;
      const scrollTop = window.scrollY;
      return {
        pageH: document.documentElement.scrollHeight,
        // ⚠ 2026-10-04 修量具：原先 `q(".form-text, .text-muted, small")` 会把**同一个元素算两次**
        //   （很多小灰字同时带 .form-text 与 .text-muted）⇒ 我数出 79，设计 C 数出 75。
        //   改为**去重后计数**，口径与 C 一致。**改前改后必须同一口径，否则两列不可比。**
        // ⚠ 口径与设计 C 对齐（2026-10-04）：**只数叶子节点**。
        //   第一次我以为 79 vs 75 的差是「同一元素被算两次」，改成 Set 去重后**仍是 79** ⇒ 假设错了。
        //   真正的差是：C 只数**叶子**（无元素子节点）⇒ 排除掉 4 个**容器**元素。
        //   容器不是「说明文字」⇒ **C 的口径更对**，以它为准（否则「改前改后」两列不可比）。
        formText: (() => {
          let n = 0;
          document.querySelectorAll(".form-text, .text-muted, small").forEach(e => {
            if (e.children.length === 0 && (e.textContent || "").trim()) n++;
          });
          return n;
        })(),
        helperBlocks: q(".form-text"),
        inputs: q("input"), selects: q("select"), buttons: q("button, .btn"),
        checkboxes: q("input[type=checkbox]"),
        // ⚠ 全角括号！页面用的是「（A123）」不是「(A123)」—— 我第一版用半角，得到 0 处（假绿），
        //   而截图里明明有。设计 A/B/C 三家都量到 **17 处**。报「0 处」时先怀疑量具。
        codes: (txt.match(/（[A-Z]{1,3}[0-9A-Za-z+-]*）/g) || []).length,
        confirmBadges: (txt.match(/需人工确认/g) || []).length,
        primaryTop: r ? Math.round(r.top + scrollTop) : -1,
        primaryInFirstScreen: r ? (r.top + scrollTop) < 1000 : false,
        jargon: {},
      };
    }""")
    txt = re.sub(r"\s+", " ", pg.inner_text("body"))
    for j in JARGON:
        m["jargon"][j] = txt.count(j)
    print("  整页高度        : %d px" % m["pageH"])
    print("  表单控件        : input=%d select=%d 复选=%d 按钮=%d" % (m["inputs"], m["selects"], m["checkboxes"], m["buttons"]))
    print("  小灰字(form-text): %d 块 ｜ 所有 muted/small: %d" % (m["helperBlocks"], m["formText"]))
    print("  内部代号 (A123)  : %d 处" % m["codes"])
    print("  「需人工确认」   : %d 处" % m["confirmBadges"])
    print("  主操作纵向位置   : %s px（在首屏内: %s）" % (m["primaryTop"], m["primaryInFirstScreen"]))
    print("  行话计数        : %s" % m["jargon"])
    b.close()