# t13 评审报告：t7 重复劳动自动化
> **状态**：`归档` ｜ **主题**：`成绩留痕评审` ｜ **取代**：`t35-review-t7-round2.md` ｜ **核对**：`2026-09-26`
> ⚠️ 本文已被 [`t35-review-t7-round2.md`](t35-review-t7-round2.md) 取代，请优先阅读后者。

> **后续（2026-09-12 队长授权补记）**：本文 5 条 findings 中 **F1–F4 已由 t34 修复**，经 **t35 复评 pass**（见 `docs/plans/t35-review-t7-round2.md`）；F5 经队长裁决保留。
> 本文保留**第一轮判定**作为历史记录，其 verdict=needs_revision 不代表 t7 当前仍有未解决项——**请勿只读本文就把它记成未解决项**。

> 评审人：study-eng ｜ 被评审：t7（flow-eng）｜ 依据：t13 契约（kind=review）
> 方法：读**提交态**代码（`git show 448d8b4` 与工作区）逐条对照 t7 自身 acceptance；
> 并特别复核队长指定的 6 个风险面。评审只读，未修改任何 `custom_addons/` 文件。

## 1. 结论（verdict）

**needs_revision** —— 功能**已交付且大体正确**，但有 2 项必须修正才可视为满足验收：
① 验收 #1 明确要求「附**操作前后计数证据**」，交付物中没有该证据；
② t7 output 声称「改分统一走 `edu_apply_marks` **唯一入口**…三条路径全部留痕」，
   该保证**只靠约定、不靠构造**：经模型边界的直写（含**后台成绩录入**）会**不产生留痕**。

另有 3 条**先存性问题**（非 t7 引入，但被 t7 的批量端放大），建议另立任务。

## 2. 逐条 acceptance 判定

| # | acceptance | 判定 | 证据 |
|---|---|---|---|
| 1 | 三个审批列表均可批量通过与批量驳回（**附操作前后计数证据**） | **部分不通过** | 路由齐备且有**门禁对等**（见 §3.1）；`_bulk_loop` 逐条 savepoint 隔离、返回 成功/失败/跳过 并写审计行。**但交付物无「操作前后计数」证据**：t7 output 的门禁只列 ux_v3_route_matrix 与 notice_privilege_smoke，无批量审批的前后计数实测 |
| 2 | 成绩批量保存 + CSV 导入导出，且改分有 tracking 留痕 | **部分不通过** | 三条**门户**路径（行内批量保存 / CSV 导入 / 上期复制）确实都经 `edu_apply_marks` 留痕（registration.py:393-421）；但**留痕未在模型边界强制**（见 §3.2 F1），后台直写不落痕 |
| 3 | 公告可套模板并定时发布；考勤可复制上次记录并支持 Excel 补录 | **通过** | `_cron_publish_scheduled` 一次性消费正确（`publish_at = False`，notice.py:84-110）；考勤两段式导入 + `?copy=1` 预填 |
| 4 | 在读证明/成绩单自助下载；报课有先修/学分/容量前置校验 | **通过** | registration.py 的先修/学分/容量校验；报表与模板在 views/roles.xml |

**inScope 合规**：t7 提交 `448d8b4` 改动 **8 个文件，与 t7 inScope 的 8 项完全一致**，**无越界文件**。

## 3. 队长指定 6 个风险面的复核结论

### 3.1 权限与越权：批量 vs 单条**门禁对等**——对等情况属实

逐对比较（bulk 与 single 用**同一**门禁表达式）：
- 请假：`/leave/set_state_bulk`(roles.py:1755) 与 `/leave/set_state`(roles.py:880) 均为
  `fac = current_faculty(); if not fac and not privileged_staff(): redirect`；
- 申诉：`/grievances/set_state_bulk`(1795) 同型；
- 选课：`/registrar/subject/set_state_bulk`(enroll.py:458) 同型。

**结论：批量未绕过单条门禁**（队长最担心的那条不成立）。批量反而**更严**：驳回强制填原因
（bulk 拒绝空原因，single 允许留空"保持旧行为"）—— 见 F5。

### 3.2 留痕完整性（队长 #5）：**F1 —— 未覆盖所有改分路径**

`custom_addons/edu_portal/models/exam_session_ext.py:23-41` 的
`OpExamAttendees.write()` **已经在拦截 marks 变更**（用于发成绩通知），但它**只发通知、不写
`edu.grade.history`**。因此任何**经模型边界的直写**——最现实的是**后台（Odoo webclient）
直接改 `op.exam.attendees.marks`**——会：通知学生 ✓ / 留痕 ✗。

t7 的 claim（"唯一入口"）因此**不成立**：拦截点已存在且看得到这些变更，只是没在那里留痕。

