# 调研：请假单拆分 + 分级审批 + 转交审批

> 主题：学生/教职人员请假单拆分 · 按天数分级审批 · 转交审批（铁律 0 调研档案）
> 日期：2026-09-25 ｜ 状态：**已完成**（含 1 条工具故障声明与 7 条未验证）
> 取证环境：本机 Odoo 19 容器 `edu19-clone-web-1`（镜像 `odoo:19`）+ 生产只读库 `prod-host` / `edu19`
> 规范：`docs/research/README.md`

---

## 0. 一句话结论

**Odoo 19 核心的 `hr_holidays` 只有「固定两级（Employee's Approver → Time Off Officer）、按请假类型配置」的审批，既没有按天数分流，也没有转交概念；OCA 在 19.0 分支上没有任何多级/条件审批模块（`base_tier_validation` 族只做到 18.0 且为 AGPL-3）；国内三家（钉钉/飞书/企微）里只有钉钉拿到了官方级的一手证据，而钉钉的「条件分支 + 日期区间按时长判断 + 转交/加签/代理」三件套与本次需求一一对应。**
⇒ 结论：**本仓自研有据**（不是"懒得找"，是三条路都查过且都有明确的排除理由）。

---

## 1. 取证环境与方法（可复现）

| 项 | 值 | 备注 |
|---|---|---|
| 本机 Odoo 19 源码 | `docker exec edu19-clone-web-1 sh -c 'ls /usr/lib/python3/dist-packages/odoo/addons/'` | 685 个模块；`hr_holidays` 在其中 |
| 生产库 | `ssh prod-host 'docker exec -i edu19-prod-db-1 psql -U odoo -d edu19 -A -P pager=off'` | **只读 SELECT / \d**，未做任何写操作 |
| 文档源文件技巧 | Sphinx 站点可用 `https://www.odoo.com/documentation/19.0/_sources/<path>.rst.txt` 直取**未渲染的 rst 源** | 绕开「导航栏吃满 100 KB 截断」的问题；正文页 URL 去掉 `_sources/` 与 `.rst.txt` 即为人访问页 |
| 钉钉文档 | `https://help.dingtalk.io` 是**静态 markdown** 站点：把任意文档 URL 末尾加 `.md` 即得纯文本；索引见 `https://help.dingtalk.io/llms.txt` | 与 `open.dingtalk.com`（SPA，抓不到正文）同属一套内容 |

### ⚠ 工具故障声明（影响取证范围，必须写清）

本次会话中 **`web_search` 工具持续返回 `unparseable response body`**（重试 4 次均失败），只能用 `web_fetch` 直取已知 URL + 必应（`cn.bing.com`）兜底检索。
**后果**：无法做「关键词 → 结果」式的全网遍历，因此**本报告只能覆盖"直接可达的一手文档"**，不能声称「已穷尽」。

---

## 2. Odoo 19 核心源码（读源码，不猜）

### 2.1 有没有 `hr.leave.approval` / `approval_level`？—— **没有**（已核实）

**证据一（模型文件清单）**：
```
$ docker exec edu19-clone-web-1 ls /usr/lib/python3/dist-packages/odoo/addons/hr_holidays/models/
__init__.py  calendar_event.py  hr_department.py  hr_employee.py  hr_employee_public.py
hr_leave.py  hr_leave_accrual_plan.py  hr_leave_accrual_plan_level.py  hr_leave_allocation.py
hr_leave_mandatory_day.py  hr_leave_type.py  hr_version.py  mail_activity_type.py
mail_message_subtype.py  res_company.py  res_partner.py  res_users.py  resource.py
```
**没有任何 approval 专属模型**。全模块 `grep -rn 'approval' models/` 的命中全部落在 `hr_leave.py` / `hr_leave_allocation.py` 的**方法名**（`_check_approval_update`、`_get_responsible_for_approval`）与 **mail.activity 类型**上，不是独立实体。

**证据二（Odoo 19 全 addons 扫描）**：
```
$ docker exec edu19-clone-web-1 sh -c "ls /usr/lib/python3/dist-packages/odoo/addons/ | grep -iE 'approv'"
（0 行命中）
```
**Odoo 19 社区版 685 个模块里没有名字含 "approv" 的模块。**

**证据三（官方文档目录树，证明"Approvals 应用"在 19.0 文档里不存在）**：
- `https://www.odoo.com/documentation/19.0/_sources/applications/productivity.rst.txt` → documents / sign / spreadsheet / dashboards / knowledge / calendar / appointments / discuss / data_cleaning / whatsapp / phone / to_do / ai（**无 approvals**）
- `https://www.odoo.com/documentation/19.0/_sources/applications/hr.rst.txt` → attendances / employees / appraisals / frontdesk / fleet / payroll / time_off / recruitment / referrals / lunch（**无 approvals**）
- `https://www.odoo.com/documentation/19.0/_sources/applications/services.rst.txt` → project / timesheets / planning / field_service / helpdesk（**无 approvals**）
- 同样三条在 **18.0 与 17.0** 也复查过，同样没有 approvals：
  `https://www.odoo.com/documentation/18.0/_sources/applications/services.rst.txt`、
  `https://www.odoo.com/documentation/17.0/_sources/applications/services.rst.txt`

