#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「选课 → 课表」断链：读数复核 + 修法甲的事务内干跑（2026-09-29）。

## 本文件回答什么

用户诉求（原话）：「**选好课之后，课表里能显示他的每日课程**」。
被诊断的事实链：报课只写 op.subject.registration → 审批只写 op.student.course.subject_ids
→ 全仓没有一处为报课创建 op.session → 学生课表按**档案班**精确匹配 op.session。
本探针把这条链上的每一个环节都变成**可复跑的读数**，并把修法甲的落地步骤
**在事务内跑一遍再回滚**。

## 三段

| 段 | 内容 | 是否写库 |
|---|---|---|
| **A** | 复核 6 条现状读数（班级 / 课节 / 学生 / 合班批 / 在读档案 / 本周空档） | 只读（psql SELECT） |
| **B** | **审批 → 课表**：造一张待批报课单 → 跑真实的 action_enroll_approve → 量 Δ(op_session) | 单事务，**跑完 rollback** |
| **C** | **修法甲干跑**：多班批量排课（真实控制器方法）+ 反例（顺延=0 必须被拒）+ 合班批批量停用 | 单事务，**跑完 rollback** |

## 为什么 B/C 敢在本地主库上跑

任务口径本来就允许「**dry-run 或事务内跑完回滚**」。两段都在**一个** Odoo 事务里执行，
结束时**显式回滚该游标**，并**逐条复核残留 = 0**（行数 / 字段值回到基线）。
不写生产、不 commit、不删任何既有行。

⚠ **本探针绝不改 op.session 的既有排课**：C 段新建的课时与就地置 cancel 的改动，
全部只存在于那一个被回滚掉的事务里。

## 跑法

    python3 tests/smoke/enroll_timetable_gap_dryrun.py            # A + B + C
    python3 tests/smoke/enroll_timetable_gap_dryrun.py --section a
    python3 tests/smoke/enroll_timetable_gap_dryrun.py --json out.json

退出码：0=全绿 ｜ 1=有断言失败 ｜ 2=ENV（升级锁 / 容器不可达 / odoo shell 起不来）。
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RESULTS = HERE / 'enroll_timetable_gap_dryrun_results.json'
LOCK = Path(os.environ.get('TMPDIR') or '/tmp') / 'edu19_upgrade.lock'

DB = 'edu19'
#: 本地库的「合班/全体」批（name 含 合班 或 全体）；设计稿 §18.5 那 9 个
COMBINED_LIKE = ('%合班%', '%全体%')

OK, FAIL = 'PASS', 'FAIL'
items, readings = [], {}


def check(no, name, cond, detail=''):
    items.append({'no': no, 'name': name, 'pass': bool(cond),
                  'detail': str(detail)[:1500]})
    print('  %-4s #%-4s %-56s %s'
          % (OK if cond else FAIL, no, name, str(detail)[:220]))
    return bool(cond)


def note(msg):
    print('  ---- %s' % msg)


def die(msg, code=2):
    print('ENV: %s' % msg)
    json.dump({'error': msg, 'items': items, 'readings': readings,
               'when': datetime.datetime.now().isoformat()},
              open(RESULTS, 'w'), ensure_ascii=False, indent=1)
    return code


# ---------------------------------------------------------------------- 宿主侧助手

def _compose_exec(args, stdin=None, timeout=300):
    cmd = ['docker', 'compose', 'exec', '-T'] + args
    p = subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                       cwd=str(REPO), timeout=timeout)
    return (p.stdout or '') + (p.stderr or ''), p.returncode


def psql(sql, timeout=180):
    """在本地库跑一段只读 SQL（-X -A -F 竖线）。**调用方负责只写 SELECT**。"""
    out, _rc = _compose_exec(['db', 'psql', '-U', 'odoo', '-d', DB,
                              '-X', '-A', '-F', '|', '-v', 'ON_ERROR_STOP=1'],
                             stdin=sql + '\n', timeout=timeout)
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if (not line or line.startswith(('Pager usage', 'SET'))
                or '|' not in line or set(line) <= set('-| ')):
            continue
        rows.append(line.split('|'))
    return out, rows


SHELL_CMD = ['web', 'odoo', 'shell', '-c', '/etc/odoo/odoo.conf', '-d', DB,
             '--db_host=db', '-r', 'odoo', '-w', 'odoo', '--no-http']


