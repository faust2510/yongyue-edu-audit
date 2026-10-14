# 设计：课代表（学生干部身份）+ 我的课程内权限
> **状态**：`已上线` ｜ **主题**：`课代表权限` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「只设计，不含任何实现」，实际已于 `149cab8` 交付（2026-09-26 核对发现）。正文未改动。

> 需求来源：校长两轮拍板 + 队长补充判断（见下「需求基线」）。
> **本文档只设计，不含任何实现**；不改 `custom_addons/`、不改 `openeducat_erp/`。
> 调研依据（铁律 0）：`docs/research/course-representative.md`。
> 初版 2026-09-19；骨架已先行落盘（commit 81273f3），本文为其逐节补全版。

---

## 需求基线（已拍板，不再另设计）

| # | 拍板内容 |
|---|---|
| 1 | **权限清单**：看本课程同学名单（姓名+班级）· 给本课程同学发通知 · **审批本课程的出勤类请假** |
| 2 | **审批人**：任课老师 / 教务 / 管理员 —— **任一都能单独批**（OR 语义，不是串行三级） |
| 3 | **每门课只能有 1 个课代表** —— 必须是**数据库级唯一约束**（先例：`edu_tg_claim` 的 `unique(chat_id)`、`edu.invite.code`），**不许用代码 `if` 判断** |
| 4 | **归还是课代表唯一的自主动作**：不能指定 / 不能提名 / 不能转交给任何人；归还后由教务主任/管理员再任命下一个人 |
| 5 | **兜底到期**：他所在那个班的**结课日期 + 可配置宽限期**（默认 30 天）；宽限期做成系统参数；**必须真实现（cron + 判定处实时判定，双保险）**；**必须回答结课日期字段为空时怎么办**（空值不能把权限永久留下） |
| 6 | **请假审批三护栏**（各要一个负向验收用例）：**只能批本课程** · **不能批自己** · **必须留痕**（记录上显示「由课代表 X 审批」，不能混同老师审批） |
| 7 | **入口**：必须落在**学生主页的「我的课程」**里 |
| 8 | 队长补充：点名只做「提交待老师确认」；作业提交情况**只给「还有几人没交」的统计、不给名单**；上传课程资料**二期**再说 |
| 9 | **写死不给**：看任何人的**成绩** · 改**他人数据** · 看**财务/家庭/身份证** · 审批**非出勤类**申请 |

> ⚠ 本文「学生主页」= `/my/home`（`custom_addons/edu_portal/controllers/batch2.py:1905`，模板 `edu_portal.edu_dashboard_v2`，标题「我的主页」）；
> 「我的课程」的精确落点见 §5.3（含一处**必须纠正的事实**）。

---

## 第 0 步：落地前查重

> 目的：确认全仓**没有**课代表/助教/学生干部的任何既有实现，避免造第二套。
> **搜索范围**：仓库根 = `/Users/qwe/Documents/文件大总管/10-项目/教务系统网站新架构`；
> 覆盖 `custom_addons/`（全部自研模块，含 .py / .xml / .csv / .js / .css）
> 与 `openeducat_erp/`（官方基座源码快照，含 `i18n/*.po`）；`-a` 强制按文本搜。
> 命令一律带 `-rn`（行号 + 文件名），下方「实测命中」为**本次真实执行的输出**，不是估计值。

| # | 关键词 | 命令（在仓库根执行） | 实测命中 |
|---|---|---|---|
| 1 | 课代表 / 班代表 / 课委 | `grep -rn -E '课代表\|班代表\|课委' custom_addons/ openeducat_erp/ --include='*.py' --include='*.xml' --include='*.csv' -a` | **0** |
| 2 | 学生干部 / 班干部 / 班长 | `grep -rn -E '学生干部\|班干部\|班长' custom_addons/ openeducat_erp/ -a` | **0** |
| 3 | 助教 | `grep -rn '助教' custom_addons/ openeducat_erp/ -a` | **8**（全部是「评教类型」或文案，见下） |
| 4 | assistant / representative / course_rep / class_monitor | `grep -rniE 'assistant\|representative\|course_rep\|class_monitor' custom_addons/ openeducat_erp/ --include='*.py' -a` | **0** |
| 5 | ta_* 标识符 | `grep -rnE 'ta_[a-z_]+' custom_addons/ openeducat_erp/ --include='*.py' -a` | **3**（全部是 `ta_review`） |

补充佐证（同一次执行）：
```
$ grep -rn '助教' custom_addons/ | wc -l          → 7（+1 处基座 zh.po 子串误命中）
$ grep -rniE 'assistant|representative|course_rep|class_monitor' custom_addons/ openeducat_erp/ --include='*.py' -a
  （无输出）
$ grep -rn -E '课代表|班代表|课委' … ; grep -rn -E '学生干部|班干部|班长' …
  （两组均无输出）
```

### 命中明细（逐行核对，**没有一处是「助教实体」**）

```
custom_addons/edu_brand/views/pages.xml:183        以网络授课、助教带领讨论和作业为主要形式。   ← 营销文案
custom_addons/edu_eval/models/admin_eval.py:15     ('ta_review', '助教评教'),                    ← 评教类型枚举
custom_addons/edu_eval/__manifest__.py:4           'summary': '…教师/助教评教…'                 ← 模块简介文案
custom_addons/edu_eval/controllers/eval_portal.py:17   'ta_review': '助教评教',                  ← 评教类型标签
custom_addons/edu_eval/views/eval_views.xml:40     <filter name="filter_ta_review" string="助教评教" …/>  ← 过滤器
custom_addons/edu_eval/views/eval_views.xml:127    <filter name="filter_ta_review" string="助教评教" …/>  ← 过滤器（第二模型）
custom_addons/edu_portal/controllers/batch2.py:307   '对教师与助教的匿名评教'),                ← 首页卡片描述文案
openeducat_erp/openeducat_core/i18n/zh.po:1146     教师和后台办公室。                          ← 与「助教」无关（子串误命中）
```

**核实结论（线索要求核实的一条）**：`ta_review` **确认只是「评教类型」枚举值**
（`edu_eval/models/admin_eval.py:15`、`edu_eval/controllers/eval_portal.py:17`），
语义是「学生对助教的评教」，**不是助教实体**；全仓**不存在**助教模型、助教字段、助教用户组。
⇒ 「课代表」在本仓是**全新概念，零既有实现**，不存在重复造轮子的问题。

### 相关但不同的既有物（必须区分，**不能误当先例照抄**）

| 既有物 | 位置 | 与「课代表」的关系 |
|---|---|---|
| 「同班同学」名单（**只姓名+班名**） | `custom_addons/edu_portal/controllers/contacts.py:127-151` | **形态可直接复用**：`{'name': …, 'class_name': …}`，与需求①「姓名+班级」逐字吻合。但它按 **batch（班）** 口径，课代表要按 **subject（课程）** 口径 ⇒ 需一个按 subject 的查询，**不是另建一套渲染**。 |
| 审批代理 `edu.approval.delegate` | `custom_addons/edu_portal/models/leave.py:155-201` | **最接近的既有物**：已有「被代理人 / 代理人 / 代理起止日 / 可撤销」= **带有效期的授权**。但它代理的是 **res.users 之间**的审批放行权，粒度是「整人」而非「某门课」，且只是放行判定、不是身份。⇒ **抄形态，不抄粒度**。 |
| 评估名单 `edu.assess.roster` | `custom_addons/edu_assess/models/assess.py` 的 `EduAssessRoster` 整类 | 不是课程花名册，是**评教任务的对象名单**。但它给出了本仓 **Odoo 19 唯一约束的正确写法**（`models.Constraint('UNIQUE (task_id, subject_ref)', …)` = 今 `EduAssessRoster._roster_subject_uniq`）与「不用可空外键做唯一键」的理由（今在 `EduAssessRoster.subject_ref` 的 `help` 里：Postgres 里 NULL≠NULL）⇒ **唯一约束照它写**。 |
| `op.subject.registration` | `custom_addons/edu_portal/models/registration.py` | 选课/换班**注册单**（申请→审批→生效），但表达的是「学籍变更」，**不是「某人在某课里的角色」**。 |

### 查重结论与台账登记

- **零重复**：没有任何既有实现与「课代表」重叠 ⇒ **不在 `docs/audit/deprecated-inventory.md` 追加行**
  （该台账登记的是「已隐藏/已弃用」的**菜单与模型**三态，且明确「维护：docs-eng」）。
- 唯一一处「像弃用」的东西是 `edu_portal.edu_home_timeline` 模板（`views/study.xml:257`）——
  它**未被任何路由引用**，但这是 `study.xml:253-255` 注释**刻意保留**的（H-1 零删除红线），
  **不属弃用**，故也不登记。若队长要求登记，请由 docs-eng 按台账锚点口径追加。

### 唯一约束的写法口径（直接决定需求③能否成立）

