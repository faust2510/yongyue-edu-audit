# 班级管理（batch）设计（需求 7 · 校长原话「不要新造」）
> **状态**：`已上线` ｜ **主题**：`班级管理与回收站` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「仅设计」，实际已于 `5bf346d` 交付（2026-09-26 核对发现）。正文未改动。

> **历史状态**：仅设计（第 0 步「落地前查重」+ 第 3 步「读参考」+ 第 4 步「设计摘要」）。
> **本文件不代表已实施**——本次**未写一行代码**、**未新建模块**、**未动 `openeducat_erp/`**、**未动 `custom_addons/`**。
> **需求一句话**（校长原话）：「教务主任可以在学生页面给学生分配班级，老师可以新建/编辑班级，**最好找贴近的直接合并，而不是新造一个出来，避免冗余**。学生接受邀请之后进入自己的班级，学生可以查看自己的班级，看见同班同学、老师。」
> **校长更正（本版并入）**：「**删除班级这个是我搞错了，应该是教务老师**」⇒ 删除归**教务处/back-office**（`openeducat_core.group_op_back_office_admin`），**不给教师**。另：**必须给教务老师一个回收站，防止误删**。
> **口径来源**：`docs/dev-workflow.md` 第 0 步 + 六步闸门 ｜ `CLAUDE.md` 铁律 0 ｜ `docs/research/README.md` ｜ `docs/audit/deprecated-inventory.md`（C1–C7 删除门槛）
> **采集时刻**：**2026-09-18**；读数口径 = 本地库 `edu19`（只读 SELECT）+ 容器 `edu19-clone-web-1`（`docker compose`，`db Up 24h / web Up 14h`）+
> 真机 HTTP 探针（`:8069`，四角色真实登录，只读调用）+ Odoo 19 源码（容器内 `/usr/lib/python3/dist-packages/odoo/`）。
> **行号取证 = 仓内 `openeducat_erp/` 快照（19.0）、本工作区当前 HEAD、Odoo 19 运行时源码**。
> **未验证项**一律集中写在 §14，**不得当结论用**（本仓规范）。
> ⚠ **合规红线**：本文**不贴 `openeducat_erp/` 任何源码**，只给**路径 + 行号 + 字段/记录命名**。

---

## 0. 结论速览（TL;DR）

| 项 | 结论 |
|---|---|
| **裁定（三选一）** | **复用**。**能不能不新建：能。** 基座 `op.batch` + `op.student.course.batch_id` **已经完整承载「班级实体」与「学生在哪个班」**；**回收站也已内建**（`op.batch.active`，`batch.py:36`）⇒ **连软删都不必新造**。缺口只有**入口可见性、归档入口的视图层、门户只读展示、注册后置**四处，**全是"补入口/补口径"，不是"补模型"**。 |
| **零新建** | **不新建模块、不新建模型、不新建表、不新增字段。** 自研代码面 = ①菜单可见性（数据，非代码）②`op.batch.unlink()` **护栏覆写**（照本仓既有先例 `edu_portal/models/fees.py:128-138`）③列表视图加 `active` 一列（恢复基座归档动作）④门户**只读**同班同学分支。 |
| **落地模块（若实施）** | `custom_addons/edu_portal`（既有；门户 + 菜单可见性 + 删除护栏均落它，因为它已依赖 `openeducat_core` 且已有 `group_tuning.xml` / `menu_reachability.xml` 两处同类先例） |
| **头号事实（必须先看）** | **基座 ACL 早就允许老师建/改班级**（`ir.model.access.csv:8` → 实查 `create=True, write=True, unlink=False`）；**挡住老师的是菜单**——`批次` 菜单只在教务处组可见（实查 `load_menus`：教师 76 个可见节点里**没有** `批次`，教务 182 个里有）。⇒ **这不是"缺功能"，是"缺入口"**。 |
| **第二事实（权限口径 · 校长已更正）** | **删除 = 教务处**，与基座对 `op.session`（课节）的既有模式**完全同构**：「User（教师）」建/改/不可删，「Manager（教务）」可删 —— 实查 ACL：`op.session` 对 `group_op_timetable_user`(id 59) 为 `1,1,1,0`、对 `group_op_timetable_manager`(id 60) 为 `1,1,1,1`。⇒ 本设计**照抄这个模式**，不新造口径。 |
| **第三事实（回收站）** | **回收站不必新造**：`active` 已在（`batch.py:36`），**归档 = 软删，且零外键副作用**（`ondelete` 只在**真删**时生效 ⇒ §11 的三档 RESTRICT/SET NULL/CASCADE **一条都不会发生**）。缺口是**视图层 1 处**：基座批次**列表视图没有 `active` 列**（`batch_view.xml:8-14`），而 Odoo 19 的归档动作**只在"视图字段里有 `"active"@"时才出现**（源码硬条件，§7-Q7）。 |
| **删除语义（本设计建议）** | **默认只归档、不真删**；真删入口**保留给"零引用"的班**（照 `fees.py:128-138` 先例：被引用则拒绝并引导到「停用」）。⚠ 注意：**教务今天确实有 `unlink` 权限**（实测 `True`）⇒「只归档不真删」**必须做一次变更**，不是"默认如此"。 |
| **命名（校长拍板项）** | 本仓已有**两套用词**：基座 Odoo 19 自己是「**存档**」（`Archive`→`存档`）/「**取消归档**」（`Unarchive`），**自己都不一致**；本仓自研先例一律「**停用 / 恢复**」。**建议本仓统一「停用 / 恢复」**，见 §13 P6。 |
| **待校长拍板** | **6 项**（老师删除权 / 谁能分班 / 同班同学字段 / 家长可见性 / 注册后置方式 / 「删除」按钮叫什么），见 §13。 |

---

## 1. 目标 / 非目标

### 1.1 目标（拆成 6 条，逐条可验）

| # | 能力 | 用户感受 | 现有状态 |
|---|---|---|---|
| **G1** | 教务主任**在学生页面**给学生分配班级 | 打开一个学生，就地选班、存下 | ⚠ 表单上**没有**班级字段（§7-Q2） |
| **G2** | 老师**新建 / 编辑**班级 | 老师自己就能开班、改班名 | ⚠ ACL 已给建/改，**菜单没给老师** |
| **G3** | **教务老师删除班级** + **回收站防误删** | 教务能清掉开错的班；删错了能捞回来 | ⚠ 权限已有（教务 `unlink=1`）；**回收站半成品**（表单可用、列表不可用，§7-Q7） |
| **G4** | 学生接受邀请之后**进入自己的班级** | 注册完就有班、课表/老师/同学都在 | ❌ 注册流程**完全不写班级**（§7-Q3） |
| **G5** | 学生**查看自己的班级** | 门户能看到"我是哪个班" | ✅ **已可见**（首页班级 chip + 档案页入学卡，§7-Q4） |
| **G6** | 学生看见**同班同学、老师** | 同学名单 + 任课老师名单 | 老师 ✅（`/my/study`）；**同学 ❌ 全仓 0 命中** |

### 1.2 非目标（明确不做，避免范围漂移）

- **不做新班级模型**（校长明确"不要新造"；且 §7-Q1 证明基座够用）。
- **不做新回收站模型 / 新"软删"字段**（`active` 已是回收站；§7-Q7）。
- **不做班级群 / 班级公告 / 班级相册**：本需求只到"看见"，不到"互动"。
- **不做自动分班算法**：不按成绩/性别/人数均衡自动排班。
- **不做学生自助转班**：涉及学籍口径，见 §13 P2/P5。
- **不动基座**：`openeducat_erp/` **只读**；本设计**不修改基座任何文件**（包括不改基座 `batch_view.xml`，而用继承视图）。
- **不决定"老师能否删班"**：校长已更正为教务，但**老师侧是否彻底无删除权**仍列拍板项（§13 P1），本文默认**不给**。

---

## 2. 第 0 步①：先信 code-map

`docs/code-map.md` 逐条读后与本设计相关的锚点：

| 位置 | 内容 | 对本设计的含义 |
|---|---|---|
| `code-map.md:148` | 基座模块职责：「openeducat_core 学生/教师/课程基座：`op.student`、`op.student.course`、…、`op.batch`、`op.subject.registration`…」 | 班级实体与学生归属**都在基座**，本设计第一优先是证明它够用 |
| `code-map.md:161-165` | **权限四层**来源：`group_op_faculty`（教师）/ `group_op_back_office_admin`（教务，**基座源码里 imply `base.group_system`，本仓已于 2026-09-17 解除**）/ `student_login_rule`（学生只见自己） | 本设计所有权限结论必须与四层对齐（§10） |
| `code-map.md:180,192` | `278 学生`（`op.student` 第二根）**已停用**（`CM-278`），子树迁入 `257 学生信息` | ⚠ **坑 1**：`op.student.course` 的编辑菜单挂在**已停用的 278 子树下**（§7-Q2 实证） |
| `code-map.md:256-263` | 权限四层硬约定：教务侧写 `groups="openeducat_core.group_op_back_office_admin,base.group_system"` 并列；**「看得见点不开」缺一即死角**；菜单可见性口径一律用**口径 B** `/web/webclient/load_menus` | 菜单改动**必须四件套齐**：菜单 `groups` + ACL + `ir.rule` + 控制器判据 |
| `code-map.md:245` | 约定第 3 条：**不建自定义组**，复用四层 | 老师建班**不新开组** |
| `code-map.md:249` | 「新功能三件套：先写 `docs/plans/<功能>-design.md` 再动工」 | 本文件就是那个前置件 |
| `code-map.md:169` | 「逐条台账见 `docs/audit/deprecated-inventory.md`」 | 重复登记写台账，不写 code-map |
| `docs/research/README.md:17-24` | 调研索引；`scheduling-approaches.md:40,417,421` 已确立：`op.batch`（班）+ `op.session` 是既有实体，且本场景「**既有班级、又有学生自主选科**」 | 回引该调研（§8.2），**不重复调研** |

---

## 3. 第 0 步②：既有实现对照

> 规矩（`dev-workflow.md:29-30`）：**「没找到」也要写清搜索范围与方式**；**不允许"我记得没有"**。
> 本节所有命令均**在本工作区实跑**（2026-09-18）；DB 读数**只读 SELECT**；HTTP 探针**只读调用**（`check_access_rights` 不落库、`search_read` 只读）。

### 3.1 模型 / 路由 / 菜单 / 向导 / 回收站 五路查重

