# 评估系统重建设计（形态甲：评分项存数据行 + 矩阵渲染 + xlsx 往返）
> **状态**：`在研` ｜ **主题**：`评估系统重建` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> **任务**：校长交办「删掉现有两套评估、重建一套」；队长已钉死形态 = **甲**（评分项**存成数据行**、界面**渲染成矩阵表**）、**D（xlsx 往返）为必须项**、**删除顺序 = 先建新的 → 验证可用 → 再删旧的（删前先备份）**。
> **上游依据**：`docs/research/evaluation-rebuild.md`（620 行，2026-09-18，本次调研，本文最重要的输入）；`docs/dev-workflow.md` 第 0 步 + 六步闸门；`docs/code-map.md`（全文）；`docs/audit/feature-overlap-audit.md`、`docs/audit/deprecated-inventory.md`、`docs/audit/security-audit-app.md`。
> **证据环境**：仓库工作区 + **生产只读**（`ssh prod-host` → 容器 `edu19-prod-db-1`，只跑 SELECT，**未触碰匿名意见箱 `edu_telegram` / `edu_feedback` 的任何数据**）。
> ⚠ **本轮本地栈未运行**（`docker compose ps` → `Cannot connect to the Docker daemon`，2026-09-18 实测）⇒ **本文所有"本地读数"均引自他人文档并已标注，未复核**；本文**未跑任何真机验证**，§9 是**待执行的验收标准**，不是已通过的结论。
> **合规**：本文只写文档、不写一行代码；`custom_addons/`、`openeducat_erp/` 一行未改；`openeducat_erp/` 源码只给路径 + 行号，不贴码；生产只读。
> 行号漂移：本文 `custom_addons/**` 与 `docs/**` 行号取自 2026-09-18 工作区快照；上游 Odoo 行号一律转引 `docs/research/evaluation-rebuild.md` 并注明其取证日期。

---

## 0. 结论速览

| 问题 | 结论 |
|---|---|
| 载体裁定 | **新建独立模块 `edu_assess`（模型前缀 `edu.assess.*`），过渡期与旧两套并存**；旧的 `edu.eval.*`（A 套）与 `edu.admin.eval.*`（B 套）**冻结 → 303 兼容 → 最后删除**。理由与收口触发条件见 §3 |
| 是否有第三处评估实现 | **没有**。全仓 `*.py/*.xml/*.csv/*.js` 与**生产 `ir_model` 实读**均只有 **7 个**评测模型 = A 套 4 + B 套 3；相邻的「考勤/成绩/测验/周记评阅/福利积分」5 类**都不是评估**（逐条否证见 §2.3） |
| 数据模型 | 五层：**模板 `edu.assess.template` → 评分项（= 一列）`edu.assess.item` → 任务 `edu.assess.task` → 名单快照 `edu.assess.roster`（= 一行）→ 单元格 `edu.assess.score`**。矩阵 = 「行 = roster、列 = item」的动态渲染，**列不是模型字段** ⇒ 加一个评分项 = 插一行数据 |
| 在线增删评分项 | **自定义行表（`edu.assess.item`），不用内核 Properties（jsonb）**。**推翻**调研 §7.1 的 Properties 推荐：Properties 是"每记录一份键值"、做不了 FK/唯一约束，且**会使 D（xlsx 导题）直接死掉**（`base_import` 只能映射既有字段、不能新建字段）。五条依据见 §5 |
| xlsx 往返 | **自研两段式（导出宽表 → Excel 填 → 导回预览 → 提交）**，**照抄仓内既有先例** `/grading/import`（`roles.py:2044-2115` 预览 / `:2117+` 提交）与 `_read_table_file`（`roles.py:19-47`，openpyxl 读，生产容器实测 3.1.2）。幂等键 = **任务（导出时锁定）+ 学号 `gr_no`（优先）/姓名 + 评分项名**；冲突三态见 §6。⚠ **发现的硬事实：教务组没有 `base.group_allow_export`** ⇒ Odoo 原生「导出」按钮对教务**不出现**（生产实测闭包），所以自研导出不是锦上添花、是**必须** |
| 旧两套处置 | A 套：**不写迁移脚本**（默认方案 A，代价 ≈ 0.5 人日）——生产实读 4 模板 / 13 评分项 / 1 任务 / **0 条打分**，"迁移"实质只有 4+13 行**定义**，0 行业务数据 ⇒ 改为"导出留档 + 教务在新引擎重建"；校长若要保留定义则转方案 B（≈1 人日 + 真机验证）。B 套：**0/0/0 ⇒ 可 uninstall**，但有 **7 条前置条件**（§7.3），其中**最硬的一条是 `edu_nav` 的 4 条 `edu_eval.menu_*` 必须先摘掉并重新生成菜单数据**，否则装载期守卫报漂移 ERROR |
| 删除顺序 | ① 建 `edu_assess` → ② 三侧入口 + xlsx 往返真机验收（§9）→ ③ 旧路由 303、旧菜单停用 → ④ **备份（pg_dump + xlsx 导出，落盘留路径）** → ⑤ uninstall `edu_eval` / 删 A 套表（走 `migrations/`）。**不许先删后建** |
| 菜单不新增第 3 个评估入口 | 新引擎**接管 588「综合评估」这个容器根**（改名「评估」），**不新建第 3 个评估根菜单** —— 否则 backoffice 可见根 12→13，破 `docs/code-map.md:199` 的 ≤12 验收线 |
| 校长拍板项 | 8 项，见 §11（含**现文案「评教完全匿名」与实现不符**这一条，属用户可见的合规问题） |
| 未验证项 | 12 条，见 §12（本轮本地栈未运行、生产未做门户越权实测、openpyxl 写入未在 Odoo 请求周期里实跑…） |

---

## 1. 本设计**作废** `docs/plans/eval-merge-design.md`

`docs/plans/eval-merge-design.md`（t4，2026-09-17）的结论是「**留 A 套 `edu.eval.*`、B 套冻结退役并入 A**」（该文档 `:15-24` §0：留 A 套 / B 冻结退役 / 零迁移 / 新增 `edu.eval.campaign` + 9 个增量字段 / `type_code` 3→6 值）。

**本设计作废它，原因两条**：

1. **前提被校长推翻**：它的立论是「A 套有存量（本地 3 模板 / 1 任务 / 5 打分）⇒ 保留 A 最便宜」。校长已确认「**学生表现分**」不是他在用的；**生产实读 A 套打分 = 0 条**（§2.5）⇒「保留 A 更便宜」这个前提不成立了。
2. **目标不同**：它要「合成一套、留一个入口」；校长要「**两套都删、重建一套，形态 = 评分项存数据行 + 矩阵 + xlsx 往返**」。它的 6 口径 `type_code`、匿名 HMAC 令牌、`/eval/*` 303 到 `/my/evaluation` 等结论，全部是为"合并"服务的，**与"重建"无关**。

> **给下一个人的硬约束**：不要照 `eval-merge-design.md` 实施。**照它做会得到第三套评估实现**（`edu.eval.*` 留在 `edu_portal` 里 + 新增 `edu.eval.campaign`），正是 `docs/dev-workflow.md` 第 0 步要防的事。
> 建议动作（**属队长/文档侧，不在本设计内**）：给该文档加一行醒目作废声明，或按台账体例登记为"已作废的前提"（`docs/research/evaluation-rebuild.md:45` 已先例登记过一次）。

---

## 2. 第 0 步：落地前查重（`docs/dev-workflow.md:6-81`）

### 2.1 查了什么 / 用什么方式 / 命中什么

| # | 查什么 | 命令（原样可复跑） | 命中 |
|---|---|---|---|
| ① | code-map 全文（§4 模块地图 + §5 路由速查 + §6 约定） | `read docs/code-map.md`（384 行全读） | 评估现状 = `code-map.md:97-101`（edu_eval 冻结退役）/ `:226`（评估路由现状）/ `:291`（eval-merge-design 索引）；权限四层硬约定 `:256-263` |
| ② | A 套模型前缀 | `grep -rn "edu\\.eval" --include=*.py --include=*.xml --include=*.csv custom_addons/` | `models/evaluation.py:20/47/66/123`；`security/ir.model.access.csv:58-65`；`views/evaluation.xml:6-98`；`controllers/evaluation.py:34,69,81,89,96,100,112,135,138,166,204`；`controllers/batch2.py:629-630` |
| ③ | B 套模型前缀 | `grep -rn "edu\\.admin\\.eval" …` | `edu_eval/models/admin_eval.py:25/70/95`；`edu_eval/security/ir.model.access.csv:2-10`；`edu_eval/security/security.xml`；`edu_eval/controllers/eval_portal.py:43,86,112,…,297`；`edu_portal/controllers/batch2.py:1812-1816`（KPI 回退） |
| ④ | 门户路由（两个名字都搜） | `grep -rn "http.route" custom_addons/edu_portal/controllers/evaluation.py custom_addons/edu_eval/controllers/eval_portal.py` | A：`/my/evaluation`、`/my/evaluation/new`、`/my/evaluation/create`、`/my/evaluation/task/<id>`、`…/save`、`/my/evaluation/results`、`/my/evaluation/results.csv`；B：`/eval/fill/<id>`、`/eval/fill/<id>/save`、`/eval/my`、`/eval/review`、`/eval/review/<id>`、`/eval/review/<id>/submit` |
| ⑤ | 后台菜单与动作 | `grep -n "menuitem\|res_model" custom_addons/edu_portal/views/evaluation.xml custom_addons/edu_eval/views/eval_views.xml` | A：root `综合评估`(588) → `模板管理`(589) / `评估任务`(590)；B：root `行政评估`(597) → `评估模板`(598) / `打分记录`(599) / `结果分析`(600) |
| ⑥ | 中文同义词 | `grep -rn "评估\|评教\|评价" --include=*.py --include=*.xml custom_addons/` | 命中清单见 §2.2；**无第三方评估引擎** |
| ⑦ | 有没有第三处实现（模型/表） | **生产库只读**：`select model from ir_model where model like '%eval%'` / `information_schema.tables like '%eval%'` | **恰好 7 个**：`edu.eval.{template,template.line,task,score}` + `edu.admin.eval.{template,item,score}`（表同名）；**无第 8 个** |
| ⑧ | 有没有第三处实现（可装模块） | **生产库只读**：`select name,state from ir_module_module where name in ('survey','spreadsheet','spreadsheet_dashboard','web_grid','hr_appraisal','web_studio','base_import')` | `survey=uninstalled`；`spreadsheet`/`spreadsheet_dashboard`/`base_import`/`mail`=`installed`；`web_grid`/`hr_appraisal`/`web_studio`=`uninstallable`（**代码不在镜像里**，企业版）⇒ 生产是**纯社区版**，与调研 §2.0 结论一致 |
| ⑨ | 前端资产里的评估逻辑 | `grep -rn "eval\|评分\|评估" --include=*.js custom_addons/` | 只有 `edu_eval/static/src/js/eval_portal.js`（3 处，`:7` `.eval-score-input` 渐进增强）；**无隐藏的第三方矩阵引擎** |
| ⑩ | 生成物里的评估入口 | `grep -rn "行政评估\|综合评估" scripts/` | `scripts/gen_manual.py:158-176`（生成 `docs/manuals/永约教务系统操作手册.docx` 的 **3.5 行政评估** 与 **3.6 综合评估** 两节）；`scripts/gen_icons.py:150`（行政评估菜单图标）；`scripts/check_prod_menus.py:244`（升级清单含 `edu_eval`） |
| ⑪ | 台账已登记的评估条目 | `grep -n "评估\|eval" docs/audit/deprecated-inventory.md` | `:126` `CM-597`；`:184` B2；`:185` B3；`:205` C-05；`:11` 引用了已作废的 `eval-merge-design.md`。**四栏（保留原因/替代路径/何时可删/删除前置条件）当时填的是"先实施 eval-merge-design"⇒ 本设计落地后这四栏全部要重写** |

