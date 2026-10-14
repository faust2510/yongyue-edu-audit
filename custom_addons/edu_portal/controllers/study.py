# -*- coding: utf-8 -*-
"""学生一条龙：课程中心（/my/study，每门在修科目一页）。

设计：docs/plans/study-hub-v3-design.md
调研依据：docs/research/onestop-learning-and-repetitive-work.md
  §1  Canvas Modules 顺序解锁（locked/unlocked/started/completed）
  §1  Moodle Timeline 分桶（逾期 / 近 7 天 / 近 30 天）
  §2  课节级会议链接 = Odoo 19 原生 calendar.event.videocall_location
      + firstjoin 时间窗（「还有 N 分钟可入会」）
  §3  成绩三层（grade_items / grade_grades / grade_letters → 三层展示）

约定：模板只做纯输出，一切文案/数字格式化在控制器侧完成
（规避 Odoo19 t-options 与 QWeb % 格式化陷阱）。

P0（2026-09-28，docs/plans/study-scheduling-design.md §7.2）：本页内嵌**只读**
本周课表 —— 这一节的全部读口径都是**复用**，不是第二套：
  * 角色分流与数据域      = controllers/scheduling.py:148-171（既有 /student/timetable）
  * 周窗口/学期锚点       = edu_schedule.models.week_utils（与排课/课表同一份）
  * 时区换算与停课判定    = controllers/scheduling.py 的 _local_dt / _role_batch_context
  * 完整课表与订阅        = 只链接既有 /student/timetable 与 /my/calendar，不新建渲染器
本页**零写路径**：新增的只有 <a> 链接，没有 POST 表单（tests/smoke/study_week_schedule.py V3）。
"""
from datetime import timedelta

from odoo import fields, http
from odoo.http import request

from odoo.addons.edu_schedule.models.week_utils import (
    monday_of, term_anchor, week_no_of,
)

from .downloads import _can_download, _visibility_domain
from .lms import _subjects_for
from .main import current_student, safe_count, student_course
from .roles import current_faculty, current_parent, privileged_staff
# 与 /student/timetable 共用同一份「星期名 / 时区换算 / 周窗口 / 停课班级域」。
# 复用而不是就地重写，是为了让两侧口径在**源头**上只有一个（H6/S5）；
# 本页新增的那层（角色→域）由 tests/smoke/study_week_schedule.py 的 V2
# 「两页课节集合逐条相等」长期守着，漂移即判红。
from .scheduling import (
    DAY_NAMES, _local_dt, _role_batch_context, _week_window_utc,
)

MAX_SESSIONS = 5      # 每科目「最近 / 下次」各展示上限
MAX_ITEMS_PER_COURSE = 5   # Moodle Timeline 口径：每课程至多 5 条
FULL_TIMETABLE_HREF = '/student/timetable?view=week'   # P0-3：只链接既有课表页
CALENDAR_HREF = '/my/calendar'                         # P0-3：订阅出口指既有 ICS 面板


# --------------------------------------------------------------------------
# 数据装配
# --------------------------------------------------------------------------
def _role_batch_course(student, parent):
    """当前学习者的 (batch_ids, course_ids)，家长取孩子合集。"""
    env = request.env
    Scs = env['op.student.course'].sudo()
    if student:
        scs = Scs.search([('student_id', '=', student.id)])
    elif parent:
        scs = Scs.search([('student_id', 'in', parent.student_ids.ids)])
    else:
        return [], []
    return scs.mapped('batch_id').ids, scs.mapped('course_id').ids


def _sessions_of(subject, batch_ids):
    """科目的最近课节与下次课节（按学习者的班级过滤）。"""
    env = request.env
    domain = [('subject_id', '=', subject.id), ('state', '!=', 'cancel')]
    if batch_ids:
        domain.append(('batch_id', 'in', batch_ids))
    Session = env['op.session'].sudo()
    now = fields.Datetime.now()
    upcoming = Session.search(
        domain + [('start_datetime', '>=', now)],
        order='start_datetime asc', limit=MAX_SESSIONS)
    recent = Session.search(
        domain + [('start_datetime', '<', now)],
        order='start_datetime desc', limit=MAX_SESSIONS)
    return recent, upcoming


