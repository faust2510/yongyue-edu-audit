# -*- coding: utf-8 -*-
"""永约学坊真实数据种子脚本（幂等，可反复重跑）

用法（在仓库根目录）：
    # 建立/刷新骨架 + 最小【演示】运营数据
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db -r odoo -w odoo -d edu19 --no-http < scripts/seed_yongyue_data.py

    # 清场模式：删除全部【演示】标记数据后仍保留真实骨架（开学前用）
    SEED_PURGE=1 docker compose exec -T web odoo shell ... < scripts/seed_yongyue_data.py

原则（2025-08 拷问定案）：
- 幻觉数据一律删除（CS课程/假科目/假教师/假书/假账单）
- 真实骨架：6 个大学部体系专业；圣经高中不进系统
- 科目只填预备科 14 门（内容以公开官网 /programs 页为准）
- 所有临时运营数据必须带「【演示】」标记，绝不出现拟真姓名/拟真成绩
"""
import datetime
import os

DEMO = "【演示】"
PURGE = os.environ.get("SEED_PURGE") == "1"
env = env  # odoo shell 注入
S = lambda m: env[m].sudo()

def drop(records, label=""):
    n = 0
    for r in records:
        try:
            r.unlink(); n += 1
        except Exception as e:
            print("  ! 无法删除", label or r._name, r.id, str(e)[:80])
            env.cr.rollback()
    return n

print("=" * 30, "A. 清除幻觉演示库数据", "=" * 30)
fake_courses = S('op.course').search([('name', '=', '计算机科学与技术')])
if fake_courses:
    regs = S('op.subject.registration').search([('course_id', 'in', fake_courses.ids)])
    print(" 选课记录", drop(regs))
    scs = S('op.student.course').search([('course_id', 'in', fake_courses.ids)])
    print(" 学生选课", drop(scs))
    atts = S('op.attendance.line').search([('attendance_id.register_id.course_id', 'in', fake_courses.ids)])
    print(" 考勤行", drop(atts))
    print(" 考勤表", drop(S('op.attendance.sheet').search([('register_id.course_id', 'in', fake_courses.ids)])))
    print(" 考勤登记", drop(S('op.attendance.register').search([('course_id', 'in', fake_courses.ids)])))
    sess = S('op.session').search([('course_id', 'in', fake_courses.ids)])
    print(" 课节", drop(sess))
    env.cr.commit()
    if 'op.assignment.sub.line' in env:
        subs = S('op.assignment.sub.line').search(
            [('assignment_id.course_id', 'in', fake_courses.ids)])
        for sl in subs:
            try:
                sl.state = 'draft'
            except Exception:
                env.cr.rollback()
        print(" 作业提交", drop(subs))
    ms_lines = S('op.marksheet.line').search([])
    rl = S('op.result.line').search([('marksheet_line_id', 'in', ms_lines.ids)])
    print(" 成绩明细", drop(rl)); print(" 成绩行", drop(ms_lines))
    exams = S('op.exam').search([('course_id', 'in', fake_courses.ids)])
    print(" 考试出席", drop(S('op.exam.attendees').search([('exam_id', 'in', exams.ids)])))
    print(" 考试", drop(exams))
    # 兜底：按科目再扫一遍残留考试（防 course 为空的孤儿数据）
    _fsubj = S('op.subject').search([('name', 'in',
        ["高等数学", "大学英语", "数据结构", "操作系统", "体育"])])
    _ex2 = S('op.exam').search([('subject_id', 'in', _fsubj.ids)])
    if _ex2:
        drop(S('op.exam.attendees').search([('exam_id', 'in', _ex2.ids)]))
        print(" 残留考试(按科目)", drop(_ex2))
    env.cr.commit()
    _ess = S('op.exam.session').search(
        ['|', ('course_id', 'in', fake_courses.ids),
              ('batch_id.course_id', 'in', fake_courses.ids)])
    if _ess:
        print(" 成绩登记册", drop(S('op.marksheet.register').search(
            [('exam_session_id', 'in', _ess.ids)])))
        print(" 成绩单模板", drop(S('op.result.template').search(
            [('exam_session_id', 'in', _ess.ids)])))
        drop(S('op.result.line').search([('session_id', 'in', _ess.ids)]))
        print(" 考试学期", drop(_ess))
        env.cr.commit()
    asg = S('op.assignment').search([('course_id', 'in', fake_courses.ids)])
    for a in asg:
        try:
            a.state = 'draft'
        except Exception:
            env.cr.rollback()
    print(" 作业", drop(asg))
    if 'grading.assignment' in env:
        print(" 孤儿评分作业", drop(S('grading.assignment').search(
            [('course_id', 'in', fake_courses.ids)])))
        env.cr.commit()
    print(" 批次", drop(S('op.batch').search([('course_id', 'in', fake_courses.ids)])))
    print(" 课程", drop(fake_courses))
    env.cr.commit()

