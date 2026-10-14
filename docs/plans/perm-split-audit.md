# 权限分层收口 · 教务后台可达性巡检与修复（t1）
> **状态**：`归档` ｜ **主题**：`权限分层收口巡检` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 读法：§1 结论 → §6 发现的问题（要动作的都在这） → §9 怎么复跑。
> 实测口径三层（L1 菜单可见 / L2 ORM 可打开 / L3 浏览器真渲染）+ 三条端到端流程；
> **只看 HTTP 200 不算数**——「看得见点不开」正是状态码看不见的那一类，本轮把这条写进了脚本。
> 数字口径先看 **§2.1（A/B 两把尺子）与 §2.2（库+时刻+是否含 edu_nav 三要素）与 §2.3（区分度主集）**：
> 任何菜单数离开这三样都不可引用。

| 项 | 值 |
|---|---|
| 任务 | t1 教务后台可达性巡检与修复（权限分层后） |
| 账号 | `backoffice@local`（uid 12，组 `openeducat_core.group_op_back_office_admin`） |
| 环境 | 本地克隆 docker compose（`edu19` @ http://127.0.0.1:8069，web 容器 `edu19-clone-web-1`） |
| 采集时刻 | 主读数 2026-09-17 17:23:31（Asia/Shanghai）；其余读数各自带时刻，基线快照另标 |
| 代码基线 | `2f53947`（t11 文档），权限分层落地提交 `d2c41de` 已在其祖先里 |
| 交付 | `tests/smoke/backoffice_reachability.py`（可重跑门禁）+ 本文档 + `edu_portal` 的菜单收口（§6.1） |
| 提交 | `2773ffe` 交付 · `3ef6cba` 门禁收口 · `294516c` 静态层分离断言 · `589178b` t13 收口与抖动判据 · `1fb2545` 口径三要素与区分度 |

---

## 1. 结论（一句话）

**任务点名的覆盖清单（34 条菜单）在 L1/L2/L3 三层判据下全部可达**，三条端到端流程
（报名审批 / 成绩留痕 / 考勤落库）以教务身份真跑通过、夹具自建自清 `leftover=0`，
红线自查（教务不含 `base.group_system`）通过。
把巡检扩到**教务可见的全部菜单**后抓到 3 处「看得见点不开」（共 5 条原生菜单：网站/活动、
电子商务/付款方式、在线聊天/会话×3），**已当场修**：按业务把它们收回到真正需要的功能组 + 超管
（§6.1 有改动清单与升级实证），教务可见菜单 184 → 179（收窄 5 条死角）；t13 随后补回两条入口（§6.2），
现为 **181**，死角 **5 → 0**。

t1 当时登记的两条**存量缺口**（`邀请码` / `老账号补挂身份` 被收口停成了孤儿、对所有人不可见）已补回入口：
菜单 **790/791** 挂在 `学生信息 / 配置(261)` 下（新 xmlid、groups = 教务组 + 系统组，edu_nav 的停用记录原样不动）。
验收读数（§6.2.2）：**教务 ✓ / 教师 ✗ / 管理员 ✓**；`ir.ui.menu` 总数 605 → **607**；
同类孤立项巡检：26 条停用根里**「能力活着却无入口」= 0**（唯一非空 action 的 `547 在线学习` 是 0 行数据 + 收口文档「确认下线」）。
影响面不是瑕疵而是**能力**：注册流程要求邀请码，缺入口期间学校发不出新账号（§6.2.2）。

---

## 2. 口径与方法（为什么是三层，而不是一层）

| 层 | 判据 | 抓得到什么 / 抓不到什么 |
|---|---|---|
| **L0 静态层分离**（离线，先跑） | 扫 `custom_addons/*/views/*.xml`：**不得有只挂 `base.group_system` 的自家菜单**（两种写法都查：`<menuitem groups="…">` 与 `<record model="ir.ui.menu"><field name="group_ids">`）；例外必须登记在脚本里的显式清单并写明理由 | 抓「菜单挂错组 ⇒ 层分离后教务直接看不见」。**抓不到**运行时 ACL/记录规则问题（那是 L2/L3）；也**不扫基座**（Odoo 原生「设置/应用」只挂系统组是设计） |
| **L1 菜单可见** | `/web/webclient/load_menus`（前端真正渲染的那份树） | 抓「菜单该不该出现」。**抓不到**「出现了但点不开」 |
| **L2 ORM 可打开** | `/web/action/load` 解析菜单动作 → `get_views`（视图 arch/组限制）+ `search_read`（模型 ACL + 记录规则）+ `check_access_rights` 读/写/建/删 | 抓 AccessError / 视图取不到 / 模型不可读。**抓不到**客户端渲染期的失败、也抓不到「动作打开但页面空白」 |
| **L3 浏览器真渲染** | Playwright 打开 `/odoo/action-<id>?menu_id=<id>`，断言控制面板 + 面包屑 + 视图容器（list/kanban/form/graph/...）+ **关键元素**（列表视图字段标签，取自该菜单自己的视图 arch，不写死文案）+ 无错误弹窗/AccessError | 抓「真点不开」。**代价**：慢（覆盖清单 ~3 分钟），且会被本机环境抖动干扰（见下） |
| **E2E 三条流程** | 教务身份真写：报名审批（公开表建单 → 审核中 → 已录取 + 材料核对）、成绩录入（改分 → `edu.grade.history` 留痕）、考勤录入（点名册 → 点名表 → 出勤明细落库）；每条都做 DB 反查 | 抓「页面能开但写不进」 |

**关键元素怎么定（避免「看 200 就算过」）**：列表视图渲染后，表头必须命中该菜单自己的
视图 arch 里的字段标签（视图没写 `string=` 时用 `fields_get` 的当前语言标签）。
例：`教务审批 / 请假审批` 的判据是表头出现「申请编号 / 学生 / 休假类型 / 开始日期」之一，
而不是「页面返回 200」。

**环境抖动怎么处理**：本地 Odoo dev 服务偶发丢连接（`ERR_EMPTY_RESPONSE` / `ConnectionLostError`），
客户端会回落到 `/apps` 应用面板——第一轮全量扫（2026-09-17 15:01–15:11）就是这么被误报出
「活动 / 付款方式 / 会话 点不开」的（同一轮里 admin 打开**已知可用**的菜单也复现）。
所以 L3 一律重试（默认 3 次），并把重试次数写进读数；判定「真失败」的条件是**重试后仍复现**。

---

### 2.1 「教务可见菜单」的口径（**数字必须自带口径**，否则不可复现）

同一天里同一个库，这个数字可以差一倍——不是谁错，是**口径没锁**。所以本脚本每次运行都打印
**两把尺子**，各自带 API、条数、根数、库名、采集时刻（可直接引用；报告只许引脚本输出，不许手抄）：

| 口径 | API / 命令 | 量的是什么 | 典型用途 |
|---|---|---|---|
| **A（ORM）** | `ir.ui.menu.with_user(backoffice@local)._visible_menu_ids()`（本脚本内走只读 `docker compose exec web odoo shell`；RPC 不能调私有方法） | 按「组 + 动作可解析 + 祖先是可见的」算出的菜单 id 集合；**会包含**「父级不可见 ⇒ 客户端永远点不到」的孤儿 | 与 verifier 的独立读数对账（同 API）；回答「权限上应该看得见多少条」 |
| **B（前端）** | `GET /web/webclient/load_menus` 渲染树 | 客户端**真正渲染**的那份树：已剔除黑名单菜单与无可见父的孤儿（Odoo `base/models/ir_ui_menu.py:257-259`） | **L1 判据用它**；回答「用户实际能点到多少条」 |

