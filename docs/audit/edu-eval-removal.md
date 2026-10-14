# 行政评估（`edu_eval`）删除 —— 证据与回滚

> **状态：已执行（本地已完成；生产见 §4.2）**｜执行：2026-09-29｜授权：用户原话「行政评估可以删了，**完全没有人用过**，你删吧。」
> 判据、读数、原始输出与回滚路径全在本文件；**任何结论都能用文中的命令原样复跑**。
> ⚠ 本仓此前从未删过模块（弃用台账 §0 三态口径里「已删除」= 0 条）——**这是第一条「已删除」记录**，因此证据按最严标准留档。

---

## 0. 判据（先定规矩，再看读数）

**什么算「有人用过」** —— 满足任一条即为有过使用，必须停手上报：

| # | 判据 | 本轮结果 |
|---|---|---|
| J1 | 三张表（`edu_admin_eval_template` / `_item` / `_score`）**现在**有任何一行 | **否**（本地 0/0/0；生产 0/0/0） |
| J2 | 历史上出现过**任何一条非演示数据**（例如 name/note 不含【演示】标记的业务行） | **否**（全生命周期只进过 2 条模板，两条都叫「【演示】…」；见 §1.3） |
| J3 | 别的表有指向它的外键 / 通用引用（`res_model`+`res_id`） | **否**（全库仅模块内部 3 条 FK；mail/attachment/activity/followers/rating 0 命中） |
| J4 | 审计留痕（`edu_audit_log`）、服务器错误（`ir_logging`）里有它的行 | **否**（两者均 0 命中） |
| J5 | 别的模块的 xmlid / 数据登记指向它 | **否**（只有 `edu_eval` 自己的 73 条定义型 xmlid） |

**关键分辨（不是「从来没人点过」，而是「从没进过真实数据」）**：生产三张表的**累计**计数器
`pg_stat_user_tables.n_tup_ins` 显示历史上进过 2 模板 / 6 评分项 / 5 打分，**且全部被删**（`n_tup_del` 同数）。
这些行的真身已在备份里找到（§1.3）：**2 条模板全部带【演示】前缀**、5 条打分的 note 全部带【演示】字样
—— 即第三方演示批次 + 一次表单试填，**没有一条是教务/教师的真实业务数据**。

---

## 1. 第 1 步：证明「真的没人用过」

### 1.1 本地库 `edu19`（只读）

```bash
docker compose exec -T db psql -U odoo -d edu19 -c "
SELECT 'template' AS t, count(*) FROM edu_admin_eval_template
UNION ALL SELECT 'item', count(*) FROM edu_admin_eval_item
UNION ALL SELECT 'score', count(*) FROM edu_admin_eval_score;"
```

采集时刻 **2026-09-29 15:1x +08**（本地栈 `edu19-clone`）。原始输出：

```
    t     | count
----------+-------
 template |     0
 item     |     0
 score    |     0
```

配套（同一次运行）：
- 三张表**互指 FK 仅 3 条**（`item.template_id`、`score.task_id`、`score.item_id`，均 `ON DELETE CASCADE`）；
  **反向**（别的表指向它）**0 条**。
- `mail_message` / `ir_attachment` / `mail_activity` / `mail_followers` 按 `res_model LIKE 'edu.admin.eval%'` **全 0**。
- `edu_audit_log`（2250 行）按 `model LIKE 'edu.admin.eval%'` = **0**。
- `ir_model_data WHERE module='edu_eval'` = **73 行，且全是定义型**（ir.model / ir.model.fields / ir.model.access / ir.rule / ir.ui.menu / ir.ui.view / ir.actions / ir.model.constraint / selection），**没有一条数据型 xmlid**。
- 序列 `last_value` = 3 / 6 / 6（`is_called=t`）⇒ 历史上有过 3 模板 / 6 项 / 6 打分，**现存 0 行**；本地演示数据清理由 `scripts/cleanup_demo_data.py` 承担（它显式登记了 B 套三张表，模板按 `name` 的【演示】标记删）。

### 1.2 生产库 `edu19`（**只读 SELECT**，`edu19-prod-db-1`）

```bash
ssh prod-host "docker exec -i edu19-prod-db-1 psql -U odoo -d edu19 -f -" < /tmp/edu_step1_full.sql
```

采集时刻 **2026-09-29 15:4x +08**。原始输出（摘关键段）：

```
### P3. ROW COUNTS (the decisive reading)
           tbl           | rows
-------------------------+------
 edu_admin_eval_template |    0
 edu_admin_eval_item     |    0
 edu_admin_eval_score    |    0

### P4/P5/P6. 三张表 FULL DUMP → 均 (0 rows)

### P8. SEQUENCE forensics
    t      | last_value | is_called
-----------+------------+-----------
 template  |          2 | t
 item      |          6 | t
 score     |          7 | t

### P9. FK constraints pointing AT these tables  → 仅 3 条模块内部 FK
### P10. cross-references from OTHER tables      → (0 rows)
### P11. custom audit trail                     → audit_rows = 0
### P12. ir_model_data of module edu_eval        → 9 类定义型，共 73 行

### P14. pg_stat_user_tables
         relname        | n_tup_ins | n_tup_upd | n_tup_del | n_live_tup
------------------------+-----------+-----------+-----------+------------
 edu_admin_eval_item    |         6 |        22 |         6 |          0
 edu_admin_eval_score   |         5 |        10 |         5 |          0
 edu_admin_eval_template|         2 |        11 |         2 |          0
 datname | stats_reset
---------+-------------
 edu19   |            (NULL = 计数从未重置，是真实累计值)
```

### 1.3 那 2 条被删的模板是什么？（决定性证据）

