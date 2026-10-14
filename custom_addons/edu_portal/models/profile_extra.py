# -*- coding: utf-8 -*-
"""学生档案页交互动作族轻量模型（缺口 B7）。

- edu.student.skill    学生技能标签：档案「技能测评」区 chips + 「Add Your Skill」内联表单。
- edu.placement.offer  学生 Placement Offer：受邀/加入/拒绝三态，档案「实习就业」区展示，
                       行内「加入 / 拒绝」按钮由本人自助变更状态。
                       （后台批量录入 offer 不在本次范围，后续可用后台表单或下一批次补齐。）

安全约定：门户端所有写操作走控制器 sudo + 归属校验（记录必须属于当前登录学生的
op.student），因此门户 ACL 仅授只读；内部用户保留完整读写便于后台维护。
"""
from odoo import fields, models


class EduStudentSkill(models.Model):
    _name = 'edu.student.skill'
    _description = 'Student Skill Tag'
    _order = 'create_date desc, id desc'

    name = fields.Char('Skill Name', size=128, required=True)
    student_id = fields.Many2one('op.student', string='Student',
                                 required=True, index=True,
                                 ondelete='cascade')


class EduPlacementOffer(models.Model):
    _name = 'edu.placement.offer'
    _description = 'Student Placement Offer'
    _order = 'create_date desc, id desc'

    student_id = fields.Many2one('op.student', string='Student',
                                 required=True, index=True,
                                 ondelete='cascade')
    title = fields.Char('Job Title', size=256)
    company = fields.Char('Company', size=256)
    state = fields.Selection(
        [('invited', 'Invited'),
         ('joined', 'Joined'),
         ('rejected', 'Rejected')],
        string='Status', default='invited', index=True)