### 3.3 幂等与重放：通过
- 批量审批只处理 `state == 'request'`，非待处理计入"跳过"（roles.py:1761 附近），重复提交不会重复流转；
- `_cron_escalate_pending` 以 `escalated_at` 去重（leave.py:128-152），重复跑安全；
- 成绩 `edu_apply_marks` 对「无变化」返回 `''` 且不写 history（registration.py:405-406），重放安全。

### 3.4 CSV 导入安全性：两段式成立，但**范围门禁偏弱**（F2）
两段式（预览 → 确认）**存在**且逐行回执（`valid/invalid`、逐行 errors）。
但**确认段只校验 `att.exam_id.id == exam.id`**，而 `exam_id` 直接取自请求，
门禁仅 `current_faculty()`——**不校验该教师是否教这门课**（roles.py:2024-2050）。

### 3.5 "半截失败"：**设计正确**
`_bulk_loop`（roles.py:1728-1743）逐条 `with request.env.cr.savepoint()`，
单条异常只记入 `failures` 并**回滚该条**，同批其它条继续 → 不会"批量失败留半截"。
导入 commit 同样逐条 savepoint（2050）。这是本任务做得最扎实的一处。

### 3.6 定时任务：**通过**
一次性语义正确（发布后 `publish_at=False`，不会被反复复活）；`active=False` 作"未发布"载体，
到点前不进任何列表——规避了"改 batch2 列表"的连带改动。escalate cron 幂等见 3.3。

## 4. findings

| id | severity | problem | requiredFix | file | line |
|---|---|---|---|---|---|
| F1 | medium | `OpExamAttendees.write()` 已拦截 marks 变更但不写 `edu.grade.history` → **后台/直写改分不留痕**；与 t7「唯一入口、全部留痕」的表述不符 | 二选一：**(a)** 在该 `write()` 内补写 history（该文件不在 t7 inScope，需队长授权或另立任务）；**(b)** 修正 claim 为「三条门户路径已留痕；后台直写路径未覆盖」 | custom_addons/edu_portal/models/exam_session_ext.py | 23-41 |
| F2 | medium | 成绩导出/导入/确认/复制均以请求传入的 `exam_id` 为准，仅 `current_faculty()` 放行，**不校验教师对该考试的归属** → 任意教师可改任意考试分数（新导入端把单页写入放大为批量写入） | 抽出 `_teacher_exam(exam_id)`（口径参考既有 `_teacher_assignment`）并在这 4 个路由统一使用；**注意这是先存问题**（t7 前的 `/grading/save` 同样只校验 `att.exam_id == exam_id`），建议另立任务而非退回 t7 | custom_addons/edu_portal/controllers/roles.py | 2024-2050 |
| F3 | low | 批量审批以 `_posted_ids` 取 id 后仅按 `state` 过滤，**"谁能批这条"的限定完全依赖列表 UI**；构造 ids 可越过列表范围批量处置 | 与 F2 合并处理：在 browse 之后按审批人可作用范围过滤；若判定为可接受风险，请在 output 显式声明 | custom_addons/edu_portal/controllers/roles.py | 1713-1724 / 1755-1800 |
| F4 | medium | 验收 #1 明写「附操作前后计数证据」，交付物**无该证据** | 补一次批量审批的前后计数实测（pending N → 处理后 pending N-m），贴进 output | — | — |
| F5 | low | 驳回原因：批量**强制**、单条**可空**，同一动作两种策略 | 对齐策略（建议单条也必填，或批量放宽为可选并说明理由） | custom_addons/edu_portal/controllers/roles.py | 1778-1783 vs 895-900 |

## 5. 值得肯定的部分（应保留）

1. **逐条 savepoint 的批量隔离**——"单条失败不影响同批其它条 + 逐条原因回执"是正确设计，直接消灭了"半截失败"。
2. **一次性的定时语义**（`publish_at=False`）+ `active=False` 作未发布载体，改动面最小。
3. **改分留痕选型正确**：自建 `edu.grade.history`（action/logged_user/old_marks/new_marks/source/timemodified）与调研 §4.3 的 Moodle `grade_grades_history` 语义一致，是国内三家 SaaS 的空白点。
4. **门禁对等**与**零越界文件**——批量端没有走捷径，值得作为后续批量功能的范式。
5. 两段式导入 + 逐行回执沿用仓内 `/edu/import/students` 既有范式，未另造一套。

## 6. 评审边界（如实声明）

- 本报告为**代码级与提交级**评审：未在共享库上执行批量审批/成绩导入的**写操作实测**（避免污染他人测试数据），故 acceptance #1 的"前后计数"我判定为**证据缺失**而非"功能不成立"——机制我已在代码层逐行核对。
- F2/F3 经 `git show 7b43a49`（t7 前）对照确认**先存**，不是 t7 回归；F1 的修复点也不在 t7 inScope。因此本报告的 needs_revision **只要求便宜的两项**（F4 补证据、F1 择一修正），F2/F3/F5 建议另立任务。
