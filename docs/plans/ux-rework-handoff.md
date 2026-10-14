# ux-rework 交付报告与试用指引（ux-rework-handoff）
> **状态**：`归档` ｜ **主题**：`钉钉式排课改造交付` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 整合：engineer（ux-rework 团队）｜2026-08-28 ｜ 任务：t8（integration）
> 全链路：调研（t1/t2）→ 方案（t3，含 3 轮修订 t9/t11）→ 实施（t4）→ 验证（t6）→ 评审（t5/t7/t10/t12/t13）
> 交付物：本报告 + 实施说明 `docs/plans/ux-implement-report.md` + 回归报告 `docs/plans/local-regression.md` + 方案 `docs/plans/ux-improve-proposal.md`

---

## 1. 结论

本地实施与验收**全部完成**：P0（S1 冲突分色 / S2 周期排课升级）+ P1（S3 复制预览 / S4 周课表增强 / S5 校历三视图 / W1 常用区 / W2 编辑排序）共 7 项改进落地；三套 smoke 全绿（18/49/32）；四角色关键路由 27/27 全 200；F14 寒暑假守卫回归 35 项断言全绿；升级两次 `-u` 无 ERROR/CRITICAL；数据库零残留。

**云端部署待用户审查后另行指令，本团队不执行部署**（铁律：仅本地，等用户拍板）。

---

## 2. 改动清单（文件 + 功能）

### 2.1 功能改进总览（对照方案 §1 总览表）

| # | 改进项 | 优先级 | 状态 | 功能说明 |
|---|---|---|---|---|
| S1 | 排课网格冲突分色 | P0 | ✅ 落地 | `op.session` 计算字段 `conflict_kind`/`conflict_color`（**Integer 0-3**：0 无冲突/1 教师红/2 教室橙/3 班级黄 → `o_calendar_color_0-3`，t14 B1 实证），继承官方 `view_op_session_calendar` 改 `color`；quick-create/拖拽/过滤保留；服务端四查拦截不动 |
| S2 | 周期排课升级 | P0 | ✅ 落地 | `/timetable/bulk` 加「周次范围」（`1,3-5,8-12` 语法）+ 每周/单周/双周；预览改节次×星期周矩阵（绿勾/红叹/灰旗/未命中）；week_ranges 留空=旧行为兼容 |
| S3 | 整周复制预览+明细 | P1 | ✅ 落地 | 新增 `/timetable/copy/preview`（纯读预览，目标周网格 + 跳过原因分类）；`/timetable/copy/run` 结果页扩充逐条明细（已复制/已存在/停课日/冲突） |
| S4 | 周课表增强+今日卡 | P1 | ✅ 落地 | `/student/timetable`：今天列高亮、`view=day` 日视图 + 前后翻页 + 今天定位、第 N 周标注、停课灰显；`/my/home` 首页「今日课表」预览卡（学生/教师/家长） |
| S5 | 校历三视图 | P1 | ✅ 落地 | `/my/calendar` 月（默认）/周/列表三视图切换 + 今天定位；周视图节次×星期三色事件芯片（课程蓝/考试红/活动青绿/停课灰） |
| W1 | 常用应用置顶区 | P1 | ✅ 落地 | 首页宫格顶部「常用应用」区（角色化预置 4 件套）；空组守卫（既有控制器过滤 + 模板层二次）+ 更多区/常用区空态 |
| W2 | 编辑态排序 | P1 | ✅ 落地 | 卡片 hover「⋯」菜单：固定到常用/取消固定/上移/下移；localStorage（`home_favs_<role>`）持久化；无偏好=服务端默认顺序（零丢失） |
| W3/A1 | 角标审计/审批聚合 | P2 | 未做 | 方案 §4/§5 明确 P2 边界（v2 网格已具备 oe_count_zero 灰底角标） |

### 2.2 文件清单（git status 实况，2026-08-28 收尾）