| # | 查了什么 | 命令 | 命中 | 为什么不复用 / 结论 |
|---|---|---|---|---|
| 1 | 候选新模型 `edu.batch*` / `EduBatch*` | `grep -rn "edu\.batch\|EduBatch" --include="*.py" custom_addons/` | **0 命中**（`edu.invite.code.batch` 是**向导**名，指"批量生成邀请码"，`models/invite_code.py:411`，**与班级无关**） | 名字可用，但**本设计决定不新建**（§7-Q1） |
| 2 | 候选门户路由 `/my/class*`、`/my/batch*` | `grep -rniE "@http.route\('[^']*(class\|batch)" --include="*.py" custom_addons/` | **0 命中** | **全仓没有任何"班级页"路由** ⇒ G5/G6 若做必须新增路由 |
| 3 | 「同班同学 / 同学 / classmate」全仓（代码 + 模板 + 调研 + 设计） | `grep -rniE "同学\|同班\|classmate" --include="*.py" --include="*.xml" custom_addons/ docs/plans/ docs/research/` | **0 条活实现**；仅 3 类噪声：①「相同学位」文案（`edu_brand/views/pages.xml:41`）②通知正文称呼（`seed_batch2.py:269,272,278`）③**"同班级冲突"**（`edu_portal/models/calendar_event.py:11,66` 等）——那是**排课冲突** | **G6「同班同学」确无先例** ⇒ 真缺口；载体可复用（§9.1） |
| 4 | 「班级/批次」在门户模板里的既有落点 | `grep -rniE "批次\|班级" --include="*.xml" custom_addons/edu_portal/views/` → **54 命中** | 学生可见的只有两处：`batch1.xml:588`（档案页班级 chip）、`batch2.xml` 首页 chip（由 `batch2.py:1930-1931,1962-1963` 供值）；其余全是教务/教师侧表单 | ✅ **复用这两处口径**：学生侧"我的班级"**已经显示** |
| 5 | 基座是否有"把学生放进班"的**现成入口** | ① 读 `openeducat_erp/openeducat_core/views/student_view.xml` 结构；② DB 查动作/菜单；③ 全仓查 `student.migrate` | ① `op.student` **kanban** 引用 `course_detail_ids`（`:12`），但 **form 视图（`:76-264`）里没有 `course_detail_ids`、也没有任何 batch 字段**；② 基座动作 **392「学生课程详情」** 的菜单 **282** 挂在 **280 通用 ← 278 学生（`active=f`）** 下 ⇒ **整棵不可见**；③ 基座 **`student.migrate`** 向导（`openeducat_activity/wizard/student_migrate_wizard.py:25-151`，`batch_id` 在 `:33`）动作 **399** 存在但 **`ir_ui_menu` 0 行引用** | ⚠ **"地基有、门没有"**：三个候选入口全部不可达或不存在 ⇒ **G1 缺口 = 入口，不是模型**（§7-Q2） |
| 6 | 门户"选课→选班→落班"链是否已通 | 读 `edu_portal/controllers/enroll.py` + `models/registration.py` | **通了**：`enroll.py:91-121` 按课程列班（**已显式 `('active','=',True)`** `:95`）、`:206-274` 提交注册单；`registration.py:133-212 action_enroll_approve()` 写 `op.student.course`：**无档案建档并写 `batch_id`（`:178-187`）、有档案转班/合班（`:193-195`，限同课程）** | ✅ **本仓唯一已投产的"定班"路径**；**G1 复用它的事务语义，不另写一套写库逻辑** |
| 7 | 教务侧审批入口 | 读 `edu_portal/views/approval_backend.xml:186-232` | 菜单「教务审批」→「选课审批」，域 `[('state','=','submitted'),('doc_type','=','subject_registration')]`；按钮已换绑 `action_enroll_approve`（`:208-211`） | ✅ 既有；G1 若加"教务直接分班"，**共用同一模型方法** |
| 8 | **是否已有"回收站 / 软删 / 归档"的第二套实现** | `grep -rniE "action_archive\|action_unarchive\|active_test" --include="*.py" --include="*.xml" custom_addons/` | `active_test` 仅 1 处（`edu_nav/models/menu_consolidation.py:40`，用于数菜单）；**`action_archive` / `action_unarchive` 全仓 0 命中** | ✅ **没有第二套软删实现** ⇒ 直接用 `active` 基座机制，**不新造**（§7-Q7） |
| 9 | 本仓"删除守卫"的先例（决定删除语义怎么写） | `grep -rn "def unlink" --include="*.py" custom_addons/` | **2 处装护栏**：`edu_portal/models/downloads.py:44-55`（非空文件夹禁删）、**`edu_portal/models/fees.py:128-138`（被引用禁删 + 文案引导「停用」）**；其余 unlink 为正常清理 | ✅ **本仓对"破坏性删除"的既有口径 = 覆写 `unlink()` 装护栏 + 人话文案 + 引导替代路径** ⇒ 本设计照抄（§9.6） |

### 3.2 「没找到」的，也要写清范围（本节的负结论）

| 负结论 | 搜索范围与方式（原样可复现） |
|---|---|
| **全仓没有"班级门户页"** | ① `grep -rniE "@http.route\('[^']*(class\|batch)" --include="*.py" custom_addons/` = 0；② 通读 `code-map.md` §5「路由速查」全表（`:217-239`）逐行核对；③ 汇总 `edu_portal/controllers/*.py` 全部 `@http.route` 后 grep = 0 |
| **全仓没有"同班同学"能力** | 见 §3.1 #3（三种拼写 × 代码/模板/调研/设计四类目录） |
| **全仓没有"班级"专用模型或视图扩展** | `grep -rn "_inherit = ['\"]op.batch" --include="*.py" custom_addons/` = **0 命中** ⇒ 基座 `op.batch` 至今**零自研扩展** |
| **`op.batch` 没有记录规则（`ir.rule`）** | 实查 `select … from ir_rule r join ir_model im … where im.model='op.batch'` → **0 rows** ⇒ 班级**不做记录级隔离**，ACL 是唯一门（§10） |
| **全仓没有第二套软删/回收站实现** | `action_archive` / `action_unarchive` 在 `custom_addons/` = **0 命中**；`active_test` 只有 1 处且用于菜单计数 |
| **老师看不到批次菜单** | 真机 `load_menus`（口径 B）：教师 76 个具名节点中 `批次`=**无**；教务 182 个中=**有**（`264 批次`，`actionPath='batches'`，`actionID=386`）；admin 362 个中=**有**；学生/家长 `load_menus`=**403**（门户用户不进后台） |

---

## 4. 第 0 步③：设计摘要落点

✅ 本文即 `docs/plans/class-batch-management-design.md`（第 4 步产出物）：**既有实现对照在 §3**、**六问 + 回收站问在 §7**、**裁定在 §8**、**边界/数据流/路由/验收在 §9**、**权限在 §10**、**级联在 §11**、**隐私在 §12**、**拍板项在 §13**。

---

## 5. 第 0 步④：升级会不会动业务数据

> 依据 `docs/dev-workflow.md:33-46`（`finding-F5`）：`data` 每次 `-u` **重放**，`demo` 只在安装且开启演示数据时装载。

1. `custom_addons/edu_portal/__manifest__.py` 的 `data` 列表**已含两处同类先例**，可直接照抄形态：
   - `views/group_tuning.xml`（`:41`）—— 用 `(3, ref('base.group_system'))` **解隐含**，**只改组关系，不写业务表**；
   - `data/menu_reachability.xml`（`:45`）—— 注释自述「`<function>` 只改菜单 `group_ids`，**幂等、缺模块不报错**」。
   ⇒ **本设计的菜单可见性改动属第三处同类**，可落 `data/`，**不触碰业务表**。
2. ⇒ **硬约束**：若在 `edu_portal/data/` 新增文件，**只允许写配置类记录**（`ir.ui.menu` / `ir.actions` / 视图 / ACL / `ir.config_parameter`）；**任何写 `op.batch`、`op.student.course`、`op.subject.registration` 的 `<function>` 一律禁止进 `data/`**。
3. ⇒ **预期 `data/` 业务副作用 = 0**：G1~G3 是"开入口 / 装护栏"，G4 是"注册流程加一次写"（**走控制器代码，不走 `data/`**），G5/G6 是**只读门户页**。
4. ⚠ **如实点名邻近风险**：`edu_life/data/demo_life.xml` 末尾的 `<function model="edu.checkin.type" name="_load_demo_records"/>` 按"今天"滚动补写业务表 `edu.checkin.record`（`docs/dev-workflow.md:103-127`，t12 修复中）。**它与班级无关**，但**它证明的规矩对本设计有效**：写业务表的种子函数**不得**放 `data/`。本设计验收若含"计数型判定"，**先按 `dev-workflow.md` 陷阱 1 探活**。
5. ⚠ **与"归档"相关的升级风险（本设计特有）**：归档动作**不是** `data/` 里的记录（Odoo 19 由 web client 生成），故**升级不会重放归档状态**；但若实施时新增"回收站"动作/菜单，**务必用 `noupdate` 或纯 `record`**，**绝不允许**在 `data/` 里写 `<function>` 去"批量归档历史班"（那会改业务数据）**。

---

## 6. 第 0 步⑤：演示数据策略（一句话）

**本设计不新增任何业务演示数据。**
- **分班/归档演示**：用库里**已有的 17 个批次 + 4 名学生**做真机验证（§9.5 验收），**不造新样本**；
- 若实施时确需造样本（例如本地某班学生数为 0 造不出"同班同学"页，或要造一个"零引用空班"验真删），**放 `scripts/seed_batch_mgmt_demo.py`**（仓库既有惯例：`scripts/seed_*.py` 必须**幂等**），**名称前缀一律【演示】**（`code-map.md:247` 第 5 条硬约定），**清理分支写在同一脚本的 `--clean`**（按前缀 `unlink` 并**断言计数归零**）；
- **禁止**放进 `data/`（理由见 §5.2）。
- ⚠ **归档状态本身不进任何种子**：演示脚本若建班，应建**未归档**的；"已归档"由验收步骤现场产生并现场恢复（`leftover=0`）。

> 现有 17 个批次实况（只读 SELECT）：`8 预备科 · 2026级【演示】`（唯一有学生的班：1 名 + 72 节课节）；其余 16 个班学生数全为 **0**，但 **288 节课节 100% 挂班**。**17 条全部 `active=t`** ⇒ **回收站是空的、从未被用过**（§7-Q7）。⚠ 其中大量是**合班**（`B3+B4合班`、`A123+B34合班`…）⇒ **`op.batch` 的语义是"授课班次/合班"，不是"行政班"**；此点直接决定 §12 的隐私口径。

---

## 7. 第 3 步「读参考」：基座逐条结论

> 规矩：**给实查结论，不要猜**。每条都给「读了哪几行 + 用什么命令 + 命中什么」。

### Q1 基座 `op.batch` 现状：字段 / 菜单 / 谁能建改删

**① 模型字段（全量，共 6 个字段 + 1 个唯一约束 + 1 个日期校验）**

`openeducat_erp/openeducat_core/models/batch.py:25-68`：

| 字段 | 定义行 | 类型 / 必填 | 备注 |
|---|---|---|---|
| `code` | `:30` | Char(size=16)，**required** | 唯一约束 `:37-38`（`unique(code)`） |
| `name` | `:31` | Char(size=32)，**required** | |
| `start_date` | `:32-33` | Date，**required**，默认今天 | |
| `end_date` | `:34` | Date，**required** | |
| `course_id` | `:35` | `op.course`，**required** | **班级必须挂在一个课程下** |
| **`active`** | **`:36`** | Boolean，**default=True** | **归档开关 = 回收站本体**（§7-Q7） |

