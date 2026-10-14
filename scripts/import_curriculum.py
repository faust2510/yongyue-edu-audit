# -*- coding: utf-8 -*-
"""《学位课程规划》CSV -> op.subject + 课程挂接（幂等，可 dry-run）。

在 odoo shell 内执行（脚本经 stdin 送入，避免依赖挂载）：
    docker compose exec -T -e CSV=/tmp/curriculum.csv -e DRY_RUN=1 web odoo shell \
        -c /etc/odoo/odoo.conf -d edu19 --db_host=db -r odoo -w odoo --no-http \
        < scripts/import_curriculum.py

环境变量
    CSV     课程清单 CSV 路径（列：课程,学分,性质,类别,适用学位）
    DRY_RUN 1 = 只报不写
    REPORT  对拍表落盘路径（默认 /tmp/import_report.csv）
"""
import csv as _csv
import os

CSV = os.environ.get('CSV', '/tmp/curriculum.csv')
DRY = os.environ.get('DRY_RUN', '') not in ('', '0', 'false', 'no')
REPORT = os.environ.get('REPORT', '/tmp/import_report.csv')

# 学位 -> 目标课程（按名称解析，绝不写死 id）
DEGREE = {
    '教育学士/文学学士': ['教育学士', '文学学士'],
    '神学士/研究硕士': ['神学学士科', '基督教研究硕士科'],
}

Subject = env['op.subject'].sudo()
Course = env['op.course'].sudo()

cmap = {}
for c in Course.search([]):
    cmap[(c.name or '').strip()] = c
# 既有科目：smap 按**名字**去重（导入判重就是按名字），但**报数必须同时给行数** ——
# 否则「32 行科目里有 1 组重名」会被误读成「数据少了 1 条」（2026-10-01 实测：基础信仰 BTH-FOU01 + PRP-C02）。
_all_subjects = Subject.with_context(active_test=False).search([])
smap = {}
for s in _all_subjects:
    smap.setdefault((s.name or '').strip(), s)
_named = {}
for s in _all_subjects:
    k = (s.name or '').strip()
    _named[k] = _named.get(k, 0) + 1
_dups = sorted([(k, v) for k, v in _named.items() if v > 1])
_dup_txt = ('（重名: ' + ', '.join('%s x%d' % (k, v) for k, v in _dups) + '）') if _dups else ''
used_codes = set(_all_subjects.mapped('code'))

rows = list(_csv.DictReader(open(CSV, encoding='utf-8')))
print('[import] CSV =', CSV)
print('[import] 行数 =', len(rows), '| DRY_RUN =', DRY,
      '| 既有科目 =', len(_all_subjects), '行 /', len(smap), '个唯一名', _dup_txt,
      '| 课程 =', len(cmap))

new_n = exist_n = skip_n = link_n = 0
missing_course = {}
report = [['课程', '学分', '性质', '动作', '挂接到课程', '说明']]

for idx, r in enumerate(rows, 1):
    name = (r.get('课程') or '').strip()
    credits = (r.get('学分') or '').strip()
    kind = (r.get('性质') or '').strip()
    degrees = (r.get('适用学位') or '').strip()

    targets = []
    for d in degrees.split('+'):
        targets += DEGREE.get(d.strip(), [])
    if not name or not targets:
        skip_n += 1
        report.append([name, credits, kind, '跳过', '', '无课程名或学位映射不上'])
        continue

    subj = smap.get(name)
    if subj is not None:
        exist_n += 1
        act = '已存在'
    else:
        code = 'YY-%03d' % idx
        bump = idx
        while code in used_codes:
            bump += 1
            code = 'YY-%03d' % bump
        used_codes.add(code)
        if DRY:
            act = '将新建'
            subj = None
        else:
            vals = {
                'name': name,
                'code': code,
                'type': 'theory',
                'subject_type': 'compulsory' if kind.startswith('必修') else 'elective',
                'active': True,
            }
            # 字段按现场 schema 容忍（生产库比本地旧，缺 credit_points/capacity）
            for fld, val in (('credit_points', float(credits) if credits.replace('.', '', 1).isdigit() else 0.0),):
                if fld in Subject._fields:
                    vals[fld] = val
            subj = Subject.with_context(lang='zh_CN').create(vals)
            smap[name] = subj
            act = '新建'
        new_n += 1

    linked_to = []
    for cn in targets:
        c = cmap.get(cn)
        if c is None:
            missing_course[cn] = missing_course.get(cn, 0) + 1
            continue
        if DRY or subj is None:
            linked_to.append(cn + '(dry)')
            continue
        if subj.id not in c.subject_ids.ids:
            c.write({'subject_ids': [(4, subj.id)]})
            link_n += 1
        linked_to.append(cn)

    report.append([name, credits, kind, act, '|'.join(linked_to), ''])

print('[import] 新建 =', new_n, '| 已存在 =', exist_n, '| 跳过 =', skip_n)
print('[import] 合计 =', new_n + exist_n + skip_n, '断言 == CSV 行数:', new_n + exist_n + skip_n == len(rows))
print('[import] 新增挂接 =', link_n)
if missing_course:
    print('[import] ⚠ 未找到的课程（已跳过，未静默）:', missing_course)
else:
    print('[import] 目标课程全部命中 ✓')

try:
    import io
    with io.open(REPORT, 'w', encoding='utf-8') as f:
        _csv.writer(f).writerows(report)
    print('[import] 对拍表已写', REPORT)
except Exception as e:
    print('[import] 对拍表写入失败:', e)

if not DRY:
    # odoo shell 结束时会回滚，必须显式提交（否则「跑完了但库里没变」）
    env.cr.commit()
    print('[import] 已提交 env.cr.commit()')

print('[import] 收尾计数：op_subject =', Subject.with_context(active_test=False).search_count([]),
      '| 挂接 =', env['op.course.op.subject.rel'].sudo().search_count([]) if 'op.course.op.subject.rel' in env else 'n/a')