for nm in ["高等数学", "大学英语", "数据结构", "操作系统", "体育"]:
    s = S('op.subject').search([('name', '=', nm), ('code', 'not like', 'PRP-%')])
    if s: print(" 假科目", nm, drop(s))

keep_logins = {"stu@local", "parent@local", "faculty@local"}
for fac in S('op.faculty').search([]):
    login = fac.user_id.login if fac.user_id else ""
    full = (fac.last_name or "") + (fac.first_name or "")
    if login == "faculty@local":
        continue  # 稍后改名为演示导师
    if full in ("李强", "张红", "刘国") or (login and login not in keep_logins):
        print(" 假教师", full or fac.id, drop(fac))

FAKE_MEDIA_IDS = lambda: S('op.media').search([('name', 'in', FAKE_MEDIA)]).ids
FAKE_MEDIA = ["Python 编程：从入门到实践", "算法导论（第四版）", "深入理解计算机系统",
              "高等数学（同济第七版）", "大学英语综合教程", "程序员修炼之道",
              "电脑报（月刊）", "科技前沿季刊"]
_ids = FAKE_MEDIA_IDS()
if _ids:
    print(" 借阅记录", drop(S('op.media.movement').search([('media_id', 'in', _ids)])))
    for extra in ('op.issue.media', 'op.return.media'):
        if extra in env:
            drop(S(extra).search([('media_unit_id.media_id', 'in', _ids)]))
    print(" 预约队列", drop(S('op.media.queue').search([('media_id', 'in', _ids)])))
    if 'op.media.unit' in env:
        print(" 册单元", drop(S('op.media.unit').search([('media_id', 'in', _ids)])))
    print(" 假图书", drop(S('op.media').search([('id', 'in', _ids)])))
    env.cr.commit()
_cards = S('op.library.card').search([])
if _cards:
    for m_ in ('op.faculty', 'op.student'):
        S(m_).search([('library_card_id', 'in', _cards.ids)]).write({'library_card_id': False})
    for mm_ in ('op.media.movement',):
        print(" 卡流通", drop(mm_ and S(mm_).search([('library_card_id', 'in', _cards.ids)])))
    if 'op.issue.media' in env:
        print(" 卡签发", drop(S('op.issue.media').search([('library_card_id', 'in', _cards.ids)])))
    print(" 假借书卡", drop(_cards))
env.cr.commit()

inv = S('account.move').search([('move_type', '=', 'out_invoice')])
n = 0
for mv in inv:
    try:
        if mv.state == 'draft':
            mv.unlink()
        else:
            mv.button_draft(); mv.button_cancel(); mv.unlink()
        n += 1
    except Exception as e:
        print("  ! 发票", mv.id, str(e)[:70])
print(" 假账单", n)

print("=" * 30, "B. 大学部专业骨架（6 个）", "=" * 30)
COURSES = [
    ("CRS-MCS", "基督教研究硕士科"),
    ("CRS-BTH", "神学学士科"),
    ("CRS-BLA", "文学学士"),
    ("CRS-BED", "教育学士"),
    ("CRS-HSA", "家教学院"),
    ("CRS-PRP", "预备科"),
]
courses = {}
for code, name in COURSES:
    c = S('op.course').search([('code', '=', code)], limit=1)
    if not c:
        c = S('op.course').create({'name': name, 'code': code,
                                   'evaluation_type': 'GPA'})
    elif c.name != name:
        c.name = name
    courses[code] = c
    print(" 课程", code, c.name)