**custom_addons/edu_schedule（新增/修改）**
| 文件 | 状态 | 内容 |
|---|---|---|
| `models/week_utils.py` | 新增 | 唯一公共周次工具：`monday_of` / `week_no_of` / `parse_week_ranges` / `week_in_ranges` / `parity_ok` / `term_anchor`（三级回退）/ `week_window_utc`（周窗口唯一实现） |
| `models/session_ext.py` | 新增 | S1 冲突分色计算字段（**Integer 0-3**，t14 B1；**含 t6 修复的批量计算缺陷**，见 §5） |
| `views/session_conflict_view.xml` | 新增 | 继承官方 `view_op_session_calendar`：color→conflict_color + 追加 conflict_kind/conflict_color 字段 |
| `controllers/main.py` | 修改 | S2 周次/单双周 + 周矩阵预览；S3 `/timetable/copy/preview` + 结果逐条明细 |
| `views/templates.xml` | 修改 | bulk 表单周次/单双周字段、周矩阵预览模板、复制预览模板、结果页逐条展开 |
| `models/__init__.py`、`__manifest__.py` | 修改 | 注册新模型模块与视图 |

**custom_addons/edu_portal（新增/修改）**
| 文件 | 状态 | 内容 |
|---|---|---|
| `controllers/scheduling.py` | 修改 | S4 周/日视图、今天、第N周、停课灰显；`_week_window_utc` 改薄封装转发 week_utils |
| `controllers/calendar.py` | 修改 | S5 三视图 + 今天定位；`_active_term` 迁移为 `term_anchor` 薄封装（F14 守卫保持） |
| `controllers/batch2.py` | 修改 | W1 常用区装配；S4 首页今日课表卡；卡 dict 增 `app_href` |
| `views/edu_portal_templates.xml` | 修改 | 课表周/日切换、今天、第N周徽标、停课灰显 |
| `views/calendar.xml` | 修改 | 校历月/周/列表切换、周网格三色、列表议程 |
| `views/batch2.xml` | 修改 | v2 首页常用区 + 今日课表卡 + 空组守卫；教师工作台常用条 |
| `static/src/js/home_favs.js` | 新增 | W2 常用区编辑（固定/上移/下移，localStorage） |
| `static/src/css/ux_rework.css` | 新增 | S2 周矩阵/复制芯片/今天列/停课灰显/校历/常用区样式（≥15px、reduced-motion） |
| `__manifest__.py` | 修改 | 版本号 + 资产注册 |

**docs / tests**
| 文件 | 状态 | 内容 |
|---|---|---|
| `docs/plans/ux-improve-proposal.md` | 新增 | 方案（t3 + t9/t11 修订 + t13 最终裁定） |
| `docs/plans/ux-research-dingtalk.md` | 新增 | t1 钉钉/企微/飞书交互调研 |
| `docs/plans/oss-research.md` | 新增 | t2 开源项目调研 |
| `docs/plans/ux-implement-report.md` | 新增 | t4 实施说明（含 S1 批量缺陷补记） |
| `docs/plans/local-regression.md` | 新增 | t6 回归报告 |
| `tests/smoke/ux_week_utils_check.py` | 新增 | 周次工具单测（18 项） |
| `tests/smoke/ux_rework_http_smoke.py` | 新增 | 路由×角色矩阵 + S2/S3 链路（49 项，含 t14 补 3 项 S1 字段契约断言） |
| `tests/smoke/ux_rework_playwright.py` | 新增 | 交互冒烟（32 项） |
| `tests/smoke/ux_rework_f14_calendar_check.py` | 新增（t6） | F14 守卫 + 冲突四维断言（24 项） |
| `tests/smoke/ux_rework_f14_summer_e2e.py` | 新增（t6） | 寒暑假不过滤 E2E（6 项） |
| `tests/smoke/ux_rework_s1_batch_probe.py` | 新增（t6） | 批量计算路径探针（5 项） |

> 上游 `openeducat_erp/openeducat_timetable/` 零改动；`edu_brand` 未改动。

---

## 3. 怎么试用（本地）

### 3.1 环境

