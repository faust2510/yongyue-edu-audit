# 独立验证报告：权限分层收口（t4 · verifier）
> **状态**：`归档` ｜ **主题**：`权限分层验证` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 一句话结论：**「教务≠系统管理员」这条分层在本地 edu19 上站得住**（红线可复算、双判据齐、门户无误伤）；
> **但判据③ 未达标** —— 教务经「网站/配置/应用」仍可进入系统管理面（模块列表），
> 该修复在 t1 已 completed 的情况下**未交付**（findings F-1）。其余四项复算与执行者读数一致。

采集者：verifier（attempt `e6857f45`）｜ 采集库：**本地 edu19** ｜ 采集时刻：见每条。
本报告**不采信执行者自述**：每一项都是我自己跑出来的读数，执行者读数并列在后。

---

## 0. 环境前提（三要素：库 + 时刻 + 是否含 edu_nav 收口）

| 项 | 值 |
|---|---|
| 库 | **edu19（本地 edu19-clone-web-1）** |
| edu_nav 菜单收口 | **已应用**（停用 200 条：全库 605 = active 405 + inactive 200） |
| 生产 | **未安装 edu_nav**（生产 603 active / 607 全库；来源为队长生产读数，**本工作区无法复现**） |
| 演示链路 | 课业链路**已恢复**（王小明档案 14 门，`scripts/seed_wangxiaoming_subjects.py` 口径） |
| 容器扰动 | 14:00–16:45 期间容器被 `safe_upgrade.sh` 多次重建（所有读数**带时刻**，**不跨重建相减**） |

> ⚠️ 生产口径未在本工作区复现：「生产教务可见 391」来自队长在生产库的读数（有命令/时刻/跨库计数互证）；
> 我**没有生产访问**，因此列为**执行者读数**，不作为我的验证结论。

**口径纪律**：菜单数字一律用**口径 B** = `GET /web/webclient/load_menus?db=edu19` 的数字键条目（前端从根建树）。
口径 A（`ir.ui.menu._visible_menu_ids()`）**只作交叉参考**：实测 **B ⊆ A**，A 多出的全是「父根不可见」的孤儿
（教务 A−B=15、admin A−B=37；逐条核过 **37 条全部有隐藏祖先**）。
**陷阱**：不带 `?db=` 时 `load_menus` 对 admin 返回**网站 HTML** 而非 JSON（我踩过）。

---

## 1. ① 复跑 t1 巡检脚本并与 t1 报告对照

```
$ NO_PROXY=localhost,127.0.0.1 python3 tests/smoke/backoffice_reachability.py
T1_GATE_EXIT=0        # 16:44:49 起跑 → 16:46:57 结束；HEAD=1f2b9bc；窗口安静（lock absent，0 并发冒烟）
== 汇总 ==  PASS 87 / FAIL 0 / GAP 2     结论：全绿
```

我自己的关键输出：

- `L1 前端可见菜单 181 条`（根：图书馆、学生信息、招生、招聘管理、教务审批、时间表、灵命生活、综合评估、网站、财务管理、资产管理、资料下载）
- 红线三条全 PASS：教务有效组 **20** 个不含 `base.group_system`；教务组 implied 闭包不含；5 个业务管理组仍在
- 收口回归 5 条全 PASS（网站/活动、电子商务/付款方式、网站/技术/会话×3：教务不可见、超管可见）
- E2E 三条真跑 PASS，**夹具清场 leftover=0**（六张表按标记核查）

**与执行者对照**：

| 项 | 执行者（t1） | 我（verifier） | 判定 |
|---|---|---|---|
| exit code | 0 | **0** | ✓ 一致 |
| PASS 数 | 86 | **87** | 差 1（见下） |
| L1 可见菜单 | 184→**179**（16:41:11 快照） | **181**（16:44:14，含 t13 新入口 +2） | 带时刻的两次快照，**非矛盾** → 登记项 **N-2** |
| 死角 5→0 | 5 条规则菜单 | 5 条均实测对教务不可见 | ✓ 一致 |

**86 vs 87 的差异**：脚本内 `收口回归` 断言 5 条；差额 1 条我无法从 t1 报告定位（报告未逐条列）。登记为**轻微口径差**，不影响结论。