两者关系（本脚本每次打印）：`A − B = 黑名单 + 孤儿`（实测 2026-09-17 17:23:31：A=195 条 / 12 根，
B=180 节点 / 12 应用，差 15 条）。**根数两边必须分开报**：A 报 `parent_id=False 且在可见集内`，
B 报 payload 的 `appID` 分组数（= 应用面板上的瓦片数），两者都应是 12。

**可引用句（把 <时刻> 换成脚本打印的时刻，写完不许再手改）**：

> 教务可见菜单（口径 A：`ir.ui.menu.with_user(backoffice@local)._visible_menu_ids()`，条数/根数，
> edu19 本地克隆，<采集时刻>，已应用 edu_nav 收口）= **195 / 12**；口径 B（前端 `load_menus` 渲染树，节点/应用）= **180 / 12**。

> 口径补充（Odoo 语义，2026-09-17 verifier 复述、t1 复核）：`_visible_menu_ids(debug=False)` 会**丢弃
> `base.group_no_one`**（即使该用户实际持有该组）⇒ 教务看不到仅 `group_no_one` 的菜单。不是缺陷，是语义。

**对不上的历史数字（留档，别再引用）**：队长先前记的「可见菜单 404→391」是
**ORM 口径 / 别的时刻 / 别的库**（收口轮 vs 分层前后），与这里的 195/180 不是同一把尺子；
引用时必须连口径与时刻一起引。verifier 独立读到的 199 / 12 是**同一把尺子（口径 A）的另一时刻**——
那之后本轮收窄了 5 条死角菜单、t13 又补回 2 条入口，所以现在 A=195；两数之差可用本脚本
`--dump` 的 `menu_scope` 块逐条对账（快照里带 `A`/`B` 两个读数与时刻）。

### 2.2 基线三要素：**库 + 采集时刻 + 是否含 edu_nav 菜单收口**

同一个口径在不同库/不同时刻也不是同一个数：本地库**已应用 edu_nav 菜单收口**（收口把大量原生根停用/收窄），
生产库**没有 edu_nav**（同口径读数会大一个量级，队长记录生产同口径约 391）——**两边的数字不可互替**。
所以本脚本每次运行都按三要素打印，并把它写进 `--dump` 快照（`menu_scope.A_orm / B_frontend / discrimination`）：

| 要素 | 打印形式 | 例（2026-09-17 17:21:37，本地） |
|---|---|---|
| 库 | `edu19（本地克隆）` / 生产 | edu19（本地克隆） |
| 采集时刻 | `YYYY-MM-DD HH:MM:SS`（本地时区） | 2026-09-17 17:21:37 |
| 是否含 edu_nav 收口 | `已应用 edu_nav 菜单收口（consolidated_count=357）` / `未应用…` | 已应用（357） |

⚠ **并行会话预警**：本工作区今天 11:59–15:17 另有会话在做菜单收口（`git log --since`），
读数若在变先看提交、别当成自己的改动；**本文件里所有数字都必须带采集时刻**，跨时刻引用请重跑（§9）。

### 2.3 区分度基线：**教务可见 ∧ 教师不可见 ∧ active=True**（别用全局停用菜单当证据）

「教师看不见 ⇒ 说明分层生效」这个推理**只有在菜单本身是活的时候才成立**：本地库有 **200 条**
`active=False` 的菜单（菜单收口停用的），它们对**任何人**都不可见 —— 拿它们证明教师被挡住是白过。
本脚本因此打印主集与两个必须为 0 的旁证：

- **主集**：教务可见 ∧ 教师不可见 ∧ `active=True`（口径 B = **116 条**；口径 A 同集 = **120 条**，2026-09-17 17:23:31 本地读数）；
- **零混入断言**：主集里 `active=False` 的条数必须 = **0**（实测 0）——这条断言把「白过」结构性地挡在门外；
- **教师侧对照**：教师可见 75 节点 / 应用根 9（同一时刻），教务 180 / 12。

引用时同样要带三要素，例：

> 区分度主集（口径 A：`ir.ui.menu.with_user(<角色>)._visible_menu_ids()` 差集 ∩ active，条数，edu19 本地克隆，
> 2026-09-17 17:21:37，已应用 edu_nav 收口）= 120 条；主集内 `active=False` 混入 = 0 条。

## 3. 覆盖清单读数（任务点名的 15 个业务域，逐菜单）

- 判据列 L2 = 动作解析 + 目标模型 + 【读✓写✓建✓删✗】权限读数 + 关键元素候选；
- 判据列 L3 = 真浏览器落地结果（视图容器 / 行数 / 向导弹窗 / act_url 落地页）；
- `act_url` 类菜单（财务总台账 / 报销审批 / 资料下载管理 / 周期排课）L2 判 HTTP 可达、L3 判**落地页有正文**。

