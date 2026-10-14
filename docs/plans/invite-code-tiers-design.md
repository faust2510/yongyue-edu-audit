# 邀请码分层（层级码 / 绑人码）设计
> **状态**：`已上线` ｜ **主题**：`邀请码分层` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「本任务不写任何实现代码」，实际已于 `e2739ce` 交付（2026-09-26 核对发现）。正文未改动。

> 任务：**t6**（调研+设计）｜**本文件不写实现代码**，实施由队长另立任务。
> 调研依据（每条结论的来源）：[[docs/research/invite-code-tiers.md]](../research/invite-code-tiers.md)（含未验证清单）。
> 取证时间：2026-09-17，本机 docker 栈（`edu19`）+ 运行镜像 `odoo:19` 源码。文中所有「本机实测」均为只读 SELECT / HTTP GET。
> 关联：`docs/code-map.md` §4（edu_portal）、§6.3（权限铁律）、§4.1（菜单收口）；`custom_addons/edu_portal/views/group_tuning.xml`（四层权限分层）。

---

## 0. 结论速览（TL;DR）

1. **两种码并存，语义互斥**：绑人码（= 现状，码绑到某位学生/家长/教师的档案）+ 层级码（新，码只带层级、不绑人）。同一个码二者只能居其一（OR）。
2. **层级 → 组的映射是设计核心**：学生/家长 → `base.group_portal`（现状不变）；**教师 → `openeducat_core.group_op_faculty`（内部用户，会拿到后台 9 个根菜单）**；**教务 → `openeducat_core.group_op_back_office_admin`**。⚠ 核心约束：**同一用户不能同时在 portal 组与内部组**（`base/models/res_users.py:535-548`），注册写组必须二选一。
3. **档案缺口（本设计最大的业务取舍）**：推荐 **「层级码注册即成层 + 不做自助认领 + 由教务在补挂工具挂接」**（方案 1），并在注册后与门户显式提示「待认领」——**不推荐**注册时自助选「我是谁」（冒充面）——同类先例：校管家师生信家长端就是「先注册、后绑定学员」。
4. **教务层码仅超管可发 = 三层拦截**（§6）：① 视图/菜单层（表单只读 + 选项按组过滤）② `ir.rule` 记录规则（现状 **0 条**，教务可见全部码）③ **ORM 守卫（唯一不可绕过的闸，因为 `sudo()` 会绕过 ir.rule）**。
5. **码的三个属性**：文本可自定义（但必须**统一大写 + 数据层唯一约束**——现状 `code` 只有非唯一索引）、次数可配（现状硬编码单次）、有效期可设（现状已有 `expire_at`，默认 7 天）。
6. **列表精简**：`used_login`（注册邮箱）与 `created_by`（发放人）改为 `optional="hide"`——**字段保留、默认不显示**（校长指令）。
7. **⚠ 现况必须先解决**：**「邀请码」后台菜单（id 542）当前是 `active=false`，全角色不可见**（菜单收口时被停用，且未按计划重挂到 257 下）。**不恢复入口，本设计做完了校长也找不到地方生成码**（§2.6）。
   > 【2026-09-17 更正（t13）】**这条「必须先修」已修**：新增菜单记录 **790「邀请码」/ 791「老账号补挂身份」**（`active=t`，挂 `261` 配置下），教务实测可办理（见 §2.6 更正行的读数）。原文保留，供追溯。

---

## 1. 目标 / 非目标

**目标**
- 校长需求落地：生成 `teacher-123` 这样的码，别人凭码注册**即成为对应层级**的用户。
- 层级码与既有绑人码**共存**、语义不打架；发放权限与现有四层权限模型一致（教务=学院领导、开发者=系统管理）。
- 不新造“看得见点不开”的死角：层级码带来的**档案缺口**必须有闭环。

**非目标**
- ❌ 本任务不写任何实现代码（models / controllers / views / CSV 一律不动）。
- ❌ 不改基座（`openeducat_erp/`），不改四层权限分层的现有口径。
- ❌ 不引入新的 res.groups 自定义组（本仓铁律：不建自定义组，复用 base/openeducat 组）。
- ❌ 不做「注册时自助选身份 + 审批队列」的完整实现（作为备选方案记录在 §5.2，需队长/校长拍板）。

---

## 2. 现状（全部一手证据）

### 2.1 数据模型与生命周期（`edu.invite.code`）

