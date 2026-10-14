# -*- coding: utf-8 -*-
"""永约学坊公开页面路由：学院概况 / 招生信息 / 校刊在线阅读。"""
from odoo import http
from odoo.http import request

JOURNAL_TOTAL = 33


class EduBrandPublic(http.Controller):

    @http.route('/about', type='http', auth='public', website=True)
    def about(self, **kw):
        return request.render('edu_brand.edu_about', {})

    @http.route('/programs', type='http', auth='public', website=True)
    def programs(self, **kw):
        return request.render('edu_brand.edu_programs', {})

    @http.route('/admissions', type='http', auth='public', website=True)
    def admissions(self, **kw):
        return request.render('edu_brand.edu_admissions', {})

    @http.route('/journal', type='http', auth='public', website=True)
    def journal(self, **kw):
        pages = [{'no': n, 'src': '/edu_brand/static/src/journal/scrts-2025-10/pages/page-%03d.webp' % n}
                 for n in range(1, JOURNAL_TOTAL + 1)]
        return request.render('edu_brand.edu_journal', {
            'pages': pages,
            'total': JOURNAL_TOTAL,
        })

    @http.route('/journal/page/<int:page_no>', type='http',
                auth='public', website=True)
    def journal_page(self, page_no, **kw):
        if page_no < 1 or page_no > JOURNAL_TOTAL:
            return request.redirect('/journal')
        return request.render('edu_brand.edu_journal_reader', {
            'page_no': page_no,
            'src': '/edu_brand/static/src/journal/scrts-2025-10/pages/page-%03d.webp' % page_no,
            'prev_no': page_no - 1 if page_no > 1 else 0,
            'next_no': page_no + 1 if page_no < JOURNAL_TOTAL else 0,
            'total': JOURNAL_TOTAL,
        })
