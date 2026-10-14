# -*- coding: utf-8 -*-
"""资产借还门户：/my/assets 我的借还 + 申请借用表单。"""
from odoo import http
from odoo.http import request

from .main import current_student
from .roles import current_parent


class EduAssetsPortal(http.Controller):

    def _my_loans(self, student):
        return request.env['edu.asset.loan'].sudo().search(
            [('student_id', '=', student.id)],
            order='requested_date desc, id desc')

    @http.route('/my/assets', type='http', auth='user', website=True)
    def my_assets(self, applied=None, **kw):
        env = request.env
        student = current_student()
        parent = current_parent()
        if not student and not parent:
            return request.redirect('/my/home')

        loans = env['edu.asset.loan'].sudo().browse(())
        if student:
            loans = self._my_loans(student)
        elif parent:
            loans = env['edu.asset.loan'].sudo().search(
                [('student_id', 'in', parent.student_ids.ids)],
                order='requested_date desc, id desc')

        available = env['edu.asset'].sudo().search(
            [('state', '=', 'available')], order='category, name')
        return request.render('edu_portal.edu_assets_page', {
            'title': '资产借还',
            'role': 'parent' if (parent and not student) else 'student',
            'loans': loans,
            'available': available,
            'applied': bool(applied),
            'page_name': 'assets',
        })

    @http.route('/my/assets/apply', type='http', methods=['POST'],
                auth='user', website=True, csrf=True)
    def asset_apply(self, **post):
        student = current_student()
        if not student:
            return request.redirect('/my/assets')
        try:
            asset_id = int(post.get('asset_id', 0))
        except ValueError:
            asset_id = 0
        asset = request.env['edu.asset'].sudo().browse(asset_id)
        if not asset.exists() or asset.state != 'available':
            return request.redirect('/my/assets?error=unavailable')
        Loan = request.env['edu.asset.loan'].sudo()
        dup = Loan.search([('student_id', '=', student.id),
                           ('asset_id', '=', asset.id),
                           ('state', 'in', ('requested', 'borrowed'))],
                          limit=1)
        if dup:
            return request.redirect('/my/assets?error=dup')
        Loan.create({
            'asset_id': asset.id,
            'student_id': student.id,
            'requested_note': (post.get('note') or '')[:200],
        })
        return request.redirect('/my/assets?applied=1')
