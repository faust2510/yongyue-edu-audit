# -*- coding: utf-8 -*-
"""成绩等级（op.result.line.grade）的口径修复 —— 基座缺陷覆盖。

## 为什么需要这份覆盖（读源码确认，不是猜）

基座 openeducat_exam 的 op.result.line._compute_grade 有两处问题：

  ① **缺 break**：循环对"不匹配"的档位写 else: record.grade = None —— 命中的档位只要
     不是最后一档，后面的档位就会把它重新清成 None。七档（A+ / A / B / C / D / E / F）下
     **只有落在最后一档（F）才留得下值** ⇒ 实际表现是「考 74 分，等级显示空」。
     对照：op.marksheet.line._compute_grade 在命中后 break，所以卡片级等级是对的 ——
     同一份阈值字典、两处口径，本仓已把它记为待避坑点
     （docs/research/gradebook-entry.md 第 10.2 节）。
  ② **口径与 marksheet 不一致**：这里拿 marks（原始分）去比 min_per / max_per（**百分比**
     阈值），而 marksheet 那一侧比的是 percentage ⇒ 满分不是 100 的考试会串档。

## 本文件只改这两处

换成 **percentage 口径 + 命中即停**；阈值字典仍然是
marksheet_line_id.marksheet_reg_id.result_template_id.grade_ids（唯一字典 =
op.grade.configuration 七档，不新造第二套映射）。
满分 100 的容器（门户「成绩录入」建的、以及基座自己的考试）两种口径同解，
所以这条修复对既有数据是**无差异**的；只有满分 ≠ 100 的考试才从"串档"变为"按百分比"。

放在 custom_addons 里 _inherit 覆盖（code-map §3：基座快照原则上不改，改也在
custom_addons 里继承/extending）。
"""
from odoo import api, models


class OpResultLine(models.Model):
    _inherit = 'op.result.line'

    @api.depends('marks', 'exam_id.total_marks', 'evaluation_type',
                 'marksheet_line_id.marksheet_reg_id.result_template_id.grade_ids')
    def _compute_grade(self):
        for record in self:
            record.grade = None
            if record.evaluation_type != 'grade':
                continue
            grades = (record.marksheet_line_id.marksheet_reg_id
                      .result_template_id.grade_ids)
            total = record.exam_id.total_marks or 0
            if not grades or not total:
                continue
            pct = 100.0 * (record.marks or 0) / total
            for grade in grades:
                if grade.min_per <= pct <= grade.max_per:
                    record.grade = grade.result
                    break
