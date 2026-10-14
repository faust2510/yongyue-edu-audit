# 菜单收口基线报告（t2 只读准备）

> 产出人：menu-eng（菜单收口工程师）｜产出时间：2026-09-17（本地时区）
> 依据：队长裁定 t2 开工前"只做只读准备：导出当前菜单树 + 三个角色的可见菜单快照，另存为收口前基线"
> 性质：**只读**。本报告与其配套产物**没有改过任何一条记录**（见 §6 自证）。

## 1. 一句话结论

基线已固化：**口径 A（parent_id IS NULL，含 inactive）= 40 行（active 39 / inactive 1）**；
**口径 B（按角色 ORM 读到的可见根菜单数）= admin 38 ／ backoffice@local 31 ／ faculty@local 19**。
按队长裁定的验收口径（B(教务) ≤ 12、B(管理员) ≤ 20），**三个角色目前都不达标**，其中 faculty 19 与 backoffice 31 是收口的主战场。

## 2. 口径定义（写死，防止读的人猜）

| 口径 | 定义 | 为什么单列 |
|---|---|---|
| A | `ir.ui.menu` 中 `parent_id IS NULL` 的行数（含 inactive；active/inactive 分列） | 这是"数据库里到底有多少个根"，与"谁能看见"无关 |
| B | 以该角色用户身份调 `ir.ui.menu._visible_menu_ids()`（Odoo 官方可见性算法：组过滤 → action 存在性 → 模型 read 权限 → 父链补齐）后落在根层级的菜单数 | 这是验收用的口径 |
| C | B 的集合中"有 `action` 且无子菜单"的项数 | 真正能点开干活的口径；B 变小而 C 不变 = 只藏了容器，业务入口没少 |

三者都写进了基线 JSON 的 `definitions` 字段，**同一份产物里不给"根菜单总数"这类无口径数字**。

## 3. 基线数字

### 3.1 口径 A

- 全库菜单 **605** 条（active 601 / inactive 4）
- 根菜单（`parent_id IS NULL`）**40** 条 —— active 39，inactive 1（`sale.sale_menu_root` 销售 id=434）
- 队长此前口述的"47"作废，与实测一致按 40 记

### 3.2 口径 B / C（三锚点）

| 角色 | 登录名 | B 可见根 | C 可见叶子 | 可见菜单总数 |
|---|---|---|---|---|
| 管理员 | `admin` | 38 | 400 | 551 |
| 教务/后台 | `backoffice@local` | 31 | 279 | 391 |
| 教师 | `faculty@local` | 19 | 115 | 164 |

### 3.3 分角色可见根清单（收口前的"入口全景"）

- **faculty 可见 19 个**：作业、员工、图书馆、在线课程、学生、学生信息、招生、招生报名、招聘管理、教务审批、日常管理、时间表、测验、灵命生活、综合评估、考试、行政评估、课堂考勤、资产管理
- **backoffice 可见 31 个**：在 faculty 的 19 个之外，另有 仪表板、发票、在线聊天、招聘、日历、活动、网站、老账号补挂身份、联系人、讨论、财务管理、资料下载、邀请码、链接追踪器
- **admin 可见 38 个**：在 backoffice 的 31 个之外，另有 在线学习、出勤、数据清除、应用、设置
- **三锚点皆不可见 2 个**：销售（id=434，inactive）、测试（id=16，active 但无人可见）

## 4. 施工图数据源的实测事实（供 t1 决策，不代替决策）

以下是**实测观察**，不是收口结论；每一条都能用 §5 的命令复算。

### 4.1 当前"只有超管可见"的根菜单只有 1 个：应用（id=15）

也就是说：**队长裁定②的"原生噪音只对 base.group_system 可见"这件事，目前基本还没做**。
现状与裁定的差距，逐条对应如下：

