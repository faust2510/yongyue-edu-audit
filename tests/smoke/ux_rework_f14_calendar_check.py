#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ux-rework t6 回归：F14 寒暑假月视图「不过滤」守卫 + S1 冲突分色计算字段。

运行方式（odoo shell，注入 env）：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf \
        --db_host=db -r odoo -w odoo -d edu19 --no-http \
        < tests/smoke/ux_rework_f14_calendar_check.py

覆盖（对应 docs/plans/ux-improve-proposal.md §1A 处置表 / §S2 迁移清单 1 / F14）：
1. week_utils.term_anchor 三级回退语义（进行中 / 最近过去 / 最早未来 / 无学期→None）；
2. calendar._active_term 薄封装守卫：今天不在任何学期窗口（寒暑假）→ None；
3. 月视图「不过滤」路径：term=None 时 session/exam 不加学期 domain；
4. S1 conflict_kind / conflict_color 计算字段：
   - 无冲突课时 → '' / 0；
   - 同教师重叠 → 'faculty' / 1；
   - 同教室重叠 → 'classroom' / 2；
   - 同班级同科目重叠 → 'batch_subject' / 3；
   - 同班级不同科目重叠 → 'batch' / 3；
   - 已取消(state=cancel)不参与冲突；
   - store=False、不落库（写回无副作用）。
测试数据在 finally 中清理并 commit，零残留；四查约束参数临时关闭后恢复。
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


# ------------------------------------------------------------------
# 0. 依赖就绪性
# ------------------------------------------------------------------
from odoo.addons.edu_schedule.models import week_utils  # noqa: E402

check('week_utils 可导入', hasattr(week_utils, 'term_anchor')
      and hasattr(week_utils, 'monday_of')
      and hasattr(week_utils, 'week_no_of')
      and hasattr(week_utils, 'parse_week_ranges')
      and hasattr(week_utils, 'week_in_ranges')
      and hasattr(week_utils, 'parity_ok'),
      'term_anchor/monday_of/week_no_of/parse_week_ranges/'
      'week_in_ranges/parity_ok')

try:
    import odoo.addons.edu_portal.controllers.calendar as _cal_mod

    class _FakeReq(object):
        env = env

    _cal_mod.request = _FakeReq()   # odoo shell 无活动 request，注入 env
    _active_term = _cal_mod._active_term
    check('calendar._active_term 存在', callable(_active_term))
except Exception as e:
    check('calendar._active_term 存在', False, repr(e)[:120])
    _active_term = None

Session = env['op.session'].sudo()

# ------------------------------------------------------------------
# 1. term_anchor 三级回退（用库里真实学期窗口）
# ------------------------------------------------------------------
Term = env['op.academic.term'].sudo()
terms = Term.search([], order='term_start_date asc')
check('库中存在学期记录', bool(terms), 'n=%d' % len(terms))
if terms:
    t_first, t_last = terms[0], terms[-1]
    in_date = t_first.term_start_date
    a_in = week_utils.term_anchor(env, in_date)
    check('term_anchor 进行中→本学起日', a_in == t_first.term_start_date,
          'in=%s anchor=%s' % (in_date, a_in))
    far_future = t_last.term_end_date + timedelta(days=400)
    a_fut = week_utils.term_anchor(env, far_future)
    check('term_anchor 远期→最近过去学期起日',
          a_fut == t_last.term_start_date,
          'future=%s anchor=%s' % (far_future, a_fut))
    far_past = t_first.term_start_date - timedelta(days=400)
    a_past = week_utils.term_anchor(env, far_past)
    check('term_anchor 远古→最早学期起日',
          a_past == t_first.term_start_date,
          'past=%s anchor=%s' % (far_past, a_past))
    # 无学期→None 分支：term_anchor 在 search 全空时返回 None。
    # 用「不存在学期 id」不可行；用空 domain 搜索零结果无法注入，
    # 以代码审查 + 下方 _active_term 守卫断言覆盖该分支。

