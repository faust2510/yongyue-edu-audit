# 代码图谱（Code Map）

> **目的：给 AI 助手/新人一份"一页读懂全仓"的索引，避免每次会话重新爬代码、浪费 token。**
> 本文件是权威入口，改了架构/新增模块/新增路由分组时必须同步更新。
> 配套：实现铁律见 `docs/dev-workflow.md`；背景故事见 `README.md`；各功能设计见 `docs/plans/`。

最后更新：2026-09-17（**权限四层收口**：`docs/plans/perm-model.md` = 四层规范 + 挂层规矩；code-map §6 第 12 条 = 硬约定；教务侧读数 179 节点/12 根、死角 5→0。同时保留本日**功能重叠收口**：新增 `edu_nav` 菜单收口模块 + 打卡两套合一；入口现状见 §4.1，弃用台账见 `docs/audit/deprecated-inventory.md`。**同日晚新增**：模块 `edu_tg_bind`（Telegram 发注册码机器人，设计 `docs/plans/tg-invite-bot-design.md`）+ 本仓 v2.2 `edu_telegram` 的退役登记（弃用台账 §0.1 / B8，**doc-only**））
> 上次全量更新 2026-09-12（v3 改造启动：去 Odoo 化 + 学坊本土化 + 一条龙服务；新增 `docs/research/` 调研档案与六步闸门）

> **v3 进行中**：去 Odoo 痕迹（含电商残留/默认发件人/用户菜单外链）、`edu_zh` 译文覆盖与「学费→统筹费」、课程中心与课节级 Zoom 链接、首页 Timeline 工作台、批量审批与成绩批量化。范围与依据见 `docs/research/`。

---

## 1. 项目是什么

永约学坊（Covenant Reformed Seminary）的教务系统，**Odoo 19 + OpenEduCat（LGPL，19.0 分支快照）** 为骨架，自研 `custom_addons/edu_*` 模块做门户与业务扩展。公开官网信息以 `custom_addons/edu_portal` 与 `edu_brand` 中的"永约学坊"资料为准；**一切旧学院假资料（电话/邮箱/地址）必须清除**，演示数据必须带【演示】标记。

## 2. 环境速查

| 项 | 值 |
|---|---|
| 本地启动 | `docker compose up -d`（PG16 + Odoo19，项目名 edu19-clone） |
| 本地地址 | http://localhost:8069 （HTTP）/ :8072 （WebSocket，必须开） |
| 数据库 | `edu19`；文件存 `./data/`；compose 挂载 `openeducat_erp→/mnt/extra-addons`、`custom_addons→/mnt/custom-addons` |
| ⚠ 本地多库陷阱（2026-09-12 事故，因果已复核） | 本地 Postgres 有 **3 个库**（`edu19`、`edu19_relay_probe`、`postgres`）。**根因 = 多库且没有默认库**：请求解析不出库时落进 `_serve_nodb()` 路由表 → 除少数核心路由外**全站 404**。<br>**修复 = 在 `config/odoo.conf` 写 `db_name = edu19`**（配置层默认库，等价于给每个请求预选库）。<br>**`list_db = False` 与生产一致、刻意保留**——它只决定是否暴露库列表/选择器，**不是 404 的主犯，不要因为 404 就把它改回 True**（那会重新拉开本地与生产的差距）。<br>带 `?db=edu19` 仍无害且更显式，但**已不再是必要条件**（db_name 生效后裸 URL 也可用）。<br>⚠ **2026-10-01 换机时这个坑在生产复现了一次，而且是致命形态**：`deploy/odoo.conf.server`（生产配置，因含 `admin_passwd` 被 gitignore）只有 `list_db=False`、**没有 `db_name`**。后果：匿名访问 `/` 返回 200（**看起来完全正常**），但**登录后 `/my/home`、`/my/study`、`/student/timetable` 全部 404**。<br>实测证据（新机 203.0.113.11，用 `/web/session/authenticate` 登 王佐 uid=19）：加 `db_name` 之前三页全 404；加 `db_name = edu19` 并重启 web 之后三页全 200，且 `/my/home` 上「王佐」出现 6 次。<br>**⇒ 生产配置也必须有 `db_name`**；部署后**不要只冒烟匿名路由**（那会全绿），必须验一条登录态路由。若哪天有人「清理」掉这一行，学生一登录就全站 404。 |
| ⚠ 门禁跑前三步探活 | ① 无升级锁（`$TMPDIR/edu19_upgrade.lock` 不存在）；② 容器 Up 时长 > 30s（不是刚重启）；③ **带 cookie jar** 访问 `/web/login?db=edu19` 得 200/302/303，且 `/login` 非 404。任一不满足就不要跑门禁——跑了也是假红。<br>（裸 curl 不带 cookie 时 `/web/login?db=edu19` 会**自跳 302 到自己**，那是会话选库、不是故障；探活一律用 `curl -c jar -b jar`。） |
| Odoo 配置 | `config/odoo.conf`（example 备份在同目录） |
| 生产环境 | 马来西亚 prod-host（**203.0.113.10**，Hostinger `srv1868290`），`/opt/edu-app`，经 Cloudflare 隧道绑定 `edu.example.org`。<br>
⚠ **2026-10-04 已从 201 切回本机**（`cn.edu.example.org` 灰云 A 与 `edu.example.org` 隧道 CNAME 双双指回）；**203.0.113.11 已退货退款**。<br>
ssh 别名：**`prod-host` → 187**（所有引用它的脚本自动跟着走，含 `deploy_myedu.sh` 的默认 `REMOTE`）｜`prod-a` → 187｜`prod-b` → 201（过渡期用）。 |
| ✅ **2026-10-01「数据事故」已于 2026-10-04 更正** | 当时记为「旧机 `203.0.113.10` 欠费自动关机、**数据全丢且不可恢复**」——
**这句话是错的，不要采信**。校长续费后实测：容器按重启策略自动拉起、`PGDATA` 197M 与 filestore 37M 完好，
学生 51 / 用户 39 / 附件 545 全部在，最后写入 2026-09-24。已完整备份到校长 Mac（含**还原彩排**）并**切回该机作正式站**。<br>
**教训：「看不到」不等于「没有了」——写「数据全丢」这种结论前必须有一次直接读数。**
全过程见 [docs/audit/old-server-187-recovery-2026-10-04.md](audit/old-server-187-recovery-2026-10-04.md)｜
切换见 [docs/audit/cutover-back-to-187-2026-10-04.md](audit/cutover-back-to-187-2026-10-04.md)。<br>
下面这段是**当时**的新机重建记录，保留为历史（该机已退货，重建计划不再需要执行）：新机从 2026-08-30 的生产快照 `edu19_post_cleanup_0830.dump` 还原后 `-u all` 升到最新代码。<br>**⇒ 8/30 之后的业务数据（12 个班的学籍、216 节课、115 门课、38 个账号）全部不存在，需要重建**；新机 filestore 只有抢救回的 186/709 条附件字节（且**没有一件校方资料**）。<br>重建执行清单 [docs/audit/migration/rebuild-plan.md](docs/audit/migration/rebuild-plan.md)｜数据损失台账 [docs/audit/migration/data-loss-ledger.md](docs/audit/migration/data-loss-ledger.md)｜换机手册 [docs/ops/migration/new-server-runbook.md](docs/ops/migration/new-server-runbook.md)｜DNS/TLS 切换 [docs/ops/migration/dns-and-tls-cutover.md](docs/ops/migration/dns-and-tls-cutover.md)。<br>同一台机还是 `prod-host` 别名，**部署脚本无需改**（`REMOTE=prod-host`）。 |
| 部署 | `bash scripts/deploy_myedu.sh [模块名]` —— rsync 六模块 → 远端 `-u` 升级 → 起站 → 冒烟 5 个公开路由。<br>⚠ **部署前先干跑孤儿检查**：`FIX_DRY_RUN=1` 跑 `scripts/fix_edu_apply_xmlid.py` —— `SKIP`=可直接部署；`DRY`=生产存在同型 xmlid 孤儿（先跑脚本补映射**再**部署，否则 `-u edu_apply` 会因 `UNIQUE(name)` 撞车 EXIT=255）；`ABORT`=数据与预期不符，停手人工核对 |
| 改码后本地验证 | **`bash scripts/safe_upgrade.sh <模块>`**（内含串行锁 / 正确 DB 参数 / `--no-http` / 挂载自检 / 失败特征硬失败），要求 EXIT=0 无 Traceback。**默认 `-u`；只有首次安装新模块才用 `-i`**——⚠ 实测：`-i` 对已装模块**不重载 data/view 文件**（新字段会建、新视图不会进库），会制造「升级成功但页面没变」的假象。**不要**直接 `docker compose exec web odoo ...`：exec 绕过 entrypoint，会缺 `--db_host` 并撞 8069 端口 |
| 汉化验收 | `python3 scripts/check_english.py`（v3 起四类分流：must-fix / whitelist / data / theme；**验收口径 = must-fix 为 0**，白名单只留品牌名、品牌口号、Zoom、语言自称） |
| 压测结论 | 浏览态约 60 人零失败；登录洪峰阈值约 40–60 并发（docs/plans 有实测记录） |

## 3. 顶层目录地图

| 目录 | 作用 | 改动频率 |
|---|---|---|
| `custom_addons/` | **全部自研 Odoo 模块（14 个 edu_*）**——本项目的主战场（份数以 `ls -d custom_addons/edu_*` 实测为准，门禁 `check_doc_module_count.py`） | ★★★ |
| `openeducat_erp/` | OpenEduCat 官方源码快照（19.0），基座，**原则上不改**（改也在 custom_addons 里继承/extending） | 只读 |
| `scripts/` | 种子/汉化/图标/截图/压测/部署等 50+ 独立脚本 | ★★ |
| `docs/` | 设计说明 + plans/ 设计文档 + 审计报告 | ★★ |
| `config/` `deploy/` | odoo.conf；生产 compose 与服务器 conf | 低 |
| `data/` | PG 数据卷 + odoo 文件存储（gitignore 大部分） | 运行时 |
| `reference/` `scrape/` | 原站参考包、抓取页面/截图——只读素材 | 只读 |
| `tests/` | smoke / gap 子目录，冒烟脚本 | ★ |
| `specs/` | batch2/batch3 施工规格（历史） | 只读 |

> ⚠ **源码快照 ≠ 生产 schema（2026-09-24 实测）**：`openeducat_erp/` 是官方源码快照，与**实际部署**的基座版本不完全一致。
> 例：快照 `openeducat_core/models/student.py:33` 声明 `op.student` 上有 `course_id`（required）/ `batch_id` / `academic_years_id`，
> 而生产库 `op_student` **没有这几列**——它们在学籍行模型 `op.student.course`（表 `op_student_course`）上。
> **凡涉及「某字段在不在 / 叫什么 / 挂在哪个模型」，先查库再动手**：
>
> ```bash
> ssh prod-host 'docker exec -i edu19-prod-db-1 psql -U odoo -d edu19 -c "\d op_student"'   # 或查 ir_model_fields
> ```
>
> 只读快照会把人带沟里：2026-09-24 个人资料页「学籍卡」就因此踩过一次（按快照写 op.student.course_id，实际要走 op.student.course）。
> 相关口径：学号唯一真身 = `op.student.gr_no`（唯一约束），禁止在 res.partner 另开学号字段。

## 4. 自研模块地图（custom_addons/，依赖方向：brand/public ← portal ← 其他）

