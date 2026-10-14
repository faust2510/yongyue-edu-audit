# 课程中心排课入口设计（/my/study → 给学生和班级排课）
> **状态**：`在研` ｜ **主题**：`课程中心排课入口` ｜ **取代**：`—` ｜ **核对**：`2026-09-28`

> **本文性质**：**初版只有设计、零代码**（初版未改 `custom_addons/` 任何文件、未改 `openeducat_erp/`、未改任何数据库、未 git commit）。
> **实施现状（2026-09-28 追加）**：**P0（课程中心内嵌只读周课表）已实施并在本地 `edu19` 自证，未部署生产**（部署须用户确认）；**P1（课程中心内排课面板 + 「排课到人」）、P2（学生自助选时段）未开始**，仍阻塞在 §10 的用户确认。逐条见 §7.2 与 §13。
> **触发问题（用户原话）**：「这个**课程中心**这里我希望能够做成**给学生和班级排课**的功能。https://edu.example.org/my/study」
> **口径来源**：`docs/dev-workflow.md` 第 0 步（落地前查重）+ 六步闸门 ｜ `docs/research/scheduling-approaches.md`（铁律 0 产物）｜
> `docs/research/onestop-learning-and-repetitive-work.md` ｜ `docs/plans/timetable-design.md`（排课系统，已上线）｜
> `docs/plans/scheduling-overhaul-design.md`（排课链路改造，在研；§18 已实施）｜ `docs/plans/study-hub-v3-design.md`（课程中心来源，已上线）｜
> `docs/plans/enroll-v2-design.md`（学生自主报课，已上线）｜ `docs/plans/session-change-impact-design.md`（C-1，已上线）｜
> `docs/plans/class-batch-management-design.md` ｜ `docs/audit/task-B1-enroll-timetable-gap.md` ｜ `timetable_import/catalog.md`
> **取证时刻**：**2026-09-28**（本工作区）。读数口径：**本地 `edu19` 只读 SELECT**（`docker compose exec -T db psql -U odoo -d edu19`）+ **git 历史** + **逐行读源码**。
> ⚠ **本次未连生产**：凡引用「生产读数」的地方**一律显式标注来源文档与采集日**，不得当本次实测用（本仓规范：读数必须带采集时刻）。
> ⚠ **未验证项**集中在 §11，**不得当结论用**。**待用户确认的假设**集中在 §10。

---

## 0. 结论速览（TL;DR）

| 项 | 结论 |
|---|---|
| **一句话** | 「排课」在本仓**已经完整存在、且不止一套入口**（§3）：数据层 `op.session`、写路径 3 条、读路径 8 条、影响面/通知/留痕 4 件。**唯一确定缺失的**是：① 课程中心（`/my/study`）里**没有课表**（只有「下次：」一行）；② 全仓**没有「排课到人」**（`scheduling-overhaul-design.md:55` 明写不做）。 |
| **用户那句需求是三种解读** | **(甲) 把既有排课能力搬/暴露到 `/my/study`** ｜ **(乙) 在 `/my/study` 新增学生自助选课/选时段/选班级** ｜ **(丙) 让 `/my/study` 变成课表展示与订阅入口**。三者工作量与风险**差一个量级**（§4）。 |
| **倾向判断（★待确认，不是结论）** | **倾向 (甲)，且必然包含 (丙) 作为配套**；(乙) **不推荐**——因为「学生自助选课」**已经上线**（`/subject/enroll` + 教务审批），而「选时段」要先有「教学班/课次候选」层，**本仓没有 ⇒ 必须新建模型**，与零新模型口径正面冲突。 |
| **判断依据（5 条可查）** | ① 本仓语言里「**排课**」= 教务的 `op.session` 写入动作，而「**选课/报课**」有专门名字且已上线（`enroll.py:74`）；② 用户说的是「学生**和**班级」两个对象——**班级排课已存在**，「给学生排课」正是全仓唯一空缺；③ `/my/study` **不是学生专属页**（`edu_portal_templates.xml:162` 无角色守卫；教师/教务看到**全部科目**，`lms.py:26-27`），且**已经有一个教师/教务写入口**（设置课节会议链接，`study.py:342,377-387`）⇒ 把「排课」接在这里不需要新开页面；④ 顶部导航的「课表」指向 `/my/calendar`（`edu_portal_templates.xml:140`）而**不是**课表页，入口与内容不同名；⑤ 调研 `§8` 判定本项目为「全日制小班」，与高校两轮选课场景不匹配。 |
| **设计骨架（若 (甲)）** | **零新模块 / 零新模型 / 零新表 / 零新字段**：排课结果仍是 `op.session`；「排给学生」用**基座已有的** `op.session.student_ids`（`openeducat_timetable/models/timetable.py:60`，本地库 **0 行 = 从未使用**）；写路径**复用** `/timetable/bulk` 三步流；冲突判据**扩展现有唯一实现**而不是新写一套；通知/留痕**复用 C-1**；课表**复用** `/student/timetable` 与 `week_utils`。 |
| **权限口径（§7.5）** | **谁能排 = 教务组 + 系统管理员**（与后台 `op.session` 写权限同层）；**教师**只在课程中心编辑**自己任教课节**的会议链接（现状，不放宽）；**学生/家长只读**；门户写路由 **fail-closed 303**。**不新建组、不给门户组加后台菜单、不新增 ACL 行**（授权在控制器，见 §7.5 的接缝判定）。 |
| **最大风险（§9）** | 「**班级断点**」未解决：学生课表按 `op.student.course.batch_id` 过滤（`scheduling.py:152-155`），而生产真实课大量挂在**合班批**（`B1234` 等，`scheduling-overhaul-design.md` §18.5 生产只读读数）⇒ **即使做了课程中心课表，学生也只看到自己档案班那几节**。 |
| **待用户拍板** | **9 项**（§10 A1–A9；其中 **A1（三种解读取哪种）** 决定整个设计走向）。 |

---

## 1. 目标 / 非目标

### 1.1 目标

| # | 能力 | 用户感受（校长可见） |
|---|---|---|
| **G1** | **课程中心里看得见课表** —— `/my/study` 不再只有「下次：」一行，学生/家长/教师都能在本页看到本周安排，并一键进完整周课表或订阅 | 「在课程中心就把这周上什么看完了」 |
| **G2** | **课程中心里排得了课（教务）** —— 教务在课程中心按**班级**（沿用既有批量）或**个别学生**（新增「排课到人」）排课，不必切到后台 | 「给谁排课都在同一页，排完顺手就核对」 |
| **G3** | **排到人之后，学生看得见、教师看得见、有留痕** —— 复用 C-1 的收件人口径与通知体例，不新增第二条通知链 | 「给他加的那一节，他自己收到了通知」 |
| **G4** | **不新增第二个事实源** —— 排课的唯一事实源仍是 `op.session`；课表的唯一读口径仍是「按 `batch_id` / `faculty_id` / `student_ids` 过滤的 `op.session`」 | 「系统里只有一份课表」 |

### 1.2 非目标（明确不做，写清为什么）

- **不做求解器 / 自动排课**：与 `scheduling-overhaul-design.md` §1.2 同口径；`docs/research/scheduling-approaches.md` §2 已给出「生产系统实际选择的是局部搜索 + 人工可介入」，且我们**连数据都没备齐**（教室 100% 空、教师 1 位占位）。
- **不做学生自助「选时段 / 抢课」**：见 §4 (乙) 与 §7.4——它需要**先有**「教学班 / 课次候选」模型层，本仓没有；且 `op.session` 是**确定的一条课**，不是「有容量的教学班」。
- **不改报课链路**（`/subject/enroll` + 审批）：它与本设计**正交**（报课写 `op.student.course.subject_ids`，课表读 `op.session.batch_id`，见 `docs/audit/task-B1-enroll-timetable-gap.md` §0/§2）。
- **不改基座**：`openeducat_erp/` **只读**；冲突四查、向导、`op.session` 一律**继承/复用**，不就地改。
- **不新建模块**：落在既有 `custom_addons/edu_portal`（门户页所在）+ `custom_addons/edu_schedule`（排课能力所在）。
- **不碰红线**：不读写 `edu_telegram` / `edu.telegram.outbox` / `edu_feedback`（生产匿名意见箱，见 `docs/code-map.md` §4 与 `docs/audit/deprecated-inventory.md` §0.1）。
- **不动其他会话的在改文件**：`custom_addons/edu_life/*`、`custom_addons/edu_nav/*`、`edu_portal/controllers/batch2.py`、`edu_portal/views/edu_portal_templates.xml`、`scripts/gen_menu_data.py`、`tests/audit/out/*` —— **本次只读、未改**（`git status` 实测这些文件当前均为 modified，属他人工作区）。

---

## 2. 第 0 步①：先信 code-map（逐条锚点）

| 位置 | 内容 | 对本设计的含义 |
|---|---|---|
| `docs/code-map.md:121-122` | `edu_schedule` = 排课工具：`/timetable/bulk`→`/preview`→`/create`；`EduScheduleHoliday`；`OpSessionConflictExt`；**整周复制已于 2026-09-15 删除** | 排课侧改造**全部落在既有模块**，不新开命名空间 |
| `docs/code-map.md:74` | `controllers/scheduling.py`(854行) = 「学生视角课表」 | **课表已经在门户里**，本设计只做「接进课程中心」 |
| `docs/code-map.md:257` | `/my/study`（课程中心：课节/入会/资料/成绩）、`/my/study/<id>`、`/my/study/session/<id>/join` 属 **v3 新增** | 课程中心是**已上线的既有页**，改它 = 改既有件，不是新建 |
| `docs/code-map.md:241` | 路由速查「排课」= `/timetable/bulk*`（`edu_schedule/main.py`）+ `/student/timetable`（`edu_portal/scheduling.py`） | 两条线就是全部排课入口 |
| `docs/code-map.md:274-281` | **权限四层**硬约定（§6 第 12 条） | 新增菜单/ACL/路由**必须声明属于哪一层**（§7.5） |
| `docs/code-map.md:283-286` | **身份反查只有一条口径** = `edu_schedule/models/identity.py`（§6 第 13 条） | 排课到人要用它，**禁止**再写 `search([('user_id','=',uid)])` |
| `docs/code-map.md:155` | 依赖方向 `edu_schedule──> openeducat_timetable, website`（**不依赖 edu_portal**）；`edu_portal` 依赖 `edu_schedule` | 模型层共享件只能落 `edu_schedule`；门户页落 `edu_portal` |
| `docs/code-map.md:303` | 门禁脚本族（`check_english` / `check_view_xpath` / `check_qweb_dict_foreach` / `check_docs_index`） | 实施时 verify 默认带 `check_view_xpath.py`（新增模型/`_inherit` 的默认口径） |
| `docs/dev-workflow.md:6-81` | **第 0 步：落地前查重**（① 查 code-map ② 查同义模型/入口 ③ 写进设计摘要 ④ 查升级是否动业务数据 ⑤ 演示数据策略）与「查到重复怎么办」三步 | 本文 §3 = ②③，§5 = ④⑤，§12 = 台账登记 |

