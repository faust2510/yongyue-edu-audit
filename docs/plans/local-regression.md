# ux-rework t6 本地回归报告（local-regression）
> **状态**：`归档` ｜ **主题**：`排课回归` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 回归：engineer（ux-rework 团队）｜2026-08-28 ｜ 依据：`docs/plans/ux-improve-proposal.md`（t3 批准版，§1A 处置表 + §S1/S2 契约 + F14 回归项）
> 基线：`custom_addons/edu_schedule`、`custom_addons/edu_portal` 工作区（t4 实施成果，冻结待审状态）
> 环境：docker compose edu19-clone（odoo:19 + postgres:16，db=edu19），本机 127.0.0.1:8069

## 0. 结论

**全部通过。** 升级无 ERROR/CRITICAL；三套 t4 smoke 复跑全绿（18/49/32，http smoke 含 t14 补 3 项 S1 字段契约断言）；四角色关键路由矩阵 27/27 全 200；F14 寒暑假守卫回归（shell 24 项 + E2E 6 项 + 批量计算探针 5 项）全绿；S1 冲突分色在**视图批量计算路径**上发现并修复一处真实缺陷（详见 §4.2）；tmp_t4_*.py 已按 §1A 处置表清理；git status 与处置表登记文件一一勾稽。

**本回归发现并修复的缺陷（S1 批量计算）**：`_compute_conflict` 原实现把 `self.ids` 从 others 排除，日历视图一次读取整窗口事件（批量 read）时，同批互相冲突的课时彼此不可见 → 视图上不显色。t4 的 shell 验证只做了单记录读取，未覆盖批量路径。已修复并新增探针断言（§4.2），修复后单记录与批量路径均正确。

---

## 1. 升级回归（步骤②）

命令（与 t4 同构）：
```bash
python3 -m compileall -q custom_addons/edu_schedule custom_addons/edu_portal
docker compose run --rm web odoo -d edu19 -u edu_schedule,edu_portal \
    --db_host=db -r odoo -w odoo --stop-after-init
```

| 检查 | 结果 | 证据 |
|---|---|---|
| compileall 语法 | ✅ | `COMPILEALL_OK`（edu_schedule + edu_portal 全量） |
| 模块加载 | ✅ | `136 modules loaded`、`Modules loaded.`，无 ERROR/CRITICAL |
| 升级幂等 | ✅ | 首次升级含 `-u` 一次通过；修复 S1 后二次 `-u` 仍一次通过 |

> 注：回归期间曾因测试脚本删除 `ir.config_parameter` 记录（xmlid 由 `timetable_params.xml` noupdate 固化）导致升级撞唯一键——已恢复 `ir_model_data` 链接并将测试脚本改为 `set_param(k, '')`（不删记录），后续升级恢复正常。此问题为**测试脚本方法问题，非产品代码问题**。

---

## 2. 三套 smoke 复跑（步骤③）

| 套件 | 结果 | 覆盖 |
|---|---|---|
| `tests/smoke/ux_week_utils_check.py` | ✅ 18/18 | S2 周次工具单测（monday_of / parse_week_ranges / week_no_of / week_in_ranges / parity_ok） |
| `tests/smoke/ux_rework_http_smoke.py` | ✅ 49/49 | 四角色 × 校历三视图/周课表周日视图/首页常用区；S2 周矩阵预览（2-3 周绿格、单周语法）；S3 复制预览四态；未登录守卫；t14 补 3 项 S1 字段契约断言 |
| `tests/smoke/ux_rework_playwright.py` | ✅ 32/32 | 常用区编辑（固定/取消/上移/持久化/无偏好回退）；avatar 弹窗；周课表今天/日视图/第N周/今天列；校历三视图；排课表单下拉 + 周次/单双周 → 矩阵预览 |

复跑时机：S1 批量修复 + week_utils 周窗口落位后、web 容器重启后（三次全绿，含修复后）。

---

## 3. 四角色关键路由矩阵（步骤④）

新增 `t6_role_matrix`（HTTP 会话矩阵，27 项全 200）：

| 角色 | /my/home | /my/calendar | /my/calendar?view=week | /my/calendar?view=list | /student/timetable | /student/timetable?view=day |
|---|---|---|---|---|---|---|
| admin | 200 | 200 | 200 | 200 | 200 | 200 |
| stu@local | 200 | 200 | 200 | 200 | 200 | 200 |
| faculty@local | 200 | 200 | 200 | 200 | 200 | 200 |
| parent@local | 200 | 200 | 200 | 200 | 200 | 200 |

后台排课工具（admin）：`/timetable/bulk` 200。（`/timetable/copy*` 已于 2026-09-15 删除 —— 本条为历史读数，删改见 code-map §4。）
（四角色 × 三视图校历 + S2/S3 链路在 http smoke 49 项中已覆盖，此处为独立复核。）

