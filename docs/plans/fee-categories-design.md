# 费用分类可配置化（edu.fee.category）设计
> **状态**：`已上线` ｜ **主题**：`费用分类可配置化` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 上游调研：`docs/research/fee-categories.md`（291 行，2026-09-16，每条结论带一手来源）
> 需求来源：校长 2026-09-16 —— 「分类有统筹、房租、交通、活动、接待、补助、补贴、课时费、粮草、日常物品、奉献、礼物……最好是可以自己创建」
> 现状缺陷背景：该字段此前是**硬编码 Selection**，且因「QWeb 遍历 dict 未 .items()」导致下拉框字母化、记账落库为兜底值（缺陷 #25/#26，已修）

## 1. 目标 / 非目标

**目标**
- 校方在后台**自助增删改**费用分类（不改代码、不求程序员）。
- 全站分类口径统一：记账表单、台账筛选、费用账单页、报销申请、CSV 导出、汇总展示，全部读同一份档案。
- 存量数据零丢失迁移（旧 7 个 code 逐一映射）。

**非目标**
- 不做「收入/支出」两套独立字典（用可选的方向倾向字段表达即可，见 §3）。
- 不引入 Odoo 总账（account.account）或产品（product.product）体系 —— 调研已排除，理由见调研 §Q1/§Q4。
- 不做多级分类（校管家支持大类/小类；我们账单量级用不上，需要时再加 parent_id，先例 edu.download.category 已有两级写法可抄）。

## 2. 数据模型（照抄本项目同构先例）

先例：`edu.download.category`（`custom_addons/edu_portal/models/downloads.py:13-25`）—— 同样是「校方自助维护的字典表」。

```python
class EduFeeCategory(models.Model):
    _name = 'edu.fee.category'
    _description = '费用分类'
    _order = 'sequence, id'

    name = fields.Char('分类名称', required=True)
    code = fields.Char('代码', required=True, index=True,
                       help='英文/拼音短码，用于 CSV 与脚本引用；建后不建议改')
    sequence = fields.Integer('排序', default=10)
    active = fields.Boolean('启用', default=True)
    direction_hint = fields.Selection(
        [('receivable', '应收'), ('payable', '应付')], string='方向倾向',
        help='留空=两边都能用；填了就只在该方向的记账表单里出现')
    note = fields.Char('说明')
    _code_uniq = models.Constraint('UNIQUE(code)', '分类代码不能重复。')
```

`edu.fee.bill.category`（Selection）→ `category_id = Many2one('edu.fee.category', required=True, ondelete='restrict')`。
**ondelete='restrict' 是有意的**：分类被账单引用时删不掉，只能停用（active=False），避免历史账失去分类。

## 3. 初始清单（16 条，种子数据）

| 序 | 名称 | code | 方向倾向 | 来源 |
|---|---|---|---|---|
| 10 | 统筹 | tongchou | 应收 | 校长清单（旧值 tuition「统筹费」改名） |
| 20 | 房租 | fangzu | 应付 | 校长清单 |
| 30 | 交通 | jiaotong | 通用 | 校长清单（旧值 transport） |
| 40 | 活动 | huodong | 通用 | 校长清单（旧值 activity） |
| 50 | 接待 | jiedai | 应付 | 校长清单 |
| 60 | 补助 | buzhu | 应付 | 校长清单 |
| 70 | 补贴 | butie | 应付 | 校长清单 |
| 80 | 课时费 | keshifei | 应付 | 校长清单 |
| 90 | 粮草 | liangcao | 应付 | 校长清单 |
| 100 | 日常物品 | richang | 应付 | 校长清单 |
| 110 | 奉献 | fengxian | 应收 | 校长清单 |
| 120 | 礼物 | liwu | 通用 | 校长清单 |
| 130 | 教材 | jiaocai | 通用 | **保留旧项**（旧值 textbook，生产 B3 无关但历史口径） |
| 140 | 打印 | dayin | 通用 | **保留旧项**（旧值 printing；调研建议并入「日常物品」，保留更稳、且自助可删） |
| 150 | 罚款 | fakuan | 应收 | **保留旧项**（旧值 fine） |
| 999 | 其他 | qita | 通用 | **保留旧项 + default**（旧值 other，兜底） |

