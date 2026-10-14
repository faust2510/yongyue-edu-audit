# -*- coding: utf-8 -*-
"""Telegram 演示数据：教师(带工号)、图书借阅、考勤、缴费。跑于 odoo shell。"""
import datetime
env = env
now = datetime.datetime.now()
today = datetime.date.today()

def mk(model, vals, tag, uniq=None):
    if uniq and model.search(uniq, limit=1):
        print("SKIP", tag)
        return model.search(uniq, limit=1)
    try:
        with env.cr.savepoint():
            rec = model.create(vals)
            print("OK", tag)
            return rec
    except Exception as e:
        print("ERR %s: %s" % (tag, str(e).replace("\n", " ")[:160]))
        return None

# ---- 教师：工号 E1001，生日 1985-05-01 ----
emp = env['hr.employee'].search([('name', '=', '李强')], limit=1) or \
      mk(env['hr.employee'], {'name': '李强', 'identification_id': 'E1001'}, 'EMP 李强',
         [('name', '=', '李强')])
fac = env['op.faculty'].search([('first_name', '=', '强'),
                                ('last_name', '=', '李')], limit=1)
if fac and emp and not fac.emp_id:
    fac.write({'emp_id': emp.id})
    print("OK faculty.emp_id linked")
fac = env['op.faculty'].search([('emp_id', '!=', False)], limit=1)
print("FACULTY:", fac.id, fac.name, "emp:", fac.emp_id.name,
      "birth:", fac.birth_date)

stu = env['op.student'].browse(
    env['op.student.course'].search([('roll_number', '=', '20240101')],
                                    limit=1).student_id.id)

# ---- 图书借阅 ----
ctype = env['op.library.card.type'].search([], limit=1) or \
        mk(env['op.library.card.type'],
           {'name': '通用', 'allow_media': 5, 'duration': 30},
           'CARDTYPE', [('name', '=', '通用')])
def card(partner, stu_id=None, fac_id=None, tag='CARD'):
    existing = env['op.library.card'].search(
        [('partner_id', '=', partner.id)], limit=1)
    if existing:
        return existing
    try:
        with env.cr.savepoint():
            c = env['op.library.card'].create({
                'library_card_type_id': ctype.id,
                'issue_date': today - datetime.timedelta(days=60),
                'type': 'student' if stu_id else 'faculty',
                'student_id': stu_id, 'faculty_id': fac_id,
                'partner_id': partner.id})
            print("OK", tag)
            return c
    except Exception as e:
        print("ERR %s: %s" % (tag, str(e)[:140]))
        return None

card_s = card(stu.partner_id, stu_id=stu.id, tag='CARD student')
card_f = card(fac.partner_id, fac_id=fac.id, tag='CARD faculty')
media = env['op.media'].search([], limit=1)
unit = env['op.media.unit'].search([], limit=1)
if media and unit:
    if media and unit and card_s:
        mk(env['op.media.movement'], {
            'media_id': media.id, 'media_unit_id': unit.id,
            'student_id': stu.id, 'type': 'student',
            'library_card_id': card_s.id,
            'return_date': today + datetime.timedelta(days=6),
        }, 'BORROW student ok', [('student_id', '=', stu.id)])
    if media and unit and card_f:
        mk(env['op.media.movement'], {
            'media_id': media.id, 'media_unit_id': unit.id,
            'faculty_id': fac.id, 'type': 'faculty',
            'library_card_id': card_f.id,
            'issued_date': today - datetime.timedelta(days=9),
            'return_date': today - datetime.timedelta(days=3),
            'penalty': 1.5,
        }, 'BORROW faculty overdue', [('faculty_id', '=', fac.id)])

# ---- 考勤：register -> sheet -> line ----
Reg = env['op.attendance.register']
reg = Reg.search([], limit=1)
if not reg:
    course = env['op.course'].search([], limit=1)
    batch = env['op.batch'].search([], limit=1)
    reg = mk(Reg, {'name': 'TG考勤册', 'code': 'TG01',
                   'course_id': course.id, 'batch_id': batch.id},
             'ATT register', [('code', '=', 'TG01')])
Sheet = env['op.attendance.sheet']
if reg and not Sheet.search([('register_id', '=', reg.id)], limit=1):
    course = env['op.course'].search([], limit=1)
    batch = env['op.batch'].search([], limit=1)
    for d in range(5):
        day = today - datetime.timedelta(days=d + 1)
        try:
            with env.cr.savepoint():
                Sheet.create({
                    'register_id': reg.id,
                    'course_id': course.id, 'batch_id': batch.id,
                    'attendance_date': day,
                    'attendance_line': [(0, 0, {
                        'student_id': stu.id,
                        'present': d not in (2, 4),
                        'absent': d == 4,
                        'late': d == 2})]})
                print("OK ATT sheet", day)
        except Exception as e:
            print("ERR sheet:", str(e)[:140])

# ---- 缴费 ----
prod = env['product.product'].search([], limit=1)
FeesD = env['op.student.fees.details']
if prod and not FeesD.search([('student_id', '=', stu.id)], limit=1):
    mk(FeesD, {'student_id': stu.id, 'product_id': prod.id,
               'amount': 5000.0, 'state': 'invoice',
               'date': today}, 'FEE due')
    mk(FeesD, {'student_id': stu.id, 'product_id': prod.id,
               'amount': 2000.0, 'state': 'invoice',
               'date': today - datetime.timedelta(days=30)},
       'FEE paid-ish')
env.cr.commit()
print("SEED DONE")
