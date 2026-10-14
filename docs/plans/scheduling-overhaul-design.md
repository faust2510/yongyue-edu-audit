# 排课链路改造设计（先排课后报课 · 降本交互 · 教师不可用 · 人工排课路径）
> **状态**：`已上线` ｜ **主题**：`排课链路改造` ｜ **取代**：`—` ｜ **核对**：`2026-10-14`
> ⚠️ 本文原写「仅设计（本次未写一行代码）」，实际已于 `1ec787f` 交付 §18（2026-09-26 核对发现）；主体四件（G1 报课池三档 / G2 覆盖看板 / G3 预检查三类化 / G4 教师不可用）已于 `59c33a6` 交付并部署上生产（2026-10-14，实测见 §19.5）。正文未改动。

> **历史状态**：仅设计（第 0 步「落地前查重」+ 第 3 步「读参考」+ 第 4 步「设计摘要」）。
> **本文件不代表已实施**——本次**未写一行代码**、**未新建模块**、**未动 `custom_addons/`**、**未动 `openeducat_erp/`**。
> **一句话目标**：把「排课」从一条断掉的手工线，变成**报课的前置条件**——教务先排完，学生才能报，报完课表就有课。
> **口径来源**：`docs/dev-workflow.md` 第 0 步与六步闸门 ｜ `docs/research/scheduling-approaches.md`（铁律 0 产物）｜
> `docs/plans/session-change-impact-design.md`（C-1，已上线）｜ `docs/plans/class-batch-management-design.md`（班级口径）｜
> `docs/audit/task-B1-enroll-timetable-gap.md`（B1 诊断）｜ `docs/audit/feature-overlap-audit.md` ｜ `timetable_import/catalog.md`（既有排课数据契约）
> **采集时刻**：**2026-09-18**。读数口径：**生产** `prod-host / edu19-prod-db-1`（**只读 SELECT**，未做任何写操作、未触碰 `edu_telegram`/`edu_feedback`）
> + **本地** `edu19`（只读 SELECT）+ 容器 `edu19-clone-web-1` 内 Odoo 19 核心源码（`/usr/lib/python3/dist-packages/odoo/addons/`）。
> **未验证项**一律集中写在 §15，**不得当结论用**（本仓规范）。
> ⚠ **合规红线**：本文**不贴 `openeducat_erp/` 与 Odoo 核心任何源码**，只给**路径 + 行号 + 字段/记录命名**。

---

## 0. 结论速览（TL;DR）

