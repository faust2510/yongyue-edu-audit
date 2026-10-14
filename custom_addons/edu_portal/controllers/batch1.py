# -*- coding: utf-8 -*-
"""学生门户第二批控制器：考勤 / 个人档案 / 考试 / 作业。

以 reference/ 目录下抓取的原站（Odoo 19 + OpenEduCat 企业版）DOM 为蓝本，
全部数据取自开源 OpenEduCat 模型：
- op.attendance.line            （考勤）
- op.student / op.student.course（档案）
- op.exam / op.exam.attendees   （考试）
- op.assignment                 （作业）
"""
import base64
import datetime as _dt
import re
from urllib.parse import quote

from odoo import fields, http
from odoo.http import content_disposition, request
from odoo.addons.portal.controllers.portal import pager

from .main import (assignment_scope_domain, csv_download, current_student,
                   safe_count, student_course)

_DAY_NAMES = ['周一', '周二', '周三', '周四', '周五',
              '周六', '周日']

# ---------------- 缺口 B7：档案动作族文案/徽章映射 ----------------
OFFER_STATE_LABEL = {'invited': '受邀', 'joined': '已加入', 'rejected': '已拒绝'}
OFFER_STATE_BADGE = {'invited': 'text-bg-info', 'joined': 'text-bg-success',
                     'rejected': 'text-bg-danger'}
LEAVE_TYPE_LABEL = {'sick': '病假', 'legal': '法定假期', 'casual': '事假',
                    'other': '其他',
                    # §6（S3，2026-09-25）：类型重做新增的三个 code。
                    # 不补 ⇒ /student/profile 的请假记录会显示英文 code。
                    'marriage_funeral': '婚丧假', 'winter_summer': '寒暑假',
                    'practice_week': '实践周'}
LEAVE_STATE_LABEL = {'request': '待审批', 'approved': '已通过',
                     'refused': '已拒绝',
                     # §3.1（S3，2026-09-25）：四级状态机的第四态。
                     # 不补这一条 ⇒ /student/profile 的请假记录表会把英文 code
                     # 'pending_second' 直接显示给学生（check_english must-fix 点名）。
                     'pending_second': '待二级审批'}
LEAVE_STATE_BADGE = {'request': 'text-bg-warning', 'approved': 'text-bg-success',
                     'refused': 'text-bg-danger',
                     'pending_second': 'text-bg-info'}
GRIEVANCE_STATE_LABEL = {'draft': '草稿', 'submitted': '已提交',
                         'in_progress': '处理中', 'resolve': '已解决',
                         'reject': '已驳回', 'close': '已关闭'}
GRIEVANCE_STATE_BADGE = {'draft': 'text-bg-secondary',
                         'submitted': 'text-bg-primary',
                         'in_progress': 'text-bg-info',
                         'resolve': 'text-bg-success',
                         'reject': 'text-bg-danger',
                         'close': 'text-bg-dark'}
PROFILE_TABS = ('personal_info', 'placement_offers', 'job_post_detail',
                'activity_log', 'fees_details', 'library', 'discipline')
PROFILE_SAVED_BANNER = {
    'skill': ('技能已添加。', 'success'),
    'offer': ('Placement Offer 状态已更新。', 'success'),
    'leave': ('请假申请已撤回。', 'success'),
    'apology': ('道歉信已提交，等待老师处理。', 'success'),
}
PROFILE_ERROR_BANNER = {
    'skill_empty': ('请填写技能名称后再提交。', 'warning'),
    'skill_dup': ('该技能已经在你的技能列表里了。', 'warning'),
    'offer_missing': ('未找到该 Offer，或它不属于当前学生。', 'danger'),
    'offer_state': ('该 Offer 当前状态不可再变更。', 'warning'),
    'leave_missing': ('未找到该请假申请，或它不属于当前学生。', 'danger'),
    'leave_state': ('只有待审批的请假申请才能撤回。', 'warning'),
    'apology_empty': ('道歉信的主题和说明都不能为空。', 'warning'),
    'invoice_missing': ('未找到该发票，或它不属于当前账户。', 'danger'),
    'pdf_fail': ('费用 PDF 生成失败，请稍后重试或联系管理员。', 'danger'),
}


def _back_to_profile(saved='', error='', tab=''):
    """动作完成后回到档案页并携带横幅 / 锚点 tab 参数。"""
    qs = []
    if saved:
        qs.append('saved=' + saved)
    if error:
        qs.append('error=' + error)
    if tab:
        qs.append('tab=' + tab)
    return request.redirect(
        '/student/profile' + ('?' + '&'.join(qs) if qs else ''))


