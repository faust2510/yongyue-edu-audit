#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批次 1：身份写入前置守卫（身份反查统一）—— 验收脚本。

被测的两处「写入前置守卫」（docs/audit/identity-lookup-unification.md §2.2 待办 #1/#2）：

  A) custom_addons/edu_portal/models/invite_code.py  _validate_identity()
     绑人码注册前的「该人员已绑账号」判定。
  B) custom_addons/edu_portal/controllers/contacts.py relink_save()
     老账号补挂身份的「一人一挂」守卫（写入见同文件 :385-389）。

为什么这两处最危险（不是「显示为空」，是**身份被抢**）
------------------------------------------------------
两处都是**写入前**的判定，判漏的后果是不可逆的数据正确性问题：
  · 同一份学生/教师/家长档案被绑到**两个账号**上 —— 两个账号都解析出同一份身份，
    甲的成绩/课表/账单会出现在乙的账号里；通知、权限、账单归属变成「谁先绑谁说话」；
  · 同一账号连挂**两份档案** —— 同上，只是方向相反。

漏在哪（一手证据，与上一轮同一根因）
------------------------------------
Odoo 19 的「账号 ↔ 伙伴」只有一条是规范关系：
    res.users.partner_id      （账号 → 伙伴）
    res.partner.user_ids      （伙伴 → 账号，其反向 one2many；core res_partner.py:287）
而 res.partner.user_id 是**销售员**字段（core res_partner.py:229 明写不是 partner_id
的反向），程序化 create res.users **不回填**它。
两处守卫都只查「链①」（档案自身 user_id / 伙伴的销售员列），**漏掉链②** ⇒
「账号是同一位伙伴的账号、但销售员列是空的」这种真实形态（脚本/接口建的账号）判不出来。

统一口径 = custom_addons/edu_schedule/models/identity.py（**唯一实现**，禁止第二套）：
反查 ①→②；正向 users_of_profile = ① 档案自身 user_id ∪ ② 伙伴 user_id ∪ ③ 伙伴 user_ids。

用法
----
  # 1) 建夹具（幂等；提交，夹具跨「升级前后」存活）
  python3 tests/smoke/identity_guard_batch1.py setup
  # 2) 改码前读数（必须在改动**之前**跑：它要证明漏判真能被触发）
  python3 tests/smoke/identity_guard_batch1.py measure --tag before
  # 3) 改码 + bash scripts/safe_upgrade.sh edu_portal
  # 4) 改码后读数（同一夹具；每条负向用例都必须被拒）
  python3 tests/smoke/identity_guard_batch1.py measure --tag after
  # 5) 清场（断言残留 = 0、全库计数回到基线）
  python3 tests/smoke/identity_guard_batch1.py teardown

结果落盘：tests/smoke/identity_guard_batch1_results.json（按 tag 累加）。

只碰本脚本自建的夹具（名字/登录/邀请码全部带 smoke_guard 前缀，一律按显式 id
定位，**不用 max(id) 之类的方式取号**）；夹具全部由 teardown 删除。
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

import requests  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
OUT = Path(__file__).resolve().parent / "identity_guard_batch1_results.json"
BASE = os.environ.get("SMOKE_BASE", "http://localhost:8069")
DB = os.environ.get("EDU_DB_NAME", "edu19")
DB_CONTAINER = os.environ.get("EDU_DB_CONTAINER", "edu19-clone-db-1")
PWD = "demo123"
NL = chr(10)

LOGIN_PREFIX = "smoke_guard_"
NAME_PREFIX = "[smoke guard]"
CODE_PREFIX = "SMOKE-GUARD-"
# 夹具锚点：**不能用名字**（op.student/op.faculty create 会把伙伴名改写成
# "New"/"名字 姓氏"），所以伙伴一律用 res.partner.ref 作稳定锚点。
REF_PREFIX = "smoke_guard_"

CHECKS = []
READINGS = []


def check(no, name, ok, detail=""):
    CHECKS.append({"no": no, "name": name, "pass": bool(ok),
                   "detail": str(detail)[:2000]})
    print("[%s] #%s %s%s" % ("PASS" if ok else "FAIL", no, name,
                             "" if ok else " | " + str(detail)[:700]))


def reading(name, value):
    READINGS.append({"name": name, "value": str(value)[:2000]})
    print("读数 | %s | %s" % (name, str(value)[:500]))


# ---------------------------------------------------------------------------
# 夹具定义（唯一事实源；setup / reset / teardown / 断言都从它派生）
# ---------------------------------------------------------------------------
SPEC = {
    "pwd": PWD,
    # 伙伴：名字即人眼标识，全部带前缀
    "partners": {
        "p1": NAME_PREFIX + " 学生甲伙伴",
        "p2": NAME_PREFIX + " 学生乙伙伴",
        "p3": NAME_PREFIX + " 抢挂账号丙伙伴",
        "p4": NAME_PREFIX + " 学生丁伙伴",
        "p5": NAME_PREFIX + " 学生戊伙伴",
        "p6": NAME_PREFIX + " 教师己伙伴",
        "p7": NAME_PREFIX + " 抢挂账号庚伙伴",
        "p8": NAME_PREFIX + " 学生辛伙伴",
        "p9": NAME_PREFIX + " 学生壬伙伴",
        "p9u": NAME_PREFIX + " 正向账号癸伙伴",
        "p10": NAME_PREFIX + " 家长子伙伴",
        "p11": NAME_PREFIX + " 抢挂账号丑伙伴",
    },
    # 账号：[key, login, partner_key]；绝不回填 partner.user_id（链① 为空）
    "users": [
        ["u1", LOGIN_PREFIX + "a@local", "p1"],    # 学生甲：只经链② 挂上
        ["u2", LOGIN_PREFIX + "b@local", "p2"],    # 学生乙：只经链② 挂上
        ["u3", LOGIN_PREFIX + "c@local", "p3"],    # 来抢学生乙的账号
        ["u4", LOGIN_PREFIX + "d@local", "p4"],    # 已挂学生丁（链①），想再挂学生戊
        ["u6", LOGIN_PREFIX + "e@local", "p6"],    # 教师己：只经链② 挂上
        ["u7", LOGIN_PREFIX + "f@local", "p7"],    # 来抢教师己的账号
        ["u9", LOGIN_PREFIX + "g@local", "p9u"],   # 正向：自由账号
        ["u10", LOGIN_PREFIX + "h@local", "p10"],  # 家长子：只经链② 挂上
        ["u11", LOGIN_PREFIX + "i@local", "p11"],  # 来抢家长子的账号
    ],
    # 学生：[key, partner_key, owner_user_key|None]
    "students": [
        ["s1", "p1", None],   # 甲：链② 被 u1 占用（链① 空）
        ["s2", "p2", None],   # 乙：链② 被 u2 占用（链① 空）
        ["s4", "p4", "u4"],   # 丁：链① 已挂 u4
        ["s5", "p5", None],   # 戊：空闲（u4 想再挂）
        ["s8", "p8", None],   # 辛：空闲（正向注册用）
        ["s9", "p9", None],   # 壬：空闲（正向重绑用）
    ],
    "faculty": [["f6", "p6"]],          # 教师己：链② 被 u6 占用（销售员列空）
    "parents": [["r10", "p10"]],        # 家长子：链② 被 u10 占用（user_id 空）
    # 邀请码：[key, code, identity, profile_key]
    "codes": [
        ["c1", CODE_PREFIX + "A", "student", "s1"],    # 负向：甲已被 u1（链②）占用
        ["c4", CODE_PREFIX + "B", "student", "s4"],    # 对照：丁已被 u4（链①）占用
        ["c8", CODE_PREFIX + "P", "student", "s8"],    # 正向：辛空闲
        ["c10", CODE_PREFIX + "R", "parent", "r10"],   # 负向：家长子已被 u10（链②）占用
    ],
    # 注册探针用的新邮箱（负向 ×2 / 正向 ×1）
    # 域名必须带点：注册页的 _EMAIL_RE 是 ^[^@\s]+@[^@\s]+\.[^@\s]+$
    # —— 'x@local' 会被「邮箱格式不正确」挡在身份校验之前（实测踩过）。
    "reg_logins": {
        "n1": LOGIN_PREFIX + "reg1@example.invalid",
        "n5": LOGIN_PREFIX + "reg5@example.invalid",
        "pos": LOGIN_PREFIX + "regpos@example.invalid",
    },
    # 复位后的期望状态（= 夹具原始态）
    "pristine": {
        "s1": None, "s2": None, "s4": "u4", "s5": None, "s8": None, "s9": None,
        "f6_partner_salesperson": None, "r10": None, "p1_salesperson": None,
        "p10_salesperson": None,
    },
}


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
def psql(sql):
    out = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", "odoo", "-d", DB,
         "-tAc", sql], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError("psql failed: " + out.stderr.strip()[:400])
    return out.stdout.strip()


