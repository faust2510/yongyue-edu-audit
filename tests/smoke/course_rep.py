#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""课代表真机冒烟（六步闸门第 6 步）：7 条负向 + 正向验收。

设计稿：docs/plans/course-representative-design.md（§7 负向 N1-N9 / 正向 P1-P8）
用法：python3 tests/smoke/course_rep.py             # 全量（含夹具清理）
      python3 tests/smoke/course_rep.py --keep      # 保留夹具（排查用）
结果落盘：tests/smoke/course_rep_results.json

判据红线（照 class_change_request.py 的既定口径）
- 探测**不跟随重定向**（allow_redirects=False），判 303 必须看首跳；
- 不只断言「页面 200 / 有横幅」——要看库里的行与字段；
- 「不能批自己 / 不能批非本课程」的判据是 **写库效果 = 0**（state 仍 request、
  approver_kind 仍 NULL），不是「按钮被禁用」；
- 夹具自带标签、自带清理，leftover 必须 = 0（跑完复查，非 0 即 FAIL）。
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

BASE = os.environ.get('CREP_BASE', 'http://localhost:8069')
DB = os.environ.get('EDU_DB_NAME', 'edu19')
DB_CONTAINER = os.environ.get('EDU_DB_CONTAINER', 'edu19-clone-db-1')
REPO = Path(__file__).resolve().parent.parent.parent
RESULTS_JSON = (Path(__file__).resolve().parent
                / 'course_rep_results.json')
LOCK = os.path.join(os.environ.get('TMPDIR') or '/tmp', 'edu19_upgrade.lock')

TAG = '【演示】课代表冒烟'
ADMIN = ('crep_admin@local', 'demo123')      # base.group_system => admin
REGISTRAR = ('backoffice@local', 'demo123')  # op_back_office_admin => registrar
TEACHER = ('faculty@local', 'demo123')       # op_faculty => faculty
REP = ('crep_rep@local', 'demo123')          # 课代表（学生）
MATE = ('crep_mate@local', 'demo123')        # 同课程同学（非课代表）
OUTSIDER = ('crep_out@local', 'demo123')     # 另一门课的学生（非本课程）

RESULTS = []
FX = {}


def check(no, name, ok, detail=''):
    RESULTS.append({'no': no, 'name': name, 'pass': bool(ok),
                    'detail': str(detail)[:900]})
    print('  [%s] %-14s %s%s' % ('PASS' if ok else 'FAIL', no, name,
                                 (' | ' + str(detail)[:400]) if detail else ''))
    return bool(ok)


def note(msg):
    print('  ---- %s' % msg)


# ---------------------------------------------------------------- 工具
def psql(sql, want_err=False):
    out = subprocess.run(['docker', 'exec', DB_CONTAINER, 'psql', '-U', 'odoo',
                          '-d', DB, '-tAc', sql],
                         capture_output=True, text=True, timeout=180)
    if out.returncode != 0 and not want_err:
        raise RuntimeError('psql 失败：' + (out.stderr or '').strip()[:300])
    return (out.stdout or '').strip(), (out.stderr or '').strip()


def pscalar(sql):
    return int(psql(sql)[0] or 0)


def ptext(sql):
    return psql(sql)[0]


def shell(code, timeout=600):
    cmd = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
           '-c', '/etc/odoo/odoo.conf', '--db_host=db', '--db_port=5432',
           '--db_user=odoo', '--db_password=odoo', '-d', DB, '--no-http']
    out = subprocess.run(cmd, input=code, capture_output=True, text=True,
                         timeout=timeout, cwd=str(REPO))
    return (out.stdout or '') + (out.stderr or '')


def shell_json(body, timeout=600):
    # ⚠ 一律用 chr(10) 拼换行：本文件里出现真的换行会把 odoo shell 的 stdin 拆断
    NL = chr(10)
    head = 'import json' + NL + 'OUT = {}' + NL
    tail = (NL + "print('@@CREPJ@@' + json.dumps("
            "OUT, ensure_ascii=False, default=str))" + NL)
    blob = shell(head + body + tail, timeout)
    m = re.search(r'@@CREPJ@@(.*)', blob)
    if not m:
        Path('/tmp/crep_shell_fail.txt').write_text(blob)
        raise RuntimeError('odoo shell 未返回 JSON（完整输出 /tmp/crep_shell_fail.txt）：'
                           + blob[-1200:])
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


def probe(sess, path, data=None, method='GET'):
    """**不跟随重定向**的探测（判 303 必须看首跳）。"""
    if method == 'GET':
        return sess.get(BASE + path, timeout=40, allow_redirects=False)
    return sess.post(BASE + path, data=data, timeout=40,
                     allow_redirects=False)


def csrf_of(sess, path):
    r = probe(sess, path)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text or '')
    return m.group(1) if m else None


def follow(sess, path):
    """跟随重定向取最终页面（用于「页面上看不看得见」这类断言）。"""
    r = sess.get(BASE + path, timeout=40, allow_redirects=True)
    return r.status_code, (r.text or '')


def loc(resp):
    return resp.headers.get('Location') or ''


def sql_lit(s):
    return "'" + str(s).replace("'", "''") + "'"


def max_id(table):
    return pscalar('select coalesce(max(id),0) from ' + table)


def msg_count(uid, event_key=None):
    dom = 'recipient_id=%d' % uid
    if event_key:
        dom += ' and event_key=%s' % sql_lit(event_key)
    return pscalar('select count(*) from edu_message where %s' % dom)


def msg_bodies(uid, after_id):
    # ⚠ string_agg 与 ORDER BY 必须写在聚合里（外层 order by 会报 42803）
    rows = ptext("select coalesce(string_agg(id::text || '|' || "
                 "replace(body, chr(10), ' / '), chr(10) order by id), '') "
                 "from edu_message where recipient_id=%d and id > %d"
                 % (uid, after_id))
    return [r for r in rows.splitlines() if r.strip()]


def audit_count(action, model=None, res_id=None):
    dom = 'action=%s' % sql_lit(action)
    if model:
        dom += ' and model=%s' % sql_lit(model)
    if res_id is not None:
        dom += ' and res_id=%d' % res_id
    return pscalar('select count(*) from edu_audit_log where %s' % dom)


def leave_row(lid):
    row = ptext("select coalesce(state,'-'), coalesce(approver_kind,'NULL'), "
                "coalesce(approver_id::text,'NULL'), coalesce(subject_id::text,'NULL'), "
                "coalesce(leave_type,'-'), coalesce(name,'-') "
                "from edu_leave where id=%d" % lid)
    p = [x.strip() for x in row.split('|')]
    return {'state': p[0], 'kind': p[1], 'approver': p[2], 'subject': p[3],
            'type': p[4], 'name': p[5]}


def rep_row(subject_id):
    row = ptext("select coalesce(id::text,'-'), coalesce(state,'-'), "
                "coalesce(student_id::text,'NULL'), coalesce(expires_at::text,'NULL'), "
                "coalesce(deadline_source,'-') from edu_course_rep "
                "where subject_id=%d" % subject_id)
    if not row:
        return None
    p = [x.strip() for x in row.split('|')]
    return {'id': int(p[0]), 'state': p[1],
            'student': None if p[2] == 'NULL' else int(p[2]),
            'expires_at': p[3], 'source': p[4]}


def rep_count(subject_id):
    return pscalar('select count(*) from edu_course_rep where subject_id=%d'
                   % subject_id)


def att_line_count(student_id):
    return pscalar('select count(*) from op_attendance_line where student_id=%d'
                   % student_id)


def sheets_for(batch_id, adate):
    return pscalar("select count(*) from op_attendance_sheet where batch_id=%d "
                   "and attendance_date=%s" % (batch_id, sql_lit(adate)))


def sheet_row(sid):
    row = ptext("select coalesce(state,'-'), coalesce(submitted_by_rep_id::text,'NULL'), "
                "coalesce(rep_subject_id::text,'NULL'), "
                "coalesce(rep_submitted_at::text,'NULL'), "
                "coalesce(rep_proposal,'NULL') from op_attendance_sheet "
                "where id=%d" % sid)
    if not row:
        return None
    p = [x.strip() for x in row.split('|')]
    return {'state': p[0], 'rep': p[1], 'subject': p[2], 'at': p[3],
            'proposal': p[4]}


def queue_has(html, lid):
    """该假单是否出现在课代表队列里：以**处置表单的隐藏 leave_id** 为准。

    ⚠ 不能用「单号是否出现在 HTML 里」当判据 —— 课代表面板的队列表**不显示
    单号**，那种写法是恒真（永远 PASS）的假绿。
    """
    return ('name="leave_id" value="%d"' % lid) in html


def extract_rows(html, cls):
    """抽出所有 class 含 cls 的元素文本（QWeb 会丢弃注释节点，故用 class 锚点）。"""
    pat = re.compile(r'<[a-z]+[^>]*class="[^"]*\b' + cls + r'\b[^"]*"[^>]*>(.*?)</[a-z]+>',
                     re.S)
    return [re.sub(r'<[^>]+>', ' ', m.group(1)) for m in pat.finditer(html)]


def new_leaves(after_id):
    rows = ptext('select id from edu_leave where id > %d order by id' % after_id)
    return [int(x) for x in rows.split() if x.strip()]


