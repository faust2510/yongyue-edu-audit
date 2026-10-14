# -*- coding: utf-8 -*-
"""网页端深度操作页：选课申请 / 教师点名 / 成绩录入。

bot 只负责发起与提醒，复杂表单在这里完成。
"""
from odoo import http
from odoo.http import request


def current_student():
    return request.env['op.student'].sudo().search(
        [('user_id', '=', request.env.uid)], limit=1)


def current_faculty():
    Fac = request.env['op.faculty'].sudo()
    emp = request.env['hr.employee'].sudo().search(
        [('user_id', '=', request.env.uid)], limit=1)
    if emp:
        fac = Fac.search([('emp_id', '=', emp.id)], limit=1)
        if fac:
            return fac
    return Fac.search(
        [('partner_id', '=', request.env.user.partner_id.id)], limit=1)


class SubjectRegPortal(http.Controller):

    @http.route('/my/subject-reg', type='http', auth='user', website=True)
    def subject_reg(self, saved=None, **kw):
        stu = current_student()
        if not stu:
            return request.render('edu_telegram.ops_message', {
                'msg': '仅学生可操作选课。'})
        sc = request.env['op.student.course'].sudo().search(
            [('student_id', '=', stu.id)], limit=1)
        Reg = request.env['op.subject.registration'].sudo()
        reg = Reg.search([('student_id', '=', stu.id)], order='id desc',
                         limit=1)
        if not reg:
            reg = Reg.create({
                'student_id': stu.id,
                'course_id': sc.course_id.id, 'batch_id': sc.batch_id.id})
            reg.get_subjects()
        electives = reg.course_id.subject_ids.filtered(
            lambda s: s.subject_type == 'elective')
        values = {
            'reg': reg, 'electives': electives,
            'saved': bool(saved),
            'compulsory': reg.compulsory_subject_ids,
        }
        return request.render('edu_telegram.subject_reg_page', values)

    @http.route('/my/subject-reg/save', type='http', auth='user',
                methods=['POST'], csrf=True)
    def subject_reg_save(self, **kw):
        stu = current_student()
        reg = request.env['op.subject.registration'].sudo().search(
            [('student_id', '=', stu.id)], order='id desc', limit=1)
        ids = [int(i) for i in kw.get('elective_ids', '').split(',') if i]
        if reg and reg.state in ('draft', 'rejected'):
            reg.write({'elective_subject_ids': [(6, 0, ids)]})
            reg.action_submitted()
        elif reg and reg.state == 'submitted':
            reg.write({'elective_subject_ids': [(6, 0, ids)]})
        return request.redirect('/my/subject-reg?saved=1')


