# Odoo 19 三层主题机制与同类教务系统配色实践（铁律 0 调研）

> 任务：t1 · 调研员 study-eng · 2026-09-15（attempt 2）
> 上游依据：[`docs/audit/ui-color-audit-2026-09-15.md`](../audit/ui-color-audit-2026-09-15.md)（Tabbit 真机取色）、[`docs/audit/ui-color-raw-2026-09-15.json`](../audit/ui-color-raw-2026-09-15.json)
> 服务对象：t2《永约学坊统一色板规范 v4（路线 A）》定稿；t3–t8 实现
> **本文件只做调研**：不含设计决策、不改任何代码。每条结论带一手来源；无法一手的进 §8「未验证」。

---

## 0. 取证基准（先看这段，再看任何结论）

| 项 | 值 |
|---|---|
| Odoo 上游 | `odoo/odoo` 分支 `19.0`，HEAD = `65dae4abd4a743e1e1b9a7e9b0751af0815908a7`（author date 2026-07-14 / committer date 2026-09-14，取自 GitHub branches API） |
| 引文格式 | 本文行号按上述 commit：`https://github.com/odoo/odoo/blob/19.0/<path>#L<n>`（纯文本等价：`https://raw.githubusercontent.com/odoo/odoo/19.0/<path>`） |
| 本机运行态（实测） | `docker exec edu19-clone-web-1 odoo --version` → `Odoo Server 19.0-20260817`；镜像 `odoo:19`。与上游 HEAD 差约 1 个月 |
| ⚠ 行号会漂移 | 依据 `docs/research/README.md` 收录规范第 4 条：**实施时以本机版本为准** |
| ⚠ 本机容器当前不可用 | 调研期间 `docker ps` 已无 `edu19-clone-web-1`（只剩 `edu19-clone-db-1`，且状态 `unhealthy`）。t8/t9 跑本地回归前必须先 `docker compose up -d`，并按 `docs/code-map.md` §2 三步探活（无升级锁 / Up > 30s / 带 cookie jar 得 200-303），否则是假红 |

**证据强度图例**：✅ 一手源码（带行号） · 🌐 官方文档 · 🧪 本机/现网实测 · ⚠ 未验证（**不得当结论用**）

---

## 1. 一句话结论（TL;DR）

1. **网站色板没有专用表/字段**：用户在网站构建器里调的色板，落库形态是 **`ir.attachment` + `ir.asset`** 两条记录（附件里是 SCSS 变量文件，asset 是 `replace` 指令的替换关系）；程序化入口是 `env['website.assets'].make_scss_customization(url, values)`（✅ `addons/website/models/assets.py:189`）。
2. **`--color-palettes-name` / `--has-customized-colors` 不是可写字段**，而是 SCSS 编译期**派生**出来的 CSS 变量（✅ `addons/website/static/src/scss/website.scss:159,161`）。想改它们只能改上游变量（调色板名 / 用户调色板 map）。
3. **后台「只覆盖了一部分」是三个独立原因叠加**：
   - ① **map 快照**：`primary_variables.scss` 把品牌色折算进 `$o-btns-bs-override` 等 map（✅ `:231-289`）；
   - ② **变量快照**：`web/static/src/**/*.variables.scss`（如 `navbar.variables.scss:7` 的 `$o-navbar-background: $o-brand-odoo !default`）在**模块变量文件之前**编译，提前把默认紫定格；
   - ③ **模板字面量**：`#71639e`/`#714B67` 有一部分是 **QWeb 模板里的硬编码**（✅ `addons/web/views/webclient_templates.xml:279,352-354`），SCSS 覆盖**永远够不到**。
4. **Bootstrap 5.3 的 `--bs-primary` 在 Odoo 里根本不存在**：Odoo 把 `$variable-prefix` 设为空串（✅ `addons/web/static/src/scss/bootstrap_overridden.scss:51`、`addons/website/static/src/scss/bootstrap_overridden.scss:29`），所以实际变量名是 `--primary` / `--primary-rgb` / `--link-color-rgb`。审计里「`--bs-primary` 惰性」的一手现象，机制上等于「**名字找错了 + 这些变量是编译期快照**」。
5. **同类系统全都是「单一主色 + 派生 + 出厂默认值」的令牌模型**：Moodle 用 `$theme-colours` map（🌐 官方组件库文档给了完整默认值）；Canvas 用命名令牌 Theme Editor（🌐 官方 KB 给了 `Primary Brand Color` 默认 `#008ee2` 等 20+ 令牌）。**没有任何一家是把两套设计语言并存的。**
6. **OCA 没有可直接装的配色主题模块**：`OCA/server-brand@19.0` 存在但全是**去品牌化/去企业版入口**类模块（不含配色主题），`OCA/website-themes@19.0` **只有仓库骨架、没有模块**，`OCA/website@19.0` 是 10 个 snippet/可见性模块。→ 配色必须自研；但「模板字面量必须单独清」这一点，`server-brand` 的模块划分方式可以直接抄（§6）。

---

## 2. ① 网站色板：存在哪张表 / 字段，程序化怎么设

### 2.1 一套调色板的构成（官方定义）

🌐 Odoo 19 官方文档 *Theming* → *Colors*（源码 RST：`https://www.odoo.com/documentation/19.0/_sources/developer/howtos/website_themes/theming.rst.txt`；渲染页 `.../developer/howtos/website_themes/theming.html`）原文列出五色语义：

| 变量 | 官方语义 |
|---|---|
| `o-color-1` | Primary |
| `o-color-2` | Secondary |
| `o-color-3` | Extra (Light) |
| `o-color-4` | Whitish |
| `o-color-5` | Blackish |