def _fmt_dt(dt):
    if not dt:
        return ''
    local = fields.Datetime.context_timestamp(
        request.env.user, dt).replace(tzinfo=None)
    return local.strftime('%m月%d日 %H:%M')


def _session_rows(sessions):
    """课节行（含入会状态文案；控制器侧预格式化）。"""
    rows = []
    for ses in sessions:
        st = ses.join_state()
        rows.append({
            'id': ses.id,
            'subject_id': ses.subject_id.id,
            'when': _fmt_dt(ses.start_datetime),
            'end': _fmt_dt(ses.end_datetime),
            'classroom': ses.classroom_id.name or '',
            'faculty': ses.faculty_id.name or '',
            'has_url': st['has_url'],
            'ready': st['ready'],
            'label': st['label'],
        })
    return rows


def _material_domain(subject_id):
    """资料域：既有四组可见范围 ∪ 第五维「本课程学员」（仅课程资料）。

    复用 controllers/downloads.py 的 _visibility_domain()，不另造可见性；
    只在学生/家长视角把 visible_course 并入同一个 OR（教务处/管理员
    的 _visibility_domain() 返回 [] = 恒可见，保持原口径）。
    """
    vis = list(_visibility_domain())
    if not vis:
        base = []
    else:
        lead = 0
        while lead < len(vis) and vis[lead] == '|':
            lead += 1
        leaves = vis[lead:]
        base = (['|'] * len(leaves) + leaves + [('visible_course', '=', True)]
                if subject_id else vis)
    dom = [('file', '!=', False)] + base
    return [('subject_id', '=', subject_id)] + dom


def _materials_of(subject):
    """该科目的课程资料：edu.download.file[subject_id] ∩ 既有可见范围。"""
    if not subject:
        return request.env['edu.download.file'].sudo()
    return request.env['edu.download.file'].sudo().search(
        _material_domain(subject.id))


def _materials_admin():
    """行政/通用表格（无科目归属），供「相关表格」区。"""
    return request.env['edu.download.file'].sudo().search(
        _material_domain(False), limit=8)


def _subject_teachers(subject, batch_ids):
    dom = [('subject_id', '=', subject.id), ('state', '!=', 'cancel')]
    if batch_ids:
        dom.append(('batch_id', 'in', batch_ids))
    ses = request.env['op.session'].sudo().search(dom)
    out = []
    for fac in ses.mapped('faculty_id'):
        out.append({'name': fac.name or '', 'email': fac.email or '',
                    'id': fac.id})
    return out


def _attendance_stats(student):
    """出勤概况（op.attendance.line 无科目维度，故按学习者整体统计）。"""
    if not student:
        return None
    Line = request.env['op.attendance.line'].sudo()
    domain = [('student_id', '=', student.id)]
    total = Line.search_count(domain)
    if not total:
        # 2026-10-03（沿第 40 轮那处同型问题扫出来的）：「没有考勤记录」不等于「出勤率 0%」。
        # 原样返回 rate=0 会被模板印成「出勤率 0%」—— 一个读起来像**事实判断**的数字。
        # 本仓已有正确先例（batch2.py 首页 mhero 的 'att_pct_txt': '—'）⇒ 这里同样给文本态。
        # 触发面：**刚入学、还没有考勤记录的学生**（演示库里没有这样的学生，
        # 但生产上新生第一周正好是这个状态）。
        return {'total': 0, 'present': 0, 'late': 0, 'absent': 0, 'rate': 0,
                'rate_txt': '—'}
    present = Line.search_count(domain + [('present', '=', True)])
    late = Line.search_count(domain + [('late', '=', True)])
    absent = Line.search_count(domain + [('absent', '=', True)])
    # 2026-10-03（跨页一致性复核）：`present` 与 `late` 是**两个独立布尔**，
    # **迟到那一条的 present 也是 True** ⇒ 原式 `(present + late)` 把迟到**算了两次**。
    # 实测（学生 5）：present 23 ｜ late 1 ｜ total 48 ⇒ 原式 (23+1)/48 = **50%**，
    # 而 /my/home 与 /student/attendance 都是 **48%**（23/48）⇒ 本页是唯一异类。
    # 同一页显示「到堂 23 · 迟到 1 · 缺勤 25 · 合计 48」时，23+1+25=49≠48，用户自己就能看出矛盾。
    # ⇒ 到堂已经含迟到，率就是 present/total；迟到的含义在模板里标成「其中迟到」。
    rate = round(present * 100.0 / total)
    return {'total': total, 'present': present, 'late': late,
            'absent': absent, 'rate': rate,
            'rate_txt': '%d%%' % rate}


