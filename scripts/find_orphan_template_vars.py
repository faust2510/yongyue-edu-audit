#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找「模板里被引用、但全仓没有任何地方提供」的变量 —— **报告型工具，不是门禁**。

## 它解决什么问题

`t-if="course_cards"` 这类写法：模板等一个变量，而**没有任何控制器传过它** ⇒ 这一段永远不渲染，
**页面上看不出来**（没有报错、没有空白，就是那一段不存在）。四轴 UI 门禁也看不见。

**成片出现时更有价值**：如果同一个模板里一次冒出好几个孤儿变量，通常不是「少传一个变量」，
而是**整个模板都没被渲染过**。C-10（`edu_welfare_checkin`，197 行）就是这么被定位到的：
`today_rec`/`recents`/`bible_streak`/`devotion_streak`/`month_attend`/`month_days`/`m_last`
一批全落在同一个模板内 ⇒ 顺着查下去发现它全仓 0 引用。参见 docs/audit/deprecated-inventory.md §4.1。

## ⚠ 已知假阳性类别（**先看完再用**）

1. **字典键**：`pager["page_count"]` —— `page_count` 由 Odoo 核心的 `pager()` 生成，本仓代码里写不出来，
   会被误报。⇒ 本脚本**先把表达式里的引号内容整段剔除**，这类就消掉了。
2. **模板名**：`t-call="edu_life_page"` —— 那是模板 id，不是变量。⇒ 不扫 `t-call` / `t-inherit`。
3. **CSS 类名碎片**：`t-attf-class="... fade ..."` ⇒ 不扫 `t-att-class` / `t-attf-class` / `t-att-style`。
4. **HTML 实体**：`&amp;` 里的 `amp` ⇒ 先剔除 `&xxx;`。
5. **继承自 Odoo 核心的模板**：`inherit_id="mail.mail_notification_layout"` 这类，变量是**核心在渲染时给的**，
   本仓代码里当然找不到（实测命中 `show_footer` / `show_unfollow` / `preference` / `unsubscribe_token`）。
   ⇒ 本脚本**没有**自动跳过这类，看输出时要自己认出来（实用判据：该模板带 `inherit_id` 且指向非本仓模块）。
6. **QWeb 的 `t-foreach` 派生变量**：`t-as="p"` 会**自动**提供 `p_index` / `p_first` / `p_last` / `p_value` 等。
   这类已编码处理（见 `scan()` 里的 `_index`/`_first`… 后缀），否则 `p_index` / `row_index` 会被误报。
7. 变量若由**父模板**通过 `t-set` 定义、或用 `t-call="x"><t t-set=...>` 传入，本脚本按「全仓有无出现」判定，
   仍可能漏（名字只出现在同一个 XML 里也算「有来源」——这正是我们要的宽口径）。

⇒ 结论：**它的输出是候选，不是结论**。每条都要人去看。

## 玩法

    python3 scripts/find_orphan_template_vars.py            # 按模板聚合输出
    python3 scripts/find_orphan_template_vars.py --flat     # 按变量平铺（原来那种）
