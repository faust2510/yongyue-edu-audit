# 国内教育/校园类开源项目与排课交互调研报告
> **状态**：`归档` ｜ **主题**：`开源排课调研` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 调研人：oss-researcher（ux-rework 团队）｜检索时间：2026 年 8 月
> 方法：GitHub Search/Repository API 核验（star 数、license、语言），关键仓库浅克隆到本地逐文件核读；结合本仓库已装 OpenEduCat 基座（`openeducat_erp/`）的本地源码核对关键路径。star 数为检索当日值，仅供参考。
> 关联文档：`docs/plans/timetable-design.md`（本库排课系统既有设计，OpenEduCat 已作为基座），本文不重复其内容，聚焦可参考的外部开源项目矩阵。

---

## 0. 结论速览（TL;DR）

> **决策固化（t2 结论，供 t3 方案直接引用）**
>
> **D1｜License 边界**：本方案可复用/引用代码仅限 **MIT / Apache-2.0 / LGPL**（OpenEduCat LGPL 基座合法已在用）；**GPL-3.0 与无 License 项目只作思路参考，不得搬运代码**。
>
> **D2｜排课交互选型**：前端排课/调课交互**首选参考 javashub/CourseArragement 的"周矩阵 + 拖拽调课 + 冲突面板"模式**（Apache-2.0，可借鉴其 `ScheduleView.vue` 网格与原生 DnD 手法）；**服务端冲突检测复用 openeducat_timetable 现有四查逻辑**（教师/教室/班级/班级+课程，`models/timetable.py` 的 `check_timetable_fields()`），不另造冲突引擎；拖拽落点前的"班级+教师跨班"前置校验可参照 Rackar/EduScheduler 的 `checkScheduleConflicts` 交互范式。

1. **排课交互做得最完整、最值得直接借鉴的三个仓库**：
   - `javashub/CourseArragement`（Apache-2.0，403★）：Vue3 + Element Plus，**周课表矩阵 + 原生 HTML5 拖拽调课 + 调课记录回放 + 自动排课（教师日/周上限、班级禁排时段）+ 冲突提示**，前后端结构清晰，与本项目后台（Odoo web 中文视图）交互同构性最高。
   - `Rackar/EduScheduler`（Apache-2.0，17★）：Vue3 周视图按"周模板 + 周次"展开，**拖拽调课时实时校验班级冲突与教师跨班冲突，右侧"待处理冲突"面板 + 目标格红/绿虚线提示 + 自动优化（optimizeSchedule）**，交互范式与钉钉日历"排期冲突即时反馈"一致。
   - `openeducat/openeducat_erp`（LGPL-3.0，864★）：已在本地库中。`openeducat_timetable` 的**四类冲突约束（教师/教室/班级/班级+课程）、Odoo calendar 视图拖拽建课、周过滤**是本项目既有实现的底座，继续作为行为基准。
2. **日程/日历类组件**：FullCalendar（MIT）、TOAST UI Calendar（MIT）可直接作为"周视图矩阵 + 拖拽"前端内核候选；`yannecer/NCalendar`（Apache-2.0）是仿钉钉/华为日历的 Android 控件（周/月滑动切换），移动端参考。
3. **钉钉风格后台/工作流**：`StavinLi/Workflow`（MIT，仿钉钉审批流）、`AntFlow.net`（Apache-2.0，钉钉工作流 UI 风格）、`vue-element-admin` / `ant-design-pro` / `RuoYi-Vue` / `vue-vben-admin`（均为 MIT）提供"工作台网格 + 左侧导航 + 通知中心"的信息架构范式。
4. **校园教务小程序/App**：`danbaixi/yunxiaozhi`（GPL-3.0，课表查询小程序）、`zfman/TimetableView`（MIT，Android 周课表控件、重叠自动处理）验证了移动端"周次弹窗 + 周矩阵"交互。
5. **违规风险提示**：`georgehuan1994/DingDing-Automatic-Clock-in`（979★）等打卡脚本**无 License**，仅可看思路不可搬运；`TOGO_School_Miniprograme`、`wechat-kaoqin` 同理。

