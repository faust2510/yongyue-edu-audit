# 架构代码清理审计（custom_addons/）

> **状态**：完成（只读审计 4 条线索 + 2 处低风险小件已修）
> **取证日期**：2026-10-06（本地 edu19 克隆库、工作区、跑着的 web 容器）
> **写作用域**：本文件 + `custom_addons/edu_brand/static/src/css/brand.css`
> **铁律遵守声明**：① `find_undefined_classes` 的 35 个类名**一个都没动**（只给结论，改不改等校长拍）；
> ② **未改任何 `.py`**、未改任何产品行为；③ 未碰他人文件；④ 全程 `git commit --only <路径>`，未用 `git add -A`。
> **行号口径**（本仓 §6 第 15 条）：正文一律「文件 + 符号名」；行号只出现在标注为「取证块」的段落里，
> 那是**某一刻的读数、不得据此定位代码**；每块的复核命令见 §7。

---

## 0. 结论速览

| # | 线索 | 结论 | 本次是否已修 |
|---|---|---|---|
| 1 | `undefined_classes` 35 个 | **9 个是工具误报 / 4 个是真缺陷（命名不一致或变体缺口）/ 12 个是整块未移植 / 10 个是无害标记** | ❌ 未动（按要求等校长拍） |
| 2 | brand.css 失效类名 + 孤儿样式 | 孤儿样式 2 条**属实**（已删）；失效类名 2 个**属实**（删除点在 `views/`，超出写作用域，附一行改法） | ⚠️ 部分（删了孤儿样式） |
| 3 | edu_portal ↔ edu_schedule 依赖环 | **仓内无环**；跨模块模板引用 8 条**全部已声明**；另有 **2 处无守卫的模型级未声明依赖**（edu_brand→edu_portal、edu_public→edu_portal） | ❌ 未动（要动 depends，超出写作用域） |
| 4 | brand.css 违反令牌纪律 | 实测 **58 处**色值字面量有**同值令牌**（本轮换了 56 处，另 2 处随孤儿样式一起删除）；**27 种**无同值令牌，**不可换** | ✅ 已修 |

一句话：**校长看到的「35 个未定义类名」里，真正需要动的只有 4 个（且都是几行 CSS 的事）；
其余 31 个是「尺子的盲区」或「无害的历史标记」。**

---

## 1. 线索一：`undefined_classes` 的 35 个 —— 逐类判定

### 1.1 先把尺子说清楚（结论完全取决于这两个扫描面）

`scripts/find_undefined_classes.py` 的判据是**两个集合求差**：

- **「用了」** = `custom_addons/*/views/*.xml` 里 `class=` / `t-att-class=` 的**字符串字面量**（注释与 `<style>` 块被挖空）；
- **「定义了」** = `custom_addons/*/static/**/*.{css,scss,js}` 里**出现过该名字**（不做选择器解析）。

⇒ 由此派生两个**必然的盲区**（本轮实测都撞上了）：

1. **定义面不含「views 里的内联 `<style>` 块」** —— 在模板里写的样式，工具看不见；
2. **定义面用 `re.findall` 逐字符消费**，形如 `.a.b{…}` 的**合并选择器**里，第二个类名前面的那个 `.`
   会被上一个匹配吃掉 ⇒ **相邻的第二个类名永远扫不到**（§1.4 有复现代码）。

### 1.2 四类结论（35 = 9 + 4 + 12 + 10）

| 类别 | 个数 | 含义 | 建议 |
|---|---|---|---|
| **A 工具误报** | 9 | 真实样式规则存在，只是不在工具的两个扫描面里 | 工具应修（§1.4），**页面无需改动** |
| **B 真缺陷** | 4 | 类名写错、或同族变体缺失 ⇒ **视觉确实没生效** | **建议修**（4 处，均在 `edu_portal`） |
| **C 整块未移植** | 12 | 成绩单「学期卡片」整块没有自定义样式，靠 Bootstrap `.card` 撑住 | 属于**未完成的移植**，修不修是产品决定 |
| **D 无害标记** | 10 | 该元素另有已定义类（Bootstrap 或自有类）承载视觉；类名只是历史标记 | **不修**（删了也没视觉变化，留着无害） |

### 1.3 逐类明细

> **取证块（2026-10-06 读数，不得据此定位代码；复核命令见 §7.1）**
> 「使用处」为模板 `class=` 中的首次命中；「处数」为全 `views/*.xml` 里按词边界统计的出现次数。

