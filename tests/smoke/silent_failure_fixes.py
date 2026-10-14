#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静默失效两处修复的验收脚本（2026-09-18）。

被验收的两处缺陷（都属于「页面能打开、东西是空的」这一类）：

  缺陷 A —— 课表「日视图」的前后导航实际不动
    controllers/scheduling.py 用 Datetime.to_date(str(d)) 解析 URL 的 d= 参数，
    而 Odoo 19 的 Datetime 类**没有** to_date（运行时源码 odoo/orm/fields_temporal.py
    里 to_date 只定义在 Date，第 138 行）。异常被 except Exception 吞掉 ⇒ 恒回落
    「今天」：页面永远显示今天，且日志里一个字都没有。
    修法：改用 Date.to_date；兜底照旧回退今天，但打 WARNING + 计数（不许静默）。

  缺陷 B —— 教师账号解析不出「我是哪位教师」⇒ 教师课表静默变空
    op.faculty 对 res.partner 用 _inherits 委托，op.faculty.user_id 实为
    related=partner_id.user_id；而 Odoo 19 的 res.partner.user_id 是「销售员」列，
    程序化 create res.users 不回填它 ⇒ 新建教师账号 current_faculty() 命中 None，
    课表静默落成访客空表（页面照常 200，只是里面什么都没有）。
    修法：① controllers/roles.py 统一改为**双向并集**（record.user_id == uid
    ∪ partner.user_ids ∋ uid）；② scripts/create_teacher_account.py 建完账号
    回填 partner.user_id（目标 partner 已被别的账号占用则**跳过 + 告警**，
    绝不抢占别人的教师身份）。

自查项：
  A1 运行时 API 事实：Datetime 无 to_date、Date 有 to_date（根因守卫）
  A2 静态：scheduling.py 不再调用 Datetime.to_date，且兜底可计数有痕迹
  A3/A4 真机：d= 昨天 / 明天 ⇒ 页面显示的就是那一天（前后对照）
  A5 真机：日视图的导航链接跟随所显示的那一天（不再是今天的 ±1）
  A6 真机：非法 d= 仍 200、无 Traceback、回退今天
  A7 痕迹：A6 那一次在容器日志里留下 WARNING，且带「累计 N 次」
  B1 根因守卫：create res.users 不回填 partner.user_id（savepoint 内实测后回滚）
  B2 源头修：跑真脚本建账号 ⇒ 回填 partner.user_id，链①能命中
  B3 真机：该账号登录后教师课表 = 本人任教课节（与库内计数对齐）
  B4 不回归：既有账号的解析结果与「只走链①」时完全一致（只加不减）
  B5 清场：残留 = 0

