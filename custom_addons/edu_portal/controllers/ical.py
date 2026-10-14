# -*- coding: utf-8 -*-
"""iCal 日历订阅 feed（/my/calendar/ics/<token>）。

参考 Moodle/Canvas 的 Calendar Feed：token 鉴权的公开 ics 端点，
用户在手机日历 / Google Calendar / Outlook 里订阅一次，课程、考试、
停课、校历活动自动同步（数据口径与校历页 _query_items 一致；
作业模型无截止日期字段，故不含作业事件，不编造数据）。
"""
import datetime

from odoo import http
from odoo.http import request

from odoo.addons.edu_schedule.models.identity import (
    faculty_of_user, parent_of_user, student_of_user)

PAST_DAYS = 14      # 回看窗口（天）
FUTURE_DAYS = 120   # 预告窗口（天）
_KIND_LABEL = {'session': '课程', 'exam': '考试',
               'holiday': '停课', 'event': '活动'}


def _esc(text):
    """RFC5545 文本转义（反斜杠/分号/逗号/换行）。

    先统一换行再转义：CRLF 与裸 CR 一律归一为 \n 字面量，否则 Outlook
    会把裸 CR 当成属性分隔，事件正文被截断。
    """
    out = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    return out.replace('\\', '\\\\').replace(';', '\\;') \
        .replace(',', '\\,').replace('\n', '\\n')


def _fold(line):
    """RFC5545 折行：内容行超 75 octet 时折行，续行以单个空格开头。

    按 UTF-8 字节计数但**不切断多字节字符**（中文课节名很容易越线）；
    续行首空格本身占 1 octet，故续行内容上限为 74。
    """
    if len(line.encode('utf-8')) <= 75:
        return line
    parts, cur, cur_len, limit = [], [], 0, 75
    for ch in line:
        size = len(ch.encode('utf-8'))
        if cur_len + size > limit:
            parts.append(''.join(cur))
            cur, cur_len, limit = [], 0, 74
        cur.append(ch)
        cur_len += size
    parts.append(''.join(cur))
    return '\r\n '.join(parts)


def _ics_dt(dt_utc_naive):
    return dt_utc_naive.strftime('%Y%m%dT%H%M%SZ')


def _scope_for(user):
    """按指定用户（token 反查）计算校历视角，逻辑同 calendar._role_scope。

    身份解析走公共 helper（双向并集，见 edu_schedule/models/identity.py）：
    只按 user_id 反查会让「账号由脚本新建」的订阅者静默落成 guest —— 订阅
    照样 200、日历却是空的（本缺陷家族最典型的静默失效）。
    """
    env = request.env
    uid = user.id
    student = student_of_user(env, uid)
    fac = faculty_of_user(env, uid)
    parent = parent_of_user(env, uid)
    batch_ids, course_ids = [], []
    if student:
        Scs = env['op.student.course'].sudo()
        scs = Scs.search([('student_id', '=', student.id),
                          ('state', '=', 'running')], limit=1) \
            or Scs.search([('student_id', '=', student.id)], limit=1)
        batch_ids = [scs.batch_id.id] if scs and scs.batch_id else []
        course_ids = [scs.course_id.id] if scs and scs.course_id else []
    elif parent:
        scs = env['op.student.course'].sudo().search(
            [('student_id', 'in', parent.student_ids.ids)])
        batch_ids = scs.mapped('batch_id').ids
        course_ids = scs.mapped('course_id').ids
    elif fac:
        batch_ids = env['op.session'].sudo().search(
            [('faculty_id', '=', fac.id)]).mapped('batch_id').ids
    role = ('student' if student else 'parent' if parent
            else 'faculty' if fac
            else 'admin' if user._is_admin() or user.has_group(
                'openeducat_core.group_op_back_office_admin')
            else 'staff' if user.has_group('base.group_user') else 'guest')
    return {
        'role': role,
        'batch_ids': batch_ids or [0],
        'course_ids': course_ids or [0],
        'faculty_id': fac.id if fac else None,
    }


