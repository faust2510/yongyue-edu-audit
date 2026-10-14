# -*- coding: utf-8 -*-
"""游客可访问的公开页：课程列表 / 在线考试 / 数字图书馆分类入口。"""
from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import pager


def _page_param(kw):
    try:
        return max(1, int(kw.get('page', 1) or 1))
    except (TypeError, ValueError):
        return 1


def _course_param(kw):
    """解析 ?course=N；缺失或非整数返回 None（回退列表）。"""
    try:
        return int(kw.get('course') or 0)
    except (TypeError, ValueError):
        return None


def _media_type_param(kw):
    """解析 ?type=N；缺失或非整数返回 None（回退分类总览）。"""
    try:
        return int(kw.get('type') or 0) or None
    except (TypeError, ValueError):
        return None


# op.course.evaluation_type 的展示文案（B8 课程详情用）
COURSE_EVAL_LABELS = {
    'normal': '常规考核',
    'GPA': 'GPA 绩点',
    'CWA': 'CWA 加权平均',
    'CCE': 'CCE 连续综合评价',
}


class EduPublic(http.Controller):

    @http.route('/courses', type='http', auth='public', website=True)
    def public_courses(self, **kw):
        """公开课程列表；?course=N 时渲染该课程详情（B8）。

        course 参数缺失 / 非整数 / 无对应课程时一律回退列表页，
        游客可访问（auth 保持 public）。
        """
        Course = request.env['op.course'].sudo()
        course_id = _course_param(kw)
        course = Course.search([('id', '=', course_id)], limit=1) \
            if course_id else Course.browse()
        if course:
            values = {
                'title': course.name or '课程详情',
                'course': course,
                'subjects': course.subject_ids,
                'eval_label': COURSE_EVAL_LABELS.get(course.evaluation_type, ''),
            }
            return request.render('edu_public.edu_course_detail', values)
        page = _page_param(kw)
        STEP = 9
        total = Course.search_count([])
        courses = Course.search([], order='id asc',
                                limit=STEP, offset=(page - 1) * STEP)
        values = {
            'title': '课程目录',
            'courses': courses,
            'pager': pager('/courses', total=total, page=page, step=STEP),
        }
        return request.render('edu_public.edu_courses', values)

    @http.route('/online-exams', type='http', auth='public', website=True)
    def public_exams(self, **kw):
        page = _page_param(kw)
        STEP = 9
        Exam = request.env['op.exam'].sudo()
        total = Exam.search_count([])
        exams = Exam.search([], order='start_time desc',
                            limit=STEP, offset=(page - 1) * STEP)
        values = {
            'title': '在线考试',
            'exams': exams,
            'pager': pager('/online-exams', total=total, page=page, step=STEP),
        }
        return request.render('edu_public.edu_online_exams', values)

    @http.route('/digital-library', type='http', auth='public', website=True)
    def digital_library(self, **kw):
        """数字图书馆公开页；?type=N 时按媒体类型过滤并展示媒体列表。

        历史上分类卡片链接指向 /library/media?filterby=N，该路由在
        edu_portal 中为 auth='user'，游客点击被 303 到登录页。
        现改为停留在本公开页（?type=N），游客可完整浏览（B5）。
        """
        Media = request.env['op.media'].sudo()
        MediaType = request.env['op.media.type'].sudo()
        types = MediaType.search([])
        cards = []
        for mt in types:
            cards.append({
                'id': mt.id,
                'name': mt.name or '',
                'count': Media.search_count([('media_type_id', '=', mt.id)]),
            })
        total_media = Media.search_count([])
        media_type_id = _media_type_param(kw)
        if media_type_id and not MediaType.browse(media_type_id).exists():
            media_type_id = None  # 无效类型 id 一律回退分类总览
        current_type = MediaType.browse(media_type_id) \
            if media_type_id else MediaType.browse()
        domain = [('media_type_id', '=', media_type_id)] \
            if media_type_id else []
        medias = Media.search(domain, order='name asc')
        values = {
            'title': '数字图书馆',
            'cards': cards,
            'total_media': total_media,
            'current_type': current_type,
            'medias': medias,
        }
        return request.render('edu_public.edu_digital_library', values)

    @http.route('/digital-library/material/<int:mid>', type='http',
                auth='public', website=True)
    def digital_library_material(self, mid, **kw):
        """公开媒体详情页（B5）；无效 id 回退 /digital-library。"""
        media = request.env['op.media'].sudo().browse(mid).exists()
        if not media:
            return request.redirect('/digital-library')
        return request.render('edu_public.edu_digital_library_material', {
            'title': media.name or '媒体详情',
            'media': media,
            'media_type': media.media_type_id,
            'authors': media.author_ids,
            'publishers': media.publisher_ids,
            'subjects': media.subject_ids,
        })

    @http.route('/booking', type='http', auth='public', website=True)
    def booking(self, **kw):
        return request.render('edu_public.edu_booking', {
            'title': '在线预约',
        })


    @http.route('/alumni', type='http', auth='public', website=True)
    def alumni(self, **kw):
        # 安全审计 F3：本页 auth='public'，原实现 search([], limit=12) 零过滤，
        # 匿名访问即渲染在读学生的真实姓名与 partner id（生产已实测可匿名爬取名册）。
        # 收口（最保守口径）：匿名访客不读取、也不渲染任何真实姓名/头像/人员 id；
        # 登录用户保持原行为。是否整页改为需登录待校长拍板。
        if request.env.user._is_public():
            return request.render('edu_public.edu_alumni', {
                'title': '校友', 'students': None})
        students = request.env['op.student'].sudo().search([], limit=12)
        return request.render('edu_public.edu_alumni', {
            'title': '校友', 'students': students})

    @http.route('/campus/jobs', type='http', auth='public', website=True)
    def campus_jobs(self, **kw):
        """公开招聘岗位：自研 edu.job.posting（已发布），替代原 hr.job 数据源。

        2026-10-06：加**跨模块守卫**。edu.job.posting 由 edu_life 定义，而本模块（edu_public）
        不依赖 edu_life —— 模板层「靠渲染期侥幸能用」的问题已在 2026-10-06 的架构审计里清零，
        模型层这一处是**公开路由上的裸调**：模型一旦不在注册表（模块被卸载/未装），这里会 500。
        守卫写法沿用本仓既有惯例（`in request.env`），不新增依赖、不成环。"""
        if 'edu.job.posting' not in request.env:
            return request.render('edu_public.edu_campus_jobs', {
                'title': '校园工作', 'jobs': []})
        jobs = request.env['edu.job.posting'].sudo().search(
            [('state', '=', 'published')])
        return request.render('edu_public.edu_campus_jobs', {
            'title': '校园工作', 'jobs': jobs})

    @http.route(['/campus/jobs/<int:posting_id>',
                 '/campus/jobs/<int:posting_id>/sent'], type='http',
                auth='public', website=True)
    def campus_job_detail(self, posting_id, **kw):
        # 2026-10-06：同 campus_jobs，公开路由上的跨模块软引用必须带守卫
        if 'edu.job.posting' not in request.env:
            return request.redirect('/campus/jobs')
        posting = request.env['edu.job.posting'].sudo().browse(posting_id)
        if not posting.exists() or posting.state != 'published':
            return request.redirect('/campus/jobs')
        # 路径字面量 /sent 不会映射为参数，按实际路径判断
        sent = request.httprequest.path.endswith('/sent')
        return request.render('edu_public.edu_campus_job_detail', {
            'title': posting.name,
            'posting': posting,
            'sent': sent,
        })

    @http.route('/campus/jobs/<int:posting_id>/apply', type='http',
                methods=['POST'], auth='public', website=True, csrf=True)
    def campus_job_apply(self, posting_id, **post):
        """公开投递：honeypot 反机器人 + 必填校验，入库仅限安全字段。"""
        posting = request.env['edu.job.posting'].sudo().browse(posting_id)
        if post.get('website_url') or not posting.exists() \
                or posting.state != 'published':
            return request.redirect('/campus/jobs')
        name = (post.get('name') or '').strip()
        phone = (post.get('phone') or '').strip()
        if not name or not phone:
            return request.redirect(f'/campus/jobs/{posting.id}')
        request.env['edu.job.application'].sudo().create({
            'posting_id': posting.id,
            'name': name[:60],
            'phone': phone[:30],
            'email': (post.get('email') or '').strip()[:80],
            'education': post.get('education') or 'other',
            'note': (post.get('note') or '')[:1000],
        })
        return request.redirect(f'/campus/jobs/{posting.id}/sent')

    @http.route('/alumni/job/card', type='http', auth='public', website=True)
    def alumni_job_card(self, **kw):
        jobs = request.env['edu.job.posting'].sudo().search(
            [('state', '=', 'published')])
        return request.render('edu_public.edu_alumni_jobs', {
            'title': '校友招聘', 'jobs': jobs})

    @http.route('/alumni/jobs', type='http', auth='public', website=True)
    def alumni_jobs_page(self, **kw):
        """校友与就业（v2.1-A9）：校友岗位列表，数据复用 /alumni/job/list
        的来源模型 edu.alumni.job（Backoffice 发布，公开页只读展示）。

        支持 ?state=recruiting|pending|closed 过滤；模型未安装（edu_portal
        缺位）时优雅空态，绝不让公开页 500。
        """
        stats = {'total': 0, 'recruiting': 0, 'pending': 0, 'closed': 0}
        jobs = []
        state_filter = (kw.get('state') or '').strip()
        if state_filter not in ('recruiting', 'pending', 'closed'):
            state_filter = ''
        if 'edu.alumni.job' in request.env:
            Job = request.env['edu.alumni.job'].sudo()
            domain = [('state', '=', state_filter)] if state_filter else []
            jobs = Job.search(domain, order='start_date desc, id desc')
            for k in ('recruiting', 'pending', 'closed'):
                stats[k] = Job.search_count([('state', '=', k)])
            stats['total'] = sum(stats.values())
        return request.render('edu_public.edu_alumni_jobs_page', {
            'title': '校友与就业',
            'jobs': jobs,
            'stats': stats,
            'state_filter': state_filter,
            'state_labels': {
                'recruiting': '招聘中', 'pending': '待定',
                'closed': '已结束',
            },
            'pay_labels': {
                'monthly': '月薪', 'weekly': '周薪', 'yearly': '年薪',
            },
        })

    @http.route('/courses-offered', type='http', auth='public', website=True)
    def courses_offered(self, **kw):
        courses = request.env['op.course'].sudo().search([])
        return request.render('edu_public.edu_courses_offered', {
            'title': '开设课程', 'courses': courses})

    @http.route('/program-offered', type='http', auth='public', website=True)
    def program_offered(self, **kw):
        programs = request.env['op.program'].sudo().search([])
        return request.render('edu_public.edu_program_offered', {
            'title': '培养项目', 'programs': programs})


    @http.route('/my-courses', type='http', auth='user', website=True)
    def my_courses(self, **kw):
        """我的课程（对齐原站 LMS 入口）：展示在读课程卡片。

        第 2 期（enroll-v2）：课程卡新增「进入学习」入口——学生点击进入
        LMS /my/courses 学习其档案科目（个人选课联动）。数据以
        op.student.course 为准，非学生（如内部账号）仍展示全部课程目录。
        """
        student = request.env['op.student'].sudo().search(
            [('user_id', '=', request.env.uid)], limit=1)
        scs = request.env['op.student.course'].sudo().search(
            [('student_id', '=', student.id)]) if student else \
            request.env['op.student.course'].sudo().search([])
        courses = scs.mapped('course_id')
        course_items = []
        for c in courses:
            # 2026-10-03（跨页一致性复核）：`subject_n` 是**该专业全部科目**（课程目录），
            # 而卡片点「进入学习」到的页面上写的是「N 门在修科目」（学生的在修数）。
            # 实测：本卡显示「（14 门科目）」、目的地显示「1 门在修科目」——**同一个词、差 14 倍**，
            # 学生只会以为哪边坏了。两处口径都要给，就得让卡片把**两个数**都说清楚。
            # `enrolled_n` 与 study.py 的 subject_n 同源（都是 scs.mapped('subject_ids')）⇒ 不至于引入新的不一致。
            enrolled = scs.filtered(lambda s: s.course_id.id == c.id).mapped('subject_ids')
            course_items.append({
                'course': c,
                'subject_n': len(c.subject_ids),
                'enrolled_n': len(enrolled),
                'is_student': bool(student),
            })
        return request.render('edu_public.edu_my_courses', {
            'title': '我的课程', 'courses': course_items,
            'is_student': bool(student)})
