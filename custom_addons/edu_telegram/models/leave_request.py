# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OpLeaveRequest(models.Model):
    """轻量请假单：TG 对话提交，教师/管理员 inline 审批。"""
    _name = 'op.leave.request'
    _description = '学生请假单'
    _order = 'id desc'

    student_id = fields.Many2one('op.student', required=True,
                                 ondelete='cascade')
    leave_type = fields.Selection(
        [('sick', '病假'), ('personal', '事假'), ('other', '其他')],
        required=True, default='sick')
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    reason = fields.Text()
    state = fields.Selection(
        [('submitted', '待审批'), ('approved', '已批准'),
         ('rejected', '已驳回')], default='submitted')

    TYPE_ZH = dict(sick='病假', personal='事假', other='其他')
    STATE_ZH = {'submitted': '⏳ 待审批', 'approved': '✅ 已批准',
                'rejected': '❌ 已驳回'}

    def summary(self):
        self.ensure_one()
        return ("📝 请假单 #%d\n学生：%s\n类型：%s\n日期：%s ~ %s\n"
                "事由：%s\n状态：%s" % (
                    self.id, self.student_id.name,
                    self.TYPE_ZH[self.leave_type], self.date_from,
                    self.date_to, self.reason or '-',
                    self.STATE_ZH[self.state]))
