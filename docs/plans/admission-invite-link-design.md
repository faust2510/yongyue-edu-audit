# 录取后发放入学码（「已录取」→ 他能登录）设计
> **状态**：`已上线` ｜ **主题**：`录取后发放入学码` ｜ **取代**：`—` ｜ **核对**：`2026-10-14`

> 任务：**C-3**（第 0 步查重 + 第 3 步读参考 + 第 4 步设计摘要）｜**本文件不写实现代码**，实施由队长另立任务。
> 取证时间：2026-09-18，本机 docker 栈（`edu19`，Odoo 19 + OpenEduCat 19.0 快照）。所有 DB 读数 = **只读 SELECT**；所有 HTTP 探测 = 只读；**未碰生产、未碰 custom_addons/、未碰 openeducat_erp/ 的任何一行**。
> 关联：`docs/code-map.md` §4（edu_apply / edu_portal / edu_tg_bind）、§5（路由速查）、§6（约定与铁律，尤其第 12 条权限四层）；`docs/dev-workflow.md` 第 0 步与六步闸门；`docs/research/invite-code-tiers.md`（本设计的调研依据）。
> 红线：`/Users/qwe/odoo-enterprise-ref/README.md`（企业版源码不进仓、只读不搬）；生产**匿名意见箱**（`edu_telegram`）数据一行不碰（`docs/audit/deprecated-inventory.md` §0.1）。

---

## 0. 结论速览（TL;DR）

| 项 | 结论 |
|---|---|
| **校长的问题** | 「假如有通过网页报名的，我怎么给他们对接下去呢？」——现状是**四步全人工**（建 `op.student` → 建 `op.student.course` → 分班 → 生成码 → 发码 → 他去 `/register`），**从「已录取」到「他能登录」之间没有任何连线**（§3 实跑证据）。 |
| **本设计做什么** | 在 `edu.application` 表单上，给状态 `admitted` 加一个按钮：**生成一张学生层级邀请码 → 绑定到这条申请 → 邮件发给申请人 → 他凭码 `/register` 即成为学生**。教务只剩「点一下」。 |
| **载体裁定（§8）** | **复用**（不新建码表、不新建池、不新增模型/路由/ACL/菜单）+ **一处最小模块级新建**：新增薄模块 `edu_admit_invite`（depends: edu_portal）承载 2 个 _inherit 方法 + 1 个继承视图。落点**不选 edu_portal**：edu_portal 依赖 edu_apply（`__manifest__.py:29`）⇒ 字段方向被锁死（§8.3），且 `-u edu_portal` 会触发**未关闭的 F1 菜单重放**。 |
| **唯一 schema 变更（§8.3）** | **只加 1 列**：`edu.invite.code.application_id`（m2o `edu.application`，ondelete='restrict'）+ **unique (application_id)**。发放时间/发放人/是否已注册**全部复用码行既有字段**（create_date / created_by / used_by / used_login / used_on / state）⇒ **不需要 issued_at / issued_by / issued_invite_code_id**。 |
| **码池结论（§9.1）** | **不与 edu_tg_bind 共用池，也不另立池——本渠道「点一次、生成一张」（按需生成）**。共用池有两个后果：① 一边抽干另一边（空池不会自动补货）；② **同一张码会被两个渠道各发一次**——TG 的池判据（`tg_claim.py:48-57`）只看 `edu_tg_claim`，看不见网页侧发出的码，而网页发出的码在注册前仍满足 TG 池的**全部**条件。要共用就必须改 edu_tg_bind 的 SQL（跨模块）；不改就不能共用。 |
| **无邮箱兜底（§9.3）** | `edu.application.email` **非必填**（`application.py:41`；库内 6 条申请**只有 1 条**有邮箱）⇒ **邮件只能覆盖少数人**。结论：**主渠道 = 邮件（有邮箱才发）+ 永远在线的兜底 = 页面回显码**（码常驻显示在申请表单上，教务自己电话/微信转告）。短信**现在发不了**（sms 已装但 sms_twilio 未装 = 无服务商）。 |
| **安全口径（§10）** | 有效期默认 14 天可配；一码一人 = use_limit=1 + _validate_view()（**并如实标注：消费侧无行锁，并发注册的理论窗口未实测**）；明文邮件的风险与缓解逐条列出；误发错误邮箱 = **对方就是学生了**（不校验收件人），撤销 = 把 expire_at 改到过去（**不需要新状态**），边界是**作废不回收已注册账号**。 |
| **待校长拍板** | **6 项**（按钮名 / 邮件标题正文 / 有效期 / 到期是否自动重发 / 无邮箱是否允许发放 / 是否加「注册邮箱不符」告警），见 §14。 |
| **零新增** | **不新增模型、不新增表、不新增模块级 ACL、不新增菜单、不新增路由、不新增演示数据**（§5/§6/§12）。 |

---

## 1. 目标 / 非目标

### 1.1 目标（逐条可验）

| # | 能力 | 用户感受 |
|---|---|---|
| **G1** | 教务在「已录取」的申请上**点一下**，系统生成一张学生层级邀请码并绑定到这条申请 | 不用再去「邀请码」菜单手工建码 |
| **G2** | 申请人**留了邮箱**时，自动把码发到他邮箱 | 不用教务手抄、手发 |
| **G3** | 申请人**没留邮箱**时，码**显示在教务眼前**，可自行电话/微信转告 | 不会出现「按钮点了没反应」 |
| **G4** | 重复点按钮**回显原码**，不再发第二张（**数据库级**，不是 if 判断） | 手抖点两次不会多废一张码、不会多发一封信 |
| **G5** | 申请人凭码 `/register` 注册后，教务在**同一条申请**上看到「已注册 + 注册邮箱 + 注册时刻」 | 「对接下去」有闭环、可追 |
| **G6** | 教务能**作废并重发**（对方没收到邮件 / 发错了邮箱） | 有纠错通道 |

### 1.2 非目标（明确不做，避免范围漂移）

- ❌ **不建学生档案、不分班**：层级码注册后由既有 `create_pending_archive()` 自动建【待分配】档案（`invite_code.py:337-390`），**分班是 C-2 的地盘**（`docs/plans/class-batch-management-design.md` §13 **P5**：先注册后置待办、教务去分）。
- ❌ **不发短信**：本机 sms 已装、sms_twilio **未装** ⇒ 无服务商（§9.3）。
- ❌ **不做「申请人自助查码」公开页**：需要额外凭据（手机号后四位之类）+ 防枚举，是**新攻击面**，本轮不划算。
- ❌ **不做自动续期 / cron 补发**：码池式惰性判定已在（无 cron），本渠道同理；过期由教务点「重新发放」。
- ❌ **不改 edu_portal / edu_apply / edu_tg_bind 的任何一行**（理由见 §8.2）。
- ❌ **不做录取通知书 PDF、不做身份校验**（与 TG 机器人同期口径：本轮「领取即发」，见 `docs/plans/tg-invite-bot-design.md` §12）。
- ❌ **不动基座 openeducat_erp/**（只读快照）。
- ❌ **不动生产 edu_telegram 匿名意见箱**（红线）。

---

## 2. 第 0 步①：先信 code-map

`docs/code-map.md` 逐条读后与本设计相关的锚点：

| 位置 | 内容 | 对本设计的含义 |
|---|---|---|
| `code-map.md:88-89` | edu_apply = `/apply` 公开报名表（元数据驱动，九区 30 字段，answer_json + 冗余检索列） | 本设计的**申请侧载体**；申请实体列 = 姓名/电话/**邮箱**/教会/身份证/科别 |
| `code-map.md:72,116-122` | edu_portal 的 `/web/register`（EduInviteCode 邀请码）；edu_tg_bind = TG 发码机器人（一 TG 账号一张，唯一约束不是 if 判断） | 本设计的**码侧**与**消费侧**；edu_tg_bind 的并发/幂等口径是**照抄对象** |
| `code-map.md:130-141` | 依赖关系：edu_tg_bind → edu_portal；edu_apply → website, mail | ⚠ **关键约束**：edu_portal 依赖 edu_apply（`edu_portal/__manifest__.py:29`）⇒ **edu_apply 不能反向依赖邀请码**（§8.3） |
| `code-map.md:231` | 路由：`/apply`、`/apply/submit`（edu_apply/main.py）；`/register`（v3 别名） | 申请人用的是**既有** `/register`，本设计**不开公开路由** |
| `code-map.md:249` | 「新功能三件套：先写 docs/plans/〈功能〉-design.md 再动工」 | 本文件即那个前置件 |
| `code-map.md:256-263` | 权限四层硬约定：教务写 groups="openeducat_core.group_op_back_office_admin,base.group_system" 并列；**「看得见点不开」缺一即死角**；菜单可见性口径一律用**口径 B** | 按钮必须**声明属于哪一层**并做**双层门禁**（视图 groups + ORM 判据） |
| `code-map.md:262` | `tests/smoke/backoffice_reachability.py` 已有「招生 / 入学申请」这一行断言（:75） | 验收可直接扩展这套工具，不另造 |

---

## 3. 第 0 步②：既有实现对照（命令 + 命中行号 + 为什么不复用）

> 规矩（`dev-workflow.md:18-32`）：**「没找到」也要写清搜索范围与方式**；**不允许"我记得没有"**。
> 本节命令**全部在本工作区实跑**（2026-09-18），DB 读数**只读 SELECT**。

### 3.1 七路查重表

| # | 查了什么 | 命令（原样可复现） | 命中 | 为什么不复用 / 结论 |
|---|---|---|---|---|
| 1 | **edu_apply 模块内**有没有「录取后发码/建档」 | grep -rniE "invite_code｜注册码｜入学码｜发码｜create_student｜op.student｜.tg.claim｜approve｜admitted" custom_addons/edu_apply/ | 只有 2 行**状态机字样**：`models/application.py:59`（('admitted','已录取')）、`views/backend_views.xml:27`（statusbar）；**其余 0 命中** | ✅ 证实「断点」：edu_apply 里**没有**任何发码/建档/通知申请人的逻辑（_notify 只通知**招生邮箱**，见 #5） |
| 2 | **全仓**谁引用 edu.application | grep -rniE "edu.application｜edu_apply" --include="*.py" custom_addons/ ｜ grep -v "^custom_addons/edu_apply/" | 只命中 3 类：`edu_portal/__manifest__.py:29`（依赖）、`edu_portal/models/registration.py:395`（**同名的 edu_apply_marks 成绩方法，与报名无关**）、`tests/smoke/backoffice_reachability.py`（可达性断言） | ✅ **全仓没有任何"申请 → 码/账号"的连线** |
| 3 | 全仓搜「入学码/录取码/发放入学/邀请链接」等**功能名** | grep -rniE "入学码｜录取码｜admission_code｜invite_link｜issue_invite｜grant_invite｜send_invite｜发放入学" --include="*.py" --include="*.xml" custom_addons/ docs/ scripts/ | **0 命中** | ✅ 命名空间干净 |
| 4 | **基座 openeducat_admission 有没有「录取 → 建档」** | 读 `openeducat_erp/openeducat_admission/models/admission.py`；grep -rn "enroll_student｜get_student_vals" openeducat_erp/openeducat_admission/ | ⚠ **命中，而且是"几乎同名同位置"的一个**：状态机 `:77-82`（含 'admission','Admission Confirm'）、student_id `:96-97`、**get_student_vals() `:245-301`**（`:250-260` 建 res.users 只给 base.group_portal；`:284-296` 同时建 op.student.course（**含 batch_id**））、**enroll_student() `:303-387`**（`:316-317` 建 op.student、`:379-387` 建 op.subject.registration、`:334-371` 写学费明细）；视图按钮 `views/admission_view.xml:51-52`（invisible="state != 'admission'"） | ❌ **不复用其写路径**，四条理由见 §3.2；✅ **只抄它的字段映射口径**（见 §7-Q5） |
| 5 | 通知书/邮件出口 | grep -rniE "mail.template｜mail.mail｜send_mail｜message_post" custom_addons/edu_apply/ custom_addons/edu_portal/ | `edu_apply/controllers/main.py:111-115`（mail.mail create + send(raise_exception=False)）；`edu_portal/models/notice.py:152`（公告邮件） | ✅ **出口形态可照抄**；但 _notify 发给的是**招生邮箱**（`:96-99`：参数 edu.apply_notify_email → 兜底 res.company.email），**不是申请人** ⇒ 本设计新增的是"发给申请人"这一条 |
| 6 | edu.application 上有没有**自动化动作/服务器动作/定时任务**（Odoo 的"零代码"实现方式） | select count(*) from base_automation; + select * from base_automation; + select name,model_id from ir_act_server; | `base_automation` 仅 **4 条**，模型分别是 op.assignment.sub.line(623) 与 op.media.movement(647)——**没有一条挂在 op.admission/edu.application**；41 条 cron 里也没有 | ✅ 没有「偷偷自动发码」的第二套实现 |
| 7 | 有没有**第二处**「把一张码发给某个外部身份」的实现 | grep -rniE "edu.invite.code" --include="*.py" --include="*.xml" custom_addons/ ｜ grep -v "^custom_addons/edu_portal/models/invite_code.py" | 只有两条活路径：① `edu_tg_bind/models/tg_claim.py`（TG 池）；② 后台**批量生成向导** `edu_portal/models/invite_code.py:405-463` + 视图 `views/invite_code_views.xml` | ✅ **只有两处**，本设计将是**第三处** ⇒ §8.5 给了"第三处 ⇒ 必须收口"的触发条件 |