- 本地地址：http://127.0.0.1:8069 （docker compose edu19-clone：odoo:19 + postgres:16，db=edu19）
- 启动：`docker compose up -d`（web+db 已在运行）；代码改动后升级：`docker compose run --rm web odoo -d edu19 -u edu_schedule,edu_portal --db_host=db -r odoo -w odoo --stop-after-init`，再 `docker compose restart web`
- 登录账号（本地库，密码为 t4 重置的约定值）：
  - 学生 `stu@local` / `demo123`（王小明）
  - 教师 `faculty@local` / `demo123`（预备科导师【演示】）
  - 家长 `parent@local` / `demo123`（家长【演示】）
  - 管理员 `admin` / `admin`

### 3.2 操作路径（按改进项）

| 改进项 | 入口 | 操作 |
|---|---|---|
| S1 冲突分色 | 后台「时间表」应用（admin）→ 官方日历 | 排课日历事件按冲突维度分色：教师红 / 教室橙 / 班级黄；无冲突=默认色；quick-create/拖拽照旧 |
| S2 周期排课 | `http://127.0.0.1:8069/timetable/bulk`（admin） | 选课程/班级/教师/节次/教室 → 勾星期 → 填周次范围（如 `2-3`）→ 选每周/单周/双周 → 「预览将生成的课节」看周矩阵（绿=可排/红=冲突/灰=停课）→ 确认创建 |
| S3 复制预览 | `http://127.0.0.1:8069/timetable/copy`（admin） | 源周日期 + 目标周（最多 3）→ 「预览复制结果」看目标周网格与跳过原因；确认后结果页逐条明细（已复制/已存在/停课日/冲突） |
| S4 周课表 | `http://127.0.0.1:8069/student/timetable`（任一角色） | 周视图：今天列高亮 + 第 N 周徽标 + 停课灰显；切「日视图」单日纵排 + 后一天/今天；首页 `/my/home` 见「今日课表」卡（点击进日视图） |
| S5 校历 | `http://127.0.0.1:8069/my/calendar`（任一角色） | 顶部「月 / 周 / 列表」切换 + 「今天」按钮；周视图三色事件芯片；列表按日议程 |
| W1 常用区 | `http://127.0.0.1:8069/my/home` | 首页顶部「常用应用」区（角色预置 4 件套：学生=课表/打卡/校历/作业） |
| W2 编辑排序 | `http://127.0.0.1:8069/my/home` | hover 卡片右上「⋯」→ 固定到常用/取消固定/上移/下移；刷新后保持（localStorage）；清 localStorage 恢复默认 |

### 3.3 关键差异点提示

- 周期排课「周一」复选框已修复（t4 顺带修复既有 `t-att-value` 渲染缺陷，周一此前不可选）。
- 停课灰显读 `edu.schedule.holiday`（sudo 只读），门户只读展示，不写数据。
- 常用区/今日课表卡为新增纯视觉组：未设偏好时渲染与服务端默认完全一致；禁用 JS 回退默认顺序。

---

## 4. 回滚方案

**前提**：本批次全部改动**未提交、未部署**，全部在工作区（git 未跟踪/已暂存混合状态，HEAD=`ebc5cff`）。

| 回滚级别 | 操作 | 说明 |
|---|---|---|
| 全量回滚（丢弃） | `git checkout -- custom_addons/` + 删除未跟踪新增文件（`session_ext.py`、`week_utils.py`、`session_conflict_view.xml`、`home_favs.js`、`ux_rework.css`、3+3 个 smoke 脚本） | 回到 HEAD `ebc5cff`（v2.1/v2.2 已部署批），无任何遗留 |
| 代码回滚 + 数据复位 | 上述回滚后，`docker compose run --rm web odoo -d edu19 -u edu_schedule,edu_portal --stop-after-init` | 计算字段 store=False 不落库、无新表/新列，`-u` 复位即干净（回归期间实测：字段不在 DB 表） |
| 单功能回滚 | 按 §2.2 文件清单只还原对应文件 | 各改进项文件相互独立（视图继承文件可单独移除） |
| 数据库 | 无需迁移脚本；`ir.config_parameter` 四查参数已恢复 `True`（含 xmlid 链接） | t6 回归后实测零残留：`op_session`=47 基线、`op_faculty`=1 |

> 注意：若此前对本地库做过演示数据操作（如批量排课/复制创建），回滚代码不会自动删除已创建的 `op.session` 数据——需要时按名称/时间清理（本团队回归期间已全部清理，当前库=基线）。

