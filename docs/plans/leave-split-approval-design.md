# 设计：请假单拆分 + 分级审批 + 转交审批
> **状态**：`已上线` ｜ **主题**：`请假拆分与分级审批` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「本文档只设计，不含任何实现」，实际已于 `2fe14e9` 交付（2026-09-26 核对发现）。正文未改动。

> **本文档只设计，不含任何实现**；不改 `custom_addons/`、不改 `openeducat_erp/`、不部署、不 commit。
> 调研依据（铁律 0）：`docs/research/leave-approval.md`（Odoo 19 源码 + OCA + 钉钉官方 + 本仓源码 + 生产只读库）。
> 需求来源：校长原话「把请假条分为学生请假单和教职人员请假单…学生请假时长在三天内由当班教职同工负责审批，三天以上的假期需要上报给教务长…需要给教师开通请假条转交审批功能」+ 一轮逐条答复 + 队长最终裁决。
> 版本：定稿 2026-09-25。

---

## 0. 先看清家底（决定设计形态的 5 条硬现实）

| # | 现实 | 一手出处 | 对设计的影响 |
|---|---|---|---|
| R1 | **本仓没有「班主任」字段** | `models/registration.py:366` 原文「本仓无「班主任」字段，取课节 faculty 去重」；全仓 grep `班主任\|homeroom\|head_teacher\|class_teacher\|tutor` 只有 2 处注释、0 个字段 | 班主任必须**新建字段**；且必须允许为空 |
| R2 | **教师名单也没有**：`op_faculty` 全表 **1 行且 `active=false`**（0 个在职教师）；`op_session` 216 行的 `faculty_id` 只有 **1 个不同值（=20，就是那行 inactive 的）** | 生产只读库实测 | 任何"按任课老师批"的方案今天都跑不通；**必须做到"没有班主任也能跑"** |
| R3 | **「教务长」实体不存在**：`res_groups` 88 行全表无该组/用户 | 生产只读库实测 | 二级审批只能落到**教务处组**（3 人：`backoffice@local`/`jiaowu@local`/`admin`） |
| R4 | **条例 PDF 里没有教职员工请假条款**（文件名"员工请假条例"，正文是《请假条例》学生版，96 行正文里 0 条讲员工） | `pdftotext -layout` 全文核对（MD5 `71afe09739208685ed8f6f0d7c10cb06`） | 教职单**只能按学生条例同构推定**（见 §5.4），并把推定过程写清 |
| R5 | 学生 29 人，其中**只有 24 人**有 `op_student.course.batch_id`（5 人无班）；**0 人跨多班** | 生产只读库实测 | "取哪个班"必须给空值口径（无班 ⇒ 同"无班主任"分支） |

### 0.1 已存在且**不要**重造的东西

| 能力 | 本仓现成实现 | 本次怎么用 |
|---|---|---|
| 审批代理（带时间窗） | `edu.approval.delegate`（`models/leave.py:207-253`） | **并存不改**（§4.1），转交是新东西 |
| 超时提醒 | cron 39 + `_cron_escalate_pending()`（48h，幂等） | **保留**；语义不动（它只提醒教务处，不切换审批人） |
| 班级→教师账号解析 | `registration.py:378-387` `_ccr_faculty_users()`（双向并集） | **抄这条口径**，不另写一套 |
| 身份反查 | `edu_schedule/models/identity.py`（全仓唯一口径，code-map §6 第 13 条） | 教职/学生分流必须走它 |
| 学期边界 | `op.academic.term`（2 行，第一学期 2026-06-23~12-20） | 事假学期配额直接算 |
| 天数字段 | `roles.py:1160-1162` 已用「`(to-from).days + 1`」= **含头含尾** | 与用户裁决天然一致，**复用不重写** |
| 审批留痕 | `approver_id / approver_kind / approved_at` + `_approver_vals()` | 沿用，新增字段只做增量 |

---

## 1. 需求基线与逐条裁决（**全部已锁定，无待裁决项**）

| # | 需求 / 裁决 | 来源 | 本文落点 |
|---|---|---|---|
| 1 | 单据拆成**学生请假单** / **教职人员请假单** | 校长原话 | §2 模型取舍 |
| 2 | **≤3 天 → 班主任（当班教职同工）批；>3 天 → 上报教务长批** | 校长原话 + 用户答复 4 | §3 |
| 3 | **「3 天」= 含头含尾、自然日**；「不用纠结工作日」 | 用户答复 4（逐字） | §3.4 |
| 4 | **「当班教职同工」= 班主任 / 班级导师** | 用户答复 2（逐字） | §5.1 |
| 5 | **「教务长」= 教务人员，账号就是 `backoffice@local`** | 用户答复 3（逐字） | §5.2 |
| 6 | **教师可以把自己待批的假单转交别人审批** | 校长原话 | §4 |
| 7 | 转交：**同角色互转 / 转交后原审批人不能再批 / 只能转 1 次 / 必须留痕（谁转给谁·何时·为什么）** | 队长裁决 C 组 | §4.3 |
| 8 | **员工请假条例不存在**（用户原话「我不知道，没有那个东西」）⇒ 教职单**参照学生条例同构** | 用户答复 + 队长裁决 1 | §5.4 |
| 9 | B 组 6 条全做：销假 / 证明材料 / 提前申请期（**软提示不硬拦**）/ 事假学期配额 ≤5 天（**超限自动升级教务处**）/ 禁止事后补假 / 类型按条例重做 | 队长裁决 B 组 | §7 |
| 10 | **没有班主任也要能跑**：有班主任→班主任批；没有→**直接落教务处**并在单据上显示「未设班主任，已转教务处」；老师到位后**只填数据**即生效 | 队长现实约束 a–e | §3.3 / §5.1 / §9.1 |

### 1.1 两条冲突口径的并列记录（**已裁决，但必须留档**）

条例 PDF「三·2 审批要求」逐字：「普通假期由**班级导师**审批；**跨一日以上假期**须由**教务处或学院主管**审批」→ 阈值 ≈ **1 天**。
用户口述：「**≤3 天**班主任、**>3 天**教务」→ 阈值 = **3 天**。

> ✅ **已由用户裁决：以 3 天为准。**
> PDF 里「跨一日以上」那句在本设计里**只作历史文本留存**，不参与任何实现；实现里唯一读到的阈值是系统参数 `edu_portal.leave_second_approval_days`（默认 3）。
>
> ⚠ 另有一处**无法用 3 天解释**的差异必须留档、**不能**被静默吸收：PDF 三·1 写「由班级导师/陪伴老师**签字**，再报**教务助理或教务处**审批」（= 串行两级），三·2 写「普通假期由班级导师审批」（= 一级即终）。用户裁决只解决了**阈值**，没解决**"普通假期是否还要教务复核"**。本设计的处理：按用户"≤3 天 → 班主任批"理解为**一级即终**（与钉钉"有且最多一个条件分支通过"的选择语义一致），把 PDF 三·1 的串行读法记为**未采纳口径**；改动点已收敛到 §3.2 的一个系统参数（`edu_portal.leave_always_two_stage`）。

---

## 2. 模型取舍（**推荐方案 A**）

### 2.1 三个候选

| 方案 | 形态 | 评价 |
|---|---|---|
| **A（推荐）** | **一张 `edu.leave` + `applicant_kind` 维度**（`'student'` / `'staff'`），`student_id` 变可空，新增 `applicant_user_id` | 见 2.2 |
| B | 两个模型 `edu.leave.student` / `edu.leave.staff` | 否决（见 2.3） |
| C | 复用 Odoo 核心 `hr.leave`（`hr_holidays`） | 否决（见 2.4） |

### 2.2 为什么是 A

1. **向后兼容成本最低**：既有 2 行（id 26/27，均 `refused`）只需迁移一个默认值；单号 `'001'` / `'SLR000001'` 原样不动；既有列表/详情/筛选全部继续工作。
2. **现有审批入口不用翻倍**（决定性）：本仓 **4 个审批写入口 + 3 个建单入口**，全在 `edu.leave` 上：
   - 写：`/leave/set_state`（`roles.py:1110`）、`/leave/set_state_bulk`（`:2002`）、后台 `action_approve/action_reject`（`leave.py:150-177`）、课代表 `rep_set_state`（`course_rep.py:689`）
   - 建：学生 `/my/time_off`、家长 `/my/child/<id>/leave/save`（`:1041`）、后台新建
   - 拆成两个模型 ⇒ 上述 **7 处 × 2**，且 `EduLeaveRepExt` 要复制一份（还要过 `check_view_xpath.py` 的 IMPORT-ORDER/CIRCULAR-INHERIT 门禁）。
