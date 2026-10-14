# -*- coding: utf-8 -*-
{
    'name': '永约学坊 · 中文本地化（术语覆盖）',
    'version': '19.0.1.0.0',
    'category': 'Technical',
    'summary': '用具名术语覆盖基座/自研模块的机翻硬伤（仅 i18n_extra + post_init hook）',
    'description': """
永约学坊中文本地化模块
======================

只有译文，没有模型 / ACL / 权限组 / 视图。

覆盖对象（全部带 #: 目标引用行，见 i18n_extra/*.po）：
* openeducat_erp 基座字段描述与选择值机翻硬伤
  （地位→状态、批→班级、马克→分数、年级→等级、经过→及格、
    迄今为止→结束日期、得到正式认可的→已批准、公认→已批准、
    被拒绝→已驳回、要求/已请求→已申请、颜色指数→颜色序号）
* edu_* 自研模块未翻译的选择值（In Progress / Resolved / Rejected /
  Approved / Requested / Closed / Circular）
* 门户视图里写死的中文标签（开启→进行中、收到的分数→得分、
  尝试日期→作答日期、完全错误→答错题数、Circular 公告→通告）

生效方式（重要）
----------------
本模块的 .po 指向**其他模块**的记录，数据库里已有机翻值；
Odoo 在 overwrite=False 时数据库值优先，因此必须：

    odoo -c /etc/odoo/odoo.conf -d <db> -u edu_zh --i18n-overwrite --stop-after-init

或走 post_init_hook（仅首次安装时触发，内部
ir.module.module._load_module_terms(..., overwrite=True)）。

已知副作用：-u edu_zh 时 Odoo 会连同依赖闭包（base）一起重载其 PO，
若同时给了 --i18n-overwrite，base 的手工译文会被官方 PO 覆盖。
""",
    'author': '永约学坊',
    'website': 'https://github.com/',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': [],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
