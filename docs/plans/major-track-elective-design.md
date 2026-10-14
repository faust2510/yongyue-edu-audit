# 专业编排（学制 + 必修/选修）设计
> **状态**：`已上线` ｜ **主题**：`专业编排（学制·必修选修）` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「仅设计——本次未写一行代码、未新建模块」，实际已于 `d1a37f8` 交付（2026-09-26 核对发现）。正文未改动。

> **历史状态**：仅设计（第 0 步「落地前查重」+ 第 3 步「读参考」+ 第 4 步「设计摘要」）。
> **本文件不代表已实施**——本次**未写一行代码**、**未新建模块**、**未改 `custom_addons/`**、**未改 `openeducat_erp/`**、**未改任何库**。
> **需求一句话**（校长原话）：「我现在需要你给教务人员和管理员在**课程编排**那里，可以自己做选择进行分类，比如说**标记哪些学制需要学什么课**，**哪些是选修，哪些是必修**，都有教务老师和管理员说了算。」
> **口径来源**：`docs/dev-workflow.md` 第 0 步 + 六步闸门 ｜ `CLAUDE.md` 铁律 0 ｜ `docs/audit/deprecated-inventory.md`（C1–C7 删除门槛）｜ `docs/ops/menu-rename-list.md`（改名体例）
> **采集时刻**：**2026-09-19**。读数口径 = **生产** `prod-host` / 容器 `edu19-prod-db-1`（只读 SELECT，**未触碰 `edu_telegram`/`edu_feedback`**）+ **本地** `edu19`（只读 SELECT）+ 仓内 `openeducat_erp/` 快照（19.0）+ 容器内 Odoo 19 运行时源码（`/usr/lib/python3/dist-packages/odoo/`）。
> **行号取证** = 本工作区当前 HEAD 的仓内文件。
> **未验证项**一律集中写在 §10，**不得当结论用**（本仓规范）。
> ⚠ **合规红线**：本文**不贴 `openeducat_erp/` 任何源码**，只给**路径 + 行号 + 字段/记录命名**。

---

## 0. 结论速览（TL;DR）

| 项 | 结论 |
|---|---|
| **第 0 步查重** | **未命中任何已存在的「专业↔科目 必修/选修 配置」实现**（§3 逐条命令 + 命中行号 + 扫过范围）。命中的是**承载物**（不是重复物）与**一处真正的重复概念**（`op.program`，见下）。 |
| **头号发现（改名地雷）** | 生产菜单里**已经有一条叫「专业」的菜单**：**276 `op.program`**（`docs/ops/menu-rename-list.md:29` 由 t117 从机翻「节目」改来）。校长要求把 **263 `op.course`「课程」改成「专业」** ⇒ **会撞名**。必须同时处置 276/277，否则教务会看到两个「专业」（§6.6）。 |
| **第二个发现（改名机制）** | 本仓既有改名机制是 **`edu_zh` PO 按 `msgid` 覆盖**，而 **PO 覆盖按 msgid 全局生效**（`docs/ops/menu-rename-list.md:93-95` 自己写了这条）。`Courses` 这个 msgid **不止 263 用** ⇒ **不能**用 `Courses → 专业` 直接覆盖（会把生产**仍启用**的 561「课程」=`slide.channel` 一起改掉）。必须**改 263 的 en_US source** 再 PO 新串（§6.6.3）。 |
| **学制载体裁定** | **复用基座 `op.program.level`（菜单 277）**，**不新建表**；但**不走 `op.program` 中间层** —— 在 `op.course` 上**新增一个直连字段 `edu_level_id`（M2O → `op.program.level`）**。理由见 **§5.2**（`op.program` 生产 **0 条**、`op.course.program_id` **6/6 全 NULL** ⇒ 中间层是纯负担）。 |
| **关系表裁定** | **新建 through 模型 `edu.course.subject`**（表 `edu_course_subject`），**单一事实源**；`op.course.subject_ids` **保留原名**、改为**非存储 computed Many2many + inverse + search** ⇒ 既有 20+ 个消费点**零改动**（§6.3）。 |
| **零数据迁移的真相** | 「零迁移」指 **教务侧不用重配任何一条**（334 条关系搬过来时 `subject_type` **全部留空 = 继承全局**）——**不是**指「不搬数据」。搬迁是 1 条 `INSERT..SELECT`，可逆、可核对（§6.4）。 |
| **报课页读取口径** | 三级 fallback：**该专业该科目的行值 → 科目全局 `subject_type`**（**只有两级**，学制层**不参与**判定；学制只是专业上的分类维度）。落地为 `op.course` 上一个模型级 helper，`enroll.py` 两处改调用（§6.5）。 |
| **权限** | 配置面 = **教务 `openeducat_core.group_op_back_office_admin` + `base.group_system`**（校长原话）。菜单 263/277 **本来就只挂教务组**（生产实测 `ir_ui_menu_group_rel`）；新模型的 ACL 按四层规范给这两组，**不给 `group_user`**（§6.7）。 |
| **本设计明确不做** | 不新建模块、不新建「学制」表、不新开门户页/后台页、不换菜单位置以外的入口、不动 `openeducat_erp/`、**不重命名门户「我的课程」**（§1.2）。 |
| **待校长拍板** | **5 项**（276/277 怎么处置 / 262 容器改名 / 门户「课程」字样是否一并改 / 要不要「学制级默认」第三层 / 学生档案上要不要显示学制），见 §9。 |

---

## 1. 目标 / 非目标

### 1.1 目标（逐条可验）

| # | 能力 | 用户感受 | 现状 |
|---|---|---|---|
| **G1** | 教务给**专业**标**学制**（本科 / 专科 / 硕士…） | 专业列表能按学制筛/分组 | ❌ `op.course` **没有**任何学制字段（生产 6 条 `program_id` 全 NULL） |
| **G2** | 教务在**已存在的「专业」表单 → Subjects 标签页**给每门科目标**必修 / 选修** | 一个清单、多一列，配完即生效 | ❌ 现在只有**科目全局** `op.subject.subject_type`（生产 147 门 = 必修 25 / 选修 122） |
| **G3** | **没配的专业仍继承全局值** | 教务**一条都不用重配** | —（新增能力，要求零配置也能跑） |
| **G4** | 学制的**可选项由教务自助增删** | 加一个「博士」不用改代码 | ⚠ 表在（`op.program.level`）但**入口不在教务动线上**（在「项目管理」下）、**数据 0 条**、**没有停用开关** |
| **G5** | 报课页对**该专业学生立刻生效** | 教务配完，学生刷新报课页就看到新分组 | ❌ 现在按**全局** `subject_type` 分组 |
| **G6** | 界面上把「课程」改名为**「专业」**（**限定范围**） | 教务在「配置 → 课程管理 → 专业」里配 | ⚠ 见 §6.6：**撞名**（276 已叫「专业」）+ **改名机制是全局 msgid**，两处都得处理 |
| **G7** | **只有教务 / 管理员**能改这套配置 | 教师改不了 | 菜单已天然满足（263/277 只挂教务组），但**新模型 ACL 必须显式收口** |

### 1.2 非目标（明确不做，避免范围漂移）

- **不新建模块**：落 `custom_addons/edu_portal`（既依赖 `openeducat_core`，又已拥有 `op.subject`/`op.student.course` 的继承先例与全部门户消费点）。
- **不新建「学制」表**（复用 `op.program.level`，见 §6.1）。
- **不新建后台页面、不新建门户路由**：配置面 = **已有的** 263「课程」表单 Subjects 页；学制维护 = **已有的** 277。
- **不改 `openeducat_erp/` 任何一个文件**（含 `course_view.xml`、`openeducat_core_menu.xml`）——全部用**继承视图 / 记录覆盖**。
- **不删任何记录**（本仓红线）：`op_course_op_subject_rel`、`op.program`、菜单 275/276/277 一律**只留不动**；确需隐藏的走 `active=False` 并登记台账。
- **不做「学制级默认」第三层**（只做两级 fallback，见 §6.5；理由与唤醒条件见 §9-P4）。
- **不改门户「我的课程」/LMS**（`/my/courses` 列的是**科目**，见 §6.6.4）。
- **不做选课学分/容量/先修校验的改动**（`edu.subject.prereq` 原样，`enroll.py:149-169` 不动逻辑，只换数据来源）。
- **不动 `op.subject.subject_type` 的全局语义**（它成为「默认值」，不是「废弃字段」）。

---

## 2. 第 0 步①：先信 code-map

`docs/code-map.md` 逐条读后与本设计相关的锚点：

| 位置 | 内容 | 对本设计的含义 |
|---|---|---|
| `code-map.md:148` | 基座 `openeducat_core` =「学生/教师/课程基座：`op.student`、`op.student.course`、… `op.course`、`op.batch`、`op.subject`、`op.subject.registration`… `op.program`、`op.category`」 | 专业/科目/学制**全在基座**；本设计第一优先是证明**基座够用、不新建** |
| `code-map.md:161-165` | 权限四层：`group_op_faculty`（教师）/ `group_op_back_office_admin`（教务，**基座源码里它 imply `base.group_system`，本仓 2026-09-17 已解除**） | 所有权限结论必须与四层对齐（§6.7）；**不得**给教务补 imply |
| `code-map.md:255-263` | 权限四层硬约定：教务侧写 `groups="openeducat_core.group_op_back_office_admin,base.group_system"` 并列；「看得见点不开」缺一即死角；菜单可见性口径一律用**口径 B** | 菜单/ACL/ir.rule/控制器**四件套**都要交代 |
| `code-map.md:245` | 约定第 3 条：**不建自定义组**，复用四层 | 本设计 **0 个新组** |
| `code-map.md:249` | 「新功能三件套：先写 `docs/plans/<功能>-design.md` 再动工」 | 本文件就是那个前置件 |
| `code-map.md:169` | 重复登记写 `docs/audit/deprecated-inventory.md`，不写 code-map | 本设计已追加 1 行（§3.6） |
| `code-map.md:30` | 升级一律 `bash scripts/safe_upgrade.sh <模块>`；**`-i` 对已装模块不重载 data/view** | 验收必须用 `-u`（§7） |
| `code-map.md:31` | 汉化验收 `python3 scripts/check_english.py`（must-fix = 0） | 新增英文串（若走「改 en_US source」）必须过这条门禁（§6.6.3） |
| `code-map.md:252` | 无障碍硬约定；门禁 `scripts/check_accessibility.py` | 新增的「必修/选修」控件必须有可访问名（§7-V8） |
| `code-map.md:254` | QWeb 遍历 dict **必须显式 `.items()`**；门禁 `scripts/check_qweb_dict_foreach.py` | 若新分组数据以 dict 传模板，必须 `.items()` |
| `docs/ops/menu-rename-list.md:29-30,64,85-89,93-95` | 276「专业」/277「专业层次」是 t117 已改好的**要保护**的成果；263「课程」在**不得改坏的回归对照**清单里；**PO 覆盖按 msgid 全局生效** | **改名范围与机制**的直接依据（§6.6） |

---

## 3. 第 0 步②③：查重实跑（命令 + 命中行号 + 扫过的范围）

> 口径：`grep` 一律**全仓**（含 `openeducat_erp/`、`custom_addons/`、`scripts/`、`tests/`、`docs/`），排除 `node_modules`。
> **命中 ≠ 活路径**：下面每条都判定「活路径 / 只读引用 / 注释 / 历史文档」。
> **「没找到」也留证据**：写明扫了哪些范围、用什么方式。

### 3.1 候选前缀 / 模型名查重 —— **候选新模型名 `edu.course.subject` 全仓 0 命中**

```bash
grep -rn "edu\.course\.subject\|edu_course_subject\|class EduCourseSubject" --include=*.py --include=*.xml --include=*.csv .
```

