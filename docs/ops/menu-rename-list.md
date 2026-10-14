# 后台菜单改名一览（t117）

> **用途**：供操作手册引用 —— 教务每天要点的后台入口，机翻错译已修正。
> **做法**：`custom_addons/edu_zh/i18n_extra/{zh_CN,zh_TW}.po` 词条覆盖；**不改只读基座 `openeducat_erp/`**。
> **最后更新**：2026-09-24（**第二轮 P0/P1/P2**：字段 parent_id 家长部→上级院系、276 专业→培养方案、
> 264 批次→班级、298 父母→家长设置、299 人际关系→亲属关系、动作 414 父母→家长 + §0.2/§0.3 机制精确化；
> **同日第三遍 P0b**：op.department.name 姓名→**名称**（同一张新建表单整表扫描所得，见 §3.5）；
> 上一版 2026-09-22 菜单 259/265 + §0.1 noupdate 机制；更早 2026-09-14 t117）

---

## 0. 为什么能这样改（改之前先证明改得动）

1. 这些菜单的 source 名（en_US）**本身没错**，错的是**机器译文**（`Programs`→「节目」、`Profile`→「轮廓」、`Sheets`→「床单」、`SIS`→「安全信息系统」）。
2. 实测 t117 这批菜单 `ir_model_data.noupdate = **f**` ⇒ **PO 可覆盖**（不是 noupdate 陷阱）。
   ⚠ **这不是全库通则**：2026-09-22 实测**菜单 259 的 xmlid `noupdate = t`**，声明式覆盖与 PO 覆盖**都到不了它**（见 §0.1）。
3. 但按本仓已证的硬限制：**覆盖其他模块的 DB 词条必须带 `--i18n-overwrite`**，否则数据库既有值优先、改了不生效。

### 0.1（2026-09-22）noupdate 记录：一次标记咬两次，以及怎么改

起因：教务专员在后台点「院系」落进**教职员工人事表**（要 名/姓/性别/出生日期），要建的「院系」其实是菜单 265 → `op.department`。改名时撞上 **本仓第一次遇到的 noupdate 记录**，实测两层都咬：

| 层 | 现象（实测） | 依据 |
|---|---|---|
| ① 声明式 `<record id="openeducat_core.…" forcecreate="0">` | 菜单 265 / 动作 380 / 动作 388 **一次生效**；菜单 259 `noupdate=t` ⇒ 升级 **exit 0、日志无异常**，而 `ir_ui_menu.name->>'en_US'` **仍是 Faculties** | 升级后 psql 实读 |
| ② PO 覆盖（`-u edu_zh` + `--i18n-overwrite`） | 动作 388 的 zh 变成「教职员工」；菜单 259 的 zh **停在旧的「院系」** | Odoo 19 `odoo/tools/translate.py:1609-1610,1663`：*"For a record with 'noupdate' in ir_model_data, its existing translations will be overwritten if force_overwrite or (not noupdate and overwrite)"* ⇒ 升级路径下 `force_overwrite=False` ⇒ **带了 `--i18n-overwrite` 也无效** |

**改法**：该记录改由 `<function>` 走 ORM —— **先把 `ir_model_data.noupdate` 规范成 False（幂等、查不到就跳过），再写 source 名**；**用户可见中文仍一律走 PO**。
- 代码：`custom_addons/edu_portal/models/menu_labels.py`（`edu_apply_menu_label_renames`，写法照 `models/menu_reachability.py` 先例）
- 数据：`custom_addons/edu_portal/views/menu_labels.xml`（265/380/388 三条声明式 + 259 一条 `<function>`）
- 复现 SQL：`SELECT module||'.'||name, noupdate FROM ir_model_data WHERE model='ir.ui.menu' AND res_id IN (259,265);` → `menu_op_faculty_main|t`、`menu_op_department_sub|f`

> 迁移到别的改名任务时的自检：**动手前先查 `noupdate`**。为 `t` 时声明式写法是**静默失效**（没有报错可看），必须走 §0.1 的 ORM 路 + 规范标记。

