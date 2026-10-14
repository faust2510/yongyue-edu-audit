# 学生一条龙服务 v3 设计（t6）
> **状态**：`已上线` ｜ **主题**：`学生一条龙服务 v3` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「本文件只做设计，不含实现；实现待 t4/t5 解锁后开工」，实际已于 `7b43a49` 交付（2026-09-26 核对发现）。正文未改动。

> 六步闸门第 4 步产出物。上游调研：[`docs/research/onestop-learning-and-repetitive-work.md`](../research/onestop-learning-and-repetitive-work.md)（t1 归档，2026-09-12）。
> 本文件只做设计，不含实现；实现落在 `custom_addons/edu_portal/` 与 `custom_addons/edu_schedule/`。
> 范围：t6（课程中心 / 课节级 Zoom / 课前提醒 / 课程资料归属 / 档案成绩三层 / 首页 Timeline 工作台）。t8（已读回执 / 过期下架 / 行政表格分流）另开文档。

> **引用口径**：「回引」列的 `§x` 一律指**上游调研文档**的章节；引用本文自身章节时写作「本文 §x」。

> **修订说明（2026-09-18，H-1 学生门户主页合并）**：本文关于首页 IA 的结论（首页瘦身成 Timeline 工作台、
> 全量卡片迁往 `/my/apps`）**已被校长拍板取代** —— 合并后 `/my/home` **就是**全量宫格
> （`edu_portal.edu_dashboard_v2`），旧 Timeline 的唯一独有内容「待办三桶」以**顶部窄条**保留在宫格页
> （三桶全空则不渲染），`/my/apps` 对学生/家长降级为 **303 兼容层**（内部用户仍 200）。
> **本文其余结论一律保留**（含 §6「零功能丢失对照表」，继续作为该口径的清单）；历史决策记录不改。
> 现行口径见 [`student-portal-home-profile-design.md`](student-portal-home-profile-design.md)。

最后更新：2026-09-12 ｜ 状态：**D1 已批准（方案 A）；D2 已转 verifier；实现待 t4/t5 解锁后开工**

---

## 0. 环境前置（实测，非引用）

### 0.1 本机 `-u` 升级命令必须补 db 参数（阻塞级）

`docs/code-map.md` §2/§10 与 `scripts/safe_upgrade.sh` 写的命令形式在本机**跑不通**：

```
docker compose exec web odoo -c /etc/odoo/odoo.conf -d edu19 -u <模块> --stop-after-init
→ psycopg2.OperationalError: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed
→ EXIT=1
```

根因（已定位）：`docker-compose.yml` 把 `./config/odoo.conf` 以 `:ro` 挂到 `/etc/odoo/odoo.conf`，而该文件**没有 `db_host/db_user/db_password`**；官方镜像 `entrypoint.sh` 只在使用 `docker compose run`（走 entrypoint）时注入 `HOST/USER/PASSWORD`，而 `docker compose exec` **绕过 entrypoint**，于是 Odoo 回落到本地 unix socket。

**已修复（2026-09-12 队长）**：本仓**统一走 `scripts/safe_upgrade.sh`**，不要手敲命令：

```bash
bash scripts/safe_upgrade.sh edu_portal,edu_brand   # 默认 -i（对已装模块等价于升级，新模块首装也能用）
bash scripts/safe_upgrade.sh -u edu_portal          # 需要严格 -u 时，把 -u 作为第一个参数
```

该脚本共修四处（队长通报，我按 107 行版本核对）：① 补 `--db_host=db --db_port=5432 --db_user=odoo --db_password=odoo`；② 加 `--no-http` 避免撞主服务 8069；③ 新模块首装用 `-u` 无效 → 默认 `-i`；④ **挂载失步自检**（升级前对拍近 30 分钟改动文件的宿主/容器 md5，失步则 `--force-recreate web` 后复检）。

**退出码语义（实现时按此判成败）**：`0` 成功（且已扫过失败特征）；`3` 等锁超时；`4` 挂载失步未修复（拒绝升级）；`5` 退出码为 0 但输出含 `Traceback`/`CRITICAL`/`manifest not found`/`not installable, skipped`/`inconsistent states`。