---

## 3. 既有排课能力清单（★交付物①：file:line + 能做什么 + 谁在用）

> 口径：**行号取自本次实读**（2026-09-28，工作区 HEAD `86d10a6`）。凡「生产读数」均标注来源文档与采集日。
> 分类：A 数据层 → B 写路径 → C 读/展示路径 → D 影响面·通知·留痕 → E 数据来源 → F 入口与菜单 → G git 史实核对 → H 负结论。

### A. 数据层（模型 / 表）—— **全部是基座或既有自研，零重复**

| # | 位置 | 载体 | 能做什么 | 谁在用 |
|---|---|---|---|---|
| A1 | `openeducat_erp/openeducat_timetable/models/timetable.py:27` | `op.session` | **排课的唯一事实源**：一条 = 某班某科目在绝对起止时间的一节课（+ 教师/教室/时段） | 排课工具、4 视角课表、C-1 影响面、课程中心「下次课」、ICS、校历 |
| A2 | 同上 `:60` | `op.session.student_ids`（m2m `op.student`） | **「课节到人」的原生载体**（表 `op_session_op_student_rel`）；基座 `create()` 会据此自动 **subscribe follower + 按 `_NOTIFY_WORTHY_FIELDS` 发通知** | 基座通知链；**本地库 `op_session_op_student_rel` = 0 行 ⇒ 从未被使用**（本次实测） |
| A3 | 同上 `:245-337` | `check_timetable_fields`（`@api.constrains`） | **冲突四查**：教师 / 教室 / 班级 / 班级+科目；同班同科才算「班级+科目」；`state='cancel'` 不参与；两端严格 `<`（首尾相接不算冲突） | 任何写 `op.session` 的路径（写入即拦） |
| A4 | 同上 `:507` | `_NOTIFY_WORTHY_FIELDS`（8 字段白名单）+ `:342-390` 自动订阅 | 基座「值得通知」字段集；`student_ids`/`faculty_id` 变更会重新平衡 follower | 基座通知；C-1 的 `IMPACT_WATCH_FIELDS` 与其**同集合**（已是既有事实） |
| A5 | `openeducat_erp/openeducat_timetable/models/`（`op.timing`） | 节次定义（第 N 节 + 起止 + 时长） | 门户课表的**行**；周期排课的时段下拉 | `scheduling.py:225-241` 矩阵、`main.py:171-214` 解析 |
| A6 | `custom_addons/edu_schedule/models/holiday.py:22` | `edu.schedule.holiday._matches(day, batch_id)` | 停课日判定（班级留空 = 全校停课） | 周期排课跳过、课表灰显、批量停用提示 |
| A7 | `custom_addons/edu_schedule/models/session_ext.py:94,97` | `conflict_kind` / `conflict_color`（`store=False`） | 冲突**分色**（教师红 / 教室橙 / 班级琥珀），Integer 0–3 走 Odoo calendar 色板 | 后台日历/列表视觉 |
| A8 | 同上 `:167-174` | `calendar_event_id` / `meeting_url`(related) / `reminder_sent_at` | **课节级**会议链接（存原生 `calendar.event.videocall_location`）+ 课前提醒水位 | 课程中心「进入会议」、「还有 N 分钟可入会」 |
| A9 | 同上 `:202` / `:232` | `set_meeting_url()` / `join_state()` | 链接写入（http/https 归一化）/ 入会态（`has_url`/`ready`/`label`） | 教师/教务设链接；学生入会 |
| A10 | 同上 `:402` / `:433` | `IMPACT_WATCH_FIELDS` / `_impact_flags()` | 改课留痕字段集 / **读四个 `timetable.is_*_constraint` 系统参数**（判真值口径照抄基座：`'False'` 亦为真） | C-1 影响面与预检、多班预检 |
| A11 | `custom_addons/edu_portal/models/scheduling.py:19,23` | 事务级 `pg_advisory_xact_lock(872401)` | **并发兜底**：`op.session` 的 `create`/`write` 串行化（基座四查是纯 Python constrains，并发可双穿） | 所有写路径 |

> **结论 A**：**没有任何自研排课模型**。「排课 = 写 `op.session`」是本仓**唯一**的事实源口径。

### B. 写路径（谁在排课）—— **3 条 + 1 条一次性导入，全部「按班排」，无「按人排」**

| # | 位置 | 入口 | 能做什么 | 谁在用 |
|---|---|---|---|---|
| B1 | `custom_addons/edu_schedule/controllers/main.py:669` `GET /timetable/bulk` → `:698` `POST /preview`（**不落库**）→ `:733` `POST /create` | **门户周期排课三步流**（★主力） | 单科目 × 多班 × 多周次；周次范围 / 单双周 / 停课日跳过 / 自定义起止时间（按一刻钟对齐）/ 课程与科目**行内新建**；**落库前周矩阵预检**（红/灰格）；批量审计 | **教务组 + 课表 manager**；菜单 603 |
| B2 | `main.py:780-833` `_create_multi`（§18，`1ec787f` 已上线） | 同上页，勾 ≥1 个班 | **多班批量 + 时间自动错开**（第 i 班 = 首班 + i×每班间隔；默认间隔 = 一个课时长度）；**一条冲突就整批拒绝**（不写一半）；本批已生成的课节参与后续班判定 | 教务（「各年级分开排」的落地手段） |
| B3 | `main.py:262-298` `_slot_conflict_dims` | **本模块唯一的重叠判定实现** | 返回 `['faculty','classroom','batch_subject','batch']` 子集；`:300` 的 `_slot_conflicted` 只是它的 bool 薄封装（**禁止写第二套判据**） | 预检（B1/B2） |
| B4 | `openeducat_erp/openeducat_timetable/wizard/generate_timetable.py:30-133`（菜单 **344 生成时间表**） | **基座向导** | 课程+班级 → **7 天网格 × 每天多行**（教师/科目/时段/教室各一），一次生成整批 | 菜单 `ir_ui_menu_group_rel` 本地实读**仅 gid=60**（`group_op_timetable_manager`）；教务组 40 隐含 60 ⇒ 教务**能打开**（`scheduling-overhaul-design.md` §9.1 实测） |
| B5 | 后台 `op.session` 表单/日历/列表（`edu_schedule/views/session_conflict_view.xml`，priority=1 压过上游英文视图） | **单节改删** | 改时间/教师/教室/停用；日历拖拽 | 教务 / 管理员 |
| B6 | `timetable_import/import_sessions.py`（+ `parse_timetable.py` / `normalize_sessions.py`） | **一次性 CSV 导入** | 从 `2+6排课表.xlsx` 契约导入；`--dry-run` 先验；幂等判重；教师占位「待定」、教室留空 | **生产 216 节全部来自这条线**（`timetable_import/PRODUCTION_CHECKLIST.md`；`scheduling-overhaul-design.md` §6.1 生产只读读数，采集 2026-09-18） |

> **结论 B**：写路径**只有 3 个**（门户三步流 / 基座向导 / 后台单节），**且没有任何一条能「排给某个学生」** —— `student_ids` 从未被写过（A2）。

### C. 读 / 展示路径（谁在看课表）—— **8 条，其中 2 条就是课表**

| # | 位置 | 入口 | 角色与数据域 | 说明 |
|---|---|---|---|---|
| C1 | `custom_addons/edu_portal/controllers/scheduling.py:130` `/student/timetable` | **周课表（四视角）** | 学生 = `batch_id`（`:152-155`）；教师 = `faculty_id`（`:149-151`）；家长 = 孩子班级合集（`:156-165`）；内部 = **全校只读**（`:166-167`）；**裸门户账号 = 空表**（`:168-171`，不泄露全校数据） | 周/日视图、上周/本周/下周、今天高亮、第 N 周（学期锚点）、停课灰显、「未分节」桶；`:198-202` **已补 `state != 'cancel'`** |
| C2 | `custom_addons/edu_portal/controllers/study.py:273` `/my/study` | **课程中心**（★用户点名的页） | `_subjects_for`：学生 = `op.student.course.subject_ids`；教师/内部 = **全部科目**；家长 = 孩子档案科目（`lms.py:22-44`） | 每科目一张卡：教师、**「下次：」一行**、最近 N 节、资料数、成绩百分比、出勤统计（页首） |
| C3 | `study.py:323` `/my/study/<subject_id>` | 单科目一页 | 同上 + `can_edit_link = fac or privileged_staff()`（`:342`） | 最近/下次课节（各 ≤5）、资料、成绩三层 |
| C4 | `study.py:351` `/my/study/session/<id>/join` | 一键入会 | 学生/家长**限本班**（`:358-364` 防拼 URL） | 时间窗未到 → 等待页；到点 → 302 到 `videocall_location` |
| C5 | `study.py:377` `POST /my/study/session/<id>/link/save` | **课程中心里既有的写入口** | 门禁 = `current_faculty() or privileged_staff()`（`:381-382`） | 教师/教务设会议链接 —— **证明课程中心已不是纯学生页** |
| C6 | `custom_addons/edu_portal/controllers/calendar.py:343` `/my/calendar` | 校历三视图（月/周/列表） | 四角色 | 与课表**不同页**（不同名不同物） |
| C7 | `custom_addons/edu_portal/models/ical.py:101` `/my/calendar/ics/<token>`（`auth='public'` + token） | **iCal 订阅** | 手机/Outlook/Google 订阅后自动同步课表、考试、停课、活动 | `res.users.edu_ical_token`（`ical.py:15`）；**本仓差异化点之一** |
| C8 | `custom_addons/edu_portal/controllers/lms.py:22-44` `/my/courses` | LMS 课程/课次 | 学生 = 档案 `subject_ids` | ⚠ 与 C1 的 `op.session` **不同源**：这是「报课产物」不是「课表」 |

> **结论 C**：**「课表」这件事在门户里已经有两处**（C1 周课表 + C7 订阅），**唯独课程中心（C2）没有周课表** —— 只有每科「下次：」一行，加一个快捷入口 `/student/timetable`（`views/study.xml:343`）。**这正是用户看到的那一幕。**

### D. 影响面 · 通知 · 留痕（改课之后的事）

