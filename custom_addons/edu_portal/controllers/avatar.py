# -*- coding: utf-8 -*-
"""头像自助更换：每个用户可上传/修改本人头像。

入口：B11 顶栏点击自己头像（弹窗），或用户菜单「修改头像」。
只允许写当前登录用户自己的 partner 记录，不触碰他人数据。
"""
import base64

from odoo import http
from odoo.http import request


class EduAvatar(http.Controller):

    @http.route('/my/avatar/upload', type='http', auth='user',
                methods=['POST'], csrf=True, website=True)
    def avatar_upload(self, **kw):
        upload = request.httprequest.files.get('avatar')
        if upload and upload.filename:
            data = upload.read()
            if data:
                request.env.user.partner_id.sudo().write({
                    'image_1920': base64.b64encode(data).decode(),
                })
        return request.redirect(request.httprequest.referrer or '/my/home')