def _exam_class_range(exam):
    """班级区间：同一考试的 min/max/avg（供「班级区间」列）。"""
    lines = request.env['op.result.line'].sudo().search(
        [('exam_id', '=', exam.id)])
    marks = [ln.marks for ln in lines if ln.marks is not None]
    if not marks:
        return None
    return {'min': min(marks), 'max': max(marks),
            'avg': round(sum(marks) / float(len(marks)), 1),
            'n': len(marks)}


def _grade_layers(student, subject_ids):
    """成绩三层 + 历史学期折叠。

    L1 本学期总览：每科目 得分/满分/及格线/加权占比/班级区间
    L2 科目条目：单次考试 名称/权重/得分/满分/及格线/是否及格
    L3 单条目反馈：考试备注（教师反馈位）
    """
    env = request.env
    if not student:
        return {'current': [], 'history': [], 'has_any': False}
    mslines = env['op.marksheet.line'].sudo().search(
        [('student_id', '=', student.id)],
        order='generated_date desc, id desc')
    if not mslines:
        return {'current': [], 'history': [], 'has_any': False}

    def build(group_lines):
        buckets = {}
        for ms in group_lines:
            for rl in ms.result_line:
                ex = rl.exam_id
                if not ex or (subject_ids and ex.subject_id.id not in subject_ids):
                    continue
                b = buckets.setdefault(ex.subject_id.id, {
                    'subject': ex.subject_id.name or '',
                    'got': 0, 'total': 0, 'pass_line': 0, 'items': []})
                b['got'] += rl.marks or 0
                b['total'] += ex.total_marks or 0
                b['pass_line'] += ex.min_marks or 0
                b['items'].append({
                    'id': rl.id,
                    'name': ex.name or '',
                    'marks': rl.marks or 0,
                    'total_marks': ex.total_marks or 0,
                    'min_marks': ex.min_marks or 0,
                    'passed': (rl.marks or 0) >= (ex.min_marks or 0),
                    'feedback': (ex.note or '').strip(),
                    'when': _fmt_dt(ex.start_time),
                    'range': _exam_class_range(ex),
                })
        out = []
        for b in buckets.values():
            tot = b['total'] or 0
            for it in b['items']:
                it['weight'] = (round(it['total_marks'] * 100.0 / tot)
                                if tot else 0)
            b['items'].sort(key=lambda x: x['name'])
            b['pct'] = round(b['got'] * 100.0 / tot) if tot else 0
            b['passed'] = b['got'] >= b['pass_line']
            b['item_n'] = len(b['items'])
            # 加权口径：本组及格线占总分的比例（Moodle grade_items.gradepass）
            b['pass_pct'] = (round(b['pass_line'] * 100.0 / tot)
                             if tot else 0)
            out.append(b)
        out.sort(key=lambda x: x['subject'])
        return out

    def _sem_key(ms):
        """学期键：优先 marksheet 登记册；缺登记册的旧数据回落生成年份。

        本库存在 marksheet_reg_id 为空的演示成绩（登记册未生成），
        只按登记册分组会把所有历史都并进本学期 → 用年份兜底。
        """
        if ms.marksheet_reg_id:
            return ('r', ms.marksheet_reg_id.id)
        return ('y', ms.generated_date.year if ms.generated_date else 0)

    cur_key = _sem_key(mslines[0])
    current_lines = mslines.filtered(lambda m: _sem_key(m) == cur_key)
    history_lines = mslines - current_lines
    current = build(current_lines)
    history = build(history_lines)
    reg_first = mslines[0].marksheet_reg_id
    label = (reg_first.name if reg_first and reg_first.name
             else '本学期')
    return {'current': current, 'history': history,
            'has_any': bool(current or history),
            'current_label': label,
            'history_n': len(history)}


