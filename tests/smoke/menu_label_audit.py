#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台菜单/动作/字段标签读数器 —— 改名任务的 before/after 逐条对照证据 + 可重跑。

为什么单独写一个（不复用 tests/smoke/department_path.py）：
  department_path.py 验的是**一条路径走通**（菜单→动作→视图→真浏览器新建）；
  本脚本验的是**一批标签的字面值**，且必须一次读全两类口径：
    · 受影响集（本次要改的菜单/动作/字段）
    · 回归对照集（不该被改坏的邻居 + 与本次共享 msgid 的旁证字段）
  读数一律经 ORM（lang=zh_CN / en_US 各读一次），因为 complete_name 是计算字段，SQL 直读不到。
  ⚠ 口径：**只看 HTTP 200 不算数**，这里读的是渲染上游的真实字段值。

用法：
  python3 tests/smoke/menu_label_audit.py --out tests/smoke/menu_label_audit_before.json
  python3 tests/smoke/menu_label_audit.py --out tests/smoke/menu_label_audit_after.json
  python3 tests/smoke/menu_label_audit.py --diff before.json after.json    # 逐条对照
退出码：0 读数成功（--diff 时 0 = 与预期一致）；2 环境不可用。

预期（改后）在 EXPECT 里写死，--diff 会逐条判 PASS/FAIL，便于当门禁用。
"""
import argparse
import json
import os
import sys

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

import xmlrpc.client  # noqa: E402

BASE = os.environ.get("MLA_BASE", "http://localhost:8069")
DB = os.environ.get("MLA_DB", "edu19")
USER = os.environ.get("MLA_USER", "admin")
PWD = os.environ.get("MLA_PWD", "admin")

# ---- 受影响集：本次要改的记录（改后逐条核对） ----
MENUS = [
    # (menu_id, xmlid, 说明)
    (276, "openeducat_core.menu_op_program_sub", "P1 op.program 菜单（原「专业」，与 263 撞名）"),
    (264, "openeducat_core.menu_op_batch_sub", "P2 op.batch 菜单（原「批次」）"),
    (298, "openeducat_parent.menu_op_school_config_parent", "P2 家长配置容器（原「父母」）"),
    (299, "openeducat_parent.menu_op_parent_relationship_sub_parent", "P2 op.parent.relationship 菜单（原「人际关系」）"),
    (297, "openeducat_parent.menu_op_parent_root", "P2 op.parent 菜单（应为「家长」，noupdate=t）"),
    # ---- 回归对照集：不得一字变动 ----
    (263, "openeducat_core.menu_op_course_sub", "回归：专业（op.course，唯一）"),
    (265, "openeducat_core.menu_op_department_sub", "回归：院系部门（上一轮刚改）"),
    (259, "openeducat_core.menu_op_faculty_main", "回归：教职员工（上一轮刚改）"),
    (257, "openeducat_core.menu_op_school_root", "回归：学生信息"),
    (261, "openeducat_core.menu_op_school_config", "回归：配置"),
    (262, "openeducat_core.menu_op_school_config_course", "回归：教学管理"),
    (266, "openeducat_core.menu_op_subject_root", "回归：学科管理"),
    (267, "openeducat_core.menu_op_subject_sub", "回归：科目"),
    (273, "openeducat_core.menu_op_academic_year_sub", "回归：学年"),
    (274, "openeducat_core.menu_op_academic_term_sub", "回归：学期"),
    (277, "openeducat_core.menu_op_program_level_sub", "回归：学制"),
    (279, "openeducat_core.menu_op_student_main_student", "回归：档案"),
    (280, "openeducat_core.menu_op_general_student", "回归：通用"),
    (287, "openeducat_activity.menu_student_migrate", "回归：学生转班"),
    (291, "openeducat_assignment.menu_op_assignment_sub_line_sub", "回归：作业提交"),
    (343, "openeducat_timetable.menu_student_session_main", "回归：会议"),
    (612, None, "回归：选课审批（无 zh 槽位，靠回退）"),
    (797, None, "回归：已停用班级"),
]

ACTIONS = [
    (395, "openeducat_core.act_open_op_program_view", "P1 op.program 动作"),
    (386, "openeducat_core.act_open_op_batch_view", "P2 op.batch 动作"),
    (415, "openeducat_parent.act_open_op_parent_relationship_view", "P2 op.parent.relationship 动作"),
    (414, "openeducat_parent.act_open_op_parent_view", "P2 op.parent 动作（原「父母」，与菜单 297「家长」不一致）"),
    # ---- 回归对照 ----
    (380, "openeducat_core.act_open_op_department_view", "回归：院系部门动作"),
    (385, "openeducat_core.act_open_op_course_view", "回归：专业动作"),
    (388, "openeducat_core.act_open_op_faculty_view", "回归：教职员工动作"),
    (393, "openeducat_core.act_open_op_academic_year_view", "回归：学年动作"),
    (396, "openeducat_core.act_open_op_program_level_view", "回归：学制动作"),
    (705, "openeducat_slide.act_open_slide_channel_view", "回归：在线课程动作（共享 Courses msgid 的旁证）"),
    (815, None, "回归：已停用班级动作"),
]

# ---- 与本次共享 msgid 的旁证字段：证明新串隔离了影响面 ----
FIELDS = [
    ("op.department", "parent_id", "P0 目标字段（原「家长部」）"),
    ("op.course", "department_id", "旁证：仍应是「部门」（非新串可波及处）"),
    ("op.program", "department_id", "旁证：仍应是「部门」"),
    ("op.subject", "department_id", "旁证：仍应是「部门」"),
    ("op.department", "name", "P0b 同表单补漏：Name 的专业译名应是「名称」而非「姓名」"),
    ("op.department", "code", "旁证：代码"),
]


def dump():
    common = xmlrpc.client.ServerProxy(BASE + "/xmlrpc/2/common")
    uid = common.authenticate(DB, USER, PWD, {})
    if not uid:
        print("FATAL | 登录失败 %s@%s/%s" % (USER, BASE, DB))
        sys.exit(2)
    models = xmlrpc.client.ServerProxy(BASE + "/xmlrpc/2/object")

    def rd(model, ids, fields, lang):
        if not ids:
            return []
        return models.execute_kw(DB, uid, PWD, model, "read", [ids, fields],
                                 {"context": {"lang": lang}})

    out = {"base": BASE, "db": DB, "menus": {}, "actions": {}, "fields": {},
           "named_专业": [], "notes": []}

    want_menu_ids = [m[0] for m in MENUS]
    for lang in ("zh_CN", "en_US"):
        rows = {r["id"]: r for r in rd("ir.ui.menu", want_menu_ids,
                                       ["name", "complete_name", "active", "parent_id"], lang)}
        for mid, xmlid, why in MENUS:
            out["menus"].setdefault(str(mid), {})[lang] = {
                "xmlid": xmlid, "why": why,
                "name": rows.get(mid, {}).get("name"),
                "complete_name": rows.get(mid, {}).get("complete_name"),
                "active": rows.get(mid, {}).get("active"),
            }
    want_act_ids = [a[0] for a in ACTIONS]
    for lang in ("zh_CN", "en_US"):
        rows = {r["id"]: r for r in rd("ir.actions.act_window", want_act_ids,
                                       ["name", "res_model"], lang)}
        for aid, xmlid, why in ACTIONS:
            out["actions"].setdefault(str(aid), {})[lang] = {
                "xmlid": xmlid, "why": why,
                "name": rows.get(aid, {}).get("name"),
                "res_model": rows.get(aid, {}).get("res_model"),
            }
    for model, fname, why in FIELDS:
        ids = models.execute_kw(DB, uid, PWD, "ir.model.fields", "search",
                                [[["model", "=", model], ["name", "=", fname]]])
        for lang in ("zh_CN", "en_US"):
            rows = {r["id"]: r for r in rd("ir.model.fields", ids, ["field_description"], lang)}
            key = "%s.%s" % (model, fname)
            out["fields"].setdefault(key, {})[lang] = {
                "why": why,
                "label": next(iter(rows.values()), {}).get("field_description"),
            }
    # 唯一性审计：所有名字叫「专业」的菜单（含停用）
    ids = models.execute_kw(DB, uid, PWD, "ir.ui.menu", "search", [[["name", "=", "专业"]]],
                            {"context": {"lang": "zh_CN"}})
    rows = rd("ir.ui.menu", ids, ["name", "complete_name", "active"], "zh_CN")
    out["named_专业"] = [{"id": r["id"], "complete_name": r["complete_name"],
                          "active": r["active"]} for r in rows]
    return out


# 改后预期（--diff 用；键 = 记录键，值 = (zh_CN, en_US)）
EXPECT = {
    "menus": {
        "276": ("培养方案", "Program Plans"),
        "264": ("班级", "Student Batches"),
        "298": ("家长设置", "Parent Settings"),
        "299": ("亲属关系", "Kinship Relations"),
        "297": ("家长", "Parents"),
    },
    "actions": {
        "395": ("培养方案", "Program Plans"),
        "386": ("班级", "Student Batches"),
        "415": ("亲属关系", "Kinship Relations"),
        "414": ("家长", "Parents"),
    },
    "fields": {
        "op.department.parent_id": ("上级院系", "Parent Department"),
        "op.department.name": ("名称", "Name"),
        "op.course.department_id": ("部门", "Department"),
        "op.program.department_id": ("部门", "Department"),
        "op.subject.department_id": ("部门", "Department"),
    },
}


def do_diff(before_path, after_path):
    b = json.load(open(before_path, encoding="utf-8"))
    a = json.load(open(after_path, encoding="utf-8"))
    fails = []

    # 菜单/动作读的是 name，字段读的是 field_description（label）
    SCALAR = {"menus": "name", "actions": "name", "fields": "label"}

    def scalar(sec, entry, lang):
        return entry[lang].get(SCALAR[sec])

    def chk(tag, want_zh, want_en, got_zh, got_en):
        ok = (got_zh == want_zh) and (got_en == want_en)
        print("%-4s | %-44s | zh %-10s en %-22s (期望 %s / %s)"
              % ("PASS" if ok else "FAIL", tag, got_zh, got_en, want_zh, want_en))
        if not ok:
            fails.append(tag)
        return ok

    print("===== 受影响项：改前 → 改后（逐条期望） =====")
    for sec in ("menus", "actions", "fields"):
        for key, (want_zh, want_en) in EXPECT[sec].items():
            bf, af = b[sec][key], a[sec][key]
            chk("%s[%s] %s→%s" % (sec, key, scalar(sec, bf, "zh_CN"), scalar(sec, af, "zh_CN")),
                want_zh, want_en, scalar(sec, af, "zh_CN"), scalar(sec, af, "en_US"))

    print("\n===== 回归对照：改前后必须一字不差 =====")
    for sec in ("menus", "actions", "fields"):
        for key in b[sec]:
            if key in EXPECT[sec]:
                continue
            bf, af = b[sec][key], a[sec][key]
            same = (scalar(sec, bf, "zh_CN") == scalar(sec, af, "zh_CN")
                    and scalar(sec, bf, "en_US") == scalar(sec, af, "en_US")
                    and scalar(sec, af, "zh_CN") is not None)
            print("%-4s | %-12s [%-7s] zh %-12s en %-26s | %s"
                  % ("PASS" if same else "FAIL", sec, key,
                     scalar(sec, af, "zh_CN"), scalar(sec, af, "en_US"), af["zh_CN"]["why"]))
            if not same:
                fails.append("%s[%s] 回归被改动：%s → %s"
                             % (sec, key, scalar(sec, bf, "zh_CN"), scalar(sec, af, "zh_CN")))

    print("\n===== 「专业」唯一性（含停用菜单） =====")
    for r in a["named_专业"]:
        print("  菜单 %s  active=%s  %s" % (r["id"], r["active"], r["complete_name"]))
    if len(a["named_专业"]) != 1:
        fails.append("叫「专业」的菜单不是 1 条，而是 %d 条" % len(a["named_专业"]))
    active_专业 = [r for r in a["named_专业"] if r["active"]]
    if len(active_专业) != 1 or active_专业[0]["id"] != 263:
        fails.append("启用的「专业」不是唯一的 263：%s" % [r["id"] for r in active_专业])

    print("\n===== 结论：%s =====" % ("全绿" if not fails else "%d 条 FAIL" % len(fails)))
    for f in fails:
        print("  FAIL | %s" % f)
    return 0 if not fails else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()
    if args.diff:
        sys.exit(do_diff(*args.diff))
    out = dump()
    text = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print("written %s" % args.out)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