同一页还写明：由这 5 色**自动派生 5 套色彩组合（color combinations）**，每套含 background / text / headings / links / primary buttons / secondary buttons；覆盖用 `o-cc` 前缀（如 `o-cc1-link`）。
→ 这正是审计里 `--o-color-1..5`、`--o-cc3-bg`、`--o-cc1-btn-primary` 的来源。

### 2.2 静态侧：调色板定义在 SCSS map 里（✅ 源码）

| 变量 | 位置 | 作用 |
|---|---|---|
| `$o-color-palettes` | `addons/website/static/src/scss/primary_variables.scss:61`（`base-1`/`base-2` 在 `:63,67` 被并入） | 全部出厂 / 自定义调色板 |
| `$o-selected-color-palettes-names` | 同上 `:2043` | 网站构建器**下拉里能被选中的**调色板清单 |
| `$o-user-color-palette` / `$o-user-gray-color-palette` / `$o-user-theme-color-palette` | 同上 `:28,33,38`（`!default` 空 map） | 用户覆盖值 |
| `$o-user-website-values` | `addons/website/static/src/scss/options/user_values.scss` | 用户「网站值」（含 `color-palettes-name`） |
| `$o-base-color-palette` | `primary_variables.scss:6` | 调色板的非颜色属性（menu/footer/copyright 用第几套 cc） |

🌐 **官方推荐的主题级写法**（文档同页）：在自己的 `primary_variables.scss` 里 `$o-color-palettes: map-merge($o-color-palettes, ('airproof': (...)))`，再 `$o-selected-color-palettes-names: append(..., 'airproof')`，最后用 `$o-website-values-palettes: (('color-palettes-name': 'airproof'))` 选定。

### 2.3 用户侧：**不存在调色板表** —— 存成 `ir.attachment` + `ir.asset`（✅ 源码）

核心方法：`website.assets.make_scss_customization(url, values)` → ✅ `addons/website/models/assets.py:189`。它做两件事：

1. **写附件**：`ir.attachment.create({ name, type=binary, mimetype='text/scss', datas=base64(...), url='/_custom/<bundle_xmlid><原路径>', website_id })`（✅ `assets.py:71-79`）；URL 规则来自 `_make_custom_asset_url()`（✅ `assets.py:186`：`return f'/_custom/{bundle_xmlid}{url}'`）；`website_id` 由 `_add_website_id()` 注入（✅ `assets.py:360-364`）。
2. **写 asset 替换关系**：`ir.asset.create({ path: custom_url, target: 原 url, directive: 'replace', website_id, ... })`（✅ `assets.py:82-97`）。

写入方式是把键值对**插进目标 SCSS 文件里带 `// -- hook --` 注释的 map**（✅ `assets.py:190-204` docstring）。被插入的四个「钩子文件」都是 4~5 行常量：

| 钩子文件 | 写入的 SCSS map |
|---|---|
| `website/static/src/scss/options/colors/user_color_palette.scss` | `$o-user-color-palette`（15 色主调色板覆盖） |
| `.../options/colors/user_gray_color_palette.scss` | `$o-user-gray-color-palette` |
| `.../options/colors/user_theme_color_palette.scss` | `$o-user-theme-color-palette`（success/info/warning/danger/alpha..epsilon） |
| `.../options/user_values.scss` | `$o-user-website-values`（**`color-palettes-name` 就在这里**） |

✅ 佐证：`theme_models.py:258-275` 的 `_reset_default_config()` 把 `'color-palettes-name': 'null'` 和 `'color-palettes-number': 'null'` 一起写进 `user_values.scss` —— 即「换调色板」在实现上就是改这条 SCSS 记录。
**换调色板时的联动**（✅ `assets.py:206-224`）：写 `color-palettes-name` 会先 `reset_asset()` 掉主/灰两个用户调色板文件，并把 4 个主题色 + 5 个 `o-cc*-bg-gradient` 置 `null`。

**删除回调**：`reset_asset(url, bundle)`（✅ `assets.py:21-37`）删同一 URL 的 `ir.attachment` 与 `ir.asset`。

> 结论（对本项目最有用的一条）：**要程序化设置网站品牌色，正确入口不是改配置项、不是改 `ir.config_parameter`，而是 `env['website.assets'].make_scss_customization('/website/static/src/scss/options/colors/user_color_palette.scss', {...})`（改调色板值）或 `.../user_values.scss`（改调色板名 / 其它网站值）**，随后 `registry.clear_cache('assets')` 由框架完成（✅ `assets.py:67`）。
> 另一条同样重要：**这是「用户自定义层」，会盖过主题的 SCSS**（见 §2.4 的合并顺序）——所以装了主题也可能被历史用户自定义值压住，验收时要先确认这三份自定义附件是否为空。

### 2.4 编译期：用户调色板怎么变成 `user-palette`，以及两个派生 CSS 变量

✅ `addons/website/static/src/scss/secondary_variables.scss`：

| 行 | 逻辑 |
|---|---|
| `:87-88` | `$-color-palette-number := o-website-value('color-palettes-number')`；`$-color-palette-name := o-website-value('color-palettes-name')`（读的就是 §2.3 的用户值） |
| `:95-103` | 老库兼容：只有 number 没有 name 时，用 `$o-color-palettes-compatibility-indexes` 反查名字 |
| `:138-140` | `$-actual-user-color-palette := map-merge(出厂调色板, $o-user-color-palette)` |
| `:164` | 结果作为 `'user-palette'` 追加进 `$o-color-palettes` |
| `:211-214` | **把 `$o-color-palette-name` 等三个名字都切成 `'user-palette'`**，同时把原名字存进 `$o-original-color-palette-name` |
| `:125-130` | `$o-has-customized-colors := not not (用户调色板非空 或 主题色 success/info/warning/danger 被改)` |

✅ 打印成 CSS 变量的地方（`addons/website/static/src/scss/website.scss` 的 `:root` 块，`:20-170`）：