def _subject_payload(subject, batch_ids, grades):
    """单科目一页的全部展示数据（纯 dict，模板零逻辑）。"""
    recent, upcoming = _sessions_of(subject, batch_ids)
    mats = _materials_of(subject)
    g = {}
    for bucket in grades['current']:
        if bucket['subject'] == (subject.name or ''):
            g = bucket
            break
    return {
        'subject': subject,
        'teachers': _subject_teachers(subject, batch_ids),
        'recent': _session_rows(recent),
        'upcoming': _session_rows(upcoming),
        'has_session': bool(recent or upcoming),
        'materials': [{
            'id': f.id, 'name': f.name or '',
            'size': f.file_size or 0,
            'downloads': f.download_count or 0,
            'updated': _fmt_dt(f.write_date),
        } for f in mats],
        'material_n': len(mats),
        'grade': g,
    }


# --------------------------------------------------------------------------
# P0：本周课表（只读；课程中心内嵌）
# --------------------------------------------------------------------------
def _week_role_and_domain(user, student, fac, parent):
    """角色 → (role, op.session 域) —— 与 /student/timetable **逐字同口径**。

    口径唯一来源：controllers/scheduling.py:148-171（既有已上线页）。
    分支**顺序**也是口径的一部分（教师身份优先于学生/家长；内部用户全校只读；
    裸门户账号给空表而不是全校数据），照抄不改。
    """
    domain = []
    if fac:
        role = 'faculty'
        domain.append(('faculty_id', '=', fac.id))
    elif student:
        role = 'student'
        _, batch = student_course(student)
        domain.append(('batch_id', '=', batch.id if batch else 0))
    elif parent:
        role = 'parent'
        Scs = request.env['op.student.course'].sudo()
        scs = Scs.search([('student_id', 'in', parent.student_ids.ids),
                          ('state', '=', 'running')])
        if not scs:
            scs = Scs.search([('student_id', 'in', parent.student_ids.ids)])
        domain.append(('batch_id', 'in', scs.mapped('batch_id').ids or [0]))
    elif user.has_group('base.group_user'):
        role = 'staff'
    else:
        # 既非学生/教师/家长、也非内部用户：空表，绝不给全校数据（同 C1）
        role = 'guest'
        domain.append(('id', '=', 0))
    return role, domain


def _learner_batch_names(role, student, parent):
    """学生/家长视角「按哪个班筛的」的班名（行内说明与空态共用同一口径）。"""
    if role == 'student':
        _, batch = student_course(student)
        return [(batch.name or '#%s' % batch.id)] if batch else []
    if role == 'parent':
        Scs = request.env['op.student.course'].sudo()
        scs = Scs.search([('student_id', 'in', parent.student_ids.ids),
                          ('state', '=', 'running')])
        if not scs:
            scs = Scs.search([('student_id', 'in', parent.student_ids.ids)])
        return [n for n in scs.mapped('batch_id').mapped('name') if n]
    return []