### 2.2 现两套的全部入口（第 0 步要求的"全入口清单"）

**A 套 —— 综合评估（`edu_portal` 内，模型名 `edu.eval.*`）**

| 类别 | 事实 | 路径:行号 |
|---|---|---|
| 模型 | `edu.eval.template`；字段 `name/type_code`(3 值：freshman/student/intern)`/total/pass_line/excellent_line/visible_to_student/line_ids` | `custom_addons/edu_portal/models/evaluation.py:20-43` |
| 模型 | `edu.eval.template.line`；`template_id/name/max_score/sequence`（**= 一列评分项**） | 同上 `:47-62` |
| 模型 | `edu.eval.task`；`template_id/student_id/evaluator_type`(teacher/self/ta/pastor)`/period/state`(draft/scoring/done)`/score_ids/total_score/grade/approved_by` | 同上 `:66-119` |
| 模型 | `edu.eval.score`；`task_id/template_line_id/score` + `UNIQUE(task_id, template_line_id)` + 0≤score≤max 约束 | 同上 `:123-145` |
| 后台 | 根 588 `综合评估`（`groups=` 空 ⇒ 本地按 `edu_portal.views/evaluation.xml:90-98`）→ 589 `模板管理` / 590 `评估任务` | `views/evaluation.xml:78-98` |
| 门户 | `/my/evaluation`（中心）、`/new`、`/create`(POST)、`/task/<id>`、`/task/<id>/save`(POST)、`/results`、`/results.csv` | `controllers/evaluation.py:31,61,75,107,129,154,200` |
| 卡片/门禁 | `_is_staff()` = **`base.group_user`**（任何内部用户）；KPI 卡「评估待打分」→ `href=/my/evaluation` | `controllers/evaluation.py:24-25`；`controllers/batch2.py:629-638` |
| 权限 | ACL **只有 `base.group_user`(`1,1,1,0`) 与 `base.group_system`(`1,1,1,1`)** ⇒ **没有门户 ACL**（所以也没有 ir.rule）；控制器一律 `sudo()` | `security/ir.model.access.csv:58-65`；生产实测同构（§2.5） |
| 种子 | `scripts/seed_eval_demo.py`（`edu.eval.template` 演示模板） | `scripts/seed_eval_demo.py:3` |

**B 套 —— 行政评估（`edu_eval` 模块，模型名 `edu.admin.eval.*`）**

| 类别 | 事实 | 路径:行号 |
|---|---|---|
| 模型 | `edu.admin.eval.template`（`name/type_code/period/due_date/state`(draft/open/closed)`/item_ids`） | `custom_addons/edu_eval/models/admin_eval.py:25-66` |
| 模型 | `edu.admin.eval.item`；`label/max_score/weight`(权重倍率)`/sequence` | 同上 `:70-91` |
| 模型 | `edu.admin.eval.score`；`task_id/student_id/teacher_id/item_id/score/note/scorer_id`；**`scorer_id` `required=True`** | 同上 `:95-116` |
| ⚠ 隐患 | `UNIQUE(task_id,item_id,student_id,scorer_id)`：评教行的 `student_id` 为 **NULL** ⇒ **Postgres 里 NULL≠NULL，该唯一约束对评教行形同虚设**（同一人对同一教师同一项可插多条） | 同上 `:120-122`（对照 `:124-130` 的"被评对象二选一"约束，可见评教行 `student_id` 必为 NULL） |
| 后台 | 根 597 `行政评估` → 598 `评估模板` / 599 `打分记录` / 600 `结果分析` | `views/eval_views.xml:167-196` |
| 门户 | `/eval/fill/<task_id>`、`/eval/fill/<id>/save`、`/eval/my`、`/eval/review`、`/eval/review/<id>`、`/eval/review/<id>/submit` | `controllers/eval_portal.py:81,106,160,194,259,284` |
| 门户能力 | **整班矩阵打分页**：行 = 学生（按 `op.batch` 分组）、列 = 评分项、单元格 `name="score_<sid>_<iid>"`、逐项 `max_score` 夹取、`weight` 加权总分 | `controllers/eval_portal.py:40-104`（组装）、`:106-156`（落库 upsert） |
| 门禁 | `_is_staff()` = **`base.group_user`**，且**不校验任教班级** ⇒ 任何内部用户可给**全校**学生打分 | 同上 `:23-24`、`:84-88`、`:108-119` |
| 权限 | ACL 含 `base.group_portal`：template/item 只读；**score 为 `1,1,1,0`（读+写+建）**；另有两条 ir.rule（门户可读/可写"自己提交的评教"） | `edu_eval/security/ir.model.access.csv:2-10`；`edu_eval/security/security.xml`（`rule_edu_admin_eval_score_portal_read/write`） |
| 前端资产 | `eval_portal.js`（矩阵输入框渐进增强：`.eval-score-input`）、`eval_portal.css` | `edu_eval/__manifest__.py:25-29`；`static/src/js/eval_portal.js:7,42` |
| 用户可见文案 | 学生帮助页：「评教完全匿名，提交后不可再修改」；卡片：「对教师与助教的匿名评教」；教务帮助：「打开后台『行政评估』应用 → 评估模板」（**该入口在本地已被 597 停用**） | `edu_portal/views/help_center.xml:96-100`、`:242-245`；`edu_portal/controllers/batch2.py:302-305` |
| ⚠ 文案与实现不符 | 评教**并不匿名**：`scorer_id` **模型层 required**（`admin_eval.py:111-114`），控制器显式写 `scorer_id=uid`（`eval_portal.py:332`）；而且门户 ACL 给了 `1,1,1,0` + ir.rule 允许学生**读/改自己提交的行** ⇒ 与「提交后不可再修改」也不符。**这是用户可见的承诺失实，必须进拍板清单（§11-2）** | 三处证据如上 |
| 收口状态 | 本地：597 已停用、598/599/600 迁 588、`/eval/*` **仍 200 未重定向**；**生产：`edu_nav` 未安装 ⇒ 597 仍 active、598/599/600 仍挂 597**（§2.5） | `custom_addons/edu_nav/data/menu_consolidation_data.xml:2978-3012`；生产实测见 §2.5 |

### 2.3 有没有第三处评估实现？—— **没有**（逐条否证）

**正面结论**：候选前缀全仓 0 命中 —— `edu.assess` / `edu.asmt` / `edu.scorecard` / `edu.rating` / `edu_appraisal` / `edu_assess` 各 **0 条**（命令：`for p in …; grep -rn "$p" --include=*.py --include=*.xml --include=*.csv --include=*.js custom_addons/ docs/`），且**生产 `ir_model` 里 `%eval%` 恰好 7 个模型、`information_schema.tables` 恰好 7 张表**（§2.1 ⑦）。

**"看起来像但不是"的 5 类，逐条否证**（避免下一个人把它们当第三套）：

| 候选 | 是什么 | 为什么不是"评估引擎" |
|---|---|---|
| `edu_quiz`（EduQuiz/Attempt） | 在线测验：出题 → 作答 → 自动判分 | **判断题对错**，没有"评分项/维度/权重/被评对象"（调研 §2.1.3 已证 Odoo 计分口径 = 判对错） |
| `op.result.line` / `op.exam.attendees`（成绩册） | 考试成绩：`/grading/entry`、`/grading/export`、`/grading/import` | 一行 = 一个学生的**一个分数**，没有评分项维度；且绑定 `op.exam` |
| `/attendance/take`（整班点名） | 考勤：行 = 学生、单元格 = 出勤状态 | 形态像矩阵，但语义是出勤枚举、无评分项（`roles.py:347,445`） |
| `edu_life` 周记评阅 `/journals/review` | 教师给周记写评语 | 一条记录一段评语，无多维度评分项 |
| `edu_point.log`（福利积分） | 加分/扣分流水 | 流水账不是评估表（无模板、无评分项） |

