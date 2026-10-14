# ux-rework t4 实施说明（ux-implement-report）
> **状态**：`归档` ｜ **主题**：`门户体验改进 t4` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 实施：engineer（ux-rework 团队）｜2026-08-28 ｜ 依据：`docs/plans/ux-improve-proposal.md`（t3）
> 范围：`custom_addons/edu_portal`、`custom_addons/edu_schedule`、`custom_addons/edu_brand`（未改动）、`docs/plans`
> 铁律：只美化零功能丢失；不新增数据模型；不部署云端。

## 0. 结论

- P0 两项全部落地：S1（排课网格冲突分色）、S2（周期排课周次/单双周 + 周矩阵预览）。
- P1 五项全部落地（100% > 80%）：S3（整周复制预览 + 逐条明细）、S4（周课表门户今天/日视图/第N周/停课灰显 + 首页今日课表卡）、S5（校历周/列表视图 + 今天定位 + 三色事件）、W1（常用应用置顶区 + 空分组守卫）、W2（编辑态固定/排序，localStorage）。
- P2 两项（W3/A1）不在验收线内；W3 的 `oe_count_zero` 灰底角标在 v2 首页网格已落实（既有模板）——本次未新增 P2 改动。
- 验证证据见 §5：compileall 通过；docker compose -u 一次通过（Modules loaded 计数 ≥1，无 ERROR/CRITICAL）；关键路由逐角色 200；playwright 交互冒烟通过。

## 1. 交付清单（changed paths）

| 路径 | 内容 |
|---|---|
| `custom_addons/edu_schedule/models/week_utils.py` | 新增：周次工具（锚点/周次/单双周/周次范围解析），S2/S3/S4 共用 |
| `custom_addons/edu_schedule/models/session_ext.py` | 新增：`op.session` 计算字段 `conflict_kind` / `conflict_color`（S1） |
| `custom_addons/edu_schedule/models/__init__.py` | 新增两模型模块导入 |
| `custom_addons/edu_schedule/views/session_conflict_view.xml` | 新增：日历视图继承（color=conflict_color 红/橙/黄分色） |
| `custom_addons/edu_schedule/controllers/main.py` | S2 周次/单双周 + 周矩阵；S3 `/timetable/copy/preview` + 逐条明细 |
| `custom_addons/edu_schedule/views/templates.xml` | bulk 表单加周次/单双周；预览改周矩阵 + 折叠明细；复制预览模板；结果页逐条展开 |
| `custom_addons/edu_schedule/__manifest__.py` | 版本 19.0.2.1.0；data 增 `session_conflict_view.xml` |
| `custom_addons/edu_portal/controllers/scheduling.py` | S4：`view=week/day`、今天定位、第 N 周、停课灰显（`edu.schedule.holiday` sudo 只读） |
| `custom_addons/edu_portal/controllers/calendar.py` | S5：`view=month/week/list` 三视图 + 今天定位；查询/归桶抽取共用方法（月视图逻辑不动） |
| `custom_addons/edu_portal/controllers/batch2.py` | W1 常用应用置顶组 + `_home_role/_build_favorites`；S4 首页今日课表卡 `_today_classes`；卡 dict 增 `app_href` |
| `custom_addons/edu_portal/views/edu_portal_templates.xml` | 课表模板：周/日切换、今天、第N周徽标、停课灰显列、日视图纵排 |
| `custom_addons/edu_portal/views/calendar.xml` | 校历模板：月/周/列表切换、周网格三色芯片、列表议程、停课灰列 |
| `custom_addons/edu_portal/views/batch2.xml` | v2 首页：常用区 + 今日课表卡 + 空分组守卫 + data-home-role/data-fav-grid；教师工作台常用条 + 今日我教的课卡 |
| `custom_addons/edu_portal/static/src/js/home_favs.js` | 新增：W2 常用区编辑（固定/取消固定/上移/下移，localStorage） |
| `custom_addons/edu_portal/static/src/css/ux_rework.css` | 新增：S2 周矩阵/复制芯片/今天列/停课灰显/校历周列表/常用区编辑样式（≥15px 正文、reduced-motion） |
| `custom_addons/edu_portal/__manifest__.py` | 版本 19.0.1.7.0；assets_frontend 增 css/js |
| `tests/smoke/ux_week_utils_check.py` | 新增：周次工具单测（提案 §6.4 tests/ smoke 惯例） |
| `tests/smoke/ux_rework_http_smoke.py` | 新增：关键路由 × 角色矩阵 + S2/S3 表单链路冒烟 |
| `tests/smoke/ux_rework_playwright.py` | 新增：交互冒烟（下拉/弹窗/周导航/视图切换/常用区编辑） |
| `docs/plans/ux-implement-report.md` | 本文件 |
| `tests/smoke/ux_rework_f14_calendar_check.py` | t6 新增：F14 守卫 + S1 冲突四维断言（24 项，odoo shell） |
| `tests/smoke/ux_rework_f14_summer_e2e.py` | t6 新增：寒暑假月视图「不过滤」E2E（6 项，odoo shell） |
| `tests/smoke/ux_rework_s1_batch_probe.py` | t6 新增：S1 批量计算路径探针（5 项，odoo shell） |
| `custom_addons/edu_schedule/models/session_ext.py`（t6/t14 增量） | t6：修复批量计算缺陷（others 不再排除整个 recs，按 id 跳过自身）；t14 B1：`conflict_color` 由 Selection 改 **Integer 0-3**（前端 getColor 仅 number 走色板档） |
| `custom_addons/edu_schedule/models/week_utils.py`（t6 增量） | t6：新增 `week_window_utc(monday_local, tz_name)` 周窗口唯一实现落位 |
| `custom_addons/edu_portal/controllers/scheduling.py`（t6 增量） | t6：`_week_window_utc` 改为薄封装转发 `week_utils.week_window_utc`（调用点迁移清单 4） |

