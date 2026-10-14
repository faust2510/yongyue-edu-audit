# 弃用台账（Deprecated Inventory）

> **这份台账只有一个目的：让「哪些东西已经不用了」变成可查、可验、可安全删除的三态记录。**
> 本仓红线是**零业务记录删除**（只隐藏 / 迁移 / 重定向）——所以本轮**没有删除任何菜单、模型、表或记录**；
> 本文写下的是「**如果将来要删，先满足什么**」。
>
> - 建立：t6（2026-09-17）｜裁定：队长｜维护：docs-eng（**本文件只追加，不覆盖历史行**）
> - 上游依据：`docs/audit/feature-overlap-audit.md`（t1 审计与施工图）、
>   `docs/audit/menu-consolidation/diff-report.md`（逐字段改动 129 条）、
>   `docs/audit/checkin-merge-report.md`（t5 打卡合一实施报告）、
>   `docs/plans/eval-merge-design.md` 与 `docs/plans/jobs-merge-design.md`（t4 设计，**本轮未实施**）
> - 锚点：每条 `CM-<菜单 id>` 回指 `docs/code-map.md` §4.1；两边对不上时以**库内实况**为准并当场改文档
> - 读数：本地库 `edu19`，只读 SELECT，采集 **2026-09-17**；复核命令见 §1（**已逐条实跑**）

---

## 0. 三态口径（先看这条，否则会把"隐藏"当"删除"）

| 状态 | 库内形态 | 用户感受 | 本台账里怎么标 |
|---|---|---|---|
| **在用** | 记录存在 + 入口可达 | 能点、能用 | 不进本台账 |
| **隐藏**（本轮全部） | 记录**仍在**：`active=False` 或 `group_ids=[仅超管]` | 该角色看不到；超管仍可见、可一键恢复 | 「何时可彻底删除」= **无计划（NULL）** + 前置条件 |
| **已删除** | 记录不存在 | 不可恢复（除备份） | **2026-09-17 那一轮 = 0 条**；**2026-09-29 起 = 1 条真删除**（`edu_eval` 行政评估，用户授权，证据 `docs/audit/edu-eval-removal.md`）——凡真删除必须附删除证据与还原路径，本条即范式 |

> ⚠ 三件事不能混为一谈：**"入口隐藏" ≠ "实现弃用" ≠ "可以删表"**。
> 例：`/my/checkin` 是**兼容层**（303 重定向，实现必须留着）；`edu.daily.checkin` 表是**只读化石**（无读无写）——
> 两者可以分开删，**不要绑在一起**。

### 0.1 ⚠ 同名不同物：生产上跑着的 `edu_telegram` **不是**本台账里的 `edu_telegram`

| | **生产**（马来西亚 edu19） | **本仓**（`custom_addons/edu_telegram`） |
|---|---|---|
| 是什么 | **匿名意见收集机器人**（学生私聊吐槽 → 教务看汇总） | 「Edu Telegram Bot」**v2.2 四角色教务前端** |
| 模型 | `edu.feedback` / `edu.feedback.session` / `edu.telegram.outbox` | `op.telegram.chat` / `edu.telegram.binding` / `edu.telegram.outbox`（**表名也同名**）/ `edu.telegram.flow` / `edu.telegram.push` |
| 系统参数 | `edu_telegram.*` | `edu_telegram.*`（**同名**） |
| webhook 路由 | `/telegram/webhook` | `/telegram/webhook`（**同名**） |
| 部署状态 | **在跑**（P0 已上线） | **从未部署**；2026-09-17 用户裁定**退役** |

三条必须记住的后果：
1. **匿名红线（不可逆）**：意见箱的匿名性建立在「不保存明文 chat_id、只存 HMAC 指纹」上。
   任何把两个模块的 chat_id **并表 / join / 并排导出**的动作都会作废学校对学生的匿名承诺，且无法撤回。
2. **路由冲突**：两边都声明 `/telegram/webhook` ⇒ 把本仓 v2.2 部署上去会与生产意见箱抢同一个路由
   （Odoo 同名 `@http.route` 的 leaf 归属随加载顺序漂移）。
3. **参数撞名**：两边都用 `edu_telegram.*` ⇒ 同一个 key 被两套语义读，改一处会波及另一处。

> 因此 **B8 只说本仓 v2.2**；**不要**据此去动生产那个模块的任何一行（那是独立决策，不在本任务范围）。
> 另外，「学生私聊领注册码机器人」是本项目里的**第三个东西**：模块 `edu_tg_bind`，
> 路由 `/telegram/tgb/webhook`，参数 `edu_tg_bind.*`，设计见 `docs/plans/tg-invite-bot-design.md`。

### 未来删除的**最低门槛**（下表每条都引用这套编号，编号不要改写）

| 编号 | 条件 | 怎么验（可执行） |
|---|---|---|
| **C1** 归档 | 删除前已导出可还原的归档 | `docker compose exec -T db pg_dump -U odoo -t <表> edu19 > /tmp/<表>.sql`，`wc -l` 留证（或 `\copy <表> to '/tmp/<表>.csv' csv header`） |
| **C2** 零写入 | 自本台账登记日（2026-09-17）起**连续 30 天**无 INSERT/UPDATE | 读**状态表**（不是统计表）：`select count(*), max(create_date), max(write_date) from <表>;`——口径与理由见 `docs/dev-workflow.md` 判据强度第 5 条（量具不许有副作用） |
| **C3** 零引用 | 没有模型/视图/模板/脚本/文档仍**活读书写**它 | `grep -rn "<模型名或表名>" --include="*.py" --include="*.xml" custom_addons/ scripts/ tests/` → 命中逐条判定「活路径 / 注释 / 历史文档」；**报"不存在"必须写明扫了哪些范围** |
| **C4** 回滚不依赖 | 任何 `--rollback` 分支都不再回写它 | `ls scripts/migrations/` + 逐个读 `--rollback` 分支（口径：**所有**分支都不再指向它） |
| **C5** 断言已改强 | 冒烟/路由矩阵对旧入口的断言已从"跟随后 200"改成"303 + Location 精确" | 跑对应断言文件全绿，且 grep 到的旧断言不再是追随重定向的口径 |
| **C6** 独立验证 | 独立验证（t7 一类）通过：重复入口消失、数据一致、四角色权限无回归 | `python3 tests/audit/verify_consolidation.py --phase after` → `verdict` 全 PASS |
| **C7** 分步 + 观察窗 | 先删路由/ACL → 观察一个工作周期 → 再删表/模型；**禁止一步 drop** | 每步一个独立 commit；观察窗内无 404/500 报障 |

---

## 1. 怎么复核（命令逐条实跑；**读者可原样复现**）

```bash
# ① 全库菜单计数：605 条记录未增未删（只改了开关）
docker compose exec -T db psql -U odoo -d edu19 -c \
  "select count(*) total, count(*) filter (where active) active, count(*) filter (where not active) inactive from ir_ui_menu;"
# → 605 / 405 / 200（2026-09-17 实测）

# ② 根菜单：40 条，其中 active 14、inactive 26
docker compose exec -T db psql -U odoo -d edu19 -c \
  "select id, active, name->>'zh_CN' nm from ir_ui_menu where parent_id is null order by id;"

# ③ 逐表条数（"没丢数据"的唯一证据）
docker compose exec -T db psql -U odoo -d edu19 -c \
  'select '"'"'edu.daily.checkin'"'"' t, count(*) n from edu_daily_checkin
   union all select '"'"'edu.checkin.record'"'"', count(*) from edu_checkin_record
   union all select '"'"'edu.alumni.job'"'"', count(*) from edu_alumni_job
   union all select '"'"'edu.admin.eval.template'"'"', count(*) from edu_admin_eval_template
   union all select '"'"'edu.job.application'"'"', count(*) from edu_job_application;'
# 说明：上式为 shell 单引号包含 SQL 的写法（'"'"' 即"结束单引号 + 双引号单引号 + 重开单引号"）；
# 也可直接把 SQL 存成文件后用 -f 传入，避免引号嵌套。
# → 7 / 53 / 3 / 0 / 26（2026-09-17 实测；注意 job.application 已从 t1 基线 25 变 26，见 §7-3）
# ⑤ 任何**新库 / 模块重装**后，检查「到堂打卡」类型是否还在（见 §5 待固化项）：
# docker compose exec -T db psql -U odoo -d edu19 -c \
#   "select id, name from edu_checkin_type order by id;"   # 应含 id=5 到堂打卡；没有就补跑：
# python3 scripts/merge_checkins.py --dry-run && python3 scripts/merge_checkins.py --apply

# ④ 登记日（C2 的"连续 30 天"以此起算）
date +%F    # → 2026-09-17
```

> 采集时刻：**2026-09-17**。本仓正在做菜单收口的修复（F1，见 §6），上表 ② 的 active 数会随修复推进变化 ⇒
> **引用必须带采集时刻**；`605`（全库）与 `40`（根）这两个**记录总数**不受影响（红线：零删除）。

---

## 2. 台账 A：被隐藏的根菜单（27 条登记：15 合并 + 11 本轮隐藏 + 1 收口前既有）

> 口径关系：库内 `inactive` 根菜单 **26 条** = 15 合并 + 11 本轮隐藏；另有 **1 条**（434）收口前就已停用、
> 不属于本轮处置，为对账一并登记 ⇒ **本台账登记 27 条**。全库 inactive 菜单 **200 条**（含上述根的子树）。

统一四栏：**保留原因 / 替代路径 / 何时可彻底删除 / 删除前置条件**。全部条目**本轮只隐藏，记录一行未删**。

### A1. 合并类（15 条：本根 `active=False`，子树迁入容器）

> **保留原因（15 条共通）**：① 零删除红线；② 这些根的 xmlid 声明在各自模块 XML 里——直接删，
> 下一次 `-u` 会把它们**重新创建**（"删了又回来"）；③ 子树承载着仍在用的业务（见替代路径列）。
> **替代路径**：见下表。**何时可彻底删除**：**无计划（NULL）**。
> **删除前置条件**：C1–C7 **且**先把声明来源（对应模块 XML 的 `<menuitem>`）一起改掉，否则升级复活。

