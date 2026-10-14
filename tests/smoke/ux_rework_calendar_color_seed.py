#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t14 探针造数（幂等）：2026-09-07 三组冲突课时（同教师/同教室/同班级）。

odoo shell 输入脚本（env 注入）。已存在则跳过（按 name='T14探针' + 日期窗口查重）。
输出 SEED_OK <ids> 供主探针解析。
"""
from datetime import datetime

Param = env['ir.config_parameter'].sudo()
KEYS = ['timetable.is_faculty_constraint', 'timetable.is_classroom_constraint',
        'timetable.is_batch_and_subject_constraint', 'timetable.is_batch_constraint']
S = env['op.session'].sudo()
# name 是计算字段（faculty:subject:timing），不能按 name 查重；按 9/7 窗口 + 教师/主题特征
existing = S.search([('start_datetime', '>=', '2026-09-07 00:00:00'),
                     ('start_datetime', '<', '2026-09-08 00:00:00'),
                     ('state', '!=', 'cancel')])
# 只保留本探针造的 6 条（08:00-08:45 起、10:00 起、14:00 起的成对课时）
mine = [s for s in existing
        if s.start_datetime.hour in (8, 10, 14)
        and s.start_datetime.minute in (0, 30)
        and (s.faculty_id.last_name in ('预备科', '教师乙'))]
if len(mine) >= 6:
    print('SEED_OK', [s.id for s in mine])
else:
    old = {k: Param.get_param(k) for k in KEYS}
    for k in KEYS:
        Param.set_param(k, '')
    fac = env['op.faculty'].sudo().search([], limit=1)
    batch = env['op.batch'].sudo().search([], limit=1)
    subj = env['op.subject'].sudo().search([], limit=1)
    course = env['op.course'].sudo().search([], limit=1)
    timing = env['op.timing'].sudo().search([], limit=1)
    room = env['op.classroom'].sudo().search([], limit=1)
    fac2 = env['op.faculty'].sudo().search([('id', '!=', fac.id)], limit=1)
    if not fac2:
        fac2 = env['op.faculty'].sudo().create({
            'first_name': 'T14', 'last_name': '教师乙',
            'gender': 'male', 'birth_date': '1990-01-01',
            'partner_id': fac.partner_id.id})

    def mk(start, end, **kw):
        v = {'name': 'T14探针', 'course_id': course.id, 'faculty_id': fac.id,
             'batch_id': batch.id, 'subject_id': subj.id,
             'timing_id': timing.id if timing else False,
             'start_datetime': start, 'end_datetime': end, 'state': 'done'}
        v.update(kw)
        return v

    ids = []
    ids.append(S.create(mk(datetime(2026, 9, 7, 8, 0), datetime(2026, 9, 7, 8, 45))).id)
    ids.append(S.create(mk(datetime(2026, 9, 7, 8, 30), datetime(2026, 9, 7, 9, 15))).id)
    ids.append(S.create(mk(datetime(2026, 9, 7, 10, 0), datetime(2026, 9, 7, 10, 45),
                           classroom_id=room.id)).id)
    ids.append(S.create(mk(datetime(2026, 9, 7, 10, 30), datetime(2026, 9, 7, 11, 15),
                           faculty_id=fac2.id, classroom_id=room.id)).id)
    ids.append(S.create(mk(datetime(2026, 9, 7, 14, 0), datetime(2026, 9, 7, 14, 45))).id)
    ids.append(S.create(mk(datetime(2026, 9, 7, 14, 30), datetime(2026, 9, 7, 15, 15),
                           faculty_id=fac2.id)).id)
    for k in KEYS:
        Param.set_param(k, old.get(k) or 'True')
    env.cr.commit()
    print('SEED_OK', ids)
