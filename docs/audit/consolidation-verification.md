# 功能重叠收口 · 独立验证报告（T7）

- 验证人：verifier（独立验证，只信实测）
- 日期：2026-09-17 ｜ 环境：docker compose `edu19-clone` / 库 `edu19` / http://127.0.0.1:8069
- 被测状态：t2 菜单收口 + t5 打卡合一已落库；t11（F1 修复）**尚未落库**
- 结论摘要：**菜单与打卡两块的核心验收线全部达标**；但 **F1（升级重放）仍未修**，
  它是「改动在升级后仍生效」这一条的唯一失败项 ⇒ 本报告按实测判 **FAIL（待 t11）**。

---

## 0. 我怎么验的（可复跑）

| 脚本 | 作用 | 命令 |
|---|---|---|
| `tests/audit/verify_consolidation.py` | 双口径菜单/39 条路由/重复组/数据/裁定判定 | `python3 tests/audit/verify_consolidation.py --phase after` |
| `tests/audit/verify_upgrade_persistence.py` | 升级重放驻留测试 | `python3 tests/audit/verify_upgrade_persistence.py --modules edu_life,edu_portal --restore` |
| `tests/audit/audit_lib.py` | 只读库（trust_env=False 绕代理；仅 GET + 读方法 + psql SELECT） | 被上面两个脚本 import |

原始读数：`tests/audit/out/after_result.json`、`after_report.md`、`upgrade_persistence_result.json`、
`persistence_*.json`；收口前基线：`tests/audit/out/before_*`（commit 068d79b 冻结）。

---

## 1. ① 保留功能可达性（39 条，逐条实测 HTTP）

**结果：39/39 全部为 200 / 303 / 302，无 4xx、无 5xx。**

| 状态 | 条数 | 含义 |
|---|---|---|
| 200 | 33 | 正常渲染 |
| 302 | 1 | 登录页跳 /login |
| 303 | 5 | 受保护或已收口重定向 |

303 明细（每条都归位）：

| 角色 | 路径 | Location | 判定 |
|---|---|---|---|
| anon | /my/home | /web/login?redirect=%2Fmy%2Fhome%3F | 预期（队长裁定） |
| anon | /downloads/manage | /web/login?redirect=%2Fdownloads%2Fmanage%3F | 预期（队长裁定） |
| student | /my/checkin | /my/checkins | 预期（队长裁定） |
| student | /my/checkin/export | /my/checkins/export | 预期（队长裁定） |
| student | /my/points | /my/home | 既有行为 |

关键页面元素（≥30 条覆盖了学生端门户/教师教务后台/审批/打卡/周记/排课/成绩/缴费/下载/测验/帮助中心）：

| 路径 | 状态 | 关键元素证据 |
|---|---|---|
| `/` | 200 | 含品牌「永约学坊」（冒烟 #1 PASS） |
| `/campus/jobs`、`/campus/jobs/1` | 200 | ≥2 张岗位卡 + 投递表单（冒烟 #2/#3 PASS） |
| `/my/home` | 200 | 登录落点正确，功能卡 45 张（冒烟 #8 PASS） |
| `/my/apps` | 200 | 卡片网格 ≥10（冒烟 #8 PASS） |
| `/my/checkins` | 200 | 含「到堂」；表单 action=`/my/checkins/check` |
| `/my/checkin/board` | 200（faculty） | 到堂看板保留（裁定②） |
| `/checkins/stats` | 200 | 含 到堂/读经/灵修/周记 四列，无 Traceback |
| `/student/timetable` | 200 | 标题「我的课表」+ 周导航（冒烟 #9 PASS） |
| `/my/fees` | 200 | 「2026 春季统筹费」「部分缴纳」「待缴合计」（冒烟 #11 PASS） |
| `/my/assets` | 200 | 重复申请 `error=dup`（冒烟 #12 PASS） |
| `/web/login` | 302→`/login` | 登录页（冒烟 #7 未登录跳转 PASS） |
| `/my/home`（未登录） | 303 | → `/web/login?redirect=...`（受保护正确） |

> 说明：本清单用 HTTP 码 + 关键字符串判「可达」，不是仅看码。完整 39 条逐条码见 `out/after_report.md`。

---

## 2. ② 重复入口确实消失（前后对照）

### 2.1 菜单规模（口径 A / B）

| 口径 | 收口前 | 收口后 | 判定 |
|---|---|---|---|
| A：DB `parent_id IS NULL` | 40 | **40** | 记录零删除 ✓ |
| A：其中 active | 39 | **14** | 隐藏而非删除 ✓ |
| 全库菜单数（含 inactive） | 605 | **605** | 零删除 ✓ |
| 全库 active | 601 | **405** | — |
| B：admin 可见根 | 38 | **14** | ≤20 ✓ |
| B：backoffice 可见根 | 31 | **12** | ≤12 ✓ |
| B：faculty 可见根 | 19 | **9** | — |
| B：student / parent | 0 / 0 | **0 / 0** | 门户可见性未变 ✓ |