⚠️ **方向倾向是我按常识预填的**，校长可在后台一个字改掉（留空 = 两边都能用）。

## 4. 存量迁移（零丢失）

生产 `edu_fee_bill` 仅 2 行、本地 2 行 ⇒ 迁移成本近零，但**流程必须显式**（不能靠"数据少"赌）：

1. `__manifest__.py` 版本 `19.0.1.11.0 → 19.0.2.0.0`；
2. `migrations/19.0.2.0.0/pre-migrate.py`：把旧列快照到临时表
   `CREATE TABLE IF NOT EXISTS edu_fee_bill_cat_backup AS SELECT id, category FROM edu_fee_bill`
   （**必须在字段被 _auto_init 删列之前**取快照）；
3. 分类档案由 `data/fee_categories.xml` 建（固定 xmlid `edu_portal.fee_cat_<code>`）；
4. `migrations/19.0.2.0.0/post-migrate.py`：读快照 → 按映射表写 `category_id` →
   `DROP TABLE edu_fee_bill_cat_backup`；映射：tuition→tongchou, textbook→jiaocai,
   activity→huodong, transport→jiaotong, printing→dayin, fine→fakuan, other→qita；
   遇到映射表外的 code → 归 `qita` 并打印告警（不静默丢）。
5. 迁移后自查：`SELECT count(*) FROM edu_fee_bill WHERE category_id IS NULL` 必须 = 0。

## 5. 影响面（来自调研 §三，实施时逐条打勾）

| # | 位置 | 改法 |
|---|---|---|
| 1 | `models/fees.py` | 新增 EduFeeCategory；`FEE_CATEGORIES` 常量与 `category` 字段退场；`category_label` 相关（:228）改读 m2o |
| 2 | `models/fees.py:221` | 报销状态标签映射不动 |
| 3 | `controllers/ledger.py`（约 15 处） | `_CATEGORY_LABEL` 删除；筛选 `category` 改按 id/code；表单选项、卡片字典、CSV 列、审计文案 |
| 4 | `controllers/fees.py` | 同上（该文件有一份**重复的** `_CATEGORY_LABEL`，一并收敛到一处） |
| 5 | `views/ledger.xml` | 记账表单与筛选下拉改遍历分类记录（`t-foreach="categories" t-as="c"` + `c.name`） |
| 6 | `views/fees.xml` | 报销申请表单的分类下拉同上 |
| 7 | 后台菜单 | 新增「费用分类」菜单（教务/管理员），列表可增删改、可停用 |
| 8 | `security/ir.model.access.csv` | 分类表读写权限（backoffice + system） |
| 9 | `tests/smoke/ledger_select_labels.py` | **必须改**：它逐字断言 7 个 label 与字母序，改后语义变为 sequence 顺序 |
| 10 | `tests/smoke/zero_loss_reachability.py` 等 | 若引用 category 字段则同步 |
| 11 | `scripts/check_qweb_dict_foreach.py` | 门禁自动覆盖新写法（遍历 dict 的反例不再出现） |

## 6. 验收标准

1. 后台「费用分类」菜单能新增一条分类（校长视角，无需开发者），前台记账表单**立刻**出现该选项；
2. 记账选「接待」→ 落库 category_id=接待 → 台账明细与 CSV 导出都显示「接待」；
3. 台账筛选按分类过滤生效（选「接待」只剩该条）；
4. 停用某分类 → 新记账不再出现，但历史账仍显示原名（不丢）；
5. 尝试删除被账单引用的分类 → 被拒绝（restrict），提示改用停用；
6. 迁移后 `category_id IS NULL` 计数 = 0；旧 7 值全部映射到位；
7. 门禁：check_english / check_qweb_dict_foreach / check_view_xpath / check_accessibility 全绿；
   行为级断言 `tests/smoke/ledger_category_admin.py`（新建分类→记账→筛选→停用→删除被拒，逐条真跑）。