生产上唯一"曾经装过数据"的备份快照是 `/opt/edu-app/backups/edu19_pre_user_cleanup.dump`
（**2026-08-25 18:08**，自定义格式）。只读抽取（`pg_restore -a -t <表> -f -`，**不落库**）：

```
COPY public.edu_admin_eval_template (...) FROM stdin;
1	1	1	【演示】学生日常量化 · 2026-09	student_daily	2026-09	open	2026-09-24	2026-08-24 17:08:33.758594	2026-08-25 07:05:23.11073
2	1	1	【演示】教师评教 · 2026-09	teacher_review	2026-09	open	2026-09-24	2026-08-24 17:08:33.758594	2026-08-25 07:05:23.11073
\.
```

- 两条**名字都以「【演示】」开头**；`create_uid=1`、`create_date` **同到微秒** ⇒ 一次性脚本批次（不是人工逐条录）。
- 打分行 5 条，`note` 逐条为「【演示】本月全勤，纪律良好」「【演示】课堂发言积极」「【演示】两次作业迟交」「【演示】评教示例」×2；
  被评对象 = `student_id=5` / `teacher_id=17`（演示批次的对象），`scorer_id` = 8/11。
- 6 条评分项里 5 条与模板同批次（`create_date` 同上），第 6 条（label=`权重`）由 **uid=2 于 2026-08-25 04:08 手工试填、04:17 被改过一次** —— 表单试填痕迹，不是业务。
- **窗口对账**：`2026-08-31 00:09` 起的每一份生产备份（含 `edu19_before_cleanup_0830`、`before_enroll_v2`、`before_feedbackbot`、`before_ledger`、`pre_*_2026091[89]/092[12]`）
  的同一 COPY 段**都是空** ⇒ 这些行在 8/25 之后、8/31 之前就被删了，此后**再无新增**。
- `pg_stat_user_tables.n_tup_ins` 全生命周期 = 2/6/5，与上述快照**逐行对上**（模板 2、项 6、打分 5）⇒ **可以断言"一条不漏"**：这两张快照 + 计数器覆盖了该模块的全部历史写入。

### 1.4 ⚠ 与队长简报的两处不符（以实测为准）

1. 简报说「门户路由 `/eval/*` **已全部 303** 收口」——**准确**（壳在 `edu_assess`，见 §3.1），
   但**生产与本地不同步**：本地的后台菜单 597–600 已按收口方案停用/迁移，**生产上 597 仍是 `active=t`、598–600 仍挂在 597 下**
   （读 `ir_ui_menu`：本地 `597 active=f / 598-600 parent=588`；生产 `597 active=t / 598-600 parent=597`）。
   原因是 F1（未关闭）：`-u edu_eval` 会把模块自己的 `<menuitem>` 重放回来，生产 2026-09-29 04:30 刚跑过一次升级。
   **对本次删除无影响**（卸载会把 597–600 一并删掉），但它是"文档写已收口、生产其实没收口"的又一实证。
2. 简报列举的交叉引用里**漏了 3 处**（都在第 3 步发现并处理）：
   - `edu_portal/controllers/batch2.py` 的 `_YONGYUE_CARDS` 里**两张首页卡**直接指向 `eval/my`、`eval/review`；
   - 同一文件的 `FA_HOME_ICONS` 图标映射与「成长」分组的 href 名单；
   - `edu_portal/views/register.xml` 注释里以 `edu_eval` 的 JS 当"同源写法"范例。

---
## 2. 第 2 步：生产备份（删除不可逆 ⇒ 先备份再动手）

```bash
ssh prod-host 'cd /opt/edu-app && docker compose exec -T db pg_dump -U odoo edu19 | gzip > /root/pre_deleval_$(date +%Y%m%d_%H%M).gz'
ssh prod-host 'ls -la /root/pre_deleval_*.gz'
```

原始输出（2026-09-29 15:45 +08）：

```
DUMP_RC=0 FILE=/root/pre_deleval_20260929_1545.gz
-rw-r--r-- 1 root root 4925334 Sep 29 15:45 /root/pre_deleval_20260929_1545.gz
== /root/pre_deleval_20260929_1545.gz
bytes=4925334
gzip -t: OK
```

完整性核对（不止看大小）：

| 项 | 读数 |
|---|---|
| 文件 | `/root/pre_deleval_20260929_1545.gz` |
| 大小 | **4,925,334 B**（非 0；同量级旁证：同期 `pre_majortrack_20260922.gz` = 5.47 MB） |
| 格式 | plain SQL（pg_dump 默认）⇒ `pg_restore -l` 不适用，用 `zcat \| grep -c '^CREATE TABLE'` 核对 |
| `gzip -t` | OK |
| `CREATE TABLE` 语句 | **714** 条 |
| `COPY ` 数据块 | **714** 个（与表数一致 ⇒ 结构完整） |
| 含 `edu_admin_eval` 建表 | **3** 条（三张表都在备份里，回滚时表结构可还原） |
| sha256 | `5a698dd01dcbc2f6b957c817a84596d75bedc77b50a76ec1ba28f6389da28b9d` |
| 磁盘余量 | `/dev/sda1 96G 22G 已用 75G 可用 (23%)` |

> 备份是**全库**的（不是只备这三张表）：卸载会连带删 ACL/ir.rule/菜单/动作/视图/字段定义与 3 张表，
> 单表备份不足以还原"模块曾装过"的完整状态。

---

## 3. 第 3 步：拔入口与交叉引用（**先 grep 全仓，不按简报的清单办事**）