def _week_scope_note(role, student, fac, parent):
    """行内说明：这张表**按什么筛的**、以及筛不到的东西（R1 如实呈现）。

    设计 §9 R1：学生课表按**档案班**过滤，而生产有大量课挂在合班批 —— 本页
    不用一个假口径把空缺遮掉：把筛选依据与「合班批不展开」写在行内，
    空表就空表（截图即真实状态）。
    """
    if role == 'student':
        names = '、'.join(_learner_batch_names(role, student, parent))
        return ('只读 · 按你的档案班筛选：%s。与「课表」页显示一致；'
                '合班批（如「B3+B4合班」）与其它班的课节不会出现在这里。'
                % (names or '（未设置档案班，故无课可筛）'))
    if role == 'parent':
        names = '、'.join(_learner_batch_names(role, student, parent))
        kids = '、'.join(n for n in parent.student_ids.mapped('name') if n)
        return ('只读 · 按孩子（%s）的档案班筛选：%s。与「课表」页显示一致；'
                '合班批不展开。'
                % (kids or '未关联学生', names or '（未设置档案班）'))
    if role == 'faculty':
        return ('只读 · 按你任教的课节筛选（任课教师 = %s 本人）。'
                '与「课表」页显示一致。' % (fac.name or '你'))
    if role == 'staff':
        return '只读 · 全校视图：本周全校所有已排课节（含各班）。'
    return ('只读 · 当前账号没有学生 / 教师 / 家长档案，按既定规则不展示任何课节。')


def _week_empty_hint(role, student, parent):
    """空态文案：**说清是「本账号的数据域本周本来就没课」，不是加载失败**。

    本仓既有教训是「静默失败要按缺陷处理」：空表必须与「取数失败」在语言上
    不同形，且要说出筛的是什么，用户才知道该去找教务还是该等排课。
    """
    if role == 'student':
        names = '、'.join(_learner_batch_names(role, student, parent))
        return ('本周暂无排课：你的档案班%s在本周没有任何课节记录'
                '（这是本页的筛选结果，不是加载失败）。'
                % ('「%s」' % names if names else '（未设置）'))
    if role == 'parent':
        names = '、'.join(_learner_batch_names(role, student, parent))
        return ('本周暂无排课：孩子的档案班%s在本周没有任何课节记录。'
                % ('「%s」' % names if names else '（未设置）'))
    if role == 'faculty':
        return '本周暂无排课：本周没有以你为任课教师的课节。'
    if role == 'staff':
        return '本周暂无排课：全校本周没有任何已排课节。'
    return '本周暂无排课：当前账号没有学生 / 教师 / 家长档案。'


def _week_holiday_map(batch_ids, monday):
    """本周 7 天的停课标注 {iso: 停课名}；判定复用 holiday._matches（同 C1）。"""
    holidays = request.env['edu.schedule.holiday'].sudo().search(
        [('active', '=', True)])
    out = {}
    for i in range(7):
        day = monday + timedelta(days=i)
        for h in holidays:
            if any(h._matches(day, bch) for bch in batch_ids):
                out[day.isoformat()] = h.name or '停课'
                break
    return out


