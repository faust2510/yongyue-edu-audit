# -*- coding: utf-8 -*-
"""学生门户批次2控制器：成绩簿 / 图书馆 / 学习材料 / 布告栏。

外加 /my/home 首页重构（原站五分类折叠结构）——通过继承 main.EduPortalHome
并重写 /my/home 路由实现，不改动 main.py / batch1.*。

数据来源（社区版模型）：
- op.marksheet.register / op.marksheet.line / op.result.line （成绩簿）
- op.media / op.media.unit / op.author / op.publisher / op.media.movement （图书馆）
- op.subject（学习材料，经 op.student.course.subject_ids）
- edu.notice（布告栏，自建轻量模型）
"""
import datetime
import re
import time

from odoo import fields, http
from odoo.http import request
from odoo.tools import file_path
from odoo.addons.portal.controllers.portal import pager

from .main import (EduPortalHome, assignment_scope_domain, current_student,
                   safe_count, student_course)
from .roles import EduParentPortal, current_faculty, privileged_staff
from .calendar import month_event_count_for_user
# v2.1-B9：私信可用性降级守卫（同一导入同时完成 controllers/messages.py
# 的路由注册，保持 B9 改动都在契约 inScope 内，不动 controllers/__init__.py）
from .messages import _messages_ready  # noqa: E402,F401
# v3 一条龙（t6）：controllers/study.py 的路由注册同样走「由 inScope 模块
# 导入」的方式（沿用 B9 对 messages.py 的既有做法），不改 controllers/__init__.py
from . import study  # noqa: E402,F401


def _fmt_date(d):
    return d.strftime('%Y/%m/%d') if d else ''


# ---------------------------------------------------------------------------
# 首页分类映射（原站 reference/dashboard_categories.json 的内嵌副本）
# count 为 None 表示无对应模型，渲染时按需求只显示 desc，不挂计数徽标
# ---------------------------------------------------------------------------

# 计数短缓存：/my/home 单次渲染触发 ~20 次计数查询，60s TTL 内跨请求复用
_COUNT_TTL = 60
_count_cache = {}


def _count_cached(student, course, batch, href):
    key = (request.env.uid, student.id if student else 0, href)
    # v2.1-B9：私信未读实时性优先——不走 60s 计数缓存（打开会话即已读，
    # 缓存会导致未读角标延迟；30s 轮询只负责在页面上刷新，服务端渲染
    # 必须拿到当前值，否则「新私信」提醒卡可能不渲染或残留旧值）。
    if href == 'my/messages':
        return _count_for_card(student, course, batch, href)
    now = time.time()
    hit = _count_cache.get(key)
    if hit and now - hit[0] < _COUNT_TTL:
        return hit[1]
    val = _count_for_card(student, course, batch, href)
    now2 = time.time()
    _count_cache[key] = (now2, val)
    if len(_count_cache) > 8192:
        cutoff = now2 - _COUNT_TTL
        for k in [k for k, v in _count_cache.items() if v[0] < cutoff]:
            _count_cache.pop(k, None)
    return val


def _notice_audience_codes():
    """当前用户的人群码列表；None = 教务/管理员（恒可见全部公告）。

    单一事实源仍是 edu.notice._audience_users（t7 F4 已交付的实现）：这里
    不复制任何身份规则，只是用「取某人群的收件人集合」反查当前用户是否属于
    该人群。结果按请求缓存，避免同一次渲染重复物化人群集合。
    """
    if getattr(request, '_edu_notice_codes_ready', False):
        return request._edu_notice_codes
    user = request.env.user
    codes = None
    if not (user.has_group('openeducat_core.group_op_back_office_admin')
            or user.has_group('base.group_system')):
        codes = []
        Notice = request.env['edu.notice']
        for code in ('student', 'faculty', 'parent'):
            try:
                if user in Notice.new({'audience': code})._audience_users():
                    codes.append(code)
            except Exception:
                continue
    request._edu_notice_codes = codes
    request._edu_notice_codes_ready = True
    return codes


def _notice_audience_domain():
    """布告可见性 domain（t21）：staff 恒可见；其余 = audience=all 或命中人群。"""
    codes = _notice_audience_codes()
    if codes is None:
        return []
    return ['|', ('audience', '=', 'all'), ('audience', 'in', codes)]


def _notice_targeted_to(notice, codes):
    """单条可见性：codes 为 None（staff）恒真；否则 all 或命中人群。"""
    if codes is None:
        return True
    return (notice.audience or 'all') == 'all' or notice.audience in codes


def _count_for_card(student, course, batch, href):
    """按原站卡片 href 计算真实计数；无对应模型返回 None。"""
    if href == 'student/profile':
        return 1 if student else None
    if href == 'library/media':
        return safe_count('op.media', [])
    if href == 'my/notice_board/notice':
        # v2-B5：卡片计数改为「当前用户未读布告数」
        reads = request.env['edu.notice.read'].sudo().search(
            [('user_id', '=', request.env.uid)])
        read_ids = set(reads.mapped('notice_id').ids)
        # t21：卡片角标只统计「对该用户可见」的公告，避免泄漏定向公告
        notices = request.env['edu.notice'].sudo().search(
            _notice_audience_domain())
        return len([n for n in notices if n.id not in read_ids])
    if href == 'subject/registration':
        # 我的选课申请数（含草稿/提交中），无学生返回 None 不挂角标
        return safe_count('op.subject.registration',
                          [('student_id', '=', student.id)]) \
            if student else None
    if href == 'subject/enroll':
        # 报课选科：无计数角标（入口型卡片）
        return None
    if href == 'course/change/request':
        # 换班申请角标：只数归属变更单（与页面 domain 同口径）
        return safe_count('op.subject.registration',
                          [('student_id', '=', student.id),
                           ('doc_type', '=', 'course_change')]) \
            if student else None
    if href == 'subject/details':
        if student:
            scs = student.course_detail_ids.sudo()
            subs = set()
            for sc in scs:
                subs.update(sc.subject_ids.ids)
            return len(subs)
        return None
    if href == 'student/assignment/details':
        return safe_count('op.assignment',
                          [('batch_id', '=', batch.id)]) if batch else None
    if href == 'student/exam':
        return safe_count('op.exam',
                          [('course_id', '=', course.id)]) if course else None
    if href == 'student/attendance':
        return safe_count('op.attendance.line',
                          [('student_id', '=', student.id)]) if student else None
    if href == 'student/timetable':
        return safe_count('op.session',
                          [('batch_id', '=', batch.id)]) if batch else None
    if href == 'grade-book':
        return safe_count('op.marksheet.line',
                          [('student_id', '=', student.id)]) if student else None
    if href == 'my-library':
        return safe_count(
            'op.media.queue',
            [('partner_id', '=', student.partner_id.id)]) if student else None
    if href == 'requested/queue/list':
        return safe_count(
            'op.media.queue',
            [('partner_id', '=', student.partner_id.id)]) if student else None
    if href == 'my/fees':
        return safe_count(
            'edu.fee.bill',
            [('student_id', '=', student.id)]) if student else None
    if href == 'my/reimburse/apply':
        # 报销入口卡角标：我的在途报销数（申请中/待付）
        if not student:
            return None
        try:
            return request.env['edu.fee.bill'].sudo().search_count([
                ('direction', '=', 'payable'),
                ('reimburse_state', 'in', ('request', 'approved')),
                ('created_by_partner', '=', student.partner_id.id)])
        except Exception:
            return None
    if href == 'my/calendar':
        # v2.1-B10：本月可见活动数（口径同校历页，角色内部解析）
        return month_event_count_for_user()
    if href == 'my/messages':
        # v2.1-B9：未读私信数（收件人=当前账号且未读）。
        # 降级守卫：目标库未 -u 升级（模型未注册或表未创建）时静默返回 0，
        # 保证 /my/home 对全员可渲染（对齐 safe_count / 'edu.eval.task'
        # in env 判存惯例）。
        if not _messages_ready():
            return 0
        return request.env['edu.message'].sudo().search_count(
            [('recipient_id', '=', request.env.uid),
             ('is_read', '=', False)])
    if href == 'downloads':
        # 资料下载 v2：卡片角标与「资料库上新」提醒共用口径——近 30 天新资料数
        return safe_count('edu.download.file', [
            ('active', '=', True),
            ('create_date', '>=', fields.Datetime.now()
             - datetime.timedelta(days=30))])
    if href == 'my/purchase':
        return safe_count('purchase.order', [])
    return None


# 教育类卡片：icon 为已下载的 SVG 文件名（static/src/img/），缺文件用 fa 类兜底
_OPENEDUCAT_CARDS = [
    ('student/profile', '学生档案',
     'openeducat_core_enterprise_static_src_img_student-profile.svg',
     '个人信息与学籍数据'),
    ('my/fees', '费用账单',
     'openeducat_fees_plan_static_images_invoice.svg',
     '学杂费账单与缴纳状态查询'),
    ('my-library', '数字图书馆',
     'openeducat_digital_library_static_src_img_digital-library.svg',
     '访问广泛的数字资源进行学习'),
    ('library/media', '图书馆',
     'openeducat_library_enterprise_static_src_img_library.svg',
     '丰富的研究资源'),
    ('meeting/information', '线上会议',
     'openeducat_meeting_enterprise_static_src_img_meetings.svg',
     '一键进入 Zoom 课堂'),
    ('my/notice_board/notice', '布告栏',
     'openeducat_notice_board_enterprise_static_src_img_notice-board.svg',
     '集中分享重要公告和信息'),
    ('users/result-overview', '测验结果',
     'openeducat_quiz_static_src_img_quiz-result.svg',
     '访问和审查测验结果以进行绩效分析'),
    ('my/time_off', '请假',
     'openeducat_student_leave_enterprise_static_src_img_time-off.svg',
     '处理休假请求和缺勤'),
    ('student/progression', '进展',
     'openeducat_student_progress_enterprise_static_src_img_progression.svg',
     '监控和评估学生的学业进步'),
    ('subject/details', '学习材料',
     'openeducat_subject_material_allocation_static_src_img_study-material.svg',
     '课程配套学习资料'),
    ('my/asset-request', '资产请求',
     'openeducat_asset_request_enterprise_static_src_img_asset-requests.svg',
     '处理教育材料和资源请求'),
    ('student/assignment/details', '作业',
     'openeducat_assignment_enterprise_static_src_img_assignments.svg',
     '高效地跟踪、收集和管理课程作业'),
    ('student/exam', '考试',
     'openeducat_exam_enterprise_static_src_img_exams.svg',
     '参加并管理各种考试'),
    ('my/grievances', '申诉',
     'openeducat_grievance_enterprise_static_src_img_grievances.svg',
     '及时处理和解决机构关注的问题'),
    ('my-courses', '课程',
     'openeducat_lms_static_src_img_courses.svg',
     '提供多样化的课程，满足不同的学习需求'),
    ('certificate', '证书',
     'openeducat_lms_static_src_img_certificate.svg',
     '颁发和管理课程结业证书'),
    ('student/attendance', '出席率',
     'openeducat_attendance_enterprise_static_src_img_attendance.svg',
     '准确管理学生考勤记录'),
    ('student/newregistration/info', '入场',
     'openeducat_dynamic_admission_static_src_img_new-registration.svg',
     '新课程入学注册流程'),
    ('student/timetable', '时间表',
     'openeducat_timetable_enterprise_static_src_img_timetable.svg',
     '创建和管理课程和活动的时间表'),
    ('grade-book', '成绩簿',
     'openeducat_grading_static_src_img_gradebook.svg',
     '分析学生的成绩和表现'),
    ('course/change/request', '换班申请',
     'openeducat_course_change_request_static_src_img_course-change-request.svg',
     '申请换班或换课程，提交后由教务审批'),
    ('subject/enroll', '报课选科',
     'fa-pencil-square-o',
     '课程/班级/科目目录自主选报，提交教务审批'),
    ('subject/registration', '科目注册',
     'openeducat_core_enterprise_static_src_img_subject-registration.svg',
     '选课注册单：课程/班级/科目选报与申请进度'),
    ('my/academic-calendar', '学术日历',
     'openeducat_core_enterprise_static_src_img_academic-calendar.svg',
     '跟踪重要日期和学术活动'),
    ('my/thesis', '论文',
     'openeducat_core_enterprise_static_src_img_subject-registration.svg',
     '管理您的论文注册和提交流程'),
    ('online/meeting', 'Zoom 会议',
     'fa-video-camera',
     '点击跳转 Zoom 链接'),
]