# ================================================================ 夹具
PURGE_FN = '''
def purge_all(env, tag):
    """按标签清场（幂等）：科目/课代表槽位/点名表/课节/登记簿/作业/学生/账号。
    ⚠ 只按夹具标签与夹具 id 反查，**不按 max(id) 猜**（本会话已有代理因此误删他人夹具）。"""
    S = env['op.subject'].sudo().with_context(active_test=False)
    subs = S.search([('name', 'like', tag + '%')])
    sub_ids = subs.ids
    reps = env['edu.course.rep'].sudo().with_context(active_test=False).search(
        [('subject_id', 'in', sub_ids or [0])])
    rep_ids = reps.ids
    sheets = env['op.attendance.sheet'].sudo().with_context(active_test=False).search(
        [('rep_subject_id', 'in', sub_ids or [0])])
    sheet_ids = sheets.ids
    if sheet_ids:
        env['op.attendance.line'].sudo().with_context(active_test=False).search(
            [('attendance_id', 'in', sheet_ids)]).unlink()
        sheets.unlink()
    B = env['op.batch'].sudo().with_context(active_test=False)
    batches = B.search([('name', 'like', tag + '%')])
    b_ids = batches.ids
    if b_ids:
        env['op.session'].sudo().with_context(active_test=False).search(
            [('batch_id', 'in', b_ids)]).unlink()
        # ⚠ 顺序（2026-09-21 实测踩坑）：点名学生行 → 点名表 → **最后**才是登记簿。
        #   op_attendance_sheet.register_id 是普通外键（无 ondelete=cascade），先删登记簿必然
        #   ForeignKeyViolation（教师侧那张普通点名表还在库里时）→ 清场中断 → leftover != 0。
        #   同批次的点名表 id 一并并进 sheet_ids：它们的审计行（考勤录入/考勤确认）在下面
        #   按 sheet_ids 清，漏掉就是留脏档。
        b_sheets = env['op.attendance.sheet'].sudo().with_context(
            active_test=False).search([('batch_id', 'in', b_ids)])
        if b_sheets:
            env['op.attendance.line'].sudo().with_context(active_test=False).search(
                [('attendance_id', 'in', b_sheets.ids)]).unlink()
            sheet_ids = sorted(set(sheet_ids) | set(b_sheets.ids))
            b_sheets.unlink()
        env['op.attendance.register'].sudo().with_context(active_test=False).search(
            [('batch_id', 'in', b_ids)]).unlink()
    asg = env['op.assignment'].sudo().with_context(active_test=False).search(
        [('description', '=', tag)])
    gas = asg.mapped('grading_assignment_id')
    if asg:
        # ⚠ 必须先删提交行：op_assignment_sub_line.assignment_id 是普通外键
        # （无 ondelete=cascade），直接 unlink 作业会撞 FK 约束。
        env['op.assignment.sub.line'].sudo().with_context(
            active_test=False).search([('assignment_id', 'in', asg.ids)]).unlink()
    asg.unlink()
    gas.unlink()
    env['grading.assignment.type'].sudo().search(
        [('code', 'like', 'CREP-%')]).unlink()
    studs = env['op.student'].sudo().with_context(active_test=False).search(
        [('name', 'like', tag + '%')])
    stu_ids = studs.ids
    uids = studs.mapped('user_id').ids
    if stu_ids:
        env['op.student.course'].sudo().with_context(active_test=False).search(
            [('student_id', 'in', stu_ids)]).unlink()
    leaves = env['edu.leave'].sudo().with_context(active_test=False).search(
        ['|', ('subject_id', 'in', sub_ids or [0]),
         ('student_id', 'in', stu_ids or [0])])
    leaf_ids = leaves.ids
    leaves.unlink()
    if rep_ids:
        env['edu.audit.log'].sudo().search(
            [('model', '=', 'edu.course.rep'), ('res_id', 'in', rep_ids)]).unlink()
    if sheet_ids:
        env['edu.audit.log'].sudo().search(
            [('model', '=', 'op.attendance.sheet'),
             ('res_id', 'in', sheet_ids)]).unlink()
    if leaf_ids:
        env['edu.audit.log'].sudo().search(
            [('model', '=', 'edu.leave'), ('res_id', 'in', leaf_ids)]).unlink()
    if sub_ids:
        env['edu.audit.log'].sudo().search(
            [('model', '=', 'op.subject'), ('res_id', 'in', sub_ids)]).unlink()
    U = env['res.users'].sudo().with_context(active_test=False)
    fusers = U.search([('login', 'like', 'crep_%')]) | U.browse(uids).exists()
    fuids = fusers.ids
    if fuids:
        env['edu.message'].sudo().search(
            ['|', ('recipient_id', 'in', fuids), ('sender_id', 'in', fuids)]).unlink()
        fusers.unlink()
    if stu_ids:
        studs.unlink()
    P = env['res.partner'].sudo().with_context(active_test=False)
    fp = P.search([('name', 'like', tag + '%')])
    if fp:
        fp.unlink()
    if b_ids:
        batches.unlink()
    if sub_ids:
        subs.unlink()
    env.cr.commit()
    return {'rep_ids': rep_ids, 'sheet_ids': sheet_ids, 'leaf_ids': leaf_ids,
            'sub_ids': sub_ids, 'b_ids': b_ids, 'stu_ids': stu_ids}


def mk_user(env, login, name, groups):
    U = env['res.users'].sudo().with_context(active_test=False)
    old = U.search([('login', '=', login)])
    if old:
        old.partner_id.unlink()
    p = env['res.partner'].sudo().create({'name': name})
    u = env['res.users'].sudo().create(
        {'name': name, 'login': login, 'password': 'demo123',
         'partner_id': p.id, 'group_ids': [(6, 0, groups)]})
    return u, p
'''

SETUP_CODE = PURGE_FN + '''
env = env  # noqa
TAG = '__TAG__'
purge_all(env, TAG)
portal = env.ref('base.group_portal').id
system = env.ref('base.group_system').id

rep_u, rep_p = mk_user(env, '__REP__', TAG + '甲（课代表）', [portal])
mate_u, mate_p = mk_user(env, '__MATE__', TAG + '乙（同学）', [portal])
out_u, out_p = mk_user(env, '__OUT__', TAG + '丙（外课）', [portal])
adm_u, adm_p = mk_user(env, '__ADMIN__', TAG + '管理员', [system])
cap_p = env['res.partner'].sudo().create({'name': TAG + '丁（无班）'})
us = {'rep': rep_u.id, 'mate': mate_u.id, 'out': out_u.id, 'admin': adm_u.id}

sub_a = env['op.subject'].sudo().create(
    {'name': TAG + '科目A', 'code': 'CREP-A', 'type': 'theory',
     'subject_type': 'compulsory'})
sub_b = env['op.subject'].sudo().create(
    {'name': TAG + '科目B', 'code': 'CREP-B', 'type': 'theory',
     'subject_type': 'compulsory'})
batch = env['op.batch'].sudo().create(
    {'name': TAG + '班', 'code': 'CREP-BATCH', 'course_id': 18,
     'start_date': '2026-03-01', 'end_date': '2027-07-01'})
SC = env['op.student.course'].sudo()
rep = env['op.student'].sudo().create(
    {'name': TAG + '甲（课代表）', 'partner_id': rep_p.id, 'user_id': rep_u.id})
mate = env['op.student'].sudo().create(
    {'name': TAG + '乙（同学）', 'partner_id': mate_p.id, 'user_id': mate_u.id})
out = env['op.student'].sudo().create(
    {'name': TAG + '丙（外课）', 'partner_id': out_p.id, 'user_id': out_u.id})
cap_stu = env['op.student'].sudo().create(
    {'name': TAG + '丁（无班）', 'partner_id': cap_p.id})
# 戊：只在科目B、且**无班级档案**（P7「空值兜底 ⇒ deadline_source=cap」的载体；
# 不能借用丁：科目A 已有一位课代表，UNIQUE(subject_id) 只允许一个槽位）
cap2_p = env['res.partner'].sudo().create({'name': TAG + '戊（B课无班）'})
cap2_stu = env['op.student'].sudo().create(
    {'name': TAG + '戊（B课无班）', 'partner_id': cap2_p.id})
sc_rep = SC.create({'student_id': rep.id, 'course_id': 18, 'batch_id': batch.id,
                    'state': 'running', 'academic_term_id': 1,
                    'subject_ids': [(6, 0, [sub_a.id])]})
sc_mate = SC.create({'student_id': mate.id, 'course_id': 18, 'batch_id': batch.id,
                     'state': 'running', 'academic_term_id': 1,
                     'subject_ids': [(6, 0, [sub_a.id])]})
sc_out = SC.create({'student_id': out.id, 'course_id': 18, 'batch_id': batch.id,
                    'state': 'running', 'academic_term_id': 1,
                    'subject_ids': [(6, 0, [sub_b.id])]})
sc_cap = SC.create({'student_id': cap_stu.id, 'course_id': 18,
                    'state': 'running', 'subject_ids': [(6, 0, [sub_a.id])]})
sc_cap2 = SC.create({'student_id': cap2_stu.id, 'course_id': 18,
                     'state': 'running', 'subject_ids': [(6, 0, [sub_b.id])]})
sess = env['op.session'].sudo().create(
    {'course_id': 18, 'batch_id': batch.id, 'subject_id': sub_a.id,
     'faculty_id': 17, 'start_datetime': '2032-01-05 08:00:00',
     'end_datetime': '2032-01-05 10:00:00'})
at = env['grading.assignment.type'].sudo().search([], limit=1)
if not at:
    at = env['grading.assignment.type'].sudo().create(
        {'name': TAG + '作业类型', 'code': 'CREP-AT'})
ga = env['grading.assignment'].sudo().create(
    {'name': TAG + '作业', 'course_id': 18, 'subject_id': sub_a.id,
     'issued_date': '2032-01-05 08:00:00', 'assignment_type': at.id,
     'faculty_id': 17})
asg = env['op.assignment'].sudo().create(
    {'grading_assignment_id': ga.id, 'batch_id': batch.id,
     'description': TAG, 'submission_date': '2032-01-10 23:59:59',
     'state': 'publish', 'courses_subjects': [(6, 0, [sub_a.id])],
     'allocation_ids': [(6, 0, [rep.id, mate.id, cap_stu.id])]})
sub = env['op.assignment.sub.line'].sudo().create(
    {'assignment_id': asg.id, 'student_id': mate.id,
     'submission_date': '2032-01-08 10:00:00'})
env.cr.commit()

OUT['sub_a'] = sub_a.id
OUT['sub_b'] = sub_b.id
OUT['batch'] = batch.id
OUT['rep'] = rep.id
OUT['mate'] = mate.id
OUT['out'] = out.id
OUT['cap_stu'] = cap_stu.id
OUT['cap2_stu'] = cap2_stu.id
OUT['users'] = us
OUT['sess'] = sess.id
OUT['asg'] = asg.id
OUT['sc'] = {'rep': sc_rep.id, 'mate': sc_mate.id, 'out': sc_out.id,
             'cap': sc_cap.id, 'cap2': sc_cap2.id}
OUT['names'] = {'rep': rep.name, 'mate': mate.name, 'out': out.name,
                'cap': cap_stu.name, 'cap2': cap2_stu.name}
OUT['notify_events'] = [k for k, _l in __import__(
    'odoo.addons.edu_portal.models.notify_pref',
    fromlist=['NOTIFY_EVENTS']).NOTIFY_EVENTS]
env.cr.commit()
'''