- `_inherit = "mail.thread"`（`:27`）⇒ **有 chatter**（但字段均**未声明 `tracking=True`**，故**不会自动生成字段级留痕**，§14-2）。
- `check_dates()`（`:40-47`）：**结束日不得早于开始日**。
- `name_search()`（`:49-61`）：context `get_parent_batch` 时按课程及**父课程**链展开候选。
- ❌ **没有**：`student_ids`、`faculty_ids`、`subject_ids`、学年/学期、容量、班级类型、教室。⇒ **`op.batch` 是"课程的班次"，不是"学生的容器"**；学生关系**只存在于 `op.student.course.batch_id`**（`openeducat_erp/openeducat_core/models/student.py:34`）。

**② 菜单（id / 组）**

- 声明处：`openeducat_erp/openeducat_core/menu/openeducat_core_menu.xml:55-60` —— 菜单 id `menu_op_batch_sub`，**`groups="group_op_back_office_admin"`**（只给教务处组）。
- 实查库内：菜单 **id `264`**「批次」，`parent_id=262`「课程管理」← `261`「配置」← **`257`「学生信息」（根）**；`active=t`；`action = ir.actions.act_window,386`；挂组 = **`经理`**（= `group_op_back_office_admin`，组 id 40）。
- 动作 `386`：`res_model=op.batch`，`path='batches'`（后台 URL **`/odoo/batches`**），`binding_view_types=form`（`batch_view.xml:93`）。
- ⚠ **`edu_nav` 未改过它**（menu-consolidation-plan.json 与 `edu_nav/data/menu_consolidation_data.xml` grep `264\|批次` 均 **0 命中**）⇒ 264 是**基座原样**。

**③ 谁能建 / 改 / 删（`ir.model.access` 实查，两层证据）**

声明层 `openeducat_erp/openeducat_core/security/ir.model.access.csv:8-9`：

| 行 | 组 | R | W | C | **U** |
|---|---|---|---|---|---|
| `:8 access_op_batch_faculty` | `group_op_faculty` | 1 | **1** | **1** | **0** |
| `:9 access_op_batch_back_office_admin` | `group_op_back_office_admin` | 1 | 1 | 1 | **1** |

`…/ir.model.access.csv:5`（`access_op_batch_parent`）另给 `base.group_portal` **只读**（`1,0,0,0`）。

**库内实查（`ir_model_access` join `ir_model`）**：`596|op.batch|用户|t|t|t|f`、`597|op.batch|经理|t|t|t|t`、`663|op.batch|角色 / 门户网站|t|f|f|f`。
**记录规则**：`op.batch` 的 `ir.rule` = **0 行**。
**组 id 对照（实查）**：`openeducat_core.group_op_faculty` = **39**（User/用户）；`openeducat_core.group_op_back_office_admin` = **40**（Manager/经理）。

**④ 真机 HTTP 探针（四角色真实登录 `/web/session/authenticate` → `call_kw op.batch.check_access_rights`，只读、不落库）**

| 角色（账号） | read | create | write | **unlink** | 口径 B `load_menus` 里有「批次」吗 |
|---|---|---|---|---|---|
| 教师 `faculty@local` (uid 11) | ✅ | **✅** | **✅** | **❌** | **没有**（76 个具名节点） |
| 教务 `backoffice@local` (uid 12) | ✅ | ✅ | ✅ | **✅** | **有**（182 个节点，`264 批次`，path `batches`） |
| 超管 `admin` (uid 2) | ✅ | ✅ | ✅ | ✅ | 有（362 个节点） |
| 学生 `stu@local` (uid 8) / 家长 `parent@local` (uid 10) | 门户用户 `load_menus` = **403**；模型层有 `base.group_portal` **只读** ACL | | | | 不适用 |

> ⚠ **探针方法论如实登记（一次我自己的假红）**：我第一次把 `/web/webclient/load_menus` 当 jsonrpc 包体解析（读 `result`），得到 **`result: None`** ⇒ 误判「**连教务也看不到批次**」。
> 复核发现 **Odoo 19 的 `load_menus` 直接把扁平字典放在 HTTP body 顶层**（无 `result` 包装），改用顶层解析后结论翻转。**本文表中的菜单读数取自修正后的探针**；这条也回证 `code-map.md:263` 的口径 B 说明。

**⇒ Q1 结论**
1. **老师"能建、能改"，但"看不见入口、不能删"**：ACL `create/write=True`（实测），但 `批次` 菜单 `groups` 只挂教务处组。**这是"缺入口"，不是"缺权限"。**
2. **删除只有教务组与超管能做**（教师 `unlink=False`，实测）—— **与校长更正一致，无需改 ACL**。
3. **班级零记录规则**：任何能读到的人看到全部 17 个班；`op.batch` **零自研扩展**、零新增字段、**已有 `active`**。

### Q2 「在学生页面给学生分配班级」现在有没有现成路径

| 候选入口 | 证据 | 结论 |
|---|---|---|
| **A. `op.student` 表单内联分班** | `…/views/student_view.xml`：kanban 引用 `course_detail_ids`（`:12`），**form 视图（`:76-264`）内既无 `course_detail_ids` 也无任何 batch 字段** | ❌ **不存在**（校长要的东西**目前真的没有**） |
| **B. 基座「学生课程详情」菜单** | 动作 **392**（`path='student-course'`）；菜单 **282** ← **280 通用** ← **278 学生（`active=f`）** | ⚠ **记录在、菜单被隐藏**（`CM-278`）⇒ **教务今天也点不进去** |
| **C. 基座 `student.migrate` 向导** | `…/openeducat_activity/wizard/student_migrate_wizard.py:25-151`（`batch_id` `:33`；写 `op.student.course` `:115-123`）；动作 **399** 存在但 **`ir_ui_menu` 0 行**；且 `_check_admission_register()`（`:58-81`）要求源/目标课程同 parent 或同 program | ❌ **无入口**，语义是**转课程**，**不复用**（§8.3） |
| **D. 门户选课 → 教务审批（已投产）** | 学生 `enroll.py:91-121` / `:206-274`；教务 `approval_backend.xml:225-232` → `registration.py:133-212`（建档 `:178-187` / 转班 `:193-195`） | ✅ **唯一已投产的"定班"路径**，但**由学生发起**；教务**不能主动**分班 |

**`op.student.course` 的创建入口（全仓点名）**：① 选课审批（**主路径**，`registration.py:178-195`）；② 基座学生移民向导（无入口）；③ 基座后台内联（菜单 282 被隐藏）；④ 种子脚本（`seed_demo.py:63`、`seed_batch1.py:103,144,181,198`、`seed_batch2.py:39`、`seed_batch3.py`、`seed_tg_demo.py:89-103`）；⑤ 门户家校只读（`contacts.py:110-117`）。

**⇒ Q2 结论**：**"在学生页面给他分班"目前没有可用路径**（无 / 被隐藏 / 无入口 / 学生发起）。**但缺口是"入口"**——基座字段与写库方法**都已存在且已投产**，**不需要新模型**。

### Q3 「学生接受邀请之后将进入自己的班级」——注册流程现在分班吗

**读 `controllers/register.py`（141 行）+ `models/invite_code.py`（491 行）全文，结论：不分班。**

| 步骤 | 证据（行号） | 写班级？ |
|---|---|---|
| 校验邀请码 / 身份 | `register.py:57-70` | — |
| 建账号 + 落层组 | `register.py:83-108`；`invite_code.py:34-39 TIER_GROUPS` | ❌ |
| **绑人码**：挂接既有档案 | `register.py:119-120` → `invite_code.py:305-326 attach_identity()` | ❌ **不写班级**；但**若教务已预先给他建好 `op.student.course`（含 `batch_id`），注册后门户立刻显示该班** |
| **层级码**：自动建「待分配」档案 | `register.py:123-124` → `create_pending_archive()`；学生分支 `:352-358`：**只 `create` 一个 `op.student`** | ❌ **不建 `op.student.course` ⇒ 该生"无班、无课、无师"** |
| 收尾 | `register.py:125` / `:135 redirect('/my/home')` | ❌ |

**⇒ Q3 结论**：
- **注册那一刻系统不选班、也不分班**；层级码注册得到「**【待分配】**档案」（`invite_code.py:30,345`）。学生进门户后课表/科目/老师**全为空**（`lms.py:27-29` 学生视角 = `op.student.course.subject_ids`；`study.py:30-40` 由它推 `batch_ids`）。
- **「接受邀请后就进班」只有两条路**：(a) **注册期选班**；(b) **注册后置**（教务点一下就分）。**二者都是"补一个动作"，不是"补一个模型"** ⇒ 校长拍板项 P5。
- ⚠ **依赖关系**：(b) 的**前置是 G1（教务分班入口）先落地**，否则学生会一直卡在「待分配」。

### Q4 学生查看班级 / 同班同学 / 老师：门户现在有什么

| 视图 | 现状 | 证据 |
|---|---|---|
| **自己的班级名** | ✅ **已有（两处）** | `batch1.py:313-323` → `views/batch1.xml:588` 班级 chip；`batch2.py:1930-1931,1962-1963` 首页 `chip_batch` |
| **自己的课程 / 科目** | ✅ 已有 | `/my/study`（`study.py:270-320`）、`/my/courses`（`lms.py:17-39`） |
| **自己的任课老师** | ✅ **已有（按班过滤）** | `study.py:122-131 _subject_teachers(subject, batch_ids)`（`op.session` 按 `batch_id ∪ subject` 取 `faculty_id`） |
| **自己的课表 / 全班课节** | ✅ 已有且**已按班过滤** | `study.py:43-57 _sessions_of()`（`:47-48` 加 `batch_id in batch_ids`）、`:68-84`；防拼 URL `:358-364` |
| **班级页（"我的班级"独立页）** | ❌ **没有** | §3.1 #2 |
| **同班同学** | ❌ **完全没有** | §3.1 #3 |
| **相关既有页：通讯录** | ⚠ **有，但学生看不到同学** | `/my/contacts`（`contacts.py:47-163`）熟人圈矩阵：管理员=全部；教师=**本班学生/家长**（`:67-74`）；**学生=只有自己**（`:75-80`）；家长=自己孩子+孩子任课教师（`:81-88`）。学生条目字段 = 姓名 + 课程/班名 + **email + phone**（`:110-126`）；教师条目含 email/phone（`:93-108`） |

**⇒ Q4 结论**：**"学生看自己的班"已实现**（首页 chip + 档案卡）；**"看见老师"已实现**；**"看见同班同学"是真缺口且无先例**，但**载体可复用** `/my/contacts` 的熟人圈矩阵（教师分支 `:67-74` 是现成模板）。**字段口径是校长拍板项（§12 / §13 P3）。**

### Q5 删除班级的级联影响（最容易出事的一条）

**实测口径：查 `pg_constraint`（引用 `op_batch` 的外键），逐列取 `confdeltype`。共 21 条，按删除语义分三档：**

