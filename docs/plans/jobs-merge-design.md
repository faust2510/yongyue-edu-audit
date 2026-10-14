# 岗位两套合并设计 —— 一套实体 + 面向类型（edu.job.posting）
> **状态**：`设计中` ｜ **主题**：`岗位合并` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 任务：t4 ②（岗位收口设计）｜ **本轮只出设计**：不改代码、不动菜单、不改数据
> 实测时间：**2026-09-17 11:06 CST**｜环境：docker 项目 `edu19-clone`（库 `edu19`，http://127.0.0.1:8069）
> 方法：只读 SQL 读数 + 公开页/登录页逐条 HTTP 实测 + 源码核对（未实测项一律标「未核」）
> 上游依据：`docs/audit/feature-overlap-audit.md`（t1）§1.3 / §1.6 / §2.3 / §3（585 保留为独立根「招聘就业」）
> 历史设计：`docs/plans/jobs-design.md`（`edu.job.posting` 的交付摘要，✅ 已交付 2026-08-23）

---

## 0. 结论速览（TL;DR）

| 问题 | 结论 |
|---|---|
| 合并方向 | **以 `edu.job.posting`（+`edu.job.application`）为唯一实体**，把「校友」收敛为它的一个**面向类型字段 `audience`**（§3） |
| `edu.alumni.job` | **冻结退役**：表与模型保留、无删；3 条记录**迁移**为 3 条 `posting`（`audience='alumni'`），带台账与 `--rollback` |
| 25 份申请 | **零改动**：全部挂在 `posting 1`（校园岗），迁移只**新增 3 行** posting，不触碰任何申请行 |
| 门户 URL | `/alumni/jobs` **保留 200**（数据源换成 posting 的校友面向）；`/alumni/job/card` **303 → `/alumni/jobs`**；`/campus/jobs` 全链路不变 |
| 后台入口 | 唯一根菜单 **585「招聘管理」**（t1 施工图：保留为独立根，归入教务 12 根里的「⑧ 招聘就业」），新增第三个子项「校友岗位」（校友面向筛选视图） |
| 回滚 | `--rollback` 只删**台账内本次新建的 3 行**（且必须未被申请引用）；代码层 `git revert` + `-u` |
| 待拍板 | 3 项（§10）：待定岗可见性 / 币种口径 / 过期岗处理 |

---

## 1. 目标 / 非目标

**目标**
- 全站**只有一个岗位实体**（`edu.job.posting`）、一个申请流水（`edu.job.application`）、一套后台维护入口。
- 「校友岗位」不再是一张独立表，而是 posting 的一个**面向（audience）**；`/alumni/jobs` 仍然只有校友岗位、`/campus/jobs` 仍然只有校园岗位。
- 3 条校友岗位**内容零丢失**（名称/编号/薪资/周期/起止日/状态逐字段可对照）。
- 25 份申请与其投递链路（`/campus/jobs/<id>/apply`）一行不动。
- 消除既存错位：今天 `/alumni/job/card`（导航名「校友招聘」）**渲染的是校园岗位**。

**非目标**
- 不删除 `edu.alumni.job` 的表/模型/记录（红线）。
- 不重做公开站导航（`website_menu` 属 t2 / 后续任务的收口范围，本设计只列目标与依赖）。
- 不做 `hr_job` / 原生 `website_hr_recruitment`（`/jobs`）的功能对齐 —— 原生侧 0 数据，t1 已判定为「原生噪音」，处置是**导航层下掉**，不是本设计的实体合并。
- 不引入投递流程改造（honeypot/csrf/字段截长全部沿用）。

---

## 2. 现状与四层证据（2026-09-17 11:06 实测）

### 2.1 模型与数据

