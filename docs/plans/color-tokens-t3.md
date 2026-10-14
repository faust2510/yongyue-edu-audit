# t3 交付说明：唯一颜色令牌源 + 网站色板接线
> **状态**：`已上线` ｜ **主题**：`配色令牌` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 任务：t3 · 作者：eng-web · 2026-09-15
> 依据规范：`docs/plans/color-system-v4.md`（t2 定稿）§1.2 / §2 / §2.7 / §3.4 / §6.3
> 本文回答验收条款 3：「网站色板接线可复跑、幂等，并在 docs 写明**改哪条记录/哪个字段 + 复跑命令**」。

---

## 0. 一句话

令牌源是**文件**不是记录：`custom_addons/edu_brand/static/src/scss/brand_tokens.scss`。
网站色板通过其中的 **`$o-user-color-palette`**（SCSS 变量）在**编译期**接线 ——
**不写任何数据库记录**，因此天然可复跑、幂等，且与「唯一令牌源」不冲突。

---

## 1. 改哪条记录 / 哪个字段

### 1.1 实际写法：编译期变量，零 DB 记录

| 项 | 值 |
|---|---|
| **文件** | `custom_addons/edu_brand/static/src/scss/brand_tokens.scss`（§4 段） |
| **变量（"字段"）** | `$o-user-color-palette` |
| **写法** | `$o-user-color-palette: map-merge($o-user-color-palette, ( 'o-color-1': $brand-action, ... ));` |
| **注册** | `edu_brand/__manifest__.py` 的 `web._assets_primary_variables`，**排在 `backend_variables.scss` 之前** |
| **数据库记录** | **无**（不创建 ir.attachment / ir.asset / 不改 website 字段） |

**为什么这一处就够（源码链，可复核）**：

1. `website/static/src/scss/primary_variables.scss:28` 声明 `$o-user-color-palette: () !default;`，
   该文件由 website 模块注册在 `web._assets_primary_variables`（`website/__manifest__.py:290-291`）。
2. `edu_brand` depends `website` + `theme_web_openeducat` ⇒ **本模块的文件在其之后编译**，
   普通赋值（非 `!default`）即被采纳。
3. `website/static/src/scss/secondary_variables.scss:138-140` 执行
   `map-merge(出厂调色板, $o-user-color-palette)`，结果作为 `'user-palette'` 并入；
   `:125-130` 据「`$o-user-color-palette` 非空」把 **`$o-has-customized-colors` 置真**。
4. ⇒ **改色板与置标志一次完成**，且色值仍只出自令牌源。

### 1.2 取值映射（全部有出处，非自创）

| 调色板键 | 改前（出厂） | 改为 | 依据 |
|---|---|---|---|
| `o-color-1` | `#026DDE` | `$brand-action` `#0C6DD7` | 审计 §4「必须消灭的 alien 色」之首；规范 §2.1 明钉 |
| `o-color-2` | `#09417E` | `$brand-700` `#084CA0` | 该色同属审计指标 7 的「出厂残留 12 色」清单 |
| `o-color-3` | `#F3F2F2` | `$bg` `#F4F7FA` | 规范已判「#F3F2F2 98 处 → `--bg`」 |
| `o-color-4` | `#FFFFFF` | `$white` | 豁免白，无视觉变化 |
| `o-color-5` | `#111827` | `$text-1` `#1A2233` | 审计 §4 点名的 alien 色（页脚/深色块） |
| `o-cc1-text` | `#6B7385` | `$text-3` `#5E6779` | 规范 §2.3 桥接；压 `--bg` 5.29 ✓（原值 4.42 ✗） |
| `o-cc1-headings` | `#192335` | `$text-1` | 与正文同色温 |
| `o-cc1-link` | `#0F34C3` | `$brand-action` `#0C6DD7` | 审计：全站链接色须并入品牌蓝 |

> `o-cc1-btn-primary` / `o-cc1-btn-secondary` 在主题里是**对 `o-color-1/2` 的引用**，随之生效（实测已确认）。

---

## 2. 复跑命令

```bash
# 复跑（幂等：这是源码改动，不是状态写入，重复执行结果完全一致）
bash scripts/safe_upgrade.sh edu_brand

# 契约要求的四条验证
bash scripts/safe_upgrade.sh edu_portal
python3 scripts/check_english.py
python3 scripts/check_view_xpath.py
python3 scripts/check_accessibility.py --selftest

# 令牌门禁（判据 C）
python3 scripts/color_tokens.py --check          # 棘轮口径
python3 scripts/color_tokens.py --check --strict # t9/t10 全量复核
python3 scripts/color_tokens.py --write          # 重新生成 color_tokens.json
```

### 幂等性说明

- 本方案**只改源码**；重复执行 `safe_upgrade` 得到逐字节相同的色板（实测两次执行的编译产物令牌值一致）。
- 对比：若走 `env['website.assets'].make_scss_customization(url, values)`，它会
  **创建 `ir.attachment`（`url=/_custom/<bundle><原路径>`, mimetype `text/scss`）+ `ir.asset`（`directive=replace`）**，
  并在换调色板时联动重置多份文件 —— 需要自己写去重/清理才算幂等，且色值会落到数据库里成为**第二处真相**。
  ⇒ 若将来确要走该路径，请勿与本节方案并用（会互相覆盖），并同步修改本文件。

