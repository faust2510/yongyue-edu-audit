# 重建清单：B 类 19 条 → 可执行步骤（新服务器实测版）

> **状态**：`执行预案（含实测基线）`｜**作者**：loss-ledger（task-3 续作）｜**日期**：2026-10-01
> **写作范围**：`docs/audit/migration/`（本目录）
> **上游**：本目录 `data-loss-ledger.md`（B 类 19 条的损失判定与证据）；本文回答「**怎么把它做回来**」。
> **前提**：旧机 `203.0.113.10` **彻底不可恢复**（用户原话「全没了」）⇒ B 类 19 条全部走重建。
> **新机**：`203.0.113.11`（ssh 别名 **prod-host**，密钥 `~/.ssh/my_edu_ed25519`），**本次已实测**（见 §1）。
> **纪律**：不改 `custom_addons/**`、不 `git commit`、不碰 `评估表格/`；每条结论标证据，查不到的标「未验证」。
> ⚠ **行号会漂**：本目录**外部**的 `文件:行` 引用在 2026-10-01 复核过；仓库规范本身要求「不要用行号引用（插入即漂）」，因此本文件已尽量把外部引用改写成「**文件 + 章节标题/特征串**」。两把尺子（`verify_plan_evidence.py` / `verify_ledger_evidence.py`）会在别人改动后**立刻报红**，请以它们的输出为准重新定位。


---

## 0. 结论速览

| 类 | 含义 | 条数 | 条目 |
|---|---|---|---|
| **甲** | **能脚本重放**（仓库有现成脚本 + 源数据，幂等可复跑） | **6** | B5 排课 216 节 ｜ B6 课程清单 ｜ B7 专业编排 ｜ B8 班级迁移 ｜ B13 评估结构（0 行） ｜ B14 到堂打卡类型（**实测已存在**） |
| **乙** | **能半自动**（脚本需改参数/需补少量输入，或功能有向导但要人操作） | **8** | B2 学生主档 ｜ B9 请假 ｜ B12 财务 ｜ **B15 上传文件（部分自动恢复，见 §4.8）** ｜ B16 字体附件 ｜ B17 报名 ｜ B18 邀请码 ｜ B19 单号序列 |
| **丙** | **只能人工**（无脚本可代劳） | **5** | B1 账号（→§6） ｜ B3 学籍档案与分班 ｜ B4 报课单 ｜ B10 站内信 ｜ B11 审计日志 |

### 0.1 「顺序陷阱」已实测解除（但顺序仍然不能反）

**实测（2026-10-01 13:47Z，新机 `edu19`）**：
- `ir_module_module`：**`edu_portal` = `19.0.4.0.0` installed**（evidence Q1）；
- 表 **`edu_course_subject` 存在且已有 14 行**，另有 `edu_leave_transfer`、`edu_fee_category` 同在（evidence Q1 §2）⇒ **`migrations/19.0.3.0.0` / `19.0.4.0.0` / `19.0.2.0.0` 三个迁移都已跑过**。

⇒ **课程清单导入可以直接做**（`op.course.subject_ids` 现在是非存储 computed + inverse，写入会落到 `edu_course_subject`）。

⚠ **但「先排课后导入课程」这个顺序不能反**——不是因为迁移，而是因为**科目计数**：

| 步骤 | `op_subject` | 课程导入 DRY_RUN 会看到的三个数 | 证据 |
|---|---|---|---|
| 现在（8/30 快照态） | **14** | 既有 **14** / 已存在 **2** / 新建 **122** | 本次实测（evidence §B） |
| 先跑 B5 排课（新建 18 科） | **32** | 既有 **32** / 已存在 **9** / 新建 **115** | 推算；09-14 生产实测同值（`docs/curriculum/import-report.md:30-35`） |
| 再跑 B6 课程导入 | **147** | —— | `docs/curriculum/import-report.md:31` |

> ⇒ **目标 147 只有在「先 B5」的前提下才成立**。若先跑 B6，最终 `op_subject` = 14 + 122 = **136**，与 09-14 的历史态差 11 个科目（正好少掉排课导入自带的那些）。
>
> ✅ **2026-10-01 已按此顺序真跑完毕**：B5 → B6，终态 **`op_subject` 147 / `edu_course_subject` 320 / `op_session` 216**（执行记录与对账见 §11）。

### 0.2 今天就能跑的脚本（真实路径；详见 §7）

| 序 | 命令（新机形态） | 对应 | dry-run？ |
|---|---|---|---|
| 1 | 本机：`python3 timetable_import/import_sessions.py --dry-run` | B5 预检（**离线不连库**） | ✅ |
| 2 | `ssh prod-host '… odoo shell …' < timetable_import/import_sessions.py`（`SESSIONS_CSV` 注入） | B5 落库 | ✅ 先 1 |
| 3 | `ssh prod-host '… odoo shell …' < scripts/import_curriculum.py`（`DRY_RUN=1` / 不带） | B6/B7 | ✅ |
| 4 | `ssh prod-host '… odoo shell …' < scripts/ops/retire_old_batches.py` | B8（**不可逆**，B5 之后） | ❌ |
| 5 | `ssh prod-host '… odoo shell …' < scripts/merge_checkins.py --apply` | B14（**实测已无需做**） | ✅ 默认 dry-run |
| 6 | `/opt/edu-app/scripts/switch_currency_cny.py`（**脚本已在新机上**） | C2 | ❌（幂等） |
| 7 | `/opt/edu-app/scripts/setup_brand_yongyue.py` → `/opt/edu-app/scripts/seed_d1_nav.py` | C1/导航（**顺序不可反**） | ❌（幂等） |
| 8 | `/opt/edu-app/scripts/create_teacher_account.py` + `/opt/edu-app/scripts/fix_teacher_user_backlink.py` | 教师占位 | ❌（幂等） |

> **实测**：新机 `/opt/edu-app/scripts/` **已经有** `import_curriculum.py` / `merge_checkins.py` / `switch_currency_cny.py` / `setup_brand_yongyue.py` / `seed_d1_nav.py` / `create_teacher_account.py` / `safe_upgrade.sh` / `deploy_myedu.sh`；**没有** `ops/retire_old_batches.py`，也**没有** `timetable_import/` ⇒ 第 2、4 条必须从本机经 `ssh … < 文件` 送入。

---

## 1. 新服务器实测基线（2026-10-01 已跑通；原始输出见 evidence 目录）

**复跑形态**（本机 → ssh → 容器；SQL 一律走 `.sql` 文件 + `psql -f -`，**不要**把 `$` 放进 bash 双引号）：

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY ssh -o ConnectTimeout=25 prod-host \
  'docker exec -i edu19-prod-db-1 psql -U odoo -d edu19 -A -P pager=off -f -' < /tmp/q.sql
