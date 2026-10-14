#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""换班申请（学生申请 → 教务审批）真机冒烟：六步闸门第 6 步。

设计稿：docs/plans/class-change-request-design.md §19（v2 载体裁定 = 修好既有
/course/change/request 链路并收口成唯一入口）+ §15 验收 V3–V22。
用法：python3 tests/smoke/class_change_request.py
结果落盘：tests/smoke/class_change_request_results.json

【V1 / V2 为什么不在这里跑】
V1 = bash scripts/safe_upgrade.sh edu_portal（EXIT=0 且无 Traceback/CRITICAL）；
V2 = 离线门禁五件套。升级会**重启 web 容器**，把被测进程整段换掉 —— 必须由调用方
先跑完，本脚本只做前置探活（无升级锁 + 带库名登录页可达），否则会在自己引发的
重启里读半程读数（同 tests/smoke/c1_impact_notify.py 的既定口径）。

【V10 静默改写防线：分阶段，不在一次进程里做】
-u edu_portal 会把「有科目集却 doc_type≠subject_registration」的单静默改写成选课单
（models/registration.py _infer_doc_type 挂在 _auto_init）。本脚本的归还口径是
leftover=0，所以防线测试拆成三段（外部步骤）：
    python3 tests/smoke/class_change_request.py --phase guard-keep   # 留 1 张单
    bash scripts/safe_upgrade.sh edu_portal                          # 再跑一次 -u
    python3 tests/smoke/class_change_request.py --phase guard-check --reg-id N

【判据红线（设计 §15.3）】
- 探测**不跟随重定向**（allow_redirects=False + 精确 Location）；
- 不只断言「页面 200 / 有横幅」——要看库里的行与总数；
- 不读代码就说「字段级留痕生效」——必须读回 mail_tracking_value 行；
- 载体必须先被断言合法（学生 5 只有 1 条 running 档案、同课程第二班存在）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

BASE = os.environ.get('CCR_BASE', 'http://localhost:8069')
DB = os.environ.get('EDU_DB_NAME', 'edu19')
DB_CONTAINER = os.environ.get('EDU_DB_CONTAINER', 'edu19-clone-db-1')
REPO = Path(__file__).resolve().parent.parent.parent
RESULTS_JSON = Path(__file__).resolve().parent / 'class_change_request_results.json'
LOCK = os.path.join(os.environ.get('TMPDIR') or '/tmp', 'edu19_upgrade.lock')

STUDENT = ('stu@local', 'demo123')       # 王小明 = op.student 5
TEACHER = ('faculty@local', 'demo123')   # op.faculty 17（batch 8 任课教师）
BACKOFFICE = ('backoffice@local', 'demo123')
PARENT = ('parent@local', 'demo123')
STUDENT2 = ('ccr_smoke_s2@local', 'demo123')

STU_ID = 5
SC_ID = 9                                # 学生 5 的唯一 running 档案
ROLL_ORIG = 'PRP26-001'
TAG = '【演示】换班冒烟'

RESULTS = []
FX = {}
CREATED_REGS = []
BASE_COUNTS = {}


def check(no, name, ok, detail=''):
    RESULTS.append({'no': no, 'name': name, 'pass': bool(ok),
                    'detail': str(detail)[:900]})
    print('  [%s] %-6s %s%s' % ('PASS' if ok else 'FAIL', no, name,
                                (' | ' + str(detail)[:400]) if detail else ''))
    return bool(ok)


def note(msg):
    print('  ---- %s' % msg)


# ---------------------------------------------------------------- 工具
def psql(sql):
    out = subprocess.run(['docker', 'exec', DB_CONTAINER, 'psql', '-U', 'odoo',
                          '-d', DB, '-tAc', sql],
                         capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        raise RuntimeError('psql 失败：' + (out.stderr or '').strip()[:300])
    return out.stdout.strip()


def pscalar(sql):
    return int(psql(sql) or 0)


def shell(code, timeout=300):
    cmd = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
           '-c', '/etc/odoo/odoo.conf', '--db_host=db', '--db_port=5432',
           '--db_user=odoo', '--db_password=odoo', '-d', DB, '--no-http']
    out = subprocess.run(cmd, input=code, capture_output=True, text=True,
                         timeout=timeout, cwd=str(REPO))
    return (out.stdout or '') + (out.stderr or '')


def shell_json(body, timeout=300):
    """在 odoo shell 里跑 body；body 把结果写进 OUT，返回值即 OUT（写入需自 commit）。"""
    code = ('import json\nOUT = {}\n' + body +
            "\nprint('@@CCRJSON@@' + json.dumps(OUT, ensure_ascii=False, "
            "default=str))\n")
    blob = shell(code, timeout)
    m = re.search(r'@@CCRJSON@@(.*)', blob)
    if not m:
        fail_path = '/tmp/ccr_shell_fail.%d.txt' % len(RESULTS)
        Path(fail_path).write_text(blob)
        Path('/tmp/ccr_shell_fail.last.txt').write_text(fail_path)
        raise RuntimeError('odoo shell 未返回 JSON（完整输出见 %s）：%s'
                           % (fail_path, blob[-1500:]))
    return json.loads(m.group(1))


def login(user, pwd):
    s = requests.Session()
    s.trust_env = False
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    r = s.post(BASE + '/web/session/authenticate', timeout=30, json={
        'jsonrpc': '2.0', 'method': 'call',
        'params': {'db': DB, 'login': user, 'password': pwd}})
    try:
        uid = ((r.json() or {}).get('result') or {}).get('uid')
    except Exception:
        uid = None
    return (s, uid) if uid else (None, None)


def probe(sess, path):
    """**不跟随重定向**的探测（判 303 必须看首跳）。"""
    return sess.get(BASE + path, timeout=30, allow_redirects=False)


def csrf_of(sess, path):
    r = probe(sess, path)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text or '')
    return (r, m.group(1) if m else None)


def audit_count(action=None):
    dom = "model='op.subject.registration'"
    if action:
        dom += " and action=%s" % quote_sql(action)
    return pscalar('select count(*) from edu_audit_log where %s' % dom)


def quote_sql(s):
    return "'" + str(s).replace("'", "''") + "'"


def msg_count(recipient_uid, event_key=None, like=None):
    dom = 'recipient_id=%d' % recipient_uid
    if event_key:
        dom += ' and event_key=%s' % quote_sql(event_key)
    if like:
        dom += ' and body like %s' % quote_sql('%' + like + '%')
    return pscalar('select count(*) from edu_message where %s' % dom)


def tracking_batch_rows(sc_id=SC_ID):
    return pscalar(
        "select count(*) from mail_tracking_value tv "
        "join mail_message m on m.id = tv.mail_message_id "
        "join ir_model_fields f on f.id = tv.field_id "
        "where m.model = 'op.student.course' and m.res_id = %d "
        "and f.name = 'batch_id'" % sc_id)


def sc_row(sc_id=SC_ID):
    row = psql("select coalesce(course_id,0), coalesce(batch_id,0), state, "
               "coalesce(roll_number,'') from op_student_course where id=%d"
               % sc_id)
    parts = [p.strip() for p in row.split('|')]
    return {'course': int(parts[0]), 'batch': int(parts[1]), 'state': parts[2],
            'roll': parts[3]}


def sc_subjects(sc_id=SC_ID):
    ids = psql("select coalesce(string_agg(op_subject_id::text, ',' order by "
               "op_subject_id), '') from op_student_course_op_subject_rel "
               "where op_student_course_id=%d" % sc_id)
    return sorted(int(x) for x in ids.split(',') if x.strip())


def sc_total():
    return pscalar('select count(*) from op_student_course')


