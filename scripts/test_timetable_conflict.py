# -*- coding: utf-8 -*-
# 在 odoo shell 里验证冲突拦截：同一教师同时段第二节课必须被拒。
# 用法: docker exec -i edu19-clone-web-1 odoo shell -c /etc/odoo/odoo.conf \
#         -d edu19 --db_host=db -r odoo -w odoo --no-http < scripts/test_timetable_conflict.py
from datetime import datetime, timedelta

Session = env['op.session']
start = datetime(2026, 9, 10, 9, 0, 0)
end = datetime(2026, 9, 10, 9, 45, 0)
base = dict(course_id=18, batch_id=8, subject_id=35, faculty_id=17,
            start_datetime=start, end_datetime=end, state='draft')

first = Session.create(dict(base))
print('FIRST-OK id=%s' % first.id)
try:
    Session.create(dict(base))
    print('CONFLICT-GUARD=FAIL 第二节课未被拦截！')
except Exception as e:
    print('CONFLICT-GUARD=PASS (%s)' % type(e).__name__)
env.cr.rollback()
print('DONE(已回滚，不留测试数据)')
