#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""§18 各年级分开排：多班批量排课（时间自动错开）+ 旧合班课时批量停用 —— 真机冒烟。

设计稿：docs/plans/scheduling-overhaul-design.md §18.6（断言 V20–V25）。
用法：python3 tests/smoke/schedule_grade_split.py
退出码：0=全绿；1=有断言失败；2=运行错误（环境不可用）。

【V1 为什么不在脚本里】V1 = `bash scripts/safe_upgrade.sh edu_schedule`
（EXIT=0 且无 Traceback / CRITICAL）。升级会**重启 web 容器**，把被测进程
整段换掉 —— 必须由调用方先跑完；本脚本只做前置探活（无升级锁 + 登录页可达）。

【夹具纪律】本仓 2026-09-18 有代理误删过别人的夹具。本脚本**只建、只删
自己创建的记录**：全部带 SPLITDEMO 标记，清理按标记精确匹配，并断言
leftover = 0。**绝不**碰任何其它记录（不用真班级、不改真教师）。

【为什么不用真班级验收】在真班级上排课会污染生产同形的数据；且本脚本要
反复建/删，落在真班上风险不可接受。故自建 4 个演示班，口径与真班完全一致
（同一 op.batch 模型、同一 op.session 写入路径、同一冲突检测）。
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

BASE = os.environ.get('SG_BASE', 'http://localhost:8069')
DB = os.environ.get('EDU_DB_NAME', 'edu19')
DB_CONTAINER = os.environ.get('EDU_DB_CONTAINER', 'edu19-clone-db-1')
REPO = Path(__file__).resolve().parent.parent.parent
LOCK = os.environ.get('EDU_UPGRADE_LOCK',
                      os.path.join(os.environ.get('TMPDIR') or '/tmp',
                                   'edu19_upgrade.lock'))
if LOCK.endswith('/'):
    LOCK = LOCK[:-1]

MARK = 'SPLITDEMO'
BACKOFFICE = ('backoffice@local', 'demo123')
STU_LOGIN = 'splitdemo.stu@local'
TEA_LOGIN = 'splitdemo.tea@local'
PWD = 'demo123'
BATCH_CODES = ['SPLITDEMO-A', 'SPLITDEMO-B', 'SPLITDEMO-C', 'SPLITDEMO-D']

RESULTS = []
IDS = {}
TARGET = None


def check(no, name, ok, detail=''):
    RESULTS.append({'no': no, 'name': name, 'pass': bool(ok),
                    'detail': str(detail)[:900]})
    print('  [%s] %-5s %s%s' % ('PASS' if ok else 'FAIL', no, name,
                                (' | ' + str(detail)[:500]) if detail else ''))
    return bool(ok)


def note(msg):
    print('  ---- %s' % msg)


# ---------------------------------------------------------------- 工具
def psql(sql):
    out = subprocess.run(['docker', 'exec', DB_CONTAINER, 'psql', '-U', 'odoo',
                          '-d', DB, '-tAc', sql],
                         capture_output=True, text=True, timeout=120)
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


def kv(blob, key):
    m = re.search(r'^' + re.escape(key) + '=(.*)$', blob or '', re.M)
    return m.group(1).strip() if m else None


def login(user, pwd):
    s = requests.Session()
    s.trust_env = False
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    try:
        r = s.post(BASE + '/web/session/authenticate', timeout=30, json={
            'jsonrpc': '2.0', 'method': 'call',
            'params': {'db': DB, 'login': user, 'password': pwd}})
        uid = ((r.json() or {}).get('result') or {}).get('uid')
    except Exception:
        uid = None
    return (s, uid) if uid else (None, None)


def csrf_of(sess, url):
    r = sess.get(BASE + url, timeout=30, allow_redirects=False)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text or '')
    return (m.group(1) if m else None), r


def text_of(html):
    txt = re.sub(r'(?is)<(script|style).*?</\1>', ' ', html or '')
    txt = re.sub(r'(?s)<[^>]+>', ' ', txt)
    for a, b in (('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'),
                 ('&gt;', '>'), ('&#39;', "'"), ('&quot;', '"')):
        txt = txt.replace(a, b)
    return re.sub(r'\s+', ' ', txt)