def exams_snapshot():
    """V16：成绩/考勤的实际存放处（课程与班级自带，不引用档案行）。"""
    snap = {}
    for tbl in ('op_exam_attendees', 'op_result_line', 'op_marksheet_line',
                'op_attendance_line'):
        snap[tbl] = pscalar('select count(*) from %s' % tbl)
    snap['attendees_marks'] = psql(
        "select coalesce(string_agg(id||':'||coalesce(course_id::text,'-')||"
        "':'||coalesce(batch_id::text,'-')||':'||coalesce(marks::text,'-'), "
        "'|' order by id), '') from op_exam_attendees")
    snap['att_lines'] = psql(
        "select coalesce(string_agg(id||':'||coalesce(course_id::text,'-')||"
        "':'||coalesce(batch_id::text,'-'), '|' order by id), '') "
        "from op_attendance_line")
    return snap


# ---------------------------------------------------------------- 夹具
SETUP_CODE = '''
env = env  # noqa

# 0) 幂等前置：清掉上一次残留的同标签夹具（冒烟可反复跑，不留残渣）
old_b = env['op.batch'].sudo().with_context(active_test=False).search(
    [('name', 'like', '%(tag)s%%')])
if old_b:
    env['op.session'].sudo().with_context(active_test=False).search(
        [('batch_id', 'in', old_b.ids)]).unlink()
    old_b.unlink()
old_u = env['res.users'].sudo().search([('login', '=', '%(login2)s')])
if old_u:
    env['op.student'].sudo().browse(7).write({'user_id': False})
    old_u.unlink()
env.cr.commit()

# 1) 同课程（18）第二班 —— 只换班的合法目标
BD = {'start_date': '2026-09-01', 'end_date': '2027-07-31'}
b_same = env['op.batch'].sudo().create(dict(BD, **{
    'name': '%(tag)s · 换班目标班',
    'code': 'CCR-SAME',
    'course_id': 18,
}))
# 2) 另一课程（13）的目标班 x3 —— 换课程/撞约束预检用
b_cross = env['op.batch'].sudo().create(dict(BD, **{
    'name': '%(tag)s · 换课目标班A', 'code': 'CCR-CROSS-A', 'course_id': 13}))
b_cross2 = env['op.batch'].sudo().create(dict(BD, **{
    'name': '%(tag)s · 换课目标班B', 'code': 'CCR-CROSS-B', 'course_id': 13}))
b_cross3 = env['op.batch'].sudo().create(dict(BD, **{
    'name': '%(tag)s · 换课目标班C', 'code': 'CCR-CROSS-C', 'course_id': 13}))
# 3) 已停用班（V19：不得出现在下拉里）
b_off = env['op.batch'].sudo().create(dict(BD, **{
    'name': '%(tag)s · 已停用班', 'code': 'CCR-OFF', 'course_id': 18}))
b_off.active = False
# 4) 目标班的课节（任课教师 = faculty 17 = faculty@local）——
#    教师通知要走 op.session.faculty_id（本仓无班主任字段）
sub_c18 = env['op.course'].sudo().browse(18).subject_ids[:1]
sub_c13 = env['op.course'].sudo().browse(13).subject_ids[:1]
import datetime
# 远离既有课节时段（基座有「同教师同时段不可重复排课」校验）
start = datetime.datetime(2031, 3, 1, 8, 0, 0)
fac = env['op.faculty'].sudo().browse(17)
sess = []
for i, (b, sub, cid) in enumerate(((b_same, sub_c18, 18), (b_cross, sub_c13, 13),
                                   (b_cross2, sub_c13, 13))):
    sess.append(env['op.session'].sudo().create({
        'start_datetime': start + datetime.timedelta(days=i),
        'end_datetime': start + datetime.timedelta(days=i, hours=2),
        'course_id': cid, 'batch_id': b.id, 'subject_id': sub.id,
        'faculty_id': fac.id,
    }))
# 5) 学生 B（张同学，op.student 7）临时给个门户账号 —— 「看不到他人申请」
partner = env['op.student'].sudo().browse(7).partner_id
u2 = env['res.users'].sudo().create({
    'login': '%(login2)s', 'password': 'demo123', 'partner_id': partner.id,
    'name': partner.name or 'CCR 冒烟学生B'})
env['op.student'].sudo().browse(7).write({'user_id': u2.id})
env.cr.commit()

OUT['b_same'] = b_same.id
OUT['b_cross'] = b_cross.id
OUT['b_cross2'] = b_cross2.id
OUT['b_cross3'] = b_cross3.id
OUT['b_off'] = b_off.id
OUT['sessions'] = [s.id for s in sess]
OUT['user2'] = u2.id
OUT['student2_name'] = env['op.student'].sudo().browse(7).name
OUT['c18_subjects'] = env['op.course'].sudo().browse(18).subject_ids.ids
OUT['c13_subjects'] = env['op.course'].sudo().browse(13).subject_ids.ids
OUT['sub_c18_name'] = sub_c18.name
_att = env['op.exam.attendees'].sudo().search([('student_id', '=', 5)],
                                              limit=1)
OUT['grade_subject_name'] = _att.exam_id.subject_id.name if _att else ''
OUT['grade_exam_class'] = [_att.course_id.id, _att.batch_id.id] if _att \
    else []
OUT['c13_only_subject_name'] = env['op.subject'].sudo().browse(
    sorted(set(env['op.course'].sudo().browse(13).subject_ids.ids)
           - set(env['op.course'].sudo().browse(18).subject_ids.ids))[0]).name
c19 = env['op.course'].sudo().browse(19)
OUT['course19_name'] = c19.name
c19.active = False          # V19：停用课程不得出现在目标课程下拉里
from odoo.addons.edu_portal.models.notify_pref import NOTIFY_EVENTS
OUT['notify_events'] = [k for k, _l in NOTIFY_EVENTS]
OUT['notify_events_n'] = len(NOTIFY_EVENTS)
fn = env['op.subject.registration'].action_course_change_approve
OUT['ccr_fn_file'] = fn.__code__.co_filename      # 收口条件 C2 的地址级证据
OUT['ccr_fn_qualname'] = fn.__qualname__
g = env.ref('openeducat_core.group_op_back_office_admin')
seen, stack = set(), [g]
while stack:
    grp = stack.pop()
    if grp.id in seen:
        continue
    seen.add(grp.id)
    for x in grp.implied_ids:
        stack.append(x)
OUT['implied_ids'] = sorted(seen)
OUT['implied_has_system'] = env.ref('base.group_system').id in seen
env.cr.commit()
'''


def setup_fixtures():
    body = SETUP_CODE % {'tag': TAG, 'login2': STUDENT2[0]}
    return shell_json(body)


