# -*- coding: utf-8 -*-
"""站内帮助中心：/help 四角色公开使用指南（免登录可读）。

五个纯静态页面：帮助首页 + 学生版 / 教师版 / 家长版 / 教务管理版。
全部 auth='public'，面向零基础用户的中文操作指引，
站内直达链接均指向本仓库真实路由。
"""
from odoo import http
from odoo.http import request

# 帮助首页四张角色卡（href / 图标 / 底色 / 标题 / 一句话简介）
_HELP_CARDS = [
    {'href': '/help/student', 'icon': 'fa-graduation-cap',
     'color': '#7C3AED', 'title': '学生版',
     'desc': '登录、看课表、交作业、每日打卡、写周记、评教、查成绩与费用'},
    {'href': '/help/faculty', 'icon': 'fa-user-circle',
     'color': '#0891B2', 'title': '教师版',
     'desc': '教师工作台、周期排课、整周复制、周记批阅、打卡统计'},
    {'href': '/help/parent', 'icon': 'fa-child',
     'color': '#DB2777', 'title': '家长版',
     'desc': '家长账号如何查看孩子的课表、考勤、作业与成绩'},
    {'href': '/help/registrar', 'icon': 'fa-cogs',
     'color': '#B45309', 'title': '教务管理版',
     'desc': '开学排课全流程、综合评估任务发布、报名表字段调整'},
]


class EduHelpCenter(http.Controller):

    def _page(self, template, **kw):
        kw.setdefault('help_cards', _HELP_CARDS)
        return request.render(template, kw)

    @http.route('/help', type='http', auth='public', website=True)
    def help_index(self, **kw):
        """帮助首页：四张角色卡入口。"""
        return self._page('edu_portal.edu_help_index')

    @http.route('/help/student', type='http', auth='public', website=True)
    def help_student(self, **kw):
        """学生版使用指南。"""
        return self._page('edu_portal.edu_help_student')

    @http.route('/help/faculty', type='http', auth='public', website=True)
    def help_faculty(self, **kw):
        """教师版使用指南。"""
        return self._page('edu_portal.edu_help_faculty')

    @http.route('/help/parent', type='http', auth='public', website=True)
    def help_parent(self, **kw):
        """家长版使用指南。"""
        return self._page('edu_portal.edu_help_parent')

    @http.route('/help/registrar', type='http', auth='public', website=True)
    def help_registrar(self, **kw):
        """教务管理版使用指南。"""
        return self._page('edu_portal.edu_help_registrar')