class RollcallPortal(http.Controller):

    def _faculty_or_none(self):
        fac = current_faculty()
        return fac

    @http.route('/my/rollcall', type='http', auth='user', website=True)
    def rollcall_index(self, **kw):
        import datetime as _dt
        fac = self._faculty_or_none()
        if not fac:
            return request.render('edu_telegram.ops_message', {
                'msg': '仅教师可点名。'})
        d0 = _dt.datetime.combine(_dt.date.today(), _dt.time.min)
        sessions = request.env['op.session'].sudo().search(
            [('faculty_id', '=', fac.id),
             ('start_datetime', '>=', d0),
             ('start_datetime', '<', d0 + _dt.timedelta(days=7))],
            order='start_datetime asc')
        return request.render('edu_telegram.rollcall_index', {
            'sessions': sessions})

    @http.route('/my/rollcall/<int:session_id>', type='http',
                auth='user', website=True)
    def rollcall_form(self, session_id, saved=None, **kw):
        fac = self._faculty_or_none()
        Session = request.env['op.session'].sudo()
        ses = Session.browse(session_id)
        if not ses.exists() or ses.faculty_id.id != (fac and fac.id):
            return request.render('edu_telegram.ops_message', {
                'msg': '无此课或不是你的课。'})
        Register = request.env['op.attendance.register'].sudo()
        reg = Register.search(
            [('course_id', '=', ses.course_id.id),
             ('batch_id', '=', ses.batch_id.id)], limit=1)
        if not reg:
            reg = Register.create({
                'name': '自动考勤册 %s' % ses.course_id.code,
                'code': 'AUTO%s' % ses.course_id.id,
                'course_id': ses.course_id.id,
                'batch_id': ses.batch_id.id})
        Sheet = request.env['op.attendance.sheet'].sudo()
        import datetime as _dt
        sheet = Sheet.search([
            ('register_id', '=', reg.id),
            ('session_id', '=', ses.id),
            ('attendance_date', '=', _dt.date.today())], limit=1)
        students = request.env['op.student.course'].sudo().search(
            [('batch_id', '=', ses.batch_id.id)]).mapped('student_id')
        lines = {l.student_id.id: l
                 for l in request.env['op.attendance.line'].sudo().search(
                     [('attendance_id', 'in',
                       (sheet and sheet.ids or []))])}
        rows = []
        for st in students:
            l = lines.get(st.id)
            rows.append({'stu': st, 'line': l,
                         'present': not l or l.present,
                         'late': bool(l and l.late),
                         'absent': bool(l and l.absent)})
        return request.render('edu_telegram.rollcall_page', {
            'ses': ses, 'sheet': sheet, 'rows': rows, 'saved': bool(saved)})

    @http.route('/my/rollcall/<int:session_id>/save', type='http',
                auth='user', methods=['POST'], csrf=True)
    def rollcall_save(self, session_id, **kw):
        fac = self._faculty_or_none()
        ses = request.env['op.session'].sudo().browse(session_id)
        if not ses.exists() or not fac or                 ses.faculty_id.id != fac.id:
            return request.redirect('/my/rollcall')
        Register = request.env['op.attendance.register'].sudo()
        reg = Register.search([('course_id', '=', ses.course_id.id),
                               ('batch_id', '=', ses.batch_id.id)], limit=1)
        if not reg:
            reg = Register.create({
                'name': '自动考勤册 %s' % ses.course_id.code,
                'code': 'AUTO%s' % ses.course_id.id,
                'course_id': ses.course_id.id,
                'batch_id': ses.batch_id.id})
        Sheet = request.env['op.attendance.sheet'].sudo()
        import datetime as _dt
        today = _dt.date.today()
        sheet = Sheet.search([('register_id', '=', reg.id),
                              ('session_id', '=', ses.id),
                              ('attendance_date', '=', today)], limit=1)
        if not sheet:
            sheet = Sheet.create({'register_id': reg.id,
                                  'session_id': ses.id,
                                  'course_id': ses.course_id.id,
                                  'batch_id': ses.batch_id.id,
                                  'attendance_date': today})
        Line = request.env['op.attendance.line'].sudo()
        for key, val in kw.items():
            if not key.startswith('st_'):
                continue
            sid = int(key[3:])
            flags = {'present': False, 'excused': False,
                     'absent': False, 'late': False}
            flags[val] = True
            line = Line.search([('attendance_id', '=', sheet.id),
                                ('student_id', '=', sid)], limit=1)
            vals = {'attendance_id': sheet.id, 'student_id': sid,
                    'attendance_date': today, **flags}
            if line:
                line.write(flags)
            else:
                Line.create(vals)
        return request.redirect('/my/rollcall/%d?saved=1' % session_id)


class MarksPortal(http.Controller):

    def _faculty_or_none(self):
        return RollcallPortal._faculty_or_none(self)

    @http.route('/my/marks', type='http', auth='user', website=True)
    def marks_index(self, **kw):
        fac = self._faculty_or_none()
        if not fac:
            return request.render('edu_telegram.ops_message', {
                'msg': '仅教师可录入成绩。'})
        import datetime as _dt
        exams = request.env['op.exam'].sudo().search(
            [('responsible_id', 'in', [fac.id]),
             ('end_time', '<', _dt.datetime.now())],
            order='start_time desc')
        return request.render('edu_telegram.marks_index', {'exams': exams})

    @http.route('/my/marks/<int:exam_id>', type='http', auth='user',
                website=True)
    def marks_form(self, exam_id, saved=None, **kw):
        fac = self._faculty_or_none()
        Exam = request.env['op.exam'].sudo()
        exam = Exam.browse(exam_id)
        if not exam.exists() or not fac or                 fac.id not in exam.responsible_id.ids:
            return request.render('edu_telegram.ops_message', {
                'msg': '无此考试或不是负责人。'})
        attendees = request.env['op.exam.attendees'].sudo().search(
            [('exam_id', '=', exam.id)])
        return request.render('edu_telegram.marks_page', {
            'exam': exam, 'attendees': attendees, 'saved': bool(saved)})

    @http.route('/my/marks/<int:exam_id>/save', type='http', auth='user',
                methods=['POST'], csrf=True)
    def marks_save(self, exam_id, **kw):
        fac = self._faculty_or_none()
        exam = request.env['op.exam'].sudo().browse(exam_id)
        if not exam.exists() or not fac or                 fac.id not in exam.responsible_id.ids:
            return request.redirect('/my/marks')
        Att = request.env['op.exam.attendees'].sudo()
        for key, val in kw.items():
            if key.startswith('mk_') and str(val).isdigit():
                att = Att.browse(int(key[3:]))
                if att.exists() and att.exam_id.id == exam.id:
                    att.write({'marks': int(val)})
        return request.redirect('/my/marks/%d?saved=1' % exam_id)
