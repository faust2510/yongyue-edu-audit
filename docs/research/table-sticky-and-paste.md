# 网页表格的冻结表头/首列 与 Excel 整块粘贴 —— 先例与实现路径调研

> **服务的设计文档**：[`docs/plans/eval-unified-design.md`](../plans/eval-unified-design.md) §6.6（E6 冻结）/ §6.7（E7 整块粘贴）/ §9.7（自陈缺口）
> **状态**：✅ **本轮调研完成**（10 节全部落盘；未验证项单列于 §9）
> **调研人**：技术调研员（subagent）｜**日期**：2026-09-28（本机 `date` 实测；文中所有"当前快照"均指该日）
> **铁律 0 定位**：本文件补 `docs/research/evaluation-rebuild.md` **未覆盖**的两项交互机制；不重复该文件已有内容。

## 0. 本次调研的边界与前置

| 项 | 内容 |
|---|---|
| 要回答的机制 | M1 = 表格冻结表头/冻结首列（sticky）；M2 = Excel 整块粘贴进网页表格 |
| 不重复的部分 | `evaluation-rebuild.md` 已覆盖：Odoo `spreadsheet` 社区版只读、企业版 `action_edit_dashboard` OEEL-1、OCA `spreadsheet_oca` 的 AGPL 红线、Handsontable 7.0.0 起非开源、Univer 的 xlsx 在付费 pro 包 |
| 本次新增 | **Odoo 19 列表视图的冻结能力源码取证**、**Odoo 19 spreadsheet 的剪贴板/冻结分割源码取证**、**sticky 在 overflow 祖先下的失效判据（CSS 规范级）**、**Moodle/Canvas 成绩册的冻结与粘贴实现**、**OCA 可用模块与 license**、**国内同类功能名级证据** |

### 取证环境（可复现）

```bash
# Odoo 19 社区版：docker 容器内
docker exec edu19-clone-web-1 sh -c 'ls /usr/lib/python3/dist-packages/odoo/addons | wc -l'
# Odoo 19 企业版全量源码（本地只读参考，按 ~/odoo-enterprise-ref/README.md 约定永不进仓库）
ls ~/Documents/文件大总管/30-资源/odoo源代码企业版/odoo/addons/ | wc -l   # 1467
```

> ⚠ **引用约定**：企业版源码路径在仓库外（`~/Documents/文件大总管/30-资源/odoo源代码企业版/`），**没有公开 URL**。
> 本文凡引用企业版源码，一律写 `ENT:<模块相对路径>:<行号>`，并单独在 §8 标注「本地企业版源码，非公开来源，**不可对外引用**」。

## 1. 结论速览

### 1.1 四项「必须回答」的答案

| 问题 | 答案 |
|---|---|
| **Odoo 19 有现成能力吗（表头冻结）** | ✅ **社区版核心就有**：`addons/web/static/src/views/list/list_renderer.scss:14-24` `o-position-sticky(0)` + `--sticky-header-zindex` 变量法。但**只冻表头，不冻首列**（同一 mixin 只传了 `$top`） |
| **Odoo 19 有现成能力吗（整块粘贴）** | ❌ **列表/x2many 一律没有**（`views/` 目录只命中 `input_field_hook.js:54` 的换行拦截）；✅ **只有 o-spreadsheet 有**完整实现（`o_spreadsheet.js:6292-6352` + `8042`） |
| **Odoo 19 spreadsheet 是「像 Excel 一样好用」的现成答案吗** | **作为"一个像 Excel 的表"= 是**（冻结/粘贴/公式/小计/条件格式/数据验证/xlsx 读写全在 LGPL-3 的库里）；**作为"我们评估表的答案"= 不是**（它是**文档型 JSON**、社区版**没有可保存的编辑回路**、**没有回写业务记录**、且会**把算分搬到前端**，与设计文档「单一算法源」冲突）。详见 §4.4 |
| **sticky 在外层有 overflow 祖先时会失效吗** | **不是"失效"，是"参考系被换掉"**。判据见 §7.3：**C1**（`overflow:hidden` 祖先内部确有溢出内容 + 用户实际滚的是更外层）= **一定失效**；**C6**（`overflow: clip`）**不**劫持；**C7**（矩阵自己当滚动容器）**一定生效**；**C8**（只写 `overflow-y: auto`）**横轴照样有滚动容器**（`visible` 表现为 `auto`）。**设计文档 §6.6 ① 的结论正确，措辞需修正** |
| **可装模块** | OCA 全表见 §5：**LGPL-3** = `web_responsive`、`web_remember_tree_column_width`…；**AGPL-3（传染性 → 需法务确认）** = ⭐`web_widget_x2many_2d_matrix`（四向冻结的完整先例）、`spreadsheet_oca`（CE 可编辑 Spreadsheet）。**OCA 无任何「列表冻结首列」或「整块粘贴」模块** |
| **同类系统** | DataTables：**冻结列与粘性表头是两个扩展**（官方原句），v5 用 `position: sticky` + 手算偏移（**MIT**）；SlickGrid（Canvas 用）：**分栏同步滚动**，不用 sticky；**Moodle**：`flexible_table::column_sticky()` **核心一等公民** + grader 四向冻结，**无粘贴**；**Canvas**：冻结有、**整块粘贴 0 命中**（走 CSV 上传）；**国内**：钉钉 AI 表格「冻结到此列」+ 拖冻结线、宜搭「最多冻结 5 列」+ Excel **文件**往返，**无一家做剪贴板整块粘贴** |

### 1.2 一句话给设计的结论

> **E6（冻结）**：**能做，且先例最多**（Odoo 核心、OCA 矩阵、DataTables、Moodle grader 四份）。**关键不是"能不能"，而是"矩阵必须是它自己的滚动容器"**（§7.3 C7），否则参考系会被门户祖先劫持。**首列冻结是自研项，但形态可照抄 OCA 的 20 行 SCSS**（只抄方法不抄代码，AGPL-3）。
>
> **E7（整块粘贴）**：**同类系统里几乎没有先例**（Canvas/Moodle/宜搭/钉钉全是"文件导入"）。**唯一可抄的实现是 o-spreadsheet 的 5 步管线**（§3.2），**内核只有 3 行**：`\r` 归一 → 按 `\n` 分行 → 按 `\t` 分列 → 补成矩形 → **按 locale 归一数值**。**必须自研的部分是"粘进去之后怎么校验"**（§8）。
>
> **spreadsheet 方向**：**不要因为 E6/E7 而换渲染范式**（§4.4(b)）。它的价值在于**给出可抄的实现**与**未来"Excel 式自由编辑"单独立项时的库选型**。

### 1.3 本报告相对`evaluation-rebuild.md`的**增量**（不重复其内容）

1. **Odoo 19 列表视图粘性表头的源码位置与四条工程细节**（变量法/height:100%/打印分支/background-clip）——既有文档**完全没有**。
2. **o-spreadsheet 的粘贴管线逐行取证**（含"Excel 的 HTML 被显式丢弃走 TSV"这一句关键判断）。
3. **LGPL-3 ↔ OEEL-1 的精确切分**（`spreadsheet_dashboard` 是 LGPL-3 且在社区镜像里；`/spreadsheet/xlsx` 路由在 OEEL-1）——既有文档只笼统说"只读"。
4. **行号漂移 −64 行**的实证（78149/78288 → 78085/78224）。
5. **Moodle 的四条可抄经验**（`top: 导航条高度`、hover 态背景、colspan 需 JS 补偏移、sticky 会裁切下拉框）。
6. **Canvas 的整块粘贴 0 命中**（可复现命令行给出）。
7. **sticky 的规范级失效判据 8 条**（既有文档只有一句"未验证"）。
8. **OCA 全模块 license 逐个取证**（既有文档只标了 3 个模块）。

## 2. M1 冻结表头/首列 —— Odoo 19 现成能力

### 2.1 结论：**表头冻结有现成（社区版核心），首列冻结没有**

| 能力 | Odoo 19 有没有 | 源码位置 |
|---|---|---|
| 列表视图**粘性表头** | ✅ **有** | `addons/web/static/src/views/list/list_renderer.scss:6-24` |
| 列表视图**冻结首列** | ❌ **没有** | 全仓 `grep -rn -i "frozen\|freeze"` 在 `addons/**/*.{js,scss,css,xml}` 里**没有一个**是「冻结列」语义（见 §10 命令） |
| 表格内部 CSS mixin | ✅ 有 | `addons/web/static/src/scss/utils.scss:31-37` `@mixin o-position-sticky($top,$right,$bottom,$left)` |

**取证原文（Odoo 19.0 FINAL，本地全量源码 `odoo/addons/web/static/src/views/list/list_renderer.scss:6-24`）**：

```scss
.o_list_renderer {
    --sticky-header-zindex: 1;
    --o-view-nocontent-zindex: calc(var(--sticky-header-zindex) + 1);
    // sticky header on desktop
    @include media-only(screen) {
        @include media-breakpoint-up(md) {
            height: 100%;
            .o_list_table thead {
                @include o-position-sticky(0);
                z-index: var(--sticky-header-zindex);
            }
        }
    }
```

**四个可直接抄走的工程细节**（这四条比「有没有」更有价值）：

1. **只给 `top`，不给 `left`** ⇒ Odoo 自己**不做**冻结首列。注意 `o-position-sticky(0)` 只填第一个参数（`$top`），后三个是 `auto` —— 混用 `o-position-sticky(0, auto, auto, 0)` 是本仓新增能力，**不是** Odoo 现成的。
2. **`z-index` 用 CSS 变量集中管理**（`--sticky-header-zindex: 1`），并派生 `--o-view-nocontent-zindex = 表头 + 1`」—— 说明**「表头 vs 遮罩」的层级冲突是已知问题**，Odoo 的解法是**用一个变量当单一真相源**。我们做「首列冻结」时会多一层（首列 z-index=1 / 表头 z-index=2 / 交叉格 z-index=3），**这个变量派生法必须抄**，否则交叉格会被表头盖住。
3. **`height: 100%` 是粘性能生效的前提之一**：`.o_list_renderer` 显式撑满父容器，粘性元素才有「可粘的行程」。
4. **`@include media-only(print)` 分支显式处理打印**（`list_renderer.scss:26-29`：`width: 100% !important`，且 `list_view` 下把 `--ListRenderer-table-padding-x` 归零、`border-collapse: separate`）⇒ **Odoo 自己在打印态切换了 `border-collapse`**，等于承认「collapse + sticky 的边框问题是真实存在的」，见 §2.3。

### 2.2 为什么 Odoo 的表头粘性「能生效」——它自己的滚动容器布局（**这条直接回答设计文档的 V1 风险**）

`addons/web/static/src/webclient/webclient_layout.scss`（Odoo 19.0 FINAL）原文：

```scss
.o_web_client { height: 100%; display: flex; flex-flow: column nowrap; overflow: hidden; ... }
  > .o_action_manager { flex: 1 1 auto; height: 100%; overflow: hidden; }
    > .o_action { height: 100%; display: flex; flex-flow: column nowrap; overflow: hidden; ...
        .o_content { overflow: auto; height: 100%; }        // ← 唯一的滚动容器
        > .o_control_panel { flex: 0 0 auto; }
```

**这是 Odoo 对「外层有 overflow 祖先」这个问题的官方答案**：

- 外面**全是 `overflow: hidden`**（`.o_web_client` / `.o_action_manager` / `.o_action`），页面**根本不滚动**；
- 真正的滚动容器**只有一个、且是显式的**：`.o_content { overflow: auto; height: 100% }`；
- 粘性表头相对 `.o_content` 这个 scrollport 生效 —— 也正因为外面那些 `overflow: hidden` 的盒子**都不滚动**，它们**不会**抢走 sticky 的参考系。

> **判据（先给结论，推导见 §7）**：sticky **不是**「遇到 overflow 祖先就失效」，而是「**相对最近的滚动盒子偏移**」。
> 危险的不是 `overflow: hidden` 本身，而是「**你以为的滚动发生在页面上，但 sticky 的参考系却是某个不滚动的 overflow 盒子**」。
> Odoo 的做法（`html/o_web_client/o_action` 全 `overflow:hidden` + 只有一个 `.o_content{overflow:auto}`）就是**把参考系显式化**。

### 2.3 关于 `border-collapse: collapse` 下 sticky 边框「掉线」——Odoo 的旁证

- Odoo 列表用的是 **`collapse`**：`list_renderer.scss` 里 `.o_list_table { border-collapse: collapse; ... }`，并配了一句注释「We need this to be collapse because we want to add a border on the rows for sale order/invoice lines of type section.」⇒ **Odoo 选了 collapse 并保留了它**，代价是**在打印态切成 `separate`**。
- Odoo 用 **`background-clip: padding-box`** 修 Firefox 下的单元格边框显示问题（同文件：`// This fixes a bug that was hidding part of cell borders on Firefox.`）。**这条修法可以直接抄**，比设计文档 §6.6 ② 提的 `box-shadow: inset 0 -1px 0` 更省事、且是 Odoo 自己的选择（两者可叠加）。
- ⚠ **未验证**：Odoo 用 collapse 时**粘性表头滚动中边框是否真的不断线**，我没有在本机浏览器实测（见 §9 未验证清单）。设计文档的 `box-shadow` 方案仍是稳妥兜底。

### 2.4 与本仓现状的差距（用 Odoo 的尺子量我们）