> ⚠️ 两点务必注意：
> 1. **别把升级输出管进 `tail`**——退出码会被吃掉，出现「exit=0 但什么都没升」的假象。脚本已改为 `tee /tmp/edu19_upgrade.log` 并单独取 `PIPESTATUS[0]`。
> 2. **挂载失步是间歇性的，不要按「write vs edit」之类的规律去规避**（队长对照实验未能复现稳定规律）——那会给出虚假的安全感。让脚本自检，别猜。
> 无脚本时的等价裸命令（我实测 EXIT=0）：`docker compose exec -T web bash -lc 'odoo -c /etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" -d edu19 -u <模块> --stop-after-init'`（**不含**挂载自检与失败特征扫描，仅应急）

### 0.2 登录页 curl 必须带 cookie jar（否则误判为死循环）

`curl http://localhost:8069/web/login?db=edu19` 不带 cookie 时返回 **302 到自身**（`Location: /web/login?db=edu19`）。这是 Odoo 选库会话跳转（源码 `odoo/http.py:1848 session.db = dbname`），**不是故障**。

```bash
curl -c /tmp/cj -b /tmp/cj -L "http://localhost:8069/web/login?db=edu19"   # → 200，<title>Login | 永约学坊</title>
```

带 cookie jar 后 200（26194 bytes）。Python 侧用 `requests.Session()` 天然规避。

### 0.3 现状基线（本次实测）

| 指标 | 现状 |
|---|---|
| `/my/home` DOM 高度 @1280px | **3744 px** |
| `/my/home` DOM 高度 @375px | **5889 px** |
| 首页分类容器数 | 9 |
| 本地数据量 | op_session 263 / op_subject 33 / edu_lesson 8 / edu_download_file 2 / op_student 4 |

---

## 1. 复用 vs 自研边界（能抄不造）

| # | 能力 | 决策 | 载体 | 依据 |
|---|---|---|---|---|
| R1 | 会议链接存储 | **复用（原生字段）** | `calendar.event.videocall_location` | 调研 §2「Odoo 19 原生会议链接位」+ §5#10 |
| R2 | 资料存储/权限/审计 | **复用（零改动）** | `edu.download.file` + `edu.download.category` + `EduDownloadLog` | 仓内既有 downloads v2.1；§3「Show course to 可见范围」 |
| R3 | 课程容器 | **复用** | `op.subject` | 仓内 `models/lms.py` 已定：课程容器复用基座 op.subject |
| R4 | 课次与进度 | **复用** | `edu.lesson` / `edu.lesson.progress` | 仓内既有（LMS 已交付） |
| R5 | 成绩数据 | **复用** | `op.marksheet.line` / `op.result.line` / `op.exam` | 仓内 `/grade-book` 已在用 |
| R6 | 课节排期 | **复用** | `op.session`（openeducat_timetable） | 基座，只读不改 |
| R7 | 日历订阅 | **复用** | `res.users.edu_ical_token` | 仓内 `models/ical.py`；§5#7 |
| R8 | 提醒去重 | **复用** | `EduNotifyPref`（通知偏好） | 仓内既有模型 |
| R9 | 顺序解锁状态机 | **自研（语义抄 Canvas）** | `edu.lesson` 三字段 + 1 计算 | §1 Canvas Modules + §5#1 |
| R10 | 课前提醒任务 | **自研（形态抄 mod_zoom）** | ir.cron 每 5 分钟 | §2「独立计划任务，每 5 分钟」+ §5#4 |
| R11 | Timeline 分桶 | **自研（口径抄 Moodle）** | 控制器聚合，无新模型 | §1 Moodle Timeline 筛选 + §5#2 |
| R12 | 成绩三层展示 | **自研（模型抄 Moodle）** | 控制器聚合现有 op.* | §3 grade_items/grade_grades/grade_letters + §5 |

### 1.1 明确不做（写清为什么）

- **不对接任何会议 API**（Zoom/腾讯/飞书）——§2.2 额度实测：Zoom 每用户每天 100 次创建上限、腾讯会议免费版不支持 API 创建、飞书只支持 30 天内且不生成日程。一期无收益。
- **不自建第二套资料系统**——R2 复用；课程归属只是给 `edu.download.file` **加一个字段**，不是新模型。
- **不自建 URL/token 体系**——R1；门户入会一律跳原生 `videocall_location`，不自造短链。

---

## 2. 决策记录（已拍板）