> ⚠ **反证说明（不要把这条当结论用）**：`https://apps.odoo.com/apps/modules/19.0/approvals` 返回 **404**。但企业版模块**本来就不进公开应用商店**，所以 404 **不能**用来证明 Approvals 不存在。它只作为「社区版装不到」的旁证，**不作为**"Odoo 没有审批应用"的证据（见 §6 U3）。

### 2.2 那多级审批到底长什么样？——**固定两级 + 按类型配置**（已核实，含行号）

| 事实 | 一手来源 |
|---|---|
| 状态机 = `confirm`（To Approve）→ `validate1`（Second Approval）→ `validate`（Approved），另有 `refuse` / `cancel` | `hr_holidays/models/hr_leave.py:129-135`（本机 `odoo:19` 镜像） |
| 审批级别是**请假类型上的一个 Selection**：`no_validation` / `hr`（By Time Off Officer）/ `manager`（By Employee's Approver）/ `both`（两者都要） | `hr_holidays/models/hr_leave_type.py:83-90`；官方文档 `https://www.odoo.com/documentation/19.0/_sources/applications/hr/time_off/time_off_types.rst.txt`（"Time off requests section → Approval"） |
| 只有 `both` 会经过 `validate1`；`hr` / `manager` 都是**一步到位** | `hr_leave.py:1410-1415`（`elif validation_type == 'manager': state_result['confirm'].add('validate')`） |
| 审批人**跟着"人"走，不跟着"单"走**：`employee.leave_manager_id` → `employee.parent_id.user_id` → `holiday_status_id.responsible_ids` | `hr_leave.py:1500-1514` `_get_responsible_for_approval()` |
| 官方文档原文："Requests either need **one or two** approvals, if any, depending on how the specific type of time off is configured." | `https://www.odoo.com/documentation/19.0/_sources/applications/hr/time_off/management.rst.txt` |
| 权限组三层：`group_hr_holidays_responsible`（Time Off Responsible）/ `group_hr_holidays_user`（Officer）/ `group_hr_holidays_manager`（Administrator） | `hr_holidays/security/hr_holidays_security.xml:11-30` |
| 记录规则按 `employee_id.leave_manager_id` 分流 | `hr_holidays/security/hr_holidays_security.xml` 的 `hr_leave_rule_employee_update` |
| license = **LGPL-3**（不传染） | `hr_holidays/__manifest__.py`: `'license': 'LGPL-3'` |

**按天数分流？—— 不存在**（已核实）：
```
$ docker exec edu19-clone-web-1 sh -c "grep -rn 'number_of_days' /usr/lib/python3/dist-packages/odoo/addons/hr_holidays/models/hr_leave.py"
176:    number_of_days = fields.Float(...)      # 只是个字段
244:        'CHECK ( number_of_days >= 0 )',    # 只是个约束
```
`number_of_days` **不参与任何审批路由决策**——全模块搜不到「按天数选审批人」的分支。

**转交 / 加签 / 代理？—— 不存在**（已核实，强否定）：
```
$ docker exec edu19-clone-web-1 sh -c "grep -rniE 'delegat|substitut|transfer' /usr/lib/python3/dist-packages/odoo/addons/hr_holidays/models/"
（0 行命中）
```
`hr_holidays` 里**没有任何"把审批权交给别人"的机制**（既没有 delegate，也没有 transfer，也没有 substitute）。

### 2.3 为什么**不能**复用 `hr.leave`（本项目的具体理由）

| 理由 | 一手依据 |
|---|---|
| 生产**没装** `hr_holidays` | 生产库 `ir_module_module`：`hr`=installed、`hr_attendance`=installed、**`hr_holidays`=uninstalled**、`hr_work_entry`/`hr_work_entry_holidays`=uninstalled |
| 它是"员工"语义：`hr.leave` 的 `employee_id` 是必填主干，审批人解析全挂在 `hr.employee` 上 | `hr_leave.py:1500-1514` |
| 本仓学生不是员工：`op.student` 29 条 vs `hr_employee` **2 条** | 生产只读查询 |
| 它的两级**不可按天数切换**（只有 `both` 才有第二级） | §2.2 第 3 条 |
| 它**没有**转交，需求 (c) 必须自研 | §2.2 强否定 |
| 真装它 = 拉进 `hr` 全套后台菜单树，与 2026-09-17 的菜单收口（backoffice 可见根 = 12，压线）直接冲突 | `docs/code-map.md` §4.1 |

