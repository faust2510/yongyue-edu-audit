# 后台导航栏「一个条目」的原厂惯例（Odoo 19 源码级取证）

> 起因：v4-t8 要修 `apps_panel_chip.js` 往 `.o_main_navbar` 里注入的「应用面板」入口。
> 它原先是一个**内联样式写死 `background:#714B67` 的紫色胶囊**，hover/active 全无反馈。
> 铁律 0：先读原厂怎么写导航栏条目，再决定我们的形 —— 不凭喜好发明新胶囊。
>
> 日期：2026-09-28 ｜ 取证环境：本机容器 `edu19-clone-web-1`（image `odoo:19`，Odoo 19.0-20260817）

## 0. 怎么复现（全部命令可直接粘贴）

```bash
docker compose exec -T web bash -lc 'cat /usr/lib/python3/dist-packages/odoo/addons/web/static/src/webclient/navbar/navbar.variables.scss'
docker compose exec -T web bash -lc 'cat /usr/lib/python3/dist-packages/odoo/addons/web/static/src/webclient/navbar/navbar.scss'
docker compose exec -T web bash -lc 'cat /usr/lib/python3/dist-packages/odoo/addons/web/static/src/webclient/navbar/navbar.xml'
# 「谁在扩展这些自定义属性」——三个核心模块
docker compose exec -T web bash -lc "grep -rn 'NavBar-entry' /usr/lib/python3/dist-packages/odoo/addons/ --include='*.scss' | grep -v 'webclient/navbar'"
```

⚠ **行号会漂移**：下面引的行号取自本机镜像里的那份快照（不是上游 git 分支的某个 commit，
本机没有该 git 元数据可核）。本仓纪律：实施时以本机实测为准。

## 1. 结论：原厂条目 = 透明块 + 半透明黑叠层，四态全走 CSS 变量

| 维度 | 原厂做法 | 出处（镜像内路径） |
|---|---|---|
| 定位 | `position: relative; display: flex; align-items: center` | `navbar.variables.scss` 的 `%-main-navbar-entry-base` |
| 高度 | `height: calc(var(--o-navbar-height) - 0px)` = **46px**（`--o-navbar-height` 由 `@include print-variable` 打在 `.o_main_navbar` 上，子元素继承） | 同上 + `navbar.scss:5` |
| 圆角 | `border-radius: $o-navbar-entry-border-radius` = **0**（原厂条目没有圆角） | `navbar.variables.scss` |
| 底色 | **`background-color: inherit`** —— 条目**没有自己的背景色**，继承导航栏底色 | `%-main-navbar-entry-base` |
| 水平内边距 | `padding-left/right: var(--NavBar-entry-padding-*, .63em)` | `%-main-navbar-entry-spacing` |
| 字色 | `color: var(--NavBar-entry-color, rgba(255,255,255,.9))`，hover/focus → `var(--NavBar-entry-color--hover, #fff)` | `%-main-navbar-entry-base` + `@mixin o-hover-text-color`（`web/static/src/scss/utils.scss:173-179`） |
| hover / focus 底色 | `var(--NavBar-entry-backgroundColor--hover, rgba($o-black, .08))` —— **8% 半透明黑叠层** | `navbar.scss` 的 `.o_menu_sections .o_nav_entry, .dropdown-toggle` 块 |
| active 底色 | `var(--NavBar-entry-backgroundColor--active, …)`，原厂值与 hover **同值**（`$o-navbar-entry-bg--active: $o-navbar-entry-bg--hover !default`） | `navbar.variables.scss` + `navbar.scss` |
| 展开态（下拉已打开） | 另加 `border-color: var(--NavBar-entry-borderColor-active, transparent)` | `navbar.scss` 的 `.dropdown.show.dropdown-toggle` |
| 预留边框 | 条目统一 `border: $border-width solid transparent` —— 边框位**先占住**，只在特定态上色 | `navbar.scss`；实测 `button.o-dropdown.dropdown-toggle` 计算值 `border: 2px transparent`、`border-radius: 0` |

实测（本机 /odoo/contacts，1440×900）原厂条目几何：`.o_navbar_apps_menu .dropdown-toggle`
→ `height: 46px`、`border-radius: 0`、`background-color: rgba(0,0,0,0)`、`color: rgba(255,255,255,.9)`。

## 2. 「态」的着手点 = `--NavBar-entry-*` 自定义属性（原厂留下的扩展缝）