### D1 会议链接落在 `op.session` 还是 `calendar.event`？——✅ 队长已批准：方案 A

班级课节的记录是 `op.session`（OpenEduCat），而原生 `videocall_location` 在 `calendar.event` 上，两者当前**无任何桥接**（全仓 grep 确认）。两种落法：

| 方案 | 做法 | 优点 | 代价 |
|---|---|---|---|
| **A（建议）** | `op.session` 加 1 个 M2o `calendar_event_id`；链接**只存** `calendar.event.videocall_location` | 完全贴合「不自建 URL 体系」；未来接入 Odoo 原生日历/ICS 自动生效 | 需管生命周期（建/同步/删）；多一层记录 |
| B | `op.session.meeting_url` 直接存（仿 `_set_videocall_location` 的 http/https 校验） | 最简单，1 字段 1 路由，§2.1「最低成本」字面 | 自建了一套 URL 存储，与队长「不自建 URL 体系」相悖；脱离原生日历 |

**决定（2026-09-12 队长批准）：采用方案 A**。理由：与调研 §5#10 结论一致，且我**已实测**原生字段可写（证据见本文 §9.1）。
方案 B 作为退路保留：若实施中发现生命周期管理成本过高，可退回 `op.session.meeting_url` 直存，但**必须复用** `_set_videocall_location` 的 http/https 归一化语义；届时本文 §3.1 字段表与 §4 路由设计不变，只换存储位置。

### D2 `/my/apps` 与 t4 的 `/apps` 关系 —— ✅ 已转 verifier

`tests/smoke/ux_v3_route_matrix.py` 第 72-74 行把 `/apps` 记为「t4 交付」、`/my/apps` 与 `/my/study` 记为「t5 交付」——**该归属标注与本轮 DAG 不符**（t5 是 i18n-eng 的本土化任务）。按队长本轮指派：`/my/study`、`/my/apps` 属 **t6（我）**，`/apps` 属 t4（brand-eng）。已转 verifier 同步更正矩阵注释（2026-09-12 队长通报），避免 t9 复核时归属错乱。

---

## 3. 数据流与新增字段清单

### 3.1 新增字段（全部为「加字段」，无新模型）

| 模型 | 字段 | 类型 | 说明 | 回引 |
|---|---|---|---|---|
| `op.session`（edu_schedule 扩展） | `calendar_event_id` | M2o `calendar.event`（ondelete=set null） | D1 方案 A 的桥接字段（**1 字段**） | §2.1#1 |
| `op.session`（扩展，存储型布尔，非 computed） | `reminder_sent_at` | Datetime | 提醒已发水位，cron 幂等依据 | §2「每 5 分钟计划任务」 |
| `edu.lesson` | `require_sequential` | Boolean | 必须完成前一课次才解锁（按 sequence） | §1 Canvas `require_sequential_progress` |
| `edu.lesson` | `unlock_at` | Datetime | 定时解锁 | §1 Canvas `unlock_at` |
| `edu.lesson` | `prerequisite_lesson_id` | M2o `edu.lesson` | 显式前置课次（支持跨序列先修） | §1 Canvas `prerequisite_module_ids` |
| `edu.download.file` | `subject_id` | M2o `op.subject`（可空，index） | 课程归属；空=行政/通用资料 | §3 Course Attendees / Show course to |
| `edu.download.category` | `subject_id` | M2o `op.subject`（可空） | 课程文件夹归集（可选，便于批量挂课） | 同上 |

**计算字段（不落库）**：

| 模型 | 字段 | 取值 | 回引 |
|---|---|---|---|
| `edu.lesson` | `lock_state` | `locked / unlocked / started / completed` | §1 Canvas `state` 四态 |
| `op.session` | `meeting_url` | related `calendar_event_id.videocall_location`（readonly） | R1 |

**系统参数（无 schema 变更）**：
- `edu.meeting.join_lead_minutes`（默认 15）——最早可入会分钟数，对应 mod_zoom 的 `firstjoin`/leadtime（§2）
- `edu.meeting.reminder_minutes`（默认 30）——T-30min 触发课前提醒（§2.1#2）

### 3.2 数据流

