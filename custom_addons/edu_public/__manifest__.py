# -*- coding: utf-8 -*-
{
    'name': 'Edu Public Pages',
    'summary': '游客可访问的公开页：课程列表 / 在线考试 / 数字图书馆',
    'version': '19.0.1.1.0',
    'category': 'Website',
    'depends': ['website', 'openeducat_core', 'openeducat_exam',
                'openeducat_library'],
    'data': [
        'views/edu_public_views.xml',
        'views/course_detail.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
}
