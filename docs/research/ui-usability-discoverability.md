# Odoo 19 后台/门户 UI 可用性与可发现性改善（铁律 0 调研）

> 任务：调研员 study-ui-a11y · 2026-09-28
> 触发：用户原话「**我对于如图的这种 UI 很不满意，总感觉操作起来不好看也不舒服，有没有更好的方案？而且它很多功能被折叠了，导致我不点都不知道有这些功能。这种 UI 很不友好。我希望全部的这类 UI 都改善一下。**」
> （图 = Odoo 19 后台标准列表视图：蓝色顶栏「财务管理 / 账单管理 / 费用分类 / 缴费流水 / 财务总台账」+ 搜索栏 + 表格 + 「新建」按钮）
> 上游依据：`CLAUDE.md` 铁律 0；体例见 [`docs/research/README.md`](README.md)
> **本文件只做调研**：不含设计决策、不改任何代码。每条结论带一手来源；无法核实的进 §9「未验证」。
>
> ⚠ **订正记录（2026-09-28 收尾轮，实测）**：本文件有两处已订正，**原值都保留在正文里并标注**：
> ① §3 的 `optional="hide"` **37** / `optional="show"` **34** 是 **raw grep 行数**（把注释文本里提到的同名串也算进去了），元素级真实值是 **308efbb 之前 34 / 34、之后 33 / 36** —— 见 §3「数字订正」块。
> ② 命令面板键位原文写作 `Ctrl+K`；`hotkey_service.js:73-78` 在 macOS 上把 Cmd 映射为 logical control ⇒ **macOS 上必须按 ⌘K**。本机实测：**⌘K 打开面板 = True；Ctrl+K = False** —— 见 §2.10「键位订正」块。

---

## 0. 取证基准（先看这段，再看任何结论）

| 项 | 值 |
|---|---|
| Odoo 上游 | `odoo/odoo` 分支 `19.0`，`refs/heads/19.0` = `4e7b84db9455086754164db5e404987c34d48eb7`（2026-09-28 取，命令：`git ls-remote https://github.com/odoo/odoo refs/heads/19.0`） |
| 引文格式 | `https://github.com/odoo/odoo/blob/19.0/<path>#L<n>`（纯文本等价：`https://raw.githubusercontent.com/odoo/odoo/19.0/<path>`） |
| 本机运行态（实测） | `docker exec edu19-clone-web-1 odoo --version` → `Odoo Server 19.0-20260817`；容器源码根 = `/usr/lib/python3/dist-packages/odoo`（上游仓库的 `odoo/addons/` 与 `addons/` 会摊平到这里） |
| 本机数据库 | `docker exec edu19-clone-db-1 psql -U odoo -d edu19`，库名 `edu19` |
| ⚠ 行号会漂移 | 依据 `docs/research/README.md` 收录规范第 4 条：**实施时以本机实测为准**（本机镜像比上游 HEAD 早约 1 个月） |
| ⚠ 上游路径差异 | `base` 应用在上游是 `odoo/addons/base/...`（**不是** `addons/base/...`）；`web`、`web_tour` 是 `addons/web*` |

**证据强度图例**：✅ 一手源码（带行号） · 🌐 一手官方文档 · 🧪 本机实测（命令 + 输出） · ⚠ 未验证（**不得当结论用**）

⚠ **本仓可观察到的工具故障**（下一个人不必重试）：
- `web_search` 工具**全程不可用**：返回 `HTTP 400 BAD_REQUEST — You have insufficient credits`。本报告所有外部证据均由 `curl` / `web_fetch` / `raw.githubusercontent.com` / `git ls-remote` 直接取得。
- `api.github.com` 未认证额度 60/小时**已耗尽**（`core.remaining` 归零）。替代方案：`git ls-remote`（查分支）+ `raw.githubusercontent.com`（取文件，不限速）+ `git clone --filter=blob:none`（列目录）。

---

## 1. 一句话结论（TL;DR）

1. **两个痛点是两类问题，不能用同一把锤子砸**：
   - (a)「不好看、不舒服」= 大部分是**风格偏好**（审美选择，§7 单列）；
   - (b)「功能被折叠、不点不知道」= **可用性缺陷**，可客观裁定，而且 **Odoo 19 原生就有 6 类现成开关**（§2），第一杀手是 `optional="hide"`。
2. **本仓已经在犯这个错，且有铁证**：`custom_addons/edu_portal/views/invite_code_views.xml:58-65` 里写着一次和用户今天说法**几乎逐字相同**的现场抱怨（「我怎么不可以调整这个邀请码的可使用次数」→ 真因是那一列被 `optional="hide"` 了）。全仓 `optional="hide"` **33 处** vs `optional="show"` **36 处**（🧪 元素级计数，2026-09-28 当前树；**原写的 37 / 34 是 raw grep 误值 —— 已在 §3 订正，原数字保留在彼处**）。
3. **Odoo 19 已内置「任何菜单都能被搜到」**：命令面板 = `command_service.js:67`（注册的是逻辑 `control+k`；**macOS 上实际键位是 ⌘K —— 见 §2.10 的实测订正**），面板内 `/` 命名空间用模糊搜索遍历**全部应用与菜单**（`menu_providers.js:29-79`）；`Alt` 显示所有快捷键徽标（`hotkey_service.js:111,167`）。**我们 0 处提示用户这件事**。
4. **Odoo 19 已内置「新手引导引擎」，而且我们库里就装着**：`web_tour` 模块（🧪 `state = installed`），模型 `web_tour.tour` 带 `user_consumed_ids`（**每人只自动播一次**是原生语义）、`res.users.tour_enabled`（界面标签 **Onboarding**）、后台可视化增删 tour、JS 录制器。🧪 库里已有 4 条 tour，**没有一条是教务的**；12 个用户里只有 2 个（管理员）开着 Onboarding。
   → **「做首次使用提示」不需要自研引擎，只需要「写内容 + 开开关」。**
5. **搜索面板 `searchpanel` 是「把筛选条件永远摊在左边」的原生手段**（左侧常驻分类树/多选筛选，带计数），**本仓 0 处使用**；**视图切换**（列表 ↔ 看板 ↔ 日历 ↔ 活动）是「同一份数据换个角度」的原生手段，本仓 56 个动作里 **`view_mode` 有 39 个只是 `list,form`**，kanban 视图 **0 个**、activity 视图 **0 个**。
6. **能装的现成货存在，但都在 OCA 且多数是 AGPL-3**（§5）：`web_responsive`（**LGPL-3**，全屏应用菜单 + 应用菜单内搜索 + 列表粘性表头 + 快捷键）是本轮最值得评估的一个；`web_group_expand`（AGPL-3）、`web_remember_tree_column_width`（LGPL-3）次之。**没有任何现成模块能替我们决定「哪一列该默认可见」——那是业务判断，只能我们自己做。**
7. **同类系统的成熟解**（§4）：钉钉 AI 表格把「显示/隐藏字段」做成一等公民（字段管理面板）；校管家把后台能力编成「新手入门手册」四步 +「探索更多高阶功能」；Moodle 用 `admin/search.php` 搜遍上千个设置 + `tool_usertours` 导览 + 表格每列表头的显隐开关；Canvas 用「隐藏课导航页签 + 待办推到面前 + 空状态组件」。
8. **观感侧有一个明确的负结论**：Odoo 19 `web` 模块**没有任何 density（密度）开关**（`grep -rn "density"` 命中 **0**）。列表行高/内边距只能靠 SCSS 覆盖 `--ListRenderer-*` 变量（`list_renderer.scss:3-4,7`）——这条属于「要么接受默认，要么自研样式」。

---

## 2. ① Odoo 19 后台列表/表单 UI 有哪些现成的改善手段（原生优先）

> 本节的属性名全部取自 **RNG 视图模式定义**（服务端强校验的权威清单），并配上前端消费点。**写视图前先查 RNG，比猜文档可靠。**

### 2.1 列表视图 `<list>` 的全部 arch 属性（权威清单）

来源：[odoo/addons/base/rng/list_view.rng](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/rng/list_view.rng)（本机：`/usr/lib/python3/dist-packages/odoo/addons/base/rng/list_view.rng`）

| 属性 | RNG 行 | 作用 | 与本痛点的关系 |
|---|---|---|---|
| `create` / `edit` / `delete` | :27-29 | 关掉新建/编辑/删除 | 只读台账用 |
| `multi_edit` | :30 | **多行批量编辑**（勾选多行改同一字段） | 手感/效率 |
| `export_xlsx` | :31 | 关掉 xlsx 导出 | — |
| `import` / `duplicate` | :36 / :35 | 关掉导入 / 复制 | — |
| `group_create` / `group_edit` / `group_delete` | :32-34 | 分组时的增删改组 | 分组体验 |
| `default_order` | :41 | 默认排序 | 让「最该先看到的」排在前面 |
| `default_group_by` | :42 | **默认按某字段分组** | **把「分层结构」直接摊开** |
| `decoration-bf/it/danger/info/muted/primary/success/warning` | :43-50 | 整行着色条件 | 观感 + 状态一眼可读（本仓已用 109 处） |
| `sample` | :51 | **空库时显示示例数据** | 空状态不再是一片白 |
| `action` + `type` | :52-53 | 点整行触发自定义动作（前端 `list_arch_parser.js:229-231`） | 行级快捷操作 |
| `open_form_view` | :54 | 可编辑列表上显示「打开表单」按钮 | 可发现性 |
| `limit` / `count_limit` / `groups_limit` | :56 / :61 / :66 | 每页行数 / 计数上限 / 分组上限 | 观感 |
| `editable`（取值 `top` 或 `bottom`） | :71-76 | **行内编辑**（不用点进表单就能改） | **手感最大的一个开关** |
| `expand` | :78 | **分组是否默认展开**（前端 `list_controller.js:213`：`openGroupsByDefault: rawExpand ? evaluateExpr(rawExpand, ctx) : false`） | **直接对应「折叠了看不见」** |
| `js_class` | :40 | 换成自定义列表组件 | 自研入口 |