原厂把条目的每个视觉旋钮都暴露成了自定义属性，**核心模块自己就是从这些缝里扩展的**：

| 扩展者 | 改了什么 | 文件 |
|---|---|---|
| website | `--NavBar-entry-padding-left/right`、`--border-color` | `website/static/src/components/navbar/navbar.scss:1-13` |
| mail | `--NavBar-entry-backgroundColor`（讨论界面整体换底） | `mail/static/src/core/public_web/discuss.dark.scss:3` |
| web（user_menu） | `--NavBar-entry-padding-right` | `web/static/src/webclient/user_menu/user_menu.scss:2` |

⇒ **我们的入口要三态齐全，正确做法是吃这几个变量**，而不是给元素配一套自创配色。

## 3. 「可辨识的形」有没有原厂先例？

- **导航栏条目里没有**：`.o_menu_toggle` / `.o_menu_brand` / `.o_nav_entry` / `.o_navbar_apps_menu .dropdown-toggle` / systray 各项
  **全部**是 `background-color: inherit`（即"透明"），没有任何一个是自带底色的胶囊。
  ⚠ 唯一看着像"有底色"的写法是 `.o_menu_sections .o_nav_entry{background: var(--NavBar-entry-backgroundColor, $o-navbar-background)}`
  —— 它的默认值**就是导航栏自己的底色**，视觉上等于透明，只是为了让 hover/active 有可覆盖的基值。
- **唯一"填充块"先例在 website 的 systray**（不是后台导航栏）：
  `edit_website_systray_item.xml` 用 `class="o-website-btn-custo-primary btn d-flex align-items-center rounded-0 border-0 px-3"`，
  `new_content_systray_item.xml` 同样 `btn rounded-0 border-0 px-3`。
  ⇒ 即便是"显眼的主行动按钮"，原厂也**压成直角、去掉边框**，长在导航栏高度里。这反过来说明"圆角胶囊"不是这套 UI 的词汇。
- **分隔线的先例**：`.o_website_systray .o_user_menu{border-right:1px solid var(--border-color)}`，
  而 `--border-color: darken($primary, 10%)`（`website/.../navbar.scss:5`）——
  即**"导航栏底色的加深档"**。本仓已经有同角色的令牌：`backend_variables.scss:52` 把导航栏下边框设为 `$brand-action-hover`。
- **.o_main_navbar 下的原厂"应用面板入口"**恰好就是左边那个 `.o_navbar_apps_menu .dropdown-toggle`（`title="Home Menu"`，图标 `oi oi-apps`）
  —— 透明、直角、全高，hover 才出现 8% 黑叠层。**我们的入口与它同职能**，形就该是同一套。

## 4. ⚠ 一处**不能照样抄**的地方：字色档

原厂条目字色是 `rgba($o-white, .9)`。它在**原厂紫**底上是合格的，在我们的**品牌蓝**底上不是：

| 前景 | 背景 | 对比度 | 判定 |
|---|---|---|---|
| `rgba(255,255,255,.9)` | `#71639E`（原厂社区版紫，原厂导航栏底色） | **4.635** | ✓（原厂就这么定的） |
| `rgba(255,255,255,.9)` | **`#0C6DD7`（本仓 `--brand-action` = 我们的导航栏底色）** | **4.372** | **✗ 低于 AA 4.5** |
| `#FFFFFF`（不透明白） | `#0C6DD7` | **5.019** | ✓ |

⇒ 抄结构可以，**这一档必须换成本仓令牌 `--white`**。复算（本仓已用同一算法核对过其它档）：

```bash
python3 - <<'PY'
def f(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
def L(p): return 0.2126*f(p[0]) + 0.7152*f(p[1]) + 0.0722*f(p[2])
def cr(a, b):
    la, lb = L(a), L(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
def over(fg, a, bg): return tuple(fg[i]*a + bg[i]*(1-a) for i in range(3))
BA, W = (12, 109, 215), (255, 255, 255)
print('opaque white    ', round(cr(W, BA), 3))
print('white .9        ', round(cr(over(W, .9, BA), BA), 3))
print('black .08 wash  ', round(cr(W, over((0, 0, 0), .08, BA)), 3))
print('black .16 press ', round(cr(W, over((0, 0, 0), .16, BA)), 3))
print('rest white .08 (不采用)', round(cr(W, over(W, .08, BA)), 3))
PY
```