### edu_portal —— 门户中枢（最大模块，~1.5 万行，manifest 19.0.2.0.0）
学生/教师/教务/家长四角色门户 + 后台审批 + 资料下载。控制器按批次拆分：
- `controllers/main.py`：/my 重定向、/my/home 首页分发（学生卡片页 / 教师工作台分支）
- `controllers/batch1.py`(935行)：学生档案/考勤/考试/作业（/student/* 五页 + 提交/撤回/发票PDF）
- `controllers/batch2.py`(1548行，最大文件)：**首页卡片引擎**（`_YONGYUE_CARDS` + `cards()`，SVG 图标优先/FA 兜底）、成绩册、图书馆、公告、分组导航
- `controllers/batch3.py`(900行)：证书下载、申诉、请假(time_off)、毕业论文、选课、会议、DMS、结果总览
- `controllers/roles.py`(585行)：**教师/教务侧**——考勤打分 /attendance/take、作业发布、请假审批、公告发布、成绩录入、家长端 /my/child；批次 4 A1 审批聚合：/leave/approvals/<id> 详情、/grievances/approvals[/<id>] 申诉审批、/leave|grievances/set_state 写路由（审批后经 edu.message 通知申请人）
- `controllers/calendar.py`(854行)：校历三视图（月/周/列表）+ EduEvent 模型
- `controllers/messages.py`：私信（轮询 /my/messages/poll）
- `controllers/contacts.py`：通讯录 + 身份重绑（relink_identity）
- `controllers/welfare.py`：福利积分（EduPointLog 打分扣分/每日打卡 board）
- `controllers/evaluation.py`：评教（EduEvalTemplate/Task/Score 四模型）
- `controllers/lms.py`、`assets.py`、`fees.py`、`jobs.py`(校友招聘)、`scheduling.py`(学生视角课表)、`ledger.py`(财务总账+报销：/ledger 总台账、/ledger/new 记总账、/ledger/reimburse 审批台，教务/管理员门禁)
- **收口实况（2026-09-17）**：`controllers/welfare.py` 的打卡实现**已退役为兼容入口**——
  ①  `/my/checkin`、`/my/checkin/export`、`/my/checkin/save` 全部 **303 → `/my/checkins*`**（GET+POST；写路由不再解析表单、不再落库）；
  ②  `/my/checkin/board` 保留 200（`base.group_user`），**数据源已从 `EduDailyCheckin` 换成** `edu.checkin.record` + 「到堂打卡」类型（`edu_life`）；
  ③  模型 `EduDailyCheckin`（表 `edu_daily_checkin`，7 条）**只读化石：既无写入口也无读入口，一行未删**。
  唯一打卡实现 = `edu_life`（见下）；弃用与「何时可彻底删除」见 `docs/audit/deprecated-inventory.md`
- **费用分类自助维护（2026-09-16）**：`models/fees.py` 的 `edu.fee.category`（name/code/sequence/active/**direction_hint 方向倾向**；照抄同构先例 `edu.download.category`）。后台菜单「财务管理 → 费用分类」由教务**自助增删**；账单侧的 `category`（写死的 Selection）已换成 `category_id`（m2o，`ondelete='restrict'`：被账单引用时删不掉、提示改用「停用」，历史账不丢分类名）。存量迁移在 `migrations/19.0.2.0.0/`（旧列快照 → 回填 → 删快照；跑完必须 `category_id IS NULL` = 0）。设计 `docs/plans/fee-categories-design.md`｜调研 `docs/research/fee-categories.md`｜断言 `tests/smoke/ledger_select_labels.py` + `tests/smoke/ledger_category_admin.py`
- `controllers/downloads.py` + `models/downloads.py`：**资料下载中心 v2.1（单页两态）**——/downloads 普通态=搜索/筛选/分页下载；教务处同页「管理模式」=两级文件夹 CRUD+批量上传（白名单/大小限系统参数可调）+批量删除/停用/恢复/移动+行内编辑换文件；审计 edu.download.log + 统计 /downloads/stats；**可见范围 v3**（2026-08-29 grill 定稿：四组勾选 visible_registrar/teacher/student/parent，管理员恒可见，_identity_fields 按身份判定——教师=group_op_faculty、家长=op.parent 绑定、门户非家长=学生、内部兜底教师口径；旧 audience 三档在 init() 等值迁移，列删除后自动跳过）；旧 /downloads/manage|upload 302 兼容跳转；设计见 docs/plans/downloads-v2-design.md
- `controllers/help_center.py` + `views/help_center.xml`：/help 四角色公开使用指南
- `controllers/my_password.py`：门户自助改密（走原生 change_password）
- `controllers/register.py`：/web/register 注册（EduInviteCode 邀请码）
- **学号登录通道（2026-10-12）**：`login_alias.py`（纯函数：`looks_like_gr_no` / `bucket_key` / `next_failure_state` / `blocked_seconds`）+ `models/login_alias.py`
  （`login_for_gr_no` 走 `edu.invite.code._edu_student_by_gr_no` → `edu_schedule.identity.users_of_profile` 拿登录名）+ `controllers/main.py` 的 `_edu_alias_login()`
  在 POST 前把「学号」改写成真实登录名（**邮箱登录一字未变**）。失败限速落库在 `edu.portal.login.throttle`（**跨 worker 共享**：进程内令牌桶在 `workers = 6` 下被稀释，实测第 9 次仍能登录 ⇒ 改落库），
  只统计失败（15 分钟 8 次 ⇒ 封 15 分钟），成功即删行。单测 `tests/unit/edu_portal_login_alias_test.py`（42 条）。
- `controllers/search.py`：全站搜索 + 语言切换
- **后台菜单/动作改名（2026-09-22）**：`views/menu_labels.xml` + `models/menu_labels.py` —— 259「院系」→**教职员工**（它的模型是 `op.faculty` 人事档案）、265「部门」→**院系部门**（`op.department` = 教务要建的院系）。
  ⚠ 硬知识：`noupdate=t` 的菜单记录上，**声明式 `<record forcecreate="0">` 与「PO + --i18n-overwrite」都会静默失效**（前者写不进；后者被 Odoo 的 noupdate 规则挡掉），必须走 ORM 并先把 `noupdate` 规范成 False；依据 `docs/ops/menu-rename-list.md` §0.1/§2.1/§3，证据 `tests/smoke/department_path.py` + `department_path_{before,after}.json`
- **后台菜单/动作/字段改名第二轮（2026-09-24）**：同一对文件 —— 字段 `op.department.parent_id`「家长部」→**上级院系**（`edu_zh` PO 定点覆盖，基座 `department.py:31` 只读）、`op.department.name`「姓名」→**名称**（同一张「新建院系部门」表单整表扫描补漏；该 msgid 被 14+ 字段共用 ⇒ 按 xmlid 钉死）、276+395→**培养方案**（`op.program`，与 263 `op.course` 的「专业」解耦，之后全库只剩 263 叫「专业」）、264+386→**班级**（`op.batch` = 一个班的学生，与 797「已停用班级」同实体）、298→**家长设置**（配置容器）、299+415→**亲属关系**、动作 414「父母」→**家长**（PO 词条漏写 xmlid 引用）。
  门禁口径：`tests/smoke/menu_label_audit.py --diff`（标签字面值 + 回归，**14 受影响 + 30 回归全绿**）；`tests/smoke/department_form_sweep.py`（**整表逐字**列标签，含「无 label 字段」这一口径 —— 见 `docs/ops/menu-rename-list.md` §3.5）。
  ⚠ 机制精确化：PO 词条**不是**按 msgid 全局生效，而是按 `#: model:<model>,<field>:<xmlid>` 引用落到**具体 xmlid**（Odoo 19 `odoo/tools/translate.py:1596-1600` + 1636-1646）——**漏写引用 = 没覆盖**（动作 414 就是这么停在旧译文的），**写清引用 = 定点覆盖、不牵连**（字段标签靠它）。
  门禁：`python3 tests/smoke/menu_label_audit.py --diff before.json after.json`（13 受影响 + 31 回归，全绿）；依据 `docs/ops/menu-rename-list.md` §0.2/§0.3/§2.2/§3.3/§3.4
- `views/`：batch1/2/3.xml 为页面模板主体；`edu_portal_templates.xml` 是公共外壳（**`edu_page` 模板 = 所有门户页的 t-call 外壳**）；`approval_backend.xml` 后台"教务审批"菜单；`downloads_*.xml`、`welfare.xml`、`calendar.xml`、`lms.xml`、`fees.xml` 等
- `models/`（25 个模型）：核心 EduLeave(请假+审批 action_approve/reject/reject_reason)、EduCertificate(EDU-CERT-%04d 序号)、EduNotice/EduNoticeRead、EduGrievance(申诉)、EduMessage、EduInviteCode、EduEval*、EduPointLog/**EduDailyCheckin（收口后只读化石，写路由已 303）**、**EduEval\*（收口后唯一评估引擎，见下）**、EduFeeBill/EduFeePayment、EduLesson/EduLessonProgress、EduAsset/EduAssetLoan、EduJobPosting/EduJobApplication、EduDownload*、EduEvent、EduFavorite(常用区收藏)、EduAuditLog(操作审计)；res.users 扩展 edu_ical_token；EduNotifyPref(通知偏好)、EduAttendSelfToken(自助签到令牌)；另有 OpSession/OpExamSession/OpAssignmentSubLine/ResPartner 等基座扩展
- `data/timetable_params.xml`、`views/menu_icons.xml`（应用面板渐变瓦片）、`static/src/img/icons/`（24+ 彩色 SVG，由 scripts/gen_icons.py 生成）

### edu_brand —— 品牌官网（公开页）+ 去 Odoo 品牌化
首页/about/programs/admissions/journal（校刊分页）/登录页品牌化。`views/pages.xml`(418行)+`brand_templates.xml`(239行)。**公开页文案改动需先跑 `scripts/setup_brand_yongyue.py` 本地验证**。
去 Odoo 品牌化（2026-08-29）：`odoo_debrand.xml` 全局替换 Powered by 徽标；`data_brand/brand_debrand_data.xml` 设校徽 favicon+公司 logo（注意 website.default_website 的 xml_id 自带 noupdate，已装库升级需一次性 ORM 写入，注释有记录）；`static/src/js/user_menu_debrand.js` 从注册表移除用户菜单 odoo.com 外链。

### edu_zh —— 汉化与术语覆盖（v3 新增）
汉化资源 `i18n_extra/zh_CN.po`、`zh_TW.po`：覆盖基座机翻硬伤 + **15 条 JS/code 词条**（走 `translatedTermsGlobal` 兜底通路，无需 JS patch）；升级必须 `--i18n-overwrite`（`__init__.py` 用源码行号说明：`post_init` 只在 install 跑）。术语口径：用户可见面「学费→统筹费」、币种 **USD→CNY**（按 `res.currency` 渲染，硬编码 `¥` 归零）；**混排品牌串**（如 core tooltip「转到您的Odoo应用程序」）由 PO 覆盖为「转到您的应用」。

### edu_public —— 公开功能页
/alumni 校友、/campus/jobs 职位+投递、/digital-library 数字图书馆、/courses-offered、/booking、/online-exams 等 13 路由。EduAlumniJob 等模型在 edu_portal 侧。

### edu_apply —— 报名入学
`/apply` 公开报名表：**元数据驱动**（EduApplySection/EduApplyField，九区30字段 noupdate 预置于 `data/form_meta_data.xml`，六核心字段 locked 守卫）；管理员后台"报名表设置"可视化增删字段/必填（`views/backend_views.xml`）；答卷 answer_json + 冗余检索列；提交即建 EduApplication + 五个子表（Education/Family/Ministry/Work）。

### edu_admit_invite —— 录取后发放入学码（**2026-10-14 新增；2026-10-14 已部署生产**）
极薄模块（4 个文件、**零新增路由/模型/表/ACL**）：`_inherit edu.invite.code` 只加 1 列 `application_id`（m2o `edu.application`，`ondelete='restrict'`，`unique(application_id)`）+ `_inherit edu.application` 加 2 个 object 按钮（发放入学码 / 重新发放）与 6 个非存储回执字段。发放 = `edu.invite.code.create(code_kind='tier', tier='student', use_limit=1, expire_at=now+14d)`；邮件走 `mail.mail.send(raise_exception=False)`（本机 `ir.mail_server` 0 行 ⇒ 只落 `state='exception'`，不向教务抛错）；无邮箱则不发信、页面回显码。设计见 `docs/plans/admission-invite-link-design.md` §18（任务书）+ §18.5（实测 54/54）。

### edu_life —— 灵命生活（打卡+周记）**= 唯一打卡实现**
EduCheckinType(daily/weekly+周目标)、EduCheckinRecord(学生×类型×日期唯一，拒未来日期)、EduJournalEntry(ISO 周唯一，draft→submitted→reviewed)。学生 /my/checkins 月历一键打卡、/my/journals；教师 /journals/review 批阅队列→评语、/checkins/stats 按班完成率统计。演示数据 `data/demo_life.xml` 幂等。
- **收口实况（2026-09-17）**：`/my/checkin*`（`edu_portal` 那套）已 303 并入本模块；「到堂打卡」类型由 `scripts/merge_checkins.py` get-or-create（**不在模块 data 里**，新库/重装需重跑，见台账）。
  实测：`edu.checkin.record` **53 条**、`edu.checkin.type` **4 条**（读经 24 / 灵修 22 / 到堂 7 / 周记 0）；`edu.daily.checkin` 7 条原样保留、不再被读写。
  ⚠ 已知副作用（已认账）：`/checkins/stats` 的 `avg_rate` 覆盖**所有 active 类型** ⇒ 新增「到堂」列后教师端平均完成率会变（t5 实测 45% → 40%）。

### ~~edu_eval —— 行政评估~~（**2026-09-29 已卸载并删除模块**）
**不存在了**：`custom_addons/edu_eval/` 整个目录、模型 `edu.admin.eval.template/.item/.score`、三张表、ACL 与 2 条 ir.rule、后台菜单 597–600、门户 `/eval/*` 六条路由 —— 全部已删（唯一评估引擎 = `edu_assess` 的 `edu.assess.*`）。
- **删除前置证据**（逐表读数 + 判据 + 可复跑命令）：`docs/audit/edu-eval-removal.md`。一句话：本地与生产**三张表均 0 行**；历史上只进过 2 条模板，**两条都叫「【演示】…」**（2026-08-24 一次性脚本批次，后随演示数据清理删除）⇒ 无任何非演示使用痕迹。
- **学生侧入口已并入新引擎**：首页「成长」组原「我的评分 / 评教填答」两卡**合成一张卡** → `/assess/my`（落点与删除前 303 的落点逐字相同）。
- 旧地址 `/eval/*` **现在是 404**（有意为之）：303 兼容壳随宿主 `edu_assess` 一起拆除 —— 壳自己的注释就要求"连同 import 一起删"。
- ⚠ **没动的东西**：`edu_portal` 的 **A 套 `edu.eval.*`**（旧地址 `/my/evaluation*` → 303 `/assess`，壳在 `edu_portal/controllers/eval_compat.py`）与本次删除无关，一行未动。
- ⛔ **残留引用（本轮可写范围之外，尚未处置）**：`scripts/deploy_myedu.sh`（3 处 `edu_eval`，**不改就跑不动部署**）、`scripts/gen_icons.py`、`tests/smoke/zero_loss_reachability.py` 与 `eval_rebuild.py`、`tests/_edu_eval_smoke.py`、`tests/audit/verify_*.py`、`scripts/{cleanup_demo_data,backup_a_eval_json,ui_surface_report,check_english,check_prod_menus,portal_token_map,gen_manual,test_life_eval}.py`、`README.md`。逐条影响与修法见 `docs/audit/edu-eval-removal.md` §6.1/§6.2。

### edu_schedule —— 排课工具（自研）
周期排课三步流 `/timetable/bulk`→`/preview`(不落库)→`/create` 批量建 op.session（**整周复制 `/timetable/copy` 已于 2026-09-15 按用户裁定删除** —— 与周期排课功能重叠、且从未被使用）；EduScheduleHoliday 停课日；OpSessionConflictExt 冲突检测视图。后台"排课"菜单仅教务处组可见（`views/menu.xml`）。周工具函数在 `models/week_utils.py`。

### edu_quiz —— 在线测验
EduQuiz/Question(单选·多选·简答)/Attempt；教师后台出题→学生 /quiz 作答→自动判分（单选比字母、多选比集合、简答关键词）→结果页。

### edu_nav —— 后台菜单收口（v-收口期新增，2026-09-17）
**菜单收口的唯一落地处**：`data/menu_consolidation_data.xml`（由 `scripts/gen_menu_data.py` 从 `docs/audit/menu-consolidation/menu-consolidation-plan.json` 生成，**禁止手改**）用「**目标菜单自己的规范 xmlid**」+ `forcecreate="0"` 覆盖各模块菜单的 `active / group_ids / parent_id / sequence`；`models/menu_consolidation.py` 是装载期守卫（红线自查 + 与 `ir.config_parameter edu_nav.consolidated_count` 对账）。
- **只改开关，禁止删除**：菜单记录数 605 → 605；根菜单 40 → 40（active 根 39 → 18）。
- 口径 B（前端可见根）：admin 38 → **14**、backoffice 31 → **12**（验收线 ≤12）、faculty 19 → **9**；student / parent 仍 0（它们走门户，不进后台）。
- ⚠ **未关闭的风险 F1**：`-u edu_portal` 等「自己的 XML 里声明了 groups/active」的模块会把收口值重放回来（backoffice 12 → 17）——实测复现与修复方向见 `docs/audit/finding-F1-menu-replay-on-upgrade.md`；复验 `python3 tests/audit/verify_upgrade_persistence.py --modules edu_portal,edu_life`。
- 结构校验与逐字段改动：`docs/audit/menu-consolidation/diff-report.md`（含 diff-report 与三个角色读数）。
- ⚠ **部署链缺口的实测取证（2026-09-29）**：`edu_nav` 原先既不在 rsync 列表、也不在 `-u` 列表 ⇒ 它的改动**上不了生产**（实测：生产的 `menu_consolidation_data.xml` 与本地 md5 不同、`website_menu_data.xml` 生产上根本不存在）。本轮**只补同步、不进 `-u` 列表**，两条实测理由：① 数据文件里有 4 条记录用 `account_payment` 等**5 个已卸载模块**的规范 xmlid 做键，`convert.py:_test_xml_id` 对跨模块引用未安装模块是**硬断言**（`forcecreate="0"` 也拦不住）⇒ 升级 `exit 255`；② 就算能装，同一次 `-u` 里它排在 `edu_portal` **之前**（`Loading module edu_nav (2/115)`，顺序由 `ModuleGraph` 的 `(phase, depth, name)` 决定）⇒ 赢不了"最后写者"。前置条件（重新生成数据文件 + 独立容器排在主升级之后）见 `docs/audit/menu-consolidation/deploy-shipping-gap.md`。

### edu_tg_bind —— Telegram 发注册码机器人（**2026-09-17 新增；本地已装，未部署生产**）
学生私聊机器人 → 回他一张**学生层级邀请码** → 他去 `/register` 用码注册。**一个 TG 账号只能领一张**（数据库唯一约束 `unique(chat_id)` + `unique(invite_code_id)`，不是 if 判断）；同一个人再来 = **回显原码**。
- `models/tg_claim.py`：`edu.tg.claim`（chat_id 存**字符串**——TG 用户 id 超 32 位，Integer 落 int4 会溢出）+ 码池选取（`FOR NO KEY UPDATE SKIP LOCKED`）与冲突重试；`models/tg_bot.py`：Bot API 出网（`requests`，**不走** `edu_telegram_outbox`）。
- `controllers/webhook.py`：**`/telegram/tgb/webhook`**（`auth='public'` + 官方头 `X-Telegram-Bot-Api-Secret-Token` + **fail-closed**：secret 未配一律 403）；只处理私聊，群/频道忽略。
- 参数 `edu_tg_bind.token / webhook_secret / pool_batch_prefix / register_url / dry_run`；后台入口挂在 学生信息(257) → 配置(261)（教务 + 系统管理员）。
- **学生版新手教程（2026-10-12）**：`models/tg_claim.py` 的 `_tutorial_lines()` 把三步教程拼在领码文案后（1 用码注册 → 2 用**邮箱或学号**登录 → 3 忘记密码去 `/help/student`），
  `reply_keyboard()` 追加两键「🔑 去登录」（`/login`）与「📖 使用指南」（`/help/student`）；原文案逐字保留（无测试断言原文，但有独立单测覆盖码形状与幂等）。
- ⚠ **Odoo 19 隔离级别是 REPEATABLE READ** ⇒ 裸 `SKIP LOCKED` 不够（实测复现），必须叠加唯一约束 + 整事务回滚后重试；三条技术选择（出网/并发/鉴权）的实测依据见设计文档。
- 设计：`docs/plans/tg-invite-bot-design.md`。**与生产匿名意见箱、与本仓 v2.2 都无关**（见下两段）。

### edu_tg_gate —— Telegram 前门分发（**2026-10-08 新增；为复用 @sctrs_bot**）
一个 Telegram 机器人只能挂**一个** webhook，而 @sctrs_bot（edu_tg_bind）与 edu_tg_assist 都要收消息
⇒ 新增这个**纯分发层**：Telegram → `/telegram/sctrs/webhook` → 按判据转给两边。
- **无模型、无表、无 ACL、无 data**；`depends ['edu_tg_bind']`（assist 走**运行时** `env.get('edu.tg.assist.bot')`，
  刻意不写进 depends ⇒ assist 缺失时前门退化成「私聊一律 bind、群消息忽略」，学生流不受影响）。
- `routing.py` 是**纯函数**判据（不 import odoo），单测 `tests/unit/tg_gate_router_test.py`（**60 条**断言）：
  `callback_query` / 群消息 / 已登记教职工 / 白名单指令（`/assist /bind /bindcode /dm /name /notify /tpl /whoami`）→ assist；
  **其余（含 `/start`、`/help`、自由文本）→ bind**（fail-safe：学生流逐字不变）。
- **深链载荷判据（2026-10-12）**：`/start <载荷>` 若载荷匹配 `edu_tg_assist.bind_code_payload` 参数里的正则（默认 `^BIND-[A-Z0-9]{6,6}$`，唯一来源 `edu_tg_assist/bindtext.py` 的 `PAYLOAD_RE`）⇒ assist，
  其余 `/start`（含 `ref_…`、`STU-…`、空载荷）⇒ bind。老师点 `https://t.me/sctrs_bot?start=BIND-XXXXXX` 一次完成绑定，**学生领码流一个字节都没动**。
- `controllers/gate.py`：鉴权照抄 bind（官方头 `X-Telegram-Bot-Api-Secret-Token` + `hmac.compare_digest` + 未配一律 403）。
- 参数 `edu_tg_gate.webhook_secret`。**bind 的旧路由 `/telegram/tgb/webhook` 保留**（一键回滚）。
- 与 bind 的共用实现：`edu.tg.claim.handle_private_message(message)`（自带路由与前门**单实现双调用**）。
- 代价与边界 B7/B8 见 `docs/plans/tg-assist-bot-design.md` §9。

### edu_tg_assist —— Telegram 班务机器人（**2026-10-08 接入；2026-10-10 加打卡闭环、上手/运营整改与材料归档 F7；2026-10-12 加身份绑定码与新手教程**）
与 @sctrs_bot **共用同一个 bot**，由 `edu_tg_gate` 前门按判据分发（见上）；`depends ['base']`，与 edu_tg_bind / edu_telegram **零共享**（设计文档 §2 B1–B8）。
- 表：`edu.tg.assist.{chat,person,reminder,template,mention,reply,dm,notify,send_log,update_log,poll,poll.reply,material}` + `api` / `bot` / `selfcheck`（瞬态，后台「自检」）/ `llm` / `notion` 等无表服务模型；
  控制器 `/telegram/assist/webhook`（secret 头 + fail-closed）；出网照抄 `edu_tg_bind`（容器直连 api.telegram.org，**不走** outbox）。
- **Mini App 面板（2026-10-13，§9.17）**：`/edu_tg_assist/app`（页面，GET）+ `/edu_tg_assist/app/api`（JSON，POST，**initData 验签**；纯函数 `miniapp_auth.py`）；
  SDK 自托管在 `custom_addons/edu_tg_assist/static/vendor/telegram-web-app.js`（2026-10-14 修「no initData」，设计 §9.20）。
- **面板「定时群发」（2026-10-14，设计 §9.21）**：面板主菜单新增 ⏰ 定时群发；动作 `reminders / reminder_create / reminder_toggle / reminder_run / reminder_delete`
  （整族属 `ADMIN_ACTIONS`）；后端一条 `edu.tg.assist.reminder.quick_create(chat, body, weekday, hour, minute)`（正文 → 复用或新建模板 → 建规则，规则自带 ir.cron）；
  「立即发一次」复用 `_do_send(kind='manual')`；**不新增表 / 路由 / 参数**，depends 仍只有 base；单测 `tests/unit/tg_assist_reminder_panel_test.py`（57 条）。
  权限三层：任何人（whoami/help/groups）、教职工（materials/forward）、行政（notify/dm/staff/reminders 族），越权写 `denied` 审计；
  入口 = 底部键盘最后一行的 `web_app` 按钮（`menutext.reply_keyboard`，只在私聊有效）。两条路由是**常量式**声明 ⇒ `check_ui_surface.py` 看不见，不登记 `tests/ui/surface.json`（已知形态）。
- **指令自动发现**：模型实现 `_tg_assist_commands()` / `_tg_assist_group_commands()` / `_tg_assist_handle_callback(cq)` 即被 `models/bot.py` 收进注册表
  （**必须记住注册者模型**，否则 `getattr` 落空被控制器兜住 = 静默失败）。回调前缀两套：`ck:` = @提醒待办、`p:` = 打卡（两张表、两个解析函数，互不抢）。
- **打卡闭环（2026-10-10）**：`reminder.with_buttons` → `_do_send` 建 `edu.tg.assist.poll` → `send_message_full` 拿 `message_id` → `_mark_sent`；
  点击落 `poll.reply`（唯一约束 `unique(poll_id, tg_user_id)`，重复点改选项）；统计口径 = 「人员映射」里 `role` 相符且 active 的人；
  `callback_data` 超 Telegram 64 字节时**放弃按钮、降级纯文本**（宁可没有按钮，也不能整条被拒）。
- **上手/运营整改（2026-10-10，§9.10）**：`/stop`（私聊停发：person `active=False` + 清空 `chat_id`，再 `/start` 恢复）、群内 `/alias`（给当前群起短名，撞名拒绝不覆盖）、
  `/cmd_name` 给学生的回头提示、`/dm`/`/notify` 回执带角色与 `message_id`；后台新增「自检」（瞬态模型 `edu.tg.assist.selfcheck`，只读，调 getMe/getWebhookInfo）与
  「清理发送记录」（默认**开**的 cron，参数 `edu_tg_assist.send_log_keep_days` 默认 90、0 = 不清）。**注意 `/stop` 归档的人仍必须走班务流** ⇒
  `edu_tg_gate/models/router.py` 的 `_staff_chat_ids()` 与 `person.upsert_from_user()` 查人一律 `with_context(active_test=False)`。
  另有 `api.selfcheck_lines()`（token 只报长度）、`send_log._prune_old()`/`action_prune_now()`。
- **材料归档 F7（2026-10-10）**：老师私聊**转发**文本/文件 → `models/bot.py` 私聊挂点 `_note_private_message()` 自动发现 `material._tg_assist_note_private_message()`
  （**空文本**与**不是指令**两条路都先问挂点；学生与未知角色返回 `None` ⇒ 走原路，B12）→ 建 `edu.tg.assist.material`（`state=new`）→ cron「材料分类归档」（1 分钟）
  `_analyze_one()`：规则抽取（`mattext.rule_extract`）必做，`llm_configured()` 且非 dry_run 才脱敏后走 `edu.tg.assist.llm`（OpenAI 兼容 `/chat/completions`）→ `_push_notion()` 可选导出。
  纯函数全在 `custom_addons/edu_tg_assist/mattext.py`（脱敏 / JSON 宽容提取 / 字段净化 / 中文日期 / 规则抽取 / Notion payload）；
  边界 **B9–B12**：`llm_*`/`notion_*` 参数没配齐 = **零出网**、出网前必脱敏、原文只存本库（送 Notion 默认只送摘要+关键信息）、归档只对教职工私聊生效；
  表**只给 `base.group_system`**（含原文，不开放只读）；参数 `edu_tg_assist.{llm_base_url,llm_model,llm_api_key,llm_timeout,llm_max_chars,notion_token,notion_db_id,notion_api_version,notion_parent_type,notion_enabled,notion_include_raw,material_keep_days,material_auto_analyze}`；
  Notion 属性对不上 schema 时**自动降级**成保底 `title`+正文块重试一次（`notion_fallback`）。设计 §9.11、调研 `docs/research/ai-archive-and-notion.md`。
- **身份绑定码与新手教程（2026-10-12，§9.12）**：表 `edu.tg.assist.bindcode`（码 `BIND-XXXXXX`、一次性、默认 14 天有效；纯函数在 `bindtext.py`）——
  管理员 `/bindcode 教师 张三` 出码 + 深链，老师点深链或手输 `/bind <码>` 一次绑定「姓名 + 角色」，之后不再需要管理员手工标注；
  `models/bot.py` 的 `help_text()` 按身份分版（教职工版 / 未登记版），`/help` 与 `/start` 都回它；教程里写明**密码只在网站登录页输入、绝不在聊天里发**。
- **网站侧权限组（2026-10-13，§9.15）**：`security/assist_security.xml` 新增 `group_assist_manager`「班务机器人管理员」（**不隐含 `base.group_system`**），
  `security/ir.model.access.csv` 追加 14 行（配置类 1,1,1,1、审计类 1,0,0,0 = 能看不能改）；根菜单 630 的 `groups` 扩为 `edu_tg_assist.group_assist_manager,base.group_system`；
  离线断言 `tests/unit/tg_assist_security_test.py`（26 条）；给教务开账号 = `edu_portal.group_backend_full` + `openeducat_core.group_op_back_office_admin` + 本组（生产无 `ir.mail_server` ⇒ 初始密码只能人工交付）。
- **站内通知桥（对接选项 b，2026-10-14，§9.18）**：`models/bridge.py` 两张表 —— `edu.tg.assist.bridge`（规则：事件名/发给谁/水位/sent_count）
  + `edu.tg.assist.bridge_log`（`unique(rule_id, message_id)`）。**门户一行代码都不改**：`edu.message` 只读、按 id 水位轮询
  （新规则或重新启用时把水位推成当前最大 id ⇒ 不回放历史），cron `cron_bridge_edu_message` 每 2 分钟；
  `edu.tg.assist.person` 新增 `user_id`（网站账号）供 `target='recipient'` 找人，**查不到就跳过、绝不猜**；
  B9 禁读清单 `edu.feedback` / `edu_telegram` / `edu.tg.claim` / `edu.tg.bot` / `edu.invite`（`_check_source_allowed` fail-closed），B10 只发文字且照旧进 `send_log`。
- **网站公告 → Telegram 群（对接选项 a，2026-10-14，§9.19）**：`edu.notice.channel_telegram` 勾上后，门户 `_send_channels()` 先按模型名探本模块在不在
  （`'edu.tg.assist.bridge' in self.env`，**门户没有 depends、没有 import**），在则调 `bridge.push_site_notice(notice)`，发给 `edu.tg.assist.chat` 里
  勾了 `notice_enabled`（「接收网站公告」）的启用群；探不到才回退旧路 `op.telegram.chat → edu.telegram.outbox`（生产上没有前者的模型，异常一律吞掉）。
  **公告不能用 id 水位轮询**（与 b 的差别）：`edu.notice.active=False` 是「未发布」载体，草稿先建、几天后发布的 id 会落在水位之下而永漏发 ⇒ 改成发布那一刻主动调用。
  出网仍走 `api.send_message(..., kind='notice')`，自动进 `send_log`。
- 设计 `docs/plans/tg-assist-bot-design.md`（§3 能力 / §5 表 / §9 接线与裁定变更 / §9.9 打卡 / §9.10 上手与运营 / §9.11 材料归档 F7 / §9.12 绑定码与学号登录 / §9.15 网站侧权限与教务账号）；大白话 `docs/ops/tg-assist-bot-howto.md`；
  离线单测 `tests/unit/tg_assist_poll_test.py`（27 条）、`tests/unit/tg_assist_text_test.py`（26 条）、`tests/unit/tg_assist_material_test.py`（72 条）、`tests/unit/tg_assist_bindcode_test.py`（33 条）、`tests/unit/tg_assist_notice_test.py`（31 条）。

### edu_telegram —— 「Edu Telegram Bot」v2.2 四角色教务前端（**从未部署；2026-09-17 用户裁定退役**）
`op.telegram.chat` / `edu.telegram.binding` / `edu.telegram.flow` / `edu.telegram.push` / `edu.telegram.outbox`（Outbox 推送队列 + `data/cron.xml`）+ `op.leave.request`/`op.notice` 扩展；webhook **`/telegram/webhook`**（`controllers/main.py:990`）；教师门户 ops `/my/rollcall`、`/my/marks`、`/my/subject-reg`；绑定页 `/my/telegram`；中继脚本 `scripts/telegram_relay.py`（宿主常驻，认领 `edu_telegram_outbox`）。
- ⚠ **同名不同物（本项目最容易踩的雷）**：**生产上跑着的 `edu_telegram` 是另一个模块** —— 匿名意见收集机器人（`edu.feedback` / `edu.feedback.session` / `edu.telegram.outbox`，参数同样叫 `edu_telegram.*`，webhook 路由同样是 `/telegram/webhook`）。它的匿名性建立在「**不保存明文 chat_id、只存 HMAC 指纹**」上。**本仓这套与它无关**（不共享代码），但**两边路由与参数同名** ⇒ 部署本仓 v2.2 会与生产意见箱**抢路由**。
- **退役处置（doc-only，零删除）**：不删文件、不改代码；台账登记见 `docs/audit/deprecated-inventory.md` §0.1 与 **B8**。
- 新的「学生私聊领注册码机器人」是**第三个模块**：`edu_tg_bind`（路由 `/telegram/tgb/webhook`、参数 `edu_tg_bind.*`，设计见 `docs/plans/tg-invite-bot-design.md`）——与意见箱、与 v2.2 **都不共享**。

### 依赖关系（manifest depends，已核验 2026-08-29）
```
edu_assess ──> edu_portal ──> website + openeducat_core/erp
edu_brand   ──> website, theme_web_openeducat          （不依赖 edu_portal）
edu_public  ──> website, openeducat_core/exam/library  （不依赖 edu_portal）
edu_apply   ──> website, mail                          （不依赖 edu_portal）
edu_life    ──> website, mail, openeducat_core         （不依赖 edu_portal）
edu_schedule──> openeducat_timetable, website         （不依赖 edu_portal）
edu_quiz    ──> openeducat_core/exam, mail             （独立）
edu_telegram──> openeducat_core/exam/library/fees/attendance（独立；**已退役**，见上）
edu_tg_bind ──> edu_portal（要用 edu.invite.code；**不依赖** edu_telegram）
edu_tg_gate ──> edu_tg_bind（前门只做分发；对 edu_tg_assist 是**运行时**检查，不是 depends）
```
> 注意：跨模块引用符号（如 batch2.py 里的卡片导航）是运行时 env 查找，不是 manifest 依赖——新增 depends 前先查实际 manifest。

### 基座 openeducat_erp（14 个官方模块，原则上不改，只用/继承）

| 模块 | 职责与关键模型 |
|---|---|
| openeducat_core | 学生/教师/课程基座：op.student、op.student.course、op.faculty、op.course、op.batch、op.subject、op.subject.registration、op.department、op.program、op.category、op.academic.year/term（均在 `openeducat_core/models/`） |
| openeducat_timetable | op.session（课表节次）、op.timing（时段定义） |
| openeducat_attendance | op.attendance.register/sheet/line（考勤三件套） |
| openeducat_exam | op.exam、op.result.line（考试与成绩行） |
| openeducat_assignment | op.assignment |
| openeducat_admission | op.admission、op.admission.register |
| openeducat_library | op.media、op.library.card |
| openeducat_fees | op.fees.terms、学生费用明细 |
| openeducat_parent | op.parent（家长门户） |
| openeducat_classroom | op.classroom、op.asset |
| openeducat_activity / facility | op.activity / op.facility |
| openeducat_erp | 聚合入口；theme_web_openeducat 前端主题 |

**权限组**（`openeducat_core/security/op_security.xml`）：
- `openeducat_core.group_op_faculty` 教师（imply group_user）
- `openeducat_core.group_op_back_office_admin` 教务处/Manager —— ⚠ **基座源码里它 imply `base.group_system`**（`op_security.xml`），本仓已于 **2026-09-17 解除**（`custom_addons/edu_portal/views/group_tuning.xml`：`(3, ref('base.group_system'))` + 改为隐含「教师 + partner_manager + 考勤/课表/图书馆/考试 各 user·manager」）。**改基座快照或重装模块时务必确认这条解除仍在**（判据 = 教务组 implied 传递闭包不含 `base.group_system`）。四层定义与挂层规矩见 `docs/plans/perm-model.md`
- 家长：`openeducat_parent.group_op_parent_manager`
- 数据隔离：`student_login_rule` ir.rule（学生只见自己数据）

## 4.1 收口实况与锚点（2026-09-17，防复发用）

> 逐条台账（保留原因 / 替代路径 / 何时可彻底删除 / 删除前置条件）见 **`docs/audit/deprecated-inventory.md`**。
> 本节只给**锚点**：台账里每条都回指这里的一个 id，便于两边对不上时当场对账。
> 读数口径：菜单 id 取自本地库 `edu19`（只读 SELECT）；「可见」= 前端 `load_menus` 口径
> （`tests/audit/out/after_result.json`，采集 **2026-09-17 14:25:07**；独立验证报告见
> `docs/audit/consolidation-verification.md`，t2 最终口径落库 commit `682d3a1`）。
> **跨天/跨修复窗口引用时请重跑** `python3 tests/audit/verify_consolidation.py --phase after`。

**入口现状（被保留 / 被隐藏，一眼可查）**

| 菜单 id | 名称 | 处置 | 现在从哪走 | 锚点 |
|---|---|---|---|---|
| 257 | 学生信息 | **保留**（容器，接收 278 / 542 / 606 的子树） | 唯一 `op.student` 后台根；`278 学生`已停用 | `CM-257` |
| 278 | 学生（`op.student` 第二根） | 隐藏（整棵停用，记录保留） | → 257 学生信息 | `CM-278` |
| 341 | 时间表 | **保留**（容器，接收 349 / 288 / 325 / 576 / 504 的子树） | 教学唯一后台根 | `CM-341` |
| 588 | 综合评估 | **保留**（容器，接收 597 的子树） | 评估唯一后台根；`597 行政评估`已随模块删除（2026-09-29），子树 598–600 同去 | `CM-588` |
| 593 | 灵命生活 | **保留**（容器，接收 543 的子树） | 打卡/积分唯一后台根；`543 日常管理`已停用 | `CM-593` |
| 608 | 资料下载 | **保留**（独立根；注意库内 0 条资料） | `/downloads` | `CM-608` |
| 300 | 招生 | **保留**（容器，接收 591 的子树） | 招生唯一后台根；`591 招生报名`已停用 | `CM-300` |
| 497 / 579 / 582 / 585 / 310 | 教务审批 / 财务管理 / 资产管理 / 招聘管理 / 图书馆 | **保留**（独立根） | 各自门户与后台 | `CM-497` 等 |
| 218 | 网站 | **保留**（容器，接收 83 / 357 / 372 / 507 的子树） | 网站与沟通唯一后台根 | `CM-218` |
| 1 / 15 | 设置 / 应用 | 保留但**仅超管**（根 + 全部子树挂 `base.group_system`） | 超管登录可见 | `CM-1` |
| 121 / 142 / 196 / 566 | 联系人 / 发票 / 员工 / 数据清除 | 隐藏给非超管（`121/142/566` 整棵停用；`196` 仅超管可见） | 需要时用超管登录 | `CM-121` 等 |
| 16 / 75 / 214 / 388 / 434 / 529 / 547 | 测试 / 链接追踪器 / 仪表板 / 招聘(HR) / 销售 / 出勤(HR) / 在线学习 | 隐藏（原生噪音，数据 0 或已停用） | 不对外开放，记录保留 | `CM-16` 等 |
| 83 / 357 / 372 / 507 / 504 / 288 / 325 / 349 / 576 / 591 / 597 / 543 / 542 / 606 / 278 | 15 个被合并的根 | 隐藏（子树已迁入容器） | 见各容器行的「现在从哪走」 | `CM-merged` |

**口径 B（前端可见根菜单）实测**（`tests/audit/out/after_result.json`）：

| 角色 | 收口前 | 收口后 | 验收线 |
|---|---|---|---|
| admin | 38 | **14** | ≤20 ✓ |
| backoffice（教务） | 31 | **12** | ≤12 ✓ |
| faculty（教师） | 19 | **9** | — |
| student / parent | 0 | 0 | 走门户，不进后台 |

- admin 可见根：1 设置、15 应用、218 网站、257 学生信息、300 招生、310 图书馆、341 时间表、497 教务审批、
  579 财务管理、582 资产管理、585 招聘管理、588 综合评估、593 灵命生活、608 资料下载（共 14 条，**含仅超管的 1/15**）。
- backoffice 可见根：上表去掉 1 与 15（共 12 条，正好压线）。
- faculty 可见根：257、300、310、341、497、582、585、588、593（共 9 条）。
- ⚠ **口径会随档2 模式变动，引用时必须带采集时刻**：
  · 档2 = 全部 `restrict_tree`（只挂 `base.group_system`，不整棵停用）⇒ admin 18 / backoffice 12 / faculty 9
    （这是 `48e74bd` 落库并按守卫脚本与队长 psql 三读一致的版本）。
  · 档2 = 混档（**最终口径**：`1/15` 仅超管；`121/142/196/566` 整棵停用）⇒ admin **14** / backoffice 12 / faculty 9
    （独立验证 `tests/audit/out/after_result.json`，采集 **2026-09-17 14:25:07**，即 `682d3a1` 落库后的读数）。
  · 两种情况都满足验收线（backoffice ≤12、admin ≤20），**但"14"与"18"不是同一个口径，不能混用**。
- ⚠ 这些数字**依赖 `edu_nav` 的重放**：跑一次 `-u edu_portal` 会被打回 23 / 17 / 12（F1，未关闭）。

---

## 5. 路由速查（高频入口）

| 域 | 路由前缀 | 文件 |
|---|---|---|
| 学生门户 | /my/home, /student/*, /my/* | edu_portal batch1/2/3.py |
| 教师/教务 | /attendance/*, /assignment/publish*, /leave/approvals[/<id>], /leave/set_state, /grievances/approvals[/<id>], /grievances/set_state, /notice/publish*, /grading/* | edu_portal roles.py |
| 排课 | /timetable/bulk*, /student/timetable | edu_schedule/main.py, edu_portal/scheduling.py |
| 灵命/打卡 | **唯一实现**：/my/checkins*, /my/journals*, /journals/review*, /checkins/stats, /checkins/stats/export | edu_life/life.py |
| 打卡旧入口（**兼容层，勿再挂新功能**） | /my/checkin、/my/checkin/export、/my/checkin/save → **303 /my/checkins***；/my/checkin/board 保留 200（数据源=edu.checkin.record+到堂） | edu_portal/welfare.py |
| 评估（现状） | 唯一引擎 = `edu_assess`：`/assess`、`/assess/my`、`/assess/review`…；A 套旧地址 `/my/evaluation*` → **303 /assess**（兼容壳 `eval_compat.py`）；**B 套 `/eval/*` 已随模块删除 ⇒ 现在 404** | edu_assess/controllers/portal.py、edu_portal/evaluation.py |
| 岗位（现状） | `/campus/jobs*`（`edu.job.posting`，在用）；`/alumni/jobs*`、`/alumni/job/list`（`edu.alumni.job`，**待合并**，设计见 jobs-merge-design.md） | edu_public/main.py、edu_portal/roles.py |
| 公开官网 | /, /about, /programs, /admissions, /journal, /contactus | edu_brand/main.py |
| 公开功能 | /alumni*, /campus/jobs*, /digital-library* | edu_public/main.py |
| 报名 | /apply, /apply/submit | edu_apply/main.py |
| 其他门户 | /my/messages, /my/contacts, /my/calendar, /my/fees(统筹费+我的报销同页), /my/reimburse/apply(发起报销), /my/assets, /my/courses, /my/points, /my/grievances, /downloads, /help/*, /my/password, /quiz*, /quiz/my | 各对应模块 |
| 财务总账(教务) | /ledger, /ledger/new, /ledger/new/save, /ledger/reimburse, /ledger/reimburse/set, /ledger/export | edu_portal controllers/ledger.py |
| 导出/订阅 | /student/attendance/export, /my/time_off\|grievances\|fees\|checkin/export, /my/checkins/export(edu_life), /checkins/stats/export(edu_life), /downloads/mine\|stats/export, /my/calendar/ics/<token> | 辅助增强包批次1 |
| 治理/管理 | /edu/audit(教务审计查询), /assignment/manage\|edit/<id>\|submissions/<id>(教师作业管理), /my/favorites/save | 辅助增强包批次3/4 |
| 第 5 批 | /my/notify(通知偏好), /attendance/selfcheck/start\|stop\|/<token>(QR 自助签到), /edu/import/students(学生导入两段式) | 第 5 批 A/B/F |
| Telegram（v2.2，**已退役**） | /telegram/webhook, /my/rollcall\|marks\|subject-reg, /my/telegram | edu_telegram |
| **Telegram 发码机器人（2026-09-17 新增）** | **/telegram/tgb/webhook**（鉴权：官方 secret 头；只认私聊）——**2026-10-08 起 Telegram 不再打这条，保留作回滚** | edu_tg_bind |
| **Telegram 班务机器人（2026-10-08 接入；2026-10-10 加打卡）** | **/telegram/assist/webhook**（同样 secret 头 + fail-closed；私聊指令 / 群广播 / 按钮回填 `ck:` + 打卡按钮 `p:`） | edu_tg_assist |
| **Telegram 前门分发（2026-10-08 新增；@sctrs_bot 现在打这里）** | **/telegram/sctrs/webhook**（secret 头；按 routing.py 判据转 bind 或 assist） | edu_tg_gate |
| **Telegram Mini App 面板（2026-10-13 新增）** | **/edu_tg_assist/app**（页面）+ **/edu_tg_assist/app/api**（JSON，initData 验签）—— 常量式声明，surface 门禁看不见，属已知形态 | edu_tg_assist |
| **学号登录（2026-10-12）** | `/login` 与 `/web/login` 的 POST 支持「**学号 + 密码**」（内部改写成该账号的登录名；邮箱登录不变；失败限速落库 `edu.portal.login.throttle`） | edu_portal |
| **v3 新增（2026-09-12）** | `/login`、`/apps`、`/register`（友好别名，旧 `/web/login`、`/web/register`、`/openeducat/apps_menu` 302 兼容）；`/my/apps`（全量功能页，承接旧首页 35 张卡）、`/my/study`（课程中心：课节/入会/资料/成绩）、`/my/study/<id>`、`/my/study/session/<id>/join`；`/downloads/need-ack/<id>`、`/downloads/ack/<id>/save`、`/downloads/unacked/<id>[/export]`、`/downloads/remind/<id>/save`（需确认已读闭环） | edu_brand（别名）、edu_portal（my_apps/study/downloads）、edu_apply |
| **入口收口（2026-10-13）** | 裸 `/web`、`/odoo`（无 subpath、无 `menu_id`、无 `redirect`）**服务端 303 → `/apps`**（原来会先渲染整页后台外壳再跳 = 用户看到的「一开进来先闪一下蓝顶栏」）；教务/管理员登录落点由 `/web` 改为 `/apps`；后台深链 `/odoo/action-<id>`、`/odoo/settings`、`/web?menu_id=…` 原样 200；门户侧栏「管理后台」（`href="/web"`）入口撤下（元素留作扩展点壳 `t-if="False"`，规则见 §6 第 19 条） | edu_portal（`controllers/main.py` 的 `EduHomeRedirect.web_client` / `_login_redirect`）、edu_brand（`edu_action_href`） |
| **排课链路改造（2026-10-14）** | **`/timetable/coverage`** + **`/timetable/coverage/unfilled`**（G2 覆盖看板与未排课清单 CSV；只读、教务/系统组，其余身份 303 `/my/home`）；**`/my/availability`** + **`/my/availability/save`** + **`/my/availability/delete`**（G4 教师自助登记不可用时间，写 `resource.calendar.leaves`；无 `op.faculty` 档案者 303）；**`/edu/enroll/pool_mode`** + **`/edu/enroll/pool_mode/save`**（G1 报课池三档 `off/annotate/strict` 的教务设置页，改档位直读参数表即刻全站生效） | edu_schedule（`controllers/coverage.py`、`views/availability_views.xml`）、edu_portal（`controllers/availability.py`、`controllers/enroll_settings.py`） |