**搜索范围的边界（`dev-workflow.md:29-30` 要求写清）**：本次只搜了 `custom_addons/`、`scripts/`、`docs/` 与各 `*.md/`；**未搜**：`openeducat_erp/` 全量（只在 `ir_model` 层确认无 `%eval%` 模型）、前端编译产物与 `reference/`|`scrape/` 只读素材目录、生产 `ir_ui_menu` 的**全量**名称模糊匹配（只精确查了 7 个已知 id 与 `parent_id=588`）。

### 2.4 台账/审计里已登记的评估条目（要跟着本次修订的）

| 位置 | 现内容 | 本设计落地后须改成 |
|---|---|---|
| `deprecated-inventory.md:126` `CM-597` | 597 行政评估 → 588 综合评估 | 保留（生产尚未生效，见 §2.5） |
| `deprecated-inventory.md:184` **B2** | B2/B3 "先实施 eval-merge-design；当前不得删" | **作废该前置条件**，改为本设计 §7.3 的 7 条 |
| `deprecated-inventory.md:185` **B3** | 同上（item/score 同批处置） | 同上 |
| `deprecated-inventory.md:205` **C-05** | `/eval/*` 5 条仍 200 未重定向 | 保留，改造时按本设计 §7 改为 303 并更新"何时可删" |
| `deprecated-inventory.md:11` | 引用 `eval-merge-design.md`（**未实施**） | 改为引用本文件 |
| `feature-overlap-audit.md:25-26/59-67/143-145/185-186/220` | 评估两套的四层证据；待决问题"评估引擎留哪套" | 答案已改：**两套都不留，重建** |
| `security-audit-app.md:401` | `edu.eval.task` 无门户 ACL ⇒ RPC 被 ACL 拦 | 新引擎若要给门户 ACL，必须同批写 ir.rule（§8.3） |
| `docs/plans/eval-merge-design.md` 全文 | "留 A 并入 B" | **作废**（§1） |

### 2.5 读数复核（我实测，2026-09-18，生产只读）

**A 套 / B 套数据（`edu19-prod-db-1`，只读 SELECT）**

| 表 | 条数 | 备注（明细我逐行读过） |
|---|---|---|
| `edu_eval_template` | **4** | 1 `学生综合评估记分表【演示】`(5 项) / 2 `实习同工评估表【演示】`(4 项) / 3 `新生综合测评表【演示】`(3 项) / 4 **`学生表现分`**(1 项) |
| `edu_eval_template_line` | **13** | 5+4+3+1；第 13 行 = `迟到`（模板 4，`max=9`） |
| `edu_eval_task` | **1** | id 2 / 模板 4 / `student_id=11` / `state=scoring` / `create_date=2026-09-17 06:38:42` |
| `edu_eval_score` | **0** | —— |
| `edu_admin_eval_template` / `_item` / `_score` | **0 / 0 / 0** | 与该模块从未被使用一致 |

⇒ **队长转述的读数（4/13/1/0 与 0/0/0）我逐条复核一致**；并由此确认校长那句「学生表现分不是我用的」在本库是**可证的**：它只剩"1 个模板 + 1 个评分项 + 1 个空壳任务 + 0 条打分"。

**菜单实况（只读）—— 本地与生产**不一致**（重要）**

| id | 生产 `name/active/parent` | 本地（据 `edu_nav` data 与 code-map） |
|---|---|---|
| 588 综合评估 | **active / 无父 / groups=角色·用户** | 同 |
| 589 模板管理 / 590 评估任务 | active / `parent=588` | 同 |
| 597 行政评估 | **active（仍在！）/ 无父 / groups=角色·用户** | **已停用**（`menu_consolidation_data.xml:2979-2985`） |
| 598/599/600 | **`parent=597`（未迁！）** | 已迁 `parent=588`（`:2987-3012`） |

**根因（实测）**：`select name,state from ir_module_module where name='edu_nav'` → **生产根本没有 `edu_nav` 模块**（生产已装清单：`edu_apply/edu_brand/edu_eval/edu_life/edu_portal/edu_public/edu_quiz/edu_schedule/edu_telegram/edu_tg_bind/edu_zh`，**无 `edu_nav`**）。
⇒ **`docs/code-map.md:97-101`「597 已停用、子树已迁入 588」是本地事实，不是生产事实**。删除顺序与验收必须按生产实际（597 仍活）来排；`code-map` §4.1 早已要求"引用菜单读数必须带采集时刻"，本条一并回填。

**权限实况（只读，递归闭包）**：`backoffice@local`(uid 12) 与 `jiaowu@local`(uid 18) 的 `base.group_allow_export` = **false**（`admin`/`__system__` = true）；教务组成员组 = `角色/用户(1) + 经理(40) + 后台·完整视图(87)`；`openeducat_core.group_op_back_office_admin`(id 40) 的 implied 已**不含 `base.group_system`(id 4)**（`views/group_tuning.xml` 生效）。
⇒ **教务点不出 Odoo 原生「导出」**（`web/static/src/views/list/export_all/export_all.js:34-38` 要求 `base.group_allow_export`）⇒ 调研 §2.7「D 是白送的」**只对管理员成立**，对**教务**不成立 —— 这是本设计与调研的第一处重要分歧，落点见 §6.4。

**容器能力实测**：`edu19-prod-web-1` 里 `python3 -c "import openpyxl"` → **3.1.2**；`base_import` 在镜像内；`web/controllers/export.py` 存在。
⇒ `openpyxl` 读写 xlsx 在生产**可用**（但**未在 Odoo 请求周期里实跑过**，见 §12）。

### 2.6 第 0 步 ④：升级会不会写业务表？

- **新模块 `edu_assess`（本设计）**：`data/` 只放**配置类**（视图/菜单/ACL/动作/系统参数默认值）；**演示数据一律走 `demo/` 键 + 【演示】标记**；**禁止**把任何写 `edu.assess.score` / `roster` 的 `<function>` 放进 `data/`（`docs/dev-workflow.md:33-46` 反面实例 = `edu_life/data/demo_life.xml` 的 `_load_demo_records`，实测每次 `-u` 跨日补 9 行）。
- **既有两套（现状，供对照）**：A 套种子在**脚本** `scripts/seed_eval_demo.py`（不在 `data/`，**`-u edu_portal` 不会重放**）—— 这是**正确**做法，新模块照抄这个位置。B 套 `edu_eval` 无 `data/` 目录（`ls custom_addons/edu_eval/` 实测无 `data`），manifest `data` 只有 4 个配置文件。
  ⇒ **两套旧实现都不存在"升级写业务表"问题**；本次不动它们的数据。
- ⚠ 同族风险（**这次必须避开**）：`menu_consolidation_data.xml` 是 `data` 且**每次 `-u edu_nav` 重放**，它按目标菜单自己的 xmlid 覆盖 `active/parent_id` —— 新引擎一旦接管 588，**这套重放机制就是"菜单收口会不会被 `-u edu_portal` 打回"的关键**（F1 未关闭，见 §3.5）。

### 2.7 第 0 步 ⑤：演示数据策略（一句话）

**演示数据只进 `edu_assess/demo/`（`<odoo>` 里显式带**【演示】**前缀的模板名），并通过 `scripts/seed_assess_demo.py` 幂等 get-or-create 供给本地演示；生产**不装**任何评估演示数据**（参照现状：生产 A 套那 3 条带【演示】的模板是历史遗留，本次随旧套一起退场）。

### 2.8 三选一裁定

| 裁定 | 内容 | 理由 |
|---|---|---|
| **新建（并存）** | 新建 `edu_assess` + `edu.assess.*`；旧两套冻结为"只读化石"直到删除 | 校长钉死的顺序要求**过渡期两套并存** ⇒ 必须有第三组不冲突的名字；且需求形态（评分项 = 数据行 + 矩阵 + xlsx 往返）在旧两套的数据模型上都改不出来（A 套无"评分项名称可编辑的列"之外的自由参数、B 套评分项名叫 `label` 且 `scorer_id` required 锁死匿名可能） |

**为什么不复用 A 套 `edu.eval.*`**：① 名字被占 ⇒ 过渡期无法并存；② A 套 `edu.eval.score` 的唯一键是 `(task_id, template_line_id)`（`evaluation.py:135-137`）⇒ **一个任务里每个评分项只能有一条分**，无法表达"多个打分人对同一个被评者各打一份"（教师评/自评/TA评/牧者评今天靠"一个任务只用一种 `evaluator_type`"绕过，见 `evaluation.py:75-78`）；③ A 套模型在 `edu_portal` 里，删表要写 `migrations/`，回滚成本高于卸载一个模块。

**为什么不复用 B 套 `edu.admin.eval.*`**：① B 套 `scorer_id` 模型层 `required=True`（`admin_eval.py:111-114`）⇒ **结构上排除了匿名评教**，而校长要"参数丰富"、帮助页今天正承诺匿名；② B 套把"模板"和"任务"合成一张表（`edu.admin.eval.template` 同时是模板与实例，`period/due_date/state` 全在同一行）⇒ 无法支持"一个模板发布多次评估"（校长要的"像 Excel 那样自由"，多次复用是基本盘）；③ 唯一约束对评教行失效（§2.2 隐患行）。

**收口触发条件（出现任一即回第 0 步查重、并考虑合并载体）**：