| 现状 | 证据 |
|---|---|
| 字段：`code / note / identity(student,parent,faculty) / student_id / parent_id / faculty_id / state(unused,used) / created_by / used_by / used_login / used_on / expire_at` | `custom_addons/edu_portal/models/invite_code.py:21-45` |
| 码默认形态 `EDU-XXXXXX`，码表去掉易混字符（31 字符） | `invite_code.py:13,47-51` |
| **单次**：`state != 'unused'` 即拒；**过期**：`expire_at < now` 即拒（惰性判定，无 cron） | `invite_code.py:63-71` |
| 默认有效期 **7 天**（`expire_at` 为 required） | `invite_code.py:43-45` |
| 绑人码的“一人一挂”前置校验 + 注册后挂接（学生/家长写自身 `user_id`，教师写 `partner_id.user_id`） | `invite_code.py:84-124` |
| 消费：一次性写 `state/used_by/used_login/used_on` | `invite_code.py:126-130` |
| `code` 可自定义（create 只在空值时生成） | `invite_code.py:53-58` |
| **`code` 没有唯一约束**：本机实测 `pg_indexes` → 只有 `edu_invite_code__code_index`（普通索引，非唯一） | 本机只读 SQL：`select indexname from pg_indexes where tablename='edu_invite_code';` |
| 取值口径：`_order = 'create_date DESC'` ⇒ 若有同码两行，**最新那条生效** | `invite_code.py:19` + `controllers/register.py:51`（`search(..., limit=1)`） |

### 2.2 注册链路（`/register` 与兼容路径）

- 路由：`/register`、`/register/submit`（`controllers/main.py:236-249`，继承 `EduRegister`），`/web/register` → 302 到 `/register`（`main.py:251-259`）；实现体在 `controllers/register.py:33-112`。
- 表单字段：邀请码 / 姓名 / 邮箱（作为登录名）/ 密码 / 确认密码（`views/register.xml:20-56`）；**邀请码输入框带 `text-uppercase`**（`register.xml:29`）。
- 校验顺序：必填 → 邮箱格式 → 密码 ≥6 → 两次一致 → **码存在** → `_validate_view()`（未用/未过期）→ `_validate_identity()`（绑人码）→ 邮箱未被注册（`register.py:47-62`）。
- 建号：**只给 `base.group_portal`**（`register.py:68-79`）；绑人码路径复用人员已有 partner（`register.py:80-99`，注释里的 F1 讲清了「不许用注册输入覆盖档案姓名/邮箱」）；随后 `attach_identity()` + `consume()`（`register.py:100-102`），再自动登录跳 `/my/home`。

### 2.3 发放权限与可见性（**现状：教务全权，且无任何记录规则**）

| 层 | 现状 | 证据 |
|---|---|---|
| ACL | `base.group_system` 全权 **且** `openeducat_core.group_op_back_office_admin` 全权（读写建删） | `security/ir.model.access.csv:15,82` |
| 记录规则 | **0 条**（本机 `ir_rule` 实测，`edu.invite.code` 与 `edu.audit.log` 均无规则） | 本机 SQL |
| 菜单（源码口径） | 「邀请码」与「老账号补挂身份」都授权给 `backoffice + system` | `views/invite_code_views.xml:67-71,80-84` |
| 菜单（**库内实况**） | 两条都是 `active=false` ⇒ **当前全角色不可见** | §2.6 |
| 菜单（**2026-09-17 16:47 实况 · t13 修复后**） | 新增 **790「邀请码」/ 791「老账号补挂身份」**（`active=t`、挂 `261` 配置下）⇒ **教务可见且实测可办理**；旧记录 542/606 仍 `active=f`、`parent_id=NULL`（孤儿未清理，仅台账意义） | §2.6 更正行 / t13 |
| 全局搜索 | 有 `op.faculty` 档案的人（教师/教务）能在搜索里按码/备注查到，链接指向该 action | `controllers/search.py:156-173` |

**结论**：现状下教务**能看到超管发的教务码**（含未使用），并能改/删——这是本设计要修的第一件事（§6.3）。

### 2.4 列表界面现状（校长要精简的两列）

`views/invite_code_views.xml:8-22` 列表按序显示：`code / identity / student_id(optional hide) / parent_id(optional hide) / faculty_id(optional hide) / state / note / expire_at / used_login(注册邮箱) / used_on / created_by(发放人)`。
**结论**：邮件与发放人两列改为 `optional="hide"` 即可满足指令（字段保留、默认隐藏、用户可自行打开）——见 §8。

### 2.5 与权限分层的关系（四层模型）

- 基座把「经理」（=教务处）定义成 **隐含 `base.group_system`**：`openeducat_erp/openeducat_core/security/op_security.xml:45-51`。
- 本仓已解除该隐含（2026-09-17 校长裁定）：`custom_addons/edu_portal/views/group_tuning.xml:13-26` —— 教务仍保留 教师组 / 联系人管理 / 考勤(用户+管理) / 课表(用户+管理) / 图书馆(用户+馆员) / 考试(用户+管理)，**但不再自动获得系统管理员**。
- 因此四层 = **开发者 `base.group_system`｜教务 `group_op_back_office_admin`｜教师 `group_op_faculty`（隐含 `base.group_user`）｜学生·家长 `base.group_portal`**。
- 门户侧身份判据：`current_student/current_parent/current_faculty`（`controllers/roles.py:160-176`）、门禁 `privileged_staff()`（`roles.py:150-157` = 教务组或 system 组）。

