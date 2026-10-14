# -*- coding: utf-8 -*-
"""财务总账 + 报销 · 教务侧控制台（第三期）。

设计：docs/plans/ledger-design.md。

路由（全部新路径，无冲突）：
- GET  /ledger                   总台账：应收/应付一页（筛选/搜索/CSV 导出）
- GET  /ledger/new               记总账：方向/分类/金额/@学生 | @老师 | @班级(拆每人)
- POST /ledger/new/save          批量落库（saved=1 回跳）
- GET  /ledger/reimburse         报销审批台：待批列表 + 详情（收据预览）
- POST /ledger/reimburse/set     写路由：approve(带金额)/refuse(带原因)/pay(付款)

门禁口径（ledger-design §5 权限矩阵；比 enroll 审批先例更严）：
- 本控制台仅 教务/管理员（privileged_staff：教务处组或 system 组）放行；
  普通教师（仅 op.faculty 绑定）与学生/家长一律拦截回 /my/home ——
  总台账/记总账/报销审批/付款登记 是教务专属（矩阵全 ❌ 行）；
- 全部读走 sudo()（门户既有惯例），写操作由控制器判角色把关；
- 学生/老师不能访问审批/记账（负例在冒烟 L12 全绿）。
审计：记账/报销审批/付款均写 edu.audit.log（失败不阻断）。
"""
import logging

from odoo import fields, http
from odoo.http import request

from .main import csv_download
from .roles import privileged_staff

_logger = logging.getLogger(__name__)

_PAGE_SIZE = 50

_DIRECTION_LABEL = {'receivable': '应收', 'payable': '应付'}
# 分类标签不再是常量字典：2026-09-16 起读 edu.fee.category 档案（校方自助增删）
_REIMBURSE_LABEL = {'request': '申请中', 'approved': '已同意待付',
                    'refused': '已驳回', 'paid': '已付款'}
_STATE_LABEL = {'open': '待缴', 'partial': '部分缴纳',
                'paid': '已缴清', 'void': '作废'}
_METHOD_LABEL = {'bank': '银行转账', 'wechat': '微信', 'alipay': '支付宝',
                 'cash': '现金', 'other': '其他'}

def _categories(env, direction='', keep_id=0):
    """表单可选分类（edu.fee.category 档案，校方自助维护）。

    - 只列启用中的；给了 direction 时按「方向倾向」过滤
      （留空=两边都能用，填了=只在该方向出现）；
    - 当前选中项即使已停用也保留，否则筛选栏会莫名跳回「全部」。
    """
    # 实现在模型上（edu.fee.category.selectable），两个控制器共用一份
    return env['edu.fee.category'].sudo().selectable(direction, keep_id)


def _category_domain(param, env):
    """分类筛选参数（分类 id）→ (domain 片段, 选中 id)。非法值一律忽略。"""
    return env['edu.fee.category'].sudo().domain_for(param)


def _resolve_category_id(env, raw, fallback_code='qita'):
    """表单提交的分类参数 → 有效分类 id；找不到则兜底（其他 → 第一个启用项）。

    返回 0 表示一个可用分类都没有（调用方应回跳报错，不要静默丢分类）。
    """
    return env['edu.fee.category'].sudo().resolve_id(raw, fallback_code)


# 报销收据白名单 + 大小上限（设计 §4）
_RECEIPT_EXTS = {'.jpg', '.jpeg', '.png', '.pdf'}
_RECEIPT_MAX_MB = 10


def _fmt_date(d):
    return d.strftime('%Y/%m/%d') if d else ''


def _fmt_dt(rec, dt):
    if not dt:
        return ''
    try:
        return fields.Datetime.context_timestamp(
            rec, dt).strftime('%Y/%m/%d %H:%M')
    except Exception:
        return ''


def _bill_card(b):
    """账单 → 前端展示字典（中文标签 + 收付合计）。"""
    return {
        'id': b.id,
        'name': b.name or '',
        'ref': b.reimburse_ref or '',
        'direction': b.direction or 'receivable',
        'direction_label': _DIRECTION_LABEL.get(
            b.direction, b.direction or ''),
        'category_label': b.category_id.name or '',
        'student': b.student_id.name or '',
        'faculty': b.faculty_id.name or '',
        'partner': b.partner_id.name or '',
        'amount': b.amount,
        'symbol': b.currency_id.symbol or b.currency_id.name or '',
        'paid': b.paid_amount,
        'due': max((b.amount or 0) - (b.paid_amount or 0), 0),
        'state': b.state or 'open',
        'state_label': _STATE_LABEL.get(b.state, b.state or ''),
        'reimburse_state': b.reimburse_state or '',
        'reimburse_label': _REIMBURSE_LABEL.get(
            b.reimburse_state, b.reimburse_state or ''),
        'approved_amount': b.approved_amount,
        'reject_reason': b.reject_reason or '',
        'due_date': _fmt_date(b.due_date),
        'create_date': _fmt_dt(b, b.create_date),
        'creator': b.created_by_partner.name or '',
    }