| 编号 | 触发条件 | 判据 |
|---|---|---|
| **T1** | 全仓出现**第三组**评估模型前缀（除 `edu.eval.*`、`edu.admin.eval.*`、`edu.assess.*`） | `grep -rn "class Edu.*Eval\|_name = 'edu\..*eval" --include=*.py custom_addons/` 的前缀集合 > 3 |
| **T2** | 出现**第二个**"给学生/教师打分"的门户写库入口（今天唯一 = `edu.assess.score` 的控制器） | `grep -rn "score_" --include=*.py custom_addons/edu_portal/controllers/` 出现新命名族 |
| **T3** | 校长要求"评估结果进成绩册"（`op.result.line`） | 那时评估不再是独立域 ⇒ 须重走第 0 步（很可能应挂 `openeducat_exam` 而非新模块） |
| **T4** | `edu.assess` 落地 6 个月后**仍 0 条打分** | 与旧两套同样的死法 ⇒ 说明需求口径未落地，停手复盘而不是继续加参数 |

---

## 3. 载体裁定（问题 2）

### 3.1 结论

> **新建模块 `edu_assess`（模型前缀 `edu.assess.*`，5 个模型，见 §4），依赖 `edu_portal`；门户外壳/身份判据/通知/审计全部复用 `edu_portal` 既有件；旧两套命名空间一个也不复用。**

### 3.2 论证（每条带可核证据）

1. **过渡期并存是校长钉死的** ⇒ 模型名不能撞：生产 `ir_model` 实读 `edu.eval.*`(4) + `edu.admin.eval.*`(3) 全占用（§2.5）。
2. **`edu_portal` 是门户中枢且不可卸载**（`docs/code-map.md:50`：最大模块 ~1.5 万行；manifest 19.0.2.0.0）：把新引擎塞进去 = 给唯一中枢再加一个功能域，**且失去"整体回滚 = 停用/卸载一个模块"的能力**；新模块可 `bash scripts/safe_upgrade.sh edu_assess` 单独冒烟、可整体停菜单回滚。
3. **依赖方向有现成先例**：`edu_eval → edu_portal`（`docs/code-map.md:132`）已经证明"评估引擎独立成模块、借 `edu_portal` 拿 `edu_page` 外壳与 `current_student()/current_faculty()` 判据"这条路走得通 —— 新模块同构，只是这次**不再叫 eval**。
4. **删除成本**：卸载模块 = Odoo 自动 drop 表；A 套在 `edu_portal` 内部则必须写 `migrations/<版本>/`（先例 `docs/code-map.md:68`）才能删表 —— 更贵、更易错。
5. **命名不冲突（已查）**：`edu.assess`/`edu_assess`/`edu.asmt`/`edu.scorecard`/`edu.rating` 全仓 **0 命中**（§2.3 命令）。
6. **不复用 `/my/evaluation*` 路由**：该地址今天的语义是"教师建任务 + 整表打分 + 雷达图"（`controllers/evaluation.py:2-7` 头注释自陈），与"三侧入口（学生填/教师审/教务建）"不是一回事；且一旦复用，**回滚就只剩"回代码"一条路**（旧实现与新实现共用一个 URL，无法用"旧地址还在不在"判断新引擎是否接管）。旧地址一律 **303** 保留书签（§7.4）。

### 3.3 被引用面（先 grep 后裁定）

`grep -rn "/eval/\|/my/evaluation" --include=*.py --include=*.xml --include=*.js custom_addons/`（排除 `edu_eval/` 自身）命中 **21 处**，可归为 4 类，**全部要跟着改**（分派见 §7.5）：

| 类 | 命中 | 处置 |
|---|---|---|
| A 套实现自身的 URL | `controllers/evaluation.py` 7 条路由 + `views/evaluation.xml:117,152,157,190,203,277` | 随 A 套退场：路由 303、视图停用 |
| 门户卡片/KPI | `controllers/batch2.py:302,304,305,638`（"我的评分"/"评教填答"/"评估待打分"三张卡） | 改指向新路由 |
| 帮助与手册 | `views/help_center.xml:96-100`、`:242-245`；`views/edu_portal_templates.xml:529`；`scripts/gen_manual.py:158-176`（生成 `docs/manuals/永约教务系统操作手册.docx` 的 **3.5/3.6 两节**） | 改文案 + 重新生成手册（**两节合成一节**） |
| 菜单/图标/部署脚本 | `edu_nav/data/menu_consolidation_data.xml:2978-3012`；`scripts/gen_icons.py:150`；`scripts/check_prod_menus.py:244`；`scripts/portal_token_map.py:33`（`edu_eval/static/…css` 色令牌） | 菜单数据重新生成；图标与色令牌随新模块重建（**不要留 `edu_eval` 的 CSS 引用指向已卸模块**） |

### 3.4 模块骨架（照本仓"新功能三件套"约定，`docs/code-map.md:249`）

```
custom_addons/edu_assess/
├── __manifest__.py            # depends: ['edu_portal']  （→ website/openeducat_core 传递）
├── models/assess.py           # 5 个模型
├── controllers/portal.py      # 三侧门户 + xlsx 往返（四段：# 门户矩阵 # 我的 # 教师审阅 # 教务导入导出）
├── views/assess_views.xml     # 后台 4 个列表/表单 + 动作（菜单挂 588，见 §3.5）
├── views/assess_portal.xml    # 门户模板（t-call="edu_portal.edu_page"）
├── security/ir.model.access.csv
├── security/security.xml      # ir.rule（口径见 §8.3）
├── demo/assess_demo.xml       # 【演示】模板（本地用）
└── static/src/js/assess_grid.js  # 矩阵录入渐进增强（抄 edu_eval/static/src/js/eval_portal.js 的手感）
```
`scripts/seed_assess_demo.py`（幂等 get-or-create）为本地演示入口；**不进 `data/`**（§2.6）。

### 3.5 菜单裁定：**接管 588，不新建第 3 个评估根**

- 事实：`588 综合评估` 是本仓评估的唯一容器根（`edu_nav` 的施工图把 597 也并到它下面，`feature-overlap-audit.md:185-186`）；`backoffice` 可见根 **12 条正好压线**（`docs/code-map.md:199`，验收线 ≤12）。
- ⇒ **新引擎不再新建评估根菜单**：由 `edu_assess` 在 588 下挂 4 条子菜单（模板与评分项 / 评估任务 / 打分记录 / 结果与导出），588 的 `name`（综合评估 → **评估**）与 `groups`（角色·用户 → **教务组 + 系统组**，按四层模型 `code-map.md:258`）**由 `edu_nav` 的 plan 承载**（`docs/code-map.md:110`：菜单收口唯一落地处；**不要**写在 `edu_assess` 自己的 XML 里，否则重演 F1「`-u` 把收口值打回」`docs/audit/finding-F1-menu-replay-on-upgrade.md`）。
- ⇒ 589/590（A 套子菜单）停用；597/598/599/600（B 套）在生产**先停用**再随模块卸载消失。
- 验收口径：**教务可见的评估根 = 1 个（588）**，`backoffice` 可见根 **≤12 不破线**（§9 V10）。

---

## 4. 数据模型三层 → 五层（问题 3）

### 4.1 模型

| 模型 | 一句话 | 关键字段（★ = 校长的"参数丰富"落点） |
|---|---|---|
| `edu.assess.template` | 评估表定义（可复用、可多期发布） | `name`、★`kind`(Selection：评教 / 学生综合 / 行政考评 / 实习…由教务自己维护的字典)、★`target_kind`(student/faculty)、★`total`、★`pass_line`/`excellent_line`、★`score_visible`(被评者能否看结果)、★`allow_self`(是否允许自评)、`state`(draft/active/archived)、`item_ids`、`notes`、`active` |
| `edu.assess.item` | **一个评分项 = 未来的一列** | `template_id`(cascade)、★`name`、★`max_score`、★`weight`(默认 1.0)、★`required`(必填项)、★`score_kind`(number/level，二期)、`sequence`、★`help`(给打分人看的提示)、`active`；**唯一约束 `UNIQUE(template_id, name)`**（同时是 xlsx 导题的幂等键，§6.3） |
| `edu.assess.task` | 一次评估 = 模板 × 周期 × 参与对象 | `template_id`、`period`(如 `2026秋`)、`date_begin`/`date_due`、`state`(draft/open/closed)、★`scope_batch_ids`/`scope_program_ids`(参与对象范围)、★`scorer_kind`(学生评教师 / 教师评学生 / 自评 / 互评)、★`anonymous`(匿名口径，§8.4)、★`summary_min`(匿名汇总门槛 N 份)、`roster_ids`、`score_count`/`progress`(compute) |
| `edu.assess.roster` | **一行 = 一个被评者**（发布任务时的**名单快照**） | `task_id`、`student_id`/`faculty_id`(二选一，照 B 套 `admin_eval.py:124-130` 的校验形态)、`state`(pending/done)、`total`(compute)、**`UNIQUE(task_id, student_id, faculty_id)`** |
| `edu.assess.score` | **一个格 = 一条记录** | `task_id`、`item_id`、`roster_id`、★`value`(Float)、★`note`(评语)、`scorer_id`(实名口径才写)、**`scorer_ref`(Char，非空)**；**`UNIQUE(task_id, item_id, roster_id, scorer_ref)`** |

### 4.2 为什么"名单快照"这一层是必须的（不是过度设计）

1. **行的集合必须稳定**：本仓刚吃过"换班/换课程导致名单漂移"的账（调班设计 `docs/plans/class-change-request-design.md` §11 明写"换班后该生将从原班点名表/评教名单移除"）。若"行"靠实时查 `op.student.course`，则一次调班会让**历史评估的行凭空少人**，历史总分与完成率一起漂。
2. **xlsx 空表要有确定名单**：导出空表 = 导 `roster`；导回时"文件里多出来的人/缺的人"才有确定判据（缺人 = 提示、多人 = 报错）。
3. **匿名汇总门槛要有分母**：`匿名 + summary_min` 需要"应评份数"（= roster × scorer 数），没有快照算不出来。