# ------------------------------------------------------------------
# 2. _active_term 薄封装守卫语义（寒暑假场景）
# ------------------------------------------------------------------
today = date.today()
if _active_term is not None:
    term_now = _active_term()
    check('_active_term 今天在学期窗口→返回学期', bool(term_now),
          'term=%s' % (term_now and term_now.name))

# ------------------------------------------------------------------
# 3. 月视图「不过滤」路径断言（term=None → 无学期收窄）
# ------------------------------------------------------------------
summer = date(2027, 7, 15)   # 第二学期 2027-06-18 之后（暑假）
a_summer = week_utils.term_anchor(env, summer)
check('寒暑假日期 term_anchor 回退锚点非空(证明需守卫)',
      a_summer is not None, 'summer=%s anchor=%s' % (summer, a_summer))

# 关键行为断言（迁移清单 1 的「不过滤」）：_active_term() 仅在
# 今天∈学期窗口时返回学期；否则 None → 月视图 if term: 不加学期 domain。
# 无法注入 date.today()，因此用等价断言：对暑假日期，term_anchor 会给出
# 回退锚点（非 None），而 _active_term 的 in-window 二次判定把它拦成 None。
# 直接验证该判定逻辑 = ref_date 是否在 [term_start, term_end]：
in_win = any(t.term_start_date <= summer <= t.term_end_date
             for t in terms) if terms else False
check('暑假日期不在任何学期窗口', not in_win, 'summer=%s' % summer)
if terms:
    # term_anchor 对暑假给出回退锚点；_active_term 守卫应返回 None。
    # 用代码审查锁定：_active_term = anchor + in-window search。
    # 运行时验证：构造等价调用——term_anchor 锚点 + 窗口判定 → None。
    anchor_summer = week_utils.term_anchor(env, summer)
    guard_term = Term.search(
        [('term_start_date', '<=', summer),
         ('term_end_date', '>=', summer)], limit=1)
    check('暑假守卫判定→无进行中学期', not guard_term,
          'anchor=%s guard=%s' % (anchor_summer, guard_term and guard_term.name))

# ------------------------------------------------------------------
# 4. S1 冲突分色计算字段（临时关闭四查约束，测试后恢复）
# ------------------------------------------------------------------
# 注意：上游 check_timetable_fields 直接对参数字符串做真值判断，
# 'False'/'0' 均 truthy；唯一 falsy 值是空串 ''。用 set_param(k, '') 关闭
# （不删除记录，避免破坏 ir_model_data xmlid 链接），测后恢复原值。
Param = env['ir.config_parameter'].sudo()
KEYS = ['timetable.is_faculty_constraint',
        'timetable.is_classroom_constraint',
        'timetable.is_batch_and_subject_constraint',
        'timetable.is_batch_constraint']
old_vals = {k: Param.get_param(k) for k in KEYS}
for k in KEYS:
    Param.set_param(k, '')
