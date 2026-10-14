# -*- coding: utf-8 -*-
"""学生门户批次3控制器：12 个静态/轻量页面骨架 + 学术日历。

数据来源：
- op.media.queue        （/requested/queue/list 图书预约队列，注意按 partner_id 过滤）
- op.subject.registration（/subject/registration 科目注册，社区版有模型）
- edu.leave / edu.grievance（自建轻量模型，见 models/leave.py、models/grievance.py）
- op.academic.year / op.academic.term（/my/academic-calendar）
- 其余页面（证书 / 数字图书馆 / 课程变更 / 会议 / OMR / 测验结果等）
  社区版无对应模型，按参考 DOM 渲染结构 + 优雅空态。

工程红线：QWeb 模板中不出现 % 格式化表达式（Odoo 19 装载时 %% 折叠会崩），
所有百分比字符串一律在 Python 侧预格式化后传入模板。
"""
import json
import re

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request

from .main import csv_download, current_student, student_course
# §5.3 / §7.5（S3）：/my/time_off 的学生/教职身份分流与「禁止事后补假」判据
# 都只有一份实现（落 controllers/roles.py，身份反查走
# edu_schedule/models/identity.py 的唯一口径）—— 这里只 import，不复制规则。
from .roles import (leave_applicant_kind, leave_attach_proof_file,
                    leave_backdated_guard, leave_check_proof,
                    leave_portal_context, leave_proof_vals)

# 请假类型 / 申诉状态 / 队列状态 的中文标签（selection -> label）
_LEAVE_TYPE_LABEL = {
    'sick': '病假', 'legal': '法定假',
    'casual': '事假', 'other': '其他',
}
_LEAVE_STATE_LABEL = {
    'request': '已申请', 'approved': '已批准', 'refused': '已拒绝',
    # §3.1（S3）：四级状态机的第四态。缺这一条，学生/教职列表会直接把
    # 英文 code 'pending_second' 显示给用户。
    'pending_second': '待二级审批',
}
_QUEUE_STATE_LABEL = {
    'request': '已申请', 'accept': '已接受', 'reject': '已驳回',
}
_GRIEVANCE_STATE_LABEL = {
    'draft': '草稿', 'submitted': '已提交', 'in_progress': '进行中',
    'resolve': '已解决', 'reject': '已驳回', 'close': '已关闭',
}
_SUBJREG_STATE_LABEL = {
    'draft': '草稿', 'submitted': '已提交',
    'approved': '已批准', 'rejected': '已驳回',
}
_CERT_STATE_LABEL = {
    'draft': '草稿', 'issued': '已发放',
}


def _fmt_date(d):
    return d.strftime('%Y/%m/%d') if d else ''


# 「调班审批」审计明细的固定格式（models/registration.py
# action_course_change_approve 写入）。学生页用它还原「原班 → 新班」对照：
# 数据源 = edu.audit.log（设计 §11.2：不新增字段，同一份留痕即可复读）。
_CCR_DETAIL_RE = re.compile(
    r'^通过：原 (?P<old>.*) → 新 (?P<new>.*)'
    r'（档案 \d+，课程 \d+→\d+，科目 \d+ 门）$')


def _parse_ccr_detail(detail):
    """从审批审计明细里取回 (原标签, 新标签)；解析失败返回 ('', '')。"""
    m = _CCR_DETAIL_RE.match((detail or '').strip())
    if not m:
        return '', ''
    return m.group('old'), m.group('new')


def _nav_params(kw):
    """统一读取排序/筛选/分组/搜索四个导航参数。"""
    return {
        'sortby': kw.get('sortby') or 'none',
        'filterby': kw.get('filterby') or 'all',
        'groupby': kw.get('groupby') or 'none',
        'search': (kw.get('search') or '').strip(),
    }


def _leave_days(rec):
    """请假天数（含首尾）。"""
    if rec.date_from and rec.date_to:
        return (rec.date_to - rec.date_from).days + 1
    return 0


def _leave_type_label(env, code):
    """类型中文标签（§6）：本地表优先，其次**模型 selection 的标签**，最后才退 code。

    为什么必须有「其次模型」这一档：§6 把类型重做成 7 个 code；任何一份手写的
    中文表都会在下次加类型时漏掉新 code ⇒ 页面直接把英文 code 显示给用户
    （实测：婚姻假/寒暑假/实践周在 /my/time_off 上就是这样被 check_english 点名的）。
    模型那一档对新类型本来就是中文（婚丧假/寒暑假/实践周），**不会**把
    'Sick Leave' 这类历史英文标签带上页面 —— 旧 code 先被本地表命中。
    """
    label = _LEAVE_TYPE_LABEL.get(code)
    if label:
        return label
    try:
        desc = env['edu.leave']._fields['leave_type'].get_description(env)
        for item in desc.get('selection') or []:
            if item[0] == code:
                return item[1]
    except Exception:
        pass
    return code or ''


# ---------------------------------------------------------------------------
# /my/time_off 的共享零件（S3：学生视图与教职视图**同一形状**，防口径分裂）
# ---------------------------------------------------------------------------
def _time_off_item(lv, viewer=None):
    """列表行数据（源字段一处定义，两个身份的视图共用）。"""
    return {
        'leave': lv,
        'name': lv.name or '',
        'type': _leave_type_label(lv.env, lv.leave_type),
        'type_raw': lv.leave_type or '',
        # 学生单取 student_id；教职单没有学生档案 ⇒ 退到申请人账号名（§5.3）
        'student_name': (lv.student_id.name
                         if lv.student_id else (viewer.name
                                                if viewer else '')
                         or (lv.applicant_user_id.name or '')),
        'date_from': _fmt_date(lv.date_from),
        'date_to': _fmt_date(lv.date_to),
        'days': _leave_days(lv),
        'days_str': '%d 天' % _leave_days(lv),
        'state': _LEAVE_STATE_LABEL.get(lv.state, lv.state or ''),
        'state_raw': lv.state or '',
        'reason': lv.reason or '',
    }


def _sort_time_off_items(items, sortby):
    """列表排序（学生/教职同一口径）。"""
    order = {
        'date': lambda i: (i['leave'].date_from or fields.Date.today()),
        'state': lambda i: (i['state_raw'], i['name']),
        'leave_type': lambda i: (i['type_raw'], i['name']),
        'request_number': lambda i: i['name'],
    }.get(sortby or 'date')
    if order:
        items.sort(key=order, reverse=(sortby == 'date'))
    return items


def _time_off_stats(leaves):
    """统计卡：**待审批 = request + pending_second**（§3.1 新增第四态）。"""
    return {
        'total': len(leaves),
        'approved': sum(1 for lv in leaves if lv.state == 'approved'),
        'pending': sum(1 for lv in leaves
                       if lv.state in ('request', 'pending_second')),
        'refused': sum(1 for lv in leaves if lv.state == 'refused'),
    }