def odoo_shell(lines, timeout=900, commit=False):
    """把若干行 python 喂给容器内 odoo shell。

    commit=False（默认）⇒ 末尾 rollback，只读探针不落库。
    """
    body = list(lines)
    body.append("env.cr.commit()" if commit else "env.cr.rollback()")
    cmd = ["docker", "compose", "exec", "-T", "web", "odoo", "shell",
           "-c", "/etc/odoo/odoo.conf", "-d", DB, "--db_host=db",
           "-r", "odoo", "-w", "odoo", "--no-http"]
    out = subprocess.run(cmd, input=NL.join(body), capture_output=True,
                         text=True, timeout=timeout, cwd=str(REPO))
    txt = (out.stdout or "") + (out.stderr or "")
    if out.returncode != 0:
        raise RuntimeError("odoo shell exit %s: %s" % (out.returncode, txt[-2000:]))
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
    return ("print('<<<" + tag + ">>>' + json.dumps(" + obj +
            ", ensure_ascii=False) + '<<<END>>>')")


def session_login(login, pwd):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + "/web/session/authenticate",
               json={"jsonrpc": "2.0",
                     "params": {"db": DB, "login": login, "password": pwd}},
               timeout=60)
    uid = (r.json().get("result") or {}).get("uid")
    return (s, uid) if uid else (None, None)


def csrf_of(session, url):
    r = session.get(BASE + url, timeout=60)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    if not m:
        m = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', r.text)
    return (m.group(1) if m else None), r.status_code


def http_post(session, url, data):
    """POST 且**不跟随重定向**：注册/补挂的成败都写在 Location 上。"""
    return session.post(BASE + url, data=data, timeout=90,
                        allow_redirects=False)


# ---------------------------------------------------------------------------
# 夹具：建 / 复位 / 清场（全部只碰 SPEC 里的对象）
# ---------------------------------------------------------------------------
def _spec_literal():
    return json.dumps(SPEC, ensure_ascii=False)


def _prelude():
    """夹具脚本的公共前奏：模型别名 + 按 SPEC 建/取记录的函数。"""
    return [
        "import json",
        "SPEC = json.loads(r'''" + _spec_literal() + "''')",
        "P = env['res.partner'].sudo(); U = env['res.users'].sudo()",
        "S = env['op.student'].sudo(); F = env['op.faculty'].sudo()",
        "Par = env['op.parent'].sudo(); C = env['edu.invite.code'].sudo()",
        "portal = env.ref('base.group_portal').id",
        "CREATE = True",
        "out = {}",
        "",
        "def _partner(key, name):",
        "    p = P.with_context(active_test=False).search(",
        "        [('ref', '=', '" + REF_PREFIX + "' + key)], limit=1)",
        "    if not p and CREATE:",
        "        p = P.create({'name': name, 'ref': '" + REF_PREFIX + "' + key})",
        "    out['p.' + key] = p.id",
        "    return p",
        "",
        "def _user(key, login, p):",
        "    u = U.with_context(active_test=False).search([('login', '=', login)], limit=1)",
        "    if not u and CREATE:",
        "        u = U.create({'login': login, 'partner_id': p.id, 'password': SPEC['pwd'],",
        "                      'active': True, 'group_ids': [(6, 0, [portal])]})",
        "    elif u and CREATE:",
        "        u.write({'partner_id': p.id, 'active': True, 'password': SPEC['pwd']})",
        "    out['u.' + key] = u.id",
        "    return u",
        "",
        "def _student(key, p):",
        "    if not p:",
        "        out['s.' + key] = None",
        "        return S.browse()",
        "    s = S.with_context(active_test=False).search([('partner_id', '=', p.id)], limit=1)",
        "    if not s and CREATE:",
        "        s = S.create({'partner_id': p.id, 'gender': 'm'})",
        "    out['s.' + key] = s.id",
        "    return s",
        "",
        "def _faculty(key, p):",
        "    if not p:",
        "        out['f.' + key] = None",
        "        return F.browse()",
        "    f = F.with_context(active_test=False).search([('partner_id', '=', p.id)], limit=1)",
        "    if not f and CREATE:",
        "        f = F.create({'partner_id': p.id, 'first_name': '冒烟', 'last_name': '教师己',",
        "                      'birth_date': '1985-01-01', 'gender': 'male'})",
        "    out['f.' + key] = f.id",
        "    return f",
        "",
        "def _parent(key, p):",
        "    if not p:",
        "        out['r.' + key] = None",
        "        return Par.browse()",
        "    r = Par.with_context(active_test=False).search([('name', '=', p.id)], limit=1)",
        "    if not r and CREATE:",
        "        rel = env['op.parent.relationship'].sudo().search([], limit=1)",
        "        r = Par.create({'name': p.id, 'relationship_id': rel.id, 'user_id': False})",
        "    out['r.' + key] = r.id",
        "    return r",
        "",
        "def _code(key, text, identity, rec):",
        "    c = C.with_context(active_test=False).search([('code', '=', text)], limit=1)",
        "    vals = {'code': text, 'code_kind': 'person', 'identity': identity,",
        "            'use_limit': 1, 'tier': False, 'parent_id': False,",
        "            'student_id': False, 'faculty_id': False,",
        "            'state': 'unused', 'used_count': 0, 'used_by': False,",
        "            'used_login': False, 'used_on': False}",
        "    vals['%s_id' % identity] = rec.id",
        "    if not c and CREATE:",
        "        c = C.create(vals)",
        "    elif c and CREATE:",
        "        c.write(vals)",
        "    out['c.' + key] = c.id",
        "    return c",
        "",
        "def _build():",
        "    recs = {'p': {}, 'u': {}, 's': {}, 'f': {}, 'r': {}, 'c': {}}",
        "    for k, name in SPEC['partners'].items():",
        "        recs['p'][k] = _partner(k, name)",
        "    for k, login, pk in SPEC['users']:",
        "        recs['u'][k] = _user(k, login, recs['p'][pk])",
        "    for k, pk, owner in SPEC['students']:",
        "        recs['s'][k] = _student(k, recs['p'][pk])",
        "    for k, pk in SPEC['faculty']:",
        "        recs['f'][k] = _faculty(k, recs['p'][pk])",
        "    for k, pk in SPEC['parents']:",
        "        recs['r'][k] = _parent(k, recs['p'][pk])",
        "    for k, text, identity, prof in SPEC['codes']:",
        "        recs['c'][k] = _code(k, text, identity, recs[prof[0]][prof])",
        "    # op.student/op.faculty 的 create 会把伙伴名改写成 'New'/'冒烟 教师己'",
        "    # （_inherits 委托）——夹具名字必须写回，否则读数不可读",
        "    for k, name in SPEC['partners'].items():",
        "        if recs['p'][k] and recs['p'][k].name != name:",
        "            recs['p'][k].write({'name': name})",
        "    return recs",
        "",
        "def _reg_users():",
        "    return U.with_context(active_test=False).search(",
        "        [('login', 'in', list(SPEC['reg_logins'].values()))])",
        "",
        "def _snapshot(recs):",
        "    st = {}",
        "    for k, s in recs['s'].items():",
        "        st['s.' + k] = s.user_id.id or None",
        "    for k, f in recs['f'].items():",
        "        st['f.' + k + '.salesperson'] = f.partner_id.user_id.id or None",
        "        st['f.' + k + '.users_on_partner'] = sorted(",
        "            U.with_context(active_test=False).search(",
        "                [('partner_id', '=', f.partner_id.id)]).ids)",
        "    for k, r in recs['r'].items():",
        "        st['r.' + k] = r.user_id.id or None",
        "        st['r.' + k + '.partner_salesperson'] = r.name.user_id.id or None",
        "    for k, p in recs['p'].items():",
        "        st['p.' + k + '.salesperson'] = p.user_id.id or None",
        "        st['p.' + k + '.users'] = sorted(",
        "            U.with_context(active_test=False).search(",
        "                [('partner_id', '=', p.id)]).ids)",
        "    for k, c in recs['c'].items():",
        "        st['c.' + k] = [c.state, c.used_count, c.used_by.id or None,",
        "                        c.used_login or None]",
        "    st['reg_accounts'] = sorted(_reg_users().ids)",
        "    st['ids'] = dict((kk + '|' + k, v.id) for kk, d in",
        "                     [('p', recs['p']), ('u', recs['u']), ('s', recs['s']),",
        "                      ('f', recs['f']), ('r', recs['r']), ('c', recs['c'])]",
        "                     for k, v in d.items())",
        "    return st",
    ]


