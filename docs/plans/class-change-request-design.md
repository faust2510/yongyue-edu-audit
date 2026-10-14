# 学生调班申请与教务审批（班级变更申请）设计
> **状态**：`已上线` ｜ **主题**：`调班申请与审批` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「仅设计」，实际已于 `9b8509d` 交付（2026-09-26 核对发现）。正文未改动。

> **历史状态**：仅设计（第 0 步「落地前查重」+ 第 3 步「读参考」+ 第 4 步「设计摘要」）。
> **本文件不代表已实施**——本次**未写一行代码**、**未新建模块**、**未动 `openeducat_erp/`**、**未动 `custom_addons/`**、**未改库**（全部读数为只读 SELECT）。
> **需求一句话**（校长原话）：「由于当时我是给别人展示的时候用的王佐账号，我乱填的选课，结果导致我**进错班级**了，我希望**学生可以申请修改，让管理员通过**。」
> ⇒ 功能：**学生申请调班（换班）→ 教务审批通过后生效**。
> **口径来源**：`docs/dev-workflow.md` 第 0 步与六步闸门 ｜ `CLAUDE.md` 铁律 0 ｜ `docs/plans/enroll-v2-design.md`（选课注册单先例）｜ `docs/plans/session-change-impact-design.md`（C-1：通知/留痕通道口径）｜ `docs/plans/class-batch-management-design.md`（需求 7：班级实体口径）
> **采集时刻**：**2026-09-18**；读数口径 = 本地库 `edu19`（只读 SELECT）+ 容器 `edu19-clone-web-1`（Odoo 19 运行时源码 `/usr/lib/python3/dist-packages/odoo/`）。
> **行号取证** = 仓内 `openeducat_erp/` 快照（19.0，**只给路径+行号，不贴源码**）+ 本工作区当前 HEAD + Odoo 19 运行时源码。
> **未验证项**一律集中写在 §17，**不得当结论用**（本仓规范）。

---

## 修订记录

| 项 | 内容 |
|---|---|
| **版本** | **v2（2026-09-18）**。v1 = 本文件 commit `58bc028`，**原文一字未删、仍完整在案**（本仓台账惯例 = 追加不覆盖）；凡 v2 与 v1 冲突处，**以 v2 为准**。 |
| **修订原因** | **校长改判 P6**：v1 的 §16 P6 建议「(a) 不允许跨课程调班」，**校长否决**，原话「**课程也可以换**」（六项拍板第 6 条）。 |
| **修订性质** | **不是返工**：是**需求变了**。v1 三条核心论证里，**生效语义（§8）与载体裁定（§7）必须重做**；审批人（§9）、三条通道（§11 通道本身）、与需求 7 的关系（§12）不受影响。 |
| **受影响章节** | §0（TL;DR 的载体行/生效语义行/P6 行）、§1.2（非目标「不做跨课程调班」）、§3.2 ⑤、**§7（载体裁定）**、**§8（生效语义，重做）**、§10（路由与动作清单）、§11（通知**收件人范围**）、§13.2（数据流 A/B/C）、§15（验收）、§16（P1 命名 / P6）、§17（未验证项）、§18（台账登记）。以上各章标题下均加了「⚠ v2 修订」标记，**标记统一指向新增的 §19**（本次修订正文）。 |
| **新增章节** | **§19「修订（v2）：P6 改判『课程也可以换』」**（含 19.0–19.10：载体重裁 / 生效语义重做 / 命名候选 / 表单字段 / 通知收件人 / 生产与本地读数 / 复核不符项 / 收口触发条件 / 验收增量 V15–V22 / 未验证项）。原 §19「变更记录」**重编号为 §20**，内容未改（仅表尾追加两行）。 |
| **其余 5 项拍板照办** | P1 命名因 P6 改判**需重新给候选**（§19.3 P1′）；P2 只有教务 + 超管 ✅ 照办；P3 显示「原班 → 新班」✅ 照办（跨课程时扩为「原课程/班 → 新课程/班」）；P4 **复用既有事件、不新增 key** ✅ 照办（§19.5）；P5 旧班历史考勤/成绩对学生可见 ✅ 照办。 |
| **本次复核口径** | 本地库 `edu19`（只读 SELECT，容器 `edu19-clone-db-1`）+ **生产库 `edu19`（只读 SELECT，`ssh prod-host` → 容器 `edu19-prod-db-1`）** + 仓内当前 HEAD 的 `openeducat_erp/` 与 `custom_addons/`（**只给路径 + 行号，不贴基座源码**）。**未写一行代码、未改 `custom_addons/`、未改 `openeducat_erp/`、未改任何库**。 |
| **本次独立复核的 3 条不符项** | 见 §19.7（① `batch3.py:277` 的取班口径措辞；② `batch2.py:616` 的同类失效注释；③ 「写库入口唯一」的作用域与 `eval_portal` 行号）。 |

---

## 0. 结论速览（TL;DR）

> ⚠ **v2 修订（2026-09-18，P6 改判）**：本表「载体裁定」「生效语义」「待校长拍板」三行已被重做（§19.1 载体重新裁定、§19.2 生效语义重做、§19.3 拍板项含命名 P1′/P6′/P7–P10）。其余各行的**证据链仍然有效**。 **以 §19 为准。**

| 项 | 结论 |
|---|---|
| **载体裁定（三选一）** | **复用（候选 A）**。**载体现成**：`op.subject.registration` 已有完整状态机 `draft/submitted/approved/rejected`、已有 `doc_type` 分型先例、已有门户审批聚合页、已有后台审批菜单、已接通知与审计。**扩展方式** = 新增**第三个 `doc_type = 'batch_change'`（调班）** + 一个**不碰科目**的审批动作 `action_batch_change_approve()` + 一条学生路由族。**不新建模块、不新建模型、不新建表。** |
| **头号事实（必须先看）** | **本仓已有一个"半成品"的同类实现**：学生路由 `/course/change/request` + `/course/change/request/save`（`edu_portal/controllers/batch3.py:213,258`，写 `doc_type='course_change'`），**但教务侧明确把它排除在审批队列外**（`views/approval_backend.xml:229` 注释原文「课程变更单不进审批队列」；`controllers/enroll.py:337` 的 domain 硬写 `doc_type='subject_registration'`）⇒ 库里 **11 张 `course_change` 单 100% 卡在 `submitted`**，从未有人批过。**这既是"必须复用"的最强证据，也是"必须先把口径定死"的理由**（§3.2）。 |
| **第二事实（结构性死路）** | 那条既有链路**批不动**，不只是"没入口"：① `batch_id` 由学生当前档案带出（`batch3.py:277-278`），而 `course_id` 由表单另选 ⇒ 库内 11 张单全部满足 `batch.course_id(18) ≠ course_id(13)`；② 既有的 `action_enroll_approve` 会**整体覆盖 `subject_ids`**，并在"单无科目而档案有科目"时**抛 UserError 拦住**（`models/registration.py:161-171`，校长 2026-09-17 亲裁「拦住吧」）⇒ 把调班单接进同一个动作会**当场死锁**。 |
| **生效语义（最关键）** | **当场改写 `op.student.course.batch_id`（不新建档案行、不置 finished）**。理由：① `batch_id` 自带 `tracking=True`（`student.py:34`）⇒ 字段级 old→new 自动进 chatter；② 唯一约束 `unique(student_id,course_id,batch_id)`（`student.py:50`）会让"新建 + 旧行 finished"的写法**换回原班时直接撞约束**（旧行还在）；③ `state='finished'` 在学生侧渲染成**「已结业」**（`enroll.py:309`）＝ 语义污染；④ 这与本仓**唯一**的既有"定班"写库语义完全一致（`registration.py:193-195`）。风险见 §8.3（**旧班历史考勤/教师名单会立刻看不到他**，有行号实证）。 |
| **审批人** | `roles.privileged_staff()`（= `openeducat_core.group_op_back_office_admin` **或** `base.group_system` 并列，`roles.py:154-160`）。**建议不带 `current_faculty()`** —— 与选课审批（`enroll.py:328` 是 `current_faculty() or privileged_staff()`）**故意不同**：调班改的是**学籍归属**（本仓四层里属业务管理层），与需求 7 的 §13 P2 同答。 |
| **学生侧入口** | 新增路由族 **`/batch/change/request`（GET）+ `/batch/change/request/save`（POST）**，与既有 `/course/change/request` **互为兄弟**（同载体、同状态机、同审批页、同通知审计）；学生首页卡片复用同一套卡片引擎。门禁 = `current_student()` 判空 → `303 /my/home`（门户铁律）。 |
| **通知与留痕** | **100% 复用 C-1 已落地的同一套通道**（不另造）：`edu.message._notify_event`（`models/notify_pref.py:51`，事件 key 登记在 `:15-24`）+ `edu.audit.log._log`（`models/audit.py:29`，查询页 `/edu/audit`，`roles.py:1406`）+ `mail.thread` 字段级留痕。 |
| **与需求 7 的关系** | **不冲突、不复用第二套概念**：班级实体仍只用 `op.batch`，学生归属仍只用 `op.student.course.batch_id`。本设计**恰好落在需求 7 自己写下的收口触发条件上**——其 §8.4 **T3**：「出现第二个『给学生定班』的写库入口（今天只有 `registration.py:178-195`）」⇒ 本设计**必须把写库语义收敛到同一处**，并**明确接力**其 §1.2「不做学生自助转班」这一条非目标（校长本次原话推翻了它，见 §12）。 |
| **待校长拍板** | **6 项**（入口命名 / 谁能批 / 可见范围 / 通知事件与文案 / 历史考勤可见性 / 是否允许跨课程），见 §16。 |

---

## 1. 目标 / 非目标

### 1.1 目标

| # | 能力 | 用户感受 |
|---|---|---|
| **G1** | 学生看到「我现在在哪个班」，并能**提交一次调班申请**（选目标班 + 填理由） | 「进错班了」不再只能私信教务 |
| **G2** | 教务在自己已熟悉的审批位置**看到这张单**，并能**通过 / 驳回（驳回必填原因）** | 不用学新系统，和批选课单一样 |
| **G3** | 通过后**当场生效**：学生课表、任课老师、同班同学立刻变成新班的 | 「换班」在门户上是立即看得见的 |
| **G4** | 学生能看到**进度与结果**（待审批 / 已通过 / 已驳回 + 原因） | 不用反复问 |
| **G5** | 每次审批有**留痕**（谁、何时、从哪个班改到哪个班） | 家长问得清、出事追得到 |

### 1.2 非目标（明确不做，避免范围漂移）

> ⚠ **v2 修订（2026-09-18，P6 改判）**：第一条非目标「**不做跨课程调班**」**已被校长 P6 改判推翻**（§19.0/§19.1）。 **以 §19 为准。**

- **不做跨课程调班**：只允许**同课程内换班**（`目标班.course_id == 现档案.course_id`）。跨课程＝换课程，涉及科目集整体变更与建档语义，**另立**（既有 `/course/change/request` 与 11 张历史单的处置见 §3.2 / §7.3）。
- **不做容量/名额截断**：`op.batch` **没有容量字段**（`openeducat_erp/openeducat_core/models/batch.py:30-36`，需求 7 §7-Q1 已实证）⇒ 只能展示"该班现有人数"，**不做自动限流**。
- **不做排课冲突预检**：调班只改归属，不比时间表；"目标班课节数"只作只读展示。
- **不做"即改即生效"**：校长明确要**审批**（外部同类系统里 Moodle 的组自选恰恰是"即选即入"，见 §14——**这是本设计对外部先例的有意偏离，理由 = 校长原话**）。
- **不做教师发起**：教师既不是申请人也不是审批人（只读现状）。
- **不动基座**：`openeducat_erp/` **只读**；**不改** `subject_registration.py`、**不改** `student.py`、**不改**任何基座视图/ACL。
- **不新建软件实体**：❌ 新模块 ❌ 新模型 ❌ 新表 ❌ 新 `op.batch` 字段 ❌ 新权限组 ❌ 新通知/审计通道。

---

## 2. 第 0 步①：先信 code-map

`docs/code-map.md` 逐条读后与本设计相关的锚点：

| 位置 | 内容 | 对本设计的含义 |
|---|---|---|
| `code-map.md:55` | `controllers/batch3.py`(900行)＝证书下载、申诉、请假、毕业论文、**选课**、会议、DMS | 既有 `/course/change/request` 就落在这个文件（`:213,258`），**新路由同族落点** |
| `code-map.md:56` | `controllers/roles.py`＝教师/教务侧；批次 4 A1 审批聚合：`/leave/approvals[/<id>]`、`/grievances/approvals[/<id>]`、`.../set_state`（**审批后经 edu.message 通知申请人**） | **审批聚合页 + 通知申请人的既有形态**，本设计照此 |
| `code-map.md:62` | `controllers/ledger.py` 用「教务/管理员门禁」 | 门禁写法先例 |
| `code-map.md:148` | 基座 `openeducat_core` 承载 `op.student.course`、`op.batch`、`op.subject.registration` | 三个承载物都在基座，**本设计第一优先是证明它们够用** |
| `code-map.md:161-165` | **权限四层**：`group_op_faculty` / `group_op_back_office_admin`（**基座源码里 imply `base.group_system`，本仓 2026-09-17 已解除**）/ `student_login_rule` | 所有权限结论必须与四层对齐（§10.4） |
| `code-map.md:245` | 约定第 3 条：**不建自定义组**；控制器用 `current_student()/current_faculty()/current_parent()` 判空分流，**不做组判断**；门禁型管理页用 `roles.privileged_staff()` | 学生侧与教务侧门禁一律照此 |
| `code-map.md:249` | 「新功能三件套：先写 `docs/plans/<功能>-design.md` 再动工」 | **本文件就是那个前置件** |
| `code-map.md:256-263` | 第 12 条硬约定：新增菜单/ACL **必须声明属于哪一层**；「看得见点不开」缺一即死角 | §10.4 逐条声明 |
| `docs/research/README.md:17-24` | 调研索引 | 按铁律 0 回引（§14），并如实报告**这一主题的调研空白** |

---

## 3. 第 0 步②：既有实现对照（逐条：查了什么 / 命令 / 命中 / 为什么不复用）

> 规矩（`dev-workflow.md:18-30`）：**「没找到」也要写清搜索范围与方式**；**不允许"我记得没有"**。
> 本节所有命令均**在本工作区实跑**（2026-09-18）；DB 读数**只读 SELECT**。

### 3.1 六路查重（模型 / 路由 / 关键词 / 菜单 / 种子 / 写库入口）

| # | 查了什么 | 命令 | 命中 | 结论 |
|---|---|---|---|---|
| 1 | 候选新模型 `edu.batch.change` / `EduBatchChange` / `batch_change_request` | `grep -rn "edu\.batch\.change\|EduBatchChange\|batch_change_request" --include="*.py" --include="*.xml" custom_addons/` | **0 命中** | 名字可用；但**本设计决定不新建**（§7） |
| 2 | 「调班 / 换班 / 转班 / 班级变更 / 换课 / 调课」全仓 | `grep -rn "调班\|换班\|转班\|班级变更\|换课\|调课\|batch_change\|batch.change" --include="*.py" --include="*.xml" custom_addons/` | **16 命中，逐条判定后 0 条是"调班"**：`edu_schedule/models/session_ext.py:381,648,689,716,730,803`＋`edu_portal/models/notify_pref.py:22-23`＋`roles.py:87,140` = **C-1 的"调课"**（改一节课的老师/时间，**与"学生在哪个班"无关**）；`edu_portal/models/registration.py:27,46,95,194`＋`controllers/enroll.py:280,336`＋`views/enroll.xml:182` = **换课/转班注释**（见 #3） | ✅ **"学生申请调班"确无实现** |
| 3 | 候选路由族 `change` / `transfer` / `swap` | `grep -rniE "@http.route\('.[^']*(change\|transfer\|swap)" --include="*.py" custom_addons/` | **仅 2 条**：`/course/change/request`（`batch3.py:213`）、`/course/change/request/save`（`:258`） | ⚠ **头号命中**：已有一条"课程变更申请"链路（§3.2） |
| 4 | 后台菜单/动作里有没有"调班 / 班级变更" | `grep -rn "课程变更\|调班\|班级变更" custom_addons/edu_portal/views/approval_backend.xml custom_addons/edu_portal/views/enroll.xml` | **1 命中且是"排除"**：`approval_backend.xml:229`「仅报课单（doc_type=subject_registration）；**课程变更单不进审批队列**」 | ⚠ **教务侧根本没有这条队列**（证据链的核心） |
| 5 | 种子/冒烟脚本有没有造过这类单 | `grep -rn "course_change\|change/request" scripts/*.py` | **8 命中**：`scripts/smoke_b_submit_faculty.py:118,124,128-133,413-414`（`S3 学生换课申请`）、`scripts/test_submit_flows.py:59,63,77`、`scripts/check_english.py:105`、`scripts/gen_icons.py:130` | ⚠ 库内那 11 张单**很可能是这两支冒烟脚本的产物**，不是真实申请 ⇒ 引用时必须标明（§3.2 / §17-2） |
| 6 | 「给学生定班」的**写库入口**有几处 | `grep -rn "op\.student\.course" --include="*.py" custom_addons/`（56 命中）逐条判定 | **写库（create/write）只有 1 处**：`edu_portal/models/registration.py:178-201`（`action_enroll_approve` 内建档 / 转班）；其余全是 `search/search_count` 只读 | ✅ 与需求 7 §8.4 **T3** 的口径一致：写库语义**唯一**，本设计**不得**制造第二处（§12） |

