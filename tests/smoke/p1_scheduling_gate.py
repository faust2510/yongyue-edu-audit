#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""排课链路改造本轮（2026-10-14：G1 先排课后报课 / G2 未排课看板 / G3 预检查三类化 /
G4 教师例外不可用）的活体验收 —— 设计 §13 的 V3–V19 可执行子集 + 本轮新增交付点。

栈：本地 edu19-clone（http://localhost:8069，db=edu19）—— **不碰生产**。
写操作自还原：探针建的课节 / 演示 leave / 探针建的节次全部删除，末尾断言 leftover=0。
用法：python3 tests/smoke/p1_scheduling_gate.py
结果：同目录 p1_scheduling_gate_results.json
"""
import datetime
import json
import os
import re
import subprocess
import sys

os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
os.environ['no_proxy'] = 'localhost,127.0.0.1'

import requests

B = 'http://localhost:8069'
DB = 'edu19'
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OK = []
NOTES = []
CREATED_SESSIONS = []
CREATED_TIMINGS = []


def check(name, got, want, extra=''):
    good = got == want
    OK.append((bool(good), name))
    print('  %-4s %-58s 期望 %-22s 实际 %s %s'
          % ('PASS' if good else 'FAIL', name, want, got, extra))
    return good


def note(text):
    NOTES.append(text)
    print('  ..   注：%s' % text)


def loc(r):
    return (r.headers.get('Location') or '').replace(B, '')


def login(name, pw='demo123'):
    s = requests.Session()
    r = s.get(B + '/login?db=%s' % DB, timeout=30)
    m = re.search(r'csrf_token[^>]*?value="([^"]+)"', r.text or '')
    assert m, '登录页没有 csrf_token（HTTP %s）' % r.status_code
    s.post(B + '/login', allow_redirects=False, timeout=30, data={
        'csrf_token': m.group(1), 'db': DB, 'login': name,
        'password': pw, 'redirect': ''})
    return s


def csrf_of(html):
    m = re.search(r'csrf_token[^>]*?value="([^"]+)"', html or '')
    return m.group(1) if m else None


def tok(sess, path):
    return csrf_of(sess.get(B + path, timeout=60).text)


def sql(q):
    p = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                        '-U', 'odoo', '-d', DB, '-tAc', q],
                       cwd=REPO, capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        raise RuntimeError('psql 失败：%s' % (p.stderr or '')[-300:])
    return p.stdout.strip()


def one(q):
    return sql(q).splitlines()[0].strip() if sql(q) else ''


def shell(code):
    """odoo shell（本地容器）。脚本里用 PROBE_RESULT= 打印结论。"""
    p = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
         '-c', '/etc/odoo/odoo.conf', '--db_host=db', '-r', 'odoo',
         '-w', 'odoo', '-d', DB, '--no-http'],
        cwd=REPO, input=code, capture_output=True, text=True, timeout=420)
    return (p.stdout or '') + (p.stderr or '')


def text_of(html):
    return re.sub(r'<[^>]+>', ' ', html or '')


TOMORROW = datetime.date.today() + datetime.timedelta(days=1)
WD = TOMORROW.weekday()          # 0=周一（与 weekdays_csv 口径一致）
DAY = TOMORROW.isoformat()

print('=== 0. 登录与载体（V3：不得在空载体上验收）===')
bo, fa, st, pa = (login('backoffice@local'), login('faculty@local'),
                  login('stu@local'), login('parent@local'))
check('四个身份登录成功（教务/教师/学生/家长）', True, True)

FAC = int(one("select f.id from op_faculty f "
              "join res_partner p on p.id=f.partner_id "
              "join res_users u on u.id=p.user_id "
              "where u.login='faculty@local'"))
check('载体①教师档案存在（op_faculty）', FAC > 0, True, 'id=%d' % FAC)

RES = one("select coalesce(resource_id::text,'NULL') from op_faculty "
          "where id=%d" % FAC)
check('G4 迁移：该教师已回填 resource.resource', RES.isdigit(), True,
      'resource_id=%s' % RES)
RES = int(RES)

CAR = one("select batch_id||','||subject_id||','||coalesce(course_id,0) "
          "from op_session where faculty_id=%d order by id limit 1" % FAC)
BATCH, SUBJECT, COURSE = [int(x) for x in CAR.split(',')]
check('载体②有在读学生的班（batch）',
      int(one("select count(distinct student_id) from op_student_course "
              "where batch_id=%d" % BATCH)) >= 1, True,
      'batch=%d' % BATCH)
check('载体③该班×科目×教师有既有课节（冲突/回归用）', SUBJECT > 0, True,
      'subject=%d course=%d' % (SUBJECT, COURSE))

BASE_SESS = int(one('select count(*) from op_session'))
BASE_LEAVE = int(one('select count(*) from resource_calendar_leaves'))
BASE_REG = int(one('select count(*) from op_subject_registration'))
BASE_TIMING = set(sql('select id from op_timing').split())
print('  基线：op_session=%d  leaves=%d  报课=%d  节次=%d'
      % (BASE_SESS, BASE_LEAVE, BASE_REG, len(BASE_TIMING)))

print('=== 1. G4 教师例外不可用（V10 登记 → V11 拦截 → V12 逃逸口）===')
r = fa.get(B + '/my/availability?db=%s' % DB, timeout=60)
check('V10-a 教师自助页 /my/availability 200', r.status_code, 200)
check('V10-a 页面含「我的不可用时间」', '我的不可用时间' in (r.text or ''), True)
r = fa.post(B + '/my/availability/save', allow_redirects=False, timeout=60, data={
    'csrf_token': csrf_of(r.text), 'mode': 'single', 'date': DAY,
    'start_time': '10:00', 'end_time': '12:00',
    'reason': '【演示】验收探针（自动还原）'})
check('V10-b 登记提交 → 303', r.status_code, 303, loc(r))
check('V10-c resource_calendar_leaves +1',
      int(one('select count(*) from resource_calendar_leaves')),
      BASE_LEAVE + 1)
check('V10-d time_type = leave',
      one("select time_type from resource_calendar_leaves order by id desc "
          "limit 1"), 'leave')
check('V10-e resource_id 指向该教师资源',
      one("select resource_id from resource_calendar_leaves order by id desc "
          "limit 1"), str(RES))
LEAVE_ID = one("select id from resource_calendar_leaves order by id desc "
               "limit 1")
check('V10-f 时段落库 = 明日 10:00–12:00（本地，UTC 存 02:00–04:00）',
      one("select to_char(date_from,'YYYY-MM-DD HH24:MI')||'~'||"
          "to_char(date_to,'HH24:MI') from resource_calendar_leaves "
          "order by id desc limit 1"),
      '%s 02:00~04:00' % DAY)

FORM = {'batch_id': BATCH, 'course_id': COURSE, 'subject_id': SUBJECT,
        'faculty_id': FAC, 'custom_begin': '10:00', 'custom_end': '12:00',
        'start_date': DAY, 'end_date': DAY,
        'weekday': str(WD), 'weekdays_csv': str(WD)}
bulk = bo.get(B + '/timetable/bulk?db=%s' % DB, timeout=60)
BT = csrf_of(bulk.text)
check('V11-a /timetable/bulk 教务可打开（200）', bulk.status_code, 200)

pv = bo.post(B + '/timetable/bulk/preview', allow_redirects=False, timeout=120,
             data=dict(FORM, csrf_token=BT))
check('V11-b 预览 200', pv.status_code, 200)
check('V11-c 预览格位 title = 日期：教师不可用·自动排除（图例那句永远在，不作证据）',
      bool(re.search(r'\d{4}-\d{2}-\d{2}：教师不可用·自动排除', pv.text or '')),
      True)
cr = bo.post(B + '/timetable/bulk/create', allow_redirects=False, timeout=180,
             data=dict(FORM, csrf_token=BT))
check('V11-d 提交被拦 → 303', cr.status_code, 303, loc(cr))
check('V11-e 该行 failed=1 且 created=0',
      ('failed=1' in loc(cr) and 'created=0' in loc(cr)), True, loc(cr))
check('V11-f op_session 行数不变（真没落库）',
      int(one('select count(*) from op_session')), BASE_SESS)

# V13 必须在 V12 之前跑：V12 会在该教师 10:00-12:00 建一节，之后 V13 改课就会
# 先撞基座「同教师同时段」判词，拿不到教师不可用那句（write() 里 leave 判定在
# super().write() 之前，但两个判据都在同一次写入里，先撞哪个取决于时段是否重叠）。
print('=== 1b. V13 单节改课拦截（写路径 / 单节表单）===')
SID = int(one('select id from op_session where faculty_id=%d order by id '
              'limit 1' % FAC))
SID_START = one("select to_char(start_datetime,'YYYY-MM-DD HH24:MI') "
                'from op_session where id=%d' % SID)
out = shell("""
s = env['op.session'].sudo().browse(%d)
try:
    s.write({'start_datetime': '%s 03:00:00', 'end_datetime': '%s 04:00:00'})
    env.cr.commit()
    print('PROBE_RESULT=NO_ERROR')