def _week_schedule(user, student, fac, parent, viewable_subject_ids):
    """本周（自然周）只读课表 payload；模板零逻辑。

    viewable_subject_ids：当前身份**打得开**的科目 id（= _subjects_for 的结果）。
    只给打得开的科目加链接 —— 否则学生点自己班课表里一门没报的科目会被
    /my/study/<id> 的既有守卫弹回课程中心（那是「报课 ≠ 课表」既有断点的表现，
    不是本页该制造的第二个死链）。

    周窗口 = week_utils（monday_of / week_window_utc / term_anchor / week_no_of），
    与 /student/timetable、周期排课、校历同一份口径（S5）。
    课节按**起始时刻的星期**归入周一…周日，与 C1 的矩阵同一归桶方式
    （跨周零点的课也不丢、不另起一套）。
    """
    env = request.env
    role, domain = _week_role_and_domain(user, student, fac, parent)
    today_local = fields.Datetime.context_timestamp(
        user, fields.Datetime.now()).date()
    monday = monday_of(today_local)
    win_start, win_end = _week_window_utc(monday)

    fulldomain = [
        ('state', '!=', 'cancel'),                       # 停用课节不可见（同 C1）
        ('start_datetime', '<', fields.Datetime.to_string(win_end)),
        ('end_datetime', '>=', fields.Datetime.to_string(win_start)),
    ] + domain
    sessions = env['op.session'].sudo().search(
        fulldomain, order='start_datetime asc')

    buckets = {i: [] for i in range(7)}
    show_faculty = role != 'faculty'      # 教师看自己的教学安排：不重复显示本人
    show_batch = role == 'staff'          # 全校视图才需要知道是哪个班
    for ses in sessions:
        loc = _local_dt(ses.start_datetime)
        idx = loc.weekday() if loc else 0
        loc_end = _local_dt(ses.end_datetime)
        meta = []
        if show_faculty and ses.faculty_id.name:
            meta.append(ses.faculty_id.name)
        if show_batch and ses.batch_id.name:
            meta.append(ses.batch_id.name)
        if ses.classroom_id.name:
            meta.append(ses.classroom_id.name)
        sid = ses.subject_id.id
        buckets[idx].append({
            'id': ses.id,
            'subject_id': sid,
            'href': ('/my/study/%d' % sid) if sid in viewable_subject_ids else '',
            'subject': ses.subject_id.name or '',
            'start': loc.strftime('%H:%M') if loc else '',
            'end': loc_end.strftime('%H:%M') if loc_end else '',
            'meta': (' · ' + ' · '.join(meta)) if meta else '',
        })

    holiday_map = _week_holiday_map(
        _role_batch_context(role, student, fac, parent), monday)
    today_iso = today_local.isoformat()
    days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        rows = buckets[i]
        days.append({
            'iso': d.isoformat(),
            'label': '%s %d月%d日' % (DAY_NAMES[i], d.month, d.day),
            'today': d.isoformat() == today_iso,
            'holiday': holiday_map.get(d.isoformat(), ''),
            'sessions': rows,
            'n': len(rows),
        })

    sunday = monday + timedelta(days=6)
    week_label = '%d月%d日 – %d月%d日（本周）' % (
        monday.month, monday.day, sunday.month, sunday.day)
    week_no = week_no_of(monday, term_anchor(env, monday))
    total = sum(d['n'] for d in days)
    return {
        'role': role,
        'title': {'student': '我的课表', 'faculty': '我的教学安排',
                  'parent': '孩子的课表', 'staff': '全校课表（只读）',
                  'guest': '课表'}.get(role, '课表'),
        'scope_note': _week_scope_note(role, student, fac, parent),
        'week_label': week_label,
        'week_no_label': ('第 %d 周' % week_no) if week_no else '',
        'days': days,
        'total': total,
        'empty_hint': _week_empty_hint(role, student, parent),
        'timetable_href': FULL_TIMETABLE_HREF,
        'calendar_href': CALENDAR_HREF,
    }


