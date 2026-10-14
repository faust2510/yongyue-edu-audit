# -*- coding: utf-8 -*-
{
    'name': '教务导航收口（edu_nav）',
    'version': '19.0.1.0.0',
    'summary': '菜单收口的唯一落地处：只改 active / group_ids / parent_id / sequence，禁止删除菜单',
    'author': 'Yongyue',
    'category': 'Education',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': ['data/menu_consolidation_data.xml'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