```

### 1.1 关键读数（N1 / N2 / N3 / N5 全部闭环）

| # | 项 | **实测值**（2026-10-01 13:47Z） | 结论 |
|---|---|---|---|
| N2 | `edu_portal` 版本 / 迁移产物 | **19.0.4.0.0 installed**；`edu_course_subject` **存在 14 行**；`edu_leave_transfer` 存在；`edu_leave.applicant_kind` 列在；`op_batch.homeroom_teacher_id` 列在；`edu_fee_bill.category_id` 列在 | ✅ **三个迁移都跑过** ⇒ 顺序陷阱解除 |
| N3 | 旧模块残留 | `edu_eval` **uninstalled**（`ir_model` 命中 0、菜单命中 0、`edu_admin_eval_template` = NULL）；`edu_telegram` **installed (19.0.2.2)**；`edu_feedback` **不在模块表里** | ✅ N3 闭环 |
| N1 | 业务读数 | `op_subject` **14**（全是 `PRP-C01..C14`）｜`op_course_op_subject_rel` **14**｜`edu_course_subject` **14**｜`op_session` **0**｜`op_batch` **1**（`id=8 预备科 · 2026级【演示】`）｜`op_faculty` **0**｜`op_timing` **3**｜`op_student` **1**（王佐，`gr_no` 为空）｜`op_student_course` **0**｜`op_course` **6**｜`op_academic_term` **2** | ✅ 这是 **8/30 快照态**，比台账里的 09-24 目标态**早 3 周** |
| N1 | 逐课程挂接 | `CRS-PRP` 14 条；`CRS-MCS/BTH/BLA/BED/HSA` **各 0 条** | ⇒ 课程导入会往那 4 个学位课程加挂接（预期 +306） |
| N5 | 账号 | 共 **8 行**；**active 只有 2 个：`admin`(id2) 与 `qnj2510798178@gmail.com`(id19=王佐, share=t)**；**`backoffice@local`(id12) 与 `jiaowu@local`(id18) 存在但 `active=f`**，且两者组已是「角色/用户 + 经理 + 后台·完整视图」3 组 | ✅ 教职工**不用新建**，只需 `active=t` + 重设口令 |
| — | 币种 | 公司 id1「永约学坊」`currency_id=1`(**USD**)；`USD active=t` / **`CNY active=f`** | ❌ **C2 尚未执行** |
| — | 财务 | `edu_fee_bill` **0**；`edu_fee_category` **15** | 分类已由模块 data 建好 |
| — | 系统参数 | `edu.apply.deadline` / `edu.enroll.deadline` = **2026-10-01**；`mail.default.from` = `scrtsschool@gmail.com`；**`edu_nav.consolidated_count` 不存在** | C3 基本就绪；C9 未收口 |
| — | 菜单 | `ir_ui_menu` **610** 行 / **409** active；`edu_nav` 守卫启动即报 ERROR「期望 357 条收口记录，但参数声明为 0」（根菜单 39 / 停用 25） | ⚠ C9 需处理 |
| — | 序列 | 4 条序列 **`number_next` 都是 1**（`SR` / `EDU-CERT-` / `REB` / `CERT/`） | B19：新库序列干净，需人工定起始号 |
| — | 打卡 | `edu_checkin_type` **4 条**（读经/灵修/周记/**到堂打卡**）；`edu_checkin_record` **0**；`edu_daily_checkin` **0** | ✅ B14 **已无需做**（类型由模块 data 建好，且无历史行要 merge） |
| — | 其他业务表 | `edu_leave` 0 ｜ `edu_message` 0 ｜ `edu_audit_log` 0 ｜ `op_subject_registration` 0 | 都需重建（数量见台账） |
| — | 附件 | `ir_attachment` **971** 行，其中 `store_fname` 非空 **709**；**`edu*`/`op.*` 业务附件 = 0 行** | ⇒ **8/30 快照里根本没有业务上传件**（详 §4.8） |

> **附件/行数报数口径（钉死，对应 N13）**：本目录任何一次报数**必须带「时刻 + 分母」**，形如「2026-10-01T13:50:50Z，分母 = 8/30 快照的 710 行」。
> 原因：实测同一库在十几分钟内 `ir_attachment(store_fname)` 就从 707 漂到 709、filestore 从 265 漂到 266 —— **Odoo 每次 registry 加载/生成资产都会新增附件**，不带时刻与分母的数字必然对不上。


| 项 | 实测 |
|---|---|
| OS / Docker | Ubuntu **26.04.1 LTS**；Docker **29.8.2**；Compose **v5.5.1** |
| 部署目录 | `/opt/edu-app/{backup,config,custom_addons,data,docker-compose.yml,openeducat_erp,scripts}` |
| 容器 | `edu19-prod-db-1`（postgres:16，healthy）、`edu19-prod-web-1`（odoo:19） |
| 端口 | web 绑 **127.0.0.1:8069 / 8072**；`curl 127.0.0.1:8069/` → **200** |
| 挂载 | `./openeducat_erp → /mnt/extra-addons`、`./custom_addons → /mnt/custom-addons`、`./config/odoo.conf → /etc/odoo/odoo.conf:ro`、**`./data/web → /var/lib/odoo`** |
| odoo.conf | `data_dir = /var/lib/odoo`（⇒ filestore = 宿主 `/opt/edu-app/data/web/filestore/edu19`）；`list_db=False`、`proxy_mode=True`、`workers=2` |
| 还原源 | `/opt/edu-app/backup/edu19_post_cleanup_0830.dump`（**10,234,709 B**，与本机备份同字节数） |
| 服务器上的脚本 | `/opt/edu-app/scripts/`：`import_curriculum.py` `merge_checkins.py` `switch_currency_cny.py` `setup_brand_yongyue.py` `seed_d1_nav.py` `create_teacher_account.py` `safe_upgrade.sh` `deploy_myedu.sh` —— **没有** `ops/retire_old_batches.py`、**没有** `timetable_import/` |
| 凭据（弱点，登记） | compose 里 `POSTGRES_PASSWORD=odoo`（4 字符，与旧机同款弱口令）；DB 只绑容器网络、未对外 |

### 1.3 三个本次踩到的环境坑（写下来免得下一个人再踩）

1. **`docker exec -i` 会吃掉 `bash -s` 的剩余脚本**：用 `ssh prod-host 'bash -s' < script.sh` 喂多行脚本时，脚本里第一个 `docker exec -i …`（哪怕只是 `psql -c`）会把**脚本剩下的行当自己的 stdin 读走**，表现为「后半段静默不执行、输出为空」。**修法：`docker exec` 不要 `-i`，或显式 `</dev/null`**。
2. **`op_subject` / `op_batch` 的 `name` 是 `varchar`，不是 jsonb**：`name->>'zh_CN'` 会报 `operator does not exist: character varying ->> unknown`；直接 `select name` 即可（`ir_ui_menu.name` 才是 jsonb）。
3. **`ir_sequence` 没有 `number_next_actual` 列**（PG16/Odoo19 实测报错）⇒ 用 `number_next`。

### 1.4 原始证据文件（本次交付）

| 文件 | 内容 |
|---|---|
| `docs/audit/migration/evidence/2026-10-01-newserver-readings.txt` | Q1/Q3/Q4/Q5 四段原始输出（965 行） |
| `docs/audit/migration/evidence/2026-10-01-import-dryruns.txt` | 排课离线 dry-run + 课程导入 DRY_RUN + 零写入对照（112 行） |
| `docs/audit/migration/evidence/2026-10-01-filestore-recovery.txt` | 附件字节抢救的方法、数字与逐模型对账（见 §4.8） |
| `docs/audit/migration/evidence/2026-10-01-b5-execution.txt` | **B5 真跑**的备份 sha256 / dry-run / 真跑输出 / 前后对账 / 幂等复跑（见 §11） |

---

## 2. 执行顺序（实测后的版本）

```
[0] 对账（§1 已跑完） + pg_dump 基线
        │
        ├─► B5 排课：import_sessions.py ──► op_subject 14→32 / op_batch 1→17 / op_session 0→216
        │        │                          （实测 dry-run：16 批 + 1 占位教师 + 216 节）
        │        └─► B8 班级迁移（**必须在 B5 之后**；本机送入 ops/retire_old_batches.py）
        │
        ├─► B6 课程清单（**必须在 B5 之后**）：既有 32 / 已存在 9 / 新建 115 ──► op_subject 147
        │        └─► B7 专业编排：edu_course_subject 14 →（预期 ≈320）
        │
        ├─► C2 币种 / C1 品牌+导航 / C9 菜单收口（C8 已由 module data 完成）
        │
        └─► 乙类（B15 已有部分回填 / B12 / B16 / B18 / B19）→ 甲类完成后并行
                 │
                 └─► 丙类（B1 / B3 / B4）—— 需要校方输入，最后且最久
