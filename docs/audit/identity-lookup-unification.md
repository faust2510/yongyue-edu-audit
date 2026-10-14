# 由 user 反查身份档案：口径统一（审计 + 施工 + 待办）

> 2026-09-18。管辖范围：全仓 `custom_addons/**`（不含 `openeducat_erp/`，**不含**
> `custom_addons/edu_telegram/` —— 生产上那个同名模块是匿名意见箱，红线，只列不改）。
> 验收脚本：`tests/smoke/identity_lookup_unification.py`（读数落
> `tests/smoke/identity_lookup_unification_results.json`）。

---

## 0. 一句话结论

本仓「静默失效」的共同根因是**同一个反查被写成了两套口径**：一套只认记录自身的
`user_id`（= 本仓既有写入口径，教师那列其实是 Odoo 的「销售员」列），一套只认
Odoo 19 的规范反向 `res.users.partner_id → res.partner.user_ids`。凡只走其一的地方，
都会在「另一种方式建的账号」上**静默解析不出身份**（页面 200、内容是空的）。

本轮把口径收敛成**一处实现**：`custom_addons/edu_schedule/models/identity.py`
（双向并集、①优先①落空才查②、只加不减），并把四处高危接入它。

---

## 1. 根因（一手证据）

| 事实 | 出处 |
|---|---|
| `res.partner.user_id` 是**销售员**字段，**不是** `res.users.partner_id` 的反向 | core `res_partner.py:229-236`（原文："Warning: user_id is a Salesperson, not the inverse of partner_id in res.users."） |
| 它只由 `_compute_user_id` 从 `parent_id` 同步 ⇒ **程序化 `create res.users` 不回填** | core `res_partner.py:419-423` |
| 规范反向是 `res.partner.user_ids`（one2many → `res.users.partner_id`） | core `res_partner.py:287` |
| `partner.user_ids` **只返回在用账号** | core `res_partner.py:864` 注释 |
| `op.faculty` 没有自己的 `user_id` 列：`_inherits={"res.partner": "partner_id"}`，`user_id` 实际是 `related='partner_id.user_id'`（`store=False`） | 基座 `openeducat_core/models/faculty.py:29,58`；容器内实测 `_fields['user_id'] = related partner_id.user_id, store=False, string='Salesperson'` |
| `op.student.user_id` / `op.parent.user_id` 是**独立存储列**（不是伙伴的派生） | 基座 `student.py:92`；`openeducat_parent/models/parent.py:31`（`op.parent` 的伙伴字段是 `name`，`:29`） |
| 「(user_id, '=', uid)」与「(partner_id.user_id, '=', uid)」对 `op.faculty` **逐字生成相同 SQL** | 本容器 odoo shell 实测：全库 10 个用户逐条比对，两域名的 `search_count` **0 处不一致** ⇒ messages.py 原注释里的「双口径兜底」是同义反复 |

实测复现（本轮夹具，改前）：

```
# 脚本新建教师账号（create res.users 不回填 partner.user_id）
partner 120: user_id=NULL, res.users.partner_id → 1 个账号
op.faculty.search([('user_id','=',该账号)])           → 0 条   （链①落空）
op.faculty.search([('partner_id.user_ids','in',[uid])]) → 1 条   （链②命中）
```

---

## 2. 全仓清点（自行重扫，非照抄）

**扫描范围**：`custom_addons/**/*.py`（1 个 `test` 子目录、13 个自研模块 + `seed_*/fix_*`
脚本）。**方法**：两遍静态扫描 ——
① 域名扫描：所有 `search/search_count` 调用的域名/上下文里出现 `user_id|user_ids|uid`，
且目标模型是身份模型（`op.student` / `op.faculty` / `op.parent` / `hr.employee`）；
② 别名感知：`Stu = env['op.student'].sudo()` 这类别名（否则会漏掉 `Stu.search(...)`）；
③ 补扫正向（档案→账号）：`.partner_id.user_id` / `.name.user_id` / `.emp_id.user_id` /
`mapped('user_id')`。
**未找到**：`openeducat_erp/`（基座只读，未扫）；`edu_telegram/tests/` 只登记不改。

### 2.1 本轮已修（9 个文件 / 20 个代码点）