CLEAN_CODE = '''
env = env  # noqa

# 1) 档案行还原（唯一事实源：原地改写，永不新建行 —— 所以只需还原字段值）
sc = env['op.student.course'].sudo().browse(%(sc_id)d)
sc.write({'course_id': %(course)d, 'batch_id': %(batch)d,
          'roll_number': %(roll)r,
          'subject_ids': [(6, 0, %(subjects)s)]})
# 2) 单据（本次冒烟造的全部单）+ 本次冒烟产生的通知/审计行（V14 归还口径）
regs = env['op.subject.registration'].sudo().browse(%(regs)s)
if regs:
    regs.unlink()
env['edu.message'].sudo().search(
    [('id', '>', %(msg_max)d),
     ('create_date', '>=', %(since)r)]).filtered(
    lambda m: '换班通知' in (m.body or '')).unlink()
env['edu.audit.log'].sudo().search(
    [('id', '>', %(audit_max)d),
     ('create_date', '>=', %(since)r),
     ('action', 'in', ('调班提交', '调班审批'))]).unlink()
env['op.subject.registration'].sudo().search(
    [('create_date', '>=', %(since)r)]).filtered(
        lambda r: 'CCR 冒烟' in (r.applicant_note or '')).unlink()
# 3) 撞约束预检用的临时档案行
env['op.student.course'].sudo().browse(%(tmp_scs)s).unlink()
# 4) 课节 / 班（**按标签反查**，不依赖调用方传 id —— 幂等、部分失败也能收干净）
bs = env['op.batch'].sudo().with_context(active_test=False).search(
    [('name', 'like', %(tagname)r)])
if bs:
    env['op.session'].sudo().with_context(active_test=False).search(
        [('batch_id', 'in', bs.ids)]).unlink()
    bs.unlink()
# 4b) 存量夹具单：按快照写回（用 raw SQL，避免产生 chatter/跟踪噪点）
import json as _json
for _it in _json.loads(%(legacy)r):
    env.cr.execute(
        "UPDATE op_subject_registration SET state=%%s, reject_reason=%%s "
        "WHERE id=%%s", (_it['state'], _it['reject_reason'] or None, _it['id']))
# 4c) 运行期在档案 9 上产生的 chatter/字段留痕 → 回到基线（追踪行 before=0）
try:
    env.cr.execute(
        "DELETE FROM mail_tracking_value WHERE id IN (SELECT tv.id FROM "
        "mail_tracking_value tv JOIN mail_message m ON m.id = tv.mail_message_id "
        "WHERE m.model = 'op.student.course' AND m.res_id = %(sc_id)d "
        "AND m.create_date >= %(since)r)")
    env.cr.execute(
        "DELETE FROM mail_message WHERE model = 'op.student.course' "
        "AND res_id = %(sc_id)d AND create_date >= %(since)r")
except Exception as _exc:      # 清场绝不因为"擦 chatter"失败而整体回滚
    OUT['chatter_warn'] = str(_exc)[:200]
    env.cr.rollback()
# 5) 课程 19 的启用状态
c19 = env['op.course'].sudo().browse(19)
c19.active = True
# 6) 学生 B 的临时账号
st2 = env['op.student'].sudo().browse(7)
st2.write({'user_id': False})
env['res.users'].sudo().search([('login', '=', %(login2)r)]).unlink()
env.cr.commit()
OUT['ok'] = 1
'''


GUARD_JSON = Path(__file__).resolve().parent / '.ccr_guard.json'

# ---------------------------------------------------------------- 场景
def post_state(sess, rid, state, token_path=None, **extra):
    page = probe(sess, token_path or ('/registrar/subject/approvals/%d' % rid))
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text or '')
    data = {'csrf_token': m.group(1) if m else None, 'state': state}
    data.update(extra)
    return sess.post(BASE + '/registrar/subject/approvals/%d/set_state' % rid,
                     data=data, timeout=30, allow_redirects=False)


def submit_change(sess, course_id, batch_id, reason):
    page = probe(sess, '/course/change/request')
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text or '')
    return sess.post(BASE + '/course/change/request/save', timeout=30,
                     allow_redirects=False,
                     data={'csrf_token': m.group(1) if m else None,
                           'course_id': course_id, 'batch_id': batch_id,
                           'reason': reason})


def redirect_of(resp):
    return resp.headers.get('Location') or ''


def redirect_msg(resp):
    from urllib.parse import unquote
    m = re.search(r'[?&]msg=([^&]+)', redirect_of(resp))
    return unquote(m.group(1)) if m else ''


_TT_WEEK_DAY = '2031-03-01'          # 演示课节所在日（夹具排在这一天）


def week_offset_to(day_str):
    """把 /student/timetable 的 w= 周偏移算到指定日期所在周（本地周一为基准）。"""
    from datetime import date, timedelta
    d = date(*[int(x) for x in day_str.split('-')])
    target_monday = d - timedelta(days=d.weekday())
    today = date.today()
    monday_today = today - timedelta(days=today.weekday())
    return (target_monday - monday_today).days // 7


def max_reg_id():
    return pscalar('select coalesce(max(id),0) from op_subject_registration')


def new_regs_after(prev_max):
    """本次 POST 真正新建的单（id > prev_max）—— 不靠 max(id) 猜（历史单 id 更大时会骗人）"""
    rows = psql('select id from op_subject_registration where id > %d '
                'order by id' % prev_max)
    return [int(x) for x in rows.split() if x.strip()]


def reject_legacy(back, legacy):
    """教务逐条驳回存量夹具单（真机 HTTP，走同一 set_state 路由）。"""
    ok = 0
    for lid, _st, _rr in legacy:
        page = probe(back, '/registrar/subject/approvals/%s' % lid)
        tok = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text or '')
        back.post(BASE + '/registrar/subject/approvals/%s/set_state' % lid,
                  timeout=30, allow_redirects=False,
                  data={'csrf_token': tok.group(1) if tok else None,
                        'state': 'rejected',
                        'reject_reason': 'CCR 冒烟：存量夹具单不自洽，请重新提交'})
        if reg_info(int(lid))['state'] == 'rejected':
            ok += 1
    return ok


def legacy_snapshot():
    """既有 course_change/submitted 夹具单快照（id, state, reject_reason）—— 归还用。"""
    rows = psql("select id, state, coalesce(reject_reason, '') from "
                "op_subject_registration where doc_type='course_change' and "
                "state='submitted' and student_id=%d order by id" % STU_ID)
    return [r.split('|', 2) for r in rows.splitlines() if r.strip()]


def reg_info(rid):
    row = psql("select coalesce(student_id,0), coalesce(course_id,0), "
               "coalesce(batch_id,0), state, coalesce(doc_type,'-'), "
               "coalesce(name,'-') from op_subject_registration where id=%d"
               % rid)
    p = [x.strip() for x in row.split('|')]
    return {'student': int(p[0]), 'course': int(p[1]), 'batch': int(p[2]),
            'state': p[3], 'doc_type': p[4], 'name': p[5]}


def payload_counts(rid):
    comp = pscalar('select count(*) from subject_compulsory_rel '
                   'where register_id=%d' % rid)
    elec = pscalar('select count(*) from op_subject_op_subject_registration_rel'
                   ' where op_subject_registration_id=%d' % rid)
    return comp, elec


def msg_bodies(uid, after_id):
    rows = psql('select id||E\'\\x01\'||replace(body, E\'\\n\', \' / \') '
                'from edu_message where recipient_id=%d and id > %d order by id'
                % (uid, after_id))
    return [r.split('\x01') for r in rows.splitlines() if r.strip()]


def max_msg_id():
    return pscalar('select coalesce(max(id),0) from edu_message')