## 6. 约定与铁律（违反会返工）

1. **Odoo19 新语法**：字段 `group_ids`（不是 groups_id）、视图 `<list>`（不是 tree）、`invisible="expr"` 新表达式——曾因 groups_id 炸过 registry。
2. **sudo 用法**：Odoo19 `sudo()` 在 recordset 上，不在 Environment 上（`env.sudo()` 会 AttributeError）。
3. **权限**：不建自定义组，复用 `base.group_portal/group_user/group_system` + `openeducat_core.group_op_back_office_admin`（=教务处）；ACL 写各模块 `security/ir.model.access.csv`；控制器用 `current_student()/current_faculty()/current_parent()` 判空分流，不做组判断；**门禁型管理页**（公告发布/请假审批/申诉处理/资料管理）用 `roles.privileged_staff()`（教务处组或 system 组）放行管理员=最高权；需要教师班级数据的页面（考勤/成绩/作业）仍要求 op.faculty 绑定。
4. **门户页面**：模板外壳 `t-call="edu_portal.edu_page"`；写操作走兄弟路由 `/xxx/save` + csrf。
5. **种子脚本** `scripts/seed_*.py` 必须幂等（可重复 -u）；演示数据必须带【演示】标记。
6. **品牌红线**：联系方式只允许 scrtsschool@gmail.com 等永约学坊真实资料；电话/地址未公开确认的不得编造；老学院资料一律清除。
7. **新功能三件套**：models/controllers/views 各一文件，先写 `docs/plans/<功能>-design.md` 再动工（六步闸门见 dev-workflow.md）。
8. **图标**：统一渐变瓦片 SVG 由 `scripts/gen_icons.py` SPEC 驱动生成，别手画。
9. **升级一律走 `bash scripts/safe_upgrade.sh <模块>`**（不要直接 `docker compose exec web odoo ...`）：exec 绕过 entrypoint 会缺 DB 参数、不传 `--no-http` 会撞 8069、`-u` 对未装模块无效（脚本默认 `-i`）。脚本内置**挂载新鲜度自检**——Docker Desktop 偶尔让容器读到旧内容（表现为 `manifest not found` / `not installable, skipped` / `inconsistent states`，**而退出码仍是 0**），脚本发现失步会强制重建容器，仍失步则 exit 4；升级后还会扫输出里的失败特征并 exit 5。手工绕过脚本时若见上述症状，执行 `docker compose up -d --force-recreate web`。
10. **无障碍（2026-09-14 起为硬约定，违反即被门禁点名）**：新增/改动控件必须带**可访问名** —— 表单控件用 `<label for>`+`id`（首选）或 `aria-label`；**图标按钮必须命名**（`aria-label`/`title`，纯装饰图标加 `aria-hidden="true"`）；**图片必有 `alt`**（有信息写内容，纯装饰写 `alt=""`）；正文内的行内链接不能**只靠颜色**与周围文字区分（加下划线）。门禁：`python3 scripts/check_accessibility.py`（2026-09-28 起扫描集见 `check_accessibility.py` 的页面清单，**2026-10-04 实测 72 页** × axe 4.10.2，含 **2 页后台** `/odoo/contacts`、`/odoo/students`；**BASELINE 已收到 0** ⇒ 任何一条新违规立刻报警；读数必须带指纹 + 时刻）。**后台页两层口径**：外壳 `.o_navbar` 的 color-contrast + 未登记规则 + 本地对比度检查 `shell-contrast` = **判据（零容忍）**；Odoo 核心渲染的主体/ARIA（role-img-alt、label、meta-viewport、html-has-lang、role=menu…）**只读数**（逐条打印 + 出现新规则即判红）。⚠ 覆盖盲区已实证：axe 的 color-contrast 对 `disabled` 控件内的文字**结构上不判**（`isDisabled` 向上继承；本库单公司 ⇒ 公司切换器按钮是 `disabled`）⇒ `.oe_topbar_name` 只能靠本地检查兜住；细节与本轮修复见 `tests/smoke/UX_V3_GATE.md` §11。改配色时：正文/按钮文字按 **4.5:1**、大字与大色块按 3:1，**不要动 `--brand-500` 等品牌主色**（交互面另有 `--brand-action`）。**修复优先公共 partial**（实测：门户共享语言切换器一处 `aria-label` 覆盖 22 页；共享搜索按钮一处命名覆盖 20 处）。
    · **后台核心渲染项：已修 6 类，剩 3 类只读数（2026-09-29）**。已修（都在 `custom_addons/edu_brand/`，只做属性级 / slot 级改动，**不碰核心组件**）：`role-img-alt` 88→0、`meta-viewport` 2→0、`html-has-lang` 2→0、`button-name` 1→0、`aria-allowed-attr` 4→2、**`label` 81→0（AX 树口径）**。
      · **`label` 的读数 ≠ 缺陷面（判据口径，务必照抄）**：axe 只对**首屏可见行**判违规 —— 同一页视口 900px 报 **19** 条、2700px 报 **63** 条，命中集合**永远是 DOM 顺序的前缀**；而**浏览器自己的 AX 树**（CDP `Accessibility.getFullAXTree`，独立于 axe）数出 **81 个 checkbox、81 个可访问名全空**。⇒ 判「axe 报得对不对」一律以 AX 树为准（`tests/smoke/a11y_ax_tree_probe.py` 就是这把尺子）。修法 = 给 `web.ListRenderer` 与 **`web.ListRenderer.RecordRow`** 两处 `CheckBox` 用法补 `.visually-hidden` slot 文字；核心把列表拆成 4 条 Owl 模板，**行选择框在 RecordRow 里** —— 漏看这点会命不中 xpath、抛错并让整个列表页白屏（2026-09-29 踩过一次，失败是响的）。
      · **仍只读数的 3 类**（队长 2026-09-29 裁定：边界归「核心结构」，维持不动）：① `aria-required-children` x3 + ② `aria-required-parent` x1 —— `web.NavBar` 的 `role="menu"` 结构，属**语义改写**；③ `aria-allowed-attr` x2 —— `role="searchbox"` 输入框上的 `aria-selected` 是**运行时**由导航服务（`web/static/src/core/navigation/navigation.js`）写上去的，模板继承改不到。

