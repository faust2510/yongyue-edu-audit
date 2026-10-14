# 财务缴费 · 设计摘要与实施方案
> **状态**：`已上线` ｜ **主题**：`财务缴费` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 状态：✅ 已交付（2026-08-23）｜ 工作流 `docs/dev-workflow.md`

## 决策

- **不纠缠 openeducat_fees** 的学期收费结构（op_fees_terms/element 对学坊过重），
  自建轻量两层：`edu.fee.bill` 应收账单 + `edu.fee.payment` 到账流水。
- 账单状态自动汇总（compute store）：无到账=open，不足额=partial，足额=paid，void 手工。
- **deny-by-default**：portal 无 ACL 行，门户 `/my/fees` 只读走 sudo + 身份绑定；
  收款登记由内部员工在后台完成（学坊线下收款线上记账场景）。
- 首页「费用账单」卡片从 Odoo 标准英文发票页(/my/invoices) 改指 `/my/fees`（5 处锚点）。

## 文件

models/fees.py｜controllers/fees.py｜views/fees.xml（含家长按孩子分组模板）｜
ACL 追加2行｜manifest 19.0.1.4.0｜scripts/seed_fees_demo.py

## 验收（真机 ✅）

升级 ERROR=0；种子幂等(2→0)；状态自动汇总核对
（12000/open、300 已缴100/partial）；四角色截图+页面内容断言全过
（账单在/部分缴纳徽标/待缴合计提示/无报错）。
