# -*- coding: utf-8 -*-
"""LMS 在线课程门户（/my/courses 三页 + 四视角分流）。

设计文档：docs/plans/lms-design.md。角色分流与数据域对齐
scheduling.py 的做法；时间/文本格式化一律在控制器完成，
模板只做纯输出（规避 Odoo19 t-options widget 陷阱）。
"""
from odoo import fields, http
from odoo.http import request

from odoo.addons.edu_schedule.models.identity import users_of_profile

from .main import current_student, student_course
from .roles import current_faculty, current_parent

MAX_COURSES = 50

#: 课代表发通知的字数上限（设计 §8-13 建议 500 字；频率限制待校长拍板）
REP_NOTICE_MAX = 500


def _subjects_for(student, fac, parent, user):
    """按角色返回可见的课程科目 recordset 及视角标签。"""
    env = request.env
    Subject = env['op.subject'].sudo()
    if fac or user.has_group('base.group_user'):
        return Subject.search([]), ('faculty' if fac else 'staff')
    if student:
        # 个人选课联动：学生视角 = 在读档案 op.student.course.subject_ids
        # （报课通过后自动出现新科目卡；仅加科目而课程不变也即时联动）。
        # 无档案学生不泄露全目录（保持空列表）。
        scs = env['op.student.course'].sudo().search([
            ('student_id', '=', student.id)])
        subjects = scs.mapped('subject_ids')
        return subjects, 'student'
    if parent:
        Scs = env['op.student.course'].sudo()
        scs = Scs.search([('student_id', 'in', parent.student_ids.ids),
                          ('state', '=', 'running')])
        if not scs:
            scs = Scs.search([('student_id', 'in', parent.student_ids.ids)])
        subjects = scs.mapped('subject_ids')
        return subjects, 'parent'
    return Subject.browse(()), 'guest'


