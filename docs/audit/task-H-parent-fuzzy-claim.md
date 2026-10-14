# 任务 H 报告：基座「模糊搜索把无关联系人认领成家长」的数据污染缺陷（含同段相邻两处）

> 覆盖文件：`custom_addons/edu_portal/models/parent_link_fix.py`（**在任务 G 的同一文件里接着改**，未新建第二个覆盖同一方法的文件）
> 对照/断言脚本：`tests/smoke/parent_link_identity.py`（新增，红→绿同一份脚本）
> 平台：本地 edu19（Odoo 19.0-20260817 + openeducat_parent 19.0.1.0 + edu_portal 19.0.2.0.0）｜日期：2026-09-17
> 基座快照只读未改一个字节：行号均指 `openeducat_erp/openeducat_parent/models/parent.py`（236 行）。
> **本文区分「实测」与「推断」；每条改动的依据都能指到脚本里的一条读数。**

---

## Symptom（实测）

| # | 路径 | 现象 |
|---|---|---|
| ① | `op.parent.create({...})` 且 **不传 email/mobile** | 命中「该字段为空的任意伙伴」⇒ 无关联系人被写 `is_parent=True`、被回填手机号、`op.parent` 挂到它身上（**持久污染**）；同一库里第二次再撞 `unique(name)` → `UniqueViolation` |
| ② | `op.student.write({'user_id': ...})`（家长 `op.parent.user_id` 与 `name.user_id` 不同） | 学生账号挂到**别的账号**上；家长真正的登录账号拿不到关联（或基座写入目标为空 ⇒ 静默丢失） |
| ③ | 同上，家长 `op.parent.user_id` 为空、`name.user_id` 有值 | 起点读到**空列表**再整体 `[(6,0,...)]` 回写 ⇒ 那个账号**原有其它孩子被清空** |
| ④ | `op.student.unlink()`（同型读写错位） | 清理落到**别的账号**：家长真正账号留下**已删学生的僵尸关联**，另一个账号的孩子被整体清空 |

## Reproduction（实测，改前原文）

同一份脚本 `tests/smoke/parent_link_identity.py` 在**改前**跑：**PASS 6 / FAIL 13**（13 条 FAIL 即复现）。关键原文：

```
读数 | ① 前置：canary（无关联系人） | id=481 name='!。【临时·冒烟H】无关联系人（无邮箱无电话）' email=False phone=False is_parent=False
读数 | ① 前置：基座那条搜索会命中谁（同域 limit=1） | id=481 name=…（≠ 请求的 '【临时·冒烟H】张三A'）
读数 | ①-A 建成后 op.parent 指向 | op.parent id=69 → 伙伴 id=481 name='!。【临时·冒烟H】无关联系人…'
读数 | ①-A canary 读数（污染后） | is_parent=True phone='13100000001'
FAIL | ①-A 没有把无关联系人认领成家长（op.parent 指向请求的名字）
FAIL | ①-A 无关联系人未被标记 is_parent（既有伙伴的 is_parent 集合不变） | canary.is_parent=True ｜ 既有伙伴中 is_parent 3→4
FAIL | ①-A 无关联系人 phone 未被回填 | canary.phone='13100000001'
FAIL | ①-B 第二次空条件 create 不撞 unique(name) | UniqueViolation: duplicate key value violates unique constraint "op_parent_unique_parent"
FAIL | ①-C 三条搜索都为空：不误认任意伙伴 | 新增 is_parent 伙伴=[3] ｜ op.parent id=71 → 伙伴 'Administrator'
FAIL | ②-A 按 email 认领到正确的伙伴 | op.parent.name='Administrator'（应为 '【临时·冒烟H】邮箱认领·伙伴'）
FAIL | ②-B 按 name 认领到同名伙伴（不新建重复伙伴） | UniqueViolation: …
读数 | ③ 写入后 child_ids | name.user_id(u_a=302)=[304] ｜ op.parent.user_id(u_b=303)=[]
FAIL | ③ 学生账号挂到 op.parent.user_id（家长真正的登录账号） | u_b.child_ids=[] 期望含 304
FAIL | ③ name.user_id 未被误写 | u_a.child_ids=[304] 期望 []
读数 | ④ 写入后 u_c.child_ids | [307]（原有孩子 306 / 新学生账号 307）  ← 原有孩子 306 被清空
FAIL | ④ REPLACE 不丢兄弟：原有孩子仍在 | after=[307]
读数 | ⑤ 删前 | u_b(op.parent.user_id) child_ids=[304] ｜ u_a(name.user_id) child_ids=[308]
读数 | ⑤ 删后 | u_b child_ids=[304]（僵尸关联）｜ u_a child_ids=[]（原 308 被误清）
FAIL | ⑤ 清理落在 op.parent.user_id（家长真正账号） | u_b.child_ids=[304]
FAIL | ⑤ 未误清 name.user_id 账号上的其它孩子 | u_a.child_ids=[] 期望仍含 308
```