| 类名 | 使用处（首例，取证块） | 处数 | 判定 | 依据 |
|---|---|---|---|---|
| b11-home | edu_portal/views/batch2.xml:687 | 2 | D 无害标记 | 同元素带 `row`；JS 用 `[data-home-role]` 属性选，不用类名 |
| b11-shell | edu_portal/views/edu_portal_templates.xml:18 | 1 | D 无害标记 | 同元素带 `o_portal_wrap`；CSS 作用域用的是 `#wrapwrap.o_portal .o_portal_wrap` |
| b11-user-name | edu_portal/views/edu_portal_templates.xml:101 | 1 | D 无害标记 | 同元素带 `d-none d-md-inline`（Bootstrap 管显隐） |
| oe-adm | edu_portal/views/batch1.xml:704 | 1 | D 无害标记 | 同元素带 `oe-rc-card`（已定义，见 batch1.css） |
| oe-asg-btn--active | edu_portal/views/batch2.xml:579 | 2 | **B 缺变体** | 同族有 `.oe-asg-btn` / `--danger` / `--ghost`，**独缺 `--active`** ⇒ 选中 tab 无选中态 |
| oe-att-col-wide | edu_portal/views/batch2.xml:427 | 1 | A 工具误报 | 规则在 enterprise.css，选择器是合并写法 `.oe-att-field.oe-att-col-wide` |
| oe-cal-dayno | edu_portal/views/calendar.xml:150 | 1 | A 工具误报 | 定义在 calendar.xml 的**内联 style 块**（起始行见 §1.4 取证块） |
| oe-cal-items | edu_portal/views/calendar.xml:151 | 1 | A 工具误报 | 同上 |
| oe-cal-legend | edu_portal/views/calendar.xml:118 | 1 | A 工具误报 | 同上 |
| oe-cal-more | edu_portal/views/calendar.xml:160 | 1 | A 工具误报 | 同上 |
| oe-cal-mv | edu_portal/views/calendar.xml:141 | 1 | A 工具误报 | 同上 |
| oe-cal-nav | edu_portal/views/calendar.xml:47 | 1 | A 工具误报 | 同上 |
| oe-cal-out | edu_portal/views/calendar.xml:149 | 1 | A 工具误报 | 同上 |
| oe-chart-line | edu_portal/views/batch2.xml:848 | 1 | D 无害标记 | 同元素带 `oe-chart-card`（已定义） |
| oe-edit-btn | edu_portal/views/batch2.xml:1258 | 2 | D 无害标记 | 同元素带 `btn btn-link p-0`（Bootstrap 管） |
| oe-gb-head | edu_portal/views/batch2.xml:8 | 4 | C 整块未移植 | 成绩单页同族**只**定义了 `.oe-gb-hic/.oe-gb-page/.oe-gb-s/.oe-gb-t` |
| oe-gb-htitle | edu_portal/views/batch2.xml:10 | 4 | C 整块未移植 | 同上 |
| oe-gb-term | edu_portal/views/batch2.xml:60 | 1 | C 整块未移植 | 同上（外层另有 `card mb-3`，故仍像卡片） |
| oe-gb-term-grade | edu_portal/views/batch2.xml:71 | 1 | C 整块未移植 | 同上 |
| oe-gb-term-head | edu_portal/views/batch2.xml:61 | 1 | C 整块未移植 | 同上 |
| oe-gb-term-ic | edu_portal/views/batch2.xml:62 | 1 | C 整块未移植 | 同上 |
| oe-gb-term-meta | edu_portal/views/batch2.xml:63 | 1 | C 整块未移植 | 同上 |
| oe-gb-term-name | edu_portal/views/batch2.xml:64 | 1 | C 整块未移植 | 同上 |
| oe-gb-term-pct | edu_portal/views/batch2.xml:70 | 1 | C 整块未移植 | 同上 |
| oe-gb-term-pct--fail | edu_portal/views/batch2.xml:70 | 1 | C 整块未移植 | 同上（`--fail` 无红/绿区分样式） |
| oe-gb-term-pct--pass | edu_portal/views/batch2.xml:70 | 1 | C 整块未移植 | 同上 |
| oe-gb-term-sub | edu_portal/views/batch2.xml:65 | 1 | C 整块未移植 | 同上 |
| oe-home-blocks | edu_portal/views/batch2.xml:818 | 1 | D 无害标记 | 同元素带 `id="oe_home_blocks"`，子元素各自有类 |
| oe-kpi--assign | edu_portal/views/roles.xml:79 | 2 | **B 缺变体** | controller 生成 `--assign/--exam`，CSS **只**定义了 `.oe-kpi--courses` |
| oe-kpi--exam | edu_portal/views/roles.xml:1115 | 2 | **B 缺变体** | 同上 |
| oe-kpi-info | edu_portal/views/roles.xml:1118 | 1 | A 工具误报 | 规则在 custom_home.css，合并写法 `.oe-kpi-ic.oe-kpi-info` |
| oe-skillassess | edu_portal/views/batch1.xml:744 | 1 | D 无害标记 | 同元素带 `oe-rc-card`（已定义） |
| oe-statbox-ic--warning | edu_portal/views/evaluation.xml:112 | 1 | **B 命名不一致** | 同族定义的是 `--warn`（另有 danger/info/ok/primary/success），模板写的是 `--warning` |
| oe-study-page | edu_portal/views/study.xml:16 | 4 | D 无害标记 | 同元素带 `ux3-page`（已定义，见 ux_v3.css） |
| ux-approval-alerts | edu_portal/views/batch2.xml:944 | 1 | D 无害标记 | 同元素带 `card shadow-sm border-0 rounded-3 mb-4`（Bootstrap 管） |