---

## 4. F14 寒暑假回归 + S1 冲突分色（步骤⑤）

### 4.1 F14 月视图「不过滤」守卫（迁移清单 1）

新增 `tests/smoke/ux_rework_f14_calendar_check.py`（odoo shell，24 项全过）关键断言：

| 断言 | 结果 | 含义 |
|---|---|---|
| `term_anchor` 三级回退（进行中/远期→最近过去/远古→最早学期） | ✅ | week_utils 契约：进行中→本学起日；远期→最近过去学期起日；远古→最早学期起日 |
| `_active_term()` 今天在学期窗口 → 返回第一学期 | ✅ | 薄封装守卫存在且工作 |
| 暑假日期（2027-07-15）不在任何学期窗口 | ✅ | 无进行中学期前提成立 |
| 暑假守卫判定 → 无进行中学期（None） | ✅ | in-window 二次判定拦截回退锚点 |

新增 `tests/smoke/ux_rework_f14_summer_e2e.py`（odoo shell，6 项全过）三条路径：

- **A 逻辑闸门**：暑假日期 `_active_term` 同款 in-window 搜索 → 无进行中学期（None 前提）；
- **B 不过滤路径**：term=None 时月视图 session_domain 不含学期收窄 → 构造的暑假课时可见（`found=1`）——正是「今天在暑假」时的查询形态；
- **C 行为保持**：term=当前进行中学期时暑假课时被学期窗口拦下（`filtered=0`）——证明既有「进行中过滤」语义未被迁移破坏。

**grep 确认无双实现**：
```
custom_addons/edu_schedule/models/week_utils.py:66:def term_anchor(env, ref_date):      # 唯一实现
custom_addons/edu_portal/controllers/calendar.py:74:def _active_term():                  # 唯一薄封装
custom_addons/edu_schedule/models/week_utils.py:def week_window_utc(...)                # 唯一周窗口实现
custom_addons/edu_portal/controllers/scheduling.py:38:def _week_window_utc(...)           # 薄封装（调用 week_utils）
```
`_active_term` 仅 calendar.py 一处定义（grep 计数=1）；`term_anchor` 仅 week_utils 一处。周窗口工具按迁移清单 4 落位 week_utils（`week_window_utc(monday_local, tz_name)`），scheduling.py `_week_window_utc` 改为薄封装转发（calendar.py 经 scheduling 导入不受影响），**无双实现**。

### 4.2 S1 冲突分色计算字段（含批量路径缺陷修复）

新增 `tests/smoke/ux_rework_s1_batch_probe.py`（odoo shell，5 项全过）：

| 断言 | 修复前 | 修复后 |
|---|---|---|
| 单记录读取 s1/s2 冲突（t4 口径） | ✅ | ✅ |
| 批量计算（视图 read 路径）双方均显冲突 | ❌ **FAIL（kind=''）** | ✅ |

**缺陷根因**：`_compute_conflict` 原实现 `others = search([('id','not in', recs.ids), ...])`——单记录计算时 self 只有一条，others 含其余课时 → 正确；但日历视图渲染时 Odoo 对窗口内全部事件**批量 read**，`self` = 整批，`recs.ids` 把互相冲突的课时全部排除 → 双方都看不到对方 → 视图上**不显色**。t4 的 shell 验证（单记录读取）恰好绕过了该路径，造成假阳性通过。

**修复**（`custom_addons/edu_schedule/models/session_ext.py`）：others 不再排除整个 recs，改为窗口内全部非取消课时，循环内按 `other.id == rec.id` 跳过自身。单记录路径行为不变（others 仍含其余课时），批量路径双方可见。修复后 24 项冲突维度断言 + 5 项批量探针全绿。

**冲突维度断言（`ux_rework_f14_calendar_check.py` §4，隔离时段构造）**：

| 场景 | conflict_kind | conflict_color | 结果 |
|---|---|---|---|
| 无冲突课时（独占时段 + 同教师 cancel 重叠） | '' | '0' | ✅ |
| 同教师重叠 | faculty | '1' | ✅ |
| 同教室重叠（不同教师） | classroom | '2' | ✅ |
| 同班级同科目重叠（不同教师） | batch_subject | '3' | ✅ |
| 同班级不同科目重叠（不同教师） | batch | '3' | ✅ |
| cancel 课时自身不参与冲突 | '' | '0' | ✅ |
| store=False 不落库 | — | — | ✅（DB 无列） |
| 视图批量 read 双方均标注 | faculty | 1 | ✅ |

**视图继承链路验证**（odoo shell）：`get_combined_arch()` 合并后 `color="conflict_color"`、`quick_create="true"`、`event_open_popup="true"` 保留、`conflict_kind`/`conflict_color` 字段追加；官方 action `act_open_op_session_view` 仍绑定 `view_op_session_calendar`（op.session.calendar），继承记录指向官方视图。