---

## 3. 怎么验证（真机读数，非读源码猜）

用审计同一套口径（遍历可见元素，取 computed `color`/`background-color`/`border-*-color`，`rgba` 归一成 `rgb`）：

| 页面 | 可见元素 | 不同颜色数 | `rgb(2,109,222)` | `rgb(15,52,195)` | `rgb(243,242,242)` | `rgb(17,24,39)` |
|---|---|---|---|---|---|---|
| `/` | 264 | 23 | **0** | **0** | **0** | **0** |
| `/apply` | 285 | 26 | **0** | **0** | **0** | **0** |

另外三项：

- `--has-customized-colors` = **`true`**（改前 `false`）；
- 公开页 `.btn-primary` 计算底色 = **`rgb(12, 109, 215)`** = `--brand-action`；
- `--body-color` 在 `body` 上 = `#5E6779` = `--text-3`（回归锚点）。

---

## 4. 已知边界（不属本任务遗留，交由下游）

| 现象 | 归属 | 说明 |
|---|---|---|
| `/apply` 上还有一个 `rgb(138,109,59)` 按钮底 | **t7** | `edu_apply/views/templates.xml:109` 的 inline `#8a6d3b`；规范 §4.3 判它 → `--brand-action` |
| 页脚仍有金色/暖米链接色（`#C8A870`/`#D9D2C5`） | **t6** | 首页/页脚/导航；规范 §2.5 金只作点缀 |
| `--border` 在 `.yylc-home` 的作用域覆盖 | **t6** | 门禁记 WARN（非 bug）；规范 §1.4 判 t6 加 `--yylc-` 前缀迁移 |
| 未收口文件里的令牌外债务色（当前 179） | t4/t5/t7/t8 | 门禁逐批棘轮：各任务把自己文件加进 `color_tokens.json` 的 `adopted_files` |

---

## 5. 本次交付的偏离（已获 captain 授权/追认）

1. **规范原写「`custom_home.css:83-139` 整块删除」**，但该块含 **37 个非颜色令牌**
   （字号/行高/字重/间距/圆角/组件尺寸）且有 **90+ 处 `var()` 引用**（全在该文件内）。
   已将其**原值迁入令牌源** §2.11-2.14，使「整块删除」得以按字面执行且零引用失效。已报 captain + color-arch。
2. **网站色板走 `$o-user-color-palette` 编译期接线**，而非任务书中预设的
   `make_scss_customization`（DB 记录）路径。理由：满足「唯一令牌源」、零 DB 状态、天然幂等。
   已报 captain；若裁定改走 DB 路径，改动集中在本文件 §4 段与 `edu_brand` 的 post_init/migration。
3. **`:654` 桥接选择器补了 `:root > body`**：真机自证发现服务端 `<html>` **无 `data-bs-theme` 属性**，
   `[data-bs-theme] body` 半在公开页不匹配；旧写法仅靠排在 bundle 末尾取胜，迁到令牌源（排最前）后
   `--body-color` 退回主题灰 `#6b7385`（4.42 ✗）。补 `:root > body` 使声明落在 `body` 自身，与源码顺序无关。
   `[data-bs-theme] body` 半按 captain 硬约束原样保留。

---

## 6. 语法纪律（规范 §2.7 四条硬规则 · r4 反转后口径）

本环境 SCSS 后端是 **libsass 3.6.5**（容器内无 `sass`/`sassc` 二进制），**未实现模块系统**。以下四条均已实测，违反任一都会被门禁 `--check` 判 FAIL：

| # | 规则 | 违反后果（实测） |
|---|---|---|
| 1 | 通道令牌**一律逗号分隔**：`--brand-500-rgb: 14, 123, 242` | 空格通道喂进逗号式消费 ⇒ **静默失效**（不报错） |
| 2 | 消费**一律** `rgba(var(--x-rgb), α)` | 普通属性上写斜杠式 `rgb(var(--x) / α)` ⇒ **直接编译报错** `Function rgb is missing argument $green`（libsass 把 `rgb(` 当内置函数）。**只有自定义属性值内部**才允许斜杠式 |
| 3 | 自定义属性值**一律显式插值** `--x: #{$y};` | 写 `--x: $y;` ⇒ libsass 对自定义属性值**不解析**，裸变量被原样输出成字符串 ⇒ 浏览器取不到值，**编译却通过、不报错** |
| 4 | 任何 `--x-rgb` 必须有**同名** `--x` 基色令牌 | 门禁判据 8 缺基色即 FAIL |

**另：禁止 `@use`/`@forward`/`color.*`** —— libsass 未实现模块系统，写了会**直接让整个 bundle 编译失败**；令牌源与所有消费方只能用老式全局函数 `red()/green()/blue()/mix()/map-merge()/darken()/lighten()`。

> **重要**：Odoo 对 SCSS 编译错误是**静默丢弃该文件的 CSS**，不会让 `-u` 失败。⇒ **「`safe_upgrade` 退出码 0」不等于「样式生效」**，改完 SCSS 必须**核对编译产物**。t3 正是靠这一步才发现并修掉一处静默回归。