①-B 的原始 traceback（改前）：

```
2026-09-17 11:03:16,774 ERROR edu19 odoo.sql_db: bad query: b'INSERT INTO "op_parent" (..., "name", ...) VALUES (..., 543, ...)'
ERROR: duplicate key value violates unique constraint "op_parent_unique_parent"
DETAIL:  Key (name)=(543) already exists.
Traceback (most recent call last):
  File "<string>", line 60, in attempt
  File "<string>", line 166, in <lambda>
  File "/usr/lib/python3/dist-packages/odoo/orm/decorators.py", line 369, in create
    return method(self, vals_list)
  File "/mnt/custom-addons/edu_portal/models/parent_link_fix.py", line 106, in create
    res = super(_BaseOpParent, self).create(vals_list)
  File "/usr/lib/python3/dist-packages/odoo/orm/decorators.py", line 369, in create
    return method(self, vals_list)
  File "/usr/lib/python3/dist-packages/odoo/orm/models.py", line 4711, in create
    records = self._create(data_list)
  File "/usr/lib/python3/dist-packages/odoo/orm/sql_db.py", line 440, in execute
    self._obj.execute(query, params)
psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint "op_parent_unique_parent"
DETAIL:  Key (name)=(543) already exists.
```

复现形状（三条都要能站住）：

```python
# ① 空 email/mobile：命中库里第一条「email 为空」的伙伴（本机实测：canary '!…'，真实库里就是 Administrator id=3）
env['op.parent'].create({'name': '张三', 'relationship_id': rel.id,
                         'student_ids': [(6, 0, [stu.id])], 'mobile': '13100000001'})
# → op.parent.name 变成那条无关伙伴；它 is_parent=True、phone='13100000001'；第二次同型调用 → UniqueViolation

# ③ 读 A 写 B：op.parent.user_id=u_b / name.user_id=u_a（a≠b）
stu.write({'user_id': u_stu.id})     # → 写进 u_a.child_ids，u_b 空
```

## Root Cause（实测，带行号）

### ① 基座 :68-73 —— 空值参与 OR 搜索（主缺陷）

```python
partner = self.env['res.partner'].search([
    '|', '|',
    ('name', '=', parent_name),
    ('email', '=', parent_email),      # parent_email 为 None/'' 时 → 「email 为空的任意伙伴」
    ('phone', '=', parent_mobile),     # 同上
], limit=1)
```
实测域语义：`('email','=',None)` / `('email','=',False)` / `('email','=','')` 三者在本库**都命中 36 条**无邮箱伙伴。
触发条件（两条路径都会踩）：email 或 mobile **任一为空**即可能劫走 → 命中后 :76-83 写 `is_parent=True` + 回填 email/phone、
`vals['name'] = partner.id`；若那条伙伴已被别的 op.parent 认领过 → :95 `super().create()` 撞 `unique(name)`。
**注意 `email` 传了值也会被劫**：域是 OR，只要库里存在排在前面的无邮箱伙伴（本机 = `Administrator`，complete_name ASC 首位），
连「按邮箱认领正确伙伴」的正向路径也会被打偏（实测 ②-A FAIL）。

