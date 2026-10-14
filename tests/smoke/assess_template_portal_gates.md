# 「模板与评分项」门户化管理 —— 门禁与验收留档

留档人：edu-assess-portal 会话（受队长指派）｜ 2026-09-28
主题：把「模板与评分项」管理从 Odoo 后台搬进门户（用户反馈 P1/P2 风格割裂）
实现：`custom_addons/edu_assess/controllers/template_admin.py` +
`custom_addons/edu_assess/views/assess_template_admin.xml`
端到端验收脚本：`tests/smoke/assess_template_portal.py`（22 条断言，自带夹具/清理）

---

## 0. 环境与探活（跑门禁前的三步）

| 项 | 读数 |
|---|---|
| 容器 | `edu19-clone-web-1` / `edu19-clone-db-1`（`docker ps`） |
| 探测 | `curl -c jar -b jar /web/login?db=edu19` → **200**（探活用带 cookie 的往返，见 code-map §2） |
| 升级 | `bash scripts/safe_upgrade.sh edu_assess` → **EXIT 0**，无 Traceback / 无 `manifest not found`，末尾自带 `docker compose restart web` + 就绪探活 302 |
| ⚠ 并行会话 | 本克隆有**别的会话**在同一时间改 `edu_assess`（新增「评估历程」`/assess/my/history` 等，`controllers/portal.py` 17:13:04、`views/assess_portal.xml` 17:13:35 落盘）。**这些不是本次交付**；本轮实测用的活体进程启动于 **17:10:45**（早于它们落盘），所以本轮读数描述的是**本次改动**的效果。 |

## 1. 四条 UI 门禁（口径 = 本仓既有命令，未改任何门禁脚本）

| 门禁 | 命令 | 退出码 | 关键读数 |
|---|---|---|---|
| 表面登记 | `python3 scripts/check_ui_surface.py` | **0** | 仓内路由 302 条 / 登记 285 条 / **违规 0 条**（新路由未登记 0、门禁名不在闭集 0、名单不一致 0） |
| 无障碍 | `python3 scripts/check_accessibility.py` | **0** | **扫描成功页 50 / 50**，`违规合计 = 0 条（critical 0 / serious 0 / moderate 0 / minor 0）`；新页 `/assess/templates`、`/assess/templates/new` 以 backoffice 身份**真被 axe 扫到且 OK** |
| 汉化 | `python3 scripts/check_english.py` | **0** | `TOTAL must-fix = 0 条 / brand = 0 条 / 路由状态违规 = 0 条 / 夹具残留 = 0 条` |
| 可用性四轴 | `python3 scripts/check_ui_usability.py --report` | **0** | `A 0 ｜ B 0 ｜ C 0 ｜ D 0`；**样本有效=True**（探页前后容器 StartedAt 一致）；新页 375 视口 `ov=0` |
| 路由矩阵 | `python3 tests/smoke/ux_v3_route_matrix.py` | **0** | `检查点 505：PASS 505 / WARN 0 / PENDING 0 / FAIL 0 / ENV 0`；`/assess/templates` 与 `/assess/templates/new` = stu/fac/par `303→200`、bo/admin `200` |

### 1.1 未通过的两轮（照实记录，不掩盖）

| 轮次 | 门禁 | 退出码 | 原因 |
|---|---|---|---|
| 第 1 轮 16:59 | `check_ui_usability.py --report` | **2（ENV，样本作废）** | 采样期间 `edu19-clone-web-1` 被**并行会话重启**（StartedAt 08:57:29Z → 09:00:21Z）⇒ 按 UX_V3_GATE §0 纪律样本作废。页面读数当时已是 A/B/C/D = 0，但不采信 |
| 第 2 轮 17:11 | `check_english.py` | **0**，但打印 `[ENV] 开跑时检测到冒烟脚本在跑（1 个）` | 那个"冒烟脚本"是**本会话自己在跑的 `ux_v3_route_matrix.py`**（并行 bg job）。为不留疑问，17:14 在**无并发冒烟**时复跑一次：`[ENV]` 计数 = **0**，夹具残留 = **0** |

## 2. 端到端验收（`python3 tests/smoke/assess_template_portal.py`）

**22 条断言全 PASS（EXIT 0）**，结果落 `tests/smoke/assess_template_portal_results.json`。分组：

- **A 入口对照（3 条）**
  - A1 `/assess` 已**不再**出现 `/odoo/action-edu_assess.action_edu_assess_template` 的卡片
  - A2 `/assess` 出现门户原生入口 `/assess/templates`（按钮「进入管理」）
  - A3 历史落点 `/odoo/action-…` 仍 **200 且含 `o_web_client`**（后台路由一行未删，可回退）
- **B2 同源（3 条）**：门户页读出的 `{模板名: [评分项名]}` 与后台 JSON-RPC 读出的**双向差集 = 空**；模板 3 条、评分项 7 条逐条相等
- **B3 CRUD（11 条）**：门户 POST 建模板 → 库里出现；门户 POST 加两个评分项 → 两条落库；
  **后台读得到**（同一份数据）→ 门户列表页也立刻列出；非法等级线被模型拒绝且未写库；
  重名评分项被唯一约束拒绝且**回门户带人话**（不再甩 422 错误页）；停用↔恢复；
  逐个删评分项 → 删模板 → **行数回到基线 3/7**、**【冒烟】残留 = 0**
- **B4 权限（4 条）**：教务正对照取到真实模板名；教师/学生/家长对 **3 条 GET + 4 条写路由**全部
  `303 → /my/home`（落地页 200），且越权写入残留 = 0

### 2.1 匿名（未登录）

`auth='user'` ⇒ 403 之前被 Odoo 拦到登录页（303 → `/web/login?redirect=…`），非 200 暴露。

## 3. 反向自证：本轮**没有**放宽任何断言/删任何检查

- 未改 `scripts/check_*.py`、未改 `tests/smoke/ux_v3_route_matrix.py`（`git diff` 为空）；
  `tests/ui/surface.json` **只新增 7 行登记**（3 页 + 4 写端点），未动任何既有行。
- 修 UI 缺陷时改的是**实现**，不是判据：重名评分项曾吐 422 错误页，修法是
  在控制器里同时接住 `UserError` 与 `psycopg2.IntegrityError`（Odoo 的
  `service/model.py:213` 在控制器**之外**才做转换），文案复用
  `_sql_error_to_message()`，与后台逐字同源。