---

## 3. OCA —— 有没有现成的多级/条件审批？（已核实：**19.0 没有**）

### 3.1 `OCA/hr-holidays` @ 19.0：**只有 4 个模块，全与审批无关**

`GET https://api.github.com/repos/OCA/hr-holidays/contents/?ref=19.0` 返回目录：
`hr_holidays_leave_report_calendar_type`、`hr_holidays_natural_period`、`hr_holidays_public`、`hr_holidays_settings`（其余为 `.github`/`setup`）。

逐个读 `__manifest__.py`（`https://raw.githubusercontent.com/OCA/hr-holidays/19.0/<模块>/__manifest__.py`）：

| 模块 | summary | license |
|---|---|---|
| `hr_holidays_leave_report_calendar_type` | Adds leave type filter to Time Off Overview calendar | **AGPL-3** |
| `hr_holidays_natural_period` | Apply **natural days** in holidays | **AGPL-3** |
| `hr_holidays_public` | Manage Public Holidays | **AGPL-3** |
| `hr_holidays_settings` | Enables Settings Form for HR Holidays | **AGPL-3** |

**四个全 AGPL-3（传染），且没有一个是多级/条件审批。**
> 唯一沾边的是 `hr_holidays_natural_period`（自然日），**但它只是把"工作日"改成"自然日"**，与"按天数分级审批"是两回事——不过它反过来印证了：**Odoo 默认按工作日算假**，这对我们「自然日、含头含尾」的口径是个必须显式声明的差异（见设计稿 §3.4）。

### 3.2 `OCA/server-ux`：审批引擎的"标准答案"在 18.0，**19.0 还没搬过来**（关键）

| 分支 | 目录数 | 有没有 tier validation 族 |
|---|---|---|
| **19.0** | 19 | ❌ **没有**（目录：`barcode_action, base_cancel_confirm, base_export_manager, base_menu_visibility_restriction, base_optional_quick_create, base_revision, base_search_custom_field_filter, base_substate, base_technical_features, date_range, date_range_account, developer_menu, document_quick_access, filter_multi_user, mail_message_destiny_link_template, sequence_reset_period, server_action_mass_edit` + `.github/setup`） |
| **18.0** | 38 | ✅ 有 `base_tier_validation`、`base_tier_validation_confirm_auth`、`base_tier_validation_correction`、`base_tier_validation_formula`、**`base_tier_validation_forward`**、`base_tier_validation_server_action` |

来源：`https://api.github.com/repos/OCA/server-ux/contents/?ref=19.0` 与 `...?ref=18.0`。

**OCA 组织级检索**：`https://api.github.com/search/repositories?q=org:OCA+approval` → `{"total_count": 0}`（**整个 OCA 组织没有一个仓库名含 "approval"**）。

### 3.3 但 18.0 的 tier validation **值得抄形状**（不是抄代码）

读 `https://raw.githubusercontent.com/OCA/server-ux/18.0/base_tier_validation/README.rst`：
> "With this module you will be able to define your custom validation workflows for any Odoo document. … an abstract model to implement a validation process **based on tiers**."

读 `https://raw.githubusercontent.com/OCA/server-ux/18.0/base_tier_validation_forward/README.rst`（maturity **Alpha**）：
> "To allow **Forward** the tier to different user. … A user is appointed to approve a tier, but he/she don't want to make decision for some reason, and want to **pass/forward the decision to another person**. User can then click on **Forward** instead of Approve. A new tier with minor sequence will be created on the reviewer table, and new user will be able to make approval decision."

读 `https://raw.githubusercontent.com/OCA/server-ux/18.0/base_tier_validation_formula/README.rst`：
> "This module includes the ability to define the **tier definition domain** … using python code."（= 用 domain/py 表达式决定"这张单该走哪些审批层级"）

**这两条对本次设计的价值**（设计稿 §4 的取舍依据）：
1. **「层级」= 数据行（tier definition），不是代码分支** → 印证我们应把「3 天阈值」做成可配参数，而不是硬编码 if。
2. **「转交」= 在 reviewer 表里插一条新行（minor sequence）**，原审批人被替换掉 → 与钉钉「转交后该审批单从"待处理"转移到"已处理的"」（原审批人待办消失）**语义一致**。两条独立来源互相印证，可作转交设计的形状依据。

> ⚠ 但 **19.0 装不了**（分支不存在），且全 AGPL-3（本仓红线）。所以**只抄形状，不装代码**。

---

## 4. 同类系统：钉钉 / 飞书 / 企业微信

### 4.1 钉钉 OA 审批（✅ 官方一手，全部可复现）

