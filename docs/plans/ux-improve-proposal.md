# 钉钉式排课与应用板块改进提案（ux-improve-proposal）
> **状态**：`已上线` ｜ **主题**：`排课与应用板块改进` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 提出：ux-researcher（ux-rework 团队）｜日期：2026-08-28 ｜ 类型：requirements（round 1，t9 修订 round 2，t11 修订 round 3）
> 文档路径：`docs/plans/ux-improve-proposal.md`（即本文件，供 t4 实施与评审引用）
> round 2 修订（落实 t9 评审意见）：S1 改为扩展既有 CN 视图、S3 复用既有结果模板、学期锚点提取公共模块、W1 空组守卫改为验证项、A1 提醒卡按未读渲染表述、§0/S1/S2/S3 文件路径补全。
> round 3 修订（落实 t11 评审意见）：§1A 工作区既有实现处置决定（冻结+对齐+changedPaths 预期）；S1 载体定为继承官方 `view_op_session_calendar` 并重写验收①/②；S2 唯一公共模块定为 `week_utils.py` 并写死函数契约；S1 color 载体钉死 Integer 0-4 索引（**t14 修订为 Integer 0-3，见 t14 修复行**）；§6 增加批次 0 基线清点。
> t14 修复（B1 实证修订）：S1 color 载体由「Selection 索引 0-3」**改为 `fields.Integer` 计算字段 0-3**——Odoo calendar 前端 `getColor()`（web/static/src/views/calendar/utils.js）仅对 `typeof number` 走 0-55 色板索引档（`((key-1)%55)+1`），Selection 字符串走 hash 分支产生随机色（浏览器实证：官方时间表 15 个事件全部同色 `o_calendar_color_6`）。Integer 0/1/2/3 → `o_calendar_color_0/1/2/3` 四档可区分。
> 最终契约（评审 F10-F13 裁定，船长转达并直接落稿）：① S1 载体=继承官方 `view_op_session_calendar`（时间表根菜单已绑定该视图，实际可见路径），不扩展无菜单绑定的 CN 日历视图，验收①前提同步修正；② 共享工具契约=已落地的 `edu_schedule/models/week_utils.py`（以实际函数名为准）+ 调用点迁移清单；③ S1 颜色机制钉死：Odoo calendar 的 color 字段按 **Integer 计算字段 0-3** 取色（非 hex、非 Selection 字符串），写明索引→色板映射表；④ §6 批次 0 登记 in-flight 文件（状态=冻结待审、归属=t4 engineer）。S2-S5、W1-W3、A1 保持 r2 已核实修订不变。
> 输入依据：
> - `docs/plans/ux-research-dingtalk.md`（t1，钉钉/企微/飞书交互模式调研，下文以「调研 §x.y」引用）
> - `docs/plans/oss-research.md`（t2，开源排课/课表/日历项目调研，下文以「OSS §x.y」引用）
> - 本仓库现状：`docs/plans/ui-reference.md`（B11 门户壳）、`docs/plans/timetable-design.md`（排课系统）、`docs/plans/v2-checklist.md`（v2.1-2.4 已上线批）、`docs/ux-audit.md`（全站审计）
> 铁律：**只做加法/视觉/交互层增强，零功能丢失**——每项标注对既有功能的影响评估与回归方式（全程对照路由清单，参照 B11 §7「零功能丢失对照检查清单」与 `docs/dev-workflow.md`）。

---

## 0. 现状锚点（v2.4 之后的排课与应用板块事实）

| 能力 | 现状实现 | 位置 |
|---|---|---|
| 排课查看/维护 | 官方「时间表」应用（Odoo calendar 周视图，quick-create 弹窗、拖拽建课/改期、filter_session_week 周过滤）；冲突四查（教师/教室/班级/班级+课程）保存时 ValidationError 红字拦截，参数 noupdate 固化全开；官方日历视图 `view_op_session_calendar`（priority=8、string="Sessions"、color=course_id、quick_create=true）被官方 action `act_open_op_session_view` 显式绑定（S1 用 inherit_id 继承着色，分色在官方日历上可见）；门户另有自建中文日历视图 `view_op_session_calendar_cn`（priority=1、color=subject_id，绑定门户侧「周课表」action，不参与官方入口，本次不动） | `openeducat_erp/openeducat_timetable/views/timetable_view.xml`（`view_op_session_calendar` 与 `act_open_op_session_view`，只读依据，不改）、`openeducat_erp/openeducat_timetable/models/timetable.py`（冲突四查，只读依据，不改）、`custom_addons/edu_portal/data/timetable_params.xml`（四查参数固化）、`custom_addons/edu_portal/views/scheduling.xml`（CN 视图，不动） |
| 周期排课 | `/timetable/bulk` 表单式向导：勾选星期几 + 课程/班级/教师/节次/教室 → 预览表 `_build_plan` → 逐条创建（created/failed 计数 + error_msg 文本） | `custom_addons/edu_schedule/controllers/main.py`、`views/templates.xml`（edu_schedule_bulk/edu_schedule_preview） |
| 整周复制 | `/timetable/copy` 表单式：源周日期 + 最多 3 目标周 + skip_existing，无预览、失败静默跳过 | 同上（edu_schedule_copy） |
| 停课管理 | `edu.schedule.holiday`（后台 CRUD + `_matches(day,batch)`），门户侧未呈现 | `custom_addons/edu_schedule/models/holiday.py`、`views/holiday_views.xml` |
| 周课表门户 | `/student/timetable` 四视角（学生/教师/家长/内部）+ 上周/本周/下周（w 参数）+ 未分节行 | `custom_addons/edu_portal/controllers/scheduling.py`、`views/edu_portal_templates.xml` |
| 校历 | `/my/calendar` 月视图聚合：op.session + op.exam + holiday + edu.event，按角色过滤，新建活动冲突红字拦截；`/my/calendar/new` 表单新建 | `custom_addons/edu_portal/controllers/calendar.py`、`views/calendar.xml` |
| 工作台 | `/my/home` 宫格（B11：分组标题行、品牌蓝 FA 瓦片、角标、b11 骨架；v2.3 合并隐藏部分卡片） | `custom_addons/edu_portal/controllers/roles.py`、`views/roles.xml` |
| 申请/审批 | 课程变更 `/course/change/request[/save]`（op.subject.registration，submitted/approved/rejected）、请假 `/my/time_off` + `/leave/approvals` + `/leave/set_state`、投诉 `/my/grievances` | `custom_addons/edu_portal/controllers/batch3.py`、`roles.py`、`views/approval_backend.xml` |
| 打卡 | `/my/checkin[/board/save]` 火焰连击卡 + 三状态大按钮 + 个人打卡月历 + 漏卡横幅 | `custom_addons/edu_life/` |