### 0.2（2026-09-24）动手前的 noupdate 例行自检（本轮复现，照抄即可）

```sql
SELECT d.model, d.module||'.'||d.name AS xmlid, d.res_id, d.noupdate
  FROM ir_model_data d
 WHERE (d.model='ir.ui.menu' AND d.res_id IN (264,276,297,298,299))
    OR (d.model='ir.actions.act_window' AND d.res_id IN (386,395,414,415))
    OR d.name='field_op_department__parent_id';
```

实测：**本轮要改的 6 条菜单/动作 + 1 个字段 xmlid 全是 `f`**（只有 297 `menu_op_parent_root` 是 `t`，
而本轮**不动它的 source**）⇒ 声明式 `<record forcecreate="0">` 即可生效，`<function>` 的 ORM 路本轮用不上。

### 0.3（2026-09-24）机制精确化：词条**不是**按 msgid 全局生效，而是**按 xmlid**

上一版文档（§5、各 PO 注释）写的是「PO 覆盖按 msgid 全局生效」。本轮源码取证发现**更准确**的说法是
**按 PO 里的 `#:` 引用落到具体 xmlid 上**：

| 环节 | 位置 | 事实 |
|---|---|---|
| 解析引用 | `odoo/tools/translate.py:1596-1600` | 译文存进 `model_terms_translations[model][field][xmlid][src][lang]` —— **xmlid 来自 `#: model:<model>,<field>:<xmlid>` 引用行** |
| 落库 | 同文件 1636-1646 | 按 `(module, name)` 反查 `ir_model_data` 那**一条**记录，逐条判 noupdate |

两条推论（本轮都实测到了）：

1. **漏写引用 = 没覆盖**：`Parents` 词条原来只写了菜单 297 的引用 ⇒ 动作 414 的中文停在基座机翻
   **「父母」**，而菜单 297 是**「家长」**（同一记录家族两个名字，面包屑 ≠ 菜单）。本轮补上动作 414 的引用即修好。
2. **写清引用 = 定点覆盖、不牵连**：P0 的 `Parent Department` 是**字段标签**（`ir_model_fields.field_description`），
   源串在基座模型里、不能改（`openeducat_erp/` 只读）⇒ 用引用行钉死 `field_op_department__parent_id`
   这一条覆盖即可（基座 PO 里该 msgid 本来也只有这一个引用，双保险）。

> 实务写法不变：**另造全新唯一串 + 给新串出词条**（引用旧串的条目一并撤掉），这样既隔离影响面，
> 又天然绕开「已有译文优先」的 keep-existing 分支（新串在该记录上还没有译文，无论 noupdate 都能落进去）。

## 1. 生效方式（可复现）

```bash
# 已装模块用 -u（**不是 -i**：-i 对已装模块不重载 data/view，会得到「升级成功但页面没变」的假象）
UPGRADE_EXTRA_ARGS="--i18n-overwrite" bash scripts/safe_upgrade.sh -u edu_zh
```

实测退出码与前后对照见 §3。

## 2. 改名一览（旧名 → 新名 → 菜单 id）

| 菜单 id | 旧中文名（机翻） | 新中文名 | en_US（source，未改） | 模块 |
|---|---|---|---|---|
| 257 | 安全信息系统 | **学生信息** | SIS | openeducat_core |
| 276 | 节目 | **专业** | Programs | openeducat_core |
| 277 | 程序级别 | **专业层次** | Program Level | openeducat_core |
| 279 | 轮廓 | **档案** | Profile | openeducat_core |
| 260 / 280 | 一般的 | **通用** | General | openeducat_core |
| 287 | 学生移民 | **学生转班** | Student Migration | openeducat_activity |
| 291 | 意见书 | **作业提交** | Submissions | openeducat_assignment |
| 297 | 父母 | **家长** | Parents | openeducat_parent |
| 349 | 课堂出勤率 | **课堂考勤** | Class Attendances（含前导空格） | openeducat_attendance |
| 350 | 出席率 | **考勤** | Attendance | openeducat_attendance |
| 351 | 寄存器 | **点名册** | Registers | openeducat_attendance |
| 352 | 床单 | **点名表** | Sheets | openeducat_attendance |
| 353 | 出勤线 | **出勤明细** | Attendance Lines | openeducat_attendance |

