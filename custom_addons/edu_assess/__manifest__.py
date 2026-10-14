# -*- coding: utf-8 -*-
{
    'name': 'Edu Assess (评估引擎)',
    'summary': '评估系统重建（形态甲）：评分项 = 数据行，加一列不发版；三面矩阵 + xlsx 往返 + 匿名指纹',
    'description': """
评估引擎（**唯一评估引擎**；B 套已删除，A 套只剩兼容入口）。

设计稿：docs/plans/evaluation-rebuild-design.md（校长拍板 8 项 + 形态甲 + 匿名口径 ③）。

- **形态甲**：评分项是数据行 edu.assess.item，**不是模型字段** ⇒ 教务在后台点
  「添加一行」就等于给矩阵加一列，不发版、不升级、刷新即生效。
- **三面共用一份定义**：门户服务端渲染矩阵（行 = 名单快照、列 = 评分项）、
  后台可编辑列表、xlsx 宽表；三者都在请求时读同一份 item_ids。
- **匿名口径 ③**：评教不存明文打分人，只存 HMAC(用户 + 任务 + 盐) 指纹；
  样本数低于门槛时结果页不展示任何明细。
- **xlsx 自研两段式**：导出 → 填写 → 导回预览 → 提交；幂等键 = 任务 + 被评者 + 评分项
  （教务组没有 base.group_allow_export，Odoo 原生导出按钮对他们不出现）。
- **旧两套的现状（2026-09-29 订正文案；只改描述，代码未动）**：
  · **B 套（edu_eval / edu.admin.eval.*）已删除**：模块目录与三张表、后台菜单 597–600、
    门户 /eval/* 六条路由全部移除 ⇒ 那些旧地址**现在是 404**（有意为之，不是漏挂）。
    本模块原先代管的 B 套 303 兼容壳也随之拆除（壳自己的注释就要求「连同 import 一起删」）。
  · **A 套（edu.eval.*）仍在 edu_portal 里，一行未删**：旧地址 /my/evaluation* 由 edu_portal
    的 `eval_compat` 兼容层 303 收口到本模块的 /assess（模型/表/ACL 未动，只冻结）。
  · 因此本模块才是**唯一在用的评估引擎**，与旧套之间只剩「A 套兼容入口」这一条关系。

权限：门户组与内部用户组一律不给 ACL（门户走控制器 sudo() + 显式域收敛），
教师组另有行级规则收敛到本人任教班（security/security.xml）。
    """,
    'version': '19.0.1.0.0',
    'category': 'Website',
    'depends': [
        'edu_portal',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'views/assess_views.xml',
        'views/assess_portal.xml',
        'views/assess_template_admin.xml',
        'views/assess_task_admin.xml',
        'views/assess_structure_views.xml',
    ],
    # 演示数据一律走 demo 键（不会在生产安装时装载），且名称带【演示】标记。
    # 本地演示用 scripts/seed_assess_demo.py（幂等 get-or-create）。
    'demo': [
        'demo/assess_demo.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'edu_assess/static/src/css/assess_grid.css',
            'edu_assess/static/src/js/assess_grid.js',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
