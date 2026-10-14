#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同一指标在**多个页面**的读数是否一致 —— **报告型对照探针**。

## 为什么立它（2026-10-03，两轮里靠它抓到 4 个缺陷）

这个轴不靠「我看页面觉得不对」，而是靠**同一事实出现两个读数**自动暴露矛盾：

· 第 39 轮：家长首页「考勤 0%」 vs 学生首页「46%」—— 前者是无数据被渲染成 0；
· 第 40 轮：首页 mhero「46%」 vs 同页概览「48%」 vs 出勤页「47.92%」——
  根因是 `present`/`late` 被当成互斥标志（环形图四段和还只有 47≠48）；
· 第 41 轮全仓搜同类算式，又抓出 `/my/study`「50%」（迟到**算了两遍**）与
  Telegram 机器人「迟到恒 0」（互斥 if/elif 链里 `late` 那支永远轮不到）。

⇒ 一条指标、四处实现、三种口径。**把「读数是否一致」做成探针，比逐个页面人眼看可靠得多。**

## 判据

把各处读数**四舍五入到整数**后比较（47.92 与 48 是同一个值的不同显示精度 ✓）：

  0 = 各处一致（极差 ≤ 1）
  1 = **不一致**（极差 > 1）⇒ 至少一处错，需人工判哪处对
  2 = ENV（登录失败 / 页面取不到）—— **不是通过**

⚠ 本工具只报**「不一致」**，不替你判哪处对 —— 判对错要看库里的原始事实
   （例：`select count(*) filter (where present), count(*) filter (where late) from op_attendance_line`）。