### ②/③ OpStudent.write 基座 :195-199 —— 读一个对象、写另一个对象

```python
if vals.get('user_id', False):
    for parent_id in self.parent_ids:
        child_ids = parent_id.user_id.child_ids.ids          # :197 读 A（家长登录账号）
        child_ids.append(vals['user_id'])
        parent_id.name.user_id.child_ids = [(6, 0, child_ids)]  # :199 写 B（且整体 REPLACE）
```
A≠B 时写入落到别的账号（实测 ③）；`parent_id.user_id` 为空时「起点」是空列表，整体 REPLACE 会清空 B 的其它孩子（实测 ④）。
⚠ **Odoo 19 语义（实测）**：`res.partner.user_id` 已不是「伙伴的登录账号」，而是**销售员**字段 ——
core `base/models/res_partner.py:229-236`：`"Warning: user_id is a Salesperson, not the inverse of partner_id in res.users"`。
本机实测：新建门户账号后 `partner.user_id` 仍为 `False`（`user_ids=[302]`）。所以基座这条写在真实数据上
**多半是静默丢失**（写空 recordset），只有 `partner.user_id` 恰好被写过（例如基座自己的 `create_parent_user` :151、
或 CRM 派了销售员）时才会命中——而那时命中的是**另一个语义的对象**。

### ④ OpStudent.unlink 基座 :207/:209 —— 同型

:207 读 `parent_id.user_id.child_ids`，:209 却写 `parent_id.name.user_id`：清理落到别的账号。

## Change Necessity

- ①不修 ⇒ 校方的「bug 一定要修」指向的就是它：**任何**不带邮箱/手机号的建档都会污染一条无关联系人并让 op.parent 指向错人；
  第二次同型操作直接 500（UniqueViolation）。这是**写进库的**数据污染，不是显示问题。
- ②③④不修 ⇒ 家长↔孩子账号关联（`res.users.child_ids`，被 openeducat 的 ir.rule
  `('student_id.user_id','in',user.child_ids.ids)` 直接消费）会挂到错误的账号上 / 静默丢失 / 清空别人的孩子列表；
  后者还可能把甲学生的记录暴露给乙账号（可见性越界）。

## Fix Boundary（改了什么 / 没改什么）

改（`custom_addons/edu_portal/models/parent_link_fix.py`，行号为改后）：

| 位置 | 改动 |
|---|---|
| `OpParent.create` :112-132 | 只重建搜索域：**空值不参与搜索**（`if parent_email:` 才加那一条，mobile 同理）；三条都为空时**不搜索**，直接走「新建伙伴」分支。域的 OR 形状 `['\|']*(n-1)+leaves` 与基座同形，有值时语义不变 |
| `OpStudent.write` :172-209（**新增覆盖层**） | 方法体 = 基座 :178-201 逐字副本；只改末段：读写统一到 `parent_id.user_id`，家长没账号就跳过 |
| `OpStudent.unlink` :226-231 | 回写目标由 `parent_id.name.user_id` 统一成 `parent_id.user_id`（与 :219 的读同源）；**保留** G 的成员判定 |

没改（刻意）：基座 `openeducat_erp/` 0 字节；G 的 `vals['mobile']` 修复；`:193` 无保护 remove；`:115` `clear_cache()`；
`:98/:110/:120` 的 `name.user_id` 守卫；`res.partner.user_id` 语义漂移；**没有**给 `res.users` 写操作加 sudo（保持原权限语义）；
没有重构整个方法、没有新建第二个覆盖同一方法的文件（MRO 会打架）。

