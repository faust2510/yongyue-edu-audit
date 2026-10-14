# 改课影响面与变更通知设计（C-1）
> **状态**：`已上线` ｜ **主题**：`改课影响面与变更通知` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「仅设计」，实际已于 `5da2270` 交付（2026-09-26 核对发现）。正文未改动。

> **历史状态**：仅设计（第 0 步「落地前查重」+ 第 3 步「读参考」+ 第 4 步「设计摘要」）。
> **本文件不代表已实施**——本次**未写一行代码**、**未新建模块**、**未动 `openeducat_erp/`**、**未动 `custom_addons/`**。
> **功能一句话**：教务改动一节课时，系统先告诉他「这会惊动谁」，改完能一键把变更通知到人，并留下变更痕迹。
> **口径来源**：`docs/dev-workflow.md` 第 0 步与六步闸门 ｜ `docs/research/scheduling-approaches.md` §6/§9 ｜ `docs/audit/feature-overlap-audit.md`
> **采集时刻**：**2026-09-17**；读数口径 = 本地库 `edu19`（只读 SELECT）+ 容器 `edu19-clone-web-1`。
> **未验证项**一律集中写在 §11，**不得当结论用**（本仓规范）。

---

## 0. 结论速览（TL;DR）

| 项 | 结论 |
|---|---|
| **裁定（三选一）** | **复用 + 模块内扩展**。通知复用 `edu.message`；留痕复用 `mail.thread` + `edu.audit.log`；影响面属**无先例**，在**既有模块 `edu_schedule` 内**新增一条只读计算方法与两条门户路由。**不新建模块、不新建模型、不新建表、不新增字段。** |
| **落地模块** | `custom_addons/edu_schedule`（既有，manifest 19.0.2.1.0，本地已装） |
| **零新数据** | 影响面 100% 由 `op.session` + `op.student.course` + 四查口径**运行时算出**；留痕走基座已有的 chatter（`mail.thread`，9 个字段 `tracking=True` 已在库内生效）；通知落 `edu_message`（既有表） |
| **头号重复对象** | `custom_addons/edu_telegram/models/hooks.py:5-35` —— **本仓已存在一个「课表变更推送」**（`op.session.write` 覆盖 + Telegram 出队）。该模块**本地仍是 installed**（实查 `ir_module_module`），但 **2026-09-17 用户已裁定退役**。C-1 **不复用它**，并须在弃用台账登记（§12） |
| **红线** | `edu.telegram.outbox` 与**生产上的匿名意见箱同名同表**（`docs/audit/deprecated-inventory.md` §0.1）⇒ C-1 **绝不**使用该出口 |
| **待校长拍板** | **4 项**（命名 / 通知渠道与收件人口径 / 留痕对学生是否可见 / 停课是否同套通知），见 §10 |

---

## 1. 目标 / 非目标

### 1.1 目标（本设计只覆盖 C-1）

| # | 能力 | 用户感受 |
|---|---|---|
| G1 | **改前影响面**：打开一节课，先看到「这会惊动谁」（受影响的人 × 受牵连的其他课节 × 撞在哪些维度） | 「一改课就牵一发动全身」变成「先看见动的是哪几根线」 |
| G2 | **改后一键通知**：改完点一次，把变更推给该知道的人 | 不用再人肉挨个通知 |
| G3 | **变更留痕**：谁在什么时候把这节课的哪个字段从什么改成什么 | 出事能追、家长问能答 |

### 1.2 非目标（明确不做，避免范围漂移）

- **不做候选方案建议**（那是 **C-2**，依赖 **F-1** 的「教师例外不可用」数据）。
- **不做教师不可用时间自助录入**（**F-1**，复用 Odoo 核心 `resource` 模块；本次仅在 §8.1 备注）。
- **不做算法**：不算最优时段、不排班、不求解。影响面 =「按既有四查口径枚举受影响对象」，不是搜索。
- **不合并基座向导**：`openeducat_timetable/wizard/generate_timetable.py`（`generate.time.table`）**保留**；
  门户 `/timetable/bulk` 后续向它合并 —— **本次只记待办，一行**：
  > **待办（不在本设计范围）**：`generate.time.table`（基座官方七日网格向导）与门户 `/timetable/bulk`（`edu_schedule/controllers/main.py:405`）功能重叠，合并方向与时机**待另立任务**；本次**不动基座、不动 `/timetable/bulk`**。
- **不动 `openeducat_erp/`**（只读快照，且被 `.gitignore:11` 忽略、不纳入提交）。

---

## 2. 第 0 步①：先信 code-map

`docs/code-map.md` 逐条读后与本设计相关的锚点：

| 位置 | 内容 | 对本设计的含义 |
|---|---|---|
| `docs/code-map.md:103-104` | `edu_schedule` =「排课工具（自研）」：`/timetable/bulk`→`/preview`→`/create`；`EduScheduleHoliday`；`OpSessionConflictExt` 冲突检测视图；菜单仅教务处组可见 | C-1 的落点模块；**既有冲突分色**就是影响面的近亲 |
| `docs/code-map.md:223` | 排课路由：`/timetable/bulk*`（`edu_schedule/main.py`）、`/student/timetable`（`edu_portal/scheduling.py`） | 新增路由必须挂 `/timetable/` 前缀族，不另开命名空间 |
| `docs/code-map.md:271-272` | 门禁脚本清单；`audit_completeness_smoke.py`（留痕断言） | 验收复用既有工具，不自造 |
| `docs/code-map.md:256-263` | **权限四层**硬约定（教务组写 `groups="openeducat_core.group_op_back_office_admin,base.group_system"` 并列） | 新增菜单/ACL 必须声明层级 |
| `docs/code-map.md:249` | 「新功能三件套：models/controllers/views 各一文件，先写 `docs/plans/<功能>-design.md` 再动工」 | 本文件就是那个前置件 |

---

## 3. 第 0 步②：既有实现对照（逐条：查了什么 / 用什么命令 / 命中什么 / 为什么不复用）

> 规矩：**「没找到」也要写清搜索范围与方式**；**不允许"我记得没有"**。
> 本节所有命令均**在本工作区实跑**（2026-09-17），命中行号取自实跑输出；DB 读数只读 `SELECT`。

### 3.1 模型名 / 路由名 / 菜单名查重（候选名先查空，再动设计）

| # | 查了什么 | 命令 | 命中 | 结论 |
|---|---|---|---|---|
| 1 | 候选模型前缀 `edu.session*`（拟用作「变更记录」模型） | `grep -rn "edu\.session[a-z_.]*\|EduSession" --include="*.py" custom_addons/` | **0 命中** | 名字可用；但**本设计决定不新建该模型**（见 §3.2 #7/#9） |
| 2 | 候选路由 `/timetable/*` 族 | `grep -rn "/timetable/\|timetable/" --include="*.py" custom_addons/` | **11 命中**，去重后**只有 3 条真路由**：`/timetable/bulk`（`edu_schedule/controllers/main.py:405`）、`/timetable/bulk/preview`（:415）、`/timetable/bulk/create`（:438）；其余为注释/卡片图标映射（`batch2.py:791,819,1819-1820`） | `/timetable/session/<id>/*` **未被占用**，可新增；不与任何既有 leaf 撞 |
| 3 | 同名功能入口「调课/代课/改课/换课」 | `grep -rn "调课\|代课\|改课\|换课\|substitut" --include="*.py" custom_addons/` 与 `--include="*.xml"` | `.py` **5 命中**全部是**学生换课单**（`edu_portal/models/registration.py:27,46,95`；`controllers/enroll.py:280,336`，`course_change` 类型）；`.xml` **0 命中** | **教务侧「改一节课」没有既有功能**；学生换课是另一条业务线，**不重叠** |
| 4 | 后台菜单落点 | 读 `edu_schedule/views/menu.xml` 全文 + `grep -rn "op.session" --include="*.xml" custom_addons/` | `edu_schedule/views/menu.xml:11-22`：两条菜单挂在 `openeducat_timetable.menu_op_timetable_root` 下（周期排课 / 停课管理），组 = `group_op_timetable_manager,group_op_back_office_admin` | **菜单落点已有**；C-1 **不新增根菜单**，只在既有「时间表」应用内挂入口 |
| 5 | 冲突计算有没有第二份实现 | `grep -rn "conflict_kind\|conflict_color\|_overlaps" --include="*.py" --include="*.xml" custom_addons/` | `edu_schedule/models/session_ext.py:51-115`（`conflict_kind`/`conflict_color` + `_compute_conflict`）、`views/session_conflict_view.xml:6-19`（继承官方日历视图，`color=conflict_color`） | **全仓只有一份**冲突分色实现 ⇒ C-1 **必须复用它的口径**，不得另写第二套冲突判定 |
| 6 | 「影响面 / 候选方案 / 受影响的人」有没有先例 | `grep -rn "影响面\|impact\|affected\|候选" --include="*.py" --include="*.xml" custom_addons/`（另见 §3.4） | **0 命中**（活代码） | **无先例** ⇒ 这是 C-1 唯一「新建」的部分 |