| 锚点 | 菜单 id | 名称 | 替代路径（现在从哪走） | 该子树里仍在用的东西 |
|---|---|---|---|---|
| `CM-278` | 278 | 学生 | → 257 学生信息 | `op.student` 唯一后台根（子项 258 学生 = `op.student`） |
| `CM-542` | 542 | 邀请码 | → 257 学生信息 | `edu.invite.code` |
| `CM-606` | 606 | 老账号补挂身份 | → 257 学生信息 | 身份重绑（`/my/contacts` 配套） |
| `CM-591` | 591 | 招生报名 | → 300 招生 | `edu.application` 6 条、报名表设置 |
| `CM-349` | 349 | 课堂考勤 | → 341 时间表 | `op.attendance`（47 张点名表，**在用**） |
| `CM-288` | 288 | 作业 | → 341 时间表 | `op.assignment` |
| `CM-325` | 325 | 考试 | → 341 时间表 | `op.exam` / `op.result.line` |
| `CM-576` | 576 | 在线课程 | → 341 时间表 | `edu.lesson` 8 条（**在用**） |
| `CM-504` | 504 | 测验 | → 341 时间表 | `edu.quiz` 1 条；原生 `slide.channel`=0 |
| `CM-543` | 543 | 日常管理 | → 593 灵命生活 | 其子项 544 全员打卡 / 545 积分流水 / 546 教师积分排行 = 打卡 B 套的旧后台入口 |
| `CM-597` | 597 | 行政评估 | ~~→ 588 综合评估~~ **已随模块删除** | `edu.admin.eval.*` 三模型 **2026-09-29 已卸载删除**（菜单 597–600 一并消失；见 §3 B2/B3 与 `docs/audit/edu-eval-removal.md`） |
| `CM-83` | 83 | 讨论 | → 218 网站 | `mail` 讨论频道 |
| `CM-357` | 357 | 日历 | → 218 网站 | 原生 calendar |
| `CM-372` | 372 | 活动 | → 218 网站 | 原生 event |
| `CM-507` | 507 | 在线聊天 | → 218 网站 | `im_livechat` |

> ⚠ **这 15 棵里有 5 棵（542 / 543 / 576 / 597 / 606）是 F1 的"重放源"**：它们的 `active/groups` 在
> `edu_portal` / `edu_eval` 自己的 XML 里有声明 ⇒ `-u edu_portal` 会把 `active` 写回 `True`
> （实测 backoffice 12 → 17）。**动它们之前必须先修 F1**，否则删了也会被重放回来。

### A2. 本轮隐藏（整棵停用或仅超管）——11 条 + 1 条收口前既有

> **保留原因共通**：① 零删除红线；② 它们是 **Odoo 原生应用**的菜单（`base` / `hr` / `website_slides` /
> `data_recycle` / `mail` 等），删了会破坏原生菜单树结构，且升级必然重建；③ 处置目标是"不给非超管看"，
> 不是"从产品里去掉"。
> **何时可彻底删除**：**无计划（NULL）**——这些不该由本仓删。
> **删除前置条件**：**C1–C7 不适用**；若要真去掉，正确抓手是**卸载对应原生模块**（独立决策，须校长/队长拍板）。

| 锚点 | 菜单 id | 名称 | 隐藏理由（实测数据） | 现在从哪走 |
|---|---|---|---|---|
| `CM-16` | 16 | 测试 | 原生 Odoo 测试菜单，无业务数据 | 无（超管可用） |
| `CM-75` | 75 | 链接追踪器 | 原生营销工具，教务不用 | 无 |
| `CM-214` | 214 | 仪表板 | 原生仪表板，教务不用 | 无 |
| `CM-388` | 388 | 招聘（HR） | `hr.job` = **0**（自研 `edu.job.posting` 2 条在用） | 585 招聘管理 |
| `CM-529` | 529 | 出勤（HR） | `hr.attendance` = **0**（课堂考勤走 `op.attendance`） | 341 时间表 |
| `CM-547` | 547 | 在线学习（slide） | `slide.channel` = **0**（自研 `edu.lesson` 8 条在用） | 341 时间表 |
| `CM-121` | 121 | 联系人 | 原生通讯录；`res_partner` 多为系统伙伴 | 超管可用 |
| `CM-142` | 142 | 发票 | `account.move` = **0**（自研财务在 579） | 579 财务管理 |
| `CM-566` | 566 | 数据清除 | 原生破坏性工具（`data_recycle`） | 超管可用 |

> **另有 3 条不是"整棵停用"而是"仅超管"**（记录仍 active，根 + 全部子树挂 `base.group_system`）：
> `CM-1` 设置、`CM-15` 应用、`CM-196` 员工（`hr.employee` 有 2 条真实数据）。
> 它们**不属于被隐藏的 26 条 inactive 根**，但同样"不该删"：删除前置条件同 A2（原生模块的事）。
> 计数关系：26 条 inactive 根 = A1 的 15 + A2 的 9 + A3 的 2。

> **收口前就已停用、不在本轮处置内的 1 条**（登记只为对账）：

| 锚点 | 菜单 id | 名称 | 事实 | 处置 |
|---|---|---|---|---|
| `CM-434` | 434 | 销售 | 收口前即 `active=False`（`sale_order`=0） | **保持停用**（本轮未动其开关） |

### A4. 子树（批量，逐个由根决定）

- 库内 `inactive` 菜单共 **200** 条（= 上面各根 + 它们的子树）。逐条字段级改动（哪些"停用"、
  哪些"改父菜单"、哪些"改组"）见 `docs/audit/menu-consolidation/diff-report.md` §3（129 条字段改动清单）。
- 处置：**全部保留，子树不单独设删除计划**——它们的生命周期跟随其根（根不删、子树不删）。
- 前置条件：将来若删某个根，其子树的 C1–C7 一并适用，**且必须与根同批、同 commit、同回滚点**。

---

## 3. 台账 B：被弃用的模型（保留但停写 / 冻结退役）

> 口径：**表、模型、ACL、ir.rule 全保留**。「何时可彻底删除」只对**真停写停读**的写"可评估"；
> 对**仍被门户读取**或**设计未实施**的写"未退役，无删除计划"——避免把还能用的东西写进删除队列。

| 编号 | 模型（表） | 现状读数（2026-09-17） | 保留原因 | 替代路径 | 何时可彻底删除 | 删除前置条件 |
|---|---|---|---|---|---|---|
| **B1** | `edu.daily.checkin`（`edu_daily_checkin`） | **7 条**，id `1,2,4,5,6,7,8`；**无读入口、无写入口**（`/my/checkin/save` 已 303，board 已换源） | t5 只迁移不删（零删除红线）；7 条历史事实已并入 `edu.checkin.record` | `edu.checkin.record` + `edu.checkin.type`「到堂打卡」（`edu_life`） | **可评估**（当前无读写方；这是台账里唯一一条可进入删除评估的） | **C1–C7 全满足** + 队长书面确认「`/my/checkin*` 的 303 是永久兼容层还是可下线」（永久兼容层⇒旧表可先删，重定向不依赖它）+ `scripts/merge_checkins.py` 的 `--rollback`（C4）不再回写它 |
| ~~**B2**~~ | ~~`edu.admin.eval.template`~~ | **2026-09-29 表已删除**（卸载时 DROP）。删前读数：本地 0 条 / 生产 0 条（`max(create_date)` 为空） | 用户 2026-09-29 授权删除（原话「行政评估可以删了，完全没有人用过，你删吧」） | **新引擎 `edu_assess`（`edu.assess.*`）**；学生门户入口 = `/assess/my` | **已删除（2026-09-29）** | 已完成；前置证据 = `docs/audit/edu-eval-removal.md`（J1–J5 判据 + 生产备份 `/root/pre_deleval_20260929_1545.gz`）。⚠ 本条**不再**引用已作废的 `docs/plans/eval-merge-design.md`（它的前提「A 套有存量」已被生产读数推翻） |
| ~~**B3**~~ | ~~`edu.admin.eval.item` / `edu.admin.eval.score`~~ | **2026-09-29 表已删除**（卸载时 DROP）。删前：本地 0/0、生产 0/0 | 同 B2（三件套同批处置，已执行） | `edu.assess.item` / `edu.assess.score`（`edu_assess`） | **已删除（2026-09-29）** | 同 B2 |
| **B4** | `edu.alumni.job`（`edu_alumni_job`） | **3 条**，id `1,2,3`；最近写入 2026-08-22 12:19:25；**`/alumni/jobs` 仍在读它** | t4 设计：以 `edu.job.posting` + `audience` 吸收；**本轮未实施**；表内是历史真实数据（非演示） | `edu.job.posting`（2 条在用）——**尚未合并过去** | **未退役**（今天仍是公开页的唯一数据源） | 先实施 `docs/plans/jobs-merge-design.md`；实施后按 C1–C7，且删前必须逐字段核对 3 行已在新表可查 |
| **B5** | `edu_checkin_type` id=**4** 缺号 | 现有 id `1 读经 / 2 灵修 / 3 周记 / 5 到堂` | 缺号本身无害；**不要为"补连续"去重建 id=4**（可能撞历史引用） | —— | **不适用** | 仅当"谁取走了 4"被查明才谈；本轮**未核**（见 §6 T-02） |
| **B6** | `hr.job` / `hr.attendance` / `slide.channel` / `sale.order` / `account.move` | 全 **0 条** | 原生模块自带表；删表会破坏原生数据模型 | 自研对应实现（见 §2 A2 的"现在从哪走"列） | **无计划**（不归本仓删） | 若要清理，正确抓手是**卸载原生模块**（独立决策、须拍板） |
| **B7** | 三套「已读」：`edu.alert.read`(2) / `edu.notice.read`(16) / `edu.download.ack`(0) | 三套并存、各写各的 | t1 §1.7 登记为**技术债**，本轮明确不合并 | 未定 | **无计划** | 见 §6 T-01 的唤醒条件（机会型：任何一次动"已读/提醒"时顺路收口） |
| **B8** | **本仓 v2.2 全套**（`custom_addons/edu_telegram`）：`op.telegram.chat` / `edu.telegram.binding` / `edu.telegram.outbox` / `edu.telegram.flow` / `edu.telegram.push` | 本地库 **9 / 5 / 180 / 0 /（push 表不存在）** 条 —— **⚠ 2026-10-03 复核：outbox 仍在被写**：台账登记日（2026-09-17）时 117 条、今天 180 条 ⇒ **+63 = 21 天 × 3 条/天**，与「每小时 cron」完全吻合；写入者 = **本模块自己的两个定时任务**（`ir_cron` id **25** 每日推送、id **33** 公告推送每小时，均 `active=t`）⇒ 演示数据之外**它在持续自增**。模块**本地已装**（19.0.2.2）、**生产从未部署** | 「Edu Telegram Bot」v2.2 四角色教务前端；用户 2026-09-17 裁定**退役**；零删除红线（本轮**只登记，不删文件、不改代码**） | **无替代**（该功能不再做）。注意：「学生私聊领注册码」是**另一件事** ⇒ 走新模块 `edu_tg_bind`（`docs/plans/tg-invite-bot-design.md`），与本模块**无代码/数据关系** | ~~**可评估**~~ ⇒ **⚠ 2026-10-03 复核：暂不可评估** —— 它的**每小时 cron 仍在往 `edu_telegram_outbox` 写** （实测每天 3 条），**C2「连续 30 天无写入」结构上不可能满足**。要进入删除评估，**先停这两个 cron** （`ir_cron` 25 / 33），再重新起算 30 天。（从未部署 ⇒ 生产无存量数据这一点不变） | **C1–C7 全满足** + 队长书面确认「v2.2 永不部署」+ 确认本仓 v2.2 的 `/telegram/webhook` 永不出现在生产（与意见箱**撞路由**，见 §0.1）+ `scripts/telegram_relay.py` 一并处置（它认领 `edu_telegram_outbox`，且只认单个 `TG_TOKEN`） |

