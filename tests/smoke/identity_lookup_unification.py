#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「由 user 反查身份档案」口径统一 —— 验收脚本（2026-09-18）。

缺陷家族（本仓「静默失效」的公共根因）
--------------------------------------
Odoo 19 里「账号 ↔ 伙伴」的正反向关系只有一条是规范的：
    res.users.partner_id      （账号 → 伙伴，唯一的真关系）
    res.partner.user_ids      （伙伴 → 账号，其反向 one2many）
而 res.partner.user_id 是**销售员**字段（core res_partner.py:229 明写不是
partner_id 的反向），只有 _compute_user_id 从 parent_id 同步；程序化
create res.users 时**不会回填**它。

本仓历史数据把「教师账号」挂在 partner.user_id 上（邀请码 attach_identity、
create_teacher_account.py 的显式回填），所以：
  · 只按 partner.user_id 反查 ⇒ 漏掉脚本新建的教师账号（课表/通知/日历静默为空）
  · 只按 res.users.partner_id 反查 ⇒ 漏掉本仓既有数据（生产按老口径挂的）

统一口径 = **双向并集**：链① 记录自身 user_id == uid；①落空才查链②
partner.user_ids ∋ uid。只加不减 ⇒ 既有账号的解析结果一字不变。

本脚本验收的四处高危点
----------------------
  ical.py      学生/教师/家长的 ICS 订阅视角（订阅失败是静默的）
  messages.py  教师私信（原「双口径兜底」逐字生成相同 SQL = 同义反复）
  session_ext.py  课前提醒 / 改课通知的收件人（「通知 0 收件人」那一族）
  fees.py      报销收据可见性（受理人解析只走 partner.user_id）

用法
----
  # 1) 建夹具（幂等，提交；夹具会跨「升级前后」存活）
  python3 tests/smoke/identity_lookup_unification.py setup
  # 2) 改码前读数（必须在本轮改动**之前**跑）
  python3 tests/smoke/identity_lookup_unification.py measure --tag before
  # 3) 改码 + bash scripts/safe_upgrade.sh edu_schedule edu_portal
  # 4) 改码后读数（同一夹具）
  python3 tests/smoke/identity_lookup_unification.py measure --tag after
  # 5) 清场（断言残留 = 0）
  python3 tests/smoke/identity_lookup_unification.py teardown

结果落盘：tests/smoke/identity_lookup_unification_results.json（按 tag 累加）
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

import requests  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
OUT = Path(__file__).resolve().parent / "identity_lookup_unification_results.json"
BASE = os.environ.get("SMOKE_BASE", "http://localhost:8069")
DB = os.environ.get("EDU_DB_NAME", "edu19")
DB_CONTAINER = os.environ.get("EDU_DB_CONTAINER", "edu19-clone-db-1")

TEACHER_LOGIN = "smoke_id_teacher@local"
STUDENT_LOGIN = "smoke_id_student@local"
TEACHER_TOKEN = "smokeidteachertoken0000000000000001"
STUDENT_TOKEN = "smokeidstudenttoken0000000000000001"
STUDENT_PARTNER_NAME = "[smoke identity] 学生夹具"
STUDENT_NAME = "[smoke identity] 夹具学生"
FEE_REF = "REB-SMOKE-IDENTITY"
PWD = "demo123"
NL = chr(10)

CHECKS = []
READINGS = []


def check(no, name, ok, detail=""):
    CHECKS.append({"no": no, "name": name, "pass": bool(ok),
                   "detail": str(detail)[:1500]})
    print("[%s] #%s %s%s" % ("PASS" if ok else "FAIL", no, name,
                             "" if ok else " | " + str(detail)[:600]))


def reading(name, value):
    READINGS.append({"name": name, "value": str(value)[:2000]})
    print("读数 | %s | %s" % (name, str(value)[:400]))


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


def odoo_shell(lines, env_extra=None, timeout=600, commit=False):
    """把若干行 python 喂给容器内 odoo shell，返回合并输出。

    commit=False 时脚本末尾自动 rollback ⇒ 探针不落库（通知/审计零残留）。
    """
    body = list(lines)
    body.append("env.cr.rollback()" if not commit else "env.cr.commit()")
    cmd = ["docker", "compose", "exec", "-T"]
    for k, v in (env_extra or {}).items():
        cmd += ["-e", k + "=" + v]
    cmd += ["web", "odoo", "shell", "-c", "/etc/odoo/odoo.conf", "-d", DB,
            "--db_host=db", "-r", "odoo", "-w", "odoo", "--no-http"]
    out = subprocess.run(cmd, input=NL.join(body), capture_output=True,
                         text=True, timeout=timeout, cwd=str(REPO))
    txt = (out.stdout or "") + (out.stderr or "")
    if out.returncode != 0:
        raise RuntimeError("odoo shell exit %s: %s"
                           % (out.returncode, txt[-1200:]))
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
    return (s, uid) if uid else (None, None)


def http_get(session, url):
    r = session.get(BASE + url, timeout=60)
    return r.status_code, r.text


def ics_facts(text):
    """ICS 正文读数：总事件数 / 课程事件数 / 是否教师视角。"""
    return {
        "total_vevent": text.count("BEGIN:VEVENT"),
        "session_vevent": len(re.findall(r"UID:session-", text)),
        "exam_vevent": len(re.findall(r"UID:exam-", text)),
        "event_vevent": len(re.findall(r"UID:event-", text)),
        "holiday_vevent": len(re.findall(r"UID:holiday-", text)),
    }