来源：`https://help.dingtalk.io`（钉钉官方帮助中心，静态 markdown；把文档 URL 加 `.md` 得纯文本）。

#### (a) 条件分支 = 按天数走不同审批人 —— **官方给的例子就是本需求**

`https://help.dingtalk.io/zh/approval/set-conditional-approval.md` 原文：
> "**当发起审批时，选择不同条件，审批节点不同时，需要使用分条件审批（请假 3 天以内主管审批，3 天以上需要主管和分管领导审批）**"
> "条件分支不是传统意义的节点，是用来进行复杂条件下的流程分流 … 同一层级的条件分支，按照**从左到右优先级运行**，只要有一个分支规则执行通过，其他分支则不再继续尝试，**有且最多有一个条件分支会被最终通过**"

#### (b) 条件分支控件：**「日期区间」按"时长"判断** —— 我们的"3 天"就是这个控件

`https://help.dingtalk.io/zh/approval/conditional-branch-controls.md` 原文：
> "支持设置为审批条件的控件有 **数字输入框、单选框、多选框、金额、计算公式、部门、日期区间**…"
> "**日期区间**作为条件时，以开始时间和结束时间之间自动计算的"**时长**"进行判断，支持**小于、小于等于、等于、大于等于、大于、介于**（两个数之间）。典型场景：**请假时长小于 12 小时走主管审批，超过则增加分管领导审批**。"
> "所有控件须**设置为必填**才可设为条件。"

⇒ **三条可直接照抄的设计约束**：① 阈值比较必须支持「≤ / >」两档（对应"≤3 天 / >3 天"）；② 参与比较的量必须由起止时间**自动算出**，不能让人手填；③ 用于分流的字段必须**必填**（否则分支会落空——钉钉专门有排错文档 `conditional-troubleshooting.md` 讲"当前条件没有设置审批人"）。

#### (c) 流程节点与审批人动作集

`https://help.dingtalk.io/zh/approval/admin-process-design.md`（节点类型表）：
> 发起人 / **审批人**（同意、拒绝、**转交**、回退、**加签**）/ 抄送人 / 办理人（提交、**转交**、回退、**加签**、评论）/ **条件分支** / 并行分支（付费）/ 连接器（付费）/ 自动化（付费）

`https://help.dingtalk.io/zh/approval/operator-guide.md`（动作定义，**逐字**）：
> **转交**：「当审批人岗位调整，但流程还未调整时，审批人可手动操作转交；点击转交后，可以从通讯录中选择组织内成员转交当前审批节点；**转交后，该审批单从"待处理"转移到"已处理的"**」
> **加签**：「当需要临时增加审批人时，审批人可手动操作加签；点击加签后，可以选择**前加签或后加签**；前加签：加签到当前审批人之前，当前审批单从"待处理"转移到"已处理的"；后加签：加签到当前审批人之后，当前审批单不转移，待审批完成后，自动流转给被加签人」
> **回退**：「当需要之前的审批人或发起人补充信息时…可以选择回退到哪个节点；回退的节点审批人或发起人审批完成后，需要**重新逐级审批**」

#### (d) 代理（= 本仓既有 `edu.approval.delegate` 的原型）

`https://help.dingtalk.io/zh/approval/admin-agent-settings.md`：
> "管理员可以在管理后台操作代理设置；包括：**被代理人、代理人和代理时间**"；「进入'审批管理后台'- 系统管理 - **代理设置**」

`https://help.dingtalk.io/zh/approval/operator-guide.md` §3：
> "可以设置代理人、**代理时间**、以及代理的审批单，**可以针对不同的审批类型设置不同的代理人**"；"提交成功后，跳转进入【**代理记录**】，如果临时改变休假计划，也可以**点击撤销**"

#### (e) 四个概念在钉钉里的**定义与差异**（回答调研问题 3）

| 概念 | 钉钉定义 | 生命周期 | 留痕 |
|---|---|---|---|
| **条件分支** | 流程设计期的**静态分流**：按表单字段（含日期区间算出的"时长"）决定"这张单走哪些节点" | 模板级配置，改一次影响所有后续单 | 流程设计器里可见；单例外不额外留痕 |
| **转交** | 审批**运行期**动作：把**当前这一个节点**交给别人；原审批人的待办**消失** | 单笔、永久（对该单该节点） | 落入"我处理的"，可从审批单操作记录查 |
| **加签** | 审批**运行期**动作：**临时加人**，可选前加签/后加签；不改变原审批人 | 单笔 | 同上 |
| **代理** | 一个**带时间窗的事前授权**（被代理人/代理人/代理时间），可针对不同审批类型设不同代理人，可撤销；期间代理人**代**原审批人批 | 时间窗，**可撤销** | 有独立的「**代理记录**」页，可按被代理人/代理人查询 |