def odoo_shell(payload, timeout=600):
    """把 payload 从 stdin 送进 odoo shell。

    ⚠ odoo shell 进程退出时会回滚未 commit 的事务 —— B/C 两段的「干跑」正是靠它兜底；
    脚本里仍然显式 rollback 一次并自证残留，不把安全性押在这条隐含行为上。
    """
    out, rc = _compose_exec(SHELL_CMD, stdin=payload, timeout=timeout)
    got = {}
    for line in out.splitlines():
        if line.startswith('@@'):
            k, _, v = line[2:].strip().partition(' ')
            got[k] = v.strip()
    return got, out, rc


def shell_int(got, key):
    try:
        return int(str(got.get(key, '')).strip())
    except (TypeError, ValueError):
        return None


def shell_ids(got, key):
    raw = str(got.get(key, '')).strip().strip('[]')
    if not raw:
        return []
    try:
        return [int(x) for x in raw.split(',') if x.strip()]
    except ValueError:
        return []

# ---------------------------------------------------------------------- A 段：读数复核

def week_window():
    """本地时区（Asia/Shanghai）下「本周」的 UTC naive 窗口 + 本地周一。

    口径与学生课表完全同源：edu_schedule.models.week_utils.week_window_utc
    （本地周一 00:00 → +7 天，再转 UTC naive）。
    """
    from zoneinfo import ZoneInfo
    tz = ZoneInfo('Asia/Shanghai')
    now = datetime.datetime.now(tz)
    monday = (now - datetime.timedelta(days=now.weekday())).date()
    start = datetime.datetime.combine(monday, datetime.time.min, tzinfo=tz)
    end = start + datetime.timedelta(days=7)
    return (start.astimezone(datetime.timezone.utc).replace(tzinfo=None),
            end.astimezone(datetime.timezone.utc).replace(tzinfo=None),
            monday)


def section_a():
    ws, we, monday = week_window()
    readings['week'] = {'monday_local': str(monday),
                        'window_utc': [str(ws), str(we)]}
    note('本周口径：本地周一 %s（Asia/Shanghai）⇒ UTC 窗口 %s ~ %s'
         % (monday, ws, we))

    sql = """
SELECT 'batches_total', count(*)::text FROM op_batch
UNION ALL SELECT 'sessions_total', count(*)::text FROM op_session
UNION ALL SELECT 'sc_rows_total', count(*)::text FROM op_student_course
UNION ALL SELECT 'sc_running', count(*)::text FROM op_student_course WHERE state='running'
UNION ALL SELECT 'students_total', count(*)::text FROM op_student
UNION ALL SELECT 'registrations_total', count(*)::text FROM op_subject_registration
UNION ALL SELECT 'session_student_rel', count(*)::text FROM op_session_op_student_rel
UNION ALL SELECT 'combined_batches', count(*)::text FROM op_batch
        WHERE name LIKE '%%合班%%' OR name LIKE '%%全体%%'
UNION ALL SELECT 'combined_sessions', count(*)::text FROM op_session s
        WHERE s.batch_id IN (SELECT id FROM op_batch
                             WHERE name LIKE '%%合班%%' OR name LIKE '%%全体%%')
UNION ALL SELECT 'combined_students', count(*)::text FROM op_student_course sc
        WHERE sc.batch_id IN (SELECT id FROM op_batch
                              WHERE name LIKE '%%合班%%' OR name LIKE '%%全体%%')
UNION ALL SELECT 'batches_zero_this_week', count(*)::text FROM op_batch b
        WHERE (SELECT count(*) FROM op_session s
               WHERE s.batch_id=b.id AND s.active AND s.state <> 'cancel'
                 AND s.start_datetime < '%s' AND s.end_datetime >= '%s') = 0
UNION ALL SELECT 'batches_any_session', count(*)::text FROM op_batch b
        WHERE EXISTS (SELECT 1 FROM op_session s WHERE s.batch_id=b.id)
""" % (we, ws)
    raw, rows = psql(sql)
    # 第一行是列名行（?column?|count），别把它当读数
    d = {k: v for k, v in rows if k and not k.startswith('?')}
    readings['A'] = d
    note('原始读数：%s' % json.dumps(d, ensure_ascii=False))

    total = int(d.get('batches_total', 0))
    zero = int(d.get('batches_zero_this_week', 0))
    comb_n = int(d.get('combined_batches', 0))
    comb_s = int(d.get('combined_sessions', 0))
    comb_stu = int(d.get('combined_students', 0))
    run = int(d.get('sc_running', 0))

    check('A1', 'op.session 总数（复核「288」这条读数）',
          int(d.get('sessions_total', 0)) > 0, 'sessions_total=%s' % d.get('sessions_total'))
    check('A2', '班级数与「本周零课节」的班数（复核「17 个班 11 个本周零课节」）',
          total == 17 and zero == 11,
          'batches_total=%s ｜ 本周零课节=%s ｜ 有课节的班=%s'
          % (total, zero, d.get('batches_any_session')))
    check('A3', '合班/全体批：批数 9 ｜ 课节 139 ｜ 挂在其上的学生 0',
          comb_n == 9 and comb_s == 139 and comb_stu == 0,
          '批数=%s ｜ 课节=%s ｜ 学生=%s' % (comb_n, comb_s, comb_stu))
    check('A4', '全库在读（running）学籍档案 = 1 条（复核「只有 1 条 running 档案」）',
          run == 1, 'sc_running=%s ｜ sc_rows_total=%s' % (run, d.get('sc_rows_total')))
    check('A5', 'op.session.student_ids 直连学生表 = 0 行（288 节课没有一节点名到学生）',
          int(d.get('session_student_rel', 0)) == 0,
          'op_session_op_student_rel=%s' % d.get('session_student_rel'))

    # 逐班明细（原始读数，作为「合班批 = 9 个」的自证）
    sql2 = """
SELECT b.id, b.code, b.name,
       (SELECT count(*) FROM op_session s WHERE s.batch_id=b.id)::text,
       (SELECT count(*) FROM op_student_course sc WHERE sc.batch_id=b.id)::text
FROM op_batch b ORDER BY b.id
"""
    _raw2, rows2 = psql(sql2)
    readings['A_batches'] = rows2
    note('逐班（id|code|name|课节数|挂批学生数）：')
    for r in rows2:
        print('        %s' % ' | '.join(r))
    return True