**同族一并修的**：351「寄存器」、353「出勤线」、287「学生移民」、291「意见书」、297「父母」——
它们与教务点名/招生/作业的日常动线在同一批菜单里，属同一类机翻错译。

## 3. 实测对照（改前 / 改后）

> 「改后」列为 `ir_ui_menu` 实读值（zh_CN），由 §1 的升级命令生效后测得。

| 菜单 id | en_US | 改前 zh_CN | 改后 zh_CN | complete_name（改后） |
|---|---|---|---|---|
| 257 | SIS | 安全信息系统 | **学生信息** | 学生信息 |
| 276 | Programs | 节目 | **专业** | 学生信息/配置/项目管理/专业 |
| 277 | Program Level | 程序级别 | **专业层次** | 学生信息/配置/项目管理/专业层次 |
| 279 | Profile | 轮廓 | **档案** | 学生/档案 |
| 260 / 280 | General | 一般的 | **通用** | 学生信息/通用 ｜ 学生/通用 |
| 287 | Student Migration | 学生移民 | **学生转班** | 学生信息/通用/学生转班 |
| 291 | Submissions | 意见书 | **作业提交** | 作业/作业/作业提交 |
| 297 | Parents | 父母 | **家长** | 学生信息/家长 |
| 349 | ` Class Attendances` | 课堂出勤率 | **课堂考勤** | 课堂考勤 |
| 350 | Attendance | 出席率 | **考勤** | 课堂考勤/考勤 |
| 351 | Registers | 寄存器 | **点名册** | 课堂考勤/考勤/点名册 |
| 352 | Sheets | 床单 | **点名表** | 课堂考勤/考勤/点名表 |
| 353 | Attendance Lines | 出勤线 | **出勤明细** | 课堂考勤/考勤/出勤明细 |
| 263 | Courses | 课程 | 课程（**未变**） | 学生信息/配置/课程管理/课程 |
| 264 | Batches | 批次 | 批次（**未变**） | 学生信息/配置/课程管理/批次 |
| 267 | Subjects | 科目 | 科目（**未变**） | 学生信息/配置/学科管理/科目 |
| 343 | Calendar Events | 会议 | 会议（**未变**） | 时间表/时间表/会议 |
| 612 | （en_US 即中文） | （空槽位，靠回退） | 选课审批（**未变**） | 教务审批/选课审批 |

> **测量方式**：`ir_ui_menu` 经 ORM（`lang=zh_CN`）读取 `name` 与 `complete_name`（后者是计算字段，SQL 直读不到）。
> **繁体同步实测**：257=`學生資訊`、276=`專業`、279=`檔案`、352=`點名表`。
> **回归结论**：263/264/267/343/612 **一字未变**；尤其 612 无 zh_CN 槽位、靠回退显示「选课审批」，本次未触碰。

### 2.1（2026-09-22）名字与**模型**不符的两条：259 / 265

> 与 §2 的「机翻错译」不同类：这两条的 source 名没错，**错的是名字指向的实体**（详见 §0.1 起因）。
> 机制照 2026-09-19 专业编排（`docs/plans/major-track-elective-design.md` §6.6.3）：**改 source 成全新唯一串 + PO 出新串词条**（不直接覆盖旧 msgid ⇒ 不波及其他记录）。

| 菜单 id | 旧中文名 | 新中文名 | 新 en_US source | 关联动作 | 动作指向的模型 | 落点 |
|---|---|---|---|---|---|---|
| **259** | 院系 | **教职员工** | `Teaching Staff` | 388 | `op.faculty`（人事档案，名/姓/性别/出生日期 required） | `custom_addons/edu_portal/views/menu_labels.xml` + `models/menu_labels.py`（**noupdate=t，走 ORM**） |
| **265** | 部门 | **院系部门** | `Academic Departments` | 380 | `op.department`（**名称 + 代码**，父级可选） | 同上文件（声明式即可） |