11. **QWeb 模板遍历字典必须显式 `.items()`**（2026-09-15 起）：控制器常把 `{code: 中文}` 这类字典直接传给模板；QWeb 遍历 dict 得到的是 **key 字符串**，写成 `<t t-foreach="x" t-as="v"><option t-att-value="v[0]" t-out="v[1]"/></t>` 会把 key 切成人眼看不见的单字符，`value` 同时变成非法值（筛选静默失效；记账表单方向/分类会被控制器兜底成「应收 + 其他」）。写法只有两种：`x.items()`（推荐）或 `t-as="k"` + `t-out="x[k]"`。门禁：`python3 scripts/check_qweb_dict_foreach.py`（离线，`--selftest`），运行时由 `tests/smoke/ledger_select_labels.py` 兜底。

12. **权限四层（2026-09-17 起为硬约定；完整规范 `docs/plans/perm-model.md`）**：全仓只有四层身份 —— 开发者 `base.group_system` / 教务 `openeducat_core.group_op_back_office_admin` / 教师 `openeducat_core.group_op_faculty` / 学生·家长 `base.group_portal`。**新增菜单与 ACL 必须声明自己属于哪一层**（提交说明写一行），并按层挂：
    · 系统设置/应用/模块装卸/系统参数 → **仅** `base.group_system`；
    · 业务管理（课程·科目·批次·课节 / 考勤 / 考试与成绩 / 财务 / 公告 / 审批 / 资料 / 校历 / 打卡积分 / 评教 / 图书馆） → **教务组**（写 `groups="openeducat_core.group_op_back_office_admin,base.group_system"`，与系统组**并列**，保管理员最高权）；
    · 教学执行（点名 / 成绩录入 / 作业与评阅，且只限自己任教班级） → **教师组**；
    · 只看自己 / 看孩子 → **门户路由 + `ir.rule`**，不给后台菜单。
    **禁止**给教务组加隐含 `base.group_system`（或任何把四层压成两层的 imply）——先例、理由与「故意不给什么」都写在 `custom_addons/edu_portal/views/group_tuning.xml` 的文件注释里。
    ⚠ 这一层最容易漏的是**「看得见点不开」**：菜单 `groups=`、模型 ACL（`security/ir.model.access.csv`）、记录规则（`ir.rule`）、控制器判据**缺一即死角**，而且症状常常不是报错，而是「点进去落到 `/apps` 应用面板」。判据与巡检：`python3 tests/smoke/backoffice_reachability.py`（L1 `load_menus` 可见 → L2 动作+`get_views`+`search_read`+权限读数 → L3 浏览器真渲染且**关键元素命中**；**只看 HTTP 200 不算通过**；exit 0 = 全绿）。实测先例：分层后 5 条原生菜单（网站/活动、电子商务/付款方式、在线聊天/会话×3）曾「看得见点不开」，处置是**把菜单收回到它真正需要的功能组 + 超管**（`custom_addons/edu_portal/models/menu_reachability.py`），**不是**给教务补功能组、更不是加回 `group_system`。
    菜单可见性口径一律用 **口径 B** `/web/webclient/load_menus`（GET；响应是扁平数字键字典，按 `result.root` 解析会得 0）；口径 A `_visible_menu_ids()` 会把「父根不可见」的孤儿算进来（偏高），不得混用。

13. **身份反查只有一条口径（2026-09-18 起为硬约定）**：由登录账号反查学生/家长/教师档案（以及反向「档案 → 账号」），**唯一实现** = `custom_addons/edu_schedule/models/identity.py`（双向并集：① 记录自身 `user_id` == uid，①落空才查 ② `partner.user_ids ∋ uid`；只加不减）。**禁止**再就地写 `search([('user_id','=',uid)])` 或 `partner.user_id` 单链反查。
    · 为什么在 edu_schedule：`edu_portal` 依赖它、它不依赖 `edu_portal` ⇒ 模型层与控制器都能 import 的唯一无环落点（放 controllers/roles.py 会成环：模型 import 控制器；先例 `models/week_utils.py`）；
    · 需要它的模块若不在其依赖闭包内（`edu_life`/`edu_quiz`/`edu_public` 等），**加 `edu_schedule` 到 depends**，不要复制一份；
    · 根因与全仓清点（含未改的 18 组待办）：`docs/audit/identity-lookup-unification.md`；验收：`python3 tests/smoke/identity_lookup_unification.py`（setup / measure --tag before|after / teardown）。