### 6.1 门禁判据 6 的三个子项（对应上表 1/2/3）

| 子项 | 判据 | 实测 |
|---|---|---|
| 6a | `--x-rgb` 的值里没有逗号（空格通道） | 注入空格通道 ⇒ **FAIL**；逗号 ⇒ 通过 |
| 6b | **普通属性**上出现斜杠式 `rgb(var(` | 注入 `color: rgb(var(--brand-500-rgb) / .1)` ⇒ **FAIL**；`rgba(var(...), .1)` ⇒ 通过 |
| 6c | 裸变量赋自定义属性（`--x: $y;` 无 `#{}`） | 注入 ⇒ **FAIL**（同行与换行两种写法都抓）；`#{$y}` / `var(--y)` ⇒ 通过 |

### 6.2 本轮按规范 r4/r7 完成的整改

| # | 项 | 改前 | 改后 | 出处 |
|---|---|---|---|---|
| 1 | 通道分隔符 | 空格 `14 123 242` | **逗号 `14, 123, 242`**（11 个全改） | §2.7 规则 1 |
| 2 | 阴影令牌 | `rgb(var(--shadow-rgb) / .05)` | **`rgba(var(--shadow-rgb), .05)`** | §2.7 规则 2 / §2.6 |
| 3 | 金命名 | `--gold-200` | **`--gold-100`** | §2.5 captain 终版命名 |
| 4 | 别名 | `--accent: var(--teal-500)` | **`var(--teal-600)`**（teal-500 作文字仅 3.11–3.43 ✗） | §2.1 r4 裁定 |
| 5 | 通道基色 | `--neutral-rgb` 由 `$text-3` 派生 | **由 `$neutral` 派生**（同名基色，判据 8 可机检） | §6.3 判据 8 |
| 6 | 兼容别名 | — | 新增 `--covenant-gold: var(--gold-500)` | §2.5 别名行 |

**提取器同步增强**：`color_tokens.py` 现在能解析**别名链**（SCSS 级 `$a: $b;` 多级、CSS 级 `--a: var(--b);`），并把别名令牌并入令牌表（`alias_of` 字段标注），否则「`--neutral-rgb` 由 `$neutral` 派生」会被误判为「基色未定义」，判据 8 也会误杀合法别名。

---

## 7. 自证断言（可机械复跑；含 eng-backend 提出的「失败指纹」）

规范 §2.7 规则 3（r4 ④）要求「自定义属性值一律 `#{}` + t3 自证断言」。以下断言均已在本机实测通过，命令与读数如下。

### 7.1 约定

- **失败指纹**：编译产物里若出现**未代入的 SCSS 变量字面字符串**（`$brand-` / `$teal-` / `$o-` / `$shadow` / `$bg` / `$text-`），说明 libsass 把自定义属性值当 opaque token 原样输出 ⇒ **令牌全空、编译能过、不报错**。这是本任务最危险的静默失败形态。
- **安全写法**：令牌源里自定义属性值**一律**写 `--x: #{$y};`，**永不**写 `--x: $y;`。理由：若 libsass 会解析变量，`#{}` 等价且无害；若不解析，`#{}` 是唯一能正确代入的写法。**两种行为下都安全，无需先判定是哪种。**

### 7.2 复跑命令

```bash
FE=$(curl -sL 'http://localhost:8069/web/login?db=edu19' | grep -oE '/web/assets/[^"]+\.css' | sort -u | head -1)
curl -s -o /tmp/fe.css "http://localhost:8069$FE"

# ① 失败指纹必须为 0
grep -cE '\$(brand-|teal-|o-|shadow|bg|text-)' /tmp/fe.css

# ② 具体值断言：各必须 >= 1
grep -c -- '--brand-500: #0E7BF2'                 /tmp/fe.css
grep -c -- '--brand-action: #0C6DD7'              /tmp/fe.css
grep -c -- '--focus-ring: var(--brand-500)'       /tmp/fe.css
grep -c -- '--brand-500-rgb: 14, 123, 242'        /tmp/fe.css

# ③ 令牌源合规：裸变量赋自定义属性必须为 0
grep -cE '^\s*--[A-Za-z0-9_-]+\s*:\s*\$' custom_addons/edu_brand/static/src/scss/brand_tokens.scss
```

### 7.3 实测读数（2026-09-15）

| 断言 | 结果 |
|---|---|
| 失败指纹 `$brand-` / `$teal-` / `$o-` / `$shadow` / `$bg` / `$text-` | **全为 0** ✓ |
| `--brand-500: #0E7BF2` | **1** ✓ |
| `--brand-action: #0C6DD7` | **1** ✓ |
| `--focus-ring: var(--brand-500)` | **1** ✓ |
| `--brand-500-rgb: 14, 123, 242` | **1** ✓ |
| 令牌源裸变量赋自定义属性 | **0** ✓ |
| 令牌源 `#{}` 插值用法 | **55** 处 |

> **为何这条断言比「编译产物非空」强得多**：产物非空只证明「有东西编译出来了」；失败指纹 + 具体值断言才证明**令牌真的带值**。eng-backend 指出这一点后已采纳并入本节，他也据此把 t5 的消费写法统一为 `rgba(var(--brand-500-rgb), .06)`。

