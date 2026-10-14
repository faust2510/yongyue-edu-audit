# -*- coding: utf-8 -*-
"""学生门户复刻控制器。

以 reference/ 目录下抓取的原站 DOM 为蓝本，用开源数据模型重建学生端页面。
"""
import logging

from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.openeducat_core.controllers.app_main import OpeneducatHome
# 裸后台入口收口要用到的「选库」副作用（与 core 的 web_client 同一实现）。
# 注意：odoo.http 里**没有** ensure_db（Odoo 19 它在 web.controllers.utils）。
from odoo.addons.web.controllers.utils import ensure_db

from odoo.addons.edu_schedule.models.identity import student_of_user

# 学号登录的纯函数部分（判据 + 限速键）。放在 controllers 之外、不 import odoo，
# 因此 tests/unit/edu_portal_login_alias_test.py 能离线单测同一份实现。
# 失败计数本身落库（models/login_throttle.py）—— 进程内桶在多 worker 下会被稀释。
from odoo.addons.edu_portal.login_alias import bucket_key, looks_like_gr_no

from .roles import EduParentPortal, current_faculty

_logger = logging.getLogger(__name__)


def current_student():
    """当前登录用户对应的学生记录（无则 None）。

    口径 = identity.student_of_user（双向并集，见
    edu_schedule/models/identity.py）。本函数是**学生侧唯一入口**（batch1/2/3、
    study、scheduling、search、lms、messages、welfare、assets、fees、enroll、
    contacts、calendar 全都用它）—— 这里若自建第二套口径，学生侧整整一片页面
    都会在「账号由脚本新建」时静默落成访客空表。
    """
    return student_of_user(request.env)


def safe_count(model, domain):
    try:
        return request.env[model].sudo().search_count(domain)
    except Exception:
        return 0


def csv_download(filename, header, rows):
    """通用 CSV 导出响应（utf-8-sig 防 Excel 乱码，中文文件名走 RFC5987）。"""
    import csv
    import io

    from odoo.http import content_disposition
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


def assignment_scope_domain(student):
    """学生「自己的作业」的域 —— 门户各处的**唯一口径**。

    2026-10-03 立：同一个域原先在 4 处各写一遍，写法还不一样 ——
    首页 KPI 与待办时间线只按 `batch_id`，作业页按 `batch+course`。
    实测后果（batch 8 共 5 条作业，其中 `course_id=13` 的 2 条不属于该生）：
    · 首页「待完成作业」算成 4（真值 2，已修）；
    · 学业进展页「作业提交 1 / 5」（真值 1 / 3，本轮修）；
    · 全站搜索会把别的课程的作业也搜出来。
    ⇒ 统一到这里：口径一致由**共用同一个函数**保证，而不是靠每处自觉。
    优先级与作业页（batch1）原有写法一致：能同时限定就都限定。
    """
    course, batch = student_course(student)
    if course and batch:
        return ['&', ('course_id', '=', course.id), ('batch_id', '=', batch.id)]
    if batch:
        return [('batch_id', '=', batch.id)]
    if course:
        return [('course_id', '=', course.id)]
    return [('id', '=', 0)]


def student_course(student):
    """学生的在读课程/班级（Odoo 19 拆分到 op.student.course）。"""
    if not student:
        return None, None
    sc = request.env['op.student.course'].sudo().search(
        [('student_id', '=', student.id), ('state', '=', 'running')],
        limit=1) or request.env['op.student.course'].sudo().search(
        [('student_id', '=', student.id)], limit=1)
    return (sc.course_id, sc.batch_id) if sc else (None, None)


