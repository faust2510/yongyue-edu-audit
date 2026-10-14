# -*- coding: utf-8 -*-
"""批次3演示数据：请假（edu.leave）/ 申诉（edu.grievance）/ 科目注册 /
学术日历（学年学期）/ 追加一条图书预约请求。

用法（严禁管道接 head，防止 SIGPIPE 中断导致不提交）：
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
    -r odoo -w odoo -d edu19 --no-http < scripts/seed_batch3.py > /tmp/sb3.txt 2>&1
"""
import datetime

env = env


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

user = env['res.users'].search([('login', '=', 'stu@local')], limit=1)
student = env['op.student'].search([('user_id', '=', user.id)], limit=1) \
    if user else False
if not student:
    print("ERR STUDENT_NOT_FOUND")
    env.cr.rollback()
    raise SystemExit(1)
print("STUDENT id=%d name=%s partner=%d" % (
    student.id, student.name, student.partner_id.id))

sc = env['op.student.course'].search(
    [('student_id', '=', student.id)], limit=1)
course = sc.course_id if sc else False
batch = sc.batch_id if sc else False

# =====================================================================
# 1) 请假 edu.leave：1 条待审批（sick）+ 1 条已批准（legal）
# =====================================================================
if env['edu.leave'].search_count([('student_id', '=', student.id)]) < 2:
    mk_sp(env['edu.leave'], {
        'name': 'SLR000001',
        'student_id': student.id,
        'leave_type': 'sick',
        'date_from': today - datetime.timedelta(days=3),
        'date_to': today + datetime.timedelta(days=4),
        'state': 'request',
        'reason': '感冒发烧，遵医嘱休息一周，请假期间课程内容会自行补上。',
    }, 'LEAVE SLR000001')
    mk_sp(env['edu.leave'], {
        'name': 'SLR000002',
        'student_id': student.id,
        'leave_type': 'legal',
        'date_from': today + datetime.timedelta(days=10),
        'date_to': today + datetime.timedelta(days=12),
        'state': 'approved',
        'reason': '参加家庭重要事务，已提前与辅导员沟通并获批。',
    }, 'LEAVE SLR000002')
else:
    print("SKIP leave (已有请假数据)")

# =====================================================================
# 2) 申诉 edu.grievance：2 条（已提交 + 审查中）
# =====================================================================
if env['edu.grievance'].search_count([('student_id', '=', student.id)]) < 2:
    mk_sp(env['edu.grievance'], {
        'name': 'GRI0001',
        'student_id': student.id,
        'subject': '成绩复核申请',
        'category': '学业 / 成绩问题',
        'description': '对第一学期《数据结构》成绩存在疑问，申请复核。',
        'state': 'submitted',
        'date': today,
    }, 'GRIEVANCE GRI0001')
    mk_sp(env['edu.grievance'], {
        'name': 'GRI0003',
        'student_id': student.id,
        'subject': '宿舍服务异常',
        'category': '非学业 / 交通与住宿问题',
        'description': '宿舍楼热水供应时段不稳定，影响晚间学习。',
        'state': 'in_progress',
        'date': today,
    }, 'GRIEVANCE GRI0003')
else:
    print("SKIP grievance (已有申诉数据)")

# =====================================================================
# 3) 科目注册 op.subject.registration：1 条已批准 + 1 条草稿
#    （社区版核心自带该模型，name 由 ir.sequence 生成，这里显式给名）
# =====================================================================
if course and batch and not env['op.subject.registration'].search_count(
        [('student_id', '=', student.id)]):
    comp_ids = course.subject_ids.ids if course.subject_ids else []
    mk_sp(env['op.subject.registration'], {
        'name': 'SR0001',
        'student_id': student.id,
        'course_id': course.id,
        'batch_id': batch.id,
        'compulsory_subject_ids': [(6, 0, comp_ids)],
        'state': 'approved',
    }, 'SUBJ-REG SR0001')
    mk_sp(env['op.subject.registration'], {
        'name': 'SR0002',
        'student_id': student.id,
        'course_id': course.id,
        'batch_id': batch.id,
        'state': 'draft',
    }, 'SUBJ-REG SR0002')
else:
    print("SKIP subject.registration (无课程或已有注册数据)")

# =====================================================================
# 4) 学术日历 op.academic.year / op.academic.term：1 学年 + 2 学期
# =====================================================================
year = env['op.academic.year'].search(
    [('name', '=', '2026-2027')], limit=1)
if not year:
    year = mk_sp(env['op.academic.year'], {
        'name': '2026-2027',
        'start_date': today - datetime.timedelta(days=60),
        'end_date': today + datetime.timedelta(days=300),
        'term_structure': 'two_sem',
    }, 'ACAD-YEAR 2026-2027')
if year and not env['op.academic.term'].search_count(
        [('academic_year_id', '=', year.id)]):
    mk_sp(env['op.academic.term'], {
        'name': '第一学期',
        'academic_year_id': year.id,
        'term_start_date': today - datetime.timedelta(days=60),
        'term_end_date': today + datetime.timedelta(days=120),
    }, 'ACAD-TERM 第一学期')
    mk_sp(env['op.academic.term'], {
        'name': '第二学期',
        'academic_year_id': year.id,
        'term_start_date': today + datetime.timedelta(days=121),
        'term_end_date': today + datetime.timedelta(days=300),
    }, 'ACAD-TERM 第二学期')
else:
    print("SKIP academic term (已有学期数据)")

# =====================================================================
# 5) 图书预约队列：追加 1 条 state=request 的请求（展示不同状态）
# =====================================================================
if student and env['op.media.queue'].search_count(
        [('partner_id', '=', student.partner_id.id)]) < 2:
    media_all = env['op.media'].search([], order='id asc')
    if media_all:
        mk_sp(env['op.media.queue'], {
            'media_id': media_all[0].id,
            'partner_id': student.partner_id.id,
            'date_from': today,
            'date_to': today + datetime.timedelta(days=10),
            'user_id': user.id,
            'state': 'request',
        }, 'MEDIA-QUEUE-REQUEST')
else:
    print("SKIP media.queue (已有队列数据)")

# =====================================================================
# 汇总
# =====================================================================
print("COUNTS leave=%d grievance=%d subj_reg=%d acad_year=%d acad_term=%d "
      "media_queue=%d" % (
    env['edu.leave'].search_count([('student_id', '=', student.id)]),
    env['edu.grievance'].search_count([('student_id', '=', student.id)]),
    env['op.subject.registration'].search_count(
        [('student_id', '=', student.id)]),
    env['op.academic.year'].search_count([]),
    env['op.academic.term'].search_count([]),
    env['op.media.queue'].search_count(
        [('partner_id', '=', student.partner_id.id)])))
env.cr.commit()
print("COMMITTED")
