# 零覆盖门户页 · 七轴体检问题账（C 组）

> **一句话结论**（修正 A/B 后重算）：45 条「从未被任何 UI 门禁扫过」的门户页里，**范围内 43 条**（另 2 条属退役模块），**37 条真机探到、6 条按红线未探**；37 条中有问题 **10 条（27.0%）**，其中 **P1 仅 2 条**。
> 而**已被三门禁覆盖的对照组 20 条，问题率反而更高：7 条（35%），P1 1 条（手机端审批按钮跑到视口外）**。
> ⇒ **原结论不仅成立，而且更硬**：P1 密度 1.08 : 1（死角 2/37 = 0.054 vs 对照 1/20 = 0.050）、P1+P2 密度 **0.46 : 1**、有问题密度 **0.77 : 1** —— 三个指标上死角组**都不比已覆盖组差**。**「已覆盖」既不代表无 P1，也不代表更少粗糙问题**：这门禁名单目前没有筛选力，详见 §1.3。

| 项目 | 值 |
|---|---|
| 采集时刻 | HTTP：**2026-09-26 21:02~21:05（+0800）**；视口：**21:06~21:09**；SQL/ORM 复核：**21:09~21:12** |
| 站点 | `http://localhost:8069`（docker `edu19-clone`：`web-1 Up 47 hours`、`db-1 Up 5 days (healthy)`） |
| 数据库 | 本地 `edu19`（`db_name = edu19`、`list_db = False`、`workers = 6`） |
| 身份 | `stu@local` / `faculty@local` / `parent@local` / `backoffice@local`（口令 `demo123`）+ `admin`（**本库口令是 `demo123`，不是 `backoffice_reachability.py` 里写的 `admin`**） |
| 视口 | 375×812（iPhone UA）+ 1280×900，Playwright chromium headless |
| 清单来源 | 队长 2026-09-26 修正版 `/tmp/dead_corners.txt`（41 → **45** 条：补 `/my/child/<id>`、`/my/child/<id>/leave`、`/my/child/<id>/leave/saved`、`/my/evaluation/new`） |
| 与 A 组对账 | `tests/ui/surface.json` 里 `status = "gap"` 的正好也是这 45 条，**逐条一致、0 差异**；但它的生成器**漏了 3 条已被门禁覆盖的门户页**（`/grade-book`、`/downloads`、`/downloads/mine` 在 surface 里查不到），只影响 surface 自身完整性，不影响本账口径 |

---

## 修正记录（队长 2026-09-26 复核后）


| # | 队长指出 | 本轮处置 |
|---|---|---|
| 修正 1 | `edu_telegram`（本仓 v2.2）**从未部署、2026-09-17 已裁定退役**；生产上跑着的同名模块是「匿名意见收集机器人」（同名不同物）⇒ 生产根本没有 `/my/rollcall`、`/my/marks` 这两条路由 | 已核实：`docs/code-map.md`「edu_telegram —— v2.2 四角色教务前端（**从未部署；2026-09-17 用户裁定退役**）」；`scripts/deploy_myedu.sh:35` 的 `MODULES` 为 `edu_life,edu_eval,edu_schedule,edu_apply,edu_portal,edu_brand,edu_tg_bind,edu_assess`，**不含 edu_telegram**。⇒ **`/my/rollcall/<session_id>` 与 `/my/marks/<exam_id>` 改判「范围外（退役模块，生产不存在）」**；P1 由 7 → **6**，全部汇总数字与密度比已重算（§1）。原发现**保留**：它证明「就地自建身份口径」会立刻出错，该模块是反面教材。 |
| 修正 2 | 「教师身份反查落空」表述不准：**唯一口径（双向并集）在本库命中 chain①**，教师链路是通的 | 已核实并改写：psql 实测 `op_faculty 17 → partner 32 → partner.user_id = 11` ⇒ `faculty_of_user(uid=11)` **走 chain① 命中**，所以 `/attendance/take`、`/grading/entry` 对教师 200（与本轮读数一致）。**落空只发生在 `edu_telegram/controllers/portal_ops.py:15` 自建的那套**（先 `hr.employee→emp_id`、再 `partner_id=当前 partner`，两条本地链都落空）——而该模块已退役。 |
| 修正 3 | 补录：`edu_life/controllers/life.py:57` 的 `current_faculty()` **只查 chain①**，违反 `edu_schedule/models/identity.py` 文件头与 `docs/code-map.md §6 第 13 条` 的硬约定 | 已核实并补录进 **§9.1**（P2）。同时如实记录 `fac@local`（uid 9）两条链都落空一事（§9.2，成因未定）。 |
| 补测授权 | 授权对「静态看是纯读页」的路由补测（4 条护栏） | 已按护栏执行：**实际补测 5 条**（逐条先读 handler 源码 → 单次 GET → 探前/探后行数快照）。另 `/my/lang` 死于护栏①（有 `user.write`），5 条死于护栏⑤（队长排除清单）。详见 §4 与 §9.4。 |
| 护栏纪律 | 行数有变 ⇒ 立即停手并写账 | **6 次补测（5 条路由，`/my/reimburse/apply` 走 stu/fac 两个身份）业务表行数 0 变化**；唯一变化是框架自身每请求写 1 行 `res_device_log`（见 §6.1）。 |
| 修正 A | eval 家族 4 条（`/eval/review/<id>`、`/eval/fill/<id>`、`/my/evaluation/new`、`/my/evaluation/task/<id>`）不是缺陷，而是**有意为之的 303 兼容层** | 已复核原文并改判「设计如此（303 兼容层）」，**移出 P1 计入**：`eval_compat.py` 文件头引设计稿 `evaluation-rebuild-design.md §7.4-2`「旧 7 条路由改 303，不删模型、不删表、不改 ACL（先建后删是校长钉死的顺序）」；`edu_assess/controllers/portal.py:926` 是同构的 `class EduAdminEvalCompat(EduAdminEvalPortal)` 继承覆写。⇒ P1 由 6 → **2**，汇总与密度比已重算（§1）。真机读数（5 身份 303）**无误**，改的是定性与级别；旧实现成死代码一事**关联队列待办 ④**，单列不计入本账。 |
| 队长自纠 | 来函（第二次）称 `/journals/review` 也受 `edu_life` 的 chain① 口径影响 | 队长已自行复核并**撤回**该说法，按本轮 §9.1 结论保留（`edu_life` 内只有 life.py:464/576 两处调用；`/journals/review` 走 `_require_teacher()`）。 |

## 0. 方法与判据（可复核）

### 0.1 探活三步（照 `tests/smoke/ux_v3_route_matrix.py::health_check` 的纪律）

| 步骤 | 读数（2026-09-26 21:02） | 判定 |
|---|---|---|
| ① 升级锁 | `$TMPDIR/edu19_upgrade.lock` **不存在** | 通过 |
| ② 容器不是刚重启 | `edu19-clone-web-1 Up 47 hours`（> 30s） | 通过 |
| ③ 带库名探活 | `/web/login?db=edu19` → **302**；`/login?db=edu19` → **200** | 通过 |

### 0.2 采集方式

1. **登录与会话**：完全照抄 `tests/smoke/ux_v3_route_matrix.py:233-263` 的 `login()`（JSON-RPC `/web/session/authenticate` 带 `db` 参数 + `requests.Session` cookie jar），未自创第二套。
2. **HTTP 真机**：每条 `(路径, 身份)` 一次 GET（`allow_redirects=True`，记录 `hist → final → final_path`、字节数、耗时、错误标记），并把**原始 HTML 落盘**到 `/tmp/ui42/html/<组>__<页>__<身份>.html`，分析与请求分离，避免重复请求带来重复副作用。
3. **内容判据（L3 口径，照 `tests/smoke/backoffice_reachability.py` 的「真渲染 + 关键元素命中」）**：只看 HTTP 200 **不算通过**；必须命中所属版式的内容区元素（表单/表头/按钮/空态块），并用 `<main>` 内、剥离门户顶栏与移动底栏后的正文做语言与出口判据。
4. **视口**：Playwright 每页测 375 与 1280：`documentElement.scrollWidth - innerWidth`（横向溢出）、`main` 内主按钮的 bounding box（是否在首屏、是否超出视口宽）、`position:fixed/sticky` 悬浮层与主按钮的相交（遮挡）。
5. **数据样本**：全部用**只读** ORM（`search_read/search_count/fields_get`）定位真实 id；**关键数字另用 `docker compose exec db psql` 只读 SELECT 复核**——因为 `edu.message` 上有**全局 ir.rule**（「仅收发双方本人可见」），非 sudo 的 ORM 计数会被悄悄过滤（本项目一度因此把 523 条未读误读成 0，见 §6.3）。
6. **G 轴（操作闭环）**：**一律不真提交**，按「控制器分支 + 模板结构」判，标注为「静态判定」。

### 0.3 红线执行

- `deactivate|confirm|save|submit|delete|remove|cancel|close|approve|reject|transfer|import|apply|start|stop|send|mark|join|poll` 命中者**一律不发请求**（`approvals` 含 `approve`、`marks` 含 `mark` 也按字面命中）。
- `/my/messages/poll` 按队长指示例外可探（只读 JSON，实测零写）。
- **额外拦下一条清单外的有写路由**：`/attendance/selfcheck/<token>` 名字不含禁用词，但代码在 GET 里 `line.write({present: True})` —— 按「有副作用一律不探」精神未探。
- 探测前对每条候选路径做**零写预检**（读控制器源码 + 读数据），例如 `/my/rollcall/<id>` 先确认 `op.attendance.register` 已存在（否则 GET 会 `create` 自动建册）。

---

## 1. 汇总数字与两组对比

### 1.1 死角组（45 条）

| 口径 | 数 |
|---|---|
| 清单总数 | **45**（范围内 **43** + 范围外 2：退役模块） |
| 真机探到（≥1 身份） | **37**（含队长授权补测的 5 条） |
| 未探（防副作用） | **6**（原 12：5 条已授权补测、1 条移出范围） |
| 37 条中「有问题」 | **10（27.0%）** |
| P1 | **2** |
| P2 | **4** |
| P3 | **4**（新增 `/my/child/<id>/leave/saved` 孤儿别名） |
| 无问题 | 27（另有 4 条判为「设计如此」不计问题） |
| 其中「需数据·未造样本」而无法完整判定的页 | 5（`/library/media/info`、`/my/reimburse/receipt`、`/my/notice_banner`、`/my/courses/<id>/rep`、`/quiz/<id>/take`(学生侧)） |

**P1 两条**：`/timetable/session/<id>/impact`（**教师版文案指向一个被隐藏的按钮**，且内容区无出口）、`/quiz/<qid>/take`（**唯一的已发布测验学生进不去，教师反而能进**）。
> 原判 P1 的 6 条里：4 条 eval 家族已按**修正 A** 改判「设计如此（303 兼容层）」（旧实现成死代码 → 关联**队列待办 ④**，不计入本账）；`/my/rollcall` 已按**修正 1** 移出范围（退役模块）。

### 1.2 对照组（20 条，已被 route_matrix 覆盖）

| 口径 | 数 |
|---|---|
| 页面数 | **20** |
| 有问题 | **7（35%）** |
| P1 | **1**（`/leave/approvals` 手机端横向溢出 126px 且「批准」按钮在视口外） |
| P2 | **6** |
| P3 | 0 |
| 无问题 | 13 |

对照组的 P2 含：门户首页五个英文分类名（`Academics/Resources/Growth/Finance/Community`）、`/student/profile` 与 `/grade-book` 对家长/教务/管理员都说「您当前以**教师**身份登录」、`/quiz` 列表输出「0 items / 1 items」、`/downloads` 空态无下一步 + 英文键位提示、**`/grading/entry` 与 `/attendance/take` 的教务被弹回首页而矩阵仍判 PASS（假绿）**。

### 1.3 密度比（**这是本次体检最重要的结论**）