3. **门户口径不用分裂**：`/my/time_off`（学生）、`/my/child/<id>`（家长）、`/leave/approvals`（教师/教务）、后台 497→498 全部读同一个模型；拆表后每张页都要 union 或加 tab。
4. **审批留痕字段只加一次**：`approver_id/approver_kind/approved_at` 的口径已经因为"4 个写入点必须一致"踩过一次（`leave.py:77-79` 注释原文），拆表会让这个口径分裂风险翻倍。
5. **单据类型的差异是"字段级"而非"结构级"**：学生单多出 `subject_id`（课代表）、`casual` 学期配额；教职单多出 `applicant_user_id`。差异 ≤ 5 个字段，用一个 `applicant_kind` + 视图分流完全够用。

**明确的逃生阀**：若后续字段差异 > 8 个（例如教职单要接薪酬/年假台账），**再**用 `_inherits` 把 staff 变体拆出去（Odoo 惯用法：共享底表 + 变体表），届时本次新增的字段名可原样保留。

### 2.3 为什么否决 B（两个模型）

除 2.2 第 2/3/4 条的"工作量翻倍"外，还有一条**正确性**理由：**跨类型统计会无解**。三件已存在的事都要求"一张单"的视角——① 首页提醒卡按 `my/time_off` 计数（`batch2.py` 的 `_ALERT_CARDS/_count_for_card`）；② `/edu/audit` 的「请假审批」模型列（`roles.py:82`）；③ `edu.audit.log` 的动作名（现已有「请假审批」×1、「请假批量审批」×7）。拆表后这三处都要改成"两个模型的并集"，属于纯粹的负债。

### 2.4 为什么否决 C（装 `hr_holidays` / 复用 `hr.leave`）

一手依据全部在 `docs/research/leave-approval.md` §2.2–2.3，摘要：

| 否决理由 | 依据 |
|---|---|
| 生产**没装** `hr_holidays`（=uninstalled）；装它会连带 `hr_work_entry` 等，并拉进整套 HR 后台菜单树 —— 与 2026-09-17 菜单收口（backoffice 可见根 = 12，**压线**）直接冲突 | 生产只读库 + `docs/code-map.md` §4.1 |
| 它的审批级别挂在**请假类型**上（`hr.leave.type.leave_validation_type` ∈ `no_validation/hr/manager/both`），**不挂在单上** ⇒ **做不出"同一类型按天数走不同审批人"** | `hr_holidays/models/hr_leave_type.py:83-90` |
| 它的第二级只有 `both` 才有，且**固定**是 "Employee's Approver → Time Off Officer" 两级 | `hr_leave.py:1410-1415` + 官方文档 `https://www.odoo.com/documentation/19.0/_sources/applications/hr/time_off/management.rst.txt` |
| **零转交**：全模块 `grep -rniE 'delegat\|substitut\|transfer'` = **0 命中** | 本机 `odoo:19` 源码 |
| 它是员工语义，审批人解析全挂 `hr.employee`；本仓学生 29 ≠ 员工 | `hr_leave.py:1500-1514` + 生产 `hr_employee` 仅 2 行 |
| license 虽为 LGPL-3（不传染），但**功能上根本不满足需求** | `hr_holidays/__manifest__.py` |

> 顺带排除 OCA：`OCA/hr-holidays@19.0` 只有 4 个模块（全 AGPL-3）且**都不是审批**；`OCA/server-ux@19.0` **没有** `base_tier_validation` 族（18.0 才有，AGPL-3）。详据见调研档案 §3。

---


## 3. 分级审批状态机

### 3.1 状态与流转

**`edu.leave.state` = 四态**（在既有三态上**只加一个** `pending_second`）。`request` 保留既有值（= 待一级审批），因此既有筛选 `filterby=request` 与首页计数**语义不变**。

```
                        一级通过 & 不需要二级 ─────────────► approved（终态）
                      ┌──────────────────────────────────►
建单 ──► request ─────┤
           ▲          ├── 一级驳回 ──────────────────────► refused（终态）
           │          │
           │          └── 一级通过 & 需要二级 ──► pending_second
           │                                        │  │
           │                          二级通过 ─────┘  └──── 二级驳回 ──► refused
           │                          ▼
           └─── 二级「退回」──────────┤（回 request，一级重批）
                                      └────────────► approved（终态）
```

**新增状态与原因（1 个）**

| 状态 | 含义 | 为什么需要 |
|---|---|---|
| `pending_second` | 一级已通过，等二级（教务）审批 | 不能复用 `request`——否则"待一级"与"待二级"在队列里分不开，一级审批人会看到自己已经批过的单 |

**不新增的状态（以及为什么）**

| 想做但**不做** | 理由 |
|---|---|
| `draft`（退回申请人改） | 既有模型**没有**草稿态，建单即 `request`；引入 `draft` 会打断全部既有筛选 + 首页计数 + `_leave_steps()` 进度条（`roles.py:1173-1193`）。申请人的修改路径沿用既有事实：**撤回**（= 写 `refused` + 原因，生产 id=27 就是这么产生的），然后重新建单 |
| `closed`（已销假） | 销假**不是审批裁决**，做成状态会污染 `filterby`。改为**正交字段**（§7.1） |

**「驳回回退」的两个动作要分清**（照钉钉的 拒绝 vs 回退 两个独立动作）：
- **驳回**（`refused`，终态）：裁决否定，通知申请人，可附原因（沿用既有 `reject_reason`）。
- **二级退回一级**（`pending_second` → `request`）：二级认为信息不全，退回一级重批；写 `second_sent_back_at` + `second_send_back_reason`，清空 `second_approver_id`。
- **不允许一级退回申请人**：本仓无 `draft`（见上表）。申请人要改 ⇒ 撤回 + 重建。

### 3.2 审批人解析（唯一的"谁该批"计算点）

新增 `models/leave_flow.py`，**唯一**路由函数：

```
def route_of(leave) -> RouteResult:
    """返回 RouteResult(
        first_users      : res.users 记录集   # 当前一级应批人（可为空集）
        second_users     : res.users 记录集   # 当前二级应批人（不需要二级时为空集）
        need_second      : bool
        fallback_reason  : str | None         # 如 '未设班主任，已转教务处'
    )"""
```

**判定表（学生单）**

| 输入 | 一级（`first_users`） | 需要二级？ |
|---|---|---|
| 学生所在班 `batch.homeroom_teacher_id` 非空 | **该账号** | `days > 阈值` **或** `over_quota` |
| `homeroom_teacher_id` 为空 | **教务处组 ∪ 系统组**；`fallback_reason='未设班主任，已转教务处'` | 同上 |
| 学生无 `op.student.course.batch_id`（本库 29 人里有 5 人） | **教务处组 ∪ 系统组**；`fallback_reason='该生未分班，已转教务处'` | 同上 |

**判定表（教职单）** —— 见 §5.4。

**"取哪个班"的口径**（本库 0 人跨班，但字段允许）：取该生 `op.student.course` 中 `batch_id` 非空、且 `batch.end_date` **最晚**的一条（与 `course_rep.py:181-203` `_batch_term_layers` 的"取最晚不早退"同一取舍）。
> ⚠ 该口径**只写在 `route_of()` 一处**，禁止散落（与 `course_rep.py` 文件头"权限判定的唯一事实源"同一要求）。

**二级审批人集合**：`① 系统参数 edu_portal.leave_principal_user_ids（逗号分隔 uid，可选，用于单点指定教务长） → ② 教务处组 openeducat_core.group_op_back_office_admin → ③ base.group_system`。

**为什么不写死 `backoffice@local`**：① 写死 login 在生产换人/改名时会**静默失效**；② 与既有 `notify_approvers()`（`leave.py:26-43`，教务处组 + 系统组）口径一致；③ 用户原话"教务长 = 教务人员"，**组比账号更接近语义**。当前该组 = `backoffice@local`(12) / `jiaowu@local`(18) / `admin`(2)。