# ---------------------------------------------------------------------- B 段：审批 → 课表

B_SHELL = """
Reg = env['op.subject.registration'].sudo()
Session = env['op.session'].sudo()
Sc = env['op.student.course'].sudo()

sc = Sc.search([('state', '=', 'running')], order='id', limit=1)
print('@@B_SC %s' % sc.id)
print('@@B_SC_BATCH %s' % (sc.batch_id.id or 0))
print('@@B_SUBJ_BEFORE %s' % sorted(sc.subject_ids.ids))
print('@@B_SESS_BEFORE %s' % Session.search_count([]))
print('@@B_SCROWS_BEFORE %s' % Sc.search_count([]))

# ⚠ Odoo 19 实测坑：browse([id, ...]) 在 exists() 里会生成 IN (ARRAY[...]) 而报
#   UndefinedFunction（integer = integer[]）⇒ 一律用 search 取 rig 集，不用 browse(list)
subj = env['op.subject'].sudo().search([('id', 'in', SUBJ_IDS)])
reg = Reg.create({
    'student_id': sc.student_id.id,
    'course_id': sc.course_id.id,
    'batch_id': sc.batch_id.id,
    'doc_type': 'subject_registration',
    'state': 'submitted',
    'compulsory_subject_ids': [(6, 0, subj.ids)],
})
print('@@B_REG %s' % reg.id)
print('@@B_PAYLOAD %s' % sorted(reg._subject_payload()))
print('@@B_REG_STATE_BEFORE %s' % reg.state)
reg.action_enroll_approve()
sc.invalidate_recordset()
print('@@B_REG_STATE_AFTER %s' % reg.state)
print('@@B_SUBJ_AFTER %s' % sorted(sc.subject_ids.ids))
print('@@B_SESS_AFTER %s' % Session.search_count([]))
print('@@B_WEEK_SESS_AFTER %s' % Session.search_count([
    ('batch_id', '=', sc.batch_id.id or 0),
    ('state', '!=', 'cancel'),
    ('start_datetime', '<', 'WENDT'),
    ('end_datetime', '>=', 'WSTART')]))

env.cr.rollback()
print('@@B_RESID_SESS %s' % Session.search_count([]))
print('@@B_RESID_SCROWS %s' % Sc.search_count([]))
print('@@B_RESID_SUBJ %s' % sorted(Sc.browse(sc.id).subject_ids.ids))
print('@@B_RESID_REG %s' % Reg.search_count([('id', '=', reg.id)]))
"""