- 结果：**0 命中**（扫过：`custom_addons/` 全 9 个模块、`openeducat_erp/` 14 个模块、`scripts/`、`tests/`）。
- 同类命名（`edu.*` 里带 subject 的模型）：`custom_addons/edu_portal/models/course_rep.py:136,451`（课代表 × 科目）、`custom_addons/edu_portal/models/lms.py:17`（LMS 资料 × 科目）、`custom_addons/edu_portal/models/leave.py:81`（请假 × 科目）、`custom_addons/edu_portal/models/downloads.py:80`（资料 × 科目）、`custom_addons/edu_portal/models/registration.py:502,504`（先修关系 `edu.subject.prereq` + 行模型）——**没有一个是「专业 × 科目 × 必修/选修」**。

### 3.2 `subject_type` 的全部命中 —— **本仓消费点只有 1 个控制器 + 3 个测试**

```bash
grep -rn 'subject_type' --include=*.py --include=*.xml --include=*.js --include=*.md .
```

| 命中位置 | 判定 |
|---|---|
| `openeducat_erp/openeducat_core/models/subject.py:36-38` | **字段定义（全局）**——就是本需求要「按专业下放」的那个字段。`Selection([('compulsory',…),('elective',…)])`，`default='compulsory'`，`required=True` |
| `openeducat_erp/openeducat_core/models/subject_registration.py:100` | **活路径**：`get_subjects()` 把 `course_id.subject_ids` 里 `subject_type=='compulsory'` 的灌进注册单 `compulsory_subject_ids`（`:95-102`） |
| `openeducat_erp/openeducat_core/views/subject_view.xml` | 表单/列表字段展示（只读渲染） |
| `openeducat_erp/openeducat_core/views/subject_registration_view.xml:16,66-69` | 注册单视图；`:69` 的 `domain="[('subject_type','=','elective')]"` 是**全局**口径 |
| `openeducat_erp/openeducat_exam/wizard/room_distribution.py:73,76` | **活路径**：考场分配向导按 `subject_type` 判必修/走 `elective_subject_ids` |
| `openeducat_erp/openeducat_core/tests/test_openeducat_core_comprehensive.py:57` | 基座自带测试（夹具） |
| `custom_addons/edu_portal/controllers/enroll.py:34,160-162,236` | **本次要改的唯一活业务消费点**（报课页分组 + 服务端补齐必修） |
| `custom_addons/edu_telegram/controllers/portal_ops.py:45` | **已退役模块**（`docs/audit/deprecated-inventory.md` §0.1/B8；从未部署）——**不在范围** |
| `tests/smoke/authz_endtoend_smoke.py:263`、`tests/smoke/p2_enroll_smoke.py:174,255,318`、`tests/smoke/course_rep.py:370,373` | 冒烟夹具（造 `elective` 科目）——**改造后需回归**（§7-V7） |
| `scripts/import_curriculum.py`、`scripts/seed_yongyue_data.py`、`scripts/seed_wangxiaoming_subjects.py`、`timetable_import/import_sessions.py`、`timetable_import/catalog.md` | 导入/种子脚本（写全局值）——**保持写全局，不改语义** |
| `docs/plans/scheduling-overhaul-design.md:170,195-197`、`docs/plans/enroll-v2-design.md:27,105-115,186-188,364,417`、`docs/audit/task-B1-enroll-timetable-gap.md` | 历史文档（**只读引用**；其中 `enroll-v2-design.md:188` 明确写「沿用基座字段，不另加 m2m 表」——**本设计的 §6.3 正是对这句话的修订**，见 §6.3.5） |

### 3.3 `compulsory` / `elective` —— 没有第二套「专业级」实现

```bash
grep -rn 'compulsory\|elective' --include=*.py --include=*.xml --include=*.js --include=*.md .
```

- **本仓自研侧**：`custom_addons/` **0 处** 读/写必修选修语义（除 `edu_telegram` 退役模块的 `portal_ops.py:45`）。
- 基座侧命中全部落在 **`op.subject.registration` 的两个 M2M**（`subject_registration.py:37-42`，表 `subject_compulsory_rel` 与 `op_subject_registration_elective_subject_ids_rel`）与它的视图（`subject_registration_view.xml:16,66-69`）。
- ⚠ **这不是「专业↔科目配置」，是「一张选课单要选哪些科目」**——语义不同轴，**不得拿它当载体**（它就是本仓 `doc_type='subject_registration'` 审批单的基座原型，`custom_addons/edu_portal/models/registration.py:29-32`）。
- 测试夹具旁证：`tests/smoke/class_change_request.py:468,642,1005,1126` 断言 `subject_compulsory_rel` 的条数（**调班单不得携带科目集**这条硬约束，见 `docs/plans/class-change-request-design.md:195`）。

### 3.4 `subject_ids` 的全部消费点（`op.course` 视角）—— 见 §6.3 的逐条清单

```bash
grep -rn 'subject_ids' --include=*.py --include=*.xml --include=*.js .
```

分三类（**逐条行号见 §6.3.1**）：

1. **`op.course.subject_ids`（本设计的字段）**：`enroll.py:147,232,483`、`lms.py:24-30`（经 `op.student.course`）、`batch1.py:316`、`registration.py:439,466`、`edu_public/controllers/main.py:57`、`services`：`openeducat_core/models/subject_registration.py:98-99`、`openeducat_timetable/models/timetable.py:86-88,407-412`、`openeducat_assignment/models/assignment.py:104`、`openeducat_erp/openeducat_core/views/course_view.xml:15,54`、`openeducat_timetable/views/timetable_view.xml:146,167-168`。
2. **`op.student.course.subject_ids`（学生的档案科目集，**不是**本设计的字段）**：`lms.py:29-35`、`batch2.py:143,993,1322-1328,1409-1419`、`batch3.py:478,599-608,785`、`course_rep.py:184-193,264-290,528`、`downloads.py:153`、`registration.py:535,552-564`、`scripts/seed_wangxiaoming_subjects.py:17,102,113,120`。**这些一行都不用改**（本设计不碰档案行）。
3. **测试夹具**：`tests/smoke/{authz_endtoend_smoke,p2_enroll_smoke,course_rep,class_change_request,class_batch_mgmt,subject_bulk_scope,class_batch_mgmt_ui}.py`。

> **反向证据（很关键）**：全仓 **没有任何一处** 对 `op.course.subject_ids` 做 **domain 过滤** ——
> ```bash
> grep -rn "('subject_ids', 'in'" custom_addons/
> ```
> 9 条命中**全部**落在 `op.student.course`（`registration.py:535`、`downloads.py:153`、`course_rep.py:193,290,528`、`batch2.py:1328,1419`、`lms.py:385,424`）。
> ⇒ 兼容层即使做成非存储 computed，**也不会踩到 `op.course` 上的域查询**（`search` 仍必须实现，见 §6.3.3）。

### 3.5 同义前缀扫描 —— `major` / `专业` / `学制` / `program_level` / `track`

```bash
grep -rniE 'major|专业|学制|层次|program_level|program\.level|degree|track' --include=*.py --include=*.xml --include=*.csv custom_addons/
```

| 命中 | 判定 |
|---|---|
| `custom_addons/edu_portal/models/partner_edu.py:6,19-20` | ⚠ **同名词、不同物**：`res.partner.street2` 改文案为「学制」（注释写明「即本科、硕士等」）——**这是联系人/学生档案上的一个自由文本 Char**，不是可选的学制表、没有 FK、没有唯一约束。→ **不复用它**（它挂在 `res.partner` 上、由人事/注册场景填写；本需求要的是**专业上的分类维度**），但**保留不动**（改了会波及门户「我的账户」，见 §6.6.4）。**入选台账登记项**（§3.6 第 ② 条） |
| `custom_addons/edu_assess/models/assess.py` 的 `EduAssessTask.scope_program_ids` 与 `EduAssessTask._roster_students`（后者用 `course_detail_ids.course_id.program_id` 收敛） | **形态可抄的先例**：`scope_program_ids = Many2many('op.program', 'edu_assess_task_program_rel', …)` + 用 `course_detail_ids.course_id.program_id` 收敛参与学生 ⇒ 证明「教务在后台勾一个配置、影响门户可见范围」这条链路本仓已跑通 |
| `custom_addons/edu_apply/models/application.py:20,100-101` | `track`（Selection，`'3+1制本科班'/'家教学院'/'3+2制本硕连读'`）、`major`（Char 科系主修）、`degree`（Char 学位）——**报名表单的自由文本字段**，与在读专业无 FK。**不动、不合并**（报名表是元数据驱动的历史表单，`edu_apply/data/form_meta_data.xml:5,41-43,180-189`） |
| `custom_addons/edu_brand/views/pages.xml:76,101,128,153,179,203,248` | 公开官网「专业设置」页，每个专业一条 `<dt>学制</dt>` **纯静态 HTML 文案**（3年/4年/1-2年…）——与 DB 无关。**不动**（改它要同步官网文案，超出本需求） |
| `custom_addons/edu_portal/controllers/lms.py:170,212` | 注释里的「独立评审 Major#1/#2」= **编号**，不是专业。**不相关** |
| `custom_addons/edu_multi_department`（如存在） | 无命中 |

### 3.6 查重结论（三步处置）

**① 不得直接新建？—— 命中 1 处真重复，其余都是承载物。**

| # | 对象 | 类型 | 证据 | 裁定 |
|---|---|---|---|---|
| **1** | **`op.program`（菜单 276「专业」）与 `op.course`（菜单 263「课程」）是同一概念的两种表达** | **真重复（概念级）** | 生产：`op_program` **0 行**、`op_course` **6 行**（神学学士科/文学学士/教育学士/基督教研究硕士科/家教学院/预备科）、`op_course.program_id` **6/6 全 NULL**；`op.program.level` **0 行**；全仓 `op.program` 的活消费点只有 2 处：`custom_addons/edu_assess/models/assess.py` 的 `EduAssessTask.scope_program_ids`（评估「参与专业」多选，0 数据）与 `custom_addons/edu_public/controllers/main.py:252-256`（`/program-offered`「培养项目」公开页，**0 条数据 → 空页**） | **本设计不合并、不删、不动**——只**登记**（→ 已追加台账行）。**理由**：合并它会动 `edu_assess` 的范围口径与一条公开路由，**超出本需求**；且校长只要求「专业=现在的课程」，没要求清掉 program。**但必须处置菜单撞名**（§6.6.2）。**唤醒条件**：出现第二处「给 `op.program` 写数据」的入口，或教务开始用 276 建「专业」 |
| **2** | `res.partner.street2`「学制」（`partner_edu.py:19-20`） | **同名词、不同物** | 自由文本 Char，无 FK / 无唯一约束 / 挂在联系人上 | **不合并**（本设计要的是**字典表 + FK**）。**登记**，避免下一个 agent 以为「学制已经有了」 |
| **3** | `op.program.level`（菜单 277「专业层次」） | **承载物（不是重复物）** | 表在、`mail.thread` 在、`unique(name)` 在、ACL 已给教务 CRUD、菜单已挂教务组；**数据 0 条** | **复用**（§6.1）——新建一张「学制」表**才是**制造重复 |
| **4** | `op.subject.subject_type`（全局必修/选修） | **承载物 + 缺一层** | 生产 147 门 = 必修 25 / 选修 122；`Selection` 硬编码 2 值 | **保留为「默认值」**，在其上叠加「专业×科目」层（§6.2）。**不删字段、不做数据迁移** |

**② 登记**：已按 `docs/dev-workflow.md` 第 0 步要求，在 `docs/audit/deprecated-inventory.md` **追加 1 行**（§8 变更记录表，第 ① 与第 ③ 条合并登记为一次查重记录）。

**③ 请队长裁定**：本设计已给出裁定建议（§6.1/§6.2/§6.3），其中 **涉及用户可见变化的 5 项**已单列 §9 交校长拍板。

