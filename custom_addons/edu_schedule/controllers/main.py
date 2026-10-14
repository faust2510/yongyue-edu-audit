# -*- coding: utf-8 -*-
"""排课工具控制器（仅内部用户；门户学生一律 303 回 /my/home）。

路由清单：
- GET  /timetable/bulk         周期排课表单
- POST /timetable/bulk/preview 预览将生成的课节（不落库）
- POST /timetable/bulk/create  确认生成（循环建 op.session）

S2（周次范围 / 单双周 + 周矩阵预览）与 S3（复制预览 + 逐条明细）：
- 周次锚点口径全站统一（edu_schedule/models/week_utils.py）：
  学期 term_start_date 所在周为第 1 周；无学期退化以起始日所在周为第 1 周；
- 原参数完全兼容：不填周次范围 + 每周 时行为与旧版一致（零功能丢失）；
- 预览红格/灰格仅为提示，创建与复制仍走服务端四查兜底。

约定沿用 openeducat_timetable 自带向导：
本地时区(用户 tz)构造时刻 -> 转 UTC naive 入库；
批量创建时按班级注册学生预取一次写入 student_ids。
"""
import datetime
from urllib.parse import quote as url_quote, urlencode

import pytz

from odoo import fields, http
from odoo.http import request

from odoo.addons.edu_schedule.models.week_utils import (
    monday_of, parse_week_ranges, parity_ok, term_anchor,
    week_in_ranges, week_no_of,
)

WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
_PARITY_LABEL = {'weekly': '每周', 'odd': '单周', 'even': '双周'}


def _batch_sort_key(batch):
    """班级排序键：GB2312 编码序 = 拼音序（只用内置编码，零第三方依赖）。

    GB2312 一级汉字本就按拼音排列，故 name.encode('gb2312') 后逐字节比较
    即得拼音序；ASCII 字母 < 0x80，天然排在汉字前面，班名混中英文也稳定。
    编码外字符经 errors='replace' 退化成 '?'，只求可比、不求可读。
    """
    name = (batch.name or '')
    return (name.encode('gb2312', errors='replace'),
            (batch.code or ''), batch.id)


def _upcoming_holidays(limit=8):
    """未来停课日（含今天），供表单页提示。"""
    today = datetime.date.today()
    return request.env['edu.schedule.holiday'].sudo().search(
        [('active', '=', True), ('date_end', '>=', today)],
        order='date_start asc', limit=limit)


def require_internal():
    """内部用户闸门：门户学生等一律 303 回 /my/home。"""
    return request.env.user.has_group('base.group_user')


def privileged_staff():
    """管理员/教务处 = 最高权限（口径同 edu_portal.controllers.roles）。

    本模块不能 import edu_portal（edu_portal 依赖 edu_schedule，反向会成环），
    故按同一判据就地复用：教务组 / 系统组。
    """
    u = request.env.user
    return (u.has_group('openeducat_core.group_op_back_office_admin')
            or u.has_group('base.group_system'))


def _as_int(raw):
    """查询串数字容错：非数字/缺失一律 0（不因 URL 参数 500）。"""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def local_to_utc(naive_dt):
    """用户时区墙钟 -> UTC naive（入库口径）。"""
    tz = pytz.timezone(request.env.user.partner_id.tz or 'GMT')
    return tz.localize(naive_dt, is_dst=None).astimezone(pytz.utc) \
        .replace(tzinfo=None)


def utc_to_local(naive_dt):
    """UTC naive -> 用户时区 naive（展示口径，与门户课表一致）。"""
    if not naive_dt:
        return None
    tz = pytz.timezone(request.env.user.partner_id.tz or 'GMT')
    return naive_dt.replace(tzinfo=pytz.utc).astimezone(tz) \
        .replace(tzinfo=None)


def timing_span(timing):
    """op.timing -> (起始分钟, 结束分钟)；duration 空 默认 1 小时。"""
    hour = int(timing.hour) % 12 + (12 if timing.am_pm == 'pm' else 0)
    begin = hour * 60 + int(timing.minute)
    finish = begin + int(round((timing.duration or 1.0) * 60))
    return begin, finish


def fmt_minutes(m):
    return '%02d:%02d' % divmod(m, 60)


def parse_date(raw):
    try:
        return fields.Date.to_date(raw)
    except Exception:
        return None