### 2.6 ⚠ 现况缺陷：**邀请码后台入口当前是黑的**（必须先修）

> 【2026-09-17 更正（t13 已修复；本节其余文字是**修复前快照**，原文保留供追溯）】
> · **入口**：新增菜单记录 **790「邀请码」**（`ir.actions.act_window,687` → 模型 `edu.invite.code`）与 **791「老账号补挂身份」**（`ir.actions.act_url,745` → `/edu/backend/relink_identity`），`active=t`、挂在 `261` 配置下 ⇒ 教务 `load_menus` 可见；**旧记录 542/606 仍 `active=f`、`parent_id=NULL`**（孤儿未清理，属台账收尾项，不影响可用性）。
> · **守卫**：下面「另一条同样被停用的入口」那段里写的「控制器只放行 `base.group_system`」**已不成立** —— `EduIdentityRelink._allowed()` 已改为复用 `controllers/main.py` 的 `is_backoffice(user)`（= `base.group_system` 或 `openeducat_core.group_op_back_office_admin`）⇒ **教务 + 系统管理员**（`controllers/contacts.py`，t13 起）。
> · **实测**（本地库 `edu19`，2026-09-17 16:47；只做 GET、不碰写路径）：教务身份 `edu.invite.code.search_read` **返回 3 行、无 AccessError**；教务身份 `GET /edu/backend/relink_identity` = **200** 且渲染出补挂表单（用 `allow_redirects=False` 排除「旧守卫 303 跳 `/my/home`」这种假绿；admin 侧同为 200）。
> · ⇒ 本稿「入口缺失 / 必须先修」的表述已逐条更正（共 8 处）：§0 第 7 条、§2.3 表、**本节**（标题下这一段）、§5.2 方案 1 代价列、§5.3 第 1 条、§6.1 ①、§9 前的 §10「S4 / S5」两行、§10 末尾的顺序建议。未更正的**原文**一律保留在本行上下，供追溯。

| 证据 | 读数 |
|---|---|
| 库内菜单 | `ir_ui_menu id=542`（xmlid `edu_portal.menu_edu_invite_code_root`，名「邀请码」）→ **`active=f`**，`parent_id=NULL`，**257 学生信息下没有该子菜单** |
| 声明源 | `custom_addons/edu_nav/data/menu_consolidation_data.xml:2706-2713`：设置 `active=False`，注释写「合并：本根停用，子树迁往 邀请码(257)」 |
| 计划书 | `docs/audit/menu-consolidation/menu-consolidation-plan.json:204-209`：`{"id":542,"into":257,"name":"邀请码","note":"队长：移入 257 后其自带组限制（经理+管理员）保持不变，backoffice 仍可见"}` |
| 差异报告 | `docs/audit/menu-consolidation/diff-report.md:495`（`542｜邀请码｜启用开关｜true→false`）；同文件 64/88 行写「并入 学生信息(257) → 在其下继续可用」 |
| 弃用台账 | `docs/audit/deprecated-inventory.md:96`（`CM-542 … → 257 学生信息`） |

**事实**：计划书假设「542 有子树，停用父根后子树迁到 257」，但 542 在本库**没有子节点**，所以「停用根」的净效果 = **邀请码功能后台无入口**（连 admin 也看不到）。计划书里「backoffice 仍可见」与库内 `active=f` 相互矛盾。
**另一条同样被停用的入口**：`ir_ui_menu id=606`（老账号补挂身份，`menu_edu_relink_identity`）也是 `active=f`（`diff-report.md:533`），而它的控制器**只放行 `base.group_system`**（`controllers/contacts.py:210-211,219-220`）——即「菜单授权给教务、控制器只认超管」，属于本轮的「看得见点不开」同族问题（**登记给 t1/队长，本设计不修**）。
**可达的兜底**：全局搜索对有 `op.faculty` 档案的用户能命中邀请码并给出 `/odoo/action-<id>` 链接（`search.py:156-173`）——但这不能替代「校长/超管找得到入口」。

---

## 3. 概念：两种码

### 3.1 定义

| | **绑人码（现状，保留）** | **层级码（新增）** |
|---|---|---|
| 语义 | 「这张码是给**这个人**的」 | 「这张码是给**这个层级**的」 |
| 注册后 | 账号自动挂到该人员档案（`op.student/op.parent/op.faculty`） | 账号**只拿到层级权限**，**没有档案** |
| 谁用 | 已有档案的学生/家长/教师（本校在读、在职） | 新生源、新入职、外聘、临时协作等**还没有档案**的人 |
| 现状字段 | `identity + student_id/parent_id/faculty_id` | 新增 `tier` |