### 7.4 marker 探针实测（captain 要求，2026-09-15 执行）

临时在令牌源尾部插入 `:root{--t3-marker:1;}` → `safe_upgrade.sh edu_brand` → 拉取两个 bundle 核对 → **移除探针并复核基线**。

| 阶段 | 前台 bundle | 后台 bundle |
|---|---|---|
| 含 marker 时 `--t3-marker` 出现次数 | **1** | **1** |
| markdown 移除后 | **0** | **0** |
| 值断言（`--brand-500: #0E7BF2` / `--brand-action: #0C6DD7` / `--focus-ring: var(--brand-500)`） | **1 / 1 / 1** | **1 / 1 / 1** |

⇒ **marker 证明「能进 bundle」，值断言证明「值真的代入了」，两件事都成立。** 探针已移除，文件与提交版本逐字节一致。

### 7.5 ⚠ 失败指纹在全量 bundle 上会误报 —— 必须限定到本方文件

对**整个后台 bundle** 跑失败指纹，会发现 **2 处真实命中，且都来自 Odoo 官方源码**（不是本仓）：

| 位置 | 产物中的原文 | 后果 |
|---|---|---|
| `website/static/src/client_actions/website_preview/website_builder_action.dark.scss` | `.o_website_preview{--websitePreview-bg-color: $o-gray-200;}` | 自定义属性值是**未代入的变量字符串** ⇒ 该属性为空、浏览器取不到值 |
| livechat SCSS | `--list-group-active-border-color: map-get($o-theme-text-colors, 'warning');` | SCSS 函数被原样输出 ⇒ 同上 |

**三点结论**：
1. **这是「情形 E」的实网实证** —— 规则 3 的前提（libsass 对自定义属性值不解析）不再只是合成测试，而是**在官方编译产物里被直接观测到**（比合成用例强得多）。
2. **失败指纹必须按文件范围判定**：整包跑会永久报 2 处误报（来源是 core，不归本仓管）。**本方文件的读数：前台 0、后台 0**（那 2 处均在 core 的 SCSS 里）。
3. **上游缺陷，仅记录不修**：`odoo/addons` 是官方快照（本仓纪律：基座原则上不改）。其影响局部（网站预览器的深色底色变量、livechat 的激活边框色），与本次配色目标无交叉，列入已知项即可。

---

## 8. `color_tokens.py --scope S1|S2|S3`（规范 §4.2.1 r8 要求）

规范 §4.2.1 要求令牌脚本「必须以 `--scope S1|S2|S3` 参数形式支持三种口径，**输出必须带口径标签**」，且 **S3 须逐族输出 α 直方图**（brand-500 / text-1 / success / danger / warning / neutral / gold-500 / shadow 八族）。**已实现**。

### 8.1 用法

```bash
python3 scripts/color_tokens.py --scope S1   # 全仓 custom_addons/** 的 css/scss/xml/js/py（规范默认）
python3 scripts/color_tokens.py --scope S2   # 门户 9 个 CSS：edu_portal/static/src/css/*.css
python3 scripts/color_tokens.py --scope S3   # 单一家族：逐族输出 α 直方图
```

输出首行即口径标签（形如 `计数口径 S1 = 全仓 custom_addons/** …`），满足「无标签的数字视为不完整」。

### 8.2 ⚠ 规范 §4.2.1 的冻结数字会随 t4/t5 收口而漂移（实测对平）

实现后在当前工作区实测：**S1 的 brand-500 族只有 10 处**，而规范写的是 **111 处**。这不是脚本 bug —— 是 **t4 正在把字面值换成 `var()`**：

```
literal  rgba(14, 123, 242, α)          =  10 处
var      rgba(var(--brand-500-rgb), α)  = 101 处
                          10 + 101 = 111  ← 恰好等于规范的 S1 数
```

同理，同日门禁的「债务色」计数也从 175 降到 **142**（t4 收口进行中）。

**⇒ 建议规范给 §4.2.1 那张表加时间戳 / commit 标记**（例如「r8 基线，t4 收口前」）。否则按规范自己定的规则「无标签的数字视为不完整，t10 可直接判 finding」，那张表会自我判罚。

---

## 9. 交接给 t8 的清单（t3 范围外、但 t3 盘点时发现）

t3 的 inScope 含 `custom_addons/edu_portal/static/src/css/custom_home.css`，盘点时在其中发现以下项。**按规范 §7 它们归 t8**，t8 归 eng-web，故在此留档、不遗失。

| 位置 | 内容 | 处置要求 |
|---|---|---|
| `custom_home.css:584` | `--bs-primary: #0C6DD7; --bs-primary-rgb: 12, 109, 215;` | 规范判为**惰性**（Odoo `$variable-prefix` 为空串 ⇒ 不存在 `--bs-*`，写它无效）⇒ **删除**（规范 §7 t8 行） |
| **`custom_home.css:585`** | `--bs-link-color: #0C6DD7; **--bs-link-hover-color: #0A66D0**;` | ⚠ **`#0A66D0` 是审计 §7.6 点名的「源侧 6 种蓝」之一**，规范 §2.1 判其应并入 **`--brand-action-hover` = `#0A63CC`**。**这是取值问题、不是单纯惰性** —— 收口时要按 `#0A63CC` 改，**不要照原值搬** |
| `custom_home.css:586` | `--bs-btn-active-bg` / `--bs-btn-active-border-color: #0C6DD7` | 同上，**删除** |
| `custom_home.css:412/414` | `--bs-table-bg` / `--bs-table-color`（值已是 `var()`） | **Bootstrap 表格变量的合法消费，不是残留，不要动** |