| 域 | 菜单（L1 口径 B 路径） | L2 判据（动作 + 模型 + 权限读数） | L3 判据（浏览器真渲染） |
|---|---|---|---|
| 报名审批 | 招生 / 入学申请 | edu.application（读✓写✓建✗删✗） | 列表渲染，6 行，表头命中「姓名 / 报考科别 / 性别」 |
| 课程 | 学生信息 / 配置 / 课程管理 / 课程 | op.course（读✓写✓建✓删✓） | 列表渲染，7 行 |
| 科目 | 学生信息 / 配置 / 学科管理 / 科目 | op.subject（读✓写✓建✓删✓） | 列表渲染，80 行 |
| 批次 | 学生信息 / 配置 / 课程管理 / 批次 | op.batch（读✓写✓建✓删✓） | 列表渲染，17 行 |
| 课节（课次） | 时间表 / 课次管理 | edu.lesson（读✓写✓建✓删✗） | 列表渲染，8 行 |
| 时间表 | 时间表 / 时间表 / 会议 | op.session（读✓写✓建✓删✓） | 列表渲染，80 行 |
| 时间表（向导） | 时间表 / 时间表 / 生成时间表 | generate.time.table（读✓写✓建✓删✓） | 打开「生成会话」向导弹窗（**动作本身就是向导，不是故障**） |
| 周期排课 | 时间表 / 周期排课（批量） | act_url `/timetable/bulk` HTTP 200 | 落地门户页，正文 600 字 |
| 考试 | 时间表 / 考试 / 考试 | op.exam（读✓写✓建✓删✓） | 列表渲染，1 行 |
| 考试参加者 | 时间表 / 考试 / 考试参加者 | op.exam.attendees（读✓写✓建✓删✓） | 列表渲染，1 行 |
| 考试课程 | 时间表 / 考试 / 考试课程 | op.exam.session（读✓写✓建✓删✓） | 列表渲染，1 行 |
| 成绩（结果行） | 时间表 / 考试 / 结果行 | op.result.line（读✓写✓建✓删✓） | 列表渲染，1 行 |
| 结果分析 | 时间表 / 报告 / 结果分析 | op.result.line（读✓写✓建✓删✓） | 图形视图渲染 |
| 课堂考勤 · 点名册 | 时间表 / 考勤 / 点名册 | op.attendance.register（读✓写✓建✓删✓） | 列表渲染，1 行 |
| 课堂考勤 · 点名表 | 时间表 / 考勤 / 点名表 | op.attendance.sheet（读✓写✓建✓删✓） | 列表渲染，1 行 |
| 课堂考勤 · 出勤明细 | 时间表 / 考勤 / 出勤明细 | op.attendance.line（读✓写✓建✓删✓） | 列表渲染，47 行 |
| 图书馆 | 图书馆 / 所有媒体 / 媒体 | op.media（读✓写✓建✓删✓） | 列表渲染（0 行 = 库里确实没有媒体，页头关键元素在位） |
| 图书馆 · 图书卡 | 图书馆 / 配置 / 图书卡 | op.library.card（读✓写✓建✓删✓） | 列表渲染，0 行 |
| 财务总台账 | 财务管理 / 财务总台账 | act_url `/ledger` HTTP 200 | 落地门户页，正文 600 字 |
| 费用分类 | 财务管理 / 费用分类 | edu.fee.category（读✓写✓建✓删✓） | 列表渲染，15 行 |
| 账单管理 | 财务管理 / 账单管理 | edu.fee.bill（读✓写✓建✓删✓） | 列表渲染，2 行 |
| 缴费流水 | 财务管理 / 缴费流水 | edu.fee.payment（读✓写✓建✓删✓） | 列表渲染，1 行 |
| 报销审批 | 教务审批 / 报销审批 | act_url `/ledger/reimburse` HTTP 200 | 落地门户页，正文 410 字 |
| 公告（布告栏） | 教务审批 / 布告栏管理 | edu.notice（读✓写✓建✓删✓） | 列表渲染，8 行 |
| 公告模板 | 教务审批 / 公告模板 | edu.notice.template（读✓写✓建✓删✓） | 列表渲染，0 行 |
| 请假审批 | 教务审批 / 请假审批 | edu.leave（读✓写✓建✓删✓） | 列表渲染，13 行，表头命中「申请编号 / 学生 / 休假类型」 |
| 申诉处理 | 教务审批 / 申诉处理 | edu.grievance（读✓写✓建✓删✓） | 列表渲染，23 行 |
| 证书管理 | 教务审批 / 证书管理 | edu.certificate（读✓写✓建✓删✓） | 列表渲染，1 行 |
| 选课审批 | 教务审批 / 选课审批 | op.subject.registration（读✓写✓建✓删✓） | 列表渲染，0 行 |
| 福利打卡（全员） | 灵命生活 / 全员打卡 | edu.daily.checkin（读✓写✓建✓删✓） | 列表渲染，7 行 |
| 打卡记录 | 灵命生活 / 打卡记录 | edu.checkin.record（读✓写✓建✓删✓） | 列表渲染，53 行 |
| 积分流水 | 灵命生活 / 积分流水 | edu.point.log（读✓写✓建✓删✓） | 列表渲染，2 行 |
| 校历 | 时间表 / 校历活动 | edu.event（读✓写✓建✓删✓） | 列表渲染，0 行 |
| 资料下载管理 | 资料下载 | act_url `/downloads` HTTP 200 | 落地门户页，正文 600 字（含「批量上传 / 管理模式」） |
| 评教 · 模板管理 | 综合评估 / 模板管理 | edu.eval.template（读✓写✓建✓删✗） | 列表渲染，3 行 |
| 评教 · 打分记录 | 综合评估 / 打分记录 | edu.admin.eval.score（读✓写✓建✓删✗） | 列表渲染，0 行 |
| 评教 · 评估任务 | 综合评估 / 评估任务 | edu.eval.task（读✓写✓建✓删✗） | 列表渲染，1 行 |
| 邀请码 | 学生信息 / 配置 / 邀请码 | edu.invite.code（读✓写✓建✓删✓） | 列表渲染，5 行，表头命中「邀请码 / 注册身份 / 对应学生」 |
| 老账号补挂身份 | 学生信息 / 配置 / 老账号补挂身份 | act_url `/edu/backend/relink_identity` HTTP 200 | 落地门户页，正文 600 字 |

> 读数全量见脚本输出（终态 `PASS 91 / FAIL 0 / GAP 0`；含静态层分离、5 条收口回归、3 条红线、3 条端到端）。
> `邀请码` / `老账号补挂身份` 两条**已由 t13 补回入口**（菜单 790/791），从「已知缺口」升格为标准覆盖项（见 §6.2）。
> `邀请码`、`老账号补挂身份` 两条按「已知缺口」记 GAP，默认不判红；`--strict-gaps` 可把它们一起判红。

### 3.1 「看得见但写不进」也查了

- `edu.application` 对教务是 读✓写✓**建✗删✗** —— 这是**设计**：报名单由公开报名表创建
  （`edu_apply/controllers/main.py:89` 用 sudo 建），教务负责审，不负责建/删；
- `edu.eval.*` / `edu.lesson` 删✗ —— 评估与课次不允许删除，防误删；
- 其余清单内业务模型教务都是 读✓写✓建✓删✓。
- **没有任何一条**是「菜单可见、模型只读、却指望教务写」的组合（这正是「看得见点不开/点了存不了」的典型形态）。

---

### 3.2 静态层分离断言（L0）：0 处「只挂系统组」的自家菜单

> 为什么单独有这一节：本轮分层前，自家菜单里有 **7 处**写成 `groups="base.group_system"` 的孤组
> （`invite_code_views.xml`×2、`notice_admin.xml`×3、`welfare.xml`×2）——拆开教务组后，
> 教务对这些菜单是**直接看不见**（不是"点不开"）。修好之后，这条不变式**没有任何东西守着**，
> 将来加菜单很容易再犯。本节就是把它从「一次性改动」变成「长期守着的东西」。

**判据（脚本 `静态·层分离`，离线先跑，服务不通也能给结论）**

- 命中定义：某菜单声明的组集合**恰好等于** `{base.group_system}`；
- 覆盖两种写法：`<menuitem groups="…"/>` 与
  `<record model="ir.ui.menu"><field name="group_ids|groups_id" eval="[(6,0,[ref('…')])]"/></record>`；
- 输出：`file:line` + 菜单 id + 原组串 + 改法（"应写成 `教务组,base.group_system` 并列，或登记例外"）；
- 命中即 **FAIL**（退出码 1），不设"警告级"。

**扫描边界（声明并计数，每次运行都打印）**

`custom_addons/*/views/*.xml` —— 本轮实测 **56 个文件 / 52 个 `<menuitem>` / 9 个 `ir.ui.menu <record>`**。
按设计排除两类（写在脚本注释里，避免下一个人以为是漏扫）：

1. 基座 `openeducat_erp/`：Odoo 原生「设置 / 应用」这类只挂系统组的菜单是**合法的**，报它就是误报；
2. `custom_addons/*/data/*.xml`：`edu_nav` 的收口数据有意用 `group_ids=[4]` 做「档2：仅超管可见」，
   那是**声明式策略**而不是漏挂教务组（要改口径去那边改）。