1. **Odoo 19 已废弃 `_sql_constraints`**：本仓多处注释明写「Odoo19 新约束 API：旧 `_sql_constraints` 会被框架静默忽略」
   （`edu_life/models/checkin_record.py:29`、`edu_portal/models/downloads.py:311`、`edu_portal/models/lms.py:153`、
   `edu_eval/models/admin_eval.py:118`）⇒ **必须用 `models.Constraint(...)`**。
   ⚠ 本仓仍有 4 处旧写法未迁移（`edu_telegram/models/flow.py:15`、`binding_code.py:22`、`telegram_chat.py:20`、
   `edu_portal/models/alert_read.py:29`）——**那是历史遗留，不得作为先例照抄**。
2. **PostgreSQL 的 `ADD CONSTRAINT … UNIQUE` 不支持 `WHERE`** ⇒ 「部分唯一索引」
   （`UNIQUE(subject_id) WHERE state='active'`）**无法用 `models.Constraint` 表达**，只能靠 `init()` 手写
   `CREATE UNIQUE INDEX`——那会变成第二套写法，违反「照既有先例的形态写」。
   ⇒ 这是 §1 选择「**每科目一行、槽位复用**」而不是「每任期一行」的**直接原因**。

---

## 1. 载体裁定

### 外部依据（铁律 0，详见 `docs/research/course-representative.md`）

三件事决定了下面的裁定，每条都有独立的一手证据：

| 依据 | 来源（一手） | 对本裁定的作用 |
|---|---|---|
| **不能装现成的**：Odoo 19 核心无「某人在某课程/班级内有限权限 + 有效期」的模型（组是**全局**的、`ir.rule` 是静态 domain、全无日期字段） | `res_users.py#L257-L259`、`res_groups.py#L16-L37`、`ir_rule.py#L22-L30`（19.0 head `6bae1e2f`） | 排除候选 B（Odoo 组）——**不是我们没想到，是 Odoo 没有** |
| **OCA 也没有**：`vertical-education` 19.0 **空仓零模块**；全组织 266 仓 + 应用商店检索 = 0 命中；唯一可用的 `base_user_role`（LGPL-3）作用域是「用户 ↔ **全局**角色」，**没有课程维度** | <https://github.com/OCA/vertical-education/tree/19.0>；<https://github.com/OCA/server-backend/blob/19.0/base_user_role/models/role.py#L172-L192> | **不引入 OCA 依赖**（省一份依赖 + AGPL 风险面），只抄它的写法 |
| **可抄的现成形状**：Canvas 把「助教」做成**课程下的一等公民 enrollment**（`TaEnrollment`），权限用 `available_to/true_for` 矩阵，时效用 `start_at/end_at` + **5 分钟粒度服务端 cron 主动失效** + 「临时注册」到期动作**三选一** | `app/models/enrollment.rb#L21-L28`、`config/initializers/permissions_registry.rb`、`app/models/enrollment_state.rb#L154-L184`、`config/initializers/periodic_jobs.rb#L301-L302` | **本设计的直接蓝本**：`edu.course.rep` ≈ `enrollment`；「实时判定 + cron」双保险 ≈ Canvas 的 `end_at` + `recalculate_expired_states` |
| **数据模型最干净的先例**：Moodle `role_assignments(userid, roleid, contextid)`（`contextlevel=50` = 一门课） | `moodle/lib/db/install.xml#L1301-L1325`、`lib/accesslib.php#L122-L136` | **抄数据模型**：我们的 `(subject_id, student_id)` 槽位是它的简化版，天然支持「同一人在 A 课是课代表、B 课是学生」 |
| **时效绝不抄 Moodle**：1.9 有 `timestart/timeend`，**2.0 主动删除**（升级脚本注释原文「hidden is completely removed, timestart+timeend are now in the user_enrolments table」） | `moodle/lib/db/upgrade.php#L4326-L4370` | ⇒ 时效只学 Canvas，**不学 Moodle** |
| **「学生做审批人」不是我们发明的**：钉钉通用审批引擎支持「表单内联系人审批」（发起人指定审批人）；「代理人设置」= 授权强制带 **[代理时间] 且可撤销** | <https://help.dingtalk.io/zh/approval/set-form-contact-approval.md>；<https://help.dingtalk.io/zh/approval/admin-agent-settings.md> | 需求②（学生做审批人）与需求⑤（带到期）**都有国内大厂同类先例**；后者与本仓 `edu.approval.delegate` 形态完全一致 |
| **⚠ 唯一必须自研且无先例的域对象**：**「学生请假 / 出勤类审批」** —— Canvas 核心**没有**考勤/请假模型（`attendance` 只作第三方 LTI 示例出现），Moodle 是第三方插件，国内教务 SaaS 无成品 | `canvas/doc/api/tools_xml.md#L79-L81` | **需求①的第三条（审批出勤类请假）无现成可抄**，必须自研且**挂到既有 `edu.leave`**（§6.1） |
| **需求③的写法被外部证实**：`_sql_constraints` 在 Odoo 19 **静默失效**（不报错、约束不建库） | `odoo/orm/model_classes.py#L162-L164`、`orm/registry.py#L233`、官方迁移器 `upgrade_code/18.1-00-sql-constraint.py` | 唯一约束**必须**写 `models.Constraint('UNIQUE (subject_id)')`；本仓 4 处旧写法建议单独立项核查 |

> **一句话**：**能抄形状（Canvas/Moodle/钉钉），不能装模块；课程维度 + 「学生请假审批」这两块世面上没有，必须自研。**

### 候选与打分

| 候选 | 能表达「某一门课」？ | 能表达「有效期」？ | 能表达「每课唯一」？ | 裁定 |
|---|---|---|---|---|
| **A. 新建 `edu.course.rep`**（subject_id + student_id + state + 期限） | 可以，一等字段 | 可以，字段 + 实时判定 | 可以，`models.Constraint('UNIQUE(subject_id)')` | **采用（主干）** |
| B. Odoo 组 + `ir.rule`（把课代表做成 `res.groups` 成员） | 不行：组是**全局**的，成员资格没有 subject 维度 | 不行：组不得到期，`ir.rule` 是静态 domain | 不行：无法用组表达「本课仅 1 人」 | **否决**（只借它的 `ir.rule` 做**行级纵深防御**） |
| C. 复用既有审批模型加类型 | 可以（给 `edu.leave` 加 `subject_id`） | 不行：审批单不是身份 | 不行 | **部分采用**：作为**请假审批的挂载点**，不作为课代表身份载体 |
| D. 复用 `op.subject.registration` 加类型 | 可以 | 不行 | 不行 | **否决**（语义是学籍变更单，混入「身份」会污染审批域） |

### 裁定：**新建 `edu.course.rep`，一张表、每科目一行（槽位复用）**

理由（逐条对应校长硬要求）：

1. **唯一约束必须硬** ⇒ 表设计成「**一个科目一个槽位**」：`subject_id` 非空，
   `models.Constraint('UNIQUE (subject_id)', '每门课只能有一位课代表。')`。
   这与 `edu_tg_claim`（`edu_tg_bind/models/tg_claim.py:87-90`，`unique (chat_id)` / `unique (invite_code_id)`）、
   `edu.invite.code`（`edu_portal/models/invite_code.py:148`，`unique (code)`）**同一形态**，
   是**数据库层**保证，**不依赖任何代码分支**。
2. **不能每任期一行** ⇒ 若每任期一行，唯一约束必须写成部分唯一索引（`WHERE state='active'`），
   而 `models.Constraint` 表达不了（§0）⇒ 会引入第二套写法。故用**槽位复用**：
   归还 / 到期 / 撤销 **不删行、不新建行**，只改 `state`；下一次任命**覆盖同一槽位**的 `student_id`。
   任期历史由 `edu.audit.log` 承载（§4 各小节留痕 + §9.1 收口触发条件）。
   > ⚠ 这是本设计的**核心取舍**：以「唯一约束的硬度」优先于「任期数据自然成表」。
3. **不新建 Odoo 组** ⇒ 组无 subject 维度；且给 `base.group_portal` 加组会**全局**提权
   （学生可能看到不该看的东西），属「一处授予、处处生效」的错误粒度。
   权限一律在**判定函数 + 控制器 + ir.rule** 三层收口。
4. **不新建第二套请假模型** ⇒ 现场有且**只有一个**学生请假模型 `edu.leave`
   （`custom_addons/edu_portal/models/leave.py:47`，`_name = 'edu.leave'`）。
   ⚠ **纠正线索给出的方向**：`edu_life` 里**没有** `edu.leave` ——
   `grep -rn 'leave' custom_addons/edu_life/` **0 命中**（已实测）。
   另有 `custom_addons/edu_telegram/models/leave_request.py:13`（`leave_type = fields.Selection(…)`）
   属**匿名意见箱 / Telegram 通道**的独立假单表——**红线区域，本文档不碰、不设计、不查询**。
   课代表的审批能力**挂在 `edu.leave`**，不外挂。

### 复用 / 新建 一览（含**收口触发条件**）