### 3.2 数据模型建议（实施时照此落地）

```
code_kind  : Selection([('person','绑人码'), ('tier','层级码')])  required, default 'person'
tier       : Selection([('student','学生'), ('parent','家长'),
                        ('faculty','教师'), ('backoffice','教务')])
tier 互斥  : tier 码 ⇒ identity / student_id / parent_id / faculty_id 必须为空
             person 码 ⇒ identity 必填，且对应人员字段必填（沿用现状校验）
```

- **新增而非改造**：现有 5 条历史码（本机 `edu_invite_code` 共 5 行）全部按 `code_kind='person'` 兼容，无需数据迁移。
- 互斥用 `@api.constrains` 强制（避免「既是教务层又绑到某学生」的口径冲突）。
- **不建议**把 `tier` 塞进现有 `identity`：`identity` 现有语义是「绑到哪类人员」，混用后 `_validate_identity()`/`attach_identity()` 的分支会变得难以判读（`invite_code.py:84-124`）。

---

## 4. 层级 ↔ 组 映射（设计核心）

### 4.1 映射表

| tier | 注册后写入的组（`group_ids`） | 实际拿到什么 | 是否内部用户 | 发放权限（§6） |
|---|---|---|---|---|
| `student` | `base.group_portal` | 门户学生视图（无档案 ⇒ 多数页面空转，见 §5.1） | 否 | **教务可发** |
| `parent` | `base.group_portal` | 门户家长视图（同上） | 否 | **教务可发** |
| `faculty` | `openeducat_core.group_op_faculty`（隐含 `base.group_user`） | 门户教师页 **＋ 后台 9 个根菜单**（faculty 口径，`code-map.md` §4.1） | **是** | **教务可发**（⚠ 高风险，见 §6.4） |
| `backoffice` | `openeducat_core.group_op_back_office_admin`（隐含 faculty + partner_manager + 考勤/课表/图书馆/考试管理组，**不隐含 group_system**） | 教务层：后台 12 个可见根 + 各业务管理权 | **是** | **仅超管可发** |

依据：`views/group_tuning.xml:13-26`（现行隐含清单）、`openeducat_erp/openeducat_core/security/op_security.xml:45-51`（基座原始定义，已被上面覆盖）、`code-map.md` §4.1（各角色后端可见根数，采集 2026-09-17）。

### 4.2 注册时怎么写组（**必须替换现状写法**）

- 现状：`user_vals['group_ids'] = [(6, 0, [portal.id])]`（`register.py:68-79`）——对 `student/parent` 继续成立。
- 教师/教务：`group_ids = [(6, 0, [faculty 或 backoffice 组])]`，**绝不能再叠加 `base.group_portal`**：`base/models/res_users.py:535-548` 的 `_check_disjoint_groups` 会直接抛 `ValidationError`（同一用户不能同时是 portal 与 internal）。
- `backoffice` 组是**多组隐含**（见上表），写入后建议在读侧核对 `res_groups_users_rel`，确认隐含组已展开。
- ⚠ **未验证（实施时第一件事）**：Odoo 19 在 `group_ids` 写入时对隐含组的展开与 portal 清理行为，必须在本地库上真跑一次注册并读 `res_groups_users_rel` 验证（调研文档 U9）。

### 4.3 注册后必须做的一件事：**留痕**

每次 `consume()` 都写一条 `edu.audit.log`（`invite_code.consume`：码、tier、发放人、注册登录名、时间）——理由与实现口径见 §9.2。

---

## 5. 层级码的关键后果：**注册后没有档案**（本设计最大的取舍）

### 5.1 后果清单（逐条带代码证据）

| # | 后果 | 证据 |
|---|---|---|
| C1 | 门户所有「需要学生档案」的页面直接空转：控制器 `if not student: return request.redirect('/my/home')` ⇒ 用户**点进去被弹回首页**，表现为「看得见点不开」 | `controllers/batch1.py:196-198`（同型分支遍布 batch1/2/3、assets、downloads、enroll，全仓 grep 命中 20+ 处） |
| C2 | 教师工作台的考勤/成绩/作业页面找不到 `op.faculty` 记录即不可用（`current_faculty()` 按 `user_id` 查 `op.faculty`，查不到即空记录集） | `controllers/roles.py:174-176`；`code-map.md` §6.3（「需要教师班级数据的页面仍要求 op.faculty 绑定」） |
| C3 | 家长端同理（`op.parent.user_id`） | `controllers/roles.py:160-162` |
| C4 | 层级码用户**不会**自动出现在通讯录/补挂列表的“已挂接”集合里，需要人工挂接 | `controllers/contacts.py:230-237`（已挂接集合的算法） |
| C5 | 教务层码不涉及“教务档案”实体，但**它给的是后台管理权**，风险是另一类（§6.4） | 本机 `res.groups` 读 + `group_tuning.xml` |