"""
import argparse
import collections
import glob
import io
import os
import re

KEYWORDS = set("""not and or if else in is None True False len str int float bool dict list set tuple
                sum min max range sorted round abs any all getattr hasattr isinstance datetime fields
                timedelta date time map filter enumerate zip reversed next iter json math re os
                QString float_compare relativedelta""".split())

EXPR = re.compile(r't-(if|elif|foreach|out|esc|set|value|options)="([^"]*)"')
TPL = re.compile(r'<template[^>]*\bid="([^"]+)"')
INH = re.compile(r'inherit_id="([^"]+)"')
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ENTITY = re.compile(r"&[a-zA-Z]+;")
DBLQ = re.compile(r'"[^"]*"')
SNGQ = re.compile(r"'[^']*'")


def scan():
    used = collections.defaultdict(set)      # ident -> {where}
    owner = {}                               # ident -> 所属模板 id
    defined = set()
    core_inherited = set()                   # 继承自**核心模块**的模板 id（其变量由核心渲染时提供）
    for p in sorted(glob.glob("custom_addons/*/views/*.xml")):
        cur = "?"
        body = io.open(p, encoding="utf-8", errors="replace").read().split("\n")
        for i, line in enumerate(body, 1):
            m = TPL.search(line)
            if m:
                cur = m.group(1)
                # 继承自核心（website./web./mail./portal./auth_totp 等，即非 edu_*）的模板：
                #   它的变量很可能是**核心在渲染时给的**，本仓当然找不到。
                #   ⚠ 但**不能整块跳过** —— 我们自己在里面追加的区块用的是**我们的**变量，
                #     跳了就会把真孤儿一起掩盖。故只做**标注**，让人工判断带上这个上下文。
                # ⚠ inherit_id **常在下一行**（`<template id=...` 换行写 `inherit_id=...`）——
                #   只看本行会漏（第一版就漏了，两个 mail 模板没被标上）。⇒ 往后看 4 行。
                window = " ".join(body[i - 1:i + 3])
                mi = INH.search(window)
                if mi and not mi.group(1).startswith("edu_"):
                    core_inherited.add(cur)
            for m in EXPR.finditer(line):
                expr = ENTITY.sub(" ", m.group(2))
                if m.group(1) == "foreach":
                    mm = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s+in\s", expr)
                    if mm:
                        defined.add(mm.group(1))
                expr = SNGQ.sub(" ", DBLQ.sub(" ", expr))   # 剔除字符串/字典键
                for w in IDENT.findall(expr):
                    if w in KEYWORDS or len(w) < 2:
                        continue
                    used[w].add("%s:%d" % (p.split("custom_addons/")[-1], i))
                    owner.setdefault(w, cur)
            for m in re.finditer(r't-as="([A-Za-z_][A-Za-z0-9_]*)"', line):
                v = m.group(1)
                defined.add(v)
                # QWeb 的 t-foreach 会**自动**给出一整套派生变量：t-as="p" ⇒ p_index/p_first/
                #   p_last/p_value/p_size/p_odd/p_even/p_parity …。不把它们算进「已定义」，
                #   就会把 p_index / row_index 这类**本来就该有**的名字误报成孤儿。
                for suf in ("_index", "_first", "_last", "_value", "_size",
                            "_odd", "_even", "_parity", "_previous", "_next"):
                    defined.add(v + suf)
            for m in re.finditer(r't-set="([A-Za-z_][A-Za-z0-9_]*)"', line):
                defined.add(m.group(1))

    in_code = set()
    for dp, dn, fn in os.walk("custom_addons"):
        if "__pycache__" in dp:
            continue
        for f in fn:
            if f.endswith((".py", ".js")):
                in_code.update(IDENT.findall(
                    io.open(os.path.join(dp, f), encoding="utf-8", errors="replace").read()))

    orphan = {k: v for k, v in used.items() if k not in in_code and k not in defined}
    return used, orphan, owner, core_inherited


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flat", action="store_true", help="按变量平铺输出")
    a = ap.parse_args()
    used, orphan, owner, core_inherited = scan()
    print("值表达式里引用了 %d 个标识符；无来源的 **%d** 个（候选，不是结论）"
          % (len(used), len(orphan)))
    if a.flat:
        for k in sorted(orphan, key=lambda x: (-len(orphan[x]), x)):
            print("  %-26s %2d 处  %s" % (k, len(orphan[k]), sorted(orphan[k])[0]))
        return 0
    # 按模板聚合：同一个模板里孤儿越多，越可能整个模板都没被渲染
    by_tpl = collections.defaultdict(list)
    for k, v in orphan.items():
        by_tpl[owner.get(k, "?")].append(k)
    print("")
    print("按模板聚合（**孤儿 ≥2 个的模板优先看**）：")
    for tpl, names in sorted(by_tpl.items(), key=lambda kv: -len(kv[1])):
        if len(names) < 2:
            continue
        mark = "  ⚠核心继承，变量可能由核心提供（需人工判）" if tpl in core_inherited else ""
        print("  %-46s 孤儿 %d 个：%s%s"
              % (tpl, len(names), ", ".join(sorted(names)[:8]), mark))
    singles = [k for k, v in by_tpl.items() if len(v) < 2]
    print("")
    print("只有 1 个孤儿变量的模板：%d 处（多为漏传一个变量，或本工具的假阳性）" % len(singles))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())