### 3.2 头号命中：既有「课程变更申请」是一条**批不动的半成品**（证据链）

> ⚠ **v2 修订（2026-09-18，P6 改判）**：②的失效注释**不止一处**（另见 `batch2.py:616`）、④-A 的取班口径**措辞需订正**、⑤的「不能把调班塞进 `course_change`」**已被推翻**（§19.7、§19.1）。 **以 §19 为准。**

**① 学生侧入口是活的**（有路由、有模板、有首页卡片）

- `batch3.py:213` `GET /course/change/request`（列表 + 折叠表单 + 统计卡）；`:258` `POST /course/change/request/save`。
- 模板 `views/batch3.xml:158-205`（`edu_course_change_request`；表单字段只有**目标课程** `course_id`，`views/batch3.xml:176-188`）。
- 学生首页有卡：`batch2.py:268-270`（`('course/change/request', '课程变更请求', …)`）、`:429`（FA 配色 `fa-exchange`）、`:132-135`（计数角标）、`:813`（学业组 `acad_hrefs`）；**且不在 `_DEFAULT_HIDDEN_CARDS`（`batch2.py:338-344`）里** ⇒ **对学生是可见的**。

**② 教务侧是关闭的**（两处硬编码排除 + 一处注释）

- `controllers/enroll.py:334-337`：`domain = [('doc_type', '=', 'subject_registration')]`，注释「**纯 course_change 换课单不进聚合（教务另有换课流程）**」；统计同样只数报课单（`:350-357`）。
- `views/approval_backend.xml:229`：`domain [('state','=','submitted'), ('doc_type','=','subject_registration')]` + 注释「课程变更单不进审批队列」。
- **但"教务另有换课流程"这句话在本仓查无实据**：`grep -rn "course_change\|课程变更" controllers/roles.py views/approval_backend.xml views/enroll.xml` **只回上述 1 条注释**（§3.1 #4）⇒ **那句话是一句失效的注释**。

**③ 库里 11 张单全部卡死（只读 SELECT）**

`SELECT doc_type, state, count(*) FROM op_subject_registration GROUP BY 1,2`：

| doc_type | state | 条数 |
|---|---|---|
| `course_change` | `submitted` | **11** |
| `subject_registration` | `approved` | **1** |

逐行（`SELECT id,name,student_id,course_id,batch_id,state,doc_type …`）：ids **10–19** 与 **72**。其中 ids 10–19 = `student_id 5`（王小明 / `stu@local` / `user_id 8`）、`course_id 13`、`batch_id 8`；id 72 = `student_id NULL`（**孤儿单，无学生**）、`course_id 18`、`batch_id 13`。

**④ 这批单在结构上是批不动的**（两条互相叠加的死路）

| 死路 | 机制（路径 + 行号） |
|---|---|
| **A. 归属不自洽** | `batch3.py:277-278` 建单时 `batch_id` 直接取**学生当前档案的班**，而 `course_id` 由表单另选 ⇒ 库里 10–19 全部满足 `batch(8).course_id = 18` 而 `course_id = 13`。既有审批动作开头的自洽校验（`registration.py:147-150`：`batch.course_id != course_id` 即 `ValidationError`）**会直接拒绝它们**。 |
| **B. 空科目会被拦** | 同一动作会**整体覆盖** `subject_ids`（`registration.py:190`）；而校长 2026-09-17 亲裁的防呆（`registration.py:161-171`）在「单无科目 ∩ 档案有科目」时**抛 UserError**。换课单从不写科目（`batch3.py:274-282` 无任何科目字段）⇒ 走 `action_enroll_approve` **必然死锁**。 |

**⑤ 为什么不复用（就本需求而言）**

- **既有 `course_change` 的语义是"换课程"**（表单只收 `course_id`；`batch_id` 是带出来的），**本需求是"换班级"**（课程不变）。**两者不是同一个动作**：换课程要连科目集一起换（否则学生挂着新课程名、读着旧课程的科目），换班级**绝不能碰科目**。⇒ **不能把调班塞进 `course_change` 这个值**，否则会把 11 张历史单的语义搅浑，且审批动作被迫分叉成一个"看情况"的大函数。
- **但它证明了"载体是对的"**：状态机（`draft/submitted/approved/rejected` + `submitted_at/approved_at/approved_by/reject_reason/applicant_note/doc_type` 五个自研字段，`registration.py:38-46`）、门户聚合页（`enroll.py:324-378`）、后台菜单（`approval_backend.xml:186-232`）、通知（`registration.py:100-128`）、审计（`registration.py:208-211`）**全都是现成的**。⇒ 结论：**复用载体，另立分型**（§7）。
- **既有那 11 张单的处置不在本设计范围**：本设计**不改它们、不批量审批、不删除**，只在 §7.3 给"唤醒条件"。

### 3.3 通知 / 留痕 / 审计三条通道（复用候选逐条判定）

| # | 通道 | 位置（行号） | 复用裁定 |
|---|---|---|---|
| 7 | **站内信引擎 `edu.message`** | 模型 `edu_portal/models/message.py:15-66`；**带偏好的统一入口** `edu_portal/models/notify_pref.py:51 _notify_event(event_key, recipient_user, body, sender_uid=None)`；事件白名单 `notify_pref.py:15-24` **现 7 类**（`leave_result / grade_result / assignment_graded / journal_reviewed / subject_reg_result / reimburse_result / session_change`） | ✅ **复用为主通道**。库内 `edu_message` 按 `event_key` 实查：`grade_result 697 / notice_publish 205 / subject_reg_result 155 / approval_escalate 62 / leave_result 24 /（空）11` ⇒ **155 行已有真实数据**，不是纸面能力 |
| 8 | **关键操作审计 `edu.audit.log`** | 模型 `edu_portal/models/audit.py:15-41`（`user_id/action/model/res_id/res_name/detail`，`_log()` **失败只告警、绝不阻断业务事务**）；查询页 `/edu/audit`（`roles.py:1406`），门禁 `privileged_staff()`（`roles.py:154`） | ✅ **复用**：写 `action='调班提交'` / `'调班审批'`。⚠ **必改两处标签表**：`roles.py:72` 与 `roles.py:125` 是**同名重复定义**的 `_AUDIT_MODEL_LABELS`（后者生效），两处都要加 `'op.student.course': '学生课程档案'`，否则模型列会落到中文兜底「**其它记录**」（`roles.py:112-118` 的兜底逻辑）。库内现 **1434** 行审计 |
| 9 | **字段级留痕 `mail.thread`** | ① `openeducat_erp/openeducat_core/models/student.py:28` `_inherit = "mail.thread"`、`:34 batch_id … tracking=True`；② 机制 `mail/models/mail_thread.py:632 _track_subtype`（**默认 False ⇒ 只记录、不通知**）、`:644 _message_track`、`:676` 判定分支 | ✅ **复用为零成本**（字段已 `tracking=True`）。⚠ **但落地量未证**：`mail_tracking_value` join `mail_message` 且 `model='op.student.course'` = **0 行**（§17-3）。**C-1 已有同样教训**（其 §9.3 反例原文：「❌ 只读代码就声称『留痕已生效』」） |
| 10 | **同型先例：C-1 已落地的"变更通知"** | `edu_schedule/models/session_ext.py:392 IMPACT_EVENT_KEY='session_change'`、`:670 _notify_session_change()`、`:790 action_notify_session_change()`；事件已登记 `notify_pref.py:23`；真机冒烟 `tests/smoke/c1_impact_notify.py` 已存在 | ✅ **必须复用同一套口径**（校长交办原文：「请去读 `docs/plans/session-change-impact-design.md` 并复用同一套通道口径，不要另造」）。本设计**不新增通道**，只在 `NOTIFY_EVENTS` 决定"新 key 还是复用 key"（§16 P4） |
| 11 | **同型先例：成绩变更留痕 `edu.grade.history`** | `registration.py:357-392`（`_name='edu.grade.history'`）；**唯一入口** `edu_apply_marks`（`:394-425`，用 `with_context(edu_marks_entry=True)` 声明"本次写入来自受管入口"） | ⚠ **不直接复用（对象不同）**，但**必须照它的口径**：① **唯一入口才留痕**；② 用 context 标记而不是调用栈扫描（`:411-412` 注释记着 t34→t42 的教训）。⇒ 调班的写库点**只能有一个**，且必须显式声明 |
| 12 | **邮件通知（基座自带）** | `openeducat_erp/openeducat_core/models/subject_registration.py`（`mail.thread` 已挂，但**未覆写 `_track_subtype`**）；**基座无 `notify_user()` 同类实现**（那是 `openeducat_timetable` 的，`timetable.py:418-480`） | ⚠ **不作为主通道**：本仓既有审批结果一律走站内信（`registration.py:123-128` / `leave` 同款）。**不改**基座、不新增邮件模板 |

### 3.4 「没找到」的，也要写清范围（本节的负结论）

| 负结论 | 搜索范围与方式（原样可复现） |
|---|---|
| **全仓没有"学生申请调班"的任何实现** | ① `grep -rn "调班\|换班\|转班\|班级变更\|batch_change" --include="*.py" --include="*.xml" custom_addons/`（16 命中逐条判定，**0 条相关**，§3.1 #2）；② `grep -rniE "@http.route\('.[^']*(change\|transfer\|swap)" --include="*.py" custom_addons/`（**仅 2 条换课路由**）；③ 通读 `code-map.md` §4 全部 `edu_*` 段落与 §5 路由速查（`:217-239`）逐行核对；④ 读 `docs/plans/enroll-v2-design.md` 全文（428 行）、`docs/plans/class-batch-management-design.md` 全文（700 行） |
| **全仓没有"班级门户页"路由** | 需求 7 §3.1 #2 已实跑（`@http.route` 全量搜 `class\|batch` = 0）；本设计复核一致 ⇒ 新路由族 `/batch/change/request` **无冲突** |
| **全仓没有第二套"给学生定班"的写库入口** | `grep -rn "op\.student\.course" --include="*.py" custom_addons/` 56 命中逐条判定 ⇒ **create/write 仅 `registration.py:178-201` 一处**（§3.1 #6） |
| **`op.student.course` 至今零自研扩展** | `grep -rn "_inherit = .*op\.student\.course\|op\.student\.course.*_inherit" --include="*.py" custom_addons/` = **0 命中** ⇒ **没有任何 write() 覆盖钩子**（改 `batch_id` 不会触发隐藏副作用；反过来也说明**没有现成的留痕埋点**） |
| **教务侧没有任何"课程/班级变更"审批队列** | §3.1 #4 的唯一命中是**排除语句**；`approval_backend.xml` 的「教务审批」根菜单下只有 请假 / 申诉 / 选课 三条（`:186-232` 段内） |
| **Odoo 19 社区版没有可装的"审批流"模块** | ① 容器内核心 addons：`ls /usr/lib/python3/dist-packages/odoo/addons/ \| grep -c approv` = **0**（全量 685 个 addons）；② 库内 `SELECT count(*) FROM ir_module_module WHERE name LIKE '%approv%'` = **0** ⇒ **企业版 Approvals（`approval.request`）在本仓不可用**，"能装不写"这一站在此**落空** ⇒ 复用仓内既有"学生申请→教务审批"形态是正解（§7） |

---

## 4. 第 0 步③：设计摘要落点

✅ 本文即 `docs/plans/class-change-request-design.md`（第 4 步产出物）：
**既有实现对照在 §3**、**裁定在 §7**、**生效语义在 §8**、**审批人在 §9**、**入口/路由/权限在 §10**、**通知留痕在 §11**、**与需求 7 的关系在 §12**、**边界与数据流在 §13**、**读参考在 §14**、**验收在 §15**、**拍板项在 §16**。

---

## 5. 第 0 步④：升级会不会动业务数据

> 依据 `docs/dev-workflow.md:33-46`（`finding-F5`）：`data` 每次 `-u` **重放**，`demo` 只在安装且开启演示数据时装载。

**实跑读数（2026-09-18）**：`custom_addons/edu_portal/data/` 只有 **3 个文件**（`fee_categories.xml` / `menu_reachability.xml` / `timetable_params.xml`），全目录 `grep -rn "<function\|_load_demo\|create("` **仅 1 命中**，且是**配置类**：

| 命中 | 写的是什么 | 判定 |
|---|---|---|
| `data/menu_reachability.xml:9` `<function model="ir.ui.menu" name="edu_apply_reachability_groups"/>` | **菜单 `group_ids`**（文件内注释自述「幂等、缺模块不报错」） | ✅ 可接受（配置类，非业务表） |

`__manifest__.py` 的 `data` 列表在 `:33-63`，**无任何写业务表的 `<function>`**；`demo` 键**不存在**（全仓 12 个模块 `demo` 一律 `None`）。

**与本研究直接相关的结论**：

1. ⇒ **硬约束**：若实施时在 `edu_portal/data/` 新增文件，**只允许写配置类记录**（`ir.ui.menu` / `ir.actions` / 视图 / ACL / `ir.config_parameter`）；**任何写 `op.subject.registration`、`op.student.course`、`op.batch` 的 `<function>` 一律禁止进 `data/`**。
2. ⇒ **预期 `data/` 业务副作用 = 0**：G1/G4 是门户只读+一次建单（走控制器代码）、G2/G3 是审批动作（走模型方法）、G5 是审计与 chatter。**不新增 `ir.cron`**（没有定时任务需求）⇒ `data/` 变动预期为零，`-u edu_portal` 的业务数据副作用 = 0。
3. ⚠ **必须点名的既有"升级会写业务表"的一处（不是 `data/`，但同样每次 `-u` 触发）**：`edu_portal/models/registration.py:57-89` 的 `_infer_doc_type()` 挂在 `_auto_init()` 上，**每次 `-u edu_portal` 都会跑一条 UPDATE**：把「有科目集却 `doc_type ≠ subject_registration`」的行**改成 `subject_registration`**。
   ⇒ **对本设计的硬约束**：**调班单不得携带任何科目集**（`compulsory_subject_ids` / `elective_subject_ids` 必须为空）。否则一次 `-u edu_portal` 就会把调班单的类型**静默改写**成选课单，之后被 `/registrar/subject/approvals` 收进队列、被 `action_enroll_approve` 覆盖科目——**这是一条静默数据损坏路径**。这条约束恰好与 §8 的"审批绝不碰 `subject_ids`"同向，**互相加固**。
4. ⚠ **如实点名邻近风险（与本设计无关但同类）**：`edu_life/data/demo_life.xml` 末尾的 `<function model="edu.checkin.type" name="_load_demo_records"/>` 按"今天"滚动补写业务表 `edu.checkin.record`（`docs/dev-workflow.md:43-46,103-127`，F5，t12 修复中）。⇒ 本设计验收若含**计数型判定**，**先按 `dev-workflow.md` 陷阱 1 探活**：`ls -lt /tmp/edu19_upgrade.*.log | head -3` 确认最近没跑过 `-u edu_life`。

---

## 6. 第 0 步⑤：演示数据策略（一句话）

**本设计不新增任何业务演示数据；但本地"同课程只有 1 个班"，因此真机验收必须现场造 1 个班并现场还原。**

- **为什么必须造**（只读 SELECT 实况）：学生 `5`（王小明 / `stu@local`）的**唯一 running 档案** = `op_student_course.id 9`（`course_id 18` 预备科 / `batch_id 8` / `term 1`）；而 `op_batch` 里 **`course_id = 18` 的班只有 id 8 这一个**（其余 16 个班分属课程 14/16）。⇒ **没有"同课程的第二班"可换**，不造就**造不出合法载体**。
  （旁证：`op_student_course` 全表 4 行 —— id 9 = 学生 5 在读；ids 10/11/12 = 学生 7/8/9，**均 `state='finished'` 且 `batch_id` 为空**，不可用作载体。）
- **放哪**：`scripts/seed_batch_change_demo.py`（仓库既有惯例：`scripts/seed_*.py` **必须幂等**），建 1 个 `course_id=18`、`active=True` 的班，名称**前缀一律【演示】**（`code-map.md:247` 第 5 条硬约定），例：`预备科 · 2026级B【演示】`。
- **怎么清理**：清理分支写在**同一脚本的 `--clean`**（按【演示】前缀 `unlink` 并**断言计数归零**）；验收末尾必须断言 `leftover = 0`（同型先例：`checkin-merge-report` 的「构造 → 断言 → 还原」三段模板）。
- **禁止**放进 `data/`（理由见 §5.1）。
- ⚠ **归档状态不进种子**：种子只建 `active=True` 的班；"已停用目标班"这一否定用例由验收步骤**现场产生、现场恢复**（§15 V9）。

---

## 7. 载体裁定（三选一）+ 理由 + 收口触发条件

> ⚠ **v2 修订（2026-09-18，P6 改判）**：**本章整体被 §19.1 重做**：本次推荐**改判**为「修好既有换课链路并收口成唯一入口」，不新增 `doc_type`。§7.4 的收口触发条件 B1–B5 由 §19.8 的 C1–C4 接续（C2 即原 B2）。 **以 §19 为准。**

