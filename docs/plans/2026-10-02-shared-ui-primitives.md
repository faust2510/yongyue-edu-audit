# 共享 UI 原件下沉（门户壳 / 窄屏卡片样式）

> **状态**：`设计中` ｜ **主题**：`共享UI原件下沉` ｜ **取代**：`—` ｜ **核对**：`2026-10-02`
>
> 起因：round 13 与 round 22-23 **两次被同一个根因挡住**，本文只给方案，未实施任何代码。

## 1. 问题：两个「人人要用」的原件，住在依赖图的**最上层**

现依赖图（`__manifest__.py` 的 depends，实测）：

```
edu_brand   → website, theme_web_openeducat, auth_totp_portal      （无 edu_* 依赖，在最底层）
edu_schedule→ openeducat_timetable, website
edu_quiz    → openeducat_core, openeducat_exam, mail
edu_public  → website, openeducat_core, openeducat_exam, openeducat_library
edu_portal  → portal, website, openeducat_*, edu_apply, **edu_brand**, **edu_schedule**   ← 最上层
edu_life    → edu_portal   ｜ edu_assess → edu_portal ｜ edu_tg_bind → edu_portal
```

而两个**所有门户页都该用**的原件却住在 `edu_portal`（依赖图的顶层）：

| 原件 | 现位置 | 用途 |
|---|---|---|
| `edu_page`（门户外壳） | `edu_portal/views/edu_portal_templates.xml:8` | 本仓成文标准：`code-map.md:93/267`「**所有门户页**的 t-call 外壳」 |
| `edu_narrow_table_cards`（窄屏卡片表格样式） | `edu_portal/views/roles.xml:554` | 手机端把宽表折成卡片，已用于 10+ 处 |

⇒ **依赖图下层/旁层的模块用不了它们**，只能「绕过」或「将就」。这不是假设，是已经发生的两次阻塞：

### 阻塞一（round 13，仍在）：`edu_schedule` 引用了它声明不到的模板

`edu_schedule/views/templates.xml` 有 **2 处** `t-call="edu_portal.edu_narrow_table_cards"`，
但 `edu_schedule` 的 depends 里**没有 edu_portal**；而 `edu_portal` 依赖 `edu_schedule` ⇒ **加依赖就成环**。

**它现在「能用」是巧合**：QWeb 的 `t-call` 按 xmlid 在**渲染时**解析，只要 edu_portal 装了就找得到，
与 manifest 的声明无关。⇒ manifest 在**说谎**：声明了一个它实际依赖的模块之外的关系。
（若单独安装 edu_schedule 而不装 edu_portal，这 2 处会直接渲染失败。）

### 阻塞二（round 22-23）：4 个页面想换门户壳但换不了

实测量出 **8 个内部页仍在用公开站外壳**（`scripts/find_wrong_shell.py`）。按模块拆开看，能不能修**完全由依赖图决定**：

| 模块 | 页数 | 有 edu_portal 依赖？ | 能否换壳 |
|---|---|---|---|
| `edu_life` | 4 | **有** | ✅ 可以（已派 task-16） |
| `edu_quiz` | 2 | 无 | ⚠ 可加依赖（`edu_portal` 不依赖 quiz，**不成环**） |
| `edu_schedule` | 1 | 无，且**成环** | ❌ **不能** |
| `edu_public` | 1（`/my-courses`） | 无（且公开模块不该依赖门户） | ❌ 需按 `enroll-v2-design.md:59` 的规划重建 |

## 2. 根因

**共享 UI 原件被放在了「聚合模块」里，而不是「基础模块」里。**

`edu_portal` 的角色是**聚合与业务**（它 depends 了 edu_brand/edu_schedule/edu_apply 等），
把「所有页面都要用的外壳」放进去，等于把公共设施盖在了大楼顶层 —— 楼下的人上不去。

## 3. 方案 —— ⚠ 初版「建议 A：下沉到 `edu_brand`」**已证伪**（2026-10-03 完成前置核查）

**证伪依据**：`edu_page` **不是纯展示层**的东西，它直接读 ERP 业务模型与组：

```
request.env.user.has_group('openeducat_core.group_op_back_office_admin')
request.env['op.faculty'] / ['op.parent'] / ['op.student']  的 search_count
```

而 `edu_brand` 的依赖是 `[website, theme_web_openeducat, auth_totp_portal]`，
其中 `theme_web_openeducat` 只依赖 `[website, theme_default]` —— **够不到 `openeducat_core`**。
⇒ 照建议 A 搬，就得让**品牌模块依赖 ERP 核心**，把 `edu_brand` 从「展示层」变成「与业务耦合」，
与它现在装的东西（品牌标 / 登录页 / 去 Odoo 化）不是一个定位。**故不做。**

### 修订方案（建议 B）：新建中间层模块 `edu_shell`