_COMMON_CARDS = [
    ('my/addresses', '地址', 'portal_static_src_img_portal-addresses.svg',
     '添加、删除或修改您的地址'),
    # 2026-09-24：'my/security' → 'my/password'。core portal 那页在控制器里 strip
    # 新密码（portal.py:877-879），改密后用自己敲的密码登不上；我们自己的页逐字保存。
    ('my/password', '修改密码',
     'portal_static_src_img_portal-connection.svg',
     '修改你的登录密码'),
]

# v4 永约：灵命生活与评估入口（图标为 FA 类，语义互不重复）
# 2026-09-29：原「我的评分 / 评教填答」两卡指向 edu_eval（行政评估 / B 套）的
# /eval/my、/eval/review。该模块已卸载、/eval/* 的 303 兼容壳一并删除 ⇒ 两卡并成
# 一卡、直指新引擎 edu_assess 的门户页：**落点与卸载前 303 的落点逐字相同**
# （旧两条地址当时都 303 → /assess/my，见 edu_assess/controllers/portal.py）。
# 并卡而非留两张同地址卡：batch2.py 的 spec_map 以 href 为键，
# 同 href 两张卡会渲染成两张一模一样的瓦片（后写的那条覆盖前一条）。
_YONGYUE_CARDS = [
    ('my/checkins', '每日打卡', 'fa-calendar-check',
     '读经、灵修等每日打卡记录'),
    ('my/journals', '我的周记', 'fa-book-open',
     '每周周记提交与教师批阅'),
    ('assess/my', '我的评估', 'fa-star-half-o',
     '待填评教与历次评估结果'),
    ('help', '使用指南', 'fa-book', '各角色操作说明与常见流程'),
    ('downloads', '资料下载', 'fa-download',
     '请假表、阅读报告格式等常用表格下载'),
    ('my/reimburse/apply', '发起报销', 'fa-exchange',
     '垫付的书费/车费/活动费申请报销'),
]

_ALERT_CARDS = [
    ('subject/registration', '您的科目注册申请已批准'),
    ('my/notice_board/notice', '给您的通知'),
    ('student/profile', '已获就业安置'),
    ('users/result-overview', '测验结果'),
    ('my/time_off', '您的请假状态已更新'),
    ('my/asset-request', '资产请求已批准'),
    ('student/assignment/details', '新作业已发布'),
    ('student/exam', '考试结果'),
    ('my/grievances', '申诉进展更新'),
    ('my/fees', '待支付账单'),
    ('my/quotes', '要审查的报价'),
    ('requested/queue/list', '您的图书馆媒体请求已接受'),
    ('my/messages', '新私信'),
    ('downloads', '资料库上新'),
]


# ---- 门户卡片隐藏开关 -------------------------------------------------
# 系统参数 edu.portal_hidden_cards：逗号分隔的卡片 href。
# 未设置时用下方默认值；设为空串即全部恢复显示（隐藏≠删除，随时可开回）。
# D5 解隐：my/orders / my/payment_method / my/dms / my/asset-request /
# openeducat-omr/* 本地路由均已可用，恢复显示；仅保留路由缺失的三个。
# 2026-08 拷问确认：课表/学术日历/使用指南/即时聊天 与校历/帮助中心/私信重复，
# 隐藏重复入口（隐藏≠删除，随时可开回）。
_DEFAULT_HIDDEN_CARDS = [
    'my/rfq', 'my/purchase',            # 采购询价（路由缺失）
    'student/newregistration/info',     # 入场注册（路由缺失，用户确认暂不做）
    'student/timetable',                # 排课查看统一走校历
    'my/academic-calendar',             # 学术日历并入校历
    'help',                             # 使用指南并入帮助中心（/my/help）
]


# 2026-10-04（第 87 轮）：**家长首页不该出现学生专属卡片**。
#   首页上手卡片承诺「点击右上角「应用面板」**或首页卡片**进入各功能」，而实测
#   （`scripts/probe_home_cards.py`，已接进 check_all）家长宫格有 10 张卡点进去
#   是「该页面仅面向学生账号」或被静默弹回首页 —— 因为 `_home_categories` 只按
#   `student` 取数、**从不按角色过滤**（它对家长只**加**了一张「我的孩子」，没减）。
#
#   这份名单就是探针实测出来的那 10 条。**它不会悄悄过期**：探针每次全量跑，
#   将来若有新卡混进家长宫格、或这里的名单与实况不符，check_all 立刻报红。
# 2026-10-04（第 92 轮）：这份名单从「家长专用」升级为**通用** ——
#   第 87 轮只按 `is_parent` 过滤，于是 `/my/apps`（「全部应用」）对**教务**照样摆出
#   全套学生卡：实测 11 张点进去是拒止页/被弹回。而 `/my/home` 是**另一套** staff 宫格
#   （教务在那儿看到的是「课程编排 / 管理后台」）⇒ 同一个账号在两个页面看到的入口不一致。
#   （2026-10-13 起门户侧栏的「管理后台」入口已撤下，/my/home 侧栏只剩「课程编排」；
#    教务的后台入口改由 /apps 卡片承担，见 code-map §6 第 19 条。）
#
#   口径（按实测分两类，不搞一刀切）：
#   口径：**没有学生档案的账号，这 10 张一律不出**（家长 / 教务 / 教师都实测进不去）。
#   （一度想给教师开例外，实测后否掉了 —— 见文件下方 cards() 里那段注释。）
_STUDENT_ONLY_CARDS = [
    'student/profile',            # 学生档案：仅面向学生账号
    'student/progression',        # 进展
    'student/assignment/details',  # 作业
    'student/exam',               # 考试
    'student/attendance',         # 出席率
    'grade-book',                 # 成绩簿（第 73 轮我就见过它对家长拒止，当时只查了左导航没查宫格）
    'subject/details',            # 学习材料
    'subject/enroll',             # 报课选科（被弹回首页）
    'course/change/request',      # 换班申请（被弹回首页）
    'my/reimburse/apply',         # 发起报销（被弹回首页）
]


def _hidden_cards():
    val = request.env['ir.config_parameter'].sudo().get_param(
        'edu.portal_hidden_cards')
    if not val:
        return set(_DEFAULT_HIDDEN_CARDS)
    return {h.strip() for h in val.split(',') if h.strip()}


def _alert_counts(student):
    """D3：提醒类别的当前计数 {key(href): raw count}。

    key 与 _ALERT_CARDS 及首页模板渲染的卡片 data-alert-key 对齐；
    'student/profile' 在提醒区指 Placement（无数据源，恒空），不计入。
    A1：my/time_off / my/grievances 在 _count_for_card 无计数源（宫格卡
    也不该挂这类计数），此处按「申请人侧状态更新」口径补充——
    请假=已出结果（非 request）、申诉=有进展（非 draft/submitted）；
    /alerts/mark_read 提水位与首页渲染共用本函数，保证口径一致。
    """
    course, batch = student_course(student)
    counts = {}
    for href, _title in _ALERT_CARDS:
        if href == 'student/profile':
            continue
        counts[href] = _count_cached(student, course, batch, href) or 0
    if student:
        counts['my/time_off'] = safe_count(
            'edu.leave', [('student_id', '=', student.id),
                          ('state', '!=', 'request')])
        counts['my/grievances'] = safe_count(
            'edu.grievance', [('student_id', '=', student.id),
                              ('state', 'not in', ('draft', 'submitted'))])
    return counts


def _alert_seen_map():
    """当前用户的已读水位 {key: 水位}；无记录返回空 dict。"""
    rec = request.env['edu.alert.read'].sudo().search(
        [('user_id', '=', request.env.uid)], limit=1)
    return dict(rec.seen_map or {}) if rec else {}


# 无独立路由的卡片 → 图标别名（scripts/gen_icons.py 的 extra/*）
_ICON_ALIASES = {'my/child': 'extra/child'}


def _home_icon_svg(href):
    """href 的渐变瓦片 SVG 图标（static/src/img/icons/<href>.svg，
    文件名与 href 一一对应）。文件存在才返回静态 URL；缺失返回 None，
    由模板回退到下方 FA 彩色瓦片。"""
    href = _ICON_ALIASES.get(href, href)
    try:
        file_path('edu_portal/static/src/img/icons/%s.svg' % href)
        return '/edu_portal/static/src/img/icons/%s.svg' % href
    except FileNotFoundError:
        return None


# 首页卡片图标美化：href → (FA 图标, 品牌色)。
# 命中即用彩色圆角瓦片替代企业版灰阶 SVG；未命中回退原 img。
# 有同名 SVG 插画（_home_icon_svg）时优先用插画，此处仅作兜底。
FA_HOME_ICONS = {
    'student/timetable': ('fa-calendar', '#1D6FEB'),
    'student/attendance': ('fa-check-circle', '#0E9F6E'),
    'student/exam': ('fa-pencil-square-o', '#E7650A'),
    'student/assignment/details': ('fa-file-text-o', '#2563EB'),
    'grade-book': ('fa-bar-chart', '#059669'),
    'library/media': ('fa-book', '#7C3AED'),
    'my-library': ('fa-tablet', '#4F46E5'),
    'subject/details': ('fa-folder-open', '#D97706'),
    'my/fees': ('fa-credit-card', '#B45309'),
    'my/reimburse/apply': ('fa-exchange', '#0F766E'),
    'meeting/information': ('fa-video-camera', '#0891B2'),
    'online/meeting': ('fa-video-camera', '#0284C7'),
    'my/notice_board/notice': ('fa-bullhorn', '#DC2626'),
    'users/result-overview': ('fa-trophy', '#C8A870'),
    'my/time_off': ('fa-plane', '#64748B'),
    'student/progression': ('fa-line-chart', '#16A34A'),
    'my/asset-request': ('fa-laptop', '#0891B2'),
    'my/grievances': ('fa-commenting-o', '#DB2777'),
    'my-courses': ('fa-graduation-cap', '#7C3AED'),
    'certificate': ('fa-certificate', '#CA8A04'),
    'student/newregistration/info': ('fa-sign-in', '#0E7490'),
    'course/change/request': ('fa-exchange', '#0F766E'),
    'subject/enroll': ('fa-pencil-square-o', '#0F766E'),
    'subject/registration': ('fa-list-ul', '#9333EA'),
    'my/academic-calendar': ('fa-calendar-plus-o', '#4338CA'),
    'my/thesis': ('fa-sticky-note-o', '#7C2D12'),
    # v4-t8：#714B67（Odoo 原厂紫）→ 令牌引用。本表的值只经
    # views/batch2.xml 的 t-att-style="'color:' + card['color']" 落到 CSS 声明，
    # 所以直接写 var(--token) 即可；白底 8.23 ✓（原紫 7.23）。
    # ⚠ 本表其余 24 色是 Tailwind 路由色（§4.5 的「25 色收编」是另一件事，
    #   会导致可见变化 ⇒ 按规范 §4.4 先上报再改，本轮不动）。
    'student/profile': ('fa-user-circle', 'var(--brand-700)'),
    'my/rfq': ('fa-shopping-bag', '#64748B'),
    'my/purchase': ('fa-shopping-bag', '#475569'),
    'my/addresses': ('fa-map-marker', '#64748B'),
    'my/password': ('fa-key', '#334155'),  # 原 my/security：改指逐字安全的改密页（见 _COMMON_CARDS）
    'my/checkin': ('fa-calendar-check-o', '#0E9F6E'),
    'requested/queue/list': ('fa-list-ol', '#0E9F6E'),
    'my/checkins': ('fa-calendar-check', '#0E9F6E'),
    'my/journals': ('fa-book-open', '#7C3AED'),
    'assess/my': ('fa-star-half-o', '#D97706'),
    'my/contacts': ('fa-address-book-o', '#0E9F6E'),
    'my/calendar': ('fa-calendar', '#0E9F6E'),
    'my/messages': ('fa-comments-o', '#0E9F6E'),
    # 课程中心（/my/study）：图标与左导航那条 b11-nav-item 同字（fa-graduation-cap），
    # 颜色沿用表内既有的 #0E7490（原消费点 student/newregistration/info 属默认隐藏卡，
    # 所以可见宫格里不会出现同色同字的另一块瓦片）；本表不新增第 26 个路由色。
    'my/study': ('fa-graduation-cap', '#0E7490'),
}