### 3.2 为什么不复用基座 op.admission.enroll_student()（**第 0 步最重要的一条**）

它是本仓唯一一个「录取 → 建学生 → 建门户账号」的既有实现，**必须逐条否证**：

| # | 理由 | 证据（路径 + 行号，不贴源码） |
|---|---|---|
| R1 | **数据模型不兼容**：它要求 register_id（op.admission.register，**required**）与 email（**required**）、gender 是 m/f、姓名拆 first/middle/last、还要 fees term / program / course 结构 | `openeducat_admission/models/admission.py:67-68,92-100`；而本仓报名表是**元数据驱动**的 edu.application（`application.py:16-46`：email **非必填**、中文姓名单列、科别是 3 值 Selection） |
| R2 | **本仓这条链路是死的**：op_admission **0 行**、op_admission_register **0 行**（本机只读 SELECT）；ACL 只给它自己的两个组（openeducat_admission.group_op_admission_*，见该模块 security/ir.access.csv），**教务组不在内**；它的根菜单已被 edu_apply 显式限制回基座自己的组（`custom_addons/edu_apply/views/backend_views.xml:188-196`，注释写明"教务点进去只会撞访问错误弹窗——2026-09-17 校长实际遇到"） | 本机 SELECT + 上述行号 |
| R3 | **它解的不是校长的问题**：它建出来的账号**没有密码、也没有邀请入口**（get_student_vals 的 res.users.create 只给 name/login/is_student/company_id/group_ids，**不含 password**），所以"他能登录"这一步**它也没解决** | `openeducat_admission/models/admission.py:250-260`；开关参数 openeducat_admission.enable_create_student_user **默认 True**（该模块 `data/parameter_data.xml`，本机实测库内值 True） |
| R4 | **它会写本仓不认的账**：enroll_student() 顺带写学费明细（`:334-371`）与 op.subject.registration（`:379-387`），而本仓费用口径是**统筹费 + CNY**（`code-map.md:83`）、选课走门户 enroll.py + 教务审批（`registration.py:133-212`） | 行号见左 |

> **裁定的另一半**：**抄什么**——get_student_vals() 把"申请的实体列 → res.partner 字段 → op.student 字段"逐项映射的**做法**值得抄（`:261-301`），本设计只抄**映射口径**，不抄代码、不调它的方法。

### 3.3 「没找到」的，也要写清范围（负结论）

| 负结论 | 搜索范围与方式（原样可复现） |
|---|---|
| **全仓没有"录取后发码"的任何实现**（包括自动动作） | ① grep -rniE "invite_code｜注册码｜入学码｜发码｜create_student｜op.student｜approve｜admitted" custom_addons/edu_apply/ = 2 行状态机字样；② grep -rniE "入学码｜录取码｜admission_code｜invite_link｜issue_invite｜grant_invite｜send_invite｜发放入学"（custom_addons/ + docs/ + scripts/）= 0；③ base_automation 4 条逐条看模型 = 0 条命中；④ grep -rn "edu.application" 全仓 = 仅依赖声明与可达性测试 |
| **全仓没有"申请转学生"的实现** | ① 同上 #2（edu.application 的全部引用）；② 读 edu_apply 全部 3 个 Python 文件 + 2 个 XML（models/、controllers/、views/）；③ grep -rn "op.student" 与 grep -rn ".create(" custom_addons/ 交叉核对，只命中 `edu_portal/models/invite_code.py:353-358`（层级码注册建【待分配】档案）与种子脚本 |
| **edu.invite.code 上没有任何"来源单据"字段** | 读 `edu_portal/models/invite_code.py:94-143` 全字段 + 本机列清单（code/note/state/used_login/used_on/expire_at/student_id/parent_id/faculty_id/identity/use_limit/used_count/code_kind/tier/batch_ref）⇒ **没有任何指向申请的列** |
| **没有第三处发码实现** | grep -rniE "edu.invite.code" 全仓逐条判定（#7）⇒ 只有 TG 池 + 后台向导两处 |

---

## 4. 第 0 步③：设计摘要落点

✅ 本文即 `docs/plans/admission-invite-link-design.md`（第 4 步产出物）：**既有实现对照在 §3**、**第 3 步读参考在 §7**、**载体裁定在 §8**、**三个专问（码从哪来/幂等/兜底）在 §9**、**安全在 §10**、**连回与 C-2 P5 衔接在 §11**、**边界/数据流/动作清单/权限在 §12**、**验收在 §13**、**拍板项在 §14**。

---

## 5. 第 0 步④：升级会不会动业务数据

> 依据 `docs/dev-workflow.md:33-47`（finding-F5）：data 每次 -u **重放**，demo 只在安装且开启演示数据时装载。

1. **本设计的 manifest（拟）**：data = ['views/apply_admit_button.xml']——**只有一条继承视图**（把按钮插进 `edu_apply.view_edu_application_form` 的 <header>，该 header 在 `custom_addons/edu_apply/views/backend_views.xml:26-28`）。
2. **不写任何 <function>、不建码、不建示范申请**：data 里若出现写业务表的函数，一律禁止（`dev-workflow.md:42`）。⇒ **预期 -u / -i 对业务表的副作用 = 0**；唯一 DDL 变更是给 edu_invite_code 加 1 个**可空列** + 1 个唯一约束（存量行 application_id = NULL，**NULLS DISTINCT ⇒ 不冲突**）。
3. **⚠ 如实点名两条邻近风险**：
   - `edu_life/data/demo_life.xml` 的 <function …_load_demo_records/> 按滚动窗口补写业务表（`dev-workflow.md:103-127`，t12 修复中）。**它与本设计无关**，但**它证明的规矩对本文有效**：写业务表的种子函数**不得**放 data/。本设计的验收若含"计数型判定"，**先按陷阱 1 探活**。
   - **F1 未关闭**（`docs/audit/finding-F1-menu-replay-on-upgrade.md`）：-u edu_portal 会把菜单收口值重放回来（backoffice 12→17）。⇒ 这是 §8.2 **不把落点选在 edu_portal** 的直接理由之一；如果实施者改了主意落进 edu_portal，部署清单里**必须**带一条 python3 tests/audit/verify_upgrade_persistence.py --modules edu_portal --restore。

---

## 6. 第 0 步⑤：演示数据策略（一句话）

**本设计不新增任何业务演示数据。**
- 真机验证用**库里已有的 6 条申请**是**不行的**——发码会真写码、真发邮件。⇒ 验收必须自造样本，且**放在验证脚本里而不是模块里**：`scripts/seed_admit_invite_demo.py`（仓库惯例：scripts/seed_*.py 必须**幂等**），**姓名/备注一律带【演示】前缀**（`code-map.md:247` 第 5 条硬约定），**清理分支写在同一脚本的 --clean**（按前缀 unlink，并**断言计数归零**）。
- **禁止**放进 data/（理由见 §5.2）。
- 本地验证用的**收件邮箱必须是不可送达的假地址**（如 demo-admit@example.invalid）——避免真发到任何真实邮箱；且**断言邮件到 mail_mail 为止**（本机无 SMTP，见 §7-Q4）。

---

## 7. 第 3 步「读参考」：逐条结论（Q1–Q7）

> 规矩：**给实查结论，不要猜**。每条都给「读了哪几行 + 用什么命令 + 命中什么」。

### Q1 邀请码体系现状（edu.invite.code）：能不能承载"入学码"？

| 事实 | 证据 |
|---|---|
| 字段与语义已够用：code_kind(person/tier)、tier(student/parent/faculty/backoffice)、use_limit、used_count、expire_at、batch_ref、note、created_by、used_by/used_login/used_on | `edu_portal/models/invite_code.py:99-141`；本机表结构列清单 |
| **unique(code) 已在**（S1 已落地） | 模型 `:143`；本机约束名 edu_invite_code_code_uniq（UNIQUE CONSTRAINT） |
| 有效期默认 **7 天**（expire_at required） | `:139-141` |
| 消费判定：state != 'unused' 或 used_count >= use_limit → 「该邀请码已被使用」；expire_at < now → 「该邀请码已过期」（惰性，无 cron） | `:264-273` |
| 注册成功消费：used_count+1、首个使用者写 used_by/used_login/used_on、用尽置 state='used' | `:392-402` |
| 层级码注册后**自动建【待分配】档案**（学生层：partner_id/gender/user_id/edu_pending_setup=True，并在建完后给 partner 名称加【待分配】前缀） | `:337-390`（学生分支 `:352-358`） |
| 「待分配」判据字段 edu_pending_setup **已存在且已建索引**（index=True）——可直接当"待办队列" | `:470-491` |
| 教务对 edu.invite.code 的 ACL = **全权**（R/W/C/U） | 本机 ir_model_access：id 1408（组=**经理**=教务）；id 1148（管理员） |
| edu.invite.code 的**全局记录规则**：非系统管理员只看 tier != 'backoffice' | 本机 ir_rule id 344，domain_force = [] if user.has_group('base.group_system') else [('tier','!=','backoffice')]，**global=t** ⇒ 我们发的是 tier='student'，**教务可见可建**，守卫不受影响 |
| 批量向导**明确反对连号码**（"连号可被外面的人按序猜到（等于把邀请码变成可枚举口令）"） | `:405-463`，尤其 `:408-409` |

**⇒ Q1 结论**：edu.invite.code **能承载**"入学码"（层级码语义、有效期、次数、消费、留痕、教务 ACL 全都现成）；**缺的只有一条"这张码是给哪条申请发的"的绑定**（§8.3 论证这是唯一必要的 schema 变更）。