---

## 5. 清理与 git status 对照（步骤⑥）

§1A 处置表核对：

| 处置 | 文件 | 状态 |
|---|---|---|
| 清理 | `tmp_t4_cal_shell.py`、`tmp_t4_http_smoke.py` | ✅ 已删除 |
| 保留并扩充（新增回归脚本） | `tests/smoke/ux_rework_f14_calendar_check.py`、`ux_rework_f14_summer_e2e.py`、`ux_rework_s1_batch_probe.py` | ✅ 新增 |
| 不在处置范围 | `tmp_t7_nav_test.py`、`screenshot_user*.png`、`tmp_t.py` | 未动（非本方案产物） |

`git status` 已跟踪改动与处置表「采纳并对齐」清单逐文件勾稽一致：
- edu_schedule：`models/session_ext.py`（AM）、`models/week_utils.py`（AM）、`views/session_conflict_view.xml`（A）、`controllers/main.py`、`views/templates.xml`、`models/__init__.py`、`__manifest__.py`；
- edu_portal：`controllers/scheduling.py`、`controllers/calendar.py`、`controllers/batch2.py`、`views/edu_portal_templates.xml`、`views/calendar.xml`、`views/batch2.xml`、`__manifest__.py`、`static/src/js/home_favs.js`（A）、`static/src/css/ux_rework.css`（A）；
- docs：`ux-implement-report.md`（A）；tests：三个 t4 smoke（A）+ 三个新回归脚本（??，本回归新增）。

数据库零残留：测试课时（T6冲突测试/T6暑假课时/T6批量探针）全部清理，`op_session` 计数回到基线 47；`op_faculty` 回到 1；四查约束参数恢复 `True`（含 `ir_model_data` xmlid 链接）。

---

## 6. 零功能丢失核对（本回归角度）

- 升级 `-u edu_schedule,edu_portal` 两次全绿，官方日历 quick_create/拖拽/过滤保留（合并 arch 断言）；
- 四查约束参数全部恢复 True，写路径（新建/复制）拦截语义未动（测试期间临时置空、测后恢复）；
- `/my/calendar` 月视图为默认视图，查询逻辑零变化（F14 C 路径证明既有「进行中过滤」行为保持）；
- `/student/timetable` 周视图默认形态、上周/本周/下周导航保留（playwright 断言）；
- 未部署云端（铁律）。

## 7. 复跑命令速查

```bash
python3 -m compileall -q custom_addons/edu_schedule custom_addons/edu_portal
python3 tests/smoke/ux_week_utils_check.py
python3 tests/smoke/ux_rework_http_smoke.py
python3 tests/smoke/ux_rework_playwright.py
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
    -r odoo -w odoo -d edu19 --no-http < tests/smoke/ux_rework_f14_calendar_check.py
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
    -r odoo -w odoo -d edu19 --no-http < tests/smoke/ux_rework_f14_summer_e2e.py
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
    -r odoo -w odoo -d edu19 --no-http < tests/smoke/ux_rework_s1_batch_probe.py
python3 tests/smoke/ux_rework_calendar_color_probe.py   # t14 浏览器探针（自包含：造数→断言→清理）
```

---

## 8. t14 修复回归（B1/M1/M2，2026-08-28 追加）

> 依据：t10 评审 BLOCKER B1 + 2 MEDIUM（M1/M2）。修复代码 + 文档契约 + 回归证据见本节。

### 8.1 B1：conflict_color 载体 Selection → Integer（实证修复）

**问题实证**：Odoo calendar 前端 `getColor()`（`web/static/src/views/calendar/utils.js`）对 `typeof key === "number"` 走 `((key-1)%55)+1` 色板索引档；对**字符串**（含 Selection 值）走 hash 分支产生随机档。浏览器实测（Selection 实现）：
- 官方时间表日历 15 个事件 **全部 `o_calendar_color_6` 同一粉色**——冲突分色完全失效（验收② FAIL）。

**修复**（`custom_addons/edu_schedule/models/session_ext.py`）：
- `conflict_color` 由 `fields.Selection` 改为 **`fields.Integer`**（compute, store=False）；
- compute 返回 `0`（无冲突）/`1`（教师）/`2`（教室）/`3`（班级）；
- `_KIND_INDEX` 值由字符串 `'0'-'3'` 改为整数 `0-3`；`_KIND_HEX`/`_KIND_LABEL` 键同步改整数；
- `conflict_kind`（Char）不变。

**浏览器实证（Integer 实现，升级 + 重启后）**：
- 无冲突周：15 事件全部 `o_calendar_color_0`（默认档）✅；
- 冲突周（2026-09-07 造数）：`o_calendar_color_1: 2`（教师）+ `o_calendar_color_2: 2`（教室）+ `o_calendar_color_3: 2`（班级）——**三档冲突色可区分，与无冲突档 0 不同** ✅。

