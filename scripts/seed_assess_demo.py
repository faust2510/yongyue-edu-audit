# -*- coding: utf-8 -*-
"""评估引擎本地演示数据（幂等 get-or-create）——【演示】标记。

用法（与 scripts/seed_eval_demo.py 同法）：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf \
        --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo \
        -d edu19 --no-http < scripts/seed_assess_demo.py

为什么放这里而不是 data/：本仓陷阱 1（edu_life/data/demo_life.xml 的
_load_demo_records 每次 -u 跨日补业务行）——演示数据不进 data/，也不写业务表。
"""
Tpl = env['edu.assess.template'].sudo()
Item = env['edu.assess.item'].sudo()
Task = env['edu.assess.task'].sudo()

TLP = [
    ('学生日常量化评估表【演示】', 'student', 'student', True,
     [('出勤与纪律', 20), ('课堂参与', 20), ('学业表现', 30), ('服事态度', 30)]),
    ('教师评教表【演示】', 'teaching', 'faculty', False,
     [('备课充分', 25), ('课堂表达', 25), ('对学生的关怀', 25), ('整体评价', 25)]),
]

created_tpl = created_item = created_task = skipped = 0
tpl_by_name = {}
for name, kind, target, visible, items in TLP:
    tpl = Tpl.search([('name', '=', name)], limit=1)
    if not tpl:
        tpl = Tpl.create({
            'name': name, 'kind': kind, 'target_kind': target,
            'total': 100.0, 'pass_line': 60.0, 'excellent_line': 90.0,
            'score_visible': visible,
        })
        created_tpl += 1
    else:
        skipped += 1
    tpl_by_name[name] = tpl
    for i, (iname, mx) in enumerate(items):
        if Item.search([('template_id', '=', tpl.id),
                        ('name', '=', iname)], limit=1):
            continue
        Item.create({'template_id': tpl.id, 'name': iname,
                     'max_score': float(mx), 'sequence': 10 * (i + 1)})
        created_item += 1

# 一个进行中的匿名评教任务（门槛 3 份），名单快照现场生成
tpl = tpl_by_name['教师评教表【演示】']
task = Task.search([('template_id', '=', tpl.id),
                    ('period', '=', '2026秋')], limit=1)
if not task:
    task = Task.create({
        'template_id': tpl.id, 'period': '2026秋', 'state': 'open',
        'scorer_kind': 'student', 'anonymous': True, 'summary_min': 3,
    })
    task.action_build_roster()
    created_task += 1
else:
    skipped += 1

env.cr.commit()
print('ASSESS-SEED tpl=%d(+%d) item=%d task=%d skip=%d TOTAL_TPL=%d TOTAL_ITEM=%d '
      'TOTAL_TASK=%d DONE' % (
          created_tpl, skipped, created_item, created_task, skipped,
          Tpl.search_count([]), Item.search_count([]), Task.search_count([])))