### 3.2 通知 / 留痕 / 审计三条通道（复用候选逐条判定）

| # | 通道 | 命令 / 位置（含「命中（行号）」） | 复用裁定 |
|---|---|---|---|
| 7 | **站内信引擎 `edu.message`** | `grep -rn "edu\.message\|EduMessage" --include="*.py" custom_addons/` → **33 命中**；模型定义 `edu_portal/models/message.py:15-66`（`sender_id/recipient_id/body/sent_at/is_read/thread_key`）；**带偏好的统一入口** `edu_portal/models/notify_pref.py:48-79` `_notify_event(event_key, user, body)`；事件白名单 `notify_pref.py:15-22` `NOTIFY_EVENTS` **只有 6 类**（`leave_result/grade_result/assignment_graded/journal_reviewed/subject_reg_result/reimburse_result`）——**没有课表变更类** | ✅ **复用为主通道**。新增事件 key `session_change`；因 `_notify_event` 的**静音开关**只认 `NOTIFY_EVENTS` 里登记过的 key（未登记的 key 仍能发，只是用户**关不掉**），所以要在 `notify_pref.py:15-22` 追加一行 |
| 8 | **关键操作审计 `edu.audit.log`** | `grep -rn "edu\.audit\.log" --include="*.py" custom_addons/` → **37 命中**；模型 `edu_portal/models/audit.py:15-41`（`user_id/action/model/res_id/res_name/detail`，`_log()` **失败只告警、绝不阻断业务事务**）；查询页 `/edu/audit` 在 `edu_portal/controllers/roles.py:1402-1425`，门禁 `privileged_staff()`（`roles.py:150`） | ✅ **复用**：改课入口写 `action='课节变更'`（`detail` 带 old→new 摘要）。**注意**：本表只有 `detail` 一个自由文本列，**没有结构化 old/new** ⇒ 「字段级留痕」不靠它，靠 #9 |
| 9 | **字段级留痕 `mail.thread`** | ① `grep -n "tracking=True" openeducat_erp/openeducat_timetable/models/timetable.py` → `:34,36,39,41,43,46,48,50,56` **9 个字段**；② 库内确认：`select name,tracking from ir_model_fields where model='op.session'` → **9 行 `tracking=100`**（`batch_id/classroom_id/course_id/end_datetime/faculty_id/start_datetime/state/subject_id/timing_id`）；③ 机制源码 `mail/models/mail_thread.py:632 _track_subtype`（**默认返回 False ⇒ 只记录、不通知**）、`:644 _message_track`、`:675-690`（有 subtype 才 `message_post`）、`:702 _message_track_post_template`；值表 `mail/models/mail_tracking_value.py:68 _create_tracking_values`、`:197 _tracking_value_format` | ✅ **复用为零成本**（`openeducat_erp/.../models/timetable.py:29` 已是 `_inherit=["mail.thread"]`）。**但必须复核落地量**：库内 `mail_tracking_value` 全库 **137** 行，其中 `op.session` 只有 **4** 行（2026-08-24 两条消息）⇒ 机制在、**真实改课路径的留痕量未被证明**（§11-3） |
| 10 | **同型先例：成绩变更留痕 `edu.grade.history`** | `grep -rn "变更" --include="*.py" custom_addons/` → `edu_portal/models/registration.py:355-392`（`_name='edu.grade.history'`，字段语义照抄 Moodle `grade_grades_history`：`action/logged_user_id/old_*/new_*/source/timemodified/note`；唯一入口 `edu_apply_marks` 在 `:394`） | ⚠ **不直接复用（对象不同：`op.exam` vs `op.session`）**，但**必须照它的口径**：若将来真要「课节变更留痕」表，字段语义与「唯一入口才留痕」的做法照抄本先例，**不要另创一套** |
| 11 | **邮件通知（基座自带）** | 完整读 `openeducat_erp/openeducat_timetable/models/timetable.py`：`:418-480 notify_user()`（**一封群发**给 followers，模板 `openeducat_timetable.session_details_changes`，`:507-510 _NOTIFY_WORTHY_FIELDS` 8 个字段，`:512-567 write()` → `:547 should_notify` + `:563 state not in ('draft','done')`）；模板定义 `openeducat_timetable/views/timetable_templates.xml:5` | ⚠ **部分复用、不作为主通道**：① 它**只发给 mail followers**，而库内 `op_session_op_student_rel` = **0 行**（`student_ids` 实际为空）⇒ 实测关注者只有教师（`预备科导师【演示】×68`）；② **草稿态不发**（`:563`），而库内 **266/288 是 draft** ⇒ 日常改课**根本不会触发**；③ 它是**自动**的，而 C-1 要的是**人按一下**。⇒ 结论：**保留它不动**（零上游改动），C-1 走 #7 |
| 12 | **重复对象（头号）：`edu_telegram` 的「课表变更推送」** | `grep -rn "edu\.telegram\.outbox\|Outbox" --include="*.py" custom_addons/`（12 命中）+ 逐文件读：`edu_telegram/models/hooks.py:5-35`（`_inherit='op.session'`，`WATCH={start_datetime,end_datetime,classroom_id,subject_id,faculty_id,state}`，`write()` 里 `_tg_notify_change()` → 按 `batch` 找学生、`op.telegram.chat` 找出队目标 → `edu.telegram.outbox.enqueue`）；`edu_telegram/models/__init__.py` **导入了 hooks**；`select name,state from ir_module_module` → `edu_telegram 19.0.2.2` **installed** | ❌ **不复用**（三重理由）：① 出口 `edu.telegram.outbox` **与生产匿名意见箱同名同表**（`deprecated-inventory.md` §0.1 三条后果）＝ **红线**；② 该模块**用户已裁定退役**（`code-map.md:124-128`、台账 B8），C-1 不能把新功能拴在退役件上；③ 它**没有影响面**、**没有门户可见痕迹**（出队即走）。**但其存在本身必须在台账登记**（§12），并在实施时处理「双写」：C-1 落地后 `edu_telegram.hooks` 若仍 installed 会**重复推送**，故 C-1 必须**同时具备一次通知去重口径**（见 §7.4） |

### 3.3 基座与其向导（读参考，不搬代码）