### 1.4 工具本身的两个盲区（都可复现）

> **取证块（2026-10-06 读数，不得据此定位代码）**
> · calendar.xml 的内联 style 块**起始行 = 7**；
> · 合并选择器实例：`custom_addons/edu_portal/static/src/css/enterprise.css:1148`
>   （`… .oe-att-field.oe-att-col-wide{…}`）与 `custom_addons/edu_portal/static/src/css/custom_home.css:389`
>   （`… .oe-kpi-ic.oe-kpi-info{…}`）。

**盲区 1（定义面不含内联样式）**：`oe-cal-*` 这 7 个类的规则写在 `edu_portal/views/calendar.xml`
的 `<style>` 块里，而工具只把 `static/**` 当归档面 ⇒ 判成「没定义」。

**盲区 2（合并选择器被 `re.findall` 吃掉）**：复现方式 —— 直接调用工具自己的
`collect_defined()`，问 `oe-att-col-wide` 在不在集合里，答案是 `False`，而它的规则明明就在
`static/**` 里。原因是定义面的正则

```python
r"[.\"']([A-Za-z][\w-]*)[\"\'\s.:,>{[]"
```

在 `.a.b{` 上匹配掉 `.a` **连同一个 `.`** 之后，扫描位置已经越过 `b` 前面的那个点 ⇒ `.b` 再也匹配不上。
**这不是文档缺陷，是会漏报的假绿**：任何「同元素挂两个自有类」的写法都会漏掉第二个。

**两条盲区的共同后果**：工具报的 35 个里有 9 个（26%）是假的；而这 9 个恰好都是**最正常的写法**
（合并选择器、内联样式）。建议的修法（**属于工具文件，不在我的写作用域**）：
① 定义面加扫 `views/*.xml` 的 `<style>` 块；② 定义面改用 `finditer` + 零宽断言（或先按 `}` 切规则再取选择器）。

### 1.5 建议（按优先级，等校长拍）

1. **`oe-statbox-ic--warning` → 改模板为 `--warn`**（或给 CSS 补一条 `--warning` 别名）——
   一处字符串，改完「优秀」图标才有警示色。**证据：同族 6 个变体的命名规则一致，唯独模板这一个不同。**
2. **`oe-asg-btn--active` → 补一条 CSS**（或让模板复用既有 `--ghost`）—— 通知/公告切换 tab 的选中态现在是空的。
3. **`oe-kpi--assign` / `oe-kpi--exam` → 补两条 CSS**（对齐既有的 `.oe-kpi--courses`）。
4. **C 类 12 个**：是否补「学期卡片」的样式是**产品决定**（现在靠 Bootstrap 能用、只是不如旧站精致），
   我不主张顺手做——那属于「恢复旧视觉」，不是清理。
5. **D 类 10 个**：建议**保持不动**（删类名要改模板、且没有任何收益）。

---

## 2. 线索二：brand.css 的失效类名与孤儿样式（4 条全部复验属实）