| | 校友岗位（A 套） | 招聘岗位（B 套） |
|---|---|---|
| 模型 | `edu.alumni.job` | `edu.job.posting` + `edu.job.application` |
| 条数（实测） | **3** | **2** + **25** |
| 字段 | `name` / `code` / `salary` / `pay_period`(monthly,weekly,yearly) / `start_date` / `end_date` / `state`(recruiting,pending,closed) / `creator`(Char) | `name`/`department`/`location`/`salary_range`/`openings`/`description`(Html)/`publish_date`/`state`(draft,published,closed)/`posted_by`(m2o) + 申请：`name/phone/email/education/note/state/applied_date` |
| 字段语言 | **英文**（`Job Title`/`Salary Range`/`Payable`/`Recruiting`…） | 中文 |
| 状态分布 | recruiting 2 / pending 1 / closed 0 | published 2（draft 0 / closed 0） |
| 申请 | **0**（无申请关系字段） | 25（全部 `posting_id=1`、`state='new'`；posting 2 为 0） |

**3 条校友岗位逐行**（迁移必须逐字保留）：

| id | name | code | salary | pay_period | start_date | end_date | state | creator |
|---|---|---|---|---|---|---|---|---|
| 1 | 网络设计师 | JP002 | `$ 40,000.00 - $ 60,000.00` | yearly | 2026-08-08 | 2026-08-21 | recruiting | 校友 |
| 2 | 施工经理 | JP004 | `$ 50,000.00 - $ 60,000.00` | monthly | 2026-08-10 | 2026-08-21 | recruiting | 校友 |
| 3 | 电气设计工程师 | JP006 | `$ 30,000.00 - $ 45,000.00` | monthly | 2026-08-14 | 2026-09-11 | pending | 校友 |

**2 条招聘岗位**：`【演示】神学课程助教`（教务处/2 人）、`【演示】图书馆兼职管理员`（图书馆/1 人），均 `published`、`posted_by=1(admin)`、`publish_date=2026-08-23`。

> 语料来源推测（**未核**）：校友岗位的 `code=JP00x` + `$` 金额 + `creator='校友'` 像是从原站抓取/导入的历史数据；`scripts/` 下**没有**对应的种子脚本（`seed_jobs_demo.py` 只建 posting 的 2 条【演示】）。因此这 3 条**不能按"演示数据"处理**，迁移必须逐字段保真。

### 2.2 门户路由（逐条 HTTP 实测）

| 路由 | 数据源 | 匿名 | 学生 | 教师 | 教务 | 家长/管理员 |
|---|---|---|---|---|---|---|
| `/alumni/jobs`（+`?state=recruiting`） | `edu.alumni.job`（全量，按 state 过滤） | **200** | 200 | 200 | 200 | 200 |
| `/alumni/job/card` | **`edu.job.posting`**（`state='published'`） | **200** | 200 | 200 | 200 | 200 |
| `/alumni/job/list`（Backoffice 只读列表） | `edu.alumni.job` | 303（要登录） | **200** | 200 | 200 | 200 |
| `/campus/jobs` | `edu.job.posting`（`published`） | **200** | 200 | 200 | 200 | 200 |
| `/campus/jobs/<id>`、`/campus/jobs/<id>/sent` | `edu.job.posting` | 200 | 200 | 200 | 200 | 200 |
| `/campus/jobs/<id>/apply`（POST） | 写 `edu.job.application` | 公开可投 | — | — | — | — |
| `/jobs`（**原生** `website_hr_recruitment`） | `hr.job`（**0 条**） | 200（标题 `Jobs \| 永约学坊`） | 200 | 200 | 200 | 200 |

**页面内容实测（互不串台）**：`/alumni/jobs` 页面出现「网络设计师 / 施工经理 / 电气设计工程师」各 1 次，**不出现**两条校园岗位；`/campus/jobs` 出现「神学课程助教 / 图书馆兼职管理员」，**不出现**校友岗位。

### 2.3 网站导航（`website_menu` 实测）—— 岗位类入口共 6 个，其中 3 个指向同一个原生空页

