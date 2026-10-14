# -*- coding: utf-8 -*-
"""去 Odoo 化：session_info 里的用户菜单 Help 外链。

Odoo 19 在 ir.http.session_info() 硬编码
    "support_url": "https://www.odoo.com/buy"
（本机镜像实测：addons/web/models/ir_http.py:109；上游 HEAD 为 :114，行号会漂移），
后台用户菜单的「帮助」项据此打开 odoo.com 购买页。这里改为站内帮助中心。

依据：docs/research/odoo19-debranding-i18n.md §2.D（自研，不引入 OCA AGPL 模块）。
"""
from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        info['support_url'] = '/my/help'
        return info