| 能力 | 复用既有 | 新建 | 收口触发条件（何时才允许改裁定） |
|---|---|---|---|
| 课代表身份 | — | `edu.course.rep`（1 张表） | 若要「历届课代表名单」页 ⇒ 加**只读** `edu.course.rep.term` 流水表，**主表唯一约束不变** |
| 行级权限 | `edu_portal/security/security.xml` 的 ir.rule 形态（全文 111 行，8 条规则） | 追加 1 条 ir.rule | 若不新增可被 RPC 直读的模型则**不加**规则（禁止「看起来安全」的空规则） |
| 通知 | `edu.message._notify_event()`（`edu_portal/models/notify_pref.py:51`）+ `NOTIFY_EVENTS`（:15-24） | 新增 2 个事件 key | 若要通知**未登录学生**（短信/微信）⇒ 另立需求，不在本设计内 |
| 留痕 | `edu.audit.log._log()`（`edu_portal/models/audit.py:29`） | 无 | — |
| 审批对象 | `edu.leave`（`edu_portal/models/leave.py:47`） | 给 `edu.leave` 加 4 个字段 | 若「一次请假覆盖多门课」⇒ 字段改 M2M，属改裁定 |
| 审批域 | `approval_scope_domain()`（`edu_portal/controllers/roles.py:2580`）的**形态** | 一个**独立**的课代表域函数 | 若要把教师/课代表域**合并成一套** ⇒ 必须先证明二者语义相同。**目前不同**：教师按 batch、课代表按 subject |
| 名单形态 | `contacts.py:148-151` 的 `{'name','class_name'}` | 按 subject 的查询 | — |
| 点名 | `op.attendance.sheet` / `op.attendance.line` / `/attendance/take` | 1 个「待确认」标记字段 | 若教师要求课代表补录历史考勤 ⇒ 改裁定 |
| 作业统计 | `op.assignment` + `op.assignment.sub.line` | 无（只算数） | 若要给未交名单 ⇒ **违反需求⑧，禁止** |

---

## 2. 数据模型

### 2.1 新建 `edu.course.rep`（课代表，每科目一行）

放在 `custom_addons/edu_portal/models/course_rep.py`（与 `edu.leave` 同模块 ⇒ 可直接引用，无循环依赖）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `subject_id` | Many2one `op.subject`，**required**，index，ondelete=`cascade` | 槽位键 |
| `student_id` | Many2one `op.student`，index，ondelete=`set null` | 现任 / 最近一任课代表；空闲槽位为空 |
| `state` | Selection `active` / `vacant` / `expired` / `revoked`，default `vacant`，index | **唯一约束不依赖它**（靠 `subject_id`）；它只表达「是否在任」与「为何离任」 |
| `appointed_by_id` | Many2one `res.users`，ondelete=`set null` | 任命人（教务 / 管理员） |
| `appointed_at` | Datetime | 任命时刻（同时是 §4.3 第③层兜底上限的起算点） |
| `expires_at` | Date（**compute + store**） | **冗余快照**，只供 cron 扫描与页面展示；**权限判定不读它**（§4.3） |
| `deadline_source` | Selection `batch` / `term` / `cap` / `none`（compute + store） | 期限来自哪一层（可解释性 + 运维排查） |
| `vacated_at` / `vacated_by_id` / `vacate_reason` | Datetime / M2o / Text | 归还、到期、撤销的收口记录 |
| `active` | Boolean，default True | 本仓通用软删口径 |

**唯一约束（需求③的落点，逐字）**：

```python
_subject_uniq = models.Constraint(
    'UNIQUE (subject_id)',
    '每门课只能有一位课代表（同一科目不能有两个槽位）。')
```

> 与 `edu_tg_claim` 的 `unique (chat_id)` / `unique (invite_code_id)`（`edu_tg_bind/models/tg_claim.py:87-90`）
> **同构**；Odoo 19 新约束 API 的写法照 `edu_assess/models/assess.py` 的 `EduAssessRoster._roster_subject_uniq`。
> **不是代码 `if` 判断**，并发下也挡得住——与 `tg_claim.py:18` 记载的三层防线同思路
> （SKIP LOCKED 挡在途 + DB 唯一约束做最后也最硬的一层）。

### 2.2 修改既有 `edu.leave`（**只加字段，不改既有行为**）

| 新字段 | 类型 | 用途 | 兼容性 |
|---|---|---|---|
| `subject_id` | Many2one `op.subject`，可空，index | 「本课程」的归属；学生提交时从「我的课程」里选 | **可空** ⇒ 既有数据不回填、老单据行为一字不变 |
| `approver_id` | Many2one `res.users`，可空，ondelete=`set null` | 实际审批人 | 可空 |
| `approver_kind` | Selection `student_rep` / `faculty` / `registrar` / `admin`，可空 | **需求⑥的核心**：区分课代表与老师 | 可空（既有已批单据为空，显示「—」） |
| `approved_at` | Datetime，可空 | 审批时刻 | 可空 |

> **不改** `leave_type` 的 Selection 取值（`edu_portal/models/leave.py:53-58`：`sick`/`legal`/`casual`/`other`），
> 「出勤类」用**系统参数映射**表达（§6.2），避免改枚举带来的既有数据与多语言映射风险。

### 2.3 修改既有 `op.attendance.sheet`（点名「待老师确认」）——**口径 (b+)，队长已裁定**

> **队长裁定（2026-09-19）**：**不采用**「按科目另建 register」的做法（会让同一班同一天出现
> 多张互相看不见的点名表，与教师侧「按 (course,batch) 复用 + 按天查重」**直接冲突——是必撞，不是要确认**）。
> 采用 **(b+)：点名仍落既有的「一天一张整班点名表」，不改教师侧任何行为（零回归）；
> 但用本仓 `_inherit` 给 `op.attendance.sheet` 加自研字段记录科目辨识度与提交人。**

自研字段（`_inherit`，**不动基座**；**字段只用于辨识与留痕，不参与唯一性**）：

| 字段 | 类型 | 用途 |
|---|---|---|
| `rep_subject_id` | Many2one `op.subject`，可空 | **这是为哪个科目点的**（课代表是 subject 级 ⇒ 科目辨识度不能丢） |
| `submitted_by_rep_id` | Many2one `edu.course.rep`，可空 | 提交人（课代表） |
| `rep_submitted_at` | Datetime，可空 | 提交时刻 |

- **复用既有 `state`**（`openeducat_erp/openeducat_attendance/models/attendance_sheet.py:50-53`，
  `draft`/`start`/`done`/`cancel`）：课代表提交后停在 **`start`**（已开、未落定），
  **只有教师能调 `attendance_done()`**（:57-58）落定。
- **不改既有唯一性**：模型层只有 `_unique_register_sheet`（:64-66）与
  `/attendance/save` 流程层的 `(course_id, batch_id, attendance_date)` 查重（`roles.py:514-519`）
  ⇒ **保持「一个班一天一张表」**。`rep_subject_id` **绝不参与**唯一键。

#### ⚠⚠ 已核实的阻塞点：老师**看不见**课代表提交的待确认表（必须补做）

**取证**：读 `custom_addons/edu_portal/controllers/roles.py:380-476`（教师点名 `/attendance/take` 全文）。

| 事实 | 证据 |
|---|---|
| 教师 GET `/attendance/take` **不按日期查询「今日已有点名表」**，渲染的是一张**空白录入表单** | `roles.py:395-404` 只取班级学生；:432-443 的 `Sheet.search` **只查「上一次」**用于「复制上次记录」（`order='attendance_date desc, id desc', limit=1`），**不是查今天** |
| 唯一的「重复」感知在 **POST** `/attendance/save` 里：按 `(course_id, batch_id, attendance_date)` 查重后 303 回 `?dup=1&dup_sheet=<id>` | `roles.py:514-523`；`/attendance/take` 只是把 `dup`/`dup_sheet` 透传给模板（:471-473） |
| 教师侧**没有**「待确认点名」列表 | `roles.py` 无对应路由；模型层也**没有**模型级查重（`attendance_sheet.py:77-84` 的 `create` 只写 `name` 序列号） |
| ⇒ 结果 | **课代表提交了一张 `state='start'` 的表，老师那头没有任何入口能看到它**；老师当天去点名只会被自己的 dup 分支拦下（或另生一张，取决于 session_id 是否为空——`unique(register_id, session_id, attendance_date)` 在 `session_id` 为 NULL 时**不生效**，因 PostgreSQL 里 NULL≠NULL） |

**必须补做（否则「课代表点名」等于没做）**——两条一起做：

1. **老师侧「待确认」入口**：`/attendance/take` 的 GET 增加「该班该日**已存在**的点名表」查询并渲染
   （状态 + 提交人 + 提交时刻 + 一键确认），复用既有的 `dup`/`dup_sheet` 模板参数位
   （`roles.py:471-473` 已在透传，**模板 `edu_portal.edu_attendance_take` 已有渲染位置**）；
   **或**另立一个「待确认点名」列表页（改动更大，**不推荐**）。
   ⇒ 推荐**前者**：改动小、与零回归目标一致。