14. **密码「值」的门只走逐字保存（2026-09-24 起为硬约定；根因见注册事故）**：Odoo 登录端（`session.authenticate` / `_check_credentials`）对提交的口令**不做任何归一化**，所以任何把密码两端 `.strip()` 掉的入口都会造出「用自己敲的密码永远登不上」的锁死账号。
    · **已治**：core `res.users._change_password` 的 `new_passwd.strip()`（19.0 `base/models/res_users.py:920`）由 `custom_addons/edu_portal/models/res_users_password.py` 覆盖 ⇒ 门户 `/my/password`、后台改密向导（`change.password.wizard` ↔ `:1481`）、个人偏好向导（`change.password.own` ↔ `:1501`）三处一并收口；注册路径 `controllers/register.py` 自 2026-09-24 起逐字。
    · **治不了、必须绕开**：core portal 的 `/my/security` 在**控制器里**就 strip 了 —— `odoo/addons/portal/controllers/portal.py:877-879`：`post['old'].strip(), post['new1'].strip(), post['new2'].strip()` —— strip 发生在进模型**之前**，模型层覆盖够不到。实测（2026-09-24，本地 clone）：在该页把密码改成 `"DoorsPass456 "` → 页面报 "Password Updated"，但登录只认 `"DoorsPass456"`。
    · 因此**我们自己的导航不得指向 `/my/security`**：门户用户菜单、移动端底部 Tab、`/my/apps` 卡片、图标 SPEC 一律指 `/my/password`（`edu_portal_templates.xml:82,240`；`controllers/batch2.py` 的 `_COMMON_CARDS`/`FA_HOME_ICONS`/个人与设置分组）。标签必须与落点一致（落点是密码表单就写「修改密码」，别写「我的账户与安全」）。core 路由本身**原样保留、URL 仍可访问**。
    · 回归：`tests/smoke/change_password_verbatim.py`（门户 + RPC，before/after 证据）、`tests/smoke/password_doors_verbatim.py`（`/my/security` 与重置令牌门）、`tests/smoke/password_doors_shell.py`（向导/写入口，odoo shell 版）。

15. **引用只写「文件 + 符号名」，不写行号；写死的读数同罪（2026-09-28 起为硬约定）**：文档与代码注释里引用源码位置时**禁止**写 `xxx.py:NNN` —— 写的是**引用**，行号是**某一刻的读数**，文件一长就烂。
    · **实测根因（不是理论担忧）**：`docs/plans/eval-unified-design.md` 原有 39 行 `assess.py:NNN` 引用，按第 1 期 **507 行**版本写的那一批在第 2 期落地后（该文件 **1517 行**）**全部失效**；而且它们**当时大多是对的** —— 连写对的引用都会烂。更糟的是`docs/plans/eval-unified-design.md` §4.4 原引的 `assess.py:253-260`（声称是 `init()` 的 `DROP CONSTRAINT`）**在写下时就指错**：那 8 行是 `EduAssessTask._check_summary_min`，且**第 1 期那版根本没有 `init()`**。代码注释同样中招（`scripts/check_view_xpath.py` 的 r13 注释里 4 处 `models/assess.py:490`）。
    · **正确写法**：`assess.py` 的 `EduAssessRoster._item_cell`。符号名是**可复核的键** —— 读者当场跑一条命令就能拿到现行行号，不必信文档里的任何数字。
    · **行号只允许出现在显式标注了取证时刻的取证块里**（必须写明「这是 YYYY-MM-DD 的读数，不得据此定位代码」）。**带日期的历史取证块保留不动** —— 那是证据，不是引用。
    · **写死的读数与行号同罪**：任何「现状 = N 条 / N 行」都必须带**采集时刻 + 可复跑的复核命令**（先例：`docs/plans/eval-unified-design.md` §8.0.1 把「C 套 3/7/3/7/8」改成口径 + `psql` 复核命令）。
    · 复核工具：`python3 scripts/assess_symbol_index.py`（`edu_assess/models/assess.py` 的符号 → 现行行号；`--grep <符号>` 单查 / `--kind` 过滤 / `--selftest` 自证）。它自带三条自证（符号总数下限、六个模型类齐全、抽查 4 个符号与 `grep -n` 实测一致），**查不到符号 / 解析出 0 个符号 / 文件不存在，一律非零退出**（不许静默成功）。
    · 规矩全文与来由：`docs/plans/eval-unified-design.md` §8.0.3。**上游源码**（Odoo 核心 / OCA / Moodle…）不适用本条，仍按 `docs/research/README.md` 第 4 条：`给 commit + 文件路径`，行号可留但必须注明取证版本。审计表：`docs/plans/password-verbatim-audit.md`。

16. **edu_zh 的 PO 词条必须带 `#. module: <模块>` 行（2026-10-02 起为硬约定；缺它会让后台整页白屏）**：这不是注释礼节，是 **Odoo 19 的运行时硬要求** —— `odoo/tools/translate.py` 的 `CodeTranslations.__iter__` 用 `match = re.match(r"(module[s]?): (\w+)", entry.comment)` 取模块名，**缺这一行 ⇒ `match=None` ⇒ `AttributeError`** ⇒ `/web/webclient/translations` 返回 **500** ⇒ **后台整页白屏**。
    · 最坑的是**症状与状态码不一致**：白屏时 `/odoo` **仍返回 200** ⇒ 拿状态码当判据会漏。判据要打 `/web/webclient/translations`（正常 200 且约 510KB）。
    · 实测先例：2026-10-02 后台汉化第一版只写 `#:`（引用）没写 `#.`（注释），后台立刻白屏；补上即恢复。取证见 `docs/audit/backend-ux/report.md`。
    · **同一盲区家族（门禁假绿）**：`/odoo/*` 在 `tests/ui/surface.json` 里只登记 `gates=["accessibility"]`。⚠ **把它加进 english 门禁会造一个永久假绿** —— `check_english.scan_body()` 剔除 `<script>`，而后台空壳的**全部文本都在 `<script>` 里**（控制组实测：登记成 english 后照样报 OK，而同一时刻浏览器在 `/odoo/apps` 数到 32 条英文）。⇒ **要加它必须先证明它能变红**；同理 `load_menus` 读**进程内缓存**，psql 直写译文后探针不会变红，必须重启 web 再测（本轮踩过，第一次反向自证是假绿）。

16. **跨模块 `t-call` 必须查依赖方向（2026-10-02 立）**：模板里 `t-call="别的模块.模板id"` 是**渲染期按 xmlid 解析**的，
   装着对方模块时不会报错 ⇒ **平时看不出问题**，只在「单装本模块不装对方」时炸 `External ID not found`。
   规则：t-call 了谁，就在 `depends` 里声明谁。**但声明前必须先查会不会成环** —— 本条就是踩过才立的：
   `edu_life` 与 `edu_schedule` 同样 t-call 了 `edu_portal.edu_narrow_table_cards`，但
   `edu_portal` 的 depends **含 `edu_schedule`**（不含 `edu_life`）⇒ **edu_life 能加、edu_schedule 不能加**。
   edu_schedule 那条的正解是「把共用 partial 挪到双方都依赖的低层模块」或「自带一份」，两条都有代价。
   **✅ 2026-10-03 已按前者收口**：`edu_narrow_table_cards` 是**纯 `<style>`、零模型访问**，
   已下沉到 `edu_brand`（`views/shared_ui.xml`），`edu_portal` 留同名薄别名，
   `edu_schedule` 改为直引并在 depends 里**如实**声明 `edu_brand`。commit `d2c3798`。
   ⇒ 教训：**「别人也这么干、他也这么修」不能替代查环**；同一个症状在不同模块上可能有相反的修法。
17. **`noupdate=t` 是「按 xmlid」咬的，与哪个模块的数据文件无关（2026-10-03 立，实测两次失败后立）**：
   想把一个 `ir_model_data.noupdate = t` 的记录改掉，**声明式 `<record>` 一律被静默跳过** ——
   升级 exit 0、日志无异常，值纹丝不动。而且**换模块写也一样跳**（noupdate 记在 xmlid 上，不区分作者）。
   实测（停用一个已退休模型的菜单）：

   ```
   ① 改 edu_portal/views/welfare.xml 加 active="False" → -u edu_portal → DB: active 仍 = t
   ② 改 edu_nav/data/menu_consolidation_data.xml（它 parent_id 的声明处）→ -u edu_nav → active 仍 = t
   ③ 走 ORM（<function> → models/menu_labels.py 的 RETIRE_MENUS）→ active = f ✅ 且 noupdate 被规范成 f
   ```

   处置：**先把这个 xmlid 的 noupdate 规范成 False，再写值** —— 本仓已有先例与完整取证
   （`edu_portal/models/menu_labels.py` 头注释 ①，为菜单 259 改名而立；`docs/audit/finding-F1-menu-replay-on-upgrade.md`
   讲的是孪生现象 F1「声明值 ≠ 收口值」）。新增同类需求直接往 `RETIRE_MENUS` / `RENAMES` 里加一行，
   不要另起一套。
   ⇒ 教训：**改不动先查 noupdate**，别急着怀疑加载顺序或「最后写者」。
18. **「定义下沉 + 上层留别名」只对叶子模板成立（2026-10-03 立，**事故后立的**）**：
   本轮把门户外壳 `edu_page` 下沉到 `edu_brand` 时，按「上层留同名薄别名」改写 `edu_portal.edu_page`，
   升级**当场失败并整批回滚**：

   ```
   ParseError: 上级视图内找不到元素
     "<xpath expr=\"//aside[@id='b11-side']//a[@href='/web']\">"
   View error context: {'name': '门户导航：课程编排入口', 'view': ir.ui.view(3710,) ...}
   ```

   **原因**：`edu_page` **不是叶子** —— `edu_portal/views/curriculum.xml:217/:237` 两个视图用
   `inherit_id` + `xpath` 去它的 arch 里定位 `aside#b11-side`（侧栏）与 `nav#b11-tabbar`（移动端底栏）里的元素。
   薄别名只有一条 `t-call`，**没有那些扩展点** ⇒ 子视图必然「找不到元素」。
   规则：**要下沉的模板先查两件事** —— ① 有没有人 `t-call` 它（可留别名）；
   ② **有没有人 `inherit_id` 它**（不可留别名，必须全局改调用点，且**把那些 xpath 注入一起搬**）。
   ② 用的工具：`python3 scripts/check_alias_not_extended.py`（静态、可自证、可反向注入）。
   ⇒ 教训：**「别名 = 零改动」这个直觉是错的**；别名会把模板变成**没有扩展点的空壳**，
   而这类错误只在升级时才炸、且**整批回滚**（当时 137 处调用点一行没动，全靠回滚保住）。

19. **被 `xpath` 扩展的元素不能直接删；裸后台入口一律服务端 303（2026-10-13 立，**第 18 条同一家族的第二次**）**：
   ① 撤掉门户侧栏「管理后台」（`edu_portal_templates.xml` 的 `<a class="b11-nav-item" href="/web">`）时，
   只改父模板、把元素整行删掉 ⇒ 升级**当场失败并整批回滚**，报错与第 18 条**一模一样**：
   `ParseError: 上级视图内找不到元素 "<xpath expr=\"//aside[@id='b11-side']//a[@href='/web']\">"`（view 3710）。
   **触发顺序比第 18 条更阴**：`edu_portal_templates.xml` 在 manifest 里排在 `curriculum.xml` **之前**
   ⇒ 父模板写入时校验的是 **DB 里那份尚未升级的子视图**，而它的 `xpath` 锚点就是被删的元素。
   规则：**删元素前先查扩展点**（`grep -rn "xpath.*<元素特征>"` + `check_view_xpath.py`）；本仓正解是
   **保留元素但 `t-if="False"`**（不渲染、扩展点仍在），子视图改锚到真实元素（`/edu/import/students`），
   等确认所有环境升过本版本后再删壳。
   ② 「一开进来先闪一下蓝顶栏（后台外壳）再跳」的根因**不在前端**：裸 `/web`、`/odoo` 先由 core 渲染一整页
   webclient 外壳；`edu_portal/static/src/js/apps_menu_redirect.js` 的 `_loadDefaultApp` patch 是**外壳已可见之后**才跳的
   ⇒ 只要走裸入口就必有闪现。正解在**服务端路由**：`EduHomeRedirect.web_client` 覆盖 core 的四条路由
   （`/web`、`/odoo`、`/odoo/<path:subpath>`、`/scoped_app/<path:subpath>`），
   **只对「无 subpath、无 `menu_id`、无 `redirect`」的裸入口 303 → `/apps`**，其余原样 `super()` 放行给 core。
   本地验收 18/18：教务 `POST /login` → 303 `/apps`；教务 `GET /web`、`/odoo` → 303 `/apps`；
   `GET /odoo/action-720`、`/odoo/settings`、`/web?menu_id=1` → 200（后台不受影响）；匿名 `/web` → 303 `/web/login`；
   学生 `GET /web` → 303 `/apps`（再由 `/apps` 分流 `/my/home`）；教师登录 → 302 `/my/home`。
   门禁侧连带：`check_odoo_trace.py` 的后台面改用 `/odoo/settings`（裸 `/web` 现在 303，留在 BACKEND 里会变**假绿**），
   并新增一条自证断言把「裸 /web 必须 303 到 /apps」钉住。
   ⇒ 教训：**「删掉入口」与「改入口落点」是两件事**（前者撞扩展点）；**能改服务端就别改前端**。

20. **视图继承选择器不得用「翻译属性」（`aria-label` / `string` / `title` / `help` / `placeholder` …）（2026-10-14 立，**真实升级失败后立**）**：
   `bash scripts/safe_upgrade.sh edu_schedule,edu_portal` 当场失败并整批回滚：
   `ParseError: while parsing None:2115` / `View inheritance may not use attribute 'aria-label' as a selector.`
   （`file`: `custom_addons/edu_portal/views/roles.xml`，`xmlid`: `edu_timetable_availability_btn`，`view`: `ir.ui.view(3837,)`）。
   真源（照抄 core，不猜）：`base/models/ir_ui_view.py:405-424 _valid_inheritance()` 对 `<xpath expr>` 命中
   `TRANSLATED_ATTRS_RE`（`:135`）**直接抛错**；非 `<xpath>` 的继承节点**自身**带翻译属性同样抛错（`:417-423`）；
   集合定义在 `odoo/tools/translate.py:75 TRANSLATED_ATTRS`（aria-label, title, string, help, alt, placeholder,
   label, confirm, data-tooltip …，另含 `t-attf-<attr>` 变体）。
   ⇒ 选择器只许用稳定属性：`@name` / `@id` / `@role` / `@type` / `@href` / `@t-if` / `hasclass(...)` / 非 `data-tooltip` 的 `@data-*`；
   `@class` 当选择器只是 core 的 warning（`WRONGCLASS`），本仓门禁按 WARN 处理、不计 FAIL。
   守卫：`scripts/check_view_selector_attrs.py`（离线扫 `custom_addons/*/views/**`，`--selftest` 9 样本，退出码 0=OK / 1=FAIL / 2=ENV）。

21. **改 `ir.config_parameter` 后「立刻全员生效」必须直读参数表，不能依赖 `get_param`（2026-10-14 立，**真机探针抓到**）**：
   `env['ir.config_parameter'].sudo().get_param(key)` 带 `@ormcache('key', cache='stable')` —— 参数改了，
   **只有「处理那次写入请求的那个 worker」清缓存**，其余 worker 继续读旧值直到重启/升级。
   实证：本轮报课池档位开关（`edu.enroll.pool_mode`）真机验收 `G1-b`（切 `off` 后报课页仍出现「不可报：本学期未排课」）失败，
   根因就是这个 per-worker 缓存 —— 同一请求路径上换个 worker 就换了答案，**读数是随机的**，最容易被当成「偶发」放过去。
   正解（本仓既有先例 `custom_addons/edu_portal/models/course_rep.py:71-90` 的 `_raw_param`）：
   **直读表** `SELECT value FROM ir_config_parameter WHERE key = %s`（失败回落默认值、不炸页面），
   本轮落点在 `custom_addons/edu_portal/controllers/enroll.py:65 edu_pool_mode()`。
   判据：**教务在网页上改、要求立刻生效的开关**一律走直读；只影响下次启动/低频读取的参数才可用 `get_param`。

22. **`write()` 之后紧接着 `create()` 引用同一唯一键：必须显式 flush（2026-10-14 立，**真机探针抓到**）**：
   ORM 的 `create` **不保证**先把上一条 `write` 的 UPDATE 刷到 DB。实证：录取后发放入学码的「重新发放入学码」
   先 `old.write({'application_id': False})` 解绑旧码、再 `create` 新码，**HTTP 路径下**插入时撞
   `edu_invite_code_edu_admit_application_uniq`（`psycopg2.errors.UniqueViolation`，Odoo 包装成 `ValidationError`）；
   而 `odoo shell` 里手工补一句 `env.cr.flush()` 就通过 —— **同一个方法两种结果**，最容易被误判成「偶发」。
   正解：写完立刻 `old.flush_recordset(['application_id'])`，落点
   `custom_addons/edu_admit_invite/models/application_ext.py` 的 `action_reissue_admission_invite()`。
   判据：**凡「先改 A 的键、再插引用该键的 B」**都按这条办，不要依赖 `create` 的隐式 flush。