def probe(sess, path):
    r = sess.get(BASE + path, timeout=30, allow_redirects=False)
    return r.status_code, r.headers.get('Location', ''), r.text


# ------------------------------------------------------------ ORM 夹具脚本
# 说明：odoo shell 读 stdin；写操作必须 env.cr.commit()。
# 全部记录带 MARK 前缀；清理只按 MARK 精确匹配（不碰任何其它记录）。
ORM_SETUP = """
MARK = 'SPLITDEMO'
from datetime import date, timedelta
cand = date.fromisoformat(ref_date)
Sess = env['op.session'].sudo()
Batch = env['op.batch'].sudo()
Course = env['op.course'].sudo()
Subject = env['op.subject'].sudo()
Faculty = env['op.faculty'].sudo()
Student = env['op.student'].sudo()
SC = env['op.student.course'].sudo()
Users = env['res.users'].sudo()
Timing = env['op.timing'].sudo()
Holiday = env['edu.schedule.holiday'].sudo()


def first_sel(model, fname):
    f = env[model]._fields[fname]
    sel = f.selection
    if callable(sel):
        sel = sel(env[model])
    return (sel or [('', '')])[0][0]


# ---- 幂等：先清掉上次残留（只删带标记的） ----
old_b = Batch.with_context(active_test=False).search([('code', 'like', MARK)])
if old_b:
    Sess.search([('batch_id', 'in', old_b.ids)]).unlink()
for lg in ['splitdemo.stu@local', 'splitdemo.tea@local']:
    u = Users.with_context(active_test=False).search([('login', '=', lg)])
    if u:
        u.unlink()
old_st = Student.with_context(active_test=False).search([('first_name', '=', MARK)])
if old_st:
    SC.search([('student_id', 'in', old_st.ids)]).unlink()
    old_st.unlink()
old_f = Faculty.with_context(active_test=False).search([('first_name', '=', MARK)])
if old_f:
    old_f.unlink()
if old_b:
    old_b.unlink()
old_c = Course.with_context(active_test=False).search([('code', '=', MARK)])
if old_c:
    old_c.unlink()
old_su = Subject.with_context(active_test=False).search([('code', '=', MARK)])
if old_su:
    old_su.unlink()
old_t = Timing.with_context(active_test=False).search([('name', 'like', MARK)])
if old_t:
    old_t.unlink()

# ---- 选一个不被停课日覆盖的演示日期 ----
target = cand
for _ in range(8):
    hit = Holiday.search([('active', '=', True), ('date_start', '<=', target),
                          ('date_end', '>=', target)], limit=1)
    if not hit:
        break
    target = target + timedelta(days=7)

# ---- 建夹具 ----
course = Course.create({'name': MARK + ' 演示课程', 'code': MARK,
                        'evaluation_type': first_sel('op.course', 'evaluation_type')})
subject = Subject.create({'name': MARK + ' 演示科目', 'code': MARK,
                          'type': first_sel('op.subject', 'type'),
                          'subject_type': first_sel('op.subject', 'subject_type')})
faculty = Faculty.create({'first_name': MARK, 'last_name': '演示教师',
                          'birth_date': '1980-01-01',
                          'gender': first_sel('op.faculty', 'gender')})
batches = []
for i, letter in enumerate(['A', 'B', 'C', 'D']):
    batches.append(Batch.create({
        'name': MARK + ' 演示班' + letter, 'code': MARK + '-' + letter,
        'course_id': course.id, 'start_date': target,
        'end_date': target + timedelta(days=365)}))
student = Student.create({'first_name': MARK, 'last_name': '演示学生',
                          'gender': first_sel('op.student', 'gender')})
SC.create({'student_id': student.id, 'batch_id': batches[0].id,
           'course_id': course.id, 'state': 'running'})
timing = Timing.create({'name': MARK + ' 演示节次', 'hour': '8', 'minute': '00',
                        'am_pm': 'am', 'duration': 0.75, 'sequence': 480})
portal = env.ref('base.group_portal')
u_stu = Users.create({'name': MARK + ' 演示学生账号',
                      'login': 'splitdemo.stu@local', 'password': 'demo123',
                      'partner_id': student.partner_id.id,
                      'group_ids': [(6, 0, [portal.id])], 'active': True})
student.user_id = u_stu.id
u_tea = Users.create({'name': MARK + ' 演示教师账号',
                      'login': 'splitdemo.tea@local', 'password': 'demo123',
                      'partner_id': faculty.partner_id.id,
                      'group_ids': [(6, 0, [portal.id])], 'active': True})
# 程序化建用户时 Odoo **不会回填** res.partner.user_id，而门户
# current_faculty() 正是靠 op.faculty.user_id（related 到 partner.user_id）
# 解析教师身份 —— 本仓已有同名修复脚本 scripts/fix_teacher_user_backlink.py，
# 这里照抄同一口径（否则教师课表会静默落成「访客空表」）。
faculty.partner_id.sudo().write({'user_id': u_tea.id})
env.cr.commit()

print('TARGET=' + str(target))
print('WEEKDAY=' + str(target.weekday()))
print('COURSE=%d' % course.id)
print('SUBJECT=%d' % subject.id)
print('FACULTY=%d' % faculty.id)
print('TIMING=%d' % timing.id)
print('BATCHES=' + ','.join(str(b.id) for b in batches))
print('STUDENT=%d' % student.id)
print('BATCH_A=%d' % batches[0].id)
"""