---

## 1. 总览表（实施优先级 P0/P1/P2）

| # | 改进项 | 优先级 | 排课专项？ | 是否影响既有功能 |
|---|---|---|---|---|
| S1 | 排课网格「冲突分色 + 空闲留白」（继承官方日历视图着色：inherit_id + xpath 改 color） | **P0** | ✅ | 否（视图层增强，冲突拦截逻辑与写路径不动） |
| S2 | 周期排课升级：周次范围/单双周 + 网格预览 | **P0** | ✅ | 否（表单加字段，原参数兼容） |
| S3 | 整周复制加「预览 + 结果页逐条明细」 | P1 | ✅ | 否（新增 preview 路由 + 既有 copy_result 模板扩充，原路径保留） |
| S4 | 周课表门户：当天列高亮 + 日视图 + 第N周标注 + 停课灰显；首页「今日课表」预览卡（教师端在 batch2） | P1 | ✅ | 否（只读增强，URL 与数据域不变） |
| S5 | 校历：周视图 + 列表视图切换 + 今天定位（三色事件） | P1 | ✅ | 否（月视图保留为默认） |
| W1 | 应用面板「常用应用」置顶区（角色化）+ 空组守卫验证 + 更多/常用区空态处理 | P1 | 否 | 否（模板/装配层，URL 不变；置顶区可关） |
| W2 | 应用面板编辑态排序（轻量：上移/下移 + 固定到常用，先不做拖拽） | P1 | 否 | 否（默认顺序=现顺序；偏好本地存储） |
| W3 | 角标 0 值灰底与待办聚合规范落实（审计项） | P2 | 否 | 否（视觉层，沿用 oe_count_zero） |
| A1 | 申请/审批流「待办聚合 + 进度可视化 + 就近操作」 | P2 | 否 | 否（列表页增强 + 首页提醒条加类型） |

---

## 1A. 工作区既有实现处置决定（t4 开工前置 · round-3）

**查明结论（2026-08-28 现场核验）**：
1. **engineer（t4）已提前开工**：`git status` 显示 11 个已跟踪文件被修改（edu_portal/edu_schedule 控制器/视图/manifest，+1548/-106 行）、新增 **9 个本方案相关新文件**（代码 5 个：`session_ext.py`、`week_utils.py`、`session_conflict_view.xml`、`home_favs.js`、`ux_rework.css`；报告 1 个：`ux-implement-report.md`；smoke 测试 3 个：`ux_rework_http_smoke.py` / `ux_week_utils_check.py` / `ux_rework_playwright.py`）；其自述实施说明 `docs/plans/ux-implement-report.md` 声称 S1-S5/W1/W2 已落地并通过本地冒烟（compileall / `-u` 升级 / 逐角色 200 / playwright）。
2. **t9/t11 不越界**：t9 与 t11 的交付物仅为方案文档 `docs/plans/ux-improve-proposal.md`（changedPaths 唯一登记该文件），未触碰任何 `custom_addons/` 代码；工作区实现文件全部归属 engineer 的 t4 实施，无需因 t9/t11 回滚任何代码。
3. engineer 实施与 round-2 方案存在两处待对齐差异（见处置表）：① S1 color 载体：engineer 用 Char 十六进制色值（`conflict_color`），本方案契约要求 Integer 0-4 索引（**t14 最终裁定为 Integer 0-3，见 §S1 契约与 t14 修复行**）；② 公共模块：engineer 已建 `models/week_utils.py`（方案 round-2 写的是 `term_utils.py`），且 `_week_window_utc`/`_active_term` 尚未完成迁移（scheduling.py 仍本地定义、calendar.py 仍有 `_active_term`）。

**处置总则**：**冻结不手工回滚**——保留 engineer 已实施成果及其报告证据（供 t7 评审与用户审查），但**冻结视为"未批准状态"**：自本文件落定起至 t12 评审通过前，任何人不新增/不提交相关实现改动；t12 通过后由调度正式放行 t4，t4 必须按本 round-3 批准版逐项对齐。

**处置表（文件 → 处置 → 对齐要求）**：

| 文件 | 处置 | 对齐要求（t4 职责） |
|---|---|---|
| `custom_addons/edu_schedule/models/week_utils.py` | **采纳并对齐** | 定为唯一公共模块（不新建 term_utils.py）；函数契约见 §S2（以实际函数名为准：`monday_of` / `week_no_of` / `parse_week_ranges` / `week_in_ranges` / `parity_ok` / `term_anchor(env, ref_date)`，已实现，保留）；按 §S2 迁移清单完成调用点迁移（calendar `_active_term`→`term_anchor`；scheduling.py 已接线；`_week_window_utc` 在模块内落位或薄封装，不得双实现） |
| `custom_addons/edu_schedule/models/session_ext.py` | **采纳并对齐** | `conflict_kind`（Char，语义字段）保留；**`conflict_color` 由 Char hex 改为 Integer 计算字段 0-3**（`0`=无冲突默认档 / `1`=教师 / `2`=教室 / `3`=班级，班级+科目归并本档），Odoo calendar 前端 `getColor()` 仅对 number 走 0-55 色板档、字符串走 hash 随机色（t14 B1 实证），Integer 0/1/2/3 → `o_calendar_color_0/1/2/3`，契约见 §S1 |
| `custom_addons/edu_schedule/views/session_conflict_view.xml` | **采纳** | inherit_id 继承 `openeducat_timetable.view_op_session_calendar`（时间表根菜单已绑定该视图=实际可见路径）+ xpath 改 `color`/追加字段——与最终裁定一致，`color="conflict_color"`（Integer 语义）；`view_op_session_calendar_cn`（无菜单绑定）与其并存但不改 |
| `custom_addons/edu_schedule/controllers/main.py`、`views/templates.xml`、`models/__init__.py`、`__manifest__.py` | **采纳并对齐** | S2 周次/单双周 + 周矩阵预览、S3 `/timetable/copy/preview` + copy_result 逐条明细；保持「week_ranges 留空=旧行为」参数兼容；预览红格仅为提示、创建仍走四查 |
| `custom_addons/edu_portal/controllers/scheduling.py` | **采纳并对齐** | S4（view=week/day、今天、第N周、停课灰显）保留；**完成调用点迁移**：`_week_window_utc` 改由 week_utils 提供（或薄封装），删除本地重复实现 |
| `custom_addons/edu_portal/controllers/calendar.py` | **采纳并对齐** | S5 三视图保留；**完成迁移（含 F14 守卫语义）**：删除本地 `_active_term`，改用 `week_utils.term_anchor` 的**薄封装 `term_anchor_or_none`**（保留「今天不在任何学期窗口即 None + `if term:` 不过滤」语义，见 §S2 迁移清单 1）；月视图查询逻辑零变化；t6 增加**寒暑假（无进行中学期）日期回归**，断言月视图不过滤 |
| `custom_addons/edu_portal/controllers/batch2.py`、`views/batch2.xml`、`views/roles.xml`、`views/edu_portal_templates.xml`、`views/calendar.xml` | **采纳并对齐** | W1 常用区（服务端预置 4 件套）+ 空组守卫验证 + 更多区/常用区空态；S4 首页今日课表卡（教师端 batch2）；S5 模板；卡片 URL/图标语义不变 |
| `custom_addons/edu_portal/static/src/js/home_favs.js`、`static/src/css/ux_rework.css` | **采纳** | W2 编辑态（localStorage，无偏好=服务端默认顺序，禁用 JS 回退）；样式随 Selection 色板语义微调 |
| `docs/plans/ux-implement-report.md` | **保留** | 作为 t4 实施证据，供 t7 评审与用户审查；本提案引用其中事实但以本文件契约为准 |
| `tests/smoke/ux_rework_http_smoke.py`、`tests/smoke/ux_week_utils_check.py`、`tests/smoke/ux_rework_playwright.py` | **保留并扩充** | 三个 smoke 测试均属 t4 产物；t6 依据；按 §S1 验收②补冲突分色断言（三种冲突色可区分 + 正常默认色）；ux_rework_playwright.py 补学期窗口/寒暑假回归场景（见 F14 回归项） |
| `tmp_t4_cal_shell.py`、`tmp_t4_http_smoke.py` | **清理** | t4 收尾时删除或移入 `scripts/`，不得留在仓库根 |
| `screenshot_user*.png`、`tmp_t7_nav_test.py` 等与方案无关既有文件 | 不在处置范围 | 非本方案产物，不登记 |

