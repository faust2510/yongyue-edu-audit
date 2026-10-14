# -*- coding: utf-8 -*-
"""一体化校历（v2.1-B10）：门户 /my/calendar 月视图 + 新建活动与冲突拦截。

四路数据源按角色过滤：
- 学生/家长：只看所属班级（课程/考试/活动均为班级集，停课取全校+本班）；
- 教师：自己教的课（op.session.faculty_id）+ 考试（任教班级/负责教师）
  + 全校活动（edu.event 全量）+ 停课（全校+任教班级）；
- 管理员/教务处/内部用户：全量只读；
- 其余门户账号：空表（不暴露全校数据，与课表页 guest 口径一致）。

新建活动仅管理员/教师可用；提交前按排课冲突拦截同款规则
（同教师/同教室/同班级时段重叠）预检，命中即以红字列出冲突并拦截，
模型层 @api.constrains 再兜底一道（后端直建同样不可绕过）。

不做拖拽、不做循环事件（P3 边界约定）。
"""
import calendar as cal_mod
from datetime import date, datetime, time, timedelta

import pytz
from odoo import fields, http
from odoo.fields import Datetime as Dt
from odoo.http import request

from .main import current_student, student_course
from .roles import current_faculty, current_parent
from .scheduling import _week_window_utc
from odoo.addons.edu_schedule.models.week_utils import term_anchor

_DAY_HEAD = ['日', '一', '二', '三', '四', '五', '六']

# 四种数据源在月视图里的芯片配色（与首页图标色系一致）
_KIND_COLOR = {
    'session': '#1D6FEB',   # 课程
    'exam': '#E7650A',      # 考试
    'holiday': '#DC2626',   # 停课
    'event': '#0E9F6E',     # 活动
}
_KIND_LABEL = {
    'session': '课程', 'exam': '考试', 'holiday': '停课', 'event': '活动',
}


def _local_dt(dt):
    """UTC naive → 用户时区 naive（展示口径，与课表页一致）。"""
    if not dt:
        return None
    return Dt.context_timestamp(request.env.user, dt).replace(tzinfo=None)


def _user_tz():
    return pytz.timezone(request.env.user.tz or 'UTC')


def _local_to_utc_naive(local_naive):
    """用户时区墙钟 → UTC naive（入库口径）。"""
    tz = _user_tz()
    try:
        aware = tz.localize(local_naive, is_dst=None)
    except pytz.exceptions.NonExistentTimeError:
        aware = tz.localize(local_naive, is_dst=False)
    except pytz.exceptions.AmbiguousTimeError:
        aware = tz.localize(local_naive, is_dst=False)
    return aware.astimezone(pytz.UTC).replace(tzinfo=None)


def _month_window_utc(year, month):
    """本地「当月首日 00:00 → 下月首日 00:00」对应的 UTC naive 起止。"""
    first = datetime(year, month, 1)
    nxt = first + timedelta(days=cal_mod.monthrange(year, month)[1])
    return _local_to_utc_naive(first), _local_to_utc_naive(nxt)


def _active_term():
    """当前处于进行中的学期（term_start_date<=今天<=term_end_date），无则 None。

    2026-08 迁移：底层锚点统一走 edu_schedule.models.week_utils.term_anchor（三级回退），
    但此处保持既有守卫语义——仅当今天落在学期窗口内才返回学期记录，否则 None
    （寒暑假等场景月视图走「不过滤」路径，行为与迁移前一致，t6 寒暑假回归覆盖）。
    """
    today = date.today()
    anchor = term_anchor(request.env, today)
    if not anchor:
        return None
    Term = request.env['op.academic.term'].sudo()
    term = Term.search([('term_start_date', '<=', today),
                        ('term_end_date', '>=', today)], limit=1)
    return term or None