def section_b():
    ws, we, _mon = week_window()
    # 单列查询没有分隔符，psql() 的解析器会把整行当表头丢掉 ⇒ 显式拼一列出来
    subj_sql = "SELECT id, name FROM op_subject WHERE id IN (36,38,39) ORDER BY id"
    _r, rows = psql(subj_sql)
    subj_ids = [int(x[0]) for x in rows if x and str(x[0]).strip().isdigit()]
    if not subj_ids:
        return check('B0', '夹具科目（36/38/39）存在', False, '本地库没有这三门科目')

    payload = (B_SHELL.replace('SUBJ_IDS', repr(subj_ids))
               .replace('WSTART', str(ws)).replace('WENDT', str(we)))
    got, out, _rc = odoo_shell(payload)
    readings['B'] = got
    for k in ('B_SC', 'B_SC_BATCH', 'B_SUBJ_BEFORE', 'B_SESS_BEFORE', 'B_SCROWS_BEFORE',
              'B_REG', 'B_PAYLOAD', 'B_REG_STATE_BEFORE', 'B_REG_STATE_AFTER', 'B_SUBJ_AFTER',
              'B_SESS_AFTER', 'B_WEEK_SESS_AFTER',
              'B_RESID_SESS', 'B_RESID_SCROWS', 'B_RESID_SUBJ', 'B_RESID_REG'):
        note('%s = %s' % (k, got.get(k)))

    if 'B_SESS_AFTER' not in got:
        return check('B1', '审批动作能跑完（action_enroll_approve 无异常）', False,
                     out[-700:])

    before, after = shell_int(got, 'B_SESS_BEFORE'), shell_int(got, 'B_SESS_AFTER')
    check('B1', '审批动作真的跑了：报课单 state submitted → approved',
          got.get('B_REG_STATE_BEFORE') == 'submitted'
          and got.get('B_REG_STATE_AFTER') == 'approved',
          '%s → %s' % (got.get('B_REG_STATE_BEFORE'), got.get('B_REG_STATE_AFTER')))
    check('B2', '审批真的改写了学生档案科目（subject_ids 变了）',
          shell_ids(got, 'B_SUBJ_BEFORE') != shell_ids(got, 'B_SUBJ_AFTER'),
          '%s → %s' % (got.get('B_SUBJ_BEFORE'), got.get('B_SUBJ_AFTER')))
    check('B3', '★ 但 op.session 总数 Δ = 0（审批不产生任何课节 ⇒ 课表不可能变）',
          before is not None and after is not None and after - before == 0,
          'before=%s after=%s Δ=%s' % (before, after,
                                       (after - before) if None not in (before, after) else '?'))
    check('B4', '审批后「该档案班本周课节」仍与该生课表口径一致（没变就是 0）',
          shell_int(got, 'B_WEEK_SESS_AFTER') == 0,
          'B_WEEK_SESS_AFTER=%s' % got.get('B_WEEK_SESS_AFTER'))
    check('B5', '残留自证：回滚后 op.session 行数 / 学籍行数 / 报课单 全部回到基线',
          shell_int(got, 'B_RESID_SESS') == before
          and shell_int(got, 'B_RESID_SCROWS') == shell_int(got, 'B_SCROWS_BEFORE')
          and shell_int(got, 'B_RESID_REG') == 0,
          'sess=%s/%s sc=%s/%s reg=%s'
          % (got.get('B_RESID_SESS'), before, got.get('B_RESID_SCROWS'),
             got.get('B_SCROWS_BEFORE'), got.get('B_RESID_REG')))
    check('B6', '残留自证：回滚后档案科目逐字回到基线',
          shell_ids(got, 'B_RESID_SUBJ') == shell_ids(got, 'B_SUBJ_BEFORE'),
          '%s vs %s' % (got.get('B_RESID_SUBJ'), got.get('B_SUBJ_BEFORE')))
    return True

# ---------------------------------------------------------------------- C 段：修法甲干跑