### 4.3 "行=被评者、列=评分项"的矩阵怎么渲染（三个面，同一份数据）

| 面 | 实现 | 为什么这样 |
|---|---|---|
| **门户矩阵页**（教师整班打分 / 学生填评教） | 服务端渲染 `<table>`：`<thead>` = `template.item_ids.sorted('sequence')` 循环出列；`<tbody>` 行 = `task.roster_ids`；单元格 `<input name="v_<roster_id>_<item_id>">` | **本仓已有同构先例**：B 套 `/eval/fill/<task_id>`（`edu_eval/controllers/eval_portal.py:40-156`，行=学生、列=item、`score_<sid>_<iid>`）+ 教师端 `/attendance/take`（行=学生）；抄形态、不抄代码（模块要卸） |
| **后台列表** | `edu.assess.score` 列表视图 `editable="bottom"` + `multi_edit="1"` + 按 `roster` 分组 | Odoo 原生（`addons/web`，社区版）：格内直改、多行批量同值、可选列、列宽拖拽；研究 §2.5.3 已说明其局限：视觉上是"每个学生一个小块"，不是一张连续大表 |
| **xlsx 宽表** | 导出：行 = roster，列 = item（表头 = 评分项名）；导入：同结构 | 校长要的"真的做成 Excel"（§6） |

**三者共用一份定义**：列集合 = `template.item_ids`，行集合 = `task.roster_ids`，两者都是**数据**。

### 4.4 为什么这样就能满足"像 Excel 一样自由加列"（必须讲清的口径）

- **列不是模型字段**：不新增 `ir.model.fields`、不改数据库 schema、不发版、不重启。加一个评分项 = 在 `edu.assess.item` **插一行**（后台内联列表点"添加一行"，`editable="bottom"` 已经在本仓的 A/B 两套里用过：`views/evaluation.xml:43`、`edu_eval/views/eval_views.xml:82`）。
- **"当场生效"的机制**：三个面都**在请求时**读 `item_ids` 渲染 ⇒ 保存后刷新即出现新列；无需任何缓存失效逻辑。
- **反面对照（为什么不走"列=数据库字段"）**：那样每加一项要发版/写模块（研究 §2.5.2：`base_import` **不能**新建字段；Studio 是企业版 `web_studio=uninstallable`，生产实测）。
- **边界要说清（不许夸大）**：这不等于"自由单元格 Excel"——不能合并单元格、不能插空白行、不能写任意公式（研究 §2.5.3 五条 + 国内无一家做成"自由单元格"§5.2）。**我们能给的是"列可自由增删 + 整表 xlsx 往返"**，这两件是校长原话里"参数丰富 + 像 Excel + 修改方便"的**可交付交集**。

---

## 5. 在线增删评分项：Properties 还是行表？（问题 4）—— **裁定：行表，推翻调研推荐**

> 调研 §7.1 与 §0.3 推荐「B 用 `Properties` + 评分项行表解决」。**本设计推翻 Properties 那一半**，理由是它在**本需求的三条硬约束**下都站不住：

| # | 依据 | 为什么决定性 |
|---|---|---|
| 1 | `Properties` 的语义是"每条记录一份键值字典"，不是"全表共享的一列"（`odoo/orm/fields_properties.py:32-51` docstring 原文："pseudo-fields … **without being independently stored in database**"；定义挂在容器记录上） | 矩阵要求"**一列 = 一个评分项，对所有被评者同一列**"；Properties 的键是**每条记录自己的**，无法保证"人人同一列"，也无法表达"模板级排序/满分/必填" |
| 2 | 评分记录必须 **FK 到评分项**（A 套既有形态 `evaluation.py:129-131` `template_line_id`；唯一约束 `:135-137`） | jsonb 子键**做不了外键、做不了唯一约束**；要"同一任务同一项同一人唯一"只能靠应用层判重（并发下不可靠 —— 本仓 `edu_tg_bind` 已实测这个坑：`docs/code-map.md:121` "唯一约束 + 整事务回滚重试"） |
| 3 | **D 会直接死掉**：xlsx 导题（把 20 个评分项一次导进去）只能走 `base_import`；而 `base_import` 的字段映射**只能从既有模型字段里挑，不能新建字段**（研究 §2.5.2；官方文档"Field missing to map column"给唯一解法是切"advanced"看**已有**字段） | jsonb 子键**不在可选字段列表里** ⇒ 用 Properties 就必须自研导题解析器，与"能装不写、能抄不造"相悖；而 **D 是校长钉死的必须项** |
| 4 | 后台按评分项分组/排序/统计（`read_group` by item、按 item 出平均分） | 行表 = ORM 原生；jsonb 要表达式索引 + SQL |
| 5 | "加列零成本"这个卖点行表同样有 | 行的 INSERT 就是零 schema 变更；Properties 省下的只是"建一次表"，而模板/评分项**本来就该是实体**（要有名称唯一、排序、满分、权重、说明、停用） |

**保留 Properties 的合理落点（不是否定它）**：把 `Properties` 用在**被评对象档案**上的"自定义附加属性"（per-record 键值，如"该生本学期特殊约定"）——那是它设计要解决的问题。**一期不做，二期再议**（写进 §10）。

---

## 6. xlsx 往返（问题 5）

### 6.1 三段路由（全部在 `edu_assess`，全部门户/后台内，`csrf=True`）

| 路由 | 作用 | 权限层 |
|---|---|---|
| `/assess/template/<id>/blank.xlsx` | **导出空表**：第 1 行表头 = `学号`、`姓名` + 每个 active 评分项一列；第 2 行起 = 该模板**占位名单**（空表模式：只表头 + 说明行）/ 或指定任务的 roster | 教务组 |
| `/assess/task/<id>/export.xlsx` | **导出结果**：行 = roster，列 = 评分项 + `总分` + `等级`；被评者姓名/学号 | 教务组（教师可导自己班的，见 §8.2） |
| `/assess/task/<id>/import` → `…/import/commit` | **导回两段式**：上传 → 预览（valid/invalid 两表 + 旧值→新值）→ 提交 | 教务组（教师可导自己班的） |

### 6.2 字段映射（导出什么列）

| 列 | 来源 | 导入时 |
|---|---|---|
| `学号` | `op.student.gr_no`（`roles.py:2030` 已有先例用它做键） | **首选幂等键**；空则退姓名 |
| `姓名` | `op.student.name` | 兜底键；**同名多人必须报错**（`roles.py:2071-2073` 的 `by_name.setdefault` 会静默取第一个 ⇒ 新引擎要改成"重名即 invalid"） |
| 每个评分项一列 | `edu.assess.item.name`（按 `sequence`） | 表头 `trim` 后**精确匹配** `item.name` |
| `总分` / `等级` | 计算列（导出时写公式或静态值） | **不读**（导入时忽略，防篡改；总分一律服务端算） |
| `评语`（可选，二期） | `score.note` | 命中 `_note` 后缀列 |

**为什么不用 External ID 当键**：外部 ID 是 `base_import` 的口径（"I want to update data (import-compatible export)"），面向管理员与技术用户；**教务/教师面对的是 Excel，列头是"评分项名称"、行首是学号**。外部 ID 路径**仍保留**（下面 §6.4）但**不是主路径**。

### 6.3 幂等（最关键的一问）

**幂等键 = `task_id`（导入页锁定，不接受文件里改） + 被评者（学号优先 / 姓名兜底） + 评分项名**，落到 `UNIQUE(task_id, item_id, roster_id, scorer_ref)` 的 **upsert**。

- 同一文件导两次 ⇒ **不翻倍**（第二次全部命中同一唯一键 ⇒ UPDATE 同值）。V4 断言这个。
- **评分项重命名会破坏"按名称"的幂等** ⇒ 三期口径写清：① 未知列头**默认报错不新建**（防错别字变成新列）；② 教务勾选「**按新列创建评分项**」才新建（这是"导题"路径，抄希沃"批量导入点评项目"研究 §5.1）；③ 可选增强（默认关）：导出时列头写成 `评分项名 #<item_id>`，导入时优先按 `#id` 匹配、再退名称 —— **重命名也不会错位**。
- **并发/重复提交**：不靠审计日志做闸门（本仓教训：`docs/plans/class-change-request-design.md:265` —— 审计日志**无唯一约束**，双击会建两条）⇒ 靠数据库唯一约束 + `savepoint` 逐条；重复提交结果相同（幂等），不会翻倍。

### 6.4 冲突策略（三态，与 `/grading/import` 同构）

| 单元格/行状态 | 处置 | 预览页显示 |
|---|---|---|
| **空** | **跳过**（**不清空**库里已有的分） | 「跳过（空值）」 |
| **非法**：非数字 / 负数 / 超 `item.max_score` / 找不到被评者 / 表头未知评分项 / 同一文件里学号重复 | **整行不写**（不做半行写入） | `invalid` 表 + 逐条原因（照 `roles.py:2081-2105` 的 `errors` 列表形态） |
| **合法** | 写（upsert），预览显示 **旧值 → 新值**；提交后写 `edu.audit.log`（`action='评估导入'`，含 task / 文件名 / 条数 / 操作人） | `valid` 表 |

**权限真相（本轮新发现，必须写进设计）**：教务组**没有** `base.group_allow_export`（生产闭包实测 false，§2.5）⇒ Odoo 原生「导出」对教务**不出现**，所以**自研导出是必须项、不是加分项**。
两条路对比：