SUBJECTS = [
    ("小要理问答", "theory", "compulsory"), ("基础信仰", "theory", "compulsory"),
    ("圣经概论（新旧约概论）", "theory", "compulsory"), ("圣经救赎历史", "theory", "compulsory"),
    ("阅读课程", "other", "compulsory"), ("古汉语课程", "theory", "compulsory"),
    ("写作课程", "theory", "compulsory"), ("英语课程", "theory", "compulsory"),
    ("原文基础课程", "theory", "compulsory"), ("灵命塑造课程", "other", "compulsory"),
    ("文史哲综合备考课", "theory", "compulsory"), ("选修课程", "other", "elective"),
    ("意志和技能课程", "other", "compulsory"), ("游历课程", "other", "compulsory"),
]
prp = courses["CRS-PRP"]
subj_ids = []
for i, (nm, typ, styp) in enumerate(SUBJECTS, 1):
    code = "PRP-C%02d" % i
    s = S('op.subject').search([('code', '=', code)], limit=1)
    if not s:
        s = S('op.subject').create({'name': nm, 'code': code,
                                    'type': typ, 'subject_type': styp})
    subj_ids.append(s.id)
prp.subject_ids = [(6, 0, subj_ids)]
print(" 预备科科目", len(subj_ids), "门")

batch = S('op.batch').search([('code', '=', 'PRP-2026')], limit=1)
if not batch:
    today = datetime.date.today()
    batch = S('op.batch').create({
        'name': '预备科 · 2026级' + DEMO, 'code': 'PRP-2026',
        'course_id': prp.id,
        'start_date': today, 'end_date': today + datetime.timedelta(days=700)})
print(" 班级", batch.name)
env.cr.commit()

print("=" * 30, "C. 教师（占位，不编真人名）", "=" * 30)
fu = S('res.users').search([('login', '=', 'faculty@local')], limit=1)
fac = S('op.faculty').search([('user_id', '=', fu.id)], limit=1) if fu else S('op.faculty')
if fu and not fac:
    fac = S('op.faculty').create({
        'first_name': '导师' + DEMO, 'last_name': '预备科',
        'gender': 'male', 'birth_date': '1990-09-01',
        'partner_id': fu.partner_id.id, 'user_id': fu.id})
elif fac:
    fac.write({'first_name': '导师' + DEMO, 'last_name': '预备科',
               'gender': 'male'})
if fu:
    _gu = env.ref('base.group_user', raise_if_not_found=False)
    _gp = env.ref('base.group_portal', raise_if_not_found=False)
    try:
        if _gp and _gp in fu.group_ids:
            fu.group_ids = [(3, _gp.id)]
        if _gu and _gu not in fu.group_ids:
            fu.group_ids = [(4, _gu.id)]
        print(" 已将 faculty@local 升级为内部用户（可进后台审批）")
    except Exception as e:
        print("  ! 组调整失败:", str(e)[:100]); env.cr.rollback()
    try:
        _nm = {'name': '预备科导师' + DEMO}
        fac.partner_id.write(_nm)
        if fu.partner_id and fu.partner_id != fac.partner_id:
            fu.partner_id.write(_nm)
    except Exception as e:
        print("  ! 教师改名失败:", str(e)[:80]); env.cr.rollback()
print(" 教师记录:", fac and ((fac.last_name or '') + (fac.first_name or '')), "user:", fu.login if fu else "无")

print("=" * 30, "D. 演示学生选课", "=" * 30)
su = S('res.users').search([('login', '=', 'stu@local')], limit=1)
stu = S('op.student').search([('user_id', '=', su.id)], limit=1) if su else S('op.student')
sc = S('op.student.course').search([('student_id', '=', stu.id), ('course_id', '=', prp.id)], limit=1)
if not sc and stu:
    sc = S('op.student.course').create({
        'student_id': stu.id, 'course_id': prp.id, 'batch_id': batch.id,
        'roll_number': 'PRP26-001'})
print(" 选课:", sc and (sc.roll_number or sc.id))