**预留开关（对应 §1.1 未采纳口径）**：系统参数 `edu_portal.leave_always_two_stage`（默认 `0`）。置 `1` 时，一级通过后**一律**进 `pending_second`（= 实现 PDF 三·1 的"导师签字后再报教务"串行读法）。**默认关闭**，与用户裁决"≤3 天一级即终"一致。

### 3.3 空值行为（**硬要求：没有班主任也能跑**）

| 场景 | 一级待办落点 | 单据显示 | 能否继续流转 |
|---|---|---|---|
| 班上有班主任 | 班主任账号 | 「一级审批：张三（班主任）」 | ✅ |
| 班上没有班主任 | 教务处组 ∪ 系统组 | 「一级审批：教务处（**未设班主任，已转教务处**）」 | ✅ |
| 学生未分班 | 教务处组 ∪ 系统组 | 「一级审批：教务处（该生未分班，已转教务处）」 | ✅ |
| 教务处组与系统组**都为空** | 空集 | 「一级审批：**无可用审批人，请先配置教务处**」 | ✅ 单据可建可读；`/leave/approvals` 对 `privileged_staff()` 仍开放 |

> 最后一行是刻意的：**只 fail-open 到"无人可批但看得见"，绝不 fail-open 到"任何人都能批"**。

> **今天上线会命中哪一行？** R2 说 `op_faculty` 0 个在职、班主任字段全空 ⇒ **上线当天 100% 走"未设班主任 → 教务处"**。这是**预期行为**，不是降级，验收说明里要写明。

**老师到位后"只填数据"的证明路径**（不新增模型、不改代码、不 `-u`）：
把某个 `res.users` 填进「班级」表单的「班主任」字段（后台 264/386 菜单）⇒ **立刻**影响**新提交**的单据路由。已在途的单据**不回溯**（`first_approver_id` 在提交时快照）——这条要显式写明，避免"改了班主任为什么老单没变"的困惑。

### 3.4 「3 天」的边界口径（**已裁决**）

| 项 | 口径 | 实现 |
|---|---|---|
| 粒度 | **含头含尾**：9/1–9/3 = **3 天** | `days = (date_to - date_from).days + 1` —— **既有 `roles.py:1160-1162` 已是此算法，直接复用** |
| 日历 | **自然日**（不扣周末、不扣停课日 `edu_schedule_holiday`、**不扣法定节假日**——本仓**无**节假日字典） | 不做任何日历扣减 |
| 阈值 | **`days <= 3` → 只一级；`days > 3` → 二级** | `days > int_param('edu_portal.leave_second_approval_days', 3)` |
| 阈值可配 | ✅ 系统参数，默认 3 | 参照 OCA `base_tier_validation`「层级是数据不是代码」+ 钉钉「流程设计器里改条件」；本仓既有先例 `edu_portal.approval_escalate_hours`（`leave.py:17-23`，生产未设值、走默认） |

⚠ **本设计做不到的粒度（必须写清）**：现有 `date_from/date_to` 是 `fields.Date`（生产列类型 = `date`），**表达不了"半天"**。条例二·3 病假原文是「可请假**半天至一天**」⇒ **"半天"在本期无法表达**。改成 `Datetime` 是**破坏性改造**（既有 2 行 + 全部下游渲染 + 课代表判定），**本期不做**，列入 §11 Q1。

### 3.5 超时升级 ≠ 分级审批（别混用）

既有 cron 39（`edu_portal: 请假审批超时升级提醒`，每 6 小时，阈值 `edu_portal.approval_escalate_hours` 默认 48h）**只做一件事**：`escalated_at` 为空且超过 48h 的待批单 → 提醒教务处组 + 系统组，然后打上 `escalated_at`（`leave.py:182-204`）。它**不改状态、不换审批人**。

本次：**保留其语义不动**，仅把提醒文案补上"当前应批人"（`first_approver_id` / `second_approver_id`）。**不**在一级超时后自动改派教务处（用户没要求；且会与"转交后原审批人不能再批"的留痕语义打架）。是否自动改派 → §11 Q2（不阻塞）。

---

## 4. 转交审批

### 4.1 与既有 `edu.approval.delegate` 的关系：**并存，不合并**（结论）

| 维度 | `edu.approval.delegate`（既有） | 转交（本次新增） |
|---|---|---|
| 语义 | **事前、带时间窗的长期授权**：「我出差这 5 天，你代我批」 | **事后、单笔的一次性让渡**：「这一张单我不批了，你去批」 |
| 粒度 | 人 → 人 + 日期区间（覆盖该人**所有**可批的单） | **一张单的一个审批级** |
| 时限 | `date_from` / `date_to`，可撤销 | 无时限，**永久（对该单该级）** |
| 原审批人还能批吗 | **能**（代理是"也能"，不是"不能"） | **不能**（用户裁决） |
| 留痕 | 一条设置行（可撤销） | 一行转交记录 + 审计 + 单据可见 |
| 生产使用 | **0 行**（上线未用） | 新功能 |
| 外部先例 | 钉钉「代理人设置」（被代理人/代理人/代理时间，可撤销，有代理记录页） | 钉钉「转交」（**转交后该审批单从"待处理"转移到"已处理的"**）+ OCA `base_tier_validation_forward`（在 reviewer 表插一条 minor sequence 行） |

**结论：两条并存。** 合并会同时丢掉两个语义（时间窗 vs 单笔永久），而且 `is_delegate_of()` 已被门户审批路由使用（若把"转交"塞进去，需要给每张单建代理行，与"代理 0 行"的现状和"代理可撤销"的语义都冲突）。
> 一手依据：钉钉把三者做成**三个独立功能**（`help.dingtalk.io/zh/approval/operator-guide.md` + `admin-agent-settings.md`）；OCA 也是两个独立模块（`base_tier_validation_forward` 另成一包）。**没有一家把两者合成一个**。

### 4.2 数据模型

**新模型 `edu.leave.transfer`**（一行 = 一次转交；表名 `edu_leave_transfer`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `leave_id` | m2o `edu.leave`，required，`ondelete='cascade'`，index | 被转交的单 |
| `stage` | Selection `[('first','一级'),('second','二级')]`，required | 转的是哪一级 |
| `from_user_id` | m2o `res.users`，required | 转出人 |
| `to_user_id` | m2o `res.users`，required | 转入人 |
| `reason` | Text，**required** | 「为什么转」（用户要求的留痕三要素之一） |
| `create_date` / `create_uid` | 自带 | 「何时 / 谁操作」 |

**数据库级唯一约束（"只能转 1 次"必须是 DB 级，不是 if 判断）**：
```
_transfer_once = models.Constraint(
    'UNIQUE (leave_id, stage)',
    '同一张请假单的同一审批级只能转交 1 次。')
```
> ⚠ **必须用 `models.Constraint`，不能写 `_sql_constraints`**：Odoo 19 里旧写法**静默失效**（框架只遍历 `_table_objects`，且会在日志里告警）。本仓先例：`models/course_rep.py:174-176`、`edu_tg_bind/models/tg_claim.py`、`edu_portal/models/invite_code.py`。

**`edu.leave` 新增字段（转交相关）**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `first_approver_id` | m2o `res.users`，index，`ondelete='set null'` | **当前**一级应批人（提交时快照；转交后改写） |
| `second_approver_id` | m2o `res.users`，index，`ondelete='set null'` | **当前**二级应批人（进入 `pending_second` 时快照） |
| `transfer_ids` | o2m `edu.leave.transfer` | 留痕行 |
| `route_note` | Char(128) | 「未设班主任，已转教务处」这类可解释性文案（**只读**） |

> **不回填历史**：既有 2 行的 `first_approver_id` 留空（与 `approver_id` 既有口径一致 —— `leave.py:83-85` 原文「既有历史单据为空（显示「—」）」）。

### 4.3 四条规则（逐条对应队长裁决 C）

**(1) 同角色之间互转**