`@include print-variable('color-palettes-name', $o-original-color-palette-name);`  ← `:159`
`@include print-variable('has-customized-colors', $o-has-customized-colors);`    ← `:161`
`@include print-variable('custom-colors', $custom-colors);`                      ← `:168`

→ 审计在 `/apply` 读到的 `--color-palettes-name: 'base-1'` + `--has-customized-colors: 'false'`，**读的就是这两个派生变量**：意思是「选了出厂 base-1 调色板，且没有任何用户覆盖」。**这恰好证明根因①：网站色板从未被自定义过。**

### 2.5 网站上的链接色/主色是调色板的函数（✅ 源码）

`addons/website/static/src/scss/bootstrap_overridden.scss`：

| 行 | 内容 |
|---|---|
| `:73-74` | `$body-bg: o-color('o-cc1-bg')`；`$body-color: o-color('o-cc1-text')` |
| `:83-86` | `$link-color: auto-contrast(o-color('o-cc1-link') 或 primary, $body-bg)`；hover = darken 15% 再过 `auto-contrast` |
| `:109` | `$component-active-bg: o-color('o-cc1-btn-primary')` |

→ 审计里官网导航 logo 的 `#0F34C3`（`--link-color`）就是 `auto-contrast()` 对 `o-cc1-link` 自动加深的结果：**它不是谁手写的，是调色板 + 对比度算法算出来的**。它跟着调色板走（不是跟着 `$o-community-color` 走）。

---

## 3. ② 后端「只覆盖了一部分」的完整机制

`custom_addons/edu_brand/static/src/scss/backend_variables.scss` 的顶部注释已经写对了一半（map 快照）；本节把它补全成**三个互不相同的机制**，并给出本项目**漏掉的那一环**。

### 3.1 机制 A：**map 快照**（注释里已写对）

✅ `addons/web/static/src/scss/primary_variables.scss`：

| 行 | 内容 |
|---|---|
| `:73-78` | `$o-community-color: #71639e !default;` `$o-enterprise-color: #714B67 !default;` `$o-brand-odoo: $o-community-color !default;` `$o-brand-primary: $o-community-color !default;` |
| `:83-87` | `$o-action: $o-brand-primary`；`$o-success: #28a745`、`$o-warning: #ffac00`、`$o-danger: #dc3545`（Bootstrap 5 出厂状态色） |
| `:123` | `$o-main-link-color: darken($o-brand-primary, 5%) !default;` |
| `:132-134` | `$o-component-active-color/bg/border`（bg 是 `mix($o-action, ...)`） |
| `:145,:150` | `$o-text-colors-custom` / `$o-bg-colors-custom`（`action` 项写死当前值） |
| `:231-272` | `$o-btns-bs-override`：`map-merge((primary/secondary/light 三套完整状态…), $o-btns-bs-override)` |
| `:274-289` | `$o-btns-bs-outline-override` 同理 |

这些 map 里的值是**在 `primary_variables.scss` 被编译的那一刻**从 `$o-brand-primary` 求值并固定的。
**顺序合同（关键）**：merge 形式是 `map-merge(默认值, $o-btns-bs-override)`，所以**模块只要在「本文件之后」把自己那份 merge 进去就能赢**。这正是 `backend_variables.scss:20-32` 现在做的事 —— 所以「主按钮」这类**已经被显式重做过的**部分确实生效了。
**反例**：没有对应的显式重做，就定格在默认值。

### 3.2 机制 B：**变量快照**（本项目漏掉的一环，直接对应审计的 `#71639E`）

✅ `addons/web/static/src/webclient/navbar/navbar.variables.scss:7-8`：

`$o-navbar-background: $o-brand-odoo !default;`
`$o-navbar-border-bottom: 1px solid darken($o-brand-odoo, 10%) !default;`

✅ 消费方 `addons/web/static/src/webclient/navbar/navbar.scss:147-155`：

`.o_nav_entry, .dropdown-toggle:not(.o-dropdown-toggle-custo) { ... background: var(--NavBar-entry-backgroundColor, #{$o-navbar-background}); }`

**为什么它拿不到新值**：`navbar.variables.scss` 属于 `web._assets_primary_variables`，且是被 **glob** 收进去的：

✅ `addons/web/__manifest__.py:376-379`：

`'web._assets_primary_variables': [`
`    'web/static/src/scss/primary_variables.scss',`
`    'web/static/src/**/*.variables.scss',`
`],`

而模块追加的文件排在 **web 自己的文件之后**（见 §3.4 的顺序证明）。于是执行序是：

`web/static/src/scss/primary_variables.scss`（此时 `$o-brand-odoo` = 默认紫 `#71639e`）
`→ web/static/src/**/*.variables.scss`（**`$o-navbar-background` 在这里被定格成 `#71639e`**）
`→ edu_brand/.../backend_variables.scss`（此时才把 `$o-brand-odoo` 改成 `#0E7BF2`，**但 `$o-navbar-background` 已经算完了**）

→ **`$o-navbar-background` 必须被模块再赋值一次**，否则导航栏下拉类元素永远是 `#71639E`。这与审计 §2 根因③的一手读数 **完全吻合**（`button.o-dropdown.dropdown-toggle` = `#71639E`，且全页只此 1 处）。
→ 同一机制还影响所有名字里带 `-variables.scss` 的派生变量（例如 `$o-navbar-border-bottom`）；**修法一律是「按名字再赋一次值」，而不是只改根变量。**

### 3.3 机制 C：**QWeb 模板里的字面量**（SCSS 永远够不到）

✅ `addons/web/views/webclient_templates.xml`：

| 行 | 内容 | 出现场景 |
|---|---|---|
| `:279` | `<meta name="theme-color" content="#71639e"/>` | `web.webclient_bootstrap` —— **每一个后台页面** |
| `:352-354` | `background-color: #714B67; color:#FFFFFF; border: 1px solid #714B67;` | 离线页（service worker fallback）的内联 `<style>` |