```


---

## 3. 甲类 —— 能脚本重放（6 条）

> 每条按六项写：**脚本路径 / 源数据路径 / 幂等性证据 / DRY_RUN 怎么跑 / 预计产生多少行 / 依赖哪些模块**。

### 3.1 B5 排课 216 节（+ 18 科 / 16 班 / 10 timing / 1 占位教师）

| 项 | 内容 |
|---|---|
| 脚本路径 | `timetable_import/import_sessions.py`（**新机上没有这个目录**，必须由本机经 `ssh … < 文件` 送入）；`timetable_import/run_import_local.sh` 是本地入口（新机不可直接用，容器名/路径不同） |
| 源数据路径 | `timetable_import/sessions.csv`（实体主表）+ `timetable_import/full_sources.csv`；唯一数据契约 `timetable_import/catalog.md` |
| 幂等性证据 | 判重键 `(batch_code, subject_code, 本地日期, 本地 start HH:MM)`，先查后建（`timetable_import/import_sessions.py:39`，判重实现 `:517`）；重跑预期 `created=0 / skipped=216`（`timetable_import/PRODUCTION_CHECKLIST.md:47`） |
| DRY_RUN 怎么跑 | **离线**：`python3 timetable_import/import_sessions.py --dry-run`（不连库；**本次已跑**，输出见 evidence `…import-dryruns.txt` §A） |
| 预计产生多少行 | **16 `op.batch` + 18 `op.subject` + 1 `op.faculty`（TBD-TEACHER「待定教师」）+ 10 `op.timing` + 216 `op.session`**（`PRODUCTION_CHECKLIST.md:71`；dry-run 实测：16 批逐条列出、导出计划 216 行） |
| 依赖哪些模块 | `openeducat_core` + `openeducat_timetable`（已 installed）；**`edu_portal` 必须已装**（脚本结尾 `S('edu.audit.log')._log(...)`，`import_sessions.py:584`）—— **实测已装** |
| **实测基线影响** | 新机当前 `op_batch` **1**（仅演示批 `PRP-2026`）、`op_subject` **14**、`op_session` **0**、`op_timing` **3** ⇒ 跑完应为 `op_batch 17 / op_subject 32 / op_session 216 / op_timing 13`（timing 若与既有 3 条判重则为 13 或更少，**跑完以库为准**） |

### 3.2 B6 课程清单（115 科 + 296 挂接）

| 项 | 内容 |
|---|---|
| 脚本路径 | `scripts/import_curriculum.py`（129 行，odoo shell 脚本）—— **新机 `/opt/edu-app/scripts/` 里已有同名文件** |
| 源数据路径 | `docs/curriculum/yongyue-curriculum.csv`（表头 `课程,学分,性质,类别,适用学位`，124 行）—— 需 `scp` 到新机并 `docker cp` 进 web 容器 |
| 幂等性证据 | 按科目名命中即「已存在」不新建（`:71-74`）；新增挂接前判 `if subj.id not in c.subject_ids.ids`（`:111-113`）；09-14 生产第 2 次运行实测 0 新建 / 0 挂接（`docs/curriculum/import-report.md:28-35`） |
| DRY_RUN 怎么跑 | `-e CSV=/tmp/yongyue-curriculum.csv -e DRY_RUN=1`（语义 `:18`，文档 `:11`）。**本次已在新机跑过**，见 evidence §B |
| **实测数字（新机，B5 之前）** | `既有科目 = 14 ｜ 课程 = 6 ｜ 新建 = 122 ｜ 已存在 = 2 ｜ 跳过 = 0 ｜ 断言 122+2+0 = 124 ✓` |
| **预期数字（先跑 B5 之后）** | `既有 32 / 已存在 9 / 新建 115` ⇒ **`op_subject` = 32 + 115 = 147**（与 09-14 历史态一致） |
| ⚠ dry-run 的假象 | DRY_RUN 下 `新增挂接 = 0` **不代表没有挂接**：脚本对「将新建」的科目走 `subj is None` 分支、跳过计数（`scripts/import_curriculum.py:108-110`）⇒ **挂接数只能落库后量**，预期 `+306`（见 B7） |
| 依赖哪些模块 | `openeducat_core` + **`edu_portal`**（非存储 computed + inverse 在 `custom_addons/edu_portal/models/major_track.py:95-99`）；**两者都已 installed** |

### 3.3 B7 专业编排（`edu_course_subject`）

| 项 | 内容 |
|---|---|
| 脚本路径 | ① 模块迁移（**已跑过**）：`custom_addons/edu_portal/migrations/19.0.3.0.0/post-migrate.py`；② 新增挂接由 B6 的导入经 inverse 写入 |
| 源数据路径 | 老表 `op_course_op_subject_rel`（新机 **14 行**，全是 `CRS-PRP`）+ B6 导入的挂接 |
| 幂等性证据 | 迁移四纪律：只增不改 / `NOT EXISTS` + 新表 `unique(course_id, subject_id)` / 自证不过 `raise` 回滚 / 全新库跳过（迁移文件头） |
| DRY_RUN 怎么跑 | 模块迁移无 dry-run；**用 §1 的 `to_regclass` + `count(*)` 代替**（已跑：表在、14 行） |
| **前置守卫（可执行）** | `bash docs/audit/migration/precheck_b6.sh` —— 断言 `edu_portal` installed + 版本 ≥ **19.0.3.0.0** + `to_regclass('edu_course_subject')` 非空 + 新表行数 ≥ 14；**正跑 exit 0**，`PRECHECK_NEGATIVE=1`（反向注入不存在的版本）**恰好 1 条 FAIL、exit 1**，其余 3 条控制组仍 PASS。**跑 B6 之前必须先过这条守卫** |
| **实测基线** | `edu_course_subject` **14 行**（CRS-PRP 14；`CRS-MCS/BTH/BLA/BED/HSA` 各 0） |
| **实测产生多少行** | **320**（14 存量 + **306** 新增；2026-10-01 B6 真跑实测）。与旧生产 334 的差 14 = 旧库那 24 条非 PRP 手工挂接 − 其中 10 条与 CSV 撞车（算得清，见 §11.2 注） |
| 依赖哪些模块 | `edu_portal`（迁移与 inverse）+ `openeducat_core` |
| ⚠ 不可重放部分 | 教务在后台逐行设的**必修/选修覆盖值**（09-22→09-24 生产从 334 涨到 478 的 +144，来源无记录） |

### 3.4 B8 班级迁移（12 班退役 + 总览班 + 139 节重挂）

| 项 | 内容 |
|---|---|
| 脚本路径 | `scripts/ops/retire_old_batches.py`（执行稿；**新机 `/opt/edu-app/scripts/` 里没有**，须本机送入） |
| 源数据 | 无外部文件：就地处理「12 个 inactive 旧班 + 其名下课时」 |
| 幂等性证据 | 文件头自陈「本文件即本轮实际执行的完整脚本…生产库当前状态就是本文件的执行结果」（`:3-5`）；总览班按 `code` get-or-create；重挂走 raw SQL 只改 `batch_id` |
| DRY_RUN | **无** ⇒ 先 `pg_dump`，且**必须在 B5 之后** |
| 预计行数 | +1 `op.batch`（`OVERVIEW` 总览班）+ 139 节 `batch_id` 重挂（`op_batch` 19→12 是旧机口径） |
| ⚠ 新机差异 | 新机当前只有 **1** 个批（演示 PRP）⇒ 本脚本的「12 个 inactive 旧班」前提在跑完 B5（生成 16 批）之前**不成立**，顺序不可跳 |

### 3.5 B13 评估（结构自动，0 行业务数据）

| 项 | 内容 |
|---|---|
| 脚本 | 不需要：`edu_assess` **已 installed**（`19.0.1.0.0`） |
| 实测 | 生产旧两套 0 行（台账 B13）；新机 `edu_eval` uninstalled、`ir_model` 命中 0 |
| 预计行数 | **0**；若要重建旧 A 套定义 ≈ 4 模板 + 13 项 + 1 任务，只能人工（或从 08-25 dump 抽，若还能拿到） |

### 3.6 B14 「到堂打卡」类型 —— **实测已无需做**

| 项 | 内容 |
|---|---|
| 实测 | `edu_checkin_type` **已有 4 条**：读经打卡 / 灵修打卡 / 周记 / **到堂打卡**（全部 active）；`edu_checkin_record` **0**、`edu_daily_checkin` **0** |
| 结论 | 类型由模块 data `custom_addons/edu_life/data/demo_life.xml:36` 的 `_ensure_attend_checkin_type` 自动建好；**没有历史行需要 merge** ⇒ `scripts/merge_checkins.py` 本次**不需要跑** |
| 保留脚本 | 若将来从别处搬回 `edu_daily_checkin` 数据，再用 `scripts/merge_checkins.py`（默认 dry-run，`:27`；幂等自陈 `:20`） |

---

## 4. 乙类 —— 能半自动（8 条）

### 4.1 B2 学生主档

- **实测基线**：`op_student` **1 行**（id 11 王佐，`gr_no` 为空、email `qnj2510798178@gmail.com`）；目标态（09-24）是 **29 名**（含 5 名【待分配】）。
- 导入功能现成：「学生 CSV 两段式导入」（`docs/plans/README.md:68`），**源数据（名册）不在仓库**。
- **要什么输入**：姓名 / 邮箱 / 学号（唯一真身 `op.student.gr_no`，`docs/code-map.md:59`）/ 课程 / 班级。
- 仓库里已有 12 个真名（`docs/audit/security-audit-app.md:501`），**邮箱除王佐外一个都没有**。
- **不要用** `scripts/seed_*.py` 一族（写的是【演示】数据，`docs/plans/data-provenance.md:18` 红线）。
- 工时（估算）：**0.5–1 人日**（不含校方整理名册）。

### 4.2 B9 请假 / 申诉

- **实测**：`edu_leave` **0 行** ⇒ 新机上没有历史请假要恢复；结构列（`applicant_kind`）已在（`migrations/19.0.4.0.0`）。
- 若校方要补录历史请假：当事人重提 + 审批人重批（**审批留痕不可重建**）。工时 **0.1 人日**。

### 4.3 B12 财务

- **实测**：`edu_fee_bill` **0**、`edu_fee_category` **15**（分类已由 `custom_addons/edu_portal/data/fee_categories.xml` 建好）；**币种仍是 USD**（见 C2）。
- 要做：先跑 C2 切 CNY，再按旧台账补那两笔（含「接待 ¥850」→ 报销单 `REB000012`，内容见 `docs/plans/fee-categories-design.md:138`）。工时 **0.2–0.5 人日**。

### 4.4 B16 字体本地化附件

- **实测**：`ir_attachment where name like 'google-font%'` = **0** ⇒ 未做。
- 脚本**不在 `scripts/`**，逐字写在 `docs/plans/google-fonts-localization-report.md` §7；依赖新机能出网到 `fonts.googleapis.com`；附件 id 不能照抄旧的 `1317`（`:7-10`）。
- 验收：`LIKE 'google-font%'` = **54**，另 `LIKE '%(google-font)%'` = 1。工时 **0.2 人日**。

### 4.5 B17 报名申请（`/apply`）

- 功能在、答卷不可重建；新机 `edu_application` 情况见跑库（**未测**）。通知申请人重填 + 导出留档。工时 **0.2 人日**。

### 4.6 B18 邀请码

- 功能在：`edu.invite.code.batch` 向导 + `action_generate`（`custom_addons/edu_portal/models/invite_code.py:685`；说明 `:13`）；旧码无需恢复。工时 **0.2 人日**。

### 4.7 B19 单号序列

- **实测**：4 条序列 `number_next` **全为 1**（`op.subject.registration`(SR) / `edu.certificate`(EDU-CERT-) / `edu.reimburse.seq`(REB) / `op.student.certificate`(CERT/)）⇒ 新库从 1 起，**不会重号**；只有在「要与历史单号连续」时才需人工设起始值。
- 锚点：旧生产最大 `SR0017`、`REB000012`（`docs/audit/task-B1-enroll-timetable-gap.md:82`、`docs/plans/fee-categories-design.md:138`）。工时 **0.1 人日**（校方拍板）。

### 4.8 B15 上传文件字节（filestore）—— **部分自动恢复：157/710 已回填，剩余 553 条无实体**

**一、已完成的部分（队长 2026-10-01 执行，本次已独立复现）**

| 口径 | 数字 | 说明 |
|---|---|---|
| 8/30 快照里 `ir_attachment.store_fname` 非空 | **710 行**（540 个唯一 blob） | 由本机 8/30 dump 用 `pg_restore -a -t ir_attachment` 抽出，**不还原库** |
| 其中**本机 Mac filestore 命中** | **157 行**（**91 个唯一文件**） | 本机 `data/web/filestore/edu19` 共 192 个文件 |
| 已上传到新机 | `/opt/edu-app/data/web/filestore/edu19`，`chown 100:101`；新机 filestore 文件数 **91 → 265** | 265 = 91 抢救件 + 174 运行期生成 |
| 抢救到的主要内容 | **校徽 logo**（png/webp/jpg 共 7 个）、**公司 logo**、**乌鸦.jpeg**（discuss.channel）、**~15 个 `res.partner` 头像变体**、38 个 `ir.ui.menu` 图标、45 个 gamification 徽章、25 个 karma 等级、10 个 `hr.employee` 头像、6 个 dashboard、5 个 website、4 个 chatbot、3 个 res.lang | 逐模型对账见 evidence |

**二、口径差必须写清（`157 行 / 91 唯一`）**

> filestore 是**内容寻址**的：`store_fname` = 内容的 sha1（路径自带两级目录），**多条 `ir_attachment` 行可以指向同一个 blob**。
> 所以「157」是**行数**（有多少条挂接的字节还在）、「91」是**唯一文件数**（实际搬了几个 blob）。两者不是矛盾，是两种口径。

**三、本次在新机实测（2026-10-01 13:50:50Z）**

| 指标 | 值 |
|---|---|
| filestore 文件数 | **265** |
| `ir_attachment` 中 `store_fname` 非空 | **709 行**（539 个唯一 blob） |
| 其中**字节在新机 filestore 里** | **186 行 / 98 个唯一文件** |
| **`edu*` / `op.*` 业务附件** | **0 行** |

> 186 > 157 的原因：**升级/启动时 Odoo 又生成了新的附件**（编译资产、视图图片等）并写入 filestore ⇒ 「现在存在」≠「抢救来的」。**157/91 是抢救口径的权威数字**（以 8/30 快照的 710 行为分母）。

**四、逐模型对账（新机实测，`hit/total`）**

| res_model | 命中/总数 | 说明 |
|---|---|---|
| `payment.method` | **0 / 462** | 平台图标，**整批缺失**（payment 模块数据，非校方资料） |
| `gamification.badge` | 45 / 45 | 徽章图标，全在 |
| `ir.ui.menu` | 38 / 38 | 菜单图标，全在 |
| `ir.ui.view` | 17 / 37 | 视图图片，部分 |
| `res.partner` | 15 / 25 | 头像变体，部分 |
| `payment.provider` | **0 / 25** | 同 payment.method |
| `gamification.karma.rank` | 25 / 25 | 全在 |
| `ir.attachment` | 10 / 10 ｜ `hr.employee` 10 / 10 | 全在 |
| `spreadsheet.dashboard` / `website` / `onboarding.onboarding.step` / `chatbot.script` / `res.lang` | 6/6 · 5/5 · 5/5 · 4/4 · 3/3 | 全在 |
| `forum.forum` | **0 / 5** | 缺失 |
| `discuss.channel` | 1 / 1 | **乌鸦.jpeg** |

**五、结论（对「校方资料丢了多少」的直白回答）**

1. **8/30 快照里根本没有业务附件**（`edu*`/`op.*` 的 `ir_attachment` = **0 行**）⇒ 资料下载中心的上传件、报销收据、请假证明**都不是 8/30 之前产生的**；
2. 因此抢救回来的 157 行**全是平台资源与头像**，**没有一件是校方上传的资料**；
3. 09 月产生的业务上传件（若有）随旧机**永久丢失**，且**没有任何口径能算出到底有多少** ⇒ **必须请教务处回忆/盘点**（这是 B15 剩下那 553 条的真正含义）。

**六、可复跑命令（逐字）**

```bash
# ① 从 8/30 dump 抽 store_fname 列表（不还原库；任意 PG16 都行）
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY scp ~/Documents/edu19-backups/edu19_post_cleanup_0830.dump prod-host:/tmp/snap0830.dump
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY ssh prod-host \
  'docker cp /tmp/snap0830.dump edu19-prod-db-1:/tmp/snap0830.dump && \
   docker exec edu19-prod-db-1 pg_restore -a -t ir_attachment -f - /tmp/snap0830.dump > /tmp/att.tsv'