---

## 2. ② 教务能办业务流程（真跑 + DB 反查）

```
# odoo shell，2026-09-17 16:48:50 本地（全部以教务身份写，最后 sudo 清场）
MARK CREATED id=23 state=new
MARK FLOW {'review': 'review', 'admitted': 'admitted'}     # ← with_user(backoffice) 写
MARK MATERIALS 7/7 all_true=True
MARK DB_RECHECK id=23 state=admitted name=【冒烟】t4-verifier mats=7
MARK LEFTOVER=0
```

方法（唯一正确的写法）：教务对 `edu.application` 是 **读✓写✓建✗删✗**（设计如此：申请由公开报名表产生，教务只审核）
⇒ 夹具用 **sudo 建替身**（充当公开报名表），**状态流转与材料核对全部以教务身份执行**，最后 sudo 清场。

- 结论：**教务确实办得到**（`new → review → admitted` + 材料 7/7，DB 反查确认，非只看页面）
- leftover=0 ✓
- 与执行者对照：t1 的 E2E① 报 `app#17 新申请→审核中→已录取，材料 7/7` ✓ **同一流程、同一结论**

---

## 3. ③ 教务不能办管理事务（双判据）

| 目标 | 判据一：菜单 | 判据二：直连 |
|---|---|---|
| 「设置」根 | **不可见** | `ir.config_parameter` **FFFF** + RPC `AccessError` |
| 「应用」根 | **不可见** | — |
| 装卸模块 | — | `ir.module.module` `r/w/c/u = T/F/F/F` ⇒ **不能装卸** |
| 改系统参数 | — | `ir.config_parameter` FFFF |
| 改视图／自动化／模型 | — | `ir.ui.view`、`base.automation`、`ir.model` 全 **FFFF** |
| 正面控制 | — | **admin 全 TTTT**（证明判据有区分度，不是对谁都 F） |

红线复测 ✓：`group_op_back_office_admin` 的 `implied_ids` 与 `all_implied_ids` **均不含 `base.group_system`**。

**⚠️ 但队长修订后的判据（按「动作指向」而非「菜单名」）未达标 —— findings F-1**：

```
MARK FORBIDDEN_backoffice = 1  ids=[238]      # 目标 = 0
MARK FORBIDDEN_admin      = 19                # 正对照（稳定）
MARK 238 name=应用 parent=网站/配置 groups=[edu_portal.group_backend_full, base.group_system] visible_to_bo=True
RPC: ir.module.module search_count (教务) = 731
     POST /web/action/load(336) = OK res_model=ir.module.module view_mode=kanban,list,form
```

⇒ 教务点得进「网站/配置/应用」，能看到**全部 731 个模块**。**不是提权**（写权限 F/F/F），
但「教务不能进应用」按字面不成立，且与「开发者=系统管理」的分层意图冲突。

---

## 4. ④ 教师／学生／家长边界（实测判据）

**教务专属路由（5 条）—— 双判据（教师 303 且教务 200）**：

```
faculty@local     /ledger 303 /ledger/new 303 /ledger/reimburse 303 /ledger/export 303 /edu/audit 303 → 全 /my/home
backoffice@local  同 5 条 → 全部 200     ← 正对照：证明教师的 303 是角色边界，不是页面坏了
```

**后台外壳**：`backoffice 200`；`faculty 200`（**内部用户，设计如此**，见 code-map §9）；`stu 303→/my`、`parent 303→/my` ✓

**教师层收口**：可见根 **9** 个，**不含 设置／应用／数据清除**；**指向系统管理面模型的入口 = 0**；
`has_group(base.group_system)=False`、`has_group(教务组)=False` ✓

**t13 补回的两个入口（实测 16:42:53 创建）**：

| 入口 | 教务 | 教师 |
|---|---|---|
| `邀请码`(790, act_window→`edu.invite.code`) | 可见 + `search_count=5` ✓ | **AccessError** ✓ |
| `老账号补挂身份`(791, act_url) | `GET` **200** + 页面含标题 ✓ | **303 → /my/home** ✓ |