def _leave_type_codes(env):
    """leave_type 的合法码 —— 从**模型**读，不在路由里抄一份。

    为什么：§6 重做类型（marriage_funeral / winter_summer / practice_week …），
    路由若照抄一份老清单，新类型会被**静默降级成「其他」**（不报错、数据已经错了）。
    读模型的 selection ⇒ 类型表只有一处事实源；读不到时退回老清单。
    """
    try:
        desc = env['edu.leave']._fields['leave_type'].get_description(env)
        return {code for code, _label in desc.get('selection') or []}
    except Exception:
        return {'sick', 'legal', 'casual', 'other'}


def _leave_seq(env):
    """下一个单号序号（**既有口径逐字保留**：取 id 最大的单，名字第 4 位起为数字）。"""
    last = env['edu.leave'].sudo().search([], order='id desc', limit=1)
    if last and last.name and last.name[3:].isdigit():
        return int(last.name[3:]) + 1
    return 1


def _template_exists(xmlid):
    """模板是否已存在（S3 的教职视图安全网：S4 建了就用，没建就回退）。"""
    try:
        return bool(request.env['ir.ui.view'].sudo().search_count(
            [('key', '=', xmlid)]))
    except Exception:
        return False


# 申诉分类固定选项（学生提交时选用）
GRIEVANCE_CATEGORIES = [
    '学业 / 成绩问题',
    '考勤 / 纪律问题',
    '缴费 / 费用问题',
    '图书馆 / 设施问题',
    '非学业 / 交通与住宿问题',
    '其他',
]


