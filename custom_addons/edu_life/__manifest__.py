# -*- coding: utf-8 -*-
{
    'name': 'Edu Life 灵命生活',
    'summary': '灵命生活：类型化打卡引擎（月历+一键打卡）与学生周记本（教师批阅）',
    'description': """
灵命生活模块：
- edu.checkin.type 打卡类型（daily/weekly，周目标与截止星期可配）
- edu.checkin.record 打卡记录（学生x类型x日期唯一，拒绝未来日期）
- /my/checkins 学生打卡门户：本月日历网格 + 一键打卡 + 当月各类型计数
- edu.journal.entry 学生周记（周次唯一，草稿/提交/批阅三态）
- /my/journals 学生周记本：本周编辑提交 + 历史与教师评语
- /journals/review 教师端待批队列：查看正文 -> 填评语 -> 置已批阅
后台顶级菜单「灵命生活」：打卡类型 / 打卡记录 / 周记归档。
""",
    'version': '19.0.1.0.0',
    'category': 'Website',
    'depends': [
        'website',
        'mail',
        # 打卡记录/周记的 student_id 指向 op.student：必须声明依赖，
        # 否则 -u 时模块图先于 openeducat_core 加载，comodel 断言失败
        'openeducat_core',
        # 2026-10-02 补（narrow-a 报告）：本模块的 views/portal_templates.xml 现在
        #   `t-call="edu_portal.edu_narrow_table_cards"`（窄屏卡片式表格共用样式）。
        #   t-call 是**渲染期按 xmlid 解析**，所以今天装着 edu_portal 时不报错；
        #   但**只装 edu_life 不装 edu_portal** 时会炸 External ID not found。
        #   同仓的 edu_assess 做同样的事时就声明了 'edu_portal' ⇒ 本仓口径一致。
        #   不成环：edu_portal 的 depends 里没有 edu_life（已核）。
        'edu_portal',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'views/checkin_type_views.xml',
        'views/checkin_record_views.xml',
        'views/journal_views.xml',
        'views/menus.xml',
        'data/demo_life.xml',
        'views/portal_templates.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
}
