# 评估两套合并设计 —— 一套引擎 + 类型字段（edu.eval.*）
> **状态**：`归档` ｜ **主题**：`评估引擎合并` ｜ **取代**：`evaluation-rebuild-design.md` ｜ **核对**：`2026-10-06`
> ⚠️ 本文已被 [`evaluation-rebuild-design.md`](evaluation-rebuild-design.md) 取代，请优先阅读后者。

> 任务：t4 ①（评估收口设计）｜ **本轮只出设计**：不改代码、不动菜单、不改数据
> 实测时间：**2026-09-17 11:06 CST**｜环境：docker 项目 `edu19-clone`（库 `edu19`，http://127.0.0.1:8069）
> 方法：只读 SQL / ORM 读数 + 门户路由逐条 HTTP 实测 + 源码核对（每条数字都带来源，未实测的一律标「未核」）
> 上游依据：`docs/audit/feature-overlap-audit.md`（t1，commit dd0074f）§1.2 / §2.3 / §4-1
> 历史设计：`docs/plans/eval-design.md`（A 套 v2-P2，文件自身状态标「待确认」）；B 套无独立设计文档

---

## 0. 结论速览（TL;DR）

| 问题 | 结论 |
|---|---|
| 留哪套引擎 | **留 A 套：`edu_portal` 的 `edu.eval.*`**（理由见 §3，最终由拍板 1 确认） |
| B 套（`edu_eval` / `edu.admin.eval.*`） | **冻结退役**：模型/表/ACL/ir.rule 全保留，只隐藏菜单 + 路由 303 重定向 + 登记弃用台账。**不删任何记录、不删表、不删模型** |
| 存量数据迁移 | **本轮零迁移**：B 套模板/条目/打分 = 0/0/0，无数据可迁；A 套 18 行（3 模板 + 12 评分项 + 1 任务 + 5 打分）原样保留、语义不变 |
| 统一模型 | A 的 4 个模型不动骨架，**新增 1 个模型 `edu.eval.campaign`（评价活动）+ 9 个增量字段**，另 2 处 Selection 扩值、1 处 required 放宽、3 条新约束（§4.2） |
| 6 种口径 | 全部落在 `edu.eval.template.type_code`（3 → 6 值）+ 新增 `target_kind`（学生/教师），见 §4.3 |
| 评分维度 | 沿用 `edu.eval.task.evaluator_type`（4 → 5 值，补「学生评」），见 §4.4 |
| 匿名评教 | 新增 `edu.eval.task.reviewer_token`（HMAC 不可逆令牌）+ 汇总门槛，**不落评者 user id**，见 §4.6 |
| 门户入口 | 学生/教师/教务**统一 `/my/evaluation`**；旧 `/eval/my`、`/eval/review`、`/eval/fill/*` 全部 **303** 到新址（保留老书签不 404） |
| 后台入口 | 唯一根菜单 **588「综合评估」**（库内实况 2026-09-17 复核；t1 施工图已定：588 容器、597 合并进 588。下文凡写「评估」者均指该容器，"改名『评估』"**尚未落地**——改名须由 edu_nav 用 XML 覆盖基座 xmlid，且需先修好 t11 的升级重放问题） |
| 回滚 | 无数据写入 ⇒ 回滚 = 退代码 + `-u`；新增列/表留在库中无副作用（§8） |
| 待拍板 | 3 项（§11） |

---

## 1. 目标 / 非目标

**目标**
- 全站**只有一个评估引擎、一个评估数据归属、一个学生入口、一个后台根菜单**。
- 合并后 6 种评估口径（新生综合测试 / 学生综合评估 / 实习同工评估 / 学生日常量化 / 教师评教 / 助教评教）由一个模型族表达，不再出现「改名区分」的并行实现。
- 学生端「我的评分 + 评教填答」两张卡收敛为一张，历史得分一条不丢。
- 零业务记录删除；每一步可独立 commit、可回滚。

**非目标**
- 不在本设计里实施（本轮不写代码/不动菜单/不改数据）；实施归属见 §12。
- 不合并「已读状态三套」（`edu.alert.read` / `edu.notice.read` / `edu.download.ack`）—— t1 §1.7 已登记为技术债，不在本设计范围。
- 不引入 AI 评分（沿用 `docs/plans/eval-design.md` 的既有红线）。
- 不删除 B 套任何表/模型/记录。

---

## 2. 现状与四层证据（2026-09-17 11:06 实测）

### 2.1 模型与数据条数

| | A 套：综合评估（`edu_portal`） | B 套：行政评估（`edu_eval`） |
|---|---|---|
| 模型 | `edu.eval.template` / `.template.line` / `.task` / `.score` | `edu.admin.eval.template` / `.item` / `.score` |
| 条数（本次实测） | **3 / 12 / 1 / 5** | **0 / 0 / 0** |
| 类型值 | `freshman` 新生综合测试、`student` 学生综合评估、`intern` 实习同工评估 | `student_daily` 学生日常量化、`teacher_review` 教师评教、`ta_review` 助教评教 |
| 维度 | `evaluator_type`：教师评 / 自评 / TA评 / 牧者评（task 级） | 无维度字段；`type_code` 同时编码"被评对象 + 评者" |
| 权重 | 无 | `item.weight`（倍率，默认 1.0） |
| 等级线 | `total` / `pass_line` / `excellent_line` + `grade` compute | 无等级 |
| 学生可见开关 | `template.visible_to_student` | 无 |
| 评分对象 | task 一个学生（`student_id` required） | 行级：`student_id` 或 `teacher_id` 二选一（constraint 保证） |
| 打分人 | **不记录** | `scorer_id`（required） |
| 状态机 | `draft / scoring / done`（+ `approved_by/date`） | `draft / open / closed` |
| 截止日 | 无 | `due_date` |
| 匿名 | 无此概念 | UI 不展示打分人，但 `scorer_id` **落库**（后台列表 `optional="hide"` 可展开） |