| 档 | 语义 | 表 / 列 | 校长的感受 |
|---|---|---|---|
| **🔴 挡住（`RESTRICT`）** | **删不掉**，报外键约束错误 | `op_session.batch_id`（**课节**）、`op_assignment.batch_id`（**作业**）、`op_attendance_register.batch_id`（**考勤登记簿**）、`op_exam_session.batch_id`（**考试安排**） | "这个班删不掉"（**这是好事**） |
| **🟡 静默解绑（`SET NULL`）** | **删得掉，且不报错**——挂在上面的记录被**清空班级** | **`op_student_course.batch_id`（学生分班！）**、`op_subject_registration.batch_id`（选课注册单）、`op_exam.batch_id`、`op_attendance_sheet.batch_id` / `op_attendance_line.batch_id`、`op_student_fees_details.batch_id`、`op_classroom.batch_id`、`edu_event.batch_id`、`edu_schedule_holiday.batch_id`、`op_admission.batch_id`，以及 `op_held_exam` / `op_room_distribution` / `time_table_report` / `student_migrate`（transient 向导） | "**删完学生全没班了，而且没人告诉你**"（**这是坏事**） |
| **🔵 跟着删（`CASCADE`）** | 连同子记录一起删 | **`edu_attend_self_token.batch_id`（QR 自助签到令牌）**、`generate_time_table.batch_id`（transient） | 令牌失效（**可接受**，但要知道） |

**机制说明（为什么"必填字段"会变成 RESTRICT）**：Odoo 19 的 `orm/fields_relational.py:270-282` —— **未显式声明 `ondelete` 的 `Many2one`，Odoo 自动取 `'restrict' if required else 'set null'`**；`:283-287` 明文拒绝"required + set null"。
⇒ 实测吻合：`op_session` / `op_assignment` / `op_attendance_register` / `op_exam_session` 的 `batch_id` 都是 **`required=True` 且未写 ondelete**（如 `…/openeducat_timetable/models/timetable.py:45-46`、`…/openeducat_assignment/models/assignment.py:49`、`…/openeducat_attendance/models/attendance_register.py:36-37`、`…/openeducat_exam/models/exam_session.py:34-35`）⇒ 自动 RESTRICT；
而 `op.student.course.batch_id`（`…/openeducat_core/models/student.py:34`）**非必填** ⇒ 自动 **SET NULL**；`op.subject.registration.batch_id`（`…/subject_registration.py:35`）同样 **SET NULL**。

**库内实况（只读 SELECT）**：`op_batch` **17**（全部 `active=t`）；`op_student_course` **4** / 带 `batch_id` **1**；`op_session` **288** / 带 `batch_id` **288（100%）**；`op_subject_registration` **12/12**；`op_assignment` **5/5**；`op_attendance_register` 带班 **1**；`edu_attend_self_token` **18**；**有学生的班只有 id=8（1 名）**。

**⇒ Q5 结论（可直接当口径用）**
1. **今天任何一个"被排过课"的班都删不掉**（288 节课节 100% 挂班，`op_session` 是 RESTRICT）⇒ 教务点删除会得到外键错误。**这是保护，不是 bug。**
2. **真正危险的是"没排课的班"**：若挂了**学生**，删它会**静默解绑**（SET NULL），**不报错、无提示、无留痕**（`op.batch` 无 `tracking` 字段）。
3. **连带面比"课节"大**：作业 / 考勤登记簿 / 考试安排都会挡；考试 / 点名表 / 费用明细 / 校历活动 / 停课日会被**静默清空班级**；QR 自助签到令牌会被**删掉**。
4. ⇒ **这正是"必须给回收站"的实证依据**（校长硬要求）：**归档不会触发上面任何一档**（§7-Q7、§11.4）。

### Q6 权限口径：老师建/改、教务删除（**校长已更正**）

**先给实查事实，再给建议。**

| # | 事实 | 证据 |
|---|---|---|
| 1 | 基座 ACL：教师 **建/改可、删不可**；教务 **全可** | `…/openeducat_core/security/ir.model.access.csv:8-9`；真机实测教师 `create=True/write=True/unlink=False`、教务 `unlink=True` |
| 2 | 教师**看不见**批次菜单 | `load_menus`（口径 B）：教师 76 个节点中无「批次」；`openeducat_core_menu.xml:55-60` `groups` 只挂教务组 |
| 3 | **基座对"课节 `op.session`"就是这个模式** | ACL 实查：`op.session` 对 `group_op_timetable_user`(**id 59**) `= 1,1,1,0`（能建能改不能删）、对 `group_op_timetable_manager`(**id 60**) `= 1,1,1,1`（能删） |
| 4 | 教务组**已 imply 教师组**（并列不产生额外权） | `op_security.xml:45-51`（基座里还 imply `base.group_system`，**本仓已于 2026-09-17 解除**，`custom_addons/edu_portal/views/group_tuning.xml:13-25`）；`group_tuning.xml:20-21` 另把 `group_op_timetable_user/manager` 并列授予教务 |
| 5 | **教务今天确有 `unlink`** | 真机 `check_access_rights('unlink') → True`（uid 12），库内 `597\|op.batch\|经理\|t\|t\|t\|t` |

**建议（按四层，逐层写"为什么"）：**

| 层 | 建 | 改 | **删（真删）** | 归档/恢复 | 理由 |
|---|---|---|---|---|---|
| `base.group_system` 超管 | ✅ | ✅ | ✅ | ✅ | 基线不变（`code-map.md:257` "保管理员最高权"） |
| `group_op_back_office_admin` **教务** | ✅ | ✅ | **✅（校长更正：删除归教务）** | ✅ | ① **与基座对 `op.session` 的模式同构**（事实 3）⇒ **不新造口径**；② 教务是业务口径责任人（`code-map.md:258` 明确「课程·科目·**批次**·课节」属教务组）；③ **本设计不改基座 ACL**（教务的 `unlink=1` 原样保留） |
| `group_op_faculty` **教师** | ✅ **本设计要求"开通菜单让它真能用"** | ✅ **同上** | **❌ 不给**（校长更正 + 基座原样） | ⚠ **待拍板 P1** | ① **建/改保留的证据**：基座 ACL 明写 `1,1,1,0`（`:8`）；教师**已经能给自己班排课/建课节**（`op.session` 的 User 档 `1,1,1,0`），**能排课却不能建班**是当前的不一致 ⇒ 开建/改即可消除；② **删除不给的理由**：删班是**破坏性 + 影响学生学籍归属**且当前 `SET NULL` **静默解绑**（§11），后果由**学生**承担；而基座/本仓对"教师无权删"是**既有默认**（`op.session` 同样 `unlink=0`） |
| `base.group_portal` 学生·家长 | ❌ | ❌ | ❌ | ❌ | 维持只读（`ir.model.access.csv:5`）；学生**只看得见自己**（`op_security.xml:54-60 student_login_rule`） |

**⚠ 关于"老师能不能归档/恢复"（P1 的第二半）——本文建议：可以给老师"归档"自己的班，但不给"恢复"？**
不建议这么切。理由：归档虽然比删除温和，但**仍会让该班从所有"选班"下拉中消失**（`enroll.py:93-95` 已显式过滤 `active`），**对新招生/分班是实质影响**。⇒ **本文建议归档/恢复与删除同层（教务 + 超管）**，教师在班级上只有**建 / 改 / 看**。**这是拍板项 P1 的默认值。**

### Q7 回收站：现有菜单/视图到底暴露了「归档 / 取消归档」没有？（**校长硬要求，本节专答**）

**结论先说：回收站机制已内建（`active`），但入口是"半成品"——表单能用、列表不能用。**

**① 机制在（复用依据）**
- `op.batch.active = fields.Boolean(default=True)` —— `openeducat_erp/openeducat_core/models/batch.py:36`（同文件 `:25` `class OpBatch`、`:27` `_inherit = "mail.thread"`，与队长复核一致）。
- Odoo 的 `active` 就是**软删**：`active=False` 后，默认 `search` **不再返回**它（`orm/models.py:5355-5363`：`active_test` 会自动追加 `('active','=',True)`），**记录与全部外键完好**。

**② Odoo 19 的归档动作是"条件出现"的**（这是缺口的技术根因）

| 位置 | 事实（源码，容器内 `/usr/lib/python3/dist-packages/odoo/`） |
|---|---|
| `web/static/src/views/list/list_controller.js:107-112` | `archiveEnabled = "active" in this.props.fields ? !...readonly : ... : false`；**上一行注释原文：`// enable the archive feature in Actions menu only if the active field is in the view`** |
| `…/views/form/form_controller.js:585-593` | 表单同条件（`"active" in this.model.root.activeFields`），同样注明 **"only if the active field is in the view"** |
| `…/views/list/list_controller.js:446-459` | ☰ 菜单里 `archive`（`oi oi-archive`）/ `unarchive`（`oi oi-unarchive`）两项，`isAvailable: () => this.archiveEnabled` |
| `…/model/relational_model/dynamic_list.js:218-231` | `toggleArchiveWithConfirmation()`：**归档有确认弹窗**（默认文案 `"Are you sure that you want to archive all the selected records?"`，确认键 `Archive`）；**⚠ 取消归档（unarchive）没有确认弹窗**，直接执行（`:228-230`） |

**③ 基座 `op.batch` 视图的实际情况（逐视图判定）**

| 视图 | 是否含 `active` | 归档/取消归档可用？ | 证据 |
|---|---|---|---|
| **列表** `view_op_batch_tree` | **❌ 没有**（只有 name / code / start_date / end_date / course_id） | **❌ 不可用 ⇒ 无法批量归档** | `views/batch_view.xml:8-14` |
| **表单** `view_op_batch_form` | **✅ 有**（`<field name="active" invisible="True"/>` + ribbon `title="Archived"`） | **✅ 可用**（表单 ☰ → 归档 / 取消归档） | `views/batch_view.xml:26-28` |
| **搜索** `view_op_batch_search` | — | **✅ 已有「Archived」过滤器**（`domain=[('active','=',False)]`） | `views/batch_view.xml:67` |
| **动作** 386 | — | `domain=[]`（默认受 `active_test` 影响 ⇒ **列表默认不显示已归档班**） | `views/batch_view.xml:96` |

> ⚠ **"搜索视图里已有 Archived 过滤器"是有效的**：`orm/models.py:5355-5363` 的判据是「**domain 里显式提到 `active` 就不再自动追加**」⇒ 该过滤器**能搜出已归档班**（这是复用它的前提）。

**④ 库内实况**：`select active, count(*) from op_batch group by active` → **`t|17`** ⇒ **一条都没归档过**，回收站是空的、功能从未被使用。

**⑤ "归档"的连带影响（与 §11 真删对照）**