🧪 本机旁证：仓库里抓取的现网页面 `reference/apps_menu_target.html`、`reference/roles/faculty/my__home.html` 里能直接 grep 到 `<meta name="theme-color" content="#71639e">` / `"#714B67"`（后者是门户/website layout 那一条）。
→ **这一处必须靠视图继承（xpath 替换模板）或 CSS 覆盖 `[content]` 之外的手段解决；改 SCSS 无效。**

### 3.4 顺序证明：Odoo 19 资产包的编译顺序合同（✅ 一手源码）

✅ `odoo/addons/base/models/ir_asset.py`：

| 行 | 内容 |
|---|---|
| `:184-197` `_fill_asset_paths()` | ① 先应用 `sequence < 16` 的 `ir.asset` 记录 → ② **按 addons 拓扑序遍历所有 manifest 的 assets 声明** → ③ 再应用 `sequence >= 16` 的 `ir.asset` 记录 |
| `:212-214` | `if directive == INCLUDE_DIRECTIVE: self._fill_asset_paths(path_def, ...)` —— **`('include', X)` 是递归内联，把 X 的文件并进同一列表**，所以变量 bundle 的文件与被 include 的 bundle 在**同一次 SCSS 编译**里 |
| `:14` | `DEFAULT_SEQUENCE = 16` |
| `:287-306` | `_topological_sort()`：按 addons 依赖广度拓扑排序 |

推论（**这就是「顺序合同」**）：
1. `web.assets_backend` → `('include', 'web._assets_helpers')` → `('include', 'web._assets_primary_variables')`，全部**内联进一个编译单元**（✅ `addons/web/__manifest__.py:49-58,383-393`）。
2. manifest 声明按**模块拓扑序**展开：`web` 先、依赖它的模块后 → **本仓库 `edu_brand` 的变量文件一定排在 web 自己的变量文件之后**（✅ 本仓 `custom_addons/edu_brand/__manifest__.py:32-34` 用的是官方文档指定的 `web._assets_primary_variables`，位置正确）。
3. 因此：**「根变量赋值」必然晚于「web 的派生快照」** → 想让派生变量听话，只能显式重做（机制 A）或按名字再赋值（机制 B）。

🌐 官方文档对模块的唯一要求也是这个 bundle（*Theming → Odoo variables*）：「create a `primary_variables.scss` file and add it to the `_assets_primary_variables` bundle」，manifest 示例 `'web._assets_primary_variables': [...]`。文档同时提示 Bootstrap 变量要放 `web._assets_frontend_helpers`（配 `('prepend', ...)`），并**警告不要覆盖「依赖 Odoo 变量的 Bootstrap 变量」**——这正是机制 A/B 的另一种表述。

### 3.5 审计里 `#714B67` 的真正来源：**本项目自己的硬编码**（🧪 本机 grep）

审计 `docs/audit/ui-color-raw-2026-09-15.json` 的 `/odoo/contacts` 页底色里，`rgb(113,75,103)`（`#714B67`）**恰好 1 处**。本机全量 grep（`custom_addons/`）得到 5 处命中，其中**唯一出现在后台页面上的**是：

| 文件:行 | 内容 |
|---|---|
| `custom_addons/edu_portal/static/src/js/apps_panel_chip.js:18` | 往 `.o_main_navbar` 里 `appendChild` 一个 `<a id="yy-apps-chip">`，内联样式 `background:#714B67; color:#fff` |
| `custom_addons/edu_portal/controllers/batch2.py:434` | `'student/profile': ('fa-user-circle', '#714B67')`（门户卡片图标色） |
| `custom_addons/edu_portal/views/register.xml:11` | `<h2 class="fw-bold" style="color:#714B67;">注册账号</h2>` |
| `custom_addons/edu_portal/views/evaluation.xml:344-345` | canvas `fillStyle='rgba(113,75,103,.35)'` / `strokeStyle='#714B67'` |
| `custom_addons/edu_brand/static/src/scss/backend_variables.scss:2` | 仅注释 |

→ **后台那一处 `#714B67` 极可能是我们自己的 `apps_panel_chip.js`（后台每个页面都会注入的 `<a>`）**，即「Odoo 原厂残留」其实是**自伤**。⚠ 证据强度：元素级对应关系为**推断**（审计原始数据只记了聚合计数，没有选择器），需真机点一次确认（见 §8）。
→ **但无论如何，`#71639E`（导航栏下拉按钮）是 Odoo 原厂值，机制见 §3.2；而 `backend_b11.css` 只硬覆盖了「列表主按钮」等局部**，这解释了「一屏之内两种主按钮蓝」。

---

## 4. ③ Bootstrap 5.3 的 `--link-color-rgb` / `--bs-primary` 与 `--o-*` 的关系

### 4.1 变量名：`--bs-*` 前缀在 Odoo 里是**空串**（✅ 源码）

| 位置 | 内容 |
|---|---|
| `addons/web/static/src/scss/bootstrap_overridden.scss:51` | `$variable-prefix: '' !default;`（该文件由 `web._assets_backend_helpers` 收录 → **后台确定为空前缀**；前端对应文件是 `bootstrap_overridden_frontend.scss`，其中**未出现** `variable-prefix` → 前端是否也空前缀**未验证**，见 §8） |
| `addons/website/static/src/scss/bootstrap_overridden.scss:29` | `$variable-prefix: '' !default;`（网站再确认一次） |

→ 所以 Odoo 输出的 CSS 变量是 **`--primary`、`--primary-rgb`、`--link-color`、`--link-color-rgb`、`--body-bg`…**，**没有 `--bs-` 前缀**。审计里在 `/odoo` 读到 `--primary-rgb: 14, 123, 242` 就是这个 —— 也是审计说 `--bs-primary` 「惰性」的第一层原因：**那个名字在 Odoo 里不存在**（在原生 Bootstrap 站点上才叫 `--bs-primary`）。