2. **站内通知**：课代表提交后，给该班该课的任课老师发站内信
   （`_notify_event('attendance_rep_submitted', 教师账号, …)`，**需新登记 `NOTIFY_EVENTS`**；
   收件人 = 该课 `op.session.faculty_id` 对应账号，用 `users_of_profile` 反查，见 §3.1）。

> ⚠ 这两条是**新增工作量，未计入原设计**，必须在排期时单列。
> 依据：队长裁定「课代表提交了但老师永远看不见，等于这个功能没做」

### 2.4 不新建的东西（写清，防后续漂移）

- **不新建**课代表的 Odoo 组；除 `edu.course.rep` 的 ACL 外不加权限实体。
- **不新建**第 2 个请假模型、不新建考勤模型、不新建通知模型。
- **不新建**课代表任期流水表（除非触发 §1 的收口条件）。
- **不建**任何「课代表可提名 / 可指定 / 可转交」的字段——需求④明文禁止，
  **不给字段就是最硬的护栏**。

---

## 3. 数据流

### 3.1 身份解析（**复用唯一实现，禁止自写反查**）

`from odoo.addons.edu_schedule.models.identity import student_of_user, users_of_profile`
（`custom_addons/edu_schedule/models/identity.py:94-172`）。

- 登录账号 → 学生档案：`student_of_user(env)`（**双向并集**：① `record.user_id`，①落空才查 ② `partner_id.user_ids`）。
- 学生档案 → 登录账号（通知收件人）：`users_of_profile(profiles)`（取并集、逐个发）。
- **理由**：本仓今天刚因这条踩过坑（commit `f0e3f3c`「统一『由 user 反查身份档案』口径为双向并集」）；
  `identity.py:26-39` 明写「需要本模块的模块若不在依赖闭包里，请把 edu_schedule 加进 depends，
  **不要就地复制一份**——复制出来的一定是第二套口径（本仓已因此踩过两次）」。
  `edu_portal` 已在 `depends` 声明 `edu_schedule`（`edu_portal/__manifest__.py:31`）⇒ 可直接 import，无需改依赖。

### 3.2 「我的课程」数据域（复用学生视角口径）

`edu_portal/controllers/lms.py:24-30`（`_subjects_for`）注释逐字：
「个人选课联动：学生视角 = 在读档案 `op.student.course.subject_ids`」。
⇒ 课代表身份的课程集合与「我的课程」页面**同一来源**，
不会出现「页面上没有这门课、却能在该课行使权限」的不一致。

### 3.3 本课程同学名单

口径（按 **subject**，与 `contacts.py` 按 **batch** 不同）：

```
students = op.student.course.search([('subject_ids', 'in', [subject_id]),
                                     ('state', '=', 'running')]).mapped('student_id')
```

渲染字段**逐字沿用** `contacts.py:148-151` 的 `{'name': …, 'class_name': …}`：
- `name` = `op.student.name`
- `class_name` = 该生**在这门课**的 `op.student.course.batch_id.name`（同一学生多班时 `' / '` 连接、去重）

**只姓名 + 班级**——不给学号、邮箱、手机、头像（与校长拍板 P3-(a) 同口径，见 `contacts.py:127-131`）。

### 3.4 发通知

`edu.message._notify_event('course_rep_notice', user, body, sender_uid=rep_user.id)`
（`edu_portal/models/notify_pref.py:51-81`），并**在 `NOTIFY_EVENTS`（:15-24）登记新 key**
（该表同时驱动 `/my/notify` 的静音开关；不登记 ⇒ 用户在偏好页看不到这一类）。
收件人 = §3.3 名单的**登录账号并集**（复用 `users_of_profile`），**排除课代表自己**。
同时写 `edu.audit.log`（`action='课代表发通知'`）。

### 3.5 请假审批数据流

```
学生在 /my/time_off 提交请假（可选「涉及课程」= 自己 subject_ids 里的一门）
  → edu.leave{state='request', subject_id=?, student_id=…}
  → 课代表打开「本课程请假待批」队列
       ├─ 队列域 = 三条同时成立：
       │    ① edu.leave.subject_id ∈ 我的在任课程
       │    ② edu.leave.state = 'request'
       │    ③ edu.leave.student_id ≠ 我本人的学生档案     ← 需求⑥「不能批自己」
       └─ 点「通过 / 驳回」（POST /my/courses/<sid>/rep/leave/set_state）
            → 服务端**重新判定**（不信前端）：在任 + 同课程 + 非本人 + 出勤类
            → state = approved / refused
            → 写 approver_id=我、approver_kind='student_rep'、approved_at=now
            → edu.audit.log._log('请假审批(课代表)', 'edu.leave', …)
            → edu.leave._notify_applicant(new_state)     ← 复用既有通知
```

### 3.6 兜底到期的数据流

```
期限 = min( 第①层：该生在这门课的班级结课日 + 宽限期 ,
            第②层：该生在该课的学期结束日          ,
            第③层：任命日 + 硬上限天数 )            ← 第③层永远有值
每层取值处若为空 ⇒ 下沉到下一层；三层全空 ⇒ 不可能（③ 一定有值）
```
详见 §4.3。

---

## 4. 权限的授予 / 归还 / 兜底到期 / 中途撤销

> 四件事各自的动作 + 留痕。**留痕统一走 `edu.audit.log._log()`**
> （`custom_addons/edu_portal/models/audit.py:29-41`，本仓通用留痕，**失败只告警、绝不阻断业务事务**；
> 查询页 `/edu/audit` 仅教务处与管理员可见，见 `audit.py:3-6` 的 docstring）。

### 4.0 授予（任命）

| 项 | 内容 |
|---|---|
| 谁能做 | 教务主任（`openeducat_core.group_op_back_office_admin`）/ 管理员（`base.group_system`）—— 复用 `privileged_staff()`（`controllers/roles.py:159-166`） |
| 入口 | **后台** `edu.course.rep` 列表上的「任命」按钮（**不在学生门户**） |
| 动作 | 槽位 `state ∈ {vacant, expired, revoked}` → 写 `student_id` / `appointed_by_id` / `appointed_at` / `state='active'` |
| 校验（唯一约束之外的部分） | 候选人**必须是该课程的注册学生**（在 `op.student.course.subject_ids` 里），否则拒绝 |
| 唯一性 | **交给 DB**（`UNIQUE(subject_id)`）。并发双击 / 两人同抢同一课 ⇒ 第二笔撞约束、整个事务回滚，UI 显示友好错误文案（**不做前置 `if` 判断**） |
| 留痕 | `_log('课代表任命', 'edu.course.rep', id, <科目名>, '任命 <学生名>(id) 为课代表；期限 <expires_at>（来源 <deadline_source>）')` |
| 通知 | `_notify_event('course_rep_appointed', 该生账号, …)` —— **需新登记事件 key** |

### 4.1 归还（课代表**唯一**的自主动作）

| 项 | 内容 |
|---|---|
| 谁能做 | **只有现任课代表本人**；且**只允许这一个动作**（无「提名 / 指定 / 转交」入口，模型层也没有对应字段） |
| 入口 | 学生「我的课程」→ 该课程卡 → 课代表面板的「**辞去课代表**」按钮（POST `/my/courses/<sid>/rep/release`） |
| 动作 | `state='vacant'`；`vacated_at=now`、`vacated_by_id=me`、`vacate_reason='本人归还'`；**保留 `student_id`**（= 上一任，供教务核对，**不参与任何权限判定**） |
| 校验 | 服务端重新判定「我是该槽位的 active 且未到期」；否则按不存在处理（303 回课程页） |
| 效果 | **立即失效**（判定读 `state=='active'` ⇒ 归还瞬间所有权限消失） |
| 留痕 | `_log('课代表归还', 'edu.course.rep', id, <科目名>, '本人归还；上一任 <学生名>')` |
| 不做什么 | **不自动任命下一人**（需求④明文：由教务主任/管理员再任命） |

### 4.2 中途撤销（教务/管理员强制解除）

| 项 | 内容 |
|---|---|
| 谁能做 | 教务主任 / 管理员（同 §4.0） |
| 入口 | 后台 `edu.course.rep` 的「撤销」按钮 |
| 动作 | `state='revoked'`；`vacated_*` 同上；`vacate_reason` **必填**（如「学生转班」「违规」） |
| 效果 | 立即失效（同 §4.1） |
| 留痕 | `_log('课代表撤销', 'edu.course.rep', id, <科目名>, 原因)` + 通知被撤销的学生 |

### 4.3 兜底到期（**双保险 + 空值答案**）

#### 期限怎么算（三层阶梯，**自上而下取第一个可用值**，最后取 `min`）

