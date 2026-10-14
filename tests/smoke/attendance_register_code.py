#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""考勤登记簿「全新 (课程,班级)」冒烟（六步闸门第 6 步）。

事故背景（本用例是它的**永久回归**，别再让它烂三个月没人知道）
------------------------------------------------------------------
任何**还没有考勤登记簿**的 (课程, 班级) —— 新开课 / 新班第一次点名 ——
教师侧 POST /attendance/save 必 500：

    ValueError: Invalid field 'start_date' in 'op.attendance.register'
      File ".../edu_portal/controllers/roles.py", line 556, in attendance_save

两处同源缺陷：① 建簿时传了基座**不存在**的 start_date / end_date；
② 漏传 required + unique 的 code。第二处建簿点在考勤补录
（POST /attendance/import/commit）。此外成功路径以 print(...) 结尾（无 return）
⇒ 老师保存成功后拿到**空白页**，且「同班同课程同日期已有点名表 → dup=1」的
防重复分支在全新 (课程,班级) 上根本走不到（建簿先炸）。

判据红线（照 course_rep.py / class_change_request.py 的既定口径）
- 探测**不跟随重定向**（allow_redirects=False）：303 必须看首跳与 Location；
- 不只断言「页面 200」——要看库里的行（register/sheet/line 的条数与 code 值）；
- 夹具自建自清，leftover 必须 = 0；取号一律用 shell/psql 返回的真实 id，
  **不用 max(id)**；只碰本脚本自己建的记录。

用法：python3 tests/smoke/attendance_register_code.py [--keep]
结果落盘：tests/smoke/attendance_register_code_results.json
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

BASE = os.environ.get('ATTREG_BASE', 'http://localhost:8069')
DB = os.environ.get('EDU_DB_NAME', 'edu19')
DB_CONTAINER = os.environ.get('EDU_DB_CONTAINER', 'edu19-clone-db-1')
REPO = Path(__file__).resolve().parent.parent.parent
RESULTS_JSON = Path(__file__).resolve().parent / 'attendance_register_code_results.json'

TAG = '【演示】考勤建簿冒烟'
TEACHER = ('faculty@local', 'demo123')
D1 = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
D2 = (datetime.date.today() - datetime.timedelta(days=8)).isoformat()

RESULTS = []
FX = {}


def check(no, name, ok, detail=''):
    RESULTS.append({'no': no, 'name': name, 'pass': bool(ok),
                    'detail': str(detail)[:900]})
    print('  [%s] %-6s %s%s' % ('PASS' if ok else 'FAIL', no, name,
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


def sql_lit(val):
    """SQL 字符串字面量（自己拼 WHERE 时用；日期/代码都从我们自己的夹具来）。"""
    return "'" + str(val).replace("'", "''") + "'"


def shell(code, timeout=600):
    cmd = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
           '-c', '/etc/odoo/odoo.conf', '--db_host=db', '--db_port=5432',
           '--db_user=odoo', '--db_password=odoo', '-d', DB, '--no-http']
    out = subprocess.run(cmd, input=code, capture_output=True, text=True,
                         timeout=timeout, cwd=str(REPO))
    return (out.stdout or '') + (out.stderr or '')


def shell_json(body, timeout=600):
    # ⚠ odoo shell 的 stdin：拼接的**字符串字面量**里不要出现真换行（用 chr(10)）
    NL = chr(10)
    head = 'import json' + NL + 'OUT = {}' + NL
    tail = (NL + "print('@@ATTREGJ@@' + json.dumps("
            "OUT, ensure_ascii=False, default=str))" + NL)
    blob = shell(head + body + tail, timeout)
    m = re.search(r'@@ATTREGJ@@(.*)', blob)
    if not m:
        Path('/tmp/attreg_shell_fail.txt').write_text(blob)
        raise RuntimeError('odoo shell 未返回 JSON（完整输出 '
                           '/tmp/attreg_shell_fail.txt）：' + blob[-1500:])
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
    r = sess.get(BASE + path, timeout=40)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text or '')
    return m.group(1) if m else ''


def loc(resp):
    return resp.headers.get('Location') or ''