| # | 位置 | 能力 | 口径 |
|---|---|---|---|
| D1 | `main.py:891` `GET /timetable/session/<id>/impact` + `session_ext.py:470-514` `_impact_related()` | **改课影响面**：受牵连的其他课节 + 维度标签 + **判词两档**（「保存会被系统拦下」/「不会拦，但人是受影响者」） | 口径逐条对齐基座 `check_timetable_fields`（不调用它——它是 constrains） |
| D2 | `session_ext.py:566-579` `_impact_recipients()` + `:259-282` `_session_student_users`/`_reminder_users` | **收件人清单**：任课教师 + 该班**全部在读学生**，**家长不发**；`student_ids` 为空时按 `op.student.course` 的 batch **回退** | ⚠ 本地库 `op_session_op_student_rel` = 0 ⇒ **这条回退是活路径**，不是兜底 |
| D3 | `main.py:921` `POST /timetable/session/<id>/notify` + `session_ext.py:676-739` `_notify_session_change()` | **一键通知**：站内信 `edu.message._notify_event('session_change', …)`；**逐人计数（成功/静音/失败三分）**；每次写一条 `edu.audit.log('课节变更通知')` | 幂等：允许补发；页面「最近一次通知」由审计表回答（`session_ext.py:603-629`，零新字段） |
| D4 | `session_ext.py:745-782` `op.session.write()` 钩子 | **字段级留痕**：`IMPACT_WATCH_FIELDS` 变更 → `edu.audit.log('课节变更')`，old→new 摘要 | 失败只告警、绝不阻断业务事务 |
| D5 | `main.py:837` `GET /timetable/batch/<id>/deactivate` + `:865` `POST …/confirm` + `session_ext.py:906-999` | **批量停用**（`state='cancel'`，**不删行**）+ 影响面先行 + 二次确认（**服务端**判据）+ 审计 `'课节批量停用'` | 复用 D2 收件人口径；停用后课表**立即不可见**（C1 的 `:198-202` 因此补过） |
| D6 | `session_ext.py:828-882` `OpBatchGradeSplit._deactivate_composition()` | **合班批 → 年级组成推导**（`B1234 → B1/B2/B3/B4`） | **推导 ≠ 事实**，一律带 `need_confirm=True`，页面必须显式标注「推导，需人工确认」 |

### E. 数据来源（排课数据从哪来）

| # | 位置 | 说明 |
|---|---|---|
| E1 | `timetable_import/catalog.md` **§0 三条铁律** | ① 文26下 = B 部唯一权威源（B12 课次**全部弃用**）；② `L1–L18` = **课次编号不是周次**；③ `A1/A2/A3` = 神学部年级班、`B1–B4` = 人文部年级班，`A123`/`B34`/`A123B34` 等 = **合班组合** |
| E2 | `timetable_import/parse_timetable.py` → `normalize_sessions.py` → `import_sessions.py --dry-run` → 生产导入 | **已跑通过一次的路径**（`scheduling-overhaul-design.md` §12.2 裁定「照抄，不要另造导入器」） |
| E3 | 本地实测（2026-09-28，只读 SELECT） | `op_session` = **288**（`cancel` 0 / `draft` 266）；distinct batch **14** / subject **22** / faculty **2**；`classroom_id` 空 **277/288**；`op_session_op_student_rel` = **0**；`op_batch` **17**（全 active）；`op_student` **6**；`op_student_course` **4**（running **1**）；`op_subject_registration` **12**；`op_subject` **148**；`op_course` **7** |
| E4 | 按班分布（本地实测，节数从多到少） | 预备科·2026级【演示】72 ｜ B3 40 ｜ B34 27 ｜ A123 23 ｜ B1234 18 ｜ B1 18 ｜ B234 15 ｜ A123B1 15 ｜ B4 15 ｜ A123B234 12 ｜ A23B34 12 ｜ A123B34 11 ｜ A23 6 ｜ A1 4 ｜ **A2 / A3 / B2 = 0** |
| E5 | 生产读数（**引用**：`scheduling-overhaul-design.md` §6.1–§6.3 / §18.5，采集 **2026-09-18**，**本次未复核**） | `op_session` 216（100% draft）；覆盖 18 科目 / 13 班 / **1 位教师（占位「待定」）** / **0 间教室**；`op_batch` 19 中**有在读学生的只有 1 个**；`op_subject_registration` 1 条（`SR0017` `submitted`，payload 21 必修、**排课数 0**） |

### F. 入口与菜单现状（本地实读，2026-09-28）

| # | 位置 | 内容 |
|---|---|---|
| F1 | `edu_schedule/views/menu.xml:11-16` | 菜单 **603「周期排课（批量）」**（`ir.actions.act_url 742` → `/timetable/bulk`），`groups = group_op_timetable_manager, group_op_back_office_admin`，parent = `openeducat_timetable.menu_op_timetable_root` |
| F2 | 同上 `:17-22` | 菜单「停课管理」→ `edu.schedule.holiday` |
| F3 | 本地 `ir_ui_menu` 实读 | **341 时间表**（根，action 456）→ **342 时间表** → **344 生成时间表**（基座向导）；**603 周期排课（批量）**（parent 341）。⚠ 603 的 `name` 只有 `en_US`（**无 zh_CN**）⇒ 中文界面下走 en_US 回退 |
| F4 | `edu_portal/views/edu_portal_templates.xml:140` | 顶部导航「**课表**」→ **`/my/calendar`**（不是 `/student/timetable`！） |
| F5 | 同上 `:162` | 顶部导航「**课程中心**」→ `/my/study`，**无 t-if 角色守卫**（所有角色可见） |
| F6 | `edu_portal/views/study.xml:343` | 课程中心**间接**入口：`/student/subjects` 页的「下一步四件事」① 看课表已更新 → `/student/timetable` |
| F7 | `edu_portal/controllers/batch2.py:264,460,470,480,492,1018,1021` | 宫格/卡片里的「时间表 / 课表 / 教学安排 / 孩子的课表 / 全校课表」→ `/student/timetable`；「课程中心」→ `/my/study` |
| F8 | **门户无排课入口**（硬事实） | `/timetable/bulk`、`/timetable/bulk/preview`、`/timetable/bulk/create` 三条**全部** `require_internal()`（`main.py:56-58`）⇒ 门户账号（含学生）**303 回 `/my/home`**（`:671-672`、`:701-702`、`:736-737`）；`/timetable/batch/*/deactivate`（`:845-848`）、`/timetable/session/*/impact`（`:900-901`）、`/timetable/session/*/notify`（`:930-931`）同样内部+教务双门禁 |
| F9 | `edu_schedule/security/ir.model.access.csv` | **只有 2 行**：`edu.schedule.holiday` 给 `group_op_timetable_manager` 与 `group_op_back_office_admin`（1,1,1,1）。`op.session` 的 ACL 来自基座 |
| F10 | `edu_portal/controllers/help_center.py:18,24` | 帮助中心教师卡 desc 写「周期排课、**整周复制**」（**整周复制已于 2026-09-15 删除** ⇒ 文案滞后，见 §3 H2）；教务卡 desc「开学排课全流程」 |

### G. git 史实核对（★用户点名「用 git log 查证它们实际做到了什么」）

> 命令：`git log --pretty=format:'%h|%ad|%s' --date=short -1 <hash>`（逐条实跑，2026-09-28）

| 提交 | 日期 | **实际做到了什么（可复核）** | 没做到什么 |
|---|---|---|---|
| `7640444` | 2026-08-25 | `feat(life+eval+schedule)`：**批量排课首次落地**（三大模块 + 门户集成） | 无 C-1、无多班、无停课日 |
| `0303036` | 2026-08-25 | 并入**时间表应用菜单**；**停课日管理**（批量排除 + 复制跳过）；课程/科目**行内新建**；自定义上下课时间 | — |
| `393f8ab` / `727a6f9` | 2026-08-25 / **2026-08-28** | 后台「排课」菜单（教务处可见）；**钉钉式排课改造 S1 冲突分色 / S2 周期排课增强（周次范围·单双周）/ S3 复制预览 / S4 周课表（周/日视图·今天·第N周·停课灰显）/ S5 校历三视图 / W1 常用区 / W2 编辑排序** | 格子/拖拽排课 |
| `77b0b75` | **2026-09-15** | **删除**「整周复制」`/timetable/copy`（用户裁定：与周期排课重叠、**生产从未使用**）→ 三条路由 404 + 四辅助方法 + 三模板 + 菜单两条 | ⚠ **文案残留未清**（见 §3 H2） |
| `5da2270` | **2026-09-18** | **C-1 改课影响面与变更通知**（本设计要复用的核心资产） | — |
| `1ec787f` | **2026-09-18** | **§18 各年级分开排**：① 多班批量排课（**时间自动错开**）② 旧合班课时**批量停用**（不删行）③ 课表页补 `state != 'cancel'` ④ 冒烟 `tests/smoke/schedule_grade_split.py`（V20–V25） | **§7 先排课后报课 / §8 降本三件 / §10 教师不可用 / §12 人工排课路径 四件未实现**（`docs/plans/README.md:42` 待办 ② 明记「主体四件未实现」） |
| `f0d9226` | 2026-09-18 | `fix(edu_portal)`：**课表日视图 `d=` 日期解析静默失效**修复（`Datetime.to_date` 在 Odoo 19 不存在 ⇒ 恒回落今天）+ 教师账号身份解析 | — |
| `c34a01b` | 2026-09-21 | 文档：补三条已核实事实（`op.session.subject_id required` / register 粒度冲突 / A→B 导流） | — |

> **史实结论**：git 历史证明「**按年级排课**」（`1ec787f`）与「**批量排课**」（`7640444`/`727a6f9`）都是**教务侧**能力，**没有一次提交让「学生」成为排课的主体或对象**。用户点名的几条，实际做到的都落在 §3 的 B/E/F 里；**「给学生排课」在 git 历史里零命中**。

### H. 负结论（写清搜索范围与方式，可复现）

| # | 负结论 | 搜索范围与方式（原样可复现） |
|---|---|---|
| H1 | **全仓没有「排课到人」** | ① `grep -rn "学生排课\|自助排课\|给学生排课\|排课到人\|个性化课表" docs/` = **1 命中**，且是**否定式**：`docs/plans/scheduling-overhaul-design.md:55`「**不做**"排课到人"（单个学生的个性化课表排课）：一对一场景本项目不存在」；② `op_session_op_student_rel` 本地 **0 行**（实测）；③ 三条写路径（B1/B2/B5）无一处写 `student_ids`（逐行读） |
| H2 | **「整周复制」已删除但文案未清**（既有实况不一致，非本设计引入） | `grep -rn "整周复制"` 全仓 **20 命中**，其中**非文档**的有：`README.md:60`、`edu_schedule/__manifest__.py:4,5`（summary+description）、`edu_schedule/views/templates.xml:25`、`edu_schedule/views/holiday_views.xml:41`、`edu_schedule/models/holiday.py:2`、`edu_schedule/models/week_utils.py:2`、`edu_portal/views/scheduling.xml:106`、`edu_portal/views/help_center.xml:240`、`edu_portal/controllers/help_center.py:18`、`edu_portal/models/audit.py:5`、`edu_portal/controllers/batch2.py:1918`（注释）⇒ 删除提交声明清了「帮助中心该节/手册/回归/路由矩阵」，**实际残留 12 处面客/面开发者文案** |
| H3 | **门户没有排课入口**（不是「有但隐藏」） | ① F8 逐条读 `require_internal()` 与 `privileged_staff()`；② `grep -rn "/timetable/" custom_addons/edu_portal/views/` 只命中 `timetable/bulk` 卡片（`batch2.py:155,264` 教师/教务侧） |
| H4 | **课程中心无周课表** | 逐行读 `study.py:273-387`：`/my/study` 只取 `_sessions_of()`（`:43-57`，subject+batch，各 ≤5 条）并经 `_session_rows()`（`:68-84`）输出「下次：/最近：」；**无周矩阵、无星期列、无时段行**（对比 `scheduling.py:224-250` 的 `matrix`/`loose`） |
| H5 | **没有第二套冲突判定** | `grep -rn "conflict_kind\|conflict_color\|_overlaps\|_slot_conflict" custom_addons/` ⇒ 唯一活实现 = `session_ext.py:104-156`（展示定级）与 `main.py:262-298`（预检判定）；`main.py:270-274` 明文自述「**本方法是本模块唯一的重叠判定实现**」 |
| H6 | **没有第二套周口径** | `grep -rn "def monday_of\|def week_no_of\|def term_anchor\|def week_window_utc"` ⇒ 唯一实现 = `edu_schedule/models/week_utils.py:18/23/30/88`，被 `main.py:27-30` 与 `scheduling.py:23-25` 两处 import |
| H7 | **没有第二套「谁该收到改课通知」** | `grep -rn "_reminder_users\|_session_student_users"` ⇒ 唯一实现 `session_ext.py:259-292`；C-1 影响面（`:572`）与批量停用（`:893`）**两处都复用它** |
| H8 | **没有「教学班 / 课次候选 / 容量」层**（(乙) 的关键缺口） | ① `op.session` 无容量字段（逐行读 `timetable.py:27-160`：无 `capacity`/`max_seats`）；② `grep -rn "capacity" custom_addons/edu_portal/models/` ⇒ 容量语义只出现在**科目**上（`op.subject.capacity` + `edu.subject.prereq._edu_enrolled_count`，`enroll.py:180`），与**时段**无关；③ `docs/research/scheduling-approaches.md` §7 明记本仓「**没有选课层**（只有班级预注册）」——**该结论已被 `enroll-v2` 部分推翻**（科目级选课已上线），但「选时段」仍然没有 |

