#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t14 探针清理（幂等）：删除 2026-09-07 的 T14探针 课时 + 临时教师乙。

odoo shell 输入脚本（env 注入）。
"""
S = env['op.session'].sudo()
# name 是计算字段；按 9/7 窗口 + 起始时间特征删除探针课时（08:00/10:00/14:00 成对）
existing = S.search([('start_datetime', '>=', '2026-09-07 00:00:00'),
                     ('start_datetime', '<', '2026-09-08 00:00:00'),
                     ('state', '!=', 'cancel')])
ids = [s.id for s in existing
       if s.start_datetime.hour in (8, 10, 14)
       and s.start_datetime.minute in (0, 30)
       and (s.faculty_id.last_name in ('预备科', '教师乙'))]
if ids:
    S.browse(ids).unlink()
# 清理临时教师乙（last_name=教师乙 且 first_name=T14）
F = env['op.faculty'].sudo()
fac2 = F.search([('first_name', '=', 'T14'), ('last_name', '=', '教师乙')])
for f in fac2:
    try:
        f.unlink()
    except Exception:
        env.cr.rollback()
env.cr.commit()
print('CLEAN_OK', ids)
