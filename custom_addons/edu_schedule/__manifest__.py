# -*- coding: utf-8 -*-
{
    'name': 'Edu Schedule 排课工具',
    'summary': '批量周期排课 + 停课管理：并入时间表应用',
    'description': '教师排课效率工具：周期排课(先预览后批量生成 op.session)与停课日管理(自动避开)。单节改删直接走后台列表。菜单并入 openeducat_timetable 应用。',
    'version': '19.0.2.2.0',
    'category': 'Website',
    'depends': [
        'openeducat_timetable',
        'website',
        # 2026-10-03：**如实声明**。views/templates.xml 的 /timetable/bulk 表调用了
        # edu_brand.edu_narrow_table_cards（窄屏卡片式表格的共用样式）。
        # 此前它引用的是 edu_portal.edu_narrow_table_cards，而本模块**不能**依赖 edu_portal
        # （edu_portal 依赖 edu_schedule ⇒ 成环），于是那条引用只能是「未声明的依赖」，
        # 靠渲染期 xmlid 解析侥幸能用。该共用样式已下沉到 edu_brand（纯 CSS、零模型访问）——
        # 它在本模块的依赖图下游，不成环。见 docs/plans/2026-10-02-shared-ui-primitives.md。
        'edu_brand',
        # 2026-10-04（第 66 轮，**全新库实测**）：models/session_ext.py:167 定义了
        #   calendar_event_id = fields.Many2one('calendar.event', ...)（「会议链接」那一组字段，
        #   用于把 op.session 与日历事件挂起来）。但 depends 里**没有 calendar** ⇒
        #   在没装过 calendar 的新库上，Odoo 装载模型时直接断言失败：
        #     AssertionError: Field op.session.calendar_event_id with unknown comodel_name
        #                     'calendar.event'
        #   ⇒ 整个安装中断。克隆库上看不出来，只因生产早就装过 calendar。
        #   与同轮修的 edu_brand 缺 digest 是同一类毛病（用了别的模块的模型却没声明）。
        'calendar',
        # 2026-10-14（排课链路改造 S1）：教师不可用时间落在 Odoo 原生
        # resource.resource / resource.calendar / resource.calendar.leaves 上
        # （models/faculty_ext.py）。虽有 hr / calendar 传递安装，仍如实声明。
        'resource',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/cron.xml',
        'views/templates.xml',
        'views/holiday_views.xml',
        # 2026-10-14（排课链路改造 S1）：教师不可用时间的后台总览（list+日历）。
        # 自己的 menuitem 也在这个文件里，引用的 action 在同文件更早处定义。
        'views/availability_views.xml',
        # 2026-10-14：S2 的排课完成度看板（G2）。views/menu.xml 的 menuitem
        # 引用本文件定义的 action_edu_coverage_url（act_url）⇒ 必须排在
        # menu.xml **之前**，否则安装期 ParseError（先例：holiday_views.xml → menu.xml）。
        'views/coverage.xml',
        'views/menu.xml',
        'views/session_conflict_view.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
}
