# 排课方法调研（成熟系统到底怎么做）

> **铁律 0 产物**（CLAUDE.md 铁律 0 / docs/dev-workflow.md 六步闸门第 2 步）。
> 触发问题（用户原话）：「我总觉得咱们这种排课的方式很麻烦，网上先进的排课方法是什么样的？」
> **本文件只做调研，不含实现**；不改任何代码。
> **取证时间**：2026-09-17。本机源码引用一律带分支/commit 口径；上游文档一律给 URL。

**一句话结论**：成熟系统里，「先进」不是一个算法，而是**四个各自独立的层**——
① **求解器层**（把"排课"变成约束优化，要么用 MIP/matheuristic 上算力，要么用局部搜索启发式换性价比）；
② **数据模型层**（把「教师可用时间 / 偏好 / 房间容量 / 班级结构」这些**约束源**变成一等数据，而不是排课时靠人脑记）；
③ **交互层**（网格/表格 + 预检查冲突 + 双击即建 + 高亮对向 + 最小扰动改课建议——**这才是用户说"麻烦"的那一层**）；
④ **选课层**（志愿优先 / 抽签 / 先到先得三选一，它们对并发和公平性的影响完全不同）。
我们现在**四层里只有第 ①层的最粗糙版本（人工填 + 四类冲突检测）**，而**第 ③ 层几乎为零**——这正是"麻烦"的来源。

---

## 0. 结论速览

