# -*- coding: utf-8 -*-
"""入学申请：高频检索字段保留为实体列，其余答卷统一存 answer_json（元数据见 edu.apply.section/field）。"""
import json

from markupsafe import escape
from odoo import api, fields, models


class EduApplication(models.Model):
    _name = 'edu.application'
    _description = '入学申请'
    _order = 'create_date desc'
    _inherit = ['mail.thread']

    # —— 动态答卷存储：全部答案存 JSON；姓名/电话/邮箱/教会/科别等冗余实体列便于后台搜索 ——
    answer_json = fields.Text('答卷数据（JSON）')
    answers_html = fields.Html('答卷内容（按分区展示）', compute='_compute_answers_html')

    # 报考科别
    track = fields.Selection([
        ('b31', '3+1制本科班'), ('hsa', '家教学院'), ('m32', '3+2制本硕连读'),
    ], string='报考科别', required=True)

    # 基本信息
    name = fields.Char('姓名', required=True)
    gender = fields.Selection([('male', '男'), ('female', '女')], string='性别', required=True)
    id_no = fields.Char('身份证号/护照号', required=True)
    birth = fields.Char('出生年月')
    native_place = fields.Char('籍贯')

    # 信仰信息
    baptism_date = fields.Char('受洗时间')
    baptism_church = fields.Char('施洗教会')
    church = fields.Char('现委身的教会', required=True)
    marital = fields.Selection([
        ('married', '已婚'), ('divorced', '离异'), ('single', '单身')], string='婚姻状况')

    # 联系方式
    address = fields.Text('通讯地址')
    phone = fields.Char('电话/手机', required=True)
    email = fields.Char('电子邮箱')
    emergency_name = fields.Char('紧急联络人姓名')
    emergency_phone = fields.Char('紧急联络人电话')

    # 其他
    remark = fields.Text('其它备注（例如著作）')

    # 缴交材料核对（学院填）
    mat_form = fields.Boolean('申请表')
    mat_recommend = fields.Boolean('推荐信')
    mat_testimony = fields.Boolean('个人见证')
    mat_calling = fields.Boolean('学习之路\\蒙召见证')
    mat_diploma = fields.Boolean('学历或成绩副本')
    mat_physical = fields.Boolean('体检表')
    mat_idcard = fields.Boolean('身份证复印件')

    state = fields.Selection([
        ('new', '新申请'), ('review', '审核中'), ('exam', '待考试面试'),
        ('admitted', '已录取'), ('rejected', '未通过')], default='new', string='状态')

    education_ids = fields.One2many('edu.apply.education', 'application_id', '学历')
    work_ids = fields.One2many('edu.apply.work', 'application_id', '工作经历')
    ministry_ids = fields.One2many('edu.apply.ministry', 'application_id', '教会事奉经历')
    family_ids = fields.One2many('edu.apply.family', 'application_id', '家庭状况')

    @api.depends('answer_json')
    def _compute_answers_html(self):
        """按分区元数据把 answer_json 渲染成分组表格（实时计算，设置调整后即生效）。"""
        Section = self.env['edu.apply.section'].sudo()
        for app in self:
            try:
                data = json.loads(app.answer_json or '{}')
            except ValueError:
                data = {}
            chunks = []
            for sec in Section.search([], order='sequence, id'):
                rows = []
                for f in sec.field_ids:
                    val = data.get(f.name or '')
                    if isinstance(val, bool):
                        val = '是' if val else ''
                    if not val:
                        continue
                    rows.append(
                        '<tr><th class="fw-normal text-muted" style="width:38%%">%s</th>'
                        '<td>%s</td></tr>' % (escape(f.label), escape(str(val))))
                if rows:
                    chunks.append(
                        '<h6 class="mt-2 mb-1">%s</h6>'
                        '<table class="table table-sm table-borderless mb-2">%s</table>'
                        % (escape(sec.name), ''.join(rows)))
            app.answers_html = ''.join(chunks) or '<p class="text-muted">暂无答卷内容。</p>'


class EduApplyEducation(models.Model):
    _name = 'edu.apply.education'
    _description = '申请-学历'
    school = fields.Char('校名')
    years = fields.Char('起止年份')
    major = fields.Char('科系主修')
    degree = fields.Char('学位')
    application_id = fields.Many2one('edu.application', ondelete='cascade')


class EduApplyWork(models.Model):
    _name = 'edu.apply.work'
    _description = '申请-工作经历'
    company = fields.Char('单位名称')
    title = fields.Char('职称')
    period = fields.Char('起止日期')
    role = fields.Char('职务')
    application_id = fields.Many2one('edu.application', ondelete='cascade')


class EduApplyMinistry(models.Model):
    _name = 'edu.apply.ministry'
    _description = '申请-教会事奉经历'
    church = fields.Char('教会')
    role = fields.Char('职分')
    period = fields.Char('起止日期')
    application_id = fields.Many2one('edu.application', ondelete='cascade')


class EduApplyFamily(models.Model):
    _name = 'edu.apply.family'
    _description = '申请-家庭状况'
    relation = fields.Char('称谓')
    name = fields.Char('姓名')
    age = fields.Integer('年龄')
    education = fields.Char('教育程度')
    faith = fields.Char('宗教信仰')
    application_id = fields.Many2one('edu.application', ondelete='cascade')