### 4.2 这些变量怎么来的（✅ Bootstrap 源码，上游与 Odoo 内置副本逐行一致）

| 位置 | 内容 |
|---|---|
| `twbs/bootstrap@v5.3.3 scss/_root.scss:9-23`（Odoo 内置副本 `addons/web/static/lib/bootstrap/scss/_root.scss` 同段） | `@each $color,$value in $colors { --#{$prefix}#{$color}: #{$value}; }`；`$grays`；`$theme-colors`；**`$theme-colors-rgb` → `--<name>-rgb`** |
| 同文件 `:82-87` | `--#{$prefix}link-color`、`--#{$prefix}link-color-rgb: #{to-rgb($link-color)}`、`--link-hover-color`、`--link-hover-color-rgb` |
| Odoo `addons/web/static/src/scss/bootstrap_overridden.scss:31,76` | `$primary: $o-brand-primary !default;`、`$link-color: $o-main-link-color !default;` |
| Odoo 内置 bootstrap 的确切小版本号 | ⚠ **未验证**（`addons/web/static/lib/bootstrap/package.json` 不存在；只能确认 `_root.scss` 与上游 v5.3.3 相应行一致） |

### 4.3 「惰性」的完整解释（写给 t3/t5 的实现者）

1. **`--primary-rgb` 不是开关**：它只是 `$primary`（= `$o-brand-primary`）在 `:root` 里的一个**只读快照**。改它不会反向影响任何 `.btn-primary` 规则。
2. **Bootstrap 组件并不都读 `var(--primary)`**：5.3 大量组件用的是**编译期** `$primary`（如 `.btn-primary` 的 background 由 `$theme-colors` 生成），CSS 变量主要供「运行时主题切换」和少量 `rgba(var(--x-rgb), α)` 场景。**所以「接线到规则级」是必须的**（这正是 `custom_home.css` t112 修订记录的经验，与源码一致）。
3. **网站与后台的 `--primary` 不同源**：后台 `--primary ← $o-brand-primary ← $o-community-color`（`web/primary_variables.scss:73-78`）；网站 `$primary` 走调色板（`website/bootstrap_overridden.scss:73-110`）。审计里「`/odoo` 是 `14,123,242`、官网是 `2,109,222`」正是这两条链路的差异 —— **不是缓存，是两套变量链**。
4. **`--link-color-rgb` 同理**：后台 = `$o-main-link-color`（`darken($o-brand-primary,5%)`，`web/primary_variables.scss:123`）；网站 = `auto-contrast(o-cc1-link)`（`website/bootstrap_overridden.scss:83-86`）。→ 「每页链接色 8→≤2」的达标路径必须**同时**收口这两条链路。

---

## 5. ④ 同类系统配色实践（功能名 + 官方 URL）

### 5.1 Moodle —— 单一 `$theme-colours` map + 预设（🌐 官方）

- 官方组件库文档 *Themes → Colours*：`https://componentlibrary.moodle.com/admin/tool/componentlibrary/docspage.php/moodle/themes/colours/`（本次已抓取正文）
  - 原文：「**Use the `$theme-colours` Scss array to customize colours in `theme/boost/scss/preset/default.scss`**」，并给出官方默认值：`primary #1177d1`、`secondary #ced4da`、`success #398439`、`info #5bc0de`、`warning #f0ad4e`、`danger #d43f3a`、`light #f8f9fa`、`dark #373a3c`。
  - 同页强调「Moodle colours are slightly different from standard Bootstrap colours」，即**Moodle 自己定义了一套语义色，而不是直接用 Bootstrap 出厂色**。
- 官方主题文档：`https://docs.moodle.org/en/Boost_theme`、主题自定义层级 `https://docs.moodle.org/en/theme/custom`
- 官方设计系统（令牌化）：`https://design.moodle.com/` —— 自述为「A shared source of truth for Moodle UI foundations and tokens」。

**对本项目的意义**：教务 SaaS 的事实标准 = **一个主题预设 + 一个语义色 map + 出厂默认值**；没有任何一家在同一个产品里跑两套色温。

### 5.2 Canvas / Instructure —— 命名令牌的 Theme Editor（🌐 官方 KB，含默认值）

- 官方文档 *Canvas Theme Editor Components*：`https://community.instructure.com/en/kb/articles/387083-canvas-theme-editor-components`（本次已抓取正文）
  - 原文（摘录）：「The Theme Editor allows admins to create custom Canvas themes for an institution using colors and images.」
  - **Global Branding** 令牌：`Primary Brand Color`（默认 `#008ee2`，「Primary color used throughout Canvas, primarily shown in course navigation links and Dashboard toggle icon」，并同时用于 Canvas Student/Teacher App）、`Main Text Color`（默认 `#2d3b45`）、**`Link Color`（默认 `#008ee2`）**、`Primary Button`（「**if a color is not set, the Primary Button assumes the Primary Color**」）、`Primary Button Text`（默认 `#ffffff`）、`Secondary Button`（默认 `#2d3b45`）…
  - **Global Navigation** 令牌：`Nav Background`（同时决定浏览器地址栏底色）等。
  - 官方还明确风险边界：「custom files may overwrite any colors supported for high contrast styles; … changing a link color to red in a custom css file will also show as red to users with high contrast styles, which may create accessibility issues.」→ **自定义 CSS 与无障碍高对比模式的冲突是官方承认的既有坑**。

**对本项目的意义**：**「链接色」被当作一等令牌单独列出**（Canvas 的 `Link Color` 与 `Primary Brand Color` 是两个键，只是默认同值）——与我们「每页链接色 ≤2」的验收指标同构；且「主按钮默认继承主色」正是路线 A 想要的行为。

### 5.3 钉钉 / 企业微信教育版 —— 官方 URL 在，色值规范**未验证**

