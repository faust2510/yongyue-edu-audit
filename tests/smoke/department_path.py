#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""院系部门（op.department）后台路径端到端验证 —— 证据 + 可重跑门禁。

背景（2026-09-22，教务专员实测）：菜单 259「院系」（= op.faculty 教职员工）把教务
带进一张要 名/姓/性别/出生日期 的人事表；真正要建的「院系」其实在
教学管理(262) → 部门(265) → op.department。本脚本把这条路走一遍，留下前后对照。

判据（层与层不互相替代）：
  L1 菜单可见（口径 B：/web/webclient/load_menus，前端真正渲染的那份树）
  L2 动作解析（/web/action/load → res_model / view_mode，不是只看状态码）
  L3 ORM 可打开（get_views + search_read：视图 arch + ACL 真跑）
  L4 **真浏览器**（Playwright）：点 教学管理 → 部门 → 新建 → 填 名称+代码 → 保存
     → 列表里看得见；截图留档。只看 HTTP 200 不算通过。
  S  副作用（只读实测）：op.department.create() 会把新院系**挂到创建者身上**
     （基座 openeducat_core/models/department.py:33-38 → env.user.department_ids）
  C  清场：删除探针记录并复验 leftover = 0（含 SQL 反查）

用法：
  python3 tests/smoke/department_path.py --out tests/smoke/department_path_before.json
  python3 tests/smoke/department_path.py --no-browser      # 只跑 L1-L3 + S
  python3 tests/smoke/department_path.py --keep            # 保留探针（调试用）
退出码：0 全绿；1 有 FAIL；2 环境不可用（登录失败/站点不通/缺依赖）。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

try:
    import requests
except ImportError:
    print("FATAL | 需要 requests")
    sys.exit(2)

BASE = os.environ.get("DEPT_BASE", "http://localhost:8069")
DB_NAME = os.environ.get("DEPT_DB", "edu19")
USER = (os.environ.get("DEPT_USER", "backoffice@local"), os.environ.get("DEPT_PWD", "demo123"))
MENU_DEPT = 265          # 教学管理 → 部门（op.department）
MENU_PARENT = 262        # 教学管理
MENU_FACULTY = 259       # 「院系」误名菜单（op.faculty）
ACTION_DEPT = 380        # ir.actions.act_window → op.department
UI_NAME = "【冒烟】院系部门探针UI"
UI_CODE = "SMOKE-DEPT-UI"
RPC_CODE = "SMOKE-DEPT-RPC"
ROOT = Path(__file__).resolve().parent.parent.parent
SHOTS = ROOT / "shots" / "smoke"
SHOTS.mkdir(parents=True, exist_ok=True)

RESULT = {"rows": [], "notes": []}


def rec(kind, area, detail):
    RESULT["rows"].append({"kind": kind, "area": area, "detail": detail})
    print("%-4s | %-28s | %s" % (kind, area, detail), flush=True)


def sess_login(user, pwd):
    s = requests.Session()
    s.trust_env = False
    s.proxies = {"http": None, "https": None}
    try:
        r = s.post(BASE + "/web/session/authenticate", json={
            "jsonrpc": "2.0", "method": "call",
            "params": {"db": DB_NAME, "login": user, "password": pwd}}, timeout=30)
        res = (r.json() or {}).get("result") or {}
        if res.get("uid"):
            return s, res["uid"], None
        return None, None, json.dumps(r.json(), ensure_ascii=False)[:200]
    except Exception as exc:  # noqa: BLE001
        return None, None, "%s: %s" % (type(exc).__name__, exc)


def call(s, model, method, args=None, kwargs=None, timeout=120):
    try:
        r = s.post(BASE + "/web/dataset/call_kw", json={
            "jsonrpc": "2.0", "method": "call",
            "params": {"model": model, "method": method,
                       "args": args or [], "kwargs": kwargs or {}}}, timeout=timeout)
        j = r.json()
    except Exception as exc:  # noqa: BLE001
        return False, "RPC异常 %s: %s" % (type(exc).__name__, exc)
    if "error" in j:
        d = (j["error"].get("data") or {})
        return False, "%s: %s" % (d.get("name") or "Error",
                                  (d.get("message") or j["error"].get("message") or "")[:220])
    return True, j.get("result")


def load_menus(s):
    payload = s.get(BASE + "/web/webclient/load_menus?unique=dept_path", timeout=60).json()
    nodes = {k: v for k, v in payload.items() if k.isdigit()}
    parent = {}
    for k, v in nodes.items():
        for c in (v.get("children") or []):
            parent[str(c)] = k

    def path_of(nid):
        names, cur, seen = [], str(nid), set()
        while cur and cur in nodes and cur not in seen:
            seen.add(cur)
            names.append(nodes[cur].get("name") or "?")
            cur = parent.get(cur)
        return " / ".join(reversed(names))

    return nodes, path_of