**A 套存量的实际内容（逐行核对）**

- 模板 3 行，全部带【演示】后缀（来源 `scripts/seed_eval_demo.py`，create_date 2026-08-24 08:58:30）：
  1. `学生综合评估记分表【演示】`（student，100/60/90，对学生可见）5 项 × 20 分
  2. `实习同工评估表【演示】`（intern，100/60/80，对学生不可见）4 项 × 25 分
  3. `新生综合测评表【演示】`（freshman，100/60/90，对学生可见）笔试 40 + 面试 30 + 写作 30
- 任务 1 行：模板 1 × 学生 `op_student(5) 王小明`（= 本地 `stu@local` 账号）｜维度 `teacher`｜周期 `2026秋`｜`done`｜总分 90｜等级 优秀。
  - **来源存疑（待拍板/记录在案）**：create_date 2026-08-24 08:59:10、create_uid=11（`faculty@local`），即**演示模板落库后 40 秒**由教师账号在门户打分表里建的，5 条打分全为 18/20。**高度疑似验证数据而非真实业务**——但按红线一律**原样保留**，本设计不对其做任何处置。
- 打分 5 行：全部 18 分（`edu.eval.score` 唯一约束 `UNIQUE(task_id, template_line_id)`）。

**B 套 0 行的后果（本次实测的旁证）**：`/eval/fill/1` 对教务/教师/学生**全部返回 303**（`edu.admin.eval.template` 无记录 ⇒ 控制器的 `task.exists()` 为假）。也就是说 **B 套的整班打分 / 匿名评教链路在本库从未有数据跑过**。

### 2.2 菜单 / 动作 / 组限制

| 根菜单 | id | 名称 | sequence | groups（实测） | 子菜单 → 动作 |
|---|---|---|---|---|---|
| `edu_portal.menu_edu_eval_root` | **588** | 综合评估 | 71 | `base.group_user`（角色/用户） | 589 模板管理 → act 726 (`edu.eval.template`)；590 评估任务 → act 727 (`edu.eval.task`，view_mode `list,form,pivot`) |
| `edu_eval.menu_edu_admin_eval_root` | **597** | 行政评估 | 72 | `base.group_user` | 598 评估模板 → act 738 (`edu.admin.eval.template`)；599 打分记录 → act 739 (`edu.admin.eval.score`)；600 结果分析 → act 740 (`edu.admin.eval.score`, pivot) |

→ 两个根菜单**同级、同组、相邻序列**，教务登录后并排出现，是「重复入口」的直接形态。t1 施工图已定：**588 保留为容器（库内名「综合评估」），597 隐藏、子树迁入 588**。

### 2.3 门户路由（逐条 HTTP 实测，含 cookie 会话）

| 路由 | 学生 `stu@local` | 教师 `faculty@local` | 教务 `backoffice@local` | 家长 | 管理员 | 归属 |
|---|---|---|---|---|---|---|
| `/my/evaluation`（中心） | **200**（含自己 1 条任务） | 200 | 200 | 200 | 200 | A |
| `/my/evaluation/results` | 303→`/my/evaluation` | 200 | 200 | 303 | 200 | A |
| `/my/evaluation/results.csv` | 303 | 200 | 200 | 303（按代码，未测） | — | A |
| `/my/evaluation/new` | 303 | 200 | 200 | 303 | 200 | A |
| `/my/evaluation/task/1` | 303 | 200 | 200 | — | — | A |
| `/eval/my` | 200 | 200 | 200 | 200 | 200 | B |
| `/eval/review` | 200 | 200 | 200 | 200 | 200 | B |
| `/eval/fill/1` | 303 | 303 | 303 | 303 | 303 | B（无数据可填） |

**学生实见内容（`/my/evaluation`，实测抓取）**：统计卡「任务总数 1 / 打分中 0 / 已完成 1 / 优秀 1」+ 一行表格
`王小明 | 学生综合评估 | 教师评 | 2026秋 | 90 | 优秀 | 已完成`。
→ **A 套的门户页对学生已经是可用的 200 页**，只是没有挂到学生导航卡上。

### 2.4 权限（ACL / ir.rule 实测）

| 模型 | `base.group_user` | `base.group_system` | `base.group_portal` | ir.rule |
|---|---|---|---|---|
| `edu.eval.*`（4 个模型） | 1/1/1/0 | 1/1/1/1 | **无 ACL** | **无规则** |
| `edu.admin.eval.template` / `.item` | 1/1/1/0 | 1/1/1/1 | 1/0/0/0 | — |
| `edu.admin.eval.score` | 1/1/1/0 | 1/1/1/1 | 1/1/1/0 | 读：`student_id.user_id = uid` **或** `scorer_id = uid`；写：`scorer_id = uid` |

→ **A 套学生端靠控制器 `sudo()` + 显式域过滤**（`/my/evaluation` 学生分支：`student_id = 自己` 且 `type_code = 'student'` 且 `template.visible_to_student = True`）；B 套走 ACL + ir.rule。
→ 合并后沿用 A 的形态（控制器 sudo + 显式过滤）**是零权限回归的路径**；B 的规则作为历史资产保留在库里（不再生效于主链路）。

### 2.5 代码侧「两套并存」的自证（原文）

