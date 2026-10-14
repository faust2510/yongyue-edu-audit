# 8/30 之后生产数据损失台账（仓库侧考古）

> **状态**：`审计报告`（非设计文档，不进 docs/plans/ 索引）
> **作者**：loss-ledger（Agent Teams 队员，共享任务 task-3）｜**日期**：2026-10-01
> **写作范围**：`docs/audit/migration/`（本目录）
> **不做**：把 Aug30 dump 还原进库的读数（归 backup-restore，落 `tests/smoke/` 与 `docs/ops/backup-policy.md`）；本文**没有**跑过任何还原。
> **证据纪律**：每条断言给出 commit / 文件:行 / 命令；仓库里查不到的一律标「未验证」并给取证命令，**不当结论用**。
> ⚠ **行号会漂**：本目录**外部**的 `文件:行` 引用在 2026-10-01 复核过；仓库规范本身要求「不要用行号引用（插入即漂）」，因此本文件已尽量把外部引用改写成「**文件 + 章节标题/特征串**」。两把尺子（`verify_plan_evidence.py` / `verify_ledger_evidence.py`）会在别人改动后**立刻报红**，请以它们的输出为准重新定位。


---

## 0. 一页结论（TL;DR）

1. **备份边界 = 2026-08-30 19:12 / 19:38 两份生产 pg_dump**（PostgreSQL custom 格式，**只含数据库，不含 filestore**）。本机两份副本与生产同名文件**字节数逐位吻合**（`edu19_post_cleanup_0830.dump` = 10,234,709 B，两处同值）⇒ 确认同源。
   - 生产侧清单与权限：`docs/audit/security-audit-infra.md:669-673`；filestore 不在 dump 内的口径：`docs/deploy-malaysia.md「服务器路径」表的 filestore 行`。
2. **生产在备份之后又活了整整 30 天**：最后可证活的时刻 = **2026-09-29 15:4x +08**（当天 16:15 +08 还在被读写），也就是说 **08-30 ~ 09-29 的全部数据库写入都不在本地两份 dump 里**。
   - `docs/audit/edu-eval-removal.md:114-124`、`:138-146`、`:440`。
3. **代码不是损失项**：`2026-08-31` 起共 **682 个提交**（全量清单见附录 `appendix-commits-since-20260830.txt`），含 4 个新模块、1 个模块删除、1 个模块退役。重新部署即可回来（A 类）。
4. **真正不可替代的只有两样**，且**两样都不在本地**：
   - **① 生产 filestore**（`/opt/edu-app/data/web/filestore`）= 所有上传文件的**字节**：资料下载中心的资料、报销收据、请假证明、头像、公告附件、以及 2026-09-28 本地化的 55 个字体附件。`pg_dump` **不含** filestore。
   - **② 生产机上的库转储**（`/opt/edu-app/backup`、`/opt/edu-app/backups`、`/root/edu19-backup`、`/root/*.gz`，审计时 124 MB / 35 个文件），**最新一份到 2026-09-29 15:45**（`/root/pre_deleval_20260929_1545.gz`，4,925,334 B）。它比本机 Aug30 dump 多出**几乎全部** 09 月数据。
5. **分类计数**：**A 类 12 条**（代码/结构，可恢复）｜**B 类 19 条**（数据，已丢失/需补录）｜**C 类 12 条**（配置与设置，需人工重设）。逐条见 §3 / §4 / §5。
6. **最痛的一条**：**学生登录账号（真人 + 邮箱即登录名）**。生产账号 09-18 实测 24 个 → 09-24 实测 38 个；学生档案 09-21 实测 20 条 → 09-24 实测 29 条；这些**账号密码（加盐哈希）与邮箱**丢了，学生**登不进来**，必须逐个重发邀请码/重设口令。

---

## 1. 口径与边界

### 1.1 「Aug30 之后」怎么划

| 项 | 值 | 证据 |
|---|---|---|
| 备份当日最后一提交 | `21afd64` 2026-08-30 22:18:49 +0800 | `git log -1 --before=2026-08-30T23:59:59` |
| 本台账纳入范围 | `2026-08-30 00:00 起`的全部提交（= 684 条；其中 682 条在 08-31 及以后） | 附录文件 |
| 备份文件生成时刻 | 08-30 19:12（before_cleanup）/ 19:38（post_cleanup） | `docs/audit/security-audit-infra.md:669,673` |
| 本机副本落盘时刻 | 08-30 19:38 / 19:39 | `ls -la ~/Documents/edu19-backups/` |

> ⚠ **边界不是「最后一提交」而是「最后一次 dump」**：08-30 19:38 之后生产仍在被写（例如 09-06 的排课导入）。判据必须以**库转储**为准，不能以 git 提交时刻为准。

### 1.2 两份本地 dump 的体检（只读；**不是还原**）

```console
$ file ~/Documents/edu19-backups/*.dump
edu19_local_dev_0830.dump:   PostgreSQL custom database dump - v1.15-0
edu19_post_cleanup_0830.dump: PostgreSQL custom database dump - v1.15-0
$ ls -la ~/Documents/edu19-backups/
-rw-r--r--  10690076 Aug 30 19:39 edu19_local_dev_0830.dump
-rw-r--r--  10234709 Aug 30 19:38 edu19_post_cleanup_0830.dump
```

> `file` 的类型判定 = **pg_dump custom 格式** ⇒ **只装数据库对象，不装 filestore 字节**。
> 交叉核对（关键）：生产 `/opt/edu-app/backup/edu19_post_cleanup_0830.dump` 的字节数 = **10234709**（`docs/audit/security-audit-infra.md:673`），与本机副本**逐位相同** ⇒ 本机这份就是生产 08-30 19:38 那一份。
> 反向可证伪：若本机副本其实是另一份（例如 local_dev 是本地库），则**用 `pg_restore -l` 列目录**应看到 `res_company.name` 等值的差异；本台账**未做**库级比对 ⇒ 该比对留给 backup-restore（红线：我不重复还原）。

### 1.3 生产机上还有更多 dump（**这是找回 09 月数据的第一顺位**）

| 文件（生产机） | 时刻 | 证据 |
|---|---|---|
| `/opt/edu-app/backups/edu19_pre_user_cleanup.dump` | 2026-08-25 18:08 | `docs/audit/edu-eval-removal.md:100` |
| `/opt/edu-app/backup/edu19_before_cleanup_0830.dump` | 2026-08-30 19:12 | `security-audit-infra.md:669` |
| `/opt/edu-app/backup/edu19_post_cleanup_0830.dump` | 2026-08-30 19:38 | `security-audit-infra.md:673` |
| `/opt/edu-app/backups/pre-migration-20260831-0009.dump` | 2026-08-31 00:09 | `security-audit-infra.md:683` |
| `/opt/edu-app/backup/edu19_before_enroll_v2.dump` | 2026-09-07 00:00 | `security-audit-infra.md:670` |
| `/opt/edu-app/backup/edu19_before_ledger.dump` | 2026-09-10 10:10 | `security-audit-infra.md:672` |
| `/opt/edu-app/backup/edu19_before_feedbackbot_20260910_1800.dump` | 2026-09-10 18:00 | `security-audit-infra.md:671` |
| `/root/edu19-backup/edu19-pre-deploy-20260914-1414.sql.gz` | 2026-09-14 14:14（课程清单导入 + 币种切换前） | `security-audit-infra.md:695`、`docs/plans/data-provenance.md:278` |
| `/root/edu19-backup/edu19-pre-bulkfix-20260917-0950.sql.gz` | 2026-09-17 09:50 | `security-audit-infra.md:694` |
| `/root/edu19-backup/edu19-pre-applyacl-20260917-1023.sql.gz` | 2026-09-17 10:23 | `security-audit-infra.md:693` |
| `/root/edu19-backup/edu19-pre-t16-20260917-1729.sql.gz` | 2026-09-17 17:29（审计时最新） | `security-audit-infra.md:696` |
| `/root/pre_majortrack_20260922.gz` | 2026-09-22（专业编排迁移前） | `docs/audit/edu-eval-removal.md:153` |
| `/root/pre_overview_20260924b.gz` | 2026-09-24 第 1 轮 | `scripts/ops/retire_old_batches.py:16` |
| `/root/pre_overview2_20260924.gz` | 2026-09-24 16:54 | `scripts/ops/retire_old_batches.py:17` |
| `/root/backup/edu19_before_slim.2026-09-24-174524.sql.gz` | 2026-09-24 17:45 | grep 命中（本仓 docs） |
| `/root/pre_font_20260928.gz` | 2026-09-28（字体本地化前） | grep 命中（本仓 docs） |
| **`/root/pre_deleval_20260929_1545.gz`** | **2026-09-29 15:45（最新；4,925,334 B，全库 plain SQL，714 表）** | `docs/audit/edu-eval-removal.md:138-159` |
| `/opt/edu-app/edu19-prod.dump` | 2026-09-18 审计时 9,494,692 B | `security-audit-infra.md:679-680` |