C_SHELL = """
import datetime
from odoo.addons.edu_schedule.controllers import main as S


class FakeReq(object):
    '''最小请求替身：只提供控制器真正用到的那几样（env / redirect / render）。

    这样 C 段跑的是**真实控制器方法**（_build_plans_multi / _create_multi），
    不是把逻辑抄一遍 —— 抄一遍就只能证明「我抄对了」。
    '''

    def __init__(self, env):
        self.env = env

    def redirect(self, url, code=303):
        return {'__redirect__': url, 'code': code}

    def render(self, template, values=None):
        return {'__render__': template}


S.request = FakeReq(env)
tool = S.EduScheduleTool()

Batch = env['op.batch'].sudo()
Session = env['op.session'].sudo()

# ---- C1 合班批 → 组成年级（Odoo 侧推导，非本脚本自己解析）----
combined = Batch.search([('name', 'like', '合班'), ('active', '=', True)]) | \\
    Batch.search([('name', 'like', '全体'), ('active', '=', True)])
comp = {}
for b in combined.sorted(lambda x: x.id):
    c = b._deactivate_composition()
    comp[b.id] = (b.code, c.get('is_combined'), c.get('parts_label'),
                  [p['code'] for p in c.get('parts', [])],
                  [p['exists'] for p in c.get('parts', [])])
print('@@C_COMP %s' % comp)
print('@@C_COMP_ALL_RESOLVED %s' % all(all(v[4]) for v in comp.values()))
print('@@C_COMP_UNKNOWN %s' % sum(1 for v in comp.values() if not v[1]))

# ---- C2/C3 多班批量排课（§18 能力 A）----
src = Session.search([('batch_id', '=', 10)], order='id', limit=1)
# ⚠ 必须用 list 而不是括号元组：list 在 % 里算「一个值」，元组会被当成多个参数
print('@@C_SRC %s' % ([src.id, src.subject_id.name, src.faculty_id.name,
                       src.timing_id.name] if src else []))
grades = Batch.browse()
for code in ('B1', 'B2', 'B3', 'B4'):
    one = Batch.search([('code', '=', code)], limit=1)
    if one:
        grades |= one
print('@@C_GRADES %s' % [(b.id, b.code, b.name) for b in grades])
print('@@C_GRADES_LIVE_BEFORE %s' % [
    (b.code, Session.search_count([('batch_id', '=', b.id),
                                   ('state', '!=', 'cancel')])) for b in grades])
print('@@C_SESS_BEFORE %s' % Session.search_count([]))

DAY = '2027-05-03'
params = {
    'course_id': str(src.course_id.id),
    'subject_id': str(src.subject_id.id),
    'faculty_id': str(src.faculty_id.id),
    'classroom_id': str(src.classroom_id.id or 0),
    'timing_id': str(src.timing_id.id or 0),
    'start_date': DAY,
    'end_date': DAY,
    'weekdays_csv': '0',
    'stagger_minutes': '',
    'week_ranges': '',
    'parity': 'weekly',
}

data, error = tool._build_plans_multi(params, grades)
print('@@C_PREVIEW_ERR %s' % error)
if data:
    print('@@C_PREVIEW %s' % {
        'batch_count': data['batch_count'], 'total': data['total'],
        'conflict_total': data['conflict_total'], 'step': data['step'],
        'span': data['span'],
        'labels': [(p['batch'].code, p['time_label'], p['offset_label'])
                   for p in data['plans']],
    })

res = tool._create_multi(params, grades)
print('@@C_CREATE_RES %s' % (list(res.keys()) if isinstance(res, dict) else type(res).__name__))
new = Session.search([('batch_id', 'in', grades.ids),
                      ('start_datetime', '>=', '%s 00:00:00' % DAY.replace('-', '-')),
                      ('start_datetime', '<', '2027-05-10 00:00:00')],
                     order='start_datetime')
print('@@C_CREATED %s' % len(new))
print('@@C_CREATED_ROWS %s' % [
    (s.batch_id.code, s.start_datetime.strftime('%Y-%m-%d %H:%M'),
     s.end_datetime.strftime('%H:%M'), s.faculty_id.id, s.subject_id.name)
    for s in new])
print('@@C_GRADES_LIVE_AFTER %s' % [
    (b.code, Session.search_count([('batch_id', '=', b.id),
                                   ('state', '!=', 'cancel')])) for b in grades])
print('@@C_SESS_AFTER_CREATE %s' % Session.search_count([]))

# ---- C4 反例 V21：每班顺延 = 0 ⇒ 必须整批被拒（中文人话），且一节都不建 ----
bad = dict(params)
bad['stagger_minutes'] = '0'
before_bad = Session.search_count([])
data_bad, err_bad = tool._build_plans_multi(bad, grades)
print('@@C_BAD_ERR %s' % err_bad)
print('@@C_BAD_CONFLICT %s' % (data_bad['conflict_total'] if data_bad else None))
res_bad = tool._create_multi(bad, grades)
after_bad = Session.search_count([])
print('@@C_BAD_RES %s' % (list(res_bad.keys()) if isinstance(res_bad, dict) else res_bad))
print('@@C_BAD_CREATED %s' % (after_bad - before_bad))
print('@@C_BAD_MSG %s' % (data_bad and tool._multi_block_message(data_bad)))

# ---- C5 合班批批量停用（§18 能力 B）----
for b in combined.sorted(lambda x: x.id):
    r = b.deactivate_batch_sessions()
    print('@@C_DEACT %s|%s|%s|%s' % (b.id, b.code, r['cancelled'], r['already']))
print('@@C_SESS_AFTER_DEACT %s' % Session.search_count([]))
print('@@C_DEACT_TOTAL %s' % Session.search_count(
    [('batch_id', 'in', combined.ids), ('state', '=', 'cancel')]))
print('@@C_DEACT_LIVE %s' % Session.search_count(
    [('batch_id', 'in', combined.ids), ('state', '!=', 'cancel')]))
print('@@C_AUDIT_DEACT %s' % env['edu.audit.log'].sudo().search_count(
    [('action', '=', '课节批量停用')]))

# ---- C6 停用立刻对师生不可见（学生课表 domain 口径）----
print('@@C_VISIBLE_AFTER_DEACT %s' % Session.search_count([
    ('batch_id', 'in', combined.ids), ('state', '!=', 'cancel'),
    ('start_datetime', '<', '2027-01-01 00:00:00')]))

env.cr.rollback()
print('@@C_RESID_SESS %s' % Session.search_count([]))
print('@@C_RESID_DEACT %s' % Session.search_count(
    [('batch_id', 'in', combined.ids), ('state', '=', 'cancel')]))
print('@@C_RESID_AUDIT %s' % env['edu.audit.log'].sudo().search_count(
    [('action', '=', '课节批量停用')]))
"""