def student_study_rows(student):
    """学生学籍卡（只读展示行）：院系 / 学制 / 班级 / 学年。

    值全部来自**学籍记录**，不落 res.partner 的自由文本：
        院系 = op.course.department_id（经在读/最近一条 op.student.course）
        学制 = op.course.edu_level_id（= op.program.level，models/major_track.py:86）
        年级/班级 = op.student.course.batch_id；学年 = academic_years_id
    取不到的项**渲染成「未设置」**（队长 Decision 2·b），绝不给一个能瞎填的
    空文本框冒充学籍，也不编造值（旧实现把 res.partner 的 company_name/vat/street2
    改名成 院系/年级/学制，校长截图里那两个框是空的，而学生的城市「台州市」
    填进了「学制」= street2）。
    """
    # 四行**永远都在**：取不到的项渲染成「未设置」（校长/队长裁定：宁可写「未设置」，
    # 也不给学生一个空白可编辑框冒充学籍，更不能编造值）。
    blank = [('院系', ''), ('学制', ''), ('年级 / 班级', ''), ('学年', '')]
    if not student:
        return blank
    SC = request.env['op.student.course'].sudo()
    sc = SC.search([('student_id', '=', student.id),
                    ('state', '=', 'running')], limit=1) or SC.search(
        [('student_id', '=', student.id)], limit=1)
    if not sc:
        return blank
    course = sc.course_id
    level = ''
    # edu_level_id 由 models/major_track.py:86 加在 op.course 上；老库未升级时
    # 字段可能不在注册表里 ⇒ 守卫一次，缺了就当没有（该行显示「未设置」，不报错）。
    if 'edu_level_id' in course._fields and course.edu_level_id:
        level = course.edu_level_id.name or ''
    return [
        ('院系', course.department_id.name or ''),
        ('学制', level),
        # 年级：本仓的「级」写在班级名里（如「预备科 · 2026级」，见
        # edu_schedule/models/session_ext.py:835 的「各年级分开排」口径）
        ('年级 / 班级', sc.batch_id.name or ''),
        # 学年：op.academic.year 实测存的是「2026-2027」**学年**，不是年级 ⇒
        # 如实叫「学年」，不硬套「年级」（队长 Decision 2 · a）
        ('学年', sc.academic_years_id.name or ''),
    ]