| id | 名称 | url | 父级 | 备注 |
|---|---|---|---|---|
| 124 | Alumni & Careers | `/alumni/jobs` | 4 | 英文名（品牌残留） |
| 188 | 工作机会 | `#` | 4 | 容器 |
| 189 | 校友招聘 | `/alumni/job/card` | 188 | **名实不符：名为校友、实渲染校园岗位** |
| 190 | 校园工作 | `/campus/jobs` | 188 | 与 `/alumni/job/card` 同为 posting 数据 |
| 191 | 工作 | `/jobs` | 4 | 原生空页 |
| 197 / 198 | Jobs / Jobs | `/jobs` | 4 / 1 | 原生空页，**同一 url 三个入口** |
| 192 | 校友 | `/alumni` | 4 | 校友页（非岗位，保留） |

> 即：**数据层面 2 套实体（本次要合并）＋ 入口层面 6 个导航项指向 4 个 url，其中 3 个指向 0 数据的原生页**。导航层的收敛归 t2/后续任务，本设计给出目标（§6.3）。

### 2.4 后台菜单 / ACL

| 项 | 实测 |
|---|---|
| 根菜单 585「招聘管理」 | seq 70，`groups=base.group_user`，`web_icon=edu_portal,…,jobs.svg` |
| 子项 586「岗位管理」 | action 724 → `edu.job.posting`（`list,form`，表单含「申请记录」页签） |
| 子项 587「申请处理」 | action 725 → `edu.job.application`（`list,form`） |
| `edu.alumni.job` 的后台入口 | **没有**（无菜单、无 action、无视图、无 ACL） |
| `edu.alumni.job` 的管理界面 | 只有门户只读页 `/alumni/job/list`（模板 `roles.xml:1040` `edu_alumni_job_list`），**没有任何新增/编辑/删除入口** |
| ACL | `edu.job.posting` 1/1/1/1、`edu.job.application` 1/1/1/0（均 `base.group_user`）｜`edu.alumni.job` **无 ACL**（仅控制器 `sudo()` 可达） |

**可见英文（本设计登记为待修）**：`roles.xml` 的校友岗位列表模板里有 `My Job Posts` / `Recruiting` / `Pending` / `Closed` / `Alumni Salary` / `Payable At` 等**用户可见英文**（教务/教师可见），违反「用户可见文案必须中文」；`website_menu` 124 名为 `Alumni & Careers`。合并实施时一并中文化（`python3 scripts/check_english.py` must-fix 口径）。

### 2.5 判定

**真重复 + 名实错位**：
- 两张表都在表达「一个岗位 + 面向谁」，字段高度同构（name / 薪资 / 起止 / 状态 / 发布人）。
- 但**只有 posting 侧有维护入口、有 ACL、有申请关系、有中文文案**；`edu.alumni.job` 是"只能看、不能管"的遗留展示层。
- `/alumni/job/card` 已经把「校友」这颗导航项接到了 posting 上 —— 事实上的合并**当年做了一半**（`docs/plans/jobs-design.md`：「`/campus/jobs` 与 `/alumni/job/card` 从 hr.job 切换到本研模型」），留下的 `/alumni/jobs` 仍读旧表，于是出现"两个校友入口、两种数据源"。

---

## 3. 合并方向：推荐把「校友」做成 posting 的面向类型

### 3.1 推荐（正向：校友 → posting 的 `audience`）

| # | 理由 | 证据 |
|---|---|---|
| 1 | **业务权重压倒性**：25 份申请 + 完整维护链路在 posting；校友侧 0 申请、0 维护入口 | §2.1 / §2.4 |
| 2 | **反向合并要重写申请外键**：`edu.job.application.posting_id` → 25 行必须改指向，且 `/campus/jobs/<id>/apply` 公开投递链路要整体改造；且 `edu.alumni.job` 没有部门/地点/描述/申请关系字段，需要给旧表补 5+ 个字段才能承载 | §2.1 |
| 3 | **正向只需给 posting 加 1 个面向字段 + 4 个可选字段**，全部是增量，存量 27 行（2 岗位 + 25 申请）零改动 | §4 |
| 4 | **消灭名实错位**：`/alumni/job/card` 早就读 posting，合并后「校友」入口终于名副其实 | §2.3 |
| 5 | **公开页语义天然适配**：一张 posting 表、两种面向，`/campus/jobs` 与 `/alumni/jobs` 变成同一实体的两个过滤视图，不会再有第三套 | §6.1 |