class EduLmsPortal(http.Controller):

    # ------------------------- 课程列表 -------------------------
    @http.route('/my/courses', type='http', auth='user', website=True)
    def my_courses(self, child_id=None, **kw):
        env = request.env
        student = current_student()
        fac = current_faculty()
        parent = current_parent()

        subjects, role = _subjects_for(student, fac, parent, env.user)

        # 进度统计对象：学生=自己；家长=孩子合集（合并视图）
        progress_student_ids = []
        if role == 'student' and student:
            progress_student_ids = [student.id]
        elif role == 'parent':
            progress_student_ids = parent.student_ids.ids

        Prog = env['edu.lesson.progress'].sudo()
        Lesson = env['edu.lesson'].sudo().search([('state', '=', 'published')])

        # 课代表徽标：只有**本人**在任的课程才渲染（实时判定，含期限）
        rep_ids = []
        if role == 'student' and student:
            rep_ids = env['edu.course.rep'].sudo().active_subject_ids_of(student)

        cards = []
        for sub in subjects[:MAX_COURSES]:
            lessons = Lesson.filtered(lambda l: l.subject_id.id == sub.id)
            done_keys = set()
            if progress_student_ids:
                done_keys = {
                    (p.lesson_id.id) for p in Prog.search([
                        ('student_id', 'in', progress_student_ids),
                        ('lesson_id', 'in', lessons.ids),
                        ('state', '=', 'done')])
                }
            total = len(lessons)
            done = sum(1 for l in lessons if l.id in done_keys)
            pct = round(done * 100.0 / total) if total else 0
            cards.append({
                'subject': sub,
                'total': total,
                'done': done,
                'pct': pct,
                'href': f'/my/courses/{sub.id}',
                'is_rep': sub.id in rep_ids,
            })
        title = {'faculty': '全部课程', 'staff': '全部课程',
                 'parent': '孩子的课程', 'guest': '课程'} \
            .get(role, '我的课程')

        return request.render('edu_portal.edu_lms_courses', {
            'title': title,
            'role': role,
            'cards': cards,
            'page_name': 'lms_courses',
        })

    # ------------------------- 课次列表 -------------------------
    @http.route('/my/courses/<int:subject_id>', type='http',
                auth='user', website=True)
    def course_lessons(self, subject_id, **kw):
        env = request.env
        student = current_student()
        fac = current_faculty()
        parent = current_parent()
        subjects, role = _subjects_for(student, fac, parent, env.user)
        subject = env['op.subject'].sudo().browse(subject_id)
        if not subject.exists() or subject not in subjects:
            return request.redirect('/my/courses')

        lessons = env['edu.lesson'].sudo().search([
            ('subject_id', '=', subject.id),
            ('state', '=', 'published')], order='sequence asc, id asc')

        learner_ids = []
        if role == 'student' and student:
            learner_ids = [student.id]
        elif role == 'parent':
            learner_ids = parent.student_ids.ids
        Prog = env['edu.lesson.progress'].sudo()
        # 课代表面板入口：仅当**本人**是该课在任课代表时渲染（实时判定）
        is_rep = False
        if role == 'student' and student:
            is_rep = bool(env['edu.course.rep'].sudo().active_rep_for(
                student, subject))

        prog_map = {}
        if learner_ids and lessons:
            for p in Prog.search([('student_id', 'in', learner_ids),
                                  ('lesson_id', 'in', lessons.ids)]):
                prog_map[p.lesson_id.id] = p.state

        items = [{
            'lesson': l,
            'done': prog_map.get(l.id) == 'done',
        } for l in lessons]
        done_n = sum(1 for i in items if i['done'])
        pct = round(done_n * 100.0 / len(items)) if items else 0

        return request.render('edu_portal.edu_lms_lessons', {
            'title': subject.name or '课次列表',
            'role': role,
            'subject': subject,
            'items': items,
            'done_n': done_n,
            'total': len(items),
            'pct': pct,
            'is_rep': is_rep,
            'page_name': 'lms_lessons',
        })

    # ------------------------- 课次详情 -------------------------
    @http.route('/my/courses/lesson/<int:lesson_id>', type='http',
                auth='user', website=True)
    def lesson_detail(self, lesson_id, **kw):
        env = request.env
        student = current_student()
        fac = current_faculty()
        parent = current_parent()
        lesson = env['edu.lesson'].sudo().browse(lesson_id)
        # 独立评审 Major#1：详情页同样受科目可见域门禁，
        # 防止拼 URL 枚举阅读全部已发布课件
        subjects, role = _subjects_for(student, fac, parent, env.user)
        if not lesson.exists() or lesson.state != 'published' \
                or lesson.subject_id not in subjects:
            return request.redirect('/my/courses')

        learner_ids = []
        if student:
            learner_ids = [student.id]
        elif parent:
            learner_ids = parent.student_ids.ids
        my_state = None
        if learner_ids:
            p = env['edu.lesson.progress'].sudo().search([
                ('lesson_id', '=', lesson.id),
                ('student_id', 'in', learner_ids),
                ('state', '=', 'done')], limit=1)
            my_state = p.state if p else None

        safe_video = ''
        if lesson.type == 'video' and (lesson.video_url or '').startswith(
                'https://'):
            safe_video = lesson.video_url

        return request.render('edu_portal.edu_lms_lesson', {
            'title': lesson.name,
            'role': role,
            'lesson': lesson,
            'safe_video': safe_video,
            'my_state': my_state,
            # D 组第一批（P2）：「标记完成」是**学生本人**的动作 —— 写路由
            # lesson_done 第一行就是 current_student()，非学生一律 303 不落库。
            # 此前模板只看 my_state，于是教师/教务（内部用户走 _subjects_for 的全目录
            # 分支、learner_ids 为空 ⇒ my_state 恒为 None）也看到一颗「标记完成」按钮，
            # 点下去什么都不会发生（角色语义错位 + 按了没用）。这里如实告诉模板
            # 「本次访问是否具备该动作的资格」，由模板决定渲染按钮还是只读说明。
            # 判据与写路由**同一条件**（有学生档案），不新增第二套口径。
            'can_mark': bool(student),
            'subject': lesson.subject_id,
            'page_name': 'lms_lesson',
        })

    @http.route('/my/courses/lesson/<int:lesson_id>/done', type='http',
                auth='user', methods=['POST'], website=True, csrf=True)
    def lesson_done(self, lesson_id, **post):
        student = current_student()
        if not student:
            return request.redirect('/my/courses')
        lesson = request.env['edu.lesson'].sudo().browse(lesson_id)
        # 独立评审 Major#2：仅本班（可见科目）内的课次可标记完成
        subjects, _role = _subjects_for(student, None, None, request.env.user)
        if lesson.exists() and lesson.state == 'published' \
                and lesson.subject_id in subjects:
            lesson.mark_done(student)
        return request.redirect(f'/my/courses/lesson/{lesson_id}')

    # ==================================================================
    # 课代表（docs/plans/course-representative-design.md §5.1）
    #
    # 铁律：**所有权限点先过 edu.course.rep.is_active_now() 那条链**
    # （active_rep_for / active_subject_ids_of），禁止在这里直接判 state。
    # 越权一律按「不存在」处理（303 回课程页/列表），不给任何「禁用按钮」
    # —— 禁用只是不能点，POST 重放仍能提交。
    # ==================================================================

    @http.route('/my/courses/<int:subject_id>/rep', type='http',
                auth='user', website=True)
    def course_rep_panel(self, subject_id, **kw):
        """课代表面板：本课程同学 / 发通知 / 待批请假 / 点名 / 辞去。"""
        env = request.env
        subject = env['op.subject'].sudo().browse(subject_id)
        student, slot = _rep_slot_of(subject)
        if not slot:
            return request.redirect('/my/courses')
        roster = _roster_of(subject)
        Leave = env['edu.leave'].sudo()
        leaves = Leave.search(Leave.rep_queue_domain(slot), order='id desc')
        return request.render('edu_portal.edu_lms_rep_panel', {
            'title': '%s · 课代表' % (subject.name or ''),
            'page_name': 'lms_rep',
            'subject': subject,
            'student': student,
            'slot': slot,
            'deadline': slot.deadline_realtime(),
            'deadline_source': slot.deadline_source,
            'roster': roster,
            'roster_n': len(roster),
            'leaves': leaves,
            'leave_n': len(leaves),
            'leave_type_labels': _LEAVE_TYPE_LABELS,
            'assignment_stats': _assignment_stats(subject, student),
            'today': fields.Date.today().isoformat(),
            'notice_max': REP_NOTICE_MAX,
            'box': kw.get('box') or '',
        })

    @http.route('/my/courses/<int:subject_id>/rep/notify', type='http',
                auth='user', methods=['POST'], website=True, csrf=True)
    def course_rep_notify(self, subject_id, **post):
        """给本课程同学发通知（收件人 = 本课程同学账号并集，排除课代表自己）。"""
        env = request.env
        subject = env['op.subject'].sudo().browse(subject_id)
        student, slot = _rep_slot_of(subject)
        if not slot:
            return request.redirect('/my/courses')
        body = (post.get('body') or '').strip()[:REP_NOTICE_MAX]
        sent = 0
        if body:
            roster = _roster_of(subject)
            mine = users_of_profile(student.sudo())
            recipients = users_of_profile(
                env['op.student'].sudo().browse(
                    [r['student'].id for r in roster])) - mine
            msg = env['edu.message'].sudo()
            for user in recipients:
                if msg._notify_event('course_rep_notice', user, body,
                                     sender_uid=env.user.id):
                    sent += 1
            env['edu.audit.log'].sudo()._log(
                '课代表发通知', 'op.subject', subject.id, subject.name or '',
                '「%s」发通知给本课程同学，收件人 %d 人：%s'
                % (subject.name or '', sent, body[:120]))
        return request.redirect(
            '/my/courses/%d/rep?box=notified_%d' % (subject_id, sent))

    @http.route('/my/courses/<int:subject_id>/rep/leave/set_state',
                type='http', auth='user', methods=['POST'], website=True,
                csrf=True)
    def course_rep_leave_set_state(self, subject_id, **post):
        """课代表审批**本课程出勤类**请假（通过 / 驳回）。

        服务端**重新判定**（不信前端）：在任 + 严格同课程 + 非本人 + 出勤类；
        任一条不成立 => 按不存在处理，**不写任何字段**（含直接 POST 重放）。
        """
        env = request.env
        subject = env['op.subject'].sudo().browse(subject_id)
        student, slot = _rep_slot_of(subject)
        if not slot:
            return request.redirect('/my/courses')
        new_state = post.get('state', '')
        if new_state not in ('approved', 'refused'):
            return request.redirect('/my/courses/%d/rep' % subject_id)
        try:
            lid = int(post.get('leave_id', 0) or 0)
        except ValueError:
            lid = 0
        leave = env['edu.leave'].sudo().browse(lid)
        ok = False
        if leave.exists():
            ok = leave.rep_set_state(
                slot, new_state, (post.get('reject_reason') or '').strip())
        return request.redirect('/my/courses/%d/rep?box=%s'
                                % (subject_id, 'done' if ok else 'denied'))

    @http.route('/my/courses/<int:subject_id>/rep/attendance', type='http',
                auth='user', methods=['POST'], website=True, csrf=True)
    def course_rep_attendance(self, subject_id, **post):
        """课代表提交点名（**待老师确认**，设计 §2.3 队长裁定 (b+)）。

        提交后 sheet 停在 state='start'；考勤行程（op.attendance.line）
        **要等老师确认才落**，所以确认前统计一字不变。
        """
        env = request.env
        subject = env['op.subject'].sudo().browse(subject_id)
        student, slot = _rep_slot_of(subject)
        if not slot:
            return request.redirect('/my/courses')
        try:
            adate = fields.Date.to_date(post.get('date')) \
                or fields.Date.today()
        except (TypeError, ValueError):
            adate = fields.Date.today()
        proposal = {}
        for row in _roster_of(subject):
            status = post.get('status_%d' % row['student'].id, 'present')
            proposal[row['student'].id] = (
                status if status in ('present', 'late', 'absent')
                else 'present')
        result, _sheet = env['op.attendance.sheet'].sudo().rep_submit(
            slot, subject, adate, proposal)
        return request.redirect('/my/courses/%d/rep?box=att_%s'
                                % (subject_id, result))

    @http.route('/my/courses/<int:subject_id>/rep/release', type='http',
                auth='user', methods=['POST'], website=True, csrf=True)
    def course_rep_release(self, subject_id, **post):
        """辞去课代表 —— **唯一的自主动作**（无提名 / 指定 / 转交）。"""
        env = request.env
        subject = env['op.subject'].sudo().browse(subject_id)
        student, slot = _rep_slot_of(subject)
        if not slot:
            return request.redirect('/my/courses')
        env['edu.course.rep'].sudo().release(student, subject)
        return request.redirect('/my/courses?box=rep_released')


