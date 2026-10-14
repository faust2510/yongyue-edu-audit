# -*- coding: utf-8 -*-
"""财务门户（/my/fees + /my/reimburse/apply）：双向台账·学生/教师视角。

- /my/fees：同页显示 统筹费应收（既有）+ 我的报销申请（含状态/驳回原因/收据）；
  学生看自己、家长看孩子、教师看自己的报销、内部只读总览。
- /my/reimburse/apply(+save)：学生/教师发起报销申请（request），
  分类必选、金额必填、收据 jpg/png/pdf ≤10MB、防重、csrf。
  （设计 docs/plans/ledger-design.md §2/§4；写操作走兄弟路由 + csrf。）
"""
import base64
import logging

from odoo import fields, http
from odoo.http import content_disposition, request

from .main import csv_download, current_student
from .roles import current_faculty, current_parent

_logger = logging.getLogger(__name__)

_BILL_STATE_LABEL = {'open': '待缴', 'partial': '部分缴纳',
                     'paid': '已缴清', 'void': '作废'}
_REIMBURSE_LABEL = {'request': '申请中', 'approved': '已同意待付',
                    'refused': '已驳回', 'paid': '已付款'}
# 分类标签不再是常量字典：2026-09-16 起读 edu.fee.category 档案（校方自助增删）
_RECEIPT_EXTS = {'.jpg', '.jpeg', '.png', '.pdf'}
_RECEIPT_MAX_BYTES = 10 * 1024 * 1024


def _bill_card(b):
    return {
        'id': b.id,
        'name': b.name or '',
        'ref': b.reimburse_ref or '',
        'direction': b.direction or 'receivable',
        'direction_label': '应收' if b.direction != 'payable' else '应付',
        'category_label': b.category_id.name or '',
        'student': b.student_id.name or '',
        'faculty': b.faculty_id.name or '',
        'amount': b.amount,
        'symbol': b.currency_id.symbol or b.currency_id.name or '',
        'paid': b.paid_amount,
        'due': max((b.amount or 0) - (b.paid_amount or 0), 0),
        'state': b.state or 'open',
        'state_label': _BILL_STATE_LABEL.get(b.state, b.state or ''),
        'reimburse_state': b.reimburse_state or '',
        'reimburse_label': _REIMBURSE_LABEL.get(
            b.reimburse_state, b.reimburse_state or ''),
        'approved_amount': b.approved_amount,
        'reject_reason': b.reject_reason or '',
        'due_date': b.due_date,
        'create_date': b.create_date,
        'creator': b.created_by_partner.name or '',
        'attachments': b.receipt_attachment_ids,
    }


