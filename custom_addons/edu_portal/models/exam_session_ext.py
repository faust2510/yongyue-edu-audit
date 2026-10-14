# -*- coding: utf-8 -*-
"""考试场次扩展：支持「线上考试」（v2 用户反馈）+ 成绩录入通知（辅助增强包 2a）。

- 勾选线上后，场地不再必填；未勾选则维持原必填校验。
- op.exam.attendees.marks 变更 → 站内信告知学生（门户录入与后台编辑同一入口）。
"""
import logging
import sys

from odoo import fields, models

_logger = logging.getLogger(__name__)


class OpExamSession(models.Model):
    _inherit = 'op.exam.session'

    online = fields.Boolean(
        string='线上考试',
        help='勾选后本场考试在线上进行，无需填写场地。')


class EduGradeHistoryExt(models.Model):
    """成绩留痕扩展：source 增加「后台直改」取值（t34 F1）。

    放在本文件而不改 models/registration.py —— t34 的 inScope 只有本文件与
    controllers/roles.py；用 selection_add 扩展取值，不重定义字段。
    """
    _inherit = 'edu.grade.history'

    source = fields.Selection(
        selection_add=[('backend', '后台直改')],
        ondelete={'backend': 'set default'})


class OpExamAttendees(models.Model):
    _inherit = 'op.exam.attendees'

    MARK_ENTRY_KEY = 'edu_marks_entry'

    def _via_managed_portal_path(self):
        """本次写入是否由受管入口（EduGradeHistory.edu_apply_marks）发起。

        门户三条路径（页面保存 / CSV 导入 / 上期复制）自己会写一条带 source
        的留痕；模型侧不再重复记一条 backend 留痕。

        t42：判定从**调用栈扫描**（t34 临时方案：用 sys._getframe 向上找
        edu_apply_marks，栈深 > 8 或中间多包一层就漏判 → 双记）改为
        **context 标记**：由 edu_apply_marks 在写入前 with_context() 声明。
        好处：与调用深度/包装层数无关，间接调用（helper → helper → 入口）
        也能正确传播，且不再依赖 sys 内省。
        """
        return bool(self.env.context.get(self.MARK_ENTRY_KEY))

    def write(self, vals):
        before = {r.id: r.marks for r in self} if 'marks' in vals else {}
        res = super().write(vals)
        if not before:
            return res
        # t34 F1：模型边界（后台 webclient 直改分）也要留痕 —— 与门户三条
        # 路径同一张表、同一字段口径；门户路径自带留痕，故跳过避免双记。
        log_history = not self._via_managed_portal_path()
        for rec in self:
            if before.get(rec.id) == rec.marks:
                continue
            if log_history:
                try:
                    old_marks = before.get(rec.id)
                    self.env['edu.grade.history'].sudo().create({
                        'exam_id': rec.exam_id.id,
                        'student_id': rec.student_id.id,
                        'old_marks': old_marks or 0,
                        'new_marks': rec.marks or 0,
                        'action': 'create' if old_marks in (0, False, None)
                                  else 'update',
                        'source': 'backend',
                        'logged_user_id': self.env.uid,
                        'note': '后台/模型边界直写',
                    })
                except Exception:
                    _logger.warning('grade history(backend) failed att=%s',
                                    rec.id, exc_info=True)
            user = rec.student_id.user_id
            if not user or user.id == self.env.uid:
                continue
            exam = rec.exam_id
            self.env['edu.message']._notify_event(
                'grade_result', user,
                '【成绩通知】您的考试《%s》成绩已录入：%s 分。' % (
                    exam.name or exam.subject_id.name or '考试',
                    rec.marks))
        return res