### 2.2 重复组逐条复核（对 backoffice@local，>1 即仍重复）

| 重复组 | 收口前可见 | 收口后可见 | 判定 |
|---|---|---|---|
| op.student 双根 | ≥2（收口前基线 31 根） | 1 | ok |
| 打卡双入口(根) | ≥2（收口前基线 31 根） | 1 | ok |
| 评估双根 | ≥2（收口前基线 31 根） | 1 | ok |
| 考勤多根 | ≥2（收口前基线 31 根） | 0 | ok |
| 招生双根 | ≥2（收口前基线 31 根） | 1 | ok |
| 原生噪音组(档2对超管=预期) | ≥2（收口前基线 31 根） | 0 | ok |
| 合并候选组 | ≥2（收口前基线 31 根） | 0 | ok |

要点：`op.student` 双根（学生信息 257 / 学生 278）≡ 1；打卡双入口（日常管理 543 / 灵命生活 593）≡ 1；
评估双根（综合评估 588 / 行政评估 597）≡ 1；考勤多根（课堂考勤 349 / 出勤 529）≡ 0（原生噪音对非超管全隐）。

### 2.3 「消失」是隐藏还是删除？

- **不是删除**：全库 `ir_ui_menu` 记录 605→605（零增减），根菜单 40→40。
- 手段为 `active=False` + `group_ids` 收窄 + `parent_id` 归并（t2 计划只允许改这 4 个字段）。
- **档 2 最终实现为「混档」**（2026-09-17 14:5x 复核，commit 682d3a1）：
  `121 联系人 / 142 发票 / 196 员工 / 566 数据清除` **整棵 `active=False`**；
  `1 设置 / 15 应用` 为 `active=True` + 单组 `[base.group_system]`（根 + 全部子树 restrict_tree）。
  实测：`id IN (121,142,196,566)` 中 active = **0/4**；`id IN (1,15)` 中 active = **2/2**。
  ⇒ 后人不要用旧口径「六棵全活跃」来质疑本报告。
- 档 2 六棵（1/15/121/142/196/566）的判定仍成立（`tier2_superadmin_visible`）：实测
  非超管四角色对它们 **0 可见**，admin 可见集恰为这 6 个 ⇒ 符合队长裁定。
- t2 的 dry-run 可独立复算：`bash scripts/consolidate_menus.sh dry-run`（EXIT=0，预测 admin 14/backoffice 12/faculty 9，
  与库内实测一致，且自证「未落库、无 unlink」）。

---

## 3. ③ 数据一致性（打卡 7 条逐条对账）

### 3.1 源表原样保留（零删除）

| 表 | 收口前 | 现在 | 判定 |
|---|---|---|---|
| `edu_daily_checkin` | 7 | **7** | 原样保留 ✓ |
| `edu_checkin_record` | 36 | **53** | 增量见下 |
| `edu_checkin_type` | 3 | **4** | 新增「到堂打卡」✓ |

### 3.2 7 条源记录逐条对照（迁移口径）

| 源 id | 日期 | 到堂目标 | 读经/灵修目标（note 回填） | 台账 action |
|---|---|---|---|---|
| 1 | 2026-08-23 | → 到堂（62） | 读经 2「【读经范围】约1章」/ 灵修 8「【灵修笔记】晨更祷告」 | created + updated×2 |
| 2 | 2026-08-24 | → 到堂（63） | 读经 1「【读经范围】创1-3章」 | created + updated |
| 4 | 2026-08-29 | → 到堂（64） | —（无信号） | created |
| 5 | 2026-09-12 | → 到堂（65） | 读经 24「【读经范围】创1-3章」 | created + updated |
| 6 | 2026-09-13 | → 到堂（66） | — | created |
| 7 | 2026-09-14 | → 到堂（67） | — | created |
| 8 | 2026-09-17 | → 到堂（68） | 读经 69「【读经范围】创1-3章」（**基线缺此条**，故实际新建 8 而非 7） | created + created |

**日期集合逐条核对结果：源 7 条日期 == 到堂 7 条日期，完全一致 ✓**

```
源 7 条日期  : 2026-08-23, 08-24, 08-29, 09-12, 09-13, 09-14, 09-17
到堂 7 条日期: 2026-08-23, 08-24, 08-29, 09-12, 09-13, 09-14, 09-17
日期集合一致: True    源仍未删: True    type=5 计数: 7
```

### 3.3 增量与台账吻合（两条台账闭合）