### 5.2 三个备选方案与取舍

| 方案 | 做法 | 优点 | 代价 / 风险 |
|---|---|---|---|
| **方案 1（推荐）** | **注册即成层，不提供自助认领**；注册成功后账号处于「待认领」，门户顶部与「我的资料」显示引导：请把邀请码交给教务/管理员补挂档案；教务在**后台补挂工具**里把账号挂到具体档案 | 零新审批队列；不引入冒充面（任何人拿到 `TEACHER-123` 也不能把自己挂到某位真教师名下）；与同类一致（校管家家长端「先注册后绑定」） | 需要一个**能用的**补挂入口（现状 606 菜单 `active=f` + 控制器仅超管 ⇒ **必须先修**，见 §2.6）；教务要动手 **【2026-09-17 更正（t13）】此代价已解除**：入口（新增菜单 791）与守卫（`_allowed()` → `is_backoffice`）均已就绪 |
| 方案 2 | 注册时**自助选「我是谁」**（按 tier 过滤候选档案），提交后进审批队列，教务通过才生效 | 用户自助感强；减少教务来回沟通 | ① 需新增审批模型/队列（本波工作量翻倍）② 冒充面：拿到教师码即可认领任意教师档案（要靠审批兜住，但审批人未必核对）③ 与现有「一人一挂」校验耦合更复杂 |
| 方案 3 | 取消层级码，只保留绑人码（即维持现状） | 最安全 | **满足不了校长需求**（新生源/新入职没有档案，就发不出码） |

### 5.3 推荐（含遗留风险）

**推荐方案 1**，并把「补挂」作为发布前置：
1. 本波实施任务必须同时解决「补挂工具对教务不可用」的问题——二选一（不许两头都不动）：
   - **A**：把 `/edu/backend/relink_identity` 的 `_allowed()` 从「仅 system」放宽到 `privileged_staff()` 口径（`roles.py:150-157`），并**只允许挂接 student/parent/faculty 三类**（教务不能靠它给自己人加系统管理员）；
   - **B**：把 606 菜单从教务组里摘掉，只留超管，教务走线下找超管。
   - 建议 **A**（教务本来就是“学院领导”，学生的档案挂接是它的本职；B 会让校长需求卡在超管一个人身上）。
   > 【2026-09-17 更正（t13）】**已按 A 落地**：`_allowed()` 改为复用 `main.is_backoffice()`（= system 组或教务组，与 A 的 `privileged_staff()` 同族口径），入口（菜单 791）同时恢复；实测教务 `GET /edu/backend/relink_identity` = **200**（读数见 §2.6 更正行）。上面「二选一、必须先修」的文字保留为当时的决策记录。
2. 门户「待认领」提示要有明确文案与去处（例如「请把您的邀请码/邮箱告知教务处，由教务为您挂接档案」），否则 C1 的“弹回首页”就是本波新造的「看得见点不开」。
3. **教师层码**建议在 UI 上写明「该码会开通后台账号」，并要求发放时填写备注（发给谁），便于事后追责。

---

## 6. 发放权限：教务层码**仅超管**可发（在哪一层拦截）

### 6.1 三层拦截（缺一层就漏）

| 层 | 做什么 | 为什么需要 |
|---|---|---|
| **① 视图/菜单层** | ① 表单里 `tier` 字段：选择项对非超管隐藏 `backoffice`（在 `fields.Selection` 的 selection 上按组过滤，或视图里对该选项做只读回显）；② 列表视图用 `decoration` 把教务层码标出来；③ **重新给「邀请码」做入口**（§2.6 的 542 现在是黑的）**【2026-09-17 更正（t13）】入口已恢复**（新增菜单 790，挂 261 配置下），此子项**已完成** | 防手滑、防误选；入口是功能能不能用的前提 |
| **② 记录规则（`ir.rule`）** | 新增一条规则挂在 `openeducat_core.group_op_back_office_admin`：`domain_force = [('tier','!=','backoffice')]`，`perm_read/perm_write/perm_create/perm_unlink` 全开；`base.group_system` **不建规则**（天然全可见） | 现状 **0 条规则**，教务对全表可见可改可删（`ir.model.access.csv:82` + 本机 `ir_rule` 0 行）；这条把「教务看得见超管发的教务码」堵上。Odoo 语义：同模型不同组的规则是 **OR**，全局规则才 AND ⇒ 超管若同时在两组，仍是全可见（符合预期）。**注意**：`ir.rule` 对 `create` 同样生效（新建记录的 domain 会被校验），所以教务**建不出** `tier='backoffice'` 的行 |
| **③ ORM 守卫（真闸）** | 在 `edu.invite.code` 的 `create()/write()` 里显式判断：`if 'backoffice' in tiers and not self.env.user.has_group('base.group_system'): raise AccessError`；`write()` 里还要拦「把既有非教务码改成教务码」与「改 `state` 作废超管发的码」 | **`sudo()` 会绕过 ir.rule**（本仓注册控制器就大量用 sudo，`register.py:50,60,89`），任何机器人/脚本/门户代码路径一旦用 sudo 就穿过 ②；而 `env.user.has_group(...)` 判的是**人不是权限**，sudo 下一样生效。另外 `ir.model.access` **无法表达字段级限制**（CSV 只有 read/write/create/unlink 四个开关），「教务能建码但只能建非教务码」只能靠 ②/③ |