- `custom_addons/edu_portal/controllers/evaluation.py:6` ——「（原「评估中心」，2026 更名以与「行政评估」区分；路由 `/my/evaluation` 不变）」⇒ 当时的处理方式是**改名，不是合并**。
- `custom_addons/edu_eval/models/admin_eval.py:4` ——「与 edu_portal 的「评估中心」(`edu.eval.*`) 相互独立：本模块模型统一使用 `edu.admin.eval.*` 前缀，避免同名模型在注册表中合并、破坏既有数据。」
- `custom_addons/edu_portal/controllers/batch2.py:587-588` ——「评估待打分：`edu.eval.task` state=scoring（教师真正可办的事；**既有 KPI「进行中评估」= edu.admin.eval 口径，保持不动**）」⇒ 同一屏里两个口径并存。
- `custom_addons/edu_portal/controllers/batch2.py:1807` —— `if 'edu.admin.eval.task' in env:` —— **该模型不存在**（B 套是 `edu.admin.eval.template`）⇒ 死分支，KPI 永远走 `elif` 读 `edu.admin.eval.template`。
- 学生首页卡片 `batch2.py:302-305` —— `('eval/my','我的评分')`、`('eval/review','评教填答')` **指向 B 套**；`_YONGYUE_CARDS` 与「成长 Growth」分组（`batch2.py:829-834`）也只挂了这两个。
- 学生帮助中心 `views/help_center.xml:98` ——「六、评教填答 → 进入 `/eval/review`」**教学生用 B 套**。
- `/my/evaluation` 的教师待办卡 `batch2.py:632-638` —— 读 `edu.eval.task`，链接 `/my/evaluation`（A 套）。

**判定（与 t1 一致）**：引擎结构真重复（模板 + 评分类 + 打分）；**当前学生可见面指向 B，教师可办面指向 A**，两边各有一点数据/能力，是典型的「改名式并存」。

---

## 3. 留哪套：推荐与理由（含反向方案的代价）

### 3.1 推荐：留 A 套（`edu_portal` / `edu.eval.*`）

| # | 理由 | 证据 |
|---|---|---|
| 1 | **零数据迁移**。B 套 0/0/0，留 A 则"迁移"是空操作，从根上消灭"迁移丢数据/迁移写错"这一类风险；A 的 18 行不需要改模型、不需要改语义 | §2.1 |
| 2 | **存量被打过一遍的是 A**。A 有 1 张已完成的表（90 分/优秀）走过「建表 → 打分 → 存档 → 学生可见」全链路；B 从未有数据落过（`/eval/fill/1` 恒 303） | §2.1「B 套 0 行的后果」 |
| 3 | **归属与依赖方向更干净**。`edu_eval` 是唯一「反向依赖 `edu_portal` 的评估模块」；把引擎留在门户中枢 `edu_portal`，可以让 `edu_eval` 整体降级为弃用壳，避免"依赖方持有主引擎"的倒挂 | `edu_eval/__manifest__.py` depends=`edu_portal` |
| 4 | **A 的独有语义对新生/实习类评估是刚需**：等级线（及格/优秀）、雷达图、`visible_to_student` 开关、`approved_by` 审批留痕、CSV 导出。这些在 B 里从零补；反过来 B 的独有能力（权重、整班、匿名、状态机+截止日）**在 A 上的补法更轻**（§4 全是增量字段 + 1 个新模型，不动存量语义） | §2.1 |
| 5 | **学生的"历史"不需要换页**。学生现在在 `/my/evaluation` 上已经看得到自己的 90 分；留 A 则这条历史纹丝不动，只改导航指向 | §2.3 |

### 3.2 反向方案（留 B）的代价 —— 为什么不是它

1. **必须迁移 A 的 18 行**，且迁移中有一处**无法从数据复原**的字段：`edu.eval.task` **不记录打分人**，而 B 的 `edu.admin.eval.score.scorer_id` 是 `required`。要么编造一个打分人（制造假归因），要么放宽 B 的 required（动 schema），要么把任务降级为"无主记录"。任一选择都需要人拍板 —— 合并动作本身**新增了一个必须拍板的数据归属问题**。
2. **语义缺口**：A 的模板没有 `period`（周期在 task 上），B 的模板 `period` 是 `required`。3 个模板里有 2 个（实习/新生）在 A 下没有任务 ⇒ 迁到 B 后周期**无来源**。
3. **维度无处安放**：A 的「教师评/自评/TA评/牧者评」在 task 级；B 只有 `type_code`。留 B 就必须新加 `evaluator_role`，否则 6 口径里的 3 个（新生/学生综合/实习）都会丢掉"谁在评"。
4. **学生入口要改址**：学生的历史分数会从 `/my/evaluation` 迁到 `/eval/my`（不同页面、不同呈现口径），属于用户可见的变化，需要额外的迁移核对与告知。
5. 引擎能力仍要补：等级线 / 雷达图 / `visible_to_student` / 审批留痕 / CSV —— 与留 A 要补的 4 项（权重/整班/匿名/状态机）工作量同量级，但**多背了 18 行数据迁移**。

> 结论：两套都要补字段、都要改路由，差别在于**留 A 不搬数据、留 B 必须搬数据且引入一处不可复原字段**。因此推荐留 A。
> 若校长/队长从"业务形态"出发更认同 B（`type_code` 即口径、天然多被评对象），请按拍板 1 明确后再实施 —— 那时的施工顺序见 §5.2。

---

## 4. 统一模型（字段表）

### 4.1 模型清单（最终态）

| 模型 | 归属模块 | 处置 |
|---|---|---|
| `edu.eval.template` | `edu_portal` | **保留并扩展**（唯一评估表模板） |
| `edu.eval.template.line` | `edu_portal` | **保留并扩展**（唯一评分项） |
| `edu.eval.task` | `edu_portal` | **保留并扩展**（唯一"表"= 一个被评对象 × 一个维度/评者） |
| `edu.eval.score` | `edu_portal` | **保留不动骨架**（唯一打分明细；`UNIQUE(task_id,template_line_id)` 保留） |
| `edu.eval.campaign` | `edu_portal` | **新增**（评价活动/轮次：批量场次的容器） |
| `edu.admin.eval.template` / `.item` / `.score` | `edu_eval` | **冻结退役**：表与模型保留、菜单隐藏、路由重定向、登记弃用台账；**不删** |

