# 费用分类可配置化调研（edu.fee.bill.category → 可自助新增的分类模型）

> 日期：2026-09-16 ｜ 触发：校长要求把「分类」换成校方自己的清单（统筹/房租/交通/活动/接待/补助/补贴/课时费/粮草/日常物品/奉献/礼物），且**校方要能自己新增分类，不想每次都让程序员改代码**。
> 铁律 0 落盘：本文件为设计前置调研，不含任何代码改动。
> **取证环境**：Odoo 19 源码取自本机容器 `edu19-clone-web-1`（镜像 `odoo:19`，digest `odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd`），路径 `/usr/lib/python3/dist-packages/odoo/addons/`；上游对照 https://github.com/odoo/odoo/tree/19.0 。库内数据取自容器 `edu19-clone-db-1` 的 `edu19` 库。
> **行号会漂移**：本报告行号取自上述镜像与 19.0 分支当日快照，实施时以本机实测为准。

---

## 一、结论摘要（每条一句话 + 出处）

1. **Odoo 19 核心的「费用类别」就是 `product.product`，不是 `product.category`** —— `hr.expense.product_id` 是 `Many2one('product.product')`，字段标签直接写作 `string="Category"`，过滤域 `can_be_expensed`（本机 `/usr/lib/python3/dist-packages/odoo/addons/hr_expense/models/hr_expense.py:97-103`；上游 [hr_expense.py#L97-L103](https://github.com/odoo/odoo/blob/19.0/addons/hr_expense/models/hr_expense.py#L97-L103)）。
2. **`product.category` 不管费用分类，它管的是「产品分组 + 会计科目默认值」** —— 该模型全文无任何 expense 字段，核心 hr_expense 完全没引用它；会计侧才有 `property_account_expense_categ_id`（本机 `/usr/lib/python3/dist-packages/odoo/addons/product/models/product_category.py:9-21`；`/usr/lib/python3/dist-packages/odoo/addons/account/models/product.py:15-24`）。
3. **OCA 没有、也不需要「可配置收费项目」模块** —— OCA/vertical-education 在 13.0–19.0 是**空仓库**、OCA 内 `fee`/`student` 关键词仓库数为 0、`OCA/hr-expense` 的 19.0 分支只有 copier 脚手架；且 OCA 实测仓库级 license 全为 **AGPL-3.0**（[vertical-education](https://raw.githubusercontent.com/OCA/vertical-education/19.0/README.md)、[hr-expense@19.0 清单](https://data.jsdelivr.com/v1/package/gh/OCA/hr-expense@19.0/flat)、https://api.github.com/repos/OCA/hr-expense）。
4. **同类系统里唯一能直接对标的形态是校管家的「收支类别」** —— 校方在【账务管理 → 数据维护 → 账户设置 → 收支类别】点「新增」、选「收入/支出」+ 填名称即可自助新增（官方帮助中心，[wiki.xiaogj.com](https://wiki.xiaogj.com/docs/shu-ju-wei-hu-she-zhi-shou-kuan-zhang-hu-shou-zhi-lei-bie)，最近修改 2025-02-10）。
5. **推荐方案：自建 `edu.fee.category` 小模型（name/code/sequence/active/可选 direction_hint），不用 product.product、不用 product.category、不用 account.account** —— 因为 Odoo 核心那套是给员工报销用的（本库 `hr_expense` 实测 **uninstalled**），而本项目**已有同构先例** `edu.download.category`（`custom_addons/edu_portal/models/downloads.py:13-25`：name/parent_id/sequence/active + 计数 + unlink 防护），照抄学习成本≈0。

---

## 二、逐问题证据

### Q1｜Odoo 19 核心怎么建模「费用类别 / 收入类别」？

#### 1.1 `hr.expense` 的费用类型 = `product.product`（且 19.0 起开关落在 `product.template`）

本机 `/usr/lib/python3/dist-packages/odoo/addons/hr_expense/models/hr_expense.py:96-104`：

```python
# product_id is not required to allow to create an expense without product via mail alias, but should be required on the view.
product_id = fields.Many2one(
    comodel_name='product.product',
    string="Category",
    tracking=True,
    check_company=True,
    domain=[('can_be_expensed', '=', True)],
    ondelete='restrict',
)
```

同文件 `:1253-1257` 核心代码自己就把 `product.product` 称作 category：

```python
raise UserError(_("You need to have at least one category that can be expensed in your database to proceed!"))
```

「可报销」开关定义在 **product.template**，不是 product.category —— 本机 `/usr/lib/python3/dist-packages/odoo/addons/hr_expense/models/product_template.py:18-19`：

```python
can_be_expensed = fields.Boolean(string="Expenses", compute='_compute_can_be_expensed',
    store=True, readonly=False, help="Specify whether the product can be selected in an expense.")
```

同文件 `:21-31` 的 `_auto_init()` 会为新列回填：`UPDATE product_template SET can_be_expensed = false WHERE type NOT IN ('consu', 'service')`。
上游对照（行号一致）：[hr_expense.py#L97](https://github.com/odoo/odoo/blob/19.0/addons/hr_expense/models/hr_expense.py#L97-L103)、[hr_expense/models/product_template.py#L18](https://github.com/odoo/odoo/blob/19.0/addons/hr_expense/models/product_template.py#L18-L31)。

**校方能不能自助新增？能，而且是标准动作** —— 本机 `/usr/lib/python3/dist-packages/odoo/addons/hr_expense/views/hr_expense_views.xml:647` 有菜单：

```xml
<menuitem id="menu_hr_product" name="Expense Categories" parent="menu_hr_expense_configuration" .../>
```

配 `views/product_product_views.xml:32`（form `string="Expense Categories"`）与 `:131`（action name）。
Odoo 官方 19.0 文档原话：「Expense *categories* are managed like *products* in Odoo」「To create a new expense category, navigate to Expenses app → Configuration → Expense Categories. Click New」——[odoo/documentation@19.0 expense_categories.rst](https://github.com/odoo/documentation/blob/19.0/content/applications/finance/expenses/expense_categories.rst)。

> ⚠️ **本条对我们最关键的推论**：「用 product.product 当费用分类」在 Odoo 里是正统做法，但它的宿主是 **Expenses（hr_expense）** 这个员工报销应用。本库实测 `hr_expense` 状态 = **uninstalled**（`docker exec edu19-clone-db-1 psql -U odoo -d edu19 -c "SELECT name,state FROM ir_module_module WHERE name='hr_expense'"` → `uninstalled`），且 `product_template.can_be_expensed` 这一列在本库**根本不存在**（该列由 hr_expense 的 `_auto_init` 创建）。走这条路 = 为「给账单分类」而装一整套员工报销 + hr 依赖。

#### 1.2 `product.category` 承担什么

本机 `/usr/lib/python3/dist-packages/odoo/addons/product/models/product_category.py` 关键行：

| 行 | 内容 |
|---|---|
| `:9` | `_name = 'product.category'` |
| `:13` | `_parent_store = True`（树形层级） |
| `:15` | `_order = 'complete_name'` |
| `:17` | `name = fields.Char('Name', index='trigram', required=True)` |
| `:21` | `parent_id = fields.Many2one('product.category', 'Parent Category', index=True, ondelete='cascade')` |

- **全文 grep `expense` 无命中**（`docker exec edu19-clone-web-1 grep -rn "expense" .../product/models/product_category.py` → 空）。它自己不承担费用分类语义。
- 它在会计侧被扩展来**确定默认科目**：本机 `/usr/lib/python3/dist-packages/odoo/addons/account/models/product.py:15`（`_inherit = "product.category"`）、`:17`（`property_account_income_categ_id`）、`:24`（`property_account_expense_categ_id`）、`:68`（`_get_product_accounts`）。
- 产品挂分类：本机 `/usr/lib/python3/dist-packages/odoo/addons/product/models/product_template.py:81-84` `categ_id = fields.Many2one(comodel_name='product.category', ...)`。
- 后台入口：本机 `/usr/lib/python3/dist-packages/odoo/addons/account/views/account_menuitem.xml:62` → `Product Categories`，挂在 **Invoicing** 菜单下，`groups="account.group_account_invoice,account.group_account_readonly"`（即需要开票/会计权限）。

**结论**：`product.category` = 产品分录的「组」，附带会计科目默认值。把它当费用分类用属于语义错位，且会让费用分类与库存/产品报表混在一棵树里。

#### 1.3 `account.account` 承担什么

本机 `/usr/lib/python3/dist-packages/odoo/addons/account/models/account_account.py`：

| 行 | 内容 |
|---|---|
| `:20` | `_name = 'account.account'` |
| `:33` | `name = fields.Char(string="Account Name", required=True, index='trigram', tracking=True, translate=True)` |
| `:39` | `code = fields.Char(string="Code", size=64, tracking=True, compute='_compute_code', ...)` |
| `:44-70` | `account_type = fields.Selection([...19 个值...], required=True, ...)` |

`account_type` 的 19 个值：`asset_receivable / asset_cash / asset_current / asset_non_current / asset_prepayments / asset_fixed / liability_payable / liability_credit_card / liability_current / liability_non_current / equity / equity_unaffected / income / income_other / expense / expense_other / expense_depreciation / expense_direct_cost / off_balance`。

**结论**：`account.account` 是**总账科目**。建一个科目必须从 19 种会计类型里选一个、还有编码唯一性等约束 —— 业务含义直接进财务报表，**绝对不该让校长自助新增**。

#### 1.4 小结：三个模型谁是谁

| 模型 | Odoo 里的角色 | 谁维护 | 校方可自助新增 | 适合当「收费/支出分类」吗 |
|---|---|---|---|---|
| `product.product`（+ `can_be_expensed`） | **员工报销的费用类别**（hr_expense 专用） | 财务/HR（Expenses → Configuration → Expense Categories） | 技术上可以，但本库需**先装 hr_expense** | ✗ 宿主是员工报销应用；会引入 hr 依赖与会计科目绑定 |
| `product.category` | 产品分组 + 会计科目默认值 | 会计/仓管（Invoicing → Product Categories） | 可以（需会计权限） | ✗ 语义错位；与产品/库存共用一棵树 |
| `account.account` | 总账科目（法定报表口径） | 会计（专业门槛高） | 不该 | ✗ 会把业务分类污染成会计科目 |
| **自建 `edu.fee.category`** | **业务台账分类** | 教务/校长 | **可以（本项目的既有形态）** | ✓ 见 Q4 |

---

### Q2｜OCA 有没有现成的「可配置收费项目」模块？

**答案：没有。明确的没有。** 三条独立证据：

1. **OCA 的教育纵向仓库是空壳。** `OCA/vertical-education` 在 13.0–19.0 **全部没有模块**，只有 LICENSE/setup 脚手架；README 的 addons 表为空；19.0 HEAD = 2025-09-30「Initial commit」。逐版本文件数（jsDelivr 清单）：13.0=12、14.0=19、15.0=17、16.0=17、17.0=14、18.0=15、19.0=16 —— 均无教育模块。
   证据：https://raw.githubusercontent.com/OCA/vertical-education/19.0/README.md ｜ https://data.jsdelivr.com/v1/package/gh/OCA/vertical-education@17.0/flat
2. **OCA 组织内按关键词穷举命中数为 0。** `org:OCA education` 仅 1 个仓库（就是上面的空壳）；`org:OCA student` = 0；`org:OCA fee` = 0；`org:OCA school` / `university` 都指向同一个空壳。证据：https://api.github.com/search/repositories?q=org:OCA+fee
3. **最接近的 `OCA/hr-expense` 在 19.0 上零模块。** 19.0 HEAD = 2026-08-13「Merge pull request #379 … 19.0-dck-copier」，根目录仅 15 个脚手架文件、jsDelivr 清单 0 个模块；对照 18.0 = 268 文件 / 13 个 `hr_expense_*` 模块，**全是报销流程**（预支核销 / 付款 / 关联发票 / 备用金 / 异常），不含「费用类别维护」。
   证据：https://api.github.com/repos/OCA/hr-expense/branches/19.0 ｜ https://data.jsdelivr.com/v1/package/gh/OCA/hr-expense@18.0/flat

**License：OCA 是 AGPL-3.0 地带，须评估。** 本机实测 `api.github.com/repos/OCA/{hr-expense, account-analytic, account-financial-tools, vertical-education, hr}` 五个仓库的 `license.spdx_id` **全部 = `AGPL-3.0`**，`default_branch` 全部 = `18.0`。
（注意 OCA README 明确「each module can have a totally different license」—— repo 级 AGPL ≠ 模块级，需逐个 `__manifest__.py` 核。）

**AGPL 对「SaaS 部署但不分发源码」的实际影响**（据一手条文，非法律意见）：
- AGPLv3 §13 原文：「if you modify the Program, your modified version must prominently offer all users interacting with it remotely through a computer network … an opportunity to receive the Corresponding Source」—— https://www.gnu.org/licenses/agpl-3.0.txt
- FSF 官方解释：「if you run a modified program on a server and let other users communicate with it there, your server must also allow them to download the source code corresponding to the modified version」—— https://www.gnu.org/licenses/why-affero-gpl.html
- OCA 官方立场：「a Proprietary module cannot depend on an AGPLv3 module」—— https://www.odoo-community.org/blog/news-updates-1/oca-odoo-meeting-on-licenses-21
- ⇒ 原样并列安装不触发源码义务；**一旦修改该 AGPL 模块并让外部用户经网络使用，§13 要求向这些用户提供修改版 Corresponding Source**；且我们的专有模块不得 `depends` AGPL 模块。

**顺带核实到的生态件（与本项目基座同源，值得知道）**：
`openeducat_fees` 就在本仓基座里、且**已安装** —— `openeducat_erp/openeducat_fees/__manifest__.py`：`'version': '19.0.1.0'`、**`'license': 'LGPL-3'`**、`'summary': 'Manage Fees'`、`'depends': ['openeducat_core', 'account']`（本库实测 `openeducat_fees = installed`）。但它**不是分类字典**，见 Q4。

---

### Q3｜同类系统怎么建「费用类别」？校方能否自助新增？

#### 3.1 Moodle：有官方支付子系统，但**没有费用类别字典**

- 核心内置支付子系统 **Payment API / Payment accounts**（实体 `core_payment\account`、`account_gateway`、`gateway`、`local_entities\payable`；网关插件类型 `paygw`，核心网关仅 paypal）。站点管理员可自助建账户：capability `moodle/payment:manageaccounts`。证据：https://github.com/moodle/moodle/tree/main/public/payment
  （**注意路径变更**：主分支 docroot 已移入 `public/`，旧路径 `/tree/main/payment` 现在 404。本机实测 `raw.githubusercontent.com/moodle/moodle/main/payment/...` 全部 404，而 `MOODLE_405_STABLE/payment/classes/helper.php` = 200。）
- 核心内置报名费 **Enrolment fee（`enrol_fee`）**：费用 = **每个选课实例的 `cost` + `currency`**，不是可复用的分类。本机实测 `MOODLE_405_STABLE/enrol/fee/classes/plugin.php`：
  - `:335-341` `$mform->addElement('text','cost', get_string('cost','enrol_fee'))` / `$mform->addElement('select','currency', ...)`
  - `:252-253` `'cost' => $data->cost, 'currency' => $data->currency`
  - `:223` `'cost' => \core_payment\helper::get_cost_as_string($cost, $instance->currency)`
  证据：https://github.com/moodle/moodle/blob/main/public/enrol/fee/classes/plugin.php ｜ https://phpdoc.moodledev.io/5.0/da/df1/classenrol__fee__plugin.html
- **未验证**：`docs.moodle.org` / `moodle.org` 本机全部 **HTTP 403（Cloudflare）**，故 Moodle 官方文档页与插件目录（第三方 `paygw` 如 stripe）本次**未能核实**，不作结论。

**对我们的意义**：Moodle 连「费用类别」这个概念都没有，无从抄起 —— 这条正好反证「自建分类字典是本项目需要自己走的一段路」。

#### 3.2 Canvas LMS：核心仓库**不含**收费/账单模型

`instructure/canvas-lms`（AGPLv3）`app/models` 共 335 个模型，全量 grep `fee|bill|charge|invoice|pay|price|order|cost|tuition|wallet|credit|commerce|store` 仅命中外链 feed / 翻译反馈等噪声；`gh search code --repo instructure/canvas-lms "invoice"` = 0 命中。证据：https://github.com/instructure/canvas-lms/tree/master/app/models
Instructure 的收费/账单属商业侧产品，**未验证**。

#### 3.3 国内同类：**校管家是可对标的硬证据**

| 厂商 | 校方能否自助新增 | 功能名 / 操作路径（原文） | 来源等级 + URL |
|---|---|---|---|
| **校管家** | **✅ 能 —— 独立「收支类别」字典** | 【账务管理 → 数据维护 → 账户设置】→【收支类别】→ 点「新增」→ 选「收入 / 支出」+ 填名称；原文另注「如果直接新增为**大类**需要确保该**大类**下有一个**小类**」 | **官方帮助中心**（本机抓到正文，页脚「最近修改 2025-02-10」，标注适用「企业版」）：https://wiki.xiaogj.com/docs/shu-ju-wei-hu-she-zhi-shou-kuan-zhang-hu-shou-zhi-lei-bie |
| 校管家 | ✅ 另有一套「收费类型」也可自定义 | 《如何自定义收费费类型？》：内置「新增、续费、扩科」，可在【系统设置 → 基础参数设置 → 收费类型】新增，前台收费时下拉选择 | **官方帮助中心**：https://helpcenter.xiaogj.com/help-list/detail-607.html |
| 学邦技术 | ✅ 能（但走「课程产品」绕行，无独立字典） | 【设置 → 课程设置 → 新增课程产品】→ 课程类型选【其他】；填课程分类（教材费/学杂费）、项目分类（服务费/教材费），课程名称「可以自定义编辑」 | **官方帮助中心**：https://www.xuebangsoft.com/help/shezhi/94960.html |
| 学邦技术 | ❓ 是否存在独立「收支类别」字典 | 帮助中心「财务」类目逐页看过，只有收款管理/退费/流水/封账，**未见**收支类别字典 | **未验证**（不构成否定证据）；BOSS 帮助中心为 JS 动态加载：https://boss.xuebangsoft.net/eduboss/helpCenter/index.html |
| 校宝在线 | ⚠️ 部分 | 《如何设置课程收费模式？》：「当课程需要多种收费标准时，可以点击收费标准后的【+】号添加」 | **官方**：https://www.xiaobao100.com/Help_QAndA?s=%E6%94%B6%E8%B4%B9 |
| 爱耕云 / 十克助教 / 希沃 | ❓ 未验证 | 官网只到宣传层，无「收费项目/支出类别」可自助新增的官方文档 | **未验证**：http://www.aigengyun.cn/ ｜ https://mm-jia.cn/ ｜ https://www.seewo.com/product/platform |

> **最有价值的一条**：校管家的「收支类别」形态 = **独立字典 + 收入/支出二分 + 大类/小类两级 + 自助新增**，并且它和「收费类型」是两套东西（前者对账务流水，后者对收费动作）。这与我们 `edu.fee.bill` 的 `direction`(receivable/payable) 双向台账**天然同构** —— 说明「自建分类小模型」不是我们拍脑袋，行业头部产品就是这么做的。

---

### Q4｜推荐方案与理由

## 推荐：自建 `edu.fee.category` 小模型（不装、不蹭现成模型）

```
edu.fee.category
  name           Char   required          # 分类名（校方输入）
  code           Char   required + unique # 稳定技术码，用于迁移/导出/筛选（如 rent / transport）
  sequence       Integer default 10       # 排序
  active         Boolean default True      # 停用而非删除（历史账单还要显示）
  direction_hint Selection(receivable/payable/both) default 'both'   # 仅做新建账单时的默认值提示，不强制
  note           Char                      # 备注
```

`edu.fee.bill.category` → `fields.Many2one('edu.fee.category', string='分类', required=True, ondelete='restrict')`

#### 理由（逐条对应取舍维度）

1. **学习成本 ≈ 0，因为本项目已经有一个一模一样的先例。**
   `custom_addons/edu_portal/models/downloads.py:13-25` 的 `edu.download.category`：`name` / `parent_id` / `sequence` / `active` + `file_count` 计算字段 + `unlink()` 非空禁删防护，配后台菜单与门户 `/downloads/manage` 管理页。**整套「小模型 + 自助增删 + 防误删」的模式在本仓已跑通并上线**，抄它即可，不需要新的架构决策。
2. **后台菜单天然**：既有 `财务管理`（`custom_addons/edu_portal/views/fees.xml:182`，`groups="openeducat_core.group_op_back_office_admin,-base.group_user"`）下面已经挂着「账单管理」「缴费流水」；加一个 `费用分类` 子菜单（`sequence=5`）即可，位置、权限组、图标体系全部复用，校长一眼能找到。
3. **迁移成本极低（本库实测）**：`edu19` 库 `edu_fee_bill` **总共 2 行**，且**全部**是 `direction=receivable, category='other'`（`SELECT direction, category, count(*), sum(amount) FROM edu_fee_bill GROUP BY 1,2` → 只有一行 `receivable | other | 2 | 12300.00`）；`reimburse_state IS NOT NULL` 的行数 = 0；`op_fees_terms` = 0。⇒ 本环境可以**先建新表 → 一条 UPDATE 全量重映射 → 再删旧列**，无历史包袱。（生产库数量待确认，见「未验证」。）
4. **为什么不用 `product.product`（Odoo 核心那套）**：
   - 本库 `hr_expense` **uninstalled**，`product_template.can_be_expensed` 列不存在 ⇒ 要先装 hr_expense，而它 `depends` hr → 引入员工档案 + 报销审批整套工作流，为一个「分类下拉框」付这个代价不划算。
   - product 自带 `sale_ok/purchase_ok`/税/科目绑定/价格 等一堆与「分类」无关的字段，校长新增一个「接待」分类会被要求理解这些。
   - 与我们的 `direction` 双向台账语义冲突：product 是「可卖/可买」的物料/服务，而我们的类别同时要覆盖应收（学生交）与应付（学校付）。product 的 sale/purchase 二分与 receivable/payable 并不是一回事。
5. **为什么不用 `product.category`**：见 Q1-1.2 —— 核心 hr_expense 压根没用它；它承载的是产品分组 + 会计科目默认值。拿它当费用分类 = 语义错位 + 与库存/产品报表共用一棵树 + 需要会计权限才能维护。
6. **为什么不用 `account.account`**：见 Q1-1.3 —— 19 种会计类型 + 编码唯一性约束 + 直接进法定报表。让校长自助建科目是**风险敞口**，不是便利。
7. **与 `direction` 双向台账的契合度**：新模型可加 `direction_hint` 只做**默认值提示**（例如选「房租」时默认把 direction 拨到 payable），但不强制绑定 —— 因为同一分类在业务上确实两边都可能（如「交通」既可能是学生交通费应收，也可能是校车油费应付；历史 2 条数据里的 `other` 就是 receivable）。这点比 product.product 的 sale_ok/purchase_ok 硬绑定更贴合我们。

#### 顺带说明：`openeducat_fees` 已装，但**不是**分类字典

`openeducat_erp/openeducat_fees/models/fees_terms.py:37-68` 的 `op.fees.terms`（name/code/active/分期 lines/discount，且 `line_ids` 的 `value` 之和必须 = 100%）是**「课程收费方案」**（按天/按日期分期收款）；
`openeducat_erp/openeducat_fees/models/fees_element.py:24-33` 的 `op.fees.element` 是「某个分期下的费用明细行」，**其 `product_id` 仍指向 `product.product`**。
⇒ 它同样是「用 product.product 当费用项」，而且形态是**百分比拆分的课程收款计划**，不是「自由记账用的分类字典」，且本库 `op_fees_terms` 0 行、挂在 `openeducat_core.menu_op_school_config` 下（`openeducat_erp/openeducat_fees/views/fees_terms_view.xml:117-121`，`groups=openeducat_fees.group_op_fees_admin`）。**可以继续留作课程收费方案，但解决不了我们这次的诉求。**

#### 备选方案对比表

| 方案 | 校方自助新增 | 后台菜单位置 | 迁移成本 | 与 direction 契合 | 依赖代价 | 裁决 |
|---|---|---|---|---|---|---|
| **自建 `edu.fee.category`** | ✅ 复刻 `edu.download.category` 先例 | 「财务管理 → 费用分类」（复用既有根菜单） | 极低（2 行数据） | ✅ 可加 direction_hint，不强制 | 无 | **推荐** |
| `product.product` + `can_be_expensed` | ✅（标准动作） | Expenses → Configuration → Expense Categories | 中（2 行可映射，但要建 product 数据 + 装模块） | △ sale/purchase 与 receivable/payable 不同构 | 需装 `hr_expense`（拉 hr 依赖） | 不推荐 |
| `product.category` | ✅（需会计权限） | Invoicing → Product Categories | 中 | ✗ | 无新依赖但语义错位 | 不推荐 |
| `account.account` | ⚠️ 技术可行，业务不该 | 会计 → 科目表 | 高（要定编码 + account_type） | ✗ | 高阶会计门槛 | 不推荐 |
| OCA 现成模块 | — | — | — | — | **不存在**（Q2） | 无此选项 |
| 复用 `openeducat_fees` | ✅（Fees Terms 可新建） | 学校配置 → Fees Terms | 中 | ✗ 是课程收费方案，非台账分类 | 已在装 | 不适用 |

---

### Q5｜迁移映射建议（旧 7 值 → 新清单）

**旧值**：`tuition` 统筹费 / `textbook` 教材 / `activity` 活动 / `transport` 交通 / `printing` 打印 / `fine` 罚款 / `other` 其他
**新清单（校长给的 12 项）**：统筹、房租、交通、活动、接待、补助、补贴、课时费、粮草、日常物品、奉献、礼物

| 旧值 | 旧中文 | **建议** | 新模型中的记录 | 理由 |
|---|---|---|---|---|
| `tuition` | 统筹费 | **改名并入「统筹」** | `code=general, name=统筹` | 同义，只是旧的带「费」字。建议**统一叫「统筹」**以贴合校长清单；若门户文案想保留旧称，可在展示层做映射，但**数据层只留一条** |
| `textbook` | 教材 | **保留为独立项「教材」** | `code=textbook, name=教材, direction_hint=receivable` | 新清单确实没有对应项。教材费是典型的**对学生应收**，性质上归不到「日常物品」（那是学校采购支出）也归不到「活动」。硬塞会丢失可对账性 |
| `activity` | 活动 | **原样保留** | `code=activity, name=活动` | 完全对应 |
| `transport` | 交通 | **原样保留** | `code=transport, name=交通` | 完全对应 |
| `printing` | 打印 | **归入「日常物品」**（默认建议） | 迁移到 `code=daily, name=日常物品` | 打印/复印属日常耗材。**例外**：若学校要单独核算打印成本，则保留独立项「打印」；建议按「归入日常物品」先做，校长有异议再加一条分类即可（这正是本方案的价值） |
| `fine` | 罚款 | **保留为独立项「罚款」** | `code=fine, name=罚款, direction_hint=receivable` | 罚款是**应收**且带纪律/审计意义，与「日常物品」（支出）性质完全不同，不能混类 |
| `other` | 其他 | **保留为独立项「其他」+ 设为新模型 default** | `code=other, name=其他, sequence=999, direction_hint=both` | 兜底项必须存在。新模型的 `default` 指向这条，保证「不选分类」时的行为与现状一致 |

**由此得到的初始分类清单 = 校长给的 12 项 + 教材 + 罚款 + 其他 = 15 条**（若打印也保留独立项则 16 条）。

**`direction_hint` 建议初值**（只是新建账单时的默认值，不限制使用）：

| 类别 | 建议 hint | 说明 |
|---|---|---|
| 统筹、活动、交通、教材、罚款 | `receivable` | 多为向学生/家长收款 |
| 房租、接待、补助、补贴、课时费、粮草、日常物品 | `payable` | 多为学校向外付款 |
| 奉献、礼物、其他 | `both` | 方向不确定，先 both 由校长后续收敛 |

> ⚠️ 需校长确认的两点：(a)「打印」是否并入「日常物品」；(b) 新清单是否需要「教材 / 罚款 / 其他」这三条补充项（我的建议是**需要**，否则存量应收账单会丢标签）。

---

## 三、改造影响面（供后续实施参考，本次未改任何代码）

改动会波及以下**已知**消费点（本机 grep 实测），实施时需一并处理：

| 文件 | 位置 | 现状 |
|---|---|---|
| `custom_addons/edu_portal/models/fees.py` | `:21-29` `FEE_CATEGORIES` 常量、`:77-79` `category = fields.Selection(...)`、`:228` `dict(FEE_CATEGORIES).get(self.category,...)`（报销通知文案） | 定义源 + 一处 label 反查 |
| `custom_addons/edu_portal/controllers/fees.py` | `:25-27` `_CATEGORY_LABEL` 字典（**与模型常量重复**）、`:39`、`:135`、`:177`、`:252` | 门户侧 label 映射 |
| `custom_addons/edu_portal/controllers/ledger.py` | `:72-73`、`:129-130`、`:216-217`、`:245`、`:311-323`、`:350-396`、`:465`（筛选下拉、新建台账表单、CSV 导出，共约 15 处） | 内部台账页；`:318-319` 有「非法值回退 other」逻辑 |
| `custom_addons/edu_portal/views/fees.xml` | `:68`（list）、`:106`（form）、`:281-283`（门户下拉 `t-foreach="category_label.items()"`）、`:348/:387/:445` | 后台 + 门户模板 |
| `custom_addons/edu_portal/views/ledger.xml` | `:92-96`、`:173`、`:239-240`、`:378` | 台账筛选/新建/展示 |
| `tests/smoke/p3_ledger_smoke.py` | `:125/:148/:244/:374/:425/:444/:459` 硬编码 `transport`/`printing`/`fine` | 冒烟门禁 |
| `tests/smoke/p3_prod_ledger_smoke.py` | `:239` `transport`、`:385` `printing` | 冒烟门禁 |
| `tests/smoke/ledger_select_labels.py` | `:79-81` 断言「字母化顺序 + 精确 label 集合」 | **最容易被漏掉的门禁**：它逐字比对新下拉框的 7 个 label |

⚠️ 特别注意 `git log` 里最近一条 `24f2f8c fix(ledger): 下拉框字母化（QWeb 遍历 dict 未 .items()）— 8 处修复 + 离线门禁 + 运行时断言`：下拉框渲染对「遍历顺序」有硬性断言，改成 `Many2one` 后**排序语义会从「字母序」变成「sequence」**，必须同步更新该门禁。

---

## 四、未验证 / 待确认清单（**不得当结论用**）

| # | 事项 | 为什么未验证 |
|---|---|---|
| 1 | Moodle 官方文档页与插件目录（`docs.moodle.org`、`moodle.org/plugins`） | 本机 **HTTP 403（Cloudflare）**；故第三方 `paygw` 插件（stripe 等）与官方措辞未核实 |
| 2 | Canvas 的收费/账单模块（Canvas Catalog 等） | Instructure 商业侧**未开源**，核心仓库无此模型 |
| 3 | 学邦是否存在**独立**「收支类别」字典 | 帮助中心「财务」类目未见；BOSS 帮助中心 JS 动态加载未取到正文。**不构成否定证据** |
| 4 | 校宝在线的「支出类别」自助新增 | 帮助中心搜索 0 结果，但页面 JS 渲染，**不构成否定证据** |
| 5 | 爱耕云 / 十克助教 / 希沃的收费分类自助新增 | 官网仅宣传层，无官方帮助文档 |
| 6 | **生产库** `edu_fee_bill` 的真实行数与 category 分布 | 本次只核了本机 clone 库（2 行，全 `other`）。生产库需另行确认 |
| 7 | OCA 各仓库 **19.0 分支 HEAD 提交时间** | GitHub 未认证 API 触发限流（60/h）；只用到了仓库级 `pushed_at` |
| 8 | FSF FAQ 条目 `#UnreleasedModsAGPL` 的**答案正文** | 页面在 10 万字符处被截断，仅确认题目存在 |
| 9 | `openeducat_fees` 后台实际可用性（新建 Fees Terms 的 UI 流程） | 只读了源码，未在界面上实测 |
| 10 | 校长对新清单的两处确认 | (a)「打印」是否并入「日常物品」；(b) 是否接受补充「教材 / 罚款 / 其他」三条 |
| 11 | 行号时效 | 本报告行号取自 `odoo@sha256:f99ffac…` 镜像与 19.0 分支当日快照，上游后续提交可能漂移 |

---

## 五、下一步建议（不在本次范围）

1. 校长确认 Q5 的两个待定点（打印归属、是否留教材/罚款/其他）。
2. 设计文档阶段参考 `custom_addons/edu_portal/models/downloads.py` 的 `edu.download.category` 直接复用其形态（含 `unlink()` 防误删）。
3. 实施时同步更新 `tests/smoke/ledger_select_labels.py` 的 label 集合断言与排序断言。
4. 生产库迁移前，先跑一次 `SELECT direction, category, count(*) FROM edu_fee_bill GROUP BY 1,2` 核对真实分布。