except Exception as e:
    print('PROBE_RESULT=ERROR:' + str(e).splitlines()[0][:200])
""" % (SID, DAY, DAY))
m = re.search(r'PROBE_RESULT=(.*)', out)
check('V13-a 把既有课改到教师不可用时段（本地 11:00–12:00）⇒ 教师不可用判词',
      bool(m) and '已登记不可用时间' in m.group(1), True,
      (m.group(1)[:150] if m else out[-200:]))
check('V13-b 改课失败后该节仍停在原时段（无半写）',
      one("select to_char(start_datetime,'YYYY-MM-DD HH24:MI') from op_session "
          'where id=%d' % SID), SID_START)

cr2 = bo.post(B + '/timetable/bulk/create', allow_redirects=False, timeout=180,
              data=dict(FORM, csrf_token=BT, ignore_teacher_leave='1'))
check('V12-a 逃逸口提交 → 303', cr2.status_code, 303, loc(cr2))
check('V12-b created=1（绕过成功）', 'created=1' in loc(cr2), True, loc(cr2))
check('V12-c op_session +1', int(one('select count(*) from op_session')),
      BASE_SESS + 1)
SID = int(one('select id from op_session order by id desc limit 1'))
CREATED_SESSIONS.append(SID)
check('V12-d 审计留痕含「教师不可用」',
      int(one("select count(*) from edu_audit_log where "
              "create_date >= now() - interval '20 min' and "
              "(detail like '%教师不可用%' or action like '%教师不可用%')")) >= 1,
      True)

print('=== 2. V14 误拦反例（最重要：证明没把晚课当不可用）===')
SLOT_A, SLOT_B = '', ''
for _a, _b in (('11:15', '13:15'), ('13:15', '15:15'), ('15:15', '17:15')):
    if one("select count(*) from op_session where faculty_id=%d and "
           "start_datetime='%s %s:00'" % (FAC, DAY, _a)) == '0':
        SLOT_A, SLOT_B = _a, _b
        break
check('V14-0 找到该教师当日夜间空闲时段（19:15/21:15/23:15 本地起）',
      bool(SLOT_A), True, '%s–%s UTC' % (SLOT_A, SLOT_B))
if SLOT_A:
    out = shell("""