统一判据：**「命中」= 删改前 grep 有、删改后 grep 无**；命令与输出均为原样。
唯一"故意保留"的命中是**说明性注释里的模块名**（下表中逐条注明）。

| # | 位置 | 处理 | 改前 | 改后 |
|---|---|---|---|---|
| 1 | `edu_assess/controllers/portal.py` 的 `EduAdminEvalCompat`（继承 `edu_eval` 控制器做 `/eval/*` 303 壳）+ 文件头 import | **整段删除**（含 `_redirect_old`；该文件自己的注释就写着"三期卸载 edu_eval 时，本段要连同 import 一起删"） | `grep -n 'edu_eval\|EduAdminEvalPortal\|_redirect_old' → 9 命中` | **0** |
| 2 | `edu_eval/views/eval_views.xml` 的根菜单 597 + 三个子菜单 | 随模块卸载连记录一起删（菜单行 597–600 → 库里 0 条） | 库里 597–600 = 4 行 | **0 行** |
| 3 | `edu_portal/controllers/batch2.py` 的**兜底分支**（`edu.admin.eval.task` 优先 + 回退 `edu.admin.eval.template` 的 state=open 计数） | 换成 `eval_open = 0` + 说明注释（新数据源属产品决定，见 §6） | 11 行 if/elif/else | **1 行赋值** |
| 4 | `edu_portal/controllers/help_center.py` 帮助卡文案「行政评估任务发布」 | →「综合评估任务发布」 | 1 命中 | **0** |
| 5 | `edu_portal/views/help_center.xml` 教务版正文「行政评估与报名表维护」 | →「综合评估与报名表维护」 | 1 命中 | **0** |
| 6 | `edu_nav/data/menu_consolidation_data.xml` 的 4 条 `edu_eval.menu_*` 记录 | 删除 4 条（记录键的 xmlid 随模块消失，留着只能被 `forcecreate="0"` 跳过） | 4 命中 | **0** |
| 7 | `docs/audit/menu-consolidation/menu-consolidation-plan.json` 的 `merged` 里 id=597 条目 | 删除该条目（XML 是它生成的；下次 `gen_menu_data.py` 由此算出 353） | 1 命中 | **0** |
| 8 | `tests/ui/surface.json` 里 6 条 `/eval/*` 登记行 | 删除（否则 `check_ui_surface` 会判"登记已失效"；三个 UI 门禁的名单都读它） | 6 命中（`pages` 308→302） | **0** |
| 9 | `edu_portal/controllers/roles.py` 的图标/配色映射 `'行政评估'` | 两个键删除（菜单没了，映射成死键） | 2 命中 | **0** |
| 10 | `edu_portal/security/security.xml` 注释里"未加行规则的模型"点名 `edu.admin.eval.*` | 删掉该条（模型不存在了） | 1 命中 | **0** |
| 11 | `edu_portal/models/alumni_job.py` 注释「与 edu_eval 的 'closed' 口径一致」 | 改为「评估类 state 'closed'」 | 1 命中 | **0** |
| 12 | **简报漏项①**：`edu_portal/controllers/batch2.py` 的 `_YONGYUE_CARDS` **两张首页卡**（`eval/my`「我的评分」、`eval/review`「评教填答」）+ `FA_HOME_ICONS` 两条 + 「成长」分组 href 名单 + 非学生隐藏集 | 合并为一张卡 `('assess/my', '我的评估', …)`（**并卡不是随手合并**：`spec_map` 以 href 为键，两张同 href 的卡会渲染成两张一模一样的瓦片） | 6 处 `eval/my`/`eval/review` | **0** |
| 13 | **简报漏项②**：`edu_portal/views/register.xml` 注释以 `edu_eval` 的 JS 当"同源写法"范例 | 只留 `edu_apply` 那一半 | 1 命中 | **0** |
| 14 | `edu_eval/**` 整个模块（13 个受版本管理的文件） | **删除目录**；模块卸载后源码无宿主 | — | **目录不存在** |

**唯一保留的命中（有意）**：`batch2.py` 内部**说明"为什么留 0"的注释**里出现了一次 `edu.admin.eval.template`
（"原口径 = …的 template state=open；该模块已卸载 ⇒ 恒为 0"）—— 那是**删除说明**，不是活引用。

### 3.1 复核命令（改后应为 0）

```bash
grep -rn 'edu_eval\|edu\.admin\.eval' custom_addons/ --include='*.py' --include='*.xml' --include='*.csv' --include='*.js' --include='*.po' \
  | grep -v '^custom_addons/edu_eval/' | grep -v 'edu\.eval\.'      # 会剩：说明性注释 3 处（见上）
grep -rn '行政评估' custom_addons/ --include='*.py' --include='*.xml'   # 同上，只剩说明性注释
grep -c 'edu_eval' tests/ui/surface.json                                # → 0
grep -c 'edu_eval' docs/audit/menu-consolidation/menu-consolidation-plan.json   # → 0
```

⚠ **不要把 `edu.eval.*`（A 套，`edu_portal`）当成同一实体**：A 套仍在用，它的
`access_edu_eval_template_user` / `view_edu_eval_template_list` / `edu_eval_center` 这些
**xmlid 与模板名**会让 `grep edu_eval` 命中 —— 它们**不是** B 套的引用，本轮一行未动。

---

## 4. 第 4 步：卸载模块（**不可逆的那一步**）

### 4.1 本地（`edu19`）

路径 = `odoo shell` + `button_immediate_uninstall()`（`scripts/safe_upgrade.sh` 只做 `-u`/`-i`，卸载没有等价开关）。
取同一把串行锁（`$TMPDIR/edu19_upgrade.lock`，与 `safe_upgrade.sh` 同路径）+ 同一套 DB 参数。原始输出（`/tmp/edu_local_uninstall.log`）：