| 我们要的 | Odoo 19 给到哪一步 | 我们还需要做什么 |
|---|---|---|
| 表头冻结 | **给了 `position: sticky; top: 0`** 的现成写法与变量法 | 抄 `list_renderer.scss:14-24` 的**结构**（含 `--sticky-header-zindex` 变量派生），但**不能直接复用 class**（我们的矩阵是门户模板 `assess_portal.xml` 里的自绘 table，不是 `o_list_renderer`） |
| 首列冻结 | **没有** | 自研（Odoo 无先例，OCA 见 §5，同类系统见 §6） |
| 滚动容器 | **给了范本**：`.o_content{overflow:auto}` + 外层全 hidden | 门户页是 `website` 布局，**必须先确认门户的滚动容器是谁**（见 §7 判据 + §9 未验证） |

## 3. M2 Excel 整块粘贴 —— Odoo 19 现成能力

### 3.1 结论：**列表视图 / x2many 一律没有；只有 o-spreadsheet 有完整实现**

| 位置 | 有没有「整块粘贴」 | 证据 |
|---|---|---|
| 列表视图 / 内嵌 x2many / 可编辑列表 | ❌ **没有** | `addons/web/static/src/views/` 全目录 grep `onpaste/handlePaste/addEventListener("paste")` **只命中 1 处**：`views/fields/input_field_hook.js:54` 的 `insertFromPaste`（只用来拦「换行」），**不是**二维块粘贴 |
| `product_matrix`（Odoo 官方矩阵小组件，**LGPL-3**） | ❌ **没有** | `grep -rn -i "paste\|clipboard" addons/product_matrix/static/src/` → **0 命中** |
| **o-spreadsheet**（`spreadsheet` 模块内嵌的 LGPL-3 库） | ✅ **有，且是教科书级实现** | 见 §3.2 |
| Web 客户端剪贴板工具 | ✅ 有（写剪贴板，非粘贴） | `addons/web/static/src/polyfills/clipboard.js` |

### 3.2 o-spreadsheet 的粘贴管线（**M2 最该抄的东西**）

全部位于 `addons/spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js`（Odoo 19.0 FINAL；行号见 §10 的漂移警告）：

| # | 环节 | 行号 | 原文/行为 | 对我们的意义 |
|---|---|---|---|---|
| ① | 读系统剪贴板 | `6292` | `function parseOSClipboardContent(content)`：同时读 `content["text/html"]` 与 `content["text/plain"]`，另支持图片 MIME | **同时带 html + plain 读**，不只用一种 |
| ② | **Excel HTML 判别** | `6305` | `function getOSheetDataFromHTML(htmlDocument)`：`if ([...htmlDocument.documentElement.attributes].some((attr) => attr.value.includes("microsoft"))) return;` | **来自 Excel 的 HTML 被显式丢弃**，改走 `text/plain` 的 **TSV** 通道 —— 这条判断是本仓要抄的第一句 |
| ③ | **二维切分** | `8042` | `convertTextToClipboardData(text)`：`text.replace(/\r/g, "").split("\n")`，每行 `.split("\t")`，**取各行最大列数 `rowLength` 对齐成矩形** | 这就是「整块粘贴」的最小内核：**\r 先归一、按 \n 分行、按 \t 分列、补成矩形** |
| ④ | **按 locale 归一数值** | `8052` | `canonicalizeNumberValue(row[i] \|\| "", locale)` | **不直接 `Number()`** —— 本地化数字（千分位/小数点）要走 locale 归一。**本仓要抄**（Odoo 19 多语言后台，中文环境照样有全角输入问题） |
| ⑤ | 粘贴目标与铺满语义 | `6288` | `function getPasteZones(target, content)` → `splitZoneForPaste(t, width, height)` | **复制 1×1 粘到 3×5 区域时会被「平铺」填满** —— 这是 Excel 的语义，**我们必须显式决定要不要**（见 §3.3） |
| ⑥ | 多处理器管线 | `6317` / `6341` | `applyClipboardHandlersPaste(handlers, copiedData, target, options)`、`getPasteTargetFromHandlers(...)` | 每种数据类型一个 handler（cell/border/merge/conditional_format/data_validation/chart/image/carousel/table/sheet/references，见 `6370-8618`）。**我们只需要 cell 一个**，但不能不知道这个形状 |
| ⑦ | **粘贴后选中被粘区域** | `6352` | `selectPastedZone(selection, sourceZones, pastedZones)` | 粘完把选中区扩到粘贴范围（Excel 同款），**这是「像 Excel」的体感细节** |
| ⑧ | **跨冻结线粘贴被拒** | `8527-8531`（`SheetClipboardHandler.isPasteAllowed`） | `const { xSplit, ySplit } = this.getters.getPaneDivisions(sheetId); if (doesAnyZoneCrossFrozenPane(getPasteZones(target, content.cells), xSplit, ySplit)) return "FrozenPaneOverlap";`，错误文案见 `38419`：「This operation is not allowed due to an overlapping frozen pane.」 | **M1 与 M2 的耦合点**：Excel 类产品**显式禁止**粘贴块跨越冻结边界。**本仓必须表态**（见 §3.3） |

### 3.3 我们从这份实现里必须**显式决策**的三件事（照抄会踩坑）

1. **平铺 vs 截断**：o-spreadsheet 会把 1×1 平铺填满选区（`getPasteZones`/`splitZoneForPaste`）。我们的矩阵是「行=学生、列=评分项」，平铺在「一列同分」场景下**正是用户想要的**（设计文档 §6.7 原话：「一列几十行是同一种给分」）。**建议保留平铺**，但只在「源 1 列 × 目标多行」时允许，**源多列时溢出即拒**（Excel 也是这个边界语义 —— 见 §6）。
2. **跨冻结线**：o-spreadsheet 选择**拒绝**。我们的矩阵首列是学号/姓名（只读文本），粘贴目标是评分数值格，**源列与目标列天然不重叠**时不存在跨界问题；但**若用户从 Excel 复制「含姓名列的整块」**，就会命中「源含首列」。**建议：源块里的姓名列直接丢弃 + 计数提示**，而不是整块拒绝（我们的首列是只读的，拒绝会让最常见的操作路径失败）。
3. **HTML vs TSV**：抄 ② 那句 `microsoft` 判别。注意 WPS/腾讯文档/Google Sheets 的 HTML 里**不一定**带 `microsoft` 字样 ⇒ **未验证**（见 §9），因此**回退策略必须是「html 解析失败一律走 text/plain」**，不能依赖白名单。

### 3.4 附带发现：Odoo 19 核心有一个剪贴板**写入** polyfill（可复用）

`addons/web/static/src/polyfills/clipboard.js`（LGPL-3，随 `spreadsheet.o_spreadsheet` bundle 加载）：
- 补 `navigator.clipboard.write`（Firefox 部分实现）与 `window.ClipboardItem`；
- 内部用「临时 shadow DOM + `document.execCommand("copy")`」实现；
- **它的注释明写**：`Calling clipboard.write() without a "text/plain" type may result in an empty clipboard on some platforms.` ⇒ **反向**说明「写剪贴板必须带 text/plain」这条跨平台坑。

> **与本仓 M2 的关系**：我们**只读剪贴板**（粘贴），不写剪贴板 ⇒ 这个 polyfill **不需要**。但如果后续要做「复制一块成绩到 Excel」（M2 的镜像功能），**这就是现成的**，不必自研。

## 4. Odoo 19 `spreadsheet` 模块正面评估（**这条决定设计方向，单独成节**）

### 4.1 先切开 license 边界（这是全节的地基）

用 `grep -oE "['\"]license['\"] *: *['\"][^'\"]*['\"]" <模块>/__manifest__.py` 逐个取证（命令见 §10）：

| 模块 | license | 说明 |
|---|---|---|
| `spreadsheet` | **LGPL-3** | 编辑器外壳 + **整个 o-spreadsheet 库**（`static/src/o_spreadsheet/o_spreadsheet.js`，78699 行） |
| `spreadsheet_dashboard` | **LGPL-3** | ⚠ **在社区版 `odoo:19` 官方镜像里就有**（`docker exec edu19-clone-web-1 ls .../addons \| grep spreadsheet` 列出 14 个 `spreadsheet_dashboard*`）。**只读**展示看板 |
| `spreadsheet_account` | **LGPL-3** | 会计数据源 |
| `spreadsheet_edition` | **OEEL-1** | ← **可编辑的持久化/协作/导出路由都在这里** |
| `spreadsheet_dashboard_edition` | **OEEL-1** | ← `action_edit_dashboard`（"编辑看板"入口） |
| `spreadsheet_sale_management` | **OEEL-1** | ← **回写业务记录**（销售订单行）的能力在这 |
| `web_grid` / `web_studio` / `hr_appraisal` / `account_reports` | **OEEL-1** | 与 `evaluation-rebuild.md` 结论一致 |

### 4.2 只读是**运行期开关**，不是代码被删掉了（关键机制）

`addons/spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js`：

```js
// 行 78085
isReadonly: () => this.config.mode === "readonly" || this.config.mode === "dashboard",
// 行 78224
const isReadonly = config.mode === "readonly" || config.mode === "dashboard";
```

- `mode` 是**调用方传进来的 config**；社区版唯一入口把它**写死成只读**：
  `spreadsheet/static/src/public_readonly_app/public_readonly.js:58` →
  `mode: this.props.mode === "dashboard" ? "dashboard" : "readonly"`
- 而 `isReadonly()` 的**全部拦截点都在 LGPL-3 的 bundle 里**（`9023`/`9028` 返 `noStateChange`；`29469`/`29474`/`29482`；`44056`；`44951`/`45002`；`62268`；`68924`），**不是**被 OEEL-1 模块 patch 掉的。

> **这一条必须写明性质**：这说明「社区版只读」是**Odoo 用入口点（OEEL-1 模块）实现的商业边界**，不是**技术能力边界**。
> **结论只陈述事实，不构成建议**：任何「在自研模块里用 LGPL-3 的 `spreadsheet` bundle + 传 `mode:"normal"` 拿到可编辑表格」的做法，**绕开的是 Odoo 的企业版商业边界**（不是版权边界），
> 属于**需法务确认**的灰区，且**必然**在官方升级/补丁中出问题（社区版的 `spreadsheet` 模块不承诺支持这种用法）。
> **干净的替代路径**：o-spreadsheet 本身是独立上游项目（`git ls-remote https://github.com/odoo/o-spreadsheet` **确认存在**，分支含 `14.0`/`15.0`…，LGPL-3），**把它当第三方库用**与「拿 Odoo 社区模块改开关」是两件事——前者是 OCA `spreadsheet_oca` 走的路线（§5）。

### 4.3 LGPL-3 bundle 里**真的**有什么（能力清单，全部源码取证）

| 能力 | 有没有 | 证据 |
|---|---|---|
| 冻结行/列（**真正的 Excel 式冻结窗格**） | ✅ | `FREEZE_ROWS`/`FREEZE_COLUMNS`/`UNFREEZE_*` 命令（`1739-1743`）；交互入口 `interactiveFreezeColumnsRows(env, dimension, base)`（`38964`）；右键菜单「Freeze / Freeze first row / Freeze first column / Unfreeze」（`39245-39304`）；渲染 `drawFrozenPanes()`/`drawFrozenPanesHeaders()`（`45882-45917`） |
| 冻结的**数据结构** | ✅ | 每 sheet 存 `xSplit/ySplit`；`getPaneDivisions`；`frozenContainerStyle`；`hasFrozenPane` getter（`45253-45451`） |
| **冻结在只读态也允许** | ✅ | `freezeFirstRow`/`freezeFirstCol` 等菜单项都带 `isReadonlyAllowed: true`（`39261-39304`） |
| 冻结与选区的交互约束 | ✅ | `doesZoneCrossFrozenPane`（`5220`）、`doesAnyZoneCrossFrozenPane`（`5226`） |
| **整块粘贴** | ✅ | §3.2 全表 |
| 公式/子总计（SUBTOTAL 等） | ✅ | `34745`「Conversion map for the SUBTOTAL(index, formula) function in xlsx」 |
| **xlsx 读**（完整 reader） | ✅ | `src/xlsx/xlsx_reader.ts`（`37581`），`XlsxReader.convertXlsx()`；`EXCEL_IMPORT_VERSION = "18.4.2"`；extractor 覆盖 sheet/style/table/pivot/chart/figure/data_validation/cf（`36289-37581`） |
| **xlsx 写** | ✅ | `src/xlsx/xlsx_writer.ts`（`77722`）；`Model.exportXLSX()`（`78442`） |
| 数据验证（**下拉档位**） | ✅ | `data_validation_clipboard.ts`（`8251`）、`convertDataValidationRules`（`35687`） |
| 条件格式（**超分标红**） | ✅ | `conditional_format_clipboard.ts`（`8136`）、`convertConditionalFormats`（`35119`） |
| **导出 xlsx 的 HTTP 路由** | ❌ 社区没有 | `/spreadsheet/xlsx` 定义在 `spreadsheet_edition/controllers/main.py:32`（**OEEL-1**） |
| **xlsx 导入的 UI 入口** | ❌ 无（库有、入口无） | `grep -rn "XlsxReader" addons/ --include=*.js` **只命中 bundle 自己**（`37583` 定义、`38106` 内部调用）；`helpers.js:60` 还留着 TODO「replace it by the one in o_spreadsheet xlsx import when its merged」 |
| **回写业务记录** | ❌ 社区没有 | 回写在 `spreadsheet_sale_management/models/sale_order_spreadsheet.py`（**OEEL-1**） |

