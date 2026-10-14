# -*- coding: utf-8 -*-
"""课程结业证书轻量模型。

社区版 OpenEduCat 无证书模型，自建 edu.certificate 支撑
/certificate 学生门户列表与 /my/certificate/download/<id> PDF 下载。
证书编号由 ir.sequence（code=edu.certificate）生成 EDU-CERT-%04d。
"""
from odoo import api, fields, models


class EduCertificate(models.Model):
    _name = 'edu.certificate'
    _description = '课程结业证书'
    _order = 'issue_date desc, id desc'
    _rec_name = 'certificate_no'

    student_id = fields.Many2one('op.student', string='学生', required=True,
                                 ondelete='cascade', index=True)
    course_id = fields.Many2one('op.course', string='课程', required=True,
                                ondelete='cascade')
    certificate_no = fields.Char(
        string='证书编号', copy=False,
        default=lambda self:
            self.env['ir.sequence'].next_by_code('edu.certificate'))
    issue_date = fields.Date(string='发放日期', default=fields.Date.today)
    grade = fields.Char(string='成绩')
    state = fields.Selection(
        [('draft', '草稿'), ('issued', '已发放')],
        string='状态', default='issued')
    remark = fields.Char(string='备注')

    @api.model
    def action_issue(self):
        """确认签发：draft -> issued（后台表单按钮，self 为空时回退 active_ids）。"""
        recs = self or self.browse(self.env.context.get('active_ids') or [])
        recs.write({'state': 'issued'})