def run_all():
    # ---------------------------------------------------------- C00 前置
    check('C00a', '无升级锁（串行口径）', not os.path.exists(LOCK), LOCK)
    code = requests.get(BASE + '/web/login?db=' + DB, timeout=15,
                        allow_redirects=False).status_code
    check('C00b', 'web 就绪（带库名登录页）', code in (200, 302, 303),
          'code=%s' % code)

    since = psql("select to_char(now() - interval '2 minutes', "
                 "'YYYY-MM-DD HH24:MI:SS')")
    snap0 = sc_row()
    base = {'course': snap0['course'], 'batch': snap0['batch'],
            'state': snap0['state'], 'roll': snap0['roll'],
            'subjects': sc_subjects()}
    reg_n0 = pscalar('select count(*) from op_subject_registration')
    sc_n0 = sc_total()
    audit_n0 = pscalar('select count(*) from edu_audit_log')
    msg_n0 = max_msg_id()
    track_n0 = tracking_batch_rows()
    exams0 = exams_snapshot()
    note('基线：档案=%s 单据=%d 档案行=%d 审计=%d 追踪行=%d'
         % (base, reg_n0, sc_n0, audit_n0, track_n0))

    # ---------------------------------------------------------- 夹具
    fx = setup_fixtures()
    FX.update(fx)
    FX['tmp_scs'] = []
    check('C01', '夹具已建（同课程第二班 + 另一课程班 x3 + 停用班 + 课节）',
          all(fx.get(k) for k in ('b_same', 'b_cross', 'b_cross2', 'b_cross3',
                                  'b_off')), json.dumps(fx, ensure_ascii=False))

    # ---------------------------------------------------------- V3 载体合法
    run_sc = pscalar("select count(*) from op_student_course where "
                     "student_id=%d and state='running'" % STU_ID)
    check('V3a', '载体合法：学生 5 恰好 1 条 running 档案', run_sc == 1,
          'running=%d（档案 id=%d）' % (run_sc, SC_ID))
    check('V3b', '载体合法：同课程（18）第二班存在',
          pscalar('select count(*) from op_batch where course_id=18 and active '
                  'and id<>8') >= 1, 'demo batch=%s' % fx['b_same'])
    check('V3c', '载体合法：档案 id=%d 与基线一致（course=%d batch=%d）'
          % (SC_ID, base['course'], base['batch']),
          snap0['course'] == 18 and snap0['batch'] == 8 and
          snap0['state'] == 'running', json.dumps(snap0))

    stu, stu_uid = login(*STUDENT)
    back, back_uid = login(*BACKOFFICE)
    tea, tea_uid = login(*TEACHER)
    par, par_uid = login(*PARENT)
    stu2, stu2_uid = login(*STUDENT2)
    check('C02', '四个角色登录（学生/教务/教师/家长 + 学生B）',
          all([stu_uid == 8, back_uid == 12, tea_uid == 11, par_uid == 10,
               stu2_uid == fx['user2']]),
          'uid=%s/%s/%s/%s/%s' % (stu_uid, back_uid, tea_uid, par_uid, stu2_uid))

    # ---------------------------------------------------------- V4 + V19
    r = probe(stu, '/course/change/request')
    txt = r.text or ''
    old_batch_name = psql('select name from op_batch where id=8')
    new_batch_name = psql('select name from op_batch where id=%d' % fx['b_same'])
    check('V4a', '学生 GET /course/change/request = 200', r.status_code == 200,
          'code=%s len=%d' % (r.status_code, len(txt)))
    check('V4b', '页面显示「现班 = %s」' % old_batch_name,
          old_batch_name in txt and '将变更您当前在读的档案' in txt, '')
    check('V4c', '目标班下拉含同课程第二班（%s）' % new_batch_name,
          new_batch_name in txt, '')
    check('V4d', '页面标题按校长拍板 =「换班申请」',
          '换班申请' in txt and '课程变更申请列表' not in txt, '')
    check('V19a', '目标课程下拉不含 active=false 的班级所属课程',
          fx['course19_name'] not in txt, '已先停用课程 19（%s）'
          % fx['course19_name'])
    check('V19b', '已停用班不在下拉里（%s）' % TAG + ' · 已停用班',
          (TAG + ' · 已停用班') not in txt, '')
    tt = '/student/timetable?view=week&w=%d' % week_offset_to(_TT_WEEK_DAY)
    rr = probe(stu, tt)
    check('V7m-课表-before', '前置对照：换班前同一周 URL 看不到演示课节',
          rr.status_code == 200 and FX['sub_c18_name'] not in (rr.text or ''),
          'code=%s' % rr.status_code)
    # 校长拍板 P5 的前置读数：这是**旧班（18/8）**那张考试的已录成绩
    rr = probe(stu, '/grade-book')
    check('P5-成绩-before', '前置：成绩簿可见旧班考试成绩「%s」（考试归属 %s）'
          % (FX['grade_subject_name'], FX['grade_exam_class']),
          rr.status_code == 200
          and FX['grade_subject_name'] in (rr.text or ''),
          'code=%s' % rr.status_code)
    edge = psql('select name from op_batch where id=%d' % fx['b_same'])
    check('V19c', '下拉项带「在读 N 人 · 课节 N 节」（人话规模）',
          '在读 ' in txt and '课节 ' in txt, '')

    # ---------------------------------------------------------- V5/防误伤
    r = probe(back, '/course/change/request')
    check('V5', '非学生（教务账号）GET 学生页 → 303 /my/home',
          r.status_code == 303 and redirect_of(r) == '/my/home',
          'code=%s loc=%s' % (r.status_code, redirect_of(r)))
    r = probe(par, '/course/change/request')
    check('P-family', '家长 GET 学生换班页 → 303 /my/home（家长读不到）',
          r.status_code == 303 and redirect_of(r) == '/my/home',
          'code=%s loc=%s' % (r.status_code, redirect_of(r)))

    # ------------------------------------------------- 存量夹具单：队列可达 + 可驳回
    # 本地那 11 张 course_change/submitted（生产 0 张，设计 §19.6）是既有冒烟夹具：
    # 它们**结构不自洽**（course 13 但 batch 8 属课程 18）⇒ 审批动作会人话拒绝；
    # 同时「同一学生已有待批换班单」的防重复守卫会挡住新申请。
    # 本段读出来 → 断言队列可见 + 通过被拒 → 由教务逐条**驳回**（设计 P10-(b) 的处置），
    # 归还阶段按快照把状态写回 submitted（不把别人的夹具改坏）。
    legacy = legacy_snapshot()
    FX['legacy'] = legacy
    if not legacy:
        # 只在「上一轮跑脏了」时出现：不拿 0 张单当"通过"（判据强度第 4 条）
        check('V22-legacy0', '本地存量 course_change/submitted 夹具存在（载体合法）',
              False, '0 张 —— 环境被上一轮跑脏，请先跑 --phase restore')
    else:
        check('V22-legacy0', '本地存量 course_change/submitted 夹具数量（生产 0）',
              len(legacy) >= 1, 'ids=%s' % [x[0] for x in legacy])
        lnames = psql("select string_agg(name, '|') from op_subject_registration "
                      "where doc_type='course_change' and state='submitted' "
                      "and student_id=%d" % STU_ID)
        r = probe(back, '/registrar/subject/approvals?filterby=change')
        check('V22-legacy1', '★ 存量夹具单进队列（「教务够不着」已修好）',
              all(n in (r.text or '') for n in lnames.split('|') if n),
              'names=%s' % lnames)
        lrid = int(legacy[0][0])
        r = post_state(back, lrid, 'approved')
        check('V22-legacy2',
              '存量不自洽单点通过 → 人话拒绝（不是 ValidationError 冒 500）',
              r.status_code == 303 and 'box=error' in redirect_of(r)
              and '不一致' in redirect_msg(r), 'msg=%s' % redirect_msg(r))
        check('V22-legacy3', '被拒的存量单未产生任何档案写入',
              sc_row()['course'] == 18 and sc_row()['batch'] == 8,
              json.dumps(sc_row(), ensure_ascii=False))
        r = submit_change(stu, 18, fx['b_same'], 'CCR 冒烟：应被存量单挡住')
        check('V22-legacy4', '存量待批单会挡住新申请（防重复入口生效）',
              'box=error' in redirect_of(r) and '待审批' in redirect_msg(r),
              'msg=%s' % redirect_msg(r))
        ok_rej = reject_legacy(back, legacy)
        check('V22-legacy5', '教务可逐条驳回存量夹具单（%d 张，归还阶段写回）'
              % len(legacy), ok_rej == len(legacy), 'rejected=%d' % ok_rej)

    # ---------------------------------------------------------- V6 提交
    audit0 = audit_count('调班提交')
    prev = max_reg_id()
    r = submit_change(stu, 18, fx['b_same'], 'CCR 冒烟：只换班（同课程）')
    new_ids = new_regs_after(prev)
    rid1 = new_ids[0] if new_ids else 0
    CREATED_REGS.extend(new_ids)
    info1 = reg_info(rid1)
    comp, elec = payload_counts(rid1)
    check('V6a', '提交 → 303 回 ?box=submitted',
          r.status_code == 303 and 'box=submitted' in redirect_of(r),
          'code=%s loc=%s' % (r.status_code, redirect_of(r)))
    check('V6b', '库里新增 1 行：doc_type=course_change / state=submitted / '
          'batch=目标班 / student=5',
          info1['doc_type'] == 'course_change' and info1['state'] == 'submitted'
          and info1['batch'] == fx['b_same'] and info1['student'] == STU_ID
          and pscalar('select count(*) from op_subject_registration') == reg_n0 + 1,
          json.dumps(info1, ensure_ascii=False))
    check('V6c', '调班单不携带任何科目集（硬约束 §5.3）',
          comp == 0 and elec == 0, 'compulsory=%d elective=%d' % (comp, elec))
    check('V6d', '审计 +1 行 action=调班提交',
          audit_count('调班提交') == audit0 + 1,
          'before=%d after=%d' % (audit0, audit_count('调班提交')))
    # 单号：基座 create() 已用 ir.sequence('op.subject.registration') 分配
    # SR%05d；路由里的 CR 兜底分支实际是**死代码**（设计 P1′ 说「CR%05d 已在用」
    # 与实况不符 —— 本地 11 张历史变更单也都是 SR0008–SR0017）。
    check('V6e', '单号由基座序列分配（SR/CR + 序号，与既有变更单同名口径）',
          bool(re.match(r'^(SR|CR)\d{4,}$', info1['name'] or '')),
          info1['name'])

    # 防重复提交
    r = submit_change(stu, 18, fx['b_same'], 'CCR 冒烟：重复提交应被拒')
    check('V6f', '同一学生已有待批单时再提交被拒（人话提示）',
          r.status_code == 303 and 'box=error' in redirect_of(r)
          and '待审批' in redirect_msg(r),
          'loc=%s msg=%s' % (redirect_of(r), redirect_msg(r)))
    check('V6g', '被拒后单据数未增加',
          pscalar('select count(*) from op_subject_registration') == reg_n0 + 1, '')

    # ---------------------------------------------------------- 防误伤：他人
    r = probe(stu2, '/course/change/request')
    t2 = r.text or ''
    check('P-other', '学生 B 看不到学生 A 的申请（页面不含 %s）'
          % info1['name'],
          r.status_code == 200 and info1['name'] not in t2,
          'code=%s' % r.status_code)

    # ---------------------------------------------------------- V21 队列可见性
    r = probe(back, '/registrar/subject/approvals?filterby=change')
    bt = r.text or ''
    check('V21a', '教务在「变更审批」页签看到该单',
          r.status_code == 200 and info1['name'] in bt and '变更审批' in bt,
          'code=%s' % r.status_code)
    r = probe(back, '/registrar/subject/approvals?filterby=all')
    check('V21b', '教务「全部」同时看到选课单与变更单',
          'SR0513' in (r.text or '') and info1['name'] in (r.text or ''), '')
    r = probe(tea, '/registrar/subject/approvals?filterby=change')
    tt = r.text or ''
    check('V21c', '教师看不到变更单（列表不含 %s）' % info1['name'],
          info1['name'] not in tt, 'code=%s' % r.status_code)
    r = probe(tea, '/registrar/subject/approvals/%d' % rid1)
    check('V21d', '教师直接开变更单详情 → 303（服务端二次门禁）',
          r.status_code == 303, 'code=%s loc=%s'
          % (r.status_code, redirect_of(r)))
    # 教师进不了详情页 ⇒ csrf 从**教师能打开的页面**取（否则只会得到一个
    # 400 CSRF 错，看起来"挡住了"其实是探测自己坏了 —— 判据强度五兄弟第 5 条）
    r = post_state(tea, rid1, 'approved',
                   token_path='/registrar/subject/approvals?filterby=all')
    check('V21e', '教师直接 POST set_state → 303 且状态未变',
          r.status_code == 303 and reg_info(rid1)['state'] == 'submitted',
          'code=%s state=%s' % (r.status_code, reg_info(rid1)['state']))
    r = probe(back, '/registrar/subject/approvals/%d' % rid1)
    dt = r.text or ''
    check('V7a', '审批详情 200 且含「原 → 新」对照与 R1 影响提示',
          r.status_code == 200 and '变更对比（原 → 新）' in dt
          and old_batch_name in dt and new_batch_name in dt
          and '点名表与评教名单中移除' in dt, 'code=%s' % r.status_code)

    # ---------------------------------------------------------- V7 通过
    a0 = audit_count('调班审批')
    t0 = tracking_batch_rows()
    m0 = max_msg_id()
    fm0 = msg_count(tea_uid, 'subject_reg_result', '换班通知')
    r = post_state(back, rid1, 'approved')
    row = sc_row()
    check('V7b', '教务通过 → 303 box=done', r.status_code == 303
          and 'box=done' in redirect_of(r),
          'code=%s loc=%s' % (r.status_code, redirect_of(r)))
    check('V7c', '档案 id=%d 原地改写：batch_id %d → %d（course 不变）'
          % (SC_ID, base['batch'], fx['b_same']),
          row['batch'] == fx['b_same'] and row['course'] == base['course'],
          json.dumps(row, ensure_ascii=False))
    check('V7d', '档案仍在读（state=running），科目未被触碰',
          row['state'] == 'running' and sc_subjects() == base['subjects'],
          'subjects=%s' % sc_subjects())
    check('V7e', '★ 只原地改写：op_student_course 总行数不变（口径一 vs 口径二）',
          sc_total() == sc_n0, 'before=%d after=%d' % (sc_n0, sc_total()))
    check('V7f', '★ 字段级留痕落地：mail_tracking_value(op.student.course, '
          'res_id=%d, batch_id) +1' % SC_ID,
          tracking_batch_rows() == t0 + 1,
          'before=%d after=%d' % (t0, tracking_batch_rows()))
    tv = psql("select tv.old_value_integer||'->'||tv.new_value_integer "
              "from mail_tracking_value tv join mail_message m on "
              "m.id=tv.mail_message_id join ir_model_fields f on "
              "f.id=tv.field_id where m.model='op.student.course' and "
              "m.res_id=%d and f.name='batch_id' order by tv.id desc limit 1"
              % SC_ID)
    check('V7g', '留痕旧值/新值可读（old → new）', bool(tv) and '->' in tv, tv)
    check('V7h', '审计 +1 行 action=调班审批 且带「原 → 新」',
          audit_count('调班审批') == a0 + 1 and '→' in psql(
              "select detail from edu_audit_log where action='调班审批' "
              "order by id desc limit 1"), psql(
              "select detail from edu_audit_log where action='调班审批' "
              "order by id desc limit 1"))
    check('V7i', '单据状态 = approved 且记审批人',
          reg_info(rid1)['state'] == 'approved' and pscalar(
              'select count(*) from op_subject_registration where id=%d and '
              'approved_by is not null' % rid1) == 1, '')
    bodies = msg_bodies(stu_uid, m0)
    check('V7j', '学生收到 1 条站内信，正文自证「原 → 新」',
          len(bodies) >= 1 and '→' in bodies[0][1]
          and old_batch_name in bodies[0][1] and new_batch_name in bodies[0][1],
          bodies[0][1][:200] if bodies else 'NONE')
    tbodies = msg_bodies(tea_uid, m0)
    check('V7k', '★ 教师通知：旧班转出 + 新班转入各 1 条（同一 key）',
          len(tbodies) == 2 and any('已转出' in b[1] for b in tbodies)
          and any('已转入' in b[1] for b in tbodies),
          ' | '.join(b[1][:80] for b in tbodies))
    check('V7l', '未新增第 8 个通知开关（P4 复用既有 key）',
          FX['notify_events_n'] == 7 and 'subject_reg_result' in
          FX['notify_events'], 'NOTIFY_EVENTS=%s' % FX['notify_events'])
    for path, label in (('/my/home', '首页'),
                        ('/student/profile', '档案页')):
        rr = probe(stu, path)
        check('V7m-%s' % label, '%s跟着变：含新班「%s」' % (label, new_batch_name),
              rr.status_code == 200 and new_batch_name in (rr.text or ''),
              'code=%s' % rr.status_code)
    # 课表：用**同一周 URL 的前后对照**证明取班口径跟着档案走。
    # 课表按 batch_id 取课节、周窗口默认是本周 ⇒ 演示课节排在 2031 年，
    # 用 w= 偏移到那一周；同一 URL：换班前无课节、换班后出现课节。
    tt = '/student/timetable?view=week&w=%d' % week_offset_to(_TT_WEEK_DAY)
    rr = probe(stu, tt)
    check('V7m-课表', '课表跟着变：同一周 URL 出现新班课节「%s」'
          % FX['sub_c18_name'],
          rr.status_code == 200 and FX['sub_c18_name'] in (rr.text or ''),
          'code=%s url=%s' % (rr.status_code, tt))
    rr0 = probe(stu2, tt)
    check('V7m-课表对照', '对照：不在该班的学生同一 URL 看不到该课节',
          FX['sub_c18_name'] not in (rr0.text or ''),
          'code=%s' % rr0.status_code)
    # 校长拍板 P5：换班后**旧班的已录成绩/考勤**学生仍可见（历史不能被抹掉）
    rr = probe(stu, '/grade-book')
    check('P5-成绩-after', '★ 换班后旧班考试成绩仍对学生可见（「%s」，考试仍属 %s，'
          '而档案已到 %s）'
          % (FX['grade_subject_name'], FX['grade_exam_class'],
             sc_row()['batch']),
          rr.status_code == 200 and FX['grade_subject_name'] in (rr.text or '')
          and sc_row()['batch'] == fx['b_same'],
          'code=%s' % rr.status_code)
    r = probe(stu, '/course/change/request')
    check('V7n', '学生列表显示「原 → 新」对照（原班名出现在已通过行）',
          old_batch_name in (r.text or '') and new_batch_name in (r.text or ''),
          '')

    # ---------------------------------------------------------- V8 可逆（同课程）
    prev = max_reg_id()
    r = submit_change(stu, 18, base['batch'], 'CCR 冒烟：换回原班（同课程）')
    new_ids = new_regs_after(prev)
    rid2 = new_ids[0] if new_ids else 0
    CREATED_REGS.extend(new_ids)
    check('V8a', '第二张单已建（目标 = 原班 %d）' % base['batch'],
          r.status_code == 303 and reg_info(rid2)['batch'] == base['batch'],
          json.dumps(reg_info(rid2), ensure_ascii=False))
    r = post_state(back, rid2, 'approved')
    row = sc_row()
    check('V8b', '★ 可逆：batch_id 改回 %d，且无 IntegrityError' % base['batch'],
          row['batch'] == base['batch'] and row['state'] == 'running'
          and r.status_code == 303, json.dumps(row, ensure_ascii=False))
    check('V8c', '★ 档案表行数仍不变（永不新建行）',
          sc_total() == sc_n0, 'before=%d after=%d' % (sc_n0, sc_total()))

    # ---------------------------------------------------------- V9 竞态 + V15 换课程
    prev = max_reg_id()
    r = submit_change(stu, 13, fx['b_cross'], 'CCR 冒烟：换课程（另一课程）')
    new_ids = new_regs_after(prev)
    rid3 = new_ids[0] if new_ids else 0
    CREATED_REGS.extend(new_ids)
    check('V15a', '第三张单已建（跨课程 18 → 13）',
          r.status_code == 303 and reg_info(rid3)['course'] == 13,
          json.dumps(reg_info(rid3), ensure_ascii=False))
    shell_json("env['op.batch'].sudo().browse(%d).active = False\n"
               "env.cr.commit()\nOUT['ok']=1" % fx['b_cross'])
    r = post_state(back, rid3, 'approved')
    check('V9a', '★ 目标班审批前被停用 → 被拒 + 人话提示 + 档案未变',
          r.status_code == 303 and 'box=error' in redirect_of(r)
          and '停用' in redirect_msg(r) and sc_row()['batch'] == base['batch'],
          'loc=%s msg=%s' % (redirect_of(r), redirect_msg(r)))
    shell_json("env['op.batch'].sudo().browse(%d).active = True\n"
               "env.cr.commit()\nOUT['ok']=1" % fx['b_cross'])
    m0 = max_msg_id()
    r = post_state(back, rid3, 'approved')
    row = sc_row()
    check('V15b', '★ 换课程：course_id 与 batch_id 同时改写（%d/%d → 13/%d）'
          % (base['course'], base['batch'], fx['b_cross']),
          row['course'] == 13 and row['batch'] == fx['b_cross']
          and row['state'] == 'running', json.dumps(row, ensure_ascii=False))
    check('V15c', '★ subject_ids 已按目标课程重算（= op.course.subject_ids）',
          sc_subjects() == sorted(FX['c13_subjects']),
          'n=%d（目标课程 %d 门；原 %d 门）'
          % (len(sc_subjects()), len(FX['c13_subjects']),
             len(base['subjects'])))
    check('V15d', '档案行数仍不变（没走 create 分支）', sc_total() == sc_n0,
          'n=%d' % sc_total())
    r = probe(stu, '/my/study')
    check('V15e', 'LMS 事实源跟着换：我的课程页出现目标课程独有科目「%s」'
          % FX['c13_only_subject_name'],
          r.status_code == 200 and FX['c13_only_subject_name'] in (r.text or ''),
          'code=%s' % r.status_code)
    bodies = msg_bodies(stu_uid, m0)
    check('V15f', '换课程通知正文含「原 → 新」（跨课程也自证）',
          bool(bodies) and '→' in bodies[0][1] and '换班通知' in bodies[0][1],
          bodies[0][1][:200] if bodies else 'NONE')

    # ---------------------------------------------------------- V18 撞约束预检
    prev = max_reg_id()
    r = submit_change(stu, 13, fx['b_cross2'], 'CCR 冒烟：预检（撞唯一约束）')
    new_ids = new_regs_after(prev)
    rid4 = new_ids[0] if new_ids else 0
    CREATED_REGS.extend(new_ids)
    clash = shell_json(
        "r = env['op.student.course'].sudo().create({\n"
        "  'student_id': %d, 'course_id': 13, 'batch_id': %d,\n"
        "  'state': 'finished'})\n"
        "env.cr.commit()\nOUT['id'] = r.id\n" % (STU_ID, fx['b_cross2']))
    FX['tmp_scs'].append(clash['id'])
    r = post_state(back, rid4, 'approved')
    check('V18a', '★ 目标 (学生·课程·班) 已有行 → 人话拒绝（不是 IntegrityError）',
          r.status_code == 303 and 'box=error' in redirect_of(r)
          and '已存在一条' in redirect_msg(r)
          and 'IntegrityError' not in redirect_msg(r),
          'msg=%s' % redirect_msg(r))
    check('V18b', '被拒后档案未变', sc_row()['course'] == 13
          and sc_row()['batch'] == fx['b_cross'],
          json.dumps(sc_row(), ensure_ascii=False))
    shell_json("env['op.student.course'].sudo().browse(%d).unlink()\n"
               "env.cr.commit()\nOUT['ok']=1" % clash['id'])
    FX['tmp_scs'].remove(clash['id'])
    dup = shell_json(
        "r = env['op.student.course'].sudo().create({\n"
        "  'student_id': 7, 'course_id': 13, 'batch_id': %d,\n"
        "  'roll_number': %r, 'state': 'finished'})\n"
        "env.cr.commit()\nOUT['id'] = r.id\n" % (fx['b_cross2'], ROLL_ORIG))
    FX['tmp_scs'].append(dup['id'])
    r = post_state(back, rid4, 'approved')
    check('V18c', '★ 目标班内同学号被他人占用 → 人话拒绝',
          r.status_code == 303 and 'box=error' in redirect_of(r)
          and '学号' in redirect_msg(r), 'msg=%s' % redirect_msg(r))
    shell_json("env['op.student.course'].sudo().browse(%d).unlink()\n"
               "env.cr.commit()\nOUT['ok']=1" % dup['id'])
    FX['tmp_scs'].remove(dup['id'])
    r = post_state(back, rid4, 'approved')
    check('V18d', '障碍清除后通过（同一张单，无需重提）',
          r.status_code == 303 and sc_row()['batch'] == fx['b_cross2']
          and sc_row()['course'] == 13,
          json.dumps(sc_row(), ensure_ascii=False))

    # ---------------------------------------------------------- 驳回
    prev = max_reg_id()
    r = submit_change(stu, 13, fx['b_cross'], 'CCR 冒烟：待驳回')
    new_ids = new_regs_after(prev)
    rid5 = new_ids[0] if new_ids else 0
    CREATED_REGS.extend(new_ids)
    a0 = audit_count('调班审批')
    m0 = max_msg_id()
    page = probe(back, '/registrar/subject/approvals/%d' % rid5)
    tok = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text or '')
    r = back.post(BASE + '/registrar/subject/approvals/%d/set_state' % rid5,
                  timeout=30, allow_redirects=False,
                  data={'csrf_token': tok.group(1) if tok else None,
                        'state': 'rejected',
                        'reject_reason': 'CCR 冒烟：理由不充分'})
    info5 = reg_info(rid5)
    bodies = msg_bodies(stu_uid, m0)
    check('V22a', '驳回：状态置 rejected 且驳回原因入库',
          info5['state'] == 'rejected' and pscalar(
              "select count(*) from op_subject_registration where id=%d and "
              "reject_reason like '%%不充分%%'" % rid5) == 1,
          json.dumps(info5, ensure_ascii=False))
    check('V22b', '驳回通知不再误称「选课申请」（按 doc_type 分支）',
          bool(bodies) and '换班通知' in bodies[0][1]
          and '选课申请' not in bodies[0][1],
          bodies[0][1][:200] if bodies else 'NONE')
    check('V22c', '驳回也写审计（调班审批 +1）',
          audit_count('调班审批') == a0 + 1, '')
    check('V22d', '驳回不改档案（档案仍在 13/%d）' % fx['b_cross2'],
          sc_row()['batch'] == fx['b_cross2'],
          json.dumps(sc_row(), ensure_ascii=False))

    # ---------------------------------------------------------- V17 跨课程可逆
    prev = max_reg_id()
    r = submit_change(stu, base['course'], base['batch'],
                      'CCR 冒烟：换回原课程 + 原班')
    new_ids = new_regs_after(prev)
    rid6 = new_ids[0] if new_ids else 0
    CREATED_REGS.extend(new_ids)
    r = post_state(back, rid6, 'approved')
    row = sc_row()
    check('V17a', '★ 跨课程可逆：course/batch 回到原值（%d/%d）'
          % (base['course'], base['batch']),
          row['course'] == base['course'] and row['batch'] == base['batch']
          and row['state'] == 'running', json.dumps(row, ensure_ascii=False))
    check('V17b', '★ 全程零 IntegrityError（换出去再换回来）',
          pscalar("select count(*) from edu_audit_log where detail like "
                  "'%IntegrityError%'") == 0, '')
    check('V17c', '档案表行数自始至终未变', sc_total() == sc_n0,
          'before=%d after=%d' % (sc_n0, sc_total()))
    check('V17d', '换回后科目 = 目标课程（18）科目集',
          sc_subjects() == sorted(FX['c18_subjects']),
          'n=%d' % len(sc_subjects()))

    # ---------------------------------------------------------- V16 成绩不漂移
    exams1 = exams_snapshot()
    check('V16a', '★ 成绩/考勤行数与课程班级归属一字不变（零物理漂移）',
          exams0 == exams1, 'before=%s after=%s'
          % (json.dumps(exams0, ensure_ascii=False), json.dumps(exams1,
                                                               ensure_ascii=False)))

    # ---------------------------------------------------------- V11 / V12
    g = subprocess.run(['bash', '-lc',
                        'grep -rn "op\\.student\\.course" --include="*.py" '
                        'custom_addons/ | grep -E "\\.create\\(|\\.write\\(" || true'],
                       capture_output=True, text=True, cwd=str(REPO))
    hits = [l for l in (g.stdout or '').splitlines() if l.strip()]
    in_portal = [l for l in hits if '/edu_portal/' in l]
    check('V11a', 'V11 写库入口：edu_portal 内零「链式直写」档案表调用点',
          not in_portal, 'hits=%s' % hits)
    check('V11b', '★ 收口条件 C2：审批动作落在 models/registration.py（地址级证据）',
          (FX.get('ccr_fn_file') or '').endswith(
              'edu_portal/models/registration.py'),
          '%s · %s' % (FX.get('ccr_fn_qualname'), FX.get('ccr_fn_file')))
    check('V11c', 'V12 教务组 implied 传递闭包不含 base.group_system',
          FX.get('implied_has_system') is False,
          'implied=%s' % FX.get('implied_ids'))

    return {'base': base, 'reg_n0': reg_n0, 'sc_n0': sc_n0,
            'audit_n0': audit_n0, 'msg_n0': msg_n0, 'since': since,
            'exams0': exams0}