> **口径**：以上 35 个文件里 `/opt` 下的部分是 **0644 世界可读**（`security-audit-infra.md:684-687`：`find /opt /root ... -perm -o=r | wc -l` → 35；`du -ch` → 124M）。
> **可证伪**：若旧机拿得回，`ls -la /root/*.gz /opt/edu-app/backup*/ /root/edu19-backup/` 应能逐条对上；对不上说明清单有误（本表全部来自仓库文档，**不是**本次实测——本机现在连不上旧机）。

### 1.4 生产活到什么时候（= 损失窗口的右端）

| 时刻（+08） | 事件 | 证据 |
|---|---|---|
| 2026-09-29 04:30 | 生产跑过一次 `-u edu_eval` 升级（导致菜单 597 被重放回 active） | `docs/audit/edu-eval-removal.md:123` |
| 2026-09-29 13:26:47Z（=21:26:47） | 部署脚本自证：升级 rc=0 | commit `9461d90` 正文 §1 |
| 2026-09-29 13:27:05Z | web 容器 StartedAt（升级后重启生效） | 同上 |
| 2026-09-29 15:45 | 生产全库 pg_dump `pre_deleval_20260929_1545.gz` | `docs/audit/edu-eval-removal.md:142` |
| 2026-09-29 15:4x | 生产 `edu_eval` 三表 0 行只读读数 | 同上 `:63` |
| 2026-09-29 16:15 | 生产 `/eval/*` 五条全 404（卸载已生效） | 同上 `:440` |
| 2026-09-29 16:03 | 生产被改为定点补丁（`/root/deleval_20260929_160331/*.before`） | 同上 `:272` |

> ⇒ **损失窗口 ≈ 2026-08-30 19:38 → 2026-09-29 16:15**（约 30 天）。
> ⚠ 生产**跑的是工作区（未提交）代码**：`9461d90` 正文 §5-③ 记「实测 5 个文件生产 md5 == 工作区 md5 != HEAD」⇒ **代码恢复不能只 `git checkout HEAD`**，必须核对工作区版本。这条对 A 类同样致命。

---


## 2. 目标状态（「今天这个状态」应有哪些读数）

### 2.1 生产实测读数（带采集时刻；全部来自仓库文档的只读探针）

| # | 事实 | 生产读数 | 采集时刻 | 证据（文件:行） |
|---|---|---|---|---|
| T1 | 行政班（`op_batch`） | **12** 个：A1/A2/A3/B1/B2/B3/B4/C·A硕/C·B硕/预科/二级本科/**总览班** | 2026-09-24 | `docs/research/gradebook-entry.md:123` |
| T2 | 课节（`op_session`） | **216** | 2026-09-24 | `docs/research/gradebook-entry.md:124` |
| T3 | 「总览班」课时 | batch **34**（OVERVIEW 总览班）= **139** 节 | 2026-09-24 | `docs/research/gradebook-entry.md:124`（`34(139)`） |
| T4 | uid=19 = 王佐 | `op.student` **11** / `res.partner` **64** / `res.users` **19** / login `qnj2510798178@gmail.com` / 仅 `base.group_portal` | 2026-09-18 | `docs/audit/task-B1-enroll-timetable-gap.md:25,34` |
| T5 | 王佐学籍档案 | `op.student.course` **13**（course16 教育学士 / batch13 人文一年级 / running / roll `BED2026-WZ001`），**create_date 2026-09-06 13:33:31** | 2026-09-18 | `docs/audit/task-B1-enroll-timetable-gap.md:26,38` |
| T6 | 报课单 | `op.subject.registration` 唯一 1 行：id **19**/`SR0017`/`submitted`/21 门必修；**create_date 2026-09-17 06:53:54** | 2026-09-24 | `docs/research/gradebook-entry.md:864-866`、`docs/audit/task-B1-enroll-timetable-gap.md:42,82` |
| T7 | 科目 | `op_subject` **147**（compulsory 25 / elective 122） | 2026-09-22 期望 / 09-24 实测 | `docs/plans/major-track-elective-design.md:631-632`、`docs/research/gradebook-entry.md:122` |
| T8 | 课程↔科目挂接 | `op_course_op_subject_rel` **334**（CRS-BED 88 / CRS-BLA 81 / CRS-BTH 79 / CRS-MCS 72 / CRS-PRP 14） | 2026-09-14 起 | `docs/curriculum/import-report.md:31,37`、`docs/plans/major-track-elective-design.md:627-630` |
| T9 | 学生 | `op_student` **29**（其中 **5 名**【待分配】无学籍档案） | 2026-09-24 | `docs/research/gradebook-entry.md:119-120` |
| T10 | 学籍档案 | `op_student_course` **24** | 2026-09-24 | `docs/research/gradebook-entry.md:120` |
| T11 | 账号总数 | `res.users` **38**（其中 `users_with_totp = 0`） | 2026-09-24 | `docs/plans/password-verbatim-audit.md:53` |
| T12 | 启用账号 | **24** = 21 门户（**全是学生**，login 就是学生本人邮箱）+ 3 内部（admin / backoffice@local / jiaowu@local） | 2026-09-18 | `docs/audit/security-audit-app.md:743`、`:443` |
| T13 | 真实学生数 | **19** 名（真实姓名与邮箱已确认存在）；`/alumni` 匿名可列出其中 12 名 | 2026-09-18 | `docs/audit/security-audit-app.md:448,500-503` |
| T14 | 教师 | `op_faculty` **1** 行（id=20「待定」，`active=false`），**216 节课全挂在它名下** | 2026-09-24 | `docs/research/gradebook-entry.md:118` |
| T15 | 成绩/考试 | `op_exam` **0** / `op_exam_session` **1**（draft，挂总览班）/ `op_marksheet_line` **0** / `op_result_line` **0** / `op_grade_configuration` **7** | 2026-09-24 | `docs/research/gradebook-entry.md:106-127` |
| T16 | 考勤 | `op_attendance_sheet` **0** / `op_attendance_line` **0** | 2026-09-18~21 | `docs/plans/course-representative-design.md:703`、`docs/plans/class-change-request-design.md:826` |
| T17 | 评估（新引擎） | `edu_assess_*` 7 张表 **全 0 行** | 2026-09-24 | `docs/research/gradebook-entry.md:129` |
| T18 | 评估（旧两套） | 本地/生产三表 0/0/0；B 套于 09-29 卸载 | 2026-09-29 | `docs/audit/edu-eval-removal.md:15,66-71` |
| T19 | 请假 | `edu_leave` **1 行**（`leave_type=sick`） | 2026-09-19 | `docs/plans/course-representative-design.md:698` |
| T20 | 站内信 | `edu_message` **5 行** | 2026-09-21 | `docs/plans/course-representative-design.md:703` |
| T21 | 财务 | `edu_fee_bill` **2 行**；台账含「接待 ¥850」（09-16 转报销单 `REB000012`） | 2026-09-16 | `docs/plans/fee-categories-design.md:70,138` |
| T22 | 班级数据迁移 | 12 个 inactive 旧班退役、课程并入新建「总览班」；`op_batch` 19→12 | 2026-09-24 | `scripts/ops/retire_old_batches.py:2,20-21` |
| T23 | 菜单 | 生产 **515** 条菜单 / 19 个 active 根（卸载 B 套后 511） | 2026-09-29 | `docs/audit/edu-eval-removal.md:328`、commit `d0ef5a2` 正文 |
| T24 | 配置 | 公司 永约学坊 / 币种 **CNY** / `mail.default.from` = `scrtsschool@gmail.com` | 2026-09-14 | `docs/plans/data-provenance.md:278-281`、`docs/audit/security-audit-app.md:685` |
| T25 | 域名 | `edu.example.org`（Cloudflare）+ `cn.edu.example.org`（中国直连） | 2026-09-24 | commit `9920abc`、`docs/deploy-malaysia.md「中国直连入口」实测段` |

### 2.2 ⚠ 队长口径里**仓库找不到独立证据**的两条（不当结论用）