> **为什么另造新串**（实测引用，`openeducat_core/i18n/zh_CN.po`）：`Faculties` 还挂在 `act_open_op_faculty_view_2` 与 `field_wizard_op_faculty__faculty_ids` 上（2239-2241 行）；`Department` 还挂在 `op_course`/`op_program`/`op_subject`.`department_id` 三个字段标签与三张 `op.department` 视图 arch 上（1832-1838 行）⇒ 直接覆盖 msgid 会连带改错（§5 的全局性）。

### 2.2（2026-09-24）第二轮：字段标签 + 四条菜单/动作 + 一处名实不符

> 与 §2 的「机翻错译」和 §2.1 的「名字指向错实体」都不同类：本轮**四类**各有各的病根，逐条列。
> 落地处：菜单/动作 source 走 `custom_addons/edu_portal/views/menu_labels.xml`（声明式，本轮 6 条 noupdate 全 f）；
> 中文与字段标签走 `custom_addons/edu_zh/i18n_extra/{zh_CN,zh_TW}.po`。

| 类 | 记录 | 旧中文 | 新中文 | 新 en_US source | 病根（实测） |
|---|---|---|---|---|---|
| **P0** | 字段 `op.department.parent_id` | 家长部 | **上级院系** | （不改，仍是 `Parent Department`） | 基座机翻：规范所有者 = `openeducat_core/models/department.py:31` 的字段串 + `openeducat_core/i18n/zh_CN.po:4102-4105`。基座只读 ⇒ 唯一合规修法是 `edu_zh` 定点覆盖（§0.3） |
| **P0b** | 字段 `op.department.name` | 姓名 | **名称** | （不改，仍是 `Name`） | 同一张表单整表扫描（§3.5）补漏：基座把通用串 `Name` 直译「姓名」，对院系荒谬。该 msgid 被 **14+ 个字段**共用（学生/教师/家长的 name 都是它，那些地方「姓名」是对的）⇒ 必须按 xmlid 钉死，**不可全局覆盖** |
| **P1** | 菜单 276 + 动作 395 | 专业（动作还叫「节目」） | **培养方案** | `Program Plans` | **同名不同物**：276 → `op.program`，263 → `op.course`；276 挂在停用的 275 下，启用即静默多出第二个「专业」 |
| **P2a** | 菜单 264 + 动作 386 | 批次 | **班级** | `Student Batches` | `op.batch` 在本校 = 一个班的学生（旁证：需求 7 班级分配全复用 `op.batch`，`views/class_batch_views.xml:4-5`；797「已停用班级」同实体） |
| **P2b** | 菜单 298（无动作） | 父母 | **家长设置** | `Parent Settings` | 298 与 297 **同名 `Parents` 不同物**：297 = `op.parent` 名册（已是「家长」），298 = 挂在「配置」下的**容器**，唯一子节点是 299 |
| **P2c** | 菜单 299 + 动作 415 | 人际关系 | **亲属关系** | `Kinship Relations` | `op.parent.relationship` 是 father/mother/guardian 的**关系字典**，不是人际网络 |
| **P2d** | 动作 414 | 父母 | **家长** | （不改，仍是 `Parents`） | 词条 xmlid 漏写（§0.3）：菜单 297 早已是「家长」，动作 414 却停在同一 msgid 的基座机翻「父母」 |