| 类名 | 类型 | 判定 | 证据（取证块，2026-10-06） |
|---|---|---|---|
| `yylc-course-list` | 用了没定义 | **属实** | `edu_brand/views/pages.xml:212` 的 `<ul class="yylc-list yylc-course-list">`；全仓无任何 `.yylc-course-list` 选择器 |
| `yylc-footer-body` | 用了没定义 | **属实** | `edu_brand/views/brand_templates.xml:219` 的 `<div class="yylc-footer-body">`；全仓无选择器 |
| `yylc-lang-btn` | 定义了没人用 | **属实** | 定义在 brand.css（本轮删除前）；渲染页 HTML 里 0 次 |
| `yylc-lang-float` | 定义了没人用 | **属实** | 同上；语言切换控件 2026-09-12 已按产品裁定撤除（`brand_templates.xml:241` 起的长注释） |

**处置与理由**

- **孤儿样式 2 条 → 删**（本轮已做，在写作用域内）。理由：**零视觉风险**（无元素携带这 2 个类，
  在官网 + 门户共 5 个页面实测 0 次命中），且保留它们会让人误以为「站上有语言切换」。
  删除时**留了墓碑注释**：写明撤除是产品裁定、不是本次清理，并指回 `brand_templates.xml` 的恢复步骤与 git 历史。
- **失效类名 2 个 → 未删，附一行改法**。理由：**它们的删除点在 `views/*.xml`，不在我的写作用域**
  （本次写作用域只有本文 + brand.css）。我**没有**选择「补样式」——那需要先知道它们**本来想表达什么**，
  而旧站样式表从未进本仓（`reference/`、`scrape/` 里也没有对应 CSS），**补样式等于编造视觉 = 改产品行为**，
  违反本次铁律 ②。建议的改法（一行，谁写作用域谁做）：
  - `pages.xml`：`<ul class="yylc-list yylc-course-list">` → `<ul class="yylc-list">`（`yylc-list` 已定义，承载全部现有视觉）；
  - `brand_templates.xml`：`<div class="yylc-footer-body">` → `<div>`（页脚布局由 `.yylc-footer-inner` 等已定义类承载）。

---

## 3. 线索三：依赖图（环 + 未声明依赖）

### 3.1 实测的仓内依赖图（2026-10-06，从各 `__manifest__.py` 的 `depends` 解析）

```
edu_brand    → website, theme_web_openeducat, auth_totp_portal, digest   （底层，无 edu_* 依赖）
edu_nav      → base
edu_zh       → base
edu_apply    → website, mail, openeducat_core, openeducat_admission
edu_public   → website, openeducat_core, openeducat_exam, openeducat_library
edu_schedule → openeducat_timetable, website, edu_brand, calendar
edu_portal   → portal, website, openeducat_{core,timetable,attendance,assignment,exam,library,parent},
               edu_apply, edu_brand, edu_schedule
edu_life     → website, mail, openeducat_core, edu_portal
edu_quiz     → openeducat_core, openeducat_exam, mail, edu_portal
edu_assess   → edu_portal
edu_tg_bind  → edu_portal
edu_telegram → openeducat_{core,exam,library,fees,attendance}（退役）
```

**环的判定：无环。** 用 DFS 着色在仓内 12 个 `edu_*` 子图上跑（复核命令见 §7.3）：
`edu_portal → edu_schedule → edu_brand` 是一条链而不是环（`edu_brand` 谁也不依赖）。
校长问的「edu_portal 与 edu_schedule 有没有环」——**现在没有**，而且**方向是固定的**：
`edu_portal` 依赖 `edu_schedule`，反向依赖会成环，因此 `edu_schedule` **永远不能**声明 `edu_portal`。

### 3.2 跨模块**模板**引用对账（这是「靠渲染期侥幸能用」的原发地）

逐条扫 `t-call="<模块>."` 与 `inherit_id="<模块>."`，共 **8 条跨模块引用，全部已在 depends 里声明**：

| 来源 | 类型 | 目标 | depends 是否声明 |
|---|---|---|---|
| edu_assess | t-call / inherit_id | edu_portal | ✅ |
| edu_life | t-call | edu_portal | ✅ |
| edu_quiz | t-call | edu_portal | ✅ |
| edu_portal | t-call / inherit_id | edu_brand | ✅ |
| edu_portal | inherit_id | edu_apply | ✅ |
| edu_schedule | t-call | edu_brand | ✅ |