### 4.4 正面回答：**它是不是「像 Excel 一样好用」的现成答案？**

**分三层答，不能一句「是/不是」：**

#### (a) 作为「一个像 Excel 的表」——是，而且比自研强得多
冻结窗格、整块粘贴、公式、小计、条件格式、数据验证、xlsx 双向 —— **这七条全部在 LGPL-3 的库里**。**我们设计文档 §6.6/§6.7 要自研的两条，在这个库里都是现成的**（而且「冻结」比我们的 sticky 方案更彻底：它冻的是窗格，支持任意行列数、支持只冻行/只冻列/都冻，`39245-39304`）。

#### (b) 作为「我们评估表的答案」——**不是**，四条硬理由（每条带源码依据）

| # | 理由 | 依据 |
|---|---|---|
| 1 | **它是文档（JSON 二进制块），不是记录列表**。 `spreadsheet.dashboard` 把整本工作簿存在一个 Binary 字段里：`spreadsheet/models/spreadsheet_mixin.py:22` `spreadsheet_binary_data = fields.Binary(...)`；校验方式是 `json.loads(base64.b64decode(...))`（`:34`）。**行=学生、列=评分项 的关系不在 ORM 里**，而是在这坨 JSON 里 ⇒ 我们现有的「服务端算分 / 幂等键 / 名单唯一键 `UNIQUE(task_id, subject_ref)` / 已打分行拒删」**全部失去落点** | `spreadsheet_mixin.py:22,30-35` |
| 2 | **社区版没有可保存的编辑回路**。可编辑要走 `spreadsheet_edition`（OEEL-1，提供 `spreadsheet.revision` 协作/持久化）或 OCA `spreadsheet_oca`（AGPL-3）。社区版唯一路径（`public_readonly.js:58`）**把 mode 写死**，改它就是 §4.2 那条灰区 | `public_readonly.js:58`、`spreadsheet_edition/models/spreadsheet_revision.py` |
| 3 | **没有「回写业务记录」的社区能力**。要让粘贴进去的数落回 `edu.assess.score`，得自己写一整套（库只提供 `ODOO.LIST` 这类**只读**数据源读取）。Odoo 自己的回写范例是 OEEL-1 的销售模块 | `spreadsheet_sale_management/models/sale_order_spreadsheet.py:36` |
| 4 | **算分算法会被搬到前端**。设计文档 §6 E7 明写「**单一算法源：凡算分的事一律在服务端**」；spreadsheet 的中心思想是前端公式引擎。用它当录入面，等于让「总分」变成可被用户改的单元格 ⇒ 与 §6 的总原则直接冲突 | 设计文档 §6（`eval-unified-design.md`）自述原则 |

**第 5 条（非技术）**：我们已有 `edu.assess` 五层模型 + `assess_grid.js` + 门户模板，设计文档 §6 的 E6/E7 自评「**纯前端、零字段、零模型**」。改用 spreadsheet 是**换渲染范式**（相当于把「一个引擎一套矩阵」推翻，重开一条文档型资产线），成本远大于 E6+E7 本身。

#### (c) 对我们的**实际可用价值：抄形状 + 可选做库级复用**

| 用法 | 评价 |
|---|---|
| **抄 §3.2 的粘贴内核 + §2 的 sticky 变量法** | ✅ **推荐**。这就是「能抄不造」能落地的部分 |
| **抄 o-spreadsheet 的「冻结窗格」思路替代 sticky** | ⚠ 不推荐：那是 canvas 内偏移（`frozenContainerStyle`/`drawFrozenPanes`），要求整表由 canvas 渲染；我们的矩阵是原生 `<table>+<input>` + 表单 POST。**换渲染等于重写** |
| **把 o-spreadsheet 当第三方库**（不经过 Odoo 的 `spreadsheet` 模块入口）用于「Excel 式自由编辑」场景 | ⚠ **未验证**（我没有实测 Odoo 19 的 asset bundle 是否能干净地引入上游 o-spreadsheet），且属于**架构级决定**，应单独立项，不在 E6/E7 范围内 |
| **直接装 `spreadsheet_oca` 当编辑面** | ❌ 本期不建议：AGPL-3（§5）+ 上面 (b) 四条理由仍然成立 |

### 4.5 对 `evaluation-rebuild.md` 的两处**行号级修正**（不改变它的结论）

- 它引用 `o_spreadsheet.js:78149 / 78288` 作为「只允许 readonly/dashboard」的证据；在**本机 19.0 FINAL 全量源码**里同一断言位于 `78085 / 78224`，**漂移 −64 行** ⇒ 证实 README §4「行号会漂移」的警告。**结论不变**（`isReadonly` 的判定表达式逐字相同）。
- 它说「`spreadsheet` 社区版只读」——**本次补充**：社区版 **`spreadsheet_dashboard` 是 LGPL-3 且真的在官方 `odoo:19` 镜像里**（不是企业版独占），**只读展示**可用；**可编辑**才是 OEEL-1。

## 5. OCA 可装模块清单（含 license，**逐个从 `__manifest__.py` 取证**）

**取证方式（可复现）**：下载 `19.0` 分支 tarball 后扫 manifest，**不依赖任何 API**（api.github.com 额度已耗尽，故绕开）：

```bash
mkdir -p /tmp/oca && cd /tmp/oca
git ls-remote --heads https://github.com/OCA/web | grep 19.0          # b405af9c04a04d74b1e34bdf827fe4033a28899a
git ls-remote --heads https://github.com/OCA/spreadsheet | grep 19.0  # 300839166475965e1c8d39870b68094c15a76798
curl -sL -o web-19.0.tar.gz         https://codeload.github.com/OCA/web/tar.gz/refs/heads/19.0
curl -sL -o spreadsheet-19.0.tar.gz https://codeload.github.com/OCA/spreadsheet/tar.gz/refs/heads/19.0
tar xzf web-19.0.tar.gz && tar xzf spreadsheet-19.0.tar.gz
# 逐模块取 license（正则脚本见 §10）
```

**扫描结果（OCA/web@19.0 共 36 个模块，逐个核对 "license" 键）**：

| 模块 | license | 版本 | 与本课题的关系 |
|---|---|---|---|
| **`web_widget_x2many_2d_matrix`** | **AGPL-3** ⚠ | 19.0.1.0.0 | 🎯 **最贴近的先例**：二维矩阵小组件，「行×列可编辑 + 四向冻结」全都有（§5.1） |
| **`web_responsive`** | **LGPL-3** ✅ | 19.0.1.1.0（Production/Stable） | 只补**列表粘性页脚**（`bottom: 0`）+ 移动端粘性控制面板；**表头粘性在 Odoo 19 已是核心**（§2.1）⇒ ⚠ **修正 `ui-usability-discovery.md` 里「web_responsive 提供列表粘性表头」的表述**：在 19.0 上表头粘性不是它提供的 |
| `web_remember_tree_column_width` | **LGPL-3** ✅ | 19.0.1.0.0 | 记住列表列宽（**不涉及冻结**），属「长表好用」同族但与本课题无关 |
| `spreadsheet_oca` | **AGPL-3** ⚠ | 19.0.1.0.1（Beta） | 「Odoo CE 里**新增和编辑** Spreadsheet」——**企业版 `spreadsheet_edition` 的社区替代品**（§5.2） |
| `spreadsheet_dashboard_oca` | **AGPL-3** ⚠ | 19.0.1.0.0 | 看板版 |
| `spreadsheet_dashboard_purchase_oca` / `spreadsheet_dashboard_purchase_stock_oca` | **AGPL-3** ⚠ | — | 采购数据源，与本课题无关 |
| `web_group_expand` / `web_quick_start_screen` / `web_dark_mode` / `web_timeline` / `web_m2x_options` 等 24 个 | **AGPL-3** ⚠ | — | 与本课题无关（已在 `ui-usability-discovery.md` 登记） |
| `web_calendar_slot_duration` / `web_chatter_position` / `web_company_context_highlight` / `web_dialog_size` 等 | **LGPL-3** ✅ | — | 与本课题无关 |

**关键负结论（这三条是本节的产出）**：

1. **OCA/web@19.0 里没有任何模块给「列表视图」加冻结首列** —— 全仓 `grep -rn "position: *sticky"` 只有 **5 处**命中：4 处在 `web_widget_x2many_2d_matrix`，1 处在 `web_responsive` 的**页脚**。
2. **OCA/web@19.0 里没有任何模块做「粘贴」** —— `grep -rn -iE "addEventListener\\(.paste|onpaste|handlePaste|pasteEvent"` **0 命中**（唯一的 clipboard 命中是 `web_widget_url_advanced` 的「复制 URL 到剪贴板」，与表格无关）。
3. `OCA/vertical-education` 的 19.0 分支**存在**（`da4c4c12d48d47a8ab3d5fd27efeac78ad820b77`），但与本课题无关。

### 5.1 ⭐ `web_widget_x2many_2d_matrix` —— **四向冻结的完整先例（AGPL-3）**

**文件**：`web_widget_x2many_2d_matrix/static/src/components/x2many_2d_matrix_field/x2many_2d_matrix_field.scss`（19.0 分支，全 85 行，**逐行读过**）。原文结构（**行内注释是我加的，不是原文**）：

```scss
$x2many_2d_matrix_max_height: 450px;

.o_form_view .o_field_x2many_2d_matrix {
    .table-responsive { max-height: $x2many_2d_matrix_max_height; overflow-y: auto; }   // ← 自带滚动容器
    .table {
        > thead > tr > th {
            position: sticky; top: 0; z-index: 1; background-color: $o-gray-100;         // ← 冻表头
            &.total { right: 0; }
        }
        > tbody > tr > td {
            &:first-child { position: sticky; left: 0;                                   // ← 冻首列
                border-right: 1px solid $gray-300; background-color: $o-view-background-color; }
            &.row-total { position: sticky; right: 0;                                    // ← 冻右侧合计列
                border-left: 1px solid $gray-300; background-color: $o-view-background-color; }
        }
        > tfoot > tr > th { position: sticky; bottom: 0; background-color: $o-gray-100; } // ← 冻页脚
    }
}
```

**四条可直接搬到 E6 的实现要点**（比设计文档 §6.6 更完整）：

| # | 要点 | 为什么重要 |
|---|---|---|
| 1 | `.table-responsive { max-height: 450px; overflow-y: auto; }` | **这就是设计文档 §6.6 ① 说的「让矩阵自己成为滚动容器」**，而且**只写 `overflow-y`** —— 因为 CSS 规定：`overflow-x: visible` 与 `overflow-y: auto` 同时出现时，`visible` 会被**表现为 `auto`** ⇒ 同一个盒子**同时**是纵/横滚动容器 ⇒ **冻首列才有横向 scrollport**（§7 展开） |
| 2 | 每个 sticky 元素都**显式给 `background-color`**（表头用 `$o-gray-100`、单元格用 `$o-view-background-color`） | 与设计文档 §6.6 ② 一致；**两条独立实现者踩到同一个坑** ⇒ 这条是硬约束不是偏好。⚠ **但 OCA 这条只覆盖了默认态，漏了 hover/条纹态 —— Moodle 有更完整的做法，见 §6.2 经验 2** |
| 3 | 用 `border-right: 1px solid $gray-300` **而非 box-shadow** 画冻结列分隔线 | 说明「边框」在原生 table 上**可以直接用**（前提是没被 `border-collapse: collapse` 吃掉边线）⇒ **未验证**，见 §9 |
| 4 | **表头 `z-index: 1`，首列单元格不声明 `z-index`；交叉格（`th:first-child`）靠表头规则拿到 1** | 与设计文档 §6.6 ③「交叉格 `z-index: 3`」**是不同解法**。OCA 的解法更省事，**但只在「交叉格是 `<th>`」时成立**；我们的矩阵第一行第一列确实是 `<th>` ⇒ **可照抄，但必须实测** |

**license 判定**：`"license": "AGPL-3"`（`__manifest__.py`），README badge 亦写 AGPL-3，maturity 为 Production/Stable。
⇒ **按本课题要求：AGPL-3 的传染性标注为「需法务确认」**（与既有调研对 OCA 全系的处理一致）。
⇒ **可立即采用的形态：只抄这 20 行 SCSS 的「思想/方法」（版权不保护思想），不 copy 代码、不装模块。** 若要**装模块**，必须先过法务。

### 5.2 `spreadsheet_oca`（AGPL-3）—— CE 里的「可编辑 Spreadsheet」

- README 原文（19.0 分支，逐字）：「**This module adds a functionality for adding and editing Spreadsheets using Odoo CE. It is an alternative to the proprietary module `spreadsheet_edition` of Odoo Enterprise Edition.**」
- 能力（文件树取证）：`models/spreadsheet_spreadsheet.py`、`spreadsheet_oca_revision.py`（修订）、`spreadsheet_spreadsheet_tag.py`、`spreadsheet_spreadsheet_import_mode.py`、`ir_websocket.py`（协作）、`static/src/spreadsheet/bundle/odoo_panels.esm.js`（插 Odoo 数据源面板）
- README 指向的上游文档：`https://odoo.github.io/o-spreadsheet/`
- ⚠ **与 §4.4 的关系**：它解决「**CE 能不能编辑 spreadsheet**」，**不解决**「评估表要不要变成 spreadsheet」——§4.4(b) 的四条理由对它**同样成立**（文档型 JSON、记录关系不在 ORM、算分跑前端、换渲染范式）。