**回滚触发条件**：仅当 t12 评审驳回时，由 t4 按评审意见对**涉事子项**回滚重做（回滚范围=处置表内对应文件，禁止全量回滚已验收无涉的实现）。

**t4 changedPaths 预期（对照登记）**：处置表中全部「采纳/保留并扩充」文件构成 t4 收尾时 `changedPaths` 的**核对清单**；凡超出清单的改动，t4 必须在实施说明中逐条说明原因，t6/t7 以本清单为核对依据。

---

## 2. 排课专项改进（≥3 条要求，共 5 条）

### S1【P0】排课网格「点格即建 + 冲突分色 + 空闲留白」增强

**现状问题**：后台排课主入口（官方时间表 calendar 视图）已支持点 slot 快速建课与拖拽，但网格不区分冲突类型（四查矛盾时统一弹 ValidationError 红字）；门户侧周期排课预览是纯表格行列表，看不到"哪个格已被占/哪个格冲突"。国内行业标书反复要求"图形化方格 + 教室/班级/教师冲突分色 + 空闲格留白"（调研 §2.1，内蒙古/福建采购文件原文）。
**参考依据**：
- 调研 §2.1：方格矩阵 + 三分色冲突（教室/班级/教师）+ 空闲留白（政府采购需求原文归纳）；
- OSS §1.1：OpenEduCat 四查语义（faculty/classroom/batch/batch+subject）可直接映射颜色；
- OSS §1.2 CourseArragement `ScheduleView.vue`：网格 + 卡片含课程/教师/教室三要素 + 冲突提示 alert；
- OSS §1.3 EduScheduler：拖拽 drop 前班级 + 教师跨班双校验、右侧「待处理冲突 (N)」面板。
**建议改法**：
1. 在 `op.session` 上经 `_inherit` 加**只读计算字段 `conflict_kind`**（Char，语义标签）与 **`conflict_color`（Integer 数值 0-3）**，复用现有四查判定口径（±24h 窗口预筛 + sudo 全量 + `state != cancel` 不参与；按课时所属时段周边做一次检查，`store=False` 不落库）。载体：`custom_addons/edu_schedule/models/session_ext.py`，**不改上游 `openeducat_erp/openeducat_timetable/models/timetable.py`**；
2. **S1 载体 = 继承/覆盖官方视图 `view_op_session_calendar`**（新文件 `custom_addons/edu_schedule/views/session_conflict_view.xml`）：**时间表根菜单已绑定该视图**（官方 action `act_open_op_session_view` 显式绑定 `view_op_session_calendar`，经 `ir.actions.act_window.view` 挂到「时间表」根菜单）——即**实际可见路径**，冲突分色将出现在时间表应用的官方日历上；`<record>` 以 `inherit_id ref="openeducat_timetable.view_op_session_calendar"` 继承（快速建课/拖拽/弹窗/过滤全部随之保留），xpath 两处：① `//calendar` 属性 `color` 改为 `conflict_color`；② 在 `//calendar/field[@name='faculty_id']` 后追加 `<field name="conflict_kind"/>`（conflict_color 可 `invisible="1"`）。**不再指定扩展无菜单绑定的 CN 日历视图**（`view_op_session_calendar_cn` 无官方菜单绑定、不参与官方入口，分色在其上不可见——保持原样不动）；
3. **color 载体契约（钉死，t14 B1 实证修订）**：**Odoo calendar 的 `color` 字段必须是 Integer 数值（0-3），不是 Selection 字符串、不是 hex**。前端 `getColor()`（`web/static/src/views/calendar/utils.js`）对 `typeof key === "number"` 走 `((key-1)%55)+1` 色板索引档（0→0、1→1、2→2、3→3 → `o_calendar_color_0/1/2/3`）；对字符串（含 Selection 值）走 hash 分支产生随机档（浏览器实证：Selection 实现下官方时间表 15 个事件全部同色 `o_calendar_color_6`）。`conflict_color = fields.Integer(compute=…)`，compute 返回 0/1/2/3；视图 `color="conflict_color"`。**索引→色板映射表**：

   | 索引值（Integer） | 语义 | 色板档位（Odoo calendar palette） |
   |---|---|---|
   | `0` | 无冲突（正常课时） | `o_calendar_color_0`（默认档，事件默认外观） |
   | `1` | 教师冲突 | `o_calendar_color_1`（红色系档） |
   | `2` | 教室冲突 | `o_calendar_color_2`（橙色系档） |
   | `3` | 班级冲突（班级+科目归并本档） | `o_calendar_color_3`（黄色/琥珀系档） |

   engineer 现行 Char hex 实现（`#DC2626` 等）**不符合该机制**，按 §1A 处置表对齐为 Integer 0-3；t14 B1 实证 Selection 字符串同样失效（hash 随机色），**契约钉死 Integer 数值**；若冒烟证明所选索引档位渲染与预期不符，按 §1A「对齐分支」调整索引→色板映射并复跑断言（契约仍是 Integer 数值，不退回 hex/Selection）；