```
教师/教务在课节上设置 Zoom 链接
   └─> op.session.calendar_event_id ─> calendar.event.videocall_location   [原生字段, videocall_source=custom]

学生 /my/study
   ├─ 课程中心：op.subject（按 op.student.course 过滤，沿用 lms.py _subjects_for 口径）
   ├─ 课节列表：op.session（本班/本科目） + edu.lesson（先修/解锁态 lock_state）
   ├─ 课程资料：edu.download.file[subject_id=本科目] ∩ 可见范围(_identity_fields)   ← 复用 downloads，不新系统
   └─ 档案成绩三层：op.marksheet.line / op.result.line / op.exam

课前提醒 cron（每 5 分钟）
   └─ 扫 start_datetime ∈ [now+T-reminder, now+T-reminder+5min] 且 reminder_sent_at 为空 且 有 meeting_url
        └─> EduNotifyPref 尊重偏好 → EduMessage / Telegram outbox → 写 reminder_sent_at（幂等）
```

---

## 4. 路由清单

| 路由 | 方法 | 角色 | 说明 | 回引 |
|---|---|---|---|---|
| `/my/home` | GET | 登录用户 | **改造**为 Timeline 工作台（瘦身，见 §5） | §1 Moodle Timeline |
| `/my/apps` | GET | 登录用户 | **新建**应用面板：全量卡片目录（零功能丢失载体） | §4 钉钉工作台式宫格 |
| `/my/study` | GET | 学生/家长 | **新建**课程中心：我的课程 + 今日课节 + 待办 Timeline | §2.1#1 |
| `/my/study/<int:subject_id>` | GET | 学生/家长 | **新建**课程详情：课节（含锁定态）+ 课程资料 + 成绩三层入口 | §1 + §3 |
| `/my/study/session/<int:session_id>/join` | GET | 学生/家长 | **新建**课节入会：时间窗检查 → 302 到 `videocall_location` | §2 `clickjoin`/`firstjoin` |
| `/my/study/link/<int:session_id>/save` | POST | 教师/教务 | **新建**设置课节链接（csrf；兄弟路由 `/save` 约定） | 铁律 4 |
| `edu_portal.cron_session_reminder` | cron | — | **新建**每 5 分钟课前提醒 | §2 `send_ical_notifications` |

> 写操作一律 POST + csrf + 兄弟路由 `/xxx/save`（`docs/dev-workflow.md` 实现约定）；
> 控制器用 `current_student()/current_faculty()/privileged_staff()` 判空分流，**不建自定义组**（铁律 3）；
> 门户页外壳一律 `t-call="edu_portal.edu_page"`；模板禁 `%` 格式化，格式化在控制器侧完成。

---

## 5. 首页 Timeline 工作台（核心增量）

### 5.1 新 IA（`/my/home` 只留 4 块）

| 块 | 内容 | 上限 | 回引 |
|---|---|---|---|
| ① 今日课节 | 今天/现在进行的 op.session + **一键入会**（带 leadtime 文案） | 全部今日 | §2 firstjoin |
| ② 待办 Timeline | **已逾期 / 未来 7 天 / 未来 30 天** 三桶，来源=作业·考试·待解锁课次·请假/申诉结果·评教 | 每课程 5 条 | §1 Moodle Timeline（overdue/next7days/next30days + 每课程默认 5 条） |
| ③ 我的课程 | 最多 3 张课程卡（进度%），「全部课程 →」进 `/my/study` | 3 | §1 Canvas Modules |
| ④ 快捷入口 | 最多 8 个高频卡 + 「全部应用 →」进 `/my/apps` | 8 | §4 钉钉宫格 |

- 空桶/空态**不渲染**（不占高度）。
- 历史学期在成绩页折叠（§3「历史学期折叠」）。

### 5.2 高度目标与达成手段

| 视口 | 现状（实测） | 目标 | 降幅 |
|---|---|---|---|
| 1280px 桌面 | 3744 px | **≤1800 px** | −52% |
| 375px 手机 | 5889 px | **≤2600 px** | −56% |

达成手段（逐条可验收）：
1. **35 张卡全部移出首页** → `/my/apps` 分组宫格；首页只留 §5.1 四块。（这是高度的主因：现首页平铺 9 组 / 35+ 卡）
2. 每课程 Timeline 条目**硬上限 5**（Moodle 口径），超出折叠为「还有 N 条」。
3. Timeline **只渲染有数据的桶**，空桶零高度。
4. 课程卡上限 3，快捷入口上限 8。
5. 复用现有渐变瓦片 SVG / FA 图标，**不新增图片请求**（沿用 batch2.py 的图标优先级逻辑）。
6. 手机端默认折叠「未来 30 天」桶。