**一句话差异**：**条件分支是"流程设计"（谁该批），转交/加签是"运行期动作"（临时改谁批），代理是"带期限的长期授权"（一段时间内自动顶班）。**

### 4.2 飞书 / 企业微信 —— ⚠ **未验证**（原因见下，不得当结论用）

| 平台 | 尝试过的一手 URL | 结果 |
|---|---|---|
| 飞书开放平台 | `https://open.feishu.cn/document/server-docs/approval-v4/approval-overview` | HTTP 200，返回 7 KB **SPA 外壳**（`<title>审批概述 - 服务端 API - 飞书开放平台</title>`），正文由 JS 渲染，取不到 |
| 飞书开放平台（旧版路径） | `.../document/uAjLw4CM/ukTMukTMukTM/reference/approval-v4/approval-overview` | 同上（外壳，标题正确） |
| 飞书开放平台文档 API | `https://open.feishu.cn/document_portal/v1/document/get_detail?fullPath=<5 个候选路径>` | 5 个全部 `{"code":41404,"msg":"文档不存在"}` —— **端点存在但参数契约未攻破** |
| 飞书帮助中心 | `https://www.feishu.cn/hc/zh-CN/search?query=转交审批`；`/hc/sitemap.xml`；`/llms.txt` | 搜索页 SPA（HTML 里搜不到"转交"）；sitemap 404；llms.txt 404 |
| 飞书帮助中心（抽样） | `https://www.feishu.cn/hc/zh-CN/articles/025577990143`、`/489007294725`、`/980591272592` | 能取到 `<meta name="description">` 里的**正文摘要**（证明这是可抓的路线），但**这三篇是"我的常用/工作台/日历视图"，与审批无关**——本仓旧调研 `docs/plans/ux-research-dingtalk.md` 引用它们时的语境是"工作台视觉"，**不能**用作"飞书审批转交"的证据 |
| 企业微信开发者中心 | `https://developer.work.weixin.qq.com/document/path/91816`（批量获取审批单号）、`/90269`、`/91814`、`/91817` | HTTP 200，但 4 个 URL 的响应**都恰好 100 000 字节**（被内联 CSS 吃满，正文在截断点之后）；在 HTML 里搜「转交/加签/会签/或签/条件分支/审批人」**全部 -1** |
| 企业微信帮助中心 | `https://open.work.weixin.qq.com/help2/pc/16828` | 拿到的是英文页 "How to sort apps"（本仓旧调研引用此 URL 的语境与本次不同） |
| 兜底检索 | `web_search` 工具（4 次失败）；`cn.bing.com`；`search.brave.com`（fetch failed）；`ecosia.org`（跨域跳 bing） | **均未产出可用的官方一手页** |

**未验证原因归类**（`docs/research/README.md` §3 要求）：**站点 JS 渲染 + 响应体被静态资源吃满导致正文不可达 + 检索工具故障**。三因叠加，**不是"查了没有"，是"抓不到"**。
⇒ 因此本设计的**同类系统依据全部来自钉钉**；飞书/企微**不能**声称"没有这些功能"，也**不能**引用为证据。

---

## 5. 现有实现盘点（读代码 + 读生产库）

### 5.1 代码侧（全部已核实，带行号）