⇒ 两条都满足「教务看得见**且打得开** / 教师看不见**且到不了**」。
（旧的 542／606 仍 `parent=ROOT + active=False`，是**被替代的旧记录**，非缺口。）

**门户数据面（方法学结论，重要）**：学生／家长**直连 RPC** 对 `op.student` 得 **0 条**、
对 `op.result.line`／`edu.fee.bill` 直接 `AccessError`；而 `/my/fees` 仍能渲染出账单。
⇒ **门户数据隔离是在 controller 层用 `sudo()` + 显式作用域实现的，不是靠记录规则** ⇒
**数据级判据必须走门户路由；直连 RPC 一律 deny-by-default，测出的 0 条只能证明 deny-by-default，证明不了隔离。**

---

## 5. ⑤ 文档数字抽查（t3 `docs/plans/perm-model.md`）

| t3 文档写的 | 我的独立读数 | 判定 |
|---|---|---|
| 教务 **179** 节点 / 12 根（口径 B，16:41:11 快照） | **181** / 12 根（16:44:14） | 快照差异 → **N-2（非 finding）** |
| admin **358**（16:41:11 快照） | **360**（16:44:14） | 快照差异 → **N-2（非 finding）** |
| 教师 **75** | **75** | ✓ |
| 有效组 **20**、不含 `base.group_system` | **20** / 不含 | ✓ |
| 可写模型 **41/45** | **41**（`--dump` 16:49:17） | ✓ |
| 死角 5→0 | 5 条规则菜单均不可见 | ✓ |

**N-2（登记项，非 finding —— 按队长 2026-09-17 口径）**：判定规则 =「只有**无时刻的数字**、或**同刻却对不上**才是 finding」。本条两者皆不成立：
文档数字**带来源与时刻**（§5 表格的「来源」列写明「t1 报告 §8；本文件 16:41 复采一致」），且 **t3 已在 §134 显式登记**下述预告 ——
「上表的『不可见』是 16:10 之前的状态；菜单数字（**179→181、admin 358→360**）与三角色表**待 t13+t15 收口后一次性同步**」。
⇒ 这**不是隐瞒**，是**已声明待同步**；我实测的 181 / 360 **恰好等于 t3 预告的值** ✓ ⇒ t3 的预期正确，只差落笔。

> **残留提示（不判红，仅供读者注意）**：正文（L2 三角色行）仍写着 179 / 358，读者若只读该行会先读到快照值；
> §134 那条预告在其下方。docs-eng 已获授权在 t13 收口后同步（原文保留 + 追加快照更正行 + 三角色表）。
> **我实测时刻**：2026-09-17 16:44:14（教务 181 / admin 360 / 教师 75）与 16:49:17（`--dump`：181 / 可写模型 41）。

**179→181 的成因（我定位到条目）**：`load_menus` 集合 diff ——
`消失 = {373, 488, 524, 525, 526}`（正好是收口的 5 条）、`新增 = {790, 791}`（t13 补回的两个入口，创建于 **16:42:53**）
⇒ 184 − 5 + 2 = **181** ✓。t3 的 16:41:11 复采得 179，**在其采集时刻是对的**，两分钟后被 t13 改变。

---

## 6. Findings

| id | 严重度 | 问题 | 证据 | 建议 |
|---|---|---|---|---|
| **F-1** | **medium** | 判据③ **未达标**：教务经 `网站/配置/应用`(238) 仍可进模块列表（731 条）。**t1 已 completed 但该修复未交付** | `FORBIDDEN_backoffice=1`；`NARROW_RULES` 只有 5 条**不含 238**；全仓 `grep menu_website_add_features` **0 命中**；t1 提交 `3ef6cba` 与本项无关 | 加一条 `NARROW_RULES`（`['base.group_system']`）**并**让 `seed_teacher_menus.py` §3 不覆盖它（§3 遍历「网站」整棵子树，会把含 238 的节点写成 `[87]`），再加 seed 幂等复跑断言 |
| ~~F-2~~ → **已按队长口径撤下（改为登记项 N-2，见 §5）** | ~~low~~ | ~~t3 文档正文的 179 / admin 358 已过期~~ | 按队长口径「数字带时刻 + 已显式登记待同步 + 同刻不矛盾 ⇒ 不是 finding」判定为**漂移可审计**，不计 finding | 无需修复；待 docs-eng 在 t13 收口后按预告同步 |
| **F-3** | info | 教师与教务对 `ir.module.module` 同为 `read=T`（ACL 层） | 实测 `r/w/c/u` 两者皆 `TFFF` | 238 属**菜单可见性**泄漏而非 ACL 泄漏；若按 ACL 收会牵连教师 |