**例外纪律（不放宽断言，改成可见可审计的清单）**

脚本里的 `STATIC_GROUP_EXCEPTIONS`（当前为**空**）——确实只该给开发者的自家菜单必须逐条登记
「(相对路径, 菜单 id) → 理由」；每次运行都会连同**例外条数**一起打印；**已失效的例外**（菜单已改并列写法
或被删）会被点名并给出行号，逼着人删掉过期条目。

**尺子自证（`--selftest`，离线 7 条断言）**

```bash
python3 tests/smoke/backoffice_reachability.py --selftest   # exit 0；7/7
```

合成夹具里放 4 种声明：孤组 menuitem（应命中）、孤组 record（应命中）、并列写法（不应命中）、
纯 `base.group_user`（不应命中），外加"显式例外生效"与"失效例外被点名"两条路径。
**这条自证不是形式主义**：写好第一版时它当场抓出两个真 bug——
① `REPO_ROOT` 上溯少一层导致**扫描面 0 文件却报 PASS**（假绿；现已加"扫描面为空即 FAIL"的守卫）；
② record 写法的取值用 `[^"']*` 会在 eval 值里的第一个单引号处截断，导致孤组 record **漏报**
（现已改用同种引号反引用 `(?P=q)`）。

**反例演示（这条断言会红，不是橡皮图章）**：把任一处菜单改回 `groups="base.group_system"`
（或加一条孤组 record），再跑 `python3 tests/smoke/backoffice_reachability.py --no-browser --skip-flows`
即得 `FAIL | 静态·层分离 | <file>:<line> → 菜单 <id> 只挂系统组 …`，退出码 1。

## 4. 三条端到端流程（教务身份真跑 + DB 反查）

| # | 流程 | 动作 | 读数（原始证据） |
|---|---|---|---|
| ① | 报名审批 | 匿名 POST `/apply/submit` 建【冒烟】申请 → 教务 `web_save`（= 后台表单保存的同一个方法）改状态与材料 | `app#17 新申请 → 审核中 → 已录取`；DB 反查 `state=admitted` 且 `mat_form/recommend/testimony/calling/diploma/physical/idcard` **7/7 = t** |
| ② | 成绩录入 | 教务建【冒烟】考试 + 考生行 → `web_save` 改分 0→73、73→81 | `exam#135 att#120`；`edu_grade_history` 2 条：`(0,73,'create','backend',12)`、`(73,81,'update','backend',12)`（含操作人 uid=12）；考生行 `marks=81` |
| ③ | 考勤录入 | 教务建【冒烟】点名册 → 点名表 → 出勤明细 → 置 `done` | `register#8 sheet#168(done, 2026-09-17) line#146 present=t`（写入的是教师页同一批模型） |
| — | 清场 | 按 id + 【冒烟】标记双口径删 | 删 `op_attendance_line/sheet/register、op_exam_attendees、op_exam、edu_application` 各 1 条；**leftover=0**（四张表全表按标记核查） |

**教师页对照（信息项，不判红）**：教务访问门户 `/attendance/take` → `200 /my/home`。
这是设计（`edu_portal/controllers/roles.py:174 current_faculty()` 要求 `op.faculty` 绑定；
code-map 铁律 3 明确「需要教师班级数据的页面仍要求教师绑定」）。
**教务的考勤/成绩入口就是后台**（时间表→考勤→点名册/点名表/出勤明细；时间表→考试→考试参加者/结果行），
这条分工写进了脚本注释，免得下一个人再把它当 bug 报一遍。

---

## 5. 全量巡：教务可见的**全部**带动作菜单

命令：`python3 tests/smoke/backoffice_reachability.py --all-menus --skip-flows`
（判据与覆盖清单同一套：动作解析 + 渲染容器 + 关键元素 + 无错误弹窗；`act_url` 判落地页有正文；
客户端动作判落地有正文；环境抖动自动重试，**全量模式重试 4 次**）

| 读数 | 值 |
|---|---|
| 教务可见菜单节点 | **181**（**该次 `--all-menus` 运行自己的输出**；本轮收窄前 184 → 收窄 5 条死角后 179 → t13 补回 2 条入口后 181。§2.1 在 2026-09-17 17:23:31 读到 **180** —— 期间另有会话改了菜单（见 §2.2 预警），跨时刻引用请重跑） |
| 其中带动作、被实际扫描 | **149** |
| PASS | **197**（含覆盖清单 49 条 + 全量 149 条） |
| FAIL | **0** |
| GAP（已知缺口） | **0**（旧的邀请码 / 老账号补挂身份已由 t13 补回并升格为覆盖项，§6.2） |
| 退出码 | **0** |

**关于「环境抖动」这一类红（本轮真踩到过，留档以免误判）**：第一次刷新全量扫描时，
`网站 / 网站 / 此网页 / HTML / CSS 编辑器`（`website_preview` 客户端动作）弹了「哎呀！出了点问题」
错误弹窗 —— 但把同一菜单**单跑 3 次 × 同家族 6 条菜单（18 次加载）全部正常**（都落到 `/` 站点预览，
无弹窗），复跑整轮全量也 0 FAIL。判为**高负载下的 Owl 生命周期偶发**（不是权限问题：A/B 里
admin 与教务表现一致），已把 `OwlError / owl lifecycle` 加入抖动标记、全量模式重试 4 次。
**这类"先复现 3–4 次再算红"的纪律**写在脚本注释里：环境抖动与真失败长得一样，
唯一能分开的办法就是重试 + 换身份重放（§6.1 用的就是这招）。

**修复前的同一扫描**判红 19 条，其中：

- **14 条是判据自己的假阳性**：客户端动作（讨论 / 通知 / 语音和视频 / 网站编辑器 `website_preview` /
  分析 / 登记处）与 `act_url`（周期排课 / 资料下载 / 财务总台账 / 报销审批）本来就没有控制面板与列表视图；
  根因是「动作类型没传进判据」——已在脚本里修好（`row["action"]` 透传 + 按动作类型分流判据）；
- **5 条是真失败**（网站 / 活动、电子商务 / 付款方式、在线聊天 / 会话 ×3）：**不靠扫描器启发式下结论**，
  而是用浏览器 A/B + 抓包重放坐实（§6.1），修复后归零。

**分类说明（怎么读这张表）**：

| 动作类型 | 判据 | 例子 |
|---|---|---|
| `ir.actions.act_window` | 控制面板 + 视图容器 + 列表视图表头命中该视图字段标签 | 全部业务菜单 |
| `ir.actions.act_window`（向导） | 打开向导弹窗即算落地（**不是故障**） | 时间表 / 生成时间表、报告 / 生成时间表报告 |
| `ir.actions.act_url` | 落地门户/后台页面且有正文（不是只判 3xx） | 财务总台账、报销审批、资料下载、周期排课、老账号补挂身份 |
| `ir.actions.client` | 落地有正文、无报错（这类动作本来就没有列表视图） | 讨论、通知、网站编辑器、登记处、分析 |

> 注：`网站` 根下仍带着 Odoo 原生树（讨论/日历/活动/博客/论坛/在线聊天/电子商务…）——那是上一轮
> 菜单收口「网站 = 网站与沟通唯一后台根」的既有口径，**不是本轮的死角**（能开的都开得开，
> 开不了的 5 条已按业务收口，见 §6.1 与 §6.3）。

