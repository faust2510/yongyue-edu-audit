# edu_nav 上不了生产：取证、判断与前置条件（2026-09-29）

> 触发：用户报告「`edu_nav` 既不在 rsync 同步列表、也不在 `-u` 列表 ⇒
> `custom_addons/edu_nav/data/menu_consolidation_data.xml` 的任何改动永远上不了生产，
> 对「菜单收口」这类工作是静默失效」。
>
> 本文是**实测取证 + 判断依据**；结论写在 §1，动手前的先决条件写在 §5。
> 相关：`docs/audit/finding-F1-menu-replay-on-upgrade.md`（升级重放）、`docs/audit/menu-consolidation/diff-report.md`。

---

## 0. ✅ 2026-10-02 更新：**阻断已解除**（下面 §1–§5 保留为当时的取证，勿当现状读）

**结果**：`bash scripts/safe_upgrade.sh edu_nav` → **EXIT=0**；部署已改为**两趟**（主升级 → 单独 `-u edu_nav`），
并用部署脚本的真实模块表在本地跑通两趟（PASS1_EXIT=0 / PASS2_EXIT=0）。四棵根菜单 542/543/576/606 保持 `active=f`。

**根因升级为源码级判据**（原来是「实测现象」，现在是可推导的规则）—— 读 `odoo/tools/convert.py` 的 `_test_xml_id`：

```python
if module != self.module:
    modcnt = env['ir.module.module'].search_count(
        [('name', '=', module), ('state', '=', 'installed')])
    assert modcnt == 1, 'The ID "%s" refers to an uninstalled module'
```

⇒ **被引用模块必须恰好是 `state='installed'`；`to upgrade` 不算**。同一批 `-u` 里的模块会先被全部置成
`to upgrade` ⇒ 只要 edu_nav 的数据引用了**同批升级模块**的 xmlid，就**必然**断言失败（与 `forcecreate` 无关，
断言在写入之前）。这一条同时解释了本文 §2.3 的两种崩法：
  · `-u edu_nav` 单独 → 崩在 5 个**已卸载**模块的 xmlid；
  · `-u edu_portal,edu_nav` → 崩在 `edu_portal.menu_edu_invite_code_root`（那一刻 edu_portal 是 to upgrade）。
⇒ **推论（对本仓有普遍意义）：任何「跨模块引用他人 xmlid」的数据文件，都不能与它所引用的模块同批 `-u`。**

**做了什么**：
1. `scripts/gen_menu_data.py` 新增 `uninstalled_modules()`，发射前剔除「xmlid 属未安装模块」的条目
   （这些菜单在盘上**根本不存在**，属「计划里还留着、盘上已经没了」的陈旧引用，删之无损）。
   实测 `[filter] 跳过 23 条`，353 → **330** 条；文件头计数、模块常量、库内参数三处同步。
2. `scripts/deploy_myedu.sh` 改成两趟（第二趟失败不让第一趟的成功被吞掉，合并退出码交给失败特征扫描）。
3. 顺手删掉生成器里**被粘了两遍**的 `duplicate_children` for 循环。

**反向自证**：塞回 1 条 `account_payment.payment_provider_menu` ⇒ 立刻 **EXIT=255** 且原样复现那句
`AssertionError: ... refers to an uninstalled module`；删掉 ⇒ EXIT=0 且文件与生成器产物 `diff -q` 逐字一致。

**⚠ 一处预测未被复现（诚实记）**：本文 §2.5 与 §1.3 预测 `-u edu_portal` 会把四棵根菜单重新点亮（F1）。
2026-10-02 实测**未复现** —— 跑完 `-u edu_portal` 后 542/543/576/606 仍是 `active=f`（根菜单 14 启用 / 23 停用）。
⇒ 该预测不再当「已知事实」使用；但「edu_nav 单独跑一趟」仍是正确做法（成为最后写者 + 规避上面那条硬断言）。

## 1. 结论（TL;DR）

1. **同步**必须加（已加）：`scripts/deploy_myedu.sh` 第 1 步 rsync 列表 + 第 2 步 chmod 列表
   现在都含 `edu_nav`。不加的话文件永远上不去 —— 这是"静默失效"的直接成因。
