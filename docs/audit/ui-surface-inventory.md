# 门户 UI 表面清单与覆盖率（A 组 · 2026-09-26）

> 这份文档回答一个问题：**门户（登录后学生 / 教师 / 教务 / 家长看到的页面）一共有多少面，
> 其中多少面没有任何门禁看着？** 全部数字可复算，命令见 §0。

## 0. 这是什么 ｜ 谁是单一来源 ｜ 怎么重算

- **单一来源 = `tests/ui/surface.json`**：114 条门户页面，逐条给出 路由 / 模块 / 允许身份 / 覆盖门禁 / 状态。本文是人读版；两者不一致时**以 surface.json 为准**，重跑 `--generate` 对齐。
- 三个 UI 门禁（`ux_v3_route_matrix` / `check_accessibility` / `check_english`）各自维护**手写名单**，互相不一致，新页面会自动落在名单外 —— 这份清单就是给它们当**分母**用的。
- **登记全、量得窄**：surface.json 登记**全部 277 条去重路由**（页面 159 + 端点 118，含写路由），本次的覆盖率只量其中的**门户页 120 条** —— 登记是为了让 E 组的消费门禁（scripts/check_ui_surface.py）能回答「有没有新路由漏网」，量测是为了回答「有多少面没人看着」。
- **范围机器可读（scope，2026-09-26 队长裁定新增）**：portal ｜ public ｜ endpoint ｜ other —— portal = 目标集（120 条）；public = 非门户且 auth=public（匿名可到达的公开站 / 营销 / 帮助页）；endpoint = kind=endpoint（导出 / 文件 / 数据接口，含写路由）；other = 其余（登录 / 注册 / 后台兼容路由）。判据见 `scripts/ui_surface_report.py::row_scope`；覆盖率只量 portal。
- 复算命令（零环境依赖：不连 DB、不发 HTTP、不读容器，停机可跑）：

```bash
python3 scripts/ui_surface_report.py --generate   # 从源码重生成 surface.json（保留已填字段）
python3 scripts/ui_surface_report.py --coverage   # 打印覆盖率 + 死角逐条 + 分型
python3 scripts/ui_surface_report.py             # 核对：表与源码是否同步（0=一致 1=幽灵 3=漏登记）
python3 scripts/ui_surface_report.py --selftest   # 反例自检（25 条断言，/tmp 夹具）
```

### 抽取口径 = **装饰器括号配对**（2026-09-26 队长修正）

逐文件定位 `@http.route(`，向右配对括号拿到整个调用体（字符串与注释里的括号不计），
再取调用体内**所有**以 `/` 开头的字符串字面量。**不要用单字符串正则**（只认紧随其后的
第一个引号串的那类写法）—— 它会漏掉 5 处列表形式声明：

| 口径 | 声明 | 去重路径 | 门户页 |
| --- | --- | --- | --- |
| 单字符串正则（旧） | 288 | 271 | 116（漏 4 条家长 / 评估页） |
| **装饰器括号配对（现行）** | **295** | **277** | **114** |

被旧口径漏掉的 6 条路由（其中 4 条属门户页）：

- `/my/evaluation/new`（门户页）
- `/my/child/<int:child_id>`（门户页）
- `/my/child/<int:child_id>/leave`（门户页）
- `/my/child/<int:child_id>/leave/saved`（门户页）
- `/campus/jobs/<int:posting_id>`（公开站，不在门户 114 条内）
- `/campus/jobs/<int:posting_id>/sent`（公开站，不在门户 114 条内）

脚本另用 `ast` 交叉核对两条抽取路径的路径集：**本轮差集为空**（两法一致）。

## 1. 覆盖率读数（2026-09-26）

```
路由声明 295 条 ｜ 去重 277 条 ｜ 写路由（methods 不含 GET）88 条 ｜ 可读路由 189 条 = 页面 159 + 端点 30

门户 114 ｜ 已覆盖 71 ｜ 死角 43
  route_matrix  覆盖 68
  accessibility 覆盖 13
  english       覆盖 61
surface.json 登记 278 条 = 页面 160 + 端点 118（含写路由）；本次覆盖率只量**门户页 114 条**
scope 分布：portal 114 ｜ public 24 ｜ endpoint 112 ｜ retired 12 ｜ other 16
继承上级门禁（只登记意图，非直探本页）：0 条
```