class EduStudentBatch3(http.Controller):

    # ------------------------------------------------------------------
    # /certificate 结业证书（edu.certificate 真实数据）+ PDF 下载
    # ------------------------------------------------------------------

    @http.route('/certificate', type='http', auth='user', website=True)
    def certificate(self, **kw):
        p = _nav_params(kw)
        student = current_student()
        domain = [('student_id', '=', student.id)] if student \
            else [('id', '=', 0)]
        if p['search']:
            domain += ['|', ('certificate_no', 'ilike', p['search']),
                       ('course_id.name', 'ilike', p['search'])]
        certs = request.env['edu.certificate'].sudo().search(
            domain, order='issue_date desc, id desc')

        items = []
        for c in certs:
            items.append({
                'cert_id': c.id,
                'certificate_no': c.certificate_no or '',
                'course': c.course_id.name if c.course_id else '',
                'issue_date': _fmt_date(c.issue_date),
                'grade': c.grade or '',
                'state': _CERT_STATE_LABEL.get(c.state, c.state or ''),
                'state_raw': c.state or '',
            })
        if p['sortby'] == 'course_id':
            items.sort(key=lambda i: (i['course'], i['certificate_no']))

        values = {
            'title': '课程结业证书',
            'page_name': 'certificate',
            'student': student,
            'sortby': p['sortby'],
            'filterby': p['filterby'],
            'groupby': p['groupby'],
            'search': p['search'],
            'items': items,
            'has_records': bool(items),
        }
        return request.render('edu_portal.edu_certificate', values)

    @http.route('/my/certificate/download/<int:cert_id>', type='http',
                auth='user', website=True)
    def certificate_download(self, cert_id, **kw):
        """证书 PDF 下载：仅本人或内部用户。"""
        cert = request.env['edu.certificate'].sudo().browse(cert_id).exists()
        student = current_student()
        is_owner = bool(student and cert.student_id.id == student.id)
        if not cert or not (is_owner or request.env.user._is_internal()):
            return request.not_found()
        pdf, _dummy = request.env['ir.actions.report']._render_qweb_pdf(
            'edu_portal.report_edu_certificate', [cert.id])
        filename = (cert.certificate_no or 'certificate').replace('/', '-')
        return request.make_response(
            pdf,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition',
                 'attachment; filename="%s.pdf"' % filename),
            ])

    # ------------------------------------------------------------------
    # /my-library 数字图书馆（分类入口卡 + 真实馆藏统计）
    # ------------------------------------------------------------------

    @http.route('/my-library', type='http', auth='user', website=True)
    def my_library(self, **kw):
        student = current_student()
        env = request.env
        box = kw.get('box') or ''

        total_books = env['op.media'].sudo().search_count([])
        in_progress = returned = 0
        if student:
            movs = env['op.media.movement'].sudo().search(
                [('student_id', '=', student.id)])
            in_progress = sum(1 for mv in movs if mv.state == 'issue')
            returned = sum(1 for mv in movs if mv.actual_return_date)
        reading_list = 0
        if student:
            reading_list = env['op.media.queue'].sudo().search_count(
                [('partner_id', '=', student.partner_id.id)])

        stats = {
            'total_books': total_books,
            'in_progress': in_progress,
            'reading_list': reading_list,
            'audiobooks': 0,
        }

        # 分类入口卡：按 op.media.type 聚合，点击跳转 /library/media 筛选
        cats = env['op.media.type'].sudo().search([], order='id asc')
        cat_cards = []
        for t in cats:
            n = env['op.media'].sudo().search_count(
                [('media_type_id', '=', t.id)])
            cat_cards.append({
                'id': t.id,
                'name': t.name or '',
                'count': n,
                'icon': 'fa-book',
                'all': False,
            })
        cat_cards.append({
            'id': 0,
            'name': '查看全部馆藏',
            'count': total_books,
            'icon': 'fa-list-ul',
            'all': True,
        })

        if box == 'in_progress':
            stats['_box'] = 'in_progress'
        elif box == 'reading_list':
            stats['_box'] = 'reading_list'
        else:
            stats['_box'] = ''

        values = {
            'title': '我的图书馆',
            'page_name': 'my_library',
            'student': student,
            'stats': stats,
            'cat_cards': cat_cards,
            'box': box,
            'has_media': bool(total_books),
        }
        return request.render('edu_portal.edu_my_library', values)

    # ------------------------------------------------------------------
    # /course/change/request 换班申请（= 归属变更：目标课程 + 目标班级成对）
    #
    # 设计：docs/plans/class-change-request-design.md §19。
    # 载体裁定（v2）：**沿用既有路由族与既有 doc_type='course_change'**，
    # 只把表单从「只收目标课程」补齐成「目标课程 + 目标班级成对」
    # （服务端 batch3.py 早就在读 batch_id，缺的只是模板里的一个 select），
    # 教务侧解除硬排除后即可审批。不新增 doc_type、不新增路由族。
    # ------------------------------------------------------------------

    @staticmethod
    def _ccr_current(student, env):
        """学生当前在读档案（零新字段口径：只认唯一的 running 档案）。

        返回 (sc, can_submit, note)：
          - sc 有值且 can_submit=True 时，才是合法的申请人；
          - 0 条 → 提示先由教务分班；>1 条 → 不让学生选（改错行风险不可接受，
            与审批动作 _ccr_source_archive 同口径）。
        """
        if not student:
            return env['op.student.course'].sudo().browse(), False, ''
        scs = env['op.student.course'].sudo().search([
            ('student_id', '=', student.id), ('state', '=', 'running')],
            order='id')
        if not scs:
            return env['op.student.course'].sudo().browse(), False, \
                '您当前没有在读档案，暂时不能提交换班申请。请联系教务先在学生页面分班。'
        if len(scs) > 1:
            return env['op.student.course'].sudo().browse(), False, \
                '您有 %d 条在读档案，系统无法确定要变更哪一条（避免改错行）。请联系教务处理后再提交。' % len(scs)
        return scs, True, ''

    @http.route('/course/change/request', type='http', auth='user',
                website=True)
    def course_change_request(self, **kw):
        student = current_student()
        if not student:
            # 门户铁律：非学生身份（家长/教师/教务/访客）一律回首页。
            # 2026-09-18 补：原实现**没有**这道门禁 —— 家长能拿到 200 空页
            # （与刚上线的「家长读不到」口径冲突，设计 §15 V5 要求 303 + /my/home）。
            return request.redirect('/my/home')
        p = _nav_params(kw)
        box = kw.get('box') or ''
        env = request.env
        # 本页是「换班申请」：只列归属变更单（doc_type=course_change）。
        # 选课注册单在 /subject/registration（我的申请）里，两张页各看各的。
        domain = [('student_id', '=', student.id),
                  ('doc_type', '=', 'course_change')] if student \
            else [('id', '=', 0)]
        if p['filterby'] in ('approved', 'rejected', 'submitted'):
            domain.append(('state', '=', p['filterby']))
        regs = env['op.subject.registration'].sudo().search(
            domain, order='id desc')
        sc, can_submit, block_note = self._ccr_current(student, env)
        cur_label = '%s · %s' % (sc.course_id.name or '—',
                                 sc.batch_id.name or '—') if sc else ''
        # 审批留痕（edu.audit.log）→ 学生列表的「原 → 新」对照。
        # 只读既有审计行，不新增字段（设计 §11.2 幂等口径同一数据源）。
        audits = {}
        if regs:
            logs = env['edu.audit.log'].sudo().search([
                ('model', '=', 'op.subject.registration'),
                ('res_id', 'in', regs.ids),
                ('action', '=', '调班审批')], order='id')
            for log in logs:
                audits[log.res_id] = log.detail or ''
        items = []
        for r in regs:
            old_label, new_label = '', ''
            if r.state == 'approved':
                old_label, new_label = _parse_ccr_detail(
                    audits.get(r.id) or '')
            if not new_label:
                new_label = '%s · %s' % (r.course_id.name if r.course_id
                                         else '—',
                                         r.batch_id.name if r.batch_id else '—')
            if not old_label and r.state != 'approved':
                # 未生效的单：来源就是学生当前档案（审批后档案才变）
                old_label = cur_label or '—'
            items.append({
                'id': r.id,
                'name': r.name or '',
                'course': r.course_id.name if r.course_id else '',
                'batch': r.batch_id.name if r.batch_id else '',
                'old_label': old_label or '—',
                'new_label': new_label,
                'note': r.applicant_note or '',
                'reject_reason': r.reject_reason or '',
                'state': _SUBJREG_STATE_LABEL.get(r.state, r.state or ''),
                'state_raw': r.state or '',
            })
        stats = {
            'total': len(items),
            'approved': sum(1 for i in items if i['state_raw'] == 'approved'),
            'pending': sum(1 for i in items
                           if i['state_raw'] == 'submitted'),
            'rejected': sum(1 for i in items if i['state_raw'] == 'rejected'),
        }
        # 目标课程：只列 active（照 enroll.py:79-80 既有口径；旧实现无过滤）
        courses = env['op.course'].sudo().search(
            [('active', '=', True)], order='name')
        batch_map = {}
        if courses:
            for b in env['op.batch'].sudo().search([
                    ('course_id', 'in', courses.ids), ('active', '=', True)],
                    order='name'):
                batch_map.setdefault(str(b.course_id.id), []).append({
                    'id': b.id,
                    'name': b.name or '',
                    'session_n': env['op.session'].sudo().search_count(
                        [('batch_id', '=', b.id)]),
                    'student_n': env['op.student.course'].sudo().search_count(
                        [('batch_id', '=', b.id), ('state', '=', 'running')]),
                })
        values = {
            'title': '换班申请',
            'page_name': 'course_change_request',
            'student': student,
            'sortby': p['sortby'],
            'filterby': p['filterby'],
            'groupby': p['groupby'],
            'search': p['search'],
            'box': box,
            'msg': (kw.get('msg') or '')[:200],
            'stats': stats,
            'items': items,
            'courses': courses,
            'batch_map': batch_map,
            'batch_map_json': json.dumps(batch_map, ensure_ascii=False),
            'cur_sc': sc,
            'cur_label': cur_label,
            'cur_course_id': sc.course_id.id if sc else 0,
            'can_submit': can_submit,
            'block_note': block_note,
            'has_records': bool(items),
        }
        return request.render('edu_portal.edu_course_change_request', values)

    @http.route('/course/change/request/save', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def course_change_request_save(self, **kw):
        """提交换班/换课申请（服务端校验防绕过；见设计 §19.4 五条）。

        单据**不带任何科目集**：带科目集会被 -u edu_portal 的
        _infer_doc_type() 静默改写成选课单（设计 §5.3 / §19.2.2 #1 硬约束）。
        """
        from urllib.parse import quote as _quote

        student = current_student()
        if not student:
            return request.redirect('/course/change/request')
        env = request.env

        def _back(code, msg):
            return request.redirect(
                '/course/change/request?box=%s&msg=%s' % (code, _quote(msg)))

        sc, can_submit, block_note = self._ccr_current(student, env)
        if not can_submit:
            return _back('error', block_note)
        try:
            course_id = int(kw.get('course_id') or 0)
            batch_id = int(kw.get('batch_id') or 0)
        except (TypeError, ValueError):
            return _back('error', '请选择有效的目标课程与目标班级。')
        course = env['op.course'].sudo().browse(course_id)
        batch = env['op.batch'].sudo().browse(batch_id)
        if not course.exists() or not course.active:
            return _back('error', '目标课程无效或已停用，请重新选择。')
        if not batch.exists() or not batch.active:
            return _back('error', '目标班级无效或已停用，请重新选择。')
        if batch.course_id.id != course.id:
            return _back('error', '目标班级不属于所选课程，请重新选择。')
        if sc.course_id.id == course.id and sc.batch_id.id == batch.id:
            return _back('error', '目标课程与班级和您当前在读的一致，无需申请。')
        dup = env['op.subject.registration'].sudo().search_count([
            ('student_id', '=', student.id), ('state', '=', 'submitted'),
            ('doc_type', '=', 'course_change')])
        if dup:
            return _back('error', '您已有一条待审批的换班申请，请等教务处理后再提交。')
        # 撞约束预检（提交时先拦，别等教务点通过才炸 IntegrityError）
        clash = env['op.student.course'].sudo().search_count([
            ('student_id', '=', student.id), ('course_id', '=', course.id),
            ('batch_id', '=', batch.id), ('id', '!=', sc.id)])
        if clash:
            return _back(
                'error', '您已有一条「%s · %s」的档案，无法重复变更到同一班级。'
                % (course.name or '', batch.name or ''))
        roll = sc.roll_number
        if roll:
            roll_dup = env['op.student.course'].sudo().search_count([
                ('roll_number', '=', roll), ('course_id', '=', course.id),
                ('batch_id', '=', batch.id), ('id', '!=', sc.id)])
            if roll_dup:
                return _back(
                    'error', '您的学号「%s」在目标班级已被占用，'
                    '请先联系教务处理学号后再申请。' % roll)
        note = (kw.get('reason') or kw.get('applicant_note') or '').strip()[:500]
        reg = env['op.subject.registration'].sudo().create({
            'student_id': student.id,
            'course_id': course.id,
            'batch_id': batch.id,
            'state': 'submitted',
            'submitted_at': fields.Datetime.now(),
            'applicant_note': note,
            # 单据类型：归属变更（换班/换课）；科目字段一律留空
            'doc_type': 'course_change',
        })
        if not reg.name or reg.name in ('New', '/'):
            # 保留既有兜底：基座 op.subject.registration.create() 已用
            # ir.sequence('op.subject.registration') 分配 SR%05d 名，走到这里说明
            # 序列缺号；此时才用 CR 前缀（设计 P1′ 说的「CR%05d 已在用」与实况
            # 不符 —— 实测新建单号是 SR0517，本地 11 张历史变更单也都是 SR0008–17）。
            reg.name = 'CR%05d' % reg.id
        env['edu.audit.log'].sudo()._log(
            '调班提交', 'op.subject.registration', reg.id, reg.name or '',
            '学生 %s：原 %s · %s → 新 %s · %s（理由：%s）'
            % (student.name or '', sc.course_id.name or '—',
               sc.batch_id.name or '—', course.name or '', batch.name or '',
               (note or '—')[:40]))
        return request.redirect(
            '/course/change/request?box=submitted&new_id=%d' % reg.id)

    # ------------------------------------------------------------------
    # 请假/申诉提交（edu.leave / edu.grievance 写路由）
    # ------------------------------------------------------------------

    @http.route('/my/time_off/save', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def my_time_off_save(self, **kw):
        env = request.env
        student = current_student()
        # §5.3（S3）分流：学生 → 学生单；student/parent 皆空 → **教职单**；
        # 家长不算教职（他的入口是 /my/child/<id>/leave）⇒ 回本页走分流。
        if not student and leave_applicant_kind() != 'staff':
            return request.redirect('/my/time_off')
        # §6：类型合法码从**模型**读 —— 路由里再抄一份老清单的话，新类型
        # （marriage_funeral / winter_summer / practice_week …）会被**静默
        # 降级成「其他」**（不报错、数据已经错了）。
        leave_type = kw.get('leave_type') \
            if kw.get('leave_type') in _leave_type_codes(env) else 'other'
        try:
            date_from = fields.Date.to_date(kw.get('date_from'))
            date_to = fields.Date.to_date(kw.get('date_to'))
        except Exception:
            return request.redirect('/my/time_off?box=error_date')
        # 空日期必须在这里挡住：fields.Date.to_date('') 返回 False（**不抛异常**），
        # 于是原写法 date_to < date_from 会 TypeError ⇒ 整页 500。
        # （实测证据：2026-09-24 空 date_from 的 POST /my/time_off/save →
        #  "TypeError: '<' not supported between instances of 'datetime.date'
        #   and 'NoneType'" @ batch3.py:562。既有页面的 required 只挡浏览器，
        #   挡不住任何非浏览器客户端。）
        if not date_from or not date_to:
            return request.redirect('/my/time_off?box=error_date')
        if date_to < date_from:
            # 2026-10-03（视觉/交互复核）：原先这里是**静默改写** —— `date_to = date_from`，
            # 然后照常落库并回「请假申请已提交」。
            # 实测：填「开始 2026-10-10、结束 2026-10-01」提交 ⇒ 页面说"已提交"，
            # 而实际落库的是**一天**（10-10）。**用户永远不知道自己的输入被改过。**
            # 结束早于开始是语义矛盾，系统不该替用户猜一个值 —— 改为明确告知、让用户自己改。
            return request.redirect('/my/time_off?box=error_range')
        # §7.5（S3）：门户侧**禁止事后补假** —— date_from < 提交日 ⇒ 硬拒、不落库。
        # 边界：今天请假、今天提交（date_from == today）**允许**；后台代录历史走
        # backfilled 通道，不受本校验（判据只有一份：roles.leave_backdated_guard）。
        if leave_backdated_guard(date_from):
            raise UserError(
                '《请假条例》一·2 规定严禁事后补假，请勿补提过去日期的申请。')
        vals = {
            'name': 'SLR%06d' % _leave_seq(env),
            'leave_type': leave_type,
            'date_from': date_from,
            'date_to': date_to,
            'reason': (kw.get('reason') or '').strip()[:500] or '—',
        }
        if student:
            # 课代表（需求①）：请假可**选填**「涉及课程」——只能选自己的课程。
            # 不填 => subject_id 为空 => 课代表无权批（fail-closed），走老师/教务，
            # 对既有流程零影响（设计 §6.3 / §8-16）。
            subject_id = False
            raw_sid = kw.get('subject_id')
            if raw_sid and str(raw_sid).isdigit():
                mine = env['op.student.course'].sudo().search([
                    ('student_id', '=', student.id)]).mapped('subject_ids')
                hit = mine.filtered(lambda s: s.id == int(raw_sid))
                subject_id = hit.id if hit else False
            vals.update({'student_id': student.id, 'subject_id': subject_id,
                         'applicant_kind': 'student'})
        else:
            # 教职单（§5.3）：申请人 = 登录账号本身；学生单才用 student_id
            vals.update({'student_id': False, 'applicant_kind': 'staff',
                         'applicant_user_id': env.user.id})
        # §7.2（S3）：证明字段原样转发给模型 —— S2 的 create 校验读的是
        # vals['proof_kind']/['oral_proof_by']，路由不转发的话，用户明明在表单里
        # 填了口头证明人也会被判成「未提供证明」而拒绝。
        vals.update(leave_proof_vals(kw))
        # §7.5：带上「门户自助提交」context（教务/管理员本人在门户提交时，
        # 模型的兜底判据会把特权账号误判成后台代录通道）。
        leave = env['edu.leave'].sudo().with_context(
            **leave_portal_context()).create(vals)
        # §7.2 文件证明：附件是 o2m，只能建单后落库；随后调 S2 的附件复核
        # （S2 的 docstring 明确要求 S3/S4 在上传完成后调它）。
        leave_attach_proof_file(leave, kw)
        leave_check_proof(leave)
        return request.redirect('/my/time_off?box=submitted')

    @http.route('/my/grievances/save', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def my_grievances_save(self, **kw):
        student = current_student()
        if not student:
            return request.redirect('/my/grievances')
        subject = (kw.get('subject') or '').strip()[:200]
        if not subject:
            return request.redirect('/my/grievances?box=error_subject')
        category = kw.get('category') if kw.get('category') in \
            GRIEVANCE_CATEGORIES else '其他'
        env = request.env
        last = env['edu.grievance'].sudo().search(
            [], order='id desc', limit=1)
        seq = 1
        if last and last.name and last.name[3:].isdigit():
            seq = int(last.name[3:]) + 1
        env['edu.grievance'].sudo().create({
            'name': 'GRI%04d' % seq,
            'student_id': student.id,
            'subject': subject,
            'category': category,
            'description': (kw.get('description') or '').strip()[:2000],
            'state': 'submitted',
        })
        return request.redirect('/my/grievances?box=submitted')

    # ------------------------------------------------------------------
    # /subject/registration 科目注册（op.subject.registration 真实数据）
    # ------------------------------------------------------------------

    @http.route('/subject/registration', type='http', auth='user',
                website=True)
    def subject_registration(self, **kw):
        student = current_student()
        p = _nav_params(kw)
        box = kw.get('box') or ''
        env = request.env

        domain = [('student_id', '=', student.id)] if student \
            else [('id', '=', 0)]
        if p['filterby'] in ('approved', 'rejected', 'submitted'):
            domain.append(('state', '=', p['filterby']))
        if p['search']:
            domain += ['|', ('name', 'ilike', p['search']),
                       ('course_id.name', 'ilike', p['search'])]
        regs = env['op.subject.registration'].sudo().search(domain)

        items = []
        for r in regs:
            # 科目并集（compulsory 在前、去重，保留 op.subject 记录供链入 LMS）
            seen = set()
            subj_recs = []
            for s in list(r.compulsory_subject_ids) + \
                    list(r.elective_subject_ids):
                if s.id not in seen:
                    seen.add(s.id)
                    subj_recs.append(s)
            items.append({
                'reg': r,
                'name': r.name or '',
                'state': _SUBJREG_STATE_LABEL.get(r.state, r.state or ''),
                'state_raw': r.state or '',
                'course': r.course_id.name if r.course_id else '',
                'course_id': r.course_id.id if r.course_id else 0,
                'batch': r.batch_id.name if r.batch_id else '',
                'student_name': (r.student_id.name
                                 if r.student_id else (student.name
                                                       if student else '')),
                'subjects': subj_recs,
                'reject_reason': r.reject_reason or '',
            })

        order = {
            'name': lambda i: i['name'],
            'course_id': lambda i: (i['course'], i['name']),
            'batch_id': lambda i: (i['batch'], i['name']),
            'state': lambda i: (i['state_raw'], i['name']),
        }.get(p['sortby'])
        if order:
            items.sort(key=order)

        groups = []
        if p['groupby'] == 'course_id':
            by_course = {}
            for i in items:
                by_course.setdefault(i['course'] or '其他', []).append(i)
            groups = [{'name': k, 'items': v} for k, v in by_course.items()]
        else:
            groups = [{'name': '', 'items': items}]

        all_regs = regs if p['filterby'] == 'all' else \
            env['op.subject.registration'].sudo().search(
                [('student_id', '=', student.id)]) if student else []
        stats = {
            'total': len(all_regs),
            'approved': sum(1 for r in all_regs if r.state == 'approved'),
            'pending': sum(1 for r in all_regs
                           if r.state in ('draft', 'submitted')),
            'rejected': sum(1 for r in all_regs if r.state == 'rejected'),
        }

        course, _batch = student_course(student)
        # 我的已选科目横卡：读在读档案（running 优先）subject_ids → LMS 联动
        subject_cards = []
        if student:
            sc_env = env['op.student.course'].sudo()
            scs = sc_env.search(
                [('student_id', '=', student.id),
                 ('state', '=', 'running')]) or sc_env.search(
                [('student_id', '=', student.id)])
            for sc in scs:
                subs = sc.subject_ids.sorted(key=lambda s: s.name)
                subject_cards.append({
                    'course': sc.course_id.name or '',
                    'batch': sc.batch_id.name or '—',
                    'subject_n': len(subs),
                    'subjects': subs,
                })
        values = {
            'title': '我的选课申请',
            'page_name': 'subject_registration',
            'student': student,
            'sortby': p['sortby'],
            'filterby': p['filterby'],
            'groupby': p['groupby'],
            'search': p['search'],
            'box': box,
            'stats': stats,
            'groups': groups,
            'has_records': bool(items),
            'reg_course': course.name if course else '',
            'subject_cards': subject_cards,
        }
        return request.render('edu_portal.edu_subject_registration', values)

    @http.route('/subject/registration/data/<int:rid>', type='http',
                auth='user', website=True)
    def subject_registration_data(self, rid, **kw):
        """注册单详情（对齐原站 /subject/registration/data//N）。"""
        student = current_student()
        # 安全审计 F2：原写法 "or (student and ...)" 在 student 为 None 时整条件
        # 短路为 False，家长/教师等任何非学生账号都能枚举 rid 读他人注册单。
        # 改为显式判空：非学生身份直接拒绝，学生身份再校验归属。
        if not student:
            return request.redirect('/my/home')
        env = request.env
        r = env['op.subject.registration'].sudo().browse(rid)
        if not r.exists() or r.student_id.id != student.id:
            return request.redirect('/subject/registration')
        subjects = list(r.compulsory_subject_ids) + \
            list(r.elective_subject_ids)
        return request.render('edu_portal.edu_subject_registration_data', {
            'title': (r.name or '注册单') + ' · 注册详情',
            'page_name': 'subject_registration_data',
            'r': r,
            'subjects': subjects,
            'state_label': _SUBJREG_STATE_LABEL.get(r.state, r.state or ''),
        })

    # ------------------------------------------------------------------
    # /requested/queue/list 图书预约队列（op.media.queue，按 partner_id）
    # ------------------------------------------------------------------

    @http.route('/requested/queue/list', type='http', auth='user',
                website=True)
    def requested_queue_list(self, **kw):
        student = current_student()
        p = _nav_params(kw)

        domain = [('partner_id', '=', student.partner_id.id)] if student \
            else [('id', '=', 0)]
        if p['filterby'] and p['filterby'].startswith('state+'):
            domain.append(('state', '=', p['filterby'][6:]))
        if p['search']:
            domain += ['|', ('name', 'ilike', p['search']),
                       ('media_id.name', 'ilike', p['search'])]
        queues = request.env['op.media.queue'].sudo().search(domain)

        items = []
        for q in queues:
            items.append({
                'queue': q,
                'name': q.name or '',
                'media': q.media_id.name if q.media_id else '',
                'media_type': (q.media_id.media_type_id.name
                               if q.media_id and q.media_id.media_type_id
                               else ''),
                'date_from': _fmt_date(q.date_from),
                'date_to': _fmt_date(q.date_to),
                'state': _QUEUE_STATE_LABEL.get(q.state, q.state or ''),
                'state_raw': q.state or '',
                'partner': q.partner_id.name if q.partner_id else '',
            })

        order = {
            'name': lambda i: i['name'],
            'date_from': lambda i: (i['queue'].date_from or
                                    fields.Date.today()),
            'date_to': lambda i: (i['queue'].date_to or fields.Date.today()),
            'state': lambda i: (i['state_raw'], i['name']),
        }.get(p['sortby'] or 'name')
        if order:
            items.sort(key=order)

        groups = []
        if p['groupby'] == 'media_id':
            by_media = {}
            for i in items:
                by_media.setdefault(i['media'] or '其他', []).append(i)
            groups = [{'name': k, 'items': v} for k, v in by_media.items()]
        else:
            groups = [{'name': '', 'items': items}]

        values = {
            'title': '媒体队列列表',
            'page_name': 'requested_queue_list',
            'student': student,
            'sortby': p['sortby'],
            'filterby': p['filterby'],
            'groupby': p['groupby'],
            'search': p['search'],
            'groups': groups,
            'has_records': bool(items),
        }
        return request.render('edu_portal.edu_requested_queue_list', values)

    # ------------------------------------------------------------------
    # /my/time_off 休息时间/请假（edu.leave 自建模型）
    # ------------------------------------------------------------------

    @http.route('/my/time_off', type='http', auth='user', website=True)
    def my_time_off(self, **kw):
        # §5.3（S3）**同一页分流**（不新增页面，也不新增重复路由）：
        #   学生（op.student 非空）     → 学生请假单视图；
        #   教职（student/parent 皆空） → 教职员工请假单视图；
        #   家长（op.parent 非空）      → 既有「为孩子请假」入口 /my/child
        #                               （家长**不算**教职，§5.3 的反例）。
        # 判据只有一份实现：controllers/roles.py:leave_applicant_kind()。
        student = current_student()
        p = _nav_params(kw)
        box = kw.get('box') or ''
        if not student:
            if leave_applicant_kind() == 'staff':
                return self._my_time_off_staff(p, box)
            # 家长（§5.3）：**不算教职**，也**不套学生单** —— 家长在 /my/time_off
            # 看到的是「为孩子请假」，落点就是既有的家长中心 /my/child
            # （那里每个孩子都有 /my/child/<id>/leave 的请假入口，即 §8.1 的
            # 「建学生单」家长路径）。
            # ⚠ 这是**有意行为**，不应改成 200：本页对家长没有可用的提交表单
            #   （/my/time_off/save 在家长身份下会被分流挡回、不落库），给一个
            #   按了没反应的假入口，比直接送到正确入口更差。
            # ⚠ 门禁提示：check_english 的路由状态不变量只放行「跳 /my/home · /web」
            #   的门禁跳转 ⇒ 本行会报 ROUTE-BAD（队长 2026-09-25 已派 S5 把
            #   「/my/time_off → /my/child（家长）」登记进路由表/EXEMPT）。
            return request.redirect('/my/child')

        domain = [('student_id', '=', student.id)]
        if p['filterby'] and p['filterby'] != 'all':
            domain.append(('leave_type', '=', p['filterby']))
        if p['search']:
            domain += ['|', ('name', 'ilike', p['search']),
                       ('reason', 'ilike', p['search'])]
        leaves = request.env['edu.leave'].sudo().search(domain)
        items = _sort_time_off_items(
            [_time_off_item(lv, viewer=student) for lv in leaves], p['sortby'])
        all_leaves = leaves if p['filterby'] == 'all' else \
            request.env['edu.leave'].sudo().search(
                [('student_id', '=', student.id)])

        # 课代表（需求①）：提交请假时的「涉及课程」下拉 = 我自己的科目集
        # （与 /my/courses 同源：op.student.course.subject_ids，见 lms.py:24-30）
        my_subjects = request.env['op.student.course'].sudo().search([
            ('student_id', '=', student.id)]).mapped('subject_ids')

        values = {
            'title': '休假请求列表',
            'page_name': 'time_off',
            'applicant_kind': 'student',
            'is_staff': False,
            'student': student,
            'my_subjects': my_subjects,
            'sortby': p['sortby'],
            'filterby': p['filterby'],
            'groupby': p['groupby'],
            'search': p['search'],
            'box': box,
            'stats': _time_off_stats(all_leaves),
            'items': items,
            'has_records': bool(items),
        }
        return request.render('edu_portal.edu_time_off', values)

    def _my_time_off_staff(self, p, box):
        """教职员工的请假单视图（§5.3 / §8.1「建教职单 = 同一页分流」）。

        数据源 = applicant_user_id == 我（学生单走 student_id，两条路互不混淆）。
        模板优先 edu_portal.edu_time_off_staff（S4 建了这个 template id 就自动
        生效），不存在时回退既有 edu_time_off —— **绝不 500**（并行开发期的
        安全网；回退页仍是 200、数据也是对的，学生表单在教职分支下提交后会
        落成教职单，见 my_time_off_save 的分流）。
        """
        env = request.env
        domain = [('applicant_user_id', '=', env.user.id)]
        if p['filterby'] and p['filterby'] != 'all':
            domain.append(('leave_type', '=', p['filterby']))
        if p['search']:
            domain += ['|', ('name', 'ilike', p['search']),
                       ('reason', 'ilike', p['search'])]
        leaves = env['edu.leave'].sudo().search(domain)
        items = _sort_time_off_items(
            [_time_off_item(lv) for lv in leaves], p['sortby'])
        mine = leaves if p['filterby'] == 'all' else \
            env['edu.leave'].sudo().search(
                [('applicant_user_id', '=', env.user.id)])
        values = {
            'title': '休假请求列表',
            'page_name': 'time_off',
            'applicant_kind': 'staff',
            'is_staff': True,
            'staff_user': env.user,
            'student': False,
            'my_subjects': env['op.subject'].sudo().browse(),
            'sortby': p['sortby'],
            'filterby': p['filterby'],
            'groupby': p['groupby'],
            'search': p['search'],
            'box': box,
            'stats': _time_off_stats(mine),
            'items': items,
            'has_records': bool(items),
        }
        template = ('edu_portal.edu_time_off_staff'
                    if _template_exists('edu_portal.edu_time_off_staff')
                    else 'edu_portal.edu_time_off')
        return request.render(template, values)

    # 2026-10-02 补回丢失的装饰器：本方法**有完整实现、却没有 @http.route** ⇒ 从未注册成路由，
    #   而 views/batch3.xml:638 的「导出 CSV」按钮就指着 /my/time_off/export ⇒ **点下去 404**
    #   （实测 `GET /my/time_off/export` → 404，而 `/my/time_off` → 200）。
    #   发现途径：符号级死代码扫描 —— 「有实现但全仓没人按名字调用」正是「装饰器丢了」的指纹。
    #   口径与同文件同族的 /my/grievances/export、/my/checkins/export 一致（type=http, auth=user）。
    @http.route('/my/time_off/export', type='http', auth='user')
    def my_time_off_export(self, **kw):
        """请假台账 CSV 导出：与列表页同筛选，全量（学生自己的单 / 教职自己的单）。"""
        student = current_student()
        # §5.3（S3）：教职同样能导出自己的台账（否则教职页上的「导出 CSV」
        # 按钮会把用户弹回 /my/home —— 看得见点不动）。
        if not student and leave_applicant_kind() != 'staff':
            return request.redirect('/my/home')
        p = _nav_params(kw)
        domain = [('student_id', '=', student.id)] if student \
            else [('applicant_user_id', '=', request.env.user.id)]
        if p['filterby'] and p['filterby'] != 'all':
            domain.append(('leave_type', '=', p['filterby']))
        if p['search']:
            domain += ['|', ('name', 'ilike', p['search']),
                       ('reason', 'ilike', p['search'])]
        rows = [[
            lv.name or '',
            _LEAVE_TYPE_LABEL.get(lv.leave_type, lv.leave_type or ''),
            _fmt_date(lv.date_from),
            _fmt_date(lv.date_to),
            _leave_days(lv),
            _LEAVE_STATE_LABEL.get(lv.state, lv.state or ''),
            (lv.reason or '').replace('\n', ' '),
        ] for lv in request.env['edu.leave'].sudo().search(
            domain, order='date_from desc, id desc')]
        return csv_download(
            '请假台账_%s.csv' % fields.Date.today().strftime('%Y%m%d'),
            ['单号', '类型', '开始日期', '结束日期', '天数', '状态', '事由'],
            rows)

    # ------------------------------------------------------------------
    # /meeting/information 会议（无社区模型 -> 空态）
    # ------------------------------------------------------------------

    def _zoom_url(self):
        """Zoom 会议链接（系统参数 edu.zoom_url，未配置返回空）。"""
        return request.env['ir.config_parameter'].sudo().get_param(
            'edu.zoom_url') or ''

    @http.route('/meeting/information', type='http', auth='user',
                website=True)
    def meeting_information(self, **kw):
        zoom = self._zoom_url()
        if zoom:
            return request.redirect(zoom, local=False)
        p = _nav_params(kw)
        values = {
            'title': '线上会议',
            'page_name': 'meeting',
            'student': current_student(),
            'sortby': p['sortby'],
            'filterby': p['filterby'],
            'groupby': p['groupby'],
            'search': p['search'],
            'has_records': False,
        }
        return request.render('edu_portal.edu_meeting', values)

    # ------------------------------------------------------------------
    # /online/meeting 在线会议（无社区模型 -> 空态）
    # ------------------------------------------------------------------

    @http.route('/online/meeting', type='http', auth='user', website=True)
    def online_meeting(self, **kw):
        zoom = self._zoom_url()
        if zoom:
            return request.redirect(zoom, local=False)
        p = _nav_params(kw)
        values = {
            'title': 'Zoom 会议',
            'page_name': 'online_meeting',
            'student': current_student(),
            'sortby': p['sortby'],
            'filterby': p['filterby'],
            'groupby': p['groupby'],
            'search': p['search'],
            'has_records': False,
        }
        return request.render('edu_portal.edu_online_meeting', values)



    # ------------------------------------------------------------------
    # /users/result-overview 测验结果（无社区模型 -> 空态）
    # ------------------------------------------------------------------

    def _result_items(self, student):
        """本人成绩行：与 /grade-book 同源（op.marksheet.line → result_line），
        字段供结果下钻与统计使用；无学生或无记录时返回空列表。"""
        if not student:
            return []
        MarksheetLine = request.env['op.marksheet.line'].sudo()
        lines = MarksheetLine.search(
            [('student_id', '=', student.id)],
            order='generated_date desc, id desc')
        items = []
        for ms in lines:
            for rl in ms.result_line:
                ex = rl.exam_id
                total = ex.total_marks or 0
                pct = round(rl.marks / total * 100.0, 2) if total else 0.0
                items.append({
                    'subject': ex.subject_id.name or (ex.name or ''),
                    'exam': ex.name or '',
                    'marks': rl.marks,
                    'total': total,
                    'pct': pct,
                    'pct_str': '%.2f%%' % pct,
                    'status': {'pass': '及格', 'fail': '不及格',
                               }.get(rl.status, '') if rl.status else '',
                    'passed': rl.status == 'pass',
                })
        return items

    @http.route('/users/result-overview', type='http', auth='user',
                website=True)
    def users_result_overview(self, **kw):
        student = current_student()
        p = _nav_params(kw)
        box = kw.get('box') or ''
        items = self._result_items(student)
        # B6 结果下钻：行数据带上本人测验结果页链接 /quiz/<qid>/result/<aid>。
        # 归属校验：edu.quiz.attempt.student_id = 当前学生（op.student.user_id）。
        # 行(考试)与测验无外键，先按名称精确匹配，匹配不到回退到本人最近一次 attempt。
        attempts = []
        if student and 'edu.quiz.attempt' in request.env:
            attempts = request.env['edu.quiz.attempt'].sudo().search(
                [('student_id', '=', student.id)])
        by_name = {}
        for a in attempts:  # _order=create_date desc：setdefault 即最近一次
            by_name.setdefault(a.quiz_id.name, a)
        latest = attempts[:1]
        for i in items:
            a = by_name.get(i['exam']) or latest
            i['attempt_url'] = (
                '/quiz/%d/result/%d' % (a.quiz_id.id, a.id)) if a else ''
        pcts = [float(i['pct_str'].rstrip('%')) for i in items]
        avg = round(sum(pcts) / len(pcts), 2) if pcts else 0.0
        stats = {
            'total': len(items),
            'avg': ('%.2f%%' % avg) if items else '—',
            'passed': sum(1 for i in items if i['status'] == '及格'),
            'failed': sum(1 for i in items if i['status'] == '不及格'),
        }
        values = {
            'title': '测验结果',
            'page_name': 'result_overview',
            'student': student,
            'sortby': p['sortby'],
            'filterby': p['filterby'],
            'groupby': p['groupby'],
            'search': p['search'],
            'box': box,
            'stats': stats,
            'items': items,
            'has_records': bool(items),
        }
        return request.render('edu_portal.edu_result_overview', values)

    # ------------------------------------------------------------------
    # /my/grievances 申诉（edu.grievance 自建模型）
    # ------------------------------------------------------------------

    @http.route('/my/grievances', type='http', auth='user', website=True)
    def my_grievances(self, **kw):
        student = current_student()
        p = _nav_params(kw)
        box = kw.get('box') or ''

        domain = [('student_id', '=', student.id)] if student \
            else [('id', '=', 0)]
        if p['filterby'] and p['filterby'] != 'all':
            domain.append(('state', '=', p['filterby']))
        if p['search']:
            domain += ['|', ('subject', 'ilike', p['search']),
                       ('name', 'ilike', p['search'])]
        grievances = request.env['edu.grievance'].sudo().search(domain)

        items = []
        for g in grievances:
            items.append({
                'grievance': g,
                'name': g.name or '',
                'subject': g.subject or '',
                'category': g.category or '',
                'date': _fmt_date(g.date),
                'state': _GRIEVANCE_STATE_LABEL.get(g.state, g.state or ''),
                'state_raw': g.state or '',
                'description': g.description or '',
            })

        order = {
            'id': lambda i: i['grievance'].id,
            'grievance_category_id': lambda i: (i['category'], i['name']),
        }.get(p['sortby'] or 'id')
        if order:
            items.sort(key=order, reverse=(p['sortby'] == 'id'))

        groups = []
        if p['groupby'] == 'category_id':
            by_cat = {}
            for i in items:
                by_cat.setdefault(i['category'] or '其他', []).append(i)
            groups = [{'name': k, 'items': v} for k, v in by_cat.items()]
        else:
            groups = [{'name': '', 'items': items}]

        all_g = grievances if p['filterby'] == 'all' else \
            request.env['edu.grievance'].sudo().search(
                [('student_id', '=', student.id)]) if student else []
        stats = {
            'total': len(all_g),
            'resolved': sum(1 for g in all_g
                            if g.state in ('resolve', 'close')),
            'pending': sum(1 for g in all_g
                           if g.state in ('draft', 'submitted',
                                          'in_progress')),
            'rejected': sum(1 for g in all_g if g.state == 'reject'),
        }

        values = {
            'title': '申诉',
            'page_name': 'grievances',
            'student': student,
            'sortby': p['sortby'],
            'filterby': p['filterby'],
            'groupby': p['groupby'],
            'search': p['search'],
            'box': box,
            'stats': stats,
            'groups': groups,
            'categories': GRIEVANCE_CATEGORIES,
            'has_records': bool(items),
        }
        return request.render('edu_portal.edu_grievances', values)

    @http.route('/my/grievances/export', type='http', auth='user')
    def my_grievances_export(self, **kw):
        """申诉记录 CSV 导出：与列表页同筛选，全量。"""
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        p = _nav_params(kw)
        domain = [('student_id', '=', student.id)]
        if p['filterby'] and p['filterby'] != 'all':
            domain.append(('state', '=', p['filterby']))
        if p['search']:
            domain += ['|', ('subject', 'ilike', p['search']),
                       ('name', 'ilike', p['search'])]
        rows = [[
            g.name or '',
            g.subject or '',
            g.category or '',
            _fmt_date(g.date),
            _GRIEVANCE_STATE_LABEL.get(g.state, g.state or ''),
            (g.description or '').replace('\n', ' '),
        ] for g in request.env['edu.grievance'].sudo().search(
            domain, order='date desc, id desc')]
        return csv_download(
            '申诉记录_%s.csv' % fields.Date.today().strftime('%Y%m%d'),
            ['单号', '主题', '分类', '日期', '状态', '描述'],
            rows)

    # ------------------------------------------------------------------
    # /my/academic-calendar 学术日历（op.academic.year/term 真实数据）
    # ------------------------------------------------------------------

    @http.route('/my/academic-calendar', type='http', auth='user',
                website=True)
    def my_academic_calendar(self, **kw):
        p = _nav_params(kw)
        env = request.env

        domain = []
        years = env['op.academic.year'].sudo().search(
            domain, order='start_date asc')
        today = fields.Date.today()

        items = []
        for y in years:
            terms = []
            for t in y.academic_term_ids.sorted(
                    key=lambda t: t.term_start_date or today):
                terms.append({
                    'term': t,
                    'name': t.name or '',
                    'start': _fmt_date(t.term_start_date),
                    'end': _fmt_date(t.term_end_date),
                })
            current = bool(y.start_date and y.end_date
                           and y.start_date <= today <= y.end_date)
            items.append({
                'year': y,
                'name': y.name or '',
                'start': _fmt_date(y.start_date),
                'end': _fmt_date(y.end_date),
                'current': current,
                'terms': terms,
            })

        if p['search']:
            items = [i for i in items
                     if p['search'].lower() in i['name'].lower()]
        if p['filterby'] == 'today':
            items = [i for i in items if i['current']]
        if p['sortby'] == 'name':
            items.sort(key=lambda i: i['name'])
        elif p['sortby'] == 'stop_date':
            items.sort(key=lambda i: i['year'].end_date or today)
        else:  # start_date
            items.sort(key=lambda i: i['year'].start_date or today)

        groups = []
        if p['groupby'] == 'start_date':
            by_yr = {}
            for i in items:
                by_yr.setdefault(i['start'] or '—', []).append(i)
            groups = [{'name': k, 'items': v} for k, v in by_yr.items()]
        else:
            groups = [{'name': '', 'items': items}]

        values = {
            'title': '学术日历',
            'page_name': 'academic_calendar',
            'student': current_student(),
            'sortby': p['sortby'],
            'filterby': p['filterby'],
            'groupby': p['groupby'],
            'search': p['search'],
            'groups': groups,
            'has_records': bool(items),
        }
        return request.render('edu_portal.edu_academic_calendar', values)


# ------------------------------------------------------------------
# 收尾三页：DMS / 资产请求 / 论文（骨架 + 空态，对齐原站路由）
# ------------------------------------------------------------------
class EduPortalBatch3Extra(http.Controller):

    def _simple_page(self, title, template, **kw):
        p = _nav_params(kw)
        return request.render(template, {
            'title': title,
            'page_name': template.split('.')[-1],
            'student': current_student(),
            'sortby': p['sortby'],
            'filterby': p['filterby'],
            'groupby': p['groupby'],
            'search': p['search'],
            'has_records': False,
        })

    @http.route('/my/dms', type='http', auth='user', website=True)
    def my_dms(self, **kw):
        return self._simple_page('我的 DMS', 'edu_portal.edu_dms', **kw)

    @http.route('/my/asset-request', type='http', auth='user', website=True)
    def my_asset_request(self, **kw):
        return self._simple_page('资产请求',
                                 'edu_portal.edu_asset_request', **kw)

    @http.route('/my/thesis', type='http', auth='user', website=True)
    def my_thesis(self, **kw):
        return self._simple_page('我的论文', 'edu_portal.edu_thesis', **kw)