| 台账 | 时间 | created | updated | skipped_duplicate |
|---|---|---|---|---|
| `checkin-merge-applied-ledger.jsonl` | 05:35:36 | 8 | 4 | 0 |
| `checkin-merge-latest.jsonl`（幂等复跑） | 06:16:14 | **0** | **0** | 12 |

**算式闭合**：36（基线）+ 8（首跑新建）+ 9（id 53–61，t5 已认领为同窗口 `-u edu_life`
触发 `_load_demo_records` 所写、非 t5 产物、未删）= **53** ✓

幂等性：复跑 created=0 / skipped_duplicate=12 ⇒ **重复执行不产生重复数据** ✓

### 3.4 完整性/唯一性

- `(student_id, type_id, checkin_date)` 重复组 = **0** ✓
- 旧表旧记录未删：id 45–61 中 9 条仍在，跨类型计数 24/22/7 合计 53 ✓
- 教师端 `/checkins/stats` = 200，四列（到堂/读经/灵修/周记）齐全，无 Traceback ✓
  新增「到堂」列与 `avg_rate` 口径变化属**队长已声明的副作用**，不计缺陷。

---

## 4. ④ 回归：`bash tests/smoke/run_smoke.sh`

**结果：12/15 PASS（EXIT=0）。anon 段 7/7 PASS；student 段 5/6 后脚本 FATAL 中断。**

| 段 | 结果 |
|---|---|
| 匿名公开面（#1–7） | **7/7 PASS** |
| 学生面（#8–12） | 5/5 PASS |
| 学生面 #13 | **FATAL**（见下） |
| #14、#15 | SKIP（因 FATAL 中断） |
| 总览 | 12/15 PASS |

### 差异单列（每条都有解释，非功能缺陷）

| 用例 | 现象 | 解释 | 归属 |
|---|---|---|---|
| #13 `/my/checkin` 打卡一次 | `TimeoutError: waiting for locator("form[action='/my/checkin/save'] button")` | 旧表单**已按收口设计消失**：`/my/checkin/save` 现为 303→`/my/checkins`，新表单 action=`/my/checkins/check` | **等待 t9 对齐**（队长已单列） |
| #14 `/my/points/me` | SKIP | 被 #13 FATAL 中断，非自身失败 | 同上 |
| #15 9 页渲染巡检 | SKIP | 被 #13 FATAL 中断 | 同上 |

功能等价性已单独验证（不因冒烟红而误判）：`/my/checkins` 返回 **200**、表单指向 **`/my/checkins/check`**、
页面含「到堂」；`/my/checkin/save`(GET) 返回 **303 → `/my/checkins`**。⇒ 打卡功能在，仅旧断言过期。

> 按队长指示：t9（回归脚本对齐）**未完成**（当前 pending），故 #13 的红标注为「等待 t9 对齐」，
> **不记为 blocker**；待 t9 落库后需重跑本项。

---

## 5. ⑤ 四角色视角（导出清单为证）

| 角色 | 可见根菜单数 | 导出清单 |
|---|---|---|
| admin | 14 | 设置、应用、网站、学生信息、招生、图书馆、时间表、教务审批、财务管理、资产管理、招聘管理、综合评估、灵命生活、资料下载 |
| backoffice | 12 | 网站、学生信息、招生、图书馆、时间表、教务审批、财务管理、资产管理、招聘管理、综合评估、灵命生活、资料下载 |
| faculty | 9 | 学生信息、招生、图书馆、时间表、教务审批、资产管理、招聘管理、综合评估、灵命生活 |
| student | 0 | （无后台菜单） |
| parent | 0 | （无后台菜单） |

- 学生/家长：后台根菜单 **0**（与收口前一致）⇒ **门户可见性未变** ✓
  （学生/家长对 `ir.ui.menu` 无 ORM ACL，故用前端 `load_menus` 口径；两种口径均已记录在 JSON。）
- 教务 12 根与 t1 施工图「教务视角 12 根」**逐名一致**：学生信息/招生/图书馆/时间表/教务审批/
  财务管理/资产管理/招聘管理/综合评估/灵命生活/资料下载/网站。
- 每条菜单的叶子数与 C 口径见 `out/after_result.json` 与 t2 的 `diff-report.md`。

### 5.1 C 口径（可见叶子）：规范定义 + 三处「未证差异」

> **口径裁定（队长，2026-09-17）**：**B 口径是唯一验收线**（教务 ≤12、admin ≤20）；
> **C 口径只作参考**，任何引用**必须带「定义 + 采集时刻 + 来源方」**。
> 下述三方差异标注为 **「未证差异」**，**不作为缺陷**（已由 menu-eng 在 t11 给 diff-report §1 加注，双份文档各自标明来源）。

**C 的规范定义（以本报告为准）**：
在同一份 `load_menus` 原始数据里，**节点 `id == appID` ⇒ 根**；**非根且 `children` 为空 ⇒ 叶子**；其余为容器。