| # | 位置 | 事实 |
|---|---|---|
| 1 | `custom_addons/edu_portal/models/leave.py:46-204` | 模型 `edu.leave`（`_description = 'Student Time Off / Leave Request'`）。状态机**只有三态**：`request` / `approved` / `refused`（`:61-65`） |
| 2 | 同上 `:51-93` | 字段：`name / student_id / leave_type / date_from / date_to / state / reason / reject_reason / active / escalated_at` + 课代表四件套 `subject_id / approver_id / approver_kind / approved_at`。**`student_id` 是唯一申请人主体；无用户字段、无附件字段、无天数字段** |
| 3 | 同 `:53-58` | `leave_type` = `sick / legal / casual / other`（与条例的"寒暑假/婚丧假/病假/事假/实践周"**对不上**） |
| 4 | 同 `:86-92` | `approver_kind` = `student_rep / faculty / registrar / admin` |
| 5 | 同 `:17-23` | `escalate_hours(env)`：系统参数 `edu_portal.approval_escalate_hours`，默认 **48 小时** |
| 6 | 同 `:182-204` | `_cron_escalate_pending()`：超时只**提醒教务处+系统组**，`escalated_at` 幂等去重；**不改状态、不升级审批人** |
| 7 | 同 `:207-253` | `edu.approval.delegate`：`delegator_id / delegate_id / date_from / date_to / note / active` + `_active_domain()` / `is_delegate_of()` / `delegators_of()`。**事前代理，带时间窗** |
| 8 | `models/course_rep.py:614-705` | `EduLeaveRepExt`（`_inherit='edu.leave'`）：`approver_kind_of()` / `_approver_vals()` / `rep_queue_domain()` / `rep_can_handle()` / `rep_set_state()`。**审批写入口之一** |
| 9 | 同 `:117-126` | `edu_portal.course_rep_leave_types` 默认 `('sick','casual')` —— ⚠ **改 leave_type 枚举会静默打掉课代表的处置范围**（见设计稿 §7.6） |
| 10 | `models/__init__.py:3-7` | 导入顺序硬约束：`leave.py` **必须**先于 `course_rep.py`（`_inherit` 引用）。门禁 `scripts/check_view_xpath.py` 规则 7 |
| 11 | `controllers/roles.py:1067-1147` | 门户审批两条写路由：**列表** `/leave/approvals`（`:1067`）、**单条写** `/leave/set_state`（`:1110`）。守卫 = `current_faculty() or privileged_staff()`（`:1069-1071`） |
| 12 | `controllers/roles.py:2002-2055` | **批量写** `/leave/set_state_bulk`。→ 加上模型层 `action_approve/action_reject`、课代表 `rep_set_state`，**审批写入口共 4 处** |
| 13 | `models/leave.py:150-177` | 后台按钮 `action_approve / action_reject`（注释明确写"既有后台按钮也必须补写"留痕） |
| 14 | `controllers/roles.py:819-835`、`:2716-2750` | `approval_scope_domain(env)` / `scoped_record` / `scoped_records`：**列表与可处置范围同一域**（"看得见的 = 能处置的"） |
| 15 | `controllers/roles.py:247-254` | `privileged_staff()` = 教务处组 **或** 系统组 |
| 16 | `controllers/roles.py:284-301` | `current_student() / current_faculty()` —— 反查口径唯一实现在 `edu_schedule/models/identity.py`（code-map §6 第 13 条） |
| 17 | `controllers/roles.py:1025-1065` | **家长代请假**入口 `/my/child/<id>/leave/save`（第 5 个建单入口） |
| 18 | `views/roles.xml:1993+` | cron `ir_cron_edu_leave_escalate`；`:538-730` 门户审批列表/详情模板；`:499` 家长请假表单 |

**⚠ 本仓没有「班主任」字段 —— 源码里自己写着**（已核实）：
`custom_addons/edu_portal/models/registration.py:365-366`
```
def _ccr_faculty_users(self, batch):
    """某班任课教师账号（本仓无「班主任」字段，取课节 faculty 去重）。
```
全仓在 `custom_addons/` 搜 `班主任|homeroom|head_teacher|class_teacher|tutor|陪伴老师|班级导师` 只有 **2 处命中，且都不是字段**：`registration.py:366`（上面这句注释）、`class_batch.py:280`（一句注释文案）。

**现成的"班级→教师账号"解析只有一处可抄**：`registration.py:378-387` `_ccr_faculty_users(batch)` —— 取本班全部 `op.session` 的 `faculty_id` 去重，再按 **双向并集**（① `op.faculty.user_id`（委托字段） ∪ ② `res.users.partner_id ∈ faculties.partner_id`）解析出账号；注释里写明"只写②会 0 收件人"。**这条并集口径是本次设计的必抄项。**

### 5.2 生产库存量（只读实测，2026-09-25）