已验证（🌐 官方页可抓取正文）：
- 企业微信「家长通知」产品页 `https://work.weixin.qq.com/nl/act/p/5d7ac4f1e1764e7f`：原文「老师可在**工作台-家长通知**，编辑通知内容…勾选『需家长确认收到』；在家校通讯录中有资料的家长，会在**微信-通讯录-学校通知**中收到通知…老师即可在『家长通知-已发送的通知』查看通知的阅读名单」。→ 家校工作台是**单一界面承载多角色**，这支持「高频工作界面用统一冷色」的取舍。
- 企业微信「如何设置企业 LOGO」`https://open.work.weixin.qq.com/help2/pc/15024?person_id=1`：原文（英文 HELP CENTER 镜像页）「管理员可以设置对应的企业logo…在手机端或电脑端启动企业微信的时候会展示企业logo」。→ 品牌资产（logo）与配色是**分开的两层**：logo 可换，界面主色不暴露给管理员。
⚠ 未验证（**不得当结论用**）：
- 钉钉 OpenUI／UI 规范的具体色值：`https://open.dingtalk.com/document/development/basic-specification-definition` —— 返回的 HTML 只有 ~102 字符的 SPA 外壳（JS 渲染），**本次无法一手取证**；搜索摘要称其「描述了钉钉平台的基础UI规范，你可以引用钉钉定义的色值」，但**摘要不是一手来源**。
- `https://open.dingtalk.com/document/services/design-specification-for-dingtalk-product-solution-provider`（设计规范页）同为 SPA，未取证。
- 企业微信具体主色 HEX：官方帮助中心为使用指南，未找到公开的配色规范页 → 未验证。
- 钉钉帮助中心 `https://help.dingtalk.io/zh` 可抓取（20k 字符，服务端渲染），但其索引 `llms.txt` 返回 15 字节（无内容），未能在其中定位到配色规范。

### 5.4 三家横向对照（只列已一手取证的）

| 维度 | Moodle | Canvas | 本项目现状（审计） |
|---|---|---|---|
| 主色 | `$theme-colours.primary = #1177d1` | `Primary Brand Color = #008ee2` | 3 种蓝并存（`#026DDE`/`#0E7BF2`/`#0C6DD7`） |
| 链接色 | 由 primary 派生（Bootstrap `$link-color`） | **独立令牌 `Link Color`，默认同主色** | 每页最多 8 种 |
| 状态色 | 自带一套（非 Bootstrap 出厂） | 由 Theme Editor 令牌控制 | 门户一套 + b11 旧值一套 + Bootstrap 出厂一套 |
| 用户在管理端能改什么 | 主题设置 / 自定义 SCSS（可限定权限） | **仅命名令牌**（Theme Editor，+ 可选自定义 CSS/JS，官方标注风险） | 无（网站色板 `--has-customized-colors: false`） |

---

## 6. ⑤ OCA 现成主题模块评估（能装不写、能抄不造）

### 6.1 `OCA/server-brand`（19.0 分支存在 ✅）

- 仓库：`https://github.com/OCA/server-brand/tree/19.0`；分支清单实测含 `11.0…19.0`。
- **许可证（实测 API `license` 端点）：整仓 `AGPL-3.0`**；⚠ 但模块级可以不同 —— 实测 `website_debranding/README.rst` 自带徽章 **`License: LGPL-3`**。→ **评估许可以模块 manifest 为准，不要按仓库名一刀切。**
- 19.0 模块清单（实测 API `contents?ref=19.0`）：`disable_odoo_online`、`mail_debranding`、`portal_debranding`、`remove_odoo_enterprise`、`sale_portal_debranding`、`website_debranding`。
- `remove_odoo_enterprise`（AGPL-3, Beta）README 原文：「This module removes enterprise-only apps and features from all settings views. It also removes the widget in the General Settings page for downloading the Odoo mobile apps」→ **与配色无关**；其 `static/` 下只有 `description/`，无 SCSS。
- `website_debranding`（LGPL-3）＝移除网站上的 Odoo 品牌痕迹（页脚品牌链接等）。
- ❗**结论：`server-brand` 里没有任何「配色主题」模块** —— 它解决的是「Odoo 品牌出现/消失」，不是「色值」。

### 6.2 `OCA/website-themes`（19.0 分支存在，但**空壳**）

- 仓库：`https://github.com/OCA/website-themes/tree/19.0`；分支含 `11.0…19.0`；**license `AGPL-3.0`**。
- 实测 `contents?ref=19.0`：**只有仓库脚手架**（`.github`、`.pre-commit-config.yaml`、`LICENSE`、`README.md`、`setup/`、lint 配置），**没有任何模块目录**。
- ❗**结论：19.0 上没有可复用的网站主题**（历史分支可能有，但对本项目无用）。

### 6.3 `OCA/website`（19.0）

- 实测目录：`portal_invitation_by_website`、`website_conditional_visibility_user_group`、`website_cookiefirst`、`website_form_require_legal`、`website_forum_subscription`、`website_google_tag_manager`、`website_require_login`、`website_snippet_big_button`、`website_snippet_marginless_gallery`。
- ❗**无主题/配色模块**（`website_snippet_big_button` 只是按钮 snippet）。

### 6.4 评估结论