### 8.2 M1：验收②浏览器探针（新增 smoke 套件成员）

新增 `tests/smoke/ux_rework_calendar_color_probe.py`（**自包含**：odoo shell 幂等造数 → playwright 后台日历断言 → finally 清理，库零残留）：

| 断言 | 结果 |
|---|---|
| 造数成功（SEED_OK） | ✅ |
| 后台登录 + 时间表日历加载 | ✅ |
| 找到冲突课时周（dist=1:2/2:2/3:2） | ✅ |
| 事件色 ≥2 种可区分（累计 0/1/2/3 四档） | ✅ |
| 无冲突档与冲突档不同 | ✅ |
| 冲突档互异（≥2 档） | ✅ |
| 三档冲突色齐全（1/2/3） | ✅ |
| 事件总数 > 0 | ✅ |
| 清理完成（CLEAN_OK） | ✅ |

配套：`tests/smoke/ux_rework_calendar_color_seed.py`（幂等造数）、`ux_rework_calendar_color_cleanup.py`（幂等清理）。

### 8.3 M2：in-flight 变更入账

- `docs/plans/ux-improve-proposal.md`：§S1 契约与映射表改「Integer 0-3 → o_calendar_color_0-3」；§1A 处置表 session_ext.py 行同步；§6 批次 0 in-flight 登记表补登 t6/t14 修复行（session_ext 批量修复 + B1 Integer、week_utils 周窗口落位、scheduling 薄封装、3 个 F14/批量探针脚本、本探针 3 件套）。
- `docs/plans/ux-implement-report.md`：changedPaths 表补登 t6/t14 增量（session_ext 批量修复 + Integer 载体、week_utils `week_window_utc`、scheduling 薄封装、F14/批量/颜色探针脚本）；§2 关键口径 S1 描述同步 Integer 机制。

### 8.4 复跑验证（B1 修复后全量）

| 项目 | 结果 |
|---|---|
| compileall | ✅ |
| `-u edu_schedule,edu_portal` 升级 | ✅（136 modules loaded，无 ERROR/CRITICAL） |
| `ux_week_utils_check.py` | ✅ 18/18 |
| `ux_rework_http_smoke.py` | ✅ 49/49 |
| `ux_rework_playwright.py` | ✅ 32/32 |
| `ux_rework_f14_calendar_check.py`（Integer 断言版） | ✅ 24/24 |
| `ux_rework_f14_summer_e2e.py` | ✅ 6/6（前次验证） |
| `ux_rework_s1_batch_probe.py` | ✅ 5/5（前次验证） |
| `ux_rework_calendar_color_probe.py`（M1 探针） | ✅ 10/10 |

数据库零残留：探针造数/清理后 `op_session`=47 基线、`op_faculty`=1、四查参数 True（含 xmlid 链接）。

### 8.5 收尾入账与最终复跑（船长指令，2026-08-28）

- **临时脚本清理**：`tmp_t7_nav_test.py` 已不在工作区（t7 评审期间遗留，收尾确认已清）；`tmp_t4_*.py` 此前已删；`tmp_t.py`（历史遗留删除 `D` 状态）非本方案产物，保持原状。工作区零临时文件（`ls tmp_*.py` 无结果）。
- **git add 入账**（t7 L1 收尾）：三个 t6 回归脚本（`ux_rework_f14_calendar_check.py` / `ux_rework_f14_summer_e2e.py` / `ux_rework_s1_batch_probe.py`）+ 三个 t14 颜色探针（`ux_rework_calendar_color_probe.py` / `_seed.py` / `_cleanup.py`）+ 五个 docs 报告（`local-regression.md` / `oss-research.md` / `ux-improve-proposal.md` / `ux-research-dingtalk.md` / `ux-rework-handoff.md`）全部 `git add`（状态 A）。
- **最终复跑（入账后全量）**：

| 项目 | 结果 |
|---|---|
| compileall | ✅ |
| `-u edu_schedule,edu_portal` 升级 | ✅（136 modules loaded，无 ERROR/CRITICAL） |
| `ux_week_utils_check.py` | ✅ 18/18 |
| `ux_rework_http_smoke.py` | ✅ 49/49 |
| `ux_rework_playwright.py` | ✅ 32/32 |
| `ux_rework_f14_calendar_check.py` | ✅ 24/24 |
| `ux_rework_f14_summer_e2e.py` | ✅ 6/6 |
| `ux_rework_s1_batch_probe.py` | ✅ 5/5 |
| `ux_rework_calendar_color_probe.py` | ✅ 10/10 |
| DB 零残留 | ✅ 47/1/四查 True |
