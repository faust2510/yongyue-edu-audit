# 任务 G 报告：两个「管理员也炸」的基座 bug（op.parent.create / op.student.unlink）

> 修复提交：**bf85b7a**（`fix(edu_portal): 覆盖基座 op.parent.create / op.student.unlink 两处缺陷（任务 G）`）
> 覆盖文件：`custom_addons/edu_portal/models/parent_link_fix.py`（新增）｜断言脚本：`tests/smoke/parent_student_lifecycle.py`（新增）
> 平台：本地 edu19（Odoo 19.0-20260817 + openeducat_parent 19.0.1.0 + edu_portal 19.0.2.0.0）｜日期：2026-09-17
> **本文所有结论标注「实测 / 推断」；行号均指只读基座快照 `openeducat_erp/openeducat_parent/models/parent.py`（236 行，未改一个字节）**

## Symptom（实测）

校方点得到的两条后台路径，**管理员（uid=2, su=False）同样失败**：

| # | 路径 | 报错 |
|---|---|---|
| ① | 新建家长（伙伴是**新名字**时） | `ValueError: Invalid field 'phone' in 'op.parent'` |
| ② | 删除「有家长的学生」 | `ValueError: list.remove(x): x not in list` |

## Reproduction（实测，改前原始 traceback）

复现身份：`env(user=2, su=False)`（= 真实 admin 会话，非 superuser，用来排除「superuser 免检」假象）。

① 新建家长（`name` 传**字符串**，三路搜索均不命中）：

    Traceback (most recent call last):
      File "<string>", line 27, in <module>
      File "/usr/lib/python3/dist-packages/odoo/orm/decorators.py", line 369, in create
        return method(self, vals_list)
      File "/mnt/extra-addons/openeducat_parent/models/parent.py", line 95, in create
        res = super(OpParent, self).create(vals_list)
      File "/usr/lib/python3/dist-packages/odoo/orm/models.py", line 4654, in create
        raise ValueError(f"Invalid field {field_name!r} in {self._name!r}")
    ValueError: Invalid field 'phone' in 'op.parent'

② 删除「有家长、无门户账号」的学生：

    Traceback (most recent call last):
      File "<string>", line 73, in <module>
      File "/mnt/extra-addons/openeducat_parent/models/parent.py", line 208, in unlink
        child_ids.remove(record.user_id.id)
    ValueError: list.remove(x): x not in list

复现形状（两条都必须**唯一** email/mobile，否则会先撞下面 Same-pattern 第 3 条）：

    parent = env(user=2, su=False)['op.parent'].create({
        'name': '某新家长名',            # 字符串 → 走「新建伙伴」分支
        'relationship_id': <rel.id>,
        'student_ids': [(6, 0, [<学生id>])],
        'mobile': '13000000001', 'email': 'x@example.invalid',
    })                                    # → ValueError: Invalid field 'phone'

    stu = env(user=2, su=False)['op.student'].create({'name': '某学生'})   # 无门户账号
    env['op.parent'].create({... 'student_ids': [(6, 0, [stu.id])], ...})
    stu.unlink()                          # → ValueError: list.remove(x): x not in list

## Root Cause（实测，带确切行号与触发条件）

### ① 基座 parent.py:93（在 :95 炸）

基座 `OpParent.create`（第 49-105 行）第 84-93 行的「**找不到已有伙伴**」else 分支：
它先在 res.partner 上新建伙伴（第 85-90 行，四字段 name/email/**phone**/is_parent 对 res.partner 全部合法），
然后把同样的值回填进 `op.parent` 的 vals：

    92:                vals['email'] = parent_email      # op.parent 有 email ✔
    93:                vals['phone'] = parent_mobile     # ✘ op.parent 没有 phone

`op.parent` 自己的字段叫 **mobile**（同文件第 33 行 `mobile = fields.Char(string='Mobile')`），
没有 `phone`（内核实读字段表：`'phone' in env['op.parent']._fields → False`）。于是第 95 行
`super().create(vals_list)` 的字段校验抛 `ValueError`（odoo/orm/models.py:4654）。

**触发条件（三个同时成立才炸）**：
1. `name` 传的是**字符串**（不是已存在伙伴的 id）；
2. 该 name / email / mobile 三路 OR 搜索**都没命中**已有 res.partner → 进 else 分支。
   命中已有伙伴则走 59-83 行分支，**不写 phone**，所以那一支没事（实测：`create({'name': <已有伙伴id>, ...})` 成功）；
3. 因此「新建家长必炸」准确说是「**新建伙伴**必炸」。