2. **升级（`-u edu_nav`）本轮不能加**，两条各自独立的实测理由：
   - **会直接炸**：数据文件里有记录用**已卸载模块**（`account_payment` 等 5 个）的规范 xmlid 做键，
     Odoo 的 `tools/convert.py:_test_xml_id` 对跨模块 xmlid 引用未安装模块是**硬断言**
     ⇒ ParseError ⇒ 升级容器 `exit 255`。加进 `-u` 列表 = **每次部署都红**（不是变慢，是直接失败）。
   - **即便能装也赢不了**：加载顺序由 `ModuleGraph` 的 `(phase, depth, name)` 决定，
     **不由 `-u` 列表顺序决定**；`edu_nav` 只依赖 `base`（depth=1），实测**第 2 个**就被加载，
     而 `edu_portal` 深得多、排在后面 ⇒ edu_portal 自己 XML 里的 `<menuitem>` 重放照样是**最后写者**
     （F1：四棵根菜单会被重新点亮）。
3. **生产现在的菜单收口是"半复原"状态**（实测）：合并根 `543 日常管理`、`576 在线课程`
   在生产上是 `active=true`（应停用），`542 邀请码`、`606 老账号补挂身份` 是 `false`。
   即：**F1 不是理论风险，已经在生产上发生过**，而 edu_nav 因为不在部署链里，谁也没把它盖回来。
4. **正确的"让它可升级"路径**（前置条件，见 §5）：重新生成数据文件（不再引用已卸载模块）→
   把它作为**独立的一次性容器、排在主升级之后**跑。

## 2. 实测证据（原始读数）

### 2.1 「改动上不了生产」的直接证据：同一文件两边 md5 不同

```bash
# 本地（工作区）
md5 -q custom_addons/edu_nav/data/menu_consolidation_data.xml
# 生产
ssh prod-host 'cd /opt/edu-app && md5sum custom_addons/edu_nav/data/menu_consolidation_data.xml'
```

| 文件 | 本地工作区 | 生产（部署前） | 判读 |
|---|---|---|---|
| `edu_nav/data/menu_consolidation_data.xml` | `994a14c84efc89f3d525de31a2989952` | `5c33d200b34d8e84d053c2860c81e800` | **不同 ⇒ 生产上的是旧文件** |
| `edu_nav/data/website_menu_data.xml` | `574dd8c53e10a60b8e588eca4959984a` | **不存在** | 新文件从未上过生产 |
| `edu_nav/models/menu_consolidation.py` | `bf738a28569cf160db9d0abc6628d633` | 同左 | 这一份曾被手工 rsync 过 |
| `edu_portal/security/security.xml` | `0bb3dd782e2f51dfb7bb6ce8ee0818aa` | 同左 | 对照：在列表里的模块两边一致 |

### 2.2 生产菜单"半复原"读数

```bash
ssh prod-host 'docker exec -i edu19-prod-db-1 psql -U odoo -d edu19 -tAc \
  "select id, (name->>'"'"'en_US'"'"') as nm, active from ir_ui_menu where id in (542,543,576,606,597) order by id"'
```

```
542|邀请码|f
543|日常管理|t      ← 应停用（计划里并入 593 灵命生活）
576|在线课程|t      ← 应停用（计划里并入 341 时间表）
606|老账号补挂身份|f
（597 行政评估已随 edu_eval 删除，行不存在）
```

### 2.3 `-u edu_portal,edu_nav` 在本地的实测崩溃

命令（本仓库自带的对照工具，`--batch` 单次容器）：

```bash
python3 tests/audit/verify_upgrade_persistence.py --modules edu_portal,edu_nav --restore
```

原始输出（节选）：

```
[run] bash .../scripts/safe_upgrade.sh -u edu_portal,edu_nav
[exit] 255  traceback=True
  -> BATCH edu_portal,edu_nav   UNKNOWN  （升级未真正发生 ⇒ 拒判，不判 PASS 也不判 REPLAY）
```

日志里的失败点（`tests/audit/out/upgrade_edu_portal_edu_nav.log`）：

```
  File "/usr/lib/python3/dist-packages/odoo/tools/convert.py", line 249, in _test_xml_id
    assert modcnt == 1, """The ID "%s" refers to an uninstalled module""" % (xml_id,)
AssertionError: The ID "account_payment.payment_provider_menu" refers to an uninstalled module
odoo.tools.convert.ParseError: while parsing /mnt/custom-addons/edu_nav/data/menu_consolidation_data.xml:1817
<record id="account_payment.payment_provider_menu" model="ir.ui.menu" forcecreate="0">
```