| 路径 | 教务能用吗 | 代价 | 裁定 |
|---|---|---|---|
| 原生 `base_import` + `/web/export/xlsx` | **导入能**（视图不写 `create="false"` 即出现），**导出不能** | 0 | **保留为管理员第二条路**（后台列表视图不写 `create="false"` ⇒ 白送的 Import/Export 与外部 ID 幂等对管理员仍可用）；**不作为教务主路径** |
| 自研两段式（本设计） | 能 | 抄 `/grading/import` 先例（`roles.py:19-58` 解析 + `:2044-2115` 预览 + `:2117+` 提交） | **主路径** |

> ⚠ 另一条**不做**的方案：给教务组加 `base.group_allow_export`。那是**全局导出权**（能导出他们能读的**任何**模型的**任何**行，含学生档案/账单），与"最小权限"相悖 ⇒ **不建议**，若校长坚持要走 §11 拍板。

---

## 7. 旧两套的处置（问题 6）

### 7.1 删除顺序（校长钉死，逐条可核）

```
① 建 edu_assess（新引擎，与旧两套并存，三者互不干扰）
② 三侧入口 + xlsx 往返真机验收通过（§9 V1–V10）
③ 旧路由 303 + 旧菜单停用（本地与生产都要做；生产今天 597 仍活，见 §2.5）
④ 备份：pg_dump -t edu_eval_* / edu_admin_eval_* + 4 个模板的 xlsx 导出，落盘并在台账登记路径
⑤ 删除：uninstall edu_eval（B 套）/ migrations 删 A 套表（A 套在 edu_portal 里）
```
**不许先删后建**；每步独立 commit、可独立回滚。

### 7.2 A 套（`edu.eval.*`）：迁移代价算账 → **默认不迁**

**生产实读**（§2.5）：4 模板 / 13 评分项 / **1 任务** / **0 条打分**。逐行看过模板构成：

| 模板 | 评分项 | 判断 |
|---|---|---|
| 1 `学生综合评估记分表【演示】` | 5（出勤与纪律/课堂参与/灵修生活/学业表现/服事态度，各 20） | 演示件 |
| 2 `实习同工评估表【演示】` | 4（事奉忠心/团队配搭/属灵榜样/专业能力，各 25） | 演示件 |
| 3 `新生综合测评表【演示】` | 3（基础信仰笔试 40/面试表现 30/写作测试 30） | 演示件 |
| 4 `学生表现分` | 1（`迟到`，`max=9`） | **校长已确认"不是我在用的"**；其 task 是空壳（0 打分） |

⇒ **"迁移"的实质 = 迁 4 行模板 + 13 行评分项的"定义"，0 行业务数据。**

| 方案 | 做什么 | 代价 | 触发条件 |
|---|---|---|---|
| **A（推荐，默认）** | **不写脚本**：把 4 个模板定义**导出留档**（后台 xlsx 导出或只读 SELECT 存档），教务在新引擎里**按需重建**（"学生表现分"1 个模板 1 分钟；三条【演示】若非演示用途就不建） | **≈0.5 人日**（导出 + 留档 + 重建 1 个模板 + 截图） | 默认 |
| B | 一次性 `scripts/migrate_eval_to_assess.py`：读 `edu.eval.template/.template.line` → `create edu.assess.template/item`（映射 `name→name`、`type_code→kind`、`line.name→item.name`、`max_score→item.max_score`、`sequence→sequence`）；`task` 按学生是否存在决定迁不迁；**score 0 行无需迁** | **≈1 人日** + 1 次真机验证（断言 `edu_assess_item` 行数 = 13） | **仅当校长书面说"要保留那 4 个模板的定义"**；且**必须在 A 套模型改只读之前**跑 |

### 7.3 B 套（`edu_eval`）：**可以 uninstall**，但有 7 条前置条件

| # | 前置条件 | 依据 |
|---|---|---|
| 1 | 新引擎三侧 + xlsx 往返真机验收通过（§9） | 校长钉死的顺序 |
| 2 | B 套 **0/0/0**（已复核，§2.5）⇒ 零数据损失 | 生产实测 |
| 3 | `/eval/*` **6 条**路由改 303 → 新地址；断言用 `allow_redirects=False` + `Location` **精确匹配** | `docs/dev-workflow.md:129-146` 陷阱 2；台账 C5 口径 |
| 4 | **`edu_nav` 的 4 条 `edu_eval.menu_*` 必须先摘掉并重新生成**：`edu_nav/data/menu_consolidation_data.xml:2979/2987/2996/3005` 用 `edu_eval.menu_edu_admin_eval_*` 做记录键；模块卸载后这些 xmlid 消失 ⇒ `forcecreate="0"` 那几条只能跳过（加载器告警），且 `edu_nav` 装载期守卫会因 `edu_nav.consolidated_count` 与实际状态漂移**报 ERROR**（`edu_nav/models/menu_consolidation.py:54-71` 的漂移反查；`MENU_CONSOLIDATED_COUNT=357`）。**正确动作 = 从 `docs/audit/menu-consolidation/menu-consolidation-plan.json` 摘掉 4 条 → 重跑 `scripts/gen_menu_data.py` → 同步守卫常量** | `edu_nav` 文件实读 |
| 5 | 4 处**用户可见引用**先改：`views/help_center.xml:96-100`（`/eval/review` 链接 + 匿名文案）、`:242-245`（后台"行政评估"路径）、`controllers/batch2.py:302/304-305`（两张卡）、`scripts/gen_manual.py:158-176`（手册 3.5 节） | §3.3 引用面 |
| 6 | `scripts/check_prod_menus.py:244` 的升级模块清单去掉 `edu_eval`；`scripts/gen_icons.py:150`、`scripts/portal_token_map.py:33` 的 `edu_eval` 引用一并处置 | §3.3 |
| 7 | **备份落盘 + 校长书面确认**（卸载会 drop 三张表；本仓"零删除红线"下这是硬前置） | `docs/audit/deprecated-inventory.md` §3 体例 |

> **另一条可选路径（更保守）**：只做 1–5（菜单停用 + 路由 303 + 文案改），**保留模块不卸载**，等 30 天无报障再卸。代价 = 库里留 3 张空表；收益 = 回滚只需改回菜单开关。**推荐先走保守路径**（§10 分期）。

### 7.4 A 套模型自身的处置（在 `edu_portal` 内，不能卸模块）

1. 菜单停用：`views/evaluation.xml:90-98` 的 588/589/590 —— 588 由新引擎接管（§3.5），589/590 `active=False`（**写进 `edu_nav` 的 plan，不写在本文件**，避 F1 重放）。

   > ✅ **2026-10-03 已做，但落点与本条原本的建议不同 —— 这里更正一下，免得下一个人去 `edu_nav` 里找**：
   > 实现在 **`edu_portal/models/menu_labels.py` 的 `RETIRE_MENUS`**（第 50 轮就有的 noupdate-规范化 + ORM 停用机制），
   > **不是** `edu_nav` 的 plan。理由是先把「F1 重放」这个担心**实测掉**了：
   > `grep -rn "menu_edu_eval_task\|menu_edu_eval_template" custom_addons/edu_nav/` ⇒ **0 命中**
   > ⇒ `edu_nav` 的合并计划根本不引用这两个 xmlid，**重放碰不到它们** ⇒ 那条担心对本条不适用。
   > 且做了**升级存活实测**：连跑 `safe_upgrade.sh edu_nav` 与 `safe_upgrade.sh edu_portal` 后复查，
   > 两个菜单仍然 `active=False`（`edu_apply_menu_retirements()` 每次升级都幂等重申，反而比一次性写 plan 更稳）。
   > 效果：后台「综合评估」下拉由 **6 项（含两个同名「评估任务」）** 变为 **4 项无重名**。
2. 路由 303：`/my/evaluation*` 7 条 → 新引擎对应页（`/my/evaluation` → 学生 `/assess/my` 或教师 `/assess`，按身份分流）。

   > ✅ **2026-10-03 实测**：代码里 7 条路由**一律** 303 到 `/assess`（`controllers/eval_compat.py:24-54`），
   > 而本条原本写的是「学生 `/assess/my` / 教师 `/assess`，按身份分流」—— **分流其实由 `/assess` 自己完成**，
   > 所以实现与设计**不冲突**：以 `stu@local` 打 `/my/evaluation` ⇒ 303 → `/assess` → 200，落地页是学生版
   > （「我的评估 / 查看自己收到的评估」）；以 `faculty@local` 同路 ⇒ 落地页是教师版（「整班打分 / 有 3 个进行中的评估」）。
   > ⇒ **无需**为旧路由另写按身份分流的重定向。
3. 保留期：表与模型**留 30 天**（只读化石：无写入口、无读入口），期间 `edu.eval.*` 的 ACL 不动。
4. 删除：走 `custom_addons/edu_portal/migrations/19.0.3.0.0/` 删 4 张表（先例 `docs/code-map.md:68` 的费用分类迁移）；**同时**清 `security/ir.model.access.csv:58-65` 与 `controllers/batch2.py:1810-1816` 的 `edu.eval.*` 回退分支（避免"删了表还留引用"）。

### 7.5 一处**必须写清的先后关系**

新引擎接管 588 ⇒ 588 的 `name`/`groups` 要改；而 588 的 xmlid 属于 `edu_portal`。**改法有两条**：
- **（推荐）** 全部改动写进 `edu_nav` 的 plan（`menu-consolidation-plan.json` → 重新生成 data），因为 `edu_nav` 是菜单收口的唯一落地处（`code-map.md:110`）；代价 = 要跑生成器。
- （不推荐）在 `edu_assess` 里 `<record id="edu_portal.menu_edu_eval_root">` 覆盖 —— 这会让"收口值"散落在业务模块里，重演 F1（`docs/audit/finding-F1-menu-replay-on-upgrade.md`，**未关闭**）。

---

## 8. 三侧入口与权限（问题 7）

### 8.1 三侧入口清单