**为什么管理员同样炸**：该分支在 `super().create` 里、任何 ACL/ir.rule 判定**之前** ——
与四层权限模型无关（实测：admin su=False 复现）。
**为什么上游 CI 没抓到**（推断，有代码证据）：基座自带 `openeducat_parent/tests/test_parent.py`
四处 create 全部传 `self.parent_partner.id`（int）→ 永远走「已有伙伴」分支，else 分支零覆盖。

### ② 基座 parent.py:208

基座 `OpStudent.unlink`（第 203-210 行）：

    203:    def unlink(self):
    204:        for record in self:
    205:            if record.parent_ids:
    206:                for parent_id in record.parent_ids:
    207:                    child_ids = parent_id.user_id.child_ids.ids     # op.parent.user_id，可空
    208:                    child_ids.remove(record.user_id.id)             # op.student.user_id，可空 ✘
    209:                    parent_id.name.user_id.child_ids = [(6, 0, child_ids)]
    210:        return super(OpStudent, self).unlink()

`list.remove` 要求成员存在；这里三处都可能是「不存在」：

- **学生没有门户账号**（`op.student.user_id = False` → `remove(False)`）——本地 4 名学生里 3 名如此；
- **家长没有 `op.parent.user_id`**（`child_ids` 为空列表）；
- 该学生**本就不在**该家长的 `child_ids` 里。

而第 208 行在 `return super().unlink()` **之前**，异常直接把整条删除动作打断 ⇒ 学生**没被删掉**（实测）。

## Change Necessity

- 基座是官方只读快照（铁律：一个字节都不改）⇒ 修法只能是本仓 `_inherit` 覆盖；
- 两条路径都在校方可达界面/API 上，且与本仓权限设定无关（admin 亦炸）⇒ 必须修；
- **承载模块选 `edu_portal`**：`op.parent` / `op.student` 的档案与门户关联本来就是它的地盘 ——
  同模块 `models/invite_code.py:470/486` 已各有一层 `_inherit`（`edu_pending_setup`），
  家长端 /my/child（`controllers/batch2.py`）、通讯录重绑（`controllers/contacts.py`）、
  家长档案 ACL（commit 5b4f736）都在这；放这里不需要新模块、不新增部署面。
  （另一候选「新建 edu_parent_fix 小模块」被否：只为一个覆盖层多一个模块/部署单元，收益为负。）

## Fix Boundary

**改了什么**（`custom_addons/edu_portal/models/parent_link_fix.py`，两个类，方法体 = 基座方法体**逐字副本**，只改 2 处）：

1. `OpParent.create`：第 93 行那一处 `vals['phone']` → **`vals['mobile']`**
   （与上一行 `vals['email']` 对称，就是基座作者的原意；`mobile` 是 op.parent 自己的字段）。
2. `OpStudent.unlink`：`child_ids.remove(...)` 前加成员判定 ——
   `if student_uid and student_uid in child_ids:` 才 `remove` + 回写；
   不在列表里 = 本来就没有这条关联要清，无需 remove，也不必回写
   （基座那种「无条件回写」在这种场景下反倒会用空列表清掉别人 `child_ids`）。
   **清理语义不变**：该清的时候照旧清，且照旧回写到 `parent.name.user_id`。

**实现上必须知道的坑**（已写进文件 docstring）：本层在 MRO 里位于基座那一层**之上**
（实测 MRO：`op.parent` → `edu_portal.parent_link_fix.OpParent` → `edu_portal.invite_code.OpParent`
→ `openeducat_parent...OpParent` → `Model`；`op.student` 同构），
所以复制体**不能**用裸 `super()` 结尾 —— 那会**二次执行**基座那套缺陷代码；
两处都写成 `super(基座类, self)`，即「从 MRO 里基座那一层**之后**继续」，
等价于基座自己 `super(OpStudent, self)` 的效果（不吞掉其它层的实现）。

**+2 处接线改动**：
- `models/__init__.py` 追加 `from . import parent_link_fix`（排在 `invite_code` 之后——同模块后导入的层在 MRO 更靠前，才盖得住基座）；
- `__manifest__.py` depends 增 `openeducat_parent`：既有 `_inherit` 事实 + 新代码**直接 import 基座类**，不声明依赖等于偷依赖。

**没改什么**（边界自证）：
- `openeducat_erp/` 一个字节没动；
- 没新增/修改任何字段定义；没动基座的 `write` / `create_parent_user` / `_onchange_name` / 约束；
- 没碰 `security/ir.model.access.csv`（同期他人正在改）；
- 没动别人未提交的改动（edu_life / edu_nav / docs / tests 等）；
- 未部署生产；未改菜单/视图/模板。