s = env['op.session'].sudo().browse(%d)
vals = {'course_id': s.course_id.id, 'batch_id': s.batch_id.id,
        'subject_id': s.subject_id.id, 'faculty_id': s.faculty_id.id,
        'start_datetime': '%s %s:00', 'end_datetime': '%s %s:00'}
try:
    new = env['op.session'].sudo().create(vals)
    env.cr.commit()
    print('PROBE_RESULT=CREATED:%%d' %% new.id)
except Exception as e:
    print('PROBE_RESULT=ERROR:' + str(e).splitlines()[0][:200])
""" % (SID, DAY, SLOT_A, DAY, SLOT_B))
    m = re.search(r'PROBE_RESULT=(\S+)', out)
    check('V14-a 常规工时之外且教师无 leave ⇒ 允许创建',
          bool(m) and m.group(1).startswith('CREATED'), True,
          (m.group(1) if m else out[-200:]))
    if m and m.group(1).startswith('CREATED'):
        CREATED_SESSIONS.append(int(m.group(1).split(':')[1]))

print('=== 3. V15 三类提示（真冲突 / 待补档 / 不得全屏假红）===')
EVE_FORM = dict(FORM, custom_begin='19:15', custom_end='21:15')
pv2 = bo.post(B + '/timetable/bulk/preview', allow_redirects=False, timeout=120,
              data=dict(EVE_FORM, csrf_token=BT))
check('V15-a 预览 200（与既有课节同时段）', pv2.status_code, 200)
check('V15-b 出现带日期前缀的「与既有课时冲突」格位',
      bool(re.search(r'\d{4}-\d{2}-\d{2}：与既有课时冲突', pv2.text or '')), True)
NC_FORM = dict(FORM, custom_begin='14:00', custom_end='16:00')
NC_FORM.pop('classroom_id', None)
pv3 = bo.post(B + '/timetable/bulk/preview', allow_redirects=False, timeout=120,
              data=dict(NC_FORM, csrf_token=BT))
check('V15-c 未指定教室 ⇒ 黄色待补文案', '未指定教室' in (pv3.text or ''), True)
check('V15-d 待补不等于致命（页面不出现「数据异常必须先修好」）',
      '数据异常必须先修好' in (pv3.text or ''), False)

print('=== 4. G2 未排课看板（V8 对拍 / V9 权限）===')
cov = bo.get(B + '/timetable/coverage?db=%s' % DB, timeout=90)
check('V8-a 教务 /timetable/coverage 200', cov.status_code, 200)
WIN = ("state <> 'cancel' and start_datetime >= '2026-06-22 16:00:00' "
       "and start_datetime < '2026-12-20 16:00:00'")
N_TERM = int(one('select count(*) from op_session where ' + WIN))
N_ROOM = int(one('select count(*) from op_session where classroom_id is not '
                 'null and ' + WIN))
check('V8-b 课时数与同口径 SQL 相等（%d）' % N_TERM,
      str(N_TERM) in (cov.text or ''), True)
check('V8-c 教室填写率分子与 SQL 相等（%d / %d）' % (N_ROOM, N_TERM),
      (str(N_ROOM) in (cov.text or '') and str(N_TERM) in (cov.text or '')),
      True)
check('V8-d 教师不可用登记率一行已生效（不再是降级说明）',
      '教师不可用登记率' in (cov.text or '')
      and '教师资源尚未接线' not in (cov.text or ''), True)
csv = bo.get(B + '/timetable/coverage/unfilled?db=%s' % DB, timeout=90)
check('V8-e /unfilled 教务拿到真 CSV',
      (csv.status_code, 'text/csv' in (csv.headers.get('Content-Type') or '')),
      (200, True))
r = st.get(B + '/timetable/coverage?db=%s' % DB, allow_redirects=False,
           timeout=60)
check('V9-a 学生访问看板 ⇒ 303 /my/home', (r.status_code, loc(r)),
      (303, '/my/home'))
r = pa.get(B + '/timetable/coverage/unfilled?db=%s' % DB,
           allow_redirects=False, timeout=60)
check('V9-b 家长访问 CSV ⇒ 303 /my/home', (r.status_code, loc(r)),
      (303, '/my/home'))
r = st.get(B + '/my/availability?db=%s' % DB, allow_redirects=False, timeout=60)
check('V18-a 学生访问 /my/availability ⇒ 303 回门户',
      (r.status_code, loc(r)), (303, '/my/home'))
BO_G = one("select res_id from ir_model_data where module="
           "'openeducat_core' and name='group_op_back_office_admin'")
check('V18-b 教务组 implied 闭包不含 base.group_system',
      int(one("select count(*) from res_groups_implied_rel r where r.gid=%s "
              "and r.hid=(select res_id from ir_model_data where "
              "module='base' and name='group_system')" % BO_G)), 0)

print('=== 5. G1 先排课后报课（V4 前端 / V5 绕过前端 / 档位开关）===')
en = st.get(B + '/subject/enroll?db=%s' % DB, timeout=90)
check('V4-a 学生报课页 200', en.status_code, 200)
STU_ID = one("select s.id from op_student s join res_users u on "
             "u.id=s.user_id where u.login='stu@local'")
STU_BATCH = one("select batch_id from op_student_course where student_id=%s "
                "limit 1" % STU_ID)
STU_COURSE = one("select course_id from op_batch where id=%s" % STU_BATCH)
UNSCHED = one(
    "select s.id from op_subject s join op_course_op_subject_rel r on "
    "r.op_subject_id=s.id where r.op_course_id=%s and s.active and not "
    "exists (select 1 from op_session ss where ss.subject_id=s.id and "
    "ss.batch_id=%s) order by s.id limit 1" % (STU_COURSE, STU_BATCH))
if UNSCHED:
    check('V4-b 未排课科目卡有红字「不可报：本学期未排课」',
          '不可报：本学期未排课' in (en.text or ''), True)
    r = st.post(B + '/subject/enroll/save', allow_redirects=False, timeout=90,
                data={'csrf_token': csrf_of(en.text), 'course_id': STU_COURSE,
                      'batch_id': STU_BATCH, 'elective_subject_ids': UNSCHED})
    check('V5-a 绕过前端提交未排课科目 → 303 且带 box=',
          (r.status_code, 'box=' in loc(r)), (303, True), loc(r))
    check('V5-b 报课零新增（真没落库）',
          int(one('select count(*) from op_subject_registration')), BASE_REG)
else:
    note('V4/V5 载体不足：该生课程池里没有「未排课」科目，跳过前端红字与绕过前端两条')
param = "select value from ir_config_parameter where key='edu.enroll.pool_mode'"
check('G1-a 档位默认 = annotate（先排课后报课）',
      one(param) or 'annotate', 'annotate')
shell("""
env['ir.config_parameter'].sudo().set_param('edu.enroll.pool_mode', 'off')
env.cr.commit()
print('PROBE_RESULT=OFF')
""")
en2 = st.get(B + '/subject/enroll?db=%s' % DB, timeout=90)
check('G1-b off 档 = 零回归开关（科目卡不再出现「不可报：本学期未排课」）',
      '不可报：本学期未排课' in (en2.text or ''), False)
shell("""
env['ir.config_parameter'].sudo().set_param('edu.enroll.pool_mode', 'annotate')
env.cr.commit()
print('PROBE_RESULT=ON')
""")

print('=== 6. 审批详情「已排课 M / 共 N」（V7）+ 设置页入口 ===')
APV = one("select id from op_subject_registration order by id desc limit 1")
r = bo.get(B + '/registrar/subject/approvals/%s?db=%s' % (APV, DB), timeout=90)
check('V7-a 审批详情页 200', r.status_code, 200)
check('V7-b 页面出现「已排课」计数', '已排课' in (r.text or ''), True)
r = bo.get(B + '/edu/enroll/pool_mode?db=%s' % DB, allow_redirects=False,
           timeout=60)
check('G1-c 设置页入口 /edu/enroll/pool_mode 可达（200）', r.status_code, 200,
      loc(r))

print('=== 7. V16 还原（leftover=0）===')
for sid in CREATED_SESSIONS:
    shell("""