### 3.2 反向方案（把 posting 搬进 `edu.alumni.job`）为什么不可取

1. 25 份申请是**真实投递数据**，改外键 = 动唯一在用的业务链路；一旦迁移中断，公开投递会挂。
2. `edu.alumni.job` 字段是英文、无 ACL、无后台菜单 —— 等于**把在用的东西搬到一个没有管理界面的壳里**，再补一堆字段和视图，工作量与风险都更大。
3. 公开页 `/campus/jobs` 的模板/详情/投递三件套都是围绕 `edu.job.posting` 写的（`edu_public/controllers/main.py:153-196`），反向要整体重写。

> 结论：**正向合并**（校友 → posting 面向类型）是唯一不需要重写在用链路的方案。

---

## 4. 统一模型（`edu.job.posting` 扩展）

### 4.1 新增字段

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `audience` | Selection `[('campus','校园'),('alumni','校友'),('both','两者')]`，index | `'campus'` | **合并核心**：面向类型。默认 `campus` ⇒ **存量 2 条不变**（/campus/jobs 依然只显示它们） |
| `reference` | Char | 空 | 岗位编号（校友侧的 `JP002/JP004/JP006`）；原生 `hr.job` 的"职位编号"口径 |
| `pay_period` | Selection `[('monthly','月薪'),('weekly','周薪'),('yearly','年薪')]` | `'monthly'` | 校友侧的计薪周期（公开页渲染成「（月薪）」）；**枚举与 `edu.alumni.job` 完全同义**，迁移零转换 |
| `deadline` | Date | 空 | 到期日（校友侧的 `end_date`）；`edu.job.posting` 目前没有截止概念 |
| `legacy_ref` | Char，index | 空 | 迁移锚点，形如 `edu.alumni.job:1`；**只由迁移脚本写**，用于 `--rollback` 精确定位本次新增的行，也给出"这批数据从哪来"的可查证据 |

### 4.2 扩展字段

| 字段 | 现状 | 变更 | 理由 |
|---|---|---|---|
| `state` | `draft / published / closed` | **+ `('pending','待定')`** | 校友侧 1 条 `pending` 今天**是公开可见的**（`/alumni/jobs` 显示并带「待定」徽标）。若映射成 `draft`，`/alumni/jobs` 会从 3 条变 2 条 = 用户可见的数据消失。新增枚举值可零损失承载；可见性策略见拍板 1 |
| `publish_date` | Date | 语义扩为"发布日期"（校友侧 `start_date` 迁入） | 不改字段 |
| `salary_range` | Char | 语义扩为"薪资范围"（校友侧 `salary` 原样迁入） | **字符原样**，不改金额/币种（拍板 2） |

### 4.3 不改动的部分

- `edu.job.application` **一个字段都不动**；25 行保持 `posting_id=1`。
- 两条【演示】校园岗位保持 `audience='campus'`、`published`。
- `/campus/jobs` 的列表/详情/投递模板保持结构，只在查询域（domain）上加一条过滤。

### 4.4 字段级对照（迁移后如何查回原值）