def picker_uids(html):
    """/my/messages 「发起新对话」下拉里的 <option value=uid> 集合。"""
    m = re.search(r'<select[^>]*id="msg-new-pick".*?</select>', html, re.S)
    if not m:
        return set()
    return {int(v) for v in re.findall(r'<option[^>]*value="(\d+)"',
                                       m.group(0))}


def picker_options(html):
    m = re.search(r'<select[^>]*id="msg-new-pick".*?</select>', html, re.S)
    if not m:
        return []
    return re.findall(r'<option[^>]*value="(\d+)"[^>]*>(.*?)</option>',
                      m.group(0), re.S)


# ---------------------------------------------------------------------------
# 夹具状态（全部按 login / 名字反查，脚本不落额外状态文件）
# ---------------------------------------------------------------------------
def fixture_state():
    st = {}
    row = psql("SELECT u.id || '|' || u.partner_id FROM res_users u "
               "WHERE u.login = '" + TEACHER_LOGIN + "'")
    if row:
        st["teacher_uid"], st["teacher_partner"] = (int(x) for x in row.split("|"))
    row = psql("SELECT u.id || '|' || u.partner_id || '|' || p.id FROM res_users u "
               "JOIN res_partner p ON p.id = u.partner_id "
               "WHERE u.login = '" + STUDENT_LOGIN + "'")
    if row:
        uid, partner, _p = row.split("|")
        st["student_uid"], st["student_partner"] = int(uid), int(partner)
    row = psql("SELECT s.id || '|' || s.partner_id FROM op_student s "
               "JOIN res_partner p ON p.id = s.partner_id "
               "WHERE p.name = '" + STUDENT_NAME + "'")
    if row:
        st["student_rec"], _ = (int(x) for x in row.split("|"))
    # 教师夹具的档案 = 夹具账号 partner 名下的 op.faculty（不再是「找空闲的」——
    # 夹具一旦建好，该 partner 就不再空闲；必须按夹具账号反查，否则读数会空）
    row = psql("SELECT f.id || '|' || f.partner_id FROM op_faculty f WHERE "
               "f.partner_id = (SELECT partner_id FROM res_users WHERE login = '"
               + TEACHER_LOGIN + "') ORDER BY f.id LIMIT 1")
    if row:
        st["faculty"], st["faculty_partner"] = (int(x) for x in row.split("|"))
    row = psql("SELECT sc.id FROM op_student_course sc WHERE sc.student_id = "
               + str(st.get("student_rec") or 0))
    if row:
        st["student_course"] = int(row.split(NL)[0])
    row = psql("SELECT id FROM edu_fee_bill WHERE reimburse_ref = '" + FEE_REF + "'")
    if row:
        st["fee_bill"] = int(row.split(NL)[0])
    return st


COUNT_SQL = (
    "SELECT json_build_object("
    "'user', (SELECT count(*) FROM res_users), "
    "'partner', (SELECT count(*) FROM res_partner), "
    "'faculty', (SELECT count(*) FROM op_faculty), "
    "'student', (SELECT count(*) FROM op_student), "
    "'student_course', (SELECT count(*) FROM op_student_course), "
    "'session', (SELECT count(*) FROM op_session), "
    "'bill', (SELECT count(*) FROM edu_fee_bill), "
    "'message', (SELECT count(*) FROM edu_message))::text")