# ---------------------------------------------------------------- 夹具
PURGE_FN = '''
def purge_all(env, tag):
    out = {}
    C = env['op.course'].sudo().with_context(active_test=False).search(
        [('code', 'like', 'ATTREG-%')])
    B = env['op.batch'].sudo().with_context(active_test=False).search(
        [('code', 'like', 'ATTREG-%')])
    St = env['op.student'].sudo().with_context(active_test=False).search(
        [('gr_no', 'like', 'ATTREG-%')])
    Rg = env['op.attendance.register'].sudo().with_context(active_test=False).search(
        [('course_id', 'in', C.ids)])
    Sh = env['op.attendance.sheet'].sudo().with_context(active_test=False).search(
        [('register_id', 'in', Rg.ids)])
    Ln = env['op.attendance.line'].sudo().with_context(active_test=False).search(
        [('attendance_id', 'in', Sh.ids)])
    Se = env['op.session'].sudo().with_context(active_test=False).search(
        [('course_id', 'in', C.ids)])
    SC = env['op.student.course'].sudo().with_context(active_test=False).search(
        ['|', ('course_id', 'in', C.ids), ('student_id', 'in', St.ids)])
    Al = env['edu.audit.log'].sudo().with_context(active_test=False).search(
        [('detail', 'like', tag)])
    Sb = env['op.subject'].sudo().with_context(active_test=False).search(
        [('code', 'like', 'ATTREG-%')])
    out['lines'] = len(Ln)
    out['sheets'] = len(Sh)
    out['registers'] = len(Rg)
    out['sessions'] = len(Se)
    out['student_course'] = len(SC)
    out['students'] = len(St)
    out['audit'] = len(Al)
    out['subjects'] = len(Sb)
    out['batches'] = len(B)
    out['courses'] = len(C)
    Ln.unlink()
    Sh.unlink()
    Rg.unlink()
    Al.unlink()
    Se.unlink()
    SC.unlink()
    P = St.mapped('partner_id')
    if St:
        St.unlink()
    if P:
        P.unlink()
    Sb.unlink()
    if B:
        B.unlink()
    if C:
        C.unlink()
    env.cr.commit()
    return out
'''

SETUP_CODE = PURGE_FN + '''
env = env  # noqa
TAG = '__TAG__'
purge_all(env, TAG)
from odoo.addons.edu_schedule.models.identity import faculty_of_user
U = env['res.users'].sudo().with_context(active_test=False)
fac_u = U.search([('login', '=', '__TEACHER__')], limit=1)
assert fac_u, '教师登录账号缺失：__TEACHER__'
# 反查口径必须与控制器 current_faculty() 完全一致（双向并集，见
# edu_schedule/models/identity.py）：否则夹具建的班在 HTTP 侧落不到这位老师名下
fac = faculty_of_user(env, fac_u.id)
assert fac, '教师档案缺失：__TEACHER__'
subj = env['op.subject'].sudo().create(
    {'name': TAG + '科目', 'code': 'ATTREG-SUB', 'type': 'theory'})
OUT['faculty'] = fac.id


def mk_pair(env, tag, n, nstu):
    crs = env['op.course'].sudo().create(
        {'name': tag + '课程%d' % n, 'code': 'ATTREG-C%d' % n,
         'evaluation_type': 'normal'})
    bat = env['op.batch'].sudo().create(
        {'name': tag + '班%d' % n, 'code': 'ATTREG-B%d' % n,
         'course_id': crs.id, 'start_date': '2026-01-01',
         'end_date': '2030-12-31'})
    env['op.session'].sudo().create(
        {'course_id': crs.id, 'batch_id': bat.id, 'subject_id': subj.id,
         'faculty_id': fac.id,
         'start_datetime': '2033-0%d-01 03:00:00' % n,
         'end_datetime': '2033-0%d-01 04:00:00' % n})
    stus = []
    for i in range(nstu):
        p = env['res.partner'].sudo().create({'name': '%s生%d-%d' % (tag, n, i)})
        st = env['op.student'].sudo().create(
            {'name': p.name, 'partner_id': p.id,
             'gr_no': 'ATTREG-S%d%d' % (n, i)})
        env['op.student.course'].sudo().create(
            {'student_id': st.id, 'course_id': crs.id, 'batch_id': bat.id,
             'state': 'running', 'academic_term_id': 1})
        stus.append(st.id)
    return crs.id, bat.id, stus


OUT['c1'], OUT['b1'], OUT['s1'] = mk_pair(env, TAG, 1, 2)
OUT['c2'], OUT['b2'], OUT['s2'] = mk_pair(env, TAG, 2, 1)
OUT['c3'], OUT['b3'], OUT['s3'] = mk_pair(env, TAG, 3, 0)
env.cr.commit()
'''

CLEAN_CODE = PURGE_FN + '''
env = env  # noqa
OUT['purged'] = purge_all(env, '__TAG__')
env.cr.commit()
'''