---

## 4. 用户那句需求 = 三种解读（★交付物②）

> 用户原话：「这个**课程中心**这里我希望能够做成**给学生和班级排课**的功能。https://edu.example.org/my/study」
> 同一句话至少有三种落法，**工作量与风险差一个量级**。下面**逐条分开写**，并给出「需要什么信息才能定」。

### 4.1 (甲) 把**已有**排课能力（现在教务在后台/工具页做）**搬/暴露到** `/my/study`

| 项 | 内容 |
|---|---|
| 一句话 | 课程中心从「看」变成「**既能看也能排**」：教务（或教师在受限范围内）在课程中心里对**班级**或**学生**发起排课，写路径仍是既有的 `op.session` |
| 现状支撑 | `/my/study` **已是角色感知页**（`lms.py:22-44`：教师/内部见全部科目）；`/my/study/<id>` **已有教师/教务写入口**（`study.py:342,377-387` 设会议链接）；排课能力已有 3 条写路径（§3 B） |
| 现状阻碍 | ① `/timetable/bulk*` 三条路由**门户一律 303**（F8）⇒ 「搬」意味着**要么放宽既有门禁，要么在 `edu_portal` 侧新建同能力写路由**（后者 = 第二个入口 ⇒ 触第 0 步「查到重复」）；② 「给学生排课」需要写 `op.session.student_ids`，**基座四查不含学生维**（A3 只有教师/教室/班级/班级+科目）⇒ 必须**扩展现有唯一判据**（H5） |
| **需要什么信息才能定** | ① **谁能在课程中心排课**？（教务独占 / 教师可排自己班的 / 学生自己申请）——决定权限层；② 暴露的是「**入口跳转**」还是「**页面内嵌表单**」——决定是否产生第二个写入口；③ 「给学生排课」是不是要能**改时间/教师/教室**，还是只在既有班级课上**加人**（前者 = 全量排课能力，后者 = 一句 `student_ids` 写） |
| 工作量 | **小–中**（若只做「跳转预填 + 按人加课」≈ 2 个文件；若要在课程中心内嵌完整排课表单 + 学生维预检 ≈ 4–6 个文件） |
| 风险 | **中**：唯一真风险是**权限面**——本仓四层硬约定（`code-map.md:274-281`）明确「写业务管理只给教务组」，把排课搬进门户若被读成「放开学生」，就是越权（`main.py:56-58` 那一个 `require_internal()` 是**全部门禁**） |

### 4.2 (乙) 在 `/my/study` 里**新增**「选课 / 选时段 / 选班级」类的**学生自助排课**

| 项 | 内容 |
|---|---|
| 一句话 | 学生自己在课程中心挑课/挑时段/挑班级，系统按容量与冲突落成课表 |
| **关键既有事实** | **「学生自助选课」已经上线**：`GET /subject/enroll`（`enroll.py:74-225`，课程/班级/科目三级选择 + 先修/学分/容量预检 + F6 blocker 渲染）→ `POST /subject/enroll/save`（`:230-326`，建 `op.subject.registration` `state=submitted` + 审计）→ 教务审批 `/registrar/subject/approvals[/<id>][/set_state]`（`:359-582`）+ 批量（`:587-672`）→ `action_enroll_approve()`（`edu_portal/models/registration.py:165-230`，**把科目写进 `op.student.course.subject_ids`**）。设计 `docs/plans/enroll-v2-design.md`（索引标 **已上线**） |
| 所以 (乙) 的增量不是「选课」 | 而是「**选时段 / 选班次 / 选班级组合**」——**选班级**其实也已存在（`/subject/enroll` 的 `course_id × batch_id` 三级选择，`enroll.py:99-146`）。**真正缺的只有「选时段/选班次」** |
| 「选时段」的硬前置 | 需要「**同一门课有多个候选时段/教学班 + 容量 + 抽签**」这一层。本仓：① `op.session` 无容量（H8）；② 容量只挂在**科目**（`op.subject.capacity`）；③ 无「教学班」实体。⇒ **必须新建模型**，与**零新模型口径**正面冲突 |
| 行业口径（回引调研） | `docs/research/scheduling-approaches.md` §7.1（一手 URL：西北大学/上海交大/西电教务处通知）：中国高校事实标准是**两轮制——预选（志愿优先/超容量抽签，且与提交时间无关）→ 正选（即选即得）**，且「**时间片冲突检测必须在填志愿时给**」；§9 第 3 件把它列为「最值得抄的 3 件事」之一 |
| **需要什么信息才能定** | ① 用户要的到底是「选**科目**」（已有）/「选**时段**」（须新建模型）/「选**班级**」（部分已有）；② 是否需要在**同一门课的多个时段间**做选择——若不需要，(乙) 直接退化为「既有报课 + 时段冲突提示」；③ 容量与公平性：先到先得 / 抽签（决定是否要并发与随机机制） |
| 工作量 | **大**（新模型 + 容量 + 两轮状态机 + 时间冲突前置 + 并发削峰） |
| 风险 | **高**：新事实源（第二个「学生的课」来源）会与 `op.student.course.subject_ids`（报课，LMS 读它）和 `op.session.batch_id`（课表读它）**三足鼎立**——本仓已经有「报课 ≠ 课表」这一处断点（`task-B1-enroll-timetable-gap.md`），再引入第三个来源会让「学生到底上什么」彻底说不清 |

### 4.3 (丙) 让 `/my/study` 变成**课表的展示与订阅入口**（学生看自己的课表）

| 项 | 内容 |
|---|---|
| 一句话 | 课程中心页内嵌课表（本周摘要 / 完整），并给订阅出口；**不新增任何写路径** |
| 现状支撑 | 读路径**已齐**：周课表 `/student/timetable`（C1，四视角 + 周/日 + 停课灰显 + 第 N 周）、校历 `/my/calendar`（C6）、**iCal 订阅**（C7，`auth='public'` + token）、周口径工具 `week_utils`（H6） |
| 现状缺口 | 课程中心**没有周课表**（H4）：每科目只有「下次：」一行 + 一个指向 `/student/timetable` 的快捷入口（`study.xml:343`），而**顶部导航的「课表」指向 `/my/calendar`**（F4）⇒ **入口与内容不同名**，学生（与提需求的人）自然会在「课程中心」里找课表 |
| **需要什么信息才能定** | ① 课程中心里要的是「**本周摘要**」还是「**完整周视图**」（前者 ≈ 30 行模板，后者建议**直接复用 `/student/timetable`** 只加跳转）；② 是否要**把导航里的「课表」改指课表页**（F4 的 `/my/calendar` 与「课表」名实不符）；③ 家长视角要不要（孩子合集口径已在 C1 里实现） |
| 工作量 | **小**（≈ 1 控制器 + 1 模板 + 1 快捷入口；零写路径、零新模型、零权限变更） |
| 风险 | **低**：只读；但**它会把「班级断点」暴露给学生**（§9 R1/R9）——现在看不见，做完就看得见「我只有 2 门课」 |

### 4.4 我的倾向判断（**★明确标注：这是待用户确认的假设，不是结论**）

**倾向排序：(甲) ≈ (丙) > (乙)；且 (甲) 若成立必然包含 (丙) 作为配套。**

**依据（逐条可查，不用「我记得」）**：

1. **用词**：本仓语言里「**排课**」是一个**有明确含义的教务动作**（写 `op.session`，§3 B）；而「**选课/报课**」有**专门名字且已上线**（`/subject/enroll`，「报课选科」，`enroll.py:74`；导航文案「报课选科」见 `edu_portal_templates.xml:145`）。用户说的是「排课」不是「选课」⇒ 弱化 (乙)。
2. **对象**：「给学生**和班级**排课」——**班级排课已完整存在**（§3 B1/B2/E4：本地 14 个班有课）。**「给学生排课」（排课到人）恰是全仓唯一的空缺**（H1：`op_session_op_student_rel` 0 行；`scheduling-overhaul-design.md:55` 明写不做）⇒ 这句话的**增量**落在「学生」那一半，指向 (甲) 的「排课到人」形态。
3. **页面**：用户给的是 `/my/study`——**页面级诉求**。而该页 **不是学生专属**（F5 无角色守卫；`lms.py:26-27` 教师/教务见全部科目），且**已有教师/教务写入口**（C5 设会议链接）⇒ 「把排课接进这一页」在结构上没有障碍，也不需要新开页面。
4. **它缺什么**：课程中心当前唯一的「课」信息是每科目一行「下次：」（H4）。**一个「排课」功能做进去之后，第一件要能看见的就是课表** ⇒ (丙) 是 (甲) 的必然配套，不是另一个方案。
5. **反面证据（弱化 (乙) 那条，给足）**：`docs/research/scheduling-approaches.md` §7.1/§9 确实把「学生选课两轮制 + 时间冲突前置」列为最值得抄的第 3 件；但**同一份调研** §8 的场景判定把本项目归为「**全日制小班**」（班级固定、教师流动），而两轮抽签是**高校学分制**的事实标准 ⇒ **场景不匹配**，且 (乙) 的代价是**第三个事实源**（§4.2 风险）。
6. **入口名实不符（支持 (丙) 的独立证据）**：导航「课表」指向 `/my/calendar`（F4，「校历」另有一条 `/my/calendar` —— 同一路由两个名字），而真正的周课表 `/student/timetable` 在课程中心里**不可直达**（只有 `/student/subjects` 的「下一步四件事」里有一条，F6）⇒ 用户「在课程中心找不到课表」是可复现的现状。