### 4.2 字段表（增量部分逐字段写清"现状 → 变更"）

**`edu.eval.template`（评估表模板）**

| 字段 | 现状 | 变更 | 说明 |
|---|---|---|---|
| `type_code` | Selection **3 值** | **3 → 6 值** | 见 §4.3 承载表 |
| `target_kind` | — | **新增** Selection `('student','学生')` / `('teacher','教师')`，compute store，由 `type_code` 派生 | 被评对象；评教类为教师 |
| `anonymous` | — | **新增** Boolean，默认 False | 匿名评教；仅 `target_kind='teacher'` 时有意义 |
| `visible_to_student` | 已有 | 不变（语义扩为"该口径是否对学生展示"） | 与拍板 3 联动 |
| `total` / `pass_line` / `excellent_line` | 已有 | 不变 | 等级线 |
| `weight_total` | — | **新增** Float compute（= Σ`line.max_score × line.weight`） | 加权满分，用于百分制归一（雷达图用） |

**`edu.eval.template.line`（评分项）**

| 字段 | 现状 | 变更 | 说明 |
|---|---|---|---|
| `weight` | — | **新增** Float，默认 **1.0**，`> 0` 约束 | 吸收 B 套的「倍率」；加权总分 = Σ(得分 × 权重)。默认 1.0 ⇒ **存量 12 行的语义与数值完全不变** |
| `name` / `max_score` / `sequence` | 已有 | 不变 | |

**`edu.eval.campaign`（评价活动 —— 新增模型）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | Char, required | 活动名称，如「2026秋 学生日常量化（第1轮）」 |
| `template_id` | m2o `edu.eval.template`, required, ondelete restrict | 用哪张表 |
| `type_code` / `target_kind` / `anonymous` | related store 自模板 | 便于筛选与权限判定 |
| `period` | Char，默认 `2026秋`（沿用现有 `eval.task.period` 写法） | 周期 |
| `due_date` | Date | 截止日（吸收 B 的 `due_date`） |
| `state` | Selection `draft(草稿)/open(进行中)/closed(已结束)`，默认 draft | 吸收 B 的状态机 |
| `scope` | Selection `all(全体)/batch(按班级)/student(单人)` | 活动覆盖面 |
| `batch_id` | m2o `op.batch`，nullable | `scope='batch'` 时必填 |
| `anonymity_salt` | Char，**`groups='base.group_system'`** | 匿名令牌的盐；非超管读不到该字段 |
| `task_ids` | One2many `edu.eval.task.campaign_id` | 活动下的 N 张表 |
| `sheet_count` / `score_count` | Integer compute | 统计 |
| 动作 | `action_open()` / `action_close()` / `action_draft()` | 发布前校验 `template.line_ids` 非空；已有打分的活动不允许撤回草稿（照抄 B 的守卫语义） |

**`edu.eval.task`（一张"表"）**

| 字段 | 现状 | 变更 | 说明 |
|---|---|---|---|
| `campaign_id` | — | **新增** m2o，nullable | **存量任务 1 保持 NULL**（独立表模式，读取口径兼容，零迁移） |
| `student_id` | m2o `op.student`, required | **required → 可选** | 评教表的被评对象是教师，此列留空 |
| `teacher_id` | — | **新增** m2o `op.faculty`, nullable | 评教表的被评教师 |
| `evaluator_type` | Selection **4 值** | **4 → 5 值**（补 `('student','学生评')`） | 见 §4.4 |
| `reviewer_token` | — | **新增** Char, index, `groups='base.group_system'` | 匿名评教的去重令牌（§4.6），**不落 user id** |
| `reviewer_id` | — | **新增** m2o `res.users`, nullable, `groups='base.group_system'` | **仅非匿名**场景的填表人留痕（审计）；匿名活动恒为空 |
| `due_date` | — | **新增** Date, nullable | 冗余自活动，便于单表页显示 |
| `state` / `period` / `template_id` / `total_score` / `grade` / `approved_by` / `approved_date` | 已有 | 不变 | 存量语义不动 |
| 约束 | — | **新增**：`teacher_id` 与 `student_id` **至多一个**（评教表=教师；其余=学生）；`campaign_id` 非空时要求 `template_id = campaign.template_id` | 防脏数据 |

**`edu.eval.score`（打分明细）**

| 字段 | 现状 | 变更 |
|---|---|---|
| `task_id` / `template_line_id` / `score` | 已有 | **不变** |
| `UNIQUE(task_id, template_line_id)` | 已有 | **保留**（这是整班模式下"一表=一人"能成立的前提） |

### 4.3 六种口径如何承载（`type_code` + `target_kind`）

| 口径 | `type_code`（新增值加粗） | `target_kind` | 表级 `evaluator_type` | 评者身份 | 匿名 |
|---|---|---|---|---|---|
| 新生综合测试 | `freshman`（已有） | student | `teacher` | 教师 | 否 |
| 学生综合评估 | `student`（已有） | student | `teacher` / `self` / `ta` / `pastor` | 教师 / 学生本人 / TA / 牧者 | 否 |
| 实习同工评估 | `intern`（已有） | student | `self` / `ta` / `pastor` | 同上 | 否 |
| **学生日常量化** | **`student_daily`** | student | `teacher` | 教师 | 否 |
| **教师评教** | **`teacher_review`** | teacher | **`student`** | 学生（逐位评价教师） | **是** |
| **助教评教** | **`ta_review`** | teacher | **`student`** | 学生 | **是** |

