# -*- coding: utf-8 -*-
# 招聘演示数据（幂等）：2 个已发布岗位。
# 运行: docker exec -i edu19-clone-web-1 odoo shell -c /etc/odoo/odoo.conf \
#         -d edu19 --db_host=db -r odoo -w odoo --no-http < scripts/seed_jobs_demo.py
Posting = env['edu.job.posting']
ITEMS = [
    ('【演示】神学课程助教', '教务处', '永约学坊校内', '面议', 2,
     '<p><b>职责：</b>协助教师准备讲义、批改作业、维护课程资料。</p>'
     '<p><b>要求：</b>在读学员或毕业生，信仰端正，做事细致。</p>'),
    ('【演示】图书馆兼职管理员', '图书馆', '永约学坊校内', '时薪制', 1,
     '<p><b>职责：</b>图书编目、借还登记、阅览室秩序维护。</p>'
     '<p><b>要求：</b>熟悉基本办公软件，每周可到馆 2-3 个半天。</p>'),
]
created, skipped = 0, 0
for name, dept, loc, salary, openings, desc in ITEMS:
    dup = Posting.search([('name', '=', name)], limit=1)
    if dup:
        skipped += 1
        continue
    Posting.create({
        'name': name, 'department': dept, 'location': loc,
        'salary_range': salary, 'openings': openings,
        'description': desc, 'state': 'published',
    })
    created += 1
env.cr.commit()
print('JOB-SEED created=%d skipped=%d total=%d DONE' % (
    created, skipped, Posting.search_count([])))