**这句话我判断不出、必须要用户回答的**（⇒ §10 A1）：用户说「排课」时，脑子里的**动作主体**是「**教务给谁排**」还是「**学生自己排/挑**」。这一条会**完全决定**设计走向。

---

## 5. 第 0 步④⑤：升级会不会动业务数据 / 演示数据策略

### 5.1 ④ 本设计是否向业务表写数据

**结论：本文零代码 ⇒ 无任何升级副作用。** 实施时必须遵守（照 `dev-workflow.md` 第 0 步 ④）：

1. `edu_portal` / `edu_schedule` 的 `data/` **只允许**配置类记录（视图 / 菜单 / ACL / `ir.config_parameter` / `ir.actions`）。**任何写 `op.session` / `op_session_op_student_rel` / `edu.audit.log` / `edu.message` 的 `<function>` 一律禁止进 `data/`**（依据：`dev-workflow.md` 第 0 步 ④ + `docs/audit/finding-F5-edulife-demo-injection.md`：`-u edu_life` 会按滚动窗口补写业务表）。
2. 本设计**不需要任何回填迁移**（`op.session.student_ids` 是既有字段，空 = 未使用；**不得**为了让页面好看而回填）。
3. ⇒ 实施后预期 `-u edu_portal` / `-u edu_schedule` 的**业务数据副作用 = 0**；验收必须能断言「升级前后 `op_session` / `op_session_op_student_rel` 行数不变」。

### 5.2 ⑤ 演示数据策略（一句话）

**不新增演示业务数据**；真机验证用「造一节真课 + 改回原值」的三段模板（① 绕过被测路径 → ② 读真正的产物 → ③ 还原并断言 `leftover=0`，`dev-workflow.md`）。
若确需样本（本地「有学生的班 × 有课时的科目 × 有登录账号的学生」组合不齐 —— 本地实测 `op_student_course` running 仅 **1** 行）：放 `scripts/seed_*.py`（**幂等**）、名字带 **【演示】**、脚本自带 `--clean` 按标记 `unlink` 并断言计数归零；**禁止**放进 `data/`。既有先例可照抄 `tests/smoke/schedule_grade_split.py:41`（`MARK = 'SPLITDEMO'`，只建只删自己的记录、断言 `leftover = 0`）。

---

## 6. 第 3 步「读参考」：学什么 / 砍什么（回引调研）

### 6.1 回引 `docs/research/scheduling-approaches.md`（第 4 步硬要求）

| 调研结论（节） | 我们的现状 | 本设计的落点 |
|---|---|---|
| §0 四层模型（求解器 / 数据模型 / **交互层** / 选课层）；「用户说'麻烦'指的就是交互层」 | 我们第 ① 层最粗糙版本；第 ③ 层几乎为零 | 本设计**不动交互层**（§1.2 非目标）；只补**入口与展示** |
| §7.1 选课两轮制 + 冲突前置（三校教务处通知） | **科目级选课已上线**（enroll-v2）；**时段级没有** | (乙) 若要做，**必须先有容量/教学班层**（§7.4 列清代价），本期**不推荐** |
| §8 场景判定：全日制小班 vs 高校学分制 | 我们 = **全日制小班**（班级固定、教师流动） | ⇒ 主诉是「**班级/年级**排课」+「**看得见课表**」，不是「学生抢课」 |
| §9 第 1 件（网格排课 + 三类提示） | 已有「填组合→生成 N 条」+ 周矩阵预检 | **不做**（§1.2）；但**提示分三类**那半件仍可作为后续增量 |
| §9 第 2 件（教师可用性 → 最小扰动） | **F-1 未实现**（`resource_calendar_leaves` = 0 行） | **不依赖它**（§9 R3：本设计的预检**加入不了教师不可用这一维**） |

### 6.2 回引 `docs/research/onestop-learning-and-repetitive-work.md`（课程中心的来源调研）

| 学到什么 | 本设计怎么用 |
|---|---|
| Moodle **Timeline** 分桶（逾期 / 近 7 天 / 近 30 天） | 课程中心的「下次课」就是这个口径的简化版；本设计把「**本周**」补上（周窗口口径复用 `week_utils`） |
| Canvas **Modules** 顺序解锁 | 已在 `edu.lesson`（`require_sequential` 等）**不动** |
| §5#10「**不自建 URL/token 体系**」 | 本设计的订阅出口**只指** `/my/calendar`（既有 ICS）与 `/student/timetable`（既有页），**不建第二套** |

### 6.3 学什么 / 砍什么（本设计）

- **学**：① 既有门户的「角色分流 + 控制器侧预格式化」写法（`scheduling.py` 是现成范本，模板零逻辑）；② C-1 的「影响面先行 + 通知自证是这一次的变更 + 逐人计数」体例；③ 既有 `/timetable/bulk` 的「**落库前预检**」形态（`preview` 不落库）。
- **砍**：① 不搬任何新算法；② 不引入格子/拖拽；③ 不新建容量/抽签；④ 不建第二个冲突判据、第二个周口径、第二条通知链（H5–H7）。

---

## 7. 设计（★交付物④权限口径 / ★⑤接缝）

> ⚠ **本节的前提是 §4.4 的倾向判断（待确认）**。故给出 **P0 / P1 / P2 三档**，用户选哪一档就实施哪一档；
> **三档共用**同一套权限口径（§7.5）与接缝纪律（§7.6），**P0 ⊂ P1**，**P2 不推荐**。

### 7.0 设计前提（待确认，见 §10）

- **A1**：三种解读取哪一种（(甲)/(乙)/(丙)）。
- **A2**：「给学生排课」的**动作主体**——教务替他排（管理动作）还是学生自己挑（自助动作）。
- **A3**：「排课到人」的业务场景（补课 / 重修 / 选修走班 / 一对一）。
- **A4**：课程中心里的课表是**本周摘要**还是**完整周视图**。

### 7.1 **零新模型承诺**（为什么不新增模型）

| 需求 | 用什么承载（**既有件**） | **为什么不新增** |
|---|---|---|
| 排课的**结果** | `op.session`（基座） | 它是全仓唯一事实源（A1）；新表 = 第二个事实源，且要重建冲突四查/通知/课表/ICS 整条链 |
| 「**排给某个学生**」 | **`op.session.student_ids`（基座既有 m2m，A2）** | 基座**已经**为「课节到人」准备好了字段与通知语义（`create()` 自动 subscribe + `_NOTIFY_WORTHY_FIELDS`）；本地 0 行只是**没被用过**，不是**不能用**。**新增 `edu.session.student` 之类的表 = 与基座字段语义重复** |
| 停课 | `edu.schedule.holiday`（已有，A6） | 已有「按班/全校停课 + `_matches`」语义 |
| 冲突判定 | `main.py:262` `_slot_conflict_dims` + `session_ext.py:433` `_impact_flags` | H5：**明文规定它是唯一实现**；写第二套必然漂移 |
| 周次/学期锚点 | `week_utils.py`（H6） | 全站统一口径（周期排课/课表/学习页共用） |
| 改课通知与留痕 | C-1 全套（D1–D4） | H7：收件人口径唯一；审计走 `edu.audit.log`（不新建留痕表） |
| 会议链接 | `op.session.calendar_event_id → calendar.event.videocall_location`（A8） | 调研 §5#10「不自建 URL/token 体系」已定 |
| 身份反查 | `edu_schedule/models/identity.py`（`student_of_user:111` / `users_of_profile:148`） | `code-map.md:283-286` 硬约定：**唯一口径**，禁止就地写 `search([('user_id','=',uid)])` |

> **一句话**：本设计**新增的只有「行为」**（新路由 + 新模板 + 只读聚合 + 一处既有判据的维度扩展），**没有新增任何实体**。

### 7.2 **P0——课程中心内嵌课表**（= (丙)；最小件，**零写路径**）

**改动面（3 处，全部在既有文件内增改）**：

| # | 文件 | 改什么 |
|---|---|---|
| P0-1 | `custom_addons/edu_portal/controllers/study.py` | `my_study()`（`:273`）增加一段**只读**装配：本周窗口（复用 `edu_schedule.models.week_utils` 的 `monday_of`/`week_window_utc`/`term_anchor`/`week_no_of`，与 `scheduling.py:23-25` **同一份**）+ 该角色的 `op.session`（**域与 C1 逐字一致**：学生 `batch_id`、教师 `faculty_id`、家长孩子班合集、内部全校只读、其余空表）+ `('state','!=','cancel')`（C1 `:198-202` 已有，**照抄**）+ 时区换算（`context_timestamp`）+ 停课灰显（复用 `holiday._matches`） |
| P0-2 | `custom_addons/edu_portal/views/study.xml` | 在 `edu_study_home`（`:14`）的 hero 与统计条之后插一个「**本周课表**」区块：7 列 × 时段行（或 P0-lite：本周逐日列表）；渲染**纯输出**（控制器预格式化，规避 `t-options` 陷阱）；空态文案「本周暂无排课」 |
| P0-3 | 同上 | 「完整课表 →」出口写死 `/student/timetable?view=week`（**不新建第二个课表渲染器**，H4 的对策）；订阅出口写死 `/my/calendar`（复用 ICS，C7） |

**明确不做**：不改 `/student/timetable`、不改 `scheduling.py`（它是既有已上线页，**只被链接**）；不新增路由；不新增模型/字段；不动 C1 的任何口径。

**风险**：**低** —— 只读；唯一副作用是把「班级断点」暴露给学生（§9 R1/R9）。

### 7.3 **P1——课程中心里的「排课」**（= (甲)；含 P0）

#### 7.3.1 两条子能力（分开可独立上线）

| 子能力 | 语义 | 落点 |
|---|---|---|
| **P1-a 「按班级排课」入口** | 教务在课程中心点「排课」→ **跳既有 `/timetable/bulk` 并预填** `course_id`/`batch_id`/`subject_id`（querystring） | 只加**一个链接 + 预填**；页面与写入逻辑**仍在 `edu_schedule`**（**不复制**建课逻辑，避免第二个写入口） |
| **P1-b 「给学生排课」（排课到人）** | 在既有课节上**加/减学生**（写 `op.session.student_ids`）；或按学生**单独建一节**（补课形态） | 落在 `edu_schedule` 侧（模型方法）+ 门户页（表单） |

**P1-b 必须同时满足的三条**（否则不做）：

