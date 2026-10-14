#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""空态质量巡检（文案层判据）：把「空的时候说没说明白」变成机械可判、可反向证伪的读数。

为什么需要它（与 D 轴的分工）
------------------------------
scripts/check_ui_usability.py 的 D 轴判据是**结构性**的：页面无 table tbody tr 且无 .card，
且页内没有任何指向其他页面的 a[href] ⇒ 报「死胡同」。它自己写明了局限：「不看文案」。
后果是两类真缺陷它**永远看不见**（2026-10-02 实测）：
  ① 半截空态：/student/attendance 只写「暂无考勤记录。」—— 页脚有导航，出口判据满足，D 轴绿；
     但用户不知道「为什么空」「下一步去哪」。
  ② 结构误判：/student/attendance 有 48 条记录时，模板渲染的既不是表格行也不是 .card
     ⇒ D 轴把它当「空态」；反过来 .oe-asg-card 卡片页在 D 轴眼里也是「空」。
本脚本只补第 ① 类的判据（文案层），第 ② 类照实记录为已知局限。

判据（逐条可复算；口径全部写在下面，改口径必须同时改本节）
----------------------------------------------------------------
  输入：docs/audit/empty-states/sweep-*.json（sweep.py 逐页抓的 DOM + 文本）。
  A. 取样范围：verdict == ok 且响应是 HTML（ctype 含 html 或空）的读数。
  B. 错误页：http 不在 (200, 303) ⇒ E-HTTP 报红（空态讨论的前提是页面能打开）。
  C. 「内容空态」判定（**比 D 轴多算 .oe-asg-card**，因为本项目部分列表用自绘卡片）：
       records == 0（records = table tbody tr + .card + .oe-asg-card）
       且（hints 非空 或 mainText 长度 < 300）
       —— mainText 长 = 页面有正文（如 /help 的指南正文），不是空态，退出本判据。
  D. E0（**不计红**，记 INFO）：结构上无记录/卡片、又没识别到任何空态文案 ——
       可能是本项目大量使用的自绘卡片页（.oe-asg-card 之外还有别的类名），也可能是真空白。
       结构判断是 D 轴的活，本判据不据此报红：改变不了结论的检查不许冒充判据。
  E. E1 说明性（报红）：最长的空态文案去掉空白后 >= 24 字符。
       「暂无考勤记录。」= 7 字符 ⇒ 红；补齐「为什么空 + 会怎样填满」后 >= 24 ⇒ 绿。
       阈值 24 的来历：本仓既有合格空态的最短一条（/my/dms 的「暂无文档。上传或接收的文件将在此处管理。」）
       是 23 字符，取 24 表示「至少要像它那样多说一句」。
  F. E2 出口/指引（报红）：空态块的 outerHTML 含 <a（块内真链接），或其文案命中动作指引词表
       （请|去|查看|联系|先|可|需要|由|自动出现|报名|发起|提交|新建|申请|打开|点击）。
       两者都不满足但**页面上**有动作入口（链接标签含动作词）⇒ 记 E2-weak（INFO，不计红）：
       D 轴只要求「页内有链接」，这里把「块内出口」记成读数而不是判据，免得为过门禁硬塞链接。
  退出码：0 = 无红；1 = 有红；2 = INCOMPLETE（读数文件读不到 / 形状不对）。

用法：
    python3 docs/audit/empty-states/check_empty_state_quality.py docs/audit/empty-states/sweep-before-*.json
    python3 docs/audit/empty-states/check_empty_state_quality.py --only /student/attendance <file>