4. 冲突拦截保留服务端四查原逻辑（四个 `timetable.*` 参数与上游 constrains 一律不动），失败提示的「替代建议」**P0 版本明确降级为弹窗文案提示**（在现有 ValidationError 展示处追加一句"可尝试：同一教室其他空时段 / 同时段其他空教室"，**不动任何写路径，无评审豁免需求**）；若后续升级为 `session_ext.py` 的 create/write override 式自动推荐（P2 候选），则该 override **列入与计算字段同等的评审豁免**，并标注回归点：新建/编辑/批量/整周复制四条写路径仍必须触发四查拦截、门户只读视图（`/student/timetable`、`/my/calendar`）行为零变化、`op.session` 状态流转（cancel 等）不受影响；
5. 门户周期排课预览改为**节次×星期网格预览**（见 S2）。
**涉及文件与路由**：`custom_addons/edu_schedule/views/session_conflict_view.xml`（新，inherit_id 继承官方视图）、`custom_addons/edu_schedule/models/session_ext.py`（新，conflict_kind/conflict_color 计算字段）、`custom_addons/edu_schedule/models/__init__.py` + `__manifest__.py`（注册）；`custom_addons/edu_portal/views/scheduling.xml`、`custom_addons/edu_portal/data/timetable_params.xml` 只读不动；上游 `openeducat_erp/openeducat_timetable/` 零改动；后台菜单「时间表」（parent=341）不动。无新路由。
**风险**：计算字段在周窗口内 O(周课时数²) 可接受（与四查同构的窗口预筛 + 内存比较）；Integer 0-3 为 Odoo calendar 官方 color 字段取色机制（`getColor()` number 分支 → 0-55 色板档位，t14 浏览器探针断言兜底）；继承视图零删除零覆盖（官方视图记录不变，仅新增继承）。**验收①（最终契约前提）**：**实际可见路径=后台「时间表」根菜单所挂官方日历（`view_op_session_calendar`）**——升级后进入时间表应用官方日历，确认 **官方日历英文标题保持（不引入 CN 视图；CN 视图无菜单绑定，不在验收范围）、既有 quick-create/拖拽/过滤行为保持原样、冲突分色在该官方日历上可见**。**验收②（可断言形式）**：**同一教师/教室/班级冲突课时在日历上呈三种可区分颜色，正常课时保持默认色**；断言方式=t4 截图存档（shots 惯例）+ t14 浏览器探针（`tests/smoke/ux_rework_playwright.py` 扩充或独立脚本：登录后台打开时间表日历，抓取事件元素 class，断言存在 ≥2 种可区分的 `o_calendar_color_N` 且无冲突档与冲突档不同）。回归：`/student/timetable`、`/my/calendar`、后台三视图（应用网格/课时列表/排课日历）逐一截图对比。

### S2【P0】周期排课升级：周次范围 / 单双周 + 网格预览

**现状问题**：`/timetable/bulk` 只能"勾选星期几"整窗批量铺课，无法表达"第 1-16 周每周一三"或"单周/双周"这类国内课表最普遍的周期形态；预览是行列表格，看不出周矩阵形态与冲突位置。
**参考依据**：
- 调研 §4.1：钉钉排班四法之「按周期」与「单双周循环」（14 天周期、6+5 天交替），以及 set-alternating-week 帮助页；
- OSS §1.3 EduScheduler：`formatWeeks()` 周次缩写"1-3,5 周"、`mergeScheduleWeeks()` 多周次合并展示；周模板→实例数据模型（`op.timing` 天然是模板结构）；
- OSS §4 yunxiaozhi：20 周周次模型 + 周数弹窗。
**建议改法**：
1. `/timetable/bulk` 表单增加 **「周次范围」输入**（语法与 EduScheduler 一致：`1,3-5,8-12`，留空=整学期默认）+ **「每周/单周/双周」单选**；
2. **学期锚点/周窗口公共化（贯穿 S2/S4/S5，先行落地；唯一模块契约写死）**：公共模块**唯一确定为 `custom_addons/edu_schedule/models/week_utils.py`**（已落地；不新建 term_utils.py）。**函数契约以实际函数名为准（固定，t4 不得改名改参）**：
   - `monday_of(day)`：day 所在自然周的周一（本地日期）；
   - `week_no_of(day, anchor)`：day 在 anchor 锚点下的周次（≥1），anchor 为空返回 None；
   - `parse_week_ranges(spec)`：`'1,3-5,8-12'` → 升序去重周次列表，空/非法 → None（=全部周）；
   - `week_in_ranges(week_no, ranges)`：周次命中判定，ranges 为 None 恒 True；
   - `parity_ok(week_no, parity)`：单双周判定（weekly/odd/even），无周次视同每周；
   - `term_anchor(env, ref_date)`：**三级回退语义（以 week_utils.py 已实现为准，契约与此对齐）**——返回 ref_date 所在进行中学期的起日；无进行中则回退「最近已过去学期」起日，再退「最早学期」起日；**仅库中完全无学期记录时返回 None**。调用方如需「不在任何学期窗口内即不锚定」的守卫语义，必须自行做 in-window 判定（见迁移清单 1 的薄封装要求），不得依赖 term_anchor 返回 None。
   **调用点迁移清单（最终裁定）**：
   1. `edu_portal.controllers.calendar._active_term`（calendar.py:72）→ **薄封装迁移，保留既有 None 守卫语义**：删除本地重复实现，改为封装 `term_anchor_or_none(env, ref_date)`（calendar.py 内私有函数：`term_anchor` 返回 None 或 **ref_date 不在该学期窗口内（term_start_date ≤ ref_date ≤ term_end_date）时返回 None**，否则返回学期记录）；月视图 `if term:` 守卫与查询逻辑零变化。**关键行为约束：寒暑假等「今天不在任何学期窗口」场景，月视图必须保持「不过滤」路径（对照迁移前截图），禁止直接调用 term_anchor 造成按回退锚点过滤**；
   2. `edu_portal.controllers.scheduling.py` **已接线**（scheduling.py:21-22 已 `from odoo.addons.edu_schedule.models.week_utils import monday_of, term_anchor, week_no_of`），按上表继续使用，不得回改；
   3. **S4「第 N 周」** → `week_utils.week_no_of` / `term_anchor`（scheduling.py 周次标注路径，已接线）；
   4. **S5 周窗口** → 统一走 `week_utils`（周窗口工具 `_week_window_utc` 现驻 scheduling.py:38、calendar.py 反向 import——对齐动作：在 week_utils 内落位或经其薄封装，调用点改自 week_utils 导入，**不允许双实现**）。
   edu_schedule 不依赖 edu_portal，`edu_portal` manifest 已 depends `edu_schedule`，反向 import 无循环。**t6 回归校历月视图 / 周课表周界行为零变化（与既有截图对照，如 `shots/` 下 timetable 系列截图；周界跨 UTC 行为不变）**；