> **P1 取舍（一句话理由，可逆）**：学校的「专业」= `op.course`（263，2026-09-19 专业编排已定并上线），
> 而 `op.program` 是「课程 + 学制」的编排结构 ⇒ 取**培养方案**，全库只剩 263 一条叫「专业」。
> 若教务另有口头习惯（如「课程体系」），改 PO 里 `Program Plans` 的 msgstr 一处即可，source 与代码不用动。
> **P0b 取舍（一句话理由，可逆）**：与右侧的「代码」配成**名称 + 代码**这一本仓既有标准对（§2.1 原文即写「名称 + 代码」），
> 且 `op.department` 在 `op_course`/`op_program`/`op_subject` 的 `department_id` 里是以「部门」身份被引用的，
> 字段自身写死「院系名称」会在那些 m2o 语境下别扭 ⇒ 取通用的**名称**。改回「院系名称」只需改 PO 一处 msgstr。
> **未动的邻居（有意）**：275「项目管理」（停用容器，仅出现在 276 的面包屑前缀里）。
> **系统性问题（本轮只修了本表单这一条）**：`Name`→「姓名」是基座对整个通用串的直译，`op.batch.name`（班级列表列头）
> 等其它模型的 name 字段同样显示「姓名」；要收敛需按模型逐条加 xmlid 引用词条，**属另一件工作，不在本轮范围**。

> ⚠️ **生效方式实测（两次都记，含失败那次）**：
> 1. `bash scripts/safe_upgrade.sh -u edu_zh` → **退出码 0，但菜单名一字未变**（`ir_ui_menu` 实读仍是旧名）——
>    这正是「**升级成功但页面没变**」的假成功，也印证了必须带 `--i18n-overwrite`；
> 2. `UPGRADE_EXTRA_ARGS="--i18n-overwrite" bash scripts/safe_upgrade.sh -u edu_zh` → **退出码 0**，
>    日志出现 2 次 `loading translation file`，菜单名**全部变为新名**。
> **结论**：`--i18n-overwrite` 不是可选优化，是**生效的必要条件**。

### 3.1（2026-09-22）259 / 265 改前 / 改后实读（+ 端到端走通）

> 读数：`ir_ui_menu` / `ir_act_window` 经 psql 实读（zh_CN 槽位）；页面口径用真浏览器（Playwright）复核。
> 证据脚本：`tests/smoke/department_path.py`（L1 菜单可见 → L2 动作 → L3 视图/列表 → L4 真浏览器新建保存 → 清场；**可重跑**）；
> 读数落盘：`tests/smoke/department_path_before.json` / `department_path_after.json`；截图 `shots/smoke/dept_path_before_*.png`、`dept_path_after_*.png`（`shots/` 是 gitignore）。

| 记录 | 改前 zh_CN | 改后 zh_CN | 改后 en_US | 页面口径（真浏览器） |
|---|---|---|---|---|
| 菜单 259「院系」 | 院系 | **教职员工** | `Teaching Staff` | 259 页 title：院系 → **教职员工**（改前是两名人员看板，非院系列表） |
| 动作 388 | 院系 | **教职员工** | `Teaching Staff` | 面包屑/页面标题同源 |
| 菜单 265「部门」 | 部门 | **院系部门** | `Academic Departments` | 265 路径 = 学生信息 / 配置 / 教学管理 / **院系部门**；title 与面包屑均 **院系部门** |
| 动作 380 | 部门 | **院系部门** | `Academic Departments` | 同上 |

**端到端（改后实测，before/after 两次都跑，均 FAIL=0）**：`教学管理 → 院系部门` 打开列表（0 条 → 新建 名称+代码 → 保存 → 列表可见 → 删除 → 残留 0）；`op.department.create()` 的副作用实测见 §6。

### 3.2（2026-09-22）副作用实测：`op.department.create()` 会把新院系挂到**创建者**身上

- 基座 `openeducat_core/models/department.py:33-38`：`self.env.user.write({'department_ids': [(4, d.id) …]})`。
- 实测（本地，教务账号 uid=12）：建 1 条院系 → `res.users.department_ids` 由 0→1（新增该 id）。
- 它**不是**权限（本仓无 ACL/ir.rule 读它），但会当作默认值：`op.faculty.allowed_department_ids`（`models/faculty.py:68-71`，默认取当前用户的 department_ids）与 `res.company.create_user`（`models/res_company.py:59`）。
- **结论**：可接受，但是个**隐形的台账式副作用**——教务建过的院系会累积在他自己账号上、成为他之后**每建一个教师档案**时「允许院系」的默认值。要不要挡（在 `edu_portal` 覆盖 `create` 不写 `env.user`）**留给队长拍板**，本轮不动。