class EduPortalHome(CustomerPortal):

    # --------------- 我的账户 /my/account：学籍卡 + 学号自助填写 ---------------

    def _prepare_my_account_rendering_values(self, redirect='/my', **kwargs):
        """/my/account 渲染值：补学生学籍卡与学号（教师/家长/教务零变化）。

        edu_student 为空时模板整块不渲染 ⇒ 非学生账号既看不到学号，也看不到学籍卡。
        """
        values = super()._prepare_my_account_rendering_values(
            redirect=redirect, **kwargs)
        student = current_student()
        values['edu_student'] = student
        values['edu_study_rows'] = student_study_rows(student)
        values['edu_gr_no'] = (student.gr_no or '') if student else ''
        values['edu_study_hint'] = (
            '' if any(v for _label, v in values['edu_study_rows'])
            else '尚未分班或专业未编排，学籍信息待教务处维护。')
        # 学号表单提交结果（一次性 flash；见 edu_account_gr_no_submit）
        flash = request.session.pop('edu_gr_no_flash', None) or {}
        values['edu_gr_no_error'] = flash.get('error', '')
        values['edu_gr_no_ok'] = bool(flash.get('ok'))
        if student:
            # 学生是个人，没有「公司名称 / 税号」可填：关掉商务字段块。
            # is_used_as_billing 在 Odoo 19 门户模板里**只**用于该块的门控
            # （portal/views/address_templates.xml:196）；这里改的是渲染值，
            # 表单 hidden 字段 use_delivery_as_billing 原样保留 ⇒ 地址语义不变。
            values['is_used_as_billing'] = False
        return values

    @http.route('/my/account/gr-no', type='http', auth='user', website=True,
                methods=['POST'], sitemap=False)
    def edu_account_gr_no_submit(self, edu_gr_no='', **kw):
        """学号提交：**独立表单/独立路由**，刻意不挂在地址表单上。

        为什么不复用 /my/address/submit（实测 + 生产取证）：
        core 19 的地址表单在 use_delivery_as_billing 为真时（/my/account 就是如此）
        要求**整份地址**——name/email/phone/street/city/country_id
        （portal/controllers/portal.py:761-769 把 billing∪delivery 的必填并入，
         :335-346 给出字段集）。生产 24 名学生伙伴里只有 2 名有电话/街道/城市/国家
        （2026-09-25 实测）⇒ 学号若挂在地址表单上，22/24 名学生点了保存只会拿到
        「必填字段不能为空」而学号一个字节也存不下去。
        学号是 op.student 上的字段、与地址无关 ⇒ 独立成表单，互不阻塞。

        结果用**会话 flash** 回显（不放 URL：中文与不可篡改），见
        _prepare_my_account_rendering_values 的读取处。
        写入规则本身在 models/partner_edu.py 的 OpStudentEduGrNo（只空可填一次、
        撞号给人话、写审计）；本方法**绝不抛异常**（门户上抛异常 = traceback 500）。
        """
        student = current_student()
        if not student:
            # 非学生（教师/家长/教务）：学号区根本不渲染，这里也不写、不报错
            return request.redirect('/my/account', code=303)
        reason = student.edu_portal_fill_gr_no(edu_gr_no)
        request.session['edu_gr_no_flash'] = (
            {'error': reason} if reason else {'ok': True})
        return request.redirect('/my/account', code=303)

    # ------------------------- 卡片索引 -------------------------

    def _dashboard_cards(self, student):
        course, batch = student_course(student)
        cnt_att = safe_count('op.attendance.line',
                             [('student_id', '=', student.id)]) if student else 0
        cnt_asg = safe_count('op.assignment',
                             [('batch_id', '=', batch.id)]) if batch else 0
        cnt_exam = safe_count('op.exam',
                              [('course_id', '=', course.id)]) if course else 0
        cnt_ses = safe_count('op.session',
                             [('batch_id', '=', batch.id)]) if batch else 0
        cnt_media = safe_count('op.media.unit', [])
        cnt_queue = safe_count('op.media.queue',
                               [('student_id', '=', student.id)]) if student else 0

        return [
            {'href': '/student/profile', 'title': '学生档案 Profile',
             'desc': '个人信息与学籍数据', 'icon': 'fa-user-circle-o', 'count': 0},
            {'href': '/student/timetable', 'title': '时间表',
             'desc': '每周课程与活动安排', 'icon': 'fa-calendar', 'count': cnt_ses or ''},
            {'href': '/student/attendance', 'title': '出席率 Attendance',
             'desc': '准确管理学生考勤记录', 'icon': 'fa-check-square-o', 'count': cnt_att or ''},
            {'href': '/student/assignment/details', 'title': '作业 Assignments',
             'desc': '高效地跟踪、收集和管理课程作业', 'icon': 'fa-pencil-square-o', 'count': cnt_asg or ''},
            {'href': '/student/exam', 'title': '考试 Exams',
             'desc': '参加并管理各种考试', 'icon': 'fa-file-text-o', 'count': cnt_exam or ''},
            {'href': '/grade-book', 'title': '成绩簿 Gradebook',
             'desc': '分析学生的成绩和表现', 'icon': 'fa-bar-chart', 'count': ''},
            {'href': '/library/media', 'title': '图书馆 Library',
             'desc': '丰富的研究资源', 'icon': 'fa-book', 'count': cnt_media or ''},
            {'href': '/my-library', 'title': '数字图书馆 E-Library',
             'desc': '访问广泛的数字资源进行学习', 'icon': 'fa-tablet', 'count': cnt_queue or ''},
            {'href': '/subject/details', 'title': '学习材料 Materials',
             'desc': '课程配套学习资料', 'icon': 'fa-folder-open-o', 'count': ''},
            {'href': '/my/notice_board/notice', 'title': '布告栏 Notices',
             'desc': '集中分享重要公告和信息', 'icon': 'fa-bullhorn', 'count': ''},
            {'href': '/my/time_off', 'title': '请假 Leave',
             'desc': '处理休假请求和缺勤', 'icon': 'fa-plane', 'count': ''},
            {'href': '/users/result-overview', 'title': '测验结果 Quizzes',
             'desc': '访问和审查测验结果以进行绩效分析', 'icon': 'fa-line-chart', 'count': ''},
            {'href': '/my-courses', 'title': '课程 Courses',
             'desc': '多样化的课程，满足不同的学习需求', 'icon': 'fa-graduation-cap', 'count': ''},
            {'href': '/certificate', 'title': '证书 Certificate',
             'desc': '颁发和管理课程结业证书', 'icon': 'fa-certificate', 'count': ''},
        ]

    @http.route('/my/home', type='http', auth='user', website=True)
    def edu_home(self, **kw):
        student = current_student()
        values = {
            'title': '我的账户',
            'student': student,
            'cards': self._dashboard_cards(student),
            'page_name': 'home',
        }
        return request.render('edu_portal.edu_dashboard', values)

    @http.route('/my', type='http', auth='user', website=True)
    def edu_my_redirect(self, **kw):
        return request.redirect('/my/home')

    # 学生课表已迁至 controllers/scheduling.py
    # （周过滤 + 四视角 + 周导航，排课系统 v2，见 docs/plans/timetable-design.md）