### 3.7 第 0 步④⑤：升级会不会动业务数据 / 演示数据策略

- **④ 升级写业务数据？** 本设计**新增**的数据面只有 **菜单/动作的文案与 `parent_id`**（配置类记录 `ir.ui.menu`）——**没有** `<function>`、没有 `_load_demo`、**不写任何业务表**。搬迁脚本（§6.4）落 `migrations/`（**只在版本号变更时跑一次**），**不进 `data/`**（`data` 每次 `-u` 重放 ⇒ 这是 `edu_life/data/demo_life.xml` 的 F5 教训，`docs/dev-workflow.md:33-46,103-127`）。
- **⑤ 演示数据策略**：本设计**不产生任何演示数据**。真机验收（§7）造的样本一律带 `【冒烟】`/`【演示】` 前缀并在同一次运行内清场（照 `tests/smoke/p2_enroll_smoke.py` 的现有做法）。
- **既有数据的处置**：`op_course_op_subject_rel` **334 行一行不删**（见 §6.4）——**不满足 C1/C2 前置就不用想删表**。

---

## 4. 第 3 步：读参考（基座数据模型 + Odoo 19 机制实证）

> 只给**路径 + 行号 + 字段/记录命名**，**不贴 `openeducat_erp/` 源码**（合规红线）。

### 4.1 基座侧要用的四张表（全部现成、只读、不改文件）

| 对象 | 文件:行 | 关键事实（字段名/约束/默认值） |
|---|---|---|
| **`op.course`（= 本仓「专业」）** | `openeducat_erp/openeducat_core/models/course.py:25-59` | `name`(:30, required, translate) / `code`(:31, size=16, required) / `parent_id`(:32) / `evaluation_type`(:33-36) / **`subject_ids` = 普通 Many2many('op.subject')（:37）** / `max\|min_unit_load`(:38-39) / `department_id`(:40-43) / `active`(:44) / **`program_id` = Many2one('op.program')（:45，tracking）** / `unique(code)`(:47-48) |
| | `openeducat_erp/openeducat_core/views/course_view.xml` | `view_op_course_tree`(:3-19，`subject_ids` 在 :15) / **`view_op_course_form`(:21-62)：`<page string="Subjects" name="subject">` 在 :52-57，`subject_ids` 字段在 :54，`context="{'default_course_id': id, 'default_department_id': department_id}"`** / `program_id` 在 :48 / 动作 `act_open_op_course_view`(:108-121，`view_mode=list,form,pivot`) / `act_window.view`(:123-130) |
| | `openeducat_core/menu/openeducat_core_menu.xml` | `menu_op_school_config_course`(:43-46) → **`menu_op_course_sub`「Courses」(:48-53)，`groups="group_op_back_office_admin"`** |
| **`op.program.level`（= 拟复用的「学制」字典）** | `openeducat_erp/openeducat_core/models/program.py:46-54` | `_name='op.program.level'`、`_inherit='mail.thread'`、`name`(:51, required, translate, tracking)、`unique(name)`(:53-54)。**没有 `active` 字段**（⚠ 见 §5.4） |
| | `program_level.xml:3-47` | 列表 `view_op_program_level_tree`(:3-12，只一列 `name`)、表单 `view_op_program_level_form`(:13-38)、动作 `act_open_op_program_level_view`(:39-47) |
| | `..._menu.xml:136-141` | **`menu_op_program_level_sub`「Program Level」(:136-141)，`groups="group_op_back_office_admin"`** |
| **`op.program`（判断「要不要走中间层」用）** | `program.py:24-43` | `name/code/max\|min_unit_load/department_id/active/image_1920` + **`program_level_id = Many2one('op.program.level', required=True)`(:39-40)** |
| | `..._menu.xml:124-141` | `menu_op_school_config_program`「Program Management」(:124-127) → `menu_op_program_sub`(:129-134) + `menu_op_program_level_sub`(:136-141)，两条都 `groups="group_op_back_office_admin"` |
| **`op.subject`（默认值来源）** | `subject.py:24-53` | **`subject_type`(:36-38)：`Selection([('compulsory','Compulsory'),('elective','Elective')])`，`default='compulsory'`，`required=True`**；`type`(:32-35)；`credit_points` 等扩展由 `edu_portal/models/registration.py:488` 起的 `_inherit='op.subject'` 提供 |
| **「带字段的关系表」先例（形态照抄对象）** | `openeducat_erp/openeducat_core/models/student.py:25-51` | **`op.student.course` = 学生 × 专业 × 班级 + `roll_number` + `state`**（`:31-41`），三条 `unique` 约束（`:43-51`）——**本仓「外键 + 业务字段」的基座原生范本** |
| | `openeducat_core/models/subject_registration.py:37-42` | 基座自己的「带分区的关系」写法：两个独立 M2M（`compulsory_subject_ids` 显式给了 relation 名 `subject_compulsory_rel`，`elective_subject_ids` 用默认表名）——**说明基座也没打算给一个 M2M 挂字段**（这正是我们要补的洞） |

**基座消费点（改造后必须仍然工作）**：

| 消费点 | 文件:行 | 怎么用 `subject_ids` |
|---|---|---|
| 选课注册单灌必修 | `openeducat_core/models/subject_registration.py:98-101` | `for subject in record.course_id.subject_ids: if subject.subject_type == 'compulsory'` ⇒ **读** |
| 课表向导科目域 | `openeducat_timetable/models/timetable.py:86-88` | `course_subject_ids = fields.Many2many(related='course_id.subject_ids')`（**非存储 related**） |
| 课表冲突校验 | `openeducat_timetable/models/timetable.py:407-412` | `self.course_id.subject_ids.ids` 判科目是否属该专业 ⇒ **读** |
| 课表视图域 | `openeducat_timetable/views/timetable_view.xml:146,167-168` | `domain="[('id','in', course_id and course_subject_ids or [])]"` |
| 作业抄写科目 | `openeducat_assignment/models/assignment.py:104` | `rec.courses_subjects = rec.course_id.subject_ids`（**赋值**） |
| 后台表单 | `openeducat_core/views/course_view.xml:15,54` | many2many_tags / 内嵌列表 ⇒ **读写** |

### 4.2 Odoo 19 机制实证：**非存储 computed Many2many + inverse + search 是官方支持的写法**

（读数口径 = 本地容器 `edu19-clone-web-1` 内 Odoo 19 运行时源码 `/usr/lib/python3/dist-packages/odoo/`，**只读 grep/sed**）

| 事实 | 证据（路径:行） | 对本设计的含义 |
|---|---|---|
| 计算字段支持 `inverse` 与 `search` 两个属性 | `odoo/orm/fields.py:288`（`inverse` 属性）、`:1930-1932`（`determine_domain` **用 `self.search`** 把域名转成条件） | **`search` 必须实现**，否则任何对 `op.course.subject_ids` 的域查询会报错 |
| **`write()` 会调用 inverse** | `odoo/orm/models.py:4399`（收集 `determine_inverses`）、`:4490-4501`（写入 cache 后逐个 `determine_inverse(real_recs)`） | `course.write({'subject_ids': [(6,0,[...])]})` **能正常工作** ⇒ 既有写路径零改动 |
| **`create()` 也会调用 inverse** | `odoo/orm/models.py:4661,4682,4717-4733`（同一套机制） | 新建专业时带 `subject_ids` 的写法（`tests/smoke/authz_endtoend_smoke.py:265-266`）**也能工作** |
| **官方内核先例**：`res.users.all_group_ids` = 非存储 computed Many2many + `search` | `odoo/addons/base/models/res_users.py:258-259` | 这种「算出来的 M2M」在 Odoo 19 内核里就有；不是我方自创 |
| `related='course_id.subject_ids'` 指向非存储计算字段 | `openeducat_timetable/models/timetable.py:86-88` | related 链不受「存储/非存储」影响（`course_subject_ids` 本身也是非存储） |

### 4.3 学什么 / 砍什么

**学**：
1. **形态**：基座 `op.student.course`（`student.py:25-51`）就是「带业务字段的关系表」——**表 + 两个 FK + 业务列 + `unique` 约束**，本设计的关系表照它的规格建。
2. **配置→门户的链路**：`edu_assess` 的「参与专业/参与班级」已经跑通「教务在后台配一个范围 → 影响门户可见集合」（`edu_assess/models/assess.py` 的 `EduAssessTask.scope_batch_ids` / `EduAssessTask.scope_program_ids` 与 `EduAssessTask._roster_students`）——**抄它的交互形态**（后台一个可编辑清单，不做新页面）。
3. **权限挂法**：菜单 `groups` + ACL 双层（`code-map.md:256-263`），且**教务与系统组并列**。

**砍**（明确不学、不做）：
1. **不学 `op.program.program_level_id` 的「必填」**：学制在专业上是**可选**的（6 条存量专业全是空，硬设 `required=True` 会让升级即报错）。
2. **不学基座 `subject_registration` 的两个 M2M 写法**（`subject_registration.py:37-42`）：那是「单据上的分区」，不是「配置上的字典」，跟着它会做出**第二套**必修/选修表达。
3. **不引入 OCA/第三方模块**：本需求是**既有表的字段扩展 + 一个 through 模型**，比装任何同构模块都小（铁律 0「能装不写」在这条上不成立——**因为要装的东西比要写的大**）。
4. **不做「按学制自动生成专业科目清单」**的自动铺数据逻辑：校长要的是**教务自己选**，不是系统替他填。

---

## 5. 载体裁定之一：**学制** 用 `op.program.level`（复用），不用新建表

### 5.1 三个候选

| 候选 | 做法 | 新表 | 教务自助增删 | 存量 6 条专业 | 与基座语义 |
|---|---|---|---|---|---|
| **A（推荐）** | **复用 `op.program.level`**；在 `op.course` 新增 **`edu_level_id`（M2O → `op.program.level`，`ondelete='restrict'`）** | **0** | ✅ 表已存在 + 菜单 277 已挂教务组 + ACL 已给教务 CRUD | ✅ 新字段**可空**，6 条全空、升级不报错 | 高度一致：`op.program.level` 就是「层次/学制」的字典 |
| **B** | 走 `op.course.program_id → op.program → program_level_id`（基座原有链路） | 0 | ✅（但要**先建 program**） | ❌ **必须给 6 条专业各建 1 条 program**（`program_level_id` 必填），还会给 `edu_assess` 的「参与专业」灌进 6 条空壳 → **副作用外溢** | 一致但**多一跳** |
| **C** | 新建 `edu.course.level`（name/code/sequence/active） | **+1 表 + ACL + 视图 + 菜单** | ✅ | ✅ | ❌ 与 `op.program.level` **语义完全同构** ⇒ 制造本仓最忌讳的「一个功能的第二套实现」 |

### 5.2 裁定：**A**（复用 `op.program.level` + 直连字段 `edu_level_id`）

**理由（三条，全部可查）**：

1. **它就是那张表**。`op.program.level` 的字段面（`program.py:46-54`）恰好是「学制」所需的全部：`name`（required/translate/tracking）+ `unique(name)` + `mail.thread`。**新建 C 会与它 100% 重叠**。
2. **教务已经能维护它，且入口已挂对了组**。生产实测：菜单 **277「专业层次」** `groups` = `gid 40 = openeducat_core.group_op_back_office_admin`；模型 ACL 实测 `op.program.level` 对 gid 40 = `1,1,1,1`（读/写/建/删全给）。⇒ **不需要新增任何权限面**。
3. **`op.program` 是空壳，走它就是给自己添负担**。生产实测：`op_program` **0 行**、`op_course.program_id` **6/6 全 NULL**、`op_program_level` **0 行**。候选 B 会让教务为了标一个「本科」先建一条 `op.program`（`program_level_id` 必填 ⇒ 还要先有 level），**两层跳转、零收益**；且会给 `edu_assess` 的「参与专业」多选灌进 6 条空壳 program（`assess.py` 的 `EduAssessTask.scope_program_ids`），**副作用外溢到别人的模块**。