# ② 解析出 store_fname 列（脚本 /tmp/parse_att2.py 见 evidence 文件，逻辑：找 COPY 头定位列号 + 跳过 \\N）
#    结果：all=710  unique=540
# ③ 与本机 filestore 对拍（本机 Mac，路径 = filestore/edu19/<store_fname>，store_fname 自带 xx/ 前缀）
FS=data/web/filestore/edu19
while IFS= read -r f; do [ -n "$f" ] && [ -f "$FS/$f" ] && echo "$f"; done < /tmp/sf_dump_all.txt > /tmp/hits_from_dump.txt
wc -l < /tmp/hits_from_dump.txt          # 157（行口径）
sort -u /tmp/hits_from_dump.txt | wc -l  # 91（唯一文件口径）
# ④ 上传到新机并修属主
rsync -az --files-from=<(sed 's|^|/|' /tmp/hits_from_dump.txt) data/web/filestore/edu19/ prod-host:/opt/edu-app/data/web/filestore/edu19/
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY ssh prod-host 'chown -R 100:101 /opt/edu-app/data/web/filestore/edu19'
```

> **本次独立复现结果**：`all=710 / unique=540` → `rows_present=157 / unique_present=91`，与队长留的 `/tmp/hits.txt` **集合完全相同（diff = 0）**；见 `docs/audit/migration/evidence/2026-10-01-filestore-recovery.txt`。

> **剩下的 553 行**：`payment.method 462` + `payment.provider 25` + `forum.forum 5` + 其余零散（多为平台资源，Odoo 重装/重建时可再生成，**不是校方资料**）⇒ **无需人工找**；真正要人工确认的是「09 月上传的业务件」。


---

## 5. 丙类 —— 只能人工（5 条）

| # | 项 | 谁来做 | 要什么输入 | 大概多久（估算） |
|---|---|---|---|---|
| B1 | **账号**（见 §6） | 管理员/教务 | 学生名册（姓名+邮箱） | **1–2 人日 + 逐人通知** |
| B3 | 学籍档案 `op.student.course` + 分班 | 教务 | 每个学生的「课程 + 班级 + 学号」 | 0.5–1 人日 |
| B4 | 报课单与明细 | 学生本人（或教务代录） | 要选的科目 | 0.2 人日 |
| B10 | 站内信与已读状态 | —— | —— | **建议放弃**（内容是通知，不是档案） |
| B11 | `edu_audit_log` 操作审计 | **没人能补** | —— | **不可重建** |

> **实测注**：新机 `op_student_course` = **0** ⇒ 王佐的学籍档案也没了（旧机是 09-06 才建的，见台账 T5）；`edu_audit_log` = **0** 行 ⇒ 新机上没有可继承的留痕。

---

## 6. 账号重建（专节；已按实测改写）

### 6.1 实测现状（N5 闭环，2026-10-01）

| id | login | active | share | 有口令 | 组 |
|---|---|---|---|---|---|
| 1 | `__system__` | f | f | f | 17 |
| **2** | **`admin`** | **t** | f | t | 37 |
| 3 | `public` | f | t | t | 1 |
| 4 | `portaltemplate` | f | t | f | 1 |
| 5 | `parentportaltemplate` | f | t | f | 1 |
| **12** | **`backoffice@local`**（教务专员） | **f** | f | t | **角色/用户 + 经理 + 后台·完整视图** |
| **18** | **`jiaowu@local`**（教务二号） | **f** | f | t | **同上 3 组** |
| **19** | **`qnj2510798178@gmail.com`（王佐）** | **t** | **t** | t | 角色/门户网站 |

⇒ **只有 admin 与王佐是活的**（与队长通报一致）；**教职工账号不用新建**：`backoffice` / `jiaowu` 两行都在、口令哈希也在、组也对，**只差 `active=t` + 口令**。

### 6.2 学生账号清单从哪来（**唯一硬阻塞**）

| 来源 | 有什么 | 证据 |
|---|---|---|
| 王佐 | 姓名 + 邮箱 `qnj2510798178@gmail.com`（uid 19，已在库，**不要重建**） | `docs/audit/task-B1-enroll-timetable-gap.md:25,34` |
| `/alumni` 匿名泄露 | **12 个真名**：王佐、花木、余晖、艾志恒、泫、赵军、王院宇、李直、陈雨声、汤沅沅、李宣雨、罗中政 —— **只有姓名，没有邮箱** | `docs/audit/security-audit-app.md:501` |
| 旧台账/设计里的学号-姓名对 | 如 `24A0025 万橙` / `26A0019 罗中政` / `24B0045` | `docs/research/gradebook-entry.md:885-891`、`docs/plans/README.md:112` |
| 邮箱总表 | **仓库里没有**（除王佐外 19~21 个学生邮箱一个都没有） | **未验证 / 缺失** ⇒ 必须先向校方要「姓名 + 邮箱」 |

### 6.3 方案 A（推荐）：批量建号 + 一次性口令 + 导出交割（脚本思路，未实现）

**输入** `users.csv`：`name,email,role,gr_no,course_code,batch_code`。**执行**：odoo shell（`docker exec -i … odoo shell` 由本机送入），骨架照 `scripts/create_teacher_account.py`。

```python
# scripts/ops/rebuild_users.py（建议落点；本文不实现）
import csv, secrets, io
env = env
Users, Partner = env['res.users'].sudo(), env['res.partner'].sudo()
portal_gid  = env.ref('base.group_portal').id   # 学生 = 仅门户
student_gid = env.ref('base.group_user').id     # 教职工 = 内部用户
out = [['姓名', '登录名(邮箱)', '一次性口令']]
for r in csv.DictReader(open(USERS_CSV, encoding='utf-8')):
    email = (r['email'] or '').strip().lower()
    if not email:
        print('[skip] 无邮箱:', r['name']); continue
    p = Partner.search([('email', '=ilike', email)], limit=1) or Partner.create({'name': r['name'], 'email': email})
    u = Users.with_context(active_test=False).search([('login', '=', email)], limit=1)
    if u:
        print('[exist] 跳过（不改口令，除非 RESET=1）:', email)
    else:
        u = Users.create({'name': r['name'], 'login': email, 'partner_id': p.id,
                          'group_ids': [(6, 0, [student_gid if r['role'] == 'staff' else portal_gid])]})
        pwd = secrets.token_urlsafe(9)
        u.write({'password': pwd})        # 只写一次；明文只进导出文件
        out.append([r['name'], email, pwd])
    if not p.user_id:
        p.user_id = u.id                  # ⚠ 必须显式回填（res.users.create 不回填）
    elif p.user_id.id != u.id:
        print('[warn] partner.user_id 已被占用，跳过回填:', p.name)
