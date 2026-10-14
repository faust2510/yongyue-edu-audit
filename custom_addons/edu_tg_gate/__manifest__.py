# -*- coding: utf-8 -*-
{
    'name': 'Edu TG Gate 前门分发',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'SCRTS 一个 webhook 分发给两个模块：学生领码 / 行政班务',
    'description': """
Telegram 前门分发（edu_tg_gate）
=================================

背景（2026-10-08 用户裁定，见 docs/plans/tg-assist-bot-design.md §9）：
学校决定**复用 @sctrs_bot** 作为行政班务机器人的载体（而不是新建第三个机器人）。
一个 Telegram 机器人只能挂一个 webhook URL，而 @sctrs_bot 的 URL 已经被
edu_tg_bind（学生私聊领邀请码）占用；轮询退路也被 Telegram 封死
（getUpdates 实测 409：can't use getUpdates method while webhook is active）。
⇒ 必须有一个**前门**：一个网址、两个模块。

本模块做什么
------------
· 独占新路由 /telegram/sctrs/webhook（官方 secret 头 + fail-closed 403）；
· 按 routing.decide() 把 update 判给 edu_tg_bind（学生领码）或 edu_tg_assist（行政班务）；
· 默认方向朝 edu_tg_bind —— 拿不准的私聊一律走学生流：
学生领不到码是「学校招不到人」，教职工多收一条码只是「看着奇怪」。

硬边界（B7/B8，违反即事故）
---------------------------
· B7 —— 绝不占用 /telegram/webhook（生产匿名意见箱）与 /telegram/tgb/webhook
（edu_tg_bind 自带路由，保留作一键回滚）；本模块用 /telegram/sctrs/webhook。
· B8 —— 本模块**不存任何表、不存 chat_id**：只做分流与转发。
chat_id 只存在于 edu_tg_bind（学生码）与 edu_tg_assist（人员映射）各自的表里，
与 edu.feedback.* 的指纹永不 join、永不并排导出（沿用 assist 设计 §2 B5）。

依赖
----
· depends = ['edu_tg_bind']：前门要调 edu.tg.claim（领码流的唯一实现）。
· edu_tg_assist **刻意不写进 depends**，走运行时注册表检查（self.env.get）：
assist 没装 / 被卸时，前门必须继续把私聊送到领码流（学生流优先级最高）。
""",
    'depends': [
        'edu_tg_bind',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