| 需求 | 现成可装？ | 建议 |
|---|---|---|
| 后台/门户统一色板 | ❌ 无 | **自研**（本仓 `edu_brand` 已是正确挂载点，缺的是 §3.2 的变量快照补齐） |
| 网站色板预设 | ❌ 无（OCA 无；官方文档给的是**主题模块**写法，且要求 `category: Website/Theme` 的完整主题模块） | 两种合规路径：**(a)** 建正式主题模块写 `$o-color-palettes`；**(b)** 用 §2.3 的 `make_scss_customization` 程序化写「用户调色板」层。**(b) 改动小、可脚本化、可直接进部署清单**；**(a) 更「正统」但要新建模块与数据文件** |
| 去 Odoo 品牌（页脚/设置页/企业版入口） | ✅ `OCA/server-brand@19.0`（`website_debranding` LGPL-3 可用；其余 AGPL-3 需评估） | 抄思路；**若要引入 AGPL 模块必须先做许可评估**（本仓 `custom_addons` 目前统一 LGPL-3，见 `edu_brand/__manifest__.py:37`） |
| 模板里的 `#71639e`/`#714B67` 字面量 | ❌ 无 | 自研视图继承（见 §3.3） |

⚠ 未验证：`OCA/web@19.0` 是否含主题类模块 —— 本次 GitHub API 触发**未认证限流**（60 req/h），未取得目录清单。

---

## 7. 现网与本机实测补充（供 t9 复测用）

1. 🧪 现网紫色定量（来源 `docs/audit/ui-color-raw-2026-09-15.json`）：`/odoo/contacts` 的 `bg` 计数含 `rgb(113,99,158)`（`#71639E`）×**1**、`rgb(113,75,103)`（`#714B67`）×**1**，同页还有 Bootstrap 出厂 `rgb(40,167,69)`（`#28A745`）×1、`rgb(222,226,230)`（`#DEE2E6`）×4。
2. 🧪 上面两处「原厂紫」各自**只出现 1 次**，与「一条模板 meta + 一个 navbar 下拉规则」和「我们自己的 1 个注入 `<a>`」的推断规模一致。
3. 🧪 本机容器 `odoo:19` = `Odoo Server 19.0-20260817`（`docker exec ... odoo --version`）。**调研期间该容器不在运行**（`docker ps` 只剩 db，且 unhealthy）→ t8/t9 之前必须先起容器 + 三步探活，否则门禁是假红（`docs/code-map.md` §2）。

---

## 8. 未验证 / 待确认（不得当结论用）

| # | 项 | 原因 | 建议的取证方式 |
|---|---|---|---|
| 1 | 钉钉 OpenUI／平台 UI 规范的**具体色值** | `open.dingtalk.com` 为 JS 渲染 SPA，抓取只得到 102 字节外壳 | 浏览器打开后人工摘录，或找官方 PDF/设计资源包 |
| 2 | 企业微信界面的**主色 HEX 与是否可配置** | 官方帮助中心是使用指南，未找到公开配色规范页 | 同上；或从官方客户端截屏取色（**截图取色不是官方规范，标注为实测非规范**） |
| 3 | Odoo 内置 Bootstrap 的**确切小版本号** | `addons/web/static/lib/bootstrap/package.json` 不存在（404）；只能比对 `_root.scss` 与上游 v5.3.3 一致 | 在容器里 `head -20 /usr/lib/python3/dist-packages/odoo/addons/web/static/lib/bootstrap/scss/_variables.scss`，或搜 `bootstrap.scss` 头注释 |
| 4 | 后台 `#714B67` 那一处**元素级**归属（是否就是 `apps_panel_chip.js`） | 审计原始 JSON 只存聚合计数，未存选择器 | 真机打开 `/odoo/contacts`，`document.querySelectorAll('*')` 过滤 `background-color: rgb(113,75,103)` |
| 5 | `$o-navbar-background` 是否为 `#71639E` 的**唯一**来源 | 同 4，未做元素级验证 | 真机取 `button.o-dropdown.dropdown-toggle` 的 computed background，并与 `backend_b11.css` 的覆盖范围比对 |
| 6 | `OCA/web@19.0` 是否含主题类模块 | GitHub 未认证 API 限流 | 限流恢复后 `GET /repos/OCA/web/contents?ref=19.0` |
| 7 | `base-1` 调色板（`--o-color-1: #026dde` 那位）的**字面定义文件** | 在 `website/primary_variables.scss` 中只搜到 `map-merge(map-get($o-color-palettes,'base-1'), ...)`，未见 `'base-1': (...)` 本体定义 | 在容器内 `grep -rn "'base-1'" /usr/lib/python3/dist-packages/odoo/addons/` |
| 8 | 非 website 的 `web.assets_frontend`（登录页/门户）是否也使用空 `$variable-prefix`（即是否也存在 `--primary` 而非 `--bs-primary`） | `bootstrap_overridden_frontend.scss` 内无 `variable-prefix`；未能取得 `web.assets_frontend` 的完整 bundle 成员（抓取超时） | 容器内 `grep -n variable-prefix -r /usr/lib/python3/dist-packages/odoo/addons/web/static/src/scss/`，并检查生成的 `web.assets_frontend` CSS 的 `:root` 块 |
| 9 | 门户/website layout 那条 `#714B67` meta 的出处 | 只在本仓抓取页面里见到，未定位到 Odoo 模板行 | 同上，`grep -rn 'theme-color' odoo/addons/*/views/*.xml` |

---

## 9. 参考来源汇总（全部一手）

**Odoo 19 源码（commit `65dae4ab…`；链接写 `19.0` 分支形式）**