## Verification（命令 + exit code + 关键输出）

**1) 升级门禁**：`bash scripts/safe_upgrade.sh edu_portal` → **SAFE_UPGRADE_EXIT=0**；
日志内 `Traceback (most recent call last)|CRITICAL` 计数 **0**；收尾 `就绪：/web/login?db=edu19 → 302`。
文件一致性自证：三个模块文件 host md5 == container md5（`parent_link_fix.py 9447e699 / __init__.py 6fb9e5ec / __manifest__.py 8148d13f`），
mtime 18:39:32-36 < 升级日志开始 18:41:00 ⇒ 该次升级覆盖的正是最终代码。

**2) 新建家长（admin）**：改前 raw `ValueError: Invalid field 'phone'`（见上）→ 改后成功并读回：
`op.parent id=47`、**`mobile='13000000001'`（原来写错的字段，读回正确）**、`email` 正确、
伙伴 `phone/email` 落库正确、`is_parent=True`、`student_ids=[160]`。

**3) op.parent 其它创建路径**：已有伙伴分支成功（`id=48`，伙伴 441 被标 `is_parent`、phone/email 回填）；
批量新建（一次两条 vals）成功（`ids=[49,50]`，两条 mobile 各自正确）。

**4) 删除有家长的学生**：
- 学生**无**门户账号（上报的那种）：改前 `ValueError: list.remove(x): x not in list` → 改后成功（student 161 已删）；
  家长侧读数 `child_ids before=[] after=[]`（无账号 ⇒ 无可清理，符合语义）；
- 学生**有**门户账号且确在家长 user 的 `child_ids` 里：改后成功（student 163 已删），
  **家长侧关联被清理：`before=[291] → after=[]`**。

**5) 不回归**：删除**无家长**的学生仍成功；`op.student` 常规写/读不受影响（写 email 后读回一致）。

**6) 四角色（权限差异说明）**：
- **教务 `backoffice@local`（uid=12）**：新建家长（新伙伴分支）**成功**且 mobile 落库正确；
  删「有家长、无账号」的学生**成功**（走同样两条路径）。
- **教师 `faculty@local` / 学生 `stu@local` / 家长 `parent@local`**：读数 = ACL 拒绝
  （教师「不允许创建家长(op.parent)」；学生/家长「不允许创建联系人(res.partner)」）——
  与本次修复前同类拒绝一致：他们本来就不在档案层的授权面内，本次改动**不改变**其权限面。
- **边界读数（同一份数据、只换身份）**：家长伙伴已绑门户账号时，基座 create 末尾要写 `res.users.child_ids` →
  **admin: ok ／ 教务: `AccessError: 不允许修改"用户"（res.users）记录`**。
  这是**四层权限边界**（L2 教务没有 res.users 写权限，Odoo 只给 `group_erp_manager` 写权限），
  **不是**本次那两个基座缺陷，故未纳入本次修复（见下）。

**7) 清场自证**：残留 = 0（op.parent / op.student / res.partner / res.users / 家长-学生关联表 全 0），
且计数回到开工前（op.parent 1→1、op.student 4→4）。
断言脚本：`tests/smoke/parent_student_lifecycle.py` → **SMOKE_EXIT=0，PASS 20 / FAIL 0**。

**8) 静态门禁**：`python3 scripts/check_view_xpath.py` → **RESULT=OK / exit 0**（规则 7 外部模块清单
23 条 == 常量 23，**无须改边界常量**：edu_portal 早已继承 op.parent / op.student，
同一 (模块,模型) 组合不重复计数）；`python3 scripts/check_manifest_tracking.py` → **OK / exit 0**。

**9) 归因对照（证明修的是哪一层）**：修复后直接调「基座那一层」——
`BaseP.create(...) ` → 仍是 `ValueError: Invalid field 'phone' in 'op.parent'`（parent.py:95）；
`BaseS.unlink(...)` → 仍是 `ValueError: list.remove(x): x not in list`（parent.py:208）；
而走正常 API（本仓覆盖层）同一形状两次都成功 ⇒ 行为变化来自覆盖层，不是环境里别的东西变了。

## Same-pattern（同型巡检；**只报告，未修**）

同一基座文件，逐条核对结果：

1. **写不存在的字段**：**只有**第 93 行这一处。全文件 `vals[...]`/`update_vals[...]` 赋值 9 处
   （61/63/78/80 写 res.partner 合法字段；83/91/92/93 写 op.parent；198 是 list.append）——已修，无第二处。