"""
import argparse
import glob
import io
import json
import os
import re
import sys

MIN_INFO = 8
#: 「裸陈述」判据：先按空态短语切掉「没有 X」那一段，再说剩下的字够不够。
#: 为什么不用「全文 >= 24 字符」这种固定阈值（第一版就是这么写的，实测两处假红）：
#:   · 「尚未记录技能评估，添加你的第一个技能吧。」20 字符 —— 它已经给了下一步（下面就是表单），
#:     却因为比阈值短 4 个字被判红；
#:   · 「还没有账号？在线报名 或 使用邀请码注册。」22 字符 —— 块内两个真链接，同样被判红。
#: 阈值天生会把「短而完整」当成「短而残缺」。改成切掉空态短语后看剩余信息量：
#:   · 「暂无考勤记录。」⇒ 剩余 0 字 ⇒ 红（这才是「只写暂无数据」）；
#:   · 「尚未记录技能评估，添加你的第一个技能吧。」⇒ 剩余「添加你的第一个技能吧」⇒ 绿。
BARE_RE = re.compile("(暂无|还没有|尚未|暂未|没有符合条件|没有记录|无记录|无数据|未分班|未选课|未发布|未开放)"
                     "[^，。；！？、]{0,14}[，。；！？]?")
ACTION_WORDS = ("请", "去", "查看", "联系", "先", "可", "需要", "由", "自动出现", "报名",
                "发起", "提交", "新建", "申请", "打开", "点击", "添加", "上传", "下载", "找")


def info_len(text):
    """切掉「没有 X」之后的剩余信息量（去掉标点空白后计字数）。纯函数，可单测。"""
    core = BARE_RE.sub("", text)
    core = re.sub(r"[\s，。；！？、,.!?;:：（）()\[\]【】]+", "", core)
    return len(core)
#: 只认「明确说没有」的措辞。为什么不用 sweep.py 抓 hint 时的宽口径，
#: 原因是有实测假红：宽口径含「待办 / 等待 / 空白 / 可」，
#: 教学指南里的「待办事项计数」（/help/faculty）会被当成空态文案，
#: 于是指南页被本判据误报。判据宁可漏（漏的由 D 轴与人工补），不许噪音。
EMPTY_RE = re.compile("暂无|还没有|尚未|暂未|没有符合条件|没有记录|无记录|无数据|未分班|未选课|未发布|未开放")
#: 站内链接的元素判定：<a href=...> / <a\n / <a> 都要认（第一版写成 "<a " 漏掉了 <a href>，实测假红 /help）。
LINK_RE = re.compile(r"<a[\s>]")


def texts(reading):
    """严格空态文案（EMPTY_RE 过滤后去重）。返回 [{text, html}]。"""
    # 判定的单位是「空态区域」：sweep.py 用类名抓到的容器（.oe-norec / .oe-empty / 各种 nocontent）优先，
    # 因为它们才是用户看到的那一整块（可能含「说明段 + 按钮」多个兄弟元素）。
    # 没有类名容器时（本仓大量裸 <div class="alert alert-info">暂无X。</div>）退回 hint 的内层文本。
    # 事故现场（2026-10-02）：/my/calendar 补了说明段 + 「查看课表」按钮，但说明段不含「暂无」，
    # 只按 hint 判 ⇒ 仍只看到最内层那句「本月暂无校历事项。」⇒ 判据假红（修好了却说没修）。
    blocks = [{"text": " ".join((b.get("text") or "").split()), "html": b.get("html") or ""}
              for b in (reading.get("emptyBlocks") or [])]
    blocks = [b for b in blocks if b["text"] and EMPTY_RE.search(b["text"])]
    srcs = blocks
    if not srcs:
        # 只认**块级**元素。实测假红（2026-10-02）：/my/study 的课程卡里有个 <span>「暂无排课」
        # （ux3-meta-item 的兜底值），它不是空态文案，是卡片里的一个字段值 ——
        # 拿它当空态判会把人引去改一个根本不该改的地方。
        BLOCK_TAGS = ("p", "div", "li", "td", "section", "article", "h1", "h2", "h3", "h4", "h5")
        srcs = [{"text": " ".join((h.get("text") or "").split()), "html": h.get("html") or ""}
                for h in (reading.get("hints") or [])
                if (h.get("tag") or "p") in BLOCK_TAGS]
        srcs = [s for s in srcs if s["text"] and EMPTY_RE.search(s["text"])]
    raw, seen = [], set()
    for src in srcs:
        t = src["text"]
        if not t or t in seen:
            continue
        seen.add(t)
        raw.append({"text": t, "html": src["html"]})
    # 只留**最内层**：sweep.py 的 hint 抓取限定 children<=2，仍可能同时抓到「外层容器 + 内层空态块」
    # （实测：/student/attendance 抓到「排序依据…导出 CSV 暂无考勤记录。」与「暂无考勤记录。」两条）。
    # 判定文案质量必须用最内层那句 —— 否则外层容器把长度撑过 E1 阈值，真缺陷被自己的取样口径洗白。
    # 这里用「文本包含关系」做包含去重（对旧读数同样适用，不需重跑采集）。
    # 保留「最小文本」= 丢掉文本里**包含**了另一条候选的那些（外层容器）；方向写反过一次，
    # 实测后果：div.b11-body 把整页文本（含 暂无考勤记录。）撑到 160 字符 ⇒ E1 假绿。
    out = [a for a in raw
           if not any(a is not b and b["text"] in a["text"] and b["text"] != a["text"] for b in raw)]
    return out or raw


def page_action_links(reading):
    """页面上带动作词的站内链接标签（E2 的兜底信号：页面确实给了一个可点的下一步）。"""
    out = []
    for l in (reading.get("links") or []):
        href, txt = (l.get("href") or ""), (l.get("text") or "")
        if not href.startswith("/") or href.startswith("//"):
            continue
        if any(w in txt for w in ACTION_WORDS):
            out.append("%s(%s)" % (txt, href[:40]))
    return out


def judge(reading):
    """纯函数：一条读数 -> (issues, notes)。issues = 报红；notes = 需人工看一眼（不计红）。"""
    ctype = (reading.get("ctype") or "").lower()
    if reading.get("verdict") != "ok":
        return [{"code": "E-PROBE", "detail": "探页失败：%s" % (reading.get("error") or "")[:120]}], []
    if ctype and "html" not in ctype:
        return [], []
    http = reading.get("http")
    if http not in (200, 303):
        return [{"code": "E-HTTP", "detail": "HTTP %s：页面打不开，空态无从谈起" % http}], []
    if reading.get("records") != 0:
        return [], []
    mt = reading.get("mainText") or ""
    tx = texts(reading)
    if not tx and len(mt) >= 300:
        return [], []
    if not tx:
        # 结构上「无记录/无卡片」但一个字都没识别到：可能是自绘卡片页（本项目大量使用），
        # 也可能是真空白。**不据此报红**（结构判断是 D 轴的活，且 D 轴已自述误判面），
        # 记为 E0 让人工看一眼 —— 「要断言检查过，就必须让检查失败能改变结论」，
        # 这一条改变不了结论，所以它不许冒充判据。
        return [], [{"code": "E0", "detail": "结构上无记录/卡片且未识别到空态文案（可能是自绘卡片页，需人工看）"}]
    longest = max(tx, key=lambda x: len(x["text"]))
    issues, notes = [], []
    bare = [t for t in tx
            if info_len(t["text"]) < MIN_INFO and not LINK_RE.search(t["html"] or "")]
    # E1 逐块判：**每一个**空态块都要说得下去（不是只看最长的那个）。
    # 事故现场（2026-10-02 反向注入）：把 /my/study 的空态抽成「暂无在修科目。」后，
    # 只看最长块（同页另有「本周暂无排课…」那段）⇒ 判据假绿。逐块判才抓得到。
    if bare:
        worst = min(bare, key=lambda t: info_len(t["text"]))
        issues.append({"code": "E1", "detail": "有 %d 个空态块是裸陈述（切掉「没有 X」后剩 %d 字 < %d，块内也无链接），最短一条：%s"
                       % (len(bare), info_len(worst["text"]), MIN_INFO, worst["text"][:60])})
    has_exit = any(LINK_RE.search(t["html"] or "") or any(w in t["text"] for w in ACTION_WORDS)
                   for t in tx)
    if not has_exit:
        acts = page_action_links(reading)
        if acts:
            notes.append({"code": "E2-weak",
                          "detail": "空态块内无链接/指令，但页面上有动作入口：%s"
                                    % "，".join(acts[:3])})
        else:
            issues.append({"code": "E2", "detail": "空态块内既没有链接也没有动作指引，页面上也没有动作入口：%s"
                           % longest["text"][:60]})
    return issues, notes


def load(paths, only):
    rows, meta = [], {}
    for pat in paths:
        for p in sorted(glob.glob(pat)):
            with io.open(p, encoding="utf-8") as fh:
                doc = json.load(fh)
            meta[p] = doc.get("meta") or {}
            for r in doc.get("readings") or []:
                if only and only not in (r.get("path") or ""):
                    continue
                rows.append(r)
    return rows, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("readings", nargs="+", help="sweep-*.json 路径（支持通配）")
    ap.add_argument("--only", default="", help="只看含该子串的路径")
    args = ap.parse_args()
    rows, meta = load(args.readings, args.only)
    if not rows:
        print("INCOMPLETE：读不到任何读数（%s）" % args.readings)
        return 2
    red, green, skipped, notes = [], 0, 0, []
    for r in rows:
        issues, ns = judge(r)
        if ns:
            notes.append((r, ns))
        if not issues:
            green += 1
            continue
        if all(i["code"] == "E-PROBE" for i in issues):
            skipped += 1
            continue
        red.append((r, issues))
    for p, m in meta.items():
        c = (m.get("container") or {})
        print("读数：%s（tag=%s，探页 %s，容器样本有效=%s）"
              % (os.path.basename(p), m.get("tag"), m.get("probes"), c.get("sample_valid")))
    print("== 空态文案判据（E0/E1/E2）==")
    print("读数 %d 条：无问题 %d ｜ 报红 %d ｜ 探页失败跳过 %d" % (len(rows), green, len(red), skipped))
    for r, issues in sorted(red, key=lambda x: (x[0].get("path") or "")):
        print("  [RED] %-10s %-38s %s" % (r.get("role"), r.get("path"),
                                          "；".join("%s:%s" % (i["code"], i["detail"]) for i in issues)))
    print("-- 需人工看一眼（E0/E2-weak：结构未识别或缺块内出口，**不计红**）%d 条 --" % len(notes))
    for r, ns in sorted(notes, key=lambda x: (x[0].get("path") or ""))[:20]:
        print("  [INFO] %-10s %-38s %s" % (r.get("role"), r.get("path"),
                                           "；".join("%s:%s" % (i["code"], i["detail"][:90]) for i in ns)))
    if len(notes) > 20:
        print("  … 另 %d 条" % (len(notes) - 20))
    print("结论：%s" % ("无红（空态文案层全绿）" if not red else "有 %d 页空态文案不合格" % len(red)))
    return 0 if not red else 1


if __name__ == "__main__":
    sys.exit(main())