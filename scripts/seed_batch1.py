# -*- coding: utf-8 -*-
"""第二批演示数据：考勤记录 / 考试 / 作业 / 活动（为 stu@local 的学生造数）。

用法（严禁管道接 head，防止 SIGPIPE 中断导致不提交）：
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
    -r odoo -w odoo -d edu19 --no-http < scripts/seed_batch1.py > /tmp/sb1.txt 2>&1
"""
import datetime

env = env

def mk(model, vals, tag):
    try:
        rec = model.create(vals)
        print("OK %s" % tag)
        return rec
    except Exception as e:
        print("ERR %s: %s" % (tag, str(e).replace("\n", " ")[:220]))
        return None

def mk_sp(model, vals, tag):
    """savepoint 包裹的 create，防止单条失败污染事务。"""
    try:
        with env.cr.savepoint():
            rec = model.create(vals)
        print("OK %s" % tag)
        return rec
    except Exception as e:
        print("ERR %s: %s" % (tag, str(e).replace("\n", " ")[:220]))
        return None

today = datetime.date.today()

# ---------- 学生 / 课程 / 班级 ----------
user = env['res.users'].search([('login', '=', 'stu@local')], limit=1)
student = env['op.student'].search([('user_id', '=', user.id)], limit=1) \
    if user else False
if not student:
    print("ERR STUDENT_NOT_FOUND")
    env.cr.rollback()
    raise SystemExit(1)
print("STUDENT id=%d name=%s" % (student.id, student.name))

sc = env['op.student.course'].search(
    [('student_id', '=', student.id)], limit=1)
course = sc.course_id
batch = sc.batch_id
if not course or not batch:
    print("ERR NO_STUDENT_COURSE")
    env.cr.rollback()
    raise SystemExit(1)
print("COURSE id=%d batch id=%d" % (course.id, batch.id))

# 把已有科目挂到学生课程上（档案页 Subjects 标签）
if not sc.subject_ids:
    subs_all = env['op.subject'].search([], order='id asc')
    if subs_all:
        try:
            with env.cr.savepoint():
                sc.write({'subject_ids': [(6, 0, subs_all.ids)]})
            print("OK SUBJECTS-LINK (%d)" % len(subs_all))
        except Exception as e:
            print("ERR SUBJECTS-LINK: %s" % str(e).replace("\n", " ")[:200])

subjects = env['op.subject'].search([], order='id asc')
faculties = env['op.faculty'].search([], order='id asc')
if not subjects or not faculties:
    print("ERR NEED_SUBJECTS_AND_FACULTIES (先跑 seed_demo.py)")
    env.cr.rollback()
    raise SystemExit(1)

# ---------- 补全学生档案信息（让 /student/profile 更丰满） ----------
partner = student.partner_id
try:
    with env.cr.savepoint():
        if not student.blood_group:
            student.blood_group = 'A-'
        if not student.nationality:
            cn = env['res.country'].search([('code', '=', 'CN')], limit=1)
            if cn:
                student.nationality = cn.id
        if not partner.phone:
            partner.phone = '13800001234'
        if not partner.street:
            partner.street = '朝阳区望京街道 1 号'
        if not partner.city:
            partner.city = '北京市'
        if not partner.email:
            partner.email = 'stu@local'
    print("OK PROFILE-ENRICH")
except Exception as e:
    print("ERR PROFILE-ENRICH: %s" % str(e).replace("\n", " ")[:200])

# ---------- 1) 考勤：register -> sheet -> line ----------
if not env['op.attendance.line'].search_count(
        [('student_id', '=', student.id)]):
    regs = []
    for i, sub in enumerate(subjects[:3]):
        reg = mk_sp(env['op.attendance.register'], {
            'name': '考勤登记-%d' % (i + 1),
            'code': 'ATTREG%d' % (i + 1),
            'course_id': course.id,
            'batch_id': batch.id,
            'subject_id': sub.id,
        }, 'ATTREG %d' % (i + 1))
        if reg:
            regs.append(reg)
    n_lines = 0
    for ri, reg in enumerate(regs):
        for d in range(14):  # 近 14 天每天一张表
            adate = today - datetime.timedelta(days=d)
            sheet = mk_sp(env['op.attendance.sheet'], {
                'register_id': reg.id,
                'attendance_date': adate,
                'state': 'done',
            }, 'SHEET r%d d%d' % (ri, d))
            if not sheet:
                continue
            # 确定性出席模式：约 2/3 出席
            present = (ri + d) % 3 != 0
            line = mk_sp(env['op.attendance.line'], {
                'attendance_id': sheet.id,
                'student_id': student.id,
                'present': present,
                'absent': not present,
                'remark': '演示数据',
            }, 'LINE r%d d%d %s' % (ri, d, 'P' if present else 'A'))
            if line:
                n_lines += 1
    print("ATTENDANCE LINES CREATED: %d" % n_lines)
else:
    print("SKIP attendance (已有考勤数据)")

