# -*- coding: utf-8 -*-
"""排课中心 · 周课表门户（学生/教师/家长/内部 四视角 + 周导航 + 日视图）。

覆写 main.EduPortalHome.student_timetable：
- 按自然周过滤课时并支持上周/本周/下周导航；
- S4：周/日视图切换、今天定位（当天列高亮）、第 N 周标注（学期锚点，
  与周期排课/校历共用 edu_schedule.models.week_utils 口径）、停课日灰显；
- 角色感知数据域：学生=本班、教师=本人任教、家长=孩子班级合集、
  内部用户=全校只读、其余门户账号=空表（不暴露全校数据）；
- 无 op.timing 归属的课时落入「未分节」行，不再静默丢弃。

设计文档：docs/plans/timetable-design.md、docs/plans/ux-improve-proposal.md §S4。
"""
import logging
from datetime import datetime, timedelta

import pytz
from odoo import http
from odoo.fields import Date
from odoo.fields import Datetime as Dt
from odoo.http import request

from odoo.addons.edu_schedule.models.week_utils import (
    monday_of, term_anchor, week_no_of, week_window_utc,
)

from .main import EduPortalHome, current_student, student_course
from .roles import current_faculty, current_parent

_logger = logging.getLogger(__name__)

DAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

# 日视图 d= 解析失败的**进程内**累计次数（S4 静默失效修复，2026-09-18）。
_bad_day_param_count = 0


def bad_day_param_count():
    """d= 解析失败累计次数（供自检 / 冒烟读取；进程内计数，重启归零）。

    注意本服务 workers=6 ⇒ 该计数是「某个 worker 的」累计值，跨请求不保证单调；
    作为「可计数」的证据请以日志为准（每次失败都有一条 WARNING，含运行号）。
    """
    return _bad_day_param_count


def _parse_day_param(d, today_local):
    """URL 的 d= → 本地日期；解析失败回退「今天」，但**绝不静默**。

    缺陷现场（2026-09-18 实测复现）：原实现调 Datetime.to_date(str(d))，
    而 **Odoo 19 的 Datetime 类上没有 to_date** —— 运行时源码
    odoo/orm/fields_temporal.py 里 to_date 只定义在 Date（:138），
    Datetime（:191）只有 now/today/context_timestamp/to_datetime/to_string。
    于是这里抛 AttributeError，被 except Exception 吞掉后**恒回落今天**
    ⇒ 日视图「前一天 / 后一天」点了没反应（页面永远显示今天，且无任何痕迹）。

    修法：改用 Odoo 19 的正确 API Date.to_date（接受 str / date / datetime，
    非日期串抛 ValueError），并保留兜底分支 —— 但兜底**必须可计数、有痕迹**：
    每次失败都打一条 WARNING（带原始入参、异常类型与累计次数）。
    本仓既有教训：静默失败要按缺陷处理，「没有课节」与「参数没解析出来」
    必须在日志上不同形。
    """
    global _bad_day_param_count
    day = None
    try:
        day = Date.to_date(str(d))
    except Exception as exc:      # noqa: BLE001 —— 兜底可以，静默不可以
        _bad_day_param_count += 1
        _logger.warning(
            '课表日视图 d 参数解析失败（累计 %d 次），已回退今天：d=%r（%s: %s）',
            _bad_day_param_count, d, type(exc).__name__, exc, exc_info=True)
        return today_local
    if not day:
        # to_date 对空/None 返回 None：d 明明是传进来的却解析成空，同样要留痕
        _bad_day_param_count += 1
        _logger.warning(
            '课表日视图 d 参数解析为空（累计 %d 次），已回退今天：d=%r',
            _bad_day_param_count, d)
        return today_local
    return day


def _local_dt(dt):
    """UTC naive → 用户时区 naive（用于星期归位）。"""
    if not dt:
        return None
    return Dt.context_timestamp(request.env.user, dt).replace(tzinfo=None)


def _week_window_utc(monday_local):
    """本地周一 naive → 该自然周起止的 UTC naive（薄封装，唯一实现见 week_utils）。"""
    return week_window_utc(monday_local, request.env.user.tz or 'UTC')


