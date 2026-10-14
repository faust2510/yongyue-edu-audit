# -*- coding: utf-8 -*-
"""去 Odoo 化：发件服务器「测试邮件收件人」默认值。

Odoo 19 的 ir.mail_server._get_test_email_to() 硬编码返回 noreply@odoo.com
（本机镜像实测：addons/base/models/ir_mail_server.py:298），会直接显示在
「设置 → 技术 → 发件服务器」的测试收件人输入框里。改为学坊唯一对外邮箱。

品牌红线：对外联系方式只允许 scrtsschool@gmail.com。
"""
from odoo import models


class IrMailServer(models.Model):
    _inherit = 'ir.mail_server'

    def _get_test_email_to(self):
        return 'scrtsschool@gmail.com'