| 口径（队长提供） | 仓库里最接近的读数 | 判定 |
|---|---|---|
| 「**45 条学生选课**」 | `op_student_course` **24**（09-24）｜`op_student_course_op_subject_rel` **2**（09-24）｜`op_subject_registration` **1**（09-18） | **未验证**（仓库无 45 这个数；口径可能是「学籍档案 + 报课明细」的不同定义，或来自 Aug30 dump 还原读数） |
| 「**本学期 10 节课**」 | 仓库只有：`op_session` 216 全量 / 王佐所在 batch 13「本周 1 条」（09-18） | **未验证**（仓库无「本学期 10 节课」的口径；疑为「本周」或「某班本学期」的子集） |

> **取证命令（谁都能复跑，拿到就能把这两条钉死或推翻）**：
> ```sql
> -- 45 条学生选课：分别数三种候选口径
> SELECT 'op_student_course' t, count(*) FROM op_student_course
> UNION ALL SELECT 'sc_subject_rel', count(*) FROM op_student_course_op_subject_rel
> UNION ALL SELECT 'subject_registration', count(*) FROM op_subject_registration;
> -- 本学期 10 节课：按当前学期窗口数
> SELECT count(*) FROM op_session s JOIN op_academic_term t ON t.id = s.academic_term_id
>  WHERE now() BETWEEN t.term_start_date AND t.term_end_date;
> ```
> ⚠ 本机现在**连不上旧机**，以上 SQL **未执行** ⇒ 标「未验证」。

---

## 3. A 类 —— 代码与结构（可恢复：在 git 里，重新部署即可回来）

> **判据**：改动只要在 git 可达（含工作区），且不携带「只存在于生产库的行」，就归 A。
> **总数**：**12 条**（A1–A12）。逐条提交见附录 `appendix-commits-since-20260830.txt`（690 行，含 682 条 08-31 后提交 + 边界锚点）。

### 3.1 模块级增删（4 新增 / 1 删除 / 1 退役）

| # | 模块 | 变更 | 入库证据 | 生产是否已生效 |
|---|---|---|---|---|
| A1 | `edu_assess` | **新增**（评估统一引擎）→ 09-28 第 2 期 → 09-29 上线 | `734ddd6`(09-18)、`19c8565`(09-28)、`8c6854d`(09-29) | ✅ 生产 `ir_module_module=edu_assess installed`（`docs/plans/README.md:136`）；09-29 升级 rc=0（`9461d90`） |
| A2 | `edu_nav` | **新增**（菜单收口落地处，`data/menu_consolidation_data.xml` 由生成器产出） | `2773ffe`/`c541ad8`/`5f0dfec` 等；模块目录 `custom_addons/edu_nav/` | ⚠ **只同步不升级**：rsync 列表已含，但**不进 `-u`**（`scripts/deploy_myedu.sh:156,183`、`9461d90` 正文 §2）⇒ 生产菜单是**半复原**状态（543 日常管理 / 576 在线课程 active=true） |
| A3 | `edu_tg_bind` | **新增**（Telegram 发注册码机器人） | `d46caec`(09-17)、`43c7c0b`(09-17) | ✅ 生产 md5 一致 + 活体注册表 LIVE（`docs/plans/README.md:151`） |
| A4 | `edu_zh` | **新增**（汉化/术语覆盖） | 09-14 首装（`docs/plans/ux-v3-delivery.md:588`） | ✅ `-i` 安装过；升级必须 `--i18n-overwrite` |
| A5 | `edu_eval` | **删除**（行政评估；用户授权「完全没有人用过」） | `d0ef5a2`(09-29)、证据 `docs/audit/edu-eval-removal.md` | ✅ 本地 + 生产均已卸载，三表 DROP |
| A6 | `edu_telegram` | v2.2 退役登记（doc-only） | `docs/audit/deprecated-inventory.md` §0.1/B8 | ❌ **生产实际仍 installed**（v19.0.3.2）——文档与生产不一致，见 `docs/audit/security-audit-app.md:690-692` |

### 3.2 大功能批次（A 类主体；按入库日期）

| # | 功能 | 入库 | 代表提交 | 生产生效判据 |
|---|---|---|---|---|
| A7 | 排课批量导入（216 节 + 18 科 + 16 班 + 10 timing + 1 占位教师） | 2026-09-06 | `644f543` | 生产 op_session 216（ids 330-545），`docs/deploy-malaysia.md「排课批量导入（2026-09-05）」节` |
| A8 | 学生自主报课 + 教务审批（enroll-v2 第 2 期） | 2026-09-06 | `dd5cabc`/`f06721b` | 生产部署记录 + md5 一致（`docs/plans/README.md:139`） |
| A9 | 财务总账 + 报销（第三期） | 2026-09-10 | `f4e546e` 等 | 生产 23/23 冒烟 PASS（`docs/deploy-malaysia.md「生产冒烟（23/23 PASS）」节`） |
| A10 | v3 去 Odoo 化 + 学坊本土化（术语/币种/公开页） | 2026-09-12 | `448d8b4`/`7b43a49` | 生产 09-14 部署完成（`ux-v3-delivery.md:588`） |
| A11 | 权限四层 + 菜单收口 + 邀请码分层 + 课代表 + 专业编排 + 请假分级 + 班级管理/调班 + 改课影响面 + 门户入口合一 | 2026-09-17 ~ 09-24 | `d2c41de`/`e2739ce`/`149cab8`/`d1a37f8`/`2fe14e9`/`5bf346d`/`9b8509d`/`1ec787f` 等 | `docs/plans/README.md:81-100` 逐条判据；⚠ 09-18 入库的班级管理**要等 09-24 22:29 重启才在活体进程生效**（同表 `:104-106,144`） |
| A12 | 09-28/29 批次：字体本地化 + 评估 v2 + 教务成绩录入 + 课程编排批量 + 站内搜索 + 无障碍第二批 + 部署自证 | 2026-09-28/29 | `970a44c`/`19c8565`/`8c6854d`/`154d2f9`/`91448a4`/`9461d90` | 09-29 生产升级 rc=0 + web 重启自证 + 冒烟 5+5 绿（`9461d90` 正文 §1） |

### 3.3 A 类的「可恢复」不是无条件的（三条硬约束）

1. **生产跑的是工作区版本**：`9461d90` 正文 §5-③ 实测「5 个文件生产 md5 == 工作区 md5 != HEAD」⇒ 恢复时必须**同时**核对工作区；只 `git checkout HEAD` 会丢一部分新代码。
2. **`edu_nav` 的数据文件改动不会上生产**（`9461d90` 正文 §2-③；`docs/audit/menu-consolidation/deploy-shipping-gap.md`）⇒ 菜单收口的最终形态**要重新生成数据文件 + 单独排一次 `-u edu_nav`**。
3. **A 类里混着生产库行**：`edu_nav` 的 `ir.config_parameter edu_nav.consolidated_count`、菜单 active 状态、`edu_life` 到堂类型（`scripts/merge_checkins.py` get-or-create）**都不在模块 data 里**，属 C 类/需重跑脚本。参见 A2、C10。


---

## 4. B 类 —— 数据（**已丢失**，需要补录或需要旧机恢复）

> **判据**：任何**只存在于生产库/生产文件系统**、且生成时刻 **晚于 2026-08-30 19:38** 的业务行或文件字节，归 B。
> **总数**：**19 条**（B1–B19）。工时均为**估算**（标「估算」），依据见每条。
> **先看结论**：真正痛的是 **B1（学生登录）**、**B2/B3（学生与学籍）**、**B5（排课）**、**B15（上传文件）**。

### 4.0 B 类速览（按「痛感」排序）

