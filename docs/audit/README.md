# 审计档案（docs/audit/）

**本页是本目录的索引 —— 找审计结论先看这里，不要翻目录。**

> **最后核对**：`2026-10-06` ｜ **份数**：`65`（`docs/audit/**/*.md`，不含本页）
> 复核命令（原样可跑）：`find docs/audit -name '*.md' -not -name README.md | wc -l`

> ⚠ **读之前先看这条**：本目录里有若干**结论已被现实验证推翻**的文档，下表已逐个标出。
> 最典型的是「187 数据全丢且不可恢复」——**该结论已于 2026-10-04 证伪**（数据完好，并已切回该机作正式站）。
> 记录这次更正的两份（`old-server-187-recovery-2026-10-04.md`、`cutover-back-to-187-2026-10-04.md`）**不是**过期文档，它们是**更正本身**。

## 迁移与换机（5 份）

- [`cutover-back-to-187-2026-10-04.md`](cutover-back-to-187-2026-10-04.md) — 正式站切回 187（2026-10-04）（2026-10-04）
- [`old-server-187-recovery-2026-10-04.md`](old-server-187-recovery-2026-10-04.md) — 187 旧机找回记（2026-10-04）—— 数据**没有**丢（2026-10-04）
- [`migration/data-loss-ledger.md`](migration/data-loss-ledger.md) — 8/30 之后生产数据损失台账（仓库侧考古）（2026-10-01） ⚠ **重建计划不再需要执行（187 数据完好）**
- [`migration/duplicate-subject-review.md`](migration/duplicate-subject-review.md) — 「基础信仰」重名科目 —— 教务确认清单（**只出清单，不动数据**）（2026-10-01）
- [`migration/rebuild-plan.md`](migration/rebuild-plan.md) — 重建清单：B 类 19 条 → 可执行步骤（新服务器实测版）（2026-10-01） ⚠ **重建计划不再需要执行（187 数据完好）**

## 菜单与导航（10 份）

- [`menu-consolidation/deploy-shipping-gap.md`](menu-consolidation/deploy-shipping-gap.md) — edu_nav 上不了生产：取证、判断与前置条件（2026-09-29）（2026-10-02）
- [`menu-nav-handoff.md`](menu-nav-handoff.md) — 菜单/导航收口：接手须知与"两个数"口径台账（menu-eng 交接）（2026-09-28）
- [`finding-F1-menu-replay-on-upgrade.md`](finding-F1-menu-replay-on-upgrade.md) — 发现 F1：菜单收口值在「升级其它模块」后被重放（t2 残留风险，实测成立）（2026-09-17）
- [`nav-consolidation-t10.md`](nav-consolidation-t10.md) — t10：导航重复入口收口 + 校友岗位页中文化（2026-09-17）
- [`menu-consolidation/baseline-report.md`](menu-consolidation/baseline-report.md) — 菜单收口基线报告（t2 只读准备）（2026-09-17）
- [`menu-consolidation/diff-report.md`](menu-consolidation/diff-report.md) — 菜单收口前后对照表（2026-09-17）
- [`menu-consolidation/nav-probe-diff-report.md`](menu-consolidation/nav-probe-diff-report.md) — 菜单收口前后对照表（2026-09-17）
- [`menu-consolidation/plan-table-before-apply.md`](menu-consolidation/plan-table-before-apply.md) — 菜单收口施工图（40 根：现态 → 目标态）（2026-09-17）
- [`menu-consolidation/root-menu-plan-before.md`](menu-consolidation/root-menu-plan-before.md) — 根菜单施工图数据源（口径 A 全部 40 行，含 inactive 1）（2026-09-17）
- [`menu-consolidation/selfcheck-diff-report.md`](menu-consolidation/selfcheck-diff-report.md) — 菜单收口前后对照表（2026-09-17）

## UI 与无障碍（17 份）

