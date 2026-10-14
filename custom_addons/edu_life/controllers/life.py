# -*- coding: utf-8 -*-
"""灵命生活控制器。

路由清单（门户 auth='user' + website=True；写操作一律 POST+csrf，
sudo() 写库但归属强制取 current_student()，不信 POST 参数）：
- GET  /my/checkins                     学生打卡页：当月月历+一键打卡+计数
- POST /my/checkins/check               一键打卡（类型 id 来自表单）
- GET  /my/journals                     学生周记本：本周编辑提交+历史
- POST /my/journals/save                暂存草稿 / 提交周记（action 区分）
- GET  /journals/review                 教师待批队列（base.group_user）
- GET  /journals/review/<int:entry_id>  批阅详情页
- POST /journals/review/<int:entry_id>/grade   填评语并置已批阅

工程红线沿用 edu_portal：QWeb 模板内不出现 % 格式化表达式，
日期/状态文案一律在 Python 侧预格式化后传入模板。
"""
import calendar as _cal
import csv
import datetime
import io
import logging

from odoo import fields, http
from odoo.http import content_disposition, request

_logger = logging.getLogger(__name__)

# 月历表头（周一开头）
WEEKDAY_HEADERS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
STATE_LABELS = {'draft': '草稿', 'submitted': '已提交', 'reviewed': '已批阅'}
STATE_BADGES = {'draft': 'text-bg-secondary', 'submitted': 'text-bg-warning',
                'reviewed': 'text-bg-success'}