env.cr.commit()                            # odoo shell 结束会回滚
with io.open(OUT, 'w', encoding='utf-8') as f: csv.writer(f).writerows(out)
```

**纪律（各有前车之鉴）**：① 按 `login` 幂等、不覆盖已有口令（`scripts/create_teacher_account.py:5`）；② 必须显式回填 `partner.user_id`，否则门户解析不到教师/学生（`create_teacher_account.py:16`，Odoo 19 的 `res.partner.user_id` 是「销售员」字段）；③ 已被占用则**跳过并告警**，不抢占；④ 一次性口令只导出一次、`chmod 600`、离线交割后删除（不要重蹈 0644 转储覆辙）；⑤ **王佐（id19）已在库，跳过**，只按需重设口令。

### 6.4 方案 B（备选）：邀请码自助注册

`edu.invite.code.batch` + `action_generate`（`custom_addons/edu_portal/models/invite_code.py:685`）批量生成层级码/绑人码，学生自助注册（教务不保管口令）；码经 Telegram 机器人或人工发放。**建议 A+B 混用**：已知邮箱走 A，联系不上走 B。

### 6.5 教职工：**不要新建，只需激活**

```sql
-- 一行激活（先备份）
UPDATE res_users SET active = true WHERE login IN ('backoffice@local','jiaowu@local');
```

激活后口令仍然未知（哈希不可逆）⇒ 由管理员在后台「修改密码」重设，或走 `scripts/` 的口令重设路径。`teacher@local`（旧机 uid 33）**不在**新库，需要时跑 `create_teacher_account.py` + `fix_teacher_user_backlink.py`（**新机 `/opt/edu-app/scripts/` 里都有**，幂等）。

---

## 7. 「今天就能跑」清单（新机实测路径）

```bash
# 0) 基线备份（任何写操作前）
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY ssh prod-host \
  'cd /opt/edu-app && docker compose exec -T db pg_dump -U odoo edu19 | gzip > /root/pre_rebuild_$(date +%Y%m%d_%H%M).gz && ls -l /root/pre_rebuild_*.gz'

