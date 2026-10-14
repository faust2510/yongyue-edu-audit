# -*- coding: utf-8 -*-
{
    'name': 'Edu TG Assist 行政班务机器人',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': '行政与班务辅助机器人：定时提醒、@提醒、广播、一对一私发、按钮回填',
    'description': """
行政与班务辅助机器人（edu_tg_assist）

校长给的《机器人开发.docx》的落地实现。能力：定时提醒 / @提醒 / 广播 / 一对一私发 / 按钮回填 / 模板库。

⚠ 硬边界（违反即事故，见 docs/plans/tg-assist-bot-design.md §2）：
生产上跑着的 edu_telegram 是**另一个**模块（匿名意见收集机器人：edu.feedback.* /
edu_telegram.outbox / edu_telegram.* 参数 / /telegram/webhook）。它的匿名性建立在
「不保存明文 chat_id、只存 HMAC 指纹」上。本模块与它**零共享**：
· 不读写它的表与系统参数；
· 不占它的路由（本模块用 /telegram/assist/webhook）；
· depends 里没有它；
· 本模块的 chat_id 与它的指纹**永不 join、永不并排导出**。

设计文档：docs/plans/tg-assist-bot-design.md
""",
    'depends': [
        # 只用 Odoo 原生。刻意不依赖 edu_portal / edu_telegram：
        # 依赖 edu_portal 会把「机器人能不能装」绑在门户上；本模块用 chat_id/姓名即可工作。
        'base',
    ],
    'data': [
        # ⚠ 顺序要紧：ACL 里引用 group_assist_manager，组必须先装载
        'security/assist_security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'data/ir_cron_reminder.xml',
        'views/assist_views.xml',
        # ⚠ 顺序要紧：下面的视图都引用 assist_views.xml 里的 menu_assist_root，必须排其后
        'views/assist_reminder_views.xml',
        'views/assist_dm_views.xml',
        'views/assist_mention_views.xml',
        'views/assist_material_views.xml',
        'views/assist_bindcode_views.xml',
        'views/assist_bridge_views.xml',
        # Mini App 面板（§9.17）：自包含 QWeb 页面，不依赖门户布局
        'views/miniapp_templates.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
}