| 指标 | 死角组（37） | 对照组（20） | 比值 |
|---|---|---|---|
| P1 密度 | 2 / 37 = **0.054** | 1 / 20 = **0.050** | **1.08 : 1** |
| P1+P2 密度 | 6 / 37 = **0.162** | 7 / 20 = **0.350** | **0.46 : 1** |
| 有任何问题密度 | 10 / 37 = **0.270** | 7 / 20 = **0.350** | **0.77 : 1** |

> **结论（不藏，修正后更强）**：**覆盖名单没有起作用**。进了 route_matrix / axe / english 三门禁的 20 条对照组，问题密度**反而高于**死角组（35% vs 27.0%），P1 密度基本持平（0.050 vs 0.054，比值 1.08 : 1）——**「已覆盖」既不保证无 P1，也不保证更少粗糙问题**。
> 换句话说：现有三门禁对「走不通」这一档，实际只剩「不 5xx / 不大面积 404」两层最低保障（原先以为被抓到的「路由被遮蔽」一档，经修正 A 确认是**设计如此**、本来就不该被抓）；而在这层最低保障之下，对照组**仍然留下 1 条 P1**（`/leave/approvals` 手机端「批准」按钮跑到视口外）——说明判据（HTTP 层 + 英文词表 + axe）**在结构上就抓不到「按钮跑出屏幕」这类可用性缺陷**；至于**空态无指引、措辞错、移动端横滑、角色身份错、英文残留**这些「用户每天都会遇到」的问题，更是**完全没有筛选力**。
> 佐证：对照组的 `/quiz`、`/library/media`、`/my/home`、`/downloads` 都**登记了 english 门禁**，却仍然留着「items」「Academics」「Ctrl/Shift」等英文；`/grading/entry`、`/attendance/take` 登记了 route_matrix，教务被弹回首页却判 PASS（矩阵跟随重定向后只看 `final == 200`，见 `ux_v3_route_matrix.py::verdict`）。

---

## 2. 死角组 45 条：一览

> 45 = **范围内 43**（已探 37 + 未探 6）+ **范围外 2**（edu_telegram v2.2 退役模块，生产无此路由）。
> 级别取该页所有身份读数中最重者；「未探」= 按红线未发请求（见 §4）；「设计如此」= 303 兼容层（修正 A，判定依据见 §3 对应条目）。

| 页面 | 探测身份（HTTP 结果） | A 可达 | B 空态 | C 报错态 | D 语言 | E 死胡同 | F 移动端 | G 闭环 | 级别 | 归属期 |
|---|---|---|---|---|---|---|---|---|---|---|
| `/assess/fill/<int:task_id>` | 学生 200 /assess/fill/2；教师 303→200 /my/home；家长 303→200 /my/home；教务 303→200 /my/home；管理员 303→200 /my/home | pass | n/a | n/a | pass | pass | ok | pass(静态) | **—** | — |
| `/assess/grade/<int:task_id>` | 教师 200 /assess/grade/1；教务 200 /assess/grade/1；管理员 200 /assess/grade/1；学生 303→200 /my/home；家长 303→200 /my/home | pass | n/a | n/a | pass | pass | ok | pass(静态) | **—** | — |
| `/assess/task/<int:task_id>/results` | 教师 200 /assess/task/1/results；教务 200 /assess/task/1/results；管理员 200 /assess/task/1/results；学生 303→200 /my/home；家长 303→200 /my/home | pass | n/a | n/a | pass | pass | ok | n/a | **—** | — |
| `/eval/review/<int:task_id>` | 学生 303→200 /assess/my；教师 303→303→200 /my/home；家长 303→303→200 /my/home；教务 303→303→200 /my/home；管理员 303→303→200 /my/home | pass | n/a | n/a | n/a | n/a | n/a | n/a | **设计如此**（303 兼容层） | 教师 |
| `/eval/fill/<int:task_id>` | 学生 303→200 /assess；教师 303→200 /assess；家长 303→200 /assess；教务 303→200 /assess；管理员 303→200 /assess | pass | n/a | n/a | n/a | n/a | n/a | n/a | **设计如此**（303 兼容层） | 学生家长 |
| `/journals/review/<int:entry_id>` | 教师 200 /journals/review/2；教务 200 /journals/review/2；管理员 200 /journals/review/2；学生 303→200 /my/home；家长 303→200 /my/home | pass | n/a | n/a | pass | pass | ok | pass(静态) | **P3** | 教师 |
| `/library/media/info/<int:mid>` | 学生 303→200 /library/media；教师 303→200 /library/media；家长 303→200 /library/media；教务 303→200 /library/media；管理员 303→200 /library/media | n/a | n/a | n/a | n/a | n/a | n/a | n/a | **—** | — |
| `/subject/material/detail/<int:sid>` | 学生 200 /subject/material/detail/46；教师 303→200 /subject/details；家长 303→200 /subject/details；教务 303→200 /subject/details；管理员 303→200 /subject/details | pass | fail | pass | pass | pass | ok | n/a | **P2** | 学生家长 |
| `/my/notice/<int:notice_id>` | 学生 200 /my/notice/8；教师 200 /my/notice/8；家长 200 /my/notice/8；教务 200 /my/notice/8；管理员 200 /my/notice/8 | pass | n/a | pass | pass | pass | ok | n/a | **—** | — |
| `/my/notice_banner` | 学生 200 /my/notice_banner；教师 200 /my/notice_banner；家长 200 /my/notice_banner；教务 200 /my/notice_banner；管理员 200 /my/notice_banner | pass | n/a | n/a | pass | n/a | n/a | n/a | **—** | — |
| `/my/calendar/new` | 教师 200 /my/calendar/new；教务 200 /my/calendar/new；管理员 200 /my/calendar/new；学生 303→200 /my/calendar；家长 303→200 /my/calendar | pass | n/a | pass | pass | pass | ok | pass(静态) | **—** | — |
| `/subject/enroll` | 学生 200 /subject/enroll；教师 303→200 /my/home；家长 303→200 /my/home；教务 303→200 /my/home；管理员 303→200 /my/home | pass | n/a | n/a | pass | pass | ok | pass(静态) | **—** | — |
| `/registrar/curriculum` | 教务 200 /registrar/curriculum；管理员 200 /registrar/curriculum；学生 303→200 /my/home；教师 303→200 /my/home；家长 303→200 /my/home | pass | n/a | pass | pass | pass | ok | pass(静态) | **—** | — |
| `/my/evaluation/task/<int:task_id>` | 学生 303→200 /assess；教师 303→200 /assess；家长 303→200 /assess；教务 303→200 /assess；管理员 303→200 /assess | pass | n/a | n/a | n/a | n/a | n/a | n/a | **设计如此**（303 兼容层） | 教师 |
| `/my/reimburse/receipt/<int:bill_id>/<int:att_id>` | 学生 404 /my/reimburse/receipt/1/1；教师 404 /my/reimburse/receipt/1/1；家长 404 /my/reimburse/receipt/1/1；教务 404 /my/reimburse/receipt/1/1；管理员 404 /my/reimburse/receipt/1/1 | n/a | n/a | pass | n/a | n/a | n/a | n/a | **—** | — |
| `/my/courses/<int:subject_id>` | 学生 200 /my/courses/46；教师 200 /my/courses/46；教务 200 /my/courses/46；管理员 200 /my/courses/46；家长 200 /my/courses/46 | pass | fail | pass | pass | pass | ok | n/a | **P2** | 学生家长 |
| `/my/courses/lesson/<int:lesson_id>` | 教师 200 /my/courses/lesson/1；教务 200 /my/courses/lesson/1；管理员 200 /my/courses/lesson/1；学生 303→200 /my/courses；家长 303→200 /my/courses | pass | n/a | pass | pass | pass | ok | pass(静态) | **P2** | 学生家长 |
| `/my/courses/<int:subject_id>/rep` | 学生 303→200 /my/courses；教师 303→200 /my/courses；家长 303→200 /my/courses；教务 303→200 /my/courses；管理员 303→200 /my/courses | n/a | n/a | n/a | n/a | n/a | n/a | n/a | **—** | — |
| `/my/messages/<int:uid>` | 教师 200 /my/messages/2；学生 200 /my/messages/2；家长 200 /my/messages/2；教务 200 /my/messages/2；管理员 303→200 /my/messages | pass | n/a | pass | pass | pass | ok | pass(静态) | **—** | — |
| `/my/messages/poll` | 学生 200 /my/messages/poll；教师 200 /my/messages/poll；家长 200 /my/messages/poll；教务 200 /my/messages/poll；管理员 200 /my/messages/poll | pass | n/a | n/a | pass | n/a | n/a | n/a | **—** | — |
| `/grading/history` | 教师 200 /grading/history；教务 200 /grading/history；管理员 200 /grading/history；学生 303→200 /my/home；家长 303→200 /my/home | pass | n/a | pass | fail | pass | fail | n/a | **P2** | 教务 |
| `/my/documents` | 学生 200 /my/documents；教师 303→200 /my/home；家长 303→200 /my/home；教务 303→200 /my/home；管理员 303→200 /my/home | pass | n/a | pass | pass | pass | ok | n/a | **—** | — |
| `/my/documents/enrollment-certificate` | 学生 200 /my/documents/enrollment-certificate；教师 303→200 /my/home；家长 303→200 /my/home；教务 303→200 /my/home；管理员 303→200 /my/home | pass | n/a | pass | n/a | n/a | n/a | n/a | **—** | — |
| `/my/documents/transcript` | 学生 200 /my/documents/transcript；教师 303→200 /my/home；家长 303→200 /my/home；教务 303→200 /my/home；管理员 303→200 /my/home | pass | n/a | pass | n/a | n/a | n/a | n/a | **—** | — |
| `/my/study/<int:subject_id>` | 学生 200 /my/study/46；教师 200 /my/study/46；教务 200 /my/study/46；管理员 200 /my/study/46；家长 200 /my/study/46 | pass | pass | pass | pass | pass | ok | n/a | **—** | — |
| `/my/points/me` | 学生 200 /my/points/me；教师 303→200 /my/home；家长 303→200 /my/home；教务 303→200 /my/home；管理员 303→200 /my/home | pass | n/a | pass | pass | fail | ok | n/a | **P3** | 学生家长 |
| `/quiz/<int:qid>/take` | 学生 303→200 /quiz；教师 200 /quiz/1/take；家长 303→200 /quiz；教务 200 /quiz/1/take；管理员 200 /quiz/1/take | fail | n/a | pass | pass | pass | ok | pass(静态) | **P1** | 学生家长 |
| `/quiz/<int:qid>/result/<int:aid>` | 学生 200 /quiz/1/result/1；教师 303→200 /quiz；家长 303→200 /quiz；教务 303→200 /quiz；管理员 303→200 /quiz | pass | n/a | pass | pass | pass | ok | n/a | **—** | — |
| `/timetable/session/<int:sid>/impact` | 教师 200 /timetable/session/293/impact；教务 200 /timetable/session/293/impact；管理员 200 /timetable/session/293/impact；学生 303→200 /my/home；家长 303→200 /my/home | pass | n/a | fail | pass | fail | ok | pass(静态) | **P1** | 教师 |
| `/my/rollcall/<int:session_id>` | 范围外（未计入） | — | — | — | — | — | — | — | 范围外 | 范围外（退役模块） |
| `/my/child/<int:child_id>` | 家长 200 /my/child/5；学生 303→200 /my/child；教师 303→200 /my/child；教务 303→200 /my/child；管理员 303→200 /my/child | pass | pass | pass | pass | pass | ok | n/a | **P3** | 学生家长 |
| `/my/child/<int:child_id>/leave` | 家长 200 /my/child/5/leave；学生 303→200 /my/child；教师 303→200 /my/child；教务 303→200 /my/child；管理员 303→200 /my/child | pass | n/a | pass | pass | pass | ok | pass(静态) | **—** | — |
| `/my/evaluation/new` | 教师 303→200 /assess；教务 303→200 /assess；管理员 303→200 /assess；学生 303→200 /assess；家长 303→200 /assess | pass | n/a | n/a | n/a | n/a | n/a | n/a | **设计如此**（303 兼容层） | 教师 |
| `/registrar/subject/approvals/<int:rid>` | 未探（防副作用） | — | — | — | — | — | — | — | 未探 | 教务 |
| `/attendance/selfcheck/<token>` | 未探（防副作用） | — | — | — | — | — | — | — | 未探 | 学生家长 |
| `/leave/approvals/<int:leave_id>` | 未探（防副作用） | — | — | — | — | — | — | — | 未探 | 教师 |
| `/attendance/import` | 未探（防副作用） | — | — | — | — | — | — | — | 未探 | 教师 |
| `/my/lang/<string:code>` | 未探（防副作用） | — | — | — | — | — | — | — | 未探 | 学生家长 |
| `/timetable/batch/<int:bid>/deactivate` | 未探（防副作用） | — | — | — | — | — | — | — | 未探 | 教务 |
| `/my/reimburse/apply` | 学生 200 /my/reimburse/apply；教师 200 /my/reimburse/apply | pass | n/a | pass | pass | pass | ok | pass(静态) | **—** | 学生家长 |
| `/my/child/<int:child_id>/leave/saved` | 家长 200 /my/child/5/leave/saved | pass | n/a | pass | pass | pass | ok | fail(静态) | **P3** | 学生家长 |
| `/leave/transfer` | 教师 303 /leave/approvals | pass | n/a | n/a | n/a | n/a | n/a | pass(静态) | **—** | 教师 |
| `/leave/<int:leave_id>/return_confirm` | 学生 303 /my/home | pass | n/a | n/a | n/a | n/a | n/a | pass(静态) | **—** | 学生家长 |
| `/my/study/session/<int:session_id>/join` | 学生 200 /my/study/session/293/join | pass | n/a | pass | pass | pass | ok | n/a | **—** | 学生家长 |
| `/my/marks/<int:exam_id>` | 范围外（未计入） | — | — | — | — | — | — | — | 范围外 | 范围外（退役模块） |

