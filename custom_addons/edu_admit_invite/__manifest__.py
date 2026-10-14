# -*- coding: utf-8 -*-
{
    'name': 'Edu Admit Invite 录取后发放入学码',
    'summary': '「已录取」→ 发一张学生层级入学码 → 邮件通知 → 申请人自助注册',
    'description': '在入学申请（edu.application）的「已录取」状态上发放学生层级邀请码（edu.invite.code）：'
                   '绑定申请（唯一）、邮件尽力而为通知、页面回显码与注册回执、可重新发放。'
                   '不新造发码模型，只给既有码表加一列 application_id。'
                   '设计与任务书：docs/plans/admission-invite-link-design.md（§18 为实施口径）。',
    'version': '19.0.1.0.0',
    'category': 'Website',
    'license': 'LGPL-3',
    'depends': [
        # 码表 edu.invite.code 与留痕 edu.audit.log 都在 edu_portal。
        'edu_portal',
        # 本模块继承 edu.application（入学申请）并继承其表单视图；
        # edu_portal 虽已依赖 edu_apply，但这里如实声明（仓内口径：用了就声明）。
        'edu_apply',
    ],
    'data': [
        'views/application_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