3. 预览升级为**网格预览**：每周几一行（或一行多周列），命中周次打勾显示、灰色格＝停课日（读 `edu.schedule.holiday`）、红色底＝与既有课时冲突的格；确认后沿用 `/timetable/bulk/create` 创建（逐条 try/except 不变）；
4. 原参数全部兼容：不填周次范围时行为与现状完全一致（**零丢失**）。
**涉及文件与路由**：`custom_addons/edu_schedule/models/week_utils.py`（唯一公共模块）、`custom_addons/edu_schedule/controllers/main.py`（`_build_plan` 增加 week_ranges 解析与网格投影、预览渲染数据）、`custom_addons/edu_schedule/views/templates.xml`（edu_schedule_bulk/edu_schedule_preview 模板改网格）、`custom_addons/edu_portal/controllers/calendar.py` + `scheduling.py`（调用点迁移至 week_utils，行为不变）。路由 `/timetable/bulk`、`/timetable/bulk/preview`、`/timetable/bulk/create` 不变。
**风险**：低。周次解析为纯函数（可单测）；停课/冲突仅为预览着色，不改变创建逻辑；创建仍走四查兜底。回归：用现有一笔"每周三 2 节"参数跑 bulk，确认生成结果与旧版一致。

### S3【P1】整周复制加「预览 + 逐条结果明细」

**现状问题**：`/timetable/copy` 表单提交后直接执行，看不到"源周哪些课时将落在目标周的哪个格"，skip_existing 静默跳过、无逐条反馈；冲突场景下难以核对。
**参考依据**：调研 §3.1（钉钉日历新建弹窗的即时反馈）、OSS §1.2 CourseArragement 调课记录表（调整前→后 + 定位按钮，操作留痕透明化）。
**建议改法**：
1. 新增 **`/timetable/copy/preview`**（POST，复用 `/timetable/copy` 表单同款参数）：解析源周课时清单，按目标周投影为周网格预览，冲突格标红 + 标注"将跳过（原因）"；纯读操作，不创建任何 session；
2. `/timetable/copy/run` 执行后跳既有结果页，**在既有 `edu_schedule_copy_result` 模板上扩充逐条明细**（每条：课时名、源日期→目标日期、「已复制 / 跳过（原因：已存在 / 停课日 / 冲突）」），**复用 `main.py` 现有 groups/结果模板渲染结构，不新建第二套结果页**；
3. 保留原表单字段与默认值（skip_existing 仍默认勾选），原 `/timetable/copy` GET 直接提交路径不受影响（零丢失）。
**涉及文件与路由**：`custom_addons/edu_schedule/controllers/main.py`（新增 preview 路由 + 投影工具，可复用 S2 的网格投影函数与 week_utils 周窗口）、`custom_addons/edu_schedule/views/templates.xml`（edu_schedule_copy_result 扩充逐条明细区块）。**新建路由，不动既有路由行为**。
**风险**：低；预览纯读，结果仅扩充既有模板区块；回归：现有 copy 流程重跑一次，核对课时数与"已复制/跳过"汇总一致。

### S4【P1】周课表门户「今天定位 + 日视图 + 周次标注 + 停课灰显」；首页「今日课表」预览卡

**现状问题**：`/student/timetable` **已有 上周/本周/下周 导航与「（本周）」标识**（w 参数），缺**当天列高亮、日视图、第 N 周标注、停课灰显**——用户翻到非本周时没有"回到今天"的视觉锚点，停课日（holiday）在格上无体现（学生看到停课日的课格照常显示）；`/my/home` 无今日课表预览（家长/学生每天进课表页看"今天上什么"）。
**参考依据**：
- 调研 §2.2/§3.1：超级课程表桌面卡片（课程名+时间+教室钉在桌面）+ 周/日视图切换；钉钉日历"今天"定位与移动端三日视图、每周起始日；
- OSS §4 yunxiaozhi 周次弹窗/now_week、NCalendar 周日历"当前时间线"指示。
**建议改法**（**新增部分仅为以下四项，其余一律不动**）：
1. **当天列高亮边框**：本周视图（w=0）下当天列加高亮边框（沿用现有 nav 的 `w` 参数与「本周」判断，仅模板层加类）；
2. **日视图 `view=day`**：同一渲染函数按单日窗口截取（数据域逻辑复用，零模型改动），导航区加「今天」链接（`w=0&view=day`）；
3. **周次标注**：周标题旁显示「第 N 周」（复用 S2 唯一公共模块 `custom_addons/edu_schedule/models/week_utils.py` 的 `week_no_of`/`term_anchor`，契约见 S2）；
4. **停课灰显**：holiday `_matches(day, batch)` 命中的日期列/格加灰底 + 斜杠角标（只读，不改数据）；另 `/my/home` 新增**「今日课表」预览卡**（学生/教师/家长角色可见）：取当日 ≤5 条课时（名称+节次+教室），点击进 `/student/timetable?view=day`；卡片不渲染时（无课/纯空）显示"今日无课，查看本周课表"（空态范本，参照 ux-audit §3.3）。
**涉及文件与路由**：`custom_addons/edu_portal/controllers/scheduling.py`（view=day 参数 + 周次标注数据 + holiday 交并）、`views/edu_portal_templates.xml`（高亮/日视图/灰显模板）；今日课表预览卡：学生/家长分支在 `custom_addons/edu_portal/controllers/roles.py` + `views/roles.xml`，**教师分支在 `custom_addons/edu_portal/controllers/batch2.py`（教师工作台数据组装，批次 B8 起）+ `views/batch2.xml`（教师工作台模板）**。路由 `/student/timetable` 不变（参数新增）。
**风险**：中低。日视图/周次/灰显均为只读计算；停课灰显需 `edu.schedule.holiday` 权限确认（内部用户 sudo 读，门户只读展示）；今日课表卡为新增卡片（v2.3 已删卡为先例，新增同样安全）。零丢失：周视图默认形态、上周/本周/下周导航、四视角数据域、空表兜底（guest=空表）全部保留。

