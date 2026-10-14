# 招聘后台 · 设计摘要与实施方案
> **状态**：`已上线` ｜ **主题**：`招聘后台与岗位发布` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 状态：✅ 已交付（2026-08-23）｜ 工作流 `docs/dev-workflow.md`

## 决策

- `edu.job.posting` 岗位（发布状态机 draft→published→closed，职责要求 Html，
  申请计数 compute）+ `edu.job.application` 申请（公开可投，honeypot 反机器人）。
- **替换数据源**：`/campus/jobs` 与 `/alumni/job/card` 从 hr.job（此前假数据来源）
  切换到本研模型；新增详情页 + 公开投递表单（csrf + honeypot + 必填校验 + 字段截长）。
- ACL deny-by-default：posting/application 对 public 无行；申请创建仅经控制器 sudo；
  application 对 group_user 不可删除（1/1/1/0）。
- 后台「招聘管理」根菜单 seq70：岗位管理（内嵌申请记录页签）/ 申请处理。
- 踩坑记录：Odoo19 list 视图 field 不允许 `string=` 覆盖、`decoration-secondary`
  不在合法清单；路径字面量 /sent 不映射为路由参数（按 request.path 判断）。

## 文件

edu_portal: models/jobs.py｜views/jobs.xml｜ACL 2行｜manifest 19.0.1.6.0｜
scripts/seed_jobs_demo.py　·　edu_public: controllers/main.py 三路由｜
views/edu_public_views.xml 列表卡片改写+详情/投递模板

## 验收（真机 ✅）

升级 ERROR=0；种子幂等(2→0)；匿名全流程：列表两岗位卡 → 详情表单 →
投递落库（姓名/电话/学历/state=new 全对）→ 成功提示；
后台「岗位管理」截图含申请数列。