if PURGE:
    print("=" * 30, "P. 清场：移除全部演示运营数据", "=" * 30)
    pat = '%' + DEMO
    _b = S('op.batch').search([('code', '=', 'PRP-2026')], limit=1)
    if _b:
        print(" 课节", drop(S('op.session').search([('batch_id', '=', _b.id)])))
    _regs = S('op.attendance.register').search([('code', '=', 'ATT-PRP-DEMO')])
    if _regs:
        print(" 考勤行", drop(S('op.attendance.line').search(
            [('attendance_id.register_id', 'in', _regs.ids)])))
        print(" 考勤表", drop(S('op.attendance.sheet').search(
            [('register_id', 'in', _regs.ids)])))
        print(" 考勤登记", drop(_regs))
    print(" 作业", drop(S('op.assignment').search([('name', 'like', pat)])))
    _stu = S('op.student').search([('user_id.login', '=', 'stu@local')], limit=1)
    _ms = S('op.marksheet.line').search([('student_id', '=', _stu.id)]) if _stu else S('op.marksheet.line')
    print(" 成绩明细", drop(S('op.result.line').search(['|', ('marksheet_line_id', 'in', _ms.ids), ('exam_id', 'like', '%' + DEMO)])))
    print(" 成绩行", drop(_ms))
    exs = S('op.exam').search([('name', 'like', pat)])
    drop(S('op.exam.attendees').search([('exam_id', 'in', exs.ids)]))
    print(" 考试", drop(exs))
    print(" 图书", drop(S('op.media').search(['|', ('internal_code', '=like', 'YUE-BOOK%'), ('name', 'like', pat)])))
    env.cr.commit()
    env.cr.commit()
    print("PURGE DONE —— 真实骨架保留，运营数据已清场")