| 对象 | 实测 | 说明 |
|---|---|---|
| `edu_leave` 行数 | **2** | 全部 `state='refused'` |
| ├ id=26 | `name='001'`, student 11, sick, 2026-09-09~09-09, refused, reject_reason「下午有课」, `escalated_at` 非空, **approver_id/approver_kind/approved_at 全空** | 留痕字段是**后加**的，历史单为空 |
| └ id=27 | `name='SLR000001'`, student 51, sick, 2026-09-25~09-26, refused, reject_reason「学生本人于学生档案页撤回该申请。」 | **撤回 = 写 refused + 原因**（不是独立状态） |
| `edu_leave` 列 | 19 列，含 `subject_id / approver_id / approver_kind / approved_at / escalated_at`；**无 employee_id** | 与源码一致 |
| `ir_sequence` | `code='edu.leave'`, `prefix='LV'`, padding 6 | ⚠ 但 id=27 的单号是 `SLR000001` ⇒ 存在**第二条建单路径**（见 §6 U4） |
| `edu_approval_delegate` 行数 | **0** | 事前代理功能**已上线但从未使用** |
| `op_faculty` 行数 | **1**，其中 `active=true` 的 **0** | 唯一一行：id=20, `first_name={en_US:"Humanities",zh_CN:"人文"}`, `last_name="教师"`, `emp_id` 空, `active=false`；`partner_id=65`（名称"待定"）↔ `res_users` id=33 `teacher@local`（**share=true，门户账号**） |
| `op_student` 行数 | **29** | |
| `hr_employee` 行数 | **2** | `hr` 模块已装 |
| `hr_holidays` / `hr_work_entry` / `hr_work_entry_holidays` | **uninstalled** | `hr`、`hr_attendance` = installed |
| 群组 `openeducat_core.group_op_back_office_admin` (id 40) | **3 人**：`backoffice@local`(12, 教务专员)、`jiaowu@local`(18, 教务二号)、`admin`(2) | |
| 群组 `openeducat_core.group_op_faculty` (id 39) | **1 人**：`admin`(2) | 与 `op.faculty` 无关；`teacher@local` **不在**此组 |
| 群组 `base.group_system` (id 4) | 2 人：`系统`(1)、`admin`(2) | |
| **「教务长」实体** | **不存在** | `res_groups` 88 行全表 + `ir_model_data` 对角，**没有任何名为"教务长"的组或用户** |
| `op_session` | **216 行，`faculty_id` 只有 1 个不同值（=20）** | ⇒ 现行"任课老师"口径下，**全校所有课的任课老师都是同一个 inactive 档案** |
| `op_batch` | 12 行；列 = `id/course_id/code/name/start_date/end_date/active/create_uid/write_uid/create_date/write_date` —— **无任何教师字段** | ⇒ 「班主任」需新增字段 |
| `op_academic_term` | 2 行：第一学期 2026-06-23~2026-12-20、第二学期 2026-12-21~2027-06-18 | ⇒ **事假学期配额可算** |
| `edu_schedule_holiday` | 表存在 | 语义 = **停课日**（code-map §4），**不是法定节假日字典** ⇒ 本仓**无**"法定节假日"表（§6 U6） |
| `op_leave_request` | 表存在、**0 行、`ir_model` 里没有对应模型**（`select count(*) from ir_model where model='op.leave.request'` = 0） | **孤儿死表**（列形似早期版本的请假单：student_id/leave_type/state/date_from/date_to/reason） |
| `edu_course_rep` | **0 行** | 课代表审批链已上线、未使用 |
| 未设值的系统参数 | `ir_config_parameter` 里 `edu_portal.*` **0 行** | ⇒ 超时升级 = 默认 48h；课代表白名单 = 默认 sick,casual |
| cron id=39 | `edu_portal: 请假审批超时升级提醒`，model `edu.leave`，active，每 6 小时 | |
| `edu_leave` ACL | 5 条：`base.group_portal`(只读) / `base.group_user`(全) / 教务处组(全) / `base.group_system`(全) + 1 | `edu.approval.delegate` 3 条、`edu.course.rep` 2 条 |
| 菜单 | 497「教务审批」(根) → **498「请假审批」** | |
| 视图 | `view_edu_leave_list` / `view_edu_leave_form`（后台）、`edu_leave_approvals` / `edu_leave_detail` / `edu_child_leave`（QWeb） | |
| `edu_audit_log` | 已有「请假审批」×1、「请假批量审批」×7 两条动作名 | 转交要加**新的独立动作名**（不改既有两个） |

### 5.3 条例原文核对（一手材料，非网页）

用户提供 `员工请假条例.pdf`。实测（`pdftotext -layout`）：

| 项 | 实测 |
|---|---|
| 文件 | 3 页 A4，MD5 `71afe09739208685ed8f6f0d7c10cb06`，Producer = macOS Quartz PDFContext，CreationDate 2026-08-31 |
| **PDF 内标题** | **《请假条例》（2025.9 初版）** —— **不是**文件名里的"员工请假条例" |
| **正文主体** | **通篇是学生条例**：开篇"本条例旨在**引导学生**合理安排个人时间…"、"**学生**应按学校规定时间返校…"、"**学生**须提前 1–2 周提交请假申请…" |
| **涉及教职员工的条款** | **0 条**（正文 96 行里「员工」只出现在文件名；只有「班级导师/陪伴老师」「教务助理或教务处」「教务处」「学院主管」这些**审批方**角色，没有一条讲教职员工本人怎么请假） |
| 三·1 提交申请 | 「由**班级导师/陪伴老师**签字，再报**教务助理或教务处**审批」 |
| 三·2 审批要求 | 「普通假期由**班级导师**审批；**跨一日以上假期**须由**教务处或学院主管**审批」 |
| 三·3 销假与反馈 | 「学生返校后须**及时销假**，向导师报告行程及实践收获」；「导师可视情况安排学生分享心得」 |
| 二·2 婚丧假 | 限直系亲属及近亲；**2–5 天**；须**提前 1–2 周**；附证明（喜帖、讣告），**无文本证明可请家长/牧长口头证明** |
| 二·3 病假 | 半天至一天；**连续两天及以上必须出示正规医院诊断证明** |
| 二·4 事假 | **提前至少两天**书面申请；**每学期不超过 5 天**，特殊情况需**报教务处批准** |
| 二·5 实践周 | 「法定节假日如遇实践周，**并非假期，不调休不拼假**」；「原则上**不批准外出长假**」 |
| 一·2 原则 | 「以诚实为本，**严禁虚假请假或事后补假**」 |
| 四·1 违规 | 无故缺席、**不销假**、虚假请假 → 记录在**综合评估档案** |
| 五·1 附则 | 「本条例自发布之日起实施，由**教务处**负责解释与修订」 |