### 6.2 为什么不能只用 ACL

`security/ir.model.access.csv` 只有 `perm_read/perm_write/perm_create/perm_unlink` 四个开关（`ir.model.access.csv:1` 表头），**不能按字段值分区**。所以「教务可以发学生/家长/教师码，但不能发教务码」这句话在 ACL 层**写不出来**，必须落到 `ir.rule`（记录级）+ ORM（不可绕过）。

### 6.3 可见性矩阵（目标态）

| 角色 | 看得到哪些码 | 能建哪些码 | 能作废哪些码 |
|---|---|---|---|
| 超管（`base.group_system`） | 全部 | 全部 4 个 tier + 绑人码 | 全部 |
| 教务（`group_op_back_office_admin`） | **非教务层级的码**（学生/家长/教师 + 绑人码） | 学生/家长/教师 + 绑人码 | 同上 |
| 教师 / 学生 / 家长 | 不可见（ACL 已不含 `base.group_user`/`group_portal`） | — | — |

> 可选加强（列入 §12 未决）：教务是否**只应看到自己发的码**（`create_uid = uid`）。建议**不要**这么做——教务之间需要互相顶班（某人休假时代发），只按“层级”分区已经够用。

### 6.4 教师层码的风险声明（必须写进发布说明）

- 教师层码 = **开通一个能进后台的内部账号**（faculty 口径后台可见 9 个根菜单，`code-map.md` §4.1）。
- 因此：教师层码建议 **`max_use=1` + 有效期 ≤ 7 天 + 备注必填（发给谁）**；如校长同意，**教师层码由教务发但必须同时指定 `op.faculty` 档案**（即退化为绑人码），把「纯层级教师码」留给「新教师尚未建档案」这一种场景。

---

## 7. 码的三个属性：文本 / 次数 / 有效期

### 7.1 文本自定义（校长的 `teacher-123`）

现状：`code` 本来就可自定义（`invite_code.py:53-58` 只在空值时生成），但**没有任何其它约束**。建议：

| 项 | 建议 | 理由 / 证据 |
|---|---|---|
| 大小写 | **存储与校验统一 `upper()`**（表单显示大写、比较大写） | 注册页输入框已是 `text-uppercase`（`register.xml:29`），但 CSS 只改显示；校验是精确 `=`（`register.py:51`）⇒ 小写码 + 用户手动输入会得到「邀请码无效」，是一类可避免的工单 |
| 字符集 | 允许 `A-Z0-9-_`，长度 **4–64**；禁用空白与中文 | 现状随机码用去易混字符表（`invite_code.py:13`）；自定义不应比随机码更弱 |
| 强度下限 | 自定义码**不得**是纯数字、纯连续（`123456`），长度 ≥6（与 `teacher-123` 同级） | Moodle 把组码纳入站点密码策略（`public/group/group_form.php:200-205`）——同类先例 |
| **唯一性** | **必须加数据层唯一约束**（`_sql_constraints UNIQUE(code)`） | 本机实测只有**非唯一**索引 `edu_invite_code__code_index`；而注册按 `_order='create_date DESC'` 取最新（`invite_code.py:19` + `register.py:51`）⇒ 两条同码不同层级时，**谁后建谁生效**，这是安全缺陷不是优雅问题 |

### 7.2 次数（单次 / 多次）

- 现状：**硬编码单次**（`state` 只有 `unused/used`，`_validate_view()` 见 `invite_code.py:35-37,67-68`）。
- 建议：新增 `max_use`（默认 **1**）+ `used_count`；校验改判 `used_count < max_use`；`used_by/used_login/used_on` 保留首个使用者，其余每次消费写 `edu.audit.log`（或加 `edu.invite.redemption` 子表，二选一）。
- **风险闸**：多次码 × 层级码 = **可传播的权限凭证**。建议：`tier='faculty'|'backoffice'` 的码 **`max_use` 固定为 1**（UI 上禁用该字段）；学生/家长层级码可放宽到 N（建议 ≤ 20）且**必须设有效期**。（同类可多人复用：Moodle 组码、Canvas join code；我们的默认更严。）