- [`ui-promises-verification.md`](ui-promises-verification.md) — UI 承诺验收台账（2026-10-04 第 79–91 轮）（2026-10-03）
- [`ui-visual-review/report.md`](ui-visual-review/report.md) — 门户 UI 视觉复核（人眼判断型轴 —— 机械门禁不覆盖）（2026-10-03）
- [`backend-ux/t18-independent-verification.md`](backend-ux/t18-independent-verification.md) — task-18 独立验证清单（backend-ux 出具，全部只读）（2026-10-03）
- [`backend-ux/t18b-teacher-direct-verification.md`](backend-ux/t18b-teacher-direct-verification.md) — task-18 第三轮：教师**直连**成绩簿 —— 独立验证（backend-ux 出具）（2026-10-03）
- [`backend-ux/t18c-column-scope-and-feedback.md`](backend-ux/t18c-column-scope-and-feedback.md) — 修复：教师「看得见、存不了、还被说成没改」——列按任教收敛 + 保存反馈（2026-10-03）
- [`narrow-tables-c/report.md`](narrow-tables-c/report.md) — task-12：窄屏卡片化 C（门户台账 / 课程编排 / 家长账单 + 批量排课）（2026-10-02）
- [`narrow-tables-c/task15/report.md`](narrow-tables-c/task15/report.md) — task-15：判据 C（表头折行）修复 —— /my/checkin/board 与 /my/points/me（2026-10-02）
- [`empty-states/before-after-4roles.md`](empty-states/before-after-4roles.md) — 逐页 before/after 证据（每条都是本机栈实测 DOM）（2026-10-02）
- [`empty-states/before-after.md`](empty-states/before-after.md) — 逐页 before/after 证据（每条都是本机栈实测 DOM）（2026-10-02）
- [`empty-states/page-matrix.md`](empty-states/page-matrix.md) — 逐角色逐页空态矩阵（读数：sweep-v2first-20261002-1849.json，sweep-v2-20261（2026-10-02）
- [`empty-states/report.md`](empty-states/report.md) — 空状态与首次使用体验审计（task-7）（2026-10-02）
- [`ui-visual-review/task9-report.md`](ui-visual-review/task9-report.md) — task-9：门户肉眼可视缺陷修复（V1/V2/V3/V5/V6/V8）（2026-10-02）
- [`backend-ux/report.md`](backend-ux/report.md) — 后台（Odoo 管理界面）UI/UE 审计报告 —— T3 死角（2026-10-02）
- [`a11y-coverage-curriculum-assess-20260929.md`](a11y-coverage-curriculum-assess-20260929.md) — 无障碍门禁：补两处覆盖 + 「还能红」演练（2026-09-29）（2026-09-29）
- [`ui-gap-ledger.md`](ui-gap-ledger.md) — 零覆盖门户页 · 七轴体检问题账（C 组）（2026-09-28）
- [`ui-surface-inventory.md`](ui-surface-inventory.md) — 门户 UI 表面清单与覆盖率（A 组 · 2026-09-26）（2026-09-26）
- [`ui-color-audit-2026-09-15.md`](ui-color-audit-2026-09-15.md) — 全站配色实测审计（2026-09-15）（2026-09-17）

## 安全与权限（3 份）

- [`portal-color-token-map-t4.md`](portal-color-token-map-t4.md) — t4 台账：门户颜色字面值 → 令牌 对照表（2026-09-28）
- [`security-audit-app.md`](security-audit-app.md) — （2026-09-18）
- [`security-audit-infra.md`](security-audit-infra.md) — 基础设施与部署层安全审计（2026-09-18）

## 成绩与录入（1 份）

- [`edu-eval-removal.md`](edu-eval-removal.md) — 行政评估（`edu_eval`）删除 —— 证据与回滚（2026-10-01）

## 其他（29 份）