---

## 7. 未验证面／半覆盖／假绿登记（如实，不省）

**未验证面**
1. **生产口径**（391 等）—— 本工作区无生产访问，无法复现；作为执行者读数并列，不作我的结论。
2. **「09:12 清空」的操作者** —— `edu_audit_log` 56 行**全为审批留痕、无删除行**，且空单审批通过的前提是档案已空
   ⇒ **该表在结构上无法定位清空者**。**动作与操作者：未验证。**
3. 浏览器级渲染／按钮可见性 —— 我只证到「action 可 load + 模型可读」，未做 DOM 级断言（238 是否渲染出「安装」按钮：未验证）。

**半覆盖**
1. **可写模型 41/45** 我未独立重算（复用 t1 `--dump` 的 41 与分母口径 45）——只核了「41」这个数。
2. **admin 侧口径 B 正对照** 仅在带 `?db=` 时可取（360 ✓）；不带参数返回网站 HTML，属陷阱非缺口。
3. `stu@local` 的 `load_menus` = **403**（门户用户无菜单树）⇒ 该口径对门户角色不适用。

**假绿（含我自己产出的，已撤回）**
1. 我先前报的「教务 199 可见菜单 → unopenable=0」**近似同义反复**：`_visible_menu_ids()` 本身已排除 action 模型不可读的菜单
   ⇒ 该扫描**不可能失败**，**不作为「无死角」的证据**（已撤回）。
2. 旧 p2 `#10` 判据 `red_ok = … and '14' in r40.text` **双向不可靠**：我 16:12 那次跑完档案只有 **1 门**，`#10` 仍记 **PASS**
   ⇒ 那个 `'14'` 是被页面其它数字撞上的 ⇒ **旧判据的「数字」那半从没在验「档案有 14 门」**。
   队长已改为动态读 `n_cur` 且加 `n_cur > 0`（我复跑 **13/13 exit 0**，并核过其变异测试 `n_cur+999` 仍能红）。
3. **口径混用**：同一概念在不同通道量出不同的数（391／199／184、口径 A／B、122／120）⇒ 已按「同一判据锁定唯一采集通道，换通道必须重采」执行。

**已钉死的根因（供后续引用）**
- 王小明档案科目被清空：**经队长批准的破坏性实验**已把强推断转为**直接观测** ——
  `tests/smoke/subject_bulk_scope.py` 的 `clone()` 克隆 id 最小的行并继承其 `doc_type=course_change`
  （全库分布 `course_change×11 / subject_registration×1`）⇒ `registration.py:164` 的**空单防呆不适用** ⇒ 批量审批把空 payload 写回档案。
  实验读数：跑前 **1 门**（审计 1898）→ 只跑一次（`EXIT=0, 26 PASS`）→ 跑后 **0 门／审计 1915 同微秒／写者 faculty@local** → **18 秒内恢复 14 门**并复核 p2 的 `#10` 前置（档案非空）。
  **边界**：这是**本次会话的观测**，不外推为「所有脚本都如此」。

---

## 8. 复跑方式

```bash
# 0) 前置：安静窗口（我全程按此执行）—— 条件 = 无 ^python3 tests/smoke/ 进程 且 无升级锁
#    （锁路径：EDU_UPGRADE_LOCK > TMPDIR > /tmp）
# 1) 本任务的 verify 命令
NO_PROXY=localhost,127.0.0.1 python3 tests/smoke/backoffice_reachability.py     # 期望 exit 0
# 2) 只读基线（口径 B + 可写模型）
NO_PROXY=localhost,127.0.0.1 python3 tests/smoke/backoffice_reachability.py --dump /tmp/d.json
# 3) 门户回归（工具不在本任务 inScope，引用其读数）
NO_PROXY=localhost,127.0.0.1 python3 tests/smoke/portal_regression_smoke.py     # 期望 101/101 exit 0
```

