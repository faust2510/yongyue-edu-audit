# 批次4（P2）A1 审批待办聚合 留痕
> **状态**：`归档` ｜ **主题**：`审批待办聚合` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 任务：ux-improve-proposal §A1「申请/审批流：待办聚合 + 进度可视化 + 就近操作」
> 范围：门户侧纯增强，只动 `custom_addons/edu_portal`；不改状态机、不改权限模型、
> 不动 `views/approval_backend.xml`；上一批 W3 已于 commit 4608e7b 入账。

## 0. 前置核对结论（先核对后动工，对照方案 §A1 的要求）

### 0.1 `_alert_counts`（batch2.py:272）数据来源与口径

- 数据来源：遍历静态 `_ALERT_CARDS`（13 个 href，batch2.py:231），每个 href 调
  `_count_cached → _count_for_card`（batch2.py:63）取「当前计数」。
- **未读判定字段**：`edu.alert.read.seen_map`（JSON，每用户一条，alert_read.py），
  每类未读 = `max(0, 当前计数 − seen_map[key])`，只升不降（`_raise_watermarks`）；
  清零入口 `/alerts/mark_read`（batch2.py:1535，POST key 按类提水位）。
- **关键发现 1**：`_count_for_card` 只实现了 6 个 href 的计数（布告/作业/考试/费用/
  图书队列/私信）；`my/time_off`、`my/grievances`、`subject/registration`、
  `users/result-overview`、`my/asset-request`、`my/quotes` 返回 None → 恒 0 →
  这些提醒卡**从不渲染**（其中就包括「您的请假状态已更新」「新申诉」两张卡）。
- **关键发现 2**：`_alert_counts` 只服务学生/家长侧首页（`_home_categories`）；
  **教师/教务工作台（`_teacher_dashboard` + `edu_dashboard_teacher` 模板）完全没有提醒区**，
  仅有 KPI 徽标（待批周记/进行中评估）与快捷大卡角标。
- 折叠区结构本身已是「raw=0 不渲染」的动态语义（W3 审计确认 0 值 t-if 隐藏），
  方案所说「由静态分类改为按未读动态渲染」的实际缺口 = ①待审批类计数源缺失、
  ②教师/教务侧无提醒区。

### 0.2 审批流现状（请假/申诉）

- **请假**：门户审批路由 `/leave/approvals`（列表，roles.py:418）+ `/leave/set_state`
  （POST，roles.py:431）。守卫 = `current_faculty()`（有 op.faculty 档案的用户，
  即 faculty@local；backoffice@local/admin **无** op.faculty 档案 → 进不了门户审批页，
  只能用后台「教务审批」菜单）。
- 状态机（models/leave.py）：`request（已申请）→ approved（已批准）/ refused（已拒绝）`；
  注意是 **refused** 不是 rejected。后台按钮 `action_approve`/`action_reject`
  （@api.model，驳回须先填 `reject_reason`，否则 UserError）。
- `/leave/set_state` 副作用 = 仅 `rec.write({'state': ...})`：
  **不写审批人、不写审批时间、无任何通知**（与方案假设一致：set_state 无通知）。
- **申诉**：门户侧**没有任何审批路由**，仅后台 approval_backend.xml 的表单按钮
  （action_start/resolve/reject/close，models/grievance.py）。状态机：
  `draft → submitted → in_progress → resolve/reject → close`。
  同样**无审批人/时间字段、无通知**。
- 结论：方案要求「详情页主行动 + 审批后通知申请人」在两条流上都是从零补，无重复发送风险。

### 0.3 approval_backend.xml 已有能力（本次不动）

请假/申诉/证书三组 list+form 后台视图 + 「教务审批」菜单（groups=base.group_user）。
form 内已有通过/驳回按钮（走模型 action_*）。本批次全部改动不触碰该文件；
但审批通知挂在**模型 action_* 方法内**（见 0.4），因此后台按钮审批同样会通知申请人
——文件零改动、行为补齐，属 A1 第 3 点的落地而非后台逻辑重写。

### 0.4 B5 通知引擎既有发送入口

- 无独立「站内通知」模型。既有通道两条：
  ① `edu.message`（B9 轻量私信，models/message.py；唯一 create 点 messages.py:374，
  sudo 写入、收件人未读角标 + 30s 轮询 + 铃铛徽标联动）；
  ② 首页提醒卡引擎（`_alert_counts` + seen_map 水位，学生/家长侧）。
- **落地**：审批/处理动作后经 `edu.message.create` 给申请人门户账号发一条
  系统通知（发件人=审批人），同时在学生首页提醒区给 `my/time_off` /
  `my/grievances` 补上计数源（走既有 seen_map 水位语义），双通道可见。

