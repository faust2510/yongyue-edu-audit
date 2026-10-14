# -*- coding: utf-8 -*-
"""报名表元数据：分区与字段。
管理员在后台即可增删字段、调整分区与排序、设置必填/选填；
口径基线 = SCRTS人文教育入学申请表(2020-1版)，预置见 data/form_meta_data.xml（noupdate）。"""
from odoo import api, fields, models
from odoo.exceptions import UserError

FIELD_TYPES = [
    ('char', '单行文本'), ('select', '下拉选择'), ('radio', '单选'),
    ('date', '日期'), ('text', '多行文本'), ('textarea', '段落文本'),
    ('checkbox', '勾选框'),
]


class EduApplySection(models.Model):
    _name = 'edu.apply.section'
    _description = '报名表分区'
    _order = 'sequence, id'

    name = fields.Char('分区名称', required=True)
    sequence = fields.Integer('排序', default=10)
    active = fields.Boolean('启用', default=True)
    field_ids = fields.One2many('edu.apply.field', 'section_id', string='字段')

    def unlink(self):

        return super().unlink()


class EduApplyField(models.Model):
    _name = 'edu.apply.field'
    _description = '报名表字段'
    _order = 'sequence, id'

    section_id = fields.Many2one('edu.apply.section', string='所属分区',
                                 required=True, ondelete='cascade')
    label = fields.Char('显示名称', required=True)
    name = fields.Char('技术名（自动生成）', copy=False)
    type = fields.Selection(FIELD_TYPES, string='类型', default='char', required=True)
    required = fields.Boolean('必填')
    locked = fields.Boolean('核心锁定',
                            help='核心字段不可删除、不可停用、不可取消必填。')
    options = fields.Text('选项（每行一个）',
                          help='用于「下拉选择 / 单选」类型，每行写一个选项。')
    sequence = fields.Integer('排序', default=10)
    active = fields.Boolean('启用', default=True)

    _name_uniq = models.Constraint(
        'UNIQUE(name)', '字段技术名重复，请检查。')
    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        for rec in recs:
            if not rec.name:
                rec.name = 'q_%s' % str(rec.id).zfill(4)
        return recs

    def write(self, vals):
        # 管理员拥有完全权限：locked 仅作为界面标注，不再强制限制修改
        return super().write(vals)

    def unlink(self):
        for rec in self:
            used = self.env['edu.application'].search_count(
                [('answer_json', 'like', '"%s"' % rec.name)])
            if used:
                raise UserError(
                    '字段「%s」已有历史申请填写过内容，删除会丢失答卷数据；请改为停用。' % rec.label)
        return super().unlink()

    def option_lines(self):
        """QWeb 直接调用：把每行一个的 options 拆成列表。"""
        return [o.strip() for o in (self.options or '').splitlines() if o.strip()]