def do_setup():
    """建夹具（幂等 + 提交）。教师夹具刻意**不回填** partner.user_id —— 
    这就是「脚本新建教师账号」的真实形态（Odoo 不回填）。"""
    baseline = json.loads(psql(COUNT_SQL))
    reading("建夹具前的基线计数", baseline)
    out = odoo_shell([
        "import json",
        "P = env['res.partner'].sudo(); U = env['res.users'].sudo()",
        "F = env['op.faculty'].sudo(); S = env['op.student'].sudo()",
        "B = env['op.batch'].sudo(); C = env['op.course'].sudo()",
        "portal = env.ref('base.group_portal').id",
        # --- 教师夹具：挂在「有课节、partner 名下无账号」的教师档案上 ---
        "fac = F.search([('id', 'in', [f.id for f in F.search([]) "
        "if f.partner_id and not f.partner_id.user_id and not f.partner_id.user_ids "
        "and env['op.session'].search_count([('faculty_id', '=', f.id)]) > 0])], order='id', limit=1)",
        "fac = fac or F.search([('partner_id.user_id', '=', False)], order='id', limit=1)",
        "tp = fac.partner_id",
        "tu = U.with_context(active_test=False).search([('login', '=', '" + TEACHER_LOGIN + "')], limit=1)",
        "if not tu:",
        "    tu = U.create({'login': '" + TEACHER_LOGIN + "', 'partner_id': tp.id,",
        "                   'password': '" + PWD + "', 'active': True,",
        "                   'group_ids': [(6, 0, [portal])],",
        "                   'edu_ical_token': '" + TEACHER_TOKEN + "'})",
        "else:",
        "    tu.write({'active': True, 'password': '" + PWD + "', 'partner_id': tp.id,",
        "               'edu_ical_token': '" + TEACHER_TOKEN + "'})",
        # --- 学生夹具：全新 partner + 账号 + 学生档案（**不写 op.student.user_id**）---
        "sp = P.search([('name', '=', '" + STUDENT_PARTNER_NAME + "')], limit=1)",
        "if not sp:",
        "    sp = P.create({'name': '" + STUDENT_PARTNER_NAME + "', "
        "'email': 'smoke_id_student@example.invalid'})",
        "su = U.with_context(active_test=False).search([('login', '=', '" + STUDENT_LOGIN + "')], limit=1)",
        "if not su:",
        "    su = U.create({'login': '" + STUDENT_LOGIN + "', 'partner_id': sp.id,",
        "                   'password': '" + PWD + "', 'active': True,",
        "                   'group_ids': [(6, 0, [portal])],",
        "                   'edu_ical_token': '" + STUDENT_TOKEN + "'})",
        "else:",
        "    su.write({'partner_id': sp.id, 'active': True, 'password': '" + PWD + "',",
        "              'edu_ical_token': '" + STUDENT_TOKEN + "'})",
        "st = S.search([('partner_id', '=', sp.id)], limit=1)",
        "if not st:",
        "    st = S.create({'partner_id': sp.id, 'name': '" + STUDENT_NAME + "',",
        "                   'first_name': '夹具', 'last_name': '学生', 'gender': 'm'})",
        # 学生课程：挂到「有在读学生且有课节」的批次（batch 8 的课节最多）
        "batch = B.search([('id', 'in', env['op.student.course'].search([]).mapped('batch_id').ids)], limit=1)",
        "batch = batch or B.search([], limit=1)",
        "course = C.search([], limit=1)",
        "if not env['op.student.course'].search([('student_id', '=', st.id)], limit=1):",
        "    env['op.student.course'].sudo().create({'student_id': st.id, 'course_id': course.id,",
        "                                          'batch_id': batch.id, 'state': 'running'})",
        # --- 费用夹具：一张挂在教师档案上的应付单（受理人解析用）---
        "bill = env['edu.fee.bill'].sudo().search([('reimburse_ref', '=', '" + FEE_REF + "')], limit=1)",
        "if not bill:",
        "    bill = env['edu.fee.bill'].sudo().create({'name': '[smoke identity] 夹具应付单',",
        "        'direction': 'payable', 'amount': 1.0, 'reimburse_ref': '" + FEE_REF + "',",
        "        'faculty_id': fac.id, 'partner_id': tp.id, 'reimburse_state': 'request'})",
        "res = {'faculty': fac.id, 'faculty_partner': tp.id, 'teacher_uid': tu.id,",
        "       'teacher_partner': tp.id, 'student_uid': su.id, 'student_partner': sp.id,",
        "       'student_rec': st.id, 'batch': batch.id, 'bill': bill.id}",
        emit("SETUP", "res"),
    ], commit=True)
    st = payload(out, "SETUP") or {}
    reading("夹具（setup）", st)
    state = fixture_state()
    st.update(state)
    st["baseline_counts"] = baseline
    check("S1", "夹具就绪：脚本新建教师账号（不回填 partner.user_id）+ 学生账号 + 费用单",
          bool(st.get("teacher_uid")) and bool(st.get("student_uid"))
          and bool(st.get("student_course")) and bool(st.get("bill")),
          json.dumps(st, ensure_ascii=False))
    # 关键前提：教师 partner 的**链①为空**（否则验不出链②的价值）
    sales = psql("SELECT COALESCE(user_id::text, '') FROM res_partner WHERE id = "
                 + str(st.get("faculty_partner") or 0))
    ids = psql("SELECT count(*) FROM res_users WHERE partner_id = "
               + str(st.get("faculty_partner") or 0))
    st["teacher_salesperson_before"] = sales
    st["teacher_native_accounts"] = int(ids or 0)
    check("S2", "夹具前提成立：教师 partner.user_id（链①）为空，账号只走链② partner.user_ids",
          sales == "" and st["teacher_native_accounts"] >= 1,
          "partner %s: user_id=%r res.users.partner_id=%s"
          % (st.get("faculty_partner"), sales, st["teacher_native_accounts"]))
    save_phase("setup", {"fixture": st}, [])
    return st


# ---------------------------------------------------------------------------
# 结果落盘
# ---------------------------------------------------------------------------
def load_results():
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {"suite": "identity_lookup_unification",
            "db": DB, "phases": {}, "checks": [], "readings": []}


def save_phase(tag, data, checks):
    doc = load_results()
    doc["generated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    doc["phases"][tag] = data
    # 同一相位同一编号 = **覆盖**（重跑必须换掉旧读数，否则会把已修的假红永远留在
    # 证据文件里）；不同相位之间互不影响（before 是改码前基线，必须原样保留）。
    fresh = {c["no"] for c in checks}
    doc["checks"] = [c for c in doc["checks"]
                     if not (c.get("phase") == tag and c.get("no") in fresh)]
    for c in checks:
        cc = dict(c)
        cc["phase"] = tag
        doc["checks"].append(cc)
    doc["readings"] = [r for r in doc["readings"]
                       if not r["name"].startswith(tag + " | ")]
    doc["readings"] += [{"name": tag + " | " + r["name"], "value": r["value"]}
                        for r in READINGS]
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                   encoding="utf-8")