- `addons/website/models/assets.py` — <https://github.com/odoo/odoo/blob/19.0/addons/website/models/assets.py>（`:21-37,40,58-97,186,189,206-224,318-364`）
- `addons/website/models/theme_models.py` — <https://github.com/odoo/odoo/blob/19.0/addons/website/models/theme_models.py>（`:258-275`）
- `addons/website/static/src/scss/website.scss` — <https://github.com/odoo/odoo/blob/19.0/addons/website/static/src/scss/website.scss>（`:20-170`）
- `addons/website/static/src/scss/secondary_variables.scss` — <https://github.com/odoo/odoo/blob/19.0/addons/website/static/src/scss/secondary_variables.scss>（`:87-140,164,211-217`）
- `addons/website/static/src/scss/primary_variables.scss` — <https://github.com/odoo/odoo/blob/19.0/addons/website/static/src/scss/primary_variables.scss>（`:6,28,33,38,61,2043`）
- `addons/website/static/src/scss/bootstrap_overridden.scss` — <https://github.com/odoo/odoo/blob/19.0/addons/website/static/src/scss/bootstrap_overridden.scss>（`:29,73-86,109`）
- `addons/website/static/src/scss/color_palettes.scss`、`.../options/colors/user_*_palette.scss`、`.../options/user_values.scss` — <https://github.com/odoo/odoo/tree/19.0/addons/website/static/src/scss/options>
- `addons/web/static/src/scss/primary_variables.scss` — <https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/scss/primary_variables.scss>（`:73-87,123,132-134,145,150,231-289`）
- `addons/web/static/src/scss/bootstrap_overridden.scss` — <https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/scss/bootstrap_overridden.scss>（`:31,51,76`）
- `addons/web/static/src/webclient/navbar/navbar.variables.scss` / `navbar.scss` — <https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/webclient/navbar/navbar.variables.scss>（`:7-8`）、<https://github.com/odoo/odoo/blob/19.0/addons/web/static/src/webclient/navbar/navbar.scss>（`:147-155`）
- `addons/web/views/webclient_templates.xml` — <https://github.com/odoo/odoo/blob/19.0/addons/web/views/webclient_templates.xml>（`:279,352-354`）
- `addons/web/__manifest__.py` — <https://github.com/odoo/odoo/blob/19.0/addons/web/__manifest__.py>（`:49-58,376-393`）
- `odoo/addons/base/models/ir_asset.py` — <https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/ir_asset.py>（`:14,184-197,212-214,287-306`）
- 内置 Bootstrap 副本 — <https://github.com/odoo/odoo/blob/19.0/addons/web/static/lib/bootstrap/scss/_root.scss>（`:9-23,82-87`）

**Bootstrap 上游**

- `twbs/bootstrap` v5.3.3 `scss/_root.scss` — <https://github.com/twbs/bootstrap/blob/v5.3.3/scss/_root.scss>（`:9-23,82-87`）

**Odoo 官方文档（19.0）**

- *Theming*（howtos/website_themes）— <https://www.odoo.com/documentation/19.0/developer/howtos/website_themes/theming.html>；纯文本源 <https://www.odoo.com/documentation/19.0/_sources/developer/howtos/website_themes/theming.rst.txt>
- *Theme tutorial Ch.1* — <https://www.odoo.com/documentation/19.0/developer/tutorials/website_theme/01_theming.html>

**同类系统官方页**

- Moodle 组件库 *Colours* — <https://componentlibrary.moodle.com/admin/tool/componentlibrary/docspage.php/moodle/themes/colours/>
- Moodle *Boost theme* — <https://docs.moodle.org/en/Boost_theme>；*Themes* — <https://docs.moodle.org/en/Themes>；设计系统 — <https://design.moodle.com/>
- Canvas *Theme Editor Components* — <https://community.instructure.com/en/kb/articles/387083-canvas-theme-editor-components>
- 企业微信 *家长通知* — <https://work.weixin.qq.com/nl/act/p/5d7ac4f1e1764e7f>；*设置企业 LOGO* — <https://open.work.weixin.qq.com/help2/pc/15024?person_id=1>；帮助中心 — <https://open.work.weixin.qq.com/help2/pc/18875?person_id=1>
- 钉钉 OpenUI（未取证正文）— <https://open.dingtalk.com/document/development/basic-specification-definition>；设计规范（未取证正文）— <https://open.dingtalk.com/document/services/design-specification-for-dingtalk-product-solution-provider>；帮助中心 — <https://help.dingtalk.io/zh>

**OCA**

- `OCA/server-brand@19.0` — <https://github.com/OCA/server-brand/tree/19.0>（模块：disable_odoo_online / mail_debranding / portal_debranding / remove_odoo_enterprise / sale_portal_debranding / website_debranding；仓库 license AGPL-3.0，`website_debranding` 模块为 LGPL-3）
- `OCA/website-themes@19.0` — <https://github.com/OCA/website-themes/tree/19.0>（AGPL-3.0，19.0 无模块）
- `OCA/website@19.0` — <https://github.com/OCA/website/tree/19.0>（无主题模块）

**本仓内部证据**

- `docs/audit/ui-color-audit-2026-09-15.md`、`docs/audit/ui-color-raw-2026-09-15.json`
- `custom_addons/edu_brand/static/src/scss/backend_variables.scss:1-45`、`custom_addons/edu_brand/__manifest__.py:22-38`
- `custom_addons/edu_portal/static/src/js/apps_panel_chip.js:8-27`、`controllers/batch2.py:434`、`views/register.xml:11`、`views/evaluation.xml:344-345`
- `reference/apps_menu_target.html`、`reference/roles/faculty/my__home.html`（抓取的现网页面，含 `theme-color` meta 原文）

---

## 追加（captain 容器实测，2026-09-15；本项由 t5 复核引出）

- **$min-contrast-ratio: 3（不是 Bootstrap 默认 4.5）** —— addons/web/static/src/scss/bootstrap_overridden.scss:43：$min-contrast-ratio: 3 !default;（本机 odoo:19 镜像实读）。
  含义：color-contrast() 会在 #0E7BF2（白底仅 4.09）上照样选白字 ⇒ **交互面的文字颜色必须显式给值，不能依赖自动推断**。
  结果侧旁证（color-arch）：后台主按钮实测为 #0E7BF2 底 + **白字**；若阈值是 Bootstrap 默认 4.5，color-contrast() 会选黑字 —— 实测行为与阈值 3 一致。
  引用处：docs/plans/color-system-v4.md 的 §3.3 / §8.2（「官方文档没写、源码才有的坑」）。
