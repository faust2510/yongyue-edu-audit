# -*- coding: utf-8 -*-
"""批量导入 2+6 排课表课次 → 本地 edu19 克隆库 op.session（t2）。

数据契约：timetable_import/catalog.md（唯一数据契约）+
         sessions.csv（226 实体主表，analyst 生成）。

运行方式（二选一）：

  # 1) 离线 dry-run（不连库、不写任何数据，仅预检计数/冲突/档案规划）
  python3 timetable_import/import_sessions.py --dry-run

  # 2) 真实导入（本地 edu19 克隆库；容器不挂载仓库根，CSV 经环境变量传入）
  bash timetable_import/run_import_local.sh
  # 等价手工命令：
  #   docker compose exec -T -e SESSIONS_CSV="$(cat timetable_import/sessions.csv)" web \
  #       odoo shell -c /etc/odoo/odoo.conf --db_host=db -r odoo -w odoo -d edu19 --no-http \
  #       < timetable_import/import_sessions.py
  # 幂等重跑：再次执行同一条命令即可，重复执行不产生重复 session。

用户裁决（2026-09-05 拍板，固化于下方 RULING_* / COURSE_OVERRIDES 常量区）：
1. 家教 157 条不单独建 session（沿用 sessions.csv 合并实体，source_sheet 含
   "家教"即网课视角；不需要为家教学员建独立 batch/course）。
2. 师生互动 14 行（周三 14:00-17:00，batch 空 = A 部 A123 活动）不建 op.session，
   导入时过滤 kind 含"师生互动"，也不为其建科目/占位。
3. 救恩论 A123 密集课（原 2026-12-28 09:00-17:00 单行）展开为 5 节独立 session：
   12/28~12/31 + 1/4（元旦 1/1 放假顺延，与校历"元旦"标注一致）；每天
   09:00-17:00，lesson_no 留空，kind 留空，raw_text 标注"第N天"。
4. B 部 B1/B3/B4/B34/B234/B1234（含档案班 B2）归属 course 可配置：默认
   CRS-BED（教育学学士）而非 CRS-BLA——改 COURSE_OVERRIDES 即可一键改回；
   跨部合班课（A 开头）主属 CRS-BTH。

其余默认维持 catalog：考试课照排（kind=考试 记入 name）、教室不指定、
教师占位「待定」1 名（TBD-TEACHER）、B12 不导入、CB34 并入 A123B34。

设计要点：
- 写库走合法 ORM：op.course/op.subject/op.batch/op.faculty/op.timing 建档 +
  op.session.create(一次批量调用) + 审计 edu.audit.log；禁止裸 SQL。
- Asia/Shanghai 墙钟 → UTC naive 入库（与 edu_schedule/edu_portal 口径一致）。
- 幂等：以 (batch_code, subject_code, 本地日期, 本地 start HH:MM) 判重，先查后建。
- 冲突预检内联 upstream check_timetable_fields 的四维重叠逻辑（faculty /
  classroom / batch+subject / batch），dry-run 与真实导入前都会打印；同 batch
  同刻（同科目或不同科目）为真实冲突必须为 0；同教师重叠仅来自占位「待定」
  教师（全部课共用同一人造成的结构性重叠，属 catalog §7 G 待决，真实教师
  替换后自然消解）；教室未指定故该维恒 0。
- 全部 session 以一次 create_multi 提交：upstream 冲突守卫对 self 内同批互查
  豁免，而序列 create 会把「不同 batch 的并行班」误判为同一占位教师冲突
  （实测探针：create_multi 两节同教师重叠不报错，序列创建抛 ValidationError）。
"""
import csv
import datetime as _dt
import io
import os
import sys

import pytz

# 仓库根与数据源定位：优先环境变量（容器运行时），其次宿主路径（dry-run）。
# odoo shell 经 stdin 执行时无 __file__，回退到环境变量 SESSIONS_CSV 数据。
try:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    HOST_CSV = os.path.join(_BASE, 'timetable_import', 'sessions.csv')
    PLAN_OUT = os.path.join(_BASE, 'timetable_import',
                            'session_import_plan.csv')