**为什么"口径"用 `type_code`、"谁在评"用 `evaluator_type` 两个字段分开**：B 把两者塞进一个 `type_code`（`teacher_review` 既表示口径又表示"评者是学生"），一旦要表达「助教评学生」或「牧者评实习」就没有位置；分开之后 6 口径 × 5 维度都是可组合的，且 A 的存量语义（`type_code`= 口径、`evaluator_type`= 维度）**一个字都不用改**。

### 4.4 评分维度如何承载

沿用 `edu.eval.task.evaluator_type`（表级，一个维度一张表 → 一个学生可有 5 张并存的表），并补第 5 值 `student`（学生评）。聚合口径：
- 按 (`template.type_code`, `task.evaluator_type`) 分组算平均 → 雷达图的轴（现有 `/my/evaluation/results` 就是按 `type_code` 分组的，实施时把轴改成 `evaluator_type` 或"口径 × 维度"，属可见变化，列入 §10 验收）。
- 加权总分 = Σ(`score.score × line.weight`)，等级线按 `weight_total` 归一后比较（**存量 12 行的 weight=1.0，归一后与原 `total=100` 口径完全等价**）。

### 4.5 为什么不把 `edu.eval.score` 拍平（保留 `UNIQUE(task_id, template_line_id)`）

B 的 `score` 是"行级带被评对象"（一行 = 活动 × 评分项 × 学生/教师 × 打分人），A 的是"表级带被评对象"（表 = 学生 × 维度，行只到评分项）。两者不能同时保留一条 `UNIQUE(task_id, template_line_id)`。
**选择保留 A 的约束**，理由：
1. 存量 5 行**零改动**（拍平就必须改写这 5 行 + 动约束，风险与工作量都落在"有数据的那个"上）。
2. 整班打分的需求用**新模型 `campaign` 承载**：一个活动 = N 张表（N 个 `task`），一屏渲染、一次 POST（key 形如 `score_<task_id>_<line_id>`），落库仍是每表逐项 upsert —— 与现有 `/my/evaluation/task/<id>/save` 完全同构，**打分行的写路径只有一条**。
3. 代价：整班 30 人 = 30 行 `task`（本校学生总量 4 人，量级无压力）；换来的是"行级对象唯一性"不会出现 NULL 归属歧义。

### 4.6 匿名评教如何不落身份

**设计**：匿名活动的表（`task`）不写 `reviewer_id`，只写
`reviewer_token = HMAC-SHA256(campaign.anonymity_salt, str(uid))[:32]`。

| 需求 | 如何满足 |
|---|---|
| 去重（同一个人对同一位教师只能交一次） | 应用层按 `(campaign_id, teacher_id, reviewer_token)` 查重 + 唯一约束；也可让同一学生在同一活动下复用同一张表 |
| 不落身份 | 库内**没有任何"令牌 → 用户"的字段或接口**；`anonymity_salt` 与 `reviewer_token` 字段均 `groups='base.group_system'`，普通内部用户与门户用户 read 时字段被剔除 |
| 防"用令牌反查人" | 不提供任何按令牌检索的视图/动作/CSV；salt 仅超管可见且不可导出 |
| 防小样本反推 | 结果页在**参评人数 < 3** 时不显示均分与人数（只显示"样本不足"）；该门槛做成系统参数（默认 3），见拍板 2 |
| 审计（可选） | 若学校要求"出事能追责"，则改用拍板 2 的候选 B（落 `reviewer_id` + 字段级限制），**二者不可兼得** |

**诚实声明（写进本设计，不做隐瞒）**：本校规模是 2 位教师 / 4 名学生（本次实测 `op_faculty=2`、`op_student=4`），在这种量级下"完全匿名"在数学上做不到（谁没交一目了然）。本设计只承诺**技术层不落身份 + 界面不暴露 + 汇总门槛**，不承诺统计意义上的匿名。

---

## 5. 存量数据迁移

### 5.1 方案 A（推荐，本设计的默认路径）：**暂不迁移**

| 对象 | 行数 | 处置 | 回滚 |
|---|---|---|---|
| `edu.admin.eval.*`（B 套） | 0 / 0 / 0 | **无数据可迁**；表/模型/ACL/规则原样冻结 | 无需回滚 |
| `edu.eval.template` | 3 | 不动；（拍板落地后可选）给 `weight` 留默认 1.0 | 无 |
| `edu.eval.template.line` | 12 | 不动 | 无 |
| `edu.eval.task` | 1 | 不动，`campaign_id` 保持 **NULL** | 无 |
| `edu.eval.score` | 5 | 不动 | 无 |

**"先只并入口、不并数据"就是本方案的完整形态**：菜单/路由/卡片先收敛（学生看到"一个评估入口"），引擎能力按 §4 增量补齐，**数据一行不搬**。这也是唯一能把"零删除 + 可回滚"做到零成本的方向。

**读取口径（兼容层）**：任何按"活动"聚合的页面，必须同时覆盖两类表 —— `task.campaign_id = <活动>` **或** `task.campaign_id is NULL`（存量独立表）。实现时用一个 helper（`_campaign_tasks(campaign)`）统一，避免页面各写各的。

### 5.2 方案 B（备选，仅当拍板 1 选"留 B"时执行）

**映射表**（此处只给映射与已知缺口，不推荐启用）：