| 序 | 项 | 生产读数（时刻） | 可自动重放？ | 补录工时（估算） |
|---|---|---|---|---|
| B1 | 学生/教务登录账号（含口令哈希） | 38 账号（09-24）/21 门户（09-18） | ❌ | 1–2 人日 + 逐人通知 |
| B2 | 学生主档 `op.student` / `res.partner` | 29（09-24）；09-21 时 20 | ⚠ 部分（名册在文书里） | 0.5–1 人日 |
| B3 | 学籍档案 `op.student.course` + 分班 | 24（09-24）；09-18 时 1 | ❌ | 0.5–1 人日 |
| B4 | 报课单与明细（`SR0017`） | 1 单 / 21 必修（09-24） | ❌ | 0.2 人日（重报） |
| B5 | 排课 216 节 + 18 科/16 班/10 timing/1 教师 | 216（09-24） | ✅ **可重放**（CSV 在仓库） | 0.2 人日 |
| B6 | 课程清单 115 科 + 296 挂接 | 147 / 334（09-14 起） | ✅ **可重放** | 0.2 人日 |
| B7 | 专业编排必修/选修 | `edu_course_subject` 334(09-22) / 478(09-24) | ⚠ 迁移可重放，**后台手改不可** | 0.5 人日 |
| B8 | 班级迁移结果（总览班） | 12 班 / 139 节（09-24） | ✅ 脚本可重放 | 0.2 人日 |
| B9 | 请假/申诉/审批留痕 | `edu_leave` 1（09-19） | ❌ | 0.1 人日 |
| B10 | 站内信与通知偏好 | `edu_message` 5（09-21） | ❌ | 可放弃（估算 0） |
| B11 | 操作审计 `edu_audit_log` | 生产未查（本地 2250） | ❌ | **不可补**（留痕不可重建） |
| B12 | 财务账单/总账/报销 | 账单 2 行、`REB000012`（09-16） | ⚠ 部分（订正脚本可重跑） | 0.2–0.5 人日 |
| B13 | 评估数据 | **全 0**（09-24/29） | — 无数据可丢 | 0（旧模板定义重建 0.5 人日） |
| B14 | 打卡/周记/积分 | 生产未查 | ❌ | 未知 |
| B15 | 上传文件字节（filestore） | 未查（**pg_dump 不含**） | ❌ **不可重放** | 取决于资料量 |
| B16 | 字体本地化附件 | 55 条（09-28） | ⚠ 脚本可重跑（需连 Google） | 0.2 人日 |
| B17 | 报名申请 | 备份内 2（王茜茜）；09 月新增未查 | ❌ | 0.2 人日 |
| B18 | 邀请码 | 生产未查 | ❌ | 0.2 人日 |
| B19 | 单号序列（SR/REB/CERT） | 生产未查 | ❌（`last_value` 不可从行数反推） | 0.1 人日（需定起始号） |

### 4.1 逐条明细

#### B1 学生 / 教务的登录账号与口令 —— **最痛**

| 项 | 内容 |
|---|---|
| 生产读数 | 09-18：**24 个启用账号** = 21 门户（`share=True`，**全是学生**，login 就是学生本人邮箱）+ 3 内部（admin / backoffice@local / jiaowu@local）；09-24：**38 个账号**、`users_with_totp=0` |
| 证据 | `docs/audit/security-audit-app.md:743,443,448`；`docs/plans/password-verbatim-audit.md:53`；`docs/audit/task-B1-enroll-timetable-gap.md:25,34`（王佐 uid=19 的行读法） |
| 为什么丢 | 账号行（含 `res.users.password` 加盐哈希、`login`、`partner_id`、组关系、`signup_token`）全在 DB；08-30 dump 里没有 09 月新增的账号 |
| **谁能补** | 教务 / 管理员（后台「设置→用户」或邀请码体系）；口令只能**重设**，不能还原（哈希） |
| **怎么补** | ① 用 `docs/audit/security-audit-app.md:500-503` 里那 12 个真实姓名 + 各自邮箱，逐个在后台建账号并绑 `op.student`；② 或走邀请码（`edu.invite.code`）让学生自助注册；③ ⚠ **邮件通道未配**（`ir.mail_server` 0 行，`docs/plans/README.md:114`）⇒ 「发送重置密码邮件」**发不出去**，只能人工发码/口头通知 |
| **大概多久（估算）** | 建 19–29 个账号 ≈ **1–2 人日**；逐个通知到位另计（视联络渠道，1–3 天） |
| 反向证伪 | 若 Aug30 dump 还原后 `res_users` 里已含 09 月学生邮箱，则本条不成立 ⇒ 用 `SELECT id,login,create_date FROM res_users ORDER BY id` 对账（**归 backup-restore**） |

#### B2 学生主档 `op.student` / `res.partner`

| 项 | 内容 |
|---|---|
| 生产读数 | `op_student` **29**（09-24），09-21 时 **20**；其中 **5 名**【待分配】（id 25/30/39/40/54）；另有名单「泫 / 王院宇 / 张恩雨 / 裴枝 / 文文 / 24B0045」6 名未分班 |
| 证据 | `docs/research/gradebook-entry.md:119-120`；`docs/plans/course-representative-design.md:703`；`docs/plans/README.md:112` |
| 为什么丢 | 09 月新增的学生档案与伙伴（姓名/邮箱/电话/头像）不在 dump |
| 谁能补 | 教务（`op.student` 后台 / 学生 CSV 两段式导入） |
| 怎么补 | 校方提供名册 → `scripts` 里的学生导入链（辅助增强包第 5 批「学生 CSV 两段式导入」）或后台手工建档；邮箱必须与登录名一致 |
| 大概多久（估算） | 29 人 **0.5–1 人日** |
| 未验证 | 09 月新增学生到底是 9 名（20→29）还是含更早的清理；需 dump 对账 |

#### B3 学籍档案 `op.student.course` + 分班结果

| 项 | 内容 |
|---|---|
| 生产读数 | 09-18：**1 行**（id 13 王佐）→ 09-24：**24 行**，**5 名学生无档案**；09-24 班级迁移后 12 班 |
| 证据 | `docs/plans/class-change-request-design.md:824,826`；`docs/research/gradebook-entry.md:120`；`scripts/ops/retire_old_batches.py:2` |
| 关键细节 | 王佐那行 `create_date = 2026-09-06 13:33:31`（**晚于 dump 两个半小时**，能确认「09 月新增」这个概念成立） |
| 谁能补 | 教务（门户「班级管理」或后台 `op.student.course`） |
| 怎么补 | 逐个学生挂「课程 + 班级 + 学期」；`roll_number`（学号，唯一真身 = `op.student.gr_no`）必须重给 |
| 大概多久（估算） | 24 行 **0.5–1 人日**（含 6 名未分班的确认） |

#### B4 报课单与明细

| 项 | 内容 |
|---|---|
| 生产读数 | `op.subject.registration` **1 行**（id19 `SR0017`，`submitted` 未审批）+ `subject_compulsory_rel` **21 行** + 选修 rel **0** |
| 证据 | `docs/research/gradebook-entry.md:864-866`；`docs/audit/task-B1-enroll-timetable-gap.md:92-101`（21 门科目逐条 id/名） |
| 谁能补 | 学生本人重报（`/subject/enroll`）或教务代录 |
| 怎么补 | 重新报课 → 教务审批（审批才会写 `op.student.course.subject_ids`） |
| 大概多久（估算） | **0.2 人日**（1 个学生） |

#### B5 排课数据（216 节课）

| 项 | 内容 |
|---|---|
| 生产读数 | `op_session` **216**（ids 330–545），覆盖 13 个批；其中 9 个合班批 **139** 节、A1/B1/B3/B4 **77** 节；全部 `state=draft` |
| 证据 | `docs/deploy-malaysia.md「排课批量导入（2026-09-05）」节`；`docs/plans/scheduling-overhaul-design.md:650`（§18.5 逐批表）；`timetable_import/PRODUCTION_CHECKLIST.md:71,89` |
| 为什么丢 | 导入发生在 **2026-09-06**（commit `644f543`），晚于 dump |
| **可自动重放** | ✅ `timetable_import/`（`parse_timetable.py` → `normalize_sessions.py` → `import_sessions.py`；权威源 `full_sources.csv`）幂等 |
| 怎么补 | 按 `timetable_import/PRODUCTION_CHECKLIST.md:37-64` 重跑；注意会**新建 18 科/16 班/10 timing/1 占位教师**，且 course 复用现有 |
| 大概多久（估算） | **0.2 人日**（含对拍 216 条） |
| ⚠ 不可重放的部分 | 教务导入后在后台对课节的**手工改动**（改时间/教师/教室）——仓库无记录，**未验证有没有** |

#### B6 课程清单（115 科 + 296 挂接）

| 项 | 内容 |
|---|---|
| 生产读数 | `op_subject` 32 → **147**（+115，`YY-` 前缀）；挂接 38 → **334**（+296）；教育学士池 13 → 88 |
| 证据 | `docs/curriculum/import-report.md:26-39`（生产执行 2026-09-14）；回滚 SQL 在同文件 `:42-50` |
| **可自动重放** | ✅ `scripts/import_curriculum.py` + `docs/curriculum/yongyue-curriculum.csv`（124 行，幂等；`DRY_RUN=1` 只报不写） |
| 怎么补 | 重跑导入器；**注意**：09-22 之后 `op_subject.subject_type` 已被改成 25 必修 / 122 选修，重跑前要先确认导入器的默认值口径（`docs/curriculum/import-report.md:1-25`） |
| 大概多久（估算） | **0.2 人日** |

