# -*- coding: utf-8 -*-
"""门户自助修改密码：/my/password（所有登录角色）。

原密码校验走 res.users.change_password()：内部即
_check_credentials({'login':..., 'password': old, 'type': 'password'},
{'interactive': True})，验证通过后才写入新密码。

**新密码逐字保存**：core 的 _change_password 第一行把两端空格 strip 掉
（19.0 base/models/res_users.py:920）—— 与 2026-09-24 邀请码注册事故（register.py）
同源的第二扇门。已在 models/res_users_password.py 覆盖该方法（门户页 / 后台改密向导 /
个人偏好向导三个入口一并收口），因此本控制器不再自己拦「带空格的新密码」
（旧实现以「新密码首尾不能有空格」拒收，与注册/登录口径不一致，本次撤除）。
"""
from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request


class EduMyPassword(http.Controller):

    def _page(self, error=None, ok=False):
        return request.render('edu_portal.edu_my_password', {
            'title': '修改密码',
            'error': error,
            'ok': ok,
        })

    @http.route('/my/password', type='http', auth='user',
                website=True, sitemap=True)
    def password_form(self, ok=False, **kw):
        return self._page(ok=bool(int(ok)) if str(ok).isdigit() else False)

    @http.route('/my/password/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def password_save(self, **post):
        old = post.get('old_password') or ''
        new = post.get('new_password') or ''
        confirm = post.get('confirm_password') or ''
        if new != confirm:
            err = '两次输入的新密码不一致'
        # 纯空格密码（如 8 个空格）几乎必是误输入：明确拒收。注意这里只做**判断**
        # —— 拒收不改值，也不把用户敲的东西悄悄换成别的（那是本次事故的成因）。
        # 首尾空格则是密码本身的一部分：逐字收下（core 的 strip 已由
        # models/res_users_password.py 的覆盖撤除）。
        elif not new.strip():
            err = '新密码不能只由空格组成'
        elif len(new) < 8:
            err = '新密码至少 8 位'
        elif not old:
            err = '当前密码不正确'
        else:
            try:
                request.env.user.change_password(old, new)
            except AccessDenied:
                err = '当前密码不正确'
            else:
                return request.redirect('/my/password?ok=1', code=303)
        return self._page(error=err)