### Q2 `/register` 消费链路：申请人拿到码之后会发生什么？

| 步骤 | 证据 |
|---|---|
| 友好路径 `/register`（GET/POST）→ 实现在 EduRegister；`/web/register` 302 兼容 | `edu_portal/controllers/main.py:235-259`；`controllers/register.py:41-55` |
| 校验顺序：必填 → 邮箱格式 → 密码 ≥6 → 两次一致 → **码存在** → _validate_view() → _validate_identity() → 邮箱未被注册 | `register.py:23-81` |
| 建账号：**只给 base.group_portal**（层级码则写该层级的组；portal 与内部组**二选一**，Odoo 禁同属） | `register.py:83-98` |
| 随后：attach_identity()（绑人码）→ create_pending_archive()（层级码）→ consume() → 自动登录 → redirect('/my/home') | `register.py:119-135` |
| `/register` 页面的输入框是 text-uppercase（**只是 CSS**），后端 vals['code'].upper() 才保证小写输入可命中 | `register.py:28-30` |

**⇒ Q2 结论**：**消费侧一行都不用改**。本设计要做的只是"把码交到正确的人手里"。

### Q3 码池与"一人一码"的既有实现（edu_tg_bind）：哪些要抄、哪些不能共用？

| 要抄的 | 证据 |
|---|---|
| **三层防线**：FOR NO KEY UPDATE SKIP LOCKED（挡在途）+ **唯一约束**（挡已提交）+ 整事务 ROLLBACK 换快照重试（Odoo 19 = REPEATABLE READ，裸 SKIP LOCKED 不够） | `edu_tg_bind/models/tg_claim.py:12-20, 188-226`；设计 `docs/plans/tg-invite-bot-design.md` §5（含四组对照实验） |
| **"先落库再出网"**：决定是否回复/发信的 created 标志由"这次真的新建了吗"决定；出网失败**不回滚**业务记录 | 设计 §5.7 |
| **不写 state/used_count**：领取 ≠ 消费；提前写会让持码人注册时被判「已被使用」 | 设计 §3 的不变量（`tg_claim.py:143-146` 同源注释） |
| **"取不到"的两种原因分开报**：空池 vs 全被在途锁住，文案不同 | `tg_claim.py:130-171` |

| 不能共用的 | 证据 / 后果 |
|---|---|
| **池**（batch_ref 前缀 + state='unused' + used_count=0 + 未过期 + code_kind='tier' + tier='student' + 未被 edu_tg_claim 领走） | `tg_claim.py:48-57`。**⚠ 这条 SQL 看不见网页侧的发放**：网页发出去的码在注册前**仍满足上面全部条件** ⇒ 共用前缀时，TG 学生**可能领到同一张已经 email 给申请人的码**。共用就必须改这段 SQL（跨模块改动），不共用就不用改。见 §9.1 的完整论证。 |
| 把网页发放塞进 edu.tg.claim | chat_id 语义是"Telegram 私聊会话 ID"（`:65-68`），把申请 id 塞进去会污染 TG 后台视图（`views/tg_claim_views.xml:13` 明写"本页只显示 edu.tg.claim"），且破坏它的两条唯一约束语义 |

### Q4 通知书出口与本仓邮件能力（**含一条硬事实**）

| 事实 | 证据 |
|---|---|
| 既有出口形态：mail.mail.sudo().create({...}).send(raise_exception=False)，收件人取参数 edu.apply_notify_email → 兜底 res.company.email | `edu_apply/controllers/main.py:93-117` |
| **本机 ir.mail_server = 0 行** ⇒ 现在这套栈**根本发不出邮件**（而 `_notify` 却一直"看起来在工作"，因为它把异常吞了：`edu_apply/controllers/main.py:116-117`） | 只读 SELECT：select id,name,smtp_host,smtp_user,active from ir_mail_server; ⇒ **0 rows** |
| **没有 SMTP 记录时 Odoo 会退回 localhost:25**（配置默认 smtp_server=localhost / smtp_port=25） | 运行镜像 `base/models/ir_mail_server.py`（_connect__ 的 else 分支读 tools.config.get('smtp_server')）；`odoo/tools/config.py` 的 --smtp / --smtp-port 默认值 |
| send(raise_exception=False) 失败时**不抛异常**，而是把邮件写成 state='exception' + failure_reason | `addons/mail/models/mail_mail.py:721-727, 946-961` |
| 发件人已配：mail.default.from = scrtsschool@gmail.com；公司邮箱同值 | 只读 SELECT（ir_config_parameter / res_company） |
| 短信通道**不可用**：sms 模块 installed，sms_twilio **uninstalled** | 只读 SELECT（ir_module_module） |

**⇒ Q4 结论**：邮件**形态可照抄**，但**本机发不出去**（无 SMTP）⇒ 验收只能证到"邮件记录已生成"，**不能**证"已送达"；生产 SMTP 是否可用**未核对**（§15）。**这条直接决定 §9.3 的兜底必须是"页面回显"而不是"邮件是唯一通道"。**

### Q5 「申请 → 档案」的字段映射：抄谁？

- 抄基座 `openeducat_admission/models/admission.py:261-301` 的**映射口径**（申请实体列 → res.partner（name/phone/email/street/city/country…）→ op.student（first/last/birth_date/gender/course_detail_ids…））。
- **不抄它的写路径**（§3.2 R1–R4）。
- ⚠ 本仓注册路径有自己的口径：**带身份的路径绝不把注册输入写进人员档案**（`register.py:91-93` 的 F1 注释）——若将来做"发码时预建档案"，这条必须遵守。

### Q6 Odoo 19 核心可抄的三件事

| 主题 | 一手证据（路径 + 行号） | 学什么 |
|---|---|---|
| **行级互斥的官方 API** | `odoo/orm/models.py:5564-5590`（lock_for_update(allow_referencing=…)，内部用 FOR NO KEY UPDATE SKIP LOCKED）、`:5592-5614`（try_lock_for_update() → **返回能锁到的记录集**，锁不到的被跳过，**不抛异常**） | 按钮的"并发在途"一层**不需要自己写 SQL、也不需要 rollback**：app.try_lock_for_update() 拿不到 = 有另一个请求正在发放 ⇒ 直接回"正在发放，请稍候"。⚠ 该 API **未在按钮上下文实跑**（§15） |
| **按钮返回人话**（不是刷页面） | 本仓**在用的先例**：`custom_addons/edu_schedule/models/session_ext.py:795-811`（action_notify_session_change 返回 ir.actions.client / display_notification，按 failed 切换 success/warning）。⚠ 该文件当前有在途改动，行号以落地时为准 | 我们的按钮**照这个形状返回**：把这"一次发放"的码与投递结果直接弹给教务看（这是 G3 兜底的关键） |
| **邮件失败不阻断业务** | `mail_mail.py:721-727`（raise_exception=False 写 state='exception'）；本仓 `edu_apply/controllers/main.py:116-117`（except: pass） | 先落库（码 + 绑定 + 审计），再出网；出网失败只提示、不回滚 |

### Q7 相邻设计：哪里必须对齐、哪里不能冲突

| 相邻设计 | 必须对齐的点 | 证据 |
|---|---|---|
| **班级管理 C-2**（已拍板） | ① 本设计与 C-2 **不重叠**：C-2 管的是 op.batch（班级实体）与"何时分班"；本设计**不碰 op.batch、不写 op.student.course**。② **衔接在 C-2 的 P5(b)**：「先注册后置待办、教务去分」——层级码注册后自动产生的【待分配】档案（edu_pending_setup=True）**就是那个待办队列**。③ ⚠ **C-2 已声明本设计的最后一公里依赖它**：`docs/plans/class-batch-management-design.md:661`（P5 表格）明写「(b) 依赖 G1（分班入口）先落地，否则学生会一直卡在「待分配」」 | `class-batch-management-design.md:20-28, 215-231, 661` |
| **改课通知 C-1** | **通知通道口径**：站内信 edu.message 只能发给**已有账号**的人——申请人**还没有账号**，所以本设计**不能**用 edu.message；C-1 另外立了个"用 edu.audit.log 承载'最近一次通知'、**不新增字段**"的口径，本设计的幂等展示与留痕照它 | `docs/plans/session-change-impact-design.md:81`（#7 通道）、`:235-240`（§7.4 幂等不新增字段） |
| **学生门户主页/资料 H-1** | H-1 的"资料待补全提示"用的是 edu_pending_setup 标记，且口径是「**提示而非拦截**」——本设计产生的【待分配】档案会直接出现在它的提示面上（**这正是我们想要的**：让新生知道要找教务） | `docs/plans/student-portal-home-profile-design.md:205`（C 方案）、`:223`（/register 只写 name/email/password） |
| **TG 发码机器人 T-E** | **不共用池、不共用表、不共用参数、不共用路由**（§9.1/§12）；本设计**不改 edu_tg_bind 一行** | `docs/plans/tg-invite-bot-design.md:25-56, 149-171` |

---

## 8. 载体裁定（复用 / 合并 / 新建）+ 字段论证 + 收口触发条件

### 8.1 裁定（逐能力，落成台账里的一个字）

| 能力 | 裁定 | 替代路径 / 扩展方式 |
|---|---|---|
| 码实体（edu.invite.code） | **复用** | 既有模型；本设计只加 1 列 + 1 条唯一约束 |
| 码的生成 | **复用** | 既有 code_kind='tier' / tier='student' 语义 + 既有 ORM create（`invite_code.py:179-188`） |
| 码 → 注册 → 落层 → 建【待分配】档案 | **复用** | 既有 `/register` 链路（`register.py:53-135`），**零改动** |
| 申请实体列 → op.student 字段映射（若将来做） | **复用其口径**（不复用代码） | 抄 `openeducat_admission/models/admission.py:261-301` 的映射思路 |
| 通知书出口 | **复用** | mail.mail + send(raise_exception=False)（照 `edu_apply/controllers/main.py:111-115`） |
| **"申请 ↔ 码"的绑定与幂等** | **新建 1 列**（唯一必要的 schema 变更） | edu.invite.code.application_id + unique (application_id) |
| **载体（动作落在哪个模块）** | **新建薄模块 edu_admit_invite** | depends: ['edu_portal']；2 个 _inherit（edu.application / edu.invite.code）+ 1 个继承视图；**零新增模型/表/ACL/菜单/路由** |
| 码池 | **不共用、也不另立** | 按需生成（§9.1） |

> **一句话**：**"复用一套码体系 + 补一列绑定 + 新建一个薄模块装这个动作"**。

### 8.2 为什么不是「合并」、为什么落点不选 edu_portal

**不是"合并"**：本仓"合并"的定义是"新旧两套都留记录、只留一个入口/一份引擎"（`dev-workflow.md:61`）。本设计**没有第二套引擎**——码、注册、落层、档案全走既有唯一实现；edu_tg_bind 不动。所以它不是合并题。

**落点三选一的代价对照**（这是本设计最需要被复核的一张表）：