class EduIcalFeed(http.Controller):

    @http.route('/my/calendar/ics/<token>', type='http', auth='public',
                methods=['GET'])
    def ical_feed(self, token, **kw):
        user = request.env['res.users'].sudo().search(
            [('edu_ical_token', '=', token)], limit=1)
        if not user:
            return request.not_found()
        env = request.env
        scope = _scope_for(user)
        now_utc = datetime.datetime.utcnow()
        win_start = now_utc - datetime.timedelta(days=PAST_DAYS)
        win_end = now_utc + datetime.timedelta(days=FUTURE_DAYS)
        role = scope['role']
        events_ics = []
        stamp = _ics_dt(now_utc)
        seq = 0

        def add(uid_prefix, start, end, title, desc='', all_day=None,
                location=''):
            nonlocal seq
            seq += 1
            lines = ['BEGIN:VEVENT',
                     'UID:%s-%d@edu.example.org' % (uid_prefix, seq),
                     'DTSTAMP:' + stamp]
            if all_day:
                lines.append('DTSTART;VALUE=DATE:' + all_day[0])
                lines.append('DTEND;VALUE=DATE:' + all_day[1])
            else:
                lines.append('DTSTART:' + _ics_dt(start))
                lines.append('DTEND:' + _ics_dt(end))
            lines.append('SUMMARY:' + _esc(title))
            if desc:
                lines.append('DESCRIPTION:' + _esc(desc))
            # 无链接/无地点时**省略整个字段**，绝不输出空 LOCATION
            if location:
                lines.append('LOCATION:' + _esc(location))
            lines.append('END:VEVENT')
            events_ics.append('\r\n'.join(_fold(x) for x in lines))

        if role not in ('guest',):
            # —— 课程（op.session：有明确起止时间的节次）——
            session_domain = [('state', '!=', 'cancel'),
                              ('start_datetime', '>=', win_start),
                              ('start_datetime', '<', win_end)]
            if role == 'faculty':
                session_domain.append(
                    ('faculty_id', '=', scope['faculty_id']))
            elif role in ('student', 'parent'):
                session_domain.append(('batch_id', 'in', scope['batch_ids']))
            if role in ('student', 'parent', 'faculty'):
                for ses in env['op.session'].sudo().search(
                        session_domain, order='start_datetime asc'):
                    end = ses.end_datetime or ses.start_datetime
                    if end < ses.start_datetime:
                        end = ses.start_datetime
                    # v3（t20）：课节级会议链接进日历。
                    # URL 取自 Odoo 原生 calendar.event.videocall_location
                    # （t6 已把链接落在该字段，不自建 URL 体系）。
                    # 无链接的课节：LOCATION 整个字段省略，不输出空串。
                    join_url = ses.meeting_url or ''
                    room = ' '.join(
                        x for x in [ses.batch_id.name or '',
                                    ses.classroom_id.name or ''] if x)
                    desc = room
                    if join_url:
                        desc = (desc + '\n入会链接：' + join_url).strip()
                    add('session', ses.start_datetime, end,
                        '[课程] %s' % (ses.subject_id.name
                                       or ses.course_id.name
                                       or ses.name or '上课'),
                        desc, location=join_url)
                # —— 考试 ——
                exam_domain = [('state', '!=', 'cancel'),
                               ('start_time', '>=', win_start),
                               ('start_time', '<', win_end)]
                if role in ('student', 'parent'):
                    exam_domain += ['|',
                                    ('batch_id', 'in', scope['batch_ids']),
                                    ('course_id', 'in', scope['course_ids'])]
                elif role == 'faculty':
                    exam_domain += ['|',
                                    ('batch_id', 'in', scope['batch_ids']),
                                    ('responsible_id', '=',
                                     scope['faculty_id'])]
                for ex in env['op.exam'].sudo().search(
                        exam_domain, order='start_time asc'):
                    end = ex.end_time or ex.start_time
                    add('exam', ex.start_time, end,
                        '[考试] %s' % (ex.name or ex.subject_id.name
                                       or '考试'),
                        ex.subject_id.name or '')
                # —— 作业截止 ——（op.assignment 无截止字段，暂无此事件源）

        # —— 校历活动（全角色可见口径）——
        event_domain = [('active', '=', True),
                        ('start_datetime', '>=', win_start),
                        ('start_datetime', '<', win_end)]
        if role in ('student', 'parent'):
            event_domain = ['|', ('batch_id', 'in', scope['batch_ids']),
                            ('batch_id', '=', False)] + event_domain
        for ev in env['edu.event'].sudo().search(
                event_domain, order='start_datetime asc'):
            end = ev.end_datetime or ev.start_datetime
            add('event', ev.start_datetime, end,
                '[活动] %s' % (ev.name or '活动'), ev.location or '',
                location=ev.location or '')

        # —— 停课日（全天事件；date_start/date_end 为本地日期）——
        holiday_domain = [('active', '=', True),
                          ('date_start', '<=', win_end.date()),
                          ('date_end', '>=', win_start.date())]
        if role in ('student', 'parent', 'faculty'):
            holiday_domain = ['|', ('batch_id', 'in', scope['batch_ids']),
                              ('batch_id', '=', False)] + holiday_domain
        for hd in env['edu.schedule.holiday'].sudo().search(holiday_domain):
            d0 = hd.date_start
            d1 = (hd.date_end or hd.date_start) + datetime.timedelta(days=1)
            add('holiday', None, None,
                '[停课] %s' % (hd.name or '停课'), '',
                all_day=(d0.strftime('%Y%m%d'), d1.strftime('%Y%m%d')))

        body = '\r\n'.join([
            'BEGIN:VCALENDAR',
            'VERSION:2.0',
            'PRODID:-//Yongyue Edu//Portal Calendar//CN',
            'CALSCALE:GREGORIAN',
            'X-WR-CALNAME:永约学坊·我的日历',
            'X-WR-TIMEZONE:Asia/Kuala_Lumpur',
        ] + events_ics + ['END:VCALENDAR', ''])
        return request.make_response(
            body.encode('utf-8'), headers=[
                ('Content-Type', 'text/calendar; charset=utf-8'),
                ('Content-Disposition',
                 'inline; filename="yongyue-calendar.ics"'),
                ('Cache-Control', 'no-store'),
            ])