### 5.3 本节**没找到**的（明确写下来，免得下一个人再走一遍）

| 想要的东西 | 找法 | 结果 |
|---|---|---|
| 「列表视图冻结首列」的 OCA 模块 | 全仓 `grep -rn "position: *sticky"` + 逐模块读 scss | **没有** |
| 「网页表格整块粘贴」的 OCA 模块 | 全仓 `grep -rn -iE "paste\|clipboard"` | **没有**（只有「复制 URL 到剪贴板」） |
| 「成绩/评估矩阵」的 OCA 模块 | 既有多份调研已查（`evaluation-rebuild.md`：`vertical-education` 19.0 空仓 + appraisal/grade 全组织 0 命中） | **不重复**，沿用既有负结论 |

## 6. 同类系统怎么做（Moodle / Canvas / 通用库 / 国内）

### 6.1 通用做法：**两大主流表格库把「冻结列」与「粘性表头」当成两件事**

#### (a) DataTables（MIT）

- **官方对两个能力的切分**（原文，`https://datatables.net/extensions/fixedcolumns/`）：
  > 「When making use of DataTables' x-axis scrolling feature (`scrollX`), you may wish to fix the left or right most columns in place. This extension for DataTables provides exactly this option (**for non-scrolling tables, please use the FixedHeader extension, which will create sticky headers and footers for tables**).」
  ⇒ **冻结列 = FixedColumns；粘性表头 = FixedHeader**。**冻结列这个扩展不负责表头**。这条官方切分**正面支持**设计文档把 E6 拆成两件事来做（表头、首列）。
  - 官方还列了「**Support for complex headers / footers (colspan / rowspan)**」⇒ **多层表头是官方支持的能力**。
- **实现路线（源码级）**：`github.com/DataTables/FixedColumns`，`src/FixedColumns.ts`（584 行，MIT，`License.txt` 首行「MIT license」）：
  - `FixedColumns.ts:417` → `item.css('position', 'sticky').css(positionSide, off + 'px')` ⇒ **v5 用的是 CSS `position: sticky` + 逐列计算 `left/right` 偏移**，**不是**老的 scroll 同步。
  - `FixedColumns.ts:411-415` → 冻结**右侧**列时，表头/表尾的偏移要**再加一条滚动条宽度**：`if (side === 'end' && (part === 'header' || part === 'footer')) { off += barWidth; }` ⇒ **冻结右侧列必须补偿滚动条宽度**（我们只冻左侧，但**若将来加"合计列冻结在右"就会踩到**）。
  - `FixedColumns.ts:433-441` → `header.forEach(row => { if (row[idx]) applyStyles(Dom.s(row[idx].cell), 'header') })` ⇒ **多层表头的每一行都单独上 sticky**，不是只冻叶子行。
  - `FixedColumns.ts:488-500` → JS 监听 `scrollLeft` 只是**加状态类**：`classToggle(tableScrollingStart/End/Left/Right)`，注释写 `scrollLeft = scroller.scrollLeft; // 0 when fully scrolled left`、`+ Math.abs(scrollLeft) + 1; // extra 1 for Chrome` ⇒ **位置靠 CSS，JS 只做「是否已滚动」的样式开关**。**这正是设计文档 §7 若要做「滚动后加边框/阴影」该抄的形状**。
- **对我们最有用的一句**：DataTables 证明 **`position: sticky` 可以做到多层表头全冻 + 左右列都冻**，代价是要**自己算偏移**（含滚动条宽度）。

#### (b) SlickGrid（Canvas 用的表格引擎，仓库内 fork）

- `packages/slickgrid/slick.grid.js`（Canvas 仓库内，129 KB）：
  - `slick.grid.js:130` → `numberOfColumnsToFreeze: 0, // Number of left-most columns to freeze from scrolling`
  - 实现（`333-358`）→ 建**独立的冻结容器**：`const totalWidthOfFrozenColumns = ...` → `.css($.extend({}, containerCSS, {width: totalWidthOfFrozenColumns}))`，并**同步滚动位置**。
  - `packages/slickgrid/slick.grid.scss` **完全没有 `position: sticky`**（grep 0 命中）。
  ⇒ **SlickGrid 走的是「分栏 + 同步滚动」路线，不是 CSS sticky。**

> **§7 会用到这条对比**：两条路线在**有 overflow 祖先**时的表现完全不同 ——
> CSS sticky 路线**受祖先 scrollport 制约**（Moodle/OCA/DataTables v5），
> 分栏同步路线**不受** sticky 规则影响，但要自己维护滚动同步（SlickGrid）。**选哪条，取决于 §7 的判据在我们的门户页里能不能满足。**

#### (c) Handsontable 的粘贴语义（官方文档原文）

`https://handsontable.com/docs/api/options/` 原文（`copyPaste` 选项组）：

> `pasteMode` `'overwrite' | 'shift_down' | 'shift_right'`
> 「When pasting: **'overwrite'**: overwrite the currently-selected cells; **'shift_down'**: move the currently-selected cells down; **'shift_right'**: move the currently-selected cells to the right」

其他原文条目：`rowsLimit`/`columnsLimit`（`A number (default: Infinity)` **复制上限**，默认无限）、`copyColumnHeaders`（默认 `false`，「add a context menu option for copying cells along with their nearest column headers」）、`copyColumnGroupHeaders`；钩子 `beforePaste` / `afterPaste`（`https://handsontable.com/docs/api/hooks/`）。
另有 **`ManualColumnFreeze`** 插件与 `fixedColumnsStart` 选项（同 options 页）—— 印证「冻结列 + 整块粘贴」是**表格控件标配的两件套**。

**License**：`https://handsontable.com/license` → **HTTP 404**；`https://handsontable.com/docs/license-key/` 原文：
> 「Handsontable is available under **Commercial and Free licenses, depending on your usage.** We require you to specify which terms apply to your usage, by passing a license key…」

⇒ **确认它现在是「商业 / 免费双许可 + 必须显式传 licenseKey」**。具体价格与免费边界**以官方 pricing 页为准**（既有调研 `evaluation-rebuild.md` 已记「7.0.0 起非开源」，**此处不重复取证**）。

### 6.2 Moodle —— **冻结能力是核心一等公民，粘贴没有**（源码级）

**取证**（`github.com/moodle/moodle`，分支 `main`，**2026-09-28 克隆的 HEAD**；⚠ 未锁定 commit，`main` 会漂移）：

| 能力 | 结论 | 证据 |
|---|---|---|
| **任意列的「粘性列」API** | ✅ 有 | `public/lib/table/classes/flexible_table.php:108` `/** @var array The sticky attribute of each table column. */ protected $columnsticky = [];`；`:421` `public function column_sticky(string $column, bool $sticky = true): void`；`:423` 写入的类名是 `' sticky-column'`；`:1173`（数据格）、`:1373`（表头格）拼进 `class` |
| 对应的 CSS | ✅ | `public/theme/boost/scss/moodle/tables.scss:15-21`：`table { .sticky-column { position: sticky; left: 0; background-color: inherit; } }`；`:46-48`：`.table-hover { td.sticky-column { background-color: $table-hover-bg; } }` |
| **成绩册 grader 表**的冻结 | ✅ 全都有 | `public/theme/boost/scss/moodle/grade.scss`：`:566-570` `tr.heading { position: sticky; top: $navbar-height; z-index: 4; }`；`:600-607` `th.header { left: 0; position: sticky; &#studentheader { z-index: 1; } }`；`:582-591` `tr.lastrow:not(.userrow) { position: sticky; bottom: -1px; &.pinned { z-index: 4; } }` |
| 多层表头 colspan 的粘性偏移 | ✅ 有专门 JS | `public/grade/report/grader/amd/src/stickycolspan.js`（文件头注释原文：「**Javascript module for fixing the position of sticky headers with multiple colspans**」）：对 `colSpan > 1` 的 `th` **用 JS 补 `left/right` 偏移**：`tableHeader.style.left = 'calc(' + leftOffset + ' - ' + addOffset + 'px )'` |
| **整块粘贴** | ❌ **没有** | `public/grade/report/grader/amd/src/*.js` **逐文件读过**，`paste` **0 命中**；grader 的批量录入走**文件导入**（`grade/import`） |

**Moodle 给我们的 4 条可抄经验（比 OCA 那条更深）**：

1. **`top` 不能写 0，要写「导航条高度」**：`top: $navbar-height` ⇒ 我们的门户有固定头部时，表头 sticky 的 `top` **必须是头部高度**，否则表头会**藏到头部下面**。
2. **hover / 条纹行的背景必须单独覆盖**：`.sticky-column { background-color: inherit }` 在**默认态**够用，但 `.table-hover td.sticky-column` 必须**显式改成 hover 底色**。⇒ **设计文档 §6.6 ②「背景色必须显式给」只说了默认态，漏了 hover/条纹态。这是本次新增的必做项。**
3. **多层表头要用 JS 补偏移**（`stickycolspan.js`）：`colspan` 跨列的表头格，其 `left` 偏移**不是常数**，要靠 JS 按 `offsetWidth` 算。⇒ **设计文档 §6.6 ④「只冻结叶子表头行、不冻上层」的取舍，Moodle 证明"上层也能冻"，但代价是要一个 JS 偏移模块**。我们的取舍因此**有了依据**（省掉那个模块）。
4. **sticky 的副作用要主动修**：`stickycolspan.js` 开头注释原文：「The sticky positioning attributed to the user column cells affects the stacking context and **makes the dropdowns within these cells to be cut off**. To solve this problem … we need to **manually bump up the z-index**」；另有 `defineLastRowIntersectionObserver()` 与 `pinned` 类 —— 注释写「**Hack used by the observer to help detecting when the sticky last row is pinned**」⇒ **CSS 没有「当前是否吸附」的原生状态**，要 JS `IntersectionObserver`。**我们若只想「永远可见」而不加吸附态样式，可以完全不要这段** —— 这是省工作量的依据。

### 6.3 Canvas —— **冻结列有（SlickGrid 原生），整块粘贴没有**（源码级负结论）

**取证命令（可复现）**：

```bash
git clone --filter=blob:none --depth 1 --sparse https://github.com/instructure/canvas-lms /tmp/canvas
cd /tmp/canvas && git sparse-checkout set ui/features/gradebook
find ui/features/gradebook -type f | wc -l          # 404 个文件（整个成绩册前端）
grep -rn -i "paste"     ui/features/gradebook       # 0 命中
grep -rn -i "clipboard" ui/features/gradebook       # 0 命中
grep -rn -i "frozen\|sticky" ui/features/gradebook   # 命中 frozen，见下
```

| 能力 | 结论 | 证据 |
|---|---|---|
| **冻结首列（学生列）** | ✅ 有，且**可动态调** | `ui/features/gradebook/react/default_gradebook/GradebookGrid/GridSupport/Columns.ts:73-77`：`const frozenCount = this.grid.getOptions().numberOfColumnsToFreeze; … frozen: columns.slice(0, frozenCount), scrollable: columns.slice(frozenCount)`；`GradebookGrid/index.ts:68` `numberOfColumnsToFreeze: this.gridData.columns.frozen.length`；`Gradebook.tsx:628-637` 动态更新冻结集 |
| **整块粘贴（剪贴板）** | ❌ **没有** | 上述 grep 0 命中；全仓**只有** `packages/canvas-rce/src/rce/plugins/instructure_paste/*`（**富文本编辑器**的粘贴插件，与成绩册无关） |
| 批量成绩录入走什么 | **CSV 文件上传** | `app/controllers/gradebook_csvs_controller.rb`、`app/controllers/gradebook_uploads_controller.rb`、`app/models/gradebook_csv.rb`、`app/models/gradebook_upload.rb`、`lib/gradebook_importer.rb`、`app/views/gradebook_uploads/new.html.erb` |

> **这条负结论很有价值**：**全球最大的 LMS 的成绩册，也没有做「从 Excel 整块粘到网页表格」**，它选的是 **CSV 上传**（设计文档 §6.7 明确区分了这两条路）。
> ⇒ **E7「整块粘贴」在同类系统里确实没有直接先例可抄 UI 行为，只有 o-spreadsheet 那一份实现可抄**。

### 6.4 国内同类（功能名 + 官方 URL 级证据）