23. **判「某入口是否已退役」不能只看定义处 —— 一天内连犯两次（2026-10-14 立）**：
   ① **只读父类控制器 ⇒ 漏掉继承覆写**：A 套旧评估 7 条门户路由，父类
   `custom_addons/edu_portal/controllers/evaluation.py` 的实现**一行未删、看起来全活**；
   但同目录 `custom_addons/edu_portal/controllers/eval_compat.py`（注册于 `controllers/__init__.py:17`）
   **继承** `EduEvalPortal` 并覆写同一批 `@http.route` —— Odoo 的 leaf 覆盖机制（`odoo/http.py:_generate_routing_rules`）
   **只实例化最底层子类**，父类的同名路由不再注册 ⇒ 实际全是 303。我据此在评审包里把「旧入口仍可写」
   写成了事实，**错了**；活体实测（教务/教师/学生三角色）7/7 全 303。
   ② **只看菜单定义 ⇒ 误判成空壳**：`edu_portal.menu_edu_eval_root`（「综合评估」根应用）定义处
   （`custom_addons/edu_portal/views/evaluation.xml:90`）**没有 action**、两个旧子菜单也已停用 ⇒ 我判它是
   「点不开的空壳磁贴」并加进 `RETIRE_MENUS` 停用；升级后立刻发现新引擎 `edu_assess` 的 4 条菜单
   （`custom_addons/edu_assess/views/assess_views.xml:261-276`）`parent` **就是它** ⇒ 停用等于关掉新引擎后台入口。
   **当场回滚**（588 已恢复 `active=t`；`RETIRE_MENUS` 里留了「绝不能再停用」的注释与判据）。
   ⇒ **判据**：① 路由：活体实测 + `grep -rn "class .*(" <控制器目录>` 查有没有子类覆写同一路由；
   ② 菜单/动作/视图：先查**生效态**——`select id,name->>'en_US' from ir_ui_menu where parent_id=<id> and active;`
   与 `inherit_id` 反查，再决定动不动它。

## 7. scripts/ 分类索引

| 类别 | 脚本 |
|---|---|
| 种子/演示 | seed_batch1-3, seed_demo, seed_yongyue_data, seed_assets/eval/fees/jobs/lms/certificate/c_content/d1_nav/teacher_menus/tg_demo/tg_users |
| 环境初始化 | setup_brand_yongyue（公开页品牌文案）, setup_nav_yongyue（导航）, fix_user, cleanup_demo_data |
| ⚠ **2026-10-02 归位** | 原先躺在 `custom_addons/` 根下的 10 个非模块脚本已处理：**删 3**（`fix_menus.py` / `seed_menus.py` / `seed_fees.py`）、**迁 7 → 本目录 `scripts/`**（`seed_demo` / `seed_batch1-3` / `fix_user` / `seed_tg_demo` / `seed_tg_users`）。逐条零引用证据见 [docs/audit/redundancy/inventory.md](audit/redundancy/inventory.md)；守卫 `scripts/check_stray_addons.py`（addons 根出现游离文件即红）。<br>⚠ `seed_fees.py` 删得尤其该：它写的是 `account.move`，而页面读 `edu.fee.bill` —— **模型都不对**，真数据来自 `scripts/seed_fees_demo.py`。 |
| 验收/回归 | check_qweb_dict_foreach（QWeb 遍历 dict 字母化：静态双向判定，`--selftest` 4 条；口径失败项 0）, check_manifest_tracking（manifest 引用集 ⊆ git 跟踪集；零环境依赖）, **assess_symbol_index（`assess.py` 符号 → 现行行号；`--grep`/`--kind`/`--selftest`；查不到符号或 0 符号一律非零退出；铁律 §6 第 15 条的复核工具）**, check_english（英文门禁 v3.2：must-fix/brand/whitelist/data/theme 五类分流，`--selftest`/`--coverage`）, check_odoo_trace（去 Odoo 痕迹 v3.2：页面/属性/邮件/数据不变量四维，`--selftest`/`--list-routes`）, check_view_xpath（继承视图/裸 < / t-elif / 导入顺序，`--selftest`）, check_prod_menus, test_life_eval, test_submit_flows, test_timetable_conflict, test_checkin_journal, review_*_t2 |
| **入口文档计数一致（2026-10-12 新立）** | **`check_doc_module_count.py`** —— 入口文档（CLAUDE.md / README.md / docs/code-map.md / docs/dev-workflow.md）里写死的「自研模块数」必须等于 `custom_addons/` 下 `edu_*` 目录实测数。判据只认两种写法（`N 个 edu_*`、`edu_*` 后 40 字符内 `N 个模块`），其余不碰；含「当时/历史/曾/已过期/退役」的行**跳过并逐条打印**（历史叙述允许旧数字 —— 静默吞掉的检查等于没检查）。退出码 0=一致 ｜ 1=不一致 ｜ 2=环境未就绪（**2 不是通过**）。<br>**立它的由来：同一个数字咬过三次** —— README「自研十个模块」→实为 12（2026-10-06 修）；README 改成「12 个」→实为 14；code-map §3「9 个 edu_*」→实为 14。后两处是 **2026-10-12 网页版 Claude 读仓库时抓到的**（它按提示词如实报「文档与实测不符」，没猜）。<br>**自证（红→绿）**：把 README 的 `14 个模块` 注入成 `99 个模块` ⇒ **FAIL rc=1 且点名 `README.md:3`**；还原 ⇒ **OK rc=0**；`--selftest` **5/5**（含 2 条负样本：`14 个官方模块` 与「当时…历史」不得命中）。已登记进 `check_all.sh` 静态段。 |
| **v3 门禁（tests/smoke/）** | **`a11y_ax_tree_probe.py`（后台页可访问名·**浏览器 AX 树口径**（CDP）—— 独立于 axe，判「axe 报得对不对」靠它）, **`a11y_label_dom_compare.py`（列表选择框 DOM 层审计：label 实体 / id 唯一性 / 父链；与 AX 树配套：一个判有无名字，一个判名字从哪来）**, **`a11y_label_fix_experiment.py`（候选修法内存实验：先反向注入清空 label 验量具、再修补验方向；顺带演示 axe 的视口口径 19 vs 63）**, **`assess_template_guard.py`（评估任务换模板护栏·**模型层**：2 红必拒 / 2 绿必放行 / 1 状态不变量必拒 + 计数自清；走 odoo shell，因为护栏在 ORM 层）, **`backend_head_probe.py`（后台页 head 实测：viewport 不禁缩放 + html lang 合法 BCP47 + 前台控制组未被改动；只读、不起浏览器）**, **`init_cross_table_check.py`（init() 跨表回填静态门禁；`--selftest`/--file；已接进 safe_upgrade.sh 的 gate D）**, **`ledger_select_labels.py`（台账/记账下拉内容：标签必须中文、value 必须合法；防字母化回归）**, **`ledger_payable_card.py`（应付待付汇总卡口径：手工应付/待批报销计入、已驳回不计；三段模板自带清理）**, **`ledger_category_admin.py`（费用分类自助新建→出现在表单→筛选→停用→删除被拒→真删除，13 条）**, `ux_v3_route_matrix.py`（100 路由 × 5 角色，ENV/真红分流）, `zero_loss_reachability.py`（旧首页 35 卡零丢失 + 共享类契约）, `data_driven_brand_leak.py`（数据驱动品牌泄漏，自带造样本/清场）, `audit_completeness_smoke.py`（后台直写 + 门户三路径的留痕断言）, `gate_seam_check.py`（两门禁接缝，含故障注入）, **`deploy_web_restart_proof.py`（部署脚本「升级↔重启配对自证」的**离线**探针：PATH 上造假 ssh/docker/date 模拟远端，**不碰生产**；4 条判据 = 正常路径必绿 / 升级成功但未重启必红且印处置话术 / 读不到标记必须拒判且不冒充结论 / 升级 rc≠0 另判；跑 `python3 tests/smoke/deploy_web_restart_proof.py`，退出 0 = 4/4） |
| **页内链接可达（2026-10-02 新立）** | **`check_inpage_links.py`** —— 查 `views/*.xml` **页内**按钮/链接指向的路由到底存不存在。判据只取一种：**404 = 缺陷**（403/302/200 一律不算，角色与流程跳转都会产生它们）；含动态段（`{{ }}`/`#{ }`/`<int:>`）与静态资源（`/web/`、`/static/`、外链）**一律跳过、不假装探过**；退出码 0=无 404 ｜ 1=有 ｜ 2=环境未就绪（**2 不是通过**）。<br>**为什么需要它**：既有 `check_nav_reachable.py` 的输入是**活导航树 `website.menu`**，只覆盖导航栏链接，**页内按钮它看不见**。实证缺陷：`batch3.xml:638` 的「导出 CSV」指向 `/my/time_off/export`，而控制器里 `my_time_off_export()` **实现完整却丢了 `@http.route` 装饰器** ⇒ 从未注册成路由，实测 **404**（`/my/time_off` 却是 200）。发现途径是符号级死代码扫描（「有实现但全仓没人按名字调用」正是「装饰器丢了」的指纹）。<br>**自证（红→绿）**：拿掉装饰器 ⇒ **FAIL，1 条 404 且点名 `batch3.xml:638`**；装回 ⇒ **OK（175 条路径 × 2 身份 = 350 次实探，0 条 404）**。<br>⚠ **建它时踩过的两个坑**（都已写进脚本注释）：① 抽取第一版漏了拼接式 `t-att-href="'/path' + 变量"` 与 `#{ }`，**曾把 20 条动态路径截断成假 404**，也曾因为漏了拼接式而使门禁**抓不到自己立起来要抓的那个缺陷**（反向注入仍报绿）；② 新模式的 `rx.append` 一度写在扫描循环**之后**，等于没生效。⇒ 铁律：**新门禁必须用它要抓的那个真实缺陷做反向注入**。 |
| **PO 健全（2026-10-02 新立）** | **`check_po_sanity.py`** —— 查 `custom_addons/**/*.po` 里**同一个 (msgctxt, msgid) 出现两次以上**。判据只取这一种，因为它是客观的、且正是 `msgfmt --check` 判 **fatal** 的那一类。退出码 0=OK ｜ 1=有重复 ｜ 2=找不到 .po（**2 不是通过**）；`--selftest` 自带红绿自证。<br>**为什么不用 msgfmt**：它属 gettext，不保证每台机器都有；门禁一旦依赖外部命令，缺失时就会「跳过」或「崩」——两种都不是「通过」。故自己解析 PO，只做重复检测这一件事。<br>**立它的原因**：`edu_zh` 的 zh_CN 与 zh_TW **各有 3 处重复 msgid**（`General` 两遍、`Closed`/`In Progress` 各两遍）。译文当时一致 ⇒ **行为上看不出来**，但这最难查：一旦有人只改其中一份，「哪份生效」就变成**按文件顺序**的隐式行为。反向注入实测：把 `General` 复制成两份 ⇒ **FAIL 并点名 453/458 行**；恢复 ⇒ OK 且与备份逐字节相同。 |
| **记录集与 None 比较（2026-10-03 新立，事故后立的门禁）** | **`check_recordset_none.py`** —— 静态查出「把 Odoo **记录集**拿去和 `None` 比」。`search()`/`browse()` **永远不返回 None**，返回的是空记录集 ⇒ `if rec is None:` 那一支**永远进不去**。<br>**立它的原因（实测）**：`edu_life` 周记页写着 `if entry is None:` ⇒ **没写周记的学生被告知「老师已批阅，评语在正文之后」**，而同一页旁边的表单还写着「已写 0 字」（学生 5 有 W34/35/36/37/39、今天 W40 无记录，页面却报已批阅）。同函数上一行 `not entry` 本来就是对写法，只有这一支写错。<br>判据：赋值右侧出现 `.search(`/`.browse(`/`.filtered(`/`.mapped(`，随后该名字出现 `is [not] None` ⇒ 报红；**按「被重新赋值」失效，不看行距**。退出码 0/1/2，带 `--selftest`（坏写法被抓 / `if not rec:` 与普通 `dict.get(...) is None` 不误报）。<br>⚠ **本门禁第一版是假绿**：用「6 行内」窗口，而真实代码里注释一多就超出窗口 ⇒ 反向注入后**仍然报绿**。红测发现后改为按重新赋值失效，现已能如实报红。<br>**当前读数**：0 处 ⇒ `RESULT=OK`。 |
| **同指标跨页一致性（2026-10-03 新立，报告型探针）** | **`probe_metric_consistency.py`** —— 同一个指标在**多个页面**的读数是否一致。判据：各处读数四舍五入到整数后比较（47.92 与 48 是同一值的不同显示精度），极差 > 1 即报红。<br>**立它的由来：两轮里这个轴抓到 4 个缺陷** —— 第 39 轮家长首页「考勤 0%」（无数据被渲染成 0）；第 40 轮首页 mhero 46% vs 同页概览 48%（`present`/`late` 被当互斥标志，环形图四段和只有 47≠48）；第 41 轮全仓搜同类算式又抓出 `/my/study` 50%（迟到**算了两遍**）与 Telegram「迟到恒 0」（互斥 if/elif 里 `late` 那支永远轮不到）。**一条指标、四处实现、三种口径。**<br>⚠ 只报**「不一致」**，不判哪处对 —— 判对错要看库里的原始事实（如 `select count(*) filter (where present), count(*) filter (where late) from op_attendance_line`）。<br>**自证**：反向注入旧的 `(present+late)` 算法 ⇒ 报红并点名 `/my/study` 50、极差 2.08；逐字节还原 ⇒ 回绿（真实退出码 0）。<br>**当前读数**：出勤率五处 48 / 48 / 48 / 47.92 / 48、在修科目数两处 1 / 1、待完成作业两处 2 / 2 ⇒ `RESULT=OK`。<br>
**第二个指标就是它自己抓出来的**：首页「待完成作业」原先只按 `batch_id` 取作业，
而作业页按 `batch+course` ⇒ 首页把**别的课程的 2 条作业**也算进来了（实测 batch 8 共 5 条，
其中 `course_id=13` 的 2 条不属于该生），首页显示 **4**、作业页实为 **2**。已对齐两处的作用域优先级。 |
| **越权 / 跨角色（2026-10-03 新立，报告型探针）** | **`probe_privilege_boundaries.py`** —— 用**非授权角色**去打「只该某角色看」的带对象 id 的 GET 路由，看是否真被挡住。门户有 50+ 条这样的路由，是标准**越权（IDOR）**表面。<br>判据：非授权 ⇒ 应当 3xx/403/404（**不该 200**）；授权 ⇒ 应当 200 且内容类型符合预期。<br>⚠ **关键实现细节（我第一版就栽在这）**：必须 `max_redirects=0`。本仓的越权守卫多为 `redirect('/my/home')`，而 **APIRequestContext 默认跟随重定向** ⇒ 落到 `/my/home` 也是 **200 且有内容**，于是「200 且无登录表单」会把**被正确挡下**的判成越权 —— 第一版一跑报 12 条「越权」，与先前 fetch 实测「全部落 /my/home」**直接矛盾**。**矛盾的读数就是 bug 的信号**，先查工具、再谈漏洞。<br>**当前读数**：12 条学生越权全部 **303 已挡**；授权侧（本人下载证书）**200 PDF** ⇒ `RESULT=OK`。 |
| **写操作错误路径（2026-10-03 新立，报告型探针）** | **`probe_write_error_paths.py`** —— 对门户写操作发**空载荷**（`csrf_token` + 无字段，带对应身份），把结果分三档合法 / 两档缺陷：<br>· ✅ **明确拒绝**（落 `box=`/`error=`/`err=` 且页面有中文提示）· ✅ **权限守卫回落**（落 `/my/home`，本仓 `if not _X_guard(): redirect('/my/home')` 的既有模式）· ✅ **静默 no-op**（越权/记录不存在 ⇒ 一个字段都不写、303 回列表，实测先例 `/leave/set_state`）；<br>· ⛔ **没接住**（5xx 或响应体含 `Traceback`）· ⛔ **静默成功**（空载荷却落 `box=submitted`/`saved=1`）。<br>**立它的由来**：第 36 轮把「验渲染」换成「验错误路径」，第一个手写探针就抓到真缺陷（请假倒挂日期被静默改写成一天还回「已提交」，commit `9176a8f`）⇒ 该轴值得可复跑。<br>**只用空载荷**：空载荷在任何一处都该被挡下，故**不会造数据**（若某路由对空载荷也落库，那本身就是缺陷）。退出码 0/1/2（2=登录不了，**不是通过**）。<br>**当前读数**：11 条路由全部落在三档合法之内，**RESULT=OK**。 |

| **窄屏横向溢出（2026-10-03 新立，报告型探针）** | **`scripts/probe_mobile_layout.py`** —— 在 **375px** 下逐页量 `documentElement.scrollWidth > clientWidth + 2`（＝整页要左右拖），报红时给出**最靠右的元凶元素**。**为什么单独立一条**：既有门禁只管「表格被压扁」与「无障碍」，**没有一条**管横向溢出；而它**与表格无关** —— 超宽图片、`min-width`、不换行的长串都能造成。**刻意不判触控目标尺寸**：实测报出的「小目标」全是内联文字链接（WCAG 2.5.8 内联豁免）、禁用的分页箭头、跳至内容（1px，本就该看不见）、自带 `aria-label` 的图标链接 ⇒ 全假阳性；按本仓纪律降级为 `--tap-report` **只读数不判红**（豁免清单写在文件头）。`--selftest` 用注入超宽元素自证量具（375→900 必须变红）。**首次全量：70 页无溢出** |

| **一键全套验证（2026-10-04 新立）** | **`bash scripts/check_all.sh`** —— 一次跑完 ① 静态门禁 ② 站点门禁（含 `english` / `nav_reachable` / `odoo_trace` / `ui_usability`，这些此前**没人跑过**）③ 4 个探针 ④ **4 份 E2E**；逐项 ✅/❌ + 汇总 + 退出码（0 全绿 / 1 有红 / 2 环境未就绪）。`--no-e2e` 跳过 E2E，`--list` 只看清单。**为什么立它**：仓里已有 20+ 门禁与 4 份 E2E，却**没有一处把它们串起来** ⇒ 第 62/63 轮实测发现两份 E2E **红着没人知道**（一份自称可重复却重复必红、一份写死过去日期且漏填必填字段）。**门禁再多，不跑就等于没有**。⚠ 报告型工具（如 `find_undefined_classes`，其 docstring 明写「只报告、不判死」）**只读数**，仅当**超过登记值**（`UNKNOWN_KNOWN=35`，对应 deprecated-inventory **C-13**）才报红 —— 否则会造出一条永远红的死检查 |