def is_backoffice(user):
    """教务 / 管理员 = 三层策略的第三层（门户应用面板里的后台应用卡片）。"""
    return (user.has_group('base.group_system')
            or user.has_group('openeducat_core.group_op_back_office_admin'))


class EduHomeRedirect(OpeneducatHome):
    """登录落点与门户友好路径（v3 批次1：门户/公开站零 Odoo 跳转）。

    三层策略（用户要求：教师不再被丢进后台）：
    1) 学生 / 家长          → 门户 /my/home
    2) 教师（op.faculty）   → 门户 /my/home（工作台在门户内）
    3) 教务 / 管理员        → 门户应用面板 /apps（卡片直接深链 /odoo/action-<id>）

    第三层口径 2026-10-13 修订（用户实测缺陷）：「每次一开进来先闪一下后台那个蓝顶栏
    （P1）才进门户，这个风格丑爆了」。旧口径是「保留后台 /web + 门户侧栏给一个中性中文
    入口」，而那条链路**必然**先由 core 渲染整页 webclient 外壳（P1 就是它），再靠 JS 的
    _loadDefaultApp 兜底跳门户 ⇒ 稳定复现一帧闪现（客户端补丁永远治不了它）。
    现在裸 /web、/odoo 在服务端直接 303 到 /apps（见下方 web_client），门户侧栏的
    「管理后台」入口随之删除。后台**没有**失去入口：/apps 的应用卡片与后台内浮动的
    「转到您的应用」都是显式深链（/odoo/action-<id>），不走裸入口。

    兼容：/web/login 的 GET 请求 302 到 /login；POST 原样放行——302 会把登录
    表单降级成 GET 从而丢失凭据，因此只对 GET 做别名跳转。
    """

    # 用 auth='public' + website=True 渲染登录页：走的正是网站公开页那一套
    # （公开用户与 request.website 就位 → 顶栏/页脚能正常算出来）。实测
    # auth='none' 的独立路由会在渲染 website.layout 时炸
    # "ValueError: Expected singleton: res.users()"（_compute_menu → ACL）。
    @http.route('/login', type='http', auth='public', website=True,
                sitemap=False)
    def edu_login(self, redirect=None, **kw):
        """友好登录路径（旧 /web/login 302 到这里）。

        已登录用户直接 303 回自己的落地页（门户角色 → /my/home；教务/管理员 →
        应用面板 /apps，2026-10-13 前是裸 /web，那会先渲染一整页后台外壳），
        避免从收藏夹点旧链接时又看到一次登录表单。
        """
        if request.session.uid and not request.params.get('redirect'):
            user = request.env['res.users'].browse(request.session.uid)
            return request.redirect(
                '/apps' if is_backoffice(user) else '/my/home', code=303)
        return EduHomeRedirect.web_login(self, redirect=redirect, **kw)

    # 找回密码是 Odoo 自己的认证工具页（低频、匿名可用）。保留上游实现，
    # 只把对外路径换成 /reset_password，避免页面上出现 /web 链接。
    @http.route('/reset_password', type='http', auth='none', readonly=False)
    def edu_reset_password(self, **kw):
        query = request.httprequest.query_string.decode('utf-8')
        return request.redirect(
            '/web/reset_password' + ('?' + query if query else ''), code=302)

    def _edu_alias_login(self):
        """学号登录（乙，2026-10-12）：把纯数字的「学号」改写成该生的登录名（邮箱）。

        上游 Home.web_login（odoo/addons/web/controllers/home.py）只读
        request.params 里的 login / password / type，所以这里改的就是它读的那一份；
        **不复制**它的渲染逻辑（复制必然与上游漂移，上游一改就错）。
        request.params 是可写 dict（odoo/http.py:2365）。

        三条边界：
          · 输入不像学号（含 @、非纯数字、长度不在 4–20）⇒ 一个字都不改，
            邮箱登录逐字不变；
          · 解析不到（学号不存在 / 该生没有账号）⇒ 也不改：上游照常回
            「Wrong login/password」，**不提示「这个学号不存在」**（否则等于
            把「谁在册」做成可枚举接口）；
          · 限速超限 ⇒ 把 password 置空，让上游按**普通登录失败**渲染
            （空 password 会被上游的 CREDENTIAL_PARAMS 过滤掉）。

        返回限速键（不像学号 / 已被限速时返回 None）：调用方拿它去
        login_alias.note_attempt() 记这次的结果 —— 计数落库、跨 worker 共享。
        """
        typed = (request.params.get('login') or '').strip()
        if not looks_like_gr_no(typed):
            return None
        key = bucket_key(request.httprequest.remote_addr, typed)
        alias = request.env['edu.portal.login.alias'].sudo()
        if alias.blocked_seconds(key) > 0:
            request.params['password'] = ''
            _logger.warning('edu_portal: 学号登录尝试过于频繁，已按普通失败处理')
            # 被限速的请求**不再计数**（否则封禁会被自己的重试无限续期）。
            return None
        real = alias.login_for_gr_no(typed)
        if real:
            request.params['login'] = real
            # 只记长度：学号本身不进日志（与「不记录你是谁」的口径一致）。
            _logger.info('edu_portal: 学号登录已解析到账号（学号长度=%s）', len(typed))
        return key

    def web_login(self, redirect=None, *args, **kw):
        if (request.httprequest.method == 'GET'
                and request.httprequest.path.rstrip('/') == '/web/login'):
            query = request.httprequest.query_string.decode('utf-8')
            # 先把库名写进会话（等价 ensure_db 的副作用）：否则跳到 /login 时
            # 会话仍无库，请求落在 nodb 路由表里 → 404（多库开发环境实测）。
            if request.params.get('db') and not request.session.db:
                request.session.db = request.params['db']
            return request.redirect('/login' + ('?' + query if query else ''),
                                    code=302)
        key = None
        if request.httprequest.method == 'POST':
            key = self._edu_alias_login()
        response = super().web_login(redirect=redirect, *args, **kw)
        if key:
            # 结果落库（成功清零 / 失败累加）—— 用**独立事务**，与请求事务无关。
            request.env['edu.portal.login.alias'].sudo().note_attempt(
                key, bool(request.session.uid))
        if request.params.get('login_success') and not redirect:
            user = request.env.user
            if is_backoffice(user):
                # 上游 OpeneducatHome.web_login 对 base.group_user 一律回
                # '/web?<query>'（本次实测的 302 目标）＝整页后台外壳 + JS 兜底跳转
                # ⇒ 就是用户看到的「一开进来先闪 P1」。这一层不接住，_login_redirect
                # 再对也没用（上游压根不走它）。
                return request.redirect('/apps', code=303)
            return request.redirect('/my/home', code=303)
        return response

    # ===== 裸后台入口收口（2026-10-13）=====
    # 为什么必须重列这四条路由：@http.route 在继承链上是**整体替换**而不是并集
    # （odoo/http.py:891-942 按 reversed(mro) 逐层 merged_routing.update，子类最后写入，
    # 覆盖父类；odoo/http.py:849 的文档也写明「覆盖就必须重新装饰」）。少列一条 = 删掉
    # 那条路由，例如漏掉 '/odoo/<path:subpath>' 会让门户「财务管理」这类
    # /odoo/action-<id> 深链一起 404。四条与 core（odoo/addons/web/controllers/home.py:46）
    # 逐字一致，将来 Odoo 升小版本时若 core 改了这里要跟着改。
    # type/auth 不写等于沿用 core 的合并结果；readonly 也不能写死 —— core 传的是可调用对象
    # _web_client_readonly（会话要 touch，不能锁成只读游标）。
    @http.route(['/web', '/odoo', '/odoo/<path:subpath>',
                 '/scoped_app/<path:subpath>'], type='http', auth='none')
    def web_client(self, s_action=None, subpath=None, **kw):
        """裸 /web、/odoo 不渲染后台外壳，直接 303 到门户应用面板。

        四种情形原样交回 core：
          · 带 subpath（/odoo/action-<id>、/odoo/settings…）—— 那本来就是后台界面；
          · 带 redirect —— 显式跳转，core 自己处理；
          · 带 menu_id —— 旧菜单深链，语义就是「进后台」；
          · 未登录 —— 交回 core，它 303 到 /web/login?redirect=…（登录链路零改动）。

        角色分流不在这里做：目标 /apps 自己按角色算（非内部用户 303 → /my/home，
        见 EduAppsAlias.apps_menu），在这里再判一次只会多一份会漂移的判据。
        """
        if subpath or kw.get('redirect') or kw.get('menu_id'):
            return super().web_client(s_action=s_action, subpath=subpath, **kw)
        # 与 core 同序：先选库，否则多库环境下 request.session.uid 读不到，判定会失效。
        ensure_db()
        if not request.session.uid:
            return super().web_client(s_action=s_action, subpath=None, **kw)
        return request.redirect('/apps', code=303)

    def _login_redirect(self, uid, redirect=None):
        if redirect:
            return super()._login_redirect(uid, redirect)
        user = request.env['res.users'].browse(uid)
        if not user.has_group('base.group_user'):
            return '/my/home'
        if is_backoffice(user):
            return '/apps'
        return '/my/home'

    @http.route('/logout', type='http', auth='user', website=True, sitemap=False)
    def edu_logout(self, **kw):
        """门户友好登出，替代对外可见的 /web/session/logout 链接。"""
        request.session.logout(keep_db=True)
        return request.redirect('/', code=303)