ORM_CLEAN = """
MARK = 'SPLITDEMO'
Sess = env['op.session'].sudo()
Batch = env['op.batch'].sudo()
Course = env['op.course'].sudo()
Subject = env['op.subject'].sudo()
Faculty = env['op.faculty'].sudo()
Student = env['op.student'].sudo()
SC = env['op.student.course'].sudo()
Users = env['res.users'].sudo()
Timing = env['op.timing'].sudo()
b = Batch.with_context(active_test=False).search([('code', 'like', MARK)])
if b:
    # 审计是追加式日志，但**本次演示产生的**日志不该留给下一个人当噪音
    # ⇒ 先把 res_name/detail 里带 MARK 的行删掉（只有本脚本会写这个标记），
    # 再删课时。删班本身还会被 edu_portal 的分班护栏记一条「删班」，
    # 同样带 MARK ⇒ 一并覆盖。
    env['edu.audit.log'].sudo().search(
        ['|', ('res_name', 'like', MARK), ('detail', 'like', MARK)]).unlink()
    Sess.search([('batch_id', 'in', b.ids)]).unlink()
else:
    b = Batch.browse([])
for lg in ['splitdemo.stu@local', 'splitdemo.tea@local']:
    u = Users.with_context(active_test=False).search([('login', '=', lg)])
    if u:
        u.unlink()
st = Student.with_context(active_test=False).search([('first_name', '=', MARK)])
if st:
    SC.search([('student_id', 'in', st.ids)]).unlink()
    st.unlink()
f = Faculty.with_context(active_test=False).search([('first_name', '=', MARK)])
if f:
    f.unlink()
if b:
    b.unlink()
c = Course.with_context(active_test=False).search([('code', '=', MARK)])
if c:
    c.unlink()
su = Subject.with_context(active_test=False).search([('code', '=', MARK)])
if su:
    su.unlink()
t = Timing.with_context(active_test=False).search([('name', 'like', MARK)])
if t:
    t.unlink()
# 再扫一次审计：删班本身会被分班护栏写一条「删班」（那是在上面的首扫之后），
# 以及任何在删除过程中新写的、带 MARK 的行。只按 MARK 认领，不碰别人。
env['edu.audit.log'].sudo().search(
    ['|', ('res_name', 'like', MARK), ('detail', 'like', MARK)]).unlink()
env.cr.commit()
print('CLEAN_DONE=1')
"""