| 原 `edu.alumni.job` | 目标 `edu.job.posting` | 迁移规则 |
|---|---|---|
| `name` | `name` | 原样（含空格/大小写） |
| `code` | `reference` | 原样 |
| `salary` | `salary_range` | **原样字符**（含 `$` 与空格） |
| `pay_period` | `pay_period` | 枚举同名同义：`monthly/weekly/yearly` |
| `start_date` | `publish_date` | 原样（Date） |
| `end_date` | `deadline` | 原样（Date）；是否下架见拍板 3 |
| `state=recruiting` | `state='published'` | 语义：招聘中 = 已发布 |
| `state=pending` | `state='pending'`（**新增枚举值**） | 保留"待定"且公开可见（拍板 1） |
| `state=closed` | `state='closed'` | 语义一致（存量 0 条） |
| `creator='校友'`（文本） | `posted_by = NULL` + 台账记原值 | **不编造用户账号**：`posted_by` 是 `res.users`，把文本"校友"塞进去就是假归因；原值记在迁移台账 |
| （无） | `audience='alumni'` | 合并核心 |
| （无） | `openings=1`（字段默认） | 原文无招聘人数；按字段默认值落库，并在台账标注"默认值，非原文" |
| （无） | `department` / `location` / `description` | **留空**（不猜、不编） |
| （无） | `legacy_ref='edu.alumni.job:<id>'` | 回滚锚点 |

---

## 5. 迁移步骤（3 条岗位）与 25 份申请的兼容

### 5.1 迁移（脚本形态，实施任务执行）

1. **`--dry-run`**：打印将新建的 3 行（逐字段前后对照）+ 幂等预检（按 `legacy_ref` 判断是否已迁过）。
2. **前置断言（任一不满足即中止）**：`edu.alumni.job` = 3 行；`edu.job.posting` = 2 行；`edu.job.application` = 25 行且全部 `posting_id=1`；`legacy_ref` 命中的行数 = 0。
3. **写入**：按 §4.4 逐字段建 3 行 `posting`，`audience='alumni'`，`legacy_ref` 写明来源 id。**不修改、不移动、不 unlink 任何存量行**。
4. **台账**：逐条记 `edu.alumni.job:<id> → edu.job.posting:<id>`（含"`posted_by` 原值=校友、`openings` 为默认值"两处说明），落 `docs/audit/` 或 `scripts/` 侧（与 t6 的弃用台账呼应）。
5. **`--rollback`**：只删**台账内本次新建**、且 `legacy_ref` 非空的 3 行；若目标行**已有 `edu.job.application` 引用**则**拒绝回滚并报错**（防止把已投递的岗位抽走）。

### 5.2 25 份申请：零改动

| 事实 | 结论 |
|---|---|
| 25 行全部 `posting_id=1`（`【演示】神学课程助教`） | 迁移只新增 posting 行，不动申请 |
| `posting 1` 迁移后 `audience` 仍是 `campus`（不设 `alumni`） | `/campus/jobs` 仍显示它，`/alumni/jobs` 不会混入校园岗 |
| 投递链路 `/campus/jobs/<id>/apply` 读 `state='published'` | 不受 `audience` 影响（只在**列表查询**加过滤） |

### 5.3 幂等与计数对照（实施报告必须给）

| 计数 | 迁移前 | 迁移后（期望） |
|---|---|---|
| `edu.job.posting` | 2 | **5**（其中 `audience='alumni'` = 3、`campus` = 2） |
| `edu.job.application` | 25 | **25**（逐条 `id`/`posting_id`/`state` 完全一致） |
| `edu.alumni.job` | 3 | **3**（不动；仅停止被门户读取） |
| `/campus/jobs` 页面岗位数 | 2 | **2** |
| `/alumni/jobs` 页面岗位数 | 3 | **3** |
| 幂等复跑 | — | 新增 0 行 |

---

## 6. 门户与后台入口归属

### 6.1 门户 URL 策略