#: 请假类型中文标签（与 roles.py:_leave_detail_vals 同口径）
_LEAVE_TYPE_LABELS = {
    'sick': '病假', 'legal': '法定假', 'casual': '事假', 'other': '其他',
}


def _rep_slot_of(subject):
    """(当前学生, 该课在任课代表槽位) —— 不在任则槽位为空 recordset。

    判定只走 edu.course.rep.active_rep_for（= state 且**实时重算**的期限），
    这里**不得**出现任何 state == 'active' 的直接判断。
    """
    student = current_student()
    if not student or not subject:
        return student, request.env['edu.course.rep'].sudo().browse()
    slot = request.env['edu.course.rep'].sudo().active_rep_for(student, subject)
    return student, slot


def _roster_of(subject):
    """本课程同学名单（按 **subject** 口径）。

    渲染字段**逐字沿用** contacts.py:148-151 的 {'name','class_name'}
    —— 只给姓名 + 班级：不给学号、邮箱、手机、头像、成绩。
    """
    scs = request.env['op.student.course'].sudo().search([
        ('subject_ids', 'in', subject.ids),
        ('state', '=', 'running')])
    rows, order = {}, []
    for sc in scs:
        stu = sc.student_id
        if not stu:
            continue
        if stu.id not in rows:
            rows[stu.id] = {'student': stu, 'name': stu.name or '',
                            'classes': [], 'has_batch': bool(sc.batch_id)}
            order.append(stu.id)
        cls = sc.batch_id.name if sc.batch_id else ''
        if cls and cls not in rows[stu.id]['classes']:
            rows[stu.id]['classes'].append(cls)
    out = []
    for sid in order:
        row = rows[sid]
        row['class_name'] = ' / '.join(row['classes'])
        out.append(row)
    return out


def _assignment_stats(subject, student):
    """本课程作业的**统计**（需求⑧：只给「还有几人没交」，**不给名单**）。

    每张作业只回三个数：应交人数 / 已交人数 / 还有几人没交。
    ⚠ 绝不回任何未交学生姓名或 id —— 模板里也不许把它们渲染出来。
    """
    env = request.env
    assignments = env['op.assignment'].sudo().search([
        ('courses_subjects', 'in', subject.ids),
        ('state', 'in', ('publish', 'finish')),
    ], order='submission_date desc, id desc', limit=20)
    out = []
    for asg in assignments:
        due = len(asg.allocation_ids)
        if not due:
            scs = env['op.student.course'].sudo().search([
                ('batch_id', '=', asg.batch_id.id),
                ('subject_ids', 'in', subject.ids)])
            due = len(scs.mapped('student_id'))
        submitted = len(asg.assignment_sub_line.mapped('student_id'))
        out.append({
            'name': asg.name or asg.grading_assignment_id.name or '',
            'due': due,
            'submitted': submitted,
            'missing': max(0, due - submitted),
        })
    return out