## 3. 死角组 45 条：逐条账与修法

#### `/eval/review/<int:task_id>` — 设计如此（303 兼容层）｜教师

- 判据（队长 2026-09-26 核实，本轮复核原文）：设计稿 docs/plans/evaluation-rebuild-design.md §7.4-2：旧 7 条路由改 303，不删模型、不删表、不改 ACL（旧两套本期只冻结：只读化石，先建后删是校长钉死的顺序）。实现上用「继承 + 覆写」（eval_compat.py 文件头；edu_assess 侧是同构的 EduAdminEvalCompat）——Odoo 的 leaf 覆盖只实例化最底层子类，父类同路由不再单独注册，因此归属**不随模块加载顺序漂移**（eval_compat.py 明写「不用同名路由各写一遍」的原因，正是 scripts/check_view_xpath.py 规则 5 拦的那件事）。⇒ 5 个身份拿 303 是**预期行为**；旧实现仍在库中但永不执行，属队列 **待办 ④ 评估收口第二步**（不计入本账）。
- 本页对应实现：edu_assess/controllers/portal.py:926 class EduAdminEvalCompat(EduAdminEvalPortal) 覆写 eval_review_form → 303 /assess/my
- 原判（已撤回）：本轮曾按「同路径重复注册、真页被遮蔽」判 P1 —— **真机读数（5 身份 303）无误，定性错了**：机制上是**父子覆写**（不是加载顺序漂移），意图上是设计稿钉死的兼容期行为。
- **关联：队列待办 ④ 评估收口第二步** —— 旧实现（`edu_portal/controllers/evaluation.py`、`edu_eval/controllers/eval_portal.py`）仍在库中但永不执行，属**死代码**；按设计稿「不删模型、不删表、不改 ACL；先建后删」，应在收口第二步一并处理。**不计入本账。**
- 真机读数：
  - `/eval/review/1`（学生）：HTTP 303→200 /assess/my
  - `/eval/review/1`（教师）：HTTP 303→303→200 /my/home
  - `/eval/review/1`（家长）：HTTP 303→303→200 /my/home
  - `/eval/review/1`（教务）：HTTP 303→303→200 /my/home
  - `/eval/review/1`（管理员）：HTTP 303→303→200 /my/home

#### `/eval/fill/<int:task_id>` — 设计如此（303 兼容层）｜学生家长

- 判据（队长 2026-09-26 核实，本轮复核原文）：设计稿 docs/plans/evaluation-rebuild-design.md §7.4-2：旧 7 条路由改 303，不删模型、不删表、不改 ACL（旧两套本期只冻结：只读化石，先建后删是校长钉死的顺序）。实现上用「继承 + 覆写」（eval_compat.py 文件头；edu_assess 侧是同构的 EduAdminEvalCompat）——Odoo 的 leaf 覆盖只实例化最底层子类，父类同路由不再单独注册，因此归属**不随模块加载顺序漂移**（eval_compat.py 明写「不用同名路由各写一遍」的原因，正是 scripts/check_view_xpath.py 规则 5 拦的那件事）。⇒ 5 个身份拿 303 是**预期行为**；旧实现仍在库中但永不执行，属队列 **待办 ④ 评估收口第二步**（不计入本账）。
- 本页对应实现：同族：portal.py:953 eval_fill → 303 /assess；A 套由 edu_portal/controllers/eval_compat.py 的 EduEvalCompat 接管
- 原判（已撤回）：本轮曾按「同路径重复注册、真页被遮蔽」判 P1 —— **真机读数（5 身份 303）无误，定性错了**：机制上是**父子覆写**（不是加载顺序漂移），意图上是设计稿钉死的兼容期行为。
- **关联：队列待办 ④ 评估收口第二步** —— 旧实现（`edu_portal/controllers/evaluation.py`、`edu_eval/controllers/eval_portal.py`）仍在库中但永不执行，属**死代码**；按设计稿「不删模型、不删表、不改 ACL；先建后删」，应在收口第二步一并处理。**不计入本账。**
- 真机读数：
  - `/eval/fill/1`（学生）：HTTP 303→200 /assess
  - `/eval/fill/1`（教师）：HTTP 303→200 /assess
  - `/eval/fill/1`（家长）：HTTP 303→200 /assess
  - `/eval/fill/1`（教务）：HTTP 303→200 /assess
  - `/eval/fill/1`（管理员）：HTTP 303→200 /assess

#### `/journals/review/<int:entry_id>` — P3｜教师

- **G 轴｜P3**
  - 现状证据：批阅动作只有「批阅通过并置为『已批阅』」一个出口，页面上不存在「退回/要求重写」（measure：form 内 1 input + 1 button）。
  - 建议修法：若业务允许退回，补「退回并说明」；若不允许，页面上写明「周记仅可批阅通过」。

- 备注：fac/bo/admin 200，stu/par 303→/my/home。有「返回队列」。
- 真机读数：
  - `/journals/review/2`（教师）：HTTP 200 /journals/review/2；375 溢出 0px
  - `/journals/review/2`（教务）：HTTP 200 /journals/review/2；375 溢出 0px
  - `/journals/review/2`（管理员）：HTTP 200 /journals/review/2；375 溢出 0px
  - `/journals/review/2`（学生）：HTTP 303→200 /my/home；375 溢出 无视图口读数
  - `/journals/review/2`（家长）：HTTP 303→200 /my/home；375 溢出 无视图口读数

#### `/library/media/info/<int:mid>` — 无级别｜—（需数据：未造样本）

- 备注：需数据（未造样本）：op.media 全表 0 行 ⇒ 5 角色一律 303→/library/media。控制器 batch2.py:1396「不存在即 303 回列表」，无 500/404。真机不可判 B/D/E/F/G。
- 真机读数：
  - `/library/media/info/1`（学生）：HTTP 303→200 /library/media；375 溢出 无视图口读数
  - `/library/media/info/1`（教师）：HTTP 303→200 /library/media；375 溢出 无视图口读数
  - `/library/media/info/1`（家长）：HTTP 303→200 /library/media；375 溢出 无视图口读数
  - `/library/media/info/1`（教务）：HTTP 303→200 /library/media；375 溢出 无视图口读数
  - `/library/media/info/1`（管理员）：HTTP 303→200 /library/media；375 溢出 无视图口读数

#### `/subject/material/detail/<int:sid>` — P2｜学生家长

- **B 轴｜P2**
  - 现状证据：空态文案「该科目暂无学习材料。」只陈述事实、无下一步入口；页面唯一出口是「返回科目列表」。对照全站范本 /library/media 的空态写法。
  - 建议修法：空态补一行指引 + 一个入口（如「去图书馆找相关馆藏」→ /library/media，或「联系任课教师」）。

- 备注：stu 200；fac/par/bo/admin 303→/subject/details（非授权不 200）。
- 真机读数：
  - `/subject/material/detail/46`（学生）：HTTP 200 /subject/material/detail/46；375 溢出 0px
  - `/subject/material/detail/46`（教师）：HTTP 303→200 /subject/details；375 溢出 无视图口读数
  - `/subject/material/detail/46`（家长）：HTTP 303→200 /subject/details；375 溢出 无视图口读数
  - `/subject/material/detail/46`（教务）：HTTP 303→200 /subject/details；375 溢出 无视图口读数
  - `/subject/material/detail/46`（管理员）：HTTP 303→200 /subject/details；375 溢出 无视图口读数

#### `/my/notice_banner` — 无级别｜—（需数据：未造样本）

- 备注：JSON 数据接口（七轴仅 A/D 适用）：5 角色 200 {"banners": []}；无数据（未造样本）：8 条公告 banner_enabled 全 false。
- 真机读数：
  - `/my/notice_banner`（学生）：HTTP 200 /my/notice_banner；375 溢出 0px
  - `/my/notice_banner`（教师）：HTTP 200 /my/notice_banner；375 溢出 0px
  - `/my/notice_banner`（家长）：HTTP 200 /my/notice_banner；375 溢出 0px
  - `/my/notice_banner`（教务）：HTTP 200 /my/notice_banner；375 溢出 0px
  - `/my/notice_banner`（管理员）：HTTP 200 /my/notice_banner；375 溢出 0px

#### `/my/evaluation/task/<int:task_id>` — 设计如此（303 兼容层）｜教师

- 判据（队长 2026-09-26 核实，本轮复核原文）：设计稿 docs/plans/evaluation-rebuild-design.md §7.4-2：旧 7 条路由改 303，不删模型、不删表、不改 ACL（旧两套本期只冻结：只读化石，先建后删是校长钉死的顺序）。实现上用「继承 + 覆写」（eval_compat.py 文件头；edu_assess 侧是同构的 EduAdminEvalCompat）——Odoo 的 leaf 覆盖只实例化最底层子类，父类同路由不再单独注册，因此归属**不随模块加载顺序漂移**（eval_compat.py 明写「不用同名路由各写一遍」的原因，正是 scripts/check_view_xpath.py 规则 5 拦的那件事）。⇒ 5 个身份拿 303 是**预期行为**；旧实现仍在库中但永不执行，属队列 **待办 ④ 评估收口第二步**（不计入本账）。
- 本页对应实现：edu_portal/controllers/eval_compat.py（class EduEvalCompat(EduEvalPortal) 覆写 eval_task）→ 303 /assess
- 原判（已撤回）：本轮曾按「同路径重复注册、真页被遮蔽」判 P1 —— **真机读数（5 身份 303）无误，定性错了**：机制上是**父子覆写**（不是加载顺序漂移），意图上是设计稿钉死的兼容期行为。
- **关联：队列待办 ④ 评估收口第二步** —— 旧实现（`edu_portal/controllers/evaluation.py`、`edu_eval/controllers/eval_portal.py`）仍在库中但永不执行，属**死代码**；按设计稿「不删模型、不删表、不改 ACL；先建后删」，应在收口第二步一并处理。**不计入本账。**
- 真机读数：
  - `/my/evaluation/task/1`（学生）：HTTP 303→200 /assess
  - `/my/evaluation/task/1`（教师）：HTTP 303→200 /assess
  - `/my/evaluation/task/1`（家长）：HTTP 303→200 /assess
  - `/my/evaluation/task/1`（教务）：HTTP 303→200 /assess
  - `/my/evaluation/task/1`（管理员）：HTTP 303→200 /assess

