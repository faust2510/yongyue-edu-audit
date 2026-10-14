#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_doc_module_count.py —— 入口文档里写死的「自研模块数」必须等于实测值。

为什么立它（2026-10-12）：
  同一个数字写死在多处、又随开发漂移，已经咬过三次 ——
    · README.md 写「自研十个模块」，实为 12（2026-10-06 修）
    · README.md 改成「12 个模块」，实为 14（2026-10-12 网页版 Claude 读仓库时抓到）
    · docs/code-map.md §3 写「9 个 edu_*」，实为 14（同上）
  这类漂移是**静默失效**：没有任何东西报错，接手的人第一眼读到的就是错的。
  同族先例：docs/plans/README.md 的份数（已改为「索引自述 + 可复跑复核命令」）。

判据（只认这两种写法，别处不碰）：
  ① 数字 + 「个」+ edu_*
  ② edu_* 之后 40 字符内出现 数字 + 「个模块」
实测值 = custom_addons/ 下 edu_* 目录数。

口径：
  · 命中行含「当时/历史/曾/已过期/退役/原先是/不再」的**跳过**（历史叙述允许旧数字），
    跳过项**逐条打印**，不静默吞 —— 静默吞掉的检查等于没检查。
  · exit 0=一致 ｜ 1=不一致 ｜ 2=环境未就绪（custom_addons 不存在）

用法：python3 scripts/check_doc_module_count.py [--selftest]
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = ["CLAUDE.md", "README.md", "docs/code-map.md", "docs/dev-workflow.md"]
SKIP_WORDS = ["当时", "历史", "曾", "已过期", "退役", "原先是", "不再"]

PATTERNS = [
    re.compile(r"(\d+)\s*个\s*edu_\*"),
    re.compile(r"edu_\*[^\n]{0,40}?(\d+)\s*个模块"),
]

# 自证样本：(文本, 期望捕获的数字 或 None 表示不该命中)
SAMPLES = [
    ("| custom_addons/ | **全部自研 Odoo 模块（9 个 edu_*）**——本项目的主战场 |", 9),
    ("自研 custom_addons/edu_* **12 个模块**（v3 新增 edu_zh）", 12),
    ("| openeducat_erp/ | OpenEduCat 官方 19.0 快照（14 个官方模块，只读不改） |", None),
    ("下面这段是**当时**的新机重建记录，保留为历史（该机已退货）", None),
    ("全仓 12 个班的学籍、216 节课", None),
]


def actual_count():
    d = os.path.join(ROOT, "custom_addons")
    if not os.path.isdir(d):
        return None
    return len([n for n in sorted(os.listdir(d))
                if n.startswith("edu_") and os.path.isdir(os.path.join(d, n))])


def scan(path):
    hits, skipped = [], []
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return hits, skipped
    with open(full, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            for rx in PATTERNS:
                for m in rx.finditer(line):
                    row = (path, i, int(m.group(1)), line.strip()[:100])
                    if any(w in line for w in SKIP_WORDS):
                        skipped.append(row)
                    else:
                        hits.append(row)
    return hits, skipped


def selftest():
    bad = 0
    for text, expect in SAMPLES:
        found = None
        for rx in PATTERNS:
            m = rx.search(text)
            if m:
                found = int(m.group(1))
                break
        ok = (found == expect)
        print("  %s 期望=%s 实得=%s ｜ %s" % ("PASS" if ok else "FAIL", expect, found, text[:60]))
        if not ok:
            bad += 1
    print("SELFTEST: %d/%d 通过" % (len(SAMPLES) - bad, len(SAMPLES)))
    return 1 if bad else 0


def main():
    if "--selftest" in sys.argv:
        return selftest()

    actual = actual_count()
    if actual is None:
        print("ENV: 找不到 custom_addons/（在 %s 下运行）" % ROOT)
        return 2

    print("== 入口文档「自研模块数」↔ 实测 ==")
    print("实测：custom_addons/ 下 edu_* 目录 %d 个" % actual)

    hits, skipped, bad = [], [], 0
    for path in DOCS:
        h, s = scan(path)
        hits.extend(h)
        skipped.extend(s)

    print("命中 %d 处 ｜ 按历史口径跳过 %d 处" % (len(hits), len(skipped)))
    for path, i, val, txt in skipped:
        print("  [跳过·历史] %s:%d 写的是 %d ｜ %s" % (path, i, val, txt))

    for path, i, val, txt in hits:
        ok = (val == actual)
        print("  [%s] %s:%d 写的是 %d（实测 %d）｜ %s"
              % ("OK" if ok else "FAIL", path, i, val, actual, txt))
        if not ok:
            bad += 1

    print("结论：%s" % ("OK" if bad == 0 else "FAIL —— %d 处与实测不符" % bad))
    print("修法：把数字改成 %d，或改成「以 ls -d custom_addons/edu_* 实测为准」不再写死。" % actual)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
