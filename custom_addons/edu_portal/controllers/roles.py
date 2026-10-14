# -*- coding: utf-8 -*-
"""角色门户：家长端（我的孩子 / 孩子仪表盘）。"""
import base64
import csv
import datetime
import io
import json
import logging
import os
from urllib.parse import quote

from psycopg2 import errors as pg_errors

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.addons.portal.controllers.portal import pager

# 身份反查的唯一口径（模型层不能 import 控制器，故公共 helper 落在
# 被依赖方 edu_schedule；理由见 custom_addons/edu_schedule/models/identity.py）
from odoo.addons.edu_schedule.models.identity import (
    PROFILE_CHAINS, profile_of_user)

_LEAVE_TYPE_LABEL = {'sick': '病假', 'legal': '法定假期',
                     'casual': '事假', 'other': '其他',
                     # §6（S3，2026-09-25）：类型重做新增的三个 code —— 审批详情页
                     # 会直接显示这张表的取值，不补就把英文 code 给老师看。
                     'marriage_funeral': '婚丧假', 'winter_summer': '寒暑假',
                     'practice_week': '实践周'}


def _read_table_file(f):
    """读上传的 CSV/XLSX → (header, rows)；单元格统一为去空白字符串。

    XLSX 走 openpyxl（容器已装 3.1.2）；CSV 先按 utf-8-sig，失败回退 gbk
    （国内 Excel 导出常见编码）。
    """
    if not f or not f.filename:
        return [], []
    raw = f.read()
    name = (f.filename or '').lower()
    if name.endswith(('.xlsx', '.xlsm')):
        import openpyxl
        book = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
        sheet = book.active
        rows = []
        for row in sheet.iter_rows(values_only=True):
            rows.append(['' if c is None else str(c).strip() for c in row])
    else:
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('gbk', errors='replace')
        rows = [[(c or '').strip() for c in r]
                for r in csv.reader(io.StringIO(text))]
    rows = [r for r in rows if any(r)]
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _col_index(header, *names):
    """按表头名找列号（容忍前后空格）；找不到返回 None。"""
    for i, cell in enumerate(header):
        if (cell or '').strip() in names:
            return i
    return None


def _cell(row, idx):
    if idx is None or idx >= len(row):
        return ''
    return (row[idx] or '').strip()


_ATT_STATUS_LABEL = {
    '出勤': 'present', '到堂': 'present', 'present': 'present',
    '迟到': 'late', 'late': 'late',
    '缺勤': 'absent', '缺席': 'absent', 'absent': 'absent',
}


# 操作审计页的模型列中文名（避免 /edu/audit 页面出现英文模型名；
# 未登记的模型回退显示原名）
_AUDIT_MODEL_LABELS = {
    'edu.leave': '请假申请',
    'edu.grievance': '学生申诉',
    'edu.notice': '公告',
    'edu.notice.template': '公告模板',
    'edu.approval.delegate': '审批代理设置',
    'edu.grade.history': '成绩变更留痕',
    'edu.subject.prereq': '先修科目要求',
    'op.subject.registration': '选课注册单',
    'op.subject': '科目',
    'op.exam': '考试',
    'op.attendance.sheet': '考勤点名表',
    'op.student': '学生档案',
    'edu.certificate': '结业证书',
    'edu.audit.log': '操作审计',
    # C-1：改课影响面/调课通知写的是 op.session（原样会落到「其它记录」）
    'op.session': '课节',
}


def _audit_user_label(user):
    """审计页操作人显示名：技术/机器人账号一律显示「系统」。

    基座把超级用户/机器人改名为 'OpenEducat Bot' 之类的品牌名，直接渲染
    会把基座品牌泄漏到用户可见处（t7 修复，T4 的 check_odoo_trace 口径外）。
    """
    if not user:
        return '系统'
    name = (user.name or '').strip()
    if not name or user.id == 1 or 'bot' in name.lower() \
            or name.lower().startswith('openeducat'):
        return '系统'
    return name


_logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# 考勤登记簿：唯一 code 口径 + 并发收敛（教师快速点名 / 考勤补录共用）
# ----------------------------------------------------------------------
# 冲突重试上界：撞 unique(code) 后换快照重查，正常最多一轮就收敛
ATTENDANCE_REGISTER_MAX_ATTEMPTS = 3

# 基座 code = fields.Char(size=16) ⇒ 库里是 varchar(16)，而 Odoo 对 Char 超长值是
# **静默截断**（odoo/orm/fields_textual.py:115 「value = s[:self.size]」，本机实测：
# 建簿时按基座上限截断才落库）。截断会毁掉「code 唯一 ⟺ 组合唯一」的前提，
# 故这里自己兜住长度，不把正确性交给一行看不见的截断。
ATTENDANCE_REGISTER_CODE_MAX = 16


def attendance_register_code(course_id, batch_id):
    """(课程, 班级) → 考勤登记簿的**稳定且唯一** code。

    口径 = 'R{course_id}-{batch_id}'，与课代表侧
    （edu_portal/models/course_rep.py:_rep_register）逐字一致——两条路径撞**同一个**
    唯一键正是要的效果：它让「一个 (course, batch) 只有一本登记簿」由数据库的
    unique(code) 保证，而不是由某处的 if 判断保证。
    本函数是单射（按第一个 '-' 切开即可还原两个 id）⇒ code 唯一 ⟺ 组合唯一。
    两个 id 各 7 位以内（现实是 3 位）不会触到 16 字上限；再长则退化为
    'R' + sha1(原码) 前 15 位（仍是 (course, batch) 的确定性函数，两侧算出来一样）。
    """
    raw = 'R%d-%d' % (course_id, batch_id)
    if len(raw) > ATTENDANCE_REGISTER_CODE_MAX:
        import hashlib
        raw = 'R' + hashlib.sha1(raw.encode('utf-8')).hexdigest()[
            :ATTENDANCE_REGISTER_CODE_MAX - 1]
    return raw


def attendance_register(env, course, batch):
    """取或建 (course, batch) 的考勤登记簿，返回**已落库**的记录。

    三条代价换来的教训（2026-09 事故：新班第一次点名必 500）：
      1. **只用真实存在的字段**：基座 op.attendance.register 只有
         name / code / course_id / batch_id / subject_id / active
         （openeducat_attendance/models/attendance_register.py:30-43）。
         这里曾传不存在的 start_date / end_date ⇒
         ValueError: Invalid field 'start_date' in 'op.attendance.register'（HTTP 500）。
      2. **code 是 required + unique，必须显式给**：删掉假字段后仍会撞
         NOT NULL / 唯一冲突（只是换一种 500）。
      3. **并发不靠先查后写**：唯一约束 + 整事务换快照重试。
         Odoo 19 的事务隔离级别是 REPEATABLE READ（odoo/sql_db.py 无条件设置）——
         快照一旦开始，就看不见别人**随后提交**的行；撞唯一约束后即使在 savepoint
         内重查也永远查不到（本机实测见 edu_tg_bind/models/tg_claim.py 文件头，
         那是本仓同款先例）。故这里撞约束后**整事务 ROLLBACK 换快照**再查。
         ⚠ 因此本函数只允许在**本事务还没有任何写入**时调用（现有两个调用点都在
         写 op.attendance.sheet 之前，符合）。
    """
    Register = env['op.attendance.register'].sudo()
    code = attendance_register_code(course.id, batch.id)
    for attempt in range(1, ATTENDANCE_REGISTER_MAX_ATTEMPTS + 1):
        if attempt > 1:
            # 换快照：REPEATABLE READ 下必须结束当前事务，否则重查永远看不见对手
            env.cr.rollback()
            env.invalidate_all(flush=False)
        register = Register.search([('course_id', '=', course.id),
                                    ('batch_id', '=', batch.id)], limit=1)
        if register:
            return register
        try:
            with env.cr.savepoint():
                return Register.create({
                    'name': '考勤登记 %s %s' % (course.name or '',
                                                batch.name or ''),
                    'code': code,
                    'course_id': course.id,
                    'batch_id': batch.id,
                })
        except pg_errors.UniqueViolation:
            # 并发对手已建同 (course, batch) 的登记簿（同 code）⇒ 下一轮换快照即可复用
            _logger.info(
                'edu_portal: 考勤登记簿并发冲突第 %s 次'
                '（course=%s batch=%s code=%s），换快照重试',
                attempt, course.id, batch.id, code)
    raise UserError(
        '考勤登记簿创建冲突（课程 %s / 班级 %s），请重试。'
        % (course.name or course.id, batch.name or batch.id))


def _audit_model_label(env, model):
    """审计页模型列中文名：登记表优先，其次取模型中文 _description，
    纯英文/未知模型统一中文兜底「其它记录」（不给用户看 edu.* 技术名）。"""
    if not model:
        return ''
    if model in _AUDIT_MODEL_LABELS:
        return _AUDIT_MODEL_LABELS[model]
    try:
        desc = env[model]._description or ''
    except Exception:
        desc = ''
    if desc and any('\u4e00' <= ch <= '\u9fff' for ch in desc):
        return desc
    return '其它记录'


# 操作审计页的模型列中文名（避免 /edu/audit 出现英文模型名；未登记的
# 模型走 _audit_model_label 的中文兜底）
_AUDIT_MODEL_LABELS = {
    'edu.leave': '请假申请',
    'edu.grievance': '学生申诉',
    'edu.notice': '公告',
    'edu.notice.template': '公告模板',
    'edu.approval.delegate': '审批代理设置',
    'edu.grade.history': '成绩变更留痕',
    'edu.subject.prereq': '先修科目要求',
    'op.subject.registration': '选课注册单',
    'op.subject': '科目',
    'op.exam': '考试',
    'op.attendance.sheet': '考勤点名表',
    'op.student': '学生档案',
    'edu.certificate': '结业证书',
    'edu.audit.log': '操作审计',
    # C-1：改课影响面/调课通知写的是 op.session（原样会落到「其它记录」）
    'op.session': '课节',
}


def _absence_warn_ratio(env):
    """缺勤比例告警阈值（系统参数 edu_portal.absence_warn_ratio，默认 0.3）。"""
    try:
        return float(env['ir.config_parameter'].sudo().get_param(
            'edu_portal.absence_warn_ratio', '0.3') or 0.3)
    except (TypeError, ValueError):
        return 0.3


def privileged_staff():
    """管理员/教务处 = 最高权限（用户铁律）。

    仅用于"教师身份仅作门禁、不作数据过滤"的教师侧管理页放行；
    需要教师绑定班级数据的页面（考勤/成绩/作业）不在此列。"""
    u = request.env.user
    return (u.has_group('openeducat_core.group_op_back_office_admin')
            or u.has_group('base.group_system'))


def _profile_of_current_user(model, partner_chain=None):
    """由登录账号反查身份档案（学生 / 家长 / 教师共用的**唯一口径**）。

    实现只有一处：edu_schedule/models/identity.py（双向并集、
    ①优先①落空才查②、只加不减）—— 本函数只是控制器侧的薄壳。为什么薄壳
    必须指向那个模块、而不是在这里自建一套：见 identity.py 模块 docstring
    （模型层不能 import 控制器；且共享代码只能落在被依赖方 edu_schedule）。

    :param partner_chain: **仅兼容旧调用点**。链②的伙伴字段现在由公共
        helper 的模型表给出（学生/教师=partner_id、家长=name）。传进来的值
        若与模型表不一致，这里**直接报错**（不静默采用调用方的口径）。
    """
    if partner_chain:
        expect = PROFILE_CHAINS.get(model, (None, None))[1]
        if partner_chain != (expect or '') + '.user_ids':
            raise ValueError(
                '身份反查口径不一致：%s 的链②应为 %s.user_ids，调用方传的是 %s'
                '（统一口径见 edu_schedule/models/identity.py）'
                % (model, expect, partner_chain))
    return profile_of_user(request.env, model)


def current_parent():
    """当前登录用户对应的家长档案（无则 None）；口径见 _profile_of_current_user。"""
    return _profile_of_current_user('op.parent')


def current_student():
    """当前登录用户对应的学生记录（无则 None）。

    本文件不 import main.py 的同名函数（main ↔ roles 存在相互引用，
    局部定义避免循环导入）。
    """
    return _profile_of_current_user('op.student')


def current_faculty():
    """当前登录用户对应的教师档案（无则 None）。

    口径 = 双向并集（见 _profile_of_current_user）：只按 partner.user_id 查会漏掉
    程序化创建的教师账号（教师课表静默变空）；只按 res.users.partner_id 查又会
    漏掉本仓既有数据（挂的是 partner.user_id）。与
    edu_assess/controllers/portal.py:_current_faculty 同源。
    """
    return _profile_of_current_user('op.faculty')


# 应用面板图标：根菜单名（当前语言）→ FA 图标（无 web_icon 时的兜底图案，
# 各自保持原配色 → 白色瓦片 + 彩色图案，背景统一纯白不再彩色）。
_APPS_FA_BY_NAME = {
    '讨论': 'fa-comments', 'Discuss': 'fa-comments',
    '在线聊天': 'fa-comments-o', 'Live Chat': 'fa-comments-o',
    '日历': 'fa-calendar', 'Calendar': 'fa-calendar', '校历': 'fa-calendar-o',
    '时间表': 'fa-calendar', 'Time Table': 'fa-calendar',
    '排课管理': 'fa-calendar-plus-o', '周课表': 'fa-calendar',
    '招生报名': 'fa-pencil-square-o', '招生': 'fa-sign-in', 'Admissions': 'fa-sign-in',
    '联系人': 'fa-address-book-o', 'Contacts': 'fa-address-book-o',
    '销售': 'fa-shopping-cart', 'Sales': 'fa-shopping-cart',
    '仪表板': 'fa-tachometer', 'Dashboards': 'fa-tachometer',
    '测验': 'fa-question-circle', 'Quiz': 'fa-question-circle',
    '发票': 'fa-credit-card', 'Invoicing': 'fa-credit-card',
    '财务管理': 'fa-money', '费用账单': 'fa-credit-card',
    '教务审批': 'fa-check-square-o', '审批': 'fa-check-square-o',
    '日常管理': 'fa-tasks', '管理': 'fa-tasks',
    '在线课程': 'fa-graduation-cap', '课程': 'fa-graduation-cap',
    'LMS': 'fa-graduation-cap', 'eLearning': 'fa-play-circle', '在线学习': 'fa-play-circle',
    '资产管理': 'fa-laptop', '资产': 'fa-laptop',
    '招聘管理': 'fa-briefcase', '招聘': 'fa-user-plus', 'Recruitment': 'fa-user-plus',
    '校友工作': 'fa-briefcase',
    '灵命生活': 'fa-heart', '生命': 'fa-heart',
    '综合评估': 'fa-star-half-o', '评估': 'fa-balance-scale',
    '邀请码': 'fa-ticket', '邀请': 'fa-ticket',
    '老账号补挂身份': 'fa-link',
    '网站': 'fa-globe', 'Website': 'fa-globe',
    '员工': 'fa-users', 'Human Resources': 'fa-users', '人员': 'fa-users',
    '活动': 'fa-calendar-o', 'Events': 'fa-calendar-o',
    '出勤': 'fa-check-circle-o', 'Attendances': 'fa-check-circle-o',
    '课堂出勤率': 'fa-check-circle-o', 'Class Attendances': 'fa-check-circle-o',
    'SIS': 'fa-university', '学生': 'fa-user-o', 'Students': 'fa-user-o',
    '链接追踪器': 'fa-link', 'Link Tracker': 'fa-link',
    '作业': 'fa-file-text-o', 'Assignments': 'fa-file-text-o',
    '考试': 'fa-pencil-square', 'Exams': 'fa-pencil-square',
    '图书馆': 'fa-book', 'Library': 'fa-book', '数字图书馆': 'fa-tablet',
    '数据清除': 'fa-eraser', 'Data Cleaning': 'fa-eraser',
    '应用': 'fa-th-large', 'Apps': 'fa-th-large',
    '设置': 'fa-cog', 'Settings': 'fa-cog',
    '测试': 'fa-flask', 'Tests': 'fa-flask',
}

# FA 兜底图案的配色（与各应用主色一致；无映射用中性石板灰）
_APPS_FA_COLOR = {
    '排课管理': '#4338CA', '课表': '#4338CA', 'Time Table': '#4338CA',
    '测验': '#C8A870', 'Quiz': '#C8A870',
    '综合评估': '#0E7BF2', '评估': '#0F9B91',
    '日常管理': '#E8930C', '管理': '#E8930C',
    '灵命生活': '#E11D48', '生命': '#E11D48',
    '老账号补挂身份': '#64748B',
}


