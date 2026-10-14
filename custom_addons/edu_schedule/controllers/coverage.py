# -*- coding: utf-8 -*-
"""排课完成度看板（G2，只读聚合；设计稿 §8.3）。

路由：
- GET /timetable/coverage            看板页（门禁 = require_internal ∧ 教务/系统组）
- GET /timetable/coverage/unfilled   (班 × 科目) 未排课差集导出（表格文件）

四区块 = 按班覆盖 / 按课程覆盖 / 数据完整度 / 未排课清单。

口径（docs/plans/scheduling-overhaul-design.md §8.3 四区块 + §7.3 判定域，逐条照抄）：
- 「已排课」= count(op.session) > 0，条件 batch_id = 该班 ∧ subject_id = 该科目
  ∧ state != 'cancel' ∧ start_datetime 落在学期窗口内；
  **不计** state='cancel'、**不计** active=False —— 后者由 ORM 的 active_test 默认排除，
  _read_group 同样受其约束，故本文件不显式写 ('active', '=', True)（写了反而是自造第二口径）。
- 聚合一律走 _read_group（**禁止**逐科目 search_count：88 门 = 88 次查询）。
- **红线**：本页只读，不提供任何写入入口（写入口只有一个 = /timetable/bulk）。
"""
import csv
import datetime
import io
import logging

import pytz

from odoo import fields, http
from odoo.http import content_disposition, request

from odoo.addons.edu_schedule.models.week_utils import term_anchor

from .main import _batch_sort_key, require_internal

_logger = logging.getLogger(__name__)

# 看板可见性（§19.1 P4：仅教务 / 管理员）：教务组 ∨ 系统组
COVERAGE_GROUPS = (
    'openeducat_timetable.group_op_timetable_manager',
    'openeducat_core.group_op_back_office_admin',
    'base.group_system',
)

# 占位教师（生产 op_faculty 唯一一行就叫「待定」）：命中即不计入「实名」
_PLACEHOLDER_MARKS = ('待定', '占位', '未定', '暂无')

# 状态码 → 中文（页面上不出现英文串；未知码归「其它」，不回落成英文）
_STATE_LABEL = {'draft': '草稿', 'confirm': '已确认', 'done': '已完成'}

# 未排课清单在页面上最多预览多少行（全量走导出）
_UNFILLED_PREVIEW = 50


def coverage_allowed():
    """看板门禁：内部用户 ∧（教务组 ∨ 系统组）。

    学生 / 家长 / 教师都过不了这一关 —— 门户角色不是 base.group_user 或不在上述两组内，
    调用方一律 303 回 /my/home（§13.2 V9）。
    """
    if not require_internal():
        return False
    user = request.env.user
    return any(user.has_group(g) for g in COVERAGE_GROUPS)


def _day_start_utc(day):
    """本地某日 00:00 → UTC naive（ORM 入库口径）。

    换算技术与双时区来源沿用 week_utils.week_window_utc（该函数固定 +7 天，
    学期窗口不是整周，故此处只复用同一换算方式 + 同一时区来源 request.env.user.tz）。
    """
    tz = pytz.timezone(request.env.user.tz or 'UTC')
    aware = tz.localize(datetime.datetime(day.year, day.month, day.day))
    return aware.astimezone(pytz.UTC).replace(tzinfo=None)


def _term_window():
    """学期窗口的 UTC naive 起止 → (term, lo, hi)；无学期 ⇒ (empty, None, None)。

    学期 = 今天落在 term_start_date ~ term_end_date 内的那条；落在学期之间（寒暑假）
    退回全站统一的三级锚点 week_utils.term_anchor；仍取不到 ⇒ **不过滤**，并由页面
    横幅显式说明「未识别学期」，绝不静默改变口径（§7.3 的兜底条款）。
    """
    today = datetime.date.today()
    Term = request.env['op.academic.term'].sudo()
    term = Term.search([('term_start_date', '<=', today),
                        ('term_end_date', '>=', today)], limit=1)
    if not term:
        anchor = term_anchor(request.env, today)
        if anchor:
            term = Term.search([('term_start_date', '=', anchor)], limit=1)
    if not term:
        return Term.browse(), None, None
    lo = _day_start_utc(term.term_start_date)
    hi = _day_start_utc(term.term_end_date + datetime.timedelta(days=1))
    return term, lo, hi


def _session_domain(lo, hi):
    """§7.3 判定域（active=False 由 ORM active_test 兜底，不重复写）。"""
    dom = [('state', '!=', 'cancel')]
    if lo:
        dom += [('start_datetime', '>=', lo), ('start_datetime', '<', hi)]
    return dom


def _group_counts(model, domain, groupby):
    """_read_group 计数 → {键元组: 条数}。

    Odoo19 的 _read_group 对 m2o 分组键返回**记录集**，故用 getattr(key, 'id', key)
    归一为 id；聚合值恒在元组末尾（count / :min 都一样）。
    """
    out = {}
    for row in model._read_group(domain, list(groupby), ['__count']):
        keys = tuple(getattr(k, 'id', k) for k in row[:-1])
        out[keys] = row[-1]
    return out


