#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐页 before/after 证据生成器：把两份 sweep 读数里的**同一页 × 同一角色**摆在一起。

口径：空态块一律取「最内层」（复用 check_empty_state_quality.texts 的包含去重），
      DOM 片段是 var.browser 里真实渲染出来的 outerHTML（sweep.py 采集），不是模板源码改写。

用法：
    python3 docs/audit/empty-states/diff_evidence.py \
        --before docs/audit/empty-states/sweep-first-before-*.json \
        --after  docs/audit/empty-states/sweep-first-after-*.json \
        --pair /student/attendance:first --pair /student/exam:first ...
    # --pair 省略时，输出两份读数里所有「改前报红、改后不报红」的页（自动对照）
"""
import argparse
import glob
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_empty_state_quality as chk  # noqa: E402  （同一把尺子，不复制第二份口径）


def load(patterns):
    out = {}
    for pat in patterns:
        for p in sorted(glob.glob(pat)):
            with io.open(p, encoding="utf-8") as fh:
                doc = json.load(fh)
            for r in doc.get("readings") or []:
                out[(r.get("path"), r.get("role"))] = r
    return out


def block(reading):
    tx = chk.texts(reading)
    if not tx:
        return "", ""
    longest = max(tx, key=lambda x: len(x["text"]))
    return longest["text"], " ".join((longest["html"] or "").split())


def line(label, r):
    if not r:
        return "- %s：读数缺失" % label
    http = r.get("http")
    txt, html = block(r)
    v = "空" if r.get("records") == 0 else "有内容(records=%s)" % r.get("records")
    if not html:
        html = "（本页没有可识别的空态块）"
    return ("- %s：HTTP %s ｜ records=%s（%s） ｜ DOM：%s"
            % (label, http, r.get("records"), v, html))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", action="append", required=True)
    ap.add_argument("--after", action="append", required=True)
    ap.add_argument("--pair", action="append", default=[],
                    help="路径:角色（可重复）；省略则自动取「改前有 E1/E2 红、改后无红」的页")
    args = ap.parse_args()
    B, A = load(args.before), load(args.after)
    pairs = []
    if args.pair:
        for spec in args.pair:
            path, _, role = spec.rpartition(":")
            pairs.append((path, role))
    else:
        for key in sorted(set(B) | set(A)):
            rb, ra = B.get(key), A.get(key)
            if not rb or not ra:
                continue
            ib = chk.judge(rb)[0]
            ia = chk.judge(ra)[0]
            if ib and not ia:
                pairs.append(key)
    print("# 逐页 before/after 证据（每条都是本机栈实测 DOM）\n")
    print("| # | 路由 | 角色 | 改前 | 改后 |")
    print("|---|---|---|---|---|")
    for i, (path, role) in enumerate(pairs, 1):
        rb, ra = B.get((path, role)), A.get((path, role))
        print("| %d | `%s` | %s | HTTP %s | HTTP %s |"
              % (i, path, role, (rb or {}).get("http"), (ra or {}).get("http")))
    print("")
    for i, (path, role) in enumerate(pairs, 1):
        rb, ra = B.get((path, role)), A.get((path, role))
        print("## %d. `%s`（%s）\n" % (i, path, role))
        print(line("改前", rb))
        print(line("改后", ra))
        if rb and ra:
            tb, _hb = block(rb)
            ta, _ha = block(ra)
            print("- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 %d）：改前 %d 字 → 改后 %d 字 ｜ 文本长度 改前 %d → 改后 %d ｜ records 改前 %s → 改后 %s"
                  % (chk.MIN_INFO, chk.info_len(tb), chk.info_len(ta), len(tb), len(ta),
                     rb.get("records"), ra.get("records")))
        print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())