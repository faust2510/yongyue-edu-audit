#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找「手机上被挤扁的表格」—— **报告型工具**（判据见下）。

## ⚠ 两条已知的「报了但不是缺陷」，读报告时先看这里（2026-10-03 补）

**① 日历 / 排班这类「宽网格」本来就该宽着滚 —— 别去卡片化它。**
本仓自己的先例：`edu_portal/static/src/css/ux_rework.css:69` 明确写 `.ux-cal-week { min-width: 820px; }`，
即**有意**让周课表网格宽于屏幕，并在同一页提供「月 / 周 / **列表**」三态切换作为窄屏替代（`calendar.xml:210` 的 `.ux-cal-list`）。
所以判据 A 对 7 列日期网格会报「未卡片化」，那是**判据的边界，不是页面的缺陷**。
实测例子：`/my/checkins` 的月历（7 列、表宽 658 / 容器 329）—— 报告里出现时要人工判断，
正确问法不是「怎么折成卡片」，而是「这一页有没有像 /my/calendar 那样的列表替代」。

**② 只看得到「演示数据渲染出来的」表。**
同一个 `/my/checkins`：库里没有打卡记录时页面走**空态**（根本没有表）⇒ 扫描看不见；
一旦有了记录，7 列月历才被渲染出来、才被命中。
⇒ **全绿不等于没有宽表，只等于「当前演示数据下没有宽表」。**
（本仓已登记的同类盲区：`docs/audit/ui-visual-review/report.md` §「身份抽样与数据依赖渲染叠加」）

## 判据

## 为什么需要它（2026-10-02 round 12 的教训）

四轴 UI 门禁量的是**文档宽度**。`/my/fees` 补了 `.table-responsive` 之后 A 轴从 93px 变 0 ——
但 390 视口下那张 6 列表仍然挤成**逐字换行**（「【演/示】/2026/春季/统筹/费」），「状态」列被裁在屏外。
⇒ **「门禁绿」不等于「能用」**；「挤成一团」没有任何机械判据在量。这个脚本就是那条判据。

## 判据（只在 375 视口）

一个 `<table>` 同时满足：
  ① `thead` 仍然可见（`display !== none` ⇒ **没有走卡片模式**）；
  ② 列数 ≥ 4；
  ③ 表宽 > 容器宽 + 4px ⇒ 屏幕装不下。
⇒ 用户在手机上要么横向滚动才看得全、要么每列被压到几十像素宽而逐字换行。两种都是差体验。

**不判**：`thead` 已隐藏（那就是已经在用卡片模式了）。

## 修法（本仓已有，不要新造）

`custom_addons/edu_portal/views/roles.xml:554` 的共用模板 `edu_portal.edu_narrow_table_cards`：
纯 CSS，`@media (max-width: 767.98px)` 下隐藏 thead、把每行折成卡片、由每个 td 的 `data-label` 顶出列名。
三步：① 表前 `<t t-call="edu_portal.edu_narrow_table_cards"/>`（**每个模板一次即可**）；
② 表加 `edu-card-table` 类；③ **每个 td** 加 `data-label="列名"`。
已有用例：enroll.xml:320、roles.xml:632/:1679、leave_flow.xml、fees.xml。

## 玩法

    python3 scripts/find_squeezed_tables.py               # 全量扫描（约 8 分钟）
    python3 scripts/find_squeezed_tables.py --path /ledger # 只查一条，验证修复用