class EduScheduleTool(http.Controller):

    # ------------------------- 公共 -------------------------

    def _form_options(self):
        # 注意 Odoo19 的 sudo() 在 recordset 上而非 Environment 上
        return {
            'courses': request.env['op.course'].sudo().search([]),
            # 班级统一按 _batch_sort_key（拼音/字母序）排，与 _batch_rows 同口径
            'batches': request.env['op.batch'].sudo().search([]).sorted(
                _batch_sort_key),
            'subjects': request.env['op.subject'].sudo().search([]),
            'faculties': request.env['op.faculty'].sudo().search([]),
            'timings': request.env['op.timing'].sudo().search([]),
            'classrooms': request.env['op.classroom'].sudo().search([]),
            'weekdays': WEEKDAY_NAMES,
        }

    # ------------------------------------------------------------ 表单回填（①②）
    # 2026-10-04 修一簇同根因缺陷：**填表页从不读回已填值**。实测（backoffice@local）：
    #   ① 服务端校验失败（如没勾星期几）=> course_id/batch_id/subject_id/faculty_id/
    #      timing_id/start_date/end_date/week_ranges **8 项全空**，用户白填一遍；
    #   ② 预览页点「返回修改」=> href 写死 /timetable/bulk => 同样是空白表单。
    # 两条路都只是「没有读回来」，所以修法也是同一处：读回 + 回填。
    #
    # 与 views/templates.xml 里 <form action="/timetable/bulk/preview"> 的 name= 一一对应。
    # **新增表单字段时必须同步这里**，否则该字段仍然「填了就没」。
    _FORM_FIELDS = ('course_id', 'batch_id', 'subject_id', 'faculty_id',
                    'timing_id', 'classroom_id', 'new_course_name',
                    'new_subject_name', 'custom_begin', 'custom_end',
                    'start_date', 'end_date', 'week_ranges', 'parity',
                    'stagger_minutes')

    def _submitted(self, name):
        """取用户填过的值：POST 表单优先，取不到再取 query（GET）。

        两条路都要读，因为它们本来就是同一件事的两个入口：
          · 服务端校验失败是 POST，回显读 request.form；
          · 预览页「返回修改」是 GET，回显读 request.args。
        """
        http_req = request.httprequest
        vals = http_req.form.getlist(name) or http_req.args.getlist(name)
        return [v for v in vals if v is not None]

    def _form_echo(self):
        """归一化成模板可直接绑定的 dict（回填的唯一口径，模板不再各自解释参数）。"""
        echo = {}
        for key in self._FORM_FIELDS:
            vals = self._submitted(key)
            echo[key] = vals[-1] if vals else ''
        echo['weekdays'] = [v for v in self._submitted('weekday') if str(v).strip()]
        echo['batch_ids'] = [v for v in self._submitted('batch_ids') if str(v).strip()]
        return echo

    def _bulk_back_url(self, echo=None):
        """「返回修改」的地址：把已填值放进 query，表单页再从 query 读回来（②）。

        为什么不改成 POST 回跳：这是导航按钮，GET 才符合浏览器语义（可后退、可收藏）；
        而「表单页读 query」本来就该支持（见 _submitted）。
        """
        echo = echo if echo is not None else self._form_echo()
        pairs = [(k, echo[k]) for k in self._FORM_FIELDS if echo.get(k)]
        pairs += [('weekday', d) for d in (echo.get('weekdays') or [])]
        pairs += [('batch_ids', b) for b in (echo.get('batch_ids') or [])]
        return '/timetable/bulk' + ('?' + urlencode(pairs) if pairs else '')

    def _batch_priority_notice(self):
        """④ 「勾了多班」会盖掉「单班」——**既有契约不改**，但必须让用户看见。

        _resolve_batch_ids() 只读 batch_ids、从不读 batch_id（既有语义，本次不动）；
        于是用户上面选了一个班、下面又勾了一个班时，上面那个被**无声忽略**。
        这里只负责把这件事说出来（判据与取数同源：单班有值 + 勾选非空 + 单班不在勾选里）。
        """
        single = (self._submitted('batch_id') or [''])[-1].strip()
        picked = [v for v in self._submitted('batch_ids') if str(v).strip()]
        if not (single and picked) or single in picked:
            return ''
        return ('您同时选了上面「班级（单班）」和下面勾选的班级：按既有规则以勾选的为准，'
                '上面选的那个班本次不会排课。要排它请把它也勾上，或取消其余勾选。')

    def _render_bulk(self, values):
        values.update(self._form_options())
        # ①② 回填：错误页与「返回修改」都落到这里，必须带着用户已填的内容
        values.setdefault('form', self._form_echo())
        values.setdefault('notice', self._batch_priority_notice())
        values.setdefault('title', '周期排课')
        values.setdefault('page_name', 'edu_schedule_bulk')
        # 2026-10-05：服务端分流「批量停用」工具页（`?tool=deactivate`）。
        # 为什么用服务端而不是客户端 Tab：客户端 Tab 仍把 17 行停用表留在 DOM 里，
        # 窄屏上那 4113px（整页 7168px 的 57%）照样要滚 —— 搬走 DOM 才叫搬走。
        # 三份独立设计（A/B/C）都要求「停用必须离开默认视图」，此处取 C 的方案（+2 行，不新增菜单）。
        values.setdefault('tool', '')
        return request.render('edu_schedule.edu_schedule_bulk', values)

    def _batch_rows(self):
        """工具页「批量停用」卡片的数据（§18 能力 B）。

        每行 = 一个启用班级 + 在用/已停用课时数 + 合班批组成推导。
        批名/代号**自己编码了组成**（B1234 的批名就是「B1-B4全体」），
        但推导 != 事实 ⇒ 页面上必须显式标注「推导，需人工确认」，
        绝不能静默套用（设计稿 §18.5）。
        """
        # 排序口径与 _form_options 的 batches 完全一致：SQL order 无法表达
        # GB2312 字节序（库排序规则不等价），故取回后在 Python 侧排。
        batches = request.env['op.batch'].sudo().search(
            [('active', '=', True)]).sorted(_batch_sort_key)
        live, stopped = {}, {}
        for ses in request.env['op.session'].sudo().search(
                [('batch_id', '!=', False)]):
            bid = ses.batch_id.id
            bucket = stopped if ses.state == 'cancel' else live
            bucket[bid] = bucket.get(bid, 0) + 1
        rows = []
        for bch in batches:
            comp = bch._deactivate_composition()
            rows.append({
                'batch': bch,
                'live_count': live.get(bch.id, 0),
                'cancel_count': stopped.get(bch.id, 0),
                'is_combined': comp['is_combined'],
                'parts_label': comp['parts_label'],
                'unknown_label': '、'.join(comp['unknown']),
                'href': '/timetable/batch/%d/deactivate' % bch.id,
            })
        return rows

    def _resolve_timing(self, params):
        """自定义起止时间(HH:MM)优先；否则用节次下拉。
        op.timing 的分钟只有一刻钟档位，自由时间按最近一刻钟对齐。"""
        Timing = request.env['op.timing'].sudo()
        raw_b = (params.get('custom_begin') or '').strip()
        raw_e = (params.get('custom_end') or '').strip()
        if not raw_b and not raw_e:
            return Timing.browse(int(params.get('timing_id') or 0)), None

        def minutes(raw, label):
            try:
                hh, mm = raw.split(':')
                m = int(hh) * 60 + int(mm)
                if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                    raise ValueError
                return m
            except Exception:
                return None
        begin = minutes(raw_b, '开始')
        finish = minutes(raw_e, '结束')
        if begin is None or finish is None:
            return Timing, '请按 HH:MM 填写自定义时间。'
        if begin >= finish:
            return Timing, '结束时间必须晚于开始时间。'
        # 一刻钟对齐
        begin = begin // 15 * 15 + (15 if begin % 15 >= 8 else 0)
        finish = finish // 15 * 15 + (15 if finish % 15 >= 8 else 0)
        duration = round((finish - begin) / 60.0 * 4) / 4
        bh, bm = divmod(begin, 60)
        eh, em = divmod(finish, 60)
        hour = str(bh % 12 or 12)
        minute = '%02d' % bm
        am_pm = 'pm' if bh >= 12 else 'am'
        timing = Timing.search([
            ('hour', '=', hour), ('minute', '=', minute),
            ('am_pm', '=', am_pm), ('duration', '=', duration)], limit=1)
        if not timing:
            timing = Timing.create({
                'name': ('%s-%s' % (fmt_minutes(begin),
                                    fmt_minutes(finish)))[:16],
                'hour': hour, 'minute': minute, 'am_pm': am_pm,
                'duration': duration, 'sequence': begin,
            })
        return timing, None

    def _resolve_course_subject(self, params):
        """「或新建」文本框：填了名字就直接建档，免去先去后台建课程/科目。"""
        Course = request.env['op.course'].sudo()
        Subject = request.env['op.subject'].sudo()
        course = Course.browse(int(params.get('course_id') or 0))
        subject = Subject.browse(int(params.get('subject_id') or 0))
        new_course = (params.get('new_course_name') or '').strip()
        new_subject = (params.get('new_subject_name') or '').strip()
        err = None
        if not course.exists() and new_course:
            course = Course.create({'name': new_course,
                                    'code': new_course[:16]})
        if not subject.exists() and new_subject:
            subject = Subject.create({'name': new_subject,
                                      'code': new_subject[:16]})
        return course, subject, err

    # ------------------- S2/S3 周矩阵与冲突预检工具 -------------------

    def _occupied_map(self, start, end):
        """[start-1d, end+1d] 既有课时（非取消）→ 本地日期 → 占用槽列表。

        [(utc_start_naive, utc_end_naive, faculty_id, classroom_id, batch_id)]，
        供周期排课/复制预览做冲突红格。重叠判定在 UTC 轴（与上游四查一致），
        预览用的「将建的课节」也是按用户时区墙钟转 UTC 入库，同轴可比。
        """
        lo = local_to_utc(datetime.datetime.combine(
            start - datetime.timedelta(days=1), datetime.time.min))
        hi = local_to_utc(datetime.datetime.combine(
            end + datetime.timedelta(days=1), datetime.time.min))
        sesses = request.env['op.session'].sudo().search([
            ('state', '!=', 'cancel'),
            ('start_datetime', '>=', lo.strftime('%Y-%m-%d %H:%M:%S')),
            ('start_datetime', '<', hi.strftime('%Y-%m-%d %H:%M:%S')),
        ])
        out = {}
        for s in sesses:
            loc_s = utc_to_local(s.start_datetime)
            if not loc_s or not s.end_datetime:
                continue
            out.setdefault(loc_s.date(), []).append((
                s.start_datetime, s.end_datetime,
                s.faculty_id.id or 0, s.classroom_id.id or 0,
                s.batch_id.id or 0, s.subject_id.id or 0))
        return out

    def _slot_conflict_dims(self, day, begin, finish, faculty, classroom,
                            batch, subject, occupied):
        """该 (本地日期, 时段) 在哪些维度撞既有课时（**唯一冲突判据**）。

        返回 ['faculty', 'classroom', 'batch_subject', 'batch'] 的子集，
        顺序 = 定级顺序，与 C-1 的 _impact_overlap_dims / conflict_kind 同口径；
        非空 ⇔ 冲突。begin/finish 为本地分钟；先把墙钟转成 UTC naive
        再与既有课时同轴比较（重叠判定全在 UTC 轴，与上游四查一致）。

        ⚠ 本方法是本模块**唯一**的重叠判定实现：旧 _slot_conflicted 现在是
        它的薄封装（bool(非空)），「多班批量排课」的硬预检也走它 ——
        不写第二套判据（设计稿 §18.3「不要另造提示体系」）。
        """
        if not batch.exists():
            return []
        dims = []
        fac_id = faculty.id if faculty.exists() else 0
        room_id = classroom.id if classroom.exists() else 0
        sub_id = subject.id if (subject is not None and subject.exists()) else 0
        bch_id = batch.id
        u_begin = local_to_utc(datetime.datetime.combine(
            day, datetime.time(hour=begin // 60, minute=begin % 60)))
        u_finish = local_to_utc(datetime.datetime.combine(
            day, datetime.time(hour=finish // 60, minute=finish % 60)))
        for (us, ue, of, orm, ob, osb) in occupied.get(day, []):
            if not (us < u_finish and u_begin < ue):
                continue
            if fac_id and of == fac_id and 'faculty' not in dims:
                dims.append('faculty')
            if room_id and orm == room_id and 'classroom' not in dims:
                dims.append('classroom')
            if ob == bch_id:
                if sub_id and osb == sub_id and 'batch_subject' not in dims:
                    dims.append('batch_subject')
                if 'batch' not in dims:
                    dims.append('batch')
        return dims

    def _slot_conflicted(self, day, begin, finish, faculty, classroom,
                         batch, occupied, subject=None):
        """该 (本地日期, 时段) 与既有课时在教师/教室/班级任一维度是否冲突。

        薄封装（保持既有签名与语义不变）；subject 只影响「班级+科目」这一档的
        细分标签，不影响"是否冲突"的布尔结论。
        """
        return bool(self._slot_conflict_dims(
            day, begin, finish, faculty, classroom, batch, subject, occupied))


    def _term_anchor_info(self, ref_date):
        """取锚点学期（含名称）；无学期返回 (None, '')。"""
        Term = request.env['op.academic.term'].sudo()
        term = Term.search([('term_start_date', '<=', ref_date),
                            ('term_end_date', '>=', ref_date)], limit=1) \
            or Term.search([('term_start_date', '<=', ref_date)],
                           order='term_start_date desc', limit=1) \
            or Term.search([], order='term_start_date asc', limit=1)
        if not term:
            return None, ''
        return term.term_start_date, '%s（%s 起）' % (
            term.name, term.term_start_date)

    def _switch_flags(self):
        """四查开关（**复用 session_ext._impact_flags**，不写第二份）。

        与基座 check_timetable_fields 同源：读同四个 ir.config_parameter，
        判真值口径也照抄（基座判的是字符串真值，'False' 亦为真）。
        硬预检必须与基座同构，否则会拒掉基座本来允许的排课。
        """
        return request.env['op.session']._impact_flags()

    def _plan_ctx(self, params, batches):
        """排课计划的公共前置解析（单班 / 多班共用）。返回 (ctx, error)。

        batches = 本次要排的班级（有序 recordset）；校验顺序与旧版逐条一致
        （课程 → 班级 → 科目 → 教师 → 节次 → 日期 → 星期 → 跨度）。
        """
        course, subject, cs_err = self._resolve_course_subject(params)
        if cs_err:
            return None, cs_err
        timing, t_err = self._resolve_timing(params)
        if t_err:
            return None, t_err
        faculty = request.env['op.faculty'].sudo().browse(
            int(params.get('faculty_id') or 0))
        classroom = request.env['op.classroom'].sudo().browse(
            int(params.get('classroom_id') or 0))
        start = parse_date(params.get('start_date'))
        end = parse_date(params.get('end_date'))
        raw_days = params.get('weekdays_csv') or ''
        days = set()
        for piece in str(raw_days).split(','):
            piece = piece.strip()
            if piece.isdigit() and 0 <= int(piece) <= 6:
                days.add(int(piece))

        if not course.exists():
            return None, '请选择课程或填写新课程名。'
        if not batches:
            return None, '请选择班级。'
        if not subject.exists():
            return None, '请选择科目或填写新科目名。'
        if not faculty.exists():
            return None, '请选择教师。'
        if not timing.exists():
            return None, '请选择节次或填写自定义时间。'
        if not start or not end:
            return None, '请填写起止日期。'
        if start > end:
            return None, '结束日期不能早于开始日期。'
        if not days:
            return None, '请至少勾选一个星期几。'
        if (end - start).days > 366:
            return None, '日期跨度不能超过一年，请分段排课。'

        # ---- S2 周次范围 / 单双周 ----
        ranges = parse_week_ranges(params.get('week_ranges'))
        parity = (params.get('parity') or 'weekly').strip() or 'weekly'
        if parity not in ('weekly', 'odd', 'even'):
            parity = 'weekly'
        anchor_raw, anchor_label = self._term_anchor_info(start)
        anchor = monday_of(anchor_raw) if anchor_raw else monday_of(start)
        begin, finish = timing_span(timing)

        # 周矩阵列：起始周到结束周（锚点口径）
        week_nos = []
        wn = week_no_of(start, anchor)
        w1 = week_no_of(end, anchor)
        while wn <= w1:
            week_nos.append(wn)
            wn += 1

        return {
            'course': course, 'subject': subject, 'timing': timing,
            'faculty': faculty, 'classroom': classroom,
            'start': start, 'end': end, 'days': sorted(days),
            'ranges': ranges, 'parity': parity,
            'anchor': anchor, 'anchor_label': anchor_label,
            'begin': begin, 'finish': finish, 'week_nos': week_nos,
            'holidays': request.env['edu.schedule.holiday'].sudo().search(
                [('active', '=', True)]),
            'occupied': self._occupied_map(start, end),
            # G4：教师已登记的例外 —— 整段区间只查一次，逐格不重复查库
            'faculty_leave': self._faculty_leave_intervals(
                faculty, start, end),
            'faculty_leave_registered': bool(faculty.exists())
            and faculty._has_leave_records(),
            # G4 逃逸口：勾了「忽略教师不可用」才放行（权限复核在模型层）
            'ignore_teacher_leave': bool(params.get('ignore_teacher_leave'))
            and privileged_staff(),
        }, None

    def _meta_for(self, ctx, batch, begin, finish):
        """单班的排课要素摘要（字段与旧版逐字一致，模板零改动）。"""
        course, subject = ctx['course'], ctx['subject']
        faculty, classroom = ctx['faculty'], ctx['classroom']
        timing = ctx['timing']
        return {
            'course_name': course.name,
            'batch_name': batch.name,
            'subject_name': subject.name,
            'faculty_name': faculty.name,
            'timing_label': '%s（%s-%s）' % (
                timing.name, fmt_minutes(begin), fmt_minutes(finish)),
            'classroom_name': classroom.name if classroom.exists() else '（不指定）',
            'range_label': '%s ~ %s' % (ctx['start'], ctx['end']),
            'days_label': '、'.join(WEEKDAY_NAMES[d] for d in ctx['days']),
            'ids': {
                'course_id': course.id,
                'batch_id': batch.id,
                'subject_id': subject.id,
                'faculty_id': faculty.id,
                'timing_id': timing.id,
                'classroom_id': classroom.id if classroom.exists() else 0,
            },
            'weekdays_csv': ','.join(str(d) for d in ctx['days']),
            'week_ranges_spec': (','.join(str(w) for w in ctx['ranges'])
                                 if ctx['ranges'] else ''),
            'parity': ctx['parity'],
            'parity_label': _PARITY_LABEL.get(ctx['parity'], '每周'),
            'anchor_label': ctx['anchor_label'],
        }

    def _plan_for_batch(self, ctx, batch, begin, finish, occupied):
        """单班的 rows + grid（单班与多班共用）。

        与旧内层循环**逐行为同**，只多两件事：
          ① 每个格带上冲突维度 dims / dims_text（供 C-1 同形的明细表用）；
          ② 生成的槽**就地追加进 occupied** —— 多班共用同一位教师时，
             后续班必须看得见前面班刚排的课时，否则「每班顺延 = 0」
             会得到一片假绿，再被基座拦下（设计稿 §18.3 能力 A）。
        """
        flags = self._switch_flags()
        labels = request.env['op.session'].IMPACT_DIM_LABELS
        rows = []
        holiday_dates = []
        grid_rows = []
        fac_id = ctx['faculty'].id
        room_id = ctx['classroom'].id if ctx['classroom'].exists() else 0
        sub_id = ctx['subject'].id
        for day_idx in ctx['days']:
            cells = []
            for week_n in ctx['week_nos']:
                d = ctx['anchor'] + datetime.timedelta(
                    days=7 * (week_n - 1) + day_idx)
                if not (ctx['start'] <= d <= ctx['end']):
                    cells.append({'week': week_n, 'date': '',
                                  'status': 'none'})
                    continue
                hit = next((h for h in ctx['holidays']
                            if h._matches(d, batch.id)), None)
                if hit:
                    cells.append({'week': week_n, 'date': str(d),
                                  'status': 'holiday'})
                    label = '%s（%s）' % (d, hit.name or '停课')
                    if label not in holiday_dates:
                        holiday_dates.append(label)
                    continue
                if not (week_in_ranges(week_n, ctx['ranges'])
                        and parity_ok(week_n, ctx['parity'])):
                    cells.append({'week': week_n, 'date': str(d),
                                  'status': 'miss'})
                    continue
                dims = self._slot_conflict_dims(
                    d, begin, finish, ctx['faculty'], ctx['classroom'],
                    batch, ctx['subject'], occupied)
                leave = self._faculty_leave_hit(ctx, d, begin, finish)
                if leave:
                    # 「被规则限制」档：不是与别的课节冲突，而是规则不让排
                    dims = ['faculty_leave'] + dims
                cells.append({
                    'week': week_n, 'date': str(d),
                    'status': 'unavailable' if leave
                    else ('conflict' if dims else 'ok'),
                })
                local_begin = datetime.datetime.combine(
                    d, datetime.time(hour=begin // 60, minute=begin % 60))
                local_finish = datetime.datetime.combine(
                    d, datetime.time(hour=finish // 60, minute=finish % 60))
                u_begin = local_to_utc(local_begin)
                u_finish = local_to_utc(local_finish)
                rows.append({
                    'date': str(d),
                    'weekday': WEEKDAY_NAMES[d.weekday()],
                    'time_text': '%s-%s' % (
                        fmt_minutes(begin), fmt_minutes(finish)),
                    'dims': dims,
                    'dims_text': '、'.join(
                        labels.get(x, x) for x in dims) or '无冲突',
                    'rule': 'faculty_leave' if leave else '',
                    'leave_text': leave,
                    # 勾了「忽略教师不可用」⇒ 教师例外不再算拦截（创建时留痕）
                    'blocking': (bool(leave)
                                 and not ctx['ignore_teacher_leave'])
                    or any(flags.get(x) for x in dims),
                    '_start_utc': u_begin,
                    '_end_utc': u_finish,
                })
                occupied.setdefault(d, []).append(
                    (u_begin, u_finish, fac_id, room_id, batch.id, sub_id))
            grid_rows.append({
                'weekday': day_idx,
                'name': WEEKDAY_NAMES[day_idx],
                'cells': cells,
            })

        grid_counts = {'ok': 0, 'conflict': 0, 'holiday': 0, 'miss': 0,
                       'none': 0, 'unavailable': 0}
        for gr in grid_rows:
            for c in gr['cells']:
                grid_counts[c['status']] = grid_counts.get(c['status'], 0) + 1
        grid = {'weeks': ctx['week_nos'], 'rows': grid_rows,
                'counts': grid_counts,
                'holidays_label': '、'.join(holiday_dates)}
        return rows, grid

    # ------------------- G4 教师不可用（判定只用登记过的例外） -------------------

    def _faculty_leave_intervals(self, faculty, start, end):
        """本次排课区间内该教师已登记的全部例外（UTC naive 三元组；整段只查一次）。

        未登记 / 没有资源 ⇒ []，即「可用」（§10.4 兜底）；但是否登记过由
        ctx['faculty_leave_registered'] 带出去，本页要给灰字提示，**不得静默**。
        """
        if not faculty.exists():
            return []
        lo = local_to_utc(datetime.datetime.combine(
            start, datetime.time(hour=0, minute=0)))
        hi = local_to_utc(datetime.datetime.combine(
            end, datetime.time(hour=23, minute=59)))
        return faculty._leave_intervals_utc(lo, hi)

    def _faculty_leave_hit(self, ctx, day, begin, finish):
        """该格是否撞上教师已登记的例外 → 中文原因（含时刻与事由）；否则空串。"""
        intervals = ctx.get('faculty_leave') or []
        if not intervals:
            return ''
        u_begin = local_to_utc(datetime.datetime.combine(
            day, datetime.time(hour=begin // 60, minute=begin % 60)))
        u_finish = local_to_utc(datetime.datetime.combine(
            day, datetime.time(hour=finish // 60, minute=finish % 60)))
        for lv_begin, lv_end, reason in intervals:
            if lv_begin < u_finish and u_begin < lv_end:
                when = utc_to_local(lv_begin).strftime('%Y-%m-%d %H:%M') \
                    + '–' + utc_to_local(lv_end).strftime('%H:%M')
                return '教师不可用（%s%s）' % (
                    when, '·' + reason if reason else '')
        return ''

    def _build_plan(self, params, batches=None):
        """由原始参数构建**单班**排课计划。返回 (meta, rows, grid, error)。

        rows 为逐日期明细（创建用）；grid 为周矩阵（S2 预览用，
        行=选中星期几，列=周次，格状态 ok/holiday/conflict/miss/none）。
        不填周次范围 + 每周时 rows 与旧版一致（零丢失）。
        """
        if batches is None:
            batches = request.env['op.batch'].sudo().browse(
                int(params.get('batch_id') or 0))
        ctx, error = self._plan_ctx(params, batches)
        if error:
            return None, [], {}, error
        batch = batches[:1]
        begin, finish = ctx['begin'], ctx['finish']
        rows, grid = self._plan_for_batch(
            ctx, batch, begin, finish, ctx['occupied'])
        meta = self._meta_for(ctx, batch, begin, finish)
        meta['holidays_label'] = grid.get('holidays_label', '')
        # G3：数据异常分两级 —— 致命（阻止提交）/ 待补（允许继续）
        fatal, todo = self._precheck(params, ctx, batch, begin, finish)
        meta['precheck'] = {'fatal': fatal, 'todo': todo}
        meta['faculty_leave_registered'] = ctx['faculty_leave_registered']
        return meta, rows, grid, None

    # ------------------- §8.1 三类预检查之「数据异常」（G3） -------------------

    def _batch_student_ids(self, batch):
        """班级名下的在读学生（与创建链路同一取数口径，不写第二套学生名单）。"""
        if not batch.exists():
            return []
        return request.env['op.student.course'].sudo().search(
            [('batch_id', '=', batch.id)]).mapped('student_id').ids

    def _uses_meeting_links(self):
        """本校是否在用「课节会议链接」（有任一课节挂过日程即为真）。

        为什么要这个门：新生成的课节天生没有链接，无条件提示就是天天黄字，
        反而把真正的待补项淹掉；从没用过链接的学校不该看到这条提示。
        """
        return bool(request.env['op.session'].sudo().search_count(
            [('calendar_event_id', '!=', False)]))

    def _precheck(self, params, ctx, batch, begin, finish):
        """数据异常档（§8.1）：返回 (fatal, todo)，两组 [{code, text}]。

        致命 ⇒ 红字 + 阻止提交；待补 ⇒ 黄字提示 + 允许继续。
        **必须分级**：生产 classroom_id 非空 = 0/216、任课教师全是占位「待定」，
        判成致命就是 216 条红（全红 = 没有判据）。
        科目池同理：只在课程**明确登记了科目池**时才判——空池 = 未登记，
        判了同样会全红；「或新建科目」这条既有入口属于显式意图，不判。
        """
        fatal, todo = [], []
        course, subject = ctx['course'], ctx['subject']
        faculty, classroom = ctx['faculty'], ctx['classroom']
        if not faculty.exists():
            fatal.append({
                'code': 'no_faculty',
                'text': '未指定任课教师：课节会缺教师归属，不能生成。',
            })
        if not batch.course_id:
            fatal.append({
                'code': 'batch_no_course',
                'text': '班级「%s」没有关联课程：请先在班级档案里选好课程。'
                        % batch.name,
            })
        if course.exists() and subject.exists() and course.subject_ids \
                and subject not in course.subject_ids:
            fatal.append({
                'code': 'subject_out_of_pool',
                'text': '科目「%s」不在课程「%s」的科目池里：请换成本课程的科目，'
                        '或先在课程档案里把它加进去。' % (subject.name,
                                                        course.name),
            })
        if finish <= begin:
            fatal.append({
                'code': 'bad_span',
                'text': '结束时刻不晚于开始时刻：请检查「上课时间」的时长设置。',
            })
        if not classroom.exists():
            todo.append({
                'code': 'no_classroom',
                'text': '未指定教室：可以先生成，之后在课节上补教室。',
            })
        if faculty.exists() and faculty._is_placeholder():
            todo.append({
                'code': 'placeholder_faculty',
                'text': '任课教师是占位「待定」：课表上会是待定，生成后请尽快'
                        '换成真实教师。',
            })
        if batch.exists() and not self._batch_student_ids(batch):
            todo.append({
                'code': 'no_students',
                'text': '班级「%s」名下没有在读学生：生成的课节不带学生名单，'
                        '课前提醒发不出去。' % batch.name,
            })
        if self._uses_meeting_links():
            todo.append({
                'code': 'no_meeting_link',
                'text': '生成的课节不带会议链接：需要线上课时请生成后逐个设置。',
            })
        return fatal, todo

    # ------------------- §18 多班批量排课（各年级分开排） -------------------

    def _resolve_batch_ids(self, params):
        """本次勾选的班级（表单顺序，去重，只保留存在的）。空 = 单班模式。

        口径（页面同步写明）：**第 1 个班 = 勾选列表里最上面那个**
        （HTML 表单顺序，不依赖点击顺序）—— 不做隐式猜测（设计稿 §18.3）。
        """
        raw = []
        try:
            raw = request.httprequest.form.getlist('batch_ids')
        except Exception:
            raw = []
        if not raw:
            single = params.get('batch_ids')
            one = single.strip() if isinstance(single, str) else ''
            raw = [one] if one else []
        Batch = request.env['op.batch'].sudo()
        ids = []
        for piece in raw:
            n = _as_int(piece)
            if n and n not in ids and Batch.browse(n).exists():
                ids.append(n)
        return Batch.browse(ids)

    def _stagger_step(self, params, ctx):
        """每班顺延分钟。返回 (step, error)。

        留空 = **一个课时长度**（默认档，教务零新概念）；填 0 也允许 ——
        0 会让所有班同刻，由冲突预检用**中文人话**挡住，
        而不是在这里造一条假的表单规则（设计稿 §18.6 V21 就是打这个）。
        """
        raw = params.get('stagger_minutes')
        raw = (raw or '').strip() if isinstance(raw, str) else ''
        shape = ctx['finish'] - ctx['begin']
        if not raw:
            return shape, None
        try:
            step = int(raw)
        except (TypeError, ValueError):
            return 0, '「每班顺延」请填写整数分钟（留空 = 自动用一个课时长度）。'
        if step < 0:
            return 0, '「每班顺延」不能为负数（留空 = 自动用一个课时长度）。'
        return step, None

    def _build_plans_multi(self, params, batches):
        """多班批量排课：N 个班各一组课时，时间按每班顺延错开。

        返回 (data, error)；data = {step, span, plans[], batch_count,
        total, conflict_total}，plans 按勾选顺序，每项 {batch, meta, rows,
        grid, time_label, offset_label, conflict_rows, ok_count}。

        冲突判据 = 既有四查口径（_slot_conflict_dims + _switch_flags），
        **本批已生成的课时也参与后续班的判定**（同一教师 ⇒ 不查就是假绿）。
        """
        ctx, error = self._plan_ctx(params, batches)
        if error:
            return None, error
        step, step_err = self._stagger_step(params, ctx)
        if step_err:
            return None, step_err
        plans = []
        occupied = ctx['occupied']
        for idx, batch in enumerate(batches):
            begin = ctx['begin'] + idx * step
            finish = ctx['finish'] + idx * step
            if finish > 24 * 60:
                return None, ('第 %d 个班「%s」顺延后跨过午夜，'
                              '请减小「每班顺延」或把首班时间提前。'
                              % (idx + 1, batch.name))
            rows, grid = self._plan_for_batch(
                ctx, batch, begin, finish, occupied)
            blocked = [r for r in rows if r['blocking']]
            fatal, todo = self._precheck(params, ctx, batch, begin, finish)
            meta = self._meta_for(ctx, batch, begin, finish)
            meta['precheck'] = {'fatal': fatal, 'todo': todo}
            meta['faculty_leave_registered'] = ctx['faculty_leave_registered']
            plans.append({
                'batch': batch,
                'meta': meta,
                'rows': rows,
                'grid': grid,
                'time_label': '%s-%s' % (
                    fmt_minutes(begin), fmt_minutes(finish)),
                'offset_label': ('首班 · 不顺延' if idx == 0
                                 else '顺延 %d 分钟' % (idx * step)),
                'conflict_rows': blocked,
                'conflict_count': len(blocked),
                'ok_count': len(rows) - len(blocked),
            })
        return {
            'step': step,
            'span': ctx['finish'] - ctx['begin'],
            'plans': plans,
            'batch_count': len(plans),
            'total': sum(len(p['rows']) for p in plans),
            'conflict_total': sum(p['conflict_count'] for p in plans),
            # G3：致命数据异常（任一班有 ⇒ 整批不许提交，与冲突同一形态）
            'fatal_total': sum(len(p['meta']['precheck']['fatal'])
                               for p in plans),
            'faculty_leave_registered': ctx['faculty_leave_registered'],
        }, None

    def _multi_block_message(self, data):
        """整批拒绝时的中文人话提示（逐条列出冲突；不暴露基座英文报错）。"""
        rows = []
        leave_n = 0
        for plan in data['plans']:
            for row in plan['conflict_rows']:
                if row.get('rule'):
                    leave_n += 1
                rows.append('%s · %s %s %s · %s' % (
                    plan['batch'].name, row['date'], row['weekday'],
                    row['time_text'], row['dims_text']))
        if leave_n:
            head = ('有 %d 条课节不能生成（其中 %d 条是教师不可用），已整批取消'
                    '创建（一节都没写入）。请换教师或改「上课时间」，确需强排时'
                    '勾选「忽略教师不可用」再重试。明细：' % (len(rows), leave_n))
        else:
            head = ('有 %d 条课节与既有安排冲突，已整批取消创建（一节都没写入）。'
                    '请调整「上课时间」或「每班顺延」后重试。冲突明细：' % len(rows))
        shown = '；'.join(rows[:12])
        tail = '' if len(rows) <= 12 else '；另有 %d 条（见下方预览）' % (
            len(rows) - 12)
        return head + shown + tail

    # ------------------------- A. 周期排课 -------------------------

    @http.route('/timetable/bulk', type='http', auth='user', website=True)
    def timetable_bulk(self, **kw):
        if not require_internal():
            return request.redirect('/my/home', code=303)
        return self._render_bulk({
            'created': kw.get('created'),
            'failed': kw.get('failed'),
            'multi_created': kw.get('multi_created'),
            'batch_rows': self._batch_rows(),
            'selected_batch_ids': [],
            'holidays': _upcoming_holidays(),
            # 服务端分流：只有 ?tool=deactivate 才渲染停用表（见 _render_bulk 的说明）
            'tool': (kw.get('tool') or '').strip(),
        })

    def _render_multi_preview(self, params, batches, data=None, error=None):
        """多班预览页（同一模板，multi 分支渲染）。"""
        values = {
            'title': '排课预览',
            'page_name': 'edu_schedule_preview',
            'multi': data,
            'error': error,
            'params': params,
            'selected_batch_ids': batches.ids,
            # ② 返回修改带着已填值回跳；④ 提前告知「勾选的盖掉单班」
            'back_url': self._bulk_back_url(),
            'notice': self._batch_priority_notice(),
            'total': data['total'] if data else 0,
            'can_ignore': privileged_staff(),
            'ignore_checked': bool(params.get('ignore_teacher_leave')),
            'meta': None,
            'rows': [],
            'grid': None,
        }
        return request.render('edu_schedule.edu_schedule_preview', values)

    def _render_single_preview(self, params, meta, rows, grid, error=None):
        """单班预览页（multi=None ⇒ 模板走单班分支，与改动前逐字一致）。

        致命数据异常时也走这里回显：预览页才是三类判据的展示地。
        """
        return request.render('edu_schedule.edu_schedule_preview', {
            'title': '排课预览',
            'page_name': 'edu_schedule_preview',
            'multi': None,
            'meta': meta,
            'rows': rows,
            'grid': grid,
            'total': len(rows),
            'params': params,
            'error': error,
            'back_url': self._bulk_back_url(),
            'can_ignore': privileged_staff(),
            'ignore_checked': bool(params.get('ignore_teacher_leave')),
        })

    def _apply_teacher_leave_skip(self, Session, ignore):
        """勾了「忽略教师不可用」⇒ 创建时带上逃逸口 context。

        未勾选原样返回：逐节创建会被模型层拦下并计入 failed（§10.3）。
        权限复核在模型层（只有教务组/系统组有效），这里不做门禁重复。
        """
        if not ignore:
            return Session
        return Session.with_context(**{
            Session.SKIP_TEACHER_LEAVE_KEY: True})

    @http.route('/timetable/bulk/preview', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def timetable_bulk_preview(self, **kw):
        if not require_internal():
            return request.redirect('/my/home', code=303)
        days = request.httprequest.form.getlist('weekday')
        params = dict(kw)
        params['weekdays_csv'] = ','.join(
            d for d in days if str(d).strip().isdigit())
        # §18 多班批量排课：勾了班级（>=1）走多班；否则沿用原单班路径（零改动）。
        batch_ids = self._resolve_batch_ids(params)
        if batch_ids:
            data, error = self._build_plans_multi(params, batch_ids)
            if error:
                return self._render_bulk({
                    'error': error,
                    'selected_batch_ids': batch_ids.ids,
                })
            return self._render_multi_preview(params, batch_ids, data=data)
        meta, rows, grid, error = self._build_plan(params)
        if error:
            return self._render_bulk({'error': error})
        return self._render_single_preview(params, meta, rows, grid)

    @http.route('/timetable/bulk/create', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def timetable_bulk_create(self, **kw):
        if not require_internal():
            return request.redirect('/my/home', code=303)
        batch_ids = self._resolve_batch_ids(kw)
        if batch_ids:
            return self._create_multi(kw, batch_ids)
        meta, rows, _grid, error = self._build_plan(kw)
        if error:
            return self._render_bulk({'error': error})
        fatal = (meta.get('precheck') or {}).get('fatal') or []
        if fatal:
            # 致命数据异常：红字 + 阻止提交（回预览页，让三条判据都看得见）
            return self._render_single_preview(
                kw, meta, rows, _grid,
                error='有 %d 项数据异常必须先修好，本次一节都没生成：%s' % (
                    len(fatal), '；'.join(f['text'] for f in fatal)))
        ignore = bool(kw.get('ignore_teacher_leave'))
        Session = self._apply_teacher_leave_skip(
            request.env['op.session'].sudo(), ignore)
        student_ids = self._batch_student_ids(
            request.env['op.batch'].sudo().browse(meta['ids']['batch_id']))
        created, failed, first_error = 0, 0, ''
        for row in rows:
            vals = {
                'course_id': meta['ids']['course_id'],
                'batch_id': meta['ids']['batch_id'],
                'subject_id': meta['ids']['subject_id'],
                'faculty_id': meta['ids']['faculty_id'],
                'timing_id': meta['ids']['timing_id'],
                'start_datetime': row['_start_utc'].strftime(
                    '%Y-%m-%d %H:%M:%S'),
                'end_datetime': row['_end_utc'].strftime(
                    '%Y-%m-%d %H:%M:%S'),
                'student_ids': [(6, 0, student_ids)],
            }
            if meta['ids']['classroom_id']:
                vals['classroom_id'] = meta['ids']['classroom_id']
            try:
                Session.create(vals)
                created += 1
            except Exception as exc:
                failed += 1
                if not first_error:
                    first_error = str(exc).replace(chr(10), ' ')[:120]
        tail = '&error_msg=%s' % first_error if first_error else ''
        # 4a 审计：批量排课（教师不可用时把「绕过/命中」的节数据实写清）
        leave_rows = len([r for r in rows if r.get('rule')])
        detail = '新建 %d 节 · 失败 %d 节' % (created, failed)
        if leave_rows:
            detail += ' · %s教师不可用 %d 节' % (
                '绕过' if ignore else '命中', leave_rows)
        request.env['edu.audit.log'].sudo()._log(
            '批量排课', 'op.session', 0, '', detail)
        return request.redirect(
            '/timetable/bulk?created=%d&failed=%d%s' % (
                created, failed, tail), code=303)

    def _create_multi(self, params, batches):
        """多班创建：**先整批预检，有一条冲突就一节都不写**（§18.3 能力 A）。

        为什么不做「写一半」：4 个年级里只排上 1~3 个，教务要自己去比对
        哪几个成了、哪几个没成 —— 这是最难收拾的中间态。整批拒绝 + 中文
        明细，教务改一个数字重试即可。
        """
        data, error = self._build_plans_multi(params, batches)
        if error:
            return self._render_bulk({
                'error': error, 'selected_batch_ids': batches.ids})
        if data.get('fatal_total'):
            fatal_texts = [f['text'] for p in data['plans']
                           for f in p['meta']['precheck']['fatal']]
            return self._render_multi_preview(
                params, batches, data=data,
                error='有 %d 项数据异常必须先修好，本次一节都没生成：%s' % (
                    data['fatal_total'], '；'.join(fatal_texts[:5])))
        if data['conflict_total']:
            return self._render_multi_preview(
                params, batches, data=data,
                error=self._multi_block_message(data))
        ignore = bool(params.get('ignore_teacher_leave'))
        Session = self._apply_teacher_leave_skip(
            request.env['op.session'].sudo(), ignore)
        created = failed = 0
        first_error = ''
        for plan in data['plans']:
            meta = plan['meta']
            student_ids = self._batch_student_ids(
                request.env['op.batch'].sudo().browse(
                    meta['ids']['batch_id']))
            for row in plan['rows']:
                vals = {
                    'course_id': meta['ids']['course_id'],
                    'batch_id': meta['ids']['batch_id'],
                    'subject_id': meta['ids']['subject_id'],
                    'faculty_id': meta['ids']['faculty_id'],
                    'timing_id': meta['ids']['timing_id'],
                    'start_datetime': row['_start_utc'].strftime(
                        '%Y-%m-%d %H:%M:%S'),
                    'end_datetime': row['_end_utc'].strftime(
                        '%Y-%m-%d %H:%M:%S'),
                    'student_ids': [(6, 0, student_ids)],
                }
                if meta['ids']['classroom_id']:
                    vals['classroom_id'] = meta['ids']['classroom_id']
                try:
                    Session.create(vals)
                    created += 1
                except Exception as exc:
                    failed += 1
                    if not first_error:
                        first_error = str(exc).replace(chr(10), ' ')[:120]
        leave_rows = len([r for p in data['plans'] for r in p['rows']
                          if r.get('rule')])
        detail = ('班级 %d 个 · 新建 %d 节 · 失败 %d 节 · 每班顺延 %d 分钟'
                  % (data['batch_count'], created, failed, data['step']))
        if leave_rows:
            detail += ' · %s教师不可用 %d 节' % (
                '绕过' if ignore else '命中', leave_rows)
        request.env['edu.audit.log'].sudo()._log(
            '多班批量排课', 'op.session', 0,
            '、'.join(p['batch'].name for p in data['plans']), detail)
        tail = '&error_msg=%s' % first_error if first_error else ''
        return request.redirect(
            '/timetable/bulk?multi_created=%d&created=%d&failed=%d%s' % (
                data['batch_count'], created, failed, tail), code=303)

    # ------------------- §18-B. 旧合班课时批量停用（不删） -------------------

    @http.route('/timetable/batch/<int:bid>/deactivate', type='http',
                auth='user', website=True)
    def batch_deactivate(self, bid, **kw):
        """二次确认页（GET，只读）：先看清会影响到谁，再决定停不停。

        门禁：内部用户 + 教务组/管理员（同 /timetable/session/<id>/notify）。
        影响面 = 运行时计算，不落库、不新增字段（复用 C-1 口径）。
        """
        if not require_internal():
            return request.redirect('/my/home', code=303)
        if not privileged_staff():
            return request.redirect('/my/home', code=303)
        batch = request.env['op.batch'].sudo().browse(bid).exists()
        if not batch:
            return request.redirect('/my/home', code=303)
        values = dict(batch._batch_deactivate_impact())
        values.update({
            'title': '批量停用课时',
            'page_name': 'edu_schedule_batch_deactivate',
            # 该页与批量工具的页脚提示无关，隐藏那句说明
            'hide_bulk_hint': True,
            'done': _as_int(kw.get('done')),
            'skipped': _as_int(kw.get('skipped')),
            'error': (kw.get('error') or '').strip(),
        })
        return request.render(
            'edu_schedule.edu_schedule_batch_deactivate', values)

    @http.route('/timetable/batch/<int:bid>/deactivate/confirm', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def batch_deactivate_confirm(self, bid, **kw):
        """执行批量停用：state 置 cancel（**不删行**）+ 审计留痕。

        二次确认是**服务端**判据（不是前端 disabled）：未勾选确认框直接
        303 回确认页并带中文原因。
        """
        if not require_internal():
            return request.redirect('/my/home', code=303)
        if not privileged_staff():
            return request.redirect('/my/home', code=303)
        batch = request.env['op.batch'].sudo().browse(bid).exists()
        if not batch:
            return request.redirect('/my/home', code=303)
        if (kw.get('confirm') or '') != 'yes':
            return request.redirect(
                '/timetable/batch/%d/deactivate?error=%s'
                % (bid, url_quote('请先勾选「我已确认」再提交。')), code=303)
        res = batch.deactivate_batch_sessions()
        return request.redirect(
            '/timetable/batch/%d/deactivate?done=%d&skipped=%d'
            % (bid, res['cancelled'], res['already']), code=303)

    # ------------------------- B. 改课影响面（C-1） -------------------------

    @http.route('/timetable/session/<int:sid>/impact', type='http',
                auth='user', website=True)
    def session_impact(self, sid, **kw):
        """改课影响面页（GET，只读）：先看清「改这一动会惊动谁」。

        口径见 docs/plans/session-change-impact-design.md §7.2/§7.3：
        门禁 = require_internal（门户学生 303 回 /my/home）；
        影响面 = 运行时计算，不落库、不新增字段。
        """
        if not require_internal():
            return request.redirect('/my/home', code=303)
        session = request.env['op.session'].sudo().browse(sid).exists()
        if not session:
            # 不存在的课节：按「看不到」处理，不给 500（写路由三收紧）。
            return request.redirect('/my/home', code=303)
        data = session._impact_data()
        values = dict(data)
        values.update({
            'title': '改课影响面',
            'page_name': 'edu_schedule_impact',
            # 该页与本模块批量工具的页脚提示无关，隐藏那句说明
            'hide_bulk_hint': True,
            'can_notify': privileged_staff(),
            'sent': _as_int(kw.get('sent')),
            'failed': _as_int(kw.get('failed')),
            'muted': _as_int(kw.get('muted')),
            'notified': bool(kw.get('notified')),
        })
        return request.render('edu_schedule.edu_session_impact', values)

    @http.route('/timetable/session/<int:sid>/notify', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def session_notify(self, sid, **kw):
        """一键通知（POST 写路由）：只发站内信给任课教师 + 该班在读学生。

        幂等口径（设计稿 §7.4）：允许重复点（教务可能补发），每次留一条
        edu.audit.log('课节变更通知')，页面据此显示「最近一次通知」。
        失败不阻断：逐人计数后回显在影响面页上。
        """
        if not require_internal():
            return request.redirect('/my/home', code=303)
        if not privileged_staff():
            # 只有教务组/系统组能发起通知（与 /edu/audit 同一把门）。
            return request.redirect('/my/home', code=303)
        session = request.env['op.session'].sudo().browse(sid).exists()
        if not session:
            return request.redirect('/my/home', code=303)
        res = session._notify_session_change()
        return request.redirect(
            '/timetable/session/%d/impact?notified=1&sent=%d&failed=%d&muted=%d'
            % (session.id, res['sent'], res['failed'], res['muted']),
            code=303)


