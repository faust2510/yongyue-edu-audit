# -*- coding: utf-8 -*-
# LMS 演示数据种子（幂等）：为前 3 门科目各建 2-3 个【演示】课次。
# 运行: docker exec -i edu19-clone-web-1 odoo shell -c /etc/odoo/odoo.conf \
#         -d edu19 --db_host=db -r odoo -w odoo --no-http < scripts/seed_lms_demo.py
VIDEO_DEMO = 'https://www.w3schools.com/html/mov_bbb.mp4'

PLAN = [
    ('小要理问答', [
        ('video', '【演示】要理问答第一课·导论'),
        ('article', '【演示】要理问答第一课·讲义'),
        ('video', '【演示】要理问答第二课·问答1-2'),
    ]),
    ('基础信仰', [
        ('video', '【演示】基础信仰第一课'),
        ('article', '【演示】基础信仰第一课·阅读材料'),
    ]),
    ('圣经概论（新旧约概论）', [
        ('video', '【演示】圣经概论·创世记导论'),
        ('article', '【演示】圣经概论·读经表'),
        ('article', '【演示】圣经概论·课程说明'),
    ]),
]

ARTICLE_BODY = (
    '<p>本课次为<b>演示数据</b>（永约学坊 LMS 上线前的占位内容）。</p>'
    '<p>正式内容将由教师发布：讲义、阅读材料与思考题。</p>'
)

created, skipped = 0, 0
Lesson = env['edu.lesson']
for subject_name, lessons in PLAN:
    sub = env['op.subject'].search([('name', '=', subject_name)], limit=1)
    if not sub:
        print('SEED-SKIP 科目不存在:', subject_name)
        continue
    for idx, (ltype, title) in enumerate(lessons):
        dup = Lesson.search([('subject_id', '=', sub.id),
                             ('name', '=', title)], limit=1)
        if dup:
            skipped += 1
            continue
        vals = {
            'subject_id': sub.id,
            'name': title,
            'type': ltype,
            'sequence': 10 * (idx + 1),
            'state': 'published',
            'content_html': ARTICLE_BODY,
        }
        if ltype == 'video':
            vals['video_url'] = VIDEO_DEMO
            vals['content_html'] = False
        Lesson.create(vals)
        created += 1

env.cr.commit()
print('LMS-SEED created=%d skipped=%d total=%d' % (
    created, skipped, Lesson.search_count([])))
print('DONE')
