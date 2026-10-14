# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OpTelegramChat(models.Model):
    _name = 'op.telegram.chat'
    _description = 'Telegram 会话绑定'

    chat_id = fields.Char(required=True, index=True)
    telegram_name = fields.Char()
    role = fields.Selection(
        [('student', '学生'), ('faculty', '教师'), ('parent', '家长'),
         ('admin', '管理员')],
        required=True)
    student_id = fields.Many2one('op.student', ondelete='cascade')
    faculty_id = fields.Many2one('op.faculty', ondelete='cascade')
    parent_id = fields.Many2one('op.parent', ondelete='cascade')
    bound_on = fields.Datetime(default=fields.Datetime.now, readonly=True)

    _sql_constraints = [('chat_id_uniq', 'unique(chat_id)',
                        '每个 Telegram 会话只能绑定一个身份')]

    def _upsert(self, chat_id, vals):
        Chat = self.sudo()
        rec = Chat.search([('chat_id', '=', chat_id)], limit=1)
        if rec:
            rec.write(vals)
        else:
            rec = Chat.create(vals)
        return rec

    @api.model
    def bind_by_code(self, chat_id, tg_name, code):
        """一次性绑定码路径：/start <code>，网页端 /my/telegram 生成。"""
        role, rec0 = self.env['edu.telegram.binding'].consume(code, chat_id)
        if not rec0:
            return None
        vals = {'chat_id': chat_id, 'telegram_name': tg_name,
                'role': role, 'bound_on': fields.Datetime.now(),
                'student_id': rec0._name == 'op.student' and rec0.id or False,
                'faculty_id': rec0._name == 'op.faculty' and rec0.id or False,
                'parent_id': rec0._name == 'op.parent' and rec0.id or False}
        return self._upsert(chat_id, vals)

    @api.model
    def bind(self, chat_id, tg_name, number, birth):
        """学号/工号 + 生日双因子绑定，命中哪个角色就是哪个角色。"""
        vals = None

        sc = self.env['op.student.course'].sudo().search(
            [('roll_number', '=', number)], limit=1)
        stu = sc.student_id
        if stu and stu.birth_date and \
                stu.birth_date.strftime('%Y%m%d') == birth:
            vals = {'chat_id': chat_id, 'telegram_name': tg_name,
                    'role': 'student', 'student_id': stu.id,
                    'faculty_id': False, 'parent_id': False}

        if not vals:
            # HR 员工编号优先，其次工卡名，最后身份证号兜底
            fac = self.env['op.faculty'].sudo().search(
                ['|', ('emp_id.identification_id', '=', number),
                 ('emp_id.name', '=', number)], limit=1)
            if not fac:
                fac = self.env['op.faculty'].sudo().search(
                    [('id_number', '=', number)], limit=1)
            if fac and fac.birth_date and \
                    fac.birth_date.strftime('%Y%m%d') == birth:
                vals = {'chat_id': chat_id, 'telegram_name': tg_name,
                        'role': 'faculty', 'faculty_id': fac.id,
                        'student_id': False, 'parent_id': False}

        if not vals:
            key = self.env['ir.config_parameter'].sudo().get_param(
                'edu_telegram.admin_key')
            if key and number == key:
                vals = {'chat_id': chat_id, 'telegram_name': tg_name,
                        'role': 'admin', 'student_id': False,
                        'faculty_id': False, 'parent_id': False}
        if not vals:
            return None

        vals['bound_on'] = fields.Datetime.now()
        return self._upsert(chat_id, vals)

    @api.model
    def identity_of(self, chat_id):
        """返回 (role, record)；未绑定为 (None, None)。"""
        rec = self.sudo().search([('chat_id', '=', chat_id)], limit=1)
        if not rec:
            return None, None
        # admin 无业务档案，返回会话记录本身保证真值
        return rec.role, (rec.student_id or rec.faculty_id
                          or rec.parent_id or rec)
