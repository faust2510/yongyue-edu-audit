# 权限分层模型（四层）· 可执行规范
> **状态**：`已上线` ｜ **主题**：`权限四层规范` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> **读这一页就够知道「新人/新模块该挂哪一层」。**
> 背景：基座 `openeducat_core` 曾把「经理」（= 教务处）组定义成隐含 `base.group_system`，
> 于是「教务 = 系统管理员」，四层塌成两层 —— 2026-09-17 解除（commit `d2c41de`，解除处见
> `custom_addons/edu_portal/views/group_tuning.xml`，文件内注释写明「为何解除 / 故意不给什么」）。
> 本文件把这四层写成规矩，防复发。

**数字来源（一律带口径 + 时刻 + 库，禁止口口相传）**：
· 主来源 = `docs/plans/perm-split-audit.md`（t1 实测，采集 **2026-09-17 15:50–16:10**，库 `edu19`，本地克隆 `:8069`）；
· 复采 = 本文件作者在 **2026-09-17 16:41:11** 用 `python3 tests/smoke/backoffice_reachability.py --dump <json>`（**只读**）复跑，与主来源一致。

---

## 1. 四层定义（谁 / 用哪些组 / 能做什么 / 不能做什么 / 判据）

| 层 | 谁（本地账号） | 用哪些组 | 能做什么 | **不能做什么** | 判据（可核查） |
|---|---|---|---|---|---|
| **L1 开发者 / 系统管理员** | `admin`（超管） | `base.group_system` | 设置、应用、模块装卸、系统参数、数据清除；收口后 5 条管理面菜单**仍 5/5 可见** | ——（本层就是兜底） | 收口回归断言「超管仍可见 5/5」 |
| **L2 教务（学院领导）** | `backoffice@local`（uid 12）、生产 `jiaowu@local` | `openeducat_core.group_op_back_office_admin`（id 40，界面名「经理」）；**隐含** 教师组 + `base.group_partner_manager` + 考勤(user/manager) + 课表(user/manager) + 图书馆(user/manager) + 考试(user/admin)。**不隐含** `base.group_system` | 业务管理面全部可办：课程/科目/批次/课节、考试与成绩、课堂考勤、时间表与周期排课、图书馆、财务（总台账/账单/缴费/费用分类/报销审批）、公告、请假·申诉·选课·报名审批、资料下载管理、校历、打卡与积分、评教 | **进不了** 设置 / 应用 / 数据清除（菜单不显示）；**装卸不了**模块、**改不了**系统参数（`res.config.settings` 四项全 False）、**改不了** ACL/菜单（`ir.model.access` 读 False、`ir.ui.menu` 写 False）；**进不了教师门户页**（`/attendance/take` 等要 `op.faculty` 绑定 ⇒ 303 回 `/my/home`） | 有效组 **20**（SQL 闭包）、**不含** `base.group_system`；可见菜单 **179 节点 / 12 根**（口径 B）；`backoffice_reachability.py` exit 0 |
| **L3 教师** | `faculty@local` | `openeducat_core.group_op_faculty`（隐含 `base.group_user`） | 门户教师页：点名 `/attendance/take`、成绩录入、作业发布与批阅、请假审批、打卡统计、课表；后台只到「教学执行」面（可见根 **9 个**） | **不是管理员**：不属教务组、不含 `base.group_system`、可见根不含 设置/应用/数据清除；也**看不到**财务台账、审批台等教务面 | 可见节点 **75**（t1 §6.2，16:12 采集）、可见根 9（code-map §4.1，14:25 采集）；`privileged_staff()` 对教师为 False |
| **L4 学生 / 家长** | `stu@local`；家长 = `op.parent` 绑定用户 | `base.group_portal`（门户身份） | 只看自己（家长看绑定的孩子）：`/my/*`、`/student/*`、成绩/考勤/账单/资料/课表/请假/申诉/证书 | **进不了后台**（可见根 **0**）；**看不到别人的行** | 0 根菜单；数据隔离靠 `ir.rule`（`student_login_rule` 等）+ 控制器 `current_student()/current_parent()`（判空分流） |

> ⚠ **口径陷阱（引用数字前必读）**：菜单可见性有两种口径 ——
> **口径 A** `ir.ui.menu.with_user(u)._visible_menu_ids()` 与 **口径 B** `/web/webclient/load_menus`（前端真正建树）。
> **本仓一律用 B**；A 会把「父根不可见」的孤儿也算进来（实测教务 **199 vs 184**，差 15 条全是孤儿，偏高）。
> 口径 B 的调用细节：**GET**（POST 会 405）；响应是**扁平的数字键字典**，按 `result.root` 之类嵌套树解析会得 0。