def _role_scope():
    """解析当前用户的校历视角。

    返回 dict：role / batch_ids（本角色班级集）/ course_ids / faculty_id。
    role: student | parent | faculty | admin | staff | guest
    """
    env = request.env
    student = current_student()
    fac = current_faculty()
    parent = current_parent()
    batch_ids = course_ids = []
    faculty_id = fac.id if fac else None

    if student:
        role = 'student'
        course, batch = student_course(student)
        batch_ids = [batch.id] if batch else []
        course_ids = [course.id] if course else []
    elif parent:
        role = 'parent'
        Scs = env['op.student.course'].sudo()
        scs = Scs.search([('student_id', 'in', parent.student_ids.ids),
                          ('state', '=', 'running')])
        if not scs:
            scs = Scs.search([('student_id', 'in', parent.student_ids.ids)])
        batch_ids = scs.mapped('batch_id').ids
        course_ids = scs.mapped('course_id').ids
    elif fac:
        role = 'faculty'
        # 教师任教的班级集（冲突/停课过滤用）
        batch_ids = env['op.session'].sudo().search(
            [('faculty_id', '=', fac.id)]).mapped('batch_id').ids
    elif env.user._is_admin() or env.user.has_group(
            'openeducat_core.group_op_back_office_admin'):
        role = 'admin'
    elif env.user.has_group('base.group_user'):
        role = 'staff'
    else:
        role = 'guest'
    return {
        'role': role,
        'batch_ids': batch_ids or [0],
        'course_ids': course_ids or [0],
        'faculty_id': faculty_id,
        'student': student,
        'faculty': fac,
        'parent': parent,
    }


def _ical_feed_url(kw):
    """iCal 订阅 URL：仅 ?sub=1 时懒生成 token 并返回完整链接。

    基址取系统参数 web.base.url（生产为 https 域名，日历 App 可直接拉取）。"""
    if kw.get('sub') != '1':
        return ''
    token = request.env.user._ensure_ical_token()
    base = request.env['ir.config_parameter'].sudo().get_param(
        'web.base.url') or ''
    return '%s/my/calendar/ics/%s' % (base.rstrip('/'), token)


def month_event_count_for_user():
    """当前用户本月可见的活动数（口径同校历页，供首页卡片角标）。"""
    scope = _role_scope()
    today = date.today()
    win_start, win_end = _month_window_utc(today.year, today.month)
    domain = [('active', '=', True),
              ('start_datetime', '>=', win_start),
              ('start_datetime', '<', win_end)]
    if scope['role'] in ('student', 'parent'):
        domain = ['|', ('batch_id', 'in', scope['batch_ids']),
                  ('batch_id', '=', False)] + domain
    elif scope['role'] == 'guest':
        domain.append(('id', '=', 0))
    return request.env['edu.event'].sudo().search_count(domain)