### 7.1 三个候选的代价与后果（逐条）

| 候选 | 做法 | 代价 | 后果 |
|---|---|---|---|
| **A. 复用 `op.subject.registration` 加一个 `doc_type`** | 新增第三个值 `('batch_change', '班级变更')`（`registration.py:29-32` 的 `_DOC_TYPE` 由 2 值扩 3 值）+ 新门户路由族 + 不碰科目的新审批动作 | ① **1 行 Selection 扩展**；② 1 个新模型方法（约 40 行）；③ 2 条学生路由 + 1 段模板；④ 审批聚合页加 1 个 `filterby` 分支；⑤ 后台加 1 个按钮 + 1 条菜单 domain 放宽 | ✅ **零新表、零新概念**；状态机/单号/通知/审计/审批页/后台菜单**全部继承**；与既有 11 张换课单**语义不混**（不同 doc_type）；与需求 7 的 T3 口径**相容**（写库仍收敛在一处） |
| **B. 新建 `edu.batch.change.request`** | 新模块/新模型/新表 | ① 新模块 + manifest + ACL + 视图 + 控制器 + 模板；② **要重造**一套状态机、单号序列、审批聚合页、后台菜单、通知事件、审计埋点；③ 要与 `op.batch`、`op.student.course`、`op.subject.registration` 三方对接 | ❌ **立刻制造本仓最忌讳的"同类模型第二套"**（`docs/audit/feature-overlap-audit.md` 的 8 类重叠：打卡×2、评估×2、岗位×2 都是这么长出来的）；❌ **直接触发需求 7 的 T3**（"出现第二个给学生定班的写库入口"）；❌ 学生侧会同时存在两张"我的申请"列表 ⇒ 用户可见的重复 |
| **C. 不新建申请实体，只做"申请改 `op.student.course.batch_id`"的审批动作** | 在 `op.student.course` 上加 pending 字段对（如 `pending_batch_id` / `pending_state`），门户直接写、教务批 | ① 要在**基座模型上加字段**（本仓"基座只读、只在 `custom_addons` 继承"的边界内可行，但把待审态挂到**事实源**上）；② `op.student.course` **没有 rejected 态**（`student.py:39-41` 只有 `running/finished`）⇒ 驳回无处安放；③ 没有单号、没有学生侧进度页、没有申请时间线 | ❌ **不能满足校长原话的"申请→审批→可驳回"**；❌ 把"未决的意愿"混进"已成事实的学籍归属"，是全仓**唯一事实源**被污染；✅ **但它的一半是对的**：**生效的写目标确实就是 `op.student.course.batch_id`**——这一半被 A 吸收（§8） |

### 7.2 裁定

| 能力 | 裁定 | 承载物（替代路径） | 扩展方式 |
|---|---|---|---|
| **G1 学生提调班申请** | **复用** | `op.subject.registration`（`doc_type='batch_change'`） | 新增学生路由族 `/batch/change/request[/save]` |
| **G2 教务审批** | **复用** | 同一模型 + 同一审批聚合页（`/registrar/subject/approvals` 加 `filterby` 分支）+ 后台「教务审批」菜单 | 新增 `action_batch_change_approve()`；后台加 doc_type 作用域按钮 |
| **G3 生效** | **复用（写库语义收敛到一处）** | `op.student.course.batch_id`（**当场改写**，§8） | 新方法**只写 `{'batch_id': …}`**，绝不碰 `subject_ids`；**与 `action_enroll_approve` 的 `registration.py:193-195` 共用同一套前置校验口径** |
| **G4 学生看进度** | **复用** | 学生侧列表页（同页 chips/筛选） | 复用 `_SUBJREG_STATE_LABEL`（`enroll.py:27-30`） |
| **G5 通知 + 留痕** | **复用** | `edu.message._notify_event` + `edu.audit.log` + `mail.thread` | 见 §11（**不新增通道**） |
| **既有 11 张 `course_change` 单** | **不动（明确不做）** | — | 见 §7.3 |

**一句话**：**能复用不新建 —— 而且这里不只是"能复用"，是"已经有一半建好了，只是批不动"。**

### 7.3 明确不做 + 唤醒条件

| 明确不做 | 理由 | 唤醒条件 |
|---|---|---|
| **不改 `doc_type='course_change'` 既有语义、不批量处置那 11 张单** | 它们是"换课程"（`course_id` 变）不是"换班级"；且 `batch_id` 与 `course_id` 不自洽（§3.2 ④-A），**任何自动处置都会猜错学生意图** | **机会型**：另立"换课/学籍异动"任务时，一并设计「选课程 + 选班级」成对的归属变更单，并决定 11 张单是**作废（`state='rejected'` + 原因）**还是**引导重提** |
| **不做跨课程调班** | 跨课程 = 换课程 + 换科目集，与"换班"是两种业务；混进来会让审批动作必须判断"要不要换科目"，正是 §3.2 ④-B 的死锁来源 | **里程碑型**：若校方提出"学生要连课程一起改"，**另立设计**（同 §7.3 上一行的机会型触发） |
| **不给 `op.student.course` 加任何字段** | 它是学籍归属的**唯一事实源**；pending 态属于**单据**不属于事实源（候选 C 的教训） | 不设（除非出现"一次申请涉及多条档案"的需求） |
| **不覆写 `op.student.course.write()`** | 该模型至今**零自研扩展**（§3.4）；覆写会命中所有写入路径（含基座后台、导入脚本），代价与收益不成比例 | **里程碑型**：若某天要"任何来源改归属都必须留痕"，则用 `ir.rule`/`write()` 统一收口，**另立设计** |

### 7.4 收口触发条件（`dev-workflow.md:62` 的"新建并存"栏；本设计裁定为复用，故列为**复发触发条件**）

| 编号 | 触发条件（可观察、可判定） | 触发后必须做什么 |
|---|---|---|
| **B1** | `_DOC_TYPE` 出现**第 4 个值**（`grep -n "_DOC_TYPE" -A 6 custom_addons/edu_portal/models/registration.py`） | **停手**：不再往 Selection 里塞类型，改为"归属变更单"独立字段（`change_kind`）+ 目标课程/班级成对建模 |
| **B2** | 出现**第二个"给学生定班"的写库入口**（今天唯一 = `registration.py:178-195`；判据 = 新增 `op.student.course` 的 `.create(`/`.write(` 调用点） | **停手**，回第 0 步查重（**这条与需求 7 §8.4 T3 是同一条**，§12） |
| **B3** | 出现**第二条学生侧"归属变更"路由**（今天 = `/course/change/request` + 本设计 `/batch/change/request`） | **停手**：两条应合并成一个"学籍异动申请"页面 + 一个 `change_kind` 选择器 |
| **B4** | 通知事件出现**第 3 个"选课/归属"类 key**（今天 = `subject_reg_result`；本设计若新增即第 2 个） | **合并**为一个 `enroll_result` 事件，避免 `/my/notify` 出现同义开关多条（判据 = `grep -n "NOTIFY_EVENTS" -A 12 custom_addons/edu_portal/models/notify_pref.py` 的行数） |
| **B5** | `op.batch` 的**归档语义**被需求 7 落地改变（`op.batch.active` 开始被真实使用） | **必须复验**"申请提交后目标班被停用"这一竞态（§15 V9），并决定是"审批时拒绝 + 提示"还是"自动改为候补" |

---

## 8. 生效语义（**最关键**）

> ⚠ **v2 修订（2026-09-18，P6 改判）**：**本章整体被 §19.2 重做**：v1 结论「只改 `batch_id`、绝不碰 `subject_ids`」只在**只换班**时成立；允许换课程后必须**原子地**同时写 `course_id` + `batch_id` + `subject_ids` + `academic_term_id`（§19.2.2）。§8.3 的 R1–R7 仍然有效；换课程新引入的风险见 §19.2.2 #3/#4 与 §19.3 的 P8。 **以 §19 为准。**

### 8.1 两种口径的对后果清单（**逐项给事实，不凭感觉**）

| 影响对象（路径 + 行号） | **口径一：当场改写 `batch_id`** | **口径二：新建档案行 + 旧行置 `finished`** |
|---|---|---|
| **学生归属事实源** `op.student.course.batch_id`（`student.py:34`） | 同一行 `batch_id` 由 A → B | 新行 (S,C,B)，旧行 (S,C,A) 保留 |
| **字段级留痕** `batch_id` 的 `tracking=True`（`student.py:34`） | ✅ **自动**产出 old(A) → new(B) 一条 `mail_tracking_value`（经 `mail/models/mail_thread.py:644 _message_track`） | ❌ **零字段变更** ⇒ 自动机制**不产生任何留痕**（要靠具名 `message_post` 手写） |
| **唯一约束** `unique(student_id,course_id,batch_id)`（`student.py:50`） | ✅ 不新增行，恒满足；**A→B→A 可往返** | 🔴 **换回原班直接撞约束**：旧行 (S,C,A) 仍在（只是 `finished`），再建 (S,C,A) → `IntegrityError`。⇒ **不可逆**。这正是校长场景的风险（演示填错要改回） |
| **学生侧"我的档案"渲染** | ✅ 仍只有 1 行，显示"在读 · 新班" | 🔴 旧行 `state='finished'` 会渲染成 **「已结业」**（`enroll.py:305-313`：`'state': '在读' if sc.state == 'running' else '已结业'`）⇒ **把"换过班"显示成"毕业了"** |
| **课表 / 任课老师 / 同班同学** | ✅ 立即换（`main.py:47 student_course()`、`study.py:30-40/43-57/122-131`、`batch2.py:1930-1931`、`batch1.py:320`） | ⚠ 也立即换（`student_course()` 取 running），但**多出一行幽灵"已结业"档案** |
| **旧班历史考勤 / 教师名单 / 评教名单** | 🔴 **旧班立刻看不到他**：`roles.py:477` 按 `[('batch_id','=',bid)]` 取名单、`roles.py:368`、`edu_eval/controllers/eval_portal.py:56-57` 同款 ⇒ **未点完的旧班点名表里他会消失** | 🔴 **同样如此**（两条口径在这一项上**没有区别**） |
| **已录成绩**（`op.exam.attendees` / `op.result.line`） | ✅ 不动、不丢（成绩行挂在"学生 × 考试"上，不随档案行走） | ✅ 不动、不丢 |
| **旧班课节**（`op.session.batch_id`，库内 288 节 100% 挂班） | ✅ 不动（课节属于班，不属于学生） | ✅ 不动 |
| **已批选课单** `op.subject.registration.batch_id`（`subject_registration.py:35`） | ⚠ 单据仍指**旧班**（单据=**申请时快照**，本就不该是当前态）；库内 12 张单 100% 挂班 | ⚠ 同上 |
| **`op_session_op_student_rel`**（现 **0 行**，`student_ids` 为空） | ⚠ 无影响（C-1 的 `_reminder_users` 走"按 batch 回退"，换班后**自动**改发新班） | ⚠ 同上 |
| **可逆性 / 学生可再次申请** | ✅ 反向申请即回原班 | 🔴 **不可逆**（约束撞车） |
| **与既有写库语义一致性** | ✅ **与 `registration.py:193-195` 完全一致**（那处就是 in-place `write({'batch_id': …})`） | ❌ 全仓**无先例** |

### 8.2 结论

> **口径一：当场改写 `op.student.course.batch_id`；不新建档案行、不把旧行置 `finished`。**

三条决定性理由（按强度排序）：
1. **口径二不可逆**：`unique(student_id,course_id,batch_id)`（`student.py:50`）使"换回去"永久失败 —— 而校长的场景**恰恰是"填错了要改"**，改错的概率远高于一次到位。**不接受不可逆的设计。**
2. **口径二语义污染**：`state='finished'` 在本仓学生侧渲染为**「已结业」**（`enroll.py:309`）；把"换班"显示成"毕业"是**用户可见的错误**，且 `state` 只有两个值（`student.py:39-41`）**没有第三个可用状态**。
3. **口径一无先例成本**：它与本仓**唯一**的既有定班写库语义同款（`registration.py:193-195`），并**白拿** `tracking=True`（`student.py:34`）的字段级留痕；口径二则要**手写**一套具名留痕（照 `timetable.py:569-607 _log_student_ids_change` 的口径），成本更高而收益（"旧班历史归属"）**已经由 chatter 覆盖**。

### 8.3 风险（**必须写进实施任务的验收里**）

| # | 风险 | 事实依据 | 处置（写进实现要求） |
|---|---|---|---|
| **R1** | **旧班历史名单立刻丢人**：换班后，旧班教师/考勤/评教按 `batch_id` 取的名单里**不再有他** | `roles.py:477`、`:368`、`eval_portal.py:56-57` | ① 在**审批详情页**向教务明示「换班后该生将从原班的点名表/评教名单中移除」；② 验收里**必须**有一条断言把这个后果读出来（§15 V7） |
| **R2** | **唯一约束撞车**：若已存在同 `(student, course, 目标班)` 的另一行（如需求 7 的教务直接分班造出来的），in-place write 会 `IntegrityError` | `student.py:43-51`（3 条约束） | 审批动作**必须先预检**：同 `(student_id, course_id, 目标 batch_id)` 是否已有行；有则**拒绝 + 人话文案**，引导教务先处理那一行 |
| **R3** | **`roll_number` 冲突**：`unique(roll_number, course_id, batch_id)` 在 `roll_number` 非空时，换到目标班可能与同班他人撞号 | `student.py:47-48`；本地 4 行 `roll_number` **均为 NULL**（Postgres 视 NULL 互不相同 ⇒ 本地不触发） | 预检同上的第二条：目标班内是否已存在同 `roll_number` 的**其他人**；有则拒绝 + 提示先改学号 |
| **R4** | **改错档案**：`student_course()`（`main.py:47-53`）取 running 时**只有 `limit=1`、没有 `order`** ⇒ 学生若有多条 running 档案（多课程），谁是"当前"是**不确定的** | `main.py:47-53` 实读 | ① 申请表单**必须显示"将变更哪一条档案"的完整标识**（课程 + 现班）；② 服务端按**显式传入的 `op.student.course` id** 定位并按 `student_id` 校验归属，**不得**靠 `limit=1` 猜 |
| **R5** | **目标班被停用（TOCTOU）**：申请提交后、审批前，教务把目标班归档 | 需求 7 §7-Q7 ⑤（归档 = 退出所有选班下拉，`enroll.py:93-95` 已显式过滤） | 审批动作**二次校验 `batch.active`**；不通过则拒绝并提示重选（§15 V9） |
| **R6** | **静默改写 doc_type**：若调班单带了科目集，`-u edu_portal` 会把它的 `doc_type` 改成 `subject_registration` | `registration.py:57-89 _infer_doc_type()` 挂在 `_auto_init` | **硬约束**：调班单**不得携带科目集**；验收加一条断言（§15 V10） |
| **R7** | **审批后"当前在哪班"与"选课单说的班"不一致** | `op.subject.registration.batch_id` 是快照 | 明示口径：**单据显示的是申请时的目标，当前归属一律以 `op.student.course` 为准**（写进审批详情页脚注 + 学生列表页） |

---

## 9. 审批人

**先说事实**：校长说「让**管理员**通过」。本仓"管理员"有两种含义（`code-map.md:161-163`、`perm-model.md` 四层）：

| 层 | 组 | 在本仓的含义 |
|---|---|---|
| 系统管理员 | `base.group_system` | 开发者/超管（唯一能进系统设置/应用/模块装卸） |
| **教务（Registrar）** | `openeducat_core.group_op_back_office_admin` | 业务口径责任人 —— `code-map.md:258` 明确「**课程·科目·批次·课节** / 考试与成绩 / 财务 / **审批**」属教务组 |

**建议（默认值）**：

| 判据 | 值 | 理由 |
|---|---|---|
| **门禁函数** | `roles.privileged_staff()`（`roles.py:154-160`＝教务组 **或** system 组） | ① 与全仓"门禁型管理页"口径一致（`code-map.md:245`）；② 与需求 7 §13 **P2**（"在学生页面给学生分班"**建议只有教务**）**同答** —— 否则会出现"教务能直接分班、却不能批学生的调班单"的荒谬组合 |
| **是否带 `current_faculty()`** | **不带**（与选课审批**故意不同**） | 选课审批的门禁是 `current_faculty() or privileged_staff()`（`enroll.py:328,437,472`）—— 因为"挂科目"属**教学执行**层；而调班改的是**学籍归属**（属业务管理层）⇒ 按四层收紧到教务。**这是刻意的差异，必须在实现里写注释，防止后人"对齐"回去** |
| **学生在哪一类审批里看到** | 教务/超管在门户聚合页看到；**教师看不到调班单** | 页面按 `doc_type` 分可见集（§10.3） |

⚠ **必须同时满足的"看不见点不开"四件套**（`code-map.md:262`）：菜单 `groups` + 模型 ACL + `ir.rule` + **控制器判据**。本设计**不新增 ACL**（模型 ACL 已有）；
⚠ **实施时必须断言**「教务组 implied 传递闭包**不含** `base.group_system`」（`code-map.md:163` 判据，2026-09-17 已解除，改基座/重装可能回弹）。

---

## 10. 学生侧入口 · 路由与动作清单 · 权限四层