### B9（2026-10-04 第 99 轮新登记）：两个**没有任何引用的 QWeb 模板**

新立 `scripts/find_dead_templates.py`（报告型）扫全仓：**180 个 QWeb 模板里，2 个没有任何引用**。

| 模板 xmlid | 位置 | 判断依据 |
|---|---|---|
| `edu_brand.homepage_yongyue` | `custom_addons/edu_brand/views/brand_templates.xml:6` | 全仓 grep 只有定义行本身；没有 `t-call`、没有 `request.render`、没有继承、也没有 `website.page` 引用它 |
| `edu_portal.edu_welfare_checkin` | `custom_addons/edu_portal/views/welfare.xml:9` | 同上。它自己的注释写着「门户：`/my/checkin` 学生每日打卡」，而那条路由**已退役**（`/my/checkin/save` 已 303、board 已换源，见 §0.3 与 t5 记录）⇒ 属于退役页面的残留 |

**本轮的处置 = 只登记，不删**（沿用本台账一贯口径）。
删除门槛比 B1/B8 更低（它们**没有任何渲染入口**，不存在「删了用户看到 404」的问题），
但仍建议走 C1–C7：C1 归档（模板就是文件本身，git 历史即归档）、C3 零引用（本轮已扫）、
C5/C6 跑一遍门禁与独立验证。**唤醒条件**：下一次做「去冗余」批次时一并处理。

**工具的三次收窄（都靠手读样本纠偏，值得记）**：首跑报 254 个 ⇒ 手读发现「带 `inherit_id` 的
继承视图**存在即生效**，不需要引用」⇒ 收窄到 221；再手读发现「`ir.rule`/`ir.cron`/费用分类这类
`<record>` **存在即生效**」⇒ 收窄到 102；再手读发现「后台 `ir.ui.view` 按**模型+类型**自动挑选，
**不需要 xmlid 引用**」⇒ 收窄到 **2**。三次都是**先看样本再改判据**，不是拍脑袋放宽。

---

## 4. 台账 C：URL 级兼容层（旧地址不 404 ⇒ **实现必须留着**）

> 这类条目的"替代路径"就是它自己（重定向目标）；**它们不该被当作"可删除项"**——删掉重定向 = 用户书签 404。
> 登记在此的目的正是：防止下一个人把重定向当死代码清理掉。

| 编号 | 旧地址 | 现状（2026-09-17 实测） | 重定向到 | 保留原因 | 何时可彻底删除 | 删除前置条件 |
|---|---|---|---|---|---|---|
| **C-01** | `/my/checkin` | **303** | `/my/checkins` | 学生卡片/书签历史指向；本轮裁定"保留兼容层" | **无计划** | 仅当队长裁定"兼容层可下线"：连同 C5 的测试断言一起删（t5 报告 §10.2 列了 4 处待改断言） |
| **C-02** | `/my/checkin/export` | **303** | `/my/checkins/export` | 同上（导出链接曾被多处引用） | **无计划** | 同上 |
| **C-03** | `/my/checkin/save`（GET+POST） | **303** | `/my/checkins` | **旧写路由**：不再解析表单、不再落库（旧表零增长） | **无计划** | 同上；删前确认"旧表行数不变"的断言仍在（t5 拟新增 `tests/smoke/attack_checkin_replay.py`，**该文件尚未落地 = t9 待办**） |
| **C-04** | `/my/checkin/board` | **200**（保留功能，**不是**兼容层） | ——（数据源已换 `edu.checkin.record`+到堂） | 教师/教务的全员到堂看板仍在使用 | **无计划** | 学生访问会 303 → `/my/checkins`；改动它须同步 `tests/audit/verify_consolidation.py` 的 `checkin_board_200` 判据 |
| **C-05** | `/eval/my`、`/eval/review`、`/eval/review/<id>`、`/eval/fill/<id>`、`/eval/fill/<id>/save` | 仍 **200** | **未重定向**（设计已定、实施未做） | B 套引擎冻结退役但仍在用；t4 设计要把它们 303 到 `/my/evaluation*` | **未退役** | 先实施 `docs/plans/eval-merge-design.md` §6。**文档不得写成"已重定向"** |
| **C-06** | `/alumni/jobs`、`/alumni/job/list` | 仍 **200** | **未重定向** | 仍读 `edu.alumni.job`（3 条） | **未退役** | 先实施 `docs/plans/jobs-merge-design.md` §6.1 |
| **C-07** | `/alumni/job/card` | 仍 **200** | **未重定向** | 设计要把它改 303 → `/alumni/jobs`（今天它渲染的是**校园岗位**，名实不符） | **未退役** | 同 C-06；改完须同步 `tests/smoke/D_public.md`（第 15 行断言 200）与 `D_public.py:25` 的口径 |

### 4.1 孤儿页与「有意双声明」（**登记不删**；2026-10-02 由去冗余普查登记）

> 这几条都**不是弃用件**。登记在此的唯一目的：**防止后人拿 grep 的「0 入链」当删除依据**。

> **C-10 是怎么被发现的（方法可复用）**：模板里被引用的变量，若**全仓没有任何 `.py`/`.js` 提供过、
> 也没在 XML 里 `t-set`/`t-as` 定义过**，那这个变量就是孤儿；而**同一个模板里成片出现孤儿变量**，
> 通常意味着**整个模板都没被渲染过**。当时的读数是「值表达式 1106 个标识符 → 36 个无来源」，
> 其中 `today_rec`/`recents`/`bible_streak`/`devotion_streak`/`month_attend`/`month_days`/`m_last`
> 等一批**全部落在 `edu_welfare_checkin` 这一个模板内** ⇒ 顺着这条线定位到它 0 引用。
> 复算工具：[scripts/find_orphan_template_vars.py](../../../scripts/find_orphan_template_vars.py)（**报告型，不是门禁**，
> 已知假阳性类别见该脚本头部）。
> 详细取证见 [docs/audit/redundancy/inventory.md](redundancy/inventory.md) §4.3 / §4.5 与 §8 的 F4 / F7。

| 编号 | 对象 | 现状（2026-10-02 实测） | 为什么现在不能删 |
|---|---|---|---|
| **C-08** | `/student/subjects`、`/my/points/me` | **可达**（带登录态探针 200），但**代码入链 0 次**，`website.menu` 表里也没有入口 | 「0 代码入链」≠「死」：入口可能由卡片引擎按 key 拼出、或本就是给下一步挂载留的页。普查已逐条追过入口来源，**判不出「死」** ⇒ 下线须先由队长确认产品意图，并按 C1–C7 门槛走 |
| **C-10** | `edu_portal/views/welfare.xml` 的 `edu_welfare_checkin` 模板（**197 行**，第 9–205 行） | **全仓 0 处引用**（除自身声明）：无 `request.render`、无 `t-call`、无菜单入口。对照：同文件另三个模板（`edu_welfare_board` / `_points_give` / `_points_me`）都有控制器在渲染 | **不是「没写完」，是「被取代」**：code-map §4 已写明「**edu_life = 唯一打卡实现**」（走 `edu.checkin.record` + 「到堂打卡」类型），本条是**旧门户打卡**那一版。
**已实测「没有坏页面」**（2026-10-02）：它原来的入口全部改成了**兼容重定向**，学生身份实测 ——
`/my/checkin` → **303** → `/my/checkins`、`/my/checkin/save` → **303** → `/my/checkins`、
`/my/checkin/board` → **303** → `/my/checkins`（看板本身限 `base.group_user`，学生被转走）。
⇒ 说明**迁移是做完的**，模板只是**迁移后没清掉的壳**，对用户零影响。
（注意这不等于「可以删」：本仓对用户可见的弃用件仍按登记制走。）**不删**的理由有两条：① 本仓对弃用件一律**登记不删**；② 删模板属产品裁定，且要一并确认没有外部书签/邮件直达这个入口 |
| **C-11** | `edu_portal/views/study.xml` 的 `edu_home_timeline` 里两段区块（第 360–374 行，以 `course_cards` / `quick_cards` 为条件） | 模板**本身是活的**（`/my/home` 正常渲染），但这两段区块的变量**全仓无来源** ⇒ `t-if` 恒假 ⇒ **从未渲染**（实测 `ux3-row` / `ux3-quick-item` 在 `/my/home` 与 `/my/study` 的 HTML 里出现 **0 次**） | 三件东西各自存在却从未连起来：helper（`_course_cards`/`_quick_cards`，已在 2026-10-02 作为死代码删除）→ 模板区块（等变量）→ 控制器（从不传变量）。归档日志显示它们本是「首页瘦身手段之一/之二」，而 `/my/home` 后来改成了 Timeline 工作台 ⇒ **改版换掉的那一版遗留**。**不删**：万一产品要把「我的课程」卡片做回来，这是现成的版式 |
| **C-13** | **35 个「模板在用、本仓样式里没有」的自有类名**（`oe-gb-*` 11 个、`oe-cal-*` 6 个、`oe-study-page`、`oe-kpi--*`、`oe-skillassess`、`oe-home-blocks`、`ux-approval-alerts` 等） | 它们出现在模板 `class=` 里，但在 `custom_addons/**/static/**` 的 `.css/.scss/.js` 里**一次都没出现**（工具同时扫 JS，所以**不是** JS 钩子）。逐条核对过 7 个代表：确认零定义 | 来历可考：`batch2.xml:4` 的注释自己写着「/grade-book 成绩簿（**对齐 `oe-gb-page` DOM**）」—— 即照**旧站**的 DOM 抄了类名、指望旧站样式表生效，而那张表**从未进入本仓**。**实测页面并不难看**（`/grade-book` 1440 截图：统计盒、学期卡、表格俱在，靠 Bootstrap 的 `d-flex/card/badge` 撑住），故**登记不删**；删了没有用户可见收益、还会断掉「将来补旧站样式」的路。检测器＝新增报告型工具 `scripts/find_undefined_classes.py` |