**为什么不新建（C）**：本仓已完成的一轮「功能重叠收口」（打卡 ×2、评估 ×2、岗位 ×2、`op.student` 双根菜单）全部是**先建后合**、再靠迁移与兼容层还债（`docs/dev-workflow.md:6-12` 自述）。新建 C 会**当场**造出第 5 处同构重复。

### 5.3 落地面（A 方案的全部改动）

| 面 | 改动 | 依据 |
|---|---|---|
| 字段 | `op.course.edu_level_id = Many2one('op.program.level', string='学制', ondelete='restrict', tracking=True)` | 照 `course.py:45` 的 `program_id` 写法 |
| 视图 | **继承** `openeducat_core.view_op_course_form`（`course_view.xml:21-62`），在选择器分组里加 `edu_level_id`；**继承** `view_op_course_tree`(:3-19) 加一列（`optional="show"`）；**继承** `view_op_course_search`(:64-87) 加「按学制分组」筛选 | 继承先例：`custom_addons/edu_portal/views/class_batch_views.xml:24,45,63`（同模块同手法） |
| 视图（学制自身） | **继承** `view_op_program_level_form`（`program_level.xml:13-38`）与 `view_op_program_level_tree`(:3-12)，加 `active` 与 `sequence` | 见 §5.4 |
| 文案 | 菜单 277「专业层次」→**「学制」**（校长用词） | §6.6.2 |
| 权限 | **不动**（表已给教务 CRUD；菜单已挂教务组） | 生产实测 |
| 数据 | **不动**（0 条 → 教务自己加） | — |

### 5.4 A 方案的两个**必要补偿**（不是可选项）

1. **补 `active`（软删/停用）**：`op.program.level` **没有 `active`**（`program.py:46-54` 通读确认）。而本仓红线是**零业务记录删除**，且我们给 `edu_level_id` 设了 `ondelete='restrict'` ⇒ 一个**已被专业引用**的学制**删不掉**，若再没有「停用」，教务加错了就**无路可走**。
   ⇒ 用 `_inherit='op.program.level'` 在 `custom_addons` 里加 `active = fields.Boolean(default=True)` + `sequence = fields.Integer(default=10)`，并在继承视图暴露。
   **先例**：本仓已在 `custom_addons` 里 `_inherit` 过基座模型（`edu_portal/models/registration.py:488` = `op.subject`；`edu_portal/models/class_batch.py:301-304` = `op.student.course`；`class_batch.py:343` = `ir.ui.menu`）。
   ⚠ **视图层的硬前提**（照 `docs/plans/class-batch-management-design.md:25` 已证的 Odoo 19 行为）：**归档动作只在「视图里有 `active` 字段」时出现** ⇒ 列表与表单**两处都要加**，否则又是「表单可用、列表不可用」的半成品。
2. **`ondelete='restrict'` 必须显式写**：Odoo 的 Many2one 默认 `ondelete='set null'` ⇒ 不写的话，删掉一条学制会**静默清空** 6 条专业的学制（**静默数据损坏**）。配套：`unlink()` 护栏（照 `custom_addons/edu_portal/models/fees.py:128-138` 与 `models/downloads.py:44-55` 的先例：有引用 → 拒绝 + 提示「改用停用」）。

### 5.5 不做「学制级默认」第三层（**明确的设计取舍**）

校长的原话是「标记**哪些学制需要学什么课**」。本设计把它落成：
```
学制（op.program.level）  ──分类维度──►  专业（op.course）  ──必修/选修──►  科目（op.subject）
```
**不做** `学制 × 科目` 的独立配置层。理由：
- 队长裁定已明确「必修/选修**下放到专业 × 科目**」+「全局留作默认值」——**两级 fallback**。
- 若再加学制层，同一门课会有 **3 个可能来源**（学制 / 专业 / 全局），排查「为什么这门课显示为选修」要跨三张表；且与「专业里配了就按专业的」这条既定语义**冲突**。
- 现实数据支持两级就够：6 个专业里 **`CRS-HSA` 家教学院 `subject_ids` = 0**（没有科目池），`CRS-PRP` 预备科只有 **14 门**，其余 4 个专业 72–88 门 —— **一个专业一套清单**是学校现在的真实形态。
- **唤醒条件**（§9-P4）：出现「同一学制下多个专业要共用同一份必修表」的真实诉求 ⇒ 再回第 0 步查重、不直接加层。

---

## 6. 第 4 步：设计摘要（载体裁定之二 + 全量改动面）

> §5 已裁定**学制载体**（复用 `op.program.level` + `op.course.edu_level_id`）。本节裁定**关系表载体**，并给出全部改动面。

### 6.1 载体裁定之二：**关系表** 新建 through 模型 `edu.course.subject`

| 项 | 裁定 |
|---|---|
| 模型名 | **`edu.course.subject`**（表 `edu_course_subject`）——全仓 0 命中（§3.1） |
| 落哪个模块 | **`custom_addons/edu_portal`**（`models/` 新文件 1 个 + `security/ir.model.access.csv` 追加 2 行 + `views/` 新文件 1 个） |
| 为什么不是 `op.course.subject` | `op.` 前缀是基座命名空间；本仓自研一律 `edu.`（`docs/code-map.md:39`） |
| 为什么不复用 `op.student.course` | 它是**学生的就读档案**（`student_id` + 三条 `unique` + `state`），语义是「谁在读什么」；本表是「某专业**规定**哪些科目必修/选修」——**主数据 vs 事务数据，不同轴** |
| 为什么不给 `op.course.subject_ids` 直接换 relation 表 | **本设计最关键的一条**：普通 M2M 的 `[(6,0,ids)]` 会 **DELETE 全表再 INSERT** ⇒ through 表上的 `subject_type` 列被**逐行重置为默认值** = **静默数据损坏**。本仓已有同型惨痛先例（`docs/plans/class-change-request-design.md:195`）。⇒ **必须走兼容层**（§6.3） |

### 6.2 模型设计

#### 6.2.1 新模型 `edu.course.subject`（单一事实源）

| 字段 | 类型 | 规格 | 说明 |
|---|---|---|---|
| `course_id` | Many2one `op.course` | **required**、`ondelete='cascade'`、`index=True`、`tracking=True` | 删专业时连带删配置行 |
| `subject_id` | Many2one `op.subject` | **required**、`ondelete='restrict'`、`index=True` | 被专业引用的科目不能真删（护栏照 `edu_portal/models/fees.py:128-138`） |
| `subject_type` | Selection `[('compulsory','必修'),('elective','选修')]` | **不 required、无 default、可空** | **空值 = 「继承科目的全局 `subject_type`」**（§6.5 fallback 第 2 级）。**这一格是「零迁移」的全部秘密** |
| `sequence` | Integer | default 10 | 清单排序 |
| `_order` / `_rec_name` | — | `'sequence, id'` / `'subject_id'` | 后台行标题显示科目名 |
| 约束 | `models.Constraint('unique(course_id, subject_id)', …)` | — | **一个专业 × 一门科目只能有一行** ⇒ helper 里 `filtered()` 取到的行数恒 ≤ 1（§6.5 依赖这条） |

> **命名体例依据**：`op.student.course`（`openeducat_core/models/student.py:25-51`）= 表名 + 两个 FK + 业务列 + `unique` 约束；本表逐项对齐它。

#### 6.2.2 `op.course` 的新增面（全部 `_inherit`，文件落 `custom_addons/edu_portal/models/`）

| 字段 | 规格 | 用途 |
|---|---|---|
| `edu_level_id` | Many2one `op.program.level`，string=`'学制'`，`ondelete='restrict'`，`tracking=True`，**可空** | 学制维度（§5） |
| `subject_line_ids` | One2many `edu.course.subject`（`course_id`），string=`'科目与必修/选修'` | **教务唯一编辑面**：取代原来那个纯 M2M 控件 |
| `subject_ids` | **Many2many `op.subject`，`compute` + `inverse` + `search`，`store=False`**，string 保持 `'Subject(s)'` | **兼容层**（§6.3） |

**三个方法的语义（规格级，非实现）**：

```
_compute_subject_ids:  rec.subject_ids = rec.subject_line_ids.subject_id
                       @api.depends('subject_line_ids.subject_id')

_inverse_subject_ids:  wanted = set(rec.subject_ids.ids)     # 新值已在 cache
                       existing = rec.subject_line_ids
                       ① 删：existing 里 subject_id 不在 wanted → unlink
                       ② 留：其余行一条都不动   ← 已配的 subject_type 原样保住
                       ③ 增：wanted 里没有行的 → create({course_id, subject_id})
                             **不传 subject_type** ⇒ 留空 = 继承全局

_search_subject_ids:   return [('subject_line_ids.subject_id', operator, value)]
```

**三条都有 Odoo 19 实证**（§4.2）：`write()`（`odoo/orm/models.py:4490-4501`）与 `create()`（`:4661,4682,4717-4733`）**都会调 inverse**；`search` 决定域查询（`odoo/orm/fields.py:1930-1932`）；内核同型先例 = `res.users.all_group_ids`（`odoo/addons/base/models/res_users.py:258-259`）。

> ⚠ **取舍**：`subject_ids` 变非存储 ⇒ 不能进 `_order`、不能 `groupby`。**全仓已核验无此用法**（§3.4 反向证据）⇒ 代价为零。

### 6.3 `subject_ids` 兼容层：既有消费点**逐条清单**（含行号与判定）

#### 6.3.1 清单（`op.course.subject_ids`）

| # | 位置 | 用法 | 兼容层后要改吗 | 验证方式 |
|---|---|---|---|---|
| 1 | `custom_addons/edu_portal/controllers/enroll.py:147` | `sel_course.subject_ids.sudo().filtered(...)` **读** | ❌ | 报课页科目池条数 |
| 2 | `custom_addons/edu_portal/controllers/enroll.py:232` | `pool = course.subject_ids.sudo().filtered(...)` **读** | ❌ | 提交注册单 |
| 3 | `custom_addons/edu_portal/controllers/enroll.py:483` | `len(course.subject_ids)` **读** | ❌ | 审批详情「同时换课程…N 门」 |
| 4 | `custom_addons/edu_portal/models/registration.py:439` | `'subject_ids': [(6,0, course.subject_ids.ids)]`（**写 op.student.course**，右侧读 `op.course`） | ❌（#17 见下） | 换课审批 V15c = `tests/smoke/class_change_request.py:829` |
| 5 | `custom_addons/edu_portal/models/registration.py:466` | `len(course.subject_ids)` **读** | ❌ | 审计文案 |
| 6 | `custom_addons/edu_portal/controllers/batch1.py:316` | `sc.course_id.subject_ids` **读**（兜底） | ❌ | 学生课程页 |
| 7 | `custom_addons/edu_public/controllers/main.py:57` | `'subjects': course.subject_ids` **读** | ❌ | `/courses-offered` |
| 8 | `openeducat_erp/openeducat_core/models/subject_registration.py:98-100` | **读**（+ 读**全局** `subject_type`） | ❌ 不改（口径不同源，风险 **R4**） | 基座向导 |
| 9 | `openeducat_erp/openeducat_timetable/models/timetable.py:86-88` | `related='course_id.subject_ids'`（**非存储 related**） | ❌ | 课表向导科目下拉 |
| 10 | `openeducat_erp/openeducat_timetable/models/timetable.py:407-412` | `self.course_id.subject_ids.ids` **读** | ❌ | `scripts/test_timetable_conflict.py` |
| 11 | `openeducat_erp/openeducat_timetable/views/timetable_view.xml:146,167-168` | 视图域用 related 字段 | ❌ | 同上 |
| 12 | `openeducat_erp/openeducat_assignment/models/assignment.py:104` | `rec.courses_subjects = rec.course_id.subject_ids` **赋值** | ❌ | 作业发布 |
| 13 | `openeducat_erp/openeducat_core/views/course_view.xml:15` | 列表 `many2many_tags` | ✅ **改**（§6.8） | 后台列表 |
| 14 | `openeducat_erp/openeducat_core/views/course_view.xml:54` | 表单 Subjects 页 M2M 控件 | ✅ **改**（§6.8） | 后台专业表单 |
| 15 | `tests/smoke/authz_endtoend_smoke.py:266` | `crs.write({'subject_ids': [(6,0,[sub.id])]})` **写** | ❌（inverse 保住分类） | 该冒烟 |
| 16 | `tests/smoke/p2_enroll_smoke.py:261,325` | 同型**写**（建临时专业） | ❌ | 该冒烟 |
| 17 | `scripts/seed_wangxiaoming_subjects.py:102,113,120` | 读 + `course.subject_ids = [(6,0,ids)]` **写** | ❌ | 一次性脚本 |
| 18 | `custom_addons/edu_telegram/controllers/portal_ops.py:45` | `reg.course_id.subject_ids.filtered(...)` **读** | ❌ 且**不管**（模块已退役，台账 §0.1/B8） | — |
| 19 | `tests/smoke/{course_rep.py:393-403, class_change_request.py:321,1124, subject_bulk_scope.py:88-92, class_batch_mgmt.py:259, class_batch_mgmt_ui.py:130}` | 夹具，目标多为 `op.student.course` | ❌ | 各冒烟 |

