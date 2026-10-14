# -*- coding: utf-8 -*-
"""为演示学生种一条结业证书（幂等）。

用法：
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
    -r odoo -w odoo -d edu19 --no-http < scripts/seed_certificate.py 2>&1 | tail -5
"""
env = env

user = env['res.users'].sudo().search([('login', '=', 'stu@local')],
                                      limit=1)
student = env['op.student'].sudo().search(
    [('user_id', '=', user.id)], limit=1) if user else env['op.student'].sudo()
student = student.search([], limit=1) if not (student and student.id) \
    else student
if not (student and student.id):
    print('NO STUDENT')
else:
    have = env['edu.certificate'].sudo().search_count(
        [('student_id', '=', student.id)])
    if not have:
        course = env['op.course'].sudo().search([], limit=1)
        env['edu.certificate'].sudo().create({
            'student_id': student.id,
            'course_id': course.id,
            'grade': '优秀',
            'state': 'issued',
            'remark': '演示数据',
        })
        print('CERT CREATED for %s' % student.name)
    else:
        print('CERT EXISTS (%d)' % have)

env.cr.commit()
print('COMMITTED')
