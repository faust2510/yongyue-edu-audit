# -*- coding: utf-8 -*-
"""校友工作发布（Backoffice 角色管理）轻量模型。"""
from odoo import fields, models


class EduAlumniJob(models.Model):
    _name = 'edu.alumni.job'
    _description = 'Alumni Job Post'
    _order = 'start_date desc, id desc'

    name = fields.Char('Job Title', required=True)
    code = fields.Char('Code', size=16)
    salary = fields.Char('Salary Range')
    pay_period = fields.Selection(
        [('monthly', 'Monthly Pay'), ('weekly', 'Weekly Pay'),
         ('yearly', 'Yearly Pay')], string='Payable', default='monthly')
    start_date = fields.Date('Start Date')
    end_date = fields.Date('End Date')
    state = fields.Selection(
        # 中文化（t10）：与仓内既有口径一致（评估类 state 'closed' → 「已结束」）
        [('recruiting', '招聘中'), ('pending', '待发布'),
         ('closed', '已结束')], string='状态', default='pending')
    creator = fields.Char('Created By')