| 转哪一级 | 候选范围 | 为什么这样定 |
|---|---|---|
| 一级 | ① 其他班的班主任账号（`op.batch.homeroom_teacher_id` 非空的并集） ∪ ② **教务处组** | ⚠ **必须把教务处放进一级候选**：R1/R2 下今天有 **0 个班主任**，若写死"一级只能转给一级"，该功能当天**完全不可用**。而用户已裁决「没有班主任 ⇒ 直接落教务处」⇒ **教务处本来就是合法的一级审批人**，转给它是同层兜底，**不是越权**。这条放宽必须在 UI 上显式呈现（"转交给教务处"是一个明写选项，不是隐藏路径） |
| 二级 | 教务处组 ∪ 系统组 | 二级的可批集合本来就等于它（§3.2） |

**必须过滤掉三种人**：① 自己（`to_user_id != from_user_id`）；② **申请人本人**（判据用**学生档案 id / 申请人 uid**，不用 partner）；③ 提交时二次校验仍在候选集合内。

**(2) 转交后原审批人不能再批** —— 判定口径的**替换**（本次最关键的一处改动）

`edu.leave` 的"我能批这一级"判据，**从"是不是班主任"改成"是不是本单当前这一级的 `first_approver_id` / `second_approver_id`"**（**唯一事实源**，做法照 `course_rep.py` 文件头的"权限判定的唯一事实源"）。

- 转交执行：写 `edu.leave.transfer` 行 + `write({'first_approver_id': to_user_id})`。
- 原审批人再 POST `/leave/set_state` ⇒ `_scoped_record('edu.leave', id)`（`roles.py:829`）按**不存在**处理 ⇒ 303 回队列、**不写任何字段**（沿用既有 fail-closed 口径，与 `rep_can_handle` 同款）。
- ⚠ **必须显式写出的例外**：`privileged_staff()`（教务处组 **或** 系统组）**恒可批任何单** —— 这是 code-map §6 第 3 条的既有铁律，也是 §3.3"无可用审批人"兜底的前提。**本次不破它**。
  ⇒ 净效果：**班主任 A 转给班主任 B 后，A 批不了（符合用户要求）；教务处 C 在任何时候都能批（既有铁律）**。这句话要原样写进转交确认弹窗的说明，避免扯皮。

**(3) 只能转 1 次**
- DB：`UNIQUE(leave_id, stage)`（§4.2）
- 代码：`/leave/transfer` 入口先 `search_count` 预检，命中即回队列并提示「该单据该级已转交过 1 次，不能再次转交」
- UI：已转交时**隐藏**转交按钮（不是置灰）
- **不需要**乐观锁：并发双转由唯一约束兜底（本仓先例：`edu_tg_bind` 的"唯一约束 + 整事务回滚重试"）

**(4) 必须留痕（谁转给谁 / 何时 / 为什么）—— 四层**
1. `edu.leave.transfer` 行（结构化，可查）
2. `edu.audit.log`：**新动作名 `'请假审批转交'`**（**不改**既有「请假审批」「请假批量审批」两个动作名），subject = 单号，body = 「一级：张三 → 李四；原因：…」
3. 单据详情页（`/leave/approvals/<id>`）显示转交历史块：「一级审批：张三 → 已转交李四（2026-09-26 10:00，原因：…）」
4. 三方通知（`edu.message._notify_event`，**新事件 key `'leave_transferred'`**）：转出人（确认）、转入人（新待办）、申请人（知会）。失败只告警不阻断（沿用 `_notify_applicant` 的错误处理风格）

### 4.4 转交的动作面

| 动作 | 路由 | 守卫 |
|---|---|---|
| 转交 | 新 `/leave/transfer`（POST，csrf） | `user ∈ {first_approver_id, second_approver_id}` 且 `to_user != self` 且 `to_user != 申请人` 且该级未转过 |
| 转出人"撤销转交" | **不做** | 用户只说"只能转 1 次"；撤销会引入第二个状态位。钉钉也没有（钉钉的撤销是针对**代理**，不是转交） |

---


## 5. 角色映射

### 5.1 「当班教职同工」= 班主任 —— 落在 `op.batch`

**新字段**（在 `custom_addons/edu_portal` 里 `_inherit`，**不碰 `openeducat_erp/`**）：

```
class OpBatchExt(models.Model):
    _inherit = 'op.batch'
    homeroom_teacher_id = fields.Many2one(
        'res.users', string='班主任', ondelete='set null',
        help='该班的班级导师。留空 = 本班请假单的一级审批直接落教务处。')
```

**为什么落 `op.batch`**：
1. 「班主任」是**班级**属性：生产 `op_batch` 12 行（code-map §4 已把 264/386 菜单改名为「班级」），一个班一个班主任 ⇒ 一列足够。
2. **不落 `op.faculty`**：R2 说该模型 0 个在职行；把班主任钉在它上面，老师到位时**必须先建 op.faculty 才能填班主任** ⇒ 多一层依赖，违反队长要求 e。
3. **不新建模型**：没有"多班主任"或"带任期"的需求（任期是课代表的特性，班主任是长期任职）。
4. **不用 `res.partner`**：路由要的是**账号**。

**为什么类型是 `res.users` 而不是 `op.faculty`**：
1. 路由要的就是账号，直接存账号 ⇒ 零解析、零失败分支；
2. 老师"只填数据"即可生效——填一个下拉框，不需要先建档案；
3. 与 `edu.approval.delegate`（`delegator_id/delegate_id` 都是 `res.users`）**口径一致**；
4. 外部先例：钉钉的「部门主管」「直属主管」也是**通讯录成员**（`help.dingtalk.io/zh/approval/set-dept-manager-approval.md` / `set-direct-manager-approval.md`）。
5. ⚠ **代价（要认账）**：换老师换账号时，这个字段不会自动跟着 `op.faculty` 走。缓解：字段加 `domain` + 帮助文本；**不做**双向同步（会引入第二个事实源）。

**视图落点**：新建 `views/leave_flow.xml`，内含 `op.batch` 继承视图（把「班主任」放进「班级」表单，后台 264/386 菜单）。

### 5.2 「教务长」= 教务处组（不写死 `backoffice@local`）

见 §3.2 的三级解析链（系统参数 → 教务处组 → 系统组）。
把用户口述的账号记为**事实核对**：`backoffice@local` = `res_users` id 12「教务专员」，确在教务处组内（该组 3 人）。**代码里不出现这个字符串。**

### 5.3 教职人员身份从哪来（**不依赖 `op.faculty` 存在**）

**判定**：`applicant_kind = 'staff'` ⟺ 当前登录账号经 `edu_schedule/models/identity.py` 的**唯一口径**反查 `op.student` 与 `op.parent` **皆为空**。

- ✅ 满足队长要求 e（不依赖 `op.faculty`）；
- 生产现状核对：可发起教职单的账号 = `admin`(2) / `backoffice@local`(12) / `jiaowu@local`(18)；`teacher@local`(33) 的 partner 65 **不关联任何 `op_student`**（实测 0 行）⇒ 会被判为**教职单** ✅（它虽 `share=true`，但判定**不看** `share`——这是刻意的：本仓 `teacher@local` 恰恰是门户账号，用 `share` 判会把它错判成学生）
- ⚠ **必须排除的反例**：家长（`op.parent`）不算教职 ⇒ 家长在 `/my/time_off` 看到的是"为孩子请假"，不是教职单。
- 门户入口**不加新页面**：`/my/time_off` 按身份分流（学生单表单 / 教职单表单），复用既有 `edu_page` 外壳。

### 5.4 教职单的审批链（**唯一一处推定，推定过程必须留档**）

用户裁决 8：**员工条例不存在 ⇒ 教职单参照学生条例同构**。
学生链 = 「≤3 天 → 班主任；>3 天 → 班主任 + 教务」。教职员工**没有班主任**（班主任是"管学生"的角色）⇒ 同构的最近落点：

| 口径 | 一级 | 二级 |
|---|---|---|
| **本文采用** | **教务处组**（无班主任可指） | **系统组（`base.group_system`）**，仅当 `days > 3` 或 `over_quota` |

**为什么二级是系统组而不是教务处**：若两级都落教务处，则**同一人可以连批两次** ⇒ 二级形同虚设。教职单的二级必须是一个**与一级不同的集合**，本仓唯一可用的"更高一级"就是系统组（= 校长/管理员，2 人）。