> ⚠ **v2 修订（2026-09-18，P6 改判）**：§10.1 裁定 (b)「新增 `/batch/change/request` 路由族」与 §10.2 的 #1/#2/#3/#5 被撤销（改为修既有 `/course/change/request`）；§10.3 可见矩阵与 §10.4 四层声明**仍然有效**（含审批人只有教务 + 超管）。 **以 §19 为准。**

### 10.1 学生侧入口裁定

| 方案 | 说明 | 裁定 |
|---|---|---|
| (a) 并入 `/course/change/request` 页面，加"变更类型"选择器 | 复用同一条路由 | ❌ **不取**：会静默改变一条**已在学生首页可见**的既有页面的语义（用户可见变化），且要把既有 11 张单的语义一起解释 |
| **(b) 新增兄弟路由族 `/batch/change/request`** | 与 `/course/change/request` 同载体、同状态机、同审批页、同通知审计；两页互放入口 | ✅ **取**：概念只有一套（"学籍归属变更申请"），**动作不同则页面不同**；既有页面零改动 |
| (c) 挂在 `/student/profile`（档案页）里 | 档案页已有班级 chip | ⚠ **作为补充入口**：档案页"我的班级"卡旁加一个「申请调班」链接（**不新增页面**），主入口仍是 (b) |

**入口落点（实现清单）**：
1. **学生首页卡片**：进 `_YONGYUE_CARDS` 卡片引擎（`batch2.py:268` 旁）与 `FA_HOME_ICONS`（`:429` 旁）、`acad_hrefs`（`:813` 旁）；**不得**加入 `_DEFAULT_HIDDEN_CARDS`（`batch2.py:338-344`）。
2. **档案页**：`batch1.py:313-323` → `views/batch1.xml:588` 的班级 chip 旁加链接（只加链接，不改 chip 口径）。
3. **`/subject/registration`「我的申请」页**：列表自然包含调班单（同模型），无需新页；顶部"我的已选科目"横卡口径不变。
4. **图标**：按 `code-map.md:250` 铁律，统一由 `scripts/gen_icons.py` SPEC 生成（**不手画**）；若走 FA 兜底则须同步移除另一源（`enroll-v2-design.md:236-240` 已记过一次双源教训）。

### 10.2 路由与动作清单（本次设计的**全部**新增面）

| # | 类型 | 路径 / 名称 | 归属文件（预期） | 权限层（四层） | 复用 / 新增 |
|---|---|---|---|---|---|
| 1 | **门户路由（学生）** | `GET /batch/change/request` | `edu_portal/controllers/batch3.py`（与 `/course/change/request` **同文件同族**） | 门户（`base.group_portal`） | **新增** |
| 2 | **门户路由（学生，写）** | `POST /batch/change/request/save`（csrf） | 同上 | 门户 | **新增** |
| 3 | **门户路由（学生）** | `GET /batch/change/request/data/<int:rid>`（可选，详情片段） | 同上 | 门户（仅本人） | **新增（可选）** |
| 4 | **模型方法** | `action_batch_change_approve()` | `edu_portal/models/registration.py` | —（门禁在控制器/按钮） | **新增（约 1 个方法）** |
| 5 | **模型扩展** | `_DOC_TYPE` 加 `('batch_change', '班级变更')` | `registration.py:29-32` | — | **改（1 行）** |
| 6 | **模型方法（改）** | `_notify_student()` 按 `doc_type` 分文案（`registration.py:100-128`） | 同上 | — | **改** |
| 7 | **审批聚合页** | `/registrar/subject/approvals` 加 `filterby=batch` 分支（`enroll.py:326-378`）；**统计与 domain 按身份分可见集** | `edu_portal/controllers/enroll.py` | 教务 + 超管（调班单） | **改** |
| 8 | **审批写路由** | `/registrar/subject/approvals/<rid>/set_state` 按 `rec.doc_type` **分派 + 分门禁** | 同上（`:433-456`） | 见 §9 | **改** |
| 9 | **后台按钮** | 新增 `action_batch_change_approve` 按钮，`invisible="doc_type != 'batch_change'"`；既有按钮加 `invisible="doc_type == 'batch_change'"` | `views/approval_backend.xml`（继承基座表单视图） | 教务 + 超管 | **新增（不改既有按钮文案）** |
| 10 | **后台菜单（改）** | 「选课审批」动作 domain 放宽为 `[('state','=','submitted'), ('doc_type','in',('subject_registration','batch_change'))]` | `views/approval_backend.xml:223-231` | 教务 + 超管 | **改（1 行 domain）** |
| 11 | **模板** | 学生页 + 审批详情页（`t-call="edu_portal.edu_page"`） | `views/batch3.xml` / `views/enroll.xml` | — | **新增** |
| 12 | **通知** | 事件 key：复用或新增（§16 **P4**） | `models/notify_pref.py:15-24` | — | **条件性改** |
| 13 | **审计标签（必改）** | `_AUDIT_MODEL_LABELS` 加 `'op.student.course': '学生课程档案'` | `controllers/roles.py:72` **与** `:125`（**同名重复定义，两处都改**） | — | **改（2 处）** |
| 14 | **演示种子** | `scripts/seed_batch_change_demo.py`（幂等 + 【演示】 + `--clean`） | `scripts/` | — | **新增（验收用）** |
| 15 | **冒烟** | `tests/smoke/batch_change_smoke.py`（§15 逐条落地） | `tests/smoke/` | — | **新增** |

**明确不新增**：❌ 新模块 ❌ 新模型 ❌ 新表 ❌ `op.student.course` / `op.batch` 新字段 ❌ 新权限组 ❌ 新通知/审计通道 ❌ 新软删机制 ❌ 新 `ir.cron`。

### 10.3 各角色可见矩阵（默认）

| 动作 | 学生 | 家长 | 教师 | 教务 | 超管 |
|---|---|---|---|---|---|
| 提交调班申请 | ✅ 仅本人 | ❌ | ❌ | ❌ | ❌ |
| 看自己的申请与进度 | ✅ 仅本人 | ❌（P3） | ❌ | ✅ 全部 | ✅ 全部 |
| **看到调班单队列** | ❌ | ❌ | ❌ | ✅ | ✅ |
| 看到选课单队列（既有） | ❌ | ❌ | ✅ | ✅ | ✅ |
| **审批调班单** | ❌ | ❌ | ❌ | ✅ | ✅ |
| 审批选课单（既有） | ❌ | ❌ | ✅ | ✅ | ✅ |
| 读审计 `/edu/audit` | ❌ | ❌ | ❌ | ✅ | ✅ |

> 一个页面（`/registrar/subject/approvals`）两种可见集：**教师看到的是选课单，教务看到的是选课单 + 调班单**；服务端按 `rec.doc_type` 再做一次门禁（**不能只靠前端隐藏**，`code-map.md:262`「看得见点不开」判据）。

### 10.4 权限四层声明（`code-map.md:256-263` 硬约定：新增 ACL/菜单必须声明层级）

| 落点 | 层 | 写法定式 | 为什么 |
|---|---|---|---|
| 学生路由族 `/batch/change/request*` | **门户**（`base.group_portal` + 身份函数分流） | `current_student()` 判空 → `303 /my/home`；**不做组判断**（`code-map.md:245`） | 与 `/subject/enroll`（`enroll.py:58-60`）、`/course/change/request`（`batch3.py:216`）**完全同款** |
| 审批聚合页（调班单部分）与 `set_state` 分派 | **教务 + 超管** | 控制器判据 `privileged_staff()`（`roles.py:154`） | 学籍归属属业务管理层（§9） |
| 后台按钮与菜单 domain | **教务 + 超管** | 菜单沿用既有 `menu_edu_approval_root`（`groups="base.group_user"`，`approval_backend.xml:234`）+ 控制器判据二次把关 | **不改现有菜单组**，避免"看得见点不开" |
| **ACL** | — | **零新增**：`op.subject.registration` 的门户写经控制器 `sudo()`（既有惯例，`registration.py:151`）；`op.student.course` 的写经 `sudo()`（同）；学生**不直接**获得任何写 ACL | 不扩权 |
| **红线复核** | — | 实施时**必须**断言「教务组 implied 传递闭包**不含** `base.group_system`」（`code-map.md:163`） | 改基座/重装可能回弹 |

---

## 11. 通知与留痕（**复用 C-1 同一套通道口径，不另造**）

> ⚠ **v2 修订（2026-09-18，P6 改判）**：三条通道与「不另造」红线**全部仍然有效**；**只重做收件人范围**（是否通知教师，§19.5）。 **以 §19 为准。**

> 校长交办原文：「**请去读 `docs/plans/session-change-impact-design.md` 并复用同一套通道口径，不要另造**」。C-1 **已落地**（不是纸面设计）：事件 key `session_change` 已在 `notify_pref.py:23`、发送方法在 `edu_schedule/models/session_ext.py:670`、按钮在 `views/session_conflict_view.xml:34`、真机冒烟 `tests/smoke/c1_impact_notify.py` 已存在。

### 11.1 三条通道（逐条照抄 C-1 的口径）

| 通道 | 落点 | 本设计的用法 |
|---|---|---|
| **站内信** | `edu.message._notify_event(event_key, recipient_user, body, sender_uid=None)`（`notify_pref.py:51`）；事件白名单 `notify_pref.py:15-24`；**偏好静音只在白名单内生效**（未登记的 key 仍能发、但用户**关不掉**） | 审批结果**必发**站内信给申请人（收件人 = `op.student.user_id`；无账号或就是审批人则跳过，照 `registration.py:107-110`）；事件 key 决策见 **§16 P4** |
| **审计** | `edu.audit.log._log(action, model, res_id, res_name, detail)`（`audit.py:29`，**失败只告警**）；查询页 `/edu/audit`（`roles.py:1406`） | 两条埋点：`'调班提交'`（学生侧，detail = 原班 → 目标班 + 理由前 40 字）、`'调班审批'`（教务侧，detail = `通过：原班 X → 新班 Y（档案 id）` / `驳回：原因`） |
| **字段级留痕** | `mail.thread` chatter（机制 `mail/models/mail_thread.py:644 _message_track`；`op.student.course._inherit="mail.thread"` `student.py:28`；`batch_id` `tracking=True` `student.py:34`） | **零成本**：批准时那一次 `write({'batch_id': …})` 自动产出 old→new。⚠ 默认 `_track_subtype` 返回 False（`mail_thread.py:632`）⇒ **只记录、不通知** —— 通知由我们显式控制（这正是想要的） |

### 11.2 不许做的事（照抄 C-1 的"不另造"红线）

- ❌ **不新增通知模型 / 不新增审计模型 / 不新增邮件模板**。
- ❌ **不使用 `edu.telegram.outbox`**（`deprecated-inventory.md` §0.1：该出口与**生产上的匿名意见箱同名同表**，是红线；且 `edu_telegram` 已由用户裁定退役）。
- ❌ **不覆写 `_track_subtype`**（会让所有写入路径都开始发信，含导入脚本）。
- ✅ **幂等口径**：同一张单重复点"通过"→ 动作内 `if rec.state != 'submitted': continue` 守卫（照 `registration.py:141-143`）；页面显示「最近一次审批：<时刻> · <审批人>」，数据源 = `edu.audit.log` 里该 `res_id` 的最近一条（**不新增字段**，照 C-1 §7.4 #1）。
- ✅ **文案必须自证是"这一次的变更"**：通知正文带**原班 → 新班**（照 C-1 §7.4 #2 的"不允许只发『课表变了』这种无法核对的话"）。

---

## 12. 与需求 7（`docs/plans/class-batch-management-design.md`）的关系

> 需求 7 已通过校长拍板：**教师可建/改班、删除与归档归教务、回收站复用 `op.batch.active`**。本设计**必须与它不冲突、且不复用第二套概念**。

### 12.1 共用同一套概念（**零新增第二套**）

| 概念 | 需求 7 的裁定 | 本设计的用法 | 是否一致 |
|---|---|---|---|
| 班级实体 | **复用 `op.batch`**（6 字段 + `mail.thread` + 内建 `active` 回收站，`batch.py:25-68`） | **完全一致**：目标班就是 `op.batch` 记录；**不新增班级概念** | ✅ |
| 学生归属 | **复用 `op.student.course.batch_id`**（唯一事实源） | **完全一致**：生效 = 改写这一个字段 | ✅ |
| 教务直接分班（需求 7 G1） | 复用 `registration.py:133-212` 的建档/转班语义 | **完全一致**：本设计**共用同一套前置校验口径**，**不另写一份** | ✅ |
| 教师建/改班 | 菜单可见性一行（ACL 已给） | **不涉及**（本设计不改班级菜单） | ✅ |
| 归档 / 回收站 | `op.batch.active` | **只读使用**：目标班下拉过滤 `active`（照 `enroll.py:93-95`）+ 审批时二次校验（§8.3 R5） | ✅ |
| 删除护栏 `op.batch.unlink()` | 需求 7 建议新增 | **不涉及**，但**不冲突**（护栏使"删掉调班目标班"更难发生，对本设计有利） | ✅ |

### 12.2 本设计**恰好落在需求 7 自己写下的收口触发条件上**

需求 7 §8.4 **T3** 原文：「出现**第二个**『给学生定班』的写库入口（今天只有 `registration.py:178-195`）⇒ 同上；**写库语义必须收敛到一处**」。

⇒ 本设计的**硬约束（写进实现要求）**：
1. `action_batch_change_approve()` **必须**复用同一套前置校验（`student` / `course` / `batch` 三者存在 + `batch.course_id == course_id` + 学期判定 `_running_term()`），**不得**复制粘贴出第二份；
2. 该方法是"调班"的**唯一**写库点（`registration.py` 内），**不得**在控制器里直接写 `op.student.course`；
3. 实施验收里加一条静态断言：`op.student.course` 的 `.create(`/`.write(` 调用点总数**仍为 1 个文件 / 2 个方法**（§15 V11）。

### 12.3 范围接力：需求 7 的"不做"被本需求推翻（**如实登记，不是冲突**）

需求 7 §1.2 非目标原文：「**不做学生自助转班**：涉及学籍口径，见 §13 P2/P5」。

⇒ 本次校长原话（「**学生可以申请修改，让管理员通过**」）**明确要求做这件事**。**两者不冲突，是范围接力**：
- 需求 7 做的是**教务发起**（教务在学生页面直接分班，无申请单）；
- 本设计做的是**学生发起 → 教务审批**（有申请单、有驳回、有留痕）。
- **两条路径共用同一个写库入口**（T3 口径）⇒ 不存在"两套口径"。
- `docs/plans/class-batch-management-design.md` 的 §1.2 那一行**建议在其实施时补一句指向本文件**（本次**不改它的文件**，只在台账登记，见 §18）。

### 12.4 与需求 7 拍板项的**同答要求**

| 项 | 需求 7 的建议 | 本设计的建议 | 必须一致的理由 |
|---|---|---|---|
| 谁能改学籍归属 | §13 **P2**：**只有教务** | §9：**只有教务 + 超管**（`privileged_staff()`） | 否则出现"教务能直接分班、却不能批调班单"的荒谬组合 |
| 归档后的班能否作目标 | §7-Q7 ⑤：归档 = 退出所有选班下拉 | §8.3 R5：下拉过滤 + 审批二次校验 | 同一语义 |
| 命名口径 | §13 **P6**：建议统一「**停用 / 恢复**」 | §16 P1 的命名需与之一致（不出现第三种说法） | 单一术语（`docs/plans/perm-model.md` / `feature-overlap-audit.md` 的收口原则） |

---

## 13. 复用 vs 自研边界 · 数据流

> ⚠ **v2 修订（2026-09-18，P6 改判）**：§13.1 边界表仍然有效（仅「1 个新方法」的写入内容扩为 4 字段）；§13.2 流程 A/B 的**表单字段与审批动作步骤被 §19.4 重做**。 **以 §19 为准。**

### 13.1 边界（**逐条划线，自研部分极小**）

| 对象 | 复用（零改动） | 自研 |
|---|---|---|
| 单据载体 + 状态机 | ✅ `op.subject.registration`（`draft/submitted/approved/rejected`）+ 自研 5 字段（`registration.py:38-46`） | **无**（只加 1 个 `doc_type` 值） |
| 单号 | ✅ 基座 `name` 序列（`SR%05d` 口径见 `enroll.py:283-284`） | 可选：调班单用 `BC%05d` 前缀（**命名拍板项 §16 P1**） |
| 学生归属写库 | ✅ **语义**复用 `registration.py:178-201` 的前置校验与 `_running_term()` 判定 | 1 个新方法（**只写 `batch_id`**） |
| 审批聚合页 | ✅ `enroll.py:324-378` 的 chips / 搜索 / 分页 / `pager` | `filterby` 分支 + 身份分可见集 |
| 后台审批菜单 | ✅ `approval_backend.xml:186-232`（按钮换绑 + 菜单 + domain） | 1 条 domain 放宽 + 1 个按钮 |
| 通知 | ✅ `edu.message._notify_event`（`notify_pref.py:51`） | 文案（按 doc_type 分支） |
| 审计 | ✅ `edu.audit.log._log`（`audit.py:29`）+ `/edu/audit`（`roles.py:1406`） | 2 个 action 字符串 + **2 处标签表补 1 行** |
| 字段级留痕 | ✅ `mail.thread` + `batch_id tracking=True`（`student.py:28,34`） | **无** |
| 学生侧身份分流 | ✅ `current_student()`（`main.py:14`）、`student_course()`（`:47`）、`privileged_staff()`（`roles.py:154`） | **无** |
| 学生页模板外壳 | ✅ `t-call="edu_portal.edu_page"`（`code-map.md:246` 第 4 条） | 1 个新模板 |
| 班级 / 归属实体 | ✅ `op.batch` + `op.student.course.batch_id`（需求 7 同款） | **无** |