| 项 | 内容 |
|---|---|
| 模块 | `edu_shell` —— 定位一句话：**门户外壳与共享 UI 原件** |
| depends | `website`（渲染外壳）+ `openeducat_core`（外壳要读 `op.student`/`op.parent`/`op.faculty` 与教务组） |
| 装什么 | `edu_page`（门户外壳） |
| **不装什么** | **业务页面、路由、模型一概不装** —— 它只有视图原件 |

### ⛔ 2026-10-03 实测：**“上层留同名薄别名”这条对 `edu_page` 不成立**（已回滚，未留半成品）

`edu_narrow_table_cards` 用别名搬成功了（它是**叶子**模板）。`edu_page` **照做会直接升级失败**，实测：

```
odoo.tools.convert.ParseError: while parsing None:14
解析或验证视图时出错：
上级视图内找不到元素“<xpath expr="//aside[@id='b11-side']//a[@href='/web']">”
View error context: {'name': '门户导航：课程编排入口', 'view': ir.ui.view(3710,),
                     'view.parent': ir.ui.view(2061,), 'xmlid': 'edu_page'}
```

**原因**：`edu_page` **不是叶子**，它被 2 个视图用 `inherit_id` + `xpath` **扩展**（`edu_portal/views/curriculum.xml:217/:237`：
侧栏塞「课程编排」入口、移动端底栏塞第 6 个 Tab）。别名只有 6 行 `t-call`，**没有 `<aside id="b11-side">` 这些被 xpath 定位的元素**
⇒ 父视图一被写成别名，它的子视图立刻 `找不到元素`，整个事务回滚（其余 5 个文件、137 处调用点因此一行都没动）。

⇒ **通用结论（建议记进 code-map §6）**：
> **“定义下沉 + 上层留别名”只适用于叶子模板。** 凡被 `inherit_id`/`xpath` 扩展过的模板，
> 别名会把它变成一个**没有扩展点的空壳**，子视图必然报错。这类模板要么**全局改名调用点**，要么**别搬**。

**若仍要搬 `edu_page`，修正后的工作量（已实测）**：

· 调用点 **137 处 / 29 个文件**（`edu_portal` 主体 100 处、`edu_assess` 15、`edu_quiz` 8、`edu_life` 4 …）；
· **另外必须把 2 条 xpath 注入一起搬到外壳所在的模块**（否则它们依旧盯不到元素）；
· 且要按下面的部署耦合把两份模块清单一起改。

**本轮处置**：**全部回滚** —— `edu_portal_templates.xml` 还原到逐字节一致、删掉新文件、还原 manifest 与两处 `inherit_id`，
重跑 `edu_brand` + `edu_portal` 升级（EXIT=0），库里 `edu_page` 只剩原记录（2061 / 23932 字节），
`/my/home`、`/my/study` 复验门户壳正常（`search=True, tabs=5`）。
⇒ **宁可不做，也不留一个“升级失败 + 库半改”的状态。**

### ⚠ 另一个执行前必须知道的：**新增模块在本仓有部署耦合，漏一步 = 门户全站白屏**

`scripts/deploy_myedu.sh` **不是**「把 custom_addons 整个同步过去」，而是**两份写死的模块清单**：

```bash
# :156  默认要升级哪些模块
MODULES=${1:-edu_life,edu_schedule,edu_apply,edu_portal,edu_brand,edu_tg_bind,edu_assess}
# :185  rsync 只同步这些目录
edu_life edu_schedule edu_apply edu_portal edu_brand edu_quiz edu_public edu_zh \
  edu_tg_bind edu_assess edu_nav "$REMOTE:$DIR/custom_addons/"
```

⇒ 新建 `edu_shell` 后，**必须同时改这两处**；任一处漏掉，生产上 `edu_shell` 这个模块就不存在，
  而 `edu_portal` 的 `edu_page` 是一条指向 `edu_shell.edu_page` 的别名 ⇒
  **所有门户页解析模板失败**（不是「样式不对」，是整页打不开）。

**这条改变了方案的风险画像，故重新比较两条路**：

| | 建议 B：新建 `edu_shell` | 建议 A′：`edu_page` 也放进 `edu_brand`（并给它加 `openeducat_core` 依赖） |
|---|---|---|
| 分层 | **干净** —— 单一职责，「门户外壳」独立成层 | 略浑浊 —— 品牌模块依赖 ERP 核心 |
| 部署 | **要改两份清单**；漏改 = 门户全站白屏 | **零新增** —— `edu_brand` 早就在两份清单里 |
| 回滚 | 删模块 + 改回清单 | `git revert` 一次提交 |
| `edu_schedule` 解锁 | ✅ | ✅（`edu_brand` 是它的下游，不成环） |

