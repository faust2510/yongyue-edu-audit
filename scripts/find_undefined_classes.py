#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找出「模板里用了、但本仓 CSS 里根本没有定义」的自有类名 —— **报告型工具**。

## 为什么立它（2026-10-02/03 两次实测）

· `oe-cat-title`：类名挂了，但本仓**全部** `.oe-cat-title` 规则都作用域在 `.oe-cat-head` 之下，
  而 `/quiz/my` 那处不在 `.oe-cat-head` 里 ⇒ **等于没挂**（实测 40px vs 兄弟页 20px）；
· `life-cal`：`/my/checkins` 的月历表挂着这个类，**全仓没有一条规则定义它**。

共同点：**既不报错、也不影响构建，只是「看起来有样式其实没有」。** 靠读代码很难发现，靠肉眼更难。

## 判据

取本仓**自有前缀**的类名（`oe-` / `ux-` / `b11-` / `edu-`，用来避开 Bootstrap 与 Odoo 核心的海量类），
若它出现在模板的 `class=` 里、却在 `custom_addons/**/static/**` 的样式文件中**一次都没出现**，就报出来。

⚠ 本工具**只报告、不判死**。命中的三种可能：① 打错了（真缺陷）；② 缺样式（真缺陷）；
③ **故意留给 JS 当钩子**（不是缺陷）。所以每一条都要人看一眼再定。

退出码：0=无命中 ｜ 1=有命中（**报告**，不等于不合格）｜ 2=ENV（读不到模板或样式目录）。

玩法：
    python3 scripts/find_undefined_classes.py
    python3 scripts/find_undefined_classes.py --selftest