| URL | 现状 | 目标 | 实现位置 | 用户可感变化 |
|---|---|---|---|---|
| `/alumni/jobs` | 读 `edu.alumni.job` | **保留 200**，改读 `posting(audience in ('alumni','both'))`，`?state=` 过滤映射到 `state∈{published,pending,closed}` | `edu_public/controllers/main.py:205` | 仍是 3 条岗位；新增「校友」标识；状态徽标文案不变（招聘中/待定/已结束） |
| `/alumni/job/card` | 读 **posting（全部 published）** | **303 → `/alumni/jobs`** | 同上 `:198` | 「校友招聘」导航项不再显示两条校园岗位（修正错位） |
| `/alumni/job/list` | 读 `edu.alumni.job`，含英文标签 | **保留 200**，改读 `posting(audience='alumni')`，**文案中文化**，页头加「去后台维护」按钮指向 586 岗位管理 | `edu_portal/controllers/roles.py:1297` + `views/roles.xml:1040` | 教务看到同一批岗位；英文标签变中文 |
| `/campus/jobs` + `/<id>` + `/apply` | 读 posting(全 published) | **保持不变**，列表加 `audience != 'alumni'` 过滤 | `edu_public/controllers/main.py:153-196` | 无（仍 2 条） |
| `/jobs`（原生） | 原生空页（`hr.job`=0） | **保留路由**，导航层下掉 3 个入口（191/197/198） | `website_menu`（t2/后续） | 顶部导航少 3 个「工作/Jobs」死入口 |

> **重定向实现注意**：`/alumni/job/card` 是 `auth='public'`、`type='http'` 的 GET 路由，改成 `request.redirect('/alumni/jobs')` 即 303；**路由不删**（删了会 404，违反"重定向"要求）。

### 6.2 后台菜单（目标态，t2 执行）

- `585 招聘管理`（保留为独立根，`base.group_user`；t1 施工图把它归入「⑧ 招聘就业」，是否顺带改显示名为「招聘就业」由 t2 定）下：586 岗位管理（保留，`edu.job.posting`，字段/视图增补 `audience`/`reference`/`pay_period`/`deadline`）、587 申请处理（保留）、**新增「校友岗位」** = `edu.job.posting` 的筛选动作（`domain=[('audience','=','alumni')]`，`context`/搜索面板带 audience 过滤）。
- 建议在 586 的 list 视图加 `audience` 列与 `decoration`；表单加「面向」字段。
- 禁止：`unlink` 任何 `ir.ui.menu`；`edu.alumni.job` 不加后台菜单（它只是待弃用表）。

### 6.3 网站导航（目标态，非本设计实施）

| id | 现状 | 目标 |
|---|---|---|
| 189 校友招聘 `/alumni/job/card` | 名实不符 | url 改 `/alumni/jobs`（或保留并依赖 303） |
| 190 校园工作 `/campus/jobs` | 已正确 | 保留 |
| 191 / 197 / 198 → `/jobs` | 三个入口指向 0 数据原生页 | 收敛为 0 个（撤下） |
| 124 `Alumni & Careers` | 英文名 | 改中文「校友与就业」（或与 189 合并为一个入口） |

---

## 7. 失败处理与回滚

| 层 | 操作 | 失败特征 | 回滚 |
|---|---|---|---|
| 模型/视图 | `bash scripts/safe_upgrade.sh -u edu_portal,edu_public` | EXIT≠0 / Traceback / `invalid value`（Selection 新值未升级先写数据） | `git revert` + 再 `-u`；`audience`/`reference`/`pay_period`/`deadline`/`legacy_ref` 五列留在库中无害 |
| 数据 | 迁移脚本（§5.1） | 前置断言失败（计数不符）/ 幂等预检命中 | `--rollback` 删台账内 3 行；**若任一行已有申请则拒绝回滚**（人工处理） |
| 门户 | `/alumni/jobs` 数据源切换 | 页面 0 条 / 5xx / 混入校园岗位 | revert `edu_public` 控制器 + `-u`（旧表仍在，立刻恢复 3 条） |
| 后台 | 新增「校友岗位」子项 | 教务看不到 | 按 t2 的菜单 `--rollback` 还原（只还原 active/groups/parent） |
| 回归 | `tests/smoke/ux_v3_route_matrix.py`（`/alumni/jobs`、`/campus/jobs` 断言 ALL5=200）；`tests/smoke/D_public.md`（`/alumni/job/card` 断言 200） | FAIL | **注意**：D_public 目前断言 `/alumni/job/card` = 200，改成 303 后**该断言的判定口径要同步改**（303 后仍 200 算 PASS，但"标记命中"判断会变），属 t7/t9 的联动项 |

