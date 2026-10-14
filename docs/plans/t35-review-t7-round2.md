# t35 复评报告（round 2）：t13 findings 的修复核验
> **状态**：`归档` ｜ **主题**：`t7 复评核验` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 评审人：study-eng ｜ 被评审：t34（repair-round-2，flow-eng）｜ 上游：t13 needs_revision
> 方法：**独立复跑关键行为**（不只看 t34 的自述），并对未独立复跑的部分显式标注证据来源。

## 1. 结论（verdict）：**pass**

t13 的 5 条 finding 中，**F1/F2/F4 已修复且可验证**，F5 经队长裁决保留，**F3 按期完成两处、第三处按期外（已披露）**。
未发现阻塞项；以下 3 条为**不阻塞的遗留项**，建议随 t14 一并处置（见 §4）。

## 2. 逐条核验

| finding | 状态 | 我的核验方式 | 结论 |
|---|---|---|---|
| **F1** 模型边界不留痕 | **已修复** | **独立复跑**（odoo shell，事务内 rollback） | 门户路径经 `edu_apply_marks` → 新增留痕 **= 1 条**（source=manual，**无双记**）；模型边界直写 → 新增 **= 1 条**（source=backend，note=后台/模型边界直写）。rollback 后该组合留痕数回到原值 6，零残留 |
| **F2** 成绩端点缺考试归属 | **已修复** | 代码级确认 + 采信 t34 断言 | `_teacher_exam_domain`(roles.py:688) / `_teacher_exam`(703) 落地；覆盖 entry/save/export/import×2/copy_prev 六处；t34 断言「越权 save → 303 且 DB marks 仍 60」。**我未独立复跑六端**（共享库写操作），标注为采信 |
| **F3** 批量 id 无作用域 | **部分修复** | 代码级确认 | `_approval_scope_domain`(645)/`_scoped_record`(663)/`_scoped_records`(675) 落地，覆盖**请假与申诉**两条批量路由；**第三条（选课审批）仍无收窄** —— enroll.py:458 的 `set_state_bulk` 未见任何 scope 调用。t34 已如实披露（enroll.py 不在其 inScope） |
| **F4** 缺前后计数证据 | **已修复** | 采信 t34 数据 | 请假「待审批 3→1、已通过 2、ok=2」；成绩导入「92→85、留痕 0→1（92->85/import）」；残留用 `active_test=False` 复核归零 |
| **F5** 驳回原因策略不一致 | **保留（裁决）** | 队长裁决 + 代码未改 | 批量更严是有意为之；t34 已写入 acceptanceResults 成文 |

**文件越界检查**：t34 只触及 `models/exam_session_ext.py` 与 `controllers/roles.py`，与其 inScope 一致，**无越界**。

## 3. F1 的实现取舍（我实测有效，但有脆弱性）

实现：`OpExamAttendees.write()` 内以 `_via_managed_portal_path()` 判定调用是否来自 `edu_apply_marks`（**检查调用栈帧名** `frame.f_code.co_name == 'edu_apply_marks'`）。

- 实测行为正确（见 F1 行）；
- 但该判定把正确性**耦合在一个函数名上**：若 `edu_apply_marks` 被重命名/包装/内联，门户路径会**静默变回双记**（后果是审计噪声，不是数据丢失）；
- t34 已主动披露「更干净的是由 `edu_apply_marks` 传 context 标记，但需改 `models/registration.py`（不在其 inScope）」——**我认为这个自评是准确的**，故不计为缺陷，列为遗留项。

## 4. 遗留项（不阻塞，建议随 t14 处置）

1. **F3 第三处**：`enroll.py` 的 `/registrar/subject/set_state_bulk` 仍无作用域收窄 → 建议另立任务（inScope 仅 enroll.py），或在交付报告「已知取舍层」显式记录。
2. **F1 栈判定脆弱性**：建议另立小任务（inScope 仅 `models/registration.py`）改为 context 标记；届时栈判定可删除。
3. **⚠️ 工作区未提交**：`git status` 显示 `controllers/roles.py` 与 `models/exam_session_ext.py` 处于 **modified 未提交**状态。t21 曾因同样情形被我提醒过，这次影响更直接——**t14 集成交付前必须入库**，否则这批修复不在提交树上。

## 5. 评审边界（如实声明）

- **独立复跑**：F1（双记/边界留痕，事务内 rollback 零残留）。
- **采信 t34 证据**：F2 六端的越权断言、F4 的前后计数（均为其自测结果，我未在共享库重跑写操作）。
- **代码级确认**：F2/F3 助手落地与调用点、文件越界、F1 实现形态。
- 未做：端到端 HTTP 越权实测（避免共享库写操作与他人在跑的门禁冲突）。