**这是本文档唯一一处推定**，理由：① 用户明确说没有员工条例；② 队长明确要求"参照学生条例同构、不要留悬空项"；③ 本仓除教务处组与系统组，**没有第三个管理角色实体**（"教务长"实体经实测不存在）。
**可回退**：若用户日后说"教职单不需要二级"，删掉 `route_of()` 里 staff 分支的 `need_second` 计算即可（改动面 1 处），`pending_second` 状态与转交功能不受影响。

### 5.5 角色映射速查表

| 概念 | 生产实体（实测） | 本设计的落点 |
|---|---|---|
| 学生 | `op.student` 29 行 | `applicant_kind='student'` + `student_id` |
| 教职人员 | 无名单（`op.faculty` 0 在职） | `applicant_kind='staff'` + `applicant_user_id`；判定 = 反查不到 student/parent |
| 班主任（当班教职同工） | **本仓无此角色**，今天 **0 人** | **新建** `op.batch.homeroom_teacher_id`（`res.users`，可空） |
| 教务长 | 无该实体；用户口述 = `backoffice@local` | **教务处组** `openeducat_core.group_op_back_office_admin`（3 人），可选系统参数单点指定 |
| 管理员/校长 | `base.group_system` 2 人 | 教职单的第二级（§5.4） |

---

## 6. 请假类型重做（条例二）

**新 Selection**（**保留全部旧 code**）：

| code | 标签 | 条例出处 | 门户下拉 |
|---|---|---|---|
| `sick` | 病假 | 二·3 | ✅ |
| `casual` | 事假 | 二·4 | ✅ |
| `marriage_funeral` | 婚丧假 | 二·2 | ✅ |
| `winter_summer` | 寒暑假 | 二·1 | ✅ |
| `practice_week` | 实践周 | 二·5 | ✅ |
| `legal` | 法定假（历史值） | 无条例出处 | ❌ 隐藏 |
| `other` | 其他 | 既有 | ✅ |

> **为什么保留 `casual` 而不是改成 `personal`（关键陷阱）**：
> `custom_addons/edu_portal/models/course_rep.py:117-126` 的 `edu_portal.course_rep_leave_types` **默认值是 `('sick','casual')`**（生产未设该系统参数 ⇒ 走默认）。若把事假的 code 改成 `personal`，课代表的会签白名单会**静默**失去事假（不报错、不告警）。
>
> **为什么保留 `legal`**：既有 2 行 + 课代表白名单 + 后台历史筛选都按老 code 走；仅从门户下拉隐藏即可。

---

## 7. 条例七条的机器化落点（B 组，逐条）

### 7.1 销假（条例三·3）—— **正交字段，不改 state**

| 字段 | 类型 | 说明 |
|---|---|---|
| `return_confirmed_at` | Datetime，readonly | 销假时间 |
| `return_confirmed_by_id` | m2o `res.users`，readonly，`ondelete='set null'` | 谁确认的（班主任/教务） |
| `return_note` | Text | 学生提交的「行程及实践收获」 |
| `return_required` | Boolean，compute（**不 store**） | `state=='approved' and date_to < today` |
| `return_overdue_alerted_at` | Datetime，readonly | cron 幂等去重（照 `escalated_at` 的形状） |

**流程**：学生（或家长）对已通过且已到期的单点「销假」→ POST `/leave/<id>/return_confirm` 提交 `return_note` → 班主任/教务确认（同一路由，二次确认置 `return_confirmed_at`）。

**逾期未销假提醒**：**新 cron**（新 `ir.actions.server`，**别改 cron 39**），照 `ir_cron_edu_leave_escalate` 的形状（`views/roles.xml:1993`）：扫 `return_required and not return_confirmed_at and return_overdue_alerted_at == False`，通知教务处 + 班主任，写 `return_overdue_alerted_at`（**幂等**：重复跑安全 —— 这条是既有 cron 的既有品质，必须保留）。

> **为什么不做成第五个状态**：会打断 ① 既有 `filterby=request|approved|refused` 三档筛选 ② 首页提醒卡计数 ③ `_leave_steps()` 进度条（`roles.py:1173-1193`）。销假是"事后义务"，不是"审批裁决"。

### 7.2 证明材料（条例二·2 婚丧假 / 二·3 病假）—— **必传附件 + 口头证明双轨**

| 字段 | 类型 | 说明 |
|---|---|---|
| `proof_kind` | Selection `[('file','文件证明'),('oral','口头证明'),('none','无')]` | 默认 `none` |
| `attachment_ids` | o2m `ir.attachment`（经 `res_model='edu.leave'` / `res_id`） | 文件证明 |
| `oral_proof_by` | Char(64) | 口头证明人（家长/牧长） |
| `oral_proof_relation` | Char(32) | 与申请人关系 |
| `oral_proof_confirmed_by_id` | m2o `res.users` | **审批人确认口头证明**的留痕 |
| `proof_required` | Boolean，compute（**不 store**） | 触发：`sick and days >= 2` → 必传；`marriage_funeral` → 必传 |

**校验**：`proof_required` 为真时，提交必须满足 `proof_kind=='file' and attachment_ids` **或** `proof_kind=='oral' and oral_proof_by`；否则 `UserError`（文案引条例原文）。
**口头证明的确认闭环**：审批人点「通过」时若 `proof_kind=='oral'` 且 `oral_proof_confirmed_by_id` 为空 ⇒ 写入 `env.user`（= 审批人确认），并写 `edu.audit.log`。
> **为什么不做成单纯的"备注字段"**：条例把"无文本证明可请家长/牧长口头证明"写成**合法凭证**，所以它必须能被审批人**确认**、能被审计查出"谁认了这份口头证明"。

### 7.3 提前申请期（二·4 事假提前 2 天 / 二·2 婚丧假提前 1–2 周）—— **软提示，不硬拦**

| 字段 | 类型 | 说明 |
|---|---|---|
| `lead_days_required` | Integer，compute（不 store） | `casual → 2`；`marriage_funeral → 7`；其余 → 0 |
| `lead_days_actual` | Integer，store（提交时快照） | `date_from - 提交日` |
| `lead_days_short` | Boolean，store | 提交时快照；供筛选与审批人提示 |

**行为**：不足时在表单页显示横幅「条例要求事假提前 ≥2 天提交，本单仅提前 1 天」+ 详情页红字 + 审批人可见；**提交照过**。
**谁能破例**：**任何有该单审批权的人**（一级班主任 / 教务处 / 系统组）——软提示本身就是例外通道；系统额外记录 `lead_days_short=True`，让"批了不达标单"**可被审计查出**。

### 7.4 事假学期配额 ≤5 天（二·4）—— **超限自动升级教务处**

| 字段 | 类型 | 说明 |
|---|---|---|
| `casual_days_used_this_term` | Float，compute（**不 store**，实时算） | 域：同 `student_id` + `leave_type=='casual'` + `state in ('request','pending_second','approved')` + `date_from` 落在当前 `op.academic.term` 区间内；求和**含头含尾** |
| `over_quota` | Boolean，store（提交时快照） | `casual_days_used_this_term + 本单天数 > 5` |

**行为**：`over_quota=True` ⇒ **无论几天，一律走二级**（`need_second = need_second or over_quota`），单上显示「事假学期累计已 X 天，超过条例 5 天上限，已上报教务处」。
**学期边界**：取 `op.academic.term` 中 `term_start_date <= date_from <= term_end_date` 的那一条（生产 2 条：第一学期 2026-06-23~12-20、第二学期 2026-12-21~2027-06-18）。
**取不到学期 ⇒ 不判超限**（fail-closed 到"不拦截"：配额是限制性规则，取不到边界就无权拦人）。

### 7.5 禁止事后补假（一·2）—— **门户硬拒 + 后台例外通道**

- **门户侧**（学生 `/my/time_off`、家长 `/my/child/<id>/leave/save`）：`date_from < 提交日` ⇒ `UserError('《请假条例》一·2 规定严禁事后补假，请勿补提过去日期的申请。')`，**不落库**。
- **后台例外通道**：后台「请假审批 → 新建」**不受此校验**（教务代录历史/特殊情况），但**必须**写 `edu.audit.log`（新动作名 `'请假事后补录'`），并在单据上置 `backfilled=True`（新 Boolean，只读，详情页红字「本条为教务事后补录」）。
- ⚠ **边界**：今天请假、今天提交 ⇒ `date_from == today` ⇒ **允许**（不是"事后"）。只有 `date_from < today` 才拒。