| 候选载体 | 新增面 | 代价 | 判定 |
|---|---|---|---|
| **A. edu_portal**（码模型所在模块） | 1 列 + 1 约束 + 1 继承视图 + 2 个方法 | ① **-u edu_portal 会触发 F1 菜单重放**（backoffice 12→17，未关闭）⇒ 本功能的每次部署都要带一条"重放后恢复"的操作；② edu_portal 是最大模块（~1.5 万行、25 模型，`code-map.md:50-76`），把"招生渠道"塞进去会糊边界 | ❌ 不选 |
| **B. edu_apply**（申请模型所在模块） | — | **物理上不可能**：字段必须指向 edu.invite.code，而 edu_portal 依赖 edu_apply（`edu_portal/__manifest__.py:29`）⇒ 反向依赖 = **循环依赖**，且 `edu_tg_bind/__manifest__.py:29-30` 已明写"不声明依赖会在装载期撞 comodel 断言" | ❌ 不可行 |
| **C. 新建薄模块 edu_admit_invite** | 同上 + 模块目录 | ① `scripts/deploy_myedu.sh` **三处硬编码模块清单**要各加一个名字（`:11` 默认 MODULES、`:18` rsync 列表、`:23` chmod 列表）；② 生产**首次要 -i**（不是 -u，先例：edu_zh，见该脚本 `:15-16` 的注释）；③ 多一个模块要维护 | ✅ **选它** |

**选 C 的三条正面理由**：① **不碰他人模块**（本任务与 edu_tg_bind 的原始边界完全同构——"新模块、不碰既有模块"，`tg-invite-bot-design.md:155,462`）；② **升级面干净**：新模块**不声明任何菜单** ⇒ 不会像 edu_portal 那样重放菜单收口值（F1）；③ **依赖方向天然正确**：edu_admit_invite → edu_portal → edu_apply，一路向下，无环。

### 8.3 字段论证：**能不能不新增字段？**（第 0 步口径：能不新增就不新增）

**先回答方向问题（这一条是硬的）**：
- 任务里点名的 `edu.application.issued_invite_code_id` / `issued_at` 这一形态，**在 edu_apply 里落不了地**——见 §8.2 B（循环依赖）。
- 所以"字段加在哪"只剩两个可能：**新建模块里 _inherit 任一侧**。下表逐条论证"能不能一个字段都不加"：

| 候选复用对象 | 能否承载"申请 ↔ 码"的绑定 | 否证理由（带证据） |
|---|---|---|
| **invite_code.used_by / used_login / used_on** | ❌ | 这三个字段是**注册消费侧**的（`invite_code.py:135-138`，由 consume() 在**注册成功后**写，`:392-402`）。发码时申请人**还没有账号、也可能没有邮箱**（6 条申请只有 1 条有邮箱）⇒ **时序上不可能承载** |
| **invite_code.student_id**（绑人码"对应学生"） | ❌ | 那是**绑人码**字段，指向 op.student；本设计的学生档案**注册后**才有（create_pending_archive，`:337-390`）。发码时无学生可指 |
| **invite_code.note**（Char，备注发放对象） | ❌ | 自由文本、**无唯一约束** ⇒ 拿它做幂等就是"先查后判"（正是队长要求排除的 if 判断）；且它是**人可读**字段，机器键塞进去会毁掉它的用途（人要在这里看"发给谁"） |
| **invite_code.batch_ref**（批次标签） | ❌ | ① 语义是"**同批共用**的标签"（`:131-132`），拿它当**每记录唯一键**是反向使用；② 它已被 edu_tg_bind 当作**池前缀**（`tg_claim.py:48-57`）⇒ 再给它加 unique 会直接打穿 TG 的池机制；③ 无唯一约束 ⇒ 并发下会生成两张"同申请"的码 |
| **用"确定性码文本"（如 ADM-000012）靠既有 unique(code) 免掉新字段** | ❌（技术上能，**安全上不能**） | 连号/可推导码 = **可枚举口令**，与本仓既定口径直接冲突："连号可被外面的人按序猜到（等于把邀请码变成可枚举口令）"（`invite_code.py:408-409`）。码本身就是**身份凭据**（§10），不能牺牲强度换一列 |
| **edu.audit.log（只记事件、零字段）** | 🟡 部分 | C-1 先例确实用审计日志承载"最近一次通知"而不加字段（`session-change-impact-design.md:235-240`）。但**审计日志没有唯一约束** ⇒ 并发双击仍可能建出两张码（各自都写成功）。⇒ **可以用它做"展示与留痕"，但不能用它做"幂等闸门"** |

**⇒ 结论**：**必须且只需 1 列**：

| 项 | 内容 | 理由 |
|---|---|---|
| 字段 | edu.invite.code.application_id：Many2one('edu.application')，ondelete='restrict'，string="入学申请" | 方向正确（码知道自己的来源）；ondelete='restrict' 与 `edu_tg_claim.invite_code_id` 同口径（`tg_claim.py:71-73`）——**删申请前必须先处理码**，不静默解绑 |
| 唯一约束 | models.Constraint('unique (application_id)', '这条入学申请已经发过入学码了。') | **一条约束同时锁住两个方向**：① 一条申请**最多一张码**（= 幂等，DB 级）；② 一张码**只能属于一条申请**（列是标量）。⚠ Postgres 唯一索引默认 **NULLS DISTINCT** ⇒ 池里未发出的码（application_id IS NULL）**互不冲突** |
| 不要重复加 index=True | — | 唯一约束自带索引；再加一个普通索引是重复的 |
| **不需要的字段** | issued_at / issued_by / issued_state / notify_state | 发放时刻 = 码行 create_date；发放人 = created_by（默认 env.user，`:133-134`）；是否已注册 = state / used_by / used_login；邮件投递结果 = mail_mail 行（res_model='edu.invite.code' + res_id=code.id，含 state / failure_reason，见 `mail_mail.py:91`） |

**表单上要显示的那几项全部是"非存储计算字段"**（compute=...，store=False ⇒ **不加列**）：issued_invite_code（码文本）、issued_used_login（注册邮箱）、issued_used_on（注册时刻）——实现时用 search([('application_id','=',rec.id)]) 反查，**必须在 _compute_… 里对 self 逐条赋值**（列表视图不要挂它们，避免 N+1）。

### 8.4 幂等：用哪条唯一约束？（对齐 edu_tg_bind 的"数据库唯一约束，不是 if 判断"）

**答案：unique (application_id) on edu.invite.code**（上面那条），并**照抄 `tg_claim.py` 的三层防线**：

| 层 | 挡什么 | 机制（本次用哪条） |
|---|---|---|
| 1 | 顺序重复点（最常见） | **先查后回显的快路径**：search([('application_id','=',app.id)], limit=1) 命中即回显，**零写入、零邮件**（对齐 `tg_claim.py:197-199`，以及 `tg-invite-bot-design.md:232-234` 的幂等口径） |
| 2 | **在途**并发（两个请求同时在跑） | app.try_lock_for_update()（`odoo/orm/models.py:5592`，内部 FOR NO KEY UPDATE SKIP LOCKED）→ 拿不到 = 对方正在发 ⇒ 回「正在发放，请稍候」，**不写不发不 500** |
| 3 | **已提交**并发（快照过期，第 2 层看不见） | **unique (application_id)** = **数据库级最后一道闸**；命中 UniqueViolation 时按 `tg_claim.py:188-226` 口径处理：env.cr.rollback() → env.invalidate_all(flush=False) → 重查 → 回显（**换快照**；设计 §5.4 实测：savepoint 内重取会一直撞同一条） |

> ⚠ **实施者注意**：第 3 层要不要真做"整事务 rollback"取决于落地方式——**若第 2 层能先锁住申请行，第 3 层几乎不可达**；此时可降级为「捕获唯一约束冲突 → 抛一句人话 UserError('该申请已发放入学码，请刷新页面查看')」，并把"两人同时点同一条申请"列为**已知边界**。**两种写法都要在实施报告里写明选了哪种、为什么**（本设计只锁定"必须有 DB 级约束"这条不变量）。

### 8.5 收口 / 复发触发条件（不写这一节，它就不是决定、是遗忘）

| # | 触发条件（可观察、可判定） | 到时该做什么 |
|---|---|---|
| **T1** | **出现第三个"把一张码发给某个外部身份"的场景**（今天只有 TG 与网页两处，§3.1 #7） | **必须把"发放记录"收口成一张表**：统一的 edu.invite.issue（渠道列 + 领取方键 + unique(渠道, 领取方键) + unique(invite_code_id)），把 edu.tg.claim 与本设计的 application_id 一并迁入。**这同时是 `dev-workflow.md:74` 说的"同一功能第三次出现重复 ⇒ 必须脚本化"的同一条** |
| **T2** | 有人要给 edu.invite.code 加**第三个**"来源单据"字段（如 op.admission_id） | 停手，回本设计 §8.3 与 T1 一起裁定 |
| **T3** | edu_tg_bind.pool_batch_prefix 被改成能匹配到 ADM- 前缀 | ⚠ **立刻停**：TG 池会开始往外发"已经 email 给申请人"的码（§9.1 后果②）。这是**配置层的红线** |
| **T4** | 校长要求"点一下之后学生**直接进班**" | 这是**新决策**（不是本设计的补丁）：首选路线 = 在**本设计之上**叠加"发码时预建 op.student（用 `op.admission.get_student_vals` 的字段映射口径）+ 教务分班（依赖 C-2 的 G1）"，并评估是否改用**绑人码**（§9.1 末），另立任务 |
| **T5** | edu_portal 的 invite_code.py **状态机被改动**（如真加了 revoked，`invite-code-tiers-design.md:270-273` 的建议） | 把本设计的"撤销 = 改 expire_at"（§10）**改用正式状态**，并复核 unique(application_id) 与 revoked 的交互 |

---

## 9. 三个专问：码从哪来 / 幂等 / 渠道与兜底

### 9.1 码从哪来：**共用池 / 另立池 / 按需生成**？

**结论：按需生成（点一次、生成一张），既不共用 edu_tg_bind 的池，也不另立池。**

**为什么不共用**（逐条给后果，任务点名要回答）：

| # | 后果 | 机制（带行号） | 严重度 |
|---|---|---|---|
| ① | **一边把池抽干 → 另一边卡死**，且**不会自动补货** | 池是**惰性判定、无 cron**（`invite_code.py:264-273`）；TG 侧空池的文案是「暂时没有可用的邀请码，请联系教务处」（`tg-invite-bot-design.md:446`）。若共用，两个渠道抢同一批备货，谁先来谁拿走 | 中（可运维） |
| ② | **同一张码会被两个渠道各发一次** | TG 的池判据（`tg_claim.py:48-57`）只排除"已被 edu_tg_claim 领走"的码；而**网页侧发出的码在注册前仍然** state='unused'、used_count=0、未过期、code_kind='tier'、tier='student' ⇒ **完全满足 TG 池的全部条件**。于是同一张码会同时出现在两个人的手里：先注册的那个成功，后注册的那个被判「该邀请码已被使用」 | **高**（支持工单 / 谁该是学生说不清） |
| ③ | 修 ② 的代价是**跨模块改 SQL** | 要么给 `edu_tg_bind._POOL_WHERE` 加一条"排除已被网页发放的码"（`docs/plans/tg-invite-bot-design.md` 的边界是"本轮明确不做：改 edu_portal"，反向同理），要么把池判据抽成公共函数 ⇒ **两份判据 = 漂移风险**（`tg_claim.py:46-47` 的注释已经为此立过规矩："**只有这一份**：取码与计数共用它，避免两处 SQL 判据漂移"） | 中（工程债） |

**为什么"按需生成"是本渠道的正确形态**：

