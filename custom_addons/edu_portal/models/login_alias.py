# -*- coding: utf-8 -*-
"""学号登录：把学号解析成该生的**登录名**（邮箱），交给 Odoo 原生登录。

为什么要有这一层（而不是在控制器里直接查库）：控制器只做「改写参数」，
「学号 → 账号」的唯一实现在这里，离线单测（tests/unit/edu_portal_login_alias_test.py）
可以只测纯函数，odoo shell 可以只测本方法。

三条硬规矩（设计文档 §9.12.5 B15 / §9.12.6 降级表）：
  · 只在输入**像学号**时才解析（controllers/main.py 先过 login_alias.looks_like_gr_no）；
  · 解析不到就返回空串 ⇒ 调用方原样放行，登录页照常回「Wrong login/password」——
    **绝不**提示「这个学号不存在」（那等于把学号是否在册做成可枚举的接口）；
  · 6 个没有学号的存量学生不受影响：他们继续用邮箱登录（邀请码注册那条路没动）。
"""
import logging

from odoo import SUPERUSER_ID, api, models

# 身份 → 账号的**唯一实现**（edu_portal 依赖 edu_schedule，无环；先例：
# models/invite_code.py、models/fees.py 都从这里取）。
from odoo.addons.edu_schedule.models.identity import users_of_profile

_logger = logging.getLogger(__name__)


class EduPortalLoginAlias(models.AbstractModel):
    _name = 'edu.portal.login.alias'
    _description = '学号登录别名（学号 → 登录名）'

    @api.model
    def login_for_gr_no(self, gr_no):
        """学号 → 登录名（邮箱）；找不到可用账号时返回 ''。

        只返回登录名，**不返回**档案或账号对象：调用方（控制器）只需要把
        request.params['login'] 换成它，多给信息只会诱使别人在这里做别的事。
        """
        gr = (gr_no or '').strip()
        if not gr:
            return ''
        try:
            # 按学号取档案：复用领码流已有的唯一实现（精确优先、=ilike 兜底、
            # 输入含 LIKE 通配符时不走兜底），不另写一套查询。
            student = self.env['edu.invite.code'].sudo()._edu_student_by_gr_no(gr)
            if not student:
                return ''
            for user in users_of_profile(student):
                if user.active and (user.login or '').strip():
                    return user.login.strip()
        except Exception as exc:  # noqa: BLE001
            # 学号登录是**附加通道**：它出问题绝不能影响邮箱登录这条主路。
            _logger.warning('edu_portal: 学号登录解析失败（%s）', type(exc).__name__)
        return ''

    @api.model
    def blocked_seconds(self, key):
        """这个限速键还要等几秒（0 = 放行）。

        读失败 ⇒ 返回 0（放行）：限速是**加固**，不能因为限速表出问题把登录挡死。
        """
        if not key:
            return 0
        try:
            return self.env['edu.portal.login.throttle'].sudo().blocked_seconds(key)
        except Exception as exc:  # noqa: BLE001
            _logger.warning('edu_portal: 学号登录限速读取失败（%s）', type(exc).__name__)
            return 0

    @api.model
    def note_attempt(self, key, ok):
        """把这次登录的结果记进限速表（ok=True 清零，False 累加失败）。

        **独立事务**（registry.cursor()）：登录失败/异常时请求事务可能回滚，
        而失败计数必须留下 —— 否则限速会被「失败即回滚」整个吃掉。
        写失败只记一条 warning，绝不冒泡（不能让限速把登录流程弄挂）。
        """
        if not key:
            return
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                throttle = env['edu.portal.login.throttle'].sudo()
                if ok:
                    throttle.clear(key)
                else:
                    throttle._bump(key)
        except Exception as exc:  # noqa: BLE001
            _logger.warning('edu_portal: 学号登录限速写入失败（%s）', type(exc).__name__)