except NameError:                       # odoo shell stdin：无 __file__
    _BASE = os.getcwd()
    HOST_CSV = ''
    PLAN_OUT = ''

LOCAL_TZ = 'Asia/Shanghai'          # 课表墙钟时区
TZ = pytz.timezone(LOCAL_TZ)
UTC = pytz.utc

# =====================================================================
# 用户裁决区（改这里即可调整默认裁决；将来换归属只改 COURSE_OVERRIDES）
# =====================================================================
RULING_DROP_KIND = '师生互动'       # 裁决2：该 kind 行不建 op.session
RULING_EXPAND = {                   # 裁决3：救恩论 A123 密集课 1 行 → 5 天
    ('救恩论', 'A123'): [
        '2026-12-28', '2026-12-29', '2026-12-30', '2026-12-31', '2027-01-04',
    ],
}
RULING_EXPAND_DAILY = {
    ('救恩论', 'A123'): ('09:00', '17:00'),
}

# 裁决4：course 归属（batch code → course code）。改回文学学士只需把 B* 的
# 值改为 'CRS-BLA' 后重跑（幂等，只影响新建档 batch 的归属）。
COURSE_OVERRIDES = {
    'B1': 'CRS-BED', 'B2': 'CRS-BED', 'B3': 'CRS-BED', 'B4': 'CRS-BED',
    'B34': 'CRS-BED', 'B234': 'CRS-BED', 'B1234': 'CRS-BED',
}
# 跨部合班课（组合首字母 A → 主属 A 部 CRS-BTH；用户裁决：跨部联课主属以
# 组合首个字母为准）。这些 code 不落入上面的 B 部覆盖。
CROSS_BATCH_A_FIRST = {'A123B1', 'A123B234', 'A123B34', 'A23B34'}

# 全部要建档的 batch code：主表挂课组合 + 年级档案班（A2/A3/B2）
SESSION_BATCH_LABELS = [
    'A1', 'A23', 'A123', 'B1', 'B3', 'B4', 'B34', 'B234', 'B1234',
    'A123B1', 'A123B234', 'A123B34', 'A23B34',
]
ARCHIVE_BATCH_LABELS = ['A2', 'A3', 'B2']
ALL_BATCH_CODES = SESSION_BATCH_LABELS + ARCHIVE_BATCH_LABELS

# 占位教师（catalog §4.4 / 裁决4 维持）：1 名「待定」
FACULTY_CODE = 'TBD-TEACHER'
FACULTY_FIRST = '待定'
FACULTY_LAST = '教师'
FACULTY_PARTNER_REF = 'TBD-TEACHER'
FACULTY_PARTNER_NAME = '待定'
FACULTY_BIRTH = '1970-01-01'

# 科目表（subject_name → (code, type, subject_type)），源自
# subjects_batches_build.csv（BTH-=神学 BLA-=人文 GEN-=跨部；师生互动不建档）
SUBJECT_CODE_MAP = {
    '英语': ('BTH-GEN01', 'theory', 'compulsory'),
    '课程设计实务': ('BLA-PRA01', 'practical', 'compulsory'),
    '基督教与文学经典选读（二）': ('BLA-LIT02', 'theory', 'compulsory'),
    '神论': ('BTH-THE01', 'theory', 'compulsory'),
    '课堂管理': ('BLA-CLA01', 'theory', 'compulsory'),
    '逻辑一': ('GEN-LOG01', 'theory', 'compulsory'),
    '希伯来语二': ('BLA-HEB02', 'theory', 'compulsory'),
    '希伯来语四': ('BLA-HEB04', 'theory', 'compulsory'),
    '圣灵论': ('BTH-SPI01', 'theory', 'compulsory'),
    '基督教与法律导论': ('BTH-LAW01', 'theory', 'compulsory'),
    '护教学基础': ('GEN-APO01', 'theory', 'compulsory'),
    '使徒行传': ('GEN-ACT01', 'theory', 'compulsory'),
    '救恩论': ('BTH-SAL01', 'theory', 'compulsory'),
    '圣约神学': ('BLA-COV01', 'theory', 'compulsory'),
    '讲道法': ('BTH-HOM01', 'theory', 'compulsory'),
    '摩西五经': ('BTH-PEN01', 'theory', 'compulsory'),
    '基础信仰': ('BTH-FOU01', 'theory', 'compulsory'),
    '改革宗初始讲座': ('BTH-REF01', 'other', 'elective'),
}
# 预留的科目 code（build csv 存在但本脚本不建档）：BTH-ACT01 师生互动