| 项 | 结论 |
|---|---|
| **根因（一句话）** | 报课与排课是**两条不通的线**：`/subject/enroll` 的科目池来自**课程目录**（course 16 = 88 门），而学生对不对得上课，取决于 `op.session`（按 **batch** 排）；生产王佐报的 **21 门必修排课数 = 0**，他的档案班 B1 全库只有 **18 节**（神论 9 + 救恩论 9）。**再加第二层断点**：B1 是「年级档案班」，而真实课大部分挂在**合班批**（B1234/B34/A123B34…），`op.batch` **没有任何班-班归属字段**（§6.3）。 |
| **Q1 先排课后报课** | 推荐 **方案 B（全列 + 逐条标注 + 未排课禁选 + 必修未排课阻断提交）**，复用**既有 F6 blocker 机制**（`roles.xml:1938-1965` 继承模板，红字 + 禁用 + 横幅）；用**一个系统参数**做三档开关（`off/annotate/strict`），**默认 `annotate`** ⇒ 新学期待排课时**不会出现空目录**，只出现「暂不可报 + 可行动提示」。见 §7。 |
| **Q2 本期降本 3 件** | ① **预检查三类化**（有冲突 / 被规则限制 / 数据异常，且**数据异常必须分「致命/待补」两级**，否则生产 216/216 无教室 = 全屏红）；② **F-1 教师例外不可用**（零算法、老师自助，是「被规则限制」档唯一可判定的规则源）；③ **排课完成度看板**（把「还差哪些没排」变成可数、可分配、可验收）。见 §8。 |
| **Q3 与基座向导合并边界** | 裁定 **并存 + 边界裁定**：基座 `generate.time.table` **保留**（校长已定），门户 `/timetable/bulk` **不删、不重定向**；分工 = 门户**单科目 × 多周次批量**（含周次范围/单双周/停课日/预检/审计），向导**多科目 × 单日网格**；**合并动作延后**，前置 = 向导缺的 4 项能力补齐。见 §9。 |
| **Q4 F-1 教师不可用** | 复用核心 `resource.calendar.leaves`（**只做例外**）；挂载 = `op.faculty` 接 `resource.mixin`（已定方向）+ 存量 1 行迁移回填；**判定只用 `resource.calendar._leave_intervals_batch`（例外），绝不用 `_unavailable_intervals*/`_work_intervals`（会把常规工时算进来，把晚课/周末课误判为不可用）**；入口 = 教师门户「我的教学安排」页头按钮 → `/my/availability`；兜底 = **未填 = 可用，但必须显式提示「该教师未登记不可用时间」+ 看板显示登记率**。见 §10。 |
| **Q5 C-2 改课候选** | **本期不做候选搜索**；只保留 C-1 已上线的「标注连带影响」（受牵连课节 + 会被拦/不会被拦）。触发条件 = 真实教师 ≥2 位且资源接线完成 + ≥1 间教室在用 + F-1 有数据。若未来做，**「只换教室」优先于「只换时间」**（连带面小）。见 §11。 |
| **Q6 人工排课路径** | 沿用**已经跑通过一次**的 CSV 契约线：`timetable_import/parse_timetable.py` → `normalize_sessions.py` → `import_sessions.py --dry-run` → 生产导入（幂等，`PRODUCTION_CHECKLIST.md:37-47` 口径）→ `/timetable/bulk` 补零散课 → **看板核对覆盖率** → 发布 → 才开报课。**147 门不是都要排**：排课对象 = 教务定的「本学期开课清单」（按班给）。见 §12。 |
| **落地模块** | `custom_addons/edu_schedule`（排课侧：看板/预检查/不可用判定）+ `custom_addons/edu_portal`（报课侧：池过滤/审批提示）+ 教师自助页落 `edu_portal`（门户引擎所在）。**不新建模块。** |
| **零新建承诺** | 不新建模块；不新建业务模型/表；新增面 = 只读计算方法 + 3 组路由 + 1 个系统参数族 + 1 个继承视图 + `op.faculty` 1 个 `resource_id`（`resource.mixin` 口径）。 |
| **待校长拍板** | **5 项**（报课池开关默认档与文案 / 班口径「档案班 vs 合班」谁代表学生的课 / 教师不可用是否可被教务强行覆盖 / 看板对谁可见 / C-2 是否本期启动），见 §14。 |

---

## 1. 目标 / 非目标

### 1.1 目标（本期设计覆盖的范围）

| # | 能力 | 用户感受（校长可见） |
|---|---|---|
| **G1** | **报课只在「已排课」的范围内进行** —— 未排课的科目**不允许被选进报课单**，且页面直接说明原因 | 「学生不会再报一门永远不开的课」 |
| **G2** | **教务看得见「还差哪些没排」** —— 排课完成度看板（按班 × 科目的课时覆盖 + 教师/教室数据完整度） | 「排课排到哪了，一眼看得出」 |
| **G3** | **排课提示分三类**（有冲突 / 被规则限制 / 数据异常），不再只有「冲突」一档 | 「知道为什么排不下去，而不是只看到一片红」 |
| **G4** | **教师例外不可用成为一等数据**（老师自助录入，排课/改课时用它拦截） | 「老师有事先登记，教务排课时系统自己避开」 |
| **G5** | **一条可执行的教务排课路径**（批量导入 + 批量生成 + 覆盖核对） | 「排课有章法，不靠一格格点」 |

### 1.2 非目标（明确不做，避免范围漂移）

- **不做求解器 / 自动排课算法**：调研结论（`scheduling-approaches.md` §2.3、§9）已明确"机器出初稿 → 人用网格改 → 机器保证合规"，且我们**连数据都没备齐**（教室 0 使用、教师 1 位占位，§6.2）。
- **不做改课候选建议（C-2）**：本期只做到「标注连带影响」，见 §11。
- **不做格子/拖拽排课（调研 §6 的 #1/#3/#4）**：先要有班口径与资源数据，否则交互层的收益被数据缺口吃掉。
- **不做选课两轮制（志愿 + 抽签）**：调研 §7 的中国高校事实标准**不是本期瓶颈**；本期先把"报得对"解决。
- **不改基座**：`openeducat_erp/` **只读**；向导、四查、`op.session` 一律**继承扩展**，不就地改。
- **不碰红线**：不使用、不读取 `edu.telegram.outbox` / `edu_telegram` / `edu_feedback`（生产匿名意见箱）。
- **不做"排课到人"**（单个学生的个性化课表排课）：一对一场景本项目不存在。

---

## 2. 第 0 步①：先信 code-map（逐条锚点）

| 位置 | 内容 | 对本设计的含义 |
|---|---|---|
| `docs/code-map.md:103-104` | `edu_schedule` = 排课工具：`/timetable/bulk`→`/preview`→`/create`；`EduScheduleHoliday` 停课日；`OpSessionConflictExt` 冲突分色 | 排课侧改造**全部落在这个既有模块里** |
| `docs/code-map.md:223` | 排课路由：`/timetable/bulk*`（`edu_schedule/controllers/main.py`）、`/student/timetable`（`edu_portal/controllers/scheduling.py`） | 新增路由沿用 `/timetable/` 族，不另开命名空间 |
| `docs/code-map.md:75` | `edu_portal/models/` 含 `OpSession/OpExamSession/ResPartner` 等基座扩展 | 报课侧改动落在既有 `enroll.py` / `registration.py` |
| `docs/code-map.md:249` | 「新功能三件套 + 先写 `docs/plans/<功能>-design.md`」 | 本文件就是那个前置件 |
| `docs/code-map.md:256-263` | **权限四层**硬约定 | 新增菜单/ACL/路由必须声明层级（§13） |
| `docs/code-map.md:284` | `timetable-design.md`：已交付的排课系统（周课表四视角 + advisory lock + 开关固化） | 本设计**不重做**已交付部分 |

---

## 3. 第 0 步②：既有实现对照（逐条：查了什么 / 用什么命令 / 命中什么 / 为什么不复用）

> 规矩：**「没找到」也要写清搜索范围与方式**；**不允许"我记得没有"**。
> 本节命令均**在本工作区实跑**（2026-09-18），命中行号取自实跑输出；DB 读数为**生产只读** `SELECT`。

### 3.1 候选模型 / 路由 / 规则源查重

| # | 查了什么 | 命令 | 命中 | 结论 |
|---|---|---|---|---|
| 1 | 候选新模型「教师可用时间/不可用」`edu.*avail*`、`edu.*leave*` 之外的第二套 | `grep -rn "可用时间\|不可用\|可约\|教师日程\|可用时段\|availability" custom_addons/` | **6 命中，全部是日志文案**（`session_ext.py:302/339/689/760`「站内信模型不可用」等）+ `edu_life/views/portal_templates.xml:42` 打卡报错文案 | **全仓没有「教师可用性」实现** ⇒ 不存在第二套可用性语义 |
| 2 | 核心 `resource` 是否已被本仓使用 | `grep -rn "resource\.calendar\.leaves\|resource\.mixin\|resource\.resource" custom_addons/` | **0 命中** | 本仓**从未**接过核心 resource ⇒ 接入是「新建接线」，不是「合并两套」 |
| 3 | 是否已有「未排课 / 覆盖率 / 排课进度」实现 | `grep -rn "未排课\|覆盖率\|coverage\|排课进度\|scheduled_n" custom_addons/` | **0 命中** | 看板无先例 ⇒ 但**零新模型**（只读聚合），见 §8.3 |
| 4 | 是否已有「候选方案 / 替代时段」实现（C-2 查重） | `grep -rn "候选\|替代方案\|alternative\|建议时段" custom_addons/` | **2 命中**，均无关排课（`edu_portal/models/fees.py:129` 费用分类删除护栏、`controllers/ledger.py:303` 班级下拉包装） | 排课候选**无先例**；本期也不做（§11） |
| 5 | 「列出但禁止选择 + 逐条原因」有没有先例 | `grep -rn "blocked_n\|precheck_msg\|\['blockers'\]" custom_addons/` | `edu_portal/controllers/enroll.py:127,137,187,189,259`（算）+ `edu_portal/views/roles.xml:1944,1947,1950,1956-1958,1963-1965`（**渲染：红字「不可报：<原因>」+ 页顶横幅 + `t-att-disabled` 禁选**） | ✅ **现成的同型机制（F6 先修/学分/容量校验）** ⇒ Q1 **必须复用它**，不得另造"未排课"提示体系（§7.4） |
| 6 | 冲突判定是否只有一份 | `grep -rn "conflict_kind\|conflict_color\|_overlaps" custom_addons/` | `edu_schedule/models/session_ext.py:104-156`（唯一活实现）；基座快照 `openeducat_timetable/models/timetable.py:243-337`（只读，不参与计算） | **必须复用同一口径**，不得写第二套冲突判定（C-1 §3.1#5 已定） |
| 7 | 基座向导有没有第二份"批量生成" | `grep -rn "generate\.time\.table\|gen\.time\.table" openeducat_erp/openeducat_timetable/` | `wizard/generate_timetable.py:31`（`_name`）、`:137`（line 模型）、`wizard/generate_timetable_view.xml:38-101`（表单 + 动作）、`menus/op_menu.xml:22-25`（菜单「生成时间表」） | 与门户 `/timetable/bulk` **功能重叠**（C-1 §1.2 已记待办）⇒ 本设计**裁定边界**并**登记台账**（§9、§16） |
| 8 | 排课数据从哪来（避免设计脱离现实） | `ls timetable_import/` + 读 `catalog.md` / `import_sessions.py` / `PRODUCTION_CHECKLIST.md` | 生产 216 节**就是这套流水线导入的**（`PRODUCTION_CHECKLIST.md:37-47` 期望读数 216、`import_sessions.py:33-44` 教师占位「待定」/教室留空/幂等判重） | **Q6 的现实路径必须沿用这条线**，不得另造导入器（§12） |

### 3.2 「没找到」的负结论（写清范围，可复现）

| 负结论 | 搜索范围与方式（原样可复现） |
|---|---|
| **全仓没有「排课完成度 / 覆盖缺口」的任何实现** | ① `grep -rn "未排课\|覆盖率\|coverage\|排课进度" custom_addons/ docs/ scripts/`；② 通读 `docs/code-map.md` §4 全部 `edu_*` 段与 §5 路由速查；③ 读 `docs/plans/timetable-design.md` 全文（79 行）、`docs/plans/enroll-v2-design.md`（D7 明确「本期不做自动冲突检测」） |
| **全仓没有「教师不可用」数据** | ① 命令 #1、#2；② 生产只读：`resource_calendar_leaves` = **0 行**、`op_faculty_with_emp` = **0**（§6.2） |
| **全仓没有第二套「批量建 op.session」的服务端入口** | ① `grep -rn "op\.session" --include="*.py" custom_addons/` 逐条判定：写路径只有 `edu_schedule/controllers/main.py:486`（`Session.create`，批量排课）、`edu_schedule/models/session_ext.py:200-227`（会议链接建 `calendar.event`，不建 session）；② `grep -rn "op\.session.*create\|create.*op\.session" ` |
| **报课截止是「展示项」不是「闸门」** | `custom_addons/edu_portal/views/enroll.xml:104`（只渲染 `enroll_deadline_cn`）；`controllers/enroll.py` **无任何** `deadline` 判定（`grep -n "deadline" controllers/enroll.py` = 0）⇒「排课完成前不许报课」目前**没有**服务端闸门，是本期要补的一条（§7.5） |

---

## 4. 第 0 步④：升级会不会动业务数据 ｜ ⑤ 演示数据策略

### 4.1 ④ 本次是否向业务表写数据

**命令**：① 读 `custom_addons/edu_schedule/__manifest__.py`（`data` 清单在 `:12-19`，共 6 项，**无 `demo` 键**）；② `grep -rn "<function" custom_addons/edu_schedule/data/`。

**结论**：`edu_schedule` 现有 `data/` 只有 `data/cron.xml`（`ir.cron`，**配置类**）。

**本设计对 `data/` 的约束（实施时必须遵守）**：

1. `data/` **只允许**配置类记录：视图/菜单/ACL/`ir.config_parameter`/`ir.actions`。**任何写 `op.session`、`edu.audit.log`、`edu.message`、`resource.calendar.leaves` 的 `<function>` 一律禁止进 `data/`**（依据：`dev-workflow.md` 第 0 步 ④ 与 `finding-F5`）。
2. 唯一需要**回填**的是 `op.faculty.resource_id`（存量 1 行「待定」教师）⇒ 走 `scripts/migrations/` + `migrations/<版本>/`，**不放 `data/`**。
3. ⇒ 预期 `-u edu_schedule` 的**业务数据副作用 = 0**；`-u edu_portal` 同理（新增的只是视图继承与参数）。

### 4.2 ⑤ 演示数据策略（一句话）

**不新增演示业务数据**；功能验证用「真机造一节真课 + 改回原值」的三段模板（`dev-workflow.md`：「① 绕过被测路径 → ② 读真正的产物 → ③ 还原并断言 `leftover=0`」）。
若确需造样本（本地没有"有学生的班 × 有课时的科目"组合、没有教师不可用数据），则放 **`scripts/seed_scheduling_demo.py`**（仓库既有惯例：`scripts/seed_*.py` 必须幂等），名称前缀 **【演示】**，同脚本 `--clean` 分支按前缀 `unlink` 并断言计数归零。**禁止**放进 `data/`。

---

## 5. 第 3 步「读参考」：学什么 / 砍什么

### 5.1 基座 `openeducat_timetable`（只读快照；**只给路径 + 行号**）

| # | 主题 | 一手位置 | 学什么 | 砍什么 |
|---|---|---|---|---|
| 1 | 七日网格向导 | `wizard/generate_timetable.py:30-62`（`generate.time.table` + 7 条 `time_table_lines_1..7`，每条 = 一天）；`:87-133`（`act_gen_time_table`）；`wizard/generate_timetable_view.xml:43-84`（notebook 七天页）；菜单 `menus/op_menu.xml:22-25` | **「一天多行、每行一个科目/教师/教室」** 的并行排课形态（我们门户页是"单科目 × 多周次"）；`:99-101` 的**学生预取**口径（批量建课时不跑 onchange ⇒ 必须自己带 `student_ids`） | **不搬它的代码**；它的缺失清单见 §9.2（周次范围/单双周/停课日/落库前预检 4 项） |
| 2 | 四查冲突 | `models/timetable.py:243-337`（四开关 `:247-254`；±24h 预筛；`state != 'cancel'` 不参与） | 冲突**语义基准**：我们的三类提示里「有冲突」一档**必须与它同构**（C-1 §3.3#13 已定） | 不调用它（它是 `@api.constrains`，不能当查询用） |
| 3 | 值得通知的字段白名单 | `models/timetable.py:507-510`（`_NOTIFY_WORTHY_FIELDS` 8 个字段） | 与 C-1 的 `IMPACT_WATCH_FIELDS`（`session_ext.py:395-398`）**同集合**已是既有事实 | — |
| 4 | 状态机 | `models/timetable.py:53-56`（`draft/confirm/done/cancel`） | 「发布」= `draft → confirm`（Q6 路径的最后一步） | 不用 `state='done'` 表达"已发布" |

### 5.2 Odoo 19 核心 `resource`（**F-1 的唯一参考**；容器 `edu19-clone-web-1` 内实读）

| # | 主题 | 一手位置（核心源码） | 学什么 | 砍什么 |
|---|---|---|---|---|
| 1 | 例外（leave）实体 | `addons/resource/models/resource_calendar_leaves.py:12-50`：`name`（:35）、`calendar_id`（:39，由 `resource_id.calendar_id` 计算）、`date_from/date_to`（:45-46）、`resource_id`（:47，**空 = 全公司**）、`time_type`（:50，`leave/other`） | **"某资源某时段不可用"的官方原语** ⇒ 教师「例外不可用」用它，**不自造日历语义**（已定方向） | 不用 `time_type='other'`（那是"当作工作时间"，与例外相反） |
| 2 | **取例外区间的正确 API** | `resource_calendar.py:502-550` `_leave_intervals_batch`（:528 直接查 `resource.calendar.leaves`） | ✅ **只用它**：给它**空 calendar**（`self` 为空 recordset）时，`calendar_id` 过滤被跳过，只剩 `time_type='leave'` + 资源匹配 ⇒ **纯例外**，与常规工时无关 | — |
| 3 | **不要用的 API** | `resource_calendar.py:556-572` `_work_intervals_batch`（= 出勤时段 − 请假）；`:574-600` `_unavailable_intervals*_batch`；`resource_resource.py:145` `_get_unavailable_intervals` | ⚠ **这三条会把"常规工作时段之外"也算成"不可用"**——公司日历是「Standard 40 hours/week」（生产实测，§6.2），**周一至周五 8:00-17:00 之外全会被判不可用** ⇒ 我们真实的晚课（`19:15-21:15`，见 `catalog.md:45-47`）与周末课会被**误拦** | **明确不用**（这是本设计最容易写错的一条） |
| 4 | 接线方式 | `resource_mixin.py:11-48`：`resource_id`（:14-16，**`required=True`**、`ondelete='restrict'`）、`resource_calendar_id`（:20-22）、`tz`（:23-24）、`create()`（:30-48，**自动为缺失 `resource_id` 的记录建 `resource.resource`**）；`resource_resource.py:34-60`（`resource_type` :34-38、`user_id` :38、`calendar_id` :47-52）；`res_users.py:9-16`（`res.users.resource_ids` 已内建） | 「教师 ↔ 资源」用官方 mixin 接线，**零自造钩子** | 不接它的常规工时语义：**`resource_calendar_id` 保持公司默认且不展示、不参与判定** |
| 5 | 同型先例（接线共存） | `addons/hr/models/hr_employee.py:42`（`hr.employee` 同时用 `resource.mixin` 与 `_inherits`） | 证明「`resource.mixin` + `_inherits`」在核心并存可行 | — |
| 6 | 请假业务层 | `hr_holidays` 生产**未安装**（§6.2） | ⇒ **不要**依赖 `hr.leave` 做例外 | 不做请假审批流（本期只要"不可用时段"这条最小数据） |

### 5.3 本仓既有可复用件

**可复用**：`conflict_kind` / `_overlaps` 口径（`session_ext.py:104-156`）；`_impact_flags()` 四查开关读取（`:426-443`，含"基座判字符串真值"的口径照抄）；`_impact_related()` 的"会被拦/不会被拦"判词（`:463-507`）；`_reminder_users()`（`_session_student_users` 的**空 `student_ids` 回退**，`:257-282`）；`edu.message._notify_event`（`notify_pref.py:51`，事件白名单 `notify_pref.py:15-24`）；`edu.audit.log._log`（`audit.py:29`）+ `/edu/audit`（`roles.py:1406`）；F6 blocker 渲染（`roles.xml:1938-1965`）；`/timetable/bulk/preview` 的"落库前预检"形态（`controllers/main.py:434-455`）；advisory lock（`edu_portal/models/scheduling.py:17-24`）。
**不可复用**：`edu_telegram` 全套（退役 + 出口红线）；基座 `notify_user()` 作为主通道（草稿态不发、只发 followers，C-1 §3.2#11）。

### 5.4 回引 `docs/research/scheduling-approaches.md`（第 4 步硬要求）

| 调研 §6 的 8 种降本手段（`:348-357`） | 我们的现状（同一张表） | 本设计的落点 |
|---|---|---|
| #1 格子/表格排课 | ❌ 表单填组合 → 生成 N 条 | **本期不做**（§8.4 理由） |
| #2 落库前预检查 + **提示分三类** | ✅ 部分（`/preview` 有红/灰格），但**只区分"冲突/无冲突"** | ✅ **本期第 1 件**（§8.1）——补「被规则限制」「数据异常」两档，并按"致命/待补"分级 |
| #3 对向高亮 / #4 双击即建 | ❌ | **本期不做**（依赖 #1 的网格形态） |
| #5 多视角课表 | ✅ 部分（学生/教师/家长/全校，`edu_portal/controllers/scheduling.py`）；❌ 教室视角 | **不做教室视角**：生产 216 节**教室 100% 为空**（§6.2）⇒ 做了也全是空列（**数据先行的直接推论**） |
| #6 教师可用时间是一等数据 | ❌ **完全没有** | ✅ **本期第 2 件**（F-1，§10） |
| #7 改课走最小扰动建议 | ❌ 完全靠人肉找空档 | **本期只做"标注连带"**（C-1 已上线）→ C-2 见 §11 |
| #8 周期批量生成 + 模板复制 | ✅ **我们最强的一环** | **不动**（§9 边界）；看板只是它的"结果校验"（§8.3） |
| §9 第 1 件顺带复核（基座向导缺什么） | — | 已读全 ⇒ §9.2 给出 4 项缺失清单与合并前置 |

---

## 6. 现状事实（**我自己复核过**的生产读数，2026-09-18）

### 6.1 排课侧读数（生产 `edu19-prod-db-1`，只读）

```
op_session = 216（100% state='draft'；按学期切分 term1 195 / term2 21；时间跨度 2026-08-31 ~ 2027-01-12）
op_session 覆盖：distinct subject = 18 ｜ distinct batch = 13 ｜ distinct faculty = 1 ｜ distinct classroom = 0
op_session 空值率：timing_id 空 = 0 ｜ faculty_id 空 = 0 ｜ classroom_id 空 = 216
op_subject = 147（compulsory 25 / elective 122）｜ 其中有排课的 = 18
op_course = 6 ｜ 其中有排课的 = 2（course 14 神学学士科 83 节 / course 16 教育学士 133 节）
op_batch = 19 ｜ 有排课的 = 13 ｜ **有在读学生的 = 1**（batch 13「B1 人文一年级」，1 人）
op_student = 19 ｜ op_student_course = 1（王佐 id 13：course 16 / batch 13 / academic_term 1 / running）
op_subject_registration = 1（id 19 / SR0017 / subject_registration / submitted；payload = 21 必修 / 0 选修）
op_session_op_student_rel = 0 行（课节的学生关系**全空**）｜ mail_followers(op.session) = 0 ｜ mail_tracking_value(op.session) = 0
timetable.is_*_constraint 四参数生产全部 = True
```

### 6.2 教师 / 教室 / 资源读数

```
op_faculty = 1（id 20「待定」，partner 33，登录账号 teacher@local，uid 33）—— 216/216 节课全挂在它下面
op_faculty_with_emp = 0（基座 op.faculty.emp_id → hr.employee，一列已存在但从未使用）
op_classroom = 3 ｜ op_session 中 classroom_id 非空 = 0
resource 模块 installed ｜ resource_calendar = 1（「Standard 40 hours/week」，tz=UTC）
resource_calendar_leaves = 0 ｜ resource_resource = 2（Administrator#1/user 2；李强#8/user 空）
hr installed ｜ hr_holidays **uninstalled** ｜ hr_employee = 2（Administrator / 李强）
教务组 id 40 的隐含闭包 = {partner_manager, faculty, library×2, exam×2, timetable user/manager, attendance×2}（**不含 base.group_system**）
```

### 6.3 课程 16 的科目池 vs 真实排课（**Q1 的直接证据**）

| 项 | 读数 |
|---|---|
| course 16（教育学士 / CRS-BED）科目池 | **88 门**（compulsory **21** / elective **67**） |
| 其中**有排课** | **13 门，全部是 `subject_type='elective'`**（英语/课程设计实务/基督教与文学经典选读（二）/神论/课堂管理/圣约神学/使徒行传/逻辑一/护教学基础/希伯来语二/希伯来语四/圣灵论/救恩论） |
| 其中**报课单 payload 的 21 门必修** | **排课数 = 0**（`compulsory` 里**没有任何一门**有 `op.session`） |
| 王佐档案班 B1（batch 13）的课时 | **18 节 = 神论 9 + 救恩论 9**（其他 86 门池内科目在该班 0 节） |
| 有排课但**没有学生**的班 | 12 个（B1234 / B34 / B234 / A123 / B3 / A123B34 / A123B234 / A123B1 / A23B34 / B4 / A1 / A23） |

**两条结构断点（本设计的核心事实）**：

```
① 科目断点：  报课池 = course.subject_ids（88 门，课程级）   ✗  排课事实 = op.session（batch × subject）
               ⇒ 学生可以报一门"全库 0 节"的课；批了也变不出课（B1 诊断 §6(3) 已记）