⇒ **§6 第 16 条（2026-10-02 立）的收口是生效的**：共用 partial 下沉到 `edu_brand` 之后，
`edu_schedule` 与 `edu_life` 都不再跨层引用 `edu_portal` 的模板。**这一类问题当前为 0。**

### 3.3 跨模块**模型**引用对账（真正的存量在这里）

同一把尺子换成模型：扫 `_inherit` / `env['x']` / `comodel_name`，再看模型定义在哪个模块。

| 来源 | 引用的模型 | 目标模块 | depends | 有没有守卫 | 判定 |
|---|---|---|---|---|---|
| edu_brand | `edu.deadline` | edu_portal | ❌ | **无** | ⛔ **无守卫的未声明依赖** |
| edu_public | `edu.job.posting` | edu_portal | ❌ | **无** | ⛔ **无守卫的未声明依赖** |
| edu_portal | `edu.checkin.record` / `edu.journal.entry` | edu_life | ❌（且**不可能**：会成环） | ✅ `try/except` 兜 0 | ✅ 有意软引用 |
| edu_portal | `edu.quiz.attempt` | edu_quiz | ❌（同上） | ✅ 注释明写「未安装则静默跳过」 | ✅ 有意软引用 |
| edu_portal | `edu.telegram.outbox` | edu_telegram | ❌ | ✅ `try/except` + 告警 | ✅ 有意软引用 |
| edu_schedule | `edu.audit.log` / `edu.message` | edu_portal | ❌（会成环） | ✅ `try/except` | ✅ 有意软引用 |
| edu_schedule | `edu.notify.pref` | edu_portal | ❌（会成环） | ✅ `if 'edu.notify.pref' in self.env` | ✅ 有意软引用 |
| edu_schedule | `edu.telegram.outbox` | edu_telegram | ❌ | ✅ `try/except` | ✅ 有意软引用 |
| edu_public | `edu.alumni.job` | edu_portal | ❌ | ✅ `if '…' in request.env` | ✅ 有意软引用 |

**两处真问题（都无守卫、都在公开路由上）**

1. `custom_addons/edu_brand/views/pages.xml` 的 `edu_admissions` 模板里有一句
   `t-out="request.env['edu.deadline'].sudo().get_cn('edu.apply.deadline')"`。
   `edu.deadline` 定义在 `edu_portal/models/registration.py`；该模板**通篇没有 `t-if` 守卫**（模板内到该行守卫数 = 0）。
   ⇒ **只要同时不装 edu_portal，/admissions 会直接 QWeb 报错**。
   ⚠ 而且这里**不能靠加 depends 解决**：`edu_portal` 的 depends **含 `edu_brand`** ⇒ 反向声明会成环。
   正解只有两条：**加守卫**（`t-if` 包一层 / 或把取值挪到一个 try 里），或**把该值下沉到低层模块**（与 §6 第 16 条同一个套路）。
2. `custom_addons/edu_public/controllers/main.py` 的 `campus_jobs`（`auth='public'`，路由 `/campus/jobs`）
   直接 `request.env['edu.job.posting']`，无守卫。
   ⇒ 这里**可以**直接补 depends（`edu_portal` 的 depends 里**没有** `edu_public`，不成环），也可以按既有风格加守卫。

> **结论**：校长问的「引用未声明依赖、靠渲染期侥幸能用」**在模板层已经清干净（0 条）**，
> 但在**模型层还有 2 条**，且两条都在**公开可访问**的页面上 —— 建议优先处理（改法都在一句话的量级）。

---

## 4. 线索四：brand.css 的色值字面量 vs 令牌纪律

### 4.1 纪律原文（`edu_brand/static/src/scss/brand_tokens.scss` 头部「纪律」块）

> 1. 其它任何文件不得再写色值字面量；引用一律 `var(--x)` 或 `$x`。
> 2. 每个 `--*-rgb` 必须有同名 `--x` 基色…  3. 页面/组件级覆盖必须降一级作用域…

### 4.2 可安全替换的（本轮已换）

**判据**：该字面量的值**与某个已注册令牌逐字节相等**（脚本里对每条映射做了 `assert`，
不相等就拒绝替换）⇒ **替换是值等价的，零视觉变化**。