```
ALLOW access to module.button_immediate_uninstall on ['Edu Admin Evaluation (行政评估)'] to user __system__ #1
User #1 triggered module uninstallation
Deleting ir.ui.menu(600, 599, 598, 597)
Deleting ir.actions.act_window(740, 739, 738)
Deleting ir.model(979, 978, 977)
Deleting ir.model.fields(14655, ... 24 条)
Deleting ir.model.access(1339 ... 1331)
Deleting ir.rule(339, 338)
[edu_nav] 菜单收口守卫：声明改写 357 条（参数表记为 357）；根菜单 37 条（停用 23）；全库 509 条（停用 178）
MARKER::STATE_BEFORE::installed
MARKER::STATE_AFTER::uninstalled
MARKER::TABLE::edu_admin_eval_template=None
MARKER::TABLE::edu_admin_eval_item=None
MARKER::TABLE::edu_admin_eval_score=None
MARKER::IMD_EDU_EVAL=0
MARKER::MENUS_597_600=0
MARKER::MODELS_LEFT=0
=== odoo shell rc=0 ===   no Traceback / CRITICAL
```

- 全库菜单 513 → **509**（少的就是 597–600）。
- `edu_nav` 守卫**没有报漂移**（打印的 "357/357" 是**两个声明值**的对账，不是实况条数）——
  ⚠ 因此本次**故意没有**去改 `MENU_CONSOLIDATED_COUNT` 常量：它一改、而 DB 参数还是 357，守卫就会**真的**报 ERROR。
  正确收口方式 = 卸载后重跑 `python3 scripts/gen_menu_data.py`（它会按实况重算成 353 并同时写常量与参数）。**已登记为待办（§6）**。

#### 门禁读数（本地，全绿）

| 门禁 | 命令 | 结果 |
|---|---|---|
| 路由矩阵 | `python3 tests/smoke/ux_v3_route_matrix.py` | **EXIT=0**；检查点 525：PASS 525 / WARN 0 / PENDING 0 / **FAIL(真红) 0 / ENV 0** |
| 无障碍 | `python3 scripts/check_accessibility.py` | **EXIT=0**；66 页，基线 `{0,0,0,0,0}`、本轮 `{0,0,0,0,0}`，"漂移判定：在基线内"；指纹 123bf9a9 |
| 英文字面 | `python3 scripts/check_english.py` | **EXIT=0** |
| UI 表面登记 | `python3 scripts/check_ui_surface.py` | **EXIT=0**（路由 ↔ surface.json 双向一致：6 条 `/eval/*` 同步删除） |
| 活体注册表 | `python3 scripts/check_live_registry.py` | **EXIT=0**；模块 12 个、**93/93 LIVE、0 DARK**（字段级 SKIP：匿名会话读不到 fields_get） |
| 继承视图 | `python3 scripts/check_view_xpath.py` | **EXIT=0** |
| 跨表 init | `python3 tests/smoke/init_cross_table_check.py` | **EXIT=0** |
| 导航可达 | `python3 scripts/check_nav_reachable.py` | **EXIT=0**（20 条导航目标全部 200） |
| （附）manifest 跟踪 | `python3 scripts/check_manifest_tracking.py` | **EXIT=0** |
| 前置探活 | 无升级锁 + cookie jar 访问 `/web/login?db=edu19` | 302（合规） |

> **`check_live_registry` 少了哪几个模型（预期，不改期望值）**：少的就是本模块的 **3 个** ——
> `edu.admin.eval.template` / `.item` / `.score`（卸载日志里 `Deleting ir.model(979, 978, 977)` 是硬证据）。
> 本地读数 96 → **93**；生产同型 91 → **88**（两边的差值都恰好是 3）。
> 该门禁的扫描面是**按已装模块现算的**（"模块 12 个 —— …"），不是写死的期望值 ⇒ **不需要、也不应该**去改它的期望值。

### 4.2 生产（`edu19` @ prod-host）

**为什么不是 `deploy_myedu.sh`/rsync，而是"远程定点补丁"**：卸载前必须先让 `edu_assess` 不再 import `edu_eval`，
否则下一次注册表装载会直接炸。但本地这两个文件里**同时有别的 agent 未提交的在制品**
（`edu_assess/controllers/portal.py`、`edu_portal/controllers/batch2.py` 在本批之前就是 `M` 状态）
⇒ rsync 整目录 = **把别人的半成品带上生产**。所以对生产只做**锚点定点替换**（替换前逐条断言"锚点恰好命中 1 次"，
不满足就整批中止、一个字节都不写）。

| 步骤 | 结果 |
|---|---|
| 0. 前置：Step-2 备份仍在且 `gzip -t` OK | ✅（4,925,334 B） |
| 1. 备份被改文件 | `/root/deleval_20260929_160331/{portal.py.before, batch2.py.before}`（分别 72,674 / 94,330 B） |
| 2. 定点补丁 | `portal.py`：删 51 行兼容块 + 3 行 import（→1438 行）；`batch2.py`：7 处替换（→2033 行）；两边 `py_compile` OK |
| 3. 卸载 | `STATE_BEFORE::installed` → `STATE_AFTER::uninstalled`；三表 `to_regclass=None`（DROP）；`IMD=0`；`MENUS=0` |
| 4. 重启 + 探活 | web 重启后 **6 秒** `/web/login → 302` |
| 5. 后置读数 | `edu_eval = uninstalled`；`ir_model_data edu_eval = 0`；**菜单 515 → 511**（−4）；表残留 0 |
| 6. HTTP 探活 | `/eval/my`→**404**、`/eval/review`→**404**、`/eval/fill/1`→**404**；`/assess/my`→303（匿名）、`/my/home`→303、`/login`→200、`/web/login`→302 |
| 7. 活体注册表门禁（生产） | **PASS**；模块 12 个、**88/88 LIVE、0 DARK**（字段级 SKIP，同本地口径） |
| 8. 源码处置 | `custom_addons/edu_eval` **移出 addons 路径** → `/root/deleval_20260929_160331/edu_eval_source`（多留一条还原路径） |

