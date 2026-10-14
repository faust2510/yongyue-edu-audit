# -*- coding: utf-8 -*-
"""D1 自检页 —— 后台「班务机器人 → 自检」点开就能看到「到底能不能发得出去」。

为什么做成一张瞬态表而不是弹个提示框：报告有十来行，提示框（toast）放不下、也没法复制；
瞬态记录只在这次操作期间存在，不进数据库长期留存。

只读：出网仅 getMe / getWebhookInfo（见 models/api.py 的 selfcheck_lines），
不发消息、不改配置、绝不打印 token 明文。
"""
from odoo import api, fields, models


class EduTgAssistSelfcheck(models.TransientModel):
    _name = 'edu.tg.assist.selfcheck'
    _description = '班务机器人自检'

    checked_at = fields.Datetime('自检时间', readonly=True)
    report = fields.Text('自检结果', readonly=True)

    @api.model
    def _build(self):
        lines = self.env['edu.tg.assist.api'].sudo().selfcheck_lines()
        return {'report': chr(10).join(lines), 'checked_at': fields.Datetime.now()}

    @api.model
    def default_get(self, fields_list):
        """从菜单打开（新建一条）时**当场跑一遍**，不必再点按钮。"""
        res = super().default_get(fields_list)
        res.update(self._build())
        return res

    def action_rerun(self):
        """「重新自检」按钮：当场重跑，结果写回这条记录并原地刷新。"""
        self.ensure_one()
        self.sudo().write(self._build())
        return {
            'type': 'ir.actions.act_window',
            'name': '班务机器人自检',
            'res_model': 'edu.tg.assist.selfcheck',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
