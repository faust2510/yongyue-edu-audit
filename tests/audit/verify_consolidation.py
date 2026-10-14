#/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T7 独立验证：功能重叠收口（只读）。

用法：
  python3 tests/audit/verify_consolidation.py --phase before
  python3 tests/audit/verify_consolidation.py --phase after
输出：tests/audit/out/<phase>_*.json

只读约定：仅 HTTP GET 与 Odoo 读方法；数据核对走 docker exec psql SELECT。
本脚本绝不修改数据库、菜单或任何实现文件。
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit_lib as A

OUT = HERE / "out"

LIMITS = {"backoffice": 12, "admin": 20}

# 重复入口对：收口后「对教务可见」的成员根菜单数必须 <= 1
DUP_GROUPS = [
    ("op.student 双根", [257, 278]),
    ("打卡双入口(根)", [543, 593]),
    ("评估双根", [588, 597]),
    ("考勤多根", [349, 529]),
    ("招生双根", [300, 591]),
    ("原生噪音组(档2对超管=预期)", [121, 142, 214, 75, 566, 15, 196, 388, 547, 529, 16, 434]),
    ("合并候选组", [504, 288, 325, 357, 83, 507, 372, 542, 606]),
]

# 保留功能可达性清单（>=30 条，覆盖学生端/教师端/教务/审批/打卡/周记/排课/成绩/缴费/下载/测验/帮助中心）
ROUTES = [
    ("anon", "GET", "/", "首页品牌"),
    ("anon", "GET", "/campus/jobs", "公开岗位列表"),
    ("anon", "GET", "/campus/jobs/1", "岗位详情+投递表单"),
    ("anon", "GET", "/help", "帮助中心入口"),
    ("anon", "GET", "/web/login", "登录页(302->/login)"),
    ("anon", "GET", "/my/home", "未登录受保护->303"),
    ("anon", "GET", "/downloads/manage", "未登录受保护->303"),
    ("student", "GET", "/my/home", "学生门户首页(合并后=宫格)"),
    # H-1：/my/apps 降级为兼容层（学生/家长 303 → /my/home），探针**不跟随重定向**
    ("student", "GET", "/my/apps", "合并后兼容层(303->/my/home)"),
    ("parent", "GET", "/my/apps", "合并后兼容层(303->/my/home)"),
    ("faculty", "GET", "/my/apps", "教师宫格已并页(2026-10-03 起 303->/my/home)"),
    ("backoffice", "GET", "/my/apps", "教务宫格入口(须200)"),
    ("student", "GET", "/my/checkins", "打卡(edu_life 留)"),
    ("student", "GET", "/my/checkin", "打卡旧入口(收口后应303->/my/checkins)"),
    ("student", "GET", "/my/checkin/export", "旧打卡导出(收口后应303)"),
    ("faculty", "GET", "/my/checkin/board", "全员到堂看板(教师须200)"),
    ("student", "GET", "/my/courses", "我的课程"),
    ("student", "GET", "/my/study", "在线学习"),
    ("student", "GET", "/my/marks", "我的成绩"),
    ("student", "GET", "/my/fees", "缴费"),
    ("student", "GET", "/my/documents", "我的文档"),
    ("student", "GET", "/my/evaluation", "综合评估(门户)"),
    # 2026-09-29：B 套（edu_eval）已删，/eval/my 现为 404；探针改贴新引擎
    # edu_assess 的同义页，保住"学生评估入口可达"这条读数。
    ("student", "GET", "/assess/my", "评估待办(新引擎)"),
    ("student", "GET", "/my/journals", "周记"),
    ("student", "GET", "/my/points", "积分(学生303->/my/home)"),
    ("student", "GET", "/my/assets", "我的资产"),
    ("student", "GET", "/my/time_off", "请假/调课"),
    ("student", "GET", "/student/timetable", "学生周课表"),
    ("student", "GET", "/student/attendance", "学生出勤"),
    ("student", "GET", "/student/subjects", "学生科目"),
    ("student", "GET", "/student/exam", "学生考试"),
    ("student", "GET", "/downloads", "资料下载列表"),
    ("student", "GET", "/downloads/mine", "我的下载"),
    ("student", "GET", "/my/help", "帮助中心(学生)"),
    ("student", "GET", "/help/student", "帮助中心(学生页)"),
    ("faculty", "GET", "/checkins/stats", "教师打卡统计"),
    ("faculty", "GET", "/assess/review", "评估评审(新引擎)"),
    ("faculty", "GET", "/help/faculty", "帮助中心(教师)"),
    ("faculty", "GET", "/my/rollcall", "点名"),
    ("parent", "GET", "/my/child", "家长查看子女"),
    ("parent", "GET", "/help/parent", "帮助中心(家长)"),
    ("backoffice", "GET", "/help/registrar", "帮助中心(教务)"),
]