| 根菜单 | id | 当前可见范围（实测） | 与裁定②的差距 |
|---|---|---|---|
| 测试 | 16 | **无 group 限制 = 所有内部用户可见**（含教师） | 需收成仅超管 |
| 数据清除 | 566 | **无 group 限制**；实测仅 admin 可见是因为 `data_recycle` 的 action 权限挡住了 backoffice/faculty | 需显式收成仅超管（当前可见性靠权限偶然成立，不稳） |
| 出勤 | 529 | `hr_attendance.group_hr_attendance_manager`（id=83，成员 1 人 = admin） | 非超管已不可见，但**锚点不是 group_system**；按裁定②应改锚 |
| 在线学习 | 547 | `website_slides.group_website_slides_manager`（id=88，成员 1 人 = admin） | 同上 |
| 链接追踪器 | 75 | 组 87「后台·完整视图」（成员：admin、backoffice） | backoffice 仍可见 → 需收成仅超管 |
| 销售 | 434 | inactive（无人可见） | 已下线，无需再动 |

### 4.2 关于组 87「后台·完整视图」的两个实测事实（与裁定③相关）

1. **组 87 当前被 251 条 active 菜单引用**（远多于根菜单数量）——原因是 2026-09-12 的 `scripts/seed_teacher_menus.py` 把整棵子树（根 + 全部后代）的组都替换成了 [87]。
2. **当前没有任何组隐含 87**（实测：`隐含 87 的组 = []`），组成员只有 admin(id=2) 与 backoffice(id=12)。
   该脚本文件里写的"`base.group_system` 隐含该组"**在当前库里并不成立**（脚本里有 GUARD 段会摘除非法隐含，且组继承关系后来被重排过）。

**推论（重要）**：87 现在是一个"只对这两个账号生效"的限制标记，**它不是"仅超管"**——backoffice 也满足它。
所以裁定②要求的"只对 `base.group_system` 可见"，**用 87 实现是不等价的**，必须真的写入 `base.group_system`(id=4)。

### 4.3 重复入口候选（实测的可见性差别，供收口决策）

| 重复对 | 各自 id | 实测差异 |
|---|---|---|
| 学生信息 257 / 学生 278 | 257（6 个子菜单，28 个 active 后代）、278（3 个子菜单，8 个 active 后代） | 两者都对 faculty/backoffice 可见 → **教师侧同时看到两个"学生"入口** |
| 综合评估 588 / 行政评估 597 | 588 属 edu_portal、597 属 edu_eval | 两者都对 faculty 可见 |
| 在线学习 547 / 在线课程 576 | 547 是原生 website_slides（仅 admin）、576 是自研 edu_lesson（全员） | 547 在教师/教务侧本就不可见，收口只需决定它是否对超管也下线 |
| 出勤 529 / 课堂考勤 349 | 529 hr.attendance、349 openeducat_attendance | 529 仅 admin、349 对 faculty 可见；两者语义不同（员工出勤 vs 课堂考勤），**合并决策需要 t1 的业务判断** |

### 4.4 口径 A 的 40 行里有 1 条 inactive（销售 id=434）

销售是 `sale.sale_menu_root`，**已 inactive 但记录仍在**（红线：不删记录）。它计入 A(40) 不计入 active(39)，也不会被任何角色看到。

## 5. 怎么复算（每条命令都实跑过；涉及容器的命令请在仓库根目录跑）

```bash
# ① 收口前基线（JSON：口径 A/B/C + 逐条菜单 + 文本树）
bash scripts/menu_baseline.sh snapshot --tag before

# ② 施工图数据源（Markdown：40 个根菜单一行一条，带三锚点可见性 / 组 / 子树规模 / 自研-原生）
bash scripts/menu_baseline.sh plan --tag before

# ③ 基线自检（JSON 可解析 + 口径自洽 + 父子链无悬空）
python3 scripts/menu_baseline_check.py docs/audit/menu-consolidation/menu-tree-before.json

# ④ 收口后快照 + 前后对照表（对照表不连库，验证方可独立复算）
bash scripts/menu_baseline.sh snapshot --tag after
python3 scripts/menu_baseline_diff.py docs/audit/menu-consolidation/menu-tree-before.json docs/audit/menu-consolidation/menu-tree-after.json --out docs/audit/menu-consolidation/diff-report.md

# ⑤ 环境冒烟（不写文件；plan 模式同理支持 --dry-run）
bash scripts/menu_baseline.sh snapshot --tag probe --dry-run
bash scripts/menu_baseline.sh plan --tag probe --dry-run

# ⑥ 对照表生成器的行为级自测（人为植入 3 处变动，断言逐条报出来）
python3 scripts/menu_baseline_diff_selftest.py
```

