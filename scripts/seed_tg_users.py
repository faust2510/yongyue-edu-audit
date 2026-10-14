# -*- coding: utf-8 -*-
"""演示账号：学生/教师/家长的门户用户，用于网页端生成绑定码。"""
env.cr.commit  # noqa
import datetime
env = env

def ensure_user(login, name):
    u = env['res.users'].search([('login', '=', login)], limit=1)
    if not u:
        u = env['res.users'].create({
            'name': name, 'login': login, 'email': login,
            'password': 'demo123',
            'group_ids': [(6, 0, [env.ref('base.group_portal').id])]})
        print('OK user', login)
    return u

portal = env.ref('base.group_portal')
stu_user = env['res.users'].search([('login', '=', 'stu@local')], limit=1)
stu = env['op.student'].search([('user_id', '=', stu_user.id)], limit=1)

fac_user = ensure_user('fac@local', '李强')
emp = env['hr.employee'].search([('identification_id', '=', 'E1001')],
                                limit=1)
if emp and not emp.user_id:
    emp.write({'user_id': fac_user.id})
    print('OK employee.user_id')

par_user = ensure_user('parent@local', '张家长')
Par = env['op.parent']
par = Par.search([('name.user_id', '=', par_user.id)], limit=1)
if not par:
    p = par_user.partner_id
    rel = env['op.parent.relationship'].search([], limit=1)
    if not rel:
        rel = env['op.parent.relationship'].create({'name': '父亲'})
    try:
        with env.cr.savepoint():
            par = Par.create({'name': p.id,
                              'relationship_id': rel.id,
                              'student_ids': [(6, 0, [stu.id])]})
        print('OK parent', par.id)
    except Exception as e:
        print('ERR parent:', str(e)[:140])

env.cr.commit()
print('USERS DONE')