---

## 2. 本轮实测基线（改前 / 改后，同一口径）

| 读数（口径 B = `/web/webclient/load_menus`） | 修复前（16:12） | 修复后（16:41 快照 · **历史**） | **现状（最终 · 17:03:38 重采）** | 出处 |
|---|---|---|---|---|
| 教务可见菜单节点 | 184 | 179 | **180** | t1 §8 ／ t3 16:41 ／ t3 17:03:38 重采 |
| 教务可见根 | 12 | 12 | **12** | 同上 |
| 「看得见点不开」（全量扫描） | 5 条 | 0 条 | **0 条** | t1 §8；t15 收口时门禁实跑 **PASS 91 / FAIL 0 / GAP 0**（其后两次改动分别只**增加**两条已验证可打开的入口、**减少** 238 一条） |
| 超管仍可见那 5 条收口菜单 | 5/5 | 5/5 | **5/5** | t1 §8（管理面没丢） |
| 教务有效组 / 含 `base.group_system` | 20 / False | 20 / False | **20 / False**（未重采：t13/t15 未改组） | t1 §7（SQL 传递闭包）／ 16:41 `--dump` |
| 教务可写模型 | 41/45 | 41/45 | **41/45**（未重采：t13/t15 未动 ACL） | t1 §8 ／ 16:41 `--dump`（45 个业务模型口径） |
| 教务可见根清单（12） | 图书馆、学生信息、招生、招聘管理、教务审批、时间表、灵命生活、综合评估、网站、财务管理、资产管理、资料下载 | 同左 | **同左**（17:03:38 重采逐项一致） | 16:41 ／ 17:03:38 `visible_roots` |

> 📌 **184 是「修复前」数，不得当现状引用**：差的 5 条正是 §4 修掉的那 5 条「看得见点不开」菜单。
> **数字演进（全部可复算；口径 B；库 `edu19`）**：教务 184（16:12 修复前）→ 179（16:41 快照）→ 181（16:44，t13 补回菜单 790/791 两条入口）→ **180（17:03:38，最终：再 −1 = t15 把 `网站/配置/应用(238)` 收成仅系统管理员）**；
> admin 358（16:12）→ **360（17:03:38）**；教师 **75（16:12 与 17:03:38 两次一致）**。

**三角色最终读数**（口径 B `/web/webclient/load_menus`；库 `edu19`；本地 `:8069`；**采集 2026-09-17 17:03:38**；采集时**无升级锁**）：

| 角色 | 可见节点 | 可见根 | `238` 子树可见节点 | 对照（早期快照） |
|---|---|---|---|---|
| `admin`（超管） | **360** | **14** | 1（238 本身） | 16:12 报告 358 |
| `backoffice@local`（教务） | **180** | **12** | **0** ✓（收窄生效） | 16:12 报告 184 / 16:41 复采 179 / 16:44 复采 181 |
| `faculty@local`（教师） | **75** | **9** | 0 | 与 16:12 报告一致 |

> 根清单（同一次采集）：admin 14 = 教务 12 + **设置 / 应用**（两个仅超管）；教务 12 = 图书馆、学生信息、招生、招聘管理、教务审批、时间表、灵命生活、综合评估、网站、财务管理、资产管理、资料下载；教师 9 = 教务 12 − 网站、财务管理、资料下载。admin 的「14 根」另与 code-map §4.1（14:25 采集，混档口径「1/15 仅超管」）一致。

**教务可写面的边界（ACL 读数，取自 `--dump` 的 acl 段）**：
· 全量可写（读/写/建/删 = T/T/T/T）：`op.student`、`op.faculty`、`op.course`、`op.batch`、`op.subject`、`op.session`、`op.exam`、`op.exam.attendees`、`op.result.line`、`op.attendance.register/sheet/line`、`op.media`、`op.library.card`、`edu.fee.*`、`edu.notice*`、`edu.leave`、`edu.grievance`、`edu.certificate`、`edu.invite.code`、`edu.point.log`、`edu.daily.checkin`、`edu.checkin.record`、`edu.event`、`edu.download.*`、`edu.grade.history`、`edu.asset*`、`edu.job.posting`、`edu.subject.prereq`；
· **建/删 = False（设计如此，不是缺陷）**：`edu.application`（报名单由公开报名表 `sudo` 建，教务只审）、`edu.apply.section`、`edu.eval.template/task/score`（防误删）、`edu.job.application`；
· **全 False**：`res.config.settings`（系统参数）、`ir.model.access`（读都 False ⇒ 读不到 ACL）、`ir.ui.menu` 写/建/删 False。