# ---------- 2) 考试：session -> exam -> attendees ----------
if not env['op.exam.attendees'].search_count(
        [('student_id', '=', student.id)]):
    ex_type = env['op.exam.type'].search([('code', '=', 'SES')], limit=1)
    if not ex_type:
        ex_type = mk_sp(env['op.exam.type'], {
            'name': '阶段考', 'code': 'SES'}, 'EXAM-TYPE')
    session = mk_sp(env['op.exam.session'], {
        'name': '2026 第一学期期末考试',
        'course_id': course.id,
        'batch_id': batch.id,
        'exam_code': 'EXSESS1',
        'start_date': today - datetime.timedelta(days=15),
        'end_date': today + datetime.timedelta(days=15),
        'exam_type': ex_type.id,
        'state': 'held',
    }, 'EXAM-SESSION')
    if session:
        marks = [82, 67, 91, 38, 55]  # 1 门不及格（38 < 40）
        for i, sub in enumerate(subjects):
            st = datetime.datetime.combine(
                today - datetime.timedelta(days=10 - i * 2),
                datetime.time(9, 0)) + datetime.timedelta(hours=i * 2)
            en = st + datetime.timedelta(hours=2)
            exam = mk_sp(env['op.exam'], {
                'session_id': session.id,
                'subject_id': sub.id,
                'exam_code': 'EX%02d' % (i + 1),
                'name': '%s-期末考试' % sub.name,
                'start_time': st,
                'end_time': en,
                'total_marks': 100,
                'min_marks': 40,
                'state': 'result_updated',
            }, 'EXAM %s' % sub.name)
            if exam:
                att = mk_sp(env['op.exam.attendees'], {
                    'exam_id': exam.id,
                    'student_id': student.id,
                    'status': 'present',
                    'marks': marks[i] if i < len(marks) else 60,
                }, 'ATTENDEE %s %d' % (sub.name, marks[i] if i < len(marks) else 60))
else:
    print("SKIP exam (已有考试数据)")

# ---------- 3) 作业：grading.assignment.type -> op.assignment -> sub.line ----------
if not env['op.assignment'].search_count(
        [('batch_id', '=', batch.id)]):
    asg_type = env['grading.assignment.type'].search(
        [('code', '=', 'HW')], limit=1)
    if not asg_type:
        asg_type = mk_sp(env['grading.assignment.type'], {
            'name': '课后作业', 'code': 'HW'}, 'ASG-TYPE')
    fac = faculties[0]
    names = [('数据结构-课后练习', 0), ('操作系统-实验报告', 1),
             ('高等数学-微积分作业', 2), ('大学英语-作文', 3)]
    for i, (nm, si) in enumerate(names):
        sub = subjects[si % len(subjects)]
        issued = today - datetime.timedelta(days=12 - i * 2)
        deadline = today + datetime.timedelta(days=5 + i)
        state = 'publish' if i < 3 else 'finish'
        asg = mk_sp(env['op.assignment'], {
            'name': nm,
            'course_id': course.id,
            'batch_id': batch.id,
            'subject_id': sub.id,
            'issued_date': datetime.datetime.combine(issued, datetime.time(9, 0)),
            'submission_date': datetime.datetime.combine(deadline, datetime.time(23, 59)),
            'assignment_type': asg_type.id,
            'faculty_id': fac.id,
            'description': '请在截止日期前完成并提交，逾期按 0 分处理。',
            'state': state,
            'marks': 100,
        }, 'ASSIGN %s' % nm)
        if asg and (i == 0 or i == 3):
            # 已提交的作业：1 个发布中已交，1 个已结束已交
            sub_state = 'submit' if i == 0 else 'accept'
            mk_sp(env['op.assignment.sub.line'], {
                'assignment_id': asg.id,
                'student_id': student.id,
                'state': sub_state,
                'description': '这是我的作业提交，请查收。',
                'submission_date': datetime.datetime.combine(
                    today - datetime.timedelta(days=1), datetime.time(20, 0)),
                'marks': 88 if i == 0 else 92,
            }, 'SUBLINE %s' % nm)
else:
    print("SKIP assignment (已有作业数据)")

# ---------- 4) 活动（档案页 活动/成就 标签） ----------
if not env['op.activity'].search_count(
        [('student_id', '=', student.id)]):
    act_type = env['op.activity.type'].search(
        [('name', '=', '课堂展示')], limit=1)
    if not act_type:
        act_type = mk_sp(env['op.activity.type'], {
            'name': '课堂展示'}, 'ACT-TYPE')
    mk_sp(env['op.activity'], {
        'student_id': student.id,
        'faculty_id': faculties[0].id,
        'type_id': act_type.id,
        'description': '课堂展示：数据结构专题讲解，表现良好。',
        'date': today - datetime.timedelta(days=8),
    }, 'ACTIVITY 1')
    mk_sp(env['op.activity'], {
        'student_id': student.id,
        'faculty_id': faculties[1].id,
        'type_id': act_type.id,
        'description': '校内程序设计比赛参与奖。',
        'date': today - datetime.timedelta(days=25),
    }, 'ACTIVITY 2')
else:
    print("SKIP activity (已有活动数据)")

# ---------- 汇总 ----------
print("COUNTS student=%d course=%d batch=%d subject=%d faculty=%d "
      "att_line=%d exam=%d attendee=%d assignment=%d subline=%d activity=%d" % (
    env['op.student'].search_count([]),
    env['op.course'].search_count([]),
    env['op.batch'].search_count([]),
    env['op.subject'].search_count([]),
    env['op.faculty'].search_count([]),
    env['op.attendance.line'].search_count([('student_id', '=', student.id)]),
    env['op.exam'].search_count([]),
    env['op.exam.attendees'].search_count([('student_id', '=', student.id)]),
    env['op.assignment'].search_count([]),
    env['op.assignment.sub.line'].search_count([('student_id', '=', student.id)]),
    env['op.activity'].search_count([('student_id', '=', student.id)])))
env.cr.commit()
print("COMMITTED")
