#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拦一类**升级时才炸、且会整批回滚**的改动：被 xpath 扩展的模板被改成了「薄别名」。

## 为什么立它（2026-10-03 实测事故，非推演）

把 `edu_portal.edu_page`（门户外壳）下沉到 `edu_brand` 时，我按「上层留同名薄别名」的做法，
把 `edu_portal.edu_page` 改写成 6 行 `t-call`。升级**当场失败并整批回滚**：

    ParseError: 上级视图内找不到元素
      "<xpath expr="//aside[@id='b11-side']//a[@href='/web']">"
    View error context: {'name': '门户导航：课程编排入口', 'view': ir.ui.view(3710,) ...}

**原因**：`edu_page` **不是叶子模板** —— `edu_portal/views/curriculum.xml:217/:237` 两个视图
用 `inherit_id` + `xpath` 去它的 arch 里定位 `aside#b11-side` 与 `nav#b11-tabbar` 里的元素。
薄别名只有一条 `t-call`，**没有那些扩展点** ⇒ 子视图必然「找不到元素」。

⇒ **规则**：「定义下沉 + 上层留别名」**只对叶子模板成立**。
   凡被 `inherit_id` 扩展过的模板，改名/下沉必须**全局改调用点**，不能留别名。

## 判据（纯静态，不连库、不跑浏览器）

1. 认出「薄别名」模板 —— body 只有一条 `t-call`，形如
     `<template id="X"><t t-call="Y"/></template>`  或
     `<template id="X"><t t-call="Y"><t t-out="0"/></t></template>`；
2. 收集所有 `inherit_id="X"` 的视图；
3. 两者相交 ⇒ **红**（这个别名是个没有扩展点的空壳，升级会炸）。

退出码：0=OK ｜ 1=有冲突 ｜ 2=ENV（读不到 views 目录）——**2 不是通过**。

玩法：
    python3 scripts/check_alias_not_extended.py
    python3 scripts/check_alias_not_extended.py --selftest
"""
import argparse
import glob
import io
import re
import sys

# 只认「body 里没有别的元素」的：一条自闭合 t-call，或 t-call 包一个 t-out="0"。
ALIAS_SELF = re.compile(
    r'<template[^>]*\bid="([^"]+)"[^>]*>\s*'
    r'<t\s+t-call="([^"]+)"\s*/>\s*'
    r'</template>', re.S)
ALIAS_WRAP = re.compile(
    r'<template[^>]*\bid="([^"]+)"[^>]*>\s*'
    r'<t\s+t-call="([^"]+)">\s*<t\s+t-out="0"\s*/>\s*</t>\s*'
    r'</template>', re.S)
INHERIT = re.compile(r'inherit_id="([^"]+)"')


def scan(paths):
    aliases, kids = {}, {}
    for p in paths:
        raw = io.open(p, encoding="utf-8", errors="replace").read()
        mod = p.split("custom_addons/")[-1].split("/")[0]
        for rx in (ALIAS_SELF, ALIAS_WRAP):
            for tid, target in rx.findall(raw):
                aliases["%s.%s" % (mod, tid)] = (target, p)
        for parent in INHERIT.findall(raw):
            kids.setdefault(parent, []).append(p.split("custom_addons/")[-1])
    return aliases, kids


def selftest():
    """自证：造一个「薄别名 + 有人继承它」的最小样本，判据必须命中。"""
    a = '<odoo><template id="shell"><t t-call="other.shell"/></template></odoo>'
    b = '<odoo><template id="kid" inherit_id="mod.shell"><xpath expr="//div" position="before"/></template></odoo>'
    io.open("/tmp/_alias_a.xml", "w", encoding="utf-8").write(a)
    io.open("/tmp/_alias_b.xml", "w", encoding="utf-8").write(b)
    aliases, kids = {}, {}
    for p in ("/tmp/_alias_a.xml", "/tmp/_alias_b.xml"):
        raw = io.open(p, encoding="utf-8").read()
        mod = "mod"
        for rx in (ALIAS_SELF, ALIAS_WRAP):
            for tid, target in rx.findall(raw):
                aliases["%s.%s" % (mod, tid)] = (target, p)
        for parent in INHERIT.findall(raw):
            kids.setdefault(parent, []).append(p)
    hit = [k for k in aliases if k in kids]
    print("  自证：应命中 ['mod.shell'] 实得 %s" % hit)
    return 0 if hit == ["mod.shell"] else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        rc = selftest()
        print("RESULT=%s" % ("OK" if rc == 0 else "FAIL"))
        return rc
    paths = sorted(glob.glob("custom_addons/*/views/*.xml"))
    if not paths:
        print("SKIP-ENV：读不到任何 views xml —— 这不是通过")
        return 2
    aliases, kids = scan(paths)
    print("薄别名模板 %d 个 ｜ 被 inherit_id 引用的父模板 %d 个 ｜ 扫描 %d 个文件"
          % (len(aliases), len(kids), len(paths)))
    bad = [(k, aliases[k][0], aliases[k][1], kids[k]) for k in sorted(aliases) if k in kids]
    if not bad:
        print("RESULT=OK（没有「被继承的薄别名」）")
        return 0
    print("")
    print("=== ⛔ 薄别名却被 xpath 扩展（升级会炸「找不到元素」）===")
    for k, target, path, cs in bad:
        print("  %s  ->  %s" % (k, target))
        print("     定义于 %s" % path.replace("custom_addons/", ""))
        for c in cs:
            print("     被继承于 %s" % c)
    print("")
    print("RESULT=FAIL（%d 处）" % len(bad))
    return 1


if __name__ == "__main__":
    sys.exit(main())