# 财务总账 + 报销 · 设计文档（ledger-design）
> **状态**：`已上线` ｜ **主题**：`财务总账与报销` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 状态：✅ 已定稿（2026-09-09，grilling 拍板）｜ 工作流 `docs/dev-workflow.md`
> 目标：**不新建模块**，在既有 `edu.fee.bill` 体系上扩展为「应收+应付/报销」双向总账，
> 学生/老师可发起报销申请，教务打勾同意（可改金额）→ 自动生成应付账单 → 付款平账。
> 设计依据：`docs/plans/fees-design.md`（既有单向学费账）；grilling 定稿见本页 §0。

## 0. 用户拍板（grilling 2026-09-09）

| # | 决策 | 结论 |
|---|---|---|
| 1 | 台账方向 | **双向**：应收（学校收：学费/罚款/教材费）+ 应付（学校付/报销：垫付的书费/车费/活动费）+ 杂费 |
| 2 | 账目分类 | 预置分类（学费/教材/活动/交通/打印/罚款/其他），后台可增删，报销必选 |
| 3 | @ 对象粒度 | 可 @ 单个学生 / 单个老师 / 整个班级（拆每人一笔）/ 部门 |
| 4 | 报销打勾 | ✓ = 同意（可改同意金额，如发票只报部分）、✗ = 驳回（必填原因） |
| 5 | 记账权限 | 教务/管理员记总账（应收/应付都从这发）；学生/老师只能发起报销申请 |
| 6 | 审批权限 | 报销审批 = 教务/管理员（聚合进既有后台审批页） |
| 7 | 币种 | 仅人民币（不可空金额，沿用现有 currency 默认公司币种） |
| 8 | 与旧学费账单关系 | **同一模型扩展同一页共存**，不新开模块；旧学费账单原样兼容 |
| 9 | 报销形态 | **两段式**：报销申请单 → 教务打勾同意 → 自动生成应付账单（挂申请人） |
| 10 | @ 班级展开 | @ 班级 = 拆成每人一笔子账单（各自可缴/各自查） |
| 11 | 金额核对 | 审批时可改同意金额（发票部分报销场景），看收据附件 |

## 1. 模型扩展（custom_addons/edu_portal/models/fees.py）

沿用 `edu.fee.bill` 单模型，**新增/改字段**（全部兼容既有数据）：

| 字段 | 类型 | 含义 | 既有兼容 |
|---|---|---|---|
| `direction` | Selection | `receivable`(应收) / `payable`(应付) | 默认 receivable（旧单=应收）|
| `partner_id` | M2o res.partner | 通用受理人（学生/老师的 partner）| 新增；旧单留空（用 student_id）|
| `student_id` | M2o op.student | 保留（应收收学生；应付报销给学生的也记）| 原字段不变 |
| `faculty_id` | M2o op.faculty | 应付给老师时记 | 新增 |
| `category` | Selection | 学费/教材/活动/交通/打印/罚款/其他 | 新增，默认 other |
| `reimburse_state` | Selection | 仅应付·报销单用：`request`(申请中)/`approved`(已同意待付)/`refused`(已驳回)/`paid`(已付) | 应收单留空 |
| `reimburse_ref` | Char | 报销申请单号（REB%06d） | 新增 |
| `receipt_attachment_ids` | M2m ir.attachment | 收据/凭证附件 | 新增 |
| `approved_amount` | Monetary | 教务同意的金额（默认=申请金额，可改） | 新增 |
| `approved_by` / `approved_on` | M2o user / Datetime | 审批人/时间 | 新增 |
| `reject_reason` | Text | 驳回原因 | 新增 |
| `created_by_partner` | M2o res.partner | 发起人（报销申请=垫付人）| 新增 |
| `source_ref` | Char | 应收/应付的原始来源（如 @班级展开的父单号/手工备注）| 新增 |

> 状态机：应收单沿用 `state`（open/partial/paid/void）+ 现有 `payment_ids` 到账流水；
> 应付·报销单用 `reimburse_state`（request→approved→paid 或 request→refused），
> 到账流水 `edu.fee.payment` 复用于**付款**（应付侧 payment=付款、应收侧 payment=收款）。

### 模型方法
- `action_reimburse_approve(amount)`：打勾 ✓。校验存在 → 置 reimburse_state=approved、
  approved_amount=传入金额（不传=申请金额）、approved_by/on；通知申请人。
- `action_reimburse_refuse(reason)`：置 refused + reject_reason；通知申请人。
- `action_pay()`：付款登记（应付侧）→ 建一条 edu.fee.payment + reimburse_state=paid、
  state=paid（复用既有 state 汇总逻辑）。
- `@api.model create`：报销申请（direction=payable, reimburse_state=request）生成
  reimburse_ref 序号（`edu.reimburse.seq`）。

## 2. 门户路由（controllers/fees.py 扩展 + 新 controllers/ledger.py）