1. **池存在的唯一理由是"无人值守、随时能发"**——TG 机器人**没有人点**（学生随时私聊）；网页渠道**有人点**（教务点了才发）。有人在场时，池是多余的中间层。
2. **按需生成让"同一张码发给两个人"在物理上不可能**：码在创建的那一刻就绑定了唯一一条申请（unique(application_id)），而 TG 池的判据**永远不会看到**它（前缀不同，见下条）。
3. **天然零交叉**：给网页渠道的码打**自己的前缀**（建议 batch_ref = 'ADM-〈yyyymmdd〉'）⇒ TG 的 batch_ref LIKE 'TGB-STU-%' 匹配不到；反之亦然。**零改动 edu_tg_bind**。
4. **备货成本归零**：TG 那边"生产码池怎么建"至今是遗留未决点（`tg-invite-bot-design.md:467`）；本渠道**不会重现**这个问题（点了就有码）。
5. 码的属性与池**完全一致**，教务感受不到差别：code_kind='tier'、tier='student'、use_limit=1、expire_at=now+有效期、created_by=当前教务、note='入学申请 #〈id〉 · 〈姓名〉'（**只写人可读的"发给谁"，不写身份证号等敏感字段**——码列表对教务可见，且全局搜索能按码/备注搜到，`edu_portal/controllers/search.py:156-173`）。

**退路（若校长坚持"预先备好一批码"）**：给报名渠道**另立一个前缀的池**（例如 ADM-），按 _validate_view() 同口径选码（state='unused' + used_count=0 + 未过期 + code_kind='tier' + tier='student'）；**仍然不共用 TG 的前缀**。代价 = 多一处备货 + 需要处理"池空"的人话（照 `tg_claim.py:130-171` 的两种原因分开报）。

**码的类型：用「层级码」还是「绑人码」？**

| | 层级码（tier='student'）← **本设计推荐** | 绑人码（identity='student' + student_id） |
|---|---|---|
| 发码前的写面 | **只写 1 行码** | 要**预建 res.partner + op.student**（2 个写入 + 档案必须先有） |
| 注册后 | 自动建【待分配】op.student 并挂 user_id（`invite_code.py:352-358`）⇒ **不会 C1 空转** | 挂接到**预建**的档案（attach_identity()，`:305-326`），姓名/电话等**已带过去** |
| 教务后续 | 要补全档案（电话/证件号/教会…） | **零补录**（从申请表带过来）+ 分班即可 |
| 风险 | 无孤儿档案 | 若对方永不用码 ⇒ 留下**无主档案**；作废/重发要连带处理档案 |
| 裁定 | ✅ **本轮用它**（校长原话"自动取一张学生层级邀请码"） | ⏸ 列为 **T4 的升级路径**（只有当校长要求"零补录"时再上） |

### 9.2 幂等（见 §8.4，此处只留结论）

**unique (application_id)** 是那一条约束；顺序重复点走"先查后回显"，并发在途走 try_lock_for_update()，已提交冲突由唯一约束挡住并按"换快照重试"处理。**重复点按钮 = 回显原码 + 不重复发信**（created 标志决定是否出网，照 `tg-invite-bot-design.md` §5.7）。

### 9.3 渠道与兜底：**没留邮箱的申请怎么发码？**（必须回答的一问）

**事实**：`edu.application.email` 是 fields.Char('电子邮箱')，**没有 required**（`models/application.py:41`；本机 ir_model_fields 实测 required=f）；库内 **6 条申请只有 1 条**填了邮箱（只读 SELECT）。

**结论：主渠道 = 邮件（有邮箱才发）；兜底 = 页面回显码，教务自行电话/微信转告。**

| 渠道 | 现状能力 | 本轮裁定 |
|---|---|---|
| **邮件** | mail.mail 出口可用（`edu_apply/controllers/main.py:111-115`）；发件人 mail.default.from 已配；但**本机 0 条 ir.mail_server** ⇒ 退回 localhost:25 必失败 | ✅ **做**；**有邮箱才发**，失败只提示不回滚 |
| **页面回显（码常驻在申请表单上）** | 零依赖、永远可用 | ✅ **做，而且这是主兜底**：申请表单上**常驻显示**「入学码 / 发放时间 / 发放人 / 注册邮箱 / 是否已注册」（非存储计算字段，§8.3）；按钮返回的 display_notification 也**直接把码念给教务看**（先例 `session_ext.py:795-811`） |
| **电话 / 短信** | sms 模块已装但 **sms_twilio 未装 = 无服务商**；且短信同样是明文凭据 | ❌ **本轮不做**（唤醒条件：校长决定开通短信服务商 ⇒ 另立任务；那时复用 phone 字段即可） |
| **让申请人自助查码** | 需要额外凭据 + 防枚举 | ❌ **本轮不做**（新公开路由 = 新攻击面） |

**UI 口径（实现时照办）**：
- 申请人**没留邮箱** ⇒ 按钮**不禁用**（否则教务卡死），但发完后**必须**给出显式提示：「该申请未填写电子邮箱，**无法自动发送**；请复制此码电话告知：〈码〉」。
- 申请人**留了邮箱但发送失败**（mail_mail.state='exception'）⇒ 提示「邮件发送失败（原因：…）。码已生成，可电话告知：〈码〉」——**码永远要念出来**，因为"码在库里"对教务毫无用处。

---

## 10. 安全口径（校长刚问过安全，本节写足）

> 前提认知（必须先说白）：**邀请码 = 凭码注册即获得身份的凭据**。层级码注册后拿到的是 base.group_portal + 一个自动创建的【待分配】op.student 档案（`invite_code.py:34-39, 352-358`）。

### 10.1 有效期

| 项 | 建议 | 理由 |
|---|---|---|
| 默认 | **14 天**（系统参数 edu_admit_invite.valid_days，默认 14） | 「录取通知 → 本人决定 → 注册」常跨 1–2 周；⚠ **必须显式传值**：expire_at 的模型默认是 **7 天**（`invite_code.py:139-141`），不传就变 7 天 |
| 上限 | 建议 UI/代码层**不超过 30 天** | 凭据暴露窗口（与 `invite-code-tiers.md` §7.3 的建议同族） |
| 过期后 | **不自动续期**；教务点「重新发放入学码」→ 作废旧码 + 建新码（§10.4） | 无 cron（惰性判定），自动续期会静默延长暴露窗口 |
| 与 TG 的差异 | TG 池建议**更长**（`tg-invite-bot-design.md:468`：池里过期=学生领不到，且不会自动补） | 两个渠道的失效后果不同，**不建议统一成一个值** |

### 10.2 一码一人如何强制（**分层写清，含一条如实标注的缺口**）

| 层 | 机制 | 证据 |
|---|---|---|
| 发放侧 | ① use_limit=1（我们显式传）；② unique(application_id)（新）：**一条申请只有一张码**；③ unique(code)（既有）：码文本唯一 | `:143`；本机约束 edu_invite_code_code_uniq |
| 消费侧 | _validate_view() 判 state != 'unused' 或 used_count >= use_limit ⇒ 「该邀请码已被使用」 | `:264-273` |
| ⚠ **缺口（如实标注，不当结论用）** | 消费侧是**应用层"读-判-写"**：`register.py:63` 校验 → `:108` 建账号 → `:125` 消费，两步之间**没有行锁、也没有唯一约束** ⇒ **两个请求拿同一张码"并发"注册**时，理论上可能都通过校验、建出两个账号（consume 把 used_count 写成 2）。**本设计未实测**（测它要真建账号），也**不在本设计范围内修复**（属于 edu_portal 的事） | 行号见左；**登记为发现**（§15） |
| 缓解（本设计能做且成本为零的） | ① 码**只发给一条申请/一个邮箱**；② 申请表单上显示 used_login，**与申请邮箱不一致时高亮**（教务一眼看出"不是本人注册的"）；③ 全流程 edu.audit.log 留痕 | §12.4 |

### 10.3 邮件明文发码的风险与缓解

| 风险 | 说明 | 缓解 | 残余风险 |
|---|---|---|---|
| 收件箱/在途被他人看到 | 邮件是明文渠道，**无法保证只有收件人能看到**；码=身份凭据 | ① use_limit=1 + 有效期；② 正文明写"此码只发给您一人，请勿转发"；③ 码只发到申请表里那**一个**地址；④ 邮件里**不写身份证号等敏感信息**；⑤ 生产 SMTP 必须走 TLS（starttls/ssl）——**列为部署前置**，本机无 SMTP 无法验证 | 收件人自己转发 ⇒ 系统无法感知（只能靠 used_login 事后发现） |
| 邮件被误判垃圾邮件（对方以为"没收到"） | 学校域名发信若无 SPF/DKIM 记录，易进垃圾箱 | ① 页面回显兜底；② 教务可电话提醒；③ **上线前确认生产发信域名的 SPF/DKIM**（§15 未验证） | 未验证 |
| 注册接口爆破 | `/register/submit` 对错码立即回显「邀请码无效」，**无限流/无验证码**（`register.py:60-61`） | 码空间大（31 字符表 × 6 位 ≈ 8.9e8，`invite_code.py:27,66-67`）；**不要**改用自定义短码 | 中等（与既有口径一致，本轮不改） |
| 码被枚举 | 若有人把码做成连号 | **禁止**连号码（`invite_code.py:408-409`）；本设计用自动随机码 | — |

### 10.4 管理员误发给错误邮箱：后果与撤销

- **后果（说白）**：拿到码的人**就是学生了**——他能在 `/register` 建 portal 账号并自动获得一个【待分配】op.student 档案。**本设计不校验收件人身份**（与 TG 机器人同期口径：「领取即发」，`tg-invite-bot-design.md:460`）。
- **发现途径**：申请表单显示 used_login（注册邮箱）；建议**与 app.email 不一致时高亮**（零成本）。
- **撤销 / 重发（现状能力，逐条给做法）**：

| 手段 | 做法 | 代价 / 边界 |
|---|---|---|
| **作废（推荐）** | 把该码的 expire_at 改成**过去时刻** ⇒ _validate_view() 立即判「该邀请码已过期」，注册被拒（`:271-272`）。**不需要新增 revoked 状态** | 教务对码有 write 权限（ACL 1408）⇒ 可自助；变更应同写 edu.audit.log |
| 删除 | 教务对 edu.invite.code 有 unlink（ACL 1408 全权） | ❌ 不建议首选：会丢"发过"的记录（只剩审计日志）；且若该码已被 TG 领走会被 FK 挡住（edu_tg_claim.invite_code_id ON DELETE RESTRICT） |
| **重发** | ① 作废旧码（如上述）；② **把旧码的 application_id 解绑**（= False）——**这一步是必须的**，否则 unique(application_id) 会挡住第二张；③ 建新码并重发邮件；④ 两步都写审计 | 解绑后旧码变成"无主码" ⇒ **必须同时作废它**（只解绑不作废 = 留下一张仍可注册的孤儿码） |
| ⚠ **边界（必须写给校长）** | **作废只挡"还没注册的人"，不会回收已经注册成功的账号** | 账号回收是另一件事（res.users 停用/归档）。若已被人注册，教务要做的是：**停用那个账号 + 处理那个【待分配】学生档案**。与 `docs/plans/invite-code-tiers-design.md:271` 同口径 |

---

## 11. 注册之后的连回：申请 ↔ 新学生档案 ↔ 班级

### 11.1 数据链路（**全部用既有字段 + 本设计唯一那一列**，不加任何新字段）

```
edu.application  --(edu.invite.code.application_id)-->  edu.invite.code
                                                             |
                          used_by / used_login / used_on / state / create_date / created_by
                                                             v
                                                   res.users（新账号）
                                                             | user_id
                                                             v
                                    op.student（注册时自动建的【待分配】档案）
                                      edu_pending_setup = True   <- 既有字段（已建索引）
```