| A 套对象 | 目标（B 套） | 映射 | 已知缺口 |
|---|---|---|---|
| `edu.eval.template` 3 行 | `edu.admin.eval.template` 3 行 | `name` 原样；`type_code` 原值（需先把 B 的 `TYPE_CODES` 扩到 6 值）；`item_ids` ← lines | **`period` 无来源**（2 个模板无任务） |
| `edu.eval.template.line` 12 行 | `edu.admin.eval.item` 12 行 | `name→label`、`max_score`、`sequence` 原样；`weight = 1.0` | 无 |
| `edu.eval.task` 1 行 | `edu.admin.eval.template` 1 行（作为"活动"）+ 5 行 `score` | `type_code` 取模板 type；`period='2026秋'`；`state done→closed` | **`scorer_id` 无来源（A 不记录打分人）** ⇒ 必须三选一：① 编造打分人（假归因，不推荐）② 放宽 B 的 `required` ③ 标记"迁移前未记录打分人" |
| `task.evaluator_type='teacher'` | 无对应列 | 必须**新增** `evaluator_role`（否则维度丢失） | 维度语义在 B 里无家可归 |

**迁移执行约束（无论方案 A/B 都适用，供实施任务照抄）**：
- 脚本必须：`--dry-run` → 幂等（按来源 id 去重）→ **台账**（`docs/audit/` 或 `scripts/` 下的台账文件，逐条记 `来源表:id → 目标表:id | 跳过原因`）→ `--rollback`。
- `--rollback` **只允许删台账内"本次迁移新建"的记录**，且若目标记录已被后续业务引用（例如已有打分/申请）则**拒绝回滚并报错**（对齐 t5 打卡合一的既有约定）。
- 禁止：`DROP TABLE` / 批量 `DELETE` / 任何 `unlink` 存量业务行。
- 迁移前后必须给「计数对照表」：`edu.eval.*` 与 `edu.admin.eval.*` 各表前后条数（方案 A 就是"前后完全一致"）。

---

## 6. 门户与后台入口归属

### 6.1 门户路由（目标态）

| 路由 | 目标行为 | 归属 | 备注 |
|---|---|---|---|
| `/my/evaluation` | **唯一入口**（角色自适应） | A | 学生 = 「我的得分」+「待我评教」两区块；教师/教务 = 活动列表 + 统计卡 |
| `/my/evaluation/campaign/<id>` | **新增**：活动详情（整班打分表 / 评教汇总） | A | 整班打分页；一屏 N 张表，一次 POST |
| `/my/evaluation/campaign/<id>/save` | **新增**：POST 写入口（csrf） | A | 校验活动 `state='open'`；upsert 语义同现有单表保存 |
| `/my/evaluation/task/<id>` + `/save` | 保留 | A | 单表页（存量任务 1 继续走这里） |
| `/my/evaluation/new`、`/create`、`/results`、`/results.csv` | 保留 | A | 结果页加"活动 × 维度"轴（实施时定） |
| `/eval/my` | **303 → `/my/evaluation`** | B | 老书签不 404 |
| `/eval/review` | **303 → `/my/evaluation`** | B | 同上 |
| `/eval/review/<id>` | **303 → `/my/evaluation`** | B | |
| `/eval/review/<id>/submit`（POST） | **303 → `/my/evaluation`** | B | POST 也要接住，否则老页面提交 404 |
| `/eval/fill/<id>` + `/save`（POST） | **303 → `/my/evaluation`** | B | 同上 |

**303 的实现位置**：`edu_eval` 自己的控制器（本模块即将退役，改动不外溢到 `edu_portal_main.py`），保留 CSRF 装饰器与 method 声明不变，只把返回体换成 `request.redirect('/my/evaluation')`（Odoo 的 `redirect` 默认 303）。路由**不删**（删了就 404，违反"重定向"要求）。

### 6.2 后台菜单（目标态，由 t2 执行，本设计只给施工要求）

- **唯一根菜单**：588「综合评估」（容器，`base.group_user`；改名未落）。
- 589 模板管理 → `action_edu_eval_template`（`edu.eval.template`）**保留**。
- 590 评估任务 → `action_edu_eval_task`（`edu.eval.task`，`list,form,pivot`）**保留**；新增子项「评价活动」→ `edu.eval.campaign` 的新动作（承载整班/评教活动）、「结果分析」可复用 590 的 pivot（现有 action 已含 `pivot`）。
- 597「行政评估」**隐藏**（`active=False` 或收窄到 `base.group_system`，二选一由 t2 定；本设计推荐 `active=False` 以便一键回滚）。
- B 的三个动作 738/739/740 **不删**：保留在库中，登记弃用台账。
- 禁止：`unlink` 任何 `ir.ui.menu`。

### 6.3 卡片 / 帮助中心 / 待办的改点清单（实施任务用，本轮不动）

| 位置 | 现状 | 目标 |
|---|---|---|
| `batch2.py:302-305` `_YONGYUE_CARDS` | `('eval/my','我的评分')`、`('eval/review','评教填答')` 两张卡 | 合并为一张 `('my/evaluation','我的评估')`，描述写"我的得分与待我填写的评教" |
| `batch2.py:443-444` 卡色表 | `eval/my`、`eval/review` 两条 | 换成 `my/evaluation` 一条 |
| `batch2.py:829-834`「成长 Growth」分组 | `eval/my`、`eval/review` | 换成 `my/evaluation` |
| `help_center.xml:98` 学生版「六、评教填答」 | 链接 `/eval/review` | 改为 `/my/evaluation`，文案改为「六、我的评估」 |
| `batch2.py:628-638` 教师待办卡「评估待打分」 | 读 `edu.eval.task state='scoring'`，链 `/my/evaluation` | 保留，口径扩为"活动 `state='open'` 或表 `scoring`" |
| `batch2.py:1805-1814` 教师工作台 KPI「进行中评估」 | 死分支 `edu.admin.eval.task` → 回退 `edu.admin.eval.template state='open'`（B 口径） | 改为单一口径：`edu.eval.campaign state='open'`；**顺手删掉死分支引用** |
| `views/edu_portal_templates.xml:520` 文案「综合评估：选模板→生成打分表→逐项打分→保存」 | 保留 | 文案随新入口微调（可选） |

### 6.4 教师端 KPI 口径统一

