# -*- coding: utf-8 -*-
{
    'name': 'Edu Telegram Bot',
    'version': '2.2',
    'category': 'Education',
    'summary': 'Telegram 四角色教务前端：绑定码、翻页、PDF 报表、定时推送',
    'depends': ['openeducat_core', 'openeducat_exam', 'openeducat_library',
                'openeducat_fees', 'openeducat_attendance'],
    'data': [
        'security/ir.model.access.csv',
        'views/telegram_templates.xml',
        'views/ops_templates.xml',
        'data/cron.xml',
    ],
    'installable': True,
}