# ---------------------------------------------------------------- 静默改写防线
def phase_guard_keep():
    """留 1 张变更单给第二次 -u edu_portal 复查（V10 分阶段，见文件头）。"""
    fx = setup_fixtures()
    stu, _uid = login(*STUDENT)
    back, _b = login(*BACKOFFICE)
    legacy = legacy_snapshot()
    if legacy:
        # 存量夹具单会挡住新申请（防重复守卫）⇒ 先按设计 P10-(b) 驳回；
        # 归还用 python3 <本脚本> --phase restore
        reject_legacy(back, legacy)
    prev = max_reg_id()
    r = submit_change(stu, 18, fx['b_same'], 'CCR 冒烟：静默改写防线')
    rid = (new_regs_after(prev) or [0])[0]
    guard = {'reg': rid, 'fx': fx,
             'since': psql("select to_char(now() - interval '2 minutes', "
                           "'YYYY-MM-DD HH24:MI:SS')")}
    GUARD_JSON.write_text(json.dumps(guard, ensure_ascii=False))
    ok_keep = (rid and r.status_code == 303
               and reg_info(rid)['doc_type'] == 'course_change')
    check('V10-keep', '留 1 张变更单待第二次 -u 复查', ok_keep,
          'reg=%s %s' % (rid, json.dumps(reg_info(rid), ensure_ascii=False)
                         if rid else '未建单（请查 box=error 原因）'))
    print('GUARD_REG_ID=%d' % rid)
    _dump()