| # | 查了什么 | 位置（**只给路径+行号，不贴源码**） | 为什么不复用 |
|---|---|---|---|
| 13 | `op.session` 字段 / `state` 取值 / 冲突四开关 / 是否 `mail.thread` | `openeducat_erp/openeducat_timetable/models/timetable.py`：`:29 _inherit=["mail.thread"]`；`:53-56 state = **draft / confirm / done / cancel（有 cancel）**；`:243-337 check_timetable_fields`，四个开关读 `ir.config_parameter`：`timetable.is_faculty_constraint` / `is_classroom_constraint` / `is_batch_and_subject_constraint` / `is_batch_constraint`（`:247-254`），比较窗口 ±24h 且 `state != 'cancel'` 不参与冲突（`:270-279`），`sudo()` 搜索以保证跨教师可见（`:289`） | ✅ **复用为口径基准**。C-1 的影响面**逐条对齐这四个开关语义**，不另发明「冲突」定义 |
| 14 | 基座七日网格向导 | `.../wizard/generate_timetable.py:30-133`（`generate.time.table` + `gen.time.table.line`；`act_gen_time_table` 在 `:87`；`:99-101` 预取班级学生、`:132 session_obj.create(data)`）；`.../wizard/session_confirmation.py:24-33`（`session.confirmation.state_confirmation` 批量 draft→confirm） | **保留，不合并**（用户已定口径）。C-1 **不碰它**；合并待办见 §1.2 |
| 15 | 基座是否有「影响面 / 候选人」能力 | 通读上述两文件 + `grep -rn "notify_user" openeducat_erp/openeducat_timetable/`（命中 `models/timetable.py:418,487,566`、`views/timetable_templates.xml:9,498`） | **无**：基座只有「改完自动群发邮件」，**没有**「改前告诉你会惊动谁」 |

### 3.4 「没找到」的，也要写清范围（本节的负结论）

| 负结论 | 搜索范围与方式（原样可复现） |
|---|---|
| **全仓没有「改动某节课 → 影响面清单」的任何实现** | ① `grep -rn "影响面\|impact\|affected\|候选" --include="*.py" --include="*.xml" custom_addons/`；② `grep -rn "调课\|代课\|改课\|换课" custom_addons/ docs/`；③ 通读 `docs/code-map.md` §4 全部 `edu_*` 模块段落与 §5 路由速查；④ 读 `docs/plans/timetable-design.md` 全文（79 行） |
| **全仓没有「课节变更留痕」模型** | `grep -rn "edu\.session[a-z_.]*" --include="*.py" custom_addons/` = 0；`grep -rn "变更留痕" custom_addons/` 只命中 `registration.py:355,358,365`（**成绩**留痕） |
| **全仓只有一份冲突判定（活代码）** | `grep -rn "_overlaps\|conflict_kind" --include="*.py" custom_addons/` → `session_ext.py:84,94,113-114`（唯一）；基座那份在 `openeducat_erp/.../timetable.py:291-307`（**只读快照，不参与 C-1 计算**） |
| **没有额外的「变更通知」出口**（除 `edu.message` / 基座 `notify_user` / `edu.telegram.outbox` 三条） | `grep -rn "telegram\|mail\.thread\|message_post\|send_mail" --include="*.py" custom_addons/` 全量逐条判定；其中 `message_post` 在 `custom_addons/` **0 命中**（只有基座快照用到） |

---

## 4. 第 0 步④：升级会不会动业务数据（manifest 的 data 列表自查）

> 依据 `docs/dev-workflow.md` 第 0 步 ④（`finding-F5`）：`data` 每次 `-u` **重放**，`demo` 只在安装且开启演示数据时装载。
> **命令**：① `grep -rn "<function" custom_addons/*/data/` 与 `data_brand/`；② 逐个解析 12 个 `__manifest__.py` 的 `data`/`demo` 键（`ast.literal_eval`）。

**实跑读数（2026-09-17）**：`<function model=…>` 全仓 **78 命中**，按「是否写业务表」分流：

| 归属 | 命中 | 写的是什么 | 判定 |
|---|---|---|---|
| `edu_life/data/demo_life.xml:35-36` | `edu.checkin.type._load_demo_records` / `_ensure_attend_checkin_type` | **业务表**（`edu.checkin.record`、`edu.checkin.type`） | ⚠ **既有反面实例（F5，t12 修复中）**——与 C-1 无关，但**它证明的规矩对 C-1 有效**：写业务表的种子函数**不得**放 `data/` |
| `edu_brand/data_brand/brand_debrand_data.xml` | `res.company.write`（:44）、`ir.config_parameter.set_param`（:46）、`res.partner.write`（:58/:233）、`digest.digest.write`、`digest.tip.write`、`mail.template.write`（:235-257，多数带 `context="{'lang': …}"`） | **配置/展示类**（公司资料、参数、摘要、邮件模板），非业务记录 | ✅ 可接受（去品牌化需要每次 `-u` 维持） |
| `edu_portal/data/menu_reachability.xml:9` | `ir.ui.menu.edu_apply_reachability_groups` | **菜单权限** | ✅ |
| `edu_brand/views/brand_templates.xml:265` | `website.write` | **网站配置** | ✅ |

**与 C-1 直接相关的结论**：

1. `custom_addons/edu_schedule/__manifest__.py:12-19` 的 `data` = 6 项（`security/ir.model.access.csv`、`data/cron.xml`、`views/templates.xml`、`views/holiday_views.xml`、`views/menu.xml`、`views/session_conflict_view.xml`），**无任何 `<function>`**；`demo` 键 **不存在**（实跑：12 个模块 `data` 均有值、`demo` 一律 `None`）。
2. ⇒ **C-1 若在 `edu_schedule` 内新增 `data/`**，必须满足两条：① **只允许写配置类记录**（`ir.cron`/`ir.actions`/视图/菜单/ACL），**任何写 `op.session`、`edu.message`、`edu.audit.log` 的 `<function>` 一律禁止进 `data/`**；② 若确需一次性回填历史，走 `scripts/migrations/` + `migrations/<版本>/`，**不放 `data/`**。
3. ⇒ **C-1 不新增 `ir.cron`**（影响面是请求时计算、通知是人按按钮，都不需要定时器）⇒ **`data/` 变动预期为零**，`-u edu_schedule` 的业务数据副作用 = 0。

---

## 5. 第 0 步⑤：演示数据策略（一句话）

**C-1 不新增任何演示数据**：功能验证用「真机改一节真实课节 + 改回原值」完成（同型先例：`checkin-merge-report` 的「构造 → 断言 → 还原 leftover=0」三段模板）；
若实施任务确需造样本（例如本地教室为空、造不出教室冲突，见 §11-6），则**放 `scripts/seed_c1_impact_demo.py`**（仓库既有惯例：`scripts/seed_*.py` 必须幂等），
**名称前缀一律【演示】**（`code-map.md:247` 第 5 条硬约定），**清理命令写在同一脚本的 `--clean` 分支**（按前缀 `unlink`，跑完断言计数归零）。
**禁止**放进 `data/`（理由见 §4）。

---
## 6. 三选一裁定 + 理由 + 收口触发条件

### 6.1 裁定（逐能力，必须逐条落地成一个字）

| 能力 | 裁定 | 承载物（替代路径） | 扩展方式 |
|---|---|---|---|
| **G1 改前影响面** | **新建（模块内扩展，非新模块）** | `edu_schedule`（既有模块）内的**只读计算方法** + **GET 路由** `/timetable/session/<id>/impact` + 模板 | 在既有 `OpSessionConflictExt`（`session_ext.py:48`）里扩一个只读方法；**不新增模型** |
| **G2 改后一键通知** | **复用** | `edu.message._notify_event`（`edu_portal/models/notify_pref.py:48`） | 新事件 key `session_change`；在 `NOTIFY_EVENTS`（`notify_pref.py:15-22`）追加一行；新增 POST 路由 `/timetable/session/<id>/notify` |
| **G3 变更留痕** | **复用** | `mail.thread` chatter（9 字段 `tracking=True` **已在库内生效**）+ `edu.audit.log`（`edu_portal/models/audit.py:29`）+ 查询页 `/edu/audit`（`roles.py:1402`） | 不改基座；在改课写入点补一条 `edu.audit.log._log('课节变更', …)`（**现在只有批量排课有**：`edu_schedule/controllers/main.py:475-477`） |
| **重复对象：`edu_telegram` 课表变更推送** | **合并（入口收口，数据不动）** | 替代路径 = 本设计的 `edu.message / session_change` | 台账登记（§12）；**实施期**须处理双写（§7.4 #4） |

### 6.2 理由（一条一句话）

- **为什么影响面只能新建**：全仓 0 先例（§3.4）；而它**不含算法**（枚举既有四查口径下的受影响对象），**不需要新数据**，因此在既有模块里扩一个只读方法是**成本最低且不会制造第二套概念**的形态。
- **为什么不合并基座 `notify_user()`**：它是**自动、只发邮件、只发 followers、草稿态不发**（§3.2 #11），与 C-1「人按一下 → 门户可见的站内留痕」是两种语义；**合并会改上游行为**（本仓原则：基座只读、要改就继承），所以**保留 + 并存**，且**不禁止它**（用户仍可收到邮件）。
- **为什么不新建通知模型/表**：`edu.message`（含偏好静音、入口 `/my/messages`、未读角标）与 `edu.audit.log`（含查询页）**已覆盖「发给谁、看没看、谁改的」**；C-1 的定调是**零新数据**。
- **为什么不用 Telegram 出口**：红线（生产同名意见箱）+ 退役件（§3.2 #12）。

### 6.3 重新考虑 / 收口的触发条件（**必须写，否则它不是决定、是遗忘**）

| 触发条件（可判定） | 到时要做什么 |
|---|---|
| **C-2 落地**（改课候选方案建议） | G1 的「影响面」升级为「候选 + 代价」引擎 ⇒ **必须重新裁定**：并入 C-2 求解器，还是保留影响面为「无算法」快路径。判据 = C-2 设计文档立项之日 |
| **F-1 落地**（教师例外不可用数据进库） | 影响面增加「教师不可用」一维 ⇒ 复用 `resource` 的判定口径，**不得**在 `edu_schedule` 复制一份可用性规则 |
| **`edu.message` 被其它任务收口/改名** | 本功能随迁；判据 = `grep -rn "edu.message" custom_addons/` 的活路径数变化 |
| **改课动作出现第三个入口**（后台表单 / 后台日历 / 门户 / 导入脚本…） | 按 `dev-workflow.md` 的「脚本化条件」：**同一功能第三次落地 ⇒ 必须脚本化**，写 `scripts/check_feature_overlap.py` 并入第 0 步 |
| **`op.session` 的 `student_ids` 被填满**（现为空） | 收件人口径可从「按 batch 回退解析」切回「直接读 `student_ids`」；判据 = `select count(*) from op_session_op_student_rel;` 从 0 变正数（**必须重新验证一遍 G2 的人数口径**） |

---

## 7. 复用 vs 自研边界 · 数据流 · 路由与动作清单

### 7.1 边界（照抄 `timetable-design.md` §二 的写法）

**直接复用（不改一行）**

| 复用物 | 位置 | 复用方式 |
|---|---|---|
| `op.session` 四查口径 | `openeducat_erp/.../models/timetable.py:243-337`（只读） | **语义对齐**（四开关 + ±24h + `state != cancel` + `sudo`）；**不调用基座方法**（它是 `@api.constrains`，不能当查询用） |
| 冲突分色口径 | `edu_schedule/models/session_ext.py:63-115` | 影响面复用其 `_overlaps` 与「教师 > 教室 > 班级」定级顺序 |
| 收件人解析（含空 `student_ids` 回退） | `edu_schedule/models/session_ext.py:216-234 _reminder_users()` | **直接复用同一方法**（它已处理「`student_ids` 为空 → 回退 `op.student.course` 按 `batch_id` 取人」） |
| 站内信引擎 | `edu_portal/models/message.py:15-66` + `notify_pref.py:48-79` | `_notify_event('session_change', user, body)` |
| 审计 | `edu_portal/models/audit.py:29-41` | `_log('课节变更', 'op.session', id, name, detail)` |
| 字段级留痕 | `mail.thread`（`openeducat_erp/.../models/timetable.py:29`） | **零成本**：改字段即自动进 chatter |
| 权限四层 | `code-map.md:256-263` | 教务组并列 `base.group_system` |
| 门户模板外壳 | `code-map.md:246` | 新页面 `t-call="edu_portal.edu_page"`（若走门户渲染） |

**自研补齐（本仓内新增，落在既有模块）**

1. `op.session` 的**只读影响面方法**（`edu_schedule/models/session_ext.py` 内扩展；`store=False`，与 `conflict_kind` 同族）
2. **GET 影响面路由** + 模板（整页，或 JSON 供后台弹窗）
3. **POST 一键通知路由**（csrf + 门禁）
4. 后台表单/日历上的**入口按钮**（继承视图；同型先例 `edu_schedule/views/session_conflict_view.xml:6-19` 的继承手法）
5. `NOTIFY_EVENTS` 追加 `session_change` 一行（`edu_portal/models/notify_pref.py:15-22`，**跨模块的一行**，与 `session_ext.py:250` 运行时查找 `edu.message` 的既有做法一致）

**明确砍掉**

- 拖拽改课 / 求解器 / 候选方案（C-2）；教师可用时间录入（F-1）；Telegram 任何出口；邮件通道自研（保留基座 `notify_user` 原样）；新模型 / 新表 / 新字段 / 新模块 / 新 cron。

### 7.2 数据流

```text
[教务] 后台「时间表」→ 课节列表/日历 点开一节课
         │
         ├─(点按钮)──► GET  /timetable/session/<id>/impact
         │                  │  运行时计算（不落库）：
         │                  │   受影响的人 = faculty.user_id ∪ batch 在读学生.user_id（复用 _reminder_users）
         │                  │   同窗口其它课节 = ±24h、state != cancel、sudo（对齐基座口径）
         │                  │   冲突维度 = 教师 / 教室 / 班级(含班级+科目)（复用 conflict_kind 定级）
         │                  ▼
         │            页面：人数 / 课节数 / 逐条明细（谁、哪节课、哪个维度、会不会被系统自动拦）
         │
         ├─(改字段并保存)─► op.session.write()
         │                  ├─ 基座四查校验（不通过即 ValidationError；这是**既有**兜底）
         │                  ├─ mail.thread 自动写 chatter（9 字段 tracking；**留痕主体**）
         │                  └─ 本设计的审计点：edu.audit.log._log('课节变更', old→new 摘要)
         │
         └─(点「一键通知」)─► POST /timetable/session/<id>/notify
                              │  幂等判定（见 7.4）
                              ├─ 逐人 edu.message._notify_event('session_change', user, body)
                              └─ edu.audit.log._log('课节变更通知', 'op.session', id, name, '通知 N 人')
                                        │
                                        ▼
                           [学生/教师] 门户 /my/messages 未读角标 → 读到「课节变更：…」
```

### 7.3 路由与动作清单（本次设计的全部新增面）

| 类型 | 名称 | 方法/形态 | 门禁 | 说明 |
|---|---|---|---|---|
| 路由 | `/timetable/session/<int:sid>/impact` | GET，`type='http'` | `require_internal()`（同 `edu_schedule/controllers/main.py:43-45`）→ 否则 303 `/my/home` | 影响面页（§7.2） |
| 路由 | `/timetable/session/<int:sid>/notify` | POST，csrf | 同上 + **写门禁**（教务组/系统组，沿用 `privileged_staff()` 口径） | 一键通知；**写路由**，按 `dev-workflow` 陷阱 2 必须配「打完就摸页面」的断言 |
| 视图（继承） | `op.session` 表单/日历加两个按钮 | `ir.ui.view` 继承（**不新增视图文件**，追加进 `views/session_conflict_view.xml`） | 按四层挂 `openeducat_core.group_op_back_office_admin,base.group_system` | 入口＝既有「时间表」应用，不新增根菜单 |
| 模板 | 影响面页 | QWeb，`t-call="edu_portal.edu_page"`（若整页） | — | 控件必须带可访问名（`code-map.md:252` 第 10 条） |
| 模型 | **无新增** | — | — | 只扩展 `op.session` 的方法 |
| 数据 | **无新增**（预期） | — | — | 若最终需要配置类记录，按 §4 判定 |
| ACL | **无新增**（复用既有模型 ACL） | — | — | — |

### 7.4 幂等与去重口径（**必须在设计里定，否则实施必踩**）

1. **同一节课重复点「一键通知」**：允许重复（教务可能补发），但页面必须显示「**最近一次通知：<时刻> · <人数> 人**」，数据源 = `edu.audit.log` 里该 `res_id` 的最近一条 `action='课节变更通知'`（**不新增字段**）。
2. **通知内容必须自证是「这一次的变更」**：`body` 带变更字段的 old→new 摘要（从 `write()` 的 `vals` 取），**不允许**只发「课表变了」这种无法核对的话。
3. **失败不阻断**：`edu.message._notify_event` 已内建「失败只告警」（`notify_pref.py:76-78`）⇒ 沿用；但**返回值必须计数**（`sent/failed`）并在页面回显（对齐 `session_ext.py:243-293` 的「单条失败可计数」教训）。
4. **与 `edu_telegram.hooks` 的双写**：`edu_telegram` 本地仍 `installed`（§3.2 #12）⇒ 实施期必须二选一：① 随退役一并停用该模块（**须队长/校长裁定**，属用户可见变化）；② 或在 C-1 路径上**不触碰 outbox**，并在验收里显式断言「C-1 通知只产生 `edu_message` 行、`edu_telegram_outbox` 行数不因 C-1 增加」。**本设计取 ②**（不改他人模块），并把 ① 列为待拍板（§10）。

---

## 8. 第 3 步：读参考（学什么 / 砍什么）

> 第 3 步产出 = 调研笔记：官方/基座模块的数据模型、冲突检测、权限、视图手法；明确「学什么、砍什么」。

### 8.1 Odoo 19 核心源码（**读源码，不猜**；运行镜像内 `/usr/lib/python3/dist-packages/odoo/addons/`，容器 `edu19-clone-web-1`）

| 主题 | 一手证据（文件 + 行号） | 学什么 | 砍什么 |
|---|---|---|---|
| **「改一个 calendar.event 的时间后，它怎么通知参会者」**（本设计最直接的可抄先例） | `calendar/models/calendar_event.py`：`:74 _inherit=["mail.thread"]`；`:139,171,177,180,186,189` 六个 `tracking=True` 字段（含 `start`/`stop`）；`:768 def write()`；**`:796-798`** 取 `_get_time_fields()`，**只要写入了时间字段就置 `update_alarms = update_time = True`**；**`:850-864`**：若 `'start' in values` 且**不是新建**、**不是 `skip_attendee_notification` 上下文**、且**新开始时间在未来**，则 `(current_attendees & previous_attendees)._notify_attendees(ref('calendar.calendar_template_meeting_changedate'), force_send=True)`（`:861-863`）；`:839` 另有 `dont_notify` 上下文闸门 | ① **按字段白名单判定「值不值得通知」**（与基座 `_NOTIFY_WORTHY_FIELDS` 同族）；② **按 diff 选模板**（新增参会者走 `_send_invitation_emails`＝`calendar_attendee.py:115`，改时间走 `calendar_template_meeting_changedate`）⇒ C-1 的通知文案**按变更字段生成**；③ **只通知「旧新交集」**（`current_attendees & previous_attendees`，`:859`）——**别把已移出的人算进受影响面**；④ **上下文开关**（`dont_notify`/`skip_attendee_notification`）让批量导入不炸通知 | 不用它的 `calendar.alarm`/`_setup_alarms` 提醒机制（`calendar_alarm_manager.py:198`）——提醒不是本功能 |
| **`mail.thread` 字段变更留痕机制** | `mail/models/mail_thread.py`：`:632 _track_subtype`（**默认 `return False`**）→ `:644 _message_track`（比对初值与现值，产出 `changed_field_names + tracking_value_ids`）→ `:675-690`「**有 subtype 才 `message_post`，无 subtype 只记录（`_message_log_batch`）、不通知**」；`:702 _message_track_post_template`、`:742 _track_template`；值表 `mail/models/mail_tracking_value.py:68 _create_tracking_values`、`:197 _tracking_value_format`；`mail_thread.py:1393-1397` 展示 `mail.mt_note`（内部）/`mail.mt_comment`（对外）的分流 | **字段级留痕是「框架自带」**——只要字段 `tracking=True`，写一次就有旧值/新值行；**通知与否由 subtype 决定**（`op.session` 没覆写 `_track_subtype` ⇒ 默认 False ⇒ **只留痕、不自动发信**）——这正是 C-1 需要「人按一下」的框架依据 | 不覆写 `_track_subtype`、不动基座（一改就影响所有写入路径，包括导入脚本） |
| **`resource` 模块（仅作 F-1 备注，不在本次范围）** | `addons/resource/models/` 共 7 文件：`resource_calendar.py`、`resource_calendar_attendance.py`（工作时段）、`resource_calendar_leaves.py`（休假/例外）、`resource_mixin.py`、`resource_resource.py`、`res_company.py`、`res_users.py` | **F-1 备忘录**：教师「例外不可用」应对齐 `resource.calendar.leaves`（一条记录 = 某资源某时段不可用），**不要自造第二套日历语义**；`op.faculty` 走 `res.partner` 继承，接线方式待 F-1 立项时再核 | 本次**不读细节、不设计**（用户已明确 F-1 不在范围） |

### 8.2 基座 `openeducat_timetable`（只读快照）

**学什么**：① 冲突判定口径（四开关 + ±24h + `state != cancel` + `sudo` 跨教师可见，`models/timetable.py:243-337`）——**C-1 的影响面逐条对齐它**；② 关注者自动维护（`:339-354 create` → `_sync_session_followers`；`:377-394` 增减 follower；`:512-567 write` 里 rebalance）——**这是「受影响的人」的框架级先例**；③ 变更具名留痕（`:569-607 _log_student_ids_change`：M2M 变化逐人列名 `message_post`，注释明说「字段级 tracking 只会说 list changed、不点名」）——**C-1 的留痕文案照这个标准**；④ 七日网格向导（`wizard/generate_timetable.py:30-133`）与批量确认向导（`wizard/session_confirmation.py:24-33`）。

**砍什么**：它的 `notify_user()` **不作为 C-1 主通道**（草稿态不发、只发 followers、自动而非手动，§3.2 #11）；**不改它**（基座只读）。

### 8.3 本仓既有实现（可复用 / 不可复用）

**可复用**：`conflict_kind` 口径（`session_ext.py:63-115`）；`_reminder_users()`（`:216-234`，**含空 `student_ids` 的班级回退**）；`_notify_upcoming()` 的**逐条 try + 计数**结构（`:236-293`）；`edu.message._notify_event`（`notify_pref.py:48-79`）；`edu.audit.log._log`（`audit.py:29`）+ `/edu/audit`（`roles.py:1402`）；`edu.grade.history` 的字段语义（`registration.py:355-392`）；继承视图手法（`session_conflict_view.xml:6-19`）；`/timetable/bulk/preview` 的「**落库前先预检查**」产品形态（`controllers/main.py:415-436`）。

**不可复用**：`edu_telegram` 全套（退役 + 出口红线）；`edu_telegram/hooks.py` 的课表变更推送（§3.2 #12）；基座 `notify_user` 作为主通道。

### 8.4 回引 `docs/research/scheduling-approaches.md`（**第 4 步硬要求**）

> **调研 §6 的 8 种降本手段**（该节表 `scheduling-approaches.md:348-357`）里，「我们现在有没有」一栏明确标了 4 个 ❌、2 个 ✅、2 个「部分」。C-1 精确落在**第 2 条与第 7 条**上：

| §6 手段 | 原文结论（一手来源与行号见 `scheduling-approaches.md`） | C-1 的对应 |
|---|---|---|
| **#2 落库前预检查，且提示分三类**（有冲突 / 被规则限制 / 数据异常） | `:351`：校管家·表格排课；我们的 `/preview` 已有红格/灰格雏形「✅ 部分有，但**不区分"冲突"与"规则受限"**」 | C-1 的影响面 = 这条的**「改课版」**：既有 `/preview` 只在**创建前**、且只分「冲突/无冲突」；C-1 把它补成**改动既有课节**时的影响清单，并在文案上**区分**「会被系统拦下（四查）」与「不会拦但会被惊动（人是受影响者）」。**「被规则受限」这一档仍缺**（依赖 F-1）⇒ **本设计明确不假装有** |
| **#7 改课/代课走「最小扰动建议」** | `:356`：UniTime「suggests a limited size set of alternative… **not affecting the assignment of more than two additional classes**… each option provides information on any additional student conflicts created」；Untis「solution suggestions with only one click… instantly see who is available」；aSc「advise the best cover teacher - **but you are free to choose**」；本仓现状「❌ 完全靠人肉找空档」 | C-1 只做这件的**前半段**：「**先告诉他动这一节会连带动到哪几节**」（对应 UniTime 口径里的 "additional classes created"）。**候选方案（alternative）留给 C-2** |
| **§9 第 2 件：把改课/代课做成最小扰动建议——但先做数据，再做算法** | `:447-461`：①「**先把"可用性"变成数据（零算法）**」＝教师不可用时段（校管家·老师日程 / UniTime「must be available / not during a prohibited time」/ ClassIn 可约时间）；② 再做候选方案搜索；并强调「代课/换课是**发生频率最高**的教务动作，而且是最花人工的」 | **C-1 = ① 与 ② 之间的那半步**：在 F-1 的数据到位**之前**，先用**现有**数据（课节本身 + 班级 + 教师 + 教室）把「这会惊动谁」摊开。**这也是本设计对调研的唯一偏离**：调研的 ① 是「先做数据」，C-1 是「先做**可见性**」——理由见 §6.2（不需要新数据、当天可见收益），**且已由校长按 C-1→F-1→C-2 的顺序拍板** |
| **§9 第 1 件顺带复核** | `:445`：「基座 `generate.time.table` 向导本身就是网格式的，我们绕开它自研了门户表单——**值得在动手前先看一遍基座向导到底缺什么**（避免重复造）」 | 本次已读全（§3.3 #14）：它**缺**「改既有课节」「影响面」「通知」「留痕」四件事 ⇒ **C-1 不重复造网格**；合并待办见 §1.2 |
| **§6 的 8 条里我们最强的一环** | `:357`：「#8 周期批量生成 + 模板复制 ✅ **这是我们目前最强的一环**」 | C-1 **不动** `/timetable/bulk`（避免把最强的环碰坏）；影响面只是**同一模块内的新出口** |

**学什么 → 砍什么（第 3 步的一句话产出）**：**学**「改动即告知」的先例形态（Odoo calendar 的 changedate 模板 + 新旧交集通知；校管家的预检查三类提示；UniTime 的「连带动了几节」）；**砍**一切需要新数据或算法的部分（教师可用性＝F-1、候选方案＝C-2、求解器＝不做）。

---

## 9. 验收标准（真机可验证的具体步骤）

> 口径：**改路由/控制器的验收里必须有一条真的去 GET 那个页面、并核对页面上的数字**（`dev-workflow.md` 陷阱 2）；**探测不许跟随重定向**（`allow_redirects=False` + 精确 `Location`）。
> 判定模板照 `dev-workflow.md`：「**① 绕过被测路径 → ② 读真正的产物 → ③ 还原并断言 `leftover=0`**」。

### 9.1 环境前置（缺一不可，否则读数无效）

1. 无升级锁：`test ! -f $TMPDIR/edu19_upgrade.lock`；容器 `Up > 30s`；`curl -c jar -b jar 'http://localhost:8069/web/login?db=edu19'` ∈ {200,302,303}。
2. **计数型判定前置**：`ls -lt /tmp/edu19_upgrade.*.log | head -3` 确认最近没跑过 `-u edu_life`（F5 会往业务表补演示打卡，见 `dev-workflow.md` 陷阱 1）。
3. 记录基线（**先取基线，再动手**）：`mail_tracking_value`、`edu_audit_log`、`edu_message`、`edu_telegram_outbox` 四个计数。

### 9.2 逐条验收（建议写成 `tests/smoke/c1_impact_notify.py`）

| # | 步骤（可原样执行） | 期望读数 |
|---|---|---|
| V1 | `bash scripts/safe_upgrade.sh edu_schedule` | **EXIT=0**，输出无 `Traceback`/`CRITICAL`/`manifest not found` |
| V2 | 离线门禁：`python3 scripts/check_view_xpath.py --selftest`、`check_manifest_tracking.py --selftest`、`check_qweb_dict_foreach.py --selftest`、`check_english.py --selftest`、`check_odoo_trace.py --selftest`、`python3 tests/smoke/gate_seam_check.py` | 全部 exit 0 |
| V3 | **正对照（先证载体合法）**：`select id,batch_id,faculty_id,state from op_session where batch_id=8 and state<>'cancel' limit 1;` | 命中 ≥1 行（batch 8 有 1 名在读学生，见 §A.3）；否则换一节**确实有在读学生**的课节，**不得在空载体上验收** |
| V4 | 教务 `backoffice@local` 登录 → 后台「时间表」→ 打开该课节 → 点「影响面」 | 页面 200；**页面上的「受影响人数」「受牵连课节数」必须等于 §A.4 同一口径的 psql 读数**（人工对拍一次并写进报告） |
| V5 | 脚本探测（**不跟随重定向**）：`sess.get(BASE+'/timetable/session/<id>/impact', allow_redirects=False)` | `200`；**且** `stu@local`（无内部身份）得 `303` + `Location == '/my/home'` |
| V6 | **写路由安全目标**（`dev-workflow` 写路由三收紧）：POST `/timetable/session/99999999/notify`（不存在 id）与对 `stu@local` POST 真 id | **3xx（非 500）**；**先断言该目标确实越界/不存在**；并断言相关表**行数未变** |
| V7 | **改一次课 → 读真正的产物**：把该课节 `start_datetime` 改到不冲突的相邻时段并保存 | ① `mail_tracking_value` 中该 `res_id` 的 `start_datetime` 行 **+1**（old/new 非空）；② `edu_audit_log` 新增 1 行 `action='课节变更'`（`model='op.session'`、`res_id` 正确） |
| V8 | 冲突兜底（既有能力，防回归）：把该课节改到与教师 43 的另一节课**完全重叠**的时段 | 保存被拒（`ValidationError`，基座四查；前置 = `timetable.is_faculty_constraint` 生效，见 `edu_portal/data/timetable_params.xml` 的 `noupdate` 固化） |
| V9 | **一键通知**：点「一键通知」 | `edu_message` 新增 **N** 行、`event_key='session_change'`、`body` 含 old→new 摘要；**N == V4 页面人数**；`edu_telegram_outbox` **不因本次操作增加**（§7.4 #4） |
| V10 | 收件侧真机：`stu@local` 登录 `/my/messages` | 未读角标 +1，会话里读到该条；截图存 `tests/gap/shots/`（六步闸门第 6 步） |
| V11 | **还原并断言 leftover=0**：把 `start_datetime` 改回原值；按 `--clean` 分支删除本次演示产生的 `edu_message`/`edu_audit_log` 行 | `select count(*) … where body like '【演示】%'` = 0；`op_session` 该行 `start_datetime` == 基线值 |
| V12 | 文案与无障碍门禁 | `python3 scripts/check_english.py` → **must-fix = 0**；`python3 scripts/check_odoo_trace.py` → 0 命中；`python3 scripts/check_accessibility.py` → **不新增违规**（BASELINE=0，新按钮必须带可访问名） |
| V13 | 权限四层自检 | 教务组可见可用；学生/家长访问两条路由得 303；教务组 implied 传递闭包**不含** `base.group_system`（不回归） |

### 9.3 反例（**明确不允许**的验收写法）

- ❌ 「升级 EXIT=0」当作通过（`dev-workflow` 陷阱 2：装载 ≠ 路由能跑）。
- ❌ 用 `allow_redirects=True` 探测新增路由（会把 303 判成 PASS）。
- ❌ 在 `student_ids` 为空的课节上验收「通知了 N 个学生」——本地 `op_session_op_student_rel` = **0 行**（§A.3），必须在**有在读学生的班**上验。
- ❌ 只读代码就声称「留痕已生效」——必须读回 `mail_tracking_value` 行（claim 与证据同级）。

---

## 10. 需要校长拍板的用户可见项（**4 项**）

| # | 待拍板 | 选项 / 影响面 |
|---|---|---|
| **P1** | **命名**（用户可见文案） | ① 入口按钮与页面标题叫「**改课影响面**」还是「**变更影响**」/「**这节课动了会影响谁**」？② 动作按钮叫「**一键通知**」还是「**通知相关师生**」？③ 通知标题叫「**课节变更**」还是「**调课通知**」？**影响面**：门户消息中心、`/my/notify` 偏好页、审计页的动作列（`edu_portal/controllers/roles.py:70-140` 有中文模型/动作名映射表，**需同步登记**） |
| **P2** | **通知渠道与收件人口径** | ① 只发**站内信**，还是同时**发邮件**（基座 `notify_user` 邮件是否保留同发 = 可能双份）？② 收件人 = 任课教师 + 该班**全部在读学生**，还是「教师 + 学生」而**家长不发**（家长被基座 `timetable.py:168-203` 算进 `user_ids`，C-1 要不要跟）？③ 是否给用户一个**默认静音**的开关（`session_change` 默认 `muted=False` 还是 `True`）？**影响面**：每改一次课的触达人数与打扰程度 |
| **P3** | **数据归属 / 可见范围**：变更留痕**给谁看** | ① 仅教务（`/edu/audit`，现状）；② 教务 + 该节师生（门户能看「这节课改过时间，原 X」）；③ 全员可见。**影响面**：留痕一旦对师生可见，就是**对外承诺**（改错了藏不住）；且 `mail.thread` chatter 的可见性由 followers 决定，需按口径设计收件人 |
| **P4** | **停课（`state='cancel'`）是否走同一套** | ① 同套（改课与停课都通知）；② 停课单独走「停课通知」文案。**背景事实**：库内 `cancel` **0 条**（`draft 266 / done 22`），即停课流程**至今没被真实用过** ⇒ 若选 ①，应在首个真实停课案例后复核（**事件型前提已标在 §6.3**） |

> 除上述 4 项外，本次设计**没有其他需要用户拍板的项**。

---

## 11. 未查到 / 不确定（**不得当结论用**）

| # | 未验证项 | 我做了什么 / 为什么不确定 |
|---|---|---|
| 1 | **`openeducat_erp/` 快照「上游原版 vs 本仓改过」无法判定** | `git check-ignore -v openeducat_erp/...` → `.gitignore:11:openeducat_erp/`；`git ls-files openeducat_erp` → **0 个文件**（该目录**从未入库**）⇒ **无版本历史可比**。能证明的只有「工作区副本 == 容器运行副本」：`models/timetable.py` 的 md5 双方均为 `910d0d5f2f615506b0ae242ad36a88f2`。**因此本文对基座行为的描述只对「本工作区快照」成立**，不外推到上游 OpenEduCat 19.0 |
| 2 | **库内 306 条 `<p>会议 创建</p>` 消息的来源未定位** | 事实：`mail_message` 中 `model='op.session'` 共 **308** 条 → **306** 条正文为 `<p>会议 创建</p>`、`author_id=2`（OdooBot）、`message_type='notification'`、`subtype_id=2`（Note），跨 2026-08-22～2026-09-17、覆盖 **306 个不同 res_id**；另有 2 条带 4 条 `mail_tracking_value`。**搜索范围（全部 0 命中）**：容器 `/usr/lib/python3/dist-packages/odoo/addons/` 全量搜 `会议 创建` 与 `Meeting created`；工作区 `openeducat_erp/`、`custom_addons/`、`scripts/`、`docs/` 同串搜索。**唯一线索（未验证）**：`mail_activity_type` id=3 = `{'en_US': 'Meeting', 'zh_CN': '会议'}`，而 `mail_activity` 中 `res_model='op.session'` 现为 **0 条**（活动可能已被删除、消息留存） |
| 3 | **真实改课路径产生的字段留痕量未被证明** | `mail_tracking_value` 全库 137 行，`op.session` 只有 **4** 行（2026-08-24 两条消息）。机制在（9 字段 `tracking=100` 已入库）但**样本太少**。⇒ V7 就是为补这个读数设计的；**在 V7 跑出来之前，不得声称「留痕已可用」** |
| 4 | **基座 `notify_user()` 的邮件到底有没有真的发出去，不可判定** | `mail_mail` 中关联 `op.session` 的消息 = **0** 行；但模板 `auto_delete` 与 `mail.mail` 的自删行为叠加 ⇒ **0 行既可能是「发过」也可能是「没发」**。要判定需在实施期临时观察一次发送 |
| 5 | **「`_notify_upcoming` / `_reminder_users` 已验证可用的通知通道」——站内信侧本地取不到成立证据** | 实测：`op_session.calendar_event_id` 非空 **2** 条；`reminder_sent_at` 非空 **1** 条（session 756，2026-09-12 06:19:34 ⟹ `_notify_upcoming` 至少成功过一次，因该字段仅在 `ok=True` 时写，`session_ext.py:318-319`）；但 `edu_message` 正文含「课前提醒」= **0** 条，而 `edu_telegram_outbox` 正文含「课前提醒」= **14** 条 ⇒ 实际出网走的是 Telegram 侧，**站内信侧 0 痕迹、原因未定位**。⇒ 本设计把 `edu.message` 当**主通道**，依据是「它在别的 6 个事件上已有 1154 行真实数据」（§A.5），**而不是**课前提醒那次 |
| 6 | **教室维度本地验不了** | `classroom_id` 为空的课节 **277/288**，`op_classroom` 仅 **3** 条（`docs/plans/timetable-design.md:74` 已记「教室字段现库中为空」，`docs/code-map.md:74` 记的是别的事）。⇒ 影响面的「教室冲突」一维**在本地造不出自然样本**，V4 的「页面数字 == psql 读数」在教室维大概率是 0；**要么先补种子（走 §5 的【演示】策略），要么在报告里显式标「教室维未验证」** |
| 7 | **通知触达天花板未测** | `op_student` **4** 条、其中有登录账号的 **1** 条；`op_student_course` **4** 条且其中 3 条 `batch_id` 为空（仅 batch 8 有 1 条）。⇒ 「通知到人」在本地最多触及 **1 名学生**；**生产口径未取**（本次只读本地 `edu19`） |
| 8 | **`resource` 模块只做了文件清单级确认** | 仅 `ls addons/resource/models/`（7 个文件）+ 文件名级判断；**未细读**（用户已明确 F-1 不在本次范围）。F-1 立项时必须重读 |
| 9 | **`edu_telegram` 在本地的实际活跃度未测** | 只知道它 `installed`、`models/__init__.py` 导入了 `hooks`、`edu_telegram_outbox` 有 117 行（其中 14 行含「课前提醒」⇒ 与课前提醒同源）。**它自己的课表变更推送到底推过多少次，没有按内容分类的证据** |
| 10 | **生产库同类读数未取** | 本文所有 DB 数字都是本地 `edu19`。生产（马来西亚 prod-host）的 `op.session`/`mail_followers`/`edu_message` 口径**未知**，部署前需另取一次基线 |
| 11 | **「课前提醒站内信 0 条」已定位为历史清场、非缺陷**（2026-09-18 实施期补记，含一处范围外发现） | 现场复现：`op.session(756)._notify_upcoming()` 在 savepoint 内返回 `(True, 0)`，**事务内确实产生 2 条 `edu_message`（正文含「课前提醒」）+ 2 条 outbox 行**，回滚后库内读数不变（残留 0）⇒ 通道本身可用、收件人解析正常（`_reminder_users()` = stu@local(8) + faculty@local(11)，与 06:19:34 那两条 outbox 行一一对应）。库内 0 条的成因：① 那 14 条 outbox 行是 2026-09-12 的多次干跑/手工跑（05:18/05:19/06:19/06:37，非 5 分钟节律）；② `docs/plans/t12-review-t6-onestop-service.md:40` 记录「干跑产生的 2 条【冒烟】课前提醒站内信」被清理（残留=0），而 outbox 行不在清场范围 ⇒ 消息表少了、出队表留下；③ `edu_message` 序列空洞（341-353、488-489、530-531、544、566-573 等；`max(id)`=1848 而 `count`=1154）与「插入后删除/回滚」一致。**范围外发现（未修）**：`session_ext.py` 的 `_notify_upcoming()` 把 `reminder_sent_at` 的写入条件定为「任一通道成功」（出队成功也计入 `sent>0`）⇒ 站内信全失败但出队成功时**不留任何站内信痕迹**；`7b43a49` 版本更甚（整段 `except Exception: pass`），t51 已改成逐条 try + 计数。**裁定：不修**（通道可用；若要加固，把条件收紧为「站内信通道成功」，另立任务） |

---

## 12. 台账登记（第 0 步「查到重复怎么办」第 2 步）

按 `docs/dev-workflow.md` 第 0 步：**不得直接新建；先登记；由队长裁定**。本次在 `docs/audit/deprecated-inventory.md` **追加一行**（**不覆盖任何历史行**）：

> 重叠对象 = `edu_telegram/models/hooks.py` 的「课表变更推送」；
> 证据 = `custom_addons/edu_telegram/models/hooks.py:5-35`（`op.session.write` 覆盖 + `WATCH` 6 字段 + `edu.telegram.outbox.enqueue`）、`models/__init__.py` 导入 hooks、模块 `edu_telegram 19.0.2.2` 本地 `installed`、`edu_telegram_outbox` 117 行；
> 候选方案 = **合并（入口收口）**：替代路径 = `edu.message._notify_event('session_change', …)`；实施期须处理双写（§7.4 #4）。

---

## 附录 A：本次实测读数（2026-09-17，本地库 `edu19`，只读 SELECT）

```bash
# 采集方式（逐条实跑，可复现）
docker compose exec -T db psql -U odoo -d edu19 -t -A -F'|' -c "<SQL>"
```

**A.1 `op.session` 总量与状态**：**288** 行 = `draft 266` + `done 22` + **`cancel 0`**
→ ⟹ 基座的「取消」状态**从未被真实使用**；P4 的答案没有现成样本。

**A.2 关注者与消息**：`mail_followers`（`res_model='op.session'`）= **88** 行，覆盖 **68** 节；组成 = `预备科导师【演示】68 / Administrator 14 / 王小明 6`。
`mail_message`（`model='op.session'`）= **308** 行（详见 §11-2）；`mail_tracking_value` 全库 **137**、其中 `op.session` **4**、`calendar.event` **2**。

**A.3 关系与主数据**：**`op_session_op_student_rel` = 0 行**（⇒ 全库 `student_ids` 实际为空，基座 `_session_follower_partners` 只能订阅到教师）；
`op_student_course` **4** 行（仅 batch 8 有 1 行、其余 3 行 `batch_id` 空）；`op_student` **4**（有登录 **1**）；`op_faculty` **2**；`op_batch` **17**；`op_classroom` **3**；`classroom_id` 为空的课节 **277/288**。

**A.4 影响面样例（口径预演，用 psql 复现设计里的算法）**：取 `op.session.id=746`（batch 12 / faculty 43 / 无教室）：
同教师重叠 **0** 节；同班级重叠 **0** 节；该班 `op.student.course` 在读学生 **0** 人 ⇒ **这一节的影响面为空**。
⟹ 结论：**本地必须挑「有在读学生的班（batch 8）+ 同教师相邻课节」来验收**，否则会得到「影响面永远为空」的假绿（这正是 V3 正对照要挡的东西）。

**A.5 通知/审计/邮件既有量**：`edu_message` **1154** 行（`event_key` 分布：`grade_result 697 / notice_publish 205 / subject_reg_result 155 / approval_escalate 62 / leave_result 24 / 空 11`）；
注意 `notice_publish` 与 `approval_escalate` **不在** `NOTIFY_EVENTS`（`notify_pref.py:15-22`）白名单里 ⇒ **未登记的 key 也能发，只是用户静音不掉**（这是本设计给 `session_change` 追加白名单的理由）；
`edu_notify_pref` **6** 行（偏好功能轻度使用）；`edu_audit_log` **1432** 行；`mail_mail` 全库 **50**（关联 `op.session` 的 **0**，见 §11-4）；`edu_telegram_outbox` **117**（含「课前提醒」14，见 §11-5）。

**A.6 模块状态**：`edu_schedule 19.0.2.1.0 · installed`（manifest `version 19.0.2.1.0` 一致）；`openeducat_timetable 19.0.1.1.0 · installed`（快照 manifest `19.0.1.1.0` 一致）；
`edu_portal 19.0.2.0.0 · installed`；`edu_life 19.0.1.0.0 · installed`；**`edu_telegram 19.0.2.2 · installed`**（退役但仍在库，见 §3.2 #12）。

**A.7 环境**：容器 `edu19-clone-web-1`（Up 5h）、`edu19-clone-db-1`（Up 15h，healthy）；Odoo 19 addons 路径 `/usr/lib/python3/dist-packages/odoo/addons/`；`config/odoo.conf` **未配置 `demo` 相关键**，12 个 `custom_addons/*/__manifest__.py` **全部没有 `demo` 键**（§4）。

---

## 附录 B：本次未做的事（可核对）

- **未写一行代码**：本任务的改动只有 `docs/plans/session-change-impact-design.md`（新建）与 `docs/audit/deprecated-inventory.md`（追加一行）。
- **未动 `openeducat_erp/`**（该目录被 `.gitignore` 忽略，不在提交范围）。
- **未动 `custom_addons/`**。
- **未改数据库**：全部 SQL 均为 `SELECT`；未 `CREATE`/`DROP` 任何对象（对照 `dev-workflow.md` 判据强度第 5 条「量具本身不许有副作用」）。
- **未提交任何他人改动**：提交用路径限定（`git commit -m … -- <两个文件>`），且提交后复核 `git show --name-only --format=%s HEAD`。

---

## 变更记录

| 日期 | 改动 | 责任 |
|---|---|---|
| 2026-09-17 | 建立：C-1 的第 0 步（落地前查重）+ 第 3 步（读参考）+ 第 4 步（设计摘要）；裁定 = 复用 + 模块内扩展；头号重复对象 `edu_telegram/models/hooks.py` 已登记台账 | 设计子代理（C-1） |
| 2026-09-18 | **实施 + 真机验收**：`edu_schedule`（models/controllers/views）+ `edu_portal` 两处最小改动（`notify_pref.py` 事件 key、`roles.py` 模型中文名）；验收脚本 `tests/smoke/c1_impact_notify.py`（35 项全绿）。**修正 §7.4#4 的验收口径**：「outbox 行数不因 C-1 增加」不成立（`edu_telegram/hooks.py:5-35` 覆写 `op.session.write()`，改课即写 outbox），已改为**基线对照**：只改课 A=6 / 改课+一键通知 B=6 ⇒ C-1 没有多写 | 实现子代理（C-1） |