### 7.6 实践周 / 寒暑假（二·1、二·5）—— 文案 + 软提示 + 1 条负向断言

| 条例原文 | 机器化落点 | 类别 |
|---|---|---|
| 「法定节假日如遇实践周，**并非假期，不调休不拼假**」 | ① 选 `practice_week` 时门户显示条例原文提示；② **一条负向断言**：`practice_week` 单据**不写任何折算字段**（本仓无调休/拼假功能 ⇒ 断言 = "没有这个字段被写"） | 文案 + 负向断言 |
| 「学生须参与打工、实习、社会服务或项目学习，若有课程则正常上课」 | 不机器化（无判据） | 文案 |
| 「原则上**不批准外出长假**」 | 软提示（同 §7.3 口径）：`practice_week` 且 `days >= 7` ⇒ 显示提示 + `long_absence_flag` Boolean | 软提示 |
| 二·1「如因个人原因未在寒暑假期间完成探亲，学期中**不得再以探亲为由**请假」 | **不机器化**（"探亲"是自然语言事由，无法可靠判定）。标注**仅文案** | 文案 |
| ⚠ 本仓**无「法定节假日」字典**（`edu_schedule_holiday` 是**停课日**，不是节假日表） | 「不调休不拼假」无法按节假日表计算 ⇒ 上述处置 | —— |

### 7.7 明确**不做**的（写清原因，防"漏了"）

| 项 | 为什么不做 |
|---|---|
| 条例四·1「违规记入**综合评估档案**」 | 跨模块写 `edu.eval.*`（评估引擎），超出本次范围；且"多次违规"本身需要人工判定。**登记为后续独立需求** |
| 半天假（二·3「半天至一天」） | 需把 `date_from/date_to` 从 `Date` 改 `Datetime` ⇒ 破坏性改造，§11 Q1 |
| 三·1 的「班级导师/陪伴老师**签字**」线下签字 | 线下动作，系统里对应的是"审批留痕"，不新增签字实体 |
| `op_leave_request` 孤儿死表清理 | 0 行、`ir_model` 无登记；本次不动（登记进 `docs/audit/deprecated-inventory.md` 即可） |
| 一级超时后自动改派教务处 | §3.5 / §11 Q2 |

---

## 8. 权限矩阵

### 8.1 谁能看 / 谁能批 / 谁能转交

| 动作 | 门户路由 | 判据（**唯一事实源**） |
|---|---|---|
| 建**学生单** | `/my/time_off`（学生）、`/my/child/<id>/leave/save`（家长） | `current_student()` / `current_parent()` 非空 |
| 建**教职单** | `/my/time_off`（同一页分流） | `current_student()` 与 `current_parent()` **皆空**（§5.3） |
| 看自己 / 孩子的单 | `/my/time_off`、`/my/child/<id>/leave` | 既有 |
| **一级审批** | `/leave/approvals` + `/leave/set_state` + `/leave/set_state_bulk` | `user == first_approver_id` **or** `privileged_staff()` |
| **二级审批** | 同上 | `user == second_approver_id` **or** `privileged_staff()` |
| **转交** | 新 `/leave/transfer`（POST） | `user ∈ {first_approver_id, second_approver_id}` 且 `to_user != self` 且 `to_user != 申请人` 且该级 `UNIQUE(leave_id,stage)` 未占用 |
| **销假** | 新 `/leave/<id>/return_confirm`（POST） | 本人/家长（提交说明）→ 审批人（确认） |
| 后台查看/新建/管理 | 后台菜单 497「教务审批」→ 498「请假审批」 | ACL 既有：教务处组 / system 组 full |

### 8.2 与既有 `privileged_staff()` / `approval_scope_domain()` 的关系

1. **`privileged_staff()` 是恒真的超集**（教务处组 or 系统组），本次**不破**它（code-map §6 第 3 条 + 第 12 条）。新的"分级"只决定两件事：① **待办/通知该发给谁**；② **非特权审批人的可批边界**（= 转交后的原审批人被挡，见 §4.3(2)）。
2. **`approval_scope_domain(env)`（`roles.py:2716`）要扩一条并集**：教师"看得见的单" =
   `[('first_approver_id','=',uid), ('second_approver_id','=',uid), ('id','in', 自己任教班级的单), ('id','in', 自己是班主任的班的单)]`（**OR** 关系）；`privileged_staff()` 不限。
   **必须与列表/批量/单条三处同域**（既有"看得见的 = 能处置的"口径，`roles.py:819-835` 注释原文），否则会重现历史缺陷。
3. **ACL**：`security/ir.model.access.csv` 追加 `edu.leave.transfer` 三行 —— 教务处组 full / system 组 full / 教师组 **read**（教师组不需要 create：转交只从门户路由发起，走 sudo + 显式校验）。

### 8.3 权限四层归属声明（code-map §6 第 12 条要求）

| 新增对象 | 层 |
|---|---|
| `op.batch.homeroom_teacher_id`（字段） | 跟随 `op.batch` 既有 ACL（**教务组**层） |
| `edu.leave` 新字段 | 跟随既有（门户只读 / 教师读写 / 教务·系统全权） |
| `edu.leave.transfer`（模型） | **教务组 + 系统组**写；教师组只读 |
| 后台菜单 498 下的新动作 | **教务组**（`groups="openeducat_core.group_op_back_office_admin,base.group_system"`，与系统组**并列**，保管理员最高权） |
| `/leave/transfer`、`/leave/<id>/return_confirm`（门户路由） | 门户路由 + 判据分流（**不给后台菜单**） |

---


## 9. 数据迁移与部署

### 9.1 迁移（`migrations/19.0.4.0.0/`，版本号从 `19.0.3.0.0` 递增）

> 版本号递增是触发 `migrations/` 的**唯一开关**（先例 `migrations/19.0.2.0.0`、`migrations/19.0.3.0.0`）。

| 步 | 动作 | 断言 |
|---|---|---|
| 1 | `edu_leave.applicant_kind` 新列 → 回填 `'student'` | `SELECT count(*) FROM edu_leave WHERE applicant_kind IS NULL` = **0** |
| 2 | `applicant_user_id` ← 从 `student_id.user_id` 尽力回填（取不到留空） | 不设硬断言（本仓 identity.py 是双向并集，单链 SQL 会漏） |
| 3 | `first_approver_id / second_approver_id / route_note / proof_kind / lead_days_short / over_quota / return_*` 留空或默认 | 无需回填 |
| 4 | **不动** `name` 单号（id=26 `'001'`、id=27 `'SLR000001'` 原样保留） | `SELECT name FROM edu_leave ORDER BY id` 与迁移前逐字一致 |
| 5 | **不动**既有 2 行 `state='refused'` | 不进入任何队列 |
| 6 | `op_batch.homeroom_teacher_id` 新列，**全空** | 无需回填 |
| 7 | 新增 `edu.leave.transfer` 表 + `UNIQUE(leave_id, stage)` | `\d edu_leave_transfer` 有该唯一索引 |

**⚠ 上线当天的预期状态（必须写进验收说明，防误判为故障）**：`homeroom_teacher_id` 全空 + `op_faculty` 0 在职 ⇒ **所有新提交的学生单一级审批都落教务处**，单据显示「未设班主任，已转教务处」。这是**设计行为**。

**不做**（防范围膨胀）：`op_leave_request` 孤儿表清理、`op_faculty` 数据补齐、`edu_approval_delegate` 与转交的合并。

### 9.2 新增/改动文件清单（供派工用）