> ⑥ 存在的理由：**"同内容对自身 → 全零"只能证明不误报，不能证明会报**。
> 若生成器恒返回零，那条全零自检会稳定地绿（"稳定通过不是证据"）。所以自测反向植入
> 「测试(16) 改成仅超管 / 链接追踪器(75) 隐藏 / 学生(278) 挂到 学生信息(257) 下」三处，
> 断言对照表逐条报出，并且「被隐藏记录数 = 1、硬删除记录数 = 0」。实测 7 条断言全 PASS。

产物清单：

| 文件 | 内容 |
|---|---|
| `docs/audit/menu-consolidation/menu-tree-before.json` | **收口前基线**（回滚目标 + 验收判据的共同来源；`generated_at_utc` 在 `meta` 里） |
| `docs/audit/menu-consolidation/menu-tree-before-recheck.json` | 复测快照（与基线逐字段可比，见 §7 一致性自证） |
| `docs/audit/menu-consolidation/root-menu-plan-before.md` | 根菜单施工图数据源（40 行决策表） |
| `docs/audit/menu-consolidation/selfcheck-diff-report.md` | 对照表自检之一：同内容对自身 → 全零（证明不误报） |
| `scripts/menu_baseline_diff_selftest.py` | 对照表自检之二：植入 3 处变动 → 逐条报出（证明会报，且不误报删除） |

## 6. "只读"自证

- 本次全部命令**只有两类**：`odoo shell` 里对 `ir.ui.menu` / `res.users` / `res.groups` 的 `search/browse`（**无 create/write/unlink**），以及宿主侧 `python3` 纯文件处理。
- `scripts/menu_baseline.py` 内**不存在 ORM 写操作**。精确判据与实测（已实跑，2026-09-17）：

  ```bash
  grep -cE '(^|[^a-z])\.(write|create|unlink)\(' scripts/menu_baseline.py   # → 0
  grep -c 'cr\.commit' scripts/menu_baseline.py                              # → 0
  ```
  说明：脚本里出现的 37 处 `.write(...)` 全部是 **`stream.write()`（往内存字符串缓冲写报告文本）**，不是 ORM 写记录 —— 所以判据用了 `(^|[^a-z])\.write\(` 排除字符串方法，而不是宽泛的 `\.write\(`（宽泛口径会得到 37 个假命中，那种"自证"是无效自证）。
  脚本对数据库只用了 `search` / `browse` / `_visible_menu_ids`。
- 未做任何模块升级、未执行 `safe_upgrade.sh`、未接触生产。
- 基线落盘走"先校验后 `mv`"，且覆盖前自动留 `.bak` —— 基线被覆盖 = 回滚目标丢失，故刻意加了备份位。

## 7. 一致性自证（两次独立快照比对）

为排除"读到的是一次性/中间态"，同一口径连读两次：

- `menu-tree-before.json` 与 `menu-tree-before-recheck.json`（两次独立 `odoo shell` 会话）
- 逐字段比对（仅剔除 `meta.generated_at_utc`）→ **完全一致**
- `selfcheck-diff-report.md` 显示所有 Δ 均为 +0（A 40/40、全库 605/605、B 38/31/19 不变）
- 反向验证（`scripts/menu_baseline_diff_selftest.py`）：植入 3 处变动后，对照表报出 3 条字段级改动、
  被隐藏记录 1 条、硬删除 0 条 —— 说明上面那个"全零"是**真的没有变化**，不是生成器恒零

## 8. 已知问题与未覆盖项（不许当成"已覆盖"）