| 路由 | 角色 | 动作 |
|---|---|---|
| `/my/fees`（改） | 学生/家长/教师/内部 | 同一页显示：学费应收 + 我的报销申请（含状态/驳回原因/收据）|
| `/my/reimburse/apply`（新） | 学生/教师 | 发起报销：选分类/填金额/收据上传/@ 备注 → POST 生成 request 应付单 |
| `/my/reimburse/apply/save`（新） | 学生/教师 | 写路由（csrf、防重、附件入库 ir.attachment）|
| `/ledger`（新，内部） | 教务/管理员 | **总台账**：全部应收/应付一页（筛选方向/分类/受理人/状态/时间；导出 CSV）|
| `/ledger/new`（新，内部） | 教务/管理员 | 记一笔应收/应付总账：选方向/分类/金额/@ 学生或 @ 老师或 @ 班级(拆每人)→ 批量生成 |
| `/ledger/reimburse`（新，内部） | 教务/管理员 | 报销审批台：待批列表 + 详情（收据预览/改同意金额/打勾✓/✗驳回）|
| `/ledger/reimburse/set`（新，内部） | 教务/管理员 | POST：approve(带金额)/refuse(带原因)/pay(登记付款) |

> 导航：学生/教师门户加「报销」入口卡；教务后台复用既有审批聚合页加「报销审批」tab；
> 总台账可从首页「费用账单」卡或后台财务菜单进入。**不新增顶层大菜单**。

## 3. 核心流程（端到端）

```
【应收 · 教务记总账】
/ledger/new 选 应收 + 分类(学费/教材…) + 金额 + @学生 或 @班级(→拆每人一张)
→ 批量建 edu.fee.bill(direction=receivable, student_id=每人)
→ 学生 /my/fees 看到 → 线下收款 → 后台登记 edu.fee.payment → 平账

【应付 · 报销】
学生在 /my/reimburse/apply 发起（分类/金额/收据/备注）
→ 建 direction=payable, reimburse_state=request, 单号 REB00001
→ 教务 /ledger/reimburse 待批列表（收据预览）
→ 打勾 ✓（可改同意金额）→ 置 approved, approved_amount → 通知学生
→ 教务付款登记 → 建 payment + paid → 平账
→ 或 ✗ 驳回填原因 → 通知学生（列表见原因）

【总台账 · /ledger】
一页查全部：方向/分类/受理人/状态筛选，应收欠款与应付待付一目了然，导出 CSV。
```

## 4. 附件（收据）存储

- 复用 Odoo `ir.attachment`（`/web/image` 公开路由已有）；报销申请上传文件 → 建 attachment
  关联 `receipt_attachment_ids`；审批详情页用既有 `/web/image/<id>` 预览图片/PDF。
- 权限：attachment 记录设为 `public`（或会话可读）以支持门户预览；上传限 10MB、类型白名单
  jpg/png/pdf。

## 5. 权限矩阵

| 动作 | 学生 | 教师 | 教务/管理员 | 家长 |
|---|---|---|---|---|
| 看自己的账单/报销 | ✅ | ✅(自己) | ✅(全部) | ✅(孩子) |
| 发起报销申请 | ✅ | ✅ | ✅ | ❌ |
| 记应收/应付总账 | ❌ | ❌ | ✅ | ❌ |
| 审批报销(打勾/驳回) | ❌ | ❌ | ✅ | ❌ |
| 付款登记 | ❌ | ❌ | ✅ | ❌ |
| 总台账查看/导出 | ❌ | ❌ | ✅ | ❌ |

> 复用既有 deny-by-default + sudo + 身份绑定惯例；内部路由用
> `current_faculty() or privileged_staff()` 门禁（同 enroll 审批）。

## 6. 审计与通知

- 审计：`edu.audit.log._log` 记录 记账/报销申请/审批/付款 四类动作（与 enroll 一致）。
- 通知：`edu.message._notify_event` 新增事件 key `reimburse_result`（申请已提交/已同意/
  已驳回/已付款），登记进 `notify_pref.py` NOTIFY_EVENTS；收件人=申请人门户账号。

## 7. 兼容与回归

- 旧应收学费账单：direction 默认 receivable、student_id 保留，/my/fees 原样显示。
- 新字段均带默认值，`-u edu_portal` 无 Traceback；既有 4 入口（/my/fees 等）回归 200。
- 生产数据：教师仅「待定」占位（partner 65）→ 报销"应付给老师"对象用 partner 落库，
  真实教师建档后即正确显示；占位期间报销测试走学生角色。

## 8. 实施顺序（工程师）

1. models/fees.py：扩展字段 + reimburse 方法 + 序号；`-u edu_portal` 升级
2. controllers/fees.py：/my/fees 兼容扩展 + /my/reimburse/apply(save)
3. controllers/ledger.py 新建：/ledger + /ledger/new + /ledger/reimburse(+set)
4. views/fees.xml 扩展（我的账单+报销区）+ 新建 views/ledger.xml（总台账/报销审批台）
5. 导航接线（学生/教师报销入口卡 + 教务总台账/审批入口）+ notify 事件登记
6. tests/smoke/p3_ledger_smoke.py（幂等：记应收→学生见→发起报销→打勾→付款→驳回→权限）
7. 本地验收 → 用户确认 → 生产部署（rsync + -u edu_portal + 冒烟 + 档案）

## 9. 待确认（非阻断，可先行）

- 应收"@ 部门"展开粒度（默认同 @班级=拆每人，部门=该部门全体学生）。
- 报销金额上限/单笔限额（默认不限，后台可设参数）。
- 学生/教师是否要看到"全部账单"（默认只看与自己相关，避免信息泄露）。