> 度量口径：`scripts/shoot_ux_v3.py`（t3 产出，含 M3 首页高度汇总）输出 `tests/gap/shots/ux-v3/heights.json`；本文的 3744/5889 由等价 playwright 脚本实测（1280×900 / 375×812，登录 stu@local）。

---

## 6. 零功能丢失对照（旧首页 35 张卡逐项落点）

旧首页卡片来自 `custom_addons/edu_portal/controllers/batch2.py`：`_OPENEDUCAT_CARDS`(26) + `_COMMON_CARDS`(2) + `_YONGYUE_CARDS`(7) = **35 张**。「落点」= 新 IA 里能找到该入口的位置。

| # | href | 旧标题 | 旧分组 | 新落点 | 备注 |
|---|---|---|---|---|---|
| 1 | student/profile | 学生档案 | 学业 | /my/apps#academics | 档案页入口保留 |
| 2 | my/fees | 费用账单 | 财务 | /my/apps#finance | 同名费用改名由 t5 负责 |
| 3 | my-library | 数字图书馆 | 资源 | /my/apps#resources | 不变 |
| 4 | library/media | 图书馆 | 资源 | /my/apps#resources | 不变 |
| 5 | meeting/information | 线上会议 | 资源 | **/my/study 课节入会** | 升级：全局 `edu.zoom_url` → 课节级 |
| 6 | my/notice_board/notice | 布告栏 | 社区 | /my/apps#community + 首页通知 | 通知条保留 |
| 7 | users/result-overview | 测验结果 | 学业 | **/my/study 成绩三层 L1** | 升级为三层页 |
| 8 | my/time_off | 请假 | 个人 | /my/apps#personal + Timeline | 状态更新进 Timeline |
| 9 | student/progression | 进展 | 学业 | **/my/study 成绩三层** | 并入档案成绩页 |
| 10 | subject/details | 学习材料 | 资源 | **/my/study 课程资料** | 升级：按课程归属 |
| 11 | my/asset-request | 资产请求 | 资源 | /my/apps#resources | 不变 |
| 12 | student/assignment/details | 作业 | 学业 | Timeline + /my/apps#academics | 逾期/7 天/30 天 |
| 13 | student/exam | 考试 | 学业 | Timeline + /my/apps#academics | 同上 |
| 14 | my/grievances | 申诉 | 社区 | /my/apps#community + Timeline | 结果进 Timeline |
| 15 | my-courses | 课程 | 学业 | **/my/study 课程中心** | 主入口 |
| 16 | certificate | 证书 | 学业 | /my/apps#academics | 不变 |
| 17 | student/attendance | 出席率 | 学业 | /my/apps#academics | 不变 |
| 18 | student/newregistration/info | 入场 | 学业 | /my/apps#academics | 旧默认隐藏；入口保留 |
| 19 | student/timetable | 时间表 | 学业 | /my/apps#academics | 旧默认隐藏（并入校历） |
| 20 | grade-book | 成绩簿 | 学业 | **/my/study 成绩三层** | 升级为三层页 |
| 21 | course/change/request | 课程变更请求 | 学业 | /my/apps#academics | 不变 |
| 22 | subject/enroll | 报课选科 | 学业 | **/my/study 课程中心** | 报课入口前置 |
| 23 | subject/registration | 科目注册 | 学业 | **/my/study 课程中心** | 申请进度 |
| 24 | my/academic-calendar | 学术日历 | 学业 | /my/apps#academics | 旧默认隐藏（并入校历） |
| 25 | my/thesis | 论文 | 学业 | /my/apps#academics | 不变 |
| 26 | online/meeting | Zoom 会议 | 资源 | **/my/study 课节入会** | 升级：课节级 |
| 27 | my/addresses | 地址 | 个人与设置 | /my/apps#personal | 不变 |
| 28 | my/security | 连接 & 安全 | 个人与设置 | /my/apps#personal | 不变 |
| 29 | my/checkins | 每日打卡 | 成长 | /my/apps#growth + Timeline | 未打卡进 Timeline |
| 30 | my/journals | 我的周记 | 成长 | /my/apps#growth + Timeline | 本周未交进 Timeline |
| 31 | eval/my | 我的评分 | 成长 | /my/apps#growth | 不变 |
| 32 | eval/review | 评教填答 | 成长 | /my/apps#growth + Timeline | 待填进 Timeline |
| 33 | help | 使用指南 | 更多 | /my/apps#more | 旧默认隐藏（并入 /my/help） |
| 34 | downloads | 资料下载 | 资源 | **/my/study 课程资料** + /my/apps#resources | 课程区/行政区在 t8 分流 |
| 35 | my/reimburse/apply | 发起报销 | 财务 | /my/apps#finance | 不变 |