| **全新库安装演练（2026-10-04 新立）** | **`bash scripts/check_fresh_install.sh [库名]`** —— 建一个全新库（默认 `edu19_rehearsal`，**拒绝在 `edu19` 上跑**）、按 `deploy_myedu.sh:156` 的清单 `-i` 一遍、断言「无致命错误 + 7 个关键模块 installed + 到堂打卡类型在」，最后删库。**为什么立它**：第 65 轮第一次真装全新库，发现**整条安装链是断的**（`edu_brand` 引用 6 个模块却只依赖 3 个；`context={"lang":"zh_CN"}` 写翻译字段而新库语言未启用；`edu_schedule` 用 `calendar.event` 却没依赖 `calendar`）—— 这些**只在全新库上出现**，克隆库永远看不出来，而本项目**已经丢过一次生产库**。第 66/67 轮修完后立此脚本，防止再被弄断。也可用 `check_all.sh --fresh-install`（独立跑，因为它有建库/删库副作用） |

| **导航死链（2026-10-04 新立，报告型探针）** | **`scripts/probe_nav_deadlinks.py`** —— 对**四个角色各自的门户导航**逐条点进去，抓三种硬信号：① HTTP ≥ 400；② 落地页含拒止文案（「仅面向…账号」等）；③ **被静默弹回首页**（请求 A 却落到 `/my/home`）。**为什么立它**：既有门禁只问「路由登记没登记」与「无障碍」，**没人问过「这个角色自己的导航，条条都通吗」**；第 54 轮教师端就撞到过一次同款死链。**判据 ③ 是调试逼出来的**：学生访问 `/assignment/manage` 不是拒止，而是**静默 302 回首页** —— 只看状态码与文案抓不到，而它正是「点了进不去」本身。`--selftest` 注入必然 404 的链接证明量具能红（**自证连续失败三次，每次都逼出我自己的错**：JS 里 `x.href` 会写成绝对 URL、注入容器写死选择器没命中、自证路径本身不是拒止页）。**首次全量：四角色 69 条导航链接条条可通** |

| **导出/下载（2026-10-04 新立）** | **`scripts/probe_exports.py`** —— 逐个打「导出 CSV / 下载报告 / 下载证书」这类路由，验**真的给出文件**。**为什么立它**：这些路由此前只被 `check_ui_surface` 登记成 endpoint（「路由存在」），**从没人验过点下去出不出文件** —— 而导出坏了是最典型的「按了没反应」（用户不报错，只以为卡了）。判据三条：① HTTP ≥ 400；② **返回 `text/html`**（导出接口返回网页 = 渲染了错误页/被弹回，**状态码可能还是 200**，这是最关键一条）；③ 体积 < 20 字节（空文件）。`--selftest` 的做法：把一条换成普通页面 ⇒ 立刻报「返回的是 HTML」⇒ 证明绿灯有意义。**首次全量：10 个导出全部出文件**（含 27KB 的证书 PDF） |

| **手机端可用性（2026-10-04 新立）** | **`scripts/probe_mobile_flow.py`** —— 375px（`is_mobile` + iPhone UA）下走四个角色 + 学生 5 个核心页，查四件事：① 底部 tabbar 可见且 ≥3 项；② 桌面侧栏**不可见**（模板 `d-none d-lg-block`）；③ 横向不溢出（同第 58 轮口径）；④ 学生核心页**主操作可见且未退化**（< 8px 视为塌了）。**为什么立它**：第 58 轮的 `probe_mobile_layout.py` 只查**横向溢出** ——「不溢出」不等于「用得了」；而第 95 轮真以手机视口走了一遍（登录→首页→作业→提交→费用→私信）才发现没人验过「能不能用」。⚠ **不判点击目标大小** —— 第 58 轮明确决定过不判（那是设计取向不是缺陷），本探针只用 8px 兜「元素塌了」。⚠ 实现上有个坑：同一路由在**隐藏的桌面侧栏**里也有一份，`query_selector` 返回第一个匹配 ⇒ 会拿到不可见的那个，必须遍历找**可见**的（第一版就这么报了一条假阳性） |
| **静态资产新鲜度（2026-10-03 新立，**提示型**）** | **`check_asset_freshness.py`** —— 比对「`custom_addons/*/static/**` 下 css/scss/js 的**最新 mtime**」与「**web 容器启动时刻**」，前者更晚即报 **STALE**。<br>**立它的原因（实测）**：改 `static/src/css/*.css` 后跑升级，改动**完全没生效** —— 服务端下发的仍是旧资产包（`717b303` 含目标类名 40 次但**不含**新规则），**重启 web 后**哈希变 `0867e66` 才带上。后果不是页面坏，而是**人拿旧资产验收新代码**（本仓口径：**样本有效性**）。<br>退出码：0=新鲜 ｜ **1=陈旧（≠代码错，是「验证前提不成立」）** ｜ 2=ENV（拿不到容器，**不是通过**）。已接进 `safe_upgrade.sh` 作为**只提示不拒绝**的一段；容器与宿主机时钟一致性有实测旁证（`date -u` 逐秒一致）。<br>**自证**：`touch` 任一 css ⇒ 由 OK 转 STALE（exit 1）；重启 web ⇒ 回 OK。 |
| **薄别名被继承（2026-10-03 新立，**事故后立的门禁**）** | **`check_alias_not_extended.py`** —— 静态查出「**薄别名模板却被人 `inherit_id` 继承**」。<br>**立它的原因是一次真实事故**：把门户外壳 `edu_page` 下沉时，我按「上层留同名薄别名」改写，升级**当场失败并整批回滚** —— `ParseError: 上级视图内找不到元素 "<xpath expr=\"//aside[@id='b11-side']//a[@href='/web']\">"`。因为 `edu_page` **不是叶子**，它被 2 个视图用 `inherit_id`+`xpath` 扩展；薄别名只有一条 `t-call`，**没有那些扩展点**。<br>**规则（已并入 §6 第 16 条的姊妹条）**：「定义下沉 + 上层留别名」**只对叶子模板成立**；被 `inherit_id` 扩展过的模板要下沉，必须**全局改调用点**，不能留别名。<br>判据：认两种别名形态（自闭合 `<t t-call="Y"/>`、包裹式 `<t t-call="Y"><t t-out="0"/></t>`）+ 收集 `inherit_id` + 求交。退出码 0/1/2（2 = 读不到 views，**不是通过**），带 `--selftest`。<br>**自证**：内置自证；并对**真实模板**反向注入（给 `edu_life.edu_life_page` 塞一个继承者 ⇒ 报红并点名别名/目标/定义处/继承者；还原后逐字节相同）。当前读数：薄别名 **2** 个、冲突 **0**。 |
| **未定义类名（2026-10-03 新立）** | **`find_undefined_classes.py`** —— 找出「模板 `class=` 里用了、但 `static/**` 的 css/scss/js 里**一次都没出现**」的**自有前缀**类名（`oe-`/`ux-`/`b11-`/`edu-`；排除 Bootstrap 与 Odoo 核心的海量类）。<br>**立它的原因**：这类缺陷**既不报错也不影响构建**，只是「看起来有样式其实没有」—— 已实测两例：`oe-cat-title`（类名挂了但规则作用域在 `.oe-cat-head` 下，`/quiz/my` 那处不在其中 ⇒ 40px vs 兄弟页 20px）、`life-cal`（`/my/checkins` 月历表挂着它，全仓零定义）。两次都是**先看图才发现**，所以才要机器扫。<br>**判据边界**：只报告不判死（命中可能是①打错②缺样式③留给 JS 的钩子；工具同时扫 `.js`，故③基本被排除）。现命中 **35 个**，已登记 **C-13**（来历＝照旧站 DOM 抄类名、旧站样式表从未进本仓；实测页面靠 Bootstrap 撑住，故登记不删）。<br>**自证**：内置 `--selftest`；并对**真实模板**做过反向注入（往 `study.xml` 塞 `oe-zz-probe-xyz` ⇒ 命中数 35→36 并点名该行；还原后逐字节相同）。 |
| 截图/度量 | shoot_ux_v3.py（4 角色 × 3 视口 + 首页 DOM 高度 M3）, shoot*.py（复刻期对比） |
| 部署/运维 | **safe_upgrade.sh（唯一推荐的升级入口：串行锁 + DB 参数 + --no-http + 挂载自检 + 失败特征硬失败 + 4 道升级前静态门禁 + 退出码 0/3/4/5/6）**, **check_live_registry.py（活体注册表门禁：库 ir_model_data vs **跑着的 web 进程**，有 DARK ⇒ exit 1；事故后必跑，见 §10 的注册表铁律）**, deploy_myedu.sh（马来西亚；一次性容器升级 + **必定重启 web** + **升级↔重启配对自证** + 有界就绪探活 + 活体注册表门禁）, fix_edu_apply_xmlid.py（部署前干跑孤儿预检，`FIX_DRY_RUN=1`）, dev_up.sh, register_webhook.sh, loadtest.py, telegram_relay.py/.sh |
| 图标/汉化 | gen_icons.py（SPEC 驱动 SVG 生成）, i18n_xml_translate.py + i18n_glossary.json（术语表汉化） |
| **视图继承选择器（2026-10-14 新立，事故后立的门禁）** | **`check_view_selector_attrs.py`** —— 拦住「用翻译属性当 `<xpath expr>` / 继承节点选择器」。判据取自 core 真源（`base/models/ir_ui_view.py:405-424 _valid_inheritance()` + `odoo/tools/translate.py:75 TRANSLATED_ATTRS`）：`expr` 里抽出的 `@属性名` 命中翻译属性集合（含 `t-attf-` 变体）⇒ **FAIL**；`@class` 作选择器仅 WARN（对齐 core `WRONGCLASS`）；`@t-att-<base>` 是动态属性、一律不判（实测 `@t-att-href` 不误报）。<br>**立它的原因（真实事故，非推演）**：2026-10-14 `bash scripts/safe_upgrade.sh edu_schedule,edu_portal` 因 `custom_addons/edu_portal/views/roles.xml` 的 `<xpath expr="//div[@aria-label='周导航']">` 直接 `ParseError: View inheritance may not use attribute 'aria-label' as a selector.`（view 3837 / xmlid `edu_timetable_availability_btn`）⇒ 整批回滚。<br>`--selftest` 9 样本（含两条反例：`@t-att-href` 不误报、`@class` 只 WARN）；退出码 0=OK / 1=FAIL / 2=ENV。**当前读数**：82 个视图 XML ⇒ FAIL 0 / WARN 3（均为 core `WRONGCLASS`）⇒ `RESULT=OK`。 |
| 对比工具（复刻期） | render_capture, shoot*, height_diff, ocr_diff, cmp_landing, extract_css* |
| 一次性修补 | fix_*, inject_home_title, hallucinate, nav_fix, tmp_*（勿模仿其风格） |

## 8. docs/ 索引（一行摘要；v3 新增段见下方「v3 交付与验证」）

**功能设计（docs/plans/）**

> **总索引已独立成页：[docs/plans/README.md](plans/README.md)** —— 逐份登记（**份数以索引顶部标注的「最后核对日期 + 份数」为准**，本节不再写死数字）
> （主题 / 状态 / 取代 / 要点 / 判定依据）+ 待办队列 + 同一主题读哪份 + 收录规范。
> 本节原表 20 行只登记 **15 份** `docs/plans/` 文档（另 6 条属 `docs/audit/` 与一个目录）；
> 其余计划文档本节从未登记 —— **两处维护必然漂移，故本节不再维护逐文件清单，也不写死份数**。要总数请看索引顶部。
>
> 最常被引用的三份（改架构前先读）：
> | 文件 | 摘要 |
> |---|---|
> | `docs/plans/major-track-elective-design.md` | 专业编排（学制 + 必修/选修）：关系表 + `subject_ids` 兼容层；**被 21 处引用，全仓最多** |
> | `docs/plans/class-batch-management-design.md` | 班级管理（分配 / 回收站 / 同班同学）；17 处引用 |
> | `docs/plans/timetable-design.md` | 排课系统（周课表多视角 + 并发兜底）；15 处引用 |

**调研档案（docs/research/）**

| 文件 | 摘要 |
|---|---|
| research/README.md | 收录规范（一手来源、未验证标注、行号漂移说明）+ 索引；历史调研登记原位 |
| research/odoo19-debranding-i18n.md | Odoo 19 去品牌化 + 汉化源码级调研：官方文档零记载、OCA/server-brand 19.0 触点清单与 license、必须自研的 A–E 类触点、PO 覆盖译文的真实限制（默认不覆盖 / code 词条无效） |
| research/onestop-learning-and-repetitive-work.md | 一条龙学习链路 + 会议链接 + 重复劳动：Canvas Modules / Moodle Timeline / mod_zoom / mod_attendance / grade history、会议 API 额度、国内 SaaS 功能名级证据与两个共性缺口 |

**UX 系列（docs/plans/ + docs 根）**
| 文件 | 摘要 |
|---|---|
| ux-research-dingtalk.md | 钉钉/企微/飞书交互模式调研；完成 |
| oss-research.md | 国内教育开源与排课交互调研，License 边界结论；完成 |
| ui-reference.md | 钉钉式工作台 UI 规范：色值/导航/宫格令牌；定稿 |
| ux-improve-proposal.md | 钉钉式改进提案 S1-S5/W1-W3；已批准 |
| ux-implement-report.md / ux-rework-handoff.md | 实施报告与交班：七项落地、云端待拍板 |
| ux-audit.md | 全站空态/机翻审计，41 路由分级 P1-P3 |

**v3 交付与验证（2026-09-12）**
| 文件 | 摘要 |
|---|---|
| plans/ux-v3-delivery.md | **交付报告**：M1–M10 目标对照、分层验收、六种「假绿」家族、已知限制、生产部署前置与回退、待用户决定项 |
| plans/ux-v3-verification.md | **独立验证报告（verifier，549 行）**：t9 七项 + 各轮补记（t22 覆盖扩展 / t23 越权复核 / t26 治根 / t28 收口 / t37 覆盖声明 / t39 审计 / t48 接缝）+ 判据沉淀（判渲染结果、claim 与证据同级、三层检测分工、误报≠漏报的证明方式） |
| plans/study-hub-v3-design.md | 一条龙学习中心设计（含 §6 旧首页 35 卡落点表、§10 零丢失可达性提案） |
| plans/data-provenance.md | 事实出处台账（含 §8 学费→统筹费逐条改写、§9 币种切换与回滚 SQL） |
| plans/t12-review-t6-onestop-service.md / t13-review-t7.md / t35-review-t7-round2.md | 交叉评审报告（评审人互不评自己的实现；t13 needs_revision → t34 修复 → t35 pass） |
| plans/t32-*.md 等 | 各轮复评留档 |
| tests/smoke/UX_V3_GATE.md | **门禁规范**：三步探活、ENV/真红判据、五类分流、两门禁边界与接缝判据、数据驱动品牌泄漏、运行窗口踩坑 |
| tests/smoke/v3_final_gates.md | 交付前全量门禁复跑的留档（命令 / 退出码 / 关键输出 / 取样有效性） |

**回归与运维（docs/ 根 + plans/）**
| 文件 | 摘要 |
|---|---|
| local-regression.md | ux-rework 本地回归：smoke 三套全绿；通过 |
| v2.1-regression.md | v2.1 全量回归：49 路由×4 角色；上线门禁通过 |
| v2-checklist.md | v2 改造总清单 A 缺陷+B 决策拷问定稿 |
| compliance-audit.md | 合规自查：自研 vs 第三方源码，版权干净 |
| deploy-malaysia.md / deploy-a8-runbook.md | 马来西亚生产拓扑/路径/回滚 + A8 部署手册 |
| yongyue-rebrand.md | 品牌化改造史：品牌信息/汉化工具链/首页移植 |
| telegram-feature-map.md | Telegram×教务对接矩阵，P0 已上线 |
| 功能全景图.html | 可视化全景 |

**运维与交接（docs/ops/）**
| 文件 | 摘要 |
|---|---|
| **ops/web-claude-prompt-pack.md** | **给网页版 Claude 的提示词包**（2026-10-12 立）：开机提示词（15 条硬规矩前置 + 「不许假装测过」口径）+ 派活模板 + 交付格式 + 跑偏纠偏表 + 反向审阅。用途：把「让网页版 Claude 改代码」变成可复制的标准动作 |
| ops/tg-assist-bot-howto.md | 班务机器人「怎么用」一页（大白话，给校长看） |
| ops/tg-assist-bot-handoff-prompt.md | 机器人选型交接提示词（给另一个窗口的 AI） |
| ops/backup-policy.md ｜ ops/backup-offsite-daily.md | 备份策略与异地每日备份 |
| ops/menu-rename-list.md | 后台菜单改名清单（noupdate 处置先例） |
| ops/decommission-201-2026-10-04.md | 201 服务器退役记录 |
| ops/jiaowu-manual.md | 教务操作手册 |

- 设计决策（ADR 类）暂记录在各 plans 文档头部

## 9. 当前账号体系（本地 edu19）

| 角色 | 账号 | 落地页 |
|---|---|---|
| 管理员 | admin（Mitchell Admin 初始） | Odoo 后台 |
| 教务处 | backoffice@local | Odoo 后台（排课/审批菜单可见） |
| 教师 | faculty@local | Odoo 后台 + 门户教师页 |
| 学生 | stu@local（【演示】王小明） | /my/home 门户 |

> 生产上已按用户要求删除学生/家长演示账号，仅保留管理员与 2 个教务账号；本地演示数据仍在（幂等种子可重建）。