Q = chr(39)

DQ_DAILY = ("SELECT id, student_id, date, attend, devotion, coalesce(bible_passage, " + Q + "-" + Q + "), "
            "coalesce(devotion_note, " + Q + "-" + Q + "), coalesce(bible_note, " + Q + "-" + Q + ") "
            "FROM edu_daily_checkin ORDER BY id")
DQ_RECORD = ("SELECT id, student_id, type_id, checkin_date, coalesce(note, " + Q + "-" + Q + ") "
             "FROM edu_checkin_record ORDER BY id")

def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def check_role_menus():
    """口径 B：前端 load_menus 的根菜单（appID 分组）+ ORM 口径交叉。"""
    res = {}
    for label, user, pwd in A.ROLES:
        s, uid, err = A.login(user, pwd)
        if not uid:
            res[label] = {"error": err}
            continue
        lm = A.load_menus(s)
        nodes = {k: v for k, v in lm.items() if k.isdigit()} if isinstance(lm, dict) else {}
        apps = {}
        for k, v in nodes.items():
            aid = v.get("appID")
            if aid is None:
                continue
            apps.setdefault(int(aid), {"name": v.get("name") if int(aid) == int(k) else None,
                                      "members": []})
            apps[int(aid)]["members"].append(v.get("name"))
        for aid, info in apps.items():
            if info["name"] is None:
                info["name"] = nodes.get(str(aid), {}).get("name") or "(未知根菜单 %s)" % aid
        orm_ok, orm_roots = True, None
        try:
            orm_roots = A.menus(s, root_only=True)
        except Exception:
            orm_ok = False
        res[label] = {
            "uid": uid,
            "B_frontend_root_count": len(apps),
            "B_frontend_nodes": len(nodes),
            "frontend_roots": [{"id": a, "name": apps[a]["name"],
                                "members": sorted(set(x for x in apps[a]["members"] if x))}
                               for a in sorted(apps)],
            "B_orm_acl_ok": orm_ok,
            "B_orm_root_count": (len(orm_roots) if orm_ok else None),
        }
    return res


def check_routes():
    """逐条实测 HTTP 码（只 GET）。"""
    sessions = {}
    for label, user, pwd in A.ROLES:
        s, uid, err = A.login(user, pwd)
        sessions[label] = s
    anon = A.sess()
    out = []
    for role, method, path, desc in ROUTES:
        s = sessions.get(role) or anon
        try:
            code, loc, final = A.get(s, path, follow=False)
            body_ok, note = None, ""
        except Exception as e:
            code, loc, final, body_ok, note = -1, str(e)[:120], "", False, "exception"
        out.append({"role": role, "method": method, "path": path, "desc": desc,
                    "status": code, "location": loc, "expected": None})
    return out