2. **无保护 `remove()`**：第 193 行（`OpStudent.write` 的「取消家长」分支）与第 208 行（已修）。
   193 **自带守卫**：上一行 `search([('child_ids','in',self.user_id.id)])` 只会返回 `child_ids` 确含该值的 user，
   故成员关系由构造保证（实测 user_id 为空的情形未炸）。
3. **模糊搜索会「认领」无关伙伴**（我造数据时踩到两次，实测）：第 68-73 行
   `('email','=',parent_email)` / `('phone','=',parent_mobile)` 在 email/mobile **缺省**时
   语义变成「email/phone 为空」→ 命中任意无邮箱伙伴（含无关伙伴）→ 把别人标成 `is_parent` 并回填 email/phone，
   紧接着撞 `unique(name)` 约束报 `UniqueViolation: duplicate key ... op_parent_unique_parent`。
4. **读写对象错位**（实测代码 + 推断后果）：unlink 读 `parent_id.user_id.child_ids`（207）
   却写 `parent_id.name.user_id.child_ids`（209）；`OpStudent.write` 同样（197 读 / 199 写）。
   两个 user 不指向同一个账号时，清理与回写落到不同记录上。
5. **REPLACE 语义丢兄弟**（推断，代码证据）：197-199 行从 `parent_id.user_id.child_ids` 起步再整体
   `[(6,0,child_ids)]` 回写 —— 若家长 `user_id` 为空而 `name.user_id` 有值，会把那个账号的**其它孩子清空**。
6. **写 res.users（权限敏感）**：第 100 / 114 / 121 / 175 / 187 / 194 / 199 / 209 行都在写
   `res.users.child_ids` 且无 `sudo()` ⇒ 任何非 admin 操作者（教务/教师）都会 `AccessError`；
   `create_parent_user`（124-151）还要**创建** res.users。核心机制（实测）：
   core `res.partner.write`（`odoo/addons/base/models/res_partner.py:919-920`）在目标伙伴绑有**其它内部用户**时
   会先 `internal_users.check_access('write')` —— 即「写伙伴」被 Odoo 附加要求「能写 res.users」。
   **建议**：若校方要「教务也能建家长/删学生」，这是要单独决策的一层（给组授权 or 基座路径改 `sudo`），
   超出任务 G 边界（本次只修「管理员也炸」的两个缺陷），请队长裁定。
7. **字段语义漂移**（推断；字段元数据为实测）：基座把 `res.partner.user_id` 当作「该伙伴的用户」
   （45/98/110/120/151 行读写它），但 Odoo 19 里 `res.partner.user_id` 的 string 是 **Salesperson**
   （`compute=_compute_user_id`），真正的账号绑定是 `res.partner.user_ids`（One2many）。
   基座判空/赋值实际落在业务员字段上。
8. **低危**：第 115 行 `rec.env.registry.clear_cache()` —— 每次 `op.parent.write` 都清全局缓存。

## Commit

- **bf85b7a**（分支 `main-real`）：`fix(edu_portal): 覆盖基座 op.parent.create / op.student.unlink 两处缺陷（任务 G）`
- 只含本次 4 个文件：`custom_addons/edu_portal/models/parent_link_fix.py`（新增）、
  `custom_addons/edu_portal/models/__init__.py`、`custom_addons/edu_portal/__manifest__.py`、
  `tests/smoke/parent_student_lifecycle.py`（新增）。
  提交用 `git commit -- <这 4 个路径>` 显式限定：**同期他人已 stage 的 `edu_tg_bind` 等文件未被带入**（`git show --stat` 已核）。
- 本报告文档随后单独提交。
- **未部署生产**（按任务边界，部署由队长统一执行）。

## Confidence

**A（实测为主）**。依据：
- 两条缺陷都拿到了**改前原始 traceback**（含基座行号 95 / 208）与**改后同形状成功**的对照；
- 「修的是哪一层」有直接对照实验（同一天内直接调基座类仍失败、走覆盖层成功）；
- 断言不是「不报错就算过」：读回了被写错的 `mobile`、伙伴 `phone/email/is_parent`、
  家长侧 `child_ids` 清理前后读数（`[291] → []`）；
- 升级门禁 EXIT=0 + host/container md5 一致（证明跑的是最终代码）；
- 清场与计数回到开工前，残留=0。
**未覆盖的分支（明确列出）**：多公司（`res.company`）下的家长创建、生产库只读复现、
基座自带 `tests/test_parent.py` 全量重跑（需新建测试库，未做——其断言形状已逐条比对，与本次改动无冲突）。