**2026-10-03 逐类分诊结论（35 条**全部看过，**没有一条要改**）**：

| 类 | 判定 | 依据 |
|---|---|---|
| `oe-gb-*`（11） | 旧站 DOM 遗留，**页面不难看** | `/grade-book` 1440 截图：统计盒/学期卡/表格俱在，靠 Bootstrap 撑住 |
| `oe-cal-*`（6）、`oe-study-page`、`oe-home-blocks` 等 | 装饰性遗留 | 对应页面（`/my/calendar`、`/my/study`、`/my/home`）实看正常 |
| `oe-asg-btn--active`（2） | **不是缺陷 —— 是「标记类」** | 基类 `.oe-asg-btn` 本身就是「选中态」外观（`background: var(--brand-action)`，见 `enterprise.css:685`），`--ghost` 才是被改写的那一个 ⇒ `--active` **不需要规则**。差点被我当成「缺样式」去补一条，那样反而会改动外观 |
| `oe-kpi--assign` / `--exam` | 变体未写，无可见损失 | 基类 `.oe-kpi` 有 37 处样式；这两个变体只影响配色细分 |
| `oe-statbox-ic--warning`（**1 处**） | **疑似拼写错误**（同族 `--warn` 有 3 条规则、模板用了 10 次），但落在**冻结模板**里 | 该处位于 `evaluation.xml` 的 `edu_eval_center` —— 见下条，该页已被 303 兼容层接管、**用户看不到** |

**顺带查清一件事（后人不必再查）**：`/my/evaluation` 有**两条**路由声明 ——
`controllers/evaluation.py:31` 与 `controllers/eval_compat.py:24`。这**不是** C-09 那种「同名双声明」隐患，
而是 `eval_compat` **继承 `EduEvalPortal` 后覆写**的**有意接管**：Odoo 路由生成器只实例化最底层子类（leaf 覆盖），
归属确定、不随加载顺序漂移。该文件头写明「旧 7 条路由改 303…**先建后删是校长钉死的顺序**…
`evaluation.py` 的实现一行未删（**回滚 = 删本文件**）」。
⇒ 故 `edu_eval_center` 及其内的 `--warning` **按设计不可达**，改动它无收益。
（本仓 `check_view_xpath.py` **规则 5** 就是专拦「无意同名路由」的，本条属有意，不冲突。） |
| **C-12** | `/my-courses`（`edu_public/controllers/main.py:259` + `edu_public/views`） | 路由保留（`auth='user'`，实测 200）。**门户左导航里那条「课程」入口已删除**（2026-10-03）。⚠ **但它不是孤儿页 —— 仍有 ≥4 个入口**（下表） | 见下方「依据」与「入口清单」 |

**依据（不是我自己的判断，是本仓已上线的决定）**：`docs/plans/study-hub-v3-design.md` §6「零功能丢失对照」**第 15 行**（该文档状态行 = `已上线`）：

> `| 15 | my-courses | 课程 | 学业 | **/my/study 课程中心** | 主入口 |`

即**本仓 2026-09-26 就已决定这个入口的新落点是 `/my/study`**，只是左导航没照做（`batch2.py:834` 的注释也复述了这条决定）。
实测佐证：1440 下 `/my-courses` 用**公开站外壳**、无底部 Tab、正文只有 1 张课程卡、站内链接 24 个；
`/my/study` 是门户页、「报课→上课→资料→下载→成绩」+ 出勤 + 周课表、链接 46 个 ⇒ 前者**严格更差**。

**⚠ 更正我自己一处错**：本条最初写「已无入链（grep 0 处）」—— **那是错的**。
`grep` 只能看见 `views/*.xml` 里的字面链接，而 `/my-courses` 的其余入口**定义在控制器配置里**，grep 看不见。
真实入口清单（逐个实读）：

| # | 位置 | 形态 |
|---|---|---|
| 1 | `edu_portal/controllers/batch2.py:252` | 「全部应用」宫格卡片 `('my-courses', '课程', …)`，描述「提供多样化的课程，满足不同的学习需求」 |
| 2 | `edu_portal/controllers/main.py:206` | 另一份卡片配置 `{'href': '/my-courses', 'title': '课程 Courses'}` |
| 3 | `edu_portal/controllers/batch2.py:844` | `acad_hrefs` 学业组顺序表（**仅排序用**，不是跳转） |
| 4 | 公开站顶栏菜单「我的课程」 | 浏览器实测（`li.nav-item` in `#top_menu`，桌面 + 手机抽屉各一份）；**其定义位置尚未定位**（不在 `views/*.xml` 字面里，疑似 `website.menu`/`ir.ui.menu` 数据，psql 按名查未命中）—— 标「未定位」 |

**处置**：**不删路由**（`docs/plans/enroll-v2-design.md:59` 规划把它重建为学生「我的课程」学习中枢）。
入口 1/2 是否改指向 `/my/study`（照 §6 第 15 行）属产品口径，**留待裁定**；本次只动了左导航那一条。 |
| **C-09** | `/web/register` 同路径双声明 | 父类 `register.py` 的两条 `@http.route` 在**运行态注册表里 0 条**（被同名路径覆盖）；活的是别名类的壳；而**父类实现经 `super()` 仍在用** | ⚠ **别误删父类实现** —— 它在 `super()` 链上。这不是冗余，是「同名路径 + 模板方法」；要动它必须先补一条父子调用断言 |

---

### 4.2 「登录」入口对已登录用户仍显示 —— 实测定位 + **有意不修**（2026-10-02）

现象：已登录用户在**公开页**（含首页 `/`）看到的 `/login` 链接共 **4 处**（逐条实测）：

| # | 位置 | 桌面 | 手机 | 文案 |
|---|---|---|---|---|
| 1 | 顶栏菜单项（`LI.nav-item` in `NAV.navbar` 的 `top_menu`） | 可见 | 折叠进汉堡菜单 | 登录 |
| 2 | 同上，手机抽屉里那一份 | 隐藏 | 展开后可见 | 登录 |
| 3 | 首页区块卡片（`SECTION.yylc-section` → `DIV.col-12 col-md-6 col-lg-4`） | 可见 | 可见 | 进入系统 |
| 4 | 首页 hero 行动区（`SECTION.yylc-contact` → `DIV.yylc-hero-actions`） | 可见 | 可见 | 进入教务系统 |

**危害等级：低**，且功能是**对的** —— 实测点任意一条都是 **303 → `/my/home`（200）**，
即已登录用户不会被卡在登录页。问题只在**标签过期**（还写着「登录」）。

**为什么不修**：#1/#2 来自核心 `portal.user_sign_in`（见 `edu_brand/views/odoo_debrand.xml:102` 的注释），
而要用一行 CSS 隐掉它需要一个「已登录」锚点 —— 实测 **匿名与登录态的 `<body>` 标签完全一样（都是裸 `<body>`）**，
**没有可用锚点** ⇒ 得先加一个 body class 标记，再写 CSS。
对一个「点了也能到对的地方」的标签来说，这个代价不划算。

**唤醒条件**：若将来动公开页页头（例如做「登录后页头」的统一改造），把这条一并处理；
届时锚点可顺手加上（`edu_brand` 里对 `<body>` 做一次 `position="attributes"`）。

## 5. 待固化项（下一轮要做完的事；**固化前有新库/重装的操作前置条件**）

> 与「可删除」相对：这一节记的是**当前还靠外部脚本/手工维持**的东西——它们不是弃用件，
> 而是「**换了环境就会少一块功能**」的隐患。每条都写：现状 / 证据 / 少了会怎样 / 固化方案 / 固化前必须做什么。

| 编号 | 对象 | 现状 | 证据（实测） | 少了会怎样 |
|---|---|---|---|---|
| **P-01** | `edu.checkin.type` 的「**到堂打卡**」类型（id=5） | ~~只由迁移脚本 get-or-create 产生，不在模块 data 里~~ **✅ 已关闭（2026-10-04 实测）**：`edu_life/data/demo_life.xml:36` 已有 `<function model="edu.checkin.type" name="_ensure_attend_checkin_type"/>`，且该文件在 manifest 的 **data**（非 demo）里 ⇒ 每次安装自动 get-or-create。全新库实测：`edu_checkin_type` = 1 读经打卡 / 2 灵修打卡 / 3 周记 / **4 到堂打卡**，无需任何脚本。原状态列 | `scripts/merge_checkins.py`（t5，commit `7e67a0a`）；库内 id `1 读经 / 2 灵修 / 3 周记 / 5 到堂` | 到堂类型不存在 ⇒ 教师 `/checkins/stats` 的「到堂列」消失、学生端到堂打卡卡消失、`/my/checkin/board` 退化（不报错，**静默少功能**） |

- **固化方案（下一轮）**：把「到堂打卡」写成 `edu_life` 的 `data/` 记录（照 `seed_*` 幂等写法），
  让 `-u edu_life` 天生保证它存在；随后 P-01 关闭（那时本行下移到 §8 变更记录）。
- **固化前（硬前置）**：**任何新库 / 模块重装 / 从零部署，都必须补跑一次**
  ```bash
  python3 scripts/merge_checkins.py --dry-run   # 看它会不会建「到堂」类型
  python3 scripts/merge_checkins.py --apply
  ```
  （该脚本对已存在类型是 get-or-create、对已迁移记录是幂等，可安全复跑。）