#### `/my/reimburse/receipt/<int:bill_id>/<int:att_id>` — 无级别｜—（需数据：未造样本）

- 备注：需数据（未造样本）：edu.fee.bill 2 行但挂在其上的 ir.attachment 0 行 ⇒ 5 角色一律 404。fees.py:193 注释明写「越权统一 404，不泄露存在性」⇒ 404 属设计行为；真机无法判 B/D/E/F/G。
- 真机读数：
  - `/my/reimburse/receipt/1/1`（学生）：HTTP 404 /my/reimburse/receipt/1/1；375 溢出 无视图口读数
  - `/my/reimburse/receipt/1/1`（教师）：HTTP 404 /my/reimburse/receipt/1/1；375 溢出 无视图口读数
  - `/my/reimburse/receipt/1/1`（家长）：HTTP 404 /my/reimburse/receipt/1/1；375 溢出 无视图口读数
  - `/my/reimburse/receipt/1/1`（教务）：HTTP 404 /my/reimburse/receipt/1/1；375 溢出 无视图口读数
  - `/my/reimburse/receipt/1/1`（管理员）：HTTP 404 /my/reimburse/receipt/1/1；375 溢出 无视图口读数

#### `/my/courses/<int:subject_id>` — P2｜学生家长

- **B 轴｜P2**
  - 现状证据：空态只有一句「本课程暂无已发布课次。」（alert-info），无下一步入口；唯一出口是「返回课程列表」。
  - 建议修法：空态补指引 + 入口（如「去 /my/study/<subject> 看课程资料」或「联系任课教师」）。

- 备注：5 角色均 200（fac/bo/admin 走 _subjects_for「内部用户=全部科目」；par 走孩子档案）。标题「选修课程 / 完成 0/0」对非学生身份语义偏弱。
- 真机读数：
  - `/my/courses/46`（学生）：HTTP 200 /my/courses/46；375 溢出 0px
  - `/my/courses/46`（教师）：HTTP 200 /my/courses/46；375 溢出 0px
  - `/my/courses/46`（教务）：HTTP 200 /my/courses/46；375 溢出 0px
  - `/my/courses/46`（管理员）：HTTP 200 /my/courses/46；375 溢出 0px
  - `/my/courses/46`（家长）：HTTP 200 /my/courses/46；375 溢出 0px

#### `/my/courses/lesson/<int:lesson_id>` — P2｜学生家长

- **C 轴｜P2**
  - 现状证据：fac/bo/admin 200 且渲染学生动作「标记完成」按钮；stu 反而 303→/my/courses（课节所属科目 35 不在其档案 subject_ids=[46]）。教师/教务可替学生标完成。
  - 建议修法：「标记完成」加角色条件（仅学生本人或家长）；教师/教务看只读版。

- 备注：需数据：学生侧不可达（未给学生挂科目 35）。有「返回课次列表」→/my/courses/35。
- 真机读数：
  - `/my/courses/lesson/1`（教师）：HTTP 200 /my/courses/lesson/1；375 溢出 0px
  - `/my/courses/lesson/1`（教务）：HTTP 200 /my/courses/lesson/1；375 溢出 0px
  - `/my/courses/lesson/1`（管理员）：HTTP 200 /my/courses/lesson/1；375 溢出 0px
  - `/my/courses/lesson/1`（学生）：HTTP 303→200 /my/courses；375 溢出 无视图口读数
  - `/my/courses/lesson/1`（家长）：HTTP 303→200 /my/courses；375 溢出 无视图口读数

#### `/my/courses/<int:subject_id>/rep` — 无级别｜—（需数据：未造样本）

- 备注：需数据（未造样本）：edu.course.rep 无在任课代表 ⇒ 5 角色一律 303→/my/courses；本地整条「课代表」链路不可达。
- 真机读数：
  - `/my/courses/46/rep`（学生）：HTTP 303→200 /my/courses；375 溢出 无视图口读数
  - `/my/courses/46/rep`（教师）：HTTP 303→200 /my/courses；375 溢出 无视图口读数
  - `/my/courses/46/rep`（家长）：HTTP 303→200 /my/courses；375 溢出 无视图口读数
  - `/my/courses/46/rep`（教务）：HTTP 303→200 /my/courses；375 溢出 无视图口读数
  - `/my/courses/46/rep`（管理员）：HTTP 303→200 /my/courses；375 溢出 无视图口读数

#### `/grading/history` — P2｜教务

- **F 轴｜P1**
  - 现状证据：375 视口横向溢出 116px（fac/bo/admin 三次读数一致：documentElement.scrollWidth - innerWidth = 116），「新分数/操作人」列需横滑。
  - 建议修法：表格容器加 table-responsive，或小屏折叠次要列。

- **D 轴｜P2**
  - 现状证据：「来源」列 35 行显示英文值 backend（同列其他值为中文「页面录入」）⇒ 同列中英混用；说明文字出现「对齐 Moodle grade_grades_history」，把外部系统名与下划线字段名暴露给教师。
  - 建议修法：source 值补中文 label（backend→后台录入 / excel→表格导入…）；说明改写为不含 Moodle 与字段名的中文。

- 备注：fac/bo/admin 200，stu/par 303→/my/home。有「共 188 条变更记录」与筛选表单。
- 真机读数：
  - `/grading/history`（教师）：HTTP 200 /grading/history；375 溢出 116px
  - `/grading/history`（教务）：HTTP 200 /grading/history；375 溢出 116px
  - `/grading/history`（管理员）：HTTP 200 /grading/history；375 溢出 116px
  - `/grading/history`（学生）：HTTP 303→200 /my/home；375 溢出 无视图口读数
  - `/grading/history`（家长）：HTTP 303→200 /my/home；375 溢出 无视图口读数

#### `/my/points/me` — P3｜学生家长

- **E 轴｜P3**
  - 现状证据：内容区无任何出口链接（无「返回门户/去打卡」入口），只能靠顶栏导航。
  - 建议修法：补一条「去灵命打卡 / 返回门户首页」。

- 备注：stu 200；其余 4 角色 303→/my/home。有完整明细表（时间/分值/原因/操作人/备注）。
- 真机读数：
  - `/my/points/me`（学生）：HTTP 200 /my/points/me；375 溢出 0px
  - `/my/points/me`（教师）：HTTP 303→200 /my/home；375 溢出 无视图口读数
  - `/my/points/me`（家长）：HTTP 303→200 /my/home；375 溢出 无视图口读数
  - `/my/points/me`（教务）：HTTP 303→200 /my/home；375 溢出 无视图口读数
  - `/my/points/me`（管理员）：HTTP 303→200 /my/home；375 溢出 无视图口读数

#### `/quiz/<int:qid>/take` — P1｜学生家长

- **A 轴｜P1**
  - 现状证据：唯一的已发布测验（edu.quiz#1，course=13 基督教研究硕士科）对 stu 303→/quiz：学生档案 course=18 预备科，与测验课程不符 ⇒ 学生永远进不了作答页。fac/bo/admin 反而 200 并渲染作答界面（_visible_course_ids 对内部用户返回 None=不受限）。
  - 建议修法：（a）数据侧：测验挂到学生实际在读课程/班级；（b）代码侧：作答页对非学生身份 303，别让教师/教务看到作答界面。

- 备注：两件事叠加：学生侧不通（数据+口径），教师侧过宽（口径）。
- 真机读数：
  - `/quiz/1/take`（学生）：HTTP 303→200 /quiz；375 溢出 无视图口读数
  - `/quiz/1/take`（教师）：HTTP 200 /quiz/1/take；375 溢出 无视图口读数
  - `/quiz/1/take`（家长）：HTTP 303→200 /quiz；375 溢出 无视图口读数
  - `/quiz/1/take`（教务）：HTTP 200 /quiz/1/take；375 溢出 无视图口读数
  - `/quiz/1/take`（管理员）：HTTP 200 /quiz/1/take；375 溢出 无视图口读数

#### `/timetable/session/<int:sid>/impact` — P1｜教师

- **C/E 轴｜P1**
  - 现状证据：fac 页面里有 form(action=/timetable/session/293/notify)，但提交按钮被 can_notify=privileged_staff() 隐藏（edu_schedule/views/templates.xml:884-895 的 t-if="can_notify"），而正文仍写「确认无误后点页面底部的『通知相关师生』」⇒ 文案指向不存在的按钮；内容区无返回/下一步链接。bo/admin 正常（按钮在）。
  - 建议修法：教师版二选一：① can_notify 放宽到任课教师并写明权限；② 指导语改成「由教务处通知」并补「返回校历/课节」出口。

- 备注：fac/bo/admin 200；stu/par 303→/my/home。信息面（受影响人数/受牵连课节/新旧值对比）完整。
- 真机读数：
  - `/timetable/session/293/impact`（教师）：HTTP 200 /timetable/session/293/impact；375 溢出 0px
  - `/timetable/session/293/impact`（教务）：HTTP 200 /timetable/session/293/impact；375 溢出 0px
  - `/timetable/session/293/impact`（管理员）：HTTP 200 /timetable/session/293/impact；375 溢出 0px
  - `/timetable/session/293/impact`（学生）：HTTP 303→200 /my/home；375 溢出 无视图口读数
  - `/timetable/session/293/impact`（家长）：HTTP 303→200 /my/home；375 溢出 无视图口读数

#### `/my/rollcall/<int:session_id>` — 范围外（不计入统计）

- 处置依据：docs/code-map.md「edu_telegram —— v2.2 四角色教务前端（从未部署；2026-09-17 用户裁定退役）」；scripts/deploy_myedu.sh:35 的 MODULES 不含 edu_telegram ⇒ 生产无此路由
- 说明：edu_telegram v2.2 从未部署、2026-09-17 用户裁定退役 ⇒ 生产不存在该路由；本轮读数取自本机装着的退役模块，因此**不代表生产行为**。
- 保留的价值：本条不是生产缺陷，但它证明「就地自建身份口径」会立刻出错（该模块正是反面教材）。原始真机读数仍保留在 `tests/ui/readings/dead-45.json` 的 `http` 字段里供追溯。

#### `/my/child/<int:child_id>` — P3｜学生家长

- **C/E 轴｜P3**
  - 现状证据：非家长（stu/fac/bo/admin）访问 /my/child/5 → 303→/my/child 落到「我的孩子 · 选择一个孩子查看其仪表盘」空页（200），文案对教师/教务语义错，内容区无出口链接。
  - 建议修法：非家长分流回各自首页（/my/home），或空页补「返回门户首页」并改中性文案。

- 备注：家长侧内容完整：出勤率 / 已出成绩考试 / 学习生活摘要（作业·打卡·周记·请假真实计数）/ 考试成绩表 / 7 个快捷入口 / 「为孩子请假」/「返回我的孩子」。队长补录第 43 条。
- 真机读数：
  - `/my/child/5`（家长）：HTTP 200 /my/child/5；375 溢出 0px
  - `/my/child/5`（学生）：HTTP 303→200 /my/child；375 溢出 无视图口读数
  - `/my/child/5`（教师）：HTTP 303→200 /my/child；375 溢出 无视图口读数
  - `/my/child/5`（教务）：HTTP 303→200 /my/child；375 溢出 无视图口读数
  - `/my/child/5`（管理员）：HTTP 303→200 /my/child；375 溢出 无视图口读数

#### `/my/evaluation/new` — 设计如此（303 兼容层）｜教师

