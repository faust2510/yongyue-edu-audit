#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找「带对象 id 的写路由，但看不到归属校验」—— 写侧越权（write-IDOR）的检索入口。

**为什么立它**（2026-10-04 第 85 轮）：
  第 84 轮给越权探针补了对象级**读**路由（附件/证明），但那只覆盖 GET ——
  真正严重的是**写**：一个学生若能 POST 别人的 id 改掉别人的数据，后果比「看到了」大得多。
  写路由没法像读那样用探针打（打成功就等于真改了数据），所以改成**静态检索**：
  把「带 <int:...> 的 POST 路由」列出来，标出**正文里看不到任何归属校验痕迹**的那些，交人复核。

判据（只做文本判断，**报告型**，不是门禁）：
  · 路由装饰器里 methods 含 POST，且路径里有 `<int:...>`；
  · 处理函数正文里**没有**出现下列任一「像归属校验」的痕迹：
    current_student / current_faculty / _own_ / _teacher_ / _guard_ /
    `.student_id` / `.faculty_id` / `.user_id` / `partner_id` / `.sudo().browse` 后跟比较；
  · 两条都成立 ⇒ 列出来。**很可能有假阳性**（守卫可能抽到别的函数里、或用别的写法）。

⚠ 不要拿它当结论 —— 它只负责「把需要人读一遍的地方找出来」。

## 首轮实测：15 条候选，手读了 3 条，**全部是假阳性**（2026-10-04 第 85 轮）

| 候选 | 实际守卫 | 判定 |
|---|---|---|
| `/my/courses/<id>/rep/notify`、`rep/leave/set_state`、`rep/attendance` | `_rep_slot_of(subject)`，且注释写明「服务端**重新判定**（不信前端）：在任 + 严格同课程 + 非本人 + 出勤类；任一条不成立 ⇒ 按不存在处理，**不写任何字段**（含直接 POST 重放）」 | ✅ 守得很严 |
| `/my/evaluation/task/<id>/save`（两处同名） | **不是重复注册** —— `eval_compat.py` 是**继承** `EvalPortal` 的 303 兼容层，用 Odoo 的 leaf 覆盖机制接管旧地址；docstring 甚至写明「不用同名路由各写一遍」的理由，并指向 `check_view_xpath.py` 规则 5 | ✅ 有意为之 |
| `/downloads/ack/<fid>/save` | `_can_download(rec)` | ✅ 有守卫 |

**根因（值得记住）**：这个仓的守卫**习惯抽成 helper**（`_rep_slot_of` / `_can_download` /
`_registrar` / `_own_*` / `_teacher_*`）⇒ **按函数名猜守卫的文本扫描天然低精度**。
真正该做的是**读那一段代码**，不是扩充关键词表（关键词表永远补不全）。
因此本工具**不接进 check_all**，只作为「换个角度把需要读的地方列出来」的入口。

用法：find_unguarded_write_routes.py [--all]   （--all 连有守卫痕迹的也列）
退出码：0=跑完（有发现也 0）
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS = os.path.join(ROOT, "custom_addons")

ROUTE_RE = re.compile(r"@http\.route\((?P<args>.*?)\)\s*\n(?P<body>.*?)(?=@http\.route|\Z)",
                      re.S)
GUARD_HINTS = ("current_student", "current_faculty", "_own_", "_teacher_",
               "_guard_", "privileged_staff", ".student_id", ".faculty_id",
               ".user_id", ".partner_id", ".create_uid")


def iter_routes():
    for dirpath, _dirs, files in os.walk(ADDONS):
        if "controllers" not in dirpath:
            continue
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            text = open(path, encoding="utf-8").read()
            for m in ROUTE_RE.finditer(text):
                yield path, m.group("args"), m.group("body")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    total = idpost = unguarded = 0
    rows = []
    for path, args, body in iter_routes():
        total += 1
        flat = re.sub(r"\s+", " ", args)
        m = re.search(r"[\'\"]([^\'\"]*<int:[^\'\"]+)[\'\"]", flat)
        if not m:
            continue
        route = m.group(1)
        is_post = "POST" in flat
        if not is_post:
            continue
        idpost += 1
        fn = re.search(r"def (\w+)", body)
        head = body[:2200]
        guarded = [h for h in GUARD_HINTS if h in head]
        if not guarded:
            unguarded += 1
            rows.append((os.path.relpath(path, ROOT), route,
                         fn.group(1) if fn else "?"))
        elif a.all:
            rows.append((os.path.relpath(path, ROOT), route,
                         (fn.group(1) if fn else "?") + "  [有痕迹: %s]" % ",".join(guarded[:3])))
    print("扫了 %d 条路由；其中**带 id 的 POST 写路由** %d 条；" % (total, idpost))
    print("**正文里看不到归属校验痕迹**的 %d 条：" % unguarded)
    for p, r, f in rows:
        print("  · %-46s %-44s %s" % (r[:46], f[:44], p))
    print("（报告型：守卫可能抽到别的函数里 ⇒ 有假阳性，**要人读一遍**，不要当结论。）")
    return 0


if __name__ == "__main__":
    sys.exit(main())