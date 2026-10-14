# -*- coding: utf-8 -*-
{
    'name': 'Edu TG Bind 邀请码机器人',
    'version': '19.0.2.0.0',
    'category': 'Education',
    'summary': '学生私聊 Telegram 机器人，领一张学生层级注册邀请码（一个 TG 账号只能领一张）',
    'description': """
Telegram 发注册码机器人（edu_tg_bind）

学生私聊机器人，机器人回他一张学生层级邀请码，他拿码去 /register 注册。

- 一个 Telegram 账号只能领一张码：由数据库唯一约束保证（chat_id 唯一 + 邀请码唯一），不是 if 判断；同一个人再来＝回显原来那张，绝不发第二张。
- 领码/回显的回复**带 inline keyboard**：一个「➡️ 去注册」按钮（url = 系统参数
  edu_tg_bind.register_url）+ 一个「📋 复制邀请码」按钮（官方 copy_text，Bot API 7.11 起）；
  文案与键盘分开构造（edu.tg.claim.reply_text / reply_keyboard），下一步加 Mini App 只动键盘。
  两种按钮都**不产生 callback_query 更新** ⇒ 生产 setWebhook 的 allowed_updates 无需改动。
- 只处理私聊（chat.type 为 private）；群聊/频道/非 message 更新一律忽略，否则一个群能把码池刷空。
- 不验证身份、只发码（本轮不含课表/成绩/通知）。
- 码池 = edu.invite.code 中 batch_ref 以系统参数 edu_tg_bind.pool_batch_prefix 开头、state 为 unused、used_count 为 0、未过期、code_kind 为 tier、tier 为 student 的码。

⚠ 边界（重要，防踩雷）：生产上跑着的 edu_telegram 是**另一个**模块（匿名意见收集机器人：
edu.feedback.* / edu_telegram.outbox / edu_telegram.* 参数 / /telegram/webhook）。
本模块与它不共享任何东西：不读写它的表与参数、不占它的路由、depends 里也没有它。
完整边界与理由见 docs/plans/tg-invite-bot-design.md 第 1 节。

设计文档：docs/plans/tg-invite-bot-design.md（含出网/并发/webhook 鉴权三项实测依据）。
""",
    'depends': [
        # 只依赖真正需要的：本模块发的码是 edu.invite.code（定义在 edu_portal），
        # 且 edu.tg.claim.invite_code_id 指向它 —— 不声明依赖会在装载期撞 comodel 断言。
        # ⚠ 绝不依赖 edu_telegram：生产上那个同名模块是「匿名意见箱」，与本案无关。
        'edu_portal',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/tg_claim_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