⚠ **生产侧没跑 UI 门禁**（如实声明，不是"跑了没问题"）：`/opt/edu-app` 下**只有 `scripts/`，没有 `tests/`**，
也没有可用的浏览器账号 ⇒ route_matrix / accessibility / english / ui_surface **在生产上不可跑**。
生产侧实际跑到的「同样口径」只有 `scripts/check_live_registry.py` + curl 探活 + psql 读数，全部通过。
**生产 UI 面的真实验活要等下一次带门禁的部署**（那时 `tests/` 会跟着上去）。

#### 踩到并已修复的两个坑（留给下一个人）

1. **`docker exec -i` 会吃掉从 stdin 喂进来的脚本**：脚本用 `ssh … 'bash -s' < script` 方式执行时，
   里面若有 `docker exec -i … psql`，psql 会把**脚本剩余部分**当成自己的 stdin 读走 ⇒ 脚本静默提前结束、
   **退出码还是 0**（第一次尝试就这样停在"PRE-STATE 第 2 条查询"）。修法：改 `docker exec`（去掉 `-i`）或显式 `< /dev/null`。
2. **`odoo shell` 的子命令必须排在选项之前**：`odoo --db_host=… shell` 会报 `unrecognized parameters: shell`（默认按 `server` 子命令解析）。
   正确形态抄 `scripts/gen_menu_data.py`：`odoo shell -c /etc/odoo/odoo.conf --db_host=db -r odoo -w odoo -d edu19 --no-http`。

---

## 5. 第 5 步：回滚路径（删错了怎么办）

| 层 | 回滚动作 | 位置 / 命令 |
|---|---|---|
| **数据（生产）** | 恢复全库备份 | `/root/pre_deleval_20260929_1545.gz`（sha256 见 §2）<br>`ssh prod-host 'cd /opt/edu-app && zcat /root/pre_deleval_20260929_1545.gz \| docker compose exec -T db psql -U odoo -d edu19'`<br>⚠ 这会**覆盖**期间的所有新数据 —— 只在确认删错时用 |
| **数据（本地）** | 本地无删除前备份；本地是克隆库，且三张表 0 行 ⇒ 数据无可回滚的必要 | —— |
| **代码** | `git checkout <commit> -- custom_addons/edu_eval` | **锚点 commit = `35a1dc55e03ae7c04a911bff388fdaab9f0706af` 及其之前**（本批改动**未提交**，提交后锚点不变：该 commit 仍含完整模块）<br>校验：`git ls-tree -r --name-only 35a1dc5 custom_addons/edu_eval \| wc -l` → **13** |
| **生产代码** | 模块源码被移出 addons 路径（不是销毁） | `/root/deleval_<stamp>/edu_eval_source`（同目录另有被改文件的 `.before` 原件） |
| **重新安装** | `safe_upgrade.sh -i edu_eval`（本地）／生产 `docker compose run … odoo -i edu_eval` | 表会按模型重建（**数据不会回来**，要靠 §2 的备份） |

---
## 6. 我没做成 / 不确定的部分（不粉饰）

### 6.1 硬阻断（**已修**，队长 2026-09-29 扩权后）

原本 `scripts/deploy_myedu.sh` 有 3 处 `edu_eval`（`MODULES` 默认值 / rsync 源列表 / chmod 列表）+
`scripts/gen_icons.py` 的 SPEC 会往已删目录写图标。**两处都已改并验证**，逐条见 §7。

### 6.2 残留引用 —— 全部已处置（原为 13 个文件，现 0 个活引用）

**逐文件「改了什么 / 为什么」见 §7。** 仍**故意保留**的只有两类，且都不是活引用：
1. **历史/取证文件**（不改）：`docs/audit/eval-rebuild/a-suite-eval-definitions.json`（删除前的 B 套 0/0/0 留档，
   已加覆盖互锁）、`docs/plans/eval-merge-design.md`（已被 eval-rebuild 线判作废的设计稿，留作史料）、
   `docs/audit/menu-consolidation/menu-tree-*.json` 等**带日期的取证快照**（记录的是当时读数，改了就是伪造历史）。
2. **说明性注释**（保留）：本批新写的注释里出现 `edu_eval` 的地方 —— 那是"这个模块为什么没了"的说明，
   不是活引用。判据：`grep -rn 'edu_eval' custom_addons/ | grep -v '已卸载\|已删\|原口径\|原「' ` 应为空。

### 6.3 我特意没做的事（附理由）

1. **没改 `MENU_CONSOLIDATED_COUNT` / `edu_nav.consolidated_count`**：两者现在都是 357、彼此一致 ⇒ 守卫绿。
   单改常量会让守卫**真的**报漂移。正确收口 = 卸载后重跑 `python3 scripts/gen_menu_data.py`（会重算成 353 并同时写常量与 DB 参数）。
2. **没跑 `-u edu_portal` / `edu_nav`（本地或生产）**：`-u edu_portal` 会触发已登记的 **F1 菜单重放**；
   生产上还等于顺手重放整份菜单收口（生产当前 515 条菜单/19 个 active 根，与本地口径不同）——**那是队长的决策，不是删除行政评估的必要步骤**。
   已核实：卸载**不需要** `-u` 任何模块（`odoo shell` 卸载后注册表自己重载，重启 web 即生效）。