- **核验命令**（两条都要过）：
  ```bash
  docker compose exec -T db psql -U odoo -d edu19 -c \
    "select id, name from edu_checkin_type order by id;"           # 必须含 5|到堂打卡
  curl -s -o /dev/null -w '%{http_code}\n' -b <教师 cookie> http://127.0.0.1:8069/checkins/stats
  ```
- **反例（不许当证据）**：只跑 `bash scripts/safe_upgrade.sh -u edu_life` **不会**建这个类型——
  脚本不在模块里，`-u` 与它无关；"升级成功"与"到堂类型在"是两件事。

---

## 6. 未关闭项与「明确不做」（**不做也要有唤醒条件**，否则它不是决定、是遗忘）

| 编号 | 事项 | 状态 | 唤醒条件（可观察、可判定） |
|---|---|---|---|
| **F1** | `-u edu_portal` 等模块升级后**重放菜单收口值**（backoffice 12 → 17，独立验证的唯一失败项） | **未关闭**，**已开 t11 修复** | **里程碑型**：修复后跑 `python3 tests/audit/verify_upgrade_persistence.py --modules edu_portal,edu_life,edu_eval --restore`，`verdict` 全 PASS + `verify_consolidation.py --phase after` 复跑一致。详见 `docs/audit/finding-F1-menu-replay-on-upgrade.md`、`docs/audit/consolidation-verification.md` §6 |
| **T-01** | 三套「已读」机制（`edu.alert.read` / `edu.notice.read` / `edu.download.ack`）不合并 | **明确不做**（本轮） | **机会型**：任何一次任务本来就要动"已读/提醒"功能时顺路收口（t1 §1.7） |
| **T-02** | `edu_checkin_type` id=4 缺号 | **未核**（不追） | **事件型**：若出现第二个"到堂打卡"类型、或类型统计对不上时再查 |
| **T-03** | 9 条来源不明 → 已归因（t2 的 `-u edu_life` 触发演示加载器）；id 53–61 **保留未删** | 已归因、**不删** | **机会型**：若队长决定清理，走 `scripts/cleanup_demo_data.py --include-linked-data`，由**非 t5** 执行并留证 |
| **F5** | `edu_life/data/demo_life.xml` 的 `<function …_load_demo_records/>` **非幂等**：按滚动窗口（读经近 7 天 / 灵修到昨天）每次 `-u edu_life` 再补一批演示打卡 | **t12 正在修成幂等**（verifier 独立发现并复核） | 已被第 0 步闸门 ④ 收编为**开工前检查项**，并在「已知陷阱」立了「计数前先确认最近有没有跑过 `-u edu_life`」。详见 `docs/audit/finding-F5-edulife-demo-injection.md` |
| **T-04** | 生产库（edu.example.org）现状未核对 | **未核**（本轮禁止碰生产） | **里程碑型**：上线前做一次环境比对（`scripts/check_prod_menus.py`）。~~⚠ 上线前同时执行 §5 P-01 的补跑（新库/重装硬前置）~~ **2026-10-04 更正：不必了** —— P-01 已实测关闭（到堂类型由模块 data 自动创建，见 §5 P-01 行）；**但上线前请改跑一次「全新库安装演练」**（第 65 轮正是靠它发现整条安装链是断的，见 `docs/audit/fresh-install-broken.md`） |

---

## 7. 已知的文档/实况不一致（登记给队长；**不在本任务内改**）

1. **F1 重放未关闭** ⇒ 任何引用"口径 B 数字"的文档与断言，在任何 `-u` 之后都可能失效。
2. **口径 B 存在两个版本**（都达标，但**不是同一口径**）：
   - `admin 18 / backoffice 12 / faculty 9`——档2 全部 `restrict_tree`，`48e74bd` 落库版（守卫脚本与队长 psql 三读一致）；
   - `admin 14 / backoffice 12 / faculty 9`——档2 混档 = **最终口径**（t2 落库 `682d3a1`），独立验证 `tests/audit/out/after_result.json`（2026-09-17 14:25:07）。
   `docs/code-map.md` §4.1 已显式标注"引用必须带采集时刻"。
3. **`edu_job_application` 计数 25 → 26**（t1 审计基线 25 → 本台账采集 26）：有一次真实投递发生。
   ⇒ 任何写死"25"的断言/文档应改成"≥25 / 以台账为准"。**这是数据在动，不是错误**。
4. **`/my/checkin/board` 的学生行为变了**：学生访问改为 303 → `/my/checkins`（收口前 303 → `/my/checkin`）；
   `tests/smoke/ux_v3_route_matrix.py:103` 的旧断言会变成假绿（t5 报告 §10.2 已列，交 t9）。
5. **t5 报告提到的 `tests/smoke/attack_checkin_replay.py` 尚未落地**（现文件名仍是 `tmp_t3_attack_http.py` 形态）
   ⇒ C-03 的"删除前置条件"引用的是**待办**，不是既有证据。
6. **写入期间本地库处于修复窗口**：`edu19-clone-web-1` 在 2026-09-17 14:24 前后重启、随后 t2 最终口径落库（`682d3a1`：admin 14 / backoffice 12 / faculty 9）并由 t7 出报告（`docs/audit/consolidation-verification.md`，⑥ 升级复现是唯一 FAIL 项 ⇒ F1 已开 t11）。
   ⇒ 本文所有菜单读数都带采集时刻，**引用前请重跑 §1 的命令**。
7. **本任务执行期的一次环境改动（自我登记）**：取"何时可删除"证据时曾误用 `pg_stat_user_tables` 累计计数，
   并为读取它跑了 `CREATE EXTENSION pg_stat_statements`（本地库 `edu19`）。**该扩展已当场 `DROP`**，
   现状核对 `select count(*) from pg_extension where extname='pg_stat_statements';` → **0**；此后全部读数改用状态表
   （`max(create_date)`）。教训已写进 `docs/dev-workflow.md`「判据强度第 5 条：量具本身不许有副作用」。

---

## 8. 变更记录