# ---------------------------------------------------------------------------
# W1/W2：常用应用（角色化 4 件套 + localStorage 排序/固定）
# ---------------------------------------------------------------------------
_FAV_PRESETS = {
    'student': [
        ('student/timetable', '课表', 'fa-calendar', '#1D6FEB',
         '每周课程与今日上课安排'),
        ('my/checkins', '每日打卡', 'fa-calendar-check-o', '#0E9F6E',
         '打卡足迹与连续记录'),
        ('my/calendar', '校历', 'fa-calendar', '#0E9F6E',
         '课程、考试、停课与活动总览'),
        ('student/assignment/details', '作业', 'fa-file-text-o', '#2563EB',
         '待完成与已提交的作业'),
    ],
    'faculty': [
        ('student/timetable', '教学安排', 'fa-calendar', '#1D6FEB',
         '本周与每日我教的课'),
        ('checkins/stats', '打卡统计', 'fa-pie-chart', '#0E9F6E',
         '学生每日打卡情况统计'),
        ('my/calendar', '校历', 'fa-calendar', '#0E9F6E',
         '课程、考试、停课与活动总览'),
        ('my/messages', '消息', 'fa-comments-o', '#0E9F6E',
         '与学生、家长即时沟通'),
    ],
    'parent': [
        ('student/timetable', '孩子的课表', 'fa-calendar', '#1D6FEB',
         '孩子的每周课程安排'),
        ('my/calendar', '校历', 'fa-calendar', '#0E9F6E',
         '课程、考试、停课与活动总览'),
        ('my/messages', '消息', 'fa-comments-o', '#0E9F6E',
         '与老师、学校即时沟通'),
        ('my/contacts', '通讯录', 'fa-address-book-o', '#0E9F6E',
         '老师、家长与学校联系人'),
    ],
    'internal': [
        ('my/calendar', '校历', 'fa-calendar', '#0E9F6E',
         '课程、考试、停课与活动总览'),
        ('student/timetable', '全校课表', 'fa-calendar', '#1D6FEB',
         '全校周课表（只读）'),
        ('my/messages', '消息', 'fa-comments-o', '#0E9F6E',
         '与师生即时沟通'),
        ('openeducat/apps_menu', '应用面板', 'fa-th-large', '#64748B',
         '全部应用入口'),
    ],
}


def _home_role():
    """首页角色的常用区预置口径（student/faculty/parent/internal）。"""
    is_parent = bool(request.env['op.parent'].sudo().search_count(
        [('user_id', '=', request.env.uid)]))
    if not is_parent and current_student():
        return 'student'
    if current_faculty():
        return 'faculty'
    if is_parent:
        return 'parent'
    return 'internal'


def _has_server_favs():
    """当前用户在服务端是否有收藏（3b：供前端区分 SSR 口径与 localStorage 兜底）。"""
    try:
        return bool(request.env['edu.favorite'].sudo().search_count(
            [('user_id', '=', request.env.uid)]))
    except Exception:
        return False


def _build_favorites(role, all_cards=None):
    """角色化常用应用卡片（URL 复用既有路由；隐藏卡剔除；计数短缓存）。

    辅助增强包 3b：用户在服务端有收藏（edu.favorite）时按收藏顺序直出，
    覆盖预置 4 件套；无收藏回退预置（与旧行为一致）。
    all_cards = 全页卡片元数据映射（_home_categories 构建），用于找回
    预置池之外被收藏过的入口；查不到时用占位卡，不递归调分组引擎。
    """
    student = current_student()
    course, batch = student_course(student)
    hidden = _hidden_cards()
    out = []
    for href, title, icon, color, desc in _FAV_PRESETS.get(role, []):
        if href in hidden:
            continue
        try:
            count = _count_cached(student, course, batch, href)
        except Exception:
            count = None
        out.append({
            'href': '/' + href,
            'app_href': href,
            'title': title,
            'icon': icon,
            'svg': None,
            'color': color,
            'desc': desc,
            'count': count,
        })
    # 服务端收藏覆盖（仅使用已知入口，防止伪造 href 注入）
    try:
        favs = request.env['edu.favorite'].sudo().search(
            [('user_id', '=', request.env.uid)], order='sequence, id')
    except Exception:
        favs = None
    if favs:
        by_href = {c['app_href']: c for c in out}
        for f in favs:
            # t122：脏数据防线 —— card_href 为空/空白的收藏行解析不出任何卡片，
            # 落进占位分支就会变成 href='/' 的空卡（数据侧由
            # scripts/fix_favorite_card_href.py 一次性订正）。这里直接跳过。
            if not (f.card_href or '').strip():
                continue
            c = by_href.get(f.card_href) or (all_cards or {}).get(
                f.card_href)
            if not c:
                c = {'app_href': f.card_href,
                     'href': '/' + f.card_href,
                     'title': f.card_href,
                     'icon': 'fa-external-link',
                     'svg': None, 'color': '#64748B',
                     'desc': '', 'count': None}
            if c in out:
                out.remove(c)
            out.append(c)
    return out


# v3：原 _backend_action_url() 返回 '/web#action=<id>' 后台回退链接，
# 已按 v3 去 Odoo 化要求**删除**——三处待办卡一律改走门户路由
# （/leave/approvals、/grievances/approvals、/registrar/subject/approvals）。


def _approval_alerts():
    """A1：教师/教务工作台「待办提醒」聚合（纯只读，0 计数的卡不进列表）。

    - 待批请假：edu.leave state=request；待处理申诉：edu.grievance
      submitted/in_progress；评估待打分：edu.eval.task state=scoring
      （教师真正可办的事）。
    - href 按角色分流：有教师档案 → 门户审批页（守卫同既有路由）；教务处/
      管理员（无 op.faculty）→ 后台「教务审批」对应 action，不改权限模型。
    """
    env = request.env
    is_fac = bool(current_faculty())
    alerts = []
    leave_n = safe_count('edu.leave', [('state', '=', 'request')])
    if leave_n:
        alerts.append({
            'key': 'leave', 'title': '待批请假', 'count': leave_n,
            'icon': 'fa-plane', 'color': '#D97706',
            'cls': 'text-bg-warning',
            'desc': '学生/家长请假申请等待审批',
            'href': '/leave/approvals',
        })
    grievance_n = safe_count(
        'edu.grievance',
        [('state', 'in', ('submitted', 'in_progress'))])
    if grievance_n:
        alerts.append({
            'key': 'grievance', 'title': '待处理申诉', 'count': grievance_n,
            'icon': 'fa-commenting-o', 'color': '#DB2777',
            'cls': 'text-bg-info',
            'desc': '学生申诉等待处理',
            'href': '/grievances/approvals',
        })
    # 第 2 期：待批选课 + 换班/换课（op.subject.registration submitted）。
    # 2026-09-18 订正：旧注释写「课程变更单走既有 /course/change/request
    # 学生流程」——而该流程当时**没有**任何教务审批入口，是失效注释；
    # 变更单现已进 /registrar/subject/approvals 的「变更审批」页签。
    subj_n = safe_count('op.subject.registration',
                        [('state', '=', 'submitted'),
                         ('doc_type', 'in', ('subject_registration',
                                             'course_change'))])
    if subj_n:
        alerts.append({
            'key': 'subject_reg', 'title': '待批选课', 'count': subj_n,
            'icon': 'fa-pencil-square-o', 'color': '#0F766E',
            'cls': 'text-bg-secondary',
            'desc': '学生选课注册单与换班申请等待审批',
            'href': '/registrar/subject/approvals',
        })
    eval_n = 0
    if 'edu.eval.task' in env:
        eval_n = env['edu.eval.task'].sudo().search_count(
            [('state', '=', 'scoring')])
    if eval_n:
        alerts.append({
            'key': 'eval', 'title': '评估待打分', 'count': eval_n,
            'icon': 'fa-star-half-o', 'color': '#4338CA',
            'cls': 'text-bg-primary',
            'desc': '综合评估打分任务进行中',
            'href': '/my/evaluation',
        })
    return alerts


def _today_classes(student, fac, parent):
    """今日课表预览（≤5 条 + 总数；S4 首页卡；学生/教师/家长角色可用）。

    纯只读：按角色域取当日课时，返回 {'items', 'total'}；
    无角色（如纯内部员工）返回空表，模板不渲染卡片。
    """
    import datetime
    import pytz as pytz_mod
    env = request.env
    if not (student or fac or parent):
        return {'items': [], 'total': 0}
    today = datetime.date.today()
    tz = pytz_mod.timezone(request.env.user.tz or 'UTC')
    try:
        start = tz.localize(
            datetime.datetime.combine(today, datetime.time.min))
        end = start + datetime.timedelta(days=1)
        win_start = start.astimezone(pytz_mod.UTC).replace(tzinfo=None)
        win_end = end.astimezone(pytz_mod.UTC).replace(tzinfo=None)
    except Exception:
        return {'items': [], 'total': 0}
    domain = [('start_datetime', '>=', win_start),
              ('start_datetime', '<', win_end),
              ('state', '!=', 'cancel')]
    if fac and not student:
        domain.append(('faculty_id', '=', fac.id))
    elif student:
        _, batch = student_course(student)
        domain.append(('batch_id', '=', batch.id if batch else 0))
    elif parent:
        Scs = env['op.student.course'].sudo()
        scs = Scs.search([('student_id', 'in', parent.student_ids.ids),
                          ('state', '=', 'running')])
        if not scs:
            scs = Scs.search([('student_id', 'in', parent.student_ids.ids)])
        batch_ids = scs.mapped('batch_id').ids
        domain.append(('batch_id', 'in', batch_ids or [0]))
    sessions = env['op.session'].sudo().search(
        domain, order='start_datetime asc')
    items = []
    for ses in sessions[:5]:
        loc = ses.start_datetime
        try:
            loc = ses.start_datetime.replace(tzinfo=pytz_mod.UTC) \
                .astimezone(tz).replace(tzinfo=None)
        except Exception:
            pass
        items.append({
            'title': ses.subject_id.name or ses.course_id.name or '课程',
            'time': loc.strftime('%H:%M') if loc else '',
            'room': ses.classroom_id.name or '',
        })
    return {'items': items, 'total': len(sessions)}


