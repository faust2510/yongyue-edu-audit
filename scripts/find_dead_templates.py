#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找「定义了但没人引用」的 QWeb 模板 / 视图 —— 冗余检索入口（报告型）。

**为什么立它**（2026-10-04 第 99 轮）：
  本仓已有 `find_orphan_template_vars.py`（找模板里**没被传进来的变量**）、
  `docs/audit/deadcode-scan.md`（**函数级**死代码扫描，2026-10-02 立）与
  `check_view_xpath.py`（找 xpath 打空），但**没有人找过「模板本身没人用」** —— 本脚本补的正是这一层。
  一个模板若既没被 `t-call`、也没被 `request.render`、也没被继承/改写，
  那它就是死代码 —— 而且它**不会报错**，只是安静地留在仓库里。

判据（只做文本统计，**报告型**）：
  · 收集所有 `<template id="X"` 与 `<record id="X" model="ir.ui.view">` 的定义；
  · 在 `custom_addons/**` 的 .py/.xml 里数「该 id 出现在**定义行之外**」的次数；
  · 计数为 0 ⇒ 列出来。

⚠ 已知假阳性来源（所以**不能当门禁**）：
  · 动态渲染（xmlid 由变量拼出来）；
  · 被**模块外**引用（Odoo 核心、主题、其他仓）；
  · 作为 `website.page` 的 `view_id`、或 `ir.actions` 的 `view_id`（这里也扫，但格式各异）。
  用法：find_dead_templates.py [--limit N]   退出码：0=跑完（有发现也 0）
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS = os.path.join(ROOT, "custom_addons")
# ⚠ 关键修正（首跑 518 个定义里报了 254 个，一半是假的）：
#   带 `inherit_id` 的视图是**继承视图** —— Odoo 会自动应用它们，**根本不需要有人引用**。
#   首版没排除这一类，于是 edu_brand 那批「去 odoo 化」的继承视图全被当成死代码。
#   所以定义正则要把**整个标签**抓下来，才能判断它有没有 inherit_id。
DEF_RE = re.compile(r'<(?:template|record)\b[^>]*\bid="([a-z0-9_]+)"[^>]*>', re.I)
INHERIT_RE = re.compile(r'\binherit_id\s*=', re.I)
# ⚠ 第二个关键修正（排除继承视图后仍有 221 个，又一半是假的）：
#   首版把**所有 `<record>`** 都当成了「模板/视图」，于是 ir.rule（门户自有规则）、
#   ir.cron（定时任务）、费用分类这类**数据记录**全被算进来 —— 它们**存在即生效**，
#   根本不需要谁引用。只保留真正需要被引用的：<template> 与 model="ir.ui.view" 的 record。
IS_VIEW_RE = re.compile(r'\bmodel\s*=\s*"ir\.ui\.view"', re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()
    files = []
    for dp, _d, fs in os.walk(ADDONS):
        for fn in fs:
            if fn.endswith((".py", ".xml")):
                files.append(os.path.join(dp, fn))
    texts = {}
    for f in files:
        try:
            texts[f] = open(f, encoding="utf-8").read()
        except Exception:
            pass
    defs = []   # (module, id, file, lineno)
    for f, t in texts.items():
        mod = os.path.relpath(f, ADDONS).split(os.sep)[0]
        for m in DEF_RE.finditer(t):
            line_no = t[:m.start()].count("\n") + 1
            tag = m.group(0)
            if INHERIT_RE.search(tag):
                continue          # 继承视图：Odoo 自动应用，不需要引用
            if tag.lower().startswith("<record"):
                # ⚠ 第三个关键修正（收窄到 102 个后仍是假的居多）：
                #   **后台 ir.ui.view 根本不需要被 xmlid 引用** —— Odoo 按「模型 + 视图类型」
                #   自动挑选（list/form/search 都这样），所以 `view_edu_fee_bill_list` 这类
                #   全被误报。真正需要显式引用的只有 **QWeb `<template>`**（要被 t-call /
                #   request.render / 继承 才算活）。所以 record 一律不看。
                continue
            if tag.lower().startswith("<record"):
                continue
            defs.append((mod, m.group(1), f, line_no))
    # 只统计「模块内 id」的引用（xmlid 形如 edu_portal.xxx）
    dead = []
    for mod, tid, f, ln in defs:
        xmlid = "%s.%s" % (mod, tid)
        hits = 0
        for g, t in texts.items():
            for m in re.finditer(re.escape(tid), t):
                gline = t[:m.start()].count("\n") + 1
                if g == f and gline == ln:
                    continue          # 定义行本身不算
                # 同文件里出现同名但不同前缀的，也可能只是重名 ⇒ 保守计入
                hits += 1
                break
        if hits == 0:
            dead.append((xmlid, os.path.relpath(f, ROOT), ln))
    print("扫了 %d 个文件；模板/视图定义 %d 个；**没有任何引用的 %d 个**："
          % (len(texts), len(defs), len(dead)))
    for xmlid, path, ln in dead[:a.limit]:
        print("  · %-46s %s:%d" % (xmlid, path, ln))
    if len(dead) > a.limit:
        print("  …（还有 %d 个，用 --limit 调整）" % (len(dead) - a.limit))
    print("（报告型：动态渲染 / 模块外引用会算成假阳性 ⇒ 要人读一遍，**不接 check_all**。）")
    return 0


if __name__ == "__main__":
    sys.exit(main())