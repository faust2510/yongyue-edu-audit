#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫「把 Odoo 记录集拿去和 None 比」—— search()/browse() **永远不返回 None**。

## 为什么立它（2026-10-03 实测踩到）

`edu_life/controllers/life.py` 的周记页：

```python
entry = Journal.search([("student_id", "=", student.id), ("week", "=", week_key)], limit=1)
if entry is None:                       # ← Odoo 返回的是【空记录集】，不是 None
    week_hint_text = "本周还没动笔……"     # ⇒ 这一支【永远进不去】
```

后果：**没写周记的学生被告知「老师已批阅，评语在正文之后」**——
同一页旁边的表单还写着「已写 0 字」，自相矛盾。实测：学生 5 有 W34/35/36/37/39，
今天 W40 无记录，页面却报「已批阅」。

正确写法是 Odoo 惯用的假值判断：`if not entry:`（空记录集为假）——
同函数上一行的 `can_edit = bool(not entry or ...)` 本来就是对写法，只有这一支写错了。

## 判据

静态：某变量在**赋值时**来自 `.search(` / `.browse(` / `.filtered(` / `.mapped(`，
随后 6 行内出现 `该变量 is [not] None` ⇒ 报红。

（`some_dict.get(x) is None`、`plain_value is None` 这类**不是**记录集的判断不会误报 ——
  判据要求赋值右侧确实出现 Odoo 的记录集 API。）

退出码：0=干净 ｜ 1=有 ｜ 2=ENV
"""
import glob
import io
import os
import re
import sys

ASSIGN = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")
SEARCHY = re.compile(r"\.(search|search_count|browse|filtered|mapped)\s*\(")
WINDOW = 6


def scan(repo="custom_addons"):
    hits = []
    for p in sorted(glob.glob(os.path.join(repo, "*", "**", "*.py"), recursive=True)):
        if "__pycache__" in p:
            continue
        try:
            lines = io.open(p, encoding="utf-8").read().split("\n")
        except Exception:
            continue
        # ⚠ 第一版用「6 行内」的窗口 ⇒ **真实代码里注释一多就漏报**：
        #   实文件里 `entry = ...search(` 与 `if entry is None` 中间隔着注释，距离 > 6 ⇒
        #   变量被移出窗口 ⇒ 反向注入后门禁**仍然报绿**（假绿；靠红测才发现）。
        # ⇒ 改为**按「重新赋值」失效**，不再看行距：只要该名字最近一次赋值来自记录集 API，
        #   之后任何 `X is None` 都算命中；一旦它被赋成别的东西就不再算。
        recent = {}
        for i, ln in enumerate(lines, 1):
            stripped = ln.lstrip()
            if stripped.startswith("#"):
                continue
            m = ASSIGN.match(ln)
            if m:
                var, rhs = m.group(1), m.group(2)
                if SEARCHY.search(rhs):
                    recent[var] = i
                else:
                    recent.pop(var, None)   # 被重新赋成非记录集 ⇒ 不再算
            for var, src in list(recent.items()):
                if re.search(r"\b%s\s+is\s+(not\s+)?None\b" % re.escape(var), ln):
                    hits.append((p, i, src, var, stripped[:88]))
    return hits


def selftest():
    """按判据造两段样本：坏写法要被抓到，好写法不能误报。"""
    import tempfile
    bad = "rec = env['x'].search([])\nif rec is None:\n    pass\n"
    good = "rec = env['x'].search([])\nif not rec:\n    pass\n"
    plain = "d = {}\nif d.get('k') is None:\n    pass\n"
    ok = True
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "mod"), exist_ok=True)
        for name, src, want in (("bad.py", bad, True), ("good.py", good, False), ("plain.py", plain, False)):
            q = os.path.join(d, "mod", name)
            io.open(q, "w", encoding="utf-8").write(src)
        got = {os.path.basename(p): True for p, *_ in scan(d)}
        for name, _, want in (("bad.py", bad, True), ("good.py", good, False), ("plain.py", plain, False)):
            if bool(got.get(name)) != want:
                print("  SELFTEST FAIL：%s 期望被%s、实际%s" % (name, "抓" if want else "放过", "抓到" if got.get(name) else "放过"))
                ok = False
    print("  selftest %s" % ("通过（坏写法被抓、好写法与普通 dict 判断不误报）" if ok else "未通过"))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    hits = scan()
    print("  「记录集与 None 比较」%d 处" % len(hits))
    for p, i, src, var, txt in hits:
        print("     %s:%d  (%s 来自第 %d 行)" % (p.replace("custom_addons/", ""), i, var, src))
        print("        %s" % txt)
    if hits:
        print("RESULT=FAIL（记录集永远不是 None，请改用 `if not rec:`）")
        return 1
    print("RESULT=OK（没有把记录集与 None 比较的写法）")
    return 0


if __name__ == "__main__":
    sys.exit(main())