# -*- coding: utf-8 -*-
"""批次2演示数据：图书馆媒体 / 成绩单（marksheet）/ 布告栏（edu.notice）。

用法（严禁管道接 head，防止 SIGPIPE 中断导致不提交）：
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
    -r odoo -w odoo -d edu19 --no-http < scripts/seed_batch2.py > /tmp/sb2.txt 2>&1
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
print("STUDENT id=%d name=%s" % (student.id, student.name))

sc = env['op.student.course'].search(
    [('student_id', '=', student.id)], limit=1)
course = sc.course_id
batch = sc.batch_id
subjects = sc.subject_ids or env['op.subject'].search([], order='id asc')

# =====================================================================
# 1) 图书馆：媒体类型 / 作者 / 出版社 / 媒体 / 馆藏单元 / 借阅记录
# =====================================================================
media_types = {mt.code: mt for mt in env['op.media.type'].search([])}
if 'CB' not in media_types:
    media_types = {}
    for code, name in [('CB', '课程用书'), ('RB', '参考书'),
                       ('MG', '杂志'), ('RP', '研究论文')]:
        mt = mk_sp(env['op.media.type'], {'name': name, 'code': code},
                   'MEDIA-TYPE %s' % code)
        if mt:
            media_types[code] = mt

authors = env['op.author'].search([])
if not authors:
    authors = []
    for nm in ['吴军', 'Thomas H. Cormen', '高铭', '刘未鹏']:
        a = mk_sp(env['op.author'], {'name': nm}, 'AUTHOR %s' % nm)
        if a:
            authors.append(a)

pubs = env['op.publisher'].search([])
if not pubs:
    pubs = []
    for nm in ['人民邮电出版社', '机械工业出版社', '清华大学出版社']:
        p = mk_sp(env['op.publisher'], {'name': nm}, 'PUB %s' % nm)
        if p:
            pubs.append(p)

if not env['op.media'].search_count([]):
    media_specs = [
        ('Python 编程：从入门到实践', '9787115546093', '3rd Edition',
         'CB', 0, '数据结构'),
        ('算法导论（第四版）', '9787111600062', '4th Edition',
         'RB', 0, '数据结构'),
        ('深入理解计算机系统', '9787111544938', '2nd Edition',
         'RB', 1, '操作系统'),
        ('高等数学（同济第七版）', '9787040396638', '7th Edition',
         'CB', 2, '高等数学'),
        ('大学英语综合教程', '9787040392869', '2nd Edition',
         'CB', 1, '大学英语'),
        ('程序员修炼之道', '9787121287496', '1st Edition',
         'RP', 1, '操作系统'),
        ('电脑报（月刊）', '9787506813006', '2026-08', 'MG', 0, ''),
        ('科技前沿季刊', '9787506813007', 'Vol. 12', 'MG', 1, ''),
    ]
    medias = []
    for i, (nm, isbn, ed, tcode, ai, subj) in enumerate(media_specs):
        sub_ids = []
        if subj:
            s = subjects.filtered(lambda x: x.name == subj)
            if s:
                sub_ids = [s.id]
        m = mk_sp(env['op.media'], {
            'name': nm,
            'isbn': isbn,
            'edition': ed,
            'internal_code': 'IC%04d' % (1000 + i),
            'media_type_id': media_types[tcode].id,
            'author_ids': [(6, 0, [authors[ai % len(authors)].id])],
            'publisher_ids': [(6, 0, [pubs[i % len(pubs)].id])],
            'subject_ids': [(6, 0, sub_ids)],
        }, 'MEDIA %s' % nm)
        if m:
            medias.append(m)
    # 馆藏单元（op.media.unit 自动生成条码）
    for m in medias[:4]:
        for k in range(2):
            mk_sp(env['op.media.unit'], {
                'name': '%s-Unit%d' % (m.name, k + 1),
                'media_id': m.id,
                'state': 'available',
            }, 'UNIT %s-%d' % (m.name, k + 1))

# 图书馆借阅卡 + 一条在借记录（Issued to Me 统计用）
card_type = env['op.library.card.type'].search([], limit=1)
if not card_type:
    card_type = mk_sp(env['op.library.card.type'], {
        'name': 'Student Card',
        'allow_media': 5,
        'duration': 14,
        'penalty_amt_per_day': 0.5,
    }, 'CARD-TYPE')
card = env['op.library.card'].search(
    [('student_id', '=', student.id)], limit=1)
if not card:
    card = mk_sp(env['op.library.card'], {
        'partner_id': student.partner_id.id,
        'student_id': student.id,
        'library_card_type_id': card_type.id,
        'issue_date': today - datetime.timedelta(days=60),
        'type': 'student',
        'number': 'LC%05d' % student.id,
    }, 'LIB-CARD')

media_all = env['op.media'].search([], order='id asc')
units = env['op.media.unit'].search(
    [('state', '=', 'available')], order='id asc')
if card and units and not env['op.media.movement'].search_count(
        [('student_id', '=', student.id)]):
    mv = mk_sp(env['op.media.movement'], {
        'media_id': media_all[0].id,
        'media_unit_id': units[0].id,
        'type': 'student',
        'student_id': student.id,
        'library_card_id': card.id,
        'issued_date': today - datetime.timedelta(days=6),
        'return_date': today + datetime.timedelta(days=8),
        'state': 'issue',
    }, 'MOVEMENT-ISSUED')
    if mv:
        # 馆藏单元置为已借出
        try:
            with env.cr.savepoint():
                units[0].state = 'issue'
            print("OK UNIT-ISSUED")
        except Exception as e:
            print("ERR UNIT-ISSUED: %s" % str(e).replace("\n", " ")[:200])
        # 一条媒体队列请求（首页「我的图书馆 / 提醒」计数用）
        mk_sp(env['op.media.queue'], {
            'media_id': media_all[1].id,
            'partner_id': student.partner_id.id,
            'date_from': today,
            'date_to': today + datetime.timedelta(days=7),
            'user_id': user.id,
            'state': 'accept',
        }, 'MEDIA-QUEUE')
    # 一条已归还记录（Returned 统计用）
    if len(units) > 1:
        mk_sp(env['op.media.movement'], {
            'media_id': media_all[1].id,
            'media_unit_id': units[1].id,
            'type': 'student',
            'student_id': student.id,
            'library_card_id': card.id,
            'issued_date': today - datetime.timedelta(days=20),
            'return_date': today - datetime.timedelta(days=6),
            'actual_return_date': today - datetime.timedelta(days=7),
            'state': 'return_done',
        }, 'MOVEMENT-RETURNED')
        try:
            with env.cr.savepoint():
                units[1].state = 'available'
            print("OK UNIT-RETURNED")
        except Exception as e:
            print("ERR UNIT-RETURNED: %s" % str(e).replace("\n", " ")[:200])

# =====================================================================
# 2) 成绩单：grade 配置 -> result template -> marksheet register/line/result
# =====================================================================
if not env['op.marksheet.line'].search_count(
        [('student_id', '=', student.id)]):
    session = env['op.exam.session'].search([], limit=1)
    if session:
        # 结果模板要求考试 state=done；批次1的种子考试是 result_updated
        try:
            with env.cr.savepoint():
                session.exam_ids.write({'state': 'done'})
            print("OK EXAMS-DONE (%d)" % len(session.exam_ids))
        except Exception as e:
            print("ERR EXAMS-DONE: %s" % str(e).replace("\n", " ")[:200])
        try:
            with env.cr.savepoint():
                session.evaluation_type = 'grade'
            print("OK SESSION-GRADE")
        except Exception as e:
            print("ERR SESSION-GRADE: %s" % str(e).replace("\n", " ")[:200])

        grade_cfg = env['op.grade.configuration'].search([], limit=1)
        if not grade_cfg:
            grades = []
            for res, lo, hi in [('A+', 90, 100), ('A', 80, 89), ('B', 70, 79),
                                ('C', 60, 69), ('D', 50, 59), ('E', 40, 49),
                                ('F', 0, 39)]:
                g = mk_sp(env['op.grade.configuration'], {
                    'result': res, 'min_per': lo, 'max_per': hi},
                    'GRADE %s' % res)
                if g:
                    grades.append(g)
        else:
            grades = env['op.grade.configuration'].search([])

        tmpl = mk_sp(env['op.result.template'], {
            'name': '2026 第一学期成绩单模板',
            'exam_session_id': session.id,
            'result_date': today,
            'state': 'result_generated',
            'grade_ids': [(6, 0, [g.id for g in grades])],
        }, 'RESULT-TEMPLATE')
        if tmpl:
            reg = mk_sp(env['op.marksheet.register'], {
                'name': '2026 第一学期成绩册',
                'exam_session_id': session.id,
                'generated_date': today,
                'generated_by': env.uid,
                'state': 'validated',
                'result_template_id': tmpl.id,
            }, 'MARKSHEET-REG')
            if reg:
                ms_line = mk_sp(env['op.marksheet.line'], {
                    'marksheet_reg_id': reg.id,
                    'student_id': student.id,
                    'generated_date': today,
                }, 'MARKSHEET-LINE')
                if ms_line:
                    for exam in session.exam_ids:
                        att = env['op.exam.attendees'].search(
                            [('exam_id', '=', exam.id),
                             ('student_id', '=', student.id)], limit=1)
                        marks = att.marks if att and att.marks is not False \
                            else 60
                        mk_sp(env['op.result.line'], {
                            'marksheet_line_id': ms_line.id,
                            'exam_id': exam.id,
                            'student_id': student.id,
                            'marks': marks,
                        }, 'RESULT-LINE %s %d' % (exam.name, marks))
                print("MARKSHEET DONE")
else:
    print("SKIP marksheet (已有成绩单数据)")

# =====================================================================
# 3) 布告栏：edu.notice 演示数据（至少 3 条）
# =====================================================================
if env['edu.notice'].search_count([]) < 3:
    notices = [
        ('关于2026学年第一学期选课的通知',
         '本学期选课系统已开放，请同学们在 9 月 15 日前完成课程与科目注册，逾期不再受理。',
         '教务处', today - datetime.timedelta(days=3)),
        ('图书馆延长开放时间公告',
         '即日起图书馆开放时间延长至 22:00，周末正常开放，欢迎同学们前来借阅学习。',
         '图书馆', today - datetime.timedelta(days=1)),
        ('第一学期期中考试安排',
         '期中考试定于本月 20-25 日举行，具体考场安排请留意各科目老师的通知，请提前复习。',
         '教务处', today),
        ('校园安全温馨提示',
         '近期校内施工，请同学们注意绕行安全区域，夜间出行尽量结伴，保管好个人财物。',
         '学生工作处', today + datetime.timedelta(days=1)),
    ]
    for i, (nm, content, sender, d) in enumerate(notices):
        mk_sp(env['edu.notice'], {
            'name': nm,
            'content': content,
            'sender': sender,
            'date': d,
        }, 'NOTICE %d %s' % (i + 1, nm[:12]))
else:
    print("SKIP notice (已有布告数据)")

# =====================================================================
# 汇总
# =====================================================================
print("COUNTS media=%d media_type=%d media_unit=%d author=%d pub=%d "
      "movement=%d queue=%d marksheet_reg=%d marksheet_line=%d "
      "result_line=%d notice=%d" % (
    env['op.media'].search_count([]),
    env['op.media.type'].search_count([]),
    env['op.media.unit'].search_count([]),
    env['op.author'].search_count([]),
    env['op.publisher'].search_count([]),
    env['op.media.movement'].search_count([('student_id', '=', student.id)]),
    env['op.media.queue'].search_count([('partner_id', '=', student.partner_id.id)]),
    env['op.marksheet.register'].search_count([]),
    env['op.marksheet.line'].search_count([('student_id', '=', student.id)]),
    env['op.result.line'].search_count([('student_id', '=', student.id)]),
    env['edu.notice'].search_count([])))
env.cr.commit()
print("COMMITTED")