BATCH_NAME_MAP = {
    'A1': '神学一年级', 'A2': '神学二年级', 'A3': '神学三年级',
    'A23': 'A2+A3合班', 'A123': 'A1+A2+A3合班',
    'B1': '人文一年级', 'B2': '人文二年级', 'B3': '人文三年级',
    'B4': '人文四年级', 'B34': 'B3+B4合班', 'B234': 'B2+B3+B4合班',
    'B1234': 'B1-B4全体', 'A123B1': 'A123+B1合班',
    'A123B234': 'A123+B234合班', 'A123B34': 'A123+B34合班',
    'A23B34': 'A23+B34合班',
}
# 基础归属（B 部将按裁决4 覆盖为 CRS-BED；此处给出"改回文学学士"基准）
BASE_BATCH_COURSE = {
    'A1': 'CRS-BTH', 'A2': 'CRS-BTH', 'A3': 'CRS-BTH',
    'A23': 'CRS-BTH', 'A123': 'CRS-BTH',
    'B1': 'CRS-BLA', 'B2': 'CRS-BLA', 'B3': 'CRS-BLA', 'B4': 'CRS-BLA',
    'B34': 'CRS-BLA', 'B234': 'CRS-BLA', 'B1234': 'CRS-BLA',
    'A123B1': 'CRS-BTH', 'A123B234': 'CRS-BTH',
    'A123B34': 'CRS-BTH', 'A23B34': 'CRS-BTH',
}
# 学期边界（仅用于审计文本；op.session 无 term 字段，不落库）
TERMS = [('第一学期', '2026-06-23', '2026-12-20'),
         ('第二学期', '2026-12-21', '2027-06-18')]

COURSE_LABEL = {'CRS-BTH': '神学学士科', 'CRS-BLA': '文学学士',
                'CRS-BED': '教育学学士'}
WEEKDAYS = '一二三四五六日'


def local_to_utc_naive(day, hhmm):
    """本地(Asia/Shanghai)日期+HH:MM → UTC naive datetime（入库口径）。"""
    hh, mm = hhmm.split(':')
    wall = TZ.localize(_dt.datetime(day.year, day.month, day.day,
                                    int(hh), int(mm)), is_dst=None)
    return wall.astimezone(UTC).replace(tzinfo=None)


def utc_naive_to_local(dt_naive):
    """UTC naive → Asia/Shanghai naive（导出/判重用）。"""
    return dt_naive.replace(tzinfo=UTC).astimezone(TZ).replace(tzinfo=None)


def _read_rows():
    """读取 sessions.csv（env SESSIONS_CSV 优先，其次宿主路径）。

    统一清除首列可能的 BOM（utf-8-sig 只在文件路径生效，env 字符串不生效）。
    """
    raw = os.environ.get('SESSIONS_CSV')
    if raw:
        rows = list(csv.DictReader(io.StringIO(raw)))
    else:
        with open(HOST_CSV, newline='', encoding='utf-8-sig') as fh:
            rows = list(csv.DictReader(fh))
    return [{k.lstrip('\ufeff'): v for k, v in r.items()} for r in rows]


def parse_rows():
    """读 CSV → 过滤裁决2 → 展开裁决3 → 返回 (raw, dropped, rows)。"""
    raw = _read_rows()
    rows, dropped = [], []
    for r in raw:
        kind = (r.get('kind') or '').strip()
        if RULING_DROP_KIND and RULING_DROP_KIND in kind:
            dropped.append(r)
            continue
        rows.append(r)
    expanded = []
    for r in rows:
        key = ((r['subject_name'] or '').strip(),
               (r['batch_label'] or '').strip())
        days = RULING_EXPAND.get(key)
        if not days:
            expanded.append(r)
            continue
        s, e = RULING_EXPAND_DAILY[key]
        for n, day in enumerate(days, 1):
            nr = dict(r)
            nr['date'] = day
            nr['start_time'] = s
            nr['end_time'] = e
            nr['lesson_no'] = (r.get('lesson_no') or '').strip()
            nr['kind'] = ''
            nr['time_source'] = 'default'
            raw_txt = (r.get('raw_text') or '').strip()
            nr['raw_text'] = (raw_txt + ' ;; 救恩论 A123 密集五天课第%d天' % n)
            nr['_expand_day'] = n
            expanded.append(nr)
    return raw, dropped, expanded