class EduFeesPortal(http.Controller):

    @http.route('/my/fees', type='http', auth='user', website=True)
    def my_fees(self, **kw):
        env = request.env
        student = current_student()
        fac = current_faculty()
        parent = current_parent()
        Bill = env['edu.fee.bill'].sudo()

        sections = []          # 家长视角：按孩子分组
        if parent:
            role, title = 'parent', '孩子的账单'
            for stu in parent.student_ids:
                bills = Bill.search([('student_id', '=', stu.id)],
                                    order='due_date desc, id desc')
                # 家长欠款只算 应收（应收欠款；应付=报销不属家长负担）
                sections.append({
                    'student': stu,
                    'bills': [_bill_card(b) for b in bills],
                    'due': sum(b.amount - b.paid_amount for b in bills
                               if b.direction == 'receivable'
                               and b.state in ('open', 'partial')),
                })
            bills = Bill.browse(())
        elif student:
            role, title = 'student', '我的账单'
            # 统筹费应收按 student_id；我的报销按发起人 partner（门户账号）或学生档案 partner
            bills = Bill.search(
                ['|', '|',
                 ('student_id', '=', student.id),
                 ('created_by_partner', '=', env.user.partner_id.id),
                 ('created_by_partner', '=', student.partner_id.id)],
                order='due_date desc, id desc')
        elif fac or env.user.has_group('base.group_user'):
            # 教师：只显示与自己相关的账单/报销（应付给本人 或 以本人为受理人/发起人）
            fac_rec = fac
            if fac_rec:
                role, title = 'faculty', '我的账单与报销'
                bills = Bill.search(
                    ['|',
                     ('created_by_partner', '=', fac_rec.partner_id.id),
                     ('partner_id', '=', fac_rec.partner_id.id)],
                    order='due_date desc, id desc')
            else:
                role, title = 'staff', '全部账单（只读）'
                bills = Bill.search([], order='due_date desc, id desc',
                                    limit=100)
        else:
            role, title = 'guest', '账单'
            bills = Bill.browse(())

        # 学生待缴合计 = 只算 应收（统筹费/教材/罚款等）；
        # 应付（报销）不是学生欠款，不计入
        due_total = sum(b.amount - b.paid_amount for b in bills
                        if b.direction == 'receivable'
                        and b.state in ('open', 'partial'))
        # 渲染用卡片字典（模板按字典访问；家长 sections 已转字典）
        bill_cards = [_bill_card(b) for b in bills]
        recv_cards = [b for b in bill_cards if b['direction'] != 'payable']
        pay_cards = [b for b in bill_cards if b['direction'] == 'payable']
        return request.render('edu_portal.edu_fees_page', {
            # 币种符号由 res.currency 决定，模板不再硬编码 ¥/$（t5 币种统一）
            'cur_symbol': (env.company.currency_id.symbol
                           or env.company.currency_id.name or ''),
            'title': title,
            'role': role,
            'sections': sections,
            'bills': bill_cards,
            'recv_bills': recv_cards,
            'pay_bills': pay_cards,
            'recv_count': len(recv_cards),
            'pay_count': len(pay_cards),
            'due_total': due_total,
            'reimburse_label': _REIMBURSE_LABEL,
            'categories': env['edu.fee.category'].sudo().selectable('payable'),
            'page_name': 'fees',
        })

    @http.route('/my/fees/export', type='http', auth='user')
    def my_fees_export(self, **kw):
        """账单 CSV 导出：与页面同视角（学生本人/家长按孩子/内部全量）。"""
        env = request.env
        student = current_student()
        fac = current_faculty()
        parent = current_parent()
        Bill = env['edu.fee.bill'].sudo()
        bills = Bill.browse(())
        if parent:
            for stu in parent.student_ids:
                bills |= Bill.search([('student_id', '=', stu.id)],
                                     order='due_date desc, id desc')
        elif student:
            bills = Bill.search(
                ['|',
                 ('student_id', '=', student.id),
                 ('created_by_partner', '=', student.partner_id.id)],
                order='due_date desc, id desc')
        elif fac or env.user.has_group('base.group_user'):
            fac_rec = fac
            if fac_rec:
                bills = Bill.search(
                    ['|',
                     ('created_by_partner', '=', fac_rec.partner_id.id),
                     ('partner_id', '=', fac_rec.partner_id.id)],
                    order='due_date desc, id desc', limit=200)
            else:
                bills = Bill.search([], order='due_date desc, id desc',
                                    limit=100)
        else:
            return request.redirect('/my/home')
        rows = []
        for b in bills:
            rows.append([
                b.name or '',
                b.student_id.name or '',
                '应收' if b.direction != 'payable' else '应付',
                b.category_id.name or '',
                '%.2f' % (b.amount or 0),
                '%.2f' % (b.paid_amount or 0),
                '%.2f' % max((b.amount or 0) - (b.paid_amount or 0), 0),
                _BILL_STATE_LABEL.get(b.state, b.state or ''),
                _REIMBURSE_LABEL.get(b.reimburse_state, '') \
                    if b.reimburse_state else '',
                fields.Date.to_string(b.due_date) if b.due_date else '',
            ])
        return csv_download(
            '缴费账单_%s.csv' % fields.Date.today().strftime('%Y%m%d'),
            ['账单', '学生', '方向', '分类', '金额', '已收付', '余额', '状态',
             '报销状态', '截止日期'],
            rows)

    # ------------------------------------------------------------------
    # 收据受控预览：/my/reimburse/receipt/<bill>/<att>
    # ------------------------------------------------------------------
    @http.route('/my/reimburse/receipt/<int:bill_id>/<int:att_id>',
                type='http', auth='user', website=True)
    def reimburse_receipt(self, bill_id, att_id, **kw):
        """按身份校验的收据预览（设计 §4：public=False 的受控入口）。

        仅 申请人本人（created_by_partner.user_ids）或 教务/管理员 可看；
        校验通过后以 sudo 读附件数据，经 /web/binary/saveas 同款头部渲染
        （图片/pdf 走 inline 预览）。越权统一 404，不泄露存在性。
        """
        env = request.env
        bill = env['edu.fee.bill'].sudo().browse(bill_id)
        if not bill.exists() or not bill._user_can_view_receipt():
            return request.not_found()
        att = env['ir.attachment'].sudo().browse(att_id)
        if not att.exists() or att.id not in bill.receipt_attachment_ids.ids:
            return request.not_found()
        data = base64.b64decode(att.datas or b'')
        if not data:
            return request.not_found()
        fname = att.name or 'receipt'
        ctype = att.mimetype or 'application/octet-stream'
        inline = kw.get('inline') == '1' and (
            (att.mimetype or '').startswith('image/')
            or (att.mimetype or '') == 'application/pdf')
        # 复用 Odoo 的 content_disposition（RFC5987 中文名安全），
        # 按预览/下载改写前置处置词（inline / attachment）。
        disp = content_disposition(fname)
        if inline and disp.startswith('attachment;'):
            disp = 'inline;' + disp[len('attachment;'):]
        return request.make_response(data, headers=[
            ('Content-Type', ctype),
            ('Content-Disposition', disp),
            ('Content-Length', str(len(data))),
        ])

    # ------------------------------------------------------------------
    # 报销申请：/my/reimburse/apply + /my/reimburse/apply/save
    # ------------------------------------------------------------------
    @http.route('/my/reimburse/apply', type='http', auth='user', website=True)
    def reimburse_apply(self, **kw):
        student = current_student()
        fac = current_faculty()
        if not student and not fac:
            return request.redirect('/my/home')
        env = request.env
        # 我的历史报销（防重：同一申请人在途同分类全等金额只提醒一次）
        Bill = env['edu.fee.bill'].sudo()
        partner = env.user.partner_id.sudo()
        dup = False
        if kw.get('box') == 'dup':
            dup = True
        return request.render('edu_portal.edu_reimburse_apply', {
            'title': '发起报销',
            'page_name': 'reimburse_apply',
            'is_student': bool(student),
            'is_faculty': bool(fac),
            'partner': partner,
            'categories': env['edu.fee.category'].sudo().selectable('payable'),
            'dup': dup,
            'box': kw.get('box') or '',
        })

    @http.route('/my/reimburse/apply/save', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def reimburse_apply_save(self, **post):
        student = current_student()
        fac = current_faculty()
        if not student and not fac:
            return request.redirect('/my/home')
        env = request.env
        form = request.httprequest.form

        cat_id = env['edu.fee.category'].sudo().resolve_id(
            form.get('category'))
        if not cat_id:
            return request.redirect('/my/reimburse/apply?box=bad_category')
        try:
            amount = float(form.get('amount') or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            return request.redirect('/my/reimburse/apply?box=bad_amount')
        name = (form.get('name') or '').strip()[:200]
        if not name:
            name = '报销申请'
        note = (form.get('note') or '').strip()[:1000]

        # 防重（grilling #2 分类必选；同人/同分类/同金额在途单拦截）
        # 发起人身份统一用当前门户账号 partner（入库 created_by_partner 同源）
        partner = env.user.partner_id.sudo()
        Bill = env['edu.fee.bill'].sudo()
        dup_domain = [
            ('direction', '=', 'payable'),
            ('category_id', '=', cat_id),
            ('amount', '=', amount),
            ('reimburse_state', 'in', ('request', 'approved')),
            ('created_by_partner', '=', partner.id),
        ]
        if Bill.search_count(dup_domain):
            return request.redirect('/my/reimburse/apply?box=dup')

        # 收据附件（可选多文件，白名单 + 10MB）
        # public=False：不开放匿名/任意登录用户直读，预览一律走
        # /my/reimburse/receipt/<bill_id>/<att_id> 受控路由（身份校验）。
        # 健壮性：ir.attachment.create 会对 image/* 走 Odoo 的
        # _postprocess_contents → PIL.Image.open 尝试解码，损坏图片会抛
        # UnicodeDecodeError/OSError 等（Odoo 内部只捕 UserError）→ 未捕获
        # 即 HTTP 500。此处兜住解码异常并回中文提示；因 _check_contents
        # 在建行之前执行，捕获时不会残留半截附件。
        att_ids = []
        files = request.httprequest.files.getlist('receipts')
        for f in files:
            if not f.filename:
                continue
            name_l = f.filename.lower()
            if not any(name_l.endswith(ext) for ext in _RECEIPT_EXTS):
                return request.redirect('/my/reimburse/apply?box=bad_type')
            data = f.read()
            if len(data) > _RECEIPT_MAX_BYTES:
                return request.redirect('/my/reimburse/apply?box=too_big')
            try:
                att = env['ir.attachment'].sudo().create({
                    'name': f.filename[:128],
                    'datas': base64.b64encode(data).decode(),
                    'mimetype': f.mimetype or 'application/octet-stream',
                    'public': False,   # 受控预览（见 receipt 路由）
                })
            except Exception as exc:  # noqa: BLE001
                _logger.warning('reimburse receipt rejected (undecodable) '
                                'name=%s mime=%s bytes=%d err=%s',
                                f.filename, f.mimetype, len(data), exc)
                return request.redirect('/my/reimburse/apply?box=bad_image')
            att_ids.append(att.id)

        partner_id = partner.id
        vals = {
            'name': name,
            'direction': 'payable',
            'category_id': cat_id,
            'amount': amount,
            'currency_id': env.company.currency_id.id,
            'due_date': fields.Date.today(),
            'note': note,
            'created_by_partner': partner_id,
            'partner_id': partner_id,
            'student_id': student.id if student else False,
            'reimburse_state': 'request',
            'approved_amount': amount,
        }
        if fac:
            vals['faculty_id'] = fac.id
            vals['partner_id'] = fac.partner_id.id if fac.partner_id \
                else partner_id
        if att_ids:
            vals['receipt_attachment_ids'] = [(6, 0, att_ids)]
        bill = Bill.create(vals)

        env['edu.audit.log'].sudo()._log(
            '报销申请', 'edu.fee.bill', bill.id,
            bill.reimburse_ref or bill.name or '',
            '%s · %s · 金额 %.2f · 收据 %d' % (
                bill.category_id.name or '',
                '学生' if student else '教师', amount, len(att_ids)))
        return request.redirect(
            '/my/fees?box=reimburse_submitted&ref=%s' %
            (bill.reimburse_ref or ''))