def setup_fixture(ref_date):
    blob = shell(ORM_SETUP.replace(
        'cand = date.fromisoformat(ref_date)',
        'cand = date.fromisoformat(%r)' % ref_date))
    if kv(blob, 'CLEAN_DONE'):
        pass
    got = {k: kv(blob, k) for k in
           ('TARGET', 'WEEKDAY', 'COURSE', 'SUBJECT', 'FACULTY', 'TIMING',
            'BATCHES', 'STUDENT', 'BATCH_A')}
    missing = [k for k, v in got.items() if not v]
    if missing:
        raise RuntimeError('夹具建立失败，缺：%s\n%s' % (missing, blob[-1500:]))
    return got


def clean_fixture():
    return shell(ORM_CLEAN)


def leftover():
    """演示数据残留盘点（只读计数）。

    注意：Odoo 19 的 name/code 多为 jsonb（翻译字段），`like` 会报
    "operator does not exist: jsonb ~~ unknown" ⇒ 一律先 ::text 再比。
    """
    rows = []
    for table, col in (('op_course', 'code'), ('op_subject', 'code'),
                       ('op_faculty', 'first_name'), ('op_batch', 'code'),
                       ('op_student', 'first_name'), ('op_timing', 'name')):
        rows.append((table, pscalar(
            "select count(*) from " + table + " where "
            + col + "::text like '%SPLITDEMO%';")))
    rows.append(('res_users', pscalar(
        "select count(*) from res_users where login like 'splitdemo.%';")))
    rows.append(('edu_audit_log', pscalar(
        "select count(*) from edu_audit_log where res_name like '%SPLITDEMO%'"
        " or detail like '%SPLITDEMO%';")))
    return rows


# ---------------------------------------------------------------- HTTP 工具
def post(sess, url, data, token):
    payload = dict(data)
    payload['csrf_token'] = token
    return sess.post(BASE + url, data=payload, timeout=90,
                     allow_redirects=False)


WEEK_OFFSETS = (-2, -1, 0, 1, 2)


def subject_hits(sess, subject_name, offsets=WEEK_OFFSETS):
    """周课表里该科目出现几次（试几个周偏移取最大；返回 (count, offset)）。

    为什么用周视图 + 试偏移、不用日视图的 d=：实测 `/student/timetable?view=day&d=...`
    的 d 参数**在 Odoo 19 不生效**（scheduling.py 用
    `odoo.fields.Datetime.to_date(str(d))`，该 API 在 19 不存在 ⇒ 被
    `except Exception` 吞掉、静默落回今天 —— 这是**既有的**日视图缺陷，
    不属于本任务范围，本脚本只把它记录在案、改用确实可用的周视图偏移）。
    不同角色可能配了不同时区，所以不做时区假设，直接试 ±2 周取到的那一周。
    """
    best = (0, None)
    trace = []
    for w in offsets:
        code, _loc, html = probe(sess, '/student/timetable?view=week&w=%d' % w)
        n = text_of(html).count(subject_name) if code == 200 else -1
        trace.append('%+d:%s/%s' % (w, code, n))
        if n > best[0]:
            best = (n, w)
    print('       [timetable] %s' % ' '.join(trace))
    return best


def sessions_of(codes):
    """演示班课时的 UTC 起止（psql 读回，用于逐条列出时间）。"""
    blob = psql(
        "select b.code || '|' || to_char(s.start_datetime,"
        " 'YYYY-MM-DD HH24:MI:SS') || '|' || to_char(s.end_datetime,"
        " 'YYYY-MM-DD HH24:MI:SS') || '|' || s.state"
        " from op_session s join op_batch b on b.id = s.batch_id"
        " where b.code like 'SPLITDEMO-%' order by s.start_datetime, b.code;")
    rows = []
    for line in (blob or '').splitlines():
        p = line.split('|')
        if len(p) == 4:
            rows.append({'code': p[0], 'start': p[1], 'end': p[2],
                         'state': p[3]})
    return rows


def parse_dt(s):
    return date.fromisoformat(s[:10]), s[11:]