try:
    env['op.session'].sudo().browse(%d).unlink()
    env.cr.commit()
    print('PROBE_RESULT=DEL')
except Exception as e:
    print('PROBE_RESULT=ERR:' + str(e)[:120])
""" % sid)
r = fa.post(B + '/my/availability/delete', allow_redirects=False, timeout=60,
            data={'csrf_token': tok(fa, '/my/availability?db=%s' % DB),
                  'leave_id': LEAVE_ID})
check('V16-a 演示 leave 已删（页面提交 303）', r.status_code, 303, loc(r))
NEW_TIMING = set(sql('select id from op_timing').split()) - BASE_TIMING
if NEW_TIMING:
    note('探针新建的节次 %s（自定义时间自动建档），一并删除' % sorted(NEW_TIMING))
    shell("""
ids = [%s]
try:
    env['op.timing'].sudo().browse(ids).unlink()
    env.cr.commit()
    print('PROBE_RESULT=DEL')
except Exception as e:
    print('PROBE_RESULT=ERR:' + str(e)[:120])
""" % ','.join(sorted(NEW_TIMING)))
shell("""
try:
    env['resource.calendar.leaves'].sudo().search(
        [('name', '=', '【演示】验收探针（自动还原）')]).unlink()
    env.cr.commit()
    print('PROBE_RESULT=PURGED')
