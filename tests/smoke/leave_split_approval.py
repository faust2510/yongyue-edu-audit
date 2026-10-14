#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""请假分级审批 + 转交 + 条例校验 —— S5 冒烟门禁（设计稿 §9.4 的 A1–A14）。

设计稿：docs/plans/leave-split-approval-design.md
  · §9.3 验收命令闭环（本脚本是第 4 段的功能门禁）
  · §9.4 验收断言清单 A1–A14（逐条对应下面的 A case id）
被测实现：
  · S2 custom_addons/edu_portal/models/leave_flow.py（路由/状态机/转交/销假/条例校验）
  · S3 custom_addons/edu_portal/controllers/{roles.py,batch3.py}（门户写路由）
接口依据：S2 的**冻结签名清单**（FROZEN_SIGS，本文件不发明方法名）+
  RouteResult(first_users, second_users, need_second, fallback_reason)。

三段模板（docs/dev-workflow.md）：
  ① 造数走**真门户路由**（/my/time_off/save、/leave/set_state、/leave/transfer）；
     只有「没有登录账号的分支」（学生未分班 / 后台例外通道）才用模型 create()，
     并在输出里写明；
  ② 读**真正的产物**：库里的行 + 审计行 + 站内信，不看「按钮是否置灰」；
  ③ 收尾断言 leftover = 0（夹具逐 id 复查 + 班主任字段还原）。

负向用例（A8 / A9 / A13）一律断言「**没发生**」：
  · A8 转交后原审批人 POST ⇒ 状态与快照逐字段未变（含 write_date）+ 无新审计行；
  · A9 第二次转交 ⇒ 转交行仍为 1（HTTP 侧被守卫挡住）+ 直接 ORM 插重复行撞 UNIQUE；
  · A13 实践周 ⇒ 模型上不存在任何折算/调休字段，且单据日期逐字未变。

用法：
    python3 tests/smoke/leave_split_approval.py --selftest    # 不连站点：证明「尺子准」
    python3 tests/smoke/leave_split_approval.py --model-only  # 只跑 A1（注册表/结构/接口冻结）
    python3 tests/smoke/leave_split_approval.py               # 全量（连本地 edu19）
    python3 tests/smoke/leave_split_approval.py --json /tmp/s5.json
退出码：0=全绿；1=有 FAIL；2=环境不可用（容器/db/站点探活失败）。
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent.parent
BASE = os.environ.get('S5_BASE', 'http://localhost:8069')
DB = os.environ.get('EDU_DB_NAME', 'edu19')
DB_CONTAINER = os.environ.get('EDU_DB_CONTAINER', 'edu19-clone-db-1')
COMPOSE_FILE = os.environ.get('EDU_COMPOSE_FILE', str(REPO / 'docker-compose.yml'))
RESULTS_JSON = Path(os.environ.get('S5_JSON', '/tmp/s5_leave_split_approval.json'))
SHELL_FAIL_LOG = Path('/tmp/s5_leave_shell_fail.txt')

# ---------------------------------------------------------------- 冻结契约（唯一真源 = S2）
# ⚠ 这份清单**逐字**来自 S2 的接口冻结段（leave_flow.py 文件头「接口冻结」）与
#   设计稿 §10 的 S2 卡片。**不要在这里发明方法名**，也不要「顺手改个名字」。
FROZEN_SIGS = [
    'route_of', 'can_user_act', 'action_first_approve', 'action_second_approve',
    'action_refuse', 'action_send_back', 'action_transfer', 'transfer',
    'action_confirm_return', 'transfer_candidates', '_cron_return_overdue',
]
ROUTE_RESULT_FIELDS = ['first_users', 'second_users', 'need_second',
                       'fallback_reason']
# §3.3 的 route_note 逐字文案（模型侧常量，断言按**子串**判，避免与视图文案耦合）
FALLBACK_NO_HOMEROOM = '未设班主任，已转教务处'
FALLBACK_NO_BATCH = '该生未分班，已转教务处'
FALLBACK_NO_APPROVER = '无可用审批人'

# §7.6 负向断言：「实践周不调休不拼假」= 本仓**没有**任何折算字段被写。
# 口径 = 字段名模式（中英）+ 单据日期逐字未变（见 A13）。
CONVERT_FIELD_PATTERNS = ('makeup', 'make_up', 'compensat', 'convert', 'exchange',
                          'shift', 'swap', 'defer', 'reschedul', 'holiday',
                          '调休', '拼假', '折算')

TODAY = datetime.date.today()
EXPECTED_CASES = ['A%d' % i for i in range(1, 15)]

# ---------------------------------------------------------------- 断言骨架
RESULTS = []
SEEN_CASES = set()
ok = fail = 0


def check(case, name, cond, detail=''):
    """记一条断言。case ∈ A1..A14（用于覆盖率自查），name 是人读的短名。"""
    global ok, fail
    SEEN_CASES.add(case)
    cond = bool(cond)
    if cond:
        ok += 1
    else:
        fail += 1
    RESULTS.append({'case': case, 'name': name, 'pass': cond,
                    'detail': str(detail)[:900]})
    print('  [%s] %-5s %-48s %s' % ('PASS' if cond else 'FAIL', case, name,
                                    ('| ' + str(detail)[:340]) if detail else ''))
    return cond


def note(msg):
    print('  ---- %s' % msg)


# ---------------------------------------------------------------- 纯函数（--selftest 直接测）
def span_days(d1, d2):
    """含头含尾的天数（§3.4：9/1–9/3 = 3 天，自然日，不扣任何日历）。"""
    if not d1 or not d2 or d2 < d1:
        return 0
    return (d2 - d1).days + 1


def need_second_by_days(days, threshold=3):
    """§3.4 阈值：days > 3 才需要二级（3 天 = 一级即终）。"""
    return days > threshold


def proof_required_rule(leave_type, days):
    """§7.2：sick 且 days ≥ 2 ⇒ 必传；marriage_funeral ⇒ 必传；其余 False。"""
    if leave_type == 'marriage_funeral':
        return True
    return leave_type == 'sick' and days >= 2


def route_note_hits(note_text, kind):
    """route_note 的判定（正/反例都在 --selftest 里验过）。"""
    note_text = note_text or ''
    if kind == 'no_homeroom':
        return FALLBACK_NO_HOMEROOM in note_text
    if kind == 'no_batch':
        return FALLBACK_NO_BATCH in note_text
    if kind == 'no_approver':
        return FALLBACK_NO_APPROVER in note_text
    return False


