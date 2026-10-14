# 批次 4（P2）+ 清理包 · 总回归报告
> **状态**：`归档` ｜ **主题**：`批次4 P2 回归` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 日期：2026-08-29 ｜ 环境：本地 edu19 栈（http://127.0.0.1:8069，docker edu19-clone，PG16）
> 性质：交付前总回归 + 验收材料（截图）留档。只测不改（测试自建数据已全部清理，零残留）。

## 1. 提交链一览（本批次 8 个提交）

| Hash | 一句话 |
|---|---|
| 4608e7b | W3 角标全站审计：补齐教师常用区/首页铃铛/待办 KPI 三处 0 值角标覆盖 |
| 57c9dab | A1 审批待办聚合：教师首页「待办提醒」卡/请假与申诉详情页主行动+步骤条/审批后 B5 通知 |
| 4e34816 | 清理包：教师访问学生页死胡同——警告条加「返回门户首页」出口 |
| 80f8601 | 清理包：custom_home.css 清理被品牌变量取代的死代码规则 |
| 766dc7a | 清理包：timetable guest 分支标题改读 title 变量，去掉硬编码 |
| 1205a9b | 清理包：ux-rework handoff 收尾数值与 _active_term 命名对齐实况（文档） |
| d73a2dd | 清理包：CSS 溯源抽查复核记录（只查不改，文档） |
| 7d381f1 | 清理包：batch4 清理轮遗留观察笔记归档（文档） |

> 注：历史中另有并行任务（downloads v2：16d64c8/3db57ff/8ea160d/0a98d34）与本链交错提交，
> 不属本批次范围；本轮回归在其合并后的工作树上执行，等效于对两者共存状态的验证。

## 2. 回归矩阵

| # | 套件 | 覆盖 | 结果 | 失败分析 |
|---|---|---|---|---|
| 1 | `run_smoke.sh`（smoke_anon + smoke_student + 汇总） | 匿名公开面 7 项 + 学生面 8 项 | **15/15 PASS**，EXIT=0 | — |
| 2 | `ux_rework_http_smoke.py` | 49 路由 × 角色矩阵 + S2/S3 表单链路 | **49/49 PASS** | — |
| 3 | `ux_batch4_a1_approval_smoke.py` | A1 审批全链路 E2E（提交→提醒卡→详情→审批→通知→清库） | **27/27 PASS**，leave/msg 零残留 | — |
| 4 | `G_messages_smoke.py` | 私信权限矩阵与轮询 | **25/25 PASS**（首跑即绿，未触发复跑预案） | — |
| 5 | `ux_rework_playwright.py` | 首页常用区编辑/弹窗/课表与日历视图切换/排课向导 | **32/32 PASS** | — |
| 6 | `H_event_acl_smoke.py` | edu.event ACL 收紧回归 | **7/7 PASS** | — |
| 7 | `D_public.py` | 游客公开页 15 项只读检查 | **15 PASS / 0 WARN / 0 FAIL** | — |
| 8 | `F_roles_smoke.py` | 教师/家长/管理员三角色 13 项 | **PASS=12 FAIL=1** | t12 **既有失败**（见 2.1） |
| 9 | `E_quiz_cross.py` | 测验全流程 + 铃铛/搜索横切面 + 日志巡检 | **PASS=7 FAIL=2** | B6/B8（见 2.2、2.3） |

汇总：**9 套件合计 192 项断言，189 PASS / 0 WARN / 3 FAIL**；3 个 FAIL 中
0 个产品回归（1 个既有、1 个环境噪音类、1 个本轮 W3 行为变更导致的旧断言失配）。

### 2.1 F_roles t12「管理员后台菜单探活」——既有失败，非本轮引入

- 现象：odoo shell 内对 7 个根菜单 xmlid 逐一 env.ref + action/res_model 探活，
  `menu_edu_scheduling_root`（排课管理）在本库 MISSING，其余 6 项有效。
- 定性：与 `batch4-p2-a1-approval-aggregation.md` §2.1 记载一致（当轮 git stash 前后均
  FAIL t12），且与并行任务 `tests/smoke/F_roles_smoke.md` 中的 t12 记录逐字吻合
  （本库根菜单数字 id 与任务书引用不同，env.ref 该 xmlid 落空）。属**测试脚本 xmlid
  与库状态漂移的既有问题**，与批次 4 改动（只动 edu_portal 视图/控制器/CSS）无关。
- 处置：按铁律只记录不修。注：本轮按并行任务隔离要求，F 脚本运行前对
  `F_roles_smoke.md` 做了字节级备份、运行后原样还原（该文件当前为并行任务的未提交改动）。

### 2.2 E B6「铃铛已读归零」——本轮 W3 行为变更导致旧断言失配（非产品缺陷）

- 现象：stu 铃铛前值 34 → POST /alerts/mark_read 200 → 后值 None（徽标未渲染）→
  脚本 FAIL。
- 定性：**本轮引入**，定位 commit `4608e7b`（W3）：铃铛角标加 `t-if="bell"`，
  0 值不再渲染（与 msg_poll.js 语义一致）。E 脚本的 `zeroed` 判定仍是旧口径
  「徽标存在且值=0」，未跟上「0 值不渲染」新语义。实测行为（归零后徽标整体消失）
  正是 W3 规范要求，产品无缺陷。
- 处置：记录遗留，下批 UX 整理时把该判定改为「全部 None 或全 0 即归零」
  （脚本证据注释已提及 t-if，仅 zeroed 表达式漏改，一行可修）。

### 2.3 E B8「日志巡检(45m)」——环境噪音（bus websocket 握手）