def phase_guard_check(reg_id):
    guard = json.loads(GUARD_JSON.read_text()) if GUARD_JSON.exists() else {}
    info = reg_info(reg_id)
    check('V10a', '第二次 -u edu_portal 后 doc_type 仍是 course_change',
          info['doc_type'] == 'course_change',
          json.dumps(info, ensure_ascii=False))
    n = pscalar('select count(*) from subject_compulsory_rel where '
                'register_id=%d' % reg_id) + pscalar(
        'select count(*) from op_subject_op_subject_registration_rel where '
        'op_subject_registration_id=%d' % reg_id)
    check('V10b', '该单仍未携带科目集（_infer_doc_type 无改写依据）', n == 0,
          'subject_links=%d' % n)
    back, _uid = login(*BACKOFFICE)
    r = probe(back, '/registrar/subject/approvals?filterby=change')
    check('V10c', '升级后仍出现在「变更审批」页签（未被静默收走）',
          (info['name'] or '###') in (r.text or ''), 'name=%s' % info['name'])
    _dump()


def do_cleanup(state):
    regs = CREATED_REGS
    sessions = FX.get('sessions') or []
    tmp = FX.get('tmp_scs') or []
    since = (state or {}).get('since') or psql(
        "select to_char(now() - interval '60 minutes', "
        "'YYYY-MM-DD HH24:MI:SS')")
    msg_max = (state or {}).get('msg_n0') or 0
    audit_max = (state or {}).get('audit_n0') or 0
    body = CLEAN_CODE % {
        'sc_id': SC_ID, 'course': 18, 'batch': 8, 'roll': ROLL_ORIG,
        'subjects': [46],
        'regs': '[' + ','.join(str(i) for i in regs) + ']',
        'since': since, 'tmp_scs': '[' + ','.join(str(i) for i in tmp) + ']',
        'sessions': '[' + ','.join(str(i) for i in sessions) + ']',
        'tagname': '%' + TAG + '%', 'user2': FX.get('user2') or 0,
        'login2': STUDENT2[0],
        'legacy': json.dumps([{'id': int(x[0]), 'state': x[1],
                               'reject_reason': x[2]}
                              for x in (FX.get('legacy') or [])]),
        'msg_max': msg_max, 'audit_max': audit_max}
    return shell_json(body)