## 6. 发现的问题

### 6.1 权限分层引起的「点不开」：3 处 5 条菜单 —— **已当场修**

先说清单侧：任务点名的 34 条覆盖菜单**全绿**（§3）。
但把巡检扩到教务可见的全部菜单（`--all-menus`）后，抓到 3 处「看得见点不开」——
全在 `网站` 应用树下，全是「分层后教务失去 `group_system`」造成的：

| # | 菜单（教务可见） | 症状 | 根因（客户端最后一次 RPC 的原文报错） | 处置 |
|---|---|---|---|---|
| F3 | 网站 / 活动（menu 373） | 点进去落到 `/apps` 应用面板（**不是 404、不是报错弹窗**——最难发现的那种） | `event.event/web_read_group` → `AccessError: 不允许访问"活动阶段"（event.stage）记录`（看板按 stage 分组） | 菜单收回 `event.group_event_manager` / `group_event_registration_desk` + 超管 |
| F4 | 网站 / 配置 / 电子商务 / 付款方式（menu 488） | 同上，落到 `/apps` | `payment.method/web_search_read` → `AccessError: 不允许访问"支付提供商"（payment.provider）记录` | 菜单收回 超管（该模型 ACL 只给「角色/管理员」） |
| F5 | 网站 / 技术 / 进行中的通话会话 · 由客服处理 · 由机器人处理（menu 524/525/526） | 同上，落到 `/apps` | `discuss.channel/web_search_read` → `AccessError: 不允许访问"保留频道成员历史记录"（im_livechat.channel.member.history）记录` | 菜单收回 `im_livechat.im_livechat_group_user` / `group_manager` + 超管 |

**证据链（可复现）**：

1. **浏览器 A/B**：`/odoo/action-500?menu_id=373` → admin 落在 `/odoo/events`（kanban 渲染），
   教务落在 `/apps`（连测 2 次复现）；488 / 524 同样 A/B 成立；
2. **抓包 + 重放**：拿到客户端最后一次 `call_kw` 的**完整请求体**（含 `unfold_read_specification`），
   用两种身份重放同一条请求：教务 → `AccessError`，admin → 200（活动 4 个分组）。
   这一步同时把「环境抖动」排除了：**同一条请求、同一时刻、只换身份，结果不同**；
3. **修完复扫**：教务侧这 5 条菜单不再出现（死角关闭），超管仍可见（管理面没丢）——
   这条断言已写进巡检脚本的 `收口回归` 段，谁把它改回去都会红。

**为什么是「收回菜单」而不是「给教务补组」**：这三个面分别是 电子商务付款配置 / 在线聊天客服台 /
网站事件应用，都不是「教务 = 学院领导」的业务；教务自己的活动入口是自研
`时间表 / 校历活动`（`edu.event`，§3 已验证可达）。把教务塞进这些功能组才是真正的「放宽」，
所以按业务把菜单收回到它们真正需要的组 + 超管。

**改动清单（文件:行号）**：

| 文件 | 内容 |
|---|---|
| `custom_addons/edu_portal/models/menu_reachability.py`（新增） | `NARROW_RULES`（5 条规则 + 逐条理由）+ `ir.ui.menu.edu_apply_reachability_groups()`：幂等；缺模块/缺组一律跳过并记日志，**绝不让升级失败** |
| `custom_addons/edu_portal/data/menu_reachability.xml`（新增） | `<function model="ir.ui.menu" name="edu_apply_reachability_groups"/>` |
| `custom_addons/edu_portal/__manifest__.py`（33-36 行） | 注册数据文件（放在 `views/group_tuning.xml` 之后） |
| `custom_addons/edu_portal/models/__init__.py`（41-43 行） | 导入新模型文件（只 `_inherit 'ir.ui.menu'`，无仓内导入顺序依赖） |

**为什么不用声明式 `<record ... forcecreate="0">`**（edu_nav 的写法）：记录键是**别的模块**的 xmlid，
Odoo 装载器在「记录缺失 且 `forcecreate=0`」时会抛 `Cannot update missing record`
**直接打断升级**（源码实测：`odoo/tools/convert.py:386-390`）；换成 `<function>` 后，
某部署没装 `website_sale` / `spreadsheet_dashboard_im_livechat` 时只是跳过并记日志。

**升级与落库实证**：`bash scripts/safe_upgrade.sh edu_portal` → `UPGRADE_EXIT=0`（无失败特征），
升级日志内一行：
`[edu_portal] 后台可达性收口：改写 5 条菜单组 [...]；已是目标值 0 条；跳过 无`；
DB 反查 `ir_ui_menu_group_rel`：373 → `{event.group_event_manager, event.group_event_registration_desk, base.group_system}`，
488 → `{base.group_system}`，524/525/526 → `{im_livechat.im_livechat_group_user, group_manager, base.group_system}`。

### 6.1.1 覆盖清单侧的典型裂缝（逐条查过，0 例）

1. **菜单组 vs 动作模型**：菜单可见但目标模型无 ACL —— 逐菜单 `search_read` 实测，0 例；
2. **记录规则（ir.rule）**：摸底全部「只挂 `base.group_system`」的规则（16 条，全是 Odoo 核
   `discuss.channel / ir.ui.view / res.users.settings` 等管理面），以及挂教务组的 5 条规则
   （`edu.fee.bill / op.faculty / op.session / op.student / op.subject.registration`）——
   教务在 `op.student`（4/4）、`op.faculty`（3/3）、`op.session`（288/288）上的可见行数与 admin 一致；
   教务组里那条 `Student Login rule [(user_id,'=',user.id)]` 因为教务同时持有「教师」组
   `View Students [(1,'=',1)]`，规则按组 OR 合并 ⇒ **不会**把教务锁成只看自己；
3. **视图组限制**：逐菜单 `get_views` 都能取到视图（含列表/表单/看板/图形），0 例「视图取不到」。

### 6.2 存量缺口 F1/F2：**已由 t13 补回入口**（本条保留历史与证据链）

这两条不是权限分层引入的，而是上一轮菜单收口留下的「孤儿入口」；t1 发现并登记，
**t13（signup-eng）已按登记的两条修法之一补回**，t1 随后把它们从「已知缺口」升格进覆盖清单
（现在被门禁守着，谁再藏起来立刻红）。

| # | 当时的状态（t1 实测） | 根因 | 现在（t13 修复后，t1 复测） |
|---|---|---|---|
| F1 | `邀请码` 对**所有人**（含 admin）不可见 | 收口数据只写了 `active=False`、没写 `parent_id`：`custom_addons/edu_nav/data/menu_consolidation_data.xml:2707`（注释自认「子树迁往」），而该根**0 个后代** ⇒ 没有东西被迁走；旧记录 id=542 至今仍是 `parent_id=NULL, active=f` | 新增菜单 **790** `邀请码`（`edu_portal.menu_edu_invite_code_entry`）挂在 `学生信息 / 配置` 下，`groups = 教务组 + 系统组`；t1 复测：**教务可见**，L2 `edu.invite.code` 读✓写✓建✓删✓，L3 列表渲染命中「邀请码 / 注册身份 / 对应学生 / 对应家长」 |
| F2 | `老账号补挂身份`（`act_url /edu/backend/relink_identity`）同理不可见 | 同一批数据（`menu_consolidation_data.xml:3023`），文档承诺「并入 学生信息(257) → 在其下继续可用」而实际没迁 | 新增菜单 **791**（`edu_portal.menu_edu_relink_identity_entry`）同处 `学生信息 / 配置`；t1 复测：**教务可见**，`act_url` HTTP 200 且落地页有正文 |

