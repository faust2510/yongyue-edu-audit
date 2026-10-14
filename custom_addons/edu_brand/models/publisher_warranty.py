# -*- coding: utf-8 -*-
"""去 Odoo 化：切断 publisher-warranty 对外回连。

Odoo 19 默认每 4 小时（cron mail.ir_cron_module_update_notification）向
http://services.odoo.com/publisher-warranty/ POST 本库信息
（addons/mail/models/update.py:_get_sys_logs；默认 URL 见 odoo/tools/config.py）。
本系统不需要该回连，直接停用发送路径（cron 仍可安全触发）。
"""
from odoo import models


class PublisherWarrantyContract(models.AbstractModel):
    _inherit = 'publisher_warranty.contract'

    def update_notification(self, cron_mode=True):
        return False