**结论**：
1. **文件名与正文主体不一致**：名为"员工请假条例"，正文是**学生条例**，且**完全没有教职员工请假条款**。
2. **PDF 三·2 与用户口述冲突**：PDF 写「跨一日以上假期须由教务处或学院主管审批」（阈值 ≈ 1 天）；用户口述「≤3 天班主任、>3 天教务」。**两条并列记录；已由用户裁决以 3 天为准**（见设计稿 §1）。

---

## 6. 未验证 / 待确认清单（不得当结论用）

| # | 项 | 状态 | 原因 / 下一步 |
|---|---|---|---|
| U1 | 飞书审批的「转交 / 加签 / 条件分支 / 代理」官方定义 | **未验证** | 见 §4.2：开放平台与帮助中心均 SPA + 响应体被静态资源吃满；`web_search` 工具故障。需要可渲染浏览器（或修复检索工具）才能取证 |
| U2 | 企业微信审批的「转交 / 加签 / 条件分支 / 代理」官方定义 | **未验证** | 同上；`developer.work.weixin.qq.com` 若干路径响应恰好 100 KB 全为 CSS，正文不可达 |
| U3 | Odoo **企业版**是否有 Approvals 应用、它有无条件分支 | **未验证** | 企业版模块不进 `apps.odoo.com`（`/apps/modules/19.0/approvals` = 404），17/18/19 三版官方文档目录树均无该条目；**不能据此断言不存在**。本项目不依赖此结论（社区版装不到） |
| U4 | `edu_leave` 单号 `SLR000001` 的产生路径 | **未验证** | 生产只有 `prefix='LV'` 的序列；本次只读范围内未找到 `SLR` 前缀来源。**数据迁移按"不动单号"处理**即可绕开 |
| U5 | `hr_employee` 那 2 条是谁 | **未验证** | 首次查询因 `job_title` 列不存在失败，未获得行内容。**与本设计无关**（已排除复用 `hr.leave`） |
| U6 | 「法定节假日」字典 | **本仓不存在**（已核实） | `edu_schedule_holiday` 是**停课日**不是节假日；条例"不调休不拼假"因此**无法按节假日表机器化**，只能做文案 + 负向断言（设计稿 §7.4） |
| U7 | 生产上「教务长」的实际归属 | **已核实为"实体不存在"；映射按用户口述** | `res_groups` 全表无"教务长"组/用户；用户已口述"就是 `backoffice@local`"（= `res_users` id 12「教务专员」，教务处组 3 人之一）。设计稿按**教务处组**实现，不写死账号 |

---

## 7. 落盘结论：可复用 / 必须自研

| 能力 | 结论 | 依据 |
|---|---|---|
| 单据类型拆分 | **必须自研**（在既有 `edu.leave` 上加维度） | Odoo 核心无"学生/教职"二分的请假实体；`hr.leave` 是员工专用且生产未装（§2.3） |
| 按天数分级审批 | **必须自研** | `hr_holidays` 的级别在**类型**上而非**单**上、且固定两级（§2.2）；OCA 19.0 空（§3.1/3.2） |
| 转交审批 | **必须自研**；**形状抄钉钉 + OCA tier forward** | `hr_holidays` 零命中（§2.2）；OCA `base_tier_validation_forward` 只在 18.0 且 AGPL-3（§3.3） |
| 代理设置 | **本仓已有** `edu.approval.delegate`，形状已与钉钉一致 | 钉钉官方复验为真（§4.1(d)）；本仓 0 行未使用 |
| 「班级→教师账号」解析 | **抄本仓自己的 `_ccr_faculty_users` 双向并集** | `registration.py:365-387`；注释已记录"只写②会 0 收件人"的实测 |
| 「超时升级」 | **本仓已有**（48h 提醒） | `leave.py:17-23, 182-204`；**但它只提醒、不升级审批人**，与新需求的"分级"是两件事，别混用 |
| 「学期」边界 | **本仓已有** `op.academic.term`（2 行） | 生产实测；事假配额可直接用 |
| 附件 | **本仓模式**：`ir.attachment`（`res_model/res_id`）或 `fields.Binary` | 无一手外部来源，按 Odoo 惯例 ⇒ 标注为本仓自定 |