#### B7 专业编排（学制 + 必修/选修）

| 项 | 内容 |
|---|---|
| 生产读数 | `edu_course_subject`：09-22 迁移预期 **334**；09-24 实测 **478**；`op_subject` 25 必修 / 122 选修 |
| 证据 | `docs/plans/major-track-elective-design.md:627-645`（V1.1 断言 = 334）；`docs/research/gradebook-entry.md:128`（478）；`docs/plans/README.md:92` |
| 可重放性 | ⚠ **两段**：① 迁移脚本（`d1a37f8` 的 334 行）可从 `op_course_op_subject_rel` 重放；② **教务在后台逐行设的「必修/选修」覆盖值**（V2.2 场景）**仓库无记录**，且 09-22→09-24 从 334 涨到 478 的 **144 行来源未验证**（可能是继承/默认值/手工配置） |
| 谁能补 | 教务（后台「专业 → Subjects 页」逐行设） |
| 怎么补 | 先重放迁移得 334，再请教务重新标必修/选修（若 478 里含手工配置） |
| 大概多久（估算） | 迁移 0.2 人日 + 教务重标 **0.5 人日**（144 行） |

#### B8 班级数据迁移结果（总览班 + 12 班退役）

| 项 | 内容 |
|---|---|
| 生产读数 | 12 个 inactive 旧班退役；新建 batch 34「总览班」`code=OVERVIEW`；139 节课的 `batch_id` 用 **raw SQL** 重挂 |
| 证据 | `scripts/ops/retire_old_batches.py:1-30`（头部写明「本文件即本轮实际执行的完整脚本」+ 生产备份路径）；`docs/audit/security-audit-infra.md` 不含此备份但脚本自陈 |
| **可自动重放** | ✅ 脚本在仓库、且带执行原始输出（同文件末尾） |
| 怎么补 | 在重放过 B5 之后重跑该脚本（顺序依赖：先有 op_session 216，才有 139 可重挂） |
| 大概多久（估算） | **0.2 人日** |

#### B9 请假 / 申诉 / 审批留痕

| 项 | 内容 |
|---|---|
| 生产读数 | `edu_leave` **1 行**（`leave_type=sick`，09-19 只读）；申诉/审批单生产读数**未查** |
| 证据 | `docs/plans/course-representative-design.md:698` |
| 谁能补 | 申请人重提 + 审批人重批（**审批留痕不可重建**） |
| 大概多久（估算） | **0.1 人日** |

#### B10 站内信与通知偏好

| 项 | 内容 |
|---|---|
| 生产读数 | `edu_message` **5 行**（09-21）；`edu.notify.pref` 生产读数**未查** |
| 证据 | `docs/plans/course-representative-design.md:703` |
| 判断 | **可放弃**（内容是通知，不是档案）；偏好可让学生重设 |
| 大概多久（估算） | **0**（不补） |

#### B11 操作审计 `edu_audit_log`

| 项 | 内容 |
|---|---|
| 生产读数 | **未查**（仓库只有本地 2250 行，`docs/audit/edu-eval-removal.md:53`） |
| 性质 | **留痕，不可重建**（谁在何时改了什么） |
| 谁能补 | **没人能补** |
| 取证命令 | `ssh prod-host 'docker exec edu19-prod-db-1 psql -U odoo -d edu19 -Atc "select count(*), max(create_date) from edu_audit_log"'`（现在连不上） |

#### B12 财务：账单 / 总账 / 报销

| 项 | 内容 |
|---|---|
| 生产读数 | `edu_fee_bill` **2 行**（09-16，币种已切 CNY）；台账含「**接待 ¥850**」→ 09-16 已转报销单 **`REB000012`**（方向=应付、分类=接待、`reimburse_ref` 自动取号、垫付人清空+备注「垫付人待补」） |
| 证据 | `docs/plans/fee-categories-design.md:70,115,138`；`docs/plans/README.md:79` |
| 可重放性 | ⚠ 两笔账单 + 那条总账的**内容在文档里有**（金额/方向/分类）；09-16 的订正脚本「四合一」也在仓库（commit 2026-09-16）⇒ **可手工重做** |
| 谁能补 | 教务（后台/门户记账） |
| 大概多久（估算） | **0.2–0.5 人日** |

#### B13 评估数据（**结论：没有真实数据可丢**）

| 项 | 内容 |
|---|---|
| 生产读数 | `edu_assess_*` 7 张表 **全 0**（09-24）；旧 B 套 `edu_admin_eval_*` 三表 0/0/0（09-29）；旧 A 套 **4 模板 / 13 评分项 / 1 任务 / 0 打分** |
| 证据 | `docs/research/gradebook-entry.md:129`；`docs/audit/edu-eval-removal.md:15-24,66-96`；`docs/plans/evaluation-rebuild-design.md:22,358` |
| 判断 | **B 类里唯一「不痛」的一项**：无业务数据；损失的只是 **A 套 4+13 行定义**，教务可在新引擎重建 |
| 大概多久（估算） | **0.5 人日**（若要重建定义） |

#### B14 打卡 / 周记 / 积分（`edu_life`）

| 项 | 内容 |
|---|---|
| 生产读数 | **未查**（仓库 53 条 / 4 类型是**本地** `edu19`，`docs/audit/checkin-merge-report.md:3` 明写「库：edu19（本地）」） |
| ⚠ 恢复陷阱 | `edu_life` 的演示加载器**不是幂等的**：每次 `-u edu_life` 会按滚动 7 天窗口再补一批演示打卡（证据 `docs/audit/checkin-merge-report.md:95-104`、`docs/audit/finding-F5-edulife-demo-injection.md`）⇒ **恢复后库里的打卡行可能混着【演示】数据**，判「有没有丢」之前必须先分辨来源 |
| 谁能补 | 学生重新打卡（**历史打卡不可重建**） |

#### B15 上传的文件字节（filestore） —— **只有旧机才有**

| 项 | 内容 |
|---|---|
| 为什么丢 | Odoo 的 Binary/附件**行在 DB、字节在 filestore**；`pg_dump` **不含 filestore**（`docs/deploy-malaysia.md「服务器路径」表的 filestore 行`：「附件/资产二进制（pg_dump 不含，需单独 rsync）」）⇒ 本机两份 `.dump` 是 PostgreSQL custom 格式（实测 `file`），**字节一个都没有** |
| 涉及面 | 资料下载中心的资料（`edu.download.file`）、报销收据、请假/申诉证明、学生头像、公告附件、以及 `res.field='image_1920'` 的头像附件 |
| 生产数量 | **未查**（审计只记了目录权限 `0755 世界可读`，`docs/audit/security-audit-infra.md:26`） |
| 谁能补 | 教务处 / 校方重新提供原件 —— **补的是「再上传一次」，不是「恢复」** |
| 大概多久（估算） | 取决于资料量；每份上传几分钟，**不可估**（生产数量未知） |
| 取证命令 | `ssh prod-host 'du -sh /opt/edu-app/data/web/filestore; find /opt/edu-app/data/web/filestore -type f \| wc -l'`（现在连不上） |

#### B16 字体本地化附件（55 条，2026-09-28）

| 项 | 内容 |
|---|---|
| 生产读数 | `ir_attachment name LIKE 'google-font%'` = **54** 个 woff2 + 1 个主 CSS（`Roboto (google-font)`，33,156 B）⇒ **55 条新建附件**；生产自己的 main CSS id = **1317** |
| 证据 | `docs/plans/google-fonts-localization-report.md:7-10,127-140`；`docs/plans/README.md:176` |
| 为什么说「几乎只有旧机才有」 | DB 行 + filestore 字节**都在生产**；仓库里**没有** woff2 文件（`find custom_addons -iname '*.woff2'` = 0） |
| 可重放 | ⚠ 脚本在报告 §7 里逐字给出（`/tmp/localize_fonts.py`），但要**从 Google 抓**（生产能出网；中国直连入口不能替代） |
| 大概多久（估算） | **0.2 人日** |

#### B17 报名申请（`/apply`）

| 项 | 内容 |
|---|---|
| 生产读数 | 08-30 基线条数：**2 条真实报名（王茜茜）**（那 2 条**在** dump 内）；09 月新增**未查** |
| 证据 | `docs/handoff-prompt.md:20` |
| 谁能补 | 申请人重填（表单是公开页 `/apply`）；原始答卷 `answer_json` **不可重建** |
| 大概多久（估算） | **0.2 人日**（通知重填） |