| 层次 | 来源 | 计算 | 本仓依据 |
|---|---|---|---|
| ① 主 | 该生在这门课的**班级结课日** | `op.batch.end_date` **+ 宽限期**（系统参数，默认 30 天） | `openeducat_erp/openeducat_core/models/batch.py:34` `end_date = fields.Date('End Date', required=True)`；链路 `edu.course.rep(student, subject) → op.student.course(student_id, subject ∈ subject_ids) → batch_id → op.batch.end_date`（`openeducat_core/models/student.py:33-38`） |
| ② 次 | 该生在该课的**学期结束日** | `op.student.course.academic_term_id.term_end_date`（**不加宽限期**） | `student.py:38` `academic_term_id`；`op_academic_term.py:21` `term_end_date = fields.Date('End Date', required=True)` |
| ③ 兜底硬上限 | 任命日 + `edu_portal.course_rep_max_days`（默认 **180**） | `appointed_at + 180d` | 系统参数先例：`edu_portal/models/leave.py:17-23` 的 `escalate_hours()` 读 `edu_portal.approval_escalate_hours`（默认 48）——**同写法** |

最终 `deadline = min(①, ②, ③)`（①②有值才参与比较，③**永远有值**）。

#### ⚠ 空值时怎么办（校长点名要回答的问题）

> **一句话答案：空值 ⇒ 下沉到下一层；因为第③层永远有值，所以「无期限」这个状态在本设计里根本不存在——权限永远拿不到永久。**

逐种空值情形（**全部 fail-closed，绝不 fail-open**）：

| # | 空的是什么 | 实际后果 | 处理 |
|---|---|---|---|
| 1 | `op.student.course.batch_id` 为空（该字段**非 required**） | ①层取不到结课日 | 下沉②；②也空 ⇒ 下沉③ |
| 2 | **找不到**匹配的 `op.student.course` 行（刚任命但没分班 / 已退课） | ①②都取不到 | 下沉③（任命日 + 180 天）；管理页同时打**「该生在此课程无在读档案」**告警 |
| 3 | `op.batch.end_date` 为空 | 理论不可能（`required=True` ⇒ DB NOT NULL），但历史数据 / 直连 SQL 可能造出 | 视为该层不可用、下沉；**绝不当作「无到期」** |
| 4 | `academic_term_id` **链接**为空（不是字段为空） | ②层不可用 | 下沉③ |
| 5 | 三个月后学生退课/换班 ⇒ ①层重算出更早的日期 | 权限**提前**失效 | **这是期望行为**（判定处实时计算，不读旧快照） |

**硬规则（写进实现铁律，防后人漂移）**：

> `deadline is None` **永不等于**「永久有效」。实现层**禁止**出现
> `if not deadline: return True`；正确写法是 `if not deadline: return FALLBACK_CAP`（③层）。
> 单测必须覆盖：「①②全空 ⇒ `is_active_for` 在 `appointed_at + 180d` 之后返回 False」。

#### 双保险机制（需求⑤明文要求「cron 或判定处实时判定，要求双保险」）

- **保险一（实时判定 = 唯一事实源）**
  单一函数 `edu.course.rep.is_active_for(student, subject)`（或 `active_reps_for(student)`）
  **每次判定都实时重算期限**，条件 = `state == 'active'` **且** `now <= min(①②③)`。
  **所有权限点**（看名单 / 发通知 / 批假 / 点名 / 作业统计）**必须先过这个函数**；
  **禁止**任何地方直接写 `if rep.state == 'active'`（那会绕过期限）。
  实时重算的好处：宽限期参数一改、结课日一改，**立刻生效**，没有快照漂移。
- **保险二（cron 收口）**
  `ir.cron` **每日一次**扫 `state='active'` 但实时判定已过期的槽位 → 写 `state='expired'` +
  `vacated_*` + `_log('课代表到期失效', …)` + 通知学生与教务处。
  形态照本仓既有 cron（`edu_portal/views/roles.xml:1968-1987` 的 `ir_cron_edu_leave_escalate`：
  active 幂等、失败不炸事务）。
  **cron 不是权限依据**：即使 cron 三天没跑，权限也已在实时判定处失效——这正是「双保险」的含义。

#### 系统参数（需求⑤要求「做成系统参数」）

| 参数 key | 默认 | 用途 | 先例写法 |
|---|---|---|---|
| `edu_portal.course_rep_grace_days` | `30` | ①层宽限期 | `models/leave.py:17-23` |
| `edu_portal.course_rep_max_days` | `180` | ③层硬上限（**空值兜底的关键**） | 同上 |
| `edu_portal.course_rep_leave_types` | `sick,casual` | 「出勤类请假」白名单（§6.2） | 同上 |

全部**读时容错**（`try/except` + 保底默认值），照 `leave.py:18-23` 的 `escalate_hours()` 写。

---

## 5. 路由与动作清单

### 5.1 学生侧（课代表本人）——**只读 + 3 个写动作**

| 路由 | 方法 | 谁能进 | 作用 | 状态 |
|---|---|---|---|---|
| `/my/courses` | GET | 学生（既有） | **「我的课程」落点**：课程卡上加「课代表」徽标（在任才渲染） | 改造既有（`controllers/lms.py:45`，模板 `views/lms.xml:93` = `edu_lms_courses`） |
| `/my/courses/<int:subject_id>` | GET | 学生（既有） | 该课程课次页；在任课代表时**追加「课代表」面板入口** | 改造既有（`lms.py:97`，模板 `views/lms.xml:136` = `edu_lms_lessons`） |
| `/my/courses/<int:subject_id>/rep` | GET | **仅该课在任课代表** | 课代表面板（同学名单 / 发通知 / 待批请假 + 辞去按钮） | **新增** |
| `/my/courses/<int:subject_id>/rep/notify` | POST | **仅该课在任课代表** | 给本课程同学发通知 | **新增** |
| `/my/courses/<int:subject_id>/rep/leave/set_state` | POST | **仅该课在任课代表** | 通过 / 驳回本课程出勤类请假 | **新增** |
| `/my/courses/<int:subject_id>/rep/release` | POST | **仅该课在任课代表** | **辞去课代表**（唯一自主动作） | **新增** |
| `/my/time_off`（既有） | GET/POST | 学生 | 提交请假时**新增可选字段「涉及课程」**（下拉 = 自己的 subject_ids） | 小幅改造既有（`controllers/batch3.py:716` / `:455`） |

### 5.2 教师侧 / 后台侧

**教师侧（改造既有，见 §2.3 的阻塞点）**

| 位置 | 作用 | 状态 |
|---|---|---|
| `/attendance/take`（既有 GET） | **新增**「该班该日已存在的点名表」渲染 + 一键确认（含「课代表已提交」标识） | **改造既有**（`controllers/roles.py:380-476`；模板 `edu_portal.edu_attendance_take`，参数位 `dup`/`dup_sheet` 已在 `roles.py:471-473` 透传） |
| `/attendance/save`（既有 POST） | **不改**（保持 dup 查重与回跳） | 零回归 |
| 站内通知 | 课代表提交后给任课老师发信（新事件 key `attendance_rep_submitted`） | **新增** |

**后台侧（教务/管理员）**

| 位置 | 作用 |
|---|---|
| 后台菜单 `edu.course.rep` 列表 | 查看每门课的槽位与状态；筛「在任 / 空缺 / 已到期 / 已撤销」 |
| 表单按钮「任命 / 变更 / 撤销」 | §4.0 / §4.2 |
| 列「期限」+「期限来源（`deadline_source`）」 | 可解释性：让教务一眼看出为什么是这个日期 |
| `/edu/audit`（既有） | 四件事的留痕查询，**无需新建页面** |

### 5.3 「我的课程」的精确落点（回答需求⑦）

现场有**三个**都在叫「我的课程 / 课程」的页面，必须先说清是哪个（**不要造第四个**）：

| # | 路由 | 控制器 | 模板（record id） | 页面标题 | 数据源 |
|---|---|---|---|---|---|
| A | `/my-courses` | `custom_addons/edu_public/controllers/main.py:259` | `edu_public.edu_my_courses`（`main.py:280` render） | **「我的课程」**（`main.py:281` 逐字） | `op.student.course.course_id`（**课程级**） |
| B | `/my/courses` | `custom_addons/edu_portal/controllers/lms.py:45` | `edu_portal.edu_lms_courses`（`views/lms.xml:93`） | 学生视角**「我的课程」**（`lms.py:85-87` 的 `{'faculty':'全部课程','staff':'全部课程','parent':'孩子的课程','guest':'课程'}.get(role,'我的课程')`） | **`op.student.course.subject_ids`**（**科目级**，注释 `lms.py:24-26`） |
| C | `/my/study` | `custom_addons/edu_portal/controllers/study.py:273` | `edu_portal.edu_study_home` | 「课程中心」 | 同上（科目级） |
| — | `/my/home` 宫格 | `custom_addons/edu_portal/controllers/batch2.py:1905` | `edu_portal.edu_dashboard_v2` | 「我的主页」 | 卡片索引；「学业」组里的 `my-courses` 卡标题是「**课程**」→ 指向 A（`batch2.py:252-254` 与 `:813`） |