### 13.2 数据流（逐步给文件:行号）

**流程 A —— 学生提交调班申请**

    学生（stu@local）→ /my/home 卡片「申请调班」
      → GET  /batch/change/request
           门禁：current_student()（main.py:14）判空 → 303 /my/home
           数据：① 我的 running 档案（main.py:47 student_course / 显式定位，§8.3 R4）
                 ② 可换目标班 = 同课程下 active 的 op.batch
                    （口径照 enroll.py:93-95：course_id in …、active = True）
                 ③ 每班展示：班名、课节数（op.session by batch_id 计数，照 enroll.py:103-104）、
                    在读人数（op.student.course by batch_id 计数）
      → 学生选目标班 + 填理由 → POST /batch/change/request/save（csrf）
           服务端校验（防绕过，逐条）：
             ① 学生必填（current_student 判空 → 303）
             ② 目标班必须存在且 active
             ③ 目标班.course_id == 我的档案.course_id（跨课程一律拒绝，§7.3）
             ④ 目标班 != 现班（无变化拒绝，人话提示）
             ⑤ 同一学生同一档案存在 submitted 的调班单 → 拒绝（防重复提交）
             ⑥ 目标班预检（§8.3 R2/R3）：(student,course,目标班) 已有档案行？目标班内同 roll_number 冲突？
           建单：op.subject.registration{student_id, course_id, batch_id = 目标班,
                  state='submitted', doc_type='batch_change', applicant_note=理由,
                  submitted_at=now}   ← 科目字段一律为空（§5.3 硬约束）
           审计：edu.audit.log._log('调班提交', 'op.subject.registration', rid, name, '原班 X → 目标班 Y')
      → 303 /batch/change/request?box=submitted

**流程 B —— 教务审批**

    教务/超管 → 门户 /registrar/subject/approvals?filterby=batch
          门禁：privileged_staff()（roles.py:154）；教师看不到调班单
          列表：单号 / 学生 / 课程 / 现班 → 目标班 / 申请时间 / 理由 / 状态
          详情 /registrar/subject/approvals/<rid>：
            · 差异与影响面（照 C-1「先看见动的是哪几根线」的产品形态）：
                现班 → 目标班、目标班课节数、目标班在读人数、
                「换班后该生将从原班的点名表 / 评教名单中移除」（§8.3 R1）
            · 操作：POST …/set_state  state=approved|rejected
                approved → rec.action_batch_change_approve()
                    ① state 守卫（!= submitted 直接返回，幂等）
                    ② 解析档案（学生 + 课程 → running 优先，照 registration.py:153-159 口径）
                       无档案 → 拒绝并提示"该生尚无课程档案，请先在学生页面分班"
                       （不自动建档：调班的前提是"已经有班"）
                    ③ 目标班二次校验：存在 / active / course_id == 档案 course_id（§8.3 R5）
                    ④ 约束预检（R2/R3）
                    ⑤ 唯一写库动作：sc.write({'batch_id': 目标班.id})
                       ⇒ mail.thread 自动写 old→new（student.py:34 tracking=True）
                    ⑥ rec.write({state:'approved', approved_at, approved_by})
                    ⑦ _notify_student('approved') → edu.message._notify_event(…)
                    ⑧ edu.audit.log._log('调班审批', …,'通过：原班 X → 新班 Y（档案 id）')
                rejected → 复用 action_enroll_reject()（registration.py:214-230）：
                           驳回原因必填（控制器先写 reject_reason）+ 通知 + 审计
      → 学生侧立即可见：
          课表/任课老师/同班同学（study.py:30-40 / 43-57 / 122-131）
          首页班级 chip（batch2.py:1930-1931）、档案页 chip（batch1.py:320）
          站内信角标（/my/messages）

**流程 C —— 反向调回（可逆性验收）**

    学生再提一张单（目标 = 原班）→ 教务通过 → 同一行 batch_id 改回
      ⇒ 与流程 B 完全同路径；这是口径一相对口径二的决定性优势（§8.1 唯一约束行）

---

## 14. 第 3 步：读参考（学什么 / 砍什么）

> 第 3 步产出 = 调研笔记：官方/基座模块的数据模型、权限、视图手法；明确「学什么、砍什么」。

### 14.1 回引 `docs/research/`（索引见 `docs/research/README.md:17-24`）

**先说负结论（必须如实报）**：`docs/research/` **没有**"学生申请班级/学籍变更"这一主题的调研。
`grep -rn "调班\|换班\|转班\|学籍异动" docs/research/*.md` = **0 命中**（"变更"的命中全部是"成绩变更留痕"与"路径变更"）。⇒ 本设计的**外部先例依据是薄弱的**，主张的支点是**仓内先例**（选课注册单 + C-1 通道），**不是外部调研**。这一点必须让下一个人知道。

**能回引的两处（精确到行号）**：

| 调研 | 结论（原文出处） | 本设计的对应 |
|---|---|---|
| `docs/research/scheduling-approaches.md:373`（西安电子科技大学教务处，一手 URL <https://jwc.xidian.edu.cn/info/1012/23283.htm>） | 第 1 轮正选：**「可志愿退改」「调整即刻生效」**，「限定课容量」「限制时间冲突」「可实时查看个人选课结果」 | ⚠ **本设计有意偏离**：外部事实标准是"**退改即生效、无需审批**"，而校长原话要求**审批**。⇒ **"学"「实时看到个人结果」与「候选范围受约束」；"砍"「即改即生效」**（理由 = 校长口径优先；且本场景是**学籍归属**而非选课期的加减课） |
| `docs/research/scheduling-approaches.md:30,368-378`（西电 / 西北大学 <https://jwc.nwu.edu.cn/info/1034/11158.htm> / 上海交大 <https://jwc.sjtu.edu.cn/info/1222/126721.htm>） | 选课是**两轮制**（预选志愿/抽签 → 正选即选即得），且"筛选与选课时间先后无关" | ⚠ **本设计用不到**（调班不是抢名额）；⇒ 明确**不引入**"志愿/抽签"这套概念，避免概念膨胀 |

### 14.2 外部先例（本次实查，**标注核实程度**）

| 主题 | 一手证据 | 学什么 | 砍什么 |
|---|---|---|---|
| **Moodle「Group self-selection」/「Group choice」：学生自选组** | 官方文档条目 <https://docs.moodle.org/en/Group_self-selection_module>（摘要原文："The Group selection activity module allows students to select a group in the course that they want to be members of"）、<https://docs.moodle.org/en/Group_choice_quick_guide>（"Following their choice, they are **automatically enrolled** in the group(s) of their choice"） | ① **"学生可以自己选班/组"是成熟系统里存在的产品形态**（不是我们发明的）；② **候选范围由教务划定**（下一行） | ⚠ **直连 403**（`docs.moodle.org` 实测 web_fetch 返回 **403**，取不到正文）⇒ **标「未验证（仅有官方文档站条目摘要）」**；**不做"即选即入"**（与校长口径冲突） |
| **候选范围可配 + 可设容量上限** | LSE（伦敦政经）官方 Confluence <https://lse.atlassian.net/wiki/spaces/MG/pages/2771517482>：「Teachers must specify which groups are available for selection and can set **limits on the number of students** allowed in each group」 | ✅ **学**：目标班**候选范围由教务决定**（本设计 = 同课程 + `active` 的班，照 `enroll.py:93-95`）；**显示**每班现有人数供人判断 | ❌ **砍容量上限**：`op.batch` **没有容量字段**（`batch.py:30-36`，需求 7 §7-Q1 已实证）⇒ 本期只展示、不拦截（§1.2 非目标） |
| **Odoo 企业版 Approvals（`approval.request`）** | **本仓不可用**：容器核心 addons `grep -c approv` = **0**（685 个 addons）；库内 `ir_module_module` 名字含 `approv` = **0** | ✅ **学形态**（分类 → 申请 → 待批 → 通过与驳回 + 审批人），这正是本仓"选课注册单"已经在做的 | ❌ **砍"装它"这条路**：社区版没有，"能装不写"在本主题**落空** ⇒ **复用仓内既有形态**是正解 |

### 14.3 基座与仓内（只读；**学什么 / 砍什么**）

| 对象（路径 + 行号） | 学什么 | 砍什么 |
|---|---|---|
| `openeducat_erp/openeducat_core/models/subject_registration.py`（`_inherit=["mail.thread"]`；`name` readonly default `'New'`；`state` 4 值 + `tracking=True`；`course_id`/`batch_id`/`student_id` `tracking=True`） | ✅ **载体自带 chatter 与 4 态状态机** ⇒ 零成本 | ❌ **不调用基座 `action_approve`**（`enroll-v2-design.md:39-53` 已实证其两处缺陷：无档案抛错、不更新班级/学期、不通知不审计） |
| `openeducat_erp/openeducat_core/models/student.py:25-58` | ✅ `op.student.course` = **归属事实源**；`batch_id tracking=True`（`:34`）；3 条唯一约束（`:43-51`） | ❌ **不加字段、不覆写 `write()`**（§7.3） |
| `openeducat_erp/openeducat_core/models/batch.py:25-68` | ✅ 目标班实体（6 字段 + `active`） | ❌ 不加字段（容量/学年学期都没有，需求 7 已裁"不加"） |
| **本仓先例 `edu_portal/models/registration.py:133-212`** | ✅ **判别式复用**：state 守卫、running 优先取档案、`_running_term()` 学期判定、`_notify_student` 写法、审计一行 | ❌ **不复制粘贴**：必须共用前置校验（T3 口径，§12.2） |
| **本仓先例 `edu_schedule/models/session_ext.py`（C-1）** | ✅ **通知/留痕三通道 + 幂等口径 + 「最近一次通知」读数** | ❌ 不复用其"影响面四查"（那是课节冲突算法，与归属变更无关） |
| **本仓先例 `registration.py:161-171`（校长亲裁的防呆）** | ✅ **"拦住 + 人话 + 引导替代路径"** 的形态（另有 `fees.py:128-138`、`downloads.py:44-55` 两处同类） | ❌ 不照搬其触发条件（那是"清空科目"的防呆） |

---

## 15. 验收标准（**真机可验证**）

> ⚠ **v2 修订（2026-09-18，P6 改判）**：V1–V14 仍然有效（V4/V6/V7 的 URL 改为既有 `/course/change/request*`）；**新增 V15–V22**（§19.9，含「成绩不漂移」与「跨课程可逆」两条必测项）。 **以 §19 为准。**

> 口径（`dev-workflow.md` 陷阱 2）：**改路由/控制器的验收必须有一条真的去 GET 那个页面、并核对页面上的数字**；**探测不许跟随重定向**（`allow_redirects=False` + 精确 `Location`）。
> 判定模板：「**① 绕过被测路径 → ② 读真正的产物 → ③ 还原并断言 `leftover=0`**」（同型先例 `checkin-merge-report`）。
> 建议落地为 `tests/smoke/batch_change_smoke.py`（命名与结构照 `tests/smoke/c1_impact_notify.py`）。

### 15.1 环境前置（缺一不可，否则读数无效）

1. 无升级锁 `test ! -f $TMPDIR/edu19_upgrade.lock`；容器 `Up > 30s`；`curl -c jar -b jar 'http://localhost:8069/web/login?db=edu19'` ∈ {200,302,303}。
2. **计数型判定前置**：`ls -lt /tmp/edu19_upgrade.*.log | head -3` 确认最近没跑过 `-u edu_life`（F5 会往业务表补演示打卡，`dev-workflow.md:103-127`）。
3. **先取基线**（4 个计数）：`op_subject_registration`（按 doc_type 分组）、`op_student_course`、`edu_audit_log`、`edu_message`。
4. **夹具前置**：跑 `python3 scripts/seed_batch_change_demo.py`（建 1 个 `course_id=18` 的【演示】班）；**先断言夹具合法**：`select id from op_batch where course_id=18 and active and name like '%【演示】%'` **≥1 行**。

### 15.2 逐条验收

| # | 步骤（可原样执行） | 通过线 | 反例（**不许这么写**） |
|---|---|---|---|
| **V1** | `bash scripts/safe_upgrade.sh edu_portal` | **EXIT=0**，输出无 `Traceback`/`CRITICAL`/`manifest not found` | ❌ 把"升级成功"当通过（`dev-workflow` 陷阱 2：装载 ≠ 路由能跑） |
| **V2** | 离线门禁：`check_view_xpath --selftest`、`check_manifest_tracking --selftest`、`check_qweb_dict_foreach --selftest`、`check_english --selftest`、`check_odoo_trace --selftest`、`gate_seam_check.py` | 全部 **exit 0** | — |
| **V3** | **正对照（先证载体合法）**：`select id from op_student_course where student_id=5 and state='running'` = **1 行**（id 9）；`select count(*) from op_batch where course_id=18 and active and id<>8` **≥1** | 两个读数都成立 | ❌ 在"没有同课程第二班"的库上验收（本地必须靠 §6 的种子） |
| **V4** | 学生 `stu@local` 登录 → `GET /batch/change/request` | **200**；页面**含**「现班 = 预备科 · 2026级【演示】」与目标班下拉（含【演示】班） | ❌ 只看 200 不看内容 |
| **V5** | **越权反向断言（不跟随重定向）**：用**无学生身份的账号**（如 `backoffice@local` 无 `op.student`）GET `/batch/change/request` | **303** + `Location == '/my/home'` | ❌ 用 `allow_redirects=True`（会把 303 判成 PASS） |
| **V6** | 学生提交申请：选【演示】班 + 填理由 → POST `/batch/change/request/save` | ① `op_subject_registration` 新增 **1** 行：`doc_type='batch_change'`、`state='submitted'`、`batch_id` = 目标班、`student_id` = 5；② **`compulsory_subject_ids` 与 `elective_subject_ids` 均为空**；③ `edu_audit_log` 新增 1 行 `action='调班提交'`；④ 响应 303 → `?box=submitted` | ❌ 只断言"页面出现成功横幅"（要看库里的行） |
| **V7** | 教务 `backoffice@local` → `/registrar/subject/approvals?filterby=batch` → 打开该单 → 点「通过」 | ① 页面 200 且**含「原班 → 目标班」与「换班后该生将从原班点名表/评教名单移除」提示**；② `op_student_course.id 9` 的 **`batch_id` 变成目标班 id**，且 **`state` 仍 `running`**、**`subject_ids` 未变**、**该表总行数未变（仍 4 行）**；③ `mail_tracking_value` 中 `model='op.student.course'` 且该 `res_id` 的 `batch_id` 行 **+1**（old/new 非空）——**这一条就是 §8.1"口径一白拿留痕"的实证**；④ `edu_audit_log` 新增 `action='调班审批'` 1 行；⑤ `edu_message` 新增 **1** 行（收件人 = `stu@local` 的 user 8） | ❌ 只读代码说"tracking 会留痕"（**C-1 §9.3 的反例**）；❌ 不断言"表总行数未变"（那就分不清口径一/口径二） |
| **V8** | **可逆性（口径一相对口径二的决定性证据）**：再提一张单，目标 = 原班（id 8）→ 教务通过 | ① `batch_id` 改回 **8**；② **无 `IntegrityError`**；③ `op_student_course` 仍 **4 行** | ❌ 不测反向（口径二在这里会直接撞 `unique(student_id,course_id,batch_id)`） |
| **V9** | **竞态 / 归档目标班**：新提一张单（目标 = 【演示】班）→ **审批前**把该班 `active=false` → 教务点通过 | **被拒绝**（人话提示"目标班已停用，请重选"），且 `op_student_course.id 9` 的 `batch_id` **未变**；随后把班恢复 `active=true` | ❌ 直接通过（那就没有 §8.3 R5 的保护） |
| **V10** | **静默改写防线**：`bash scripts/safe_upgrade.sh edu_portal` 后复查 | 新造的调班单 `doc_type` **仍是 `batch_change`**（未被 `_infer_doc_type` 改成 `subject_registration`），且 `/registrar/subject/approvals?filterby=pending` 的**统计里仍不含它** | ❌ 不跑这次 `-u` 就声明"安全"（§5.3 的路径正是每次 `-u` 触发） |
| **V11** | **写库入口计数（T3 口径）**：`grep -rn "op\.student\.course" --include="*.py" custom_addons/ \| grep -E "\.create\(\|\.write\("` | 命中**仍只在 `registration.py` 的 2 个方法内** | ❌ 让控制器直接写库（那就制造了第二入口） |
| **V12** | **权限四层自检**：教务组 implied 传递闭包**不含** `base.group_system`；教师账号访问 `/registrar/subject/approvals?filterby=batch` → 列表**不含**调班单；直接 POST 调班单的 `set_state` → **303 且状态未变** | 三条全过 | ❌ 只测"教务能批"（要**正反对照**） |
| **V13** | 文案与无障碍门禁 | `check_english.py` → **must-fix = 0**；`check_odoo_trace.py` → **0 命中**；`check_accessibility.py` → **BASELINE 仍为 0**（新按钮/新下拉必须带可访问名，`code-map.md:252` 第 10 条） | — |
| **V14** | **还原并断言 `leftover=0`**：撤回演示数据（删本次产生的 `op_subject_registration` / `edu_message` / `edu_audit_log` 行；把 `op_student_course.id 9` 的 `batch_id` 还原为 **8**；`python3 scripts/seed_batch_change_demo.py --clean`） | ① 三张表的相关行数回到基线；② `batch_id` == **8**；③ 【演示】班计数 = **0** | ❌ 留样本就交（`dev-workflow` 的"构造 → 断言 → 还原"三段模板） |