def _csv_download(filename, header, rows):
    """CSV 导出响应（utf-8-sig 防 Excel 乱码，中文名 RFC5987）。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow(['' if v is None else v for v in row])
    payload = '\ufeff' + buf.getvalue()
    return request.make_response(
        payload.encode('utf-8'),
        headers=[
            ('Content-Type', 'text/csv; charset=utf-8'),
            ('Content-Disposition', content_disposition(filename)),
        ])


def current_student():
    """当前登录用户对应的学生记录（无则 None）。"""
    return request.env['op.student'].sudo().search(
        [('user_id', '=', request.env.uid)], limit=1)


def current_faculty():
    """当前登录用户对应的教师记录（无则 None）。"""
    return request.env['op.faculty'].sudo().search(
        [('user_id', '=', request.env.uid)], limit=1)


def month_target(ctype, days_elapsed):
    """当月目标次数：daily=本月已过天数；weekly=周目标×已过整周数。"""
    if ctype.frequency == 'weekly':
        weeks_elapsed = max(1, -(-days_elapsed // 7))
        return ctype.weekly_target * weeks_elapsed
    return days_elapsed


def iso_week_key(day):
    """ISO 周次字符串，如 2026-W34。"""
    iso_year, iso_week = day.isocalendar()[:2]
    return '%04d-W%02d' % (iso_year, iso_week)


def fmt_dt(dt):
    return dt.strftime('%Y-%m-%d %H:%M') if dt else ''


def _streak_days(student_id, today):
    """连续打卡天数（门户 streak 展示用）。

    口径与主流习惯打卡应用一致：截至今天，只要当天打过任意一个类型
    即算该天有效；今天还没打卡时不清零，从昨天往前数（当天未打不算断）。
    """
    if not student_id:
        return 0
    since = today - datetime.timedelta(days=69)
    rows = request.env['edu.checkin.record'].sudo().search_read(
        [('student_id', '=', student_id),
         ('checkin_date', '>=', since)],
        fields=['checkin_date'])
    days = set()
    for row in rows:
        day = row.get('checkin_date')
        if isinstance(day, str):
            day = fields.Date.to_date(day)
        if day:
            days.add(day)
    cursor = today if today in days else today - datetime.timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= datetime.timedelta(days=1)
    return streak


def _month_grid(types, done_set, today):
    """当月月历数据：每周一行，每天一格，格内逐类型打勾状态。"""
    year, month = today.year, today.month
    days_in_month = _cal.monthrange(year, month)[1]
    month_start = datetime.date(year, month, 1)
    month_end = datetime.date(year, month, days_in_month)
    grid = []
    for week in _cal.monthcalendar(year, month):
        row = []
        for dnum in week:
            if dnum == 0:
                row.append({'blank': True, 'day': '', 'is_today': False,
                            'future': False, 'cells': []})
                continue
            day = datetime.date(year, month, dnum)
            cells = [{'type_label': t.label or t.name,
                      'icon': t.icon or 'fa-check-circle-o',
                      'done': (day, t.id) in done_set}
                     for t in types]
            row.append({'blank': False, 'day': str(dnum),
                        'is_today': day == today, 'future': day > today,
                        'cells': cells})
        grid.append(row)
    return grid, month_start, month_end


class EduLife(http.Controller):

    # ------------------------- 学生打卡门户 -------------------------

    def _checkin_page_values(self, **kw):
        student = current_student()
        if not student:
            return None
        env = request.env
        today = fields.Date.today()
        types = env['edu.checkin.type'].sudo().search(
            [('active', '=', True)], order='sequence, id')
        first_day = today.replace(day=1)
        days_in_month = _cal.monthrange(today.year, today.month)[1]
        month_end = today.replace(day=days_in_month)
        counts = env['edu.checkin.record'].sudo().month_counts(
            student.id, first_day, month_end)
        done_set = env['edu.checkin.record'].sudo().month_done_set(
            student.id, first_day, month_end)
        today_map = env['edu.checkin.record'].sudo().today_done_map(
            student.id, today)
        grid, _, _ = _month_grid(types, done_set, today)
        # 鼓励性微文案在 Python 侧预生成（QWeb 内不做逻辑/格式化）
        days_elapsed = today.day
        weeks_elapsed = max(1, -(-days_elapsed // 7))
        stat_cards = []
        for t in types:
            count = counts.get(t.id, 0)
            if t.frequency == 'weekly':
                target_total = (t.weekly_target or 0) * weeks_elapsed
                if count <= 0:
                    cheer = '本周目标 %d 次，记得安排上' % (t.weekly_target or 0)
                elif target_total and count >= target_total:
                    cheer = '阶段目标已达成，干得漂亮！'
                else:
                    cheer = '已完成 %d/%d 次，再接再厉' % (count, target_total)
            else:
                if count <= 0:
                    cheer = '本月还未开始，今天就是好起点'
                elif count >= days_elapsed:
                    cheer = '至今满勤，太棒了！'
                else:
                    pct = min(100, round(count * 100.0 / days_elapsed))
                    cheer = '本月已完成 %d%%，继续保持' % pct
            stat_cards.append({
                'id': t.id,
                'label': t.label or t.name,
                'icon': t.icon or 'fa-check-circle-o',
                'count': count,
                'is_weekly': t.frequency == 'weekly',
                'target': t.weekly_target,
                'deadline_name': t.deadline_display(),
                'cheer': cheer,
            })
        today_types = [{
            'id': t.id,
            'label': t.label or t.name,
            'icon': t.icon or 'fa-check-circle-o',
            'done': t.id in today_map,
        } for t in types if t.frequency == 'daily']
        today_total = len(today_types)
        today_done = sum(1 for tt in today_types if tt['done'])
        streak_days = _streak_days(student.id, today)
        if streak_days > 0:
            streak_text = '连续打卡 %d 天，继续保持！' % streak_days
        else:
            streak_text = '还没有连续纪录，今天打第一次卡开启它吧'
        return {
            'title': '灵命打卡',
            'page_name': 'edu_life_checkins',
            'student': student,
            'today': today,
            'month_label': '%d年%d月' % (today.year, today.month),
            'weekday_headers': WEEKDAY_HEADERS,
            'grid': grid,
            'stat_cards': stat_cards,
            'today_types': today_types,
            'today_done': today_done,
            'today_total': today_total,
            'today_progress_pct': (round(today_done * 100.0 / today_total)
                                   if today_total else 0),
            'streak_text': streak_text,
            'has_month_records': bool(done_set),
            'saved': kw.get('saved') == '1',
            'dup': kw.get('dup') == '1',
            'error': kw.get('error') == '1',
        }

    @http.route('/my/checkins', type='http', auth='user', website=True)
    def my_checkins(self, **kw):
        values = self._checkin_page_values(**kw)
        if values is None:
            return request.redirect('/my/home')
        return request.render('edu_life.edu_life_my_checkins', values)

    @http.route('/my/checkins/export', type='http', auth='user')
    def my_checkins_export(self, **kw):
        """本人灵命打卡记录 CSV 导出（全量）。"""
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        recs = request.env['edu.checkin.record'].sudo().search(
            [('student_id', '=', student.id)],
            order='checkin_date desc, id desc')
        rows = [[
            fields.Date.to_string(r.checkin_date) if r.checkin_date else '',
            r.type_id.label or r.type_id.name or '',
            (r.note or '').replace('\n', ' '),
        ] for r in recs]
        return _csv_download(
            '灵命打卡记录_%s.csv' % fields.Date.today().strftime('%Y%m%d'),
            ['日期', '打卡项目', '备注'],
            rows)

    @http.route('/my/checkins/check', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def my_checkins_check(self, **kw):
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        try:
            type_id = int(kw.get('type_id') or 0)
        except (TypeError, ValueError):
            type_id = 0
        ctype = request.env['edu.checkin.type'].sudo().browse(type_id)
        if not ctype.exists() or not ctype.active:
            return request.redirect('/my/checkins?error=1')
        Record = request.env['edu.checkin.record'].sudo()
        today = fields.Date.today()
        if Record.search_count([('student_id', '=', student.id),
                                ('type_id', '=', ctype.id),
                                ('checkin_date', '=', today)]):
            # 已打过：幂等返回成功提示
            return request.redirect('/my/checkins?dup=1')
        try:
            Record.create({'student_id': student.id,
                           'type_id': ctype.id,
                           'checkin_date': today})
        except Exception:
            return request.redirect('/my/checkins?error=1')
        return request.redirect('/my/checkins?saved=1')

    # ------------------------- 学生周记本 -------------------------

    @http.route('/my/journals', type='http', auth='user', website=True)
    def my_journals(self, **kw):
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        env = request.env
        Journal = env['edu.journal.entry'].sudo()
        today = fields.Date.today()
        week_key = iso_week_key(today)
        entry = Journal.search([('student_id', '=', student.id),
                                ('week', '=', week_key)], limit=1)
        can_edit = bool(not entry or entry.state == 'draft')
        # 本周三态提示文案（草稿可编辑 / 已提交待批阅 / 已批阅含评语）
        # 2026-10-03：原先写的是 `if entry is None` —— **Odoo 的 search() 返回空记录集、不是 None**，
        # 所以「本周还没动笔」这一支**永远进不去**，没写周记的学生会被走到下面的 else，
        # 看到「老师已批阅，评语在正文之后」—— 而他一篇都没写（实测：学生 5 有 W34/35/36/37/39，
        # 今天是 W40，无 W40 记录，页面却报「已批阅」，旁边表单还写着「已写 0 字」）。
        # ⇒ 改用 Odoo 惯用的假值判断（空记录集为假；同函数上一行 `not entry` 本来就是对写法）。
        if not entry:
            week_hint_text = '本周还没动笔，花十分钟写下这一周的感悟吧。'
            week_hint_style = 'light'
        elif entry.state == 'draft':
            week_hint_text = '草稿仅自己可见；完善后点「提交周记」，老师就能看到。'
            week_hint_style = 'info'
        elif entry.state == 'submitted':
            week_hint_text = '周记已提交，等待老师批阅；批阅前不能再修改。'
            week_hint_style = 'warning'
        else:
            week_hint_text = '老师已批阅，评语在正文之后，别忘了查看。'
            week_hint_style = 'success'
        all_rows = []
        for rec in Journal.search([('student_id', '=', student.id)],
                                  order='week desc'):
            feedback = rec.feedback or ''
            all_rows.append({
                'week': rec.week,
                'title': rec.title or '（无标题）',
                'state': rec.state,
                'state_label': STATE_LABELS.get(rec.state, rec.state),
                'badge': STATE_BADGES.get(rec.state, 'text-bg-secondary'),
                'has_feedback': bool(feedback),
                'feedback_short': feedback[:50] + ('…' if len(feedback) > 50 else ''),
                'reviewer': rec.reviewer_id.name or '',
                'when': fmt_dt(rec.write_date),
            })
        # 历史列表状态筛选（?state=xxx，可选；默认全部）
        state_filter = kw.get('state') if kw.get('state') in STATE_LABELS else ''
        state_counts = {'draft': 0, 'submitted': 0, 'reviewed': 0}
        for row in all_rows:
            if row['state'] in state_counts:
                state_counts[row['state']] += 1
        history = [row for row in all_rows
                   if not state_filter or row['state'] == state_filter]
        return request.render('edu_life.edu_life_my_journals', {
            'title': '我的周记',
            'page_name': 'edu_life_journals',
            'student': student,
            'week_key': week_key,
            'entry': entry,
            # 注意：不能叫 editable，会被 website 前端渲染上下文的同名变量覆盖
            'can_edit': can_edit,
            'week_hint_text': week_hint_text,
            'week_hint_style': week_hint_style,
            'history': history,
            'all_count': len(all_rows),
            'state_counts': state_counts,
            'state_filter': state_filter,
            'saved': kw.get('saved') == '1',
            'submitted': kw.get('submitted') == '1',
            'error': kw.get('error') == '1',
        })

    @http.route('/my/journals/save', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def my_journals_save(self, **kw):
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        action = kw.get('action') if kw.get('action') in (
            'draft', 'submit') else 'submit'
        title = (kw.get('title') or '').strip()[:200]
        content = (kw.get('content') or '').strip()
        if action == 'submit' and (not title or not content):
            return request.redirect('/my/journals?error=1')
        week_key = iso_week_key(fields.Date.today())
        Journal = request.env['edu.journal.entry'].sudo()
        rec = Journal.search([('student_id', '=', student.id),
                              ('week', '=', week_key)], limit=1)
        if rec and rec.state != 'draft':
            # 已提交/已批阅的周记不允许再改
            return request.redirect('/my/journals?error=locked')
        vals = {'title': title, 'content': content}
        if action == 'submit':
            vals['state'] = 'submitted'
        if rec:
            rec.write(vals)
        else:
            Journal.create({'student_id': student.id,
                            'week': week_key,
                            **vals})
        flag = 'submitted=1' if action == 'submit' else 'saved=1'
        return request.redirect('/my/journals?' + flag)

    # ------------------------- 教师批阅端 -------------------------

    def _require_teacher(self):
        """内部用户（教师）才可进入批阅端；其余回门户首页。"""
        return request.env.user.has_group('base.group_user')

    @http.route('/journals/review', type='http', auth='user', website=True)
    def journals_review(self, **kw):
        if not self._require_teacher():
            return request.redirect('/my/home')
        Journal = request.env['edu.journal.entry'].sudo()

        def row(rec):
            return {
                'id': rec.id,
                'student': rec.student_id.name or '-',
                'week': rec.week,
                'title': rec.title or '（无标题）',
                'when': fmt_dt(rec.write_date),
                'href': '/journals/review/%d' % rec.id,
            }

        pending = [row(r) for r in Journal.search(
            [('state', '=', 'submitted')], order='write_date asc')]
        reviewed = [row(r) for r in Journal.search(
            [('state', '=', 'reviewed')], order='write_date desc',
            limit=20)]
        return request.render('edu_life.edu_life_review_queue', {
            'title': '周记批阅',
            'page_name': 'edu_life_review_queue',
            'pending': pending,
            'reviewed': reviewed,
        })

    @http.route('/journals/review/<int:entry_id>', type='http',
                auth='user', website=True)
    def journals_review_detail(self, entry_id, **kw):
        if not self._require_teacher():
            return request.redirect('/my/home')
        entry = request.env['edu.journal.entry'].sudo().browse(entry_id)
        if not entry.exists():
            return request.redirect('/journals/review')
        return request.render('edu_life.edu_life_review_detail', {
            'title': '批阅周记 · %s' % (entry.student_id.name or ''),
            'page_name': 'edu_life_review_detail',
            'entry': entry,
            'student_name': entry.student_id.name or '-',
            'state_label': STATE_LABELS.get(entry.state, entry.state),
            'badge': STATE_BADGES.get(entry.state, 'text-bg-secondary'),
            'when': fmt_dt(entry.write_date),
            'reviewer_name': entry.reviewer_id.name or '',
            'grade_href': '/journals/review/%d/grade' % entry.id,
            'can_grade': entry.state == 'submitted',
            'reviewed_ok': kw.get('reviewed') == '1',
        })

    @http.route('/journals/review/<int:entry_id>/grade', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def journals_review_grade(self, entry_id, **kw):
        if not self._require_teacher():
            return request.redirect('/my/home')
        entry = request.env['edu.journal.entry'].sudo().browse(entry_id)
        if not entry.exists() or entry.state != 'submitted':
            return request.redirect('/journals/review')
        entry.write({
            'feedback': (kw.get('feedback') or '').strip(),
            'reviewer_id': request.env.uid,
            'state': 'reviewed',
        })
        # 批阅提醒：带偏好过滤的站内信（edu.message 属 edu_portal；未装则跳过）
        suser = entry.student_id.user_id
        if suser and suser.id != request.env.uid:
            try:
                request.env['edu.message']._notify_event(
                    'journal_reviewed', suser,
                    '【周记批阅】您的周记《%s》已批阅，快去看看老师的评语吧。'
                    % (entry.title or '无标题'))
            except Exception:
                _logger.warning('journal %s notify student failed',
                                entry.id, exc_info=True)
        return request.redirect('/journals/review/%d?reviewed=1' % entry.id)

    # ------------------------- 教师打卡统计 -------------------------

    @http.route('/checkins/stats', type='http', auth='user',
                website=True)
    def checkin_stats(self, **kw):
        fac = current_faculty()
        if not fac:
            # 学生回自己的打卡页；其余内部用户回门户首页
            if current_student():
                return request.redirect('/my/checkins', code=303)
            return request.redirect('/my/home', code=303)
        env = request.env
        today = fields.Date.today()
        days_elapsed = today.day
        types = env['edu.checkin.type'].sudo().search(
            [('active', '=', True)], order='sequence, id')
        Course = env['op.student.course'].sudo()
        Record = env['edu.checkin.record'].sudo()
        month_start = today.replace(day=1)
        month_end = today.replace(day=_cal.monthrange(
            today.year, today.month)[1])

        # 班级分组：按学生课程表的 batch 归组（与教务数据保持一致）
        courses = Course.search([('batch_id', '!=', False)])
        groups = {}
        seen_students = set()
        for sc in courses:
            stu = sc.student_id
            if not stu or stu.id in seen_students:
                continue
            seen_students.add(stu.id)
            groups.setdefault(sc.batch_id.id, {
                'name': sc.batch_id.name,
                'students': [],
            })
            groups[sc.batch_id.id]['students'].append(stu)
        # 尚无任何课程/班级归属的学生兜底归入「未分班」
        orphan_domain = ([('id', 'not in', list(seen_students))]
                         if seen_students else [])
        orphans = env['op.student'].sudo().search(
            orphan_domain, order='name')
        if orphans:
            groups.setdefault(0, {'name': '未分班', 'students': []})
            groups[0]['students'].extend(orphans)

        group_cards = []
        for key in sorted(groups.keys(), key=lambda k: (k == 0, k)):
            grp = groups[key]
            rows = []
            for stu in grp['students']:
                recs = Record.search([
                    ('student_id', '=', stu.id),
                    ('checkin_date', '>=', month_start),
                    ('checkin_date', '<=', month_end),
                ])
                counts, lasts = {}, {}
                for rec in recs:
                    tid = rec.type_id.id
                    counts[tid] = counts.get(tid, 0) + 1
                    day = rec.checkin_date
                    lasts[tid] = day if lasts.get(tid) is None \
                        else max(lasts[tid], day)
                cells, rates = [], []
                for t in types:
                    target = month_target(t, days_elapsed)
                    count = counts.get(t.id, 0)
                    rate = min(100, round(count * 100.0 / target)) \
                        if target else 0
                    rates.append(rate)
                    cells.append({
                        'label': t.label or t.name,
                        'icon': t.icon or 'fa-check-circle-o',
                        'text': '%d/%d · %d%%' % (count, target, rate),
                        'count': count,
                        'done': bool(target) and count >= target,
                    })
                avg_rate = round(sum(rates) / len(rates)) if rates else 0
                last_all = max(lasts.values()) if lasts else None
                rows.append({
                    'student_id': stu.id,
                    'student_name': stu.name or '-',
                    'cells': cells,
                    'avg_rate': avg_rate,
                    'rate_text': '%d%%' % avg_rate,
                    'last_date': str(last_all) if last_all else '—',
                })
            # 升序：完成率最低的排最前，最需要关注
            rows.sort(key=lambda r: (r['avg_rate'], r['student_name']))
            group_cards.append({
                'name': grp['name'],
                'rows': rows,
                'type_headers': [{
                    'label': t.label or t.name,
                    'icon': t.icon or 'fa-check-circle-o',
                } for t in types],
            })
        # 零数据引导：有类型但一条打卡都没有 / 完全没有可统计的学生
        total_students = sum(len(g['rows']) for g in group_cards)
        has_any_records = any(cell['count'] > 0
                              for g in group_cards
                              for r in g['rows']
                              for cell in r['cells'])
        return request.render('edu_life.edu_life_checkin_stats', {
            'title': '打卡统计',
            'page_name': 'edu_life_checkin_stats',
            'faculty': fac,
            'month_label': '%d年%d月' % (today.year, today.month),
            'days_elapsed': days_elapsed,
            'groups': group_cards,
            'has_types': bool(types),
            'total_students': total_students,
            'has_any_records': has_any_records,
        })

    @http.route('/checkins/stats/export', type='http', auth='user')
    def checkin_stats_export(self, **kw):
        """打卡统计 CSV 导出（教师，当月按班按生，与统计页同口径）。"""
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home', code=303)
        env = request.env
        today = fields.Date.today()
        days_elapsed = today.day
        types = env['edu.checkin.type'].sudo().search(
            [('active', '=', True)], order='sequence, id')
        Course = env['op.student.course'].sudo()
        Record = env['edu.checkin.record'].sudo()
        month_start = today.replace(day=1)
        month_end = today.replace(day=_cal.monthrange(
            today.year, today.month)[1])
        courses = Course.search([('batch_id', '!=', False)])
        groups, seen = {}, set()
        for sc in courses:
            stu = sc.student_id
            if not stu or stu.id in seen:
                continue
            seen.add(stu.id)
            groups.setdefault(sc.batch_id.id,
                              {'name': sc.batch_id.name, 'students': []})
            groups[sc.batch_id.id]['students'].append(stu)
        orphans = env['op.student'].sudo().search(
            [('id', 'not in', list(seen))] if seen else [], order='name')
        if orphans:
            groups.setdefault(0, {'name': '未分班', 'students': []})
            groups[0]['students'].extend(orphans)
        header = ['班级', '学生', '平均完成率', '最近打卡']
        header += ['%s(次/目标)' % (t.label or t.name) for t in types]
        rows = []
        for key in sorted(groups.keys(), key=lambda k: (k == 0, k)):
            grp = groups[key]
            for stu in grp['students']:
                recs = Record.search([
                    ('student_id', '=', stu.id),
                    ('checkin_date', '>=', month_start),
                    ('checkin_date', '<=', month_end),
                ])
                counts, lasts = {}, {}
                for rec in recs:
                    tid = rec.type_id.id
                    counts[tid] = counts.get(tid, 0) + 1
                    day = rec.checkin_date
                    lasts[tid] = day if lasts.get(tid) is None \
                        else max(lasts[tid], day)
                cells, rates = [], []
                for t in types:
                    target = month_target(t, days_elapsed)
                    count = counts.get(t.id, 0)
                    rate = min(100, round(count * 100.0 / target)) \
                        if target else 0
                    rates.append(rate)
                    cells.append('%d/%d' % (count, target))
                avg_rate = round(sum(rates) / len(rates)) if rates else 0
                last_all = max(lasts.values()) if lasts else None
                rows.append([grp['name'], stu.name or '-', '%d%%' % avg_rate,
                             str(last_all) if last_all else ''] + cells)
        return _csv_download(
            '打卡统计_%s.csv' % fields.Date.today().strftime('%Y%m%d'),
            header, rows)