def _home_categories(student):
    """组装首页分类（对齐原站）：通知折叠条 + 六个标题头平铺组。"""
    course, batch = student_course(student)

    # 汇集全部卡片规格（href -> (title, icon, desc)）
    spec_map = {}
    for spec in (_OPENEDUCAT_CARDS + _COMMON_CARDS
                   + _YONGYUE_CARDS):
        spec_map[spec[0]] = spec[1:]
    # 即时聊天（2026-08 拷问确认：与私信重复，整体隐藏；私信为唯一消息入口）
    livechat_href = ''
    # 家长角色：注入「我的孩子」入口卡
    is_parent = bool(request.env['op.parent'].sudo().search(
        [('user_id', '=', request.env.uid)], limit=1))
    if is_parent:
        spec_map['my/child'] = ('我的孩子', 'fa-child',
                                '查看孩子的仪表盘、成绩与档案')

    hidden = _hidden_cards()

    def cards(href_list):
        out = []
        for href in href_list:
            # t122：空 href 不得成卡。历史上用 livechat_href = '' 当"隐藏开关"
            # （本文件社区分组仍这么用），而未知 href 会回退成 (href, 'fa-file-o', '')
            # ⇒ 渲染成 <a href="/" title=""> 的空卡片（/my/apps 实测 1 张，曾是 axe link-name 命中点）。
            # 这里统一把空/空白 href 视为"不生成卡片"，隐藏开关语义不变。
            if not (href or '').strip() or href in hidden:
                continue
            # 非学生：学生专属卡片一律不出（名单与口径见文件上方，由 probe_home_cards.py
            # 实测支撑；家长要看孩子的内容走「我的孩子」那张卡）。
            # 第 92 轮实测确认：这 10 条对**任何非学生**（家长 / 教务 / 教师）都进不去 ——
            #   教师看似「应该能看作业/考试」，但 /my/apps 上实测同样回「仅面向学生账号」；
            #   （第 87 轮在 /my/home 上没看到教师中招，是因为教师在那儿走的是**另一套 staff 宫格**。）
            if not student and href in _STUDENT_ONLY_CARDS:
                continue
            title, icon, desc = spec_map.get(
                href, (href, 'fa-file-o', ''))
            fa = FA_HOME_ICONS.get(href)
            if fa:
                icon = fa[0]
            # 首屏提速：有 FA 彩色映射时优先用打包图标（零额外请求），
            # SVG 插画仅作少数无映射入口的兜底，避免首页 30+ 独立图标请求瀑布。
            svg = None if fa else _home_icon_svg(href)
            count = None if href.startswith('#') or href == 'student/profile' \
                else _count_cached(student, course, batch, href)
            out.append({
                'href': '/' + href if not href.startswith('#') else '#',
                'app_href': href,
                'title': title,
                'icon': icon,
                'svg': svg,
                'color': fa[1] if fa else None,
                'desc': desc,
                'count': count,
            })
        return out

    # 提醒分类：每类未读 = max(0, 当前计数 - 已读水位)；只展示有数据的提醒卡
    seen_map = _alert_seen_map()
    counts_map = _alert_counts(student)
    alert_cards = []
    alert_unread = 0
    for href, title in _ALERT_CARDS:
        if href in hidden:
            continue
        raw = counts_map.get(href, 0)
        if not raw:
            continue
        unread = max(0, raw - seen_map.get(href, 0))
        alert_cards.append({
            'href': '/' + href,
            'key': href,
            'title': title,
            'raw': raw,
            'unread': unread,
        })
        alert_unread += unread

    # Backoffice 角色：More 组首位插入「校友工作」管理卡
    is_backoffice = bool(request.env['res.users'].browse(
        request.env.uid).login == 'backoffice@local')
    if is_backoffice:
        spec_map['alumni/job/list'] = ('校友工作', 'fa-briefcase',
                                       '校友发布的工作岗位管理')

    # 「在线测验」入口：全角色统一中文标签（教师视角此前漏翻译显示英文 quiz）
    spec_map['quiz'] = ('在线测验', 'fa-question-circle',
                        '参加在线测验并查看成绩')

    # 排课工作台两卡：属教务处（Registrar/Back Office Admin）职权，
    # 按 OpenEduCat 官方组层级授予；教师账号不显示
    is_registrar = request.env.user.has_group(
        'openeducat_core.group_op_back_office_admin')
    # 管理员/教务处：门户内直达「发布公告」（路由门禁已同步放行）
    is_priv = is_registrar or privileged_staff()
    if is_priv:
        spec_map['notice/publish'] = ('发布公告', 'fa-bullhorn',
                                      '发布全校公告/通知（支持门户横幅）')
    if is_registrar:
        spec_map['timetable/bulk'] = ('周期排课', 'fa-calendar-plus-o',
                                      '勾选星期与起止周，批量生成整学期课表')

    # v2.1-B8：通讯录（/my/contacts）——全角色常用，进「社区」组
    spec_map['my/contacts'] = ('通讯录', 'fa-address-book-o',
                               '校园通讯录：老师、学生、家长（按熟人圈可见）')

    # v2.1-B10：一体化校历（/my/calendar）——课程+考试+停课+活动月视图
    spec_map['my/calendar'] = ('校历', 'fa-calendar',
                               '一体化校历：课程、考试、停课与活动一页总览')

    # v2.1-B9：轻量双向私信（/my/messages）——熟人圈内一对一通信
    spec_map['my/messages'] = ('私信', 'fa-comments-o',
                               '轻量私信：与老师、学生、家长即时沟通（熟人圈）')

    # 课程中心（/my/study）—— 登记进宫格，**不是**给搜索单开一条。
    # 来由（2026-09-29）：这一页此前只写在左导航（views/edu_portal_templates.xml
    # 的 b11-* 段），不是宫格卡片；而门户搜索的入口索引单一来源就是本函数
    # （controllers/search.py 的 _panel_entries 只做投影），于是用户搜「课程中心」
    # 必然 0 条。正解 = 让它成为宫格卡：宫格与搜索一起拿到，两处永不漂移。
    # 分组与角色可见性见下方 acad_hrefs 的注释（学业组首位；不加比左导航更窄的守卫）。
    spec_map['my/study'] = ('课程中心', 'fa-graduation-cap',
                            '每门在修科目：课节、一键入会、课程资料与成绩')

    # 课程中心（/my/study）居学业组首位（2026-09-29）：它是「课程 / 报课 / 申请 /
    # 成绩」的主入口 —— docs/plans/study-hub-v3-design.md §6 的零功能丢失表把
    # my-courses「课程」、subject/enroll、subject/registration 三条的落点都记成它。
    # **角色可见性口径 = 左导航**：那条 b11-nav-item 没有 t-if 守卫（学生/家长/教师/
    # 教务/管理员都看得到），所以这里也不加角色过滤 —— 反过来（只给学生）就等于
    # 用宫格另立一份比导航更窄的名单。/my/study 自己的守门在 controllers/study.py
    # 的 _subjects_for（内部用户=全目录、学生=在册科目、家长=孩子科目）。
    # 家长角色：Academics 组首位插入「我的孩子」入口（仍排在课程中心之前）
    acad_hrefs = ['my/study', 'student/profile', 'users/result-overview',
                  'student/progression',
                  'student/assignment/details', 'student/exam', 'my-courses',
                  'subject/enroll',
                  'student/attendance',
                  'student/newregistration/info', 'student/timetable',
                  'my/calendar',   # v2.1-B10：校历（课程/考试/停课/活动）
                  'grade-book', 'course/change/request', 'subject/registration',
                  'my/academic-calendar', 'my/thesis', 'quiz']
    if request.env['op.parent'].sudo().search_count(
            [('user_id', '=', request.env.uid)]):
        acad_hrefs.insert(0, 'my/child')
    if is_registrar:
        acad_hrefs += ['timetable/bulk']

    # 学生专属「成长」组：教师等非学生身份隐藏打卡/周记入口
    if not student:
        hidden |= {'my/checkins', 'my/journals', 'assess/my'}
    # 财务卡：教务/管理员不再渲染「费用账单」（2026-09-24 合账裁定，展示层过滤）。
    # 判据 privileged_staff() = base.group_system 或 group_op_back_office_admin，
    # 与 views/edu_portal_templates.xml 侧栏的 b11_back 同一口径：侧栏已把他们送到
    # 后台「财务管理 ▸ 账单管理」（/odoo/action-720），宫格里再挂同一张只读账单页
    # 就是第二道门。学生/家长/教师**照旧**显示该卡——那是他们唯一的自家账单入口。
    # 只过滤消费点，_OPENEDUCAT_CARDS 里的条目本身保留（隐藏≠删除）。
    finance_hrefs = ['my/fees', 'my/reimburse/apply']
    if privileged_staff():
        finance_hrefs = [h for h in finance_hrefs if h != 'my/fees']
    groups = [
        ('portal_academics_category', '学业 Academics', 'fa-graduation-cap', acad_hrefs),
        ('portal_resources_category', '资源与学习 Resources', 'fa-book', [
            'my-library', 'library/media', 'subject/details',
            'meeting/information', 'online/meeting',
            'my/asset-request', 'downloads',
        ]),
        ('portal_growth_category', '成长 Growth', 'fa-leaf', [
            'my/checkins', 'my/journals', 'assess/my',
        ]),
        ('portal_finance_category', '财务 Finance', 'fa-credit-card', finance_hrefs),
        ('portal_community_category', '社区 Community', 'fa-users', ([
            livechat_href, 'my/notice_board/notice', 'notice/publish',
            'my/contacts', 'my/messages', 'my/grievances',
        ] if is_priv else [
            livechat_href, 'my/notice_board/notice', 'my/contacts',
            'my/messages', 'my/grievances',
        ])),
        ('portal_personal_category', '个人与设置', 'fa-cog', [
            'my/time_off', 'my/addresses', 'my/password',
        ]),
    ]
    more_hrefs = ['help', 'my/rfq', 'my/purchase']
    if is_backoffice:
        more_hrefs.insert(0, 'alumni/job/list')
        groups.append(('portal_more_category', '更多', 'fa-ellipsis-h',
                       more_hrefs))
    else:
        groups.append(('portal_more_category', '更多', 'fa-ellipsis-h',
                       more_hrefs))

    out = [{'key': 'portal_alert_category', 'id': 'portal_alert_category',
            'title': '通知', 'icon': 'fa-bell', 'alert': True,
            'total': alert_unread, 'cards': alert_cards}]
    # 先构建各分组卡，再构建常用区（需要全页卡元数据做收藏找回）
    all_cards = {}
    for key, title, icon, hrefs in groups:
        hrefs = [h for h in hrefs if h not in hidden]
        gcards = cards(hrefs)
        if not gcards and key != 'portal_more_category':
            continue
        for c in gcards:
            if c.get('app_href'):
                all_cards[c['app_href']] = c
        out.append({'key': key, 'id': key, 'title': title, 'icon': icon,
                    'alert': False, 'total': None, 'cards': gcards,
                    'count_label': f'{len(gcards)} 项'})
    # W1：常用应用置顶区（角色化 4 件套 / 服务端收藏；空则不渲染该组）
    fav_cards = _build_favorites(_home_role(), all_cards)
    if fav_cards:
        out.insert(1, {'key': 'portal_favorites_category',
                       'id': 'portal_favorites_category',
                       'title': '常用应用', 'icon': 'fa-star-o',
                       'alert': False,
                       'fav': True, 'total': None, 'cards': fav_cards,
                       'count_label': f'{len(fav_cards)} 项'})
    return out


# ---------------------------------------------------------------------------
# v3 首页 Timeline 工作台（调研 §1 Moodle Timeline：overdue/next7days/next30days
# + 每课程默认 5 条收敛）与 /my/apps 应用面板的配套数据装配。
# ---------------------------------------------------------------------------
def _learner_scope(student, parent_rec):
    """学习者的班级/课程范围（家长取孩子合集）。"""
    Scs = request.env['op.student.course'].sudo()
    if student:
        scs = Scs.search([('student_id', '=', student.id)])
    elif parent_rec:
        scs = Scs.search([('student_id', 'in', parent_rec.student_ids.ids)])
    else:
        return [], []
    return scs.mapped('batch_id').ids, scs.mapped('course_id').ids


def _tl_when(dt):
    if not dt:
        return ''
    local = fields.Datetime.context_timestamp(
        request.env.user, dt).replace(tzinfo=None)
    return local.strftime('%m月%d日 %H:%M')


def _timeline_buckets(student, batch_ids, course_ids):
    """逾期 / 近 7 天 / 近 30 天三桶，每课程至多 5 条。

    数据源：作业(op.assignment.submission_date)、考试(op.exam.start_time)、
    课节(op.session.start_datetime)、定时解锁课次(edu.lesson.unlock_at)。
    作业无「已提交」标记时不臆测状态，逾期 = 截止时间已过。
    """
    out = {'overdue': [], 'next7': [], 'next30': []}
    if not student:
        return out
    env = request.env
    now = fields.Datetime.now()
    d7 = now + datetime.timedelta(days=7)
    d30 = now + datetime.timedelta(days=30)
    rows = []

    def push(kind, when, title, href, course):
        if not when:
            return
        rows.append({'_dt': when, 'kind': kind, 'when': _tl_when(when),
                     'title': title, 'href': href, 'course': course or ''})

    adom = [('submission_date', '!=', False), ('submission_date', '<=', d30)]
    if batch_ids:
        adom.append(('batch_id', 'in', batch_ids))
    for asg in env['op.assignment'].sudo().search(adom):
        push('作业', asg.submission_date, asg.name or '作业提交',
             '/student/assignment/details',
             asg.subject_id.name or asg.course_id.name or '')

    edom = [('start_time', '!=', False), ('start_time', '<=', d30)]
    if batch_ids:
        edom.append(('batch_id', 'in', batch_ids))
    for ex in env['op.exam'].sudo().search(edom):
        push('考试', ex.start_time, ex.name or '考试', '/student/exam',
             ex.subject_id.name or '')

    sdom = [('state', '!=', 'cancel'), ('start_datetime', '>=', now),
            ('start_datetime', '<=', d30)]
    if batch_ids:
        sdom.append(('batch_id', 'in', batch_ids))
    for ses in env['op.session'].sudo().search(sdom):
        push('课节', ses.start_datetime,
             '%s 上课' % (ses.subject_id.name or '课程'),
             '/my/study/%d' % ses.subject_id.id, ses.subject_id.name or '')

    ldom = [('state', '=', 'published'), ('unlock_at', '!=', False),
            ('unlock_at', '<=', d30)]
    for ls in env['edu.lesson'].sudo().search(ldom):
        push('解锁', ls.unlock_at, '%s 解锁' % (ls.name or '课次'),
             '/my/study/%d' % ls.subject_id.id, ls.subject_id.name or '')

    rows.sort(key=lambda r: r['_dt'])
    seen = {}
    for row in rows:
        key = row['course'] or '-'
        if seen.get(key, 0) >= 5:        # Moodle：每课程至多 5 条
            continue
        seen[key] = seen.get(key, 0) + 1
        if row['_dt'] < now:
            bucket = 'overdue'
        elif row['_dt'] <= d7:
            bucket = 'next7'
        else:
            bucket = 'next30'
        out[bucket].append({k: v for k, v in row.items() if k != '_dt'})
    return out