子节点（RNG :79-97）：`header`（表头按钮 :81-85）、`control`（列表自定义 create/button，RNG :406-416；前端 `list_arch_parser.js:166-187`）、`field`、`widget`（:418-424）、`separator`、**嵌套 `list`**（:90）、**`groupby`**（:91）、`button`、`filter`、`html`、`newline`。

其中 **`<groupby name="字段">` 是一条被低估的能力**（RNG :10-21）：分组之后，**每个分组内部可以换一套列**，并且它自己也有 `expand`（:13）。前端：`list_arch_parser.js:149-158` → `list_controller.js:202-207`。

### 2.2 字段级属性（普通列能用什么）

来源：[odoo/addons/base/rng/common.rng:191-292](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/rng/common.rng#L191-L292)（`<rng:define name="field">`）

关键几个：`optional`（**:254**）、`nolabel`（:228）、`width`（:201）、`sum`（:215）、`avg`（:217）、`column_invisible`（:211）、`invisible`（:212）、`groups`（**:43-47** `access_rights`）、`widget`（:232）、`decoration-*`（:256-263）、`force_save`（:265-272）、`options`（:276）、`placeholder`（:277）。

### 2.3 ⭐ `optional` ——「功能被折叠」的第一杀手（完整机制）

**默认可见性只有一个开关：`optional`。**

| 取值 | 效果 |
|---|---|
| 不写 | **永远可见**，且**不出现在列设置菜单里**（用户无法把它藏起来） |
| `optional="show"` | 默认可见，**但用户可以关掉**；出现在列设置菜单 |
| `optional="hide"` | **默认不可见**，用户必须「知道去那里点开」才能看见；出现在列设置菜单 |

证据链（全部一手）：

| 环节 | 位置 | 内容 |
|---|---|---|
| 解析 | [`list_arch_parser.js:119`](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/views/list/list_arch_parser.js#L119) | `optional: node.getAttribute("optional") \|\| false` |
| **默认值判定** | [`list_renderer.js:1171-1189`](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/views/list/list_renderer.js#L1171-L1189) | `computeOptionalActiveFields()`：若 localStorage 无记录 → `optionalActiveFields[col.name] = col.optional === "show"`（**:1185-1188**）；有记录则用记录（:1178-1184） |
| 生效过滤 | 同文件 `:326-334` `getActiveColumns()` | `if (col.optional && !this.optionalActiveFields[col.name]) return false;` |
| 持久化 | 同文件 `:141` / `:1972-1979` | localStorage key = `optional_fields,<view key>`；`saveOptionalActiveFields()` |
| 切换 UI | [`list_renderer.xml:49-85`](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/views/list/list_renderer.xml#L49-L85) | 表头右上角 `oi-settings-adjust` 图标下拉（`o_optional_columns_dropdown`）；`:74-82` 另有 debug 用「View Button」 |
| 切换逻辑 | `list_renderer.js:2086-2092`（单列）/ `:2097-2105`（整组） | `toggleOptionalField(name)` → 写 localStorage → 重渲染 |
| 可分组 | `list_renderer.js:630-657` | `optionalFieldGroups`：**Properties 字段按组**折叠成一组勾选项 |

⚠ **`column_invisible` 与 `optional` 是两回事**：`column_invisible` 是按表达式的**硬隐藏**（`getActiveColumns()` :335-341），**不进列设置菜单**，用户永远看不到 ⇒ 用它藏东西 = 永久不可发现。

### 2.4 搜索视图 `<search>` 与 **搜索面板 `<searchpanel>`**

来源：[odoo/addons/base/rng/search_view.rng](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/rng/search_view.rng) + [addons/web/static/src/search/search_arch_parser.js](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/search/search_arch_parser.js)

`<search>` 顶层允许：`field` / `group` / `separator` / `filter` / `newline` / **`searchpanel`**（RNG :21-36）。

**`<searchpanel>`** = 视图**左侧常驻**的筛选栏（不是下拉，不需要点开才知道）——这是「把筛选能力摊开」的最强原生手段：

| 元素/属性 | 位置 | 含义 |
|---|---|---|
| `view_types` | RNG :13；解析 `search_arch_parser.js:333-335` | 在哪些视图显示（默认 `kanban,list`，**:10** `DEFAULT_VIEWS_WITH_SEARCH_PANEL`） |
| `class` | :331-332 | 自定义样式类 |
| 子 `<field select="multi">` | `search_arch_parser.js:352` | → `type: "filter"`（多选复选框，配 `domain`/`groupby`） |
| 子 `<field select="one">`（默认） | 同上 | → `type: "category"`（**左侧分类树**，默认图标 `fa-folder`，常驻一个「全部」项，:365-377） |
| `string` / `icon` / `color` | :355 / :359 / :354 | 显示名 / 图标（filter 默认 `fa-filter`，:381）/ 颜色 |
| `enable_counters` | :356 | **每个分类后面显示条数** |
| `expand` | :357 | 分类树是否展开 |
| `limit` | :361（默认 **200**，:9） | 每个 section 最多显示多少个值 |
| `hierarchize`（默认 1）/ `depth` | :368-369 | 是否按父子层级缩进 / 从哪一级开始取 |
| `domain` / `groupby` | :379-380 | 多选筛选生效的 domain / 按某字段分组 |

⚠ **一个真实的坑（有源码告警）**：`enable_counters` 的分类与「带 `domain` 的 filter」**互斥**——同时出现时框架会**把全部 category 计数器静默关掉**并 `console.warn`（`search_arch_parser.js:387-406`，原文注释：*"Category counters are automatically disabled if a filter domain is found to avoid inconsistencies"*）。设计时二选一。

**`<filter>`** 属性（RNG `common.rng:360-395`）：`name`（必需 :364）、`string`、`domain`、`context`、`date` 与 `start_year/end_year/start_month/end_month/default_period`、`icon`、`invisible`、`help`、`separator`。
- `context` 里写 `'group_by': '字段'` 会**自动升级成分组筛选项**（`search_arch_parser.js:205-222`）。
- `date` 过滤器会自动生成「本月/上月/本季…」的时间选项（:227-250），`default_period` 指定默认选中项。

**搜索框内的字段**（`search_arch_parser.js:112-203`）：支持 `filter_domain`（自定义匹配表达式）、`operator`、`context`、`string`。

**`search_default_*`（预设）**：动作的 `context` 里写 `search_default_<字段名>` 或 `search_default_<filter name>` 即可让某筛选**一进来就是开的**（`search_arch_parser.js:137-191` 字段默认值、`:264-283` filter 默认值，groupBy 默认 rank 100）。→ **这是「用户不用自己找筛选」的最便宜做法。**

### 2.5 动作层 `ir.actions.act_window`（决定「打开后长什么样」）

来源：[odoo/addons/base/models/ir_actions.py](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/ir_actions.py)

| 字段 | 行 | 说明 |
|---|---|---|
| `help` | [**:71-72**](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/ir_actions.py#L71-L72) | *"Optional help text for the users with a description of the target view, such as its usage and purpose."*；`read()` 在 :341-355 把它交给模型的 `get_empty_list_help()` |
| `view_mode` | :318-319 | 逗号分隔的可用视图列表，默认 `list,form`。**写多个 → 控制面板出现视图切换按钮组** |
| `mobile_view_mode` | :320 | 小屏优先视图，默认 `kanban` |
| `limit` | :328 | 列表默认每页 80 |
| `search_view_id` | :331 | 指定专用搜索视图 |
| `target` | :317 | `current` / `new` / `fullscreen` / `main` |
| `context` | :312-313 | 放 `search_default_*` |

**空状态（empty state）默认长什么样**（[addons/web/static/src/views/no_content_helpers.xml:5-17](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/views/no_content_helpers.xml#L5-L17)）：标题默认 *"No data to display"*，正文默认 *"Try to add some records, or make sure that there is no active filter in the search bar."*（**英文**）。
→ **不写 `help`，用户看到的就是这句英文兜底**；写了才是业务语言。图标三种：`o_view_nocontent_smiling_face` / `o_view_nocontent_neutral_face` / `o_view_nocontent_empty_folder`（`views/view.scss:25,32,39`）。

**`sample`**（RNG :51 → [addons/web/static/src/views/view.js:356,400-401](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/views/view.js#L400-L401)）：`sample="1"` 时空库渲染**示例数据行**，用户能先看见「这张表长什么样、有哪些列」。

### 2.6 多视图切换（同一份数据，换个角度）

✅ [addons/web/static/src/search/control_panel/control_panel.xml:93-122](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/search/control_panel/control_panel.xml#L93-L122)：当 `viewSwitcherEntries.length > 1` 时渲染按钮组 `o_cp_switch_buttons`（桌面，:110-121）；小屏收成 Dropdown（:94-109）。
✅ 切换命令同时注册进命令面板：`control_panel.js:169-176` `useCommand(_t("Show %s view"), () => this.switchView(view.type))`。
⇒ **只要 `view_mode` 里写第二个视图，用户就多了一条「发现同一数据另一面」的入口。**

### 2.7 菜单与可见性：`groups`

✅ [common.rng:43-47](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/rng/common.rng#L43-L47)（`access_rights`：可选属性 `groups`）被 `field` / `button` / `group` / `filter` / `list` 等元素引用 ⇒ **视图层的字段/按钮/筛选项都可以按组隐藏**。
🧪 本仓已用 47 处 `groups="..."`。
⚠ 与 §2.3 同理：**按组隐藏 = 该类用户永久不可发现**，这是「该藏」与「该摊开」的分界线（见 §7）。

### 2.8 表单侧的「把隐藏功能摊开」手段

| 手段 | 证据 |
|---|---|
| `<header>` 按钮 + `<field widget="statusbar">` | 本仓 `custom_addons/edu_portal/views/fees.xml:90-101` 已用；状态流转一眼可见 |
| `oe_button_box` / `oe_stat_button`（「智能按钮」） | ✅ [addons/web/static/src/views/form/form_compiler.js:131](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/views/form/form_compiler.js#L131)（`oe_button_box`）、[:158](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/views/form/form_compiler.js#L158)（`oe_stat_button`） |
| `<notebook><page>` | 本仓 `fees.xml:132-144` 已用（把明细收进页签） |

### 2.9 ⭐ Odoo 19 新能力：`ir.embedded.actions`（把「相关动作」嵌进列表页）

✅ 模型：[odoo/addons/base/models/ir_embedded_actions.py:8-29](https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/ir_embedded_actions.py#L8-L29)

| 字段 | 行 | 含义 |
|---|---|---|
| `parent_action_id` | :15 | 挂在哪个动作上（必填） |
| `action_id` / `python_method` | :19-20 | 二选一：要跳的动作，或返回动作的方法 |
| `filter_ids` | :25 | 该嵌入动作的**默认筛选** |
| `default_view_mode` | :24 | 打开时用哪个视图 |
| `domain` / `context` | :27-28 | 作用于父记录 |
| `groups_ids` | :29 | 谁能看到这个嵌入动作 |
| `is_visible` | :26 | 按 domain 计算是否显示 |
| `user_id` | :22 | 用户私有（空 = 共享） |

前端渲染：✅ `control_panel.xml:129-133` `web.embeddedActionsDropdown`（一个滑块图标的下拉）。
⇒ **用途：把「这个列表相关的其他入口」直接摊在同一个页面上，而不是埋在菜单树里。** 本仓目前只有 1 处用到。

### 2.10 键盘与命令面板（「不点也能到」）

| 能力 | 证据 |
|---|---|
| **命令面板**（注册的是逻辑 `control+k` ⇒ **macOS = ⌘K / Windows = Ctrl+K**，见下方订正） | ✅ [addons/web/static/src/core/commands/command_service.js:67](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/core/commands/command_service.js#L67)：`hotkeyService.add("control+k", openMainPalette, ...)` |
| 面板内 **`/` 搜索全部应用与菜单** | ✅ [addons/web/static/src/webclient/menus/menu_providers.js:29-79](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/webclient/menus/menu_providers.js#L29-L79)：`computeAppsAndMenuItems(menuService.getMenuAsTree("root"))` + `fuzzyLookup`（:37-40），分 `apps`（:53-75）与 `menu_items`（:41-50）两类；空态文案 `"No menu found"`（:24） |
| 任意带 `data-hotkey` 的元素自动进面板 | ✅ [addons/web/static/src/core/commands/default_providers.js:69-80](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/core/commands/default_providers.js#L69-L80)（`[data-hotkey]:not(:disabled)`） |
| **`Alt` 显示快捷键徽标** | ✅ [addons/web/static/src/core/hotkeys/hotkey_service.js:111](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/core/hotkeys/hotkey_service.js#L111) `overlayModifier: "alt"`；:167 按下即显示 |

> ⚠ **键位订正（2026-09-28，**实测**，不是推断）**：本节原文把命令面板写成 `Ctrl+K`。
> Odoo 注册的是**逻辑** `control+k`（`command_service.js:67`），而 [core/hotkeys/hotkey_service.js:73-78](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/core/hotkeys/hotkey_service.js#L73-L78) 的修饰键映射是
> `isMacOS() ? ev.ctrlKey : ev.altKey` → logical `alt`、`isMacOS() ? ev.metaKey : ev.ctrlKey` → logical `control`
> ⇒ **macOS 上 Cmd(⌘) 才是 logical control，物理 Ctrl 反被当作 logical alt**：Mac 用户按物理 Ctrl+K **打不开**。
> 🧪 本机实测（headless Chromium，UA = `Macintosh; Intel Mac OS X 10_15_7`，登录 `backoffice@local` 进真后台后按键，各测 2 次）：
> **⌘K → 命令面板可见 = True；Ctrl+K → 命令面板可见 = False**。Windows / Linux 上仍是 `Ctrl+K`。
> ⇒ **本报告其余各处（以及帮助页 / §6 的 tour 文案）凡涉及命令面板键位，一律写「⌘K（Mac）/ Ctrl+K（Windows）」。**

⇒ **「功能藏得深」在 Odoo 里本来就有一条通用出口：命令面板（⌘K / Ctrl+K）打菜单名。** 我们的问题不是没有出口，是**没人告诉用户这个出口存在**。

### 2.11 ⭐ Odoo 19 原生「新手引导」引擎：`web_tour`（「首次使用提示」不需要自研）

| 事实 | 证据 |
|---|---|
| 核心模块 `web_tour`（名 `Tours`，v1.0，`depends: ['web']`） | ✅ [addons/web_tour/__manifest__.py:5,12,13](https://github.com/odoo/odoo/blob/19.0/addons/web_tour/__manifest__.py) |
| 🧪 **本机已安装** | `select name,state from ir_module_module where name='web_tour'` → `installed`（库 `edu19`） |
| 模型 `web_tour.tour`：`name` / `step_ids`(One2many `web_tour.tour.step`) / `url`(Starting URL) / `sharing_url` / `sequence` / `custom` / **`user_consumed_ids`** | ✅ [addons/web_tour/models/tour.py:6-23](https://github.com/odoo/odoo/blob/19.0/addons/web_tour/models/tour.py#L6-L23) |
| **「每人只自动播一次」是原生语义** | ✅ `get_current_tour()` [:38-42](https://github.com/odoo/odoo/blob/19.0/addons/web_tour/models/tour.py#L38-L42)：`search([("custom","=",False),("user_consumed_ids","not in",self.env.user.id)])`；`consume()` :30-36 播完就记进 `user_consumed_ids` |
| 分享链接（可直接发给某人播） | ✅ :28 `sharing_url = f"{base_url}/odoo?tour={name}"` |
| 用户级开关 `res.users.tour_enabled`（界面标签 **Onboarding**） | ✅ [addons/web_tour/models/res_users.py:7](https://github.com/odoo/odoo/blob/19.0/addons/web_tour/models/res_users.py#L7)；计算规则 :9-13 = `user._is_admin() and demo_modules_count == 0` ⇒ **默认只有管理员开着** |
| 后台可视化维护（表单/列表/搜索 + 菜单项） | ✅ [addons/web_tour/views/tour_views.xml:3,45,59,69,75](https://github.com/odoo/odoo/blob/19.0/addons/web_tour/views/tour_views.xml)（`menuitem id="menu_tour_action" parent="base.next_id_2"`） |
| 前端服务：`startTour(name, opts)` / 进页面自动播 `session.current_tour` / `?tour=` URL 参数 / **`startTourRecorder()` 录制器** | ✅ [tour_service.js:126](https://github.com/odoo/odoo/blob/19.0/addons/web_tour/static/src/js/tour_service.js#L126) / :269-275 / :258-261 / :250,277-282 / `odoo.startTour` :285 |
| 🧪 库里已有 4 条 tour | `select id,name,url,custom from web_tour_tour` → `account_tour` / `event_tour` / `hr_recruitment_tour` / `discuss_channel_tour`（**没有一条是我们的**） |
| 🧪 平台侧开关状态 | `select tour_enabled, count(*) from res_users group by 1` → `f=10, t=2`（12 个用户只有 2 个开着） |

⇒ **结论（能装不写）：「首次使用提示/功能导览」不需要自研任何引擎，只需要 (1) 写 tour 内容，(2) 给目标用户打开 `tour_enabled`。**

### 2.12 「观感/手感」有哪些原生旋钮（含负结论）

**有**：`decoration-*` 行着色、`widget="badge"`（本仓已用）、`sum`/`avg` 合计（RNG `common.rng:215,217`）、`width`（:201）、`limit`/`groups_limit`、`editable` 行内编辑、`sample` 示例数据、`oe_stat_button` 智能按钮。

**样式钩子（可覆盖，但要自研样式）**：
- ✅ [addons/web/static/src/views/list/list_renderer.scss:3-4](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/views/list/list_renderer.scss#L3-L4)：`--ListRenderer-table-padding-x`、`--ListRenderer-thead-padding-y`；:7 `--ListRenderer-tfoot-bg-color`
- ✅ [addons/web/static/src/views/view.scss:44,57](https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/views/view.scss#L44)：空内容区最小高度
- ⚠ 后台顶栏颜色机制（`$o-navbar-background` 快照问题）见 [ui-design.md](ui-design.md) §3.2

**❌ 负结论**：Odoo 19 `web` 模块**没有 density（紧凑/宽松）开关**——`grep -rn "density" addons/web/static/src/` 命中 **0**。用户若觉得「行太高/太挤」，**没有原生设置可给**，只能 SCSS 覆盖或改 `--ListRenderer-*`。

---

## 3. 本仓现状实测（同一条尺子量自己）

🧪 取证命令（工作目录 = 本仓根）：

```bash
# ⚠ 已订正（2026-09-28）：这两条是 **raw grep**，数的是「命中行数」——注释文本里**提到**这个属性名
#   同样命中 ⇒ **不是列数**。元素级真实值见本段末尾的订正块与 python 片。
grep -rn --include=*.xml -F 'optional="hide"' custom_addons | wc -l   # 37（308efbb 之前；raw grep，已订正）
grep -rn --include=*.xml -F 'optional="show"' custom_addons | wc -l   # 34（308efbb 之前；raw grep，已订正）
grep -rn --include=*.xml -F 'searchpanel' custom_addons | wc -l       # 0
grep -rn --include=*.xml -F 'sample="1"' custom_addons | wc -l        # 0
grep -rn --include=*.xml -F 'expand="' custom_addons | wc -l          # 0
grep -rn --include=*.xml -F 'multi_edit' custom_addons | wc -l        # 1
grep -rn --include=*.xml 'name="help"' custom_addons | wc -l          # 17（动作总数 56）
```

| 指标 | 本仓 | 含义 |
|---|---|---|
| `ir.actions.act_window` 动作数 | **56** | — |
| 其中写了 `<field name="help">`（空状态引导） | **17 / 56** | **39 个动作的空状态是英文兜底文案** |
| `view_mode` 分布 | `list,form` **39**；`list,pivot` 2；`list` 2；`form` 2；`pivot,list` 1；`list,form,pivot` 1；`graph,pivot` 1；`calendar,list,form` 1 | **39/56 打开就是纯列表，没有视图切换** |
| `<kanban>` 视图 | **0** | 卡片视图完全没用 |
| `<activity>` 视图 | **0** | 活动/待办视图完全没用 |
| `<calendar>` / `<pivot>` / `<graph>` 视图 | 1 / 1 / 1 | 几乎没用 |
| `searchpanel` | **0** | 左侧常驻筛选一次没用 |
| `sample="1"` | **0** | 空库永远是一片白 + 英文兜底 |
| `expand="..."` | **0** | 分组默认收起 |
| `default_group_by` | 1 | — |
| `search_default_*` | 5 | — |
| `optional="hide"` / `optional="show"` | **33 / 36**（元素级；308efbb 之前 = **34 / 34**）⚠ 原表 **37 / 34** 是 raw grep 误值，已订正（见下方「数字订正」块） | 默认可见的列**已经反超**默认隐藏的；仍有 **33 条默认不可见列**（原结论「藏起来的比露出来的还多」不成立） |
| `groups="..."` | 47 | 按组隐藏（合理，但需与「该摊开」区分） |

**⚠ 数字订正（2026-09-28，原数字保留在上方，不删）**：原表与 TL;DR 写的 `optional="hide"` **37** / `optional="show"` **34** 是 **raw grep 行数**，不是列数。
- **原数字为何错**：`grep -F 'optional="hide"'` 数的是「命中的行」——XML **注释里提到**这个属性名同样命中；本仓至少两处在注释里讲这件事（`invite_code_views.xml` 的现场抱怨注释、`fees.xml` 的回归护栏注释），所以 raw 值**系统性偏高**，且**会随着护栏注释变多而越来越偏**。
- **元素级真实值**（只数 `<field ...>` 开始标签上的 `optional=`，先摘掉 XML 注释）：

| 时点 | `optional="hide"` | `optional="show"` |
|---|---|---|
| **308efbb（本次 UI 改动）之前** | **34** | **34** |
| **308efbb 之后（当前树，2026-09-28）** | **33** | **36** |

（308efbb 把 `faculty_id`、`reimburse_ref` 由 `hide` 改 `show`，把 `currency_id` 由 `column_invisible` 改 `hide` ⇒ hide −1、show +2、净 +1 条进「列设置」菜单。）

```bash
# 元素级计数（工作目录 = 本仓根）：先摘注释，再只数 <field ...> 开始标签上的 optional=
python3 - <<'PY'
import re, os
c = re.compile(r'<!--.*?-->', re.S); t = re.compile(r'<field\b[^>]*>', re.S)
n = {'hide': 0, 'show': 0}
for dp, _, fs in os.walk('custom_addons'):
    for f in fs:
        if f.endswith('.xml'):
            s = c.sub('', open(os.path.join(dp, f), encoding='utf-8').read())
            for m in t.finditer(s):
                for a in re.findall(r'optional="(hide|show)"', m.group(0)):
                    n[a] += 1
print(n)   # 当前树 {'hide': 33, 'show': 36} ｜ 308efbb 之前 {'hide': 34, 'show': 34}
PY
```

- **被订正掉的结论**：「**默认藏起来的列比默认露出来的还多**」**不成立** —— 改前两者持平（34/34），改后默认可见的反超 3 个（33/36）。
- **不受影响的判断**：仍**有 33 条默认不可见的列**，其中包含用户必须用的可编辑列（§3 下方 `invite_code_views.xml` 先例 + §7.2 的 D1/D2 裁定）；「第一杀手是 `optional="hide"`」这个**方向**仍成立，只是**不能再用「37 > 34」当论据**。
- 另注：raw grep 在 308efbb **之后反而涨到 43 / 37**（该提交自己的护栏注释又提了 7 次）⇒ **下次引用本仓列显隐数字，请用元素级计数。**

**截图那个列表的实名定位**：[custom_addons/edu_portal/views/fees.xml:56-82](custom_addons/edu_portal/views/fees.xml#L56-L82)（`view_edu_fee_bill_list`）
- 12 列里 `faculty_id`、`reimburse_ref` 是 `optional="hide"`，`currency_id` 是 `column_invisible="1"`（**永久不可见**）。
- 对应动作 `:166-174` `action_edu_fee_bill`：`view_mode` = `list,form`（无视图切换），**有** `help`（这个做对了）。
- 菜单：`:182-189`「财务管理」→「账单管理」/「缴费流水」；[custom_addons/edu_portal/views/fee_category.xml:67](custom_addons/edu_portal/views/fee_category.xml#L67)「费用分类」；[custom_addons/edu_portal/views/ledger.xml:15](custom_addons/edu_portal/views/ledger.xml#L15)「财务总台账」。

**⭐ 本仓已有的「同款抱怨」铁证**（[custom_addons/edu_portal/views/invite_code_views.xml:58-65](custom_addons/edu_portal/views/invite_code_views.xml#L58-L65)，原文）：

```xml
<!-- 2026-09-17（用户现场：「我怎么不可以调整这个邀请码的可使用次数」）：
     可用次数(use_limit) 是新码「可用/剩余/已用」三列里**唯一可编辑**的一列，
     但旧版它是 optional="hide" —— 用户默认只看得见只读的「剩余次数」
     (uses_left = _compute_uses_left 计算列，点进去改不动)，
     于是判定「次数改不了」。此处去掉 optional="hide" 让它默认可见且可编辑，
     并紧挨 uses_left 成对读作「可用次数 | 剩余次数」。
     ⚠ 回归护栏：不要再给它加 optional="hide" / readonly ——
     否则本条症状会原样复发（只放只读列 = 用户必然点错）。 -->
```

⇒ **用户今天的抱怨不是新问题，是同一个问题在财务模块重演。** 这条注释本身就是「可用性缺陷（非审美）」的判定先例。

---

## 4. ② 「功能被折叠、不点不知道」在成熟产品里怎么解

> 判据：本节每条都给 **正例**（做对了，可复用）与 **反例**（做错了，别抄）。

### 4.1 正例 / 反例清单

| 模式 | 正例（一手来源） | 反例（同来源里的教训） |
|---|---|---|
| **列显隐做成一等公民** | 🌐 钉钉 AI 表格「字段管理」：*"Manage fields centrally from each view's toolbar. Click the icon next to the field name to **show or hide** it in the current view."* — [help.dingtalk.io/aitable/fields/field-management.md](https://help.dingtalk.io/aitable/fields/field-management.md)。另见 [add-field.md](https://help.dingtalk.io/aitable/fields/add-field.md)：*"add, edit, **hide**, freeze, reorder, describe, and set defaults for fields"* | 反例：**主字段（第一列）不可隐藏/删除**（`add-field.md`：*"The first column ... can't be deleted or hidden"*）——「必须永远可见的那一列」由产品定死，不交给用户 |
| **视图 = 保存下来的筛选** | 🌐 钉钉：*"A view is not a new table — it's a saved filter + a way to present data!"* — [views/views-overview.md](https://help.dingtalk.io/aitable/views/views-overview.md)；一个数据表支持 表格/甘特图/日历/看板/画册 多视图 — [中文快速上手](https://help.dingtalk.io/zh/aitable/getting-started/quick-start.md) | 反例：视图一多，「当前在哪个视图」就成了新的迷路点；钉钉用「左侧视图列表常驻」解决 |
| **功能地图 / 新手入门手册** | 🌐 校管家 wiki「新手入门手册」把后台编成四步：一、基础数据设置 → 二、初始化系统数据 → 三、进一步运用系统 → **四、探索更多高阶功能** — [wiki.xiaogj.com/docs/xin-shou-ru-men](https://wiki.xiaogj.com/docs/xin-shou-ru-men) | 反例：手册是**站外文档**，产品内没有等长入口——用户不点开 wiki 就还是不知道 |
| **表格里的「折叠」补偿：行内批量新增 + 分组 + 落库前预检查** | 🌐 校管家「表格排课」：支持「新增10行」「按规则批量新增」「按不同维度分组」，并在**落库前**给三档异常提示（**有冲突 / 被限制 / 数据异常**）— [wiki.xiaogj.com/docs/biao-ge-pai-ke](https://wiki.xiaogj.com/docs/biao-ge-pai-ke) | 反例：三档提示是**排课专有**，说明「异常提示分档」是他们自己发明的、通用后台没有 |
| **搜索兜底：设置/菜单能被搜到** | ✅ Moodle 后台设置全局搜索：[admin/search.php](https://raw.githubusercontent.com/moodle/moodle/MOODLE_405_STABLE/admin/search.php)（`admin_search_settings_html($query)`）——上千个折叠设置靠它被发现。✅ Odoo 命令面板（⌘K / Ctrl+K）+ `/` 搜全部菜单（§2.10） | 反例：**搜索只能救「知道关键词」的人**；用户不知道功能叫什么就搜不到（这正是 Odoo `/` 面板要按「应用 + 菜单树路径」模糊匹配的原因，`menu_providers.js:37-40`） |
| **表格每列一个显隐开关（不进设置页）** | ✅ Moodle `flexible_table::show_hide_link()` 在**表头直接渲染**隐藏/显示图标，带 `aria-expanded` 与 `data-action=hide/show`：[lib/table/classes/flexible_table.php:1249-1290](https://raw.githubusercontent.com/moodle/moodle/MOODLE_405_STABLE/lib/table/classes/flexible_table.php)；常量 `TABLE_VAR_HIDE/SHOW`：[lib/tablelib.php:29-30](https://raw.githubusercontent.com/moodle/moodle/MOODLE_405_STABLE/lib/tablelib.php)；默认隐藏列可预设 `set_hidden_columns()` :1502，前序状态持久化 :1474-1502 | 反例：Moodle 的开关**在表头 hover 才出现**，仍然属于「要点一下」那一类 |
| **首次使用导览（tour）** | ✅ Odoo 原生 `web_tour`（§2.11）：每用户只播一次 + 后台可视化编辑 + 录制器。✅ Moodle `admin/tool/usertours/`：可按 role / course / theme / accessdate 过滤给谁看哪段（[classes/local/filter/](https://github.com/moodle/moodle/tree/MOODLE_405_STABLE/admin/tool/usertours/classes/local/filter)），并埋了 `step_shown` / `tour_started` / `tour_ended` 事件 | 反例：导览**只讲一次**，讲完就消失；靠它兜底「全部功能」必然失败——它只能解决「最重要的一两步」 |
| **把待办推到用户面前** | ✅ Canvas：[app/views/courses/_to_do_list.html.erb](https://github.com/instructure/canvas-lms/blob/master/app/views/courses/_to_do_list.html.erb)（dashboard 与课程首页都渲染）+ [app/views/courses/_recent_feedback.html.erb](https://github.com/instructure/canvas-lms/blob/master/app/views/courses/_recent_feedback.html.erb) + [app/presenters/to_do_list_presenter.rb](https://github.com/instructure/canvas-lms/blob/master/app/presenters/to_do_list_presenter.rb) | 反例：Canvas 只推「待办/反馈」，不推「你还有哪些功能没用过」——**没有一家产品做「功能使用度发现」** |
| **折叠导航，但给信号** | ✅ Canvas 全局导航可折叠且记住状态：[ui/features/navigation_header/react/SideNav.tsx:90](https://github.com/instructure/canvas-lms/blob/master/ui/features/navigation_header/react/SideNav.tsx#L90)（`collapse_global_nav`）、:211-213（`primary-nav-expanded`）；课程导航页签可隐藏但**存在统一配置模型** `course.tab_configuration`：[app/models/course.rb:83](https://github.com/instructure/canvas-lms/blob/master/app/models/course.rb#L83)（serialize）、:3502、:3970（`hidden_tab_ids` = 从 `tab_configuration` 里筛 `t[:hidden]`） | 反例：**隐藏页签对学生是永久不可见**（`tab_configuration` 是课程级配置），学生端并没有「查看全部页签」入口 |
| **空状态引导** | ✅ Odoo：`ir.actions.act_window.help`（`ir_actions.py:71-72`）+ 三种表情图标（`view.scss:25,32,39`）；✅ Canvas [ui/shared/planner/components/PlannerEmptyState/](https://github.com/instructure/canvas-lms/tree/master/ui/shared/planner/components/PlannerEmptyState)、[app/stylesheets/components/_empty-state.scss](https://github.com/instructure/canvas-lms/blob/master/app/stylesheets/components/_empty-state.scss) | 反例：**Odoo 默认兜底是英文**（`no_content_helpers.xml:13-14`）——不写 `help`，中文用户看到英文 |
| **示例数据（让空表先长得像样）** | ✅ Odoo `sample="1"`（`list_view.rng:51` → `views/view.js:356,400-401`） | 反例：示例数据**必须明显区别于真数据**，否则会误导（本仓品牌红线：`docs/code-map.md` §6 演示数据标记） |
| **功能开关的「存在感」** | ✅ Canvas [config/feature_flags/00_standard.yml](https://github.com/instructure/canvas-lms/blob/master/config/feature_flags/00_standard.yml)：每个 flag 有 `state`（`hidden`/`allowed`/…）、`display_name`、`description`、`applies_to` | 反例：`state: hidden` 的 flag 用户**根本看不到它存在**——这是「可发现性 vs 稳定性」的自觉取舍（先默认关，验证后再放） |

### 4.2 归纳：三条可判定的原则（有证据支撑）

1. **「藏」必须留一个非记忆性的找回路径**：钉钉（工具栏按钮）、Moodle（表头图标 + 后台搜索）、Odoo（列设置下拉 + 命令面板 ⌘K / Ctrl+K）。**反例判定**：`column_invisible` / 按 `groups` 永久隐藏 / Canvas `hidden` 页签 —— **没有任何找回路径 = 可用性缺陷**。
2. **默认值就是产品意见**：`optional="hide"` 是「我认为你不常看」，`optional="show"` 是「我认为你该看见」。⚠ 原文这里的论据「**37 vs 34**（hide 多于 show）说明我们长期在做前者」**是 raw grep 误值，已在 §3 订正**（元素级真实值：改前 34 vs 34、改后 33 vs 36）。**但「谁多谁少」本来就不是缺陷判据** —— 判据是 D2（默认值让用户做出错误判断，见 §3 `invite_code_views.xml` 先例）；存量是那 **33 条默认不可见的列**。
3. **导览只解决前两步，功能清单要用「常驻可搜」兜底**：没有任何一家（含 Odoo/Moodle/Canvas/钉钉/校管家）用导览讲完所有功能；**常驻的搜索 + 常驻的列表**才是兜底。

---

## 5. ③ 有哪些现成模块/方案可以「装」而不是「写」

**取证方式**：`git ls-remote --heads https://github.com/OCA/<repo>` 验证 19.0 分支存在（`web` / `server-ux` / `server-backend` / `server-brand` / `server-tools` / `vertical-education` 全部 **YES**）；`curl https://raw.githubusercontent.com/OCA/<repo>/19.0/<module>/__manifest__.py` 取 `license` 字段。

### 5.1 OCA/web @ 19.0（最相关的一批；该分支共 31 个模块）

| 模块 | 版本 | license | 它解决什么 | 与两个痛点的关系 |
|---|---|---|---|---|
| [`web_responsive`](https://github.com/OCA/web/tree/19.0/web_responsive) | 19.0.1.1.0 | **LGPL-3** | 全屏应用菜单、**应用菜单内搜索**、列表视图粘性表头/页脚、表单粘性状态栏、加大复选框、小屏按钮图标化、快捷键（`Alt+Shift+NUM`、`Alt+S` 保存） | (b) **最对症**：应用菜单内搜索 = 「我要的功能在哪」的通用入口；(a) 粘性表头/加大复选框 = 手感 |
| [`web_group_expand`](https://github.com/OCA/web/tree/19.0/web_group_expand) | 19.0.1.0.0 | AGPL-3 | 分组列表右上角加「全部展开/收起」按钮，一次展开一层 | (b) 对应「分组折叠了看不见」。⚠ 与 Odoo 19 原生 `expand` **可能重叠**（原生决定**默认**是否展开；OCA 这个提供**随时一键**展开）——装上要验证是否还需要 |
| [`web_remember_tree_column_width`](https://github.com/OCA/web/tree/19.0/web_remember_tree_column_width) | 19.0.1.0.0 | **LGPL-3** | 记住用户拖过的列宽 | (a) 手感（列表列宽每次重来很烦） |
| [`web_quick_start_screen`](https://github.com/OCA/web/tree/19.0/web_quick_start_screen) | 19.0.1.0.0 | AGPL-3 | **可配置的「开始屏」**：把常用动作做成一屏入口（`Settings > Technical > User Interface > Screen actions`，按用户配） | (b) 把「常用但藏得深」的动作摊到第一屏。README 原话：*"Some users use repeatedly the same actions on and off and sometimes those actions are so many clicks away which tends to be frustrating."* |
| [`web_search_with_and`](https://github.com/OCA/web/tree/19.0/web_search_with_and) | 19.0.1.0.0 | AGPL-3 | 搜索框多条件用 AND 而非 OR | (b) 搜索可用性 |
| [`web_tree_many2one_clickable`](https://github.com/OCA/web/tree/19.0/web_tree_many2one_clickable) | 19.0.1.0.0 | AGPL-3 | 列表里的 m2o 名可直接点开 | (a) 手感 |
| [`web_m2x_options`](https://github.com/OCA/web/tree/19.0/web_m2x_options) | 19.0.1.0.1 | AGPL-3 | m2o/m2m 控件行为（限制创建、限制打开等） | (a) 手感 |
| [`web_no_bubble`](https://github.com/OCA/web/tree/19.0/web_no_bubble) | 19.0.1.0.0 | AGPL-3 | 去掉 x2many 输入时的气泡提示 | (a) 手感 |
| [`web_dialog_size`](https://github.com/OCA/web/tree/19.0/web_dialog_size) | 19.0.1.0.2 | AGPL-3 | 对话框可最大化/记忆尺寸 | (a) 手感 |
| [`web_dark_mode`](https://github.com/OCA/web/tree/19.0/web_dark_mode) | 19.0.1.0.0 | AGPL-3 | 后台深色模式 | (a) 纯观感（**属风格偏好**） |
| [`web_refresher`](https://github.com/OCA/web/tree/19.0/web_refresher) | 19.0.1.0.0 | AGPL-3 | 可配置自动刷新 | (a) 手感 |
| `web_chatter_position` / `web_notify` / `web_calendar_slot_duration` / `web_company_context_highlight` | 19.0.1.0.x | LGPL-3 | chatter 位置 / 通知 / 日历刻度 / 多公司高亮 | 边缘 |
| `web_ir_actions_act_window_message` / `web_form_banner` / `web_environment_ribbon` / `web_widget_x2many_2d_matrix` / `web_timeline` / `web_favicon` / `web_editor_class_selector` / `web_pwa_customize` / `web_search_deactivate_autosearch` / `web_m2x_options_manager` / `web_ir_actions_act_multi` / `web_widget_one2many_tree_line_duplicate` / 其余 8 个 | 19.0.1.0.x | 除 `web_ir_actions_act_multi`（LGPL-3）外多为 AGPL-3 | 见 [OCA/web@19.0 目录](https://github.com/OCA/web/tree/19.0) | 边缘 |

### 5.2 OCA/server-ux @ 19.0（与「搜索/发现」相关）

| 模块 | license | 说明 |
|---|---|---|
| `base_search_custom_field_filter` | AGPL-3 | **运行时给搜索视图加任意字段筛选**（把「能筛什么」交给用户） |
| `base_technical_features` | AGPL-3 | 不开 debug 也能看到技术字段 |
| `server_action_mass_edit` | AGPL-3 | 批量编辑（与原生 `multi_edit` 重叠，装前需比较） |
| `document_quick_access` | AGPL-3 | 文档快捷入口（书签式） |
| `filter_multi_user` | AGPL-3 | 共享筛选器 |
| `base_substate` / `base_export_manager` / `base_menu_visibility_restriction` / `developer_menu` / `base_optional_quick_create` | AGPL-3 | 子状态 / 导出模板 / **按组限制菜单可见性** / 开发者菜单 / 快速创建开关 |
| `date_range` | LGPL-3 | 可复用的日期区间（给筛选用） |
| `OCA/server-backend`：`base_user_role` / `base_user_role_company` | AGPL-3 | 带起止日期的角色（本仓 [course-representative.md](course-representative.md) 已记录） |

### 5.3 ⚠ AGPL-3 传染性评估（必须点名）

**事实（有出处）**：OCA 每个模块的 `__manifest__.py` 里都有 `license` 字段；上面列出的模块绝大多数为 `AGPL-3`，少数为 `LGPL-3`。

**判断（非结论，建议法务确认）**：
- 只**安装、不修改** AGPL-3 模块 → 不改变本仓 `custom_addons/edu_*` 的许可；但若整个系统对外提供服务，AGPL 的网络交互条款对**被修改的 AGPL 部分**有源码提供义务。
- 一旦为了适配（改视图、改字段名、改逻辑）去动 OCA 代码 → 该改动部分需按 AGPL 义务提供源码。
- `LGPL-3` 模块（`web_responsive` / `web_remember_tree_column_width` / `date_range` / `web_chatter_position` / `web_notify` / `web_calendar_slot_duration` / `web_company_context_highlight` / `web_ir_actions_act_multi`）风险最低，**若必须装，优先选这几个**。
- ⚠ **未验证**：本报告没有拉取 AGPL-3.0 原文与 OCA 许可政策页逐条核对「网络交互」条款措辞，也没有咨询法务；上述是依据 `license` 字段与通行理解的**推断**，不得当结论用。

### 5.4 明确的「装不了」

- `OCA/vertical-education` @ 19.0 分支存在但**与本主题无关**（历史调研已多次记录其 19.0 无相关模块）。
- Moodle 的 `flexible_table`（PHP）、`admin/tool/usertours`（PHP）**不可移植**，只能**抄形状**。
- Canvas 是 AGPL-3 的 Rails 应用，**只可抄形状**。

---

## 6. ④ 候选方案（3 个，含取舍与「解决不了什么」）

> 三个方案不互斥，可按 A → B → C 递进；**每个都写清「它解决不了什么」**，方便与用户谈取舍。

### 方案 A：只动配置（原生开关优先），不改代码架构 —— 成本最低

**改什么**（全部是 XML/数据，不写业务逻辑）：
1. **默认可见性复盘**：把「用户必须用的可编辑列」从 `optional="hide"` 改 `optional="show"`（先做财务模块，对齐 `invite_code_views.xml:58-65` 已有的先例）。改 `column_invisible` 的地方逐个复核——那是**没有找回路径**的隐藏。
2. **搜索面板**：给高频大表（账单、缴费流水、总台账、学生、课表）加 `<searchpanel>`，用 `select="one"` 做分类树（分类/批次/状态），`enable_counters="1"` 显示条数（⚠ 不要同时给带 `domain` 的 filter，否则计数器被静默关闭）。
3. **空状态**：给剩下 39 个动作补 `<field name="help">`；给高频列表加 `sample="1"`。
4. **视图切换**：把 `view_mode` 从 `list,form` 扩成 `list,kanban,form` 或加 `activity`（先挑 2-3 个最痛的表验证），并配 `default_group_by` + `expand="1"`。
5. **预设筛选**：用 `search_default_*` 让「最常用的那一档」一进来就是开的。
6. **引导**：在本机已有的 `web_tour` 里写 2-3 条教务 tour（列表怎么筛选、列设置在哪、命令面板 ⌘K / Ctrl+K 怎么用），并把目标用户的 `tour_enabled` 打开（当前 12 个用户只有 2 个开着）。
7. **显性告知**：命令面板（⌘K / Ctrl+K）、`Alt` 热键徽标、列设置图标位置——**这三条 Odoo 原生能力用户 100% 不知道**（本仓 0 处提及）。

**成本**：低（纯 XML，无新模块）；可分批、可回滚。
**风险**：低。主要风险是「默认可见列变多 → 屏宽不够」（用 `limit`/`width`/`optional` 取舍）；以及 `expand="1"` 在数据量大时首屏变慢（用 `groups_limit` 兜）。
**解决不了什么**：
- 解决不了「整体观感」（顶栏颜色、行高、密度）——那需要样式层，而 Odoo 没有 density 开关。
- 解决不了「用户不知道有这个功能」的**根本**（只能把**现有**入口摊开；没有的功能仍然没有）。
- 不提供「跨模块的功能地图」。

### 方案 B：装 OCA 现成模块（能装不写）

**改什么**：
1. **`web_responsive`（LGPL-3，19.0.1.1.0）** —— 首要评估对象：全屏应用菜单 + **应用菜单内搜索**（通用「功能在哪」入口）+ 列表粘性表头。
2. 可选：`web_remember_tree_column_width`（LGPL-3，列宽记忆）、`web_group_expand`（AGPL-3，一键展开分组）、`web_quick_start_screen`（AGPL-3，可配置开始屏）。
3. 装前必做：本机 `-u` 冒烟 + 与 `edu_brand` 的 SCSS/模板覆盖冲突排查（`web_responsive` 会改应用菜单与快捷键，可能与品牌定制打架）。

**成本**：中低（安装 + 冒烟 + 冲突排查）。
**风险**：
- **license**：`web_responsive` / `web_remember_tree_column_width` 是 LGPL-3（低）；`web_group_expand` / `web_quick_start_screen` 是 AGPL-3（需法务确认，见 §5.3）。
- **兼容/升级**：OCA 19.0 分支刚起步，且会覆盖 Odoo 原生前端行为；Odoo 升级时要跟。
- `web_responsive` 与 `web_group_expand` 的功能**部分与 Odoo 19 原生重叠**（原生已有 `expand`、命令面板）——装了可能「双重入口」。
**解决不了什么**：
- **解决不了「哪一列该默认可见」** —— 这是业务判断，任何模块都不会替我们决定。
- 解决不了「没有中文功能地图/导览」。
- 解决不了「观感」（除了 dark mode，而那是风格偏好）。

### 方案 C：自研一层统一 UX（谨慎，只在无先例处自研）

**改什么**（按「确实无先例」排序，能砍就砍）：
1. **自研候选 1（可能无先例）：中文「功能地图 / 能力清单」页面** —— 把本仓全部动作列成可搜索的清单（可复用 `ir.actions.act_window` + 已注册的菜单树，做到「搜索 + 直达」）。**为何可能无先例**：Odoo 原生命令面板（⌘K / Ctrl+K）的 `/` 面板已经能搜全部菜单（§2.10）——**自研前必须先验证它是否已够用**；若够用，本条应直接砍掉。
2. **自研候选 2（有先例可抄形状）：导览内容 + 首启引导** —— 引擎用原生 `web_tour`（§2.11），**只写内容，不写引擎**。形状抄 Moodle `tool_usertours` 的「按角色/课程过滤给谁看哪段」。
3. **自研候选 3（有先例可抄形状）：列表观感令牌** —— 用 SCSS 覆盖 `--ListRenderer-table-padding-x` / `--ListRenderer-thead-padding-y`（`list_renderer.scss:3-4`）做「紧凑/宽松」切换，**形状抄 AITable 的「行高设置」**（[aitable/basic-operations/row-height.md](https://help.dingtalk.io/aitable/basic-operations/row-height.md)）与 OCA `web_dark_mode` 的开关形状；**为何要自研**：Odoo 无 density 开关（§2.12 负结论）。

**成本**：高（新模块 + 前端 + 回归 + 长期维护）。
**风险**：高——自研前端样式会在 Odoo 升级时碎；与 `edu_brand` 已有 SCSS 覆盖叠加（见 [ui-design.md](ui-design.md) §3 三个机制）。
**解决不了什么**：解决不了「用户根本不需要这些功能」的问题——**功能多不是 UI 能修的**（有些模块也许该砍，而不是该被发现）。
**前置条件**：按铁律 0，**自研前必须先在报告中写明「为何无先例」**；本报告只给出「候选 1 可能无先例」的**待验证**判断（因为命令面板（⌘K / Ctrl+K）已覆盖大部分场景）。

---

## 7. ⑤ 「风格偏好」vs「可用性缺陷」的划分

> 用户原话里前半句是审美，后半句是缺陷。**别把审美当 bug 修，也别把缺陷当审美怼回去。**

### 7.1 判定规则（可操作）

一条 UI 现象是**可用性缺陷**，当且仅当满足下列**任一**：
- **D1 无找回路径**：功能/数据被隐藏后，用户在任何界面都无法重新发现它（`column_invisible`、按 `groups` 永久隐藏、Canvas 式隐藏页签）。
- **D2 默认值违背任务**：默认状态让用户**做出错误判断**（`invite_code_views.xml:60-62`：默认只显示只读列 → 用户得出「改不了」的错误结论）。
- **D3 有可观测的不一致**：界面文字与实际能力不符（如写着「可调整」却没有入口）。
- **D4 必须靠记忆/外部文档**：产品内没有入口，只能靠 wiki/口头（校管家的手册就是站外文档 → 那是补偿，不是解决）。

否则属于**风格偏好**：观感、间距、配色、圆角、动效、深浅色、字体。

### 7.2 逐条裁定

| 观察到的现象 | 裁定 | 依据 |
|---|---|---|
| 财务列表里某些列默认看不见、不点不知道 | **可用性缺陷（D1+D2）** | `optional="hide"` + 本仓 33 处（元素级订正后的值；原文 37 是 raw grep 误值，见 §3）；已有同款先例注释 |
| `currency_id` 用 `column_invisible="1"` | **可用性缺陷（D1）**，但可能是**有意**的技术字段隐藏 → 建议改为「保留但默认隐藏（`optional="hide"`）」，让它进列设置菜单 | `getActiveColumns()` 逻辑（`list_renderer.js:326-341`） |
| 分组列表默认收起 | **可用性缺陷（D1+D4）**：用户得知道分组能展开 | `expand` 原生属性未用（本仓 0 处） |
| 空列表只显示英文 "No data to display" | **可用性缺陷（D3）**：中文产品里出现英文兜底，也没告诉用户下一步做什么 | `no_content_helpers.xml:13-14`；本仓 39/56 动作没写 help |
| 用户不知道命令面板（⌘K / Ctrl+K） / `Alt` 快捷键 / 列设置图标 | **可用性缺陷（D4）**：能力存在但零提示 | `command_service.js:67`、`hotkey_service.js:111`；本仓无任何入口 |
| 蓝色顶栏不好看 | **风格偏好** | 属主题变量（[ui-design.md](ui-design.md) §3），不影响任务完成 |
| 行太高/太挤、表格留白 | **风格偏好**（⚠ 但若「一屏看不完关键列导致必须横向滚动」→ 转 D2 缺陷） | Odoo 无 density 开关（§2.12） |
| 表格边框/斑马纹/圆角 | **风格偏好** | — |
| hover 才有反馈 | **风格偏好**（除非导致 D1，如 Moodle 表头 hover 才出现的显隐图标） | `flexible_table.php:1249-1290` |
| 「希望全部的这类 UI 都改善一下」 | **需求，不是缺陷**：应拆成「哪些是缺陷（可裁定）→ 哪些是偏好（需用户拍板）」 | 本表 |

### 7.3 给决策者的一句话

> **可以裁定并立刻修的是 D1–D4 四类**（默认可见性、找回路径、空状态、入口提示）；**需要用户拍板的是观感层**（顶栏色、密度、圆角）。**把这两件事混在一次改动里，很容易把「用户的审美偏好」当成「我们的实现缺陷」来返工。**

---

## 8. 调研过程记录（可复现命令 / 试过并排除的路径 / 查不到的原因）

> 本节按 `docs/research/README.md` 收录规范：**只留结论会让下一个人把同一条死路再走一遍**。

### 8.1 可复现的取证命令

```bash
# 0) 环境
docker exec edu19-clone-web-1 odoo --version          # Odoo Server 19.0-20260817
docker exec edu19-clone-db-1 psql -U odoo -d edu19 -c "select name,state from ir_module_module where name in ('web_tour','web','base')"

# 1) 读 Odoo 源码（容器内，行号即本报告行号）
docker exec edu19-clone-web-1 nl -ba /usr/lib/python3/dist-packages/odoo/addons/web/static/src/views/list/list_arch_parser.js
docker exec edu19-clone-web-1 cat /usr/lib/python3/dist-packages/odoo/addons/base/rng/list_view.rng
docker exec edu19-clone-web-1 grep -rn "density" /usr/lib/python3/dist-packages/odoo/addons/web/static/src/   # 0 hit

# 2) 上游锚点（行号漂移时对照）
git ls-remote https://github.com/odoo/odoo refs/heads/19.0
curl -s -o /dev/null -w "%{http_code}" https://raw.githubusercontent.com/odoo/odoo/19.0/odoo/addons/base/rng/list_view.rng

# 3) OCA 19.0 分支存在性 + license（不耗 GitHub API 额度）
git ls-remote --heads https://github.com/OCA/web | grep 19.0
curl -s https://raw.githubusercontent.com/OCA/web/19.0/web_responsive/__manifest__.py | grep -E "license|version|name"

# 4) 批量列出 OCA 模块目录（绕开 API 限速）
git clone --quiet --depth 1 --branch 19.0 --filter=blob:none --no-checkout https://github.com/OCA/web /tmp/ocaprobe/web
cd /tmp/ocaprobe/web && git ls-tree -d --name-only HEAD

# 5) 本仓现状统计
# ⚠ optional="hide" 的 raw grep **不是列数**（注释文本同样命中）—— 订正后的元素级值与 python 片见 §3
grep -rn --include=*.xml -F 'optional="hide"' custom_addons | wc -l   # 37（308efbb 之前；raw grep，已订正）
grep -rn --include=*.xml -F 'searchpanel' custom_addons | wc -l       # 0
grep -rn --include=*.xml -F 'sample="1"' custom_addons | wc -l        # 0
grep -rn --include=*.xml 'name="help"' custom_addons | wc -l          # 17 / 56 动作

# 6) 命令面板键位（2026-09-28 订正轮；实测，非推断）
docker exec edu19-clone-web-1 sh -c "nl -ba /usr/lib/python3/dist-packages/odoo/addons/web/static/src/core/hotkeys/hotkey_service.js | sed -n '70,80p'"
#   → :73-78  isMacOS() ? ev.ctrlKey : ev.altKey → "alt"；isMacOS() ? ev.metaKey : ev.ctrlKey → "control"
#     ⇒ macOS 上：物理 Ctrl = logical alt，**Cmd(⌘) = logical control**
docker exec edu19-clone-web-1 sh -c "grep -n 'hotkeyService.add' /usr/lib/python3/dist-packages/odoo/addons/web/static/src/core/commands/command_service.js"
#   → :67  hotkeyService.add("control+k", openMainPalette, …)
# 实测（playwright + headless Chromium，UA=Macintosh，登录 backoffice@local，进 /odoo/settings 真后台后按键，各测 2 次）：
#   Meta+K（⌘K）→ .o_command_palette 可见 = True(2/2) ｜ Control+K → 可见 = False(2/2)
```

### 8.2 试过并排除的路径

| 路径 | 结果 | 排除原因 |
|---|---|---|
| `odoo/addons/base/rng/view.rng` | 404 | **不存在这个文件**；RNG 按视图类型拆分：`list_view.rng` / `search_view.rng` / `activity_view.rng` / `graph_view.rng` / `pivot_view.rng` / `calendar_view.rng` / `common.rng` |
| 上游路径 `addons/base/...` | 404 | `base` 应用在上游是 `odoo/addons/base/`；`addons/` 前缀只对 `addons/` 下的模块成立 |
| `api.github.com` 查模块列表 | 额度耗尽（60/h） | 未认证限速；改用 `git ls-remote` + `raw.githubusercontent.com` + blobless clone |
| `moodle/moodle@main` 的 raw 文件 | **404**（`README.md` 例外，200） | 未查明；改用 `MOODLE_405_STABLE`（`lib/tablelib.php` 200）。⚠ 记在这里：**Moodle 用 `main` 分支取文件会 404，请用 `MOODLE_405_STABLE`** |
| Moodle `whatsnew` 机制 | 文件树中 **0 命中** | Moodle 4.5 已无该机制（不要照抄旧文档）；替代品是 `admin/tool/usertours` |
| Moodle `lib/tablelib.php` 全文 | 只有 49 行 | 该类已移到 `lib/table/classes/flexible_table.php`；`lib/tablelib.php` 只剩常量定义 |
| `admin/search.php` 全文 | 只有 94 行 | 正常（它本来就短），关键调用是 `admin_search_settings_html($query)` |
| Canvas 命令面板（`kbar`/`CommandPalette`/`command-palette`） | 文件树中 **0 命中** | ⚠ 只做了**文件名级**检索（`git ls-tree -r` + `grep -i`），**未做代码级全文搜索** ⇒ 结论只能写「文件名级未发现」 |
| Canvas 空状态通用组件 | 只有分散的 `*EmptyState.tsx` / `PlannerEmptyState` | 没有统一 `EmptyState` 组件可引用 |
| 飞书帮助中心 | **不可取证** | `feishu.cn/hc/zh-CN/articles/<id>` 用 curl 只拿到 SPA 空壳（正文 CJK 字符数 10）；`feishu.cn/hc/api/article/search` 返回 `{"code":1002,"message":"err limit"}` |
| 企业微信帮助中心**正文** | **不可取证** | 目录树是服务端渲染的（`work.weixin.qq.com/help2/*`、`open.work.weixin.qq.com/help2/pc/*`），但**正文由 JS 装载**，curl 拿到的只有导航 + 页脚。仅导航/目录结构可当证据 |
| `www.jiaxiaoguan.com` | `000`（连接失败） | 域名不对；正确入口是本仓历史文档已引用的 `wiki.xiaogj.com` |
| `procomponents.ant.design` / `arco.design` / `docs.qq.com` / `open.dingtalk.com/document/` | 200 但正文 CJK = 0–19 | SPA 空壳，不可取证 |
| 钉钉帮助中心中文索引 `help.dingtalk.io/zh/llms.txt` | 404 `Asset not found` | 只有英文 `/llms.txt`；**但单页可用 `/zh/<path>.md` 直取中文 markdown**（已验证：`/zh/aitable/getting-started/quick-start.md` CJK=1554） |
| `web_search` 工具 | **HTTP 400 insufficient credits** | 全程不可用，改用 curl / web_fetch |
| `work.weixin.qq.com/help2/`（无 `pc` 段） | 404 | 正确形式是 `open.work.weixin.qq.com/help2/pc/<id>` |

### 8.3 一处**不能当结论**的观察

- OCA `web_responsive` 的快捷键改动（`Alt+Shift+NUM`）与浏览器 `Alt+数字` 冲突的关系 —— **未验证**（未在本机实测按键）。

---

## 9. 未验证 / 待确认清单

| # | 事项 | 为什么未验证 |
|---|---|---|
| 1 | OCA 各模块在**我们这套定制**（`edu_brand`/`edu_zh`/`edu_nav`）下是否真的可用、有无样式冲突 | 只做了源码/manifest 级取证，**未在真机安装冒烟** |
| 2 | `web_responsive` 与 Odoo 19 原生命令面板/应用菜单的**功能重叠程度** | 未安装对比；其 README 声称有「应用菜单内搜索」，未实测与命令面板（⌘K / Ctrl+K）的差异 |
| 3 | AGPL-3 对本项目的**具体**影响 | 未咨询法务；未核对 AGPL-3.0 原文与 OCA 许可政策 |
| 4 | 飞书、企业微信的**功能级**证据（正文） | 站点 SPA / 正文 JS 渲染；§8.2 |
| 5 | Canvas 是否真的没有命令面板 | 只做了**文件名级**检索，未做代码级全文搜索 |
| 6 | 校管家的「新手入门手册」是否在产品内有等长入口（还是纯站外 wiki） | 只取证了 wiki 站点；无产品内截图/演示账号 |
| 7 | 学邦 / 希沃的**教务后台**列表 UI 一手证据 | `www.xuebangsoft.com` 只取到公司/产品页（CJK 2340），未找到后台帮助中心；`help.seewo.com` 是**综合素质评价**产品帮助（CJK 407），与本项目不是同一产品线 |
| 8 | Odoo 19 是否有**未公开**的 density 开关（如企业版/埋藏设置） | 只搜了社区版 `addons/web/static/src`；本仓无企业版代码 |
| 9 | `ir.ui.view.groups_id`（按组隐藏整张视图）的准确字段与行号 | 本次未取；需要「按组隐藏视图」时请自行核对 `odoo/addons/base/models/ir_ui_view.py` |
| 10 | `<groupby>` 内部换列的实际视觉效果 | 只读了源码路径（`list_arch_parser.js:149-158` → `list_controller.js:202-207`），**未在真机渲染验证** |
| 11 | `web_tour` 的 `tour_enabled` 打开后对**门户用户**（非 internal）是否生效 | `get_current_tour()` 有 `_is_internal()` 判断（`tour.py:40`）⇒ **推测门户用户不适用**，未实测 |
| 12 | 钉钉 `help.dingtalk.io`（国际版）与本项目所对标的国内版内容是否一致 | 只用了国际版作来源；国内版可能有差异 |
| 13 | 本报告引用的 OCA 版本号（19.0.1.x.x）是否会很快变动 | 取的是 2026-09-28 当天的 `__manifest__.py` |

---

## 附：一句话交接

> **用户的两个痛点里，(b)「功能折叠」是可用性缺陷、有 6 类原生开关可立刻修（第一杀手是 `optional="hide"`，本仓 33 处 —— 元素级订正后的值；原文 37 处是 raw grep 误值）；(a)「不好看」大部分是风格偏好、需要用户拍板，而且 Odoo 没有 density 开关——想改只能自研样式。**
> **「能装不写」的三条现成货：Odoo 原生 `web_tour`（引导引擎，已装未用）、Odoo 原生命令面板 ⌘K（Mac）/ Ctrl+K（Windows）（菜单搜索，零提示）、OCA `web_responsive`（LGPL-3，列表/导航手感）。**
> **没有任何现成方案能替我们回答「哪一列该默认可见」——那是业务判断，必须我们自己拍。**