- **正查**（给一条申请，看它发出去的码与注册情况）：search([('application_id','=',app.id)]) → used_by（新账号）、used_login（注册邮箱）、used_on（注册时刻）、state（used = 已注册）。
- **反查**（给一个账号，看它来自哪条申请）：res.users → edu.invite.code.search([('used_by','=',user.id)]) → .application_id。
- **档案**：注册时 create_pending_archive() 已经写了 op.student.user_id（`invite_code.py:352-358`）⇒ **档案不需要额外连线**，used_by 就是那条线。
- **班级**：**注册不分班**（C-2 已实测：`class-batch-management-design.md:215-231`）——本设计**不碰**。

### 11.2 与 C-2 已拍板 P5「先注册后置待办、教务去分」的衔接（给结论）

| 环节 | 谁做 | 依据 |
|---|---|---|
| 注册完成后学生**有档案但没班** | 本设计（复用 create_pending_archive） | `invite_code.py:337-390` |
| 「待办队列」的判据 | **已经是现成字段**：edu_pending_setup = True（index=True） | `:470-491`；C-2 亦引用它（`student-portal-home-profile-design.md:205`） |
| 分班 | **C-2 的 G1**（教务在学生页面给班；缺口是"入口"，不是模型） | `class-batch-management-design.md:202-213, 661` |
| ⚠ **依赖声明** | 本设计的**最后一公里依赖 C-2 的 G1 先落地**；否则新生会停在【待分配】（C-2 已在自己的 P5 里写明这条依赖）。本设计**不重复设计分班入口** | `class-batch-management-design.md:661` |

**⇒ 结论**：本设计把学生送到「**有账号 + 有待分配档案**」这一站，与 C-2 的 P5(b) 严丝合缝；**"进班"由 C-2 接管**。若校长希望"更自动"，那是 T4（§8.5）。

---

## 12. 复用 vs 自研边界 / 数据流 / 动作清单 / 权限

### 12.1 复用 vs 自研边界（**自研部分极小**）

| 面 | 复用 | 自研（新增） |
|---|---|---|
| 码实体 / 字段 / 状态机 | edu.invite.code（`invite_code.py:94-402`） | **1 列** application_id + **1 条唯一约束** |
| 码的生成 | 既有 ORM create（`invite_code.py:179-188`，含大写归一与守卫） | 传参组装（code_kind/tier/use_limit/expire_at/note/batch_ref/application_id） |
| 码 → 注册 → 落层 → 建档 | `/register` 全链路（`register.py:53-135`） | **0** |
| 邮件出口 | mail.mail + send(raise_exception=False) | 正文/标题（**不新增 mail.template 记录**，用 Python 组装 HTML，照 `main.py:102-115`） |
| 留痕 | edu.audit.log._log（`audit.py:28-41`，失败只告警） | 一个 action 名 + detail 格式 |
| 幂等并发 | try_lock_for_update（`odoo/orm/models.py:5592`）+ models.Constraint（`tg_claim.py:87-90` 同款写法） | 三层防线的编排 |
| 按钮反馈 | ir.actions.client / display_notification（`session_ext.py:795-811`） | 文案组装 |
| 权限 | 教务对码是**全权**、对申请是**读+写**（ACL 1408 / 1403）⇒ **不需要任何 ACL 变更** | 视图 groups + ORM 门禁判据 |

### 12.2 数据流（逐步给文件:行号）

1. 教务在「招生 → 入学申请」（菜单 592，源码声明 `edu_apply/views/backend_views.xml:185`；库内 parent=300）打开一条 state='admitted' 的申请（状态机 `application.py:57-59`）。
2. 点按钮 **action_issue_admission_invite**（新模块在 edu.application 上的方法；按钮由继承视图插进既有 header，`backend_views.xml:26-28`；invisible="state != 'admitted'"，与基座 `admission_view.xml:52` 同手法）。
3. 方法内**顺序固定**：门禁（§12.4）→ **幂等快路径（命中即回显）** → try_lock_for_update() → create（unique(application_id) 兜底）→ edu.audit.log._log(...) → **仅当本次真新建**才出网（有邮箱才发）→ 返回 display_notification（把码与投递结果念给教务）。
4. 申请人收到邮件 → 打开 https://edu.example.org/register（`edu_portal/controllers/main.py:241-249` 别名 → `controllers/register.py:53-135`）→ 校验 → 建 portal 账号（`register.py:83-98`）→ create_pending_archive() 建【待分配】op.student（`invite_code.py:352-358`）→ consume() 写 used_by/used_login/used_on/state（`:392-402`）→ 自动登录 → `/my/home`。
5. 教务回到同一条申请：表单上**常驻显示**「入学码 / 发放时间 / 发放人 / 注册邮箱 / 已注册」（非存储计算字段反查码行）。

### 12.3 路由与动作清单（本次设计的**全部**新增面）

| 类型 | 名称 | 形态 | 说明 |
|---|---|---|---|
| 路由 | **无新增** | — | 申请人走**既有** `/register`；教务走**后台按钮**（ORM，不经 HTTP 路由）⇒ **零新公开面** |
| 动作（后台按钮） | edu.application.action_issue_admission_invite | type="object"，string=「发放入学码」（**待拍板**，§14-P1）；groups="openeducat_core.group_op_back_office_admin,base.group_system"；invisible="state != 'admitted'" | 主按钮 |
| 动作（后台按钮） | edu.application.action_reissue_admission_invite | 同上；invisible="未发过码 或 已注册" | 「重新发放入学码」（作废+重发，§10.4） |
| 视图 | 继承 edu_apply.view_edu_application_form | 插 2 个按钮 + 4 个只读展示字段 | 唯一 data 文件 |
| 模型 | edu.invite.code（_inherit） | +application_id、+unique、+发放/重发/回显方法 | 1 列 |
| 模型 | edu.application（_inherit） | +2 个按钮方法、+3 个**非存储**计算字段 | 0 列 |
| 迁移 | **无** | 存量行 application_id = NULL | 无需 migrations/ 目录 |
| ACL / ir.rule / 菜单 / 路由 / 演示数据 | **无新增** | — | — |
| 系统参数 | edu_admit_invite.valid_days（默认 14）、edu_admit_invite.register_url（默认 https://edu.example.org/register） | L1（仅 base.group_system 可改） | ⚠ **改完要让 web 进程重新读到**：从后台界面改，或用 shell 改完 docker compose restart web（`tg-invite-bot-design.md:404-411` 实测坑） |

### 12.4 权限挂层（四层口径，逐条声明"属于哪一层"）

| 面 | 层 | 依据 |
|---|---|---|
| 按钮 groups | **教务** group_op_back_office_admin + **开发者** base.group_system（并列） | `code-map.md:256-261` 第 12 条 |
| ORM 门禁 | 同一口径的**再判一次**：u.has_group('openeducat_core.group_op_back_office_admin') or u.has_group('base.group_system')（等价 roles.privileged_staff()，`roles.py:150-157`） | ⚠ **必需**：菜单 592「入学申请」**没有任何组限制**（本机 ir_ui_menu_group_rel 实测 0 行；它靠父菜单 300 的组限制被间接收窄），而 edu.application 的 ACL 给 base.group_user **只读**（ACL 1293）——只靠菜单层就是"看得见点不开"的反面：**看得见、点得动**。双层门禁缺一即死角 |
| 学生 / 家长 / 教师 | **不可达**（后台按钮） | 学生走门户 `/register`；教师不该发码 |
| ACL | **不改** | 教务对 edu.invite.code 全权（ACL 1408）、对 edu.application 读写（ACL 1403）⇒ 按钮要做的两件事都已授权 |
| 记录规则 | **不改**（既有全局规则 344 已允许教务操作 tier='student' 的码） | 本机 ir_rule id 344 |

---

## 13. 真机可验证的验收标准（可机读、可复现）

> 依据 `dev-workflow.md:99-148`：**升级 EXIT=0 ≠ 按钮能用**；**改了按钮/方法，必须有一条"打完就摸页面"的判据**；**探针不许跟随重定向**；**纯中文文案两边都不误报**。

**前置（缺一不可）**：① 无升级锁；② 容器 Up > 30s；③ 带 cookie 访问 `/web/login?db=edu19` 得 200/302/303；④ 按陷阱 1 确认最近没跑过 `-u edu_life`（若跑过，把增量单列）。

| # | 断言 | 怎么验（期望） |
|---|---|---|
| **A1** | 首装成功 | bash scripts/safe_upgrade.sh -i edu_admit_invite → **EXIT=0**、无 Traceback。⚠ -i 对**未装**模块有效；对已装模块必须 -u（`code-map.md:30`） |
| **A2** | schema 变更到位 | 查 information_schema.columns 出现 application_id 列 + 唯一约束（如 edu_invite_code_application_id_uniq）；select count(*) from edu_invite_code where application_id is not null; = **0**（存量不受影响） |
| **A3** | 入口可见性（四层） | 教务账号打开该申请表单 → 状态 admitted 时**看得见**按钮；state='new' 时**看不见**；**教师账号**打开同一 URL → 按钮不可见 / ORM 调用被拒（UserError/AccessError 都算通过，但**必须有明确人话**） |
| **A4** | **幂等（头号断言）** | 同一条申请**连点两次**：两次都得到**同一个码**；select count(*) from edu_invite_code where application_id=〈id〉; = **1**；select count(*) from mail_mail where model='edu.invite.code' and res_id=〈code_id〉; **不因第二次点击增加** |
| **A5** | 并发 | 同一申请**并行两个请求**：最终仍只有 1 张码、1 封邮件；另一个请求得到的是"正在发放/已发放"的人话，**不是 500**（若实施选了"唯一约束冲突则报人话"的降级口径，也在此断言） |
| **A6** | 邮件（**只能证到"已生成"**） | 有邮箱的申请：mail_mail **+1**，email_to == 申请邮箱，res_model='edu.invite.code'、res_id == 码 id。**本机无 SMTP ⇒ state='exception' 是预期**；**不得**把"已生成"写成"已送达" |
| **A7** | **无邮箱兜底** | 无邮箱的申请：按钮**可点**；页面出现码 + 「未填写电子邮箱…请电话告知」提示；mail_mail **不增加** |
| **A8** | 注册闭环（**真的走一遍**） | 用该码在 `/register` 注册一个【演示】测试邮箱 → ① 新 res.users（base.group_portal）；② 新 op.student（edu_pending_setup=True、user_id=新账号、名称带【待分配】）；③ 码 state='used'、used_login=测试邮箱、used_on 非空；④ 申请表单显示"已注册 + 注册邮箱" |
| **A9** | 一码一人 | 用**同一张码**再注册一次 → 判「该邀请码已被使用」，且**未**建第二个账号 |
| **A10** | 作废 / 重发 | 把码 expire_at 改到过去 → 注册被拒（「该邀请码已过期」）→ 点「重新发放入学码」→ 新码可用、**旧码仍不可用**、unique(application_id) 未报错（解绑+绑定顺序正确） |
| **A11** | **不碰 TG（边界断言）** | grep 证明新模块**不含** edu_telegram_outbox / edu_telegram. / `/telegram/webhook`；本功能前后 select count(*) from edu_tg_claim; **不变**；TG 池可用数**不变**；复跑 TG 的 V3（同 chat 再来 = 原码） |
| **A12** | 不改他人模块 | git diff --name-only **只含新模块目录 + 本文 + 脚本**；edu_portal / edu_apply / edu_tg_bind **0 改动** |
| **A13** | 门禁 | check_manifest_tracking.py（manifest 引用集 ⊆ git 跟踪集）、check_view_xpath.py（继承视图 xpath / 裸 < / 导入顺序）、check_english.py（动了用户可见文案）、check_odoo_trace.py、check_qweb_dict_foreach.py 全绿 |
| **A14** | 清场 | 测试申请 / 测试码 / 测试账号 / 测试学生档案**逐条删除**，残留 = 0（逐条 SELECT 自证） |

