# tests/color — 全站配色取色量具（t12 冻结版）

把审计用的一次性 Tabbit 取色**固化成仓库内可复跑的量具**，并归档一份本地基线，
供 t9 做「同环境 before/after 对照」（依据 docs/audit/ui-color-audit-2026-09-15.md §7.5：
**禁止「本地 after vs 生产 before」跨环境比较**）。

## 文件

| 文件 | 作用 |
|---|---|
| color_audit.py | 量具主程序：selftest / aggregate（带 --expect）/ assert（回归锚点）/ tokens / capture |
| pages.json | §7.3 冻结的页面集合（frozen6 六页；legacy4 是最初归档的四页子集） |
| capture_page.js | 单页取色程序（驱动 Tabbit 真机；输出四属性 + 令牌值 + 对比度对） |
| **baseline-local.json** | **本地基线（canonical，JSON 内 status=CANONICAL）** —— 当前工作树快照，**t9 的 before 用这一份** |
| baseline-local-before.json | 更早快照（15:32，86 色），JSON 内 status=SUPERSEDED，**勿用于 t9**（缺 bodyColor 字段） |
| color_gauge.py | 纯转发别名（captain 曾指定 color_audit.py 为路径，而 eng-backend 引用了旧名，故留此以防断链） |
| **capture_playwright.py** | **替代驱动**（v4-t8 新增）：官方驱动走 `tabbit-cli`，本机实测其返回 `BROWSER_RUNTIME_UNAVAILABLE`（ENV）；本文件用 Playwright 驱动，**测量代码逐字取自 `capture_page.js`**（运行时切片）。⚠ 产物 `driver=playwright`，**只用于绝对判据**，不得与 tabbit 抓的 `baseline-local.json` 做色数相减 |

## 口径（§7.3 冻结；before/after 必须同一支量具）

- **页面集合**：/ 、/apply 、/my/home 、/my/calendar?view=week 、/apps 、/odoo/contacts
- **四属性**（逐元素 computed 值去重计数）：
  text = color ｜ bg = backgroundColor ｜ border = 实际画出的边框色 ｜ anchor = a 元素的 color
- **归一**：rgba(r,g,b,a) → rgb(r,g,b)（合并 alpha 变体）
- **豁免集（captain 2026-09-15 放宽，按归一后匹配）**：归一后为纯黑或纯白的**任何值、含全部 α 变体**
  （rgba(0,0,0,.7) ｜ rgba(255,255,255,.95) ｜ color(srgb 0 0 0 / .097) ｜ #000 ｜ #fff），
  以及 transparent 与全透明 —— 一律豁免。不这样放宽，**黑色遮罩会被误判成「令牌外色」**。
  ⚠ 只豁免「恰好 0 或 255」：rgb(1,1,1)、rgb(254,254,254) 这类近黑近白**仍计入**（与 §7.3 原口径一致）。
- **可见性**：display!=none ∧ visibility!=hidden ∧ opacity!=0 ∧ rect 宽高不全为 0
- **主判据**：令牌外色 = 0（口径无关）；色数收敛作辅助指标

### 三处必须写明的口径细节（审计原脚本未留档，本工具为重建）

1. **border 只记「真的画出来的」边框**：元素无边框宽度时 border-*-color 仍返回 currentColor
   （= 文字色），会把边框列污染成文字列的副本 —— 实测本地 / 得 33 色且大半与 text 列逐项相同；
   生产归档的边框列明显不是这个形态。现按「某一侧 border-*-width > 0 才记该侧颜色」计数。
2. **anchor 追加 " | -"**（来源变量未知），与生产归档 schema 字面一致；计数前会剥掉 " | " 之后的内容。
3. **渲染稳定后才取**：高负载下门户页元素数会缓慢增长，固定 sleep 会取到偏小的读数；
   现改为「元素数连续 5 次采样（每 600ms）不变」才取。

## 用法

    # 1) 先证量具（离线，秒级；不连站点、不代表环境可用）
    python3 tests/color/color_audit.py selftest

    # 2) 复算 §7.3 口径 + 门禁
    python3 tests/color/color_audit.py aggregate docs/audit/ui-color-raw-2026-09-15.json --set legacy4 --expect 53
    python3 tests/color/color_audit.py aggregate tests/color/baseline-local-before.json --set frozen6

    # 3) 回归锚点（captain 2026-09-15 追加）
    python3 tests/color/color_audit.py assert  tests/color/baseline-local-before.json --set frozen6
    python3 tests/color/color_audit.py tokens  tests/color/baseline-local-before.json --set frozen6

    # 4) 真机取色（需本地实例就绪；先跑 code-map §10 的探活三步）
    python3 tests/color/color_audit.py capture --base-url http://127.0.0.1:8069 --out tests/color/baseline-local-after.json

退出码：**0**=通过 ｜ **1**=量具/门禁失败（读数不一致）｜ **2**=ENV（取色器不可用／未登录／缺页／存档缺字段）。

## 量具自证（selftest 通过）

> **条数订正（2026-09-28 v4-t8）**：本行原写「**44/44**」，代码里的 `SELFTEST_CASES` 当时已是 **50**，
> 本轮为「禁用色 ④」又加 2 条 ⇒ **当前 52/52**（`python3 tests/color/color_audit.py selftest` 实测）。
> **以代码里的常量与实测输出为准**，不要引用本节的历史数字（这正是本节下方「引用数字规范」要防的那类错）。

四条归一化 + 剔除 + 口径绑定
+ **对比度四条**（黑白 = 21.000 标定、两对回归对数值与审计相符、跨写法等价）
+ **锚点恒等三条**（同值 PASS／退回 core #6b7385 必 FAIL／空值必 FAIL）
+ **回归对两条**（命中必被抓到／干净样本不误报）
+ **样本外三条**（color-arch 的 3 对数值与发现值相符、出现必被命中、不得把实色误判为半透明对）
+ **焦点环两条**（贴按钮低对比必被判违规／高对比不误报）
+ 门禁会红 + 归档生产基线 legacy4=53 / frozen6=69。

> 「门禁会红」「锚点退回必红」「干净样本不误报」「实色不得误判为半透明」都是刻意构造的反向断言：
> 门禁若不会失败就不是门禁，若什么都报也不是。断言条数写死常量 `SELFTEST_CASES`（**现值 52**，见上方条数订正），**条数漂移即 exit 1**。

## 回归锚点（captain 2026-09-15 追加）

