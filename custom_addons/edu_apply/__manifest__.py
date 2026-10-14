# -*- coding: utf-8 -*-
{
    'name': '永约学坊 · 在线报名',
    'version': '2.0',
    'summary': '公开入学申请表（字段标准：SCRTS人文教育入学申请表 2020-1版）',
    # openeducat_core：教务组 xmlid 在 ACL 里要用到（group_op_back_office_admin）
    # openeducat_admission：要把基座那棵用不上的「招生」菜单对教务藏起来
    'depends': ['website', 'mail', 'openeducat_core', 'openeducat_admission'],
    'data': [
        'security/ir.model.access.csv',
        'data/form_meta_data.xml',
        'views/templates.xml',
        'views/backend_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'edu_apply/static/src/js/apply_form.js',
            'edu_apply/static/src/css/apply.css',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