| 侧 | 入口 | 层（`code-map.md:256-261`） | 机制 |
|---|---|---|---|
| **学生填评教** | `/assess/fill/<task_id>`、`/assess/fill/<task_id>/save`、`/assess/my`（我的评估结果） | **L4 门户** `base.group_portal` | 门户路由 + `current_student()` 判空分流；**读全部走 `sudo()` + 控制器内显式域收敛** |
| **教师整班打分 / 审阅** | `/assess/grade/<task_id>`、`/assess/grade/<task_id>/save`、`/assess/review`（审阅队列，可选） | **L3 教师** `openeducat_core.group_op_faculty`，**且只限自己任教班级** | `current_faculty()` + 任教班收敛（复用 `roles.py` 已有口径：`_teacher_exam()` 式收敛，见 `roles.py:2019-2022` 注释"导出同样收敛到本人任教范围"） |
| **教务建模板 / 看结果 / 导出入** | 后台 588 子树（模板与评分项 / 评估任务 / 打分记录 / 结果与导出）+ 门户管理页（可选） | **L2 教务** `group_op_back_office_admin` **并列** `base.group_system` | 菜单 `groups="openeducat_core.group_op_back_office_admin,base.group_system"`；ACL 给教务组 `1,1,1,1`、系统组 `1,1,1,1`；**不给 `base.group_user`**（现状 588 是"角色/用户"= 任何内部用户可见，本次收紧） |

### 8.2 三条现状缺陷（重建时必须修掉，逐条带证据）

| # | 缺陷 | 证据 | 新引擎怎么做 |
|---|---|---|---|
| 1 | **任何内部用户可给全校学生打分**：A/B 两套的 `_is_staff()` 都只判 `base.group_user` | `edu_portal/controllers/evaluation.py:24-25`；`edu_eval/controllers/eval_portal.py:23-24`、`:84-88`（`/eval/fill` 只判 staff，学生列表来自全库 `op.student.search([])`） | 教师侧加**任教班收敛**；不给"任意内部用户"打分权 |
| 2 | **评教"匿名"是假的**：`scorer_id` 模型层 required + 控制器显式写入；且门户 ACL/ir.rule 让学生能**读/改自己提交的行**，与"提交后不可再修改"冲突 | `edu_eval/models/admin_eval.py:111-114`；`edu_eval/controllers/eval_portal.py:332`；`edu_eval/security/ir.model.access.csv:9`(`score` 门户 `1,1,1,0`)；`edu_eval/security/security.xml`（读写两条规则）；文案 `edu_portal/views/help_center.xml:100` | 匿名口径由校长拍板（§11-2）；**实现与文案必须一致**（要么实现匿名、要么改文案） |
| 3 | **唯一约束对评教行失效**：`UNIQUE(task_id,item_id,student_id,scorer_id)` 里 `student_id` 为 NULL（评教行）⇒ Postgres NULL≠NULL | `edu_eval/models/admin_eval.py:120-130` | 新引擎用 **`roster_id`（非空）+ `scorer_ref`（非空 Char）** 做唯一键（§4.1），**不用可空外键做唯一键** |

### 8.3 权限落地的硬口径（吸收 2026-09-18 安全审计/加固的教训）

- **教训原文（可核）**：`docs/audit/security-audit-app.md:416-460` F1（**严重**）——「门户账号拿到了整表读权限却没有行过滤，一个 RPC 请求即可读走全校数据」（`POST /web/dataset/call_kw/<model>/search_read`）；修复 = `custom_addons/edu_portal/security/security.xml`（补 ir.rule）+ commit `e7243e0`（"补 edu.* 行级权限并止血越权"）。审计 §F1 修复建议第 2 条即："把门户专用模型 ACL 收成 `1,0,0,0` 甚至 `0,0,0,0`，门户一律经控制器 `sudo()` 取数 —— 这是本仓既有约定"。
- **本设计的裁定**：`edu.assess.*` 的 `security/ir.model.access.csv` **不给 `base.group_portal` 任何权限（`0,0,0,0`）**，门户读写一律经控制器 `sudo()` + 显式域收敛。理由：① 与审计建议一致；② `sudo()` 会绕过 `ir.rule`（本仓 `docs/plans/invite-code-tiers-design.md:202` 已写明这个陷阱），所以"给门户 ACL + 写 ir.rule"在门户代码全走 sudo 的现实下**规则形同虚设**，反而给人"已经防住了"的错觉。
- **代价与对等要求（必须同批写进代码注释）**：`0,0,0,0` 把风险从"RPC 直读"挪到"控制器漏判"⇒ 控制器必须：① 每个写路由 `csrf=True` + `auth='user'`；② 先判身份（`current_student()/current_faculty()` 判空 → 直接 303 回首页，不 fallthrough）；③ 查询域按身份收敛（非本人得空集）；④ 越权探测要有负面断言（§9 V8）。
- **无门户 ACL 的对照证据**：A 套今天正是 `0` 门户 ACL —— 生产实测 `edu.eval.task` 无门户 ACL，审计 `:401` 记「拒绝访问（ACL 拦截）」，`:728` 记 `/eval/review` 对学生是"无数据泄漏"。⇒ 本口径**在本仓已被验证过**。
- **教师侧数据隔离**：教师"只限自己任教班"若靠控制器写死，将来任何新入口都可能漏 ⇒ 建议**同时**给 `op.student`/`op.faculty` 相关的**新模型**（`edu.assess.roster`）配**教师组的 ir.rule**（`('batch_id','in', 任教班)` 式域），作为纵深防御（与 §8.3 门户口径不冲突：`sudo()` 只用在门户侧，教师侧控制器**不用 sudo**，让 ir.rule 真正生效）。

### 8.4 匿名口径（校长拍板项，三选一）

| 口径 | 落库 | 能否防重复提交 | 风险 |
|---|---|---|---|
| ① 实名 | `scorer_id` 必填（= 现状 B 套） | 能 | 与"匿名评教"文案冲突；学生不敢真评 |
| ② 完全不留痕 | 什么都不存 | **不能**（同一人可刷 N 份） | 汇总结果可被刷票污染 |
| ③ **HMAC 指纹（推荐）** | `scorer_ref = 'h:' \|\| HMAC(盐, task_id + user_id)`，**不存 `scorer_id`** | 能（唯一键含指纹） | ⚠ **可被穷举**：盐在 `ir.config_parameter` 里、`user_id` 空间小 ⇒ **不是密码学匿名**，只是"后台界面看不到是谁"。必须配 `summary_min`（少于 N 份不出报表）。**此风险须书面告知校长** |

（口径 ③ 的思路来自 `docs/plans/eval-merge-design.md` §4.6 —— 那份设计的**载体结论作废**，但这条机制本身可用。）

---

## 9. 真机可验证的验收标准（问题 8）

> 全部待执行。**核心命题 = 证明"加一个评分项不改代码、不升级就能生效"**（V1）。
> 判据纪律：`docs/dev-workflow.md:129-146`（升级 EXIT=0 不算通过；改路由必须有"打完就摸页面"的断言；**不许跟随重定向**）。

| 编号 | 场景 | 断言（必须同时读页面 + 读库） |
|---|---|---|
| **V1** ⭐ | 教务后台 → 评估 → 588 下"模板与评分项" → 打开某模板 → 评分项内联列表**点「添加一行」**填 `课堂笔记 / 满分 10 / 权重 1` → 保存。**全程不跑 `safe_upgrade.sh`、不重启容器、不改一行代码** | ① 门户矩阵页刷新后**表头出现「课堂笔记」列**（HTML 断言：`<th>` 文本命中）；② 学生/教师填入 8 并提交后，`select count(*), max(value) from edu_assess_score where item_id=<新项>` → **1 行 / 8**；③ 断言脚本在**保存前后各跑一次**，只有第 2 次出现新列（证明"当场生效"而非"本来就该有"） |
| **V2** | 删除该评分项 | ① 无打分时：删得掉，门户列消失；② **有打分时：拒绝删除并提示改用「停用」**（照 `edu_portal/models/fees.py:128-138`、`models/downloads.py:44-55` 的"有引用拒删 + 引导停用"先例）；③ 停用后列消失、历史分仍在（只读可见） |
| **V3** | `/assess/template/<id>/blank.xlsx` | ① `file` 命令 / `openpyxl.load_workbook` 能打开（**真 xlsx，不是 CSV 改后缀**）；② 表头 = `学号/姓名` + 全部 active 评分项（逐个命中）；③ 行数 = roster 数 |
| **V4** ⭐ | 用 Excel 填 3 学生 × 2 项 → `/assess/task/<id>/import` → 预览 → 提交 | ① 预览 `valid=3, invalid=0`；② 提交后库里 **6 行**；③ **同一文件再导一次 ⇒ 仍是 6 行**（幂等）；④ 第二次预览显示"旧值 = 新值" |
| **V5** | 冲突三态 | 一格填 999（超满分）、一格留空 → 预览 `invalid=1` + "跳过 1"；提交后**超满分那格库里仍是旧值**、留空格未被清空 |
| **V6** | 未知列头 | 默认：**报错不新建**（断言 `edu_assess_item` 行数不变）；勾选「按新列创建评分项」后：模板新增 1 项（断言行数 +1，名称 = 列头） |
| **V7** | 正面权限 | `stu@local` 打开 `/assess/my` **只见自己**；`faculty@local` 打开 `/assess/grade/<task>` **只见自己任教班**（对照 `op.session` 的任教班名单） |
| **V8** ⭐ | **负面权限（RPC 直读，审计 F1 同款判据）** | 以 `stu@local` 会话 `POST /web/dataset/call_kw/edu.assess.score/search_read` → **拒绝访问**（门户 ACL = 0）；以 `parent@local` 同样断言；以 `faculty@local` 直读 → 只返回自己任教班（ir.rule 生效） |
| **V9** | 旧地址不 404 | `/eval/my`、`/eval/review`、`/eval/fill/<id>`、`/my/evaluation` 全部 **`allow_redirects=False` 得 303 + `Location` 精确匹配**（**不跟随**；`dev-workflow.md:138-146`） |
| **V10** | 菜单唯一 + 不破线 | `load_menus`（口径 B，`code-map.md:263`）下：教务可见评估根**只有 1 个**（588）；597/589/590 不可见；**backoffice 可见根 ≤12**（`code-map.md:199` 验收线） |
| **V11** | 删除前备份 | `pg_dump -t edu_eval_*`、`-t edu_admin_eval_*` 与 4 个模板 xlsx **都已落盘**，路径写进台账 |
| **V12** | 升级不动业务数据 | `-u edu_assess` 前后 `edu_assess_score` 行数**不变**（陷阱 1 同族：演示数据不得放 `data/`）；`-u edu_nav` 后 V10 的读数**仍成立**（F1 未关闭 ⇒ 必须每次升级后复验） |