3. **生产上没同步 cosmetic 改动**（help 文案、`edu_nav` XML 的 4 条、roles/security/alumni_job 注释、register.xml 注释）：
   它们要么只影响文案、要么需要 `-u` 才生效；为避免 F1 与"带上他人 WIP"，生产只打了两处**功能性**补丁
   （`edu_assess` 去壳 + `batch2.py` 卡片/KPI）。**下次正常部署会一并同步**（那时本地是权威版本）。
4. **KPI「进行中评估」留 0 而不是换数据源**：`eval_open` 原来读 `edu.admin.eval.template`；现在恒 0（徽标不再出现）。
   把它接到新引擎 `edu.assess.task` 的 state 口径是**产品决定**，超出"删除行政评估"的授权范围 ⇒ 如实留空并在此点名。
5. **没有"顺手"删 A 套**：`edu_portal` 的 `edu.eval.*`（`/my/evaluation*` → 303 `/assess`）与本次任务无关，一行未动。

### 6.4 结论上的精确边界（避免下一个人误引）

- 可以说：**"生产从未有过任何真实（非演示）行政评估数据；现存 0 行"**。
- **不能说**：**"这张表从未被写入过"** —— 生产累计写入过 2 模板 / 6 项 / 5 打分（全部演示/试填，且已全部删除）。
  本地同型：序列到 3/6/6。
- 本地那次 `0/0/0` 与生产那次 `0/0/0` **各自独立实测**，不是互相引用。

### 6.5 未验证项

- **生产 UI 面**（页面渲染、无障碍、英文文案）**本次未验证** —— 生产没有 `tests/`、也没有浏览器账号，见 §4.2 的显式声明。
- `tests/smoke/zero_loss_reachability.py` **没跑成**：本地 `admin` 角色登录 `Access Denied`（ENV），
  按仓库规矩 ENV 不当结论 ⇒ 只给**静态判据**（名单里含 `eval/my`、`eval/review`，见 6.2），未给实跑读数。
- 生产上"卡片是否真的渲染成 `/assess/my`"**只验证到代码与探针层**（补丁已写、`py_compile` 过、web 已重启、
  `/assess/my` 可达），**没有登录态的门户截图/HTML 断言**（缺生产门户账号）。
## 7. 残留引用处置：逐文件「改了什么 / 为什么」（队长 2026-09-29 扩权后）

> 原则：**专用工具才删整份；通用工具只改条目**；**绝不为让门禁变绿而放宽断言**
> （`eval_rebuild.py` 那条就是反例：旧期望 303 已不可能成立，**正确的期望是 404**，且要贴着真实状态码写）。

### 7.1 `scripts/deploy_myedu.sh`（原硬阻断）—— 4 处改动 + 可跑性证明

| 位置 | 改前 | 改后 |
|---|---|---|
| `MODULES` 默认值 | `edu_life,edu_eval,edu_schedule,…` | `edu_life,edu_schedule,edu_apply,edu_portal,edu_brand,edu_tg_bind,edu_assess`（**只去 edu_eval，其余一个字节未动**） |
| rsync 源列表 | `… edu_life edu_eval edu_schedule …` | 去掉 `edu_eval` |
| chmod 列表 | `… edu_life edu_eval edu_schedule …` | 去掉 `edu_eval` |
| 头部用法注释的示例 | `deploy_myedu.sh edu_life,edu_eval` | `deploy_myedu.sh edu_life,edu_assess`（同样是 edu_eval 相关的那一处；仅示例文本） |

**可跑性证明（原始输出）**：

```
$ bash -n scripts/deploy_myedu.sh && echo 'deploy syntax OK'
deploy syntax OK
$ grep -c 'edu_eval' scripts/deploy_myedu.sh
0

$ cd custom_addons && for m in edu_life edu_schedule edu_apply edu_portal edu_brand edu_quiz edu_public edu_zh edu_tg_bind edu_assess; do [ -d "$m" ] && echo "OK $m" || echo "MISSING $m"; done
OK      edu_life / edu_schedule / edu_apply / edu_portal / edu_brand / edu_quiz / edu_public / edu_zh / edu_tg_bind / edu_assess     （10/10 全在）

$ rsync -az --dry-run --exclude='__pycache__' -e "ssh -o BatchMode=yes -o ConnectTimeout=20" \
    edu_life edu_schedule edu_apply edu_portal edu_brand edu_quiz edu_public edu_zh edu_tg_bind edu_assess \
    "prod-host:/opt/edu-app/custom_addons/"
attempt 1 TRUE_EXIT=0     ← 源集合完整、远端可达、比较成功（--dry-run 不传输、不升级、不重启）
```

> ⚠ **没有真跑部署**（队长要求：真跑会把本地其他 agent 的未提交改动一并推上生产）。
> 上面的 `--dry-run` 是"不改远端一个字节"的最强证明：它走的就是脚本第 1 步那条命令。
> **MODULES 默认值覆盖面复核**（队长要求"别顺手多删"）：默认升级 7 个 /
> rsync 同步 10 个 / **同步但默认不 `-u` 的 3 个 = `edu_public`,`edu_quiz`,`edu_zh`（改动前就是这样，我没动）**；
> 仓内 `edu_*` 共 12 个 ⇒ **既不同步也不升级的 2 个 = `edu_nav`,`edu_telegram`（改动前就是这样）**。
> 这两条是**既有口径**，本次**未改**，但值得队长知道（尤其 `edu_nav`：本次改的 `edu_nav/data/menu_consolidation_data.xml`
> **不会**被 `deploy_myedu.sh` 同步到生产）。