**动态注入卡（不在 35 内，同样不得丢失）**：`my/child`（家长）、`quiz`、`notice/publish`（教务处）、`timetable/bulk`、`timetable/copy`（教务处）、`my/contacts`、`my/calendar`、`my/messages`、`alumni/job/list`（backoffice）——全部进 `/my/apps` 对应分组；`/my/calendar`、`/my/messages` 另在首页快捷入口优先占位。

**统计口径**：35/35 有落点；其中 **10 张**由「平铺入口」升级为「一条龙内嵌」（#5/7/9/10/15/20/22/23/26/34）。

---

## 7. 验收标准

| # | 验收项 | 判定手段 | 回引 |
|---|---|---|---|
| A1 | `/my/home` @1280px DOM 高度 **≤1800px** | `scripts/shoot_ux_v3.py` → heights.json | §5.2 |
| A2 | `/my/home` @375px DOM 高度 **≤2600px** | 同上 | §5.2 |
| A3 | 旧 35 卡**零丢失**（逐项可达） | 按 §6 表逐条打开落点，35/35 = 200 | §6 |
| A4 | `/my/study`、`/my/apps` 从 PENDING → **PASS** | `tests/smoke/ux_v3_route_matrix.py` | t9 |
| A5 | 顺序解锁正确：锁定课次不可标完成，前置完成后解锁 | 学生账号实操 + 三个字段的组合矩阵 | §1 |
| A6 | 课节入会时间窗：早于 `start − join_lead_minutes` 提示「最早可提前 N 分钟加入」 | 手动改 `op.session.start_datetime` 复现 | §2 firstjoin |
| A7 | 课前提醒 **幂等**：重复跑 cron 不重复发 | 连跑 2 次 cron，比对 EduMessage 条数 | §2 |
| A8 | 资料按课程归属正确，且**不泄露可见范围外资料** | 学生视角遍历课程资料 vs `_identity_fields` 口径 | §3 |
| A9 | 成绩三层：本学期总览 → 科目条目 → 单条目反馈；历史学期折叠 | 学生实操截图 | §3 |
| A10 | 用户可见英文 = 0 | `python3 scripts/check_english.py`（新增路由须登记进其路由表） | 铁律 |
| A11 | 本地升级 EXIT=0 无 Traceback | §0.1 的**修正命令** | t9 |

---

## 8. 未验证 / 风险 / 待确认

1. ~~D1 决策未定~~ → **已解决**：队长批准方案 A（本文 §2）。实施方案 A 时须补做生命周期验证（见下条）。
2. **calendar.event 生命周期未验证**：本次只验证了「写入持久」（§9.1），**未**验证「op.session 删除/改期时日历事件的级联与同步」，实现时须补。
3. **原生 compute 竞争未验证**：`videocall_location` 是 `compute+store`，我验证了 create/write 后读回持久（`videocall_source=custom`），**未**验证批量写与并发场景下 recompute 是否覆盖。
4. **A1/A2 高度目标未验证可达**：机制上成立（移走 35 卡是主因），但需实现后实测；若达不到，优先再砍③④上限。
5. Moodle 官方文档全站 Cloudflare 403，顺序解锁/完成语义**以 Canvas API 文档 + Moodle GitHub 源码为准**（调研 §6 已声明）。
6. 「需确认已读」「过期自动下架」无原生原语（调研 §3/§4.4），属 **t8** 范围，本文不展开。
7. **成绩变更留痕**（Moodle `grade_grades_history`）属 **t7**（flow-eng）范围；本文的「成绩三层」只做**展示**，两者接口边界：t6 读 `op.result.line`，t7 负责写入与留痕。

---