class EduStudentBatch2(http.Controller):

    # ------------------------- 成绩簿 -------------------------

    @http.route('/grade-book', type='http', auth='user', website=True)
    def grade_book(self, **kw):
        student = current_student()
        env = request.env
        lines = []
        if student:
            lines = env['op.marksheet.line'].sudo().search(
                [('student_id', '=', student.id)],
                order='generated_date desc, id desc')
        cards = []
        for ms in lines:
            results = []
            for rl in ms.result_line:
                ex = rl.exam_id
                total = ex.total_marks or 0
                pct = round(rl.marks / total * 100.0, 2) if total else 0.0
                results.append({
                    'subject': ex.subject_id.name or ex.name or '',
                    'exam': ex.name or '',
                    'marks': rl.marks,
                    'total': total,
                    'pct': pct,
                    'pct_str': '%.2f%%' % pct,
                    'grade': rl.grade or '',
                    'status': {'pass': '及格', 'fail': '不及格',
                               }.get(rl.status, '') if rl.status else '',
                    'passed': rl.status == 'pass',
                })
            reg = ms.marksheet_reg_id
            cards.append({
                'register': reg.name or '',
                'session': reg.exam_session_id.name or '',
                'generated': _fmt_date(ms.generated_date),
                'percentage': ms.percentage or 0.0,
                'pct_str': '%.2f%%' % (ms.percentage or 0.0),
                'grade': ms.grade or '',
                'passed': ms.status == 'pass',
                'results': results,
            })
        overall = round(sum(ms.percentage or 0.0 for ms in lines) / len(lines),
                        2) if lines else 0.0
        course_name = ''
        if student:
            course, _batch = student_course(student)
            course_name = course.name if course else ''
        stats = {
            'overall': '%.2f%%' % overall if lines else '—',
            'grade': (lines[0].grade or '—') if lines else '—',
            'subjects': sum(len(ms.result_line) for ms in lines),
            'course': course_name or '—',
        }
        values = {
            'title': '成绩簿',
            'page_name': 'grade_book',
            'student': student,
            'stats': stats,
            'cards': cards,
            'has_records': bool(cards),
        }
        return request.render('edu_portal.edu_gradebook', values)

    @http.route('/grade-book/report/download', type='http', auth='user',
                website=True)
    def grade_book_download(self, **kw):
        """B9 成绩簿报告下载：该生成绩 CSV（utf-8-sig 防 Excel 乱码）。"""
        import csv
        import io
        student = current_student()
        if not student:
            return request.redirect('/grade-book')
        lines = request.env['op.marksheet.line'].sudo().search(
            [('student_id', '=', student.id)],
            order='generated_date desc, id desc')
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['科目', '考试', '得分', '满分'])
        for ms in lines:
            for rl in ms.result_line:
                ex = rl.exam_id
                writer.writerow([
                    ex.subject_id.name or ex.name or '',
                    ex.name or '',
                    rl.marks or 0,
                    ex.total_marks or 0,
                ])
        # utf-8-sig：BOM 头让 Excel 正确识别 UTF-8 中文
        payload = '\ufeff' + buf.getvalue()
        filename = 'gradebook_report_%s.csv' % (
            fields.Date.today().strftime('%Y%m%d'),)
        return request.make_response(
            payload.encode('utf-8'),
            headers=[
                ('Content-Type', 'text/csv; charset=utf-8'),
                ('Content-Disposition',
                 'attachment; filename="%s"' % filename),
            ])

    # ------------------------- 学业进展 -------------------------

    @http.route('/student/progression', type='http', auth='user',
                website=True)
    def student_progression(self, **kw):
        """B1 学业进展页：出勤/作业/测验/请假真实聚合。"""
        student = current_student()
        env = request.env
        rows = []
        att_pct = 0
        asg_done = asg_total = 0
        quiz_avg = None
        quiz_n = 0
        n_leaves = 0
        if student:
            # ---- 各科出勤率（sheet→session→subject；无科目回退课程名）----
            agg = {}
            for ln in env['op.attendance.line'].sudo().search(
                    [('student_id', '=', student.id)]):
                sub = ln.attendance_id.session_id.subject_id
                key = 'sub-%s' % sub.id if sub else \
                    'crs-%s' % (ln.course_id.id or 0)
                row = agg.setdefault(key, {
                    'name': (sub.name if sub else '')
                            or ln.course_id.name or '未分科目',
                    'pres': 0, 'late': 0, 'absent': 0, 'exc': 0, 'n': 0,
                })
                row['n'] += 1
                if ln.present:
                    row['pres'] += 1
                elif ln.late:
                    row['late'] += 1
                elif ln.absent:
                    row['absent'] += 1
                elif ln.excused:
                    row['exc'] += 1
            rows = sorted(agg.values(), key=lambda r: (-r['n'], r['name']))
            tot = sum(r['n'] for r in rows)
            pres = sum(r['pres'] + r['late'] for r in rows)
            att_pct = round(pres * 100.0 / tot) if tot else 0

            # ---- 作业提交率（submit / accept 视为已提交）----
            # 2026-10-03：原先是**只按 batch_id** 取作业 ⇒ 把别的课程的作业也算进来，
            # 「作业提交 1 / 5」里的 5 实为 batch 全量（真值 3，见 main.assignment_scope_domain）。
            # ⇒ 与作业页/首页共用同一口径（本轮已把该域抽成 main.assignment_scope_domain）。
            asgs = env['op.assignment'].sudo().search(
                assignment_scope_domain(student))
            done_ids = set(env['op.assignment.sub.line'].sudo().search(
                [('student_id', '=', student.id),
                 ('state', 'in', ['submit', 'accept'])]).mapped(
                     'assignment_id.id'))
            asg_total = len(asgs)
            asg_done = sum(1 for a in asgs if a.id in done_ids)

            # ---- 近期测验均分（edu.quiz.attempt 未安装则静默跳过）----
            try:
                attempts = env['edu.quiz.attempt'].sudo().search(
                    [('student_id', '=', student.id),
                     ('state', '=', 'submitted')])
                pcts = [a.score * 100.0 / a.total
                        for a in attempts if a.total]
                quiz_n = len(attempts)
                quiz_avg = round(sum(pcts) / len(pcts), 1) if pcts else None
            except Exception:
                quiz_avg = None

            # ---- 请假次数 ----
            n_leaves = safe_count('edu.leave',
                                  [('student_id', '=', student.id)])

        for r in rows:
            r['pct'] = round((r['pres'] + r['late']) * 100.0 / r['n']) \
                if r['n'] else 0
        asg_pct = round(asg_done * 100.0 / asg_total) if asg_total else 0
        has_records = bool(rows) or bool(asg_total) \
            or quiz_avg is not None or bool(n_leaves)
        values = {
            'title': '学业进展',
            'page_name': 'progression',
            'student': student,
            'stats': {
                'att_pct': ('%d%%' % att_pct) if rows else '—',
                'assign': ('%d / %d' % (asg_done, asg_total))
                          if asg_total else '—',
                'assign_pct': asg_pct,
                'quiz': ('%.1f%%' % quiz_avg) if quiz_avg is not None
                        else '—',
                'quiz_n': quiz_n,
                'leaves': n_leaves,
            },
            'rows': rows,
            'has_records': has_records,
        }
        return request.render('edu_portal.edu_progression', values)

    # ------------------------- 图书馆 -------------------------

    @http.route('/library/media', type='http', auth='user', website=True)
    def library_media(self, **kw):
        student = current_student()
        filterby = kw.get('filterby') or 'all'
        sortby = kw.get('sortby') or 'name'
        groupby = kw.get('groupby') or 'none'
        search = (kw.get('search') or '').strip()

        domain = []
        if filterby and filterby != 'all':
            domain.append(('media_type_id', '=', int(filterby)))
        if search:
            domain += ['|', '|', ('name', 'ilike', search),
                       ('isbn', 'ilike', search),
                       ('internal_code', 'ilike', search)]
        order = {
            'name': 'name asc',
            'edition': 'edition asc, name asc',
            'internal_code': 'internal_code asc',
            'isbn': 'isbn asc',
        }.get(sortby, 'name asc')
        # 分页（每页 10 条，对齐原站）
        page = max(1, int(kw.get('page', 1) or 1))
        PAGE_SIZE = 6
        Media = request.env['op.media'].sudo()
        total_media = Media.search_count(domain)
        medias = Media.search(domain, order=order,
                              limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)

        media_cards = []
        for m in medias:
            media_cards.append({
                'media': m,
                'name': m.name or '',
                'type': m.media_type_id.name if m.media_type_id else '',
                'isbn': m.isbn or '',
                'internal_code': m.internal_code or '',
                'edition': m.edition or '',
                'authors': ', '.join(m.author_ids.mapped('name')),
            })

        # 分组
        groups = []
        if groupby == 'media_type_id':
            by_type = {}
            for c in media_cards:
                by_type.setdefault(c['type'] or '其他', []).append(c)
            groups = [{'name': k, 'items': v} for k, v in by_type.items()]
        else:
            groups = [{'name': '', 'items': media_cards}]

        # 统计
        media_types = request.env['op.media.type'].sudo().search_count([])
        issued = returned = 0
        if student:
            movs = request.env['op.media.movement'].sudo().search(
                [('student_id', '=', student.id)])
            issued = sum(1 for mv in movs if mv.state == 'issue')
            returned = sum(1 for mv in movs if mv.actual_return_date)
        stats = {
            'titles': request.env['op.media'].sudo().search_count([]),
            'types': media_types,
            'issued': issued,
            'returned': returned,
        }
        filter_opts = request.env['op.media.type'].sudo().search(
            [], order='id asc')

        values = {
            'title': '库所有媒体列表',
            'page_name': 'library',
            'student': student,
            'stats': stats,
            'groups': groups,
            'pager': pager('/library/media', total=total_media, page=page,
                           step=PAGE_SIZE,
                           url_args={'filterby': filterby, 'sortby': sortby,
                                     'groupby': groupby, 'search': search}),
            'has_records': bool(media_cards),
            'filterby': filterby,
            'sortby': sortby,
            'groupby': groupby,
            'search': search,
            'filter_opts': filter_opts,
        }
        return request.render('edu_portal.edu_library', values)

    # ------------------------- 学习材料 -------------------------

    @http.route('/subject/details', type='http', auth='user', website=True)
    def subject_details(self, **kw):
        student = current_student()
        sortby = kw.get('sortby') or 'name'
        filterby = kw.get('filterby') or 'all'
        groupby = kw.get('groupby') or 'none'
        search = (kw.get('search') or '').strip()

        # 学生所在课程的科目列表
        scs = student.course_detail_ids.sudo() if student else \
            request.env['op.student.course'].sudo()
        subject_map = {}   # subject_id -> (subject, course_id, course_name)
        for sc in scs:
            cid = sc.course_id.id if sc.course_id else 0
            cname = sc.course_id.name if sc.course_id else ''
            for sub in sc.subject_ids:
                subject_map.setdefault(sub.id, (sub, cid, cname or ''))

        items = []
        for sub_id, (sub, cid, cname) in subject_map.items():
            n_files = request.env['op.media'].sudo().search_count(
                [('subject_ids', 'in', [sub_id])])
            items.append({
                'subject': sub,
                'name': sub.name or '',
                'course': cname,
                'course_id': cid,
                'code': sub.code or '',
                'files': n_files,
            })

        if filterby != 'all':
            items = [i for i in items
                     if str(i['course_id']) == filterby]
        if search:
            items = [i for i in items
                     if search.lower() in i['name'].lower()
                     or search.lower() in i['course'].lower()]
        if sortby == 'course_id':
            items.sort(key=lambda i: (i['course'], i['name']))
        else:
            items.sort(key=lambda i: i['name'])

        groups = []
        if groupby == 'course_id':
            by_course = {}
            for i in items:
                by_course.setdefault(i['course'] or '其他', []).append(i)
            groups = [{'name': k, 'items': v} for k, v in by_course.items()]
        else:
            groups = [{'name': '', 'items': items}]

        course_opts = []
        seen = set()
        for i in items:
            key = (i['course_id'], i['course'])
            if key not in seen:
                seen.add(key)
                course_opts.append({'id': i['course_id'], 'name': i['course']})

        stats = {
            'subjects': len(items),
            'materials': sum(i['files'] for i in items),
            'courses': len(seen),
        }
        values = {
            'title': '学习材料',
            'page_name': 'subject_details',
            'student': student,
            'stats': stats,
            'groups': groups,
            'has_records': bool(items),
            'sortby': sortby,
            'filterby': filterby,
            'groupby': groupby,
            'search': search,
            'course_opts': course_opts,
        }
        return request.render('edu_portal.edu_subject_details', values)

    @http.route('/library/media/info/<int:mid>', type='http', auth='user',
                website=True)
    def library_media_info(self, mid, **kw):
        """媒体详情（对齐原站 /library/media/info//N）。"""
        m = request.env['op.media'].sudo().browse(mid)
        if not m.exists():
            return request.redirect('/library/media')
        return request.render('edu_portal.edu_media_info', {
            'title': (m.name or '媒体') + ' · 馆藏详情',
            'page_name': 'media_info',
            'm': m,
        })

    @http.route('/subject/material/detail/<int:sid>', type='http',
                auth='user', website=True)
    def subject_material_detail(self, sid, **kw):
        """科目材料详情（对齐原站 /subject/material/detail//N）。"""
        student = current_student()
        sub, cname = None, ''
        scs = student.course_detail_ids.sudo() if student else \
            request.env['op.student.course'].sudo()
        for sc in scs:
            for s2 in sc.subject_ids:
                if s2.id == sid:
                    sub = s2
                    cname = sc.course_id.name or ''
                    break
            if sub:
                break
        if not sub:
            return request.redirect('/subject/details')
        materials = request.env['op.media'].sudo().search(
            [('subject_ids', 'in', [sid])])
        return request.render('edu_portal.edu_subject_material_detail', {
            'title': (sub.name or '科目') + ' · 学习材料',
            'page_name': 'subject_material_detail',
            'sub': sub,
            'course_name': cname,
            'materials': materials,
        })

    # ------------------------- 布告栏 -------------------------

    @http.route('/my/notice_board/notice', type='http', auth='user',
                website=True)
    def notice_board(self, **kw):
        """B4 布告栏：?box=notice 通知（默认）/ ?box=circular 公告两个 tab。

        box 的旧取值 active / this_month / high 仍作为通知 tab 内的
        快捷过滤保留；这些旧链接会落回默认的通知 tab。
        """
        student = current_student()
        sortby = kw.get('sortby') or 'high_priority'
        search = (kw.get('search') or '').strip()
        box = kw.get('box') or 'notice'
        # 类别维度：仅 circular 进 Circular tab，其余（含空）都归通知 tab
        category = 'circular' if box == 'circular' else 'notice'

        domain = [('category', '=', category)]
        if search:
            domain += ['|', ('name', 'ilike', search),
                       ('content', 'ilike', search)]
        # 4b：过期公告不再展示（必须在 search 前生效）
        domain += ['|', ('date_until', '=', False),
                   ('date_until', '>=', fields.Date.today())]
        # t21：定向人群在服务端过滤（布告栏列表只出现该用户该看的公告）
        domain += _notice_audience_domain()
        notices = request.env['edu.notice'].sudo().search(domain)

        # v2-B5：当前用户已读集合（用于未读标记与角标）
        _reads = request.env['edu.notice.read'].sudo().search(
            [('user_id', '=', request.env.uid),
             ('notice_id', 'in', notices.ids)])
        read_set = set(_reads.mapped('notice_id').ids)

        today = fields.Date.today()
        items = []
        for n in notices:
            items.append({
                'notice': n,
                'name': n.name or '',
                'content': n.content or '',
                'sender': n.sender or '',
                'date': _fmt_date(n.date),
                'this_month': bool(n.date and n.date.month == today.month
                                   and n.date.year == today.year),
                'unread': n.id not in read_set,
            })
        if sortby == 'date':
            items.sort(key=lambda i: i['notice'].date or today,
                       reverse=True)
        elif sortby == 'name':
            items.sort(key=lambda i: i['name'])
        else:  # high_priority -> 按日期倒序展示
            items.sort(key=lambda i: i['notice'].date or today,
                       reverse=True)

        # 旧快捷过滤（只在当前 tab 数据集上收窄）
        if box == 'active':
            items = [i for i in items if i['notice'].active]
        elif box == 'this_month':
            items = [i for i in items if i['this_month']]

        stats = {
            'total': len(notices),
            'high': 0,
            'active': sum(1 for n in notices if n.active),
            'this_month': sum(1 for n in notices
                              if n.date and n.date.month == today.month
                              and n.date.year == today.year),
            'unread': sum(1 for i in items if i['unread']),
        }
        values = {
            'title': '布告栏',
            'page_name': 'notice',
            'student': student,
            'stats': stats,
            'items': items,
            'has_records': bool(items),
            'sortby': sortby,
            'search': search,
            'box': box,
            'empty_msg': '暂无 Circular 公告。学校发布 Circular 后将在此处展示。'
                         if category == 'circular'
                         else '暂无公告。学校发布公告后将在此处展示。',
        }
        values['is_faculty'] = bool(current_faculty())
        # 管理员/教务处同样可发布公告（privileged_staff 门禁已放行路由）
        values['is_publisher'] = bool(current_faculty()) \
            or privileged_staff()
        return request.render('edu_portal.edu_notice', values)

    @http.route('/my/notice/<int:notice_id>', type='http', auth='user',
                website=True)
    def notice_detail(self, notice_id, **kw):
        """布告详情：打开即记为当前用户已读（v2-B5）。

        t21：不在定向人群内的公告按「不存在」处理（同样的重定向与响应），
        不向用户泄露该公告的存在性。
        """
        codes = _notice_audience_codes()
        notice = request.env['edu.notice'].sudo().browse(notice_id)
        if not notice.exists() or not notice.active \
                or not _notice_targeted_to(notice, codes):
            # 不存在 / 未发布 / 不在定向人群内：同一条「未找到」分支
            return request.redirect('/my/notice_board/notice')
        notice.mark_read_for(request.env.user)
        # 4b：公告附件（ir.attachment 挂 res_model/res_id）
        attachments = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'edu.notice'),
            ('res_id', '=', notice.id)])
        return request.render('edu_portal.edu_notice_detail', {
            'title': notice.name or '布告详情',
            'notice': notice,
            'date_str': _fmt_date(notice.date),
            'attachments': attachments,
            'page_name': 'notice_detail',
        })

    @http.route('/my/notice_banner', type='http', auth='user', website=True)
    def notice_banner(self, **kw):
        """门户顶部公告横幅数据（notice-banner）。

        返回所有开启「横幅展示」的进行中公告（banner_seq 升序，最多 5 条），
        前端 notice_banner.js 轮播渲染；无数据返回空列表，页面不渲染横幅。
        """
        notices = request.env['edu.notice'].sudo().search(
            [('banner_enabled', '=', True), ('active', '=', True),
             '|', ('date_until', '=', False),
             ('date_until', '>=', fields.Date.today())]
            + _notice_audience_domain(),
            order='banner_seq, date desc, id desc', limit=5)
        banners = []
        for n in notices:
            # 布告标题常带 [编号] 前缀，横幅上只显示正文标题
            text = re.sub(r'^\[[^\]]+\]\s*', '', n.name or '').strip() \
                or (n.name or '')
            banners.append({
                'id': n.id,
                'badge': n.banner_badge or '',
                'text': text[:120],
                'cta': n.banner_cta or '查看详情',
                'url': n.banner_url or f'/my/notice/{n.id}',
            })
        return request.make_json_response({'banners': banners})

    @http.route('/my/notice_board/all_read', type='http', methods=['POST'],
                auth='user', website=True, csrf=True)
    def notice_all_read(self, **post):
        """一键全部已读（当前用户 × 全部布告）。"""
        user = request.env.user
        Read = request.env['edu.notice.read'].sudo()
        existing = set(Read.search([('user_id', '=', user.id)])
                       .mapped('notice_id').ids)
        # t21：只把「对该用户可见」的公告标记为已读
        todo = request.env['edu.notice'].sudo().search(
            [('id', 'not in', list(existing))] + _notice_audience_domain())
        Read.create([{'user_id': user.id, 'notice_id': n.id}
                     for n in todo])
        return request.redirect('/my/notice_board/notice')