def do_setup():
    baseline = json.loads(psql(COUNT_SQL))
    reading("建夹具前的基线计数", baseline)
    lines = _prelude() + [
        "recs = _build()",
        "for k, s in recs['s'].items():",
        "    owner = dict((a[0], a[2]) for a in SPEC['students'])[k]",
        "    s.write({'user_id': recs['u'][owner].id if owner else False})",
        "recs['r']['r10'].write({'user_id': False})",
        "for k in ('p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8', 'p9', 'p9u', 'p10', 'p11'):",
        "    if recs['p'][k].user_id:",
        "        recs['p'][k].write({'user_id': False})",
        "st = _snapshot(recs)",
        emit("SETUP", "st"),
    ]
    out = odoo_shell(lines, commit=True)
    st = payload(out, "SETUP")
    if not st:
        print(out[-3000:])
        raise RuntimeError("setup 未取到读数")
    reading("夹具 ids", st.get("ids"))
    reading("夹具状态（建好即复位态）", {k: v for k, v in st.items() if k != "ids"})
    ids = st.get("ids") or {}
    ok_chain = (
        st.get("s.s1") is None and st.get("s.s2") is None
        and st.get("s.s4") == ids.get("u|u4")
        and ids.get("u|u1") in (st.get("p.p1.users") or [])
        and ids.get("u|u2") in (st.get("p.p2.users") or [])
        and ids.get("u|u6") in (st.get("p.p6.users") or [])
        and ids.get("u|u10") in (st.get("p.p10.users") or [])
        and st.get("p.p1.salesperson") is None
        and st.get("f.f6.salesperson") is None
        and st.get("r.r10") is None
    )
    check("S1", "夹具就绪，且「链① 空 / 链② 命中」这个真实形态成立",
          ok_chain and len(st.get("reg_accounts") or []) == 0,
          json.dumps({"ids": ids, "chain_ok": bool(ok_chain),
                      "reg_accounts": st.get("reg_accounts")},
                     ensure_ascii=False))
    baseline2 = json.loads(psql(COUNT_SQL))
    st["baseline_counts"] = baseline
    save_phase("setup", {"fixture": st, "counts_after": baseline2}, [])
    return st


def do_reset(tag, expect_pristine=True):
    """把夹具复位到原始态（只碰 SPEC 里的记录），并返回复位后状态。"""
    lines = _prelude() + [
        "recs = _build()",
        # 顺序硬要求（实测踩过）：op.student.user_id 是 ondelete='cascade'
        # —— 先删注册探针建的账号，会把整条学生档案一起级联删掉。
        # 所以：① 先摘掉所有档案上的账号列；② 再删探针账号；③ 最后写回夹具原始归属。
        "for k, s in recs['s'].items():",
        "    if s.user_id:",
        "        s.write({'user_id': False})",
        "for k, f in recs['f'].items():",
        "    if f.partner_id.user_id:",
        "        f.partner_id.write({'user_id': False})",
        "for k, r in recs['r'].items():",
        "    if r.user_id:",
        "        r.write({'user_id': False})",
        "    if r.name and r.name.user_id:",
        "        r.name.write({'user_id': False})",
        "for k, p in recs['p'].items():",
        "    if p.user_id:",
        "        p.write({'user_id': False})",
        "for u in _reg_users():",
        "    u.unlink()",
        "for k, s in recs['s'].items():",
        "    owner = dict((a[0], a[2]) for a in SPEC['students'])[k]",
        "    want = recs['u'][owner].id if owner else False",
        "    if s.user_id.id != want:",
        "        s.write({'user_id': want})",
        "st = _snapshot(recs)",
        emit("RESET", "st"),
    ]
    out = odoo_shell(lines, commit=True)
    st = payload(out, "RESET")
    if st is None:
        print(out[-3000:])
        raise RuntimeError("reset 未取到读数")
    if expect_pristine:
        want_none = ["s.s1", "s.s2", "s.s5", "s.s8", "s.s9", "r.r10",
                     "f.f6.salesperson", "p.p1.salesperson", "p.p10.salesperson"]
        bad = [(k, st.get(k)) for k in want_none if st.get(k) is not None]
        check("R1", "[%s] 夹具已复位（负向探针的写入全部撤销）" % tag,
              not bad and not st.get("reg_accounts"),
              "异常项=%s 注册残留=%s" % (bad, st.get("reg_accounts")))
    reading("[%s] 复位后夹具状态" % tag, st)
    return st


