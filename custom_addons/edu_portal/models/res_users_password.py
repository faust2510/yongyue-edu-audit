# -*- coding: utf-8 -*-
"""改密码「逐字保存」：覆盖 core 对新密码的 strip（与 2026-09-24 注册事故同源）。

事故类：Odoo core 的 res.users._change_password 第一行就是

    new_passwd = new_passwd.strip()      # base/models/res_users.py:920（19.0 部署版）

而登录端（session.authenticate → _check_credentials）对提交的口令不做任何归一化
⇒ 把密码改成 "abc " 时库里存的是 "abc"：本人用自己敲的 "abc " 永远登不上 ——
与 2026-09-24 邀请码注册事故（controllers/register.py 曾把 password 一起 strip）
同一个陷阱，走的是另一扇门；而这扇门在 core 里，控制器改不动，所以在自己的模块覆盖。

本覆盖罩住的三个入口（都汇流到 _change_password）：
  1. 门户自助改密 /my/password/save（controllers/my_password.py → change_password()）
  2. 后台「修改密码」向导 change.password.user.change_password_button
     （base/models/res_users.py:1481，管理员给别人设密码）
  3. 个人偏好里的自助向导 change.password.own.change_password
     （base/models/res_users.py:1501）

本就不 strip、因此不在本覆盖里（详见 docs/plans/password-verbatim-audit.md）：
  注册 / 邀请 / 邮箱重置令牌 → auth_signup 的 signup() 走 write()/copy() 落
  _set_password（auth_signup/controllers/main.py:153-157 原样取值、原样比对 confirm）；
  res.users.new_password 的 inverse _set_new_password（base:414-426）也不 strip。

**只改「值」，不碰哈希与存储**：末行仍是 self.password = new_passwd，落到 core 的
_set_password → _set_encrypted_password（pbkdf2_sha512），与 core 一字不差。

保留的守卫（一个不少）：
  · 空 / 纯空格新密码：明确拒收（UserError）并说清原因，**绝不静默改值**
    （静默改值正是本次事故的成因）；
  · 旧密码校验、new == confirm、最小长度：在控制器与 core 的 change_password() 里，未动；
  · 与 core 相同的改密审计日志（谁给谁改、来源 IP）。
"""
import logging

from odoo import models
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


class ResUsersPassword(models.Model):
    _inherit = 'res.users'

    def _change_password(self, new_passwd):
        """与 core 同语义，只去掉那句 strip（19.0 base/models/res_users.py:920）。"""
        if not new_passwd:
            raise UserError('密码不能为空')
        # 纯空格（如 8 个空格）几乎必是误输入：如实拒收。注意这里只**判断**
        # —— 拒收不改值，也不把用户敲的东西悄悄换成别的（那是本次事故的成因）。
        if not new_passwd.strip():
            raise UserError('密码不能只由空格组成')

        ip = request.httprequest.environ['REMOTE_ADDR'] if request else 'n/a'
        _logger.info(
            "Password change for %r (#%d) by %r (#%d) from %s",
            self.login, self.id,
            self.env.user.login, self.env.user.id,
            ip,
        )
        # 逐字写入（core 这里写的是 strip 过的值）；库里的哈希/字段一律不变。
        self.password = new_passwd