- [`user-accounts-audit-2026-10-06.md`](user-accounts-audit-2026-10-06.md) — 用户账户数据审计（2026-10-06）（2026-10-06）
- [`deploy-2026-10-03.md`](deploy-2026-10-03.md) — 部署记录：2026-10-03（本会话第一次上生产）（2026-10-04）
- [`core-loops-verification.md`](core-loops-verification.md) — 核心闭环验证台账（2026-10-04 第 69–76 轮）（2026-10-03）
- [`deprecated-inventory.md`](deprecated-inventory.md) — 弃用台账（Deprecated Inventory）（2026-10-03）
- [`fresh-install-broken.md`](fresh-install-broken.md) — ✅ **全新库装不上 → 已修好**（2026-10-04 第 65 轮发现，第 66 轮修复并复验）（2026-10-03）
- [`fresh-install-rehearsal.md`](fresh-install-rehearsal.md) — 全新库「整装演练」——按 `deploy_myedu.sh` 的真实清单（2026-10-04 第 67 轮）（2026-10-03）
- [`open-questions-2026-10.md`](open-questions-2026-10.md) — 悬而未决的疑问（2026-10 第 82 轮起登记）（2026-10-03）
- [`principal-rulings-2026-10-03.md`](principal-rulings-2026-10-03.md) — 校长裁定（2026-10-03）—— 成绩簿直连 + 教师门户合并（2026-10-03）
- [`public-surface-review.md`](public-surface-review.md) — 公开面（未登录可访问）复核 —— 2026-10-03 第 53 轮（2026-10-03）
- [`telegram-retired-but-live.md`](telegram-retired-but-live.md) — 退役中的 edu_telegram 仍在**实际运行**（含一条可猜的管理码）（2026-10-03）
- [`faculty-home-merge/report.md`](faculty-home-merge/report.md) — task-19：老师的「我的主页」与「应用面板」合并（2026-10-03）
- [`deadcode-scan.md`](deadcode-scan.md) — 符号级死代码扫描（2026-10-02 立）（2026-10-02）
- [`redundancy/inventory.md`](redundancy/inventory.md) — 去冗余审计与处置清单（T1 · 2026-10-02）（2026-10-02）
- [`identity-lookup-unification.md`](identity-lookup-unification.md) — 由 user 反查身份档案：口径统一（审计 + 施工 + 待办）（2026-09-28）
- [`task-H-parent-fuzzy-claim.md`](task-H-parent-fuzzy-claim.md) — 任务 H 报告：基座「模糊搜索把无关联系人认领成家长」的数据污染缺陷（含同段相邻两处）（2026-09-28）
- [`task-B1-enroll-timetable-gap.md`](task-B1-enroll-timetable-gap.md) — 任务 B1 诊断：报课后 `/student/timetable` 仍只显示「神论」（王佐 · 生产）（2026-09-18）
- [`checkin-merge-report.md`](checkin-merge-report.md) — t5 打卡两套合一：迁移台账与验收报告（2026-09-17）
- [`consolidation-handoff.md`](consolidation-handoff.md) — 交接：功能重叠收口（edu-consolidation）—— 已完成什么、停在第几格、怎么接着做（2026-09-17）
- [`consolidation-persistence-fix.md`](consolidation-persistence-fix.md) — t11：菜单收口的"重放"缺陷（F1）——复现、根因、修法与证据（2026-09-17）
- [`consolidation-verification.md`](consolidation-verification.md) — 功能重叠收口 · 独立验证报告（T7）（2026-09-17）
- [`feature-overlap-audit.md`](feature-overlap-audit.md) — 功能重叠审计与收口方案（2026-09-17）
- [`finding-F2-checkin-board-500.md`](finding-F2-checkin-board-500.md) — 发现 F2：`/my/checkin/board` 500（t5 落库后引入的 NameError）（2026-09-17）
- [`finding-F3-unattributed-checkin-rows.md`](finding-F3-unattributed-checkin-rows.md) — 发现 F3（已更正归因）：9 条 `edu_checkin_record` 来自 edu_life 升级期 `<func（2026-09-17）
- [`finding-F5-edulife-demo-injection.md`](finding-F5-edulife-demo-injection.md) — 发现 F5：edu_life 在 `-u` 时向业务表注入「无标记演示数据」（滚动窗写法）（2026-09-17）
- [`finding-F6-ledger-inplace-overwrite.md`](finding-F6-ledger-inplace-overwrite.md) — 发现 F6（工具隐患）：合并台账「就地覆写」导致同文件名的破坏性随时间漂移（2026-09-17）
- [`peer-research.md`](peer-research.md) — 同类系统辅助功能调研（供 aux-features 路线图参考）（2026-09-17）
- [`t11-persistence-evidence.md`](t11-persistence-evidence.md) — t11 证据：菜单收口的「重放」修复与持久性实测（2026-09-17）
- [`t15-jobs-entry-design.md`](t15-jobs-entry-design.md) — t15 设计稿（只读准备）：让 `/jobs` 空页入口不再出现，且**再升一次仍为 0**（2026-09-17）
- [`task-G-parent-student-basefix.md`](task-G-parent-student-basefix.md) — 任务 G 报告：两个「管理员也炸」的基座 bug（op.parent.create / op.student.unlin（2026-09-17）