**反例（明确不允许的验收写法）**：
- ❌ 只跑升级 EXIT=0 就宣布"按钮能用"（`dev-workflow.md:131-137`：EXIT=0 只证明装载没炸）；
- ❌ 用**跟随重定向**的探针判"页面正常"（`dev-workflow.md:138-146`）；
- ❌ 把 mail_mail 行存在写成"邮件已送达"；
- ❌ 用**库里真实的 6 条申请**做发码演示（会真发邮件、真占码）；
- ❌ 用**生产**做任何一次点击。

---

## 14. 需要校长拍板的用户可见项（**6 项**）

| # | 拍板项 | 候选 | 本文建议 | 影响面 |
|---|---|---|---|---|
| **P1** | **按钮叫什么？** | (a)「**发放入学码**」；(b)「一键发放入学码」（校长原话）；(c)「发送入学注册码」；(d)「生成并发送入学码」 | **(a)** —— 简短、不暴露实现；"一键"是内部口径，界面上显得技术化。(c) 在"没邮箱"场景会误导（那时并不会发送） | 用户可见；改名成本 = 一行 string |
| **P2** | **邮件标题与正文** | 见下方草稿 | **照草稿**，标题用「【永约学坊】您的入学注册码」 | ⚠ **邮件一旦发出无法撤回**；品牌红线：只允许真实联系方式（`code-map.md:248`） |
| **P3** | **有效期多少天？** | 7 / 14 / 30 / 教务每次自选 | **14 天**（参数 edu_admit_invite.valid_days，可改） | 安全 × 体验的直接权衡；⚠ 不显式传值会落到模型默认 **7 天** |
| **P4** | **到期后是否自动再发一张？** | (a) 不自动，教务点「重新发放」；(b) 到期前 N 天自动重发 | **(a)** | (b) 需要 cron（本仓无先例、会静默延长暴露窗口） |
| **P5** | **没留邮箱的申请，允不允许发放？** | (a) 允许，页面回显 + 提示教务电话告知；(b) 不允许，直接报错让教务去补邮箱 | **(a)** | 库内 6 条申请**只有 1 条**有邮箱 ⇒ 选 (b) 等于功能对本校**大部分申请不可用** |
| **P6** | **是否加「注册邮箱 ≠ 申请邮箱」的告警？** | (a) 表单上高亮提示（不做拦截）；(b) 只显示不提示；(c) 不做 | **(a)** | 这是"误发/不是本人注册"的**唯一低成本发现手段**；本仓"提示而非拦截"的既有口径（`student-portal-home-profile-design.md:205`） |

**P2 草稿（邮件标题 + 正文，需校长逐句改）**：

> **标题**：【永约学坊】您的入学注册码
>
> **正文**：
> 亲爱的 〈姓名〉：
>
> 感谢您申请永约学坊。经审核，您已被录取。请使用下面的注册码开通您的学生账号：
>
> - **注册码**：〈CODE〉
> - **注册地址**：https://edu.example.org/register
> - **有效期至**：〈YYYY-MM-DD〉
>
> 注册步骤：打开上面的注册地址 → 填写邀请码、姓名、邮箱与密码 → 提交后即可登录学生门户。
>
> 这张注册码只发给您一人，请勿转发给他人。若您未曾申请或不需要该账号，请忽略本邮件。
>
> 如有疑问，请联系教务处：scrtsschool@gmail.com
>
> 永约学坊 教务处

---

## 15. 未查到 / 不确定（**不得当结论用**）

| # | 未验证项 | 为什么未验证 | 何时能验证 |
|---|---|---|---|
| 1 | **生产（马来西亚 prod-host）是否配了可用 SMTP** | 本机 ir.mail_server = **0 行**；生产只读核对需授权（本任务禁止碰生产） | 上线前：select id,name,smtp_host,active from ir_mail_server; + 发一封测试信 |
| 2 | **生产发信域名的 SPF/DKIM**（决定邮件进不进垃圾箱） | 同上 | 上线前，与 SMTP 一起 |
| 3 | try_lock_for_update() 在**后台按钮上下文**的实际行为 | 只读了源码（`odoo/orm/models.py:5592-5614`），**未在按钮里实跑** | 实施期 A5 |
| 4 | **消费侧的并发竞态**（同一张码被两个请求同时注册） | 需真建两个账号才能观察；**本设计不做** | 另立任务（属 edu_portal）；登记为发现 |
| 5 | 生产库的申请条数 / 邮箱覆盖率 | 本机 6 条、1 条有邮箱；生产未核对 | 上线前只读 SELECT |
| 6 | 邮件**送达率**与垃圾箱表现 | 本机无 SMTP，无法端到端 | 生产首封实测 |
| 7 | `/register` 页面对"我还没收到码"的用户提示是否够（可能需要一句引导） | 未查（属文案/门户范畴） | 实施期视校长意见 |
| 8 | 生产 edu_tg_bind 的码池是否已按 TGB-STU- 前缀建好 | edu_tg_bind 本地已装、**未部署生产**（`code-map.md:116`，设计 §12-1） | 与本设计无关，但 **T3 触发条件**需要它 |
| 9 | 是否需要在 op.student 档案上写"来源申请"（便于统计入学转化率） | 本设计**故意不做**（那会再加一列）；若校长要看转化率，可用 used_login + application_id 现成反查 | 校长提出时 |
| 10 | **第 2 步（外部调研）的一条缺口**：同类教务系统里「录取 → 自动开通账号（并发码）」的成熟做法（如校管家"报名学员转正式学员"）**未查到一手页面** | 本设计的调研依据是既有的 `docs/research/invite-code-tiers.md`（它已把"凭码注册"的外部先例查尽：Moodle 组码 / Canvas join code / 钉钉·企微·飞书 / 校管家）；**"报名转学员"这一段的同类证据仍是空白** | 若校长要求"零补录"（T4）**之前**补一次调研 |

---

## 16. 第 0 步：重复登记（台账）

本文按 `dev-workflow.md:54-55` 要求在 `docs/audit/deprecated-inventory.md` 的**变更记录**里**追加一行**（追加、不覆盖历史行）：

- **重叠对象**：本需求命中的"既有实现"**有两层**——① **承载物**（不是重复物）：`edu.invite.code` 邀请码体系 + `/register` 消费链路；② **一个需要否证的头部候选**：基座 openeducat_admission 的 **enroll_student() / get_student_vals()**（"录取 → 建 op.student → 建门户账号"，位置与命名都与本需求几乎相同）。
- **证据**：`openeducat_erp/openeducat_admission/models/admission.py:77-82`（状态机含 admission）、`:245-301`（建 res.users 只给 portal 且**无密码**；同建 op.student.course 含 batch_id）、`:303-387`（enroll_student；写学费与 op.subject.registration）、`views/admission_view.xml:51-52`（按钮 invisible="state != 'admission'"）；本机只读读数：op_admission **0 行**、op_admission_register **0 行**、ACL 不含教务组、参数 openeducat_admission.enable_create_student_user = **True**；edu_apply 侧状态机 `application.py:57-59`、邮箱非必填 `:41`；全仓命名查重 入学码｜录取码｜admission_code｜invite_link｜issue_invite = **0 命中**；base_automation 4 条**无一**命中申请模型。
- **裁定**：**复用**（承载物 = edu.invite.code + `/register` 链路）**+ 新建一个薄模块 + 新增 1 列**（edu.invite.code.application_id + unique）。**不复用基座 enroll_student() 的写路径**（R1 数据模型不兼容 / R2 本仓 0 数据且教务无 ACL / R3 它建出的账号无密码、仍解决不了"能登录" / R4 它会写本仓不认的学费与选课结构），**只借鉴它的字段映射口径**。
- **收口触发条件**：见 §8.5（T1 第三处发码场景 ⇒ 必须收口成统一发放记录表；T2 给码表加第三个来源字段；T3 TG 池前缀被改成能匹配 ADM-；T4 校长要求"点一下直接进班"；T5 edu_portal 码状态机被改动）。

---

## 17. 变更记录

| 日期 | 改动 | 责任 |
|---|---|---|
| 2026-09-18 | 建立本文（需求 C-3「录取后发放入学码」）：第 0 步查重（§3，7 路 + 负结论 + 对基座 enroll_student 的四条否证）、第 3 步读参考（§7 Q1–Q7）、第 4 步设计摘要（§8–§13）。裁定 **复用 + 1 列 + 薄模块**；码池结论 = **按需生成、不与 TG 共用**；无邮箱兜底 = **页面回显 + 教务自行转告**。**未写一行实现代码、未改 custom_addons/ 与 openeducat_erp/、未改库、未碰生产** | 设计子代理（C-3，`docs/plans/admission-invite-link-design.md`） |
| 2026-10-14 | 六项拍板落定（§18.1）+ 实施任务书（§18.2–§18.4）；新查实：本地与生产 `ir_mail_server` 均 0 行 ⇒ 邮件渠道按「页面回显 + 尽力而为」交付 | 调度者（用户访谈 6 问） |

---

## 18. 2026-10-14 拍板与实施任务书（本轮）

### 18.1 六项拍板（用户裁定，2026-10-14）

| # | 拍板项 | 裁定 |
|---|---|---|
| P1 | 按钮名 | **「发放入学码」** |
| P2 | 邮件标题与正文 | **照 §14-P2 草稿**（标题【永约学坊】您的入学注册码；正文含姓名 / 注册码 / 注册地址 / 有效期至；落款教务处 scrtsschool@gmail.com） |
| P3 | 有效期 | **14 天**（系统参数 `edu_admit_invite.valid_days`，默认 14；⚠ 不显式传值会落到模型默认 **7 天**，必须显式传） |
| P4 | 到期后 | **不自动重发**，教务点「重新发放入学码」 |
| P5 | 没留邮箱 | **允许发放**：页面回显码 + 提示教务电话/微信转告（选「不允许」会让本校大部分申请不可用） |
| P6 | 注册邮箱 ≠ 申请邮箱 | **表单高亮提示，不拦截** |
| Q6 | 邮件渠道（本轮新查实的事实） | 本地与生产的 `ir_mail_server` **实测均为 0 行**（2026-10-14）⇒ 本轮按「**页面回显 + 邮件尽力而为**」交付：`mail.mail.send(raise_exception=False)`，发信失败只落 `mail.mail` 记录与审计、不向教务报错；SMTP 配好后自动生效 |

### 18.2 实施边界（唯一改动面）

新建模块 `custom_addons/edu_admit_invite/`：
- `__manifest__.py`（depends: `edu_portal`；data 只含 `views/application_views.xml`）
- `__init__.py`、`models/__init__.py`
- `models/invite_code_ext.py`（`_inherit = 'edu.invite.code'`）
- `models/application_ext.py`（`_inherit = 'edu.application'`）
- `views/application_views.xml`（继承 `edu_apply.view_edu_application_form`）