- 判据（队长 2026-09-26 核实，本轮复核原文）：设计稿 docs/plans/evaluation-rebuild-design.md §7.4-2：旧 7 条路由改 303，不删模型、不删表、不改 ACL（旧两套本期只冻结：只读化石，先建后删是校长钉死的顺序）。实现上用「继承 + 覆写」（eval_compat.py 文件头；edu_assess 侧是同构的 EduAdminEvalCompat）——Odoo 的 leaf 覆盖只实例化最底层子类，父类同路由不再单独注册，因此归属**不随模块加载顺序漂移**（eval_compat.py 明写「不用同名路由各写一遍」的原因，正是 scripts/check_view_xpath.py 规则 5 拦的那件事）。⇒ 5 个身份拿 303 是**预期行为**；旧实现仍在库中但永不执行，属队列 **待办 ④ 评估收口第二步**（不计入本账）。
- 本页对应实现：edu_portal/controllers/eval_compat.py 覆写 eval_new → 303 /assess
- 原判（已撤回）：本轮曾按「同路径重复注册、真页被遮蔽」判 P1 —— **真机读数（5 身份 303）无误，定性错了**：机制上是**父子覆写**（不是加载顺序漂移），意图上是设计稿钉死的兼容期行为。
- **关联：队列待办 ④ 评估收口第二步** —— 旧实现（`edu_portal/controllers/evaluation.py`、`edu_eval/controllers/eval_portal.py`）仍在库中但永不执行，属**死代码**；按设计稿「不删模型、不删表、不改 ACL；先建后删」，应在收口第二步一并处理。**不计入本账。**
- 真机读数：
  - `/my/evaluation/new`（教师）：HTTP 303→200 /assess
  - `/my/evaluation/new`（教务）：HTTP 303→200 /assess
  - `/my/evaluation/new`（管理员）：HTTP 303→200 /assess
  - `/my/evaluation/new`（学生）：HTTP 303→200 /assess
  - `/my/evaluation/new`（家长）：HTTP 303→200 /assess

#### `/my/reimburse/apply` — 无级别｜学生家长

- 补测护栏（队长授权）：fees.py:231-250 GET 分支只 request.render（无 search/create/write）

- 备注：补测（队长授权）：GET 分支只 request.render（fees.py:231-250）；stu 200 / fac 200；表单含分类/金额/事由/收据附件 + 「提交报销申请」+「返回账单」出口。探测前后业务表行数 0 变化。
- 真机读数：
  - `/my/reimburse/apply`（学生）：HTTP 200 /my/reimburse/apply；375 溢出 无视图口读数
  - `/my/reimburse/apply`（教师）：HTTP 200 /my/reimburse/apply；375 溢出 无视图口读数

#### `/my/child/<int:child_id>/leave/saved` — P3｜学生家长

- **G 轴｜P3**
  - 现状证据：本条与 /my/child/<id>/leave 共用同一 handler（roles.py:1033 的 route 列表）。但成功提示由模板 roles.xml:505 的 t-if="saved" 控制，而 saved 只在查询串（?saved=1）里进 kw —— 走 /leave/saved 这条**路径**访问时 kw 里没有 saved ⇒ 页面渲染的是普通表单，**不显示「请假申请已提交，等待教师审批。」**。且全仓 grep 显示该路径**没有任何引用**（控制器提交后跳的是 /my/child/<id>/leave?saved=1，roles.py:1085）⇒ 孤儿别名，语义误导。
  - 建议修法：删掉 route 里的 /leave/saved 别名（保留 ?saved=1），或让 handler 同时认路径段（saved=True）。

- 补测护栏（队长授权）：roles.py:1033-1046 与 /leave 同一 handler，仅 render + saved 标志

- 备注：补测（队长授权）：同一 handler，仅 render；par 200。前后行数 0 变化。
- 真机读数：
  - `/my/child/5/leave/saved`（家长）：HTTP 200 /my/child/5/leave/saved；375 溢出 无视图口读数

#### `/leave/transfer` — 无级别｜教师

- 补测护栏（队长授权）：roles.py:3221-3236：method != POST ⇒ 立即 303 回跳，写全在 POST

- 备注：补测（队长授权）：roles.py:3221-3236 —— GET（method != POST）立即 303→/leave/approvals，**动作全在 POST 与 action_transfer 内**；实测 303 + Location=/leave/approvals，edu_leave/edu_leave_transfer/edu_audit_log/edu_message 行数均无变化。
- 真机读数：
  - `/leave/transfer`（教师）：HTTP 303 /leave/approvals；375 溢出 无视图口读数

#### `/leave/<int:leave_id>/return_confirm` — 无级别｜学生家长

- 补测护栏（队长授权）：roles.py:3307-3319：method != POST ⇒ 立即 303 /my/home，写全在 POST

- 备注：补测（队长授权）：roles.py:3307-3319 —— GET 立即 303→/my/home；销假两跳的写全在 POST 分支。实测申请人本人（stu）303 + Location=/my/home，edu_leave/edu_audit_log/edu_message 行数无变化。
- 真机读数：
  - `/leave/230/return_confirm`（学生）：HTTP 303 /my/home；375 溢出 无视图口读数

#### `/my/study/session/<int:session_id>/join` — 无级别｜学生家长

- 补测护栏（队长授权）：study.py:351-372 + session_ext.py:232-248 join_state() 纯计算

- 备注：补测（队长授权）：study.py:351-372 + session_ext.py:232-248 join_state() 纯计算（无写）；实测 stu 200 渲染「待教师发布会议链接」等待页 + 「返回科目」出口（session 293 未设 meeting_url，故未发生外跳）。行数 0 变化。
- 真机读数：
  - `/my/study/session/293/join`（学生）：HTTP 200 /my/study/session/293/join；375 溢出 无视图口读数

#### `/my/marks/<int:exam_id>` — 范围外（不计入统计）

- 处置依据：docs/code-map.md「edu_telegram —— v2.2 四角色教务前端（从未部署；2026-09-17 用户裁定退役）」；scripts/deploy_myedu.sh:35 的 MODULES 不含 edu_telegram ⇒ 生产无此路由
- 说明：edu_telegram v2.2 从未部署、2026-09-17 用户裁定退役 ⇒ 生产不存在该路由；本轮读数取自本机装着的退役模块，因此**不代表生产行为**。
- 保留的价值：本条不是生产缺陷，但它证明「就地自建身份口径」会立刻出错（该模块正是反面教材）。原始真机读数仍保留在 `tests/ui/readings/dead-45.json` 的 `http` 字段里供追溯。

## 4. 未探清单（6 条，防副作用）

> 原 12 条未探中，**5 条已在队长授权下补测**（`/my/reimburse/apply`、`/my/child/<id>/leave/saved`、
> `/leave/transfer`、`/leave/<id>/return_confirm`、`/my/study/session/<id>/join`，
> 逐条零写判定依据与前后行数见 §3 对应条目与 §9.4）；**1 条移出范围**（`/my/marks/<id>`，退役模块）。余下 6 条：

| 路由 | 未探理由 | 静态复核结论（可据此授权补测） |
|---|---|---|
| `/registrar/subject/approvals/<int:rid>` | 路径含 approve（approvals）—— 红线禁用词命中，未发请求 | 控制器（enroll.py:441）判据：current_faculty() 或 privileged_staff()，否则 303→/my/home；随后按 rid 取 op.subject.registration，不存在则 303 回审批列表。GET 分支只读（本函数无 create/write/unlink —— AST 级扫描 + 人工复核）。 |
| `/attendance/selfcheck/<token>` | 即使路径不含禁用词，也属「有副作用的路由」：GET 会把本人考勤行置为到堂（roles.py:749 起 line.write / Line.create）⇒ 违反「不写库」红线，未探 | 令牌校验 → 班级成员校验 → 当日点名表存在 → 写 line.present=True；6 种结果文案（ok/already/expired/bad_token/not_in_batch/no_sheet）。本地有 4 个 active 令牌（id 3/4/13/18，均已过期：expire_at 2026-08-29~09-17）。 |
| `/leave/approvals/<int:leave_id>` | 路径含 approve（approvals）—— 红线禁用词命中，未发请求 | roles.py:1375 leave_detail；判据 leave_portal_approver（教师档案 ∪ 教务处/系统组 ∪ 本级应批人是我）；列表页 /leave/approvals 的「详情」链接即指向它（本轮对照组实测列表页可 200）。GET 分支为纯读（无写调用）。 |
| `/attendance/import` | 路径含 import —— 红线禁用词命中，未发请求 | roles.py:2520（methods=['GET','POST']）：GET 渲染上传表单，POST 才解析 CSV/XLSX 做预览；GET 分支无写调用。 |
| `/my/lang/<string:code>` | 队长点名：切语言会写 res.users.lang（search.py:183 的 user.write），污染后续所有探测 ⇒ 未探 | auth='public'；仅接受 zh_CN/zh_TW/en_US，写当前用户 lang 后 303 回 referrer 或 /my/home。 |
| `/timetable/batch/<int:bid>/deactivate` | 队长点名：GET 一下就把批次停用 ⇒ 未探 | 控制器 docstring 自称「二次确认页（GET，只读）」，但函数名与队长结论都指向 deactivate 动作；两侧证据冲突 ⇒ 一律不探（宁可漏测）。 |

## 5. 对照组 20 条（已被 route_matrix 覆盖）

| 页面 | 探测身份（HTTP 结果） | A 可达 | B 空态 | C 报错态 | D 语言 | E 死胡同 | F 移动端 | G 闭环 | 级别 | 归属期 |
|---|---|---|---|---|---|---|---|---|---|---|
| `/my` | 学生 303→200 /my/home；教师 303→200 /my/home；家长 303→200 /my/home；教务 303→200 /my/home；管理员 303→200 /my/home | pass | n/a | n/a | pass | pass | ok | n/a | **—** | — |
| `/my/home` | 学生 200 /my/home；教师 200 /my/home；家长 200 /my/home；教务 200 /my/home；管理员 200 /my/home | pass | pass | pass | fail | pass | ok | n/a | **P2** | 学生家长 |
| `/student/profile` | 学生 200 /student/profile；教师 200 /student/profile；家长 200 /student/profile；教务 200 /student/profile；管理员 200 /student/profile | pass | pass | pass | fail | pass | ok | n/a | **P2** | 学生家长 |
| `/student/timetable` | 学生 200 /student/timetable；教师 200 /student/timetable；家长 200 /student/timetable；教务 200 /student/timetable；管理员 200 /student/timetable | pass | pass | n/a | pass | pass | ok | n/a | **—** | — |
| `/student/subjects` | 学生 200 /student/subjects；教师 303→200 /my/home；家长 303→200 /my/home；教务 303→200 /my/home；管理员 303→200 /my/home | pass | pass | pass | pass | pass | ok | n/a | **—** | — |
| `/my/time_off` | 学生 200 /my/time_off；教师 200 /my/time_off；家长 303→200 /my/child；教务 200 /my/time_off；管理员 200 /my/time_off | pass | pass | pass | pass | pass | ok | pass(静态) | **—** | — |
| `/leave/approvals` | 教师 200 /leave/approvals；教务 200 /leave/approvals；管理员 200 /leave/approvals；学生 303→200 /my/home；家长 303→200 /my/home | pass | n/a | pass | pass | pass | fail | pass(静态) | **P1** | 教师 |
| `/grade-book` | 学生 200 /grade-book；教师 200 /grade-book；家长 200 /grade-book；教务 200 /grade-book；管理员 200 /grade-book | pass | fail | pass | fail | pass | ok | n/a | **P2** | 学生家长 |
| `/grading/entry` | 教师 200 /grading/entry；教务 303→200 /my/home；管理员 303→200 /my/home；学生 303→200 /my/home；家长 303→200 /my/home | warn | n/a | pass | pass | pass | ok | pass(静态) | **P2** | 教务 |
| `/downloads` | 学生 200 /downloads；教师 200 /downloads；家长 200 /downloads；教务 200 /downloads；管理员 200 /downloads | pass | pass | pass | pass | pass | ok | pass(静态) | **P2** | 教务 |
| `/downloads/mine` | 学生 200 /downloads/mine；教师 200 /downloads/mine；家长 200 /downloads/mine；教务 200 /downloads/mine；管理员 200 /downloads/mine | pass | pass | pass | pass | pass | ok | n/a | **—** | — |
| `/quiz` | 学生 200 /quiz；教师 200 /quiz；家长 200 /quiz；教务 200 /quiz；管理员 200 /quiz | pass | pass | pass | fail | pass | ok | n/a | **P2** | 学生家长 |
| `/quiz/my` | 学生 200 /quiz/my；教师 303→200 /quiz；家长 303→200 /quiz；教务 303→200 /quiz；管理员 303→200 /quiz | pass | n/a | pass | pass | pass | ok | n/a | **—** | — |
| `/library/media` | 学生 200 /library/media；教师 200 /library/media；家长 200 /library/media；教务 200 /library/media；管理员 200 /library/media | pass | pass | pass | pass | pass | ok | n/a | **—** | — |
| `/my-library` | 学生 200 /my-library；教师 200 /my-library；家长 200 /my-library；教务 200 /my-library；管理员 200 /my-library | pass | pass | n/a | pass | pass | ok | n/a | **—** | — |
| `/my/courses` | 学生 200 /my/courses；教师 200 /my/courses；家长 200 /my/courses；教务 200 /my/courses；管理员 200 /my/courses | pass | pass | n/a | pass | pass | ok | n/a | **—** | — |
| `/my/notify` | 学生 200 /my/notify；教师 200 /my/notify；家长 200 /my/notify；教务 200 /my/notify；管理员 200 /my/notify | pass | n/a | n/a | pass | pass | ok | pass(静态) | **—** | — |
| `/my/help` | 学生 200 /my/help；教师 200 /my/help；家长 200 /my/help；教务 200 /my/help；管理员 200 /my/help | pass | n/a | n/a | pass | pass | ok | n/a | **—** | — |
| `/my/search` | 学生 200 /my/search；教师 200 /my/search；家长 200 /my/search；教务 200 /my/search；管理员 200 /my/search | pass | pass | n/a | pass | pass | ok | n/a | **—** | — |
| `/attendance/take` | 教师 200 /attendance/take；教务 303→200 /my/home；学生 303→200 /my/home；家长 303→200 /my/home；管理员 303→200 /my/home | pass | n/a | pass | pass | pass | ok | pass(静态) | **—** | — |