## 9. 附：本次取证记录

### 9.1 原生 `videocall_location` 可写性（Odoo shell，全程 rollback，零残留）

```
PROBE field: store=True compute=True readonly=True copy=True
PROBE after_create: url='https://zoom.us/j/1234567890' source='custom'
PROBE after_write_readback: url='https://us02web.zoom.us/j/9876543210?pwd=abc'
PROBE rows_before=0 rows_after_rollback=0
```

结论：自定义 https 链接可写入并持久，`videocall_source` 计算为 `custom`；`_compute_videocall_location` 只在 `discuss` 源时赋值，**不会清掉自定义链接**。
对应源码：`odoo/addons/calendar/models/calendar_event.py` 141 行（字段）、529-534（compute）、544-553（`_set_videocall_location` 归一化）、555-561（source 计算）。

### 9.2 现状代码事实（本次勘察）

- 现有 Zoom 入口是**全局单链接**：`edu.zoom_url` 系统参数，`batch3.py:651 _zoom_url()` → `/meeting/information`、`/online/meeting` 直接 302。**无课节级链接** ← t6 要补的缺口。
- `op.session` **没有任何**会议链接字段（`openeducat_erp/openeducat_timetable/models/timetable.py:28`）。
- 全仓 **无** `calendar.event` 引用（`models/calendar_event.py` 定义的是自研 `edu.event`，与原生同名但不同模型）。
- `edu.lesson` 现有字段仅 `sequence/state(draft|published)`，**无解锁控制** ← t6 要补 3 字段 + 1 计算。
- `edu.download.file` 有可见范围四勾选（`visible_registrar/teacher/student/parent`）+ `_identity_fields()` 判定，**无课程字段** ← t6 加 `subject_id`。

---

## 10. 既有断言同步清单 + 零功能丢失可达性校验提案

> 归属说明：`tests/` 与 `scripts/` 是 **verifier 的 inScope**，我**未创建、未修改**任何测试文件；本节只提交清单与提案，供 verifier 实现、（队长转交）。

### 10.1 会被首页重构打红的既有断言（逐条核对源码，非转述）

| # | 位置 | 断言内容 | 为何会红 | 处理方向 |
|---|---|---|---|---|
| 1 | `tests/smoke/smoke_student.py:70` | `page.locator(".o_portal_index_card").count() >= 10`（在 /my/home） | 首页不再平铺卡片网格，卡片数降到 10 以下 | 改指向 `/my/apps`（35 张卡所在处），保留「网格≥10」的原意 |
| 2 | `tests/smoke/E_quiz_cross.py:319` | 正则 `o_portal_index_card.*?href="([^"]+)"` 抓 /my/home 首卡 href，用于「首页搜索框 Enter 跳首卡」B7 | 首页结构变化后抓不到卡 → `first_href=None` → B7 拿不到 PASS | 搜索框若保留在首页，正则改抓新快捷入口块的卡；否则该项改在 /my/apps 上跑 |
| 3 | `tests/smoke/ux_rework_playwright.py:72-110` | 收藏编辑全流程：`.o_portal_index_card a[data-app-href="library/media"]`（位于「资源与学习」分类组）→ pin / 上移 / unpin / 刷新持久化 | 分类组与 `library/media` 卡移入 `/my/apps` 后选择器找不到 | 整段改在 `/my/apps` 上跑；**`[data-fav-grid]` 与 `data-app-href` 契约必须保留** |
| 4 | `tests/smoke/G_messages_smoke.py:59` | 统计 `/my/messages` 上 `class="o_portal_index_card col-12 msg-conv"` 行数 | **不是首页的问题**：该 CSS 类被 7 个模板共用（见 10.2），首页重构若改名/删类会连带打红 /my/messages | 见 10.2，作为**硬约束**处理 |

> 路径更正：`ux_rework_playwright.py` 实际位于 `tests/smoke/`，**不是** `scripts/`（队长原清单写的是 scripts/，此处以实测为准）。

### 10.2 硬约束：`.o_portal_index_card` 是共享类，**不得改名或删除**

grep 全仓，该类至少被 7 个模板共用：

| 模板 | 行 |
|---|---|
| `views/batch2.xml`（首页） | 896 / 1010 / 1032 / 1073 |
| `views/contacts.xml` | 24 |
| `views/edu_portal_templates.xml` | 236 |
| `views/help_center.xml` | 17 |
| `views/messages.xml` | 64 |
| `views/roles.xml` | 13 / 126 |

