# -*- coding: utf-8 -*-
{
    'name': 'Edu Quiz',
    'summary': '在线测验：题库、组卷、学生作答与自动判分',
    'version': '19.0.1.0.0',
    'category': 'Education',
    # edu_portal：门户壳 edu_portal.edu_page（顶栏搜索 + 角色导航 + 移动端底部 Tab）。
    # 本仓成文标准：门户页模板外壳 = t-call="edu_portal.edu_page"
    # （docs/code-map.md:93/§4、docs/dev-workflow.md:157）。edu_portal 的 depends 里
    # 没有 edu_quiz（已核 0 次）⇒ 不成环。
    'depends': ['openeducat_core', 'openeducat_exam', 'mail', 'edu_portal'],
    'data': [
        'security/ir.model.access.csv',
        'views/edu_quiz_views.xml',
        'views/edu_quiz_portal_views.xml',
        'views/edu_quiz_menus.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
}