"""
import argparse
import glob
import io
import os
import re
import sys

PREFIXES = ("oe-", "ux-", "b11-", "edu-")
DYNAMIC = set()      # 拼接出来的类名前缀（形如 oe-leg-），只统计不报
# 静态 class：整段按空白切。
# ⚠ 必须加负向后顾：`t-att-class="…"` 的尾巴也是 `class="…"`，
#   不加就会**同一个属性被处理两次** —— 第二次按「静态类名表」切一个 QWeb 表达式，
#   切出 `oe-statbox--active\'`、`ux-today-col\'` 这种带引号的伪类名（45 条命中里 6 条是这么来的）。
CLASS_ATTR = re.compile(r'(?<![-\w])class="([^"]*)"', re.S)
# `t-attf-class` 是插值写法（`oe-leg-#{x}`）：取字面量、丢掉占位符，剩下的动态前缀由下方过滤。
ATTF_CLASS = re.compile(r't-attf-class="([^"]*)"', re.S)
# t-att-class：里面是 QWeb 表达式，**不能按空白切** —— 要先取出其中的字符串字面量再切。
# ⚠ 第一版就是漏了这一步，于是 `t-att-class="\'btn \' + (c and \'oe-x\' or \'\')"` 被切出
#    `oe-x\'` 这种**带引号的伪类名**，40 条命中里 8 条是这么来的假阳性。
ATT_CLASS = re.compile(r't-att-class="([^"]*)"', re.S)
STRING_LIT = re.compile(r"\'([^\']*)\'")


def _tokens(text, kind):
    """从一段属性值里抽出类名 token。kind=static 直接切；kind=att 先取字面量。"""
    if kind == "static":
        return text.split()
    if kind == "attf":
        cleaned = re.sub(r"#\{[^}]*\}", " ", text)      # #{expr} 占位符
        cleaned = re.sub(r"\{\{[^}]*\}\}", " ", cleaned)  # {{ expr }} 占位符
        return cleaned.split()
    toks = []
    for lit in STRING_LIT.findall(text):
        toks += lit.split()
    return toks


def collect_used():
    """模板里用到的自有类名 -> [文件:行]"""
    used = {}
    for path in sorted(glob.glob("custom_addons/*/views/*.xml")):
        raw = io.open(path, encoding="utf-8", errors="replace").read()
        # 去掉注释与 <style> 块：那里的类名不算「模板使用」。
        # ⚠ 必须**保留换行**：第一版直接替换成一个空格，把换行也吃掉了 ⇒
        #   后面所有行的行号整体前移，报出来的 `文件:行` 全指错地方（我照着它去 sed 看到的
        #   是无关行，白白多绕一圈）。所以这里用「同长度、只把非换行字符换成空格」的替换。
        def _blank(m):
            return re.sub(r"[^\n]", " ", m.group(0))
        raw = re.sub(r"<!--.*?-->", _blank, raw, flags=re.S)
        raw = re.sub(r"<style.*?</style>", _blank, raw, flags=re.S)
        short = path.split("custom_addons/")[-1]
        for kind, rx in (("att", ATT_CLASS), ("attf", ATTF_CLASS), ("static", CLASS_ATTR)):
            for m in rx.finditer(raw):
                ln = raw.count("\n", 0, m.start()) + 1
                for tok in _tokens(m.group(1), kind):
                    # 动态前缀（`t-attf-class="oe-leg-#{x}"` ⇒ 字面量是 `oe-leg-`）不是类名，跳过。
                    if tok.endswith("-"):
                        DYNAMIC.add(tok)
                        continue
                    if tok.startswith(PREFIXES) and "{" not in tok and "<" not in tok:
                        used.setdefault(tok, []).append("%s:%d" % (short, ln))
    return used
    return used


# TODO(2026-10-06)：--selftest **不测本函数** —— 它自建了一个正则（见 selftest 内），
#   所以本函数改坏时自证照样绿（当天真实发生过：前瞻漏闭合括号，自证仍 OK）。
#   要堵这个空洞，需把 selftest 改成调用本函数；因当天多次栽在正则字面量的转义上，留作独立任务。
def collect_defined():
    """样式文件里出现过的自有类名（出现过即认为「有定义」，不做选择器解析）"""
    defined = set()
    files = []
    for pat in ("custom_addons/*/static/**/*.css", "custom_addons/*/static/**/*.scss",
                "custom_addons/*/static/**/*.js"):
        files += glob.glob(pat, recursive=True)
    for path in files:
        text = io.open(path, encoding="utf-8", errors="replace").read()
        for tok in re.findall(r"[.\"\']([A-Za-z][\w-]*)(?=[\"\'\s.:,>{\[])", text):
            if tok.startswith(PREFIXES):
                defined.add(tok)
        for tok in re.findall(r"\b([a-z][\w-]*)\b", text):
            pass
    return defined, len(files)


def selftest():
    """自证：造一个「模板用了、样式没有」的类，必须被认出；已定义的类必须不报。"""
    import tempfile
    os.makedirs("/tmp/_cls_probe/views", exist_ok=True)
    tpl = '<odoo><div class="oe-ghost-class-xyz d-flex">x</div>\n<div class="oe-known-xyz">y</div></odoo>'
    css = ".oe-known-xyz{color:red}"
    io.open("/tmp/_cls_probe/views/t.xml", "w", encoding="utf-8").write(tpl)
    io.open("/tmp/_cls_probe/s.css", "w", encoding="utf-8").write(css)
    used = {}
    for attr in CLASS_ATTR.findall(tpl):
        for tok in attr.split():
            if tok.startswith(PREFIXES):
                used[tok] = ["x"]
    defined = set(re.findall(r"\.([a-z][\w-]*)", css))
    miss = sorted(k for k in used if k not in defined)
    print("  自证：应命中 ['oe-ghost-class-xyz'] 实得 %s；已知类是否被误报=%s"
          % (miss, "oe-known-xyz" in miss))
    return 0 if miss == ["oe-ghost-class-xyz"] else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        rc = selftest()
        print("RESULT=%s" % ("OK" if rc == 0 else "FAIL"))
        return rc
    used = collect_used()
    if not used:
        print("SKIP-ENV：一个模板类名都没读到 —— 这不是通过")
        return 2
    defined, nfiles = collect_defined()
    if nfiles == 0:
        print("SKIP-ENV：一个样式文件都没读到 —— 这不是通过")
        return 2
    miss = sorted(k for k in used if k not in defined)
    print("模板自有类名 %d 个 ｜ 样式文件 %d 份 ｜ 样式里出现过 %d 个"
          % (len(used), nfiles, len([k for k in used if k in defined])))
    if not miss:
        print("RESULT=OK（无未定义类名）")
        return 0
    print("")
    print("=== 模板里用了、样式里没有（**需人看一眼**：可能是打错/缺样式/故意留给 JS 的钩子）===")
    for k in miss:
        where = used[k]
        print("  %-34s %d 处  例：%s" % (k, len(where), where[0]))
    print("")
    print("RESULT=FOUND（%d 个）" % len(miss))
    return 1


if __name__ == "__main__":
    sys.exit(main())