### 0.5 与方案假设的差异（按实际代码调整，不硬套）

| 方案假设 | 实际代码 | 调整 |
|---|---|---|
| 教师首页已有 portal_alert_category 折叠区 | 教师工作台无提醒区（该模板仅学生/家长首页有） | 在 `edu_dashboard_teacher` 新增「待办提醒」卡组（钉钉式常驻待办条，非折叠式），沿用 W3 的 0 值 t-if 不渲染语义 |
| 状态 submitted/approved/rejected | leave=request/approved/refused；grievance=submitted/in_progress/resolve/reject/close | 步骤条按各自真实状态机渲染（请假：已提交→审批中→已通过/已驳回；申诉：已提交→处理中→已解决/已驳回，close 时末段显示已关闭） |
| 「不新增写路径」 | 申诉门户侧无任何写路由，而任务要求申诉详情页常驻同意/驳回主行动 | 新增 `/grievances/set_state`（镜像既有 `/leave/set_state` 的写法与守卫，sudo write 既有状态机值，不引入新状态）；请假详情页复用既有 `/leave/set_state`（加可选 reject_reason/next 参数，默认行为不变） |
| 审批人/时间已记录 | 两个模型均无审批人/时间字段 | 不加字段（改模型超出门户增强边界）；通知正文携带审批结果与驳回原因，留痕走 edu.message（含 sent_at 时间戳）；作为遗留观察登记 |
| 「评估待批」 | 教师可操作的评估待办 = 综合评估打分任务（edu.eval.task state=scoring，入口 /my/evaluation）；`edu.admin.eval.*` 的 open 任务学生侧填答、教师无门户操作页 | 提醒卡用 `edu.eval.task state='scoring'` 计数（教师真正可办的事），链接 /my/evaluation；既有 KPI「进行中评估」徽标（edu.admin.eval 口径）保持不动 |

## 1. 改动清单

| 文件 | 内容 |
|---|---|
| `controllers/batch2.py` | ① `_approval_alerts()`：教师/教务工作台待办聚合（待批请假/待处理申诉/评估待打分，0 计不进列表；href 按角色分流：有教师档案→门户页，否则→后台「教务审批」action）；② `_teacher_dashboard` 注入 `approval_alerts`；③ `_alert_counts` 补申请人侧计数（my/time_off=状态已更新的请假数、my/grievances=有进展的申诉数，供学生首页提醒卡 + 水位清零复用）；④ `_ALERT_CARDS` 两张卡的标题改为与实际语义一致（「新申诉」→「申诉进展更新」） |
| `controllers/roles.py` | ① `/leave/approvals/<id>` 详情页（守卫同列表 = current_faculty）；② `/leave/set_state` 加可选 `reject_reason` 写入与 `next` 回跳（默认行为不变）+ 流转时通知申请人；③ 新增 `/grievances/approvals` 列表、`/grievances/approvals/<id>` 详情、`/grievances/set_state` 写路由（守卫 current_faculty，只接受 in_progress/resolve/reject 三个既有状态值） |
| `models/leave.py` | `_notify_applicant()`：状态流转后经 edu.message 通知申请人（发件人=审批人、正文含申请号/日期区间/结果/驳回原因；收件人无门户账号或=审批人则跳过；try/except 保证通知失败不影响审批事务）；`action_approve/action_reject` 仅对实际从 request 流转的记录通知 |
| `models/grievance.py` | 同上（action_resolve/action_reject 通知；action_start 不通知——非审批结果） |
| `views/batch2.xml` | `edu_dashboard_teacher` 顶部新增「待办提醒」卡组（每张卡 t-if 计数>0，整块 t-if 非空） |
| `views/roles.xml` | 新模板 `edu_leave_detail` / `edu_grievance_approvals` / `edu_grievance_detail`（顶部常驻同意/驳回主行动 + 状态进度条）；`edu_leave_approvals` 列表行加「详情」链接 |
| `static/src/css/ux_rework.css` | 步骤条样式 `.ux-steps`（done/current/todo/danger 四态，含 reduced-motion/print 回退） |
| `__manifest__.py` | 版本 19.0.1.7.0 → 19.0.1.8.0 |
| `tests/smoke/ux_batch4_a1_approval_smoke.py` | 新增 E2E：学生提交→教师首页提醒卡计数→详情页主行动→同意/驳回→进度条→申请人收到 edu.message（全链路，带清理） |

## 2. E2E 步骤与结果