def _ledger_guard():
    """总账/记账/审批控制台门禁（设计 §5 权限矩阵）。

    记账、审批、付款登记、总台账查看/导出均为 教务/管理员 专属；
    教师（仅 op.faculty 绑定）与学生/家长一律拒绝——矩阵行
    「学生/老师 记总账/审批/付款/总台账 = ❌」优先于 enroll 先例里
    宽松的 current_faculty() or privileged_staff() 写法（enroll 的
    「审批」是教务动作，此处沿用 roles.privileged_staff 语义）。
    """
    return bool(privileged_staff())


class EduLedgerPortal(http.Controller):

    # ------------------------------------------------------------------
    # 总台账 /ledger
    # ------------------------------------------------------------------
    @http.route('/ledger', type='http', auth='user', website=True)
    def ledger(self, **kw):
        if not _ledger_guard():
            return request.redirect('/my/home')
        env = request.env
        Bill = env['edu.fee.bill'].sudo()

        direction = kw.get('direction') or ''
        category = kw.get('category') or ''
        actor = (kw.get('actor') or '').strip()
        state = kw.get('state') or ''
        reimburse = kw.get('reimburse') or ''
        search = (kw.get('search') or '').strip()
        page = max(1, int(kw.get('page', 1) or 1))

        domain = []
        if direction in ('receivable', 'payable'):
            domain.append(('direction', '=', direction))
        cat_dom, cat_sel = _category_domain(category, env)
        domain += cat_dom
        if state in _STATE_LABEL:
            domain.append(('state', '=', state))
        if reimburse in _REIMBURSE_LABEL:
            domain.append(('reimburse_state', '=', reimburse))
        if actor:
            domain += ['|', '|', '|',
                       ('student_id.name', 'ilike', actor),
                       ('faculty_id.name', 'ilike', actor),
                       ('partner_id.name', 'ilike', actor),
                       ('created_by_partner.name', 'ilike', actor)]
        if search:
            domain += ['|', '|',
                       ('name', 'ilike', search),
                       ('reimburse_ref', 'ilike', search),
                       ('source_ref', 'ilike', search)]

        total = Bill.search_count(domain)
        bills = Bill.search(domain, order='create_date desc, id desc',
                            limit=_PAGE_SIZE,
                            offset=(page - 1) * _PAGE_SIZE)

        # 汇总卡（全部可见筛选域上的统计）：
        # - 应收未收 = receivable 且 open/partial 的（金额 - 已收付）合计；
        # - 应付待付 = payable 且 open/partial 的（金额 - 已收付）合计；
        #   口径（2026-09-16 两次修正后）：
        #     · 手工应付账单（reimburse_state 为空）→ 计；
        #     · 报销单 request（待批）/ approved → 计（钱已由他人垫付）；
        #     · refused（已驳回）→ 不计（义务不成立）。
        #   旧口径只认 approved ⇒ 手工记的应付账在汇总卡恒为 0：台账明细里有、
        #   汇总卡里没有，是最坏的一类不一致（用户那条 ¥850 接待费即此）。
        recv_due = pay_due = 0.0
        stat_bills = Bill.search(domain, order='id desc') \
            if len(bills) < total else bills
        for b in stat_bills:
            if b.state not in ('open', 'partial'):
                continue
            bal = max((b.amount or 0) - (b.paid_amount or 0), 0)
            if b.direction == 'payable':
                # 未付清的应付都要算，含**待批报销**（request）——钱多半已经
                # 由某人垫出去了，学校迟早要还，漏掉会让校长看到假的 ¥0。
                # 只排除「已驳回」（义务不成立）。
                if b.reimburse_state != 'refused':
                    pay_due += bal
            else:
                recv_due += bal

        cards = [_bill_card(b) for b in bills]
        from odoo.addons.portal.controllers.portal import pager
        return request.render('edu_portal.edu_ledger', {
            # 币种符号由 res.currency 决定，模板不再硬编码 ¥/$（t5 币种统一）
            'cur_symbol': (request.env.company.currency_id.symbol
                           or request.env.company.currency_id.name or ''),
            'title': '财务总台账',
            'page_name': 'ledger',
            'bills': cards,
            'total': total,
            'recv_due': recv_due,
            'pay_due': pay_due,
            'direction': direction,
            'category': category,
            'actor': actor,
            'state': state,
            'reimburse': reimburse,
            'search': search,
            'direction_label': _DIRECTION_LABEL,
            'categories': _categories(env, direction, cat_sel),
            'category_sel': cat_sel,
            'state_label': _STATE_LABEL,
            'reimburse_label': _REIMBURSE_LABEL,
            'page': page,
            'pager': pager('/ledger', total=total, page=page,
                           step=_PAGE_SIZE,
                           url_args={'direction': direction,
                                     'category': category, 'actor': actor,
                                     'state': state, 'reimburse': reimburse,
                                     'search': search}),
        })

    @http.route('/ledger/export', type='http', auth='user')
    def ledger_export(self, **kw):
        """总台账 CSV 导出：同筛选口径（教务/管理员专用）。"""
        if not _ledger_guard():
            return request.redirect('/my/home')
        env = request.env
        Bill = env['edu.fee.bill'].sudo()
        domain = []
        direction = kw.get('direction') or ''
        category = kw.get('category') or ''
        actor = (kw.get('actor') or '').strip()
        state = kw.get('state') or ''
        reimburse = kw.get('reimburse') or ''
        search = (kw.get('search') or '').strip()
        if direction in ('receivable', 'payable'):
            domain.append(('direction', '=', direction))
        cat_dom, cat_sel = _category_domain(category, env)
        domain += cat_dom
        if state in _STATE_LABEL:
            domain.append(('state', '=', state))
        if reimburse in _REIMBURSE_LABEL:
            domain.append(('reimburse_state', '=', reimburse))
        if actor:
            domain += ['|', '|', '|',
                       ('student_id.name', 'ilike', actor),
                       ('faculty_id.name', 'ilike', actor),
                       ('partner_id.name', 'ilike', actor),
                       ('created_by_partner.name', 'ilike', actor)]
        if search:
            domain += ['|', '|',
                       ('name', 'ilike', search),
                       ('reimburse_ref', 'ilike', search),
                       ('source_ref', 'ilike', search)]
        bills = Bill.search(domain, order='create_date desc, id desc')
        rows = []
        for b in bills:
            rows.append([
                b.reimburse_ref or '',
                b.name or '',
                _DIRECTION_LABEL.get(b.direction, b.direction or ''),
                b.category_id.name or '',
                b.student_id.name or '',
                b.faculty_id.name or '',
                b.partner_id.name or '',
                '%.2f' % (b.amount or 0),
                '%.2f' % (b.paid_amount or 0),
                '%.2f' % max((b.amount or 0) - (b.paid_amount or 0), 0),
                _STATE_LABEL.get(b.state, b.state or ''),
                _REIMBURSE_LABEL.get(b.reimburse_state, '') \
                    if b.reimburse_state else '',
                '%s' % (b.approved_amount or ''),
                b.reject_reason or '',
                _fmt_date(b.due_date),
                _fmt_dt(b, b.create_date),
            ])
        return csv_download(
            '总台账_%s.csv' % fields.Date.today().strftime('%Y%m%d'),
            ['报销单号', '账单', '方向', '分类', '学生', '教师', '受理人',
             '金额', '已收付', '余额', '账单状态', '报销状态', '同意金额',
             '驳回原因', '截止', '创建时间'],
            rows)

    # ------------------------------------------------------------------
    # 记总账 /ledger/new + /ledger/new/save
    # ------------------------------------------------------------------
    def _ledger_form_values(self):
        env = request.env
        students = env['op.student'].sudo().search(
            [], order='name asc')
        faculties = env['op.faculty'].sudo().search([],
                                                    order='last_name asc')
        batches = env['op.batch'].sudo().search(
            [('active', '=', True)], order='name asc')
        # 班级候选：包装成 (id, name, 学生数)
        batch_opts = []
        for b in batches:
            scs = env['op.student.course'].sudo().search(
                [('batch_id', '=', b.id), ('state', '=', 'running')])
            batch_opts.append({
                'id': b.id, 'name': b.name or '',
                'n': len(scs),
                'students': scs.mapped('student_id'),
            })
        return {
            'students': students,
            'faculties': faculties,
            'batch_opts': batch_opts,
            'categories': _categories(env),
            'direction_label': _DIRECTION_LABEL,
        }

    @http.route('/ledger/new', type='http', auth='user', website=True)
    def ledger_new(self, **kw):
        if not _ledger_guard():
            return request.redirect('/my/home')
        values = self._ledger_form_values()
        values.update({
            'title': '记总账',
            'page_name': 'ledger_new',
            'box': kw.get('box') or '',
        })
        return request.render('edu_portal.edu_ledger_new', values)

    @http.route('/ledger/new/save', type='http', auth='user', website=True,
                methods=['POST'], csrf=True)
    def ledger_new_save(self, **post):
        if not _ledger_guard():
            return request.redirect('/my/home')
        env = request.env
        form = request.httprequest.form
        direction = form.get('direction') or 'receivable'
        category = form.get('category') or ''
        try:
            amount = float(form.get('amount') or 0)
        except (TypeError, ValueError):
            amount = 0
        if direction not in ('receivable', 'payable'):
            direction = 'receivable'
        cat_id = _resolve_category_id(env, category)
        if not cat_id:
            return request.redirect('/ledger/new?box=bad_category')
        if amount <= 0:
            return request.redirect('/ledger/new?box=bad_amount')
        name = (form.get('name') or '').strip()[:200]
        if not name:
            name = '手工记账'
        due_str = (form.get('due_date') or '').strip()
        due_date = False
        if due_str:
            try:
                due_date = fields.Date.to_date(due_str)
            except (TypeError, ValueError):
                due_date = False
        note = (form.get('note') or '').strip()[:1000]
        actor_type = form.get('actor_type') or 'student'
        try:
            actor_id = int(form.get('actor_id') or 0)
        except (TypeError, ValueError):
            actor_id = 0

        Bill = env['edu.fee.bill'].sudo()
        created = 0
        partner = env.user.partner_id.sudo()

        if actor_type == 'student':
            stu = env['op.student'].sudo().browse(actor_id)
            if not stu.exists():
                return request.redirect('/ledger/new?box=bad_actor')
            Bill.create({
                'name': name,
                'direction': direction,
                'category_id': cat_id,
                'amount': amount,
                'student_id': stu.id,
                'partner_id': stu.partner_id.id if stu.partner_id else False,
                'due_date': due_date,
                'note': note,
                'created_by_partner': partner.id,
            })
            created = 1
        elif actor_type == 'faculty':
            fac_rec = env['op.faculty'].sudo().browse(actor_id)
            if not fac_rec.exists():
                return request.redirect('/ledger/new?box=bad_actor')
            Bill.create({
                'name': name,
                'direction': direction,
                'category_id': cat_id,
                'amount': amount,
                'faculty_id': fac_rec.id,
                'partner_id': fac_rec.partner_id.id
                if fac_rec.partner_id else False,
                'due_date': due_date,
                'note': note,
                'created_by_partner': partner.id,
            })
            created = 1
        elif actor_type == 'batch':
            batch = env['op.batch'].sudo().browse(actor_id)
            if not batch.exists():
                return request.redirect('/ledger/new?box=bad_actor')
            scs = env['op.student.course'].sudo().search(
                [('batch_id', '=', batch.id), ('state', '=', 'running')])
            students = scs.mapped('student_id')
            if not students:
                return request.redirect('/ledger/new?box=no_students')
            vals_list = []
            parent_ref = '批量:%s' % (batch.name or '')
            for stu in students:
                vals_list.append({
                    'name': '%s（%s）' % (name, stu.name or ''),
                    'direction': direction,
                    'category_id': cat_id,
                    'amount': amount,
                    'student_id': stu.id,
                    'partner_id': stu.partner_id.id if stu.partner_id else False,
                    'due_date': due_date,
                    'note': note,
                    'source_ref': parent_ref,
                    'created_by_partner': partner.id,
                })
            Bill.create(vals_list)
            created = len(vals_list)
        else:
            return request.redirect('/ledger/new?box=bad_actor')

        env['edu.audit.log'].sudo()._log(
            '记账', 'edu.fee.bill', 0,
            '%s %s' % (_DIRECTION_LABEL.get(direction, ''), name),
            '%s · %s元 · 生成 %d 笔' % (
                _DIRECTION_LABEL.get(direction, ''),
                '%.2f' % amount, created))
        return request.redirect('/ledger/new?box=saved&count=%d' % created)

    # ------------------------------------------------------------------
    # 报销审批台 /ledger/reimburse + /ledger/reimburse/set
    # ------------------------------------------------------------------
    @http.route('/ledger/reimburse', type='http', auth='user', website=True)
    def ledger_reimburse(self, **kw):
        if not _ledger_guard():
            return request.redirect('/my/home')
        env = request.env
        Bill = env['edu.fee.bill'].sudo()
        filterby = kw.get('filterby') or 'request'
        search = (kw.get('search') or '').strip()
        page = max(1, int(kw.get('page', 1) or 1))
        domain = [('direction', '=', 'payable'),
                  ('reimburse_state', '!=', False)]
        if filterby in ('request', 'approved', 'paid', 'refused'):
            domain.append(('reimburse_state', '=', filterby))
        if search:
            domain += ['|', '|', '|',
                       ('reimburse_ref', 'ilike', search),
                       ('name', 'ilike', search),
                       ('student_id.name', 'ilike', search),
                       ('created_by_partner.name', 'ilike', search)]
        total = Bill.search_count(domain)
        bills = Bill.search(domain, order='create_date desc, id desc',
                            limit=_PAGE_SIZE,
                            offset=(page - 1) * _PAGE_SIZE)
        stats = {}
        for st_ in ('request', 'approved', 'paid', 'refused'):
            stats[st_] = Bill.search_count(
                [('direction', '=', 'payable'),
                 ('reimburse_state', '=', st_)])
        cards = []
        for b in bills:
            rec = _bill_card(b)
            rec['attachments'] = b.receipt_attachment_ids
            rec['creator_partner'] = b.created_by_partner
            rec['approved_label'] = '%s' % (
                b.approved_amount if b.approved_amount is not False else '')
            cards.append(rec)
        from odoo.addons.portal.controllers.portal import pager
        return request.render('edu_portal.edu_ledger_reimburse', {
            # 币种符号由 res.currency 决定，模板不再硬编码 ¥/$（t5 币种统一）
            'cur_symbol': (request.env.company.currency_id.symbol
                           or request.env.company.currency_id.name or ''),
            'title': '报销审批',
            'page_name': 'ledger_reimburse',
            'bills': cards,
            'total': total,
            'stats': stats,
            'filterby': filterby,
            'search': search,
            'reimburse_label': _REIMBURSE_LABEL,
            'method_label': _METHOD_LABEL,
            'page': page,
            'pager': pager('/ledger/reimburse', total=total, page=page,
                           step=_PAGE_SIZE,
                           url_args={'filterby': filterby, 'search': search}),
        })

    @http.route('/ledger/reimburse/set', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def ledger_reimburse_set(self, **post):
        if not _ledger_guard():
            return request.redirect('/my/home')
        env = request.env
        form = request.httprequest.form
        try:
            bill_id = int(form.get('bill_id') or 0)
        except (TypeError, ValueError):
            bill_id = 0
        action = form.get('action') or ''
        bill = env['edu.fee.bill'].sudo().browse(bill_id)
        if not bill.exists():
            return request.redirect('/ledger/reimburse')
        try:
            if action == 'approve':
                amount = form.get('approved_amount') or ''
                if amount == '' or amount is None:
                    bill.action_reimburse_approve()
                else:
                    try:
                        bill.action_reimburse_approve(float(amount))
                    except (TypeError, ValueError):
                        return request.redirect(
                            '/ledger/reimburse?box=bad_amount')
            elif action == 'refuse':
                reason = (form.get('reject_reason') or '').strip()
                if not reason:
                    return request.redirect(
                        '/ledger/reimburse?box=need_reason')
                bill.action_reimburse_refuse(reason)
            elif action == 'pay':
                bill.action_pay(
                    method=form.get('method') or 'bank',
                    payment_date=None,
                    note=(form.get('note') or '').strip()[:200])
            else:
                return request.redirect('/ledger/reimburse')
        except Exception as exc:
            _logger.warning('reimburse set failed bill=%s action=%s err=%s',
                            bill_id, action, exc)
            return request.redirect(
                '/ledger/reimburse?box=%s' % action)
        next_url = form.get('next') or ''
        if not next_url.startswith('/ledger/reimburse'):
            next_url = '/ledger/reimburse'
        return request.redirect(next_url)