#### `/my/home` — P2｜学生家长

- **D 轴｜P2**
  - 现状证据：门户首页应用分类标题为「学业 Academics / 资源 Resources / 成长 Growth / 财务 Finance / 社群 Community」的中英并列写法（stu 页命中 5 个英文词、par 页同理），中文界面里出现成串英文分类名。
  - 建议修法：去掉英文副标题或改为中文；若坚持双语，应全站统一并登记进术语表。

- 备注：5 角色 200；空态/待办/今日课表/常用应用齐全，A/B/C/E 轴良好。
- 真机读数：
  - `/my/home`（学生）：HTTP 200 /my/home；375 溢出 0px
  - `/my/home`（教师）：HTTP 200 /my/home；375 溢出 0px
  - `/my/home`（家长）：HTTP 200 /my/home；375 溢出 0px
  - `/my/home`（教务）：HTTP 200 /my/home；375 溢出 0px
  - `/my/home`（管理员）：HTTP 200 /my/home；375 溢出 0px

#### `/student/profile` — P2｜学生家长

- **D 轴｜P2**
  - 现状证据：非学生身份拿到的提示文案固定为「您当前以教师身份登录…」——对家长/教务/管理员都这么说（par/bo/admin 三角色实测同一句），身份措辞与实际不符。
  - 建议修法：按实际角色生成文案（学生以外一律「该页面仅面向学生账号」+ 返回门户首页）。

- 备注：stu 200 内容完整；fac/par/bo/admin 200 但为拦截页（有「返回门户首页」出口，C 轴合格）。
- 真机读数：
  - `/student/profile`（学生）：HTTP 200 /student/profile；375 溢出 0px
  - `/student/profile`（教师）：HTTP 200 /student/profile；375 溢出 0px
  - `/student/profile`（家长）：HTTP 200 /student/profile；375 溢出 0px
  - `/student/profile`（教务）：HTTP 200 /student/profile；375 溢出 0px
  - `/student/profile`（管理员）：HTTP 200 /student/profile；375 溢出 0px

#### `/leave/approvals` — P1｜教师

- **F 轴｜P1**
  - 现状证据：375 视口横向溢出 126px（fac/bo/admin 三次一致），且首要动作「批准」按钮的 bounding box 右边缘超出视口（inX=False）⇒ 手机上必须横滑才能按到审批按钮。
  - 建议修法：表格改 table-responsive + 把「批准/驳回」做成小屏可见的操作列或卡片式列表。

- 备注：fac/bo/admin 200；stu/par 303→/my/home。桌面端功能完整（批量通过/驳回/代理审批设置/详情/转交）。
- 真机读数：
  - `/leave/approvals`（教师）：HTTP 200 /leave/approvals；375 溢出 126px
  - `/leave/approvals`（教务）：HTTP 200 /leave/approvals；375 溢出 126px
  - `/leave/approvals`（管理员）：HTTP 200 /leave/approvals；375 溢出 126px
  - `/leave/approvals`（学生）：HTTP 303→200 /my/home；375 溢出 无视图口读数
  - `/leave/approvals`（家长）：HTTP 303→200 /my/home；375 溢出 无视图口读数

#### `/grade-book` — P2｜学生家长

- **B/D 轴｜P2**
  - 现状证据：非学生身份 200：先渲染学生版空壳（总评百分比 — / 等级 — / 学科 0 / 课程 —），再叠一句「该页面仅面向学生账号。您当前以教师身份登录…」（对所有非学生角色都写「教师」）。既是「0 的海洋」也是身份措辞错。
  - 建议修法：进入拦截分支时不要渲染学生版空壳；文案按实际角色生成。

- 备注：stu 200 正常（总评 92.00% / 明细表 / 下载报告）。
- 真机读数：
  - `/grade-book`（学生）：HTTP 200 /grade-book；375 溢出 0px
  - `/grade-book`（教师）：HTTP 200 /grade-book；375 溢出 0px
  - `/grade-book`（家长）：HTTP 200 /grade-book；375 溢出 0px
  - `/grade-book`（教务）：HTTP 200 /grade-book；375 溢出 0px
  - `/grade-book`（管理员）：HTTP 200 /grade-book；375 溢出 0px

#### `/grading/entry` — P2｜教务

- **A 轴｜P2**
  - 现状证据：route_matrix 把 /grading/entry 登记为 fac+bo 双角色应 200（脚本 ROUTES 第 139 行），实测 bo(教务) 303→/my/home，只有 fac 200 ⇒ 矩阵里这条是**假绿**（probe 跟随跳转后 final=200 于 /my/home，verdict 只看 final==200）。
  - 建议修法：要么给教务开权限，要么把矩阵该行 expect 改成 {'fac'}；矩阵应增加「final_path 是否为该路由本身」的断言，禁止被弹回首页算通过。

- 备注：fac 200（考试下拉 + 加载考生）；stu/par/admin 也 303→/my/home。
- 真机读数：
  - `/grading/entry`（教师）：HTTP 200 /grading/entry；375 溢出 0px
  - `/grading/entry`（教务）：HTTP 303→200 /my/home；375 溢出 0px
  - `/grading/entry`（管理员）：HTTP 303→200 /my/home；375 溢出 0px
  - `/grading/entry`（学生）：HTTP 303→200 /my/home；375 溢出 无视图口读数
  - `/grading/entry`（家长）：HTTP 303→200 /my/home；375 溢出 无视图口读数

#### `/downloads` — P2｜教务

- **B/D 轴｜P2**
  - 现状证据：库内 0 条资料：五个角色都显示「全部 (0) / 暂无资料，请稍后再来。」——空态只有等待，没有下一步（如「去课程中心」「联系教务上传」）；bo/admin 的批量上传区还出现英文键位提示「支持 Ctrl/Shift 多选」。
  - 建议修法：空态补一个动作入口；键位提示改中文（「按住 Ctrl/Shift 可多选」）。

- 备注：分来源（课程资料/行政表格）与上传/管理模式在权限上分层正确。
- 真机读数：
  - `/downloads`（学生）：HTTP 200 /downloads；375 溢出 0px
  - `/downloads`（教师）：HTTP 200 /downloads；375 溢出 0px
  - `/downloads`（家长）：HTTP 200 /downloads；375 溢出 0px
  - `/downloads`（教务）：HTTP 200 /downloads；375 溢出 0px
  - `/downloads`（管理员）：HTTP 200 /downloads；375 溢出 0px

#### `/quiz` — P2｜学生家长

- **D 轴｜P2**
  - 现状证据：列表计数直接输出英文单位：学生/家长「0 items」、教师/教务「1 items」（且 1 items 单复数也错）。surface.json 把 /quiz 登记为有 english 门禁覆盖 ⇒ 实证英文门禁漏检。
  - 建议修法：改成「0 份 / 1 份」；并把该模式（数字+英文单位）加进 check_english 的检测规则。

- 备注：fac/bo/admin 200 可看全部测验（可议但不属本表范围）；stu/par 空态「暂无已发布的测验。」
- 真机读数：
  - `/quiz`（学生）：HTTP 200 /quiz；375 溢出 0px
  - `/quiz`（教师）：HTTP 200 /quiz；375 溢出 0px
  - `/quiz`（家长）：HTTP 200 /quiz；375 溢出 0px
  - `/quiz`（教务）：HTTP 200 /quiz；375 溢出 0px
  - `/quiz`（管理员）：HTTP 200 /quiz；375 溢出 0px
---

## 6. 副作用披露、环境限制与口径注意事项

### 6.1 本轮探测对库造成的**全部**写入（逐条可复核）

| # | 页面 | 写什么 | 量 | 复核命令 |
|---|---|---|---|---|
| 1 | `/my/messages/2`（学生身份） | `edu.message.is_read = true`（thread 2-8 中发给学生的未读） | **9 行**，`write_date = 2026-09-26 13:02:26Z` | `docker compose exec db psql -U odoo -d edu19 -c "select id,is_read,write_date from edu_message where thread_key='2-8' and recipient_id=8"` |
| 2 | `/my/notice/8`（教师/家长/教务三个身份） | `edu.notice.read` 追加 3 行（学生那行 08-24 已存在 ⇒ 幂等零写） | **3 行**，`create_date = 2026-09-26 13:02:22~23Z` | `select * from edu_notice_read order by id desc limit 5` |
| 3 | `/my/documents/enrollment-certificate` + `/my/documents/transcript` | `edu.audit.log` 追加（**设计意图**，页面已写「下载会记入操作审计」） | 2 页 × 2 轮 = **4 行** | `select * from edu_audit_log where action='自助下载' order by id desc limit 6` |
| 4 | **每一次 HTTP 请求（含全部探针）** | Odoo 框架自身的设备日志 `res_device_log` 追加 | 每请求 +1 行（本轮合计约 500 次请求） | `select count(*) from res_device_log`（补测 6 次请求实测计数器 810→816，`n_tup_ins` 每次 +1） |

- **业务状态 0 行改动**（含队长授权补测的 6 次：逐条做了探前/探后 `pg_stat_user_tables` 计数器与 19 张业务表精确行数比对，**全为 0 变化**）；未建/未改任何业务记录；未造样本、未跑 `-u`、未重启容器、未 git add/commit。
- 说明：`/my/messages/2` 与 `/my/notice/8` 的写入发生在**身份轮扫**里（首轮探针把 5 个身份都走了一遍），不是有意的状态改造；两处都是**打开即已读**的产品设计行为，且 `mark_read_for` 幂等、重探不再增加。
- 另外：诊断教师身份问题时顺带 GET 过两条**不在本清单内**的只读页（`/my/rollcall` 索引、`/my/marks` 索引），零写。

### 6.2 环境与代码口径

- **运行代码 = 工作区代码**（本次涉及文件全部 `mtime` 早于容器启动 `2026-09-24 22:00:03 +0800`）：`roles.py 09-24 18:23`、`batch2.py 09-24 15:34`、`identity.py 09-18`、`portal_ops.py 08-23`。`docker compose config` 确认 `custom_addons` 是 bind mount，容器内文件与工作区**逐行一致**（已用 `docker compose exec web sed` 抽查 `portal_ops.py:91-100`）。
  ⇒ 但**工作区有未部署改动**（`git status` 显示 `batch2.py`、`edu_portal_templates.xml` 等为 `MM`）——若他人随后重启容器，读数可能变化；**引用本账请带采集时刻**。