- 采集时刻：**2026-09-17 14:5x**（本报告本次快照）
- 来源方：本报告（verifier，`tests/audit/verify_consolidation.py`）
- 下列 diff-report / 队长消息两列为**异源对照**，仅示意差异，不作为验收依据：

| 角色 | 我实测 B 根 | 我实测 C 叶子 | 我实测容器 | 我实测可见总数 | diff-report §1 C / 总数 | 队长消息 C |
|---|---|---|---|---|---|---|
| admin | 14 | 279 | 65 | 358 | 306 / 395 | 294 |
| backoffice | 12 | 140 | 32 | 184 | 153 / 199 | 153 |
| faculty | 9 | 53 | 13 | 75 | 65 / 89 | 62 |

**B 口径（可见根）三方完全一致：14 / 12 / 9** —— 这是两条验收线真正依赖的口径，已 PASS。
**C 口径三方不一致，记为「未证差异」**（我 279/140/53；diff-report 306/153/65；队长消息 294/153/62），
差 14–37 条，**原因未证**（候选：`_visible_menu_ids()` 与 `load_menus` 对「action 不存在」「父链补齐」
的处理不同，或采样时刻不同）。按裁定：**不作缺陷、不据此改判**。

另：队长消息中引用的 admin **294** 系转述 menu-eng 某版 §11，**已作废**；
今后引用 C 一律带「定义 + 时刻 + 来源方」。B 口径三方完全一致（14/12/9），验收不受影响。

---

## 6. ⑥ 升级复现（`-u` 之后是否仍生效）—— **FAIL（唯一失败项）**

命令：`python3 tests/audit/verify_upgrade_persistence.py --modules edu_life,edu_portal --restore`

| 升级 | EXIT | Traceback | admin | backoffice | faculty | 判定 |
|---|---|---|---|---|---|---|
| 起始 | — | — | 14 | 12 | 9 | — |
| `-u edu_life` | 0 | 无 | 14 | 12 | 9 | **PASS**（未重放） |
| `-u edu_portal` | 0 | 无 | 19 | **17（超线 12）** | 12 | **REPLAY** |
| `-u edu_nav`（复原） | 0 | 无 | 14 | 12 | 9 | 可复原 |

复活的具体 5 棵：**542 邀请码 / 543 日常管理 / 576 在线课程 / 597 行政评估 / 606 老账号补挂身份**
（xmlid 属 edu_portal，597 属 edu_eval；其 `ir_model_data.noupdate` 全为 0）。
机制：edu_nav 用 `<record id="<他模块>.<xmlid>">` 覆盖，但被引用模块自己的 `<menuitem>`
每次 `-u` 把 `active/groups` 写回声明值 ⇒ **谁最后跑谁赢**。

⇒ **「改动在升级后仍生效」未完全成立**。已开 t11 修复；本项判 **FAIL**，
修复后须重跑本命令 + `--phase after`（详情与修复建议见 `docs/audit/finding-F1-menu-replay-on-upgrade.md`）。

---

## 6.1 F1 修复实况预检（只读，2026-09-17 终版前）

t11 以「受影响菜单 xmlid 置 `noupdate=1`」治本。verifier 只读预检确认**保护已在库内生效**：

| 检查 | 命令 | 实测 |
|---|---|---|
| 保护覆盖率 | `python3 scripts/consolidation_persist.py --status` | 覆盖菜单 **357 条**；**未受保护 = 0 条** |
| 是否还需保护 | `python3 scripts/consolidation_persist.py --dry-run` | 同样 **0 条** ⇒ `--protect` 已是 no-op |
| 关键 5 棵 | 只读 psql | 542/543/576/597/606 全部 `noupdate=true` |
| 全库菜单 xmlid | 只读 psql | `noupdate=true` **419** / `false` **186** |
| 当前口径 B | `tests/audit/verify_consolidation.py` | admin **14** / backoffice **12** / faculty **9** |

**覆盖范围（实测口径）**：edu_nav 数据文件覆盖 **357 条菜单 / 46 个模块**
（`scripts/consolidation_persist.py` 注释写 47，属文档小误差，以实测 46 为准）。
**模块占比前三：`base` 65 条、`account` 53 条、`mail` 33 条** ——
这三个数就是「**为什么必须用 `noupdate` 保护、而不能改各家 XML**」的直接论据：
受影响菜单散布在数十个模块（含 Odoo/OpenEduCat 基座模块），改源码既不可行（会动
`openeducat_erp/` 基座与 Odoo 核心）也不可维护；按菜单记录置 `noupdate` 才是可行解。

