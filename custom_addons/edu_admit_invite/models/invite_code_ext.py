# -*- coding: utf-8 -*-
"""给既有码表 edu.invite.code 加「来源申请」这一列 —— 本模块唯一的 schema 变更。

设计：docs/plans/admission-invite-link-design.md §8.3 / §18.3。
为什么只加一列（不建 edu.invite.issue 表）：今天「把一张码发给某个外部身份」只有
两处（TG 池 edu.tg.claim、网页批量生成向导），本设计是**第三处**；§8.5 的触发条件
（出现第三处 ⇒ 收口成一张发放表）已登记为**后续项**，本轮按用户拍板只做最小闭环。

为什么不复用 code 前缀去重：`code` 已被 edu_tg_bind 当池前缀用（tg_claim.py:48-57），
再给它加语义会打穿 TG 的池机制。`application_id` 独立成列，语义单一。

并发兜底为什么靠 DB 约束而不是靠 search：`search` 在并发下会各自查到「没有」，
两张码都能建出来 —— unique(application_id) 是唯一真相层（服务端幂等快路径只是体验）。
"""
from odoo import fields, models


class EduInviteCode(models.Model):
    _inherit = 'edu.invite.code'

    application_id = fields.Many2one(
        'edu.application', string='入学申请', ondelete='restrict',
        index=True, copy=False,
        help='本码由哪张入学申请发放（录取后发放入学码）。留空 = 不是录取发放的码'
             '（如 TG 池、批量向导、教师码）。删申请前必须先处理它的码，不静默解绑。')

    # ondelete='restrict' 与 edu.tg.claim.invite_code_id 同口径（tg_claim.py:71-73）。
    # Odoo 19 旧写法 _sql_constraints 会被**静默忽略**（仓内先例：
    # custom_addons/edu_portal/models/registration.py:511）。
    _edu_admit_application_uniq = models.Constraint(
        'UNIQUE (application_id)',
        '同一张入学申请只能绑定一张入学码；请用「重新发放入学码」而不是再发一张。')