"""
import argparse
import io
import json
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8069"
LOGINS = {"student": ("stu@local", "demo123"),
          "faculty": ("faculty@local", "demo123"),
          "backoffice": ("backoffice@local", "demo123"),
          "parent": ("parent@local", "demo123")}

JS = """() => {
  const out = [];
  // 数「文本行盒」：一个 th 的文字占几行。元素高度不能用（行高会把同一行所有 th 一起算进去）。
  // ⚠ 2026-10-02 修正（narrow-a 报告）：**不能**用 selectNodeContents(el).getClientRects().length ——
  //   th 里的行内图标 <i> 会**额外贡献 1 个 rect**，含图标的表头恒被算成「折了」。
  //   实测：1440 下同一批 4 个含图标表头 rects=2，而**纯文本行盒=1**（它们明明在同一行）。
  //   ⇒ 只遍历**文本节点**，按行顶坐标去重；元素（图标）不参与计数。
  const lines = el => {
    const ys = new Set();
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      if (!n.textContent || !n.textContent.trim()) continue;
      const r = document.createRange();
      r.selectNodeContents(n);
      for (const rect of r.getClientRects()) ys.add(Math.round(rect.top));
    }
    return ys.size;
  };
  for (const t of document.querySelectorAll("table")) {
    const th = t.querySelector("thead");
    const visible = !!th && getComputedStyle(th).display !== "none";
    const wrap = t.parentElement;
    let 折行表头 = 0;
    if (visible) {
      for (const h of t.querySelectorAll("thead th")) if (lines(h) > 1) 折行表头++;
    }
    const heads = [...t.querySelectorAll("thead th")].map(h => (h.textContent || "").trim());
    const WEEK = /^(周一|周二|周三|周四|周五|周六|周日|Mon|Tue|Wed|Thu|Fri|Sat|Sun)$/;
    const isCal = (heads.length >= 5 && heads.every(x => WEEK.test(x)))
                  || /(^|\\s)(life-cal|ux-cal[\\w-]*)(\\s|$)/.test(t.className || "");
    out.push({cols: t.querySelectorAll("thead th").length,
              tableW: Math.round(t.getBoundingClientRect().width),
              containerW: wrap ? Math.round(wrap.clientWidth) : 0,
              theadVisible: visible, 折行表头: 折行表头, isCal: isCal});
  }
  return out;
}"""


def login(pg, user, pwd):
    """登录并**校验真的登进去了**。

    ⚠ 2026-10-02 实测教训（empty-states 报的假绿）：本工具一度只用浏览器表单登录、不校验结果。
    本仓登录页会把 core 的 `oe_login_form` 渲染成 `d-none`，偶发登不进去 ⇒ 目标页被重定向到登录页
    ⇒ 页面上**一张表都没有** ⇒ 被判成「无挤扁表」= **假绿**。
    实测：/registrar/curriculum 同一条命令，1 次报 OK、连跑 3 次全报 SQUEEZED（后者才对）。
    ⇒ 修法：登录后必须确认① 真的离开了 /web/login；② 页面上有已登录标记。任一不成立就抛错，
       由调用方记为 **ENV**（环境未就绪），**不是通过**。
    """
    pg.goto(BASE + "/web/login", timeout=45000)
    pg.wait_for_selector("form.oe_login_form", timeout=30000)
    pg.fill("form.oe_login_form input[name=login]", user)
    pg.fill("form.oe_login_form input[name=password]", pwd)
    pg.click("form.oe_login_form button[type=submit]", timeout=30000)
    pg.wait_for_load_state("load", timeout=45000)
    if "/web/login" in pg.url:
        raise RuntimeError("登录后仍停在 /web/login（url=%s）" % pg.url)
    cookies = {c["name"] for c in pg.context.cookies()}
    if "session_id" not in cookies:
        raise RuntimeError("登录后拿不到 session_id cookie")


def judge(pg, path):
    hits = []
    r = pg.goto(BASE + path, timeout=30000)
    pg.wait_for_timeout(400)
    if not r or r.status >= 400:
        return hits
    for t in pg.evaluate(JS):
        if t["cols"] < 4:
            continue
        # 判据 0（2026-10-03 补）：**日历 / 排班这类宽网格本来就该宽着滚** ——
        #   本文件头注释第 ① 条**早就写明**了这一点，但代码里一直没有实现它 ⇒
        #   7 列日期网格每轮都被当成「未卡片化」报出来，与真缺陷混在一起，
        #   让这份报告**长期带着假阳性**（本仓纪律：一条永远红/永远 WARN 的门禁＝死门禁）。
        #   实测来源：/my/checkins 那张 class=`life-cal` 的表（表头 周一…周日、单元格是日号）。
        #   判据：表头全是星期名，或表 class 含 life-cal / ux-cal-*。
        if t.get("isCal"):
            t["kind"] = "日历网格（有意，不判）"
            continue
        # 判据 A：**没走卡片模式**（thead 可见）却比屏幕宽 ⇒ 横向滚动 / 逐列挤压
        if t["theadVisible"] and t["tableW"] > t["containerW"] + 4:
            t["kind"] = "未卡片化"
            hits.append(t)
            continue
        # 判据 B（narrow-b 报告）：**已走卡片模式却仍比容器宽** —— 卡片被撑破。
        #   ⚠ 更正：这条我在 round 13 声称「已补进工具」，实际那次改动因语法错误**没落盘**；
        #     2026-10-02 复核时发现 judge() 里根本没有它。现在真的补上（并已自证，见下）。
        if (not t["theadVisible"]) and t["tableW"] > t["containerW"] + 4:
            t["kind"] = "卡片被撑破"
            hits.append(t)
            continue
        # 判据 C（2026-10-02 第四组视觉复核补）：**表头被折成多行**。
        #   表格「装得下」（表宽 ≤ 容器宽）所以判据 A 看不见，但列被自动布局压窄，
        #   2–3 字的表头被拆成上下两行 —— 实测 /my/documents（得分/满分/及格线/状态 全两行）、
        #   同类还有 round 12 的 /registrar/subject/approvals（单号/状态）。
        #   ⚠ 阈值取 **≥2 个**：单个表头折行可能是长标签正常换行；2 个以上一起折才是「整表被压窄」。
        if t["theadVisible"] and t.get("折行表头", 0) >= 2:
            t["kind"] = "表头折行×%d" % t["折行表头"]
            hits.append(t)
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=None, help="只查这一条路径（需配 --role）")
    ap.add_argument("--role", default="backoffice")
    a = ap.parse_args()
    flagged = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        if a.path:
            user, pwd = LOGINS[a.role]
            ctx = b.new_context(viewport={"width": 375, "height": 812}, locale="zh-CN")
            pg = ctx.new_page()
            login(pg, user, pwd)
            hits = judge(pg, a.path)
            for t in hits:
                print("  %s：%d 列  表宽 %d / 容器 %d"
                      % (t.get("kind", "挤扁"), t["cols"], t["tableW"], t["containerW"]))
            print("RESULT=%s" % ("SQUEEZED" if hits else "OK（无挤扁表）"))
            ctx.close()
            b.close()
            return 1 if hits else 0
        data = json.load(io.open("tests/ui/surface.json", encoding="utf-8"))
        pages = data["pages"] if isinstance(data, dict) and "pages" in data else data
        targets = [p for p in pages if isinstance(p, dict) and p.get("scope") == "portal"]
        for role, (user, pwd) in LOGINS.items():
            ctx = b.new_context(viewport={"width": 375, "height": 812}, locale="zh-CN")
            pg = ctx.new_page()
            try:
                login(pg, user, pwd)
            except Exception as e:
                print("  登录失败 %s：%s" % (role, e))
                ctx.close()
                continue
            for it in targets:
                if role not in (it.get("roles") or []):
                    continue
                path = it.get("path") or ""
                if "<" in path:
                    continue
                try:
                    for t in judge(pg, path):
                        flagged.setdefault(path, (role, t))
                except Exception:
                    continue
            ctx.close()
        b.close()
    print("=== 手机上「thead 可见 + ≥4 列 + 表宽 > 容器」的页面 ===")
    for path, (role, t) in sorted(flagged.items()):
        print("  %-38s [%s] %-16s %d 列  表宽 %d / 容器 %d"
              % (path, role, t.get("kind", "挤扁"), t["cols"], t["tableW"], t["containerW"]))
    print("命中页面数：%d" % len(flagged))
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())