| 字面量 | 出现处数（替换前） | 换成 | 依据令牌 |
|---|---|---|---|
| `#c8a870` | 6 | `var(--gold-500)` | `$gold-500` |
| `#e7d7b8` | 6 | `var(--gold-100)` | `$gold-100` |
| `#836a42` | 4 | `var(--gold-ink)` | `$gold-ink` |
| `#fff` | 8 | `var(--white)` | `$white` |
| `rgba(200,168,112,…)` | 32 | `rgba(var(--gold-500-rgb), …)` | `--gold-500-rgb` |
| `rgba(255,255,255,…)` | 6 | `rgba(var(--white-rgb), …)` | `--white-rgb` |

**脚本实际改动 = 56 处**（hex 23 + rgba 通道 33）。上表是「字面量种类 × 出现处」的**统计口径**
（它同时数进了注释里的字面量和随后被删掉的孤儿样式段），所以合计大于 56；
**唯一权威口径是 §5 的复核命令与实际 diff，不是这张表**。

### 4.3 **不可**替换的 27 种（保留 + 登记，别硬换）

这把尺子能安全替换的前提是「令牌表里已有同值项」。实测**旧项目的纸/墨/金第二套色板不在 v4 令牌表里**，
共 27 种字面量无同值令牌，**一律保留**（硬换成近似令牌会**真的改颜色**）：

> `#171512`(7) `#241d10`(5) `#fffdf9`(5) `#70675e`(5) `#8a6d3b`(5) `#3d3325`(4) `#f7f2eb`(3) `#26384d`(3)
> `#f3ede1`(3) `#d9d2c5`(3) `#6f5630`(3) `#7c6338`(2) `#403a33`(2) `#e5ded4`(1) `#41564f`(1) `#12100e`(1)
> `#9f8050`(1) `#8f867a`(1) `#fdfaf6`(1) `#f3ece1`(1) `rgba(23,21,18,…)`(6) `rgba(243,237,225,…)`(4)
> `rgba(159,128,80,…)`(3) `rgba(138,109,59,…)`(3) `rgba(255,253,249,…)`(1) `rgba(61,51,37,…)`(1)

**其中一条要单独点名（不是字面量问题，是命名冲突）**：brand.css 在 `.yylc-home` 里写
`--border: #e5ded4`，而 `:root` 的保留名 `--border` 是 `#E3E9F2`（蓝灰）。
结果是**同一个变量名在两处含义不同**：`.yylc-home` 内的元素拿到暖纸色，而 `.yylc-footer`、
`.yylc-article-block`、`.yylc-journal-thumb` 这些**不在 `.yylc-home` 作用域内**的规则用 `var(--border)`
拿到的是全局蓝灰。改法是**给纸色另起名**（如 `--yylc-border`），但这会改动多处、且要人眼核对，
**超出「小件」范围，本轮只登记不动**。

---

## 5. 本次实际改动清单（含验证读数）

### 5.1 改了什么

**文件：`custom_addons/edu_brand/static/src/css/brand.css`（唯一改动的代码文件）**

1. **删除 2 条孤儿样式**（`.yylc-lang-float` / `.yylc-lang-btn` 及其 media query），原位留墓碑注释
   （写明「撤除是 2026-09-12 的产品裁定 + 恢复步骤在 brand_templates.xml + git 历史里有完整规则」）；
2. **56 处色值字面量 → 同值令牌**（值等价的机械替换，注释里的字面量一律没动，含 t111/t112 的历史取证注释）。

### 5.2 验证读数（都是量出来的）

| 验证项 | 读数 | 说明 |
|---|---|---|
| 令牌在运行期真有值 | `--brand-action=#0C6DD7`、`--gold-500=#C8A870`、`--gold-100=#E7D7B8`、`--gold-ink=#836A42`、`--white=#FFFFFF`、`--gold-500-rgb=200, 168, 112`、`--white-rgb=255, 255, 255` | 若某个令牌不存在，`var()` 会让整条声明失效 —— 故必须实测 |
| 代表元素 computed 值 | `.yylc-card` 边框 `rgba(200,168,112,0.2)`、底色 `rgba(255,255,255,0.6)`；`.yylc-card-ic` 底 `rgba(200,168,112,0.16)`；`.yylc-footer-en` 色 `rgb(200,168,112)`；`.yylc-apply-btn` 底 `rgb(138,109,59)` | 与替换前逐值相同 |
| **页面像素**（改前/改后全页截图 MD5） | `/about` `62fed4ac…`、`/programs` `03c2be3e…`、`/login` `a1fe5c82…`、`/journal` `cbfb2e66…` **四页完全相同**；`/` 首页在**冻结动画**（`reduced_motion=reduce`）后同为 `a06df2a7…` | 首页有 `yylc-kenburns` 动画，**默认动效下截图本身不可重复**（实测连拍 3 次得 3 个 MD5）⇒ 必须先冻结动画，否则这条验证是**假红** |
| 升级 | `bash scripts/safe_upgrade.sh edu_brand` → **EXIT=0**（共跑 3 次：改前基线、还原 HEAD 版、装回新版） | CSS 改动必须重启 web 才生效（本仓 §「静态资产新鲜度」） |
| 页面无报错 | 5 个公开页 `pageErrors` 全为 0 | |