**⚠ 必须纠正的一处事实**：`views/study.xml:305-314` 里那个 `<h2>我的课程</h2>`（≤3 张课程卡）区块，
位于模板 `edu_portal.edu_home_timeline` 内，而该模板**当前没有任何路由引用**——
文件内注释逐字自证（`study.xml:253-255`）：「H-1（2026-09-18）：/my/home 已改渲染 edu_dashboard_v2（宫格）…
本模板**当前无路由引用**，按零删除红线留在册」。
⇒ **不能把课代表入口做进这个区块**（做了也没人看得见），也**不要**为它恢复路由。

**裁定落点（需求⑦「塞入学生主页面的『我的课程』里」）**：

1. **主落点 = B：`/my/courses`（门户 LMS「我的课程」，科目级）** —— 因为：
   (a) 学生在 `/my/home` 宫格点「课程」卡进的正是这条路（A 页再往 B 导）；
   (b) **只有它和课代表的粒度（科目）对齐**（`op.student.course.subject_ids`，`lms.py:24-30`）；
   (c) 它的页面标题逐字就是「我的课程」。
   改动：模板 `edu_portal.edu_lms_courses`（`views/lms.xml:93`）在课程卡上追加「课代表」徽标 + 面板入口按钮。
2. **次落点 = B 的科目页 `/my/courses/<int:subject_id>`**（模板 `edu_lms_lessons`，`views/lms.xml:136`）
   —— 课代表面板的「进入」按钮落在这里，因为「本课程同学 / 本课程请假 / 发通知」都需要课程上下文。
3. **首页快入口（可选，需校长拍板，见 §8-11）**：`/my/home` 宫格「学业」组加一张「课代表」卡
   （仅当该生在**至少一门课**在任时渲染）。
4. **不做**：`edu_home_timeline` 的「我的课程」区块（无路由）、A 页（课程级，粒度不对，
   **只做徽标回链，不承载功能**）。

---

## 6. 请假审批（挂到哪 / 怎么限定范围 / 怎么做到不能批自己）

### 6.1 挂到哪

**挂到既有 `edu.leave`**（`custom_addons/edu_portal/models/leave.py:47`），**不新建模型**。
既有的两条审批入口**一律不动**：
- 门户教师入口：`/leave/approvals` + `/leave/set_state`（`controllers/roles.py:940-1005`）
- 后台按钮：`edu.leave.action_approve / action_reject`（`models/leave.py:104-125`）

课代表新增**第三条门户入口** `/my/courses/<int:subject_id>/rep/leave/set_state`（§5.1），
审批对象是**同一张 `edu.leave` 表**——**不做第二套请假模型**。

### 6.2 「出勤类」怎么区分

`edu.leave.leave_type` 是**硬编码 Selection**（`models/leave.py:53-58`：`sick`/`legal`/`casual`/`other`），
**没有任何「出勤类」标记**；全仓也没有请假类型字典表。

裁定：**用系统参数做白名单映射**，`edu_portal.course_rep_leave_types`（默认 `sick,casual`）：
- 课代表**只能**处置 `leave_type ∈ {sick, casual}` 的单据；
- `legal`（法定假）/ `other`（其他）**一律不进课代表队列、也不许审批**
  （需求⑨「审批非出勤类申请」= 写死不给）；
- 教务改参数即可增减类型，**无需改代码、无需迁移数据**。
- ⚠ 边界：`other` 语义模糊（可能含影响出勤的情形）⇒ **默认排除**（保守），列 §8-8 待校长拍板。

> **不改 Selection 枚举的理由**：改枚举会影响既有数据约束与多处标签映射
> （`roles.py:1014-1017`、`batch3.py:736`、`models/leave.py:77`），属高风险、无收益改动。

### 6.3 怎么做到「只能批本课程」

判定链（服务端**必须重新判定**，不信前端）：

```
leave.subject_id 存在                                  ← 前提①（空 ⇒ 课代表无权，见下）
且 leave.subject_id 严格 ∈ 我的在任课程集合              ← 相邻课程也不行（必须严格相等）
且 is_active_for(我, leave.subject_id) 为真             ← 含期限实时判定（§4.3）
```

- **`leave.subject_id` 为空怎么办** ⇒ **课代表无权批**（fail-closed），该单据只出现在教师/教务队列。
  理由：**没有归属就没有「本课程」**，宁可漏批也不越权批。
- **为什么不复用 `approval_scope_domain()`**（`controllers/roles.py:2580-2592`）：
  它按 **batch（任教班级）** 收敛（`teacher_taught_batches` → `op.student.course.batch_id` → `student_id ∈ …`），
  而课代表要按 **subject（课程）** 收敛。两者**语义不同**（同班同学 ≠ 同课程同学），
  合并成一套必然**放宽**其中一方的作用域。⇒ 新建一个**独立**的域函数，
  但**沿用同一形态**（返回 domain 列表；越权一律按不存在处理——照
  `scoped_record` / `scoped_records`，`roles.py:2595-2613`）。

### 6.4 怎么做到「不能批自己」

**三层，缺一不可**：

1. **进不了队列**：队列域硬加 `('student_id', '!=', my_student.id)`（§3.5 条件③）。
2. **前端不渲染**：自己的单据在列表里**根本不出现**（不是「禁用按钮」——禁用仍可被重放 POST 绕过）。
3. **服务端拒绝**：POST 处理里再判一次 `leave.student_id == my_student → 按不存在处理`
   （303 回队列 + **不写任何字段**）。
   「我」用 §3.1 的 `student_of_user(env)`，**不写第二套反查**。

> 判据是「`student_id` 是否为我本人的**学生档案**」，**不是**「`res.users` 是否相同」——
> 因为一个学生可能有多个登录账号（`identity.py:64-65` 明写反向会返回全部账号）。
> 用**档案 id** 比较才挡得住「同一人两个账号」绕过。

### 6.5 怎么做到「必须留痕，不能混同老师审批」（需求⑥的核心）

**现状（这是本设计必须点出的一处缺口）**：既有的请假审批**根本不记「谁批的」**——
`leave_set_state` 只写 `state`（`roles.py:992`）+ 写审计日志（`roles.py:997-999`，`action='请假审批'`）；
`edu.leave` 本身**没有 `approver_id` / `approver_kind` 字段**。
⇒ 只靠审计日志，**单据页面上看不出「由谁审批」**，达不到校长「记录上显示『由课代表 X 审批』」的要求。

裁定：**给 `edu.leave` 加 3 个字段**（§2.2 `approver_id` / `approver_kind` / `approved_at`）：

- 课代表审批 ⇒ `approver_kind='student_rep'`；教师 ⇒ `'faculty'`；教务 ⇒ `'registrar'`；管理员 ⇒ `'admin'`。
- **既有的两条审批入口顺带补写这三个字段**——否则同一张表上「有的假单显示审批人、有的不显示」，**口径分裂**。
  ⚠ 这是**唯一一处**要改既有审批路径的地方（**队长 2026-09-19 已批准**）。**落点逐处列清（共 4 处写入点）**：

  | # | 落点 | 现状 | 要补写什么 |
  |---|---|---|---|
  | 1 | `controllers/roles.py:973-1005` `leave_set_state`（**门户教师/教务**单条审批） | :992 只写 `{'state': new_state}` | 同一次 `write` 里补 `approver_id=env.user.id`、`approver_kind`（`faculty` 或 `privileged_staff()` ⇒ `registrar`/`admin`）、`approved_at=fields.Datetime.now()` |
  | 2 | `controllers/roles.py:1888-1904`（**门户批量审批**，`edu.leave` 批量） | 批量 `write({'state': …})` | 同上批量补写（`approver_kind` 同口径） |
  | 3 | `models/leave.py:104-116` `action_approve`（**后台按钮**） | :113 `targets.write({'state': 'approved'})` | 同上（后台按钮的 `approver_kind` 按当前用户组判定） |
  | 4 | `models/leave.py:117-125` `action_reject`（**后台驳回**） | :123 `targets.write({'state': 'refused'})` | 同上 |
  | 5 | `controllers/lms.py`（**课代表，新增**） | — | 新路由写 `approver_kind='student_rep'` |

  **绝不改状态机**（仍是 `request → approved/refused` 三态）；
  **绝不改既有审计动作名** `'请假审批'`（只有课代表用 `'请假审批(课代表)'`），
  以免打乱既有查询与统计（`roles.py:997-999`、`?:1890-1910` 附近的批量审计）。
- 模板文案**区分**（需求⑥逐字要求「不能混同」）：
  - `approver_kind='student_rep'` ⇒ 「**由课代表 X 审批**」
  - `approver_kind='faculty'` ⇒ 「由任课老师 X 审批」
  - 教务 / 管理员 ⇒ 「由教务 X 审批」
  - 空 ⇒ 「—」（既有历史单据）
- 审计日志**另加一条**，动作名**可区分**：课代表用 `'请假审批(课代表)'`；
  教师/教务**保持既有** `'请假审批'`（**不改既有动作名** ⇒ 不打乱既有查询与统计）。

---

## 7. 真机可验证的验收标准

> 全部在真机（门户 + 数据库）可复现；**负向用例 7 条**（校长要求 ≥3）。
> 「真机」= 生产/预发站点，`ssh prod-host`，DB 容器 `edu19-prod-db-1`。
> ⚠ **只读生产**：只允许 `SELECT`；**红线 = 不得查询 `edu_telegram` 与 `edu_feedback` 的数据**。