机制要点（读 `convert.py` 源码确认）：`_test_xml_id` 在**写记录之前**执行，判据是
`ir.module.module.search_count([('name','=',模块),('state','=','installed')]) == 1`；
**`forcecreate="0"` 拦不住它**（断言早于 forcecreate 分支）。

### 2.4 哪些模块是"已卸载但被引用"

数据文件共 353 条记录、引用 **45 个模块**；以下 5 个在**本地与生产都是 `uninstalled`**：

```bash
# 逐库核对（本地用 docker compose exec db psql，生产用 edu19-prod-db-1）
select name||'='||state from ir_module_module
 where name in ('account_payment','hr_skills_slides','website_livechat','website_slides','website_slides_forum');
```

```
account_payment=uninstalled
hr_skills_slides=uninstalled
website_livechat=uninstalled
website_slides=uninstalled
website_slides_forum=uninstalled
```

生产上 `ir_ui_menu` id=242（`account_payment.payment_provider_menu`）**不存在**，
所以就算绕过断言，那条记录也无处可写 —— 它属于"计划里还留着、盘上已经没了"的陈旧引用。

### 2.5 加载顺序实测（为什么"放进同一个 `-u` 列表"解决不了 F1）

同一次 `-u edu_portal,edu_nav` 的日志：

```
odoo.modules.loading: loading 115 modules...
odoo.modules.loading: Loading module edu_nav (2/115)
```

`edu_nav` **第 2 个**被加载（紧跟 base），`edu_portal` 在后面 —— 于是 F1 的"谁最后跑谁赢"
结论是：**edu_portal 赢**。源码依据：`odoo/modules/module_graph.py` 顶部「THE LOADING ORDER」
一节 + `ModuleNode.phase/depth`：同一 phase 内按 `(depth, order_name)` 排序，
而 `-u` 列表的顺序**不参与**这个排序（STEP 3 从库里按 state 取模块再 `graph.extend`）。

## 3. 对既有部署的影响（回答"会不会变慢/变危险"）

| 项 | 影响 |
|---|---|
| 部署时长 | **不变**（只多了 rsync 一个模块目录，9 个文件 ~150KB） |
| 升级阶段 | **不变**（`edu_nav` 不进 `-u` 列表 ⇒ 升级容器行为一字未变） |
| 危险度 | **不增**。同步本身不装载任何东西：模块的 `data` 只在 `-u`/`-i` 时被读取。 |
| 与 F1 的关系 | 本轮**不改善也不恶化**：F1 的修复（把 edu_nav 值变成"最后写者"）依赖 §5 的前置条件。 |

## 4. 未跟踪文件 `data/website_menu_data.xml`（顺手说明）

`edu_nav/data/website_menu_data.xml`（2026-09-17 生成，未被 git 跟踪、也**不在 manifest 的
data 列表里**）会随本次同步上生产 —— 它**惰性**（Odoo 根本不会读它），但它属于未完成工作
（导航例外 F7/t15 的备选方案），上游归属见 `docs/audit/t15-jobs-entry-design.md`。

⚠ 同一批未提交工作里还有一处**静态读出来的缺陷**（未执行，仅代码阅读）：
`scripts/gen_menu_data.py` 新增的 `website_menu_exceptions` 块会对 **website.menu 的 id**
调用 `want(mid, 'url'|'name'|'sequence', ...)`，但生成器的 `state` 只采集 `ir.ui.menu`，
于是：`state_of(206)` 为空 ⇒ 字段判为"不同" ⇒ 会多发射一条
`<record id="edu_nav.menu_206" model="ir.ui.menu" forcecreate="0">`（带着 ir.ui.menu 上
**不存在的字段** `url`/`name`）。它不会炸（xmlid 不存在 + `forcecreate="0"` ⇒ 装载器跳过），
但会：① 把"期望条数"从 353 抬到 **354**；② **F7 例外实际不生效**（改指不会发生）。
修法方向：把 `website_menu_exceptions` 的采集与发射走 `website.menu` 自己的 xmlid /
单独一份数据文件，或干脆先撤掉该块。这一处属于该 WIP 的所有者，本文只留证据。