合并后**只有一套口径**：
- 「进行中评估」= `edu.eval.campaign(state='open')` 的条数（无活动时回退 `edu.eval.task(state='scoring')`）。
- 禁止再引用 `edu.admin.eval.*`（B 套退役后其数据恒为 0，引用它只会得到"永远 0"的假 KPI —— 正是 `batch2.py:1807` 今天的形态）。

---

## 7. 权限矩阵

| 角色 | 模板 / 活动 / 表 | 打分写入 | 评教写入 | 读结果 | 导出 | 特殊字段 |
|---|---|---|---|---|---|---|
| 学生 `base.group_portal` | **只读自己那张表**（口径白名单 + `visible_to_student` 双重过滤，控制器 sudo + 显式域 = 现状形态） | 不允许（A 现状即如此） | 允许：仅 `type_code ∈ {teacher_review, ta_review}` 且活动 `state='open'`，写 `reviewer_token` | 只看自己；**评教均分仅在参评 ≥ 3 时显示** | 不允许 | 读不到 `reviewer_token` / `reviewer_id` / `anonymity_salt` |
| 教师 `base.group_user` | 读全部模板/活动/表 | 允许：活动范围内（`scope='batch'` 限本班）整班打分 | — | 读本班 + 自己相关的表 | 允许（CSV 现状为 staff 全量，实施时按需收窄） | 同上 |
| 教务 `backoffice` | 读 + 建活动/发布/关闭 | 允许 | — | 全部 | 允许 | 同上 |
| 管理员 `base.group_system` | 全部 | 全部 | — | 全部 | 全部 | **可读** `reviewer_token` / `reviewer_id`（审计位，页面不展示） |

**落地方式（最小改动、零权限回归）**
1. **保持 A 的现状**：门户页读走 `sudo()` + 控制器内显式域过滤；写入走控制器 `auth='user'` + `csrf=True` + 身份校验。B 的 `ir.rule` 不迁到 A（避免 sudo 与规则语义打架）。
2. **纵深防御（可选，非必需）**：给 `edu.eval.*` 补 `base.group_portal` 只读 ACL + "只看自己"的 `ir.rule`（`task.student_id.user_id = uid`）。**若补，必须同时确认 sudo 路径不受影响**（sudo 绕过规则，行为不变）。
3. 新增字段全部用 `groups='base.group_system'` 限制：`campaign.anonymity_salt`、`task.reviewer_token`、`task.reviewer_id`。
4. 禁止：把 `edu.eval.score` 的 ACL 放宽给 portal（现有 5 条打分与将来的整班数据都不应经 ORM 暴露给学生）。

---

## 8. 失败处理与回滚

| 层 | 步骤 | 失败特征 | 回滚 |
|---|---|---|---|
| 模型/字段 | `bash scripts/safe_upgrade.sh -u edu_portal`（首次装新模型也用 `-u`，不要 `-i`） | EXIT≠0、Traceback、"unknown field" | `git revert` + 再 `-u`；**新增列/表留在库中无害**（Odoo 不删列） |
| 路由 | 在 `edu_eval` 内把 `/eval/*` 改为 303 | 门户页 5xx / 循环重定向 | revert `edu_eval` 控制器 + `-u edu_eval` |
| 菜单 | 597 隐藏（t2 的脚本） | 教务看不到「评估」子树 | 按 t2 的 `--rollback` 还原（只还原 active/groups） |
| 数据 | **本设计不写任何业务数据** | — | 无需数据回滚 |
| 回归 | `python3 tests/smoke/ux_v3_route_matrix.py`（含 `/my/evaluation`、`/eval/my`、`/eval/review` 断言） | FAIL / WARN 全表 | 按 §6 改断言（t7/t9 负责） |

**已知会变红的既有断言（实施时必须同步改，否则门禁假红）**：`tests/smoke/ux_v3_route_matrix.py:105,128,129,151` 现在断言 `/eval/my`（ALL5）、`/my/evaluation`（ALL5）、`/my/evaluation/results`（ALL5）、`/eval/review`（fac/bo）—— 3xx 跳转后 200 仍算 PASS，因此 303 重定向**不会**立刻变红；但"重复入口消失"这一条需要**新增**断言（`/eval/my` 必须 303，且不再出现在学生卡片里）。

---

## 9. 对学生的可见变化（逐条）

1. **导航卡**：原来的「我的评分」+「评教填答」两张卡 → 合并为**一张「我的评估」**，落在 `/my/evaluation`。
2. **老链接**：`/eval/my`、`/eval/review` 打开后 **303 跳到 `/my/evaluation`**（不 404、不报错；帮助中心与浏览器书签都还能用）。
3. **历史得分不变**：`王小明 | 学生综合评估 | 教师评 | 2026秋 | 90 | 优秀 | 已完成` 这条记录**显示位置与数值都不变**（实测现在就在 `/my/evaluation`）。
4. **新增区块**：`/my/evaluation` 上出现「待我评教」区块（活动 `state='open'` 且口径为评教时才有内容；当前 0 条 ⇒ 显示空态文案，不报错）。
5. **评教从"具名"变"匿名"**：帮助中心文案同步改为「匿名评教」，结果页在参评人数 < 3 时只显示"样本不足"。
6. **口径变化（取决于拍板 3）**：新生综合测试 / 学生日常量化是否也对学生展示 —— 今天**只展示 `type_code='student'`**（这是 A 的既有设计，见 `docs/plans/eval-design.md` §三），合并后是否放开由拍板 3 定。

---

## 10. 验收口径（供实施任务与 t7 独立验证）