### 8.1 一次观测到的数值漂移（无法复现，但必须留档）

**11:0x 的一次临时读数**是 backoffice = 30 根 / 402 总数；而此后 **11:32 起的四次独立读数**稳定为 **31 根 / 391 总数**（含两次完整快照 + 逐字段比对一致）。
两次读数之间发生过的、可观察的环境事件只有一件：**web 容器在 10:59:08 被重启**（`docker inspect` 实测 `StartedAt=2026-09-17T02:59:08Z`），同期审计方在跑菜单审计（容器日志里有 `GET /web/webclient/load_menus?unique=audit`）。

- 影响面：**只影响"哪个数更早"**，不影响当前基线（当前值已四读一致）。
- 处置：**不做归因猜测**。验收时**必须现场重测**（§5 的 ①/④），不得引用本文档的历史数字当判据 —— 这是本条留档的真正目的。
- 若后续再出现漂移，可用 §5 的 ④ 直接定量定位到"哪条菜单的哪个字段变了"。

### 8.2 覆盖范围声明（本工具与本文档不覆盖什么）

- 只覆盖 `ir.ui.menu` 记录本身 + **ORM 层**可见性；
- **不覆盖**：前端 JS 二次过滤（如 debug 模式的 `base.group_no_one`）、`website.menu`（另一张表）、门户/网站导航、点开 action 之后的业务可见性；
- **不覆盖**：组继承链的"为什么" —— 本文档只给 `implied_ids` 的实测结论，不替代权限审计。

### 8.3 发现的机制性风险（供 t2 施工时避开）

1. **"改完不复现"风险**：`scripts/seed_teacher_menus.py` 是**手工 ORM 改库**（脚本头注明"shell 脚本没有 XML data"），不在模块 `data/` 里 ⇒ **模块升级不会重放它**。t2 的收口改动若照此办理，会出现"升级后菜单又变回来"。**建议 t2 一律做成模块 `data/*.xml` 里的 `<function>`（每次 `-u` 重放，幂等）**。
2. **"改了但没生效"风险**：目标菜单里 `测试`(16)、`数据清除`(566)、`学生信息`(257)、`考试`(325) 等的 `group_ids` 为空 —— 空组 = 全员可见，**只隐藏父菜单不隐藏后代是无效的**（子菜单可见会把父链整条拉亮，这正是 seed 脚本注释里记过的坑）。

## 9. 交给 verifier / 复核的接口

- **验收判据**：以 `_visible_menu_ids()` 读出的 **B(faculty/backoffice) ≤ 12、B(admin) ≤ 20**（队长裁定）。
- **验收方式**：收口后重跑 §5 的 ①/④，产出 `diff-report.md`；其中 §2「不再可见的根菜单 → 新路径」必须逐条给出"新路径或确认下线"。
- **回滚目标**：`menu-tree-before.json`（逐条记录 id + active/parent_id/sequence/group_ids 的原值）。
- **注意**：回滚脚本本身也在 t2 范围内（`--rollback` 一键还原），**届时也请按"升级 `-u` 后仍生效"验证**，而不是只验一次 ORM 改回。

---

## 10. 后续进展与当前阻塞（2026-09-17 中午更新）

> 本节由 menu-eng 追加，记录 §1~§9 之后发生的事，避免"基线报告停在只读阶段"造成误读。

### 10.1 已完成的落地链路（每步独立 commit）

| commit | 内容 |
|---|---|
| 49bfcd0 | 执行器 `scripts/consolidate_menus.py/.sh` + 声明式计划 `menu-consolidation-plan.json`（12 容器 / 15 合并 / 12 隐藏 / 1 不改，40 根全覆盖） |
| 639b6e4 | XML 声明式落地机制**实测通过**：`-i edu_nav` 与再次 `-u edu_nav` 后菜单快照逐字段全 0；指向菜单 1 的 xmlid 仍唯一且仍属 `base` |
| 8090cea | `custom_addons/edu_nav`（惰性装载）+ 装载期守卫 + `scripts/verify_edu_nav.py` 行为级自测 |