### 7.3 有效期

- 现状：`expire_at` **required**，默认 `now + 7 天`（`invite_code.py:43-45`），过期判定惰性、无 cron。
- 建议：
  1. 表单提供「有效期（天）」快捷项 + 「不限期」选项（内部写 `2099-12-31` 或新增 `no_expiry` 布尔，避免手工改库造出 `2020-01-01` 那种怪值——本机库里现存一条 `EDU-D7RBRE` 就是手工造的过期码）；
  2. **教师/教务层码默认 ≤ 48 小时**（配合「发了就要用掉」），学生/家长默认 7 天；
  3. 列表加「过期」筛选/装饰，并对过期未用的码给「续期」按钮（重发语义参考 Odoo portal wizard 的 `action_invite_again`，`portal_wizard.py:189-200`）。

---

## 8. 列表界面精简（校长指令）

- **动作**：`views/invite_code_views.xml:19`（`used_login`）与 `:21`（`created_by`）加 `optional="hide"`——**字段保留、默认隐藏**，用户可在列设置里打开。
- 同批建议（一并做，成本近零）：
  - `tier`/`identity` 合并成「类型」列（层级码显示层级，绑人码显示身份）；
  - `state` 加 `decoration-warning="state == 'revoked'"`（配合 §9.1 的新状态）；
  - `max_use/used_count` 只在 `max_use > 1` 时显示（`optional="hide"`）。
- **不改**：`used_on`（使用时间）保留可见——它是追责的主要抓手。

---

## 9. 安全：作废 / 留痕 / 防滥用

### 9.1 作废

- 现状：**没有作废**，只能靠「改 `expire_at` 到过去」或删记录（教务有 `unlink` 权限，`ir.model.access.csv:82`）。
- 建议：`state` 增加 `revoked`（+ `revoked_by / revoked_on / revoke_reason`）；`_validate_view()` 增加分支并给出人话（「该邀请码已作废」）。
- **边界必须写明**：作废**只挡未注册的人**，**不会回收已经注册成功的账号**（账号回收是另一件事：`res.users` 停用/归档）。发布说明里要写清，避免校长以为「作废=撤销权限」。
- 作废同样受 §6.1 ③ 的 ORM 守卫：**教务不得作废超管发的教务码**。

### 9.2 留痕（复用 `edu.audit.log`，不新造模型）

- 现成设施：`edu.audit.log`（`models/audit.py:15-41`，`_log()` 失败只告警不阻断业务），读写 ACL：system + backoffice（`ir.model.access.csv:78-79`），查询页 `/edu/audit`（仅教务与管理员，见 `audit.py:5-6` 注释）。
- 建议记三类事件：

  | action | 触发点 | detail 建议 |
  |---|---|---|
  | `invite_code.create` | 后台建码 | `code=<码>; kind=<tier/person>; tier/identity=<值>; max_use=<n>; expire_at=<ts>` |
  | `invite_code.revoke` | 作废 | `code=<码>; reason=<文本>` |
  | `invite_code.consume` | 注册成功消费 | `code=<码>; tier=<值>; login=<注册邮箱>; user_id=<新账号 id>` |

- 现状**没有任何留痕**：码被谁改了、被谁删了、谁用什么邮箱注册的（除 `used_*` 三个字段外）都查不到。

### 9.3 防滥用

| 面 | 现状 | 建议 |
|---|---|---|
| **谁能看到谁的码** | 教务对全表可见可改可删（ACL 82 + 0 条规则） | §6.1 ② 的 `ir.rule`（教务只见非教务层级） |
| 码空间与枚举 | 随机码 = 31 字符 × 6 位（`invite_code.py:13,50`）≈ 8.9e8，人工枚举不现实；**但自定义码（`teacher-123`）会把这个强度打没** | §7.1 的强度下限；**不建议本波加限流**（列入 §12 未决） |
| 注册接口爆破 | `/register/submit` 对错码立即回显「邀请码无效」（`register.py:52-54`），**无失败计数/限流/验证码** | 列入 §12：是否加「同 IP 失败 N 次后延迟」；低优先，因为码空间足够大且错误信息不泄露“部分匹配” |
| 重复注册 | 邮箱已存在即拒（`register.py:60-62`） | 保持；这天然保证「同一邮箱不能叠两个层级码」 |
| 码转发 | 单次 + 有效期已覆盖大部分 | 教师/教务层码：`max_use=1` + 短有效期 + 备注必填（§6.4） |
| 过期码堆积 | 无 cron、无筛选 | §7.3 的筛选 + 续期 |
| 与原生注册的关系 | `website.auth_signup_uninvited='b2b'` 挡住了 `/web/signup`（本机 404） | **列入巡检**：这个字段一旦被改成 `b2c`，任何人都能自助注册门户账号，**绕过邀请码**（调研 §1.2） |