## 5. 让它"上了就生效"的前置条件（按顺序）

1. **修生成器 + 重生成数据文件**：让 `scripts/gen_menu_data.py` 跳过
   （a）当前库里不存在的菜单 id、（b）规范 xmlid 属于**未安装模块**的记录；
   然后 `python3 scripts/gen_menu_data.py --state=baseline` 重生成
   （⚠ 必须带 `--state=baseline`：默认模式只写"与库内现值不同"的字段，收口值早已落库 ⇒
   默认跑会算出 ~0 条并**掏空**数据文件）。
   ⇒ 这一步也是"常量 357 → 353"收口的**同一件事**（生成器同时写数据文件、库里参数、模块常量）。
2. **把 edu_nav 做成"最后写者"**：在部署链里作为**独立的一次性容器**、排在主升级**之后**跑
   （`docker compose run --rm … -u edu_nav`），而不是塞进主 `-u` 列表（§2.5）。
   代价：+1 次一次性容器（约 30–60s，web 不停机）。
3. **常量与参数同时改**：见 `custom_addons/edu_nav/models/menu_consolidation.py` 的注释；
   生产库的 `edu_nav.consolidated_count` 必须与新常量一致，否则部署日志里守卫会报漂移 ERROR。
4. 做完 1–3 之后再跑一次 `tests/audit/verify_upgrade_persistence.py`（口径 B 应稳定 14/12/9…）
   与 `docs/audit/consolidation-verification.md` 的复验命令。

## 6. 办结记录：第 3 条（生产参数仍是 357）已于 2026-10-08 修复

**症状**：每次部署的升级日志里都有 2 条 ERROR ——
`[edu_nav] 声明式数据漂移：ir.config_parameter 声明 357 条，模块常量期望 330 条`。
部署脚本按设计**不拿 ERROR 行当失败判据**（注册表进没进活体进程由第 6 步门禁判），
所以它一直被"如实打印、无人处置"。

**根因（正是第 3 条预言的形态）**：生成器一次写三处（数据文件 / 库里参数 / 模块常量），
但**只有两处会随部署走** —— 数据文件与 `.py` 由 rsync 上生产，
`ir.config_parameter edu_nav.consolidated_count` 只写在**跑生成器那个库**里。
数据文件经 `682d3a1`（357）→ `d0ef5a2`（353，删 edu_eval）→ `86caa92`（330，过滤未安装模块）
三次重生成，生产参数却一直停在最早那次的 357。

**实测读数（2026-10-08，生产 187）**：

| 项 | 读数 | 命令 |
|---|---|---|
| 生产 data 文件 `<record>` 条数 | **330** | `grep -c "<record " /opt/edu-app/custom_addons/edu_nav/data/menu_consolidation_data.xml` |
| 生产 data 文件 md5 vs 本地 | **相同**（`0d50b861ae581c7702a9cccea058ec1f`） | `md5sum` / `md5 -q` |
| 生产模块常量 | **330** | `grep -n "^MENU_CONSOLIDATED_COUNT" …/models/menu_consolidation.py` |
| 生产参数（改前 → 改后） | **357 → 330** | `select value from ir_config_parameter where key='edu_nav.consolidated_count'` |

**动作**：把生产参数写成 **330**（= 生产 data 文件里 `<record>` 的实测条数，也与模块常量一致；
不是"手算一个数"—— 它可当场用 `grep -c` 复核），然后**单跑一趟** `-u edu_nav` 复现守卫。

**反向对照（改前 / 改后）**：改前每次装载必报 2 条漂移 ERROR；改后同一命令的读数 ——

```
[edu_nav] 菜单收口守卫：声明改写 330 条（参数表记为 330）；根菜单 39 条（停用 23）；全库 526 条（停用 181）
grep -c "声明式数据漂移" /tmp/nav_verify.log  ⇒ 0
grep -n "ERROR\|CRITICAL\|Traceback" /tmp/nav_verify.log  ⇒ 无
```

**留下的结构性缺口（未修，本文如实登记）**：这条不变量仍然只靠人记得 ——
生成器写库、rsync 传文件，两者之间**没有自动对账**。下次重生成数据文件后，
生产参数会再次滞后并重新报漂移 ERROR。真要根治得让部署链在 rsync 之后
用模块常量回写该参数（或让守卫改读数据文件的实测条数而不是库里参数）。
