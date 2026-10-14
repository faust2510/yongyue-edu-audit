# 实施代理 X · B3 考试详情页（/student/exam/data/<id>）

日期：2026-08-23　范围：缺口清单 B 包第 3 项（SUMMARY.md:34）
改动文件（仅 2 个，符合铁律）：
- `custom_addons/edu_portal/controllers/batch1.py`（新增 考试详情 段，batch1.py:391–454）
- `custom_addons/edu_portal/views/batch1.xml`（2 处死链接上 + 新模板 `edu_exam_data`）

## 1. 控制器（batch1.py）
- `GET /student/exam/data/<int:eid>`，`type='http' auth='user' website=True`，与同文件其它学生页一致。
- 归属校验 `_own_exam(eid)`（参照 assignment 详情 `_own_assignment` 写法）：
  - `op.exam.sudo().browse(eid)` + `.exists()` 不存在 → 重定向 `/student/exam`；
  - 通过 `current_student()/student_course()` 取课程/班级，满足
    `exam.course_id == course` **或** `exam.batch_id == batch`
    **或** 该生在 `op.exam.attendees` 有本场应试记录，三者其一放行；否则重定向列表。
- 取数：该生 attendees 记录（status present/absent + marks），沿用列表口径
  `marks is not False` 判定有分；百分比、及格判定（>= min_marks）复用列表算法。
- 状态 pill 的文案与配色映射为类常量 `EXAM_STATE_LABEL / EXAM_STATE_CLASS`
  （draft/schedule/held/result_updated/done/cancel → 草稿/已排期/已举行/已出成绩/已完成/已取消）。

## 2. 视图（batch1.xml）
- 死链修复 ×2：列表卡标题 `<a class="oe-exam-title">`（原 t-att-href 自链回列表）
  与「查看详情」按钮 `<a class="oe-exam-btn">` 均改为
  `t-attf-href="/student/exam/data/{{ card['exam'].id }}"`。
  其余 `/student/exam?sortby/filterby/groupby=` 为列表自身控件，属正常保留。
  全文件无 href="#"（grep 验证）。
- 新模板 `edu_exam_data`（同文件，t-call edu_portal.edu_page）：
  - 头部：考试名 + 科目/课程/班级 + 状态 pill；
  - 信息卡：开始/结束时间（_fmt_dt）、总分、及格分、备注（可选）；
  - 成绩行三态：有得分 → 得分 X/总分 + 百分比进度条（复用 oe-exam-bar）+
    及格 pill + 出席状态；有记录无分 → oe-empty「成绩尚未公布」；
    无记录 → oe-empty「未参加本场考试」；
  - 底部「返回考试列表」按钮。

## 3. 自查
- [x] 路由注册位置：控制器内考试段之后、作业段之前，装饰器风格与同文件一致
- [x] 模板 id 同文件：edu_exam_data 在 batch1.xml 内，无需改 manifest
- [x] 归属校验：不存在/非本人课程班级且无应试记录 → 302 回列表
- [x] 无 docker/odoo/curl 执行；仅本地 py_compile + minidom 解析均通过
- 未做浏览器实测（铁律禁 docker）；QWeb 表达式均为既有模式（{{ }}、min() 已在同文件使用）