1. **一次写好，不留中间态**：建课节与写 `student_ids` **必须在同一次 `create()` 的 `vals` 里**（基座 `create()` 会用 `student_ids` 同步 follower 并发通知；先建后写会产生「课已经有、人还没有」的窗口，且可能触发两次通知）。
2. **学生维冲突判定 = 扩展现有唯一实现，不新写第二套**（H5）。现有 `_slot_conflict_dims` 返回 4 维（`faculty/classroom/batch_subject/batch`）；「排课到人」需要第 5 维 **`student`**（同一学生在两节重叠的课里）。做法：**在同名方法内新增一维并保持返回顺序语义**（新增维排在**末尾**，不改变既有 4 维的定级顺序），并**同批**同步 `session_ext._impact_overlap_dims`（`:452-468`，**同一模型上的姊妹实现**）——否则「预检会拦、影响面不说」= 两套口径。
   ⚠ **不得**为此新建 `edu.student.conflict` 之类的模型或第二个 judge 函数。
3. **四查开关口径照抄基座**（`_impact_flags` `:433`）：学生维**不是**基座四查之一 ⇒ **基座不会拦**；因此它属于「**被规则限制**」档（`scheduling-overhaul-design.md` §8.1 三类提示中的第 2 类），提示语必须是「**不会拦，但你应当知道**」，**不得**谎称「保存会被系统拦下」。

#### 7.3.2 P1 的路由清单（**全部新路径，零冲突**；写路由一律兄弟 `/save` + csrf，照铁律 4）

| 路由 | 方法 | 门禁（fail-closed） | 说明 |
|---|---|---|---|
| `/my/study/schedule` | GET | `privileged_staff()`（教务/系统管理员），否则 303 `/my/study` | 排课面板：选班级（或学生）→ 复议既有课节/新增一节（**只读渲染 + 表单**） |
| `/my/study/schedule/save` | POST | 同上 + `csrf=True` | 写 `op.session`（**复用** B1/B2 的 `vals` 构造口径：`course_id/batch_id/subject_id/faculty_id/timing_id/start/end + student_ids`），并调 `edu.audit.log._log('排课', 'op.session', …)` |
| `/my/study/session/<id>/roster/save` | POST | `privileged_staff()` **或**（教师 **且** 该课节 `faculty_id` 的账号是本人） | 加减 `student_ids`（基座 `write` 会重平衡 follower 并按 `_NOTIFY_WORTHY_FIELDS` 通知；**本设计不新增第二条通知链**） |

⚠ 上表**只在 P1 成立时实施**；P0 阶段**一条写路由都不加**。
⚠ **P1 另需一条前置（未验证项 U2）**：先实测「基座 followers 通知」与「C-1 站内信」是否双发，见 §9 R5。

### 7.4 **P2——学生自助选时段**（= (乙)；**不推荐**，列清代价供用户看清）

若用户坚持 (乙)，**必须新建**（这是零新模型口径的**唯一**合法破例路径，且需第 0 步「请队长裁定 → 校长拍板」）：

| 需要新建什么 | 为什么绕不开 | 代价 |
|---|---|---|
| 「教学班 / 开课班次」实体（1 门课 × N 个候选时段 + 容量 + 教师） | `op.session` 是**确定的一条课**，不是「有容量的教学班」（H8） | 新表 + 与 `op.session` 的挂接口径 + **第三个「学生的课」来源** |
| 容量与分配机制（先到先得 / 抽签 / 两轮制） | `op.subject.capacity` 只管科目、不管时段（H8） | 并发削峰 + 随机机制 + 通知（调研 §7.1/§7.3） |
| **填志愿时**的时间冲突检测 | 调研 §7.1 第 3 条（西电/北大）；事后报错不可接受 | 复用 `op.session` 判据但**面向学生**，必须脱敏（不能泄露别人课表） |
| 「学生的课」三源合一口径 | 否则 `subject_ids`（报课→LMS）/ `batch_id`（课表）/ 新实体（选时段）互相打架 | **一条跨 3 个模块的口径治理任务** |

**判断**：工作量**大**、风险**高**、且与「全日制小班」场景（调研 §8）不匹配 ⇒ **建议不做**；若确需，**先做 P0+P1 把课表与排课打通**，再评估。

### 7.5 权限口径（★交付物④：谁能排 / 谁能改 / 改后各自看到什么）

> 依据：`docs/code-map.md` §6 第 12 条（权限四层）+ `docs/plans/perm-model.md`。

#### 7.5.1 四层落位（新增的每一条路由/菜单/ACL 必须声明属哪一层）

| 层 | 组 | 本设计的权限 |
|---|---|---|
| **开发者** | `base.group_system` | 全部（排课、排到人、停用） |
| **教务** | `openeducat_core.group_op_back_office_admin` | **排课（含排到人）、改课、停课、通知** —— 与后台 `op.session` 写权限**同层**，不放宽 |
| **教师** | `openeducat_core.group_op_faculty` | **只在课程中心编辑自己任教课节**的会议链接（**现状已如此**，`study.py:342,377-387`）；**本设计可能给教师新增的唯一权限是** `roster/save` 对自己任教课节的加减人（**待确认，§10 A7**）；**教师不得**排课时段（教师维与班级维冲突必须由教务统一裁决） |
| **学生 / 家长** | `base.group_portal` | **只读**自己/孩子的课表；**零写权限**；**不给后台菜单** |

#### 7.5.2 「谁能排 / 谁能改」

- **能排**：教务组 ∪ 系统组。**唯一判据函数** = `edu_portal.controllers.roles.privileged_staff()`（`roles.py:251-258`）。
  ⚠ 注意 `edu_schedule/controllers/main.py:61-69` 有一份**就地复刻**（因为 `edu_schedule` 不能 import `edu_portal`，A→B 依赖成环，`main.py:62-66` 注释已写明）。**新增路由落在 `edu_portal` 侧 ⇒ 用 `roles.privileged_staff()`，不复制第二份**。
- **能改**：同上；教师仅 `roster/save` 限本人任教课节。
- **不能排**：学生、家长、无档案门户账号、guest。**fail-closed**：非授权一律 **303 `/my/home`**（既有写法：`main.py:671-672`、`study.py:381-382`），**不返回 403 详情**（不泄露存在性；与 `enroll.py` 的越权静默口径一致）。
- **后台菜单与 ACL：不动**（F9：`edu_schedule/security/ir.model.access.csv` 只有 2 行，**不给门户组新增行**）。

> ⚠ **必须写明的接缝判定（否则会被误读为「ACL 缺失」）**：门户页面上的写操作在本仓是「**控制器 `sudo()` + 控制器判角色把关**」的既有惯例（`enroll.py:18` 原文：「所有读走 `sudo()`（门户既有惯例），写操作由控制器判角色把关」）。因此**新增门户写路由而不同步 ACL 行 = 符合本仓既有口径**，**不等于**「没有授权」。
> ⚠ **任何新增的后台菜单或 ACL 行必须按四层挂**：教务层与系统组**并列**（`groups="openeducat_core.group_op_back_office_admin,base.group_system"`），**禁止**给教务组加隐含 `base.group_system`（`code-map.md:274-281`）。
> ⚠ **「看得见点不开」检查**：实施后必须跑 `python3 tests/smoke/backoffice_reachability.py`（L1 可见 → L2 动作+视图+权限读数 → L3 浏览器真渲染且**关键元素命中**；**HTTP 200 不算通过**）——即使本设计**只加门户路由**，也应确认没有打破既有后台可达性。

#### 7.5.3 改完课，各角色**分别看到什么**（口径 = C-1，**不新增第二条**）

| 角色 | 看到什么 | 依据 |
|---|---|---|
| **教务 / 管理员** | 改课页的「影响面」：受牵连课节 + 逐条判词（「保存会被系统拦下」/「不会拦，但人是受影响者」）+ 收件人清单（带角色标注）+ 最近一次通知时刻与人数 | `main.py:891`、`session_ext.py:470-514,566-579,603-629` |
| **任课教师** | 收到站内信（`session_change` 事件，可在 `/my/notify` 静音）；正文带 **old→new 变更摘要 + 班级/时间/教师/教室**；停课时追加「请勿前往教室」；课程中心/课表里**课节实时更新** | `session_ext.py:651-674`（`_session_change_body`）、`:676-739` |
| **在读学生** | 同上（同一份正文、同一事件 key）；课表 `/student/timetable` **立即生效**（含 `state!='cancel'` 过滤，C1 `:198-202`）；**「排课到人」时**：只有被排到的学生收到 | `session_ext.py:259-282`（`_reminder_users`：`student_ids` **优先**，为空才按 `op.student.course` 的 batch 回退 —— ⚠ 这条回退意味着**现在**「一班全体」是默认收件人） |
| **家长** | **不发通知**；家长只能通过 `/student/timetable`（`:156-165` 孩子班合集）与 `/my/child` **看**，**不改** | `session_ext.py:567`「家长不发」+ `_reminder_users` |
| **被静音的人** | 不收到，但**被单独计数**（「静音跳过 N 人」与「失败 N 人」分开），页面显示 | `session_ext.py:635-649`（`_impact_is_muted`）+ `:730` 的三分计数 |

### 7.6 与既有能力的接缝（★交付物⑤：不重复造，不新增第二个事实源）

| # | 既有件（位置） | 本设计**怎么接** | **不重复造什么** |
|---|---|---|---|
| S1 | `/timetable/bulk → /preview → /create`（`main.py:669/698/733`） | **被复用**：课程中心的「排课」按钮**跳它 + 预填**；**不复制**建课逻辑 | **不写第二个 `op.session.create`**（写点保持唯一；这是第 0 步「第三个入口出现即必须脚本化」的红线） |
| S2 | `_slot_conflict_dims`（`main.py:262-298`）+ `_impact_flags`（`session_ext.py:433`） | **在同一份实现上扩展学生维**（§7.3.1 第 2 条），并同批同步 `session_ext._impact_overlap_dims`（`:452-468`） | **不写第二套冲突判定**（H5；`main.py:270-274` 明文禁止） |
| S3 | C-1 影响面/通知（D1–D4） | **整体复用**：影响面先看 → 再改 → 一键通知；**复用同一正文构造与同一审计动作名**（新增动作名仅限**新动作**：`排课`/`排课到人`） | **不新增通知链、不新增事件 key、不新增留痕表** |
| S4 | 停课日 `edu.schedule.holiday`（A6） | 课表灰显与排课跳过**复用 `_matches`** | 不新增日历/停课语义 |
| S5 | 周口径 `week_utils`（H6） | 课程中心的「本周」窗口**import 同一份**（与 `scheduling.py:23-25` 同源） | 不写第二份周/学期锚点口径 |
| S6 | 周课表 `/student/timetable`（C1） | **只被链接**（P0-3 的「完整课表」出口）；**它本身不改** | 不新建第二个课表渲染器 |
| S7 | iCal 订阅（C7） | 「订阅」出口直接指 `/my/calendar` | 不自建 URL/token 体系（调研 §5#10） |
| S8 | 会议链接 `set_meeting_url`/`join_state`（A9） | 课程中心的入会按钮**沿用**（含 `/my/study/session/<id>/join` 的**本班越权防护** `study.py:358-364`） | 不建第二条入会路径 |
| S9 | 报课 `/subject/enroll` + 审批（§4.2） | **只读引用**（课程中心已有「去报课选科」空态按钮 `study.xml:33`）；**不改报课链路** | 不动 `enroll.py`/`registration.py`（**报课≠课表**那条断点属 `scheduling-overhaul-design.md` §7，未实现） |
| S10 | 身份反查 `identity.py`（`code-map.md:283-286`） | 「排给学生」时**必须**用 `student_of_user` / `users_of_profile` | 禁止就地写 `search([('user_id','=',uid)])` |
| S11 | 审计 `edu.audit.log._log` | 新动作名写进同一张表 | 不新建审计表 |
| S12 | 并发锁 `edu_portal/models/scheduling.py:19,23` | 新写路径**仍走 `op.session` 的 `create/write`** ⇒ **自动被同一把锁覆盖** | 不自建第二把锁 |