def _day_window_utc(day_local):
    """本地某日 00:00 → 次日 00:00 的 UTC naive 窗口。"""
    tz = pytz.timezone(request.env.user.tz or 'UTC')
    start = tz.localize(
        datetime(day_local.year, day_local.month, day_local.day))
    end = start + timedelta(days=1)

    def to_utc(d):
        return d.astimezone(pytz.UTC).replace(tzinfo=None)

    return to_utc(start), to_utc(end)


def _role_batch_context(role, student, fac, parent):
    """返回该角色「判定停课归属的班级集」；staff 用 -1 哨兵只认全校停课。"""
    env = request.env
    if role == 'student':
        _, batch = student_course(student)
        return [batch.id] if batch else []
    if role == 'faculty':
        return env['op.session'].sudo().search(
            [('faculty_id', '=', fac.id)]).mapped('batch_id').ids
    if role == 'parent':
        Scs = env['op.student.course'].sudo()
        scs = Scs.search([('student_id', 'in', parent.student_ids.ids),
                          ('state', '=', 'running')])
        if not scs:
            scs = Scs.search([('student_id', 'in', parent.student_ids.ids)])
        return scs.mapped('batch_id').ids
    return [-1]   # staff/guest：只有全校停课（batch_id 为空）才算停课


class EduScheduling(EduPortalHome):
    """在原门户控制器之上，接管 /student/timetable。"""

    @http.route('/student/timetable', type='http', auth='user', website=True)
    def student_timetable(self, w=0, view='week', d=None, **kw):
        env = request.env
        user = env.user
        student = current_student()
        fac = current_faculty()
        parent = current_parent()
        try:
            offset = int(w or 0)
        except (TypeError, ValueError):
            offset = 0
        if view not in ('week', 'day'):
            view = 'week'

        # 本地时区的周一（context_timestamp 以 UTC naive 为入参）
        today_local = Dt.context_timestamp(user, datetime.utcnow()).date()
        monday = monday_of(today_local) + timedelta(weeks=offset)

        domain = []
        if fac:
            title, role = '我的教学安排', 'faculty'
            domain.append(('faculty_id', '=', fac.id))
        elif student:
            title, role = '我的课表', 'student'
            _, batch = student_course(student)
            domain.append(('batch_id', '=', batch.id if batch else 0))
        elif parent:
            title, role = '孩子的课表', 'parent'
            Scs = env['op.student.course'].sudo()
            scs = Scs.search([('student_id', 'in', parent.student_ids.ids),
                              ('state', '=', 'running')])
            if not scs:
                scs = Scs.search(
                    [('student_id', 'in', parent.student_ids.ids)])
            batch_ids = scs.mapped('batch_id').ids
            domain.append(('batch_id', 'in', batch_ids or [0]))
        elif user.has_group('base.group_user'):
            title, role = '全校课表（只读）', 'staff'
        else:
            # 既非学生/教师/家长、也非内部用户：空表，绝不给全校数据
            title, role = '课表', 'guest'
            domain.append(('id', '=', 0))

        # ---- S4：窗口（周视图=自然周；日视图=单日）----
        if view == 'day':
            # d= 缺失 ⇒ 今天（正常）；d= 有值但解析失败 ⇒ 也回退今天，但会
            # 打 WARNING 并计数（_parse_day_param），不再静默。
            day_date = _parse_day_param(d, today_local) if d else today_local
            win_start, win_end = _day_window_utc(day_date)
            day_label = '%d月%d日 %s' % (
                day_date.month, day_date.day, DAY_NAMES[day_date.weekday()])
            if day_date == today_local:
                day_label += '（今天）'
            anchor = term_anchor(env, day_date)
            week_no = week_no_of(day_date, anchor)
            holiday_batches = _role_batch_context(
                role, student, fac, parent)
        else:
            day_date = None
            win_start, win_end = _week_window_utc(monday)
            anchor = term_anchor(env, monday)
            week_no = week_no_of(monday, anchor)
            holiday_batches = _role_batch_context(
                role, student, fac, parent)

        # §18（2026-09-18）：停课（state='cancel'）的课节不再出现在课表里。
        # 此前只有校历 / ICS / 学习页过滤了 cancel，课表页漏了 —— 于是
        # 「批量停用某班课时」在师生课表上看不出效果（本仓惯例：先给判据）。
        fulldomain = [
            ('state', '!=', 'cancel'),
            ('start_datetime', '<', Dt.to_string(win_end)),
            ('end_datetime', '>=', Dt.to_string(win_start)),
        ] + domain

        sessions = env['op.session'].sudo().search(
            fulldomain, order='start_datetime asc')

        # ---- S4 停课灰显：holiday _matches(day, batch)（sudo 只读）----
        holidays = env['edu.schedule.holiday'].sudo().search(
            [('active', '=', True)])
        holiday_map = {}
        h_start = day_date if view == 'day' else monday
        h_end = day_date if view == 'day' else monday + timedelta(days=6)
        day = h_start
        while day <= h_end:
            for h in holidays:
                for bch in holiday_batches:
                    if h._matches(day, bch):
                        holiday_map[day.isoformat()] = h.name or '停课'
                        break
                if day.isoformat() in holiday_map:
                    break
            day += timedelta(days=1)

        # [时段][星期] 矩阵 + 未分节桶
        timings = env['op.timing'].sudo().search(
            [], order='sequence asc, hour asc')
        matrix = {t.id: {dd: [] for dd in DAY_NAMES} for t in timings}
        loose = {dd: [] for dd in DAY_NAMES}
        ses_fmt = {}   # ses.id -> (start HH:mm, end HH:mm)，与星期归桶同一时区换算
        for ses in sessions:
            loc_start = _local_dt(ses.start_datetime)
            loc_end = _local_dt(ses.end_datetime)
            ses_fmt[ses.id] = (
                loc_start.strftime('%H:%M') if loc_start else '',
                loc_end.strftime('%H:%M') if loc_end else '',
            )
            key = DAY_NAMES[loc_start.weekday()] if loc_start else DAY_NAMES[0]
            if ses.timing_id and ses.timing_id.id in matrix:
                matrix[ses.timing_id.id][key].append(ses)
            else:
                loose[key].append(ses)

        # S4 日视图：单日窗口统一归入「周一」列渲染（避免模板按日硬编码）
        if view == 'day' and day_date:
            day_name = DAY_NAMES[day_date.weekday()]
            for tid, m in matrix.items():
                m['周一'] = m[day_name]
            loose['周一'] = loose[day_name]
        has_loose = bool(loose['周一']) if view == 'day' \
            else any(loose.values())

        # ---- 模板数据：周视图与日视图共用同一矩阵渲染 ----
        if view == 'day':
            cur_days = [day_date]
        else:
            cur_days = [monday + timedelta(days=i) for i in range(7)]

        day_flags = []
        for dd in cur_days:
            day_flags.append({
                'iso': dd.isoformat(),
                'name': DAY_NAMES[dd.weekday()],
                'label': '%d月%d日' % (dd.month, dd.day),
                'today': dd == today_local,
                'holiday': holiday_map.get(dd.isoformat(), ''),
            })

        week_no_label = ('第 %d 周' % week_no) if week_no else ''
        if view == 'week':
            sunday = monday + timedelta(days=6)
            week_label = f'{monday.month}月{monday.day}日 – ' \
                         f'{sunday.month}月{sunday.day}日'
            if offset == 0:
                week_label += '（本周）'
        else:
            week_label = day_label

        if view == 'day':
            prev_day = day_date - timedelta(days=1)
            next_day = day_date + timedelta(days=1)
            prev_href = '/student/timetable?view=day&d=%s' % prev_day
            next_href = '/student/timetable?view=day&d=%s' % next_day
            today_href = '/student/timetable?view=day'
            week_href = '/student/timetable?view=week'
        else:
            prev_href = f'/student/timetable?w={offset - 1}&view=week'
            next_href = f'/student/timetable?w={offset + 1}&view=week'
            today_href = '/student/timetable?view=week'
            week_href = '/student/timetable?view=week'

        return request.render('edu_portal.edu_timetable', {
            'title': title,
            'role': role,
            'view': view,
            'week_label': week_label,
            'week_no_label': week_no_label,
            'cur_w': offset,
            'prev_w': prev_href,
            'next_w': next_href,
            'week_href': week_href,
            'today_href': today_href,
            'day_flags': day_flags,
            'has_holiday': bool(holiday_map),
            'student': student,
            'is_faculty': bool(fac),
            'timings': timings,
            'days': DAY_NAMES,
            'matrix': matrix,
            'loose': loose,
            'ses_fmt': ses_fmt,
            'has_loose': has_loose,
            'has_sessions': bool(sessions),
            'page_name': 'timetable',
        })