## 10. 改动闭环（标准流程）

```
【0 离线自证】python3 scripts/check_english.py --selftest && python3 scripts/check_odoo_trace.py --selftest
    && python3 scripts/check_view_xpath.py --selftest && python3 scripts/check_manifest_tracking.py --selftest
    && python3 tests/smoke/init_cross_table_check.py --selftest
    && python3 scripts/check_qweb_dict_foreach.py --selftest
    （init_cross_table_check：**任何模型的 init() 只能碰自己的表** —— 2026-09-28「跨表回填 ⇒
      psycopg2 UndefinedColumn ⇒ Failed to load registry ⇒ 整站升级退出码 255」的静态判据。
      selftest 6 条（3 条反例必红 / 2 条正例必绿 / 1 条拿真实 assess.py 做对照）；
      全仓 74 个模型文件 0 违规，离线、不连库不联网、<1s。**拿改前那份代码回扫会 FAIL** —— 判据是真判据。
      ✅ **已接进升级链（gate D）**：见下方「改 custom_addons/edu_*」一行；日志 /tmp/edu19_init_cross_table.log）
    && python3 scripts/check_docs_index.py --selftest
    && python3 scripts/check_ui_surface.py --selftest
    && python3 scripts/check_view_selector_attrs.py --selftest
    （check_view_selector_attrs：**视图继承选择器不得用翻译属性** —— 2026-10-14 `roles.xml` 的
      `<xpath expr="//div[@aria-label='周导航']">` 让 `safe_upgrade.sh` 直接 ParseError 整批回滚。
      真源 `ir_ui_view.py:405-424` + `translate.py:75`；selftest 9 样本；当前 82 个视图 XML ⇒ FAIL 0 / WARN 3。
      规则见 §6 第 20 条）
    && python3 tests/smoke/gate_seam_check.py
    （check_view_xpath：继承视图 xpath / 内联 script 裸 < / t-elif 相邻性 / 模型导入顺序，离线约 1.2s）
    （check_manifest_tracking：**manifest 引用集 ⊆ git 跟踪集** —— 抓"文件在盘上但从未入库"（新克隆会加载失败）。
      **零环境依赖**（离线，停机也能跑）；首跑基线 97 已入库 / 0 缺失 / 0 未入库）
    （check_docs_index：**计划文档索引完整性** —— 每份 docs/plans/*.md 必须在本目录 README（`docs/plans/README.md`）恰好登记一次、
      头部状态行合法且与索引逐字一致、取代链无悬空无环且必有横幅。**零环境依赖**（离线，停机也能跑）；
      --selftest 9 反例必报红 / 4 正例不报红，且有一条**对照断言**拿夹具与真实文件逐字比对。
      基线（**2026-09-26 当日读数，仅作历史记录**）：68 份 / 登记 68 / 头部合规 68 / 取代边 7 ——
      **现行份数一律以 `docs/plans/README.md` 页首「最后核对」行为准**，此处不追改）
      ✅ **接入已生效**（t97 修复 + 真实路径演练证明）：`set -e` 下原先 `python3 …` 紧跟 `rc=$?` 是**死代码**
        → 检查器一非零即**当场退出**、后续 gate 永不可达；现改为 `|| rc=$?` 显式承接，且各 gate 先各跑一遍再各自判（互不阻断）。
    （gate_seam_check：两门禁的接缝 —— 同一样本至少一方必须报红、纯中文两边都不报）
    （不依赖站点状态，专抓"工具本身被改坏"；两个都必须 exit 0）
【1 前置探活】无升级锁 + 容器 Up>30s + 带 cookie 访问 /web/login?db=edu19 得 200/302/303
    顺序不可颠倒：**selftest 证明尺子准 → 探活证明环境可用 → 才真跑量东西**。
    selftest 不连站点，**不能**替代探活与真跑（它只回答"工具本身有没有被改坏"）。
改 custom_addons/edu_* → `bash scripts/safe_upgrade.sh <模块>` 冒烟（EXIT=0、无 Traceback、curl 各角色 200/303）
    （⛔ 该脚本**取锁之前**依次跑 4 道**升级前静态门禁**：A manifest 跟踪 → B 继承视图 check_view_xpath →
      C shell 变量 → **D init() 跨表 init_cross_table_check**；每道按自己的退出码契约分级
      —— **只有 1=FAIL 拒绝升级（exit 6）**，2=ENV/3=INCOMPLETE 不拒绝（一刀切会让健康检查把全队升级挡死，2026-09-12 踩过）。
      gate D 2026-09-29 接入：门禁红 ⇒ 升级被拦住并打印判据原文（模块/行号/SQL）；门禁绿 ⇒ 升级照常。
      ⚠ 新增门禁必须同时在这条链与本节登记 —— 判据只写在 tests/ 里、没有任何执行路径调用它 = 规矩只靠自觉）
→ python3 scripts/check_english.py（若动了用户可见文案；口径 must-fix = 0）
→ python3 scripts/check_odoo_trace.py（若动了用户可见页面/文案；口径 0 命中，含属性值）
→ python3 scripts/check_qweb_dict_foreach.py（若动了 QWeb 模板或控制器传参；口径 失败项 0）
→ python3 tests/smoke/ledger_select_labels.py（若动了台账/费用页下拉；口径 10/10，需本地栈在跑）
→ python3 scripts/check_docs_index.py（若动了 docs/plans/ 或新增计划文档；口径 = 退出 0，有未登记/不一致即阻断）
→ python3 scripts/check_ui_surface.py（若动了自定义路由或门户页面；口径 = 退出 0）
→ git commit（中文 conventional 风格，如 feat(downloads): …）
→ bash scripts/deploy_myedu.sh <模块>（远端升级+重启+**升级↔重启配对自证**+就绪探活+冒烟+**活体注册表门禁**；部署前先跑 fix_edu_apply_xmlid.py 干跑预检）
    （**配对自证**：升级容器 rc=0 **且** web 容器 StartedAt **晚于**升级完成时刻（/tmp/upg.done）才算绿；
      不满足 ⇒ 打印「升级成功但 web 未重启，活体注册表仍是旧的，请执行 docker compose restart web」并 **exit 10**。
      为什么要有它：SSH 一断，旧脚本会停在"升级完/没重启"的状态且**不报错** —— 生产于是停在
      「库升了、盘上文件新了、活体进程还是旧的」（2026-09-24 那次事故的形态，09-29 又发生过两次）。
      只查现状（不部署）= `bash scripts/deploy_myedu.sh --verify`；离线判据探针 = `tests/smoke/deploy_web_restart_proof.py`（4/4）；同一判据的普通 shell 门禁 = `python3 scripts/check_shell_exitcode.py`）
```

### 10.1 注册表铁律：**新 .py 必须重启 web 进程**（2026-09-24 生产事故后立）

> **一句话：注册表重载（`-u` 升级）不是重启。改了 custom_addons 里的 .py（尤其新增文件），
> 必须重启 Odoo web 进程；否则就会出现模型「库里有、活体进程没有」。
> 判据 = `python3 scripts/check_live_registry.py`（有 DARK ⇒ exit 1）。**

**机制**：web 进程启动时 import 全部模块，注册表（IR）此后是**进程内状态**。
**一个已经被导入过的模块里，rsync 上来的新文件不会被带进这个正在跑的进程** ——
`docker compose run … odoo -u <模块>` 只更新**数据库**与**执行升级的那个一次性容器**。
⇒ 菜单点得开、模型不存在（404）、cron 抛 `KeyError`。
**反例（千万别用）**：新开一个 `odoo shell` 或任何新进程去看模型 —— 新进程会重新 import，
天然看得到，拿它验证「生产认不认识这个模型」必然假绿（本次事故的定性证据正是这一组对比）。

**事故事实（生产 edu19-prod-web-1，已定案）**

- 窗口：web 容器自 **2026-09-18 05:13Z** 连续运行到 **09-24 01:52Z** 未重启；期间
  **09-18** 上线 `custom_addons/edu_portal/models/class_batch.py`（**零新模型**：只给基座
  `op.batch`/`op.student`/`op.student.course` 加回收站与分班行为 + `ir.ui.menu` 可见性，
  `5bf346d` 新增 371 行），
  **09-21** 上线 `custom_addons/edu_portal/models/course_rep.py`（模型 `edu.course.rep`），
  **09-22** 上线 `custom_addons/edu_portal/models/major_track.py`（模型 `edu.course.subject` +
  `op.course` 新字段 `edu_level_id`）；三例都是 rsync + 独立一次性容器升级 + **没重启 web**。
- 症状 ①（模型不在活体注册表）：`POST /web/dataset/call_kw model=edu.course.rep` → **404**
  （`werkzeug.exceptions.NotFound` / JSON-RPC code 404；浏览器控制台同样 404）；
  同一进程里对照模型 `op.course` 正常应答 ⇒ 会话/网络无问题，缺的就是注册表项。
- 症状 ②（新字段不在活体注册表）：`op.course method=fields_get` **没有** `edu_level_id`。
- 症状 ③（每天 01:43 的 cron 连败三天）：cron「edu_portal: 课代表到期收口（实时判定结果落库）」(44)
  在 **2026-09-22 01:43:26 / 09-23 01:43:48 / 09-24 01:43:05** 各失败一次，`KeyError: 'edu.course.rep'`；
  同期日志另有 `ERROR odoo.addons.base.models.ir_model: Missing model edu.course.rep`。
- 后果：**班级管理**（09-18 07:55Z 起）、**课代表**（09-21 03:13Z 起）与**专业/学制**（09-22 02:22Z 起）
  三个功能在生产**暗着**（入口可见、点进去没有模型；班级管理是**零新模型**的新 .py，暗的是新增方法
  不在活体进程），直到 **09-24 01:52Z** 重启；时长分别约 **5 天 18 小时**、**2 天 23 小时**、
  **1 天 23 小时**（起点取各自入库提交时刻）。
- 处置：`docker compose restart web`（约 16s；站点 3s 内恢复）后上述探针全部转正常。

**规矩**

1. 改了 `custom_addons/edu_*` 的 .py（**尤其新增 .py / 新增模型字段**）⇒ **部署必须重启 web**。
   `scripts/deploy_myedu.sh` 已按此重写：rsync → 权限 → **独立一次性容器升级（web 不停机）**
   → **一律 `docker compose restart web`**（约 15-20s）→ **有界轮询 `/web/login` 到 200|302，超时硬失败**
   → 冒烟 → **活体注册表门禁**。
2. 门禁怎么跑：本地 `python3 scripts/check_live_registry.py`；
   生产 `ssh prod-host 'cd /opt/edu-app && python3 scripts/check_live_registry.py'`。
   它取 `ir_model_data`（模块 ∈ `custom_addons/edu_*` 且 `state=installed`）里的 `ir.model` /
   `ir.model.fields` 行作**库真相**，逐条问**跑着的 web 进程**（`call_kw`）；
   有 DARK 即 `exit 1` 并打印处置命令；判据不可用（ENV）`exit 2`，不得当结论。
3. 判定口径（防假红）：**只有 `werkzeug.exceptions.NotFound`（404）算 DARK**；
   `AccessError` / `SessionExpiredException` 算 **LIVE**（模型在注册表里，只是当前身份读不到）。
   2026-09-24 有人用「任何 error 都算 DARK」的写法试跑，一次报出 5 个假红
   （`edu.alert.read` / `edu.alumni.job` / `edu.deadline` / `edu.download.ack` / `edu.tg.bot` 都明明在代码里）；
   `--selftest` 用现场捕获的真实报错样本把这条钉死（9/9）。
4. 门禁**只信跑着的进程**，因此它也**不覆盖**「rsync 了但从未 `-u` 升级」这件事（库里也没有行）；
   那一环由 deploy 的升级步骤 + 升级日志失败特征负责。
5. 给会话（`EDU_CHECK_LOGIN` / `EDU_CHECK_PASSWORD`）时门禁额外核对**字段级**；不给会话
   （生产常态：除 `odoo shell` 外没有 web 账号）则字段级**明写 SKIP**，不会静默当绿。

### 10.2 前端样式铁律：**本站有两套色板，公开页的按钮/链接必须显式覆盖**（2026-10-06 立）

> **一句话：`brand_tokens.scss`（A 套）注册在 `web._assets_primary_variables`，前后台都生效；
> 公开营销页的纸金（B 套）只作用于 `.yylc-home`。两者**同名不同值**，公开页上不许依赖 A 套的颜色。**

**实测症状（2026-10-06）**：公开页导航的「联系我们」渲染成 A 套工作台蓝 `rgb(12,109,215)`
（`class="oe_unremovable btn btn-primary btn_cta"`），与整页金/墨/纸调性打架。

**规矩**

1. **覆盖写在哪，决定影响范围**：`edu_brand/static/src/css/brand.css` 只注册在 `web.assets_frontend`
   ⇒ 在它里面覆盖 `.btn_cta` 等**只影响前台，后台工作台保持蓝**。**不要把公开页的覆盖写进 `brand_tokens.scss`**（那会波及后台与 PDF 报表）。
2. **同名不同值要当心**：`--border` 在 `:root` 是 `#E3E9F2`、在 `.yylc-home` 被覆盖为 `#e5ded4`。
   公开页上误用 A 套值 ⇒ 纸色底上偏冷偏灰。对照表见 `.superdesign/init/theme.md §0`。
3. **新增公开页样式一律限定作用域**（`.yylc-home` / `.yylc-page` / `.yylc-footer` / `.oe_website_login_container`），**不许裸写全局选择器**。
4. **改公开页样式后必须真渲染复量**（Playwright 读 `getComputedStyle`），不能只看 CSS 源码 ——
   本项目已多次出现「改了源码但渲染结果不对」（量具与口径教训见 `docs/design/` 下各篇）。
5. ⚠ **不要用 `curl` 判「页面内容对不对」**（2026-10-06 一天内连栽三次）：
   - 判「187 的站点是否在服务」时，`curl` 拿到的与浏览器渲染的不是同一份；
   - 判「登录页校徽在不在」时，`curl | grep` 命中 0，而 Playwright 实测元素存在、渲染宽度 72px；
   - 判「首页 kicker 是中文还是英文」时，`curl` 带 zh-CN/en-US 两种 `Accept-Language` **两个串都是 0 命中**。
   **`curl` 只适合判 HTTP 状态码与可达性；凡涉及「页面上有什么」，一律用浏览器（Playwright）真渲染。**

### 10.3 本地升级铁律：**升级前先停 web**（2026-10-06 立）

> **一句话：`safe_upgrade.sh` 是在正在运行的 web 容器里 `docker compose exec` 跑升级的 ⇒
> 同一容器里会有两个 Odoo 进程共用一个库，与容器自带的 cron 线程撞在 `ir_cron` 上。
> 确定性做法：`docker stop <web>` → `safe_upgrade.sh <模块>` → `docker start <web>`。**

**实测报错（2026-10-05，偶发）**

```
ERROR odoo.sql_db: bad query: SELECT "ir_cron"."id" FROM "ir_cron" WHERE … FOR NO KEY UPDATE SKIP LOCKED
ERROR: could not serialize access due to concurrent update
⇒ odoo.registry: Failed to load registry ⇒ CRITICAL: Failed to initialize database
```

⚠ **报出来的是假线索**：registry 加载失败后，转换阶段会抛
`ParseError: while parsing …/edu_schedule/data/cron.xml` —— **与那个文件毫无关系**，
照着它去改 `cron.xml` 会白费功夫。**先看 `ir_cron` 那两行 ERROR。**

**为什么偶发**：容器自带的 cron 线程每 5 分钟醒一次，撞上就失败。所以「以前一直好好的」不构成反驳。

### 10.4 推送铁律：**比「未推送」之前先 `git remote -v` 确认远端名**（2026-10-12 立）

> **一句话：本仓远端叫 `github`，不叫 `origin`。用 `origin/xxx` 去比，比的是一个不存在的引用 ——
> 命令报错、stderr 被丢掉、空输出被 `wc -l` 数成 0，屏幕上是「0 未推送」= 假绿。**

**实测经过（2026-10-12）**

```
$ git log --oneline origin/main-real..HEAD 2>/dev/null | wc -l
0                      ← 屏幕上写着「没有未推送」，看着全绿

$ git remote -v
github  git@github.com:faust2510/yongyue-edu-system.git   ← 远端名是 github，压根没有 origin
```

**真实读数（同一天，用对的名字）**：

| 引用 | 指向 | 含义 |
| --- | --- | --- |
| `github/main-real` | `bf21bab`（2026-10-02） | 远端停在 10-02 |
| `main-real`（本地） | `c9fb894`（2026-10-12） | 本地领先 **242 个提交** |

⇒ **10 天的工作（机器人 F1–F7、前门 edu_tg_gate、审计与设计文档…）压根没推上 GitHub。**

**同一轮还抓到默认分支的坑**：GitHub 上的**默认分支是 `release-clean`（2026-08-24，落后 main-real 1013 个提交）**。
任何「按默认分支克隆 / 读取」的人或工具（**包括网页版 AI 连仓库**）拿到的都是 8 月的旧代码。
已用 `gh repo edit faust2510/yongyue-edu-system --default-branch main-real` 改掉，并 `git ls-remote --symref github HEAD` 复核。

**确定性做法（三行，缺一不可）**

```bash
git remote -v                                          # ① 先拿远端名，别假定 origin
git rev-list --count github/main-real..main-real       # ② 比对**不要**加 2>/dev/null，让错误出声
git ls-remote --symref github HEAD                     # ③ 确认默认分支指向哪个 ref
```

**教训一句话**：**「看不到」不等于「没有」。把 stderr 扔掉、再用行数判空，等于给自己发一张假绿。**
（同族病：`psql … 2>/dev/null` 把 `ERROR: column does not exist` 吞成「0 条」；`git commit … | tail -4; echo $?` 取的是 `tail` 的退出码。）