| 文件:行（改后） | 用途 | 原口径 | 现口径 |
|---|---|---|---|
| `edu_schedule/models/identity.py`（**新**） | 公共 helper（唯一实现） | —— | 反查：①→②；正向：①∪②∪伙伴 `user_ids` |
| `edu_schedule/models/session_ext.py:275`（原 271） | 课节学生收件人 | 链① | 双向并集 |
| `edu_schedule/models/session_ext.py:287`（原 280-281） | 任课教师收件人 | 链① | 双向并集 |
| `edu_schedule/models/session_ext.py:332`（原 326） | 课前提醒 Telegram 分支的教师判定 | 链① | 双向并集 |
| `edu_schedule/models/session_ext.py:568`（原 562-563） | 影响面角色标注 | 链① | 双向并集 |
| `edu_schedule/models/session_ext.py:901`（原 895-896） | 批量停用的教师判定 | 链① | 双向并集 |
| `edu_portal/controllers/ical.py:67-69`（原 59-62） | ICS 订阅视角（学生/教师/家长） | 链①×3 | 双向并集×3 |
| `edu_portal/controllers/messages.py:86-88`（原 79-93） | 私信「已挂身份的账号集」 | 链① | 双向并集 |
| `edu_portal/controllers/messages.py:167/185/193`（原 196 / 211-212 / 220-221） | 账号资料卡身份判定 | 链①（教师/家长那两条是**同义反复**） | 双向并集 |
| `edu_portal/models/fees.py:265/271/272/273`（原 258-267） | 报销收据可见性 | 链①（`partner.user_id`） | 双向并集 |
| `edu_portal/controllers/roles.py:188`（原 186-191） | `current_student/faculty/parent` | 双向并集（自建一套） | 薄壳 → 公共 helper |
| `edu_portal/controllers/main.py:25`（原 16-17） | `current_student()`（学生侧 13 个控制器共用） | 链① | 薄壳 → 公共 helper |
| `edu_assess/controllers/portal.py:103/112`（原 99-115） | 评估侧 `_current_student/_current_faculty` | 链① / 双向（各自一套） | 薄壳 → 公共 helper |
| `scripts/fix_teacher_user_backlink.py`（整篇） | 补 `partner.user_id` 的脚本 | **无占用守卫（会顶掉别人）** | 已占用则跳过 + 告警 + 两链分别复核 |

> `messages.py` 的 `_faculty_user_id`（原 111-118，「双口径兜底」）本轮**直接删除**：
> 它逐字查的是同一列，留着只会诱使下一轮再抄一遍。

### 2.2 待办清单（未改，按风险分批）

风险口径：**A=写入前置守卫**（漏 ⇒ 一人多号 / 身份被抢，属数据正确性）；
**B=门户身份解析**（漏 ⇒ 页面静默空表）；**C=群体解析**（漏 ⇒ 通知/可见列表少人）；
**D=脚本/种子**（只影响本地造数）。