- 现象：45 分钟窗口内 24 行 ERROR/Traceback。
- 定性：8 次 `KeyError: 'socket'` @ `odoo/addons/bus/websocket.py open_connection`，
  即浏览器向 HTTP 8069 端口发起 WebSocket 升级握手失败（WebSocket 应走 8072）。
  堆栈全部为框架层，**无任何应用代码**；窗口恰覆盖本轮全部含真浏览器的套件
  （playwright/F/E），请求频度与浏览器会话吻合。历史基线同项为 WARN（4 行 registry
  冷启动噪音），同属环境类。
- 处置：不修（基础设施层噪音，如需根治应让前端 ws 连接走 8072 或压低握手重试）。

## 3. 截图清单（tests/gap/shots/，真实登录态，1280×800）

| 文件 | 说明 |
|---|---|
| `batch4_teacher_home_todo_alerts.png` | 教师 /my/home 顶部「待办提醒」卡组：待批请假 20 / 待处理申诉 22（A1 产物）；下方常用区 0 值角标灰底为 W3 产物 |
| `batch4_leave_approval_detail.png` | /leave/approvals/31（SLR000015·王小明·待审批）：步骤条「已提交→审批中→已通过/已驳回」+ 常驻「同意/驳回」主行动 + 驳回原因输入（A1 产物） |
| `batch4_teacher_student_page_exit.png` | 教师访问 /student/attendance：角色不符警告条 + 「返回门户首页」出口按钮（清理包 4e34816 产物） |
| `batch4_student_home_bell.png` | 学生 /my/home：迷你头铃铛=2、hero 铃铛=2 正常态（W3 后 0 值不渲染、非 0 显真实值） |

> 截图方法：playwright chrome headless（zh-CN），`.oe_login_form` 表单真实登录。
> 第 4 张为呈现角标「正常态」，临时用 odoo shell 造一条【演示】未读私信（截后即删），
> 已验证库中零残留；1–3 张直接使用库中既有演示数据（SLR000011–15 为历史冒烟留档单）。

## 4. 遗留观察汇总（收拢自三份留痕文档 + 本轮新发现）

| # | 事项 | 级别 | 出处 |
|---|---|---|---|
| 1 | edu_eval 学生档案守卫「死胡同」两条警告无返回出口（eval_portal.xml L155/L238） | P2 | batch4-cleanup-notes §1 |
| 2 | portal.css / enterprise.css 与原站抓取 CSS 同源声明 447 处（去重 201 选择器），重命名 vs 变量化改写需专门批次+全量截图回归 | P2（合规决断） | batch4-cleanup-notes §2 / compliance-audit §5.1 |
| 3 | edu_portal_templates.xml `edu_dashboard`（v1 仪表盘）+ main.py `_dashboard_cards`/`edu_home` 死代码待整段删除 | P2 | W3 §4.1 |
| 4 | 计数角标 `99+` 封顶未实现 | P3 | W3 §4.2 |
| 5 | 移动端底部 Tab「消息」无未读红点 | P3 | W3 §4.3 |
| 6 | 教师大卡「周记批阅/私信」角标 text-bg-danger 计数与「红点仅提醒」语义混用（0 值已隐藏） | P3 | W3 §4.4 |
| 7 | 审批人/审批时间未落库（leave/grievance 无字段，通知正文已携带结果留痕于 edu.message） | P3 | A1 §4.1 |
| 8 | 学生侧 /my/time_off、/my/grievances 列表行无步骤条；学生详情页可见性可复用 edu_leave_detail 参数化 | P3 | A1 §4.2 |
| 9 | 申诉「开始处理」（submitted→in_progress）不通知申请人（设计决定，避免噪音） | 记录 | A1 §4.3 |
| 10 | 教务处/管理员无 op.faculty 档案，门户审批守卫保持 current_faculty()，其待办卡直达后台「教务审批」 | 记录 | A1 §4.4 |
| 11 | custom_home.css `.oe-cat-title` 一条原站逐字声明残留（字号/颜色已被 B11 覆盖） | P3 | batch4-cleanup-notes §3 |
| 12 | custom_home.css 头部块与 B11 段重叠声明（非死代码，保守保留） | P3 | batch4-cleanup-notes §4 |
| 13 | 门户模板含 request.env 无法在 odoo shell 渲染验证（工程备忘：走 HTTP 登录态或临时探针用户） | 备忘 | batch4-cleanup-notes §5 |
| 14 | `edu.job.posting.salary_range: unknown parameter 'placeholder'` 启动警告（已在案） | 备忘 | batch4-cleanup-notes §6 |
| 15 | F_roles t12 排课管理根菜单 xmlid MISSING（既有失败，本轮复现） | 既有 | 本报告 §2.1 |
| 16 | E_quiz B6 `zeroed` 断言未跟上 W3「0 值不渲染」语义（一行可修） | 测试脚本 | 本报告 §2.2 |

## 5. 结论：可交用户验收

- **核心链路全绿**：49 路由×角色矩阵、审批 E2E（27 断言含通知与清库）、私信权限矩阵、
  playwright 交互、事件 ACL、游客公开页、匿名+学生冒烟共 9 套件，除上表 3 类
  既有/环境/断言失配外无一失败，且无任何一例可归因于本轮提交的产品回归。
- 本轮三项产物（W3 角标规范、A1 审批聚合、死胡同出口）均有 HTTP 断言 + 浏览器级截图
  双重留档；E2E 与截图所用临时数据已全部删除（edu.leave 零新建、edu.message 演示条已删）。
- 遗留观察 16 项均已在案并分级，无验收阻塞项。
- **建议：批准进入用户验收。**