COUNT_SQL = (
    "SELECT json_build_object("
    "'user', (SELECT count(*) FROM res_users), "
    "'partner', (SELECT count(*) FROM res_partner), "
    "'student', (SELECT count(*) FROM op_student), "
    "'faculty', (SELECT count(*) FROM op_faculty), "
    "'parent', (SELECT count(*) FROM op_parent), "
    "'invite', (SELECT count(*) FROM edu_invite_code))::text")


def do_teardown(st):
    """删除夹具：invite → parent → student → faculty → users → partners。

    计数口径（为什么不跟 setup 基线比）：同一台库里还有别的代理在并发造数，
    「回到基线」会被别人的数据搅成假红。改为断言**自洽不变量**：
        拆除前计数 - 拆除后计数 == 本次删掉的条数（逐表）
    这既证明「我删干净了」，也证明「我没有多删别人的」。
    """
    pre = json.loads(psql(COUNT_SQL))
    lines = _prelude() + [
        "CREATE = False",
        "recs = _build()",
        # 同上：先摘账号列，再删探针账号（op.student.user_id 是 cascade）
        "for k, s in recs['s'].items():",
        "    if s and s.user_id:",
        "        s.write({'user_id': False})",
        "for k, p in recs['p'].items():",
        "    if p and p.user_id:",
        "        p.write({'user_id': False})",
        "for u in _reg_users():",
        "    u.unlink()",
        "deleted = {'codes': [], 'parents': [], 'students': [], 'faculty': [],",
        "           'users': [], 'partners': []}",
        "for c in recs['c'].values():",
        "    if c:",
        "        deleted['codes'].append(c.id)",
        "        c.unlink()",
        "for r in recs['r'].values():",
        "    if r:",
        "        r.write({'user_id': False})",
        "        if r.name:",
        "            r.name.write({'user_id': False})",
        "        deleted['parents'].append(r.id)",
        "        r.unlink()",
        "for s in recs['s'].values():",
        "    if s:",
        "        s.write({'user_id': False})",
        "        deleted['students'].append(s.id)",
        "        s.unlink()",
        "for f in recs['f'].values():",
        "    if f:",
        "        f.partner_id.write({'user_id': False})",
        "        deleted['faculty'].append(f.id)",
        "        f.unlink()",
        "for u in recs['u'].values():",
        "    if u:",
        "        deleted['users'].append(u.id)",
        "        u.unlink()",
        "for p in recs['p'].values():",
        "    if p:",
        "        p.write({'user_id': False})",
        "        deleted['partners'].append(p.id)",
        "        p.unlink()",
        "left = {}",
        "left['users'] = U.with_context(active_test=False).search(",
        "    [('login', '=like', '" + LOGIN_PREFIX + "%')]).ids",
        "left['partners_by_ref'] = P.with_context(active_test=False).search(",
        "    [('ref', '=like', '" + REF_PREFIX + "%')]).ids",
        "left['partners_by_name'] = P.with_context(active_test=False).search(",
        "    [('name', '=like', '" + NAME_PREFIX + "%')]).ids",
        "left['codes'] = C.with_context(active_test=False).search(",
        "    [('code', '=like', '" + CODE_PREFIX + "%')]).ids",
        "plist = [p.id for p in recs['p'].values() if p]",
        "left['students'] = S.with_context(active_test=False).search(",
        "    [('partner_id', 'in', plist)]).ids",
        "left['faculty'] = F.with_context(active_test=False).search(",
        "    [('partner_id', 'in', plist)]).ids",
        "left['parents'] = Par.with_context(active_test=False).search(",
        "    [('name', 'in', plist)]).ids",
        emit("TEARDOWN", "{'deleted': deleted, 'left': left}"),
    ]
    out = odoo_shell(lines, commit=True)
    res = payload(out, "TEARDOWN")
    if res is None:
        print(out[-3000:])
        raise RuntimeError("teardown 未取到读数")
    reading("删除的夹具", {k: len(v) for k, v in res["deleted"].items()})
    reading("残留（必须全空）", res["left"])
    left = res["left"]
    check("T1", "清场残留 = 0（账号 / 伙伴 / 邀请码 / 学生 / 教师 / 家长）",
          not any(left.get(k) for k in left),
          json.dumps(left, ensure_ascii=False))
    after = json.loads(psql(COUNT_SQL))
    key_of = {"codes": "invite", "parents": "parent", "students": "student",
              "faculty": "faculty", "users": "user", "partners": "partner"}
    delta = {}
    for k, key in key_of.items():
        delta[key] = [pre.get(key), pre.get(key) - after.get(key),
                      len(res["deleted"][k])]
    bad = {k: v for k, v in delta.items() if v[1] != v[2]}
    reading("拆除前后计数（[前, 前-后, 本次删除条数]）", delta)
    reading("清场后全库计数", after)
    check("T2", "拆除的条数 = 计数差（我删干净了，也没多删别人的）",
          not bad, json.dumps(bad, ensure_ascii=False))
    save_phase("teardown", {"pre_counts": pre, "after_counts": after,
                            "delta": delta, "left": left}, CHECKS[-2:])
    return res


def load_results():
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {"suite": "identity_guard_batch1", "db": DB,
            "phases": {}, "checks": [], "readings": []}