| # | 文件:行（当前） | 用途 | 现走 | 风险 | 建议批次 |
|---|---|---|---|---|---|
| 1 | `edu_portal/models/invite_code.py:296-300` | 绑人码注册前的「该人员已绑账号」判定 | 链① + `partner.user_id`（**都是链①那一条**） | **A/高** | 批次 1 |
| 2 | `edu_portal/controllers/contacts.py:375-379` | 通讯录重绑的「一人一挂」守卫（写 `partner.user_id`/`user_id`，见 :385-389） | 同上（链①） | **A/高** | 批次 1 |
| 3 | `edu_portal/controllers/downloads.py:118/148/149` | 资料可见范围（家长/学生判定） | 链① | B/中 | 批次 2 |
| 4 | `edu_portal/controllers/batch2.py:502/715/820/1916/1925/1993` | 首页/工作台「是不是家长」判定 | 链① | B/中 | 批次 2 |
| 5 | `edu_portal/controllers/evaluation.py:38` | 评教：当前学生 | 链① | B/中 | 批次 2（可直接换 `main.current_student`） |
| 6 | `edu_portal/models/lms.py:56` | 课程学习：当前学生 | 链① | B/中 | 批次 2 |
| 7 | `edu_life/controllers/life.py:53/59` | 打卡/周记：学生 / 教师 | 链① | B/中 | 批次 2（需给 edu_life 加 `edu_schedule` 依赖） |
| 8 | `edu_quiz/controllers/portal.py:13` | 测验：当前学生 | 链① | B/中 | 批次 2（需加依赖） |
| 9 | `edu_public/controllers/main.py:267` | 公开页里的学生视角 | 链① | B/中 | 批次 2（需加依赖） |
| 10 | `edu_eval/controllers/eval_portal.py:28` | 行政评估：当前学生 | 链① | B/低 | 批次 3（模块已退役，见 code-map） |
| 11 | `edu_assess/models/assess.py` 的 `ResUsers._compute_edu_taught_batch_ids` | 评估模型内按 user 反查教师 | 链① | B/低 | 批次 3 |
| 12 | `edu_schedule/models/session_ext.py:327` | 课前提醒里「该账号是哪个学生」（Telegram 会话映射） | 链① | C/低 | 批次 3（identity 已 import，2 行） |
| 13 | `edu_portal/controllers/contacts.py:216-222/261-263/270-275` | 通讯录「已挂身份的账号」名单 | 链① | C/中 | 批次 3 |
| 14 | `edu_portal/models/notice.py:116-118` | 公告收件人（学生/家长） | 链①(`.mapped('user_id')`) | C/中 | 批次 3 |
| 15 | `edu_portal/models/downloads.py:154-163` | 资料「可见范围」收件人 | 链① | C/中 | 批次 3 |
| 16 | `edu_life/models/checkin_type.py:184`（该文件当前有**他人未提交改动**，行号以落盘版本为准） | 按 `user_id.login='stu@local'` 找学生（种子/初始化） | 按登录名（另一种口径） | D/低 | 批次 4 |
| 17 | `scripts/fix_user.py:13`、`scripts/seed_batch1.py:36`、`seed_batch2.py:28`、`seed_batch3.py:29`、`seed_demo.py:52`、`seed_tg_users.py:19/29` | 本地种子/夹具按 `user_id` 反查学生/家长 | 链① | D/低 | 批次 4（可选；只影响本地造数） |
| 18 | `edu_portal/models/registration.py:384-386` | 新学生注册通知「旧班+新班任课教师」 | **已是双向**（`user_id` ∪ `partner_id ∈ partners`） | 无 | 批次 4（换成 helper 只为统一写法） |

> 批次 2/3 里 `edu_life` / `edu_quiz` / `edu_public` 不在 `edu_schedule` 的依赖闭包内，
> 需要**加 manifest 依赖 `edu_schedule`**（先例：`edu_portal` 本就依赖它），
> 不要就地复制 helper —— 复制出来的一定是第二套口径。

### 2.3 只列不改（红线：`custom_addons/edu_telegram/`）

生产上该模块是**匿名意见箱**，与本仓同名模块不是同一个东西。以下同类反查**只登记**：

| 文件:行 | 内容 | 口径 |
|---|---|---|
| `edu_telegram/models/binding_code.py:52-53` | 按 user 找学生 | 链① |
| `edu_telegram/models/binding_code.py:56-58` | 按 user 找家长 | 链① ∪ `name.user_id`（`op.parent.user_id` 存储列 + 伙伴销售员列，**仍漏 `name.user_ids`**） |
| `edu_telegram/models/binding_code.py:61-63` | 按 user 找教师 | `emp_id.user_id` ∪ `partner_id=`（**按 partner 相等**，不是按登录账号 —— 与 `res.users.partner_id` 等价，属链②） |
| `edu_telegram/controllers/portal.py:13-21` | 绑定码列表 | 链① 为主 |
| `edu_telegram/controllers/portal_ops.py:11/16/17` | 学生/教师/hr.employee | 链① |
| `edu_telegram/tests/test_commands.py:16` | 测试夹具 | 链① |

---

## 3. 实现形态裁定：**抽公共 helper**，落点 `edu_schedule/models/identity.py`

**为什么不是就地改**：本仓已经因为「各写一套」踩过两次（通知 0 收件人 / 教师课表落成
访客空表），就地改只会让第 21 处继续长出来。本轮已把 `roles.py` 的 `_profile_of_current_user`、
`main.py` 的 `current_student`、`edu_assess` 的两个 `_current_*` 全部改成**薄壳**，
确保「一处实现、多处薄壳」。

**为什么不放 `roles.py`**（题面担心的成环，确实成立，且不止一层）：