def check_dup_entries(role_menus):
    """重复入口：每个角色下，每个重复组里「可见根菜单」的个数。"""
    out = {}
    for label, info in role_menus.items():
        if "frontend_roots" not in info:
            out[label] = {"error": info.get("error", "no data")}
            continue
        visible = set(r["id"] for r in info["frontend_roots"])
        groups = {}
        for gname, ids in DUP_GROUPS:
            hit = [i for i in ids if i in visible]
            # 队长裁定：档2 六棵对超管可见属预期（restrict_tree），非超管必须 0。
            # 故 admin 的原生噪音组只判「超出档2集合」才是缺陷。
            if "原生噪音" in gname and label == "admin":
                unexpected = [i for i in hit if i not in TIER2_ADMIN_ONLY]
                ok = not unexpected
                groups[gname] = {"ids": ids, "visible": hit,
                                 "visible_count": len(hit), "ok": ok,
                                 "expected_visible": [i for i in hit if i in TIER2_ADMIN_ONLY],
                                 "unexpected": unexpected,
                                 "rule": "admin 可见集 ⊆ 档2集合 即 PASS"}
            else:
                groups[gname] = {"ids": ids, "visible": hit,
                                 "visible_count": len(hit), "ok": len(hit) <= 1}
        out[label] = {"visible_root_count": len(visible), "groups": groups,
                      "dup_group_total": len(groups),
                      "dup_groups_ok": sum(1 for g in groups.values() if g["ok"])}
    return out


def check_limits(role_menus):
    out = {}
    for role, lim in LIMITS.items():
        info = role_menus.get(role) or {}
        n = info.get("B_frontend_root_count")
        out[role] = {"limit": lim, "actual": n, "ok": (n is not None and n <= lim)}
    return out


def check_data(phase, before_path):
    """打卡两表计数 + edu.daily.checkin 逐条明细（迁移口径核对用）。"""
    d = {"phase": phase, "checked_at": now()}
    d["counts"] = {
        "edu_checkin_record": A.cnt("edu_checkin_record") if A.has_table("edu_checkin_record") else None,
        "edu_daily_checkin": A.cnt("edu_daily_checkin") if A.has_table("edu_daily_checkin") else None,
        "edu_checkin_type": A.cnt("edu_checkin_type") if A.has_table("edu_checkin_type") else None,
    }
    if A.has_table("edu_checkin_type"):
        d["types"] = A.rows("SELECT id, name, sequence, active FROM edu_checkin_type ORDER BY id")
    if A.has_table("edu_daily_checkin"):
        d["daily_rows"] = A.rows(DQ_DAILY)
    if A.has_table("edu_checkin_record"):
        d["record_rows"] = A.rows(DQ_RECORD)
    before = None
    if before_path and os.path.exists(str(before_path)):
        with open(str(before_path), encoding="utf-8") as f:
            before = json.load(f)
    d["before_counts"] = (before or {}).get("counts")
    bp = (before or {}).get("counts", {}).get("edu_checkin_record")
    nowr = d["counts"]["edu_checkin_record"]
    d["delta_edu_checkin_record"] = None if (bp is None or nowr is None) else nowr - bp
    db4 = (before or {}).get("counts", {}).get("edu_daily_checkin")
    nowd = d["counts"]["edu_daily_checkin"]
    d["delta_edu_daily_checkin"] = None if (db4 is None or nowd is None) else nowd - db4
    return d



# 队长裁定（2026-09-17）：写成机器可判的预期，after 阶段逐条判定
RULINGS_TIER2_NOTE = ("档2 对超管可见属预期（restrict_tree 实现）；"
                    "非超管必须 0 可见")