| 层 | 成熟做法 | 代表实现（一手来源） | 我们现在的状态 |
|---|---|---|---|
| 算法 | 三种流派并存：**MIP/matheuristic**（竞赛冠军，吃算力）、**局部搜索启发式**（生产系统，性价比高）、**元启发式 SA/GA**（大面积探索，硬约束多时弱） | [ITC2019 论文](https://link.springer.com/article/10.1007/s10951-023-00801-w)、[UniTime CPSolver](https://www.unitime.org/index.php?tab=1) | 无求解器；人工填 + 服务端四查拦截 |
| 算法 | **官方 OR-Tools 里没有排课示例**（只有班次/机位/单机调度）；CP-SAT 只吃整数 | [examples/python](https://github.com/google/or-tools/tree/stable/examples/python)、[CP-SAT 文档](https://developers.google.com/optimization/cp/cp_solver) | — |
| 开源软件 | **FET**：AGPLv3、全自动生成、**每条约束带 0–100% 权重**、巨大约束调色板 | [fet/features.html](https://lalescu.ro/liviu/fet/features.html) | 未评估过（AGPL 需评估传染） |
| 开源软件 | **UniTime**：Apache-2.0 仓库；核心卖点是**课程结构模型 + 学生分班 + 场景模拟**，改课走**交互式求解器**（建议"只影响 ≤2 个其他班"的方案） | [help.unitime.org/course-timetabling](https://help.unitime.org/course-timetabling) | 未采纳 |
| 开源软件 | **OCA 没有排课可抄**：`vertical-education` 19.0 分支**零个模块目录** | [GitHub API 19.0 目录](https://api.github.com/repos/OCA/vertical-education/contents/?ref=19.0) | — |
| 商业软件 | aSc / Untis / TimeTabler 的卖点高度一致：**自动生成 + 代课（替换课）管理 + 移动端/发布** | [aSc](https://www.asctimetables.com/)、[Untis Substitution](https://www.untis.at/en/products/untis-basic-software/substitution-planning-1) | — |
| LMS | **Moodle 与 Canvas 都不做排课**：没有时间片实体；时间是"日历/截止日"，不是"课表格" | [Moodle mod/](https://api.github.com/repos/moodle/moodle/contents/mod?ref=MOODLE_405_STABLE)、[Canvas app/models](https://api.github.com/repos/instructure/canvas-lms/contents/app/models?ref=master) | — |
| 国内 SaaS | 培训机构侧（校管家/ClassIn/学邦/排课宝）**在交互层最值得抄**：表格排课、对比排课、循环规则批量生成、老师日程=不可排时间 | [校管家·表格排课](https://wiki.xiaogj.com/docs/biao-ge-pai-ke) | 我们有"预览 + 批量生成"，但没有格子、没有高亮、没有日程 |
| 国内 SaaS | 钉钉/企微/飞书**没有原生排课内核**，靠文档模板 / 多维表格 / 第三方应用 | [飞书社区《老师排课表》](https://www.feishu.cn/community/article?id=7400988057966477316) | — |
| 选课 | 中国高校事实标准是**"预选（志愿优先，超容量抽签）→ 正选（即选即得）"两轮**，且**明确告知"筛选与选课时间先后无关"** | [西电教务处](https://jwc.xidian.edu.cn/info/1012/23283.htm)、[西北大学教务处](https://jwc.nwu.edu.cn/info/1034/11158.htm)、[上海交大教务处](https://jwc.sjtu.edu.cn/info/1222/126721.htm) | **没有选课层**（只有班级预注册） |

---

## 1. 先定"什么叫先进"：我们的现状（判据基准）

来源：本仓源码与设计文档（不引外部）。

| 项 | 现状 | 出处 |
|---|---|---|
| 数据模型 | 绝对起止时间的课时实体 `op.session`；`op.timing`（第 N 节）、`op.classroom`、`op.faculty`、`op.batch`、班级科目 | `openeducat_erp/openeducat_timetable/models/` |
| 基座已有的向导 | `wizard/generate_timetable.py`（`generate.time.table`）：按 课程+班级 展开 **7 条日线网格** | `openeducat_erp/openeducat_timetable/wizard/generate_timetable.py` |
| 基座冲突门控 | 四个 `ir.config_parameter`：`timetable.is_faculty_constraint` / `is_classroom_constraint` / `is_batch_constraint` / `is_batch_subject_constraint`，**默认只随 demo 数据播种**（本库无 demo → 我们以 `noupdate=1` 固化开启） | `openeducat_timetable/models/res_config_setting.py`；`docs/plans/timetable-design.md` §二.4 |
| 我们的批量排课 | `/timetable/bulk` → `/preview`（不落库）→ `/create`（循环建 `op.session`）；周次范围 / 单双周 / 整周复制 | `custom_addons/edu_schedule/controllers/main.py` |
| 冲突可视化 | `edu_schedule` 只读计算字段 `conflict_kind` / `conflict_color`，日历事件按 0–3 整数色板着色（教师红 / 教室橙 / 班级琥珀） | `custom_addons/edu_schedule/models/session_ext.py`、`views/session_conflict_view.xml` |
| 并发兜底 | 事务级 `pg_advisory_xact_lock` 串行化 `op.session` 写 | `docs/plans/timetable-design.md` §二.3 |
| 明确砍掉的 | 批量生成向导（v2 再评估）、企业版 `planning` 的 resource/发布流/自动派班 | `docs/plans/timetable-design.md` §二 |
| **没有的** | 拖拽排课、格子视图、教师可用时间/日程、代课/换课、模板、学生选课（志愿/抽签）、任何求解器 | 全仓搜索结论（见 §6/§7） |

**判据**：下面每节的"先进"都以**"能不能减少教务的手工操作次数"**为准绳，而不是以"算法是否时髦"为准绳。

---

## 2. 算法层：高校排课问题（UCTP）到底怎么解

### 2.1 基准赛说明了什么（最重要的一手来源）

**ITC2019（第四届国际排课竞赛）** —— 组织者论文开放获取：
<https://link.springer.com/article/10.1007/s10951-023-00801-w>（Journal of Scheduling，2023）

从论文中可直接核实的结论：

1. **赛事模型的关键新意 = 把"学生分班（student sectioning）"和"时间/教室分配"放在同一个问题里**。
   原文：*"The key novelty lies in the combination of student sectioning with standard time and room assignment of particular course events."*
   → 这正是我们场景的痛处：**班级/学员归属**和**时间/房间**必须一起算，分开算会互相打架。

2. **30 个实例、来自 10 所真实大学**，全部由 **UniTime 生产环境数据**匿名化导出（四届以来最贴近实战的一届）。
   原文明示实例来自 Masaryk University、AGH、Purdue、Maryville、Bethlehem University 等。

3. **冠军是 matheuristic（数学启发式）**：fix-and-optimize + **Gurobi MIP**，并行多配置、共享当前最优；分班单独一阶段处理。
   论文记录其算力需求：**756 GB RAM**、双 CPU（各 16 核）。
   → **"最好的解"是靠堆算力堆出来的，不是靠某个聪明算法。**

4. **亚军也是 MIP**（Rappos 等，IBM CPLEX，子问题削减 + 逐步注入约束）；他们只在受限算力下（单核 / 4 GB / 2 小时）跑。

5. **UniTime 自带求解器（组织者 Tomáš Müller）在"当前最好结果"里升到第二，且算力需求最优**：**每次运行 2 小时、4 GB 内存**。
   论文原话：*"the UniTime-based solver is superior, providing results within 2 h and using 4 GB of memory per solver run. All other solvers needed much longer runtime and memory."*
   它的构成（论文）：构造式学生分班 → **iterative forward search（带 conflict-based statistics）** → **爬山（hill climbing）** → **great deluge**。

6. **模拟退火（SA）在硬约束强的地方明显弱**：*"The metaheuristic methods are naturally stronger in approaching the optimization than the satisfaction component... it is also reflected by the SA solver, whose performance is weaker when there is a high number of hard class pairs (or high utilization), showing a weaker performance in constraint satisfaction."*
   → **硬约束（不许冲突）优先，软约束（尽量满意）其次**；SA/GA 这类元启发式擅长后者、不擅长前者。

7. **MaxSAT 类求解器在"学生冲突权重大"的实例上相对弱**（论文 §comparison）。

> **对我们的直接含义**：我们不缺"世界第一的算法"，我们缺的是**"把硬约束表达出来 + 给出可解释的备选方案"**。UniTime 那条路线（启发式 + 人工可介入）才是我们这个体量该看的。

**ITC2011（第三届）** <https://www.utwente.nl/en/eemcs/dmmp/hstt/itc2011/>，结果 PDF：
<https://www.utwente.nl/en/eemcs/dmmp/hstt/itc2011/results/ResultsITC2011.pdf>
- 该届**专注"中学排课（High School Timetabling）"**，用 **XHSTT-2012** 格式的 XML 实例，**三轮**：第 1 轮不限时间资源、**第 2 轮限时 1000 秒**、第 3 轮用提前公开的隐藏集。
- 官方组织者报告（Annals of OR）：<https://link.springer.com/article/10.1007/s10479-013-1340-5>
- **"限时 1000 秒"这条赛道本身就是结论**：真实学校**要的是"几分钟内给一个能用的表"**，不是"三天后给最优表"。
  → 与我们教务的实际需求完全一致。

**ITC 系列的常设入口**：<https://www.itc2019.org/> —— 注意：该站是 Angular SPA，**正文由 JS 渲染，直接抓取只能拿到标题**（本调研实测 1117 字节、无正文），所以本文件的 ITC 结论一律以 **Springer 论文**为准，站点只作为赛事存在与 XML 数据格式的入口。（站点正文 = 未验证）

### 2.2 求解器技术路线：CP-SAT 到底能不能排课

**Google OR-Tools CP-SAT** 官方文档 <https://developers.google.com/optimization/cp/cp_solver>：
- CP-SAT **只对整数求解**；非整数约束必须**整体乘以一个足够大的整数**才能表达（原文 §"CP-SAT 求解器会针对整数进行求解…您需要先将这些约束条件乘以一个足够大的整数"）。
- 返回状态：`OPTIMAL / FEASIBLE / INFEASIBLE / MODEL_INVALID / UNKNOWN`（即**求解器自己能告诉你"无解"**）。

**但官方示例里没有排课。** 实测 `google/or-tools` `stable` 分支的 `examples/python` 目录
<https://github.com/google/or-tools/tree/stable/examples/python>：
- 含 `shift_scheduling_sat.py`、`gate_scheduling_sat.py`、`vendor_scheduling_sat.py`、`bus_driver_scheduling_sat.py`、`single_machine_scheduling_*.py`；
- **文件全名中含 "timetab" 的条目数 = 0**（本调研对目录清单做 `grep -c timetab` 得 0）。
→ 结论：**CP-SAT 是通用约束求解器，成熟用法是"班次/机位/单机"这类调度，排课要自己建模**。这与 CLAUDE.md 铁律 0 的精神一致：**官方没有现成答案，别指望抄一个 OR-Tools 排课包**。（社区有 3359 个 `timetabling language:python` 仓库，但都是个人项目、无生产级证据）

### 2.3 生产系统的实际选择：局部搜索 + 人工可介入

**UniTime CPSolver 1.3** <https://www.unitime.org/index.php?tab=1>（官方对求解器自身的描述）：
- *"The constraint solver library contains a **local search based framework**... The search is based on an **iterative forward search** algorithm."*
- **关键设计（也是最值得抄的一条思想）**：*"it operates over **feasible, though not necessarily complete, solutions**. In these solutions some variables may be left unassigned. All hard constraints on assigned variables must be satisfied however. **Such solutions are easier to visualize and more meaningful to human users than complete but infeasible solutions.** Because of the iterative character of the algorithm, the solver can also easily **start, stop, or continue from any feasible solution**."*
  → **"宁可少排几节课，也绝不排出冲突表"**，而且**随时可停、可续、可人工接手**。
- 框架内建 **"最小扰动问题（minimal perturbation problem）"** 动态支持——*"allowing the number of changes to the solution (perturbations) to be kept as small as possible"*。
- 战绩：ITC2007 三个 track 全部进决赛、**赢两个**。
- ⚠ **License 口径冲突**：该页面写 *"Open Source (GNU LGPL) license"*，但**仓库根 `LICENSE` 实际是 Apache License 2.0**
  （实测：`curl https://raw.githubusercontent.com/UniTime/unitime/master/LICENSE` 首行为 "Apache License / Version 2.0"；GitHub API `repos/UniTime/unitime` 返回 `license.spdx_id = Apache-2.0`）。
  → **引用时必须写清楚两处来源不一致，实施前以仓库 LICENSE 为准**。

### 2.4 图着色 / 遗传算法（这两个"教科书答案"的真实地位）

- **图着色启发式**是排课最早的建模方式（时间片=颜色，冲突=边）。经典起点是 **De Werra, D. (1985). "An introduction to timetabling." European Journal of Operational Research 19(2):151–162**，DOI <https://doi.org/10.1016/0377-2217(85)90167-5>（实测 DOI 解析 302 → Elsevier PII `0377221785901675`）。
  → 它的历史意义是"把排课抽象成图论问题"；**在 ITC2011/2019 的现代赛题里，纯图着色已不是竞赛级方案**（现代模型含"同一课程多次课次之间的关系""教师偏好"等，远超点着色）。
- **遗传算法（GA）**在文献中大量存在（如 `University Timetabling based on Hard Constraints using Genetic Algorithm`，IJCA <https://www.ijcaonline.org/archives/volume42/number15/5766-7964/>），但 **ITC2019 组织者论文描述的竞争性求解器里，元启发式一类只由"模拟退火"代表，且被明确指出在硬约束密集时表现弱**（见 §2.1 第 6 条）。
  → **"遗传算法排课"在竞赛与生产系统里都不是主流叙事**；把它当成"先进方案"是网络内容的误导。

---

## 3. 现成软件：能装不写（含 license）

### 3.1 FET (Free Timetabling Software) —— 约束表达最全的开源实现

一手来源：<https://lalescu.ro/liviu/fet/>（首页）、<https://lalescu.ro/liviu/fet/features.html>（功能表）

- **License：GNU AGPL v3**（首页与 features 页均写明）。⚠ 与 OCA 同级的**传染性风险**，装进 Odoo 需评估。
- **核心卖点 = 约束表达 + 全自动生成**：
  - *"Fully automatic generation algorithm, allowing also **semi-automatic or manual allocation**"*（自动 + 半自动 + 手工三种模式并存，不是"全有或全无"）
  - **每条约束都有 0.0%–100.0% 的权重**：*"Each constraint has a weight percentage, from 0.0% to 100.0%"*
    → 这是**软约束的通用表达法**，比"开关式硬约束"表达力强一整档。
  - **学生按集合组织**：*"Flexible students structure, organized into sets: **years, groups and subgroups**. FET allows overlapping years and groups and non-overlapping subgroups. You can even define **individual students** (as separate sets)."
    → 直接对应我们的"既有班级、又有学生自主选科"。
  - **巨大的约束调色板**（features 页逐条列出），摘几条与教务日常最相关的：
    - 教师：不可用时段 / 每周最多最少天数 / 每日每周最大空隙 / 每日最多连续课时 / 每日最大跨度 / 最小每日课时 / 最小休息小时
    - 学生集合：同上 + "early begins（限制第 2 节开始的次数）"
    - 活动：**首选开始时间 / 首选时段集合 / 彼此最小最大间隔 / 同一开始时间 / 不重叠 / 选定时段内最多最少同时数**
    - 空间：教室不可用时段 / 教师 home room / **每天每周最多换教室次数** / 换教室最小间隔 / 连续课同教室 / 最多占用不同教室数
  - 规模上限：每天最多 1440 小时、最多 500,000 个 activity、30,000 个教室、30,000 个学生 subgroup。
  - 输入是 **模块化 XML**（可用 XML 编辑器手改），支持 **CSV 导入导出**，输出 HTML/XML/CSV。
- **求解时间**（官方发布渠道 Microsoft Store 页面 <https://apps.microsoft.com/detail/9nk0vrpws1rf>）：*"Usually, FET is able to solve a complicated timetable in around **5-20 minutes**. For simpler timetables, it may take a shorter amount of time, **under 5 minutes**."*
- **交互层证据不足**：官方截图页 <https://lalescu.ro/liviu/fet/screenshots.html> 只给出分类链接集合，**未取到逐张截图说明** → 因此"FET 有没有拖拽排课"= **未验证**（不要当成结论）。

> **对我们的可取之处**：不是"装 FET"，而是**抄它的约束分类法与"权重"表达法**——把我们要表达的教务规则（教师不可用时段、每天最多连续几节、教室不换）做成**带权重的约束清单**，而不是四个布尔开关。

### 3.2 UniTime —— 高校侧功能最完整、改课体验最成熟的系统

一手来源：<https://www.unitime.org/>、<https://help.unitime.org/course-timetabling>、<https://help.unitime.org/>（文档站；实测可直连，无需代理）

- **项目归属**：**Apereo 基金会**项目 —— <https://www.apereo.org/programs/software/unitime>
  （*"UniTime offers a cost-effective solution for strategic planning, allowing institutions to handle schedule changes and model scenarios efficiently"*）
- **仓库**：<https://github.com/UniTime/unitime>（Apache-2.0，见 §2.3 的 license 口径冲突说明）
- **核心卖点（官方帮助文档原文级）**：
  1. **课程结构模型**：*"a very comprehensive course structure model that makes it easy to define the relationships between components of courses with **multiple types of instruction (e.g., lecture, discussion, laboratory)** and different meeting time requirements."*
  2. **学生冲突最小化有三档数据源**：*"Student course conflicts can be minimized based on either **actual student course demands, an established set of curricula, historical patterns, or a combination** of these data."*
  3. **场景模拟**：*"The course timetabling module can also be used to **test multiple scenarios**, such as the effect of fewer classrooms, or changes in course requirements."*
  4. **改课（=我们说的"换课/代课"）用交互式求解器**：
     *"Class changes after the timetable are published make use of an **interactive solver that suggests a limited size set of alternative time and/or room assignments**... Initially the solver looks for possible assignment changes which best fit all of the requirements and preferences set on classes while **not affecting the assignment of more than two additional classes**. The user can then select the set of changes which best meets his/her needs from among the options presented. **Each option provides information on any additional student conflicts created and any other preferences that would be violated.** If a solution affecting only two other classes is not possible, the search can be adjusted to allow additional changes. **Changes can be limited to allow room-only swaps, time-only swaps, or changes to both room and time.**"*
     → **这是"少手工"的最高级形态：不是替你排，而是把"改一节课要连带改哪几节"的搜索替你做完，并把代价摊开给你选。**
  5. **教师可用时间与偏好是硬/软约束的一等公民**：UniTime 4.2 起的 **Instructor Scheduling** 组件 <https://help.unitime.org/instructor-scheduling>：
     - 硬约束含 *"The instructor must be available (unless allowed, there is no other overlapping teaching assignment, the assignment is not during a **prohibited time** and, if the instructor is also student, he/she does not have any classes at the time of the assignment)"*
     - 软约束含 *"Maximize the number of satisfied **soft preferences** (strongly preferred, preferred, discouraged, or strongly discouraged) based on teaching, time, attribute, instructor, course preferences..."*
     - 以及 **MPP（Minimal Perturbation Problem）模式"最大化保留原分配"**。

### 3.3 OCA：**负结论——完全没有排课/课表模块可抄**

- **`OCA/vertical-education` 19.0 分支实测**：<https://api.github.com/repos/OCA/vertical-education/contents/?ref=19.0>
  返回的条目**只有仓库脚手架**：`.copier-answers.yml`、`.editorconfig`、`.gitattributes`、`.github`、`.gitignore`、`.pre-commit-config.yaml`、`.pylintrc`、`.pylintrc-mandatory`、`.ruff.toml`、`LICENSE`、`README.md`、`checklog-odoo.cfg`、`eslint.config.cjs`、`prettier.config.cjs`。
  → **零个模块目录**（与仓库内 `docs/research/fee-categories.md` 对 18.0 的结论一致，此处扩展到 19.0）。
- **License：AGPL-3.0**（GitHub API `repos/OCA/vertical-education` → `license.spdx_id = AGPL-3.0`）→ **传染，本仓不可用**。
- **GitHub 组织级搜索**（实测）：
  - `org:OCA timetable` → **total_count = 0** <https://api.github.com/search/repositories?q=org%3AOCA+timetable>
  - `org:OCA schedule` → **total_count = 0** <https://api.github.com/search/repositories?q=org%3AOCA+schedule>
  - `org:OCA education in:name` → **total_count = 1**（就是那个空的 vertical-education）
  - `org:OCA calendar` → 1 个 `OCA/calendar`（AGPL-3.0），与排课无关。
→ **在 OCA 这一层，"无先例"是结论，可以放心自研。**

### 3.4 Odoo 生态的其他排课模块（"能装不写"的最后一站）

- **GitHub 搜索 `timetable in:name odoo` → 总共 4 个仓库** <https://api.github.com/search/repositories?q=timetable+in%3Aname+odoo>：

  | 仓库 | License | Star | 描述（原文） |
  |---|---|---|---|
  | `BLLAKO/Odoo-School-Timetable` | **MIT** | 18 | "Module in Odoo for automating and printing school timetables." |
  | `syedafham-rgb/openeducat_timetable_substitution-odoo19` | 无 | 0 | （空描述） |
  | `Akshay-cp7/odoo_upto_timetable` | 无 | 0 | "no timetable , everything else" |
  | `drbr-odoo/academic-timetable` | 无 | 0 | （空描述） |

  → 除第一个外**都无 license、零 star**，不能作为依赖。

- **Odoo Apps Store 搜索 `timetable`** <https://apps.odoo.com/apps/modules/browse?search=timetable>：
  结果里**大多数是 HR 排班（shift）**，与教学排课同名的只有教学类商业模块：
  `OpenEduCat Timetable`、`Openrol - Timetable`、`School Timetable`（"Weekly class timetables"）、`Timetable Portal`、`Timetable for Education erp`、`Student Timetable`（"Manage Students Timetable"）、以及打包进 "University Management System"（"Curriculum, timetable, attendance, examinations, results and transcripts"）的那套。
  → **都是"课表展示/管理"，没有一家敢宣称竞赛级自动求解**（商业模块页面无算法披露）。

- **我们脚下已有的**：`openeducat_erp/openeducat_timetable`（LGPL-3，19.0 分支快照）已含
  `wizard/generate_timetable.py`（`generate.time.table`：课程 + 班级的七日线网格向导）与四个冲突开关
  `res_config_setting.py` 的 `is_faculty_constraint / is_classroom_constraint / is_batch_constraint / is_batch_subject_constraint`。
  → **基座其实已经有一个"网格式批量生成向导"，我们的 `edu_schedule` 是绕开它在门户重做了一遍**。这一条值得在设计层复核。（见 §9 建议 1）

### 3.5 商业软件：三个卖点几乎完全一致

| 产品 | 定位 | 核心卖点（一手来源原文/摘要） | 来源 |
|---|---|---|---|
| **aSc TimeTables** | K-12 全日制学校 | "**Automatic generation**... evaluate over 5,000,000 possibilities"；"you can spend days doing manual work - or you can use aSc TimeTables that can do the same work in **5 minutes**"；**Substitution 模块**"input the absentees... **advise the best cover teacher - but you are free to choose your own candidate**"；"**Move/split or join lessons**"；变更自动进 class register 与 calendar；含 **AI modul**、Cloud generator、Mobile application | <https://www.asctimetables.com/>、帮助目录 <https://www.help.asctimetables.com/text.php?id=231&lang=en>、手册 <https://help.asctimetables.com/pdf/asc_timetables_en_P1.pdf> |
| **Untis / WebUntis** | 学校（"all school types"） | 模块名本身就是卖点清单：**Multi-week timetable / Substitution planning / Break supervisions / Calendar and full year planning / Course scheduling / Department timetable**；代课：*"The module most used worldwide supports you with powerful tools for substitution control, standby planning, events, **swaps**... The Substitution planning module provides you with **solution suggestions with only one click**... You instantly see who among the teachers is **available**... who teaches the **subject**... who already **knows the class**... Just one click and you see if other periods can be held earlier"* | <https://www.untis.at/en/products/webuntis>、<https://www.untis.at/en/products/untis-basic-software/substitution-planning-1>、<https://www.untis.at/en/products/webuntis/online-substitution-planning> |
| **TimeTabler**（英国） | 学校 / MATs | "I can now create a better timetable in **less time**"；配套 **Options (Electives)**、**StaffCover**、**TOOLS online System**、**Links to MIS**；有 Gold-Start 与培训体系 | <https://www.timetabler.com/>、<https://www.timetabler.com/our-products/timetabler/>、<https://www.timetabler.com/products/options/> |
| **排课宝**（国内） | 学校 + 培训机构 | "AI 驱动，自动解决教师冲突、教室冲突与时间冲突"；"基于 AI 约束求解算法，在**毫秒级**时间内自动生成…支持千人规模学校"；"**实时检测**教师、教室、班级、时间段的多维度冲突，**提前预警并给出修复建议**"；"AI 生成初版课表后，支持**拖拽微调**，系统**实时验证合规性**" | <https://paikebao.com/>、<https://www.paikebao.com/features.html>（**厂商宣传语，非技术披露，不作为技术结论**） |

**共同结论（三家一致）**：商业排课软件真正卖的不是"生成"，而是
**① 自动生成初版 → ② 人工微调的可视化网格 → ③ 日常改课/代课的搜索与建议 → ④ 发布到教师/学生/家长（含移动端）**。
其中 ③ 是**使用频率最高、最能省人工**的一层，而我们现在一层都没有。

**Untis 官方 API**（说明它有平台化能力，可作集成参考）：
<https://developer.untis.com/api-reference/webuntis-apis/>、教师缺席管理用例 <https://developer.untis.com/api-reference/webuntis-apis/teacher-absence-management/>
（"Use cases: **Substitution planning** — Identify substitution needs based on teacher absences."）
⚠ `help.untis.at` 帮助中心被 Cloudflare 拦截（实测返回 "Just a moment..."）→ **其帮助中心正文 = 未验证**。

---

## 4. LMS 侧：Moodle / Canvas 是怎么做的（源码级取证）

> 之所以必须看这一层：我们将来会与 LMS 打通（站内信、作业、出勤），**必须知道 LMS 的边界在哪**。
> ⚠ 取证方式说明：`docs.moodle.org` 与 `moodle.org/plugins` **实测被 captcha 拦截**（页面标题 "Moodle challenge"），因此本节**一律读 GitHub 源码**，不用官方文档站。

### 4.1 Moodle 4.5（GPL-3.0，<https://github.com/moodle/moodle>，默认分支 `main`；本节取 `MOODLE_405_STABLE`）

1. **活动模块清单**（`mod/`，实测 API）：
   `assign, bigbluebuttonbn, book, chat, choice, data, feedback, folder, forum, glossary, h5pactivity, imscp, label, lesson, lti, page, quiz, resource, scorm, subsection, survey, url, wiki, workshop`
   → **没有 timetable / timeslot / schedule / calendar 活动模块**。
   来源：<https://api.github.com/repos/moodle/moodle/contents/mod?ref=MOODLE_405_STABLE>

2. **区块清单**（`blocks/`）里与"时间"有关的只有三个：
   `calendar_month`、`calendar_upcoming`、`timeline`
   → **Moodle 的"时间"是日历 / 截止日 / 时间线，不是"课表格"。**
   来源：<https://api.github.com/repos/moodle/moodle/contents/blocks?ref=MOODLE_405_STABLE>

3. **`admin/tool/` 下没有任何排课工具**（含 analytics、policy、task、uploadcourse、xmldb 等 39 项）。
   来源：<https://api.github.com/repos/moodle/moodle/contents/admin/tool?ref=MOODLE_405_STABLE>

4. **Moodle 唯一的"限额选择"原语 = `mod_choice`**：
   `lib.php` 实测含 `limitanswers`、`$option->maxanswers`、`if ($choice->limitanswers && ($option->countanswers >= $option->maxanswers))`
   → **"选项满员即止"（先到先得 + 容量上限）**，没有时间片、没有志愿、没有抽签。
   来源：<https://raw.githubusercontent.com/moodle/moodle/MOODLE_405_STABLE/mod/choice/lib.php>

### 4.2 Canvas LMS（AGPL-3.0，<https://github.com/instructure/canvas-lms>，`master`）

1. **`app/models/` 里没有 timetable / timeslot 实体**；与"时间"相关的模型是
   `appointment_group.rb`、`appointment_group_context.rb`、`appointment_group_sub_context.rb`、`calendar_event.rb`、`course_section.rb`、`enrollment_term.rb`、`course_pace.rb`。
   来源：<https://api.github.com/repos/instructure/canvas-lms/contents/app/models?ref=master>

2. **Canvas 的官方"约时间"原语 = Appointment Group（Scheduler）**：
   源码实测（`appointment_group.rb`）：文件头为 AGPL-3.0 声明；`has_many :appointments`、`has_many :appointments_participants, -> { where("calendar_events.workflow_state <> 'deleted'").order(:start_at) }`、`validates :participant_visibility, inclusion: { in: ["private", "protected"] }`。
   → **教师发布可选时段 → 学生认领**，这是"预约课"（而非"课表"）的形态。
   来源：<https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/appointment_group.rb>

3. **Canvas 的"选课"是 enrol（注册）+ **选课期（term）**，没有时间片冲突检测**——它的边界就是"课程有没有开放、你有没有 enroll 上"。

### 4.3 LMS 层的结论

> **LMS 侧没有可抄的排课解。** Moodle 与 Canvas 都把"课在星期几第几节"排除在模型之外：
> 它们是"课程容器 + 日历"，不是"课表引擎"。
> 因此**"排课"这件事必须由教务系统自己解决**（我们做对了），
> 但 **"限额选择"这一原语在 LMS 里有成熟先例**（Moodle `mod_choice` 的 `maxanswers`、Canvas 的 Appointment Group 认领制），
> 且 **Canvas Appointment Group 的"发布时段 → 学生认领"形态，正是我们"学生自主选科/约课"最省事的落地参考**。

---

## 5. 国内 SaaS：功能名 + 官方 URL

### 5.1 培训机构侧（**与我们场景最贴近的一类**）

#### 校管家（深圳市智汇管家 · 教培校务）—— 交互层证据最丰富的一家

| 功能名（官方） | 一手来源 | 关键点（原文摘要） |
|---|---|---|
| 排课管理（新版） | <https://wiki.xiaogj.com/docs/pai-ke-guan-li-xin-ban> | 子功能：排课列表 / 课表日历 / **表格排课** / 预约课 / **对比排课** / 老师日程 / 约课管理 |
| **表格排课** | <https://wiki.xiaogj.com/docs/biao-ge-pai-ke> | "以表格的形式进行排课，支持多校区、多课程、多学员、多班级的排课，同时还支持提前**预检查冲突与限制**"；"**新增 10 行** / **按规则批量新增**：按'循环规则'或者'自由日期'的规则，批量生成一批排课数据"；异常提示三类：**有冲突 / 被限制 / 数据异常**；限制规则配在 "管理后台→业务规则→排课约课→排课限制规则" |
| **对比排课** | <https://wiki.xiaogj.com/docs/dui-bi-pai-ke> | "同时查看多位学员、多位老师、多个时间的忙闲情况…左侧添加多位学员的课表，右侧添加多位老师的课表"；"**单击某个具体的时刻，对向会在相同时刻高亮显示黄色标识**"；"**双击单元格可新增排课**" |
| **课表日历** | <https://wiki.xiaogj.com/docs/ke-biao-ri-li> | "**5 种课表视图 14 种显示方式**"；五种视角：**老师课表 / 学员课表 / 班级课表 / 教室课表 / 校区课表**；"课表偏好设置"可自定义颜色/标签/时刻高度 |
| **老师日程** | <https://wiki.xiaogj.com/docs/lao-shi-ri-cheng> | "可以为员工添加日程例如开会、请假等，**有日程的时间表示该时段不能排课**"；支持为多位员工一次新增多天日程；编辑/删除分"仅本次"与"全部" |
| **预约课** | <https://wiki.xiaogj.com/docs/yu-yue-ke> | "支持将班级的排课**开放预约**…学员可以**自行预约**进入排课"；预约课常驻"约"标签 |
| **排课列表** | <https://wiki.xiaogj.com/docs/pai-ke-lie-biao> | "给班级排课"（集体班）/ "给学员排课"（一对一）/ "排预约课" |
| 冲突规则（老版帮助） | <https://yxhelp.xiaogj.com/help-list-63-3-1.html> | "系统不允许同一名老师在同样的时间段内排 2 堂不同的课；如果是集体班，**系统还会检查教室冲突（一对一排课不检查教室冲突）**。如果出现这种情况，排课时就会出现冲突提示" |

> **注意它的一个设计判断**：**一对一不检查教室冲突，集体班才检查** —— 场景区分直接落到约束开关上。我们现在的四类检测是**无差别全开**的。

#### ClassIn（翼鸥教育）—— 官方小店帮助文档

<https://shop.classin.cn/help/appointment-course/schedule-management/>（「商家后台排课管理」）：
- 课表总览同一页完成：**新增排课 / 批量排课 / 设置老师可约时间 / 查看排课详情 / 批量删除排课**
- 明确列出 **「批量排课：固定规律模式」**（= 我们的"周期批量生成"）
- 侧栏另有：**老师维护授课时段**（老师端的可约时间）、**学生自主预约课程**、**商家代约课**、**商家发起改约**、**老师查看课表/课时统计**、**约课数据分析**
→ **"老师可约时间"由老师自己维护**，把可用时间的数据采集从教务外包给了教师本人。这是一个可以直接抄的降本手段。

#### 学邦技术 · BOSS 校长（广州学邦）

<https://www.xuebangsoft.com/pro_boss.html>：
- "**智能可视化排课**：BOSS 校长行业内真正的**实时自动检测冲突，可视化调整**"
- "全业务场景支撑排课，**一对一、班课、1 对多、寒暑假排课、规律或非规律性批量排课**"
- "先进的**师生双向智能排课**"
- 帮助中心入口 <https://www.xuebangsoft.net/eduboss/helpCenter/index.html>（实测该页需交互检索，**未取到具体排课条目 = 未验证**）

#### 校宝在线 · 智慧校园（K12 全日制）

<https://www.xiaobaoonline.com/products/sis.html>：
- 学生管理系统（SIS）功能含 "**智能排课**、**新高考走班排课**"
→ 走班排课 = 学生自选造成的时间片冲突问题，属于"高校式"半边。

#### 排课宝

<https://paikebao.com/>、<https://www.paikebao.com/features.html>（见 §3.5 表）

### 5.2 平台侧（钉钉 / 企业微信 / 飞书）—— **没有原生排课内核**

| 平台 | 证据 | 结论 |
|---|---|---|
| **钉钉** | 官方页「排课与课件管理」<https://page.dingtalk.com/wow/dingtalk/default/dingtalk/aiopFSNn4F6rm8gG3NQH>；官方页「官网-班级-课程表」<https://page.dingtalk.com/wow/dingtalk/default/dingtalk/t1hSEMgXKGKmkon2MdrWC>；钉钉模板中心-排班表 <https://appcenter.dingtalk.com/template/detail.html?topicCode=topic_group_template_category&subTopicCode=test_002&templateId=26840> | 两个 `page.dingtalk.com` 页面**实测返回 9 字节 / 6 字节（JS 渲染）→ 正文未验证**；只能确认"**钉钉把排课/课件做成"文档模板"**"这一产品形态 |
| **企业微信** | 官方帮助「企业微信教育版的核心功能有哪些」<https://open.work.weixin.qq.com/help2/pc/15057> | 页面正文为目录；**未取到"排课/课表"条目（未验证）**；可确认其教育版主打家校通讯录 / 班级群 |
| **飞书** | 飞书社区官方文章《老师排课表》<https://www.feishu.cn/community/article?id=7400988057966477316>："老师们为了合理安排课程，**常使用飞书多维表格**"；多维表格模板中心 <https://www.feishu.cn/marketing/base-solo/templatecenter>；官方「如何利用多维表格实现人员自动智能排班」<https://base.feishu.cn/academy/product-guide/random-task> | **飞书没有排课内核**，排课是"用户用多维表格自己搭" |
| （反证） | 培训机构用企微排课的做法是**装第三方应用**（如"轻训"），见知乎 <https://zhuanlan.zhihu.com/p/485450296> | 佐证平台本身不做排课（**二手来源，仅作旁证**） |

> **结论**：钉钉/企微/飞书是**入口与消息通道**，不是排课引擎。**不要指望从它们身上抄排课内核**；
> 但它们的"把排课做成模板/应用市场"的形态说明了一件事：**排课的数据模型必须能对外开放**（我们已有 ICS 方向的差异化，见 CLAUDE.md 铁律 0 的注）。

### 5.3 国内高校教务厂商（正方 / 强智）

| 厂商 | 一手来源 | 取证情况 |
|---|---|---|
| 强智科技 | 官网 <https://www.qzdatasoft.com/>；数智教学微服务平台 <https://www.qzdatasoft.com/list-15-1.html> | 官网产品线**未直接列出"排课/选课"独立产品名**；学生选课操作手册见于学校转载 PDF <https://www.hualixy.edu.cn/upload/jwc/contentmanage/article/file/2026/03/4a40d/202603102034135105.pdf>（**非官方发布，仅作旁证**） |
| 正方软件 | 官网 `https://www.zfsoft.com.cn/` **实测抓取为 0 字节（未验证）**；正方教务系统登录页实例 <https://jw5.zsit.edu.cn/default2.aspx> | 官网不可达；正方选课流程只能从学校方转载手册取证，**不作为结论** |

→ 国内高校厂商的**功能名级证据只能从"学校发布的选课通知"取得**（下一节），厂商官网本身拿不到。

---

## 6. 交互层：**用户说"麻烦"指的就是这一层**（本调研最重要的一节）

把 §5.1 校管家、§3.5 aSc/Untis、§3.2 UniTime 的做法并排，**"降低手工成本"的手段一共只有 8 种**，逐条给一手来源：

| # | 手段 | 一手证据 | 我们现在有没有 |
|---|---|---|---|
| 1 | **格子/表格排课（不是表单）**：一行=一条课，可"新增 10 行"、可**按规则批量新增** | 校管家·表格排课 <https://wiki.xiaogj.com/docs/biao-ge-pai-ke> | ❌ 我们是**网页表单填一个组合**，然后生成 N 条 |
| 2 | **预检查冲突（落库前先跑一遍）**，且提示**分三类**：有冲突 / 被限制 / 数据异常 | 校管家·表格排课（同上）；我们的 `/preview` 已有"红格/灰格"雏形 | ✅ 部分有（红格/灰格），但**不区分"冲突"与"规则受限"** |
| 3 | **对向高亮（我点一个时刻，对面的忙闲同时亮）** | 校管家·对比排课 <https://wiki.xiaogj.com/docs/dui-bi-pai-ke>："单击某个具体的时刻，对向会在相同时刻高亮显示黄色标识" | ❌ |
| 4 | **双击即建（无需跳表单）** | 校管家·对比排课："双击单元格可新增排课"；课表日历："支持双击学员或老师课表新增排课" <https://wiki.xiaogj.com/docs/ke-biao-ri-li> | ❌ |
| 5 | **多视角课表（同一个数据、五种维度看）** | 校管家·课表日历："5 种课表视图 14 种显示方式"（老师/学员/班级/教室/校区） | ✅ 部分：门户已有 学生/教师/家长/全校 四视角（`edu_portal/controllers/scheduling.py`），但**没有教室视角与校区视角** |
| 6 | **教师可用时间是一等数据**：老师日程=不可排；或老师自己维护可约时段 | 校管家·老师日程 <https://wiki.xiaogj.com/docs/lao-shi-ri-cheng>；ClassIn「设置老师可约时间」<https://shop.classin.cn/help/appointment-course/schedule-management/>；UniTime 硬约束"教师必须可用 / 不在 prohibited time" <https://help.unitime.org/instructor-scheduling> | ❌ **完全没有** |
| 7 | **改课/代课走"最小扰动建议"**：系统算出"改这一节要连带动哪几节"并摊开代价让你选 | UniTime <https://help.unitime.org/course-timetabling>："suggests a limited size set of alternative... **not affecting the assignment of more than two additional classes**... each option provides information on any additional student conflicts created"；Untis <https://www.untis.at/en/products/untis-basic-software/substitution-planning-1>："**solution suggestions with only one click**…instantly see who is available / who teaches the subject / who already knows the class"；aSc："advise the best cover teacher - **but you are free to choose**" <https://www.asctimetables.com/> | ❌ 完全靠人肉找空档 |
| 8 | **周期批量生成 + 模板复制** | ClassIn「批量排课：固定规律模式」<https://shop.classin.cn/help/appointment-course/schedule-management/>；校管家「按循环规则批量新增」<https://wiki.xiaogj.com/docs/biao-ge-pai-ke>；我们自己的 `/timetable/bulk` + 整周复制 | ✅ **这是我们目前最强的一环** |

**另外两条明确的产品判断（值得抄的"取舍"）**：
- **场景不同，约束不同**：校管家明确"**一对一排课不检查教室冲突，集体班才检查**"（<https://yxhelp.xiaogj.com/help-list-63-3-1.html>）。
- **自动与手工必须共存**：FET "*Fully automatic generation algorithm, allowing also semi-automatic or **manual allocation***"（<https://lalescu.ro/liviu/fet/features.html>）；排课宝"AI 生成初版课表后，支持**拖拽微调**"（<https://www.paikebao.com/features.html>）；UniTime 求解器"**can easily start, stop, or continue from any feasible solution**"（<https://www.unitime.org/index.php?tab=1>）。
  → **"全自动"从来不是这些产品的实际形态**；实际形态是"**机器出初稿 → 人用网格改 → 机器保证合规**"。

---

## 7. 学生选课层：志愿优先 vs 抽签 vs 先到先得

### 7.1 中国高校的事实标准：**两轮制——预选（志愿/抽签）+ 正选（即选即得）**

| 学校 | 一手来源 | 原文口径 |
|---|---|---|
| **上海交通大学** | <https://jwc.sjtu.edu.cn/info/1222/126721.htm> | 分三轮：**海选 / 抢选 / 第三轮**；"**海选课程不设人数限制**；海选结束后系统将进行**筛选，随机删除超出教学班容量的学生，筛选结果与同学们选课时间先后无关**" |
| **西安电子科技大学** | <https://jwc.xidian.edu.cn/info/1012/23283.htm> | 第 1 轮：方案内课程=**正选**（预置必修、可志愿退改、"调整即刻生效"、"**限定课容量**"、"**限制时间冲突**"、"可**实时查看个人选课结果**"）；通识选修课=**预选**，"规定时段均可选课，**随机抽签决定中签学生**"。第 2 轮：**公布抽签** → 正选"**即选即得**" |
| **西北大学** | <https://jwc.nwu.edu.cn/info/1034/11158.htm> | "学生可同时最多选择两位任课教师（**两个志愿**），并将最有意向选读的教师填报为**第一志愿**…系统按照**志愿优先**进行排序筛选，如果无法用志愿筛选结果，将采用**随机抽签**确定选课结果"；"**课程筛选不考虑选课时间先后，因此学生在志愿选课期间无需抢时间选课**"；对照模式："**直选选课：采用时间优先，先到先得、即选即中**" |
| 北京大学 | <http://www.dean.pku.edu.cn/web/student_info.php?type=2&id=15> | 学生服务 → 选课和退课 栏目包含 **「冲突选课」「超学分选课」「跨院系选课」「手工选课」**，说明"时间冲突"在北大是**显式的一类业务**。（**正文中的抽签表述未取到 = 未验证**） |

**三条可直接落地的设计结论**：
1. **"志愿/抽签"这一档的存在理由之一，就是消灭抢课**：西北大学原文"**不考虑选课时间先后，因此学生在志愿选课期间无需抢时间选课**"；上海交大"**筛选结果与同学们选课时间先后无关**"。
   → **公平性 + 削峰**是同一个设计动作的两个收益。**对我们这种体量，这比"优化抢课并发"高效得多。**
2. **一轮不够，必须两轮**：预选（表达意愿、超容量抽签）→ 正选（即选即得、先到先得）。**第二轮是给"没中签的人"的补救通道**，不是重复劳动。
3. **"时间片冲突检测"在第一轮就要给**：西电原文"限制时间冲突…可实时查看个人选课结果"；北大把"冲突选课"单列成服务。
   → 对我们：学生自主选科时**必须在提交志愿前就能看到"这两门课时间撞了"**，而不是事后报错。

### 7.2 学术与商用系统的对应做法

- **Harvard Course Match**（Budish & Cantillon, *American Economic Review* 102(5):2237–2272, 2012）
  <https://www.aeaweb.org/articles?id=10.1257/aer.102.5.2237>
  → 多单位分配（multi-unit assignment）问题的经典：学生**提交课程意愿排序**，由算法分配；论文的核心贡献是论证了"课程是**捆绑品**（bundle），标准机制（含竞价）在捆绑估值下不满足如实申报"，并据此设计了近似无嫉妒的 Course Match。
  → **对我们的含义**：一旦"学生自选 + 容量有限 + 一次选多门"，就落入 multi-unit assignment，**"先到先得"在公平性上是最弱的一档**。
- **PeopleSoft（Oracle）**：学生记录模块的选课限制条件建模见
  「Defining Enrollment Requirements」<https://docs.oracle.com/cd/E56917_01/cs9pbr4/eng/cs/lssr/task_DefiningEnrollmentRequirements-ab4878.html>
  与 PeopleSoft Student Records 9.0 PeopleBook <https://download.oracle.com/docs/cd/E17221_01/cs9pbr2/eng/psbooks/lssr/htm/lssr06.htm>
  → 可核实的只是"**Enrollment Requirement Groups**（对特定课程/容量的要求）"这一概念。
  ⚠ **PeopleSoft 的"时间冲突检测"具体字段与开关，本调研未取到一手页面 = 未验证**。
- **Ellucian Banner**：本次调研**未取到任何官方一手页面**（搜索结果全是学校审计报告等无关文档）→ **未验证**，不作为结论。

### 7.3 "抢课并发"该怎么办

- 本次调研**没有取到任何厂商关于选课并发架构的一手技术披露** → **未验证**。
- 唯一可靠的一手线索是**反面**的：中国头部高校（上交、西北大）用**"抽签与时间无关"从设计上消除抢课高峰**，而不是靠扩容硬扛。
- 强智"支持万人同时在线选课"的说法只出现在知乎问答（<https://www.zhihu.com/question/1903411919727097264>，**二手，实测正文被反爬拦截**）→ **不作为结论**。

---

## 8. 三类场景的"先进"完全不是一回事（**我们更像哪一类**）

| 维度 | 中小学（全日制） | 高校（学分制） | 培训机构 / 家教网课 |
|---|---|---|---|
| 排课主体 | **班级固定**、教师流动 → 排"班级-教师-教室"的组合 | **学生自选** → 排"课程-课次-时间片"，学生组合冲突是核心 | **学员/1对1/班课混合** → 排"谁-什么时候-哪个房间" |
| 核心约束 | 教师资质、连堂、走班 | **学生冲突权重**（ITC2019 论文：*student conflicts are heavily weighted*）、课程结构（lecture/seminar/lab 父子） | 教师可约时间、学员可用时间、房间、课时扣费 |
| "先进"= | 自动生成 + 排课规则表达（aSc / Untis / TimeTabler / 校宝新高考走班） | **学生分班 + 求解器 + 场景模拟 + 交互式改课**（UniTime；ITC2019 的 key novelty 就是把 student sectioning 并进时间/教室分配） | **交互层极致**：表格排课 / 对比排课 / 循环规则批量 / 预约课（校管家 / ClassIn / 学邦 / 排课宝） |
| 选择机制 | 基本无（行政分班） | **志愿优先 + 抽签 + 两轮制** | 预约 / 排课 / 排预约课 |
| 代表证据 | <https://www.utwente.nl/en/eemcs/dmmp/hstt/itc2011/>（ITC2011 专注 High School Timetabling） | <https://link.springer.com/article/10.1007/s10951-023-00801-w>、<https://help.unitime.org/course-timetabling> | <https://wiki.xiaogj.com/docs/biao-ge-pai-ke>、<https://shop.classin.cn/help/appointment-course/schedule-management/> |

### 我们的场景判定

**现状（本仓事实）**：多间"房间"、每间房间主持人不同、排课表历史上是 Excel（`2+6排课表.xlsx` 手工导入）、教师流动、**既有班级也有学生自主选科**；实体是 `op.session`（绝对起止时间）+ `op.batch`（班）+ 班级科目 + `op.classroom` + `op.faculty`。

**判定**：
> **我们 = "培训机构式排课"为主体 + "高校式选课"为特例的混合体。**
> - **主体**（占日常工作量绝大多数）= **培训机构那一类**：班级/班次固定、教师与房间流动、要批量生成整学期、要频繁调课代课。
>   → **该抄的是校管家/ClassIn 的交互层**（§6），**不是** UniTime 的求解器。
> - **特例**（学生自主选科）= **高校学分制的那一半**：一旦学生能在多个教学班之间选，"学生时间冲突"就会成为真约束。
>   → **该抄的是中国高校的"预选（志愿+抽签）+ 正选（即选即得）"两轮制**（§7.1），**不是** Banner/PeopleSoft 的采购级方案。
> - **不是**中小学那一类：我们没有"班级固定到可以整体平移课表"的简化条件（教师流动 + 房间主持人不同），所以 aSc/Untis 那种**为"班级-教师矩阵"优化的自动生成器**，直接搬会建模不匹配。

---

## 9. 我认为对本项目最值得抄的 3 件事

### 第 1 件：把"填表单"换成"点格子"——**表格/网格排课 + 三类预检查提示**

**抄谁**：校管家·表格排课 <https://wiki.xiaogj.com/docs/biao-ge-pai-ke> + 对比排课 <https://wiki.xiaogj.com/docs/dui-bi-pai-ke>；我们**基座里已有同型先例** `openeducat_timetable/wizard/generate_timetable.py`（`generate.time.table`，课程+班级的七日线网格）。

**抄什么**：
1. **网格视图**（行=时段或课程，列=星期），**可在格子上直接增删**，不再"填一个组合 → 生成一堆"。
2. **落库前预检查**，并把提示**分成三类**而非一类：
   - **有冲突**（教师/教室/班级撞时间）——对应我们现在 `conflict_kind`；
   - **被规则限制**（比如超出"最早上课时间/每日最大课时"）——**我们现在完全没有这一档**；
   - **数据异常**（缺上级数据，如没选教室）——我们现在也没有。
3. **按"循环规则 / 自由日期"批量新增**（我们的单双周 + 周次范围已经是这个意思，只是入口是表单而不是格子）。

**为什么第一优先**：用户抱怨的是"**很麻烦**"（操作次数），不是"排出来的表不好"。省操作次数的收益**当天可见**，且**不依赖任何求解器**。

**顺带复核一条**：基座 `generate.time.table` 向导本身就是网格式的，我们绕开它自研了门户表单——**值得在动手前先看一遍基座向导到底缺什么**（避免重复造）。

### 第 2 件：把"改课/代课"做成**最小扰动建议**——但**先做数据，再做算法**

**抄谁**：
- **UniTime** 的交互式求解器口径（"**只影响不超过 2 个其他班**"、可限制为**只换教室 / 只换时间**、每个方案都告诉你**新增了哪些学生冲突与偏好违背**"）
  <https://help.unitime.org/course-timetabling>
- **Untis / aSc** 的代课建议（"一键给出方案：谁**有空**、谁教**这门课**、谁**认识这个班**"；"**系统建议，你决定**"）
  <https://www.untis.at/en/products/untis-basic-software/substitution-planning-1>、<https://www.asctimetables.com/>
- 理论上它就是 UniTime CPSolver 内建的 **"最小扰动问题（minimal perturbation problem）"**
  <https://www.unitime.org/index.php?tab=1>

**抄什么（分两步，不要一次做满）**：
1. **先把"可用性"变成数据**（零算法）：教师**不可用时段**（校管家"老师日程"= 有日程即不可排 <https://wiki.xiaogj.com/docs/lao-shi-ri-cheng>；UniTime 硬约束"must be available / not during a prohibited time" <https://help.unitime.org/instructor-scheduling>；ClassIn"设置老师可约时间" <https://shop.classin.cn/help/appointment-course/schedule-management/>）。
2. **再做"候选方案搜索"**：给定"某节课要改"，输出 3–5 个候选（含"只换教室 / 只换时间 / 都换"），每个候选标注**连带影响了几节课、是否产生新冲突**。

**为什么值得**：代课/换课是**发生频率最高**的教务动作，而且是**最花人工**的（要翻教师课表、翻教室占用、翻班级课表）。它不是"排学期初的表"，而是"每天都在发生的事"。

### 第 3 件：学生选课走**"预选（志愿 + 抽签）→ 正选（即选即得）"两轮**，并把**时间冲突检测前置到填志愿时**

**抄谁**（中国高校事实标准，官方通知级证据）：
西北大学 <https://jwc.nwu.edu.cn/info/1034/11158.htm>（志愿优先 → 抽签；"**不考虑选课时间先后，无需抢时间选课**"）
上海交通大学 <https://jwc.sjtu.edu.cn/info/1222/126721.htm>（海选"**不设人数限制**，结束后**随机删除**超容量的学生，**与时间先后无关**"）
西安电子科技大学 <https://jwc.xidian.edu.cn/info/1012/23283.htm>（预选抽签 → 正选即选即得；"**限制时间冲突**"、"可实时查看个人选课结果"）
理论依据：Harvard Course Match（Budish & Cantillon, AER 2012）<https://www.aeaweb.org/articles?id=10.1257/aer.102.5.2237>

**抄什么**：
1. **两轮**：预选收集志愿（可超容量）→ 系统定容量 → 正选即选即得（剩余名额）。
2. **抽签与提交时间无关**，并在**通知里明说**（这是消除抢课的关键，也是公平性的来源）。
3. **填志愿时就做时间片冲突检测**（西电"限制时间冲突"、北大把"冲突选课"单列为一种服务）。
4. 容量上限的现成原语可参考 Moodle `mod_choice` 的 `maxanswers`/limitanswers <https://raw.githubusercontent.com/moodle/moodle/MOODLE_405_STABLE/mod/choice/lib.php>；**预约制**可参考 Canvas Appointment Group 的"发布时段 → 学生认领" <https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/appointment_group.rb>。

**为什么值得**：这是唯一一条**同时解决公平性与并发峰值**的机制；而且实现成本低于"给选课系统做高并发"。

### （次优，也建议排期）把四个布尔开关升级为**带权重的约束清单**

- **抄谁**：FET 的约束调色板与"**每条约束有 0.0%–100.0% 权重**" <https://lalescu.ro/liviu/fet/features.html>；UniTime 的"硬约束 / 软约束（偏好分级：strongly preferred → prohibited）" <https://help.unitime.org/instructor-scheduling>。
- **抄什么**：把 `timetable.is_*` 四个开关，扩展为"**约束条目（类型 + 作用对象 + 是否硬约束 + 权重）**"的可配置清单；并按场景开关（校管家先例：**一对一排课不检查教室冲突** <https://yxhelp.xiaogj.com/help-list-63-3-1.html>）。
- **理由**：这是**未来任何自动排课/建议方案的前置数据结构**；现在不做，将来求解器就没有输入。

---

## 10. 未验证 / 待确认清单

> 按 `docs/research/README.md` 规范：以下条目**未取得一手证据**，**不得当结论使用**。

| # | 未验证项 | 原因 |
|---|---|---|
| 1 | **ITC2019 官网正文**（赛题、实例清单、规则） | `https://www.itc2019.org/` 为 Angular SPA，实测直连只返回 1117 字节且无正文；本文件 ITC2019 结论全部改引 Springer 论文 |
| 2 | **UniTime 帮助中心旧域名** | `https://help-unitime.unitime.org/unitime_intro.php` 实测直连与走代理均超时（http=000）；新域名 <https://help.unitime.org/> 可访问，本文改用新域名 |
| 3 | **ER-Timetable / Untis 帮助中心正文** | `https://help.untis.at/hc/en-us/sections/360003093780-Substitutions` 实测被 Cloudflare 拦截（返回 "Just a moment..."）；仅取到 untis.at 官方产品页 |
| 4 | **Moodle 官方文档站与插件目录** | `docs.moodle.org`、`moodle.org/plugins` 实测被 captcha 拦截（"Moodle challenge"）；本节结论全部来自 GitHub 源码 |
| 5 | **Google OR-Tools 官方站点** | `developers.google.com` **直连超时**，需走本机代理 `http://127.0.0.1:12450` 才 200；已用代理取得正文 |
| 6 | **FET 的交互层（有无拖拽 / 图形化网格）** | 官方截图页 <https://lalescu.ro/liviu/fet/screenshots.html> 只给分类链接，未取到逐张说明 |
| 7 | **PeopleSoft / Banner 的"时间冲突检测"具体实现** | 未取到 Oracle 官方针对"时间冲突检测"的专页；Banner 更是一手页面全无（搜索结果均为学校审计报告等无关文档） |
| 8 | **钉钉「班级-课程表」「排课与课件管理」页面正文** | 两个 `page.dingtalk.com` 官方页实测返回 9 / 6 字节（JS 渲染）；只能确认产品名与形态 |
| 9 | **企业微信教育版是否有排课/课表功能** | 官方帮助页 <https://open.work.weixin.qq.com/help2/pc/15057> 实测只取到目录，未取到正文条目 |
| 10 | **飞书官方帮助中心正文** | `https://www.feishu.cn/hc/zh-CN/` 实测只返回标题（JS 渲染） |
| 11 | **正方软件官网** | `https://www.zfsoft.com.cn/` 与 `https://www.sofn.com.cn/` 实测抓取 0 字节 |
| 12 | **重庆大学选课通知正文**（"3 个教学班志愿 + 服从调剂 + 系统抽签"） | `https://jwc.cqu.edu.cn/info/1084/5677.htm` 与 `/5966.htm` 实测直连与走代理均 0 字节；本条只在上海交大/西北大/西电的通知里得到等价证据，CQU 具体条款**未验证** |
| 13 | **强智 / 正方的"高并发选课"技术实现** | 只在知乎等二手渠道出现，且实测被反爬拦截（页面正文为"知乎，让每一次点击都充满意义"） |
| 14 | **"抢课并发"的任何厂商技术披露** | 全网未取到一手技术文档；本文只给出"用抽签从设计上削峰"这一有官方通知佐证的替代方案 |
| 15 | **OCA 是否存在名为 schedule/timetable/education 以外的教育相关排课仓库** | 已用 GitHub 组织级搜索（`org:OCA timetable` / `schedule` / `education in:name`）验证为 0/0/1；但**搜索 API 不能覆盖"未命名含关键词"的仓库**，理论上仍有漏网可能 |
| 16 | **aSc / Untis / TimeTabler 的具体价格与授权模式** | 本次未采集（与"排课方法"无关） |
| 17 | **我们的 `2+6排课表.xlsx` 实际字段结构** | 本文件未找到该文件（工作区内未定位），场景描述沿用任务背景给出的事实 |

---

## 11. 取证方法备忘（给下一个人）

- 本机**直连外网可用**；但 `developers.google.com` **必须走代理 `http://127.0.0.1:12450`**。
- `docs.moodle.org` / `moodle.org/plugins` 有 captcha；**Moodle 一律读 `raw.githubusercontent.com/moodle/moodle/@<分支>`**。
- GitHub 页面 HTML 噪音极大；**优先用 `https://api.github.com/repos/<owner>/<repo>/contents/<path>?ref=<branch>`** 取目录清单，用 `raw.githubusercontent.com` 取文件正文。
- 组织级检索：`https://api.github.com/search/repositories?q=org%3AOCA+<关键词>`（未认证即可用，有速率限制）。
- 本机 Odoo 基座源码在 `openeducat_erp/openeducat_timetable/`（19.0 分支快照，LGPL-3）。

---

**本文件遵循 `docs/research/README.md` 收录规范：每条结论带一手来源 URL；未取到证据的一律进 §10「未验证」清单，且不作为结论。**