> 归位说明：t1 的覆盖清单里这两条**没有**标 GAP 了 —— 它们是标准覆盖项（可复跑命令里
> `--strict-gaps` 现在无事可判红，`GAPS = []`）。历史证据（旧 id 542/606 的读数、影响面、
> 两条候选修法）保留在上表，便于与收口轮的台账对账。

### 6.2.1 注释更正（t1 增量 3）：group_tuning.xml 的「已知故意不给」清单与实现不符

- **文件**：`custom_addons/edu_portal/views/group_tuning.xml:28-32`（旧注释）→ 已改成事实描述。
- **不符之处**：旧注释写「已知故意不给：招生/网站设计器/招聘/员工/销售/发票/在线聊天/数据清除」，
  但实测教务**看得见**网站整棵子树（网站/博客/论坛/电子商务/会话…）与「招聘管理」根 ——
  机制是 `scripts/seed_teacher_menus.py`（§3.5）把 `edu_portal.group_backend_full`（后台·完整视图）
  授予了 `backoffice@local`（实测：教务有效组含该组），**不是** group_tuning.xml 的决定。
- **只有两条属于「故意只给超管」**：设置(menu 1) / 应用(menu 15)（`base.group_system`）；
  联系人(121)/发票(142)/员工(196)/HR招聘(388)/数据清除(566) 是**整棵 active=False**（菜单收口），
  对**任何人**都不可见 —— 引用时不能当「教务被挡」的证据。
- **行为零改动**：只改注释，`implied_ids` 一字未动（升级实测见 §10）。要收紧教务的后台面，
  入口在 seed 脚本的组/名单（`group_backend_full`），不在本文件。

### 6.2.2 入口回补的验收读数（队长裁定 (a)：把入口补回来）

**这不是小瑕疵，是能力缺失**：注册流程仍然**要求邀请码**（`custom_addons/edu_portal/controllers/register.py:50`
在 `edu.invite.code` 上校验），而入口被菜单收口停掉后**全系统没有任何地方能发码** ⇒
学校只能靠 SQL / 找开发者发码，**新学生 / 新家长 / 新教师这条注册链是断的**；
`老账号补挂身份`（`act_url /edu/backend/relink_identity`）同理：历史账号无法自助补挂到学生/教师/家长档案。
（这两条曾被收口挂掉的根：`edu_nav/data/menu_consolidation_data.xml:2707`（542 邀请码）、`:3023`（606 补挂身份）
只写了 `active=False`、没写 `parent_id`，而 `docs/audit/menu-consolidation/diff-report.md:43/67` 却声称
「并入 学生信息(257) → 在其下继续可用」—— 本轮就是把那条承诺**兑现**。）

**落地方式（与收口口径一致，不回根菜单）**：在**已有根** `学生信息(257) → 配置(261)` 下新建两条子菜单，
**新 xmlid**，**不动** edu_nav 的 `active=False` 记录（542 / 606 原样留着，由 edu_nav 侧后续清理）：

| 入口 | menu id | xmlid | 动作 | groups |
|---|---|---|---|---|
| 邀请码 | **790** | `edu_portal.menu_edu_invite_code_entry` | `ir.actions.act_window,687`（`edu.invite.code`） | 教务组 + 系统组 |
| 老账号补挂身份 | **791** | `edu_portal.menu_edu_relink_identity_entry` | `ir.actions.act_url,745`（`/edu/backend/relink_identity`） | 教务组 + 系统组 |

（实现文件：`custom_addons/edu_portal/views/invite_code_views.xml`，由 t13 按同一口径落地；
t1 本轮**没有重复加菜单**——重复加会在后台出现两条同名入口，只做验收与同类项巡检。）

**判据读数（口径 A：`ir.ui.menu.with_user(<角色>)._visible_menu_ids()`，edu19 本地克隆，2026-09-17 17:30:37）**：

| 入口 | 教务 | 教师 | 管理员 |
|---|---|---|---|
| 邀请码（790） | **✓** | **✗** | ✓ |
| 老账号补挂身份（791） | **✓** | **✗** | ✓ |

**ir.ui.menu 总数变化**：收口基线 **605** → 回补两条子菜单后 **607**（停用 200 条不变；
两条孤立根 542/606 保留为停用状态，未删、未改）。

**同类孤立项巡检（判据 = 「该能力是否还有活入口」，不是「这条记录是否 active」）**：

- `parent NULL + active=False` 的根共 **26 条**；
- 其中 **3 条**另有活菜单指向同一 action ⇒ 能力有入口：`83 讨论`、**`542 邀请码`（= 790）**、**`606 老账号补挂身份`（= 791）**；
- **23 条**属「能力已退役」或纯容器（action 为空）：逐一打印。唯一需要说明的非空 action 是
  **`547 在线学习`**（`website_slides`）：收口轮**确认下线**（`diff-report.md:66`「档1 整棵停用；记录保留、可一键回滚」），
  且 `slide.channel` / `slide.slide` 均 **0 行** ⇒ 没有「该有入口」的内容，**不算入口缺失**；
- **能力活着却没有入口 = 0 条**（本轮修复后）。

#### 6.2.2.1 verifier 指出的陷阱（已核）+ 判据强化（t1 本轮）

**机制（verifier 说得对的那一半）**：`ir.actions.act_url` **不在** Odoo `_visible_menu_ids` 的
`MODEL_BY_TYPE` 里 ⇒ 没有第二道「目标模型读权限」闸，菜单可见性**只由 groups 决定**。
所以「菜单组」与「路由守卫」必须同口径，否则会出现**教务看得见、点进去 303 回 /my/home**；
而只判 HTTP 状态码抓不到（跟随跳转后仍是 200）——这正是我这版判据原先的漏洞。

**实况（本次实测，edu19 本地克隆，2026-09-17 17:37，逐条可复现）**：

| 项 | 实测 | 证据 |
|---|---|---|
| 菜单 790/791 的 groups | `{openeducat_core.group_op_back_office_admin, base.group_system}`（**不含** `base.group_user`） | DB `ir_ui_menu_group_rel` 反查 |
| 路由守卫 | `contacts.py` 的 `EduIdentityRelink._allowed() = is_backoffice()`；`main.py:126-129` `is_backoffice() = system 组 **或** 教务组` | 源码 + 实测 |
| `GET /edu/backend/relink_identity` | **教务 200（原地落地，正文 43476 字）**；教师 303→/my/home；学生 303→/my/home；管理员 200 | requests 逐身份实测 |
| 守卫与菜单是否同批改 | 是 —— t13 在同一提交 `9989042`「补回邀请码/老账号补挂身份入口**并放宽补挂守卫给教务**」里一起改的 | `git log -S` |