**另两条 t8 必做**（规范 §7 t8 行原文）：
1. **顺序律核对**（§1.3）—— 确认无第二处 `:root` 重复定义同名令牌；
2. **把自己收口的文件追加进 `color_tokens.json` 的 `adopted_files`** —— 这一步是关键：未收口的文件只输出债务计数（INFO），**只有进了 `adopted_files` 门禁才真正开始保护它**。t3 已把 `brand_tokens.scss` 列入；t8 收口 `custom_home.css` 时须把它也加进去。

### 7.6 判据 6b 的两条必要限定（照字面写会误杀合法写法）

规范与 captain 的裁定都写「**.scss 的普通属性里**出现 `rgb(var(` ⇒ FAIL」。**"普通属性"这个限定是必需的**，实测有两类合法写法会被字面判据误杀：

| 情形 | 例子 | 是否合法 | 字面判据的后果 |
|---|---|---|---|
| **自定义属性值内** | `--shadow-sm: 0 1px 2px rgb(var(--shadow-rgb) / .05);` | ✅ 合法（libsass 对自定义属性值不解析，可编译） | 误判 **FAIL** |
| **注释里的示例** | `/* 禁斜杠式 rgb(var(--x-rgb) / α) */` | ✅ 只是说明文字 | 误判 **FAIL** |