| 类型 | 路径 | 动作 |
|---|---|---|
| 模型 | `custom_addons/edu_portal/models/leave_transfer.py` | **新增**（`edu.leave.transfer`） |
| 模型 | `custom_addons/edu_portal/models/leave_flow.py` | **新增**（`route_of()` / 状态机 / 转交 / 销假 / 配额 / 校验；`_inherit='edu.leave'` + `_inherit='op.batch'`） |
| 模型 | `custom_addons/edu_portal/models/__init__.py` | **追加 2 行**，顺序 `leave → leave_transfer → course_rep → leave_flow`（**`leave_flow` 必须最后**：同模块内后导入的层在 MRO 里更靠前，见该文件既有注释；门禁 `scripts/check_view_xpath.py` 规则 7） |
| 迁移 | `custom_addons/edu_portal/migrations/19.0.4.0.0/pre-migrate.py` / `post-migrate.py` | **新增** |
| ACL | `custom_addons/edu_portal/security/ir.model.access.csv` | **追加** `edu.leave.transfer` 3 行 |
| 视图 | `custom_addons/edu_portal/views/leave_flow.xml` | **新增**（`op.batch` 继承视图 + `edu.leave` 表单/列表扩展 + 门户列表/详情/表单 + 销假/转交片段 + 新 cron 记录） |
| 视图 | `custom_addons/edu_portal/views/roles.xml` | **可能改动**（`edu_leave_approvals` / `edu_leave_detail` 加"当前审批级/转交历史/销假/证明"块；也可整体放新文件、此文件不动 —— **由 S4 决定并在交付说明里写明**） |
| 控制器 | `custom_addons/edu_portal/controllers/roles.py` | **追加**（`/leave/transfer`、`/leave/<id>/return_confirm`、`approval_scope_domain` 扩域、`_leave_steps` 加二级、`/my/time_off` 身份分流） |
| 清单 | `custom_addons/edu_portal/__manifest__.py` | **version → 19.0.4.0.0** + `data` 追加 `views/leave_flow.xml` |
| 测试 | `tests/smoke/leave_split_approval.py` | **新增** |

> ⚠ 铁律：**不改** `openeducat_erp/**`（基座只读）、**不改** `custom_addons/edu_telegram/**`（已退役）、不改 `course_rep.py` 的既有规则（只允许在其后**追加**导入行）。

### 9.3 验收命令（闭环，按 `docs/code-map.md` §10）

```
# ── 0. 离线门禁（不依赖站点，先跑，证明"尺子准"） ──
python3 scripts/check_view_xpath.py  --selftest     # 新增 _inherit / xpath / 导入顺序（规则 7）
python3 scripts/check_manifest_tracking.py          # 新文件必须 git add（否则新克隆加载失败）
python3 scripts/check_qweb_dict_foreach.py --selftest
python3 tests/smoke/leave_split_approval.py --selftest

# ── 1. 前置探活（顺序不可颠倒） ──
#   ① 无升级锁 ② 容器 Up > 30s ③ 带 cookie jar 访问 /web/login?db=edu19 得 200/302/303
curl -s -c jar -b jar -o /dev/null -w '%{http_code}\n' http://localhost:8069/web/login?db=edu19

# ── 2. 升级（唯一入口；本模块已装，默认 -u） ──
bash scripts/safe_upgrade.sh edu_portal          # 要求 EXIT=0 且无 Traceback

# ── 3. 汉化 / 痕迹 / 无障碍 / QWeb（若动了用户可见文案与控件） ──
python3 scripts/check_english.py                 # 口径 must-fix = 0
python3 scripts/check_odoo_trace.py              # 口径 0 命中
python3 scripts/check_accessibility.py           # 新控件必须有可访问名（硬约定 §6.10，BASELINE 已 0）
python3 scripts/check_qweb_dict_foreach.py       # 失败项 0

# ── 4. 功能门禁 ──
python3 tests/smoke/leave_split_approval.py      # ★ 本次新增（断言见 §9.4）
python3 tests/smoke/ux_v3_route_matrix.py        # 新路由 x 5 角色
python3 tests/smoke/zero_loss_reachability.py    # 首页卡片零丢失（/my/time_off 卡仍在）

# ── 5. 注册表铁律（新增模型/字段必跑，code-map §10.1） ──
python3 scripts/check_live_registry.py           # 有 DARK 即 exit 1

# ── 6. 部署（远端升级 + 必定重启 web + 就绪探活 + 活体注册表门禁） ──
FIX_DRY_RUN=1 python3 scripts/fix_edu_apply_xmlid.py   # 部署前干跑孤儿预检：SKIP 才可部署
bash scripts/deploy_myedu.sh edu_portal
ssh prod-host 'cd /opt/edu-app && python3 scripts/check_live_registry.py'
```

### 9.4 验收断言清单（`tests/smoke/leave_split_approval.py` 的用例）

| # | 断言 | 类型 |
|---|---|---|
| A1 | `edu.leave.transfer` 在注册表；`op_batch.homeroom_teacher_id` 列存在 | 结构 |
| A2 | **有班主任**：设 `batch.homeroom_teacher_id=teacher@local`，建 2 天学生单 ⇒ `state='request'`、`first_approver_id=teacher@local`、`second_approver_id` 空 | 正向 |
| A3 | **无班主任**：清空该字段，建 2 天学生单 ⇒ `first_approver_id ∈ 教务处组`、`route_note` 含「未设班主任」 | 正向 |
| A4 | 学生无班（本库 5 人）建单 ⇒ 同 A3 分支，`route_note` 含「未分班」 | 边界 |
| A5 | 建 **4 天**单 ⇒ 一级通过后 `state='pending_second'`、`second_approver_id ∈ 教务处组` | 正向 |
| A6 | 建 **3 天**单 ⇒ 一级通过后直接 `approved`（**边界值**，含头含尾） | **边界** |
| A7 | 转交一次 ⇒ `first_approver_id` 变成转入人；`edu.leave.transfer` 有 1 行；`edu_audit_log` 有「请假审批转交」 | 正向 |
| A8 | **转交后原审批人** POST `/leave/set_state` ⇒ `state` **不变**、无新 audit 行 | **负向** |
| A9 | **第二次转交** ⇒ 撞 `UNIQUE(leave_id, stage)`，事务回滚、转交行仍为 1 | **负向** |
| A10 | 事假学期累计 >5 天 ⇒ `over_quota=True` 且**即使 ≤3 天也进** `pending_second` | 正向 |
| A11 | 门户 `date_from < today` ⇒ 拒绝且**不落库**；后台新建同款单 ⇒ 成功且 `backfilled=True` | 正/负 |
| A12 | 病假 2 天无任何证明 ⇒ 拒绝；填 `proof_kind='oral'` + 证明人 ⇒ 通过，且审批人确认后 `oral_proof_confirmed_by_id` 非空 | 正/负 |
| A13 | 实践周单据**未写任何折算字段** | **负向断言** |
| A14 | 一级超时 48h ⇒ cron 39 提醒文案含当前应批人；`escalated_at` 幂等（重复跑不重复提醒） | 回归 |

---

## 10. 实施拆分（可直接并行派工）

**依赖总览**

```
S1（数据层）
   ├──► S2（模型逻辑） ──┐
   ├──► S3（控制器/门户）─┼──► S5（测试门禁）──► S6（部署验收）
   └──► S4（视图/后台） ──┘
```

> **并行注意（同一模块内的真冲突）**：S2/S3/S4 都改 `edu_portal`，会撞同一批单点文件。**S1 必须一次性把三个单点文件改完并冻结**：`models/__init__.py`（2 行导入）、`__manifest__.py`（version + data 列表含 `views/leave_flow.xml`）、`security/ir.model.access.csv`。此后 **S2 只写** `models/leave_flow.py` + `models/leave_transfer.py`，**S4 只写** `views/leave_flow.xml`，**S3 只在** `controllers/roles.py` **文件末尾追加**（不动既有函数体，除 `approval_scope_domain` 一处）。

### S1 — 数据层与迁移（**地基，必须最先，独占**）

| 项 | 内容 |
|---|---|
| **范围** | `models/leave_transfer.py`（新模型 + `UNIQUE` 约束）；`models/leave_flow.py` **只含字段声明**（`applicant_kind / applicant_user_id / first_approver_id / second_approver_id / route_note / proof_kind / attachment_ids / oral_proof_* / return_* / lead_days_* / over_quota / backfilled`）与 `op.batch.homeroom_teacher_id`；`__init__.py` 2 行；`__manifest__.py` version + data；`security/ir.model.access.csv` 3 行；`migrations/19.0.4.0.0/` |
| **交付物** | 上述 6 个文件；`post-migrate.py` 内的回填与自证断言 |
| **验收命令** | `bash scripts/safe_upgrade.sh edu_portal`（EXIT=0 无 Traceback）；`python3 scripts/check_view_xpath.py`；`python3 scripts/check_manifest_tracking.py`；`python3 scripts/check_live_registry.py`；psql：`\d edu_leave_transfer` 有 `UNIQUE(leave_id, stage)`、`SELECT count(*) FROM edu_leave WHERE applicant_kind IS NULL` = 0 |
| **依赖** | 无 |
| **⚠** | 新增 .py ⇒ 改完**必须重启 web**（§10.1 注册表铁律），否则"库里有、活体进程没有" |