新增 `tests/smoke/ux_batch4_a1_approval_smoke.py`（27 项断言，requests 会话 + psql 落库复核，造数带【A1冒烟】标记、结束按标记 DELETE）：

| # | 断言 | 结果 |
|---|---|---|
| 0 | 教师 /my/home 200 且含「待办提醒」区；待批请假/待处理申诉计数可解析（基线 20/22） | PASS |
| 1 | 学生提交请假落库 → 教师首页「待批请假」20→21 | PASS |
| 2 | 详情页 `/leave/approvals/<id>` 200：同意/驳回常驻主行动显示 + 步骤条「审批中」current | PASS |
| 3 | 同意 → next 回跳详情；步骤条全 done「已通过」、主行动隐藏；申请人收到 edu.message「【审批通知】…已通过」；学生首页提醒卡「您的请假状态已更新」渲染 | PASS |
| 4 | 驳回（附原因）→ 步骤条「已驳回」danger + 驳回原因可见 + 主行动隐藏；驳回通知送达（含原因） | PASS |
| 5 | 申诉提交 → 教师首页「待处理申诉」22→23；`/grievances/approvals` 列表含新申诉；详情主行动 + 「处理中」步骤；同意（解决）→ 已解决 + 主行动隐藏 + 「【处理通知】…已解决」送达 | PASS |
| 6 | 申诉驳回（附原因）→ 已驳回 + 原因可见 + 通知送达 | PASS |
| 7 | admin / backoffice@local / faculty@local / stu@local / parent@local 五账号 /my/home 全 200 无 Traceback | PASS |
| 8 | 清库按标记 DELETE，leave/msg 零残留 | PASS |

**27/27 全绿。**

## 2.1 回归结果

| 套件 | 结果 |
|---|---|
| `ux_rework_http_smoke.py`（49 路由×角色矩阵） | 49/49 PASS |
| `G_messages_smoke.py`（私信权限矩阵与轮询） | 25/25 PASS |
| `H_event_acl_smoke.py`（事件 ACL） | 7/7 PASS |
| 升级 `-u edu_portal --stop-after-init`（两次：改动后、收尾复核） | `Modules loaded.` ×1、136 modules、ERROR/CRITICAL/Traceback ×0、EXIT=0 |
| `F_roles_smoke.py` | PASS=12 FAIL=1（t12 管理员后台菜单探活）——**与本次无关的既有失败**：git stash 前后（=本次改动前）复跑同样 FAIL t12，属遗留问题，按铁律只记录不修 |

> 观察一：G_messages 在「web 刚 restart 后立即跑」的一次中间运行出现 4 项瞬时 FAIL，紧接着两次复跑均 25/25——判定为重启后首次请求预热/竞态噪音，非代码问题。
> 观察二：本批次实施期间发现同一工作区有并行改动（downloads v2：controllers/downloads.py、models/downloads.py、views/downloads_portal.xml、views/help_center.xml、security/ir.model.access.csv、scripts/check_english.py、F_roles_smoke.md 报告）。A1 提交已按文件清单严格隔离，未包含这些文件；期间一次 git stash/恢复操作已完整还原双方改动（A1 E2E 与回归在还原后的合并树上复跑全绿）。

## 3. 复跑命令

```bash
python3 -m compileall -q custom_addons/edu_portal
docker compose run --rm web odoo -d edu19 -u edu_portal \
    --db_host=db -r odoo -w odoo --stop-after-init
docker compose restart web

python3 tests/smoke/ux_batch4_a1_approval_smoke.py   # A1 全链路 E2E
python3 tests/smoke/G_messages_smoke.py              # 私信回归（通知走 edu.message）
python3 tests/smoke/ux_rework_http_smoke.py          # 49 路由回归
python3 tests/smoke/H_event_acl_smoke.py             # 事件 ACL 回归
```

## 4. 遗留观察（本批次不修）

1. 审批人/审批时间未落库（模型无字段）——如需审计留痕，后续批次可加
   `approver_id/approve_time` 字段（涉及模型迁移，超出本批次门户增强边界）。
2. 学生侧 /my/time_off、/my/grievances 列表行未加步骤条（本批次按任务只做
   教师/教务视角详情页）；学生详情可见性可后续复用 `edu_leave_detail` 模板参数化。
3. 申诉「开始处理」（submitted→in_progress）未挂通知（非审批结果，避免噪音）；
   后台 action_start 保持静默。
4. 教务处/管理员无 op.faculty 档案，门户审批页守卫保持 current_faculty() 不变，
   其待办卡直达后台「教务审批」action——如需门户化需先扩守卫（涉及权限口径，不做）。