def _batch_course(code):
    """batch code → course code（裁决4 可配置）。"""
    if code in COURSE_OVERRIDES:
        return COURSE_OVERRIDES[code]
    if code in CROSS_BATCH_A_FIRST:
        return 'CRS-BTH'
    return BASE_BATCH_COURSE.get(code,
                                 'CRS-BTH' if code.startswith('A') else 'CRS-BLA')


def build_plan(rows):
    """由导入行生成档案计划：subjects/batches dict（供 dry-run 与真实导入）。"""
    subjects = {}
    batches = {}
    for r in rows:
        name = (r['subject_name'] or '').strip()
        if name and name not in subjects and name in SUBJECT_CODE_MAP:
            code, typ, styp = SUBJECT_CODE_MAP[name]
            subjects[name] = {'code': code, 'type': typ,
                              'subject_type': styp}
        bcode = (r['batch_label'] or '').strip()
        if bcode and bcode not in batches and bcode != 'CB34':
            batches[bcode] = {'name': BATCH_NAME_MAP.get(bcode, bcode),
                              'course_code': _batch_course(bcode)}
    for code in ALL_BATCH_CODES:
        if code not in batches:
            batches[code] = {'name': BATCH_NAME_MAP.get(code, code),
                             'course_code': _batch_course(code)}
    return subjects, batches


def plan_session_rows(rows, subjects, batches):
    """导入行 → session 计划 dicts（含 UTC 起止；同键去重）。"""
    plan = []
    for r in rows:
        name = (r['subject_name'] or '').strip()
        bcode = (r['batch_label'] or '').strip()
        if not name or not bcode:
            continue
        day = _dt.date.fromisoformat(r['date'])
        s_local = (r['start_time'] or '').strip() or '00:00'
        e_local = (r['end_time'] or '').strip() or s_local
        subj = subjects[name]
        batch = batches[bcode]
        plan.append({
            'date_local': day.isoformat(),
            'weekday': WEEKDAYS[day.weekday()],
            'start_local': s_local,
            'end_local': e_local,
            'start_utc': local_to_utc_naive(day, s_local),
            'end_utc': local_to_utc_naive(day, e_local),
            'subject_name': name,
            'subject_code': subj['code'],
            'batch_code': bcode,
            'course_code': batch['course_code'],
            'lesson_no': (r.get('lesson_no') or '').strip(),
            'kind': (r.get('kind') or '').strip(),
            'time_source': (r.get('time_source') or '').strip(),
            'raw_text': (r.get('raw_text') or '').strip(),
            'cell_ref': (r.get('cell_ref') or '').strip(),
            'source_sheet': (r.get('source_sheet') or '').strip(),
            '_expand_day': (r.get('_expand_day') or ''),
        })
    seen, uniq = set(), []
    for p in plan:
        k = (p['batch_code'], p['subject_code'], p['date_local'],
             p['start_local'])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)
    return uniq