| 产品 | 冻结 | 粘贴 / 导入 | 官方 URL |
|---|---|---|---|
| **钉钉 · AI 表格** | ✅ **「Freeze up to this field / column」**：原文「Right-click the field title (or hover and click the dropdown) — pick **Freeze up to this field / column**.」「Hover the **freeze line** and drag left / right to adjust the frozen range.」「Note: the **primary field is frozen by default and can't be unfrozen**.」「unfreezing a single field is not yet supported」 | 官网只写**导入 Excel 文件**（`/aitable/getting-started/import-excel`），**未见「粘贴」条目**（**未验证是"没有"还是"没检索到"**，见 §9） | 冻结：<https://help.dingtalk.io/aitable/fields/add-field.md>；导入：<https://help.dingtalk.io/aitable/getting-started/import-excel.md>；索引：<https://help.dingtalk.io/llms.txt> |
| **钉钉 · 宜搭 子表单** | ✅ **「列冻结（表格方式）」**：官方原句「**目前仅支持PC端冻结前几列**…**支持自定义冻结几列，最多冻结5列；序号也记为1列；默认设置无**」 | ✅ **「批量导入」**：「支持 Excel 批量导入数据」「批量导入每次支持50条」；**导出后回导**：「子表信息导出本地 Excel 后，经过数据内容编辑，**子表内容支持重新导回到宜搭表单数据中**」。⚠ **该页全文 grep「粘贴」= 0 命中** ⇒ 宜搭也是**文件往返**，不是剪贴板块粘贴 | <https://docs.aliwork.com/docs/yida_support/wtwabe/up3ftx/in0w72>（本机 `curl` 实测 HTTP 200，正文可读） |
| **飞书 / 企业微信 / 校管家 / 学邦 / 希沃** | **未验证** | **未验证** | 见 §9 的具体原因 |

**国内给我们的两条产品级情报**：
1. **「冻结列」在国内产品里普遍是"前 N 列、N 有上限、主字段默认冻结"的模型**（钉钉 AI 表格「冻结到此列」+ 拖冻结线；宜搭「最多 5 列」）⇒ **我们的 E6「冻结首列」比它们都保守**，不存在"做得太花"的风险；但**若将来要做成"任意列冻结"，国内先例给的上限是 5 列**。
2. **国内没有任何一家做"剪贴板整块粘贴"进评估表**（宜搭、钉钉 AI 表格都走 Excel **文件**往返）⇒ **E7 是国内空白 + 同类空白**，只有 o-spreadsheet 一份实现可抄。

## 7. sticky 与 overflow 祖先：**失效判据**（正面回答设计文档标为未验证的 V1）

> ⚠ **2026-09-30 实测补记**：§7.1–7.5 是**规范级推导**，已在真实门户用浏览器实测复核，结果见 **§7.6**。**C1 / C3 / C6 / C7 / C8 实测确认；C2 的判据被实测推翻**（`overflow:hidden` 即使**无溢出内容**也照样劫持参考系）；`clip` 虽能修 sticky，但会**废掉该盒的横向滚动能力**。

### 7.1 规范原文（两条一手来源，都已 curl 取回原文）

**来源 A：CSS Positioned Layout Level 3 §3.4 Sticky positioning**（W3C Editor's Draft，<https://drafts.csswg.org/css-position-3/#sticky-pos>）：

> 「Sticky positioning is similar to relative positioning except the offsets are automatically calculated **in reference to the nearest scrollport**.」
> 「For a sticky positioned box, the inset properties represent insets from the respective edges of **the scrollport of the nearest scroll container with a matching scrollable axis**, defining the **sticky view rectangle** used to constrain the box's position. (The sticky view rectangle can be constructed from edges of **two different scrollports**, if the nearest scroll container is a single-axis scroll container.)」
> 「**If both inset properties in a given axis are auto, no offsets are added in that axis**; the element stays where it was laid out in that axis.」
> 「…then the box must be visually shifted (as for relative positioning) to be inward of that sticky view rectangle edge, **insofar as it can while its position box remains contained within its containing block**.」
> 「Note: A sticky positioned element with a non-auto top value and an auto bottom value **will only ever be pushed down** by sticky positioning; it will never be offset upwards.」
> 「Note: **Multiple sticky positioned boxes in the same container are offset independently, and therefore might overlap.**」

**来源 B：MDN `position`**（<https://developer.mozilla.org/en-US/docs/Web/CSS/position>）——**这句是判据的核心**：

> 「Note that a sticky element "sticks" to its **nearest ancestor that has a "scrolling mechanism" (created when overflow is hidden, scroll, auto, or overlay), even if that ancestor isn't the nearest actually scrolling ancestor**.」

**来源 C：MDN `overflow`**（<https://developer.mozilla.org/en-US/docs/Web/CSS/overflow>）：

> `visible`：「**The element box is not a scroll container.**」
> `hidden`：「When overflowing, the element box **is a scroll container with no scroll bars**；scrolling is still possible via other methods…」
> `clip`：「The element box is **not** a scroll container, clipped content…」
> `auto`：「The element box **is a scroll container only when there is overflowing content**.」
> 「When using the two value syntax, **if one value is set to `visible`, that visible overflow direction will behave as `auto` if the other value is not `visible` or `clip`.**」
> 「All values, except `visible` and `clip`, create a new block formatting context.」

### 7.2 ⭐ 结论：**「遇到 overflow 祖先就失效」是错的说法；正确的说法是「参考系被换掉了」**

- sticky 的参考系**永远是「最近的滚动盒子」**，而**滚动盒子由 `overflow` 的 computed 值决定，与"它实际上有没有在滚"无关**（MDN 原句：「**even if that ancestor isn't the nearest actually scrolling ancestor**」）。
- 所以 `overflow: hidden` 的祖先**不是"让 sticky 失效"，而是"把 sticky 的参考系劫持到一个永不滚动的盒子上"**。表现上就是——**页面在滚，表头不动**（因为它以为自己在原地没滚）。
- `overflow: clip` 的祖先**不会**劫持（它不创建滚动盒子）⇒ **如果门户里某个祖先只是为了"裁剪"而写了 `overflow: hidden`，改成 `clip` 可以让 sticky 恢复对更外层生效**。⚠ **这是本报告给出的一个可能的低成本解法，但未实测**（见 §9）。

### 7.3 **失效判据（可直接当验收清单用）**

按「**一定会失效**」→「**可能失效**」→「**一定没问题**」排：

| 判据 | 是否失效 | 依据 |
|---|---|---|
| **C1**：矩阵与视口之间**存在任意一个 `overflow: hidden` 的祖先，且该祖先内部确实有溢出内容**（即它真的是滚动盒子），而**用户实际滚动的却是更外层/页面** | ❌ **一定失效**（参考系被劫持，且被劫持到不滚的盒子上） | MDN `position` 原句 + MDN `overflow`（`hidden` 在有溢出内容时是滚动盒子） |
| **C2**：`overflow: hidden` 的祖先**内部没有溢出内容** | ✅ **不一定失效**（此时它**不是**滚动盒子，参考系会继续外寻） | MDN `overflow`：「When overflowing, the element box is a scroll container」（条件是"有溢出"） |
| **C3**：矩阵的**包含块太矮**——表总高不比滚动容器高多少，滚动容器视口 ≥ 表高 | ❌ **一定看不出冻结**（不是失效，是**没有行程**：sticky 只能在包含块内移动） | CSS Position 3：「insofar as it can **while its position box remains contained within its containing block**」 |
| **C4**：只写了 `top` 没写 `left`（或反之），却期望两个轴都冻 | ❌ **该轴一定不冻**（不是 bug） | CSS Position 3：「**If both inset properties in a given axis are auto, no offsets are added in that axis**」 |
| **C5**：表头 sticky 的 `top` 写了 `0`，但页面上有**固定定位的头部/导航条** | ⚠ **"看起来失效"**（表头被头部盖住） | Moodle 用 `top: $navbar-height` 而非 0（§6.2） |
| **C6**：祖先用 `overflow: clip` | ✅ **不劫持** | MDN `overflow`：`clip` 不是滚动盒子 |
| **C7**：**矩阵自己就是滚动容器**（`max-height` + `overflow: auto`/`hidden`），行列都在里面滚 | ✅ **一定生效**（参考系就是它自己） | MDN：「sticks to its nearest ancestor that has a scrolling mechanism」；Odoo `.o_content{overflow:auto}`（§2.2）与 OCA `.table-responsive{max-height;overflow-y:auto}`（§5.1）都是这个形状 |
| **C8**：**单轴滚动**（只写 `overflow-y: auto`）却想冻首列 | ✅ **仍然生效**：`overflow-x` 的 `visible` 会**表现为 `auto`** ⇒ 同一个盒子**同时**是横轴滚动容器 | MDN `overflow` 双值语法原句（§7.1 来源 C） |

**设计文档 §6.6 ① 的原文是**「`position: sticky` **只在最近的滚动祖先里生效**。若指望页面级滚动，表头会随页面滚走；若外层门户已有 `overflow` 也会让 sticky 失效 ⇒ **矩阵必须自己成为滚动容器**」——**这条判断正确，措辞需要修正**：不是"外层有 overflow 就失效"（C2/C6 是反例），而是"**外层的 overflow 会抢走参考系**"；**结论（矩阵自己当滚动容器）依然是对的做法**，因为它把参考系变成确定的那一个（C7）。

### 7.4 我们门户页要**实测**的三件事（本报告没测，如实列为未验证）

1. **门户布局里，矩阵到视口之间有哪些祖先带 `overflow`？** 逐个取 computed `overflow-x/y`。命令（浏览器控制台）：
   ```js
   let el = document.querySelector('.yy-assess-matrix');
   while (el && el !== document.documentElement) {
     const s = getComputedStyle(el);
     if (s.overflowX !== 'visible' || s.overflowY !== 'visible')
       console.log(el.tagName + '.' + el.className, s.overflowX, s.overflowY, 'scrollH=' + el.scrollHeight, 'clientH=' + el.clientHeight);
     el = el.parentElement;
   }
   ```
   **判断**：任何一条 `scrollH > clientH` 的祖先 = 它是真滚动盒子；若**用户实际滚动的是它**，C7 已满足；若不是 ⇒ 命中 C1。
2. **`overflow: clip` 替代方案是否可行**：把劫持祖先改为 `clip` 后，表头/首列是否恢复 —— **需要真实浏览器验证**（我的环境只有 curl/无头能力未验证）。
3. **多行表头（一级/二级分组行）**：设计文档 §6.6 ④ 决定"只冻叶子行"。DataTables 证明"每行都能冻"（§6.1a），Moodle 证明"colspan 需要 JS 补偏移"（§6.2）⇒ **我们的取舍有据，但要注意：不冻的上层行**在纵向滚动时会**从叶子行上方滑过**，视觉上需要**给叶子行足够不透明背景 + 边界阴影**（呼应 §6.2 经验 2）。

### 7.5 除 sticky 之外的**两条现成替代路线**（都有一手先例）

| 路线 | 谁在用 | 优点 | 代价 |
|---|---|---|---|
| **A. 纯 CSS `position: sticky`**（+ 矩阵自己当滚动容器） | Odoo 19 核心表头（`list_renderer.scss:14-24`）、OCA 四向冻结矩阵（`x2many_2d_matrix_field.scss`）、DataTables FixedColumns v5（`FixedColumns.ts:417`）、Moodle grader（`grade.scss:566-607`） | **零 JS**（除非要"已吸附"状态类）；设计文档 §6.6 的路线 | 受 §7.3 的 C1/C3/C4 制约 |
| **B. 分栏 + 同步滚动**（SlickGrid 式） | Canvas 成绩册（`slick.grid.js:130,333-358`）；**老版** DataTables FixedColumns 亦同 | **完全不受 sticky 规则影响** —— 没有"参考系被劫持"这回事 | 要自己维护 `scrollLeft/scrollTop` 同步与列宽一致；= 自研一个小组件 |

**建议**：先按 A 走（成本最低、先例最多），**用 §7.4 第 1 步的 3 行控制台脚本先判定门户是否满足 C7**；只有在 C1 无法通过改布局消除时才考虑 B。

### 7.6 实测结论（2026-09-30 补 · 真实浏览器 + 真实门户）

> **本节只加实测对照 —— §7.1–7.5 的原文推导与 C1–C8 判据一字未改。** 凡实测与原推导不一致的，**以本节为准**（有 1 条被实测推翻，见 7.6.4 的 C2）。
> 本节同时闭环 §9 的 **V-1**（门户祖先 overflow 清单）与 **V-2**（`overflow: clip` 是否恢复）。

#### 7.6.1 取证环境（可复现）

```bash
# 仓库默认 python3=3.9 且无 playwright；用下面两个解释器之一
/opt/homebrew/bin/python3 -c "import playwright, sys; print(sys.version, playwright.__file__)"
# 容器（本地克隆 edu19；非生产）
docker ps --format '{{.Names}}\t{{.Status}}' | grep edu19-clone-web-1
```

- 浏览器：Playwright + **Chromium 148.0.7778.96**；视口 **1440×900**
- 账号：`stu@local` / `faculty@local` / `backoffice@local`，口令均 `demo123`
- 被测页面（`.yy-assess-matrix` **真实存在**，不是构造页）：`stu:/assess/fill/2`、`faculty:/assess/grade/1`、`/assess/grade/3`、`/assess/task/1/results`、`/assess/task/3/results`、`backoffice:/assess/task/3/results`
- 判定口径（两侧都留原始值）：
  - **未吸附** = 屏幕位移 `moved ≈ −scrolled`（随内容一起走）
  - **已吸附** = `moved ≈ 0`（停在屏幕上不动）
  - 竖向统一「**先预滚使 sticky 充分进入行程，再滚一段量位移**」，避免把「还没滚到顶」误读成失效
- ⚠ 门户真实页面矩阵只有 2–5 行，**行程不足以让表头滚到顶**（见 7.6.5 ③），故真实页面测试中把 `tbody` 克隆到 26 行并补一段占位。这是任务允许的「直接改 DOM」，**祖先链与几何未改**，只增加行程。