class EduParentPortal(http.Controller):

    def _child_summary(self, stu):
        sc = request.env['op.student.course'].sudo().search(
            [('student_id', '=', stu.id)], limit=1)
        att_total = request.env['op.attendance.line'].sudo().search_count(
            [('student_id', '=', stu.id)])
        att_ok = request.env['op.attendance.line'].sudo().search_count(
            [('student_id', '=', stu.id), ('present', '=', True)])
        return {
            'student': stu,
            'name': stu.name,
            'course': sc.course_id.name if sc else '',
            'batch': sc.batch_id.name if sc else '',
            'roll': sc.roll_number or '' if sc else '',
            'birth': str(stu.birth_date or ''),
            'phone': stu.partner_id.phone or '' if stu.partner_id else '',
            'email': stu.partner_id.email or '' if stu.partner_id else '',
            'att_total': att_total,
            'att_pct': round(att_ok * 100.0 / att_total) if att_total else 0,
            # 2026-10-03（沿第 39/40 轮同型问题扫出）：**「没有考勤记录」不等于「出勤率 0%」**。
            # 家长页原样把 0 印成「0% 出勤率」—— 与第 39 轮家长首页那处是**同一个毛病**，
            # 当时只修了首页，没扫同型（这次扫到了）。口径与 batch2.py 的 att_pct_txt 一致：
            # 文本态，无数据给「—」。
            'att_pct_txt': ('%d%%' % round(att_ok * 100.0 / att_total)) if att_total else '—',
        }

    @http.route('/my/child', type='http', auth='user', website=True)
    def my_child(self, **kw):
        parent = current_parent()
        children = parent.student_ids if parent else \
            request.env['op.student'].sudo()
        kids = [self._child_summary(s) for s in children]
        return request.render('edu_portal.edu_my_child', {
            'title': '我的孩子',
            'page_name': 'child',
            'kids': kids,
        })

    @http.route(['/my/child/<int:child_id>'], type='http',
                auth='user', website=True)
    def my_child_dashboard(self, child_id, **kw):
        parent = current_parent()
        stu = request.env['op.student'].sudo().browse(child_id)
        valid = stu.exists() and parent and child_id in parent.student_ids.ids
        if not valid:
            return request.redirect('/my/child')
        kid = self._child_summary(stu)

        # 近成绩（有结果记录的考试）
        Exam = request.env['op.exam.attendees'].sudo()
        marks = []
        if stu:
            for att in Exam.search([('student_id', '=', stu.id)], limit=6):
                if att.marks is not False and att.exam_id.total_marks:
                    pct = round(att.marks * 100.0 / att.exam_id.total_marks)
                    marks.append({'exam': att.exam_id.name,
                                  'marks': att.marks,
                                  'total': att.exam_id.total_marks,
                                  'pct_str': f'{pct}%'})

        # 家长视角快捷入口（复用既有学生页面）
        links = [
            ('/my/calendar', '校历', 'fa-calendar'),
            ('/student/attendance', '考勤', 'fa-check-square-o'),
            ('/student/exam', '考试', 'fa-file-text-o'),
            ('/grade-book', '成绩簿', 'fa-bar-chart'),
            ('/library/media', '图书馆', 'fa-book'),
            ('/my/fees', '费用账单', 'fa-credit-card'),
            ('/my/contacts', '通讯录', 'fa-address-book-o'),
        ]

        # 3d：学习生活摘要卡（作业/打卡/周记/请假四项真实计数）
        env = request.env
        today = fields.Date.today()
        month_start = today.replace(day=1)
        sub_line = env['op.assignment.sub.line'].sudo().search_count(
            [('student_id', '=', stu.id)])
        checkin_n = 0
        journal_n = 0
        try:
            checkin_n = env['edu.checkin.record'].sudo().search_count(
                [('student_id', '=', stu.id),
                 ('checkin_date', '>=', month_start)])
        except Exception:
            checkin_n = 0
        try:
            journal_n = env['edu.journal.entry'].sudo().search_count(
                [('student_id', '=', stu.id)])
        except Exception:
            journal_n = 0
        leave_n = env['edu.leave'].sudo().search_count(
            [('student_id', '=', stu.id)])
        summary = [
            {'label': '作业提交', 'count': sub_line, 'href': None,
             'icon': 'fa-file-text-o', 'color': 'primary'},
            {'label': '本月打卡', 'count': checkin_n, 'href': None,
             'icon': 'fa-calendar-check-o', 'color': 'success'},
            {'label': '累计周记', 'count': journal_n, 'href': None,
             'icon': 'fa-book', 'color': 'info'},
            {'label': '请假记录', 'count': leave_n, 'href': None,
             'icon': 'fa-plane', 'color': 'warning'},
        ]
        return request.render('edu_portal.edu_child_dashboard', {
            'title': f'{kid["name"]} 的仪表盘',
            'page_name': 'child_dashboard',
            'kid': kid,
            'marks': marks,
            'links': links,
            'summary': summary,
        })


    # ------------------------------------------------------------------
    # 教师考勤录入（写操作）
    # ------------------------------------------------------------------
    @http.route('/attendance/take', type='http', auth='user', website=True)
    def attendance_take(self, **kw):
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        env = request.env
        batch_id = kw.get('batch_id')
        date_str = kw.get('date') or fields.Date.today().isoformat()

        # 教师任教会话涉及的全部班级（供下拉选择）
        sess = env['op.session'].sudo().search([('faculty_id', '=', fac.id)])
        batches = sess.mapped('batch_id')
        courses_by_batch = {b.id: sess.filtered(
            lambda s, b=b: s.batch_id.id == b.id)[:1].course_id for b in batches}

        students, course = [], None
        if batch_id:
            try:
                bid = int(batch_id)
            except ValueError:
                bid = 0
            scs = env['op.student.course'].sudo().search(
                [('batch_id', '=', bid)])
            students = scs.mapped('student_id')
            course = courses_by_batch.get(bid)

        # 第 5 批 B：学生自助签到令牌状态（选中班级+日期时）
        selfcheck = None
        sel_bid = int(batch_id) if batch_id and batch_id.isdigit() else None
        if sel_bid:
            try:
                sel_date = fields.Date.to_date(date_str)
            except (TypeError, ValueError):
                sel_date = None
            if sel_date:
                tok = request.env['edu.attend.self.token'].sudo().search([
                    ('batch_id', '=', sel_bid),
                    ('checkin_date', '=', sel_date),
                    ('active', '=', True)], limit=1)
                if tok and tok.expire_at and fields.Datetime.now() < tok.expire_at:
                    base = request.env['ir.config_parameter'].sudo() \
                        .get_param('web.base.url') or ''
                    selfcheck = {
                        'token': tok.token,
                        'expire_str': fields.Datetime.context_timestamp(
                            tok, tok.expire_at).strftime('%H:%M:%S'),
                        'scan_url': '%s/attendance/selfcheck/%s' % (
                            base.rstrip('/'), tok.token),
                    }
        # 课代表（队长裁定补做项）：老师必须**能看见**课代表提交的待确认点名表。
        # 既有教师侧 GET 不按日期查「当日已有点名表」（只查「上一次」用于复制），
        # 所以这里补一个「该班该日已存在、且由课代表提交、停在 start」的入口。
        pending_sheet = None
        if sel_bid and sel_date:
            ps = env['op.attendance.sheet'].sudo().search([
                ('batch_id', '=', sel_bid),
                ('attendance_date', '=', sel_date),
                ('state', '=', 'start'),
                ('submitted_by_rep_id', '!=', False)], limit=1)
            if ps:
                pending_sheet = {
                    'id': ps.id,
                    'name': ps.name or '',
                    'rep': ps.submitted_by_rep_id.student_id.name or '',
                    'subject': ps.rep_subject_id.name or '',
                    'n': len(ps._rep_proposal_map()),
                    'at': fields.Datetime.context_timestamp(
                        ps, ps.rep_submitted_at).strftime('%Y/%m/%d %H:%M')
                        if ps.rep_submitted_at else '',
                }
        # F2：复制上次记录（?copy=1）+ 缺勤比例告警
        prefill, copy_from = {}, ''
        if sel_bid:
            Sheet = env['op.attendance.sheet'].sudo()
            last = Sheet.search([('batch_id', '=', sel_bid)],
                                order='attendance_date desc, id desc',
                                limit=1)
            if last and last.attendance_date:
                copy_from = last.attendance_date.strftime('%Y/%m/%d')
            if last and kw.get('copy') == '1':
                for line in env['op.attendance.line'].sudo().search(
                        [('attendance_id', '=', last.id)]):
                    prefill[line.student_id.id] = (
                        'late' if line.late
                        else ('absent' if line.absent else 'present'))
        absent_warn = []
        warn_ratio = _absence_warn_ratio(env)
        if students and warn_ratio > 0:
            Line = env['op.attendance.line'].sudo()
            for stu in students:
                total = Line.search_count([('student_id', '=', stu.id)])
                absent = Line.search_count(
                    [('student_id', '=', stu.id), ('absent', '=', True)])
                if total >= 3 and absent / float(total) >= warn_ratio:
                    absent_warn.append({
                        'name': stu.name, 'absent': absent, 'total': total,
                        'pct': int(round(absent * 100.0 / total)),
                    })
        values = {
            'title': '考勤录入',
            'page_name': 'attendance_take',
            'prefill': prefill,
            'copy': kw.get('copy') == '1',
            'copy_from': copy_from,
            'absent_warn': absent_warn,
            'warn_ratio': int(round(warn_ratio * 100)),
            'batches': batches,
            'students': students,
            'course': course,
            'sel_batch': sel_bid,
            'date': date_str,
            'saved': kw.get('saved'),
            'dup': kw.get('dup') == '1',
            'dup_sheet': int(kw.get('dup_sheet', 0) or 0)
            if str(kw.get('dup_sheet', 0) or 0).isdigit() else 0,
            'selfcheck': selfcheck,
            'pending_sheet': pending_sheet,
        }
        return request.render('edu_portal.edu_attendance_take', values)

    @http.route('/attendance/confirm_rep_sheet', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def attendance_confirm_rep_sheet(self, **post):
        """老师一键确认课代表提交的点名（落考勤行 + state='done'）。

        - 只能确认**本人任教班级**的表（否则按不存在处理，303 回 /attendance/take）；
        - 落 line 与置 done 在同一事务里 => 考勤统计**正好在确认这一刻**才变化；
        - 既有教师流程（GET /attendance/take 空白表单 + POST /attendance/save）一字未改。
        """
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        env = request.env
        try:
            sid = int(post.get('sheet_id', 0))
        except ValueError:
            return request.redirect('/attendance/take')
        sheet = env['op.attendance.sheet'].sudo().browse(sid)
        if not sheet.exists() or sheet.state != 'start':
            return request.redirect('/attendance/take')
        if sheet.batch_id.id not in self._teacher_taught_batches(fac):
            return request.redirect('/attendance/take')
        sheet.rep_confirm()
        env['edu.audit.log'].sudo()._log(
            '考勤确认', 'op.attendance.sheet', sheet.id, sheet.name or '',
            '确认课代表提交的点名（班级 %s · %s · %d 人）'
            % (sheet.batch_id.name or '', sheet.attendance_date or '',
               len(sheet._rep_proposal_map())))
        return request.redirect(
            '/attendance/take?batch_id=%d&date=%s&saved=1'
            % (sheet.batch_id.id, sheet.attendance_date or ''))

    @http.route('/attendance/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def attendance_save(self, **post):
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        env = request.env
        try:
            bid = int(post.get('batch_id', 0))
            cid = int(post.get('course_id', 0))
            adate = post.get('date') or fields.Date.today().isoformat()
        except ValueError:
            return request.redirect('/attendance/take')

        batch = env['op.batch'].sudo().browse(bid)
        course = env['op.course'].sudo().browse(cid)
        if not batch.exists() or not course.exists():
            return request.redirect('/attendance/take?error=1')

        # 登记簿：同课程同班级复用（取或建的唯一实现见 attendance_register()）
        register = attendance_register(env, course, batch)

        scs = env['op.student.course'].sudo().search([('batch_id', '=', bid)])
        students = scs.mapped('student_id')

        # 重复提交防护：同班同课程同日期已有点名表 → 拒绝并指引查看
        Sheet = env['op.attendance.sheet'].sudo()
        existing = Sheet.search([
            ('course_id', '=', cid),
            ('batch_id', '=', bid),
            ('attendance_date', '=', adate),
        ], limit=1)
        if existing:
            return request.redirect(
                '/attendance/take?batch_id=%d&date=%s&dup=1&dup_sheet=%d'
                % (bid, adate, existing.id))

        sheet = env['op.attendance.sheet'].sudo().create({
            'register_id': register.id,
            'course_id': cid,
            'batch_id': bid,
            'attendance_date': adate,
            'faculty_id': fac.id,
        })
        n = 0
        Line = env['op.attendance.line'].sudo()
        for stu in students:
            status = post.get(f'status_{stu.id}', 'present')
            present = status in ('present', 'late')
            late = status == 'late'
            absent = status == 'absent' or not present
            Line.create({
                'attendance_id': sheet.id,
                'student_id': stu.id,
                'present': present,
                'late': late,
                'absent': absent,
                'excused': False,
                'course_id': cid,
                'batch_id': bid,
                'attendance_date': adate,
            })
            n += 1
        # 4a 审计：考勤录入
        env['edu.audit.log'].sudo()._log(
            '考勤录入', 'op.attendance.sheet', sheet.id, sheet.name or '',
            '班级 %s · %s · %d 人' % (batch.name or '', adate, n))
        _logger.info('edu_portal: 考勤录入已保存 sheet=%s lines=%s',
                     sheet.id, n)
        # 保存成功必须回到带 saved=1 的结果页。这里原来是以 print(...) 结尾 ——
        # 9dd3ea5（自助签到 p5-B）把本路由的 return 挪进了 attendance_selfcheck_scan
        # 的 return render 之后（那句死代码现已删除），于是本路由返回 None，
        # 老师保存成功后拿到的是**空白页**（2026-09 事故的第二症状）。
        return request.redirect(
            '/attendance/take?batch_id=%d&date=%s&saved=1' % (bid, adate))

    # ------------------------------------------------------------------
    # 第 5 批 B：学生扫码自助签到（限时令牌，防代签）
    # ------------------------------------------------------------------
    @http.route('/attendance/selfcheck/start', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def attendance_selfcheck_start(self, **post):
        """教师开启/刷新自助签到：作废旧令牌并签发新令牌（60 秒有效）。"""
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        import secrets as _secrets
        try:
            bid = int(post.get('batch_id', 0))
            cdate = fields.Date.to_date(post.get('date'))
        except (TypeError, ValueError):
            return request.redirect('/attendance/take')
        Token = request.env['edu.attend.self.token'].sudo()
        Token.invalidate_batch_date(bid, cdate)
        Token.create({
            'batch_id': bid,
            'checkin_date': cdate,
            'token': _secrets.token_urlsafe(16),
            'expire_at': fields.Datetime.now() + datetime.timedelta(seconds=60),
        })
        # 4a 审计：开启自助签到
        env = request.env
        env['edu.audit.log'].sudo()._log(
            '考勤自助签到', 'edu.attend.self.token', 0, '',
            '班级 %s · %s 开启/刷新' % (bid, cdate))
        return request.redirect(
            '/attendance/take?batch_id=%d&date=%s' % (bid, cdate))

    @http.route('/attendance/selfcheck/stop', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def attendance_selfcheck_stop(self, **post):
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        try:
            bid = int(post.get('batch_id', 0))
            cdate = fields.Date.to_date(post.get('date'))
        except (TypeError, ValueError):
            return request.redirect('/attendance/take')
        request.env['edu.attend.self.token'].sudo().invalidate_batch_date(
            bid, cdate)
        return request.redirect(
            '/attendance/take?batch_id=%d&date=%s' % (bid, cdate))

    @http.route('/attendance/selfcheck/<token>', type='http', auth='user',
                website=True)
    def attendance_selfcheck_scan(self, token, **kw):
        """学生扫码自助签到：令牌有效 + 本人是该班学生 + 当日点名表存在
        → 本人考勤行置为到堂（已在则幂等提示）。"""
        env = request.env
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        tok = env['edu.attend.self.token'].sudo().search(
            [('token', '=', token), ('active', '=', True)], limit=1)
        state = 'bad_token'
        if tok:
            if fields.Datetime.now() > tok.expire_at:
                state = 'expired'
            elif tok.checkin_date != fields.Date.today():
                state = 'expired'
            else:
                # 学生须属于令牌班级（在读课程归组）
                in_batch = env['op.student.course'].sudo().search_count(
                    [('student_id', '=', student.id),
                     ('batch_id', '=', tok.batch_id.id)])
                if not in_batch:
                    state = 'not_in_batch'
                else:
                    sheet = env['op.attendance.sheet'].sudo().search([
                        ('batch_id', '=', tok.batch_id.id),
                        ('attendance_date', '=', tok.checkin_date)],
                        limit=1)
                    if not sheet:
                        state = 'no_sheet'
                    else:
                        Line = env['op.attendance.line'].sudo()
                        line = Line.search([
                            ('attendance_id', '=', sheet.id),
                            ('student_id', '=', student.id)], limit=1)
                        if line:
                            if line.present:
                                state = 'already'
                            else:
                                line.write({
                                    'present': True, 'late': False,
                                    'absent': False, 'excused': False})
                                state = 'ok'
                        else:
                            Line.create({
                                'attendance_id': sheet.id,
                                'student_id': student.id,
                                'present': True, 'late': False,
                                'absent': False, 'excused': False,
                                'course_id': sheet.course_id.id,
                                'batch_id': tok.batch_id.id,
                                'attendance_date': tok.checkin_date})
                            state = 'ok'
        msgs = {
            'ok': ('success', '签到成功！今天的到堂已记录。'),
            'already': ('info', '你今天已经签过到了。'),
            'expired': ('warning', '二维码已过期，请让老师刷新后再扫。'),
            'bad_token': ('danger', '签到码无效，请核对后重试。'),
            'not_in_batch': ('danger', '你不属于该班级，无法使用此签到码。'),
            'no_sheet': ('warning', '老师还没有创建今天的点名表，稍后再试。'),
        }
        alert_type, msg = msgs.get(state, ('danger', '签到失败，请重试。'))
        return request.render('edu_portal.edu_selfcheck_result', {
            'title': '扫码签到',
            'page_name': 'selfcheck',
            'alert_type': alert_type,
            'msg': msg,
            'state': state,
        })


    # ------------------------------------------------------------------
    # 教师打分（写操作）：为考试录入学生得分
    # ------------------------------------------------------------------
    def _approval_scope_domain(self, model_name='edu.leave'):
        """薄包装：口径已提取为模块级 approval_scope_domain(env)（t67）。

        提取动机：该口径需被 enroll.py（选课审批批量）复用，而它够不到
        本控制器类的方法 → 提取为模块级函数，避免复制一份规则。
        口径与 F2 的考试归属一致（都落在「该教师教不教这个人/这场考试」）：
        列表、批量与单条三处共用同一域，做到「看得见的 = 能处置的」。

        :param model_name: §8.2 起用于分流「请假的并集域 / 申诉的老域」；
            默认 'edu.leave'（既有请假调用点一字不改），申诉列表显式传
            'edu.grievance'（edu.grievance 没有 first/second_approver_id 字段）。
        """
        return approval_scope_domain(request.env, model_name)

    def _scoped_record(self, model_name, rec_id, extra_domain=None):
        """薄包装（t67）：见模块级 scoped_record(env, ...)。"""
        return scoped_record(request.env, model_name, rec_id, extra_domain)

    def _scoped_records(self, model_name, ids, extra_domain=None):
        """薄包装（t67）：见模块级 scoped_records(env, ...)。"""
        return scoped_records(request.env, model_name, ids, extra_domain)

    def _teacher_taught_batches(self, fac):
        """当前教师任教的班级 id（op.session.faculty_id 口径）。"""
        return request.env['op.session'].sudo().search(
            [('faculty_id', '=', fac.id)]).mapped('batch_id').ids

    def _teacher_exam_domain(self):
        """考试可见域（t34 F2）。

        - 教务处/管理员（privileged_staff）：不限（与既有后台口径一致）；
        - 教师：本人为 responsible_id 的考试，或本人任教班级的考试；
        - 无教师档案：空集。
        """
        if privileged_staff():
            return []
        fac = current_faculty()
        if not fac:
            return [('id', '=', 0)]
        return ['|', ('responsible_id', 'in', [fac.id]),
                ('batch_id', 'in', self._teacher_taught_batches(fac))]

    def _teacher_exam(self, exam_id):
        """取归属当前教师的考试；不存在/越权一律返回空记录集（按不存在处理）。"""
        Exam = request.env['op.exam'].sudo()
        try:
            eid = int(exam_id or 0)
        except (TypeError, ValueError):
            eid = 0
        rec = Exam.browse(eid)
        if not rec.exists():
            return Exam.browse()
        if rec in Exam.search(self._teacher_exam_domain()):
            return rec
        return Exam.browse()

    @http.route('/grading/entry', type='http', auth='user', website=True)
    def grading_entry(self, **kw):
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        env = request.env
        exam_id = kw.get('exam_id')
        # t34 F2：考试列表与选中项都收敛到本人任教范围（越权按不存在处理）
        exam = self._teacher_exam(exam_id) if exam_id else None
        exams = env['op.exam'].sudo().search(self._teacher_exam_domain())
        attendees = []
        saved = kw.get('saved')
        if exam and exam.exists():
            for att in env['op.exam.attendees'].sudo().search(
                    [('exam_id', '=', exam.id)]):
                attendees.append({
                    'att': att,
                    'name': att.student_id.name,
                })
        # F3：留痕条数 + 可复制的上一场（同科目、更早开始时间）
        history_n = 0
        prev_exam = None
        if exam and exam.exists():
            history_n = env['edu.grade.history'].sudo().search_count(
                [('exam_id', '=', exam.id)])
            prev_exam = env['op.exam'].sudo().search([
                ('subject_id', '=', exam.subject_id.id),
                ('id', '!=', exam.id),
                ('start_time', '<', exam.start_time)],
                order='start_time desc', limit=1)
        values = {
            'title': '成绩录入',
            'page_name': 'grading_entry',
            'exams': exams,
            'exam': exam if exam and exam.exists() else None,
            'attendees': attendees,
            'saved': saved,
            'history_n': history_n,
            'prev_exam': prev_exam if prev_exam and prev_exam.exists()
                         else None,
            'imported': kw.get('imported'),
            'copied': kw.get('copied'),
            'skipped': kw.get('skipped'),
        }
        return request.render('edu_portal.edu_grading_entry', values)

    @http.route('/grading/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def grading_save(self, **post):
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        env = request.env
        try:
            exam_id = int(post.get('exam_id', 0))
        except ValueError:
            return request.redirect('/grading/entry')
        # t34 F2：入库前先判归属（越权按不存在处理），避免越权写分
        exam = self._teacher_exam(exam_id)
        if not exam:
            return request.redirect('/grading/entry')
        Attendees = env['op.exam.attendees'].sudo()
        Hist = env['edu.grade.history'].sudo()
        n = 0
        # F3：改分走 edu.grade.history.edu_apply_marks 唯一入口 → 逐条留痕
        # （谁、何时、把哪个学生的分数从多少改到多少，见成绩留痕页）
        for key, val in post.items():
            if not key.startswith('marks_'):
                continue
            att_id = int(key[6:])
            att = Attendees.browse(att_id)
            if not (att.exists() and att.exam_id.id == exam_id):
                continue
            try:
                marks = int(val)
            except (TypeError, ValueError):
                continue
            status = post.get('st_%d' % att_id)
            if Hist.edu_apply_marks(
                    att, marks=marks,
                    status=status if status in ('present', 'absent') else None,
                    source='manual'):
                n += 1
        # 4a 审计：只记汇总（改分明细已进成绩留痕表，避免 30 条截断丢信息）
        detail = '更新 %d 名学生成绩（明细见成绩留痕，共 %d 条）' % (
            n, Hist.search_count([('exam_id', '=', exam_id)]))
        env['edu.audit.log'].sudo()._log(
            '成绩录入', 'op.exam', exam_id, exam.name or '', detail)
        return request.redirect(f'/grading/entry?exam_id={exam_id}&saved=1&scount={n}')


    # ------------------------------------------------------------------
    # 教师发布作业（写操作）
    # ------------------------------------------------------------------
    @http.route('/assignment/publish', type='http', auth='user', website=True)
    def assignment_publish(self, **kw):
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        env = request.env
        values = {
            'title': '发布作业',
            'page_name': 'assignment_publish',
            'subjects': env['op.subject'].sudo().search([]),
            'courses': env['op.course'].sudo().search([]),
            'batches': env['op.batch'].sudo().search([]),
            'types': env['grading.assignment.type'].sudo().search([]),
        }
        return request.render('edu_portal.edu_assignment_publish', values)

    @http.route('/assignment/publish_save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def assignment_publish_save(self, **post):
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        env = request.env
        name = (post.get('name') or '').strip()
        if not name:
            return request.redirect('/assignment/publish')
        def _norm_dt(val):
            """datetime-local 提交 '2026-08-24T08:00' → Datetime 可解析格式。"""
            if not val:
                return False
            val = val.strip().replace('T', ' ')
            if len(val) == 16:
                val += ':00'
            return val

        # 2026-10-03（数据一致性复核）：本表单的「课程」「班级」是两个**互不约束**的下拉
        # （控制器里 courses/batches 都是 `search([])`），而 `op.assignment` 同时挂 course_id 与 batch_id，
        # 且领域模型里 `batch.course_id` 本来就定了这对关系 ⇒ 可以提交「课程 A + 班级 B」这种矛盾组合。
        # **这不是假设**：库里实测有 2 条 `course_id=13`（基督教研究硕士科）却挂在 `batch_id=8`（预备科）名下的作业，
        # 而作业页/首页都按 batch+course 取数 ⇒ **学生永远看不到它们**（即第 42 轮那 2 条孤儿数据的来历）。
        # ⇒ 落库前把这一对校验掉，**明确告诉用户**；不静默改写他的选择（第 36 轮那处「静默改写下场」的教训）。
        _batch = env['op.batch'].sudo().browse(int(post.get('batch_id', 0) or 0))
        _course = env['op.course'].sudo().browse(int(post.get('course_id', 0) or 0))
        if _batch.exists() and _batch.course_id and _course.exists() \
                and _batch.course_id.id != _course.id:
            return request.redirect('/assignment/publish?error=course_batch')

        try:
            vals = {
                'name': name,
                'course_id': int(post.get('course_id', 0)),
                'batch_id': int(post.get('batch_id', 0)),
                'subject_id': int(post.get('subject_id', 0)) or False,
                'assignment_type': int(post.get('type_id', 0)),
                'faculty_id': fac.id,
                'marks': float(post.get('marks', 0) or 0),
                'issued_date': _norm_dt(post.get('issued_date')),
                'submission_date': _norm_dt(post.get('submission_date')),
                'description': post.get('description') or '',
                'state': 'publish',
            }
            rec = env['op.assignment'].sudo().create(vals)
            # D 组第一批（P3）：写路径上的调试 print() → 日志（同本文件其余处）。
            _logger.info('edu_portal: 作业已发布 id=%s by faculty=%s',
                         rec.id, fac.id)
        except Exception as e:
            _logger.info('edu_portal: 作业发布失败：%s',
                         str(e).replace("\n", " ")[:200])
            return request.redirect('/assignment/publish?error=save')
        # 2026-10-03：原先成功后跳 `/student/assignment/details` —— 那是**学生页**。
        # 实测（faculty@local 发布成功）：落地页写着「该页面仅面向学生账号……请返回门户首页使用
        # 与您身份对应的功能」⇒ **教师刚发布成功，立刻吃一个拒止提示**，等于把成功当失败。
        # ⇒ 改跳教师自己的作业列表 `/assignment/manage`（同一功能的正确归属页，该页本就列出
        #   刚发布的这条并带「编辑 / 提交情况」入口）。
        return request.redirect('/assignment/manage')


    # ------------------------------------------------------------------
    # 家长为孩子请假 + 教师审批（写操作闭环）
    # ------------------------------------------------------------------
    @http.route(['/my/child/<int:child_id>/leave',
                 '/my/child/<int:child_id>/leave/saved'],
                type='http', auth='user', website=True)
    def child_leave_form(self, child_id, **kw):
        parent = current_parent()
        stu = request.env['op.student'].sudo().browse(child_id)
        if not stu.exists() or not parent or \
                child_id not in parent.student_ids.ids:
            return request.redirect('/my/child')
        # D 组第一批（P3）：/leave/saved 是同一条 route 上的**孤儿别名** ——
        # 成功提示只认查询串（roles.xml 的 t-if="saved"），而提交后的回执地址是
        # /my/child/<id>/leave?saved=1（见 child_leave_save 的 redirect）；全仓没有任何
        # 地方链到 /leave/saved ⇒ 走这条**路径**进来只会看到一张普通空表单，永远看不到
        # 「请假申请已提交」。这里把它按本仓既有规矩（旧路径 303 → 现役路径，同
        # /my/checkin*、eval_compat）收敛到唯一回执地址，既不做成 404，也不再本地
        # 复刻一遍 saved 语义（浏览器地址栏也自愈到规范地址）。
        if request.httprequest.path.rstrip('/').endswith('/saved'):
            return request.redirect(
                '/my/child/%d/leave?saved=1' % child_id, code=303)
        return request.render('edu_portal.edu_child_leave', {
            'title': f'为 {stu.name} 请假',
            'page_name': 'child_leave',
            'kid': stu,
            'saved': 'saved' in kw,
        })

    @http.route('/my/child/<int:child_id>/leave/save', type='http',
                auth='user', methods=['POST'], website=True, csrf=True)
    def child_leave_save(self, child_id, **post):
        parent = current_parent()
        stu = request.env['op.student'].sudo().browse(child_id)
        if not stu.exists() or not parent or \
                child_id not in parent.student_ids.ids:
            return request.redirect('/my/child')
        # §7.5（S3）：门户侧**禁止事后补假** —— date_from < 提交日 ⇒ 硬拒、不落库。
        # 边界：今天请假、今天提交（date_from == today）**允许**（不是「事后」）；
        # 后台「请假审批 → 新建」不受此校验（教务代录历史/特殊情况，走 backfilled 通道）。
        if leave_backdated_guard(post.get('date_from')):
            raise UserError(
                '《请假条例》一·2 规定严禁事后补假，请勿补提过去日期的申请。')
        Leave = request.env['edu.leave'].sudo()
        seq = request.env['ir.sequence'].sudo().search(
            [('code', '=', 'edu.leave')], limit=1)
        name = seq.next_by_code('edu.leave') if seq else ''
        if not name:
            name = f'LV{int(request.env["edu.leave"].search_count([])) + 1:06d}'
        vals = {
            'name': name,
            'student_id': stu.id,
            'leave_type': post.get('leave_type', 'sick'),
            'date_from': post.get('date_from'),
            'date_to': post.get('date_to') or post.get('date_from'),
            'reason': post.get('reason', ''),
            'state': 'request',
        }
        # §7.2（S3）：证明字段转发 + 附件落库 + S2 的附件复核；§7.5：带上
        # 「门户自助提交」context（家长本身不是特权账号，这里是显式声明而非兜底）。
        vals.update(leave_proof_vals(post))
        mk = Leave.with_context(**leave_portal_context()).create(vals)
        leave_attach_proof_file(mk, post)
        leave_check_proof(mk)
        _logger.info('edu_portal: 家长代提交请假 %s（student=%s）', mk.name, stu.id)
        return request.redirect(f'/my/child/{child_id}/leave?saved=1')

    @http.route('/leave/approvals', type='http', auth='user', website=True)
    def leave_approvals(self, **kw):
        # §8.1 准入（S3 放宽，判据见 leave_portal_approver）：
        # 有教师档案 ∪ 教务处/系统组 ∪「本级应批人是我」。
        # 最后一档是 §3.3「没有班主任也能跑 / 老师到位后只填数据即生效」的前提——
        # op.batch.homeroom_teacher_id 存的是 res.users，而本仓 op.faculty 0 个在职行，
        # 班主任完全可能没有教师档案；沿用老门槛会让最主要的使用者连队列都进不去。
        if not leave_portal_approver():
            return request.redirect('/my/home')
        Leave = request.env['edu.leave'].sudo()
        filterby = kw.get('filterby') or 'all'
        search = (kw.get('search') or '').strip()
        page = max(1, int(kw.get('page', 1) or 1))
        # t34 F3：列表与可处置范围同一域（教师只见任教班级的申请）
        domain = self._approval_scope_domain()
        if filterby in ('request', 'approved', 'refused'):
            domain.append(('state', '=', filterby))
        if search:
            domain += ['|', '|',
                       ('name', 'ilike', search),
                       ('student_id.name', 'ilike', search),
                       ('reason', 'ilike', search)]
        total = Leave.search_count(domain)
        PAGE_SIZE = 20
        leaves = Leave.search(domain, order='id desc',
                              limit=PAGE_SIZE,
                              offset=(page - 1) * PAGE_SIZE)
        counts = {row[0]: row[1] for row in Leave._read_group(
            [], ['state'], ['__count'])}
        return request.render('edu_portal.edu_leave_approvals', {
            'title': '请假审批',
            'page_name': 'leave_approvals',
            'leaves': leaves,
            'filterby': filterby,
            'search': search,
            'pager': pager('/leave/approvals', total=total, page=page,
                           step=PAGE_SIZE,
                           url_args={'filterby': filterby,
                                     'search': search}),
            'counts': {
                'all': sum(counts.values()),
                'request': counts.get('request', 0),
                'approved': counts.get('approved', 0),
                'refused': counts.get('refused', 0),
            },
        })

    @http.route('/leave/set_state', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def leave_set_state(self, **post):
        # §8.1 准入（S3 放宽，判据见 leave_portal_approver）：
        # 有教师档案 ∪ 教务处/系统组 ∪「本级应批人是我」。
        # 最后一档是 §3.3「没有班主任也能跑 / 老师到位后只填数据即生效」的前提——
        # op.batch.homeroom_teacher_id 存的是 res.users，而本仓 op.faculty 0 个在职行，
        # 班主任完全可能没有教师档案；沿用老门槛会让最主要的使用者连队列都进不去。
        if not leave_portal_approver():
            return request.redirect('/my/home')
        try:
            lid = int(post.get('leave_id', 0))
            new_state = post.get('state', '')
        except ValueError:
            return request.redirect('/leave/approvals')
        # t34 F3：单条路由与批量同口径（越权按不存在处理）
        rec = self._scoped_record('edu.leave', lid)
        # §3.1（S3）：接受第三个动作值 'send_back' = 二级退回到一级（设计稿
        # 只给了动作没给路由；本路由是门户唯一审批入口 ⇒ 加一个值，既有的
        # 'approved' / 'refused' 行为与参数一字不变）。
        # §4.3(2)/§8.1（S3）：**动作判据** = 本单当前这一级的 first_approver_id /
        # second_approver_id 本人（或 privileged_staff 恒可批，铁律不破）。
        # 为什么不能只靠上面的作用域域：§8.2 的域含「我任教班级 / 我当班主任的班」
        # 两项 ⇒ 转交出去之后原审批人**仍看得见**这张单（设计的可见性口径），
        # 但「能不能批」按 §4.3(2) 必须落到快照上 —— 否则「转交后原审批人不能
        # 再批」这条用户裁决会在班主任身上静默失效。
        # 不是本级应批人 ⇒ 与「不存在」同样处理：不写任何字段、303 回队列。
        if rec.exists() and new_state in ('approved', 'refused', 'send_back') \
                and _leave_can_act(rec, request.env.user):
            # A1：驳回可附原因（详情页必填，列表页快捷按钮保持旧行为可不填）
            reason = (post.get('reject_reason') or '').strip()[:500]
            was_pending = rec.state == 'request'
            # 课代表需求⑥ + §3.1：审批留痕与状态流转交给 S2 的冻结动作
            # （一级通过后是 approved 还是 pending_second 由 need_second 决定，
            # 那是模型判定，控制器不得复制）。动作缺席 ⇒ 回退既有直写，见
            # 文末 _leave_flow_apply_state（含「为什么要有这层」的完整理由）。
            applied = _leave_flow_apply_state(rec, new_state, reason,
                                             was_pending=was_pending)
            # 4a 审计：请假审批
            # ⚠ S2 的冻结动作**内部已写**「请假审批」审计 + 申请人通知（队长
            # 2026-09-25 裁决：模型层是唯一事实源）⇒ 只有回退路径（'legacy'）
            # 才由本路由补审计，否则每笔审批会多出 1 条重复审计。
            if applied == 'legacy':
                request.env['edu.audit.log'].sudo()._log(
                    '请假审批', 'edu.leave', rec.id, rec.name or '',
                    '状态 → %s' % new_state)
            # D 组第一批（P3）：写路径上的调试 print() → 日志。
            _logger.info('edu_portal: 请假审批 %s -> %s', rec.name, new_state)
        # A1：详情页表单带 next 回跳详情（仅接受本域请假路径，防开放跳转）
        next_url = post.get('next') or ''
        if not next_url.startswith('/leave/'):
            next_url = '/leave/approvals'
        return request.redirect(next_url)

    # ------------------------------------------------------------------
    # A1：请假审批详情页（教师视角）——常驻同意/驳回主行动 + 状态进度条
    # ------------------------------------------------------------------

    @staticmethod
    def _leave_detail_vals(rec):
        """请假详情展示字段（含类型中文标签与天数）。"""
        type_label = {
            'sick': '病假', 'legal': '法定假',
            'casual': '事假', 'other': '其他',
            # §6（S3）：新类型的详情页标签（缺了就显示英文 code）
            'marriage_funeral': '婚丧假', 'winter_summer': '寒暑假',
            'practice_week': '实践周',
        }.get(rec.leave_type, rec.leave_type or '—')
        days = 0
        if rec.date_from and rec.date_to and rec.date_to >= rec.date_from:
            days = (rec.date_to - rec.date_from).days + 1
        return {
            'type_label': type_label,
            'date_from': rec.date_from.strftime('%Y/%m/%d')
                          if rec.date_from else '—',
            'date_to': rec.date_to.strftime('%Y/%m/%d')
                        if rec.date_to else '—',
            'days': days,
            'student_name': rec.student_id.name or '—',
        }

    @staticmethod
    def _leave_steps(state):
        """请假步骤条：已提交 → 审批中 → 已通过/已驳回（§3.1：二级单多一格）。"""
        if state == 'pending_second':
            # §3.1 新增第四态：一级已通过、等二级（教务）审批。
            # 单独一档而不是复用 request —— 否则「待一级」与「待二级」在
            # 进度条上分不开，一级审批人会看到自己已经批过的单。
            return [
                {'label': '已提交', 'cls': 'ux-step--done'},
                {'label': '一级已通过', 'cls': 'ux-step--done'},
                {'label': '待二级审批', 'cls': 'ux-step--current'},
                {'label': '已通过 / 已驳回', 'cls': 'ux-step--todo'},
            ]
        if state == 'approved':
            return [
                {'label': '已提交', 'cls': 'ux-step--done'},
                {'label': '审批中', 'cls': 'ux-step--done'},
                {'label': '已通过', 'cls': 'ux-step--done'},
            ]
        if state == 'refused':
            return [
                {'label': '已提交', 'cls': 'ux-step--done'},
                {'label': '审批中', 'cls': 'ux-step--done'},
                {'label': '已驳回', 'cls': 'ux-step--danger'},
            ]
        # request：审批中
        return [
            {'label': '已提交', 'cls': 'ux-step--done'},
            {'label': '审批中', 'cls': 'ux-step--current'},
            {'label': '已通过 / 已驳回', 'cls': 'ux-step--todo'},
        ]

    _GRIEVANCE_STATE_LABEL = {
        'draft': '草稿', 'submitted': '已提交', 'in_progress': '处理中',
        'resolve': '已解决', 'reject': '已驳回', 'close': '已关闭',
    }

    @classmethod
    def _grievance_steps(cls, state):
        """申诉步骤条：已提交 → 处理中 → 已解决/已驳回（close 显示已关闭）。"""
        pending = 'ux-step--current' if state == 'submitted' \
            else 'ux-step--done'
        if state in ('submitted', 'in_progress'):
            last = {'label': '已解决 / 已驳回', 'cls': 'ux-step--todo'}
        elif state == 'reject':
            last = {'label': '已驳回', 'cls': 'ux-step--danger'}
        elif state == 'close':
            last = {'label': '已关闭', 'cls': 'ux-step--done'}
        else:
            last = {'label': '已解决', 'cls': 'ux-step--done'}
        return [
            {'label': '已提交', 'cls': 'ux-step--done'},
            {'label': '处理中', 'cls': pending},
            last,
        ]

    @http.route('/grievances/approvals', type='http', auth='user',
                website=True)
    def grievance_approvals(self, **kw):
        """A1：申诉处理列表（教师门户侧；默认待处理 = submitted/in_progress）。"""
        fac = current_faculty()
        if not fac and not privileged_staff():
            return request.redirect('/my/home')
        Grev = request.env['edu.grievance'].sudo()
        filterby = kw.get('filterby') or 'pending'
        search = (kw.get('search') or '').strip()
        page = max(1, int(kw.get('page', 1) or 1))
        # t34 F3：与请假审批同口径（教师只见任教班级的申诉）
        # §8.2（S3）：显式声明这是**申诉**域 —— 请假侧的并集项（first/second
        # _approver_id）在 edu.grievance 上不存在，不能串用。
        domain = self._approval_scope_domain('edu.grievance')
        if filterby == 'pending':
            domain.append(('state', 'in', ('submitted', 'in_progress')))
        elif filterby in ('draft', 'resolve', 'reject', 'close'):
            domain.append(('state', '=', filterby))
        if search:
            domain += ['|', '|',
                       ('name', 'ilike', search),
                       ('student_id.name', 'ilike', search),
                       ('subject', 'ilike', search)]
        total = Grev.search_count(domain)
        PAGE_SIZE = 20
        grevs = Grev.search(domain, order='id desc', limit=PAGE_SIZE,
                            offset=(page - 1) * PAGE_SIZE)
        counts = {row[0]: row[1] for row in Grev._read_group(
            [], ['state'], ['__count'])}
        return request.render('edu_portal.edu_grievance_approvals', {
            'title': '申诉处理',
            'page_name': 'grievance_approvals',
            'grievances': grevs,
            'state_labels': self._GRIEVANCE_STATE_LABEL,
            'filterby': filterby,
            'search': search,
            'pager': pager('/grievances/approvals', total=total, page=page,
                           step=PAGE_SIZE,
                           url_args={'filterby': filterby,
                                     'search': search}),
            'counts': {
                'pending': sum(counts.get(k, 0)
                               for k in ('submitted', 'in_progress')),
                'resolve': counts.get('resolve', 0),
                'reject': counts.get('reject', 0),
                'all': sum(counts.values()),
            },
        })

    @http.route('/grievances/approvals/<int:gid>', type='http', auth='user',
                website=True)
    def grievance_detail(self, gid, **kw):
        fac = current_faculty()
        if not fac and not privileged_staff():
            return request.redirect('/my/home')
        rec = self._scoped_record('edu.grievance', gid)
        if not rec.exists():
            return request.redirect('/grievances/approvals')
        return request.render('edu_portal.edu_grievance_detail', {
            'title': '申诉处理详情',
            'page_name': 'grievance_detail',
            'rec': rec,
            'state_label': self._GRIEVANCE_STATE_LABEL.get(
                rec.state, rec.state or '—'),
            'steps': self._grievance_steps(rec.state),
            'date_str': rec.date.strftime('%Y/%m/%d') if rec.date else '—',
        })

    @http.route('/grievances/set_state', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def grievance_set_state(self, **post):
        """A1：申诉门户处理写路由（镜像 /leave/set_state 的写法与守卫）。

        只接受既有状态机的三个值，不引入新状态；驳回须附原因（与后台
        action_reject 语义对齐）；实际流转后经 B5 通知引擎告知申请人。
        """
        fac = current_faculty()
        if not fac and not privileged_staff():
            return request.redirect('/my/home')
        try:
            gid = int(post.get('grievance_id', 0))
            new_state = post.get('state', '')
        except ValueError:
            return request.redirect('/grievances/approvals')
        # t34 F3：单条路由与批量同口径（越权按不存在处理）
        rec = self._scoped_record('edu.grievance', gid)
        if rec.exists() and new_state in ('in_progress', 'resolve', 'reject'):
            was_pending = rec.state in ('submitted', 'in_progress')
            if new_state == 'reject':
                reason = (post.get('reject_reason') or '').strip()[:500]
                if reason:
                    rec.write({'reject_reason': reason})
            rec.write({'state': new_state})
            if was_pending and new_state in ('resolve', 'reject'):
                rec._notify_applicant(new_state)
        # 4a 审计：申诉处理
        request.env['edu.audit.log'].sudo()._log(
            '申诉处理', 'edu.grievance', rec.id, rec.name or '',
            '状态 → %s' % new_state)
        next_url = post.get('next') or ''
        if not next_url.startswith('/grievances/'):
            next_url = '/grievances/approvals'
        return request.redirect(next_url)

    @http.route('/leave/approvals/<int:leave_id>', type='http', auth='user',
                website=True)
    def leave_detail(self, leave_id, **kw):
        # §8.1 准入（S3 放宽，判据见 leave_portal_approver）：
        # 有教师档案 ∪ 教务处/系统组 ∪「本级应批人是我」。
        # 最后一档是 §3.3「没有班主任也能跑 / 老师到位后只填数据即生效」的前提——
        # op.batch.homeroom_teacher_id 存的是 res.users，而本仓 op.faculty 0 个在职行，
        # 班主任完全可能没有教师档案；沿用老门槛会让最主要的使用者连队列都进不去。
        if not leave_portal_approver():
            return request.redirect('/my/home')
        rec = self._scoped_record('edu.leave', leave_id)
        if not rec.exists():
            return request.redirect('/leave/approvals')
        state_label = {
            'request': '已申请（待审批）', 'approved': '已批准',
            'refused': '已拒绝',
            # §3.1：新增第四态必须给中文标签，否则详情页会直接吐出英文 code
            'pending_second': '一级已通过（待二级审批）',
        }.get(rec.state, rec.state or '—')
        # §4.4（S3 → S4 契约）：转交表单要的「当前审批级」与「合法转入人」。
        # transfer_users 用 S2 冻结接口 transfer_candidates(stage)（已过滤自己/申请人）；
        # 接口未就绪 ⇒ 空集 ⇒ S4 的 t-if 让表单隐藏（不 500、更不是「谁都能转」）。
        # 只有**当前这一级的应批人**才看得到转交入口（§4.4：privileged_staff 可批但不可转）。
        leave_stage = leave_stage_of_state(rec.state)
        can_transfer = _leave_can_transfer(rec, request.env.user, leave_stage)
        transfer_users = (leave_transfer_candidates(rec, leave_stage)
                          if can_transfer
                          else request.env['res.users'].sudo().browse())
        return request.render('edu_portal.edu_leave_detail', {
            'title': '请假审批详情',
            'page_name': 'leave_detail',
            'leave': rec,
            'vals': self._leave_detail_vals(rec),
            'state_label': state_label,
            'steps': self._leave_steps(rec.state),
            'leave_stage': leave_stage,
            'transfer_users': transfer_users,
            # §8.1/S4 契约：能否处置 / 能否转交（S4 的按钮守卫可用这两个布尔量；
            # 不给的话，转交出去后的原审批人仍看得见详情页，会看到**按了没用**的
            # 「同意/驳回」按钮 —— 后端的 fail-closed 不变，这里只是把话说在前面）。
            'can_act': _leave_can_act(rec, request.env.user),
            'can_transfer': can_transfer,
        })


    # ------------------------------------------------------------------
    # 教师发布公告（布告栏写操作）
    # ------------------------------------------------------------------
    @http.route('/notice/publish', type='http', auth='user', website=True)
    def notice_publish(self, **kw):
        fac = current_faculty()
        if not fac and not privileged_staff():
            return request.redirect('/my/notice_board/notice')
        env = request.env
        return request.render('edu_portal.edu_notice_publish', {
            'title': '发布公告',
            'page_name': 'notice_publish',
            'templates': env['edu.notice.template'].sudo().search(
                [('active', '=', True)]),
            'audiences': env['edu.notice']._fields['audience'].selection,
            'now': fields.Datetime.now().strftime('%Y-%m-%dT%H:%M'),
            'saved_tpl': kw.get('saved_tpl'),
            'err': kw.get('err'),
        })

    @http.route('/notice/publish_save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def notice_publish_save(self, **post):
        fac = current_faculty()
        if not fac and not privileged_staff():
            return request.redirect('/my/notice_board/notice')
        name = (post.get('name') or '').strip()
        if not name:
            return request.redirect('/notice/publish')
        Notice = request.env['edu.notice'].sudo()
        seq = request.env['ir.sequence'].sudo().search(
            [('code', '=', 'edu.notice')], limit=1)
        code = seq.next_by_code('edu.notice') if seq else ''
        # F4：套用模板（标题前缀 + 正文占位符；表单已填内容优先）
        tpl = None
        tpl_id = str(post.get('template_id') or '')
        if tpl_id.isdigit():
            tpl = request.env['edu.notice.template'].sudo().browse(
                int(tpl_id))
            if not tpl.exists():
                tpl = None
        if tpl and tpl.title_prefix \
                and not name.startswith(tpl.title_prefix):
            name = tpl.title_prefix + name
        content = post.get('content', '')
        if tpl and not (content or '').strip():
            content = tpl.render_content(
                日期=fields.Date.today().strftime('%Y年%m月%d日'))
        audience = post.get('audience') or (tpl.audience if tpl else 'all')
        if audience not in ('all', 'student', 'faculty', 'parent', 'staff'):
            audience = 'all'
        channels = {
            'channel_site': bool(post.get('channel_site')),
            'channel_email': bool(post.get('channel_email')),
            'channel_telegram': bool(post.get('channel_telegram')),
        }
        if not any(channels.values()):
            # 未勾选通道时按模板默认（模板也没配则默认站内信）
            channels = {
                'channel_site': tpl.channel_site if tpl else True,
                'channel_email': tpl.channel_email if tpl else False,
                'channel_telegram': tpl.channel_telegram if tpl else False,
            }
        vals = {
            'name': f'[{code}] {name}' if code else name,
            'content': content,
            'sender': fac.name if fac else request.env.user.name,
            'category': post.get('category') or 'notice',
            'audience': audience,
            'template_id': tpl.id if tpl else False,
            **channels,
        }
        # F4：定时发布（到点由 cron 转发布并推送；未到点前不得出现在列表）
        publish_at = (post.get('publish_at') or '').strip()
        scheduled = False
        if publish_at:
            try:
                dt = fields.Datetime.to_datetime(
                    publish_at.replace('T', ' '))
            except (TypeError, ValueError):
                dt = None
            if dt and dt > fields.Datetime.now():
                vals['publish_at'] = dt
                vals['active'] = False
                scheduled = True
        # 门户横幅开关（可选；后续在「教务审批 → 布告栏管理」调整）
        if post.get('banner_enabled'):
            vals.update({
                'banner_enabled': True,
                'banner_badge': (post.get('banner_badge') or '').strip()[:64],
                'banner_cta': (post.get('banner_cta') or '').strip()[:32]
                              or '查看详情',
            })
        # 4b：有效期（留空长期有效）
        until = (post.get('date_until') or '').strip()
        if until:
            try:
                vals['date_until'] = fields.Date.to_date(until)
            except (TypeError, ValueError):
                pass
        notice = Notice.create(vals)
        # 4b：公告附件（可选多文件，存 ir.attachment）
        files = request.httprequest.files.getlist('attachments')
        for f in files:
            if not f.filename:
                continue
            request.env['ir.attachment'].sudo().create({
                'name': f.filename,
                'datas': base64.b64encode(f.read()),
                'res_model': 'edu.notice',
                'res_id': notice.id,
                'mimetype': f.mimetype or 'application/octet-stream',
            })
        # F4：立即发布 → 按通道推送；定时发布 → 交给 cron（active=False）
        if scheduled:
            detail = '定时发布：%s（人群 %s）' % (vals['publish_at'], audience)
        else:
            try:
                notice._send_channels()
            except Exception:
                # D 组第一批（P3）：写路径上的调试 print() → 日志。
                _logger.info('edu_portal: 公告渠道推送失败 notice=%s', notice.id)
            detail = '立即发布（人群 %s）' % audience
        # 4a 审计：发布公告
        request.env['edu.audit.log'].sudo()._log(
            '发布公告', 'edu.notice', notice.id, notice.name, detail)
        return request.redirect('/my/notice_board/notice')


    # ------------------------------------------------------------------
    # Backoffice：校友工作管理列表
    # ------------------------------------------------------------------
    @http.route('/alumni/job/list', type='http', auth='user', website=True)
    def alumni_job_list(self, **kw):
        jobs = request.env['edu.alumni.job'].sudo().search([])
        stats = {
            'total': len(jobs),
            'recruiting': sum(1 for j in jobs if j.state == 'recruiting'),
            'pending': sum(1 for j in jobs if j.state == 'pending'),
            'closed': sum(1 for j in jobs if j.state == 'closed'),
        }
        return request.render('edu_portal.edu_alumni_job_list', {
            'title': '校友工作',
            'page_name': 'alumni_job_list',
            'jobs': jobs,
            'stats': stats,
        })


    # ------------------------------------------------------------------
    # 应用菜单（对齐原站 /openeducat/apps_menu：原生 home menu 应用网格）
    # ------------------------------------------------------------------
    @http.route('/openeducat/apps_menu', type='http', auth='user', website=True)
    def apps_menu(self, **kw):
        # 以当前用户视角取根菜单：Odoo19 的 search() 不再自动按菜单分组
        # 过滤，必须显式调用 _filter_visible_menus()（配合
        # scripts/seed_teacher_menus.py 的「后台·完整视图」组裁剪非教学应用）
        Menu = request.env['ir.ui.menu']
        roots = Menu.search(
            [('parent_id', '=', False)], order='sequence asc'
        )._filter_visible_menus()
        apps = []
        for m in roots:
            # 有动作或子菜单的才算应用；排除纯技术项
            if not m.web_icon and not m.child_id:
                continue
            apps.append({
                'id': m.id,
                'name': m.name,
                'icon': self._menu_icon_url(m),
                'fa': _APPS_FA_BY_NAME.get(m.name, 'fa-th-large'),
                'color': _APPS_FA_COLOR.get(m.name, '#64748B'),
                'href': self._menu_href(m),
            })
        return request.render('edu_portal.edu_apps_menu', {
            'title': '应用面板',
            'page_name': 'apps_menu',
            'apps': apps,
        })

    @staticmethod
    def _menu_icon_url(menu):
        """web_icon 存的是 '模块,路径' 字符串，转成可直接访问的静态 URL。
        ir.ui.menu 的 web_icon 不是二进制字段，走 /web/image 只会拿到相机占位图。"""
        icon = menu.web_icon or ''
        if ',' in icon:
            module, path = icon.split(',', 1)
            try:
                from odoo.modules.module import get_module_path
                base = get_module_path(module)
                if base and os.path.isfile(os.path.join(base, *path.split('/'))):
                    return '/' + module + '/' + path
            except Exception:
                pass
        elif icon.startswith(('http', '/')):
            return icon
        return ''

    @staticmethod
    def _menu_href(menu):
        """卡片跳转到该应用（或其子孙中）第一个可执行动作的深链；
        整棵子树都没有动作时退回门户应用面板 /apps（v3：不再暴露 /web#）。

        ⚠ 动作类型判定走 ir.ui.menu.edu_action_href（定义在 edu_brand，全仓唯一口径）：
        ir.actions.act_url **本身就是一个「跳到某个 URL」的动作**，而 act_url 的机制是
        「先把后台 webclient 起起来，再由 JS 执行 window.location = url」——
        所以只要门户卡片把它写成后台深链 /odoo/action-<id>，用户就必然**先整屏闪一遍
        Odoo 后台外壳**（蓝顶栏 + 空白 + 「正在加载」）才落到门户页（用户实测缺陷）。
        例：menu 608「资料下载」-> act_url 755 url=/downloads ⇒ 卡片 href 直接给 /downloads。
        其余动作类型（act_window 等）保持 /odoo/action-<id> —— 它们本来就是后台界面。"""
        stack, seen = [menu], set()
        while stack:
            cur = stack.pop(0)
            if cur.id in seen:
                continue
            seen.add(cur.id)
            if cur.action:
                return request.env['ir.ui.menu'].edu_action_href(
                    '%s,%d' % (cur.action._name, cur.action.id))
            stack.extend(cur.child_id)
        return '/apps'


    @http.route('/alerts/mark_read', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def alerts_mark_read(self, **post):
        env = request.env
        AlertRead = env['edu.alert.read'].sudo()
        # 当前待办总数：复用 _home_categories 的提醒组
        from odoo.addons.edu_portal.controllers.batch2 import _home_categories
        from odoo.addons.edu_portal.controllers.main import current_student
        cats = _home_categories(current_student())
        alert = next((x for x in cats if x['key'] == 'portal_alert_category'), None)
        total = alert['total'] if alert else 0
        rec = AlertRead.search([('user_id', '=', request.env.uid)], limit=1)
        vals = {'last_total': total, 'last_read': fields.Datetime.now()}
        if rec:
            rec.write(vals)
        else:
            AlertRead.create({'user_id': request.env.uid, **vals})
        return request.redirect('/my/home')


    # ------------------------------------------------------------------
    # 4a 操作审计查询页（教务处/管理员）
    # ------------------------------------------------------------------
    @http.route('/edu/audit', type='http', auth='user', website=True)
    def edu_audit(self, **kw):
        if not privileged_staff():
            return request.redirect('/my/home')
        Audit = request.env['edu.audit.log'].sudo()
        filterby = kw.get('filterby') or 'all'
        search = (kw.get('search') or '').strip()
        page = max(1, int(kw.get('page', 1) or 1))
        domain = []
        if filterby and filterby != 'all':
            domain.append(('action', '=', filterby))
        if search:
            domain += ['|', '|',
                       ('res_name', 'ilike', search),
                       ('detail', 'ilike', search),
                       ('user_id.name', 'ilike', search)]
        total = Audit.search_count(domain)
        PAGE_SIZE = 30
        rows = Audit.search(domain, limit=PAGE_SIZE,
                            offset=(page - 1) * PAGE_SIZE)
        action_counts = {row[0]: row[1] for row in Audit._read_group(
            [], ['action'], ['__count'])}
        chips = sorted(action_counts.items(), key=lambda kv: -kv[1])[:6]
        fmt = request.env['ir.fields'].sudo() if False else None
        items = [{
            'log': r,
            'user': _audit_user_label(r.user_id),
            'model_label': _audit_model_label(request.env, r.model),
            'when': fields.Datetime.context_timestamp(
                r, r.create_date).strftime('%Y-%m-%d %H:%M')
            if r.create_date else '',
        } for r in rows]
        return request.render('edu_portal.edu_audit', {
            'title': '操作审计',
            'page_name': 'edu_audit',
            'items': items,
            'filterby': filterby,
            'search': search,
            'chips': chips,
            'total_all': sum(action_counts.values()),
            'pager': pager('/edu/audit', total=total, page=page,
                           step=PAGE_SIZE,
                           url_args={'filterby': filterby,
                                     'search': search}),
        })


    # ------------------------------------------------------------------
    # 4c 教师作业管理（发布后编辑 / 撤回 / 提交名单）
    # ------------------------------------------------------------------
    _ASG_STATE_LABEL = {'draft': '草稿', 'publish': '已发布',
                        'finish': '已结束', 'cancel': '已撤销'}
    _SUB_STATE_LABEL = {'draft': '未提交', 'submit': '已提交',
                        'accept': '已通过', 'reject': '已驳回',
                        'change': '需修改'}

    def _teacher_assignment(self, aid):
        """取归属当前教师的作业（越权按不存在处理）。"""
        fac = current_faculty()
        rec = request.env['op.assignment'].sudo().browse(aid)
        if not fac or not rec.exists() \
                or rec.grading_assignment_id.faculty_id.id != fac.id:
            return None
        return rec

    @http.route('/assignment/manage', type='http', auth='user', website=True)
    def assignment_manage(self, **kw):
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        Assign = request.env['op.assignment'].sudo()
        filterby = kw.get('filterby') or 'publish'
        domain = [('grading_assignment_id.faculty_id', '=', fac.id)]
        if filterby in ('publish', 'draft', 'finish', 'cancel'):
            domain.append(('state', '=', filterby))
        recs = Assign.search(domain, order='id desc')
        counts = {row[0]: row[1] for row in Assign._read_group(
            [('grading_assignment_id.faculty_id', '=', fac.id)],
            ['state'], ['__count'])}
        items = []
        for a in recs:
            items.append({
                'a': a,
                'name': a.grading_assignment_id.name or '',
                'batch': a.batch_id.name or '',
                'subject': a.grading_assignment_id.subject_id.name or '',
                'state_label': self._ASG_STATE_LABEL.get(a.state, a.state),
                'due': fields.Datetime.context_timestamp(
                    a, a.submission_date).strftime('%m-%d %H:%M')
                if a.submission_date else '—',
                'sub_n': len(a.assignment_sub_line),
            })
        return request.render('edu_portal.edu_assignment_manage', {
            'title': '作业管理',
            'page_name': 'assignment_manage',
            'items': items,
            'filterby': filterby,
            'counts': {
                'publish': counts.get('publish', 0),
                'finish': counts.get('finish', 0),
                'cancel': counts.get('cancel', 0),
                'all': sum(counts.values()),
            },
        })

    @http.route('/assignment/edit/<int:aid>', type='http', auth='user',
                website=True)
    def assignment_edit(self, aid, **kw):
        rec = self._teacher_assignment(aid)
        if not rec:
            return request.redirect('/assignment/manage')
        return request.render('edu_portal.edu_assignment_edit', {
            'title': '编辑作业',
            'page_name': 'assignment_edit',
            'rec': rec,
            'name': rec.grading_assignment_id.name or '',
            'description': rec.description or '',
            'marks': rec.marks,
            'due': fields.Datetime.context_timestamp(
                rec, rec.submission_date).strftime('%Y-%m-%dT%H:%M')
            if rec.submission_date else '',
            'error': kw.get('error') or '',
        })

    @http.route('/assignment/edit/<int:aid>/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def assignment_edit_save(self, aid, **post):
        rec = self._teacher_assignment(aid)
        if not rec:
            return request.redirect('/assignment/manage')
        name = (post.get('name') or '').strip()
        if not name:
            return request.redirect('/assignment/edit/%d?error=name' % aid)
        def _norm_dt(val):
            val = (val or '').strip().replace('T', ' ')
            if len(val) == 16:
                val += ':00'
            return val
        vals = {
            'description': post.get('description') or '',
            'marks': float(post.get('marks', 0) or 0),
            'submission_date': _norm_dt(post.get('submission_date')),
        }
        rec.write(vals)
        rec.grading_assignment_id.write({'name': name})
        # 4a 审计：作业编辑
        request.env['edu.audit.log'].sudo()._log(
            '作业编辑', 'op.assignment', rec.id, name, '')
        return request.redirect('/assignment/manage?saved=1')

    @http.route('/assignment/set_state', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def assignment_set_state(self, **post):
        try:
            aid = int(post.get('aid', 0))
        except ValueError:
            return request.redirect('/assignment/manage')
        rec = self._teacher_assignment(aid)
        new_state = post.get('state', '')
        if rec and new_state in ('publish', 'finish', 'cancel'):
            rec.write({'state': new_state})
            # 4a 审计：作业状态
            request.env['edu.audit.log'].sudo()._log(
                '作业状态', 'op.assignment', rec.id,
                rec.grading_assignment_id.name or '',
                '状态 → %s' % self._ASG_STATE_LABEL.get(new_state, new_state))
        return request.redirect('/assignment/manage')

    @http.route('/assignment/submission/<int:sid>/grade', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def assignment_submission_grade(self, sid, **post):
        """教师给**自己那门作业**下某个学生的提交打分。

        2026-10-04（第 70 轮）：上一步补了「看得到交了什么」，接着发现**打不了分** ——
        全仓除了 edu_telegram 的合成演示代码，**没有任何地方写 `op.assignment.sub.line.marks`**，
        而提交名单页一直显示「得分 0.0」⇒ 这个字段**永远不会有值**，闭环到此断掉。

        归属判定同 `_teacher_assignment()`（按 faculty_id，越权按不存在处理）；
        分值夹在 [0, 作业分值] 内，非数字一律拒绝（不静默当 0）。
        """
        sub = request.env['op.assignment.sub.line'].sudo().browse(sid)
        rec = (self._teacher_assignment(sub.assignment_id.id)
               if sub.exists() and sub.assignment_id else None)
        if not rec:
            return request.redirect('/assignment/manage')
        # 名单口径**与提交名单页完全一致**（roles.py 的 assignment_submissions 同款）：
        # 优先用作业自己的 allocation_ids，没有就退回「本班学生」。不另立第二套口径。
        roster = rec.allocation_ids or request.env['op.student.course'] \
            .sudo().search([('batch_id', '=', rec.batch_id.id)]).mapped('student_id')
        if sub.student_id.id not in roster.ids:
            return request.redirect('/assignment/manage')
        raw = (post.get('marks') or '').strip()
        try:
            val = float(raw)
        except ValueError:
            return request.redirect('/assignment/submissions/%d?bad=1' % rec.id)
        top = float(rec.marks or 0) or 100.0
        val = max(0.0, min(val, top))
        # 2026-10-04（第 71 轮）：**必须连状态一起写**。
        #   第 70 轮我只写了 marks，结果教师打完 88 分，学生那一页仍然显示
        #   「状态 已提交·待批阅 ／ 得分 待批阅」—— 因为学生页的判据是
        #   `views/batch1.xml:559`：`(sub.marks if sub.marks else '-') if sub.state == 'accept' else '待批阅'`
        #   ⇒ 状态不动，分数就永远不显示（而 models/assignment.py:6 的批改提醒是按
        #   state/marks 变更触发的，于是会出现「收到了站内信、页面却还写着待批阅」的错位）。
        #   `accept` = 学生侧「已批阅」／教师侧「已通过」（两侧标签见各自的 _STATE_LABEL 字典）。
        # 2026-10-04（第 72 轮）：**把状态机剩下的两档也接上**。
        #   第 70/71 轮只做了「通过并打分」⇒ 教师**只能通过**，拿不到 `reject`/`change` 两个状态，
        #   而学生页（batch1.xml 的 SUB_STATE_LABEL）本来就渲染「已退回」「需修改」，
        #   教师页 `_SUB_STATE_LABEL` 也早有这两档 ⇒ **状态是设计好的，只是没有入口**。
        action = (post.get('action') or 'accept').strip()
        if action not in ('accept', 'reject', 'change'):
            action = 'accept'
        sub.write({'marks': val, 'state': action})
        return request.redirect('/assignment/submissions/%d?graded=1' % rec.id)

    @http.route('/assignment/submission/<int:sid>/file', type='http',
                auth='user', website=True)
    def assignment_submission_file(self, sid, **kw):
        """教师下载/预览**自己那门作业**下某个学生提交的附件。

        2026-10-04（第 69 轮，闭环复核发现）：全站原本**只有学生侧**的
        `/my/assignment/sub/<sid>/file`（batch1.py:831）⇒ 教师看得到「谁交了」，
        **看不到交了什么**：提交名单页只有 学生/学号/状态/提交时间/得分 五列，
        没有任何内容入口（实测把该页所有链接抓了一遍，只有三个导航链接）。

        本路由的「谁能看」直接复用既有的 `_teacher_assignment()`（按 faculty_id 判归属，
        **越权按不存在处理**）—— 不新开一套权限口径；预览/下载的写法与学生侧保持一致。
        """
        from odoo.http import content_disposition
        from .downloads import _INLINE_TYPES
        sub = request.env['op.assignment.sub.line'].sudo().browse(sid)
        rec = (self._teacher_assignment(sub.assignment_id.id)
               if sub.exists() and sub.assignment_id else None)
        if not rec or not sub.file:
            return request.redirect('/assignment/manage')
        fname = sub.filename or 'homework.bin'
        content = base64.b64decode(sub.file)
        if kw.get('inline') == '1':
            ctype = _INLINE_TYPES.get(
                (fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''))
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
                   ('Content-Disposition', content_disposition(fname)),
                   ('Content-Length', str(len(content)))]
        return request.make_response(content, headers=headers)

    @http.route('/assignment/submissions/<int:aid>', type='http',
                auth='user', website=True)
    def assignment_submissions(self, aid, **kw):
        rec = self._teacher_assignment(aid)
        if not rec:
            return request.redirect('/assignment/manage')
        submitted = {s.student_id.id: s for s in rec.assignment_sub_line}
        roster = rec.allocation_ids or request.env['op.student.course'] \
            .sudo().search([('batch_id', '=', rec.batch_id.id)]) \
            .mapped('student_id')
        rows = []
        done_n = 0
        for stu in roster.sorted(key=lambda x: x.name or ''):
            sub = submitted.get(stu.id)
            if sub:
                done_n += 1
            rows.append({
                'name': stu.name or '',
                'roll': stu.gr_no or '',
                'sub': sub,
                'state_label': self._SUB_STATE_LABEL.get(
                    sub.state if sub else 'draft', '未提交'),
                'when': fields.Datetime.context_timestamp(
                    sub, sub.submission_date).strftime('%m-%d %H:%M')
                if sub and sub.submission_date else '',
            })
        return request.render('edu_portal.edu_assignment_submissions', {
            'title': '提交名单',
            'page_name': 'assignment_submissions',
            'rec': rec,
            'name': rec.grading_assignment_id.name or '',
            'rows': rows,
            'done_n': done_n,
            'total_n': len(rows),
            'done_pct': int(round(done_n * 100.0 / len(rows))) if rows else 0,
        })


    # ------------------------------------------------------------------
    # 第 5 批 F：学生名单 CSV 两段式导入（教务处/管理员；仅建档案不开账号）
    # ------------------------------------------------------------------
    _IMPORT_GENDER = {'男': 'm', '女': 'f', 'm': 'm', 'f': 'f',
                      'male': 'm', 'female': 'f'}

    @http.route('/edu/import/students', type='http', auth='user',
                website=True)
    def edu_import_students(self, **kw):
        if not privileged_staff():
            return request.redirect('/my/home')
        return request.render('edu_portal.edu_import_students', {
            'title': '导入学生名单',
            'page_name': 'import_students',
            'preview_rows': None,
            'done': kw.get('done'),
            'skip': kw.get('skip'),
        })

    @http.route('/edu/import/students/preview', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def edu_import_students_preview(self, **post):
        """第一段：解析 CSV → 校验 → 预览（合法行以 JSON 随确认表单带回）。"""
        import csv as _csv
        import io as _io
        import json as _json

        if not privileged_staff():
            return request.redirect('/my/home')
        f = request.httprequest.files.get('file')
        if not f or not f.filename:
            return request.redirect('/edu/import/students')
        try:
            text = f.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            text = f.read().decode('gbk', errors='replace')
        reader = _csv.reader(_io.StringIO(text))
        rows = [r for r in reader if any((c or '').strip() for c in r)]
        if not rows:
            return request.redirect('/edu/import/students')
        header = [h.strip() for h in rows[0]]
        # 列名映射（顺序无关；找不到则按默认顺序）
        def _col(name):
            return header.index(name) if name in header else None
        i_name = _col('姓名')
        i_no = _col('学号')
        i_gender = _col('性别')
        i_birth = _col('出生日期')
        i_email = _col('邮箱')
        i_phone = _col('手机')
        if i_name is None:            # 无表头时按默认顺序
            i_name, i_no, i_gender, i_birth, i_email, i_phone = \
                0, 1, 2, 3, 4, 5
        Student = request.env['op.student'].sudo()
        seen_no = set()
        valid, invalid = [], []
        for n, r in enumerate(rows[1:], start=2):
            def _g(i):
                return (r[i].strip() if i is not None and i < len(r)
                        else '')
            name = _g(i_name)
            no = _g(i_no)
            errors = []
            if not name:
                errors.append('缺姓名')
            if not no:
                errors.append('缺学号')
            elif Student.search_count([('gr_no', '=', no)]):
                errors.append('学号已存在')
            elif no in seen_no:
                errors.append('文件内学号重复')
            seen_no.add(no)
            gender = self._IMPORT_GENDER.get(_g(i_gender).lower(), '')
            if _g(i_gender) and not gender:
                errors.append('性别应为 男/女')
            birth = _g(i_birth)
            if birth:
                try:
                    fields.Date.to_date(birth)
                except (TypeError, ValueError):
                    errors.append('出生日期格式应为 YYYY-MM-DD')
            rec = {'name': name, 'gr_no': no,
                   'gender': gender or '',
                   'birth': birth, 'email': _g(i_email),
                   'phone': _g(i_phone)}
            if errors:
                invalid.append({'row': n, 'rec': rec,
                                'errors': '；'.join(errors)})
            else:
                valid.append({'row': n, 'rec': rec})
        return request.render('edu_portal.edu_import_students', {
            'title': '导入学生名单',
            'page_name': 'import_students',
            'preview_rows': {'valid': valid, 'invalid': invalid},
            'confirm_json': _json.dumps(valid, ensure_ascii=False),
            'done': None,
            'skip': None,
        })

    @http.route('/edu/import/students/commit', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def edu_import_students_commit(self, **post):
        """第二段：确认写入（仅创建档案与联系人，不开登录账号）。"""
        import json as _json

        if not privileged_staff():
            return request.redirect('/my/home')
        try:
            items = _json.loads(post.get('payload') or '[]')
        except ValueError:
            items = []
        if not isinstance(items, list):
            items = []
        Partner = request.env['res.partner'].sudo()
        Student = request.env['op.student'].sudo()
        done = skip = 0
        errors = []
        for it in items:
            rec = (it or {}).get('rec') or {}
            name = rec.get('name') or ''
            no = rec.get('gr_no') or ''
            if not name or not no \
                    or Student.search_count([('gr_no', '=', no)]):
                skip += 1
                continue
            try:
                vals = {'name': name}
                if rec.get('email'):
                    vals['email'] = rec['email']
                if rec.get('phone'):
                    vals['phone'] = rec['phone']
                partner = Partner.create(vals)
                svals = {
                    'partner_id': partner.id,
                    'first_name': name,
                    'last_name': name,
                    'gr_no': no,
                }
                if rec.get('gender') in ('m', 'f'):
                    svals['gender'] = rec['gender']
                if rec.get('birth'):
                    svals['birth_date'] = rec['birth']
                Student.create(svals)
                done += 1
            except Exception as e:
                skip += 1
                errors.append('%s：%s' % (name or no,
                                          str(e).replace('\n', ' ')[:80]))
        # 4a 审计：学生导入
        request.env['edu.audit.log'].sudo()._log(
            '学生导入', 'op.student', 0, '',
            '新建 %d 人 · 跳过 %d 人%s' % (
                done, skip,
                ('；' + '；'.join(errors[:5])) if errors else ''))
        return request.redirect(
            '/edu/import/students?done=%d&skip=%d' % (done, skip))

    # ==================================================================
    # t7 重复劳动自动化新增路由
    # 设计依据：docs/research/onestop-learning-and-repetitive-work.md
    # （批量审批/代理审批/超时升级、成绩留痕、公告模板与定时、考勤补录）
    # ==================================================================

    @staticmethod
    def _posted_ids(post, key='ids'):
        """取多选 id：支持同名多值、逗号分隔两种提交方式。"""
        raw = request.httprequest.form.getlist(key)
        if not raw and post.get(key):
            raw = [post.get(key)]
        ids = []
        for chunk in raw:
            for part in str(chunk).split(','):
                part = part.strip()
                if part.isdigit():
                    ids.append(int(part))
        return sorted(set(ids))

    @staticmethod
    def _bulk_loop(records, apply_fn):
        """逐条 savepoint 批量流转：单条失败不影响其它条（隔离设计）。"""
        ok, failures = 0, []
        for rec in records:
            try:
                with request.env.cr.savepoint():
                    if apply_fn(rec):
                        ok += 1
            except Exception as exc:
                failures.append({
                    'name': rec.name or ('#%d' % rec.id),
                    'error': str(exc).replace('\n', ' ')[:120],
                })
        return ok, failures

    @staticmethod
    def _bulk_url(base, ok, failures, skipped=0, ignored=0):
        """批量结果回跳：成功/失败/跳过/忽略 计数 + 首条失败原因。

        `ignored` = len(set(ids)) - len(scoped)，即**被作用域丢弃的 id**（越权 + 不存在）
        的**聚合数**。刻意只给总数、**不拆原因** —— 拆开就会泄露该 id 是否存在/
        是否属于你（不泄露存在性，t67 收窄契约第 2 条）。
        """
        url = '%s?bulk_ok=%d&bulk_fail=%d&bulk_skip=%d&bulk_ignored=%d' % (
            base, ok, len(failures), skipped, ignored)
        msgs = []
        if failures:
            msgs.append('%s：%s' % (failures[0]['name'], failures[0]['error']))
        if ignored:
            msgs.append('另有 %d 行不在你的处理范围内或已不存在，已跳过' % ignored)
        if msgs:
            url += '&bulk_msg=%s' % quote('；'.join(msgs)[:200])
        return url

    # ------------------------------------------------------------------
    # F1：批量审批（请假 / 申诉）
    # ------------------------------------------------------------------
    @http.route('/leave/set_state_bulk', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def leave_set_state_bulk(self, **post):
        """请假批量通过/驳回。

        语义对齐飞书「只对符合条件的待处理任务批量同意或拒绝」：只处理
        state=request 的单，非待处理计入「跳过」；逐条 savepoint 独立成败。
        """
        # §8.1 准入（S3 放宽，判据见 leave_portal_approver）：有教师档案 ∪
        # 教务处/系统组 ∪「本级应批人是我」——理由与 leave_approvals 同。
        if not leave_portal_approver():
            return request.redirect('/my/home')
        new_state = post.get('state', '')
        if new_state not in ('approved', 'refused'):
            return request.redirect('/leave/approvals')
        reason = (post.get('reject_reason') or '').strip()[:500]
        if new_state == 'refused' and not reason:
            return request.redirect(
                '/leave/approvals?bulk_msg=%s'
                % quote('批量驳回需先填写驳回原因'))
        # t34 F3：批量先按作用域过滤 id（越权 id 等同不存在，只计入跳过）
        posted = self._posted_ids(post)
        # 2026-09-14 修（用户反馈）：未勾选任何一行就点「批量通过/驳回」时，原实现会回
        # ?bulk_ok=0&bulk_fail=0&bulk_skip=0 ⇒ 页面弹**绿色**"批量完成：成功 0 条…"，
        # 既没做事、又像在宣告成功。现在改为明确提示，不写审计、不回成功横幅。
        if not posted:
            return request.redirect(
                '/leave/approvals?bulk_msg=%s'
                % quote('请先勾选要处理的申请（可点表头「全选本页」）'))
        pending = self._scoped_records(
            'edu.leave', posted, [('state', '=', 'request')])
        records = self._scoped_records('edu.leave', posted)
        # §4.3(2)/§8.1（S3）：可处置 = 本级应批人本人（或 privileged_staff），
        # 与单条路由**同判据** —— 否则「转交出去的单被原审批人批量批掉」会绕过
        # §4.3(2)（批量只处理 state=request，故这里恒是一级）。
        actionable = pending.filtered(
            lambda r: _leave_can_act(r, request.env.user))

        def _apply(rec):
            # 课代表需求⑥ + §3.1：批量与单条**必须同一套分级动作** ——
            # 否则「4 天的单批量通过 = 直接终审」会绕过 pending_second（静默走样）。
            # was_pending=True：批量集合已按 state='request' 过滤。
            _leave_flow_apply_state(rec, new_state, reason, was_pending=True)
            return True

        ok, failures = self._bulk_loop(actionable, _apply)
        skipped = len(records) - len(actionable)
        # t67：被作用域丢弃的 id（越权 + 不存在）聚合计数；只给总数、不拆原因
        ignored = max(0, len(set(posted)) - len(records))
        request.env['edu.audit.log'].sudo()._log(
            '请假批量审批', 'edu.leave', 0, '',
            '批量%s：成功 %d / 失败 %d / 跳过 %d / 忽略 %d' % (
                '通过' if new_state == 'approved' else '驳回',
                ok, len(failures), skipped, ignored))
        return request.redirect(
            self._bulk_url('/leave/approvals', ok, failures, skipped, ignored))

    @http.route('/grievances/set_state_bulk', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def grievance_set_state_bulk(self, **post):
        """申诉批量解决/驳回（只处理 submitted / in_progress 的单）。"""
        fac = current_faculty()
        if not fac and not privileged_staff():
            return request.redirect('/my/home')
        new_state = post.get('state', '')
        if new_state not in ('resolve', 'reject'):
            return request.redirect('/grievances/approvals')
        reason = (post.get('reject_reason') or '').strip()[:500]
        if new_state == 'reject' and not reason:
            return request.redirect(
                '/grievances/approvals?bulk_msg=%s'
                % quote('批量驳回需先填写驳回原因'))
        # t34 F3：批量先按作用域过滤 id（越权 id 等同不存在，只计入跳过）
        posted = self._posted_ids(post)
        # 同 leave：未勾选任何一行时给明确提示，别回"成功 0/0/0"的绿色横幅
        if not posted:
            return request.redirect(
                '/grievances/approvals?bulk_msg=%s'
                % quote('请先勾选要处理的申诉（可点表头「全选本页」）'))
        pending = self._scoped_records(
            'edu.grievance', posted,
            [('state', 'in', ('submitted', 'in_progress'))])
        records = self._scoped_records('edu.grievance', posted)

        def _apply(rec):
            if new_state == 'reject':
                rec.write({'reject_reason': reason})
            rec.write({'state': new_state})
            rec._notify_applicant(new_state)
            return True

        ok, failures = self._bulk_loop(pending, _apply)
        skipped = len(records) - len(pending)
        # t67：被作用域丢弃的 id（越权 + 不存在）聚合计数；只给总数、不拆原因
        # （2026-09-17 修：这一行原先被粘到了「请假」处理器里成了重复行，
        #   而本函数只使用未定义 ⇒ 申诉批量路由每次调用 NameError → HTTP 500。
        #   冒烟 tests/smoke/subject_bulk_scope.py 抓到。）
        ignored = max(0, len(set(posted)) - len(records))
        request.env['edu.audit.log'].sudo()._log(
            '申诉批量处理', 'edu.grievance', 0, '',
            '批量%s：成功 %d / 失败 %d / 跳过 %d / 忽略 %d' % (
                '解决' if new_state == 'resolve' else '驳回',
                ok, len(failures), skipped, ignored))
        return request.redirect(
            self._bulk_url('/grievances/approvals', ok, failures, skipped, ignored))

    # ------------------------------------------------------------------
    # F1：代理审批设置（钉钉「代理设置」三要素：被代理人/代理人/时间）
    # ------------------------------------------------------------------
    @http.route('/approvals/delegate', type='http', auth='user',
                website=True)
    def approval_delegate(self, **kw):
        fac = current_faculty()
        if not fac and not privileged_staff():
            return request.redirect('/my/home')
        env = request.env
        Delegate = env['edu.approval.delegate'].sudo()
        return request.render('edu_portal.edu_approval_delegate', {
            'title': '代理审批设置',
            'page_name': 'approval_delegate',
            'mine': Delegate.search(
                [('delegator_id', '=', env.uid)], order='date_from desc'),
            'granted': Delegate.search(
                [('delegate_id', '=', env.uid)], order='date_from desc'),
            'users': env['res.users'].sudo().search(
                [('active', '=', True)], order='name'),
            'today': fields.Date.today().isoformat(),
            'saved': kw.get('saved'),
            'err': kw.get('err'),
        })

    @http.route('/approvals/delegate/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def approval_delegate_save(self, **post):
        """新增一条代理设置：我（被代理人）授权某人（代理人）在期内代批。"""
        fac = current_faculty()
        if not fac and not privileged_staff():
            return request.redirect('/my/home')
        env = request.env
        try:
            delegate_id = int(post.get('delegate_id', 0))
        except (TypeError, ValueError):
            delegate_id = 0
        date_from = (post.get('date_from') or '').strip()
        date_to = (post.get('date_to') or '').strip()
        if not delegate_id or delegate_id == env.uid:
            return request.redirect('/approvals/delegate?err=who')
        try:
            d_from = fields.Date.to_date(date_from) if date_from \
                else fields.Date.today()
            d_to = fields.Date.to_date(date_to)
        except (TypeError, ValueError):
            return request.redirect('/approvals/delegate?err=date')
        if d_to < d_from:
            return request.redirect('/approvals/delegate?err=date')
        env['edu.approval.delegate'].sudo().create({
            'delegator_id': env.uid,
            'delegate_id': delegate_id,
            'date_from': d_from,
            'date_to': d_to,
            'note': (post.get('note') or '').strip()[:128],
        })
        env['edu.audit.log'].sudo()._log(
            '代理审批设置', 'edu.approval.delegate', 0, '',
            '授权 %s 在 %s ~ %s 代批' % (delegate_id, d_from, d_to))
        return request.redirect('/approvals/delegate?saved=1')

    @http.route('/approvals/delegate/cancel', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def approval_delegate_cancel(self, **post):
        """撤销代理（被代理人本人或教务处/管理员可撤）。"""
        fac = current_faculty()
        if not fac and not privileged_staff():
            return request.redirect('/my/home')
        env = request.env
        try:
            did = int(post.get('delegate_id', 0))
        except (TypeError, ValueError):
            did = 0
        rec = env['edu.approval.delegate'].sudo().browse(did)
        if rec.exists() and (rec.delegator_id.id == env.uid
                             or privileged_staff()):
            rec.write({'active': False})
            env['edu.audit.log'].sudo()._log(
                '代理审批撤销', 'edu.approval.delegate', rec.id, '',
                '撤销 %s 代 %s 审批' % (
                    rec.delegate_id.name or '', rec.delegator_id.name or ''))
        return request.redirect('/approvals/delegate')

    # ------------------------------------------------------------------
    # F3：成绩导出 / 导入 / 上期复制 / 变更留痕
    # ------------------------------------------------------------------
    @http.route('/grading/export', type='http', auth='user', website=True)
    def grading_export(self, **kw):
        """导出某场考试成绩（CSV；带 BOM 便于 Excel 直接打开）。"""
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        # t34 F2：导出同样收敛到本人任教范围
        exam = self._teacher_exam(kw.get('exam_id'))
        if not exam:
            return request.redirect('/grading/entry')
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['学号', '姓名', '得分', '状态', '满分', '及格线',
                         '考试'])
        for att in request.env['op.exam.attendees'].sudo().search(
                [('exam_id', '=', exam.id)], order='id'):
            writer.writerow([
                att.student_id.gr_no or '',
                att.student_id.name or '',
                '' if att.marks in (False, None) else att.marks,
                '出席' if att.status == 'present' else '缺考',
                exam.total_marks or '',
                exam.min_marks or '',
                exam.name or '',
            ])
        data = '\ufeff' + buf.getvalue()
        return request.make_response(data, headers=[
            ('Content-Type', 'text/csv; charset=utf-8'),
            ('Content-Disposition',
             'attachment; filename="grades-exam-%d.csv"' % exam.id)])

    @http.route('/grading/import', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def grading_import(self, **post):
        """成绩导入第一段：解析 CSV/XLSX（学号或姓名 + 得分）→ 预览。

        先例：本仓 /edu/import/students 两段式 + 学邦「下载标准模板→填写→
        上传」流程（docs/research §4.3）。
        """
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        env = request.env
        # t34 F2：导入预览同样收敛到本人任教范围
        exam = self._teacher_exam(post.get('exam_id'))
        if not exam:
            return request.redirect('/grading/entry')
        upfile = request.httprequest.files.get('file')
        header, rows = _read_table_file(upfile)
        i_no = _col_index(header, '学号', '学籍号')
        i_name = _col_index(header, '姓名', '学生')
        i_marks = _col_index(header, '得分', '分数', '成绩', 'marks')
        if i_marks is None and header:
            i_marks = len(header) - 1      # 末列兜底
        atts = env['op.exam.attendees'].sudo().search(
            [('exam_id', '=', exam.id)])
        by_no = {a.student_id.gr_no: a
                 for a in atts if a.student_id.gr_no}
        by_name = {}
        for a in atts:
            by_name.setdefault((a.student_id.name or '').strip(), a)
        valid, invalid = [], []
        for n, row in enumerate(rows, start=2):
            no, name = _cell(row, i_no), _cell(row, i_name)
            raw_marks = _cell(row, i_marks)
            att = by_no.get(no) if no else None
            if att is None and name:
                att = by_name.get(name)
            errors = []
            if not (no or name):
                errors.append('缺学号与姓名')
            if att is None:
                errors.append('本场考试无此考生')
            try:
                marks = int(float(raw_marks))
            except (TypeError, ValueError):
                marks = None
                errors.append('得分不是数字')
            if marks is not None and marks < 0:
                errors.append('得分不能为负')
            if marks is not None and exam.total_marks \
                    and marks > exam.total_marks:
                errors.append('得分超过满分 %d' % exam.total_marks)
            item = {
                'row': n, 'no': no, 'name': name,
                'att_id': att.id if att else 0,
                'marks': '' if marks is None else marks,
                'old': '' if not att or att.marks in (False, None)
                       else att.marks,
            }
            if errors:
                item['errors'] = '；'.join(errors)
                invalid.append(item)
            else:
                valid.append(item)
        return request.render('edu_portal.edu_grading_import', {
            'title': '成绩导入',
            'page_name': 'grading_import',
            'exam': exam,
            'preview': {'valid': valid, 'invalid': invalid},
            'confirm_json': json.dumps(valid, ensure_ascii=False),
            'filename': (upfile.filename if upfile else '') or '',
        })

    @http.route('/grading/import/commit', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def grading_import_commit(self, **post):
        """成绩导入第二段：确认写入（逐条 savepoint + 留痕 source=import）。"""
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        env = request.env
        try:
            exam_id = int(post.get('exam_id', 0))
            items = json.loads(post.get('payload') or '[]')
        except (TypeError, ValueError):
            exam_id, items = 0, []
        # t34 F2：批量写入前先判归属（越权按不存在处理）
        exam = self._teacher_exam(exam_id)
        if not (exam and isinstance(items, list)):
            return request.redirect('/grading/entry')
        Hist = env['edu.grade.history'].sudo()
        Attendees = env['op.exam.attendees'].sudo()
        done = skipped = 0
        for it in items:
            att = Attendees.browse(int((it or {}).get('att_id') or 0))
            marks = (it or {}).get('marks')
            if not att.exists() or att.exam_id.id != exam.id or marks == '':
                skipped += 1
                continue
            try:
                with env.cr.savepoint():
                    if Hist.edu_apply_marks(
                            att, marks=int(marks), source='import',
                            note='文件导入'):
                        done += 1
                    else:
                        skipped += 1
            except Exception:
                skipped += 1
        env['edu.audit.log'].sudo()._log(
            '成绩导入', 'op.exam', exam.id, exam.name or '',
            '导入 %d 条 / 跳过 %d 条' % (done, skipped))
        return request.redirect(
            '/grading/entry?exam_id=%d&imported=%d&skipped=%d'
            % (exam.id, done, skipped))

    @http.route('/grading/copy_prev', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def grading_copy_prev(self, **post):
        """把同科目上一场考试的分数复制到本场（只填空缺，不覆盖已录）。"""
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        env = request.env
        try:
            exam_id = int(post.get('exam_id', 0))
        except (TypeError, ValueError):
            exam_id = 0
        # t34 F2：上期复制同样收敛到本人任教范围
        exam = self._teacher_exam(exam_id)
        if not exam:
            return request.redirect('/grading/entry')
        prev = env['op.exam'].sudo().search([
            ('subject_id', '=', exam.subject_id.id),
            ('id', '!=', exam.id),
            ('start_time', '<', exam.start_time)],
            order='start_time desc', limit=1)
        if not prev:
            return request.redirect(
                '/grading/entry?exam_id=%d&copied=0&skipped=0' % exam.id)
        Attendees = env['op.exam.attendees'].sudo()
        prev_by_student = {
            a.student_id.id: a
            for a in Attendees.search([('exam_id', '=', prev.id)])}
        Hist = env['edu.grade.history'].sudo()
        done = skipped = 0
        for att in Attendees.search([('exam_id', '=', exam.id)]):
            if att.marks not in (False, None):
                skipped += 1
                continue
            src = prev_by_student.get(att.student_id.id)
            if not src or src.marks in (False, None):
                skipped += 1
                continue
            try:
                with env.cr.savepoint():
                    if Hist.edu_apply_marks(
                            att, marks=src.marks, source='copy',
                            note='复制自 %s' % (prev.name or prev.id)):
                        done += 1
                    else:
                        skipped += 1
            except Exception:
                skipped += 1
        env['edu.audit.log'].sudo()._log(
            '成绩复制', 'op.exam', exam.id, exam.name or '',
            '自「%s」复制 %d 条 / 跳过 %d 条' % (
                prev.name or '', done, skipped))
        return request.redirect(
            '/grading/entry?exam_id=%d&copied=%d&skipped=%d'
            % (exam.id, done, skipped))

    @http.route('/grading/history', type='http', auth='user', website=True)
    def grading_history(self, **kw):
        """成绩变更留痕查询（按考试或按学生过滤）。"""
        fac = current_faculty()
        if not fac and not privileged_staff():
            return request.redirect('/my/home')
        env = request.env
        exam_id = str(kw.get('exam_id') or '')
        student_id = str(kw.get('student_id') or '')
        # t34 F2：越权考试按不存在处理（连标题都不显示）
        exam = self._teacher_exam(exam_id) if exam_id.isdigit() else None
        student = env['op.student'].sudo().browse(int(student_id)) \
            if student_id.isdigit() else None
        domain = []
        # t34 F2：教师只看自己任教考试的留痕（教务处/管理员不限）
        if not privileged_staff():
            owned = env['op.exam'].sudo().search(
                self._teacher_exam_domain()).ids
            domain.append(('exam_id', 'in', owned or [0]))
        if exam and exam.exists():
            domain.append(('exam_id', '=', exam.id))
        if student and student.exists():
            domain.append(('student_id', '=', student.id))
        page = max(1, int(kw.get('page', 1) or 1))
        PAGE_SIZE = 50
        Hist = env['edu.grade.history'].sudo()
        total = Hist.search_count(domain)
        return request.render('edu_portal.edu_grading_history', {
            'title': '成绩变更留痕',
            'page_name': 'grading_history',
            'rows': Hist.search(domain, limit=PAGE_SIZE,
                                offset=(page - 1) * PAGE_SIZE),
            'exam': exam if exam and exam.exists() else None,
            'student': student if student and student.exists() else None,
            'total': total,
            # D 组第一批：原来这两张表是**手抄的常量字典**，模型侧
            # exam_session_ext.py 用 selection_add 扩了 source='backend'（后台直改）
            # 之后没人同步 ⇒ /grading/history 的「来源」列对 35 行记录直接漏出英文
            # code「backend」（同列其余值是中文）。改为直接取字段自身的 selection
            # 标签（单一事实源，翻译也跟随用户语言），从根上消除这一类漂移。
            'action_label': dict(Hist._fields['action']._description_selection(env)),
            'source_label': dict(Hist._fields['source']._description_selection(env)),
            'pager': pager('/grading/history', total=total, page=page,
                           step=PAGE_SIZE,
                           url_args={'exam_id': exam_id,
                                     'student_id': student_id}),
        })

    # ------------------------------------------------------------------
    # F2：考勤 Excel 补录导入（两段式；先例：校管家「补点名」）
    # ------------------------------------------------------------------
    @http.route('/attendance/import', type='http', auth='user',
                methods=['GET', 'POST'], website=True, csrf=True)
    def attendance_import(self, **kw):
        """补录导入：GET 上传表单；POST 解析 CSV/XLSX → 预览。"""
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        env = request.env
        batch_id = str(kw.get('batch_id') or '')
        adate = (kw.get('date') or fields.Date.today().isoformat()).strip()
        batch = env['op.batch'].sudo().browse(int(batch_id)) \
            if batch_id.isdigit() else None
        sess = env['op.session'].sudo().search([('faculty_id', '=', fac.id)])
        batches = sess.mapped('batch_id')
        values = {
            'title': '考勤补录导入',
            'page_name': 'attendance_import',
            'batches': batches,
            'batch': batch if batch and batch.exists() else None,
            'sel_batch': int(batch_id) if batch_id.isdigit() else 0,
            'date': adate,
            'preview': None,
            'confirm_json': '',
            'filename': '',
        }
        if request.httprequest.method != 'POST':
            return request.render('edu_portal.edu_attendance_import', values)
        upfile = request.httprequest.files.get('file')
        header, rows = _read_table_file(upfile)
        i_no = _col_index(header, '学号', '学籍号')
        i_name = _col_index(header, '姓名', '学生')
        i_status = _col_index(header, '状态', '出勤状态', '考勤')
        if i_status is None and header:
            i_status = len(header) - 1
        valid, invalid = [], []
        if batch and batch.exists():
            scs = env['op.student.course'].sudo().search(
                [('batch_id', '=', batch.id)])
            by_no = {s.gr_no: s for s in scs.mapped('student_id') if s.gr_no}
            by_name = {}
            for s in scs.mapped('student_id'):
                by_name.setdefault((s.name or '').strip(), s)
            for n, row in enumerate(rows, start=2):
                no, name = _cell(row, i_no), _cell(row, i_name)
                raw_status = _cell(row, i_status)
                status = _ATT_STATUS_LABEL.get(
                    raw_status.lower() if raw_status.isascii()
                    else raw_status)
                stu = by_no.get(no) if no else None
                if stu is None and name:
                    stu = by_name.get(name)
                errors = []
                if not (no or name):
                    errors.append('缺学号与姓名')
                if stu is None:
                    errors.append('该班级无此学生')
                if not status:
                    errors.append('状态需为 出勤/迟到/缺勤')
                item = {'row': n, 'no': no, 'name': name,
                        'student_id': stu.id if stu else 0,
                        'status': status or '', 'status_raw': raw_status}
                if errors:
                    item['errors'] = '；'.join(errors)
                    invalid.append(item)
                else:
                    valid.append(item)
        values.update({
            'preview': {'valid': valid, 'invalid': invalid},
            'confirm_json': json.dumps(valid, ensure_ascii=False),
            'filename': (upfile.filename if upfile else '') or '',
        })
        return request.render('edu_portal.edu_attendance_import', values)

    @http.route('/attendance/import/commit', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def attendance_import_commit(self, **post):
        """补录写入：无当班点名表则补建，有则按补录更新对应学生行。"""
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        env = request.env
        try:
            bid = int(post.get('batch_id', 0))
            cid = int(post.get('course_id', 0) or 0)
            items = json.loads(post.get('payload') or '[]')
        except (TypeError, ValueError):
            bid, cid, items = 0, 0, []
        adate = (post.get('date') or '').strip()
        batch = env['op.batch'].sudo().browse(bid)
        if not (batch.exists() and isinstance(items, list) and adate):
            return request.redirect('/attendance/import')
        course = env['op.course'].sudo().browse(cid)
        if not course.exists():
            course = env['op.session'].sudo().search(
                [('batch_id', '=', bid), ('faculty_id', '=', fac.id)],
                limit=1).course_id
        if not course.exists():
            return request.redirect(
                '/attendance/import?batch_id=%d&date=%s' % (bid, adate))
        Sheet = env['op.attendance.sheet'].sudo()
        sheet = Sheet.search([('batch_id', '=', bid),
                              ('course_id', '=', course.id),
                              ('attendance_date', '=', adate)], limit=1)
        if not sheet:
            # 登记簿：与教师快速点名同一个取或建实现（历史缺陷同源，一起修）
            register = attendance_register(env, course, batch)
            sheet = Sheet.create({
                'register_id': register.id,
                'course_id': course.id,
                'batch_id': bid,
                'attendance_date': adate,
                'faculty_id': fac.id,
            })
        Line = env['op.attendance.line'].sudo()
        done = skipped = 0
        for it in items:
            stu_id = int((it or {}).get('student_id') or 0)
            status = (it or {}).get('status') or ''
            if not stu_id or status not in ('present', 'late', 'absent'):
                skipped += 1
                continue
            present = status in ('present', 'late')
            vals = {'present': present, 'late': status == 'late',
                    'absent': status == 'absent'}
            try:
                with env.cr.savepoint():
                    line = Line.search([('attendance_id', '=', sheet.id),
                                        ('student_id', '=', stu_id)], limit=1)
                    if line:
                        line.write(vals)
                    else:
                        Line.create(dict(vals, attendance_id=sheet.id,
                                         student_id=stu_id,
                                         course_id=course.id, batch_id=bid,
                                         attendance_date=adate,
                                         excused=False))
                    done += 1
            except Exception:
                skipped += 1
        env['edu.audit.log'].sudo()._log(
            '考勤补录导入', 'op.attendance.sheet', sheet.id, sheet.name or '',
            '补录 %d 人 / 跳过 %d 人（%s）' % (done, skipped, adate))
        return request.redirect(
            '/attendance/take?batch_id=%d&date=%s&saved=1' % (bid, adate))

    # ------------------------------------------------------------------
    # F4：公告模板保存（发布页「另存为模板」）
    # ------------------------------------------------------------------
    @http.route('/notice/template/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def notice_template_save(self, **post):
        fac = current_faculty()
        if not fac and not privileged_staff():
            return request.redirect('/my/notice_board/notice')
        name = (post.get('tpl_name') or '').strip()[:128]
        if not name:
            return request.redirect('/notice/publish?err=tpl_name')
        audience = post.get('audience') or 'all'
        if audience not in ('all', 'student', 'faculty', 'parent', 'staff'):
            audience = 'all'
        request.env['edu.notice.template'].sudo().create({
            'name': name,
            'category': (post.get('category') or 'notice')[:64],
            'title_prefix': (post.get('tpl_prefix') or '').strip()[:64],
            'content': post.get('content') or '',
            'audience': audience,
            'channel_site': bool(post.get('channel_site')),
            'channel_email': bool(post.get('channel_email')),
            'channel_telegram': bool(post.get('channel_telegram')),
        })
        request.env['edu.audit.log'].sudo()._log(
            '保存公告模板', 'edu.notice.template', 0, name)
        return request.redirect('/notice/publish?saved_tpl=1')

    # ------------------------------------------------------------------
    # F6：学生自助证明下载（在读证明 / 成绩单，QWeb → PDF）
    # ------------------------------------------------------------------
    @http.route('/my/documents', type='http', auth='user', website=True)
    def my_documents(self, **kw):
        """学生自助下载页：在读证明 + 成绩单（含本学期科目与成绩）。"""
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        rows = self._transcript_rows(student)
        return request.render('edu_portal.edu_my_documents', {
            'title': '我的证明与成绩单',
            'page_name': 'my_documents',
            'student': student,
            'rows': rows,
            'issued': fields.Date.today().strftime('%Y/%m/%d'),
        })

    @staticmethod
    def _transcript_rows(student):
        """成绩单行：按科目汇总考试成绩（只取已录入分数的场次）。"""
        env = request.env
        atts = env['op.exam.attendees'].sudo().search(
            [('student_id', '=', student.id)], order='id desc')
        by_subject = {}
        for att in atts:
            exam = att.exam_id
            key = exam.subject_id.id or 0
            row = by_subject.setdefault(key, {
                'subject': exam.subject_id.name or '—',
                'items': [],
            })
            row['items'].append({
                'exam': exam.name or '—',
                'marks': '' if att.marks in (False, None) else att.marks,
                'total': exam.total_marks or '',
                'min': exam.min_marks or '',
                'status': '出席' if att.status == 'present' else '缺考',
                'passed': bool(att.marks not in (False, None)
                               and exam.min_marks
                               and att.marks >= exam.min_marks),
            })
        return [by_subject[k] for k in sorted(
            by_subject, key=lambda i: by_subject[i]['subject'])]

    def _render_student_pdf(self, report_name, student, data=None):
        """统一 PDF 响应（文件名用 ASCII，避免 Content-Disposition 乱码）。"""
        pdf, _rtype = request.env['ir.actions.report']._render_qweb_pdf(
            report_name, [student.id], data=data or {})
        filename = ('enrollment-certificate'
                    if 'enrollment' in report_name else 'transcript')
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition',
             'attachment; filename="%s-%d.pdf"' % (filename, student.id))])

    @http.route('/my/documents/enrollment-certificate', type='http',
                auth='user', website=True)
    def my_enrollment_certificate(self, **kw):
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        request.env['edu.audit.log'].sudo()._log(
            '自助下载', 'op.student', student.id, student.name or '',
            '在读证明 PDF')
        return self._render_student_pdf(
            'edu_portal.report_edu_enrollment_certificate', student)

    @http.route('/my/documents/transcript', type='http', auth='user',
                website=True)
    def my_transcript(self, **kw):
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        rows = self._transcript_rows(student)
        request.env['edu.audit.log'].sudo()._log(
            '自助下载', 'op.student', student.id, student.name or '',
            '成绩单 PDF')
        return self._render_student_pdf(
            'edu_portal.report_edu_transcript', student,
            data={'rows': rows,
                  'issued': fields.Date.today().strftime('%Y年%m月%d日')})


# ---------------------------------------------------------------------------
# 审批作用域口径：模块级单一事实源（t67）
#
# 提取动机：请假/申诉的列表、批量、单条三处原本共用控制器方法
# _approval_scope_domain()；而选课审批批量（enroll.py 的
# /registrar/subject/set_state_bulk）也需要同一口径 —— 它够不到本控制器类
# 的方法（self. 不可达），若各写一份就变成「两套范围规则」。故提取为模块级
# 函数，控制器方法与 enroll.py 共用同一实现（方法退化为薄包装）。
# 行为与提取前逐字一致：仅把 self / request.env 显式化为参数 env。
# ---------------------------------------------------------------------------
def teacher_taught_batches(env, fac):
    """当前教师任教的班级 id（op.session.faculty_id 口径）。"""
    return env['op.session'].sudo().search(
        [('faculty_id', '=', fac.id)]).mapped('batch_id').ids


def leave_scope_students(env, fac):
    """§8.2 的 ③④：「我任教班级的学生」∪「我当班主任的班的学生」（去重 id）。

    · ③ 任教班级 = op.session.faculty_id 口径（既有 t34 F3，teacher_taught_batches）；
    · ④ 班主任班级 = op.batch.homeroom_teacher_id（S1 新增字段，可空）——
      本仓今天 0 个班主任（字段全空）⇒ 这一项恒为空集，不影响既有可见域；
    · **不看 op.faculty 是否存在**：班主任字段存的是 res.users，与 op.faculty
      0 在职无关（设计稿 §5.1「老师到位后只填数据即生效」——填下拉框即生效）。
    """
    batch_ids = list(teacher_taught_batches(env, fac) if fac else [])
    for bid in env['op.batch'].sudo().search(
            [('homeroom_teacher_id', '=', env.uid)]).ids:
        if bid not in batch_ids:
            batch_ids.append(bid)
    if not batch_ids:
        return []
    return env['op.student.course'].sudo().search(
        [('batch_id', 'in', batch_ids)]).mapped('student_id').ids


def approval_scope_domain(env, model_name='edu.leave'):
    """审批作用范围（t34 F3 + §8.2 请假分级）：教务处/管理员不限。

    请假（`model_name='edu.leave'`，默认）= 下面三项的**并集（OR）**：
      ① 我是这一单**当前一级**应批人（first_approver_id = 我）；
      ② 我是这一单**当前二级**应批人（second_approver_id = 我）；
      ③ 我任教班级 ∪ 我当班主任的班的学生提的单（既有 t34 F3 口径 + §8.2 班主任项）。
    **为什么必须并集**：§4.3(2) 把「我能不能批这一级」的判据从「是不是班主任」
    换成「是不是本单当前这一级的 first_approver_id / second_approver_id」；
    而列表 / 批量 / 单条**必须同域**（既有「看得见的 = 能处置的」，
    见上游 `_approval_scope_domain` 的注释），否则会重现历史缺陷。
    转交后原审批人 ① 落空 ⇒ 立刻看不见、也就批不了（§4.3(2)）。
    ⚠ 例外不破：privileged_staff()（教务处组 / 系统组）**恒可批任何单**，
      故这里第一行就返回「不限」（code-map §6 第 3 条铁律）。

    ⚠ 申诉（model_name='edu.grievance'）**逐字保持 t34 F3 老域**：edu.grievance
      没有这两个字段，把 OR 项拼进去 search 会直接 ValueError（申诉页 500）。
      故本函数新增 `model_name` 形参做显式分流：scoped_record/scoped_records 已把
      它们自己的 model_name 传进来，`_approval_scope_domain` 默认 'edu.leave'
      （既有请假调用点一字不改），申诉调用点显式传 'edu.grievance'。
    """
    if privileged_staff():
        return []
    fac = current_faculty()
    if model_name != 'edu.leave':
        # 非请假模型：一字不改地保留 t34 F3 行为
        if not fac:
            return [('student_id', '=', 0)]
        batches = teacher_taught_batches(env, fac)
        if not batches:
            return [('student_id', '=', 0)]
        students = env['op.student.course'].sudo().search(
            [('batch_id', 'in', batches)]).mapped('student_id')
        return [('student_id', 'in', students.ids or [0])]
    terms = [('first_approver_id', '=', env.uid),
             ('second_approver_id', '=', env.uid)]
    student_ids = leave_scope_students(env, fac)
    if student_ids:
        terms.append(('student_id', 'in', student_ids))
    # OR 前缀（波兰式）：n 项 ⇒ n-1 个 '|'
    return ['|'] * (len(terms) - 1) + terms


def scoped_record(env, model_name, rec_id, extra_domain=None):
    """按审批作用域取单条记录；不存在/越权一律返回空集（按不存在处理）。"""
    dom = approval_scope_domain(env, model_name)
    if extra_domain:
        dom = dom + list(extra_domain)
    try:
        rec_id = int(rec_id or 0)
    except (TypeError, ValueError):
        rec_id = 0
    return env[model_name].sudo().search(dom + [('id', '=', rec_id)], limit=1)


def scoped_records(env, model_name, ids, extra_domain=None):
    """按审批作用域批量取记录（越权 id 不在返回集里）。"""
    dom = approval_scope_domain(env, model_name)
    if extra_domain:
        dom = dom + list(extra_domain)
    return env[model_name].sudo().search(dom + [('id', 'in', list(ids or []) + [0])])


# ===========================================================================
# S3 —— 请假拆分 + 分级审批 + 转交：门户动作面（**本段只追加**）
#
# 设计：docs/plans/leave-split-approval-design.md
#   §3.3 空值行为（没有班主任也能跑）/ §4.3(1)(2)(3)(4) 转交四规则与四层留痕 /
#   §4.4 转交动作面 / §7.1 销假（正交字段，不改 state）/ §7.5 事后补假硬拒（门户侧）/
#   §8 权限矩阵（§8.1 谁能批/谁能转、§8.2 扩域）
#
# 本段对**既有函数**的改动只有下面这几处（其余一字不动）：
#   1) approval_scope_domain(env)：§8.2 请假侧并集（first/second_approver_id）；
#      caller（scoped_record / scoped_records / _approval_scope_domain）把
#      自己的 model_name 传下来，申诉侧显式走 'edu.grievance' 老域。
#   2) leave_approvals / leave_detail / leave_set_state / leave_set_state_bulk 的
#      **准入行**：放宽为 leave_portal_approver()（多一档「本级应批人是我」）。
#      依据 §3.3：op.batch.homeroom_teacher_id 存的是 res.users，而本仓
#      op.faculty 0 个在职行 ⇒ 班主任可以没有教师档案；不放宽则
#      「老师到位后只填数据即生效」跑不通（最主要的使用者进不来）。
#   3) leave_set_state / leave_set_state_bulk 的**执行行**：交给 S2 的冻结动作
#      （一级/二级按当前 state 自动分流，见 _leave_flow_apply_state）；
#      leave_set_state 另接受 new_state=='send_back'（§3.1 二级退回一级）。
#   4) _leave_steps：加 'pending_second' 一档（§3.1）。
#   5) leave_detail：state_label 多一档 + 给模板传 transfer_users / leave_stage。
#   6) child_leave_save：§7.5 门户侧硬拒（学生侧同判据，落在 batch3.py）。
#
# ⚠ 与 S2 的接口约定（**只调用，不实现**）：edu.leave 上的
#   can_user_act / action_first_approve / action_second_approve / action_refuse /
#   action_send_back / action_transfer / action_confirm_return / transfer_candidates
#   （route_of 归模型内部使用，门户侧不需要）。一律经 leave_flow_action() 取用：
#   拿到 ⇒ 走 S2；拿不到 ⇒ fail-closed（不写字段、不猜语义）。唯一例外是
#   leave_set_state 的 approved/refused —— 那里回退到本文件原有的直写实现
#   （逐字保留），保证 S2 落地前后既有功能零回归。
#
# ⚠ 留痕归属（队长 2026-09-25 裁决）：S2 的动作**内部已含**审计与通知
#   （action_transfer = 转交行 + 改写应批人 + 「请假审批转交」审计 + 三方通知；
#   action_first/second_approve / action_refuse = 状态 + 审批留痕 +
#   「请假审批」审计 + 申请人通知）⇒ 控制器**一律不重复写**，只在回退路径补。
#
# ⚠ 命名不一致（留档，防联调扯皮）：设计稿 §10 写 transfer()、§3.2 写模块级
#   route_of(leave)；队长清单写 action_transfer / edu.leave.route_of(self)。
#   本段对转交**两个名字都兼容**（action_transfer 优先，transfer 兜底）。
# ===========================================================================

# 身份反查唯一口径：本段要用「档案 → 账号」的反向并集（§4.3(1)② 判「是不是
# 申请人本人」、§7.1 判「是不是本人/家长」）。文件顶部那条 import 只带了正向
# 反查，故在此**追加**一个 import，不改既有 import 行（# noqa: E402：本仓先例
# main.py:338 也是非顶部 import）。
from odoo.addons.edu_schedule.models.identity import users_of_profile  # noqa: E402


# ---------------------------------------------------------------------------
# 判据层（唯一事实源；路由与模板都从这里取）
# ---------------------------------------------------------------------------
def leave_applicant_kind(env=None):
    """当前登录账号的请假身份（§5.3 唯一口径）：'student' / 'parent' / 'staff'。

    判定只走 edu_schedule/models/identity.py 的**双向并集**反查：
      · op.student 非空      ⇒ 'student'（学生在 /my/time_off 看到学生单）
      · 否则 op.parent 非空  ⇒ 'parent'（家长为孩子请假，**不是**教职单）
      · 两者皆空             ⇒ 'staff'（教职单）
    **不依赖 op.faculty 存在**、**不看 share**：本仓 teacher@local 正是门户账号
    且 share=True，用 share 判会把它错判成学生（§5.3 的显式反例）。
    """
    env = request.env if env is None else env
    if profile_of_user(env, 'op.student'):
        return 'student'
    if profile_of_user(env, 'op.parent'):
        return 'parent'
    return 'staff'


def leave_stage_of_state(state):
    """单据当前处于哪一级（§3.1）：request → 一级；pending_second → 二级。

    其它状态（approved/refused）**没有待批级** ⇒ 返回 None（转交与审批都按
    「不在该级」处理）。这是「我能不能批这一级」的唯一入口。
    """
    return {'request': 'first', 'pending_second': 'second'}.get(state or '')


def leave_portal_approver(env=None):
    """教师侧请假页的准入判据（§8.1）：有教师档案 ∪ privileged_staff ∪ 有我的待批单。

    最后一档是 §3.3 硬要求的落点：「没有班主任也能跑」「老师到位后只填数据即
    生效」—— op.batch.homeroom_teacher_id 存的是 res.users，而本仓 op.faculty
    0 个在职行，班主任完全可能没有教师档案。沿用「无教师档案 ⇒ 回 /my/home」
    的老门槛，会让这批人连队列都进不去（功能对最主要的使用者静默失效）。
    """
    if privileged_staff():
        return True
    if current_faculty():
        return True
    env = request.env if env is None else env
    return bool(env['edu.leave'].sudo().search_count(
        ['|', ('first_approver_id', '=', env.uid),
         ('second_approver_id', '=', env.uid)]))


def leave_applicant_users(leave):
    """本单申请人名下的登录账号（§4.3(1)② / §7.1 的判据；**不用 partner**）。

    · 学生单：student_id → 账号（identity.py 的「档案 → 账号」三条来源并集）；
    · 教职单：applicant_user_id 本身。
    判「是不是申请人本人」必须用这个集合：同一 partner 可能挂多个账号，也可能
    挂着程序化创建的账号，用 partner 判会漏（本仓身份反查踩过两次）。
    """
    users = leave.env['res.users'].sudo().browse()
    if leave.student_id:
        users |= users_of_profile(leave.student_id.sudo())
    if leave.applicant_user_id:
        users |= leave.applicant_user_id.sudo()
    return users


def leave_backdated_guard(raw_date):
    """§7.5 门户侧硬拒判据：date_from < 提交日 ⇒ True。

    边界（设计稿逐字）：**今天请假、今天提交**（date_from == today）允许 ——
    只有严格早于今天才算「事后补假」。解析失败返回 False（交给既有日期解析
    分支处理，不抢它的活）。
    """
    try:
        day = fields.Date.to_date(raw_date) if raw_date else None
    except Exception:
        return False
    return bool(day) and day < fields.Date.today()


def leave_flow_action(rec, name):
    """取 S2 在 edu.leave 上的冻结动作；**没有就返回 None**（调用方必须 fail-closed）。

    为什么要这个薄壳：接口是**并行开发**的冻结契约，控制器不能假设它一定已经
    落地（否则升级窗口里一按按钮就是 500）。取不到 = 功能不可用 = 什么字段都
    不写（绝不猜语义、绝不自己实现一份模型逻辑）。
    """
    fn = getattr(rec, name, None)
    return fn if callable(fn) else None


def leave_transfer_candidates(rec, stage):
    """§4.3(1)：这一级的**合法转入人**（res.users），S2 冻结接口的输出。

    接口未就绪 / 抛错 ⇒ 空集（= 转交入口隐藏、POST 也会被挡）：绝不 fail-open
    到「谁都能转」。再叠一层 §4.3(1)①② 的控制器侧过滤（自己、申请人本人）——
    候选集合的口径在模型（唯一事实源），控制器只做**收窄**不做放大。
    """
    empty = rec.env['res.users'].sudo().browse()
    if not stage:
        return empty
    fn = leave_flow_action(rec, 'transfer_candidates')
    if not fn:
        return empty
    try:
        users = fn(stage)
    except Exception:
        _logger.warning('edu_portal: transfer_candidates(%s) 调用失败，'
                        '转交入口按不可用处理', stage, exc_info=True)
        return empty
    users = (users or empty).sudo()
    banned = set(leave_applicant_users(rec).ids) | {rec.env.uid}
    return users.filtered(lambda u: u.id not in banned)


def _leave_can_act(rec, user, stage=None):
    """§8.1：我能不能批这一单的**当前这一级**。

    优先 S2 的冻结接口 can_user_act(user)（它内含 privileged_staff 恒可批的
    既有例外）；接口缺席时退到 §8.1 的逐字判据
    （user == 当前级 approver_id **or** privileged_staff()）。
    两条路都 fail-closed：判不出来就是「不能」。
    """
    fn = leave_flow_action(rec, 'can_user_act')
    if fn:
        try:
            return bool(fn(user))
        except Exception:
            _logger.warning('edu_portal: can_user_act 调用失败，按无权处理',
                            exc_info=True)
            return False
    if privileged_staff():
        return True
    field = {'first': 'first_approver_id',
             'second': 'second_approver_id'}.get(
                 stage or leave_stage_of_state(rec.state) or '')
    if not field:
        return False
    approver = rec[field]
    return bool(approver and user and approver.id == user.id)


def _leave_can_transfer(rec, user, stage):
    """§4.4：谁能转交 —— **严格**是「本单当前这一级的应批人」本人。

    ⚠ 刻意**不含** privileged_staff 例外：§8.1 把「转交」单列一行，判据是
    user 属于 {first_approver_id, second_approver_id}。教务处/系统组「恒可批」，
    但转交是把自己的待办让渡出去，不等于可以把别人的待办转走。

    优先 S2 的冻结实现 can_user_transfer(user)（它还多查「该级是否已转过」）；
    缺席时用本函数下方的逐字判据（fail-closed）。
    """
    fn = leave_flow_action(rec, 'can_user_transfer')
    if fn:
        try:
            return bool(fn(user))
        except Exception:
            _logger.warning('edu_portal: can_user_transfer 调用失败，按不可转处理',
                            exc_info=True)
            return False
    field = {'first': 'first_approver_id',
             'second': 'second_approver_id'}.get(stage or '')
    if not field or not user:
        return False
    approver = rec[field]
    return bool(approver and approver.id == user.id)


def leave_portal_context():
    """门户自助提交标记（§7.5）：S2 的 _portal_submission() 优先看这个 context。

    为什么必须带上：判据的兜底是「创建者不是特权账号」，而**教务/管理员本人**
    在门户里提交时是特权账号 —— 不带这个标记，他的单会被模型当成「后台代录」
    通道（backfilled=True），§7.5 的硬拒在他身上静默失效。
    """
    try:
        from odoo.addons.edu_portal.models.leave_flow import CTX_PORTAL
        return {CTX_PORTAL: True}
    except Exception:
        return {}


def leave_proof_kind(post):
    """§7.2 的证明方式（表单字段 → 模型 selection，非法值一律 'none'）。"""
    kind = (post.get('proof_kind') or '').strip()
    return kind if kind in ('file', 'oral', 'none') else 'none'


def leave_proof_vals(post):
    """§7.2：门户证明字段 → create 的 vals（S2 的 create 校验读的就是这三个）。"""
    return {
        'proof_kind': leave_proof_kind(post),
        'oral_proof_by': (post.get('oral_proof_by') or '').strip()[:64] or False,
        'oral_proof_relation': (post.get('oral_proof_relation') or '').strip()[:32]
                               or False,
    }


def leave_attach_proof_file(leave, post):
    """§7.2 文件证明：把门户上传的文件落成 ir.attachment(res_model/res_id)。

    为什么只能在**建单后**落库：attachment_ids 是 o2m 到 ir.attachment 的
    （res_id 指向已存在的单据）—— 建单那一刻必然还是空的。
    """
    import base64
    upload = post.get('proof_file') or post.get('attachment')
    if not upload or not getattr(upload, 'filename', None):
        return None
    try:
        data = upload.read()
    except Exception:
        _logger.warning('edu_portal: 证明附件读取失败 leave=%s', leave.id,
                        exc_info=True)
        return None
    if not data:
        return None
    return leave.env['ir.attachment'].sudo().create({
        'name': upload.filename,
        'datas': base64.b64encode(data),
        'res_model': 'edu.leave',
        'res_id': leave.id,
    })


def leave_check_proof(leave):
    """调 S2 的附件复核（§7.2：proof_kind='file' 却一个附件都没有 ⇒ UserError）。

    S2 的 docstring 明确「S3/S4 在上传完成后调用本方法」—— 动作缺席时跳过
    （不 500；证明校验的最终责任仍在模型侧）。
    """
    check = leave_flow_action(leave, '_check_proof_attachments')
    if check:
        return check()
    return None


def _leave_flow_notice(text, back='/leave/approvals'):
    """带用户可见提示的回跳（复用既有 ?bulk_msg= 回执位，模板已渲染）。"""
    return '%s%cbulk_msg=%s' % (back, '&' if '?' in back else '?',
                                quote(text[:200]))


def _leave_flow_apply_state(rec, new_state, reason, was_pending=None):
    """把门户的「同意 / 驳回 / 二级退回」落到 S2 的冻结动作上（§3.1 状态机）。

    为什么必须有这一层（而不是在路由里直接 write state）：
      · 一级通过后到底是 approved 还是 pending_second，由 need_second
        （§3.2 route_of + §7.4 over_quota）决定 —— 那是**模型**的判定，
        控制器复制一份必然走样（4 天的单会被直接终审）；
      · 二级退回（pending_second → request）只有模型知道
        second_sent_back_at / second_send_back_reason 与清空 second_approver_id。
    动作内部守卫是 fail-loud（state 不匹配抛 UserError）⇒ 本函数不吞异常，
    让错误如实暴露，而不是静默 no-op。

    返回值：'action'（已由 S2 动作执行：状态 + 审批留痕 + 审计 + 通知都归它）/
    'legacy'（回退既有直写，并在 was_pending 时补既有通知）/ 'noop'。
    """
    if new_state == 'send_back':
        fn = leave_flow_action(rec, 'action_send_back')
        if not fn:
            return 'noop'            # 'send_back' 不是状态值 ⇒ 没有动作就绝不写
        fn(reason)
        return 'action'
    if new_state == 'approved':
        name = 'action_second_approve' if rec.state == 'pending_second' else 'action_first_approve'
    else:
        name = 'action_refuse'
    fn = leave_flow_action(rec, name)
    if fn:
        if new_state == 'refused':
            fn(reason)
        else:
            fn()
        return 'action'
    # —— S2 动作缺席：逐字沿用本文件既有实现，保证升级窗口内既有功能零回归 ——
    if new_state == 'refused' and reason:
        rec.write({'reject_reason': reason})
    vals = {'state': new_state}
    vals.update(rec._approver_vals())
    rec.write(vals)
    if was_pending:
        rec._notify_applicant(new_state)
    return 'legacy'


# ---------------------------------------------------------------------------
# 门户动作面（§4.4 转交 / §7.1 销假）
# ---------------------------------------------------------------------------
class EduLeaveFlowPortal(http.Controller):
    """请假分级审批的两条新门户路由（S3）。

    两条都是 POST + csrf=True（S4 的表单带 token），并各挂一个 GET 出口：
      · 未登录 GET ⇒ Odoo 的 auth='user' 先接管 ⇒ 303 跳登录（既不是 500，
        也不是 405 —— 探测/误点不会把页面打成错误码）；
      · 已登录 GET ⇒ 303 回跳且**不写任何字段**（不做「GET 也能改状态」的坏事）。
    """

    @http.route('/leave/transfer', type='http', auth='user', website=True,
                methods=['GET', 'POST'], csrf=True)
    def leave_transfer(self, **post):
        """转交审批（§4.3 四条规则 + §4.4 动作面）。

        字段（S4 的表单已写死）：leave_id / stage / to_user_id / reason / next。
        守卫顺序（**每一步都 fail-closed，任何一步不过都不写字段**）：
          ① 越权/不存在 ⇒ 按不存在处理（沿用 scoped_record 的既有口径）；
          ② 当前级由**单据 state** 决定，不信表单的 stage（防伪造）；
          ③ 只有本级应批人**本人**能转（教务处可批但不可替人转，§4.4）；
          ④ 只能转 1 次（入口预检；并发双转由 DB UNIQUE(leave_id, stage) 兜底）；
          ⑤ 转入人必须存在、不是自己、不是申请人、且仍在候选集合内（二次校验）；
          ⑥ 执行 S2 的 action_transfer —— 四层留痕（转交行 / 应批人改写 /
             「请假审批转交」审计 / 三方通知）**全在动作内部**（队长裁决），
             控制器**一律不重复写**；另做一次「转交行是否真落下」的自证。
        """
        back = post.get('next') or ''
        if not back.startswith('/leave/'):
            back = '/leave/approvals'
        if request.httprequest.method != 'POST':
            return request.redirect(back)
        env = request.env
        try:
            lid = int(post.get('leave_id', 0))
        except (TypeError, ValueError):
            lid = 0
        reason = (post.get('reason') or '').strip()[:500]
        if not reason:
            return request.redirect(_leave_flow_notice(
                '转交必须填写原因（留痕三要素：谁转给谁、何时、为什么）'))
        rec = scoped_record(env, 'edu.leave', lid)
        if not rec.exists():
            return request.redirect(back)
        stage = leave_stage_of_state(rec.state)
        posted_stage = (post.get('stage') or '').strip()
        if not stage or (posted_stage and posted_stage != stage):
            return request.redirect(_leave_flow_notice(
                '该单据当前不在你提交的审批级上，页面已刷新'))
        if not _leave_can_transfer(rec, env.user, stage):
            return request.redirect(back)
        Transfer = env['edu.leave.transfer'].sudo()
        if Transfer.search_count([('leave_id', '=', rec.id),
                                  ('stage', '=', stage)]):
            return request.redirect(_leave_flow_notice(
                '该单据该级已转交过 1 次，不能再次转交'))
        raw_to = post.get('to_user_id')
        Users = env['res.users'].sudo()
        to_user = Users.browse(int(raw_to)) if str(raw_to or '').isdigit() else Users.browse()
        if not to_user.exists() or to_user.id == env.user.id:
            return request.redirect(_leave_flow_notice(
                '不能转交给自己，请重新选择转入人'))
        if to_user.id in leave_applicant_users(rec).ids:
            return request.redirect(_leave_flow_notice('不能转交给申请人本人'))
        candidates = leave_transfer_candidates(rec, stage)
        if not candidates or to_user not in candidates:
            return request.redirect(_leave_flow_notice(
                '该账号不在本级合法转入人范围内，请重新选择'))
        action = (leave_flow_action(rec, 'action_transfer')
                  or leave_flow_action(rec, 'transfer'))
        if not action:
            _logger.warning(
                'edu_portal: 转交动作未就绪（edu.leave.action_transfer 缺失），'
                '已 fail-closed：leave=%s 未写任何字段', rec.id)
            return request.redirect(_leave_flow_notice('转交功能尚未就绪，请稍后再试'))
        rec_id, rec_name = rec.id, rec.name or ''
        from_user = env.user
        try:
            action(to_user, reason)
        except pg_errors.UniqueViolation:
            # §4.3(3)：并发双转撞 UNIQUE(leave_id, stage) ⇒ 整事务回滚后再回队列
            # （REPEATABLE READ 下必须结束当前事务，否则重查永远看不见对手；
            #  本仓同款先例 edu_tg_bind/models/tg_claim.py）
            env.cr.rollback()
            env.invalidate_all(flush=False)
            _logger.info('edu_portal: 转交并发冲突（leave=%s stage=%s），已回滚',
                         rec_id, stage)
            return request.redirect(_leave_flow_notice(
                '该单据该级已转交过 1 次，不能再次转交'))
        if not Transfer.search_count([('leave_id', '=', rec_id),
                                      ('stage', '=', stage)]):
            _logger.warning(
                'edu_portal: action_transfer 未落下转交行（leave=%s stage=%s），'
                '按未执行处理', rec_id, stage)
            return request.redirect(_leave_flow_notice('转交未生效，请稍后重试'))
        return request.redirect(back)

    @http.route('/leave/<int:leave_id>/return_confirm', type='http',
                auth='user', website=True, methods=['GET', 'POST'], csrf=True)
    def leave_return_confirm(self, leave_id, **post):
        """销假（§7.1）：学生/家长提交「行程及实践收获」→ 班主任/教务确认。

        同一条路由两跳（S4 的表单）：
          · 提交侧：return_note，判据 = **本人/家长**（不看审批权）；
          · 确认侧：confirm=1，判据 = 本级应批人 or privileged_staff（§8.1），
            执行 S2 的 action_confirm_return（return_confirmed_at/by 由它写）。
        销假是**正交字段**、**不改 state** —— 做成第五个状态会打断既有三档筛选、
        首页计数与 _leave_steps()（§7.1）。两跳都 fail-closed：判不出来就回门户，
        不写任何字段。
        """
        if request.httprequest.method != 'POST':
            return request.redirect('/my/home')
        env = request.env
        try:
            rec = env['edu.leave'].sudo().browse(int(leave_id or 0))
        except (TypeError, ValueError):
            rec = env['edu.leave'].sudo().browse()
        if not rec.exists():
            return request.redirect('/my/home')
        note = (post.get('return_note') or post.get('note') or '').strip()[:2000]
        confirm = str(post.get('confirm') or '') in ('1', 'true', 'True',
                                                     'on', 'yes')
        user = env.user
        is_applicant = user.id in leave_applicant_users(rec).ids
        # 两跳的判据（§8.1）：确认侧 = 本级应批人 or privileged_staff；
        # 提交侧 = 本人/家长。判不出来一律回门户、不写字段。
        if confirm:
            if not _leave_can_act(rec, user):
                return request.redirect('/my/home')
        elif not is_applicant:
            return request.redirect('/my/home')
        action = leave_flow_action(rec, 'action_confirm_return')
        if action:
            # S2 的动作**一个入口两种角色**（申请人写 return_note；审批人写
            # return_confirmed_at/by），留痕、审计与「已到期才能销假」的校验都在
            # 模型里（唯一事实源）⇒ 控制器不重复写任何字段、不重复写审计。
            confirmed = action(note)
            if confirm or confirmed:
                return request.redirect('/leave/approvals')
            return request.redirect('/my/time_off?box=return_submitted')
        # —— 动作缺席（并行开发安全网）：只有「申请人提交说明」这一跳可以按
        #    §7.1 直写 return_note 一个字段；审批人确认那一跳**绝不直写**
        #    （return_confirmed_* 是裁决留痕，只能由模型动作落）——
        if confirm or rec.state != 'approved':
            _logger.warning('edu_portal: action_confirm_return 未就绪，'
                            '销假 fail-closed：leave=%s 未写任何字段', rec.id)
            return request.redirect(_leave_flow_notice(
                '销假功能尚未就绪，请稍后再试', '/my/time_off'))
        rec.write({'return_note': note})
        env['edu.audit.log'].sudo()._log(
            '请假销假', 'edu.leave', rec.id, rec.name or '',
            '提交销假说明%s' % ('：%s' % note[:60] if note else ''))
        return request.redirect('/my/time_off?box=return_submitted')