1. **方向倒挂 + 真成环**：需要它的还有**模型层**（`edu_schedule/models/session_ext.py`、
   `edu_portal/models/fees.py`）。模型 import 控制器 = 「模型 → 控制器」的环；控制器模块
   import 期还会注册路由（`@http.route`），装载顺序一变就是路由表缺项。
2. **模块级死锁**：`edu_portal` 依赖 `edu_schedule`（manifest 明写），`edu_schedule`
   **不依赖** `edu_portal` ⇒ `session_ext.py` 永远不可能 import `edu_portal.controllers.roles`。

**落点方案（选定）**：`custom_addons/edu_schedule/models/identity.py`
—— 理由只有一个，但决定性：**它同时位于 edu_portal 与 edu_schedule 的依赖闭包里、且不被
edu_portal 依赖**，是唯一无环的公共落点。本仓已有同型先例（`edu_portal/controllers/
scheduling.py`、`calendar.py` 直接 `from odoo.addons.edu_schedule.models.week_utils import ...`）。

**曾被否掉的替代方案**：新建 `edu_identity` 模块（语义最干净）—— 需要生产端多装一个
模块（`deploy_myedu.sh` 的模块清单、安装顺序、回滚都要跟着改），而本轮**不许部署**，
把一个「只有 helper」的新模块塞进部署链是把风险转移给队长；留作后续可选（若第 2 批要把
`edu_life/edu_quiz/edu_public` 也并进来，再评估）。

**API**（细节与边界见模块 docstring）：
```python
profile_of_user(env, model, uid=None)      # 反查：①→②，至多 1 条
student_of_user / faculty_of_user / parent_of_user(env, uid=None)
users_of_partner(partners)                 # 伙伴 → 账号：user_id ∪ user_ids
users_of_profile(profiles)                 # 档案 → 账号：自身 user_id ∪ 伙伴 user_id ∪ 伙伴 user_ids
user_of_profile(profile)                   # 档案 → 单个账号（①优先）
```

**只加不减的形式保证**：反查里链②**只在链①落空时**才查 ⇒ 链①有命中的账号结果一字不变；
正向是并集 ⇒ 收件人/可见名单只会变多。全库回归矩阵（10 个账号 × 3 个身份模型，
改前 vs 改后）实测 `changed = []`。

---

## 4. 四处高危：修复前后读数

夹具（真实形态，非人造简化）：**既有 `op.faculty` 档案 + 脚本新建的登录账号**
（`create res.users` 仍不回填 `partner.user_id`，链① 空、链② 命中）；
另加一个「脚本新建的学生账号」（`op.student.user_id` 空、只走链②）+ 一张挂在教师档案上的应付单。

| 高危点 | 改前 | 改后 |
|---|---|---|
| **session_ext｜课前提醒/改课通知**（sid=746，batch 12 该班无学生账号） | 收件人 **0 人**；`_notify_session_change()` → `sent=0, total=0`（静默不发） | 收件人 **1 人**（=该教师账号）；`sent=1, total=1, failed=0` |
| session_ext｜有学生的批次（sid=844，batch 8） | 收件人 1 人（只有学生 8） | 收件人 **3 人**（学生 8 + 夹具学生 + 夹具教师账号），改前每一位仍在（逐 id 断言） |
| session_ext｜既有教师课节（sid=756，回归对照） | 2 人 [8, 11] | 3 人 [8, 夹具学生, 11] —— 既有 8/11 一位不少，新增的那位是夹具学生（链②），符合「只加不减」 |
| **ical｜教师 ICS**（token 反查） | HTTP 200，`BEGIN:VEVENT` = **0**（**空日历**：身份落成 `guest`，课程/考试事件全不发） | 200，**231** 个 session 事件（= 该教师窗口内课节数） |
| **ical｜学生 ICS** | 200，0 个事件 | 200，**41~42** 个 session 事件（= 该班在 14 天回看窗口内的课节数，随运行时刻 ±1） |
| **messages｜学生发起对话选择器** | 3 个联系人，**不含**该教师（`_faculty_user_id` 恒 0） | 4 个联系人，**含**该夹具教师账号 |
| messages｜管理员私信名单 | 4 人，不含该教师 | 6 人，含该教师（资料卡角色 = 教师） |
| **fees｜收据可见性**（挂在教师档案上的应付单） | 该教师账号 `_user_can_view_receipt()` = **False** | **True**；同单以学生账号访问仍 False（不越权）；既有账号×既有账单矩阵 24 条逐条一致 |