**核心测量片段**（贴进真实门户的控制台即可复跑；`pre` 是「让 sticky 充分进入行程」的预滚，`delta` 是「量位移」的那一段）：

`@js
// 1) 先注入 sticky（门户当前没有这段 CSS）
const st = document.createElement('style');
st.textContent = '.yy-assess-matrix thead th{position:sticky;top:0;z-index:9;background:#fff}';
document.head.appendChild(st);

// 2) 两段式测量：未吸附 => moved ≈ -scrolled；已吸附 => moved ≈ 0
(function (pre = 800, delta = 200) {
  const th = document.querySelector('.yy-assess-matrix thead th');
  window.scrollTo(0, 0);
  window.scrollBy(0, pre);
  const a = th.getBoundingClientRect().top, y0 = window.scrollY;
  window.scrollBy(0, delta);
  const b = th.getBoundingClientRect().top, y1 = window.scrollY;
  console.log({ park: y0, thAtPark: a, end: y1, thAtEnd: b,
                scrolled: y1 - y0, moved: b - a,
                verdict: Math.abs(b - a) < 1.5 ? '已吸附' : (Math.abs((b - a) + (y1 - y0)) < 1.5 ? '未吸附（随内容走）' : '部分行程') });
})();
`@
> ⚠ `pre` 必须足够大（本次用 800，视口 900、矩阵顶在 y≈379），否则会量到「还没滚到顶」而**误判成失效** —— 这是本次踩到并修掉的第一个坑。
> 横向用同一函数把 `scrollBy(0, delta)` 换成 `scroller.scrollLeft += delta`、把 `getBoundingClientRect().top` 换成 `.left` 即可。

#### 7.6.2 门户里带 overflow 的祖先（§7.4 第 1 步原脚本，补 `html` 一层）

`stu /assess/fill/2`（1440×900）实测：

| 层 | 元素 | computed overflow-x / -y | scrollH / clientH | scrollW / clientW | 是真滚动盒？ |
|---|---|---|---|---|---|
| 1 | `table#yy-assess-fill-table.yy-assess-matrix` | visible / visible | 121 / 121 | 1178 / 1178 | 否 |
| **2** | **`div.table-responsive.card.shadow-sm.border-0.rounded-3`** | **hidden / hidden** | **121 / 121** | **1178 / 1178** | **否（没有溢出内容）** |
| 3 | `form` | visible / visible | 175 / 175 | 1178 / 1178 | 否 |
| 4 | `div.container.pt-3.pb-5.b11-content` | visible / visible | 537 / 537 | 1208 / 1208 | 否 |
| 5 | `div.b11-body` | visible / visible | 836 / 836 | 1440 / 1440 | 否 |
| 6 | `div#wrap.o_portal_wrap.b11-shell` | visible / visible | 900 / 900 | 1440 / 1440 | 否 |
| 7 | `main` | visible / visible | 900 / 900 | 1440 / 1440 | 否 |
| 8 | `div#wrapwrap.o_portal` | visible / visible | 1081 / 1081 | 1440 / 1440 | 否 |
| 9 | `body` | visible / visible | 1081 / **900** | 1440 / 1440 | **是（页面滚动就是它）** |
| 10 | `html` | visible / visible | 1081 / 900 | 1440 / 1440 | 是（视口滚动系；原脚本不含此层） |

**V-1 结论**：全页共 **35 个**元素带非 `visible` 的 `overflow`（多为下拉菜单等 UI 零件），但**落在矩阵祖先链上的只有 1 个** —— 第 2 层 `.table-responsive`，且它 `scrollH == clientH`（**没有溢出内容**）。这正是 §7.3 **C2** 描述的形状。

#### 7.6.3 三项点测的原始测量值

**（a）C6 —— 祖先改 `overflow: clip` 是否真的不劫持**

最小可复现页为**单变量 A/B**（除该祖先的 `overflow` 值外，DOM/CSS/尺寸全同，祖先高 807 与内容等高）；真实门户另做一组。

| 组 | 祖先 `overflow` | 祖先 scrollH / clientH | 可程序滚动 | 滚 200px 后表头位移 | 判定 |
|---|---|---|---|---|---|
| V0 对照 | visible | 807 / 807 | 否 | **0** | 已吸附 |
| **V1（C6）** | **clip** | 807 / 807 | 否 | **0** | **已吸附 ⇒ C6 成立** |
| V2（C2） | hidden | 807 / 807 | 否 | **−200** | **未吸附（随内容走）** |
| V3（C1） | hidden + max-height:200px | 807 / 200 | 是 | −100 | 未吸附 |
| V4 参照 | auto + max-height:200px | 807 / 200 | 是 | −100 | 未吸附 |
| **P1 真实门户** | wrapper 改 **clip** | 1191 / 1191 | — | park 409 时 `−30.33` → 再滚 200 后 **`0`** | **已吸附 ⇒ C6 在真实门户成立** |
| P0 真实门户 | wrapper 保持 hidden | 1191 / 1191 | — | park 409 时 `−30.33` → 再滚 200 后 **`−230.33`** | **未吸附** |
| P2 对照 | wrapper 改 visible | 1191 / 1191 | — | `0` → `0` | 已吸附 |

⇒ **C6 从「规范推断」升级为「已实测」**。⚠ 但 `clip` 有原报告未计及的代价，见 7.6.5 ②。

**（b）C8 —— 只写 `overflow-y: auto` 时 `overflow-x` 是否表现为 `auto`、冻首列是否仍成立**

| 组 | 祖先 CSS | computed overflow-x | 横向滚动量 | 首列位移 | 判定 |
|---|---|---|---|---|---|
| **H1（合成）** | **只写 `overflow-y: auto`** | **auto** | 260 | −0.5 | **首列已吸附 ⇒ C8 成立** |
| H2（合成） | `overflow: hidden` | hidden | 260 | −0.5 | 已吸附 |
| H0 对照 | 无 overflow 祖先，滚窗口 | visible | 200 | −0.5 | 已吸附 |
| **P5 真实门户** | wrapper **只写 `overflow-y:auto`** | **auto** | 300 | 247 → **247** | **首列已吸附 ⇒ C8 在真实门户成立** |
| P4 真实门户 | wrapper `overflow:hidden` | hidden | 300 | 247 → 247 | 已吸附 |

⇒ **C8 的两段都被实测到**：① MDN 那条「一值为 `visible`、另一值非 `visible`/`clip` 时表现为 `auto`」在 Chromium 148 上 **computed 值确为 `auto`**；② 该盒**确实是横向滚动容器**，冻首列**照样成立**。（表的水平加宽属本次 DOM 改造，见 7.6.1）

**（c）C7 —— 矩阵自己当滚动容器是否一定生效**

| 组 | 布局 | 滚动谁 | 表头屏幕位置 | 判定 |
|---|---|---|---|---|
| V5（合成） | wrapper `overflow:auto` + `max-height:300px` | wrapper（300 → 500） | 不动 | **已吸附** |
| **P3′ 真实门户** | `.table-responsive` 改 `overflow:auto` + `max-height:300px`（即设计文档 §6.6 ① 的形状） | wrapper（120 → 270） | `378.67` → **`378.67`** | **已吸附 ⇒ C7 在真实门户成立** |

⇒ **C7 成立**。`378.67` 是 wrapper 自身在视口里的顶边；表头**停在它上面不动**，说明参考系确实换成了矩阵自己的滚动盒。

#### 7.6.4 C1–C8 逐条对照（推导 → 实测）

| 判据 | §7.3 原推导 | 本次实测（原始值） | 结论 |
|---|---|---|---|
| **C1** | ❌ 一定失效 | V3：`hidden` 且有溢出，滚窗口 200 后表头 −100（随内容走） | ✅ **确认** |
| **C2** | ✅ 不一定失效（「无溢出 ⇒ 不是滚动盒 ⇒ 参考系继续外寻」） | V2：`hidden` 且 `scrollH == clientH`（**无溢出**），滚窗口 200 后表头 **−200**；真实门户 P0 即此形状，同样 −200 | ❌ **被实测推翻** |
| **C3** | ❌ 一定看不出冻结（没有行程） | 门户 `/assess/fill/2`：doc 1081 / 视口 900 ⇒ **仅 181px 行程**，而矩阵顶在文档 y=**378.67** ⇒ 表头**永远到不了视口顶** | ✅ **确认（并已量化）** |
| **C4** | ❌ 该轴一定不冻 | 未单测 | ⏳ **仍未实测** |
| **C5** | ⚠ 看起来失效（被固定头部盖住） | 未单测 | ⏳ **仍未实测** |
| **C6** | ✅ 不劫持（原报告标「未实测的低成本解药」） | V1 / P1 均**已吸附** | ✅ **确认**（代价见 7.6.5 ②） |
| **C7** | ✅ 一定生效 | V5 / P3′ 均**已吸附** | ✅ **确认** |
| **C8** | ✅ 仍然生效 | H1 / P5：computed `overflow-x = auto`，横向滚动 260 / 300 而首列不动 | ✅ **确认** |

**C2 被推翻后的准确表述**（替换原推断；`hidden` 与 `clip` 的分界正在这里）：

> `overflow: hidden` 的盒子**无论内部有没有溢出内容**，都**建立滚动盒并夺走 sticky 的参考系**；「有没有溢出」只决定它**能不能滚**，不决定它**是不是滚动盒**。
> 原报告 C2 的推断依据是 MDN `overflow` 那句「**When overflowing**, the element box is a scroll container」——**该句描述的是「没有滚动条时内容能不能滚」，不是「要不要建立滚动盒」**，据此推出的 C2 与浏览器行为不符。
> ⇒ 对门户当前状态的含义：`.table-responsive` 即使**装得下**（实测 `scrollH == clientH`）也**照样劫持**。**门户现状命中的是 C1/C2 形状，页面级 sticky 不生效。**

#### 7.6.5 原报告没写、实测才暴露的三件事

**① 劫持者的真身：`.card { overflow: hidden }` 压过了 `.table-responsive { overflow-x: auto }`**

从真实门户 CSSOM 逐条取（两条规则**同特异性**、同源 `web.assets_frontend.min.css`）：

| 选择器 | 声明 | 来源 |
|---|---|---|
| `.table-responsive` | `overflow-x: auto;` | Bootstrap |
| `.card` | `overflow: hidden;` | 同文件，**声明在后** |

wrapper 同时带 `table-responsive` 与 `card` 两个类 ⇒ 两条规则**同特异性**（都是单类选择器），**后者胜** ⇒ computed 变成 `hidden / hidden`。

**两条互相独立的证据**（不止是级联推断）：

1. **规则定位（CSSOM 匹配 + 源文件字节偏移）**：同一份 `web.assets_frontend.min.css`（1 205 230 字节）里 ——
   - `.table-responsive{overflow-x: auto; -webkit-overflow-scrolling: touch;}` 位于偏移 **70632**
   - `.card{overflow: hidden;}` 位于偏移 **653374**（**声明在后**；同特异性 ⇒ 胜出）
   （早前对该文件的字面量搜索曾漏掉这条，因为压缩后的规则块写法与预期不同；此处以「浏览器 CSSOM 报告该规则命中 wrapper」+「字节偏移」双证。）
2. **因果实验（真实门户上只改一个变量）**：把 wrapper 的 `card` 类去掉，其余不动，再读 computed ——

| wrapper 的 class | 变化 | computed overflow-x / -y |
|---|---|---|
| `table-responsive card shadow-sm border-0 rounded-3` | 原文 | **hidden / hidden** |
| `table-responsive shadow-sm border-0 rounded-3` | **去掉 `card`** | **auto / auto** |
| 还原为原文 | — | **hidden / hidden**（可复现） |

⇒ 去掉 `card` 后回到 Bootstrap 原意：`overflow-x: auto`；同时 `overflow-y` 也表现为 `auto` —— **这又一次在真实门户上印证了 §7.6.3(b) 的 C8 双值规则**。

即：**为卡片圆角裁剪而写的 `.card{overflow:hidden}`，顺手劫持了矩阵的 sticky 参考系**（属「附带伤害」，并非有意为之）。这是原报告没有的**根因级**发现。
**它同时给出一条比「全局改 `clip`」更安全的修法**：让 wrapper **别同时背 `card` 与 `table-responsive` 两个类**（或在该元素上显式覆盖 `overflow`），即可在不牺牲横向滚动的前提下把 `overflow-x: auto` 还回来。⚠ 但注意 —— **仅此一步仍不足以让页面级 sticky 生效**，因为 C3（短页面行程不足）还在（见本节 ③）。

**② `clip` 是解药，但有原报告未计及的代价：它把该盒的横向滚动能力一并废掉**

真实门户 + 把表加宽到 2200px（wrapper `clientW` 1178、`maxScrollLeft` 1022）：

| wrapper `overflow` | `scrollLeft` 0→300 是否成功 | 末列左边缘 | 后果 |
|---|---|---|---|
| `hidden`（现状） | **成功**（0 → 300） | 1487 | 宽表横向可达（程序可滚） |
| **`clip`** | **失败**（0 → 0） | **1787**（视口仅 1440） | **右半张表被裁掉且拿不到** |

