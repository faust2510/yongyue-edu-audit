# -*- coding: utf-8 -*-
"""资产借还：台账 + 借还单（自研）。

学生门户申请 → 员工后台批准发放/登记归还；资产状态随借还联动。
设计文档：docs/plans/assets-design.md
"""
from odoo import api, fields, models
from odoo.exceptions import UserError


class EduAsset(models.Model):
    _name = 'edu.asset'
    _description = '学坊资产'
    _order = 'category, name'

    name = fields.Char(string='资产名称', required=True)
    code = fields.Char(string='编号', index=True)
    category = fields.Selection(
        [('device', '设备'), ('book', '书籍'), ('other', '其他')],
        string='类别', default='other', required=True)
    state = fields.Selection(
        [('available', '可借用'), ('loaned', '已借出'),
         ('maintenance', '维护中'), ('retired', '已退役')],
        string='状态', default='available', required=True, index=True)
    note = fields.Text(string='备注')

    loan_ids = fields.One2many('edu.asset.loan', 'asset_id')
    current_loan_id = fields.Many2one(
        'edu.asset.loan', string='当前借出单', compute='_compute_current_loan')

    @api.depends('loan_ids.state')
    def _compute_current_loan(self):
        for asset in self:
            asset.current_loan_id = asset.loan_ids.filtered(
                lambda l: l.state == 'borrowed')[:1]

    def action_mark_maintenance(self):
        for asset in self:
            if asset.state == 'loaned':
                raise UserError('资产在借出状态，归还后才能转维护。')
            asset.state = 'maintenance'

    def action_back_available(self):
        self.filtered(lambda a: a.state == 'maintenance').write(
            {'state': 'available'})


class EduAssetLoan(models.Model):
    _name = 'edu.asset.loan'
    _description = '资产借还单'
    _order = 'requested_date desc, id desc'

    asset_id = fields.Many2one(
        'edu.asset', string='资产', required=True,
        ondelete='cascade', index=True)
    student_id = fields.Many2one(
        'op.student', string='借用学生', required=True,
        index=True, ondelete='cascade')
    state = fields.Selection(
        [('requested', '待审批'), ('borrowed', '已借出'),
         ('returned', '已归还'), ('cancelled', '已取消'),
         ('rejected', '已驳回')],
        string='状态', default='requested', required=True, index=True)
    requested_date = fields.Date(
        string='申请日期', default=fields.Date.today, required=True)
    due_date = fields.Date(string='应还日期')
    returned_date = fields.Date(string='实际归还日期')
    requested_note = fields.Char(string='申请说明')
    staff_note = fields.Char(string='员工备注')

    # ---- 后台动作（按钮调用，服务端校验）----
    def action_approve(self):
        today = fields.Date.today()
        for loan in self:
            if loan.state != 'requested':
                continue
            if loan.asset_id.state != 'available':
                raise UserError(f'{loan.asset_id.name} 当前不可借用。')
            loan.write({'state': 'borrowed',
                        'due_date': loan.due_date or today})
            loan.asset_id.state = 'loaned'

    def action_reject(self):
        self.filtered(lambda l: l.state == 'requested').write(
            {'state': 'rejected'})

    def action_return(self):
        today = fields.Date.today()
        for loan in self:
            if loan.state != 'borrowed':
                continue
            loan.write({'state': 'returned', 'returned_date': today})
            if loan.asset_id.loan_ids.filtered(
                    lambda l: l.state == 'borrowed' and l.id != loan.id):
                continue  # 还有其他并行借出记录时不动资产
            loan.asset_id.state = 'available'