> **汇总：19 条里只有 2 条要改（#13/#14，都是视图），其余 17 条一行不动。** 反向证据（§3.4）：`op.course.subject_ids` 在 `custom_addons/` **0 处域查询 / 0 处 order**。

#### 6.3.2 为什么「不用改」是真的不用改

字段**名**、**类型**（M2M → `op.subject`）、**语义**（该专业包含哪些科目）三者都没变，变的只是底层存储在哪张表。所有消费点看到的仍是一个 `op.subject` recordset。

#### 6.3.3 `search` 为什么必须有（即使今天没人用）

`odoo/orm/fields.py:1930-1932`：**非存储计算字段一旦进 domain 就走 `search`**，不实现 ⇒ 抛错。今天本仓 0 处（§3.4），但 `openeducat_timetable` 的 related 链（#9）已出现在**视图域**里（`timetable_view.xml:167-168`），后台搜索面板/自动化/导入映射也都可能产生域查询。⇒ **`_search_subject_ids` 是防御性必备**，成本约 2 行。

#### 6.3.4 「不炸」的验收判据（进 §7）

- 19 条消费点所在功能**至少各摸一次**（§7-V3.1）；
- 3 条**写路径**（#15/#16/#17）改造后**必须复跑**，并**断言分类不丢**（§7-V3.2）。

#### 6.3.5 与历史设计的关系（**修订声明**）

- `docs/plans/enroll-v2-design.md:188`「不另加 m2m 表」指的是**注册单**（`op.subject.registration`）上的两个分区字段，**不指 `op.course.subject_ids`** —— 本设计**不违反**它。
- `docs/plans/enroll-v2-design.md:105-107`「分组来自 `course_id.subject_ids` + 全局 `subject_type`」——本设计**替换了分组来源**（专业级优先、全局降为 fallback）。这是**有意的行为变更**，不是漂移。

### 6.4 M2M → through 模型：**现有 334 条关系怎么保住**

#### 6.4.1 事实（生产只读实测，2026-09-19）

| 读数 | 值 |
|---|---|
| `op_course_op_subject_rel` | **334** |
| 分专业 | `CRS-MCS`(13) 72 / `CRS-BTH`(14) 79 / `CRS-BLA`(15) 81 / `CRS-BED`(16) 88 / `CRS-HSA`(17) **0** / `CRS-PRP`(18) 14 —— **合计 334** |
| 表列名 | `op_course_id` / `op_subject_id`（Odoo 默认命名，实测可用） |

#### 6.4.2 搬迁方案（4 步，可逆，幂等）

| 步 | 做什么 | 落在哪 |
|---|---|---|
| **① 建表** | 声明 `edu.course.subject` ⇒ Odoo `_auto_init` 自动建 `edu_course_subject`（含 `unique(course_id, subject_id)`） | **不手写建表 SQL** |
| **② 搬数据** | `migrations/19.0.3.0.0/post-migrate.py`：一条**幂等** `INSERT ... SELECT`，把老表每行写成新表一行，**`subject_type` 显式 NULL**、`sequence`=10 | `custom_addons/edu_portal/migrations/19.0.3.0.0/post-migrate.py`（**先例**：`custom_addons/edu_portal/migrations/19.0.2.0.0/` = 费用分类那次） |
| **③ 自证** | 脚本末尾**三条断言**，任一不过就 `raise` ⇒ 整个 `-u` 事务回滚（**绝不留半迁移状态**）：① `count(新表) == count(老表)`；② `(course_id,subject_id)` 两边集合差集为空；③ `count(subject_type IS NOT NULL) == 0` | 同上 |
| **④ 老表封印** | `op_course_op_subject_rel` **一行不删、不 DROP、不改**（本仓红线）；登记台账 | `docs/audit/deprecated-inventory.md` |

> **幂等**：用 `WHERE NOT EXISTS` 或 `ON CONFLICT DO NOTHING`（`unique(course_id,subject_id)` 是现成冲突键）。**重跑同一次 `-u` 不产生重复行** —— 这条必须实测（§7-V4.3）。

#### 6.4.3 回滚方案

| 场景 | 动作 | 数据后果 |
|---|---|---|
| 兼容层有问题 | 代码回滚（`subject_ids` 恢复成普通 M2M 声明）⇒ 表名自动回到 `op_course_op_subject_rel` | **成员关系零丢失**（老表**从未被写过**）；上线后教务改过的分类仍在 `edu_course_subject` 里（不可见但不丢） |
| 回滚前归档 | 按台账 **C1** 口径：`\copy edu_course_subject to '/tmp/edu_course_subject.csv' csv header` | 有据可查 |
| **绝不** | 回滚时 `DROP TABLE edu_course_subject` | **禁止**（红线：只隐藏/迁移，不删） |

#### 6.4.4 「零数据迁移」的**准确表述**（防误引）

- ✅ **教务侧**：334 条关系一条都不用重配；147 门科目的全局值一个都不动；升级后**页面行为逐条一致**（所有新行 `subject_type` 为空 = 继承全局）。
- ❌ **不能**说「不动数据」：底层有 **1 次 334 行搬迁**（步②），可核对、可回滚、幂等。
- 依据 = 队长裁定第 3 条「**零数据迁移**（现有 334 条关系保持空白即可，不许要求教务重配）」。

### 6.5 报课页的读取口径（fallback 判定顺序）

#### 6.5.1 判定顺序（**唯一权威定义**）

对「专业 C 里的科目 S」，有效类型 `T(C,S)`：

```
1) 行 = edu.course.subject 里 (course_id=C, subject_id=S) 的那一行
   若 行存在 且 行.subject_type 非空  → T = 行.subject_type   ← 教务按专业配的
2) 否则                            → T = S.subject_type     ← 科目全局默认值
3) 兜底（理论上到不了：S.subject_type 是 required+default='compulsory'）
                                   → T = 'compulsory'（宁可当必修，不静默丢课）
```

**三条性质（写进验收）**：**专业优先**、**全局兜底**、**空值即继承**；且 **学制不参与判定**（§5.5）；**页面显示与服务端补齐必须同源**（否则会出现「页面显示选修、服务端按必修补齐」的自相矛盾）。

#### 6.5.2 落地位置（**一个 helper，两处调用**）

新增在 `custom_addons/edu_portal/models/` 的 `op.course` 继承类上（**模型层，不是控制器层** ⇒ 门户/后台/脚本/测试四条路径同一处生效，照 `class_batch.py:318-326`「写库语义收敛到一处」先例）：

| 方法 | 输入 | 输出 | 用途 |
|---|---|---|---|
| `edu_effective_type(subject)` | `op.subject` 单条 | `'compulsory'`/`'elective'` | 单条判定（审批详情/证书/单科目展示） |
| `edu_subject_pool()` | — | `[{id,name,code,type,type_label,compulsory,credit,capacity,enrolled,blockers,blocked}, …]`（**与 `enroll.py:156-169` 现有 dict 完全同形**） | 报课页科目池（**一次查询取全部行，避免 N+1**） |
| `edu_compulsory_subject_ids()` | — | ids | 服务端「必修全量补齐」（`enroll.py:235-236` 口径） |

> `credit/capacity/enrolled/blockers` 仍由 `enroll.py` 现有的 `edu.subject.prereq` 逻辑填（**本设计不碰先修/学分/容量**）；**只有 `type/type_label/compulsory` 三个键改来源**。

#### 6.5.3 `enroll.py` 的具体改动（**只有 2 处**）

| 行 | 现在 | 改成 |
|---|---|---|
| `:156-170` | `'type': _SUBJECT_TYPE_LABEL.get(s.subject_type, …)`、`'compulsory': s.subject_type == 'compulsory'`、`subjects.sort(key=lambda x: (not x['compulsory'], x['name']))` | `type/type_label/compulsory` 取自 `sel_course.edu_subject_pool()`（**排序键与徽标数不变**） |
| `:234-236` | `compulsory_ids = pool.filtered(lambda s: s.subject_type == 'compulsory').ids` | `compulsory_ids = course.edu_compulsory_subject_ids()` |

**`:143-152`（科目池来源）、`:171-172`（计数）、`views/enroll.xml:137-138,147-166`（渲染）全部不动** —— 它们读的就是上面这两个变量。

#### 6.5.4 明确**不**改 + 登记已知差异

| 位置 | 现状 | 处置 |
|---|---|---|
| `openeducat_core/models/subject_registration.py:95-102`（`get_subjects()`：把 `course_id.subject_ids` 里 global compulsory 灌进注册单） | 读**全局** | **不改基座**（红线）⇒ 基座向导与门户报课页口径**可能不一致** = 风险 **R4**（§8），处置见 §9-P3 |
| `openeducat_exam/wizard/room_distribution.py:73,76` | 考场向导按全局 `subject_type` 分流 | **不改**（「考试口径」与「培养方案」不同轴） |
| `tests/smoke/*` 的 `subject_type` 夹具 | 造全局值 | **不改**，但改造后**必须复跑**看有没有被联动打断（§7-V7） |
| `scripts/import_curriculum.py`、`scripts/seed_*.py`、`timetable_import/` | 写全局值 | **不改**（批量导入仍是「科目默认值」入口） |

---

### 6.6 「课程 → 专业」改名范围：**逐条清单**

> **原则**：校长要求的是「界面上把『课程』改名为『专业』」——**改的是「专业」这个实体在界面上的叫法**，不是把全仓含「课程」两个字的地方全局替换。
> **实测口径**：生产 `edu19`（`prod-host` / `edu19-prod-db-1`，只读 SELECT，2026-09-19）。生产与本地 `ir_ui_menu` 中**名字含「课程」的菜单恰好 11 条，两边 id 完全一致**。

#### 6.6.1 全量清单（11 条菜单 + 关联动作）