def _fmt_local_date(dt_utc):
    """UTC naive 时刻 → 用户时区日期文本（空值 → ''）。"""
    if not dt_utc:
        return ''
    return fields.Datetime.context_timestamp(
        request.env.user, dt_utc).strftime('%Y-%m-%d')


def _is_placeholder(name):
    n = (name or '').strip()
    return (not n) or any(mark in n for mark in _PLACEHOLDER_MARKS)


def _availability_row(faculty_total):
    """教师不可用登记率 = 已登记不可用时间的教师 / 全部教师（源 resource.calendar.leaves）。

    S1 尚未给 op.faculty 接 resource.mixin ⇒ 用**字段探测**优雅降级：
    'resource_id' 不在 _fields 时该行显示文字说明而不是 500（§8.2 / §10.4）。
    接线后本函数按 resource.calendar.leaves 只读计数即可生效 —— **不依赖** S1 的方法名，
    所以 S1 换实现也不用改这里。
    """
    env = request.env
    Faculty = env['op.faculty'].sudo()
    label = '教师不可用登记率'
    if 'resource_id' not in Faculty._fields:
        return {'label': label, 'text': '—',
                'hint': '教师资源尚未接线（op.faculty 还没有 resource_id 字段）；'
                        '接线后本行自动显示「已登记 / 全部教师」'}
    try:
        Leaves = env['resource.calendar.leaves'].sudo()
    except KeyError:
        return {'label': label, 'text': '—',
                'hint': '资源日历模型未装载，本行暂不可算'}
    if 'resource_id' not in Leaves._fields:
        return {'label': label, 'text': '—',
                'hint': '资源日历没有 resource_id 字段，本行暂不可算'}
    resource_ids = sorted(k[0] for k in _group_counts(Leaves, [], ['resource_id'])
                          if k[0])
    registered = Faculty.search_count(
        [('resource_id', 'in', resource_ids)]) if resource_ids else 0
    return {'label': label, 'text': '%d / %d' % (registered, faculty_total),
            'hint': '已登记过不可用时间的教师 / 全部教师（源：教师不可用时间记录）'}


def _csv_response(filename, header, rows):
    """通用导出响应（写法照抄 edu_portal/controllers/main.py:47-62 的 csv_download 先例：
    utf-8-sig 防表格软件乱码，中文文件名走 RFC5987）。

    不 import edu_portal 的实现：edu_portal 依赖 edu_schedule，反向 import 会成环，
    而 edu_schedule 的 manifest 不能声明 edu_portal（见 manifest 里 edu_brand 那段注释）。
    """
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


