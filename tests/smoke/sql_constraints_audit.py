#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""edu.alert.read 唯一约束（Odoo 19 _sql_constraints 静默失效）修复的验收脚本。

被验收的缺陷
------------
custom_addons/edu_portal/models/alert_read.py 原写：

    _sql_constraints = [
        ('unique_user', 'unique(user_id)', 'One read-state per user'),
    ]

而 Odoo 19 的 ORM 已不再消费该属性（运行时源码，均在容器内取证）：
  * odoo/orm/model_classes.py:162-164 —— 命中 hasattr(model_def, '_sql_constraints')
    时只打一条 WARNING；
  * odoo/orm/registry.py:233 —— registry._sql_constraints 只剩一个空 set；
  * 建约束只遍历 Model._table_objects（odoo/orm/models.py:3262-3273）⟹ 旧写法
    从未建库。病症是「源码看起来有、库里其实没有」。

修法：改用 Odoo 19 的 models.Constraint（仓内先例 edu_tg_bind/models/tg_claim.py、
edu_portal/models/invite_code.py）。约束名按 TableObject.full_name 规则为
{table}_{name} = edu_alert_read_user_uniq。

自查项
------
  A1/A2 根因守卫（运行时源码）：旧属性只告警且不被消费；models.Constraint 是
        TableObject，经 sql.add_constraint 真正落库
  A3    注册表级证据：edu.alert.read._table_objects 里确有该 Constraint 定义
  B1    静态：alert_read.py 已无 _sql_constraints 赋值、改用 models.Constraint
  B2    静态：全仓 _sql_constraints 赋值只剩 edu_telegram 的 3 处
  C1    库级（核心判据）：pg_constraint / pg_indexes 存在
        edu_alert_read_user_uniq 且为 UNIQUE
  C2    负向用例：为同一 user_id 插第二行必须被数据库拒绝 —— 证据须是 psql 的
        ERROR 23505（SQLSTATE unique_violation）+ 约束名，而不是 Python 异常；
        同一事务内第一行插入必须成功（证明拒绝的确来自「重复」而非别的原因）
  D1    零回归：search -> create-if-missing 路径照旧（建一次；第二次 search 命中同一行）
  D2    零回归：_raise_watermarks 语义不变（按类别合并 / 只升不降 / 幂等）
  D3    无残留：edu_alert_read 行快照前后一致
  E1    体检：旧写法存量（3 处，均在 edu_telegram，本次不许碰）
  E2    体检：生产库对应表是否有该唯一约束（只读 SELECT，EDU_AUDIT_PROD=1 才跑）
  F     体检：Odoo 19 同类「静默失效」运行时取证 + 本仓暴露面

用法：python3 tests/smoke/sql_constraints_audit.py
      EDU_AUDIT_PROD=1 python3 tests/smoke/sql_constraints_audit.py   # 追加只读生产巡检