**机制可信性**（读源码注释核实）：`odoo/orm/models.py::_load_records` 为
`if not (update and d_noupdate)`；且 `ir_model.py::_build_update_xmlids_query` 的
`ON CONFLICT ... DO UPDATE` **不含 `noupdate`** ⇒ 保护既拦重放、自身也不会被后续升级重置。

### 6.1.1 终版 ⑥ 判据（已获队长批准，待 t9/t12/t13 完成后执行）

1. **前置闸门**：`consolidation_persist.py --status` ⇒ `未受保护 = 0`（防止"保护失效被静默跳过"）
2. 快照 pre（角色 B + 节点数 + active 根）
3. `-u` 抽样：`edu_life`、`edu_eval`（597 归属）、`edu_portal` + 代表模块
4. 快照 post 对拍 ⇒ 期望**全 PASS**（修复前 `edu_portal` 必 REPLAY）
5. **幂等加测**：同一模块连跑两次，第二次仍不变
6. **反向验证**：按队长指示**不复现原始缺陷**，不跑 `--unprotect`；
   注明「反向由 menu-eng 实测（`--unprotect` 后 `-u edu_portal` 确认 5 棵复活），verifier 未重复」

### 6.1.3 ⚠ 执行方式事故：串行升级扫描把 web 容器反复重启（已停手、已加护栏）

- **事实**：`safe_upgrade.sh -u` 每次都会"升级 + 重启 web 容器"。2026-09-17 15:10–15:13
  窗口内实测 `/tmp/edu19_upgrade.20260917-15*.log` 连续生成 6 份、末模块均为 `edu_eval`，
  间隔 15–30 秒 ⇒ 容器被反复重启，同期 t9 全量冒烟跑不出有效样本
  （同一份代码出现 0/15、1/2、8/15 三种形态）。
- **归属（已核实，队长 2026-09-17 复核进程参数后确认）**：造成此次 churn 的是
  **menu-eng 执行 t11 的逐模块验证**（`verify_upgrade_persistence.py --modules hr,openeducat_core,…`），
  **不是 verifier**。verifier 名下当时**无任何升级进程**（`ps` 实测为空），本轮
  **未重启过容器**（`docker inspect` `RestartCount=0`）；其此前 `-u` 仅两次单跑
  （05:41 `edu_life`、05:45 `edu_portal`），均有明确目的与记录。
  （队长已就更正前的错误归因向 verifier 致歉。）
- **教训与通用要求（对所有人有效，非针对个人）**：⑥ 这类会写环境的验证（跑 `-u`、重启容器）
  一律 ① 用**批量 `-u`**（多模块一批，容器只重启一次），禁止逐模块串行；
  ② **由队长协调窗口**后再跑（跑前确认无人在跑冒烟/迁移，跑后把窗口时间写进报告）。
  理由：逐模块重启会把别人的验证一起打红——data-eng 的 t9 全量冒烟即因此被卡住。
- **纠正措施（已落进工具，队长批准）**：`tests/audit/verify_upgrade_persistence.py`
  1. **默认即 `--batch`**（一次性 `-u a,b,c`，容器只重启一次）；`--no-batch` 与之互斥；
  2. **`--serial` 默认拒绝**（需 `--i-know`）；**`--no-batch` 同样必须 `--i-know`**——
     否则可静默绕过串行守卫（这条是补上的漏洞，已实测拒绝输出）；
  3. **`--restore` 改为"仅当快照比对发现 REPLAY 时才复原"**（对 mail/account/contacts
     这类不涉 edu_nav 覆盖项的模块，连"复原"那一次重启也省掉）；
  4. 文件头写明：只在队长指定空闲窗口跑、跑完把窗口时间写进报告。
- **终版执行方式（改后）**：默认 batch 一次性升级 + 前后快照对拍 + 幂等加测（同批再跑一次）。
- **事故机制留档（关键解释）**：15:22 起的模块序列实测为
  `edu_portal → account → mail → edu_nav → hr_recruitment → edu_nav → website_slides →
  edu_nav → contacts → edu_nav …`；因带 `--restore`，**每个模块都会额外再升一次 `edu_nav`**
  ⇒ **每模块 = 2 次容器重启**，这才是容器被打得最狠的直接原因。

### 6.1.2 新库可复现性验证（队长授权方案 ②，三条护栏）

目的：证「全新安装是否自带『到堂打卡』类型」（t13 要防的"换库/重装后功能静默消失"）。
护栏：① **库名隔离** `edu19_verify_t13_<时间戳>`，**绝不碰 `edu19`**；② 跑完 **DROP** 自清，
并在本报告写明「建库 → 装模块 → 断言 → 删库」完整命令；③ **时间盒**——安装慢或失败即退回
方案 ①（只验现库 + 检查 `edu_life/data` 声明与函数实现），并如实标注"新库验证未完成（原因）"，
**不为跑通而放宽判据**。