#### B18 邀请码（`edu.invite.code`）与待分配信号

| 项 | 内容 |
|---|---|
| 背景 | 邀请码分层（层级码/绑人码/多次码/批量生成）2026-09-17 上线（`e2739ce`）；Telegram 发码机器人 09-17 上线（`d46caec`）⇒ **09 月一定生成/消耗过码** |
| 生产读数 | **未查**（仓库无生产条数） |
| 谁能补 | 超管/教务重新批量生成；**已用掉的码不可恢复**（但码本身是一次性凭据，重发即可） |
| 大概多久（估算） | **0.2 人日** |

#### B19 单号序列与业务编号

| 项 | 内容 |
|---|---|
| 内容 | `op.subject.registration` 的 `SR%04d`、报销 `REB%06d`（`edu.reimburse.seq`）、证书 `EDU-CERT-%04d` 等序列的 `last_value` |
| 证据 | 序列定义：`docs/deploy-malaysia.md「清单纠偏」节`（`edu.reimburse.seq`）；`docs/research/gradebook-entry.md:908`（`edu.assess.roster` 同型「名单快照」讨论里点明「行的集合必须稳定」） |
| 为什么单列 | 序列值**无法从现存行数反推**（行被删过就会重号）；恢复时若不显式设定 `last_value`，新单会与历史单**重号** |
| 怎么补 | 恢复后逐个 check `SELECT last_value FROM <seq>` 并与文档里的最大单号对账（`SR0017` / `REB000012`） |
| 大概多久（估算） | **0.1 人日** |


---

## 5. C 类 —— 配置与设置（需人工重设）

> **判据**：不是「代码」（不在模块 XML 里声明）也不是「业务数据」（不是用户作业留下的行），而是**运行环境与站点设置**。
> **总数**：**12 条**（C1–C12）。

| # | 配置项 | 生产现值 / 目标 | 证据 | 重设方式 | 工时（估算） |
|---|---|---|---|---|---|
| C1 | 公司/主体信息 | `res.company(1)`：名称 **永约学坊**、邮箱 `scrtsschool@gmail.com`、电话 **置空**、logo/`image_1920` 换校徽；`website` 名称 + `default_lang_id = zh_CN` | `scripts/setup_brand_yongyue.py:70-91`；`docs/plans/data-provenance.md:127-131` | 重跑 `setup_brand_yongyue.py`（幂等） | 0.1 人日 |
| C2 | 币种 = **CNY** | `res.currency CNY active=true`、`res.company(1).currency_id = CNY`、存量账单币种 USD→CNY（**不换算数字**） | `docs/plans/data-provenance.md:278-281,293-309`；脚本 `scripts/switch_currency_cny.py` | 重跑脚本（幂等；坑：必须 `with_context(active_test=False)` 才搜得到未激活的 CNY） | 0.1 人日 |
| C3 | 业务类系统参数 | `edu.apply.deadline` / `edu.enroll.deadline` = **2026-10-01**；`edu.downloads.max_file_mb` / `edu.downloads.allowed_ext`；`timetable.is_faculty_constraint` 等 4 个冲突门控；`edu.zoom_url`；`edu.portal_hidden_cards`；`edu_nav.consolidated_count=357` | `custom_addons/edu_portal/data/timetable_params.xml:29-33`；`docs/plans/ux-v3-delivery.md:614`；`docs/audit/menu-consolidation/baseline-report.md:265` | 后台「设置」（`res.config.settings`）或 `ir.config_parameter` 逐项写 | 0.2 人日 |
| C4 | **密钥类**系统参数 | `database.secret`(36) / `edu_telegram.bot_token`(46) / `.webhook_secret`(32) / `.admin_key`(10，弱) / `edu_tg_bind.token`(46) / `.webhook_secret`(44) / `edu_feedback.fp_key`(32) / `.admin_chat_id`(10) / `mail.web_push_vapid_private_key`(43) / `edu_assess.anon_salt` | `docs/audit/security-audit-app.md:673-683`；`docs/plans/eval-materials-inventory.md:524` | **必须重新签发**（不是「恢复」）：Telegram BotFather 重发 token、webhook secret 重生成；`database.secret` 建议一并轮换 | 0.3 人日 |
| C5 | 邮件与摘要 | `mail.default.from = scrtsschool@gmail.com`；邮件模板/摘要/机器人显示名去品牌化（`brand_debrand_data.xml` 里 12+ 条 `<function>` 每次 `-u` 重放）；`digest_digest(1)` 每周摘要 | `custom_addons/edu_brand/data_brand/brand_debrand_data.xml:39-128`；`docs/plans/ux-v3-review-t4.md:67` | `-u edu_brand` 重放（幂等）；⚠ **外发 SMTP 仍未配**（`ir.mail_server` 0 行）⇒ 邮件只到「已生成」 | 0.1 人日（SMTP 另计） |
| C6 | 网站与域名 | `web.base.url = https://edu.example.org`（`freeze=True`）；`cn.edu.example.org` 中国直连入口；Cloudflare **橙云**必须保持（09-24 曾被置灰云导致主站断网 43 分钟）；nginx/haproxy 片段在 `docs/ops/*.conf` | `docs/deploy-malaysia.md「关键参数」节`；commit `9920abc`、`4aac1aa`、`fe5658f`（灰云事故与探活告警）；`docs/ops/nginx-edu-strcs.conf`、`docs/ops/edu-cn.conf` | 新机上重建 nginx/cloudflared + DNS 重指；⚠ **本次禁止动生产 DNS** | 0.5 人日 |
| C7 | 报名/报课截止 | 两参数默认 **2026-10-01**，且**后台可自助改**（menu 617 / action 773 / form 3597）；**只提示不拦截**（用户 09-14 裁定） | `docs/plans/ux-v3-delivery.md:614-615`；`custom_addons/edu_portal/models/registration.py:700-701,781-819` | 已含在 C3；单独列出是因为它是**用户拍过板的业务日期** | （并入 C3） |
| C8 | 费用分类 | 校长清单 12 项（统筹/房租/交通/活动/接待/补助/补贴/课时费/粮草/日常物品/奉献/礼物），含 `direction_hint`；存量账单 `category` → `category_id` 迁移 | `docs/plans/fee-categories-design.md:5,50-53,70`；`docs/research/fee-categories.md:223` | 重跑 `-u edu_portal`（迁移在 `migrations/19.0.2.0.0/`）；跑完断言 `category_id IS NULL = 0` | 0.2 人日 |
| C9 | 菜单收口状态 | 生产 **515** 条菜单/19 active 根（09-29 卸载 B 套后 511）；**已知半复原**：543 日常管理 / 576 在线课程 `active=true`（应为 false）；`edu_nav` 参数 = 357 | `9461d90` 正文 §2-③；`docs/audit/edu-eval-removal.md:328`；`docs/audit/menu-consolidation/deploy-shipping-gap.md` | 重跑 `scripts/gen_menu_data.py`（正确命令 `--state=baseline`）+ 独立 `-u edu_nav`；**别只改常量** | 0.3 人日 |
| C10 | 定时任务（`ir_cron`） | 课代表到期收口（每天 01:43）、公告定时、下载过期下架、每周摘要、课前提醒等 | `scripts/deploy_myedu.sh:20`（提到课代表 cron）；`docs/plans/downloads-ack-v3-design.md`（过期下架 cron） | 随模块 `-u` 重建；⚠ **站点探活每 5 分钟**（`/opt/edu-monitor/health.sh`）与 Telegram 告警是**服务器侧**，不在 Odoo 里 | 0.2 人日 |
| C11 | `edu_life`「到堂打卡」类型 | 类型行**不在模块 `data/` 里**，由 `scripts/merge_checkins.py` get-or-create（本机 id=5 是偶然值） | `docs/audit/checkin-merge-report.md:40-43`；`docs/audit/deprecated-inventory.md` | 恢复后**必须重跑** `scripts/merge_checkins.py`（幂等），否则「到堂」列/卡消失 | 0.1 人日 |
| C12 | 服务器 / Odoo 运行配置与凭据 | `admin_passwd`、PG 口令 `odoo`（4 字符）、`proxy_mode=True`、`workers`、`list_db=False`、`odoo.conf`（0644）、SSH/Tunnel 凭据 | `docs/deploy-malaysia.md「服务器路径」节`；`docs/audit/security-audit-infra.md:23-24,29,36` | 新机重建（**口令必须换强**：审计已把 4 字符 DB 口令与开 root 密码登录列为高危） | 0.3 人日 |