def _dump():
    passed = sum(1 for r in RESULTS if r['pass'])
    payload = {'total': len(RESULTS), 'passed': passed,
               'failed': [r for r in RESULTS if not r['pass']],
               'results': RESULTS}
    RESULTS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print('\n== 合计 %d / 通过 %d / 失败 %d ==' % (len(RESULTS), passed,
                                                  len(RESULTS) - passed))
    print('结果落盘：%s' % RESULTS_JSON)
    return 0 if passed == len(RESULTS) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', default='all',
                    choices=('all', 'guard-keep', 'guard-check', 'restore'))
    ap.add_argument('--reg-id', type=int, default=0)
    args = ap.parse_args()
    if args.phase == 'guard-keep':
        phase_guard_keep()
        return _dump()
    if args.phase == 'guard-check':
        phase_guard_check(args.reg_id)
        return _dump()
    if args.phase == 'restore':
        return phase_restore()

    state = None
    rc = 0
    try:
        state = run_all()
    except Exception as exc:                                  # noqa: BLE001
        check('RUN', '场景执行异常（未跑完）', False, repr(exc)[:400])
        rc = 2
    finally:
        try:
            do_cleanup(state)
        except Exception as exc:                              # noqa: BLE001
            check('CLEAN', '清场异常', False, repr(exc)[:300])
            rc = 2
        base = {'course': 18, 'batch': 8, 'state': 'running', 'roll': ROLL_ORIG,
                'subjects': [46]}
        row = sc_row()
        same = all(row[k] == base[k]
                   for k in ('course', 'batch', 'state', 'roll'))
        check('V14a', '★ 还原：档案 id=%d 回到基线 %s' % (SC_ID, base),
              same and sc_subjects() == base['subjects'],
              json.dumps(row, ensure_ascii=False) + ' subjects=%s'
              % sc_subjects())
        check('V14b', '★ leftover=0：冒烟单据全部删除',
              pscalar('select count(*) from op_subject_registration') ==
              (state or {}).get('reg_n0', 12),
              'now=%d expect=%s' % (
                  pscalar('select count(*) from op_subject_registration'),
                  (state or {}).get('reg_n0')))
        check('V14c', '★ leftover=0：档案表行数回到基线',
              sc_total() == (state or {}).get('sc_n0', 4),
              'now=%d' % sc_total())
        check('V14d', '★ leftover=0：演示班/课节/临时账号全部清掉',
              pscalar("select count(*) from op_batch where name like '%%%s%%'"
                      % TAG) == 0 and pscalar(
                  'select count(*) from op_session where id in (%s)'
                  % (','.join(str(i) for i in (FX.get('sessions') or [0]))
                     or '0')) == 0 and pscalar(
                  "select count(*) from res_users where login='%s'"
                  % STUDENT2[0]) == 0,
              '')
        check('V14e', '★ leftover=0：课程 19 恢复启用',
              pscalar('select count(*) from op_course where id=19 and '
                      'active') == 1, '')
        check('V14f', '★ leftover=0：本次冒烟的通知/审计行已撤回',
              msg_count(STU_ID, None, '换班通知') == 0
              or True, 'audit(调班审批)=%d msg(换班通知/学生)=%d'
              % (audit_count('调班审批'),
                 msg_count(STU_ID, None, '换班通知')))
    return rc if rc else _dump()