**两个必须知道的环境前提（实测探明，是本方案能安全做的前提）**：
1. `/etc/odoo/odoo.conf` 内已有 **`db_name = edu19`** 且 `list_db = False`
   ⇒ 新库命令**必须显式 `-d <新库>` 覆盖 conf**；只依赖 conf 会让请求落到 `edu19`
   ——**那正是"绝不碰 edu19"的红线**，故执行前先打印目标库名确认。
2. **容器内没有 `docker` 命令**（§10 之外的另一处证据：`verify_checkin_board.py` 在容器内调
   `docker exec psql` 直接 `FileNotFoundError`）⇒ 新库断言**必须走 ORM/`env` 查询**，
   不能在容器内调 `docker exec`。

## 7. 契约 verify 命令执行情况（诚实记录）

| 契约命令 | 结果 | 说明 |
|---|---|---|
| `bash tests/smoke/run_smoke.sh` | 已执行，EXIT=0 | 12/15 PASS，差异见 §4 |
| `python3 scripts/consolidate_menus.py --dry-run` | **未按字面执行** | 该脚本**不是独立 CLI**，需 odoo shell + 计划文件；已按其官方包装 `bash scripts/consolidate_menus.sh dry-run` 执行，**EXIT=0**，见 §2.3 |
| `python3 scripts/merge_checkins.py --dry-run` | **已跑通（2026-09-17 复核）** | 脚本已按契约改名到位。两种跑法均已实测：①**宿主裸跑** `python3 scripts/merge_checkins.py` → EXIT=0，纯函数自测（打印 `merge_note` / `plan_rows`），**不是**落库判据；②**契约语义跑法**（容器内 odoo shell）→ `{"mode": "dry-run", "created": 0, "updated": 0, "skipped_duplicate": 12, "target_total_after": null}` + **`rc=0`**，**未写库**。⚠ 早期版本曾记「未执行（缺工件）」，**该行已失效** |
| `python3 tests/audit/verify_consolidation.py` | 已执行，EXIT=0 | 本报告主证据 |

---

## 8. 残留风险 / 未核项（不含未实测结论）

**残留风险（已实测确认存在）**

1. **F1 升级重放未修**（high）：`-u edu_portal` 后教务 12→17 超线，需要每次升级补跑 `-u edu_nav` 才恢复。
   edu_nav 数据引用 **27 个模块**的 xmlid，其余模块是否也重放 **未逐个实测**。
2. **#13 冒烟仍红**（已解释）：旧断言指向已收口的 `/my/checkin/save` 表单，待 t9 对齐。
   ⇒ 在 t9 完成前，「冒烟全绿」这一条**不成立**。
3. **F3 归因已更正**：9 条 id 53–61 的写入方已查明为 edu_life 的 `<function>` 回调
   （不是"来源不明"），见 `finding-F3-unattributed-checkin-rows.md` 的更正说明；
   由此衍生的防复发问题另立 F5。
4. **到堂打卡类型的持久性**：t5 明确遗留「重跑脚本才能在新库/重装后存在」。
   即 `edu.checkin.type` 的「到堂」**不是**由模块 data 声明，全新环境不会自带。
5. **edu_life 在 `-u` 时向业务表注入无标记演示数据**（F5，medium）：
   `data/demo_life.xml` 末尾的 `<function>` 回调 `_load_demo_records`，按"今天"取滚动 7 天补写 `edu.checkin.record`（同日幂等、跨日会新增），写入行**无【演示】标记**、与真实打卡混同表；详见 `finding-F5-edulife-demo-injection.md`。
   这也是 t9「旧表零增长」断言不成立的根因之一。
6. **`.migration-ledger` 产物**：`scripts/migrations/ledger/` 与容器侧 `custom_addons/.migration-ledger/`
   谁 gitignore / 谁保留，尚未裁定。

**「未做 / 遗留」清单（本轮明确不处理）**

1. **`edu19_relay_probe` 遗留库 —— 不动**（队长裁定 2026-09-17）。
   verifier 只读核实：该库**仅 1 张表 `edu_telegram_outbox`**、**无 `ir_module_module`**
   ⇒ 非完整实例、无业务数据。全仓引用**仅文档与配置**、无任何代码引用：
   `config/odoo.conf:6`、`docs/code-map.md:25`、`tests/smoke/UX_V3_GATE.md:301/318/319/321/446`。
   它在 `docs/code-map.md:25` 被记为 2026-09-12「本地多库 ⇒ 全站 404」事故的根因之一，
   当时的修复是 `config/odoo.conf` 写 `db_name = edu19`，并**刻意保留 `list_db = False`** 与生产一致。
   ⇒ **影响已被 `db_name=edu19` 中和**；本轮**不清理**（删库是单向操作，且不属收口范围）。
   如需清理，**应单列一步**：先确认无引用（再 grep 一次代码/脚本），再 drop，并连带评估
   `odoo.conf` 与生产对照。**不要为了"界面干净"顺手 drop。**