CLEAN_CODE = PURGE_FN + '''
env = env  # noqa
OUT['purged'] = purge_all(env, '__TAG__')
env.cr.commit()
'''


def _fill(code):
    """token 替换（**不用 %-格式化**：夹具代码里有 like 'crep_%' 这类裸百分号）。"""
    return (code.replace('__TAG__', TAG)
            .replace('__REP__', REP[0]).replace('__MATE__', MATE[0])
            .replace('__OUT__', OUTSIDER[0]).replace('__ADMIN__', ADMIN[0]))


def setup_fixtures():
    return shell_json(_fill(SETUP_CODE))


def cleanup_fixtures():
    try:
        return shell_json(_fill(CLEAN_CODE))
    except Exception as exc:
        print('  !! 清场失败：%s' % str(exc)[:300])
        return {}


def appoint(subject_id, student_id):
    """走模型动作（后台「任命」按钮同一条路径），返回槽位 id/期限/来源。"""
    return shell_json(
        "s = env['op.subject'].sudo().browse(%d)\n"
        "st = env['op.student'].sudo().browse(%d)\n"
        "slot = env['edu.course.rep'].sudo().appoint(s, st)\n"
        "env.cr.commit()\n"
        "OUT['id'] = slot.id\n"
        "OUT['state'] = slot.state\n"
        "OUT['expires'] = str(slot.expires_at)\n"
        "OUT['source'] = slot.deadline_source\n"
        "OUT['realtime'] = str(slot.deadline_realtime())\n" % (subject_id,
                                                                student_id))


def run_cron():
    return shell_json("OUT['n'] = env['edu.course.rep'].sudo()._cron_expire()\n"
                      "env.cr.commit()\n")


def set_param(key, value):
    return shell_json("p = env['ir.config_parameter'].sudo()\n"
                      "p.set_param(%r, %r)\n"
                      "env.cr.commit()\nOUT['ok'] = 1\n" % (key, value))


def set_batch_end(batch_id, adate):
    return shell_json("env['op.batch'].sudo().browse(%d).write({'end_date': %r})\n"
                      "env.cr.commit()\nOUT['ok'] = 1\n" % (batch_id, adate))


def submit_leave(sess, leave_type, date_from, date_to, reason, subject_id=''):
    """真机走 /my/time_off/save（学生提交请假的唯一入口）。"""
    token = csrf_of(sess, '/my/time_off')
    return probe(sess, '/my/time_off/save', method='POST', data={
        'csrf_token': token, 'leave_type': leave_type,
        'date_from': date_from, 'date_to': date_to, 'reason': reason,
        'subject_id': subject_id})


# ⚠ 请假夹具的日期与时长（S5 收口，2026-09-24）—— 两条新规则把原来的夹具打红过：
#   ① 条例一·2「严禁事后补假」（设计稿 §7.5）：门户 /my/time_off/save 对
#      date_from < 提交日**硬拒且不落库**（实测 HTTP 422）。本文件原来写死的
#      2026-06-xx 全在过去 ⇒ 建单直接失败（首个落点 IndexError，整脚本崩）。
#      这些日期只是夹具参数、与任何断言无关 ⇒ 改成「今天 + n 天」现算。
#   ② 条例二·3「病假 ≥2 天必须提交证明」（设计稿 §7.2）：sick 夹具原来有 2 天的，
#      且不带证明字段 ⇒ 缩成 **1 天**（不放宽任何断言：这些用例测的是「角色/流程」
#      —— 课代表可批/不可批、队列可见性、留痕与通知，天数只是附带参数）。
#      新规则本身由 tests/smoke/leave_split_approval.py 的 **A12** 专门覆盖
#      （2 天病假无证明 ⇒ 拒绝；1 天 ⇒ 放行；口头证明 ⇒ 放行并留确认人）。
LV_TODAY = datetime.date.today()


def lvdate(days):
    """请假夹具日期：今天 + days 天（保证不触发「事后补假」硬拒）。"""
    return (LV_TODAY + datetime.timedelta(days=days)).isoformat()


def set_homeroom(batch_id, uid):
    """给夹具班填「班主任」（= 设计稿 §3.3 的「老师到位后只填数据即生效」那条路径）。

    ⚠ 为什么必须填（S5 收口，2026-09-24）：请假分级审批落地后，「谁该批」由**提交时
    快照**决定（设计稿 §3.2 + §8.1：`user == first_approver_id or privileged_staff()`）。
    本夹具的班原来**没有班主任** ⇒ 一级应批人 = 教务处组 ∪ 系统组，而普通教师
    （op_faculty）既不在那个集合里、又不是快照本人 ⇒ 他 POST /leave/set_state 被
    **fail-closed 挡住**（N2e / P4-faculty 因此红）。这是设计行为，不是缺陷：
    §3.3「没有班主任 ⇒ 直接落教务处」与 §4.3(2)「转交后原审批人不能再批」是
    **同一条判据**。本脚本要测的仍然是「老师 / 教务 / 管理员**各自单独**也能批」⇒
    给夹具班填上「班主任 = faculty@local」，老师就成为本班假单的一级应批人，
    三条断言（N2e / P4-faculty / P4d）**一字未改**，只是让被授权的身份真的被授权。
    反过来说：**没有**这条夹具时，它证明的是「无班主任时教师批不动」（A3 路线），
    那由 tests/smoke/leave_split_approval.py 的 A2/A3 覆盖。
    """
    return shell_json("b = env['op.batch'].sudo().browse(%d)\n"
                      "b.write({'homeroom_teacher_id': %d})\n"
                      "env.cr.commit()\n"
                      "OUT['now'] = b.homeroom_teacher_id.id or 0" % (batch_id, uid))


def post_rep(sess, subject_id, suffix, data, token_path=None):
    # ⚠ token 必须从**该会话能打开**的页面取：非课代表打不开课代表面板
    #   （303 无 body ⇒ token 取到 None ⇒ 一律 400，会把"挡住了"伪装成"探测坏了"）。
    #   /my/time_off 是任何学生都能打开的页面，用它取 token（同会话通用）。
    token = csrf_of(sess, token_path or '/my/time_off')
    payload = {'csrf_token': token}
    payload.update(data)
    return probe(sess, '/my/courses/%d/rep/%s' % (subject_id, suffix),
                 method='POST', data=payload)


# ================================================================ 主流程
SELF_LEAVE_NAME = []
DATES = {'rep_att': '2026-06-01', 'teacher_att': '2026-06-02'}


def baseline():
    return {
        'msg': max_id('edu_message'),
        'audit': max_id('edu_audit_log'),
        'leave': max_id('edu_leave'),
        'sheet': max_id('op_attendance_sheet'),
        'line': max_id('op_attendance_line'),
        'rep_n': pscalar('select count(*) from edu_course_rep'),
        'leave_n': pscalar('select count(*) from edu_leave'),
        'sheet_n': pscalar('select count(*) from op_attendance_sheet'),
    }