| 影响面 | **真删（`unlink`）** | **归档（`active=False`）** |
|---|---|---|
| 课节 `op_session` / 作业 / 考勤登记簿 / 考试安排 | **被 RESTRICT 挡住** | ✅ **一条都不动**（`ondelete` 只在真删时生效） |
| 学生分班 `op_student_course.batch_id` | **静默清空（学生没班了）** | ✅ **不变**——学生仍指向该班 |
| 选课注册单 / 考试 / 点名表 / 费用明细 / 校历活动 / 停课日 | **静默清空** | ✅ **不变** |
| QR 自助签到令牌 | **一起删掉** | ✅ **不变** |
| 学生门户能否看到"我的班" | 学生**失去班级** | ✅ **仍能看到**（`study.py:30-40` 从 `op.student.course` 取 `batch_id`，**不过滤 `active`**；`batch1.py:320`、`batch2.py:1930-1931` 同理） |
| **新选班下拉** | 不再出现 | ✅ **也不再出现**（`enroll.py:93-95` **已显式** `('active','=',True)`）——**这正是"归档 = 停止招生/停止新分班"的现成语义** |
| 可逆性 | **不可逆** | ✅ **一键恢复**（`active=True`） |

**⇒ Q7 结论（直接回答队长两问）**
1. **回收站要不要新造？不要。** 机制（`active`）已在，且**归档的语义在本仓已经"被写好了一半"**：`enroll.py:93-95` 早就显式按 `active` 过滤班级下拉 ⇒ 归档即"该班退出新分班/选课"。
2. **缺口是「一个视图 + 一个动作」还是新模型？→ 都不是新模型；精确地说是「视图层 1–2 处小改」**：
   - **必须**：让**列表视图**带上 `active`（继承 `view_op_batch_tree` 插一列）⇒ 恢复 Odoo 自带的「归档 / 取消归档」菜单项，并支持**批量归档**（基座自带确认弹窗）。
   - **建议**：加一个「**已停用班级（回收站）**」`ir.actions.act_window`（同 `res_model=op.batch`，`domain=[('active','=',False)]`，`context={'active_test': False}` 双保险）+ 菜单项，让教务一眼看到回收站里有什么、一键恢复。
   - **文案/汉化**：见 §13 P6（基座自己把 `Archive` 翻成「存档」、`Unarchive` 翻成「取消归档」，**不一致**）。
   - **0 个新模型 / 0 张新表 / 0 个新字段。**

---

## 8. 三选一裁定 + 理由 + 收口触发条件

### 8.1 裁定（逐能力，落成台账里的一个字）

| 能力 | 裁定 | 承载物（替代路径） | 扩展方式 | 依据 |
|---|---|---|---|---|
| **G1 教务在学生页分班** | **复用** | `op.student.course`（基座）+ `registration.py:133-212` 建档/转班语义 | 在 `edu_portal` 内加"分班"入口，**共用 `action_enroll_approve` 同款写库语义**，**不新增模型** | §7-Q2 D |
| **G2 老师建/改班级** | **复用** | 基座 `op.batch` + 动作 386 + 菜单 264 | **只改菜单可见性**（`groups` 加入教师组）。ACL **已就位**，**零 ACL 改动** | §7-Q1 ④ / §7-Q6 |
| **G3 教务删除 + 回收站** | **复用（回收站）+ 护栏（真删）** | **`op.batch.active`（基座内建软删）** + Odoo 19 自带归档动作/确认弹窗 | ① 列表视图加 `active` 列（恢复归档动作）；② 可选「回收站」动作+菜单；③ `op.batch.unlink()` 护栏覆写（照 `fees.py:128-138`） | §7-Q7 / §9.6 |
| **G4 注册即进班** | **复用 + 补一个动作** | `create_pending_archive()`（`invite_code.py:337-358`）+ `op.student.course` | **二选一（拍板 P5）** | §7-Q3 |
| **G5 学生看自己的班** | **复用（已实现）** | 首页 chip（`batch2.py:1930-1931`）+ 档案卡（`batch1.py:320`） | **零改动**；验收里断言 | §7-Q4 |
| **G6 学生看同班同学 / 老师** | **复用载体 + 小扩展** | **老师**：`/my/study` 已实现；**同学**：`/my/contacts` 熟人圈矩阵 | 在 `contacts.py` 矩阵里**对称地**加"学生↔本班同学"分支（教师分支 `:67-74` 是模板） | §7-Q4 |

### 8.2 为什么"复用"而不是"合并/新建"

**不新建（三条硬理由）**：
1. **校长明确"不要新造"**；`op.batch`（6 字段 + 课程归属 + `mail.thread` + **`active` 回收站**）与 `op.student.course.batch_id`（**含 `tracking=True`**）已构成完整「班 + 学生归属 + 软删」三件套。**没有任何一条需求需要模型层没有的东西。**
2. **`op.batch` 至今零自研扩展**（§3.2），新建会立刻制造本仓最忌讳的"同类模型第二套"（`docs/audit/feature-overlap-audit.md` 的 8 类重叠正是这么长出来的）。
3. **新建的成本不在建，在收口**：新模型要和 288 节课节、12 份注册单、5 份作业、`op.attendance.*`、`op.exam.*`、`edu_event`、`edu_schedule_holiday` 的 `batch_id` 全部对接——**21 条外键会变成 42 条**；且**要重造一个回收站**（而 `active` 已经有）。

**不"合并"（本需求没有第二套实现可并）**：命中四个候选（学生课程详情 / 学生移民向导 / 选课审批 / 通讯录）**各自用途不同**，不是同一功能的两个实现 ⇒ **不适用"合并"**。（唯一"重叠"是 C 与 D 都写 `op.student.course`，但 C 无入口、语义是转课程 ⇒ 处置是**"明确不做并写明唤醒条件"**，见 §8.3。）

**为什么落 `edu_portal`**：① 菜单可见性已有先例落点（`edu_portal/data/menu_reachability.xml`，`__manifest__.py:45`）；② 门户页与身份分流全在 `edu_portal`；③ 已 `depends: openeducat_core`（`__manifest__.py:23`）⇒ **零新依赖**；④ **本仓"删除护栏"的两个先例都在 `edu_portal/models/`**（`fees.py` / `downloads.py`）⇒ 护栏放这里最不意外。

### 8.3 「明确不做」的两项（带唤醒条件，`dev-workflow.md:238-256`）

| 明确不做 | 理由 | **唤醒条件** |
|---|---|---|
| **不用基座 `student.migrate` 向导做分班** | 无菜单（0 引用）；`_check_admission_register()`（`student_migrate_wizard.py:58-81`）要求源/目标课程同 parent 或同 program，**分班不该要求换课程**；用它做分班会让"分班"顺带改课程与学科，语义污染 | **机会型**：若将来另立任务做"学生转课程/升学"，顺手复用它 |
| **不给 `op.batch` 加字段**（如 `student_ids` / `faculty_ids` / 学年学期 / `"已删除"标记`） | 学生会话归属的**事实源**是 `op.student.course`（全线按它过滤）⇒ 再存一份 = **两套事实源**，必然漂移；**回收站也不需新字段**（`active` 已是标准软删，另立 `is_deleted` 会与 Odoo 全线机制打架） | **里程碑型**：若某天要"行政班 vs 授课班分离"或"多级回收站（保留期/彻底清除）"被提出，**另立设计** |

### 8.4 收口触发条件（`dev-workflow.md:62` 的"新建并存"栏；本设计裁定为复用，故改为**复发触发条件**）

| 编号 | 触发条件（可观察、可判定） | 触发后必须做什么 |
|---|---|---|
| **T1** | 出现**第二个** `op.batch` 的 `_inherit`（`grep -rn "_inherit = .*op.batch" --include="*.py" custom_addons/` 从 0 → ≥1） | 停手，回到第 0 步查重；确认是否与本文 §8.1 冲突 |
| **T2** | 出现**第二个**"班级门户页"路由（`grep -rniE "@http.route\('[^']*(class\|batch)" custom_addons/` 从 0 → ≥1） | 同上；核对是否应并入 `/my/contacts` 口径 |
| **T3** | 出现**第二个**"给学生定班"的写库入口（今天只有 `registration.py:178-195`） | 同上；**写库语义必须收敛到一处**（本仓"唯一入口"惯例，参见 `edu.grade.history.edu_apply_marks`，`registration.py:394-425`） |
| **T4** | 出现**第二个**"软删 / 回收站"实现（`grep -rn "action_archive\|action_unarchive\|is_deleted" custom_addons/` 从 0 → ≥1） | 同上；**必须**回收到 `active` 口径（本仓"唯一实现"惯例，参见打卡两套合一的教训） |
| **T5** | 菜单 264 的 `groups` 被**第三次**修改（本设计若实施即第 1 次） | 审查是否应改为更稳的机制（如按 `edu_nav` 收口流程统一声明） |

---

## 9. 复用 vs 自研边界 / 数据流 / 路由与动作清单 / 删除语义 / 验收标准

### 9.1 复用 vs 自研边界（**逐条划线，自研部分极小**）

| 对象 | 复用（零改动） | 自研（若实施） |
|---|---|---|
| 班级实体 | ✅ **全部**：`op.batch`（6 字段 / 校验 / `mail.thread`） | **无** |
| **回收站（软删）** | ✅ **全部**：`active`（`batch.py:36`）+ Odoo 19 归档动作/确认弹窗（`list_controller.js:446-459`、`dynamic_list.js:218-231`） | **无新机制**；仅"让入口出现"（列表视图加 `active` 列） |
| 学生归属 | ✅ **全部**：`op.student.course.batch_id`（+ 3 条唯一约束 `student.py:43-51`） | **无** |
| 写库语义 | ✅ `registration.py:133-212`：同课程校验、建档、转班、`state='running'` | **无**（新增入口调用同款语义） |
| 老师建/改班 | ✅ ACL（`ir.model.access.csv:8`）+ 动作 386 + 视图族 | **菜单 `groups` 一行**（数据，非代码）+ 汉化 |
| **真删护栏** | ✅ Odoo 的 `ondelete` 机制（`fields_relational.py:270-282`）**+ 本仓护栏写法先例**（`fees.py:128-138`） | **`op.batch.unlink()` 覆写**（约 1 个方法）+ `edu.audit.log` |
| 学生看自己的班 | ✅ 已有两处（`batch2.py:1930-1931`、`batch1.py:320`） | **无** |
| 学生看老师 | ✅ `/my/study`（`study.py:122-131`） | **无** |
| 学生看同学 | ✅ **载体**：`/my/contacts` 矩阵（`contacts.py:47-163`） | 矩阵加"学生↔本班同学"分支（约 10 行量级）+ 模板分组文案 |
| 门户身份分流 | ✅ `current_student/current_faculty/current_parent/privileged_staff` | **无** |
| 注册后置 | ✅ `create_pending_archive()` + `edu.message._notify_event` | 注册后置动作 |

### 9.2 数据流（真机口径，逐步给文件:行号）

**流程 A —— 教务给学生分班（G1）**

```
教务后台 → 学生（op.student）→ [新增入口：分班]
  → 选「课程 → 班级」（候选来自 op.batch；基座 name_search 的 get_parent_batch 分支
     已支持按父课程链过滤，batch.py:49-61）
  → 复用 registration.action_enroll_approve 的语义写 op.student.course：
       · 无 running 档案 → create{student_id, course_id, batch_id, 学期, state='running'}（registration.py:178-187）
       · 有档案且同课程 → write{batch_id}（转班/合班，registration.py:193-195）
  → 写 edu.audit.log（'分班'，registration.py:208-211 同款）
  → 通知学生：edu.message._notify_event（registration.py:100-128 同款）
```

