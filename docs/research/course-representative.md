# 调研：课代表（学生干部身份 / 课程内有限权限）

> 铁律 0 落盘。每条结论带一手来源 URL；查不到的标「未验证」且**不得当结论用**。
> 调用方：`docs/plans/course-representative-design.md`。
> 初版 2026-09-19；骨架先行落盘（commit 81273f3），逐节补全。
>
> **取证锚点**：
> - Odoo 19 核心源码 = `odoo/odoo` **19.0 分支 head `6bae1e2f5eed5aae790944492e3d89d50bab5954`**（提交日 2026-09-16），
>   下列行号取自该提交的全量源码快照；URL 用 `blob/19.0`（内容与该 SHA 一致）。
>   本地**没有** Odoo 核心源码（`openeducat_erp/` 只是 OpenEduCat 快照）⇒ 核心结论全部基于在线 19.0 源码。
> - Canvas = `instructure/canvas-lms` master；Moodle = `moodle/moodle` **MOODLE_500_STABLE**
>   （注：`main` 分支的 `lib/db/install.xml` 当前 404，分支迁移中）。
> - 本仓 = OpenEduCat 19.0 源码快照 `openeducat_erp/` + 全部自研 `custom_addons/`（本机实测）。

---

## 0. 一句话回答：能不能装现成的？

# **不能装。必须自研 —— 但有三套现成形状可以抄。**

理由（三句话）：

1. **Odoo 19 核心没有任何「某人在某个课程/班级里拥有有限权限且带有效期」的模型** ——
   权限作用域只有「全局组」和「组 + 记录域」两种，**都没有时间维度**（§1.1）。
   Odoo 官方把「有效期」做在**凭证**（API Key）上，不是做在**组成员**上。
2. **OCA 没有课程/助教/课代表类现成模块**：`OCA/vertical-education` 的 19.0 分支**零模块**（空脚手架）；
   全组织 266 仓库名+描述扫描 + 5 个候选仓库全源码扫描 + 官方应用商店检索，
   `course representative` / `teaching assistant` / `student assistant` = **0 命中**（§2）。
3. **唯一能装的是 OCA `base_user_role`（LGPL-3，19.0 Production/Stable）** ——
   它给了「带 `date_from`/`date_to` 的角色行 + ir.cron 每 3 小时到期回收」的**完整机制骨架**，
   但作用域是「用户 ↔ **全局**角色」，**没有课程/班级维度**。
   ⇒ **能抄它的机制，装不了「课代表」的语义。**

要抄的三套形状（见 §3–§5）：
- **Canvas**（最值得抄）：「课代表 = 课程下的一种 enrollment 类型」+ 权限用 `available_to/true_for` 矩阵表达
  + 时效用 enrollment 起止日 + **5 分钟粒度服务端 cron 主动失效** + 已有「临时注册」到期动作三选一先例。
- **Moodle**：`(userid, roleid, contextid)` 的「一人一课一角色」数据模型最干净 —— **但时效绝不抄它**
  （1.9 有 `timestart/timeend`，2.0 **主动删除**并迁走）。
- **钉钉**：「代理时间」= 授权强制带时间窗且可撤销（国内大厂里唯一）；「表单内联系人审批」=
  发起人指定审批人（说明「学生做审批人」在通用审批引擎里被官方支持，不是我们发明的概念）。

**必须自研、且三体系皆无先例的**：**「学生请假 / 出勤类审批」这个域对象** ——
Canvas 核心**没有**考勤/请假模型（`attendance` 只作为第三方 LTI 示例出现），
Moodle 的 attendance 是第三方插件，国内教务 SaaS 也未见成品（§3.3 / §4 / §5.3）。

---

## 1. Odoo 19 核心 + OpenEduCat 基座

### 1.1 Odoo 19 核心：组、行级规则、订阅、频道成员 —— 结构完整，**零时间维度**