### S2 — 模型逻辑（**依赖 S1**，与 S3/S4 并行）

| 项 | 内容 |
|---|---|
| **范围** | `models/leave_flow.py`：`route_of()`（§3.2 判定表 + §5.4 staff 判定）、状态机方法（`action_first_approve / action_second_approve / action_refuse / action_send_back`）、`transfer()`（§4.3 四条规则）、销假流转（§7.1）、compute（`return_required / proof_required / casual_days_used_this_term / lead_days_*`）、提交校验（§7.2/7.3/7.5）、`_cron_return_overdue()` |
| **交付物** | `models/leave_flow.py`（可执行）；**接口冻结**：函数签名与返回结构写进文件 docstring，供 S3 直接调用 |
| **验收命令** | `python3 tests/smoke/leave_split_approval.py --model-only`（S5 提供骨架）；`bash scripts/safe_upgrade.sh edu_portal`；`python3 scripts/check_odoo_trace.py` |
| **依赖** | S1 |

### S3 — 控制器与门户（**依赖 S1**，与 S2/S4 并行）

| 项 | 内容 |
|---|---|
| **范围** | `controllers/roles.py` 末尾追加 `/leave/transfer`（POST, csrf）、`/leave/<id>/return_confirm`（POST, csrf）、`/my/time_off` 的**学生/教职身份分流**；改 `approval_scope_domain(env)`（§8.2 并集）；`_leave_steps()` 加二级步骤 |
| **交付物** | `controllers/roles.py` 追加段；分流与守卫的 fail-closed 说明 |
| **验收命令** | `python3 tests/smoke/ux_v3_route_matrix.py`（新路由 x 5 角色）；`bash scripts/safe_upgrade.sh edu_portal`；`python3 tests/smoke/zero_loss_reachability.py` |
| **依赖** | S1（S2 接口冻结后即可联调） |

### S4 — 视图与后台（**依赖 S1**，与 S2/S3 并行）

| 项 | 内容 |
|---|---|
| **范围** | `views/leave_flow.xml`：`op.batch` 继承视图（班主任字段）、`edu.leave` 表单/列表扩展（审批级/转交历史/销假/证明/配额提示/backfilled 红字）、门户 `edu_leave_approvals` / `edu_leave_detail` / `edu_time_off` 扩展、`ir.cron` 销假逾期提醒（**新记录，不改 cron 39**） |
| **交付物** | `views/leave_flow.xml`；如改动 `views/roles.xml` 需在交付说明里写明改了哪几个 template id |
| **验收命令** | `python3 scripts/check_view_xpath.py`；`python3 scripts/check_qweb_dict_foreach.py`；`python3 scripts/check_accessibility.py`；`python3 scripts/check_english.py`（must-fix=0）；`bash scripts/safe_upgrade.sh edu_portal` |
| **依赖** | S1 |

### S5 — 测试与门禁（**依赖 S2/S3**；可先提交 `--selftest` 骨架）

| 项 | 内容 |
|---|---|
| **范围** | `tests/smoke/leave_split_approval.py` 实现 §9.4 的 A1–A14；`--selftest`（不连站点，证明尺子准）+ `--model-only`（供 S2） |
| **交付物** | 测试脚本 + 一份实测输出（含"有班主任/无班主任"两用例的真实读数） |
| **验收命令** | `python3 tests/smoke/leave_split_approval.py --selftest && python3 tests/smoke/leave_split_approval.py`（exit 0） |
| **依赖** | S2、S3 |

### S6 — 部署与生产验收（**依赖 S1–S5**，独占，串行）

| 项 | 内容 |
|---|---|
| **范围** | 走 §9.3 全流程；生产侧跑 `check_live_registry.py`；把"上线当天 100% 走教务处"写进交付说明 |
| **交付物** | 部署日志（EXIT=0）+ 活体注册表读数 + 冒烟输出 |
| **验收命令** | §9.3 第 6 段全部 |
| **依赖** | S1–S5 |

### 10.1 并行派工速查

| 任务 | 可并行 | 独占文件（**防冲突的关键**） |
|---|---|---|
| S1 | 否（最先） | `models/__init__.py`、`__manifest__.py`、`ir.model.access.csv`、`migrations/**` |
| S2 | 与 S3/S4 | `models/leave_flow.py`、`models/leave_transfer.py` |
| S3 | 与 S2/S4 | `controllers/roles.py`（仅追加段 + 1 处改域） |
| S4 | 与 S2/S3 | `views/leave_flow.xml` |
| S5 | 否（依赖 S2/S3） | `tests/smoke/leave_split_approval.py` |
| S6 | 否（依赖全部） | —— |

---

## 11. 待确认项（**均不阻塞实施**；「待用户裁决」已清零）

| # | 问题 | 本文的默认处置 | 若用户改口，改动面 |
|---|---|---|---|
| Q1 | **半天假**（二·3「半天至一天」）：现有 `Date` 字段表达不了半天，是否要把 `date_from/date_to` 改成 `Datetime`？ | **不做**：破坏性改造，既有 2 行 + 全部下游渲染 + 课代表判定都要动 | 独立需求；影响面 = `edu.leave` 两个字段 + 全部渲染点 + `days` 计算 |
| Q2 | 一级审批**超时后**要不要**自动改派**教务处（不只是提醒）？ | **不做**：用户没要求；会与"转交后原审批人不能再批"的留痕语义打架 | `route_of()` 1 处 + cron 39 的 body 文案 |
| Q3 | 教职单的二级是否要落**系统组（校长）**（§5.4 的推定） | **按推定实现**（无员工条例 ⇒ 同构） | `route_of()` staff 分支 1 处 |
| Q4 | PDF 三·1「导师签字**再报**教务」的串行读法（§1.1）是否要启用 | **不启用**（按用户裁决"≤3 天班主任批"= 一级即终）；开关 `edu_portal.leave_always_two_stage` 已预留 | 改 1 个系统参数，**无需改代码** |
| Q5 | 条例四·1「违规记入**综合评估档案**」 | **本期不做**（跨模块），登记为后续独立需求 | 独立需求 |
| Q6 | 老师名单到位前，是否需要先手工指定一个"临时班主任"以便试用 | **不需要**：无班主任时自动落教务处，链路已完整可跑 | 无（用系统参数 `edu_portal.leave_principal_user_ids` 即可单点指定教务长） |

---

## 附：与铁律的对应关系（自查表）

| 铁律 | 本文对应 |
|---|---|
| 铁律 0（先调研后设计） | 调研档案 `docs/research/leave-approval.md`；本文每个取舍都指回它的条目 |
| code-map §6 第 3 条（权限） | §8.2；不新建自定义组，复用 `group_op_back_office_admin` / `base.group_system` |
| code-map §6 第 7 条（三件套 + 先设计） | 本文即设计；文件清单见 §9.2 |
| code-map §6 第 10 条（无障碍） | §9.3 跑 `check_accessibility.py` |
| code-map §6 第 11 条（QWeb dict 遍历） | §9.3 跑 `check_qweb_dict_foreach.py` |
| code-map §6 第 12 条（权限四层） | §8.3 逐对象声明层级 |
| code-map §6 第 13 条（身份反查唯一口径） | §5.3 走 `edu_schedule/models/identity.py` |
| code-map §10（改动闭环） | §9.3 |
| code-map §10.1（注册表铁律） | §9.2 / §9.3：改 .py ⇒ `deploy_myedu.sh` 必重启 web；验收跑 `check_live_registry.py` |
| `openeducat_erp/**` 只读 | §5.1 用 `_inherit='op.batch'`；§9.2 明列不改基座 |
| `edu_telegram/**BT~ 不动 | §9.2 明列不改 |
| Odoo 19 语法差异 | §4.2 用 `models.Constraint`（不是静默失效的 `_sql_constraints`） |