### 15.3 反例汇总（**明确不允许**的验收写法）

- ❌ 「升级 EXIT=0」当作通过。
- ❌ 用 `allow_redirects=True` 探测新增路由。
- ❌ 在没有"同课程第二班"的库上验收（**本地现状就是如此**，必须先跑 §6 的种子）。
- ❌ 只读代码声称「字段级留痕已生效」——必须读回 `mail_tracking_value` 行（**C-1 已有同款反例**）。
- ❌ 只断言"页面 200 / 有成功横幅"——要看库里的行与总数。
- ❌ 只测"能通过"不测"能驳回 / 能换回 / 越权被拒"。

---

## 16. 需要校长拍板的用户可见项（**6 项**）

> ⚠ **v2 修订（2026-09-18，P6 改判）**：P2/P3/P4/P5 **保持原建议**；**P1 命名需重新给候选**、**P6 已由校长改判为「允许」**，另新增 P6′/P7–P10（§19.3）。 **以 §19 为准。**

| # | 待拍板 | 选项 | 本文建议 | 影响面 |
|---|---|---|---|---|
| **P1** | **命名**（入口与学生可见文案） | ① 学生入口叫「**申请调班**」/「**班级变更申请**」/「**换班申请**」？② 单号前缀用 `BC%05d` 还是沿用 `SR%05d`？③ 教务侧页签叫「**调班审批**」还是并入「选课审批」一个页面？ | ①**「申请调班」**（校长的词就是"调班"）；② `BC%05d`（区分单据类型）；③**同一页面加页签「调班审批」** | 学生首页卡片、门户侧导航、审批页标题、`/edu/audit` 的动作列。⚠ **需与需求 7 §13 P6 的命名口径一致**（不出现第三种说法） |
| **P2** | **谁能批** | (a) **教务 + 超管**（`privileged_staff()`）；(b) 教务 + 超管 + **教师**（与选课审批一致 `current_faculty() or privileged_staff()`） | **(a)** | 校长的原话是"**管理员**通过"。选 (b) 会让任一教师都能改学生学籍归属；(a) 与需求 7 §13 P2（分班只能教务）同答 |
| **P3** | **可见范围：学生能看到多少** | ① 只看到"我的申请 + 状态 + 驳回原因"；② 另加"**原班 → 新班**"的变更前后对照；③ 再另加"历史调班记录"（多次变更的完整时间线） | **②** | ②是**必要的自我证明**（学生得知道改成了什么）；③会让"曾经在哪班"长期可见，属额外隐私面。家长是否可见 = 本文建议**不可见**（沿用需求 7 §12.3 口径） |
| **P4** | **通知事件与文案** | ① 复用既有 key `subject_reg_result`（学生只需一个「选课/学籍结果」开关）；② 新增 key `batch_change_result`（可单独静音） | **①复用** | `/my/notify` 开关数量；**B4 触发条件**（出现第 3 个同类 key 就必须合并） |
| **P5** | **换班后，旧班的历史考勤/成绩在门户是否仍对学生可见** | (a) 可见（现状：成绩按"学生×考试"聚合，不随档案走）；(b) 隐藏旧班记录 | **(a)** | §8.3 **R1** 的后果是"**旧班的名单里不再有他**"——这是**教务侧**的影响；**学生侧**他自己仍能看到旧班已录的成绩。若选 (b)，需要额外一套"历史班次"读口径（**不建议本期做**） |
| **P6** | **是否允许跨课程调班** | (a) **不允许**（跨课程走"课程变更"另议）；(b) 允许（同时换课程与班级） | **(a)** | 选 (b) 需要同时换 `course_id` + 科目集 ⇒ 直接落进 §3.2 ④-B 的空科目死锁区，且与既有 `course_change` 语义重叠 |

> **另有 2 项"非拍板但需知会"**：
> ① **后台按钮文案会新增一个**——教务在后台打开调班单时看到的是「**通过（调班）**」，而选课单仍是「通过（建档并挂科目）」（两按钮按 `doc_type` 互斥显示）。这是**用户可见变化**，但不改变既有行为。
> ② **`/edu/audit` 的模型列会新增一行「学生课程档案」**（`op.student.course` 现在未登记，会落到中文兜底「其它记录」，`roles.py:112-118`）。

---

## 17. 未查到 / 不确定（**不得当结论用**）

> ⚠ **v2 修订（2026-09-18，P6 改判）**：第 1 条（生产读数）**已补齐**、第 2 条（11 张单来源）**已复核到 create_uid 级**、第 6 条（`roll_number`）**在生产是活的**；其余条目与 §19.10 的新增未验证项一并适用。 **以 §19 为准。**

| # | 未验证项 | 我做了什么 / 为什么不确定 |
|---|---|---|
| **1** | **生产库（马来西亚 prod-host）的同类读数全部未取** | 本次只读**本地 `edu19`**（只读 SELECT）。生产的 `op_subject_registration` / `op_student_course` / `op_batch` 分布、以及**王佐那个真实学生**的档案现状（在哪个班、是否真的错班）**完全未知** ⇒ **部署前必须另取一次基线** |
| **2** | **本地那 11 张 `course_change` 单的真实来源未定** | 已知：ids 10–19（`student_id 5`，`course 13`，`batch 8`）与 id 72（`student_id NULL`）。**线索**：`scripts/smoke_b_submit_faculty.py:124-133`（`S3 学生换课申请`）与 `scripts/test_submit_flows.py:59-77` 都会 POST `/course/change/request/save` ⇒ **很可能是冒烟脚本产物**，但**没有 create_uid / create_date 级别的比对证据**（未查），故**不当"真实申请"用**，也不据此推断生产行为 |
| **3** | **`op.student.course` 的字段级留痕到底会不会落地** | 机制在（`student.py:28` `mail.thread` + `:34 tracking=True`，且 `mail_thread.py:644` 是标准路径），**但 `mail_tracking_value` join `mail_message` 且 `model='op.student.course'` = 0 行** ⇒ **从未被触发过**。⇒ **V7 就是为补这个读数设计的**；**在 V7 跑出来之前，不得声称"调班会留痕"** |
| **4** | **门户是否渲染 `op.student.course` 的 chatter** | 本仓自研门户**没有**通用的 chatter 面板；`op.student.course` 也没有后台表单给教务看。⇒ 字段级留痕**目前只存在于数据库与后台**，学生/教务在门户**看不到**它。若 P3 选③（历史时间线），需要**另建读取口径**（本设计只把它当"审计底账"） |
| **5** | **本地无法构造"多条 running 档案"** | 库内 `op_student_course` 4 行中只有 **1 行 running**（学生 5）。⇒ §8.3 **R4**（`student_course()` 无 `order` 的不确定性）**在本地测不出来**，只能靠"服务端按显式档案 id 定位"的设计规避 |
| **6** | **`roll_number` 冲突路径（R3）本地测不到** | 4 行的 `roll_number` **全部为 NULL**（Postgres 视 NULL 互不相同 ⇒ 唯一约束不会触发）。⇒ R3 是**读约束定义推出的**（`student.py:47-48`），**没有实测样本** |
| **7** | **`action_enroll_reject` 复用后通知文案是否合适** | 它现在发的是「【选课通知】您的选课申请 … 已被驳回」（`registration.py:118-122`）⇒ 调班单驳回时**文案会错**（说成"选课申请"）。本设计要求 `_notify_student` 按 `doc_type` 分支（§10.2 #6），**但分支前的现状是错的**，实施时必须一并改 |
| **8** | **`/registrar/subject/approvals` 加"按身份分可见集"后，教师侧是否真的看不到** | 目前该页 domain 硬写 `doc_type='subject_registration'`（`enroll.py:337`）⇒ **现在教师看不到任何 course_change 单**（一致）。改成两集合后**必须实跑 V12** 验证；**未验证** |
| **9** | **`scoped_records()`（`enroll.py:25` 引用）对调班单的过滤语义** | 读到该函数被 import 与用于批量审批（`set_state_bulk`），但**未逐行读完**其身份→domain 规则 ⇒ 调班单进批量审批是否安全**待查**（本设计默认**批量审批不含调班单**） |
| **10** | **需求 7 的拍板结果（P1/P2/P5/P6）未回填** | `docs/plans/class-batch-management-design.md` 是**设计稿**（未实施），其 6 项拍板**还没有答案** ⇒ §12.4 的"同答要求"只能写成**约束**，不能写成"已一致" |
| **11** | **`edu_zh` 汉化是否需要为新按钮/字段补 PO** | 本设计的新文案全在自研模板/方法内（中文硬编码），按 `code-map.md:83` 的 `edu_zh` 机制**可能不需要 PO**；**未逐条核对**现有 `i18n_extra/zh_CN.po` 的收录边界 |
| **12** | **`op.student.course` 在**生产**是否可能有"多课程 × 多 running"** | 本地只有 4 行，推断不了生产形态（§17-1） |

---

## 18. 台账登记（第 0 步「查到重复怎么办」第 2 步）

> ⚠ **v2 修订（2026-09-18，P6 改判）**：**裁定栏已改变**（不再新增 `doc_type`，改为修好既有链路并收口）——`docs/audit/deprecated-inventory.md` 已追加一行登记该变更。 **以 §19 为准。**

按 `docs/dev-workflow.md:54-55`：**不得直接新建；先登记；由队长裁定**。本次在 `docs/audit/deprecated-inventory.md` **追加一行**（**不覆盖任何历史行**）：

- **重叠对象**：① **头号**：`custom_addons/edu_portal/controllers/batch3.py:213,258` 的 `/course/change/request`「课程变更申请」——**学生侧入口是活的、教务侧被硬排除**（`controllers/enroll.py:337`、`views/approval_backend.xml:229`），库内 **11 张 `course_change` 单 100% 卡在 `submitted`**；② **同族**：`op.subject.registration`（基座选课注册单，已被本仓扩成"学生申请→教务审批"的成熟形态，`enroll-v2-design.md`）。
- **证据**：路由 `batch3.py:213,258`；模板 `views/batch3.xml:158-205`；首页卡 `batch2.py:268-270,429,813`（**不在 `_DEFAULT_HIDDEN_CARDS`**）；教务侧排除 `enroll.py:337` + `approval_backend.xml:229`；**数据条数（只读）** `op_subject_registration` 12 行 = `course_change/submitted 11` + `subject_registration/approved 1`；结构性死路两条（`batch.course_id≠course_id` 与 `registration.py:161-171` 的空科目拦截）；**写库入口唯一性** `grep -rn "op\.student\.course"` 56 命中中 create/write **仅 `registration.py:178-201`**。
- **裁定**：**复用**（候选 A）。**替代路径 = `op.subject.registration` + 新增 `doc_type='batch_change'`**；扩展方式 = 1 行 Selection + 1 个不碰科目的审批动作 + 1 条学生路由族 + 审批页 1 个 `filterby` 分支 + 后台 1 个按钮/1 行 domain。**不新建模块/模型/表/字段/权限组/通知通道。**
- **明确不做 + 唤醒条件**：既有 11 张 `course_change` 单**不改不批不删**（语义是"换课程"，与"换班"不同轴）⇒ **唤醒条件 = 另立"换课/学籍异动"任务**时一并处置（§7.3）。
- **收口触发条件**：**B1–B5**（§7.4）。其中 **B2 与需求 7 §8.4 T3 是同一条**（"第二个给学生定班的写库入口"）。

---

## 19. 修订（v2）：P6 改判「课程也可以换」

> 本章 = 本次修订正文（2026-09-18）。**v1 原文一字未删**：§7/§8/§10/§16 等仍是历史结论，**与本章冲突者以本章为准**。
> 独立验证：本章全部行号与读数由本次修订**自己复核**（本地库 + **生产库只读 SELECT** + 当前 HEAD 源码），复核出的不符项集中在 §19.7。

### 19.0 需求边界的新表述（一句话）

一条「归属变更申请」= 学生档案 `op.student.course` 的**目标课程 + 目标班级成对变更**；
「**只换班**」= 目标课程与现课程相同的**退化情形**。

⇒ **两把钥匙都得有**。v1 只准备了「班级」一把（`batch_change`）；既有 `course_change` 单只有「课程」一把（表单只收目标课程）。**「成对」这件事是本轮才被摆到台面上的结构缺口**（§19.2.2 #5）。

### 19.1 载体裁定重做（三选一）

#### 19.1.1 三个候选

| 候选 | 做法 | 代价 | 后果 |
|---|---|---|---|
| **① 修好既有换课链路 + 收口成唯一入口（本次推荐）** | 学生入口**仍用既有** `/course/change/request`（**不新增路由族**）；表单从「只收目标课程」补成「**目标课程 + 目标班级**成对」（两者都按 `active=True` 过滤、班级随课程联动）；`doc_type` **不新增第三个值**（沿用既有 `course_change`，只把 Selection **标签**改成覆盖换班/换课的文案）；教务侧解除硬排除（`enroll.py:337` domain、`:350-357` 统计、`approval_backend.xml:230` domain、`batch2.py:617-619` 待批计数，并订正 `batch2.py:616` 的失效注释）；新增**一个**审批动作 `action_course_change_approve()`（**原地改写同一行档案**） | ① 1 行 Selection **标签**改文案（**不是新增值**）；② 1 个模型方法（约 50 行，落 `registration.py`）；③ 既有模板补 1 个 `select` + 1 处取班口径修正；④ 教务侧 3 处 domain/计数 + 1 处注释；⑤ 后台 1 个按钮 + 1 行 domain | ✅ **修的缺口是同一个**：无论叫「调班」还是「换课」，教务都够不着 —— 修一次，两类单一起进队列；✅ **概念不分裂**：一个 doc_type = 一套语义 = 一张队列 = 一个审批动作；✅ **不触发 v1 自己写下的收口条件**：B1（第 3/4 个 doc_type 值）与 B3（第二条学生侧归属变更路由）都不触发；✅ 与生产实况吻合（生产 `op_subject_registration` **只有 1 行**、`course_change` **0 行**，见 §19.6）⇒ 没有需要照顾的历史语义包袱 |
| ② 维持 v1 裁定：新增 `doc_type=batch_change` + 新路由族 `/batch/change/request`（**不取**） | 不动既有换课链路，另立第三个分型与第二条学生路由 | ① `_DOC_TYPE` 加值（`registration.py:29-32`）⇒ **直接触发 v1 §7.4 的 B1**；② 新路由族 ⇒ **直接触发 v1 §7.4 的 B3**；③ 学生侧将同时存在**三条**同表页面：`/subject/registration`（我的申请，已列全部单）、`/course/change/request`（换课）、新换班页 | ❌ P6 之后「换班」与「换课」**不是两种业务，是一种业务的两个参数** ⇒ 两个 doc_type 是**同义分裂**，教务队列里会出现两张语义重叠的单；❌ 既有换课链路**仍然批不动**（教务依旧够不着），而它恰恰已经是本需求要的东西（表单收的就是目标课程）⇒ 修一处 vs 修两处，选修一处 |
| ③ 什么都不修：关掉学生入口，只保留「教务在学生页面直接分班」（**不取**） | 冻结 `/course/change/request`，学生侧零入口 | 0（零代码） | ❌ 直接违逆校长原话「**学生可以申请修改，让管理员通过**」——申请与审批是需求的字面内容；❌ v1 §12.3 已登记这是需求 7 §1.2 的**范围接力**，无入口即无接力（§12.3 的结论不变，但落点变了） |

#### 19.1.2 裁定

> **取候选 ①**：**修好既有 `/course/change/request` 链路并把它收口成唯一的「归属变更」入口**；
> 不再新增 `doc_type`、不再新增学生路由族、不再新建模板。

四条理由（按强度排序）：
1. **P6 之后两件事变成一件事**：换课 ⊇ 换班；两个 doc_type 会让"教务队列里同一业务两种单"长期存在（本仓最忌讳的同类分裂：`feature-overlap-audit.md` 记的 8 类重叠都是这么长出来的）。
2. **既有链路的缺口是"教务够不着"，不是"设计不对"**：`enroll.py:337` 与 `approval_backend.xml:230` 都是硬写 `doc_type=subject_registration` 的**单点排除**，删掉这两个限定即打通；而"修两处"（候选 ①）永远优于"修一处 + 再养一条并行链路"（候选 ②）。
3. **既有路由服务端本来就是按"成对"写的**：`batch3.py:277` 已经读表单的 `batch_id`（`kw.get(batch_id)` 优先，取不到才回落到现档案的班），只是模板 `views/batch3.xml:176-188` **没有渲染这个输入**（§19.7 不符项 1）⇒ 候选 ① 的"补一个 select"是**补齐既有设计**，不是改语义。
4. **候选 ② 会让学生侧出现第三张同表页面**：`/subject/registration`（`batch3.py:352-367`，domain 只有 `student_id` ⇒ 已列全部单）与 `/course/change/request`（`batch3.py:220-224`，同样是全部单）**今天就已经是同一份数据的两个视图**；再开一条即三份。