**退出码**：本任务 verify 命令实测 **exit 0**（16:46:57）。

---

## 9. 结论

- **分层成立**：教务≠系统管理员（红线可复算）、教务办得到业务（真跑+反查）、教务办不了系统管理（双判据 + 正对照）、
  三角色门户边界清晰且无误伤（错误口令→exit 1、站点不可达→exit 2、变异测试→1 FAIL，判据有牙齿）。
- **一处未达标**：**F-1（238 → 模块列表）** —— 教务仍可进系统管理面；修复未交付。
- **一处待同步（非 finding）**：**N-2** —— 文档快照 179/358 在 t13 补回两入口后已成 181/360；
  文档数字带时刻、且 t3 已预告待同步、同刻不矛盾 ⇒ 按队长口径判为**漂移可审计**，docs-eng 已获授权收口后同步。

---

## 10. 正式留档复跑（t17 —— 文件稳定后的门禁读数）

**为什么单独留档**：signup-eng 在 t13 报告中指出，`tests/smoke/backoffice_reachability.py` 在他运行期间被并发改过
（md5 `1d0f7ad1` → `0e7c9433`），导致他对旧版跑出 PASS 87 / GAP 2、对更新版跑出 PASS 91 / GAP 0 ——
**两次读数落在不同版本上**，不宜直接作正式留档。本节即在**确认文件不再被并发修改**后重跑。

### 10.1 前置确认：文件稳定 + 安静窗口

| 检查 | 读数 |
|---|---|
| 文件 md5（执行版） | `409216bc5411615836be095dad7daa67` |
| 文件 mtime | 2026-09-17 **17:01:47** ⇒ 起跑前 age = **676 秒（≥5 分钟）**，满足「5 分钟内有改动则等」 |
| **跑前跑后 md5 是否一致** | **NO_MIDRUN_EDIT = yes**（跑前跑后均为 `409216bc`）⇒ **本次运行期间文件未被修改** ← 这是 t17 的核心条件 |
| 安静窗口 | `lock=absent`、`pgrep '^python3 tests/smoke/'` = **0**（起跑与结束时皆为 0） |

### 10.2 三要素（提交 hash + 采集时刻 + 文件 md5）

- **文件 md5**：`409216bc5411615836be095dad7daa67`（工作树版本）
- **采集时刻**：**2026-09-17 17:13:25 → 17:15:52**（本地时区；起跑/结束）
- **提交 hash**：HEAD `7c6a2ab`（起跑时）→ `3fdbbee`（结束时；该提交**未含本文件**，期间本文件 md5 不变）

> ⚠️ **必须与读数一起读的一条**：该文件在采集时处于 **未提交的已修改状态**（`git status` = `M`）。
> 起跑时 HEAD 版本内该文件的 blob md5 是 `fa65921a135b9e61514ec0a3246a14fb`，**与执行版不同**。
> ⇒ 「提交 hash」标识的是**仓库状态**，不是**被执行的那份文件**；执行版的**可复现凭据是 md5 `409216bc…`**。

### 10.3 门禁读数（PASS/FAIL/GAP + 静态断言首行）

```
$ NO_PROXY=localhost,127.0.0.1 python3 tests/smoke/backoffice_reachability.py
GATE_EXIT=0        # 17:13:25 → 17:15:52

# 静态断言（脚本输出第 3 行，首行读数）:
PASS | 静态·层分离 | 0 处「只挂 base.group_system」的自家菜单（例外清单 0 条）；
                边界：custom_addons/*/views/*.xml —— 56 个文件 / 52 个 <menuitem> / 9 个 ir.ui.menu <record>（基座与 data/*.xml 按设计排除）

L1 前端可见菜单 180 条（根：图书馆、学生信息、招生、招聘管理、教务审批、时间表、灵命生活、综合评估、网站、财务管理、资产管理、资料下载）

== 汇总 ==  PASS 91 / FAIL 0 / GAP 0
结论：全绿（0 条缺口为已知历史问题，未判红；--strict-gaps 可判红）
```