# ============================ 冲突预检（四维） =========================
def check_conflicts(plan):
    """内联 upstream check_timetable_fields 的四维重叠逻辑。

    返回 (batch_conflicts, faculty_cross_pairs, classroom_conflicts)：
    - batch_conflicts：同一 batch 时间重叠（含同科目/不同科目）→ 真实冲突，
      必须为 0，否则拒绝导入（一个班不能同时上两门课）。
    - faculty_cross_pairs：不同 batch 之间同教师时间重叠的对数——由于全部课
      暂挂同一个占位「待定」教师（catalog §4.4 / §7 G），并行班在教师维的
      重叠属于结构性假象；真实教师逐个替换后自然消解，故不计为导入冲突，
      只作报告。
    - classroom_conflicts：未指定教室（catalog §4.5 / 裁决维持），恒 0。
    """
    by_batch = {}
    for p in plan:
        by_batch.setdefault(p['batch_code'], []).append(p)
    batch_conflicts = []
    for bcode, plist in by_batch.items():
        plist = sorted(plist, key=lambda p: (p['start_utc'], p['end_utc']))
        for i, a in enumerate(plist):
            for b in plist[i + 1:]:
                if b['start_utc'] >= a['end_utc']:
                    break
                if a['start_utc'] < b['end_utc']:
                    batch_conflicts.append((a, b))
    # 跨 batch 同教师重叠（全部课同一占位教师 → 任意跨班并行即重叠）
    allp = sorted(plan, key=lambda p: (p['start_utc'], p['end_utc']))
    faculty_cross_pairs = 0
    for i, a in enumerate(allp):
        for b in allp[i + 1:]:
            if b['start_utc'] >= a['end_utc']:
                break
            if (a['start_utc'] < b['end_utc']
                    and a['batch_code'] != b['batch_code']):
                faculty_cross_pairs += 1
    return batch_conflicts, faculty_cross_pairs, 0


# ============================ 导出 ====================================
PLAN_COLS = ['date_local', 'weekday', 'subject_name', 'subject_code',
             'batch_code', 'course_code', 'lesson_no', 'kind',
             'start_local', 'end_local', 'start_utc', 'end_utc',
             'source_sheet', 'cell_ref', 'time_source']


def write_plan_csv(plan, path):
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=PLAN_COLS, extrasaction='ignore')
        w.writeheader()
        for p in plan:
            row = dict(p)
            row['start_utc'] = p['start_utc'].strftime('%Y-%m-%d %H:%M:%S')
            row['end_utc'] = p['end_utc'].strftime('%Y-%m-%d %H:%M:%S')
            w.writerow(row)
    print('[export] 计划 CSV → %s（%d 行）' % (path, len(plan)))


def export_db_sessions(env, fac, path):
    """把本批次（占位教师）session 导出成 CSV，供 reviewer 比对。"""
    S = lambda m: env[m].sudo()
    sess = S('op.session').search([('faculty_id', '=', fac.id)],
                                  order='start_datetime asc')
    cols = ['id', 'name', 'date_local', 'weekday', 'subject', 'subject_code',
            'batch', 'course', 'start_local', 'end_local',
            'start_utc', 'end_utc', 'state', 'source_sheet', 'cell_ref']
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for s in sess:
            loc_s = utc_naive_to_local(s.start_datetime)
            loc_e = utc_naive_to_local(s.end_datetime)
            w.writerow({
                'id': s.id, 'name': s.name,
                'date_local': loc_s.date().isoformat(),
                'weekday': WEEKDAYS[loc_s.weekday()],
                'subject': s.subject_id.name,
                'subject_code': s.subject_id.code,
                'batch': s.batch_id.code, 'course': s.course_id.code,
                'start_local': loc_s.strftime('%H:%M'),
                'end_local': loc_e.strftime('%H:%M'),
                'start_utc': s.start_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'end_utc': s.end_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'state': s.state,
                'source_sheet': '', 'cell_ref': '',
            })
    print('[export] 库内明细 CSV → %s（%d 行）' % (path, len(sess)))
    return len(sess)