| # | 验收项 | 判据 |
|---|---|---|
| 1 | 升级干净 | `bash scripts/safe_upgrade.sh -u edu_portal,edu_eval` EXIT=0、无 Traceback |
| 2 | 单一后台入口 | `ir.ui.menu` 根菜单里只剩一个「评估」；597 `active=False`；**菜单记录数不变**（无 unlink） |
| 3 | 单一学生入口 | 学生登录 `/my/home`：评估类卡片 = 1 张，指向 `/my/evaluation`；`/eval/my`、`/eval/review` 均 303 |
| 4 | 零数据损失 | `edu.eval.*` 与 `edu.admin.eval.*` 各表条数**与 §2.1 完全一致**（3/12/1/5 与 0/0/0） |
| 5 | 学生历史不变 | 学生 `/my/evaluation` 仍显示 `王小明 … 2026秋 … 90 … 优秀 … 已完成` |
| 6 | 6 口径可建 | 6 个 `type_code` 都能建模板/活动，其中评教类（`teacher_review`/`ta_review`）自动 `target_kind='teacher'` |
| 7 | 匿名不落身份 | 评教表的 `reviewer_id` 恒为空、`reviewer_token` 非空；普通内部用户与学生账号**读不到** `reviewer_token`/`anonymity_salt`（字段级 groups） |
| 8 | 权重兼容 | 存量 12 个评分项 `weight=1.0`；加权总分与改造前口径一致（任务 1 仍为 90/优秀） |
| 9 | 路由矩阵 | `python3 tests/smoke/ux_v3_route_matrix.py` 无 FAIL；`/eval/*` 全部 303→200 |
| 10 | 回滚可用 | 回滚步骤逐条实测后写进实施报告（退代码 + `-u` 后站点与菜单回到收口前） |

---

## 11. 待拍板问题（3 项，业务口径类，本文不自行裁定）

**拍板 1：引擎到底留哪套？**
- 候选 A（本文推荐）：留 `edu.eval.*`（`edu_portal`），B 套冻结退役；零数据迁移。
- 候选 B：留 `edu.admin.eval.*`（`edu_eval`），迁 A 的 18 行；代价见 §3.2（含"打分人不可考""模板周期无来源"两处必须人定的缺口）。
- **影响面**：决定 18 行数据是否搬、学生历史分数换不换页、补哪些字段、t6 的 code-map 怎么写、t7 的验证口径。
- 需要拍板人：校长 / 队长（t1 §4-1 已把它列为待拍板第 1 项）。

**拍板 2：匿名评教的口径与最小展示样本数？**
- 候选 A（本文推荐）：只落不可逆令牌（`reviewer_token`），不落 user id；参评 < 3 不显示均分。
- 候选 B：落 `reviewer_id` + 字段级 `groups='base.group_system'` 限制（库内可追责、界面对外匿名）。
- 候选 C：两者并存（令牌用于去重、user id 用于审计）——**注意这与"不落身份"直接冲突**。
- **影响面**：决定 `edu.eval.task` 的字段、谁能查评教来源、出事时能否追责；也影响学生是否愿意如实评教。

**拍板 3：哪些口径对学生端可见？**
- 候选 A（现状）：只 `type_code='student'`（学生综合评估）且 `visible_to_student=True` 时可见。
- 候选 B：`student` + `freshman` + `student_daily` 三类可见（学生能看到自己的新生测试与日常量化分）。
- 候选 C：除评教结果外全部可见。
- **影响面**：学生端结果页的列表内容、"有没有看到分数"这一类家长/学生投诉的来源。

---

## 12. 实施前置条件

1. **拍板 1 落地**（引擎归属）—— 未拍板不得开工。
2. **t2 先完成菜单容器**：588 保留、597 隐藏（本设计的后台归属依赖它）。
3. **新增 Selection 值必须先 `-u` 再写数据**：`type_code` 3→6、`evaluator_type` 4→5 都是 Selection 扩展，先升级建列再落数据，否则写入报 `invalid value`。
4. **新模型 `edu.eval.campaign` 用 `-u` 升级**（`-i` 对已装模块不会重载 data/view，会制造"升级成功但看不到"的假象）。
5. **演示/测试数据标记**：任何新造的样例必须带【演示】；冒烟数据带【冒烟】。存量 3 个模板已带【演示】，任务 1 未带标记 —— 按红线保留，不动。
6. **不得触碰**：`openeducat_erp/`、B 套的表与记录、`tests/smoke` 的既有断言（改断言属 t9/t7 的活，需协调）。
7. **文案**：新增/改动的一切用户可见文案必须中文；若需对外联系方式，只允许 `scrtsschool@gmail.com`。

---

## 附：本次实测的原始读数（可复现）

```
# 计数（2026-09-17 11:06 CST）
edu_eval_template 3 | edu_eval_template_line 12 | edu_eval_task 1 | edu_eval_score 5
edu_admin_eval_template 0 | edu_admin_eval_item 0 | edu_admin_eval_score 0
op_faculty 2 | op_student 4

# 菜单（id 588/589/590 与 597/598/599/600，groups 均为 base.group_user）
588 综合评估 seq71 → 589 模板管理(act726) / 590 评估任务(act727)
597 行政评估 seq72 → 598 评估模板(act738) / 599 打分记录(act739) / 600 结果分析(act740)

# 路由（curl -c/-b cookie，5 个角色）
/my/evaluation 200(5/5 角色) | /my/evaluation/results stu&par=303、fac&bo&admin=200
/eval/my 200(5/5) | /eval/review 200(5/5) | /eval/fill/1 303(5/5)
/my/evaluation/task/1 stu=303、fac/bo=200 | /my/evaluation/results.csv stu=303、fac/bo=200
```

> 未核项：B 套整班打分页（`/eval/fill/<id>`）与匿名评教表单的**端到端 UI 行为**未实测（0 数据 ⇒ 无法进入）；B 套的 JS/CSS 资源（`edu_eval/static/src/js/eval_portal.js`）行为未核。