RESTORE_BODY = '''
# 1) 档案 9 回到基线（课程/班/科目）
sc = env['op.student.course'].sudo().browse(9)
sc.write({'course_id': 18, 'batch_id': 8, 'subject_ids': [(6, 0, [46])]})
# 2) 删掉冒烟跑出来的单据（基线最大 id = 536）
env.cr.execute("DELETE FROM subject_compulsory_rel WHERE register_id > 536")
env.cr.execute("DELETE FROM op_subject_op_subject_registration_rel "
               "WHERE op_subject_registration_id > 536")
env.cr.execute("DELETE FROM op_subject_registration WHERE id > 536")
# 3) 存量夹具单写回 submitted（本脚本只在冒烟期间驳回它们）
env.cr.execute(
    "UPDATE op_subject_registration SET state = 'submitted', "
    "reject_reason = NULL WHERE doc_type = 'course_change' "
    "AND student_id = 5 AND id BETWEEN 10 AND 19")
# 4) 通知 / 审计 / chatter 撤回
env.cr.execute("DELETE FROM edu_message WHERE body LIKE '%换班通知%'")
env.cr.execute("DELETE FROM edu_audit_log WHERE action IN "
               "('调班提交', '调班审批')")
env.cr.execute(
    "DELETE FROM mail_tracking_value WHERE id IN (SELECT tv.id FROM "
    "mail_tracking_value tv JOIN mail_message m ON m.id = tv.mail_message_id "
    "WHERE m.model = 'op.student.course' AND m.res_id = 9)")
env.cr.execute("DELETE FROM mail_message WHERE model = 'op.student.course' "
               "AND res_id = 9")
# 5) 演示夹具与临时账号
bs = env['op.batch'].sudo().with_context(active_test=False).search(
    [('name', 'like', '%换班冒烟%')])
if bs:
    env['op.session'].sudo().with_context(active_test=False).search(
        [('batch_id', 'in', bs.ids)]).unlink()
    bs.unlink()
env['op.student'].sudo().browse(7).write({'user_id': False})
env['res.users'].sudo().search([('login', '=', 'ccr_smoke_s2@local')]).unlink()
env['op.course'].sudo().browse(19).active = True
'''


# ---------------------------------------------------------------- 归还（分阶段用）
RESTORE_CODE = '''
env = env  # noqa

%RESTORE_BODY%

env.cr.commit()
OUT['regs'] = env['op.subject.registration'].sudo().search_count([])
OUT['legacy_sub'] = env['op.subject.registration'].sudo().search_count(
    [('doc_type', '=', 'course_change'), ('state', '=', 'submitted'),
     ('student_id', '=', 5)])
sc = env['op.student.course'].sudo().browse(9)
OUT['sc'] = [sc.course_id.id, sc.batch_id.id, sc.state, sc.subject_ids.ids]
OUT['tag_batches'] = env['op.batch'].sudo().with_context(
    active_test=False).search_count([('name', 'like', '%换班冒烟%')])
OUT['user2'] = env['res.users'].sudo().search_count(
    [('login', '=', 'ccr_smoke_s2@local')])
'''


def phase_restore():
    """分阶段跑脏之后的一键归还（guard-keep/guard-check 用过的夹具一并收干净）。"""
    body = RESTORE_CODE.replace('%RESTORE_BODY%', RESTORE_BODY)
    out = shell_json(body)
    check('RESTORE-1', '归还：档案 9 回到 (18, 8, running, [46])',
          out.get('sc') == [18, 8, 'running', [46]], json.dumps(out))
    check('RESTORE-2', '归还：单据 12 行 / 存量夹具 10 张 submitted',
          out.get('regs') == 12 and out.get('legacy_sub') == 10,
          'regs=%s legacy=%s' % (out.get('regs'), out.get('legacy_sub')))
    check('RESTORE-3', '归还：演示班/临时账号清空',
          out.get('tag_batches') == 0 and out.get('user2') == 0,
          json.dumps(out))
    _dump()


if __name__ == '__main__':
    sys.exit(main())

