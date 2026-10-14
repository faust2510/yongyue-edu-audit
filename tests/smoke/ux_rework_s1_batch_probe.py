#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t6 探针：S1 _compute_conflict 批量计算行为（视图路径 vs 单记录路径）。

日历视图渲染时 Odoo 一次读取窗口内全部事件的 conflict_kind/conflict_color，
compute 的 self = 整批记录；而 _compute_conflict 把 recs.ids 从 others 排除，
若两个冲突课时同属一批 → 互相看不见 → 视图上不显色（严重缺陷）。
本脚本验证：批量 browse([s1,s2])._compute_conflict() 后双方是否仍 ''/0。
"""
from datetime import datetime, timedelta

ok = fail = 0


def check(name, cond, detail=''):
    global ok, fail
    if cond:
        ok += 1
        print('PASS | %s | %s' % (name, detail))
    else:
        fail += 1
        print('FAIL | %s | %s' % (name, detail))


Param = env['ir.config_parameter'].sudo()
KEYS = ['timetable.is_faculty_constraint',
        'timetable.is_classroom_constraint',
        'timetable.is_batch_and_subject_constraint',
        'timetable.is_batch_constraint']
old_vals = {k: Param.get_param(k) for k in KEYS}
for k in KEYS:
    # '' 是上游真值检查唯一的 falsy 值（'False'/'0' 均 truthy）
    Param.set_param(k, '')

Session = env['op.session'].sudo()
BASE = datetime(2031, 2, 1, 10, 0)
fac = env['op.faculty'].sudo().search([], limit=1)
batch = env['op.batch'].sudo().search([], limit=1)
subj = env['op.subject'].sudo().search([], limit=1)
course = env['op.course'].sudo().search([], limit=1)
timing = env['op.timing'].sudo().search([], limit=1)

ids = []
try:
    def mk(start, end):
        return {
            'name': 'T6批量探针',
            'course_id': course.id,
            'faculty_id': fac.id,
            'batch_id': batch.id,
            'subject_id': subj.id,
            'timing_id': timing.id if timing else False,
            'start_datetime': start,
            'end_datetime': end,
            'state': 'done',
        }

    s1 = Session.create(mk(BASE, BASE + timedelta(minutes=45)))
    s2 = Session.create(mk(BASE + timedelta(minutes=30),
                           BASE + timedelta(minutes=75)))
    ids = [s1.id, s2.id]

    # 单记录路径（t4 shell 口径）：读取一条 → self=单条 → others 含另一条
    check('单记录读取 s1 冲突', s1.conflict_kind == 'faculty',
          'kind=%r' % s1.conflict_kind)
    check('单记录读取 s2 冲突', s2.conflict_kind == 'faculty',
          'kind=%r' % s2.conflict_kind)

    # 视图路径：一次性读取两条（等价 Odoo 日历视图批量 read）
    both = Session.browse(ids)
    both.invalidate_recordset(['conflict_kind', 'conflict_color'])
    # 模拟视图 read：一次计算两记录
    both._compute_conflict()
    k1 = both[0].conflict_kind
    k2 = both[1].conflict_kind
    check('批量计算 s1 仍显冲突', k1 == 'faculty', 'kind=%r' % k1)
    check('批量计算 s2 仍显冲突', k2 == 'faculty', 'kind=%r' % k2)

    # 更真实：invalidate 后通过 read() 路径触发
    both2 = Session.browse(ids)
    both2.invalidate_recordset(['conflict_kind', 'conflict_color'])
    vals = both2.read(['conflict_kind', 'conflict_color'])
    kv = {r['id']: r['conflict_kind'] for r in vals}
    check('read() 批量路径双方冲突', kv.get(s1.id) == 'faculty'
          and kv.get(s2.id) == 'faculty', 'kv=%s' % kv)
finally:
    if ids:
        Session.browse(ids).unlink()
    for k in KEYS:
        Param.set_param(k, old_vals.get(k) or 'True')
    env.cr.commit()

print('\n== %d passed, %d failed ==' % (ok, fail))
import sys
sys.exit(1 if fail else 0)