→ 首页重构**只能改「哪些卡出现在首页」，不能动这个类**。否则 `/my/contacts`、`/my/messages`、`/help`、教师页、家长页会连锁返工。

### 10.3 提案：零功能丢失「可达性 + IA 覆盖」双层断言

**目标**：把本文 §6 的「35/35 落点」从**声明**变成**机器可验证**——这也是本设计里唯一能防住「重构时悄悄删掉一张没人记得的卡」的机制。

**脚本**：`tests/smoke/zero_loss_reachability.py`（`tests/` 属 verifier inScope，本文只提案）

**输入**（单一真源，直接抄本文 §6 的 35 张）：

```python
STALE_35_HREFS = [
    # _OPENEDUCAT_CARDS(26)
    'student/profile', 'my/fees', 'my-library', 'library/media',
    'meeting/information', 'my/notice_board/notice', 'users/result-overview',
    'my/time_off', 'student/progression', 'subject/details', 'my/asset-request',
    'student/assignment/details', 'student/exam', 'my/grievances', 'my-courses',
    'certificate', 'student/attendance', 'student/newregistration/info',
    'student/timetable', 'grade-book', 'course/change/request', 'subject/enroll',
    'subject/registration', 'my/academic-calendar', 'my/thesis', 'online/meeting',
    # _COMMON_CARDS(2)
    'my/addresses', 'my/security',
    # _YONGYUE_CARDS(7)
    'my/checkins', 'my/journals', 'eval/my', 'eval/review', 'help',
    'downloads', 'my/reimburse/apply',
]
# 动态注入卡（不在 35 内，同样不得丢失）
DYNAMIC_HREFS = [
    'my/child', 'quiz', 'notice/publish', 'timetable/bulk', 'timetable/copy',
    'my/contacts', 'my/calendar', 'my/messages', 'alumni/job/list',
]
```

**身份策略**：默认用 **admin** 跑全量 35 条（超集，避免 `notice/publish`、`timetable/*`、`alumni/job/list` 这类角色门禁入口误报 FAIL）+ 另跑一遍 **student** 子集（学生应当可达的那些）。

**两层断言（第二层才是真门禁）**：

| 层 | 断言 | 说明 |
|---|---|---|
| **L1 可达性** | 逐条 `GET BASE + '/' + href`，跟随跳转，期望最终 **200**（或 303→200） | 对 6 张「默认隐藏」卡**同样必须通过**——**隐藏 ≠ 删除，路由必须仍在** |
| **L2 IA 覆盖** | 抓 `/my/apps` 的 HTML，断言 35 条 href **全部出现**（`href="/<href>"`） | L1 只证明「URL 能打开」；L2 才证明「用户点得到」。**缺 L2 就抓不到「卡被删掉」的回归** |

**输出**：`href -> (L1 status, L2 present)` 表 + 计数；退出码 `0`=全绿，`1`=有缺失，`2`=运行错误（登录失败/服务不可达）。

**已知例外（需在脚本里显式声明，避免误判）**：
- `meeting/information`、`online/meeting`：t6 后语义变为「跳课节入会」，应仍为 200 或 302（不是 404）。
- `help`、`student/timetable`、`my/academic-calendar`、`student/newregistration/info`、`my/rfq`、`my/purchase`：**默认隐藏**（`_DEFAULT_HIDDEN_CARDS`），L2 不要求出现在 /my/apps 首屏，但 L1 必须可达。→ 建议脚本对这批用「L1 必须、L2 豁免」的标记。

**为什么值得做**：35 条里 6 张默认隐藏，人眼最容易漏的正是它们；且本仓历史上已有「隐藏≠删除」的约定（`_DEFAULT_HIDDEN_CARDS` 注释明说「隐藏≠删除，随时可开回」），用机器把这个约定钉住，比靠人记可靠。

**实现提示（对齐本仓冒烟写法）**：登录用 `POST /web/session/authenticate` + `requests.Session()`（见 `tests/smoke/downloads_v2_smoke.py` 的 `login()`），**不要用裸 curl**——裸 curl 不带 cookie 时 `/web/login?db=edu19` 会自跳 302（本文 §0.2）。