class EduStudyPortal(http.Controller):

    # ------------------------- 课程中心 -------------------------
    @http.route('/my/study', type='http', auth='user', website=True)
    def my_study(self, **kw):
        env = request.env
        student = current_student()
        fac = current_faculty()
        parent = current_parent()
        subjects, role = _subjects_for(student, fac, parent, env.user)
        batch_ids, _course_ids = _role_batch_course(student, parent)

        learner = student or (parent.student_ids[:1] if parent else None)
        grades = _grade_layers(learner, [s.id for s in subjects])
        att = _attendance_stats(learner)

        cards = []
        for sub in subjects:
            recent, upcoming = _sessions_of(sub, batch_ids)
            mats = _materials_of(sub)
            bucket = {}
            for b in grades['current']:
                if b['subject'] == (sub.name or ''):
                    bucket = b
                    break
            nxt = upcoming[:1]
            cards.append({
                'id': sub.id,
                'name': sub.name or '',
                'code': sub.code or '',
                'teachers': _subject_teachers(sub, batch_ids),
                'next_when': _fmt_dt(nxt[0].start_datetime) if nxt else '',
                'next_ready': nxt[0].join_state()['ready'] if nxt else False,
                'next_label': nxt[0].join_state()['label'] if nxt else '暂无排课',
                'recent_n': len(recent),
                'material_n': len(mats),
                'pct': bucket.get('pct', 0),
                'passed': bucket.get('passed', False),
                'has_grade': bool(bucket),
            })
        return request.render('edu_portal.edu_study_home', {
            'title': '课程中心',
            'page_name': 'study',
            'role': role,
            # P0：本周课表（只读装配；见 _week_schedule 的口径来源说明）
            'week': _week_schedule(env.user, student, fac, parent,
                                   {s.id for s in subjects}),
            'cards': cards,
            'subject_n': len(cards),
            'attendance': att,
            'tables': [{'id': f.id, 'name': f.name or ''}
                       for f in _materials_admin()],
            'grades': grades,
        })

    # ------------------------- 单科目一页 -------------------------
    @http.route('/my/study/<int:subject_id>', type='http', auth='user',
                website=True)
    def study_subject(self, subject_id, **kw):
        env = request.env
        student = current_student()
        fac = current_faculty()
        parent = current_parent()
        subjects, role = _subjects_for(student, fac, parent, env.user)
        subject = env['op.subject'].sudo().browse(subject_id)
        if not subject.exists() or subject not in subjects:
            return request.redirect('/my/study')
        batch_ids, _course_ids = _role_batch_course(student, parent)
        learner = student or (parent.student_ids[:1] if parent else None)
        grades = _grade_layers(learner, [subject.id])
        payload = _subject_payload(subject, batch_ids, grades)
        payload.update({
            'title': subject.name or '科目',
            'page_name': 'study_subject',
            'role': role,
            'can_edit_link': bool(fac or privileged_staff()),
            'attendance': _attendance_stats(learner),
            'tables': [{'id': f.id, 'name': f.name or ''}
                       for f in _materials_admin()],
            'grades': grades,
        })
        return request.render('edu_portal.edu_study_subject', payload)

    # ------------------------- 一键入会 -------------------------
    @http.route('/my/study/session/<int:session_id>/join', type='http',
                auth='user', website=True)
    def session_join(self, session_id, **kw):
        env = request.env
        ses = env['op.session'].sudo().browse(session_id)
        if not ses.exists():
            return request.redirect('/my/study')
        # 可见域：学生/家长只能进本班课节，防拼 URL
        student = current_student()
        parent = current_parent()
        batch_ids, _c = _role_batch_course(student, parent)
        if (student or parent) and batch_ids \
                and ses.batch_id.id not in batch_ids:
            return request.redirect('/my/study')
        st = ses.join_state()
        if not st['ready'] or not st['url']:
            return request.render('edu_portal.edu_study_join_wait', {
                'title': '等待入会',
                'page_name': 'study',
                'session': ses,
                'label': st['label'],
                'subject_id': ses.subject_id.id,
            })
        return request.redirect(st['url'], local=False)

    # ------------------------- 设置课节链接（教师/教务） ------------------
    @http.route('/my/study/session/<int:session_id>/link/save', type='http',
                auth='user', methods=['POST'], website=True, csrf=True)
    def session_link_save(self, session_id, **post):
        fac = current_faculty()
        if not (fac or privileged_staff()):
            return request.redirect('/my/study')
        ses = request.env['op.session'].sudo().browse(session_id)
        if not ses.exists():
            return request.redirect('/my/study')
        ses.set_meeting_url(post.get('meeting_url') or '')
        return request.redirect('/my/study/%d' % ses.subject_id.id)