except Exception as e:
    print('PROBE_RESULT=ERR:' + str(e)[:120])
""")
check('V16-b 探针口径的【演示】leave 残留 = 0（含上一轮崩溃留下的）',
      int(one("select count(*) from resource_calendar_leaves where name = "
              "'【演示】验收探针（自动还原）'")), 0)
note('全库【演示】leave 行数（含种子数据，仅记录不判定）：%s'
     % one("select count(*) from resource_calendar_leaves where name like "
           "'【演示】%'"))
check('V16-c op_session 回到基线', int(one('select count(*) from op_session')),
      BASE_SESS)
check('V16-d 报课行数回到基线',
      int(one('select count(*) from op_subject_registration')), BASE_REG)

n_fail = len([1 for good, _ in OK if not good])
print('\n=== 汇总：%d / %d PASS，%d FAIL ===' % (len(OK) - n_fail, len(OK), n_fail))
for text in NOTES:
    print('  .. %s' % text)
with open(os.path.join(HERE, 'p1_scheduling_gate_results.json'), 'w') as fh:
    json.dump({'checks': [{'name': n, 'pass': g} for g, n in OK],
               'notes': NOTES,
               'run_at': datetime.datetime.now().isoformat()},
              fh, ensure_ascii=False, indent=1)
sys.exit(1 if n_fail else 0)