> **一句话**：C 类里只有 **C2/C3/C8/C9/C11** 是「重跑脚本能拿回」，其余（**C4 密钥、C6 域名与隧道**）是**必须重新签发/重配**的，且 C4 的旧 token 已经在 0644 世界可读的转储里躺过（`docs/audit/security-audit-infra.md:564`）⇒ **即使旧机回来也不该复用**。

---

## 6. 账号审计：admin 之外，**哪些是真实的人**

> 任务明确要求单独查清这一条 —— 因为账号一丢，学生的登录就没了。

### 6.1 结论（按「是不是真人」分类）

| 类别 | 账号 | 是真人？ | 证据 |
|---|---|---|---|
| Odoo 管理员 | `admin`（uid=2） | 共用管理账号，**不是某个人** | `docs/audit/security-audit-app.md:740-741`（`base.group_system` 生产只有 admin 一人；`__system__` 已停用） |
| **学生（真人）** | **王佐** = uid **19** / `qnj2510798178@gmail.com` / `op.student` 11 / partner 64；`base.group_portal` | ✅ **是**（用户本人，也是本项目负责人） | `docs/audit/task-B1-enroll-timetable-gap.md:25,34`；`docs/handoff-prompt.md:50`（「与用户（王佐）中文直接交流」） |
| **学生（真人，其余）** | 09-18 生产 **21 个门户账号**「全部是学生，login 就是学生本人邮箱」；**19 名学生真实姓名与邮箱已确认存在**；`/alumni` 匿名列出 12 个真名：**王佐、花木、余晖、艾志恒、泫、赵军、王院宇、李直、陈雨声、汤沅沅、李宣雨、罗中政** | ✅ **是**（login=本人邮箱即证据） | `docs/audit/security-audit-app.md:443,448,501-503,531,789` |
| **教务（真人）** | `backoffice@local`（**教务专员**，uid=12） | ✅ **是** —— 「@local 演示账号**但实为真实教务在用**」 | `docs/deploy-malaysia.md「全选修+登录修复+教务账号恢复（2026-09-07）」节`；`docs/ops/jiaowu-manual.md:126,194`；`docs/plans/ux-v3-delivery.md:574` |
| **教务（真人）** | `jiaowu@local`（**教务二号**） | ✅ **是** —— 同上；且**口令非 demo123（用户自设）** | `docs/deploy-malaysia.md「全选修+登录修复+教务账号恢复（2026-09-07）」节 / 「已知现象」节` |
| 教师占位 | `teacher@local`（uid=**33**） | ❌ **不是真人**：2026-09-14 由脚本建的**占位账号**，绑「待定」教师档案，用途=让 216 节课有人能看 | `docs/plans/ux-v3-delivery.md:575-577`（`scripts/create_teacher_account.py` + `fix_teacher_user_backlink.py`） |
| 未激活系统账号 | 生产 09-14 时另有 **4 个未激活的系统账号**（含 `__system__`） | ❌ 非真人 | `docs/plans/ux-v3-delivery.md:574`；`docs/audit/security-audit-app.md:741` |
| 本地演示账号（**不是生产**） | `stu@local` / `faculty@local` / `parent@local` / `fac@local` | ❌ 本地夹具 | `README.md:73`（「生产已删演示账号，仅留管理员与教务账号」）；`docs/code-map.md:386-390` |

### 6.2 账号增长的时间线（**外推 09 月新增账号**）

| 时刻 | 读数 | 证据 |
|---|---|---|
| 2026-09-14 | 生产 **8 个账号**：admin / backoffice@local / jiaowu@local / 王佐 + 4 未激活 | `docs/plans/ux-v3-delivery.md:574` |
| 2026-09-14 | 新建占位 `teacher@local`（uid 33） | 同上 `:575` |
| 2026-09-18 | **24 个启用**账号（21 门户 + 3 内部）；19 名学生 | `docs/audit/security-audit-app.md:743,448` |
| 2026-09-21 | `res_users` **29**（`op_student` 20） | `docs/plans/course-representative-design.md:703` |
| 2026-09-24 | `res_users` **38**（`op_student` 29）；`users_with_totp = 0` | `docs/plans/password-verbatim-audit.md:53`；`docs/research/gradebook-entry.md:119` |
| 2026-09-24 | 修复「邀请码注册后永远登不上」（注册口令被 core 的 `strip()` 吃掉） | commit `0784b4e`（「生产：邀请码注册后永远登不上」） |

> ⇒ **09-14 → 09-24 之间生产账号从 8 增到 38**（净 +30），其中绝大多数是**学生自助注册**（邀请码体系 09-17 上线）。
> ⇒ **这批账号的口令哈希与邮箱登录名是本次损失里最不可替代的一项**：口令只能重设，且**邮件通道未配**（无法自助找回）。

> ⚠ **两条必须写清的边界**：
> 1. `docs/handoff-prompt.md:15` 写「生产真实账号只有 admin 和一个教务邮箱账号（找我要）」—— 这是 **08-30 的旧口径**，与 09-14 起的实测（8 → 24 → 38）冲突 ⇒ **以带日期的实测为准**，旧口径只作历史。
> 2. 本地 `.dump` 里那个 `local_dev` 备份**不是**生产账号来源；`本地 29 名学生 / stu@local` 之类一律不当作生产事实。

---

## 7. 结论段（直白回答两个问题）

### 7.1 如果旧机拿不回来：重建到「今天这个状态」要做什么，最痛的是什么？

**要人工做的（按顺序）**：

1. **先起环境**（0.5 天）：新服务器 + PG16 + Odoo19 + 本项目 `custom_addons/`（11 个模块）+ `openeducat_erp/` 快照 + `config/odoo.conf`（C12）。
2. **再装代码**（0.5 天）：按 `scripts/deploy_myedu.sh` 的模块清单装；**注意生产跑的是工作区版本**（`9461d90` §5-③）⇒ 恢复后要跟工作区核 md5，不能只看 HEAD。
3. **然后重放数据**（1–2 天，脚本可跑）：排课 216 节（B5）→ 课程清单 147 科/334 挂接（B6）→ 班级迁移/总览班（B8）→ 专业编排迁移（B7）→ 费用分类迁移（C8）→ 到堂打卡类型（C11）。
4. **最后补人造数据**（2–4 天，**只能人工**）：29 名学生主档 + 24 条学籍档案 + **38 个账号**（B1/B2/B3）+ 分班 + 报课单 + 请假/财务等零星业务行（B4/B9/B12/B17/B18）。
5. **重设配置**（0.5 天，含重新签发）：公司/币种/截止日/费用分类/菜单收口（C1-C3/C7-C9）+ **重新签发所有密钥**（C4）+ 域名与隧道（C6）。

**最痛的（排序）**：

1. **学生登录没了** —— 38 个账号的口令是**哈希**，数学上不可逆；只能**逐个重设**再逐个通知，而**邮件通道还没配**（`ir.mail_server` 0 行）⇒ 只能人工发码。这是唯一一项「工作量随人数线性增长、且必须跟真人打交道」的补录。
2. **上传的资料文件没了** —— 资料下载中心的资料、报销收据、请假证明、头像：`pg_dump` 从来不含 filestore（`docs/deploy-malaysia.md「服务器路径」表的 filestore 行`），**本机两份 dump 里一个字节都没有**；只能让校方**重新提供原件**，而且没人知道到底丢了多少件（生产数量**未查**）。
3. **一学期的工作痕迹没了** —— `edu_audit_log`（审批/改分留痕）、历史打卡/周记、申诉与审批过程：**没有任何脚本能重建**。
4. **教务要重新确认一堆「推导值」** —— 例如 §18.5 的「合班批 → 组成年级」映射，文档明写「**推导值，供人工确认，不得当事实用**」（`docs/plans/scheduling-overhaul-design.md:650`）⇒ 重排课表前必须请教务/校长再过一遍。
5. **单号会重号** —— `SR`/`REB`/`CERT` 序列的 `last_value` 不在行里（B19），不显式设定就会与历史单号撞车。

### 7.2 如果旧机能拿回来（续费/快照）：**哪些只有旧机才有**？按不可替代性排序

