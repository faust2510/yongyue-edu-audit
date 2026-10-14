# -*- coding: utf-8 -*-
"""请假转交审批（转交留痕表）：一行 = 一次「这一张单 · 这一级」的转交。

设计稿：docs/plans/leave-split-approval-design.md
  · §4.2 数据模型（本文件的字段逐字来源）
  · §4.3 四条规则（同角色互转 / 转交后原审批人不能再批 / 只能转 1 次 / 必须留痕）
  · §9.2 文件清单（S1 新增）

为什么是**独立表**而不是在 edu.leave 上挂两个字段
--------------------------------------------------
用户明确要求留痕三要素「谁转给谁 · 何时 · 为什么」，并且要求「只能转 1 次」。
两个字段只能表达「当前是谁」，表达不了「转了几次、每次是谁转给谁、为什么」，
更表达不了「第二次转交必须失败」这条**硬规则**。

「只能转 1 次」= 数据库级唯一约束（**必须用 models.Constraint**）
----------------------------------------------------------------
Odoo 19 里旧写法 `_sql_constraints` 会被框架**静默忽略**：框架只遍历
`_table_objects`（见 odoo/orm/model_classes.py），旧列表只换来一条 WARNING，
约束**根本不建库** —— 「只能转 1 次」会静默失效。本仓既有先例：
  · custom_addons/edu_portal/models/course_rep.py:174-176
  · custom_addons/edu_portal/models/invite_code.py:148
  · custom_addons/edu_tg_bind/models/tg_claim.py:87-90
本约束在数据库里的名字 = 表名 + 去掉前导下划线的属性名：
`edu_leave_transfer_transfer_once`（`\\d edu_leave_transfer` 可见）。

与既有 `edu.approval.delegate` 的关系：**并存，不合并**（§4.1）
---------------------------------------------------------------
`edu.approval.delegate`（models/leave.py:207-253）是「**事前、带时间窗的长期授权**」：
我出差这 5 天你代我批，期内外**原审批人仍然能批**（代理是"也能"，不是"不能"）。
本表是「**事后、单笔的一次性让渡**」：这一张单我不批了，你去批，
转交后**原审批人不能再批这一级**（§4.3(2)），无时限、不可撤销。
合并会同时丢掉两个语义（时间窗 vs 单笔永久）；钉钉与 OCA 也都是做成两个独立功能。

字段口径（§4.2 表逐字落地）
---------------------------
| 字段 | 类型 | 说明 |
|---|---|---|
| leave_id | m2o edu.leave，required，ondelete='cascade'，index | 被转交的单 |
| stage | Selection [('first','一级'),('second','二级')]，required | 转的是哪一级 |
| from_user_id | m2o res.users，required | 转出人 |
| to_user_id | m2o res.users，required | 转入人 |
| reason | Text，**required** | 「为什么转」（留痕三要素之一） |
| create_date / create_uid | Odoo 自带 | 「何时 / 谁操作」 |

⚠ 本文件**只有模型与字段**，没有任何转交资格校验：
   ① 候选人必须在同层候选集合内（一级 = 其他班班主任 ∪ 教务处组；
      二级 = 教务处组 ∪ 系统组）、② 不能转给自己、③ 不能转给申请人本人、
   ④ 提交时二次校验仍在候选集合内、⑤ 写 edu.audit.log（动作名「请假审批转交」）、
   ⑥ 改写 edu.leave.first_approver_id / second_approver_id
   —— 全部由 **S2** 在 models/leave_flow.py 的 `edu.leave.transfer()` 里实现（§4.3）。
   唯一性**不在这里判**：由本文件的 UNIQUE 约束在数据库层兜底（撞约束即回滚）。
"""
from odoo import fields, models


class EduLeaveTransfer(models.Model):
    """一次转交 = 一行；同一张单的同一审批级**最多一行**（UNIQUE 兜底）。"""

    _name = 'edu.leave.transfer'
    _description = '请假转交审批留痕'
    _order = 'create_date desc, id desc'

    leave_id = fields.Many2one(
        'edu.leave', string='请假单', required=True, index=True,
        ondelete='cascade',
        help='被转交的那一张单。删单即删其转交留痕（§4.2）。')
    stage = fields.Selection(
        [('first', '一级'),
         ('second', '二级')],
        string='审批级', required=True,
        help='转的是哪一级：一级 = 班主任（无班主任时为教务处）；'
             '二级 = 教务/系统（§3.2）。')
    from_user_id = fields.Many2one(
        'res.users', string='转出人', required=True, index=True,
        help='原审批人。转交后**他不能再批这一级**（§4.3(2) 的判据替换）。')
    to_user_id = fields.Many2one(
        'res.users', string='转入人', required=True, index=True,
        help='接手审批的人。必须是同层候选集合内的人（§4.3(1)）。')
    reason = fields.Text(
        string='转交原因', required=True,
        help='为什么转（留痕三要素之一，用户逐字要求）。为空不允许提交。')

    # 「只能转 1 次」落在**数据库级**（§4.2）：不是 if 判断，撞约束即事务回滚。
    # 属性名刻意叫 transfer_once，使库内约束名可读：
    #   edu_leave_transfer_transfer_once
    _transfer_once = models.Constraint(
        'UNIQUE (leave_id, stage)',
        '同一张请假单的同一审批级只能转交 1 次。')