⇒ 「把门户 `.table-responsive` 一律改成 `clip`」**不是无痛的**：`.table-responsive` 的存在意义就是给宽表留横向滚动，改 `clip` 会把它一并废掉。
**故建议比 §7.5 更强**：正路是 **C7（矩阵自己当滚动容器）**，而不是全局改 `clip`；`clip` 只在**确认该祖先不需要横向滚动**时才用。

**③ 短页面上「页面级 sticky」本来就没有行程（C3 已量化）**

门户真实页 `/assess/fill/2` 只有 **181px** 行程（doc `scrollHeight` 1081 − 视口 900），而矩阵顶在 y=378.67 ⇒ **即使把 ①② 两个问题都修掉，这些页面上页面级 sticky 也不会吸附**。
这不是 bug，是 §7.3 的 **C3**（行程不足）——⇒ **设计文档 §6.6 ①「矩阵必须自己成为滚动容器」的方向，实测后不仅正确，而且是唯一能同时绕开 C1/C2/C3 的做法。**

> 附带记录（供 §8 第 5 项「矩阵高度预算」参考，**未按各版式枚举**）：1440×900 下 `/assess/fill/2` 的 `.yy-assess-matrix` 文档顶 = **378.67px**，即矩阵以上的门户版式占了 378.67px。设计文档 §6.6 ① 的 `calc(100vh - 220px)` 与该值**不一致**，实施时应以实测为准（此处只给这一个版式的读数，不构成全局结论）。

#### 7.6.6 本节**仍未**实测的（不得当结论用）

| # | 项 | 为什么没测 |
|---|---|---|
| 1 | **C4**（只写一个轴）与 **C5**（固定定位头部遮挡） | 本次任务未要求，未单测 |
| 2 | **`border-collapse: collapse` 下 sticky 表头滚动中边框是否掉线**（原 §9 V-3） | 未测；本次全部测点都在 collapse 下做**位移**判定，**没做像素级边框检查** |
| 3 | **OCA 矩阵用 `border-right` 画冻结列分隔线是否被 collapse 吃掉**（原 §9 V-4） | 未测 |
| 4 | **交叉格 z-index 分层**（原 §9 V-5）与**多行表头 / colspan 偏移**（§7.4 第 3 步） | 未测；本次只给 `z-index` 写了值，**没有验证两轴同时冻结时谁盖谁** |
| 5 | **用户能否用手势/滚轮横向滚动 `overflow: hidden` 的盒子** | 只证明了**程序可滚**（`scrollLeft` 0→300 成功）。`hidden` 不显示滚动条，**真实滚轮/触控板手势未测** ⇒ 不写结论 |
| 6 | **Firefox / Safari** | 仅 Chromium 148（Blink）；`clip` 与 sticky 在别的引擎可能有别 |
| 7 | **生产环境** | 本次全部在**本地克隆** `edu19` 上做的；**未动生产** |


## 8. 「无先例、必须自研」的部分及理由

| # | 必须自研的东西 | 为什么无先例（具体到本仓） |
|---|---|---|
| 1 | **首列冻结与表头的 z-index 分层**（交叉格谁在上面） | Odoo 核心**只冻表头不冻首列**（§2.1）⇒ 核心没有"两轴同时冻结"的层级约定；OCA 矩阵有实现但**AGPL-3 不能装**（§5.1）。**可抄方法**（OCA 靠"交叉格是 `<th>` 恰好继承表头 z-index"），**不能抄代码** |
| 2 | **E7 的「粘贴后校验」语义** | o-spreadsheet 是**通用格子**，它只做"能不能放"（`isPasteAllowed` 返回 `Success/FrozenPaneOverlap/WillRemoveExistingMerge…`），**不做"这个分数对这个评分项合不合法"**。我们的矩阵要按 `edu.assess.item` 的**满分/刻度/档位**逐格校验，并区分「不写入 / 标红 / 计数提示」——**没有任何先例做过这一层**（Moodle/Canvas 的校验发生在**文件导入的服务端**，不是粘贴的逐格） |
| 3 | **粘贴块的「行↔学生」「列↔评分项」对齐规则** | Excel/表格控件的块粘贴只是**位置对齐**（左上角格 + 行列偏移）。我们要处理**语义对齐**（源块里的姓名列要不要丢、学号顺序与名单不一致怎么办、名单缺人怎么办）——**同类系统无先例**（它们没有"行=学生"的网格） |
| 4 | **平铺 vs 截断的取舍（在评估场景下）** | o-spreadsheet 默认**平铺**（`getPasteZones`/`splitZoneForPaste`），Handsontable 用 `pasteMode` 三枚举。**"一列同分铺满整列"这个评估场景的具体规则（源 1 列可铺、源多列溢出即拒）需要我们自己定**——先例只给了"可以铺"这个事实（§3.3） |
| 5 | **矩阵作为滚动容器时与门户版式的高度预算** | 设计文档 §6.6 ① 写的 `max-height: calc(100vh - 220px)` 是**经验值**。Odoo 用 `.o_content{height:100%}` 的 flex 布局**避免硬编码**（§2.2），OCA 用硬编码 `450px`（§5.1）。**我们的门户头部高度只有实测才知道** ⇒ 数值必须实测得出（§9） |
| 6 | **【附】若将来做「冻结上层表头行 + 多列冻结」** | 那需要**逐列算 `left` 偏移 + 补偿滚动条宽度**（DataTables `FixedColumns.ts:411-441` 的完整做法），**并**给 colspan 表头加 JS 偏移（Moodle `stickycolspan.js`）。**本期不做**（设计文档 §6.6 ④ 已取舍），但这两份先例记在这里供将来用 |

> ⚠ **本报告不认定「无先例」的部分**：粘贴内核、sticky 表头、首列 sticky 的 CSS 形状、locale 数值归一 —— **这四件都有先例**（§2/§3/§5.1/§6），**按铁律 0 应"抄"不应"造"**。
> **特别提示**：本报告**没有把 o-spreadsheet 的代码当成可复制对象** —— 它是 **LGPL-3**，直接 copy 代码进我们模块会引入 LGPL 义务；**抄的是"方法与顺序"，不是代码文本**。同理 OCA 矩阵是 **AGPL-3**。

## 9. 未验证 / 查不到的项（含**具体原因**；**不得当结论使用**）

### 9.1 本报告自己**没有测**的（我有能力测但没测，如实标注）

> **2026-09-30 更新**：**V-1 / V-2 已由后续会话用 Playwright 实测闭环**（见 **§7.6**）——其中**有一处与原始判定冲突：C2 被推翻**。其余各项**仍未验证**。

| # | 未验证项 | 为什么没验 / 需要怎么验 |
|---|---|---|
| V-1 | **本仓门户页里，矩阵到视口之间到底有哪些祖先带 `overflow`** | 需要**真实浏览器 + 已登录门户**。本报告全程只用 curl / 文件系统，**无浏览器实测能力**。验证脚本见 §7.4 第 1 步（3 行控制台代码）。**→ 2026-09-30 已实测闭环，见 §7.6.2**：全链路只有 `.table-responsive` 一个非 `visible` 祖先，且它**无溢出内容**（`scrollH == clientH`），**却仍劫持参考系** |
| V-2 | **`overflow: clip` 替代 `hidden` 后 sticky 是否恢复**（§7.2 提的"低成本解法"） | 同上，需浏览器实测。**规范支持这个推断（MDN 原句：`clip` 不是滚动盒子），但推断 ≠ 实测**。**→ 2026-09-30 已实测闭环，见 §7.6.3(a) / §7.6.5②**：改 `clip` 后**确实恢复吸附**（合成页与真实门户都验到），**但会把该盒的横向滚动能力一并废掉**（`scrollLeft` 0→0，宽表右侧不可达） |
| V-3 | **Odoo 19 列表视图粘性表头在滚动中边框是否掉线**（`border-collapse: collapse` 下） | 需浏览器。Odoo 用 `background-clip: padding-box` 修 Firefox 边框（`list_renderer.scss:30-32` 原注释），但**没有注释说它修的是 sticky 场景** |
| V-4 | **OCA 矩阵用 `border-right` 而非 box-shadow 画冻结列分隔线，是否会被 collapse 吃掉** | 需浏览器。§5.1 已标"未验证" |
| V-5 | **交叉格 z-index 用 OCA 那种"靠 `<th>` 继承表头 z-index"的做法，在我们表里是否成立** | 需浏览器。我们的矩阵第一行是 `<th>`，结构相同，但**列数/是否有 `rowspan` 不确定** |
| V-6 | **`max-height: calc(100vh - Npx)` 里的 N 应该是多少** | 需实测门户头部高度（§8 第 5 条） |
| V-7 | **WPS / 腾讯文档 / Google Sheets 复制的 HTML 里是否含 `microsoft` 字样** | o-spreadsheet 的判别是 `attr.value.includes("microsoft")`，只对 MS Office 生效。**没测过国产办公软件**；因此 §3.3 建议"不依赖白名单，html 解析失败一律回退 text/plain" |

### 9.2 外部信息**取不到**的（含具体原因）

| # | 查不到的东西 | 具体原因（不是"没查"，是"查不动"） |
|---|---|---|
| V-8 | **`flexible_table::column_sticky()` 是哪个 Moodle 版本引入的** | 我用的是 **`--depth 1` 的 blobless 浅克隆**（`/tmp/moodle`），**没有历史**，`git log` 无用。且想对照 `MOODLE_500_STABLE` 分支时**只取了 `main` 的 tree**，`ls-tree MOODLE_500_STABLE` 返回空（未 fetch 该分支）。**另注：Moodle `main` 已把 `lib/tablelib.php` 迁到 `public/lib/tablelib.php` + `public/lib/table/classes/flexible_table.php`**，老路径 `lib/tablelib.php` 在 main 上**编译期就已不存在**（我第一次 curl 得 14 字节的 `404: Not Found`） |
| V-9 | **DataTables FixedHeader（粘性表头扩展）的源码实现** | 本轮只取证了 **FixedColumns**（`DataTables/FixedColumns` blobless clone）。**FixedHeader 是另一个仓库 `DataTables/FixedHeader`，未取**。⇒ §6.1 关于"粘性表头"的结论只来自**官方那句话**与 Odoo/OCA/Moodle，**不来自 FixedHeader 源码** |
| V-10 | **Handsontable 的价格与"免费 license"的具体边界** | `https://handsontable.com/license` → **HTTP 404**（我试了）。`/docs/license-key/` 只有「Commercial and Free licenses, depending on your usage」+ 必须传 `licenseKey`，**没有价目与边界条款**。⇒ **不重复** `evaluation-rebuild.md` 已记的「7.0.0 起非开源、$999/开发者起」 |
| V-11 | **飞书 / 企业微信 / 校管家 / 学邦 / 希沃 的冻结与粘贴功能名** | **飞书**：`www.feishu.cn/hc/zh-CN/articles/<id>` **实测 HTTP 200 且正文可读**（我抓到一篇"文件上传、在线预览的大小及格式要求"），**但我没有该站的检索接口，猜的 article id 全是别的文章** ⇒ 需要正确 id 才能取证。**企业微信 / 校管家 / 学邦 / 希沃**：本轮**未发起请求**（把时间投在了 Odoo/Moodle/Canvas 的源码取证上）；且 `web_search` 工具全程故障（见 §10），**没有"搜一下再点进去"这条路径** |
| V-12 | **钉钉 AI 表格是否支持剪贴板整块粘贴** | 只取了 `ai-table.md` 索引页 + `fields/add-field.md`。索引里**有 144 篇**，我只 grep 了索引摘要，「paste」在索引摘要里**0 命中**，但**这不等于正文没有** ⇒ 标未验证。**注意**：索引里有一篇 "Keyboard Shortcuts … **multi-cell selection**"，暗示它有多格选中的键盘操作，**可能**支持复制粘贴 —— **未验证** |
| V-13 | **企业微信 / 飞书是否也有"冻结到此列"这种产品模型** | 未验证（原因同 V-11） |
| V-14 | **`spreadsheet_oca` 在 Odoo 19 上实际是否可用**（是否能新建/编辑/保存 spreadsheet） | **只读了 README 与文件树**，**没有安装、没有跑**。README 自陈"adds functionality for adding and editing Spreadsheets using Odoo CE"，但 maturity 标 **Beta** |
| V-15 | **社区版 `spreadsheet_dashboard` 实际能显示什么** | 只确认了「LGPL-3 + 在官方 `odoo:19` 镜像里 + 只读 `public_readonly.js:58`」，**没有启动 Odoo 实际点开看** |
| V-16 | **上游 `github.com/odoo/o-spreadsheet` 的 Apache/LGPL 与版本号** | `git ls-remote --heads` **成功返回**（分支含 `14.0`/`15.0`），**但我只列了前 5 个分支就截断了**，**没有确认是否存在与 Odoo 19 对应的分支，也没有取它的 LICENSE 文件** |
| V-17 | **把 Odoo 社区版 `spreadsheet` 传 `mode:"normal"` 的可行性/合法性** | **纯法律 + 商业条款问题，本报告不作判断**，只陈述机制（§4.2）。**必须法务确认**。我**没有尝试**（也**不应**尝试）绕过 OEEL-1 边界 |

### 9.3 需要**法务确认**的清单（按本课题要求：AGPL-3 的传染性一律标注）