**判据强度说明（避免假绿，照 `dev-workflow.md` 判据强度五兄弟）**：
- V1 必须"**页面文本命中 + 库内行数**"两条，**不接受**"保存成功"提示或"升级 EXIT=0"。
- V4 的幂等必须**真跑两次**（同一文件），只跑一次会得到"看起来对"的假绿。
- V9 不许 `allow_redirects=True`（`tests/smoke/ux_v3_route_matrix.py:229` 的历史假绿正是这个）。

---

## 10. 实施分期（建议顺序，供队长排任务）

| 期 | 内容 | 产出/门禁 |
|---|---|---|
| **一期（形态甲最小可用）** | 5 模型 + 门户矩阵页（教师整班 / 学生填评教）+ 后台 4 列表 + xlsx 空表导出/结果导出/导入两段式 + 三侧权限 + 588 接管 + V1–V10 验收 | `safe_upgrade.sh edu_assess` EXIT=0；`check_english`/`check_odoo_trace`/`check_qweb_dict_foreach` 各自口径 0；`check_accessibility` 不新增违规 |
| **二期（"参数丰富"增强）** | 权重参与总分（`加权总分 = Σ 得分×权重`）、档位/区间给分（抄 Canvas `criterion_use_range`）、汇总算法下拉（抄 Canvas Outcomes 六枚举 `calculation_method`）、条件题（抄 `survey.triggering_answer_ids` 研究 §2.1.5）、雷达图 | 每项独立可验收；不改一期数据模型（只加字段） |
| **三期（退场）** | 旧路由 303 + 旧菜单停用（本地/生产）→ 备份 → 卸 `edu_eval` / `migrations` 删 A 套表 → 台账回填 → 手册重生成（3.5/3.6 两节合成一节） | §7 的 7 条前置条件全绿 |

**回滚**：一期/二期 = 停新模块菜单 + 退代码（旧两套**仍未删**，天然可回）；三期 = 从 §7 的备份恢复（`pg_dump` 文件 + 重新 `-i edu_eval`）。

---

## 11. 需要校长拍板的用户可见项（8 项）

| # | 问题 | 备选 | 我的建议 | 影响面 |
|---|---|---|---|---|
| 1 | **旧模板要不要迁** | A 不迁（导出留档 + 按需重建，≈0.5 人日）/ B 迁（≈1 人日 + 真机验证） | **A**（生产实读：0 条打分，唯一非演示模板只剩 1 项「迟到」） | 教务重建工作量 |
| 2 | **评教是否真匿名**（现状**不匿名**，帮助页却写"完全匿名"） | ①实名（改文案）②不留痕（可刷票）③HMAC 指纹 + 汇总门槛 | **③**，且**必须**同时改 `help_center.xml:100` 的文案；若不采纳 ③，则文案必须删掉"匿名"二字 | 学生可见承诺、教师评价真实性 —— **属合规问题，建议优先拍板** |
| 3 | **教师打分范围** | 只限自己任教班（推荐）/ 全校（现状 `_is_staff()` 口径） | **只限自己任教班** | 防止任意内部用户给全校学生打分（§8.2-1） |
| 4 | **权重口径** | 保留 `weight` 倍率字段（B 套有）/ 只靠 `max_score` 表达权重（Moodle 口径）/ 两者都有 | **两者都有**（校长要"参数丰富"；字段成本极低） | 总分算法口径 |
| 5 | **Excel 里遇到没见过的列头** | 报错不新建（推荐）/ 自动建评分项 | **默认报错**，另给显式勾选「按新列创建评分项」 | 误操作会不会污染模板 |
| 6 | **教务的 Odoo 原生「导出」权** | 不给（现状，用自研最小权限导出）/ 给 `base.group_allow_export` | **不给**（给了等于放开他们能读的**所有**模型的导出） | 数据外带面 |
| 7 | **删除旧两套的最终授权** | 分两段（先停用 30 天再卸载，推荐）/ 一次到位卸载 | **先停用，30 天无报障再卸载** | 不可逆动作，需书面确认 |
| 8 | **不新增第 3 个评估入口的菜单口径** | 接管 588「综合评估」并改名「评估」（推荐）/ 新建独立根菜单 | **接管 588**（新建根会破 backoffice ≤12 的验收线） | 后台菜单可见根数量 |

---

## 12. 未查到 / 不确定（**不得当结论用**）

1. **本轮本地栈未运行**（`docker compose ps` → `Cannot connect to the Docker daemon`，2026-09-18 实测）⇒ 本文**没有任何本地真机读数**；§2.2 里"本地 597 已停用/子树已迁 588"引自 `code-map.md` 与 `edu_nav` 的 data 文件，**未在库里复核**。
2. **生产门户越权未实测**：V8 的判据来自 `security-audit-app.md` 的方法论（该审计第 0 节自陈"生产环境未使用真实门户账号做越权实测"，结论由本地实测 + 本地/生产 ACL 逐条比对支撑）；**新引擎的 V8 必须重跑**。
3. **`openpyxl` 写 xlsx 未在 Odoo 请求周期里跑过**：生产容器 `import openpyxl` → 3.1.2（实测）属实，但"Odoo worker 里写 xlsx + `make_response` 下载 + 大文件内存"**未验证**；建议一期先用小文件验收，并在 `limits` 里设行上限。
4. **`base_import` 的门户侧不可用、只能后台**：条件引自研究 §2.7（`import_records.js:42-48`），**本轮未在真机点过一次**。
5. **本地与生产的菜单不一致**已实测（`edu_nav` 生产未装）；但**生产 `ir_ui_menu` 全量**（597 的子树是否还有别的孩子、是否有孤儿）**未逐条查**。
6. **HMAC 匿名的抗穷举性未做安全评估**：盐的存放（`ir.config_parameter`）、`user_id` 空间、以及"教务能否通过 `summary_min` 反推个体"**均未验证**。
7. **"权重靠分值表达"（Moodle 口径）未复核原文**：转引自 `docs/research/evaluation-rebuild.md:357`（该行来自 Wayback 2024 快照，非实时页面）。
8. **第三方表格引擎**（Univer / jspreadsheet / SheetJS）**一律未实测**：本设计一期**不引入**任何第三方前端表库（研究 §6.3/§6.4 的许可红线 + §8 未验证清单），二期若要"自由单元格感"再单独评估。
9. **`edu.assess` 的一期范围外功能**未验证可行性：区间给分、`calculation_method` 六枚举、条件题、雷达图 —— 都只是"抄得到"（研究 §4.2/§4.3），**未落设计**。
10. **第三处评估实现的搜索边界**：未搜 `openeducat_erp/` 全量源码（只在 `ir_model` 层确认无 `%eval%`）、未搜编译产物、未逐个读 `reference/`|`scrape/` 素材；`ir_ui_menu` 只精确查了已知 id，**未做全量名称模糊匹配**（§2.3 边界段）。⇒ "没有第三套"的结论，**范围**如上。
11. **删除 A 套表的 `migrations` 具体形态未验证**：`edu_portal` 现有 `migrations/19.0.2.0.0/`（费用分类先例）在**生产已跑过**（`edu_portal 19.0.2.0.0` 已装），新增迁移目录版本号与执行顺序**未验证**。
12. **手册 `docs/manuals/永约教务系统操作手册.docx` 的现状未读**：只读了生成器 `scripts/gen_manual.py:158-176`；生成物本身是否已随旧菜单过期**未核对**。

---

## 13. 需同步更新的文档（给队长/文档侧，不在本设计内执行）

| 文档 | 要改成什么 |
|---|---|
| `docs/code-map.md` §4/§4.1/§5/§8 | 评估段（`:97-101`）改为新引擎；§5 路由表（`:226,228`）加 `/assess/*` 与 303；§8 索引加本文件、标注 `eval-merge-design.md` 作废 |
| `docs/audit/deprecated-inventory.md` | B2/B3/C-05 的"何时可删/前置条件"按 §7 重写；新增"新引擎并存登记"一行（**本次已追加，见变更记录**） |
| `docs/plans/eval-merge-design.md` | 加一行醒目**作废**声明（原因见 §1） |
| `docs/plans/eval-design.md` | 该文件 `docs/code-map.md:290` 标"待确认"的 A 套设计，随 A 套退场一并标作废 |
| `docs/research/evaluation-rebuild.md` | 建议追加"§7.1 的 Properties 推荐被 `docs/plans/evaluation-rebuild-design.md` §5 推翻（原因：D 依赖 `base_import`，而它不能映射 jsonb 子键）"一行勘误（**不改正文**，调研档案应保留原样） |
| `scripts/gen_manual.py` / `docs/manuals/…docx` | 3.5 + 3.6 两节合成一节"评估" |
| `scripts/gen_icons.py` / `scripts/portal_token_map.py` | `edu_eval` 图标与色令牌引用改到 `edu_assess` |