**本脚本的处置（已实现并注入式验证）**：
1. `RX_PROP_SLASH` 捕获「属性名 : … rgb(var(」，**属性名以 `--` 开头则跳过**（自定义属性值）；
2. 扫描前先跑 `strip_comments()` 剥离 `/* */` 与 SCSS `//`（**注释里的示例不计**）。

**全仓实况（2026-09-15 复核）**：`rgb(var(` 只剩 **1 处**，在 `backend_b11.css:6`，且**是注释**（eng-backend 写的规则说明）⇒ 被正确忽略，门禁 `PASS`。令牌源内为 **0 处**。

> **给规范的建议措辞**：「**.scss 的普通属性上**出现 `rgb(var(` ⇒ FAIL；**注释与自定义属性值内不计**」。缺第二个限定（注释）同样会产生误报。

---

## 10. ⚠ 网站色板必须用 `$o-user-color-palette`，**不能**用 `$o-color-palettes` 的 base-1 merge

2026-09-15 实测对比。两种写法都能把 8 项 `o-color-*` 改成令牌值，但**只有 user-palette 写法能让链接色落回令牌内**。

### 10.1 机制（源码）

`website/static/src/scss/secondary_variables.scss:216-217`：
```scss
$o-we-auto-contrast-exclusions: () !default;
$o-we-auto-contrast-exclusions: join($o-we-auto-contrast-exclusions, map-keys($o-user-color-palette));
```
即 **把「用户色板」的键名自动加入 auto-contrast 的排除表**。而 `html_editor/.../secondary_variables.scss:126-131`：
```scss
@function auto-contrast($color1, $color2, $color1-name, $exclude: $o-we-auto-contrast-exclusions) {
    @if index($exclude, $color1-name) { @return $color1; }   // ← 命中排除表 ⇒ 原样返回
    @return increase-contrast($color1, $color2);
}
```
`website/.../bootstrap_overridden.scss:83` 的 `$link-color: auto-contrast(o-color('o-cc1-link'), $body-bg, 'o-cc1-link')` 因此：

- **用 user-palette**：`o-cc1-link` 在排除表里 ⇒ **原样返回令牌值 `#0C6DD7`** ✓
- **用 base-1 merge**：`o-cc1-link` 不在排除表 ⇒ `increase-contrast` 逐格压暗 ⇒ **`#0955A7`（对比度 7.32）** ✗

### 10.2 实测差异（真机 computed 值）

| 读数 | user-palette（采用） | base-1 merge（弃用） |
|---|---|---|
| `--o-cc1-link` | **#0C6DD7** | #0955A7 |
| `--link-color` | **#0C6DD7** | #0955A7 |
| 导航栏校名 `a.navbar-brand` 渲染色 | **rgb(12, 109, 215)** = `--brand-action`（**令牌内** ✓） | rgb(9, 85, 167) = `#0955A7`（**令牌外** ✗） |
| `--has-customized-colors` | true | false（该指标已按 captain 裁定弃用） |

⇒ **base-1 写法虽然"语义上不像用户操作"，却会在渲染层留下一个令牌外色 `#0955A7`** —— 与审计点名的 `#0F34C3` 属同类残留（都是 auto-contrast 派生出来的非令牌蓝）。**验收主判据是「令牌外色 = 0」，故采用 user-palette 写法。**

> 这条也解释了审计里 `#0F34C3` 的来龙去脉：它不是谁手写的，是 `auto-contrast(#2f57ef)` 算出来的。要让它消失，必须让 `o-cc1-link` **命中排除表**（即走 user-palette），否则只能得到一个"更接近品牌的另一种非令牌蓝"。

---

## 11. 棘轮清单的写入方式：追加式数据文件（并发安全）

规范 §6.3 要求「各任务收口完**自行把自己的文件追加进** `adopted_files`」。但直接让 t4/t5/t7/t8 都去改 `scripts/color_tokens.py` 里的常量会产生**并发写冲突**（t4 与 t5 当前同时 in_progress）。

**为此脚本改为「常量 ∪ 数据文件」**：

| 位置 | 归属 | 用途 |
|---|---|---|
| `scripts/color_tokens.py` 的 `ADOPTED_FILES` | **t3（代码）** | 初始集（唯一令牌源） |
| **`scripts/adopted_files.txt`** | **各任务（数据）** | 追加自己的收口文件，一行一个 workspace 相对路径；`#` 与空行忽略、自动去重 |

**添加方式（无需改代码）**：
```bash
cat >> scripts/adopted_files.txt <<'EOF'
custom_addons/edu_portal/static/src/css/portal.css
EOF
python3 scripts/color_tokens.py --check   # 该文件此时起参与「集外裸色 ⇒ FAIL」
python3 scripts/color_tokens.py --write   # 合并后的清单写回 color_tokens.json
```

> **注意**：`scripts/color_tokens.json` 是**生成物**（自注「不得手工维护」），直接手改会在下次 `--write` 时被覆盖。**真正的手写入口只有 `adopted_files.txt`（数据）与 `color_tokens.py`（代码）。**

**未列出的文件**只输出债务计数（INFO）、不阻断；t9/t10 用 `--strict` 把全部目标文件视为已收口复核。

---

## 12. 影子族改名 `--shadow` → `--shadow-ink`（2026-09-15，captain 终版命名）

### 12.1 落地形态（同名配对成立，零改色）

| 名字 | 值 | 说明 |
|---|---|---|
| `$shadow-ink` / `--shadow-ink` | `#14182D` | **新基色令牌**（SCSS 变量 + CSS 自定义属性） |
| `--shadow-ink-rgb` | `20, 24, 45` | **新通道令牌**，由 `$shadow-ink` 派生 ⇒ **§6.3 判据 8 同名配对成立，无需白名单** |
| `--shadow-sm/md/lg` | `rgba(var(--shadow-ink-rgb), …)` | 已改指新通道 |
| `$shadow` / `--shadow` | 别名（`$shadow-ink` / `var(--shadow-ink)`） | 兼容 t5 与旧引用 |
| **`--shadow-rgb`** | **`var(--shadow-ink-rgb)`（兼容别名）** | **见 12.2 —— 不改它会静默打断 74 处消费点** |

### 12.2 ⚠ 这不是"改 2 行"：改名会静默打断全仓 74 处消费点

captain 的指令表述是「改 `brand_tokens.scss` 的两行 + `custom_home.css:217` 一处」。**实测 blast radius 远不止**：

| 文件 | `var(--shadow-rgb)` 消费点数 | 归属 |
|---|---|---|
| `edu_portal/static/src/css/enterprise.css` | **36** | t4（eng-portal 正在编辑） |
| `edu_portal/static/src/css/portal.css` | **32** | t4（同上） |
| `edu_portal/static/src/css/batch3.css` | 1 | t4 |
| `edu_brand/static/src/css/backend_b11.css` | 1 | t5（eng-backend 正在编辑） |
| `edu_portal/static/src/css/custom_home.css` | 1 | t3（本文件，已改用新名） |
| **合计** | **74** | |

**失败模式是静默的**：自定义属性未定义 ⇒ `rgba(var(--shadow-ink-rgb), .05)` 之类的引用若找不到基色，整条 `box-shadow` 声明被浏览器丢弃、**不报错、不阻断构建**，表现为"部分阴影凭空消失"。

**处置**：保留 `--shadow-rgb: var(--shadow-ink-rgb)` 作为**兼容别名**。
- `var()` 别名**不新增字面值**（判据 4：别名/引用不计数）⇒ **不构成"第二个阴影墨"**；
- 74 处消费点**零改动**即可继续正确渲染；
- **待 t4/t5 迁到 `--shadow-ink-rgb` 后可删除该别名**（届时是纯清理）。

### 12.3 顺带修掉门禁自身一个假阳性（判据 6a）

留兼容别名后 `--check` 一度 **FAIL**：
```
判据6a brand_tokens.scss 空格通道定义 --shadow-rgb（规范要求逗号分隔）
```
**这是假阳性**：`--shadow-rgb: var(--shadow-ink-rgb);` 的值是 `var()` 引用，不是"空格分隔的通道三元组"。判据 6a 已改为**跳过值中含 `var(` 的声明**（与判据 4「别名不计数」一致）。

**反向验证**：注入真实的空格通道 `--zz-rgb: 1 2 3;` ⇒ **仍 FAIL**（未因豁免而失效）；还原后 exit 0 ✓。

---

## 13. `color_tokens.json` 的通道字段契约：**存声明形态，不存归一形态**

t4（eng-portal）在切换消费写法前设了一道机械前置：读 `color_tokens.json` 的 `channels`，确认 `--brand-500-rgb.value` **含逗号**。**这道检查第一次跑会 FAIL** —— 暴露了本脚本的一处接口缺陷：

| | 修复前 | 修复后 |
|---|---|---|
| `--brand-500-rgb.value` | `"14 123 242"`（**归一形态**） | `"14, 123, 242"`（**声明形态** ✓） |
| 附加字段 | — | `"value_normalized": "14 123 242"`（供需要归一形态的消费方） |

**为什么必须存声明形态**：`color_tokens.json` 是规范 §6.2 的「令牌集**唯一机读输入**」。下游要靠它机械判断「通道是否已改逗号」；若报归一形态，**下游会把"已改"读成"未改"并拒绝切换**。归一化是**比较用**的内部处理（`canon_value`），不该泄进对外契约。

**同时修掉的连带项**：`alpha_histogram` 里原本用 `ch["value"].split(",")[0].split()` 解析通道值 —— 改成逗号形态后该写法只会取到第一个数字。已改为对 `[,\s]+` 统一切分，**两种形态都能解析**。

**验证**：11 个通道 `value` 全部含逗号（`channels WITHOUT comma: NONE`）；`--scope S3` 直方图仍正常；门禁 `PASS` 退出码 0。

> 过程记录：改这段时我第一版按行号定位补丁，**错位覆盖了相邻的 `"base"` 键与 `hist` 初始化**，被 `--check`/`--scope` 立即暴露，随即按上下文精确修复。再次印证「改完必须核产物与运行结果」。

---

## 14. `extract_tokens` 必须**先剥注释**（给文档加示例时暴露的真 bug）

2026-09-15，按 captain ⑦ 要求把 A/B/C 三例写进令牌源头部注释后，门禁立刻 **FAIL**：
```
FAIL  判据8 通道令牌 --x-rgb 的基色 --x 未在令牌源里定义
```
**根因**：注释里写的示例 `--x-rgb: 14 123 242;` 被 `RX_CH_DERIVED/RX_CH_DIRECT` **当成真的通道令牌**提取了 —— 因为 `extract_tokens()` 读的是**原始文件**，而其余扫描器（判据 6/5）都走 `strip_comments()`。

**修复**：`extract_tokens()` 改为先 `strip_comments(raw, .scss)` 再提取。
**反向验证**：注入 `$qqtest: #123456;` + `--qqtest-rgb: #{red($qqtest)}, …`（**故意不 emit `--qqtest`**）⇒ **exit 1，判据 8 FAIL** ✓；还原 ⇒ exit 0。**判据 8 依然有效，只是不再把注释示例当令牌。**

> 教训：**文档里的示例是"看起来像令牌的文本"** —— 任何扫源码的检查都必须先把注释剥掉，否则加文档就会触发假故障。（本条与 §7.6「注释里的 `rgb(var(` 不计」是同一类问题的两个面。）

---

## 15. ⑤ 色板接线的**附带收益**：`--body-color` 在框架层也变正确了

2026-09-15 复核编译产物时发现：Bootstrap 自己的 `:root` 块现在输出
`--body-color: #5E6779`（**不再是主题灰 `#6b7385`**）。

**原因**：`website/.../bootstrap_overridden.scss` 里 `$body-color: o-color('o-cc1-text')`，而 **⑤ 把 `o-cc1-text` 映射成了 `$text-3`** ⇒ Bootstrap 编译出来的 `--body-color` 直接就是 `#5E6779`。

**意义（比原修法更强）**：
- 原修法（`:root > body`）解决的是**级联位置**问题：让声明落在 `body` 自身、与源码顺序无关；
- ⑤ 的色板映射则从**源头**把值改对了 ⇒ 连 `:root`/html 层读到的都是 `#5E6779`。
- ⇒ **两层都成立**，`--body-color` 回归的风险被双重关闭。

**实测（真机 `getComputedStyle`，`/` 与 `/apply` 两页一致）**：

| 读法 | 值 |
|---|---|
| `document.documentElement` 的 `--body-color` | **#5E6779** |
| `document.body` 的 `--body-color` | **#5E6779** |
| **`document.body` 的渲染 `color`（captain 的 outcome 级锚点）** | **rgb(94, 103, 121)** ✓ |
| `--text-3` | #5E6779 |

**对比度**：`#5E6779` 压 `--bg` = **5.29 ✓**；回到 `#6b7385` 则 **4.42 ✗** —— 锚点两侧的数值都记在此处，供 t9/t12 直接引用。

---

## 16. t8 追加项：`_KIND_COLOR` 四个日历色（captain 2026-09-15 指派）—— 核实结果与**比清单更大的范围**

captain 的表述：「`calendar.py:33-38` 的 `_KIND_COLOR` 经 `calendar.xml:116` 写成内联样式，是 `/my/calendar?view=week` 那四个图例色的唯一来源（四色各 ×1）」。**核实：成立，但范围被低估了两处。**

### 16.1 实际范围

**① 内联样式发射点有 3 个（不止图例那 1 个）**：

| 位置 | 写法 | 渲染对象 |
|---|---|---|
| `calendar.xml:116` | `t-att-style="'background:' + kind_color[k]"` | 图例四圆点（审计数的就是这 4 处） |
| **`calendar.xml:142`** | `t-att-style="'border-left-color:' + it['color']"` | **月视图芯片** |
| **`calendar.xml:209`** | `t-att-style="'border-left:3px solid ' + it['color']"` | **列表视图条目** |

**② `_KIND_COLOR` 有 8 个消费点**（`:281/:299/:313/:332/:475/:493/:507/:525`），覆盖月/周/列表三种视图 —— **不是"四色各一次"那么小**。

**③ 同一文件里还有一批硬编码色**（`calendar.xml` 的 `<style>` 块 `:9-22`）：`#64748b`、`#475569`、`#1f2937`、`#6b7280`，以及 `:14` 的 **`#0E9F6E`（与 event 色同值）**。⇒ t8 收口该文件时**这些也要一并处理**，否则文件仍进不了「令牌外裸色 = 0」。

### 16.2 ⚠ 一处需要裁决的冲突：其中两个十六进制值与 `edu_schedule` 的**已知例外**同值

- `#DC2626` / `#E7650A` 同时也是 `edu_schedule/models/session_ext.py:36-38` 的**课表冲突严重度三级语义色**，规范 §4.3（L935）把它们判为 **「已知例外 + WARN + 台账」**，**不收编为令牌**。
- 规范 L1239 又明确区分：「本页那四色**不是** `edu_schedule` 的冲突三档，而是**图例四圆点的内联样式**」⇒ 日历这一侧**应**按令牌收编。
- **后果需要一句话定案**：即使 t8 把日历侧全部改成 `var(--token)`，**`session_ext.py` 里的同值十六进制仍留着**（那是登记过的例外）⇒「令牌外色 = 0」的统计**仍会看到它们**。所以要么承认它们是两个不同语义（日历≠冲突档，例外仅在 schedule 侧成立），要么把 schedule 侧也一并收编。**t8 不擅自选。**

### 16.3 已可确定与待定的档位

| kind | 现值 | 目标 | 依据 |
|---|---|---|---|
| session | `#1D6FEB` | **`--brand-500`** | ✅ **规范 L904 已裁**（对比度 4.64 ✓） |
| exam | `#E7650A` | 待定（警告族？） | 规范未裁；且与 `edu_schedule` 例外同值（见 16.2） |
| holiday | `#DC2626` | 待定（危险族？） | 同上 |
| event | `#0E9F6E` | 待定（成功族？） | 规范未裁 |

**交付性质**：四色改成令牌值会**改变渲染**（3/4 与现值不同）⇒ 按规范 §6.6 属 **批 B**（需观感验收），不能当批 A 直接入 `adopted_files`。

**另**：`#1D6FEB`/`#E7650A`/`#DC2626`/`#0E9F6E` 四值也在 `controllers/batch2.py` 出现 —— 那份**已在 captain 此前给 t8 的清单里**，两处应同批处理，避免只改一处留下不一致。

---

## 17. 影子族命名**最终态**：`--shadow` / `--shadow-rgb`（本节取代 §12）

captain 2026-09-15 终版裁定：**不改名**，保持 `--shadow` / `--shadow-rgb`（理由：落地代码已是此态 ⇒ 零改动；同名配对天然成立 ⇒ 判据 8 无需白名单；改名属额外返工）。§12 记录的 `--shadow-ink` 方案**已撤回**，本轮已回退。

### 17.1 最终落地（逐层实测）

| 层 | 值 |
|---|---|
| SCSS | `$shadow: #14182D;`（单一规范名，无别名） |
| CSS 基色 | `--shadow: #14182D` |
| CSS 通道 | `--shadow-rgb: 20, 24, 45`（**由 `$shadow` 派生** ⇒ §6.3 判据 8 同名配对成立） |
| 阴影令牌 | `--shadow-sm/md/lg: … rgba(var(--shadow-rgb), .05/.10/.16)` |
| `custom_home.css:217` | `rgba(var(--shadow-rgb), .06)` |
| **实际消费点**（真机 computed） | `box-shadow: rgba(20, 24, 45, 0.05) 0px 1px 2px 0px` ✓ |
| 残留 `shadow-ink` 引用（全仓） | **0** |

⇒ **回到规范「选项 A（当前落地态、零改动）」**，且比改名版更干净：通道是**规范派生**而非 `var()` 别名，全仓 74 处消费点直接命中规范名。

### 17.2 命名来回的教训（记录以免后来者困惑）

本项命名经历 **`--shadow` → `--shadow-ink`（+ `--shadow-ink-rgb`）→ `--shadow`** 三轮。中间态一度落地过（含为保护 74 处消费点而设的 `--shadow-rgb: var(--shadow-ink-rgb)` 兼容别名），本轮已全部回退、无残留。

**可复用的判断**：若日后又出现改名动议，**先数消费点**——本轮实测 `var(--shadow-rgb)` 全仓 **74 处**（enterprise.css 36 / portal.css 32 / batch3.css 1 / backend_b11.css 1 / custom_home.css 1），任何改名都不是"改两行"，而是一次跨任务协调。**数完再决定**，比改完再回退便宜得多。
