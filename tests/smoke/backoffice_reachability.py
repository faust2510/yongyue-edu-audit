#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""教务后台可达性巡检（权限分层后）+ 3 条端到端真跑 —— 可重跑门禁。

背景（2026-09-17，commit d2c41de）：解除基座「经理」组隐含的 base.group_system，
教务（openeducat_core.group_op_back_office_admin）不再等于系统管理员。
拆开后最容易留下的死角是「菜单看得见、点进去 AccessError / 白屏」——
只看 HTTP 200 抓不到，所以本脚本按三层判据 + 三条端到端流程逐条实测。

判据（层与层不互相替代）：
  L0 静态层分离（离线，先跑）：custom_addons/*/views/*.xml 里**不得有只挂 base.group_system
      的自家菜单**（层分离后教务看不见它）——把「层分离」从一次性改动变成长期守着的断言；
      例外必须登记进 STATIC_GROUP_EXCEPTIONS 并写明理由（默认空）。
  L1 菜单可见（口径 B）：/web/webclient/load_menus —— 前端真正渲染的那份菜单树。
  L2 ORM 可打开：/web/action/load 解析菜单动作 → get_views（视图 arch / 组限制）+
      search_read（模型 ACL + 记录规则）。不是只看状态码，也不会把「动作能解析」
      当成「页面能打开」。
  L3 浏览器真渲染（Playwright）：打开 /odoo/action-<id>?menu_id=<id>，断言
      ① 有控制面板与面包屑；② 落到 list/kanban/form/... 视图容器；
      ③ **关键元素**：列表视图表头命中该视图 arch 里的字段标签（至少一个）；
      ④ 没有 AccessError 弹窗 / 「不允许访问」文案。
  E2E 三条流程（教务身份真跑 + DB 反查 + leftover=0）：
      ① 报名审批：公开报名表建的【冒烟】申请 → 审核中 → 已录取，并勾材料核对；
      ② 成绩录入：改一个分数 → edu.grade.history 留痕（old/new/source/操作人）；
      ③ 考勤录入：点名表 + 出勤明细落库（真写 op.attendance.sheet/line）。
  红线自查：教务账号与教务组都不得含 base.group_system（分层不许回退）。

已知缺口机制（GAPS 清单：测不到不判红，--strict-gaps 判红）：当前**为空**。
  t1 当时登记的两条（邀请码 / 老账号补挂身份 —— 收口轮对「0 后代」的合并根只写了
  active=False、没写 parent_id ⇒ 对所有人不可见）已由 t13 补回入口（菜单 790/791 挂在
  「学生信息 / 配置」，groups = 教务组 + 系统组），因此升格进 COVERAGE 由门禁长期守着；
  历史证据与两条候选修法见 docs/plans/perm-split-audit.md §6.2。

用法：
  python3 tests/smoke/backoffice_reachability.py                    # 巡检 + 3 条流程 + 清场
  python3 tests/smoke/backoffice_reachability.py --selftest          # 静态层分离断言的合成自证（离线）
  python3 tests/smoke/backoffice_reachability.py --dump before.json # 基线快照（不判红）
  python3 tests/smoke/backoffice_reachability.py --no-browser       # 只跑 L1/L2（快；非门禁口径）
  python3 tests/smoke/backoffice_reachability.py --all-menus        # L3 也扫全部可见菜单
  python3 tests/smoke/backoffice_reachability.py --strict-gaps      # 已知缺口也判红
退出码：0 全绿（GAP 不算红）；1 有 FAIL；2 环境不可用（登录失败 / 站点不通 / 缺依赖）。
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import datetime

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

try:
    import requests
except ImportError:  # pragma: no cover
    print("FATAL | 需要 requests：pip3 install requests")
    sys.exit(2)

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:8069")
DB_NAME = os.environ.get("EDU_DB_NAME", "edu19")
DB_CONTAINER = os.environ.get("EDU_DB_CONTAINER", "edu19-clone-db-1")
ADMIN = ("admin", "admin")
BACKOFFICE = ("backoffice@local", "demo123")
TAG = "【冒烟】"          # 夹具标记：自建自清的唯一依据
TAG_SQL = "%" + TAG + "%"

# ---------------------------------------------------------------- 覆盖清单
# 任务要求的 15 个业务域（+ 巡检时顺手覆盖的同类菜单）。match = L1 菜单完整路径（/ 分隔）。
# gap=True 的条目是「已知历史缺口」：测不到不算本次分层的错，但会打印出来并计入 --strict-gaps。
COVERAGE = [
    ("报名审批", ["招生 / 入学申请"], "edu.application"),
    ("专业", ["学生信息 / 配置 / 教学管理 / 专业"], "op.course"),
    ("科目", ["学生信息 / 配置 / 学科管理 / 科目"], "op.subject"),
    # 2026-09-24：264「批次」→「班级」（op.batch 在本校就是「一个班的学生」，
    # 与 797「已停用班级」同一实体；改名见 edu_portal/views/menu_labels.xml 与
    # docs/ops/menu-rename-list.md §2.2）。路径随之从 …/批次 变为 …/班级。
    ("班级", ["学生信息 / 配置 / 教学管理 / 班级"], "op.batch"),
    ("课节（课次）", ["时间表 / 课次管理"], "op.session"),
    ("时间表", ["时间表 / 时间表 / 会议", "时间表 / 时间表 / 生成时间表"], None),
    ("周期排课（批量）", ["时间表 / 周期排课（批量）"], None),
    ("考试", ["时间表 / 考试 / 考试", "时间表 / 考试 / 考试参加者"], "op.exam"),
    ("考试课程", ["时间表 / 考试 / 考试课程"], "op.exam.session"),
    ("成绩（结果行）", ["时间表 / 考试 / 结果行"], "op.result.line"),
    ("结果分析", ["时间表 / 报告 / 结果分析"], "op.result.line"),
    ("课堂考勤 · 点名册", ["时间表 / 考勤 / 点名册"], "op.attendance.register"),
    ("课堂考勤 · 点名表", ["时间表 / 考勤 / 点名表"], "op.attendance.sheet"),
    ("课堂考勤 · 出勤明细", ["时间表 / 考勤 / 出勤明细"], "op.attendance.line"),
    ("图书馆", ["图书馆 / 所有媒体 / 媒体", "图书馆 / 配置 / 图书卡"], "op.media"),
    ("财务总台账", ["财务管理 / 财务总台账"], None),
    ("费用分类", ["财务管理 / 费用分类"], "edu.fee.category"),
    ("账单/缴费", ["财务管理 / 账单管理", "财务管理 / 缴费流水"], "edu.fee.bill"),
    ("报销审批", ["教务审批 / 报销审批"], None),
    ("公告（布告栏）", ["教务审批 / 布告栏管理"], "edu.notice"),
    ("公告模板", ["教务审批 / 公告模板"], "edu.notice.template"),
    ("请假审批", ["教务审批 / 请假审批"], "edu.leave"),
    ("申诉处理", ["教务审批 / 申诉处理"], "edu.grievance"),
    ("证书管理", ["教务审批 / 证书管理"], "edu.certificate"),
    ("选课审批", ["教务审批 / 选课审批"], None),
    ("福利打卡（全员）", ["灵命生活 / 全员打卡"], "edu.daily.checkin"),
    ("打卡记录", ["灵命生活 / 打卡记录"], "edu.checkin.record"),
    ("积分流水", ["灵命生活 / 积分流水"], "edu.point.log"),
    ("校历", ["时间表 / 校历活动"], "edu.event"),
    ("资料下载管理", ["资料下载"], None),
    ("评教（模板管理）", ["综合评估 / 模板管理"], "edu.eval.template"),
    ("评教（打分记录）", ["综合评估 / 打分记录"], "edu.eval.score"),
    ("评审任务", ["综合评估 / 评估任务"], "edu.eval.task"),
    # 2026-09-17 t13 已把这两条入口补回（新增菜单 790/791 挂在 学生信息 / 配置 下，
    # groups = 教务组 + 系统组），所以它们从「已知缺口」升格为**被门禁守着的覆盖项**：
    # 谁再把它藏起来 / 改成只挂系统组，这里立刻红。
    ("邀请码", ["学生信息 / 配置 / 邀请码"], "edu.invite.code"),
    ("老账号补挂身份", ["学生信息 / 配置 / 老账号补挂身份"], None),
]
# 已知缺口（GAP：测不到不判红，--strict-gaps 判红）。当前为空 ——
# 旧的「邀请码 / 老账号补挂身份」已由 t13 补回入口并升格进 COVERAGE。
GAPS = []

# 收口回归：这些原生菜单已被「按业务补组」收回到功能组 + 超管
# （见 custom_addons/edu_portal/models/menu_reachability.py 的 NARROW_RULES）。
# 断言两件事：① 教务**看不到**（「看得见点不开」的死角已关）；
#             ② 超管**仍看得到**（没有把管理面一起弄丢）。
NARROWED = [
    ("event.menu_event_event", "网站 / 活动"),
    ("website_sale.menu_ecommerce_payment_methods", "网站 / 配置 / 电子商务 / 付款方式"),
    ("spreadsheet_dashboard_im_livechat.ongoing_sessions_agents_in_call_menu", "网站 / 技术 / 进行中的通话会话"),
    ("spreadsheet_dashboard_im_livechat.ongoing_sessions_handle_by_agent_menu", "网站 / 技术 / 由客服处理的会话"),
    ("spreadsheet_dashboard_im_livechat.ongoing_sessions_handle_by_bot_menu", "网站 / 技术 / 由机器人处理的会话"),
]

# 基线快照用的模型清单（权限分层的「可写模型」读数）
ACL_MODELS = [
    "op.student", "op.faculty", "op.course", "op.batch", "op.subject",
    "op.session", "op.exam", "op.exam.attendees", "op.result.line",
    "op.attendance.register", "op.attendance.sheet", "op.attendance.line",
    "op.media", "op.library.card", "edu.application", "edu.apply.section",
    "edu.fee.bill", "edu.fee.payment", "edu.fee.category", "edu.notice",
    "edu.notice.template", "edu.leave", "edu.grievance", "edu.certificate",
    "edu.invite.code", "edu.point.log", "edu.daily.checkin", "edu.checkin.record",
    "edu.journal.entry", "edu.event", "edu.download.file", "edu.download.category",
    "edu.eval.template", "edu.eval.task", "edu.eval.score", "edu.grade.history",
    "edu.asset", "edu.asset.loan", "edu.job.posting", "edu.job.application",
    "edu.subject.prereq", "edu.subject.registration", "res.config.settings",
    "ir.ui.menu", "ir.model.access",
]

FAILS, GAPS_HIT, PASSES = [], [], []
CREATED = []          # 本次运行建过的夹具 [(table, id), ...]：清场时按 id 精确删
TABLE_OF = {
    "edu.application": "edu_application",
    "op.exam": "op_exam",
    "op.exam.attendees": "op_exam_attendees",
    "op.attendance.register": "op_attendance_register",
    "op.attendance.sheet": "op_attendance_sheet",
    "op.attendance.line": "op_attendance_line",
    "edu.grade.history": "edu_grade_history",
}


def track(model, rec_id):
    CREATED.append((TABLE_OF[model], int(rec_id)))


def log(line):
    print(line, flush=True)


def rec(kind, area, detail):
    if kind == "FAIL":
        FAILS.append((area, detail))
        log("FAIL | %-22s | %s" % (area, detail))
    elif kind == "GAP":
        GAPS_HIT.append((area, detail))
        log("GAP  | %-22s | %s" % (area, detail))
    elif kind == "PASS":
        PASSES.append((area, detail))
        log("PASS | %-22s | %s" % (area, detail))
    else:
        log("INFO | %-22s | %s" % (area, detail))


# ---------------------------------------------------------------- HTTP / ORM
def sess_login(user, pwd, retries=2):
    s = requests.Session()
    s.trust_env = False
    s.proxies = {"http": None, "https": None}
    last = ""
    for _ in range(retries):
        try:
            r = s.post(BASE + "/web/session/authenticate", json={
                "jsonrpc": "2.0", "method": "call",
                "params": {"db": DB_NAME, "login": user, "password": pwd},
            }, timeout=30)
            res = (r.json() or {}).get("result") or {}
            if res.get("uid"):
                return s, res["uid"], None
            last = json.dumps(r.json(), ensure_ascii=False)[:200]
        except Exception as exc:  # noqa: BLE001
            last = "%s: %s" % (type(exc).__name__, exc)
        time.sleep(3)
    return None, None, last


def call(s, model, method, args=None, kwargs=None, timeout=120):
    """Odoo JSON-RPC。返回 (ok, result|error_text)。"""
    try:
        r = s.post(BASE + "/web/dataset/call_kw", json={
            "jsonrpc": "2.0", "method": "call",
            "params": {"model": model, "method": method,
                       "args": args or [], "kwargs": kwargs or {}}}, timeout=timeout)
        j = r.json()
    except Exception as exc:  # noqa: BLE001
        return False, "RPC异常 %s: %s" % (type(exc).__name__, exc)
    if "error" in j:
        err = j["error"]
        data = err.get("data") or {}
        return False, "%s: %s" % (data.get("name") or "Error",
                                  (data.get("message") or err.get("message") or "")[:220])
    return True, j.get("result")


def load_menus(s):
    r = s.get(BASE + "/web/webclient/load_menus?unique=backoffice_reach", timeout=60)
    payload = r.json()
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

    out = []
    for k, v in sorted(nodes.items(), key=lambda x: int(x[0])):
        out.append({
            "id": int(k), "name": v.get("name"), "path": path_of(k),
            "action_id": v.get("actionID") or None,
            "action_model": v.get("actionModel") or None,
            "xmlid": v.get("xmlid") or None,
        })
    return out, {m["path"]: m for m in out}, payload


def action_load(s, action_id):
    try:
        r = s.post(BASE + "/web/action/load", json={
            "jsonrpc": "2.0", "method": "call",
            "params": {"action_id": action_id, "context": {}}}, timeout=60)
        j = r.json()
    except Exception as exc:  # noqa: BLE001
        return None, "动作加载异常 %s" % exc
    if "error" in j:
        data = j["error"].get("data") or {}
        return None, (data.get("message") or "动作加载失败")[:200]
    act = j.get("result")
    if not act:
        return None, "动作 %s 解析为空" % action_id
    return act, None


BOUNCE_TARGETS = ("/my/home", "/my", "/web/login", "/login", "/web", "/apps")


def act_url_reach(sess, url):
    """act_url 落地判据：**不能是被弹回门户/登录**（那等于「菜单看得见、点进去点不开」）。

    为什么单独有这条（verifier 实测的陷阱，2026-09-17）：act_url **不在** Odoo
    ir_ui_menu._visible_menu_ids 的 MODEL_BY_TYPE 里 ⇒ 没有「目标模型读权限」那道闸，
    菜单可见性只由 groups 决定；一旦路由守卫比菜单组更严（例如菜单=教务组、守卫=仅系统组），
    就会出现「教务看得见、点进去 303 回 /my/home」，而只判 HTTP 状态码（跟随跳转后仍 200）抓不到。
    所以这里**显式判落地 URL**：被弹回门户/登录即 FAIL。
    """
    try:
        r0 = sess.get(BASE + url, allow_redirects=False, timeout=60)
    except Exception as exc:  # noqa: BLE001
        return False, "%s 请求异常 %s" % (url, exc)
    if r0.status_code == 200:
        return True, "%s HTTP 200（原地落地）" % url
    if r0.status_code in (301, 302, 303, 307, 308):
        loc = r0.headers.get("Location") or ""
        path = loc.split("?")[0]
        if path in BOUNCE_TARGETS and path != url:
            return False, ("%s → %s %s —— 被弹回门户/登录（菜单可见但路由不放行 = 死角）"
                           % (url, r0.status_code, path))
        try:
            r1 = sess.get(BASE + path if path.startswith("/") else loc,
                          allow_redirects=True, timeout=60)
        except Exception as exc:  # noqa: BLE001
            return False, "%s 跟随跳转异常 %s" % (url, exc)
        if r1.status_code < 400 and not any(t in r1.url for t in BOUNCE_TARGETS):
            return True, "%s → %s → HTTP %s（设计性跳转）" % (url, path, r1.status_code)
        return False, "%s → %s → %s（最终 %s）" % (url, path, r1.url.replace(BASE, ""), r1.status_code)
    return False, "%s HTTP %s" % (url, r0.status_code)


def model_caps(s, model):
    """该模型对当前身份的 读/写/建/删 能力（check_access_rights，不抛异常）。"""
    caps = {}
    for op in ("read", "write", "create", "unlink"):
        ok, val = call(s, model, "check_access_rights", [op], {"raise_exception": False})
        caps[op] = val if ok else "ERR"
    return caps


def caps_text(caps):
    mark = {"read": "读", "write": "写", "create": "建", "unlink": "删"}
    return "".join("%s%s" % (mark[op], "✓" if caps.get(op) is True else "✗")
                   for op in ("read", "write", "create", "unlink"))


def view_field_labels(s, model, views):
    """取视图 arch 里的字段 + 字段标签（关键元素的来源，不写死文案）。

    视图 arch 常常只写 <field name="x"/>（没有 string=），所以还要用 fields_get
    把字段名翻成**当前语言的标签**——渲染出来的表头是「姓名/状态」这类标签，
    拿字段名去比对会全判失败（第一版就是这么错的）。
    """
    ok, res = call(s, model, "get_views", [views, {}])
    if not ok:
        return None, res
    labels, archs = [], {}
    for vid, v in (res.get("views") or {}).items():
        arch = v.get("arch") or ""
        archs[str(vid)] = arch
        for m in re.finditer(r'<field\s+name="([^"]+)"', arch):
            labels.append(m.group(1))
    label_map = {}
    names = sorted(set(labels))[:60]
    if names:
        okf, fields = call(s, model, "fields_get", [names, ["string"]])
        if okf and isinstance(fields, dict):
            label_map = {k: (v or {}).get("string") for k, v in fields.items()}
    return {"labels": labels, "archs": archs, "label_map": label_map,
            "models": res.get("models")}, None


# ---------------------------------------------------------------- psql
def psql(sql, want_rows=False):
    """只读 SELECT（-tA -F '|' -c）。标量直接返回文本，多行用 db_rows() 切分。

    ⚠ 必须带 -c：漏了它 psql 会把 SQL 当数据库名，报错或返回空 —— 曾经把
    「有效组」读成空、把红线自查误报成 FAIL。
    """
    cmd = ["docker", "exec", DB_CONTAINER, "psql", "-U", "odoo", "-d", DB_NAME,
           "-tA", "-F", "|", "-c", sql]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError("psql 失败：%s" % p.stderr.strip()[:300])
    return p.stdout.strip()


def db_rows(model_table, cols, where="TRUE"):
    q = "SELECT %s FROM %s WHERE %s" % (cols, model_table, where)
    out = psql(q, want_rows=True)
    return [ln.split("|") for ln in out.splitlines() if ln.strip()] if out else []


def cleanup(marker_ids=None):
    """清场：先按 id 精确删，再按【冒烟】标记兜底删；返回 (deleted, leftover)。

    leftover 口径 = ① 本次运行建过的 id 仍在（任何一张表）；② 全库按标记还能查到行。
    两条都为 0 才算清场干净（验收③ leftover=0）。
    """
    deleted = []
    # ① 按 id 精确删（依赖顺序：明细 → 主表）
    order = ["op_attendance_line", "op_attendance_sheet", "edu_grade_history",
             "op_exam_attendees", "op_attendance_register", "op_exam", "edu_application"]
    for table in order:
        ids = [i for t, i in (marker_ids or CREATED) if t == table]
        if not ids:
            continue
        try:
            psql("DELETE FROM %s WHERE id IN (%s)" % (table, ",".join(str(i) for i in ids)))
            deleted.append("%s×%d" % (table, len(ids)))
        except Exception as exc:  # noqa: BLE001
            log("WARN | 清场 %s 失败：%s" % (table, exc))
    # ② 按标记兜底（含运行期异常留下的残件）
    tag_where = {
        "op_attendance_line": "remark LIKE '%s'" % TAG_SQL,
        "edu_grade_history": "exam_id IN (SELECT id FROM op_exam WHERE name LIKE '%s')" % TAG_SQL,
        "op_attendance_sheet": "register_id IN (SELECT id FROM op_attendance_register WHERE name LIKE '%s')" % TAG_SQL,
        "op_exam_attendees": "note LIKE '%s' OR exam_id IN (SELECT id FROM op_exam WHERE name LIKE '%s')" % (TAG_SQL, TAG_SQL),
        "op_attendance_register": "name LIKE '%s'" % TAG_SQL,
        "op_exam": "name LIKE '%s'" % TAG_SQL,
        "edu_application": "name LIKE '%s'" % TAG_SQL,
    }
    for table in order:
        try:
            psql("DELETE FROM %s WHERE %s" % (table, tag_where[table]))
        except Exception as exc:  # noqa: BLE001
            log("WARN | 清场(标记) %s 失败：%s" % (table, exc))
    # ③ 核对
    left = {}
    for table, rec_id in (marker_ids or CREATED):
        n = int(psql("SELECT count(*) FROM %s WHERE id=%d" % (table, rec_id)) or 0)
        if n:
            left["%s#%d" % (table, rec_id)] = n
    for table in ("op_attendance_line", "op_attendance_sheet", "op_attendance_register",
                  "op_exam_attendees", "op_exam", "edu_application"):
        n = int(psql("SELECT count(*) FROM %s WHERE %s" % (table, tag_where[table])) or 0)
        if n:
            left["%s(标记)" % table] = n
    return deleted, left


# ---------------------------------------------------------------- 浏览器层
# 环境抖动（本地 Odoo dev 服务偶发丢连接）会让客户端回落到 /apps 或报
# ConnectionLostError —— 那是**噪音**，不是权限问题：同一轮里 admin 打开
# 一个已知可用的菜单也会这样。所以 L3 一律「重试若干次取最好结果」，并把
# 重试次数写进读数，避免把环境抖动当成「点不开」。
TRANSIENT_MARKS = ("ConnectionLostError", "ERR_EMPTY_RESPONSE", "ERR_CONNECTION_RESET",
                   "ERR_CONNECTION_REFUSED", "Failed to fetch", "ServiceWorker",
                   # Owl 生命周期错误在高负载下也会偶发（实测：全量扫时 HTML/CSS 编辑器弹
                   # 「哎呀！」，同一菜单随后单跑 3/3 正常）——按抖动重试；真要复现三次才算红。
                   "OwlError", "owl lifecycle")
ERROR_MARKS = ("AccessError", "Access Error", "不允许访问", "已禁止访问", "Traceback",
               "哎呀", "Forbidden", "Access Denied", "MissingError")

PROBE_JS = r"""() => {
  const txt = el => (el ? el.innerText : '');
  const errDlg = document.querySelector('.o_error_dialog');
  const dialogs = [...document.querySelectorAll('.o_dialog .modal-content')].map(txt);
  const body = document.body ? document.body.innerText : '';
  const access = /AccessError|Access Error|不允许访问|已禁止访问|Traceback/.test(body);
  const views = ['.o_list_view','.o_kanban_view','.o_form_view','.o_graph_view',
                 '.o_pivot_view','.o_calendar_view','.o_activity_view','.o_cohort_view',
                 '.o_gantt_view','.o_map_view'].filter(s => document.querySelector(s));
  let rows = 0; const ths = [];
  const lv = document.querySelector('.o_list_view');
  if (lv) { rows = lv.querySelectorAll('tbody tr.o_data_row').length;
            lv.querySelectorAll('thead th').forEach(e => { const t = e.innerText.trim(); if (t) ths.push(t); }); }
  const kv = document.querySelector('.o_kanban_view');
  const cards = kv ? kv.querySelectorAll('.o_kanban_record').length : 0;
  return { url: location.href, crumb: txt(document.querySelector('.o_breadcrumb')).trim(),
           cp: !!document.querySelector('.o_control_panel'), views, rows, cards,
           ths: ths.slice(0, 14), errDialog: txt(errDlg).slice(0, 300),
           dialogs: dialogs.map(d => d.replace(/[ \t\n]+/g, ' ').slice(0, 200)),
           accessFlag: access, text: body.replace(/[ \t]+/g, ' ').slice(0, 600) };
}"""


def browser_probe(menus_to_check, sess, attempts=3):
    """L3：真浏览器逐菜单渲染检查（含环境抖动重试）。返回 (rows, error)。"""
    results = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "未安装 playwright（pip3 install playwright && playwright install chrome）"
    sid = sess.cookies.get("session_id")
    host = BASE.split("//")[-1].split(":")[0]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(locale="zh-CN", viewport={"width": 1500, "height": 950})
        ctx.add_cookies([{"name": "session_id", "value": sid, "domain": host, "path": "/"}])
        page = ctx.new_page()
        console = []

        def on_console(msg):
            if msg.type == "error":
                console.append(msg.text[:300])

        page.on("console", on_console)
        for item in menus_to_check:
            mid, aid, area = item["id"], item["action_id"], item.get("area")
            action = item.get("action") or {}
            url = "%s/odoo/action-%s?menu_id=%s" % (BASE, aid, mid)
            row = {"id": mid, "path": item["path"], "area": area, "aid": aid, "url": url,
                   "attempts": 0, "transient": 0, "action": action}
            for attempt in range(1, attempts + 1):
                console.clear()
                row["attempts"] = attempt
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    try:
                        page.wait_for_selector(
                            ".o_control_panel, .o_error_dialog, .o_dialog", timeout=15000)
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(900)
                    # act_url：等客户端跳出 /odoo（跳到门户页）
                    if action.get("type") == "ir.actions.act_url":
                        try:
                            page.wait_for_url(
                                lambda u: "/odoo" not in u, timeout=8000)
                        except Exception:  # noqa: BLE001
                            pass
                        page.wait_for_timeout(600)
                    row.update(page.evaluate(PROBE_JS))
                    row["exc"] = None
                except Exception as exc:  # noqa: BLE001
                    row["exc"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
                    row.update({"cp": False, "views": [], "ths": [], "crumb": "",
                                "errDialog": "", "dialogs": [], "accessFlag": False,
                                "text": "", "url": url})
                row["console"] = list(console)
                transient = (any(m in c for c in console for m in TRANSIENT_MARKS)
                             or row.get("url", "").endswith("/apps")
                             or "/web/login" in row.get("url", ""))
                if transient:
                    row["transient"] += 1
                    if attempt < attempts:
                        page.wait_for_timeout(2000)
                        continue
                break
            results.append(row)
        browser.close()
    return results, None


def judge_browser(row, expect_labels, action_type):
    """单菜单判据。返回 (ok, detail)。

    顺序有讲究：**先看有没有报错，再看有没有落地内容**。
    ① 向导弹窗（生成时间表 / 生成报告）算正常落地 —— 这类菜单的动作就是开向导，
       没有控制面板、也没有列表视图；把它们判红会掩盖真正的报错。
    """
    if row.get("exc"):
        return False, "打开异常 %s" % row["exc"]
    if row.get("accessFlag"):
        return False, "页面出现 AccessError/不允许访问：%s" % (row.get("errDialog") or row.get("text", "")[:160])
    if row.get("errDialog"):
        return False, "错误弹窗：%s" % row["errDialog"][:160]
    dialogs = " ".join(row.get("dialogs") or [])
    if any(m in dialogs for m in ERROR_MARKS):
        return False, "弹窗含错误信息：%s" % dialogs[:160]
    if action_type == "ir.actions.act_url":
        landed = row.get("url") or ""
        if any(t in landed for t in BOUNCE_TARGETS):
            return False, ("act_url 被弹回 %s —— 菜单可见但路由不放行 = 死角"
                           % landed)
        if not (row.get("text") or "").strip():
            return False, ("act_url 落地页空白（%s，重试 %d 次）"
                           % (landed, row.get("attempts")))
        return True, "act_url 落地 %s（正文 %d 字）" % (landed, len(row.get("text") or ""))
    if action_type == "ir.actions.client":
        if not (row.get("text") or "").strip():
            return False, "client action 白屏（%s）" % row.get("url")
        return True, "client action 落地 %s（正文 %d 字）" % (row.get("url"), len(row.get("text") or ""))
    if action_type in ("ir.actions.server", "ir.actions.report"):
        if not (row.get("cp") or row.get("views") or (row.get("text") or "").strip()):
            return False, "动作执行后没有渲染内容（%s）" % row.get("url")
        return True, "动作落地 %s（%s）" % (row.get("url"), row.get("views") or "无视图容器")
    if dialogs:
        return True, "动作打开向导弹窗：%s" % dialogs[:90]
    if not row.get("cp"):
        if (row.get("url") or "").endswith("/apps"):
            return False, "动作没打开，被弹回应用面板 /apps（重试 %d 次仍复现）" % row.get("attempts")
        return False, "没有渲染出控制面板（%s）" % (row.get("text", "")[:120] or row.get("url"))
    if not row.get("views"):
        return False, "没有视图容器（%s）" % (row.get("text", "")[:120] or row.get("url"))
    ths = [t for t in row.get("ths") or []]
    if "o_list_view" in row["views"] and expect_labels:
        hit = [lab for lab in expect_labels if any(lab and lab in t for t in ths)]
        if not hit:
            return False, "列表表头未出现视图字段关键元素（表头=%s / 期望其一=%s）" % (ths[:6], expect_labels[:6])
        return True, "渲染 %s，行=%s，关键元素命中=%s" % (row["views"], row.get("rows"), hit[:3])
    return True, "渲染 %s（cards=%s rows=%s）" % (row["views"], row.get("cards"), row.get("rows"))


# ---------------------------------------------------------------- 可见菜单口径（A/B 两把尺子）
# 「教务可见菜单有多少条」这个数字**必须自带口径**，否则不可复现：本仓实测同一天里
#   · 口径 A（ORM）  ir.ui.menu.with_user(<角色>)._visible_menu_ids()  → 195 条 / 21 根
#   · 口径 B（前端）  /web/webclient/load_menus 渲染树                → 181 节点 / 12 应用
# 差的是「黑名单菜单」+「父级不可见 ⇒ 客户端永远点不到」的孤儿（后者被 load_menus 剔除，
# 见 Odoo base/models/ir_ui_menu.py:257-259 的注释）。两把尺子都对，量的不是同一件事：
#   · L1 判据用 **B**（用户真正能在界面里点到的那份树）；
#   · A 与 verifier 的独立读数同 API，用来交叉对账。
# 口径 A 走 `docker compose exec web odoo shell`（只读求值；RPC 不能调私有方法 _visible_menu_ids）。
MENU_SCOPE_SHELL = """import json
u = env['res.users'].search([('login', '=', '%(login)s')], limit=1)
Menu = env['ir.ui.menu'].with_user(u)
ids = Menu._visible_menu_ids()
menus = Menu.browse(list(ids))
roots_strict = [m.id for m in menus if not m.parent_id]
roots_eff = [m.id for m in menus if not m.parent_id or m.parent_id.id not in ids]
print('JSON::' + json.dumps({'uid': u.id, 'count': len(ids), 'roots': len(roots_strict),
                             'roots_effective': len(roots_eff), 'ids': sorted(ids)}))
"""


def orm_menu_scope(login, timeout=180):
    """口径 A：跑一段只读的 odoo shell，返回 dict（uid/count/roots/roots_effective）。

    返回 (data, err)；data 为 None 时 err 写明为什么（容器/命令不可用）。
    """
    snippet = MENU_SCOPE_SHELL % {"login": login}
    attempts = [
        ["docker", "compose", "exec", "-T", os.environ.get("EDU_WEB_SERVICE", "web"),
         "odoo", "shell", "--db_host=db", "--db_port=5432", "--db_user=odoo",
         "--db_password=odoo", "--no-http", "-c", "/etc/odoo/odoo.conf", "-d", DB_NAME],
        ["docker", "exec", "-i", os.environ.get("EDU_WEB_CONTAINER", "edu19-clone-web-1"),
         "odoo", "shell", "--db_host=localhost", "--db_port=5432", "--db_user=odoo",
         "--db_password=odoo", "--no-http", "-d", DB_NAME],
    ]
    last = ""
    for cmd in attempts:
        try:
            p = subprocess.run(cmd, input=snippet, capture_output=True, text=True,
                               timeout=timeout, cwd=REPO_ROOT)
        except Exception as exc:  # noqa: BLE001
            last = "%s: %s" % (type(exc).__name__, exc)
            continue
        if p.returncode != 0:
            last = "退出码 %s：%s" % (p.returncode, (p.stderr or p.stdout).strip()[-200:])
            continue
        for line in reversed((p.stdout or "").splitlines()):
            if line.startswith("JSON::"):
                try:
                    return json.loads(line[6:]), None
                except ValueError as exc:
                    last = "JSON 解析失败：%s" % exc
                    break
        last = "输出里没有 JSON:: 行（末尾：%s）" % (p.stdout or "")[-160:]
    return None, last


def report_menu_scope(uid, menus, payload):
    """把两种口径都打印出来：定义 + 命令 + 条数/根数 + 库 + 采集时刻（可引用、可复现）。"""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nav = edu_nav_state()
    nodes = {k: v for k, v in payload.items() if k.isdigit()}
    apps = {v.get("appID") for v in nodes.values() if v.get("appID")}
    data, err = orm_menu_scope(BACKOFFICE[0])
    if data:
        rec("PASS", "口径·A(ORM)",
            "教务可见菜单（口径：ir.ui.menu.with_user(%s)._visible_menu_ids()）"
            "= %d 条 / %d 根（根=parent_id=False 且在可见集内；有效根 %d）｜库 %s（本地克隆）｜采集 %s｜%s"
            % (BACKOFFICE[0], data["count"], data["roots"], data["roots_effective"],
               DB_NAME, stamp, nav))
    else:
        rec("FAIL", "口径·A(ORM)",
            "拿不到 ORM 口径读数（%s）—— 复跑命令见 docs/plans/perm-split-audit.md §2.1" % err)
    rec("PASS", "口径·B(前端)",
        "教务可见菜单（口径：前端 /web/webclient/load_menus 渲染树）"
        "= %d 节点 / %d 应用（应用=payload 的 appID 分组）｜库 %s（本地克隆）｜采集 %s｜%s"
        "（L1 判据用它：这是用户真正能在界面里点到的树）"
        % (len(nodes), len(apps), DB_NAME, stamp, nav))
    if data:
        rec("INFO", "口径·差集",
            "A−B = %d 条：黑名单菜单 + 「父级不可见 ⇒ 客户端永远点不到」的孤儿"
            "（后者被 load_menus 剔除，Odoo base/models/ir_ui_menu.py:257-259）；"
            "两把尺子量的不是同一件事，引用时必须带口径" % (data["count"] - len(nodes)))
    rec("PASS", "口径·引用串",
        "【可引用·三要素=库+时刻+是否含 edu_nav 收口】教务可见菜单（口径 A："
        "ir.ui.menu.with_user(%s)._visible_menu_ids()，条数/根数，%s，%s，%s）= %s；"
        "口径 B（前端 load_menus 渲染树，节点/应用）= %d / %d"
        % (BACKOFFICE[0], DB_NAME, stamp, nav,
           ("%d / %d" % (data["count"], data["roots"])) if data else "未取到",
           len(nodes), len(apps)))
    return data, {"nodes": len(nodes), "apps": len(apps), "at": stamp, "edu_nav": nav}

# ---------------------------------------------------------------- 区分度（教务 vs 教师）
# verifier 踩过的坑：拿「教师看不见」当权限分层的证据时，若那条菜单本身 active=False
# （全局停用 ⇒ 对**任何人**都不可见），教师「通过」是白过。所以主集必须是
#   **教务可见 ∧ 教师不可见 ∧ active=True**
# 并显式报出「因全局停用而对教师不可见」的部分（它结构上不该落进主集）。
FACULTY = ("faculty@local", "demo123")


def edu_nav_state():
    """三要素之一：本地库是否已应用 edu_nav 菜单收口（生产没有 edu_nav，数字不可互替）。"""
    try:
        val = psql("SELECT value FROM ir_config_parameter "
                   "WHERE key = 'edu_nav.consolidated_count'")
    except Exception:  # noqa: BLE001
        return "未知（读不到 ir_config_parameter）"
    n = int(val or 0) if str(val or 0).isdigit() else 0
    return ("已应用 edu_nav 菜单收口（consolidated_count=%d）" % n) if n else \
        "未应用 edu_nav 菜单收口（consolidated_count 为空/0 —— 生产即此态，数字不可与本库互替）"


def discrimination_reading(bo_payload, s_bo, a_bo=None):
    """返回 (data, err)：教务可见 ∧ 教师不可见 ∧ active 的主集读数（B 与 A 两个口径）。"""
    s_fac, fac_uid, err = sess_login(*FACULTY)
    if not fac_uid:
        return None, "教师账号登录失败：%s" % err
    fac_payload = s_fac.get(BASE + "/web/webclient/load_menus?unique=disc", timeout=60).json()
    bo_ids = {int(k) for k in bo_payload if str(k).isdigit()}
    fac_ids = {int(k) for k in fac_payload if str(k).isdigit()}
    active_ids = {int(x) for x in psql("SELECT id FROM ir_ui_menu WHERE active").split() if x}
    dead_ids = {int(x) for x in psql("SELECT id FROM ir_ui_menu WHERE NOT active").split() if x}
    diff = bo_ids - fac_ids
    main = sorted(diff & active_ids)
    leak = sorted(diff & dead_ids)
    # 示例按「不同应用根各取一条」，别让 网站 的噪音刷屏（引用时更有代表性）
    parent, top = {}, {}
    for k, v in bo_payload.items():
        if not str(k).isdigit():
            continue
        for c in (v.get("children") or []):
            parent[str(c)] = k
    def _root(mid):
        cur, seen = str(mid), set()
        while cur in parent and cur not in seen:
            seen.add(cur)
            cur = parent[cur]
        return cur
    picked, used_roots = [], set()
    for i in main:
        r = _root(i)
        if r in used_roots:
            continue
        used_roots.add(r)
        picked.append(i)
        if len(picked) >= 6:
            break
    names = {}
    if picked:
        rows = psql("SELECT id || '|' || coalesce(name::json->>'zh_CN', name::json->>'en_US', name::text)"
                    " FROM ir_ui_menu WHERE id IN (%s)"
                    % ",".join(str(i) for i in picked), want_rows=True)
        for ln in rows.splitlines():
            if "|" in ln:
                mid, nm = ln.split("|", 1)
                names[int(mid)] = nm
    examples = ["%s(%s)" % (names.get(i, "?"), i) for i in picked]
    # 口径 A（ORM）下的同一个主集：与 verifier 的读数口径一致，便于对账
    a_fac, a_err = orm_menu_scope(FACULTY[0])
    main_a = []
    if a_bo and a_bo.get("ids") and a_fac:
        main_a = sorted((set(a_bo["ids"]) - set(a_fac["ids"])) & active_ids)
    return {"fac_uid": fac_uid, "bo": len(bo_ids), "fac": len(fac_ids),
            "main": main, "main_a": main_a, "a_err": a_err, "leak": leak,
            "dead_total": len(dead_ids),
            "fac_roots": len({v.get("appID") for v in fac_payload.values()
                               if isinstance(v, dict) and v.get("appID")}),
            "fac_ids": sorted(fac_ids), "examples": examples}, None


def report_discrimination(bo_payload, s_bo, scope_meta, a_bo=None):
    """打印区分度读数（主集条数 / 全局停用零命中 / 示例），数字自带三要素。"""
    data, err = discrimination_reading(bo_payload, s_bo, a_bo)
    tag = "%s（本地克隆）｜%s｜含 edu_nav：%s" % (DB_NAME, scope_meta["at"], scope_meta["edu_nav"])
    if not data:
        rec("FAIL", "区分度·教务vs教师", "拿不到读数：%s" % err)
        return None
    if data["leak"]:
        rec("FAIL", "区分度·教务vs教师",
            "主集里混进了 %d 条全局停用（active=False）菜单：%s —— 这类菜单对任何人都不可见，"
            "不能当「教师被权限挡住」的证据" % (len(data["leak"]), data["leak"][:6]))
    else:
        rec("PASS", "区分度·教务vs教师",
            "主集【教务可见 ∧ 教师不可见 ∧ active=True】= %d 条（示例：%s）；"
            "全局停用(active=False，对任何人不可见)= %d 条，**0 条**混进主集 ｜ %s"
            % (len(data["main"]), "、".join(data["examples"]), data["dead_total"], tag))
    rec("INFO", "区分度·口径",
        "教务可见 %d / 教师可见 %d（教师应用根 %d）｜主集=教务可见−教师不可见 中仍 active 的部分；"
        "教师不可见的原因两类：① 菜单组不给教师（=分层证据）② 全局停用（**不是**证据） ｜ %s"
        % (data["bo"], data["fac"], data["fac_roots"], tag))
    if data["main_a"] or data["a_err"]:
        rec("INFO", "区分度·口径A对照",
            "同主集在口径 A（ORM _visible_menu_ids，与 verifier 同 API）= %s 条%s ｜ %s"
            % (len(data["main_a"]) if data["main_a"] else "未取到",
               "（口径 A 会多算「父级不可见」的孤儿，所以通常大于口径 B）", tag))
    return data

# ---------------------------------------------------------------- 入口回补与孤立根审计
# 背景（t1 增量 4，队长选 (a)）：`邀请码`(542) / `老账号补挂身份`(606) 两个根被菜单收口
# 停用（只写 active=False、没写 parent_id），而注册流程仍要求邀请码 ⇒ 学校**发不出新账号**。
# 处置：**不动** edu_nav 的 active=False 记录，在已有根 `学生信息(257) → 配置(261)` 下新建两条子菜单
# （新 xmlid，与收口口径一致：入口挂在容器下，不回根菜单）。
RESTORED_ENTRIES = [
    ("edu_portal.menu_edu_invite_code_entry", "邀请码", "ir.actions.act_window,687"),
    ("edu_portal.menu_edu_relink_identity_entry", "老账号补挂身份", "ir.actions.act_url,745"),
]
# 孤立根例外（parent NULL + active=False 的根里，**能力已退役或另有活入口**的）——逐条写理由。
# 判据是「该能力是否还有活入口」，不是「这条记录是否 active」；命中且无理由即 FAIL。
ORPHAN_ROOT_EXCEPTIONS = {
    # 例：123: "能力已退役（说明）",
}

# 退役说明（只用于把「为什么它不算入口缺失」写清楚，不改变判据）：
# 判据仍是「有没有数据 / act_url 能不能开」——模型可读 ≠ 能力还活着。
ORPHAN_ROOT_NOTES = {
    547: "在线学习（website_slides）：收口轮确认下线（docs/audit/menu-consolidation/diff-report.md:66"
         "「档1 整棵停用；记录保留、可一键回滚」），且 slide.channel / slide.slide 均为 0 行 ⇒ 没有该有入口的内容",
    566: "数据清除：整棵停用（对任何人都不可见，属收口决定）",
    121: "联系人：整棵停用；能力入口在门户「通讯录 /my/contacts」",
    142: "发票：整棵停用；能力入口在门户「费用账单 /my/fees」",
    196: "员工：整棵停用；能力入口在门户「通讯录/用户管理」",
}


def orm_visible_ids(login):
    """某身份的可见菜单 id 集合（口径 A：_visible_menu_ids）。返回 (set|None, err)。"""
    data, err = orm_menu_scope(login)
    return (set(data["ids"]) if data and data.get("ids") else None), err


def report_restored_entries(s_bo):
    """读两条被收口挂掉的入口：三身份可见性对照 + 菜单总数变化 + 影响面。"""
    ids = {mid for _, _, _ in ()}  # 占位，实际 id 从 DB 按 xmlid 取
    rows = psql("SELECT d.module || '.' || d.name || '|' || d.res_id "
                "FROM ir_model_data d WHERE d.model='ir.ui.menu' AND d.name IN "
                "('menu_edu_invite_code_entry','menu_edu_relink_identity_entry')", want_rows=True)
    xmlid_to_id = {}
    for ln in rows.splitlines():
        if "|" in ln:
            x, i = ln.split("|", 1)
            xmlid_to_id[x] = int(i)
    total = int(psql("SELECT count(*) FROM ir_ui_menu") or 0)
    dead = psql("SELECT count(*) FROM ir_ui_menu WHERE NOT active")
    readings = {}
    for login, label in ((BACKOFFICE[0], "教务"), (FACULTY[0], "教师"), (ADMIN[0], "管理员")):
        vis, err = orm_visible_ids(login)
        readings[label] = vis
        if vis is None:
            rec("FAIL", "入口·三身份", "%s(%s) 取不到 _visible_menu_ids：%s" % (label, login, err))
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for xmlid, label, action in RESTORED_ENTRIES:
        mid = xmlid_to_id.get(xmlid)
        if not mid:
            rec("FAIL", "入口·回补", "%s（%s）在库里找不到 —— 入口没补回来" % (label, xmlid))
            continue
        marks = []
        for nm, vis in readings.items():
            marks.append("%s%s" % (nm, "✓" if vis and mid in vis else "✗"))
        ok = (readings.get("教务") and mid in readings["教务"]
              and readings.get("教师") is not None and mid not in readings["教师"]
              and readings.get("管理员") and mid in readings["管理员"])
        rec("PASS" if ok else "FAIL", "入口·三身份",
            "%s（menu %d，%s）= %s ｜ 三身份对照（口径 A：_visible_menu_ids）｜%s（本地克隆）｜%s"
            % (label, mid, action, " ".join(marks), DB_NAME, stamp))
    rec("INFO", "入口·菜单总数",
        "ir.ui.menu 总数 = %d（收口基线 605 → 回补两条子菜单 607；停用 %s 条）｜%s（本地克隆）｜%s"
        % (total, dead, DB_NAME, stamp))
    return xmlid_to_id, readings, total


def orphan_root_audit(s):
    """同类孤立项巡检：parent NULL + active=False 的根里，哪些**能力还活着却没有入口**。"""
    rows = psql("SELECT m.id || '|' || coalesce(m.name::json->>'zh_CN', m.name::json->>'en_US') || '|' "
                "|| coalesce(m.action, '') FROM ir_ui_menu m WHERE NOT m.active AND m.parent_id IS NULL "
                "ORDER BY m.id", want_rows=True)
    orphans = []
    for ln in rows.splitlines():
        parts = ln.split("|")
        if len(parts) < 3:
            continue
        mid, nm, act = parts[0], parts[1], "|".join(parts[2:])
        orphans.append((int(mid), nm, act))
    entryless, retired, has_entry = [], [], []
    for mid, nm, act in orphans:
        live = 0
        if act:
            live = int(psql("SELECT count(*) FROM ir_ui_menu WHERE active AND action = '%s'" % act) or 0)
        if live:
            has_entry.append((mid, nm, act, live))
            continue
        # 没有活菜单指向同一 action：看这条能力本身还活着吗
        alive, why = False, "action 为空（纯容器）"
        if act.startswith("ir.actions.act_url,"):
            url = psql("SELECT coalesce(url, '') FROM ir_act_url WHERE id = %s" % act.split(",")[1])
            code = 0
            try:
                code = s.get(BASE + url, allow_redirects=True, timeout=45).status_code
            except Exception:  # noqa: BLE001
                code = 0
            alive, why = (code < 400), "act_url %s → HTTP %s" % (url, code)
        elif act.startswith("ir.actions.act_window,"):
            model = psql("SELECT coalesce(res_model, '') FROM ir_act_window WHERE id = %s" % act.split(",")[1])
            okm, cnt = call(s, model, "search_count", [[]]) if model else (False, 0)
            # 「能力还活着吗」的判据用**有没有数据**，不是「模型可不可读」：
            # 退役应用（如 547 在线学习 / website_slides：slide.channel 0 行）模型当然可读，
            # 但没有数据 ⇒ 没有「该有入口」的能力（收口文档也写明「确认下线」）。
            n = int(cnt) if okm and isinstance(cnt, int) else 0
            alive, why = (okm and n > 0), "act_window %s（可读=%s，行数=%d）" % (model or "?", okm, n)
        if alive and mid not in ORPHAN_ROOT_EXCEPTIONS:
            entryless.append((mid, nm, act, why))
        else:
            retired.append((mid, nm, act, why))
    for mid, nm, act, live in has_entry[:12]:
        rec("PASS", "孤立根·有此能力活入口",
            "menu %d %s（%s）已停用，但另有 %d 条活菜单指向同一 action ⇒ 能力有入口" % (mid, nm, act, live))
    for mid, nm, act, why in entryless:
        rec("FAIL", "孤立根·能力无入口",
            "menu %d %s（%s）停用且**没有任何活菜单指向它**，但能力仍可用（%s）—— 属同类「入口缺失」，"
            "要么补入口，要么在 ORPHAN_ROOT_EXCEPTIONS 写明退役理由" % (mid, nm, act, why))
    rec("INFO", "孤立根·合计",
        "parent NULL + active=False 的根共 %d 条：另有活入口 %d / 能力已退役或纯容器 %d / **能力活着却无入口 %d**"
        % (len(orphans), len(has_entry), len(retired), len(entryless)))
    for mid, nm, act, why in retired:
        note = ORPHAN_ROOT_NOTES.get(mid)
        rec("INFO", "孤立根·已退役", "menu %d %s（%s）：%s%s"
            % (mid, nm, act, why, "；" + note if note else ""))
    return {"orphans": orphans, "has_entry": has_entry, "retired": retired,
            "entryless": entryless}

# ---------------------------------------------------------------- 静态层分离断言（离线）
# 权限分层的核心不变式：**没有任何自家菜单只挂系统组**。
# 反面写法（本轮修掉的 7 个菜单原先都是这个写法）：
#     <menuitem ... groups="base.group_system"/>
# 层分离后教务不在系统组里 ⇒ 菜单对教务**直接消失**（不是"点不开"，是"看不见"）。
# 正确写法是并列：groups="教务组,base.group_system"（教务与开发者都能见）。
#
# 扫描边界（**声明并计数**，每次运行都会打印）：
#   · 只扫 custom_addons/*/views/*.xml —— 我们自己的模块；
#   · 基座 openeducat_erp/ 不在范围：「设置 / 应用」这类只挂系统组的菜单是 Odoo 原生设计，
#     报它就是误报；
#   · custom_addons/*/data/*.xml 不在范围：edu_nav 的收口数据有意用 group_ids=[4] 做
#     「档2：仅超管可见」，那是**声明式策略**而不是漏挂教务组（要改口径去那边改，
#     见 docs/plans/perm-split-audit.md §6.5「边界声明」）。
#
# 例外纪律：确实只该给开发者的自家菜单**必须**登记到 STATIC_GROUP_EXCEPTIONS 并写明理由；
# 不放宽断言、不加通配；例外每次运行都会连同条数一起打印，失效的例外会被点名（可审计）。
# tests/smoke/backoffice_reachability.py → 上溯三层 = 仓库根
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SYS_GROUP = "base.group_system"
STATIC_SCAN_GLOB = "custom_addons/*/views/*.xml"
STATIC_GROUP_EXCEPTIONS = {
    # (相对仓库根路径, menuitem id): "为什么只该给开发者"
    # 目前为空 = 不允许任何自家菜单只挂系统组（2026-09-17 t1 实测 0 处）。
}


def static_scan_system_only_menus(root=None, pattern=None, exceptions=None):
    """离线扫「自家模块的 views/*.xml」，找「groups 集合恰好 == {base.group_system}」的菜单。

    覆盖两种写法：
      · <menuitem groups="x,y"/>（Odoo 19 菜单组的主写法）
      · <record model="ir.ui.menu"><field name="group_ids|groups_id" eval="[(6,0,[ref('...')])]"/></record>
    参数可注入（root/pattern/exceptions）是为了让 --selftest 用合成夹具证明「这把尺子会红」。
    返回 (stats, hits, stale_exceptions)；hits 每条 = (相对路径, 行号, 菜单 id, 组串, 写法)。
    """
    root = root or REPO_ROOT
    pattern = pattern or STATIC_SCAN_GLOB
    exceptions = STATIC_GROUP_EXCEPTIONS if exceptions is None else exceptions
    stats = {"files": 0, "menuitems": 0, "records": 0}
    hits, matched_keys = [], set()
    for path in sorted(glob.glob(os.path.join(root, pattern))):
        rel = os.path.relpath(path, root)
        stats["files"] += 1
        with open(path, encoding="utf-8") as fh:
            text = fh.read()

        def _line_of(pos):
            return text.count("\n", 0, pos) + 1

        def _attr(block, name):
            m = re.search(r'%s\s*=\s*["\']([^"\']*)["\']' % name, block)
            return m.group(1) if m else None

        for m in re.finditer(r"<menuitem\b[^>]*?/?>", text, re.S):
            stats["menuitems"] += 1
            block = m.group(0)
            groups = _attr(block, "groups")
            if not groups:
                continue
            gset = {g for g in re.split(r"[,\s]+", groups) if g}
            if gset != {SYS_GROUP}:
                continue
            mid = _attr(block, "id") or "?"
            key = (rel, mid)
            matched_keys.add(key)
            if key in exceptions:
                continue
            hits.append((rel, _line_of(m.start()), mid, groups, "menuitem groups="))

        for m in re.finditer(
                r'<record\b[^>]*model\s*=\s*["\']ir\.ui\.menu["\'][^>]*>(.*?)</record>',
                text, re.S):
            stats["records"] += 1
            block = m.group(0)
            rid = _attr(block, "id") or "?"
            # 取值必须用「同种引号配对」（(?P=q) 反引用）：eval 值里含单引号
            # （eval="[(6, 0, [ref('base.group_system')])]"），用 [^"']* 会在第一个单引号处截断
            # —— 第一版就是这样漏掉了 record 写法，是 --selftest 抓出来的。
            for fm in re.finditer(
                    r'<field\s+name\s*=\s*["\'](?:group_ids|groups_id)["\'][^>]*?'
                    r'(?:eval|ref)\s*=\s*(?P<q>["\'])(?P<v>.*?)(?P=q)[^>]*/?>',
                    block, re.S):
                refs = set(re.findall(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)", fm.group("v") or ""))
                if refs != {SYS_GROUP}:
                    continue
                key = (rel, rid)
                matched_keys.add(key)
                if key in exceptions:
                    continue
                hits.append((rel, _line_of(m.start()), rid, "group_ids=[%s]" % SYS_GROUP,
                             "record group_ids="))
    stale = sorted(k for k in exceptions if k not in matched_keys)
    return stats, hits, stale


def static_selftest():
    """用合成夹具证明静态断言**会红**、例外与失效例外两条路径都对（尺子先校对再量东西）。"""
    import tempfile

    fixture = """<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <menuitem id="menu_demo_bad" name="只给系统组" groups="base.group_system"/>
    <menuitem id="menu_demo_parallel" name="教务+系统"
              groups="openeducat_core.group_op_back_office_admin,base.group_system"/>
    <menuitem id="menu_demo_user" name="全体" groups="base.group_user"/>
    <record id="rec_demo_bad" model="ir.ui.menu">
        <field name="group_ids" eval="[(6, 0, [ref('base.group_system')])]"/>
    </record>
</odoo>
"""
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    with tempfile.TemporaryDirectory() as tmp:
        vdir = os.path.join(tmp, "custom_addons", "demo_mod", "views")
        os.makedirs(vdir)
        with open(os.path.join(vdir, "demo_views.xml"), "w", encoding="utf-8") as fh:
            fh.write(fixture)
        stats, hits, stale = static_scan_system_only_menus(tmp, "custom_addons/*/views/*.xml", {})
        ids = sorted(h[2] for h in hits)
        check("合成夹具扫到 1 文件/3 menuitem/1 record",
              (stats["files"], stats["menuitems"], stats["records"]) == (1, 3, 1), str(stats))
        check("命中恰好是两条孤组声明（menuitem + record）",
              ids == ["menu_demo_bad", "rec_demo_bad"], str(ids))
        check("并列写法（教务+系统）不算命中",
              "menu_demo_parallel" not in ids, str(ids))
        check("纯 base.group_user 不算命中", "menu_demo_user" not in ids, str(ids))
        check("命中带行号", all(isinstance(h[1], int) and h[1] > 0 for h in hits),
              str([(h[2], h[1]) for h in hits]))
        rel = os.path.join("custom_addons", "demo_mod", "views", "demo_views.xml")
        _, hits2, stale2 = static_scan_system_only_menus(
            tmp, "custom_addons/*/views/*.xml",
            {(rel, "menu_demo_bad"): "合成夹具：登记后不再报", (rel, "rec_demo_bad"): "同上"})
        check("显式例外生效（0 命中、0 失效）", (len(hits2), len(stale2)) == (0, 0),
              "hits=%d stale=%d" % (len(hits2), len(stale2)))
        _, _, stale3 = static_scan_system_only_menus(
            tmp, "custom_addons/*/views/*.xml", {(rel, "menu_not_exist"): "失效例外"})
        check("失效例外被点名（可审计）", len(stale3) == 1, str(stale3))

    ok = all(c[1] for c in checks)
    for name, good, detail in checks:
        print("%s | 静态自证 | %s%s" % ("PASS" if good else "FAIL", name,
                                        "" if good else "｜%s" % detail))
    print("%s | 静态自证 | 断言 %d 条，%d 通过（合成夹具证明这把尺子会红）"
          % ("PASS" if ok else "FAIL", len(checks), sum(1 for c in checks if c[1])))
    return 0 if ok else 1


def static_check():
    """把静态层分离断言接进门禁（离线，先于登录跑：服务不通也能给出结论）。"""
    try:
        stats, hits, stale = static_scan_system_only_menus()
    except Exception as exc:  # noqa: BLE001 - 断言自身出错不许静默
        rec("FAIL", "静态·层分离", "扫描失败（%s: %s）" % (type(exc).__name__, exc))
        return
    bound = ("边界：%s —— %d 个文件 / %d 个 <menuitem> / %d 个 ir.ui.menu <record>"
             "（基座与 data/*.xml 按设计排除）"
             % (STATIC_SCAN_GLOB, stats["files"], stats["menuitems"], stats["records"]))
    if stats["files"] == 0 or stats["menuitems"] == 0:
        # 这条是给「断言自己坏掉」准备的：扫不到东西 ≠ 没有问题（第一版 REPO_ROOT 上溯少一层，
        # 0 文件也报 PASS = 假绿）。边界必须被计数，计数为 0 就是红。
        rec("FAIL", "静态·层分离",
            "扫描面为空（%d 个文件 / %d 个 menuitem）—— 断言没扫到任何菜单，不许当绿；"
            "检查 STATIC_SCAN_GLOB 与 REPO_ROOT" % (stats["files"], stats["menuitems"]))
        return
    if hits:
        for rel, line, mid, groups, how in hits:
            rec("FAIL", "静态·层分离",
                "%s:%d → 菜单 %s 只挂系统组（%s%s）—— 层分离后教务**看不见**这条；"
                "应写成「教务组,base.group_system」并列，或登记进 STATIC_GROUP_EXCEPTIONS 并写明理由"
                % (rel, line, mid, how, groups))
        rec("FAIL", "静态·层分离", "命中 %d 处；%s" % (len(hits), bound))
    else:
        rec("PASS", "静态·层分离",
            "0 处「只挂 base.group_system」的自家菜单（例外清单 %d 条）；%s"
            % (len(STATIC_GROUP_EXCEPTIONS), bound))
    for key in stale:
        rec("INFO", "静态·层分离",
            "例外登记已失效（该菜单已改并列写法或被删）：%s:%s —— 建议删掉这条，保持例外清单可审计"
            % key)

# ---------------------------------------------------------------- 主流程
def dump_baseline(s, uid, menus, path, scope=None):
    """基线快照：教务视角可见菜单（两种口径）+ 各模型读写权（对拍用，不判红）。"""
    acl = {}
    for model in ACL_MODELS:
        row = {}
        for op in ("read", "write", "create", "unlink"):
            ok, val = call(s, model, "check_access_rights", [op], {"raise_exception": False})
            row[op] = (val if ok else "ERR")
        acl[model] = row
    writable = sorted([m for m, r in acl.items() if r.get("write") is True])
    data = {
        "collected_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "base": BASE, "db": DB_NAME, "uid": uid, "role": BACKOFFICE[0],
        "effective_groups": effective_groups(uid),
        # 口径必须随数字一起落盘：A=ORM _visible_menu_ids，B=前端 load_menus 渲染树
        "menu_scope": scope,
        "visible_menu_nodes": len(menus),
        "visible_roots": sorted({m["path"].split(" / ")[0] for m in menus}),
        "menu_nodes": [{"id": m["id"], "path": m["path"], "action_id": m["action_id"],
                        "action_model": m["action_model"]} for m in menus],
        "writable_model_count": len(writable),
        "writable_models": writable,
        "acl": acl,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    log("基线快照已写：%s（可见菜单 B 口径 %d 节点、有效组 %d、可写模型 %d；A 口径见 menu_scope）"
        % (path, len(menus), len(data["effective_groups"]), len(writable)))
    return data


ARCH_BUSINESS_GROUPS = [
    "openeducat_core.group_op_faculty",
    "openeducat_attendance.group_op_attendance_manager",
    "openeducat_timetable.group_op_timetable_manager",
    "openeducat_library.group_op_library",
    "openeducat_exam.group_op_exam_admin",
]

# 有效组 = 直接组 ∪ implied_ids 传递闭包（Odoo19：直接组在 res_groups_users_rel，
# 隐含关系在 res_groups_implied_rel，闭包必须自己递归）。
EFFECTIVE_GROUPS_SQL = """
WITH RECURSIVE g(gid) AS (
  SELECT gid FROM res_groups_users_rel WHERE uid = %d
  UNION
  SELECT r.hid FROM res_groups_implied_rel r JOIN g ON r.gid = g.gid
)
SELECT d.module || '.' || d.name FROM g
JOIN ir_model_data d ON d.model = 'res.groups' AND d.res_id = g.gid
ORDER BY 1
"""


def effective_groups(uid):
    out = psql(EFFECTIVE_GROUPS_SQL % uid, want_rows=True)
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def check_red_lines(s, uid):
    """红线（验收⑤）：教务账号 / 教务组都不得含 base.group_system；
    同时确认「教务=学院领导」这层仍在（业务管理组没被一起拆掉）。

    为什么走 SQL 而不是 ORM：① res.users.has_group 经 /web/dataset/call_kw 调用时
    参数绑定不上（实测 "missing 1 required positional argument"）；② ir.model.data
    对教务账号不可读（Access Rights 组专属）—— 两者都会把「查不到」误报成「没权限」，
    所以这里只读 SQL（docker exec psql SELECT），口径与队长当时的手工读数一致。
    """
    groups = effective_groups(uid)
    if not groups:
        rec("FAIL", "红线·分层口径", "拿不到 backoffice(%d) 的有效组（psql 读失败）" % uid)
        return
    if "base.group_system" in groups:
        rec("FAIL", "红线·教务非管理员",
            "backoffice 有效组里仍有 base.group_system（分层回退）")
    else:
        rec("PASS", "红线·教务非管理员",
            "backoffice 有效组 %d 个，不含 base.group_system" % len(groups))
    # 教务组的 implied_ids 传递闭包里不许再出现 group_system
    n = psql("WITH RECURSIVE g(gid) AS ("
             " SELECT res_id FROM ir_model_data WHERE model='res.groups' "
             "   AND module='openeducat_core' AND name='group_op_back_office_admin'"
             " UNION SELECT r.hid FROM res_groups_implied_rel r JOIN g ON r.gid=g.gid) "
             "SELECT count(*) FROM g JOIN ir_model_data d ON d.model='res.groups' "
             "AND d.res_id=g.gid WHERE d.module='base' AND d.name='group_system'")
    if int(n or 0) > 0:
        rec("FAIL", "红线·教务组无系统管理员",
            "教务组 implied 闭包仍含 base.group_system（见 custom_addons/edu_portal/views/group_tuning.xml）")
    else:
        rec("PASS", "红线·教务组无系统管理员",
            "教务组 implied 闭包不含 base.group_system（group_tuning.xml 生效）")
    # 业务身份仍在（拆掉的是系统管理员身份，不是业务管理身份）
    held = [x.split(".")[-1] for x in ARCH_BUSINESS_GROUPS if x in groups]
    lost = [x.split(".")[-1] for x in ARCH_BUSINESS_GROUPS if x not in groups]
    if lost:
        rec("FAIL", "红线·业务身份仍在", "教务缺业务管理组：%s（拆过头了）" % lost)
    else:
        rec("PASS", "红线·业务身份仍在",
            "教务仍持全部 %d 个业务管理组：%s" % (len(held), held))


def e2e_application(s):
    """① 报名审批：公开报名表建【冒烟】申请 → 审核中 → 已录取（+ 材料核对）。"""
    anon = requests.Session()
    anon.trust_env = False
    anon.proxies = {"http": None, "https": None}
    r = anon.get(BASE + "/apply", timeout=60)
    if r.status_code != 200:
        return False, "公开报名表 /apply 打开失败 HTTP %s" % r.status_code
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    if not m:
        return False, "/apply 页面没有 csrf_token（无法提交）"
    name = TAG + "报名审批-" + datetime.datetime.now().strftime("%m%d-%H%M%S")
    payload = {"csrf_token": m.group(1), "track": "3+1制本科班", "name": name,
               "gender": "男", "id_no": "SMOKE-ID-0001", "church": TAG + "教会",
               "phone": "13000000000", "remark": TAG + "夹具（脚本自动清理）"}
    r2 = anon.post(BASE + "/apply/submit", data=payload,
                   headers={"Referer": BASE + "/apply"}, timeout=60)
    if r2.status_code not in (200, 303):
        return False, "报名提交 HTTP %s" % r2.status_code
    rows = db_rows("edu_application", "id,state", "name LIKE '%s'" % TAG_SQL)
    if not rows:
        return False, "提交后 DB 里查不到【冒烟】申请（表单校验未通过？）"
    app_id, state0 = int(rows[-1][0]), rows[-1][1]
    track("edu.application", app_id)
    if state0 != "new":
        return False, "新申请初始状态应为 new，实际 %s" % state0

    def web_save(vals):
        return call(s, "edu.application", "web_save",
                    [[app_id], vals, {"name": {}, "state": {}, "mat_form": {},
                                      "mat_recommend": {}, "mat_testimony": {}}])

    ok, val = web_save({"state": "review", "mat_form": True, "mat_recommend": True})
    if not ok:
        return False, "教务改「审核中」失败：%s" % val
    st = db_rows("edu_application", "state,mat_form,mat_recommend", "id=%d" % app_id)
    if not st or st[0][0] != "review":
        return False, "DB 反查：状态应为 review，实际 %s" % st
    ok, val = web_save({"state": "admitted", "mat_testimony": True,
                        "mat_calling": True, "mat_diploma": True,
                        "mat_physical": True, "mat_idcard": True})
    if not ok:
        return False, "教务改「已录取」失败：%s" % val
    st = db_rows("edu_application",
                 "state,mat_form,mat_recommend,mat_testimony,mat_calling,mat_diploma,mat_physical,mat_idcard",
                 "id=%d" % app_id)
    row = st[0]
    if row[0] != "admitted" or row[1:] != ["t"] * 7:
        return False, "DB 反查：state/mat_* = %s（期望 admitted + 7 个 t）" % row
    return True, "app#%d 新申请→审核中→已录取，材料 7/7 已勾（DB 反查 state=%s）" % (app_id, row[0])


def e2e_grading(s, uid):
    """② 成绩录入：教务改分 → edu.grade.history 留痕（old/new/source/操作人）。"""
    stamp = datetime.datetime.now().strftime("%m%d-%H%M%S")
    ok, subj = call(s, "op.subject", "search_read", [[], ["id", "name"]], {"limit": 1})
    ok2, stu = call(s, "op.student", "search_read", [[], ["id", "name"]], {"limit": 1})
    if not (ok and subj) or not (ok2 and stu):
        return False, "缺少 op.subject / op.student 基础数据（无法建夹具）"
    vals = {"name": TAG + "成绩留痕巡检-" + stamp,
            "exam_code": "SMOKE-GH-" + stamp.replace("-", ""),
            "subject_id": subj[0]["id"], "total_marks": 100, "min_marks": 60,
            "start_time": "2026-09-17 09:00:00", "end_time": "2026-09-17 10:00:00"}
    ok, res = call(s, "op.exam", "web_save", [[], vals, {"name": {}}])
    if not ok:
        return False, "教务建考试夹具失败：%s" % res
    exam_id = res[0]["id"]
    track("op.exam", exam_id)
    ok, res = call(s, "op.exam.attendees", "web_save",
                   [[], {"exam_id": exam_id, "student_id": stu[0]["id"], "marks": 0,
                         "note": TAG + "夹具"}, {"id": {}, "marks": {}}])
    if not ok:
        return False, "教务建考生行失败：%s" % res
    att_id = res[0]["id"]
    track("op.exam.attendees", att_id)
    ok, res = call(s, "op.exam.attendees", "web_save",
                   [[att_id], {"marks": 73}, {"id": {}, "marks": {}}])
    if not ok:
        return False, "教务改分（0→73）失败：%s" % res
    ok, res = call(s, "op.exam.attendees", "web_save",
                   [[att_id], {"marks": 81}, {"id": {}, "marks": {}}])
    if not ok:
        return False, "教务改分（73→81）失败：%s" % res
    rows = db_rows("edu_grade_history", "old_marks,new_marks,action,source,logged_user_id",
                   "exam_id=%d ORDER BY id" % exam_id)
    marks = db_rows("op_exam_attendees", "marks", "id=%d" % att_id)
    if not rows:
        return False, "改分后 edu.grade.history 没有留痕（留痕链断了）"
    got = [(int(r[0]), int(r[1]), r[2], r[3], int(r[4])) for r in rows]
    expect = [(0, 73, "create", "backend", uid), (73, 81, "update", "backend", uid)]
    if got != expect:
        return False, "留痕读数 %s，期望 %s" % (got, expect)
    if not marks or int(marks[0][0]) != 81:
        return False, "考生分数未落库：%s" % marks
    return True, ("exam#%d att#%d 0→73→81；edu.grade.history %d 条 %s（含操作人 uid=%d）"
                  % (exam_id, att_id, len(rows), got, uid))


def e2e_attendance(s):
    """③ 考勤录入：教务在后台建 点名册 → 点名表 → 出勤明细，落库并置 done。

    注：门户 /attendance/take 是**教师页**（roles.current_faculty() 门禁），教务身份
    会 303 回 /my/home —— 那是设计（见 code-map 铁律 3：需要教师班级数据的页面要求
    op.faculty 绑定），教务的考勤入口就是后台这套 点名册/点名表/出勤明细。两者写的是
    同一批模型，本流程按教务口径真写一遍。
    """
    stamp = datetime.datetime.now().strftime("%m%d%H%M%S")
    ok, crs = call(s, "op.course", "search_read", [[], ["id", "name"]], {"limit": 1})
    ok2, bat = call(s, "op.batch", "search_read", [[], ["id", "name"]], {"limit": 1})
    ok3, stu = call(s, "op.student", "search_read", [[], ["id", "name"]], {"limit": 1})
    if not (ok and crs) or not (ok2 and bat) or not (ok3 and stu):
        return False, "缺少 op.course / op.batch / op.student 基础数据"
    # name/code 都有 size=16 上限；name 前 4 字符即【冒烟】标记（清场依据）
    ok, res = call(s, "op.attendance.register", "web_save",
                   [[], {"name": TAG + stamp[:8], "code": "SMK" + stamp,
                         "course_id": crs[0]["id"], "batch_id": bat[0]["id"]},
                    {"id": {}, "name": {}}])
    if not ok:
        return False, "教务建点名册失败：%s" % res
    reg_id = res[0]["id"]
    track("op.attendance.register", reg_id)
    ok, res = call(s, "op.attendance.sheet", "web_save",
                   [[], {"register_id": reg_id,
                         "attendance_date": datetime.date.today().isoformat()},
                    {"id": {}, "name": {}, "attendance_date": {}, "state": {}}])
    if not ok:
        return False, "教务建点名表失败：%s" % res
    sheet_id = res[0]["id"]
    track("op.attendance.sheet", sheet_id)
    ok, res = call(s, "op.attendance.line", "web_save",
                   [[], {"attendance_id": sheet_id, "student_id": stu[0]["id"],
                         "present": True, "absent": False, "late": False,
                         "remark": TAG + "夹具"},
                    {"id": {}, "present": {}}])
    if not ok:
        return False, "教务写出勤明细失败：%s" % res
    line_id = res[0]["id"]
    track("op.attendance.line", line_id)
    ok, res = call(s, "op.attendance.sheet", "attendance_done", [[sheet_id]])
    if not ok:
        return False, "点名表置 done 失败：%s" % res
    rows = db_rows("op_attendance_sheet", "id,state,attendance_date", "id=%d" % sheet_id)
    line = db_rows("op_attendance_line", "id,present,absent,late,student_id", "id=%d" % line_id)
    if not rows or rows[0][1] != "done":
        return False, "点名表未落库或状态不对：%s" % rows
    if not line or line[0][1] != "t":
        return False, "出勤明细未落库：%s" % line
    try:  # 教师页对照读数（信息项，不判红）
        rr = s.get(BASE + "/attendance/take", allow_redirects=True, timeout=60)
        rec("INFO", "教师页对照", "教务访问 /attendance/take → %s %s（教师页门禁，设计如此）"
            % (rr.status_code, rr.url.replace(BASE, "")))
    except Exception:  # noqa: BLE001
        pass
    return True, ("register#%d sheet#%d(done, %s) line#%d present=t —— 与教师页同表同结构"
                  % (reg_id, sheet_id, rows[0][2], line_id))


def check_narrowed(bo_menus, adm_menus):
    """收口回归：教务不可见（死角已关）+ 超管可见（管理面没丢）。"""
    for xmlid, label in NARROWED:
        bo = [m for m in bo_menus if m.get("xmlid") == xmlid]
        adm = [m for m in adm_menus if m.get("xmlid") == xmlid]
        if bo:
            rec("FAIL", "收口回归", "%s（%s）仍对教务可见 —— 「看得见点不开」的死角没关" % (label, xmlid))
        elif not adm:
            rec("FAIL", "收口回归", "%s（%s）连超管都看不见了 —— 收过头" % (label, xmlid))
        else:
            rec("PASS", "收口回归", "%s：教务不可见、超管可见" % label)


def main():
    ap = argparse.ArgumentParser(description="教务后台可达性巡检（权限分层后）")
    ap.add_argument("--dump", metavar="PATH", help="只取基线快照（菜单+有效组+可写模型）写 JSON，不判红")
    ap.add_argument("--no-browser", action="store_true", help="跳过浏览器层（非门禁口径）")
    ap.add_argument("--all-menus", action="store_true", help="浏览器层也扫全部可见菜单")
    ap.add_argument("--strict-gaps", action="store_true", help="已知历史缺口也判红")
    ap.add_argument("--json", metavar="PATH", help="把结果写 JSON")
    ap.add_argument("--skip-flows", action="store_true", help="跳过 3 条端到端流程")
    ap.add_argument("--selftest", action="store_true",
                    help="只跑静态层分离断言的合成自证（离线，不连服务）")
    args = ap.parse_args()

    if args.selftest:
        return static_selftest()

    log("== 教务后台可达性巡检 ==")
    log("BASE=%s DB=%s 角色=%s 时刻=%s" % (
        BASE, DB_NAME, BACKOFFICE[0],
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    # ---------------- 静态层分离断言（离线，先跑：站点不通也能给出结论）
    static_check()
    s, uid, err = sess_login(*BACKOFFICE)
    if not uid:
        log("FATAL | 教务账号登录失败：%s" % err)
        return 2
    log("登录成功 uid=%s" % uid)
    menus, by_path, raw = load_menus(s)
    log("L1 前端可见菜单 %d 节点（应用根：%s）"
        % (len(menus), "、".join(sorted({m["path"].split(" / ")[0] for m in menus}))))
    # 两种口径都打印（数字必须自带口径：API/条数/根数/库/采集时刻），见 report_menu_scope
    scope_a, scope_b = report_menu_scope(uid, menus, raw)
    # 区分度：教务可见 ∧ 教师不可见 ∧ active 的主集（并与「全局停用」严格分开）
    disc = report_discrimination(raw, s, scope_b, a_bo=scope_a)
    # 入口回补（三身份对照 + 菜单总数）与同类孤立项巡检（增量 4）
    restored, _vis, menu_total = report_restored_entries(s)
    orphans = orphan_root_audit(s)

    if args.dump:
        dump_baseline(s, uid, menus, args.dump,
                      scope={"A_orm": scope_a, "B_frontend": scope_b,
                             "discrimination": disc,
                             "restored_entries": sorted(restored.values()),
                             "menu_total": menu_total,
                             "orphan_roots": {k: len(v) for k, v in orphans.items()}})
        return 0

    # ---------------- 红线自查
    check_red_lines(s, uid)

    # ---------------- 判据自证：act_url 判据必须「有齿」
    # /subject/enroll 是学生页（教务身份实测 303 → /my/home），拿它当**已知会弹回**的样本：
    # 如果 act_url_reach 对它判绿，说明这条判据又变回橡皮图章了。
    ok_canary, why_canary = act_url_reach(s, "/subject/enroll")
    rec("FAIL" if ok_canary else "PASS", "判据·自证(act_url)",
        "已知会弹回的门户页 /subject/enroll → %s" % why_canary)

    # ---------------- 收口回归（教务不可见 / 超管可见）
    sa, aid_uid, aerr = sess_login(*ADMIN)
    if not aid_uid:
        rec("FAIL", "收口回归", "超管账号登录失败，无法核对管理面：%s" % aerr)
    else:
        adm_menus, _, _ = load_menus(sa)
        check_narrowed(menus, adm_menus)

    # ---------------- 覆盖清单：L2（ORM）+ 收集 L3 目标
    targets = []
    for area, paths, model in COVERAGE + GAPS:
        is_gap = (area, paths, model) in GAPS
        hit = [by_path[p] for p in paths if p in by_path]
        if not hit:
            near = [m["path"] for m in menus
                    if any(seg and seg in m["path"]
                           for seg in [p.split(" / ")[-1] for p in paths])]
            detail = "菜单不可见（口径 B）；近名候选：%s" % (near[:3] or "无")
            rec("GAP" if is_gap else "FAIL", area, detail)
            continue
        for m in hit:
            targets.append({"id": m["id"], "path": m["path"], "action_id": m["action_id"],
                            "area": area, "model": model, "gap": is_gap})

    log("\n-- L2 ORM 逐菜单可打开（动作解析 + get_views + search_read + 权限读数）--")
    for t in targets:
        area, aid = t["area"], t["action_id"]
        act, aerr = action_load(s, aid)
        if aerr:
            rec("FAIL", area, "%s 动作 %s 解析失败：%s" % (t["path"], aid, aerr))
            t["l2"] = False
            continue
        t["action"] = act
        atype, model = act.get("type"), act.get("res_model")
        if atype == "ir.actions.act_url":
            url = act.get("url") or ""
            ok_url, why = act_url_reach(s, url)
            rec("PASS" if ok_url else "FAIL", area,
                "%s → act_url %s" % (t["path"], why))
            t["l2"] = bool(ok_url)
            continue
        if atype == "ir.actions.client":
            rec("PASS", area, "%s → client action tag=%s（渲染判据交给 L3）"
                % (t["path"], act.get("tag")))
            t["l2"] = True
            continue
        if atype != "ir.actions.act_window" or not model:
            rec("FAIL", area, "%s → 未知动作类型 %s（model=%s）" % (t["path"], atype, model))
            t["l2"] = False
            continue
        ok, val = call(s, model, "search_read", [[], ["id"]], {"limit": 1})
        if not ok:
            rec("FAIL", area, "%s → %s.search_read 被拒：%s" % (t["path"], model, val))
            t["l2"] = False
            continue
        views = [[v[0], v[1]] for v in (act.get("views") or [])]
        info, verr = view_field_labels(s, model, views)
        if verr:
            rec("FAIL", area, "%s → %s.get_views 失败：%s" % (t["path"], model, verr))
            t["l2"] = False
            continue
        t["expect_labels"] = _key_labels(info, views, act)
        caps = model_caps(s, model)
        t["caps"] = caps
        rec("PASS", area, "%s → %s 读通过（%s；%d 条视图，关键元素候选 %s）"
            % (t["path"], model, caps_text(caps), len(info["archs"]),
               t["expect_labels"][:4]))
        t["l2"] = True

    # ---------------- L3 浏览器渲染
    if args.no_browser:
        log("\n-- L3 浏览器层：--no-browser 跳过（**非门禁口径**）--")
    else:
        log("\n-- L3 浏览器逐菜单渲染（控制面板/视图容器/关键元素/无报错；含环境抖动重试）--")
        if args.all_menus:
            # 全量模式也要按动作类型判：client action / act_url 的判据与 act_window 不同，
            # 所以每条菜单先补一次 action_load（顺带取关键元素候选）。
            check_list = []
            for m in menus:
                if not m["action_id"]:
                    continue
                item = {"id": m["id"], "path": m["path"], "action_id": m["action_id"],
                        "area": "(全量)"}
                act, aerr = action_load(s, m["action_id"])
                if act:
                    item["action"] = act
                    model = act.get("res_model")
                    if act.get("type") == "ir.actions.act_window" and model:
                        views = [[v[0], v[1]] for v in (act.get("views") or [])]
                        info, _ = view_field_labels(s, model, views)
                        if info:
                            item["expect_labels"] = _key_labels(info, views, act)
                check_list.append(item)
            by_id = {}
        else:
            check_list = [t for t in targets if t.get("l2")]
            by_id = {t["id"]: t for t in targets}
        # 全量模式菜单多、页面重，多给一次重试（覆盖清单仍是 3 次）
        results, berr = browser_probe(check_list, s, attempts=4 if args.all_menus else 3)
        if berr:
            log("FATAL | 浏览器层不可用：%s" % berr)
            return 2
        for row in results:
            t = by_id.get(row["id"], row)
            key = t.get("area") or row.get("area")
            ok, detail = judge_browser(row, t.get("expect_labels") or [],
                                       (t.get("action") or {}).get("type"))
            rec("PASS" if ok else "FAIL", key, "%s → %s" % (row["path"], detail))

    # ---------------- E2E 三条流程
    if args.skip_flows:
        log("\n-- E2E：--skip-flows 跳过 --")
    else:
        log("\n-- E2E 三条流程（教务身份真跑 + DB 反查 + 自建自清）--")
        for fn, label in ((lambda: e2e_application(s), "E2E① 报名审批"),
                          (lambda: e2e_grading(s, uid), "E2E② 成绩录入"),
                          (lambda: e2e_attendance(s), "E2E③ 考勤录入")):
            try:
                ok, detail = fn()
            except Exception as exc:  # noqa: BLE001
                ok, detail = False, "异常 %s: %s" % (type(exc).__name__, exc)
            rec("PASS" if ok else "FAIL", label, detail)
        log("\n-- 清场 --")
        deleted, left = cleanup()
        if left:
            rec("FAIL", "夹具清场", "leftover 非 0：%s" % left)
        else:
            rec("PASS", "夹具清场",
                "按 id+标记删除 %s；leftover=0（edu_application/op_exam/op_attendance_* "
                "全表按标记核查）" % "、".join(deleted))

    # ---------------- 汇总
    log("\n== 汇总 ==")
    log("PASS %d / FAIL %d / GAP %d" % (len(PASSES), len(FAILS), len(GAPS_HIT)))
    if FAILS:
        log("FAIL 清单：")
        for area, detail in FAILS:
            log("  · %s：%s" % (area, detail))
    if GAPS_HIT:
        log("GAP 清单（已知历史缺口，见 docs/plans/perm-split-audit.md）：")
        for area, detail in GAPS_HIT:
            log("  · %s：%s" % (area, detail))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "role": BACKOFFICE[0], "uid": uid,
                       "pass": PASSES, "fail": FAILS, "gap": GAPS_HIT,
                       "menus_visible": len(menus)}, fh, ensure_ascii=False, indent=1)
        log("结果已写：%s" % args.json)
    if FAILS or (args.strict_gaps and GAPS_HIT):
        log("结论：有不可达项" + ("（含 GAP）" if GAPS_HIT else ""))
        return 1
    log("结论：全绿（%d 条缺口为已知历史问题，未判红；--strict-gaps 可判红）" % len(GAPS_HIT))
    return 0


def _key_labels(info, views, act):
    """关键元素候选：列表视图字段的**可见标签**（string 属性 > fields_get 标签 > 字段名）。"""
    arch = ""
    for v in (act.get("views") or []):
        if v[1] == "list" and v[0]:
            arch = (info["archs"].get(str(v[0])) or "")
            break
    if not arch:
        for vid, a in (info["archs"] or {}).items():
            if "<list" in a:
                arch = a
                break
    label_map = info.get("label_map") or {}
    out = []
    for m in re.finditer(r'<field\s+name="([^"]+)"(?:\s+string="([^"]*)")?', arch):
        name, string = m.group(1), m.group(2)
        out.append(string or label_map.get(name) or name)
    return [lab for lab in out if lab][:10]


if __name__ == "__main__":
    sys.exit(main())