- 本地库可能被其它任务改动（同一时段确有他人留下的 `S2PROBE-*` 请假单、`E2E*` 周记等），因此**每条结论都以 2026-09-26 21:0x 的读数为准**。

### 6.3 一个必须写下来的方法论坑（否则后人会误判）

`edu.message` 上有**全局 ir.rule**（`edu.message: 仅收发双方本人可见（纵深防御）`，`global = true`），**连 admin 也会被过滤**：用 admin 会话做 search_count 得到 91 条，psql 真实是 1267 条；未读数 0 vs 523，差得极远。
⇒ 凡涉及 `edu.message`（以及任何挂了全局规则的表）的数字，**必须用 `sudo` 或 psql 复核**；本轮 `/my/messages/poll` 的 523 因此被确认为**正确**（不是虚高），已从「疑似缺陷」清单里撤回。

---

## 7. 改版评估（只能改设计才修得好的，**本轮不改，仅登记**）

| # | 发现 | 为什么不改设计修不好 | 涉及页 |
|---|---|---|---|
| 1 | ~~同一路径被两个模块各注册一次~~ **已撤回（修正 A）**：eval 家族 4 条是**设计如此**的 303 兼容层（继承覆写，非加载顺序漂移） | 唯一遗留是**死代码**：旧实现（`edu_portal/controllers/evaluation.py`、`edu_eval/controllers/eval_portal.py`）仍在库中但永不执行 —— 按设计稿「不删模型、不删表、不改 ACL；先建后删」应在**评估收口第二步**处理 ⇒ **关联：队列待办 ④**，不计入本账 | 4 条（已改判） |
| 2 | **教师身份反查存在第二套口径**（`edu_telegram/controllers/portal_ops.py:15` 自建，与 `edu_schedule/models/identity.py` 的唯一口径并存） | 只要允许多套口径并存，就会再次出现「同一个人在两套口径里是两个身份」；要么全仓收敛到一处（需要改依赖与调用点），要么为教学模块单独定义身份契约 | `/my/rollcall*`、`/my/marks*`、`/my/subject-reg` |
| 3 | **「一键通知」的按钮归属**（教师能看见影响面、能读到「点按钮」，但按钮只给教务） | 权限设计问题：改课通知该由任课教师发、还是教务发；两种设计的页面结构不同（教师版应是「已提交，等待教务处发出」的状态页） | `/timetable/session/<sid>/impact` |
| 4 | **测验与课程/班级的归属口径**（唯一 published 测验挂在 course 13，学生档案在 course 18） | 是「测验属于谁」的数据模型问题（课程/班级/科目三选一），不是页面能修的 | `/quiz/<qid>/take`、`/quiz` |
| 5 | **空态体例没有统一**（同是空态：`/library/media` 是描述型、`/student/subjects` 是行动型、`/downloads/mine` 带入口、`/subject/material/detail` 只有一句陈述） | 需要先定义「空态组件」的统一结构（说明 + 下一步 + 入口）再逐页替换；单页补一句话只会加固不一致 | 全部空态页 |
| 6 | **移动端表格体例**（原：`/grading/history` 溢出 116px、`/leave/approvals` 溢出 126px 且主按钮在视口外；**2026-09-28 复测两页均已归零，依据见下方 §7-6 复测依据**） | 需要决定「宽表在小屏是横滑、折叠、还是改卡片列表」的统一策略；逐个加 `table-responsive` 只是把问题藏进滚动条。**窄屏症状已被共用卡片体例 `edu_narrow_table_cards` 解决，但「全站窄屏表格体例」这道设计题仍未定 ⇒ 本行留在 §7** | **0 条未修**（原 2 条，含对照组 1 条 P1） |
| 7 | **8 处空的 `o_portal_pager` 占位 div**（模板里只有 `<div class="o_portal_pager …"/>`，控制器**没有任何一处**给它们传 `pager`）⇒ 这几页**当前不渲染分页条** | **需逐页判断「本来该不该分页」**：全量渲染的列表页本就不需要 pager（该删占位），只差一句 `t-call="portal.pager"` 的分页查询页则要补（该补 pager）；同一处 markup 两种结论的改法相反，**只看模板判不出来**，必须先定「哪些列表页必须分页」的口径。单页乱补会把「全量页」变成假分页 | 8 处占位 / 8 个模板（定位见下） |

> **§7-6 复测依据（2026-09-28 10:31:30–10:34:27 +0800，B 组；读数 `tests/ui/readings/usability-20260928-1034.json`）**
>
> | 项 | 读数 |
> |---|---|
> | 工具 / 参数 | `/opt/homebrew/bin/python3 scripts/check_ui_usability.py --report`（375×812、Playwright chrome headless、overflow 阈值 8px） |
> | `/grading/history` | faculty 与 backoffice 两条：HTTP 200/200、**overflow_px = 0**（scroll_width = client_width = 375）、3 个按钮全部 `inX=true` |
> | `/leave/approvals` | faculty 与 backoffice 两条：HTTP 200/200、**overflow_px = 0**（375/375）、56 个按钮 `inX` 全 true（`批准` left/right = 125/165、`驳回` 178/218、`详情` 232/272 —— 均在视口内）；即 §7-6 原记的「126px 溢出 + 主按钮在视口外」两症状**都已消失** |
> | 全量汇总 | **A0 / B0 / C0 / D0**（143 探页 = 97 页 × 身份，探到 138、排除 23）；唯一非环境失败 = `/my/study` 一条 `Page.goto: Timeout 30000ms exceeded`，是脚本文件头已记录的**量具抖动**（外网 `fonts.googleapis.com` 阻塞 @import ⇒ DOMContentLoaded 不触发），紧接同页 faculty 一次 867ms 成功 ⇒ 与本行两页无关 |
> | **字体状态（照实记 · bundle 级取证）** | 四条目标页读数的**服务端请求时刻**（`docker logs edu19-clone-web-1`）：`/grading/history` **10:32:04.779 / 10:32:05.746**、`/leave/approvals` **10:32:18.767 / 10:32:19.581**（+0800）—— 全部在**字体本地化之前**：旧 bundle `/web/assets/1/**0bfd426**/web.assets_frontend.min.css`（含阻塞式 `@import https://fonts.googleapis.com/css?family=Roboto…`）最后一次被服务是 **10:33:34**，新 bundle `**6e9f36d**` 由 Odoo 于 **10:33:58.876** 生成（日志：`assetsbundle: Generating a new asset bundle attachment /web/assets/1/6e9f36d/… (id:2450)`），字体已换成本地 `/web/content/2449/google-font-Roboto`。⇒ 本行两页的 0px 是「**字体未本地化（0bfd426）**」时的读数；字体本地化后字宽会微变，故**另跑一轮复测**（结果见下「字体本地化后复测」块），两轮数字都留 |
> | **并发状态（照实记）** | 这一轮工具自报 `并发 busy`（其口径 = `ps` 里另有 `tests/smoke/` 或 `scripts/check_` 进程）；我另用 `ps` 在**启动前/结束后**各查一次：ms-playwright 浏览器进程 0、门禁脚本 0（窗口内是否有别的脚本在跑，只有工具自己的读数作证）。⇒ 本轮 A 轴结论**带并发标记**，故又补了一轮 **`并发 quiet`** 的复测（见下「字体本地化后复测」块）：两轮数字一致，且本行关心的两条页 p95 探页耗时 494–559ms（无 30s 超时） —— 旧读数（116/126px）与 0px 差的是**两套不同症状**（溢出 + 按钮出视口 vs 全零），不是并发噪声能造出来的 |
> | 机制依据（为什么会归零） | 两页表体改用共用模板 `edu_portal.edu_narrow_table_cards`（定义 `custom_addons/edu_portal/views/roles.xml:546`），`/leave/approvals` 在 `roles.xml:624`、`/grading/history` 在 `roles.xml:1671` 调用（`<t t-call>`）。**运行库已升级**：`ir_ui_view` 的 `edu_portal.edu_leave_approvals`（id 3003）与 `edu_portal.edu_grading_history`（id 3572）arch 均含 `edu-card-table` 且 `t-call` 该模板，write_date = 2026-09-28 01:27:55 ⇒ 读到的是**已部署**的卡片体例，不是工作区里没升级的 XML |
>
> ⚠ 口径提醒：本条只说明**症状已归零**；「宽表在小屏该横滑 / 折叠 / 卡片」的**全站统一体例**仍是待决设计题（§7 保留本行的理由）。

> **§7-6 字体本地化后复测（2026-09-28 10:38:09–10:39:52 +0800，B 组；读数 `tests/ui/readings/usability-20260928-1039.json`）**
>
> 为什么必须再测一轮：**字体本地化会改变字体度量 ⇒ 可能动 A 轴读数**。事实链（可复核）：旧 bundle `0bfd426` 最后一次被服务 **10:33:34**，新 bundle `6e9f36d` 于 **10:33:58.876** 生成（`@import` 由 `fonts.googleapis.com` 改指本地 `/web/content/2449/google-font-Roboto`）—— 所以上面那一轮（目标页 10:32:04–10:32:19 探的）是**本地化前**，下面这轮是**本地化后**：
>
> | 页 | 身份 | 本地化后（`6e9f36d`，10:38:09 起） | 本地化前（`0bfd426`，10:32:04 起） |
> |---|---|---|---|
> | `/grading/history` | backoffice / faculty | overflow **0px**（375/375）｜按钮 3 个全 `inX` | overflow **0px**（375/375）｜按钮 3 个全 `inX` |
> | `/leave/approvals` | backoffice / faculty | overflow **0px**（375/375）｜按钮 56 个全 `inX`；`批准` 125/165、`驳回` 178/218、`详情` 232/272 | **同左，逐值相同** |
>
> 全量结论（本轮）：**A0 / B0 / C0 / D0**；143 探页探到 139、非环境失败 **0**、环境失败 0、排除 23；`并发 quiet`；容器未重启（`StartedAt … 02:27:49Z` 前后一致，样本有效）。
> **独立复跑（第三方会话，非我）**：10:35:17–10:37:03 的 `--report`（读数 `usability-20260928-1037.json`，并发 busy）同样是两页 0px ⇒ 本地化前后三方读数一致，本行「**0 条未修**」在两种字体状态下都成立，**不是字体度量差异造出来的**。
>
> ⚠ 仍留的坑（如实记）：`--report` 在**字体本地化前**那一轮出现过 `/my/study` 一条 `Page.goto Timeout 30000ms`（脚本文件头记的已知量具抖动）；本地化后这轮 0 条 —— 可能相关也可能只是概率，**未验证**，别当因果写。

> **§7-7 的 8 处占位定位（2026-09-28 由第二批修复作业实测补录，本批【未改代码】）**
> 判据：`grep -rn "o_portal_pager" custom_addons/edu_portal/views/` 中**空 div**（无 `t-call`）的行；"有无 pager 传参"按 `grep -rn "pager(" controllers/` 对拍（13 处调用点全在 batch1/batch2(`/library/media`)/downloads/enroll/ledger/roles，未覆盖下列模板）。
>
> | # | 占位位置 | 模板 | 页面（route） |
> |---|---|---|---|
> | 1 | `views/batch2.xml:428` | `edu_subject_details` | `/subject/details` |
> | 2 | `views/batch2.xml:635` | `edu_notice` | `/my/notice_board/notice` |
> | 3 | `views/batch3.xml:463` | `edu_subject_registration` | `/subject/registration` |
> | 4 | `views/batch3.xml:573` | `edu_requested_queue_list` | `/requested/queue/list` |
> | 5 | `views/batch3.xml:739` | `edu_time_off` | `/my/time_off` |
> | 6 | `views/batch3.xml:988` | `edu_result_overview` | `/users/result-overview` |
> | 7 | `views/batch3.xml:1151` | `edu_grievances` | `/my/grievances` |
> | 8 | `views/leave_flow.xml:864` | `edu_time_off_staff` | `/my/time_off`（教务视图覆写） |
>
> 风险（如实写）：数据量超一页时**用户看不到翻页入口**（例如 `/subject/registration`、`/requested/queue/list` 这类列表）。定级 **P3**：需先有「该页是否本该分页」的口径，再逐页处置（补 pager 或删占位），本批只登记不改。