# ---------------------------------------------------------------------------
# 首页重构：继承 EduPortalHome 重写 /my/home（Odoo 路由叶子类机制，
# 子类方法自动替换父类同名路由，因此无需改动 main.py）
# ---------------------------------------------------------------------------

class EduPortalHomeV2(EduPortalHome):

    # ------------------- 首页上半屏（对齐原站 oe-mhead/hero/kpi/charts） -------------------

    def _top_stats(self, student):
        """原站首页上半屏数据：mhero/KPI 瓦片/趋势图/环形图。"""
        import datetime
        env = request.env
        today = datetime.date.today()
        # 2026-10-03（数据一致性复核）：mhero 的「考勤」此前是**裸的无数据 0** ——
        # 家长（current_student() 为空）走下面这个 early return ⇒ 首页显示「考勤 0%」，
        # 读起来像「你孩子出勤率 0%」，而同一名学生自己的首页是 **46%**。
        # 本仓**同一控制器内**早有正确写法（batch2.py:1206 的同款指标）：
        #     'att_pct': ('%d%%' % att_pct) if rows else '—'
        # ⇒ 这里对齐它：把「有没有数据」和「数值」分开，无数据时给 '—' 而不是 0。
        out = {'att_pct': 0, 'att_pct_txt': '—', 'chips': [], 'kpis': [], 'months': [],
               'line_path': '', 'area_path': '', 'trend_pp': 0,
               'trend_dir': 'up', 'donut': []}
        if not student:
            return out

        lines = env['op.attendance.line'].sudo().search(
            [('student_id', '=', student.id)])
        # 2026-10-03（数据一致性复核）：`op.attendance.line` 的 present / late / absent / excused
        # 是**四个独立布尔**，不是互斥枚举 —— **迟到的那条 present 同时也是 True**。
        # 这个前提写错了两处，实测证据（学生 5）：
        #     total 48 ｜ present 23 ｜ present且不迟到 22 ｜ late 1 ｜ absent 25 ｜ excused 0
        #   ① 环形图 `n_late = l.late and not l.present` ⇒ 算成 **0**（真值 1），
        #      于是四段 出勤22+缺席25+请假0+迟到0 = 47 ≠ 总 48 —— **那一条落进了任何一段都不属于的缝里**；
        #   ② 出勤率 `n_pres/48` ⇒ **46%**，而同一名学生自己的
        #      `/student/attendance`（batch1.py:114 `l.present or l.late`）是 47.92% ≈ **48%**、
        #      `/student/progression` 也是 **48%** ⇒ 首页是唯一的异类。
        # 口径对齐（与本仓多数处一致）：**迟到算到堂** ⇒ 出勤率 23/48 = 48%；
        # 而环形图四段必须**互斥**才画得对 ⇒ 迟到单独占一段、出勤段取「到堂且不迟到」。
        n_pres = sum(1 for l in lines if l.present and not l.late)   # 准时到堂（环形图「出勤」段）
        n_absent = sum(1 for l in lines if l.absent)
        n_leave = sum(1 for l in lines if l.excused)
        n_late = sum(1 for l in lines if l.late)                     # 迟到（独立标志，不再要求 not present）
        n_attended = sum(1 for l in lines if l.present or l.late)    # 到堂 = 准时 + 迟到（算率用）
        total_lines = len(lines)

        # ---- mhero 出勤率 + chips ----
        att_pct = round(n_attended * 100.0 / total_lines) if total_lines else 0
        course, batch = student_course(student)
        sc_all = env['op.student.course'].sudo().search(
            [('student_id', '=', student.id)])
        n_courses = sum(1 for sc in sc_all if sc.state == 'running')
        term = env['op.academic.term'].sudo().search(
            [('term_start_date', '<=', today),
             ('term_end_date', '>=', today)], limit=1)
        prog = 0
        if term and term.term_end_date > term.term_start_date:
            span = (term.term_end_date - term.term_start_date).days
            done = (today - term.term_start_date).days
            prog = min(100, max(0, round(done * 100.0 / span)))
        # 2026-10-03（口径复核）：这里原先数的是 **op.result.line 的行数**（该生 3 行），
        # 却把这 3 印成「3学分」—— **那不是学分，是成绩条数**。
        # 而本仓**自己就有学分的唯一口径**（registration.py:515-520，挂在 `op.subject` 上）：
        #     _edu_credits_of(student) = sum(在读科目.credit_points)
        # 库里也确实有这份数据（148 门科目中 89 门 credit_points>0，取值 0/2/3/4/6）⇒ 不是空概念。
        # ⇒ 复用同一口径，不另写一份（另写就会造出第二个定义，正是本仓反复吃亏的地方）。
        # ⚠ 我第一版写成 `env['op.subject']._edu_credits_of(...)` ⇒ 首页当场 500：
        #   `AttributeError: 'op.subject' object has no attribute '_edu_credits_of'`。
        #   原因：该 helper 虽紧挨着 `credit_points` 字段写，但**它的类不是 op.subject** ——
        #   registration.py 的类边界是 `EduSubjectPrereq`（:495，_name='edu.subject.prereq'），
        #   而 `_edu_credits_of` 在 :516，落在**先修要求**模型上（位置本身就怪，但不是本轮的活）。
        #   实测确认：hasattr(env['op.subject']) = False、hasattr(env['edu.subject.prereq']) = True。
        # ⇒ 仍然**调用这一份**，不复制公式（复制就会造出第二个定义，正是本仓反复吃亏的地方）。
        credits = env['edu.subject.prereq']._edu_credits_of(student)
        credits = int(credits) if float(credits).is_integer() else round(credits, 1)

        out['att_pct'] = att_pct
        # 无出勤记录时**不给 0**（0 会被读成「考勤率 0%」这个事实判断）；与同文件 1206 行同口径。
        out['att_pct_txt'] = ('%d%%' % att_pct) if total_lines else '—'
        out['chips'] = [
            {'val': n_courses or len(sc_all), 'lab': '课程'},
            {'val': f'{prog}%', 'lab': '进度'},
            {'val': credits, 'lab': '学分'},
        ]

        # ---- KPI 三瓦片（真实计数） ----
        # 2026-10-03（跨页一致性复核）：此处原先只按 `batch_id` 取作业 ⇒ **多算了别的课程的作业**。
        # 实测证据（学生 5，batch 8）：该批共 5 条作业，其中 `course_id=18`（本人的课）3 条、
        # `course_id=13`（**别人的课**）2 条 ⇒ 首页算 5−1=**4 待完成作业**，
        # 而作业页（batch1.py:655-663 的域）按 batch+course 取 ⇒ 总作业 3、已提交 1 ⇒ **待办 2**。
        # 学生点进去只会看到 2 条 ⇒ 首页那个 4 是错的。
        # ⇒ 与作业页**用同一套域优先级**（能同时限定就都限定），口径一致由构造保证。
        kpi_asg = 0
        asgs = env['op.assignment'].sudo().search(assignment_scope_domain(student))
        done_ids = set(env['op.assignment.sub.line'].sudo().search(
            [('student_id', '=', student.id)]).mapped('assignment_id.id'))
        kpi_asg = sum(1 for a in asgs if a.id not in done_ids)
        # 2026-10-03（口径复核）：此处原先只按 `course_id` 数 op.exam，**既不看时间也不看状态**，
        # 却挂上「即将到来的考试」这个标签。实测（学生 5，course=18）三场全是**过去**的：
        #     id=11  state=draft  start=2026-08-30  ← 还是个草稿
        #     id=177 state=done   start=2026-06-23
        #     id=185 state=done   start=2026-06-23
        # 今天 2026-10-02 ⇒ 真正「即将到来」的是 **0** 场，而首页写着 3。
        # ⇒ 采用本仓日历侧**已有**的同一口径（calendar.py:218-220 的 exam_domain）：
        #      state != 'cancel' 且 start_time >= 窗口起点
        #   不另发明规则（第 42 轮学到的：口径一致要由**复用同一套域**保证）。
        import datetime as _dt
        kpi_exam = safe_count('op.exam', [
            ('course_id', '=', course.id),
            ('state', '!=', 'cancel'),
            ('start_time', '>=', _dt.datetime.now()),
        ]) if course else 0
        out['kpis'] = [
            {'cls': 'oe-kpi--courses', 'ic': 'oe-kpi-primary',
             'icon': 'fa-graduation-cap', 'val': n_courses,
             'lab': '在读课程'},
            {'cls': 'oe-kpi--assign', 'ic': 'oe-kpi-success',
             'icon': 'fa-file-text-o', 'val': kpi_asg,
             'lab': '待完成作业'},
            {'cls': 'oe-kpi--exam', 'ic': 'oe-kpi-info',
             'icon': 'fa-calendar-o', 'val': kpi_exam,
             'lab': '即将到来的考试'},
        ]

        # ---- 近6个月出勤率折线（原站同款几何：viewBox 320x78）----
        monthly = []
        for off in range(5, -1, -1):
            mm = today.month - off
            yy = today.year + (mm - 1) // 12
            mm = (mm - 1) % 12 + 1
            first = datetime.date(yy, mm, 1)
            nxt = datetime.date(yy + (mm == 12), (mm % 12) + 1, 1)
            mlines = [l for l in lines if l.attendance_date and
                      first <= l.attendance_date < nxt]
            mpct = round(sum(1 for l in mlines if l.present) * 100.0 / len(mlines)) \
                if mlines else 0
            monthly.append((f'{mm}月', mpct))
        pts = [20.0 + i * 280.0 / 5 for i in range(6)]
        ys = [round(74 - p / 100.0 * 66, 1) for _, p in monthly]
        out['line_path'] = 'M ' + ' L '.join(
            f'{x},{y}' for x, y in zip(pts, ys))
        out['area_path'] = (f'M {pts[0]},74 L ' +
                            ' L '.join(f'{x},{y}' for x, y in zip(pts, ys)) +
                            f' L {pts[-1]},74 Z')
        out['months'] = [m for m, _ in monthly]
        out['trend_pp'] = abs(monthly[5][1] - monthly[4][1])
        out['trend_dir'] = 'up' if monthly[5][1] >= monthly[4][1] else 'down'

        # ---- 环形图四段（r=34, C=2πr≈213.6）----
        C = 2 * 3.141592653589793 * 34.0
        # 2026-10-03：本段是「到堂且**不迟到**」的 22 条。原先也叫「出勤」，
        # 而 `/student/attendance` 的「出勤 23」是**含迟到**的口径（`present or late`）——
        # 同一个词在两页差 1，读的人会以为哪边算错。环形图的四段必须互斥，
        # 所以这里把标签说准：准时 22 + 迟到 1 = 到堂 23。
        segs = [('oe-donut-good', n_pres, '准时', 'good'),
                ('oe-donut-absent', n_absent, '缺席', 'absent'),
                ('oe-donut-leave', n_leave, '请假', 'leave'),
                ('oe-donut-late', n_late, '迟到', 'late')]
        offset = 0.0
        donut = []
        for cls, cnt, lab, leg in segs:
            ln = C * cnt / total_lines if total_lines else 0
            donut.append({'cls': cls,
                          'dasharray': f'{ln:.2f} {C - ln:.2f}',
                          'dashoffset': f'{-offset:.2f}',
                          'lab': lab, 'count': cnt, 'leg': leg})
            offset += ln
        out['donut'] = donut
        return out

    def _sidebar_values(self, student):
        """原站首页右侧栏：资料卡 + Overview 统计条 + 月历。"""
        import calendar as cal_mod
        import datetime
        env = request.env
        # H-1（校长拍板 2026-09-18）：资料卡的 partner 源统一到**账号 partner**
        # （= avatar.py:22 头像上传写的那条记录）。若继续读 student.partner_id，
        # 本地实测存在「档案 partner ≠ 账号 partner」的分裂行（35 vs 38）⇒ 上传
        # 成功也不会生效。模板侧读 sidebar['partner']，不再依赖裸 partner 变量。
        # 依据 docs/plans/student-portal-home-profile-design.md §5.2-#16 / §9.2-D。
        partner = request.env.user.partner_id

        # ---- Overview 统计（全部真实计算）----
        stats = []
        if student:
            lines = env['op.attendance.line'].sudo().search(
                [('student_id', '=', student.id)])
            total = len(lines)
            present = sum(1 for l in lines if l.present)
            pct = round(present * 100.0 / total) if total else 0
            stats.append({'label': '出勤率', 'value': f'{pct}%',
                          'width': pct, 'cls': 'oe-bar-good'})

            term = env['op.academic.term'].sudo().search(
                [('term_start_date', '<=', datetime.date.today()),
                 ('term_end_date', '>=', datetime.date.today())], limit=1)
            tprog = 0
            if term and term.term_end_date > term.term_start_date:
                span = (term.term_end_date - term.term_start_date).days
                done = (datetime.date.today() - term.term_start_date).days
                tprog = min(100, max(0, round(done * 100.0 / span)))
            stats.append({'label': '学期进度', 'value': f'{tprog}%',
                          'width': tprog, 'cls': 'oe-bar-info'})

            course, batch = student_course(student)
            asg_total = safe_count('op.assignment',
                                   [('batch_id', '=', batch.id)]) if batch else 0
            asg_done = safe_count('op.assignment.sub.line',
                                  [('student_id', '=', student.id)]) if student else 0
            aw = round(asg_done * 100.0 / asg_total) if asg_total else 0
            stats.append({'label': '作业', 'value': f'{asg_done} / {asg_total}',
                          'width': aw, 'cls': 'oe-bar-brand'})

        # ---- 月历（周日开头，高亮今天）----
        today = datetime.date.today()
        weeks = cal_mod.Calendar(firstweekday=6).monthdatescalendar(
            today.year, today.month)
        cal_weeks = [[{'day': d.day, 'today': d == today,
                       'in_month': d.month == today.month} for d in wk]
                     for wk in weeks]
        cal_title = f'{today.year}年{today.month}月'

        # ---- 下一节课 ----
        nxt = None
        if student:
            sc = env['op.student.course'].sudo().search(
                [('student_id', '=', student.id)], limit=1)
            dom = [('start_datetime', '>=', datetime.datetime.now())]
            if sc and sc.batch_id:
                dom.append(('batch_id', '=', sc.batch_id.id))
            ses = env['op.session'].sudo().search(dom, order='start_datetime asc', limit=1)
            if ses:
                when = ses.start_datetime.strftime('%m-%d %H:%M')
                nxt = {'subject': ses.subject_id.name or '未命名',
                       'when': when,
                       'room': ses.classroom_id.name or '',
                       'faculty': ses.faculty_id.name or ''}

        return {
            'partner': partner,
            'stats': stats,
            'cal_title': cal_title,
            'cal_head': ['日', '一', '二', '三', '四', '五', '六'],
            'cal_weeks': cal_weeks,
            'next': nxt,
        }

    def _teacher_dashboard(self, fac, is_registrar=False):
        """教师工作台数据：本周我教的课 + 待办计数 + 快捷入口。
        仅在登录用户为教师（有 op.faculty）且非学生时使用，student 恒为 None。"""
        import datetime
        env = request.env
        today = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday())
        week_start = datetime.datetime.combine(monday, datetime.time.min)
        week_end = datetime.datetime.combine(
            monday + datetime.timedelta(days=6), datetime.time.max)
        sessions = env['op.session'].sudo().search(
            [('faculty_id', '=', fac.id if fac else 0),
             ('start_datetime', '>=', week_start),
             ('start_datetime', '<=', week_end)] if fac else
            [('id', '=', 0)],
            order='start_datetime asc')
        wd_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        days = []
        for ses in sessions:
            day = ses.start_datetime.date()
            if not days or days[-1]['key'] != day:
                days.append({'key': day, 'label': '%s %s' % (
                    wd_names[day.weekday()], day.strftime('%m月%d日')),
                    'sessions': []})
            days[-1]['sessions'].append({
                'time': ses.start_datetime.strftime('%H:%M'),
                'subject': ses.subject_id.name or '未命名课程',
                'batch': ses.batch_id.name or '',
                'room': ses.classroom_id.name or '',
            })
        # 待批周记数：edu.journal.entry submitted 态
        journal_pending = safe_count('edu.journal.entry',
                                     [('state', '=', 'submitted')])
        # 我的评估任务数：原口径 = edu_eval（行政评估 / B 套）
        # edu.admin.eval.template 的 state=open 条数；该模块 2026-09-29 已卸载
        # ⇒ 计数器恒为 0（views/batch2.xml 里 t-if="eval_open" 的徽标不再出现）。
        # ⚠ 留 0 不是"为了让门禁变绿"：把 KPI 换到新引擎（edu.assess.task 的 state
        #   口径）是产品决定，不在本轮"删除行政评估"的授权范围内 ⇒ 如实留空并点名，
        #   由队长决定是否另开一条任务接新数据源。
        eval_open = 0
        is_registrar = request.env.user.has_group(
            'openeducat_core.group_op_back_office_admin')
        cards = []
        if is_registrar:
            cards.append({'href': '/timetable/bulk', 'icon': 'fa-calendar-plus-o',
                          'svg': _home_icon_svg('timetable/bulk'),
                          'title': '周期排课【教务处】', 'desc': '按周期批量生成课表',
                          'color': '#4338CA'})
        cards.append({'href': '/journals/review', 'icon': 'fa-edit',
                      'svg': _home_icon_svg('journals/review'),
                      'title': '周记批阅', 'desc': '批改学生提交的周记',
                      'color': '#D97706', 'badge': journal_pending})
        cards.append({'href': '/checkins/stats', 'icon': 'fa-pie-chart',
                      'svg': _home_icon_svg('checkins/stats'),
                      'title': '打卡统计', 'desc': '查看学生每日打卡情况',
                      'color': '#0E9F6E'});
        # 资料下载（教务/管理员上传，教师与管理员也可下载；管理模式在页内切换）
        # badge 与学生端「资料库上新」同口径：近 30 天新资料数
        cards.append({'href': '/downloads', 'icon': 'fa-download',
                      'svg': _home_icon_svg('downloads'),
                      'title': '资料下载', 'desc': '常用表格下载与资料管理',
                      'color': '#059669',
                      'badge': _count_for_card(None, None, None,
                                               'downloads') or 0});
        # 报销（教师可发起自己的报销）
        cards.append({'href': '/my/reimburse/apply', 'icon': 'fa-exchange',
                      'svg': _home_icon_svg('my/reimburse/apply'),
                      'title': '报销申请', 'desc': '垫付的书费/车费/活动费申请报销',
                      'color': '#0F766E'});
        if is_registrar:
            cards.append({'href': '/ledger', 'icon': 'fa-book',
                          'svg': _home_icon_svg('ledger'),
                          'title': '财务总台账', 'desc': '应收/应付双向台账与记账',
                          'color': '#B45309'});
            cards.append({'href': '/ledger/reimburse', 'icon': 'fa-check-square-o',
                          'svg': _home_icon_svg('ledger/reimburse'),
                          'title': '报销审批', 'desc': '报销申请审核与付款登记',
                          'color': '#0F766E'});
        # v2.1-B8：教师工作台通讯录入口（本班学生/家长+管理员可见）
        cards.append({'href': '/my/contacts', 'icon': 'fa-address-book-o',
                      'svg': _home_icon_svg('my/contacts'),
                      'title': '通讯录', 'desc': '本班学生与家长、管理员',
                      'color': '#0E9F6E'});
        # v2.1-B10：一体化校历（教师可新建活动）
        cards.append({'href': '/my/calendar', 'icon': 'fa-calendar',
                      'svg': _home_icon_svg('my/calendar'),
                      'title': '校历', 'desc': '课程、考试、停课与活动总览',
                      'color': '#0E9F6E'});
        # v2.1-B9：轻量私信（教师→本班学生/家长+管理员；教师↔教师不开放）。
        # 降级守卫：旧库未 -u 升级时不计角标（工作台照常渲染）。
        msg_unread = 0
        if _messages_ready():
            msg_unread = request.env['edu.message'].sudo().search_count(
                [('recipient_id', '=', request.env.uid),
                 ('is_read', '=', False)])
        cards.append({'href': '/my/messages', 'icon': 'fa-comments-o',
                      'svg': _home_icon_svg('my/messages'),
                      'title': '私信', 'desc': '与本班学生、家长即时沟通',
                      'color': '#0E9F6E', 'badge': msg_unread,
                      'badge_hook': True});
        # 2026-10-03（合并）：后台应用面板 /apps 不再占左侧导航位（教师只留一个入口），
        # 但**功能不丢** —— 它变成工作台上的一张卡：门户宫格装不下「后台菜单」这套东西
        # （图标是 web_icon、深链是 /odoo/action-*），所以保留独立页、只收口入口。
        cards.append({'href': '/apps', 'icon': 'fa-th-large',
                      'svg': _home_icon_svg('apps'),
                      'title': '应用面板（后台）',
                      'desc': '后台各应用入口（排课、学籍、成绩、费用等）',
                      'color': '#64748B'})
        return {
            'title': '教师工作台',
            'username': request.env.user.name,
            'faculty_name': (fac.name if fac else request.env.user.name),
            'today_str': '%s %s' % (
                today.strftime('%Y年%m月%d日'), wd_names[today.weekday()]),
            'days': [{'label': d['label'], 'sessions': d['sessions']}
                     for d in days],
            'journal_pending': journal_pending,
            'eval_open': eval_open,
            'cards': cards,
            # A1：待办提醒聚合（待批请假/待处理申诉/评估待打分，0 计不渲染）
            'approval_alerts': _approval_alerts(),
            # W1/S4：教师侧常用应用置顶条 + 今日我教的课预览卡
            'home_role': 'faculty',
            # 合并首页（/my/home 走 edu_dashboard_v2）为真：工作台 partial 不重复渲染问候区
            'merged_apps': False,
            'fav_cards': _build_favorites('faculty'),
            'fav_has_server': _has_server_favs(),
            'today_classes': _today_classes(None, fac, None),
        }

    @http.route('/my/home', type='http', auth='user', website=True)
    def edu_home(self, **kw):
        student = current_student()
        # 教师分支：教师（无学生档案）渲染教师工作台——此前批量排课、
        # 整周复制、打卡统计、周记批阅等教师入口在首页被藏住
        fac = current_faculty()
        # 管理员（system 组）与教师同样进入工作台视图；学生仍走学生仪表盘
        is_admin_user = request.env.user._is_admin()
        # 教务处员工（无教师档案）也进工作台，否则排课入口无处安放
        is_registrar = request.env.user.has_group(
            'openeducat_core.group_op_back_office_admin')
        is_parent = bool(request.env['op.parent'].sudo().search_count(
            [('user_id', '=', request.env.uid)]))
        if (fac or is_admin_user or is_registrar) and not student \
                and not is_parent:
            tvals = self._teacher_dashboard(fac, is_registrar)
            # 2026-10-03（用户要求「老师的我的主页和应用面板功能可以合并，不要分开了」）：
            # 教师（有 op.faculty 档案、非教务/管理员）的 /my/home = **工作台 + 应用宫格**
            # 同一个页面、同一个入口（宫格 markup 与 /my/apps 同源，见 _apps_grid_values）。
            # 教务/管理员不走这里（他们的工作台页保持原样），学生/家长在下面。
            if fac and not is_admin_user and not is_registrar:
                merged = self._apps_grid_values('我的主页', 'home')
                # 2026-10-03（task-19，独立复核报的缺口 3）：同一屏把同一功能说多遍是弱化。
                # 宫格（下方分类）里已有的入口，工作台不再重复摆一张卡；只留宫格没有的
                # 教师专属动作（周记批阅 / 报销申请 / 应用面板（后台）等）。
                # 判据用 href 全等（宫格卡片 href 与工作台卡片 href 都是 '/xxx' 形式）。
                grid_hrefs = {c['href'] for cat in merged['categories']
                              for c in cat.get('cards', [])}
                dropped = [c for c in tvals['cards'] if c['href'] in grid_hrefs]
                tvals['cards'] = [c for c in tvals['cards']
                                  if c['href'] not in grid_hrefs]
                if dropped:
                    tvals['dup_dropped'] = [c['title'] for c in dropped]
                merged.update(tvals)
                merged['title'] = '我的主页'
                merged['merged_apps'] = True
                merged['apps_page'] = True
                return request.render('edu_portal.edu_dashboard_v2', merged)
            return request.render('edu_portal.edu_dashboard_teacher', tvals)

        sc = request.env['op.student.course'].sudo().search(
            [('student_id', '=', student.id)], limit=1) if student else None
        parent_rec = request.env['op.parent'].sudo().search(
            [('user_id', '=', request.env.uid)], limit=1)
        batch_ids, course_ids = _learner_scope(student, parent_rec)
        # 铃铛徽标沿用原口径（各提醒类别未读之和，见 _home_categories）
        cats = _home_categories(student)
        alert_cat = next((c for c in cats
                          if c['key'] == 'portal_alert_category'), None)
        # H-1（校长拍板 2026-09-18）：学生/家长的首页 = 原「全部应用」宫格
        # （edu_dashboard_v2），不再单列 Timeline 工作台页；Timeline 的唯一
        # 独有内容「待办三桶」在宫格顶部以窄条保留（三桶全空则不渲染），
        # 数据源仍是 _timeline_buckets。URL 保持 /my/home（全仓 118 处活引用
        # 不动）；/my/apps 对学生/家长 303 回本页。模板 edu_home_timeline 按
        # 零删除红线保留在册（views/study.xml），当前无路由引用。
        # 依据 docs/plans/student-portal-home-profile-design.md §8.1/§8.3/§8.4。
        values = {
            'title': '我的主页',
            'username': request.env.user.name,
            'student': student,
            'categories': cats,
            'page_name': 'home',
            'chip_term': sc.batch_id.name if sc else '',
            'chip_batch': sc.batch_id.name if sc else '',
            'chip_course': sc.course_id.name if sc else '',
            'sidebar': self._sidebar_values(student),
            'top': self._top_stats(student),
            'home_role': _home_role(),
            'fav_has_server': _has_server_favs(),
            'today_classes': _today_classes(student, None, parent_rec),
            'timeline': _timeline_buckets(student, batch_ids, course_ids),
            'apps_page': True,
            'bell': alert_cat['total'] if alert_cat else 0,
        }
        return request.render('edu_portal.edu_dashboard_v2', values)

    def _apps_grid_values(self, title, page_name):
        """应用宫格（模板 edu_dashboard_v2）的上下文装配。

        2026-10-03：从 edu_apps 里抽出来 —— 教师合并首页（/my/home）与原 /my/apps
        共用同一份装配，避免两处漂移（谁改一处忘另一处，就是下一个「幽灵不一致」）。
        """
        student = current_student()
        sc = request.env['op.student.course'].sudo().search(
            [('student_id', '=', student.id)], limit=1) if student else None
        parent_rec = request.env['op.parent'].sudo().search(
            [('user_id', '=', request.env.uid)], limit=1)
        values = {
            'title': title,
            'username': request.env.user.name,
            'student': student,
            'categories': _home_categories(student),
            'page_name': page_name,
            'chip_term': sc.batch_id.name if sc else '',
            'chip_batch': sc.batch_id.name if sc else '',
            'chip_course': sc.course_id.name if sc else '',
            'sidebar': self._sidebar_values(student),
            'top': self._top_stats(student),
            'home_role': _home_role(),
            'fav_has_server': _has_server_favs(),
            'today_classes': _today_classes(student, None, parent_rec),
            'apps_page': True,
        }
        alert_cat = next((c for c in values['categories']
                          if c['key'] == 'portal_alert_category'), None)
        values['bell'] = alert_cat['total'] if alert_cat else 0
        return values

    @http.route('/my/apps', type='http', auth='user', website=True)
    def edu_apps(self, **kw):
        """v3 应用面板：承接原首页全部功能卡（零功能丢失）。

        H-1（校长拍板 2026-09-18）：学生/家长的宫格已合并进 /my/home，
        故对本类用户收口为**兼容层** 303 → /my/home（路由保留 ⇒ 旧书签
        不 404，与 /my/checkin* 收口同口径）。判据与
        main.EduAppsAlias.apps_menu（/apps）同口径：非内部用户回首页。
        依据 docs/plans/student-portal-home-profile-design.md §8.1/§8.2。

        2026-10-03（用户要求「老师的我的主页和应用面板功能可以合并，不要分开了」）：
        教师（有 op.faculty 档案、非教务/管理员）同样收口为 303 → /my/home ——
        他们的宫格已经在首页（与工作台同页）。**教务 / 管理员保持 200 不变**
        （他们在门户里仍只有这一条宫格入口）。

        刻意复用同一套卡片引擎与「教育门户 v2」模板，因此
        o_portal_index_card 标记、[data-fav-grid] 收藏契约与
        home_favs.js 的收藏编辑在 /my/home 上全部照旧可用。
        """
        if not request.env.user.has_group('base.group_user'):
            return request.redirect('/my/home', code=303)
        # 2026-10-03（用户要求「老师的我的主页和应用面板功能可以合并，不要分开了」）：
        # 教师的宫格已并入 /my/home（工作台 + 宫格同页、同一个入口）⇒ 本页对教师降级为
        # **兼容层** 303 → /my/home（旧书签不 404，与学生 H-1 的处置同口径）。
        # 教务 / 管理员**行为一字不变**：他们在门户里仍只有 /my/apps 这一条宫格入口。
        fac = current_faculty()
        is_registrar = request.env.user.has_group(
            'openeducat_core.group_op_back_office_admin')
        if fac and not is_registrar and not request.env.user._is_admin():
            return request.redirect('/my/home', code=303)
        return request.render('edu_portal.edu_dashboard_v2',
                              self._apps_grid_values('全部应用', 'apps'))


class EduAlertReadV2(EduParentPortal):
    """覆盖 roles.EduParentPortal 的 /alerts/mark_read（叶子类路由机制，
    同 EduPortalHomeV2 覆盖 /my/home）。

    D3 分类已读语义：带 key 只把该类水位提到当前值；不带 key 全部提满
    （兼容旧版「全部标为已读」表单等现有调用方）。
    """

    @http.route('/alerts/mark_read', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def alerts_mark_read(self, **post):
        AlertRead = request.env['edu.alert.read'].sudo()
        counts = _alert_counts(current_student())
        key = (post.get('key') or '').strip()
        # 有 key 且合法 → 仅该类；否则全部提满（旧行为）
        targets = {key: counts[key]} if key in counts else counts
        rec = AlertRead.search([('user_id', '=', request.env.uid)], limit=1)
        if not rec:
            rec = AlertRead.create({'user_id': request.env.uid})
        rec._raise_watermarks(targets)
        rec.write({'last_read': fields.Datetime.now()})
        return request.redirect('/my/home')