def _post_int(value):
    """POST 参数安全取整（非法输入归 0）。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _fmt_date(d):
    return d.strftime('%Y/%m/%d') if d else ''


def _fmt_dt(dt):
    return dt.strftime('%Y/%m/%d %H:%M:%S') if dt else ''


def _attendance_stats(env, student, filterby):
    """考勤统计：总数 / 出席 / 缺席 / 出席率（跟随当前筛选）。"""
    domain = [('student_id', '=', student.id)] if student else [('id', '=', 0)]
    if filterby == 'present':
        domain += ['|', ('present', '=', True), ('late', '=', True)]
    elif filterby == 'absent':
        domain += ['|', ('absent', '=', True), ('excused', '=', True)]
    elif filterby == 'today':
        domain.append(('attendance_date', '=', fields.Date.today()))
    lines = env['op.attendance.line'].sudo().search(domain)
    total = len(lines)
    present = sum(1 for l in lines if l.present or l.late)
    absent = sum(1 for l in lines if l.absent or l.excused)
    pct = round(present / total * 100.0, 2) if total else 0.0
    return {'total': total, 'present': present, 'absent': absent,
            'pct': pct, 'pct_str': '%.2f%%' % pct}


class EduStudentBatch1(http.Controller):

    # ------------------------- 考勤 -------------------------

    @http.route('/student/attendance', type='http', auth='user', website=True)
    def student_attendance(self, **kw):
        student = current_student()
        filterby = kw.get('filterby') or 'all'
        sortby = kw.get('sortby') or 'attendance_date'
        groupby = kw.get('groupby') or 'none'
        search = (kw.get('search') or '').strip()

        domain = [('student_id', '=', student.id)] if student else [('id', '=', 0)]
        if filterby == 'present':
            domain += ['|', ('present', '=', True), ('late', '=', True)]
        elif filterby == 'absent':
            domain += ['|', ('absent', '=', True), ('excused', '=', True)]
        elif filterby == 'today':
            domain.append(('attendance_date', '=', fields.Date.today()))
        if search:
            domain += ['|',
                       ('attendance_id.name', 'ilike', search),
                       ('course_id.name', 'ilike', search)]

        order = {
            'attendance_date': 'attendance_date desc, id desc',
            'course_id': 'course_id, attendance_date desc',
            'attendance_id': 'attendance_id, attendance_date desc',
        }.get(sortby, 'attendance_date desc, id desc')
        # 分页（对齐原站每页 10 条）
        page = max(1, int(kw.get('page', 1) or 1))
        PAGE_SIZE = 10
        Line = request.env['op.attendance.line'].sudo()
        total = Line.search_count(domain)
        lines = Line.search(domain, order=order,
                            limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)

        cards = []
        for line in lines:
            sheet = line.attendance_id
            cards.append({
                'name': sheet.name or '',
                'sheet': line.course_id.name or '',
                'present': bool(line.present or line.late),
                'absent': bool(line.absent or line.excused),
                'date': _fmt_date(line.attendance_date),
                'day': _DAY_NAMES[line.attendance_date.weekday()]
                       if line.attendance_date else '',
                'check_in': _fmt_dt(sheet.session_id.start_datetime)
                            if sheet and sheet.session_id
                            and sheet.session_id.start_datetime else '',
                'batch': line.batch_id.name or '',
            })

        groups = []
        if groupby == 'course_id':
            by_course = {}
            for c in cards:
                by_course.setdefault(c['sheet'], []).append(c)
            groups = [{'name': k, 'items': v} for k, v in by_course.items()]
        else:
            groups = [{'name': '', 'items': cards}]

        values = {
            'title': '出席率',
            'page_name': 'attendance',
            'student': student,
            'stats': _attendance_stats(request.env, student, filterby),
            'groups': groups,
            'has_records': bool(cards),
            'filterby': filterby,
            'sortby': sortby,
            'groupby': groupby,
            'pager': pager('/student/attendance', total=total, page=page,
                           step=PAGE_SIZE,
                           url_args={'filterby': filterby, 'sortby': sortby,
                                     'groupby': groupby, 'search': search}),
            'search': search,
        }
        return request.render('edu_portal.edu_attendance', values)

    @http.route('/student/attendance/export', type='http', auth='user')
    def student_attendance_export(self, **kw):
        """考勤明细 CSV 导出：与列表页同筛选，全量不分页。"""
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        filterby = kw.get('filterby') or 'all'
        search = (kw.get('search') or '').strip()
        domain = [('student_id', '=', student.id)]
        if filterby == 'present':
            domain += ['|', ('present', '=', True), ('late', '=', True)]
        elif filterby == 'absent':
            domain += ['|', ('absent', '=', True), ('excused', '=', True)]
        elif filterby == 'today':
            domain.append(('attendance_date', '=', fields.Date.today()))
        if search:
            domain += ['|',
                       ('attendance_id.name', 'ilike', search),
                       ('course_id.name', 'ilike', search)]
        lines = request.env['op.attendance.line'].sudo().search(
            domain, order='attendance_date desc, id desc')
        rows = []
        for ln in lines:
            rows.append([
                _fmt_date(ln.attendance_date),
                _DAY_NAMES[ln.attendance_date.weekday()]
                if ln.attendance_date else '',
                ln.attendance_id.name or '',
                ln.course_id.name or '',
                ln.batch_id.name or '',
                '是' if ln.present else '',
                '是' if ln.late else '',
                '是' if ln.absent else '',
                '是' if ln.excused else '',
            ])
        return csv_download(
            '考勤明细_%s.csv' % fields.Date.today().strftime('%Y%m%d'),
            ['日期', '星期', '点名表', '课程', '班级',
             '到堂', '迟到', '缺席', '准假'],
            rows)

    # ------------------------- 个人档案 -------------------------

    @http.route('/student/profile', type='http', auth='user', website=True)
    def student_profile(self, **kw):
        student = current_student()
        env = request.env

        # 缺口 B7：动作结果横幅 + 锚点 tab（白名单校验）
        saved = kw.get('saved') or ''
        error = kw.get('error') or ''
        tab = kw.get('tab') or 'personal_info'
        if tab not in PROFILE_TABS:
            tab = 'personal_info'
        banner_text = banner_kind = ''
        if saved in PROFILE_SAVED_BANNER:
            banner_text, banner_kind = PROFILE_SAVED_BANNER[saved]
        elif error in PROFILE_ERROR_BANNER:
            banner_text, banner_kind = PROFILE_ERROR_BANNER[error]

        scs = student.course_detail_ids.sudo() if student else \
            env['op.student.course'].sudo()
        running = scs.filtered(lambda s: s.state == 'running')[:1] or scs[:1]
        course = running.course_id if running else env['op.course'].sudo()
        batch = running.batch_id if running else env['op.batch'].sudo()

        # 统计卡：出席率 / 平均成绩 / 学分 / 成就
        att = _attendance_stats(env, student, 'all')
        marks_sum = marks_total = 0
        if student:
            for attd in env['op.exam.attendees'].sudo().search(
                    [('student_id', '=', student.id)]):
                if attd.marks is not False:
                    marks_sum += attd.marks
                    marks_total += attd.exam_id.total_marks or 0
        avg_result = round(marks_sum / marks_total * 100.0, 1) if marks_total else 0.0
        credits = course.max_unit_load or 0
        achievements = safe_count('op.activity',
                                  [('student_id', '=', student.id)]) if student else 0
        stats = {
            'attendance': att['pct'] if att['total'] else 0,
            'att_disp': '%d%%' % (att['pct'] if att['total'] else 0),
            'att_total': att['total'],
            'avg_result': avg_result,
            'avg_disp': '%d%%' % avg_result,
            'credits': credits,
            'credits_disp': credits and ('%d / %d' % (credits, credits)) or '—',
            'achievements': achievements,
        }

        # 侧栏个人信息（op.student 继承 res.partner）
        partner = student.partner_id if student else env['res.partner']
        gender = ''
        if student:
            # selection 原始标签不走翻译机制，直接按值映射中文
            gender = {'m': '男', 'f': '女'}.get(student.gender,
                                               student.gender or '')
        nationality = ''
        if student and student.nationality:
            nationality = student.nationality.name
        elif partner and partner.country_id:
            nationality = partner.country_id.name
        addr = []
        if partner:
            for part in (partner.street, partner.street2, partner.city,
                         partner.zip):
                if part:
                    addr.append(part)
        addr_lines = addr or []
        info = {
            'gender': gender,
            'birth_date': _fmt_date(student.birth_date) if student else '',
            'phone': partner.phone or '',
            'blood_group': (student.blood_group or '') if student else '',
            'nationality': nationality or '',
            'addr': addr_lines,
            'email': (student.email or '') if student else '',
            'status': '在读' if (student and student.active) else '',
        }

        # 入学详情卡：每个 op.student.course 一条
        adm_cards = []
        for sc in scs:
            subs = sc.subject_ids or (sc.course_id.subject_ids if sc.course_id
                                      else env['op.subject'].sudo())
            adm_cards.append({
                'course': sc.course_id.name if sc.course_id else '',
                'batch': sc.batch_id.name if sc.batch_id else '',
                'roll': sc.roll_number or '',
                'subjects': subs.mapped('name'),
            })

        # 家长信息（紧急联系人 —— 字段在 op.student 上）
        parent = student.emergency_contact if student else False
        parent_info = {
            'name': parent.name if parent else '',
            'email': parent.email if parent else '',
            'phone': parent.phone if parent else '',
        }

        # 活动记录（op.activity）
        activities = []
        if student:
            for act in env['op.activity'].sudo().search(
                    [('student_id', '=', student.id)], order='date desc'):
                activities.append({
                    'type': act.type_id.name if act.type_id else '活动',
                    'date': _fmt_date(act.date),
                    'description': act.description or '',
                    'faculty': act.faculty_id.name if act.faculty_id else '',
                })

        # 费用发票（对齐原站 Fees 表：日期/参考号/金额/状态 + 下载PDF 入口）
        fees = []
        if student and student.partner_id:
            for inv in request.env['account.move'].sudo().search(
                    [('partner_id', '=', student.partner_id.id),
                     ('move_type', '=', 'out_invoice')],
                    order='invoice_date desc', limit=10):
                fees.append({
                    'id': inv.id,
                    'date': _fmt_date(inv.invoice_date),
                    'ref': inv.name or inv.ref or '—',
                    'amount': f'{inv.amount_total:,.2f}',
                    'state': {'draft': '草稿', 'posted': '已过账',
                              }.get(inv.state, inv.state),
                })

        # ---- 缺口 B7：档案动作数据（技能 / Placement Offer / 请假 / 道歉信）----
        skills, offers, leaves, apologies = [], [], [], []
        if student:
            for sk in env['edu.student.skill'].sudo().search(
                    [('student_id', '=', student.id)],
                    order='create_date desc, id desc'):
                skills.append({'id': sk.id, 'name': sk.name or ''})
            for of in env['edu.placement.offer'].sudo().search(
                    [('student_id', '=', student.id)],
                    order='create_date desc, id desc'):
                offers.append({
                    'id': of.id,
                    'title': of.title or '职位邀请',
                    'company': of.company or '—',
                    'state_raw': of.state or 'invited',
                    'state_label': OFFER_STATE_LABEL.get(of.state,
                                                         of.state or ''),
                    'badge': OFFER_STATE_BADGE.get(of.state,
                                                   'text-bg-secondary'),
                })
            for lv in env['edu.leave'].sudo().search(
                    [('student_id', '=', student.id)],
                    order='date_from desc, id desc', limit=5):
                leaves.append({
                    'id': lv.id,
                    'name': lv.name or '',
                    'type': LEAVE_TYPE_LABEL.get(lv.leave_type,
                                                 lv.leave_type or '其他'),
                    'date_from': _fmt_date(lv.date_from),
                    'date_to': _fmt_date(lv.date_to),
                    'state_label': LEAVE_STATE_LABEL.get(lv.state,
                                                         lv.state or ''),
                    'badge': LEAVE_STATE_BADGE.get(lv.state,
                                                   'text-bg-secondary'),
                    'can_withdraw': lv.state == 'request',
                })
            for gv in env['edu.grievance'].sudo().search(
                    [('student_id', '=', student.id),
                     ('category', '=', '道歉信')],
                    order='date desc, id desc', limit=5):
                apologies.append({
                    'id': gv.id,
                    'subject': gv.subject or '',
                    'date': _fmt_date(gv.date),
                    'state_label': GRIEVANCE_STATE_LABEL.get(gv.state,
                                                             gv.state or ''),
                    'badge': GRIEVANCE_STATE_BADGE.get(gv.state,
                                                       'text-bg-secondary'),
                })

        values = {
            'title': '学生档案',
            'page_name': 'profile',
            'student': student,
            'scs': scs,
            'course': course,
            'batch': batch,
            'stats': stats,
            'info': info,
            'adm_cards': adm_cards,
            'parent': parent_info,
            'activities': activities,
            'fees': fees,
            'has_student': bool(student),
            # 缺口 B7
            'skills': skills,
            'offers': offers,
            'leaves': leaves,
            'apologies': apologies,
            'saved': saved,
            'error': error,
            'tab': tab,
            'banner_text': banner_text,
            'banner_kind': banner_kind,
        }
        return request.render('edu_portal.edu_profile', values)

    # ------------------------- 考试 -------------------------

    @http.route('/student/exam', type='http', auth='user', website=True)
    def student_exam(self, **kw):
        student = current_student()
        course, _batch = student_course(student)
        filterby = kw.get('filterby') or 'all'
        sortby = kw.get('sortby') or 'generated_date'
        groupby = kw.get('groupby') or 'none'
        search = (kw.get('search') or '').strip()

        domain = [('course_id', '=', course.id)] if course else [('id', '=', 0)]
        if search:
            domain += ['|', ('name', 'ilike', search),
                       ('exam_code', 'ilike', search)]
        Exam = request.env['op.exam'].sudo()
        total_ex = Exam.search_count(domain)
        page = max(1, int(kw.get('page', 1) or 1))
        STEP = 3
        exams = Exam.search(domain, order='start_time desc')

        cards = []
        for ex in exams:
            att = False
            if student:
                att = request.env['op.exam.attendees'].sudo().search(
                    [('exam_id', '=', ex.id),
                     ('student_id', '=', student.id)], limit=1)
            obtained = att.marks if att and att.marks is not False else None
            total = ex.total_marks or 0
            pct = round(obtained / total * 100.0, 2) \
                if obtained is not None and total else 0.0
            passed = (obtained is not None
                      and obtained >= (ex.min_marks or 0))
            generated_on = None
            if att and att.write_date:
                generated_on = att.write_date.date()
            elif ex.start_time:
                generated_on = ex.start_time.date()
            chips = []
            if ex.subject_id:
                chips = [ex.subject_id.name]
            elif ex.session_id:
                chips = list(dict.fromkeys(
                    ex.session_id.exam_ids.mapped('subject_id.name')))
            cards.append({
                'exam': ex,
                'obtained': obtained,
                'total': total,
                'pct': pct,
                'pct_str': '%.2f%%' % pct,
                'passed': passed,
                'has_result': obtained is not None,
                'chips': chips,
                'generated_on': _fmt_date(generated_on),
                'sub': ex.session_id.exam_type.name
                       if ex.session_id and ex.session_id.exam_type else '',
            })

        # 筛选
        filtered = [c for c in cards if c['has_result']]
        if filterby == 'pass':
            filtered = [c for c in filtered if c['passed']]
        elif filterby == 'fail':
            filtered = [c for c in filtered if not c['passed']]
        # 排序
        if sortby == 'percentage':
            filtered.sort(key=lambda c: c['pct'], reverse=True)
        elif sortby == 'total_marks':
            filtered.sort(key=lambda c: c['total'], reverse=True)
        elif sortby in ('status', 'grade'):
            filtered.sort(key=lambda c: c['passed'], reverse=True)
        else:  # generated_date 等
            filtered.sort(key=lambda c: c['generated_on'], reverse=True)

        # 统计（只看有成绩的考试）
        results = [c for c in cards if c['has_result']]
        total_exams = len(results)
        passed = sum(1 for c in results if c['passed'])
        failed = total_exams - passed
        avg_pct = round(sum(c['pct'] for c in results) / total_exams, 2) \
            if total_exams else 0.0
        stats = {
            'total': total_exams,
            'avg': avg_pct,
            'avg_str': '%.2f%%' % avg_pct,
            'passed': passed,
            'failed': failed,
        }

        groups = []
        if groupby == 'status':
            groups = [
                {'name': '及格', 'items': [c for c in filtered if c['passed']]},
                {'name': '不及格', 'items': [c for c in filtered
                                             if not c['passed']]},
            ]
            groups = [g for g in groups if g['items']]
        else:
            groups = [{'name': '', 'items': filtered}]

        # 分页展示（每页 3 条；统计保持全量口径）
        page_exams = filtered[(page - 1) * STEP: page * STEP]
        groups = [{'name': g['name'],
                   'items': [c for c in page_exams
                             if not groupby == 'status'
                             or (g['name'] == '及格') == c['passed']]}
                  for g in groups]
        groups = [g for g in groups if g['items']]
        pager_vals = pager('/student/exam', total=total_ex, page=page,
                           step=STEP,
                           url_args={'filterby': filterby,
                                     'sortby': sortby, 'groupby': groupby,
                                     'search': search})

        values = {
            'title': '考试',
            'page_name': 'exam',
            'student': student,
            'stats': stats,
            'groups': groups,
            'has_records': bool(filtered),
            'filterby': filterby,
            'sortby': sortby,
            'groupby': groupby,
            'search': search,
            'pager': pager_vals,
        }
        return request.render('edu_portal.edu_exam', values)

    # ------------------------- 考试详情（B3） -------------------------

    EXAM_STATE_LABEL = {
        'draft': '草稿', 'schedule': '已排期', 'held': '已举行',
        'result_updated': '已出成绩', 'done': '已完成', 'cancel': '已取消',
    }
    EXAM_STATE_CLASS = {
        'draft': 'secondary', 'schedule': 'info', 'held': 'primary',
        'result_updated': 'success', 'done': 'success', 'cancel': 'danger',
    }

    def _own_exam(self, eid):
        """考试必须存在，且属于当前学生的课程/班级（或本人有应试记录）。"""
        student = current_student()
        course, batch = student_course(student)
        e = request.env['op.exam'].sudo().browse(eid)
        if not e.exists():
            return None, None
        att = request.env['op.exam.attendees'].sudo().search(
            [('exam_id', '=', e.id),
             ('student_id', '=', student.id)], limit=1) if student else False
        if not ((course and e.course_id == course) or
                (batch and e.batch_id == batch) or att):
            return None, None
        return student, e

    @http.route('/student/exam/data/<int:eid>', type='http', auth='user',
                website=True)
    def student_exam_data(self, eid, **kw):
        """单场考试详情：头部信息卡 + 该生本次成绩行（无记录时空态）。"""
        student, e = self._own_exam(eid)
        if not e:
            return request.redirect('/student/exam')
        att = request.env['op.exam.attendees'].sudo().search(
            [('exam_id', '=', e.id),
             ('student_id', '=', student.id)], limit=1) if student else False
        obtained = att.marks if att and att.marks is not False else None
        total = e.total_marks or 0
        pct = round(obtained / total * 100.0, 2) \
            if obtained is not None and total else 0.0
        passed = (obtained is not None and obtained >= (e.min_marks or 0))
        values = {
            'title': '考试详情',
            'page_name': 'exam_data',
            'student': student,
            'e': e,
            'subject': e.subject_id.name or '',
            'course': e.course_id.name or '',
            'batch': e.batch_id.name or '',
            'start_time': _fmt_dt(e.start_time),
            'end_time': _fmt_dt(e.end_time),
            'state_label': self.EXAM_STATE_LABEL.get(e.state, e.state or ''),
            'state_class': self.EXAM_STATE_CLASS.get(e.state, 'secondary'),
            'total_marks': total,
            'min_marks': e.min_marks or 0,
            'has_att': bool(att),
            'attended': bool(att and att.status == 'present'),
            'obtained': obtained,
            'pct_str': '%.2f%%' % pct,
            'pct': pct,
            'passed': passed,
            'has_result': obtained is not None,
        }
        return request.render('edu_portal.edu_exam_data', values)

    # ------------------------- 作业 -------------------------

    @http.route('/student/assignment/details', type='http', auth='user',
                website=True)
    def student_assignment_details(self, **kw):
        student = current_student()
        course, batch = student_course(student)
        filterby = kw.get('filterby') or 'all'
        sortby = kw.get('sortby') or 'name'
        groupby = kw.get('groupby') or 'none'
        search = (kw.get('search') or '').strip()
        box = kw.get('box') or ''

        # 2026-10-03：本处原先内联写死这四支 —— 同一套规则门户里共 4 份、写法还不一致
        # （首页/时间线只按 batch）。已抽成 main.assignment_scope_domain 共用。
        domain = assignment_scope_domain(student)
        if filterby == 'state+finish':
            domain.append(('state', '=', 'finish'))
        elif filterby == 'state+publish':
            domain.append(('state', '=', 'publish'))
        if search:
            domain += ['|', ('name', 'ilike', search),
                       ('subject_id.name', 'ilike', search)]
        assignments = request.env['op.assignment'].sudo().search(domain)
        page = max(1, int(kw.get('page', 1) or 1))
        STEP_A = 3
        total_asg = len(assignments)

        # 学生已提交的作业
        sub_by_assignment = {}
        if student:
            for sub in request.env['op.assignment.sub.line'].sudo().search(
                    [('student_id', '=', student.id)]):
                sub_by_assignment[sub.assignment_id.id] = sub

        def _submitted(a):
            sub = sub_by_assignment.get(a.id)
            return bool(sub and sub.state in ('submit', 'accept'))

        state_label = {
            'draft': '草稿', 'publish': '已发布', 'finish': '已完成',
            'cancel': '已取消',
        }

        cards = []
        for a in assignments:
            cards.append({
                'assignment': a,
                'name': a.name or '',
                'state': state_label.get(a.state, a.state or ''),
                'course': a.course_id.name or '',
                'type': a.assignment_type.name if a.assignment_type else '',
                'issued': _fmt_dt(a.issued_date),
                'submission': _fmt_dt(a.submission_date),
                'submitted': _submitted(a),
            })

        if box == 'publish':
            cards = [c for c in cards if c['assignment'].state == 'publish']
        elif box == 'submitted':
            cards = [c for c in cards if c['submitted']]
        elif box == 'pending':
            cards = [c for c in cards
                     if c['assignment'].state == 'publish'
                     and not c['submitted']]

        order_map = {
            'name': lambda c: c['name'],
            'course_id': lambda c: c['course'],
            'batch_id': lambda c: c['assignment'].batch_id.name or '',
            'marks': lambda c: c['assignment'].marks or 0,
            'submission_date': lambda c: c['assignment'].submission_date or _dt.datetime.min,
            'issued_date': lambda c: c['assignment'].issued_date or _dt.datetime.min,
            'state': lambda c: c['state'],
        }
        if sortby in order_map:
            cards.sort(key=order_map[sortby], reverse=sortby in (
                'submission_date', 'issued_date', 'marks'))

        groups = []
        if groupby == 'course_id':
            by_course = {}
            for c in cards:
                by_course.setdefault(c['course'], []).append(c)
            groups = [{'name': k, 'items': v} for k, v in by_course.items()]
        else:
            groups = [{'name': '', 'items': cards}]

        stats = {
            'total': len(assignments),
            'open': sum(1 for a in assignments if a.state == 'publish'),
            'submitted': sum(1 for a in assignments if _submitted(a)),
            'pending': sum(1 for a in assignments
                           if a.state == 'publish' and not _submitted(a)),
        }

        # 分页展示（每页 3 条；统计保持全量口径）
        page_ids = {c['assignment'].id for c in
                    cards[(page - 1) * STEP_A: page * STEP_A]}
        groups = [{'name': g['name'],
                   'items': [c for c in g['items']
                             if c['assignment'].id in page_ids]}
                  for g in groups]
        groups = [g for g in groups if g['items']]
        pager_vals = pager('/student/assignment/details',
                           total=total_asg, page=page, step=STEP_A,
                           url_args={'filterby': filterby,
                                     'sortby': sortby, 'search': search})

        values = {
            'title': '作业',
            'page_name': 'assignment',
            'student': student,
            'stats': stats,
            'groups': groups,
            'has_records': bool(cards),
            'filterby': filterby,
            'sortby': sortby,
            'groupby': groupby,
            'search': search,
            'box': box,
        }
        return request.render('edu_portal.edu_assignment', values)

    # ------------------------------------------------------------------
    # 学生提交作业（自研补齐企业版 /submited/assignment/list/<id> 入口，
    # URL 与原站保持一致）
    # ------------------------------------------------------------------
    SUB_STATE_LABEL = {
        'draft': '草稿', 'submit': '已提交·待批阅', 'reject': '已退回',
        'change': '需修改', 'accept': '已批阅',
    }

    def _own_assignment(self, aid):
        """作业必须存在，且属于当前学生的课程或班级。"""
        student = current_student()
        course, batch = student_course(student)
        a = request.env['op.assignment'].sudo().browse(aid)
        if not a.exists():
            return None, None
        if not ((course and a.course_id == course) or
                (batch and a.batch_id == batch)):
            return None, None
        return student, a

    def _own_submission(self, student, aid):
        return request.env['op.assignment.sub.line'].sudo().search(
            [('assignment_id', '=', aid),
             ('student_id', '=', student.id)], limit=1)

    @http.route('/submited/assignment/list/<int:aid>', type='http',
                auth='user', website=True)
    def assignment_submit_page(self, aid, **kw):
        student, a = self._own_assignment(aid)
        if not a:
            return request.redirect('/student/assignment/details')
        sub = self._own_submission(student, aid)
        return request.render('edu_portal.edu_assignment_submit', {
            'title': '提交作业',
            'page_name': 'assignment_submit',
            'a': a,
            'sub': sub,
            'saved': kw.get('saved'),
            'sub_state_label':
                self.SUB_STATE_LABEL.get(sub.state, sub.state) if sub else '',
        })

    @http.route('/submited/assignment/list/<int:aid>/save', type='http',
                auth='user', methods=['POST'], website=True, csrf=True)
    def assignment_submit_save(self, aid, **post):
        student, a = self._own_assignment(aid)
        if not a or a.state != 'publish':
            return request.redirect('/student/assignment/details')
        Sub = request.env['op.assignment.sub.line'].sudo()
        sub = self._own_submission(student, aid)
        vals = {'state': 'submit',
                'description': (post.get('description') or '').strip()}
        fs = post.get('file')
        if fs is not None and getattr(fs, 'filename', False):
            vals['file'] = base64.b64encode(fs.read())
            vals['filename'] = fs.filename
        if sub and sub.state != 'accept':
            sub.write(vals)
        elif not sub:
            Sub.create(dict(vals, assignment_id=a.id,
                            student_id=student.id))
        return request.redirect('/submited/assignment/list/%d?saved=1' % aid)

    @http.route('/my/assignment/sub/<int:sid>/file', type='http',
                auth='user', website=True)
    def assignment_sub_file(self, sid, **kw):
        """下载/预览自己提交的作业附件（所有权校验后 sudo 取数）。

        ?inline=1 且为 pdf/图片时走浏览器内联预览，否则强制下载。"""
        from .downloads import _INLINE_TYPES
        student = current_student()
        sub = request.env['op.assignment.sub.line'].sudo().browse(sid)
        if not sub.exists() or sub.student_id.id != student.id \
                or not sub.file:
            return request.redirect('/student/assignment/details')
        fname = sub.filename or 'homework.bin'
        content = base64.b64decode(sub.file)
        if kw.get('inline') == '1':
            ctype = _INLINE_TYPES.get(
                (fname.rsplit('.', 1)[-1].lower()
                 if '.' in fname else ''))
            if ctype:
                ascii_name = fname.encode('ascii', 'replace').decode() \
                    .replace('"', '') or 'preview'
                return request.make_response(content, headers=[
                    ('Content-Type', ctype),
                    ('Content-Disposition',
                     "inline; filename=\"%s\"; filename*=UTF-8''%s"
                     % (ascii_name, quote(fname))),
                    ('Content-Length', str(len(content)))])
        headers = [('Content-Type', 'application/octet-stream'),
                   ('Content-Disposition',
                    content_disposition(fname)),
                   ('Content-Length', str(len(content)))]
        return request.make_response(content, headers=headers)

    # ------------------------------------------------------------------
    # 缺口 B7：学生档案页交互动作族（技能 / Offer / 请假撤回 / 费用PDF / 道歉信）
    # 安全约定：写路由全部 methods=['POST'] + csrf=True；先 current_student()
    # 再校验目标记录归属，越权一律按「不存在」处理并横幅提示。
    # ------------------------------------------------------------------

    @http.route('/my/skill/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def my_skill_save(self, **post):
        """B7-1 添加技能：edu.student.skill（同名去重）。"""
        student = current_student()
        if not student:
            return _back_to_profile()
        name = (post.get('name') or '').strip()[:128]
        if not name:
            return _back_to_profile(error='skill_empty', tab='personal_info')
        Skill = request.env['edu.student.skill'].sudo()
        existing = {s.name.strip().lower()
                    for s in Skill.search([('student_id', '=', student.id)])}
        if name.lower() in existing:
            return _back_to_profile(error='skill_dup', tab='personal_info')
        Skill.create({'name': name, 'student_id': student.id})
        return _back_to_profile(saved='skill', tab='personal_info')

    @http.route('/my/offer/set_state', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def my_offer_set_state(self, **post):
        """B7-2 Placement Offer 加入/拒绝：仅本人受邀(invited)记录可变更。"""
        student = current_student()
        if not student:
            return _back_to_profile()
        offer = request.env['edu.placement.offer'].sudo().browse(
            _post_int(post.get('offer_id'))).exists()
        action = post.get('action')
        if not offer or offer.student_id.id != student.id:
            return _back_to_profile(error='offer_missing',
                                    tab='placement_offers')
        if action not in ('join', 'reject') or offer.state != 'invited':
            return _back_to_profile(error='offer_state',
                                    tab='placement_offers')
        offer.write({'state': 'joined' if action == 'join' else 'rejected'})
        return _back_to_profile(saved='offer', tab='placement_offers')

    @http.route('/my/leave/withdraw', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def my_leave_withdraw(self, **post):
        """B7-3 请假撤回：仅本人待审(request)可撤。

        edu.leave 只有 request/approved/refused 三态、无独立取消态，
        故撤回落到既有 refused 终态并在 reject_reason 留痕，
        与管理员驳回（须填原因）共用同一状态值。
        """
        student = current_student()
        if not student:
            return _back_to_profile()
        leave = request.env['edu.leave'].sudo().browse(
            _post_int(post.get('leave_id'))).exists()
        if not leave or leave.student_id.id != student.id:
            return _back_to_profile(error='leave_missing',
                                    tab='personal_info')
        if leave.state != 'request':
            return _back_to_profile(error='leave_state',
                                    tab='personal_info')
        leave.write({'state': 'refused',
                     'reject_reason': '学生本人于学生档案页撤回该申请。'})
        return _back_to_profile(saved='leave', tab='personal_info')

    @http.route('/my/invoice/pdf/<int:move_id>', type='http',
                auth='user', website=True)
    def my_invoice_pdf(self, move_id, **kw):
        """B7-4 费用 PDF：sudo 渲染 account.move 发票报表。

        归属校验：发票 partner 必须等于当前学生的 res.partner；
        报表优先 account.account_invoices，失败回退 report_invoice
        名称；两次皆败返回档案页友好错误横幅而非 500。
        """
        student = current_student()
        move = request.env['account.move'].sudo().browse(move_id).exists()
        if not student or not move or move.move_type != 'out_invoice' \
                or move.partner_id.id != student.partner_id.id:
            return _back_to_profile(error='invoice_missing',
                                    tab='fees_details')
        pdf = None
        Report = request.env['ir.actions.report'].sudo()
        for ref in ('account.account_invoices', 'account.report_invoice'):
            try:
                data, _rtype = Report._render_qweb_pdf(ref, [move.id])
                if data:
                    pdf = data
                    break
            except Exception:
                continue
        if not pdf:
            return _back_to_profile(error='pdf_fail', tab='fees_details')
        safe_name = re.sub(
            r'[^0-9A-Za-z._-]+', '_',
            move.name or ('invoice-%d' % move.id)).strip('_') \
            or ('invoice-%d' % move.id)
        return request.make_response(
            pdf,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition',
                 'attachment; filename="%s.pdf"' % safe_name),
                ('Content-Length', str(len(pdf))),
            ])

    @http.route('/my/apology/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def my_apology_save(self, **post):
        """B7-5 道歉信：复用 edu.grievance，category 固定「道歉信」。

        编号沿用 /my/grievances/save 的 GRI%04d 递增惯例。
        """
        student = current_student()
        if not student:
            return _back_to_profile()
        subject = (post.get('subject') or '').strip()[:200]
        description = (post.get('description') or '').strip()[:2000]
        if not subject or not description:
            return _back_to_profile(error='apology_empty', tab='discipline')
        Grievance = request.env['edu.grievance'].sudo()
        last = Grievance.search([], order='id desc', limit=1)
        seq = 1
        if last and last.name and last.name[3:].isdigit():
            seq = int(last.name[3:]) + 1
        Grievance.create({
            'name': 'GRI%04d' % seq,
            'student_id': student.id,
            'subject': subject,
            'category': '道歉信',
            'description': description,
            'state': 'submitted',
        })
        return _back_to_profile(saved='apology', tab='discipline')