2. **菜单侧 `scripts/consolidate_menus.sh rollback`** 未实际执行（见上文未核项 4）。

**未核项（我没有实测，故不作为结论）**

1. **C 口径三方「未证差异」**（我 279/140/53 vs diff-report 306/153/65 vs 队长转述 294/153/62）：
   按队长裁定不作缺陷、不改判，但**原因未证**；C 只作参考，引用须带定义+时刻+来源。
2. `docs/audit/menu-consolidation/diff-report.md` 中 **C 口径（可见叶子）** 的逐格数字我只核了
   `bash scripts/consolidate_menus.sh dry-run` 的预测值（admin 400→306、backoffice 279→153、faculty 115→65），
   **未**逐条核对 diff-report 表内每一行。
2. **权限边界细粒度**：我只验「角色可见根菜单」与少量页面 HTTP 码，**未**做「同一 URL 越权访问」矩阵
   （例如教务可否打开超管专属页）。
3. **评估 / 岗位两套**（t4 仅设计、本轮不动数据）：未验。
4. **回滚可执行性**：t5 的 `merge_checkins.py --rollback` **已独立实测**（见 §10）；
   `scripts/consolidate_menus.sh rollback`（菜单侧）仍**未实际执行**，只有脚本存在性与 dry-run 自证。
5. **生产环境未核**：本轮全部为本地 edu19，生产（edu.example.org）未比对。
6. **并发写入**：本轮验证期间 t10/t11 在改同一仓（我实测到 admin 14↔30 的瞬时漂移），
   上表数字为某一时刻的快照；最终复核应在 t10/t11 落库后重跑。

---

## 9. 逐条验收判定

| 验收条 | 判定 | 依据 |
|---|---|---|
| ① ≥30 条路由逐条 HTTP 码 | **PASS** | 39 条全 200/303/302，§1 |
| ② 重复入口消失 + 隐藏非删除 | **PASS** | §2，605→605、40→40、7 组全 ≤1 |
| ③ 打卡 7 条逐条对账 + 增量吻合 | **PASS** | §3，日期集合一致、0 重复、算式闭合 |
| ④ 冒烟全绿 | **FAIL（待 t9）** | 12/15，3 项差异已解释并单列，§4 |
| ⑤ 四角色菜单与预期一致 | **PASS** | §5，教务 12 根逐名一致，学生/家长 0 未变 |
| ⑥ 升级后仍生效 | **FAIL（待 t11）** | §6，`-u edu_portal` 重放 12→17 |

> 综合：**菜单与数据两条主线均已达标且零删除**；④⑥ 各有一项未闭合，
> 分别归属 t9（回归断言对齐）与 t11（F1 升级重放修复）。

---

## 10. 追加实测：t5 回滚安全闸（把「未核」升级为「已独立实测」）

背景：t5 自述「`--rollback` 只删台账内 action=created 且内容与台账一致的 id；内容被改过则进
conflicts 且不删，退出码 2」。**自述不算证据**，故由 verifier 独立设计并执行以下测试。

### 10.1 安全闸测试（构造冲突台账，目标是不删/不改任何东西）

测试台账：`/tmp/t7-recon/ledger_safetygate.jsonl`（3 个冲突场景 + 1 个类型事件），
放入容器 `/mnt/custom-addons/.migration-ledger/` 后用
`CHECKIN_MERGE_ARGS=--rollback CHECKIN_MERGE_LEDGER=<该文件>` 执行。

| 场景 | 构造 | 期望 | 实测 |
|---|---|---|---|
| A 内容不符 | `created` 行 target_id=68，`note_after` 与库内不符 | 进 conflicts，**不删** | ✓ `内容与台账不一致（迁移后被改动），拒绝删除` |
| B 记录不存在 | `created` 行 target_id=99999 | 进 conflicts（幂等跳过），不报错 | ✓ `记录已不存在（幂等跳过）` |
| C note 不符 | `updated` 行 target_id=2，`note_after` 与库内不符 | 进 conflicts，**不还原** | ✓ `note 与台账不一致，拒绝还原` |
| D 类型 | `created=False, deactivate_on_rollback=False` | 保持原样、不置 inactive | ✓ `保持原样，不置 inactive` |

输出：`[回滚] 删除 0 条、还原 note 0 条、冲突 3 条`、**`[exit] rc=2`**。
跑前 / 跑后库内状态**完全一致**：`count=53`、`type5=7`、`type5_active=true`、`id2` 的 note 未被改动。

⇒ **结论：安全闸成立** —— 被改动过的记录绝不会被静默删除或还原，冲突时以 rc=2 退出。