**学生侧立即可见**：`batch2.py:1930-1931` → `batch1.py:320` → `study.py:30-40 / 43-57 / 122-131` → `/my/courses`。

**流程 B —— 老师建/改班级（G2）**

```
老师后台 → 学生信息 → 配置 → 课程管理 → 批次（菜单 264，本设计使其对教师可见）
  → 新建：填 name/code/start_date/end_date/course_id（course_id 必填，batch.py:35）
  → 校验：check_dates()（batch.py:40-47）+ unique(code)（batch.py:37-38）
  → edit：同一条菜单点开改（write=True 实测）
  → 删除 / 归档：❌ 教师无 unlink（实测 False）；列表上也没有归档入口（视图未含 active）
```

**流程 C —— 教务归档一个班（G3 回收站，**推荐主路径**）**

```
教务后台 → 批次列表（动作 386）
  → 选中一行/多行 → ☰ → 「归档」（Odoo 19 自带，需列表视图含 active 字段）
  → 确认弹窗（Odoo 自带，dynamic_list.js:220-227）→ 写 op_batch.active = false
  → 效果：该班退出所有"选班/分班"下拉（enroll.py:93-95 显式过滤 active）；
          学生仍属该班、课表/门户显示不变（study.py:30-40 不过滤 active）；
          课节/作业/考勤/考试/注册单/费用/令牌【一条都不动】
  → 恢复：搜索视图「Archived」过滤器（batch_view.xml:67）或「已停用班级」动作
          → 选中 → ☰ → 「取消归档」（⚠ 无确认弹窗，直接生效）
```

**流程 D —— 教务真删一个班（G3 护栏）**

```
教务 → 批次 → 选中 → ☰ → 删除
  → edu_portal 覆写的 op.batch.unlink() 先用 search_count 逐档计数：
       🔴 op.session / op.assignment / op.attendance_register / op.exam_session 有引用？
          → 有：拒绝 + 人话文案（「该班还有 N 节课节…」）+ 引导「请改用『停用』」
       🟡 op.student.course / op.subject.registration / op.exam / 点名表 / 费用明细 / 校历活动 / 停课日？
          → 有：拒绝 + 列出 N（避免 SET NULL 静默解绑学生）
       🔵 edu.attend.self.token？ → 提示将一并失效
       全部为 0 → super().unlink()（**给"建错的空班"留真删出口**）
  → 真删成功时写 edu.audit.log('删班', …)
（护栏对所有路径生效：后台、脚本、导入 —— 因为它在模型层）
```

**流程 E —— 学生注册后进班（G4，二选一，待拍板）**

```
选项 C1（注册期选班）：
  /register 表单（register.py:41-51）加「报读班级」下拉
  → register_submit（:53-135）建账号后，用 op.batch.course_id 推出 course_id
  → create op.student.course{batch_id}（走 registration.py 同款语义）
  → redirect /my/home（:135）时课表/老师已就位
选项 C2（注册后置待办）：
  create_pending_archive()（invite_code.py:337-358）后额外落一条「待分班」提示
  → 教务在既有「教务审批」族（views/approval_backend.xml）看到待办 → 用流程 A 分班
  → 学生第一眼看到「待分配」（edu_pending_setup=True，invite_code.py:345）
```

> ⚠ **C2 不满足校长"接受邀请之后将进入自己的班级"的字面要求**（学生仍需等教务）⇒ **必须校长选**（§13 P5）。两个选项**都不新建模型**。

### 9.3 路由与动作清单（`dev-workflow.md:92` 第 4 步要求）

> **本设计未实施**；下表是**若实施时的完整清单**。

| # | 类型 | 路径 / id | 归属 | 权限层（四层） | 复用 / 新增 |
|---|---|---|---|---|---|
| 1 | 菜单 | `openeducat_core.menu_op_batch_sub`（库内 id **264**，`openeducat_core_menu.xml:55-60`） | `edu_portal/data/` 覆写（先例 `menu_reachability.xml`） | 教师 + 教务 + 超管 | **改（一行 `groups`）** |
| 2 | 动作 | `act_open_op_batch_view`（id **386**，`path='batches'`） | **不动** | — | 复用 |
| 3 | **视图** | **列表继承视图**：给 `view_op_batch_tree` 插 `active` 列（建议 `optional="hide"`） —— **这是回收站的关键一步** | `edu_portal/views/` | — | **新增（继承，不改基座）** |
| 4 | **动作 + 菜单** | **可选**：「已停用班级（回收站）」`ir.actions.act_window`（`domain=[('active','=',False)]` + `context={'active_test': False}`）+ 菜单项 | `edu_portal/views/`、`data/` | 教务 + 超管 | **新增（可选）** |
| 5 | 按钮/入口 | 学生页面分班（G1）：挂 `op.student` 表单按钮，**优先复用动作 392** | `edu_portal/views/` + `models/` | 教务（+ 教师？见 §13 P2） | **新增（入口）** |
| 6 | 覆写方法 | **`op.batch.unlink()` 护栏**（三档计数 + 人话文案 + 引导「停用」） | `edu_portal/models/` | 层无关（护栏对所有人生效） | **新增（约 1 个方法）** |
| 7 | 记录规则 | `op.batch` 的 `ir.rule`（**今天 0 条**） | `edu_portal/security/` | 仅当 §13 P1 选"限老师自己的班" | **新增（条件性，本设计默认不需要）** |
| 8 | 门户路由 | **无新增路由**（G6 走 `/my/contacts`，`contacts.py:47`） | `edu_portal/controllers/contacts.py` | 门户（`base.group_portal` + 身份函数分流） | **改（矩阵加分支）** |
| 9 | 账号归属 | 注册后置（G4 C2）：**不新增路由**，复用 `/my/home` + 既有审批菜单 | `controllers/register.py`、`models/invite_code.py` | 公开/门户 | **改** |
| 10 | 审计 | `edu.audit.log`（`action='分班'` / `'归档'` / `'恢复'` / `'删班'`） | 同 #5/#6 | — | 复用 |
| 11 | 通知 | `edu.message._notify_event`（事件 key 需在 `notify_pref.py:15-22 NOTIFY_EVENTS` 登记，否则用户**关不掉**——C-1 同款结论） | `edu_portal/models/notify_pref.py` | — | **改（若发通知）** |
| 12 | 汉化 | 新按钮/字段文案进 `edu_zh` | `edu_zh/i18n_extra/zh_CN.po` | — | 复用流程 |

**明确不新增**：❌ 新模块 ❌ 新模型 ❌ 新表 ❌ `op.batch` 新字段 ❌ 新门户路由 ❌ 新权限组 ❌ 新软删机制。

### 9.4 老师侧"建/改班级"的空档

- 基座 `op.batch` 表单（`batch_view.xml:18-44`）是**最小表单**：无学年/学期、无教师、无学生列表、无容量。
- ⚠ **`help_center.xml:236` 目前对老师写的是**：`建班级：教务后台 →「配置」→「课程管理」→「批次」，为课程创建班级（选好学年/学期）` —— **"选好学年/学期"是错的**：`op.batch` 没有这两个字段（`batch.py:30-36`）。**既有文档与实况不一致**，实施时应一并修正（不在本次 inScope，§14-4）。**且它现在写的是"教务后台"，若 P1/P2 决定给老师开班，这句也要改。**

### 9.5 真机可验证的验收标准（`dev-workflow.md:92` 第 4 步 + `:129-146` 陷阱 2）

> 规矩：断言写成 `first == 303` + `Location` 精确匹配（不许"跟随后 200"）；**改了路由/控制器必须有"打完就摸页面"的判据**；**测试载体必须先被断言合法**。

| # | 判据（真机可执行） | 通过线 | 反例（不许这么写） |
|---|---|---|---|
| **A1** | 教师登录 → `load_menus`（口径 B）→ **含 `批次`（id 264）** 且 `actionPath='batches'` | 命中 | ❌ 只看 `load_menus` 的 HTTP 200 |
| **A2** | 教师 GET `/odoo/batches` → **200** 且列表含 ≥1 个班名 | 200 + 内容非空 | ❌ 只看 200 不看内容 |
| **A3** | 教师 `op.batch.create`（带 name/code/start_date/end_date/course_id）→ **成功**；随后教师对自己建的测试班 `unlink` → **必须失败**（无 unlink 权） | 建成功 / 删失败 | ❌ 用教务账号测教师权限（**载体不合法**） |
| **A4** | 教务 `check_access_rights('unlink')` → **True**（校长更正后**应保持 True**） | True | — |
| **A5** | **回收站可用性（列表）**：教务打开批次列表 → ☰ **含「归档」项**（`archiveEnabled` 为真）→ 归档 1 个测试班 → 该班从默认列表**消失**、`active=false`、**搜索「Archived」能找回** | 三步全过 | ❌ 只断言"记录变了"不看 UI 入口（那就没验回收站） |
| **A6** | **归档零副作用**：截图/记录归档前后 `select count(*) from op_session where batch_id=X`、`op_student_course`、`op_subject_registration`、`edu_attend_self_token` → **四个数都不变** | 全不变 | ❌ 不测副作用（那"归档"="真删"就没区别了） |
| **A7** | 归档后学生侧不变：学生登录 → `/my/home` **仍含自己的班名**；`/my/study` 仍有课表/老师 | 仍在 | ❌ 只测后台 |
| **A8** | 归档后新分班不受影响：`/subject/enroll` 的班级下拉**不含**已归档班 | 不含 | — |
| **A9** | **取消归档**：教务在「Archived」过滤器下选中 → ☰ → 取消归档 → 该班回到默认列表，`active=true` | 回得来 | — |
| **A10** | **真删护栏（有课节）**：教务删一个有课节的班 → **失败**，文案含"课节"人话 + 引导「停用」，**且 `op_batch` 行仍在** | 失败 + 数据未变 | ❌ 只看报错不看数据（"能走完"≠"没动数据"） |
| **A11** | **真删护栏（有学生）**：教务删一个"只有学生"的班 → **失败**（或按拍板给确认页），且学生 `batch_id` **未被清空** | 未清空 | ❌ 直接删完再数（事后发现） |
| **A12** | **真删逃生口**：教务删一个"零引用"的【演示】空班 → **成功** | 成功 | ❌ 不测（那就没有出口，"建错的班"永远留着） |
| **A13** | 学生 → `/my/contacts` → 学生组含同班同学 N 名，且 **N 与 `select count(*) from op_student_course where batch_id=<本班>` 一致**（去掉自己） | 数字相等 | ❌ 只断言"页面有内容" |
| **A14** | **越权反向断言**：学生 A 看不到**异班**学生（造一个异班【演示】学生，断言其姓名**不在** A 的页面） | 不出现 | ❌ 只测"看得到"（要**正对照**） |
| **A15** | 注册后置：与拍板一致 —— C1 则 `op_student_course` 新增 1 行；C2 则 `edu_pending_setup=True` 且 `course_detail_ids` 为空 | 与拍板一致 | ❌ 两个选项都断言 |
| **A16** | 清理：A3/A5/A12/A14 造的样本全部还原 → **`leftover = 0`**（同型先例：`checkin-merge-report` 三段模板） | 0 | ❌ 不还原就留样本 |
| **A17** | 计数前置（`dev-workflow.md:114-123`）：任何计数型判据前，先确认**最近没跑过 `-u edu_life`** | 已确认 | ❌ 直接对账 |

