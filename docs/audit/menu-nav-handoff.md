# 菜单/导航收口：接手须知与"两个数"口径台账（menu-eng 交接）

> 面向：t8 复核者、t7 终验者、以及后续碰菜单/导航的人
> 日期：2026-09-17 ｜ 状态：菜单收口已落库并通过队长抽验；导航收口有一条 P1 待处置

## 1. 一分钟速览（当前真值，可逐条复算）

| 指标 | 值 | 复算命令 |
|---|---|---|
| 全库菜单 | **605**（零删除） | `psql -tAc "select count(*) from ir_ui_menu"` |
| 根菜单（parent_id IS NULL） | **40** | 同上加 `where parent_id is null` |
| 其中 active | **14** | 同上加 `and active` |
| 停用菜单 | **200** | `select count(*) from ir_ui_menu where not active` |
| 收口后三个角色的可见根 | **admin 14 / backoffice 12 / faculty 9** | `python3 scripts/menu_baseline.sh snapshot --tag x`（或 `tests/audit/verify_consolidation.py --phase after`） |
| `edu_nav` 声明改写的条数 | **357** | `select value from ir_config_parameter where key='edu_nav.consolidated_count'` |
| 实际受 `noupdate=1` 保护的菜单 xmlid | **419** | `select count(*) from ir_model_data where model='ir.ui.menu' and noupdate=true` |
| 导航条数 / 其中指向空页 `/jobs` | **39 / 2（P1）** | `python3 scripts/check_nav_jobs_entries.py` |
| 「工作机会」(188) 目标 | `/campus/jobs`（200） | — |

## 2. 三次"同一件事两个数"事故（本项目已踩三次，别再踩第四次）

| 事故 | 数 A | 数 B | 各是什么口径 | 定论 |
|---|---|---|---|---|
| 根菜单 | **47** | **40** | 47 = 早期口头流传/旧快照；40 = `parent_id is null` 实测 | 以 **40** 为准（`active 39` → 收口后 `active 14`） |
| 可见叶子 | **391 / 279 / 153** | **294 / 153 / 62** 与 **306 / 153 / 65** | 391/551/164 = **总数（可见节点）**；279/140/53 = 验证方口径（**排除根**）「id != appID 且 children 为空」；294/153/62 = 前端 `actionID/action` 非空；306/153/65 = ORM 快照「有 action 且无子菜单」 | 引用必须带"口径名 + 采集时刻"；**验收只以 B（可见根数）为准**。详见 `diff-report.md` §1.1 |
| 保护数 | **357** | **419** | 357 = `edu_nav` **声明要改写**的条数；419 = **实际受 `noupdate=1` 保护**的菜单 xmlid 总数（差 62 条：子孙节点 / 保护边界外延 / 非 edu_nav 目标） | 报"收口动了多少"用 **357**；报"防重放护住多少"用 **419**。详见 `consolidation-persistence-fix.md` §7 |

## 3. 改菜单的**唯一流程**（`noupdate` 保护已生效，顺序错了会"升级成功但菜单没变"）

```bash
python3 scripts/consolidation_persist.py --unprotect    # 1 解开保护（否则 edu_nav 自己也写不进）
python3 scripts/gen_menu_data.py --state=baseline       # 2 由计划 JSON 生成声明式数据
bash scripts/safe_upgrade.sh edu_nav                    # 3 落库（普通 <record> 每次 -u 重放）
python3 scripts/consolidation_persist.py --protect      # 4 重新上保护（幂等，带备份）
```
- 想彻底交还模块 XML 控制权：`--unprotect`。
- 菜单整表还原到收口前：`python3 scripts/rollback_menus.py --apply`（以 `menu-tree-before.json` 为权威 + 回读断言）。
- 声明源：`docs/audit/menu-consolidation/menu-consolidation-plan.json`；对账器：`scripts/check_menu_data_sync.py`（XML ↔ dry-run 逐条，0 漂移才算好）。

## 4. 已知 P1：`/jobs` 空页入口会被**原生模块重建**

- 现象：t10 收口后，指向 `/jobs` 的入口被重建过两轮（203/204 → 205/206）；当前 2 条仍在。
- 根因：`/jobs` 的入口是**原生 `website_hr_recruitment`** 的 `<menuitem>`，该模块（或其依赖）被 `-u` 时按原定义重建；
  名字是多维翻译值（`en_US "Jobs" / zh_CN "工作" / zh_TW "職位空缺"`）——可据此识别"原生重建"。