| 模型 | 能否表达「某人在某范围内的有限权限」 | **有效期** | 一手证据（19.0） |
|---|---|---|---|
| `res.users` / `res.groups` | 只能「全局、整组」授权，**无范围** | **无** | [res_users.py#L257-L259](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/res_users.py#L257-L259)（`group_ids` 是普通 m2m）；[res_groups.py#L16-L37](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/res_groups.py#L16-L37)（全部字段） |
| `ir.rule`（行级） | 有：组 + `domain_force` 限记录 | **无**（只有 `active` 开关，L23） | [ir_rule.py#L22-L30](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/ir_rule.py#L22-L30) |
| `ir.model.access` | 有：组 × 模型 × CRUD | **无** | [ir_model.py#L2086-L2093](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/ir_model.py#L2086-L2093) |
| `mail.followers` | 有「按记录订阅」，但**只影响通知、不产生权限** | **无** | [mail_followers.py#L27-L38](https://github.com/odoo/odoo/blob/19.0/addons/mail/models/mail_followers.py#L27-L38) |
| `discuss.channel.member` | 有「按频道成员」 | **无**（`mute_until_dt`/`unpin_dt` 只是通知/置顶偏好，L45-L47） | [discuss_channel_member.py#L29-L57](https://github.com/odoo/odoo/blob/19.0/addons/mail/models/discuss/discuss_channel_member.py#L29-L57) |
| `calendar.attendee` | 有「按日程参与者」+邀请 token，但只是参与状态 | **无** | [calendar_attendee.py#L34-L45](https://github.com/odoo/odoo/blob/19.0/addons/calendar/models/calendar_attendee.py#L34-L45)；token [calendar_event.py#L142](https://github.com/odoo/odoo/blob/19.0/addons/calendar/models/calendar_event.py#L142) |
| **`res.role`（mail 模块）** | ⚠ **不是权限容器**：只有 `name` + `user_ids`，是通讯录里的**身份标签** | **无** | [res_role.py#L14-L15](https://github.com/odoo/odoo/blob/19.0/addons/mail/models/res_role.py#L14-L15)；用法仅作 Discuss 搜索/展示 [res_partner.py#L307](https://github.com/odoo/odoo/blob/19.0/addons/mail/models/res_partner.py#L307) |
| `hr` / `resource` | 无临时授权概念；`hr.leave.allocation` 的 `date_from/date_to` 是**休假额度**不是权限 | 额度有 | [hr_leave_allocation.py#L67-L69](https://github.com/odoo/odoo/blob/19.0/addons/hr_holidays/models/hr_leave_allocation.py#L67-L69) |

**⚠ 概念映射提醒（防被名字骗）**：名字最像「角色」的 `res.role` 恰恰**不含权限**；
真正决定权限的是 `res.groups` + `ir.model.access` + `ir.rule` 三件套。

**其他核查**：
- 组继承靠 `implied_ids`（[res_groups.py#L69](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/res_groups.py#L69)）
  在运行时展开为 `all_group_ids`（[res_users.py#L446-L452](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/res_users.py#L446-L452)）——
  继承是**静态图，没有到期概念**（上面 URL 的路径请以 `odoo/odoo` 仓库为准，见文末勘误）。
- `res.groups` 上唯一带「时长」的字段是 **`api_key_duration`**（API Key 最大有效天数，
  [res_groups.py#L32-L41](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/res_groups.py#L32-L41)）——
  它管的是**密钥时长，不是组成员时长**。
- **全仓 grep `delegat`（官方 addons 101 处命中）没有一处是「权限委托」**：
  只有 `_inherit` 委托继承的注释、Azure 的 "user delegation key"、passkey 的 `delegate_permission/*` 常量。
  ⇒ **Odoo 19 没有「授权委托」模型。**

### 1.2 Odoo 19 核心唯一的「带有效期的授权」：API Key（可作设计参照）

- `res.users.apikeys.expiration_date`（[res_users.py#L1529](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/res_users.py#L1529)）
  + 校验/禁止过去日期（[res_users.py#L1577-L1591](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/res_users.py#L1577-L1591)）。
- 组级上限 `api_key_duration` 与对应约束（[res_groups.py#L32-L41](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/res_groups.py#L32-L41)）。

**含义**：Odoo 官方把「有效期」做在**凭证**上，而不是做在**组成员**上
⇒ 我们要的「课代表到某日失效」在核心里**没有对应抽象**，必须自研。

### 1.3 「到期自动回收权限」在 Odoo 里的三种现成机制（**可复用**）

1. **`@api.autovacuum`（官方推荐的「过期清理」通道）**
   `ir.autovacuum._run_vacuum_cleaner()` 收集全库所有 autovacuum 方法并逐个执行
   （[ir_autovacuum.py#L22-L43](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/ir_autovacuum.py#L22-L43)），
   由一条 ir.cron 记录驱动（[base/data/ir_cron_data.xml#L7](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/data/ir_cron_data.xml#L7) 的 `model._run_vacuum_cleaner()`）。
   官方实例：`_gc_user_apikeys()` 直接 DELETE 过期密钥
   （[res_users.py#L1714-L1722](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/res_users.py#L1714-L1722)）。
   ⚠ **它删的是数据行，历史上不负责改组成员。**
2. **`base.automation` 时间触发器 `on_time`**：基于模型上的日期字段 + 偏移量
   （[base_automation.py#L189-L191](https://github.com/odoo/odoo/blob/19.0/addons/base_automation/models/base_automation.py#L189-L191)、
   字段 [#L216-L218](https://github.com/odoo/odoo/blob/19.0/addons/base_automation/models/base_automation.py#L216-L218)），
   底层会维护一条 ir.cron（[同文件 #L676-L683](https://github.com/odoo/odoo/blob/19.0/addons/base_automation/models/base_automation.py#L676-L683)）。
   **用法**：把「有效期至」字段配成 `on_time` 触发器 → 到点执行 Server Action（把用户移出组），**零代码**。
3. **OCA 实际做法（推荐照抄）**：一条 ir.cron 定时调用模型方法重算成员 —— 见 §2.2 的
   `base_user_role.cron_update_users()`。这是「带日期授权」场景下 **OCA 的通行解法**。

> **结论（1.1–1.3）**：Odoo 19 核心**必须自研**。没有任何模型能表达「某人在某课程/班级拥有有限权限且有有效期」；
> 可复用的只有**回收机制**（ir.cron / `@api.autovacuum` / `base.automation on_time`），
> **有效期语义必须自己加字段、自己写回收逻辑**。

### 1.4 OpenEduCat 19.0 基座：本仓实测（**硬证据，可直接当结论**）

**取证方式**：直接 grep 本机快照 `openeducat_erp/`（OpenEduCat 19.0 官方源码快照）
与 `custom_addons/`（全部自研）。命令与命中数见设计文档 §0 查重表。

**结论 1：全仓零「课代表 / 班代表 / 学生干部 / 助教实体」。**

| 关键词 | 实测命中 | 命中是什么 |
|---|---|---|
| 课代表 / 班代表 / 课委 | **0** | — |
| 学生干部 / 班干部 / 班长 | **0** | — |
| assistant / representative / course_rep / class_monitor（`.py`） | **0** | — |
| 助教 | **8**（7 处自研 + 1 处 zh.po 子串误命中） | **全部是「评教类型」或营销文案**：`edu_eval/models/admin_eval.py:15` `('ta_review', '助教评教')`、`edu_eval/controllers/eval_portal.py:17`、`edu_eval/views/eval_views.xml:40,127`、`edu_eval/__manifest__.py:4`、`edu_portal/controllers/batch2.py:307`、`edu_brand/views/pages.xml:183` |

⇒ **线索要求核实的 `ta_review`：确认只是评估模块的「评教类型」枚举值，不是助教实体。**
（设计文档 §0 有逐行明细。）

**结论 2（上游旁证）**：基座组定义只有**模块级**粗细 ——
`openeducat_core/security/op_security.xml`（本地文件 L38 起）里的 `group_op_faculty` /
`group_op_back_office_admin`，其余各模块是 `group_op_<模块>_user/manager`（共 20+ 个），
**没有课程/班级维度**。全仓 grep `represent|assistant|delegat|monitor`（`*.py`）⇒ **0 命中**。
OpenEduCat 19.0 **已不在 OCA**（见 §2.1）⇒ 本仓是唯一可用的该系列 19.0 来源。

**结论 3：「学生/教师在某门课里的角色」在基座里只有两个落点，且都不可扩展。**

| 角色 | 模型 | 字段 | 依据（本地快照 路径:行号） |
|---|---|---|---|
| 学生在这门课 | `op.student.course` | `subject_ids`（M2M `op.subject`）、`course_id`、`batch_id`、`academic_term_id` | `openeducat_erp/openeducat_core/models/student.py:33-38` |
| 谁教这门课 | `op.session` | `faculty_id`（**required**）、`subject_id`（**required**）、`batch_id`（**required**） | `openeducat_erp/openeducat_timetable/models/timetable.py:42-48` |
| 班级 | `op.batch` | `start_date`、`end_date`（**required**）、`course_id` | `openeducat_erp/openeducat_core/models/batch.py:32-35` |
| 学期 | `op.academic.term` | `term_start_date`、`term_end_date`（**both required**） | `openeducat_erp/openeducat_core/models/op_academic_term.py:20-21` |
| 考勤登记簿 | `op.attendance.register` | `course_id`(req)、`batch_id`(req)、`subject_id`（**非 req，且既有代码不用它**） | `openeducat_erp/openeducat_attendance/models/attendance_register.py:34-39` |

> ⚠ **关键**：**`op.session` 只有一个 `faculty_id`**（单值 M2o）⇒ 基座**连「一门课两个老师」
> 或「主讲 + 助教」都表达不了**，更没有「学生在课程里有权限」的位置。
> ⇒ 「课代表」**必须新建实体**，不能靠填既有字段（与 §1.1 的核心结论一致，两条独立证据同向）。

**结论 4：本仓「带有效期的授权」已有 1 处先例（自研），但粒度不对。**

`edu.approval.delegate`（`custom_addons/edu_portal/models/leave.py:155-201`）：
`delegator_id` / `delegate_id` / `date_from` / `date_to` / `active`，
`_active_domain()`（:177-182）用「今天在起止日之间」做**实时判定**，`is_delegate_of()`（:184-192）放行。
- **可抄的形态**：起止日 + 激活域 + **实时判定**（≠ 只写 `state` 字段）。
  ⚠ **这正好与 OCA `base_user_role` 的「cron 重算」形成补集**：本仓既有做法是**实时判定**，
  OCA 是 **cron 重算** —— 课代表设计应**两者都要**（实时判定为权威 + cron 收口），即设计文档 §4.3 的「双保险」。
- **不可抄的粒度**：它代理的是 `res.users` 之间的**审批放行权**，**没有** subject/course 维度。
- **本仓没有任何 cron 去做「到期自动回收」** —— `edu.approval.delegate` 到期后**行还在**，
  只是 `_active_domain()` 不再命中。

### 1.5 ★ 已证实：`_sql_constraints` 在 Odoo 19 已废弃（**静默失效**）

> 这一条**直接决定需求③「数据库级唯一约束」怎么写**，是本调研最有操作价值的一条。

- **运行时告警原文**：`Model attribute '_sql_constraints' is no longer supported, please define models.Constraint on the model.`
  —— [model_classes.py#L162-L164](https://github.com/odoo/odoo/blob/19.0/odoo/orm/model_classes.py#L162-L164)
- **新写法类定义**：`class Constraint(TableObject)`，构造参数 `(definition, message)`，例 `models.Constraint("UNIQUE (x)", "消息")`
  —— [table_objects.py#L79-L100](https://github.com/odoo/odoo/blob/19.0/odoo/orm/table_objects.py#L79-L100)
- **为什么旧写法等于失效**：建约束只遍历 `self._table_objects`（[`_add_sql_constraints`, models.py#L3268-L3273](https://github.com/odoo/odoo/blob/19.0/odoo/orm/models.py#L3268-L3273)），
  而 `registry._sql_constraints` 在 19.0 只剩**一个空的遗留 set**（[registry.py#L233](https://github.com/odoo/odoo/blob/19.0/odoo/orm/registry.py#L233)）
  ⇒ **旧属性不再被解析，只打一条 warning，约束根本不会建到数据库**（不报错、容易漏测）。
- **官方迁移器**：`odoo/upgrade_code/18.1-00-sql-constraint.py`
  （脚本名 `18.1-00` ⇒ 该破坏性变更在 19.0 落地）
  —— [#L13-L15](https://github.com/odoo/odoo/blob/19.0/odoo/upgrade_code/18.1-00-sql-constraint.py#L13-L15)
- **官方 addons 已全面改造**：19.0 官方代码里 `models.Constraint(` 出现 **253 处**
  （例 [utm_tag.py#L24](https://github.com/odoo/odoo/blob/19.0/addons/utm/models/utm_tag.py#L24)；
  base 自己也在用 [res_groups.py#L39-L41](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/res_groups.py#L39-L41)）；
  连 OCA 的 19.0 模块同样在用（[base_user_role/models/role.py#L175-L178](https://github.com/OCA/server-backend/blob/19.0/base_user_role/models/role.py#L175-L178)）。

**对本仓的直接后果**：本仓 4 处仍写 `_sql_constraints` 的地方
（`custom_addons/edu_telegram/models/flow.py:15`、`binding_code.py:22`、`telegram_chat.py:20`、
`custom_addons/edu_portal/models/alert_read.py:29`）
**很可能在数据库里根本没有约束**——这是本调研**顺带发现的隐患**，
不属课代表需求范围，但**建议单独立项核查**（校长的「唯一约束不许用代码 if」正是这个坑）。
新建的 `edu.course.rep` 必须写 `models.Constraint`。

---

## 2. OCA（github.com/OCA）

### 2.1 教育类仓库现状：19.0 分支基本是空的

- **`OCA/vertical-education`**（唯一的教育组织仓库，license **AGPL-3.0**，分支 7.0→19.0）：
  **19.0 分支零模块** —— 整仓只有 18 个脚手架文件（`.copier-answers.yml` / `.pylintrc` / `.github` / LICENSE / README 等），
  **没有任何 `__manifest__.py`**；codeload 拉取仅 **104KB**。
  <https://github.com/OCA/vertical-education/tree/19.0>
  - 12.0 / 14.0 / 16.0 / 17.0 / 18.0 **同样只有 `.github`+`setup`，均无模块**；
    只有 ≤10.0 带 `openeducat_*` 模块（与本仓 `openeducat_erp/` 快照同源）：
    <https://github.com/OCA/vertical-education/tree/10.0>
- **`OCA/e-learning` 19.0**：只有 3 个模块 `website_sale_slides_multi_qty` / `website_sale_slides_order_line_link` /
  `website_sale_slides_portal`，**全是「卖课程」的电商配套，无任何权限/角色概念**。license **AGPL-3.0**。
  <https://github.com/OCA/e-learning/tree/19.0>
- **`OCA/role-policy`**：模块**只存在于 13.0**（`role_policy` + `role_policy_account/hr/hr_expense/sale/demo`），
  14.0 起全部为空分支，**19.0 无模块**。它把 `res.role` 扩成 ACL 策略框架
  （`models/res_role_acl.py`、`model_method_execution_right.py`）。license **AGPL-3**。
  <https://github.com/OCA/role-policy/tree/13.0>

### 2.2 ★ 唯一的可用命中：`OCA/server-backend` → **`base_user_role`**（19.0 有，**LGPL-3**）

- 元数据：manifest version **`19.0.1.3.1`**，license **LGPL-3**，development_status **Production/Stable**，depends `base`：
  <https://raw.githubusercontent.com/OCA/server-backend/19.0/base_user_role/__manifest__.py>
- **带有效期的授权**：`res.users.role.line` 上有 `date_from = fields.Date("From")` / `date_to = fields.Date("To")` /
  `is_enabled`（compute，今日不在区间即为 False）：
  [models/role.py#L172-L192](https://github.com/OCA/server-backend/blob/19.0/base_user_role/models/role.py#L172-L192)
- **到期自动回收**：`cron_update_users()`（[role.py#L129-L139](https://github.com/OCA/server-backend/blob/19.0/base_user_role/models/role.py#L129-L139)）
  由 ir.cron **每 3 小时**调用（[data/ir_cron.xml](https://github.com/OCA/server-backend/blob/19.0/base_user_role/data/ir_cron.xml) 的 `model.cron_update_users()`），
  最终 `set_groups_from_roles()` 重算用户实际组（`models/user.py` L72）。
  README 功能点原文：「activate/deactivate roles depending on the date」：
  [README.rst](https://github.com/OCA/server-backend/blob/19.0/base_user_role/README.rst)
- **它给不了什么**：作用域是「用户 ↔ **全局**角色」（角色 = 若干低层组的集合），
  **没有课程/班级维度**，也不能给「某课程内的部分权限」；也没有单条授权级的记录范围。
  ⇒ **能装它的「有效期」机制，装不了「课代表」语义。**

### 2.3 关键词搜索：方法、覆盖与限制

- ⚠ **GitHub 代码搜索 API 未认证返回 401**（`https://api.github.com/search/code?q=...` → `{"message":"Requires authentication"}`），
  本会话无 token ⇒ **无法做 OCA 全组织代码级关键词检索**（见 §7 未验证）。
- **替代做法 1**：拉全 OCA 组织 **266 个仓库**的 name+description 做关键词扫描
  （`educ|teach|school|learn|student|cours|role|permiss|delegat|temporar`）：
  只命中 `vertical-education`、`e-learning`、`role-policy` 三个（结论见 §2.1）。
- **替代做法 2**：把 5 个候选仓库 19.0（role-policy 用 13.0）全源码落地后全文扫描：
  - README/源码里搜 `temporary access/permission/role`、`course representative`、`teaching assistant`、
    `delegation of access/rights`、`proxy access`、`substitute user` → **0 命中**；
  - 筛「同时含日期字段（`date_to`/`date_end`/`expiry`）**且**操作 `res.groups`/`group_ids`」的模块
    → **只有 `base_user_role`**（及其公司版测试）。这两条是「OCA 有没有带有效期授权」的**正面证据**。
- **替代做法 3**：Odoo 官方应用商店 apps.odoo.com（含商业模块）检索：
  `course representative` / `teaching assistant` / `student assistant` → **0 个模块**；
  `temporary access` → 仅 4 个通用 RBAC 模块（`access_right_control_manager`、`eg_user_security_role`、
  `user_access_management_bizople`、`visual_rbac_access_control`）。
  **对照查询** `student`/`teacher`/`school`/`course` 各返回 **18–20 个模块**，证明该检索方法有效
  （0 结果是真负例，但仍需注意 JS 渲染可能漏项）。

### 2.4 license 红线（对本仓）

| 仓库 / 模块 | license | 是否可用 |
|---|---|---|
| `OCA/vertical-education`（教育） | **AGPL-3.0** | ✗ 红线（且 19.0 无模块） |
| `OCA/e-learning` | **AGPL-3.0** | ✗ 红线（且与权限无关） |
| `OCA/role-policy`（仅 13.0） | **AGPL-3.0** | ✗ 红线 + 无 19.0 端口 |
| `OCA/server-backend/base_user_role` | **LGPL-3** | ✓ **可用**（19.0 Production/Stable） |
| `OCA/server-backend/base_user_role_company` | **AGPL-3.0** | ✗ 红线（且 Beta） |

> 本仓 `custom_addons/edu_portal/__manifest__.py:111` 是 **LGPL-3** ⇒ **只有 `base_user_role` 与本仓许可相容**；
> `base_user_role_company` 是按公司/校区隔离角色用的，**若要按校区隔离角色会踩 AGPL 红线**：
> <https://raw.githubusercontent.com/OCA/server-backend/19.0/base_user_role_company/__manifest__.py>

**结论（§2）**：**没有能直接装上的「课代表」现成模块**；只有 `base_user_role`（LGPL-3，19.0 可用）可装，
用于复用「日期有效角色 + cron 到期回收」**骨架**。**课程级作用域、课程内部分权限清单必须自研**
（建议照它的写法，别抄它的语义）。

---
## 3. Canvas LMS（`instructure/canvas-lms`，master 分支）—— **最值得抄，三件事全有现成实现**

### 3.1 TA 是不是一等公民 enrollment？—— **是**

`app/models/enrollment.rb` 是 STI 模型，`TaEnrollment` 是**五个正式类型之一**：

- L21-28 `SIS_TYPES`：`"TeacherEnrollment"=>"teacher", "TaEnrollment"=>"ta", "DesignerEnrollment"=>"designer", "StudentEnrollment"=>"student", "ObserverEnrollment"=>"observer"`
- L29 `WORKFLOW_STATES`（active/completed/deleted/invited/pending/…）
- L310 `scope :of_admin_type` = Teacher + TA + Designer；L312 `scope :of_instructor_type` = Teacher + **TA**
- L384-389 展示名映射：`"TaEnrollment" => "TA"`
- L166-168 `self.get_built_in_role_for_type(enrollment_type)` → `Role.get_built_in_role`
- 角色枚举在 `app/models/role.rb` L24 `ENROLLMENT_TYPES`；L154 `Role.get_built_in_role(name, root_account_id:)`；L127 `built_in_roles`

来源：<https://github.com/instructure/canvas-lms/blob/master/app/models/enrollment.rb> ｜
<https://github.com/instructure/canvas-lms/blob/master/app/models/role.rb>

### 3.2 TA 的权限来自哪里？—— **权限注册表 + role/role_override 落库**

- **权限清单（权威一手来源）**：`config/initializers/permissions_registry.rb` 的 `BASE_PERMISSIONS` 常量
  （L25 起，共 2493 行）。**每个权限都带两个关键字段**：
  `available_to`（可被哪些 role 开关）与 `true_for`（默认给哪些 role 打开）——这就是「TA 能做什么」的完整答案。
- `app/models/role_override.rb` L123-125 `self.permissions → Permissions.retrieve`；
  L128 `concluded_permission_types`（注释「permissions that apply to concluded courses/enrollments」⇒ **结课后权限会降级**）；
  L78-119 分粒度权限组；**L102-106 `MANAGE_TEMPORARY_ENROLLMENT_PERMISSIONS` = `temporary_enrollments_add/edit/delete`**
  ⇒ **「临时注册」本身就是一个独立权限点**（这是「课代表」最贴切的权限建模先例）。
- `lib/permissions.rb` L40 `Permissions.register`、L64 `Permissions.retrieve`（注册表实现）。
- 权限还会被 `RoleOverride` 逐账号/逐 role 覆盖，并按 context（Account / Course）生效。

来源：<https://github.com/instructure/canvas-lms/blob/master/config/initializers/permissions_registry.rb> ｜
<https://github.com/instructure/canvas-lms/blob/master/app/models/role_override.rb>

### 3.3 TA 能做 / 不能做什么（全部取自 `permissions_registry.rb` 的 `true_for`）

| 权限（Key） | 标签 | `true_for` 里有 `TaEnrollment`？ | 行号 |
|---|---|---|---|
| `read_roster` | Users - view list | ✅ 是 | L1765-1775 |
| `manage_students` | Users - manage students in courses | ✅ 是 | L1365-1368 |
| `send_messages` | Conversations - 给单个课程成员发消息 | ✅ 是 | L1909-1918 |
| `send_messages_all` | Conversations - **给全班发消息** | ✅ 是 | L1930-1939 |
| `read_announcements` | Announcements - view | ✅ 是 | L1592-1601 |
| `moderate_forum` | Discussions - moderate（含管理课程公告） | ✅ `available_to` 含 TA | L1493-1498 |
| `manage_grades` | Grades - **edit** | ✅ 是 | L1094-1097 |
| `select_final_grade` | **Grades - select final grade for moderation**（即 Moderate Grades） | ✅ 是 | L1891-1894 |
| `allow_course_admin_actions` | Users - allow administrative actions in courses | ❌ **否**（`available_to` 含 TA，`true_for` 只有 TeacherEnrollment/AccountAdmin） | L814-817 |

逐条核实：

1. **花名册**：**能**。TA 默认 `read_roster=true`（People 页 / `/courses/:id/users`），且 `manage_students` 也为 true。
   ⇒ **对应我们需求①「看本课程同学名单」——Canvas 给了现成答案。**
2. **课程通知**：**能**。`send_messages_all` 的 `true_for` 明确包含 `TaEnrollment`，即「给全课程发消息」；
   公告受 `read_announcements` + `moderate_forum` 控制。⇒ **对应需求①「给本课程同学发通知」。**
3. **批学生请假 / 缺席**：**不能——没有这个对象**。Canvas 核心**没有原生考勤/请假模型**；
   `attendance` 仅作为**第三方 LTI 工具**的示例出现
   （`doc/api/tools_xml.md` L79-81「Building a specialized attendance/seating chart tool」；
   `doc/api/navigation_tools.md` L74）。请假审批在 Canvas 里是外部 LTI / 外部系统的事。
   ⇒ **🔴 这是本项目必须自研、且无先例的一块**（对应需求①「审批本课程的出勤类请假」）。
4. **有类 Moderate Grades 开关吗**：**有**，就是 `select_final_grade`（Grades - select final grade for moderation），
   TA 默认打开。⚠ 但**我们不能抄这一条**：校长需求⑨明文「写死不给：看任何人的**成绩**」。

来源：<https://github.com/instructure/canvas-lms/blob/master/doc/api/tools_xml.md>

### 3.4 ★ 权限时效 —— Canvas 有**完整**现成机制（**最值得抄的一节**）

三层，从细到粗：

1. **enrollment 自带起止日期**
   - `enrollment.rb` L230 `are_sis_sticky :start_at, :end_at`；L615 `conclude` / L621 `unconclude`
   - L1560-1583 `effective_start_at` / `effective_end_at`：**级联 enrollment → course_section → course → enrollment_term**
2. **由 cron 驱动的到期自动失效（服务端主动，不依赖用户登录）**
   - `app/models/enrollment_state.rb` L154-165 `calculate_state_based_on_dates`：
     命中区间则 `state_valid_until = end_at`（"stores the next date trigger"）
   - L356-363 `self.recalculate_expired_states`，注释原文：
     **「called every ~5 minutes by a periodic delayed job」**，按 `state_valid_until < now` 批量重算
   - 调度点 `config/initializers/periodic_jobs.rb` **L301-302**：
     `Delayed::Periodic.cron "EnrollmentState.recalculate_expired_states", "*/5 * * * *"`
     ⇒ **5 分钟粒度、服务端主动失效，不依赖用户登录**
3. **★ 专门的「临时注册」先例（最贴近「课代表有到期时间」）**
   - `enrollment_state.rb` L173-184：`if enrollment.temporary_enrollment?` → 到期后按
     `temporary_enrollment_pairing&.ending_enrollment_state` 执行
     **`completed→conclude` / `inactive→deactivate` / 其它→`destroy`**（**到期动作三选一**）
   - 模型：`app/models/temporary_enrollment_pairing.rb`（L21-33，含 `created_by` / `deleted_by` / `workflow_state`）
   - API：`app/controllers/temporary_enrollment_pairings_api_controller.rb`
   - 权限点：`temporary_enrollments_add/edit/delete`（见 §3.2）
4. **Term 自动结课**：`app/models/enrollment_term.rb` L44 `are_sis_sticky :name, :start_at, :end_at`；
   L67-90 `update_courses_later_if_necessary` → `EnrollmentState.invalidate_states_for_term`。
   课程侧 `app/models/course.rb` L448-449 `conclude_at` / `restrict_enrollments_to_course_dates`；
   L2389-2391 `soft_concluded?`：`restrict_enrollments_to_course_dates` 开启时以 `end_at` 判定；
   L1221 `completed` 课程查询用 `conclude_at` 或 `enrollment_terms.end_at` 兜底。

> **§3 判断：能抄，且是最佳模板。**
> Canvas 把「TA」做成 enrollment 的一个类型，权限用 `available_to/true_for` 矩阵表达，
> 时效用 enrollment 的 `start_at/end_at` + **5 分钟 cron 失效** + 「临时注册」的**到期动作（结课/停用/删除 三选一）**
> —— 我们想要的三件事（**课代表 = 课程内有限角色、有限权限、到期失效**）它**全有现成形状**。
> 唯一空白是「学生请假审批」，Canvas 核心根本没有这个域对象，**必须自研**。

> ⚠ **抄 Canvas 时必须落地到 Odoo 的现实**：Canvas 有「课程 context + 权限矩阵 + enrollment 类型」三层结构，
> 而 Odoo 的组是全局的（§1.1）⇒ 我们**抄语义、不抄实现**：
> Canvas 的 `enrollment` = 我们的 `edu.course.rep`（课程级角色行）；
> Canvas 的 `available_to/true_for` 矩阵 = 我们**硬编码在判定函数里的固定权限清单**（不需要做成可配置矩阵——
> 校长已经把权限清单写死为 3 条，做成矩阵反而是过度设计）；
> Canvas 的 `start_at/end_at` + 5 分钟 cron = 我们的「实时判定（权威）+ 每日 cron（收口）」（设计文档 §4.3）。

---

## 4. Moodle（`moodle/moodle`，**MOODLE_500_STABLE**）

> 注：`main` 分支 `lib/db/install.xml` 当前返回 **404**（分支迁移中），故用最新稳定分支。

### 4.1 `role` + `context` 层级：一门课里给某人一个角色怎么落库

- 表结构 `lib/db/install.xml` **L1301-1325**：
  `role_assignments(id, roleid, contextid, userid, timemodified, modifierid, component, itemid, sortorder)`，
  `contextid` 外键 → `context.id`；**唯一索引 `(userid, contextid, roleid)`**
- context 层级常量 `lib/accesslib.php` **L122-136**：
  `CONTEXT_SYSTEM=10 / CONTEXT_USER=30 / CONTEXT_COURSECAT=40 / CONTEXT_COURSE=50 / CONTEXT_MODULE=70 / CONTEXT_BLOCK=80`
- **落库语义**：一门课 = `context` 表里一行 `contextlevel=50, instanceid=<courseid>`；
  「在某门课里给某人一个角色」= 往 `role_assignments` 插一行
  `(roleid=<角色>, userid=<人>, contextid=<该课的 context id>)`。权限判定从该 context 沿层级向上继承。
- 写入函数 `lib/accesslib.php` **L1579**：
  `role_assign($roleid, $userid, $contextid, $component = '', $itemid = 0, $timemodified = '')`
  —— **签名里没有任何时间参数**。

来源：<https://github.com/moodle/moodle/blob/MOODLE_500_STABLE/lib/db/install.xml> ｜
<https://github.com/moodle/moodle/blob/MOODLE_500_STABLE/lib/accesslib.php>

### 4.2 内置 TA / 非编辑教师角色 —— **有**，叫 `teacher` archetype

- `role` 表有 `archetype` 字段：`install.xml` **L1188**（注释「Role archetype is used during install and role reset」）
- archetype 名册 `lib/accesslib.php` **L1175-1176**：`'editingteacher' => 'editingteacher'`、`'teacher' => 'teacher'`
- 显示名 `lang/en/role.php` **L55** `$string['archetypeteacher'] = 'ARCHETYPE: Teacher (non-editing)'`；
  **L50** `archetypeeditingteacher = 'ARCHETYPE: Teacher (editing)'`；L311/L314 是 legacy 映射
- 二者能力差异的**一手证据是各模块 `db/access.php` 的 `archetypes` 默认值**：

| capability | 定义位置 | `teacher`（非编辑） | `editingteacher` |
|---|---|---|---|
| `moodle/course:viewparticipants`（**看参与者名单**） | `lib/db/access.php` L1016-1024 | ✅ `CAP_ALLOW` | ✅ `CAP_ALLOW` |
| `moodle/course:update`（改课程设置） | `lib/db/access.php` L845-853 | ❌ 无 | ✅ `CAP_ALLOW` |
| `moodle/course:manageactivities`（增删活动） | `lib/db/access.php` L983-991 | ❌ 无 | ✅ `CAP_ALLOW` |
| `mod/forum:addnews`（**发课程公告**） | `mod/forum/db/access.php` L94-103 | ✅ `CAP_ALLOW` | ✅ `CAP_ALLOW` |
| `mod/forum:addinstance`（加论坛） | `mod/forum/db/access.php` L29-38 | ❌ 无 | ✅ `CAP_ALLOW` |
| `mod/assign:grade`（**批改作业/评分**） | `mod/assign/db/access.php` L49-57 | ✅ `CAP_ALLOW` | ✅ `CAP_ALLOW` |
| `mod/assign:viewgrades` | `mod/assign/db/access.php` L152-158 | ✅ `CAP_ALLOW` | ✅ `CAP_ALLOW` |

即：**Moodle 的非编辑教师 =「能看名单、能发公告、能改成绩，但不能改课程结构」** —— 与 Canvas 的 TA **高度同构**。

### 4.3 权限时效 —— Moodle **没有**，而且**是它自己主动删掉的**（**关键反证**）

- Moodle **5.0** `lib/db/install.xml` L1301-1312：`role_assignments` **无 `timestart` / `timeend`**
- Moodle **1.9** `lib/db/install.xml` L811-824：`role_assignments` **有** `hidden` / `timestart` / `timeend`
- Moodle **2.0** `lib/db/upgrade.php` L4326-4335（把 `MIN(ra.timestart), MIN(ra.timeend)` 从 `role_assignments`
  迁到 `user_enrolments`）+ **L4341-4370**，注释原文：
  **「hidden is completely removed, timestart+timeend are now in the user_enrolments table」**，随后 drop 掉三个字段
- 现存的时效只剩 **选课层**：`user_enrolments.timestart` / `timeend`（`install.xml` L306-307，
  `timeend` 默认 2147483647），由注册插件在 cron/访问时判定（**该判定链路未逐行核实**，见 §8）。
- `role_assign` 签名无时间参数（§4.1）⇒ **「非编辑教师」这个角色本身没有到期概念**。

来源：<https://github.com/moodle/moodle/blob/MOODLE_500_STABLE/lib/db/upgrade.php> ｜
<https://github.com/moodle/moodle/blob/MOODLE_19_STABLE/lib/db/install.xml>

### 4.4 学生干部 / 课代表在 Moodle 里怎么实现

- **核心没有任何「课代表 / 学生干部 / 学生助教」内置角色**：archetype 名册（L1175-1176）与 course 级默认角色里
  全是 教师/管理者/学生/访客，**没有学生管理类角色**。
- 唯一可行路径是**自建 role**（`role` 表允许 `archetype=''` 的自定义角色）+ 把该 role 指派到课程 context。
  **但自建 role 依旧没有到期时间**（§4.3）。

> **§4 判断：模型能装、时效不能抄。**
> Moodle 的「role + context 层级 + `role_assignments`」是表达「某人在某门课有某角色」的**最干净模型**
> （`contextlevel=50` 一行搞定，**天然支持「同一人在 A 课是课代表、B 课是学生」**），
> 值得照搬为**数据模型**；但**权限时效 Moodle 自己放弃了**（1.9 有、2.0 明确删除并迁走），
> 所以「到期自动失效」**绝不能参考 Moodle，必须学 Canvas**。

---

## 5. 国内同类（校管家 / ClassIn / 钉钉 / 企业微信 / 飞书 / 希沃）

### 5.1 「班干部 / 课代表 / 助教 / 学生干部」这个功能名存在吗？

| 平台 | 证据 | 是否一手 | 结论 |
|---|---|---|---|
| **希沃云班** | 帮助中心「角色与权限」<https://help.seewo.com/yunban/ixjXwwnvYL> ：预设角色为**班主任、年级级长、任课老师、办公室主任、德育主任、教务主任、电教老师、督导主任、行政老师、值周老师**；支持自定义角色（名称/描述/功能权限/参照角色复制），系统角色不可删 | ✅ 一手（正文可直接抓取） | **有完整的角色权限体系，但预设角色全是教职工，没有「课代表/学生干部」这个功能名** |
| **钉钉** | 官方文档「管理角色」<https://help.dingtalk.io/zh/contacts/manage-roles.md> ：「通讯录 ＞ 角色管理 ＞ 新增角色」，自建角色组 + 分配成员 | ✅ 一手（Mintlify 可直取 `.md`） | 只有组织角色，**无课代表概念、无有效期** |
| **ClassIn** | 只找到第三方描述「联席教师…区分主讲人员与辅助人员的身份属性」「支持添加助教人员」（知乎 <https://www.zhihu.com/question/634757292> 、CSDN/头条转载） | ❌ **非一手** | 「联席教师」是真实功能名，但**官方 URL 未取到**，标 **未验证** |
| **校管家** | <https://wiki.xiaogj.com/docs/quan-xian-guan-li> 页面是 JS SPA，正文抓不到；仅搜索快照摘到「机构管理→权限管理 / 创建权限组 / 勾选权限点 / 给员工分配权限」 | ⚠️ **只有搜索快照级证据，非一手** | 是**员工**权限组，未见学生角色 |
| 希沃云班「设置班级值日生」 | <https://help.seewo.com/yunban/XQ32wx2Xu0> | ❌ 页面正文为空（SSR 只渲染目录） | **未验证** |

⇒ **没有任何一家把「课代表」做成一等功能名**；最接近的成品是 ClassIn 的「联席教师/助教」（**教师侧**），
以及希沃云班的**通用「自定义角色」**。

### 5.2 组织架构里的「临时权限 / 权限有效期」—— 钉钉有，其它没有

- ✅ **钉钉 OA 审批「代理人设置」（一手，最值得抄）**：<https://help.dingtalk.io/zh/approval/admin-agent-settings.md>
  - 原文：管理员在「审批管理后台-系统管理-代理设置」，**选择「被代理人」和「代理人」，选择「代理时间」**；
    「代理记录」可按被代理人/代理人查询，**也可以撤销生效中的代理记录**
  - 这是国内大厂里明确**带时间窗的权限委派**，形态就是「**主体 + 客体 + [起, 止] + 可撤销**」
  - ⚠ **与本仓 `edu.approval.delegate`（`models/leave.py:155-201`）形态完全一致**（§1.4 结论 4）
    ⇒ 说明本仓那条自研设计**方向是对的**，可作课代表的直接同类先例
- ✅ **钉钉「管理角色」**（一手）：<https://help.dingtalk.io/zh/contacts/manage-roles.md> —— 只有角色组 + 成员，**无有效期**
- ❌ **飞书「管理员角色」**（一手）：<https://www.feishu.cn/hc/zh-CN/articles/360043495213>
  —— 已对全文逐词检索，**「有效期/到期/生效/时间/临时」全部 NOT FOUND** ⇒ 飞书管理员角色无时间窗
- ⚠ **飞书「管理员设置成员登录有效期」**：<https://www.feishu.cn/hc/zh-CN/articles/538280274631>
  —— 最短 1 天、最长 90 天。**但这是「登录会话有效期」，不是「权限有效期」，别抄错**
- ⚠ **企业微信「权限管理」**：<https://open.work.weixin.qq.com/help2/pc/20933>
  —— 角色只有 **创建人 / 超级管理员 / 分级管理员**（分级管理员 = 管理范围）。页面是 SPA，正文抓不到；
  搜索快照未见有效期 ⇒ 标 **未验证**（同站目录 <https://open.work.weixin.qq.com/help2/pc/17353>）

### 5.3 国内有没有「学生审批学生请假」的先例？

- ✅ **机制层面有先例（钉钉 OA 审批，一手）**，但**不是教务产品，而是通用审批引擎**：
  - **「表单内联系人审批」** <https://help.dingtalk.io/zh/approval/set-form-contact-approval.md>
    —— 表单里加「联系人控件」，把节点处理人设为「表单内的联系人」，**由发起人（或上一节点）选择具体的人来审批**。
    原文举例是「发起人提交用车申请后…将司机设置为表单中的联系人控件」。
    **推论（非原文断言）：发起人若能填写任意成员，学生就可以把课代表填成审批人。**
  - **「角色人员审批」** <https://help.dingtalk.io/zh/approval/set-role-approval.md>
    —— 设置角色 + 管理范围作为审批人。
  - 「流程设计」 <https://help.dingtalk.io/zh/approval/admin-process-design.md> ；「代理人设置」见 §5.2
- ❌ **产品名层面未见先例**：搜到的「学生请假线上审批」资料全是 **班主任 → 教务处/辅导员** 的链路，
  且来源为百度文库、CSDN、51CTO 博客（**营销/文档站，非一手**）。
  **没有任何国内教务 SaaS 把「学生干部审批学生请假」做成内置命名功能。**

> **§5 判断：功能名抄不到，机制能抄。**
> 「课代表/班干部」在国内所有查到的产品里**都不是一等功能名**（希沃/钉钉只有教职工角色，
> ClassIn 的「联席教师」是**教师侧**且非一手证据，校管家只有员工权限组）；
> 唯一值得照抄的是**钉钉「代理人设置」的形状 —— 权限授予时强制带 [代理时间] 且可撤销**
> （这是我们「到期时间」字段的直接同类先例），以及**「表单内联系人审批」—— 由发起人指定审批人**
> 这一机制（它说明「**学生做审批人**」在通用审批引擎里被官方支持，而不是我们发明的新概念）。

---

## 6. 权限时效：Odoo 有没有现成的「带有效期的授权」？—— **没有，必须自研**

四体系横向对照（本节即需求「权限时效」的**正面回答**）：

| 体系 | 有「某人在某范围内有限权限」？ | 有「有效期」？ | 一手证据 |
|---|---|---|---|
| **Odoo 19 核心** | ❌ 只有「全局组」与「组+记录域」，**无范围** | ❌ 全无（唯一的有效期在 **API Key 凭证**上） | §1.1 / §1.2 |
| **OCA 教育类** | ❌ 无现成模块（`vertical-education` 19.0 空仓） | — | §2.1 |
| **OCA `base_user_role`（LGPL-3）** | ❌ 只有「用户 ↔ 全局角色」 | ✅ **有** `date_from/date_to` + ir.cron 每 3 小时回收 | §2.2 |
| **Canvas** | ✅ enrollment 类型（TaEnrollment 一等公民） | ✅ `start_at/end_at` + **5 分钟 cron** + 到期动作三选一 | §3.1 / §3.4 |
| **Moodle** | ✅ `(userid, roleid, contextid)` 最干净 | ❌ **1.9 有、2.0 主动删除** | §4.1 / §4.3 |
| **国内（钉钉）** | ✅ 组织角色 + 管理范围 | ✅ **只有「代理设置」带代理时间且可撤销** | §5.2 |

**落地方案（三选一，本项目的裁定见设计文档 §4.3）**：

| 方案 | 来源 | 结论 |
|---|---|---|
| 装 OCA `base_user_role` | §2.2 | ❌ **不能解决课程维度** ⇒ 装进来也还要自研课代表实体，只会多一份依赖与 AGPL 风险面 |
| 用 `base.automation` `on_time` 零代码回收 | §1.3-2 | ⚠ 可作为**补充**，但「触发时机」不可控、且**不能代替判定处的实时校验** |
| **自研：实体字段 + 实时判定（权威）+ ir.cron（收口）** | §1.3-3（OCA 通行解法）+ §1.4 结论 4（本仓先例）+ §3.4（Canvas） | ✅ **采用**（设计文档 §4.3「双保险」） |

**为什么必须「实时判定 + cron」双保险**（三条独立证据同向）：
1. OCA `base_user_role` **只靠 cron**（每 3 小时）⇒ 最长有 3 小时窗口期**权限还在**，对「请假审批」这种敏感动作不可接受；
2. Canvas **只靠 cron**（5 分钟）⇒ 同样有窗口期，但粒度更细、且**服务端主动**（不依赖用户登录）；
3. 本仓 `edu.approval.delegate` **只靠实时判定**（`_active_domain()`）⇒ 无窗口期，但**没有归档/收口**，
   过期行永久留在表里（所以设计文档要求每日 cron 把 `state` 写成 `expired` 并留痕）。
⇒ **两者都要**：实时判定保证「一秒都不多」，cron 保证「数据库里有可查的到期事实与留痕」。

---

## 7. 结论汇总：对本设计的直接影响

| # | 结论 | 对本设计的直接动作 |
|---|---|---|
| 1 | Odoo 19 核心无「课程内 + 带有效期」权限模型 | **自研 `edu.course.rep`**（设计文档 §1 载体裁定）——证据 [#§1.1](#11-odoo-19-核心组行级规则订阅频道成员--结构完整零时间维度) |
| 2 | OCA 无课代表模块；`base_user_role` 只有「用户↔全局角色」 | **不装 OCA 模块**（省一份依赖与 AGPL 风险面）；只抄它的「日期 + cron」写法 |
| 3 | **Canvas 有完整形状**（enrollment 类型 + 权限矩阵 + 起止日 + cron 失效 + 到期动作三选一） | 抄**语义**：课程级角色行 + 硬编码权限清单 + 实时判定 + cron 收口（**不抄「改成绩」那条**，需求⑨禁止） |
| 4 | **Moodle 的 `(userid, roleid, contextid)` 模型最干净** | 抄**数据模型**：我们的 `(subject_id, student_id)` 槽位是其简化版，**天然支持「同一人在 A 课是课代表、B 课是学生」** |
| 5 | **Moodle 主动删掉了角色时效** | **时效绝不参考 Moodle**，必须学 Canvas（§4.3） |
| 6 | **钉钉「代理时间」= 授权强制带时间窗 + 可撤销** | 支撑设计文档 §4.3「三层阶梯算期限」与 §4.2「中途撤销」的**同类先例**；也印证本仓 `edu.approval.delegate` 方向正确 |
| 7 | **「学生做审批人」在钉钉通用审批引擎里被官方支持** | 需求②（学生身份做审批人）**不是我们发明的概念**，有官方机制先例可引用 |
| 8 | **Canvas / Moodle / 国内 都无「学生请假审批」域对象** | 🔴 **必须自研**；设计文档 §6 已写明挂载点（既有 `edu.leave`，不新建第二套） |
| 9 | **Odoo 19 `_sql_constraints` 静默失效**（§1.5） | 需求③的唯一约束**必须**写 `models.Constraint('UNIQUE (subject_id)')`；⚠ 本仓 4 处旧写法建议单独立项核查 |
| 10 | OpenEduCat 基座 `op.session` 只有一个 `faculty_id` | 基座**连「主讲+助教」都表达不了** ⇒ 更进一步证明课代表必须新建实体（§1.4 结论 3） |

---

## 8. 未验证 / 待确认（**不得当结论用**）

### 8.1 外部调研未验证项

1. **Odoo 企业版是否有临时授权 / 带期限权限**：`enterprise` 仓库不公开，19.0 社区源码不含企业代码
   ⇒ **未验证**（**不能断言企业版有或没有**）。
2. **OCA 全组织代码级关键词检索**：GitHub 代码搜索 API 未认证返回 **401**
   （`https://api.github.com/search/code?q=course+representative+org:OCA` → `Requires authentication`），
   本会话无 token ⇒ **未验证**。§2 的负面结论仅来自「仓库名+描述全量扫描（266 仓）+ 5 个候选仓库全源码扫描
   + 官方应用商店检索」**三重覆盖**，不等价于代码级穷举。
3. **apps.odoo.com 检索的完备性**：结果为服务端 HTML 提取，页面部分内容可能 JS 渲染
   ⇒ 0 结果存在少量漏项风险（对照查询表现正常，故风险较低）。
4. **Odoo 官方文档层对 `models.Constraint` 的说明**：
   <https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html>
   抓取在 10 万字符处被截断且未命中 `Constraint` 关键字 ⇒ **未在文档层核实**；
   §1.5 结论全部基于**源码**（强度更高）。
5. **未逐条核实**：`hr` / `resource` 全模块的每个字段
   （只做了 `delegat`/`expiry` 系列 grep + 关键模型字段核查）。
6. **ClassIn「联席教师/助教」的官方 URL 未取到**（只有知乎/CSDN 等**非一手**描述）⇒ **未验证**。
7. **校管家权限管理**：<https://wiki.xiaogj.com/docs/quan-xian-guan-li> 是 JS SPA，正文抓不到
   ⇒ 只有搜索快照级证据，**非一手**。
8. **企业微信分级管理员是否有有效期**：<https://open.work.weixin.qq.com/help2/pc/20933> 是 SPA，正文抓不到
   ⇒ **未验证**。
9. **Moodle `user_enrolments.timeend` 的具体判定链路**（哪个 cron / 什么时机真正把用户移出课程）
   ⇒ **未逐行核实**。
10. **希沃云班「设置班级值日生」** <https://help.seewo.com/yunban/XQ32wx2Xu0> 正文为空（SSR 只渲染目录）
    ⇒ **未验证**。

### 8.2 本文的取证方法限制（诚实标注）

- Odoo 19 核心结论基于 **head `6bae1e2f5eed5aae790944492e3d89d50bab5954`** 的源码快照；
  **行号会漂移**，实施时以当时的 `19.0` 分支实测为准（与 `docs/research/README.md` 收录规范第 4 条一致）。
- GitHub 代码搜索 API 401 是本调研**最大的覆盖缺口**（见 8.1-2）。

### 8.3 顺带发现的仓内隐患（**不属本需求范围，建议单独立项**）

- **`_sql_constraints` 静默失效**（§1.5）：本仓 4 处旧写法
  （`custom_addons/edu_telegram/models/flow.py:15`、`binding_code.py:22`、`telegram_chat.py:20`、
  `custom_addons/edu_portal/models/alert_read.py:29`）
  **在 Odoo 19 下很可能没有真正建到数据库**（不报错、只一行 warning）。
  ⚠ 其中 `edu_tg_claim`（`_sql_constraints` 已迁移为 `models.Constraint`，见
  `edu_tg_bind/models/tg_claim.py:87-90`）**是正确写法**；
  但 `edu_telegram` 的 3 处与 `edu_portal/models/alert_read.py` 的 1 处需核查。
  **⚠ 注意 `edu_telegram` 是匿名意见箱红线区域，核查前必须先确认不触碰其数据。**
- **本仓仍有 4 处旧写法未迁移**已在设计文档 §9.3-7 登记；本条给出**外部依据**（官方迁移器与告警原文）。
