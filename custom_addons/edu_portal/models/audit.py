# -*- coding: utf-8 -*-
"""关键操作审计（辅助增强包 4a，参考 Canvas Grade Change Log）。

谁在何时对什么做了什么。埋点位置（控制器层）：
成绩录入 / 请假审批 / 申诉处理 / 考勤录入 / 批量排课 / 整周复制 /
资料批量删除与移动。查询页 /edu/audit 仅教务处与管理员可见。
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class EduAuditLog(models.Model):
    _name = 'edu.audit.log'
    _description = '关键操作审计'
    _order = 'create_date desc, id desc'

    user_id = fields.Many2one(
        'res.users', string='操作人', index=True, ondelete='set null')
    action = fields.Char(string='操作类型', required=True, index=True)
    model = fields.Char(string='模型', index=True)
    res_id = fields.Integer(string='记录 ID')
    res_name = fields.Char(string='记录标识')
    detail = fields.Text(string='明细')

    @api.model
    def _log(self, action, model='', res_id=0, res_name='', detail=''):
        """审计写入：失败只告警，绝不阻断业务事务。"""
        try:
            self.create({
                'user_id': self.env.uid,
                'action': action,
                'model': model or '',
                'res_id': res_id or 0,
                'res_name': (res_name or '')[:256],
                'detail': detail or '',
            })
        except Exception:
            _logger.warning('audit log failed: %s', action, exc_info=True)