# 1) B5 预检（本机离线）
python3 timetable_import/import_sessions.py --dry-run

# 2) B5 落库（脚本与 CSV 都从本机送入；SESSIONS_CSV 经 env 注入）
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY ssh prod-host \
  "SESSIONS_CSV=\"$(cat timetable_import/sessions.csv)\" \
   docker exec -i -e SESSIONS_CSV=\"$SESSIONS_CSV\" edu19-prod-web-1 \
   odoo shell -c /etc/odoo/odoo.conf -d edu19 --db_host=db -r odoo -w odoo --no-http" \
  < timetable_import/import_sessions.py
# 验收：op_session=216 / op_batch=17 / op_subject=32

# 3) B6 预检 + 落库（CSV 先进容器）
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY scp docs/curriculum/yongyue-curriculum.csv prod-host:/tmp/
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY ssh prod-host 'docker cp /tmp/yongyue-curriculum.csv edu19-prod-web-1:/tmp/'
#   预检（应打印 既有 32 / 已存在 9 / 新建 115）：
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY ssh prod-host \
  'docker exec -i -e CSV=/tmp/yongyue-curriculum.csv -e DRY_RUN=1 edu19-prod-web-1 \
   odoo shell -c /etc/odoo/odoo.conf -d edu19 --db_host=db -r odoo -w odoo --no-http' < scripts/import_curriculum.py
#   落库（去掉 -e DRY_RUN=1，其余相同）→ 验收：op_subject=147，edu_course_subject 预期 ≈320

# 4) B8 班级迁移（**不可逆**；B5 之后；先备份）
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY ssh prod-host \
  'docker exec -i edu19-prod-web-1 odoo shell -d edu19 -c /etc/odoo/odoo.conf \
   --no-http --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo' \
  < scripts/ops/retire_old_batches.py

# 5) C2 币种（脚本已在新机）
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY ssh prod-host \
  'docker exec -i edu19-prod-web-1 odoo shell -c /etc/odoo/odoo.conf -d edu19 --db_host=db -r odoo -w odoo --no-http' \
  < /opt/edu-app/scripts/switch_currency_cny.py

# 6) C1 品牌 + 导航（顺序不可反）
#    … < /opt/edu-app/scripts/setup_brand_yongyue.py
#    … < /opt/edu-app/scripts/seed_d1_nav.py

# 7) 教师占位（幂等）
#    … < /opt/edu-app/scripts/create_teacher_account.py
#    … < /opt/edu-app/scripts/fix_teacher_user_backlink.py

# 8) 账号批量重建（§6.3 的脚本，未实现）
#    … < scripts/ops/rebuild_users.py   （USERS_CSV / OUT 经 -e 注入）

# 9) 验证（不是重建）
python3 scripts/check_live_registry.py
#    tests/smoke/{enroll_timetable_gap_dryrun,major_track_elective,class_batch_mgmt}.py
```

> ⚠ **不要**在 `ssh 'bash -s' < script.sh` 里用 `docker exec -i`（§1.3 坑 1）；上面每条 `docker exec -i` 都是**顶层命令**，stdin 就是脚本/CSV，安全。


---

## 8. 证据自查（正向 / 反向注入 / 控制组）

**工具**：`docs/audit/migration/verify_plan_evidence.py`（**69 条锚点**：仓库脚本/文档 45 条 + 本次 evidence 三份 24 条，纯只读）

```console
$ python3 docs/audit/migration/verify_plan_evidence.py
PLAN_EVIDENCE PASS  69/69  (negative=False)
POS_EXIT=0