| 项 | license | 结论 |
|---|---|---|
| `web_widget_x2many_2d_matrix`（OCA/web@19.0） | **AGPL-3** | **需法务确认**。本报告**只抄它的 SCSS 方法（20 行思路）**，不 copy 代码、不装模块 |
| `spreadsheet_oca` / `spreadsheet_dashboard_oca` / `spreadsheet_dashboard_purchase*_oca`（OCA/spreadsheet@19.0） | **AGPL-3** | **需法务确认**（尤其 `spreadsheet_oca` 是"可编辑"的那一个） |
| `web_dark_mode` / `web_group_expand` / `web_quick_start_screen` / `web_timeline` / `web_m2x_options` 等 24 个 OCA/web 模块 | **AGPL-3** | **需法务确认**（与本课题无关，但本次扫描把它们一并核了 license） |
| `web_responsive` / `web_remember_tree_column_width` / `web_bell` 等 | **LGPL-3** | ✅ 无传染性问题（LGPL-3 对本仓 `edu_*` 模块是安全的） |
| Odoo 19 社区版 `spreadsheet` 模块内的 o-spreadsheet 库 | **LGPL-3** | 代码不可直接 copy；**抄方法与顺序** |
| Moodle 源码（`column_sticky`/`grade.scss`/`stickycolspan.js`） | **GPL-3.0-or-later**（文件头原文 "GNU GPL v3 or later"） | ⚠ **GPL 同样有传染性**，且比 LGPL 更强 ⇒ **只抄方法，不 copy 代码**。**本报告未把它的 license 列入"可装"，因为它是 PHP 应用不是 Odoo 模块** |
| Canvas 源码（`GradebookGrid/*`、`packages/slickgrid`） | **AGPL-3.0**（Canvas 整体为 AGPL-3） | ⚠ **需法务确认**；**只抄方法** |
| DataTables FixedColumns | **MIT** | ✅ 无问题（本报告只引其文档与源码事实，未 copy 代码） |

## 10. 调研过程记录（可复现命令、试过并排除的路径、工具故障）

### 10.1 取证环境（本机事实）

```bash
# Odoo 19 社区版：跑在 docker 里
docker ps --format "{{.Names}}\t{{.Image}}"        # edu19-clone-web-1  odoo:19
docker exec edu19-clone-web-1 sh -c 'ls /usr/lib/python3/dist-packages/odoo/addons/ | grep -i spreadsheet'
# → spreadsheet, spreadsheet_account, spreadsheet_dashboard, spreadsheet_dashboard_*（14 个）、test_spreadsheet
# Odoo 19.0 FINAL 全量源码（社区+企业，1467 模块），仓库外只读参考：
E="$HOME/Documents/文件大总管/30-资源/odoo源代码企业版/odoo"
ls "$E/addons" | wc -l            # 1467
grep -n "version_info" "$E/odoo-src/odoo/release.py"   # (19, 0, 0, FINAL, 0, '')
```

⚠ **两个不同 build 的差异（重要）**：`odoo:19` 容器里的 `o_spreadsheet.js` 是 **78763 行**，本地企业版全量源码里是 **78699 行** ⇒ **同一 19.0 下两份文件的 `isReadonly` 行号不同**。本报告**行号一律以本地 19.0 FINAL 源码为准**，并按 README §4 警告注明"实施时以本机实测为准"。

### 10.2 逐项取证的命令（可直接重跑）

```bash
# ---- M1：Odoo 列表视图的 sticky ----
E="$HOME/Documents/文件大总管/30-资源/odoo源代码企业版/odoo"
grep -rn --include=*.scss --include=*.js "sticky" "$E/addons/web/static/src/" | head -60
sed -n '1,80p' "$E/addons/web/static/src/views/list/list_renderer.scss"     # 14-24 行 = sticky 表头
cat "$E/addons/web/static/src/webclient/webclient_layout.scss"              # .o_content{overflow:auto} = 唯一滚动容器
grep -rn -i "frozen\|freeze" "$E/addons/" --include=*.js --include=*.scss | grep -v lib/   # 0 个"冻结列"

# ---- M2：Odoo 的粘贴 ----
grep -rn -i "onpaste\|handlePaste\|addEventListener(\"paste\"" "$E/addons/web/static/src/views/" --include=*.js
# → 只命中 views/fields/input_field_hook.js:54（换行拦截）
grep -rn -i "paste\|clipboard" "$E/addons/product_matrix/static/src/"      # → 0 命中（官方矩阵组件也不支持）

# ---- o-spreadsheet 的剪贴板与冻结 ----
F="$E/addons/spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js"
grep -n -i "clipboard" "$F" | head -60                                      # → 204 处
sed -n '6292,6315p' "$F"      # parseOSClipboardContent + getOSheetDataFromHTML（microsoft 判别）
sed -n '8042,8064p' "$F"      # convertTextToClipboardData（
 / 	 切分 + canonicalizeNumberValue）
sed -n '8526,8534p' "$F"      # FrozenPaneOverlap（跨冻结线粘贴被拒）
sed -n '39245,39305p' "$F"    # Freeze / Freeze first row / first column 菜单（均 isReadonlyAllowed: true）
grep -n "isReadonly\|exportXLSX\|XlsxReader" "$F" | head                  # 78085 / 78224 / 78442 / 37583 / 38106
grep -rn "license" "$E/addons/spreadsheet/__manifest__.py"                  # LGPL-3
grep -rn "spreadsheet/xlsx" "$E/addons/" --include=*.py                      # → 只在 spreadsheet_edition（OEEL-1）

# ---- OCA（不依赖任何 API，全走 codeload tarball） ----
mkdir -p /tmp/oca && cd /tmp/oca
git ls-remote --heads https://github.com/OCA/web | grep 19.0
curl -sL -o web-19.0.tar.gz https://codeload.github.com/OCA/web/tar.gz/refs/heads/19.0
tar xzf web-19.0.tar.gz
grep -rn "position: *sticky" web-19.0 --include=*.scss --exclude-dir=lib   # → 5 处
grep -rn -iE "addEventListener\(.paste|onpaste|handlePaste" web-19.0 --include=*.js --exclude-dir=lib  # → 0
cat web-19.0/web_widget_x2many_2d_matrix/static/src/components/x2many_2d_matrix_field/x2many_2d_matrix_field.scss

# ---- Moodle（blobless + sparse，避开通读） ----
git clone --filter=blob:none --depth 1 --sparse https://github.com/moodle/moodle /tmp/moodle
git -C /tmp/moodle ls-tree -r HEAD --name-only | grep -i tablelib
# → public/lib/tablelib.php（薄壳）+ public/lib/table/classes/flexible_table.php（真正的类）
git -C /tmp/moodle show HEAD:public/lib/table/classes/flexible_table.php > /tmp/ft.php
grep -n -i "sticky" /tmp/ft.php        # → :108 columnsticky / :421 column_sticky() / :423 ' sticky-column'
git -C /tmp/moodle show HEAD:public/theme/boost/scss/moodle/tables.scss | sed -n '15,21p'
git -C /tmp/moodle show HEAD:public/theme/boost/scss/moodle/grade.scss  | sed -n '560,610p'
git -C /tmp/moodle show HEAD:public/grade/report/grader/amd/src/stickycolspan.js | head -80

# ---- Canvas（同法） ----
git clone --filter=blob:none --depth 1 --sparse https://github.com/instructure/canvas-lms /tmp/canvas
cd /tmp/canvas && git sparse-checkout set ui/features/gradebook
find ui/features/gradebook -type f | wc -l          # 404
grep -rn -i "paste"     ui/features/gradebook       # 0
grep -rn -i "clipboard" ui/features/gradebook       # 0
grep -rn -i "frozen"    ui/features/gradebook | head
git show HEAD:packages/slickgrid/slick.grid.js | grep -n "numberOfColumnsToFreeze" | head

# ---- 通用库 ----
curl https://datatables.net/extensions/fixedcolumns/           # 官方切分原句
git clone --filter=blob:none --depth 1 https://github.com/DataTables/FixedColumns /tmp/fc
git -C /tmp/fc show HEAD:src/FixedColumns.ts | sed -n '405,445p'   # position:sticky + 逐列 offset
curl https://handsontable.com/docs/api/options/ | grep pasteMode   # 三枚举
# ---- 规范 ----
curl https://drafts.csswg.org/css-position-3/     # §3.4 sticky 原文
curl https://developer.mozilla.org/en-US/docs/Web/CSS/position    # "even if that ancestor isn't the nearest actually scrolling ancestor"
curl https://developer.mozilla.org/en-US/docs/Web/CSS/overflow    # hidden/auto/clip 与双值语法
# ---- 国内 ----
curl https://help.dingtalk.io/llms.txt
curl https://help.dingtalk.io/aitable/fields/add-field.md
curl "https://docs.aliwork.com/docs/yida_support/wtwabe/up3ftx/in0w72"   # HTTP 200，正文可读
```

### 10.3 试过并**排除掉**的路径（别重走）

| 路径 | 结果 | 处置 |
|---|---|---|
| `raw.githubusercontent.com/moodle/moodle/main/lib/tablelib.php` | **404**（14 字节） | Moodle `main` 已把源码移到 **`public/` 前缀**，且 `lib/tablelib.php` 变成薄壳，真正的类在 `public/lib/table/classes/flexible_table.php` |
| `raw.githubusercontent.com/DataTables/FixedColumns/master/js/dataTables.fixedColumns.js` | **404** | 该仓库已迁到 **TypeScript**：`src/FixedColumns.ts`（`js/` 目录不存在） |
| `handsontable.com/license` | **HTTP 404**（30 KB 的 404 页） | 改用 `/docs/license-key/`（HTTP 200） |
| `handsontable.com/docs/copy-paste/` | **HTTP 404** | `copyPaste` 的权威来源是 `/docs/api/options/#copypaste`（HTTP 200） |
| `drafts.csswg.org/css-overflow-3/` | **curl 返回 0 字节**（原因不明：疑似被截断/拒绝，未确认） | 改用 **MDN `overflow`** 作为一手来源；Position 3 的规范页**抓取成功**（436 KB） |
| `api.github.com` 检索 OCA/Canvas 仓库内容 | **未认证额度耗尽**（任务书已告知） | 全部改用 **`git ls-remote` + `codeload` tarball + `--filter=blob:none` 克隆**，**不依赖任何 API** |
| `web_search` 工具 | **全程 HTTP 400 insufficient credits**（任务书已告知） | 全部改用 **`curl` + `web_fetch` + 手工猜 URL/用 `llms.txt` 索引** |
| 在 blobless 克隆上跑 `git grep <pattern> HEAD` 全仓 | **极慢并两次撞 120 s 执行上限**（会按需拉取大量 blob） | 改为「`ls-tree` 找路径 → `git show HEAD:<path>` 逐个取 → 本地 `grep`」；或先 `sparse-checkout` 落地再本地 grep |
| Canvas 的整块粘贴：直接猜文件名 | 失败 | 改为 **`sparse-checkout` 落地整个 `ui/features/gradebook`（404 文件）后本地 grep** ⇒ 得到**可复现的 0 命中** |
| 钉钉 AI 表格文档循环抓 3 个页面 | 第 2/3 次 **返回与第 1 次完全相同的 14025 字节**（疑似 404 回落或 curl 未覆盖旧文件） | **按"未验证"处理**，不据此下任何结论 |
| 飞书帮助中心：猜 article id | 抓到的是**另一篇文章**（HTTP 200 但内容不对） | 标 **V-11 未验证**（无检索路径） |

### 10.4 本会话遇到的**工具能力限制**（留给下一个人）

1. **`subagent` 不可用**：尝试并行派两个子代理做"同类系统"与"通用库"调研，被拒：`ToolCallError: subagent depth 2 exceeds maxDepth 1`。⇒ **我是被派出来的子代理，不能再派子代理**；本报告的全部取证**在单线程内完成**，这也是国内部分只做了一半的原因。
2. **`run_code` 的程序体对模板字面量里的反引号敏感**：本文档含大量 Markdown 反引号，直接用模板字符串写会触发 TS 解析错误（`Expected ',', got ';'` / `Expression expected`）。**改用占位符替换法**（先写 `§§`，再 `.split('§§').join(String.fromCharCode(96))`）才写进去 —— **下一个人写含代码的文档时会遇到同一个坑**。
3. **无法做浏览器实测**：本环境只有 `curl`/文件系统/docker exec，**没有无头浏览器**（`tabbit` 技能存在但本任务未使用/未验证可用）。§9 的 V-1~V-6 因此全部无法闭环。 **→ 2026-09-30 补**：后续会话已具备浏览器能力（`/opt/homebrew/bin/python3` + Playwright + Chromium 148.0.7778.96），**V-1 / V-2 已闭环**（见 §7.6）；**V-3~V-6 仍未闭环**。
4. **`bash` 单次执行 120 s 上限**：blobless 克隆 + `git grep` 的组合会超时；长任务应改用 `run_in_background: true`（本次 OCA/Canvas/Moodle 的下载都这么做的）。

### 10.5 本次**未展开**、建议后续补的

1. **DataTables FixedHeader 源码**（V-9）。
2. **Moodle `column_sticky` 的引入版本**（V-8）—— 决定本仓能否把它当"同类系统已有能力"引用。
3. **国内 5 家产品的功能名+URL**（V-11/V-12/V-13）—— 需要能"搜索"的工具或正确 id。
4. **浏览器实测**（V-1~V-6）—— 这是把 §7 的判据变成**已验证结论**的**唯一**办法。