### 7.2 其余文件

| # | 文件 | 改了什么 | 为什么 | 验证 |
|---|---|---|---|---|
| 1 | `scripts/gen_icons.py` | 删 `'edu_eval/'+MENU+'admin-eval.svg'` 这条 SPEC；docstring 产物清单去掉 `edu_eval` | 那条 SPEC 会往**已删目录**写图标，凭空重建半个模块 | 跑了一次生成器：`generated 50 icons` / EXIT=0；`ls -d custom_addons/edu_eval` → **No such file or directory**；与仓库现状 diff = 空（**没顺带改别的图标**） |
| 2 | `tests/smoke/zero_loss_reachability.py` | `STALE_35_HREFS` 里 `'eval/my','eval/review'` → **`'assess/my'`**（一张卡）；4 处"35"文案改为 34 / 动态化；常量名保留 | 卡片已并成一卡（§3 第 12 条）⇒ 名单要贴现实；**不是放宽断言**（`/my/apps` 里仍必须出现这张卡） | `py_compile` OK；AST 解析读回：**34 张**，含 `assess/my`，不含 `eval/my`/`eval/review` |
| 3 | `tests/smoke/eval_rebuild.py` | V9 段：`/eval/*` 从"303 → /assess"**改判 404**，并扩成 5 条负向断言（`/eval/my`、`/eval/review`、`/eval/review/9`、`/eval/fill/9`、`/eval/fill/9/save`）；A 套 `/my/evaluation*` 的 303 断言**原样保留** | 模块与 303 壳都删了 ⇒ 旧期望**不可能**再成立；真实状态码 = 404（**实测**：生产 `curl` 五条全是 404） | 生产实测 5/5 = 404（§4.2）；本地 `py_compile` OK |
| 4 | `tests/_edu_eval_smoke.py` | **整份删除**（93 行） | 文件本身 = 被删模块的专属冒烟（全部 `/eval/*`）；删前确认**无任何文件 import 它**（只有一份设计文档引用它的 89–90 行断言 `/my/home`） | `grep -rn '_edu_eval_smoke' --include='*.py'` → 0 个 importer；引用它的设计文档已加补注（第 8 行） |
| 5 | `tests/audit/verify_consolidation.py` | 两条探针 `/eval/my`、`/eval/review` → **`/assess/my`、`/assess/review`**（角色不变） | 保住"学生评估入口可达"这条读数，改贴新引擎的同义页 | `py_compile` OK；两条路由在 surface.json 里登记且 gates 含 route_matrix |
| 6 | `tests/audit/verify_upgrade_persistence.py` | `--modules` 默认值去掉 `edu_eval`；头部用法示例同步 | 模块不存在时 `-u edu_eval` 直接报错，默认值会让工具一跑就崩 | `py_compile` OK |
| 7 | `scripts/cleanup_demo_data.py` | 删 5 处 B 套条目（`DEMO_MODELS` 3 条 + `person_table` 1 键 + `parent_map` 1 键） | 三张表已不存在（脚本虽 `table_exists` 会跳过，但留着是永久噪音） | `py_compile` OK；`grep admin.eval` → 0 |
| 8 | `scripts/backup_a_eval_json.py` | 去掉 B 套 3 张表的采集项与 `b_suite` 桶；**新增覆盖互锁**：产物里已有 `b_suite` 时默认拒绝覆盖 | 产物 `docs/audit/eval-rebuild/a-suite-eval-definitions.json` 是**删除前**的取证材料（B 套 0/0/0）；重跑会把它抹掉 | 实跑脚本 → `REFUSED …（确需覆盖请显式 EDU_ALLOW_OVERWRITE_EVIDENCE=1）`，**EXIT=3**；原文件未变 |
| 9 | `scripts/ui_surface_report.py` | `ROUTES` 里两行改登记 `/assess/my`、`/assess/review`；删 `PENDING_PARENT` 与 `SAMPLE_ID` 里的 `/eval/review/<int:task_id>` 两条 | 该表是"路由 → 期望角色"的登记面，旧路由已 404；改登记同义新页，保持覆盖不缩水 | `py_compile` OK |
| 10 | `scripts/check_english.py` | 删 `/eval/my`、`/eval/review` 两条名单项 + 2 条 303 豁免 + 那段注释 | 活名单已改从 `surface.json` 读，这里是**遗留常量**；留着会让"某脚本名单里有 /eval/*"长期存在于源码里 | `py_compile` OK；门禁实跑见 §8 |
| 11 | `scripts/check_prod_menus.py` | 修复建议里打印的 `-u edu_portal,edu_eval,…` 去掉 edu_eval | 那是给人照抄的命令，含已删模块会直接报错 | `py_compile` OK |
| 12 | `scripts/portal_token_map.py` | 删掉死输入 `edu_eval/static/src/css/eval_portal.css`；在生成的审计文档里加一条**dated 补注**（说明该文件已删、§5.2 依赖表是历史读数） | 死输入会让脚本读不到文件；而那些散文是**当时的定稿读数**，改写=伪造历史 ⇒ 只加补注 | `py_compile` OK |
| 13 | `scripts/gen_manual.py` | 「3.5 行政评估发布（edu_eval）」整节改写为「3.5 行政评估（已下线）」+ 指向新引擎入口；速查表 `('评教','/eval/review','匿名')` → `('评教','/assess/my','匿名；学生在新引擎的评估页填答')` | 手册教的是已经不存在的功能；/eval/review 也不是学生的评教入口（新引擎里学生评教在 `/assess/my`） | `py_compile` OK |
| 14 | `scripts/test_life_eval.py` | **删 ④⑤ 两段**（教师 `/eval/fill/1` 打分 + 学生 `/eval/my` 查总分）与 3 个只服务于它的常量；docstring 说明去向 | 这是**混合**脚本（打卡/周记/批阅是 `edu_life` 的，打分是 `edu_eval` 的）⇒ 只删死的那半，保住灵命生活侧的 E2E | `py_compile` OK；残留 1 处 `/eval/` 在"说明为什么删"的注释里 |
| 15 | `README.md` | 第 59 行模块表：`edu_eval` 一行改为"已卸载并删除"并指向新引擎 | 根 README 的模块地图是入口文档，留着会让人以为模块还在 | `grep -n edu_eval README.md` → 2 处（第 59 行已改；第 93 行是**历史叙事**，留） |
| 16 | `docs/plans/student-portal-home-profile-design.md` | 引用 `tests/_edu_eval_smoke.py:89-90` 的那行加补注 | 被引用文件已删 ⇒ 不补注就是**悬空引用**；补注同时写明 `/my/home` 的可达性现由 route_matrix 覆盖（该路径登记在 surface.json、gates 含 route_matrix —— 已核） | 已核 surface.json |