## 2. 关键实现口径

- **周次锚点（全站统一）**：学期 `term_start_date` 所在自然周 = 第 1 周；无学期退化为排课起始日所在周。`week_utils.term_anchor / week_no_of / parse_week_ranges / parity_ok` 被 S2（周期排课）、S4（课表第N周）共用；S3 复用同一投影工具函数族。
- **S1 冲突分色**：`conflict_kind`（语义：faculty/classroom/batch/batch_subject）+ `conflict_color`（**Integer 0-3**：0 默认 / 1 教师红 / 2 教室橙 / 3 班级黄琥珀；前端 `getColor()` 仅对 number 走 0-55 色板档 → `o_calendar_color_0-3`，t14 B1 实证 Selection 字符串走 hash 随机色不可用；`_KIND_HEX` 仅供图例展示）。口径与上游 `check_timetable_fields` 同构：±24h 窗口预筛 + sudo 全量 + `state != cancel` 不参与；一次性 `search` + 内存 O(n·m)，`store=False` 不落库。日历视图用**继承上游 view_op_session_calendar** 方式改 `color` 属性（官方 action 显式绑定该视图，priority 新视图无法顶替；继承等价且零风险），quick_create/拖拽/过滤全部保留。**t6 修复批量计算缺陷**：原实现把 `recs.ids` 整体排除出 others，日历视图批量 read 时同批冲突课时彼此不可见（视图不显色）；修复为 others 取窗口内全部非取消课时、循环内按 id 跳过自身。
- **S2 网格预览**：行=选中星期几，列=周次；格状态 ok（绿勾）/conflict（红叹号）/holiday（灰旗，自动排除）/miss（不命中周次/单双周）/none（超出日期范围）。停课与冲突仅为预览着色；创建仍逐条走服务端四查兜底。**参数兼容**：week_ranges 留空 + 每周 = 旧行为（rows 生成逻辑不变）。
- **冲突判定轴（UTC）**：预览/复制预检的重叠比较在 UTC naive 轴进行（与上游四查一致）——将要创建的课节按用户时区墙钟 → UTC 入库，与既有课时（UTC naive）同轴可比；本地分钟比较会导致时区错位误判。
- **表单修复（S2 顺带）**：`weekday` 复选框原用 `t-att-value="wn_index"`，周一（0）被 QWeb 渲染为 `value="on"`，提交时被数字过滤丢弃——改为 `t-attf-value` 后周一可正常勾选（修复既有缺陷，非行为回退）。
- **S3 复制预览**：`/timetable/copy/preview` 纯读投影（目标周 7 列 × 课节芯片，绿/灰/黄/红四态 + 汇总）；确认后 `/timetable/copy/run` 结果页逐组展开逐条「源日期 课时 → 目标日期 + 原因」（已复制/停课日/已存在/冲突）。原表单字段与默认值（skip_existing 默认勾选）不变；`/timetable/copy/run` 直达路径保留。
- **S4/S5 停课灰显**：`edu.schedule.holiday._matches(day, batch)`，角色域：学生=本班、教师=任教班集、家长=孩子班集、内部=全校停课（哨兵 -1 只认全局）；纯 sudo 只读，不改数据。今天定位=周视图当天列高亮 + 日视图直达；`第 N 周` 徽标三处同锚点。
- **W1/W2**：常用区为服务端预置（学生/教师/家长/内部各 4 件套，URL 全部复用既有路由；被 `_hidden_cards` 隐藏的入口自动剔除）；`_home_categories` 空分组守卫既有 + 模板层再加一道（`t-if="cat['cards']"`）；编辑仅 DOM 重排 + localStorage（键 `home_favs_<role>`），未设置偏好时渲染与服务端默认完全一致（零丢失），禁用 JS 时回退默认顺序。