$ LEDGER_NEGATIVE=1 python3 docs/audit/migration/verify_plan_evidence.py   # 注入：第 46 条期望改成 'installed_v2'
FAIL docs/audit/migration/evidence/2026-10-01-newserver-readings.txt:22  expect='installed_v2'  got='edu_eval||uninstalled'
PLAN_EVIDENCE FAIL  pass=68/69  (negative=True)
NEG_EXIT=1
```

⇒ **正向 69/69；反向注入后恰好 1 条变红、其余 68 条（控制组）全绿**；注入只是进程内改字符串，**未写任何文件**。

> **两把尺子都跑一遍**（本台账 + 本清单）：
> - `verify_ledger_evidence.py` → `LEDGER_EVIDENCE PASS  50/50`；
> - `verify_plan_evidence.py` → `PLAN_EVIDENCE PASS  69/69`。
>
> **尺子的边界**：它证明「文件里确实写着这句话」；对 §1/§4.8 的**新机读数**，它所锚的是 `evidence/*.txt`（**原始输出的留档**），而不是新机本身。
> 要重新验证新机现状，请按 §1 的复跑形态重跑 SQL，并与 evidence 数字比对（附件计数会漂移，见 N13）。

---

## 9. 仍未验证 / 已闭环（本次更新）

### 9.1 ✅ 本次已闭环（原来标「未验证」的 6 条）

| # | 原问题 | 实测结论 | 证据 |
|---|---|---|---|
| N1 | 新机实际读数 | op_subject 14 / rel 14 / edu_course_subject 14 / op_session 0 / op_batch 1 / op_faculty 0 / op_timing 3 / op_student 1 / op_student_course 0 / op_course 6 / op_term 2 | evidence Q1 §3 |
| N2 | 19.0.3.0.0 是否已跑 | **已跑**（`edu_portal 19.0.4.0.0`；`edu_course_subject` 表在、14 行） | evidence Q1 §1-2 |
| N3 | 旧模块残留 | `edu_eval` **uninstalled + 0 残留**；`edu_telegram` installed；`edu_feedback` 不存在 | evidence Q1 §1/§5 |
| N5 | backoffice / jiaowu 的 active | **存在但 active=f**；组已是教务 3 组 ⇒ 只需激活 + 重设口令 | evidence Q1 §4 |
| N9 | 新机 filestore 现状 | **265 个文件**（91 抢救 + 运行时生成） | evidence §4.8 / filestore 文件 |
| N12 | 服务器布局/路径/容器名 | 见 §1.2（Ubuntu 26.04.1 / Docker 29.8.2 / Compose v5.5.1 / 容器名 / 挂载 / `/opt/edu-app/scripts`） | evidence / 布局输出 |

### 9.2 ❌ 仍然未验证（8 条）

| # | 未验证项 | 为什么 | 怎么解 |
|---|---|---|---|
| **N4** | **除王佐外的学生邮箱清单**（账号重建的**唯一硬阻塞**） | 仓库里没有；旧机没了 | **向校方要名册**（或从招生报名表导出） |
| N6 | 「21 个门户账号 vs 19 名学生」差 2 个是谁 | 旧库没了 ⇒ **已不可考** | 放弃核对，直接按新名册建 |
| N7 | `edu_course_subject` 334→478 的 +144 来源 | 旧库没了 ⇒ **已不可考** | 请教务在新库重标必修/选修 |
| N8 | 09-06 排课后教务是否手工改过课节 | 无留痕、旧库没了 | 问教务；重放后请教务过一遍计划 CSV |
| N10 | 序列起始号从哪开始 | 业务决定 | 校方拍板（现全为 `number_next=1`；锚点 SR0017 / REB000012） |
| N11 | 重放的 216 节课是否仍合**今天**的教务口径 | 排课口径可能已变 | 教务过一遍 `timetable_import/session_import_plan.csv` |
| N13 | 附件计数会漂移（每次 registry 加载/资产生成都会新增） | 实测 707→709、265→266 在小窗口内变动 | 报数**一律带时刻与分母**；抢救口径以 8/30 的 710 为分母 |
| N14 | `edu_nav` 守卫启动即报 ERROR（期望 357 / 参数实为 0） | 属 C9 未收口；未动 | 跑 `scripts/gen_menu_data.py --state=baseline` 后独立 `-u edu_nav` |
| N15 | 新机 `edu_application` / `edu.download.*` 等若干业务表行数 | 本次没测（不在 B 类关键路径） | `select count(*) from <表>` |
| N16 | 本机 filestore 里未被那 710 行引用的文件是什么 | 未逐条定性 | 与本地克隆自身附件对账 |
| **N17** | **`基础信仰` 重名**（`BTH-FOU01` 课表导入建 ↔ `PRP-C02` 快照既有）**是否同一门课** | **数据质量发现**：B5 引入该碰撞；CSV 自身 124 行 / 124 唯一名、无重复 | **教务确认**（不要脚本批量改名）；详见 §11.5 |

> N6/N7/N8 的状态从「未验证」升级为「**已不可考**」——不是因为查不到，而是**载体已经不存在**；这类问题只能由人（教务/校方）回答。

---

## 10. 交付物与本次未做的事

| 文件 | 内容 |
|---|---|
| `docs/audit/migration/rebuild-plan.md` | 本重建清单（甲 6 / 乙 8 / 丙 5 + 账号专节 + 实测基线） |
| `docs/audit/migration/verify_plan_evidence.py` | 证据回读器（69 锚点；`LEDGER_NEGATIVE=1` 反向注入） |
| `docs/audit/migration/evidence/2026-10-01-newserver-readings.txt` | 新机 Q1/Q3/Q4/Q5 原始输出（965 行） |
| `docs/audit/migration/evidence/2026-10-01-import-dryruns.txt` | 两次 DRY_RUN 原始输出 + 零写入对照（112 行） |
| `docs/audit/migration/evidence/2026-10-01-filestore-recovery.txt` | 附件抢救方法/数字/逐模型对账（143 行） |
| `docs/audit/migration/data-loss-ledger.md` | 上游损失台账（B 类 19 条判定） |
| `docs/audit/migration/verify_ledger_evidence.py` | 台账证据回读器（50 锚点） |
| `docs/audit/migration/appendix-commits-since-20260830.txt` | 事故窗口内全部提交 |

> **本次实际做过的（都是只读或本机操作）**：ssh 到新机跑只读 SQL、跑两次 DRY_RUN（**零写入**，已用前后对照证明）、从 8/30 dump 抽 `ir_attachment` 列表（`pg_restore -a -t`，**不还原库**）、本机 filestore 对拍、把 CSV/脚本经 stdin 送入容器。
> **写操作（全部经队长批准）**：B5 排课导入 + B6 课程导入（见 §11）；外加把 `scripts/import_curriculum.py` 的**读数**改成「行数 / 唯一名数 / 重名清单」（队长 2026-10-01 明确要求，**只动打印、不动判重与写入**，见 §11.4）。
> **没有做**：没有改 `custom_addons/**`、没有 `git commit`、没有碰 `评估表格/`、没有改新机任何配置（/etc、nginx、systemd 一律未动）；**B7/B8 未动**。
---

## 11. 执行记录（2026-10-01，队长批准后执行）

### 11.1 B5 排课导入 —— **已执行（真跑 1 次 + 幂等复跑 1 次）**

| 阶段 | 结果 | 证据 |
|---|---|---|
| 备份（跑前） | `edu19_prod-host_20261001T140947Z.dump`（10,663,234 B）｜**sha256 `032863b5…dfc208`**｜彩排 PASS（pg_restore rc=0、error 行 0、18 张关键表达标） | evidence `2026-10-01-b5-execution.txt` |
| dry-run（离线） | 16 批 + 1 占位教师 + 计划 216 行，与预期一致 | 同上 |
| 真跑 | `RUN_EXIT=0`、无 Traceback/CRITICAL；`op.session.create × 216（ids 330..545）`；占位教师 `op.faculty id=20 partner=65`；10 个 `op.timing`；`edu.audit.log` 已写 | 同上 |
| **前后对账** | `op_subject 14→32`（+18）｜`op_batch 1→17`（+16）｜`op_session 0→216`（ids 330..545, draft）｜`op_faculty 0→1`｜`op_timing 3→13`（+10）｜`edu_audit_log 0→1`｜`edu_course_subject 14→14`（B5 不产挂接） | 同上 |
| **幂等复跑** | 第 2 次真跑：`本次新建 0 · 幂等跳过 216 · 库内总 session 216`，无错误 | 同上 |

> **意外的正面吻合**：新机生成的课节 id 段是 **330..545**，占位教师是 **partner=65 / id=20** —— 与旧生产（`docs/deploy-malaysia.md「排课批量导入（2026-09-05）」节`）**逐位相同**。说明这条导入链是确定性的，重建结果可与历史对账。

### 11.2 B6 课程导入 —— **已执行（真跑 1 次 + 幂等 dry-run 1 次）**

| 项 | 实测 |
|---|---|
| 前置守卫（跑前） | `bash docs/audit/migration/precheck_b6.sh` → **POS_EXIT=0**（4 条断言全 PASS：installed / 19.0.4.0.0 ≥ 19.0.3.0.0 / 表存在 / 14 行 ≥14）；`PRECHECK_NEGATIVE=1` → **NEG_EXIT=1**，恰好 1 条 FAIL、其余 3 条控制组 PASS |
| dry-run（真跑前） | `行数 124 ｜ 既有科目 31 ｜ 课程 6 ｜ 新建 115 ｜ 已存在 9 ｜ 跳过 0 ｜ 断言 True ｜ 收尾 op_subject 32` |
| 与 plan 预期的差异 | plan 写「既有 32」，实测 **31**（**已查实为脚本按名去重的显示口径**，见下） |
| 根因（已查实） | `op_subject` **32 行 / 31 个唯一名** —— `基础信仰` 出现两次（`BTH-FOU01` 排课导入 + `PRP-C02` 快照既有）；脚本按名字 `setdefault` ⇒ 打印唯一名数。已存在 9 / 新建 115 与预期逐字相同 |
| **真跑** | `REAL_EXIT=0`，无 Traceback/CRITICAL；`新建 115 / 已存在 9 / 跳过 0`（与 dry-run 一致）；**`新增挂接 = 306`**；`已提交 env.cr.commit()` |
| **前后对账** | **`op_subject 32 → 147`** ✓（目标 147）；`op_course_op_subject_rel` 仍 **14**（老表未动）；**`edu_course_subject 14 → 320`** ✓（预期 ≈320 = 14 + 306） |
| 逐课程挂接（B6 后） | `CRS-BED 81 ｜ CRS-BLA 81 ｜ CRS-BTH 72 ｜ CRS-MCS 72 ｜ CRS-PRP 14 ｜ CRS-HSA 0`（合计 320） |
| `subject_type` | 320 行**全为 NULL** = 继承科目全局值（设计口径，教务零重配） |
| **幂等复跑** | 真跑后再跑 dry-run：**`新建 0 / 已存在 124 / 跳过 0`**，收尾 `op_subject 147` ✓ |
| B6 备份 | `edu19_prod-host_20261001T141110Z.dump`｜**sha256 `de01aa52…a1bb4`**｜彩排 PASS（跑前已备） |

> **与历史态的差异（算得清，不是异常）**：旧生产 09-14 的终态是 **334**（CRS-BED 88 / CRS-BTH 79 …）。差额 334 − 320 = **14** = 旧库导入前已有的 **24 条非 PRP 手工挂接** 减去其中 **10 条与本 CSV 撞车**（`docs/curriculum/import-report.md:57-63` 的算法）。本库快照里那 24 条不存在 ⇒ 320 才是本库的正确终态。

### 11.4 量具订正：`import_curriculum.py` 的「既有科目」读数（**先跑完 B6，再改量具**）

| 轮次 | 输出（原样） |
|---|---|
| **改前**（B6 真跑之前，2026-10-01T14:1xZ） | `[import] 行数 = 124 ｜ DRY_RUN = True ｜ 既有科目 = 31 ｜ 课程 = 6` ／ `新建 = 115 ｜ 已存在 = 9`／`收尾计数：op_subject = 32` |
| **改后**（B6 真跑之后，同一条命令） | `[import] 行数 = 124 ｜ DRY_RUN = True ｜ 既有科目 = 147 行 / 146 个唯一名 （重名: 基础信仰 x2） ｜ 课程 = 6` ／ `新建 = 0 ｜ 已存在 = 124`／`收尾计数：op_subject = 147` |

- 改动：`scripts/import_curriculum.py:33-45`（既有科目改为 `_all_subjects` 行数 + `smap` 唯一名数 + 重名清单）与 `:47-51` 的打印行。**只改读数，不改任何判重/写入逻辑**（`smap` 仍按名字，导入行为与改前逐字相同）。
- **为什么不能在改前跑**：那会变成「用改过的量具解释改之前的结论」。所以顺序是 **B6 真跑 → 改量具 → 重跑 dry-run**。
- ⚠ **「重跑 dry-run 应读 32」这一条无法逐字复现**：B6 真跑后 `op_subject` 已是 147，**32 那个基线已经不存在**（除非用 B6 前的备份 `T141110Z` 做 scratch 重放）。替代证据（同样有效）：
  1. 改前那一刻**直连 SQL**：`select count(*), count(distinct name) from op_subject` → **`32 | 31`**（本次实测，见 §11.5 的 MARKUNIQ 输出）；
  2. 改后格式**已在活库上实证**：`147 行 / 146 个唯一名 （重名: 基础信仰 x2）` —— 与 `32 行 / 31 个唯一名` **是同一个现象的同一量具**（差 1 的原因都是那一组重名）。

### 11.5 数据质量发现：重名科目（**要拿给教务确认，不擅自改名**）

| 问 | 答（实测） |
|---|---|
| ① CSV 里本来就是两行同名吗？ | **不是**。`docs/curriculum/yongyue-curriculum.csv` **124 行 / 124 个唯一名**，`基础信仰` 只出现 **1 次**（第 21 行：`基础信仰,2,必修,圣经与神学/导论课程,教育学士/文学学士+神学士/研究硕士`） |
| ② B5 新导入的 18 科里有没有引入新的重名对？ | **引入了 1 对**：`BTH-FOU01 基础信仰`（B5/课表导入建）与 `PRP-C02 基础信仰`（8/30 快照既有）重名。全库查重：**只有这一对**（`select name,count(*) ... having count(*)>1` → `基础信仰\|2\|BTH-FOU01,PRP-C02`） |
| 后果 | B6 导入时 `基础信仰` 被按**名字**判为「已存在」，于是**把 CSV 的挂接写到了 B5 建的 `BTH-FOU01` 上**（`op_course_op_subject_rel` 侧证据见 `MARKCROSS`：`BTH-FOU01 基础信仰 ↔ PRP-C02`）。两门课是不是同一门，**只有教务能判** |
| 建议 | ① 请教务确认 `PRP-C02`（预备科「基础信仰」）与 `BTH-FOU01`（神学系「基础信仰」）是否同一门；② 若不同 → 由**教务**改名（不要用脚本批量改，改名会连带影响报课/成绩口径）；③ 若相同 → 保留现状，并在课程目录里登记「一名两码」 |

### 11.6 B6 之后的未做项

- **B7 专业编排**：`edu_course_subject` 已达 **320**（改写 §3.3 的「预期 ≈320」为**实测值**）；教务后台手改的必修/选修仍未配（320 行 `subject_type` 全 NULL）。
- **B8 班级迁移**：仍未动（脚本不在新机；且「12 个 inactive 旧班 / 139 节」在本库不存在）。
- **C1/C2/C9**：仍未动（币种实测仍 USD）。
- **账号批量重建**：仍未动（等 N4 名单）。

### 11.3 未做（按指令或待放行）

- **B7 专业编排**：未动（等 B6 之后再评估 `edu_course_subject` 的最终行数）；
- **B8 班级迁移**：未动（脚本不在新机、且「12 个 inactive 旧班 / 139 节」在此库不存在）；
- **C1/C2/C9**：未动（币种仍 USD —— 实测）；
- **账号批量重建**：未动（等 N4 名单）。