**为什么统一到 `op.parent.user_id`（而不是回退写 `name.user_id`）**：门户按它认家长
（`controllers/downloads.py:149`、`ical.py:62` `search([('user_id','=',uid)])`），绑人码/邀请码写它
（`models/invite_code.py:309/343`），同文件的 `OpStudent.create` 与 `OpParent.*` 也写它；
而 Odoo 19 的 `partner.user_id` 是销售员。把它当回退目标，等于把学生账号追加到**销售员**（可能完全无关的内部账号）的
`child_ids` 上 —— 那正是 ir.rule 消费的字段，会制造可见性越界。所以家长没账号时**跳过**（没有 child_ids 可同步）。

## Verification（命令 + exit code + 关键输出）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `bash scripts/safe_upgrade.sh edu_portal` | **EXIT=0**；日志 `/tmp/edu19_upgrade.20260917-190221.log`：`Traceback\|CRITICAL` 计数 **0**；`[safe_upgrade] 就绪：/web/login?db=edu19 → 302`<br>（第一次尝试被别的成员**重启 web 容器**打断 → odoo 退出码 137，非代码问题；重跑即 0，见「环境注记」） |
| 2 | 同一份脚本 `tests/smoke/parent_link_identity.py` **改前**跑（临时换回 HEAD 版本，md5 对拍后立即还原） | **PASS 6 / FAIL 13**（13 条 FAIL = 三个缺陷全复现） |
| 3 | 同一份脚本 **改后**跑 | **PASS 19 / FAIL 0**（连跑两次一致） |
| 4 | `docker compose exec … < tests/smoke/parent_student_lifecycle.py`（G 的回归门禁） | **EXIT=0，PASS 20 / FAIL 0** |
| 5 | 四角色读数前后对拍 `diff <(grep "⑦ " pre.log) <(grep "⑦ " post.log)` | **IDENTICAL**（逐字一致：admin ok / 教务 ok / 教师 AccessError / 学生 AccessError / 家长 AccessError；可见 op.parent 数 1/2/ERR/0/1） |
| 6 | 清场自证（脚本 ⑧） | `残留=0（op.parent / op.student / res.partner / res.users / child_ids 关联表）parent=0 student=0 partner=0 user=0 child_rel=0`；`op.parent 1→1 ｜ op.student 4→4 ｜ is_parent 伙伴 3→3`；收尾另测：全库 `残留 res.users smoke_*=0`、`res_user_first_rel1` 无残留、canary 伙伴 `[]` |
| 7 | `python3 scripts/check_english.py` | **EXIT=0**（无 must-fix） |

**正向证据（不是「以后谁都不认领了」）**：改后 `②-A op.parent 指向 id=578 name='【临时·冒烟H】邮箱认领·伙伴'（目标伙伴 id=578）`、
`②-B op.parent 指向 id=580 name='【临时·冒烟H】同名伙伴'`（按 email / 按 name 都认领到**正确**伙伴）；
`③ 写入后 child_ids | u_a=[] ｜ op.parent.user_id(u_b)=[331]`（该回写的照回写，只是回了对的账号）；
`⑤ 删后 u_b child_ids=[] ｜ u_a child_ids=[335]`（该清的照清，且不误伤别人）；
`①-C` 三条搜索全空时是 `CheckViolation: … check constraint "res_partner_check_name"`（明确报错，让人补 name），
不再默默认领任意伙伴。

**环境注记（实测）**：第一次 `safe_upgrade.sh edu_portal` 返回 137，日志无任何 Traceback ——
docker events 显示同一时刻 `edu19-clone-web-1` 被 `com.docker.compose.replace=web-1` **重建**（同工作区另一成员的升级/
挂载自检触发），把容器内的 odoo 进程一起杀掉。这不是代码问题；重跑得 EXIT=0。同一工作区多成员并发改基座/升级时需注意这个竞态。

## Same-pattern（只报告不修）