# R8：模拟「对手事务先提交、本事务快照已过期」，验证唯一约束 + 换快照重试
CONCUR_CODE = '''
env = env  # noqa
from odoo.addons.edu_portal.controllers.roles import (  # noqa: E402
    attendance_register, attendance_register_code)
cid = __C3__
bid = __B3__
C = env['op.course'].sudo().browse(cid)
B = env['op.batch'].sudo().browse(bid)
code = attendance_register_code(cid, bid)
env.cr.execute('SELECT 1')          # ① 固定本事务快照（REPEATABLE READ）
cr2 = env.registry.cursor()         # ② 对手：另一连接先建同 code 的登记簿并提交
try:
    cr2.execute(
        "INSERT INTO op_attendance_register "
        " (name, code, course_id, batch_id, active, create_uid, write_uid,"
        "  create_date, write_date) "
        " VALUES (%s, %s, %s, %s, true, 1, 1, now(), now()) RETURNING id",
        ('并发对手建簿', code, cid, bid))
    OUT['opponent_id'] = cr2.fetchone()[0]
    cr2.commit()
finally:
    cr2.close()
OUT['visible_before'] = env['op.attendance.register'].sudo().search(
    [('course_id', '=', cid), ('batch_id', '=', bid)]).ids   # ③ 旧快照：看不见
reg = attendance_register(env, C, B)                          # ④ 撞约束→换快照→复用
OUT['got_id'] = reg.id
OUT['got_code'] = reg.code
OUT['code_expected'] = code
OUT['rows_for_pair'] = env['op.attendance.register'].sudo().search_count(
    [('course_id', '=', cid), ('batch_id', '=', bid)])
OUT['total_rows_for_code'] = env['op.attendance.register'].sudo().search_count(
    [('code', '=', code)])
env.cr.commit()
'''


def _fill(code):
    return (code.replace('__TAG__', TAG)
            .replace('__TEACHER__', TEACHER[0])
            .replace('__C3__', str(FX.get('c3', 0)))
            .replace('__B3__', str(FX.get('b3', 0))))


def setup_fixtures():
    return shell_json(_fill(SETUP_CODE))


def cleanup_fixtures():
    return shell_json(_fill(CLEAN_CODE))


def leftover_counts():
    """清场后复查：本脚本建的夹具一件都不许留（判据 = 按标签/按本脚本的 code 数）。"""
    codes = ', '.join(
        sql_lit('R%d-%d' % (FX[a], FX[b]))
        for a, b in (('c1', 'b1'), ('c2', 'b2'), ('c3', 'b3'))) or "''"
    return {
        'courses': pscalar("select count(*) from op_course where code like 'ATTREG-%'"),
        'batches': pscalar("select count(*) from op_batch where code like 'ATTREG-%'"),
        'subjects': pscalar("select count(*) from op_subject where code like 'ATTREG-%'"),
        'students': pscalar("select count(*) from op_student where gr_no like 'ATTREG-%'"),
        'student_course': pscalar("select count(*) from op_student_course sc join op_course c "
                                  "on c.id = sc.course_id where c.code like 'ATTREG-%'"),
        'registers': pscalar("select count(*) from op_attendance_register "
                             "where code in (%s)" % codes),
        'sheets_by_tag': pscalar("select count(*) from op_attendance_sheet s "
                                 "join op_attendance_register r on r.id = s.register_id "
                                 "join op_course c on c.id = r.course_id "
                                 "where c.code like 'ATTREG-%'"),
        'audit': pscalar("select count(*) from edu_audit_log where detail like '%" + TAG + "%'"),
    }