⇒ 队长裁定的 (a)（教务可用）**在菜单与守卫两侧都已落地**，不需要再动 `contacts.py`；
若将来改主意走 (b)（仅系统管理员），要同时收窄菜单 groups **与** 守卫，只改一边就是死角。

**判据强化（本轮新增，防止同类陷阱再被放过）**：

- 脚本新增 `act_url_reach()`：act_url 一律**判落地 URL**，被弹回
  `/my/home | /my | /web/login | /login | /web | /apps` 即 **FAIL**（L2 HTTP 层与 L3 浏览器层双判据）；
- 新增「判据自证」：拿**已知会弹回**的门户页 `/subject/enroll` 当样本（教务实测 303 → /my/home），
  这条自证**判绿就说明判据退化成橡皮图章**（当前输出：`判据·自证(act_url) → 被弹回门户/登录` ✓）；
- 四个真实 act_url 入口（周期排课 / 财务总台账 / 报销审批 / 资料下载）与老账号补挂身份：**全部原地落地 HTTP 200**。

**邀请码那条的脆点（verifier 指出的正确部分）**：act_window 的可见性由「组 + 目标模型读权限」两道闸决定，
`edu.invite.code` 的 ACL 是教务 r/c/w/u=T、教师 F ⇒ 教师卡在第二道闸。
**脆点**：哪天给教师开了 `edu.invite.code` 读权限，菜单会自己冒出来（不靠组挡）。已写进脚本注释与本节。

**口径补充（Odoo 语义）**：`_visible_menu_ids(debug=False)` 会**丢弃 `base.group_no_one`**（即使该用户实际持有），
所以教务看不到仅 `group_no_one` 的菜单；这不是缺陷，是 Odoo 语义（已同时补进 §2.1）。

### 6.3 观察项（不判红、不属 t1 范围）

0. **门户卡片里有两张对教务「点了回首页」**：教务的 `/my/apps` 卡片网格里有
   `/subject/enroll`（选课）与 `/my/reimburse/apply`（发起报销），教务点它们会 303 回 `/my/home`。
   实测（登录态已核 uid 12）：`/my/apps` 上 43 条链接里只有这 2 条不落在原页
   （另 2 条是设计性跳转：`/openeducat/apps_menu → /apps`、`/forum → 论坛首页`）。
   判据与归属：两页的门禁是**身份门禁**（`current_student()` / 教职工报销发起），
   教务账号没有 `op.student` 绑定 ⇒ **分层前后都会这样**，不是权限分层的误伤；
   修法是门户侧按身份隐藏这两张卡（属 t2 门户回归 / 门户卡片引擎的范围，本轮只登记）。
1. **网站应用的原生噪音对教务可见**：`网站` 根下带出 Odoo 原生树（电子商务 30+ 条、实时聊天会话、
   网站编辑器 `website_preview` 客户端动作、讨论/通知设置）。这些**不是权限故障**（L3 里它们要么
   正常渲染、要么落地站点预览/讨论，无 AccessError），但**教务并不需要**。
   若后续要收，方向是「网站编辑器类条目收进 `website.group_website_designer`」——
   属于上一轮菜单收口的决定面，本轮只登记。
2. `edu_apply/controllers/main.py:60` 留了一行调试日志 `_DBG_COLLECT`（每次报名提交打
   warning 日志）。与权限无关，顺手登记（改它超出 t1 inScope）。

---

## 7. 红线自查（验收⑤）

脚本每次都跑，读数取自 SQL（`res_groups_users_rel` + `res_groups_implied_rel` 传递闭包）：

| 红线 | 读数 | 判定 |
|---|---|---|
| 教务 ≠ 系统管理员 | `backoffice@local` 有效组 **20** 个，**不含** `base.group_system` | ✓ |
| 教务组不再隐含系统管理员 | `group_op_back_office_admin`（id 40）implied 传递闭包**不含** `base.group_system`（即 `views/group_tuning.xml` 的 `(3, ref('base.group_system'))` 生效） | ✓ |
| 教务仍是「学院领导」 | 仍持 5 个业务管理组：`group_op_faculty / group_op_attendance_manager / group_op_timetable_manager / group_op_library / group_op_exam_admin` | ✓ |
| 没有「把系统管理员/普通用户加回来」 | 本轮**零**权限改动（没有新增 `base.group_system` 到任何教务面；没有放宽到 `base.group_user`） | ✓ |

> 为什么用 SQL 而不是 ORM：`res.users.has_group` 经 `/web/dataset/call_kw` 调用时参数绑定不上
> （实测 `missing 1 required positional argument`），`ir.model.data` 对教务账号不可读
> （Access Rights 组专属）——两者都会把「查不到」误报成「没权限」。脚本注释里写了这段，避免后人再踩。

---

## 8. 基线与对拍（改前 / 改后）

| 口径 | 队长记录（d2c41de 权限分层前后） | 本轮·**修复前**（16:12） | 本轮·**修复后** |
|---|---|---|---|
| 教务可见菜单（ORM 口径） | 404 → 391 | —— | —— |
| 教务可见菜单（前端 `load_menus` 口径 B） | 31 根 → 12 根（收口轮） | **184 节点 / 12 根** | **181 节点 / 12 根**（本轮 −5 = §6.1 那 5 条死角菜单；t13 +2 = §6.2 补回的两条入口） |
| 其中「看得见点不开」（全量扫描） | 未测 | **5 条** | **0 条** |
| 超管可见那 5 条收口菜单 | —— | 5/5 | **5/5**（收口没把管理面弄丢，脚本 `收口回归` 段守着） |
| 教务可写模型 | 77 → 95（全模型口径） | 41/45（脚本 `--dump` 的 45 个业务模型口径） | 41/45（本轮不动 ACL） |
| 教务有效组 | 22 → 20 | **20** | **20** |
| 教务是否含 `base.group_system` | True → **False** | False | False |

写盘位置：`--dump` 的两份快照（修复前 `/tmp/perm_baseline_before.json`、修复后 `/tmp/perm_baseline_after.json`）
都是**只读采集**，任何一步都不写库；对拍命令见 §9。

> ⚠ 两种菜单口径（ORM 可见 vs 前端 `load_menus`）**不能混用**，code-map §4.1 已记这条。
> 本轮统一用前端口径（脚本 `--dump`），因为它才是「用户看得见的那份」。

## 9. 复跑办法（门禁契约）

```bash
# 全量门禁（覆盖清单 L1+L2+L3 + 三条端到端 + 清场；退出码 0=全绿）
python3 tests/smoke/backoffice_reachability.py

# 基线快照（不动任何数据，只读；用于改动前后对拍）
python3 tests/smoke/backoffice_reachability.py --dump /tmp/perm_baseline.json

# 只跑 L1/L2（快；**非门禁口径**，别拿它当验收）
python3 tests/smoke/backoffice_reachability.py --no-browser

# 静态层分离断言的合成自证（离线，证明这把尺子会红；7 条断言）
python3 tests/smoke/backoffice_reachability.py --selftest

# 浏览器层扩到全部可见菜单（153 条；约 10 分钟，环境抖动会自动重试）
python3 tests/smoke/backoffice_reachability.py --all-menus --skip-flows

# 把「已知缺口」（GAPS 清单）也判红；当前 GAPS 为空（F1/F2 已由 t13 补回，§6.2）
python3 tests/smoke/backoffice_reachability.py --strict-gaps
```