---

## 5. 本地验证结论（t6 摘要）

全部通过，报告详见 `docs/plans/local-regression.md`：

- **升级**：`compileall` 0；`-u edu_schedule,edu_portal` 两次全绿（136 modules loaded，无 ERROR/CRITICAL）。
- **smoke**：`ux_week_utils_check` 18/18、`ux_rework_http_smoke` 49/49（含 t14 新增 3 项 S1 字段契约断言）、`ux_rework_playwright` 32/32（均在 S1 修复后复跑）。
- **路由**：四角色 × 校历三视图/周课表周日视图/首页 + admin 排课工具 = 27/27 全 200（含 `/timetable/copy/preview` POST）。
- **F14 寒暑假守卫**：`term_anchor` 三级回退、`_active_term` 薄封装守卫、月视图「不过滤」路径（暑假课时可见）、「进行中过滤」行为保持——35 项断言全绿；grep 确认无 `_active_term`/`term_anchor`/周窗口双实现。
- **S1 冲突分色**：无冲突 ''/0、教师 faculty/1、教室 classroom/2、班级(含科目) batch(_subject)/3、cancel 不参与、store=False 不落库、视图批量 read 双方均显色——全绿；`get_combined_arch` 确认 `color=conflict_color` 且 quick_create/event_open_popup 保留；**t14 浏览器实证**：官方日历无冲突周 15 事件全 `o_calendar_color_0`（默认档）、冲突周 `o_calendar_color_1/2/3` 三档齐全互异（`tests/smoke/ux_rework_calendar_color_probe.py` 10/10）。
- **零残留**：测试数据全清（op_session=47 基线）、四查参数恢复 True、tmp_t4_*.py 已删、git status 与方案 §1A 处置表逐文件勾稽一致。

### ⚠️ t6 发现并修复的缺陷（评审关注点）

S1 `_compute_conflict` 原实现把 `recs.ids` 整体排除出 others —— **日历视图批量 read 时同批互相冲突的课时彼此不可见 → 视图不显色**（S1 验收②失效）。t4 的 shell 验证只做了单记录读取，未覆盖该路径。已在 `custom_addons/edu_schedule/models/session_ext.py` 修复（others 取窗口内全部非取消课时，按 id 跳过自身），并新增 `tests/smoke/ux_rework_s1_batch_probe.py`（5 项）断言；修复后单记录/批量路径均正确。实施说明 `ux-implement-report.md` §5 已补记。

### ⚠️ t14 修复（t10 BLOCKER B1 + M1/M2，最终代码基准）

**B1（blocker）color 载体实证修复**：`conflict_color` 原用 `fields.Selection`——Odoo calendar 前端 `getColor()` 对**字符串**（含 Selection 值）走 hash 分支产生随机色，浏览器实证官方日历 15 事件**全部同一粉色 `o_calendar_color_6`**（冲突分色失效）。已改为 **`fields.Integer` 0-3**（number 分支 → `o_calendar_color_0-3`），compute 返回 `0`（无冲突）/`1`（教师）/`2`（教室）/`3`（班级）；`_KIND_INDEX` 映射保留、`conflict_kind` Char 保留。修复后浏览器实证：无冲突周 15 事件全 `o_calendar_color_0`（默认档）、冲突周三档 `o_calendar_color_1/2/3` 齐全互异。方案文档 §S1/§1A 契约同步「Integer 0-3 → o_calendar_color_0-3」。

**M1** 新增自包含浏览器探针 `tests/smoke/ux_rework_calendar_color_probe.py`（admin→官方日历→重叠课时周→断言三档互异+默认档，10/10 全绿）；http smoke 补 3 项 S1 字段契约断言（49/49）。

**M2** in-flight 变更入账：`ux-improve-proposal.md` §6 登记表 + `ux-implement-report.md` changedPaths 补登（session_ext 批量修复+Integer、week_utils `week_window_utc` 落位、scheduling 薄封装、6 个探针脚本）；`local-regression.md` §8 追加完整回归记录。

---

## 6. 评审摘要

### 6.1 评审结论