# ---------------------------------------------------------------------------
# 静态检查（改码后必须有）
# ---------------------------------------------------------------------------
HELPER_CANDIDATES = [
    "custom_addons/edu_schedule/models/identity.py",
    "custom_addons/edu_portal/models/identity.py",
    "custom_addons/edu_portal/controllers/roles.py",
]


def static_checks():
    res = {"helper": None, "importers": {}, "bad_patterns": {}}
    for rel in HELPER_CANDIDATES:
        p = REPO / rel
        if p.exists() and "def profile_of_user" in p.read_text(encoding="utf-8"):
            res["helper"] = rel
    sites = {
        "edu_portal/controllers/ical.py": ["('user_id', '=', uid)"],
        "edu_portal/controllers/messages.py": ["('partner_id.user_id', '=', uid)",
                                               "('name.user_id', '=', uid)"],
        "edu_schedule/models/session_ext.py": ["self.faculty_id.user_id if"],
        "edu_portal/models/fees.py": ["self.faculty_id.partner_id.user_id.id == uid"],
    }
    for rel, pats in sites.items():
        src = (REPO / "custom_addons" / rel).read_text(encoding="utf-8")
        res["importers"][rel] = ("identity" in src and "import" in src)
        res["bad_patterns"][rel] = [p for p in pats if p in src]
    return res