---

### 9.6 删除语义裁定：**只归档，还是保留真删？**（队长点名要裁定）

**现状（先说事实，不先说主张）**
- **教务今天就有 `unlink`**（真机 `True`，库内 `597|op.batch|经理|t|t|t|t`）⇒ 「删除」按钮/菜单**今天就在**（列表 ☰ → 删除）。
- 所以**"只允许归档、不提供真删"不是默认状态，而必须做一次变更**。

**三个可选做法（含代价）**

| 方案 | 做法 | 优点 | 代价 / 风险 |
|---|---|---|---|
| **(a) 覆写 `unlink()` 护栏（本文推荐）** | 照 `edu_portal/models/fees.py:128-138` 先例：**有引用就拒绝 + 人话文案 + 引导「停用」**；**零引用则放行**（给"建错的空班"留出口） | ① 在**模型层**生效 ⇒ 后台 / 脚本 / 导入 / 门户**全部**管住；② **不改基座 ACL**（保持"基座快照不改"红线）；③ 与 §11 的三档语义**天然对齐**、**可判定**；④ 本仓**两处同类先例**（`fees.py`、`downloads.py:44-55`） | 需写 1 个方法；文案要过汉化门禁（`check_english`） |
| **(b) 改 ACL 收回教务 `unlink`** | 覆写基座 `ir.model.access.csv` 的那一行 | 最彻底（连 API 调用都进不去） | ① 要**覆写基座 csv**（先删后建），违反"基座不改"的省事原则；② 后果是**谁都删不掉、包括以后的管理需求**；③ 与"校长说删除归教务老师"的**字面要求相冲**（教务将不再能删） |
| **(c) 只改 UI 藏掉「删除」** | 视图/菜单层面隐藏 | 零风险 | **最弱**：脚本/导入/XML-RPC 照样真删；本仓规范（`dev-workflow.md` 判据强度）明确反对"看起来拦住了" |

**裁定建议**：**采用 (a)**。理由一句话：**"护栏要挡的是后果，不是角色名"** —— 有引用 = 有后果 = 拦住；无引用 = 无后果 = 放行。这既满足校长"防止误删"，又**不制造"永远删不掉的空班"**。

**与"回收站"的关系（关键）**：**回收站（归档）是真删的替代主路径**，而不是它的补充：
- 想"清掉这个班但保留历史" → **归档**（零外键副作用，可一键恢复）；
- 想"删掉建错的空班" → **真删**（护栏放行）；
- 想"删掉有课节/有学生的班" → **护栏应当拒绝**，并引导到**归档**（因为真删会静默解绑学生，见 §11）。

---

## 10. 权限口径（四层，逐条声明"属于哪一层"）

> `code-map.md:256-263` 第 12 条硬约定：**新增菜单与 ACL 必须声明自己属于哪一层**。

| 落点 | 层 | 写法定式 | 为什么 |
|---|---|---|---|
| 批次菜单可见性（§9.3-1） | **教师 + 教务 + 超管** | `groups="openeducat_core.group_op_back_office_admin,base.group_system,openeducat_core.group_op_faculty"`（**并列**，教务与系统组保留最高权） | ① 基座 ACL 本就给教师 `create/write`；② 教务组**已 imply 教师组**（`group_tuning.xml:16`），并列不产生额外权；③ **不外扩到门户** |
| **归档 / 恢复** | **教务 + 超管**（默认） | 由菜单可见性带动（不写新 ACL：`active` 的写权就是 `write`，教师也有 —— ⚠ **见下方"陷阱"**） | 归档是**业务口径动作**（"这个班不再招生"），不是教学执行 |
| **真删** | **教务 + 超管**（校长更正） | 不改 ACL；由 `unlink()` 护栏控**后果** | 与基座 `op.session` 模式同构（§7-Q6 事实 3） |
| 学生分班入口（§9.3-5） | **教务**（默认）；**是否给教师 = 拍板项 P2** | 门禁用既有 `roles.privileged_staff()`（教务组或 system 组）或 `is_backoffice()` | `code-map.md:245`：门禁型管理页用 `privileged_staff()`；分班改的是**学籍归属** |
| 教师建/改班 | **教师** | 无需新语法（ACL 已在） | 教学执行侧；与 `op.session` 的 User 档同构 |
| 学生看同学（§9.3-8） | **门户**（`base.group_portal` + 身份函数分流） | `current_student()` / `current_parent()` 判空分流，**不做组判断** | 学生/家长无后台，走门户路由 + 数据域 |
| **红线复核** | — | 实施时**必须**断言「教务组 implied 传递闭包**不含** `base.group_system`」（`code-map.md:163` 判据） | 基座源码里它是 imply 的，本仓解除了；**改基座/重装可能回弹** |

> ⚠ **陷阱（必须写下来，否则实施时会踩）**：**`"归档"没有独立的 ACL，它用的就是 `write` 权限** —— 而教师**已经有 `write`**。
> 因此 **"归档归教务"这个口径在纯 ACL 层面是拦不住教师的**：只要把菜单开给教师（G2），教师**就能通过表单的归档/取消归档（或 XML-RPC）归档班级**。
> ⇒ 若要严格实现"归档也归教务"，**必须另加一层**（三选一）：
> ① **`ir.rule`**：非教务只读、只有教务可写 `active`（但 `ir.rule` 不能按字段区分，只能整体 write，会连带限制老师改班名）；
> ② **`write()` 覆写**：拦"非教务改 `active`"（精准，但又是一处护栏）；
> ③ **接受"教师可归档但不给真删"**（业务上可接受：归档可逆、零副作用、有确认弹窗与留痕入口）。
> **本文建议 ③**（最省、可逆、后果最小），并把**②作为 P1 的备选**。**这是拍板项 P1 的一部分。**

---

## 11. 删除班级的级联影响（**独立成节，因为这是最容易出事的一条**）

完整实测口径见 §7-Q5（21 条外键三档 + 机制源码 + 库内计数）。本节补**处置建议**与**归档对照**。

### 11.1 三档的人话翻译（建议直接用于护栏文案）

| 触发情形 | 今天的行为 | 建议文案（护栏） |
|---|---|---|
| 班上有**课节**（`op_session.batch_id`） | **报外键错误**（RESTRICT） | 「该班还有 **N** 节课节，不能删除。**请改用「停用」**：课表与历史保留，新分班不再出现该班。」 |
| 班上有**作业 / 考勤登记簿 / 考试安排** | **报外键错误**（RESTRICT） | 「该班还有 N 份作业 / N 本考勤登记簿 / N 个考试安排，不能删除。请改用「停用」。」 |
| 班上**只有学生**（`op_student_course`） | **静默成功，学生被解绑**（SET NULL） | 「删除后 **N 名学生将失去班级**（他们仍有课程与科目）。**建议改用「停用」**，可随时恢复。」 |
| 班上有**考试 / 点名表 / 费用明细 / 校历活动 / 停课日** | **静默清空班级**（SET NULL） | 「另有 N 条记录会失去班级归属（考试 N / 点名表 N / 费用明细 N …）。」 |
| 班上有 **QR 自助签到令牌** | **跟着删掉**（CASCADE） | 「该班 N 个自助签到码将失效。」 |
| **零引用** | 正常删除 | 放行（给"建错的空班"留出口），并写 `edu.audit.log` |

### 11.2 为什么建议"护栏 + 回收站"两条一起做

1. **今天删班的两种结局都是"用户不知道发生了什么"**：要么一句 `ForeignKeyViolation` 的英文报错，要么**静默解绑学生**。
2. **本仓对破坏性操作已有口径**：`code-map.md:245` 门禁型管理页；**`edu_portal/models/registration.py:161-171` 就是一次"校长裁定『拦住吧』"的先例**（防呆 + 人话文案 + 引导替代路径）；**`fees.py:128-138` 是"被引用则拒绝 + 引导停用"的现成代码形态** ⇒ **照抄即可**。
3. **`op.batch` 没有 `tracking` 字段**，chatter 不会自动记 ⇒ **不主动写 `edu.audit.log` 就等于零留痕**。

### 11.3 实测的边界（如实标注，不当结论用）

- RESTRICT / SET NULL / CASCADE 结论来自 **`pg_constraint.confdeltype` 实测**（21 条逐条列出）**+** Odoo 19 `fields_relational.py:270-282` 默认规则。**未**做"真的删一次班看报错文案"的端到端演练（会动库；本任务 doc-only）⇒ **报错文案的确切措辞属未验证**（§14-3）。
- **生产库未核对**：以上读数**只来自本地 `edu19`**（§14-1）。

### 11.4 归档 vs 真删 对照表（**给校长看的一页**）

| 影响面 | **真删（`unlink`）** | **归档 / 停用（`active=False`）** |
|---|---|---|
| 课节 / 作业 / 考勤登记簿 / 考试安排 | 🔴 删不掉（RESTRICT） | ✅ 一条都不动 |
| 学生分班（`op_student_course.batch_id`） | 🟡 **静默清空** —— 学生"没有班了" | ✅ 不变 |
| 选课注册单 / 考试 / 点名表 / 费用明细 / 校历活动 / 停课日 | 🟡 静默清空班级 | ✅ 不变 |
| QR 自助签到令牌 | 🔵 一起删掉 | ✅ 不变 |
| 学生门户能否看到"我的班" | ❌ 失去班级 | ✅ **仍能看到** |
| 新分班 / 选课下拉是否还能选它 | 不能 | 不能（`enroll.py:93-95` **已如此**）⇒ **正是"停止招生"语义** |
| 可逆 | ❌ **不可逆** | ✅ **一键恢复** |
| 谁能做 | 教务 + 超管（实测） | 见 §10 陷阱（默认教务+超管，但 ACL 层教师也可写 `active`） |

---

## 12. 学生查看班级 / 同班同学 / 老师的隐私口径（**必须写清，且列为拍板项**）

### 12.1 现状（先说清"今天能看到什么"）

| 对象 | 今天 | 证据 |
|---|---|---|
| 学生自己 → 自己的班名 / 课程 | ✅ 可见 | `batch2.py:1930-1931`、`batch1.py:320` |
| 学生自己 → 任课老师（含 email/phone） | ✅ **可见** | `study.py:122-131`；`contacts.py:75-80` + `:93-108`（**含 email / phone**） |
| 学生 → **其他学生** | ❌ **完全看不到任何人** | `contacts.py:75-80`：学生分支 `s_ids = {stu.id}` |
| 教师 → 本班学生/家长 | ✅ 可见 | `contacts.py:67-74`、`:110-138` |
| 家长 → **其他学生** | ❌ 看不到 | `contacts.py:81-88` |
| **谁看得到 `gr_no`（学号）** | 后台（`student_view.xml:11,40`）；门户通讯录条目里**没有** | `contacts.py:110-126` |
| **谁看得到头像** | `op.student` 继承 `res.partner`（kanban 用 `image_1920`/`avatar_128`，`student_view.xml:10,22-27`）；**门户通讯录不渲染头像** | `contacts.py:93-138` 条目里**没有** `image` |

### 12.2 三套候选口径（**必须校长选一套**）

| 口径 | 学生看到同学的什么 | 家长看到什么 | 优点 | 风险 / 代价 |
|---|---|---|---|---|
| **P-1 最小（推荐起步）** | **只显示姓名 + 班名**（**无学号、无头像、无 email、无 phone**） | **不开放** | 与"看见同班同学"字面一致；**不新增任何联系方式暴露**；实现最小 | 与 `/my/contacts` 现有条目字段形态不一致（需为该分支**单独裁剪字段**） |
| **P-2 中等** | 姓名 + 头像 + 班名（**仍无 email / phone / 学号**） | 不开放 | 有头像更像"认识同学" | **头像 = 个人影像**；本仓 `res.partner` 头像对门户是**新暴露面** |
| **P-3 对齐现有通讯录** | 姓名 + 课程/班名 + **email + phone**（照抄 `contacts.py:110-126`） | 不开放 | **代码最省** | ⚠ **把同学邮箱与手机号暴露给全班学生**；一旦放开**没有回头路**（学生可截屏） |

**本文建议**：**先落 P-1**，并在页面注明"可以在通讯录里找到同班同学"。若校长要 P-2/P-3，**另立任务**。

### 12.3 家长能否看到别人家孩子

**本文建议：不能**（保持现状）。理由：① 现状即如此（`contacts.py:81-88`）；② 校长原话只提「**学生**可以看见同班同学、老师」；③ 越过"熟人圈矩阵"（`contacts.py:4-13` 自述的四个角色分支）。⇒ **拍板项 P4**（默认：不做）。

### 12.4 实现口径（若落 P-1）

- 在**学生分支**（`contacts.py:75-80`）把 `s_ids` 从 `{stu.id}` 扩为「**本人 + 本人所在班（`op.student.course.batch_id`）的同学**」；教师分支 `:67-74` 是现成模板（口径必须一致）。
- ⚠ **两个必须处理的边界**：
  1. **合班语义**：本仓大量班级是**合班**（`B3+B4合班`、`A123+B34合班`…，§6）⇒ "同班同学"可能**跨年级**。建议：**凡 `batch_id` 相同即为同班**（与全线既有口径一致），页面文案写"同班"而非"同级"。
  2. **多班归属**：`op.student.course` 一课一行 ⇒ 一个学生可能属**多个班**；"同班同学" = **并集**（照 `study.py:30-40` 的 `mapped('batch_id')` 口径）。

---

## 13. 需要校长拍板的用户可见项（**6 项**）

| # | 拍板项 | 选项 | 本文建议 | 影响面 |
|---|---|---|---|---|
| **P1** | **「删除 / 归档」的层级与范围** | (a) 删除归**教务+超管**（校长更正，本设计默认）；教师只有**建/改/看**，**连归档也不行**；(b) 教师可**归档**（可逆、零副作用）但**不能真删**；(c) 教师连建/改都收回 | **(a)**，备选 (b) | ⚠ **注意 §10 的陷阱**：`"归档"用的就是 `write` 权限，教师本来就有** ⇒ 选 (a) 需要**额外一层**（`ir.rule` 或 `write()` 覆写）才能真的拦住；选 (b) 最省且后果可逆 |
| **P2** | **"在学生页面给学生分班"谁能做？** | (a) 只有教务；(b) 教务 + 教师 | **(a)** | 分班改的是**学籍归属**；本仓门禁型管理页既有口径是 `privileged_staff()` |
| **P3** | **同班同学页面，学生看到同学的哪些字段？** | (a) 只姓名 + 班名；(b) 加头像；(c) 加 email + phone | **(a)** | 个人信息暴露面；(c) **不可撤回** |
| **P4** | **家长能不能看到别人家孩子？** | (a) 不能（现状）；(b) 能 | **(a)** | 选 (b) 需重写熟人圈矩阵的家长分支 |
| **P5** | **"注册后进入班级"用哪种方式？** | (a) **注册期选班**；(b) **注册后置**（先「待分配」，教务一点就分）；(c) 两者都要 | **(b) 起步，随后 (a)** | 校长原话字面更像 (a)；但 (a) 让学生**自己选班**，与"教务分班"权责冲突（P2）。⚠ **(b) 依赖 G1（分班入口）先落地** |
| **P6** | **「删除」按钮该叫什么？（命名项）** | (a) **「停用 / 恢复」**（与本仓自研先例一致）；(b) **「归档 / 取消归档」**（与基座 Odoo 自带的 `Unarchive=取消归档` 一致）；(c) 保留「**删除**」字样但行为是归档（**不推荐**） | **(a)** | 证据：基座自己**不一致** —— `web/i18n/zh_CN.po:876-877` 把 `Archive` 译作**「存档」**、`:7204-7205` 把 `Unarchive` 译作**「取消归档」**；而本仓自研一律用**「停用 / 恢复」**（`fees.py:136`「请改为『停用』」、`downloads.py:214`「资料批量停用」/`:216`「资料批量恢复」、`downloads.py:1037`「在架 / 已停用」、`edu_nav` 全篇「停用」）。⚠ 选 (a) 需**覆盖基座译文**（`edu_zh`），选 (c) 会让用户以为"删了还能恢复" |

