#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐角色逐页空态矩阵：把 sweep 读数 + 判据结论渲染成报告用的 Markdown 表。

状态口径（写死在 report.md §2，这里实现同一份）：
  有内容        records > 0（table tbody tr + .card + .oe-asg-card）
  空态-合格     结构为空且判据（check_empty_state_quality.judge）无红
  空态-不合格   结构为空且判据报 E1/E2/E-HTTP
  需人工看      结构为空、无识别到空态文案、正文也短（E0；可能是自绘卡片页）
  正文页        结构为空但 mainText >= 300（如 /help 指南正文）——不是空态
  非页面        非 HTML 响应 / 探页失败（照实标注，不判）

用法：python3 docs/audit/empty-states/page_matrix.py --tag after > docs/audit/empty-states/page-matrix.md
"""
import argparse
import glob
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_empty_state_quality as chk  # noqa: E402

ROLE_LABEL = {"student": "学生", "parent": "家长", "faculty": "教师",
              "backoffice": "教务", "guest": "访客（未登录）", "first": "学生（空账号夹具）"}
ROLE_ORDER = ["student", "first", "parent", "faculty", "backoffice", "guest"]


def load(patterns):
    rows = {}
    for pat in patterns:
        for p in sorted(glob.glob(pat)):
            with io.open(p, encoding="utf-8") as fh:
                doc = json.load(fh)
            for r in doc.get("readings") or []:
                rows.setdefault(r.get("role"), {})[r.get("path")] = r
    return rows


def classify(r):
    """-> (状态, 文案, 判据)"""
    if r.get("verdict") != "ok":
        return "非页面", "探页失败：%s" % (r.get("error") or "")[:60], "E-PROBE"
    ctype = (r.get("ctype") or "").lower()
    if ctype and "html" not in ctype:
        return "非页面", "非 HTML 响应（%s）" % ctype, "skip"
    http = r.get("http")
    if http not in (200, 303):
        return "空态-不合格", "HTTP %s（页面打不开）" % http, "E-HTTP"
    if r.get("records"):
        return "有内容", "records=%s" % r.get("records"), ""
    tx = chk.texts(r)
    mt = r.get("mainText") or ""
    if not tx:
        if len(mt) >= 300:
            return "正文页", mt[:50], ""
        return "需人工看", "（无空态文案）", "E0"
    longest = max(tx, key=lambda x: len(x["text"]))
    issues, notes = chk.judge(r)
    codes = "/".join(i["code"] for i in issues) or "/".join(n["code"] for n in notes)
    return ("空态-不合格" if issues else "空态-合格"), longest["text"][:70], codes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--readings", action="append", default=[])
    ap.add_argument("--tag", default="after")
    args = ap.parse_args()
    pats = args.readings or ["docs/audit/empty-states/sweep-*%s*.json" % args.tag]
    rows = load(pats)
    print("# 逐角色逐页空态矩阵（读数：%s）\n" % "，".join(os.path.basename(p) for p in pats))
    tot = {"空态-合格": 0, "空态-不合格": 0, "需人工看": 0}
    for role in [r for r in ROLE_ORDER if r in rows] + sorted(set(rows) - set(ROLE_ORDER)):
        pages = rows[role]
        print("## %s（%s）—— %d 条读数\n" % (ROLE_LABEL.get(role, role), role, len(pages)))
        print("| 路由 | HTTP | 状态 | 空态文案（原样摘录，空白归一） | 判据 |")
        print("|---|---|---|---|---|")
        for path in sorted(pages):
            r = pages[path]
            st, txt, code = classify(r)
            if st in tot:
                tot[st] += 1
            txt = txt.replace("|", "\\|")
            print("| `%s` | %s | %s | %s | %s |" % (path, r.get("http"), st, txt, code))
        print("")
    print("## 合计\n")
    for k, v in tot.items():
        print("- %s：%d 条读数" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())