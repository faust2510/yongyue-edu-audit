# -*- coding: utf-8 -*-
"""学生自主报课 + 教务审批 —— 门户控制器（第 2 期）。

设计：docs/plans/enroll-v2-design.md。

路由（全部新路径，无冲突）：
- GET  /subject/enroll                 报课目录页（课程/班级/科目三级选择）
- POST /subject/enroll/save            提交注册单（state=submitted）
- GET  /subject/registration           学生「我的申请」列表（batch3.py 已实现，
                                        本文件不改它；新报课入口在视图层加入）
- GET  /registrar/subject/approvals    教务审批聚合列表（chips + 搜索 + 分页）
- GET  /registrar/subject/approvals/<int:rid>   审批详情
- POST /registrar/subject/approvals/<int:rid>/set_state  通过/驳回

权限口径（对齐 roles.py 审批先例）：
- 学生侧门禁：current_student() 判空，非学生回 /my/home；
- 教务侧门禁：current_faculty() or privileged_staff()，否则回 /my/home。
所有读走 sudo()（门户既有惯例），写操作由控制器判角色把关。
"""
import logging
from datetime import datetime, time
from urllib.parse import quote as _quote

from odoo import fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.addons.portal.controllers.portal import pager

from .main import current_student, student_course
from .roles import current_faculty, privileged_staff, scoped_records

_SUBJREG_STATE_LABEL = {
    'draft': '草稿', 'submitted': '已提交',
    'approved': '已批准', 'rejected': '已驳回',
}
_SUBJECT_TYPE_LABEL = {'compulsory': '必修', 'elective': '选修'}
_logger = logging.getLogger(__name__)
_PAGE_SIZE = 20

# ---------------------------------------------------------------------------
# G1「先排课后报课」：三档系统参数 + (班级, 学期) 排课聚合
#   设计：docs/plans/scheduling-overhaul-design.md §7.2 / §7.3 / §7.4 / §7.5
#   参数键 edu.enroll.pool_mode；三档语义：
#     off      = 零回归开关：池全列、无标注、无服务端闸门（一字回到改造前）
#     annotate = 池全列；每张卡按 (班级, 学期) 判「已排课」，未排课的科目
#                追加一条既有 F6 blocker（红字 + 自动 disabled）
#     strict   = 只列「已排课 ∪ 已批准单内」的科目；空目录给专门空态文案
#   默认值 annotate 写在**读取侧**（不落库、不动 data/timetable_params.xml ——
#   该文件不在本轮改动边界内）；越界值一律回退 annotate，不抛错。
# ---------------------------------------------------------------------------
POOL_MODE_KEY = 'edu.enroll.pool_mode'
POOL_MODES = ('off', 'annotate', 'strict')
POOL_MODE_DEFAULT = 'annotate'
# 未排课原因文案：**append 进既有 blockers**，故与 F6 其它原因同形（不带科目名前缀，
# 前缀由模板 / 服务端拼「科目名：原因」）
NO_SESSION_REASON = '本学期未排课'
# 必修未排课阻断文案（§7.4：红字必须可行动）
COMPULSORY_NO_SESSION_MSG = (
    '本课程有 %d 门必修本学期尚未排课，暂不能提交报课。请联系教务处确认开课安排。')
# strict 空目录专门文案（§7.2-③；禁止沿用「该专业暂未配置科目目录」——
# 那句会把「没排课」说成「没配课」，把责任推给专业配置）
STRICT_EMPTY_MSG = '本学期课表尚未发布，报课暂未开放；请联系教务处。'


def edu_pool_mode(env):
    """报课池模式（越界值 / 未设置 → 默认 annotate）。

    **直读 ir_config_parameter 表**，不走 get_param：get_param 带
    @ormcache('key', cache='stable')，参数改了只有「处理该请求的那个 worker」
    清缓存，其余 worker 继续读旧值直到重启/升级（本仓实测记录见
    models/course_rep.py:71-90 的 _raw_param）。档位是教务在网页上改、
    必须**立刻**对报课页生效的开关，所以这里取新鲜值。
    读失败（表还没建等）一律回落默认值，不炸页面。
    """
    raw = ''
    try:
        env.cr.execute(
            'SELECT value FROM ir_config_parameter WHERE key = %s',
            (POOL_MODE_KEY,))
        row = env.cr.fetchone()
        raw = str(row[0]).strip() if row and row[0] is not None else ''
    except Exception:
        _logger.warning('read param %s failed', POOL_MODE_KEY, exc_info=True)
        return POOL_MODE_DEFAULT
    return raw if raw in POOL_MODES else POOL_MODE_DEFAULT


def edu_term_of_student(env, student):
    """学生**当前学期**（op.academic.term）；取不到返回空 recordset。

    口径（§7.3）：学生 running 档案的 academic_term_id；
    档案没有学期时按「今天落在 term 起止区间内」兜底
    （生产 term：1 = 2026-06-23~2026-12-20、2 = 2026-12-21~2027-06-18）。
    """
    Term = env['op.academic.term'].sudo()
    if not student:
        return Term.browse()
    sc = env['op.student.course'].sudo().search(
        [('student_id', '=', student.id), ('state', '=', 'running')],
        order='id desc', limit=1)
    if sc and sc.academic_term_id:
        return sc.academic_term_id
    today = fields.Date.today()
    return Term.search([('term_start_date', '<=', today),
                        ('term_end_date', '>=', today)],
                       order='term_start_date desc', limit=1)


def edu_term_window(term):
    """学期 → (UTC 朴素下界字符串, 上界字符串)；学期不完整 → (None, None)。"""
    if not term or not term.exists() \
            or not term.term_start_date or not term.term_end_date:
        return None, None
    lo = fields.Datetime.to_string(
        datetime.combine(term.term_start_date, time.min))
    hi = fields.Datetime.to_string(
        datetime.combine(term.term_end_date, time.max).replace(microsecond=0))
    return lo, hi


def edu_scheduled_subjects(env, batch, term):
    """(班级, 学期) **已排课**科目聚合 —— 全页只此一次 _read_group，无 N+1。

    域（§7.3）：batch_id = 该班 ∧ subject_id 非空 ∧ state != 'cancel' ∧
                active（不计已归档课节）∧ start_datetime ∈ 学期窗口。
    返回 {subject_id: {'n': 节数, 'first': 首节, 'last': 末节}}（无排课返回 {}）。
    """
    if not batch or not batch.exists():
        return {}
    lo, hi = edu_term_window(term)
    if not lo:
        return {}
    domain = [('batch_id', '=', batch.id),
              ('subject_id', '!=', False),
              ('state', '!=', 'cancel'),
              ('active', '=', True),
              ('start_datetime', '>=', lo),
              ('start_datetime', '<=', hi)]
    out = {}
    for subject, cnt, first, last in env['op.session'].sudo()._read_group(
            domain, ['subject_id'],
            ['__count', 'start_datetime:min', 'start_datetime:max']):
        if not subject:
            continue
        out[subject.id] = {'n': cnt, 'first': first, 'last': last}
    return out


def edu_short_day(env, dt_utc):
    """UTC 朴素时刻 → 用户时区的「M/D」短文案（供「首节 9/7」）。"""
    if not dt_utc:
        return ''
    try:
        local = fields.Datetime.context_timestamp(
            env['res.users'].browse(env.uid), dt_utc)
        return '%d/%d' % (local.month, local.day)
    except Exception:
        return ''