---

## 8. 验收标准（实施时落 `tests/smoke/`；**本节只给判据，不写实现**）

| # | 断言 | 判据（**必须能真机复现**） |
|---|---|---|
| V1 | **P0：课程中心出现本周课表** | 学生登录 `/my/study`，页面出现「本周课表」且**本周课节数 == 该生 `batch_id` 本周 `op.session`（`state!='cancel'`）计数**（逐条比对日期/时间/科目），不是「有这块 DOM」就算过 |
| V2 | **P0：口径与 `/student/timetable` 同源** | 同一学生、同一周，两个页面的课节集合**逐条相同**（差集为空）；时区换算一致（`context_timestamp`） |
| V3 | **P0：零写路径** | P0 上线后 `op_session` / `op_session_op_student_rel` 行数**不变**；`/my/study` 页面**没有任何 POST 表单** |
| V4 | **P1-a：跳转预填** | 教务在课程中心点「排课」→ 落到 `/timetable/bulk` 且 `course_id`/`batch_id`/`subject_id` **已选中**（读页面 DOM 的 selected 值，不看 URL） |
| V5 | **P1-b：排课到人写对表** | 给学生 S 的课节 C 加人后：`op_session_op_student_rel` 出现且**仅出现** `(C,S)`；**其余行数不变**（造样本 → 断言 → 还原，断言 `leftover = 0`） |
| V6 | **P1-b 反例（学生维预检真的在拦）** | 给同一学生在**已有一节课的同一时段**再加一节 ⇒ 页面给出**中文人话**的「不会拦，但该学生此时段已有课」提示（**不是**基座英文 `ValidationError`，**不是** 500） |
| V7 | **P1-b：一次写好（无中间态）** | 断言 `create` 的 `vals` 里**同批**带 `student_ids`；用 ORM 边界写 + 读库验证不存在「课已建、人未写」的窗口 |
| V8 | **权限：越权必须 303 且不泄露** | 学生/家长 POST 任一新写路由 ⇒ **303 到 `/my/home`**（`allow_redirects=False` 断言**首跳** + `Location` 精确匹配；**禁止**用「跟随后 200」当通过 —— `dev-workflow.md` 陷阱 2 的原话） |
| V9 | **权限：教师越界被拦** | 教师对自己**不任教**的课节 POST `roster/save` ⇒ 303 且 `op_session_op_student_rel` **零变化** |
| V10 | **通知只发一次、且发对人** | 「排课到人」后：被排学生收到**一条**站内信；同班**其他**学生**零条**；家长**零条**；`edu.audit.log` 有一条对应动作（**前置 = R5 已排除双发**） |
| V11 | **零新模型** | `grep -rn "class Edu.*Session" custom_addons/edu_portal/models/` **零新增命中**；库内新增模型数 = **0** |
| V12 | **零新冲突判据** | `grep -rn "_slot_conflict_dims\|_impact_overlap_dims"` ⇒ **仍只有那两处**（一处判定、一处姊妹展示），无第三个 |
| V13 | **回归：既有件不动** | `/student/timetable`（四视角）、`/timetable/bulk`、`/timetable/session/<id>/impact`、`/my/study`、`/my/study/<id>`、`/my/study/session/<id>/join` 全部 **200/303 与改动前逐条一致**；`python3 tests/smoke/schedule_grade_split.py`（V20–V25）**仍全绿** |
| V14 | **门禁** | `bash scripts/safe_upgrade.sh edu_portal`（EXIT=0 无 Traceback）+ `docker compose restart web` + `python3 scripts/check_live_registry.py`（0 DARK）+ `check_view_xpath.py`、`check_qweb_dict_foreach.py`、`check_english.py`（must-fix 0）、`check_docs_index.py` 全绿 |

**明确不允许的验收写法**（照 `scheduling-overhaul-design.md` §13.3）：「升级 EXIT=0 就算过」「只读代码就声称生效」「只测 HTTP 200 不看页面数字」「探针跟随重定向判 303 成功」。

---

## 9. 本设计**解决不了什么** + 风险（★交付物⑥）

| # | 解决不了 / 风险 | 事实依据 | 影响 |
|---|---|---|---|
| **R1** | **班级断点（最大的一条）** | 学生课表按 `op.student.course.batch_id` 过滤（`scheduling.py:152-155`）；生产真实课大量挂在**合班批**（9 个批共 139 节，`scheduling-overhaul-design.md` §18.5 生产只读读数，采集 2026-09-18） | **即便做了课程中心课表，学生也只看到自己档案班那几节**（生产样例：B1 学生只看到 18 节）。§18 的「按年级重排」是**排课侧**的绕行，**未执行完**（`docs/plans/README.md:111-112` 挂起项 2：A1/B1/B3/B4 共 **77 课时未归档**、全套 `state='draft'`） |
| **R2** | **「报课 ≠ 课表」仍然存在** | `op.student.course.subject_ids`（报课审批写入，`registration.py:222`）与 `op.session.batch_id`（课表读）是**两条线**；B1 诊断 §0/§2 已给链路图 | 本设计**不改报课链路** ⇒ 学生「报了的课不出现在课表上」照旧。正解见 `scheduling-overhaul-design.md` §7（**未实现**） |
| **R3** | **教师不可用数据不存在** | F-1 未实现；`resource_calendar_leaves` 生产 **0 行**（`scheduling-overhaul-design.md` §6.2，采集 2026-09-18）；本仓 `resource.mixin`/`resource.calendar.leaves` **0 命中** | 排课时系统**无法**避开教师不可用时段；本设计的预检**加不了这一维** |
| **R4** | **教室维度全是空列** | 本地 `classroom_id` 空 **277/288**（本次实测）；生产 **0/216**（同前引） | 教室视角/教室冲突提示在真机上**造不出自然样本**（只能造【演示】样本）；`op_classroom` 仅 3 条 |
| **R5** | **基座通知链可能与本设计的通知重复**（⚠ **未验证 U2**） | `op.session.create()` 会用 `student_ids` **自动 subscribe + 按 `_NOTIFY_WORTHY_FIELDS` 通知**（`timetable.py:342-390,507-567`，逐段实读）；而 C-1 的 `_notify_session_change` 走 `edu.message._notify_event` | 「排课到人」可能产生**两套通知**（基座 follower 通知 + C-1 站内信）。**必须在实施前实测**，否则学生收到两条 |
| **R6** | **「排课到人」的业务必要性未经确认** | 本项目为**全日制小班**（调研 §8 判定）；`scheduling-overhaul-design.md:55` 明写「一对一场景本项目不存在」⇒ 本设计**不引入任何补课/重修实体** | 若用户其实要的是「补课管理（审批 + 费用 + 课时核销）」，本设计**给不了**（那是一个新业务，不是排课） |
| **R7** | **并发与中间态** | `op.session` 写已有一把全局 advisory 锁（A11）⇒ 点写被覆盖；但「**先建课节、再写 `student_ids`**」的两段式会产生中间态（§7.3.1 第 1 条已禁止） | 实施时必须**一次写好**；否则出现「课在、人不在」的假课表 |
| **R8** | **门户写入口的审计覆盖未知**（⚠ **未验证 U3**） | `tests/smoke/backoffice_reachability.py` 的 L1–L3 口径面向**后台菜单**；门户写路由是否被任何既有门禁覆盖，**未查** | 新增门户写路由可能落在门禁盲区 |
| **R9** | **把课表做进课程中心会「暴露」R1** | 现在学生只在 `/my/study` 看到「下次：」一行；做完 P0 会看到一周只有 2 节课 | **产品风险 > 技术风险**：建议 P0 与「按年级重排收尾」的沟通同步，或 P0 先只在教师/教务视角上线（**待用户拍板**） |
| **R10** | **既有文案残留**（不是本设计引入，但会被下一个人当现状） | H2：「整周复制」已删（`77b0b75`，2026-09-15）但全仓**仍有 12 处非文档引用**（含 `__manifest__.py` 的 summary/description、帮助中心教师卡 desc、`templates.xml:25`、`holiday_views.xml:41`、`audit.py:5`、`help_center.py:18`） | 会误导用户与开发者；**本设计不含修复**（只设计不实现），**登记给队长**（§12） |
| **R11** | **导航「课表」名实不符** | F4：顶部导航「课表」→ `/my/calendar`（校历），而真课表在 `/student/timetable` 且课程中心里不可直达 | 用户困惑的直接来源；修复要动 `edu_portal_templates.xml`（**他人 working set**）⇒ 本设计**不改**，登记给队长（§12） |

---

## 10. 需要用户确认的假设清单（★交付物⑦）

> 未回答前**不得开工**（第 0 步：查重记录缺失 = 不许进第 4 步；设计前提未定 = 不许进第 5 步）。

| # | 假设 / 问题 | 我现在的默认（**不是结论**） | 为什么必须问 | 影响面 |
|---|---|---|---|---|
| **A1** | 用户说的「给学生和班级排课」是 **§4.1 (甲) / §4.2 (乙) / §4.3 (丙)** 哪一种？ | **倾向 (甲) + (丙) 配套**（§4.4） | 三者工作量与风险差一个量级 | **整个设计走向** |
| **A2** | 「给学生排课」的**动作主体**是谁：**教务替他排**（管理动作）还是**学生自己挑**（自助动作）？ | 教务（门户写路由全部 `privileged_staff()`） | 决定权限层与是否存在越权面 | §7.5 权限口径、路由清单 |
| **A3** | 「排课到人」的业务场景是什么：补课 / 重修 / 选修走班 / 一对一？ | **未定**；本设计只用 `op.session.student_ids` 承载，**不引入补课审批与费用** | 若真是补课/重修，本设计**不够**（缺业务实体），需要另立设计 | 是否仍算「零新模型」 |
| **A4** | 课程中心里的课表要「**本周摘要**」还是「**完整周视图**」？ | 摘要 + 跳既有 `/student/timetable`（避免第二个渲染器） | 决定 P0 改动面与是否新增路由 | P0 工作量 |
| **A5** | 学生看到的应当是「**档案班课表**」还是「**实际排课班课表**」（两者不一致时）？ | 现状 = 档案班（本条**不解决**，见 R1） | 这是 R1 的**业务裁决**，不是技术选择 | 学生看到的课量；§18 收尾的口径 |
| **A6** | 「排课到人」后是否**自动通知**学生？ | 是（复用 C-1，且必须先解决 R5 的双发风险） | 通知是用户可见行为，且有双发风险 | 通知面、R5 的前置 |
| **A7** | **教师**能否在课程中心给**自己任教课节**加人（`roster/save`）？ | 允许（限本人任教课节） | 四层权限的边界问题（教师层只给「教学执行」） | 权限口径；若不允许，教师连「加个旁听生」都要找教务 |
| **A8** | 导航里「**课表**」是否应改指 `/student/timetable`（现在指 `/my/calendar`）？ | 建议改，但**不在本设计内**（会碰 `edu_portal_templates.xml`——**他人 working set**） | 名实不符是用户困惑的直接来源（F4） | 前端 IA |
| **A9** | 是否同意**先做 P0、再评估 P1**（而不是一次性做 (乙)）？ | 同意（P0 风险最低、当天可见） | 决定排期 | 交付节奏 |