- 判定：`/jobs` 实测 **HTTP 200 但内容空壳**（`hr.job = 0`）——**可达 ≠ 有内容**。
- 根治（与 c 同套机制）：给该菜单 xmlid 置 `noupdate=1`；若无 xmlid 归属，则由 `edu_nav` 按 url 覆盖/停用。
- 哨兵：`python3 scripts/check_nav_jobs_entries.py`（只读，FAIL 即代表又被重建；已修掉自身第一版的假绿）。

## 5. 复查者常用命令（都只读）

```bash
python3 tests/audit/verify_consolidation.py --phase after      # 三数 + 验收线
python3 tests/audit/verify_upgrade_persistence.py --modules edu_portal --restore   # 重放驻留
python3 scripts/menu_baseline.sh snapshot --tag check          # 口径 A/B/C 快照
python3 scripts/menu_baseline_diff.py <前> <后> --out /tmp/d.md # 前后对照表（含 §1.1 口径注记）
python3 scripts/check_menu_data_sync.py                        # XML ↔ dry-run 目标态对账
python3 scripts/consolidation_persist.py --status              # 保护覆盖率（应 357/357 覆盖、未保护 0）
python3 scripts/check_nav_reachable.py                         # 导航 24 条逐条可达
python3 scripts/check_nav_jobs_entries.py                      # /jobs 空页入口哨兵
```

## 6. 本轮我交付的文件（按用途）

| 文件 | 用途 |
|---|---|
| `docs/audit/menu-consolidation/menu-consolidation-plan.json` | 菜单收口的**唯一声明源**（12 容器 / 15 合并 / 档1 六棵 / 档2 混档 / 容器例外 300+=87） |
| `custom_addons/edu_nav/` | 声明式落地（数据文件 + 装载期守卫 + 漂移反查） |
| `scripts/gen_menu_data.py` | 由计划生成数据（`--state=baseline` 重建、`--emit=live\|inert`、禁空组守卫） |
| `scripts/check_menu_data_sync.py` | 落库前最后一道：XML ↔ dry-run 逐条对账 |
| `scripts/consolidation_persist.py` | `noupdate` 保护/撤销/状态（重放问题的根治工具） |
| `scripts/rollback_menus.py` | 以收口前基线整表还原（带回读断言） |
| `scripts/fix_nav_duplicates.py` | 导航 `/jobs` 入口收口（按 url 全量识别，带备份/回滚） |
| `scripts/check_nav_reachable.py` / `check_nav_jobs_entries.py` | 导航可达性核查 / `/jobs` 哨兵 |
| `docs/audit/menu-consolidation/diff-report.md` | 前后对照表（含 §1.1 C 口径注记） |
| `docs/audit/consolidation-persistence-fix.md` | 重放缺陷的复现/根因/修法/副作用/**§7 口径对照** |
| `docs/audit/t11-persistence-evidence.md` | 重放修复的验收证据 |
| `docs/audit/nav-consolidation-t10.md` | 导航收口的对照表/可达性/中文化/回滚/待办 |

## 7. 终验前必读：两条**判据稳定性**问题（本轮实测）

### 7.1 `check_english.py` 的退出码会在 0/2 之间抖动（不是回归）

- 实测 3 连跑：`rc=0, 0, 2`。**must-fix 恒为 0、brand 恒为 0、路由违规恒为 0**；
  抖动只来自 `夹具残留 = 6` 这类 **smoke-leftover**。
- 原因：**他人在并行跑 `tests/smoke/run_smoke.sh`** 时，冒烟夹具（如 `【冒烟】t43 越权夹具考试`、
  `【冒烟】t75 课程`、`【冒烟】预览文件夹`）会**在运行期驻留在库里**，门禁就会报 leftover 并 `exit 2`；
  冒烟结束后自动回落 0。
- **判据口径**：看 `TOTAL must-fix = 0 且 brand = 0`（这是验收面）；
  **`rc=0` 只有在"无人跑冒烟"的窗口才成立** —— 不要用 rc 当唯一证据，否则会得到"时红时绿"的假信号。
- 取证建议：跑门禁前先确认没有 `run_smoke.sh`/`smoke_*.py` 进程（`ps aux | grep smoke`）。

### 7.2 `load_menus` 结果按**会话**缓存

- 同一次登录会话里反复读会拿到旧值；**回滚/升级后必须用新登录会话测量**，
  否则会误判"回滚没生效"（本轮踩过：回滚后仍读到收口态，实际库里已是原态）。
- 取证建议：每次对比前后都用 `A.login()` 新开会话（`scripts/check_nav_reachable.py`、`menu_baseline.sh` 已如此）。