### 3.3（2026-09-24）第二轮改前 / 改后实读（含回归对照一次跑全）

> **可重跑门禁**：`python3 tests/smoke/menu_label_audit.py --out …`（读数）→ `--diff before.json after.json`（判定，逐条 PASS/FAIL）。
> 读数经 **ORM**（`lang=zh_CN` / `en_US` 各读一次；`complete_name` 是计算字段，psql 直读不到）。
> 落盘：`tests/smoke/menu_label_audit_before.json` / `_after.json`。**改后结论 = 全绿（14 受影响项 + 30 回归项全 PASS）。**

| 记录 | 改前 zh_CN | 改后 zh_CN | 改后 en_US | 改后 complete_name（zh_CN） |
|---|---|---|---|---|
| 字段 `op.department.parent_id` | 家长部 | **上级院系** | Parent Department | —（表单字段标签） |
| 字段 `op.department.name`（P0b） | 姓名 | **名称** | Name | —（表单字段标签 / 列表列头） |
| 菜单 276 | 专业 | **培养方案** | Program Plans | 学生信息/配置/项目管理/培养方案 |
| 动作 395 | 节目 | **培养方案** | Program Plans | — |
| 菜单 264 | 批次 | **班级** | Student Batches | 学生信息/配置/教学管理/班级 |
| 动作 386 | 批次 | **班级** | Student Batches | — |
| 菜单 298 | 父母 | **家长设置** | Parent Settings | 学生信息/配置/家长设置 |
| 菜单 299 | 人际关系 | **亲属关系** | Kinship Relations | 学生信息/配置/家长设置/亲属关系 |
| 动作 415 | 人际关系 | **亲属关系** | Kinship Relations | — |
| 动作 414 | 父母 | **家长** | Parents | — |
| 菜单 297（**未动**，仅核对） | 家长 | 家长（未变） | Parents | 学生信息/家长 |

**「专业」唯一性审计（含停用菜单，本轮验收线）**：`ir.ui.menu` 里 zh_CN 名字叫「专业」的菜单

| 改前 | 改后 |
|---|---|
| 2 条：263（启用，`Majors`→op.course）、276（停用，`Programs`→op.program） | **1 条：263（启用，`Majors`→op.course）** |

**同时复跑的端到端门禁**（改名后路径可变，故必须跟着改期望再跑）：

- `python3 tests/smoke/backoffice_reachability.py --no-browser` → **PASS 62 / FAIL 0 / GAP 0**（与上一轮基线一致；
  其中「班级 / 学生信息 / 配置 / 教学管理 / 班级 → op.batch」走的正是本轮改过的菜单 264 与动作 386，
  期望已随改名更新，见 `tests/smoke/backoffice_reachability.py` 的 COVERAGE 表）。
- `python3 scripts/check_view_xpath.py` → 失败项 0（退出码 0 / INCOMPLETE，唯一未覆盖项是**既有的**外部模块边界漂移 30 ≠ 31，与本轮无关）。
- `python3 scripts/check_english.py` → 退出码 0（口径 must-fix = 0）。
- `python3 tests/smoke/department_path.py` → 见 §3.4。

### 3.4（2026-09-24）P0 的浏览器口径复核（同一脚本、同一路径）

> 用上一轮 §3.1 的**同一个**真浏览器脚本 `tests/smoke/department_path.py` 复跑
> （L1 菜单可见 → L2 动作 → L3 视图/列表 → L4 真浏览器新建保存 → 清场），
> 落盘 `tests/smoke/menu_rename2_department_path.json`，截图 `shots/smoke/dept_path_*_2026*.png`。
> 该脚本 L4 会读 `.o_form_view .o_form_label` 的**表单标签文本**——上一轮读数里这一项正是 **「家长部」**
> （`tests/smoke/department_path_before.json` 第 103 行），本轮改后同一位置应为 **「上级院系」**。
> **实测（2026-09-24，FAIL=0 WARN=0）**：`265 → 院系部门` 列表/表单全绿，真浏览器建一条 → 列表可见 → 清场残留 0；
> 而**同一读数位置**的表单标签：