| 序 | 只有旧机才有的东西 | 为什么本地永远补不回来 | 证据 |
|---|---|---|---|
| **1** | **生产 filestore 的全部字节**（`/opt/edu-app/data/web/filestore`） | 本机 dump 是 `pg_dump` custom 格式，**结构里没有二进制文件**；上传件（资料/收据/证明/头像/公告附件）没有第二个副本 | `docs/deploy-malaysia.md「服务器路径」表的 filestore 行`；`file` 实测（§1.2） |
| **2** | **生产机上的库转储**（35 个，最新 `/root/pre_deleval_20260929_1545.gz`，2026-09-29 15:45） | 它覆盖 08-30 → 09-29 的**几乎全部**数据库状态；本机只有 08-30 两份 ⇒ 拿回它 = **B 类里 90% 的库数据不用补录** | `docs/audit/security-audit-infra.md:684-696`；`docs/audit/edu-eval-removal.md:138-159` |
| **3** | **生产库本身（活的 edu19）** | 一切运行态：账号哈希、`edu_audit_log`、序列 `last_value`、`ir_cron`、`ir_config_parameter` 现值、菜单 active 实况 | 同 §1.4 的探针清单 |
| **4** | **生产 Odoo 附件表 + `ir_asset`**（55 条字体附件、`user_values.scss`、`ir_asset` 102 条） | 行在 DB、字节在 filestore；两者缺一不可（`docs/plans/google-fonts-localization-report.md:216-232`） | 同表 |
| **5** | **Cloudflare 隧道/DNS 的现存配置**（`edu-tunnel-v2`、橙云状态、`cn.` 子域） | 服务器侧凭据与隧道状态；本机只有 nginx/haproxy 片段（`docs/ops/*.conf`） | `3a1af4b`（隧道轮换记录）、`4aac1aa`（灰云事故） |
| **6** | **服务器侧运维资产**：`/opt/edu-monitor/health.sh` + cron、Telegram 告警、遗留 `edu-system` :8090、SSH 授权 | 不在仓库、不在 dump | `docs/audit/security-audit-infra.md:43-59,706` |

> **一句话**：**先抢救旧机（哪怕只拿回 `/root/*.gz` 和 filestore 目录），再谈重建**。
> 拿回「最新 dump + filestore」= 本次事故基本无损；只拿回 dump 不拿 filestore = 数据在、文件没了；两样都拿不回 = 必须走 §7.1 的人工补录。


---

## 8. 证据自查（正向 / 反向注入 / 控制组）

> 本仓纪律要求：**要断言「检查过」，就必须让「检查失败」能改变结论**。本文档的每条 `文件:行` 断言都由脚本机械回读。

**工具**：`docs/audit/migration/verify_ledger_evidence.py`（50 条锚点，纯只读，不写任何文件）

**正向（原样输出）**：

```console
$ python3 docs/audit/migration/verify_ledger_evidence.py
LEDGER_EVIDENCE PASS  50/50  (negative=False)
POS_EXIT=0
```

**反向注入 + 控制组（原样输出）**：把第 15 条锚点 `docs/research/gradebook-entry.md:124` 的期望子串从 `216` 改成 **`288`**（一个真实存在、但属于**本地库**的数），该轮**必须变红**；其余 49 条**仍必须全绿**（= 控制组）。

```console
$ LEDGER_NEGATIVE=1 python3 docs/audit/migration/verify_ledger_evidence.py
FAIL docs/research/gradebook-entry.md:124  expect='288'  got='| `op_session` | 216 | 只覆盖 5 个班：34(139)、15(40)、13(18)、20(15)、10(4) |'
LEDGER_EVIDENCE FAIL  pass=49/50  (negative=True)
NEG_EXIT=1
```

**还原**：反向只是**进程内改一个字符串**（`os.environ`），**没有写任何文件、没有改任何数据**；`POS_EXIT=0` 在注入前后两次都跑到（见上）。

**这次自查真的抓到了东西（不是走过场）**：第一版正向跑出 **47/50**，三条锚点行号漂了（`:500` 应为 `:501`、`:40` 应为 `:41`、`:21` 应为 `:17`）——已全部改为实测行号后才是 50/50。⇒ 证明这套尺子**能红**。

> ⚠ **这套尺子的边界（不要高估它）**：它只证明「文件里确实写着这句话」，**不证明这句话本身是真的**。
> 「这句话是不是真的」只能由原始探针证明（生产只读 SELECT / curl），而**旧机现在不可达 ⇒ 本轮无法重跑**。

---

## 9. 仍未验证的点（不得当结论用）

| # | 未验证项 | 为什么没验 | 取证命令（谁有条件谁跑） |
|---|---|---|---|
| U1 | 队长口径的「**45 条学生选课**」 | 仓库无此数；本机连不上旧机 | §2.2 的三段 UNION SQL |
| U2 | 队长口径的「**本学期 10 节课**」 | 仓库无此口径 | §2.2 的第二段 SQL |
| U3 | 生产 `edu_audit_log` 行数与时间跨度 | 生产不可达 | `select count(*), min(create_date), max(create_date) from edu_audit_log;` |
| U4 | 生产 filestore **文件数与总字节**（B15 的量级） | 生产不可达；且审计只记了权限 | `du -sh /opt/edu-app/data/web/filestore; find ... -type f \| wc -l` |
| U5 | 生产打卡/周记/积分行数（B14） | 同上；且本地读数不能外推 | `select count(*) from edu_checkin_record;` 等 |
| U6 | 生产邀请码条数（B18） | 同上 | `select count(*) from edu_invite_code;` |
| U7 | `edu_course_subject` **334 → 478**（+144）的来源 | 仓库只记录了两个时刻，没记中间操作 | 对比 `/root/pre_majortrack_20260922.gz` 与 09-24 读数 |
| U8 | 09-06 排课导入后，教务是否在后台**手工改过课节**（B5 的不可重放部分） | 无留痕可查 | 对比全量 dump 的 `op_session.write_date` 分布 |
| U9 | 本机两份 dump 与生产同名文件的**库级一致性**（我只比了字节数） | 归 backup-restore 的还原读数 | `pg_restore -l` 目录比对 |
| U10 | 「生产有 2 条真实报名（王茜茜）」之外，09 月新增报名数 | 生产不可达 | `select count(*), max(create_date) from edu_application;` |
| U11 | 生产菜单 active 实况与 `edu_nav.consolidated_count` 是否仍 357 | 生产不可达 | `select count(*) from ir_ui_menu; select value from ir_config_parameter where key='edu_nav.consolidated_count';` |
| U12 | A 类里「生产是否已加载 09-29 全部改动」的逐文件 md5 | 无生产访问 | `check_live_registry.py` + 逐文件 md5（部署脚本自证已给一次性证据，见 `9461d90`） |

> 上表 12 条**全部**因为同一个原因没验：**旧机 203.0.113.10 当前不可达，本机没有生产访问通道**。
> 这不是「我懒得查」，而是**环境事实上不允许**；每条都给了可复跑命令，拿到旧机即可逐条钉死。

---

## 10. 交付物

| 文件 | 内容 |
|---|---|
| `docs/audit/migration/data-loss-ledger.md` | 本台账（A/B/C 三类 + 账号审计 + 结论 + 证据自查 + 未验证清单） |
| `docs/audit/migration/verify_ledger_evidence.py` | 证据回读器（50 锚点；`LEDGER_NEGATIVE=1` = 反向注入模式） |
| `docs/audit/migration/appendix-commits-since-20260830.txt` | 2026-08-30 起全部提交原始清单（684 条 + 5 行表头） |

> **本次没有做的事（如实）**：没有跑任何 dump 还原（红线）；没有 `git commit`（队长统一提交）；没有改 `custom_addons/**` 一行；没有碰 `评估表格/`；没有动生产 DNS；没有连生产（连不上）。

---

## 附录：引用密度最高的几份文件（供复核者先读）

| 文件 | 为什么重要 |
|---|---|
| `docs/audit/security-audit-infra.md` | 生产备份清单 + 35 个 0644 转储 + filestore 权限（**只有旧机才有的东西**的主要证据） |
| `docs/audit/security-audit-app.md` | 生产账号/门户账号/真实姓名 + `ir.config_parameter` 密钥清单 |
| `docs/research/gradebook-entry.md` | 2026-09-24 生产全量表读数（T1–T4/T9–T10/T15/T17） |
| `docs/plans/ux-v3-delivery.md` | 09-14 生产账号初态 + 币种切换 + 截止日裁定 |
| `docs/curriculum/import-report.md` | 09-14 课程清单导入的改前/改后/回滚 |
| `scripts/ops/retire_old_batches.py` | 09-24 班级迁移的**执行稿本身** + 生产备份路径 |
| `docs/audit/edu-eval-removal.md` | 生产最后一日的操作时间线 + 「最新生产备份」 |
| `docs/plans/README.md` | 68 份计划的状态与「入库 ≠ 生产生效」口径 |