---

## 11. 未验证 / 不确定（**不得当结论用**）

| # | 未验证项 | 我做了什么 / 为什么不确定 |
|---|---|---|
| **U1** | **生产实测** | 本次**未连生产**：§3 E5 的生产读数**全部引用** `scheduling-overhaul-design.md`（采集 **2026-09-18**），**未复核**。本地读数（E3/E4，2026-09-28 实测）**不代表生产** |
| **U2** | **基座通知链与 C-1 是否双发**（R5） | 只**实读**了 `timetable.py:342-390,507-567` 的代码路径（`create()` 订阅 + `_NOTIFY_WORTHY_FIELDS` 触发通知）；**未实跑**「写 `student_ids` 后到底发几封、走哪条通道」。实施前必须实测（三段模板） |
| **U3** | 门户写路由是否被既有门禁覆盖（R8） | **未查** `tests/smoke/` 全量断言清单与 `ux_v3_route_matrix.py` 的角色矩阵是否覆盖「新增门户 POST 路由」。实施前必须查 |
| **U4** | `op.session.student_ids` 的基座语义细节 | 只读了「自动 subscribe + 通知重平衡」的实现；**未验证**：`student_ids` 是否会影响 `check_timetable_fields`（四查不含学生维 ⇒ 应当不会），以及 `_backfill_demo_student_ids`（`timetable.py:617-657`）是否会在某些升级路径下**自动填充**这个字段（若会，则「0 行」这个读数在生产可能不成立） |
| **U5** | 生产 `op.session.student_ids` 现状 | 本地 **0 行**（实测）；**生产未查**（§18.5 只给了 `op_session_op_student_rel` **0 行** 的 2026-09-18 读数 ⇒ 与之相容，但**未复核**） |
| **U6** | 「排课到人」与冲突四查的**交互** | 设计断言「基座不会拦学生维」（四查只有 faculty/classroom/batch/batch+subject）。这是**读源码得出的**，**未实跑**反例验证 |
| **U7** | 本地 288 节里【演示】占比 | 本地有「预备科 · 2026级【演示】」批 72 节；**未逐条判定**其余 216 节的来源。本地数据只用于口径验证，**不代表生产** |
| **U8** | 重定向探测的写法 | §8 V8 引用了 `dev-workflow.md` 陷阱 2 的正确写法（`allow_redirects=False` + `Location` 精确匹配）；**本次未实跑**该探测 |
| **U9** | `edu_schedule/views/templates.xml~` 中「整周复制」残留是否影响页面 | H2 发现 `templates.xml:25` 仍有文案；**未逐条确认**这些位置在页面上**是否真的渲染给用户**（可能在被删章节里） |

---

## 12. 台账登记（第 0 步「查到重复怎么办」第 2 步）

**本次查重结论**：**没有发现「第二套排课实现」**（写路径唯一 = `op.session`，§3 H）；因此**不是**「新建（并存）」场景，而是**「复用 + 边界裁定」**。

**已在 `docs/audit/deprecated-inventory.md` §8 追加一行**（追加，不改历史行），登记两处**潜在重叠**与裁定：

1. **重叠对象 ①「排课入口」**：门户课程中心若新增「排课」，与既有 `/timetable/bulk`（`edu_schedule/controllers/main.py:669/698/733`，菜单 603）是同一件事的两个入口。
   → **裁定 = 复用（跳转 + 预填）**：课程中心**不复制**建课逻辑；写点仍唯一。
   → **收口触发条件 = 出现第三个「批量建 `op.session`」入口** ⇒ 按 `dev-workflow.md`「脚本化条件」写 `scripts/check_feature_overlap.py`（该条件已由 `scheduling-overhaul-design.md` §16 先立，本次**重申并沿用**）。
2. **重叠对象 ②「课表展示」**：`/student/timetable`（周课表，C1）与 `/my/study`（科目视图，C2）已是两处；若再做第三处渲染器会三足鼎立。
   → **裁定 = 复用（不新增渲染器）**：课程中心只做「本周摘要」，完整课表**只链接**既有页；订阅**只链接**既有 `/my/calendar`（ICS）。

**另登记两条「既有实况不一致」给队长**（不属于本设计的重叠，但会被下一个人当现状）：

3. **R10 / H2**：「整周复制」已于 `77b0b75`（2026-09-15）删除，但全仓**仍有 12 处非文档引用**（`README.md:60`、`edu_schedule/__manifest__.py:4,5`、`edu_schedule/views/templates.xml:25`、`edu_schedule/views/holiday_views.xml:41`、`edu_schedule/models/holiday.py:2`、`edu_schedule/models/week_utils.py:2`、`edu_portal/views/scheduling.xml:106`、`edu_portal/views/help_center.xml:240`、`edu_portal/controllers/help_center.py:18`、`edu_portal/models/audit.py:5`、`edu_portal/controllers/batch2.py:1918`）⇒ 建议由队长排一次文案清理（**本设计不实施**）。
4. **R11 / F4**：顶部导航「课表」指向 `/my/calendar`（校历），真正的周课表 `/student/timetable` 在课程中心里**不可直达** ⇒ 名实不符（**本设计不改**，因为它要动 `edu_portal_templates.xml` = **他人 working set**）。

---

## 13. 变更记录

| 日期 | 改动 | 责任 |
|---|---|---|
| 2026-09-28 | 初版：第 0 步（① code-map 锚点 / ② 既有实现对照 / ④ 是否动业务数据 / ⑤ 演示数据策略）+ 第 3 步读参考（回引两份调研）+ 第 4 步设计摘要（P0/P1/P2 三档 + 权限口径 + 接缝表 + 验收 + 风险 + 待确认假设 + 未验证清单）；**零代码** | 设计子代理（课程中心排课入口） |
| 2026-09-28 | **P0 已实施并自证**（队长裁定：只做 P0；**P1/P2 未开始，仍阻塞在 §10 的用户确认**）。落地 = §7.2 的 3 处：`edu_portal/controllers/study.py`（`_week_role_and_domain` / `_week_scope_note` / `_week_empty_hint` / `_week_holiday_map` / `_week_schedule` + `my_study()` 传 `week=`）、`edu_portal/views/study.xml`（`edu_study_home` 内 `#ux3-week` 区块 + 两个出口）、`tests/smoke/study_week_schedule.py`（门禁 + 取证量具）。**零新模型/零新字段/零新路由/零写路径**；课表渲染仍是既有 `/student/timetable`（只链接）；周口径仍是 `week_utils`；角色域与 C1 同口径并由门禁守着。**状态口径**：本文件落到 `在研`（门禁语义 = 本文范围内仍有**未上生产**的部分）—— P0 只在本地 `edu19` 实施并自证，**未部署生产**（部署须用户确认），且 P1/P2 未做；**改动未提交，由队长提交**（故此处不引用 git 提交号，`git status`/`git diff` 可核）。门禁读数：`tests/smoke/study_week_schedule.py` 50/50 PASS（含改前 `--capture before` 反向证据 + 四角色逐条集合 == SQL oracle == `/student/timetable` + 三段夹具 `leftover=0`）、`ux_v3_route_matrix.py` 495 检查点全绿、`check_ui_surface.py` / `check_view_xpath.py` / `check_qweb_dict_foreach.py` / `check_live_registry.py` / `check_docs_index.py` 均 EXIT=0。⚠ §8 V3 的原文「/my/study 页面没有任何 POST 表单」**与事实不符**（既有门户壳自带 `POST /my/avatar/upload` 头像表单，改前改后各 1 个）⇒ 门禁改成两条更硬的判据（区块内零 form；页面 POST action 集合只允许是既有壳那一个，且数量与改前逐字相等）。⚠ `docs/plans/README.md` 里本文件的登记行在 HEAD 中是**截断的 4 格行**（缺「依据」列与行尾竖线，门禁只判前 4 格故未报红），本次随状态改写一并补成 6 格 | 实施子代理（P0） |

---

## 附：本次取证命令（可原样复现）

```bash
# ① 本地读数（只读 SELECT，未做任何写操作）
docker compose exec -T db psql -U odoo -d edu19 -c "\d op_session"
docker compose exec -T db psql -U odoo -d edu19 -c "select count(*) from op_session;"
docker compose exec -T db psql -U odoo -d edu19 -c "select count(*) from op_session where state='cancel';"
docker compose exec -T db psql -U odoo -d edu19 -c "select count(*) from op_session_op_student_rel;"
docker compose exec -T db psql -U odoo -d edu19 -c "select count(*) from op_student_course where state='running';"
docker compose exec -T db psql -U odoo -d edu19 -c "select b.id,b.name::text,b.code,count(s.id) sess,count(distinct s.subject_id) subj from op_batch b left join op_session s on s.batch_id=b.id and s.state<>'cancel' group by 1,2,3 order by sess desc;"
docker compose exec -T db psql -U odoo -d edu19 -c "select id,name::text,parent_id,active,action from ir_ui_menu where id in (341,342,603);"

# ② git 史实（逐条）
git log --pretty=format:'%h|%ad|%s' --date=short -1 7640444
git log --pretty=format:'%h|%ad|%s' --date=short -1 727a6f9
git log --pretty=format:'%h|%ad|%s' --date=short -1 77b0b75
git log --pretty=format:'%h|%ad|%s' --date=short -1 5da2270
git log --pretty=format:'%h|%ad|%s' --date=short -1 1ec787f
git log --pretty=format:'%h|%ad|%s' --date=short -- custom_addons/edu_schedule/

# ③ 负结论（搜索范围即结论的一部分）
grep -rn "学生排课\|自助排课\|给学生排课\|排课到人\|个性化课表" docs/
grep -rn "整周复制" .
grep -rn "conflict_kind\|conflict_color\|_overlaps\|_slot_conflict" custom_addons/
grep -rn "def monday_of\|def week_no_of\|def term_anchor\|def week_window_utc" custom_addons/
grep -rn "_reminder_users\|_session_student_users" custom_addons/
grep -rn "resource\.calendar\.leaves\|resource\.mixin" custom_addons/

# ④ 文档索引门禁（新增计划文档必须过）
python3 scripts/check_docs_index.py
```