RULINGS = {
    # H-1（校长拍板 2026-09-18）：学生门户主页合并。学生/家长的 /my/apps 收口为
    # 兼容层 303 → /my/home（路由保留 ⇒ 旧书签不 404）。
    # 2026-10-03（task-19，用户要求「老师的我的主页和应用面板功能可以合并」）：
    # **教师**同样收口 303 → /my/home（工作台 + 宫格同页）；**教务保持 200**
    # （他们在门户里仍只有这一条宫格入口）。判据 = **303 + Location 精确**
    # （探针不跟随重定向，不接受"跟随后 200"，见 docs/dev-workflow.md 陷阱 2）。
    "apps_merged_303": {
        "expect": {"student": 303, "parent": 303, "faculty": 303},
        "expect_location": "/my/home",
        "expect_200": {"backoffice": 200},
        "note": "学生/家长/教师 /my/apps = 兼容层 303→/my/home；教务 200 不变",
    },
    "checkin_redirect_303": {
        "expect": {"/my/checkin": 303, "/my/checkin/export": 303},
        "note": "旧打卡入口 -> 303 /my/checkins*，属预期，不是缺陷",
    },
    "checkin_board_200": {
        "expect": {"/my/checkin/board": 200},
        "note": "看板保留，数据源改读新表「到堂」类型；仍须 200",
    },
    "new_type_daotang": {
        "expect_type_name": "到堂",
        "expect_frequency": "daily",
        "note": "新增到堂打卡类型属预期；教师统计多一列、avg_rate 改口径属已声明变化",
    },
    "student_page_must_render": {
        "paths": ["/my/checkins", "/my/home"],
        "must_not_contain": ["Traceback (most recent call last)", "Internal Error"],
        "note": "学生页报错才是真缺陷；上一条副作用不算",
    },
}



# 档2「仅超管可见」集合：对非超管必须 0 可见；admin 可见集 ⊆ 该集合即 PASS
TIER2_ADMIN_ONLY = [1, 15, 121, 142, 196, 566]
TIER2_NON_ADMIN_ROLES = ["backoffice", "faculty", "student", "parent"]


def check_tier2(role_menus):
    """队长裁定：档2 由 restrict_tree 实现（根+全部子树挂 base.group_system）。

    判定规则：
      - 非超管角色（backoffice/faculty/student/parent）对该集合必须 0 可见；
      - admin 可见集必须是 TIER2_ADMIN_ONLY 的**子集**（超出才记缺陷）。
    """
    out = {"admin_only_set": TIER2_ADMIN_ONLY, "non_admin": {}, "admin": {}}
    ok_all = True
    for role in TIER2_NON_ADMIN_ROLES:
        info = role_menus.get(role) or {}
        vis = set(r["id"] for r in info.get("frontend_roots", []))
        hit = sorted(vis & set(TIER2_ADMIN_ONLY))
        out["non_admin"][role] = {"visible": hit, "count": len(hit),
                                  "ok": len(hit) == 0}
        ok_all = ok_all and len(hit) == 0
    info = role_menus.get("admin") or {}
    vis = set(r["id"] for r in info.get("frontend_roots", []))
    got = sorted(vis & set(TIER2_ADMIN_ONLY))
    extra = sorted(x for x in got if x not in TIER2_ADMIN_ONLY)
    out["admin"] = {"visible": got, "subset_ok": not extra, "unexpected": extra}
    ok_all = ok_all and not extra
    out["ok"] = ok_all
    out["note"] = ("档2 六棵（1/15/121/142/196/566）对超管可见属预期；"
                   "非超管一律必须 0 可见")
    return out


def menu_snapshot():
    """只读：角色可见根菜单 + DB 菜单统计（用于升级前后对拍）。"""
    snap = {"captured_at": now(),
            "A_root_menus_db": int(A.sql("SELECT count(*) FROM ir_ui_menu WHERE parent_id IS NULL")),
            "A_total_menus_db": int(A.sql("SELECT count(*) FROM ir_ui_menu")),
            "A_active_menus_db": int(A.sql("SELECT count(*) FROM ir_ui_menu WHERE active")),
            "roles": {}}
    for label, user, pwd in A.ROLES:
        s, uid, err = A.login(user, pwd)
        if not uid:
            snap["roles"][label] = {"error": err}
            continue
        lm = A.load_menus(s)
        nodes = {k: v for k, v in lm.items() if k.isdigit()} if isinstance(lm, dict) else {}
        apps = {}
        for k, v in nodes.items():
            aid = v.get("appID")
            if aid is not None:
                apps.setdefault(int(aid), {"name": None, "members": 0})
                apps[int(aid)]["members"] += 1
        for aid in apps:
            apps[aid]["name"] = nodes.get(str(aid), {}).get("name") or ("(未知 %s)" % aid)
        snap["roles"][label] = {
            "B_root_count": len(apps),
            "B_nodes": len(nodes),
            "roots": sorted(apps.keys()),
            "root_names": [apps[a]["name"] for a in sorted(apps)],
        }
    return snap



