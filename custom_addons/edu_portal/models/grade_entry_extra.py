# -*- coding: utf-8 -*-
"""成绩录入「手工加人」—— 名单第 ③ 条来源的快照表（2026-10-13）。

## 为什么必须有它（生产事实，只读读数）

生产 `op_student` 51 人 / `op_student_course` 45 行 ⇒ **6 名学生（id 25/30/39/40/54/56）
一行 `op.student.course` 都没有**：门户 `/grade-entry` 的名单只有「①班级名单」「②报课未分班」
两条来源（`controllers/grade_entry.py` 的 `_roster`），两条都读 `op.student.course`
⇒ 这 6 人**永远进不了任何成绩网格**；科目最多的总览班（batch 34，14 科）也是 0 学生 ⇒ 空网格。
用户已拍板：报课为主 + **教务可手工加人**（`docs/plans/gradebook-center-design.md` §4.2）。

## 为什么单独一张表，而不是写 op.student.course

「加进成绩名单」≠「改学生的班级归属」：`op.student.course` 是**学籍/分班的事实**，
教师无权改；教务改它还会波及考勤、课表、费用等全部下游。故这里只落一条**成绩侧快照行** ——
只影响 `/grade-entry` 的名单，`op.student.course` 一个字节都不写（不越权改学生档案）。

## 四元组唯一 = (班级, 学期, 科目, 学生)

同一格重复加人没有意义，唯一性必须是**数据库级**：Odoo 19 里旧 `_sql_constraints`
会被框架**静默忽略**（实测记录见 `models/alert_read.py:29` 与 `models/leave_transfer.py:15`），
故用 `models.Constraint`。

## 学期为什么必填

名单按 (班, **学期**, 科目) 定位（设计稿 §4.2 的四元组）。学期为空时「下次重开本页还会不会
看到这个人」就没有判据 —— 宁可拒绝加人（控制器回 `err=noterm`），也不落一条无法对账的行。
"""
from odoo import fields, models


class EduGradeEntryExtra(models.Model):
    """一条 = 「把某人手工加进 (班, 学期, 科目)」的快照，删行 = 从名单移除。"""

    _name = 'edu.grade.entry.extra'
    _description = '成绩录入手工加人'
    _order = 'batch_id, subject_id, student_id'

    batch_id = fields.Many2one(
        'op.batch', string='班级', required=True,
        ondelete='cascade',
        help='加进哪个班的成绩名单。班级没了这条快照就没有意义（级联删）。')
    term_id = fields.Many2one(
        'op.academic.term', string='学期', required=True,
        ondelete='cascade',
        help='四元组之一：同一班同一科，不同学期的名单互不影响。')
    subject_id = fields.Many2one(
        'op.subject', string='科目', required=True,
        ondelete='cascade')
    student_id = fields.Many2one(
        'op.student', string='学生', required=True, index=True,
        ondelete='cascade',
        help='在册学生（任意，不要求已分班 —— 这正是本表存在的理由）。')
    added_by = fields.Many2one(
        'res.users', string='加人操作人', index=True, ondelete='set null')
    added_at = fields.Datetime(
        string='加人时间', default=fields.Datetime.now, required=True)
    note = fields.Char(
        string='备注', size=128,
        help='为什么手工加人（例如「转班待定」「补录」），给下一位教务看。')

    # Odoo19 新约束 API（旧 _sql_constraints 会被框架静默忽略）
    _entry_extra_uniq = models.Constraint(
        'UNIQUE (batch_id, term_id, subject_id, student_id)',
        '同一班级、学期、科目下，同一名学生不能重复加人。')