# ---------------------------------------------------------------- 用例
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true', help='保留夹具（排查用）')
    args = ap.parse_args()

    print('== 夹具 ==')
    fixture = setup_fixtures()
    FX.update(fixture)
    note('fixture=%s' % json.dumps(fixture, ensure_ascii=False))
    c1, b1 = fixture['c1'], fixture['b1']
    c2, b2 = fixture['c2'], fixture['b2']
    s1 = fixture['s1']
    code1 = 'R%d-%d' % (c1, b1)
    code2 = 'R%d-%d' % (c2, b2)

    check('R0a', '前置：全新 (课程,班级) #1 还没有任何考勤登记簿',
          ptext("select count(*) from op_attendance_register where course_id=%d "
                "and batch_id=%d" % (c1, b1)) == '0')
    check('R0b', '前置：#1、#2、#3 三个组合都是全新的（登记簿 0 / 点名表 0）',
          pscalar("select count(*) from op_attendance_register where course_id in (%d,%d,%d)"
                  % (c1, c2, fixture['c3'])) == 0
          and pscalar("select count(*) from op_attendance_sheet where course_id in (%d,%d,%d)"
                      % (c1, c2, fixture['c3'])) == 0)

    tea, uid = login(*TEACHER)
    check('R0c', '教师登录（%s）' % TEACHER[0], bool(uid), 'uid=%s' % uid)
    if not tea:
        _finish(args)
        return

    take_path = '/attendance/take?batch_id=%d&date=%s' % (b1, D1)
    r = probe(tea, take_path)
    check('R1', 'GET /attendance/take 选到全新班 → 200（老师能打开点名页）',
          r.status_code == 200, 'code=%s' % r.status_code)

    # ---- R2：事故主症 —— 全新 (课程,班级) 第一次点名必须建簿成功 ----
    tok = csrf_of(tea, take_path)
    r = probe(tea, '/attendance/save', method='POST', data={
        'csrf_token': tok, 'batch_id': b1, 'course_id': c1, 'date': D1,
        'status_%d' % s1[0]: 'present', 'status_%d' % s1[1]: 'late'})
    check('R2', 'POST /attendance/save（全新 (课程,班级) 第一次点名）→ 303 到 '
          '&saved=1 结果页（此前这里是 500）',
          r.status_code == 303 and 'saved=1' in loc(r),
          'code=%s loc=%s' % (r.status_code, loc(r)))
    n_reg1 = pscalar("select count(*) from op_attendance_register where course_id=%d "
                     "and batch_id=%d" % (c1, b1))
    reg_row = ptext("select id::text || '|' || coalesce(code,'-') || '|' || "
                    "coalesce(name,'-') from op_attendance_register where course_id=%d "
                    "and batch_id=%d" % (c1, b1))
    rid, rcode, rname = (reg_row.split('|') + ['', '', ''])[:3]
    check('R3', '建簿落库：1 本、code = R{course}-{batch}、name 非空（required 字段齐全）',
          n_reg1 == 1 and rcode == code1 and rname not in ('', '-'),
          'rows=%d code=%s want=%s name=%s' % (n_reg1, rcode, code1, rname))
    n_sheet1 = pscalar("select count(*) from op_attendance_sheet where course_id=%d "
                       "and batch_id=%d and attendance_date=%s" % (c1, b1, sql_lit(D1)))
    n_line1 = pscalar("select count(*) from op_attendance_line where course_id=%d "
                      "and batch_id=%d and attendance_date=%s" % (c1, b1, sql_lit(D1)))
    check('R4', '点名表与考勤行落库（1 张表 / 2 行 = 班里 2 人）',
          n_sheet1 == 1 and n_line1 == 2,
          'sheets=%d lines=%d' % (n_sheet1, n_line1))
    sheet_row = ptext("select id::text from op_attendance_sheet where course_id=%d "
                      "and batch_id=%d and attendance_date=%s" % (c1, b1, sql_lit(D1)))
    sid = int(sheet_row or 0)

    # ---- R5：防重复分支（此前因 500 根本走不到） ----
    tok = csrf_of(tea, take_path)
    r = probe(tea, '/attendance/save', method='POST', data={
        'csrf_token': tok, 'batch_id': b1, 'course_id': c1, 'date': D1,
        'status_%d' % s1[0]: 'absent'})
    check('R5', '同班同课程同日期再提交 → 303 到 dup=1 且带 dup_sheet（不建第二张表）',
          r.status_code == 303 and 'dup=1' in loc(r)
          and ('dup_sheet=%d' % sid) in loc(r)
          and pscalar("select count(*) from op_attendance_sheet where course_id=%d "
                      "and batch_id=%d" % (c1, b1)) == 1
          and pscalar("select count(*) from op_attendance_register where course_id=%d "
                      "and batch_id=%d" % (c1, b1)) == 1,
          'code=%s loc=%s' % (r.status_code, loc(r)))

    # ---- R6：已有登记簿 → 零回归（复用同一本簿，另一天照常新建表） ----
    take_path2 = '/attendance/take?batch_id=%d&date=%s' % (b1, D2)
    tok = csrf_of(tea, take_path2)
    r = probe(tea, '/attendance/save', method='POST', data={
        'csrf_token': tok, 'batch_id': b1, 'course_id': c1, 'date': D2,
        'status_%d' % s1[0]: 'present', 'status_%d' % s1[1]: 'absent'})
    check('R6', '已建簿的 (课程,班级) 第二次点名（另一天）→ 303 saved=1、复用同一本簿、表 +1',
          r.status_code == 303 and 'saved=1' in loc(r)
          and pscalar("select count(*) from op_attendance_register where course_id=%d "
                      "and batch_id=%d" % (c1, b1)) == 1
          and pscalar("select count(*) from op_attendance_sheet where course_id=%d "
                      "and batch_id=%d" % (c1, b1)) == 2,
          'code=%s loc=%s' % (r.status_code, loc(r)))

    # ---- R7：第二处建簿点：考勤补录 import/commit ----
    imp_tok = csrf_of(tea, '/attendance/import?batch_id=%d&date=%s' % (b2, D1))
    payload = json.dumps([{'student_id': fixture['s2'][0], 'status': 'absent'}],
                         ensure_ascii=False)
    r = probe(tea, '/attendance/import/commit', method='POST', data={
        'csrf_token': imp_tok, 'batch_id': b2, 'course_id': c2, 'date': D1,
        'payload': payload})
    reg2 = ptext("select coalesce(code,'-') from op_attendance_register where "
                 "course_id=%d and batch_id=%d" % (c2, b2))
    check('R7', '第二处建簿点：考勤补录（全新 (课程,班级) #2）→ 303 saved=1、'
          '建簿带 code、补录行落库',
          r.status_code == 303 and 'saved=1' in loc(r) and reg2 == code2
          and pscalar("select count(*) from op_attendance_line where course_id=%d "
                      "and batch_id=%d and absent" % (c2, b2)) == 1,
          'code=%s loc=%s reg_code=%s want=%s' % (r.status_code, loc(r), reg2, code2))

    # ---- R8：唯一性由数据库保证（不是 if 判断） ----
    out, err = psql("insert into op_attendance_register "
                    " (name, code, course_id, batch_id, active, create_uid, "
                    "  write_uid) values ('冒烟重复建簿', %s, %d, %d, true, 1, 1)"
                    % (sql_lit(code1), c1, b1), want_err=True)
    check('R8', '同 (课程,班级) 第二次建簿被数据库唯一约束拒绝（unique(code)）',
          'duplicate key value violates unique constraint' in err,
          (err or out)[:220])

    # ---- R9：并发（对手先提交 + 本事务快照过期）→ 换快照重试收敛到对手那一本 ----
    try:
        co = shell_json(_fill(CONCUR_CODE))
    except Exception as exc:
        co = {'error': str(exc)[:400]}
    check('R9', '并发收敛：快照过期的请求撞 unique(code) 后换快照，复用对手那一本'
          '（不新建第二本、不 500）',
          co.get('opponent_id') and co.get('got_id') == co.get('opponent_id')
          and co.get('total_rows_for_code') == 1
          and co.get('code_expected') == co.get('got_code'),
          json.dumps(co, ensure_ascii=False)[:500])
    check('R10', 'R9 前置：并发对手的行在本事务旧快照里确实**不可见**'
          '（证明这不是「先查后写」偶然蒙对）',
          co.get('visible_before') == [],
          'visible_before=%s' % co.get('visible_before'))

    _finish(args)


def _finish(args):
    print('\n== 清场 ==')
    if args.keep:
        note('--keep：保留夹具 %s' % json.dumps(FX, ensure_ascii=False))
        purged = None
    else:
        try:
            purged = cleanup_fixtures().get('purged')
        except Exception as exc:
            purged = {'error': str(exc)[:300]}
        note('purged=%s' % json.dumps(purged, ensure_ascii=False))
        left = leftover_counts()
        check('R11', '夹具自清：leftover 全 0（登记簿/点名表/考勤行/课程/班级/科目/学生/审计）',
              all(v == 0 for v in left.values()),
              json.dumps(left, ensure_ascii=False))

    npass = sum(1 for r in RESULTS if r['pass'])
    nfail = len(RESULTS) - npass
    summary = {'pass': npass, 'fail': nfail, 'total': len(RESULTS),
               'when': datetime.datetime.now().isoformat(timespec='seconds'),
               'base': BASE, 'db': DB, 'fixture': FX, 'purged': purged,
               'results': RESULTS}
    RESULTS_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print('\nPASS=%d FAIL=%d（结果落盘 %s）' % (npass, nfail, RESULTS_JSON))
    sys.exit(1 if nfail else 0)


if __name__ == '__main__':
    main()