---

## 5. 两条特别验证（题面指定）

1. **课前提醒/改课通知的收件人数不再为 0**（教师账号由脚本新建的夹具）：
   **0 人 → 1 人**；`_notify_session_change` 由「不发」变成 `sent=1 / total=1 / failed=0`；
   有学生的课节 **1 → 3 人**（学生 8 一位没少）。
2. **ical 教师/学生的 ICS 能出内容**（同一夹具）：教师 **0 → 231** 个课程事件，
   学生 **0 → 41~42** 个课程事件（改前两个都是「200 + 空日历」）。

---

## 6. 验证方法（可重跑）

```bash
# 1) 夹具（幂等；跨升级存活）
python3 tests/smoke/identity_lookup_unification.py setup
# 2) 改码前读数（必须在改动之前跑，否则没有对照）
python3 tests/smoke/identity_lookup_unification.py measure --tag before
# 3) 改码 + 升级
bash scripts/safe_upgrade.sh edu_schedule,edu_portal,edu_assess
# 4) 改码后读数（同夹具）
python3 tests/smoke/identity_lookup_unification.py measure --tag after
# 5) 清场（残留 = 0；基线比对）
python3 tests/smoke/identity_lookup_unification.py teardown
```

覆盖的断言：静态（helper 存在且四处已接入、旧口径片段为 0）、`session_ext` 收件人
（含逐 id 的「只加不减」）、ICS 事件数、私信可见性、收据可见性（含既有矩阵逐条一致）、
**全库账号 × 3 身份模型的回归矩阵（changed = []）**、清场残留 = 0 与「既有数据一行未少」。

读数：`tests/smoke/identity_lookup_unification_results.json`
（`phases.before` / `phases.after` / `phases.verify` / `phases.teardown`）。

**可复现性**：`after` 与 `verify` 是**多轮独立夹具**（每轮重建、每轮清场）跑出的同一组断言，
读数一致（教师 ICS 231、无学生课节收件人 1、私信可见性、收据可见性全同；学生 ICS 42→41
的差异来自 14 天回看窗口随运行时刻平移，非行为差异）。
`verify` 轮另加 **helper 单元探针**：学生/教师/家长三个模型都实测「链① 空 → 链② 命中，
且正向并集能把账号找回来」，并实测「链① 有命中时仍以链① 为准（优先不反转）」。

其它回归证据：`tests/smoke/silent_failure_fixes.py` **17/17 PASS**、
`tests/smoke/c1_impact_notify.py` **38/42 PASS**（4 项失败均为截图登录态与
`check_odoo_trace` 的既有 `mail.template` 数据面，与本次改动无关）。

---

## 7. 本轮没做 / 偏差 / 不确定

- **只接入了 4 处高危 + 2 处同义实现**（`roles.py`/`main.py`/`edu_assess`），
  余下 18 组在 §2.2 待办里；**没有**全仓一次改完（题面要求「剩余列清单分批」）。
- `edu_life` / `edu_quiz` / `edu_public` / `edu_eval` / `edu_assess(models)` 目前
  **不在** `edu_schedule` 依赖闭包内 ⇒ 批次 2 需要动 manifest（本轮未动）。
- `scripts/fix_teacher_user_backlink.py` 选择「**加守卫**」而不是删除：它做的只是
  「补回填、不改密码」，与 `create_teacher_account.py`（会重置密码）用途不同；
  加守卫后两者都不会抢占别人的教师身份。
- 「`partner.user_ids` 只返回在用账号」是有意保留的边界：停用账号若挂在链①上仍会被
  并集带出，属「只加不减」的必然结果，未做额外过滤（未验证停用账号在真实业务下的影响）。
- 本轮**未部署生产**，**未改** `openeducat_erp/`、`custom_addons/edu_telegram/`。
- 本轮在 `docs/code-map.md` §6 追加了第 13 条硬约定（身份反查只有一条口径），
  指向本文件与验收脚本；**未**改其它文档。
- `-u edu_portal` 会触发已知的 F1（菜单收口值重放，见
  `docs/audit/finding-F1-menu-replay-on-upgrade.md`）——那是既有问题，本轮升级同样触发了
  收口守卫（日志：`[edu_nav] 菜单收口守卫：声明改写 357 条`），未做额外处置。