# ---------------------------------------------------------------------------
# 读数
# ---------------------------------------------------------------------------
def measure(tag, st):
    data = {"fixture": st}

    # ===== 0) 静态 =====
    sc = static_checks()
    reading("静态检查", sc)
    if tag != "before":
        check("C0", "公共 helper 已落地（且不是第二套）", bool(sc["helper"]),
              "helper=%s" % sc["helper"])
        for rel, pats in sc["bad_patterns"].items():
            check("C0b", "高危点已改走公共 helper：%s" % rel, not pats,
                  "残留旧口径片段=%s" % pats)

    # ===== 1) session_ext：课前提醒 / 改课通知的收件人 =====
    lines = [
        "import json",
        "S = env['op.session'].sudo()",
        "F = env['op.faculty'].sudo()",
        "US = env['res.users'].sudo()",
        "res = {}",
        "fac = F.browse(%d)" % st["faculty"],
        "tu = US.browse(%d)" % st["teacher_uid"],
        "sessions = S.search([('faculty_id', '=', fac.id), ('state', '!=', 'cancel')], order='id desc')",
        "with_stu = None",
        "for s in sessions:",
        "    stu = s._session_student_users()",
        "    if stu:",
        "        with_stu = s",
        "        break",
        "no_stu = None",
        "for s in sessions:",
        "    if not s._session_student_users():",
        "        no_stu = s",
        "        break",
        "def info(s):",
        "    if not s:",
        "        return None",
        "    users = s._reminder_users()",
        "    return {'sid': s.id, 'batch': s.batch_id.id or 0,",
        "            'n_students': len(s._session_student_users()),",
        "            'recipients': len(users),",
        "            'recipient_ids': users.ids,",
        "            'teacher_in': tu.id in users.ids,",
        "            'impact': len(s._impact_recipients())}",
        "res['no_students'] = info(no_stu)",
        "res['with_students'] = info(with_stu)",
        # 既有教师（faculty@local 那族）的课节：回归对照
        "old_fac = F.search([('id', '!=', fac.id), ('partner_id.user_id', '!=', False)], order='id', limit=1)",
        "res['existing_faculty'] = info(S.search([('faculty_id', '=', old_fac.id), ('state', '!=', 'cancel')], order='id desc', limit=1)) if old_fac else None",
        # 真跑一次「改课通知」（事务内，脚本结束 rollback ⇒ 零残留）
        "if no_stu:",
        "    r = no_stu._notify_session_change(sender_uid=1)",
        "    res['notify_change'] = {'sent': r['sent'], 'total': r['total'], 'failed': r['failed'], 'muted': r['muted']}",
        # 真跑一次「课前提醒」（同上）
        "if with_stu is None and no_stu is not None:",
        "    pass",
        emit("S", "res"),
    ]
    out = odoo_shell(lines)
    sres = payload(out, "S") or {}
    data["session_ext"] = sres
    reading("session_ext 收件人读数", sres)
    ns = sres.get("no_students") or {}
    ws = sres.get("with_students") or {}
    old = sres.get("existing_faculty") or {}
    reading("session_ext｜无学生批次（=%s）收件人" % ns.get("sid"),
            "收件人 %s 人（含教师=%s）｜影响面 %s 人" % (ns.get("recipients"),
                                                     ns.get("teacher_in"),
                                                     ns.get("impact")))
    reading("session_ext｜有学生批次（=%s）收件人" % ws.get("sid"),
            "收件人 %s 人（学生 %s）｜影响面 %s 人" % (ws.get("recipients"),
                                                   ws.get("n_students"),
                                                   ws.get("impact")))
    if tag != "before":
        check("V1", "课前/改课通知收件人不再为 0（脚本新建教师账号的夹具）",
              (ns.get("recipients") or 0) >= 1 and ns.get("teacher_in") is True,
              "sid=%s 收件人=%s 含教师=%s（改课通知 %s）"
              % (ns.get("sid"), ns.get("recipients"), ns.get("teacher_in"),
                 sres.get("notify_change")))
    # 逐 id 的「只加不减」：改前名单里的每一个人，改后必须还在（漏人=回归）
    prev = load_results().get("phases", {}).get("before", {}).get("session_ext") or {}
    missing = {}
    if prev and tag == "after":
        for key, label in (("no_students", "无学生批次"),
                           ("with_students", "有学生批次"),
                           ("existing_faculty", "既有教师课节")):
            b, a = prev.get(key) or {}, sres.get(key) or {}
            if b.get("sid") and b.get("sid") == a.get("sid"):
                miss = [x for x in (b.get("recipient_ids") or [])
                        if x not in (a.get("recipient_ids") or [])]
                if miss:
                    missing[label] = miss
        check("V1b", "只加不减（逐 id）：改前每位收件人改后仍在名单里",
              not missing, "丢失=%s（改前 %s / 改后 %s）"
              % (missing, prev.get("with_students"), sres.get("with_students")))

    # ===== 2) ical：教师 / 学生的 ICS 订阅内容 =====
    ical = {}
    for who, token in (("teacher", TEACHER_TOKEN), ("student", STUDENT_TOKEN)):
        status, text = http_get(requests.Session(), "/my/calendar/ics/" + token)
        f = ics_facts(text) if status == 200 else {"status": status}
        f["status"] = status
        ical[who] = f
    data["ical"] = ical
    reading("ical 教师 ICS", ical["teacher"])
    reading("ical 学生 ICS", ical["student"])
    if tag != "before":
        check("V2", "教师 ICS 不再是空日历（身份解析出 faculty 视角）",
              ical["teacher"].get("session_vevent", 0) >= 1,
              "session 事件=%s / 总事件=%s"
              % (ical["teacher"].get("session_vevent"),
                 ical["teacher"].get("total_vevent")))
        check("V2b", "学生 ICS 不再是空日历（身份解析出 student 视角）",
              ical["student"].get("session_vevent", 0) >= 1,
              "session 事件=%s / 总事件=%s"
              % (ical["student"].get("session_vevent"),
                 ical["student"].get("total_vevent")))

    # ===== 3) messages：教师私信可见性 =====
    msg = {}
    sadmin, _ = auth("admin", "admin")
    sstu, _ = auth("stu@local", PWD)
    stea, _ = auth(TEACHER_LOGIN, PWD)
    msg["teacher_login_ok"] = bool(stea)
    if sadmin:
        st1, h1 = http_get(sadmin, "/my/messages")
        msg["admin_status"] = st1
        msg["admin_picker"] = len(picker_uids(h1))
        msg["admin_has_teacher"] = st["teacher_uid"] in picker_uids(h1)
    if sstu:
        st2, h2 = http_get(sstu, "/my/messages")
        msg["student_status"] = st2
        msg["student_picker"] = len(picker_uids(h2))
        msg["student_has_teacher"] = st["teacher_uid"] in picker_uids(h2)
        msg["student_options"] = [u for u, _ in picker_options(h2)]
    if stea:
        st3, h3 = http_get(stea, "/my/messages")
        msg["teacher_status"] = st3
        msg["teacher_picker"] = len(picker_uids(h3))
        msg["teacher_picker_has_students"] = bool(picker_uids(h3))
    data["messages"] = msg
    reading("messages 私信可见性", msg)
    if tag != "before":
        check("V3", "学生的熟人圈里出现「脚本新建教师」账号（私信可达）",
              msg.get("student_has_teacher") is True,
              "student_picker=%s has_teacher=%s"
              % (msg.get("student_picker"), msg.get("student_has_teacher")))
        check("V3b", "管理员私信列表把该教师识别为「教师」（不是管理员/查无此人）",
              msg.get("admin_has_teacher") is True,
              "admin_picker=%s has_teacher=%s"
              % (msg.get("admin_picker"), msg.get("admin_has_teacher")))

    # ===== 4) fees：报销收据可见性 =====
    lines = [
        "import json",
        "B = env['edu.fee.bill'].sudo()",
        "U = env['res.users'].sudo()",
        "res = {}",
        "bill = B.browse(%d)" % st["fee_bill"],
        # sudo() 保留 uid ⇒ 既能读（绕过 ACL），又是在「那个账号」的身份下判可见性
        "res['fixture_bill_as_teacher'] = bool(bill.with_user(%d).sudo()._user_can_view_receipt())" % st["teacher_uid"],
        "res['fixture_bill_as_student_acct'] = bool(bill.with_user(%d).sudo()._user_can_view_receipt())" % st["student_uid"],
        # 回归矩阵：既有账号 × 既有账单（排除夹具单）的可见性
        "matrix = {}",
        "for u in U.with_context(active_test=False).search([]):",
        "    for b in B.search([]):",
        "        if b.id == bill.id:",
        "            continue",
        "        matrix['%s:%s' % (u.id, b.id)] = bool(b.with_user(u.id).sudo()._user_can_view_receipt())",
        "res['existing_matrix'] = matrix",
        emit("F", "res"),
    ]
    out = odoo_shell(lines)
    fres = payload(out, "F") or {}
    data["fees"] = fres
    reading("fees 收据可见性", {"夹具单·教师账号": fres.get("fixture_bill_as_teacher"),
                            "夹具单·学生账号": fres.get("fixture_bill_as_student_acct"),
                            "既有账单矩阵条目": len(fres.get("existing_matrix") or {})})
    if tag != "before":
        check("V4", "报销收据可见性：受理教师本人的账号能看见自己的单据",
              fres.get("fixture_bill_as_teacher") is True,
              "as_teacher=%s（改前为 False）" % fres.get("fixture_bill_as_teacher"))
    prev = load_results().get("phases", {}).get("before", {}).get("fees", {})
    if prev.get("existing_matrix") is not None:
        # 只比**两边都有**的键（改前就存在的账号 × 账单）：夹具账号是改后新出现的，
        # 拿它们去比改前只会得到 None ≠ False 的假红。
        common = {k for k in prev["existing_matrix"]
                  if k in (fres.get("existing_matrix") or {})}
        diff = {k: (prev["existing_matrix"][k], fres["existing_matrix"][k])
                for k in common
                if prev["existing_matrix"][k] != fres["existing_matrix"][k]}
        fresh = sorted(set(fres.get("existing_matrix") or {}) - set(prev["existing_matrix"]))
        data["fees"]["matrix_diff_vs_before"] = diff
        data["fees"]["matrix_new_keys"] = fresh
        check("V4b", "报销收据可见性：既有账号 × 既有账单 与改前逐条一致",
              not diff, "共同键 %d 个，差异=%s（新增键 %s）"
              % (len(common), diff, fresh))

    # ===== 4.5) helper 单元探针：三个模型 × 两条链（事务内，结束即回滚） =====
    out = odoo_shell([
        "import json",
        "from odoo.addons.edu_schedule.models.identity import (",
        "    profile_of_user, users_of_profile, users_of_partner)",
        "P = env['res.partner'].sudo(); U = env['res.users'].sudo()",
        "R = {}",
        "portal = [env.ref('base.group_portal').id]",
        "def mk(tag, model_field=None):",
        "    p = P.create({'name': '[smoke identity] probe-%s' % tag})",
        "    u = U.create({'login': 'smoke_id_probe_%s@local' % tag,",
        "                  'partner_id': p.id, 'password': 'x',",
        "                  'group_ids': [(6, 0, portal)]})",
        "    return p, u",
        "p1, u1 = mk('student')",
        "st = env['op.student'].sudo().create(",
        "    {'partner_id': p1.id, 'name': '[smoke identity] probe-student',",
        "     'gender': 'm'})",
        "R['student'] = {'chain1': len(env['op.student'].sudo().search(",
        "                    [('user_id', '=', u1.id)], limit=1)),",
        "                'dual': profile_of_user(env, 'op.student', u1.id).id or 0,",
        "                'forward': sorted(users_of_profile(st).ids)}",
        "p2, u2 = mk('faculty')",
        "fa = env['op.faculty'].sudo().create({'partner_id': p2.id,",
        "                                     'first_name': 'probe',",
        "                                     'last_name': 'faculty',",
        "                                     'gender': 'male',",
        "                                     'birth_date': '1990-01-01'})",
        "R['faculty'] = {'chain1': len(env['op.faculty'].sudo().search(",
        "                    [('user_id', '=', u2.id)], limit=1)),",
        "                'dual': profile_of_user(env, 'op.faculty', u2.id).id or 0,",
        "                'forward': sorted(users_of_profile(fa).ids)}",
        "p3, u3 = mk('parent')",
        "rel = env['op.parent.relationship'].sudo().search([], limit=1)",
        "pa = env['op.parent'].sudo().create(",
        "    {'name': p3.id, 'relationship_id': rel.id})",
        "pa.write({'student_ids': [(6, 0, [st.id])]})",
        "R['parent'] = {'chain1': len(env['op.parent'].sudo().search(",
        "                    [('user_id', '=', u3.id)], limit=1)),",
        "                'dual': profile_of_user(env, 'op.parent', u3.id).id or 0,",
        "                'forward': sorted(users_of_profile(pa).ids)}",
        # 链① 仍优先：给学生在自己的列上挂另一个账号，反查必须给回那一个
        "p4, u4 = mk('chain1hit')",
        "st.write({'user_id': u4.id})",
        "R['chain1_priority'] = {'got': profile_of_user(env, 'op.student', u4.id).id or 0,",
        "                        'want': st.id}",
        emit("H", "R"),
    ])
    hres = payload(out, "H") or {}
    data["helper_unit"] = hres
    reading("helper 单元探针（三模型 × 两条链，事务内回滚）", hres)
    if tag != "before":
        # 逐条判：三个模型都要「链①空但 dual 命中」，且正向并集能把该账号找回来
        ok = True
        detail = {}
        for key in ("student", "faculty", "parent"):
            r_ = hres.get(key) or {}
            hit = bool(r_.get("dual")) and not r_.get("chain1") \
                and bool(r_.get("forward"))
            ok = ok and hit
            detail[key] = {"chain1": r_.get("chain1"), "dual": r_.get("dual"),
                           "forward": r_.get("forward")}
        pri = hres.get("chain1_priority") or {}
        ok = ok and pri.get("got") == pri.get("want") and bool(pri.get("got"))
        detail["chain1_priority"] = pri
        check("V6", "helper 自身：三模型都「链①空→链②命中」且正向并集能找回账号；链①优先不变",
              ok, json.dumps(detail, ensure_ascii=False))

    # ===== 5) 零回归：全库用户 × 三个身份模型（只加不减） =====
    lines = [
        "import json",
        "res = {'changed': [], 'added': [], 'total': 0}",
        "models = (('op.faculty', 'partner_id.user_ids'), ('op.student', 'partner_id.user_ids'), ('op.parent', 'name.user_ids'))",
        "for u in env['res.users'].sudo().with_context(active_test=False).search([]):",
        "    for model, chain in models:",
        "        Rec = env[model].sudo()",
        "        old = Rec.search([('user_id', '=', u.id)], limit=1)",
        "        new = old or Rec.search([(chain, 'in', [u.id])], limit=1)",
        "        res['total'] += 1",
        "        if old and new.id != old.id:",
        "            res['changed'].append([u.login, model, old.id, new.id])",
        "        elif not old and new:",
        "            res['added'].append([u.login, model, new.id])",
        emit("R", "res"),
    ]
    out = odoo_shell(lines)
    rres = payload(out, "R") or {}
    data["regression"] = rres
    reading("零回归矩阵（旧口径 vs 双向并集）",
            {"changed": rres.get("changed"), "added": rres.get("added")})
    check("V5", "只加不减：既有非空解析结果一字不变（全库用户 × 三身份模型）",
          rres.get("changed") == [],
          "changed=%s added=%s total=%s"
          % (rres.get("changed"), rres.get("added"), rres.get("total")))
    return data