- 三个门禁的登记集按**路径精确相等**与门户页取交（不做参数归一化 —— 归一化会把「列表页 vs 详情页」合并，而那正是本轮要量出来的那类死角）。
- `route_matrix` 的登记集 = `ROUTES` ∪ `REDIRECT_STRICT` ∪ `REDIRECT_STRICT_BY_ROLE`：后两张表是同样在跑的强断言；`/my/checkin/save` 只被它们覆盖，只读 ROUTES 会把它误判成死角。
- 三个计数有重叠：并集 = 已覆盖 71，**一条都没覆盖的 = 死角 43**（= 38% 的门户页没有任何门禁看着）。
- 修正口径后**三个门禁各自覆盖数没变**（68 / 13 / 61），但分母从 116 变成 114、死角从 41 变成 43 —— 新增的 4 条（家长 /my/child/* 三条 + 评估 /my/evaluation/new）**全部落在门禁之外**。

## 2. 死角的规律：用实际数据验证初判

初判是「**点进去之后**：详情页 / 写操作入口页 / 新模块 / 自助服务页」。逐条量过之后：
**方向对，但要修正三处**。

| 型 | 条数 | 代表路由 |
| --- | --- | --- |
| 参数页 / 令牌页（有参数段，上级未登记） | 15 | `/my/child/<int:child_id>/leave`、`/my/courses/<int:subject_id>/rep`、`/quiz/<int:qid>/result/<int:aid>` |
| 详情 / 子页（点进去之后：上级已登记，本级没有） | 11 | `/eval/review/<int:task_id>`、`/journals/review/<int:entry_id>`、`/leave/approvals/<int:leave_id>` |
| 写操作面（表单 / 提交 / 回执 / 动作） | 9 | `/my/child/<int:child_id>/leave/saved`、`/attendance/import`、`/leave/transfer` |
| 自助服务页 / 其它内容页 | 7 | `/grading/history`、`/my/documents`、`/my/documents/enrollment-certificate` |
| 数据 / 轮询面（接口被算成页面） | 1 | `/my/messages/poll` |

### 修正 1：「点进去之后」是主因，但要拆成两半

- **带参数段的页面共 26 条，占死角 60%** —— 这类页面必须先从别处点进来（要带 id / token），正是初判说的那一类。
- 但要分两半：**11 条的上级页面已登记**（列表页有人看着、详情页没人看 —— 补门禁最省力）；另 **15 条连上级都没登记**（token 直入页 / 子资源，例如 `/attendance/selfcheck/<token>`、`/subject/material/detail/<int:sid>`）。

### 修正 2：「新模块」不是一种**形态**，而是一个**模块维度**的事实

按模块看覆盖率（门户页 / 已覆盖 / 死角）：

| 模块 | 门户页 | 已覆盖 | 死角 | 覆盖率 |
| --- | --- | --- | --- | --- |
| `edu_portal` | 90 | 57 | 33 | 63% |
| `edu_assess` | 6 | 3 | 3 | 50% |
| `edu_eval` | 4 | 2 | 2 | 50% |
| `edu_quiz` | 4 | 2 | 2 | 50% |
| `edu_schedule` | 3 | 1 | 2 | 33% |
| `edu_life` | 5 | 4 | 1 | 80% |
| `edu_public` | 2 | 2 | 0 | 100% |

覆盖率最低的四个模块：`edu_schedule` 1/3（33%）、`edu_assess` 3/6（50%）、`edu_eval` 2/4（50%）、`edu_quiz` 2/4（50%）。缺口**绝对数**最多的是 `edu_portal`（33 条，占全部死角 77%）—— 它承载了 90/114 的门户页，摊薄之后的覆盖率反而是中游。

新模块确实整块偏弱（`edu_assess` 3/6、`edu_quiz` 2/4），但它们缺口的**形态**依旧是「带参数页 + 写操作面」，不是一种独立形态 —— 初判的「新模块」应记为**成因**，不是**形态**。

### 修正 3：多了一型，初判没提

- **数据 / 轮询面** 1 条：`/my/messages/poll`。它是轮询接口，却因为端点判据只认 token（export / download / file / xlsx / csv / pdf / json / blank / report、`/data/`、`/ics/`）而被算成「页面」。这条同时暴露**端点判据的边界**：poll 这类数据面不在 token 表里。
- 写操作面 9 条、自助服务页 7 条：与初判一致。

## 3. 114 页逐条表

（覆盖门禁 = 该门禁**登记了**这条路径；`—` = 没有任何门禁登记，即死角）

| # | 路由 | 模块 | 允许身份 | 覆盖门禁 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | `/assess` | `edu_assess` | 管理员/教务/教师/学生 | english | unverified |
| 2 | `/assess/fill/<int:task_id>` | `edu_assess` | 学生 | — | gap |
| 3 | `/assess/grade/<int:task_id>` | `edu_assess` | 管理员/教务/教师 | — | gap |
| 4 | `/assess/my` | `edu_assess` | 学生 | english | unverified |
| 5 | `/assess/review` | `edu_assess` | 管理员/教务/教师 | english | unverified |
| 6 | `/assess/task/<int:task_id>/results` | `edu_assess` | 管理员/教务/教师 | — | gap |
| 7 | `/attendance/import` | `edu_portal` | 教师 | — | gap |
| 8 | `/attendance/selfcheck/<token>` | `edu_portal` | 学生 | — | gap |
| 9 | `/attendance/take` | `edu_portal` | 教师 | route_matrix、accessibility、english | unverified |
| 10 | `/certificate` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 11 | `/checkins/stats` | `edu_life` | 教师/学生 | route_matrix、english | unverified |
| 12 | `/course/change/request` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 13 | `/eval/fill/<int:task_id>` | `edu_eval` | 管理员/教务 | — | gap |
| 14 | `/eval/my` | `edu_eval` | 学生 | route_matrix、english | unverified |
| 15 | `/eval/review` | `edu_eval` | 学生 | route_matrix、english | unverified |
| 16 | `/eval/review/<int:task_id>` | `edu_eval` | 学生 | — | gap |
| 17 | `/grading/entry` | `edu_portal` | 教师 | route_matrix、accessibility、english | unverified |
| 18 | `/grading/history` | `edu_portal` | 管理员/教务/教师 | — | gap |
| 19 | `/help` | `edu_portal` | 匿名 | route_matrix、accessibility、english | unverified |
| 20 | `/help/faculty` | `edu_portal` | 匿名 | route_matrix、english | unverified |
| 21 | `/help/parent` | `edu_portal` | 匿名 | route_matrix、english | unverified |
| 22 | `/help/registrar` | `edu_portal` | 匿名 | route_matrix、english | unverified |
| 23 | `/help/student` | `edu_portal` | 匿名 | route_matrix、english | unverified |
| 24 | `/journals/review` | `edu_life` | 教师 | route_matrix、english | unverified |
| 25 | `/journals/review/<int:entry_id>` | `edu_life` | 教师 | — | gap |
| 26 | `/leave/<int:leave_id>/return_confirm` | `edu_portal` | 管理员/教务 | — | gap |
| 27 | `/leave/approvals` | `edu_portal` | 学生/教师/家长/教务 | route_matrix、accessibility、english | unverified |
| 28 | `/leave/approvals/<int:leave_id>` | `edu_portal` | 管理员/教务 | — | gap |
| 29 | `/leave/transfer` | `edu_portal` | 学生/教师/家长/教务 | — | gap |
| 30 | `/ledger` | `edu_portal` | 学生/教师/家长/教务 | route_matrix、accessibility、english | unverified |
| 31 | `/ledger/new` | `edu_portal` | 学生/教师/家长/教务 | route_matrix | unverified |
| 32 | `/ledger/reimburse` | `edu_portal` | 学生/教师/家长/教务 | route_matrix、english | unverified |
| 33 | `/library/media` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 34 | `/library/media/info/<int:mid>` | `edu_portal` | 学生/教师/家长/教务 | — | gap |
| 35 | `/meeting/information` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 36 | `/my` | `edu_portal` | 学生/教师/家长/教务 | route_matrix、english | unverified |
| 37 | `/my-courses` | `edu_public` | 学生/教师/家长/教务 | route_matrix | unverified |
| 38 | `/my-library` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 39 | `/my/academic-calendar` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 40 | `/my/apps` | `edu_portal` | 学生 | route_matrix、accessibility、english | unverified |
| 41 | `/my/asset-request` | `edu_portal` | 学生/教师/家长/教务 | route_matrix | unverified |
| 42 | `/my/assets` | `edu_portal` | 家长/学生 | route_matrix、english | unverified |
| 43 | `/my/calendar` | `edu_portal` | 学生/教师/家长/教务 | route_matrix、english | unverified |
| 44 | `/my/calendar/new` | `edu_portal` | 学生/教师/家长/教务 | — | gap |
| 45 | `/my/checkin` | `edu_portal` | 学生/教师/家长/教务 | route_matrix | unverified |
| 46 | `/my/checkin/board` | `edu_portal` | 学生/教师/家长/教务 | route_matrix | unverified |
| 47 | `/my/checkin/save` | `edu_portal` | 学生/教师/家长/教务 | route_matrix | unverified |
| 48 | `/my/checkins` | `edu_life` | 学生/教师/家长/教务 | route_matrix、english | unverified |
| 49 | `/my/child` | `edu_portal` | 家长 | route_matrix、accessibility、english | unverified |
| 50 | `/my/child/<int:child_id>` | `edu_portal` | 家长 | — | gap |
| 51 | `/my/child/<int:child_id>/leave` | `edu_portal` | 家长 | — | gap |
| 52 | `/my/child/<int:child_id>/leave/saved` | `edu_portal` | 家长 | — | gap |
| 53 | `/my/contacts` | `edu_portal` | 教师/家长/学生 | route_matrix、english | unverified |
| 54 | `/my/courses` | `edu_portal` | 教师/家长/学生 | route_matrix、english | unverified |
| 55 | `/my/courses/<int:subject_id>` | `edu_portal` | 教师/家长/学生 | — | gap |
| 56 | `/my/courses/<int:subject_id>/rep` | `edu_portal` | 学生/教师/家长/教务 | — | gap |
| 57 | `/my/courses/lesson/<int:lesson_id>` | `edu_portal` | 教师/家长/学生 | — | gap |
| 58 | `/my/dms` | `edu_portal` | 学生/教师/家长/教务 | route_matrix、english | unverified |
| 59 | `/my/documents` | `edu_portal` | 学生 | — | gap |
| 60 | `/my/documents/enrollment-certificate` | `edu_portal` | 学生 | — | gap |
| 61 | `/my/documents/transcript` | `edu_portal` | 学生 | — | gap |
| 62 | `/my/evaluation` | `edu_portal` | 学生/教师/家长/教务 | route_matrix | unverified |
| 63 | `/my/evaluation/new` | `edu_portal` | 学生/教师/家长/教务 | — | gap |
| 64 | `/my/evaluation/results` | `edu_portal` | 学生/教师/家长/教务 | route_matrix | unverified |
| 65 | `/my/evaluation/task/<int:task_id>` | `edu_portal` | 学生/教师/家长/教务 | — | gap |
| 66 | `/my/fees` | `edu_portal` | 教师/家长/学生 | route_matrix、accessibility、english | unverified |
| 67 | `/my/grievances` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 68 | `/my/help` | `edu_portal` | 学生/教师/家长/教务 | route_matrix、english | unverified |
| 69 | `/my/home` | `edu_portal` | 管理员/教务/教师/学生 | route_matrix、accessibility、english | unverified |
| 70 | `/my/journals` | `edu_life` | 学生 | route_matrix、english | unverified |
| 71 | `/my/lang/<string:code>` | `edu_portal` | 匿名 | — | gap |
| 72 | `/my/messages` | `edu_portal` | 学生/教师/家长/教务 | route_matrix、accessibility、english | unverified |
| 73 | `/my/messages/<int:uid>` | `edu_portal` | 学生/教师/家长/教务 | — | gap |
| 74 | `/my/messages/poll` | `edu_portal` | 学生/教师/家长/教务 | — | gap |
| 75 | `/my/notice/<int:notice_id>` | `edu_portal` | 学生/教师/家长/教务 | — | gap |
| 76 | `/my/notice_banner` | `edu_portal` | 学生/教师/家长/教务 | — | gap |
| 77 | `/my/notice_board/notice` | `edu_portal` | 管理员/教务/教师/学生 | route_matrix、english | unverified |
| 78 | `/my/notify` | `edu_portal` | 学生/教师/家长/教务 | route_matrix、english | unverified |
| 79 | `/my/password` | `edu_portal` | 学生/教师/家长/教务 | route_matrix、english | unverified |
| 80 | `/my/points` | `edu_portal` | 教师 | route_matrix、english | unverified |
| 81 | `/my/points/me` | `edu_portal` | 学生 | — | gap |
| 82 | `/my/reimburse/apply` | `edu_portal` | 教师/学生 | — | gap |
| 83 | `/my/reimburse/receipt/<int:bill_id>/<int:att_id>` | `edu_portal` | 学生/教师/家长/教务 | — | gap |
| 84 | `/my/search` | `edu_portal` | 家长/学生 | route_matrix、english | unverified |
| 85 | `/my/study` | `edu_portal` | 管理员/教务/教师/家长/学生 | route_matrix、accessibility、english | unverified |
| 86 | `/my/study/<int:subject_id>` | `edu_portal` | 管理员/教务/教师/家长/学生 | — | gap |
| 87 | `/my/study/session/<int:session_id>/join` | `edu_portal` | 家长/学生 | — | gap |
| 88 | `/my/thesis` | `edu_portal` | 学生/教师/家长/教务 | route_matrix、english | unverified |
| 89 | `/my/time_off` | `edu_portal` | 学生 | route_matrix、accessibility、english | unverified |
| 90 | `/online-exams` | `edu_public` | 匿名 | route_matrix、english | unverified |
| 91 | `/online/meeting` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 92 | `/quiz` | `edu_quiz` | 学生 | route_matrix、english | unverified |
| 93 | `/quiz/<int:qid>/result/<int:aid>` | `edu_quiz` | 学生 | — | gap |
| 94 | `/quiz/<int:qid>/take` | `edu_quiz` | 学生 | — | gap |
| 95 | `/quiz/my` | `edu_quiz` | 学生 | route_matrix、english | unverified |
| 96 | `/registrar/curriculum` | `edu_portal` | 管理员/教务 | — | gap |
| 97 | `/registrar/subject/approvals` | `edu_portal` | 管理员/教务/教师 | route_matrix、english | unverified |
| 98 | `/registrar/subject/approvals/<int:rid>` | `edu_portal` | 管理员/教务/教师 | — | gap |
| 99 | `/requested/queue/list` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 100 | `/student/assignment/details` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 101 | `/student/attendance` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 102 | `/student/exam` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 103 | `/student/profile` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 104 | `/student/progression` | `edu_portal` | 学生 | route_matrix | unverified |
| 105 | `/student/subjects` | `edu_portal` | 学生 | route_matrix | unverified |
| 106 | `/student/timetable` | `edu_portal` | 教师/家长/学生 | route_matrix、accessibility、english | unverified |
| 107 | `/subject/details` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 108 | `/subject/enroll` | `edu_portal` | 学生 | — | gap |
| 109 | `/subject/material/detail/<int:sid>` | `edu_portal` | 学生 | — | gap |
| 110 | `/subject/registration` | `edu_portal` | 学生 | route_matrix、english | unverified |
| 111 | `/timetable/batch/<int:bid>/deactivate` | `edu_schedule` | 管理员/教务 | — | gap |
| 112 | `/timetable/bulk` | `edu_schedule` | 管理员/教务 | route_matrix、english | unverified |
| 113 | `/timetable/session/<int:sid>/impact` | `edu_schedule` | 管理员/教务 | — | gap |
| 114 | `/users/result-overview` | `edu_portal` | 学生 | route_matrix、english | unverified |

## 4. 已排除的假红（记下来免得下一个人重走）

1. **「/timetable /library /attendance /subjectreg /leave 是死卡」→ 假红。**
   那是已退役 `edu_telegram` 的**机器人命令别名**，不是浏览器路由；`custom_addons/**/*.py` 里没有这些路径的 `@http.route` 声明，
   所以它们不出现在表面清单里 —— 这是**正确**的，不是漏。
2. **「73 个模板不用门户外壳」→ 假红。** Odoo 核心模板（mail.* / web.login_layout / website.layout）本就该用自己那套外壳；少掉的只是 edu_portal.edu_page 这层壳，
   与「这个面有没有人看着」无关。
3. 本清单**不含**普通端点（导出 / 文件 / 数据接口）：189 条可读路由里 30 条被端点判据分流出去
   （例如 `/downloads/mine/export`、`/grading/export`、`/my/calendar/ics/<token>`），本次范围只到**门户页面**。
   端点要不要进门禁是另一个决定（判据边界见 §5 第 4 条）。

## 5. 表面清单的排除项

### 5.1 退役模块（scope=retired）：edu_telegram 12 条

**本项目最容易踩的雷，所以写在数据层而不是靠人记**：edu_telegram 在本仓是 v2.2 历史快照，**从未部署**；生产上跑着的同名模块是**另一个**（匿名意见收集机器人）—— 同名不同物。判据三条（逐条可查）：

1. `scripts/deploy_myedu.sh` 的部署模块清单里**没有** edu_telegram；
2. `docs/code-map.md:142-144` 明写「**从未部署；2026-09-17 用户裁定退役**」；
3. 弃用台账 `docs/audit/deprecated-inventory.md` §B8 同款登记。

处置：这 12 条路由 scope=retired、status=n/a、gates=[]（不进门禁、不进覆盖率分母），reason 逐条写明退役理由；**门户目标集因此从 120 条收敛到 114 条** —— 其中 6 条曾是门户页：
/my/marks、/my/marks/<int:exam_id>、/my/rollcall、/my/rollcall/<int:session_id>、/my/subject-reg、/my/telegram。

### 5.1.1 退役**暴露出的**门禁名单腐坏（属 B 组 / E 组处置）

把退役行置为 `gates=[]` 之后，**名单腐坏立刻显形**（这正是数据层根治的价值）：

- `tests/smoke/ux_v3_route_matrix.py` **已于本轮切到形态 B（读 surface.json 里 gates 含 route_matrix 的条目）** ⇒ 退役行 `gates=[]` 自动不再被探 —— 无需改脚本，4 条死路由自动消失（实测该门禁已不再报）。
- `scripts/check_english.py` **仍是写死名单**，里面还留着 **3 条退役路由**： `/my/marks`（:126）、`/my/rollcall`（:126）、`/my/subject-reg`（:127）⇒ E 组消费门禁（`scripts/check_ui_surface.py`）报 **3 条**「X 脚本里有，surface 未登记 X」。

处置建议（**都不要改本表** —— 表是事实）：B 组把 `check_english.py` 这 3 条删掉（或同样切形态 B）；或 E 组给 `scope=retired` 开不变式 3 的豁免。表里给它们记 gates 才是错的：那些 URL 生产上不存在，探它只会得到假读数。



### 5.2 范围外（不是退役，只是不在本次目标集）

scope 字段把范围变成机器可读的：**portal 114 ｜ public 24 ｜ endpoint 112 ｜ retired 12 ｜ other 16**
公开站 / 端点 / 登录注册后台等照样**登记**在 surface.json 里（E 组门禁要求每条路由都在册），只是不进覆盖率分母。

## 6. 口径边界与已知不足

1. **路径为变量、静态抽不到的声明 1 条**：`custom_addons/edu_tg_bind/controllers/webhook.py:42` 的 `telegram_tgb_webhook`（Telegram webhook 用常量拼路径）。抽取器**点名**它而不静默跳过 —— 静默跳过正是 `check_manifest_tracking.py` 的 t124 教训。
2. **允许身份的来源**（每一页的 `roles` 是怎么来的；`role_src` 是脚本内部字段，落盘时不写出）：

| 来源 | 条数 | 含义 |
| --- | --- | --- |
| `backfill` | 64 |  |
| `handler` | 37 | handler 身份谓词扫描 |
| `default-logged` | 12 | 兜底：已登录全身份（**未判过**） |
| `default-public` | 1 | 兜底：匿名（auth=public） |

   优先序：矩阵登记（人手判过）> handler 源码身份谓词扫描（current_student / privileged_staff / faculty_of_user …）> 兜底。**兜底不等于已判定**：`default-logged` 的 12 条只是「还没人判过，先按已登录全身份记」。
3. **`ui_surface` 这个门禁名本轮不给任何页面记覆盖**：本脚本现在只负责读表，还没逐条断言；给自己记覆盖会把 43 条死角一夜清零。
4. **端点判据的边界**：只认 token 表 + `/data/` + `/ics/`，所以 `/my/messages/poll` 这类数据面会被算成页面（反向的漏判也可能存在）。
5. **死角分型是启发的**：判据写在 `scripts/ui_surface_report.py` 的 `gap_type` 上方；改判据会让分型条数变，但覆盖率三数不变。
6. **`status` 语义**：`unverified` = 有门禁登记但没人验证过 UI；`gap` = 三个门禁一条都没登记；`verified` 目前 **0 条**（还没人回填证据）。`reason` 只在 `gates` 为空时非空。

7. **与 E 组门禁的口径分歧 —— 本轮已解决**：E 组已收窄字面量抽取（限定模块级名单常量、排除函数体），实测 scripts/check_ui_surface.py 现为 **0 违规 / exit 0**。以下保留原始分歧记录备查：不变式 3反向比对「脚本里出现的路由字面量」，而它的字面量抽取覆盖**整份脚本文本**（含注释与 selftest 夹具）。于是 /web/register 被判定应由 check_english.py 覆盖 —— 实际那里只有反面样本：check_english.py:703（selftest 的 inv_cases 夹具）与 :792（prove_invariant 的样本），两条都是「这个替身**必须报红**」的证据，不是扫描面。本表按事实登记 gates=[route_matrix]（矩阵真的探它，ROUTES 第 73 行），消费门禁因此剩 1 条 FAIL。修法应在消费门禁侧收窄字面量抽取（限定到名单赋值、排除 selftest / prove-invariant 区段），**不应**在表里给 english 记一笔假覆盖。

8. **scope 判据**（五值）：见 §0 的「范围机器可读」与 §5；计数由 `--coverage` 打印。改判据只影响 scope 分布，不影响覆盖率三数。
9. **待补样本 0 条**（队长 2026-09-26 二次裁定：**待办不是覆盖**）：这些子页**没有任何门禁真探过**，所以 gates 为空、status=gap，只登记 pending_gate（该补进哪个门禁）；reason 写「上级 X 已在 Y 扫描集内；本页需补样本 id 才能被真探」，evidence 写**样本 id 从哪来**（含 `需造样本` 的 2 条：/quiz/<qid>/result/<aid> 要 attempt 行、/my/courses/<id>/rep 要课代表绑定）。⚠ 门禁探的是具体 URL：上级被探 ≠ 本页被探。上一版把「继承」记进 gates，正是队长说的**用没量过的数字冒充覆盖**。
10. **端点判据的规格笔误（队长已认账）**：规格里写的正则带前导斜杠（/ 与 \/ 等价），**字面实现等于要求 路径里出现 //file，会漏 3 条端点**（按字面实现得 页面 162 + 端点 27）。本脚本按**不带前导斜杠**实现，才是队长的 153 / 30（全量下 159 / 30）。**不要照着错规格改回去。**
11. **迁移只搬了「覆盖面」，没搬「身份断言」（本次自查发现，队长点名要写进口径边界）**：B 组把矩阵从「脚本写死 ROUTES」迁到「读 surface.json」时，搬运的是**探哪些页**；而旧脚本里「**哪个角色必须 200**」的期望集没被搬过来 ⇒ 91 条 roles 与旧期望不一致，其中 **22 条与探针角色无交集**，矩阵对它们只剩「不 5xx / 不 404」，**不再断言必须 200**—— 这是**静默削弱**，比事故隐蔽。处置：船长 2026-09-26 裁定回填，本脚本内置ROLE_BACKFILL（91 条，来源 /tmp/roles_backfill.txt，优先级最高）逐条写回 roles；回填后与探针角色无交集者 **0 条**。**下一个人注意：把「名单」搬到表里时，断言口径（身份/期望）必须一起搬。**
12. **表内非仓内路由**：`/` 由 Odoo website 核心渲染，不在 custom_addons 的 @http.route 里，但三张门禁都会探它 ⇒ 由 EXTRA_ROUTES 显式登记（kind=page / scope=public / 三张门禁全覆盖）。E 组已落 `ALLOW_NO_ROUTE` 例外（命中不报 [stale]，且打 ALLOW 行 —— 可见、非静默）。
13. **一次真实事故（2026-09-26）与它的三条护栏**：队长裁定「表 ← 门禁字面量」与「门禁 ← 表」两个方向同时存在 ⇒ 三张门禁切成形态 B（读表）后，脚本里再没有字面量可派生，而我一次「删表重生成」把 route_matrix 覆盖清空了 90 条（跨 3 个版本指纹可见）。修复：① 从 git HEAD 的旧脚本取回 97 条静态登记（+ B 组清单逐条对账，参数化 13 条按裁定只登记pending_gate）；② load_gates() 认形态 B：该门禁的登记集**从表里读回**，不再从字面量派生；③ --generate 加**防静默丢失护栏 A/B/C** —— 表读不到 / 门禁集合塌 / 会移除已有 gates 一律**拒绝执行**，要显式 --force，且无论是否 force 都打印改动摘要（改动 N ｜ 新增 X ｜ 移除 Y ｜ 表指纹）。

---

生成时刻：2026-09-26 21:34:27 ｜ 本文档的数字由 `scripts/ui_surface_report.py` 的读数算出，重跑 `--coverage` 可复现。