### 10.2 关键机制结论（实测，不是推断）

- **605 条 `ir.ui.menu` 的 `noupdate` 全为 0** ⇒ 普通 `<record>` 每次 `-u` 都会重放
  ⇒ 「升级后仍生效 + 幂等 + 可回滚」**天生成立**，不需要 `<function>`/server action。
- 我方模块用 `record id="base.menu_administration"` 写基座菜单**安全**：不产生第二条 xmlid、不窃取基座记录。
- `post_init_hook` **只在 install 跑**（`-u` 不跑）—— 与仓内 `edu_zh/__init__.py` 的批注一致；守卫因此改挂在
  无条件的 `_register_hook` 上（第一版加了 `registry.ready` 判断，结果 `-u` 时守卫被静默跳过）。

### 10.3 dry-run 预测（按队长裁定②口径试算；事务内试算+回滚，未落库）

| 角色 | B 前 | B 后（组策略 (a) 下） | 验收线 | 结论 |
|---|---|---|---|---|
| admin | 38 | 13 | ≤ 20 | ✅ |
| backoffice@local | 31 | 12 | ≤ 12 | ✅ |
| faculty@local | 19 | 11（**需把 faculty 加入组 87**） | — | ✅ |

- 若**不**把 faculty 加入 87：faculty 的 B 会变成 **0**（组 87 里没有 faculty，12 个容器全看不见）。
  这是当前唯一阻塞项，已提请队长裁定 (a)/(b)/(c)。
- dry-run 当场抓到并已修的真缺陷：**隐藏类只收窄不整棵停用**时，admin 反而**多**解锁
  （B 12→23、C 400→409）——原被权限挡住的子项改由 `group_system` 放行；改为整棵 `active=False` 后回到 13/261。

### 10.4 证据文件

- 机制探针：`menu-tree-pre_nav_probe.json` / `post_nav_probe.json` / `post_nav_reupgrade.json` + `nav-probe-diff-report.md`（全 0）
- 执行器预测：`dryrun-report.json`（含 before/after 数字与 after 根清单）
- 回滚依据：`rollback-basis.json`（受影响菜单的改前原值：active / group_ids / parent_id / sequence）
- 行为级自测：`python3 scripts/verify_edu_nav.py`（4/4 PASS，含"探针命中"：故意写错期望条数时守卫确实报 ERROR）

### 10.5 裁定后的一步生效动作

```bash
python3 scripts/gen_menu_data.py            # 由计划 JSON 生成正式 data（默认 --emit=all）
bash scripts/safe_upgrade.sh edu_nav        # 落库（普通 record 重放）
bash scripts/menu_baseline.sh snapshot --tag after
python3 scripts/menu_baseline_diff.py docs/audit/menu-consolidation/menu-tree-before.json \
        docs/audit/menu-consolidation/menu-tree-after.json --out docs/audit/menu-consolidation/diff-report.md
```

---

## 11. 落库结果与口径地图（2026-09-17 收口完成）

### 11.1 三口径对照表（**不要混用**）

| 角色 | 可见根（前端 appID / ORM B） | 叶子（前端） | 叶子（ORM C） | 总数（前端节点） |
|---|---|---|---|---|
| admin | 38 → **14** | 400 → **294** | 400 → 306 | 551 → 358 |
| backoffice | 31 → **12** | 279 → **153** | 279 → 153 | 391 → 184 |
| faculty | 19 → **9** | 115 → **62** | 115 → 65 | 164 → 75 |
| student / parent | 0 → 0 | — | — | — |

- 口径 A：根菜单 40（active 39→14、inactive 1→26）；**全库菜单 605 不变**（零删除、零新增）。
- 前端叶子与 ORM 叶子的差（admin 12 / faculty 3 / backoffice 0）来自前端会剔除
  `base.group_no_one`（技术菜单）等 debug 过滤 —— 两套口径并列写在这里，避免后人拿两个数对不上。
- 记录数自证：全库 605、根 40、停用 200（= 25 个根 + 其子树）。

### 11.2 兑现的四项要求

