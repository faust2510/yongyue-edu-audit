# v3 交付前全量门禁复跑留档（t14）

> 执行：verifier（独立执行）｜时间：**2026-09-12 14:32–14:35**｜环境：本地 edu19（`db_name = edu19` + `list_db = False`）
> 取样有效性：**SAMPLE_VALID** —— 取样前通过三步探活（无锁 / 容器 Up 406s / 带 cookie 探活通过），
> 取样后比对 `docker inspect -f '{{.State.StartedAt}}'` 前后一致（Up 406s → 578s，期间无重启）。
> 原始日志：`/tmp/eduprobe/final/*.log`（本文件为结构化留档；命令可逐条复跑）

## 0. 离线自证族（不连站点，专抓"工具本身被改坏"）

| 命令 | 退出码 | 关键输出 |
|---|---|---|
| `python3 scripts/check_english.py --selftest` | **0** | 23 条断言全 PASS（含 `转到您的Odoo应用程序 → brand`、`纯中文文案不该命中`、`txt/md → data`） |
| `python3 scripts/check_odoo_trace.py --selftest` | **0** | 13 个扫描样本 + 7 个数据不变量样本（含正反断言）全符合预期；动态发现 4/4 + t8 2/2 |
| `python3 scripts/check_view_xpath.py --selftest` | **0** | 继承视图/多根/裸 < / t-elif 相邻性/导入顺序/循环继承/锁语义 全部通过 |
| `python3 tests/smoke/gate_seam_check.py` | **0** | 6 样本：4 组"至少一方报" + 纯中文对照 + 未登记属性 known-gap，全部符合预期 |

## 1. 门禁（真跑）

| 命令 | 退出码 | 关键输出 |
|---|---|---|
| `python3 scripts/check_english.py` | **0** | `TOTAL must-fix = 0 条 / brand = 0 条`；五组角色 must-fix 0 且 brand 0；登记项 1547（白名单/数据/主题，不计失败） |
| `python3 scripts/check_odoo_trace.py` | **0** | `PASS：Odoo / 基座品牌痕迹 0 命中（公开站 24 + 4 角色 27 + 后台 1 = 52 条静态路由）`；另含动态发现 13 条、邮件面、数据不变量 0 违规 |
| `python3 tests/smoke/ux_v3_route_matrix.py` | **0** | 检查点 500：`PASS 497 / WARN 3 / PENDING 0 / FAIL(真红) 0 / ENV(环境) 0`（WARN=/my/checkin/board 对 fac/bo/admin 404，v2-B6 既有缺陷） |
| `python3 tests/smoke/zero_loss_reachability.py` | **0** | `L1：PASS 43 / FAIL 0 / BASELINE-404 1（共 44 条）；L2 缺失 0；L0 类契约失败 0；结论：全绿` |
| `python3 tests/smoke/audit_completeness_smoke.py` | **0** | `断言 24 条：PASS 24 / FAIL 0；连跑 2 遍结果一致：是；结论：全绿`；四路径留痕字段正确、leftover=0 |
| `python3 tests/smoke/data_driven_brand_leak.py` | **0** | 5 页品牌字样 0 处；「系统」正向断言成立；`leftover=0` |
| `python3 scripts/shoot_ux_v3.py` | **0** | 69 张截图；M3 首页高度见下表 |

## 2. 既有冒烟（回归）

| 命令 | 退出码 | 关键输出 |
|---|---|---|
| `python3 tests/smoke/downloads_v2_smoke.py` | **0** | `冒烟结果: 32 PASS / 0 FAIL`；含"清理【冒烟】数据归零 / 页面无冒烟残留" |
| `python3 tests/smoke/notice_privilege_smoke.py` | **0** | 特权冒烟全 PASS |

## 3. M3 首页高度（DOM scrollHeight，本次复跑）

| 角色/页 | 1280 | 768 | 375 | 目标 |
|---|---|---|---|---|
| guest /（官网首页） | 3666 | 3929 | 5594 | — |
| student /my/home | **1436** | 1504 | 1519 | 桌面 ≤1800 ✅ / 375 ≤2600 ✅ |
| faculty /my/home | 1412 | 1470 | 2038 | — |
| parent /my/home | 1082 | 1198 | 1013 | — |
| backoffice /my/home | 1505 | 1563 | 2187 | — |

> 改前同口径 student/home = **3744**（1280）/ 5889（375）；本次 1436 / 1519（较 13:23 的 1366 略增，属 v3 后续内容增量，
> 仍在目标内）。**错误页高度（900/1024/812）已作废，禁止引用。**

## 4. 一句话结论

**13 条命令全部 exit 0，取样 SAMPLE_VALID** —— 可观测面（路由/英文/品牌/零丢失/审计/泄漏/截图）与既有回归冒烟均绿。
分层口径见 `docs/plans/ux-v3-delivery.md` §3.4：**门禁全绿只覆盖可观测面**，授权边界与业务规则一致性由交叉评审 + 行为级验证负责（t34/t35、t39）。