#### 19.1.3 为什么这次与上一版不同（一次说清）

| 维度 | v1（commit `58bc028`） | v2 |
|---|---|---|
| 前提 | 「跨课程 = 换课程 = **另一种业务**」⇒ 把「换班」独立分型，避免与 `course_change` 混（§3.2 ⑤ 原文：两者不是同一个动作） | 校长 P6 改判 ⇒ **本需求 ⊇ 既有语义**（换课含换班），"不同动作"的前提**不成立** |
| 复用到哪一层 | 复用**表**（`op.subject.registration`），但**新建分型 + 新建路由 + 新建模板** | **连分型与路由一起复用**：只补字段、只解禁队列、只加审批动作 |
| 关键证据强度 | 把「11 张卡死单」当作"必须复用载体"的**最强证据**（§0 TL;DR） | 本次复核：**生产 0 张**、本地 11 张的 `create_uid=8`（= `stu@local` 本人）⇒ 是**夹具**不是需求证据（§19.6/§19.7）；真正的证据是**教务侧两处硬排除**这个代码事实 —— 而它**无论选 ① 还是 ② 都必须修** |
| 生效语义 | 只改 `batch_id`，**绝不碰 `subject_ids`** | 换课程时**必须**同时写 `course_id + batch_id + subject_ids + academic_term_id`，一次 `write()` 原子完成（§19.2） |

### 19.2 生效语义重做（**本次核心**）

#### 19.2.1 一句话结论

> 换班与换课**都用同一次原地改写**（同一行 `op.student.course`，不新建行、不置 `finished`）；
> 但**换课程时必须一次 `write()` 原子写 4 个字段**：`course_id` + `batch_id` + `subject_ids` + `academic_term_id`。
> 任何"只改 `course_id`"的写法都会留下**"档案说新课程、科目/课表还是旧课程"的半写状态**。

#### 19.2.2 逐条给结论（每条带事实与行号）

**#1 换课程时 `subject_ids`（档案科目集）怎么办？**

- **结论：必须按目标课程重算并覆盖**（不是"不动"）。
- 事实：`op.student.course.subject_ids` 是 LMS 的事实源（`custom_addons/edu_portal/controllers/lms.py:24-37` 按学生取 `subject_ids` 决定可见课程；「我的已选科目」页同样按档案行渲染科目，`custom_addons/edu_portal/controllers/enroll.py:305-311`）；档案科目集的"正确答案"挂在**课程**上（基座 `openeducat_erp/openeducat_core/models/subject_registration.py:98` 用它填 `compulsory_subject_ids`；同文件 `:95-102 get_subjects()` 是既有口径）。
- ⚠ **与 v1 §7.2/§8 的"审批绝不碰 `subject_ids`"直接冲突**：那句话在 v1 的"只换班"前提下成立；P6 之后必须改成「**仅当目标课程 ≠ 现课程时**，按新课程重算 `subject_ids`」。
- ⚠ 仍未变的两条硬约束：① **单据本身不得携带科目集**（否则 `-u edu_portal` 的 `_infer_doc_type()`（`custom_addons/edu_portal/models/registration.py:57-74`）会把单改成 `subject_registration`，v1 §5.3 的静默改写路径）；② 既有空 payload 防呆（`registration.py:167-171`）不得放松。

**#2 已录成绩 / 考勤会不会被"漂移"到新课程名下？（队长最担心的一条）**

> **结论：不会。零物理漂移。** 成绩与考勤**都不引用** `op.student.course` —— 它们的课程/班级**自带**，来源是**考试**与**点名表**。

| 数据 | 归属键（行号） | 课程/班级从哪来 |
|---|---|---|
| `op.exam.attendees`（成绩的实际存放处） | `student_id`（`openeducat_erp/openeducat_exam/models/exam_attendees.py:30`）+ `exam_id`（`:36-37`），唯一约束 `unique(student_id,exam_id)`（`:46-47`） | `course_id`/`batch_id` 是 `compute=_compute_exam_details` 且 **store=True**，从 `exam_id.session_id` 得出（`:38-43`、`:58-66`） |
| `op.result.line` | `student_id`（`result_line.py:40`）+ `exam_id`（`:32`），唯一 `unique(exam_id,student_id)`（`:44-47`） | 经 `exam_id`（`session_id` 是 related store，`:33-35`） |
| `op.marksheet.line` | `student_id`（`marksheet_line.py:35`）+ `marksheet_reg_id`（`:30-31`） | **无课程/班级字段**；门户按 `exam_id.subject_id` 显示科目（`batch2.py:1033-1038`） |
| `op.attendance.line` | `student_id`（`attendance_line.py:35-36`）+ `attendance_id`（`:32-34`） | `course_id`/`batch_id` 是 `related=attendance_id.register_id.*` 且 **store=True**（`:43-50`） |

- 读数侧同样不经过档案：门户成绩簿与学生考勤**只按 `student_id` 过滤**（`batch2.py:1026-1028`、`:1090-1092`、`:1134-1135`）⇒ 改档案的 `course_id`/`batch_id` **不可能**把这些行搬到新课程名下。
- ⇒ v1 §8.1 那一行「已录成绩 ✅ 不动、不丢」**结论正确**，本轮只是把它的依据**落到行号**（此前只有一句概括）。

**#3 那"历史记错"的真正风险在哪？（三条，按严重度）**

1. **`subject_ids` 半写**（= #1）：档案挂着**新课程名**却按**旧课程科目**放 LMS ⇒ **学生立即可见**的记错。用 #1 的处置消除。
2. **档案行本身是唯一的历史载体**：原地改写后，"他曾在课程 18 / 班 8"在**事实源里不复存在**，只剩 chatter 与审计；而门户「我的档案 / 我的已选科目」（`custom_addons/edu_portal/controllers/enroll.py:302-313` 读**该学生的全部档案行**）会显示成"一直在新课程"。⚠ 且 **chatter 的字段级留痕至今从未产生过**：`mail_tracking_value` ⋈ `mail_message` 且 `model=op.student.course` = **0 行**（`mail_message` 有 11 条但全是"创建"备注 —— **v2 复核**）⇒ v1 §17-3 的警告**仍然成立**："靠 chatter 兜历史"目前是**纸面**，V7 那条验收不跑出来就不能声称留痕有效。
3. **名单口径**：教师/教务/评教都按 `batch_id` 取名单（`custom_addons/edu_portal/controllers/roles.py:368-370`、`:477-478`；评教 `custom_addons/edu_eval/controllers/eval_portal.py:62-64` 按 `lnk.batch_id`）⇒ 换班/换课后**旧班名单立刻不含他**（v1 R1 正确，两条口径在这一点上无差别）；而**旧课程的考试成绩行仍归旧课程**（教师成绩录入按 `exam_id` 取 attendees：`roles.py:714-715`；家长「近成绩」按 `student_id` 取：`roles.py:284`）——这是**正确**行为（教务仍能在旧课程给他改分），但**必须让教务知情**（§19.5）。

**#4 `unique(student_id, course_id, batch_id)`（`openeducat_core/models/student.py:49-51`）的规避还成立吗？**

> **结论：成立，但前提收紧到「整条链路只原地改写、永不新建行、且始终改同一行」。**

- **换回原班**（班 A → 班 B → 班 A）：同一行连续改写，不新增行 ⇒ 不撞（v1 §8.1 的论证仍成立）。
- **换课程再换回**（课程 18 → 课程 13 → 课程 18）：**同样成立**，因为目标行就是被改的那一行；`(student, 课程 18, 班 8)` 若**没有**别的行占用，改写不会触发唯一约束。
- ⚠ **但前提会被两条真实路径打破**：
  1. **`action_enroll_approve` 的建档分支**：它按 `(student_id, course_id)` 找档案（`registration.py:153-159`）——**换课程时目标课程下必然找不到** ⇒ 走 `create`（`:177-187`）**新建第二行**，而旧行（原课程）继续 `running` ⇒ 此后再"换回"该课程时 `(student, 原课程, 原班)` 已被旧行占用 ⇒ **`IntegrityError` = 不可逆**（正是 v1 §8.2 理由 1 要避免的）。**本轮已找到该路径的现实证据**：`docs/audit/task-B1-enroll-timetable-gap.md:231` 记载「跨课程报课通过后会生成**第 2 条** `op.student.course`，届时学生课表只会显示其中一个班的课」。
  2. **多 running 档案**：一旦学生有 ≥2 条 running 档案，"改哪一行"必须显式指定，否则会**改错行**；且门户取"当前班"一律 `limit=1` **无 `order`**（`custom_addons/edu_portal/controllers/main.py:47-55`；学生课表 `scheduling.py:100-103` 同款）⇒ 显示哪个班**不确定**（v1 §8.3 R4 正确）。
- ⇒ **实现红线**：换课审批动作**不得**复用 `action_enroll_approve`（它的两处缺陷恰好都在这里：空 payload 防呆 `:167-171` + 建档分支 `:177-187`），必须是"**先定位被改的那一行，再原地写 4 个字段**"。

**#5 单据需要记"来源档案"吗？（P6 才暴露的结构缺口）**

- 结构事实：`op.subject.registration` 只有**一对** `course_id` / `batch_id`（基座 `subject_registration.py:33-36`），语义是**目标**。「只换班」时来源可由"学生现档案"反查（同课程）；**「换课程」时目标课程下没有档案可反查** ⇒ 审批动作**必须显式拿到被改的那一行**。
- 三个可选实现（**拍板项 P7**）：(a) **零新字段**：提交时锁定"学生当时**唯一** running 档案"，审批时按同一学生重新解析；若解析到 **>1 条 running 档案** 则**拒绝 + 人话提示**（推荐）；(b) 给模型加 1 个字段（如 `source_student_course_id`，本仓已自研 5 个字段的先例：`registration.py:38-46`）；(c) 把档案 id 塞进 `applicant_note`（**不推荐**：结构化数据进自由文本）。

#### 19.2.3 四条"错写"反例（写进实现要求的红线）

- ❌ `sc.write({batch_id: 目标班})` 而目标班**属于另一个课程** ⇒ 档案变成「课程 18 + 班 27（属课程 13）」，与既有自洽校验口径（`registration.py:147-150`）自相矛盾。
- ❌ 只写 `course_id` 不写 `subject_ids` ⇒ #1 的半写（最像"记错"的一种）。
- ❌ 换课程时走 `create` 分支 ⇒ 学生出现 2 条 running 档案 + 不可逆（#4）。
- ❌ 顺手把旧行置 `state=finished` ⇒ 学生侧渲染成**「已结业」**（`enroll.py:309`，v1 §8.1 已实证）。

### 19.3 需要校长拍板项（v2）

| # | 待拍板 | 选项 | 本文建议 |
|---|---|---|---|
| **P1′** | **命名**（P1 重开：P6 改判后「申请调班」不再准确） | ① 学生入口与页面标题叫「**换班 / 换课申请**」，教务页签叫「**变更审批**」；② 「**学籍变更申请**」（教务口径最正式，学生侧再配副标题「换班 / 换课」）；③ 沿用校长原词「**申请调班**」+ 括号说明「（可同时换课程）」 | **①**。理由：①里学生一眼看懂两种变更；②的"学籍"对中学生不直观；③在换课程时会误导（学生会以为课程不变）。**同一个名字同时用于**：学生首页卡片、页面标题、教务页签、后台菜单与按钮、通知文案抬头。**单号前缀沿用既有 `CR%05d`**（`batch3.py:284` 已在用；本地库无 `CR` 行，零冲突）——**不再提 v1 P1 的 `BC%05d`**，因为不再新增分型。 |
| **P6′** | **跨课程换课允许到什么程度**（P6 的执行细则） | (a) 允许，目标课程须为 `active=True`（照 `enroll.py:79-80` 既有口径）；(b) 允许，但仅限"该生目前只有 1 条 running 档案"时；(c) 需要教务处单独开关 | **(a)** + 一条软约束：**「一名学生同时最多 1 条 running 档案」**作为申请前置（申请时若已 >1 条，则要求先选"要变更哪一条"，见 §19.2.2 #5-(a)）。理由：门户多处取"第一条 running"（`main.py:47-55`、`scheduling.py:100-103`），多档案会让学生看到哪个班变成不确定。 |
| **P7** | **来源档案的定位方式**（§19.2.2 #5 的 a/b/c） | (a) 零新字段，多档案时拒绝；(b) 新增 1 个字段；(c) 塞备注 | **(a)**：本设计的一贯口径是"不新增字段"，且当前**本地与生产都只有 1 条 running 档案**（§19.6），(a) 的代价今天为零。 |
| **P8** | **换课程后 `roll_number` 怎么办**（**v2 新增**，v1 未覆盖） | (a) 保留原值；(b) 教务在审批时填写新学号（写进档案）；(c) 清空 | **(b)**，并**必须**在审批动作里做撞约束预检：`unique(roll_number, course_id, batch_id)`（`student.py:46-48`）在**生产是活的**（王佐 `roll_number = BED2026-WZ001` **非空**，且学号里含课程码 `BED`，见 §19.6），而本地 4 行全为 NULL 才测不到（v1 §17-6 在**本地**成立、在**生产**不成立）。 |
| **P9** | **审批后通知谁** | (a) 只通知学生（v1 口径）；(b) 学生 + **旧班与新班的任课教师**（同一 key）；(c) 学生 + 教师 + 家长 | **(b)**：教师是**受影响方**（名单立刻变），且本仓已有"通知任课教师"的落地先例（C-1，见 §19.5）。 |
| **P10** | **既有 11 张本地 `course_change` 单**（**生产 0 张**） | (a) 保持不动且**不进队列**；(b) 进队列、允许教务**驳回**并引导重提；(c) 批量置 `rejected` 并通知 | **(b)**：队列一旦放宽它们就会出现（"看得见点不开"是本仓红线），而它们结构不自洽（`batch 8` 属课程 18，单写课程 13）⇒ 只能驳回重提。**生产无需处理（0 张）**。 |

> **另有 1 项"非拍板但需知会"**：教务页签从「选课审批」变为「选课审批 + 变更审批」两段（或同页 `filterby` 两态），**教师仍然看不到变更单**（v1 §10.3 的矩阵不变）。

### 19.4 学生申请时填什么（§13.2 流程 A 的重做）

| 字段 | 取值 | 口径出处 |
|---|---|---|
| **目标课程** `course_id` | 下拉，**仅 `active=True`**；默认 = 现课程（"只换班"的学生不用动这一项） | 照 `enroll.py:79-80`（`active = True`）。⚠ **既有换课页当前不过滤**：`batch3.py:241` 是 `search([], order=name, limit=50)`（连停用课程都会出现在下拉里）⇒ 本次必须对齐。 |
| **目标班级** `batch_id` | 下拉，**按所选课程 + `active=True`** 联动 | 照 `enroll.py:93-95`（`course_id in …` 且 `active = True`） |
| **现况展示** | **必须显示"将变更哪一条档案"**：现课程 + 现班（若多档案则让学生选一条） | v1 §8.3 R4；`main.py:47-55` 无 `order` |
| **理由** | 自由文本 → `applicant_note` | `registration.py:38-39`（既有字段） |
| **科目** | **学生不填**；服务端在**审批通过时**按目标课程重算档案科目 | §19.2.2 #1；同时保持"**单据不带科目集**"（v1 §5.3 硬约束，防 `_infer_doc_type()` 静默改写） |
| **服务端校验**（防绕过） | ① 目标班属于目标课程（`batch.course_id == course_id`，照 `registration.py:147-150` 口径）② 目标课程/班 ≠ 现课程/班（至少一项不同）③ 目标班 `active`（提交时 + **审批时二次校验**，v1 R5）④ 同一学生同档案无 `submitted` 单（防重复提交）⑤ 约束预检：目标组合是否已被 `unique(student_id, course_id, batch_id)` 或 `unique(roll_number, course_id, batch_id)` 占用（v1 R2/R3） | 行号见左列 |

> **既有的取班口径要一并修正**：`batch3.py:272-273` 找档案是 `search([(student_id, =, id)], limit=1)`——**没有状态过滤、没有课程过滤、没有 `order`**，多档案学生会取到任意一行（甚至已结业行）。新口径必须与 `action_enroll_approve` 一致（`running` 优先，`registration.py:153-159`）。

### 19.5 审批通过后通知谁（§11 的收件人重做）