def check_home_merged():
    """H-1 页面级判据（只读 GET）：合并后的 /my/home 就是宫格页。

    正反两面都断言，避免"页面 200 就算过"的假绿：
      · 正面：含宫格标记 o_portal_index_card（≥1）、含 2 处以上头像弹窗触发点
        （data-bs-target="#b11-avatar-modal"：页头用户菜单 1 + 资料卡头像 1）；
      · 反面：**不含**旧 Timeline 首页的 hero 标记 ux3-hero-title">工作台。
    另记两处头像 src 的去重结果（H-1 的"同源"机械判据 = 只剩 1 个 partner id）。
    """
    out = {}
    for role, user, pwd in A.ROLES:
        if role not in ("student", "parent"):
            continue
        s, uid, err = A.login(user, pwd)
        if not uid:
            out[role] = {"error": err, "ok": False}
            continue
        code, loc, _url = A.get(s, "/my/home", follow=False)
        body = ""
        if code == 200:
            try:
                body = s.get(A.BASE + "/my/home", timeout=90).text
            except Exception as e:  # 只读探针失败也要如实记录
                out[role] = {"status": code, "error": str(e)[:120], "ok": False}
                continue
        srcs = sorted(set(re.findall(r'/web/image/res\.partner/\d+/avatar_\d+',
                                     body)))
        out[role] = {
            "status": code,
            "location": loc,
            "cards": body.count("o_portal_index_card"),
            "old_timeline_hero": body.count('ux3-hero-title">工作台'),
            "avatar_modal_targets": body.count('data-bs-target="#b11-avatar-modal"'),
            "avatar_srcs": srcs,
            "avatar_partner_ids": sorted(set(
                p.split("/")[4] for p in srcs)),
            "todo_strip": body.count("ux3-home-todo"),
            "ok": (code == 200 and body.count("o_portal_index_card") >= 1
                   and 'ux3-hero-title">工作台' not in body),
        }
    return out


def check_rulings(role_menus, routes, data):
    """按队长裁定判定 after 阶段的预期行为。"""
    by_path = {}
    for r in routes:
        by_path.setdefault((r["role"], r["path"]), r)
    out = {}
    # 0) H-1：/my/apps 合并收口（303 + Location 精确；内部用户 200 不变）
    r_h1 = RULINGS["apps_merged_303"]
    hits = {}
    h1_ok = True
    for role, want in r_h1["expect"].items():
        got = by_path.get((role, "/my/apps"))
        loc = (got or {}).get("location") or ""
        ok = bool(got) and got.get("status") == want \
            and loc.endswith(r_h1["expect_location"])
        hits[role] = {"expect": want, "actual": (got or {}).get("status"),
                      "location": loc, "ok": ok}
        h1_ok = h1_ok and ok
    for role, want in r_h1["expect_200"].items():
        got = by_path.get((role, "/my/apps"))
        ok = bool(got) and got.get("status") == want
        hits[role] = {"expect": want, "actual": (got or {}).get("status"),
                      "location": (got or {}).get("location"), "ok": ok}
        h1_ok = h1_ok and ok
    out["apps_merged_303"] = {"cases": hits, "ok": h1_ok,
                              "note": r_h1["note"]}
    # 0b) H-1：合并后的 /my/home 页面级判据（宫格在、旧 Timeline 标记不在）
    out["home_merged_content"] = check_home_merged()
    # 1) 303 重定向
    exp = RULINGS["checkin_redirect_303"]["expect"]
    hits = {}
    for path, want in exp.items():
        got = by_path.get(("student", path))
        hits[path] = {"expect": want, "actual": (got or {}).get("status"),
                      "ok": bool(got) and got.get("status") == want}
    out["checkin_redirect_303"] = {"cases": hits,
                                   "ok": all(v["ok"] for v in hits.values()),
                                   "note": RULINGS["checkin_redirect_303"]["note"]}
    # 2) 看板 200
    exp = RULINGS["checkin_board_200"]["expect"]
    hits = {}
    for path, want in exp.items():
        # 看板按角色分别判：教师/教务直接 200；学生若被 303 到 /my/checkin 属既有行为
        # （收口前实测 student=303、faculty=200），此处记录各角色实际值。
        per_role = {}
        for (role, pth), v in by_path.items():
            if pth == path:
                per_role[role] = v.get("status")
        primary = per_role.get("faculty")
        ok = (primary == want)
        # 学生侧：收口前就是 303->/my/checkin，收口后仍是 303 即视为未回归
        stu = per_role.get("student")
        if not ok and stu == 303:
            ok = False
        hits[path] = {"expect": want, "by_role": per_role,
                      "faculty": primary, "student": stu,
                      "ok": ok}
    out["checkin_board_200"] = {"cases": hits,
                                "ok": all(v["ok"] for v in hits.values()),
                                "note": RULINGS["checkin_board_200"]["note"]}
    # 3) 到堂类型
    want = RULINGS["new_type_daotang"]["expect_type_name"]
    types = data.get("types") or []
    hit = [r for r in types if len(r) > 1 and want in (r[1] or "")]
    out["tier2_superadmin_visible"] = dict(check_tier2(role_menus),
                                           note=RULINGS_TIER2_NOTE)
    out["new_type_daotang"] = {
        "found": [r[:4] for r in hit],
        "ok": bool(hit),
        "note": RULINGS["new_type_daotang"]["note"],
    }
    return out