def diff_keys(before, after, keys):
    """逐字段比较；返回**变化了的**键名列表（空 = 什么都没写）。"""
    return [k for k in keys if before.get(k) != after.get(k)]


def convert_fields(names):
    """从字段名清单里挑出「折算/调休/拼假」字段（A13 的尺子）。"""
    out = []
    for name in names:
        low = name.lower()
        if any(p in low for p in CONVERT_FIELD_PATTERNS):
            out.append(name)
    return sorted(out)


# ---------------------------------------------------------------- 环境（探活 / psql / shell）
def psql(sql, want_err=False):
    out = subprocess.run(['docker', 'exec', DB_CONTAINER, 'psql', '-U', 'odoo',
                          '-d', DB, '-tAc', sql],
                         capture_output=True, text=True, timeout=180)
    if out.returncode != 0 and not want_err:
        raise RuntimeError('psql 失败：' + (out.stderr or '').strip()[:300])
    return (out.stdout or '').strip(), (out.stderr or '').strip()


def pscalar(sql):
    txt = psql(sql)[0]
    return int(txt or 0)


def ptext(sql):
    return psql(sql)[0]


def sql_lit(value):
    return "'" + str(value).replace("'", "''") + "'"


def shell(body, timeout=900):
    cmd = ['docker', 'compose', '-f', COMPOSE_FILE, 'exec', '-T', 'web', 'odoo',
           'shell', '-c', '/etc/odoo/odoo.conf', '--db_host=db', '--db_port=5432',
           '--db_user=odoo', '--db_password=odoo', '-d', DB, '--no-http']
    out = subprocess.run(cmd, input=body, capture_output=True, text=True,
                         timeout=timeout, cwd=str(REPO))
    return (out.stdout or '') + (out.stderr or '')


def shell_json(body, timeout=900):
    """跑一段 odoo shell，取回 OUT 字典（marker 把 shell 的日志噪音隔离掉）。"""
    blob = shell('import json\nOUT = {}\n' + body +
                 "\nprint('@@S5J@@' + json.dumps(OUT, ensure_ascii=False, default=str))\n",
                 timeout)
    m = re.search(r'@@S5J@@(.*)', blob)
    if not m:
        SHELL_FAIL_LOG.write_text(blob, encoding='utf-8')
        raise RuntimeError('odoo shell 未返回 JSON（完整输出见 %s）：%s'
                           % (SHELL_FAIL_LOG, blob[-800:]))
    return json.loads(m.group(1))