| 位置（基座只读快照） | 形态 | 实测读数 |
|---|---|---|
| `:98` → `:100` | 守卫 `record.name.user_id`（Odoo 19=销售员）、写入对象是 `record.user_id` | 不设 `name.user_id`（常态）时 `create` 后家长账号 `child_ids=[]`（**该同步是死代码**）；把 `name.user_id` 写进去后守卫才放行，读数 `u.child_ids=[345]` |
| `:110` → `:114` | `OpParent.write` 同型守卫 | 家长 `user_id` 就位、`name.user_id` 为空时，写 `student_ids` 后 `u.child_ids` 仍 `[]` |
| `:120` → `:121` | `OpParent.unlink` 同型守卫（读/写/守卫三个对象） | 删掉家长后家长账号 `child_ids=[340]`：**僵尸关联没被清** |
| `:193` | 无保护 `child_ids.remove(self.user_id.id)` | 「学生无账号 + 清空 parent_ids」实测**未炸**（`search([('child_ids','in',False)])` 命中集为空，自带守卫）——与 G 的结论一致 |
| `:115` | `rec.env.registry.clear_cache()` 全局清缓存 | 未动、未测（G 已登记） |
| `:100/:114/:121/:175/:187/:194/:199/:209`（本次改动的 `:207-231` 也在内） | 写 `res.users.child_ids` **无 sudo** | 不改权限语义：G 门禁里「家长伙伴已绑账号（写 res.users）」教务侧仍为 `AccessError: 不允许修改"用户"（res.users）记录。`，admin 侧 ok（本次改动后逐字未变） |
| `res.partner.user_id` 语义漂移 | 基座把它当「伙伴的登录账号」用（`:45/:98/:110/:120/:128/:136/:151`），Odoo 19 定义是**销售员** | core `res_partner.py:229-236` 明写警告；实测新建门户账号后该字段仍是 `False`。**这是上面 :98/:110/:120 守卫恒 False 的根因**，属于更大的话题，本次不动 |
| `:56-65`（int 分支） | 调用方传既有伙伴 id 时，会用 op.parent 的 email/phone 回填**那个伙伴**（`if parent_email and not partner.email: ...`） | **推断**（未构造复现）：调用方显式传 id 属正常契约；但若前端误传无关伙伴 id，会改写别人的邮箱/电话。未修，仅登记 |

## Commit

- `fix(edu_portal): 覆盖基座模糊搜索误认/读写错位三处缺陷（任务 H）` —— 显式 add 三个文件：
  `custom_addons/edu_portal/models/parent_link_fix.py`、`tests/smoke/parent_link_identity.py`、`docs/audit/task-H-parent-fuzzy-claim.md`。
  未提交任何他人改动（`edu_tg_bind`、`edu_life`、`edu_nav` 等工作区未提交改动一个字未动）。

## Confidence

| 结论 | 级别 | 依据 |
|---|---|---|
| ① 模糊搜索误认/污染/UniqueViolation 及其修法 | **A** | 改前实测复现（含原始 traceback、canary 前后读数、真实库命中 `Administrator`）；改后 3 条相关断言全 PASS 且有正向认领读数 |
| ②③ write 读写对象错位、REPLACE 丢兄弟 | **A（行为）/ B（触发面）** | 行为侧：构造 A≠B 后逐字复现并修好；触发面：Odoo 19 下 `name.user_id` 不会自动被写，需它被显式写过（基座自己的 `:151` 或 CRM），因此**线上命中率取决于该字段被写过的数据量**，这一点只做了语义与读数判定（B），未做生产数据普查 |
| ④ unlink 清理落错账号 | **A** | 改前 `u_b=[304]（僵尸）/ u_a=[]（误清）`，改后 `u_b=[] / u_a=[335]` |
| 四角色行为不变 | **A** | 同一脚本前后 `diff` 逐字一致 |
| Same-pattern 各行 | 见上 | 均为本机实测读数；仅 `:56-65` 标「推断」 |