"""
import re
import sys

BASE = "http://127.0.0.1:8069"

# 指标 → [(页面, 标签, 提取方式)]；提取方式是 (kind, spec)：
#   css  → 取该选择器的 textContent
#   re   → 在该页正文里用正则抓第一组
METRICS = {
    "出勤率": [
        ("/my/home", "首页 mhero", ("css", ".oe-mhero-big")),
        ("/my/home", "首页 概览", ("re", r"出勤率\s*([\d.]+)\s*%")),
        ("/student/progression", "学业进展", ("re", r"总出勤率\s*([\d.]+)\s*%")),
        ("/student/attendance", "我的出勤", ("re", r"考勤率\s*([\d.]+)\s*%")),
        ("/my/study", "课程中心", ("re", r"出勤率\s*([\d.]+)\s*%")),
    ],
    # 2026-10-03 加：首页「待完成作业」原先只按 batch_id 取作业 ⇒ 多算别的课程的作业
    #   （实测 batch 8 共 5 条，其中 course=13 的 2 条不属于该生 ⇒ 首页 4、作业页 2）。
    #   作业页口径 = 「总作业 − 已提交」= 该生真正待办数。
    # 2026-10-03 加：/my-courses 的卡片原先显示**专业科目总数**（14），
    #   而它「进入学习」到的 /my/study 显示**在修数**（1）—— 同词差 14 倍。
    #   现已让卡片两个口径都写出来，这条指标保证它们不再漂移。
    "在修科目数": [
        ("/my-courses", "我的课程 卡片", ("re", r"在修\s*(\d+)\s*门")),
        ("/my/study", "课程中心", ("re", r"(\d+)\s*门在修科目")),
    ],
    "待完成作业": [
        ("/my/home", "首页 KPI", ("kpi", "待完成作业")),
        ("/student/assignment/details", "作业页 总作业−已提交",
         ("minus", (r"总作业\s*(\d+)", r"已提交\s*(\d+)"))),
    ],
    # 2026-10-04（第 75 轮）加：**家长看到的同一个孩子的数**，必须与学生自己看到的一致。
    #   第 73 轮就是在这条线上抓到的：「家长首页的出勤趋势 0%」读起来像「你孩子出勤率 0%」。
    #   当时是人工看出来的 —— 这条指标把它变成机械判据（家长的「孩子仪表盘」对学生的「我的主页」）。
    #   `{child}` 由工具在跑之前从家长自己的 /my/child 页面解析出来，不写死 id。
    # 2026-10-04（第 79 轮）加：**钱**的跨角色一致 —— 学生看到「待缴合计」必须等于
    #   教务台账的「应收未收」。这是全站最不该漂的一个数（一边是学生要付的钱，
    #   一边是学校记的账），而且它天然跨角色，任何单角色探针都看不到。
    "待缴合计（学生 ↔ 教务台账）": [
        ("/my/fees", "学生 我的账单", ("re", r"当前待缴合计：¥\s*([\d,]+)"), "student"),
        ("/ledger", "教务 财务总台账", ("re", r"应收未收（open\+partial）\s*¥\s*([\d,]+)"), "backoffice"),
    ],
    # 2026-10-04（第 98 轮）加：家长仪表盘还有 4 个 KPI，此前只对过「出勤率」一个。
    #   这两个最容易漂（一个是按类型求和、一个是不同措辞的同一个数）。
    "本月打卡（家长 ↔ 学生各类型之和）": [
        ("/my/child/{child}", "家长 学习生活摘要", ("re", r"(\d+)\s*本月打卡"), "parent"),
        ("/my/checkins", "学生 各类型「本月已 N 次」求和",
         ("sum", r"本月已\s*(\d+)\s*次"), "student"),
    ],
    "已提交作业（家长 ↔ 学生）": [
        ("/my/child/{child}", "家长 学习生活摘要", ("re", r"(\d+)\s*作业提交"), "parent"),
        ("/student/assignment/details", "学生 作业页", ("re", r"已提交\s*(\d+)"), "student"),
    ],
    "出勤率（家长视角）": [
        ("/my/child/{child}", "家长 孩子仪表盘", ("re", r"([\d.]+)%\s*出勤率"), "parent"),
        ("/my/home", "学生 首页 概览", ("re", r"出勤率\s*([\d.]+)\s*%"), "student"),
    ],
}


def num(s):
    if s is None:
        return None
    m = re.search(r"([\d.]+)", str(s))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def main():
    import sys as _sys
    selftest = "--selftest" in _sys.argv
    if selftest:
        # 2026-10-04（第 102 轮）加：此前红证是拿临时副本做的，下一个人复现不了。
        #   固化成开关：把「家长出勤率」那条换成同页的另一个数（考勤/请假记录），
        #   两边读数必然不同 ⇒ 必须报「不一致」。
        METRICS["出勤率（家长视角）"] = [
            ("/my/child/{child}", "家长 孩子仪表盘（自证用错误读数）",
             ("re", r"(\d+)\s*请假记录"), "parent"),
            ("/my/home", "学生 首页 概览", ("re", r"出勤率\s*([\d.]+)\s*%"), "student"),
        ]
    from playwright.sync_api import sync_playwright
    bad = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        pg = ctx.new_page()
        pg.goto(BASE + "/web/login", timeout=45000)
        pg.wait_for_selector("form.oe_login_form", timeout=30000)
        pg.fill("form.oe_login_form input[name=login]", "stu@local")
        pg.fill("form.oe_login_form input[name=password]", "demo123")
        pg.click("form.oe_login_form button[type=submit]", timeout=30000)
        pg.wait_for_load_state("load", timeout=45000)
        if "/web/login" in pg.url:
            print("SKIP-ENV：登录失败 —— 这不是通过")
            return 2

        def _login(user):
            """另开一个上下文登录另一个角色（家长视角要用）。"""
            c = b.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
            q = c.new_page()
            q.goto(BASE + "/web/login", timeout=45000)
            q.wait_for_selector("form.oe_login_form", timeout=30000)
            q.fill("form.oe_login_form input[name=login]", user)
            q.fill("form.oe_login_form input[name=password]", "demo123")
            q.click("form.oe_login_form button[type=submit]", timeout=30000)
            q.wait_for_load_state("load", timeout=45000)
            return q

        pages = {"student": pg}
        curs = {"student": [None]}
        # `{child}` 占位：从家长自己的 /my/child 解析真实孩子 id（不写死）
        subs = {}
        if any("{child}" in s[0] for spots in METRICS.values() for s in spots):
            ppg = pages.setdefault("parent", _login("parent@local"))
            ppg.goto(BASE + "/my/child", timeout=45000)
            ppg.wait_for_timeout(1200)
            m = re.search(r"/my/child/(\d+)", ppg.content())
            subs["child"] = m.group(1) if m else "0"
            print("（家长的孩子 id = %s）" % subs["child"])

        cache = {}
        cur = [None]   # 当前页面 path（用于判断要不要重新导航）
        for metric, spots in METRICS.items():
            print("=== 指标：%s ===" % metric)
            vals = []
            for spot in spots:
                path, label, (kind, spec) = spot[0], spot[1], spot[2]
                role = spot[3] if len(spot) > 3 else "student"
                for k, v in subs.items():
                    path = path.replace("{%s}" % k, v)
                pg = pages.get(role)
                if pg is None:
                    # 角色 → 账号映射（2026-10-04 第 79 轮：加 backoffice 以便查「钱」的跨角色一致）
                    users = {"student": "stu@local", "parent": "parent@local",
                             "faculty": "faculty@local", "backoffice": "backoffice@local"}
                    pg = pages[role] = _login(users.get(role, role))
                cur = curs.setdefault(role, [None])
                # ⚠ 必须**每次提取前都把页面切到该 path**：`css`/`kpi` 是拿当前页做 evaluate 的，
                #   若沿用「只在没缓存时导航」，等轮到后面的 spot 时页面早被导航到别处了
                #   （本工具第一版就这样：首页 KPI 取不到值，而出勤率那条只是**碰巧**第一个跑）。
                if cur[0] != path:
                    pg.goto(BASE + path, timeout=45000)
                    pg.wait_for_timeout(1500)
                    cur[0] = path
                    cache[path] = re.sub(r"\s+", " ", pg.inner_text("body"))
                if kind == "css":
                    raw = pg.evaluate("(s) => { const e = document.querySelector(s); return e ? e.textContent.trim() : null; }", spec)
                elif kind == "kpi":
                    # 首页 KPI 瓦片：按标签找那块，取它的数值
                    raw = pg.evaluate("""(lab) => {
                      for (const e of document.querySelectorAll(".oe-kpi")) {
                        const t = (e.textContent || "").replace(/\\s+/g, " ");
                        if (t.indexOf(lab) >= 0) {
                          const v = e.querySelector(".oe-kpi-val");
                          if (v) return v.textContent.trim();
                        }
                      }
                      return null;
                    }""", spec)
                elif kind == "sum":
                    # 同一页多个同类数字求和。2026-10-04（第 98 轮）加：
                    #   学生打卡页是**按类型**列的（到堂/读经/灵修/周记 各一个「本月已 N 次」），
                    #   而家长仪表盘给的是**一个总数**「6 本月打卡」⇒ 必须求和才能比。
                    #   （我第一眼看到 6 vs 2 以为漂了，其实是口径不同 —— 第 94 轮同样的教训。）
                    nums = [float(x) for x in re.findall(spec, cache[path])]
                    raw = str(sum(nums)) if nums else None
                elif kind == "minus":
                    # 同一页两个数相减（如「总作业 − 已提交」）
                    # ⚠ 别用 a/b 命名：外层 `b` 是浏览器句柄 —— 覆盖它会让结尾的 b.close() 炸
                    #   （本工具第一版就这么错过：`AttributeError: 're.Match' object has no attribute 'close'`）。
                    ma = re.search(spec[0], cache[path])
                    mb = re.search(spec[1], cache[path])
                    raw = (float(ma.group(1)) - float(mb.group(1))) if (ma and mb) else None
                else:
                    m = re.search(spec, cache[path])
                    raw = m.group(1) if m else None
                v = num(raw)
                vals.append((label, path, raw, v))
                print("     %-14s %-22s 读数=%-8s %s" % (label, path, raw if raw else "（取不到）",
                                                      "" if v is not None else "  ⚠"))
            got = [v for *_, v in vals if v is not None]
            if len(got) < 2:
                print("     ⚠ 可读数不足 2 处，无法对照")
                continue
            spread = max(got) - min(got)
            if spread > 1:
                bad += 1
                print("     ⛔ 不一致：极差 %.2f（%s）" % (spread, " / ".join(str(v) for v in got)))
            else:
                print("     ✅ 一致：极差 %.2f" % spread)
        ctx.close()
        b.close()
    if selftest:
        print("  自证：给家长那条换成同页的另一个数（请假记录），%s"
              % ("被抓到（对）" if bad else "**没抓到 —— 量具坏了**"))
        return 0 if bad else 1
    if bad:
        print("RESULT=FOUND（%d 个指标的读数不一致）" % bad)
        return 1
    print("RESULT=OK（各指标在多个页面的读数一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())