### S5【P1】校历「周视图 + 列表视图 + 今天定位」（三色事件）

**现状问题**：`/my/calendar` 月视图信息密度对"本周课表 + 考试 + 活动"的日常心智不够（月格放不下多课时），无周视图/列表视图切换；无"今天"定位。
**参考依据**：调研 §3.1：钉钉日历 5 视图一键切换（列表/日/周/月 + 移动三日视图）、每周起始日；OSS §2：FullCalendar timeGridWeek / tui.calendar 中文周视图（均 MIT，可作渲染内核或仅参照交互）；OSS §5 五类交互对照表。
**建议改法**：
1. 校历页顶部加**视图切换**（月/周/列表，默认仍为月，零变化）；周视图复用 S4 周课表网格样式，但单元格按来源三色：课程（蓝）、考试（红）、活动（青绿）+ 停课灰显——同一"周网格"组件在课表页与校历页复用；
2. **「今天」按钮**：月视图回当月、周视图回本周并高亮当日；列表视图=按日分组的紧凑议程（钉钉"列表视图"同款，可扫读）；
3. 活动新建仍走 `/my/calendar/new` 表单（不做拖拽/循环，见 §5 暂不做清单）。
**涉及文件与路由**：`custom_addons/edu_portal/controllers/calendar.py`（view 参数 + 周窗口/学期锚点查询统一改走 `edu_schedule.models.week_utils`——周窗口与 `term_anchor` 按 §S2 迁移清单，月视图查询逻辑不动）、`views/calendar.xml`（周/列表模板）。路由 `/my/calendar` 不变（参数新增）。
**风险**：低；纯视图层新增，月视图默认保留，查询域复用现有 role_scope 过滤。周窗口/学期锚点函数统一使用 S2 唯一公共模块 `week_utils.py`，调用点迁移由 t4 完成，t6 回归校历月视图/周课表周界零变化（对照既有截图）。

---

## 3. 应用板块 / 工作台改进

### W1【P1】「常用应用」置顶区（角色化）+ 空组/常用区空态处理（守卫为验证项）

**现状问题（已核验）**：`/my/home` 宫格已有分组标题（B11）；**控制器已实现空组过滤**——`custom_addons/edu_portal/controllers/batch2.py:508`：`if not gcards and key != 'portal_more_category': continue`（空组不渲染标题行，`portal_more_category`「更多」组是刻意保留的例外）；无"常用"首屏区。
**参考依据**：调研 §1.1 钉钉金刚区（常用+全部双层）；§1.2 企微「没有添加任何常用应用时，工作台不显示‘常用’区域」原文；飞书「我的常用」小组件（调研 §1.3）。
**建议改法**：
1. 首页宫格顶部新增**「常用应用」区**：按角色预置 4 件套——学生：课表/打卡/校历/作业；教师：教学安排/打卡统计/校历/消息；家长：孩子的课表/校历/消息/通讯录；内部：校历/课表/审批/后台入口。URL 全部复用现有卡片（不改路由）；
2. **空组守卫=验证项而非新建项**：先回归验证既有 `batch2.py:508` 空组过滤行为（角色无权时整组标题不渲染），确认 v2.3 合并隐藏卡片后无空组标题残留；仅补两处空态处理：① `portal_more_category`（更多）自身无卡片时的空态（当前为刻意例外，需补"无更多项则隐藏该组"或空态文案，避免"更多"空组占位）② 新增「常用区」自身的空态（无常用卡时不渲染该区，企微「无常用则无常用区」原则）；
3. 与 W2 联动：用户可在编辑态把任意卡片加/移出常用（本地存储优先，见 W2）。
**涉及文件与路由**：`custom_addons/edu_portal/controllers/batch2.py`（home 卡片装配加常用组 + 更多组空态分支，过滤器本体不动）、`custom_addons/edu_portal/views/batch2.xml` + `views/roles.xml`（模板）。`/my/home` 路由不变。
**风险**：低；纯装配与模板层，卡片 URL/图标语义不动（B11 §7 入口核对照做）；用户有偏好时置顶区内容随 W2 存储。回归：默认（无偏好）渲染与改造前逐组对照一致，`portal_more_category` 有卡/无卡两种态各验证一次。

### W2【P1】应用面板编辑态排序（轻量：上移/下移 + 固定到常用）

**现状问题**：宫格顺序固定（roles.py 列表序），用户无法把高频应用前置；"进应用后找不回面板"已由面包屑解决（A7），但"面板内排序偏好"无解。
**参考依据**：调研 §1.2 企微「编辑工作台」拖拽排序（交互范式：编辑态才出现排序操作，桌面 hover「…」渐进披露）；OSS §3 ant-design-pro 可拖拽布局/工作台。
**建议改法**：
1. 桌面 hover 卡片右上角出现「⋯」→ 菜单含「固定到常用 / 取消固定 / 上移 / 下移」；移动端进「编辑」模式后卡片出现上下箭头（长按拖拽留待 P2 评估，见 §5）；
2. 偏好第一版存 **localStorage**（键 `home_card_order_<role>`），零后端改动；若后续要跨设备同步再评估加 `res.users` 字段（列入暂不做）；
3. 默认顺序 = 现状顺序（未设偏好时渲染完全一致，**零丢失**）。
**涉及文件与路由**：`custom_addons/edu_portal/views/roles.xml` + `custom_addons/edu_portal/static`（portal 资产新增小 JS，仅 DOM 排序，不改任何业务逻辑与选择器；参照 B11 §7 交互核对纪律）。
**风险**：中低；JS 只重排本地卡片 DOM + localStorage 读写；禁用 JS 时页面回退为默认顺序（渐进增强）。回归：无偏好浏览器与改造前渲染一致。

### W3【P2】角标 0 值灰底与待办聚合规范落实（审计项）

**现状问题**：ux-audit 与 B11 §6.3 已定"0 值灰底角标、红点仅提醒不计数"规范，但存在未覆盖页（如消息/布告栏角标个别页面仍显 0）。
**参考依据**：调研 §1.1 钉钉宫格角标（0 值灰底惯例）；B11 §6.3 既有令牌。
**建议改法**：全站扫一遍 `oe_count_zero` 覆盖情况，漏网页统一套用；首页提醒条/dashboard 提醒区按类型聚合（待审批/未读消息/打卡异常），保持角标只读引擎数据（B5/B9）；**纯视觉/文案层，零逻辑改动**。
**涉及文件与路由**：`views/roles.xml`、`views/messages.xml`、`views/batch2.xml`（角标模板）等，以扫描结果为准。
**风险**：极低。

---

## 4. 审批 / 流程（P2）