---

## 8. 建议的后续（按投入产出排序，**本轮不执行**）

1. **门禁补强（最便宜、收益最大）**
   - `ux_v3_route_matrix.py::verdict` 增加断言：`final_path` 必须等于被探路径（或白名单内的收口目标），**禁止「被弹回 /my/home 也算 PASS」**——本轮抓到 `/grading/entry`、`/attendance/take` 两条教务假绿。
   - （原「新增同 rule 重复注册门禁」已撤回：该场景由 `scripts/check_view_xpath.py 规则 5（ROUTE-AMBIG）` 覆盖，且 eval 家族走的是**父子覆写**这一规范写法；修复 A 后不再需要新门禁。）
   - 新增 **同源门禁：身份反查只允许 `edu_schedule/models/identity.py` 一处**（grep 类断言）。
   - `check_english` 增加「数字+英文单位」「中英并列标题」两类规则（`0 items`、`学业 Academics` 现在都漏）。
2. **把「空态不得是死胡同」写成可执行断言**：空态块内必须同时存在 (a) 解释句 (b) 一个指向下一步的 `<a>`；扫 45+20 条即可全量覆盖。
3. **把 375 视口的横向溢出纳入门禁**：`documentElement.scrollWidth - innerWidth > 0` 判红（Playwright 脚本本轮已跑 144 个页面读数，约 3 分钟）。
4. 剩下两条 P1（`/timetable/session/<id>/impact` 的教师版按钮/出口、`/quiz/<qid>/take` 的学生准入）先修；再按 §9.1 收口 `edu_life` 的 chain① 口径（P2，尚未暴露但会静默失败）。eval 家族的死代码按**待办 ④** 排期，不在本账。
5. 12 条未探路由**授权后补测**：其中 8 条静态看是纯读页（`/registrar/subject/approvals/<rid>`、`/my/reimburse/apply`、`/attendance/import`、`/leave/transfer`(GET 即 303)、`/my/marks/<id>` 等），可在拿到队长授权与「零写」复核后一条 GET 补齐。

---

## 9. 补录（队长核查后追加；非页面级条目，**不计入 §1 密度**）

### 9.1 【P2】`edu_life` 的教师查询只查 chain① —— 违反「身份反查唯一口径」硬约定

- **证据（源码行）**：`custom_addons/edu_life/controllers/life.py:57`
  `def current_faculty(): return request.env['op.faculty'].sudo().search([('user_id', '=', request.env.uid)], limit=1)`
  ⇒ 只查链①（记录自身的 `user_id`，对 `op.faculty` 是 `_inherits` 委托到 `res_partner.user_id`），**没有链②兜底**。
- **违反的约定**：`custom_addons/edu_schedule/models/identity.py` 文件头明文把这一写法列为禁止——「**只按链①查 ⇒ 漏掉脚本新建的账号**（教师课表、课前提醒/改课通知、ICS 订阅、私信熟人圈**静默为空**）」；`docs/code-map.md §6 第 13 条` 亦为硬约定。
- **受影响页面（本轮全仓 grep 实测只有两处调用点）**：`/checkins/stats`（life.py:464）与 `/checkins/stats/export`（life.py:576）。对**按链②绑定**的账号，`current_faculty()` 返回空 ⇒ 页面直接 303 回 `/my/home`（学生则回 `/my/checkins`），**静默不可用、无任何错误提示**。
  - ⚠ 与队长来函的差异（如实记录）：队长提到 `/journals/review` 也受影响；本轮 grep 显示 `edu_life` 内 `current_faculty()` **仅有 464/576 两处调用**，而 `/journals/review` 与 `/journals/review/<id>` 走的是 `_require_teacher()`（`base.group_user` 判据）⇒ **不受本口径影响**。以代码证据为准，供队长复核。
- **级别 P2 的理由**：本库 3 个 `op.faculty` 中只有 id17 有登录账号且走链①命中 ⇒ **本轮无暴露账号**；但违反硬约定，一旦有账号按链②绑定（脚本/邀请码创建）功能会**静默为空**，属「明显粗糙/尚未暴露」档。
- **建议修法**：`life.py` 改为 `from odoo.addons.edu_schedule.models.identity import faculty_of_user`；并把「身份反查只允许一处实现」写成 grep 类门禁（见 §8 建议 1）。

### 9.2 【成因未定，需人工确认】`fac@local`（uid 9）两条链都落空

- **实测**：`res_users(id=9, login='fac@local', partner_id=46, active=f)` —— 账号**已停用**；`op_faculty` 3 行（partner 32 / 120 / 905）中**没有任何一行的 partner 是 46** ⇒ 链①（`user_id=9`）与链②（`partner_id.user_ids ∋ 9`）都落空，该账号没有教师档案。
- **同批对照**：`faculty@local`（uid 11）走链①命中（`op.faculty id=17`）；`op.faculty 43/213` 的 partner（120/905）**两条链都没有账号**（无登录账号）。
- **判定**：这是「测试账号未绑（且已停用）」还是「绑定流程（邀请码/建号脚本）的缺口」，本轮**判不出** ⇒ 记为**成因未定，需人工确认**。若属流程缺口，应给 identity 加断言（创建教师账号后必须能被 `faculty_of_user` 反查到）。

### 9.3 【P3】家长请假控制器里有调试 `print()`

- **证据**：`custom_addons/edu_portal/controllers/roles.py:1081`
  `print(f"LEAVE CREATED {mk.name} by parent for student {stu.id}")` —— 在**写路径**（家长代孩子请假提交成功）上直接 `print`，不是 `_logger`。
- **影响**：每次家长成功提交一条请假就向 worker 的 stdout 打一行；多 worker 下日志混杂、无级别、无留痕（审计另有 `edu.audit.log`）。
- **建议修法**：改 `_logger.info('edu_portal: 家长代提交请假 %s（student=%s）', mk.name, stu.id)`。

### 9.4 授权补测结论一览（护栏落实，含「有写 ⇒ 不探」的判定）

| 路由 | 处置 | 依据 |
|---|---|---|
| `/my/reimburse/apply` | **已探**（stu 200 / fac 200） | fees.py:231-250 GET 仅 `request.render`；前后业务表行数 0 变化 |
| `/my/child/<id>/leave/saved` | **已探**（par 200） | roles.py:1033-1046 同一 handler 仅 render；0 变化 |
| `/leave/transfer` | **已探**（fac 303→/leave/approvals） | roles.py:3221-3236：非 POST 立即 303，写全在 POST；0 变化 |
| `/leave/230/return_confirm` | **已探**（stu 303→/my/home） | roles.py:3307-3319：非 POST 立即 303，写全在 POST；0 变化 |
| `/my/study/session/293/join` | **已探**（stu 200 等待页） | study.py:351-372 + session_ext.py:232-248 `join_state()` 纯计算；0 变化 |
| `/my/lang/<code>` | **判定有写 ⇒ 不探** | search.py:183 `request.env.user.sudo().write({'lang': code})`，命中护栏① |
| `/registrar/subject/approvals/<rid>`、`/leave/approvals/<leave_id>`、`/attendance/import`、`/timetable/batch/<id>/deactivate`、`/attendance/selfcheck/<token>` | **不探**（队长排除清单） | 护栏⑤；其中 `/attendance/selfcheck` 另有 GET 写考勤的静态证据 |
| `/my/marks/<id>` | **不探**（退役模块） | 护栏④；同属 `edu_telegram` v2.2 |

> 说明：队长来函写「授权 8 条」，本轮按 4 条护栏逐条筛后**实际可探 5 条**——原 §8 提到的 8 条里，`/registrar/subject/approvals/<rid>`、`/attendance/import`、`/my/marks/<id>` 分别被护栏⑤/④排除，`/my/lang` 被护栏①排除。差集已在 §4 与本表逐条交代。

---
## 附录 A · 可重跑（环境已探活时逐条可复现）

> 脚本本体放在 `/tmp/ui42/`（**未写进仓库**，避免污染他人工作区）。下列命令在仓库根目录执行。

```bash
# 0) 探活三步
ls "$TMPDIR/edu19_upgrade.lock" 2>/dev/null || echo "无升级锁 OK"
docker compose ps --format '{{.Name}} {{.Status}}'
curl -s -o /dev/null -w '%{http_code}\n' 'http://localhost:8069/web/login?db=edu19'

# 1) 死角组 45 条 HTTP 真机（5 身份 × 每条，约 3 分钟；按 §6.1 会产生 12 行已读/审计写入）
python3 /tmp/ui42/probe_all.py --set dead --out /tmp/ui42/raw_dead.json
# 2) 队长补录的 4 条（只探这些，避免重跑全量）
python3 /tmp/ui42/probe_extra.py
# 3) 对照组 20 条
python3 /tmp/ui42/probe_all.py --set ctrl --out /tmp/ui42/raw_ctrl.json
# 4) 375/1280 视口（Playwright，约 3 分钟）
python3 /tmp/ui42/probe_viewport.py
# 4b) 队长授权的零写补测（单次 GET + 前后行数快照；护栏见 §9.4）
python3 /tmp/ui42/probe_extra2.py
# 5) 内容抽取 + 汇总（不再发请求）
python3 /tmp/ui42/analyse.py && python3 /tmp/ui42/gen_readings.py

# 单条复核示例（学生看指定公告；把路径换成别的即可）
python3 - <<'PY'
import requests
s = requests.Session(); s.trust_env = False
s.post('http://localhost:8069/web/session/authenticate', json={'jsonrpc':'2.0',
  'params':{'db':'edu19','login':'stu@local','password':'demo123'}}, timeout=30)
r = s.get('http://localhost:8069/my/notice/8', timeout=30)
print(r.status_code, len(r.text))
PY
```

**选择器/判据（复核用）**

| 轴 | 判据 | 选择器 / 命令 |
|---|---|---|
| A | 允许身份 200/303；非授权不得 200；无 5xx/404 | `probe_all.py` 的 `hist→final`；响应体不得含 `Traceback`/`Internal Server Error` |
| B | 空态有下一步 | `<main>` 内出现 `暂无/还没有` 的块里，必须有 `<a href>` 指向非本页 |
| C | 报错态有解释+出口 | 文本含「仅面向/无此课/不存在」时，检查是否有 `href="/my/home"` 或「返回」 |
| D | 无英文残留 + 中文措辞 | `analyse.py` 的 `en_tokens`（已剔除校名/代码/扩展名白名单）与 `wrong_terms` |
| E | 至少一条通向下一步的链接 | 内容区 `<a href>` 列表（已剥离门户顶栏与移动底栏） |
| F | 375 无横向溢出 / 主按钮首屏可达 / 无遮挡 | `documentElement.scrollWidth - innerWidth`；`main .btn-primary, main button[type=submit]` 的 rect；`position:fixed` 层与按钮 rect 相交 |
| G | 入口→反馈→回显→可行动错误（静态） | 控制器分支 + 模板 `saved/error` 参数 |

---

## 附录 B · 机器可读读数

- `tests/ui/readings/dead-45.json` —— 45 条（177 行读数，含 12 条未探的静态结论）
- `tests/ui/readings/control-20.json` —— 对照组 20 条（100 行读数）
- `tests/ui/readings/summary.json` —— 汇总数字与密度比

每条读数结构：`{path, path_template, role, set, authorized, http{first,hist,final,final_path,bytes,ms,marks}, viewport{viewport_375,viewport_1280}, key_elements_found{forms,tables,inputs,buttons,content_links,exit_links,english_tokens,wrong_terms}, verdict{A..G}, level, findings[], notes, collected_at}`。