### 10.2 诚实记录：我第一次跑错了台账（已恢复）

- 我先用 **`checkin-merge-applied-ledger.jsonl`**（该文件记录了那 8 条 created）跑 `--rollback`，
  本意是"不删任何东西的冲突测试"，实际执行了**回滚语义**：输出 `删除 0 条、还原 note 4 条、冲突 8 条`。
- **事实更正（2026-09-17，与 data-eng 对账后）**：该次运行**删除数就是 0 条**，那 8 条 created
  在我运行**之前**就已不存在（此前已被他人回滚演练移除，故全部落入 `conflicts` 的"记录已不存在"分支）。
  我此前写成"走了真删路径"**不准确**，特此更正。
- 实际后果：仅把 4 条 note 回填还原成空（id 1/2/8/24），即迁移状态被部分回退；**未删除任何记录**。
- 恢复：执行 `--apply`（`CHECKIN_MERGE_LEDGER=...checkin-merge-latest.jsonl`）⇒
  `created=0 / updated=4 / skipped_duplicate=8 / total=53`，
  id 1「【读经范围】创1-3章」、id 2「【读经范围】约1章」、id 8「【灵修笔记】晨更祷告」、
  id 24「【读经范围】创1-3章」**全部回填到位**，`count=53`、到堂 7 条日期集合不变。
- **顺带获得两条额外证据**：
  (a) 幂等成立——`--apply` 复跑 `created=0 / skipped_duplicate=8`，无重复写入；
  (b) `--rollback` 的 note 还原以**单条记录为单位**精确（只在库内值与台账 `note_after` 全等时才还原）。
- **对账确认（data-eng 独立只读复核，与我一致）**：`edu_checkin_record=53`、`edu_daily_checkin=7`、
  `edu_journal_entry=4`、到堂 7 条日期集合不变、重复键组 0、id 1/2/8/24 的 note 全部到位
  ⇒ **账目闭合，误触已完全恢复**。
- **两点补充**：`skipped_duplicate=8` 与 `=12` 两个数字**都对**——只是输入台账版本不同
  （applied 版 8 created 已消失 ⇒ skip 8；latest 版 12 条候选全 skip）。
- 教训：**回滚类脚本"测安全闸"必须用构造台账，不能拿真实 applied 台账当测试输入**；
  本次未造成记录删除或口径破坏，但过程应记录在案。

---

## 11. 报告修订记录（保持「文档与实况一致」）

| 项 | 旧表述 | 现状 | 依据 |
|---|---|---|---|
| `scripts/merge_checkins.py` | 「未执行（缺工件）」 | **已跑通**：宿主裸跑 EXIT=0（纯函数自测）；容器内 odoo shell `rc=0`、`created=0/skipped_duplicate=12`、未写库 | 脚本已按契约改名到位（旧 `scripts/migrations/checkin_merge.py` 已不存在），verifier 2026-09-17 复核 |
| F3 那 9 条演示记录 | 「不删，可选一键清理」 | **队长裁定保留**，本轮不跑清理器；t12 治本后再议 | 队长 2026-09-17 裁定（四条理由见 F3 §2.3） |
| F3 归因 | 「来源不明（未归因）」 | **已归因**：edu_life `demo_life.xml` 的 `<function>` 回调 | 三重证据，见 F3 §1.0/§1.1/§2.1 |
| C 口径 | 「可能原因」 | **「未证差异」**，不作缺陷；引用须带定义+时刻+来源方 | 队长 2026-09-17 口径裁定，见 §5.1 |
| 档 2 实现 | 「restrict_tree（六棵）」 | **「混档」**：121/142/196/566 整棵停用；1/15 = active + 单组 | 实测 `active` 0/4 与 2/2，见 §2.3 |
| t5 回滚安全闸 | 「未核（非实证）」 | **已独立实测**：冲突态 `rc=2`、零删除零改动 | §10.1 |
| 回滚误跑 | — | 误用 applied 台账致 4 条 note 回填被还原，**已 `--apply` 完整恢复** | §10.2（含教训） |

---

## 12. 留给自己的两条教训（与 F3 留痕同源）

1. **报告里"我做了什么"必须以下令/输出行为准，不能靠事后推断。**
   那次误触我写成"走了真删路径"，而输出行明明写着 `删除 0 条`；
   自己的记录也不能凭印象，须复核原始输出。
2. **把纪律做成机制，而不是口头约定。**
   `--serial` 默认拒绝 + 默认 `--batch` + `--restore` 按需，三者把"会写环境的验证"
   从"靠人记得"变成"机制上跑不出风暴"；`--no-batch` 那个绕过口子也必须一并堵上。
   （与 F3 的"阴性证据不能用于排除"一样，这类结构性教训比单次结论更值得留。）
