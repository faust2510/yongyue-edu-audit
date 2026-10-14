# 评估中心 · 详细设计稿（v2-P2，待确认）
> **状态**：`归档` ｜ **主题**：`评估中心 v2-P2` ｜ **取代**：`evaluation-rebuild-design.md` ｜ **核对**：`2026-10-06`
> ⚠️ 本文原写「待用户确认后实施」，实际已于 `74c1c99` 交付（2026-09-26 核对发现）。正文未改动。
> ⚠️ 本文已被 [`evaluation-rebuild-design.md`](evaluation-rebuild-design.md) 取代，请优先阅读后者。

> 状态：⏸ 待用户确认后实施 ｜ PRD：`教务系统网站/行政管理系统功能/方案-老师端评估中心.md`
> 原则：不照搬任何源码；AI 红线遵守（无 AI 评分）；单系统（Odoo）内实现

## 一、三大评估 → 统一引擎

| 评估 | type_code | 对象 | 特性 | 等级线 |
|---|---|---|---|---|
| 新生综合测试 | `freshman` | 新生 | 录取/分班依据 | 可配 |
| 入学学生综合评估 | `student` | 在读学生 | 百分制日常记分驱动 | 60及格 / 90优秀 |
| 实习同工评估 | `intern` | 实习学生 | **三维度**：自评/TA评/牧者评，权重可配 | 60及格 / 80优异 |

## 二、模型（edu_portal/models/evaluation.py）

```
edu.eval.template   评分模板
  ├─ name / type_code(3选1) / total(默认100)
  ├─ pass_line / excellent_line        ← 等级线可配
  ├─ visible_to_student(bool)          ← intern 默认 False（仅教务可见）
  └─ line_ids → edu.eval.template.line
       ├─ name(评分项) / max_score / sequence

edu.eval.task       评估任务（一个学生×一模板×一维度=一张"表"）
  ├─ template_id / student_id / evaluator_type(self|ta|pastor|teacher)
  ├─ period(char, 如 2026秋) / state(draft→scoring→done)
  ├─ score_ids → edu.eval.score(task 内逐项打分)
  ├─ total_score(compute=Σscore) / grade(compute 按模板等级线)
  └─ approved_by / approved_date                        ← admin 审批留痕

edu.eval.score      打分明细
  └─ task_id / template_line_id / score  （0 ≤ score ≤ max_score 校验）
```

并发与幂等：score 唯一约束 UNIQUE(task_id, template_line_id)；
Excel 式表格整表 POST，控制器 upsert（存在即更新），事务包裹。

## 三、门户页面（teacher/admin 视角）

| 路由 | 页面 | 要点 |
|---|---|---|
| `/my/evaluation` | 评估中心首页 | 统计卡（任务数/待办/已完成）+ 任务列表（按类型筛选）+「新建评估」入口 |
| `/my/evaluation/new` GET/POST | 新建向导 | 选模板→选学生→维度→生成空白打分表 |
| `/my/evaluation/task/<id>` | **Excel 式打分表** | HTML 表格行=评分项，单元格 number 输入，实时小计 JS；整表保存 POST 幂等 upsert |
| `/my/evaluation/results` | 成绩汇总 | 按学生聚合总分/等级；**雷达图**（Canvas 自绘轻量实现，无外部 CDN）；导出 CSV 按钮 |
| `/my/evaluation/radar/<student_id>.json` | 雷达数据接口 | 各维度平均分（仅教务可访问 intern 数据） |

权限：teacher/admin 可建与打分；`approve/close/delete` 仅 admin；
学生端只读自己的 `student` 型结果（intern 结果对学生隐藏）。
所有写路由 csrf + 服务端身份校验；deny-by-default ACL（portal 全 0）。

## 四、后台管理（admin）

根菜单「评估中心」seq71：模板管理（含评分项行编辑）/ 评估任务 / 成绩查询(pivot+导出)。

## 五、种子

三套预置模板（含评分项）：学生日常表现记分表（对接奖惩加减分项）、实习三维评估、新生测评——均【演示】标记。

## 六、验收清单

- [ ] 教师建任务→Excel式打分→保存→总分/等级自动正确（边界：59/60/89/90）
- [ ] intern 三维任务同一学生各一份，汇总页权重呈现
- [ ] 雷达图按维度渲染且数值与明细一致
- [ ] 学生只见自己 student 型结果；intern 对学生不可见
- [ ] admin 审批流与删除权限生效
- [ ] 种子幂等；四角色截图存档