**与 signup-eng 两次读数对照**：

| 来源 | 版本 | 结果 |
|---|---|---|
| signup-eng（旧版） | md5 `1d0f7ad1` | PASS 87 / GAP 2 |
| signup-eng（更新版） | md5 `0e7c9433` | PASS 91 / GAP 0 |
| **本留档（verifier）** | md5 **`409216bc`**，且跑前跑后一致 | **PASS 91 / FAIL 0 / GAP 0，exit 0** |

⇒ 与 GAP 归零后的形态一致；GAP 2 → 0 是因为 t13 补回了两个入口菜单。

### 10.4 持久性复核（t17 要求的两条）

**① 542 / 606 仍停用** —— 实测 + 只读核对声明：

```
MARK OLD id=542 name=邀请码          active=False parent=None   # 2026-09-17 17:02:31 实测
MARK OLD id=606 name=老账号补挂身份   active=False parent=None
```

- **声明来源**：`custom_addons/edu_nav/data/menu_consolidation_data.xml` 第 2707 行（542）与第 3023 行（606），
  均为 `<record ... forcecreate="0">` + **显式 `<field name="active" eval="False" />`** ⇒ 停用是**声明式**的，可幂等重放 ✓
- **对 `-u edu_portal` 的判断（只读核对，未真跑两次升级）**：`edu_portal` 至今**仍声明**这两个 xmlid
  （`views/invite_code_views.xml:178/193`、`views/menu_icons.xml:22`），但其 `<menuitem>` **不声明 `active`**
  ⇒ 按 Odoo 加载语义，`-u edu_portal` 会重写它声明的字段（name/parent/action/…），但**不会把 `active` 改回 True** ⇒ 停用可存活。
  **这是基于声明与加载语义的推断，不是我实跑的读数**（本任务只允许只读核对；真跑两次 `-u` 会占全队安静窗口）。

> 🔻 **可移植性提示（不判红）**：542/606 的「停用」是 **edu_nav** 这个模块的事实。
> **生产未安装 edu_nav**（见 §0）⇒ 在生产这两个菜单**不会被停用**，会以其原有组可见。
> 这与已知的「生产 / 本地菜单口径不同」同源，登记备查，不作为缺陷。

**② 新入口 790 / 791：教务可见、教师不可见** —— 实测 + 声明：

```
MARK NEW id=790 name=邀请码         active=True parent=学生信息/配置 groups=[group_op_back_office_admin, base.group_system] | bo_visible=True faculty_visible=False
MARK NEW id=791 name=老账号补挂身份  active=True parent=学生信息/配置 groups=[group_op_back_office_admin, base.group_system] | bo_visible=True faculty_visible=False
```

- **声明来源**：`custom_addons/edu_portal/views/invite_code_views.xml` 第 212 / 218 行，
  `parent="openeducat_core.menu_op_school_config"`、`groups="openeducat_core.group_op_back_office_admin,base.group_system"`
  ⇒ 与实测的「教务组」单一门槛一致；教师既不在教务组也不在系统组 ⇒ **组闸本身就把它挡住（不依赖 ACL）** ✓
- 上一轮 t4 另已实测这两条的**功能可达性**：邀请码 教务 `search_count=5` / 教师 `AccessError`；
  老账号补挂身份 教务 `GET 200 + 标题命中` / 教师 `303 → /my/home`（见 §4）⇒ **「看得见且打得开 / 看不见且到不了」** ✓

### 10.5 边界与未验证面（本节）

1. **执行版未提交** —— 见 §10.2 警示：md5 `409216bc` 不对应任何提交的 blob；可复现凭据是 md5，不是 HEAD。
   根因是当时工作树正在被编辑（`git status` = `M`，mtime 17:01:47）。本轮已用「age ≥5 分钟 + 跑前跑后 md5 一致」把**运行期**污染排除，但无法替他人决定是否提交。
2. **「连续两次 `-u edu_portal` 后仍如此」按任务允许的「只读核对声明」执行**，未真跑升级。已给出声明级依据与加载语义推论，并标注为**推断**。
3. 本节读数**只对 md5 `409216bc` + 上述时刻有效**；该文件此后若再被修改，本留档不自动延续。