### 负向用例

| # | 用例 | 操作 | 期望 |
|---|---|---|---|
| **N1** | **非课代表拿不到** | 用一个**普通学生**账号（不是任何课的课代表，且**不是**该课学生）直接 GET `/my/courses/<subject_id>/rep` | HTTP **303 → /my/courses**（或 403），页面**不含**任何同学名单；手工 POST `…/rep/notify`、`…/rep/leave/set_state`、`…/rep/release` 三者**均不产生任何写库效果**（`edu_leave` 状态不变、`edu_message` 不新增） |
| **N2** | **课代表批不了自己** | 课代表本人给自己提交一张 `subject_id` = 他任课课程、`leave_type='sick'` 的请假；然后在课代表面板尝试通过 | 该单据**不出现**在课代表队列；直接 POST 越权 URL ⇒ **不写任何字段**（`state` 仍 `request`、`approver_kind` 仍空）；单据**仍**在教师 `/leave/approvals` 队列中可正常处理 |
| **N3** | **到期真的失效** | 把该课测试批次的 `op.batch.end_date` 改到昨天（**或用 `edu_portal.course_rep_grace_days=0` 且把 `end_date` 设为过去**） | ① 课代表面板 GET ⇒ 303/无权限；② 「我的课程」课程卡「课代表」徽标**消失**；③ **即使 cron 未跑**也已失效（实时判定）；④ 跑一次 cron 后库里 `state='expired'` 且 `edu_audit_log` 出现「课代表到期失效」 |
| **N4** | **只能批本课程** | 课代表 A 除任课课程 1 外**还是课程 2 的普通学生**；用课程 2 的请假单去 POST 课程 1 的审批 URL | **不写任何字段**；该单据不进课程 1 的队列 |
| **N5** | **批不了非出勤类** | 提交 `leave_type='legal'`（或 `'other'`）且 `subject_id` = 他任课课程的请假 | 课代表队列里**不出现**；POST 越权 URL ⇒ 不写字段 |
| **N6** | **每门课只能 1 个（数据库级）** | 为**同一 `subject_id`** 再插入第二行 `edu.course.rep`（后台或 SQL） | PostgreSQL 抛唯一约束冲突、**插入失败**；结构核对见下方只读 SQL（必须看到 `UNIQUE (subject_id)`） |
| **N7** | **归还后立刻失效、且不能转交** | 课代表点「辞去课代表」 | ① 立即拿不到任何课代表权限；② `state='vacant'`；③ **全仓 grep 不到任何「提名/指定/转交」路由或字段**（模型层就没有这个能力）；④ 教务任命下一人后**槽位仍只有 1 行**（`SELECT count(*) FROM edu_course_rep WHERE subject_id=<id>` = 1） |
| **N8** | **点名未确认 ⇒ 不影响考勤** | 课代表提交点名后，**老师不确认**，检查该班学生的考勤统计与 `/student/attendance` | 考勤统计**与提交前完全一致**（sheet 停在 `start`，未落定）；课代表**无法**自行把 `state` 改成 `done`（越权 POST 亦无效） |
| **N9** | **一个班一天只有一张点名表（不被课代表打破）** | 课代表提交该班当日点名后，老师再走 `/attendance/save` 录一次 | 命中既有 dup 分支（`?dup=1&dup_sheet=<id>`），**不产生第二张 sheet**；`SELECT count(*) FROM op_attendance_sheet WHERE attendance_date=<d>` 对应该班仍为 **1** |

### 正向用例

| # | 用例 | 期望 |
|---|---|---|
| P1 | 在任课代表打开 `/my/courses/<sid>/rep` | 显示本课程同学名单，字段**只有**姓名 + 班级；**不含**学号 / 邮箱 / 手机 / 成绩 |
| P2 | 课代表发通知 | 本课程同学的 `edu.message` 各新增 1 条、`event_key='course_rep_notice'`；课代表**自己收不到**；`/my/notify` 偏好页**能看到**该类开关（证明已登记 `NOTIFY_EVENTS`） |
| P3 | 课代表批一张**同学 B** 的本课程出勤类请假 | 单据 `state='approved'`、`approver_id`=课代表、`approver_kind='student_rep'`；**页面文案显示「由课代表 X 审批」**（逐字）；学生 B 收到 `leave_result` 站内信；`edu_audit_log` 有 `'请假审批(课代表)'` |
| P4 | 任课老师 / 教务 / 管理员各批一张 | **任一都能单独批**（OR 语义、不串行、不互相等待）；`approver_kind` 分别为 `faculty`/`registrar`/`admin`；文案**不显示**「课代表」 |
| P5 | 课代表点名（**待老师确认**） | 课代表点「提交点名」⇒ 生成的 `op.attendance.sheet` 停在 `state='start'`、`submitted_by_rep_id` 非空、`rep_subject_id` = 他的课、`rep_submitted_at` 非空；**未确认前**该班学生考勤统计**不变** |
| P5b | **老师能发现这张待确认表**（新增要求，见 §2.3） | 任课老师在 `/attendance/take` 选该班该日 ⇒ **页面上直接看到**「课代表已提交（X，时间），点击确认」；老师确认后 `state='done'`、考勤统计**才**变化；**同一班同一天始终只有 1 张 sheet** |
| P5c | 老师收到通知 | 课代表提交后，该课 `op.session.faculty_id` 对应的登录账号收到 `edu.message`，`event_key='attendance_rep_submitted'` |
| P5d | **教师侧零回归** | 不涉及课代表的普通点名流程（老师直接 `/attendance/take` → `/attendance/save`）行为**逐字不变**：仍按 `(course,batch)` 复用登记簿、仍按 `(course,batch,date)` 查重回跳 `?dup=1` |
| P6 | 作业提交统计 | 只显示「还有 N 人没交」（应交人数 − `op.assignment.sub.line` 已交人数）；**页面 HTML 里 grep 不到任何未交学生姓名**（0 命中） |
| P7 | 空值兜底 | 给 `op.student.course.batch_id` 为空的测试学生任命课代表 ⇒ `deadline_source='cap'`；`expires_at ≈ appointed_at + 180d`（**不是**空、**不是**永久） |
| P8 | 宽限期参数生效 | `edu_portal.course_rep_grace_days` 从 30 改 0 ⇒ 期限**立即**提前 30 天（实时判定，无需重算库存字段） |

### 只读验证命令（生产 `ssh prod-host` → 容器 `edu19-prod-db-1`，**仅 SELECT**）

```sql
-- N6：唯一约束真的在库里
SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
 WHERE conrelid = 'edu_course_rep'::regclass AND contype = 'u';
-- N7：每科目槽位数必须恒为 1（此查询应返回 0 行）
SELECT subject_id, count(*) FROM edu_course_rep GROUP BY subject_id HAVING count(*) > 1;
-- 口径核对：槽位状态分布
SELECT state, count(*) FROM edu_course_rep GROUP BY state;
-- P3/P4：审批人 + 身份必须成对出现（课代表审批必须 approver_kind='student_rep'）
SELECT id, state, approver_kind, approver_id, subject_id
  FROM edu_leave WHERE approver_kind IS NOT NULL ORDER BY id DESC LIMIT 20;
```

> ⚠ N3 若需改 `op.batch.end_date`，**必须用非生产的测试批次**；否则请改宽限期参数来验证。
> **不要在生产改结课日期。**

---

## 8. 需要校长拍板的用户可见项

> 以下都是**用户能看见 / 能点**的东西。按「只写文档不写代码」的要求，先请校长定文案与取舍。