---

## 10. 实施拆分建议（供队长立任务，本任务**不实施**）

| 切片 | 内容 | 依赖 | 建议验收断言 |
|---|---|---|---|
| S1 模型层 | `code_kind/tier/max_use/used_count/state(revoked)` + 互斥 constrains + `UNIQUE(code)` + 大写归一 | 无 | 同码建两次必须报唯一约束错；`tier` 码带 `identity` 必报错 |
| S2 发放权限 | §6.1 的三层拦截（视图过滤 + ir.rule + ORM 守卫） | S1 | 教务建 `tier='backoffice'` **必失败**；教务读不到超管发的教务码（`search` 空集） |
| S3 注册链路 | `tier` 码按 §4 写组；`consume` 留痕；门户「待认领」提示 | S1 | 4 个 tier 各注册一次，读 `res_groups_users_rel` 与后台可见根菜单数（faculty 9 / backoffice 12） |
| S4 入口与界面 | 恢复/新建「邀请码」后台入口（§2.6）+ 列表 `optional="hide"`（§8）+ 作废动作与留痕（§9.1/9.2）**【2026-09-17 更正（t13）】「入口」子项已完成**（菜单 790/791）；列表精简与作废留痕仍未做 | S1 | 超管能从后台菜单直达邀请码列表；作废后该码注册被拒且账号不受影响 |
| S5 补挂闭环 | §5.3 的 A/B 二选一（建议 A）**【2026-09-17 更正（t13）】已按 A 落地**（见 §5.3 更正行） | — | 教务能挂接 student/parent/faculty；挂接后该账号的门户页面不再空转 |

> 建议顺序：**S4 的入口修复先做**（否则 S1–S3 做完也没人能验证）。
>
> 【2026-09-17 更正（t13）】入口子项已完成（菜单 790/791），**S1–S3 的验证前置已具备**。

---

## 11. 验收口径（建议）

1. **层级正确性**：4 个 tier 各发 1 码 → 各注册 1 个账号 → 逐条读 `res_groups_users_rel`，与 §4.1 表一致（并复跑后台可见根菜单计数：faculty=9、backoffice=12，口径见 `code-map.md` §4.1 与 `tests/audit/verify_consolidation.py`）。
2. **权限正确性**：教务账号建 `tier='backoffice'` 的码 → **必须失败**（AccessError / 403 均可，但要有明确提示）；教务账号 `search` 邀请码 → **看不到**教务层级的码。
3. **不误伤**：现有 5 条历史码全部仍可用（`code_kind='person'` 兼容），`/register` 五个字段的老流程不回归。
4. **无新死角**：层级码注册出的账号，在门户**每个**要求档案的页面都应看到「待认领」提示而不是静默弹回首页（抽查 batch1/2/3 各 1 个页面）。
5. **留痕**：`/edu/audit` 能查到 `invite_code.create/revoke/consume` 三类事件。
6. **回归门禁**：`python3 scripts/check_english.py`（若动用户可见文案）、`check_view_xpath.py`、`check_qweb_dict_foreach.py` 全绿；升级走 `bash scripts/safe_upgrade.sh edu_portal`。

---

## 12. 未决问题（需校长/队长拍板，本设计不自行裁定）

| # | 问题 | 建议默认 |
|---|---|---|
| Q1 | 教师层码由教务发，是否强制「必须同时选 `op.faculty` 档案」？ | 建议**不强制**，但 UI 明确写「该码会开通后台账号」并要求备注 |
| Q2 | 教务层码是否也允许「绑人」（超管给某位新教务发一个码，注册即挂到预建账号）？ | 建议**允许**——超管发码本来就该一次到位 |
| Q3 | 层级码是否允许 `max_use > 1`？ | 建议学生/家长可（≤20），教师/教务**锁死 1** |
| Q4 | 教务是否只应看到**自己发**的码？ | 建议**否**（教务间需互相顶班），只按层级分区 |
| Q5 | 是否为 `/register/submit` 加限流/验证码？ | 建议**本波不做**，先靠码空间与自定义码强度下限 |
| Q6 | 补挂闭环走 A（放开教务）还是 B（只留超管）？ | 建议 **A**（§5.3） |
| Q7 | 生产 `auth_signup` 安装状态与 `website.auth_signup_uninvited` 取值（调研 U1/U2/U10） | 建议**上生产前必查**，属发布前置 |