**禁改**：`edu_portal/`、`edu_apply/`、`edu_tg_bind/`、`openeducat_erp/`、其它任何模块（A12 自证）。
**不新增**：模型 / 表 / 路由 / ACL / ir.rule / 菜单 / 演示数据 / `mail.template` 记录（§12.1）。

### 18.3 实施契约

- **唯一 schema 变更**：`edu.invite.code.application_id`（Many2one `edu.application`，ondelete='restrict'）+ `models.Constraint('unique (application_id)', …)`（Odoo 19 旧 `_sql_constraints` 会被静默忽略）。
- **按钮**：`edu.application.action_issue_admission_invite`（string=「发放入学码」）与 `action_reissue_admission_invite`（「重新发放入学码」）；`type="object"`；`groups` = 教务 `openeducat_core.group_op_back_office_admin` + `base.group_system`；`invisible` 口径：发放 = `state != 'admitted'`，重发 = 未发过码 或 已注册。
- **ORM 门禁再判一次**（菜单 592 无组限制、`edu.application` 对 `base.group_user` 只读 ⇒ 只靠视图 groups 会「看得见点得动」）：方法体内 `u.has_group('openeducat_core.group_op_back_office_admin') or u.has_group('base.group_system')`，不满足 → `UserError`（文案「只有教务处或系统管理员可以发放入学码。」）。
- **方法内顺序固定**（§12.2）：门禁 → 幂等快路径（已绑码则回显，不新建）→ `try_lock_for_update()` → `create`（`unique(application_id)` 兜底）→ `edu.audit.log._log(...)` → **仅当本次真新建**才出网（有邮箱才发）→ `display_notification` 把码与投递结果念给教务。
- **码参数**：`code_kind` / `tier` 取学生层级既有取值（照 `invite_code.py:129-135`）、`use_limit=1`、`expire_at = now + valid_days 天`（显式传）、`note` = 「入学申请 〈申请编号/姓名〉」、`application_id` = 本申请；码文本走既有 `create()` 的生成与守卫（**不得**用连号/可推导码）。
- **重发（§10.4）**：旧码 `expire_at` 改到过去 + **先把旧码 `application_id` 置 NULL 再建新码**（否则撞 `unique(application_id)`），审计记两条。
- **撤销**：就是把 `expire_at` 改到过去，**不新增状态**；边界 = 作废不回收已注册账号。
- **邮件**：不建 `mail.template`，Python 组装标题/正文 HTML（照 `edu_portal/controllers/main.py:102-115`）；`send(raise_exception=False)`；投递结果（建了几封 / 失败原因）进 `display_notification` 与审计 detail。
- **无邮箱**：不发信、不建 `mail.mail`，只回显码 + 提示「该申请没留邮箱，请电话/微信告知」。
- **表单常驻展示**（非存储计算字段反查码行）：入学码 / 发放时间（`create_date`）/ 发放人（`created_by`）/ 注册邮箱（`used_login`）/ 已注册（`used_on`）；P6 = 当 `used_login` 非空且 ≠ `application.email` 时高亮提示（不拦截）。
- **留痕**：`edu.audit.log._log(action, model, res_id, res_name, detail)`（`custom_addons/edu_portal/models/audit.py:29`）。
- **系统参数**：`edu_admit_invite.valid_days`（默认 14）、`edu_admit_invite.register_url`（默认 `https://edu.example.org/register`）。

### 18.4 验收映射（探针由调度者写：`tests/smoke/admit_invite_gate.py`）

| 段 | 断言 |
|---|---|
| A1 | 点「发放入学码」→ `edu.invite.code` +1、`application_id` 绑定、`use_limit=1`、`expire_at ≈ now+14d`、码文本非连号 |
| A2 | 再点一次 → **回显同一张码**、行数不变、不新建 |
| A3 | 并发兜底：直接 create 第二张同 `application_id` 的码 → `IntegrityError`（DB 唯一约束真的在） |
| A4 | 有邮箱 → 生成 1 封 `mail.mail`；无 SMTP 时**不向教务抛错**（通知里如实写投递结果） |
| A5 | 无邮箱 → 不建 `mail.mail`、页面回显码 + 提示转告 |
| A6 | 表单常驻显示码 / 发放时间 / 发放人 / 注册邮箱 / 已注册 |
| A7 | 学生 / 教师 / 家长身份调用按钮方法 → `UserError`（ORM 门禁）；视图 `groups` 同步 |
| A8 | `used_login ≠ application.email` → 高亮提示且**不拦截** |
| A9 | 「重新发放入学码」→ 旧码 `expire_at` 已过期且 `application_id` 解绑、新码生成、审计两条 |
| A10 | 撤销 = `expire_at` 改到过去；已注册账号不受影响 |
| A11 | 不碰 TG：`edu_tg_claim` 行数与 TG 池可用数前后不变 |
| A12 | `git diff --name-only` 只含新模块目录 + 本文 + 探针脚本 |
| A13 | 门禁：`check_manifest_tracking` / `check_view_xpath` / `check_view_selector_attrs` / `check_english` / `check_odoo_trace` / `check_ui_surface` / `check_docs_index` 全绿 |
| A14 | 清场：测试申请 / 测试码 / 测试账号 / 测试学生档案逐条删除，残留 = 0 |

**反例（不允许的验收写法）**：照 §13 末尾四条 —— 只跑升级 EXIT=0 不算能用；不得用跟随重定向的探针；`mail_mail` 行存在 ≠ 邮件已送达；**不得用库里真实的申请做演示**（会真发邮件、真占码）；**不得碰生产**。

### 18.5 实测（2026-10-14，本地 `edu19` 栈）

**结论**：`tests/smoke/admit_invite_gate.py` **54 / 54 PASS**（跑完自还原：测试申请 0 / 测试码 0 / 探针邮件 0 残留）；7 张静态门禁全绿；`safe_upgrade.sh edu_admit_invite` 无失败特征。**2026-10-14 已部署生产**（见 §18.6）。

### 18.6 生产部署（2026-10-14）—— 以及部署脚本的一个静默漏洞

**正确的首装命令**：`ACTION=-i bash scripts/deploy_myedu.sh edu_admit_invite`（新模块必须 `-i`，`-u` 对 `state!='installed'` 的模块什么都不做）。
部署通过：升级无失败特征 → web 已重启就绪 → 匿名冒烟全绿 → 活体注册表 **117/117 LIVE，0 DARK**（扫描面 15 个模块，已含本模块）。

生产核对（逐条实测）：`ir_module_module.state='installed'`；`edu_invite_code.application_id` 列存在（1）；唯一索引 `edu_invite_code_edu_admit_application_uniq` 存在；继承视图 `edu.application.form.admit.invite` 在库（1）；`edu.application` 的 `invite_*` 字段 6 个；4 个模块文件 md5 本地=远端逐一相同（`application_ext.py` `daa7c7af3ac7615236b2c602f907a977`、`application_views.xml` `882aa5346a49abf51f969aa1ef4d7b16`、`invite_code_ext.py` `d951c136cad134a7c919dabba1a5e18d`、`__manifest__.py` `013db1d65d628aaa373a075e4fa92337`）。未在生产创建任何真实入学码。

**漏洞（第一次「部署通过」其实什么都没发生）**：首跑 `bash scripts/deploy_myedu.sh edu_admit_invite`（默认 `-u`）报了「部署通过」，但生产上 `/opt/edu-app/custom_addons/edu_admit_invite` **目录都不存在**、列 0、视图 0 —— 两个独立原因叠加：① `deploy_myedu.sh` 的 rsync 清单是**手写死列表**，没有本模块 ⇒ 文件没同步；② `-u` 对未安装模块是空操作 ⇒ 升级「无失败特征」。
**已修**：`scripts/deploy_myedu.sh` 把 rsync 清单提成 `SYNC_MODULES` 变量并加**硬守卫** —— `MODULES` 里任一模块不在清单内（或本机无该目录）**跑之前就 exit 2**，不再假装成功。另记两条硬约束（与 `edu_nav` 同源）：本模块视图 `ref` 了 `edu_apply.view_edu_application_form` ⇒ **绝不能与 `edu_apply` 放进同一个 `-u` 批次**（那一刻 `edu_apply` 是 `to upgrade`，`convert.py:242 _test_xml_id` 的断言会失败）。

| 段 | 实测读数 |
|---|---|
| A0 | `edu_invite_code.application_id` 列 1、唯一索引 1 |
| A1 | 点按钮 → 码 +1、`application_id` 绑定、`use_limit=1`、`expire_at ≈ now+14d`（`EDU-EB5PV4`）、`note='入学申请 探针-mail'` |
| A2 | 再点 → 行数不变、**回显同一张码**（`EDU-EB5PV4`） |
| A3 | 手工 `create` 第二张同 `application_id` → `psycopg2.errors.UniqueViolation`（`edu_invite_code_edu_admit_application_uniq`）⇒ DB 兜底真的在 |
| A4 | 有邮箱 → `mail.mail` +1 且 `state='exception'`（本机 `ir.mail_server` 0 行，如实落库）、按钮**未抛错** |
| A5 | 无邮箱 → 不建 `mail.mail`、码仍生成、回显含「该申请没留邮箱，请电话/微信告知」 |
| A6 | 表单常驻 6 字段（码 / 发放时间 / 发放人 / 注册邮箱 / 已注册 / 邮箱比对）；两个按钮 `groups` 限教务+系统组 |
| A7 | `stu@local` / `faculty@local` / `parent@local` 调用 → `UserError`「只有教务处或系统管理员可以发放入学码。」；码数不变 |
| A8 | 写 `used_login` 成功（不拦截），表单出现比对提示 |
| A9 | 重发 → 旧码解绑 + 过期、新码生成（≠旧码）、审计 ≥ +2 |
| A10 | `expire_at` 改到过去即撤销；未新增 state 取值 |
| A11 | `edu_tg_claim` 0 行、TG 池可用数不变（**未与 TG 池共用**） |
| A12 | 改动面 = 新模块 + 本文 + 探针 + `check_view_xpath.py`（另有**并发另一路** TG 助手改动，按前缀排除） |
| A13 | `check_manifest_tracking` / `check_view_xpath`(r19) / `check_view_selector_attrs` / `check_english` / `check_odoo_trace`(52 路由) / `check_ui_surface` / `check_docs_index` 全部 exit 0 |
| A14 | 残留 0 / 0 / 0 |

**口径订正 3 条（实现与验收期发现，设计稿原文作废）**：
1. **「先解绑再建新码」光有顺序不够** —— ORM 的 `create` 不保证先把上一条 `write` 的 UPDATE 刷到 DB，实测会撞 `unique(application_id)`（`DuplicateKey`）。修法 = `old.write(...)` 后显式 `old.flush_recordset(['application_id'])`。已并入 `docs/code-map.md` §6 第 22 条。
2. **`mail_mail` 在 Odoo 19 没有 `subject` 列**（主题在 `mail_message` 上）⇒ 任何「按主题筛/删 `mail_mail`」的探针或脚本都写不出来；探针改用 id 区间。
3. **重发后的旧码 `application_id` 为空** ⇒ 清场/统计若只按 `application_id` 找码会漏掉它（探针 A14 已按「申请 ∪ 码 id」两路删）。

**未做/挂起**：① 生产 `ir.mail_server` 仍 0 行 ⇒ 邮件渠道只能证到「已生成」，见 README 第 118 行挂起项；② 未在生产创建任何真实入学码（生产 3 条申请全部 `state='new'`，按钮 invisible，暂无载体）；③ `hindsight_capture_initiative` 因 API 402 未写入记忆库。