class EduCalendar(http.Controller):

    def _can_create_event(self, scope):
        """新建活动仅管理员/教务处/教师可用（staff=内部用户的兜底）。"""
        return scope['role'] in ('faculty', 'admin', 'staff')

    # ------------------------------------------------------------------
    # /my/calendar 月视图
    # ------------------------------------------------------------------

    def _query_items(self, scope, win_start, win_end, term):
        """按角色域查询窗口内四路数据（S5 周/列表视图共用；月视图不动）。

        与月视图查询 domain 口径完全一致，仅窗口不同。
        返回 (sessions, exams, events, holidays)。
        """
        env = request.env
        role = scope['role']

        session_term_domain = []
        exam_term_domain = []
        if term:
            term_lo = datetime.combine(term.term_start_date, time.min)
            term_hi = datetime.combine(
                term.term_end_date + timedelta(days=1), time.min)
            session_term_domain = [
                ('start_datetime', '>=', term_lo),
                ('start_datetime', '<', term_hi),
            ]
            exam_term_domain = [
                ('start_time', '>=', term_lo),
                ('start_time', '<', term_hi),
            ]

        sessions = exams = events = holidays = []
        if role != 'guest':
            session_domain = [('state', '!=', 'cancel'),
                              ('start_datetime', '>=', win_start),
                              ('start_datetime', '<', win_end)
                              ] + session_term_domain
            if role == 'faculty':
                session_domain.append(('faculty_id', '=', scope['faculty_id']))
            elif role in ('student', 'parent'):
                session_domain.append(('batch_id', 'in', scope['batch_ids']))
            elif role == 'guest':
                session_domain.append(('id', '=', 0))
            sessions = env['op.session'].sudo().search(
                session_domain, order='start_datetime asc')

            exam_domain = [('state', '!=', 'cancel'),
                           ('start_time', '>=', win_start),
                           ('start_time', '<', win_end)] + exam_term_domain
            if role in ('student', 'parent'):
                exam_domain = ['|', ('batch_id', 'in', scope['batch_ids']),
                               ('course_id', 'in', scope['course_ids'])]
                exam_domain += [('state', '!=', 'cancel'),
                                ('start_time', '>=', win_start),
                                ('start_time', '<', win_end)] \
                    + exam_term_domain
            elif role == 'faculty':
                exam_domain = ['|', ('batch_id', 'in', scope['batch_ids']),
                               ('responsible_id', 'in',
                                [scope['faculty_id']])
                               if scope['faculty_id'] else ('id', '=', 0)]
                exam_domain += [('state', '!=', 'cancel'),
                                ('start_time', '>=', win_start),
                                ('start_time', '<', win_end)] \
                    + exam_term_domain
            exams = env['op.exam'].sudo().search(
                exam_domain, order='start_time asc')

            event_domain = [('active', '=', True),
                            ('start_datetime', '>=', win_start),
                            ('start_datetime', '<', win_end)]
            if role in ('student', 'parent'):
                event_domain = ['|',
                                ('batch_id', 'in', scope['batch_ids']),
                                ('batch_id', '=', False)] + event_domain
            events = env['edu.event'].sudo().search(
                event_domain, order='start_datetime asc')

            lo_date = _local_dt(win_start)
            hi_date = _local_dt(win_end)
            holiday_domain = [('active', '=', True),
                              ('date_start', '<=',
                               (hi_date.date() if hi_date else date.today())),
                              ('date_end', '>=',
                               (lo_date.date() if lo_date else date.today()))]
            if role in ('student', 'parent', 'faculty'):
                holiday_domain = ['|',
                                  ('batch_id', 'in', scope['batch_ids']),
                                  ('batch_id', '=', False)] + holiday_domain
            holidays = env['edu.schedule.holiday'].sudo().search(
                holiday_domain)
        return sessions, exams, events, holidays

    def _bucket_items(self, sessions, exams, events, holidays,
                      lo_date, hi_date):
        """四路数据按本地日期归桶 → (day_map, stats)。与月视图口径一致。"""
        day_map = {}
        stats = {'session': 0, 'exam': 0, 'holiday': 0, 'event': 0}

        def _put(day, item):
            day_map.setdefault(day.isoformat(), []).append(item)

        for ses in sessions:
            d = _local_dt(ses.start_datetime)
            if not d:
                continue
            stats['session'] += 1
            _put(d.date(), {
                'kind': 'session',
                'color': _KIND_COLOR['session'],
                'time': '%s-%s' % (d.strftime('%H:%M'),
                                   _local_dt(ses.end_datetime).strftime(
                                       '%H:%M') if ses.end_datetime else ''),
                'title': ses.subject_id.name or ses.course_id.name
                         or ses.name or '课程',
                'sub': '、'.join(x for x in [
                    ses.batch_id.name or '',
                    ses.classroom_id.name or '',
                ] if x),
            })
        for ex in exams:
            d = _local_dt(ex.start_time)
            if not d:
                continue
            stats['exam'] += 1
            _put(d.date(), {
                'kind': 'exam',
                'color': _KIND_COLOR['exam'],
                'time': '%s-%s' % (d.strftime('%H:%M'),
                                   _local_dt(ex.end_time).strftime('%H:%M')
                                   if ex.end_time else ''),
                'title': ex.name or (ex.subject_id.name or '考试'),
                'sub': ex.subject_id.name or '',
            })
        for ev in events:
            d = _local_dt(ev.start_datetime)
            if not d:
                continue
            stats['event'] += 1
            _put(d.date(), {
                'kind': 'event',
                'color': _KIND_COLOR['event'],
                'time': '%s-%s' % (d.strftime('%H:%M'),
                                   _local_dt(ev.end_datetime).strftime(
                                       '%H:%M') if ev.end_datetime else ''),
                'title': ev.name,
                'sub': '、'.join(x for x in [
                    ev.location or '',
                    dict(ev._fields['event_type'].selection).get(
                        ev.event_type, '') if ev.event_type else '',
                ] if x),
            })
        if holidays:
            for hd in holidays:
                day = max(hd.date_start, lo_date)
                last = min(hd.date_end, hi_date)
                while day <= last:
                    stats['holiday'] += 1
                    _put(day, {
                        'kind': 'holiday',
                        'color': _KIND_COLOR['holiday'],
                        'time': '',
                        'title': hd.name or '停课',
                        'sub': '停课' + ('（%s）' % hd.batch_id.name
                                         if hd.batch_id else ''),
                    })
                    day += timedelta(days=1)
        for lst in day_map.values():
            lst.sort(key=lambda i: (i['time'], i['title']))
        return day_map, stats

    @http.route('/my/calendar', type='http', auth='user', website=True)
    def my_calendar(self, y=None, m=None, view='month', w=0, **kw):
        """一体化校历：月（默认）/ 周 / 列表三视图（S5，钉钉日历五视图参照）。"""
        view = view if view in ('month', 'week', 'list') else 'month'
        if view == 'month':
            return self._calendar_month(y, m, kw)
        return self._calendar_week_list(view, w, kw)

    def _calendar_month(self, y, m, kw):
        env = request.env
        today = date.today()
        try:
            year = int(y or today.year)
            month = int(m or today.month)
        except (TypeError, ValueError):
            year, month = today.year, today.month
        if not 2000 <= year <= 2100:
            year = today.year
        if not 1 <= month <= 12:
            month = today.month

        scope = _role_scope()
        role = scope['role']
        win_start, win_end = _month_window_utc(year, month)
        month_start = date(year, month, 1)
        month_end = date(year, month,
                         cal_mod.monthrange(year, month)[1])

        # 本学期窗口（有进行中学期时才收窄课程/考试到学期内）
        # 注意：op.session 用 start_datetime、op.exam 用 start_time，
        # 两套学期同款过滤必须分开写字段名。
        term = _active_term()
        session_term_domain = []
        exam_term_domain = []
        if term:
            term_lo = datetime.combine(term.term_start_date, time.min)
            term_hi = datetime.combine(
                term.term_end_date + timedelta(days=1), time.min)
            session_term_domain = [
                ('start_datetime', '>=', term_lo),
                ('start_datetime', '<', term_hi),
            ]
            exam_term_domain = [
                ('start_time', '>=', term_lo),
                ('start_time', '<', term_hi),
            ]

        # ---- 课程 op.session ----
        session_domain = [('state', '!=', 'cancel'),
                          ('start_datetime', '>=', win_start),
                          ('start_datetime', '<', win_end)
                          ] + session_term_domain
        if role == 'faculty':
            session_domain.append(('faculty_id', '=', scope['faculty_id']))
        elif role == 'student':
            session_domain.append(('batch_id', 'in', scope['batch_ids']))
        elif role == 'parent':
            session_domain.append(('batch_id', 'in', scope['batch_ids']))
        elif role == 'guest':
            session_domain.append(('id', '=', 0))
        sessions = []
        if role != 'guest':
            sessions = env['op.session'].sudo().search(
                session_domain, order='start_datetime asc')

        # ---- 考试 op.exam ----
        exam_domain = [('state', '!=', 'cancel'),
                       ('start_time', '>=', win_start),
                       ('start_time', '<', win_end)] + exam_term_domain
        if role in ('student', 'parent'):
            exam_domain = ['|', ('batch_id', 'in', scope['batch_ids']),
                           ('course_id', 'in', scope['course_ids'])]
            exam_domain += [('state', '!=', 'cancel'),
                            ('start_time', '>=', win_start),
                            ('start_time', '<', win_end)] + exam_term_domain
        elif role == 'faculty':
            exam_domain = ['|', ('batch_id', 'in', scope['batch_ids']),
                           ('responsible_id', 'in', [scope['faculty_id']])
                           if scope['faculty_id'] else ('id', '=', 0)]
            exam_domain += [('state', '!=', 'cancel'),
                            ('start_time', '>=', win_start),
                            ('start_time', '<', win_end)] + exam_term_domain
        elif role == 'guest':
            exam_domain = [('id', '=', 0)]
        exams = []
        if role != 'guest':
            exams = env['op.exam'].sudo().search(
                exam_domain, order='start_time asc')

        # ---- 活动 edu.event ----
        event_domain = [('active', '=', True),
                        ('start_datetime', '>=', win_start),
                        ('start_datetime', '<', win_end)]
        if role in ('student', 'parent'):
            event_domain = ['|', ('batch_id', 'in', scope['batch_ids']),
                            ('batch_id', '=', False)] + event_domain
        elif role == 'guest':
            event_domain = [('id', '=', 0)] + event_domain
        events = []
        if role != 'guest':
            events = env['edu.event'].sudo().search(
                event_domain, order='start_datetime asc')

        # ---- 停课日 edu.schedule.holiday ----
        holiday_domain = [('active', '=', True),
                          ('date_start', '<=', month_end),
                          ('date_end', '>=', month_start)]
        if role in ('student', 'parent', 'faculty'):
            holiday_domain = ['|',
                              ('batch_id', 'in', scope['batch_ids']),
                              ('batch_id', '=', False)] + holiday_domain
        elif role == 'guest':
            holiday_domain = [('id', '=', 0)] + holiday_domain
        holidays = []
        if role != 'guest':
            holidays = env['edu.schedule.holiday'].sudo().search(
                holiday_domain)

        # ---- 按天归桶（本地日期） ----
        day_map = {}
        stats = {'session': 0, 'exam': 0, 'holiday': 0, 'event': 0}

        def _put(day, item):
            day_map.setdefault(day.isoformat(), []).append(item)

        for ses in sessions:
            d = _local_dt(ses.start_datetime)
            if not d:
                continue
            stats['session'] += 1
            _put(d.date(), {
                'kind': 'session',
                'color': _KIND_COLOR['session'],
                'time': '%s-%s' % (d.strftime('%H:%M'),
                                   _local_dt(ses.end_datetime).strftime('%H:%M')
                                   if ses.end_datetime else ''),
                'title': ses.subject_id.name or ses.course_id.name
                         or ses.name or '课程',
                'sub': '、'.join(x for x in [
                    ses.batch_id.name or '',
                    ses.classroom_id.name or '',
                ] if x),
            })
        for ex in exams:
            d = _local_dt(ex.start_time)
            if not d:
                continue
            stats['exam'] += 1
            _put(d.date(), {
                'kind': 'exam',
                'color': _KIND_COLOR['exam'],
                'time': '%s-%s' % (d.strftime('%H:%M'),
                                   _local_dt(ex.end_time).strftime('%H:%M')
                                   if ex.end_time else ''),
                'title': ex.name or (ex.subject_id.name or '考试'),
                'sub': ex.subject_id.name or '',
            })
        for ev in events:
            d = _local_dt(ev.start_datetime)
            if not d:
                continue
            stats['event'] += 1
            _put(d.date(), {
                'kind': 'event',
                'color': _KIND_COLOR['event'],
                'time': '%s-%s' % (d.strftime('%H:%M'),
                                   _local_dt(ev.end_datetime).strftime('%H:%M')
                                   if ev.end_datetime else ''),
                'title': ev.name,
                'sub': '、'.join(x for x in [
                    ev.location or '',
                    dict(ev._fields['event_type'].selection).get(
                        ev.event_type, '') if ev.event_type else '',
                ] if x),
            })
        for hd in holidays:
            day = max(hd.date_start, month_start)
            last = min(hd.date_end, month_end)
            while day <= last:
                stats['holiday'] += 1
                _put(day, {
                    'kind': 'holiday',
                    'color': _KIND_COLOR['holiday'],
                    'time': '',
                    'title': hd.name or '停课',
                    'sub': '停课' + ('（%s）' % hd.batch_id.name
                                     if hd.batch_id else ''),
                })
                day += timedelta(days=1)
        for lst in day_map.values():
            lst.sort(key=lambda i: (i['time'], i['title']))

        # ---- 月网格（周日起始，与首页侧栏月历一致） ----
        cal = cal_mod.Calendar(firstweekday=6)
        weeks = []
        for wk in cal.monthdatescalendar(year, month):
            weeks.append([{
                'day': d.day,
                'in_month': d.month == month,
                'today': d == today,
                'items': day_map.get(d.isoformat(), []),
            } for d in wk])

        prev_m = month - 1
        prev_y = year
        if prev_m == 0:
            prev_m, prev_y = 12, year - 1
        next_m = month + 1
        next_y = year
        if next_m == 13:
            next_m, next_y = 1, year + 1

        total = sum(stats.values())
        values = {
            'title': '校历',
            'page_name': 'calendar',
            'role': role,
            'view': 'month',
            'role_label': {
                'student': '学生视角', 'parent': '家长视角',
                'faculty': '教师视角', 'admin': '管理员视角',
                'staff': '内部只读视角', 'guest': '访客视角',
            }.get(role, ''),
            'year': year,
            'month': month,
            'month_title': '%d年%d月' % (year, month),
            'day_head': _DAY_HEAD,
            'weeks': weeks,
            'stats': stats,
            'total': total,
            'prev_href': '/my/calendar?y=%d&m=%d' % (prev_y, prev_m),
            'next_href': '/my/calendar?y=%d&m=%d' % (next_y, next_m),
            'today_href': '/my/calendar',
            'kind_label': _KIND_LABEL,
            'kind_color': _KIND_COLOR,
            'can_create': self._can_create_event(scope),
            'saved': kw.get('saved') == '1',
            'empty': total == 0,
            'ical_feed_url': _ical_feed_url(kw),
        }
        return request.render('edu_portal.edu_calendar', values)

    def _calendar_week_list(self, view, w, kw):
        """S5：周视图（节次×星期，三色事件芯片）+ 列表视图（按日议程）。"""
        env = request.env
        today = date.today()
        try:
            offset = int(w or 0)
        except (TypeError, ValueError):
            offset = 0
        scope = _role_scope()
        role = scope['role']
        term = _active_term()

        if view == 'week':
            local_today = Dt.context_timestamp(
                env.user, datetime.utcnow()).date()
            monday = local_today - timedelta(days=local_today.weekday()) \
                + timedelta(weeks=offset)
            win_start, win_end = _week_window_utc(monday)
            lo_date = monday
            hi_date = monday + timedelta(days=6)
            period_title = '%d月%d日 – %d月%d日' % (
                monday.month, monday.day, hi_date.month, hi_date.day)
            if offset == 0:
                period_title += '（本周）'
            # 周视图：三色事件按节次行归位（课程蓝/考试红/活动青绿/停课灰）
            timings = env['op.timing'].sudo().search(
                [], order='sequence asc, hour asc')
            rows = {t.id: {i: [] for i in range(7)} for t in timings}
            other = {i: [] for i in range(7)}
        else:
            # 列表视图：整个月窗口，按日分组的紧凑议程
            year = today.year
            month = today.month
            win_start, win_end = _month_window_utc(year, month)
            lo_date = date(year, month, 1)
            hi_date = date(year, month, cal_mod.monthrange(year, month)[1])
            period_title = '%d年%d月' % (year, month)
            rows = other = None
            year, month = year, month

        sessions, exams, events, holidays = self._query_items(
            scope, win_start, win_end, term)
        day_map, stats = self._bucket_items(
            sessions, exams, events, holidays, lo_date, hi_date)

        # 周视图网格行：课程按 op.timing 归行；考试/活动/未分节进「其他」行
        if view == 'week':
            for d in range(7):
                day = monday + timedelta(days=d)
                other[d] = [it for it in day_map.get(day.isoformat(), [])
                            if it['kind'] != 'session']
                other[d].sort(key=lambda i: (i['time'], i['title']))
            for ses in sessions:
                loc = _local_dt(ses.start_datetime)
                if not loc:
                    continue
                d = (loc.date() - monday).days
                tid = ses.timing_id.id if ses.timing_id else None
                if 0 <= d <= 6 and tid in rows:
                    rows[tid][d].append({
                        'kind': 'session',
                        'time': '%s-%s' % (
                            loc.strftime('%H:%M'),
                            _local_dt(ses.end_datetime).strftime('%H:%M')
                            if ses.end_datetime else ''),
                        'title': ses.subject_id.name or ses.course_id.name
                                 or ses.name or '课程',
                        'sub': '、'.join(x for x in [
                            ses.batch_id.name or '',
                            ses.classroom_id.name or '',
                        ] if x),
                    })
            week_rows = [{
                'timing': t,
                'cells': [rows[t.id][d] for d in range(7)],
            } for t in timings]
            week_rows.append({'timing': None, 'cells': [
                other[d] for d in range(7)]})
        else:
            week_rows = None

        # 列表视图：按日分组的议程（含今日高亮与停课标记）
        if view == 'list':
            list_days = []
            day = lo_date
            while day <= hi_date:
                items = day_map.get(day.isoformat(), [])
                list_days.append({
                    'date': day,
                    'iso': day.isoformat(),
                    'today': day == today,
                    'name': '周' + '一二三四五六日'[day.weekday()],
                    'items': items,
                })
                day += timedelta(days=1)
        else:
            list_days = None

        week_days = []
        if view == 'week':
            for d in range(7):
                day = monday + timedelta(days=d)
                week_days.append({
                    'iso': day.isoformat(),
                    'name': '周' + '一二三四五六日'[day.weekday()],
                    'day': day.day,
                    'label': '%d月%d日' % (day.month, day.day),
                    'today': day == today,
                    'holiday': any(
                        it['kind'] == 'holiday'
                        for it in day_map.get(day.isoformat(), [])),
                })
            prev_href = '/my/calendar?view=week&w=%d' % (offset - 1)
            next_href = '/my/calendar?view=week&w=%d' % (offset + 1)
            today_href = '/my/calendar?view=week'
        else:
            prev_m = month - 1
            prev_y = year
            if prev_m == 0:
                prev_m, prev_y = 12, year - 1
            next_m = month + 1
            next_y = year
            if next_m == 13:
                next_m, next_y = 1, year + 1
            prev_href = '/my/calendar?view=list&y=%d&m=%d' % (prev_y, prev_m)
            next_href = '/my/calendar?view=list&y=%d&m=%d' % (next_y, next_m)
            today_href = '/my/calendar?view=list'

        total = sum(stats.values())
        return request.render('edu_portal.edu_calendar', {
            'title': '校历',
            'page_name': 'calendar',
            'role': role,
            'view': view,
            'role_label': {
                'student': '学生视角', 'parent': '家长视角',
                'faculty': '教师视角', 'admin': '管理员视角',
                'staff': '内部只读视角', 'guest': '访客视角',
            }.get(role, ''),
            'period_title': period_title,
            'prev_href': prev_href,
            'next_href': next_href,
            'today_href': today_href,
            'stats': stats,
            'total': total,
            'kind_label': _KIND_LABEL,
            'kind_color': _KIND_COLOR,
            'can_create': self._can_create_event(scope),
            'empty': total == 0,
            'week_rows': week_rows,
            'week_days': week_days,
            'list_days': list_days,
            'day_head': _DAY_HEAD,
            'ical_feed_url': _ical_feed_url(kw),
            'view': view,
        })

    # ------------------------------------------------------------------
    # 新建活动（管理员/教师）：表单 + 冲突预检 + 创建
    # ------------------------------------------------------------------

    def _form_context(self, scope):
        env = request.env
        return {
            'title': '新建活动',
            'page_name': 'calendar_new',
            'types': [('meeting', '会议'), ('activity', '活动'),
                      ('ceremony', '典礼'), ('notice', '活动通知'),
                      ('other', '其他')],
            'batches': env['op.batch'].sudo().search(
                [], order='name asc'),
            'faculties': env['op.faculty'].sudo().search(
                [], order='name asc'),
            'classrooms': env['op.classroom'].sudo().search(
                [], order='name asc'),
        }

    @http.route('/my/calendar/new', type='http', auth='user', website=True)
    def calendar_new(self, **kw):
        scope = _role_scope()
        if not self._can_create_event(scope):
            return request.redirect('/my/calendar')
        values = self._form_context(scope)
        values.update({
            'form': {},          # 回填值（提交失败重渲染时保留输入）
            'error': None,       # 红字拦截明细
        })
        return request.render('edu_portal.edu_event_form', values)

    def _parse_event_post(self, post):
        """解析并校验表单，返回 (vals, error)。error 非 None 时 vals 无效。"""
        name = (post.get('name') or '').strip()
        if not name:
            return None, '请填写活动标题。'

        def _parse_dt(key):
            raw = (post.get(key) or '').strip()
            if not raw:
                return None, None, '请填写%s。' % (
                    '开始时间' if key == 'start_datetime' else '结束时间')
            raw = raw.replace('T', ' ')
            try:
                naive = datetime.fromisoformat(raw)
            except ValueError:
                return raw, None, '时间格式不正确，请使用网页选择器。'
            return raw, _local_to_utc_naive(naive), None

        start_raw, start_utc, err = _parse_dt('start_datetime')
        if err:
            return None, err
        end_raw, end_utc, err = _parse_dt('end_datetime')
        if err:
            return None, err
        if start_utc >= end_utc:
            return None, '结束时间必须晚于开始时间。'

        def _m2o(key):
            val = (post.get(key) or '').strip()
            try:
                return int(val) if val else False
            except (TypeError, ValueError):
                return False

        event_type = (post.get('event_type') or 'activity').strip()
        allowed_types = {'meeting', 'activity', 'ceremony', 'notice', 'other'}
        if event_type not in allowed_types:
            event_type = 'activity'
        vals = {
            'name': name,
            'start_datetime': start_utc,
            'end_datetime': end_utc,
            'location': (post.get('location') or '').strip(),
            'event_type': event_type,
            'batch_id': _m2o('batch_id'),
            'faculty_id': _m2o('faculty_id'),
            'classroom_id': _m2o('classroom_id'),
        }
        return vals, None

    @http.route('/my/calendar/create', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def calendar_create(self, **post):
        scope = _role_scope()
        if not self._can_create_event(scope):
            return request.redirect('/my/calendar')

        vals, error = self._parse_event_post(post)
        form = {
            'name': (post.get('name') or '').strip(),
            'start': (post.get('start_datetime') or '').strip(),
            'end': (post.get('end_datetime') or '').strip(),
            'location': (post.get('location') or '').strip(),
            'event_type': (post.get('event_type') or 'activity').strip(),
            'batch_id': (post.get('batch_id') or '').strip(),
            'faculty_id': (post.get('faculty_id') or '').strip(),
            'classroom_id': (post.get('classroom_id') or '').strip(),
        }
        Event = request.env['edu.event'].sudo()

        # 冲突预检（红字明细；模型层 constrains 再兜底）
        if not error:
            conflicts = Event._overlap_conflicts(
                vals['start_datetime'], vals['end_datetime'],
                vals['faculty_id'], vals['classroom_id'], vals['batch_id'])
            if conflicts:
                error = '时间冲突：该时段与已有排期重叠，已拦截未保存。'
                form['conflicts'] = ['%s「%s」（%s - %s）' % (
                    c['kind'], c['name'], c['start_str'], c['end_str'])
                    for c in conflicts]

        if error:
            values = self._form_context(scope)
            values.update({'form': form, 'error': error})
            return request.render('edu_portal.edu_event_form', values)

        try:
            rec = Event.create(vals)
        except Exception as e:
            values = self._form_context(scope)
            values.update({
                'form': form,
                'error': '保存失败：%s' % str(e).strip()[:200],
            })
            return request.render('edu_portal.edu_event_form', values)
        print('EVENT CREATED id=%s by user=%s' % (rec.id, request.env.uid))
        return request.redirect('/my/calendar?saved=1')