> **另有 1 项非"拍板"但需知会**：`help_center.xml:236` 现在对用户说「建班级…**选好学年/学期**」，而 `op.batch` **没有**这两个字段（`batch.py:30-36`）⇒ **既有文档错误**，建议顺手修正（不在 inScope，§14-4）。它还写着"**教务**后台"，若 P1/P2 决定给老师开入口，这句也要改。

---

## 14. 未验证 / 待确认清单（**不得当结论用**）

| # | 未验证项 | 为什么未验证 | 何时能验证 |
|---|---|---|---|
| **1** | **生产库**（马来西亚）的 `op_batch` / `op_session` / `op_student_course` 计数与分布 | 无授权、无窗口；本文读数**只来自本地 `edu19`** | 实施期，经批准后只读 SELECT |
| **2** | `op.batch` 的**字段级留痕**实际有没有生效 | 字段均**未声明 `tracking=True`**（`batch.py:30-36`）；**未实跑"改一个班名看 chatter"**（会写库） | 实施期真机改一次班名 → 查 `mail_tracking_value` |
| **3** | 删班的**确切报错文案**（RESTRICT 档） | 只做到"查外键规则 + 读 Odoo 默认策略源码"，**未真的删一次班**（会动库） | 实施期在**本地**用【演示】班演练 |
| **4** | `help_center.xml:236` 的"学年/学期"表述 | 已读出行号与文本，**未逐条核对**该页其它班级相关句 | 实施期一并复核 |
| **5** | 「同班同学」在**合班**场景下的产品语义是否被校方接受 | 需校长拍板（§12.4 延伸） | 拍板时 |
| **6** | `op.student.course` 的 3 条唯一约束（`student.py:43-51`）在**转班**写路径上会不会咬人 | 读到了约束定义，**未构造"同名 roll_number 跨班"样本**去试 | 实施期（若 G1 做转班） |
| **7** | 门户 `load_menus` 对 `stu`/`par` 返回 **403** 的文案（"不允许访问部门（hr.department）记录"）是否影响其它门户页 | 只观察到该 403，**未追查根因**（与本设计无关，属既有现象） | 另立任务 |
| **8** | 教师**只读**班级时的数据范围（能读到全部 17 个班）是否可接受 | `op.batch` 无 `ir.rule` ⇒ **技术上是全部**；**业务上是否可接受需确认** | 拍板期（可并入 P1/P2） |
| **9** | **归档后"学生仍能看到自己的班"**是否在所有入口都成立 | 已读源码判定：`study.py:30-40` / `batch1.py:320` / `batch2.py:1930-1931` 从 `op.student.course` 取 `batch_id`、**不过滤 `active`**；但**未逐页真机跑过"归档一个班后学生侧 5 个页面"** | 实施期按 §9.5 **A7** 实跑 |
| **10** | 取消归档**无确认弹窗**（`dynamic_list.js:228-230`）是否符合教务预期 | 源码事实已确认；**是否要自研确认弹窗属产品决策** | 拍板期（可并入 P6） |

---

## 15. 第 0 步：重复登记（台账）

本文按 `dev-workflow.md:54-55` 要求在 `docs/audit/deprecated-inventory.md` **追加一行**（**追加**，不覆盖历史行）：

- **重叠对象**：`op.batch`（基座班次实体，含内建 `active` 回收站）+ `op.student.course.batch_id`（学生归属）—— **本需求命中的"既有实现"不是重复物，而是承载物**。
- **证据**：模型 `op.batch`（`…/openeducat_core/models/batch.py:25-68`，`active` 在 `:36`）；归属字段 `…/models/student.py:34`；ACL `…/security/ir.model.access.csv:8-9`；菜单 **264**（组=经理，动作 386）；库内 17 班（**全部 `active=t`**）/ 288 节课节 / 12 注册单 / 5 作业全部挂 `batch_id`；`action_archive`/`action_unarchive` 在 `custom_addons/` **0 命中**。
- **裁定**：**复用**（不新建）。**替代路径 = 基座 `op.batch`（含 `active` 回收站）+ `op.student.course`**；扩展方式 = 菜单可见性一行 + 列表视图加 `active` 列 + `unlink()` 护栏 + 门户只读分支 + 注册后置动作。

---

## 16. 变更记录

| 日期 | 改动 | 责任 |
|---|---|---|
| 2026-09-18 | 建立本文（需求 7 / 班级管理）：第 0 步查重（§3）+ 第 3 步读参考（§7 Q1–Q7）+ 第 4 步设计摘要（§8–§13）。裁定 **复用**（**能，不必新建**）。**未写一行代码、未新建模块、未动 `openeducat_erp/` 与 `custom_addons/`、未改库**（全部读数为只读 SELECT / 只读 HTTP 探针 / 只读源码） | 设计子代理（C-2，`docs/plans/class-batch-management-design.md`） |
| 2026-09-18 | **并入校长更正**：① 删除班级归**教务老师**（非教师）——重写 §7-Q6 / §10，并给出"与基座 `op.session` User/Manager 模式同构"的实查证据；② **回收站**：核实 `op.batch.active`（`batch.py:36`）已在 ⇒ 裁定**复用基座归档**，新增 **§7-Q7** 专答"现有视图暴露了归档没有 / 缺口是什么"（结论：**表单可用、列表不可用；缺口 = 视图层 1–2 处，0 个新模型**）；③ 新增 **§9.6 删除语义裁定**（建议"有引用拒绝 + 无引用放行"的 `unlink()` 护栏，照 `fees.py:128-138` 先例）与 **§11.4 归档 vs 真删对照表**；④ 拍板项 5 → **6 项**（新增 P6 命名项） | 设计子代理（C-2） |