---

## 3. 结构性防复发规则（违反即返工）

· **R1 禁止「教务组隐含系统管理员」**：任何把 `base.group_system` 放进教务组 `implied_ids` 的写法都禁止（先例与理由见 `custom_addons/edu_portal/views/group_tuning.xml`）。判据 = 教务组 implied **传递闭包**不含 `base.group_system`（SQL 查 `res_groups_implied_rel`，不是只看一层）。
· **R2 禁止拿身份组当业务组补**：不许用「把 `base.group_system` / `base.group_user` 加回教务」的方式解决「点不开」。正确做法见 §4 —— 要么补**业务 ACL/组**，要么把菜单**收回**给真正需要的功能组 + 超管。
· **R3 新增菜单/ACL 必须声明所属层**：提交说明里写一行「本菜单属 L? 层」，并按 §5 清单落 groups=/ACL/ir.rule（code-map §6 第 12 条是同一条硬约定）。
· **R4 「看得见点不开」按三层判据判**：L1 菜单可见（`load_menus`）→ L2 动作可打开（`/web/action/load` + `get_views` + `search_read` + `check_access_rights`）→ L3 浏览器真渲染且**关键元素命中**。**只看 HTTP 200 不算通过**。

---

## 4. 「新增模块该挂哪一层」决策树 + 落地清单

**第 1 步：问「这件事是谁的业务」**

```
这件事是……
├─ 系统级（装模块 / 改系统参数 / 清理数据 / 站点设计器）      → L1：仅 base.group_system
├─ 学院管理（课程·科目·批次·课节 / 考勤 / 考试与成绩 / 财务 /
│   公告 / 审批 / 资料 / 校历 / 打卡积分 / 评教 / 图书馆）    → L2：教务组 + base.group_system（并列）
├─ 教学执行（点名 / 成绩录入 / 作业与评阅，且只限自己任教班级） → L3：教师组（+ 控制器 current_faculty()）
└─ 只看自己 / 看孩子                                        → L4：门户路由 + ir.rule（**不给后台菜单**）
```

**第 2 步：如果这个菜单是「别人的原生菜单」** —— 不要给教务补功能组，而是把菜单**收回到它真正需要的组 + 超管**，落地在 `custom_addons/edu_portal/models/menu_reachability.py` 的 `NARROW_RULES`（幂等、缺模块跳过、绝不让升级失败）。实测先例：分层后教务失去 `group_system`，`网站/活动`、`网站/配置/电子商务/付款方式`、`网站/技术/会话×3` 这 3 处 5 条原生菜单**看得见点不开**（症状是「点进去落到 `/apps` 应用面板」，不是报错）⇒ 收回 `event.group_event_manager` / `im_livechat.*` + 超管。

**第 3 步：按层落地「四件套」（缺一就会出现死角）**

| 要落的东西 | 写在哪 | L1 | L2（教务） | L3（教师） | L4（学生/家长） |
|---|---|---|---|---|---|
| 菜单可见性 | `views/*.xml` 的 `<menuitem groups="...">`（或 `ir.ui.menu` 收窄规则） | 仅 `base.group_system` | `openeducat_core.group_op_back_office_admin,base.group_system` | `openeducat_core.group_op_faculty` | **不给菜单** |
| 模型 ACL | `security/ir.model.access.csv`（**不能有 `#` 注释行**，Odoo CSV 加载器会 IndexError） | 视需要 | 教务组一行 | 教师组一行（如需） | 门户组（多半只给读） |
| 记录规则 | `<record model="ir.rule">` 的 `groups` + `domain_force` | —— | 教务组 | 教师组 | **必须有**（只看自己/看孩子） |
| 控制器判据 | `edu_portal/controllers/*` | —— | `roles.privileged_staff()`（教务组或 system） | `current_faculty()` + `op.faculty` 绑定 | `current_student()` / `current_parent()`，**判空分流、不做组判断** |
| 门户入口 | 卡片/导航（`/my/apps`、`_YONGYUE_CARDS`） | —— | —— | 教师页 | 学生/家长页（**按身份隐藏**，否则出现「点了回首页」） |

**反面例子（本轮实测踩过，别重演）**