| 菜单 id | 现名（zh_CN） | 父 | 动作 → 模型 | active | **处置** | 为什么 |
|---|---|---|---|---|---|---|
| **263** | **课程** | 262 课程管理 | `385` → **`op.course`** | t | ✅ **改成「专业」** | 校长明确要求；它就是那 6 条专业 |
| **385**（动作名，面包屑/页面标题用） | **课程** | — | `op.course` | — | ✅ **一并改成「专业」** | 只改菜单不改动作 ⇒ 面包屑仍写「课程」，自相矛盾 |
| **262** | **课程管理** | 261 配置 | 容器 | t | ⚠ **建议改「教学管理」**（**P1 拍板**） | 它下面除「专业」外还挂着 264 批次 / 265 部门 / 628 已停用班级 ⇒ 叫「课程管理›专业」别扭 |
| **277** | **专业层次** | 275 项目管理 | `396` → **`op.program.level`** | t | ✅ **改成「学制」** | 校长用词就是「学制」；**它就是本设计的学制字典** |
| **396**（动作名） | 程序级别 | — | `op.program.level` | — | ✅ 一并改成「学制」（**顺带修既有缺陷**：它现在是机翻「程序级别」） | 同上 |
| **276** | **专业** | 275 项目管理 | `395` → **`op.program`** | t | ⚠ **必须处置**（**P1 拍板**，见 §6.6.2） | **撞名**：与改造后的 263 都叫「专业」，但一个是 `op.program`（0 条）、一个是 `op.course`（6 条） |
| **395**（动作名） | 节目 | — | `op.program` | — | 随 P1 一起处置 | 现在面包屑显示的是**机翻遗留「节目」**（t117 只改了菜单名、没改动作名） |
| **275** | 项目管理 | 261 配置 | 容器 | t | 随 P1 | 装 276/277 |
| **282** | 学生课程详情 | 280 通用 | `392` → `op.student.course` | t | ❌ **不改** | 它是「**学生的就读档案**」列表，不是专业目录；改了会牵动审批页与 breadcrumb |
| **327** | 考试课程 | 326 考试 | `444` → `op.exam.session` | t | ❌ **不改** | 这是**考试场次**，与专业无关 |
| 416 | 课程 | 251（已停用） | — | **f** | ❌ 不动 | 已停用 |
| 548 | 课程 | 547 在线学习 | 容器 | **f** | ❌ 不动 | `website_slides` 在线学习子树，已停用 |
| 551 | 课程 | 548 | `701` → `slide.channel` | **f** | ❌ 不动 | 同上 |
| 553 | 课程 | 549 报表 | `702` → `slide.channel` | **f** | ❌ 不动 | 同上 |
| 559 | 课程组 | 550 配置 | `704` → `slide.channel.tag.group` | **f** | ❌ 不动 | 同上 |
| **561** | **课程** | 222 内容 | `705` → `slide.channel` | **t（生产启用中）** | ❌ **绝对不改** | ⚠ 它是「课程网页」= `website_slides` 的在线课程，与 `op.course` 无关；**它也是不能对 `Courses` 这个 msgid 做全局覆盖的原因**（§6.6.3） |
| 576 | 在线课程 | （根） | 容器 | **f** | ❌ 不动 | 已停用 |
| 267 | 科目 | 266 学科管理 | `387` → `op.subject` | t | ❌ **不改** | 科目就是科目（必修/选修是**科目在专业里的属性**） |

#### 6.6.2 撞名（276「专业」）的两个选项 —— **P1 请校长拍板**

| 选项 | 做法 | 代价 | 影响面 |
|---|---|---|---|
| **A（本设计默认起草口径，推荐）** | **276 菜单改「培养项目」**（+ 动作 395 同步），保留在「项目管理」子树里 | 教务在「项目管理」下看到「培养项目」 | `edu_assess` 的「参与专业」多选（`assess.py` 的 `EduAssessTask.scope_program_ids`）与公开页 `/program-offered`（`edu_public/controllers/main.py:252-256`）**继续可用** |
| **B** | **停用 275 整棵（`active=False`）**，把 277「学制」**移到 262 课程管理**下 | `edu_assess`「参与专业」**失去维护入口**（0 数据，暂无实害）；`/program-offered` 变空页 | 少一层概念，界面最干净；学制与专业同挂 262，动线更短 |

> A 符合本仓「只隐藏不删 + 不夺走别人模块入口」的红线精神；B 更干净但需菜单守卫（§8-R2）。

#### 6.6.3 改名**机制**：为什么不能简单地 `Courses → 专业`

**实测证据（生产）**：

| 记录 | zh_CN | en_US（source） |
|---|---|---|
| 菜单 263 | 课程 | `Courses` |
| 动作 385 | 课程 | `Courses` |
| 菜单 276 | **专业** | `Programs` |
| 动作 395 | **节目**（机翻，未改） | `Programs` |
| 菜单 277 | **专业层次** | `Program Level` |
| 动作 396 | **程序级别**（机翻，未改） | `Program Level` |

**两条结论**：

1. **t117 只改了「菜单名」，没改「动作名」**（菜单 276=专业 vs 动作 395=节目）⇒ 教务从面包屑/页面标题看到的仍是旧译。⇒ 本次改名**必须同时覆盖菜单 263 与动作 385**。
2. **既有机制是 `edu_zh` PO 覆盖，而 PO 覆盖按 `msgid` 全局生效**（`docs/ops/menu-rename-list.md:93-95` 自己写了这条）——`Courses` 这个 msgid **至少还挂在生产仍启用的 561**（`slide.channel`，动作 705）与 548/551/553。⇒ **不能**写 `msgid "Courses" msgstr "专业"`（会顺手把 561 也改成「专业」= 第二个撞名 + 语义错误）。

**主方案（4 步）**：

| 步 | 动作 | 落点 |
|---|---|---|
| ① | 用**基座 xmlid + `forcecreate="0"`** 覆盖两条记录，把 **菜单 263** 与 **动作 385** 的 `name`（en_US source）改成**全新唯一串**（建议 `Majors`） | `custom_addons/edu_portal/views/`（**先例**：`custom_addons/edu_nav/data/menu_consolidation_data.xml` 通篇用基座 xmlid + `forcecreate="0"` 覆盖 `ir.ui.menu`） |
| ② | `edu_zh/i18n_extra/{zh_CN,zh_TW}.po` 追加 `msgid "Majors" / msgstr "专业"`、`"專業"` | `edu_zh`（**体例照 `menu-rename-list.md:1-5,26-41`**） |
| ③ | 升级命令**必须带** `--i18n-overwrite` | `UPGRADE_EXTRA_ARGS="--i18n-overwrite" bash scripts/safe_upgrade.sh -u edu_zh`（同文 §1/§3 实测：**不带时 exit 0 但菜单名一字未变**） |
| ④ | 照 `menu-rename-list.md:70` 的方法测量（ORM 读 `name` + `complete_name`，lang=zh_CN）+ **回归对照** | §7-V9 |

**备选方案**（主方案实测不通时，见 §10-U1）：source 直接写成中文「专业」（**本仓有先例**：菜单 612「选课审批」en_US 即中文、无 zh_CN 槽位、靠回退显示，`menu-rename-list.md:68,89`）。

**⚠ 两条硬禁令**：
- **不得**用 `edu_nav` 承载本改名：`docs/code-map.md:110` 规定它的 data 由 `scripts/gen_menu_data.py` 从 plan JSON 生成、**禁止手改**；且 **生产未装 `edu_nav`**（`docs/plans/evaluation-rebuild-design.md` 实测记录）⇒ 改在那里**生产上看不到**。
- **不得**改 `openeducat_erp/` 的 `menu/openeducat_core_menu.xml` / `views/course_view.xml` 里的文案（合规红线 + 基座快照只读）。

#### 6.6.4 明确**不改**的「课程」字样（含**最危险的一处**）

| 位置 | 为什么**不**改成「专业」 |
|---|---|
| **门户 `/my/courses`**（`custom_addons/edu_portal/controllers/lms.py:22-44`） | 数据源是 `op.student.course.subject_ids`（`lms.py:29-35`）⇒ **列的是「科目」**。改成「我的专业/学位」是**胡话**。⚠ **明确不改** |
| **门户 `/my-courses`（注意：另一条路由！）**（`custom_addons/edu_public/controllers/main.py:259-279`） | 它列的是 `op.student.course.course_id` = **`op.course`**。这里叫「我的课程」**其实不准确**，但**不在本轮范围** ⇒ 登记为风险 **R5**（同名不同物：`/my/courses` 列科目、`/my-courses` 列专业） |
| 门户报课页 `views/enroll.xml:63,64,120,147,149` | 这五处**指的就是 `op.course`**，改「专业」更准；但属学生侧文案 ⇒ **列为 P3 拍板**（建议改，低风险纯文案） |
| `views/batch1.xml:16,24,46,50,366,370,396,400`、`views/batch2.xml:328,332,354,358`、`views/batch3.xml:318,322,346,350` | 这些 `course_id` **也是 `op.course`**；改更准，但属**另一批页面**且牵动两条门禁 ⇒ **本轮不改**，列为后续任务 |
| `views/certificate_report.xml:50`、`views/roles.xml:1863`、`views/enroll.xml:403` | 已有流程的**成句文案**，改动牵动已发证书模板与审批页回归 ⇒ **不改** |
| `edu_public/views/course_detail.xml:40` | 公开站占位 ⇒ **不改** |
| `op.course` 的 `_description`（`course.py:28`） | 只在「设置→技术→模型」可见（仅超管）⇒ **不改** |

> **一句话口径**：**只改「配置 →（课程管理）→ 课程」这条教务动线上的名字（菜单 263 + 动作 385）+ 学制（277 + 动作 396）；门户与其它页面一律不动。**

### 6.7 权限门禁（四层口径，照 `code-map.md:256-263`）

| 层 | 对象 | 依据（实测/规范） |
|---|---|---|
| **菜单** | **263（专业）** `groups` 已是 `gid 40 = openeducat_core.group_op_back_office_admin`；**277（学制）** 同为 gid 40；**276（P1 后）**同 | 生产 `ir_ui_menu_group_rel` 实测：`263→40`、`276→40`、`277→40`；`267 科目→39+40` |
| **ACL（新模型）** | `edu.course.subject` 两行：`openeducat_core.group_op_back_office_admin` = `1,1,1,1`；`base.group_system` = `1,1,1,1`。**不给 `base.group_user` / `base.group_portal`** | `code-map.md:258`「业务管理 → 教务组（写 `groups="…back_office_admin,base.group_system"`，与系统组并列）」；**先例**：`custom_addons/edu_portal/security/ir.model.access.csv` 的 `access_edu_course_rep_backoffice` / `_system` 两行 |
| **ACL（既有表）** | `op.course`（gid 40 = 1,1,1,1）、`op.program.level`（gid 40 = 1,1,1,1）**已满足，不动** | 生产 `ir_model_access` 实测 |
| **ir.rule** | **0 条新增** | 配置面没有「只看自己」语义；`student_login_rule` 不受影响（学生不读配置表） |
| **控制器** | **0 处新增**（本设计**不新增门户路由**） | 但 `enroll.py` 读口径改了 ⇒ §7-V6 要验「学生视图不变、教师改不了」 |
| **不建组** | **0 个新组** | `code-map.md:245` 约定第 3 条 |

**⚠ 实测到的一个既有事实（必须写清，否则会被误判为"漏了"）**：生产 `op.course` 对 **`gid 39 = group_op_faculty`（教师）** 的 ACL 是 `读=1,写=1,建=1,删=0` ⇒ **教师模型层有写权**；挡住教师的是**菜单 263 只挂教务组**。
⇒ 因此 `edu.course.subject` 的 ACL **必须不给教师组**：这样即便教师从别处拿到 `op.course` 写入口（导入/自动化/深层链接），**写 `subject_ids` 会在 inverse 里撞 `AccessError` 而整体回滚**（不是半写）。**这一条必须真机实测**（§7-V6.3）。

### 6.8 改动面汇总（文件级，供实施排期）