1. **三条线现场实测**（见 11.1）——达标：admin 14 ≤ 20、backoffice 12 ≤ 12、faculty 9。
2. **`diff-report.md`**：每个被隐藏入口 → 新路径/确认下线；②重名子项裁定表；(b′) 300 例外表。
3. **真实回滚演练**：`scripts/rollback_menus.py --apply` → 新会话实测 **admin 38 / backoffice 31 / faculty 19**
   （= 收口前），回读断言 0 条不一致；再 `gen_menu_data.py --state=baseline` + `-u` 回到 14/12/9（可复现）。
4. **`-u` 重放后仍生效**：重复升级后三行数字完全不变（幂等）。

### 11.3 回滚演练暴露的两个坑（已修，供后人避让）

- **`rollback-basis.json` 不足以整表还原**：它只覆盖"当次 dry-run 的 DESIRED"；被"折父"迁走的子菜单
  若那次已在目标父下，就**不在依据里** ⇒ 回滚后它们仍留在新容器下（实测 admin 只回到 30 而非 38）。
  修法：以**完整基线**（`menu-tree-before.json`，605 条全量快照）为权威驱动回滚，即 `scripts/rollback_menus.py`。
- **`load_menus` 结果按会话缓存**：回滚后必须用**新登录会话**测量，否则读到旧值（曾误判"回滚不彻底"）。

### 11.4 守卫基线（避免以后每次升级误报）

`ir.config_parameter edu_nav.consolidated_count = 357`（生成器写入，等于数据文件里生效的记录条数）；
`custom_addons/edu_nav/models/menu_consolidation.py` 的 `MENU_CONSOLIDATED_COUNT` 同值。
两者不一致时守卫会在升级日志里报 ERROR（`scripts/verify_edu_nav.py` 有探针证明它会报）。

### 11.5 档2 的最终实现（逐棵，与库内真值一致；2026-09-17 校准）

> 起因：早前文档里有"档2 六棵都整棵 active=False"的表述，与库内实际不符。**以库为准**，逐棵如下
> （`menu-consolidation-plan.json` 的 `tier2_admin_only[].mode` 与之一致）：

| 档2 根 | plan mode | 库内实测（psql 直查） |
|---|---|---|
| 121 联系人 | `deactivate_tree` | active=False；12 个后代全 False |
| 142 发票 | `deactivate_tree` | active=False；56 个后代全 False |
| 196 员工 | `deactivate_tree` | active=False；33 个后代全 False |
| 566 数据清除 | `deactivate_tree` | active=False；4 个后代全 False |
| 1 设置 | `restrict_tree` | active=True，groups=[4]；根 + 116 个后代全挂超管组 |
| 15 应用 | `restrict_tree` | active=True，groups=[4]；根 + 8 个后代全挂超管组 |

理由（两条并存、不是二选一）：
- `deactivate_tree` 用于**本校本就不用**的四棵：整棵停用最干净，同时避免"只收窄根"导致
  子树里原本被权限挡住的节点被 `group_system` 放行（实测那个变体会让非超管叶子反涨）；
- `restrict_tree` 用于**系统级入口**的两棵（设置/应用）：不能停用（否则超管自己也进不去设置面板），
  但必须"根 + 全部子树"一起挂超管组，否则同样会漏给非超管。

### 11.6 库内真值的稳定读数（三次独立读取，供复核对表）

| 指标 | 读数（3 次一致） |
|---|---|
| 全库菜单 | **605** |
| 根菜单（parent_id IS NULL） | **40** |
| 其中 active | **14** |
| 停用菜单总数 | **200** |

> ⚠ 对表提醒：如果复核时读到 `active 根 = 18 / inactive = 91`，那是**另一个时间点**的库状态
> （更早的 `restrict_only` 变体：当时 4 棵档2 未整棵停用、收口值也尚未被 noupdate 保护）。
> 当前态可随时用 `python3 scripts/consolidation_persist.py --status` 与
> `python3 tests/audit/verify_consolidation.py --phase after` 复读。
