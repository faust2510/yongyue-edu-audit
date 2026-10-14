# -*- coding: utf-8 -*-
import datetime
env = env

def mk(model, vals, tag):
    try:
        rec = model.create(vals)
        print(f"OK {tag}")
        return rec
    except Exception as e:
        print("ERR %s: %s" % (tag, str(e).replace("\n", " ")[:200]))
        return None

course = env['op.course'].search([], limit=1)
if not course:
    course = mk(env['op.course'], {'name': '计算机科学与技术', 'code': 'CS'}, 'COURSE')
batch = env['op.batch'].search([], limit=1)
if not batch:
    batch = mk(env['op.batch'], {
        'name': '2024级1班', 'code': 'B2401', 'course_id': course.id,
        'start_date': datetime.date(2026, 9, 1),
        'end_date': datetime.date(2030, 7, 1)}, 'BATCH')

if not env['op.subject'].search_count([]):
    for nm, cd in [('高等数学','M101'),('大学英语','E101'),('数据结构','CS201'),
                   ('操作系统','CS301'),('体育','PE100')]:
        mk(env['op.subject'], {'name': nm, 'code': cd}, 'SUBJ ' + nm)

if not env['op.timing'].search_count([]):
    mk(env['op.timing'], {'name': '第1节', 'hour': '1', 'minute': '00', 'am_pm': 'am', 'sequence': 1}, 'T1')
    mk(env['op.timing'], {'name': '第2节', 'hour': '3', 'minute': '00', 'am_pm': 'am', 'sequence': 2}, 'T2')
    mk(env['op.timing'], {'name': '第3节', 'hour': '2', 'minute': '00', 'am_pm': 'pm', 'sequence': 3}, 'T3')

if not env['op.classroom'].search_count([]):
    for i, nm in enumerate(['教学楼A-101', '教学楼A-102', '实验楼B-201']):
        mk(env['op.classroom'], {'name': nm, 'code': 'R%d' % i, 'capacity': 60}, 'ROOM ' + nm)

if not env['op.faculty'].search_count([]):
    for fn, ln in [('强', '李'), ('红', '张'), ('国', '刘')]:
        p = env['res.partner'].create({'name': ln + fn})
        mk(env['op.faculty'], {
            'name': ln + fn, 'first_name': fn, 'last_name': ln,
            'gender': 'male', 'birth_date': datetime.date(1985, 5, 1),
            'partner_id': p.id}, 'FAC ' + ln + fn)

user = env['res.users'].search([('login', '=', 'stu@local')], limit=1)
if not user:
    user = mk(env['res.users'], {
        'name': '王小明', 'login': 'stu@local', 'email': 'stu@local',
        'password': 'demo123',
        'group_ids': [(6, 0, [env.ref('base.group_portal').id])]}, 'USER')
student = env['op.student'].search([('user_id', '=', user.id)], limit=1)
if not student:
    student = mk(env['op.student'], {
        'name': '王小明', 'first_name': '小明', 'last_name': '王',
        'user_id': user.id, 'gender': 'm',
        'birth_date': datetime.date(2006, 9, 1)}, 'STUDENT')

sc = env['op.student.course'].search([('student_id', '=', student.id)], limit=1)
if not sc:
    mk(env['op.student.course'], {
        'student_id': student.id, 'course_id': course.id,
        'batch_id': batch.id, 'roll_number': '20240101'}, 'STU-COURSE')

Session = env['op.session']
if Session.search_count([('batch_id', '=', batch.id)]) < 5:
    timings = env['op.timing'].search([], order='sequence asc')
    subjects = env['op.subject'].search([])
    rooms = env['op.classroom'].search([])
    faculties = env['op.faculty'].search([])
    base = datetime.datetime.now().replace(minute=0, second=0)
    n = 0
    for d in range(7):
        day = base + datetime.timedelta(days=d)
        for i, t in enumerate(timings):
            hh = int(t.hour) + (12 if t.am_pm == 'pm' else 0)
            start = day.replace(hour=min(hh, 21))
            vals = {'start_datetime': start,
                    'end_datetime': start + datetime.timedelta(hours=2),
                    'timing_id': t.id, 'batch_id': batch.id,
                    'course_id': course.id}
            if len(subjects):
                vals['subject_id'] = subjects[(d + i) % len(subjects)].id
            if len(rooms):
                vals['classroom_id'] = rooms[(d + i) % len(rooms)].id
            if len(faculties):
                vals['faculty_id'] = faculties[d % len(faculties)].id
            try:
                with env.cr.savepoint():
                    Session.create(vals)
                    n += 1
            except Exception as e:
                print("SESS ERR:", str(e).replace("\n", " ")[:160])
    print("SESSIONS CREATED:", n)

print("COUNTS course=%d batch=%d subj=%d timing=%d room=%d fac=%d stu=%d sc=%d sess=%d" % (
    env['op.course'].search_count([]), env['op.batch'].search_count([]),
    env['op.subject'].search_count([]), env['op.timing'].search_count([]),
    env['op.classroom'].search_count([]), env['op.faculty'].search_count([]),
    env['op.student'].search_count([]), env['op.student.course'].search_count([]),
    Session.search_count([])))
env.cr.commit()
print("COMMITTED")