def save_phase(tag, data, checks):
    doc = load_results()
    doc["generated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    doc["phases"][tag] = data
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
# 链级事实（改前/改后逐条对比用；纯 SQL 只读）
# ---------------------------------------------------------------------------
def chain_facts():
    """返回 {模型: {id: {'c1':..., 'c2':[...], 'owners': [...]}}}。

    c1 = 链①（档案自身 user_id / 教师=伙伴销售员列），c2 = 链②（伙伴 user_ids）。
    """
    rows = psql(
        "SELECT json_build_object("
        "'student', (SELECT json_agg(json_build_object('id', s.id, "
        "  'c1', s.user_id, 'c2', (SELECT json_agg(u.id ORDER BY u.id) FROM res_users u "
        "  WHERE u.partner_id = s.partner_id AND u.active) ) ORDER BY s.id) FROM op_student s), "
        "'faculty', (SELECT json_agg(json_build_object('id', f.id, "
        "  'c1', p.user_id, 'c2', (SELECT json_agg(u.id ORDER BY u.id) FROM res_users u "
        "  WHERE u.partner_id = f.partner_id AND u.active) ) ORDER BY f.id) "
        "  FROM op_faculty f JOIN res_partner p ON p.id = f.partner_id), "
        "'parent', (SELECT json_agg(json_build_object('id', r.id, "
        "  'c1', r.user_id, 'c2', (SELECT json_agg(u.id ORDER BY u.id) FROM res_users u "
        "  WHERE u.partner_id = r.name AND u.active) ) ORDER BY r.id) FROM op_parent r)"
        ")::text")
    raw = json.loads(rows)
    out = {}
    for model, items in raw.items():
        out[model] = {}
        for it in (items or []):
            out[model][str(it["id"])] = {"c1": it["c1"], "c2": it["c2"] or []}
    return out


def parse_location(loc):
    """把 /edu/backend/relink_identity?... 的 Location 解析成 dict。"""
    q = loc.split("?", 1)[1] if "?" in loc else ""
    res = {}
    for part in unquote(q).split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            res[k] = v
    return res


def owners_via_sql(model, pid):
    """档案 → 账号（链① ∪ 链②），纯 SQL 读数，供报告引用。"""
    if model == "student":
        sql = ("SELECT json_build_object('c1', s.user_id, 'c2', "
               "(SELECT json_agg(u.id ORDER BY u.id) FROM res_users u "
               " WHERE u.partner_id = s.partner_id AND u.active))::text "
               "FROM op_student s WHERE s.id = %d" % pid)
    elif model == "faculty":
        sql = ("SELECT json_build_object('c1', p.user_id, 'c2', "
               "(SELECT json_agg(u.id ORDER BY u.id) FROM res_users u "
               " WHERE u.partner_id = f.partner_id AND u.active))::text "
               "FROM op_faculty f JOIN res_partner p ON p.id = f.partner_id "
               "WHERE f.id = %d" % pid)
    else:
        sql = ("SELECT json_build_object('c1', r.user_id, 'c2', "
               "(SELECT json_agg(u.id ORDER BY u.id) FROM res_users u "
               " WHERE u.partner_id = r.name AND u.active))::text "
               "FROM op_parent r WHERE r.id = %d" % pid)
    d = json.loads(psql(sql))
    owners = set(d["c2"] or [])
    if d["c1"]:
        owners.add(d["c1"])
    return {"c1": d["c1"], "c2": sorted(d["c2"] or []), "owners": sorted(owners)}


def user_holdings(uid):
    """账号 → 档案（identity.py 反查 ①→②），纯 SQL 复刻；用于零回归矩阵。"""
    facts = chain_facts()
    held = {}
    for model in ("student", "faculty", "parent"):
        for pid, f in facts[model].items():
            if f["c1"] == uid:
                held.setdefault(model, []).append(pid)
            elif uid in f["c2"]:
                held.setdefault(model, []).append(pid)
    return held


# ---------------------------------------------------------------------------
# 静态读数（源码片段）
# ---------------------------------------------------------------------------
INVITE_SRC = "custom_addons/edu_portal/models/invite_code.py"
CONTACTS_SRC = "custom_addons/edu_portal/controllers/contacts.py"


def static_probe():
    inv = (REPO / INVITE_SRC).read_text(encoding="utf-8")
    con = (REPO / CONTACTS_SRC).read_text(encoding="utf-8")
    return {
        "invite_imports_identity": "edu_schedule.models.identity" in inv,
        "invite_uses_users_of_profile": "users_of_profile" in inv,
        "invite_old_guard_present":
            "if not linked and self.identity in ('student', 'faculty')" in inv,
        "contacts_imports_identity": "edu_schedule.models.identity" in con,
        "contacts_uses_users_of_profile": "users_of_profile" in con,
        "contacts_uses_profile_of_user":
            ("student_of_user" in con and "faculty_of_user" in con
             and "parent_of_user" in con),
        "contacts_old_guard_present":
            "if not linked and role in ('student', 'faculty')" in con,
        "contacts_guard_fn_present": "def relink_guard_reason" in con,
    }


# ---------------------------------------------------------------------------
# 只读探针（odoo shell，末尾 rollback）
# ---------------------------------------------------------------------------
def probe_codes():
    """直接调 _validate_identity()（三张绑人码）——写入前的判定本身。"""
    lines = _prelude() + [
        "recs = _build()",
        "res = {}",
        "for k in recs['c']:",
        "    c = recs['c'][k]",
        "    rec = c.identity_record()",
        "    res[k] = {'code': c.code, 'identity': c.identity,",
        "              'profile': rec.id if rec else None,",
        "              'verdict': c._validate_identity()}",
        emit("CODES", "res"),
    ]
    return payload(odoo_shell(lines), "CODES")


def probe_resolve(uids):
    """账号 → 身份档案（identity.py 的公共 helper，改前改后同一口径）。"""
    lines = [
        "import json",
        "from odoo.addons.edu_schedule.models.identity import (",
        "    student_of_user, faculty_of_user, parent_of_user)",
        "res = {}",
        "for uid in " + repr(list(uids)) + ":",
        "    res[str(uid)] = {'student': student_of_user(env, uid).ids,",
        "                     'faculty': faculty_of_user(env, uid).ids,",
        "                     'parent': parent_of_user(env, uid).ids}",
        emit("RESOLVE", "res"),
    ]
    return payload(odoo_shell(lines), "RESOLVE")


def probe_guard_matrix():
    """用**新守卫函数本身**过一遍既有数据（改前该函数不存在 ⇒ 返回 None）。"""
    lines = _prelude() + [
        "from odoo.addons.edu_schedule.models.identity import users_of_profile",
        "try:",
        "    from odoo.addons.edu_portal.controllers.contacts import relink_guard_reason",
        "except ImportError as exc:",
        "    relink_guard_reason = None",
        "    _imp_err = repr(exc)",
        "if relink_guard_reason is None:",
        "    print('<<<GUARD>>>' + json.dumps({'error': _imp_err}) + '<<<END>>>')",
        "else:",
        "    M = {'student': S, 'faculty': F, 'parent': Par}",
        "    rows, multi = [], []",
        "    for u in U.with_context(active_test=False).search([('login', 'not like', '" + LOGIN_PREFIX + "%')]):",
        "        held = []",
        "        for model, Model in M.items():",
        "            for rec in Model.with_context(active_test=False).search([]):",
        "                if u in users_of_profile(rec):",
        "                    held.append(model + ':' + str(rec.id))",
        "                    rows.append([u.login, model, rec.id, relink_guard_reason(u, rec)])",
        "        if len(held) > 1:",
        "            multi.append([u.login, held])",
        "    " + emit("GUARD", "{'rows': rows, 'multi': multi}"),
    ]
    return payload(odoo_shell(lines), "GUARD")


def probe_monotonicity():
    """把**改前实现逐字复刻**成对照 oracle，与改后的真实实现逐条对拍。

    判据（守卫的「只加不减」）：旧实现判「已占用」的每一条，新实现必须仍判
    「已占用」；新增的「已占用」条数即本次修复的净收益。oracle 只用于对照，
    不是生产实现（生产只有 identity.py 一处口径）。

    改前实现（已删除）原文：
        linked = person.user_id
        if not linked and role in ('student', 'faculty') and person.partner_id:
            linked = person.partner_id.user_id
        if not linked and role == 'parent' and person.name:
            linked = person.name.user_id
        if linked and uid not in linked.ids:            # 补挂侧
        if linked:                                      # 绑人码侧（无 uid 比较）
    """
    lines = _prelude() + [
        "CREATE = False",
        "recs = _build()",
        "try:",
        "    from odoo.addons.edu_portal.controllers.contacts import relink_guard_reason",
        "except ImportError:",
        "    relink_guard_reason = None",
        "",
        "def old_relink_skip(u, person):",
        "    linked = person.user_id",
        "    if not linked and person._name in ('op.student', 'op.faculty') and person.partner_id:",
        "        linked = person.partner_id.user_id",
        "    if not linked and person._name == 'op.parent' and person.name:",
        "        linked = person.name.user_id",
        "    return bool(linked) and u.id not in linked.ids",
        "",
        "def old_code_blocked(c, rec):",
        "    linked = rec.user_id",
        "    if not linked and c.identity in ('student', 'faculty') and rec.partner_id:",
        "        linked = rec.partner_id.user_id",
        "    if not linked and c.identity == 'parent' and rec.name:",
        "        linked = rec.name.user_id",
        "    return bool(linked)",
        "",
        "M = {'student': S, 'faculty': F, 'parent': Par}",
        "lost, added, pairs = [], [], 0",
        "for u in U.with_context(active_test=False).search([]):",
        "    for model, Model in M.items():",
        "        for rec in Model.with_context(active_test=False).search([]):",
        "            old = old_relink_skip(u, rec)",
        "            new = bool(relink_guard_reason(u, rec)) if relink_guard_reason else None",
        "            if new is None:",
        "                continue",
        "            pairs += 1",
        "            if old and not new:",
        "                lost.append([u.login, model, rec.id])",
        "            if new and not old:",
        "                added.append([u.login, model, rec.id])",
        "clost, cadded = [], []",
        "for k, c in recs['c'].items():",
        "    rec = c.identity_record()",
        "    old = old_code_blocked(c, rec)",
        "    new = bool(c._validate_identity())",
        "    if old and not new:",
        "        clost.append([k, c.code])",
        "    if new and not old:",
        "        cadded.append([k, c.code])",
        emit("MONO", ("{'pairs': pairs, 'lost': lost, 'added': added,"
                      " 'code_lost': clost, 'code_added': cadded,"
                      " 'fn': bool(relink_guard_reason)}")),
    ]
    return payload(odoo_shell(lines), "MONO")


# ---------------------------------------------------------------------------
# HTTP 真机探针
# ---------------------------------------------------------------------------
def public_session():
    s = requests.Session()
    s.trust_env = False
    return s


def reg_attempt(login, code, name):
    """走真实注册路由 /register/submit（公开、csrf、不跟随重定向）。"""
    s = public_session()
    token, page = csrf_of(s, "/register")
    r = http_post(s, "/register/submit", {
        "csrf_token": token, "code": code, "name": name,
        "email": login, "password": PWD, "confirm": PWD})
    loc = unquote(r.headers.get("Location", "") or "")
    return {"status": r.status_code, "location": loc, "register_page": page,
            "has_token": bool(token), "created": bool(account_id(login))}


def account_id(login):
    return psql("SELECT id FROM res_users WHERE login = '%s'" % login)


def relink_attempt(session, uid, role, pid):
    """走真实补挂路由 /edu/backend/relink_identity/save（POST，不跟随重定向）。"""
    token, page = csrf_of(session, "/edu/backend/relink_identity")
    r = http_post(session, "/edu/backend/relink_identity/save", {
        "csrf_token": token, "person_%d" % uid: "%s:%d" % (role, pid)})
    loc = unquote(r.headers.get("Location", "") or "")
    out = {"status": r.status_code, "location": loc, "form_page": page,
           "has_token": bool(token)}
    out.update(parse_location(loc))
    return out


# ---------------------------------------------------------------------------
# 零回归矩阵（既有账号 × 既有身份，只加不减）
# ---------------------------------------------------------------------------
def existing_matrix():
    """既有账号（排除夹具账号）→ 三个身份模型的解析结果，逐条可对拍。"""
    facts = chain_facts()
    res = {}
    for line in psql("SELECT id || '|' || login FROM res_users ORDER BY id").splitlines():
        uid_s, login = line.split("|", 1)
        if login.startswith(LOGIN_PREFIX):
            continue
        uid = int(uid_s)
        held = {}
        for model in ("student", "faculty", "parent"):
            ids = [int(pid) for pid, f in facts[model].items()
                   if f["c1"] == uid or uid in f["c2"]]
            if ids:
                held[model] = sorted(ids)
        res[login] = held
    return res


def existing_profiles():
    """既有档案 → owner 账号集合（链① ∪ 链②）。"""
    facts = chain_facts()
    res = {}
    for model in ("student", "faculty", "parent"):
        for pid, f in facts[model].items():
            owners = set(f["c2"])
            if f["c1"]:
                owners.add(f["c1"])
            res["%s:%s" % (model, pid)] = sorted(owners)
    return res


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------
def measure(tag):
    st = do_reset(tag)
    ids = st.get("ids") or {}
    data = {"fixture_state": st}
    before = (tag == "before")

    # ===== 0) 静态 =====
    static = static_probe()
    reading("静态：两处守卫的写法", static)
    if before:
        check("B0", "[before] 两处仍只查链①（公共 helper 尚未接入）",
              static["invite_old_guard_present"]
              and static["contacts_old_guard_present"]
              and not static["invite_uses_users_of_profile"]
              and not static["contacts_uses_users_of_profile"],
              json.dumps(static, ensure_ascii=False))
    else:
        check("C0", "[after] 两处守卫都改走 identity.py 公共 helper（旧片段 0 处）",
              static["invite_uses_users_of_profile"]
              and static["invite_imports_identity"]
              and not static["invite_old_guard_present"]
              and static["contacts_uses_users_of_profile"]
              and static["contacts_imports_identity"]
              and static["contacts_uses_profile_of_user"]
              and not static["contacts_old_guard_present"],
              json.dumps(static, ensure_ascii=False))

    # ===== 1) 写入前判定本身（直接调 _validate_identity）=====
    codes = probe_codes()
    reading("绑人码 _validate_identity() 判定（c1=学生甲已被占用 / c8=学生辛空闲 / c10=家长子已被占用）",
            codes)
    data["code_verdicts"] = codes
    if before:
        check("B1", "[before] 复现①：学生甲已被账号 u1（链②）占用，绑人码仍判「可注册」",
              codes and codes["c1"]["verdict"] is None,
              json.dumps(codes and codes["c1"], ensure_ascii=False))
        check("B1b", "[before] 复现①-对称：家长子已被账号 u10（链②）占用，同样判「可注册」",
              codes and codes["c10"]["verdict"] is None,
              json.dumps(codes and codes["c10"], ensure_ascii=False))
        check("B1c", "[before] 对照：空闲档案（学生辛）本就该放行",
              codes and codes["c8"]["verdict"] is None,
              json.dumps(codes and codes["c8"], ensure_ascii=False))
    else:
        check("N1", "[after] 学生甲已被 u1 占用 ⇒ 绑人码必须拒（且是人话提示）",
              codes and codes["c1"]["verdict"]
              and "已绑定其他账号" in codes["c1"]["verdict"],
              json.dumps(codes and codes["c1"], ensure_ascii=False))
        check("N1b", "[after] 家长子已被 u10 占用 ⇒ 绑人码必须拒",
              codes and codes["c10"]["verdict"]
              and "已绑定其他账号" in codes["c10"]["verdict"],
              json.dumps(codes and codes["c10"], ensure_ascii=False))
        check("P1c", "[after] 空闲档案（学生辛）不被误伤：仍然放行",
              codes and codes["c8"]["verdict"] is None,
              json.dumps(codes and codes["c8"], ensure_ascii=False))
    # 对照：链① 占用的档案（学生丁 ← u4.user_id）改前改后都必须被拒
    # —— 新实现只许「多判」，不许丢掉旧实现判得出的任何一条
    check("N9c", "对照（改前改后同）：链① 占用的档案，绑人码仍被拒",
          codes and codes["c4"]["verdict"]
          and "已绑定其他账号" in codes["c4"]["verdict"],
          json.dumps(codes and codes["c4"], ensure_ascii=False))

    # ===== 2) N1：真机走注册路由（学生甲已被 u1 占用）=====
    s1, u1, p1 = int(ids["s|s1"]), int(ids["u|u1"]), int(ids["p|p1"])
    r1 = reg_attempt(SPEC["reg_logins"]["n1"], CODE_PREFIX + "A", "冒烟抢绑甲")
    o1 = owners_via_sql("student", s1)
    reading("N1 注册（学生甲）HTTP 读数", r1)
    reading("N1 注册后学生甲的 owner 集合（链① ∪ 链②）", o1)
    data["n1"] = {"http": r1, "owners": o1}
    if before:
        check("B2", "[before] 复现①落地：注册真的建出第二个账号，学生甲被两个账号同时占用",
              r1["status"] in (302, 303) and r1["created"]
              and len(o1["owners"]) == 2 and u1 in o1["owners"],
              "location=%s owners=%s" % (r1["location"], o1))
    else:
        check("N2", "[after] 注册被拒：不建账号、不写档案（人话提示而非 500）",
              r1["status"] in (302, 303) and not r1["created"]
              and "/register?" in r1["location"] and "error=" in r1["location"]
              and o1["owners"] == [u1],
              "location=%s owners=%s" % (r1["location"], o1))

    # 抢身份读数：两个账号都解析出同一份学生档案（before 阶段真机取证）
    if before and r1["created"]:
        reg1 = int(account_id(SPEC["reg_logins"]["n1"]))
        rv = probe_resolve([u1, reg1])
        reading("N1 两个账号的 identity.py 解析结果（同一份学生档案）", rv)
        data["n1"]["resolve"] = rv
        check("B3", "[before] 身份被抢：u1 与新建账号**都**解析出学生甲",
              rv and str(u1) in rv and str(reg1) in rv
              and rv[str(u1)]["student"] == rv[str(reg1)]["student"] == [s1],
              json.dumps(rv, ensure_ascii=False))
    else:
        rv = probe_resolve([u1])
        data["n1"]["resolve"] = rv
        check("N3", "[after] 修复后 u1 仍是学生甲的唯一账号（解析未受影响）",
              rv and rv[str(u1)]["student"] == [s1],
              json.dumps(rv, ensure_ascii=False))

    # ===== 3) N5：真机注册（家长子已被 u10 占用）=====
    r10, u10 = int(ids["r|r10"]), int(ids["u|u10"])
    r5 = reg_attempt(SPEC["reg_logins"]["n5"], CODE_PREFIX + "R", "冒烟抢绑家长")
    o5 = owners_via_sql("parent", r10)
    reading("N5 注册（家长子）HTTP 读数", r5)
    reading("N5 注册后家长子的 owner 集合", o5)
    data["n5"] = {"http": r5, "owners": o5}
    if before:
        check("B4", "[before] 复现①-家长分支：注册建出第二个账号，家长档案被两个账号占用",
              r5["status"] in (302, 303) and r5["created"]
              and len(o5["owners"]) == 2 and u10 in o5["owners"],
              "location=%s owners=%s" % (r5["location"], o5))
    else:
        check("N4", "[after] 家长分支同样被拒：不建账号、不写档案",
              r5["status"] in (302, 303) and not r5["created"]
              and "/register?" in r5["location"]
              and o5["owners"] == [u10],
              "location=%s owners=%s" % (r5["location"], o5))

    # ===== 4) 补挂工具（relink）四条 =====
    admin, auid = session_login("admin", "admin")
    if not auid:
        raise RuntimeError("admin 登录失败（/edu/backend/relink_identity 需要后台组）")
    reading("admin 会话 uid", auid)

    # (检查号, 说明, role, 档案 key, 账号 key, 期望 dbg 前缀, 期望人话片段, 期望 owner)
    cases = [
        ("N6", "relink|学生乙已被 u2（链②）占用，u3 来抢", "student", "s|s2",
         "u|u3", "linked-skip", "该人员已绑定其他账号", "u|u2"),
        ("N7", "relink|u4 已挂学生丁，再挂学生戊（一个账号挂两份档案）", "student",
         "s|s5", "u|u4", "user-taken-skip", "该账号已挂接其他身份档案", None),
        ("N8", "relink|教师己已被 u6（链②）占用，u7 来抢", "faculty", "f|f6",
         "u|u7", "linked-skip", "该人员已绑定其他账号", "u|u6"),
    ]
    data["relink"] = {}
    for no, label, role, prof_key, user_key, want_code, want_text, want_owner in cases:
        pid = int(ids[prof_key])
        uid = int(ids[user_key])
        attempt = relink_attempt(admin, uid, role, pid)
        owners = owners_via_sql(role, pid)
        held = probe_resolve([uid])
        reading(label + "：HTTP 读数", attempt)
        reading(label + "：档案 owner 集合", owners)
        reading(label + "：该账号解析出的身份", held)
        data["relink"][no] = {"http": attempt, "owners": owners, "held": held,
                              "role": role, "pid": pid, "uid": uid}
        if before:
            check("B5" + no[-1], "[before] 复现②：%s —— 守卫放行并真的写库" % label,
                  attempt.get("ok") == "1" and attempt.get("skip") == "0",
                  json.dumps(attempt, ensure_ascii=False))
        else:
            dbg = attempt.get("dbg") or ""
            same_owner = (want_owner is None
                          or owners["owners"] == [int(ids[want_owner])])
            check(no, "[after] 必须被拒且不写库：%s" % label,
                  attempt.get("skip") == "1" and attempt.get("ok") == "0"
                  and want_code in dbg and want_text in dbg and same_owner,
                  json.dumps({"http": attempt, "owners": owners}, ensure_ascii=False))

    # 4b) 对照（改前改后同）：链① 占用的档案也必须拒 —— 旧实现的检测一条都不能丢
    a9 = relink_attempt(admin, int(ids["u|u3"]), "student", int(ids["s|s4"]))
    reading("对照：u3 抢「链① 已挂 u4」的学生丁（改前改后都应拒）", a9)
    data["relink_chain1_control"] = a9
    check("N9r", "对照（改前改后同）：链① 占用的档案，补挂仍被拒",
          a9.get("skip") == "1" and a9.get("ok") == "0"
          and "linked-skip" in (a9.get("dbg") or ""),
          json.dumps(a9, ensure_ascii=False))

    # 抢身份读数（before）：一个档案两个账号 / 一个账号两份档案
    if before:
        o2 = data["relink"]["N6"]["owners"]
        check("B6", "[before] 身份被抢：学生乙的 owner 变成 {u2, u3} 两个账号",
              len(o2["owners"]) == 2,
              json.dumps(o2, ensure_ascii=False))
        o4 = owners_via_sql("student", int(ids["s|s4"]))
        o5b = data["relink"]["N7"]["owners"]
        check("B7", "[before] 一人多绑：u4 既占用学生丁、又占用了学生戊",
              data["relink"]["N7"]["http"].get("ok") == "1"
              and o5b["c1"] == int(ids["u|u4"]) and o4["owners"] == [int(ids["u|u4"])],
              json.dumps({"s4": o4, "s5": o5b}, ensure_ascii=False))
        check("B8", "[before] 教师被抢：教师己的 owner 变成 {u6, u7} 两个账号",
              len(data["relink"]["N8"]["owners"]["owners"]) == 2,
              json.dumps(data["relink"]["N8"]["owners"], ensure_ascii=False))

    # ===== 5) 正向：正常的一次绑定必须成功（改前改后都要成功）=====
    rp = reg_attempt(SPEC["reg_logins"]["pos"], CODE_PREFIX + "P", "冒烟正向辛")
    s8 = int(ids["s|s8"])
    o8 = owners_via_sql("student", s8)
    reading("正向注册（学生辛，空闲）HTTP 读数", rp)
    reading("正向注册后学生辛的 owner 集合", o8)
    data["positive_reg"] = {"http": rp, "owners": o8}
    check("P1", "正向用例：空闲档案的正常注册仍然成功（账号建出、档案挂上）",
          rp["status"] in (302, 303) and rp["created"] and o8["c1"]
          and o8["owners"] == [o8["c1"]],
          "location=%s owners=%s" % (rp["location"], o8))

    u9, s9 = int(ids["u|u9"]), int(ids["s|s9"])
    p2 = relink_attempt(admin, u9, "student", s9)
    o9 = owners_via_sql("student", s9)
    reading("正向补挂（u9 ← 学生壬）HTTP 读数", p2)
    reading("正向补挂后学生壬的 owner 集合", o9)
    data["positive_relink"] = {"http": p2, "owners": o9}
    check("P2", "正向用例：空闲账号 ← 空闲档案的补挂仍然成功",
          p2.get("ok") == "1" and o9["owners"] == [u9],
          json.dumps({"http": p2, "owners": o9}, ensure_ascii=False))
    p3 = relink_attempt(admin, u9, "student", s9)
    reading("正向补挂重发同一绑定（幂等，不得被新守卫误拒）", p3)
    data["positive_relink_again"] = {"http": p3}
    check("P3", "正向用例：重发**同一**绑定仍是成功（守卫不误伤幂等重存）",
          p3.get("ok") == "1", json.dumps(p3, ensure_ascii=False))

    # ===== 6) 探针痕迹复位 =====
    st2 = do_reset(tag + "|end")

    # ===== 7) 零回归：既有账号 × 既有身份 逐条 =====
    matrix = existing_matrix()
    reading("既有账号 × 三个身份模型的解析（逐条）", matrix)
    profiles = existing_profiles()
    reading("既有档案的 owner 集合", profiles)
    data["existing_matrix"] = matrix
    data["existing_profiles"] = profiles
    multi = {k: v for k, v in matrix.items() if len(v) > 1}
    check("Z1", "既有账号里没有「一个账号挂多份档案」的历史状态（新守卫不与既有数据打架）",
          not multi, json.dumps(multi, ensure_ascii=False))
    gm = probe_guard_matrix()
    reading("新守卫过既有数据（改前该函数不存在）", gm)
    data["guard_matrix"] = gm
    mono = probe_monotonicity()
    reading("改前实现（oracle）× 改后实现 逐条对拍（全库账号 × 全库档案）", mono)
    data["monotonicity"] = mono
    if not before:
        check("Z5", "[after] 只加不减：旧实现判「已占用」的一条都没丢"
                    "（多出来的条数 = 本次修复的净收益）",
              mono and not mono.get("lost") and not mono.get("code_lost"),
              json.dumps(mono, ensure_ascii=False)[:1200])
    if not before:
        rows = (gm or {}).get("rows") or []
        bad = [r for r in rows if r[3]]
        check("Z2", "[after] 新守卫对**既有**绑定逐条放行（不误伤历史数据）",
              gm is not None and not (gm or {}).get("error") and not bad,
              "rows=%d bad=%s" % (len(rows), json.dumps(bad, ensure_ascii=False)))
    # 改前/改后对拍：既有解析结果一字不变
    doc = load_results()
    prev_codes = (doc["phases"].get("before") or {}).get("code_verdicts")
    if prev_codes and not before:
        lost_codes = [k for k, v in prev_codes.items()
                      if v.get("verdict")
                      and not (codes.get(k) or {}).get("verdict")]
        check("Z4", "只加不减（码侧）：改前判「已占用」的每一张码，改后仍判「已占用」",
              not lost_codes, json.dumps(lost_codes, ensure_ascii=False))
    prev = None
    for phase_tag in ("before", "verify"):
        p = doc["phases"].get(phase_tag) or {}
        if p.get("existing_matrix"):
            prev = p["existing_matrix"]
    if prev is not None:
        diff = {k: [prev.get(k), matrix.get(k)] for k in set(prev) | set(matrix)
                if prev.get(k) != matrix.get(k)}
        check("Z3", "既有账号的解析结果与上一相位逐条一致（只加不减，changed=[]）",
              not diff, json.dumps(diff, ensure_ascii=False)[:1500])
    else:
        reading("（无上一相位可比：本相位作为基线存档）",
                "existing_matrix 已存档，供下一相位逐条对拍")
    data["pristine_end"] = st2

    save_phase(tag, data, CHECKS)
    return data


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["setup", "measure", "teardown",
                                       "status"])
    ap.add_argument("--tag", default="before")
    args = ap.parse_args()

    if args.action == "setup":
        do_setup()
        print(CHECK_SUMMARY())
    elif args.action == "measure":
        measure(args.tag)
        print(CHECK_SUMMARY())
    elif args.action == "teardown":
        doc = load_results()
        st = ((doc["phases"].get("setup") or {}).get("fixture")) or {}
        do_teardown(st)
        print(CHECK_SUMMARY())
    else:
        doc = load_results()
        print(json.dumps({k: len(v) for k, v in doc["phases"].items()},
                         ensure_ascii=False))
        print(CHECK_SUMMARY())


def CHECK_SUMMARY():
    ok = sum(1 for c in CHECKS if c["pass"])
    lines = ["---- 本相位：%d/%d PASS ----" % (ok, len(CHECKS))]
    for c in CHECKS:
        lines.append("[%s] #%s %s | %s" % ("PASS" if c["pass"] else "FAIL",
                                           c["no"], c["name"], c["detail"][:300]))
    return NL.join(lines)


if __name__ == "__main__":
    sys.exit(main())