### A1【P2】申请类流程「待办聚合 + 进度可视化 + 就近操作」

**现状问题**：课程变更 `/course/change/request`、请假 `/my/time_off`、投诉 `/my/grievances` 各自为页；审批动作（`/leave/approvals`、`/leave/set_state`）分散，无"待我处理"聚合；申请单无进度条可视化。
**参考依据**：调研 §5.1 钉钉审批（待办三入口聚合、同意/拒绝/转交/退回/加签动作集、进度可视化）；OSS §3 StavinLi/Workflow 审批流画布（前端范式，仅作方向参考）。
**建议改法**：
1. **首页提醒区 `portal_alert_category`（通知折叠区，`batch2.xml` 模板既有）改为按未读动态渲染提醒卡**：有未读/待办时才展开对应提醒卡（待审批、未读消息、打卡异常按角色分域），无未读时折叠不占位——提醒卡内容与链接由控制器按 `_alert_counts` 结果装配，目标：待办聚合 + 直达处理页（不新建页面）；
2. 详情页顶部**「同意 / 驳回」常驻主行动** + 状态进度条（申请→审批→生效三段，状态字段已有：submitted/approved/rejected）；
3. 审批通过后**经 B5 通知引擎**通知申请人（"你的课程变更已批准"）；调课类后续若落 session 变更再评估自动联动（涉及写课时，列入暂不做，见 §5）。
**涉及文件与路由**：`custom_addons/edu_portal/controllers/batch2.py`（`_alert_counts` 调用点按未读装配提醒卡）、`views/batch2.xml`（`portal_alert_category` 折叠区动态渲染）、`custom_addons/edu_portal/controllers/batch3.py`（列表/详情增强）、`views/approval_backend.xml`、`views/edu_portal_templates.xml`。
**风险**：中。**实施前由 t4 核对 `_alert_counts`（batch2.py:272）数据来源与各提醒卡计数口径**（哪些来源参与未读、按角色如何分域），以及 `/leave/set_state` 的既有副作用（是否已通知/是否改数据）；本项只做展示层动态渲染，不新增写路径；零丢失：原列表页与提交入口不变，`portal_alert_category` 无未读时的折叠态为既有行为基准。

---

## 5. 明确暂不建议做（含理由，防止范围蔓延）

| 项 | 理由 | 依据 |
|---|---|---|
| 校历拖拽建事件 / 循环事件 | v2.1-B10 已拍板"不做拖拽/循环事件"；循环事件需要重复规则数据模型与展开一致性方案，属于数据层决策 | `docs/plans/v2-checklist.md` B10；调研 §3.1 重复日程仅为参照 |
| 自动排课引擎（遗传算法/约束求解） | 工程量巨大；校园规模（神学院单班课表）手工+周期排课已够；GPL 项目只能看思路（OSS §1.4/§1.6），timetable-design.md 也已砍批量生成向导 | OSS §1.4、§1.5；timetable-design §二 |
| 拖拽调课（DnD）全量上线 | 需原生 DnD 前端 + drop 前"班级+教师跨班"双接口校验（OSS §1.3 模式）+ 调课记录表；工程中量，且与 Odoo calendar 既有拖拽能力部分重叠。先完成 S1/S2 的点格+分色+预览，P2 再评估 | OSS §1.2、§1.3；调研 §2.1 |
| 替换服务端冲突引擎 | 现有四查（±24h 窗口预筛 + sudo 全量）已固化并被真机验收，任何替换都触碰"冲突拦截"这条安全底线；只做交互层增强 | timetable-design §二；OSS §1.1 |
| 审批流画布（StavinLi/Workflow 式可视化流程设计器） | 前端重写成本高，现有 form 审批 + 状态流转满足当前场景；委托/会签/条件分支属于组织流程能力，超出本批次 | OSS §3 |
| 移动原生 App / 小程序 | 无移动端矩阵规划；门户响应式（B11 移动 Tab）已覆盖；超级课程表/NCalendar 仅作为 H5 交互参照 | 调研 §2.2；OSS §4 |
| 宫格排序的服务端持久化（res.users 字段） | 跨设备同步是低频需求；localStorage 方案（W2）零迁移风险，先用后评 | — |

---

## 6. 实施顺序与零功能丢失回归

```
批次0（基线清点，t4 开工第一步）：git status 盘点 edu_schedule/edu_portal 未跟踪/未提交改动
  → 对照下方「in-flight 登记表」与 §1A 处置表逐文件落实「保留（采纳并对齐）/ 回滚重做 / 清理」
  → 形成 t4 changedPaths 核对依据（逐项勾稽）→ 冻结状态解除，进入批次 1

批次0 · in-flight 实现文件登记表（防审计盲区；状态统一=冻结待审，归属统一=t4 engineer）：
| 文件 | 状态 | 归属 |
|---|---|---|
| custom_addons/edu_schedule/models/session_ext.py | 冻结待审 | t4 engineer |
| custom_addons/edu_schedule/models/week_utils.py | 冻结待审 | t4 engineer |
| custom_addons/edu_schedule/views/session_conflict_view.xml | 冻结待审 | t4 engineer |
| custom_addons/edu_schedule/controllers/main.py（增量） | 冻结待审 | t4 engineer |
| custom_addons/edu_schedule/views/templates.xml（增量） | 冻结待审 | t4 engineer |
| custom_addons/edu_schedule/models/__init__.py、__manifest__.py（增量） | 冻结待审 | t4 engineer |
| custom_addons/edu_portal/controllers/scheduling.py、calendar.py、batch2.py（增量） | 冻结待审 | t4 engineer |
| custom_addons/edu_portal/views/edu_portal_templates.xml、calendar.xml、batch2.xml（增量） | 冻结待审 | t4 engineer |
| custom_addons/edu_portal/static/src/js/home_favs.js、static/src/css/ux_rework.css | 冻结待审 | t4 engineer |
| tests/smoke/ux_rework_http_smoke.py、tests/smoke/ux_week_utils_check.py、tests/smoke/ux_rework_playwright.py | 冻结待审（收尾扩充与 t6 依据） | t4 engineer |
| tmp_t4_cal_shell.py、tmp_t4_http_smoke.py | 冻结待审（收尾清理） | t4 engineer |
| tests/smoke/ux_rework_f14_calendar_check.py、ux_rework_f14_summer_e2e.py、ux_rework_s1_batch_probe.py | t6 新增回归脚本（保留并扩充） | t6 engineer |
| custom_addons/edu_schedule/models/session_ext.py（t6 批量计算修复 + t14 B1 Integer 载体）、week_utils.py（t6 周窗口 `week_window_utc` 落位）、edu_portal/controllers/scheduling.py（t6 `_week_window_utc` 薄封装转发） | t6/t14 修复入账（详见 local-regression.md §4.2 与 ux-implement-report.md §5 补记） | t6/t14 engineer |

  （冻结待审=自本文件落定至 t12 评审通过前不得新增/提交改动；对齐基准=§1A 处置表 + 本文件 S1/S2 契约；t6/t14 修复行以 local-regression.md 与 ux-implement-report.md 为准）

批次1（P0，排课交互核心）：S1 冲突分色（继承官方视图+Integer 0-3 色板）→ S2 周次/单双周+网格预览+week_utils 迁移
批次2（P1，排课与校历视图）：S3 复制预览 → S4 门户今天/日视图/周次/停课灰显+今日课表卡 → S5 校历周/列表视图
批次3（P1，工作台）：W1 常用区+空组守卫验证与更多/常用区空态 → W2 编辑态排序
批次4（P2）：W3 角标审计 → A1 审批聚合（先核对 _alert_counts 数据来源与 set_state 副作用）
```