def _coverage_data(show_all=False, unfilled_limit=_UNFILLED_PREVIEW):
    """四区块的全部读数（一次页面 = 固定几次聚合查询，与班级/科目数无关）。"""
    env = request.env
    Session = env['op.session'].sudo()
    Batch = env['op.batch'].sudo()
    StudentCourse = env['op.student.course'].sudo()

    term, lo, hi = _term_window()
    dom = _session_domain(lo, hi)
    total = Session.search_count(dom)
    # 已停课：§7.3 不计入判定域，但要在页面上如实显示（否则「课节总数对不上」）
    cancelled = Session.search_count([('state', '=', 'cancel')] + dom[1:])

    # ① (班, 科目) 计数：区块 1 的「有课时的科目数」+ 区块 4 的差集 + 区块 2 的 M
    pair_counts = _group_counts(Session, dom, ['batch_id', 'subject_id'])
    batch_counts = _group_counts(Session, dom, ['batch_id'])
    batch_first = {}
    for row in Session._read_group(dom, ['batch_id'], ['start_datetime:min']):
        batch, first = row[0], row[-1]
        if batch:
            batch_first[batch.id] = first

    batches = Batch.search([])                        # active_test ⇒ 仅启用班级
    students = _group_counts(
        StudentCourse, [('state', '=', 'running'), ('batch_id', '!=', False)],
        ['batch_id'])

    # ---- 区块 1：按班覆盖 ----
    batch_rows = []
    for b in sorted(batches, key=_batch_sort_key):
        pairs = [sid for (bid, sid) in pair_counts if bid == b.id]
        batch_rows.append({
            'name': b.name or '',
            'code': b.code or '',
            'course': b.course_id.name or '',
            'students': students.get((b.id,), 0),
            'sessions': batch_counts.get((b.id,), 0),
            'subjects': len(pairs),
            'first': _fmt_local_date(batch_first.get(b.id)),
        })

    # ---- 区块 2：按课程覆盖（报课池能不能开放看这一栏）----
    scheduled = {}
    for cid, sid in _group_counts(Session, dom, ['course_id', 'subject_id']):
        if cid:
            scheduled.setdefault(cid, set()).add(sid)
    Course = env['op.course'].sudo()
    course_total = Course.search_count([])
    if show_all:
        courses = Course.search([])
    else:
        # 默认只列「有启用班级」的课程（否则 100+ 门零覆盖课程会把页面淹掉）；
        # 被略过的门数在页面上显式写出，并可一键切到全量 —— 不静默过滤。
        courses = Batch.search([]).mapped('course_id')
    course_rows = []
    for c in courses:
        pool = len(c.subject_ids)
        done = len(scheduled.get(c.id, ()))
        rate = (done * 100 // pool) if pool else 0
        course_rows.append({
            'name': c.name or '',
            'code': c.code or '',
            'pool': pool,
            'done': done,
            'rate': rate,
            'over': max(done - pool, 0),      # 已排但不在课程科目池内 ⇒ M > N，显式提示
            'no_pool': not pool,
        })
    course_rows.sort(key=lambda r: (r['no_pool'], r['rate'], -r['pool'], r['name']))

    # ---- 区块 3：数据完整度 ----
    faculty_used = [k[0] for k in _group_counts(Session, dom, ['faculty_id']) if k[0]]
    faculty_total = env['op.faculty'].sudo().search_count([])
    faculty_real = 0
    for f in env['op.faculty'].sudo().browse(faculty_used):
        if not _is_placeholder(f.name):
            faculty_real += 1
    room_counts = _group_counts(Session, dom, ['classroom_id'])
    room_filled = sum(cnt for k, cnt in room_counts.items() if k[0])
    room_total = env['op.classroom'].sudo().search_count([])
    students_empty = Session.search_count(dom + [('student_ids', '=', False)])
    state_counts = _group_counts(Session, dom, ['state'])
    state_text = ' · '.join(
        '%s %d' % (_STATE_LABEL.get(code, '其它'), state_counts[(code,)])
        for code in ('draft', 'confirm', 'done') if state_counts.get((code,)))
    completeness = [
        {'label': '教师实名率（非占位）',
         'text': '%d / %d' % (faculty_real, len(faculty_used)),
         'hint': '本学期课时用到的教师里，名字不是占位（如「待定」）的位数；'
                 '全校教师 %d 位' % faculty_total},
        {'label': '教室填写率',
         'text': '%d / %d' % (room_filled, total),
         'hint': '填了教室的课时数 / 全部课时数；教室库共 %d 间' % room_total},
        {'label': '学生名单填充率',
         'text': '%d / %d' % (total - students_empty, total),
         'hint': '课节上带学生名单的条数 / 全部课时数'},
        {'label': '课时状态分布',
         'text': state_text or '无课时',
         'hint': '另有已停课 %d 节（§7.3 不计入本页判定域，另行计数）' % cancelled},
        _availability_row(faculty_total),
    ]

    # ---- 区块 4：未排课清单（启用班 × 该班课程科目池 减去 已排课组合）----
    unfilled = []
    for b in sorted(batches, key=_batch_sort_key):
        for s in b.course_id.subject_ids:
            if (b.id, s.id) in pair_counts:
                continue
            unfilled.append({
                'batch': b.name or '',
                'course': b.course_id.name or '',
                'subject': s.name or '',
                'students': students.get((b.id,), 0),
            })
    shown = unfilled if unfilled_limit is None else unfilled[:unfilled_limit]

    if term:
        window_text = '统计窗口：%s（%s 至 %s）；课时口径 = 学期窗口内、状态非「停课」的课节' % (
            term.name, term.term_start_date, term.term_end_date)
    else:
        window_text = '统计窗口：未识别学期 —— 课时已放宽为全库口径（不按学期过滤）'

    return {
        'title': '排课完成度看板',
        'page_name': 'edu_timetable_coverage',
        'hide_bulk_hint': True,       # 骨架页顶部的「单节改删」提示与本页无关
        'term_name': term.name if term else '',
        'no_term': not term,
        'window_text': window_text,
        'total_sessions': total,
        'batch_total': len(batch_rows),
        'batch_rows': batch_rows,
        'course_rows': course_rows,
        'course_total': course_total,
        'course_hidden': 0 if show_all else max(course_total - len(course_rows), 0),
        'show_all': show_all,
        'completeness': completeness,
        'unfilled': shown,
        'unfilled_shown': len(shown),
        'unfilled_total': len(unfilled),
        'unfilled_more': max(len(unfilled) - len(shown), 0),
    }


class EduScheduleCoverage(http.Controller):
    """排课完成度看板（只读；两处路由共用同一门禁）。"""

    @http.route('/timetable/coverage', type='http', auth='user', website=True)
    def timetable_coverage(self, **kw):
        if not coverage_allowed():
            return request.redirect('/my/home', code=303)
        show_all = (kw.get('all') or '') == '1'
        return request.render('edu_schedule.edu_coverage',
                              _coverage_data(show_all))

    @http.route('/timetable/coverage/unfilled', type='http', auth='user')
    def timetable_coverage_unfilled(self, **kw):
        """未排课差集导出（全量，不受页面预览 50 行限制）。"""
        if not coverage_allowed():
            return request.redirect('/my/home', code=303)
        data = _coverage_data(False, unfilled_limit=None)
        rows = [[r['batch'], r['course'], r['subject'], r['students']]
                for r in data['unfilled']]
        return _csv_response('未排课清单.csv',
                             ['班级', '课程', '科目', '在读档案数'], rows)