**失败即停手的红线**：任何一步出现 `unlink` 存量行、申请行被改写、`edu.alumni.job` 计数变化 ⇒ 立即停手并回报队长。

---

## 8. 对公众/学生的可见变化（逐条）

1. `/alumni/jobs`：**岗位条数不变（3 条）**；排序口径从 `start_date desc` 变为 `publish_date desc`（**排序可能变化，需在验收里逐条对照**）；「待定」岗位是否仍可见取决于拍板 1。
2. `/alumni/job/card`：不再显示两条校园岗位（原来这是"校友入口显示校园岗"的错位）。
3. `/campus/jobs`：**无变化**（2 条，投递表单/成功页不变）。
4. `/alumni/job/list`（教务）：岗位数据不变，**英文标签变中文**，多一个后台维护入口。
5. 顶部导航：`工作`/`Jobs` 三个死入口撤下（若 t2 采纳 §6.3）。
6. 学生：**无可见变化**（学生不涉及岗位维护；公开页对学生与匿名一致）。

---

## 9. 验收口径（供实施任务与 t7 独立验证）

| # | 验收项 | 判据 |
|---|---|---|
| 1 | 升级干净 | `bash scripts/safe_upgrade.sh -u edu_portal,edu_public` EXIT=0、无 Traceback |
| 2 | 迁移完整 | 3 条校友岗位逐字段对照（name/code/salary/pay_period/start/end/state/creator）与 §2.1 一致；`edu.job.posting` 计数 2 → **5** |
| 3 | 申请零损失 | `edu.job.application` = 25，且逐条 `id / posting_id / state` 与迁移前快照**完全一致** |
| 4 | 公开页不串台 | `/alumni/jobs` 恰 3 条校友岗（无校园岗）；`/campus/jobs` 恰 2 条（无校友岗） |
| 5 | 旧 URL 不 404 | `/alumni/job/card` 303 → `/alumni/jobs` → 200 |
| 6 | 后台单一入口 | 585 一个根，子树含「岗位管理 / 申请处理 / 校友岗位」；菜单记录数不减少（无 unlink） |
| 7 | 幂等 | 迁移脚本复跑：新增 0 行 |
| 8 | 回滚可用 | `--rollback` 实测后 `edu.job.posting` 回到 2 行、`/alumni/jobs` 回到 3 条（旧表未被读取的那 3 条又出现）；申请仍 25 |
| 9 | 中文门禁 | `python3 scripts/check_english.py` must-fix = 0（含 `/alumni/job/list`、导航 124） |
| 10 | 路由矩阵 | `python3 tests/smoke/ux_v3_route_matrix.py` 无 FAIL（`/alumni/jobs`、`/campus/jobs` 仍 200） |

---

## 10. 待拍板问题（3 项，业务口径类，本文不自行裁定）

**拍板 1：「待定（pending）」岗位合并后是否仍对公众可见？**
- 候选 A（**保持现状**）：`posting.state` 新增 `('pending','待定')`，`/alumni/jobs` 照旧显示 3 条（含待定），投递仍只对 `published` 开放。
- 候选 B：映射为 `draft`（不公开）⇒ `/alumni/jobs` 从 **3 条变 2 条**，属于**用户可见的内容减少**。
- 候选 C：映射为 `published` 但列表加「待定」标记位（需另一列承载原状态）。
- **影响面**：公开页条数、`/alumni/jobs?state=pending` 过滤是否还在、岗位方（校友）是否认为已下架。