## 7. 校长裁定（2026-09-16，已按此实施）

1. 「可以自定义新建和**删除**」→ 删除做成：**未被引用 = 真删除**；**被引用 = 拒绝**并提示改用「停用」（历史账必须保住分类名）；
2. 接受补充项，但**「罚款」不存在** ⇒ 未收录（旧值 `fine` 迁移时归入「其他」）⇒ 初始 **15 条**；
3. 方向倾向按 §3 预填，校方后台可自行改（留空=两边都能用）；
4. 「接待 ¥850」= **需要报销、已有人垫付**（垫付人待补，见 §9）。

## 8. 实测（as-built，2026-09-16 本地）

| 项 | 读数 |
|---|---|
| `-u edu_portal`（19.0.1.11.0 → 19.0.2.0.0） | EXIT=0；pre-migrate 快照 **2 行** → post-migrate `other → qita` **2 行** → 仍无分类 **0 行** → 快照表已删 |
| 分类档案 | **15 条**按 sequence 建好，账单 `category_id` 全部回填 |
| `ledger_select_labels.py` | **12/12**（分类断言由「7 个固定标签 + 字母序」改为「15 条档案 + sequence 顺序 + 数值 id」） |
| `ledger_category_admin.py` | **13/13**（自助新建→立刻出现在表单→记账→筛选→停用→删除被拒→真删除→leftover=0） |
| `ledger_payable_card.py` | **8/8**（新增两条：**待批报销计入**、**已驳回不计**） |
| 门禁 | check_english / check_view_xpath / check_qweb_dict_foreach / check_manifest_tracking 全 **exit 0** |

**遇到并修掉的坑（诚实记录）**：
1. 后台账单列表/表单视图仍写着 `<field name="category">` → 装载期 `ParseError: 字段"category"不存在于模型`，升级**中断**（module 版本未推进、旧列仍在 ⇒ 修好后重跑即续上，没造成半迁移）；
2. `category_id` **有意不加 `required=True`**：给存量表加「必填」列会撞 NOT NULL；改由应用层必填 + 迁移断言 NULL=0；
3. 模板内联 JS 的注释里写了一个**裸 `&`** → lxml `not well-formed`：正是 dev-workflow 里那条老教训的现场重演（这次是注释里）。

## 9. 未做 / 已知边界

- 分类**两级层级**（校管家有大类/小类）未做；要加时照 `edu.download.category` 的 parent_id 写法；
- 「方向倾向」只是**表单层联动**（前端 JS 隐藏 + 后端 selectable 过滤），不是数据约束：历史账即使方向与倾向不符也不会被拦；
- `category_id` 列**允许空**（见 §8 第 2 条）——迁移后实测 0 行 NULL；日后若要收紧为 required，需再发一版并在 pre-migrate 里先确认无 NULL；
- 「接待 ¥850」转报销单 **已于 2026-09-16 生产执行**：方向=应付、分类=接待、reimburse_state=request、reimburse_ref=REB000012（自动取号）、created_by_partner **清空**（避免把记账人「教务二号」误标成垫付人）、备注追加「垫付人待补」。
  ⇒ **垫付人仍未知**：问出来后一条命令补上 SET_PARTNER=<partner_id>（订正脚本已扩为方向/分类/报销状态/垫付人四合一）。
- 取号小坑：即便 FIX_DRY_RUN=1，预演也会**消耗一个报销单号**（_next_reimburse_ref 会推进序号）⇒ 预演与真跑的单号不同（本次 000010 预演、000012 生效），序号有跳号但无重复。
