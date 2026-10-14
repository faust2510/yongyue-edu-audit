# 资产借还 · 设计摘要与实施方案
> **状态**：`已上线` ｜ **主题**：`资产借还` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「🚧 实施中」，实际已于 `9ac86b9` 交付（2026-09-26 核对发现）。正文未改动。

> 状态：🚧 实施中 ｜ 工作流 `docs/dev-workflow.md`

## 决策

- `edu.asset` 台账：name/code/category(设备|书籍|其他)/state(available|loaned|maintenance|retired)/note
- `edu.asset.loan` 借还单：asset_id/student_id/requested_note/
  state(requested→borrowed→returned，旁路 cancelled|rejected)/三日期
- 流转：学生门户申请(requested) → 员工后台「批准发放」(borrowed+资产loaned)
  → 员工「登记归还」(returned+资产available)。学生端只读自己单据；
  审批动作仅后台按钮（服务端方法，非路由参数）。
- deny-by-default ACL：portal 无行；控制器 sudo 绑定 current_student。

## 文件

models/assets.py｜controllers/assets.py｜views/assets.xml｜ACL 2行｜
manifest 19.0.1.5.0｜scripts/seed_assets_demo.py

## 验收标准

- [ ] 学生：资产目录可见可用项 → 申请借用 → 我的借还单出现 requested
- [ ] 后台批准后单据 borrowed、资产 loaned；登记归还后 returned、资产 available
- [ ] 家长视角可见孩子借还单
- [ ] 种子幂等；四角色截图断言通过