---
## 8. 收尾复核（残留处置之后再跑一遍全部门禁）

**运行时刻 2026-09-29 16:28–16:30 +08**（前置探活：无升级锁、cookie-jar `/web/login?db=edu19` → 302）。
逐条命令与退出码（`/tmp/edu_gates_after.log`）：

| 命令 | 退出码 |
|---|---|
| `python3 scripts/check_view_xpath.py` | **0** |
| `python3 tests/smoke/init_cross_table_check.py` | **0** |
| `python3 scripts/check_ui_surface.py` | **0**（路由 ↔ surface.json 双向一致；`check_english` 名单常量同步后**不变式 3 仍成立**） |
| `python3 scripts/check_manifest_tracking.py` | **0** |
| `python3 scripts/check_english.py` | **0** |
| `python3 scripts/check_nav_reachable.py` | **0** |
| `python3 scripts/check_live_registry.py` | **0**（93/93 LIVE、0 DARK） |
| `python3 scripts/check_qweb_dict_foreach.py` | **0** |
| `python3 scripts/check_docs_index.py` | **0** |
| `python3 tests/smoke/ux_v3_route_matrix.py` | **0**（检查点 525：PASS 525 / WARN 0 / PENDING 0 / **FAIL 0 / ENV 0**） |
| `python3 scripts/check_accessibility.py` | **0**（66 页；基线 `{0,0,0,0,0}` = 本轮 `{0,0,0,0,0}`，"漂移判定：在基线内"；指纹 123bf9a9） |

### 8.1 路由真实状态码（`eval_rebuild.py` 新断言所依据的实测）

**本地**（`localhost:8069`，2026-09-29 16:30 +08）：

```
/eval/my -> 404   /eval/review -> 404   /eval/review/9 -> 404   /eval/fill/9 -> 404   /eval/fill/9/save -> 404
/assess -> 303    /assess/my -> 303     /assess/review -> 303      （匿名 → 登录门禁，非 404）
```

**生产**（`127.0.0.1:8069` @ prod-host，2026-09-29 16:15 +08）：同 5 条 **全 404**；`/assess`、`/assess/my` → 303。

⇒ `tests/smoke/eval_rebuild.py` 的 V9 断言（404）与**两个环境的真实读数一致**，不是照旧结论改的。

### 8.2 队长要求的生产侧补充确认（原话：确认 /eval/* 是 404、后台菜单搜不到「行政评估」）

```
SELECT count(*) FROM ir_ui_menu WHERE name::text LIKE '%行政评估%';        -- → 0
SELECT count(*) FROM ir_model_data WHERE module='edu_eval';                -- → 0
SELECT name||' = '||state FROM ir_module_module WHERE name='edu_eval';     -- → edu_eval = uninstalled
SELECT count(*) FROM information_schema.tables WHERE table_name LIKE 'edu_admin_eval%';  -- → 0
库里仍叫「评估」的菜单（存证，全是新引擎/门户的，与本模块无关）：
  588 | 综合评估 | parent=-   | active=true
  590 | 评估任务 | parent=588 | active=true
  625 | 评估任务 | parent=588 | active=true
```

`/opt/edu-app/custom_addons` 里已无 `edu_eval`（源码在 `/root/deleval_20260929_160331/edu_eval_source`）。

---

## 9. 一处「文档与生产不一致」（队长 2026-09-29 采纳登记）

`docs/code-map.md`（改前）与弃用台账都记着**收口已完成**：`597 行政评估已停用，子树 598/599/600 已迁入 588 综合评估`。
**那是本地口径，生产从来不是这样**：2026-09-29 删除前实测，生产 `ir_ui_menu` 里 **597 仍是 `active=t`、598–600 仍挂在 597 下**
（原因 = 已登记的 F1：`-u edu_eval` 会把模块自己的 `<menuitem>` 重放回来，而生产 2026-09-29 04:30 刚跑过一次升级）。

**这条的价值**：下一个人若照文档判断生产状态，会以为后台已经看不到「行政评估」，实际当时**看得见**。
**现在的状态**：卸载已把 597–600 **整条删掉**（生产菜单 515 → 511、`LIKE '%行政评估%'` = 0）——
所以**这个问题连同它的成因一起消失了**（模块不存在 ⇒ 再也没有 `-u edu_eval` 去重放它）。
`docs/code-map.md` 与台账已同步改成"已删除"，不再留"已收口/已停用"的旧描述。