② 班级断点：  学生档案挂 B1（年级档案班）  ✗  实际课多挂在合班批（B1234 / B34 / A123B34…）
               ⇒ op.batch 只有 (course_id, code, name, start/end, active)（生产实查列清单）
                 **没有任何"班-班归属"字段** ⇒ 即便排课全部排完，B1 学生也只看得见 B1 自己的 18 节
                 （王佐的课表口径 = 只按 batch 过滤：edu_portal/controllers/scheduling.py:100-103）
```

> 第 ② 条**不是本设计能顺手修好的**（要动数据模型）⇒ 列为**校长拍板项 P2**（§14），并给触发条件（§7.6）。

### 6.4 三选一裁定（逐能力，落成台账里的一个字）

| 能力 | 裁定 | 承载物（替代路径） | 扩展方式 | 收口 / 重新考虑触发条件 |
|---|---|---|---|---|
| 「已排课」判定 | **新建**（既有模块内**只读**方法，非新模型/新表） | `op.session` 的 `read_group` 聚合（§7.3 口径） | 报课侧调用同一份判定；**禁止**第二处实现 | 出现第二个"已排课"判定 ⇒ 收口成一处函数 |
| 报课页「未排课」提示与禁选 | **复用** | **F6 blocker 机制**（`controllers/enroll.py:126-152` + 继承模板 `views/roles.xml:1938-1965`） | 同一 `blockers` 列表追加一类原因；零新模板语义 | 出现第二种"禁选"UI 语义 ⇒ 合并 |
| 报课闸门（截止/开放） | **复用 + 补一条服务端判定** | 既有 `edu.enroll.deadline`（今天**只展示**，`views/enroll.xml:104`） | 服务端读同一参数，提交时判定 | 若校长要求"按班/按课程分批开放"⇒ 重新裁定（需新字段） |
| 排课完成度看板 | **新建**（既有模块内只读页，**零新模型**） | `edu_schedule` + 既有排课菜单 | 新 GET 路由 + 只读聚合 + CSV 导出（复用 `csv_download` 先例） | **看板出现任何写入口 ⇒ 立即收口**（§16 ③） |
| 三类提示（冲突/受限/异常） | **复用**（扩展既有格状态与判词） | `/timetable/bulk/preview` 的 `grid_counts`（`controllers/main.py:413-419`）+ C-1 影响面判词（`session_ext.py:491-506`） | 加 `unavailable` 档；"数据异常"分致命/待补两级 | 出现第三套提示色板 ⇒ 合并到这一套 |
| 教师例外不可用（F-1） | **复用**（核心 `resource`，不新建模型/表） | `resource.calendar.leaves` + `resource.mixin` | `op.faculty` 接线 + `/my/availability` 自助页 | §10.1 的 `company_id` 断言失败 ⇒ 降级「只加一列 + get-or-create」 |
| 改课候选（C-2） | **本期不新建**（明确不做） | C-1 影响面（已上线） | — | §11 的三条触发条件 |
| 基座向导 ↔ 门户 `/timetable/bulk` | **并存**（本期裁决） | 两个既有入口 | 分工口径 + 页头文案；**不碰基座** | §9.2 / §16 ①② |
| 合班 ↔ 档案班归属 | **本期不新建**（只登记 + 看板暴露） | `op.batch` + `op.student.course` | — | 校长拍板 P2 后立项（§7.6） |
| 通知 / 留痕通道 | **复用**（不另造） | `edu.message._notify_event` + `edu.audit.log` + `mail.thread`（C-1 已落地通道） | 新事件 key 登记进 `notify_pref.py:15-24` | 出现第二个通知出口 ⇒ 收口 |

---

## 7. 问题 1：「先排课后报课」怎么落地

### 7.1 三个方案

| 方案 | 页面表现 | 代价 / 风险 |
|---|---|---|
| **A 白名单（只列已排课）** | 科目池 = 该 (班级, 学期) 有 `op.session` 的科目；未排课科目**根本不显示** | ① **开学前未排课 ⇒ 目录空**（今天 course 16 只剩 13 门，其中王佐的班只剩 2 门）；② 学生**无法表达"我想上但还没排"的意愿**；③ 必修若也不显示，学生连"我该上什么"都看不到 ⇒ 信息倒退 |
| **B 全列 + 标注 + 禁选（推荐）** | 池保持课程目录全列；每张卡按 (班级, 学期) 判定并显示：已排课 → 「已排课 N 节」可勾选；未排课 → 红字「本学期未排课」+ 复选框 `disabled`；页顶横幅汇总「本课程有 N 门科目本学期未排课」 | ① 需要**服务端**同步阻断（否则前端 disabled 可被绕过）；② 必修（自动带全）必须**一起改口径**，否则 21 门幽灵必修照旧进 payload（今天的问题原样保留）|
| **C 全列 + 标注 + 允许选（只登记意愿）** | 同 B 但不禁选；提交后单据进入"待排课"状态 | ① 与校长方向（先排课后报课）**相反**；② 教务要面对一堆"批了也没课"的单（正是 B1 诊断 §6(3) 的场景）⇒ 不采纳为默认，只作为**降级档** |

### 7.2 推荐：**方案 B + 三档开关 + 必修同口径**（并给出空目录兜底）

**三档开关**（`ir.config_parameter`，教务在既有「报名与报课截止」设置页切换，`views/enroll.xml:552-561` 已有该设置入口）：

| 档位 | 池内容 | 未排课科目 | 适用 |
|---|---|---|---|
| `off` | 全列 | 可勾选（= 现状） | 应急回退（**零回归开关**） |
| **`annotate`（默认）** | 全列 + 标注 | **禁选 + 红字原因** | 常态；排课未完成时也不会空目录 |
| `strict` | 只列（已排课 ∪ 已批准单里的科目） | 不显示 | 排课完成后的"干净目录"（可选） |

**必修口径（必须与选修同判，否则等于没改）**：必修**同样按 (班级, 学期) 判排课**：
- 已排课的必修 → 自动带全（现状不变）；
- **未排课的必修** → **不进 payload**，并且**阻断提交**，页面红字给出可行动信息：
  「本课程有 **21** 门必修本学期尚未排课，暂不能提交报课。请联系教务处确认开课安排。」
- 理由：`controllers/enroll.py:214-218` 的"必修全量自动带（防绕过）"若不带排课口径，就会继续生成**批了也没课**的单（B1 诊断：payload 21 门、排课 0 门、交集 0）。

**空目录兜底（校长最关心的那种场景）**：
1. **默认 `annotate` ⇒ 结构上不会出现空目录**（池仍是课程目录全列），只出现"暂不可报"的红字与横幅；
2. `strict` 档必须有**专门空态**：「本学期课表尚未发布，报课暂未开放；请联系教务处。」——**禁止**沿用现有的"该课程暂未配置科目目录"（`views/enroll.xml:142-145`，那句会把"没排课"说成"没配课"，误导）；
3. **流程层兜底**（比 UI 更硬）：新增**报课前置闸门**——学生在 `annotate/strict` 档下若所选科目**全部未排课**则直接拒绝提交（服务端），并把现有"报课截止"从**展示项**升级为**真闸门**（`views/enroll.xml:104` 目前只显示，`controllers/enroll.py` 无判定，§3.2 负结论）：报课开放需教务**显式开关/日期**，建议流程规定「排课完成 → 教务开报课」。

### 7.3 判定口径（「已排课」到底怎么算 —— 实施照抄这一段）

**域**：`(学生档案 batch, 目标学期, subject)`。

- **班级** = 学生 `op.student.course.batch_id`（`student_course()`，`edu_portal/controllers/main.py:47-55`），报课页选的 batch 同样用它（`enroll.py:118-123`）。
- **学期** = 学生 running 档案的 `academic_term_id`（王佐 = term 1）；取不到时按"日期落在 term 区间内"兜底（生产 term：1 = 2026-06-23~2026-12-20、2 = 2026-12-21~2027-06-18）。
- **已排课** = `count(op.session) > 0`，条件：`batch_id = 该班` ∧ `subject_id = 该科目` ∧ `state != 'cancel'` ∧ `start_datetime` 落在学期窗口内。
- **不计入**：`state='cancel'`（停课）；`active=False` 的 session。
- **实现形态**：**一次 `read_group`** 拿 `(subject_id, count)`，再 `(min(start), max(start))` 供文案「已排课 N 节 · 首节 9/7」；**禁止**在模板里逐科目 `search_count`（88 门 = 88 次查询）。

### 7.4 复用（第 0 步「查到重复怎么办」）：**不另造提示体系**

直接在**既有 F6 机制**上加一类 blocker：
- 服务端：`enroll.py:126-152` 的 `subjects[]` 逐条构造处，把「本学期未排课」**append 进同一个 `blockers` 列表**（与先修/学分/容量同一栏），并把 `blocked=True`；
- 页面：**零改动**即生效（`views/roles.xml:1956-1958` 显示 `s['blockers'][0]`、`:1963-1965` 自动 `disabled`）；
- 横幅：`roles.xml:1947-1953` 的 `blocked_n` 文案需要按"未排课"这一新原因**补一句**（否则学生只看到"先修/学分/容量"三种原因，实际却是没排课）。

### 7.5 教务审批侧（防"批了也没课"）

报课审批详情页（`edu_portal/views/enroll.xml:315+`）新增一行只读提示：**「本单科目在本学期已排课 M / 共 N」**；M=0 时红字提示「通过后学生课表不会有任何课，请先排课」。数据源同上（只读聚合），**不新增字段**。

### 7.6 与「班级断点」（§6.3 ②）的关系

本期**不解决**合班归属（要动模型），但**必须让教务看得见**（看板显示"有学生的班 / 无学生的班"与"该班课时数"，§8.3）。三个候选方向（**P2 拍板项**）：
1. 把学生挂到**实际排课班**（一人多档案 ⇒ 撞 `op.student.course` 唯一约束 (`student_id,course_id,batch_id`)）；
2. 给 `op.batch` 加**班-班归属**（教学班 ↔ 行政班），课表口径改为"本班 ∪ 包含本班的排课班"（**语义最正**，成本 = 1 个字段/表 + 课表与报课两处口径）；
3. 排课时**按行政班各排一份**（数据 ×N，且同教师同刻会被四查判冲突 ⇒ 需放宽教师维，风险更高）。
> 建议方向 **2**；本期只登记，不实施（触发条件见 §7.6 的收口条目，台账 §16）。

---

## 8. 问题 2：排课交互怎么降本（本期只做 3 件）

### 8.1 第 1 件：**落库前预检查升级为「三类可区分」**（调研 §6 #2）

**现在是什么样（实测）**：

| 位置 | 现有档位 | 缺什么 |
|---|---|---|
| `/timetable/bulk/preview` 周矩阵 | `ok / conflict / holiday / miss / none`（`controllers/main.py:376-394`；计数 `:413-419`） | 实际是 **1 档冲突 + 3 档"被规则限制"（停课日/不在周次范围/单双周不匹配）**，**缺「数据异常」**；且四档在同一个色板语义下没被**明确命名**（学生/教务看到的只是红格灰格） |
| C-1 改课影响面页 | 两档判词：「保存会被系统拦下」/「不会拦，但人是受影响者」（`session_ext.py:491-506`） | 同样缺「数据异常」档 |

**要做的**（沿用既有判词结构，**不新增模型**）：

| 档 | 含义 | 判据（先例口径） | 处理 |
|---|---|---|---|
| **有冲突** | 与既有课时在 教师/教室/班级(含班级+科目) 任一维撞时段 | 复用 `_overlaps` + `_impact_overlap_dims()`（`session_ext.py:125-156,445-461`）与四开关 `_impact_flags()`（`:426-443`） | 保存会被拦（与基座同构）；预览格 = 红 |
| **被规则限制** | ① 停课日（`EduScheduleHoliday`）② 不在勾选的周次范围 ③ 单双周不匹配 ④ **（本期新增）教师例外不可用**（F-1） | ①②③ 已有（`controllers/main.py:378-390`）；④ = §10 的 `_leave_intervals_batch` 判定 | ①②③ 现在只"不生成"；④ **默认硬拦、可显式覆盖**（§10.3） |
| **数据异常（新增）** | 缺上级数据 / 数据不合常理 | 分两级（**必须分级，否则全屏红**）：<br>**致命**：无教师、科目不在本课程池、班级无 `course_id`、`end<=start`<br>**待补**：`classroom_id` 为空、教师是占位「待定」、班级无在读学生、无会议链接 | 致命 ⇒ 红字 + 阻止提交；待补 ⇒ **黄字提示 + 允许继续**，并在看板上汇总 |

> **为什么必须分级（一条硬证据）**：生产 `classroom_id` 非空 = **0/216**、`faculty` = 占位「待定」、有学生的班 = **1/19**。若把"缺教室/占位教师"判成致命异常，教务打开任何一页都会看到 **216 条红**（判据强度第 2 条：全红等于没有判据——"某个门禁没报 ≠ 那一处干净"的镜像形态）。

### 8.2 第 2 件：**教师例外不可用（F-1）成为一等数据**（调研 §6 #6 / §9 第 2 件①）

见 §10（含挂载、入口、拦截、兜底）。它是"被规则限制"这一档**唯一有内容的规则源**——今天所谓四个 `is_*_constraint` 只是**开关**，不是**规则**（`session_ext.py:426-443` 读的就是这四个 bool）。

### 8.3 第 3 件：**排课完成度看板**（把"还差哪些没排"变成可数）

**页面**：`/timetable/coverage`（GET，只读，门禁 = `require_internal` + 教务组；落在既有 `edu_schedule`，**不新增菜单根**，挂既有「排课管理」菜单下，`views/menu.xml:11-22`）。

**内容（全部只读聚合，零新模型）**：

| 区块 | 读数 | 用途 |
|---|---|---|
| 按班覆盖 | 每班：`course` / 在读数 / 课时数 / **有课时的科目数** / 首个课时日期 | 一眼看出「B1 只有 2 门课」「B2/B3/A2/A3 是 0」 |
| 按课程覆盖 | 每课程：科目池 N / 已排课科目 M / 覆盖率 M/N | 报课是否可开放（§7） |
| 数据完整度 | 教师实名率（非占位）、教室填写率、`student_ids` 填充率、`state` 分布（draft/confirm） | 决定"能不能发布"（待补档的来源） |
| 未排课清单 | `(班, 科目)` 差集导出 CSV（复用 `csv_download` 先例 `edu_portal/controllers/main.py:27-44`） | 教务拿去分工催排 |

**红线**：看板**只读**；**不得**在这里提供"一键排课"（那是 `/timetable/bulk` 的职责，避免长第二个写入口 ⇒ §16 收口条件）。

### 8.4 本期**不做**的（带理由，避免"看起来漏了"）

| 调研手段 | 为什么不做 |
|---|---|
| #1 格子/表格排课、#3 对向高亮、#4 双击即建 | 交互层的收益建立在"数据齐 + 班口径清楚"上；今天 **教室 0 使用、教师 1 位占位、班口径未定**（§6.2/§6.3）⇒ 先做数据与口径（§8.2、§7.6），第三期再做网格 |
| #7 改课候选建议（C-2） | 见 §11 |
| #5 教室视角课表 | 生产教室 100% 为空 ⇒ 做出来是空列 |
| #2 的"带权重约束清单"（调研"次优建议"） | 本期先把**规则数据**（F-1）与**提示分层**做出来；权重清单是它的下一步，不是同期 |

---

## 9. 问题 3：与基座向导合并的边界（裁定）

### 9.1 现状（实测，本地与生产一致）

| 入口 | 位置 | 能力 | 可见性（实测） |
|---|---|---|---|
| **门户 `/timetable/bulk`** | `edu_schedule/controllers/main.py:424-499`；菜单 **603「周期排课」**（`ir.act_url 742` → `/timetable/bulk`） | 单科目 × 多周次：周次范围、单双周、停课日、**落库前周矩阵预检**、批量审计、`student_ids` 预取 | 组 40（教务）/60（课表 manager） |
| **基座向导「生成时间表」** | `openeducat_timetable/wizard/generate_timetable.py:30-133`；菜单 **344**（`openeducat_timetable.menu_generate_time_table`） | 多科目 × 单日：7 天 notebook，每天多行（教师/科目/时段/教室各一），一次生成整个批次 | **仅组 60**（本地与生产一致：`ir_ui_menu_group_rel` 只有 gid=60）；教务组 40 **隐含** 60 ⇒ 教务今天**能**用它 |
| 单节改删 | 后台 `op.session` 日历/列表/表单（`views/session_conflict_view.xml` 继承 + `edu_portal/models/scheduling.py:17-24` 锁） | 改一节 | 教务/管理员 |

### 9.2 裁定：**并存 + 边界裁定**（不删、不重定向）

| 项 | 裁定 |
|---|---|
| 基座向导 | **保留**（校长已定）；**不改基座**；菜单保持可用 |
| 门户 `/timetable/bulk` | **保留**（不删、不重定向）；定位 = **教务的日常批量入口**（"某科目每周几 × 周次范围"） |
| 分工口径（写进两边页头文案） | 门户 = **单科目 × 多周次**；向导 = **一次排一整个班的课表**（多科目 × 单日网格） |
| **合并动作** | **延后**（本期不做）。合并前置 = 把向导缺的 4 项能力补齐（下面表），且必须在 `custom_addons` 里**继承扩展**向导模型，不改基座 |
| 触发条件 | ① 向导补齐 4 项且通过验收；② 教务连续 2 周只用其中一个入口（访问日志）；③ 第三个"批量建 `op.session`"入口出现（第 0 步脚本化条件：同功能第三次落地 ⇒ 写 `scripts/check_feature_overlap.py`） |

**向导相对门户缺的 4 项（本设计的读参考产出，实施时逐条补）**：

| # | 缺什么 | 依据 |
|---|---|---|
| 1 | **周次范围 / 单双周**（向导只能"起止日 + 每周固定星期"，无 `week_ranges` / `parity` 概念） | `wizard/generate_timetable.py:60-62` 只有 `start_date/end_date`；门户有 `_build_plan` 的 `week_ranges/parity`（`controllers/main.py:321-326,386-390`） |
| 2 | **停课日**（`edu.schedule.holiday`） | 向导全量跳过逻辑里查不到 `edu.schedule.holiday`（`grep -rn "edu.schedule.holiday" openeducat_erp/` = 0） |
| 3 | **落库前预检**（不落库先看红/灰格） | 向导直接 `create`（`:131-132`），没有 preview 阶段 |
| 4 | **中文 + 权限对口 + 审计**（向导界面为英文原版；它无 `edu.audit.log`） | `wizard/generate_timetable_view.xml` 全英文；门户批量建课有审计（`controllers/main.py:494-496`） |

> ⚠ 本期只做**边界裁定 + 台账登记**；**不碰向导一行代码**（`openeducat_erp/` 只读）。

---

## 10. 问题 4：F-1 教师「例外不可用」

### 10.1 挂载方式（裁定 + 证据）

**裁定**：**复用 Odoo 核心 `resource`（`resource.calendar.leaves`）承载例外**；`op.faculty` 用 **`resource.mixin`** 接线（= 已定方向），资源随教师档案自动生成。

| 决策点 | 内容 | 依据 |
|---|---|---|
| 数据实体 | `resource.calendar.leaves`（**只做例外**，不做常规时间表）：`resource_id` = 教师资源、`date_from/date_to` = 不可用区间、`time_type='leave'`、`name` = 原因 | 核心 `resource_calendar_leaves.py:35-50` |
| 资源 | `op.faculty.resource_id`（`resource.mixin`，`:14-16` **required**）+ `create()` 自动建资源（`:30-48`） | 与已定方向一致；`hr.employee` 同型先例 `hr/models/hr_employee.py:42` |
| **不接**常规工时 | `resource_calendar_id` 保持公司默认（生产 = 「Standard 40 hours/week」，tz=UTC），**不展示、不参与判定** | 「只做例外不做常规时间表」（校长已定） |
| **判定只看例外** | 只用 `resource.calendar._leave_intervals_batch(start, end, resources=…)`（`resource_calendar.py:502-550`），**传空 calendar** 以跳过 `calendar_id` 过滤 ⇒ 纯 `time_type='leave'` | ⚠ **绝不用** `_unavailable_intervals*`（`:574-600`）/ `_get_unavailable_intervals`（`resource_resource.py:145`）/ `_work_intervals_batch`（`:556-572`）——它们掺入常规工时，**会把晚课/周末课误判不可用** |
| 存量迁移 | 生产 1 行（`op.faculty` id 20「待定」）+ 本地 2 行需要回填 `resource_id` | 走 `scripts/migrations/`，不进 `data/`（§4.1） |
| 被否决的两种接线 | ① **只加一列 `resource_id`**（不继承 mixin）：更少副作用，但自造 get-or-create 钩子；② **复用 `hr.employee.resource_id`**（`op.faculty.emp_id` 列已存在）：今天 `op_faculty_with_emp = 0`、`hr_employee` 只有 2 行（含 Administrator）⇒ 会把"系统管理员"变成可被排课拦截的资源 | 收口触发条件见下 |

**实施时必须补一条断言（防止 mixin 的同名字段改变既有语义）**：`resource.mixin` 也定义 `company_id`（`resource_mixin.py:17-19`，stored、related `resource_id.company_id`），而 `op.faculty` 通过 `_inherits = {res.partner: partner_id}`（基座 `faculty.py:29`）**已经**有 `company_id` 语义。⇒ 接线后断言「写 `op.faculty.company_id` 仍同步到 `res_partner.company_id` 且多公司规则不变」；**若断言失败 ⇒ 回退到「只加一列 + get-or-create 助手」**（这就是收口触发条件）。

### 10.2 录入入口在哪一页（**老师自助**）

| 入口 | 路由 | 谁 | 说明 |
|---|---|---|---|
| **主入口（教师）** | `/student/timetable`（教师视角「我的教学安排」，`edu_portal/controllers/scheduling.py:97-99`）页头加按钮「我的不可用时间」→ **`/my/availability`** | 教师本人 | 页面外壳 `t-call="edu_portal.edu_page"`（`code-map.md:246`），写操作走兄弟路由 `POST /my/availability/save` + csrf（`code-map.md:246` 约定） |
| 次入口（教师） | `/my/apps` 卡片 + `/my/home` 教师工作台卡片 | 教师本人 | 与既有卡片引擎一致（`batch2.py` 的 `_YONGYUE_CARDS`） |
| 教务代填/总览 | 后台 → 时间表应用 → **「教师不可用时间」**（list + 日历），以及看板上的"登记率" | 教务组 + 系统组 | 四层口径：业务管理 ⇒ `groups="openeducat_core.group_op_back_office_admin,base.group_system"`（并列） |

**录入形态（零新模型）**：单条（某日某时段）+ **按周重复**（每周几 + 起止时刻 + 截止日期 → 保存时**展开成多条 `leaves`**，`name` 带批次前缀以便整批撤销）。**明确写清代价**：批次只是 `name` 前缀的约定，**不是**新模型；单条可单独改/删，批次可整批删。

**身份解析**：`current_faculty()`（`edu_portal/controllers/roles.py:178-180`，按 `op.faculty.user_id`，其实体是 related `partner_id.user_id`）——**今天就能用**，无需新模型。

### 10.3 排课与改课时如何拦截

| 场景 | 位置 | 行为 |
|---|---|---|
| 批量排课预览 | `edu_schedule/controllers/main.py:376-394` 的格状态 | 新增 `unavailable` 档：该教师在该 (日期, 时段) 有 `leave` ⇒ 格子标"教师不可用（原因）"；计数进 `grid_counts`（`:413-419`） |
| 批量排课落库 | `controllers/main.py:457-499` 的 `Session.create` | **默认硬拦**：命中教师 `leave` ⇒ 该行失败并计入 `failed`（沿用现有"逐行 try + 计数 + 首错回显"，`:485-492`）；勾选"忽略教师不可用"才建，**并在 `edu.audit.log` 留痕**（`:494-496` 已有审计点，追加一句明细） |
| 单节改课（表单/日历拖拽） | `op.session.write`（C-1 已 override：`session_ext.py:739-753`） | 在同一条写路径上补判定：新时段与该节教师 `leave` 相交 ⇒ 抛 `ValidationError`（与基座四查同形态，用户看到的是同一类红字） |
| 影响面页（改前预报） | `session_ext.py:463-507` | 「被规则限制」档补一维"教师不可用"（与"会不会被系统拦下"判词并列） |
| **逃逸口（必须有）** | — | `context` 键（如 `edu_skip_teacher_leave=True`），供 ① 批量导入脚本（`timetable_import/import_sessions.py`）② 教务"确需强行排课"两种场景使用；**使用即写 `edu.audit.log`**（谁、什么时候、绕了哪一节） |
| 强行排课的权限 | — | 仅教务组/系统组（`privileged_staff()`，`edu_schedule/controllers/main.py:48-56` 的就地判据） |

> **为什么逃逸口是硬需求**：`import_sessions.py` 是"216 节全部"的一次性批量 `create_multi`（`import_sessions.py:33-47`），一旦真实教师有了 `leave`，没有逃逸口 ⇒ **重跑导入会被自己的新规则拦死**（这正是"护栏把正常路径也堵死"的经典形态）。

### 10.4 老师不填时的兜底（**必须显式，不能静默**）

| 兜底 | 内容 |
|---|---|
| **默认语义** | **未登记 = 全程可用**（与 Odoo 核心一致：没有 `leave` 就没有例外）——**这是有意的**，但**不得静默** |
| **排课时可见** | 预览/影响面在该教师处显示灰字：「该教师未登记不可用时间」；看板显示**教师登记率**（已登记 / 全部教师） |
| **催办（P2，可选）** | 排课开放前 3 天，向未登记的教师发一条 `edu.message`（复用 `_notify_event`，**新事件 key `timetable_availability` 需在 `notify_pref.py:15-24` 白名单登记**，否则用户关不掉） |
| **教务代填** | 教务可在后台同模型代填（同一份数据、同一拦截口径），留痕走 `edu.audit.log` |
| **不给的保证** | **不承诺**"老师填了就一定避开"（排课是人做的；系统只保证"排的时候会拦 + 会告诉你"）。这句话要写进页面文案，避免对老师的过度承诺 |

---

## 11. 问题 5：C-2 改课候选方案（本期裁定）

| 项 | 裁定 |
|---|---|
| **本期做不做** | **不做**（候选搜索/自动改课） |
| **本期做到什么程度** | 只做到 C-1 已上线的「**标注连带影响**」：受牵连课节清单 + 逐条判词（`session_ext.py:463-507`、页面 `/timetable/session/<id>/impact`）。**不新增**候选生成、不排序、不一键改 |
| **若未来做，「只换教室」还是「只换时间」** | **优先「只换教室」**：① 教室不是排课四查里"必然发生的冲突源"（生产教室 100% 为空 ⇒ 先补数据）；② 换时间会改日期，连带面最大（教师/班级/学生窗口全动）；③ UniTime 的口径也是"可限制为 room-only / time-only / both"（`scheduling-approaches.md:165`），room-only 是最小扰动档 |
| **触发条件（可判定）** | ① F-1 数据到位（≥2 位真实教师完成资源接线且 ≥1 条 `leaves`）；② ≥1 间教室在 `op.session` 真实使用（今天 = 0）；③ 教务提出"换教室/换时段"的实际工单 ≥3 次（可用 `edu.audit.log` 的 `课节变更` 明细计数作为判据） |
| **依赖** | F-1（可用性数据）+ C-1（影响面）**均已具备**才立项；否则候选只会在空数据上"算出一堆假选项" |

---

## 12. 问题 6：人工排课的现实路径（147 门里怎么把该排的排出来）

### 12.1 先纠正一个前提：**147 门不是都要排**

- 生产 `op_subject` = **147 门**，其中**有排课的 18 门**；`op_course` = 6 个，其中有排课的 2 个。
- 排课对象应是**教务定的「本学期开课清单」**（按班给的 `(班, 科目)` 集合），而不是全库科目。
- 选课池 = 课程目录（course 16 = **88 门**）≠ 开课清单 ⇒ 这就是 Q1 要过滤的根源（§7）。

### 12.2 已跑通过一次的路径（**照抄，不要另造导入器**）

生产那 216 节就是这么进去的（`timetable_import/PRODUCTION_CHECKLIST.md:37-47` 给了命令与期望读数），路径如下：

| 步 | 动作 | 工具 / 命令 | 产物 / 判据 |
|---|---|---|---|
| 0 | **数据前置**：建真实教师档案（`op.faculty`，必填 `birth_date/gender`，`faculty.py:34-51`）；教室表（决策项 H）；**班级口径确认**（档案班 vs 合班，§7.6） | 后台「学生信息 → 教师」或 `scripts/create_teacher_account.py` | 教师实名率、教室可用性 |
| 1 | **从 Excel 生成 CSV**（改课表时只改源表） | `python3 timetable_import/parse_timetable.py` → `normalize_sessions.py`（契约 `timetable_import/catalog.md`） | `sessions.csv`（226 实体主表） |
| 2 | **离线干跑**（不连库、不写数据） | `python3 timetable_import/import_sessions.py --dry-run` | 冲突预检 0 冲突、计数与契约一致（`import_sessions.py:9-11,40-44`） |
| 3 | **生产导入（幂等）** | `PRODUCTION_CHECKLIST.md:37-47` 的 `odoo shell` + `SESSIONS_CSV` 形态 | `op_session` 计数 = 契约数；重跑 ⇒ `created=0 / skipped=N` |
| 4 | **零散/补排课** | 门户 `/timetable/bulk`（周次范围 + 单双周 + 停课日 + 预检）或后台基座向导（一天多行） | 新课时 + 审计记录 |
| 5 | **覆盖核对（本期新增，§8.3）** | `/timetable/coverage`（看板）+ 未排课清单 CSV | 每班每科目课时数；`(班, 科目)` 差集 = 0 |
| 6 | **发布** | 后台课节列表 → `state: draft → confirm`（基座状态机 `models/timetable.py:53-56`） | 课表对学生可见（`/student/timetable` 只含非取消课时） |
| 7 | **开报课** | 教务开闸（§7.2 的开关/截止日） | 报课单 payload **全部**落在已排课集合内 |

### 12.3 分工与节奏（给教务的一句话）

> **一次学期排课 = ①导入总表（Excel→CSV）②看板找缺口 ③门户补零散 ④核对覆盖 ⑤发布 ⑥开报课。**
> 每学期只需跑一次 ①，②③是每学期的日常，④是发布前的硬门槛（**覆盖率未达标 → 不许开报课**）。

---

## 13. 问题 7：真机可验证的验收标准

> 口径：**改了路由/控制器 ⇒ 必须有一条"打完就摸页面"的判据**（`dev-workflow.md` 陷阱 2）；**探测不许跟随重定向**（`allow_redirects=False` + 精确 `Location`）；判定模板 = 「① 绕过被测路径 → ② 读真正的产物 → ③ 还原并断言 `leftover=0`」。

### 13.1 环境前置（缺一不可）

1. 无升级锁；容器 Up > 30s；`curl -c jar -b jar 'http://localhost:8069/web/login?db=edu19'` ∈ {200,302,303}。
2. **计数型判定前先确认最近没跑过 `-u edu_life`**（`dev-workflow.md` 陷阱 1：会往业务表补演示打卡）。
3. **先取基线**：`op_session` / `edu_audit_log` / `edu_message` / `resource_calendar_leaves` / `op_session_op_student_rel` 五个计数。

### 13.2 逐条验收（建议落成 `tests/smoke/p1_scheduling_gate.py`，命名沿用 `p2_enroll_smoke.py` 家族）

| # | 步骤（可原样执行） | 期望读数 |
|---|---|---|
| V1 | `bash scripts/safe_upgrade.sh edu_schedule` 与 `... edu_portal` | **EXIT=0**，输出无 `Traceback`/`CRITICAL`/`manifest not found` |
| V2 | 离线门禁：`check_view_xpath --selftest`、`check_manifest_tracking --selftest`、`check_qweb_dict_foreach --selftest`、`check_english --selftest`、`check_odoo_trace --selftest`、`tests/smoke/gate_seam_check.py` | 全部 exit 0 |
| V3 | **正对照（载体合法性先断言）**：造/选一个「有在读学生的班 × 已排课科目」（本地：`batch 8` 有 1 名学生；生产：`batch 13` 有 1 名学生） | 载体存在，**不得在空载体上验收** |
| V4 | 学生登录 `/subject/enroll`（`annotate` 档）→ **摸页面** | 200；未排课科目卡上出现红字「本学期未排课」**且** 其复选框 `disabled`；页顶横幅计数 == `blocked_n`（与控制器注入值一致） |
| V5 | **绕过前端**：直接 POST `/subject/enroll/save` 带上未排课科目 id | 不落库（`op_subject_registration` 行数不变）且 303 回带 `box=precheck`；**先断言该科目确实未排课** |
| V6 | 必修未排课场景 | 提交被拒；页面文案含"尚未排课"与门数；`op_subject_registration` **零新增** |
| V7 | 教务审批详情页（`/registrar/subject/approvals/<id>`） | 页面出现「本学期已排课 M / 共 N」；M=0 时为红字 |
| V8 | `/timetable/coverage`（教务登录） | 200；页面上的「B1 课时数 / 有学生的班数 / 教师实名率 / 教室填写率」**与同一口径 psql 读数逐个相等**（人工对拍一次并写进报告） |
| V9 | `/timetable/coverage` 权限：学生/家长访问 | **303 + `Location == '/my/home'`**（`allow_redirects=False`） |
| V10 | 教师不可用登记：教师登录 `/my/availability` → 新增一条【演示】不可用（明天 10:00-12:00） | 200；`resource_calendar_leaves` +1 且 `resource_id` == 该教师资源；**`time_type='leave'`** |
| V11 | **排课拦截（读真正的产物）**：教务用 `/timetable/bulk` 给该教师排同一时段 | 预览格状态 = "教师不可用"；`/create` 该行 `failed=1`、`created=0`（`op_session` 行数不变） |
| V12 | **逃逸口**：带 `edu_skip_teacher_leave=True` 再排一次 | 建课成功，`op_session` +1；`edu_audit_log` 新增一条绕过留痕（含日期/教师） |
| V13 | 单节改课拦截：把一节既有课改到该教师不可用时段（表单保存） | `ValidationError`（用户可见红字），且 `mail_tracking_value`/审计**不产生**"改成功"的记录 |
| V14 | **误拦反例（这条最重要）**：把课排在**常规工时之外**（如 19:15-21:15，`catalog.md:45-47` 的真实形态）且该教师**没有 leave** | **允许保存**（证明我们没有用 `_unavailable_intervals*` 把"晚课"当不可用——§10.1 的判据） |
| V15 | 三类提示：构造 ① 真冲突 ② 命中停课日 ③ 缺教室（待补档） | 预览三类分别显示，**且"缺教室"是黄色待补而不是红色致命**（防全屏假红） |
| V16 | **还原并断言 `leftover=0`** | 删除 V10 的【演示】leave、V12 建的课、V14/V15 的样本；`select count(*) from resource_calendar_leaves where name like '【演示】%'` = 0；`op_session` 回到基线；`edu_audit_log` 的样本行按 res_id 清理 |
| V17 | 文案与无障碍门禁 | `check_english` must-fix = 0；`check_odoo_trace` 0 命中；`check_accessibility.py` **不新增违规**（新按钮/复选框必须带可访问名；`code-map.md:252`） |
| V18 | 权限四层自检 | 教务组可见可用；学生 303；教务组 implied 传递闭包**不含** `base.group_system`（生产实测已成立，§6.2） |
| V19 | `-u` 副作用 | 升级前后 `op_session`/`resource_calendar_leaves`/`edu_message` 计数**不变**（§4.1 的"零业务数据副作用"断言） |

### 13.3 明确不允许的验收写法（反例）

- ❌ 「`safe_upgrade.sh` EXIT=0」当作通过（装载 ≠ 路由能跑）。
- ❌ 用 `allow_redirects=True` 探测新路由（会把 303 判成 PASS）。
- ❌ 在没有学生的班、或没有课时的科目上验收「报课被正确拦下 / 课表有课」（载体不合法 ⇒ 稳定地绿）。
- ❌ 只读代码就声称「教师不可用已生效」——必须读回 `resource_calendar_leaves` 行 + 看 `failed` 计数（claim 与证据同级）。
- ❌ 用"跟随后 200"验证 `/timetable/coverage` 的权限（必须 303 + Location 精确）。

---

## 14. 需要校长拍板的用户可见项（**5 项**）

| # | 待拍板 | 选项 / 影响 |
|---|---|---|
| **P1** | **报课页对"未排课科目"的说法与默认档** | ① 默认 `annotate`（全列 + 红字「本学期未排课」+ 禁选，**推荐**）；② 直接 `strict`（只列已排课，目录更短但可能看起来"课变少了"）；③ 维持现状（`off`）。另需定**文案**：「本学期未排课」还是「本学期暂不开课」？**影响**：学生看到的第一句话 |
| **P2** | **「哪个班」代表学生的课（班级断点）** | ① 学生挂实际排课班（合班）② 新建"班-班归属"（教学班 ↔ 行政班，**推荐方向**，要动模型）③ 排课时按行政班各排一份（数据×N、且与四查冲突）。**影响**：**决定王佐那"不止 2 门课"能不能出现在他课表上**；不选就等于"排课排完了他也看不到合班课" |
| **P3** | **教师不可用可否被教务强行覆盖** | ① 可覆盖 + 留痕（**推荐**，否则一位老师忘删 leave 就卡死整学期）② 完全不可覆盖（安全但会卡死）③ 可覆盖但必须写原因（更严）。**影响**：教务的日常可操作性与"谁负责" |
| **P4** | **排课完成度看板对谁可见** | ① 仅教务/管理员（**推荐**）② 教务 + 教师（教师看自己班的缺口）③ 公开。**影响**：教师侧会看到"哪个班还没排完"这种管理信息 |
| **P5** | **C-2（改课候选）是否本期启动** | ① 本期不启动（**推荐**，数据不具备）② 只做"只换教室"的最小档。**影响**：本期工期与"排课优先"的排序（校长已定排课最前） |

> 除上述 5 项外，本设计**没有其他需要用户拍板的项**。

---

## 15. 未查到 / 不确定（**不得当结论用**）

| # | 未验证项 | 我做了什么 / 为什么不确定 |
|---|---|---|
| 1 | **生产"王佐应当上哪些课"的业务事实** | 只能证明：他档案班 B1 有 18 节、合班批有课但与他无关联。**他在教务眼里"本学期该上几门"**是业务口径，需教务/校长确认（P2） |
| 2 | **未以王佐/教务身份在生产真机登录复现** | 生产只读 SELECT + 本地源码逐行同口径；**未取生产页面 DOM/截图**（无凭据） |
| 3 | **本设计的一切"改造后行为"未验证** | 本文是第 4 步设计摘要；**未写一行代码**，所有行为均为设计意图（验收清单 §13 就是为补这个） |
| 4 | **`resource.mixin` 接到 `op.faculty` 的副作用（`company_id` 同名）** | 只能从核心源码读出字段定义（`resource_mixin.py:17-19`）；**实际是否改变 `_inherits res.partner` 的 company 语义未实测** ⇒ §10.1 已给断言与回退方案 |
| 5 | **教师端"我不可用"页的教师使用意愿** | 无人可问；只能给兜底（未填=可用 + 显式提示 + 登记率看板） |
| 6 | **基座向导在生产是否真的被教务用过** | 只能证明菜单可见（本地与生产 `ir_ui_menu_group_rel` 均仅 gid=60，教务组隐含 60）；**没有访问日志证据**（未取生产 web 日志） |
| 7 | **`2+6排课表.xlsx` 与本仓 `session_import_plan.csv` 的现状一致性** | 契约与导入脚本在仓内可读（`catalog.md`）；**源 Excel 不在仓库**（`catalog.md:4-7` 指明在本地其它目录），本次**未打开源表核对** |
| 8 | **教室维度的任何结论** | 生产 `op_session.classroom_id` 非空 = **0/216**、`op_classroom` 仅 3 条 ⇒ 教室相关判据（含"缺教室"提示、"只换教室"候选）在真机上**造不出自然样本**，只能造【演示】样本（§4.2） |
| 9 | **本地 `edu19` 的 288 节里"演示数据"占比** | 本地读数（`op_session=288`）与生产（216）不同源；本地只用于口径验证，**不代表生产** |
| 10 | **`edu_schedule` 的 `data/cron.xml` 在生产是否已启用** | 只读了 manifest 的 `data` 清单（静态）；**未核对生产 `ir_cron` 记录与其运行历史** |

---

## 16. 台账登记（第 0 步「查到重复怎么办」第 2 步）

**已在 `docs/audit/deprecated-inventory.md` §8 追加一行**（不改历史行）：

- **重叠对象**：① **基座向导 `generate.time.table`**（`openeducat_erp/openeducat_timetable/wizard/generate_timetable.py:30-133`；菜单 id **344**，本地与生产均**仅 `group_op_timetable_manager`(60)** 可见，教务组 40 隐含 60 ⇒ 教务今天能打开）与 **门户 `/timetable/bulk`**（`custom_addons/edu_schedule/controllers/main.py:424-499`；`act_url 742`；菜单 603）——同一个"批量建 `op.session`"的两个入口；② 候选新模型「教师可用性」在本仓 **0 命中**（§3.1 #1/#2），而核心 `resource` 已有例外语义（`resource_calendar_leaves.py:35-50`）。
- **裁定**：① **并存 + 边界裁定**（本期不合并；边界与合并前置见 §9.2）；② **复用核心 `resource`**（不新建模型/表）。
- **收口触发条件**：① 第三个"批量建 `op.session`"入口出现 ⇒ 按 `dev-workflow.md` 脚本化条件写 `scripts/check_feature_overlap.py`；② 向导补齐 §9.2 的 4 项能力后必须**一次性合并**（届时门户页改为继承向导）；③ 看板出现第二个写库入口 ⇒ 立刻收口（看板必须保持只读）。

---

## 17. 变更记录

| 日期 | 改动 | 责任 |
|---|---|---|
| 2026-09-18 | 初版：第 0 步（① ② ④ ⑤）+ 第 3 步读参考 + 第 4 步设计摘要；回答 7 个必答问题；生产只读复核（216/18/147/19/1 等读数）；台账登记一行 | 设计子代理（排课链路改造，`docs/plans/scheduling-overhaul-design.md`） |
| 2026-09-18 | **追加 §18 修订：各年级分开排**（校长同日裁定「各上各的」+「按年级重排」）；新增两件能力 = 多班批量排课（时间自动错开）+ 旧合班课时批量停用；生产只读复跑合班批 → 年级映射表 | 实现子代理（排课工具改造，§18） |

---

## 18. 修订：各年级分开排（2026-09-18，校长裁定）

> **本节是追加修订 —— §1–§17 原文一字未改**（本仓惯例：原结论保留在案，修订另起一节；哪些作废集中写在 §18.4）。
> **状态**：先设计后实施；本节落定后**本期已实施**（落点见 §18.7，**零新模块**）。
> **来源**：校长 2026-09-18 两句裁定 —— ① 问「英语这门课，人文一到四年级是一起上还是各上各的？」→ 答「**各上各的**」；② 再裁定「**按年级重排**」（明确**不是**写脚本拆数据）。
> **生产读数**：2026-09-18 只读 SELECT（`prod-host / edu19-prod-db-1`，与本文抬头同口径）；本节读数**已由实现子代理复跑核对**，并逐条记在 §18.5。

### 18.1 修订原因（校长原话 → 要解决的问题）

| 项 | 内容 |
|---|---|
| **触发事实** | 「英语」在生产挂在**合班批 `B1234`（批名「B1-B4全体」）的 18 节**上 —— 人文一~四年级事实上被并成一个班上课 |
| **校长裁定 ①** | 这类课**各上各的**：每个年级单独一条课时，不再共用一条合班课时 |
| **校长裁定 ②** | 落地方式 = **教务用排课工具按年级重排**；**不是**写脚本把一条课时拆成四条 |
| **校长关切（隐含，且必须成立）** | 拆完不能出现「同一位老师同一时间要给四个班上课」这种**假课表** |
| **与既有结论的关系** | 这正是 §6.3 的**第 ② 条结构断点**（「班级断点」）在**排课侧的解法**；§7.6 给过三个候选方向，本节把方向改为候选 ③，并补上它当年被否的理由如何被消掉（见 §18.4） |

### 18.2 为什么不能靠脚本拆（**本节的核心技术判据**）

**一句话**：脚本「一条复制成 N 条（起止完全相同）」会在**第一次写库时**被基座直接拒绝，而拒绝的原因恰好就是**教师维**。

判据链条（三层，逐层给代码位置；合规红线：不贴基座源码，只给路径 + 行号 + 字段名）：

| # | 层 | 位置 | 作用 |
|---|---|---|---|
| 1 | **基座硬约束** | `openeducat_erp/openeducat_timetable/models/timetable.py:243-337`（`check_timetable_fields`，`@api.constrains(faculty_id, start_datetime, end_datetime, classroom_id, batch_id, subject_id)`） | **教师维**在 `:311-316`：同一 `faculty_id` 且时间区间重叠 ⇒ 抛 `ValidationError`，整笔写入回滚。重叠用 `_overlaps`（`:291-307`，两端严格 `<` ⇒ 首尾相接不算冲突） |
| 2 | **四个开关** | 同文件 `:247-254` 读四个 `ir.config_parameter`：`timetable.is_faculty_constraint` / `is_classroom_constraint` / `is_batch_and_subject_constraint` / `is_batch_constraint`（定义见 `models/res_config_setting.py:7-11`） | 教师维开关**必须是开的**才拦得住。本项目同构实现读**同一组开关**：`custom_addons/edu_schedule/models/session_ext.py:426-443`（`_impact_flags`） |
| 3 | **本项目的只读预检（既有）** | `custom_addons/edu_schedule/controllers/main.py:188-239`（`_occupied_map` / `_slot_conflicted`）+ `session_ext.py:445-461`（`_impact_overlap_dims`） | ±24h 预筛 + `state != 'cancel'` 不参与 + **教师 / 教室 / 班级（含班级+科目）** 三维定级 —— 与基座同构，**只查不写** |

**推论**：把一条 `B1234` 的英语课时复制到 `B1/B2/B3/B4` 四条 ⇒ `faculty_id` 相同、`start_datetime`/`end_datetime` 相同 ⇒ 命中判据 1 的教师维 ⇒ **第 2 条起全部被拒**；而第 1 条能进库 —— 于是留下最难收拾的**半截数据**（4 个年级里只有 1 个排上了）。

**所以正确做法只有一条**：

1. **教务用工具重排** —— 时间必须在年级之间**错开**（能力 A）；
2. **旧的合班课时批量停用** —— `state = cancel`，**不删记录**（留痕、可回滚、可审计）（能力 B）。

### 18.3 本期新增的两件能力（都落在 `custom_addons/edu_schedule`，**零新模块**）

#### 能力 A：**多班批量排课 + 时间自动错开**（复用既有三步流 `/timetable/bulk → /preview → /create`）

- 教务一次勾选 **N 个班级**（例：人文一~四年级 `B1/B2/B3/B4`）+ **同一科目** + **同一教师** + **同一周次** ⇒ 系统生成 **N 组课时**，**时间自动错开**。
- **错开口径（本设计的裁定）**：
  1. **首班时段由教务指定**（沿用现有「上课时间」字段，选节次或填自定义起止）；
  2. 第 `i` 个班（`i` 从 0 起）的时段 = **首班时段 + i × 每班间隔**；
  3. **每班间隔默认 = 一个课时长度**（= 首班起止之差）；另给一个可选字段「**每班顺延（分钟）**」覆盖它（用于插入课间休息）。
- **为什么选「顺延一个课时长度」而不是「起始时间 + 每班间隔」两个参数**：
  1. **零新概念**：教务本来就只填一个时段；默认档**不需要理解间隔是什么**就能拿到互不重叠的结果；
  2. **可预测、可回算**：N 个班的时段在预览页**逐条列出**，教务当场核对；
  3. **顺序确定**：**第 1 个班 = 勾选列表里最上面那个**（HTML 表单顺序，不依赖点击顺序），页面明写口径，**不做隐式猜测**；
  4. **可救**：一位老师连上四节不现实时，改**一个数字**（每班顺延）即可加课间 —— 不需要引入第二个 UI 概念。
- **冲突预检（必须，且不许另造提示体系）**：
  - 做**两次**：`/preview`（落库前教务就看得见，沿用既有红格）+ `/create`（**写库前再查一次**；**有一条冲突就整批拒绝**，不做写一半）；
  - 判据**复用既有四查口径**（`_impact_flags` 四开关 + `_impact_overlap_dims` 定级 + 教师/教室/班级重叠判定），**不写第二套判据**；
  - 提示**复用 C-1 已上线的形态**：同一张明细表（时间 · 科目 · 班级 · 教师 · 重叠维度 · 判词），判词沿用 C-1 的两档「保存会被系统拦下」/「不会拦，但人是受影响者」；**不新增色板、不新增提示体系**；
  - **同一批内的互相冲突也必须查**：N 个班**共用同一位教师** ⇒ 本批**已生成的课时要当作既有课时**参与后续班的判定。否则「每班顺延 = 0」会把预检骗过去、直接撞基座（§18.6 的 V21 就是打这个）。

#### 能力 B：**旧合班课时批量停用（不是删）**

- 教务能**一键停用某个班（或某个合班批）的全部课时**：`state` 置 `cancel`，**不删记录**（行数不变）。
- **三件必须有的东西**：
  1. **二次确认**：点「停用」先进入**只读确认页**（列出将停用的课时数、时间范围、科目分布、受影响的人），必须**再勾选确认框 + 再提交一次**才执行；
  2. **审计留痕**：沿用 C-1 已上线的 `edu.audit.log._log` 写法（`custom_addons/edu_portal/models/audit.py:28-41`），**新增一个动作名**（`课节批量停用`），明细写「停用 N 节 · 跳过已停用 M 节」；
  3. **影响面提示**：复用 **C-1 的影响面口径**（`session_ext.py:559-573` 的 `_impact_recipients`：收件人 = **任课教师 + 该班全部在读学生**，家长不发；`student_ids` 为空时按 `op.student.course` 回退），在**停用前**就把「会影响到谁」摊开。
- **立刻生效**：停用后**学生课表与教师课表不再显示这些课时**。⚠ 这条**不是自动成立的**：门户课表路由 `/student/timetable`（学生与教师**共用同一路由**，`custom_addons/edu_portal/controllers/scheduling.py:78-153`）原先**没有** `state != 'cancel'` 过滤（校历 / ICS / 学习页都有，只有课表页漏了）⇒ 本期补上（最小面改动，见 §18.7）。
- **不做**：不在批量停用时**自动群发通知**（本期只做「影响面提示」；通知仍走 C-1 的**逐节**「通知相关师生」入口，避免一次误点给全班发信）。

### 18.4 与原设计的冲突 / 作废清单（**逐条可查**）

| 原结论位置 | 原文结论 | 本期处置 |
|---|---|---|
| §0 待校长拍板 / §14 **P2** | 「哪个班」代表学生的课 → ① 学生挂排课班 ② 新建班-班归属（**推荐方向**）③ 排课时按行政班各排一份（**数据×N、且与四查冲突**） | **P2 由校长以裁定取代**：方向改为 **③ 按年级各排一份**。§14 P2 的**推荐 ② 降级为备选**（重新考虑触发条件见 §18.4 末行）；P2 选项 ③ 描述里的「**且与四查冲突**」一句**作废** —— 错开即无冲突（§18.2 + §18.3 能力 A） |
| §7.6 | 三个候选方向 + 「建议方向 **2**；本期只登记，不实施」 | **候选 ③ 取代 ② 成为本期方向**；§7.6 原文保留在案作为历史记录。**仍不新建「班-班归属」字段**（§6.4 台账行不变） |
| §6.4 台账行「合班 ↔ 档案班归属 \| 本期不新建（只登记 + 看板暴露）」 | 不新建，靠看板暴露 | **不新建这一半不变**；但**处置路径变更**：从「只在看板上暴露」升级为「**用工具按年级重排 + 停用旧合班课时**」 |
| §6.3 第 ② 条结构断点 | 学生挂 B1、真实课挂合班批 ⇒ 即便排完课，B1 学生也只看得见 B1 自己的 18 节 | **结论本身仍成立（是事实，不撤）**；但**成因被削弱**：按年级重排后课会落在**年级班**上，学生的档案班与排课班**重新对齐** —— 王佐那类看不见课的问题在**排课侧**被绕开（**报课侧**的 §7 设计不受本节影响，仍按原样） |
| §1.2 非目标 | 不做求解器 / 不做拖拽排课 / 不改基座 / 不碰 `edu_telegram` | **全部不变**：本节**没有**引入算法（时间是**教务给的**，系统只做顺延 + 预检），**没有**改 `openeducat_erp/`（只复用其判据） |
| §8.1 「三类提示（冲突 / 受限 / 异常）」 | 一类冲突 + 三类受限 + 新增数据异常 | **不变、且被本节复用**：多班预检**沿用同一套格状态与判词**（§18.3 能力 A），**未新增色板** |
| §13 验收清单 V1–V19 | 排课改造的验收口径 | **继续有效**；本节**追加** V20–V25（§18.6），**不替换**任何原条目 |
| **作废项（明确）** | —— | ① 「脚本拆合班课时」这条路**作废**（§18.2 判据：教师维硬约束）；② §14 P2 选项 ③ 括号里的「且与四查冲突」**作废**；③ 「排课工具只支持单班」这一**功能前提作废**（本期新增多班） |
| **备选复活条件**（② 班-班归属） | —— | 出现**跨系合班**（如 `A123B234`）且教务不愿按年级重排、或学生需要同时属于多个排课班 ⇒ 重新评估 ②；本期不立项 |

### 18.5 生产「合班批 → 组成年级」映射表（**推导值，供人工确认，不得当事实用**）

> 批名 / 代号**自己编码了组成**（`B1234` 的批名就是「B1-B4全体」），因此映射**可从代号推导**；
> 但**推导 ≠ 事实** —— 下表**必须由教务/校长过目确认**后才可当作重排依据；工具里以**同样口径**展示并标注「推导，需人工确认」，**不静默套用**。

**① 九个合班批（生产 19 个启用班级中的合班类）**

| 合班批（`op.batch.name`） | 代号 `code` | 推导组成（年级班） | 生产课时数 |
|---|---|---|---|
| B1-B4全体 | `B1234` | B1、B2、B3、B4 | **18** |
| B3+B4合班 | `B34` | B3、B4 | **27** |
| B2+B3+B4合班 | `B234` | B2、B3、B4 | **15** |
| A1+A2+A3合班 | `A123` | A1、A2、A3 | **23** |
| A123+B34合班 | `A123B34` | A1、A2、A3、B3、B4 | **11** |
| A123+B234合班 | `A123B234` | A1、A2、A3、B2、B3、B4 | **12** |
| A123+B1合班 | `A123B1` | A1、A2、A3、B1 | **15** |
| A23+B34合班 | `A23B34` | A2、A3、B3、B4 | **12** |
| A2+A3合班 | `A23` | A2、A3 | **6** |
| **合班批小计** | | 9 个批 | **139** |
| 非合班批（A1 4 + B1 18 + B3 40 + B4 15） | | 4 个批 | **77** |
| **合计（= 生产 `op_session` 全量）** | | **13 个批有课时** | **216** |

**② 按科目看：哪些科目落在合班批上（= 需要按年级重排的科目清单）**

| 科目 | 挂的批 | 课时数 | 推导需拆成的年级数 |
|---|---|---|---|
| 英语 | `B1234` | 18 | **4**（B1 / B2 / B3 / B4） |
| 使徒行传 | `A123B34` | 11 | 5 |
| 基督教与文学经典选读（二） | `B234` | 15 | 3 |
| 基督教与法律导论 | `A123B234` | 12 | 6 |
| 课程设计实务 | `B34` | 18 | 2 |
| 圣约神学 | `B34` | 9 | 2 |
| 神论 | `A123` | 6 | 3 |
| 救恩论 | `A123` | 5 | 3 |
| 逻辑一 | `A123B1` | 15 | 4 |
| 护教学基础 | `A23B34` | 12 | 4 |
| 讲道法 | `A23` | 6 | 2 |

> 口径说明：`A1/A2/A3` 与 `B1/B2/B3/B4` 是**两套年级命名**（A = 神学系年级、B = 人文系年级），批名里字母混用即**跨系合班**。
> 生产 19 个启用班级中，`A2`（神学二年级）、`A3`（神学三年级）、`B2`（人文二年级）**当前 0 课时**（需要新排）；其余 4 个非合班批已有课时。
> 全库 216 条课时的 `state` **全部为 `draft`**（无 `cancel`）⇒ 停用前它们**全部参与冲突检测**（§18.2 判据 3 的 `state != 'cancel'` 过滤对它们不起作用）。

### 18.6 本节新增的验收口径（**追加**，不替换 §13 的 V1–V19）

| # | 断言 | 判据 |
|---|---|---|
| **V20** | 多班批量排课的**时间错开** | 对 4 个年级班排同一科目 ⇒ 生成 **4 组课时**，且**任意两条的时间区间不相交**（逐条列出时刻为证） |
| **V21** | **反例被拒**（预检真的在拦） | 故意让两个班时段重叠（每班顺延 = 0）⇒ **整批被拒**，提示是**中文人话**（不是基座的英文 `ValidationError`，也不是数据库报错） |
| **V22** | **批量停用 = 只改状态** | 停用某班全部课时后：`op_session` **行数不变**、目标批 `state != 'cancel'` 计数 = **0**、`state = 'cancel'` 计数 = 停用数 |
| **V23** | **停用立刻对师生不可见** | 停用后 `/student/timetable`（学生身份按 batch 过滤、教师身份按 faculty 过滤）**不再返回**这些课时 |
| **V24** | **审计留痕** | `edu.audit.log` 新增一条 `课节批量停用`，含 `res_name` = 班级名、明细含停用节数 |
| **V25** | **映射表可见** | 停用确认页 / 工具页展示「批名 → 推导组成」并**显式标注「推导，需人工确认」**（不得静默套用） |

§13.3 的「明确不允许的验收写法」**全部继续适用**（尤其：装载成功 ≠ 功能可用；不许只读代码就声称生效）。

### 18.7 实施落点（本期，已落地）

| 文件 | 改动 |
|---|---|
| `custom_addons/edu_schedule/controllers/main.py` | 新增多班计划构建（`_plan_multi`）、唯一冲突判据 `_slot_conflict_dims`（`_slot_conflicted` 改为它的薄封装，语义不变）、创建前硬预检；新增 `GET /timetable/batch/<id>/deactivate`（确认页）与 `POST /timetable/batch/<id>/deactivate/confirm`（执行） |
| `custom_addons/edu_schedule/models/session_ext.py` | 新增 `_batch_composition`（映射表：推导 + 需人工确认）、`_batch_deactivate_impact`（影响面，复用 C-1 收件人口径）、`deactivate_batch_sessions`（批量置 `cancel` + 审计留痕） |
| `custom_addons/edu_schedule/views/templates.xml` | 表单页：多班勾选 + 每班顺延 + 停用入口卡片；预览页：多班分组渲染（含冲突明细表，沿用 C-1 判词）；新增停用确认页模板 |
| `custom_addons/edu_portal/controllers/scheduling.py` | **最小面**：`/student/timetable` 的 domain 补 `('state', '!=', 'cancel')`（V23 的前置；原先只有课表页漏了这条） |
| `tests/smoke/` | 新增 `schedule_grade_split.py` 冒烟脚本（V20–V25 真机断言 + 演示数据自清理） |

**零新建承诺（本节部分）**：不新建模块；不新建业务模型 / 表；不新增 `op.session` 字段；不碰 `openeducat_erp/`；不碰 `custom_addons/edu_telegram/`。

---

## 19. 2026-10-13 拍板与交付范围（本轮）

### 19.1 拍板（§14 五项 → 用户裁定）

| 项 | 裁定 |
|---|---|
| **P1 报课池** | **`annotate`**：全列 + 红字「本学期未排课」+ 复选框禁选；`off` 保留为应急回退档（零回归开关）；`strict` 暂不启用 |
| **P2 班口径** | 沿用 §18 校长裁定「**按年级各排一份**」；**不新建班-班归属**（§18.4 的备选复活条件不变） |
| **P3 教师不可用可否被覆盖** | **可覆盖 + 自动留痕**（不强制写原因） |
| **P4 看板可见性** | **仅教务 / 管理员** |
| **P5 C-2 改课候选** | **本期不启动** |
| **本轮范围** | **四件全做**：G1 报课池 / G2 看板 / G3 预检查三类化 / G4 教师不可用 |

### 19.2 实施现状台账（2026-10-14 只读复核）

| 设计承诺 | 现状证据 | 判定 |
|---|---|---|
| **G1 报课池过滤 + 三档开关** | 池 = `edu_portal/controllers/enroll.py:155` + `models/major_track.py:154`；blockers 只来自先修/学分/容量（`enroll.py:159-163`）；`op.session` 在报课控制器里只出现一次（`enroll.py:125` 班级卡计数）；三档键全仓 0 命中；生产 `ir_config_parameter` 只有 `edu.enroll.deadline` | **零命中** |
| **G2 `/timetable/coverage`** | 全仓 `coverage` 0 命中；`edu_schedule/controllers/main.py` 路由只有 bulk/preview/create/deactivate/impact/notify | **零命中** |
| **G3 预检查三类化** | 格状态仍 5 档（`edu_schedule/controllers/main.py:531/537/545/551`，计数 `:578-579`）；判词仍两档（`models/session_ext.py:508-509`） | **零命中** |
| **G4 教师不可用（F-1）** | `resource_id` / `resource.mixin` / `/my/availability` / `_leave_intervals_batch` 全仓 0 命中；`op.faculty` 无 resource（`openeducat_erp/openeducat_core/models/faculty.py:26-36`）；生产 `op_faculty` 无 `%resource%` 列、`resource_calendar_leaves` = 0 | **零命中** |
| **G5 人工排课路径** | 三步流在（`main.py:721/755/791`，多班 `:654 _build_plans_multi` / `:838 _create_multi`）；导入线三件 + `timetable_import/PRODUCTION_CHECKLIST.md:37-47` 在；**缺「覆盖核对」= 就是 G2** | **部分** |
| **§18 能力 A/B** | A：`main.py:332 _slot_conflict_dims` / `:654` / `:838`；B：`main.py:895/923` + `models/session_ext.py:843 _deactivate_composition` / `:903` / `:965` + `views/templates.xml:990/1033-1042`；`tests/smoke/schedule_grade_split.py` 在 | **已实现**（commit `1ec787f`） |

- **文档订正**：§18.7 的方法名与代码不符（写 `_plan_multi` → 实为 `_build_plans_multi`；写 `_batch_composition` → 实为 `_deactivate_composition`）；`docs/audit/deprecated-inventory.md` §8 **从未登记 §18**（grep `合班|各年级|1ec787f` = 0 命中）。
- ⚠ **生产读数漂移（2026-10-14 实测）**：`op_session` **216**（全 `draft`；`classroom_id` 非空 **0/216**；`faculty_id` 全 = `20`「待定」）；`op_batch` **12 启用**（**9 个合班批全部不存在**）；**139 节全挂 `id=34 code=OVERVIEW 总览班`**；`op_faculty` 1 行；`op_classroom` 3；`resource_calendar_leaves` **0**；`op_student_course` **45**；有在读学生的班 **9**。
  ⇒ **§18.5 的「合班批 → 组成年级」映射表在生产上已无对应批**（停用工具页按 `session_ext.py:828-835` 的自述会显示「未推导出组成」——这是**预期内的降级**，不是 bug）；**§6 / §18.5 的旧读数（19 启用班 / 9 合班批 / 1 个有学生的班）已过期，不得再当结论用。**

### 19.3 本轮分工与文件边界（三批，文件集互不重叠）

| 批 | 范围 | 拥有的文件 | 禁改 |
|---|---|---|---|
| **S1** | G3 预检查三类化 + G4 拦截侧与数据侧（`op.faculty` 接 `resource.mixin` + 存量回填 + 后台「教师不可用时间」视图 + 预览/落库/改课拦截 + 逃逸口） | `edu_schedule/controllers/main.py`、`edu_schedule/models/session_ext.py`、`edu_schedule/models/faculty_ext.py`（新）、`edu_schedule/models/__init__.py`、`edu_schedule/views/templates.xml`、`edu_schedule/views/availability_views.xml`（新）、`edu_schedule/__manifest__.py`、`scripts/migrations/`（新迁移） | `edu_portal/**`、`edu_schedule/controllers/coverage.py`、`edu_schedule/views/coverage.xml` |
| **S2** | G2 排课完成度看板 | `edu_schedule/controllers/coverage.py`（新）、`edu_schedule/views/coverage.xml`（新）、`edu_schedule/views/menu.xml` | `edu_schedule/__manifest__.py`（由 S1 登记，见任务书）、其余全部 |
| **S3** | G1 报课池 + 审批页 M/N + G4 教师自助页 | `edu_portal/controllers/enroll.py`、`edu_portal/views/roles.xml`、`edu_portal/views/enroll.xml`、`edu_portal/controllers/availability.py`（新）、`edu_portal/views/availability.xml`（新）、`edu_portal/controllers/__init__.py`、`edu_portal/__manifest__.py` | `edu_schedule/**`、`edu_portal/controllers/main.py`、`edu_portal/controllers/roles.py`（除本批明确点名的块）、`edu_portal/controllers/scheduling.py` |

### 19.4 验收（§13 V1–V19 + §18.6 V20–V25）

- 真机探针 = 新建 `tests/smoke/p1_scheduling_gate.py`（**调度者写**），覆盖 V4–V16；V17–V19 用既有门禁；V20–V25 由既有 `tests/smoke/schedule_grade_split.py` 承担。
- 探针必须遵守 §13.3 的四条反例禁令（不跟随重定向、不在空载体上验收、装载 ≠ 可用、claim 与证据同级）。

### 19.5 实测与口径订正（2026-10-14，本地 edu19-clone）

**验收读数**：`tests/smoke/p1_scheduling_gate.py` **52/52 PASS**（结果 `tests/smoke/p1_scheduling_gate_results.json`），跑完自还原：`op_session` 288、`resource_calendar_leaves` 0、`edu.enroll.pool_mode = annotate`。关键证据：

| 段 | 读数 |
|---|---|
| V10 教师自助登记 | `leaves` 0→1，`resource_id`=9，时段 UTC 02:00–04:00（本地 10:00–12:00）|
| V11 落库硬拦 | 预览 200 且格位 `title` 命中「教师不可用·自动排除」；POST create → 303 `created=0&failed=1&error_msg=…已登记不可用时间…`，`op_session` 288→288 |
| V12 逃逸口 | `ignore_teacher_leave=1` → `created=1`，288→289，审计两条（「批量排课」+「忽略教师不可用」）|
| V13 `op.session.write` | 改到不可用时段 ⇒ ERROR 含「已登记不可用时间」，原时段不变 |
| V14 误拦反例 | 19:15–21:15（本地）允许创建 ⇒ 未把晚课误判为不可用 |
| V15 冲突/待补分级 | 冲突判词「与既有课时冲突」；未指定教室只给黄字待补，**不出现**「不能生成」|
| V8/V9 看板 | 与 SQL 对拍一致（窗口 2026-06-22 16:00Z–2026-12-20 16:00Z，教室填写 11/N）；学生/家长 303 `/my/home`，教务组 implied 不含 `group_system` |
| V4/V5 G1 报课闸门 | 未排课科目卡红字「不可报：本学期未排课」；绕过前端提交零落库；`off` 档零回归 |
| G1-c 设置页 | `/edu/enroll/pool_mode` 200；三档语义全文；`off`↔`annotate` 各 303 `?box=saved` 且 psql 前后相符；非法值 303 `?box=bad` 不写库；学生/家长/教师 GET+POST 全 303 |
| V16 残留 | 探针口径【演示】leave 残留 0；`op_session`/报课行回到基线 |

**口径订正（原文有误，按实测改）**：
1. §7.4/§19 原写闸门回跳参数 `box=precheck` —— 实际是 `box=overdue` / `compulsory_no_session&n=N` / `all_no_session`（`edu_portal/controllers/enroll.py`）。
2. §13 V18「学生访问 `/my/availability` 应 303」—— 实测**无 `op.faculty` 档案的身份一律 303 `/my/home`**（学生/家长/教务都 303；只有真教师 200）。判据：`op_faculty` 7 行 partner 与任何登录账号都不相交，教务 `backoffice@local`（partner 49）不在其中 ⇒ 教务也 303 是**设计意图**，不是缺陷。
3. §10.1 的挂载方案**未采用 `resource.mixin`**，走回退分支（只加 `resource_id` 列 + `_get_or_create_resource()`）。原因（源码级）：`odoo/orm/model_classes.py:480-505 _add_inherited_fields()` 的 `if name not in model_cls._fields` 守卫会让 mixin 的 `company_id`（related `resource_id.company_id`）占住字段名，从而**停掉 `_inherits={'res.partner': …}` 的 company_id 委派** ⇒ 多公司语义被破坏。回填与委派校验见 `scripts/migrations/backfill_faculty_resource.py`（默认 dry-run，`BACKFILL_CONFIRM=1` 才写；实测本地 7 行回填、`[断言] 通过：op.faculty.company_id 仍委派 res_partner.company_id`）。
4. G1 档位读取：**不得用 `ir.config_parameter.get_param()`**（`@ormcache(cache='stable')` 是 per-worker 缓存 ⇒ 网页改档位只有处理该请求的 worker 生效，其余 worker 读旧值）。`edu_portal/controllers/enroll.py:edu_pool_mode()` 改为直读参数表（失败回落默认档）；判据出处 `custom_addons/edu_portal/models/course_rep.py:71-90`。

**新立的门禁（事故产物）**：`scripts/check_view_selector_attrs.py` —— 2026-10-14 首次升级因 `custom_addons/edu_portal/views/roles.xml` 的 `<xpath expr="//div[@aria-label='周导航']">` 直接 `ParseError: View inheritance may not use attribute 'aria-label' as a selector.`（view 3837 / xmlid `edu_timetable_availability_btn`）整批回滚；已改为 `//h4[hasclass('mb-0')]`，并立此门禁（规则见 `docs/code-map.md` §6 第 20 条）。

**仍挂起**：§18.5 的合班批映射表在生产已无对应批（12 个启用班里 9 个合班批不存在，139 节挂 `id=34 OVERVIEW 总览班`）；`op_holiday` 表不存在 ⇒ V15② 停课日无载体，本轮跳过。