def pairwise_overlap(rows):
    """返回重叠的课对（空 = 互不重叠）。判据与基座 _overlaps 同构：
    两端严格 <；首尾相接（前一节结束 == 后一节开始）不算冲突。"""
    bad = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            if a['start'] < b['end'] and b['start'] < a['end']:
                bad.append((a['code'], b['code']))
    return bad


# ---------------------------------------------------------------- 断言
def assert_v25_mapping(bo):
    """V25：批名 → 推导组成必须打印出来并标注「需人工确认」。"""
    code, _loc, html = probe(bo, '/timetable/bulk')
    txt = text_of(html)
    check('V25', '停用入口页展示「批名 → 推导组成」并显式标注需人工确认',
          code == 200 and '推导，需人工确认' in txt
          and 'B1' in txt and 'B4' in txt,
          'status=%s 含标注=%s' % (code, '推导，需人工确认' in txt))


def run_cases(bo, target, weekday, batch_ids):
    ids = IDS
    subject_name = 'SPLITDEMO 演示科目'
    shared = {
        'course_id': ids['COURSE'], 'subject_id': ids['SUBJECT'],
        'faculty_id': ids['FACULTY'], 'timing_id': ids['TIMING'],
        'classroom_id': '', 'start_date': str(target), 'end_date': str(target),
        'week_ranges': '', 'parity': 'weekly',
        'new_course_name': '', 'new_subject_name': '',
        'custom_begin': '', 'custom_end': '',
    }
    bid_a = int(ids['BATCH_A'])

    # ---------- V20：多班批量排课 + 时间自动错开 ----------
    token, form = csrf_of(bo, '/timetable/bulk')
    order = [int(x) for x in re.findall(
        r'name="batch_ids"[^>]*value="(\d+)"', form.text or '')]
    pick = [b for b in order if b in batch_ids]
    note('表单里 4 个演示班的勾选顺序 = %s（第 1 个拿首班时段）' % pick)

    r = post(bo, '/timetable/bulk/preview',
             dict(shared, batch_ids=pick, weekday=str(weekday)), token)
    txt = text_of(r.text)
    ok_prev = (r.status_code == 200 and '多班批量排课预览' in txt
               and all('SPLITDEMO 演示班' + c in txt for c in 'ABCD'))
    check('V20a', '多班预览：一次勾 4 个班 → 4 组课时的时段逐条列出',
          ok_prev, 'status=%s 含多班标题=%s' % (r.status_code,
                                              '多班批量排课预览' in txt))

    r2 = post(bo, '/timetable/bulk/create',
              dict(shared, batch_ids=pick, weekdays_csv=str(weekday)), token)
    loc = r2.headers.get('Location', '')
    rows = sessions_of('SPLITDEMO')
    codes = sorted({x['code'] for x in rows})
    dup = pairwise_overlap(rows)
    check('V20b', '4 组课时一次生成（每班一组）',
          r2.status_code == 303 and 'multi_created=4' in loc
          and 'created=4' in loc and 'failed=0' in loc
          and len(rows) == 4 and len(codes) == 4,
          'status=%s loc=%s 实际=%d 节 / %d 个班'
          % (r2.status_code, loc, len(rows), len(codes)))
    check('V20c', '★ 4 组课时时间互不重叠（基座 _overlaps 同构判据）',
          not dup, '重叠对=%s' % (dup or '无'))
    note('4 条课时的实际时间（UTC 入库值 / 本地墙钟 = 用户时区）：')
    for x in rows:
        print('       %-12s %s → %s  state=%s'
              % (x['code'], x['start'], x['end'], x['state']))
    starts = [x['start'][11:] for x in rows]
    check('V20d', '相邻班按「一个课时长度」顺延（默认档）',
          starts == sorted(starts) and len(set(starts)) == 4,
          '起始时刻=%s' % starts)
    check('V20e', '首班时段给了表单里最上面那个班',
          rows and rows[0]['code'] == 'SPLITDEMO-' + chr(65 + pick.index(pick[0]))
          and rows[0]['code'] == dict(zip(pick, BATCH_CODES))[pick[0]],
          '首节=%s（表单首个=%s）' % (rows[0]['code'] if rows else '—',
                                     pick[0]))

    # ---------- V21：反例 —— 两个班时间重叠必须被拒（中文人话） ----------
    token2, _f = csrf_of(bo, '/timetable/bulk')
    r3 = post(bo, '/timetable/bulk/create',
              dict(shared, batch_ids=pick, weekdays_csv=str(weekday),
                   stagger_minutes='0'), token2)
    t3 = text_of(r3.text)
    rows_after = sessions_of('SPLITDEMO')
    check('V21a', '反例（每班顺延 0 = 4 个班同刻）被整批拒绝',
          r3.status_code == 200 and '已整批取消创建' in t3
          and '冲突' in t3,
          'status=%s 含「已整批取消创建」=%s'
          % (r3.status_code, '已整批取消创建' in t3))
    check('V21b', '拒绝提示是中文人话（不是基座英文 ValidationError）',
          'You cannot create a session' not in t3
          and 'Traceback' not in t3 and '教师冲突' in t3,
          '含英文报错=%s 含「教师冲突」=%s'
          % ('You cannot create a session' in t3, '教师冲突' in t3))
    check('V21c', '被拒时**一节都没写入**（整批事务式拒绝）',
          len(rows_after) == len(rows),
          '拒绝前 %d 节 → 拒绝后 %d 节' % (len(rows), len(rows_after)))

    # ---------- V25：映射表打印 + 标注「需人工确认」 ----------
    assert_v25_mapping(bo)

    # ---------- V23-before：停用前三种角色都看得见 ----------
    stu, stu_uid = login(STU_LOGIN, PWD)
    tea, tea_uid = login(TEA_LOGIN, PWD)
    if not (stu_uid and tea_uid):
        raise RuntimeError('演示学生/教师账号登录失败')
    b_staff = subject_hits(bo, subject_name)
    b_stu = subject_hits(stu, subject_name)
    b_tea = subject_hits(tea, subject_name)
    check('V23a', '停用前：学生课表 / 教师课表 / 全校课表都能看到这 4 组课时',
          b_stu[0] == 1 and b_tea[0] == 4 and b_staff[0] == 4,
          '学生=%s 教师=%s 教务=%s（值是 出现次数/周偏移）'
          % (b_stu, b_tea, b_staff))

    # ---------- V22 / V24：批量停用（二次确认 + 审计 + 只改状态） ----------
    before_total = pscalar(
        'select count(*) from op_session where batch_id = %d;' % bid_a)
    code, _loc2, html = probe(bo, '/timetable/batch/%d/deactivate' % bid_a)
    txt_d = text_of(html)
    check('V22a', '停用确认页（只读）摊开影响面：节数 / 科目 / 受影响的人',
          code == 200 and '批量停用课时' in txt_d
          and subject_name in txt_d and '会影响到的人' in txt_d,
          'status=%s 含影响面=%s' % (code, '会影响到的人' in txt_d))

    token3, _f3 = csrf_of(bo, '/timetable/batch/%d/deactivate' % bid_a)
    r_no = post(bo, '/timetable/batch/%d/deactivate/confirm' % bid_a, {}, token3)
    mid_total = pscalar(
        'select count(*) from op_session where batch_id = %d;' % bid_a)
    mid_live = pscalar("select count(*) from op_session where batch_id = %d"
                       " and state <> 'cancel';" % bid_a)
    check('V22b', '二次确认：未勾选就提交 → 303 回确认页并给中文原因，且什么都没改',
          r_no.status_code == 303 and 'error=' in r_no.headers.get('Location', '')
          and mid_total == before_total and mid_live == before_total,
          'status=%s loc=%s 节数=%d/%d'
          % (r_no.status_code, r_no.headers.get('Location', ''),
             before_total, mid_live))

    r_yes = post(bo, '/timetable/batch/%d/deactivate/confirm' % bid_a,
                 {'confirm': 'yes'}, token3)
    after_rows = pscalar(
        'select count(*) from op_session where batch_id = %d;' % bid_a)
    after_live = pscalar("select count(*) from op_session where batch_id = %d"
                         " and state <> 'cancel';" % bid_a)
    after_cancel = pscalar("select count(*) from op_session where batch_id = %d"
                           " and state = 'cancel';" % bid_a)
    check('V22c', '★ 停用后：数据行数不变，只有 state 变成 cancel',
          r_yes.status_code == 303 and 'done=1' in r_yes.headers.get('Location', '')
          and after_rows == before_total and after_live == 0
          and after_cancel == before_total,
          '行数 %d→%d · 非 cancel=%d · cancel=%d'
          % (before_total, after_rows, after_live, after_cancel))

    audits = psql("select action || '|' || res_name || '|' || detail"
                  " from edu_audit_log where action = '课节批量停用'"
                  " and res_name like '%SPLITDEMO%' order by id desc limit 1;")
    check('V24', '审计留痕：edu.audit.log 新增「课节批量停用」一条',
          bool(audits) and '停用 1 节' in audits, audits or '（无）')

    # ---------- V23-after：停用后立刻不显示 ----------
    a_staff = subject_hits(bo, subject_name)
    a_stu = subject_hits(stu, subject_name)
    a_tea = subject_hits(tea, subject_name)
    check('V23b', '★ 停用后：该班学生课表立刻不再显示这些课时',
          b_stu[0] == 1 and a_stu[0] == 0,
          '学生 停用前=%s → 停用后=%s' % (b_stu, a_stu))
    check('V23c', '停用后：教师课表与全校课表同步减少一节',
          a_tea[0] == b_tea[0] - 1 and a_staff[0] == b_staff[0] - 1,
          '教师 %s→%s · 全校 %s→%s' % (b_tea, a_tea, b_staff, a_staff))

    # ---------- 零回归：单班路径仍然可用 ----------
    token4, _f4 = csrf_of(bo, '/timetable/bulk')
    r5 = post(bo, '/timetable/bulk/preview',
              dict(shared, batch_id=pick[1], weekday=str(weekday)), token4)
    check('R1', '零回归：老的「单班」路径（batch_id）仍然可用',
          r5.status_code == 200 and '排课预览' in text_of(r5.text)
          and '多班批量排课预览' not in text_of(r5.text),
          'status=%s' % r5.status_code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true', help='不清理夹具（排障用）')
    args = ap.parse_args()

    print('=' * 74)
    print('§18 各年级分开排 —— 真机冒烟（多班批量排课 + 旧合班课时批量停用）')
    print('BASE=%s DB=%s' % (BASE, DB))
    print('=' * 74)

    # ---- 前置探活（V1 由调用方先跑 safe_upgrade.sh） ----
    if os.path.exists(LOCK):
        print('环境未就绪：升级锁存在 %s' % LOCK)
        return 2
    bo, uid = login(*BACKOFFICE)
    if not uid:
        print('环境未就绪：无法以 %s 登录（先起容器并跑 safe_upgrade）' % BACKOFFICE[0])
        return 2
    print('前置：无升级锁；backoffice 登录 uid=%s' % uid)

    today = date.today()
    target = today + timedelta(days=7)
    got = setup_fixture(target.isoformat())
    IDS.update(got)
    target = date.fromisoformat(got['TARGET'])
    weekday = int(got['WEEKDAY'])
    batch_ids = [int(x) for x in got['BATCHES'].split(',')]
    print('夹具：目标日 %s（周%d）· 4 个演示班 %s · 教师 %s'
          % (target, weekday + 1, batch_ids, got['FACULTY']))

    try:
        run_cases(bo, target, weekday, batch_ids)
    finally:
        if not args.keep:
            clean_fixture()
            rows = leftover()
            check('C1', '清理：演示数据 leftover 全为 0',
                  all(n == 0 for _t, n in rows), rows)
        else:
            print('（--keep：跳过清理）')

    okn = sum(1 for r in RESULTS if r['pass'])
    print('=' * 74)
    print('结果：%d/%d 通过' % (okn, len(RESULTS)))
    for r in RESULTS:
        if not r['pass']:
            print('  FAIL %s %s | %s' % (r['no'], r['name'], r['detail']))
    print('=' * 74)
    return 0 if okn == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())