⇒ **改为推荐 A′**：把「分层更纯」换掉，换「部署面不动」。本仓的部署清单是写死的、
   而 `edu_brand` 早已在清单里 —— 在「多一个模块要维护 + 漏改即全站白屏」面前，
   这一点分层纯度不值。**（这是本轮实测部署脚本后改的判断，此前 §3 的 A/B 比较没把部署面算进去。）**

**不成环已逐条核实**：
· `openeducat_core` 的 manifest 里**没有任何 `edu_*` 依赖**（grep 0 命中）⇒ 谁依赖它都不会回环；
· `edu_schedule` 经 `openeducat_timetable → openeducat_classroom → …` 已经拿到 `openeducat_core`，
  再加一条 `edu_shell` 不引入新的环 ⇒ **`/timetable/bulk` 那 1 页由此解锁**；
· `edu_portal` 留同名薄别名 ⇒ **130+ 调用点一个都不用改**。

### 已经做掉的那一半（2026-10-03 已实施并验证，commit `d2c3798`）

`edu_narrow_table_cards` 是**纯 `<style>`、零模型访问** ⇒ 它**可以**下沉到 `edu_brand`，已实施：
定义搬到 `edu_brand/views/shared_ui.xml`、`edu_portal` 留同名薄别名、
`edu_schedule` 改为直引 `edu_brand.edu_narrow_table_cards` 并**如实**声明依赖；
逐页复跑 `find_squeezed_tables` 验证样式仍送达。

⇒ **两个原件的归属不同，而这条界线本身就是结论**：
**纯样式的归 `edu_brand`（已做），要读模型的归 `edu_shell`（待建）。**

### 旧建议 A 的原文（保留供对照）
2. 在 `edu_portal` 里保留**同名薄别名**：

   ```xml
   <template id="edu_page"><t t-call="edu_brand.edu_page"/></template>
   ```

   ⇒ **130+ 个现有调用点一个都不用改**（`edu_page` 实测 24 个文件、`edu_narrow_table_cards` 12 个文件）；
3. `edu_schedule` / `edu_quiz` 改为**直接引用 `edu_brand.*`** 并在 manifest 里**如实**声明 `edu_brand` 依赖（不成环）。

**为什么不直接全局改名**：调用点 130+ 处、跨 2 个模块，收益只是「少一层别名」，风险与工作量都不划算。

**为什么不新建 `edu_ui` 模块**：`edu_brand` 已经是「所有 edu_* 的公共底层」这一角色，另起一个只会多一个要维护的依赖边。

## 4. 前置核查（**已完成**，2026-10-03 —— 结论直接推翻了建议 A）

| 核查项 | 结论 | 依据 |
|---|---|---|
| `edu_brand` 够得到 `openeducat_core` 吗 | **够不到** | 实读 `edu_brand`=`[website, theme_web_openeducat, auth_totp_portal]`；`theme_web_openeducat`=`[website, theme_default]` |
| `edu_page` 是否自包含 | **是** | 模板块内只 `t-call="website.layout"`，**不引用任何其它 `edu_*` 模板** ⇒ 搬迁不会拖出级联 |
| `openeducat_core` 有无 `edu_*` 反向依赖 | **无** | `grep` 其 manifest，0 命中 ⇒ 新中间层不成环 |
| `edu_schedule` 能否够到中间层 | **能** | 经 `openeducat_timetable → openeducat_classroom → …` 已含 `openeducat_core` |
| `edu_page` 依赖的外部符号 | 清单如下 | `base.group_user`、`openeducat_core.group_op_back_office_admin`、`op.faculty/parent/student`、`request.env.user` |

⇒ 核查的价值正在于此：**若跳过它直接照建议 A 动手，就会把一个品牌模块绑上 ERP 核心**，
而且是在「所有人都觉得这是个低风险搬家」的前提下悄悄发生的。

## 5. 验收（实施时）

1. `find_wrong_shell.py` 全量 → 命中数从 8 降到 **0**（`/my-courses` 除外，按其自身规划处理）；
2. 全部走 `edu_portal.edu_page` 的页面**渲染结果不变**（改前/改后 1440 与 375 截图 + 关键元素读数）；
3. `find_squeezed_tables.py` 全量仍 **0 命中**；
4. 四轴 UI 门禁与无障碍门禁仍全绿；
5. `edu_schedule` 的 manifest 变成**如实声明**（加了它真正需要的依赖）。

## 6. 与既有文档的关系

· 本文是 `code-map.md` §6 第 16 条（跨模块 `t-call` 规则：**先查环再声明依赖**）的**延伸** ——
  那条规则说明「怎么安全地加依赖」，本文回答「**为什么老是加不了**」以及「怎么让它以后加得了」。
· `edu_public` 的 `/my-courses` **不在本方案范围内**：它的问题不是外壳，
  而是「学生内部页长在公开模块里」，应按 `docs/plans/enroll-v2-design.md:59` 重建。