def _fmt_dt(rec, dt):
    """时间格式化（中文门户惯例）。

    - rec：记录（用于取其宿主环境与时区）；dt：datetime 或 False。
    - 对齐 roles.py 先例：用 fields.Datetime.context_timestamp(rec, dt)
      把 UTC naive 转注册对象时区后再 strftime（rec 为 recordset）。
    """
    if not dt:
        return ''
    try:
        local_dt = fields.Datetime.context_timestamp(rec, dt)
        return local_dt.strftime('%Y/%m/%d %H:%M')
    except Exception:
        return ''


def _ccr_source(rec):
    """换班/换课单的**来源档案**（只读展示用；取不到返回空 recordset）。

    零新字段口径：来源 = 该生唯一一条 running 档案（同审批动作
    registration.py::_ccr_source_archive 的判据）。多档案/无档案 → 不猜，
    返回空让页面显示「—」并由审批动作给出人话拒绝。
    """
    if not rec.student_id:
        return rec.env['op.student.course'].sudo().browse()
    scs = rec.env['op.student.course'].sudo().search([
        ('student_id', '=', rec.student_id.id),
        ('state', '=', 'running')])
    return scs if len(scs) == 1 else rec.env['op.student.course'].sudo().browse()


class EduEnrollPortal(http.Controller):

    # ------------------------------------------------------------------
    # 学生端：报课目录页
    # ------------------------------------------------------------------
    @http.route('/subject/enroll', type='http', auth='user', website=True)
    def enroll_catalog(self, **kw):
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        env = request.env
        course, batch = student_course(student)

        # 在读档案摘要（页首展示）
        scs = env['op.student.course'].sudo().search(
            [('student_id', '=', student.id),
             ('state', '=', 'running')], order='id desc', limit=1)
        summary = None
        if scs:
            summary = {
                'course': scs.course_id.name or '',
                'course_code': scs.course_id.code or '',
                # 学生侧显示学制（校长拍板 P5：教务标了学制，学生要看得见）
                'level': scs.course_id.edu_level_id.name or '',
                'batch': scs.batch_id.name or '—',
                'term': scs.academic_term_id.name or '',
                'subjects': len(scs.subject_ids),
            }

        # 课程目录：active 课程（在读课程+同 program 兄弟课程也都在 active 内）
        courses = env['op.course'].sudo().search(
            [('active', '=', True)], order='name')
        course_list = [{
            'id': c.id,
            'name': c.name or '',
            'code': c.code or '',
            'program': c.program_id.name or '',
            # 学制：学生侧一并显示（校长拍板 P5），改完即随专业卡片出现
            'level': c.edu_level_id.name or '',
            'subject_n': len(c.subject_ids),
            'current': c.id == (course.id if course else 0),
        } for c in courses]

        # 课程 → 班级（未结束的班级）
        batch_map = {}
        if courses:
            batches = env['op.batch'].sudo().search([
                ('course_id', 'in', courses.ids),
                ('active', '=', True)])
            for b in batches:
                batch_map.setdefault(b.course_id.id, []).append({
                    'id': b.id,
                    'name': b.name or '',
                    'code': b.code or '',
                    'end_date': b.end_date.strftime('%Y/%m/%d')
                                if b.end_date else '',
                    'session_n': env['op.session'].sudo().search_count(
                        [('batch_id', '=', b.id)]),
                })
        for cid in batch_map:
            batch_map[cid].sort(key=lambda x: x['name'])

        # 默认选中：在读课程+班级；科目池随 batch 预载
        sel_course = course
        sel_batch = batch
        if kw.get('course_id'):
            try:
                sel_course = env['op.course'].sudo().browse(
                    int(kw.get('course_id') or 0))
            except (TypeError, ValueError):
                sel_course = course
        if kw.get('batch_id'):
            try:
                sel_batch = env['op.batch'].sudo().browse(
                    int(kw.get('batch_id') or 0))
            except (TypeError, ValueError):
                sel_batch = batch

        # 科目池 = 专业（op.course）subject_ids；必修/选修 = **两级 fallback**
        # （专业里配了就按专业的，没配就继承科目自身 —— 设计 §6.5 / §5.5 学制不参与判定）。
        # ⚠ 必修/选修三个键（type / type_label / compulsory）一律取自模型层 helper，
        # 与下方 /subject/enroll/save 的「服务端必修全量补齐」**同源**，
        # 否则会出现「页面显示选修、服务端按必修补齐」的自相矛盾。
        subjects = []
        blocked_n = 0
        no_session_n = 0
        scheduled_n = 0
        # G1：模式 + 一次 (班级, 学期) 排课聚合（off 档不查、不标注 = 零回归）
        pool_mode = edu_pool_mode(env)
        term = edu_term_of_student(env, student) if student \
            else env['op.academic.term'].sudo().browse()
        sched = edu_scheduled_subjects(env, sel_batch, term) \
            if pool_mode != 'off' else {}
        if sel_course and sel_course.exists():
            pool = sel_course.subject_ids.sudo().filtered(
                lambda s: s.active)
            if pool_mode == 'strict' and sel_batch and sel_batch.exists():
                # strict（§7.2-②）：只列「已排课 ∪ 已批准单内」的科目；
                # 已批准过但本学期尚未排课的不静默删掉（否则学生看不到自己已有的课）
                keep = set(sched)
                if student:
                    keep |= set(env['op.subject.registration'].sudo().search([
                        ('student_id', '=', student.id),
                        ('course_id', '=', sel_course.id),
                        ('batch_id', '=', sel_batch.id),
                        ('state', '=', 'approved')])._subject_payload())
                pool = pool.filtered(lambda s: s.id in keep)
            # 口径来源：一次取全部行（避免 N+1），键为 subject id
            rows = {r['id']: r for r in sel_course.sudo().edu_subject_pool()}
            # F6：先修 / 学分 / 容量 前置校验（先例见 docs/research §4.3）
            Pre = env['edu.subject.prereq'].sudo()
            precheck = Pre.edu_precheck(student, pool.ids) if student else {}
            for s in pool:
                blockers = list(precheck.get(s.id) or [])
                sched_row = sched.get(s.id)
                if sched_row:
                    scheduled_n += 1
                elif pool_mode != 'off':
                    # §7.4：不另造提示体系 —— 「本学期未排课」就是既有 blockers 里的一条，
                    # 置 blocked=True ⇒ 模板红字 + 自动 disabled，零额外视图改动。
                    # 插到队首：模板只渲染 blockers[0]，未排课是最需要先看到的原因。
                    blockers.insert(0, NO_SESSION_REASON)
                    no_session_n += 1
                if blockers:
                    blocked_n += 1
                row = dict(rows.get(s.id) or {})
                # 兜底（helper 里查不到该科目时，按科目全局值判，绝不静默丢课）
                if not row.get('type_key'):
                    t = s.subject_type or 'compulsory'
                    row.update({
                        'id': s.id, 'name': s.name or '', 'code': s.code or '',
                        'type': _SUBJECT_TYPE_LABEL.get(t, t),
                        'type_key': t,
                        'type_label': _SUBJECT_TYPE_LABEL.get(t, t),
                        'compulsory': t == 'compulsory',
                    })
                row.update({
                    'credit': s.credit_points or 0,
                    'capacity': s.capacity or 0,
                    'enrolled': Pre._edu_enrolled_count(s)
                                if s.capacity else 0,
                    'blockers': blockers,
                    'blocked': bool(blockers),
                    # §7.2-①：已排课一栏（「已排课 N 节 · 首节 9/7」）
                    'session_n': sched_row['n'] if sched_row else 0,
                    'first_label': edu_short_day(env, sched_row['first'])
                                   if sched_row else '',
                })
                row.pop('subject', None)   # 模板只读 dict，不传 recordset
                subjects.append(row)
            subjects.sort(key=lambda x: (not x['compulsory'], x['name']))
        compulsory_n = sum(1 for s in subjects if s['compulsory'])
        elective_n = len(subjects) - compulsory_n

        # 同 (course,batch) 已批过？→ 黄条提示
        already_approved = False
        if student and sel_course and sel_course.exists() and sel_batch \
                and sel_batch.exists():
            already_approved = bool(env['op.subject.registration'].sudo()
                                    .search_count([
                                        ('student_id', '=', student.id),
                                        ('course_id', '=', sel_course.id),
                                        ('batch_id', '=', sel_batch.id),
                                        ('state', '=', 'approved')]))

        # 页首横幅：成功 / 错误提示
        box = kw.get('box') or ''

        # G1（§7.2）：报课截止从「展示项」升级为**真闸门** —— 与模板同口径
        # （截止日当天仍算窗口内 ⇒ 判据是「今天 > 截止日」，字符串同格式可直接比）。
        deadline_raw = env['edu.deadline'].sudo().get_raw('edu.enroll.deadline')
        enroll_overdue = bool(deadline_raw) \
            and fields.Date.today().isoformat() > deadline_raw
        # 提交闸门（前端先行提示；服务端同一判据在 enroll_save 复算，硬拦）
        submit_blocked = pool_mode != 'off' and (enroll_overdue
                                                or not scheduled_n)

        return request.render('edu_portal.edu_enroll_catalog', {
            'title': '报课选科',
            # t88：报课截止（与班级 end_date 是两回事，页面上分开展示）
            'enroll_deadline_cn': request.env['edu.deadline'].sudo().get_cn(
                'edu.enroll.deadline'),
            'page_name': 'subject_enroll',
            'student': student,
            'summary': summary,
            'courses': course_list,
            'batch_map': batch_map,
            'subjects': subjects,
            'compulsory_n': compulsory_n,
            'elective_n': elective_n,
            'sel_course_id': sel_course.id if sel_course else 0,
            'sel_batch_id': sel_batch.id if sel_batch else 0,
            'already_approved': already_approved,
            'box': box,
            'blocked_n': blocked_n,
            # G1：模式 / 学期 / 未排课统计 / 提交闸门（模板只读，不再回算）
            'pool_mode': pool_mode,
            'term_label': term.name or '',
            'no_session_n': no_session_n,
            'submit_blocked': submit_blocked,
            # 必修未排课阻断回传的条数（服务端闸门 → 页面红字，§7.4）
            'comp_block_n': int(kw.get('n') or 0),
            'max_credits': env['edu.subject.prereq'].sudo()._edu_max_credits(),
            'precheck_msg': kw.get('precheck_msg') or '',
        })

    # ------------------------------------------------------------------
    # 学生端：提交注册单
    # ------------------------------------------------------------------
    @http.route('/subject/enroll/save', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def enroll_save(self, **post):
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        env = request.env
        # 统一从 werkzeug 表单取参：getlist 拿全量同名多值（多选 checkbox）。
        form = request.httprequest.form
        try:
            course_id = int(form.get('course_id') or 0)
            batch_id = int(form.get('batch_id') or 0)
        except (TypeError, ValueError):
            course_id = batch_id = 0
        course = env['op.course'].sudo().browse(course_id)
        batch = env['op.batch'].sudo().browse(batch_id)
        if not course.exists() or not batch.exists() \
                or batch.course_id.id != course.id:
            return request.redirect('/subject/enroll?box=error')
        pool = course.subject_ids.sudo().filtered(lambda s: s.active)

        # 必修：全量自动带（防绕过，服务端补齐）—— 与报课页**同源**：
        # 都走模型层 edu_compulsory_subject_ids()（专业级优先、全局兜底）
        compulsory_ids = course.sudo().edu_compulsory_subject_ids()
        # 选修：getlist 取全量多值；兼容旧表单逗号串（末值覆盖场景）
        raw_elec = form.getlist('elective_subject_ids')
        if not raw_elec and form.get('elective_subject_ids'):
            raw_elec = [form.get('elective_subject_ids')]
        posted_elec = []
        for chunk in raw_elec:
            for x in str(chunk).split(','):
                try:
                    posted_elec.append(int(x.strip()))
                except (TypeError, ValueError):
                    continue
        pool_ids = set(pool.ids)
        elective_ids = sorted(
            set(x for x in posted_elec if x in pool_ids))
        # ── G1 服务端闸门（§7.2-③ / §7.4）：比前端 disabled 更硬，绕过前端也必须拦 ──
        # 非 off 档才生效；off = 零回归开关（一字回到改造前行为）。
        pool_mode = edu_pool_mode(env)
        _back = '/subject/enroll?course_id=%d&batch_id=%d' % (course.id,
                                                              batch.id)
        if pool_mode != 'off':
            # ① 报课截止：从页面上「写着的日期」升级为真闸门（过了就一律不受理）
            deadline_raw = env['edu.deadline'].sudo().get_raw(
                'edu.enroll.deadline')
            if deadline_raw \
                    and fields.Date.today().isoformat() > deadline_raw:
                return request.redirect('%s&box=overdue' % _back)
            term = edu_term_of_student(env, student)
            sched = edu_scheduled_subjects(env, batch, term)
            # ② 必修同口径（必须改）：未排课的必修**不进 payload、且阻断提交** ——
            #    必修为「全量自动带」，不带排课口径就会继续生成「批了也没课」的单。
            no_sched_comp = [sid for sid in compulsory_ids
                             if sid not in sched]
            if no_sched_comp:
                return request.redirect(
                    '%s&box=compulsory_no_session&n=%d'
                    % (_back, len(no_sched_comp)))
            # ③ 所选科目**全部**未排课 ⇒ 直接拒绝（前端可 disabled，服务端是底线）
            chosen = set(compulsory_ids) | set(elective_ids)
            if chosen and not (chosen & set(sched)):
                return request.redirect('%s&box=all_no_session' % _back)
        # 课程全为选修（无必修）时，必须至少勾选 1 门，否则无意义空单
        if not compulsory_ids and not elective_ids:
            return request.redirect('/subject/enroll?box=no_subject'
                                    + ('&course_id=%d&batch_id=%d'
                                       % (course.id, batch.id)
                                       if course_id and batch_id else ''))
        # 已批准课程禁止再投同档案（submitted 可重复投，教务取最新）
        dup_approved = env['op.subject.registration'].sudo().search_count([
            ('student_id', '=', student.id),
            ('course_id', '=', course.id),
            ('batch_id', '=', batch.id),
            ('state', '=', 'approved')])
        if dup_approved:
            return request.redirect('/subject/enroll?box=duplicated')
        # F6：先修 / 学分 / 容量 前置校验（拦截并回报具体原因，整体不落库）
        chosen_ids = sorted(set(compulsory_ids) | set(elective_ids))
        precheck = env['edu.subject.prereq'].sudo().edu_precheck(
            student, chosen_ids)
        blockers = []
        for subject in env['op.subject'].sudo().browse(chosen_ids):
            for reason in precheck.get(subject.id) or []:
                blockers.append('%s：%s' % (subject.name or '—', reason))
        if blockers:
            from urllib.parse import quote as _quote
            return request.redirect(
                '/subject/enroll?box=precheck&course_id=%d&batch_id=%d'
                '&precheck_msg=%s' % (course.id, batch.id,
                                      _quote('；'.join(blockers[:6]))))
        # unit load 上限（course.max_unit_load>0 且科目有 weightage 才校验）
        max_unit = (course.max_unit_load or 0)
        if max_unit > 0:
            chosen = pool.filtered(
                lambda s: s.id in set(compulsory_ids) | set(elective_ids))
            total_unit = sum(chosen.mapped('grade_weightage') or [0])
            if total_unit > max_unit:
                return request.redirect(
                    '/subject/enroll?box=unit_over&course_id=%d&batch_id=%d'
                    % (course.id, batch.id))
        reg = env['op.subject.registration'].sudo().create({
            'student_id': student.id,
            'course_id': course.id,
            'batch_id': batch.id,
            'compulsory_subject_ids': [(6, 0, compulsory_ids)],
            'elective_subject_ids': [(6, 0, elective_ids)],
            'applicant_note': (form.get('applicant_note') or '').strip()[:500],
            'state': 'submitted',
            'submitted_at': fields.Datetime.now(),
            # 报课类型：与 /course/change/request 换课单区分
            'doc_type': 'subject_registration',
        })
        if not reg.name or reg.name in ('New', '/'):
            reg.name = 'SR%05d' % reg.id
        env['edu.audit.log'].sudo()._log(
            '报课提交', 'op.subject.registration', reg.id, reg.name or '',
            '学生 %s · 课程 %s · 班级 %s · 必修 %d 选修 %d'
            % (student.name or '', course.name or '', batch.name or '',
               len(compulsory_ids), len(elective_ids)))
        return request.redirect(
            '/subject/registration?box=submitted&new_id=%d' % reg.id)

    # ------------------------------------------------------------------
    # 学生端：我的已选科目（横卡摘要）
    # ------------------------------------------------------------------
    @http.route('/student/subjects', type='http', auth='user', website=True)
    def my_subjects(self, **kw):
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        env = request.env
        scs = env['op.student.course'].sudo().search([
            ('student_id', '=', student.id)], order='id desc')
        cards = []
        for sc in scs:
            cards.append({
                'course': sc.course_id.name or '',
                'batch': sc.batch_id.name or '—',
                'state': '在读' if sc.state == 'running' else '已结业',
                'state_raw': sc.state or '',
                'subjects': sc.subject_ids.sorted(key=lambda s: s.name),
                'subject_n': len(sc.subject_ids),
            })
        return request.render('edu_portal.edu_student_subjects', {
            'title': '我的已选科目',
            'page_name': 'student_subjects',
            'cards': cards,
            'has_records': bool(cards),
        })

    # ------------------------------------------------------------------
    # 教务侧：审批聚合列表
    # ------------------------------------------------------------------
    @http.route('/registrar/subject/approvals', type='http', auth='user',
                website=True)
    def approvals(self, **kw):
        fac = current_faculty()
        is_priv = privileged_staff()
        if not fac and not is_priv:
            return request.redirect('/my/home')
        Reg = request.env['op.subject.registration'].sudo()
        filterby = kw.get('filterby') or 'pending'
        search = (kw.get('search') or '').strip()
        page = max(1, int(kw.get('page', 1) or 1))
        # 2026-09-18 解禁（设计 §19.1 载体裁定 v2）：旧代码把
        # doc_type='course_change'（换班/换课＝归属变更单）**硬排除**在审批队列外，
        # 导致该类单从未被批过（该注释原文「教务另有换课流程」在本仓查无实据）。
        # 现口径：教务 + 超管可见「选课单 + 变更单」；教师仍只见选课单
        # （换班改的是学籍归属，属业务管理层 —— 设计 §9/§10.3 的可见矩阵）。
        scope = [] if is_priv else [('doc_type', '=', 'subject_registration')]
        domain = list(scope)
        if filterby == 'change':
            domain.append(('doc_type', '=', 'course_change'))
            domain.append(('state', '=', 'submitted'))
        elif filterby == 'pending':
            domain.append(('state', '=', 'submitted'))
        elif filterby in ('approved', 'rejected'):
            domain.append(('state', '=', filterby))
        if search:
            domain += ['|', '|',
                       ('name', 'ilike', search),
                       ('student_id.name', 'ilike', search),
                       ('course_id.name', 'ilike', search)]
        total = Reg.search_count(domain)
        regs = Reg.search(domain, order='id desc', limit=_PAGE_SIZE,
                          offset=(page - 1) * _PAGE_SIZE)
        # 统计与列表**同一可见集**（否则教师会看到自己点不开的数字）
        all_regs = Reg.search(scope)
        stats = {
            'pending': sum(1 for r in all_regs if r.state == 'submitted'),
            'approved': sum(1 for r in all_regs if r.state == 'approved'),
            'rejected': sum(1 for r in all_regs if r.state == 'rejected'),
            'all': len(all_regs),
            'change': sum(1 for r in all_regs
                          if r.doc_type == 'course_change'
                          and r.state == 'submitted'),
        }
        items = []
        for r in regs:
            is_change = r.doc_type == 'course_change'
            old_label = ''
            if is_change:
                sc = _ccr_source(r)
                if sc:
                    old_label = '%s · %s' % (sc.course_id.name or '—',
                                             sc.batch_id.name or '—')
            items.append({
                'reg': r,
                'is_change': is_change,
                'kind_label': '变更' if is_change else '选课',
                'old_label': old_label,
                'target_label': '%s · %s' % (
                    r.course_id.name or '—', r.batch_id.name or '—'),
                'state_label': _SUBJREG_STATE_LABEL.get(r.state, r.state),
                'submitted_at': _fmt_dt(r, r.submitted_at or r.create_date),
                'subjects_n': len(r._subject_payload()),
            })
        return request.render('edu_portal.edu_registrar_subject_approvals', {
            'title': '选课审批',
            'page_name': 'registrar_subject_approvals',
            'items': items,
            'filterby': filterby,
            'search': search,
            'stats': stats,
            'can_approve_change': is_priv,
            'pager': pager('/registrar/subject/approvals', total=total,
                           page=page, step=_PAGE_SIZE,
                           url_args={'filterby': filterby,
                                     'search': search}),
            'state_label': _SUBJREG_STATE_LABEL,
        })

    # ------------------------------------------------------------------
    # 教务侧：审批详情
    # ------------------------------------------------------------------
    @http.route('/registrar/subject/approvals/<int:rid>', type='http',
                auth='user', website=True)
    def approval_detail(self, rid, **kw):
        fac = current_faculty()
        is_priv = privileged_staff()
        if not fac and not is_priv:
            return request.redirect('/my/home')
        rec = request.env['op.subject.registration'].sudo().browse(rid)
        if not rec.exists():
            return request.redirect('/registrar/subject/approvals')
        is_change = rec.doc_type == 'course_change'
        # 服务端二次门禁（不能只靠前端隐藏）：教师不得看/批换班换课单
        if is_change and not is_priv:
            return request.redirect('/registrar/subject/approvals')
        student = rec.student_id
        # 在读档案摘要（供差异提示；优先 running，退回任意档案）
        sc = None
        if student:
            sc = request.env['op.student.course'].sudo().search([
                ('student_id', '=', student.id),
                ('course_id', '=', rec.course_id.id),
                ('state', '=', 'running')], order='id desc', limit=1) \
                or request.env['op.student.course'].sudo().search([
                    ('student_id', '=', student.id),
                    ('course_id', '=', rec.course_id.id)], limit=1)
        cur_sub_ids = set(sc.subject_ids.ids) if sc else set()
        new_sub_ids = set(rec._subject_payload())
        empty_warn = rec._legacy_empty_subject() and bool(sc)
        # G1（§7.5）：本单科目在 (本单班级, 本学期) 的排课聚合 —— 只读聚合、
        # **不新增字段**。M=0 ⇒ 通过后学生课表不会有任何课，教务必须在审批前看见。
        _term = edu_term_of_student(request.env, student)
        _sched = edu_scheduled_subjects(request.env, rec.batch_id, _term)
        sched_info = {
            'm': sum(1 for sid in new_sub_ids if sid in _sched),
            'n': len(new_sub_ids),
            'term': _term.name or '',
            'batch': rec.batch_id.name or '',
        }
        # 换班/换课：来源档案 = 唯一 running 档案（零新字段口径），
        # 目标课程/班级、目标班课节数与在读人数、以及 R1 影响提示一并给教务
        src = _ccr_source(rec) if is_change else None
        change = None
        if is_change:
            course, batch = rec.course_id, rec.batch_id
            clash = request.env['op.student.course'].sudo().search_count([
                ('student_id', '=', student.id),
                ('course_id', '=', course.id),
                ('batch_id', '=', batch.id),
                ('id', '!=', src.id if src else 0)]) if (student and course
                                                         and batch) else 0
            change = {
                'src': src,
                'old_label': '%s · %s' % (src.course_id.name or '—',
                                          src.batch_id.name or '—')
                if src else '',
                'new_label': '%s · %s' % (course.name or '—',
                                          batch.name or '—'),
                'same_course': bool(src and course
                                    and src.course_id.id == course.id),
                'batch_active': bool(batch and batch.active),
                'batch_course_ok': bool(batch and course
                                        and batch.course_id.id == course.id),
                'session_n': request.env['op.session'].sudo().search_count(
                    [('batch_id', '=', batch.id)]) if batch else 0,
                'student_n': request.env['op.student.course'].sudo()
                .search_count([('batch_id', '=', batch.id),
                               ('state', '=', 'running')]) if batch else 0,
                'clash': clash,
                # 换课程科目会按目标课程重算（LMS 事实源），只换班则不动
                'new_subject_n': len(course.subject_ids) if course else 0,
                'multi_archive': bool(student) and request.env[
                    'op.student.course'].sudo().search_count([
                        ('student_id', '=', student.id),
                        ('state', '=', 'running')]) > 1,
            }
        return request.render(
            'edu_portal.edu_registrar_subject_approval_detail', {
                'title': '变更审批详情' if is_change else '选课审批详情',
                'page_name': 'registrar_subject_approval_detail',
                'rec': rec,
                'msg': (kw.get('msg') or '')[:300],
                'is_change': is_change,
                'change': change,
                'state_label': _SUBJREG_STATE_LABEL.get(
                    rec.state, rec.state or '—'),
                'submitted_at': _fmt_dt(rec, rec.submitted_at or rec.create_date),
                'approved_at': _fmt_dt(rec, rec.approved_at),
                'student': student,
                'sc': sc,
                'sc_summary': {
                    'course': sc.course_id.name if sc else '（尚无档案）',
                    'batch': sc.batch_id.name if sc and sc.batch_id else '—',
                    'state': '在读' if sc and sc.state == 'running'
                    else ('已结业' if sc else '—'),
                    'subjects': len(cur_sub_ids),
                } if sc else None,
                'diff_n': len(cur_sub_ids - new_sub_ids),
                'diff_same': cur_sub_ids == new_sub_ids,
                'empty_warn': empty_warn,
                'sched_info': sched_info,
                'approver': rec.approved_by.name or '',
            })

    # ------------------------------------------------------------------
    # 教务侧：通过 / 驳回
    # ------------------------------------------------------------------
    @http.route('/registrar/subject/approvals/<int:rid>/set_state',
                type='http', auth='user', website=True,
                methods=['POST'], csrf=True)
    def set_state(self, rid, **post):
        fac = current_faculty()
        is_priv = privileged_staff()
        if not fac and not is_priv:
            return request.redirect('/my/home')
        rec = request.env['op.subject.registration'].sudo().browse(rid)
        new_state = post.get('state') or ''
        next_url = post.get('next') or ''
        if not next_url.startswith('/registrar/subject/approvals'):
            next_url = '/registrar/subject/approvals'
        if not (rec.exists() and new_state in ('approved', 'rejected')):
            return request.redirect(next_url)
        # 按 doc_type 分派 + 分门禁：换班/换课（course_change）只由教务 + 超管
        # 审批 —— 不带教师（设计 §9：改的是学籍归属，与选课审批的
        # current_faculty() 口径**故意不同**，不要在实现里「对齐」回去）。
        is_change = rec.doc_type == 'course_change'
        if is_change and not is_priv:
            return request.redirect('/my/home')
        try:
            if new_state == 'approved':
                if is_change:
                    # 换课程后学号需教务填新号（P8-(b)）；留空 = 保留原号
                    rec.action_course_change_approve(
                        new_roll_number=(post.get('new_roll_number')
                                         or '').strip()[:64])
                else:
                    rec.action_enroll_approve()
            else:
                reason = (post.get('reject_reason') or '').strip()[:500]
                if not reason:
                    return request.redirect(
                        '/registrar/subject/approvals/%d?box=error_reason'
                        % rid)
                rec.write({'reject_reason': reason})
                rec.action_enroll_reject()
        except (UserError, ValidationError) as exc:
            # 撞唯一约束预检 / 目标班停用 / 多档案 等，一律给**人话**提示
            # 并回详情页；绝不让 IntegrityError 冒成 500（设计 §8.3 R2/R3/R5）
            return request.redirect(
                '/registrar/subject/approvals/%d?box=error&msg=%s'
                % (rid, _quote(str(exc).replace('\n', ' ')[:300])))
        if is_change:
            next_url = '/registrar/subject/approvals/%d?box=done' % rid
        return request.redirect(next_url)

    # ------------------------------------------------------------------
    # F1：选课审批批量通过 / 驳回（逐条 savepoint，独立成败）
    # ------------------------------------------------------------------
    @http.route('/registrar/subject/set_state_bulk', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def set_state_bulk(self, **post):
        """批量审批选课单：只处理 state=submitted 的单，逐条独立成败。

        与单条路由共用同一套动作（action_enroll_approve / _reject），
        因此通知、审计、档案更新行为完全一致。
        """
        from urllib.parse import quote as _quote

        fac = current_faculty()
        if not fac and not privileged_staff():
            return request.redirect('/my/home')
        new_state = post.get('state') or ''
        if new_state not in ('approved', 'rejected'):
            return request.redirect('/registrar/subject/approvals')
        reason = (post.get('reject_reason') or '').strip()[:500]
        if new_state == 'rejected' and not reason:
            return request.redirect(
                '/registrar/subject/approvals?bulk_msg=%s'
                % _quote('批量驳回需先填写驳回原因'))
        form_ids = request.httprequest.form.getlist('ids')
        ids = []
        for chunk in form_ids:
            for part in str(chunk).split(','):
                part = part.strip()
                if part.isdigit():
                    ids.append(int(part))
        # t67：作用域口径与请假/申诉批量共用同一模块级函数（单一事实源，
        # 不在此处复制一份规则）。越权 id 静默忽略、不计 skip —— 与 t34 F3
        # 同口径；拒绝响应与「不存在」不可区分（不泄露存在性）。
        # 先取「作用域内的全部请求 id」，再从中挑出待处理 —— 这样：
        #   · 越权 id 被 scoped_records 静默丢掉 → 既不入 pending、也不计 skip
        #     （不泄露存在性：越权与「不存在」的表现一致）；
        #   · skip 只统计「在作用域内、但状态不是 submitted」的单（与 t7 口径一致）。
        # 注：原先此处直接引用 `regs`，而它属于另一个方法（approvals 列表页），
        # 在本路由里未定义 → 每次调用都会 NameError。t67 一并修掉。
        # 2026-09-14 修（与请假/申诉批量同族）：未勾选任何一行时，原实现回
        # ?bulk_ok=0&bulk_fail=0&bulk_skip=0 ⇒ 弹绿色"批量完成：成功 0 条…"。
        # 改为明确提示，不写审计、不回成功横幅。
        if not ids:
            return request.redirect(
                '/registrar/subject/approvals?bulk_msg=%s'
                % _quote('请先勾选要审批的注册单（可点表头「全选本页」）'))
        scoped_all = scoped_records(
            request.env, 'op.subject.registration', sorted(set(ids)))
        # 换班/换课单**不进批量审批**（设计 §17-9 默认口径）：它需要教务逐条
        # 看「原 → 新」与影响面（旧班名单立刻少人），且换课程要填新学号。
        # 越权/非待办一律静默丢弃（与 t34 F3 同口径，不泄露存在性）。
        pending = scoped_all.filtered(
            lambda r: r.state == 'submitted'
            and r.doc_type != 'course_change')
        ok, failures = 0, []
        for rec in pending:
            try:
                with request.env.cr.savepoint():
                    if new_state == 'approved':
                        rec.action_enroll_approve()
                    else:
                        rec.write({'reject_reason': reason})
                        rec.action_enroll_reject()
                ok += 1
            except Exception as exc:
                failures.append({
                    'name': rec.name or ('#%d' % rec.id),
                    'error': str(exc).replace('\n', ' ')[:120],
                })
        skipped = len(scoped_all) - len(pending)
        # t67：被作用域丢弃的 id（越权 + 不存在）聚合计数；只给总数、不拆原因
        ignored = max(0, len(set(ids)) - len(scoped_all))
        request.env['edu.audit.log'].sudo()._log(
            '选课批量审批', 'op.subject.registration', 0, '',
            '批量%s：成功 %d / 失败 %d / 跳过 %d / 忽略 %d' % (
                '通过' if new_state == 'approved' else '驳回',
                ok, len(failures), skipped, ignored))
        url = '/registrar/subject/approvals?bulk_ok=%d&bulk_fail=%d&bulk_skip=%d&bulk_ignored=%d' % (
            ok, len(failures), skipped, ignored)
        msgs = []
        if failures:
            msgs.append('%s：%s' % (failures[0]['name'], failures[0]['error']))
        if ignored:
            # t126：与 _bulk_url 同规则 —— 有失败时用「；」并接，不覆盖失败原因
            msgs.append('另有 %d 行不在你的处理范围内或已不存在，已跳过' % ignored)
        if msgs:
            url += '&bulk_msg=%s' % _quote('；'.join(msgs)[:200])
        return request.redirect(url)


# ======================================================================
# 教务端：课程编排（专业 × 科目 → 必修 / 选修 / 留空继承）
# ----------------------------------------------------------------------
# 设计：docs/plans/major-track-elective-design.md
#   §6.2.1 空值 = 继承「科目」自身的 subject_type（**这一档必须保留**）
#   §6.5   两级 fallback：专业行值 → 科目全局值（学制不参与判定）
# 缺口：后台「教学管理 ▸ 专业 ▸ 科目与必修/选修」这条链本来就是好的
#   （教务组 ACL 1,1,1,1），但**门户里没有任何编辑入口** => 本段只补门户
#   这一条动线：数据面仍是 edu.course.subject（单一事实源），不新增模型、
#   不新增字段、不动后台那条链，也不改学生的报课页。
# 三条口径（与设计稿对齐，改这里前先读设计稿）：
#   ① 「留空 = 继承科目默认值」与「显式选修」在界面上分开呈现 —— 现阶段
#      存量行全是显式「选修」，教务不能以为留空等于没配。
#   ② 「实际生效」列读模型自己的 effective_type_label（与非存储 helper
#      edu_effective_type 同一套两级 fallback）=> 不会出现「本页显示必修、
#      报课页按选修」的自相矛盾。
#   ③ 保存逐行走 ORM write（**不裸 SQL**）：edu.course.subject.subject_type
#      开了 tracking=True，该模型又 _inherit mail.thread => 自动按行留痕；
#      再补一条 edu.audit.log（动作名「课程编排」）。
# ======================================================================
_CURRICULUM_BOX = {
    'saved': '已保存：课程编排已更新，报课页对该专业的学生即刻生效。',
    'saved_none': '提交值与库中现值一致，本次没有任何改动。',
    'bad_course': '专业不存在或已停用，本次未做任何改动。',
    'bad_value': '提交的必修 / 选修值不合法，本次一行都没改（请刷新重试）。',
    # ---- 批量（2026-09-29 新增；三种动作 + 三种失败态，全部给人话）----
    'bulk_saved': '批量完成：课程编排已更新，报课页对该专业的学生即刻生效。',
    'bulk_none': '批量已受理：勾选的行本来就是目标值，本次没有任何改动。',
    'bulk_empty': '请先勾选要批量处理的科目行（表头「全选 / 全不选」可一次勾完本页）。',
    'bulk_bad_action': '没有识别出批量动作，本次一行都没改（请刷新页面重试）。',
    'bulk_error': '批量写入失败：整批已回滚，一条都没改。原因：',
    'write_error': '保存失败：本次改动已整体回滚，一行都没改。原因：',
}

# 批量动作 → 目标值（'' = 留空 = 回到「继承科目默认值」那一档）
_CURRICULUM_BULK_ACTIONS = {
    'compulsory': 'compulsory',
    'elective': 'elective',
    'clear': '',
}
_CURRICULUM_BULK_LABEL = {
    'compulsory': '批量设为必修',
    'elective': '批量设为选修',
    'clear': '批量清空（回到「留空 = 继承」）',
}


class CurriculumWriteError(Exception):
    """课程编排写入失败：**整批已回滚**，调用方只负责给人话提示。"""


def _curriculum_int(raw):
    """URL / 表单数字容错：非数字一律 0（手改参数不该 500）。"""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _curriculum_url(course_id, box, **extra):
    """回跳本页（303；有专业时才带 course_id；extra 用于批量回执计数）。"""
    url = '/registrar/curriculum?box=%s' % box
    if course_id:
        url += '&course_id=%d' % course_id
    for key in sorted(extra):
        url += '&%s=%s' % (key, _quote(str(extra[key])))
    return url


def _curriculum_own(course):
    """本专业自己的科目行 → {line_id: line}（**唯一写入作用域**）。

    表单里夹带的别专业 id 在这一步就被挡在门外（够不到 = 改不了），
    所以「批量只许改当前身份有权改的专业」不靠「页面没显示」，而靠写入集合
    本身只允许来自 course.subject_line_ids —— 数据层反向证明见
    tests/smoke/curriculum_bulk.py 的 ID-SCOPE 用例。
    """
    return {l.id: l for l in course.subject_line_ids}


def _curriculum_parse(form, course, bulk_action=None):
    """把表单读成一份「期望终态」计划 —— 逐行与批量**共用这一个解析器**。

    返回 (wanted, bad, picked_n, ignored_n)：
      · wanted  = {line_id: 'compulsory'|'elective'|''}，只含**属于本专业**的行；
      · bad     = True 表示表单里出现了非法值 ⇒ 调用方必须一行都不写；
      · picked_n= 本批被勾选（且属于本专业）的行数；
      · ignored_n= 提交了但不属于本专业的 id 数（越权 / 不存在，**不可区分**、
                   不泄露存在性，只报总数 —— 与选课批量审批 t67 同口径）。

    bulk_action 为 None ⇒ 逐行语义（只认 line_<id>，勾选一概不管）。
    bulk_action 非 None ⇒ 先按逐行取基准，再用批量动作**覆盖被勾选的那些行**
      （用户刚点的是批量按钮，那一格的旧值不该盖掉他的意图）；没被勾选的行
      仍按各自的逐行值写，避免「改了一半被静默丢掉」。
    """
    own = _curriculum_own(course)
    wanted = {}
    bad = False
    for line_id in own:
        raw = form.get('line_%d' % line_id)
        if raw is None:
            continue        # 表单没带这一行（例如刚被别人加进来的行）
        val = str(raw).strip()
        if val not in ('', 'compulsory', 'elective'):
            bad = True
            continue        # 扫完整张表再判定，别在第一个坏值上提前收工
        wanted[line_id] = val
    picked_n = ignored_n = 0
    if bulk_action is not None:
        seen = set()
        for chunk in form.getlist('pick'):
            for part in str(chunk).split(','):
                part = part.strip()
                if not part.isdigit():
                    continue
                lid = int(part)
                if lid in seen:
                    continue
                seen.add(lid)
                if lid in own:
                    picked_n += 1
                else:
                    ignored_n += 1
        # 说明：被忽略的 id 只计数、不逐个回显 —— 越权与「不存在」必须同形。
        for lid in seen:
            if lid in own:
                wanted[lid] = _CURRICULUM_BULK_ACTIONS[bulk_action]
    return wanted, bad, picked_n, ignored_n


def _curriculum_write(course, wanted):
    """**唯一的课程编排写入实现**（逐行与批量都走这里，不留第二份写逻辑）。

    只碰真的变了的行（其余行连 write 都不发）；**自己不开 savepoint、不 commit**
    —— 原子性由调用方的 _curriculum_apply() 用一个 savepoint 兜住整批。
    返回 [(line, 新值)]。
    """
    own = _curriculum_own(course)
    touched = []
    for line_id, val in wanted.items():
        line = own.get(line_id)
        if line is None:
            continue
        if (line.subject_type or '') == val:
            continue
        # ORM write（**不裸 SQL**）：subject_type 开了 tracking、模型又 _inherit
        # mail.thread ⇒ 按行留痕；ACL 是第二层（非教务身份写进去会在 ORM 层撞
        # AccessError，而不是只靠控制器那一层 privileged_staff()）。
        line.write({'subject_type': val or False})
        touched.append((line, val))
    return touched


def _curriculum_apply(course, wanted):
    """把整份计划写成**一条事务**：全成、或全不落（绝不留「改了一半」）。

    整批只套**一个** savepoint（不是逐行一个）——
      · 正常：savepoint 释放，改动留在本次请求事务里；
      · 任意一行抛错：with 退出时回滚到这个 savepoint ⇒ 之前那几行的 write
        一起被撤掉（Odoo sql_db.Savepoint.__exit__：有异常即 rollback），
        外层请求事务仍可用 ⇒ 回人话错误页，而不是 500。
    """
    sp = request.env.cr.savepoint()
    try:
        with sp:
            touched = _curriculum_write(course, wanted)
    except Exception as exc:      # noqa: BLE001 —— 任何失败都必须整批回滚 + 人话
        raise CurriculumWriteError(
            str(exc).replace('\n', ' ').strip()[:200]) from exc
    return touched


def _curriculum_log(course, touched, source):
    """审计：逐行与批量写**同一本台账**（动作名一致，来源落在 detail 里）。

    批量不是绕过审计的后门 —— 两条路径都在这里留痕；detail 里带「批量 / 逐行」
    与逐行改动摘要（前 8 行），另有一份按行的 mail.thread 消息记录。
    """
    lines = course.subject_line_ids
    detail = '%s专业 %s：显式 必修 %d / 选修 %d / 留空 %d —— 本次改动 %d 行：%s' % (
        source,
        course.name or ('#%d' % course.id),
        len(lines.filtered(lambda l: l.subject_type == 'compulsory')),
        len(lines.filtered(lambda l: l.subject_type == 'elective')),
        len(lines.filtered(lambda l: not l.subject_type)),
        len(touched),
        '；'.join('%s→%s' % (
            line.subject_id.name or line.subject_id.code or ('#%d' % line.id),
            _SUBJECT_TYPE_LABEL.get(val, '留空（继承）')) for line, val in touched[:8])
        or '（无变化）')
    request.env['edu.audit.log'].sudo()._log(
        '课程编排', 'op.course', course.id, course.name or '', detail)


class EduCurriculumPortal(http.Controller):
    """教务端「课程编排」：给门户补一个改「必修 / 选修」的入口。

    路由（两条都是新路径，无冲突）：
    - GET  /registrar/curriculum       选专业 → 列该专业科目 → 每行选必修/选修/留空
    - POST /registrar/curriculum/save  逐行 **或批量** ORM write + 审计 + 303 回本页

    批量（2026-09-29 加）：勾选多行 → 一键「设为必修 / 设为选修 / 清空（继承）」。
    与逐行**不是两套实现**：解析走同一个 _curriculum_parse()，写入走同一个
    _curriculum_write()，落账走同一个 _curriculum_log()；批量只是「先取逐行
    基准、再用批量动作覆盖被勾选的那些行」。整批套**一个** savepoint ⇒
    要么全改、要么全不改。

    门禁：privileged_staff()（教务组 or 系统组）——非教务**一律 303 回
    /my/home**（fail-closed，与 /ledger、/timetable/bulk 同一口径；教师、
    学生、家长都被拦）。读写**不 sudo**：教务组在这几张表上的 ACL 本就是
    1,1,1,1，让 ACL 当第二层（设计 §6.7 的意图：写不进就在 ORM 层撞
    AccessError，而不是只靠控制器一层）。
    """

    @http.route('/registrar/curriculum', type='http', auth='user',
                website=True)
    def curriculum(self, **kw):
        if not privileged_staff():
            return request.redirect('/my/home')
        env = request.env
        Course = env['op.course']
        courses = Course.search([('active', '=', True)], order='name, id')
        box = (kw.get('box') or '')[:32]
        # 批量回执（2026-09-29）：勾选 / 实际改动 / 被忽略 三个计数 + 失败原因。
        # 计数一律走 _curriculum_int 容错，且夹到 0..9999 —— 手改 URL 不该 500，
        # 也不该让页面显示一个荒唐数字冒充读数。
        def _cur_n(key):
            return max(0, min(_curriculum_int(kw.get(key)), 9999))
        bulk = {
            'action': (kw.get('bulk_action') or '')[:32],
            'picked': _cur_n('bulk_picked'),
            'changed': _cur_n('bulk_changed'),
            'ignored': _cur_n('bulk_ignored'),
            'msg': (kw.get('bulk_msg') or '')[:200],
        }
        bulk['action_label'] = _CURRICULUM_BULK_LABEL.get(bulk['action'], '')
        box_msg = _CURRICULUM_BOX.get(box, '')
        if box in ('bulk_error', 'write_error') and bulk['msg']:
            box_msg = '%s%s' % (box_msg, bulk['msg'])
        sel = Course.browse()
        raw_id = _curriculum_int(kw.get('course_id'))
        if raw_id:
            cand = Course.browse(raw_id)
            if cand.exists() and cand.active:
                sel = cand
            else:
                box = box or 'bad_course'
        else:
            # 未带参数：默认落在第一个**有科目清单**的专业 —— 没清单的专业进
            # 去就是空页，而教务要配的恰恰是有清单的那些；都没有才退回第一个。
            sel = (courses.filtered('subject_line_ids') or courses)[:1]
        rows = []
        explicit_c = explicit_e = inherit_n = 0
        for line in sel.subject_line_ids:
            if line.subject_type == 'compulsory':
                explicit_c += 1
            elif line.subject_type == 'elective':
                explicit_e += 1
            else:
                inherit_n += 1
            rows.append({
                'id': line.id,
                'subject': line.subject_id.name or '—',
                'code': line.subject_id.code or '',
                'active': bool(line.subject_id.active),
                'value': line.subject_type or '',
                'global_label': _SUBJECT_TYPE_LABEL.get(
                    line.subject_id.subject_type or '', '—'),
                # 实际生效 = 模型自己算的那一格（与报课页同源）
                'effective_key': (line.subject_type
                                  or line.subject_id.subject_type
                                  or 'compulsory'),
                'effective_label': line.effective_type_label or '',
            })
        return request.render('edu_portal.edu_registrar_curriculum', {
            'title': '课程编排',
            'page_name': 'registrar_curriculum',
            'box': box,
            'box_ok': box in ('saved', 'saved_none', 'bulk_saved', 'bulk_none'),
            'box_msg': box_msg,
            'bulk': bulk,
            'courses': [{'id': c.id, 'name': c.name or '',
                         'code': c.code or '',
                         'n': len(c.subject_line_ids)} for c in courses],
            'course': sel,
            'course_id': sel.id if sel else 0,
            'rows': rows,
            'effective_compulsory_n': sum(
                1 for r in rows if r['effective_key'] == 'compulsory'),
            'effective_elective_n': sum(
                1 for r in rows if r['effective_key'] == 'elective'),
            'explicit_compulsory_n': explicit_c,
            'explicit_elective_n': explicit_e,
            'inherit_n': inherit_n,
        })

    @http.route('/registrar/curriculum/save', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def curriculum_save(self, **post):
        """课程编排写入 —— **逐行与批量共用这一条路由、这一份写逻辑**。

        为什么批量不另开一条路由（例如 /registrar/curriculum/bulk）：
          · 同一张表的写入本来就只该有一个所有者 —— 两条路由会长出两份语义，
            正是本仓忌讳的「一个关注点两个所有者」；
          · 本仓门禁 check_ui_surface 的不变式 1 要求「仓内每条 @http.route 都
            必须在 tests/ui/surface.json 登记」，而那张表不在本次改动范围内 ——
            新路由会让门禁报「新路由未登记」这条红。
        区分方式 = 表单是否带 bulk_action：
          · 不带        ⇒ 逐行语义（与本次改动**之前逐位相同**，老习惯不受影响）
          · compulsory / elective / clear
                        ⇒ 批量把**勾选行**设成目标值（pick=<line id>，可多值）
        """
        if not privileged_staff():
            return request.redirect('/my/home')
        env = request.env
        form = request.httprequest.form
        course = env['op.course'].browse(
            _curriculum_int(form.get('course_id')))
        if not (course.exists() and course.active):
            return request.redirect(_curriculum_url(0, 'bad_course'))
        bulk_action = (post.get('bulk_action') or '').strip()
        is_bulk = bool(bulk_action)
        if is_bulk and bulk_action not in _CURRICULUM_BULK_ACTIONS:
            return request.redirect(
                _curriculum_url(course.id, 'bulk_bad_action'))
        source = (('批量·%s / ' % _CURRICULUM_BULK_LABEL[bulk_action])
                  if is_bulk else '逐行 / ')
        # ① 先把整张表校验完（含批量动作合法性）：有非法值就一行都不写
        #    （绝不做半张表的改动）。只认服务端自己列出的行 —— 表单里夹带
        #    别专业的 id 一律够不到（越权与「不存在」同形，只报总数）。
        wanted, bad, picked_n, ignored_n = _curriculum_parse(
            form, course, bulk_action if is_bulk else None)
        if bad:
            return request.redirect(_curriculum_url(course.id, 'bad_value'))
        # 一行都没勾 ⇒ 这不是一次批量动作：明确提示、不写审计、不弹成功横幅
        # （先例：选课批量审批在 ids 为空时的处置）。
        if is_bulk and not picked_n:
            return request.redirect(_curriculum_url(
                course.id, 'bulk_empty', bulk_ignored=ignored_n))
        # ② 一条事务写完整批：任意一行失败 ⇒ 整批回滚 + 人话提示
        #    （绝不出现「一半改了、一半没改」）。
        try:
            touched = _curriculum_apply(course, wanted)
        except CurriculumWriteError as exc:
            return request.redirect(_curriculum_url(
                course.id, 'bulk_error' if is_bulk else 'write_error',
                bulk_msg=str(exc)))
        # ③ 审计：两条路径写**同一本台账**（动作名都是「课程编排」）
        _curriculum_log(course, touched, source)
        if not is_bulk:
            return request.redirect(_curriculum_url(
                course.id, 'saved' if touched else 'saved_none'))
        return request.redirect(_curriculum_url(
            course.id, 'bulk_saved' if touched else 'bulk_none',
            bulk_action=bulk_action, bulk_picked=picked_n,
            bulk_changed=len(touched), bulk_ignored=ignored_n))