| 写法 | 后果 |
|---|---|
| 菜单只写 `groups="base.group_system"` | **教务看不见**（分层后必现）—— 本轮在 7 处菜单上修过（`invite_code_views.xml:70,83`、`notice_admin.xml:83,142,200`、`welfare.xml:558,562`） |
| 菜单只写教务组、不并列系统组 | **管理员被挡在外面**（新模块最容易犯的一侧）；约定一律并列 |
| 给教务加隐含 `base.group_system`（或把系统组加回教务） | 四层塌成两层，本轮全部返工的根因 |
| 把教务塞进功能组（如 `im_livechat` 用户组）以「修好」点不开 | 真放宽：教务获得与身份无关的功能权限；正确做法是**收菜单** |
| 菜单可见但目标模型无 ACL / 视图组限制不符 | 「看得见点不开」，且**多半不报错**（客户端落到 `/apps`） |

---

## 5. 判据与复验命令（改完自己跑一遍）

```bash
# ① 可达性门禁（L1+L2+L3 + 3 条端到端 + 清场 + 红线 + 收口回归；exit 0 = 全绿）
python3 tests/smoke/backoffice_reachability.py
#   全量（教务可见的每条带动作菜单）：--all-menus       只取基线：--dump <json>
# ② 门户侧不被误伤（三角色关键页）
python3 tests/smoke/portal_regression_smoke.py
# ③ 静态面
python3 scripts/check_view_xpath.py          # 继承视图/导入序/边界常量（新增 _inherit 要按流程同步常量）
python3 scripts/check_manifest_tracking.py   # manifest 引用集 ⊆ git 跟踪集
python3 scripts/check_english.py             # 可见文案门禁（must-fix = 0）
```

**红线自查（改权限后必跑，SQL 口径，别用 ORM —— `has_group` 经 `call_kw` 会参数绑定失败、`ir.model.data` 对教务不可读）**：
· 教务有效组 **20**、**不含** `base.group_system`；
· 教务组 implied **闭包**不含 `base.group_system`；
· 教务仍持 5 个业务管理组：`group_op_faculty / group_op_attendance_manager / group_op_timetable_manager / group_op_library / group_op_exam_admin`。

---

## 6. 已知缺口（登记，不在本文件修）

| # | 事项 | 现状 | 影响 |
|---|---|---|---|
| F1 | `邀请码`（menu 542）对**所有人**不可见（`parent_id=NULL, active=f`） | 上一轮菜单收口只写 `active=False` 没写 `parent_id` ⇒ 没落进任何容器 | 注册流程依赖邀请码，但**没有入口发码**；分层那次给教务补的 ACL 与菜单 groups 目前是**惰性的** |
| F2 | `老账号补挂身份`（menu 606）同上 | 同批数据 | 教务无法自助把历史账号补挂到学生/教师/家长档案 |
| O1 | `网站` 根下的网站编辑器类客户端动作对教务可见 | **能开**（打开站点预览，不是故障），只是教务不需要 | 若要收，收进 `website.group_website_designer` |
| O4 | 门户卡片 `/subject/enroll`、`/my/reimburse/apply` 对教务「点了回首页」 | 身份门禁（要 `op.student` 绑定 / 教职工报销），**分层前后都如此** | 属门户卡片引擎：按身份隐藏卡片 |

> 【2026-09-17 16:47 实测更正 · **只改事实、数字待同步**】F1/F2 的**入口已由 t13 补回**
> （新增菜单记录 **790 邀请码 / 791 老账号补挂身份**，挂在 `261` 配置下；老记录 542/606 仍 `active=f`、未清理）：
> · **邀请码**：教务**已可办理** —— 菜单可见，且以教务身份 `edu.invite.code.search_read` **返回 3 行、无 AccessError**（分层时补的 ACL 已生效）；
> · **老账号补挂身份**：入口已恢复，**本地实例实测教务 `GET /edu/backend/relink_identity` = 200 且渲染出补挂表单**；守卫 `_allowed()` 已由 t13 从 `has_group('base.group_system')` 放宽为 `is_backoffice()`（工作区已落地、本地实例已生效）。**t13 尚未收口（未提交）⇒ 生产以 t13 的提交/部署为准**。
> ⇒ 上表的「不可见」是 **2026-09-17 16:10 之前**的状态；现状以本行为准。**菜单数字与三角色表已于 2026-09-17 17:03:38 重采并同步（见 §2）**：教务 **180 节点 / 12 根**、admin **360**、教师 **75** —— t13 与 t15 均已收口，此后无已知漂移源。

> 处置与影响面详见 `docs/plans/perm-split-audit.md` §6.2/§6.3 与 §11；本文件只保证**不再新增同类缺口**。

---

## 7. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-17 | 首版（t3）：四层定义 + 本轮基线（179/12 根、死角 5→0、有效组 20）+ 挂层决策树 + 四件套清单 + 已知缺口 |

_本文件由 docs-eng（t3）编写；数字全部来自 t1 实测与 16:41 只读复采，未做任何推测。_