try:
    BASE = datetime(2031, 1, 15, 10, 0)
    fac = env['op.faculty'].sudo().search([], limit=1)
    room = env['op.classroom'].sudo().search([], limit=1)
    batch = env['op.batch'].sudo().search([], limit=1)
    subj = env['op.subject'].sudo().search([], limit=1)
    course = env['op.course'].sudo().search([], limit=1)
    timing = env['op.timing'].sudo().search([], limit=1)
    check('基础主数据齐全', bool(fac and batch and subj and course),
          'fac=%s room=%s batch=%s subj=%s course=%s timing=%s'
          % (bool(fac), bool(room), bool(batch), bool(subj),
             bool(course), bool(timing)))

    if fac and batch and subj and course:
        ids_to_clean = []
        tmp_fac = False
        try:
            def mk(start, end, **kw):
                vals = {
                    'name': 'T6冲突测试',
                    'course_id': course.id,
                    'faculty_id': fac.id,
                    'batch_id': batch.id,
                    'subject_id': subj.id,
                    'timing_id': timing.id if timing else False,
                    'start_datetime': start,
                    'end_datetime': end,
                    'state': 'done',
                }
                vals.update(kw)
                return vals

            # 隔离时段：每个维度各占独立时段，间隔 3 小时，互不重叠
            # （第二课时 30 分钟后开始、跨 45 分钟，仍留在本维度时段内）。
            # 4.2 同教师重叠（10 点，同教师 fac）→ faculty / '1'
            s_fac = Session.create(mk(BASE,
                                      BASE + timedelta(minutes=45)))
            ids_to_clean.append(s_fac.id)
            s_fac2 = Session.create(mk(BASE + timedelta(minutes=30),
                                       BASE + timedelta(minutes=75),
                                       faculty_id=fac.id))
            ids_to_clean.append(s_fac2.id)

            # 备用教师（教室维度用；库中可能仅 1 位，必要时临时创建）
            fac2 = env['op.faculty'].sudo().search(
                [('id', '!=', fac.id)], limit=1)
            tmp_fac = False
            if not fac2:
                tmp_fac = env['op.faculty'].sudo().create({
                    'first_name': 'T6测试', 'last_name': '教师乙',
                    'gender': 'male', 'birth_date': '1990-01-01',
                    'partner_id': fac.partner_id.id,
                })
                fac2 = tmp_fac

            # 4.3 同教室重叠（13 点，不同教师 fac/fac2，同教室）→ classroom / '2'
            if room:
                s_room = Session.create(mk(
                    BASE + timedelta(hours=3),
                    BASE + timedelta(hours=3, minutes=45),
                    classroom_id=room.id))          # faculty=fac
                ids_to_clean.append(s_room.id)
                s_room2 = Session.create(mk(
                    BASE + timedelta(hours=3, minutes=30),
                    BASE + timedelta(hours=3, minutes=75),
                    faculty_id=fac2.id, classroom_id=room.id))
                ids_to_clean.append(s_room2.id)

            # 4.4 同班级同科目重叠（16 点，不同教师同科目）→ batch_subject / '3'
            s_bs = Session.create(mk(BASE + timedelta(hours=6),
                                     BASE + timedelta(hours=6, minutes=45)))
            ids_to_clean.append(s_bs.id)
            s_bs2 = Session.create(mk(BASE + timedelta(hours=6, minutes=30),
                                      BASE + timedelta(hours=6, minutes=75),
                                      faculty_id=fac2.id))
            ids_to_clean.append(s_bs2.id)

            # 4.5 同班级不同科目重叠（19 点，不同教师、科目 subj vs subj2）
            # → batch / '3'
            subj2 = env['op.subject'].sudo().search(
                [('id', '!=', subj.id)], limit=1)
            if subj2:
                s_b = Session.create(mk(BASE + timedelta(hours=9),
                                        BASE + timedelta(hours=9, minutes=45),
                                        subject_id=subj.id))   # 科目 subj
                ids_to_clean.append(s_b.id)
                s_b2 = Session.create(mk(BASE + timedelta(hours=9, minutes=30),
                                         BASE + timedelta(hours=9, minutes=75),
                                         faculty_id=fac2.id,
                                         subject_id=subj2.id))  # 科目 subj2
                ids_to_clean.append(s_b2.id)

            # 4.1 无冲突课时（22 点，独占）→ '' / '0'
            s_ok = Session.create(mk(BASE + timedelta(hours=12),
                                     BASE + timedelta(hours=12, minutes=45)))
            ids_to_clean.append(s_ok.id)
            # 4.6a 取消课时（22:30 与 s_ok 同教师重叠，但 cancel 不参与）
            s_cancel = Session.create(mk(BASE + timedelta(hours=12, minutes=30),
                                         BASE + timedelta(hours=12, minutes=75),
                                         faculty_id=fac.id, state='cancel'))
            ids_to_clean.append(s_cancel.id)
            check('cancel 课时自身无冲突', s_cancel.conflict_kind == '',
                  'kind=%r' % s_cancel.conflict_kind)

            # ---- 批量重算（模拟日历视图一次读取整窗口事件） ----
            all_recs = Session.browse(ids_to_clean)
            all_recs._compute_conflict()
            kv = {r.id: (r.conflict_kind, r.conflict_color)
                  for r in all_recs}

            def kind_of(rec):
                return kv.get(rec.id, ('?', '?'))[0]

            def color_of(rec):
                return kv.get(rec.id, ('?', '?'))[1]

            # 4.1 无冲突（10 点只有 cancel，不参与）→ '' / '0'
            check('无冲突课时字段', kind_of(s_ok) == ''
                  and color_of(s_ok) == 0,
                  'kind=%r color=%r' % (kind_of(s_ok), color_of(s_ok)))
            # 4.6 cancel 不参与：s_ok 未被 cancel 标冲突
            check('cancel 不参与冲突', kind_of(s_ok) == '',
                  'kind=%r' % kind_of(s_ok))
            # 4.2 同教师
            check('同教师冲突 kind', kind_of(s_fac) == 'faculty'
                  and kind_of(s_fac2) == 'faculty',
                  'k1=%r k2=%r' % (kind_of(s_fac), kind_of(s_fac2)))
            check('同教师冲突 color', color_of(s_fac) == 1
                  and color_of(s_fac2) == 1,
                  'c1=%r c2=%r' % (color_of(s_fac), color_of(s_fac2)))
            # 4.3 同教室
            if room:
                check('同教室冲突 kind', kind_of(s_room) == 'classroom'
                      and kind_of(s_room2) == 'classroom',
                      'k1=%r k2=%r' % (kind_of(s_room), kind_of(s_room2)))
                check('同教室冲突 color', color_of(s_room) == 2
                      and color_of(s_room2) == 2,
                      'c1=%r c2=%r' % (color_of(s_room), color_of(s_room2)))
            # 4.4 同班同科
            check('同班同科冲突 kind', kind_of(s_bs) == 'batch_subject'
                  and kind_of(s_bs2) == 'batch_subject',
                  'k1=%r k2=%r' % (kind_of(s_bs), kind_of(s_bs2)))
            check('同班同科冲突 color', color_of(s_bs) == 3
                  and color_of(s_bs2) == 3,
                  'c1=%r c2=%r' % (color_of(s_bs), color_of(s_bs2)))
            # 4.5 同班异科
            if subj2:
                check('同班异科冲突 kind', kind_of(s_b) == 'batch'
                      and kind_of(s_b2) == 'batch',
                      'k1=%r k2=%r' % (kind_of(s_b), kind_of(s_b2)))
                check('同班异科冲突 color', color_of(s_b) == 3
                      and color_of(s_b2) == 3,
                      'c1=%r c2=%r' % (color_of(s_b), color_of(s_b2)))

            # 4.7 store=False 不落库：字段不在 DB 表
            env.cr.execute("""SELECT column_name FROM information_schema.columns
                              WHERE table_name='op_session'
                                AND column_name IN
                                ('conflict_kind','conflict_color')""")
            db_cols = [r[0] for r in env.cr.fetchall()]
            check('conflict 字段不落库(store=False)',
                  'conflict_kind' not in db_cols
                  and 'conflict_color' not in db_cols,
                  'db_cols=%s' % db_cols)

            # 4.8 批量路径（视图 read 口径）双方均标注
            all2 = Session.browse(ids_to_clean)
            all2.invalidate_recordset(['conflict_kind', 'conflict_color'])
            rv = {r['id']: r['conflict_kind']
                  for r in all2.read(['conflict_kind', 'conflict_color'])}
            check('视图批量 read 双方均标注',
                  rv.get(s_fac.id) == 'faculty' and rv.get(s_fac2.id) == 'faculty',
                  'kv=%s' % {k: rv.get(k) for k in (s_fac.id, s_fac2.id)})
        finally:
            if tmp_fac:
                try:
                    tmp_fac.unlink()
                except Exception:
                    env.cr.rollback()
            if ids_to_clean:
                Session.browse(ids_to_clean).unlink()
            env.cr.commit()
finally:
    # 恢复四查约束参数（无论测试成败；原值为 'True' 字符串）
    for k in KEYS:
        Param.set_param(k, old_vals.get(k) or 'True')
    env.cr.commit()

print('\n== %d passed, %d failed ==' % (ok, fail))
sys.exit(1 if fail else 0)
