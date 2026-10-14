#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PO 文件健全性门禁（离线、纯 Python，不依赖 gettext）。

## 为什么立它（2026-10-02 的实测缺陷）

`edu_zh/i18n_extra/zh_CN.po` 与 `zh_TW.po` 各有 **3 处重复 msgid**（`General` 写两遍、
`Closed`/`In Progress` 各两遍）—— `msgfmt --check` 判 **fatal**。
两处译文当时一致，所以**行为上看不出来**；但这正是最难查的一类：
一旦有人只改其中一份，「哪份生效」就变成**按文件顺序**的隐式行为，静默且无提示。

⇒ 判据只取一种、且是客观的：**同一个 (msgctxt, msgid) 在一个文件里出现两次以上 = 红**。

## 为什么不直接调 msgfmt

msgfmt 属 gettext，**不保证每台机器/每个 CI 都有**；门禁一旦依赖外部命令，
在缺失的机器上就会「跳过」或「崩」，两种都不是「通过」。故这里自己解析 PO ——
只做重复检测这一件事，不追求完整 PO 语义。

退出码：0=OK ｜ 1=发现重复 ｜ 2=环境未就绪（找不到任何 .po）——**2 不是通过**。

玩法：
    python3 scripts/check_po_sanity.py
    python3 scripts/check_po_sanity.py --selftest
"""
import argparse
import glob
import io
import re
import sys

CONT = re.compile(r'^"(.*)"$|^"(.*)"\s*$')


def parse(path):
    """返回 [(msgctxt, msgid, lineno)]。只认顶层条目，够用即止。"""
    entries = []
    cur_ctx, cur_id, cur_ln = None, None, None
    mode = None
    for i, raw in enumerate(io.open(path, encoding="utf-8", errors="replace"), 1):
        line = raw.rstrip("\n")
        s = line.strip()
        if s.startswith("#") or s == "":
            continue
        if s.startswith("msgctxt "):
            cur_ctx, mode = s[8:].strip().strip('"'), "ctx"
        elif s.startswith("msgid "):
            if cur_id is not None:
                entries.append((cur_ctx, cur_id, cur_ln))
            cur_id, cur_ln, mode = s[6:].strip().strip('"'), i, "id"
        elif s.startswith("msgstr "):
            mode = "str"
        elif s.startswith('"'):
            # 续行：拼到当前字段（这里只需 msgid 的内容，用于去重键）
            frag = s.strip('"')
            if mode == "id" and cur_id is not None:
                cur_id += frag
            elif mode == "ctx" and cur_ctx is not None:
                cur_ctx += frag
    if cur_id is not None:
        entries.append((cur_ctx, cur_id, cur_ln))
    return entries


def check(files):
    problems = []
    for p in files:
        seen = {}
        for ctx, mid, ln in parse(p):
            if mid == "":
                continue          # PO 头部
            key = (ctx or "", mid)
            if key in seen:
                problems.append((p, seen[key], ln, mid))
            else:
                seen[key] = ln
    return problems


def selftest():
    """自证：造一个含重复条目的 PO，必须报红；去掉重复必须转绿。"""
    import tempfile, os
    body = 'msgid ""\nmsgstr ""\n"Language: zh_CN\\n"\n\nmsgid "A"\nmsgstr "甲"\n\nmsgid "A"\nmsgstr "甲"\n'
    fd, path = tempfile.mkstemp(suffix=".po")
    os.write(fd, body.encode("utf-8"))
    os.close(fd)
    red = len(check([path]))
    clean = body.replace('msgid "A"\nmsgstr "甲"\n\nmsgid "A"\nmsgstr "甲"', 'msgid "A"\nmsgstr "甲"')
    os.write(fd, clean.encode("utf-8")) if False else None
    io.open(path, "w", encoding="utf-8").write(clean)
    green = len(check([path]))
    os.unlink(path)
    print("  自证：注入重复 → %d 条（应 >0）；去掉重复 → %d 条（应 0）" % (red, green))
    return 0 if (red > 0 and green == 0) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        rc = selftest()
        print("RESULT=%s" % ("OK" if rc == 0 else "FAIL"))
        return rc
    files = sorted(glob.glob("custom_addons/**/*.po", recursive=True))
    if not files:
        print("SKIP-ENV：一个 .po 都没找到 —— 这不是通过")
        return 2
    problems = check(files)
    print("扫描 %d 个 PO 文件" % len(files))
    if problems:
        for p, first, again, mid in problems:
            print("  重复 msgid：%s  第 %d 行与第 %d 行  msgid=%r" % (p, first, again, mid[:48]))
        print("RESULT=FAIL（%d 处重复）" % len(problems))
        return 1
    print("RESULT=OK（0 处重复）")
    return 0


if __name__ == "__main__":
    sys.exit(main())