退出码契约：`0` = 全绿（GAP 不算红）；`1` = 有 FAIL（不可达 / 流程失败 / 红线回退 / 夹具残留）；
`2` = 环境不可用（登录失败 / 站点不通 / 缺 playwright）。

脚本自带的三条纪律（都是踩过的坑，写进代码免得再犯）：
1. **夹具自建自清**：所有夹具名字带 `【冒烟】`，清场先按运行期 id 精确删、再按标记兜底删、
   最后按 id 与标记**双口径**核对 `leftover=0`；
2. **环境抖动不是失败**：`ConnectionLostError`/`ERR_EMPTY_RESPONSE`/被弹回 `/apps` 一律重试，
   真失败 = 重试后仍复现；
3. **关键元素不写死**：从菜单自己的视图 arch + `fields_get` 现场取标签，视图改了脚本不用改。

---

## 10. 门禁实跑记录（验收⑥）

命令与退出码（**终态**重跑，2026-09-17 16:3x）：

| 门禁 | 命令 | 退出码 | 读数 |
|---|---|---|---|
| 静态层分离自证（离线） | `python3 tests/smoke/backoffice_reachability.py --selftest` | **0** | 7/7 断言（合成夹具证明这把尺子**会红**；含"扫描面为空即红"守卫） |
| 后台可达性（本任务） | `python3 tests/smoke/backoffice_reachability.py` | **0** | `PASS 100 / FAIL 0 / GAP 0`；首行 = 静态层分离断言，其后是口径 A/B、区分度、入口三身份、孤立根巡检、红线、收口回归；全量扫描见 §5 |
| 汉化 | `python3 scripts/check_english.py` | **0** | must-fix **0** / brand **0** / 路由违规 **0** / 夹具残留 **0**（85 条路由 × 5 角色） |
| 视图 xpath | `python3 scripts/check_view_xpath.py` | **0** | `RESULT=OK`（失败项 0 / 未覆盖 0）；边界常量按文件自带流程同步 19→20，见下 |
| manifest 追踪 | `python3 scripts/check_manifest_tracking.py` | **0** | 模块 11｜已入库 103｜盘上缺失 0｜**在盘上但未入库 0**｜结论 OK |

### 10.1 两个曾经非零的门禁：已按各自文档的流程收口（做法 + 影响面）

**① `check_english`：红在「夹具残留」，不是英文。** 静默窗口首次跑 exit 2，读数里
must-fix / brand / 路由违规**都是 0**，红的 12 条全是 `/downloads` 的「【冒烟】预览文件夹」
（`edu_download_category#87` + `edu_download_file#122/123/124`，`create_date`
**2026-09-17 07:05–07:31**，由 `tests/smoke/aux1_batch_smoke.py:103` 建；该脚本第 90 行自述
「先由教务上传一个【冒烟】PDF（保证有可预览文件），**结束后不清理（幂等）**」）。

处置（2026-09-17 16:34，已向队长报备）：以超管身份走 ORM `unlink`——
`edu.download.file.unlink([122,123,124])` + `edu.download.category.unlink([87])`，
库内文件 **3→0**、分类 **1→0**；复跑 `check_english` → **exit 0**（夹具残留 0）。

- **影响面**：该分类**本来就只有一个夹具文件夹**（真资料 0 条，code-map §4.1 也记了「库内 0 条资料」），
  删掉后 `/downloads` 为空 = 回到真实状态；aux1 下次跑会按 get-or-create 自己重建
  （它先查分类下拉，没有就 POST 建一个再上传 PDF）。
- **残余风险（本轮只治了症状）**，两条可选修法（都属于 aux1 / 门禁 owner）：
  1. aux1 把夹具改成运行期 create → 课后按前缀 DELETE（它本来就是幂等 get-or-create，
     「保证有可预览文件」这条对存量数据的依赖可以去掉）；
  2. `check_english` 给该处登记**显式豁免**（像 `/edu/audit`、`/my/messages` 那样写明理由），
     而不是给 `【冒烟】` 笼统开白名单（门禁文档明确反对）。
- 另注：门禁自带并发守卫——有冒烟在跑时这类标记按 **ENV/跳过**（"在跑夹具 ≠ 残留"）。
  所以「并发窗口 exit 0」**不是**本轮的解法，本轮是真的把存量夹具清掉了。

**② `check_view_xpath`：exit 3 INCOMPLETE，且这一条是本轮自己造成的。** 失败项一直是 **0**，
红的是 `BOUNDARY-DRIFT`：该门禁「规则 7 外部模块清单」按「(模块, 外部模型) 组合」计数，
本轮新增的 `custom_addons/edu_portal/models/menu_reachability.py:66`
（`_inherit = 'ir.ui.menu'`）正好 +1 → 清单 19 → **20**。

处置：按该脚本文件内自带的维护流程（**先证明多出来的是谁 → 确认是合法边界扩张 → 同步常量 +
在「逐次来由」追加一行**）把 `EXPECTED_EXTERNAL_MODELS` 19 → 20，并写清依据（逐条 diff 只多
`edu_portal / ir.ui.menu`，无消失项）；复跑 → `RESULT=OK`、**exit 0**。
（同一次会话里 t10 刚把 18 → 19 记给了 edu_nav 的同一处继承——同一类扩张，不是我改了判据。）

## 11. 交付物与后续

**已交付**

- `tests/smoke/backoffice_reachability.py` —— 本文所有读数的可重跑来源（退出码即门禁；
  覆盖清单 + 全量扫描 + 3 条端到端 + 清场 + 红线 + 收口回归）。
- `custom_addons/edu_portal/models/menu_reachability.py` + `data/menu_reachability.xml` ——
  §6.1 的 5 条原生菜单按业务收口（幂等、缺模块不报错）。
- 本文档 —— 清单、判据、读数、缺口、门禁口径。

**未做（需要队长裁定才能动，逐条都写明了原因与影响面）**

| # | 事项 | 为什么没做 | 建议动作 |
|---|---|---|---|
| ~~F1/F2~~ | ~~`邀请码` / `老账号补挂身份` 对所有人不可见~~ | **已由 t13 补回入口**（菜单 790/791，groups=教务组+系统组），t1 复测可见可达并升格进覆盖清单 | 无需再动（§6.2 保留历史证据） |
| O1 | 网站编辑器类客户端动作（主页/菜单编辑器/权益/优化SEO/HTML-CSS/编辑菜单）对教务仍可见 | 它们**能开**（打开站点预览，不是故障），只是教务不需要；收口属上一轮菜单结构的决定面 | 若要收，收进 `website.group_website_designer` |
| O2 | `check_english` 与 `aux1` 的夹具契约冲突（§10.1） | 本轮只清了存量残留（治症状）；改任一条脚本都会影响别人 | 两条修法任选其一（§10.1） |
| O3 | ~~`check_view_xpath` 边界漂移~~ | **本轮已按流程同步常量并复跑 exit 0**（§10.1） | 无需再动 |
| O4 | 门户卡片 `/subject/enroll`、`/my/reimburse/apply` 对教务「点了回首页」（§6.3-0） | 身份门禁、分层前后都如此，属门户卡片引擎 | 交给门户回归（t2）/卡片引擎 owner |