| 收件人 | 是否通知 | 口径与理由 |
|---|---|---|
| **学生** | ✅ **必发** | 收件人 = `op.student.user_id`（无账号或就是审批人则跳过，照 `registration.py:107-110`）；事件 key **复用 `subject_reg_result`**（P4 拍板：**不新增 key**；白名单登记在 `custom_addons/edu_portal/models/notify_pref.py:15-24`）；正文**必须自证是这一次的变更**：「原课程/班 → 新课程/班」（照 C-1 §7.4 #2 的"不允许只发『课表变了』这种无法核对的话"）。 |
| **教师（旧班 + 新班）** | ⚠ **建议纳入（拍板项 P9）** | 理由：换班后**旧班**的点名表/评教名单**立刻不再包含他**（`roles.py:368-370`、`:477-478`、`eval_portal.py:62-64`），**新班**名单立刻多出他 ⇒ 教师是**受影响方**。本仓已有"通知任课教师"的落地先例 = C-1 的 `_notify_session_change`（`custom_addons/edu_schedule/models/session_ext.py:670`；收件人 `_reminder_users` `:273-282` = 课节学生 ∪ `faculty_id.user_id`）。**教师收件人口径**建议 = 该班 `op.session.faculty_id` 去重（本仓**没有班主任字段**：`op.batch` 只有 code/name/start_date/end_date/course_id/active，`openeducat_core/models/batch.py:30-36`）；**仍复用同一个 key**。⚠ 代价必须说清：这会让教师也收到 `subject_reg_result`（展示名「选课审批结果」，`notify_pref.py:20`）——若校长要求"教师通知"可单独静音，则**必须新增 key**（与 P4 冲突）⇒ 属拍板项。⚠ 另：**课表里没有任何课节的班取不到教师**（生产 `batch 8` 就没有任何 `op.session`）⇒ 该班换入/换出时教师通知会是 0 人（写入 §19.10 未验证）。 |
| **家长** | ❌ 不通知 | 沿用需求 7 §12.3 口径（v1 P3 同答） |
| **教务** | ❌ 不重复通知 | 教务就是操作人 |

**不新增通道**（§11 的红线不变）：`edu.message._notify_event`（`notify_pref.py:51`）+ `edu.audit.log._log`（`audit.py:29`）+ `mail.thread`；**不使用 `edu.telegram.outbox`**（`deprecated-inventory.md` §0.1 红线）。

### 19.6 本次独立复核的读数（只读 SELECT；v1 §17-1 的生产缺口已补）

| 对象 | 本地 `edu19` | **生产 `edu19`**（`ssh prod-host` → `edu19-prod-db-1`，**只读 SELECT**） | 对设计的意义 |
|---|---|---|---|
| `op_subject_registration` | 12 行 = `course_change/submitted` **11** + `subject_registration/approved` 1（ids 10–19 与 72、536） | **1 行**：id **19** / `SR0017` / `subject_registration` / `submitted` / student 11 / course 16 / batch 13 | **生产没有任何 `course_change` 单** ⇒ ①"11 张孤儿单"是**本地夹具**，不是需求证据（v1 §0 把它当"最强证据"是**高估**）；②候选 ① 在**生产**没有历史语义包袱 |
| 11 张单的创建者 | `create_uid = 8`（ids 10–19 全部），而 `res_users.id 8 = stu@local` | — | v1 §17-2「来源未定」⇒ **本轮补上 create_uid 级证据**：全部由**学生本人账号**创建，与冒烟脚本身份一致（`scripts/smoke_b_submit_faculty.py:118-133`、`scripts/test_submit_flows.py:59-77`）⇒ 判定为**夹具**，不得当"真实申请"用 |
| `op_student_course` | 4 行，1 行 running（id 9 = student 5 / course 18 / batch 8 / `roll_number` NULL）；chatter：`mail_message` 11 条（**全为"创建"备注**）、`mail_tracking_value` **0 行** | **1 行**：id 13 / student 11（王佐）/ course 16 / batch 13 / running / **`roll_number = BED2026-WZ001`（非空，且含课程码）** | ①"多 running 档案"风险**生产当前也不存在**（两边各 1 行）⇒ 但**换课通过后会变成 2 条**（B1 诊断 §6.4）；② `roll_number` 生产非空 ⇒ **v1 §17-6「本地测不到」在生产是活的**（见 P8） |
| `op_batch` | 17 条全 `active=t`；`course_id=18` 只有 batch 8（**无同课程第二班** ⇒ v1 §6「验收必须现场造班」仍成立） | 19 条全 `active=t`；`course_id=18` 只有 batch 8；**额外有 batch 27（`course_id=13`，属另一课程）** | ⇒ **生产已存在"换课程"的合法目标班**（课程 13 → 班 27），本地没有 ⇒ 本地验收需造**两类**夹具：同课程第二班 + 另一课程的班 |
| 成绩 / 考勤 / 课节 | `op_exam_attendees` **1**、`op_attendance_line` **47**、`op_session` 288（100% 挂班、100% 有 `faculty_id`） | `op_exam_attendees` **0**、`op_attendance_line` **0**、`op_session` 216 | ⇒ §19.2.2 #2 的"不会漂移"在生产当前是"**无数据可漂**"；机制风险一旦有成绩就生效 ⇒ **#2 的实证必须在本地做**（生产取不到正对照） |

### 19.7 复核结论：与原稿不符 / 需订正（**3 条**）

| # | v1 原文 | 复核结果 | 处置 |
|---|---|---|---|
| 1 | §3.2 ④-A：「`batch3.py:277-278` 建单时 `batch_id` **直接取学生当前档案的班**」 | **半对**：`batch3.py:277` 是「表单传了 `batch_id` 就用表单的，**只有没传才回落到"当前档案的班"**」；而模板 `views/batch3.xml:176-188` **只渲染了 `course_id`**（没有 `batch_id` 输入）⇒ **实际行为与 v1 描述一致，但原因不同**：不是路由"只取现班"，而是**表单没让填班**。 | 订正措辞；并把它变成**有利证据**：该路由**本来就是按"目标课程 + 目标班级"成对写的**（服务端早就在读 `batch_id`）⇒ 候选 ① 只需**补一个 `select`**（§19.1.2 理由 3）。 |
| 2 | §3.2 ② / §18：「『教务另有换课流程』在仓内**查无实据**」 | **不完整**：另有一处同类失效注释 —— `custom_addons/edu_portal/controllers/batch2.py:615-616`「待批选课…**课程变更单走既有 `/course/change/request` 学生流程**」（而该流程恰恰**没有**教务审批入口）。 | 一并订正；候选 ① 的改动清单里加上它（避免后人再被这两句注释误导）。 |
| 3 | §3.4 / §12.2：「**写库入口唯一** = `registration.py:178-201`」；§8.3 R1 引 `eval_portal.py:56-57` | **需限定作用域**：① 该结论只在 `custom_addons/` 内成立；**基座另有两条现成写路径**：`openeducat_erp/openeducat_activity/wizard/student_migrate_wizard.py:101-123`（旧档案置 `finished` + **新建目标课程档案** + 建 draft 单 —— **这就是基座对"换课程"的既有语义**，与 §19.2.2 #4 的"不可逆"路径同型）与 `openeducat_erp/openeducat_admission/models/admission.py`（`:491-492` 继承 `op.student.course`；建档写 `batch_id`，台账 C-3 行已登记）；两模块**本地与生产都是 `installed`**（本轮复核）。② 评教名单口径实测行号是 `edu_eval/controllers/eval_portal.py:62-64`（按 `lnk.batch_id`），**不是 `:56-57`**。 | 订正；V11 的 grep 口径补一句「**仅统计 `custom_addons/`**」。 |

### 19.8 收口触发条件（v2；接续并替代 v1 §7.4 的 B1–B5）

| 编号 | 触发条件（可观察、可判定） | 触发后必须做什么 |
|---|---|---|
| **C1** | `op.subject.registration` 出现**第 3 个用途**（`_DOC_TYPE` 出现第 3 个值，或"归属变更"再被另一个 `doc_type` 承载） | 停手：把"归属变更"从选课注册单里拆出去（= 承认单表承载不了） |
| **C2**（= v1 B2 = 需求 7 §8.4 T3） | 出现**第二个"给学生定班"的写库入口**：`grep -rn "op.student.course" --include=*.py custom_addons/ \| grep -n "\.create("`（同款把 `.create(` 换成 `.write(` 再跑一次）命中第 2 个文件/方法 | 停手回第 0 步。⇒ **本设计的 `action_course_change_approve()` 必须落在 `registration.py`（与既有写库点同文件），否则 C2 当场触发** |
| **C3** | 出现**第 2 条 running 档案**：`select student_id from op_student_course where state=running group by 1 having count(*) > 1` 有命中 | 立即处置：与 §19.2.2 #5-(a) 口径冲突，须先决定"并集显示"（B1 诊断 §7-R2）还是"拒绝多档案申请" |
| **C4** | 出现"档案课程与成绩课程不一致"的学生/教务投诉 | = §19.2.2 #3-② 落地：需为"历史归属"另立**只读**口径（读 `edu.audit.log` + chatter），不得靠改档案行"补历史" |

### 19.9 验收增量（接在 §15 的 V1–V14 之后）

| # | 步骤（可原样执行） | 通过线 | 反例（**不许这么写**） |
|---|---|---|---|
| **V15** | **换课程正例**：学生选「目标课程 = 另一 `active` 课程 + 该课程的 `active` 班」提交 → 教务通过 | ① 档案**仍是同一行**（`op_student_course` 总行数不变）；② `course_id` 与 `batch_id` **同时**变成目标值，且满足 `batch.course_id == course_id`；③ `subject_ids` **已被重算为目标课程科目集**（与 `op.course.subject_ids` 断言交集）；④ `state` 仍 `running`；⑤ 通知正文含「原课程/班 → 新课程/班」 | ❌ 只改 `course_id`（半写）；❌ 走了 create 分支（行数 +1） |
| **V16** | **成绩不漂移**（**必须在本地做**：本地有 `op_exam_attendees` 1 行 + `op_marksheet_line` 1 行；生产两者为 0，取不到正对照） | 换课程前后：`op_exam_attendees` / `op_result_line` / `op_marksheet_line` / `op_attendance_line` 的**行数与各自 `course_id`/`batch_id` 值一字不变** | ❌ 只断言"页面还能看到成绩"（v1 §15.3 已列同款反例） |
| **V17** | **可逆性（跨课程版）**：再提一张单换回原课程/原班 → 通过 | `course_id` 与 `batch_id` 都回到原值；**无 `IntegrityError`**；档案行数不变 | ❌ 不测反向（若误用 `action_enroll_approve` 的 create 分支，这里必炸） |
| **V18** | **`roll_number` 预检**：在本地造一条"目标课程 + 目标班 + 同 `roll_number`"的他行 → 教务通过 | **被拒绝 + 人话提示**；档案未变。**并须在生产上做一次只读预演**（生产 `roll_number` 非空，本地全 NULL 测不到） | ❌ 本地 `roll_number` 全 NULL 就宣称通过（v1 §17-6 的坑） |
| **V19** | **填报口径**：学生页下拉 | 目标课程下拉**不含** `active=false`；目标班级下拉**随所选课程联动**且不含 `active=false`；页面显示当前课程/班 | ❌ 照抄既有换课页的 `search([], limit=50)`（`batch3.py:241`，不过滤 active） |
| **V20** | **通知收件人**（若 P9 选 (b)） | 旧班 + 新班的任课教师各收到 1 条；学生 1 条；且 `/my/notify` **未新增第 8 个开关**（P4） | ❌ 新增第 3 个"归属类" key（v1 §7.4 B4 的触发条件） |
| **V21** | **队列不再"看得见点不开"** | 教务能在审批页看到并操作变更单；**教师仍看不到**（v1 §10.3 矩阵不变）；教师身份直接 POST → 303 且状态未变 | ❌ 只测"教务能批"（要正反对照，v1 V12 同款） |
| **V22** | **11 张本地夹具单的处置**（若 P10 选 (b)） | 它们在队列中可见；点通过 → **被拒绝 + 提示重提**（结构不自洽：`batch 8` 属课程 18，单写课程 13）；**不产生任何档案写入**；生产**无此单**（0 张） | ❌ 让教务点通过时炸 `ValidationError`（`registration.py:147-150`） |

### 19.10 §19 的未验证项（**不得当结论用**）

| # | 未验证项 | 说明 |
|---|---|---|
| **v2-1** | **换课程时 `academic_term_id` 是否应换** | v1 口径是"沿用同学同课程档案的学期，否则按今天取进行中学期"（`registration.py:172-176`）。换课程后新旧课程可能属不同学年学期，而**本地与生产各只有 1 个 `op.academic.term`** ⇒ **无法验证**；实现时按 `_running_term()` 走并留审计。 |
| **v2-2** | **学费字段**（**v1 未覆盖**） | 档案行上另有 `fees_term_id` / `fees_start_date` / `product_id`（`openeducat_fees` 写在 `op.student.course` 上，见 `openeducat_fees/views/fees_terms_view.xml:123-126` 继承该表单）⇒ 换课程后**不会自动改**；是否要连带处理**未验证**（财务口径，建议单独拍板）。 |
| **v2-3** | **教师通知的精确口径** | 本仓无"班主任"字段，只能按 `op.session.faculty_id` 去重 ⇒ **课表里没有任何课节的班取不到教师**（生产 `batch 8` 即无 `op.session`）⇒ 该班换入/换出时教师通知为 0 人，属**已知边界**，需在验收里显式记录。 |
| **v2-4** | **P9 若选 (b) 的开关语义** | 教师收到的是 `subject_reg_result`（展示名「选课审批结果」，`notify_pref.py:20`），**只改 label 不改 key** 是否够用**未验证**（属用户可见文案变更）。 |
| **v2-5** | **基座第二条建档路径的细节** | `openeducat_admission` 的建档写库路径（台账 C-3 已登记 `models/admission.py:245-301`）本轮**只复核到"模块 installed + `:491-492` 继承 `op.student.course`"**，**未逐行读其对 `batch_id` 的写法** ⇒ **不得**当"第二条定班入口"的结论用（§19.7 订正 3 的括注）。 |
| **v2-6** | **生产不可逆性未实测** | 本次对生产**只做了 SELECT**；"换课后换回来"的可逆性**只能**在本地 clone 上实测（V17），生产验证须等队长授权（任何写操作均未做）。 |

## 20. 变更记录

| 日期 | 改动 | 责任 |
|---|---|---|
| 2026-09-18 | 建立本文（学生申请调班 → 教务审批）：第 0 步查重（§3：六路搜 + 11 张孤儿单证据链 + 6 条负结论）**+** 第 0 步 ④⑤（§5 升级写业务表风险，含 `_infer_doc_type()` 这条**静默改写路径**；§6 演示数据策略）**+** 第 3 步读参考（§14：Odoo 社区版无 Approvals=实查 0 命中；Moodle 组自选=即选即入，**直连 403 已标未验证**；回引 `scheduling-approaches.md:373` 并说明**有意偏离**）**+** 第 4 步设计摘要（§7 裁定=**复用**；§8 生效语义=**当场改写 batch_id**；§9 审批人；§10 入口/路由/权限四层；§11 通知留痕复用 C-1 通道；§12 与需求 7 的关系；§15 真机验收 V1–V14；§16 拍板 6 项）。**未写一行代码、未新建模块、未动 `openeducat_erp/` 与 `custom_addons/`、未改库**（全部读数为只读 SELECT） | 设计子代理（调班申请，`docs/plans/class-change-request-design.md`） |
| 2026-09-18 | **v2 修订（校长 P6 改判「课程也可以换」）**：文首新增「修订记录」段（原因/日期/受影响章节清单，**v1 原文一字未删**）；**§19 = 本次修订正文**（19.0 边界新表述 ｜ **19.1 载体重新裁定 = 改判为「修好既有 `/course/change/request` 链路并收口成唯一入口」**，不新增 `doc_type`/不新增路由族 ｜ **19.2 生效语义重做**：换课程必须一次 `write()` 原子写 `course_id + batch_id + subject_ids + academic_term_id`；**成绩/考勤零物理漂移**（`op.exam.attendees` 挂 `student_id+exam_id`、`op.attendance.line` 挂 `student_id+attendance_id`，课程来自考试/点名表，不引用档案）；**唯一约束规避仍成立但前提收紧为"永不新建行"**，并点出打破前提的现实路径 = `action_enroll_approve` 的建档分支 + 多 running 档案；**新暴露结构缺口 = 单据只有目标一对、换课程时无来源可反查** ｜ 19.3 拍板项 P1′/P6′/P7–P10 ｜ 19.4 学生填报（课程 + 班级成对，均按 `active=True`，照 `enroll.py:79-80`、`:93-95`）｜ 19.5 **通知收件人重做**（学生必发 + **建议纳入旧班与新班任课教师**，同一 key）｜ **19.6 生产只读读数**（生产 `op_subject_registration` 仅 1 行、`course_change` 0 行、`op_exam_attendees`/`op_attendance_line` 均 0 行、王佐 `roll_number` 非空、batch 27 属课程 13）｜ **19.7 与原稿不符 3 条**（取班口径措辞 / `batch2.py:616` 同类失效注释 / 写库入口唯一性的作用域与 `eval_portal` 行号）｜ 19.8 收口触发条件 C1–C4（C2 接续原 B2）｜ 19.9 验收增量 V15–V22 ｜ 19.10 未验证项 v2-1…v2-6）。原 §19「变更记录」重编号为 §20（内容未改）。**本次未写一行代码、未改 `custom_addons/`、未改 `openeducat_erp/`、未改库；生产仅只读 SELECT** | 设计子代理（调班设计修订 v2，`docs/plans/class-change-request-design.md`） |
