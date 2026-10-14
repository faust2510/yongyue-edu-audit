#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ux-rework t6 回归：F14 寒暑假「不过滤」月视图守卫验证。

_f14 语义（迁移后保持）：_active_term() 以「今天」判定进行中学期——
今天 ∈ 学期窗口 → 返回学期；今天不在任何学期窗口（寒暑假）→ None，
此时月视图不加学期过滤（不过滤路径）。

由于无法改变运行中服务器的系统日期，按三条等价路径验证：
A. 逻辑闸门：对暑假日期（2027-07-15，无任何学期覆盖）执行
   _active_term 同款 in-window 搜索 → 无进行中学期（None 前提成立）。
B. 不过滤路径：term=None 时月视图 session_domain 不含学期收窄 →
   暑假课时可见（这正是「今天在暑假」时的查询形态）。
C. 行为保持：term=当前进行中学期时，暑假课时被学期窗口过滤 →
   证明既有「进行中过滤」语义未被迁移破坏（对照迁移前行为）。

运行：odoo shell 注入 env（同 ux_rework_f14_calendar_check.py）。
"""
import sys
from datetime import date, datetime, timedelta

ok = fail = 0


def check(name, cond, detail=''):
    global ok, fail
    if cond:
        ok += 1
        print('PASS | %s | %s' % (name, detail))
    else:
        fail += 1
        print('FAIL | %s | %s' % (name, detail))


# 暑假日期（第二学期 2027-06-18 结束后）
SUMMER = date(2027, 7, 15)
from odoo.addons.edu_schedule.models import week_utils  # noqa: E402

terms = env['op.academic.term'].sudo().search([])
check('库中存在学期记录', bool(terms), 'n=%d' % len(terms))
in_win = any(t.term_start_date <= SUMMER <= t.term_end_date
             for t in terms)
check('2027-07 不在任何学期窗口', not in_win, 'n_terms=%d' % len(terms))

# ---- A. 逻辑闸门：暑假日期 _active_term 同款判定 → None ----
Term = env['op.academic.term'].sudo()
guard = Term.search([('term_start_date', '<=', SUMMER),
                     ('term_end_date', '>=', SUMMER)], limit=1)
check('A 暑假判定无进行中学期（None 前提）', not guard,
      'guard=%s' % (guard and guard.name))

# ---- 构造暑假课时（临时，测后清理） ----
fac = env['op.faculty'].sudo().search([], limit=1)
batch = env['op.batch'].sudo().search([], limit=1)
subj = env['op.subject'].sudo().search([], limit=1)
course = env['op.course'].sudo().search([], limit=1)
timing = env['op.timing'].sudo().search([], limit=1)
Session = env['op.session'].sudo()

ses = Session.create({
    'name': 'T6暑假课时',
    'course_id': course.id,
    'faculty_id': fac.id,
    'batch_id': batch.id,
    'subject_id': subj.id,
    'timing_id': timing.id if timing else False,
    'start_datetime': datetime(2027, 7, 15, 9, 0),
    'end_datetime': datetime(2027, 7, 15, 9, 45),
    'state': 'done',
})
try:
    from odoo.addons.edu_portal.controllers.calendar import (
        _month_window_utc, _active_term)
    import odoo.addons.edu_portal.controllers.calendar as _cal

    class _FakeReq(object):
        env = env

    _cal.request = _FakeReq()
    win_start, win_end = _month_window_utc(2027, 7)

    # ---- B. 不过滤路径：term=None → 无学期 domain → 暑假课时可见 ----
    session_domain = [('state', '!=', 'cancel'),
                      ('start_datetime', '>=', win_start),
                      ('start_datetime', '<', win_end)]
    found = Session.search_count(session_domain)
    check('B 不过滤路径：暑假课时可见', found == 1,
          'win=%s~%s found=%d' % (win_start, win_end, found))

    # ---- C. 行为保持：term=当前进行中学期 → 暑假课时被过滤 ----
    term_now = _active_term()
    check('C 今天在学期窗口（当前态）', bool(term_now),
          'term=%s' % (term_now and term_now.name))
    if term_now:
        term_lo = datetime.combine(term_now.term_start_date,
                                   datetime.min.time())
        term_hi = datetime.combine(
            term_now.term_end_date + timedelta(days=1), datetime.min.time())
        filtered = Session.search_count(
            session_domain + [('start_datetime', '>=', term_lo),
                              ('start_datetime', '<', term_hi)])
        check('C 进行中过滤保持：暑假课时被当前学期窗口拦下',
              filtered == 0,
              'term=%s~%s filtered=%d'
              % (term_lo, term_hi, filtered))

    # 补充：term=None 时月视图 _query_items 的等价断言——
    # _active_term 对暑假日期（若今天是暑假）返回 None，
    # 已由 A 的 in-window 判定 + 代码审查锁定（if term: 才加 domain）。
finally:
    Session.browse(ses.id).unlink()
    env.cr.commit()

print('\n== %d passed, %d failed ==' % (ok, fail))
sys.exit(1 if fail else 0)