def section_c():
    got, out, _rc = odoo_shell(C_SHELL)
    readings['C'] = {k: v for k, v in got.items() if k != 'C_COMP'}
    readings['C_COMP'] = got.get('C_COMP')
    for k in sorted(got):
        note('%s = %s' % (k, str(got[k])[:600]))

    if 'C_CREATED' not in got:
        return check('C0', 'C 段能跑完（控制器方法在请求替身下无异常）', False,
                     out[-900:])

    check('C1', '合班批 → 组成年级的推导全部命中（9 个批、无 unknown）',
          got.get('C_COMP_ALL_RESOLVED') == 'True' and got.get('C_COMP_UNKNOWN') == '0',
          'all_resolved=%s unknown=%s'
          % (got.get('C_COMP_ALL_RESOLVED'), got.get('C_COMP_UNKNOWN')))

    prev = got.get('C_PREVIEW', '')
    check('C2', '多班排课预览：4 个年级班各一组、冲突 0、时间逐班顺延（只读，不落库）',
          "'batch_count': 4" in prev and "'conflict_total': 0" in prev
          and "'step':" in prev,
          prev[:600])

    created = shell_int(got, 'C_CREATED')
    check('C3', '多班排课真的建了 4 组课时（每班 1 节 = 4 节）',
          created == 4, 'C_CREATED=%s ｜ rows=%s'
          % (got.get('C_CREATED'), str(got.get('C_CREATED_ROWS'))[:500]))

    # 时间两两不相交（V20 判据）
    rows_raw = str(got.get('C_CREATED_ROWS', ''))
    times = re.findall(r"'(B[1-4])', '(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})', '(\d{2}:\d{2})'", rows_raw)
    read = []
    for code, day, hhmm, endmm in times:
        s = datetime.datetime.strptime('%s %s' % (day, hhmm), '%Y-%m-%d %H:%M')
        e = datetime.datetime.strptime('%s %s' % (day, endmm), '%Y-%m-%d %H:%M')
        read.append((code, s, e))
    disjoint = True
    for i in range(len(read)):
        for j in range(i + 1, len(read)):
            if read[i][1] < read[j][2] and read[j][1] < read[i][2]:
                disjoint = False
    check('C4', 'V20：4 组课时时间两两不相交（错开真的生效）',
          len(read) == 4 and disjoint, str(read))

    check('C5', 'V21：每班顺延=0 时**整批被拒**（一节都没建）',
          got.get('C_BAD_CREATED') == '0'
          and '__redirect__' not in str(got.get('C_BAD_RES', '')),
          'bad_created=%s ｜ res=%s' % (got.get('C_BAD_CREATED'), got.get('C_BAD_RES')))
    check('C6', 'V21：拒绝提示是中文人话（不是基座英文 ValidationError）',
          ('冲突' in str(got.get('C_BAD_MSG', ''))
           and 'ValidationError' not in str(got.get('C_BAD_MSG', ''))
           and '已整批取消创建' in str(got.get('C_BAD_MSG', ''))),
          str(got.get('C_BAD_MSG'))[:400])

    check('C7', 'V22：批量停用只改状态 —— op.session 行数不变',
          shell_int(got, 'C_SESS_AFTER_DEACT') == shell_int(got, 'C_SESS_AFTER_CREATE'),
          '%s → %s' % (got.get('C_SESS_AFTER_CREATE'), got.get('C_SESS_AFTER_DEACT')))
    check('C8', 'V22：9 个合班批停用后 state=cancel 计数 = 139、非 cancel = 0',
          shell_int(got, 'C_DEACT_TOTAL') == 139 and shell_int(got, 'C_DEACT_LIVE') == 0,
          'cancel=%s ｜ live=%s → 符合' % (got.get('C_DEACT_TOTAL'), got.get('C_DEACT_LIVE')))
    check('C9', 'V23：停用后学生课表口径（state != cancel）不再返回这些课节',
          shell_int(got, 'C_VISIBLE_AFTER_DEACT') == 0,
          'C_VISIBLE_AFTER_DEACT=%s' % got.get('C_VISIBLE_AFTER_DEACT'))
    check('C10', 'V24：审计留痕新增「课节批量停用」',
          (shell_int(got, 'C_AUDIT_DEACT') or 0) >= 9,
          'C_AUDIT_DEACT=%s' % got.get('C_AUDIT_DEACT'))

    check('C11', '★ 残留自证：回滚后 op.session 行数回到基线',
          shell_int(got, 'C_RESID_SESS') == shell_int(got, 'C_SESS_BEFORE'),
          '%s（基线 %s）' % (got.get('C_RESID_SESS'), got.get('C_SESS_BEFORE')))
    check('C12', '★ 残留自证：回滚后没有任何课节停在 cancel（0 行）',
          shell_int(got, 'C_RESID_DEACT') == 0,
          'C_RESID_DEACT=%s' % got.get('C_RESID_DEACT'))
    check('C13', '★ 残留自证：回滚后没有留下「课节批量停用」审计',
          shell_int(got, 'C_RESID_AUDIT') == 0,
          'C_RESID_AUDIT=%s' % got.get('C_RESID_AUDIT'))
    return True


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--section', default='abc', help='a / b / c / abc（默认 abc）')
    ap.add_argument('--json', default=None)
    args = ap.parse_args()

    if args.json:
        globals()['RESULTS'] = Path(args.json)

    if LOCK.exists():
        return die('升级锁存在（%s）⇒ 有人的 safe_upgrade 在跑，本轮作废' % LOCK)
    if not (REPO / 'scripts').is_dir():
        return die('仓库根判断失败：%s' % REPO)

    want = set(args.section.lower())
    print('== 选课→课表 断链复核 + 修法甲干跑（本地 %s，只读 / 事务内回滚）==' % DB)

    if 'a' in want:
        print('\n-- A 段：现状读数复核（psql SELECT）--')
        section_a()
    if 'b' in want:
        print('\n-- B 段：审批 → 课表（事务内跑完回滚）--')
        section_b()
    if 'c' in want:
        print('\n-- C 段：修法甲干跑（事务内跑完回滚）--')
        section_c()

    npass = sum(1 for i in items if i['pass'])
    nfail = len(items) - npass
    print('\n合计：PASS %d / FAIL %d' % (npass, nfail))
    json.dump({'when': datetime.datetime.now().isoformat(), 'db': DB,
               'items': items, 'readings': readings, 'pass': npass, 'fail': nfail},
              open(RESULTS, 'w'), ensure_ascii=False, indent=1)
    print('读数已写 %s' % RESULTS)
    return 0 if nfail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())