| 日期 | 改动 | 责任 |
|---|---|---|
| 2026-10-03 | **追加「旧一套评估的后台菜单仍与现役并排」登记（第 59 轮，后台菜单全量复核）**。全量扫 330 个菜单：**指向坏动作/坏视图的 = 0**（好消息）。但发现「综合评估」下**并排 6 个菜单、其中两个同名「评估任务」**：`edu_portal.menu_edu_eval_task`（→ `edu.eval.task`，仅 1 条**无名字**的残留记录）与 `edu_assess.menu_edu_assess_task`（→ `edu.assess.task`，4 条真实验收任务）。**这不是我的判断，是本仓自己文档里写着「收口未做」的那件事的用户可见部分** —— `docs/plans/README.md:44`：「④ 评估收口第二步：旧两套（`edu.eval.*` in `edu_portal` / `edu.admin.eval.*` in `edu_eval`）冻结 → 备份 → 删除…🟡 设计完成，收口未做」。**处置**：只停**菜单**（用户可见的那一半），不动物理表/代码，与文档「冻结→备份→删除」的次序一致且完全可逆；两个 xmlid 加入第 50 轮就有的 `RETIRE_MENUS` 机制（复用，不另起一套）。**实测**：两菜单 `active=False`、`edu_assess` 那条保留、该下拉从 6 项变 4 项无重名。另：`配置`×4（时间表下）、`报告`×2（时间表下）等重名属 **OpenEduCat 基座模块**自带（`openeducat_assignment/exam/attendance/timetable`），按「基座原则上不改」**未动**，仅登记 | 队长 |
| 2026-10-03 | **追加「退役中的 edu_telegram 仍在实际运行」登记**（承接 §0.1 与 **B8**：本仓 v2.2 退役件）。实测：模块 `installed`；**两个 cron 仍 active 且今天都跑过**（25「每日推送」最后 10-02 10:13；33「公告推送(每小时)」最后 18:12、下次 19:12）；菜单 792「Telegram 领码记录」active；参数 `bot_token` 为真实 token、`dry_run=0`（非调试态）。⚠ **安全面**：`admin_key = ADMIN-2026`（全仓代码搜不到 ⇒ 是 DB 配置值），而 `models/telegram_chat.py:73-79` 的逻辑是「消息文本 == admin_key ⇒ 绑定为 `role=admin`」⇒ **猜中即可成为管理员**；admin 又能拿 `cmd_overview`（`main.py:465`）与 `_notify_roles(('faculty','admin'))`（`main.py:588`）的教职工通知。**建议轮换 bot_token 与 admin_key**（须用户执行）。**本地克隆库隐患已处置**：该库带生产 token 且 `dry_run=0`，已把本机 `edu_telegram.dry_run` 改为 `1`（该参数本意即「本地调试」；`odoo shell` 须 `env.cr.commit()` 否则回滚）。**未停 cron、未卸模块、未改该模块任何代码**（怕停掉学校正在用的通知渠道）。详见 `docs/audit/telegram-retired-but-live.md` | 队长 |
| 2026-10-03 | 新增 **C-13**：35 个「模板在用、样式里没有」的自有类名。**新立报告型工具** `scripts/find_undefined_classes.py`（判据＝自有前缀 `oe-/ux-/b11-/edu-` 的类名出现在模板 `class=` 却不在任何样式/JS 文件里；自带 `--selftest` 与反向注入自证）。处置＝**登记不删**，理由见该行 | 队长 |
| 2026-10-03 | 新增 **C-12**：`/my-courses` —— 门户左导航那条「课程」入口删除。**依据是本仓已上线的决定**（`study-hub-v3-design.md` §6 第 15 行：该入口新落点 = `/my/study`），非我个人判断。路由保留，待 `enroll-v2-design.md:59` 的重建。⚠ 同日**更正我自己一处错**：初版写「已无入链（grep 0 处）」不成立 —— 其余入口定义在**控制器配置**里，grep 看不见；已补真实入口清单（≥4 处，其中 1 处定义未定位）。发现途径＝全量外壳扫描 `scripts/find_wrong_shell.py` 后追「谁链接到它」 | 队长 |
| 2026-10-02 | 新增 **C-11**：`edu_home_timeline` 里两段以 `course_cards`/`quick_cards` 为条件的区块 —— **模板是活的、区块是死的**（变量全仓无来源）。发现途径同 C-10 | 队长 |
| 2026-10-02 | 新增 **C-10**：`edu_portal/views/welfare.xml` 的 `edu_welfare_checkin` 模板（**197 行**）全仓 **0 引用**，属 `edu_life` 取代后的旧门户打卡实现。发现途径＝**模板变量孤儿扫描**（新增报告型工具 `scripts/find_orphan_template_vars.py`）。处置仍为**登记不删** | 队长 |
| 2026-10-02 | 新增 §4.1，登记两条**不影响功能但极易被误删**的条目：**C-08** 两条孤儿页（`/student/subjects`、`/my/points/me`，可达但代码入链 0 次）、**C-09** `/web/register` 同名路径双声明（父类两条 `@http.route` 在运行态注册表 0 条，但**父类实现经 `super()` 在用**）。均为「登记不删」；来源＝去冗余普查（[docs/audit/redundancy/inventory.md](redundancy/inventory.md) §4.3/§4.5、§8 F4/F7） | 队长 |
| 2026-09-29 | **B2 / B3 由「冻结退役」改为「已删除」**：`edu_eval` 模块目录、`edu.admin.eval.*` 三个模型与三张表、ACL/ir.rule、后台菜单 597–600、门户 `/eval/*` 六条路由（含宿主在 `edu_assess` 里的 303 兼容壳）**全部删除**，用户当日授权（原话「行政评估可以删了，完全没有人用过，你删吧」）。前置证据（J1–J5 判据、本地+生产逐表读数、生产备份指纹、两侧门禁读数、回滚路径）见 `docs/audit/edu-eval-removal.md`。同时改写 §0 三态口径的「已删除」行 —— 本轮起它**不再恒为 0** | 实现子代理（删除行政评估） |
| 2026-09-17 | 追加 §5「待固化项」P-01（到堂类型靠脚本 get-or-create，新库/重装必须补跑 `checkin_merge.py`）与 §1 ⑤ 核验命令；F5 行按队长口径改为「非幂等、t12 修复中」 | t6 / docs-eng |
| 2026-09-17 | 追加 F5 条目（升级向业务表注入无标记演示数据），并在 `docs/dev-workflow.md` 第 0 步闸门加 ④⑤ 两项 | t6 / docs-eng |
| 2026-09-17 | 建立台账：27 条被隐藏根菜单登记（15 合并 + 11 本轮隐藏 + 1 收口前既有）+ 3 条仅超管根 + 7 组弃用模型 + 7 条 URL 兼容层 + 5 条不做/未核项；定义 C1–C7 删除门槛与三态口径 | t6 / docs-eng |
| 2026-09-17 | 追加 §0.1「同名不同物」警示（生产 `edu_telegram` = 匿名意见箱 ≠ 本仓 v2.2，含匿名红线/路由撞名/参数撞名三条后果）与台账 **B8**（本仓 v2.2 退役登记：保留原因 / 替代路径 / 何时可彻底删除 / 删除前置条件）；配套更新 `docs/code-map.md` §4 的 edu_telegram 段。**未删任何文件、未改 v2.2 代码** | T-E（新模块 edu_tg_bind 任务） |
| 2026-09-17 | **追加 C-1 查重登记**（改课影响面/变更通知的第 0 步）：重叠对象 = `edu_telegram/models/hooks.py` 的「课表变更推送」（`op.session.write` 覆盖 + `WATCH` 6 字段 + `edu.telegram.outbox.enqueue`；模块 `edu_telegram 19.0.2.2` 本地实为 `installed`）；候选方案 = **合并（入口收口）**：替代路径 = `edu.message._notify_event('session_change', …)`，实施期须处理与退役模块的双写（`edu_telegram_outbox` 不得因 C-1 增加）。**本次未删任何文件、未改任何代码、未改库** | 设计子代理（C-1，`docs/plans/session-change-impact-design.md`） |
| 2026-09-18 | **追加 H-1 查重登记**（学生门户首页「我的主页 ↔ 全部应用」合并的第 0 步）：重叠对象 = **同一个「门户首页」的两套实现** —— `/my/home`（Timeline 工作台，`edu_portal/controllers/batch2.py:1895` 学生分支 → `edu_portal/views/study.xml:254`）与 `/my/apps`（全量卡片宫格，`batch2.py:1945` → `edu_portal/views/batch2.xml:663`），两者共用同一套卡片引擎/收藏契约（`batch2.py:1949-1951` 自述）。**候选方案 = 合并（入口收口）**：**保留 `/my/home`**（活引用 118 处：`request.redirect('/my/home')` 96 + `href="/my/home"` 22；`/my/apps` 仅 4 处），学生/家长访问 `/my/apps` → **303 `/my/home`**；**内部用户（教师/教务/管理员）`/my/apps` 保持 200**（那是他们唯一的门户宫格入口）。**何时可彻底删除 = 无计划（NULL）**；**删除前置条件** = ① 内部用户宫格已在别处有着落（否则不能下线）② 连续 30 天无书签/404 报障 ③ `grep -rn "/my/apps"` 的活引用归零 ④ `tests/audit/verify_consolidation.py:48` 与 `tests/smoke/ux_v3_route_matrix.py:74` 的断言已从"跟随后 200"改成"**303 + Location 精确**"（C5 口径）⑤ 队长书面确认。同文另登记**需求 6 头像统一的同族重复**（`image_256` 灰相机占位 vs `avatar_*` 首字头像，4 处写法并存），裁定 = **复用到 Odoo 内置 `avatar.mixin`**。**本次未删任何文件、未改任何代码、未改库、未动生产** | 设计子代理（H-1，`docs/plans/student-portal-home-profile-design.md`） |
| 2026-09-18 | **追加 C-3 查重登记**（「录取后发放入学码」的第 0 步）：重叠对象**有两层** —— ① **承载物**（不是重复物）：`edu.invite.code` 邀请码体系（`custom_addons/edu_portal/models/invite_code.py:94-402`，含 `unique(code)`、层级码、有效期、次数、消费留痕、教务全权 ACL）+ `/register` 消费链路（`custom_addons/edu_portal/controllers/register.py:53-135`）；② **一个需要否证的头部候选**：基座 `openeducat_admission` 的 **`enroll_student()` / `get_student_vals()`**（「录取 → 建 `op.student` → 建门户账号」，位置与命名几乎同本需求）——`openeducat_erp/openeducat_admission/models/admission.py:77-82`（状态机含 `admission`）、`:245-301`（建 `res.users` 只给 `base.group_portal` 且**不含 password** ⇒ 账号建出来也登不进去；同建 `op.student.course` 含 `batch_id`）、`:303-387`（写学费明细与 `op.subject.registration`）、`views/admission_view.xml:51-52`（按钮 `invisible="state != 'admission'"`）；**本机只读读数**：`op_admission` **0 行**、`op_admission_register` **0 行**、ACL 只给 `group_op_admission_*`（**教务组不在内**）、参数 `openeducat_admission.enable_create_student_user` = **True**；**查重命令与负结论**：`grep -rniE "入学码\|录取码\|admission_code\|invite_link\|issue_invite\|grant_invite\|send_invite\|发放入学"`（custom_addons/ + docs/ + scripts/）= **0 命中**、`base_automation` 4 条**无一**命中申请模型、`edu.application` 的全部引用只有依赖声明与可达性测试。**裁定 = 复用 + 新建薄模块 + 新增 1 列**：承载 = `edu.invite.code` + `/register`（**渠道内按需生成码，不与 `edu_tg_bind` 共用码池** —— 共用会让 TG 的池判据 `tg_claim.py:48-57` 把"已邮件发出的码"再发一次）；**不复用基座 `enroll_student()` 写路径**（R1 数据模型不兼容 / R2 本仓 0 数据且教务无 ACL / R3 它建出的账号无密码、仍解决不了"能登录" / R4 它会写本仓不认的学费与选课结构），**只借鉴它的字段映射口径**（`:261-301`）。唯一 schema 变更 = `edu.invite.code.application_id` + `unique (application_id)`（`edu_apply` 侧落不了地：`edu_portal` 依赖 `edu_apply`，反向依赖即循环）。**收口触发条件**：第三处发码场景 ⇒ 必须把发放记录收口成统一表（`edu.tg.claim` + `application_id` 一并迁入）；TG 池前缀被改成能匹配 `ADM-` 即红线告警。**本次未删任何文件、未改任何代码、未改库、未动生产** | 设计子代理（C-3，`docs/plans/admission-invite-link-design.md`） |
| 2026-09-18 | **追加 C-2 查重登记**（需求 7 班级管理的第 0 步）：重叠对象 = **本需求命中的"既有实现"不是重复物，而是承载物** —— 班级实体 `op.batch`（`openeducat_erp/openeducat_core/models/batch.py:25-68`，**6 字段 + `mail.thread` + 内建 `active` 软删（`:36`）**）与学生归属 `op.student.course.batch_id`（`openeducat_core/models/student.py:34`）。**四路查重实跑结论**：① 候选新模型 `edu.batch*` 全仓 **0 命中**；② 候选"班级门户页"路由（`@http.route` 全量搜 `class\|batch`）**0 命中**；③ 「同班同学/同学/classmate」在 `custom_addons/` + `docs/plans/` + `docs/research/` **0 条活实现**；④ **@`action_archive`/`action_unarchive` 全仓 0 命中** ⇒ **没有第二套软删实现**。**裁定 = 复用（不新建）**：不新建模块/模型/表/字段/路由/权限组/软删机制。**替代路径 = 基座 `op.batch`（含 `active` 回收站）+ `op.student.course`**；扩展方式 = ① 菜单 264 可见性一行（教师建/改；删除仍归教务，实查教师 `unlink=False`）② 批次**列表视图**补 `active` 列（Odoo 19 归档动作的硬前提：`web/static/src/views/list/list_controller.js:107-112` 注释原文 "enable the archive feature in Actions menu only if the active field is in the view"；基座列表 `views/batch_view.xml:8-14` **无** `active`，而表单 `:26` **有** ⇒ 回收站"表单可用、列表不可用"）③ `op.batch.unlink()` 护栏（照 `custom_addons/edu_portal/models/fees.py:128-138` 与 `models/downloads.py:44-55` 先例：有引用拒绝 + 引导「停用」）④ 门户只读"同班同学"分支（复用 `/my/contacts` 熟人圈矩阵 `/my/…` → `edu_portal/controllers/contacts.py:61-88`）。**彻底删除/收口触发条件（T1–T5 见设计稿 §8.4）**：出现第二个 `op.batch` 的 `_inherit`、第二个班级门户路由、第二个"定班"写库入口（今天唯一 = `edu_portal/models/registration.py:178-195`）、第二个软删实现、或菜单 264 `groups` 第三次改动 ⇒ 回第 0 步查重。**库内实况（只读）**：`op_batch` 17 条**全部 `active=t`**（回收站从未被使用）、`op_session` 288 节 100% 挂 `batch_id`、`op_subject_registration` 12/12、`op_assignment` 5/5、`op_student_course` 4 行中仅 1 行有班。**本次未删任何文件、未改任何代码、未改库、未动生产** | 设计子代理（C-2，`docs/plans/class-batch-management-design.md`） |
| 2026-09-18 | **追加 B-1 查重登记**（学生申请调班 → 教务审批的第 0 步）：重叠对象 = ① **头号**：**既有「课程变更申请」是一条批不动的半成品** —— 学生路由 `/course/change/request` + `/course/change/request/save`（`custom_addons/edu_portal/controllers/batch3.py:213,258`，写 `doc_type='course_change'`）；**教务侧两处硬排除**（`controllers/enroll.py:334-337` domain 硬写 `doc_type='subject_registration'` + 注释「教务另有换课流程」；`views/approval_backend.xml:229` 注释「课程变更单不进审批队列」），而那句「教务另有换课流程」**在仓内查无实据**（同串 grep 只回该条注释）；**库内实况（只读）**：`op_subject_registration` 12 行 = `course_change/submitted` **11**（ids 10–19 = student 5 / course 13 / batch 8，id 72 = student NULL 孤儿单）+ `subject_registration/approved` 1；**结构性死路两条**：`batch3.py:277-278` 让 `batch_id` 取自学生当前档案而 `course_id` 另选 ⇒ 11 张单全部 `batch(8).course_id=18 ≠ course_id=13`，撞 `registration.py:147-150` 的自洽校验；且该动作会整体覆盖 `subject_ids`（`:190`）并在空科目时抛 `UserError`（`:161-171`，校长 2026-09-17 亲裁「拦住吧」）⇒ **接进同一动作必然死锁**。② 同族：`op.subject.registration`（基座选课注册单，已被本仓扩成成熟的「学生申请→教务审批」形态）。**裁定 = 复用**：**替代路径 = `op.subject.registration` + 新增第三个 `doc_type='batch_change'`（班级变更）**；扩展方式 = ① `registration.py:29-32` 的 `_DOC_TYPE` 加 1 个值 ② 新增 `action_batch_change_approve()`（**只写 `{'batch_id': …}`、绝不碰 `subject_ids`**，且共用 `action_enroll_approve` 的前置校验口径）③ 学生路由族 `/batch/change/request[/save]`（与 `/course/change/request` 互为兄弟）④ 审批页 `filterby=batch` 分支 + 后台 doc_type 作用域按钮/1 行 domain。**不新建模块/模型/表/字段/路由概念/权限组/通知通道**。**生效语义 = 当场改写 `op.student.course.batch_id`**（不新建档案行、不置 `finished`）：依据 ① `student.py:34` 的 `batch_id tracking=True` 白拿字段级留痕 ② `student.py:50` 的 `unique(student_id,course_id,batch_id)` 会让"新建 + 旧行 finished"**换回原班时直接撞约束（不可逆）** ③ `state='finished'` 在学生侧渲染成「已结业」（`enroll.py:309`）④ 与全仓唯一既有定班写库语义一致（`registration.py:193-195`）。**通知/留痕 100% 复用 C-1 已落地通道**（`edu.message._notify_event` `notify_pref.py:51` + `edu.audit.log._log` `audit.py:29` + `mail.thread`），**不另造**；**不使用 `edu.telegram.outbox`**（§0.1 红线）。**明确不做 + 唤醒条件**：既有 11 张 `course_change` 单**不改不批不删**（语义是"换课程"，与"换班"不同轴）⇒ 唤醒条件 = 另立"换课/学籍异动"任务时一并处置。**收口触发条件 B1–B5**（设计稿 §7.4），其中 **B2「出现第二个给学生定班的写库入口」与需求 7 的 C-2/T3 是同一条**；本设计**接力**需求 7 §1.2「不做学生自助转班」这条非目标（校长本次原话推翻了它，两者共用同一写库入口、不冲突）。**库内实况（只读）**：`op_student_course` 4 行（仅 id 9 = 学生 5 / course 18 / batch 8 / running；ids 10-12 为 student 7/8/9、`finished` 且无班）；`op_batch` 17 条全部 `active=t`，其中 **`course_id=18`（预备科）只有 batch 8 一个班**（⇒ 真机验收必须现场造 1 个【演示】同课程班）；`op.session` 288 节 100% 挂班；`mail_tracking_value` 对 `model='op.student.course'` = **0 行**（机制在、**从未触发**，留作验收 V7 补测）；`edu_audit_log` 1434 行、`edu_message` 按事件 `subject_reg_result` 155 行。**本次未删任何文件、未改任何代码、未改库、未动生产** | 设计子代理（调班申请，`docs/plans/class-change-request-design.md`） |
| 2026-09-18 | **追加 B-1 修订登记（v2：校长 P6 改判「课程也可以换」）**：**裁定改变** —— **不再**新增 `doc_type=batch_change`、**不再**新增 `/batch/change/request` 路由族；改为 **修好既有 `/course/change/request` 半成品链路并收口成唯一入口**（学生侧 `custom_addons/edu_portal/controllers/batch3.py:213,258` 保留；解禁教务侧两处硬排除 `controllers/enroll.py:337`、`views/approval_backend.xml:230`；订正失效注释 `enroll.py:336` 与 `controllers/batch2.py:616`；新增唯一审批动作 `action_course_change_approve()`，**必须落在 `models/registration.py`**，否则触发收口条件 C2）。**生效语义重做**：换课程必须一次 `write()` 原子写 `course_id + batch_id + subject_ids + academic_term_id`（`subject_ids` 按目标课程重算 —— 与 v1「审批绝不碰 subject_ids」冲突，以 v2 为准）；**成绩/考勤零物理漂移**（`op.exam.attendees` 挂 `student_id+exam_id`、`op.attendance.line` 挂 `student_id+attendance_id`，课程来自考试/点名表，不引用档案）；**唯一约束规避仍成立但前提收紧为「只原地改写、永不新建行」**，打破前提的现实路径 = `action_enroll_approve` 的建档分支（`openeducat_activity/wizard/student_migrate_wizard.py:101-123` 同型）与多 running 档案。**本轮独立复核（只读）**：**生产** `op_subject_registration` 仅 **1 行**（id 19 / SR0017 / subject_registration / submitted）、`course_change` **0 行**、`op_student_course` 仅 **1 行**（王佐 id 13 / course 16 / batch 13 / `roll_number=BED2026-WZ001` **非空**）、`op_exam_attendees` 与 `op_attendance_line` 均 **0 行**、`op_batch` 19 条含 batch 27（course 13）；**本地** 11 张 `course_change` 的 `create_uid=8`（= `stu@local`）⇒ 判定为**夹具**（v1 §0 曾当作"最强证据"）。**与原稿不符 3 条**：取班口径措辞（`batch3.py:277` 优先取表单 `batch_id`，模板 `views/batch3.xml:176-188` 只渲染 `course_id`）、`batch2.py:616` 同类失效注释、写库入口唯一性的作用域（基座另有两条写路径）与 `edu_eval/controllers/eval_portal.py:62-64` 行号。**本次未写一行代码、未改 `custom_addons/`、未改 `openeducat_erp/`、未改库；生产仅只读 SELECT** | 设计子代理（调班设计修订 v2，`docs/plans/class-change-request-design.md` §19） |
| 2026-09-18 | **追加「评估系统重建」查重登记**（校长裁定「两套都删、重建一套（形态甲）」的第 0 步）：重叠对象 = **既有两套评估引擎全部** —— A 套 `edu.eval.template/.template.line/.task/.score`（`custom_addons/edu_portal/models/evaluation.py:20/47/66/123`；菜单 588/589/590；门户 `/my/evaluation*` 7 条路由；ACL 只有 group_user/group_system、**无门户 ACL**）与 B 套 `edu.admin.eval.template/.item/.score`（`custom_addons/edu_eval/models/admin_eval.py:25/70/95`；菜单 597/598/599/600；门户 `/eval/fill`、`/eval/my`、`/eval/review*` 6 条路由；含门户 ACL 与 2 条 ir.rule）。**证据（本轮实测）**：生产 `edu19-prod-db-1` 只读 SELECT —— A 套 **4/13/1/0**（4 模板 = 3 个【演示】+「学生表现分」；13 评分项；1 任务 id2/student11/state=scoring；**0 条打分**）、B 套 **0/0/0**；`ir_model` 中 `%eval%` **恰好 7 个模型（无第三套）**；⚠ 生产**未装 `edu_nav`** ⇒ 597 仍 active、598/599/600 仍挂 597（**与 `docs/code-map.md:97-101`「已并入 588」不一致，那是本地口径**）。**候选方案 = 新建（并存）**：新建模块 `edu_assess`（前缀 `edu.assess.*`，全仓 0 命中）+ 5 模型（template/item/task/roster/score），旧两套先冻结 → 303 → 备份 → 再删；**作废 `docs/plans/eval-merge-design.md`**（它的前提「A 套有存量」已被生产读数 0 条打分推翻），并**推翻调研 §7.1 的 `Properties` 推荐**（Properties 是每记录键值、做不了 FK/唯一约束，且会使 D「xlsx 导题」不可行：`base_import` 只能映射既有字段、不能映射 jsonb 子键）。**收口触发条件 T1–T4** = 出现第三组评估模型前缀 / 出现第二个「给学生打分」的门户写库入口 / 评估结果要进成绩册 / 落地 6 个月仍 0 条打分。**另发现 2 处存量缺陷须随重建修掉**：B 套评教**并不匿名**（`admin_eval.py:111-114` 的 `scorer_id` required + `eval_portal.py:332` 显式写入）却对学生在 `edu_portal/views/help_center.xml:100` 承诺「评教完全匿名」；`UNIQUE(task_id,item_id,student_id,scorer_id)` 对 `student_id` 为 NULL 的评教行失效（`admin_eval.py:120-130`）。**本次未写一行代码、未改 `custom_addons/`、未改 `openeducat_erp/`、未改任何库；生产仅只读 SELECT，未触碰匿名意见箱（`edu_telegram`/`edu_feedback`）** | 设计子代理（评估系统重建，`docs/plans/evaluation-rebuild-design.md`） |
| 2026-09-18 | **追加 排课链路查重登记**（《排课链路改造设计》的第 0 步）：重叠对象 = ① **同一个「批量建 op.session」的两个入口** —— 基座官方向导 `generate.time.table`（`openeducat_erp/openeducat_timetable/wizard/generate_timetable.py:30-133`「7 天 notebook × 每天多行」；菜单 id **344**，本地与生产 `ir_ui_menu_group_rel` 均**仅 gid=60**（`group_op_timetable_manager`），而教务组 id 40 隐含 60 ⇒ **教务今天就能打开它**）与门户 `/timetable/bulk`（`custom_addons/edu_schedule/controllers/main.py:424-499`；`ir_act_url 742` → `/timetable/bulk`；菜单 603，组 40/60；独有能力 = 周次范围/单双周/停课日/落库前周矩阵预检/审计）；② 候选新模型「教师可用/不可用」在 `custom_addons/` **0 命中**（`grep -rn "可用时间\|不可用\|可约\|教师日程\|可用时段\|availability"` = 6 命中且全为日志文案；`grep -rn "resource\.calendar\.leaves\|resource\.mixin\|resource\.resource"` = **0**），而 Odoo 19 核心 `resource` 已有例外原语（`addons/resource/models/resource_calendar_leaves.py:35-50`；取例外区间应用 `resource_calendar.py:502-550 _leave_intervals_batch`，**不得**用 `:574-600 _unavailable_intervals*`（掺入常规工时 ⇒ 晚课/周末课会被误判不可用））。**裁定** = ① **并存 + 边界裁定**（保留基座向导与门户页；分工 = 向导「一次排一整个班的多科目网格」/ 门户「单科目 × 多周次批量」；**本期不做合并**，合并前置 = 补齐向导缺的 4 项能力：周次范围/单双周、停课日、落库前预检、中文+权限+审计）；② **复用核心 resource**（不新建模块/模型/表；`op.faculty` 接 `resource.mixin`，存量 1 行走 `scripts/migrations/`，**不进 `data/`**）。**收口触发条件** = ① 出现第三个「批量建 op.session」入口 ⇒ 按 `docs/dev-workflow.md` 脚本化条件写 `scripts/check_feature_overlap.py`；② 向导补齐 4 项后必须一次合并；③ 排课完成度看板出现第二个写库入口 ⇒ 立刻收口（看板保持只读）。**生产只读复核（本次实测）**：`op_session` **216**（100% draft；覆盖 18 科目 / 13 班 / **1 位教师（占位「待定」id 20）** / **0 间教室**）、`op_subject` **147**（compulsory 25 / elective 122）、`op_batch` **19**（**有在读学生的只有 1 个**）、`op_student_course` **1**（王佐 → course 16 / batch 13）、`op_subject_registration` **1**（SR0017 submitted，payload 21 必修全无排课）、`resource_calendar_leaves` **0**、`hr_holidays` **uninstalled**。**本次未写一行代码、未改 `custom_addons/`、未改 `openeducat_erp/`、未改任何库；生产仅只读 SELECT，未触碰匿名意见箱（`edu_telegram`/`edu_feedback`）** | 设计子代理（排课链路改造，`docs/plans/scheduling-overhaul-design.md`） |
| 2026-09-19 | **追加「专业编排（学制 + 必修/选修）」查重登记**（校长「课程编排里教务自己标学制 / 哪些必修哪些选修」的第 0 步）：重叠对象三类 —— ① **真重复（概念级）**：`op.program`（菜单 **276「专业」**、动作 395；`openeducat_erp/openeducat_core/models/program.py:24-43`）与 `op.course`（菜单 **263「课程」**、动作 385；`course.py:25-59`）在本部署里是**同一概念的两种表达**；生产只读实测 `op_program` **0 行**、`op_course` **6 行**（CRS-BTH/BLA/BED/MCS/HSA/PRP）、`op_course.program_id` **6/6 全 NULL**、`op_program_level` **0 行**；全仓 `op.program` 活消费点仅 2 处（`custom_addons/edu_assess/models/assess.py:207-209`「参与专业」；`custom_addons/edu_public/controllers/main.py:252-256` `/program-offered`，**0 条 → 空页**）；② **同名词不同物**：`res.partner.street2` 已被改文案为「学制」（`custom_addons/edu_portal/models/partner_edu.py:6,19-20`，**自由文本 Char、无 FK / 无唯一约束**）；③ **承载物（不是重复物）**：`op.program.level`（菜单 **277「专业层次」**、动作 396；`program.py:46-54`；ACL 实测 gid 40 = `1,1,1,1`，且**没有 `active`**）与 `op.subject.subject_type`（`subject.py:36-38`；生产 147 门 = 必修 25 / 选修 122）。**候选方案 = 复用 + 新建 1 个 through 模型**：**学制复用 `op.program.level`**（新增 `op.course.edu_level_id` M2O，**不走空壳 `op.program` 中间层**；补 `active`/`sequence` 与 `ondelete='restrict'`，后者不写会静默清空学制），**新建关系表 `edu.course.subject`**（全仓 0 命中）承载「专业 × 科目 × 必修/选修（空 = 继承全局）」，`op.course.subject_ids` 改为**非存储 computed M2M + inverse + search** 兼容层（Odoo 19 运行时实证：`odoo/orm/models.py:4490-4501` 与 `:4661-4733` 的 `write`/`create` 都调 inverse；`odoo/orm/fields.py:1930-1932` `search` 决定域查询；内核同型先例 = `res.users.all_group_ids`，`odoo/addons/base/models/res_users.py:258-259`），**老表 `op_course_op_subject_rel` 334 行一行不删**（迁移 = 1 条幂等 `INSERT..SELECT` + 3 条自证断言；回滚 = 改代码，**不得 DROP**）。**同类登记**：改名撞名（276「专业」vs 263 待改「专业」）与 PO 覆盖按 `msgid` 全局生效（`docs/ops/menu-rename-list.md:29,64,93-95`）——**不得**用 `Courses → 专业` 全局覆盖（生产仍启用的 561「课程」=`slide.channel` 会被连带改掉）。**收口触发条件** = 出现第 2 个「专业 × 科目分类」写库入口 / 第 2 处「学制」字典 / 必修选修被再复制一份。**本次未删任何文件、未改任何代码、未改库、未动生产；生产仅只读 SELECT，未触碰匿名意见箱（`edu_telegram` / `edu_feedback`）** | 设计子代理（专业编排，`docs/plans/major-track-elective-design.md`） |
| 2026-09-28 | **追加「课程中心排课入口」查重登记**（《课程中心排课入口设计》的第 0 步）：**重叠对象 ①「排课入口」** = 门户课程中心若新增「排课」，与既有 `/timetable/bulk`（`custom_addons/edu_schedule/controllers/main.py:669/698/733`；`ir.actions.act_url 742`；菜单 **603**；组 40/60）是同一件事的两个入口 —— 门户侧三条路由**全部** `require_internal()`（`main.py:56-58`，门户账号 303 回 `/my/home`）⇒「搬」要么放宽门禁、要么在 `edu_portal` 侧新建同能力写路由。**裁定 = 复用（跳转 + 预填 course/batch/subject）**：课程中心**不复制**建课逻辑，写点保持唯一。**收口触发条件** = 出现第三个「批量建 `op.session`」入口 ⇒ 按 `docs/dev-workflow.md`「脚本化条件」写 `scripts/check_feature_overlap.py`（该条件由 `scheduling-overhaul-design.md` §16 先立，本次重申并沿用）。**重叠对象 ②「课表展示」** = `/student/timetable`（周课表四视角，`edu_portal/controllers/scheduling.py:130-314`）与 `/my/study`（科目视图，`edu_portal/controllers/study.py:273-320`，只有每科「下次：」一行、**无周矩阵**）已是两处。**裁定 = 复用（不新增渲染器）**：课程中心只做「本周摘要」（周窗口 import 唯一实现 `edu_schedule/models/week_utils.py:18/23/30/88`），完整课表**只链接**既有页，订阅**只链接**既有 `/my/calendar`（`edu_portal/models/ical.py:101`）。**零新建承诺（本次设计）**：不新建模块 / 业务模型 / 表 / 字段；「排课到人」用**基座既有** `op.session.student_ids`（`openeducat_erp/openeducat_timetable/models/timetable.py:60`；本地只读实测 `op_session_op_student_rel` = **0 行**）；学生维冲突判定**扩展同一份唯一实现**（`main.py:262-298 _slot_conflict_dims` + 姊妹 `session_ext.py:452-468 _impact_overlap_dims`，**不写第二套**）。**另登记两条既有实况不一致**（不属于本设计的重叠）：③「整周复制」已于 `77b0b75`（2026-09-15）删除，但全仓**仍有 12 处非文档引用**（`README.md:60`、`edu_schedule/__manifest__.py:4,5`、`edu_schedule/views/templates.xml:25`、`edu_schedule/views/holiday_views.xml:41`、`edu_schedule/models/holiday.py:2`、`edu_schedule/models/week_utils.py:2`、`edu_portal/views/scheduling.xml:106`、`edu_portal/views/help_center.xml:240`、`edu_portal/controllers/help_center.py:18`、`edu_portal/models/audit.py:5`、`edu_portal/controllers/batch2.py:1918`）⇒ 建议队长排一次文案清理；④ 顶部导航「**课表**」指向 `/my/calendar`（`edu_portal_templates.xml:140`）而真课表在 `/student/timetable`，**名实不符**（修复要动 `edu_portal_templates.xml` = **他人 working set**，本设计不改）。**本次未写一行代码、未改 `custom_addons/`、未改 `openeducat_erp/`、未改任何库、未 `git commit`；本地仅只读 SELECT** | 设计子代理（课程中心排课入口，`docs/plans/study-scheduling-design.md`） |