else:
    print("=" * 30, "E. 最小演示运营数据（全部带标记）", "=" * 30)
    # 先清旧演示再重建，保证日期始终向前有效。
    # 注意：op.session 的 name 由模块按「教师:科目:时间」自动重写，
    # 不能用名字匹配，必须按批次范围清。
    drop(S('op.session').search([('batch_id', '=', batch.id)]))
    _regs = S('op.attendance.register').search([('code', '=', 'ATT-PRP-DEMO')])
    if _regs:
        drop(S('op.attendance.line').search(
            [('attendance_id.register_id', 'in', _regs.ids)]))
        drop(S('op.attendance.sheet').search(
            [('register_id', 'in', _regs.ids)]))

    base = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    day = base + datetime.timedelta(days=1)
    weekdays = []
    while len(weekdays) < 10:
        if day.weekday() < 5:
            weekdays.append(day)
        day += datetime.timedelta(days=1)
    rot = [("小要理问答", 10, 8, 0), ("圣经概论（新旧约概论）", 11, 9, 0),
           ("古汉语课程", 12, 10, 30)]
    subj_by_name = {s.name: s for s in S('op.subject').browse(subj_ids)}
    timings = {t.id: t for t in S('op.timing').browse([r[1] for r in rot])}
    n = 0
    for d in weekdays:
        for nm, tid, hh, mm_ in rot:
            st = d.replace(hour=hh, minute=mm_)
            S('op.session').create({
                'name': '%s · %s%s' % (nm, timings[tid].name, DEMO),
                'course_id': prp.id, 'batch_id': batch.id,
                'subject_id': subj_by_name[nm].id,
                'faculty_id': fac.id,
                'timing_id': tid, 'start_datetime': st,
                'end_datetime': st + datetime.timedelta(minutes=45)})
            n += 1
    print(" 课节", n)

    reg = S('op.attendance.register').search([('code', '=', 'ATT-PRP-DEMO')], limit=1)
    if not reg:
        reg = S('op.attendance.register').create({
            'name': '预备科考勤登记' + DEMO, 'code': 'ATT-PRP-DEMO',
            'course_id': prp.id, 'batch_id': batch.id})
    stat = ['present', 'present', 'absent', 'present', 'late', 'present']
    m = 0
    for i, d in enumerate(weekdays[:len(stat)]):
        sheet = S('op.attendance.sheet').create({
            'name': '考勤表%s %s' % (DEMO, d.date()),
            'register_id': reg.id, 'course_id': prp.id, 'batch_id': batch.id,
            'attendance_date': d.date(), 'faculty_id': fac.id})
        st = stat[i]
        S('op.attendance.line').create({
            'attendance_id': sheet.id, 'student_id': stu.id,
            'present': st in ('present', 'late'), 'late': st == 'late',
            'absent': st == 'absent', 'excused': False})
        m += 1
    print(" 考勤表", m)

    at = S('grading.assignment.type').search([], limit=1)
    if not at:
        at = S('grading.assignment.type').create({'name': '课后作业',
                                                  'code': 'HW'})
    drop(S('op.assignment').search([('name', 'like', '%' + DEMO)]))
    a1 = S('op.assignment').create({
        'name': '小要理问答背诵检查' + DEMO, 'assignment_type': at.id,
        'course_id': prp.id, 'batch_id': batch.id, 'faculty_id': fac.id,
        'issued_date': datetime.datetime.now(),
        'submission_date': datetime.datetime.now() + datetime.timedelta(days=7),
        'description': '背诵《威斯敏斯特小要理问答》第一至三问及对应经文。',
        'state': 'publish', 'marks': 100})
    a2 = S('op.assignment').create({
        'name': '《天路历程》阅读报告' + DEMO, 'assignment_type': at.id,
        'course_id': prp.id, 'batch_id': batch.id, 'faculty_id': fac.id,
        'issued_date': datetime.datetime.now(),
        'submission_date': datetime.datetime.now() + datetime.timedelta(days=14),
        'description': '按指定格式撰写阅读报告，并准备书评报告陈述。',
        'state': 'publish', 'marks': 100})
    print(" 作业", a1.id, a2.id)

    drop(S('op.exam.attendees').search([('student_id', '=', stu.id)]))
    es = S('op.exam.session').search([('exam_code', '=', 'EXS-DEMO')], limit=1)
    if not es:
        et = S('op.exam.type').search([], limit=1)
        if not et:
            et = S('op.exam.type').create({'name': '阶段考'})
        es = S('op.exam.session').create({
            'name': '2026 第一学期考试' + DEMO, 'exam_code': 'EXS-DEMO',
            'course_id': prp.id, 'batch_id': batch.id,
            'evaluation_type': 'grade',
            'exam_type': et.id if et else False,
            'start_date': datetime.date.today(),
            'end_date': datetime.date.today() + datetime.timedelta(days=30)})
    old_ex = S('op.exam').search([('exam_code', 'like', '%DEMO%')])
    rl_old = S('op.result.line').search([('exam_id', 'in', old_ex.ids)])
    drop(rl_old)
    drop(old_ex)
    exam_state_vals = [v[0] for v in S('op.exam')._fields['state'].selection] \
        if 'state' in S('op.exam')._fields and S('op.exam')._fields['state'].selection else []
    ex_kwargs = {'state': 'scheduled'} if 'scheduled' in exam_state_vals else {}
    exam = S('op.exam').create({
        'name': '阶段考一 · 小要理问答' + DEMO, 'exam_code': 'EX-DEMO-01',
        'session_id': es.id,
        'subject_id': subj_by_name['小要理问答'].id,
        'total_marks': 100, 'min_marks': 60,
        'start_time': base + datetime.timedelta(days=8, hours=9),
        'end_time': base + datetime.timedelta(days=8, hours=10, minutes=30),
        **ex_kwargs})
    S('op.exam.attendees').create({
        'exam_id': exam.id, 'student_id': stu.id,
        'status': 'present', 'marks': 92})
    print(" 考试", exam.name)

    ms_old = S('op.marksheet.line').search([('student_id', '=', stu.id)])
    drop(S('op.result.line').search(['|', ('marksheet_line_id', 'in', ms_old.ids),
                                    ('exam_id', 'in', old_ex.ids)]))
    drop(ms_old)
    ms = None
    try:
        ms = S('op.marksheet.line').create({
            'student_id': stu.id, 'generated_date': datetime.date.today(),
            'evaluation_type': 'GPA', 'percentage': 92.0,
            'grade': 'A', 'status': 'pass', 'total_marks': 100})
        S('op.result.line').create({
            'exam_id': exam.id, 'marks': 92, 'student_id': stu.id,
            'marksheet_line_id': ms.id, 'evaluation_type': 'GPA',
            'grade': 'A', 'status': 'pass'})
        print(" 成绩行 OK", ms.id)
    except Exception as e:
        if ms: drop(ms)
        print("  ! 成绩行失败（成绩簿页将显示空态）:", str(e)[:120])

    print("-" * 20, "图书馆书单段已按校方要求移除（2026-08-23）", "-" * 20)

env.cr.commit()
print("SEED DONE")