| 文件 | 动作 | 内容 |
|---|---|---|
| `custom_addons/edu_portal/models/major_track.py`（新，文件名可调） | **新建** | `EduCourseSubject`（`edu.course.subject`）+ `OpCourse` 继承（`edu_level_id` / `subject_line_ids` / `subject_ids` 兼容层 / 三个 helper）+ `OpProgramLevel` 继承（`active` / `sequence`）+ `unlink()` 护栏 |
| `custom_addons/edu_portal/models/__init__.py` | 追加 1 行 import | — |
| `custom_addons/edu_portal/security/ir.model.access.csv` | 追加 2 行 | `edu.course.subject` 教务 + 系统组 ACL |
| `custom_addons/edu_portal/views/major_track_views.xml`（新） | **新建** | 继承 `view_op_course_form`（`course_view.xml:21-62`；Subjects 页 `:52-57` 的 `subject_ids` → `subject_line_ids` + 学制字段）+ 继承 `view_op_course_tree`(`:3-19`) / `view_op_course_search`(`:64-87`) + 继承 `view_op_program_level_form/tree`（`program_level.xml:3-38`）加 `active`/`sequence` + **菜单 263/385/277/396 改名记录**（§6.6.3 步①） |
| `custom_addons/edu_portal/models/__init__` / `__manifest__.py` | 追加 | views 清单 + `data` 清单 |
| `custom_addons/edu_portal/controllers/enroll.py` | **改 2 处** | `:156-170` 与 `:234-236`（§6.5.3） |
| `custom_addons/edu_portal/migrations/19.0.3.0.0/post-migrate.py` | **新建** | 334 行搬迁 + 三条自证（§6.4.2） |
| `custom_addons/edu_portal/__manifest__.py` | `version` 递增 | 触发 migrations（**先例**：`19.0.2.0.0`） |
| `custom_addons/edu_zh/i18n_extra/{zh_CN,zh_TW}.po` | 追加词条 | `Majors → 专业/專業`（+ P1 选 A 时 `Programs` 新串） |
| `docs/audit/deprecated-inventory.md` | **追加 1 行**（已做） | 本次查重登记 + `op_course_op_subject_rel` 老表封印 |
| `docs/ops/menu-rename-list.md` | 后续追加 | 263/385/277/396 改名后的实测对照（照该文件 §3 体例） |

### 6.9 数据流（改造后）

```
教务后台                                      门户（学生）
──────────                                    ────────────
配置 → 课程管理 → 学制(277)                      /subject/enroll
   └─ op.program.level  ←── edu_level_id ──┐        │
配置 → 课程管理 → 专业(263)                │        │
   ├─ op.course ───────────────────────────┘        │
   │     └─ Subjects 页 = subject_line_ids          │
   │          └─ edu.course.subject ────────────────┤
   │               (course_id, subject_id,          │
   │                subject_type = 空 / 必修 / 选修) │
   ├─ subject_ids (computed + inverse + search) ────┤ 成员集
   │                                                │
科目(267) op.subject.subject_type = 全局默认 ───────┘ 兜底
```

**生效链路**：教务存一行 → `edu.course.subject` 落库 → 学生刷新 `/subject/enroll` → `course.edu_subject_pool()` 读到新值 → **徽标数 / 分组 / 提交校验三处同源变化**（无缓存、无异步、无需重启）。

---

## 7. 真机可验证的验收标准（第 6 步口径）

> **前置**（照 `docs/code-map.md:26` 门禁跑前三步探活）：① 无升级锁；② 容器 Up > 30s；③ 带 cookie jar 访问 `/web/login?db=edu19` 得 200/302/303。
> **升级一律** `bash scripts/safe_upgrade.sh edu_portal`（`-u`，**不要** `-i`，见 `code-map.md:30`）；改 PO 时**必须** `UPGRADE_EXTRA_ARGS="--i18n-overwrite"`。
> **读数一律带采集时刻**；探针**不得跟随重定向**（`docs/dev-workflow.md:138-146`）。

### 7.0 基线快照（改造**前**先取，用于 V1/V5 对照）

```bash
# 生产（只读 SELECT；红线：不得触碰 edu_telegram / edu_feedback）
ssh prod-host 'docker exec edu19-prod-db-1 psql -U odoo -d edu19 -Atc "select count(*) from op_course_op_subject_rel"'
#   期望 334
ssh prod-host 'docker exec edu19-prod-db-1 psql -U odoo -d edu19 -Atc "select c.code, count(r.op_subject_id) from op_course c left join op_course_op_subject_rel r on r.op_course_id=c.id group by c.code order by c.code"'
#   期望 CRS-BED 88 / CRS-BLA 81 / CRS-BTH 79 / CRS-HSA 0 / CRS-MCS 72 / CRS-PRP 14
ssh prod-host 'docker exec edu19-prod-db-1 psql -U odoo -d edu19 -Atc "select subject_type, count(*) from op_subject group by 1"'
#   期望 compulsory 25 / elective 122
ssh prod-host 'docker exec edu19-prod-db-1 psql -U odoo -d edu19 -Atc "select id, coalesce(name->>'zh_CN','') from ir_ui_menu where id in (263,548,551,553,561,276,277) order by id"'
#   期望 263=课程 548=课程 551=课程 553=课程 561=课程 276=专业 277=专业层次
```

### 7.1 V1 —— 迁移无损：**现有 334 条关系一条不少**

| 判据 | 怎么测 | 通过线 |
|---|---|---|
| V1.1 条数 | `select count(*) from edu_course_subject;` | **= 334**（与 §7.0 基线逐位相等） |
| V1.2 集合相等 | 老表与新表的 `(course_id, subject_id)` 做双向 `EXCEPT` | **两个方向都 0 行** |
| V1.3 分专业条数 | 按 `c.code` 分组 | 与基线**逐专业相等**（88/81/79/0/72/14） |
| V1.4 老表未动 | `count(*)` + `max(write_date)` | **仍是 334**，`write_date` **未变** |
| V1.5 分类全空 | `select count(*) from edu_course_subject where subject_type is not null;` | **0**（= 全部继承全局） |

### 7.2 V2 —— 教务配了 = 报课页对该专业学生**立刻生效**（**本需求的核心验收**）

> 生产实况：`op_student_course` 只有 **1 行**（id 13 = student 11 / **course 16 教育学士** / batch 13 / `running`；course 16 下有 **8 个 active 班**）⇒ **生产验证用「教育学士 CRS-BED」（id 16，88 门池）**；本地库可另造【演示】数据。

| 步 | 操作 | 断言 |
|---|---|---|
| V2.1 | 教务登录后台 → 配置 → 课程管理 → **专业** → 打开「教育学士」→ **Subjects 页** | 每行有「必修/选修」可选项；**未配过的行显示为空**（=继承） |
| V2.2 | 挑一门**全局是 `elective` 的**科目（生产 122 门里任选，在 `CRS-BED` 池内）→ 设为 **必修** → 保存 | `select subject_type from edu_course_subject where course_id=16 and subject_id=<该科目>;` = `compulsory` |
| V2.3 | **学生**登录 → GET `/subject/enroll?course_id=16&batch_id=13`（**`allow_redirects=False`**） | HTTP **200**；「必修 N」比基线 **+1**、「选修 N」**−1**；该科目卡片出现 🔒 且勾选框 `disabled` |
| V2.4 | 同一门改回选修 → 刷新 | 徽标**逐位还原** |
| V2.5 | 标为必修后，学生 POST `/subject/enroll/save`（不带 `elective_subject_ids`） | 注册单 `op_subject_registration.compulsory_subject_ids` **含该科目**（服务端补齐与页面同源） |
| V2.6 | 只配了 1 门必修、其余全空的专业 | 其余科目的分组**仍是全局值**（V5 的局部伴随判据） |

### 7.3 V3 —— 既有消费点**不炸**（§6.3.1 的 19 条）

| 组 | 覆盖点 | 怎么测 |
|---|---|---|
| V3.1 读路径（14 条） | #1/#2/#3 报课与审批详情 · #4/#5 换课（`tests/smoke/class_change_request.py`） · #6 学生课程页 · #7 `/courses-offered`（公开 GET 200 且科目数 == `len(course.subject_ids)`） · #8 基座向导（后台打开「选课注册」表单点 `get_subjects` 动作，**不得 Traceback**） · #9/#10/#11 课表（`python3 scripts/test_timetable_conflict.py`） · #12 作业发布（打开一条 `op.assignment` 表单，`courses_subjects` 有值） · #13/#14 后台列表与表单 · #18 退役模块**不测** | 每项**至少一次真实 HTTP/ORM 命中**；**不得只看升级 EXIT=0** |
| V3.2 **写路径（3 条，必测）** | #15 `tests/smoke/authz_endtoend_smoke.py`、#16 `tests/smoke/p2_enroll_smoke.py`、#17 `scripts/seed_wangxiaoming_subjects.py` | 先给专业 X 配 3 门必修 → `write({'subject_ids': [(6,0, 该 3 门 + 1 门新)]})` → 断言**原 3 门仍是必修**、新的 1 门为空；再 `[(6,0,[新])]` → 断言只剩 1 行且分类为空（**证明 `[(6,0,…)]` 不会重置分类**） |
| V3.3 域查询 | `env['op.course'].search([('subject_ids','in',[sid])])` | **不抛错**且条数 == 老表口径（证明 `_search_subject_ids` 生效） |

### 7.4 V4 —— 迁移可重跑（幂等 + 失败即回滚）

| 判据 | 怎么测 | 通过线 |
|---|---|---|
| V4.1 | 连跑两次 `bash scripts/safe_upgrade.sh edu_portal` | 两次 EXIT=0，`count(edu_course_subject)` **两次都是 334** |
| V4.2 | 事务里重跑 `post-migrate` 的搬迁 SQL | 不产生重复行（`unique(course_id,subject_id)` 或 `NOT EXISTS` 生效） |
| V4.3 | 造一次「应该报红」的探针：临时删 1 行老表 → 重跑 `-u` | **报错且整个事务回滚**，老表行数不变（自证①失败必须导致回滚） |

### 7.5 V5 —— **没配的专业仍继承全局值**（零迁移的证据）

| 判据 | 怎么测 | 通过线 |
|---|---|---|
| V5.1 | **改造后、教务一条都不配**，逐专业跑 `edu_subject_pool()` | 每门科目的 `compulsory` 值 **== `op_subject.subject_type == 'compulsory'`**（逐条比对，**差异数 = 0**） |
| V5.2 | 生产 GET `/subject/enroll?course_id=16&batch_id=13` | 「必修 N / 选修 N」**与改造前基线逐位相等** |
| V5.3 | `select count(*) from edu_course_subject where subject_type is not null;` | **0**（升级后立即测 = 无人需要重配） |

### 7.6 V6 —— 权限：非教务/管理员**改不了**（校长硬要求）

| 判据 | 怎么测 | 通过线 |
|---|---|---|
| V6.1 教师看不见入口 | 教师账号 `load_menus`（**口径 B**）里搜「专业」「学制」 | **0 命中**（263/277 只挂 gid 40） |
| V6.2 教师改不了（UI） | 教师直接 GET 菜单 263 的 action URL | 无权限 / 落 `/apps`；**不得**渲染出可编辑的 Subjects 页 |
| V6.3 教师改不了（模型层，**关键**） | 以教师身份 `env['op.course'].browse(18).write({'subject_ids': [(6,0,[x])]})` | **抛 `AccessError` 且事务整体回滚** —— 老表与新表**都不变**（**不得**出现"成员变了但分类没跟上"的半写） |
| V6.4 学生改不了 | 学生账号访问同一 action | 无权限 / 回 `/my/home` |
| V6.5 教务/管理员能改 | 教务 + 系统管理员各保存一次 | 都成功；`tracking=True` 进 chatter（`create_uid`/`write_uid` 留痕） |