---

## 1. A 类：排课/课表核心项目（深度分析）

### 1.1 OpenEduCat openeducat_timetable —— 可直接借鉴（已在使用）
- 仓库：[openeducat/openeducat_erp](https://github.com/openeducat/openeducat_erp)（LGPL-3.0，864★，Odoo 系教育 ERP）
- 说明：核心课时实体 `op.session`（绝对起止时间）与 `op.timing`（第 N 节次），我们本地库已装并基于其实现排课中心/周课表四视角（见 `docs/plans/timetable-design.md`）。
- 关键文件（本地路径即上游路径）：
  - `openeducat_timetable/models/timetable.py`：`check_timetable_fields()` 冲突四查——教师（faculty）、教室（classroom）、班级（batch）、班级+课程（batch+subject），由 `timetable.is_faculty_constraint` 等四个系统参数门控（本库以 `data/timetable_params.xml` noupdate 固化默认全开）；实现要点：先按 `±24h` 日期窗口预筛"其他课时"，再做同窗重叠比较（避免全表扫描）；`state != 'cancel'` 的课时不参与冲突；用 `sudo()` 保证跨教师记录规则也能看到全部课时（修复"跨教师重叠静默通过"的 bug）。
  - `openeducat_timetable/models/timing.py`：节次/时段模型。
  - `openeducat_timetable/views/timetable_view.xml`：Odoo **calendar 视图**（周视图 Level），内置 Week 过滤（`filter_session_week`）、**拖拽/点 slot 快速建课**（quick-create 弹窗）、按资源着色。
- 可借鉴点：冲突检测的数据口径（"同一天内才可能冲突"的窗口预筛 + 全量 sudo 视野）、"模板/参数门控冲突开关"的运维手法、日历视图即编辑主入口。

### 1.2 javashub/CourseArragement —— 可直接借鉴（前端交互最贴近）
- 仓库：[javashub/CourseArragement](https://github.com/javashub/CourseArragement)（Apache-2.0，403★，Java SpringBoot2 + MySQL + Vue3/Element Plus 课程编排系统，面向培训机构/高中）
- 说明：完整闭环——课程计划（任务）、固定课保存、自动排课、周课表查看、**拖拽调课**、调课记录审计。前后端分离，前端目录 `UI/coursearrange/`。
- 关键文件与交互实现：
  - `UI/coursearrange/src/views/course/ScheduleView.vue`：课表管理页。**周视图矩阵**：网格表头"时间 + 周一到周日"、行为"第N节 + 起止时间"，按上午/下午/晚上分组着色（`TIME_GROUP_LABELS`）；**教师/班级双视角切换**（viewMode）、学期/班级/教师筛选 + 查询按钮；课程卡片按科目 12 色调色板（CSS 变量 `--course-accent` 等）着色；**拖拽调课**用原生 HTML5 DnD（卡片 `draggable`，`dragstart/dragover/drop`），空格显示"拖入调课"占位，拖拽目标格高亮；切换/调课后有 `el-alert` 状态提示；页面底部**调课记录表**（操作人/班级/教师/调整前→后/定位按钮，可跳转聚焦到变动课程）。课程卡片含课程名、教师、教室三要素，与钉钉日程卡信息密度一致。
  - `UI/coursearrange/src/views/course/scheduleGrid.js`：网格构建工具——从排课配置提取时段映射（`periodNo → start/end/group`）、按配置+数据动态确定周天数/节数、**相邻时段分组合并**（上午 1-5 节等）、课程位置解析（`weekdayNo+periodNo` 或 `classTime` 字符串回退解析）。
  - `UI/coursearrange/src/views/course/CoursePlanView.vue`：**批量排课入口**——固定时段任务 + 自动排课：自动排课读取"时间片模板"、跳过"不可上课/固定休息"时间片、遵守教师日上限/周上限课时、班级管理维护的**禁排时间**参与保存校验与避让；页面内有"冲突任务"态。
  - `UI/coursearrange/src/views/student/StudentTimetableView.vue` / `teacher/TeacherTimetableView.vue`：学生/教师个人课表视图（学生端为待迁移占位，教师端同 ScheduleView 网格）。
- 可借鉴点：自定义网格（非组件库）实现"节次 × 星期"矩阵的做法；原生 DnD 免引入拖拽库；调课记录 + 定位回放；教师日/周课时上限与禁排时段的规则配置化。License Apache-2.0，可参考/复用 UI 逻辑（注意遵守 NOTICE 与保留版权声明）。

### 1.3 Rackar/EduScheduler —— 可直接借鉴（拖拽冲突反馈最精细）
- 仓库：[Rackar/EduScheduler](https://github.com/Rackar/EduScheduler)（Apache-2.0，17★，Node/Express + Vue3 + Tailwind + ECharts 教育排课）
- 说明：面向培训机构的排课 SaaS 形态，含租户、班级/教室/教师管理、**周模板（schedule-templates）→ 实例课时**、周课表、调课、统计图表。前端 `frontend/`。
- 关键文件与交互实现：
  - `frontend/src/components/schedule/WeeklyScheduleView.vue`：**周视图矩阵**——"第N周"下拉（1..20 周）+ 班级下拉，用 `el-table` 渲染"时间行 × 周一~周五列"（列固定，行高 100px），单元格内可渲染多张课程卡；数据转换在 `frontend/src/utils/schedule.js` 的 `convertToTableData()`（把"课次列表"按 dayOfWeek/timeSlotId 投影成矩阵）、`mergeScheduleWeeks()`（**多周次课合并展示**）、`formatWeeks()`（周次区间缩写，如 "1-3,5 周"）。
  - `frontend/src/components/schedule/ScheduleAdjustView.vue`：**拖拽调课 + 实时冲突检测**——卡片 `draggable`；`dragover` 时目标格亮虚线（`hasConflict=false` 绿 / `true` 红）；`drop` 时先调 `checkScheduleConflicts`（目标班级冲突）再调 `checkTeacherOtherClassConflicts`（**教师跨班冲突**，带周次参数），合并结果后确认再提交 `updateScheduleTime`；课程卡上冲突态显示红色虚线边框（`isConflictSchedule`）；**右侧固定"待处理冲突 (N)"面板**：类型文案 + 课程/教师/班级/时间/周次明细 + "请将此课程拖拽到其他时段"引导 + 一键跳到对应班级；另有 `optimizeSchedule`（自动优化整班课表）、`clearSchedule`（清空重排）。
  - `frontend/src/views/admin/schedule-templates/edit.vue`：**周模板编辑器**（批量排课的数据基础：模板=一周的标准时间片+课程分布，实例按周次展开）。
  - `frontend/src/components/schedule/TeacherScheduleView.vue` / `ClassScheduleView.vue` / `ScheduleStatistics.vue`：教师/班级视角 + ECharts 课时统计。
- 可借鉴点："周模板→实例展开"的批量排课数据模型；**拖拽即校验（班级+教师跨班两级）**的交互链路；冲突面板的引导文案设计；多周次课（例：1-16 周每周两节）的合并展示与缩写。

### 1.4 Code-Chen/CourseSchedulingSystem —— 需改造（自动排课算法参考）
- 仓库：[Code-Chen/CourseSchedulingSystem](https://github.com/Code-Chen/CourseSchedulingSystem)（GPL-3.0，183★，SpringBoot + React 高校自动排课）
- 说明：**基于遗传算法的高校自动排课**：排课任务表（班级/课程/人数/周学时/固定时段）→ 一键"排课"→ 输出全部班级课表。前端 React + Ant Design。
- 关键文件：`UI/my-app/src/ArrangingPage.js`（任务列表表格 + 一键排课按钮，调 `/classScheduling`）；后端 `src/main/java/com/xnxy/CourseSchedulingSystem/Service/Impl/ClassSchedulingService.java`（遗传算法编排主服务，含约束评估）。
- 可借鉴点：把"教师/班级/教室/课程"约束折进适应度函数的写法；固定课（isfix）+ 自由课混合编排的输入模型。GPL-3.0 传染性：**只学算法思路，不复用代码**（本项目为 Odoo 混合授权环境，避免 GPL 代码进入）。

### 1.5 UniTime —— 需改造（重型大学排课平台）
- 仓库：[UniTime/unitime](https://github.com/UniTime/unitime)（Apache-2.0，348★，Java/GWT）
- 说明：全球数十所大学使用的排课/考试/教室调度平台，含约束求解器（solver）、冲突驱动的软硬约束、课表网格、拖拽调整、发布审批流。体量很大（GWT 前后端），不适合直接引入，但**冲突模型与"周/学期课表网格"语义是权威参照**。
- 关键文件：`JavaSource/org/unitime/timetable/gwt/client/course/`（GWT 课表网格客户端）、`JavaSource/org/unitime/timetable/solver/`（AbstractSolver、ClassAssignmentProxy 等求解与分配代理）。
- 可借鉴点：硬约束（不可重叠）/软约束（偏好）分层；"分配代理（AssignmentProxy）"把冲突判断从业务逻辑中剥离的架构——可映射为 Odoo 里独立的冲突检测服务层。Apache-2.0 合规友好。

### 1.6 FET（Free Timetabling Software）—— 仅思路（算法与展示）
- 仓库：[lalesculiviu/fet](https://github.com/lalesculiviu/fet)（官方站点 lalescu.ro 声明 GPL-3.0；GitHub 镜像未附 LICENSE 文件，谨慎复用；C++ 桌面软件）
- 说明：老牌免费排课软件，支持超细粒度约束（教师/班级/教室/时间偏好、间隙、最大连续课时等），输出周课表矩阵与统计告警。交互是桌面 GUI，不适合 Web 直接借鉴。
- 可借鉴点：**约束体系清单**（我们做排课规则配置时可对照补漏：连堂、每日最大课时、教师空闲偏好、教室容量等）；官方文档的排课流程（试排→冲突清单→手工调整）与钉钉"草稿-冲突-确认"心智一致。

---

## 2. B 类：日程/日历组件（前端内核候选）

- [fullcalendar/fullcalendar](https://github.com/fullcalendar/fullcalendar)（MIT，20621★）：事实标准日历库。**周视图 timeGridWeek / 资源视图 resourceTimelineWeek**、原生拖拽（`eventDraggable`/`eventResize`）、日期导航与"今天"定位。若我们的排课中心要上"钉钉式周/月日历"，可直接作为渲染内核；MIT 无传染。
- [nhn/tui.calendar](https://github.com/nhn/tui.calendar)（MIT，12705★，TOAST UI Calendar）：月/周/日视图，**周视图时间网格**、拖拽新建/调整/缩放事件、主题定制，中文 locale 支持良好，风格比 FullCalendar 更"移动端友好"。适合做"校历/日程"页的交互底座。
- [jquense/react-big-calendar](https://github.com/jquense/react-big-calendar)（MIT，raw LICENSE 核验）：React 生态周视图 + 拖拽（`react-big-calendar` 主包 + `@react-big-calendar/drag-and-drop`），对 React 端改造有用；本项目前端为 Odoo QWeb/模板 + 少量 Vue（排课中心为 Odoo web），优先级低于前两者。
- [yannecer/NCalendar](https://github.com/yannecer/NCalendar)（Apache-2.0，1721★）：Android 日历控件，**仿 MIUI/钉钉/华为日历，周日历/月日历滑动切换**、农历节气管线。移动端（如学生课表 H5/小程序）周历交互的直接参考，含"当前时间线"指示。

---

## 3. C 类：钉钉风格后台/工作流模板

- [PanJiaChen/vue-element-admin](https://github.com/PanJiaChen/vue-element-admin)（MIT，90203★）：国内后台事实标准模板：左侧导航 + 顶栏面包屑/通知铃铛 + 标签页 tabs + 权限路由。**"工作台首页"卡片网格**（Dashboard 应用宫格）是可借鉴的应用板块布局；MIT 可直接借鉴。
- [ant-design/ant-design-pro](https://github.com/ant-design/ant-design-pro)（MIT，38717★）：Ant Design 企业级中后台脚手架，与钉钉网页端同源技术栈（React + antd）。**ProCard 宫格、工作台 Welcome 区块、通知中心**是"钉钉式工作台"信息架构的良好参照；其"可拖拽布局"示例可支撑应用板块自定义排序。
- [yangzongzhuan/RuoYi-Vue](https://github.com/yangzongzhuan/RuoYi-Vue)（MIT，3185★）：若依前后端分离版。国内**校园/教务类二次开发最常用的底座**（大量"若依+智慧校园"派生项目），其"菜单-权限-角色"模型与我们的 Odoo 门户角色视图可对照；社区里排课/课表派生实现多但质量参差，借鉴时先看 license 与代码成熟度。
- [vbenjs/vue-vben-admin](https://github.com/vbenjs/vue-vben-admin)（MIT，33259★）：Vue3 企业级模板，暗色主题/多标签/工作台布局，风格比 vue-element-admin 更现代，接近钉钉新版视觉（圆角卡片、柔和层次）。
- [StavinLi/Workflow](https://github.com/StavinLi/Workflow)（MIT，1645★）：**仿钉钉审批流程设置**前端（可视化条件分支画布）。钉钉最深入人心的交互之一就是审批流画布；若门户要加"请假/调课审批"，此项目的前端画布交互（节点拖拽、条件配置表单）是首选参考。
- [mrtylerzhou/AntFlow.net](https://github.com/mrtylerzhou/AntFlow.net)（Apache-2.0，267★）：**钉钉工作流 UI 风格**的 BPM 工作流平台（.NET）。提供审批实例、待办列表、抄送等页面的钉钉式呈现范式。

---

## 4. D 类：校园/教务小程序与 App、课表控件

- [danbaixi/yunxiaozhi](https://github.com/danbaixi/yunxiaozhi)（GPL-3.0，439★）：云小智——校园教务查询微信小程序（课表/成绩/校历/考试/空教室）。关键路径 `pages/course/course.js`：**20 周周次模型 + "周数"弹窗切换 + 按周次×节次分组渲染**（weekCount/showWeekList/now_week），`pages/course/setTime` 做节次时段设置。移动端"我的课表"信息密度与翻周交互的实测样本。GPL 约束：仅借鉴交互。
- [214140846/TOGO_School_Miniprograme](https://github.com/214140846/TOGO_School_Miniprograme)（**无 License**，412★）：校园综合服务小程序（教务/课表/二手/论坛），功能全集但对标"大而全工作台"。无 License→仅思路。
- [wyvern1723/sachet](https://github.com/wyvern1723/sachet)（MIT，24★）：湘潭大学 Flutter 课表 App（课表/空教室/成绩）。MIT 可借鉴；移动端课表网格 + 空教室查询的现代实现。
- [zfman/TimetableView](https://github.com/zfman/TimetableView)（MIT，721★）：Android 课程表控件（庄飞）。关键文件 `AndroidTimetableView/TimetableView/src/com/zhuangfei/timetable/TimetableView.java`：周视图矩阵渲染 + **课程重叠自动处理**（同格多卡布局算法）+ 空白格点击。重叠布局算法可平移到 Web 侧（同格多课时并排卡片的宽度分配）。
- [ClassIsland/ClassIsland](https://github.com/ClassIsland/ClassIsland)（GPL-3.0，2713★）：班级多媒体屏幕课表显示工具（Windows）。课表展示层（课程卡 + 倒计时 + 轮播）与"班级门口屏"场景契合；仅思路（GPL 且桌面端）。
- [lynnlingying/wechat-kaoqin](https://github.com/lynnlingying/wechat-kaoqin)（**无 License**，77★）：微信小程序考勤打卡（GPS 打卡/统计）。对考勤卡交互有参考，无 License→仅思路。
- [georgehuan1994/DingDing-Automatic-Clock-in](https://github.com/georgehuan1994/DingDing-Automatic-Clock-in)（**无 License**，979★）：钉钉全自动打卡脚本。仅用于理解钉钉打卡链路与风控边界，**不得搬运**（无授权 + 违反平台规则风险）。

---

## 5. 五类关键交互的实现手法对照

| 交互 | OpenEduCat | CourseArragement | EduScheduler | 组件/其他参考 |
|---|---|---|---|---|
| 周视图矩阵 | Odoo calendar 周视图（Week filter） | 自定义 CSS Grid：时间头+周列、第N节行、时段分组染色 | el-table 行=时间片、列=周一~周五、行高100px | FullCalendar timeGridWeek；TimetableView 重叠布局 |
| 批量排课 | 周模板→实例（timetable 模板展开） | 固定任务+自动排课（时间片模板/禁排/教师上下限） | schedule-templates 模板编辑→周次实例 | CourseSchedulingService（遗传算法） |
| 冲突检测 | 服务端四查（教师/教室/班级/班级+课程），参数门控，±24h 窗口预筛+sudo 全量视野 | 保存校验+状态 alert+冲突任务态 | 拖拽 drop 时班级+教师跨班双接口实时校验，冲突面板+红虚线 | UniTime AssignmentProxy；FET 约束清单 |
| 拖拽调整 | calendar 视图拖拽建课/改期（Odoo 原生） | HTML5 原生 DnD 卡片拖入空格，调课记录+定位回放 | draggable 卡片+目标格绿/红虚线+确认弹窗 | react-big-calendar drag-and-drop；tui.calendar |
| 周次/单双周 | op.session 绝对时间 | 周数由配置决定（动态列） | formatWeeks "1-3,5 周" 缩写、mergeScheduleWeeks | yunxiaozhi 20 周+周弹窗 |

**钉钉式工作台/信息架构可借鉴点（综合 C 类）**：
1. 工作台=应用宫格：图标+名称+角标，可编辑排序（对应本项目门户首页卡片区，参考 `v2-checklist.md` B10 校历聚合思路）；
2. 左侧轻导航 + 顶栏通知中心/待办角标 + 多标签页；
3. 关键操作"就近化"：课表页内直接拖拽调课，冲突即时红/绿反馈，而不是跳表单页；
4. 审批流/调课留痕：仿钉钉流程画布 + 记录回放（CourseArragement 的定位按钮即"钉钉审批详情"式回放）。

## 6. 对本项目的落地适配建议（供 t3 方案参考）

1. **前端排课中心**（Odoo web 中文视图）：优先模仿 CourseArragement 的 `ScheduleView.vue` 交互（教师/班级视角切换 + 周矩阵 + 原生 DnD 调课 + 调课记录），冲突校验仍走 OpenEduCat 服务端四查（本地已固化参数全开），在 drop 前加"班级+教师跨班"前置校验接口（参照 EduScheduler 的 `checkScheduleConflicts` 模式，可先基于 `op.session.search` 实现）。
2. **校历/日程页**（`/my/calendar`，v2-checklist B10）：若需周/月视图，在 QWeb 里引 FullCalendar 或 tui.calendar（均 MIT）做渲染 + 拖拽骨架，事件模型映射 `op.session/edu.event`。
3. **批量排课**：以 EduScheduler"周模板→实例"为数据模型（`op.timing` 表天然是模板结构），自动排课借鉴 CourseArragement 的规则（时间片模板、禁排时段、教师日/周上限），复杂约束求解再参考遗传算法思路（不复用 GPL 代码）。
4. **工作台改造**：应用宫格 + 可排序参考 ant-design-pro ProCard/自定义布局，风格向 vue-vben-admin 的圆角卡片收敛；审批/调课留痕参考 StavinLi/Workflow 画布（若上审批功能）。
5. **移动端（如有）**：周次弹窗翻周参考 yunxiaozhi；周历手势切换参考 NCalendar。
6. **License 合规**：可复用代码仅限 MIT/Apache-2.0/LGPL（OpenEduCat 基座合法已在用）；GPL-3.0 项目（CourseSchedulingSystem、ClassIsland、yunxiaozhi）与无 License 项目只读思路；所有借鉴需在交付文档标注出处。

## 7. License 与可参考程度速查表

| 项目 | License | 可参考程度 | 关键路径 |
|---|---|---|---|
| openeducat/openeducat_erp | LGPL-3.0 | 可直接借鉴（已使用） | openeducat_timetable/models/timetable.py；views/timetable_view.xml |
| javashub/CourseArragement | Apache-2.0 | 可直接借鉴 | UI/coursearrange/src/views/course/ScheduleView.vue、scheduleGrid.js、CoursePlanView.vue |
| Rackar/EduScheduler | Apache-2.0 | 可直接借鉴 | frontend/src/components/schedule/ScheduleAdjustView.vue、WeeklyScheduleView.vue；utils/schedule.js |
| UniTime/unitime | Apache-2.0 | 需改造 | JavaSource/org/unitime/timetable/gwt/client/course/；solver/ |
| lalesculiviu/fet | GPL-3.0（官方） | 仅思路 | 官方文档约束清单 |
| Code-Chen/CourseSchedulingSystem | GPL-3.0 | 仅思路（算法） | UI/my-app/src/ArrangingPage.js；Service/Impl/ClassSchedulingService.java |
| fullcalendar/fullcalendar | MIT | 可直接借鉴 | 日历库 |
| nhn/tui.calendar | MIT | 可直接借鉴 | 日历库 |
| jquense/react-big-calendar | MIT | 需改造（React） | 日历库 |
| yannecer/NCalendar | Apache-2.0 | 需改造（Android） | 日历库 |
| vue-element-admin / ant-design-pro / RuoYi-Vue / vue-vben-admin | MIT | 可直接借鉴（模板） | 工作台/导航/权限 |
| StavinLi/Workflow | MIT | 可直接借鉴 | 审批流画布 |
| mrtylerzhou/AntFlow.net | Apache-2.0 | 需改造（.NET） | 钉钉工作流 UI |
| danbaixi/yunxiaozhi | GPL-3.0 | 仅思路 | pages/course/course.js |
| 214140846/TOGO_School_Miniprograme | 无 | 仅思路 | — |
| wyvern1723/sachet | MIT | 可借鉴 | Flutter 课表 App |
| zfman/TimetableView | MIT | 可直接借鉴 | AndroidTimetableView/TimetableView/src/com/zhuangfei/timetable/TimetableView.java |
| ClassIsland/ClassIsland | GPL-3.0 | 仅思路 | 显示层 |
| lynnlingying/wechat-kaoqin | 无 | 仅思路 | — |
| georgehuan1994/DingDing-Automatic-Clock-in | 无 | 仅思路 | — |

> 注：本调查未发现专门的"钉钉开源工作台模板"成品（钉钉工作台本体为闭源软件），故以"仿钉钉"组件/模板 + 通用中后台模板的组合替代，交互模式以钉钉 App 实际体验为基准在 `t1` 调研中补充。