每批回归（铁律，参照 B11 §7 与 dev-workflow）：
1. 路由全量核对：`scripts/check_english.py` ROUTES 基线逐角色跑通（学生/教师/家长/内部/匿名），与本批改动前后各一次；
2. 入口核对：`/my/home` 每张卡片 URL/标题/图标/角标行为与改造前一致（截图对比，shots 惯例）；排课后台三视图（应用网格/课时列表/排课日历）逐项截屏；
3. 交互核对：本批只允许动模板/视觉/新增只读参数，禁止改 JS 业务逻辑与既有写路径（S1 计算字段、S2/S3 新建路由除外，走评审）；
4. 数据核对：S2 周次解析、S3 预览、S4 周次锚点三处共用 `custom_addons/edu_schedule/models/week_utils.py` 同一工具（函数契约见 §S2，`tests/smoke/ux_week_utils_check.py` 覆盖 parse_week_ranges/parity_ok/week_no_of 边界用例）；`_week_window_utc`/`_active_term` 迁移后行为零变化（t6 对照既有校历月视图/周课表周界截图）；S1 `conflict_kind`/`conflict_color` 计算字段按"同教师/同教室/同班级"三组样例断言取值（Integer 0/1/2/3），且 **t14 浏览器探针断言官方日历三档冲突色可区分（验收②，`o_calendar_color_N` class）**；
5. 无障碍抽查：正文 ≥15px、点击区 ≥44px、focus 可见、prefers-reduced-motion（B11 §6）。

---

## 7. 参考依据索引

- 调研（t1）§1.1/§1.2/§1.3 工作台与常驻区；§2.1/§2.2 排课行业标准与超级课程表；§3.1 日历五视图/重复日程；§4.1/§4.2 考勤排查与就近操作；§5.1 审批三入口；§6 桌面/移动差异与 6 条通用原则
- OSS（t2）§1.1 OpenEduCat 四查；§1.2 CourseArragement；§1.3 EduScheduler；§2 FullCalendar/tui.calendar；§3 工作台模板；§4 yunxiaozhi/NCalendar/TimetableView；§7 License 速查（可复用仅 MIT/Apache-2.0/LGPL）

## 8. 验收自检

- 本文件存在：`docs/plans/ux-improve-proposal.md` ✅
- 改进项 ≥5 条：S1-S5 + W1-W3 + A1 = 9 条 ✅（每条含现状/依据/改法/文件路由/风险）
- 排课专项 ≥3 条：S1/S2/S3/S4/S5 = 5 条 ✅
- 优先级 P0/P1/P2 与零功能丢失影响评估：§1 总览表 + 每条"风险"小节 ✅
- 暂不建议项：§5 七项 ✅
- round 2 评审意见落实：S1 扩展既有 `view_op_session_calendar_cn`（含验证方式）；S4 现状修正（已有本周导航）+ batch2 教师工作台文件；S3 复用既有 `edu_schedule_copy_result`/groups 结构；学期锚点与周窗口工具提取至公共模块（签名兼容，edu_portal 反向 import）；W1 空组守卫改为验证项 + 更多/常用区空态；S1 替代建议 P0 降级为文案提示；§0 与 S1/S2/S3 文件路径补全（`openeducat_erp/openeducat_timetable/…`、`custom_addons/edu_portal/data/timetable_params.xml`）；A1 改为提醒卡按未读动态渲染（portal_alert_category）并落实 t4 核对 `_alert_counts` ✅
- round 3 评审意见落实：§1A 处置决定（查明 engineer 提前开工→冻结+逐文件处置表+t4 changedPaths 预期；t9/t11 不越界）；S1 载体=inherit_id 继承官方 `view_op_session_calendar`，验收①重写（官方标题/quick-create/拖拽/过滤保持+分色在官方日历可见）；S2 唯一公共模块=`edu_schedule/models/week_utils.py`，函数契约写死（含周窗口落位与 active_term 收敛），t4 迁移调用点、t6 回归月视图/周界零变化；§6 批次 0 基线清点 ✅
- 最终契约（F10-F13 裁定 + t14 B1 实证修订）落实：① S1 载体=继承官方 `view_op_session_calendar`（时间表根菜单已绑定=实际可见路径），不再扩展无菜单绑定的 CN 日历视图，验收①前提=时间表根菜单官方日历上验证（英文标题保持/冲突色区分可见）；② 共享工具契约=已落地 `edu_schedule/models/week_utils.py`（以实际函数名 `monday_of`/`week_no_of`/`parse_week_ranges`/`week_in_ranges`/`parity_ok`/`term_anchor` 为准），迁移清单=calendar `_active_term`→`week_utils.term_anchor`、scheduling.py 已接线（scheduling.py:21-22）、S4 第N周/S5 周窗口统一走 week_utils（周窗口落位/薄封装、禁双实现）；③ S1 颜色机制钉死=**Odoo calendar color 字段按 Integer 数值（0-3）取色（`getColor()` number 分支 → `o_calendar_color_0-3`），非 hex、非 Selection 字符串**，索引→色板映射表（0默认/1教师/2教室/3班级）已写入 §S1；④ §6 批次 0 登记 in-flight 文件表（状态=冻结待审、归属=t4 engineer，含 session_ext.py/week_utils.py/session_conflict_view.xml/main.py·templates.xml 增量/tests/smoke/ux_*/tmp_t4_*）；S2-S5、W1-W3、A1 保持 r2 已核实修订不变 ✅
- verify 命令：`grep -q 'ux-improve-proposal' docs/plans/ux-improve-proposal.md && wc -l docs/plans/ux-improve-proposal.md`