| # | 待定项 | 建议方案 | 备选 / 说明 |
|---|---|---|---|
| 1 | **身份的中文名** | 「**课代表**」（校长原话） | 「课程代表」/「班级课程代表」 |
| 2 | 课程卡上的徽标文字 | 「**课代表**」（小徽章，仅**本人**在任时显示，「我的课程」页面上） | 「我是课代表」/「课代表 · 在任」 |
| 3 | 课代表面板标题 | 「**XX 课 · 课代表**」（XX = 科目名） | 「课代表工作台」 |
| 4 | 面板三个小标题 | 「本课程同学」/「给本课程同学发通知」/「本课程请假待批」 | 「同学名单」/「发通知」/「请假审批」 |
| 5 | 「归还」按钮措辞 | 「**辞去课代表**」（学生对「归还」不直观） | 「放弃课代表身份」 |
| 6 | 辞去二次确认文案 | 「辞去后你将**立即**失去本课程的课代表权限，且**不能指定**接任的人（需由教务重新任命）。确定吗？」 | 简版：「确定要辞去 XX 课的课代表吗？」 |
| 7 | 到期失效时学生看到的提示 | 「本课程的课代表身份已于 <日期> 到期失效。」 | 不提示（静默消失） |
| 8 | **「出勤类请假」包含哪些类型** | **`sick`（病假）+ `casual`（事假）**（默认参数值） | `legal`（法定假）算不算出勤类？`other`（其他）算不算？（**当前默认排除**） |
| 9 | 宽限期默认值（`course_rep_grace_days`） | **30 天**（校长拍板值） | 0 天 / 60 天 |
| 10 | 第③层兜底硬上限（`course_rep_max_days`） | **180 天** | 365 天；或「不设上限」——**不推荐**，会留下「无期限」风险，直接违背需求⑤ |
| 11 | 首页宫格要不要加「课代表」快入口卡 | **建议加**（仅当在任时渲染）——否则学生每次要绕「课程 → 我的课程 → 课程卡」三步 | **不加**（严格贴合需求⑦「塞入我的课程里」） |
| 12 | 发通知的收件范围 | **只允许「本课程同学」一个范围**，不给「全校」选项 | 加「本课程 + 任课老师」抄送 |
| 13 | 通知的字数上限与频率限制 | 建议 **500 字 + 每人每天 ≤ 5 条**（防滥用） | 不限 |
| 14 | 课代表能否看到「本课程作业未交**人数**」 | 需求⑧已定「统计、不给名单」⇒ 建议**给** | 只给点名，不给作业统计 |
| 15 | 后台列表给不给「历届课代表」列 | 建议**先不给**（槽位复用，历史在 `/edu/audit`） | 加只读任期流水表 + 历届名单列（触发 §1 收口条件） |
| 16 | 学生提交请假时「涉及课程」是否**必填** | 建议**选填**（不填 ⇒ 课代表无权批，走老师/教务；对既有流程零影响） | 必填（会强制改既有提交表单，影响所有学生） |

---

## 9. 未查到 / 不确定（**不得当结论用**）

### 9.1 仓内未完全确认

| # | 事项 | 已知 | 未确认（实现前必须补） |
|---|---|---|---|
| 1 | ~~`op.session` 是否必有 `subject_id`~~ | **已确认：`op.session.subject_id` 是 `required=True`**（`openeducat_erp/openeducat_timetable/models/timetable.py:47-48`），`faculty_id`(:42-44) / `batch_id`(:45-46) 同样 required | **已结案**：课代表的「课」与排课记录的「课」在同一套字段语义下（都是 `op.subject`），不会对不上 |
| 2 | ~~点名粒度冲突~~ **已裁定（队长，2026-09-19）** | 见 §2.3：**采用 (b+)** —— 点名仍落「一天一张整班点名表」、**教师侧零回归**；用本仓 `_inherit` 给 `op.attendance.sheet` 加自研字段（`rep_subject_id` / `submitted_by_rep_id` / `rep_submitted_at`）承载科目辨识度与提交人。**否决 (a)**（按科目另建 register 会与教师侧 `(course,batch)` 复用 + `(course,batch,date)` 查重**必撞**） | **已结案** |
| 2b | ~~课代表提交点名后老师怎么知道要确认~~ **已核实：老师看不见** | **已读完 `roles.py:380-476`**：教师 GET `/attendance/take` **不按日期查当日已有点名表**（:432-443 的 `Sheet.search` 只查「上一次」用于复制），渲染的是空白录入表单；唯一「重复」感知在 POST `/attendance/save`（:514-523）回跳 `?dup=1`。教师侧**无待确认列表**；模型层也无查重（`attendance_sheet.py:77-84` 只写序列号） | **已结案：确认老师看不见**。⇒ **必须补做**（详见 §2.3）：① `/attendance/take` GET 增加「当日已存在点名表」渲染 + 一键确认（复用既有 `dup`/`dup_sheet` 模板参数位，`roles.py:471-473`）；② 课代表提交后给任课老师发站内信（新事件 key `attendance_rep_submitted`）。**两条均为新增工作量，须单列排期** |
| 3 | 同一学生同课程**多班**时取哪个结课日 | `contacts.py:130` 注释明写「一个学生可能属多个班」 | **队长裁定（2026-09-19）：取「最晚」（不早退），接受为安全侧。** 本文按最晚设计；**仍未验证**是否符合校方语义（教务口径可后续再收） |
| 4 | ~~`edu.leave` 数据量与 `leave_type` 分布~~ **已查（生产只读 SELECT）** | **实测（2026-09-19，`ssh prod-host` → `edu19-prod-db-1` → `edu19`）**：`edu_leave` 共 **1 行**；`SELECT leave_type, count(*) FROM edu_leave GROUP BY 1` ⇒ **`sick` 1 行**（`legal`/`casual`/`other` **各 0 行**） | **已结案**：加 `subject_id`/`approver_id`/`approver_kind`/`approved_at` 四个可空字段的**回填影响面 ≈ 0**（1 行历史数据，全部新字段留空即可）。⚠ 但仍**未验证** `other` 在**真实使用后**会装什么 ⇒ §8-8 仍需校长拍板 |
| 5 | 课程卡模板的精确插入点 | 主模板 `edu_portal.edu_lms_courses`（`views/lms.xml:93`）已定位 | 具体 `xpath` 表达式与卡片 DOM 结构**未逐行读**，需实现时读 `views/lms.xml:93-135` 确认 |
| 6 | ~~`/my-courses`（A 页）与 `/my/courses`（B 页）的导流关系~~ | **已确认**：A 页课程卡上有「进入学习」链接 `href="/my/courses"`（`custom_addons/edu_public/views/edu_public_views.xml:545`），与 `edu_public/controllers/main.py:263-266` 的注释一致 | **已结案**：A → B 确有入口；**仍未实测**是否**每张**卡片都渲染该链接（模板条件未逐行读） |
| 7 | ~~点名「待老师确认」的既有教师入口细节~~ | **已读完 `roles.py:380-476` 全文** | **已结案**：教师侧**无**「待确认」列表 ⇒ 必须补做（见 §2.3 与 #2b） |
| 8 | 通知事件 key 是否影响既有偏好页渲染 | `NOTIFY_EVENTS`（`notify_pref.py:15-24`）驱动 `/my/notify`；`edu.message` 生产表 **12 列** | 新 key 是否需在别处同步登记，**未逐一核对**（需 grep `NOTIFY_EVENTS` 的全部消费点） |
| 9 | 生产数据规模（影响测试与验收设计） | **实测**：`op_student` 20 / `res_users` 29 / `op_batch` 19 / `op_subject` 147 / `op_session` 216 / `op_attendance_sheet` **0** / `edu_message` 5 / `op_student_course` **1** | ⚠ **生产环境数据量很小**（`op_student_course` 仅 1 行）⇒ 大范围验收（多班、多课程）在**生产上做不出来**，需在预发/本地造数据。另 `op_attendance_sheet` = 0 行 ⇒ **点名相关验收必须在非生产先造数据** |
| 10 | 生产库是否已存在 `edu_course_rep` | **实测**：`information_schema.tables` 查 `edu_course_rep` = **0** | **已结案**：生产库也确认无同名表 ⇒ 建表无冲突 |

### 9.2 外部调研未验证项

> 见 `docs/research/course-representative.md` 的「未验证 / 待确认」章节（两份文档同源，此处不重复）。

### 9.3 明确的**负结论**（可以作为结论使用的部分）

1. 本仓**零**「课代表 / 班代表 / 学生干部 / 助教实体」既有实现（§0 查重：5 组关键词，实测 0 命中；
   `助教` 的 8 处全是评教类型或文案）。
2. `edu_life` **没有** `edu.leave`（`grep -rn 'leave' custom_addons/edu_life/` = **0 命中**）；
   学生请假模型**全仓唯一**在 `custom_addons/edu_portal/models/leave.py:47`。
3. `edu_home_timeline` 里的「我的课程」区块**无路由引用**（`views/study.xml:253-255` 注释自证）
   ⇒ 课代表入口**不能**做在那里。
4. `op.batch.end_date` 与 `op.academic.term.term_end_date` **都是 `required=True`**
   （`batch.py:34`、`op_academic_term.py:21`）⇒ 「日期字段为空」的**现实路径只有
   「行不存在」或「外键链接为空」**，不是字段本身为空。
   这**改变了「空值」的语义**，必须写清（§4.3 表格已逐条覆盖）。
5. `models.Constraint` **无法表达部分唯一索引**（PostgreSQL `ADD CONSTRAINT … UNIQUE` 不支持 `WHERE`）
   ⇒ 「每门课 1 个」必须靠**槽位复用（`UNIQUE(subject_id)`）**，
   而不是「每任期一行 + 状态过滤」。
6. 既有请假审批**不记审批人**（`edu.leave` 无 `approver*` 字段，`roles.py:992` 只写 `state`）
   ⇒ 需求⑥「显示由课代表 X 审批」**必须**新增字段，只靠 `edu.audit.log` 达不到。
7. **Odoo 19 里 `_sql_constraints` 已废**（被框架静默忽略），唯一约束必须用 `models.Constraint`；
   本仓 4 处旧写法（`edu_telegram/models/flow.py:15`、`binding_code.py:22`、`telegram_chat.py:20`、
   `edu_portal/models/alert_read.py:29`）**不得照抄**。