| 评审 | 结论 | 要点 |
|---|---|---|
| t5 方案评审（r1） | needs_revision（1 high + 4 medium + 2 low） | S1 视图载体与既有 CN 视图冲突、S4/S3/W1 现状描述与实际不符、S2 学期锚点循环依赖——经 t9 修订全部落实 |
| t9/t11 方案修订（r2/r3） | — | 8 + 5 条意见修订落稿（§1A 处置表、S1 继承官方视图、S2 唯一公共模块 week_utils、Selection 0-3 契约） |
| t10 评审（r2） | needs_revision（1 blocker + 2 medium） | B1 color 载体 Selection 字符串实证失效 + M1 探针缺失 + M2 入账缺失——**经 t14 全部修复**（Integer 0-3 + 浏览器探针 + 入账） |
| t12 评审（r3） | **pass**（3 low 非阻塞） | 文档「0-4」表述残留、行号漂移、`_active_term` 命名漂移（均低危，收尾对齐即可） |
| t13 评审（r4 最终裁定） | **pass**（2 low 非阻塞） | F16 新增文件计数 10→9、F17 in-flight 登记表补 playwright.py |
| t7 实施评审 | **pass**（3 low 非阻塞） | L1 三个新回归脚本未跟踪（收尾 git add 即解决）、L2 §1A 数值漂移、L3 websocket 噪音已自然消除 |

### 6.2 未决低危项（不影响交付，收尾提交时一并处理）

1. 六个 t6/t14 新增回归脚本（`ux_rework_f14_calendar_check.py` / `ux_rework_f14_summer_e2e.py` / `ux_rework_s1_batch_probe.py` / `ux_rework_calendar_color_probe.py` / `ux_rework_calendar_color_seed.py` / `ux_rework_calendar_color_cleanup.py`）目前未跟踪——提交时随批次 git add（处置表已登记「保留并扩充」，属预期新增）。
2. ✅ 已对齐（2026-08-29 收尾复核）：以 `git show --numstat 727a6f9` 为准，§1A 同口径（11 个已跟踪修改文件：控制器/视图/manifest）实况 **+1557/-114**；加 5 个新增代码文件后 edu_portal+edu_schedule 16 文件合计 **+2209/-114**，全 commit 32 文件 **+4717/-123**。方案文档行 52 的 +1548/-106 系 t4 时点快照，保留存史不改。
3. ✅ 已裁定（2026-08-29 收尾复核，按代码实况）：公共实现命名 **`term_anchor`**（`edu_schedule/models/week_utils.py`），edu_portal 侧 `_active_term` 保留为其薄封装（`edu_portal/controllers/calendar.py`，语义=F14 学期锚点守卫不变）；曾拟名 `term_anchor_or_none` 未采用。t12 F3 二选一裁定=沿用现状双名，不再改名。

---

## 7. 部署待确认说明

**本团队不执行云端部署。** 按团队铁律与任务书：改进仅在本地实施并验收；是否部署、部署到哪个环境、何时部署，**全部待用户审查本报告与本地试用后另行给出明确指令**。在收到用户明确部署指令前，不推送、不打包、不触碰任何生产环境。

---

## 8. 附录：复跑命令速查

```bash
# 升级
python3 -m compileall -q custom_addons/edu_schedule custom_addons/edu_portal
docker compose run --rm web odoo -d edu19 -u edu_schedule,edu_portal \
    --db_host=db -r odoo -w odoo --stop-after-init
docker compose restart web

# 三套 smoke
python3 tests/smoke/ux_week_utils_check.py
python3 tests/smoke/ux_rework_http_smoke.py
python3 tests/smoke/ux_rework_playwright.py

# F14/S1 shell 回归
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
    -r odoo -w odoo -d edu19 --no-http < tests/smoke/ux_rework_f14_calendar_check.py
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
    -r odoo -w odoo -d edu19 --no-http < tests/smoke/ux_rework_f14_summer_e2e.py
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
    -r odoo -w odoo -d edu19 --no-http < tests/smoke/ux_rework_s1_batch_probe.py

# S1 冲突分色浏览器探针（自包含：造数→断言→清理）
python3 tests/smoke/ux_rework_calendar_color_probe.py
```