> **方法学备注**：这条「值等价替换」的证明链是三层 —— ①替换脚本对每条映射 `assert` 字面量 == 令牌值（构造性证明）；
> ②运行期实测令牌解析值；③整页截图 MD5 相同（端到端）。第 ③ 层一开始在首页报了「不同」，
> 追下去发现是**动画导致的截图不可重复**，换用冻结动画后一致 —— 差一点就把「量具噪声」当成「改动有副作用」。

---

## 6. 未做 / 待裁定（明确交回校长与队长）

| 项 | 为什么没做 | 建议 |
|---|---|---|
| 35 个类名一个没动 | 队长明确要求「先给结论，改不改等校长拍」 | §1.5 的 4 条 B 类优先 |
| 2 个失效类名的删除 | 删除点在 `edu_brand/views/*.xml`，**超出本次写作用域** | 按 §2 的两行改法指派人做 |
| `--border` 同名不同值 | 涉及多处选择器与视觉核对，不是「小件」 | 另开小任务（§4.3 末） |
| 2 处无守卫的未声明依赖 | 要动 `__manifest__.py` 或控制器/模板，**超出写作用域** | §3.3 的两条处置 |
| 修工具的两个扫描盲区 | `scripts/find_undefined_classes.py` 不在写作用域 | §1.4 的两条修法 |
| 27 种无同值令牌的字面量 | 硬换会**真的改色**；要么给令牌表补新令牌（产品决定），要么保留 | 保留（现状可接受） |

---

## 7. 复核命令（全部可复跑，2026-10-06 环境）

```bash
cd /Users/qwe/Documents/文件大总管/10-项目/教务系统网站新架构

# 7.1 线索一：35 个类名
python3 scripts/find_undefined_classes.py            # 期望 RESULT=FOUND（35 个）

# 7.2 线索一：把「合并选择器」那两只钉死（工具自己的函数说 False，而规则就在文件里）
python3 - <<'PY'
import importlib.util, re
spec = importlib.util.spec_from_file_location('fuc', 'scripts/find_undefined_classes.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
defined, n = m.collect_defined()
for name in ('oe-att-col-wide', 'oe-kpi-info'):
    print(name, 'in defined set?', name in defined)     # 期望 False（=工具漏了）
txt = open('custom_addons/edu_portal/static/src/css/enterprise.css').read()
print('文件里其实有规则吗：', bool(re.search(r'\.oe-att-col-wide(?![\w-])', txt)))   # 期望 True
PY

# 7.3 线索三：依赖图 / 环 / 未声明依赖（三个脚本都在 /tmp，判据见本文件 §3）
python3 /tmp/narrow_a_deps.py          # depends 拓扑 + 环 + t-call/inherit_id 对账
python3 /tmp/narrow_a_modelrefs.py     # 模型级引用对账（含能否变红的自证）

# 7.4 线索四：色值字面量对账
python3 /tmp/narrow_a_colors3.py       # 哪些可替换 / 哪些没有同值令牌

# 7.5 §5 的三层验证（令牌解析 + computed + 像素）
python3 /tmp/narrow_a_verify.py        # 令牌值、computed、5 页 MD5
python3 /tmp/narrow_a_determinism.py   # 首页动画导致截图不可重复的实测（先看这个再看上面那条）
```

> ⚠ `/tmp` 里的 4 个脚本是**本次审计的一次性取证脚本**，未入库；判据与原文都写在本文件里，
> 需要长期复跑时应把它们移进 `scripts/` 并接进 `check_all.sh`（本仓纪律：门禁必须同时登记在链上）。