① **锚点恒等（outcome 级）**：门户代表页（/my/home、/my/calendar）上 **body 的实际文字色**
   `getComputedStyle(document.body).color` 必须等于 --text-3 的计算值（且非空）。

   ⚠ **读取位置已修正（captain/eng-web 2026-09-15 真机自证）**：修复后的声明会落在 **body 元素**上而非 :root，
   此时 **documentElement 上的 --body-color 可能仍不是我们的值** ⇒ **旧实现只读 documentElement 会误判**。
   body 的 used color 是最终渲染结果，与声明落点无关，才是可信锚点。documentElement 的值仍会打印，但**只作诊断、不参与判定**。

   背景：custom_home.css 原有 :root, [data-bs-theme] body{ --body-color:#5E6779; … }，
   靠「同特异度 (0,1,1) + 源码顺序」压过 core 的 [data-bs-theme="light"] body。
   若这条失守，body 文字色会**无声退回** core 的 #6b7385（压 --bg #F4F7FA = 4.42 ✗，不报错）。

   ⚠ **两种失败模式必须区分（eng-web 2026-09-15 精确化）—— 只测 A 会产生错误的教训**：

   | 模式 | 形态 | 后果 |
   |---|---|---|
   | **A** | 退化成**裸 :root** | body 拿到的是「继承值」，被 core 覆盖 ⇒ 4.42 ✗ |
   | **B（本次实际发生的）** | **保留 [data-bs-theme] body，但去掉 :root > body，且规则排在 bundle 最前** | 同样 4.42 ✗ |

   **B 的机制**：服务端 html 元素只有 data-website-id / dir，**没有 data-bs-theme 属性**
   ⇒ 选择器里 [data-bs-theme] body 那半**根本不匹配** ⇒ 真正生效的只有 :root 半（落在 html 上）；
   而令牌源经 _assets_primary_variables **必然排在 bundle 最前** ⇒ 后出现的 Bootstrap :root 同特异度胜出 ⇒ body 继承 #6b7385。

   > 关键：B 的选择器**看起来是对的**（[data-bs-theme] body 谁都以为能压过 core 的 [data-bs-theme="light"] body），
   > 它在 custom_home.css 时代也**确实能用 —— 仅因为它当时排在 bundle 末尾、靠源码顺序赢**。迁到最前就静默失效。
   > ⇒ 只测 A 会让人以为「只要别写裸 :root 就行」；**B 说明光保留半选择器也不够**。
   > 判据本身对 A、B 都能红（两者可观测结果相同），但**记录必须写 B 才是同构形态**。

   专项断言（selftest 里各一条，两个方向都钉死）：
   · documentElement 的 --body-color 是旧值、但 body.color 正确 → **PASS**（旧实现会误判为 FAIL）
   · documentElement 正确、但 body.color 错误 → **必须 FAIL**（不许被声明落点骗过）
   · bodyColor 缺失（旧存档）→ **FAIL**（不得静默通过）

   **三条读数实测表（2026-09-15 复测，六页；① 为「框架值」不判定）**：

| 页 | ① documentElement --body-color | ② body --body-color | ③ **body.color（判据）** | ③ 判定 |
|---|---|---|---|---|
| home | #5E6779 | #5E6779 | rgb(94, 103, 121) = #5E6779 | PASS |
| apply | #5E6779 | #5E6779 | rgb(94, 103, 121) = #5E6779 | PASS |
| my_home | #5E6779 | #5E6779 | rgb(94, 103, 121) = #5E6779 | PASS |
| calendar | #5E6779 | #5E6779 | rgb(94, 103, 121) = #5E6779 | PASS |
| apps | #5E6779 | #5E6779 | rgb(94, 103, 121) = #5E6779 | PASS |
| contacts | **#212529** | #5E6779 | rgb(94, 103, 121) = #5E6779 | PASS |

   ⚠ **一处与预期的偏差，如实记录**：captain 预期 ① 应为框架灰 **#6b7385**（理由：令牌源排在 bundle 最前，
   Bootstrap/主题的 :root 在后压掉）。**实测 ① 并非 #6b7385** —— 前端五页 ① = **#5E6779**（即我们的值），
   仅 /odoo/contacts 为 **#212529**（后台 Bootstrap 默认）。也就是说：**前端页上 :root 那半并没有被压掉**；
   真正被压掉的是**后台页**，而那里正是靠 `[data-bs-theme] body` / `:root > body` 这半把值送到 body 才救回来。
   ⇒ 这不构成回归（③ 六页全 PASS，且全程未见 #6b7385），但它说明「① 必然是框架灰」这个推断在**前端页不成立**。
   结论不受影响：① 本就不参与判定，判据是 ③。

② **对比度回归对**：#6b7385 / #F4F7FA、#0E7BF2 / #F4F7FA 两对**出现即 FAIL**。
   数值已由本工具独立复算核对：**4.4227** 与 **3.8043**，与审计所称 4.42 / 3.80 相符。
   同时扫出所有实测 (前景, 有效背景) 对中 < 4.5:1 的文本对（服务「对比度不达标 6→0」这条验收指标）。

### 锚点回归的完整经过（这条门禁真抓到了一个回归，并验证了修复）

| 时刻 | --body-color | --text-3 | 判定 |
|---|---|---|---|
| 15:32（首次实测） | #6b7385 | #5E6779 | **FAIL** |
| 15:39（eng-web 修复后） | **#5E6779** | #5E6779 | **PASS** |

15:32 那次正是 captain 预警的**无声回退**：custom_home.css 的 --body-color:#5E6779 规则随 :root 迁走，
而 brand_tokens.scss 的 --body-color: var(--text-3) 尚未落到 documentElement ⇒ 退回 core 的 #6b7385
（压 --bg #F4F7FA = 4.42 ✗，且**不报任何错**）。已即时告知 eng-web 与 captain；
eng-web 修复后，15:39 复测六页全部转为 **#5E6779 = --text-3**，锚点失败数 0。

> 这条记录本身就是门禁价值的证据：**先证量具会红 → 抓到真回归 → 修复 → 复测转绿**，
> 而不是「工具写完就宣布通过」。t9 必须继续保持此断言为 PASS。

> **可迁移的教训（captain 要求写进 t9 报告）**：锚点必须落在**真正承载渲染的那个元素**上 ——
> 这里 --body-color 的声明最终落在 **body**，而 documentElement 上是框架自己那份值。
> 只读 documentElement 会给出一个**与视觉无关**的判定（本次就是它把「已修好」误报成红）。
> **判据要读 outcome（渲染结果），不要读声明的落点。**
>
> **最佳教材就是 /odoo/contacts**：该页 documentElement 的 `--body-color` 是 **#212529**（Bootstrap 默认），
> 而 `body.color` 仍是 **rgb(94,103,121) = #5E6779** —— 同一页上「声明落点」与「渲染结果」**当场分叉**。
> 只读 documentElement 会据此报红（假警报）；读 outcome 才是真相。**此例请直接进 t9 报告。**

注：/odoo/contacts（后台）documentElement 上 --body-color 仍是 Bootstrap 的 #212529，
但该页不在锚点判定的两页内（判定面是门户的 /my/home 与 /my/calendar）；后台另有一套变量口径。

对比度读数（同一快照）：**不达标文本对 15 组**（含审计 §3 的 #B6B0B0/#FEFEFE = 2.12、
金色系 1.02–1.42、rgb(78,90,112) on rgb(17,24,39) = 2.55 等），**5 对回归对命中 0**。

③ **样本外不合格对**（color-arch 本轮发现，不在审计 §3 原始 6 条内）—— 同样「出现即 FAIL」：
   #c27d00 / rgba(255,165,0,.18) ｜ #ad7000 / rgba(255,165,0,.22) ｜ #d91f1f / rgba(217,31,31,.12)。
   数值已独立复算核对：**2.9703 / 3.5297 / 4.1557**，与所称 2.97 / 3.53 / 4.15 相符。
   这三对的背景是**半透明叠加**，故回归对匹配按 rgba 四元组精确比对（**不合并 alpha**），
   并有专门断言保证「不得把实色 rgb(255,165,0) 误判成半透明回归对」。

④ **焦点环对比度**（WCAG 1.4.11 非文本对比度，阈值 **3:1**）：取色器会 focus 每页前 12 个可聚焦控件，
   读 outline 环色与其有效背景。**已 live 验证**（2026-09-15 15:4x 实测）：

| 页 | 环色 | 控件背景 | 对比度 | 判定 |
|---|---|---|---|---|
| /odoo/contacts | rgb(0, 95, 204) | rgb(14, 123, 242) | **1.46** | ✗ |
| /odoo/contacts | rgb(0, 95, 204) | rgb(113, 75, 103)（Odoo 原厂紫） | **1.21** | ✗ |

   ✅ **覆盖边界（两种形态都覆盖，缺口已闭合）**：
   · **(a) outline 形态** —— outline-width>0 且 outline-style!=none；
   · **(b) box-shadow 形态** —— 非 inset、offsetX==0 && offsetY==0、且**画得出来**（alpha>0 且 blur/spread>0）。
     这是 Bootstrap 5 / Odoo 以及 **backend_b11.css:58**（box-shadow: 0 0 0 .2rem rgba(14,123,242,.35)）用的形态 ——
     **只覆盖 (a) 会得到「没抓到」的假绿**，因为我们真要修的那圈环恰恰是 (b)。
   · 环色带 alpha 时，先按 alpha **合成到参照背景**再比 —— 这正是 color-arch 推算 1.08 用的算法，故两者可比。
   · 全透明环（Chrome 会输出 rgba(0,0,0,0)）在**取色侧与判分侧双重过滤**，否则会得到一批 1.00 的假违规。

   **实测（2026-09-15，box-shadow 覆盖补齐后）—— 5 组不达标**：

| 页 | 形态 | 环色 | 参照背景 | ×n | 对比度 |
|---|---|---|---|---|---|
| home | box-shadow | rgba(12, 109, 215, 0.25) | rgb(255, 255, 255) | 10 | **1.43** ✗ |
| apply | box-shadow | rgba(12, 109, 215, 0.25) | rgb(255, 255, 255) | 10 | **1.43** ✗ |
| /odoo/contacts | outline | rgb(0, 95, 204) | rgb(14, 123, 242) | 4 | **1.46** ✗ |
| /odoo/contacts | box-shadow | rgba(194, 198, 202, 0.5) | rgb(255, 255, 255) | 1 | **1.29** ✗ |
| /odoo/contacts | outline | rgb(0, 95, 204) | rgb(113, 75, 103)（Odoo 原厂紫） | 1 | **1.21** ✗ |

   > 覆盖率对比：**只覆盖 outline 时只有 2 组**；补上 box-shadow 后是 **5 组** —— 差的那 3 组正是本轮要修的那类环。
   >
   > 关于 captain 提到的 **1.08**：那是 **color-arch 的合成推算**（rgba(14,123,242,.35) 合成到 #0C6DD7 按钮面 = #0D72E0，
   > 对按钮面 1.08），**不是直接读数**，可能没有对应的可测元素。本工具已把它作为**数值口径校准**写成 selftest 断言
   > （实算 1.08，与推算相符 ✓），故「1.08」在判分里不单列回归对；判分以**上述 5 组实测**为准。

## 本地基线（baseline-local.json）—— t9 的 before

| 项 | 值 |
|---|---|
| **标签（t9 报告必须原样带上）** | **「captured after t3 changes；用于度量 t4–t8 的效果」** |
| 冻结 | **已冻结**（captain 2026-09-15 裁定）：后续量具加字段/断言**只补字段、不重取读数**；确需重取须先报 captain |
| 采集时间 | 2026-09-15T15:50:33+08:00 |
| 实例 | 容器 edu19-clone-web-1（image odoo:19），Odoo **19.0-20260817** |
| 数据库 | edu19（config/odoo.conf 的 db_name） |
| 基址 | http://127.0.0.1:8069 |
| 工作树 | 修订 3c449ce27e86 + **2 个未提交改动**（t3–t8 进行中） |
| 锚点字段 | 含 outcome 级 bodyColor（body 的 used color），供 ① 判定 |
| 登录态 | 公开页（/ 、/apply）为**游客**（按域清 127.0.0.1 cookie 并验 /my/home → 303）；其余以 faculty@local 登录 |
| 页面校验 | 六页标题全部正常（永约学坊 / 在线报名 / 教师工作台 / 校历 / 应用面板 / 联系人），**无 Page Not Found** |

| 页面 key | URL | visible | text | bg | border | anchor | focusSampled |
|---|---|---|---|---|---|---|---|
| home | http://127.0.0.1:8069/ | 262 | 24 | 11 | 10 | 10 | 1 |
| apply | http://127.0.0.1:8069/apply | 283 | 16 | 13 | 9 | 7 | 1 |
| my_home | http://127.0.0.1:8069/my/home | 350 | 24 | 13 | 13 | 8 | 0 |
| calendar | http://127.0.0.1:8069/my/calendar?view=week | 386 | 22 | 18 | 11 | 9 | 0 |
| apps | http://127.0.0.1:8069/apps | 170 | 9 | 6 | 5 | 3 | 0 |
| contacts | http://127.0.0.1:8069/odoo/contacts | 1128 | 7 | 9 | 5 | 1 | 5 |

**本地基线全站色数（§7.3 口径）= 79**（辅助：不剔黑白 82 ｜ 只算 text 41）。
> 注：豁免集放宽前同数据为 **80** —— 差值 1 就是那条被漏判的 color(srgb 0 0 0 / 0.097647)（带 α 的纯黑）。
> 生产冻结读数不受影响：legacy4 = 53、frozen6 = 69 均**未变**（生产里那两个 color(srgb …) 是深色，仍正确计入）。
对标生产六页 = **69** —— 两者不同环境，**不得直接相减**（§7.5）；本地基线只与本地 after 比。

> 更早一次快照（15:32）为 **86 色**（豁免集放宽前同数据为 87），保留在 baseline-local-before.json，
> 该文件已带 `status: SUPERSEDED` 标记，**请勿用于 t9**（它没有 outcome 级锚点字段 bodyColor）。
> 两次差 7 色主要是 eng-web 这半小时内的令牌收口 + 该页对比度对的微小波动；
> **t9 请以 baseline-local.json（80）为准**，因为它由当前这版量具（含 tokens/contrast/focus 字段）抓取，
> 与 after 完全同口径。

## 为何没有「改动前」基线（契约第 4 条未达成，已如实上报）

契约要求：若 t3 已改动工作区，就用**改动前 git 修订的 worktree** 取基线。该路径**在本环境不成立**，
两次尝试都失败，证据如下：

1. **receipt 回放（工具 bug，已修）**：tabbit 按 (task, request-id) 命中并**回放**上一次的 receipt。
   我最初复用固定 request-id，于是「重取」拿回的是 15:18:59 的旧结果（连 startedAt 都是旧的），
   一度让我误判「干净重取与污染版完全一致 ⇒ t3 改动等值」。**该结论作废**。
   修复：RUN_ID + _rid()，每次 capture 用全新 request-id。
2. **worktree 实例不可比**：用同一 edu19 库挂上 376e718 的 addons 起容器，挂载已断言生效
   （容器内 /mnt/custom-addons/edu_portal 存在），但该实例仍**不重现 live 的页面表面**：
   /my/calendar?view=week 与 /apps 返回 **Page Not Found**、/my/home 退回 **stock Odoo portal**
   （标题 My Portal 而非 教师工作台）、且**我们的令牌全部缺席**（--body-color = Bootstrap 默认 #212529，
   --text-3 为空）。原因：数据库的模块状态与新/旧 addons 树不一致，旧树起不来同样的路由与资产。
   ⇒ 该实例的读数**与 live 不可比**，不能用作基线（该中间产物已弃用并重取）。

**结论**：本环境无法复现「改动前」的 live 渲染。因此归档的是**同一实例（live）上的当前快照**，
并在 JSON 的 capture_note / git_revision / git_dirty 字段里写清出处。
t9 的 after 只要**用同一支量具、同一 base_url** 取，就是合法的同环境对照；
代价是基线已含 t3 的首批改动，before→after 的**色数差会被低估** —— 但主判据「令牌外色 = 0」不受影响。

另：t3 改动在取色口径下**是否等值**，本轮没有拿到可信的实测证据；唯一站得住的证据是
令牌值对比（52 个同名令牌 45 个完全相同、7 处为别名化/阴影 alpha），那是源码级比对，不是取色读数。

## 回归监控项（captain 2026-09-15 登记，按 = 0 核）

与「设计上不许出现的令牌外色」（REGRESSION_PAIRS）不同，这里放的是**已归因、已派活、在途待修的已知缺陷**。
登记目的是**点名跟踪 + 验证消失**：assert 会逐项打印「仍出现 x N = 比值 ｜ 归口」，消失则打印「已消失」。

| 前景 | 背景 | 实算 | 归口 |
|---|---|---|---|
| rgb(12, 109, 215) | rgb(207, 229, 252) | **3.89** | t4 批B / t8 —— 改用 --brand-action-hover 或 --brand-700 |

**判据 B 类**（蓝调面承载文字时 --brand-action 不达标）同族还有：--fill-active 4.33 ｜ .10 叠层 4.43 ｜ b11 active 4.27。
来源：t3 的色板接线把 /apply 按钮变成 #0C6DD7 后**暴露**出来。
**t9 判分按「监控项仍出现 = 0」核**；当前实测：**仍出现 1**（即上表这一项）。

## 焦点环回归监控项（captain 2026-09-15 指定，t5 收口）

**登记理由（captain 原话）**：若只覆盖 outline，我们会以为焦点环没问题就发布了。
下表 5 组已写入 MONITOR_FOCUS，assert 的 ③b 段逐项点名「仍出现 xN = 比值 ｜ 归口」，
**t5 修完后应全部打印「✓ 已消失」** —— 收口可验证。

| 页面 | 形态 | 环色 | 参照背景 | ×n | 实算 | 归口 |
|---|---|---|---|---|---|---|
| home | box-shadow | rgba(12,109,215,.25) | rgb(255,255,255) | 10 | **1.43** ✗ | t5 / backend_b11.css 家族 |
| apply | box-shadow | rgba(12,109,215,.25) | rgb(255,255,255) | 10 | **1.43** ✗ | t5 / backend_b11.css 家族 |
| /odoo/contacts | outline | rgb(0,95,204) | rgb(14,123,242) | 4 | **1.46** ✗ | t5 |
| /odoo/contacts | box-shadow | rgba(194,198,202,.5) | rgb(255,255,255) | 1 | **1.29** ✗ | t5 |
| /odoo/contacts | outline | rgb(0,95,204) | rgb(113,75,103) 原厂紫 | 1 | **1.21** ✗ | t5 |

> 覆盖率对照（这条要进交付报告）：**只覆盖 outline 时是 2 组；补上 box-shadow 后是 5 组** ——
> 差的那 3 组正是 btn-primary 那圈环（backend_b11.css 家族），即 t5 要修的那类。
> 若当初只覆盖 outline，**我们会以为焦点环没问题就发布了**。

## ①b 校名/链接色锚点：**必须写「== --brand-action」，不能写「!= #0F34C3」**

eng-web 2026-09-15 建议新增此锚点，理由与陷阱都很具体：

- **before**（376e718）：a.navbar-brand 计算色 = rgb(15,52,195) = **#0F34C3**（审计 §1.3 点名）；
- **after（t3）**：应为 rgb(12,109,215) = **#0C6DD7** = --brand-action（令牌内）。

⚠ **#0F34C3 不是谁手写的** —— 它是 auto-contrast(o-cc1-link) **算出来的**。由此有一条关键因果：

| 做法 | 结果 | 是否令牌外 |
|---|---|---|
| 只把 o-cc1-link 改成令牌蓝、**未进 auto-contrast 排除表** | 派生出**另一个蓝 #0955A7** | **仍是令牌外** |
| 走 $o-user-color-palette（键名自动 join 进 $o-we-auto-contrast-exclusions） | **原样返回令牌值** | 令牌内 ✓ |

⇒ **判据 = 校名色 == --brand-action 的 rgb**。
**不得**写成「不再是 #0F34C3」—— 那会被 #0955A7 蒙混过关（这正是「抓不住真问题的门禁」的又一例）。

实现：capture 增记 brand 字段（a.navbar-brand 的 computed color）；assert 的 ①b 段按上式判定，
并把 #0F34C3 / #0955A7 / #0A217C 三个陷阱值**具名报出**（命中时提示是哪个派生蓝）。
旧存档无 brand 字段 ⇒ **报 ENV（该项不可判），绝不静默通过**。机制与两种写法对照读数见 docs/plans/color-tokens-t3.md §10。

## 探针 F：必填字段边框 —— captain 裁定的「三级降级」

背景：读 .o_required_modifier 的 **border-top-color** 会得到 currentColor（该边根本没有边框）⇒ **空判据**。
captain 裁定按可行度**逐级降级，绝不保留空判据**：

| 级别 | 做法 | 本轮结果 |
|---|---|---|
| 一级 | 定向读**真正画那条边**的元素 + 先断言 width>0 | **已尝试、ENV 受阻**：/odoo/contacts/new 首屏在本机**两次撞 170s 执行器硬上限** |
| 二级 | **产物级**：确认该值/变量已换到令牌值 | **✔ 已实现并通过**（见下） |
| 三级 | 从 t9 判据删掉，报告写「本地不可判定，需生产复测」 | 本轮**不需要**（二级已成立） |

### 产物级发现（决定性线索，也解释了为什么一级读 top 会失败）

产物里 .o_required_modifier 的边框是 **border-bottom**，不是四边：

    border-bottom: 1px solid #0C6DD7;                 ← 早期规则（字面量）
    --o-input-border-color: var(--brand-action);      ← 后续规则（令牌化）
    **border-bottom-color: var(--brand-action);**      ← **最后一条**

⇒ 这正是「读 top 得到 currentColor」的原因 —— **边只在 bottom**。一级探针若继续做，应读 bottom 边。

二级判定实测（逐 bundle）：

| bundle | 期望 | 实得 | 解析方式 | 判定 |
|---|---|---|---|---|
| web | --brand-action #0C6DD7 | #0c6dd7 | var(--brand-action) | **PASS** |
| web_print | --brand-action #0C6DD7 | #0c6dd7 | var(--brand-action) | **PASS** |

> 判据**能红**：selftest 断言「若是原厂紫字面量 ⇒ FAIL」「产物无 border-bottom 规则 ⇒ 明确报 ENV、不得静默通过」。
> 故这不是空判据 —— 满足 captain 的二级要求。

## 探针 F-α：必填边框的**一级取样规格**（eng-backend 从产物定位，供将来做 DOM 探针）

eng-backend 直接 grep 编译产物，找到根因规则：

    .o_input{border: var(--border-width) solid var(--o-input-border-color);
             border-width: 0 0 var(--border-width) 0;}   /* 只有底边 */

（与我独立得到的结论一致 —— 我读 border-top-color 得到 currentColor 就是因为**只有底边**有边框。）

**可直接照做的取样规格**：

| 项 | 值 |
|---|---|
| 页面 | **/odoo/contacts/new**（该页 required=1；/odoo/contacts 为 0） |
| 元素 | .o_required_modifier input.o_input（或其后代任意 .o_input） |
| 读的属性 | **border-bottom-color**（不是 top），**并同时断言 border-bottom-width > 0** |
| 期望值 | **rgb(12,109,215) = #0C6DD7** |

> 附注（eng-backend）：产物里 :root{--o-input-border-color: #ccc} 是原厂默认（$o-form-lightsecondary）；
> 其 .o_web_client 覆盖让后台输入走 --border-control；#ccc 本次**未渲染**，属潜在项。
> 现状：一级因 ENV 未跑通，已按 captain 裁定降到**二级产物级（探针 F）**并通过；此规格留给 ENV 转好时执行。

## 探针 E：.text-* 状态色类的**产物级**映射（captain 2026-09-15 改判）

为什么改判：冻结页集上 .text-success 等**根本没有元素**（/odoo/contacts 实测全 0；
/odoo/contacts/new 也只有 textDanger=1、textSuccess=0）⇒ **不能作渲染取样判据**（after 时无样本可判）。
而 $o-theme-text-colors 本就是**编译期 map** ⇒ **产物里的映射就是决定性证据**，且不依赖任何页面渲染。

⚠ 方法要点：产物由 screen + print **两个 bundle** 串成，必须**逐 bundle 各取最后一条** color 规则；
跨 bundle 取「最后一条」会拿错（实测两者内容恰好一致，但那是巧合、不能依赖）。

实测（2026-09-15）：

| 类 | 期望令牌 | 实得 | 解析方式 | 判定 |
|---|---|---|---|---|
| .text-success | --success #127A50 | #127a50 | var(--success) | **PASS** |
| .text-danger | --danger #C0272D | #c0272d | var(--danger) | **PASS** |
| .text-warning | --warning-ink #8F5700 | #8f5700 | var(--warning-ink) | **PASS** |
| **.text-info** | --info #0E7BF2 | **#5e6779** | **字面量**（非 var） | **FAIL** |

> ⚠ **.text-info 是一处真实不一致**：它落到 **#5E6779（= --text-3，灰）**，并非 --info；
> 而且是**字面量**写法（前三个都已是 var(--token) 形式）⇒ 既没用对语义令牌、也没令牌化。
> **待裁定**：#5E6779 本身**是一个合法令牌值**（--text-3），故「等于令牌值」按字面理解它算通过；
> 若要求「等于**该语义**的令牌」则不通过。**请规范方（color-arch）明确 .text-info 应有的语义**，再据此定判据。

### ⚠ 规则顺序实测：.text-success 的**最后一条**确实是 var(--success)（更正一条外部说法）

eng-backend 提醒「后台产物里 .text-success 之后还有一条**更晚的** .text-success{text-transform:none; color:#5E6779 !important}（主题层），
故后台取样会读到 #5E6779」。**我逐 bundle 按出现顺序实测，这个顺序说法不成立**：

| # | 规则（.text-success{...}） | 来源 |
|---|---|---|
| 1 | --color: RGBA(18,122,80,…); color: var(--color) !important | bootstrap 层 |
| 2 | text-transform: none; **color: #5E6779 !important** | 主题层 |
| 3 | margin: 2px 10px | （无 color） |
| 4 | **color: var(--success) !important** | 我们的令牌层 |

⇒ **#5E6779 是第 2 条，不是「更晚」**；第 4 条 var(--success) 才是最后一条（screen 与 print 两个 bundle 顺序一致）。
同特异度按源码顺序，最后一条胜出 ⇒ **两个 bundle 的有效值都是 #127A50**。
故：**探针 E 的「逐 bundle 取最后一条」逻辑正确**，其 .text-success PASS 读数成立；
「后台取样会读到 #5E6779」这一推论不成立 —— 后台有效值同样应是 #127A50。
（**若有实测反证请给我**：可能涉及 bundle 之外的加载顺序或额外主题层，我会以实测为准更新。）

### 渲染取样点：本方模板里**确实有** .text-success / .text-danger 用法（已 grep 到）

captain 裁定的「补探针条件」已满足，候选取样页：

| 文件:行 | 用法 | 候选页 |
|---|---|---|
| edu_portal/views/downloads_portal.xml:164 | fa-check-circle **text-success** | /downloads（注意可能在 t-if 内） |
| edu_portal/views/downloads_portal.xml:168 | fa-times-circle **text-danger** | /downloads |
| edu_portal/views/calendar.xml:257/264/269 | form-label 里的必填星号 **text-danger** | /my/calendar（**属 frozen6**，但星号可能在模态里） |
| edu_portal/views/edu_portal_templates.xml:516 | **text-success** | 门户模板（常驻？需实机确认） |
| edu_portal/views/batch2.xml:862 / batch3.xml | **text-danger** | 教务批处理页 |
| **edu_life/views/portal_templates.xml（多处）** | **text-success** | **/my/checkins 、/my/journals 、/journals/review/**（eng-backend 全仓普查） |
| **edu_portal/views/ledger.xml:178,395** | **text-success** | 台账页（ledger） |

> 注意：**模板里有 ≠ 渲染出来**（多数包在 t-if 里）。是否真的渲染，需实机确认后才可作取样点。
> 当前以**产物级（探针 E）**为准；找到确实渲染的页面后，再补一条定向渲染探针即可。

## 探针 D：产物合理性检查（eng-web 建议，已采纳）

背景：**Odoo 对 SCSS 编译错误是静默丢弃** —— 单文件编译失败**不会**让 -u 失败，只会让那份 CSS 从产物里消失。
若取数恰好撞上「编译失败后的残缺旧版」，before 会偏低、after 会显得凭空变好。⇒ 取数前先证明产物是完整的。

⚠ **标记必须分前后台**：eng-web 建议的 #wrapwrap.o_portal 实测在**后台** bundle 里 **count=0**
（它是前台选择器，前台 1528 处）；不分场合使用会变成一条**永远红的假判据**。

| 产物 | 标记 | 实测 |
|---|---|---|
| backend | --brand-action / --brand-500 / --teal-500 | 62 / 14 / 2 ✓ |
| frontend | #wrapwrap.o_portal / --brand-action / --teal-500 | 1528 / 51 / 6 ✓ |

实测 verdict：**PASS：产物含全部自定义标记且非空，是完整产物**（后台 2,354,079 B）。
另有下限校验（<100,000 B 即 FAIL），避免「非空但极短」蒙混。

## 探针 C：字面 SCSS 变量指纹（**必须限定到本方文件**）

判据：编译产物里出现 $o- / $brand- **字面字符串** ⇒ 该 SCSS 变量未被插值 ⇒ 浏览器取空值。

⚠ **整包跑会永久命中官方误报** —— 不限定范围的话，t9 复测会天天亮红灯，最后必然被人忽略，**那门禁就白设了**。
所以本探针**按源文件归属判定**：产物保留了 /* /path/to/file.scss */ 源标注（实测 1001 个），
取每个命中点**之前最近**的那个标注作为归属依据。

实测（2026-09-15，combined sha256=8a91c7a1…）：

| 分桶 | 数量 | 说明 |
|---|---|---|
| **ours（本方文件）** | **0** | **判据面：必须 0** |
| upstream_known | 4 | 2 处 ×2 个 bundle，**均来自 Odoo 官方源码**，按官方快照记录、不计入 |
| unclassified | 0 | 归属不明（无源标注）——保守起见不允许静默放行 |

已记录的上游命中（**仅记录不修**：odoo/addons 是官方快照，本仓纪律基座不改）：

| token | 源文件 | 影响 |
|---|---|---|
| $o-gray-200 | /website/.../website_builder_action.dark.scss | 网站预览器深色底色 |
| $o-theme-text-colors | /im_livechat/.../livechat_channel_info_list.scss | livechat 激活边框 |

> 这 2 处**不是噪声，是上游缺陷的现场证据**：它们是在**官方编译产物里直接观测到「自定义属性值不解析」**，
> 比容器里的合成用例强得多 —— 是规范「自定义属性值必须 #{} 插值」这条规则的**第一份真实产物证据**。

探针自带反向断言（probes.py --selftest，4/4）：上游命中归入 upstream_known 不清算本方；
**本方文件的字面变量必被抓到**；干净产物不误报；归属不明必进 unclassified 而非静默放行。
> 其中「本方必被抓到」这条**当场抓到我自己的 bug**：源标注正则原先只匹配 .scss，
> 而本方门户文件是 .css（custom_home.css）⇒ 本方命中会被误归到 unclassified。已修。

## ⚠ 分层报告口径 与「每个数字带三标签」规则（captain 2026-09-15 裁定）

起因：color-arch 指出 baseline-local.json 的 capture_note 写着「captured after」⇒
**它是 after t3 的快照，不是全量改造的 before**。标签本身是对的，但**引用方式**必须分层。

### 规则：任何色数数字必须自带三个标签 —— **环境 + 页面集 + 量具**

> 否则「本地 79 / 本地 86」对上「生产 53 / 生产 69」会得出**无法解释的读数**。

| 数字 | 环境 | 页面集 | 量具 / 快照 | 用途 |
|---|---|---|---|---|
| **69** | **生产** edu.example.org | frozen6（6 页） | §7.3 口径，归档于 ui-color-raw-2026-09-15.json | **全量改造的 before** —— 与**发布后生产复测**对照 |
| **53** | **生产** | legacy4（4 页） | 同上 | §7.3 headline；--expect 53 门禁 |
| **79** | **本地** 127.0.0.1:8069 @15:50:33 | frozen6（6 页） | 当前量具（含 tokens / contrast / focus） | **只度量 t4–t8 的效果**；**不得**当全量 before/after |
| **86** | **本地** @15:32:30 | frozen6（6 页） | 早期快照（**缺 bodyColor**） | **仅色数交叉校验**；**不用于锚点** |

### 分层判定

1. **主判据「令牌外色 = 0」是绝对判据 ⇒ 不需要 before**（只依赖 after 快照 + 令牌源）。
2. **辅助数「本地 79 → ≤28」只度量 t4–t8 的效果**，引用时**必须连标签一起写**。
3. **全量效果** = 生产 before（frozen6 69 / legacy4 53）对 **production after**（发布后复测）。
4. **本地 15:32 的 86 色**（放宽豁免前为 87）**只作色数交叉校验**。
5. **不重采 before**：旧 addons 树 + 同库的 worktree 实例已实测**不重现 live 表面**
   （2/6 页 404、退回 stock Odoo、令牌全缺席）⇒ 没有可用的「真 before」本地实例。**此路已证伪，不必再试。**

## 判据 B 类：浅蓝调面上的 --brand-action（权威源 = color-arch 规范 §3.2）

规范位置：docs/plans/color-system-v4.md 第 567-571 行（矩阵）、第 581 行（处置）、第 583 行（临界值）。
**本工具已逐对独立复算，与规范完全一致，无差异。**

| 面 | 值 | 实算 | 判定 |
|---|---|---|---|
| --fill-active | #E8EFF8 | **4.3336** | ✗ |
| rgba(--brand-500-rgb,.10) 叠白 | #E7F2FE | **4.4284** | ✗ |
| b11 active 面 | #E1EEFF | **4.2720** | ✗ |
| --brand-50 | #EAF4FF | **4.5127** | △ **临界通过**，余量仅 **+0.0127** |

规范处置（§3.2）：浅蓝调面上的文字**一律改用 --brand-action-hover #0A63CC**（4.59–5.15 ✓）。
上表前三对已登记为 MONITOR_PAIRS（归口 t4 批B / t8）。

> ⚠ **#EAF4FF 那一对是「临界通过」，不是不合格** —— 但它余量只有 **+0.0127**，
> 意味着**任何舍入级改动都可能把它翻成不达标**。规范改用 hover 档是**工程策略**（余量 0.65），不是因为它违规。
> 这条已写成 selftest 断言钉住，防止有人后来「顺手」把它改回去。

## t9 探针可观测性表（2026-09-15 真机实测，供 after 排期）

eng-backend（t5）请求的 after 探针，我提前跑了一遍，把「能不能在本地测到」先钉下来：

| 目标 | 冻结页集 /odoo/contacts | /odoo/contacts/new | 结论 |
|---|---|---|---|
| 导航栏下拉 button.o-dropdown.dropdown-toggle | **count=8 可读** | — | ✅ **本地可观测**；.o_main_navbar 实测 bg=rgb(12,109,215)=**#0C6DD7**，**不是**原厂紫 |
| .text-success | **count=0** | **count=0** | ❌ **两页都取不到** —— 需指定承载页面，否则 after 无从取样 |
| .text-danger | count=0 | **count=1** | ⚠ 只有 /odoo/contacts/new 可用 |
| .o_required_modifier（必填边框） | **count=0** | **count=1** | ⚠ 只有 /odoo/contacts/new 可用 |
| ~~#yy-apps-chip（t8 carve-out）~~ | **2026-09-28 v4-t8 已处置**：同一元素改后 `count=1，bg=rgb(12,109,215)`（= `--brand-action`，与导航栏同色）；该页「计算底色 = `rgb(113,75,103)` 的**可见元素**」**1 → 0** | — | ✅ 缺陷已消灭，**carve-out 随之作废**（见文末「禁用色 ④」） |

### ⚠ 必填边框不能读 border-top-color（会读成假值）

/odoo/contacts/new 上的 .o_required_modifier 实测：**border-*-width = 0px、border-*-style = none**，
故其 border-top-color 计算值为 **rgb(26,34,51) = #1A2233 = currentColor（= --text-1）**，**不是** $o-input-border-required。

> 这与「border 列必须按 border-*-width>0 过滤」是**同一个坑**：无边框时 border-color 退回 currentColor。
> 按 border-top-color 直读会得出「已落在 #1A2233 上」这种**看似合格、实则与必填边框无关**的结论。
> **正解**：定位真正画那条边的元素（疑为内部 input.o_input，且可能只在 bottom 边），并先校验 width>0。（此项**待补**）

## ⚠ 焦点环归口校准 + /odoo 重定向口径（captain 2026-09-15，t5 完成时）

### 1. 归口依据 = **页面所属 bundle**，不是环的形态

原实现按「环形态像 backend_b11.css:58」把 5 组**全部归 t5** —— 那是**按形态猜**，忽略了可达性，
会把门户的环算成 t5 漏修。现按 bundle 归口，并要求报告**分清两列**：

| 页面 | 环 | 实算 | **归口依据（bundle）** | **实际可达性** |
|---|---|---|---|---|
| home | box-shadow rgba(12,109,215,.25) | 1.43 ×10 | **frontend（门户）** | t5 的 2 个文件**够不到** ⇒ 归 t4/t6/t7/t8 |
| apply | box-shadow rgba(12,109,215,.25) | 1.43 ×10 | **frontend（门户）** | 同上 |
| /odoo/contacts | outline rgb(0,95,204) | 1.46 ×4 | backend | t5 |
| /odoo/contacts | box-shadow rgba(194,198,202,.5) | 1.29 ×1 | backend | t5 |
| /odoo/contacts | outline rgb(0,95,204) on 原厂紫 | 1.21 ×1 | backend | t5 |

> assert 的输出已改为打印「归口依据 bundle=… ⇒ 归口 …」，并显式声明：
> **「仍出现」只表示该页当前仍可测到，不等于归口方未修**。

### 2. ✅ 独立确证：#005FCC 就是 Chrome UA 默认焦点环

t5 报「它修掉的是 Chrome UA 默认环 #005FCC，产物里 0 处定义」。我把 #005fcc 加进探针 B 的追踪值：
**实测产物内 #005fcc = 0 处** ⇒ 确证那是**浏览器默认环**，不是本仓产物定义的环（支持 t5 的说法）。

### 3. /odoo 会 **302 到 /apps**（门户页、前台 bundle）—— 抓 /odoo/contacts 时的口径

⇒ 抓取后必须**确认最终 URL 与所用 bundle**，不能只看请求的路径。

* 若该页出现 #212529 ×1，来源是**前台 bootstrap 的 .table-***（**该 bundle 内 202 处**），
  **不在 t5 两个文件的可达范围** ⇒ 不得计为 t5 漏修。
* 本量具的 capture 会把**抓取后的最终 URL** 记进每条 entry 的 url 字段（可据此核 bundle）。

### 4. t5 自报的净改善（供 t9 分列归口，本轮 before 快照早于 t5 落码）

| 指标 | 从 | 到 |
|---|---|---|
| 锚点失败 | 2 | **0** |
| 不达标文本对 | 15 | **13** |
| 不达标焦点环 | 6 | **3** |
| 门禁债务色 | 169 | **99** |

/odoo/contacts（1128 可见元素）实测：#71639E / #28A745 / #DEE2E6 / #212529 **各 0**；
~~**#714B67 = 1（carve-out → t8）**~~ → **2026-09-28 v4-t8 后该色 = 0**（carve-out 作废）。**剩余不达标项均在门户侧** ⇒ t9 报告按此分列。

## t5 专项探针（captain 裁定采纳）—— **探针 ≠ 基线**

probes.py 写**独立文件** probes-t5.json，**绝不改写冻结基线** baseline-local.json（冻在 15:50:33 那份）。
探针回答的是「机制有没有进产物 / 元素在不在、可不可读」，**不是 §7.3 的色数读数**，不参与 before/after 色数对照。

    python3 tests/color/probes.py --out tests/color/probes-t5.json        # A + B
    python3 tests/color/probes.py --only b --out tests/color/probes-t5.json

仅跑其中一个不会丢掉另一半结果（工具会与既有文件合并）。

### 探针 B（产物定向读）—— 不依赖页面渲染、可复跑、**记产物 hash**

后台页面引用 2 个 CSS 产物，合计 2,353,907 B：
  · web.assets_web_print.min.css — 1,179,601 B，sha256=b28ed8127e6eb0c6…
  · web.assets_web.min.css — 1,174,306 B，sha256=5f29076e54343121…
  · **combined sha256 = 8a91c7a1124d0c773ba62374…**（复现时请核对此 hash）

按**值** grep（**不要按名**：--o-navbar-background 实测不落成 CSS 变量名，按名 count 恒为 0）：

| 值 | 计数 | 说明 |
|---|---|---|
| **#71639e** | **2** | **原厂紫仍在编译产物里** —— 即使它不在本地导航栏渲染；t5 修好后应变化/归零 |
| #0c6dd7 | 422 | 我们的 --brand-action，已大量进产物 |
| #0e7bf2 | 156 | --brand-500 |
| #dee2e6 | 10 | $o-gray-300（map 快照那条线） |
| #212529 | 6 | Bootstrap 默认正文 |
| #714b67 | 6 | 原厂主色（含 t8 的 chip 注入等） |

> 这是 eng-backend 的 B 机制**唯一可证**的本地方式：不依赖页面是否渲染该元素。

### t9 判分须知 ①：/odoo/contacts 的 before/after 期望（eng-backend 提供）

| 期望变化 | 从 | 到 |
|---|---|---|
| 正文色 | #212529 | #1A2233（--text-1） |
| 边框/底 | #DEE2E6 | #E3E9F2（--border） |
| 浅底 | #F8F9FA | --bg #F4F7FA / --fill-hover #F0F4FA |
| 交互面底与边框 | #0E7BF2 | #0C6DD7（--brand-action） |
| 消息角标底 | #28A745 | #127A50（--success） |
| 选中/激活底 | #DDDBE8 | #E8EFF8（--fill-active） |
| 注入 chip 底 | ~~#714B67~~ → `--brand-action` | **2026-09-28 v4-t8 已处置**（原写「carve-out（t8），不计 t5」，carve-out 已撤销） |

### ⚠ t9 落锤项 ② 的两条：一条**按原写法是空判据**

captain 指定：「.text-success/.text-danger 的 computed color 必须落在令牌值上（不是 #008818 等 4 个硬编码）；
必填字段 .o_required_modifier 的 border-top-color 必须不再是原厂紫（$o-input-border-required 快照）」。

- 第一条**可行，但必须指定承载页面**：冻结页集 /odoo/contacts 上 .text-success=0、.text-danger=0；
  /odoo/contacts/new 有 .text-danger=1 但 .text-success=**0** ⇒ 需指定哪一页承载 .text-success。
- 第二条**按原写法是空判据**：实测 /odoo/contacts/new 的 .o_required_modifier
  **border-*-width=0px、border-*-style=none** ⇒ border-top-color 计算值 = currentColor = **#1A2233**，
  与 $o-input-border-required **无关**。也就是说它**现在就已经「不是原厂紫」**，修不修都一样通过。
  ⇒ 正解：先定位**真正画那条边**的元素（疑为内部 input.o_input，可能只在 bottom 边），**并先校验 width>0**，
     再读该边的 color。（此项**待补**：我的专门探针撞上 170s 执行器硬上限超时。）

## ⚠ 引用数字规范（本轮已因「手抄」出错 6 次）

**根因不是谁不认真，而是从会变的产物上手工誊写。** 实际代价：基线戳记错 4 次（87 / 86 / 80 / 15:44:59）、
selftest 条数错 2 次（32 / 38，真值 44）。

⇒ **引用任何数字前，跑这条命令读文件，不要凭记忆写**：

    python3 tests/color/color_audit.py status --out tests/color/status.json

输出（实测样例）：

    selftest: 44/44 通过（断言条数常量 44）
    基线: CANONICAL | rev 3c449ce27e86 + 2 dirty | 2026-09-15T15:50:33+08:00 | 79 色
    探针: combined sha256=8a91c7a1124d0c77 | #71639e=2

另：引用基线时**必须连文件名或 status 一起写**（CANONICAL / SUPERSEDED），不单写数字。
**「为了对齐 before 而重取」不是理由** —— ④ 是绝对判据，不需要 before 有同名字段。

## 判据 ④：状态色 == 令牌值（机械判定）

### ⚠ --info 是**面令牌，不得作文字色**（captain 2026-09-15 提醒，数值已核）

--info 的值为 **#0E7BF2**（alias of --brand-500）。其 **白底对比度实算 4.09 ✗**（本工具核对：4.0904），
**低于正文 4.5 档** ⇒ 只能按「面」（背景/填充）使用，**不得当文字色**。
t9 若要用 --info 做任何判据，请按面用；按文字色用会直接产生一条不达标。

注：--warning 同理（白底 2.44 ✗）—— 本仓已为此拆出 --warning-ink 作文字档；--info 目前**没有** ink 档。

```
python3 tests/color/color_audit.py tokens RAW.json --set frozen6
```

该命令把页面实测的令牌计算值与 **scripts/color_tokens.json（§7.4 指定的唯一令牌输入）** 逐项比对：

- **判据面 = 状态色 --success/--danger/--warning/--info**，任一漂移即 VERDICT: FAIL；
- 其余字段漂移作 **INFO 不判定** —— 典型例子是后台页 documentElement 的 --body-color 取到 Bootstrap 默认值
  （已登记的「框架值」现象，判据看 body.color）；
- 归一后比较（#127A50 与 rgb(18, 122, 80) 视为相等），故跨写法不误报。

> ⚠ 这是**绝对判据**：只依赖 after 快照 + 令牌源，**不需要 before 里有同名字段**。
> 因此 canonical 基线虽在补 --info 之前抓取（那一版无 --info），判据 ④ 仍可在 t9 的 after 上完整执行。

## t9 判分须知：计数口径 与 /odoo/contacts 的 carve-out

### 棘轮单调性：两个判据**量纲不同**，不可互相印证

captain 2026-09-15 明确：门禁棘轮要**指明单位**，本仓至少有两种不同量纲：

| 单位 | 含义 | 出处 | 本工具怎么给 |
|---|---|---|---|
| **去重色数** | 四属性 union 后**不同颜色**的个数 | §7.3 的 53 / 69 / 79 就是它；门禁债务用它 | aggregate 的 distinct（**唯一可跨 before/after 比较的指标**） |
| **出现处数** | 某颜色**被用了多少次** | eng-portal §11 第 1 行是用它记账 | aggregate / 原始 JSON 里每色后面的 ×n |

**captain 2026-09-15 裁定（终版）**：**t9 的判据一律用「种类数」（distinct）** —— 这正是主判据「令牌外色 = 0」的形式；
**任何「N 处 / ×N」不得跨口径比较**（实例：同一色在本工具是 278 处、在审计是 23 处，两种计数约定，不是矛盾）。
「N 处」的领域是**源码侧债务计数**（eng-portal 的出现处数），**不是渲染色量具的领域** —— 两个量具、两种单位，
规范 §11 与判据 A 本来就是分开写的。**不要在冻结量具上加「每元素一次」模式。**

⇒ **两者不是同一个量**，不能用一个的下降去印证另一个的下降；
汇报时必须写明是「去重色数降了 X」还是「某色出现处数降了 Y」，否则会得出错误结论。

⚠ 而且**「出现处数」本身也还带一层口径**：本工具的 border 列按**渲染的边**计数（一元素最多 +4），
与审计的「每元素一次」不同 ⇒ 引用出现处数时**必须连计数口径一起声明**。

### ⚠ 计数（每色后面的 ×n）不可与审计的「N 处」直接比

本工具的 `border` 列按**实际渲染的边**计数（一条元素四边都有宽度时最多 +4），
而审计的原始数据看起来是**每元素一次**。例：`#DEE2E6` 在 /odoo/contacts ——
审计 **23 处**，本工具本地 before 读数 **bg 4 + border 271 = 275**。这是**口径差异，不是回归**。

**§7.3 的指标只用「种类数」，不用计数**，所以 79 色这一读数不受影响；
但任何引用「N 处」的说法必须先声明口径。若需要与审计可比的计数，须另加「每元素一次」模式
（不要在冻结中的量具上单方面改 —— 会再逼一次基线重取）。

### /odoo/contacts 的合法残留（eng-backend 提供，captain 已裁定归 t8 / 已豁免）

eng-backend（t5）已逐色归因并经本工具独立核对无误。~~**t9 判该页「令牌外色 = 0」时必须扣除**~~ →
**2026-09-28 v4-t8 起：不得再扣除任何 `#714B67`（该色已消灭，carve-out 作废；判据恢复为「令牌外色 = 0」原样）**。下表仅存档当年的归因：

| 色 | 生产原始计数 | 归属（已核实） |
|---|---|---|
| ~~bg #714B67~~ | ×1 | ~~**carve-out → t8**：apps_panel_chip.js:18 往 .o_main_navbar 注入内联 background:#714B67（第 18 行原文已核）~~ ⇒ **2026-09-28 v4-t8 已处置，carve-out 撤销** |
| bg #71639E | ×1 | **B/C 双链**：SCSS 可达部分（\$o-navbar-background 快照）归 t5；webclient_templates.xml 硬编码那半归 t8 |
| bg rgba(0,0,0,0.7) | ×1 | **已豁免**（captain 放宽后的豁免集：归一后纯黑/纯白的一切 α 变体） |
| 其余（#212529 / #DEE2E6 / #0E7BF2 / #F8F9FA / #28A745 / #DDDBE8 等） | 其余全部 | **t5 的，目标清零** |

> ⚠ **一条会让 t9 误判的实情（务必写进 t9 报告）**：**#71639E 在本地实例上根本没有出现**（生产原始数据里有 1 处）。
> ⇒ **本地 after 不会看到它下降**，因为它在本地压根没渲染出来。
> **t9 不得把「本地没降」记成 t5 失败** —— 这是环境差异，不是未完成。
>
> 它的 **B/C 双链归属已由 captain 裁定**：**B 链（SCSS 可达，$o-navbar-background 快照）归 t5；C 链（webclient_templates.xml 硬编码那半）归 t8**。

### 一条给 t5/t9 的结构性提示（已独立核实）

`#DEE2E6`（= \$o-gray-300，见 Odoo 核心 primary_variables.scss:53）在该页是第一大令牌外色，
但它**主要来自 map 快照而非变量**：核心 primary_variables.scss:246-247 有
`"secondary": ( background: $o-gray-300, … )`，随后 map-merge 进 \$o-btns-bs-override。
⇒ **只压 \$o-gray-* 变量，这些出现不会动**，必须重做合并后的 map 快照。

> 路径提醒：带有该 map 的 primary_variables.scss 是 **Odoo 核心**文件（容器内
> /usr/lib/python3/dist-packages/odoo/addons/web/static/src/scss/primary_variables.scss，297 行）；
> 仓内 openeducat_erp/theme_web_openeducat/static/src/scss/primary_variables.scss **只有 86 行、没有该行**，
> 在仓里 grep 会找不到。

## 已知问题（供 t9 / captain）

1. **§7.3 的「按此口径实算 = 53」只对最初四页成立**。§7.2 补齐六页后同一支量具实算 **69**
   （已冻结为 selftest 断言）。--expect 53 必须配 --set legacy4；六页请用 --set frozen6。
   §7.3 另两个辅助数（不剔黑白 70 ｜ 只算 text 30）来自**原脚本归一化之前**的算法
   （把 rgba(0,0,0,0) 当独立 token、非 0/1 的 alpha 不合并），与本工具同口径辅助数（55 ｜ 24）
   **不是同一个量**，引用时勿混用。
2. **令牌集未落地前不得判「令牌外色」**：§7.4 已定 scripts/color_tokens.json（t3 机械提取）为唯一输入。
   本工具只做「色数 / 令牌值 / 对比度」读数，不自行维护令牌表。
3. **对比度阈值的口径**：本工具扫的是「自己直接含文本的元素 × 有效背景」，因此比审计 §3 手工列举的 6 条
   更宽（同一快照得 15 组）。两者不是同一集合，**不等于审计漏了 9 条**；
   引用时必须说明是「本工具口径下的不达标对数」。
4. **生产归档有 2/6 页是「带上限」抓的（新发现）**：/my/calendar?view=week 与 /apps 带 `caps` 字段
   = text30/bg30/border20/anchor14，即当年那两页按**每属性种类上限**截断。
   实测那两页的四属性计数（12/19/9/9 与 4/4/3/3）都在上限内，**未发生截断**，故当前可比；
   但本工具**不设上限**，一旦本地某属性超过上表，该轴就不再可比。
   `aggregate` 已就此**告警**（超出即打印「实得 N > 生产上限 M」），当前两侧均无告警。
   另：生产那 4 页无 `caps` 字段，与这 2 页不同源 —— 这是生产基线自身的一致性缺口，供 t9 引用时留意。

## 环境注意（踩过的坑，复跑时省时间）

- **必须用 127.0.0.1，不要用 localhost**：浏览器侧 Node realm 把 localhost 解析成 ::1，
  而 compose 只映 IPv4 ⇒ ECONNREFUSED ::1:8069。cookie 也要按 127.0.0.1 域清。
- **browser.newContext() 被 TabbitDance 拒绝**（Target.createBrowserContext）；
  公开页改用共享 context + **按域**清 cookie（只清 127.0.0.1，绝不动用户 edu.example.org 登录态），
  并要求 /my/home 返回 3xx 才算「游客态」成立。
- **每次取色新开 page 并在 finally 关闭**：某页 goto 超时会把复用中的 page 卡死，
  之后请求会**瞬时失败**（不是超时），难以归因。
- **--timeout-ms 只接受 60000–180000**；取色程序最坏 ≈120s（goto 上限）故用 180000。
- **request-id 必须每次全新**（见上），否则静默回放旧读数 —— 这是本工具最危险的一个坑。
- **Docker Desktop 看不到 ~/.cache**：worktree 放在那里会挂成空目录（Odoo 静默降级：视图来自库仍在、
  控制器 404）。放仓库同级目录（本仓库在 ~/Documents/…）并在取数前**断言** /mnt/custom-addons/edu_portal 存在。
- **本机期间发生过宿主机重启 + Docker 守护进程掉线**，/tmp 会被清空 ⇒ 编排脚本别放 /tmp。
- 高负载下带会话首屏可达 ~100s（werkzeug 日志 101.022）；机器 load average 一度到 44。
- **本量具的取色走真实浏览器（Tabbit）+ 已登录会话，不依赖 curl 的 bundle 完整性** ——
  这是刻意的：无论「裸 curl 是否拿得到完整 bundle」，量具都不受影响。
  证据：六页 `--brand-action/--brand-500/--success/--bg` 全部有值（这些来自 edu_brand/edu_portal 自定义资产，
  bundle 若被剥掉必然是空）⇒ 量具确实拿到了完整资产。
- **「裸 curl 是否拿到残缺 bundle」——双方读数并存记录（2026-09-15，captain 裁定：并存、不追查）**：

  | 来源 | 方法 | 裸取（无 cookie） | 带 session | 结论 |
  |---|---|---|---|---|
  | captain / eng-web | 数 CSS **源数**（疑为 @import/asset 源） | `/apply` **328 源**，缺 15 个自定义模块资产 | **343 源 / 1,444,206 B** | 裸取残缺 |
  | 本量具（verifier 实测） | 数**注释块**并逐字节比对 | 1 个 CSS 文件 / **1,444,255 B** / 344 注释块 | 1 个 CSS 文件 / **1,444,255 B** / 344 注释块 | 三页（/ 、/apply 、/my/home）**完全相同**，两串内容 `b == a` → True |

  我方附加证据：`brand-action / --teal-500 / oe_count / brand_tokens / edu_portal / edu_brand / --brand-500`
  等**自定义标记在裸取与带 session 两侧全部命中** —— 若真缺 15 个自定义资产，这些不可能出现。

  ⇒ 双方均为硬读数，差异**可能来自测量时点（正逢资产重生成）或计数方式（源数 vs 注释块）**，不再追查。
  **处理（低成本保险，保留）：凡走 curl/requests 核对 CSS 的步骤一律带 cookie jar**（code-map §2 本就要求）。
  **本量具走真机浏览器 + 已登录会话，天然免疫该分歧** —— 六页自定义令牌（--brand-action/--brand-500/--success/--bg）全部有值即是证明。
- **资产 attachment 按内容 hash 缓存**（eng-web 实测）：改完 SCSS 若怀疑读到旧产物，
  需清 `ir_attachment where url like '%web.assets_%min.css'` 再重启，否则可能拿到旧内容。
  本量具**不消费 ir_attachment 缓存**（每次真机重新取渲染结果），但**t9 若用 curl 核对 CSS 就会受影响**，故记录在此。
- **探活别用 `timeout` 命令**：macOS 没有 coreutils 的 `timeout` ⇒ `timeout: command not found` (rc=127)，
  而 curl 的 000 与「连接被拒」长得一样，容易把「探测自身坏了」误判成「站点不通」。
  用 curl 自带的 `--max-time` 即可。（2026-09-15 全队曾因此一度误判 docker/8069 整体不可用。）

---

## ④ 禁用色：Odoo 原厂紫（v4-t8 新增；**同时撤销 §6.2.3 的 carve-out**）

### 为什么要有这一条

`docs/plans/color-system-v4.md` §6.2.3 曾把 `/odoo/contacts` 上唯一那一处 bg `#714B67`
以 **carve-out → t8** 从判据里扣掉（原文「判据写『令牌外色 = 0（扣除 carve-out）』」）。
**carve-out 不随缺陷一起消失，就会变成永久盲区** —— 后人照着扣，同一处紫色再长回来也没有门禁点名。
所以 t8 消灭紫色之后，这里把它改成**机械判据**（`color_audit.py` 的 `FORBIDDEN_COLORS` + `forbidden_hits()`）：

- 覆盖面 = **四属性 × 全部页**（text / bg / border / anchor），**按归一后比对** ⇒ `rgba(113,75,103,.35)` 这类半透明写法与实色一起抓；
- **没有例外项**：要豁免就得改那张常量表，改动会被 review 看见；
- 列入两个值：`rgb(113, 75, 103)` = `#714B67`（企业版原厂主色）、`rgb(113, 99, 158)` = `#71639E`（社区版原厂紫）。

### 三组证据（2026-09-28 实测；同一支量具、同一台机器）

| # | 实验 | 样本 | 判据 ④ 读数 | 结论 |
|---|---|---|---|---|
| 1 | **反向**：把紫临时塞回 `apps_panel_chip.js`（`a.setAttribute('style', 'background:#714B67')`）+ 重启 web | `/tmp/color-raw-purple.json`（driver=playwright） | `FAIL contacts bg rgb(113, 75, 103) x1  #714B67 · Odoo 企业版原厂主色`；`禁用色命中 = 1`；**VERDICT: FAIL（exit 1）** | **门禁红**（随后撤销；撤销后文件与注入前 sha256 逐字节相同） |
| 2 | **正向 / 控制组**：撤销注入后的同一状态（重启 web 后重抓，`/tmp/color-raw-control.json`；同一份读数也见于改后第一次抓的 `/tmp/color-raw-after.json`） | `color-raw-control.json`（driver=playwright） | `PASS 2 个禁用色在 6 页 × 四属性里 0 命中`；`禁用色命中 = 0` | **门禁绿** |
| 3 | **历史样本（真实归档，非构造）** | `tests/color/baseline-local.json`（t3 期快照，当时紫还在） | `FAIL contacts bg rgb(113, 75, 103) x1  #714B67 · Odoo 企业版原厂主色`；`禁用色命中 = 1`；**exit 1** | 门禁**当场抓到**当年那一处 |

> 第 3 行的价值：它证明这条判据在**真实的旧读数**上会红（不是"构造一个必红的假样本"），
> 同时**独立复核了 t5 的元素级归属** —— 归档数据里 `/odoo/contacts` 恰好 1 处 bg 紫，
> 与真机把每个元素 `getComputedStyle` 过滤出来的那 1 个元素（`#yy-apps-chip`）完全对上。
>
> ⚠ 但**不要**把第 3 行说成「门禁从绿变红」：那份快照本来就因其它项 FAIL（对比度 16 组等），
> 它只是「④ 这一项」从无到有地抓到了紫。**单变量对照是第 1 行与第 2 行**。

### 运行方式（本环境的 ENV 与替代驱动）

~~~bash
# 官方驱动（tabbit-cli）：2026-09-28 本机实测 ENV —— BROWSER_RUNTIME_UNAVAILABLE
python3 tests/color/color_audit.py capture --base-url http://127.0.0.1:8069 --out /tmp/raw.json   # -> exit 2（ENV）

# 替代驱动（Playwright；测量代码逐字取自 capture_page.js）
python3 tests/color/capture_playwright.py --base-url http://127.0.0.1:8069 --out /tmp/raw.json --set frozen6
python3 tests/color/color_audit.py assert /tmp/raw.json --set frozen6       # 看 §④ 段与「禁用色命中」计数
~~~

⚠ **驱动不同 ≠ 口径不同**：测量代码是**同一份**（运行时从 `capture_page.js` 切片，7504 字节），
但「两个驱动逐色读数相等」本轮**没有对照**（tabbit 不可用）⇒ 该产物只用于**绝对判据**，
**不得**与 tabbit 抓的 `baseline-local.json` 做色数相减。

### ⚠ 运维坑（本轮实际踩到）：改了 `static/src/js|css` 后**产物可能是旧的**

`apps_panel_chip.js` 改完第一版（结构）时是**立刻生效**的；改第二版（临时注入紫色）后**没有生效**：
真机 DOM 仍是 `inline: null`、`bg: rgb(12,109,215)`，而 `<script src>` 仍是同一个产物 hash。
本节上方「疑难杂症」里 eng-web 那条记录（**资产 attachment 按内容 hash 缓存**）是同一现象的既有记载，处置：

~~~bash
# 怀疑读到旧产物时（清产物缓存 + 重启；本仓既有口径）
docker compose exec -T db psql -U odoo -d edu19 -c "delete from ir_attachment where url like '%web.assets_%'"
docker compose restart web
~~~

> 推论（写给下一个人）：**拿到「改完没变」的读数，先确认产物 hash 变了再下结论** ——
> 否则会把「缓存」误判成「改法无效」，甚至误判成「门禁不灵」。