### 7.7 V7 —— 既有冒烟 / 门禁回归

| 门禁 | 命令 | 通过线 |
|---|---|---|
| 继承视图静态检查 | `python3 scripts/check_view_xpath.py` | exit 0；⚠ `EXPECTED_EXTERNAL_MODELS`（`scripts/check_view_xpath.py` 的模块常量；**现值以脚本为准，别在文档里抄数字** —— `grep -n '^EXPECTED_EXTERNAL_MODELS' scripts/check_view_xpath.py`）若因新增 `_inherit` 变化，**必须按该脚本注释体例追加一行 rN 说明**，不得静默改数 |
| 跟踪集 | `python3 scripts/check_manifest_tracking.py` | exit 0（新增文件必须进 git 跟踪集） |
| 汉化 | `python3 scripts/check_english.py` | **must-fix = 0**（改了 en_US source 后尤其要跑） |
| 无障碍 | `python3 scripts/check_accessibility.py` | **BASELINE 保持 0**（新增下拉/复选框必须有可访问名） |
| QWeb dict | `python3 scripts/check_qweb_dict_foreach.py` | exit 0（若把分组数据以 dict 传模板，必须 `.items()`） |
| 冒烟 | `authz_endtoend_smoke.py`、`p2_enroll_smoke.py`、`course_rep.py`、`class_change_request.py`、`subject_bulk_scope.py`、`class_batch_mgmt.py`（+ `_ui`） | 各自通过线**不低于改造前**（先取改造前读数） |
| 可达性 | `python3 tests/smoke/backoffice_reachability.py` | exit 0（L1 可见 → L2 动作+权限读数 → L3 真渲染） |
| 路由矩阵 | `python3 tests/smoke/ux_v3_route_matrix.py` | 与改造前同口径（探针**不得跟随重定向**） |

### 7.8 V8 —— 改名对照（照 `docs/ops/menu-rename-list.md:70` 的测量法）

| 判据 | 通过线 |
|---|---|
| V8.1 | ORM（`lang=zh_CN`）读 `ir_ui_menu` 263 的 `name` = **专业**；`complete_name` = **学生信息/配置/课程管理/专业** |
| V8.2 | 动作 385 的 `name`（zh_CN）= **专业** |
| V8.3 | 277 = **学制**、396 = **学制** |
| V8.4 | **回归对照（照同文 §4 体例）**：**548 / 551 / 553 / 561 必须「一字未变」= 课程**；267 = 科目、264 = 批次、282 = 学生课程详情、327 = 考试课程**一字未变** |
| V8.5 | 繁体：263 = **專業**、277 = **學制**（若做 zh_TW） |

### 7.9 V9 —— 回滚演练（**上线前必须做一次**）

| 步 | 动作 | 通过线 |
|---|---|---|
| V9.1 | 导出归档（台账 C1 口径） | `\copy edu_course_subject to '/tmp/x.csv' csv header` 成功，行数 = 334 |
| V9.2 | 代码回滚到改造前 + `-u` | `subject_ids` 恢复老表口径；条数仍 334；`/subject/enroll` 正常 |
| V9.3 | 再切回改造后 + `-u` | 又回到 334/334（**证明可逆**） |

---

## 8. 风险与收口触发条件

| # | 风险 | 证据/机制 | 处置 |
|---|---|---|---|
| **R1** | **改名主方案未实测**：把菜单/动作 en_US source 改成新串后，`edu_zh` PO 能否把 zh_CN 写到**同一条**记录上 | `docs/ops/menu-rename-list.md:70-79` 只证过「**不改 source**、覆盖已有 msgid」这一条路径 | 实施第一步就做 §6.6.3 的 4 步小实验（**只改 263**），用 V8.1/V8.4 判定；不通就走备选（source 用中文，照菜单 612 先例） |
| **R2** | **菜单重放（F1 类）**：`-u openeducat_core` / `-u openeducat_erp` 会把 `parent_id`/`name` 打回基座声明值 | `docs/audit/finding-F1-menu-replay-on-upgrade.md`（**未关闭**）；且 **生产未装 `edu_nav`** ⇒ 无守卫 | 改名记录放**生产已装**的模块；每次 `-u` 相关模块后跑 V8；若 P1 选 B（移动 277）必须额外加装载期守卫 |
| **R3** | **教师模型层有 `op.course` 写权**（`gid 39 = 1,1,1,0`，实测）⇒ 理论上可绕菜单写 `subject_ids` | 生产 `ir_model_access` 实测 | 靠 `edu.course.subject` 的 ACL 收口（不给 `group_user`）；**V6.3 必须实测是干净报错 + 整体回滚** |
| **R4** | **口径不同源**：基座 `get_subjects()`（`subject_registration.py:95-102`）仍读全局 `subject_type` | 本设计不改基座（红线） | 见 §9-P3：建议在 `edu_portal` 里 `_inherit` 覆写这一处；**至少**登记为已知差异并在帮助中心写明 |
| **R5** | **同名不同物**：`/my/courses`（`lms.py:22-44`，列**科目**）与 `/my-courses`（`edu_public/controllers/main.py:259-279`，列**专业**） | 两条路由，语义相反 | 本轮**不动**；登记台账，避免下一个 agent 把其中一条改成「我的专业」 |
| **R6** | **全局值变更的连带**：教务改一门科目的全局 `subject_type`，所有"没配过该科目"的专业会**一起变** | 这是 fallback 的**设计意图** | 在帮助中心写明（后续在 `views/help_center.xml` 追加一段）；**不要**加缓存或快照 |
| **R7** | `op.program.level.name` 是 `translate=True` + `unique(name)`（`program.py:51-54`）⇒ 多语言下可能建出近似重复 | 基座约束写法 | 实测：中文名建 1 条再切英文界面看是否允许建同义英文名；若允许，在帮助中心写明「学制名只填中文」 |
| **R8** | 新增 `_inherit='op.course'` / `'op.program.level'` 可能改变 `check_view_xpath.py` 的外部模型计数（**数字以脚本常量为准**，文档不抄） | `scripts/check_view_xpath.py` 的 `EXPECTED_EXTERNAL_MODELS` + 该文件「逐次来由」的变更体例（当前 rN 见其 `REVISION` 常量） | 跑门禁；若变化按体例追加注释行（**不得静默改数**） |
| **R9** | 基座 `openeducat_fees/views/course_view.xml:4-19` **也继承了** `view_op_course_form` ⇒ 我们与它的继承顺序**未实测**，可能字段错位 | 仓内 grep 命中 | 实施时实测表单渲染；必要时调 `priority` 或不依赖兄弟节点定位 |
| **R10** | **收口触发条件** | — | 出现 ① 第 2 个「专业×科目分类」写库入口 ② 第 2 处「学制」字典 ③ 有人把必修/选修再复制一份 ⇒ **立刻回第 0 步查重**，并按 `docs/dev-workflow.md:72-79` 考虑脚本化 |

---

## 9. 需要校长拍板的用户可见项（**5 项**）

| # | 问题 | 选项 | 本设计建议 |
|---|---|---|---|
| **P1** | 菜单 **276「专业」**（`op.program`，**0 条数据**）与改造后的 263 撞名，怎么处置？ | **A** 276 改「培养项目」保留（`edu_assess` 与 `/program-offered` 继续可用）/ **B** 停用 275 整棵并把「学制」移到 262 下（界面最干净，但夺走别人模块的入口） | **A**（保守、可逆、不伤别的模块）。**若 B**：必须同步告知 `edu_assess`「参与专业」将失去维护入口 |
| **P2** | 菜单 **262「课程管理」**（容器，下挂 专业/批次/部门/已停用班级）要不要一起改名？ | 「课程管理」保持 / 改**「教学管理」** / 改「专业与班级」 | 改**「教学管理」** |
| **P3** | 门户上指代 `op.course` 的文案要不要一起改？（报课页「课程目录」等 5 处） | 改 / 不改 | **改**（纯文案、低风险、学生看到的名字与后台一致）；同时决定是否覆写基座 `get_subjects()`（R4） |
| **P4** | 要不要**「学制级默认」第三层**（学制 × 科目 也配一遍，专业没配就继承学制）？ | 不做（两级）/ 做（三级） | **不做**（§5.5；三级会让「为什么这门课是选修」要查三张表） |
| **P5** | 学生侧要不要**看到自己专业的学制**（报课页页首 / 档案卡显示「本科」）？ | 显示 / 不显示 | **显示**（一行文案；否则「学制」只是个后台字段，教务标了学生感受不到）——属新增门户展示，需单独确认 |

---

## 10. 未查到 / 不确定（**不得当结论用**）

| # | 事项 | 为什么不确定 | 怎么把它变确定 |
|---|---|---|---|
| **U1** | **改 en_US source + PO 覆盖** 这条改名路径能否生效 | 本仓 t117 只实测了「source 不变、覆盖已有 msgid」（`menu-rename-list.md:70-79`） | §6.6.3 的 4 步小实验，判据 V8.1/V8.4 |
| **U2** | `_inverse_subject_ids` 在 **`create()`** 路径下的实际调用形态 | 只证到「`create` 会调 inverse」（`odoo/orm/models.py:4661-4733`），**没跑过带 `subject_ids` 的 `create`** | 实现时用 `tests/smoke/authz_endtoend_smoke.py:265-266` 那条 `create + write` 组合实测 |
| **U3** | 生产 25 门 `compulsory` 科目**分布在哪几个专业** | 本轮只查了总数与分专业总数，**未逐条交叉** | 按 `op_course_op_subject_rel × op_subject.subject_type` 分组查 |
| **U4** | 「`edu_nav` 生产未装」 | 来自毗邻设计文档的实测记录，**本次未亲自复核** | `select name,state from ir_module_module where name='edu_nav';` |
| **U5** | 263/277/385 的 `ir_model_data.noupdate` | 未读；t117 只验过自己那批菜单是 `noupdate=f`（`menu-rename-list.md:12`） | `select module,name,noupdate from ir_model_data where model in ('ir.ui.menu','ir.actions.act_window') and res_id in (263,277,385);` |
| **U6** | 我们与 `openeducat_fees/views/course_view.xml:4-19` 的**继承顺序/优先级** | 仓内 grep 命中，未实测渲染 | 实施时开一次专业表单看字段位置（R9） |
| **U7** | `edu_portal` 的 `migrations/` 现有版本目录与 manifest `version` | 只知本地有 `19.0.2.0.0` | `ls custom_addons/edu_portal/migrations/` + 现读 manifest |
| **U8** | `op.program.level` 加 `active` 后，基座 `op.program.program_level_id`（**required**）下拉是否会把停用值过滤掉、导致已引用它的 program 编辑报错 | `program.py:39-40` 无 domain，但 Odoo m2o 默认按 `active` 过滤 | 实测：造 1 条 program 引用一个停用 level，打开表单看是否报错（**目前 `op_program` = 0 条 ⇒ 暂无实害**） |

---

## 11. 变更记录

| 日期 | 改动 | 责任 |
|---|---|---|
| 2026-09-19 | 建立本设计：第 0 步查重（全仓 `subject_type` / `compulsory` / `elective` / `subject_ids` / `op.program` 逐条命中与判定）+ 第 3 步读参考（基座四张表 + Odoo 19 computed M2M 机制的运行时源码实证）+ 第 4 步设计摘要（学制复用 `op.program.level`、关系表 `edu.course.subject`、`subject_ids` 兼容层、334 行迁移与回滚、报课页两级 fallback、改名逐条清单、权限四层、9 项真机验收、5 项校长拍板、8 项未验证）。**未写一行代码、未改 `custom_addons/`、未改 `openeducat_erp/`、未改任何库；生产仅只读 SELECT，未触碰匿名意见箱** | 设计子代理（专业编排，`docs/plans/major-track-elective-design.md`） |