def run_all():
    # ---------------------------------------------------------- C00 前置
    check('C00a', '无升级锁（串行口径）', not os.path.exists(LOCK), LOCK)
    # 本机 web 会被别人的 safe_upgrade 重启，502 是瞬时态 ⇒ 最多等 90 秒
    # 本机 web 会被别人的 safe_upgrade 重启（502 是瞬时态）⇒ 最多等 5 分钟
    import time
    code, tries = 0, 0
    # ⚠ 本机 macOS 的**系统代理**会被 requests 的 trust_env 自动采用（本机实测：
    #   裸 requests.get → 502；Session(trust_env=False) → 302）。本文件其余所有
    #   探测都走 login() 建的 trust_env=False 会话，只有这里漏了 ⇒ 它会稳定报 502、
    #   白等 100×3 秒，把「探活探不到」伪装成「站点没起来」。与 min 口径对齐即可。
    _probe = requests.Session()
    _probe.trust_env = False
    for tries in range(1, 101):
        try:
            code = _probe.get(BASE + '/web/login?db=' + DB, timeout=20,
                              allow_redirects=False).status_code
        except Exception:
            code = 0
        if code in (200, 302, 303):
            break
        time.sleep(3)
    check('C00b', 'web 就绪（带库名登录页）', code in (200, 302, 303),
          'code=%s tries=%d' % (code, tries))

    base = baseline()
    fx = setup_fixtures()
    FX.update(fx)
    note('夹具：科目A=%s 科目B=%s 班=%s 学生 甲/乙/丙/丁=%s/%s/%s/%s'
         % (fx['sub_a'], fx['sub_b'], fx['batch'], fx['rep'], fx['mate'],
            fx['out'], fx['cap_stu']))
    sub_a, sub_b = fx['sub_a'], fx['sub_b']
    batch = fx['batch']
    batch_name = ptext('select name from op_batch where id=%d' % batch)

    rep_s, rep_uid = login(*REP)
    mate_s, mate_uid = login(*MATE)
    out_s, out_uid = login(*OUTSIDER)
    tea_s, tea_uid = login(*TEACHER)
    reg_s, reg_uid = login(*REGISTRAR)
    adm_s, adm_uid = login(*ADMIN)
    check('F01', '六个账号均可登录（课代表/同学/外课/任课老师/教务/管理员）',
          all([rep_uid, mate_uid, out_uid, tea_uid, reg_uid, adm_uid]),
          'uid=%s' % [rep_uid, mate_uid, out_uid, tea_uid, reg_uid, adm_uid])

    # ---------------------------------------------------------- 载体合法
    sc_a = ptext('select count(*) from op_student_course_op_subject_rel r '
                 'join op_student_course sc on sc.id = r.op_student_course_id '
                 'where sc.student_id in (%d, %d) and r.op_subject_id = %d'
                 % (fx['rep'], fx['mate'], sub_a))
    check('F02', '载体合法：甲/乙在科目A、丙只在科目B',
          int(sc_a or 0) >= 2 and pscalar(
              'select count(*) from op_student_course_op_subject_rel r '
              'join op_student_course sc on sc.id = r.op_student_course_id '
              'where sc.student_id = %d and r.op_subject_id = %d'
              % (fx['out'], sub_b)) == 1,
          'A 行数=%s' % sc_a)
    check('F03', '载体合法：任课老师（faculty@local → op.faculty 17）任教夹具班',
          pscalar('select count(*) from op_session where batch_id=%d and '
                  'faculty_id=17' % batch) == 1, 'batch=%d' % batch)

    # ============================================================ N1
    r = probe(mate_s, '/my/courses/%d/rep' % sub_a)
    check('N1a', 'N1 非课代表 GET 面板 → 303 回 /my/courses',
          r.status_code == 303 and loc(r).endswith('/my/courses'),
          'code=%s loc=%s' % (r.status_code, loc(r)))
    m0 = max_id('edu_message')
    r = post_rep(mate_s, sub_a, 'notify', {'body': 'CREP 越权探测'})
    check('N1b', 'N1 非课代表 POST 发通知 → 0 条新站内信',
          r.status_code == 303 and max_id('edu_message') == m0,
          'code=%s new_msg=%d' % (r.status_code, max_id('edu_message') - m0))
    r = post_rep(mate_s, sub_a, 'release', {})
    check('N1c', 'N1 非课代表 POST 辞去 → 无槽位、无写',
          r.status_code == 303 and rep_count(sub_a) == 0,
          'code=%s rows=%d' % (r.status_code, rep_count(sub_a)))
    s0 = max_id('op_attendance_sheet')
    r = post_rep(mate_s, sub_a, 'attendance', {'date': DATES['rep_att']})
    check('N1d', 'N1 非课代表 POST 点名 → 未新建点名表',
          r.status_code == 303 and max_id('op_attendance_sheet') == s0,
          'code=%s new_sheet=%d' % (r.status_code,
                                    max_id('op_attendance_sheet') - s0))
    r = probe(out_s, '/my/courses/%d/rep' % sub_a)
    check('N1e', 'N1 外课学生（连本科学生都不是）GET 面板 → 303',
          r.status_code == 303, 'code=%s loc=%s' % (r.status_code, loc(r)))
    st, html = follow(mate_s, '/my/courses')
    # ⚠ 判据用徽标的**专属标记**（title 属性），不能只 grep 三个字 ——
    #   夹具名字里就含「课代表」，否则会自证式误判。
    BADGE = '你是本课程的课代表'
    check('N1f', 'N1 非课代表「我的课程」页无课代表徽标',
          st == 200 and BADGE not in html,
          'code=%s badge=%s' % (st, BADGE in html))

    # ============================================================ P0 任命
    a0 = audit_count('课代表任命')
    m0 = max_id('edu_message')
    slot = appoint(sub_a, fx['rep'])
    FX['slot_a'] = slot['id']
    check('P0a', '教务任命 → 槽位 active、留痕「课代表任命」+1',
          slot['state'] == 'active' and audit_count('课代表任命') == a0 + 1,
          'slot=%s state=%s audit=%d' % (slot['id'], slot['state'],
                                         audit_count('课代表任命')))
    bodies = msg_bodies(rep_uid, m0)
    check('P0b', '被任命学生收到站内信（event_key=course_rep_appointed）',
          msg_count(rep_uid, 'course_rep_appointed') >= 1 and bool(bodies),
          'n=%d' % len(bodies))
    st, html = follow(rep_s, '/my/courses')
    st2, html2 = follow(mate_s, '/my/courses')
    check('P0c', '「我的课程」徽标只给本人在任的课（本人有、同学无）',
          BADGE in html and BADGE not in html2,
          'rep_page=%s mate_page=%s' % (BADGE in html, BADGE in html2))
    r = probe(rep_s, '/my/courses/%d/rep' % sub_a)
    check('P0d', '在任课代表 GET 面板 → 200',
          r.status_code == 200 and fx['names']['mate'] in (r.text or ''),
          'code=%s' % r.status_code)
    slot_b = shell_json(
        "s = env['op.subject'].sudo().browse(%d)\n"
        "st = env['op.student'].sudo().browse(%d)\n"
        "env['edu.course.rep'].sudo().create({'subject_id': s.id,"
        " 'student_id': st.id})\n"
        "rec = env['edu.course.rep'].sudo().search([('subject_id', '=', s.id)])\n"
        "rec.action_appoint()\n"
        "env.cr.commit()\n"
        "OUT['state'] = rec.state\n"
        "OUT['source'] = rec.deadline_source\n"
        "OUT['expires'] = str(rec.expires_at)\n"
        "OUT['realtime'] = str(rec.deadline_realtime())\n"
        % (sub_b, fx['cap2_stu']))
    FX['slot_b'] = rep_row(sub_b)['id'] if rep_row(sub_b) else 0
    check('P0e', '后台「任命」按钮同一条方法路径可用（action_appoint）',
          slot_b['state'] == 'active', str(slot_b))

    # ⚠ S5：把夹具班的「班主任」填成任课老师 —— 否则普通教师不是本班假单的一级
    #   应批人，N2e / P4-faculty / P4d 会因新授权判据被 fail-closed 挡住（见
    #   set_homeroom 的 docstring：这是设计行为，夹具要跟上，断言不动）。
    hr = set_homeroom(batch, tea_uid)
    check('HR0', '夹具班已设「班主任 = faculty@local」（分级审批的一级应批人前提）',
          hr.get('now') == tea_uid, 'homeroom=%s expect=%s' % (hr.get('now'), tea_uid))

    # ============================================================ N2 批不了自己
    # ⚠ 1 天（原 2026-06-10~11 = 2 天，且日期在过去）：见 lvdate 上方注释。
    submit_leave(rep_s, 'sick', lvdate(1), lvdate(1),
                 'CREP 课代表自己的假单', sub_a)
    lid_self = new_leaves(base['leave'])[-1]
    FX['lid_self'] = lid_self
    self_name = leave_row(lid_self)['name']
    # 对照单：同学的**同课程出勤类**假单 —— 它必须在同一个队列里看得见，
    # 才能证明「自己的单不出现」是针对自己的过滤，而不是队列坏了。
    # ⚠ 1 天 + 未来日期（同上）；它证明「过滤是针对自己」这一点一字未改。
    submit_leave(mate_s, 'sick', lvdate(1), lvdate(1),
                 'CREP 对照单（同学，应出现在队列）', sub_a)
    lid_peer0 = new_leaves(base['leave'])[-1]
    st, html = follow(rep_s, '/my/courses/%d/rep' % sub_a)
    check('N2a', 'N2 自己的假单不进课代表队列（队列里没有它的处置表单）',
          bool(lid_self) and not queue_has(html, lid_self),
          'lid_self=%s in_queue=%s' % (lid_self, queue_has(html, lid_self)))
    check('N2b', 'N2 前端根本不渲染该单（三层防御第②层：不是禁用按钮）；'
          '对照单在队列里 ⇒ 过滤是针对自己',
          queue_has(html, lid_peer0) and not queue_has(html, lid_self),
          'peer_in_queue=%s self_in_queue=%s'
          % (queue_has(html, lid_peer0), queue_has(html, lid_self)))
    r0 = leave_row(lid_self)
    r = post_rep(rep_s, sub_a, 'leave/set_state',
                 {'leave_id': lid_self, 'state': 'approved'})
    r1 = leave_row(lid_self)
    check('N2c', 'N2 直接 POST 通过自己的假单 → 不写任何字段',
          r.status_code == 303 and r1['state'] == 'request'
          and r1['kind'] == 'NULL' and r1['approver'] == 'NULL',
          'code=%s state=%s→%s kind=%s' % (r.status_code, r0['state'],
                                           r1['state'], r1['kind']))
    st, html = follow(tea_s, '/leave/approvals')
    check('N2d', 'N2 该单仍在教师 /leave/approvals 队列（没被顺手吞掉）',
          st == 200 and self_name in html, 'code=%s' % st)
    tok = csrf_of(tea_s, '/leave/approvals')
    r = probe(tea_s, '/leave/set_state', method='POST', data={
        'csrf_token': tok, 'leave_id': lid_self, 'state': 'approved'})
    r2 = leave_row(lid_self)
    check('N2e', 'N2 老师批它 → 成功且 approver_kind 不是 student_rep',
          r.status_code == 303 and r2['state'] == 'approved'
          and r2['kind'] not in ('NULL', 'student_rep'),
          'state=%s kind=%s' % (r2['state'], r2['kind']))

    # ============================================================ N4 / N5 数据
    # out（只在科目B）提交 sick + 科目B；mate 提交 legal/other + 科目A；mate 提交无课程假单
    submit_leave(out_s, 'sick', lvdate(2), lvdate(2),
                 'CREP 外课学生的假单', sub_b)
    submit_leave(mate_s, 'legal', lvdate(3), lvdate(3),
                 'CREP 法定假（非出勤类）', sub_a)
    submit_leave(mate_s, 'other', lvdate(4), lvdate(4),
                 'CREP 其他（非出勤类）', sub_a)
    submit_leave(mate_s, 'sick', lvdate(5), lvdate(5),
                 'CREP 未指定课程的假单', '')
    lids = new_leaves(base['leave'])
    FX['lids'] = lids
    def by_reason(text):
        for lid in lids:
            if text in ptext('select coalesce(reason, \'\') from edu_leave where id=%d' % lid):
                return lid
        return 0
    lid_out = by_reason('外课学生')
    lid_legal = by_reason('法定假')
    lid_other = by_reason('其他')
    lid_nosub = by_reason('未指定课程')
    check('F04', 'N4/N5 夹具齐备（外课单/法定假/其他/无课程单）',
          all([lid_out, lid_legal, lid_other, lid_nosub]),
          'ids=%s' % [lid_out, lid_legal, lid_other, lid_nosub])
    st, html = follow(rep_s, '/my/courses/%d/rep' % sub_a)
    check('N4a', 'N4 只在科目B的假单不进科目A课代表队列',
          not queue_has(html, lid_out), 'lid=%s in_queue=%s'
          % (lid_out, queue_has(html, lid_out)))
    r = post_rep(rep_s, sub_a, 'leave/set_state',
                 {'leave_id': lid_out, 'state': 'approved'})
    rw = leave_row(lid_out)
    check('N4b', 'N4 直接 POST 跨课程审批 → 不写任何字段',
          r.status_code == 303 and rw['state'] == 'request'
          and rw['kind'] == 'NULL',
          'code=%s state=%s kind=%s' % (r.status_code, rw['state'], rw['kind']))
    check('N4c', 'N4 subject_id 为空 → fail-closed（不进队列、POST 不写）',
          not queue_has(html, lid_nosub)
          and leave_row(lid_nosub)['subject'] == 'NULL',
          'in_queue=%s subject=%s' % (queue_has(html, lid_nosub),
                                      leave_row(lid_nosub)['subject']))
    r = post_rep(rep_s, sub_a, 'leave/set_state',
                 {'leave_id': lid_nosub, 'state': 'approved'})
    rw = leave_row(lid_nosub)
    check('N4d', 'N4 空课程单直接 POST → 不写字段（state=%s kind=%s）'
          % (rw['state'], rw['kind']),
          r.status_code == 303 and rw['state'] == 'request'
          and rw['kind'] == 'NULL',
          'code=%s' % r.status_code)
    check('N5a', 'N5 法定假（legal）不进课代表队列',
          not queue_has(html, lid_legal), 'in_queue=%s' % queue_has(html, lid_legal))
    check('N5b', 'N5 其他（other）不进课代表队列',
          not queue_has(html, lid_other), 'in_queue=%s' % queue_has(html, lid_other))
    r = post_rep(rep_s, sub_a, 'leave/set_state',
                 {'leave_id': lid_legal, 'state': 'approved'})
    rw = leave_row(lid_legal)
    check('N5c', 'N5 直接 POST 批法定假 → 不写字段',
          r.status_code == 303 and rw['state'] == 'request'
          and rw['kind'] == 'NULL',
          'state=%s kind=%s' % (rw['state'], rw['kind']))

    # ============================================================ P3 批同学的本课程出勤类假单
    # ⚠ 1 天（原 06-20~21 = 2 天病假需证明）+ 未来日期：见 lvdate 上方注释。
    submit_leave(mate_s, 'sick', lvdate(6), lvdate(6),
                 'CREP 同学的本课程病假（应可被课代表批）', sub_a)
    lid_peer = new_leaves(base['leave'])[-1]
    FX['lid_peer'] = lid_peer
    st, html = follow(rep_s, '/my/courses/%d/rep' % sub_a)
    check('P3a', 'P3 本课程出勤类假单进课代表队列（有它的处置表单）',
          queue_has(html, lid_peer), 'lid=%s in_queue=%s'
          % (lid_peer, queue_has(html, lid_peer)))
    a0 = audit_count('请假审批(课代表)')
    a_teacher0 = audit_count('请假审批')
    m0 = max_id('edu_message')
    r = post_rep(rep_s, sub_a, 'leave/set_state',
                 {'leave_id': lid_peer, 'state': 'approved'})
    rw = leave_row(lid_peer)
    check('P3b', 'P3 课代表通过 → state=approved / approver_kind=student_rep / 审批人=课代表账号',
          r.status_code == 303 and rw['state'] == 'approved'
          and rw['kind'] == 'student_rep' and rw['approver'] == str(rep_uid),
          'code=%s %s' % (r.status_code, json.dumps(rw, ensure_ascii=False)))
    check('P3c', 'P3 审计动作名独立：请假审批(课代表) +1，老师口径 请假审批 未+1',
          audit_count('请假审批(课代表)') == a0 + 1
          and audit_count('请假审批') == a_teacher0,
          'rep_audit=%d teacher_audit=%d' % (audit_count('请假审批(课代表)'),
                                             audit_count('请假审批')))
    bodies = msg_bodies(int(FX['users']['mate']), m0)
    check('P3d', 'P3 申请人收到 leave_result 站内信',
          bool(bodies) and '已通过' in bodies[0],
          bodies[0][:120] if bodies else 'NONE')
    st, html = follow(tea_s, '/leave/approvals/%d' % lid_peer)
    check('P3e', 'P3 单据页面显示「由课代表 X 审批」（需求⑥逐字）',
          st == 200 and ('由课代表 %s 审批' % fx['names']['rep']) in html,
          'code=%s 含课代表文案=%s' % (st, '由课代表' in html))

    # ============================================================ P4 老师/教务/管理员任一都能单独批
    for i in range(3):
        submit_leave(mate_s, 'sick', lvdate(7 + i), lvdate(7 + i),
                     'CREP P4 审批人身份 #%d' % i, sub_a)
    p4 = new_leaves(base['leave'])[-3:]
    for sess, uid, label in ((tea_s, tea_uid, 'faculty'),
                             (reg_s, reg_uid, 'registrar'),
                             (adm_s, adm_uid, 'admin')):
        tok = csrf_of(sess, '/leave/approvals')
        probe(sess, '/leave/set_state', method='POST', data={
            'csrf_token': tok, 'leave_id': p4[0], 'state': 'approved'})
        rw = leave_row(p4[0])
        check('P4-%s' % label, 'P4 %s 可单独批（不串行等待）→ kind=%s'
              % (label, rw['kind']),
              rw['state'] == 'approved' and rw['kind'] == label
              and rw['approver'] == str(uid),
              json.dumps(rw, ensure_ascii=False))
        p4 = p4[1:]
    st, html = follow(tea_s, '/leave/approvals')
    check('P4d', 'P4 三种身份都记了审批人（faculty / registrar / admin 各一行）',
          pscalar("select count(distinct approver_kind) from edu_leave "
                  "where approver_kind in ('faculty','registrar','admin')") == 3,
          'kinds=%s' % ptext("select string_agg(distinct approver_kind, ',') "
                            "from edu_leave where approver_kind is not null"))

    # ============================================================ P1 名单只姓名+班级
    st, html = follow(rep_s, '/my/courses/%d/rep' % sub_a)
    rows = extract_rows(html, 'cr-roster-row')
    roster_txt = ' | '.join(rows)
    check('P1a', 'P1 面板 200 且同学名单每行=姓名+班级',
          st == 200 and len(rows) >= 3
          and any(fx['names']['mate'] in x and batch_name in x for x in rows)
          and any(fx['names']['cap'] in x for x in rows),
          'code=%s 行数=%d 例=%s' % (st, len(rows), rows[:2]))
    forbidden = [w for w in ('@', '学号', '手机', '成绩', '财务', '身份证')
                 if w in roster_txt]
    check('P1b', 'P1 名单行只有姓名+班级（无邮箱/学号/手机/成绩/财务/身份证）',
          not forbidden and len(rows) >= 3, '名单行内命中禁词=%s' % forbidden)
    check('P1c', 'P1 名单行不含生日等敏感事实',
          '生日' not in roster_txt and 'roll' not in roster_txt.lower(), 'ok')

    # ============================================================ P2 发通知
    m0 = max_id('edu_message')
    a0 = audit_count('课代表发通知')
    r = post_rep(rep_s, sub_a, 'notify',
                 {'body': 'CREP 课代表通知：明天课前交作业'})
    mate_new = max_id('edu_message') - m0
    check('P2a', 'P2 发通知 → 本课程同学各 1 条、课代表自己 0 条',
          r.status_code == 303 and mate_new >= 1
          and msg_count(rep_uid, 'course_rep_notice') == 0
          and msg_count(int(FX['users']['mate']), 'course_rep_notice') >= 1,
          'new=%d rep_self=%d mate=%d'
          % (mate_new, msg_count(rep_uid, 'course_rep_notice'),
             msg_count(int(FX['users']['mate']), 'course_rep_notice')))
    check('P2b', 'P2 审计「课代表发通知」+1',
          audit_count('课代表发通知') == a0 + 1,
          'before=%d after=%d' % (a0, audit_count('课代表发通知')))
    st, html = follow(mate_s, '/my/notify')
    check('P2c', 'P2 /my/notify 偏好页能看到「课代表通知」开关（已登记 NOTIFY_EVENTS）',
          st == 200 and '课代表通知' in html,
          'code=%s events=%s' % (st, ','.join(fx['notify_events'])))

    # ============================================================ P6 作业统计（不给名单）
    st, ph = follow(rep_s, '/my/courses/%d/rep' % sub_a)
    stats = extract_rows(ph, 'cr-assign-stat')
    asg_txt = ' | '.join(x.strip() for x in stats)
    check('P6a', 'P6 作业只给「还有几人没交」统计（应交 3 / 已交 1 / 还有 2 人没交）',
          bool(stats) and '还有' in asg_txt and '2' in asg_txt and '3' in asg_txt,
          asg_txt[:220])
    leak = [n for n in (fx['names']['rep'], fx['names']['mate'],
                        fx['names']['cap'], fx['names']['cap2'])
            if n in asg_txt]
    check('P6b', 'P6 统计区里 grep 不到任何学生姓名（0 命中）',
          not leak, '泄漏命中=%s | 统计区=%s' % (leak, asg_txt[:120]))

    # ============================================================ P5 / N8 / N9 点名（待老师确认）
    d_rep = DATES['rep_att']
    line0 = att_line_count(fx['mate'])
    m0 = max_id('edu_message')
    r = post_rep(rep_s, sub_a, 'attendance', {
        'date': d_rep,
        'status_%d' % fx['mate']: 'absent',
        'status_%d' % fx['cap_stu']: 'present'})
    sid = int(ptext('select coalesce(max(id),0) from op_attendance_sheet '
                    'where batch_id=%d and attendance_date=%s'
                    % (batch, sql_lit(d_rep))) or 0)
    FX['sheet_rep'] = sid
    row = sheet_row(sid) or {}
    check('P5a', 'P5 课代表提交点名 → 停在 state=start 且带提交人/科目/时刻',
          r.status_code == 303 and row.get('state') == 'start'
          and row.get('rep') == str(FX['slot_a'])
          and row.get('subject') == str(sub_a)
          and row.get('at') not in ('NULL', None),
          'code=%s %s' % (r.status_code, json.dumps(row, ensure_ascii=False)))
    check('N8a', 'N8 未确认前考勤统计一字不变（op.attendance.line 未新增）',
          att_line_count(fx['mate']) == line0 and 'absent' in (row.get('proposal') or ''),
          'before=%d after=%d' % (line0, att_line_count(fx['mate'])))
    st, html = follow(tea_s, '/attendance/take?batch_id=%d&date=%s'
                      % (batch, d_rep))
    check('P5b', '★ P5b 老师能在 /attendance/take 看见「待确认」入口 + 提交人',
          st == 200 and '课代表已提交待确认点名' in html
          and fx['names']['rep'] in html,
          'code=%s 含待确认块=%s' % (st, '课代表已提交待确认点名' in html))
    check('P5c', 'P5c 任课老师收到 attendance_rep_submitted 站内信',
          msg_count(int(FX['users']['rep'])) >= 0
          and pscalar("select count(*) from edu_message where event_key="
                      "'attendance_rep_submitted' and id > %d" % m0) >= 1,
          'new=%d' % pscalar("select count(*) from edu_message where "
                             "event_key='attendance_rep_submitted' and id > %d"
                             % m0))
    tok = csrf_of(rep_s, '/my/courses/%d/rep' % sub_a)
    r = probe(rep_s, '/attendance/confirm_rep_sheet', method='POST',
              data={'csrf_token': tok, 'sheet_id': sid})
    check('N8b', 'N8 课代表无法自行确认（POST 老师路由 → state 仍 start）',
          r.status_code == 303 and (sheet_row(sid) or {}).get('state') == 'start',
          'code=%s state=%s' % (r.status_code, (sheet_row(sid) or {}).get('state')))
    tok = csrf_of(tea_s, '/attendance/take?batch_id=%d&date=%s' % (batch, d_rep))
    a0 = pscalar("select count(*) from edu_audit_log where action='考勤确认'")
    r = probe(tea_s, '/attendance/confirm_rep_sheet', method='POST',
              data={'csrf_token': tok, 'sheet_id': sid})
    check('P5b2', 'P5b 老师一键确认 → state=done + 考勤行落地（统计此刻才变）',
          r.status_code == 303 and (sheet_row(sid) or {}).get('state') == 'done'
          and att_line_count(fx['mate']) == line0 + 1
          and pscalar("select count(*) from edu_audit_log where "
                      "action='考勤确认'") == a0 + 1,
          'code=%s state=%s lines=%d' % (r.status_code,
                                         (sheet_row(sid) or {}).get('state'),
                                         att_line_count(fx['mate'])))
    r = post_rep(rep_s, sub_a, 'attendance', {'date': d_rep})
    check('N9a', 'N9 已确认后再提交同一天 → 不覆盖、仍只有 1 张表',
          sheets_for(batch, d_rep) == 1
          and (sheet_row(sid) or {}).get('state') == 'done'
          and 'att_locked' in loc(r),
          'code=%s loc=%s sheets=%d' % (r.status_code, loc(r),
                                        sheets_for(batch, d_rep)))
    tok = csrf_of(tea_s, '/attendance/take?batch_id=%d&date=%s' % (batch, d_rep))
    r = probe(tea_s, '/attendance/save', method='POST', data={
        'csrf_token': tok, 'batch_id': batch, 'course_id': 18, 'date': d_rep,
        'status_%d' % fx['mate']: 'present'})
    check('N9b', 'N9 老师再录同一天 → 命中既有 dup 分支（不产生第二张表）',
          r.status_code == 303 and 'dup=1' in loc(r)
          and ('dup_sheet=%d' % sid) in loc(r)
          and sheets_for(batch, d_rep) == 1,
          'code=%s loc=%s' % (r.status_code, loc(r)))
    d_tea = DATES['teacher_att']
    # ⚠ P5d 的**前置**必须显式断言出来，否则这条判据看起来比它实际证明的多：
    #   教师侧 /attendance/save 只在「该 (course,batch) **已有**登记簿」时才走得通。
    #   全新 (course,batch) 上它在建簿处必炸（roles.py:556-561 传了不存在的
    #   start_date/end_date ⇒ ValueError: Invalid field；就算删掉那两个参数，
    #   还漏传 required+unique 的 code ⇒ NOT NULL 违约）。两处建簿点
    #   （roles.py:556 / :2467）同上。2026-09-21 真机 odoo shell 实测：
    #     教师式 create → ValueError: Invalid field 'start_date' in 'op.attendance.register'
    #     补 code + 去掉假字段 → CREATED-OK。
    #   这是**既有缺陷**：attendance_save 在 149cab8^ 与 HEAD 逐字相同（课代表提交
    #   一行都没碰它），建簿块自初始快照 9ac86b9 起就在、448d8b4 重写 t7 时也没补 code。
    #   ⇒ 与课代表无关，已单独立项，**不要**在本用例里顺手改教师侧既有路径。
    #   本夹具的登记簿是课代表路径先建好的（P5a 已建、且带 code）⇒ P5d 走的是教师侧
    #   既有正常分支；该分支自课代表改动起一字未改，故 P5d 足以证「零回归」。
    n_reg = pscalar('select count(*) from op_attendance_register where '
                    'batch_id=%d and course_id=18' % batch)
    check('P5d-pre', 'P5d 前置：该 (course,batch) 已由课代表路径建好登记簿 ⇒ '
          'P5d 验的是教师侧既有正常分支（既存缺陷 d6df39e 已修，见 P5f）',
          n_reg == 1, 'registers=%d' % n_reg)
    tok = csrf_of(tea_s, '/attendance/take?batch_id=%d&date=%s' % (batch, d_tea))
    n0 = sheets_for(batch, d_tea)
    r = probe(tea_s, '/attendance/save', method='POST', data={
        'csrf_token': tok, 'batch_id': batch, 'course_id': 18, 'date': d_tea,
        'status_%d' % fx['mate']: 'present',
        'status_%d' % fx['rep']: 'present'})
    check('P5d', 'P5d 教师侧零回归：普通点名仍照旧新建（保存成功回跳 saved=1 —— '
          '旧的「空白页」是既存缺陷，已由 d6df39e 修，见 P5f）',
          r.status_code == 303 and 'saved=1' in loc(r)
          and sheets_for(batch, d_tea) == n0 + 1,
          'code=%s loc=%s sheets %d→%d' % (r.status_code, loc(r), n0,
                                           sheets_for(batch, d_tea)))
    t_ids = ptext('select id::text from op_attendance_sheet where batch_id=%d '
                  'and attendance_date=%s' % (batch, sql_lit(d_tea)))
    t_row = sheet_row(int(t_ids)) if t_ids else {}
    check('P5d2', 'P5d 教师侧新建的表不带课代表字段（_inherit 只加字段：不参与唯一性、'
          '也不污染既有路径）',
          t_row.get('rep') == 'NULL' and t_row.get('subject') == 'NULL'
          and t_row.get('at') == 'NULL' and t_row.get('proposal') == 'NULL',
          json.dumps(t_row, ensure_ascii=False))
    reg_code = ptext('select coalesce(code, chr(45)) from op_attendance_register '
                     'where batch_id=%d' % batch)
    check('P5f', 'P5f 课代表侧建的考勤登记簿带 code（op.attendance.register.code '
          '是 required+unique）。注：教师侧两处建簿点原传不存在的 start_date/end_date '
          '且漏传 code ⇒ 全新 (course,batch) 上必 500；该既存缺陷已于 d6df39e 修复，'
          'P5d 现已按修复后的 303+saved=1 断言）',
          bool(reg_code) and reg_code != '-', 'code=%s' % reg_code)

    # ============================================================ N6 数据库级唯一
    out, err = psql("insert into edu_course_rep (subject_id, state, active, "
                    "create_uid, write_uid) values (%d, 'vacant', true, 1, 1)"
                    % sub_a, want_err=True)
    check('N6a', 'N6 SQL 直插同一 subject 第二行 → 被数据库唯一约束拒绝',
          'duplicate key value violates unique constraint' in err
          or 'duplicate key' in err,
          (err or out)[:220])
    dupres = shell_json(
        "import psycopg2\n"
        "try:\n"
        "    env['edu.course.rep'].sudo().create({'subject_id': %d, "
        "'student_id': %d})\n"
        "    env.cr.commit()\n"
        "    OUT['exc'] = 'NO-ERROR'\n"
        "except Exception as e:\n"
        "    env.cr.rollback()\n"
        "    OUT['exc'] = type(e).__name__\n"
        "    OUT['msg'] = str(e)[:200]\n" % (sub_a, fx['mate']))
    check('N6b', 'N6 ORM 建第二行 → 抛唯一约束异常（不是代码 if 拦截）',
          dupres.get('exc') not in (None, 'NO-ERROR', 'UserError'),
          json.dumps(dupres, ensure_ascii=False))
    n_dup = pscalar('select count(*) from (select subject_id from '
                    'edu_course_rep group by subject_id having count(*) > 1) t')
    check('N6c', 'N6 每科目槽位数恒为 1（HAVING count(*)>1 → 0 行）', n_dup == 0,
          'dup_subjects=%d' % n_dup)
    con = ptext("select pg_get_constraintdef(oid) from pg_constraint where "
                "conrelid = 'edu_course_rep'::regclass and contype = 'u'")
    check('N6d', 'N6 结构核对：库里真有 UNIQUE (subject_id)', con == 'UNIQUE (subject_id)',
          con)

    # ============================================================ N7 归还 / 不能指定继承人
    fields = shell_json("OUT['f'] = sorted(env['edu.course.rep']._fields.keys())\n")
    fset = set(fields['f'])
    bad = [f for f in fset if any(k in f for k in
                                  ('successor', 'inherit', 'heir', 'next_rep',
                                   'delegate', 'transfer', 'nominee', 'handover'))]
    # 结构证据（不看注释/docstring：那里本来就会写「无提名/转交」这类说明文字）
    g = subprocess.run(['grep', '-nE', r"^\s*@http\.route\('/my/courses/<int:"
                        r"subject_id>/rep", 'custom_addons/edu_portal/controllers/lms.py'],
                       capture_output=True, text=True, cwd=str(REPO))
    PREFIX = 'my/courses/<int:subject_id>'
    routes = sorted({m.group(1).split(PREFIX, 1)[-1] for m in re.finditer(
        r"/(my/courses/<int:subject_id>/rep[^'\"]*)", g.stdout or '')})
    allowed = {'/rep', '/rep/notify', '/rep/leave/set_state', '/rep/attendance',
               '/rep/release'}
    extra = [r for r in routes if r not in allowed]
    check('N7a', 'N7 结构证据：课代表路由**只有** 5 条（无提名/指定/转交入口）',
          not bad and not extra and len(routes) == 5,
          '模型可疑字段=%s 路由=%s 多余=%s' % (bad, routes, extra))
    a0 = audit_count('课代表归还')
    r = post_rep(rep_s, sub_a, 'release', {})
    row = rep_row(sub_a)
    check('N7b', 'N7 辞去课代表 → state=vacant、保留上一任、留痕「课代表归还」+1',
          r.status_code == 303 and row['state'] == 'vacant'
          and row['student'] == fx['rep'] and audit_count('课代表归还') == a0 + 1,
          'code=%s %s' % (r.status_code, json.dumps(row, ensure_ascii=False)))
    r = probe(rep_s, '/my/courses/%d/rep' % sub_a)
    st, html = follow(rep_s, '/my/courses')
    check('N7c', 'N7 归还后立刻失效：面板 303 + 徽标消失',
          r.status_code == 303 and BADGE not in html,
          'panel=%s badge=%s' % (r.status_code, BADGE in html))
    submit_leave(mate_s, 'sick', lvdate(10), lvdate(10),
                 'CREP 归还后的待批单', sub_a)
    lid_after = new_leaves(base['leave'])[-1]
    m0 = max_id('edu_message')
    r1 = post_rep(rep_s, sub_a, 'notify', {'body': 'CREP 归还后越权探测'})
    r2 = post_rep(rep_s, sub_a, 'leave/set_state',
                  {'leave_id': lid_after, 'state': 'approved'})
    rw = leave_row(lid_after)
    check('N7d', 'N7 归还后 POST 发通知/批假 → 写库效果 0',
          r1.status_code == 303 and r2.status_code == 303
          and max_id('edu_message') == m0 and rw['state'] == 'request'
          and rw['kind'] == 'NULL',
          'msg_new=%d state=%s kind=%s' % (max_id('edu_message') - m0,
                                           rw['state'], rw['kind']))
    appoint(sub_a, fx['mate'])
    check('N7e', 'N7 教务任命下一人 → 槽位仍只有 1 行（槽位复用，不新建行）',
          rep_count(sub_a) == 1 and rep_row(sub_a)['student'] == fx['mate'],
          'rows=%d student=%s' % (rep_count(sub_a), rep_row(sub_a)['student']))
    rpc = mate_s.post(BASE + '/web/dataset/call_kw', timeout=30, json={
        'jsonrpc': '2.0', 'method': 'call',
        'params': {'model': 'edu.course.rep', 'method': 'write',
                   'args': [[FX['slot_a']], {'student_id': fx['out']}],
                   'kwargs': {}}})
    try:
        errname = ((rpc.json() or {}).get('error') or {}).get(
            'data', {}).get('name') or 'NONE'
    except Exception:
        errname = 'PARSE-FAIL'
    check('N7f', 'N7 学生无法经 RPC 直写课代表表（门户无 ACL，只能走控制器 sudo）',
          errname in ('AccessError', 'odoo.exceptions.AccessError')
          and rep_row(sub_a)['student'] == fx['mate'],
          'rpc_error=%s student_now=%s' % (errname, rep_row(sub_a)['student']))

    # ============================================================ N3 到期真的失效（cron 未跑）
    appoint(sub_a, fx['rep'])
    FX['slot_a'] = rep_row(sub_a)['id']
    check('N3-pre', 'N3 前置：课代表重新在任（面板 200）',
          probe(rep_s, '/my/courses/%d/rep' % sub_a).status_code == 200, '')
    yesterday = (datetime.date.today()
                 - datetime.timedelta(days=1)).isoformat()
    past = (datetime.date.today()
            - datetime.timedelta(days=60)).isoformat()
    set_param('edu_portal.course_rep_grace_days', '0')
    set_batch_end(batch, past)
    rt = shell_json(
        "r = env['edu.course.rep'].sudo().browse(%d)\n"
        "OUT['realtime'] = str(r.deadline_realtime())\n"
        "OUT['stored'] = str(r.expires_at)\n"
        "OUT['source'] = r.deadline_source\n" % FX['slot_a'])
    check('N3a', 'N3 期限实时重算到过去（班结课日 60 天前 + grace=0）',
          rt['realtime'] == past and rt['realtime'] < yesterday,
          json.dumps(rt, ensure_ascii=False))
    check('N3b', '★ N3 【cron 未跑】权限已失效：面板 GET → 303',
          probe(rep_s, '/my/courses/%d/rep' % sub_a).status_code == 303,
          'state_in_db=%s' % (rep_row(sub_a) or {}).get('state'))
    st, html = follow(rep_s, '/my/courses')
    check('N3c', '★ N3 【cron 未跑】徽标消失（实时判定，不靠 cron 改 state）',
          BADGE not in html, 'badge=%s' % (BADGE in html))
    check('N3d', 'N3 【cron 未跑】库里 state 仍是 active（证明权限失效不依赖 cron）',
          (rep_row(sub_a) or {}).get('state') == 'active',
          'state=%s' % (rep_row(sub_a) or {}).get('state'))
    submit_leave(mate_s, 'sick', lvdate(11), lvdate(11),
                 'CREP 过期后的待批单', sub_a)
    lid_exp = new_leaves(base['leave'])[-1]
    r = post_rep(rep_s, sub_a, 'leave/set_state',
                 {'leave_id': lid_exp, 'state': 'approved'})
    rw = leave_row(lid_exp)
    check('N3e', '★ N3 【cron 未跑】到期后审批写库效果 0',
          r.status_code == 303 and rw['state'] == 'request'
          and rw['kind'] == 'NULL',
          'code=%s %s' % (r.status_code, json.dumps(rw, ensure_ascii=False)))
    a0 = audit_count('课代表到期失效')
    m0 = max_id('edu_message')
    cron = run_cron()
    row = rep_row(sub_a)
    check('N3f', 'N3 跑 cron → 收口写 expired + 留痕 + 通知学生',
          row['state'] == 'expired' and audit_count('课代表到期失效') == a0 + 1
          and pscalar("select count(*) from edu_message where "
                      "event_key='course_rep_expired' and id > %d" % m0) >= 1,
          'cron_returned=%s state=%s audit=%d'
          % (cron.get('n'), row['state'], audit_count('课代表到期失效')))
    set_param('edu_portal.course_rep_grace_days', '30')
    set_batch_end(batch, '2027-07-01')
    check('N3g', 'N3 参数/日期已还原（夹具自治）',
          ptext("select value from ir_config_parameter where key="
                "'edu_portal.course_rep_grace_days'") == '30'
          and ptext('select end_date::text from op_batch where id=%d'
                    % batch) == '2027-07-01', '')

    # ============================================================ P7 空值兜底 / P8 宽限期实时
    check('P7a', 'P7 空值兜底：该生在本课程无班级档案 ⇒ 期限来源=cap（不是空、不是永久）',
          slot_b.get('source') == 'cap' and slot_b.get('expires') not in ('False', '', None),
          json.dumps(slot_b, ensure_ascii=False))
    exp_cap = (datetime.date.today()
               + datetime.timedelta(days=180)).isoformat()
    check('P7b', 'P7 期限 = 任命日 + 180 天（默认硬上限）',
          str(slot_b.get('expires')) == exp_cap,
          'expires=%s expect=%s' % (slot_b.get('expires'), exp_cap))
    shell_json("env['op.student.course'].sudo().browse(%d).write("
               "{'academic_term_id': False})\n"
               "env['op.batch'].sudo().browse(%d).write("
               "{'end_date': '2026-12-01'})\n"
               "env.cr.commit()\nOUT['ok'] = 1\n" % (fx['sc']['rep'], batch))
    appoint(sub_a, fx['rep'])
    p8a = shell_json(
        "r = env['edu.course.rep'].sudo().search([('subject_id', '=', %d)])\n"
        "OUT['rt'] = str(r.deadline_realtime())\n"
        "OUT['stored'] = str(r.expires_at)\n"
        "OUT['src'] = r.deadline_source\n" % sub_a)
    set_param('edu_portal.course_rep_grace_days', '0')
    p8b = shell_json(
        "r = env['edu.course.rep'].sudo().search([('subject_id', '=', %d)])\n"
        "OUT['rt'] = str(r.deadline_realtime())\n"
        "OUT['stored'] = str(r.expires_at)\n" % sub_a)
    gap = (datetime.date(2026, 12, 31) - datetime.date(2026, 12, 1)).days
    check('P8a', 'P8 宽限期参数实时生效：30→0 让期限当场提前 %d 天' % gap,
          p8a['rt'] == '2026-12-31' and p8b['rt'] == '2026-12-01',
          'rt30=%s rt0=%s' % (p8a['rt'], p8b['rt']))
    check('P8b', 'P8 判定读实时值、不读 stored 快照（stored 未变）',
          p8a['stored'] == p8b['stored'], 'stored=%s→%s'
          % (p8a['stored'], p8b['stored']))
    set_param('edu_portal.course_rep_grace_days', '30')
    shell_json("env['op.batch'].sudo().browse(%d).write("
               "{'end_date': '2027-07-01'})\n"
               "env['op.student.course'].sudo().browse(%d).write("
               "{'academic_term_id': 1})\n"
               "env.cr.commit()\nOUT['ok'] = 1\n" % (batch, fx['sc']['rep']))

    # ============================================================ UX：学生请假可选「涉及课程」
    st, html = follow(mate_s, '/my/time_off')
    check('UX1', 'UX /my/time_off 有「涉及课程（选填）」下拉，且只列自己的课程',
          st == 200 and '涉及课程（选填）' in html
          and ('value="%d"' % sub_a) in html
          and ('value="%d"' % sub_b) not in html,
          'code=%s' % st)
    check('UX2', 'UX 提交带课程 → 落库 subject_id；不选 → NULL（N4c 已证）',
          leave_row(FX['lid_peer'])['subject'] == str(sub_a),
          'subject=%s' % leave_row(FX['lid_peer'])['subject'])
    return base


