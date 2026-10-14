# -*- coding: utf-8 -*-
"""周次工具（S2 周期排课 / S3 整周复制 / S4 周课表门户共用，零后端状态）。

锚点口径（全站统一，见 docs/plans/ux-improve-proposal.md §S2/S4）：
- 以最近学期 term_start_date 所在自然周为「第 1 周」；
- 第 N 周 = (目标周一 - 学期起始周一).days // 7 + 1；
- 无学期数据时退化为以排课参考日所在周为第 1 周（自洽锚点，行为不依赖学期）。

周窗口：week_window_utc 为唯一实现（S4/S5 共用），本地周一 + 时区名 →
该自然周起止的 UTC naive（ORM 存 UTC naive，直接拿本地日期比较会让
周一凌晨的课串周；时区名由调用方经 request.env.user.tz 提供）。
"""
from datetime import datetime, timedelta

import pytz


def monday_of(day):
    """day 所在自然周的周一（本地日期）。"""
    return day - timedelta(days=day.weekday())


def week_no_of(day, anchor):
    """day 所在自然周在 anchor 锚点下的周次（>=1）；anchor 为空返回 None。"""
    if not anchor:
        return None
    return (monday_of(day) - monday_of(anchor)).days // 7 + 1


def week_window_utc(monday_local, tz_name='UTC'):
    """本地周一 naive → 该自然周起止的 UTC naive（唯一实现，S4/S5 共用）。

    tz_name：用户时区名（如 'Asia/Shanghai'），由调用方从 request 上下文取。
    """
    tz = pytz.timezone(tz_name or 'UTC')
    start = tz.localize(
        datetime(monday_local.year, monday_local.month, monday_local.day))
    end = start + timedelta(days=7)

    def to_utc(d):
        return d.astimezone(pytz.UTC).replace(tzinfo=None)

    return to_utc(start), to_utc(end)


def parse_week_ranges(spec):
    """'1,3-5,8-12' → 升序去重周次列表；空/None/非法 → None（=全部周）。

    语法与 EduScheduler formatWeeks 一致：逗号分隔单项，'a-b' 表示闭区间。
    """
    spec = (spec or '').strip()
    if not spec:
        return None
    weeks = set()
    for piece in spec.replace('，', ',').split(','):
        piece = piece.strip()
        if not piece:
            continue
        if '-' in piece:
            parts = piece.split('-', 1)
            try:
                lo, hi = int(parts[0]), int(parts[1])
            except (TypeError, ValueError):
                continue
            if 1 <= lo <= hi <= 60 and hi - lo <= 60:
                weeks.update(range(lo, hi + 1))
        elif piece.isdigit():
            n = int(piece)
            if 1 <= n <= 60:
                weeks.add(n)
    return sorted(weeks) if weeks else None


def week_in_ranges(week_no, ranges):
    """周次是否命中周次范围集合；ranges 为 None（未限定）恒 True。"""
    if not ranges:
        return True
    return week_no in ranges


def parity_ok(week_no, parity):
    """单双周判定：weekly=每周都排；odd=单周；even=双周；无周次视同每周。"""
    if not week_no or not parity or parity == 'weekly':
        return True
    return (week_no % 2 == 1) if parity == 'odd' else (week_no % 2 == 0)


def term_anchor(env, ref_date):
    """取 ref_date 所在（或最近）学期的 term_start_date；无学期返回 None。

    env：odoo.api.Environment——semester 属于行政数据，走 sudo 只读。
    """
    Term = env['op.academic.term'].sudo()
    term = Term.search([('term_start_date', '<=', ref_date),
                        ('term_end_date', '>=', ref_date)], limit=1) \
        or Term.search([('term_start_date', '<=', ref_date)],
                       order='term_start_date desc', limit=1) \
        or Term.search([], order='term_start_date asc', limit=1)
    return term.term_start_date if term else None