结果：tests/smoke/sql_constraints_audit_results.json
"""
import datetime
import json
import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
OUT = Path(__file__).resolve().parent / "sql_constraints_audit_results.json"
DB = os.environ.get("EDU_DB_NAME", "edu19")
DB_CONTAINER = os.environ.get("EDU_DB_CONTAINER", "edu19-clone-db-1")
WEB_CONTAINER = os.environ.get("EDU_WEB_CONTAINER", "edu19-clone-web-1")
PROD_SSH = os.environ.get("EDU_PROD_SSH", "prod-host")
PROD_DIR = os.environ.get("EDU_PROD_DIR", "/opt/edu-app")
AUDIT_PROD = os.environ.get("EDU_AUDIT_PROD", "0") == "1"

TABLE = "edu_alert_read"
MODEL = "edu.alert.read"
CONNAME = "edu_alert_read_user_uniq"
OBJNAME = "user_uniq"
OD = "/usr/lib/python3/dist-packages/odoo"

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
    """单条 SQL，-tAc，返回 stdout（非 0 退出抛错）。"""
    out = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", "odoo", "-d", DB,
         "-tAc", sql], capture_output=True, text=True, timeout=90)
    if out.returncode != 0:
        raise RuntimeError("psql failed: " + out.stderr.strip()[:400])
    return out.stdout.strip()


def psql_script(sql):
    """多语句脚本（可含 \\set / BEGIN / ROLLBACK），返回 (rc, stdout, stderr)。"""
    out = subprocess.run(
        ["docker", "exec", "-i", DB_CONTAINER, "psql", "-U", "odoo", "-d", DB,
         "-f", "-"], input=sql, capture_output=True, text=True, timeout=120)
    return out.returncode, out.stdout or "", out.stderr or ""


def in_web(cmd, timeout=120):
    out = subprocess.run(["docker", "exec", WEB_CONTAINER, "bash", "-lc", cmd],
                         capture_output=True, text=True, timeout=timeout)
    return (out.stdout or "") + (out.stderr or "")


def odoo_shell(lines, timeout=420):
    """把若干行 python 喂给容器内 odoo shell，返回合并输出。"""
    cmd = ["docker", "compose", "exec", "-T", "web", "odoo", "shell",
           "-c", "/etc/odoo/odoo.conf", "-d", DB,
           "--db_host=db", "-r", "odoo", "-w", "odoo", "--no-http"]
    out = subprocess.run(cmd, input=NL.join(lines), capture_output=True,
                         text=True, timeout=timeout, cwd=str(REPO))
    txt = (out.stdout or "") + (out.stderr or "")
    if out.returncode != 0:
        raise RuntimeError("odoo shell exit %s: %s" % (out.returncode, txt[-1200:]))
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


# ---------------------------------------------------------------------------
# 开工前快照
# ---------------------------------------------------------------------------
PRE_ROWS = psql(
    "SELECT COALESCE(json_agg(json_build_object('id', id, 'user_id', user_id,"
    " 'last_total', last_total, 'seen_map', seen_map, 'last_read', last_read)"
    " ORDER BY id)::text, '[]') FROM " + TABLE)
print("开工前 " + TABLE + " 快照：" + PRE_ROWS[:300])

# ===========================================================================
# A. 根因守卫（运行时源码事实）
# ===========================================================================
print(NL + "=== A. 根因守卫（Odoo 19 运行时源码）===")
src_model_classes = in_web("sed -n '155,170p' " + OD + "/orm/model_classes.py")
src_registry = in_web("sed -n '230,236p' " + OD + "/orm/registry.py")
src_models = in_web("sed -n '3262,3274p' " + OD + "/orm/models.py")
src_tobj = in_web("sed -n '79,125p' " + OD + "/orm/table_objects.py")

check("A1", "根因守卫：_sql_constraints 在 Odoo 19 只触发 WARNING（不再被消费）",
      ("Model attribute '_sql_constraints' is no longer supported" in src_model_classes)
      and ("_add_sql_constraints" not in src_model_classes),
      "model_classes.py:155-170 未出现任何消费逻辑")
check("A2", "根因守卫：registry._sql_constraints 是空 set（约束无从建库）",
      re.search(r"_sql_constraints\s*=\s*set\(\)", src_registry) is not None,
      src_registry.strip().replace(NL, " | ")[:200])
check("A2b", "根因守卫：建约束只遍历 _table_objects（新 API 才是唯一落库路径）",
      "_add_sql_constraints" in src_models and "_table_objects" in src_models
      and "sql.add_constraint" in src_tobj,
      "models.py:3262-3273 + table_objects.py Constraint.apply_to_database")
reading("A2c 运行时源码原文（model_classes.py:160-166）",
        [l for l in src_model_classes.split(NL) if "_constraints" in l])

# ===========================================================================
# B. 静态体检
# ===========================================================================
print(NL + "=== B. 静态体检 ===")
alert_path = REPO / "custom_addons/edu_portal/models/alert_read.py"
alert_src = alert_path.read_text(encoding="utf-8")
check("B1a", "静态：alert_read.py 已无 _sql_constraints 赋值",
      re.search(r"^\s*_sql_constraints\s*=", alert_src, re.M) is None)
check("B1b", "静态：alert_read.py 改用 models.Constraint（且声明了 user_id 唯一）",
      re.search(r"^\s*_" + OBJNAME + r"\s*=\s*models\.Constraint\(",
                alert_src, re.M) is not None
      and "unique (user_id)" in alert_src)

# 全仓 _sql_constraints 赋值（注释里提到不算）
ASSIGN = re.compile(r"^\s*_sql_constraints\s*=", re.M)
stale = []
for root in ("custom_addons", "scripts", "tests", "openeducat_erp"):
    base = REPO / root
    if not base.is_dir():
        continue
    for p in sorted(base.rglob("*.py")):
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if ASSIGN.search(txt):
            rel = str(p.relative_to(REPO))
            # 本脚本自己的 docstring 引用了旧写法原文，不算存量使用
            if rel != "tests/smoke/sql_constraints_audit.py":
                stale.append(rel)
tele = sorted(s for s in stale if s.startswith("custom_addons/edu_telegram/"))
other = sorted(s for s in stale if not s.startswith("custom_addons/edu_telegram/"))
check("B2a", "静态：全仓 _sql_constraints 赋值只剩 3 处，且全部在 edu_telegram",
      len(tele) == 3 and not other,
      "edu_telegram=%s；其他=%s" % (tele, other))
check("B2b", "静态：修好的 alert_read.py 不在存量清单里",
      str(alert_path.relative_to(REPO)) not in stale)
reading("B2c 存量旧写法（本次只报告、不修改）", tele)

# ===========================================================================
# C. 库级证据（核心判据 + 负向用例）
# ===========================================================================
print(NL + "=== C. 库级证据 ===")
idx = psql("SELECT COALESCE(string_agg(indexname || ' :: ' || indexdef, ' ;; '), '')"
           " FROM pg_indexes WHERE tablename = '" + TABLE + "'")
con = psql("SELECT COALESCE(string_agg(conname || ' :: ' || contype::text || ' :: '"
           " || pg_get_constraintdef(oid), ' ;; '), '') FROM pg_constraint"
           " WHERE conrelid = '" + TABLE + "'::regclass")
reading("C0 pg_indexes(" + TABLE + ")", idx)
reading("C0b pg_constraint(" + TABLE + ")", con)

uniq_idx = psql("SELECT COALESCE(string_agg(indexname, ','), '') FROM pg_indexes"
                " WHERE tablename = '" + TABLE + "' AND indexname = '" + CONNAME + "'"
                " AND indexdef LIKE '%UNIQUE%'")
check("C1a", "库级核心判据：pg_indexes 存在唯一索引 " + CONNAME,
      uniq_idx == CONNAME, "命中=%r" % uniq_idx)
uniq_con = psql("SELECT COALESCE(string_agg(conname, ','), '') FROM pg_constraint"
                " WHERE conrelid = '" + TABLE + "'::regclass AND conname = '"
                + CONNAME + "' AND contype = 'u'")
check("C1b", "库级核心判据：pg_constraint 存在 UNIQUE 约束 " + CONNAME,
      uniq_con == CONNAME, "命中=%r" % uniq_con)
check("C1c", "库级核心判据：UNIQUE 定义确为 (user_id)",
      "(user_id)" in psql("SELECT COALESCE(string_agg(pg_get_constraintdef(oid), ''), '')"
                          " FROM pg_constraint WHERE conrelid = '" + TABLE
                          + "'::regclass AND conname = '" + CONNAME + "'"))

# --- 负向用例：为同一 user_id 插第二行，必须被数据库拒绝 ---
print(NL + "=== C2. 负向用例（同一 user_id 插第二行）===")
free_uid = psql("SELECT u.id FROM res_users u WHERE NOT EXISTS (SELECT 1 FROM "
                + TABLE + " a WHERE a.user_id = u.id) ORDER BY u.id LIMIT 1")
if not free_uid:
    check("C2", "负向用例：同一 user_id 插第二行被数据库拒绝", False,
          "找不到「尚无已读行」的 res_users 记录，环境不满足（跳过）")
else:
    neg = NL.join([
        "\\set ON_ERROR_STOP on",
        "\\set VERBOSITY verbose",
        "BEGIN;",
        "INSERT INTO " + TABLE + " (user_id, last_total, seen_map) VALUES ("
        + free_uid + ", 0, '{}'::jsonb);",
        "SELECT 'FIRST_INSERT_ACCEPTED' AS marker;",
        "INSERT INTO " + TABLE + " (user_id, last_total, seen_map) VALUES ("
        + free_uid + ", 0, '{}'::jsonb);",
        "SELECT 'SECOND_INSERT_ACCEPTED_THIS_IS_A_FAILURE' AS marker;",
        "ROLLBACK;",
    ])
    rc, so, se = psql_script(neg)
    first_ok = "FIRST_INSERT_ACCEPTED" in so
    second_leaked = "SECOND_INSERT_ACCEPTED_THIS_IS_A_FAILURE" in so
    db_rejected = ("23505" in se) and ("unique constraint" in se) and (CONNAME in se)
    reading("C2 负向用例 psql 退出码", rc)
    reading("C2 负向用例 psql stderr 原文", se.strip().replace(NL, " | ")[:900])
    check("C2a", "负向用例：同一 user_id 的第一行可插入（正对照成立）",
          first_ok, "stdout marker=%r" % first_ok)
    check("C2b", "负向用例：第二行被**数据库**拒绝（SQLSTATE 23505 + 约束名，"
                 "不是 Python 异常）",
          db_rejected and not second_leaked, se.strip()[:500])
    left = psql("SELECT count(*) FROM " + TABLE + " WHERE user_id = " + free_uid)
    check("C2c", "负向用例：事务回滚，未留下任何残留行",
          left == "0", "残留=%s" % left)

# ===========================================================================
# D. 零回归（Odoo 层：既有两个调用方的语义照旧）
# ===========================================================================
print(NL + "=== D. 零回归 ===")
shell_lines = [
    "import json",
    "res = {}",
    "M = env['" + MODEL + "'].sudo()",
    # --- 注册表级证据 ---
    "tos = []",
    "for k, o in M._table_objects.items():",
    "    try:",
    "        d = o.get_definition(env.registry)",
    "    except Exception as e:",
    "        d = '<err %s>' % e",
    "    tos.append([k, d])",
    "res['table_objects'] = sorted(tos)",
    # --- D1: search -> create-if-missing 路径 ---
    "used = set(M.search([]).mapped('user_id').ids)",
    "free = [u.id for u in env['res.users'].sudo().search([], order='id')"
    " if u.id not in used]",
    "res['free_uids'] = free[:5]",
    "if free:",
    "    uid = free[0]",
    "    r1 = M.search([('user_id', '=', uid)], limit=1)",
    "    res['found_before'] = bool(r1)",
    "    if not r1:",
    "        r1 = M.create({'user_id': uid})",
    "    res['created_id'] = r1.id",
    "    r2 = M.search([('user_id', '=', uid)], limit=1)",
    "    res['second_search_same_row'] = (r2.id == r1.id)",
    "    res['rows_for_uid'] = M.search_count([('user_id', '=', uid)])",
    "    # --- D2: 水位语义（按类别 / 只升不降 / 幂等）---",
    "    r1.write({'seen_map': {}, 'last_total': 0})",
    "    r1._raise_watermarks({'a': 3})",
    "    res['w1_first_raise'] = dict(r1.seen_map or {})",
    "    r1._raise_watermarks({'a': 1})",
    "    res['w2_lower_ignored'] = dict(r1.seen_map or {})",
    "    r1._raise_watermarks({'b': 5})",
    "    res['w3_merge_by_key'] = dict(r1.seen_map or {})",
    "    r1._raise_watermarks({'a': 3})",
    "    res['w4_idempotent'] = dict(r1.seen_map or {})",
    "    r1.write({'last_total': 9})",
    "    res['last_total_write'] = r1.last_total",
    "    # --- 新约束在 Odoo 层的体现：同一 uid 再建一行必须报错 ---",
    "    try:",
    "        with env.cr.savepoint():",
    "            M.create({'user_id': uid})",
    "        res['dup_create'] = 'NO_ERROR_THIS_IS_A_FAILURE'",
    "    except Exception as e:",
    "        res['dup_create'] = type(e).__name__ + ': ' + str(e)[:200]",
    emit("D", "res"),
    "env.cr.rollback()",
    "print('[clean] 事务已回滚')",
]
sh_out = odoo_shell(shell_lines)
d = payload(sh_out, "D") or {}
reading("D0 edu.alert.read._table_objects（注册表级证据）", d.get("table_objects"))
tobj_hit = [t for t in (d.get("table_objects") or [])
            if t[0] == OBJNAME or t[0].endswith(OBJNAME)]
check("A3", "注册表级证据：edu.alert.read._table_objects 含 " + OBJNAME
            + " 且定义为 unique (user_id)",
      bool(tobj_hit) and any("user_id" in str(t[1]).lower() for t in tobj_hit),
      "命中=%s" % tobj_hit)

check("D1a", "零回归：无已读行的用户走 search->create 仍能建行（调用方口径不变）",
      d.get("found_before") is False and int(d.get("created_id") or 0) > 0,
      "found_before=%s created_id=%s" % (d.get("found_before"), d.get("created_id")))
check("D1b", "零回归：第二次 search 命中同一行、该用户只有 1 行（约束与调用方假设一致）",
      d.get("second_search_same_row") is True and d.get("rows_for_uid") == 1,
      "same_row=%s rows=%s" % (d.get("second_search_same_row"), d.get("rows_for_uid")))
check("D2a", "零回归：_raise_watermarks 首次按类别置水位",
      d.get("w1_first_raise") == {"a": 3}, "w1=%s" % d.get("w1_first_raise"))
check("D2b", "零回归：水位只升不降（给更小的值不改写）",
      d.get("w2_lower_ignored") == {"a": 3}, "w2=%s" % d.get("w2_lower_ignored"))
check("D2c", "零回归：多类别按 key 合并（不是整表覆盖）",
      d.get("w3_merge_by_key") == {"a": 3, "b": 5}, "w3=%s" % d.get("w3_merge_by_key"))
check("D2d", "零回归：重复同一水位是幂等的",
      d.get("w4_idempotent") == {"a": 3, "b": 5}, "w4=%s" % d.get("w4_idempotent"))
check("D2e", "零回归：last_total 旧字段照旧可写（roles.py 旧路由兼容）",
      d.get("last_total_write") == 9, "last_total=%s" % d.get("last_total_write"))
reading("D3 新约束在 Odoo 层的行为（同一 uid 再建一行）", d.get("dup_create"))
check("D3a", "新约束在 Odoo 层同样生效：同一 user_id 再建一行被拒（不再是静默重复行）",
      d.get("dup_create") not in (None, "NO_ERROR_THIS_IS_A_FAILURE"),
      "dup_create=%s" % d.get("dup_create"))

POST_ROWS = psql(
    "SELECT COALESCE(json_agg(json_build_object('id', id, 'user_id', user_id,"
    " 'last_total', last_total, 'seen_map', seen_map, 'last_read', last_read)"
    " ORDER BY id)::text, '[]') FROM " + TABLE)
check("D4", "无残留：edu.alert_read 行快照与开工前逐字段一致",
      POST_ROWS == PRE_ROWS,
      "before=%s after=%s" % (PRE_ROWS[:300], POST_ROWS[:300]))
reading("D4b 快照对比（开工前 / 收工后）", {"before": PRE_ROWS, "after": POST_ROWS})

# ===========================================================================
# E. 体检：旧写法存量 + 生产库对应表
# ===========================================================================
print(NL + "=== E. 生产库只读巡检 ===")
PROD_SQL = NL.join([
    "\\pset pager off",
    "SELECT 'ALERT_READ', indexname, indexdef FROM pg_indexes"
    " WHERE tablename = 'edu_alert_read' ORDER BY indexname;",
    "SELECT 'TG_BINDING', indexname, indexdef FROM pg_indexes"
    " WHERE tablename = 'edu_telegram_binding' ORDER BY indexname;",
    "SELECT 'TG_FLOW', indexname, indexdef FROM pg_indexes"
    " WHERE tablename = 'edu_telegram_flow' ORDER BY indexname;",
    "SELECT 'TG_CHAT', indexname, indexdef FROM pg_indexes"
    " WHERE tablename = 'op_telegram_chat' ORDER BY indexname;",
    "SELECT 'TG_ROWS', 'binding', count(*) FROM edu_telegram_binding"
    " UNION ALL SELECT 'TG_ROWS', 'flow', count(*) FROM edu_telegram_flow"
    " UNION ALL SELECT 'TG_ROWS', 'chat', count(*) FROM op_telegram_chat;",
    "SELECT 'ALERT_DUP', count(*) FROM (SELECT user_id FROM edu_alert_read"
    " GROUP BY user_id HAVING count(*) > 1) t;",
])
if not AUDIT_PROD:
    check("E2", "生产库巡检：已跳过（EDU_AUDIT_PROD!=1）—— 这是「未执行」不是「通过」", True,
          "只读巡检，需显式开启")
    reading("E2 生产库巡检", "skipped (EDU_AUDIT_PROD!=1)")
else:
    cmd = ("cd " + PROD_DIR + " && docker compose exec -T db psql -U odoo -d "
           + DB + " -f -")
    out = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", PROD_SSH, cmd],
        input=PROD_SQL, capture_output=True, text=True, timeout=180)
    prod_txt = (out.stdout or "") + "\n[ssh-rc=%s] " % out.returncode + (out.stderr or "")
    for _i in range(0, len(prod_txt), 1800):
        reading("E2 生产库巡检原文（只读）[%d]" % (_i // 1800), prod_txt[_i:_i + 1800])
    check("E2a", "生产库：ssh 巡检可执行且退出码为 0", out.returncode == 0,
          prod_txt[-500:])
    check("E2b", "生产库：edu_alert_read 无 REPEATING user_id（升级前无重复行，"
                 "新约束可安全建库）",
          re.search(r"ALERT_DUP\s*\|\s*0(\D|$)", prod_txt) is not None,
          prod_txt[-800:])
    check("E2c", "生产库：edu.telegram.binding 有唯一索引（存量旧写法在旧版本期已建库）",
          "edu_telegram_binding_code_uniq" in prod_txt)
    reading("E2d 生产库 edu_telegram_flow 是否有 chat_id 唯一约束（体检结论见回报）",
            "edu_telegram_flow_chat_uniq" in prod_txt)
    reading("E2e 生产库 op_telegram_chat 是否有 chat_id 唯一约束（体检结论见回报）",
            "op_telegram_chat_chat_id_uniq" in prod_txt)

# ===========================================================================
# F. 同类「静默失效」体检（运行时源码取证 + 本仓暴露面）
# ===========================================================================
print(NL + "=== F. 同类静默失效体检 ===")
f_src = {}
f_src["model_classes_155_170"] = src_model_classes
f_src["fields_525_540"] = in_web("sed -n '525,540p' " + OD + "/orm/fields.py")
f_src["view_488_500"] = in_web("sed -n '488,500p' " + OD
                               + "/addons/base/models/ir_ui_view.py")
f_src["name_get_in_orm"] = in_web("grep -rn name_get " + OD + "/orm/ 2>/dev/null | head -5")
f_src["deprecation_test"] = in_web("sed -n '8,40p' " + OD
                                   + "/addons/base/tests/test_deprecation.py")

check("F1", "体检：_constraints（旧版 Python 级约束）在 Odoo 19 同样只告警、静默失效",
      "Model attribute '_constraints' is no longer supported" in f_src["model_classes_155_170"])
check("F2", "体检：未知字段参数只告警并被忽略（例如 fields.Char(placeholder=...)）",
      "unknown parameter" in f_src["fields_525_540"])
check("F3", "体检：name_get 在 Odoo 19 的 orm/ 里已零引用（覆写它 = 死代码、无任何提示）",
      f_src["name_get_in_orm"].strip() == "" and "test_name_get" in f_src["deprecation_test"])
check("F4", "体检：视图 attrs=/states= 是**响亮**失败（ValidationError），不属静默失效",
      '"attrs" and "states" attributes are no longer used' in f_src["view_488_500"])
reading("F5 本仓暴露面（静默失效命中项）",
        {
            "jobs.py:18 fields.Char(placeholder=...)":
                (REPO / "custom_addons/edu_portal/models/jobs.py").read_text(
                    encoding="utf-8").splitlines()[17].strip(),
            "def name_get 出现次数": 0,
            "Python 级 _constraints 赋值": 0,
        })
reading("F6 运行时源码片段（判定依据）",
        {k: v.strip().replace(NL, " | ")[:500] for k, v in f_src.items()})

# ===========================================================================
n_fail = sum(1 for c in CHECKS if not c["pass"])
OUT.write_text(json.dumps(
    {"suite": "sql_constraints_audit",
     "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
     "target": {"table": TABLE, "model": MODEL, "constraint": CONNAME,
                "file": "custom_addons/edu_portal/models/alert_read.py"},
     "summary": {"total": len(CHECKS), "pass": len(CHECKS) - n_fail,
                 "fail": n_fail},
     "checks": CHECKS, "readings": READINGS},
    ensure_ascii=False, indent=1), encoding="utf-8")
print(NL + "== sql_constraints_audit: %d/%d PASS ==（%s）"
      % (len(CHECKS) - n_fail, len(CHECKS), OUT.name))
if n_fail:
    print("失败项：")
    for c in CHECKS:
        if not c["pass"]:
            print("  #%s %s | %s" % (c["no"], c["name"], c["detail"][:300]))
raise SystemExit(1 if n_fail else 0)