# ============================ 真实导入 ================================
def _run_import(env):
    S = lambda m: env[m].sudo()
    raw, dropped, rows = parse_rows()
    subjects, batches = build_plan(rows)
    plan = plan_session_rows(rows, subjects, batches)
    batch_conflicts, faculty_cross_pairs, classroom_conflicts = \
        check_conflicts(plan)

    print('=' * 72)
    print('[t2] 契约源 %d 行 → 裁决2 剔除师生互动 %d 行 → 裁决3 展开后 %d 行'
          % (len(raw), len(dropped), len(rows)))
    print('[t2] 导入计划 session 数（去重后）= %d' % len(plan))
    print('[t2] 档案计划：科目 %d · 批次 %d · 教师 1(待定) · 教室不指定'
          % (len(subjects), len(batches)))
    print('[t2] 冲突预检：同 batch 重叠 %d（须为 0，否则拒绝） · 跨 batch 同'
          '教师并行 %d 对（占位待定结构性重叠，真实教师替换后消解，只报告）'
          ' · 同教室 0（未指定）'
          % (len(batch_conflicts), faculty_cross_pairs))
    if batch_conflicts:
        print('[t2] ⚠ 同 batch 冲突明细（前 10）：')
        for a, b in batch_conflicts[:10]:
            print('   %s %s %s %s-%s <-> %s %s-%s' % (
                a['date_local'], a['batch_code'], a['subject_name'],
                a['start_local'], a['end_local'],
                b['subject_name'], b['start_local'], b['end_local']))
    print('=' * 72)
    if batch_conflicts:
        print('[t2] ✗ 存在同 batch 冲突，拒绝导入。')
        return {'ok': False, 'reason': 'same-batch conflicts',
                'plan': len(plan)}

    # ---------- 1. op.course 建档（幂等） ----------
    Course = S('op.course')
    course_by_code = {c.code: c for c in Course.search([])}
    for code in ('CRS-BTH', 'CRS-BLA', 'CRS-BED'):
        if code not in course_by_code:
            c = Course.create({'name': COURSE_LABEL[code], 'code': code,
                               'evaluation_type': 'GPA'})
            course_by_code[code] = c
            print('[t2] 新建 op.course', code, c.name)

    # ---------- 2. op.subject 建档（幂等，按 code 查重） ----------
    Subject = S('op.subject')
    subject_by_code = {s.code: s for s in Subject.search([])}
    created_subject = 0
    for name, meta in subjects.items():
        code = meta['code']
        obj = subject_by_code.get(code)
        if not obj:
            obj = Subject.search([('code', '=', code)], limit=1)
        if not obj:
            obj = Subject.create({'name': name, 'code': code,
                                  'type': meta['type'],
                                  'subject_type': meta['subject_type']})
            subject_by_code[code] = obj
            created_subject += 1
            print('[t2] 新建 op.subject', code, name)

    # ---------- 3. op.batch 建档（幂等，按 code 查重） ----------
    Batch = S('op.batch')
    batch_by_code = {b.code: b for b in Batch.search([])}
    created_batch = 0
    for code, meta in batches.items():
        obj = batch_by_code.get(code)
        if not obj:
            obj = Batch.search([('code', '=', code)], limit=1)
        if not obj:
            course = course_by_code[meta['course_code']]
            obj = Batch.create({'code': code, 'name': meta['name'],
                                'course_id': course.id,
                                'start_date': '2026-06-23',
                                'end_date': '2027-06-18'})
            batch_by_code[code] = obj
            created_batch += 1
            print('[t2] 新建 op.batch %-9s %-16s → %s' % (
                code, meta['name'], meta['course_code']))

    # ---------- 4. op.faculty 占位「待定」（幂等） ----------
    Faculty = S('op.faculty')
    fac = Faculty.search([('partner_id.ref', '=', FACULTY_PARTNER_REF)],
                         limit=1)
    if not fac:
        fac = Faculty.search([('first_name', '=', FACULTY_FIRST),
                              ('last_name', '=', FACULTY_LAST)], limit=1)
    if not fac:
        partner = S('res.partner').create({'name': FACULTY_PARTNER_NAME,
                                           'ref': FACULTY_PARTNER_REF})
        fac = Faculty.create({'partner_id': partner.id,
                              'first_name': FACULTY_FIRST,
                              'last_name': FACULTY_LAST,
                              'birth_date': FACULTY_BIRTH,
                              'gender': 'male'})
        partner.write({'name': FACULTY_PARTNER_NAME})
        print('[t2] 新建 op.faculty「待定」 id=%s partner=%s'
              % (fac.id, fac.partner_id.id))
    elif fac.partner_id.name != FACULTY_PARTNER_NAME:
        fac.partner_id.write({'name': FACULTY_PARTNER_NAME})

    # ---------- 5. op.timing 时间档（按 (start,end) 对建档/复用） ----------
    Timing = S('op.timing')
    timing_cache = {}

    def _get_timing(s_local, e_local):
        key = (s_local, e_local)
        if key in timing_cache:
            return timing_cache[key]
        sh, sm = s_local.split(':')
        eh, em = e_local.split(':')
        hour = str(int(sh) % 12 or 12)
        minute = sm if sm in ('00', '15', '30', '45') else \
            ('%02d' % (int(sm) // 15 * 15))
        am_pm = 'pm' if int(sh) >= 12 else 'am'
        dur = (int(eh) * 60 + int(em) - int(sh) * 60 - int(sm)) / 60.0
        name = '%s-%s' % (s_local, e_local)
        t = Timing.search([('name', '=', name)], limit=1)
        if not t:
            t = Timing.search([('hour', '=', hour), ('minute', '=', minute),
                               ('am_pm', '=', am_pm),
                               ('duration', '=', dur)], limit=1)
        if not t:
            t = Timing.create({'name': name[:16], 'hour': hour,
                               'minute': minute, 'am_pm': am_pm,
                               'duration': dur,
                               'sequence': int(sh) * 60 + int(sm)})
            print('[t2] 新建 op.timing %s (%s:%s %s, %sh)'
                  % (name, hour, minute, am_pm, dur))
        timing_cache[key] = t
        return t

    # ---------- 6. 幂等判重：库内既有 session 键 ----------
    Session = S('op.session')
    existing = {}
    for s in Session.search([]):
        if not (s.batch_id and s.subject_id and s.start_datetime):
            continue
        loc = utc_naive_to_local(s.start_datetime)
        key = (s.batch_id.code, s.subject_id.code,
               loc.date().isoformat(), loc.strftime('%H:%M'))
        existing.setdefault(key, s.id)
    to_create, skipped = [], 0
    for p in plan:
        key = (p['batch_code'], p['subject_code'], p['date_local'],
               p['start_local'])
        if key in existing:
            skipped += 1
            continue
        to_create.append(p)

    # ---------- 7. 批量 create_multi（守卫豁免 self 内互查） ----------
    vals_list = []
    for p in to_create:
        timing = _get_timing(p['start_local'], p['end_local'])
        name_parts = []
        if p['kind']:
            name_parts.append(p['kind'])
        if p['lesson_no']:
            name_parts.append(p['lesson_no'])
        name_parts.append(p['subject_name'])
        name_parts.append('[%s]' % p['batch_code'])
        name_parts.append('%s-%s' % (p['start_local'], p['end_local']))
        display = ' '.join(x for x in name_parts if x)
        vals_list.append({
            'name': display[:200],
            'course_id': batch_by_code[p['batch_code']].course_id.id,
            'batch_id': batch_by_code[p['batch_code']].id,
            'subject_id': subject_by_code[p['subject_code']].id,
            'faculty_id': fac.id,
            'timing_id': timing.id,
            'start_datetime': p['start_utc'].strftime('%Y-%m-%d %H:%M:%S'),
            'end_datetime': p['end_utc'].strftime('%Y-%m-%d %H:%M:%S'),
            'state': 'draft',
        })
    created = 0
    if vals_list:
        try:
            # tz 上下文：op.session.name 是存储计算字段，_compute_name 用
            # context_timestamp 按环境 tz 渲染——odoo shell 默认 __system__
            # 无 tz 会按 UTC 生成 06:00AM 之类误导名；显式 Asia/Shanghai 保证
            # name 显示为本地墙钟（14:00PM），与门户展示口径一致。
            sessions = Session.with_context(
                dont_notify=True, no_calendar_sync=True,
                tz=LOCAL_TZ).create(vals_list)
            sessions._compute_name()
            sessions.flush_recordset(['name'])
            created = len(sessions)
            print('[t2] op.session.create × %d 成功（ids %s..%s）'
                  % (created, sessions.ids[0], sessions.ids[-1]))
        except Exception as exc:
            env.cr.rollback()
            print('[t2] ✗ 批量 create 失败：%s' % str(exc)[:400])
            print('[t2] 已回滚，未写任何 session。')
            return {'ok': False, 'reason': 'create failed: %s' % str(exc)[:200],
                    'plan': len(plan)}

    # ---------- 8. 审计 ----------
    try:
        S('edu.audit.log')._log(
            '批量导入排课', 'op.session', 0, '',
            '导入 %d 节 · 幂等跳过 %d 节 · 计划 %d 节 · 教师=待定占位(TBD-TEACHER)'
            % (created, skipped, len(plan)))
        print('[t2] 审计 edu.audit.log 已写入')
    except Exception as exc:
        print('[t2] 审计写入失败（不阻断）:', str(exc)[:100])

    # ---------- 9. 导出供 reviewer 比对 ----------
    if os.path.isdir('/tmp'):
        # 容器内：固定路径，宿主用 docker compose cp 拉出
        plan_out = '/tmp/session_import_plan.csv'
        db_out = '/tmp/sessions_imported_local.csv'
    else:
        plan_out, db_out = PLAN_OUT, os.path.join(
            _BASE, 'timetable_import', 'sessions_imported_local.csv')
    write_plan_csv(plan, plan_out)
    export_db_sessions(env, fac, db_out)

    total = Session.search_count([])
    print('=' * 72)
    print('[t2] 完成：本次新建 %d · 幂等跳过 %d · 库内总 session %d · '
          '本批次(待定教师) %d' % (created, skipped, total,
                                Session.search_count(
                                    [('faculty_id', '=', fac.id)])))
    print('[t2] 全部建档/导入走 ORM + 审计，无裸 SQL。')
    try:
        env.cr.commit()          # odoo shell 默认不提交，必须显式持久化
        print('[t2] ✓ 已 commit 持久化')
    except Exception as exc:
        print('[t2] ✗ commit 失败:', str(exc)[:200])
        return {'ok': False, 'reason': 'commit failed',
                'plan': len(plan)}
    return {'ok': True, 'created': created, 'skipped': skipped,
            'plan': len(plan), 'total': total,
            'subjects': len(subjects), 'batches': len(batches),
            'db_export': db_out, 'plan_export': plan_out}


# ============================ dry-run =================================
def _dry_run():
    raw, dropped, rows = parse_rows()
    subjects, batches = build_plan(rows)
    plan = plan_session_rows(rows, subjects, batches)
    batch_conflicts, faculty_cross_pairs, classroom_conflicts = \
        check_conflicts(plan)
    print('=' * 72)
    print('[dry-run] 契约源 %d 行 → 剔除师生互动 %d → 展开后 %d 行'
          % (len(raw), len(dropped), len(rows)))
    print('[dry-run] 展开明细:', {('%s/%s' % k): v
                               for k, v in RULING_EXPAND.items()})
    print('[dry-run] 最终 session 计划（去重后）= %d' % len(plan))
    print('[dry-run] 同 batch 冲突 %d（须为 0） · 跨 batch 同教师并行 %d 对'
          '（占位待定，真实教师替换后消解） · 同教室 0（未指定）'
          % (len(batch_conflicts), faculty_cross_pairs))
    if batch_conflicts:
        print('[dry-run] ⚠ 同 batch 冲突明细（前 15）：')
        for a, b in batch_conflicts[:15]:
            print('   %s %s %s %s-%s <-> %s %s-%s' % (
                a['date_local'], a['batch_code'], a['subject_name'],
                a['start_local'], a['end_local'],
                b['subject_name'], b['start_local'], b['end_local']))
    print('-' * 72)
    print('[dry-run] 科目 %d：' % len(subjects))
    for name, m in subjects.items():
        print('   %-6s %-14s %s/%s' % (m['code'], name, m['type'],
                                       m['subject_type']))
    print('[dry-run] 批次 %d（→course）：' % len(batches))
    for code, m in batches.items():
        print('   %-9s %-16s → %s' % (code, m['name'], m['course_code']))
    print('[dry-run] 教师：%s 「%s%s」(CRS-BED 占位)' % (
        FACULTY_CODE, FACULTY_FIRST, FACULTY_LAST))
    write_plan_csv(plan, PLAN_OUT)
    return len(plan)


if __name__ == '__main__':
    if '--dry-run' in sys.argv:
        _dry_run()
    elif 'env' in globals():
        _run_import(env)
    else:
        print('[import_sessions] 请通过 odoo shell 运行（env 注入），'
              '或加 --dry-run 离线预检。', file=sys.stderr)
        sys.exit(1)