## 3. 与提案的偏差（≤ 刻意最小化）

1. S1 采用**继承官方日历视图**而非 priority=1 新视图：官方 action `act_open_op_session_view` 通过 `ir.actions.act_window.view` 显式绑定 `view_op_session_calendar`，自建视图无法对其生效；继承实现同样视觉效果且避免双主视图歧义。
2. S5 校历「列表视图」为整个月窗口的按日议程（钉钉列表视图口径），周视图为「节次×星期」三色网格（与课表页同构）；月视图默认与查询逻辑不动。
3. W2 未做拖拽排序（提案 P2 再评），上移/下移 + 固定到常用已满足 P1 契约。

## 4. 零功能丢失核对

- 路由全部保留并新增前缀 `/timetable/copy/preview` 一条（新建路由）；原 `/timetable/bulk|preview|create`、`/timetable/copy|run`、`/student/timetable`（w/view/d 参数均新增、默认值=旧行为）、`/my/calendar`（view 默认 month）行为不变。
- 创建/复制写路径未改动：仍逐条创建 + 服务端四查 ValidationError 拦截；预览红格仅为提示。
- 首页/教师工作台卡片 URL/标题/图标语义不变；常用区为新增纯视觉组，未设偏好时与改造前一致。
- 门户课表/校历均只读增强；`edu.schedule.holiday` 仅 sudo 读取。

## 5. 验证证据（本地）

> t6 回归补充（2026-08-28）：发现并修复 S1 批量计算缺陷——`_compute_conflict`
> 原实现把 `recs.ids` 整体排除出 others，日历视图批量 read（整窗口事件一次计算）
> 时同批互相冲突的课时彼此不可见、视图不显色；t4 的 shell 验证（单记录读取）
> 未覆盖该路径。修复：others 取窗口内全部非取消课时，循环内按 id 跳过自身；
> 新增 `tests/smoke/ux_rework_s1_batch_probe.py`（5 项）与
> `tests/smoke/ux_rework_f14_calendar_check.py`（24 项）、
> `tests/smoke/ux_rework_f14_summer_e2e.py`（6 项）回归断言，全部通过。
> 完整证据见 `docs/plans/local-regression.md`。

```
python3 -m compileall -q custom_addons/edu_portal custom_addons/edu_schedule custom_addons/edu_brand   → exit 0
docker compose run --rm web odoo -d edu19 -u edu_portal,edu_schedule,edu_brand ... --stop-after-init
    → 'Modules loaded' ×1；log 内 ERROR/CRITICAL ×0（t4 冒烟期间的 bus websocket
      KeyError 为 http 工具打 websocket 端点的环境噪音，与升级无关）
curl http://127.0.0.1:8069/my/calendar（未登录）→ 303 → /web/login（auth='user' 设计）；
    登录态关键路由全部 200：/my/calendar、/student/timetable、/timetable/bulk、
    /timetable/copy、/openeducat/apps_menu（admin 角色矩阵见 http 冒烟）
tests/smoke/ux_rework_http_smoke.py    → 49 passed, 0 failed（四角色 × 校历三视图/周课表
    周日视图/首页常用区；S2 周矩阵预览（2-3 周绿格、单周语法）；S3 复制预览四态；未登录守卫；
    t14 补 3 项 S1 字段契约断言：conflict_color type=integer store=False、conflict_kind type=char）
tests/smoke/ux_week_utils_check.py      → 18 passed, 0 failed（锚点/周次/单双周/范围解析）
tests/smoke/ux_rework_playwright.py     → 32 passed, 0 failed（常用区固定/取消/上移/
    持久化/无偏好回退；avatar 弹窗；周课表今天/日视图/第N周/今天列；校历三视图；
    排课表单下拉 + 周次/单双周 → 周矩阵；确认表单隐藏域）
S3 写路径端到端：/timetable/copy/run 复制 15 节 → 落库 15 → 明细 15 行一致 → 已清理
    （演示库零残留；op_session 序列复位）
冲突红格验证：16:00-17:00 CST（=演示课时 UTC 同窗同师同班）→ 预览红格 1；
    08:00-09:00 CST（无重叠）→ 绿格 1（UTC 轴判定）
scripts/check_english.py stu@local demo123 → TOTAL visible-English hits: 0（路由基线全 200/303）
odoo shell：conflict_kind/conflict_color 字段存在、重叠课时 kind=faculty、
    日历视图 arch 已 color=conflict_color 且 quick_create/event_open_popup 保留
```

## 6. 未做（按提案 P2/§5 边界）

- W3（角标全站审计，v2 网格已具备 oe_count_zero）、A1（审批聚合，需先核对 set_state 副作用，属 P2 批次）
- 校历拖拽/循环事件、自动排课算法、DnD 全量、替换冲突引擎、审批画布、移动原生、服务端排序持久化——均为提案 §5 明确暂不做。