def sql(sql_text):
    """宿主侧只读反查（走 docker exec）。"""
    try:
        out = subprocess.run(
            ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo", "-d", DB_NAME,
             "-t", "-A", "-c", sql_text],
            capture_output=True, text=True, timeout=60)
        return out.stdout.strip(), out.returncode
    except Exception as exc:  # noqa: BLE001
        return "sql异常 %s" % exc, 1


def browser_flow(sess, shot_prefix, created):
    """L4：真浏览器走 教学管理 → 部门 的新建动线。返回 (ok, info)。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "未安装 playwright"
    sid = sess.cookies.get("session_id")
    host = BASE.split("//")[-1].split(":")[0]
    info = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(locale="zh-CN", viewport={"width": 1500, "height": 950})
        ctx.add_cookies([{"name": "session_id", "value": sid, "domain": host, "path": "/"}])
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        url = "%s/odoo/action-%s?menu_id=%s" % (BASE, ACTION_DEPT, MENU_DEPT)
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_selector(".o_control_panel, .o_list_view", timeout=20000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1200)
        info["url"] = page.url
        info["title"] = page.title()
        info["breadcrumb"] = page.locator(".o_breadcrumb").first.inner_text().strip() if page.locator(".o_breadcrumb").count() else ""
        info["header"] = page.locator(".o_control_panel .o_last_breadcrumb_item, .o_breadcrumb").first.inner_text().strip() if page.locator(".o_control_panel").count() else ""
        page.screenshot(path=str(SHOTS / (shot_prefix + "_1_list.png")), full_page=False)
        # 新建
        for sel in (".o_list_button_add", ".o-kanban-button-new", "button[name='create']", ".o_control_panel .btn-primary"):
            if page.locator(sel).count():
                page.locator(sel).first.click()
                break
        try:
            page.wait_for_selector(".o_form_view", timeout=20000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(900)
        info["form_open"] = bool(page.locator(".o_form_view").count())
        page.screenshot(path=str(SHOTS / (shot_prefix + "_2_form.png")), full_page=False)
        if info["form_open"]:
            # Odoo 19：字段名挂在 **div.o_field_widget[name=...]** 上，不在 <input> 上
            def fill_field(fname, value):
                for sel in (".o_field_widget[name='%s'] input" % fname,
                            "input#%s_0" % fname, "input[name='%s']" % fname):
                    if page.locator(sel).count():
                        page.fill(sel, value)
                        return sel
                return None

            info["sel_name"] = fill_field("name", UI_NAME)
            info["sel_code"] = fill_field("code", UI_CODE)
            info["form_labels"] = page.locator(".o_form_view .o_form_label").all_inner_texts()[:12]
            info["form_inputs"] = page.locator(".o_form_view .o_field_widget[name]").evaluate_all(
                "els => els.map(e => e.getAttribute('name'))")[:12]
            page.wait_for_timeout(300)
            saved = False
            for sel in (".o_form_button_save", "button[name='save']"):
                if page.locator(sel).count():
                    page.locator(sel).first.click()
                    saved = True
                    break
            info["save_clicked"] = saved
            try:
                page.wait_for_selector(".o_form_view", state="detached", timeout=15000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(1500)
            info["url_after_save"] = page.url
            info["err_dialog"] = page.locator(".o_error_dialog").first.inner_text()[:200] if page.locator(".o_error_dialog").count() else ""
            info["body_has_name"] = UI_NAME in (page.content() or "")
            page.screenshot(path=str(SHOTS / (shot_prefix + "_3_saved.png")), full_page=False)
        info["console_errors"] = errors[-5:]
        browser.close()
    return True, info


def faculty_page_evidence(sess, shot_prefix):
    """用户实际误入的那一页（菜单 259「院系」→ op.faculty）留档 + 读必填字段。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "未安装 playwright"
    sid = sess.cookies.get("session_id")
    host = BASE.split("//")[-1].split(":")[0]
    info = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(locale="zh-CN", viewport={"width": 1500, "height": 950})
        ctx.add_cookies([{"name": "session_id", "value": sid, "domain": host, "path": "/"}])
        page = ctx.new_page()
        page.goto("%s/odoo/action-388?menu_id=%s" % (BASE, MENU_FACULTY),
                  wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_selector(".o_control_panel, .o_list_view", timeout=20000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1200)
        info["url"] = page.url
        info["title"] = page.title()
        info["menu_bar"] = (page.locator(".o_main_navbar").first.inner_text().replace("\n", " ")
                            if page.locator(".o_main_navbar").count() else "")
        page.screenshot(path=str(SHOTS / (shot_prefix + "_0_faculty_page.png")))
        # 打开一条记录看表单必填字段（没有记录就看列表列）
        if page.locator(".o_data_row").count():
            page.locator(".o_data_row").first.click()
            try:
                page.wait_for_selector(".o_form_view", timeout=15000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(900)
            info["required_inputs"] = page.locator(
                ".o_form_view .o_field_widget[required='1']").evaluate_all(
                "els => els.map(e => e.getAttribute('name'))")[:20]
            info["form_labels"] = page.locator(".o_form_view .o_form_label").all_inner_texts()[:20]
            page.screenshot(path=str(SHOTS / (shot_prefix + "_0b_faculty_form.png")))
        browser.close()
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    shot_prefix = "dept_path_" + (args.tag or time.strftime("%H%M%S"))

    sess, uid, err = sess_login(*USER)
    if not uid:
        print("ENV | 登录失败：%s" % err)
        return 2
    rec("PASS", "ENV·登录", "%s uid=%s lang=%s" % (USER[0], uid, (sess.post(BASE + "/web/session/get_session_info", json={"jsonrpc": "2.0", "params": {}}, timeout=30).json().get("result") or {}).get("user_context", {}).get("lang")))

    # ---- L1 菜单可见（口径 B）----
    nodes, path_of = load_menus(sess)
    dept = nodes.get(str(MENU_DEPT))
    par = nodes.get(str(MENU_PARENT))
    fac = nodes.get(str(MENU_FACULTY))
    RESULT["menu_path_dept"] = path_of(MENU_DEPT) if dept else None
    RESULT["menu_path_faculty"] = path_of(MENU_FACULTY) if fac else None
    if dept:
        rec("PASS", "L1 菜单可见", "265 路径=%s actionID=%s actionModel=%s" % (
            RESULT["menu_path_dept"], dept.get("actionID"), dept.get("actionModel")))
        if par and par.get("name") == "教学管理" and par.get("name") in RESULT["menu_path_dept"]:
            rec("PASS", "L1 归属", "265 挂在「%s」下" % par.get("name"))
        else:
            rec("WARN", "L1 归属", "265 父菜单=%s（期望 教学管理）" % (par.get("name") if par else "不可见"))
    else:
        rec("FAIL", "L1 菜单可见", "265 对 %s 不可见" % USER[0])
    if fac:
        rec("INFO", "L1 对照", "259「%s」→ action %s（op.faculty 误名项）" % (
            fac.get("name"), fac.get("actionID")))

    # ---- L2 动作解析 ----
    act = sess.post(BASE + "/web/action/load", json={
        "jsonrpc": "2.0", "method": "call",
        "params": {"action_id": ACTION_DEPT, "context": {}}}, timeout=60).json()
    a = act.get("result") or {}
    RESULT["action"] = {k: a.get(k) for k in ("name", "res_model", "view_mode", "type")}
    if a.get("res_model") == "op.department":
        rec("PASS", "L2 动作", "380 name=%r res_model=%s view_mode=%s" % (
            a.get("name"), a.get("res_model"), a.get("view_mode")))
    else:
        rec("FAIL", "L2 动作", "380 = %r" % RESULT["action"])

    # ---- L3 ORM 可打开 ----
    ok, gv = call(sess, "op.department", "get_views", [[[False, "list"], [False, "form"]]], {"options": {}})
    if ok and gv and gv.get("views"):
        RESULT["views"] = {k: (v.get("arch", "")[:120]) for k, v in gv["views"].items()}
        rec("PASS", "L3 视图", "get_views ok：%s" % ",".join(sorted(gv["views"].keys())))
    else:
        rec("FAIL", "L3 视图", "get_views 失败：%s" % gv)
    ok, rows = call(sess, "op.department", "search_read", [[], ["name", "code", "parent_id"]], {"limit": 50})
    RESULT["before_count"] = len(rows) if ok else None
    if ok:
        rec("PASS", "L3 列表", "search_read ok：现有 %d 条 %s" % (
            len(rows), [r["name"] for r in rows][:6]))
    else:
        rec("FAIL", "L3 列表", "search_read 失败：%s" % rows)

    # ---- S 副作用：创建者被挂上新院系（只读实测 + RPC 探针）----
    ok, u0 = call(sess, "res.users", "read", [[uid], ["department_ids", "dept_id"]])
    before_user = (u0[0].get("department_ids") or []) if ok else []
    RESULT["user_departments_before"] = before_user
    ok, new_id = call(sess, "op.department", "create", [{"name": "【冒烟】院系部门探针RPC", "code": RPC_CODE}])
    if ok:
        ok2, u1 = call(sess, "res.users", "read", [[uid], ["department_ids"]])
        after_user = (u1[0].get("department_ids") or []) if ok2 else []
        RESULT["user_departments_after"] = after_user
        RESULT["side_effect_probe_id"] = new_id
        gained = sorted(set(after_user) - set(before_user))
        if new_id in after_user:
            rec("PASS", "S 副作用(实测)", "create() 把新院系 %s 挂到创建者 res.users.department_ids（%d→%d，新增 %s）—— 见 department.py:33-38" % (
                new_id, len(before_user), len(after_user), gained))
        else:
            rec("WARN", "S 副作用(实测)", "新院系未出现在创建者 department_ids（%s→%s）" % (before_user, after_user))
    else:
        rec("FAIL", "S 副作用探针", "RPC create 失败：%s" % new_id)

    # ---- L4 真浏览器 ----
    ui_ok = None
    if not args.no_browser:
        ui_ok, info = browser_flow(sess, shot_prefix, None)
        RESULT["browser"] = info
        if ui_ok:
            rec("PASS", "L4 浏览器·落地", "url=%s title=%r 面包屑=%r" % (
                info.get("url"), info.get("title"), info.get("breadcrumb")))
            if info.get("form_open") and info.get("save_clicked") and not info.get("err_dialog"):
                rec("PASS", "L4 浏览器·新建保存", "表单打开→填 名称+代码→保存；页面含新记录名=%s" % info.get("body_has_name"))
            else:
                rec("WARN", "L4 浏览器·新建保存", "form_open=%s save=%s err=%r" % (
                    info.get("form_open"), info.get("save_clicked"), info.get("err_dialog")))
            if info.get("console_errors"):
                rec("WARN", "L4 控制台", "%s" % info["console_errors"])
        else:
            rec("WARN", "L4 浏览器", "跳过：%s" % info)

    # ---- 对照：用户实际误入的那一页（259 → op.faculty）----
    if not args.no_browser:
        finfo = faculty_page_evidence(sess, shot_prefix)
        RESULT["faculty_page"] = finfo
        if isinstance(finfo, dict):
            rec("INFO", "对照·259 页面", "title=%r 面包屑/必填=%s" % (
                finfo.get("title"), finfo.get("required_inputs")))
        else:
            rec("WARN", "对照·259 页面", str(finfo))

    # ---- 列表复验（新记录是否真在列表里）----
    ok, rows = call(sess, "op.department", "search_read", [[("code", "in", [UI_CODE, RPC_CODE])], ["name", "code"]], {})
    RESULT["created_rows"] = rows if ok else None
    codes = sorted({r["code"] for r in (rows or [])})
    if ok and codes == [RPC_CODE, UI_CODE]:
        rec("PASS", "复验·列表", "RPC + UI 两条探针都在列表：%s" % [(r["name"], r["code"]) for r in rows])
    elif ok:
        rec("WARN", "复验·列表", "探针 code=%s（期望 %s）⇒ UI 保存可能未落库" % (codes, [RPC_CODE, UI_CODE]))

    # ---- C 清场 ----
    if args.keep:
        rec("INFO", "C 清场", "--keep：保留探针 %s" % [r["id"] for r in (rows or [])])
    else:
        ids = [r["id"] for r in (rows or [])]
        if ids:
            ok, res = call(sess, "op.department", "unlink", [ids])
            rec("PASS" if ok else "FAIL", "C 清场", "unlink %s → %s" % (ids, "ok" if ok else res))
        out, rc = sql("SELECT count(*) FROM op_department WHERE code IN ('%s','%s');" % (UI_CODE, RPC_CODE))
        RESULT["leftover_sql"] = out
        rec("PASS" if out == "0" else "FAIL", "C 清场·SQL反查", "leftover=%s（期望 0）" % out)

    fails = [r for r in RESULT["rows"] if r["kind"] == "FAIL"]
    RESULT["summary"] = {"fail": len(fails), "warn": len([r for r in RESULT["rows"] if r["kind"] == "WARN"])}
    if args.out:
        p = Path(args.out) if os.path.isabs(args.out) else ROOT / args.out
        p.write_text(json.dumps(RESULT, ensure_ascii=False, indent=2), encoding="utf-8")
        print("结果已写入 %s" % p)
    print("== FAIL=%d WARN=%d ==" % (RESULT["summary"]["fail"], RESULT["summary"]["warn"]))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
