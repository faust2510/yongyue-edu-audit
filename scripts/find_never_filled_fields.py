#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找「模板渲染了、但库里从来没被填过」的字段 —— 第 70 轮那个发现的通用化。

**为什么立它**（2026-10-04 第 78 轮）：
  第 70 轮查作业闭环时发现：提交名单页一直显示「得分 0.0」，而**全仓没有任何地方写**
  `op.assignment.sub.line.marks` ⇒ 那个字段永远是默认值，页面上那一列是死的。
  那一次是人工挖出来的。这条规律可以机械查：**有行、但该字段所有行都是空/默认值**，
  而它又**出现在 QWeb 模板里**（说明有人会看到它）⇒ 几乎可以断定是「没人写」的死字段。

判据（两步，都只看事实）：
  ① 库里：该模型有行，且该字段**非空/非默认的行数为 0**；
  ② 代码里：字段名出现在 `custom_addons/**/views/*.xml` 的 QWeb 表达式里。
  两条同时成立 ⇒ 报出来（**报告型**：也可能是「本来就可选、恰好没数据」，需人判断）。

⚠ **精度有限，别当门禁用**（首次全量的 14 条里多数是可选项）：
  · 第 ② 步只按字段名匹配模板 ⇒ `name`/`title`/`role` 这类**通用名**会命中无关模板（假阳性）；
  · 「全空」也可能是「本来就可选、恰好没数据」（如 `note`/`help`/`date_due`）。
  真正的信号是**那些业务上必须有人填、却一条都没有的字段** —— 第 70 轮的
  `op.assignment.sub.line.marks` 就是这一类（页面当成绩显示、却没人写）。
  所以本工具**不接进 check_all**，只作为「换个角度看数据」的检索入口。

⚠ 本机踩过的三个坑（别再走一遍）：
  1. `docker cp` 在这台机器上**不可靠** —— Python 调、甚至经 `sh -c` 调，都稳定报
     「Could not find the file /tmp/fd in container」（同样的命令手敲 shell 却是好的）。
     ⇒ 改用**容器已挂载**的目录（`custom_addons` → `/mnt/custom-addons`），零拷贝。
  2. `env.registry.items()` 给的是**模型类**，类上没有 `.sudo()` ⇒ 会静默全跳过。用 `env[mname]`。
  3. Odoo 19 的 `Field` 上**没有** `.automatic`；判「有没有被填过」也不能把
     `!=False`/`!=""`/`!=0` 三个条件 AND 在一起（每种类型都会抛，再被 except 吞掉）——
     要**按类型各给一条**。Odoo 里空字符串就是 NULL，`!= False` 一条就够。

用法：find_never_filled_fields.py [--json]
退出码：0=正常跑完（有发现也返回 0 —— 报告型工具，不是门禁）；2=ENV
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTAINER = os.environ.get("EDU_WEB", "edu19-clone-web-1")
DB = os.environ.get("EDU_DB", "edu19")
VIEWS = os.path.join(ROOT, "custom_addons")

PROBE = """
import json
res = []
scanned = 0
for mname in sorted(env.registry):
    if not mname.startswith(("edu.", "op.")):
        continue
    try:
        model = env[mname].sudo()
        n = model.search_count([])
    except Exception:
        continue
    if not n:
        continue
    for fname, f in model._fields.items():
        try:
            if f.compute or f.related:
                continue
            ftype = f.type
        except Exception:
            continue
        if ftype not in ("float", "integer", "char", "text", "date", "datetime",
                         "selection", "many2one", "boolean"):
            continue
        if fname.startswith(("create_", "write_", "__")):
            continue
        try:
            if ftype == "boolean":
                filled = model.search_count([(fname, "=", True)])
            elif ftype in ("float", "integer"):
                filled = model.search_count([(fname, "!=", 0)])
            elif ftype == "selection":
                sel = [k for k, _ in (f.selection or [])]
                filled = model.search_count([(fname, "in", sel)]) if sel else 0
            else:
                filled = model.search_count([(fname, "!=", False)])
        except Exception:
            continue
        scanned += 1
        if filled == 0:
            res.append({"model": mname, "field": fname, "rows": n, "type": ftype,
                        "string": f.string or fname})
print("NFF_SCANNED=%d" % scanned)
print("NFF_JSON>>>")
print(json.dumps(res, ensure_ascii=False))
print("<<<NFF_JSON")
"""


def probe_db():
    """把探针写进**已挂载**的 custom_addons/，用挂载路径在容器里跑，跑完删掉。"""
    mounted = os.path.join(VIEWS, "_nff_probe.py")
    with open(mounted, "w", encoding="utf-8") as fh:
        fh.write(PROBE)
    try:
        r = subprocess.run(
            ["docker", "exec", "-i", "-u", "0", CONTAINER, "sh", "-c",
             "cd /mnt && odoo shell -d %s --db_host=db --db_user=odoo "
             "--db_password=odoo --no-http --log-level=error "
             "< /mnt/custom-addons/_nff_probe.py" % DB],
            capture_output=True, text=True)
    finally:
        if os.path.exists(mounted):
            os.unlink(mounted)
    m = re.search(r"NFF_JSON>>>\s*(\[.*?\])\s*<<<NFF_JSON", r.stdout, re.S)
    if not m:
        return None, None, "没取到结果：%s" % ((r.stderr or r.stdout)[-220:])
    sc = re.search(r"NFF_SCANNED=(\d+)", r.stdout)
    return json.loads(m.group(1)), (int(sc.group(1)) if sc else -1), None


def template_hits(field):
    """字段名是否出现在 views/*.xml 的 QWeb 表达式里。"""
    hits = []
    pat = re.compile(r"\b%s\b" % re.escape(field))
    for dirpath, _dirs, files in os.walk(VIEWS):
        if "views" not in dirpath:
            continue
        for fn in sorted(files):
            if not fn.endswith(".xml"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                text = open(path, encoding="utf-8").read()
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if not any(k in line for k in ("t-out", "t-esc", "t-if", "t-att")):
                    continue
                if pat.search(line):
                    hits.append("%s:%d" % (os.path.relpath(path, ROOT), i))
                    break
            if len(hits) >= 2:
                break
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows, scanned, err = probe_db()
    if err:
        print("ENV：%s" % err)
        return 2
    found = []
    for r in rows:
        hits = template_hits(r["field"])
        if hits:
            r["where"] = hits
            found.append(r)
    if a.json:
        print(json.dumps(found, ensure_ascii=False, indent=1))
        return 0
    print("共扫了 %d 个字段；其中「有行但全空」%d 个，**在模板里被渲染**的 %d 个："
          % (scanned, len(rows), len(found)))
    for r in sorted(found, key=lambda x: (-x["rows"], x["model"])):
        print("  · %-34s %-22s (%s) 行=%-5d 出现在 %s" % (
            r["model"], r["field"], r["type"], r["rows"], r["where"][0]))
    print("（报告型：也可能是「本来就可选、恰好没数据」—— 需人判断，不自动算红。）")
    return 0


if __name__ == "__main__":
    sys.exit(main())