**拍板 2：3 条校友岗位的 `$` 金额是否保持原样？**
- 候选 A（**本设计默认**）：**字符原样迁移**（`$ 40,000.00 - $ 60,000.00`）—— 迁移不得改写事实数据。
- 候选 B：按现行币种口径（CNY / 「面议」）重写 —— 属于**内容变更**，必须有明确指令与来源依据。
- **影响面**：公开页展示的薪资；若改错会被外部读者当成真实待遇。

**拍板 3：已过期的校友岗位（`end_date` 已过）是否自动下架？**
- 现状：3 条的 `end_date` = 2026-08-21 / 2026-08-21 / 2026-09-11，**今天（2026-09-17）已全部过期**，但 `/alumni/jobs` 仍全部展示（控制器只按 `state` 过滤，无日期过滤）。
- 候选 A：**保持现状**（迁 `deadline` 但不参与过滤）。
- 候选 B：`deadline < 今天` 自动从公开列表隐藏（或显示「已截止」灰标）。
- **影响面**：公开页条数（B 会从 3 条变 0 条）、校友岗位的可信度、是否需要给发布人发提醒。

---

## 11. 实施前置条件

1. **拍板 1 先定**（`pending` 的处置决定 `state` 枚举是否扩展，枚举定了才好写迁移）。
2. **Selection 新值必须先 `-u` 再写数据**：`audience`、`pay_period`、`state+pending` 都是新枚举，先升级建列再迁数据，否则 `invalid value`。
3. **迁移脚本形态**（对齐 t5 打卡合一的既有约定）：`--dry-run` / 幂等 / 台账 / `--rollback`，且**只允许回滚本次新建行**。
4. **不得触碰**：`openeducat_erp/`、`edu.alumni.job` 的 3 行、`edu.job.application` 的 25 行、`/campus/jobs` 投递链路。
5. **联动方**：后台菜单与网站导航（`website_menu`）属 **t2 / 后续菜单任务**，实施前先与队长确认归属；`tests/smoke/D_public.md` 对 `/alumni/job/card` 的断言改动属 **t7/t9**。
6. **文案**：新增/改动的一切用户可见文案必须中文（含把 `My Job Posts` 等英文改中文，改完跑 `python3 scripts/check_english.py`，must-fix = 0）。
7. **演示数据标记**：本次迁移的是**历史真实数据**，不得加【演示】；新造的样例必须带【演示】、冒烟带【冒烟】。

---

## 附：本次实测的原始读数（可复现）

```
# 计数（2026-09-17 11:06 CST）
edu_alumni_job 3 | edu_job_posting 2 | edu_job_application 25（全部 posting_id=1, state=new）
hr_job 0（原生招聘空）| 已装模块：hr_recruitment / website_hr_recruitment / edu_public / edu_portal / edu_eval

# 路由（curl；匿名 + 5 角色）
/alumni/jobs 200 | /alumni/jobs?state=recruiting 200 | /alumni/job/card 200
/alumni/job/list 200（登录后）| /campus/jobs 200 | /campus/jobs/1 200 | /campus/jobs/1/sent 200 | /jobs 200（原生空页）

# 页面内容（互不串台）
/alumni/jobs  命中 网络设计师×1 施工经理×1 电气设计工程师×1；神学课程助教×0
/campus/jobs  命中 神学课程助教×1 图书馆兼职管理员×1；网络设计师×0

# 菜单
ir.ui.menu：585 招聘管理(seq70) → 586 岗位管理(act724) / 587 申请处理(act725)
website_menu：124 /alumni/jobs | 189 /alumni/job/card | 190 /campus/jobs | 191·197·198 /jobs | 192 /alumni
```

> 未核项：① 3 条校友岗位的**原始来源**（抓取脚本/导入时间）未找到，仅能从 `code=JP00x` + `$` 金额 + `creator='校友'` 推测；② `/alumni/jobs` 与 `/alumni/job/card` 的**站点地图/SEO 收录**情况未核；③ `edu.alumni.job` 是否有外部调用方（爬虫/第三方页面）未核。