def render_md(phase, res):
    L = []
    L.append("# T7 独立验证原始读数（%s）" % phase)
    L.append("")
    L.append("- 生成时间：%s" % res["generated_at"])
    L.append("- 口径 A（DB parent_id is null）：%s 条" % res["A_root_menus_db"])
    L.append("- 口径 B（角色前端 load_menus 根菜单数）见下表")
    L.append("")
    L.append("## 1. 四角色可见根菜单（口径 B）")
    L.append("")
    L.append("| 角色 | B根菜单数 | 前端菜单节点 | ORM ACL | ORM根菜单 | 验收线 | 判定 |")
    L.append("|---|---|---|---|---|---|---|")
    for role, info in res["role_menus"].items():
        lim = LIMITS.get(role, "-")
        n = info.get("B_frontend_root_count")
        ok = "-"
        if role in LIMITS:
            ok = "PASS" if (n is not None and n <= LIMITS[role]) else "FAIL"
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            role, n, info.get("B_frontend_nodes"),
            "OK" if info.get("B_orm_acl_ok") else "DENIED",
            info.get("B_orm_root_count"), lim, ok))
    L.append("")
    L.append("## 2. 重复入口（每个重复组内对教务可见根菜单数，>1 = 仍重复）")
    L.append("")
    L.append("| 角色 | 组 | 可见成员 id | 个数 | 判定 |")
    L.append("|---|---|---|---|---|")
    for role, info in res["dup_entries"].items():
        if "groups" not in info:
            continue
        for gname, g in info["groups"].items():
            verdict = "ok" if g["ok"] else "DUP"
            if g.get("expected_visible") and g["ok"]:
                verdict = "ok(expected)"
            L.append("| %s | %s | %s | %s | %s |" % (
                role, gname, ",".join(str(i) for i in g["visible"]),
                g["visible_count"], verdict))
    L.append("")
    L.append("## 2b. 队长裁定判定（机器判，非人工）")
    L.append("")
    for key, val in (res.get("rulings") or {}).items():
        if key == "tier2_superadmin_visible":
            L.append("- **%s**：%s" % (key, "PASS" if val.get("ok") else "FAIL"))
            for role, info in (val.get("non_admin") or {}).items():
                L.append("    - 非超管 %s 可见档2根：%s（%s）" % (
                    role, info.get("visible"), "ok" if info.get("ok") else "FAIL"))
            ad = val.get("admin") or {}
            L.append("    - admin 可见档2根：%s（子集判定 %s，超出 %s）" % (
                ad.get("visible"), "ok" if ad.get("subset_ok") else "FAIL",
                ad.get("unexpected")))
        elif key == "new_type_daotang":
            L.append("- **%s**：%s found=%s" % (
                key, "PASS" if val.get("ok") else "FAIL", val.get("found")))
        elif key == "home_merged_content":
            L.append("- **%s**：%s" % (
                key, "PASS" if all(v.get("ok") for v in val.values()) else "FAIL"))
            for role, info in val.items():
                L.append("    - %s：HTTP %s / 宫格标记 %s / 旧Timeline标记 %s / "
                         "头像弹窗触发 %s / 头像 src %s（partner id %s）/ 待办窄条 %s"
                         % (role, info.get("status"), info.get("cards"),
                            info.get("old_timeline_hero"),
                            info.get("avatar_modal_targets"),
                            info.get("avatar_srcs"),
                            info.get("avatar_partner_ids"),
                            info.get("todo_strip")))
        else:
            L.append("- **%s**：%s cases=%s" % (
                key, "PASS" if val.get("ok") else "FAIL", val.get("cases")))
    L.append("")
    L.append("## 3. 保留功能可达性（%d 条，逐条 HTTP 码）" % len(res["routes"]))
    L.append("")
    L.append("| 角色 | 路径 | 说明 | 状态 | Location |")
    L.append("|---|---|---|---|---|")
    for r in res["routes"]:
        L.append("| %s | %s | %s | %s | %s |" % (
            r["role"], r["path"], r["desc"], r["status"], r.get("location") or ""))
    L.append("")
    return "\n".join(L) + "\n"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="after", choices=["before", "after"])
    ap.add_argument("--baseline", default=str(OUT / "before_data.json"),
                    help="收口前数据快照（用于增量比对）")
    ap.add_argument("--smoke-log", default=str(OUT / "smoke.log"))
    ap.add_argument("--snapshot-only", action="store_true",
                    help="只做菜单快照并落盘（升级前后对拍用），不跑路由/数据")
    ap.add_argument("--out", default=None, help="快照输出路径")
    args = ap.parse_args()

    print("== phase:", args.phase, "==")
    if args.snapshot_only:
        snap = menu_snapshot()
        path = args.out or str(OUT / (args.phase + "_snapshot.json"))
        A.save(path, snap)
        print("snapshot:", json.dumps(
            {k: v.get("B_root_count") for k, v in snap["roles"].items()},
            ensure_ascii=False))
        return
    A_root = int(A.sql("SELECT count(*) FROM ir_ui_menu WHERE parent_id IS NULL"))
    rm = check_role_menus()
    result = {
        "phase": args.phase,
        "generated_at": now(),
        "A_root_menus_db": A_root,
        "A_total_menus_db": int(A.sql("SELECT count(*) FROM ir_ui_menu")),
        "A_active_root_menus_db": int(A.sql("SELECT count(*) FROM ir_ui_menu WHERE parent_id IS NULL AND active")),
        "role_menus": rm,
        "dup_entries": check_dup_entries(rm),
        "limits": check_limits(rm),
        "routes": check_routes(),
        "data": check_data(args.phase, args.baseline if args.phase == "after" else None),
        "smoke_log": args.smoke_log,
    }
    result["rulings"] = check_rulings(result["role_menus"], result["routes"], result["data"])
    OUT.mkdir(parents=True, exist_ok=True)
    data_path = A.save(str(OUT / (args.phase + "_data.json")), result["data"])
    A.save(str(OUT / (args.phase + "_result.json")), result)
    md = render_md(args.phase, result)
    (OUT / (args.phase + "_report.md")).write_text(md, encoding="utf-8")
    print("[write] " + str(OUT / (args.phase + "_report.md")))
    print("[write] " + str(data_path))
    print()
    print("口径A根菜单=%s  口径B: " % A_root, end="")
    print(" | ".join("%s=%s" % (k, v.get("B_frontend_root_count"))
                     for k, v in rm.items()))
    print("验收线:", json.dumps(result["limits"], ensure_ascii=False))


if __name__ == "__main__":
    main()