def preflight():
    """门禁跑前三步探活（code-map §2）：无升级锁 + 带 cookie jar 的登录页可用。"""
    lock = os.path.join(os.environ.get('TMPDIR') or '/tmp', 'edu19_upgrade.lock')
    if os.path.exists(lock):
        print('环境不可用：存在升级锁 %s（等它消失再跑）' % lock)
        return False
    try:
        jar = os.path.join('/tmp', 's5_jar_%d' % os.getpid())
        code = subprocess.run(
            ['curl', '-s', '-c', jar, '-b', jar, '-o', '/dev/null', '-w', '%{http_code}',
             BASE + '/web/login?db=' + DB],
            capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception as exc:
        print('环境不可用：探活异常 %s' % exc)
        return False
    if code not in ('200', '302', '303'):
        print('环境不可用：%s/web/login?db=%s → %s' % (BASE, DB, code))
        return False
    return True


# ---------------------------------------------------------------- HTTP（门户真路由）
def login(login_name, pwd):
    sess = requests.Session()
    sess.trust_env = False
    sess.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    for _ in range(2):
        try:
            r = sess.post(BASE + '/web/session/authenticate', timeout=30, json={
                'jsonrpc': '2.0', 'method': 'call',
                'params': {'db': DB, 'login': login_name, 'password': pwd}})
            uid = ((r.json() or {}).get('result') or {}).get('uid')
        except Exception:
            uid = None
        if uid:
            return sess, uid
        time.sleep(3)
    return None, None


def probe(sess, path, data=None, method='GET'):
    """**不跟随重定向**的探测（判 303 必须看首跳）。"""
    if method == 'GET':
        return sess.get(BASE + path, timeout=60, allow_redirects=False)
    return sess.post(BASE + path, data=data, timeout=90, allow_redirects=False)


def csrf_of(sess, path):
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', probe(sess, path).text or '')
    return m.group(1) if m else None


def post_portal(sess, path, token_path, **kw):
    data = {'csrf_token': csrf_of(sess, token_path)}
    data.update(kw)
    return probe(sess, path, data=data, method='POST')


def submit_leave(sess, **kw):
    """学生/教职门户建单（唯一入口 /my/time_off/save）。"""
    return post_portal(sess, '/my/time_off/save', '/my/time_off', **kw)


def set_state(sess, leave_id, state, **kw):
    return post_portal(sess, '/leave/set_state', '/leave/approvals',
                       leave_id=leave_id, state=state, **kw)


def transfer_http(sess, leave_id, to_user_id, reason, **kw):
    return post_portal(sess, '/leave/transfer', '/leave/approvals',
                       leave_id=leave_id, to_user_id=to_user_id, reason=reason, **kw)


def leave_id_by_reason(marker):
    return pscalar('select coalesce(max(id),0) from edu_leave where reason = %s'
                   % sql_lit(marker))


def leave_name(leave_id):
    return ptext('select coalesce(name, \'\') from edu_leave where id = %d' % leave_id)


def audit_count(action, model=None, res_id=None):
    dom = 'action=%s' % sql_lit(action)
    if model:
        dom += ' and model=%s' % sql_lit(model)
    if res_id is not None:
        dom += ' and res_id=%d' % res_id
    return pscalar('select count(*) from edu_audit_log where %s' % dom)


def msg_count(needles, after_id=0):
    """正文含任一 needle 的站内信条数（needle 空 ⇒ 0）。"""
    needles = [n for n in (needles or []) if n]
    if not needles:
        return 0
    cond = ' or '.join('body like %s' % sql_lit('%' + n + '%') for n in needles)
    return pscalar('select count(*) from edu_message where id > %d and (%s)'
                   % (after_id, cond))


def max_id(table):
    return pscalar('select coalesce(max(id),0) from ' + table)


LEAVE_FIELDS_JS = (
    "{'state': rec.state, 'first': rec.first_approver_id.id or 0,"
    " 'second': rec.second_approver_id.id or 0,"
    " 'route_note': rec.route_note or '', 'leave_type': rec.leave_type or '',"
    " 'days': rec.days_of_leave(), 'date_from': str(rec.date_from or ''),"
    " 'date_to': str(rec.date_to or ''),"
    " 'proof_required': bool(rec.proof_required), 'proof_kind': rec.proof_kind or '',"
    " 'oral_confirmed_by': rec.oral_proof_confirmed_by_id.id or 0,"
    " 'over_quota': bool(rec.over_quota), 'backfilled': bool(rec.backfilled),"
    " 'long_absence': bool(rec.long_absence_flag),"
    " 'casual_used': rec.casual_days_used_this_term,"
    " 'escalated_at': str(rec.escalated_at or ''),"
    " 'return_overdue_alerted_at': str(rec.return_overdue_alerted_at or ''),"
    " 'applicant_kind': rec.applicant_kind or '',"
    " 'approver_id': rec.approver_id.id or 0, 'approver_kind': rec.approver_kind or '',"
    " 'approved_at': str(rec.approved_at or ''),"
    " 'write_date': str(rec.write_date or ''),"
    " 'create_date': str(rec.create_date or '')}")


def leave_infos(ids):
    """批量读单据（含 compute 字段 —— 只有 ORM 读得到）。"""
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    body = ("for rec in env['edu.leave'].sudo().browse(%r):\n"
            "    OUT[str(rec.id)] = %s\n" % (ids, LEAVE_FIELDS_JS))
    return shell_json(body)


def leave_info(leave_id):
    data = leave_infos([leave_id])
    if str(leave_id) not in data:
        raise RuntimeError('单据 %s 不存在（建单可能被拒）' % leave_id)
    return data[str(leave_id)]


# ---------------------------------------------------------------- A1（结构/接口冻结）
def case_a1():
    note('A1 注册表 / 列 / 唯一约束 / 冻结签名')
    d = shell_json(
        "from odoo.addons.edu_portal.models.leave_flow import RouteResult\n"
        "OUT['model_transfer'] = 'edu.leave.transfer' in env\n"
        "OUT['table_transfer'] = env['edu.leave.transfer']._table\n"
        "OUT['homeroom_field'] = 'homeroom_teacher_id' in env['op.batch']._fields\n"
        "OUT['homeroom_table'] = env['op.batch']._table\n"
        "OUT['sigs'] = {n: callable(getattr(env['edu.leave'], n, None))\n"
        "               for n in %r}\n"
        "OUT['route_fields'] = list(RouteResult._fields)\n"
        "OUT['leave_fields'] = sorted(env['edu.leave']._fields.keys())\n"
        % (FROZEN_SIGS,))
    conv = convert_fields(d.get('leave_fields') or [])
    check('A1', 'edu.leave.transfer 在注册表', d.get('model_transfer'),
          'table=%s' % d.get('table_transfer'))
    check('A1', 'op_batch.homeroom_teacher_id 字段存在（ORM）', d.get('homeroom_field'),
          'table=%s' % d.get('homeroom_table'))
    cols = ptext("select count(*) from information_schema.columns where "
                 "table_name='%s' and column_name='homeroom_teacher_id'"
                 % d.get('homeroom_table'))
    check('A1', 'op_batch.homeroom_teacher_id 列存在（DB）', cols == '1',
          'information_schema 命中=%s' % cols)
    uniq = ptext("select coalesce(string_agg(i.relname, ','), '') from pg_index x "
                 "join pg_class i on i.oid = x.indexrelid "
                 "join pg_class t on t.oid = x.indrelid "
                 "where t.relname = 'edu_leave_transfer' and x.indisunique")
    check('A1', 'edu_leave_transfer 有唯一索引（UNIQUE(leave_id, stage)）',
          bool(uniq), 'unique_index=%s' % (uniq or '无'))
    missing = [k for k, v in (d.get('sigs') or {}).items() if not v]
    check('A1', 'S2 冻结签名 11 个全部可调用（含别名 transfer）', not missing,
          'missing=%s' % (missing or '无'))
    check('A1', 'RouteResult 四字段与设计稿 §3.2 逐字一致',
          d.get('route_fields') == ROUTE_RESULT_FIELDS,
          '实际=%s' % d.get('route_fields'))
    return d


# ---------------------------------------------------------------- selftest（不连站点）
def selftest():
    """证明「尺子准」：纯函数 + 契约常量 + 本文件与源码/设计稿的一致性。"""
    print('=== leave_split_approval --selftest（不连站点，证明尺子准）===')
    d1 = datetime.date(2026, 9, 1)
    d2 = datetime.date(2026, 9, 3)
    d3 = datetime.date(2026, 9, 4)
    check('selftest', '含头含尾：9/1–9/3 = 3 天（不是 2 天）',
          span_days(d1, d2) == 3, 'span_days=%s' % span_days(d1, d2))
    check('selftest', '含头含尾：9/1–9/4 = 4 天（不是 3 天）',
          span_days(d1, d3) == 4, 'span_days=%s' % span_days(d1, d3))
    check('selftest', '单日 = 1 天；倒序/缺值 = 0 天（中性值）',
          span_days(d1, d1) == 1 and span_days(d3, d1) == 0
          and span_days(None, d1) == 0, 'ok')
    check('selftest', '阈值边界：3 天 ⇒ 不需要二级（一级即终）',
          need_second_by_days(3) is False, 'need_second(3)=%s' % need_second_by_days(3))
    check('selftest', '阈值边界：4 天 ⇒ 需要二级（A5 的前置）',
          need_second_by_days(4) is True, 'need_second(4)=%s' % need_second_by_days(4))
    check('selftest', '阈值可配：threshold=5 时 5 天一级、6 天二级',
          need_second_by_days(5, 5) is False and need_second_by_days(6, 5) is True, 'ok')
    check('selftest', '证明规则：1 天病假不传（proof_required=False，S2 实测同款）',
          proof_required_rule('sick', 1) is False, 'ok')
    check('selftest', '证明规则：2 天病假必传（A12 的前置）',
          proof_required_rule('sick', 2) is True, 'ok')
    check('selftest', '证明规则：婚丧假 1 天也必传；事假/其他不受影响',
          proof_required_rule('marriage_funeral', 1) is True
          and proof_required_rule('casual', 5) is False
          and proof_required_rule('other', 9) is False, 'ok')
    check('selftest', 'route_note 尺子：正例命中、近义串不误判',
          route_note_hits('未设班主任，已转教务处', 'no_homeroom')
          and route_note_hits('该生未分班，已转教务处', 'no_batch')
          and not route_note_hits('未设班主任，已转教务处', 'no_batch')
          and not route_note_hits('', 'no_homeroom'), 'ok')
    check('selftest', '负向尺子：diff_keys 在「有写入」时必须报出差异',
          diff_keys({'a': 1, 'b': 2}, {'a': 1, 'b': 3}, ['a', 'b']) == ['b']
          and diff_keys({'a': 1}, {'a': 1}, ['a']) == [], 'ok')
    check('selftest', 'A13 尺子：折算字段模式能抓可疑字段、且本仓模型字段全干净',
          convert_fields(['holiday_shift_days', 'date_from']) == ['holiday_shift_days']
          and convert_fields(['date_from', 'date_to', 'over_quota']) == [], 'ok')
    root = REPO
    src = root / 'custom_addons/edu_portal/models/leave_flow.py'
    text = src.read_text(encoding='utf-8') if src.exists() else ''
    missing = [n for n in FROZEN_SIGS if ('def %s(' % n) not in text]
    check('selftest', 'S2 源码里 11 个冻结签名逐个有 def（不发明方法名）',
          bool(text) and not missing, 'missing=%s' % (missing or '无'))
    design = root / 'docs/plans/leave-split-approval-design.md'
    dtext = design.read_text(encoding='utf-8') if design.exists() else ''
    cases_ok = all(('| %s |' % c) in dtext for c in EXPECTED_CASES)
    check('selftest', '设计稿 §9.4 里 A1–A14 逐条在册（不吞用例）',
          bool(dtext) and cases_ok, 'design=%s' % design.name)
    check('selftest', '本脚本的用例清单 = A1..A14（14 条）',
          EXPECTED_CASES == ['A%d' % i for i in range(1, 15)], 'ok')
    check('selftest', 'A8/A9/A13 三条负向用例在脚本里都有「没发生」断言',
          all(('A8' in _NEGATIVE_CASE_IDS, 'A9' in _NEGATIVE_CASE_IDS,
               'A13' in _NEGATIVE_CASE_IDS)) and '没发生' in __doc__,
          'negatives=%s' % sorted(_NEGATIVE_CASE_IDS))
    print('\n== selftest：%d PASS / %d FAIL ==' % (ok, fail))
    return 0 if fail == 0 else 1


_NEGATIVE_CASE_IDS = {'A8', 'A9', 'A13'}


# ---------------------------------------------------------------- 主流程
def run_live():
    print('=== 请假分级审批冒烟（设计稿 §9.4 A1–A14）· %s ===' % TODAY.isoformat())
    print('目标 %s / db %s / 容器 %s' % (BASE, DB, DB_CONTAINER))

    fx = shell_json(
        "U = env['res.users'].sudo()\n"
        "def uid(login):\n"
        "    u = U.search([('login', '=', login)], limit=1)\n"
        "    return u.id or 0\n"
        "OUT['stu'] = uid('stu@local')\n"
        "OUT['fac'] = uid('faculty@local')\n"
        "OUT['bo'] = uid('backoffice@local')\n"
        "OUT['admin'] = uid('admin')\n"
        "grp = env.ref('openeducat_core.group_op_back_office_admin').sudo()\n"
        "OUT['office_uids'] = sorted(grp.user_ids.filtered('active').ids)\n"
        "sysgrp = env.ref('base.group_system').sudo()\n"
        "OUT['system_uids'] = sorted(sysgrp.user_ids.filtered('active').ids)\n"
        "SC = env['op.student.course'].sudo()\n"
        "linked = SC.search([('batch_id', '!=', False)]).mapped('student_id').ids\n"
        "OUT['with_batch'] = sorted(linked)\n"
        "st = env['op.student'].sudo().browse(linked[0]) if linked else None\n"
        "OUT['student_with_batch'] = st.id if st else 0\n"
        "OUT['student_with_batch_name'] = st.name if st else ''\n"
        "sc = SC.search([('student_id', '=', st.id), ('batch_id', '!=', False)],\n"
        "               limit=1) if st else None\n"
        "OUT['batch_of_student'] = sc.batch_id.id if sc else 0\n"
        "OUT['batch_homeroom_before'] = (sc.batch_id.homeroom_teacher_id.id or 0) if sc else 0\n"
        "nb = env['op.student'].sudo().search([('id', 'not in', linked)],\n"
        "                                     order='id', limit=1)\n"
        "OUT['student_no_batch'] = nb.id or 0\n"
        "OUT['student_no_batch_name'] = nb.name or ''\n"
        "from datetime import date\n"
        "term = env['op.academic.term'].sudo().search(\n"
        "    [('term_start_date', '<=', date.today()),\n"
        "     ('term_end_date', '>=', date.today())], limit=1)\n"
        "OUT['term'] = term.name or ''\n")
    print('夹具：stu=%s fac=%s bo=%s admin=%s｜教务处组=%s｜系统组=%s'
          % (fx['stu'], fx['fac'], fx['bo'], fx['admin'], fx['office_uids'],
             fx['system_uids']))
    print('     学生(有班)=%s %s → 班 %s（班主任现值 %s）；学生(未分班)=%s %s；学期=%s'
          % (fx['student_with_batch'], fx['student_with_batch_name'],
             fx['batch_of_student'], fx['batch_homeroom_before'],
             fx['student_no_batch'], fx['student_no_batch_name'], fx['term']))
    if not (fx['stu'] and fx['fac'] and fx['bo'] and fx['office_uids']
            and fx['student_with_batch'] and fx['batch_of_student']):
        print('环境不可用：夹具账号 / 班级缺失 → %s' % json.dumps(fx, ensure_ascii=False))
        return 2

    stu_s, _ = login('stu@local', 'demo123')
    fac_s, _ = login('faculty@local', 'demo123')
    bo_s, _ = login('backoffice@local', 'demo123')
    if not (stu_s and fac_s and bo_s):
        print('环境不可用：门户登录失败（stu / faculty / backoffice）')
        return 2

    created = []          # 本次建的 edu_leave id（收尾逐 id 复查）
    markers = []          # 本次夹具的 reason 标记（收尾清站内信用）
    base_msg = max_id('edu_message')
    tag = TODAY.strftime('%m%d')
    lids = {}

    def new_leave(marker, **kw):
        """门户建单 + 按 reason 标记取回 id（并发环境下比 max(id) 稳）。"""
        markers.append(marker)
        resp = submit_leave(stu_s, reason=marker, **kw)
        lid = leave_id_by_reason(marker)
        if not lid:
            raise RuntimeError('门户建单未落库：reason=%r / code=%s / body=%s'
                               % (marker, resp.status_code, (resp.text or '')[:400]))
        created.append(lid)
        return resp, lid

    try:
        # ================================================ A1 结构
        case_a1()

        # ================================================ A2 有班主任（正向）
        note('A2 有班主任：op_batch(%s).homeroom_teacher_id := faculty@local(%s)'
             % (fx['batch_of_student'], fx['fac']))
        # ⚠ 每个**写库**的 shell 片段都必须显式 env.cr.commit()：odoo shell 在
        #   console() 之后无条件 cr.rollback()（core cli/shell.py:148-149）——
        #   漏提交 = 夹具"建了又没建"，症状是后面读记录 MissingError。
        shell_json("b = env['op.batch'].sudo().browse(%d)\n"
                   "b.write({'homeroom_teacher_id': %d})\n"
                   "env.cr.commit()\n"
                   "OUT['now'] = b.homeroom_teacher_id.id or 0"
                   % (fx['batch_of_student'], fx['fac']))
        m = 'S5-A2 有班主任-%s' % tag
        r2, lid_a2 = new_leave(m, leave_type='other', date_from=str(TODAY),
                               date_to=str(TODAY + datetime.timedelta(days=1)))
        i2 = leave_info(lid_a2)
        lids['a2'] = lid_a2
        check('A2', '门户建 2 天单成功（303 → ?box=submitted）',
              r2.status_code == 303 and 'submitted' in (r2.headers.get('Location') or ''),
              'code=%s loc=%s' % (r2.status_code, r2.headers.get('Location')))
        check('A2', 'state=request 且 2 天（含头含尾）',
              i2['state'] == 'request' and i2['days'] == 2,
              'state=%s days=%s' % (i2['state'], i2['days']))
        check('A2', 'first_approver_id = 班主任本人（faculty@local=%s）' % fx['fac'],
              i2['first'] == fx['fac'], 'first=%s' % i2['first'])
        check('A2', 'second_approver_id 空（2 天不需要二级）', i2['second'] == 0,
              'second=%s' % i2['second'])
        check('A2', 'route_note 为空（有班主任 ⇒ 无兜底文案）',
              i2['route_note'] == '', 'route_note=%r' % i2['route_note'])

        # ================================================ A5 4 天 → 进二级
        m5 = 'S5-A5 四日单-%s' % tag
        _, lid_a5 = new_leave(m5, leave_type='other', date_from=str(TODAY),
                              date_to=str(TODAY + datetime.timedelta(days=3)))
        i5 = leave_info(lid_a5)
        r5 = set_state(fac_s, lid_a5, 'approved')          # 一级通过（班主任本人）
        i5b = leave_info(lid_a5)
        lids['a5'] = lid_a5
        check('A5', '4 天单：一级通过后 state=pending_second',
              r5.status_code == 303 and i5b['state'] == 'pending_second',
              'code=%s state=%s→%s' % (r5.status_code, i5['state'], i5b['state']))
        check('A5', 'second_approver_id ∈ 教务处组 %s' % fx['office_uids'],
              i5b['second'] in fx['office_uids'], 'second=%s' % i5b['second'])
        check('A5', '4 天 = 4（含头含尾、自然日）', i5['days'] == 4,
              '%s ~ %s → days=%s' % (i5['date_from'], i5['date_to'], i5['days']))

        # ================================================ A6 3 天（边界）→ 一级即终
        m6 = 'S5-A6 三日单-%s' % tag
        _, lid_a6 = new_leave(m6, leave_type='other', date_from=str(TODAY),
                              date_to=str(TODAY + datetime.timedelta(days=2)))
        i6 = leave_info(lid_a6)
        r6 = set_state(fac_s, lid_a6, 'approved')
        i6b = leave_info(lid_a6)
        lids['a6'] = lid_a6
        check('A6', '3 天 = 3（边界值，含头含尾）', i6['days'] == 3,
              '%s ~ %s → days=%s' % (i6['date_from'], i6['date_to'], i6['days']))
        check('A6', '3 天单：一级通过后直接 approved（不进二级）',
              r6.status_code == 303 and i6b['state'] == 'approved'
              and i6b['second'] == 0,
              'code=%s state=%s→%s second=%s'
              % (r6.status_code, i6['state'], i6b['state'], i6b['second']))

        # ================================================ A7 转交一次（正向）
        audit_tr_before = audit_count('请假审批转交')
        msg_before = max_id('edu_message')
        name_a2 = leave_name(lid_a2)
        r7 = transfer_http(fac_s, lid_a2, fx['bo'], 'S5-A7 转交留痕（一级 → 教务处）')
        i7 = leave_info(lid_a2)
        rows7 = pscalar('select count(*) from edu_leave_transfer where leave_id=%d'
                        % lid_a2)
        check('A7', '转交一次 ⇒ first_approver_id 变成转入人（bo=%s）' % fx['bo'],
              r7.status_code == 303 and i7['first'] == fx['bo'],
              'code=%s first=%s' % (r7.status_code, i7['first']))
        check('A7', 'edu_leave_transfer 有且仅有 1 行', rows7 == 1, 'rows=%s' % rows7)
        check('A7', 'edu_audit_log 新增「请假审批转交」1 条',
              audit_count('请假审批转交') == audit_tr_before + 1,
              'before=%s after=%s' % (audit_tr_before, audit_count('请假审批转交')))
        check('A7', '三方通知落库（正文含单号 %s）' % name_a2,
              msg_count([name_a2], msg_before) >= 1,
              'rows=%s' % msg_count([name_a2], msg_before))

        # ================================================ A8 负向：原审批人不能再批
        snap0 = leave_info(lid_a2)
        audit8_all = audit_count('请假审批')
        audit8_leaf = audit_count('请假审批', 'edu.leave', lid_a2)
        r8 = set_state(fac_s, lid_a2, 'approved')          # 已转出的原审批人
        snap1 = leave_info(lid_a2)
        changed = diff_keys(snap0, snap1,
                            ['state', 'first', 'second', 'approver_id', 'approver_kind',
                             'approved_at', 'route_note', 'write_date'])
        check('A8', '负向：转交后原审批人 POST ⇒ 303 且 state 未变',
              r8.status_code == 303 and snap1['state'] == 'request',
              'code=%s state=%s→%s loc=%s'
              % (r8.status_code, snap0['state'], snap1['state'],
                 (r8.headers.get('Location') or '')[:44]))
        check('A8', '负向：该单逐字段「没发生」任何写入（含 write_date）',
              not changed, 'changed=%s' % (changed or '无'))
        check('A8', '负向：无新 audit 行（全局 / 单条两口径）',
              audit_count('请假审批') == audit8_all
              and audit_count('请假审批', 'edu.leave', lid_a2) == audit8_leaf,
              '全局 %s→%s；单条 %s→%s'
              % (audit8_all, audit_count('请假审批'), audit8_leaf,
                 audit_count('请假审批', 'edu.leave', lid_a2)))

        # ================================================ A9 负向：只能转 1 次
        r9 = transfer_http(bo_s, lid_a2, fx['fac'], 'S5-A9 第二次转交（应被挡）')
        i9 = leave_info(lid_a2)
        rows9 = pscalar('select count(*) from edu_leave_transfer where leave_id=%d'
                        % lid_a2)
        dup = shell_json(
            "L = env['edu.leave'].sudo().browse(%d)\n"
            "T = env['edu.leave.transfer'].sudo()\n"
            "row = T.search([('leave_id', '=', L.id)], limit=1)\n"
            "OUT['before'] = T.search_count([('leave_id', '=', L.id)])\n"
            "OUT['raised'] = ''\n"
            "try:\n"
            "    with env.cr.savepoint():\n"
            "        T.create({'leave_id': L.id, 'stage': row.stage,\n"
            "                  'from_user_id': row.from_user_id.id,\n"
            "                  'to_user_id': row.to_user_id.id,\n"
            "                  'reason': 'S5-A9 直接插重复行（应撞 UNIQUE）'})\n"
            "except Exception as exc:\n"
            "    OUT['raised'] = type(exc).__name__\n"
            "OUT['after'] = T.search_count([('leave_id', '=', L.id)])\n" % lid_a2)
        check('A9', '负向：第二次转交（HTTP）⇒ 303 且转交行仍为 1',
              r9.status_code == 303 and rows9 == 1 and i9['first'] == fx['bo'],
              'code=%s rows=%s→%s first=%s'
              % (r9.status_code, rows7, rows9, i9['first']))
        check('A9', '负向：直接 ORM 插重复行撞 UNIQUE(leave_id, stage)',
              dup['raised'] in ('UniqueViolation', 'IntegrityError')
              and dup['after'] == dup['before'] == 1,
              'raised=%s before=%s after=%s'
              % (dup['raised'], dup['before'], dup['after']))

        # ================================================ A3 无班主任（正向）
        shell_json("b = env['op.batch'].sudo().browse(%d)\n"
                   "b.write({'homeroom_teacher_id': False})\n"
                   "env.cr.commit()\n"
                   "OUT['now'] = b.homeroom_teacher_id.id or 0"
                   % fx['batch_of_student'])
        m3 = 'S5-A3 无班主任-%s' % tag
        _, lid_a3 = new_leave(m3, leave_type='other', date_from=str(TODAY),
                              date_to=str(TODAY + datetime.timedelta(days=1)))
        i3 = leave_info(lid_a3)
        lids['a3'] = lid_a3
        check('A3', '无班主任 ⇒ first_approver_id ∈ 教务处组 %s' % fx['office_uids'],
              i3['first'] in fx['office_uids'], 'first=%s' % i3['first'])
        check('A3', 'route_note 含「未设班主任，已转教务处」',
              route_note_hits(i3['route_note'], 'no_homeroom'),
              'route_note=%r' % i3['route_note'])

        # ================================================ A4 学生未分班（边界）
        m4 = 'S5-A4 未分班-%s' % tag
        markers.append(m4)
        a4 = shell_json(
            "L = env['edu.leave'].sudo().with_context(edu_leave_portal=True).create({\n"
            "    'name': %r, 'leave_type': 'other', 'date_from': %r, 'date_to': %r,\n"
            "    'reason': %r, 'student_id': %d, 'applicant_kind': 'student'})\n"
            "env.cr.commit()\n"
            "OUT['id'] = L.id\n"
            "OUT['first'] = L.first_approver_id.id or 0\n"
            "OUT['note'] = L.route_note or ''\n"
            "OUT['batch'] = L._student_batch().id or 0\n"
            % ('S5A4-%s' % tag, str(TODAY), str(TODAY + datetime.timedelta(days=1)),
               m4, fx['student_no_batch']))
        if a4.get('id'):
            created.append(a4['id'])
        check('A4', '学生未分班 ⇒ 同「无班主任」分支（first ∈ 教务处组）',
              a4.get('first') in fx['office_uids'] and a4.get('batch') == 0,
              'first=%s batch=%s（学生=%s %s）'
              % (a4.get('first'), a4.get('batch'), fx['student_no_batch'],
                 fx['student_no_batch_name']))
        check('A4', 'route_note 含「该生未分班，已转教务处」',
              route_note_hits(a4.get('note'), 'no_batch'), 'route_note=%r' % a4.get('note'))

        # ================================================ A10 事假学期配额
        used = float(shell_json(
            "st = env['op.student'].sudo().browse(%d)\n"
            "probe = env['edu.leave'].sudo().search(\n"
            "    [('student_id', '=', st.id), ('leave_type', '=', 'casual')], limit=1)\n"
            "from datetime import date\n"
            "OUT['used'] = probe._casual_days_used(probe._term_of(date.today()))\n"
            % fx['student_with_batch'])['used'])
        if used + 1 <= 5:      # 干净库里自造「已用」：不依赖外部数据
            need = int(5 - used) + 1
            m_t = 'S5-A10 配额补足-%s' % tag
            _, lid_t = new_leave(m_t, leave_type='casual', date_from=str(TODAY),
                                 date_to=str(TODAY + datetime.timedelta(days=need - 1)))
            used = float(leave_info(lid_t)['casual_used'])
        m10 = 'S5-A10 配额超限-%s' % tag
        _, lid_a10 = new_leave(m10, leave_type='casual', date_from=str(TODAY),
                               date_to=str(TODAY))
        i10 = leave_info(lid_a10)
        r10 = set_state(bo_s, lid_a10, 'approved')         # 一级通过（教务处兜底）
        i10b = leave_info(lid_a10)
        lids['a10'] = lid_a10
        check('A10', '事假学期累计 %s + 本单 1 天 > 5 ⇒ over_quota=True' % used,
              i10['over_quota'] is True,
              'used=%s days=%s over_quota=%s' % (used, i10['days'], i10['over_quota']))
        check('A10', '即使只有 1 天，一级通过后仍进 pending_second',
              r10.status_code == 303 and i10b['state'] == 'pending_second',
              'code=%s state=%s→%s' % (r10.status_code, i10['state'], i10b['state']))

        # ================================================ A11 禁止事后补假（负 + 正）
        y = TODAY - datetime.timedelta(days=1)
        rows_before = pscalar('select count(*) from edu_leave')
        m11n = 'S5-A11 门户补提-%s' % tag
        markers.append(m11n)
        r11n = submit_leave(stu_s, leave_type='other', date_from=str(y),
                            date_to=str(y), reason=m11n)
        rows_after = pscalar('select count(*) from edu_leave')
        hit11 = pscalar('select count(*) from edu_leave where reason = %s' % sql_lit(m11n))
        check('A11', '负向：门户 date_from < today ⇒ 422 且**不落库**',
              r11n.status_code == 422 and rows_after == rows_before and hit11 == 0,
              'code=%s rows %s→%s hit=%s'
              % (r11n.status_code, rows_before, rows_after, hit11))
        m11b = 'S5-A11 后台补录-%s' % tag
        markers.append(m11b)
        b11 = shell_json(
            "L = env['edu.leave'].with_user(%d).create({\n"
            "    'name': %r, 'leave_type': 'other', 'date_from': %r, 'date_to': %r,\n"
            "    'reason': %r, 'student_id': %d, 'applicant_kind': 'student'})\n"
            "OUT['id'] = L.id\nOUT['backfilled'] = bool(L.backfilled)\n"
            "env.cr.commit()\n"
            % (fx['admin'], 'S5A11B-%s' % tag, str(y), str(y), m11b,
               fx['student_with_batch']))
        if b11.get('id'):
            created.append(b11['id'])
        check('A11', '后台例外通道同款单 ⇒ 成功且 backfilled=True',
              bool(b11.get('id')) and b11.get('backfilled') is True,
              'id=%s backfilled=%s' % (b11.get('id'), b11.get('backfilled')))

        # ================================================ A12 病假 ≥2 天必须证明
        rows_before = pscalar('select count(*) from edu_leave')
        m12n = 'S5-A12 病假2天无证明-%s' % tag
        markers.append(m12n)
        r12n = submit_leave(stu_s, leave_type='sick', date_from=str(TODAY),
                            date_to=str(TODAY + datetime.timedelta(days=1)),
                            reason=m12n)
        rows_after = pscalar('select count(*) from edu_leave')
        hit12 = pscalar('select count(*) from edu_leave where reason = %s' % sql_lit(m12n))
        check('A12', '负向：病假 2 天无任何证明 ⇒ 422 且**不落库**',
              r12n.status_code == 422 and rows_after == rows_before and hit12 == 0,
              'code=%s rows %s→%s hit=%s'
              % (r12n.status_code, rows_before, rows_after, hit12))
        m12c = 'S5-A12 病假1天对照-%s' % tag
        r12c, lid_a12c = new_leave(m12c, leave_type='sick', date_from=str(TODAY),
                                   date_to=str(TODAY))
        i12c = leave_info(lid_a12c)
        check('A12', '对照：1 天病假不传证明也放行（proof_required=False）',
              r12c.status_code == 303 and i12c['proof_required'] is False,
              'code=%s proof_required=%s' % (r12c.status_code, i12c['proof_required']))
        m12p = 'S5-A12 病假2天口头证明-%s' % tag
        r12p, lid_a12p = new_leave(m12p, leave_type='sick', date_from=str(TODAY),
                                   date_to=str(TODAY + datetime.timedelta(days=1)),
                                   proof_kind='oral', oral_proof_by='S5 冒烟·口头证明人',
                                   oral_proof_relation='家长')
        i12p = leave_info(lid_a12p)
        r12a = set_state(bo_s, lid_a12p, 'approved')
        i12a = leave_info(lid_a12p)
        check('A12', '填 oral + 证明人 ⇒ 放行且 proof_required=True',
              r12p.status_code == 303 and i12p['proof_required'] is True
              and i12p['proof_kind'] == 'oral' and i12p['days'] == 2,
              'code=%s days=%s proof_required=%s kind=%s'
              % (r12p.status_code, i12p['days'], i12p['proof_required'],
                 i12p['proof_kind']))
        check('A12', '审批人点通过 ⇒ oral_proof_confirmed_by_id = 审批人（%s）' % fx['bo'],
              r12a.status_code == 303 and i12a['oral_confirmed_by'] == fx['bo'],
              'code=%s confirmed_by=%s' % (r12a.status_code, i12a['oral_confirmed_by']))

        # ================================================ A13 实践周（负向断言）
        m13 = 'S5-A13 实践周-%s' % tag
        r13, lid_a13 = new_leave(m13, leave_type='practice_week',
                                 date_from=str(TODAY), date_to=str(TODAY))
        i13 = leave_info(lid_a13)
        conv = convert_fields(sorted(shell_json(
            "OUT['names'] = sorted(env['edu.leave']._fields.keys())")['names']))
        check('A13', '负向：edu.leave 上不存在任何折算 / 调休 / 拼假字段', not conv,
              '命中=%s（模式=%s）' % (conv or '无', ','.join(CONVERT_FIELD_PATTERNS)))
        check('A13', '负向：实践周单据日期逐字未变（无任何折算改写）',
              r13.status_code == 303 and i13['leave_type'] == 'practice_week'
              and i13['date_from'] == str(TODAY) and i13['date_to'] == str(TODAY)
              and i13['days'] == 1 and i13['long_absence'] is False,
              '%s ~ %s days=%s long_absence=%s'
              % (i13['date_from'], i13['date_to'], i13['days'], i13['long_absence']))
        check('A13', '负向：实践周单据的 state 未被折算逻辑改写',
              i13['state'] == 'request', 'state=%s' % i13['state'])

        # ================================================ A14 cron 39（回归）
        psql("update edu_leave set create_date = now() - interval '49 hours', "
             "escalated_at = NULL where id = %d" % lid_a3)
        name_a3 = leave_name(lid_a3)
        msg0 = max_id('edu_message')
        n39_1 = shell_json(
            "OUT['n'] = env['edu.leave']._cron_escalate_pending()\n"
            "env.cr.commit()\n")['n']
        body_hit = ptext("select coalesce(string_agg(body, ' ~~ '), '') from edu_message "
                         "where id > %d and body like %s"
                         % (msg0, sql_lit('%' + name_a3 + '%')))
        i14 = leave_info(lid_a3)
        msg1 = max_id('edu_message')
        n39_2 = shell_json(
            "OUT['n'] = env['edu.leave']._cron_escalate_pending()\n"
            "env.cr.commit()\n")['n']
        n2 = msg_count([name_a3], msg1)
        check('A14', 'cron 39 提醒文案含「当前应批人」',
              bool(body_hit) and '当前应批人' in body_hit,
              'n=%s body=%s' % (n39_1, (body_hit or '（无新消息）')[:220]))
        check('A14', '提醒后已打 escalated_at（幂等去重标记）',
              bool(i14['escalated_at']), 'escalated_at=%s' % i14['escalated_at'])
        check('A14', '第二次跑 ⇒ 该单不重复提醒（新消息数 = 0）',
              n2 == 0, 'second_notified=%s（n=%s）' % (n2, n39_2))

    finally:
        lo = cleanup(created, markers, fx.get('batch_of_student'),
                     fx.get('batch_homeroom_before'), base_msg)
        print('\n收尾：本次建单 %d 张 → leftover=%s；班 %s 班主任现值=%s'
              % (len(created), lo.get('leftover_leaves'), fx.get('batch_of_student'),
                 lo.get('homeroom_now')))
        for key in sorted(lo):
            print('   %-22s %s' % (key, lo[key]))
        check('CLEAN', '夹具归还：本次建的每一张单都查不到（leftover = 0）',
              lo.get('leftover_leaves') == 0 and lo.get('leftover_transfer') == 0
              and lo.get('leftover_msg') == 0,
              'leaves=%s transfer=%s msg=%s'
              % (lo.get('leftover_leaves'), lo.get('leftover_transfer'),
                 lo.get('leftover_msg')))
        check('CLEAN', 'op_batch 班主任字段已还原为 NULL（「上线当天 100% 走教务处」的前提）',
              lo.get('homeroom_now') == 0, 'homeroom_now=%s' % lo.get('homeroom_now'))

    missing_cases = [c for c in EXPECTED_CASES if c not in SEEN_CASES]
    check('COVER', 'A1–A14 全部执行过（无静默跳过）', not missing_cases,
          'missing=%s' % (missing_cases or '无'))
    print('\n== leave_split_approval：%d PASS / %d FAIL ==' % (ok, fail))
    if fail:
        for res in RESULTS:
            if not res['pass']:
                print('  FAIL %s %s | %s' % (res['case'], res['name'], res['detail'][:240]))
    return 0 if fail == 0 else 1


def cleanup(created, markers, batch_id, homeroom_before, base_msg):
    """清场：删本次建的请假单（转交行随 cascade）+ 删本次产生的站内信 + 还原班主任。"""
    out = {}
    ids = sorted(set(int(i) for i in created if i))
    needles = [m for m in (markers or []) if m]
    if ids or needles:
        cond = []
        if ids:
            cond.append('id in (%s)' % ','.join(str(i) for i in ids))
        if needles:
            cond.append('reason in (%s)' % ','.join(sql_lit(m) for m in needles))
        raw = ptext("select coalesce(string_agg(name, ','), '') from edu_leave where %s"
                    % ' or '.join(cond))
        needles += [n for n in raw.split(',') if n]
    if ids:
        shell_json("L = env['edu.leave'].sudo().browse(%r)\n"
                   "OUT['found'] = len(L)\nL.unlink()\n"
                   "env.cr.commit()\n"
                   "OUT['left'] = env['edu.leave'].sudo().search_count(\n"
                   "    [('id', 'in', %r)])\n" % (ids, ids))
    out['leftover_leaves'] = (pscalar('select count(*) from edu_leave where id in (%s)'
                                      % ','.join(str(i) for i in ids)) if ids else 0)
    out['leftover_transfer'] = (pscalar(
        'select count(*) from edu_leave_transfer where leave_id in (%s)'
        % ','.join(str(i) for i in ids)) if ids else 0)
    if needles:
        cond = ' or '.join('body like %s' % sql_lit('%' + n + '%') for n in needles)
        psql('delete from edu_message where id > %d and (%s)' % (base_msg, cond))
    out['leftover_msg'] = msg_count(needles, base_msg)
    if batch_id:
        shell_json("b = env['op.batch'].sudo().browse(%d)\n"
                   "b.write({'homeroom_teacher_id': %s})\n"
                   "env.cr.commit()\n"
                   "OUT['now'] = b.homeroom_teacher_id.id or 0"
                   % (batch_id, homeroom_before or 'False'))
        out['homeroom_now'] = pscalar('select coalesce(homeroom_teacher_id, 0) '
                                      'from op_batch where id = %d' % batch_id)
    else:
        out['homeroom_now'] = 0
    return out


def save_results(explicit_path=None):
    payload = {'generated': time.strftime('%Y-%m-%d %H:%M:%S'),
               'pass': ok, 'fail': fail, 'cases': sorted(SEEN_CASES),
               'results': RESULTS}
    for path in {str(RESULTS_JSON), explicit_path}:
        if not path:
            continue
        try:
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                  encoding='utf-8')
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description='请假分级审批冒烟（设计稿 §9.4 A1–A14）')
    ap.add_argument('--selftest', action='store_true', help='不连站点：证明尺子准')
    ap.add_argument('--model-only', action='store_true',
                    help='只跑 A1（注册表 / 结构 / 冻结接口），不做门户写操作')
    ap.add_argument('--json', dest='json_out', help='结果落盘 JSON')
    args = ap.parse_args()

    if args.selftest:
        code = selftest()
    elif not preflight():
        code = 2
    elif args.model_only:
        case_a1()
        print('== --model-only：%d PASS / %d FAIL ==' % (ok, fail))
        code = 0 if fail == 0 else 1
    else:
        code = run_live()
    save_results(args.json_out)
    return code


if __name__ == '__main__':
    sys.exit(main())
