# -*- coding: utf-8 -*-
env = env

user = env['res.users'].search([('login', '=', 'stu@local')], limit=1)
if not user:
    user = env['res.users'].create({
        'name': '王小明', 'login': 'stu@local', 'email': 'stu@local',
        'password': 'demo123',
        'group_ids': [(6, 0, [env.ref('base.group_portal').id])],
    })
    print("USER CREATED", user.id)

student = env['op.student'].search([('user_id', '=', user.id)], limit=1)
if not student:
    student = env['op.student'].search([], limit=1)
    if student:
        student.write({'user_id': user.id,
                       'first_name': student.first_name or '小明',
                       'last_name': student.last_name or '王'})
        print("STUDENT LINKED", student.id)
    else:
        student = env['op.student'].create({
            'name': '王小明', 'first_name': '小明', 'last_name': '王',
            'user_id': user.id, 'gender': 'm'})
        print("STUDENT CREATED", student.id)

sc = env['op.student.course'].search([('student_id', '=', student.id)], limit=1)
print("STATE user=%s student=%s stu_course=%s" % (
    bool(user), student.id, sc.id))
env.cr.commit()
print("COMMITTED")