**顺带的负结论**：我们**不做**"常驻白底薄层"那种招牌式胶囊 —— 白色薄层会把白字自己压暗，
α≥0.08 就掉到 **4.381 ✗**（α=.05 才 4.612，余量只有 0.11，任何舍入都会翻面）。
这正好也是"别自创胶囊"的算术理由。

## 5. 本仓落点（结论 → 代码）

| 项 | 采用 | 理由 |
|---|---|---|
| 几何 | `height: calc(var(--o-navbar-height) - 0px)`、`border-radius: 0`、`padding: 0 .63em`、`margin: 0`、`background-color: inherit`、`font-size: 1em`、`line-height: var(--o-navbar-height)` | §1 逐条复刻 `%-main-navbar-entry-base` / `%-main-navbar-entry-spacing` |
| 常驻字色 | `var(--white)` | §4：原厂 `.9` 在我们蓝底上 4.372 ✗ |
| hover / focus | `var(--NavBar-entry-backgroundColor--hover, rgba(var(--black-rgb), .08))` + 白字 | §2：吃原厂变量，原厂机制 |
| active | `var(--NavBar-entry-backgroundColor--active, rgba(var(--black-rgb), .16))` | 原厂 `--active` 与 `--hover` 同值，是因为条目的 active 主要指"下拉已展开"、那里另有 `--NavBar-entry-borderColor-active` 一起变；我们这个入口**没有下拉**，按下时只有底色能反馈 ⇒ 用**同一个变量**、取同族叠层的加倍档 |
| 左分隔线 | `border-left-color: var(--brand-action-hover)` | §3：原厂分隔线 = `darken(导航栏底色, 10%)`；本仓已把该角色指派给 `--brand-action-hover`（`backend_variables.scss:52`）。刻意是**弱线**（1.140），与导航栏自己的下边框同强度 |
| 焦点环 | `outline: 2px solid var(--white); outline-offset: -2px` | 本文件原有的 `.o_main_navbar :focus-visible` 口径；白环压 `--brand-action` = 5.019 ✓（非文本 3:1 判据） |

三态白字对比实算：常驻 **5.019** ｜ hover **5.735** ｜ active **6.578**，全部 ≥ 4.5。

### 改前 / 改后的真机读数（/odoo/contacts）

| 项 | 改前（内联紫胶囊） | 改后（原厂条目形） |
|---|---|---|
| 元素 inline style | `…background:#714B67;color:#fff;border-radius:14px;font-size:12px` | **无**（`null`） |
| 计算底色 | `rgb(113, 75, 103)`（`#714B67`） | `rgb(12, 109, 215)`（= `--brand-action`，与导航栏同色） |
| 圆角 | `14px` | `0px` |
| 高度 / 内边距 / 字号 | 45px / 10px / 12px | **46px** / 8.82px(= .63em×14px) / **14px** |
| hover | **无任何变化**（底色、字色与常驻态逐字相同） | 底色 → `rgba(0, 0, 0, 0.08)` |
| focus-visible | 白内环（来自本文件通用规则） | 白内环（显式再写一份，防通用规则被挪走） |
| 该页计算底色 = `rgb(113,75,103)` 的可见元素数 | **1** | **0** |

## 6. 未验证 / 待确认

1. **行号漂移**：本文行号取自本机镜像里的 `odoo:19`（19.0-20260817）快照，
   **未**与上游 git 分支的某个 commit 对照（本机无该 git 元数据）。引用时请带镜像版本。
2. **移动端（`ui.isSmall`）**：窄屏下原厂导航栏会切成 `.o_app_menu_sidebar`，
   我们注入的条目**仍然是 `.o_main_navbar` 的直接子元素**。本轮**没有**在窄屏实测其表现
   （未验证：是否会与 `.o_menu_toggle` 抢位、是否需要 `d-none d-md-flex`）。
3. **暗色后台**：本仓无暗色后台主题，`--NavBar-entry-*` 在暗色下的原厂取值未查。
4. **`--o-navbar-height` 的兜底**：本实现不带后备值（与原厂一致，依赖它由 `.o_main_navbar` 打印）。
   若将来有页面把该条目挪出 `.o_main_navbar`，`height` / `line-height` 会退化成 `auto`（未验证实际后果）。
5. **跨驱动取色对照**：本轮 `tabbit-cli` 报 `BROWSER_RUNTIME_UNAVAILABLE`（ENV），
   真机读数由 Playwright 驱动取得（测量代码同一份，见 `tests/color/capture_playwright.py`）；
   **"两个驱动读数逐色相等"未做对照**，故该读数只用于绝对判据。