class EduAppsAlias(EduParentPortal):
    """应用面板友好路径：/apps（旧 /openeducat/apps_menu 302 兼容）。

    实现在 controllers/roles.py 的 EduParentPortal.apps_menu；本类只改对外
    路径（roles.py 归「重复劳动自动化」工程师，本任务不改该文件）。
    """

    @http.route('/apps', type='http', auth='public', website=True, sitemap=False)
    def apps_menu(self, **kw):
        # auth='user' 会让学生/家长直接 403（门户用户不是内部用户）；
        # 按角色分流：非内部用户 303 到门户首页（资源面板类入口对学生一律回
        # /my/home —— H-1 起宫格就是首页，/my/apps 对学生亦 303 回本页）。
        if not request.env.user.has_group('base.group_user'):
            return request.redirect('/my/home', code=303)
        return super().apps_menu(**kw)

    @http.route('/openeducat/apps_menu', type='http', auth='public',
                website=True, sitemap=False)
    def apps_menu_legacy(self, **kw):
        if not request.env.user.has_group('base.group_user'):
            return request.redirect('/my/home', code=303)
        return request.redirect('/apps', code=302)


# ⚠ 导入位置有意放在文件末尾：register.py 末尾有延迟导入 `from . import contacts`，
# 而 contacts.py 又 `from .main import current_student`。若在本文件顶部导入
# register，就会形成 main → register → contacts → main 的循环导入（实测
# ImportError: cannot import name 'current_student' from partially initialized
# module ...controllers.main）。放到末尾时 main 的关键符号已定义，环自然解开。
from .register import EduRegister  # noqa: E402


class EduRegisterAlias(EduRegister):
    """注册页友好路径：/register（旧 /web/register 302 兼容）。

    实现在 controllers/register.py 的 EduRegister；本类只改对外路径。
    """

    @http.route('/register', type='http', auth='public', website=True,
                sitemap=True)
    def register_form(self, **kw):
        return super().register_form(**kw)

    @http.route('/register/submit', type='http', auth='public',
                methods=['POST'], website=True, csrf=True)
    def register_submit(self, **post):
        return super().register_submit(**post)

    @http.route('/web/register', type='http', auth='public', website=True,
                sitemap=False)
    def register_form_legacy(self, **kw):
        return request.redirect('/register', code=302)

    @http.route('/web/register/submit', type='http', auth='public',
                methods=['POST'], website=True, csrf=True)
    def register_submit_legacy(self, **post):
        return super().register_submit(**post)
