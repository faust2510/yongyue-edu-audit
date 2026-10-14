# -*- coding: utf-8 -*-
# 评估中心演示模板（幂等）：三大评估各一套评分项。
Tpl = env['edu.eval.template']
Line = env['edu.eval.template.line']
DATA = [
    ('学生综合评估记分表【演示】', 'student', 100, 60, 90, True,
     ['出勤与纪律', 20], ['课堂参与', 20], ['灵修生活', 20],
     ['学业表现', 20], ['服事态度', 20]),
    ('实习同工评估表【演示】', 'intern', 100, 60, 80, False,
     ['事奉忠心', 25], ['团队配搭', 25], ['属灵榜样', 25], ['专业能力', 25]),
    ('新生综合测评表【演示】', 'freshman', 100, 60, 90, True,
     ['基础信仰笔试', 40], ['面试表现', 30], ['写作测试', 30]),
]
created, skipped = 0, 0
for item in DATA:
    name, code, total, pl, el, vis = item[:6]
    items = item[6:]
    dup = Tpl.search([('name', '=', name)], limit=1)
    if dup:
        skipped += 1
        continue
    t = Tpl.create({'name': name, 'type_code': code, 'total': total,
                    'pass_line': pl, 'excellent_line': el,
                    'visible_to_student': vis})
    for i, (nm, mx) in enumerate(items):
        Line.create({'template_id': t.id, 'name': nm,
                     'max_score': float(mx), 'sequence': 10 * (i + 1)})
    created += 1
env.cr.commit()
print('EVAL-SEED created=%d skipped=%d total=%d DONE' % (
    created, skipped, Tpl.search_count([])))