| 读数（`.o_form_view .o_form_label`） | 文件 |
|---|---|
| `['姓名', '家长部', '代码']`（改前） | `tests/smoke/department_path_before.json`（上一轮留档） |
| `['姓名', '上级院系', '代码']`（改后） | `tests/smoke/menu_rename2_department_path.json`（本轮） |

> ⇒ P0 是**页面口径**验证过的，不只是 ORM 读数。同表当时还剩下的 `姓名` 已在 §3.5 的整表扫描里一并修掉（P0b）。
>
> ⚠ 判据口径提醒：本节的 `form_labels` 只是**取前 12 个**的动线读数；「整表有没有别的错名」这个问题
> 由 §3.5 的 `department_form_sweep.py` 回答（它把每一个 label 与每一个**无 label 字段**都列出来）。

### 3.5（2026-09-24）「新建院系部门」表单**整表扫描**：用户从上到下到底会看到什么

> 为什么单列一节：P0/P0b 都是**先知道错、再去修**。把这张表**逐字看一遍**是另一件事，
> 方法是新脚本 `tests/smoke/department_form_sweep.py`（真浏览器、backoffice 身份、lang=zh_CN）。
> 它列出口径：列表页列头 / 每个 `.o_form_label` / 标签→字段名映射 /
> **没有任何 label 的字段**（这类字段会静默消失在「我用眼睛看过」的结论里，必须显式列）/ 分组页签 / 按钮。
> 落盘 `tests/smoke/dept_form_labels_before.json` / `_after.json`（可直接对拍）。

**先证明「整表」真的是整表**（否则扫到的只是我以为存在的那几个）：

- `op.department` 上只有 **3 个业务字段**：`name` / `code` / `parent_id`（另有 4 个审计字段，不在表单 arch 里）；
- 该模型只有 **3 个 primary 视图**（list 1791 / form 1792 / search 1793，即 `openeducat_core.view_op_department_*`），
  **没有任何 inherit 视图**；`custom_addons/` 里**没有模块**给 `op.department` 加过字段或继承过它的表单；
- search 视图里只有 3 个 `<field>`，**没有任何 filter / group_by** ⇒ 搜索面板不产生新标签。

**改前 → 改后（逐字，同一读数位置）**

| 口径 | 改前 | 改后 |
|---|---|---|
| 新建表单标签（DOM 顺序 = 用户从上到下） | `["姓名", "上级院系", "代码"]` | **`["名称", "上级院系", "代码"]`** |
| 列表页列头（点进 265 先看到的那一屏） | `["", "姓名", "代码", "上级院系"]` | **`["", "名称", "代码", "上级院系"]`** |
| 标签 → 字段 | 姓名→name、上级院系→parent_id、代码→code | 名称→name、上级院系→parent_id、代码→code |
| **无 label 的字段** | `[]` | `[]` |
| 分组 / 页签标题 | `[]` | `[]` |
| 按钮 | `["新建"]` | `["新建"]`（未动） |
| 面包屑 | `院系部门` | `院系部门`（未动） |

**结论**：这张表**一共 3 个标签**，改后**全部正确**——名称（名）/ 上级院系（父级）/ 代码（编码）；
除 `parent_id` 与 `name` 外**没有第三处机翻或误导词**（这是「按上表逐字扫过」的结论，不是「没看」的结论）。

## 4. 不得被改坏的既有正确菜单（回归对照）

| 菜单 id | 名称 | 说明 |
|---|---|---|
| 263 | 专业（2026-09-19 前叫「课程」） | 原本正确，**不在覆盖清单内**；且是**唯一**允许叫「专业」的菜单（§3.3 唯一性审计） |
| 264 | 班级（2026-09-24 前叫「批次」） | **本轮有意改名**（§2.2 P2a），改后即回归对照的固定期望值 |
| 267 | 科目 | 原本正确，**不在覆盖清单内** |
| 343 | 会议 | 原本正确，**不在覆盖清单内** |
| 612 | 选课审批 | edu_portal 自建菜单；en_US 即中文，靠**回退**显示，无 zh_CN 槽位，**未触碰** |