# ================================================================ 入口
def leftover_probe(purged):
    """leftover 判据：**本次夹具的每一个 id 都必须查不到**（比查总数更抗并发）。"""
    ids = {
        'subjects': purged.get('sub_ids') or [],
        'batches': purged.get('b_ids') or [],
        'students': purged.get('stu_ids') or [],
        'reps': purged.get('rep_ids') or [],
        'sheets': purged.get('sheet_ids') or [],
        'leaves': purged.get('leaf_ids') or [],
    }
    tables = {'subjects': 'op_subject', 'batches': 'op_batch',
              'students': 'op_student', 'reps': 'edu_course_rep',
              'sheets': 'op_attendance_sheet', 'leaves': 'edu_leave'}
    out = {}
    for key, ids_ in ids.items():
        if ids_:
            out[key] = pscalar('select count(*) from %s where id in (%s)'
                               % (tables[key], ','.join(str(i) for i in ids_)))
        else:
            out[key] = 0
    out['users'] = pscalar("select count(*) from res_users where login like "
                           "'crep_%'")
    out['by_tag_subjects'] = pscalar("select count(*) from op_subject where "
                                     "name like %s" % sql_lit(TAG + '%'))
    out['by_tag_batches'] = pscalar("select count(*) from op_batch where "
                                    "name like %s" % sql_lit(TAG + '%'))
    # ⚠ op.student.name 是 _inherits 委托字段（真列在 res_partner.name）：
    # raw SQL 必须 join，不能在 op_student 上直接 name like。
    out['by_tag_students'] = pscalar(
        "select count(*) from op_student s join res_partner p on p.id = "
        "s.partner_id where p.name like %s" % sql_lit(TAG + '%'))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true',
                    help='保留夹具（排查用；默认跑完即清）')
    args = ap.parse_args()
    print('=== course_rep 真机冒烟（docs/plans/course-representative-design.md §7）===')
    try:
        run_all()
    finally:
        if not args.keep:
            res = cleanup_fixtures()
            purged = (res or {}).get('purged') or {}
            lo = leftover_probe(purged)
            check('CLEAN', '夹具归还：本次夹具的每个 id 都查不到（leftover = 0）',
                  all(int(v) == 0 for v in lo.values()),
                  json.dumps(lo, ensure_ascii=False))
        else:
            print('  ---- --keep：跳过清场（夹具仍在库里）')
    RESULTS_JSON.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1),
                            encoding='utf-8')
    n_pass = sum(1 for r in RESULTS if r['pass'])
    print()
    print('== course_rep: %d/%d PASS == (%s)'
          % (n_pass, len(RESULTS), RESULTS_JSON.name))
    for r in RESULTS:
        if not r['pass']:
            print('  FAIL %s %s | %s' % (r['no'], r['name'], r['detail'][:240]))
    return 0 if n_pass == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