用法：python3 tests/smoke/silent_failure_fixes.py
结果：tests/smoke/silent_failure_fixes_results.json（checks + readings）
"""
import datetime
import json
import os
import subprocess
from pathlib import Path

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

import requests  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
OUT = Path(__file__).resolve().parent / "silent_failure_fixes_results.json"
BASE = os.environ.get("SMOKE_BASE", "http://localhost:8069")
DB = os.environ.get("EDU_DB_NAME", "edu19")
DB_CONTAINER = os.environ.get("EDU_DB_CONTAINER", "edu19-clone-db-1")

TEMP_LOGIN = "smoke_silentfix_teacher@local"
TEMP_PWD = "demo123"
NL = chr(10)

CHECKS = []
READINGS = []


def check(no, name, ok, detail=""):
    CHECKS.append({"no": no, "name": name, "pass": bool(ok),
                   "detail": str(detail)[:1200]})
    print("[%s] #%s %s%s" % ("PASS" if ok else "FAIL", no, name,
                             "" if ok else " | " + str(detail)[:500]))


def reading(name, value):
    READINGS.append({"name": name, "value": str(value)[:1500]})
    print("读数 | %s | %s" % (name, str(value)[:300]))


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
def psql(sql):
    out = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", "odoo", "-d", DB,
         "-tAc", sql], capture_output=True, text=True, timeout=90)
    if out.returncode != 0:
        raise RuntimeError("psql failed: " + out.stderr.strip()[:300])
    return out.stdout.strip()


def odoo_shell(lines, env_extra=None, timeout=420):
    """把若干行 python 喂给容器内 odoo shell，返回合并输出。"""
    cmd = ["docker", "compose", "exec", "-T"]
    for k, v in (env_extra or {}).items():
        cmd += ["-e", k + "=" + v]
    cmd += ["web", "odoo", "shell", "-c", "/etc/odoo/odoo.conf", "-d", DB,
            "--db_host=db", "-r", "odoo", "-w", "odoo", "--no-http"]
    out = subprocess.run(cmd, input=NL.join(lines), capture_output=True,
                         text=True, timeout=timeout, cwd=str(REPO))
    txt = (out.stdout or "") + (out.stderr or "")
    if out.returncode != 0:
        raise RuntimeError("odoo shell exit %s: %s"
                           % (out.returncode, txt[-900:]))
    return txt


def payload(text, tag):
    a = text.find("<<<" + tag + ">>>")
    if a < 0:
        return None
    b = text.find("<<<END>>>", a)
    if b < 0:
        return None
    return json.loads(text[a + len(tag) + 6:b])


def emit(tag, obj):
    return "print('<<<" + tag + ">>>' + json.dumps(" + obj + ") + '<<<END>>>')"


def auth(login, pwd):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + "/web/session/authenticate",
               json={"jsonrpc": "2.0",
                     "params": {"db": DB, "login": login, "password": pwd}},
               timeout=60)
    uid = (r.json().get("result") or {}).get("uid")
    return s if uid else None


def http_get(session, url):
    r = session.get(BASE + url, timeout=60)
    return r.status_code, r.text


def between(html, open_tag, close_tag):
    out, i = [], 0
    while True:
        i = html.find(open_tag, i)
        if i < 0:
            break
        j = html.find(close_tag, i + len(open_tag))
        if j < 0:
            break
        out.append(html[i + len(open_tag):j])
        i = j + len(close_tag)
    return out


def strip_tags(s):
    out, depth = [], 0
    for ch in s:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out).strip()


def page_facts(html):
    label = [strip_tags(x).split(NL)[0].strip()
             for x in between(html, '<p class="text-muted small mb-0">', "</p>")]
    title = [strip_tags(x).split(NL)[0].strip()
             for x in between(html, '<h4 class="mb-0">', "</h4>")]
    nav = [u.replace("&amp;", "&") for u in between(html, 'href="', '"')
           if u.startswith("/student/timetable?")]
    return {
        "title": [t for t in title if t][:3],
        "label": [x for x in label if x][:3],
        "subjects": [strip_tags(x) for x in
                     between(html, '<div class="fw-bold">', "</div>")],
        "nav": sorted(set(nav)),
        "empty_day": "这一天暂无排课记录" in html,
        "empty_week": "这一周暂无排课记录" in html,
        "traceback": "Traceback" in html,
    }



# ---------------------------------------------------------------------------
# 开工前的库内快照（用于「不回归」与「残留 = 0」）
# ---------------------------------------------------------------------------
TODAY = datetime.date.today()
MONDAY = TODAY - datetime.timedelta(days=TODAY.weekday())

PRE_COUNT = json.loads(psql(
    "SELECT json_build_object("
    "'faculty', (SELECT count(*) FROM op_faculty), "
    "'student', (SELECT count(*) FROM op_student), "
    "'parent', (SELECT count(*) FROM op_parent), "
    "'partner', (SELECT count(*) FROM res_partner), "
    "'user', (SELECT count(*) FROM res_users))::text"))
print("开工前计数：", PRE_COUNT)

# 目标教师档案 = 脚本自己的自动挑选口径（两条链都没挂账号；名字含「待定」优先；
# 再按课节数降序，好让「有课」这条断言不依赖某条特定夹具）。
TARGET = psql(
    "SELECT f.id || '|' || f.partner_id || '|' || COALESCE(p.user_id::text,'') "
    "|| '|' || COALESCE(p.name,'') || '|' || "
    "(SELECT count(*) FROM op_session s WHERE s.faculty_id = f.id "
    "AND s.state <> 'cancel') "
    "FROM op_faculty f JOIN res_partner p ON p.id = f.partner_id "
    "WHERE p.user_id IS NULL AND NOT EXISTS "
    "(SELECT 1 FROM res_users u WHERE u.partner_id = p.id) "
    "ORDER BY (position('待定' in COALESCE(p.name,'')) > 0) DESC, "
    "(SELECT count(*) FROM op_session s WHERE s.faculty_id = f.id) DESC, f.id "
    "LIMIT 1")
if TARGET:
    t_fac, t_partner, t_partner_user, t_name, t_sess = TARGET.split("|")
else:
    t_fac = t_partner = t_name = ""
    t_partner_user, t_sess = "", "0"
print("目标教师档案（脚本自动挑选口径）：faculty=%s partner=%s 名=%s 课节=%s"
      % (t_fac, t_partner, t_name, t_sess))

# 目标周：优先本周；本周无课就取该教师最近有课的那一周（保证「有课」可断言）
WEEK = psql(
    "WITH s AS (SELECT date_trunc('week', start_datetime)::date AS wk "
    "FROM op_session WHERE faculty_id = " + (t_fac or "0") +
    " AND state <> 'cancel') "
    "SELECT wk || '|' || (SELECT count(*) FROM op_session o WHERE "
    "o.faculty_id = " + (t_fac or "0") + " AND o.state <> 'cancel' "
    "AND o.start_datetime::date < (wk + 7) AND o.end_datetime::date >= wk) "
    "FROM s ORDER BY (wk = date_trunc('week', current_date)::date) DESC, wk DESC "
    "LIMIT 1")
if WEEK:
    wk_start_s, expected_week_n = WEEK.split("|")
    WEEK_OFFSET = (datetime.date.fromisoformat(wk_start_s) - MONDAY).days // 7
else:
    wk_start_s, expected_week_n, WEEK_OFFSET = "-", "0", 0
print("目标周：offset=%s 周一起=%s 该周应显示课节数=%s"
      % (WEEK_OFFSET, wk_start_s, expected_week_n))

sb = auth("faculty@local", "demo123")
if not sb:
    print("登录 faculty@local 失败：站点未就绪，无法验收")
    raise SystemExit(2)

created_uid = None
try:
    # =====================================================================
    print(NL + "=== 缺陷 A：日视图前后导航 ===")
    # =====================================================================
    out = odoo_shell([
        "from odoo.fields import Date, Datetime",
        "import json",
        emit("A1", "{'dt_to_date': hasattr(Datetime, 'to_date'), "
                   "'date_to_date': hasattr(Date, 'to_date'), "
                   "'date_to_date_val': str(Date.to_date('2026-09-17'))}"),
    ])
    a1 = payload(out, "A1") or {}
    reading("A1 容器内 Odoo 19 API 事实", a1)
    check("A1", "运行时：Datetime.to_date 不存在、Date.to_date 存在（缺陷 A 根因）",
          a1.get("dt_to_date") is False and a1.get("date_to_date") is True,
          "Datetime.to_date=%s Date.to_date=%s" % (a1.get("dt_to_date"),
                                                   a1.get("date_to_date")))

    src = (REPO / "custom_addons/edu_portal/controllers/scheduling.py").read_text(
        encoding="utf-8")
    uses_bad = "Dt.to_date" in src
    has_helper = ("_parse_day_param" in src) and ("Date.to_date" in src)
    has_trace = ("_logger.warning" in src) and ("_bad_day_param_count" in src)
    check("A2", "scheduling.py 改用 Date.to_date，兜底可计数且有痕迹（无 Dt.to_date）",
          (not uses_bad) and has_helper and has_trace,
          "Dt.to_date=%s Date.to_date=%s warning+count=%s"
          % (uses_bad, has_helper, has_trace))

    out = odoo_shell([
        "import datetime",
        "from odoo.addons.edu_portal.controllers import scheduling as S",
        "today = datetime.date(2026, 1, 2)",
        "before = S.bad_day_param_count()",
        "r1 = S._parse_day_param('not-a-date', today)",
        "r2 = S._parse_day_param('2026-03-04', today)",
        "r3 = S._parse_day_param('', today)",
        "import json",
        emit("A8", "{'delta': S.bad_day_param_count() - before, "
                   "'r1': str(r1), 'r2': str(r2), 'r3': str(r3)}"),
    ])
    a8 = payload(out, "A8") or {}
    reading("A8 _parse_day_param 直测（合法/非法/空）", a8)
    check("A8", "解析失败**可计数**：非法值 2 次 ⇒ 计数 +2、均回退今天；合法值不影响计数",
          a8.get("delta") == 2 and a8.get("r1") == "2026-01-02"
          and a8.get("r2") == "2026-03-04" and a8.get("r3") == "2026-01-02",
          "delta=%s r1=%s r2=%s r3=%s" % (a8.get("delta"), a8.get("r1"),
                                          a8.get("r2"), a8.get("r3")))

    yest_d = TODAY - datetime.timedelta(days=1)
    tmrw_d = TODAY + datetime.timedelta(days=1)
    yest, tmrw = yest_d.isoformat(), tmrw_d.isoformat()
    y_lab = "%d月%d日" % (yest_d.month, yest_d.day)
    t_lab = "%d月%d日" % (tmrw_d.month, tmrw_d.day)
    today_lab = "%d月%d日" % (TODAY.month, TODAY.day)
    reading("（今天）", "今天=%s 昨天=%s 明天=%s" % (TODAY, yest, tmrw))

    st, html = http_get(sb, "/student/timetable?view=day&d=" + yest)
    fy = page_facts(html)
    reading("A3 教师视角 GET /student/timetable?view=day&d=" + yest, fy)
    check("A3", "日视图 d=昨天 ⇒ 页面显示昨天（不再回落成今天）",
          st == 200 and fy["label"] and fy["label"][0].startswith(y_lab)
          and not fy["label"][0].startswith(today_lab),
          "status=%s label=%s" % (st, fy["label"]))

    st2, html2 = http_get(sb, "/student/timetable?view=day&d=" + tmrw)
    fy2 = page_facts(html2)
    reading("A4 教师视角 GET /student/timetable?view=day&d=" + tmrw, fy2)
    check("A4", "日视图 d=明天 ⇒ 页面显示明天",
          st2 == 200 and fy2["label"] and fy2["label"][0].startswith(t_lab),
          "status=%s label=%s" % (st2, fy2["label"]))

    want_prev = (yest_d - datetime.timedelta(days=1)).isoformat()
    want_next = (yest_d + datetime.timedelta(days=1)).isoformat()
    nav_links = [u for u in fy["nav"] if "d=" in u]
    reading("A5 d=" + yest + " 那一页渲染出的日视图导航链接", nav_links)
    # nav_links 是整条 href，故用子串判定（原先写成 list 元素相等 → 假红）
    has_prev = any(u.endswith("d=" + want_prev) for u in nav_links)
    has_next = any(u.endswith("d=" + want_next) for u in nav_links)
    has_tmrw = any(u.endswith("d=" + tmrw) for u in nav_links)
    check("A5", "前后导航链接跟随所显示的那一天（= 该日的 ±1，而非今天的 ±1）",
          has_prev and has_next and not has_tmrw,
          "links=%s（期望含 %s 与 %s，且不含今天的后一天 %s）"
          % (nav_links, want_prev, want_next, tmrw))

    st3, html3 = http_get(sb, "/student/timetable?view=day&d=not-a-date")
    fy3 = page_facts(html3)
    reading("A6 GET /student/timetable?view=day&d=not-a-date", fy3)
    check("A6", "非法 d= ⇒ 仍 200、无 Traceback、回退今天（兜底不炸）",
          st3 == 200 and not fy3["traceback"] and fy3["label"]
          and fy3["label"][0].startswith(today_lab),
          "status=%s label=%s traceback=%s" % (st3, fy3["label"],
                                               fy3["traceback"]))

    logs = subprocess.run(["docker", "compose", "logs", "--since", "3m", "web"],
                          capture_output=True, text=True, timeout=180,
                          cwd=str(REPO))
    logtxt = (logs.stdout or "") + (logs.stderr or "")
    hit = [ln for ln in logtxt.split(NL) if "课表日视图 d 参数解析失败" in ln]
    reading("A7 容器日志里的 WARNING（最后一条）", hit[-1] if hit else "（无）")
    check("A7", "解析失败在日志里留下 WARNING 且可计数（带「累计 N 次」）",
          bool(hit) and ("累计" in hit[-1]),
          "命中 %d 条；末条=%s" % (len(hit), hit[-1][:260] if hit else "无"))

    # =====================================================================
    print(NL + "=== 缺陷 B：教师账号的身份解析 ===")
    # =====================================================================
    out = odoo_shell([
        "import json",
        "P = env['res.partner'].sudo()",
        "U = env['res.users'].sudo()",
        "p = P.create({'name': '[smoke silentfix] 根因守卫临时伙伴'})",
        "u = U.create({'login': 'smoke_silentfix_probe@local', 'partner_id': p.id,"
        " 'password': 'x', 'group_ids': [(6, 0, "
        "[env.ref('base.group_portal').id])]})",
        "p2 = P.browse(p.id)",
        "res = {'partner_user_id': bool(p2.user_id), "
        "'partner_user_ids': p2.user_ids.ids, 'uid': u.id}",
        "env.cr.rollback()",
        "res['leftover_partner'] = P.search([('name', '=', "
        "'[smoke silentfix] 根因守卫临时伙伴')]).ids",
        "res['leftover_user'] = U.with_context(active_test=False).search("
        "[('login', '=', 'smoke_silentfix_probe@local')]).ids",
        emit("B1", "res"),
    ])
    b1 = payload(out, "B1") or {}
    reading("B1 create res.users 前后的 partner.user_id", b1)
    check("B1", "根因守卫：create res.users 不回填 partner.user_id（savepoint 内实测后回滚）",
          b1.get("partner_user_id") is False
          and b1.get("leftover_partner") == []
          and b1.get("leftover_user") == [],
          "partner.user_id=%s partner.user_ids=%s 残留=%s/%s"
          % (b1.get("partner_user_id"), b1.get("partner_user_ids"),
             b1.get("leftover_partner"), b1.get("leftover_user")))

    out = odoo_shell(
        (REPO / "scripts/create_teacher_account.py").read_text(
            encoding="utf-8").split(NL),
        env_extra={"TEACHER_LOGIN": TEMP_LOGIN})
    reading("B2 scripts/create_teacher_account.py 输出", out[-1400:])
    m = None
    for ln in out.split(NL):
        if ln.startswith("[t] 目标教师档案：faculty id="):
            m = ln
    picked = m.split("faculty id=")[1].split(" ")[0] if m else None
    backfilled = ("[t] 已回填 partner.user_id" in out) or                  ("[t] partner.user_id 已指向本账号" in out)
    uid_row = psql("SELECT id FROM res_users WHERE login = '" + TEMP_LOGIN + "'")
    created_uid = int(uid_row) if uid_row else None
    part_user = psql("SELECT COALESCE(p.user_id::text,'') FROM res_partner p "
                     "JOIN res_users u ON u.partner_id = p.id "
                     "WHERE u.login = '" + TEMP_LOGIN + "'")
    check("B2", "源头修：脚本建账号后回填 partner.user_id（链①能命中）",
          bool(created_uid) and backfilled and part_user == str(created_uid),
          "uid=%s 回填过=%s partner.user_id=%r（脚本报『已回填/已指向』=%s）"
          % (created_uid, backfilled, part_user, backfilled))
    check("B2b", "脚本自己挑的目标档案与验收脚本的口径一致（未抢占他人身份）",
          picked == t_fac,
          "脚本挑了 faculty=%s；验收脚本预期 faculty=%s" % (picked, t_fac))

    s2 = auth(TEMP_LOGIN, TEMP_PWD)
    check("B3a", "新建教师账号可以登录", bool(s2), "login=%s" % TEMP_LOGIN)
    if s2:
        url = "/student/timetable?view=week&w=%d" % WEEK_OFFSET
        st4, html4 = http_get(s2, url)
        f4 = page_facts(html4)
        reading("B3 GET " + url + "（新教师账号）", f4)
        check("B3b", "新教师账号的课表是「我的教学安排」（不再落成访客空表）",
              st4 == 200 and ("我的教学安排" in " ".join(f4["title"])),
              "status=%s title=%s" % (st4, f4["title"]))
        check("B3c", "课表内课节数 = 库内该教师该窗口的课节数（逐数对齐）",
              str(len(f4["subjects"])) == str(expected_week_n)
              and int(expected_week_n) > 0,
              "页面 %d 条 %s ／ 库内 %s 条"
              % (len(f4["subjects"]), f4["subjects"][:4], expected_week_n))

    out = odoo_shell([
        "import json",
        "res = {'changed': [], 'added': []}",
        "models = (('op.faculty', 'partner_id.user_ids'), "
        "('op.student', 'partner_id.user_ids'), ('op.parent', 'name.user_ids'))",
        "for u in env['res.users'].sudo().with_context(active_test=False).search([]):",
        "    for model, chain in models:",
        "        Rec = env[model].sudo()",
        "        old = Rec.search([('user_id', '=', u.id)], limit=1)",
        "        new = old or Rec.search([(chain, 'in', [u.id])], limit=1)",
        "        if old and new.id != old.id:",
        "            res['changed'].append([u.login, model, old.id, new.id])",
        "        elif not old and new:",
        "            res['added'].append([u.login, model, new.id])",
        emit("B4", "res"),
    ])
    b4 = payload(out, "B4") or {}
    reading("B4 双向并集相对旧口径的差异（changed / added）", b4)
    check("B4", "不回归：既有非空解析结果一字不变（只加不减）",
          b4.get("changed") == [],
          "changed=%s added=%s" % (b4.get("changed"), b4.get("added")))
finally:
    # =====================================================================
    print(NL + "=== 清场 ===")
    # =====================================================================
    # 只删本脚本自己建的账号；只复原「确实是我们写上去的」那一个 partner.user_id
    odoo_shell([
        "U = env['res.users'].sudo()",
        "u = U.with_context(active_test=False).search("
        "[('login', '=', '" + TEMP_LOGIN + "')])",
        "print('[clean] 待删账号', u.ids)",
        "u.unlink()",
        "p = env['res.partner'].sudo().browse(" + (t_partner or "0") + ")",
        "if p.exists() and p.user_id and p.user_id.id == "
        + str(created_uid or 0) + ":",
        "    p.write({'user_id': False})",
        "env.cr.commit()",
        "print('[clean] 完成')",
    ])

    left_user = int(psql("SELECT count(*) FROM res_users WHERE login = '"
                         + TEMP_LOGIN + "'"))
    left_bind = psql("SELECT COALESCE(user_id::text,'') FROM res_partner "
                     "WHERE id = " + (t_partner or "0"))
    now_count = json.loads(psql(
        "SELECT json_build_object("
        "'faculty', (SELECT count(*) FROM op_faculty), "
        "'student', (SELECT count(*) FROM op_student), "
        "'parent', (SELECT count(*) FROM op_parent), "
        "'partner', (SELECT count(*) FROM res_partner), "
        "'user', (SELECT count(*) FROM res_users))::text"))
    check("B5", "清场：临时账号已删、目标 partner 的 user_id 复原（残留 = 0）",
          left_user == 0 and left_bind == t_partner_user,
          "临时账号残留=%d；partner %s.user_id=%r（开工前 %r）"
          % (left_user, t_partner, left_bind, t_partner_user))
    reading("B5 收工计数（对照开工前）", {"before": PRE_COUNT, "after": now_count})
    check("B5b", "未动别人的档案：op_faculty / op_student / op_parent 计数不变",
          now_count["faculty"] == PRE_COUNT["faculty"]
          and now_count["student"] == PRE_COUNT["student"]
          and now_count["parent"] == PRE_COUNT["parent"],
          "before=%s after=%s" % (PRE_COUNT, now_count))

n_fail = sum(1 for c in CHECKS if not c["pass"])
OUT.write_text(json.dumps(
    {"suite": "silent_failure_fixes",
     "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
     "summary": {"total": len(CHECKS), "pass": len(CHECKS) - n_fail,
                 "fail": n_fail},
     "checks": CHECKS, "readings": READINGS},
    ensure_ascii=False, indent=1), encoding="utf-8")
print(NL + "== silent_failure_fixes: %d/%d PASS ==（%s）"
      % (len(CHECKS) - n_fail, len(CHECKS), OUT.name))
if n_fail:
    raise SystemExit(1)