> **2026-09-22 回归实读（259/265 改名后逐条复核）**：菜单 257/258/260/261/262/263/264/266/267/273/274/297/309/343/612 **一字未变**；动作 382/385/386/387/395/396/705 未变；
> **共享 msgid 的旁证（证明新串确实隔离了影响面）**：`op.course.department_id` 字段标签仍是**部门**、向导字段 `wizard.op.faculty.faculty_ids` 仍是**院系**、动作 389/323/324/535 仍是 **院系/部门**。
> 收口与权限门禁同批复跑：`python3 tests/smoke/backoffice_reachability.py --no-browser` → **PASS 62 / FAIL 0 / GAP 0**（含 专业/班级/科目 三条菜单路径与 3 条 E2E 流程）。
>
> **2026-09-24 回归实读（第二轮改名后逐条复核，口径 = `menu_label_audit.py --diff`）**：
> 菜单 **257/259/261/262/263/265/266/267/273/274/277/279/280/287/291/343/612/797 一字未变**；
> 动作 **380/385/388/393/396/705/815 一字未变**；字段 **`op.department.code`=代码 未变**；
> **共享 msgid 的旁证（证明新串确实隔离了影响面）**：`op_course`/`op_program`/`op_subject` 三个
> `department_id` 字段标签**仍是「部门」**（本轮改了 `op.department` 的 parent_id 与几条菜单，
> 一个都没被带跑）；动作 705（`slide.channel` 在线课程）仍是「课程网页」。
> 门禁：`backoffice_reachability --no-browser` **PASS 62 / FAIL 0 / GAP 0**；`department_path.py`（真浏览器）**FAIL=0**。
>
> **2026-09-24 第三遍（P0b 之后）全量复跑**（三连升级 `-u edu_portal` → `--i18n-overwrite -u edu_zh` → `-u edu_nav` 均 exit 0 之后）：
> 菜单 **259 教职员工 / 265 院系部门 / 263 专业 / 264 班级 / 797 已停用班级** 等 18 条、动作 **380/385/388/396/705/815** 等 7 条
> **一字未变**（`menu_label_audit.py --diff` → **14 受影响项 + 30 回归项全绿**，退出码 0）。
> 两个**当时改了期望但没重跑**的套件本轮**补跑**：
> `tests/smoke/class_batch_mgmt.py` → **66 条断言 PASS 66 / FAIL 0**（含 CB5.1 已按「班级」更新后仍通过）；
> `tests/smoke/major_track_elective.py` → **PASS=50 / FAIL=0 / SKIP=2 → ALL PASS**（V8.4 实测 `264=班级`，
> V8.6 实测 `276=培养方案|Program Plans|…|False`）。
> 表单整表扫描见 §3.5。

## 5. 已知影响面（重要，别当没发生）

- ⚠ **本条的措辞已被 §0.3 修正**：Odoo 19 的词条是**按 PO 里的 `#:` 引用落到具体 xmlid**，
  不是「按 msgid 全局生效」。下面这段结论**只在「同一个 xmlid 被多处引用」时才成立**；
  真正会「一并改」的情况是**同一条记录**被多个视图/字段共用同一 source 串。
- **PO 覆盖按 `msgid` 全局生效**（历史措辞，见上方提醒）：同一个 source 串在**其他模块/位置**也会一并改。
  本次涉及的通用串：`General`→「通用」、`Profile`→「档案」、`Attendance`→「考勤」、`Parents`→「家长」、`SIS`、`Programs`、`Submissions`。
  这些词在学校语境下新译名都更贴切；**若将来发现某处因此别扭**，处理办法是给该处单独造词条（PO 无法按记录区分）。
- **source（en_US）一律未改**：只动译文、不动基座数据 ⇒ 基座升级时不冲突。
- 繁体（zh_TW）同步覆盖（见同目录 `zh_TW.po`）。