# -*- coding: utf-8 -*-
"""招聘后台：岗位发布 + 申请收集（自研）。

公开页 /campus/jobs 由 edu_public 控制器以 sudo 渲染 published 岗位；
申请表单公开可投（honeypot 反机器人），数据仅内部可见。
"""
from odoo import api, fields, models


class EduJobPosting(models.Model):
    _name = 'edu.job.posting'
    _description = '招聘岗位'
    _order = 'publish_date desc, id desc'

    name = fields.Char(string='岗位名称', required=True)
    department = fields.Char(string='单位/部门')
    location = fields.Char(string='工作地点')
    salary_range = fields.Char(string='薪资范围', placeholder='面议')
    openings = fields.Integer(string='招聘人数', default=1)
    description = fields.Html(string='岗位职责与要求', sanitize=True)
    publish_date = fields.Date(
        string='发布日期', default=fields.Date.today, required=True)
    state = fields.Selection(
        [('draft', '草稿'), ('published', '已发布'), ('closed', '已关闭')],
        string='状态', default='draft', required=True, index=True)
    posted_by = fields.Many2one(
        'res.users', string='发布人', default=lambda self: self.env.user)
    application_ids = fields.One2many('edu.job.application', 'posting_id')
    application_count = fields.Integer(
        string='申请数', compute='_compute_application_count')

    @api.depends('application_ids')
    def _compute_application_count(self):
        for posting in self:
            posting.application_count = len(posting.application_ids)


class EduJobApplication(models.Model):
    _name = 'edu.job.application'
    _description = '岗位申请'
    _order = 'applied_date desc, id desc'

    posting_id = fields.Many2one(
        'edu.job.posting', string='应聘岗位', required=True,
        ondelete='cascade', index=True)
    name = fields.Char(string='姓名', required=True)
    phone = fields.Char(string='联系电话', required=True)
    email = fields.Char(string='邮箱')
    education = fields.Selection(
        [('high_school', '高中/中专'), ('college', '大专'),
         ('bachelor', '本科'), ('master', '硕士'), ('phd', '博士'),
         ('other', '其他')],
        string='学历', default='other')
    note = fields.Text(string='个人简介/自荐说明')
    state = fields.Selection(
        [('new', '新申请'), ('reviewing', '筛选中'),
         ('interview', '约面试'), ('accepted', '录用'),
         ('rejected', '不合适')],
        string='状态', default='new', required=True, index=True)
    applied_date = fields.Date(
        string='提交日期', default=fields.Date.today, required=True)

    _app_phone_check = models.Constraint(
        "CHECK (phone ~ '[0-9+\\- ]{6,}')",
        '联系电话格式不正确。')