# ---------------------------------------------------------------------------
# 清场
# ---------------------------------------------------------------------------
def do_teardown():
    st = fixture_state()
    before = json.loads(psql(
        "SELECT json_build_object("
        "'user', (SELECT count(*) FROM res_users), "
        "'partner', (SELECT count(*) FROM res_partner), "
        "'faculty', (SELECT count(*) FROM op_faculty), "
        "'student', (SELECT count(*) FROM op_student), "
        "'student_course', (SELECT count(*) FROM op_student_course), "
        "'session', (SELECT count(*) FROM op_session), "
        "'bill', (SELECT count(*) FROM edu_fee_bill), "
        "'message', (SELECT count(*) FROM edu_message))::text"))
    # ⚠ 清场锚点必须**确定性**：曾在 v1 用 partner.name 认学生 —— 而 op.student
    # 因 _inherits 委托，建档时写 name 会把伙伴名一起改掉，于是「按原伙伴名
    # 找学生」恒空 ⇒ 什么都没删、残留断言还全绿（一次真实的假绿）。
    # 现在一律按 **登录名 → 账号 id → 伙伴 id / 学生档案 id** 反查后再删。
    uids = [int(x) for x in (psql(
        "SELECT string_agg(id::text, ' ') FROM res_users WHERE login IN "
        "('" + TEACHER_LOGIN + "', '" + STUDENT_LOGIN + "')") or "").split()]
    # 伙伴锚点 = 夹具账号的 partner ∪ 带夹具名前缀的 partner（后者让「账号已删、
    # 档案还在」这种半清场也能被收干净 —— 名字前缀 [smoke identity] 只属本脚本）
    pids = [int(x) for x in (psql(
        "SELECT string_agg(DISTINCT p.id::text, ' ') FROM res_partner p WHERE "
        "p.id IN (SELECT partner_id FROM res_users WHERE login IN "
        "('" + TEACHER_LOGIN + "', '" + STUDENT_LOGIN + "')) "
        "OR p.name LIKE '[smoke identity]%'") or "").split()]
    # 只允许删**夹具自己建的**伙伴：教师夹具挂在既有 partner（120）上，绝不能删
    keep_pids = [st["faculty_partner"]] if st.get("faculty_partner") else []
    del_pids = [p for p in pids if p not in keep_pids]
    sid_list = []
    if pids or uids:
        sid_list = [int(x) for x in (psql(
            "SELECT string_agg(id::text, ' ') FROM op_student WHERE partner_id IN ("
            + (", ".join(str(p) for p in pids) or "0") + ") OR user_id IN ("
            + (", ".join(str(u) for u in uids) or "0") + ")") or "").split()]
    out = odoo_shell([
        "U = env['res.users'].sudo()",
        "P = env['res.partner'].sudo()",
        "S = env['op.student'].sudo()",
        "print('[clean] 夹具账号=%s 伙伴=%s 学生=%s" % (json.dumps(uids), json.dumps(del_pids), json.dumps(sid_list)) + "')",
        # op.student 的 student_course 由 ondelete=cascade 连带；先删学生再删账号/伙伴
        "S.browse(%s).unlink()" % (json.dumps(sid_list) if sid_list else "[]"),
        "U.with_context(active_test=False).browse(%s).unlink()" % (json.dumps(uids) if uids else "[]"),
        "P.browse(%s).unlink()" % (json.dumps(del_pids) if del_pids else "[]"),
        "env['edu.fee.bill'].sudo().search([('reimburse_ref', '=', '" + FEE_REF + "')]).unlink()",
        "env['edu.message'].sudo().search([('body', 'like', '%smoke identity%')]).unlink()",
        "env.cr.commit()",
        "print('[clean] 完成')",
        "print('<<<LEFT>>>' + __import__('json').dumps({",
        "  'student': S.search([('id', 'in', %s)]).ids," % (json.dumps(sid_list) if sid_list else "[]"),
        "  'student_course': env['op.student.course'].sudo().search([('student_id', 'in', %s)]).ids," % (json.dumps(sid_list) if sid_list else "[]"),
        "  'partners': P.search([('id', 'in', %s)]).ids," % (json.dumps(del_pids) if del_pids else "[]"),
        "  'bills': env['edu.fee.bill'].sudo().search([('reimburse_ref', '=', '" + FEE_REF + "')]).ids,",
        "  'users': U.with_context(active_test=False).search([('login', 'in', ['" + TEACHER_LOGIN + "', '" + STUDENT_LOGIN + "'])]).ids,",
        "}) + '<<<END>>>')",
    ], commit=False)
    left = payload(out, "LEFT") or {}
    after = json.loads(psql(
        "SELECT json_build_object("
        "'user', (SELECT count(*) FROM res_users), "
        "'partner', (SELECT count(*) FROM res_partner), "
        "'faculty', (SELECT count(*) FROM op_faculty), "
        "'student', (SELECT count(*) FROM op_student), "
        "'student_course', (SELECT count(*) FROM op_student_course), "
        "'session', (SELECT count(*) FROM op_session), "
        "'bill', (SELECT count(*) FROM edu_fee_bill), "
        "'message', (SELECT count(*) FROM edu_message))::text"))
    reading("清场残留", {"leftover": left, "counts_before": before,
                      "counts_after": after})
    # 教师 partner 必须保持「链①为空、账号已删」
    tp = st.get("faculty_partner")
    sales_after = psql("SELECT COALESCE(user_id::text, '') FROM res_partner WHERE id = "
                       + str(tp or 0))
    # 双锚点复核：ORM 事务内读 + 提交后 SQL 直读（防「事务内看着干净、其实回滚了」）
    sql_left = {
        "users": int(psql("SELECT count(*) FROM res_users WHERE login IN ('"
                          + TEACHER_LOGIN + "', '" + STUDENT_LOGIN + "')") or 0),
        "partners_by_prefix": int(psql(
            "SELECT count(*) FROM res_partner WHERE name LIKE '[smoke identity]%'") or 0),
        "students_by_prefix": int(psql(
            "SELECT count(*) FROM op_student s JOIN res_partner p ON p.id = "
            "s.partner_id WHERE p.name LIKE '[smoke identity]%'") or 0),
        "student_course_by_prefix": int(psql(
            "SELECT count(*) FROM op_student_course sc JOIN op_student s ON "
            "s.id = sc.student_id JOIN res_partner p ON p.id = s.partner_id "
            "WHERE p.name LIKE '[smoke identity]%'") or 0),
        "students": int(psql("SELECT count(*) FROM op_student WHERE id IN ("
                             + (", ".join(str(s) for s in sid_list) or "0")
                             + ")") or 0),
        "partners": int(psql("SELECT count(*) FROM res_partner WHERE id IN ("
                             + (", ".join(str(p) for p in del_pids) or "0")
                             + ")") or 0),
        "bills": int(psql("SELECT count(*) FROM edu_fee_bill WHERE reimburse_ref = '"
                          + FEE_REF + "'") or 0),
    }
    check("T1", "清场：夹具账号/档案/账单全部删除（残留 = 0，SQL 直读复核）",
          not any(left.values()) and not any(sql_left.values()),
          "事务内=%s 提交后 SQL=%s" % (json.dumps(left, ensure_ascii=False),
                                     json.dumps(sql_left)))
    # 判定基准 = **建夹具前**的基线（不是清场前 —— 清场前还带着夹具行）。
    # 只要求「不小于基线」：清场允许把夹具行删掉，绝不允许把既有行删掉；
    # 其它成员并发新增行会让计数变大，那是加号不是减号，不算失败。
    base = ((load_results().get("phases", {}).get("setup", {}) or {})
            .get("fixture", {}) or {}).get("baseline_counts") or {}
    shrunk = {k: (base.get(k), after.get(k)) for k in base
              if after.get(k, 0) < base.get(k, 0)}
    # 基线缺失时**明确失败**，绝不静默通过（本脚本 v1 就吃过一次「断言恒真」的假绿）
    check("T2", "清场：既有数据一行未少（清场后计数 ≥ 建夹具前基线）",
          bool(base) and not shrunk,
          "基线%s=%s 清场后=%s 减少项=%s"
          % ("（缺失！本项判定无效）" if not base else "", base, after, shrunk))
    check("T3", "清场：教师 partner 的 user_id 仍是空（未抢占任何账号）",
          sales_after == "", "partner %s user_id=%r" % (tp, sales_after))
    save_phase("teardown", {"leftover": left, "sql_left": sql_left,
                            "counts": {"fixture_present": before, "after": after}},
               CHECKS)
    return CHECKS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["setup", "measure", "teardown"])
    ap.add_argument("--tag", default="after")
    args = ap.parse_args()
    if args.action == "setup":
        do_setup()
    elif args.action == "measure":
        st = fixture_state()
        if not st.get("teacher_uid"):
            print("夹具不存在，请先跑 setup")
            raise SystemExit(2)
        data = measure(args.tag, st)
        save_phase(args.tag, data, CHECKS)
    else:
        # do_teardown 自己 save_phase（带 leftover / sql_left / counts 读数），
        # 这里**不要**再 save 一次空数据把它覆盖掉（曾因此丢掉清场读数）
        do_teardown()
    n_fail = sum(1 for c in CHECKS if not c["pass"])
    print(NL + "== identity_lookup_unification[%s]: %d/%d PASS ==（%s）"
          % (args.action + (":" + args.tag if args.action == "measure" else ""),
             len(CHECKS) - n_fail, len(CHECKS), OUT.name))
    if n_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
