# 教师门户「我的主页 × 应用面板」合并 —— 外部先例调研（铁律 0）

> 调研日期：**2026-10-03** ｜ 触发：用户原话「我希望老师的我的主页和应用面板功能可以合并，不要分开了」
> 方法：**读源码**（Odoo 19 核心在本地 docker 容器 edu19-clone-web-1 里；Moodle/Canvas 走 GitHub 官方仓库源码）+ OCA 官方仓库 + 官方帮助中心页面。检索工具逐条记录在 §7。
> 环境：本机 docker exec edu19-clone-web-1 odoo --version = **Odoo Server 19.0-20260817**；GitHub 经 gh api（raw.githubusercontent.com 与搜索引擎在本机不可达，见 §7）。

## 0. 要回答的问题

本仓教师登录后有 **3 个「首页式」入口**：/my/home（教师工作台仪表盘）、/my/apps（门户功能宫格）、/apps（后台应用启动器，侧栏标签「应用面板」）。
要做的是**合并成一个入口**，且原来所有功能仍可达。设计上真正需要外部先例回答的是：

1. 成熟产品里「仪表盘」与「应用/功能总览」是**两个并列的页面**，还是**一个页面内的两块**（或一个浮层）？
2. 应用启动器的惯例形态：独立页 / 导航栏浮层 / 侧滑抽屉？
3. 有没有哪个主流产品把「我的主页」和「应用面板」做成两个并列入口？

## 1. 结论速览

| # | 结论 | 一手来源 |
|---|---|---|
| 1 | **Odoo 19 自己把「应用菜单」做成导航栏下拉/侧滑浮层，不是第二个首页页**：桌面端是导航栏按钮（标题 Home Menu，hotkey h）+ Dropdown 列出全部应用；移动端是 o_app_menu_sidebar 侧滑，里面一个「All Apps」按钮切换应用列表。 | Odoo 19 源码，见 §2 |
| 2 | Odoo 19 **没有**「仪表盘一页 + 应用面板一页」这种并列结构；后台 webclient 只有一条主导航（NavBar）。 | 同上（navbar.xml 只有 AppsMenu / App Brand / Sections / Systray 四块） |
| 3 | **OCA 19.0 唯一对口的增强模块 web_responsive（LGPL-3，Production/Stable，19.0.1.1.0）把应用菜单做成「全屏浮层 + 搜索」**——依然是**浮层**而不是新门户页；而且它只作用于**后台 assets**（web.assets_backend），够不到我们的门户 QWeb 页面。 | OCA/web 19.0 分支 web_responsive/__manifest__.py，见 §3 |
| 4 | **Moodle：一个「默认首页」可切换**。站点设置 defaulthomepage 的候选值是 HOMEPAGE_SITE（Site home）/ HOMEPAGE_MY（Dashboard）/ HOMEPAGE_MYCOURSES（My courses）/ HOMEPAGE_USER（用户偏好）——**同一时刻只落地一个**，不是并列入口。 | moodle/moodle main 分支 public/admin/settings/appearance.php，见 §4 |
| 5 | **Canvas：根路由直接就是 Dashboard**（root to: users#user_dashboard），Dashboard 页内嵌课程卡（_dashboard_card.html.erb）与右侧栏（planner/待办）；课程/分组/日历在全局导航里，但**「应用面板」不是一个独立首页**。 | instructure/canvas-lms master 分支 config/routes.rb，见 §5 |
| 6 | **产品形态上的共识 =「一个落地页 + 页内/浮层宫格」**。把仪表盘与全量功能宫格做成两个并列页面，在我们查到的四家主流实现里**都没有先例**。 | 综合 §2–§5；国内 SaaS 未验证（§6） |

## 2. Odoo 19 核心：应用启动器的真实形态（源码级）

**取证命令（可复跑）**：

    docker exec edu19-clone-web-1 odoo --version
    # → Odoo Server 19.0-20260817
    docker exec edu19-clone-web-1 sh -c \
      "sed -n '75,140p' /usr/lib/python3/dist-packages/odoo/addons/web/static/src/webclient/navbar/navbar.xml"

**原文（addons/web/static/src/webclient/navbar/navbar.xml，本机 19.0-20260817 快照；行号是本次读数、会漂移）**：

    <t t-name="web.NavBar.AppsMenu">
      <t t-if="this.ui.isSmall">
        <a href="/odoo" class="o_menu_toggle border-0" t-ref="menuApps"
           t-on-click.prevent="_openAppMenuSidebar">
          <t t-call="web.NavBar.AppsMenu.Sidebar"/>
        </a>
      </t>
      <t t-else="">
        <div t-if="!isScopedApp" class="o_navbar_apps_menu">
          <Dropdown>
            <button data-hotkey="h" title="Home Menu">
              <i class="oi oi-apps" />
            </button>
            <t t-set-slot="content">
              <DropdownItem t-foreach="apps" t-as="app" t-esc="app.name" .../>
            </t>
          </Dropdown>
        </div>
      </t>
    </t>

侧滑分支（同文件 web.NavBar.AppsMenu.Sidebar）里，移动端的「全部应用」是侧栏内的一个按钮切换：

    <a href="/odoo" class="btn btn-primary" t-on-click.prevent="onAllAppsBtnClick">
      <i class="oi oi-apps"></i><span class="px-2">All Apps</span></a>

**怎么读这段**：
- 桌面端点击「应用菜单」= 导航栏上的一个 **Dropdown（浮层）**，应用列表直接列在里面；data-hotkey="h" 是官方给它的快捷键。
- 移动端 = **侧滑抽屉**（o_app_menu_sidebar），内部用 isAllAppsMenuOpened 状态在「当前应用的小节」与「全部应用」之间切换。
- `<a href="/odoo">` 这个 href 只是**无 JS 兜底**（t-on-click.prevent 拦掉了默认跳转）——不是「点一下换一个页面」的设计。
- 启动器不是在 /odoo 里再画一个网格页：Odoo 19 的 webclient 只有 web.NavBar 这一条主结构（Apps Menu / App Brand / Sections / Systray）。

> 官方文档对照：本次未取到 docs.odoo.com 的对应原文（见 §8 未验证）。源码证据已足够支撑「启动器 = 浮层」这一形态判断。

## 3. OCA 19.0：唯一对口的是 web_responsive（LGPL-3）

**取证命令**：

    gh api -H 'Accept: application/vnd.github.raw' \
      'repos/OCA/web/contents/web_responsive/__manifest__.py?ref=19.0'
    gh api 'repos/OCA/web/contents?ref=19.0' --jq '.[].name'   # 列 19.0 分支模块

**读到的事实**：
- web_responsive：version 19.0.1.1.0、license LGPL-3、development_status Production/Stable、depends [web, web_tour, mail]、excludes [web_enterprise]。
- 它带一组 static/src/components/apps_menu* 资源（官方 README 描述为全屏应用菜单 + 应用搜索），挂在 **web.assets_backend** —— 即**只影响后台 webclient**。
- 仓库 URL：<https://github.com/OCA/web/tree/19.0/web_responsive>（本机 raw.githubusercontent.com 不可达，改用 gh api 的 raw 模式取到，见 §7）。

**对本任务的意味**：连「增强应用菜单」这个社区标准做法也是**把菜单做成浮层**（而不是新增一个页面）；且我们的门户首页是自研 QWeb 模板（edu_portal），**装它不会让门户多出一个页面**，也解决不了「两个入口」的问题。⇒ 不引入该模块，只抄形态。

## 4. Moodle：一个「默认首页」设置，而不是并列入口

**取证命令**：

    gh api -H 'Accept: application/vnd.github.raw' \
      'repos/moodle/moodle/contents/public/admin/settings/appearance.php?ref=main' | grep -n -B4 -A26 defaulthomepage

**原文（public/admin/settings/appearance.php，moodle/moodle main 分支，2026-10-03 读数）**：

    $choices = [];
    if (!isset($CFG->enablemyhome) || $CFG->enablemyhome) {
        $choices[HOMEPAGE_SITE] = new lang_string('home');
    }
    if (!isset($CFG->enabledashboard) || $CFG->enabledashboard) {
        $choices[HOMEPAGE_MY] = new lang_string('mymoodle', 'admin');
    }
    if (!isset($CFG->enablemycourses) || $CFG->enablemycourses) {
        $choices[HOMEPAGE_MYCOURSES] = new lang_string('mycourses', 'admin');
    }
    $choices[HOMEPAGE_USER] = new lang_string('userpreference', 'admin');
    ...
    $temp->add(new admin_setting_configselect('defaulthomepage', ... $choices));

**怎么读**：「Site home / Dashboard / My courses」在 Moodle 里是**同一个位置的不同选项**（站点可定默认，也可交给用户偏好）。它不是「左边一个我的主页、右边一个应用面板」的并列结构。

## 5. Canvas：根路由就是 Dashboard，宫格式内容内嵌在页面里

**取证命令**：

    gh api -H 'Accept: application/vnd.github.raw' 'repos/instructure/canvas-lms/contents/config/routes.rb?ref=master' | grep -n -i dashboard | head
    gh api -H 'Accept: application/vnd.github.raw' 'repos/instructure/canvas-lms/contents/app/views/users/user_dashboard.html.erb?ref=master' | head -40
    gh api -H 'Accept: application/vnd.github.raw' 'repos/instructure/canvas-lms/contents/app/views/shared/_dashboard_card.html.erb?ref=master' | head -70

**原文（config/routes.rb，master 分支）**：

    get "" => "users#user_dashboard", :as => "dashboard"
    get "dashboard-sidebar" => "users#dashboard_sidebar", :as => :dashboard_sidebar
    ...
    root to: "users#user_dashboard", as: "root", via: :get
    # backwards compatibility with the old /dashboard url
    get "dashboard" => "users#user_dashboard", :as => :dashboard_redirect

- Canvas 的**根路由（登录落地）就是 Dashboard**；老 /dashboard 只是兼容别名。
- Dashboard 页内预取课程卡（_dashboard_card.html.erb，ic-DashboardCard__box）与右侧栏（dashboard-sidebar）——**「我的课程/待办」是 Dashboard 的内嵌内容，不是并列的第二个首页**。
- 源码里 k5（低龄版）把这一页直接叫 Home（user_dashboard.html.erb：dashboard_title = k5_user? ? t('Home') : t('Dashboard')）。

## 6. 国内同类：钉钉 / 企业微信 / 飞书 —— **未验证**

本次**没有取到可用的一手证据**，如实登记（不得当结论用）：
- 钉钉官方帮助中心 <https://help.dingtalk.io/> 有静态 llms.txt 文档索引（这是唯一能读的国内官方文档源）。抓取 /_llms/zh/product.md（1702 页索引）搜「工作台」，只有 1 条命中，且是「通过工作台或搜索找到钉盘」（<https://help.dingtalk.io/zh/drive/how-to-configure-capacity-management-by-role.md>）——只能证明**钉钉确有「工作台」这个入口且应用从那里找**，证明不了「常用应用 + 全部应用」的页内结构。
- 钉钉旧帮助站 help.dingtalk.com/portal/index.htm 抓到的是一层 SPA 壳（可见文本是搜索热词与图片链接），拿不到正文。
- 企业微信 work.weixin.qq.com/help2/pc/19868 抓到的正文与「工作台」无关（响应体主要是 CSS）。
- 飞书帮助中心直链 feishu.cn/hc/zh-CN/articles/360024819713 返回 **404**；无站内搜索可用 ⇒ 找不到正确的文章 ID。
- 本机 web_search 工具**额度用尽**（HTTP 400 insufficient credits），mcporter 的 Exa 未配置（Unknown MCP server 'exa'），DuckDuckGo 连接被拒（curl: (35) Connection reset，http_code 000），Bing 返回 302 而不给结果 ⇒ **本轮无法用搜索引擎补证**。

⚠ 结论：**国内四家的「工作台含全部应用宫格」这条，只凭产品常识说得出，本轮没有一手 URL 支撑**。设计决断不以它为依据（Odoo/Moodle/Canvas 三家已足够）。下一个人若要补，建议直接抓钉钉文档索引里未覆盖的「管理后台」板块或飞书帮助中心的分类页。

## 7. 调查过程与死路（可复现）

| 尝试 | 命令/URL | 结果 |
|---|---|---|
| Odoo 版本 | docker exec edu19-clone-web-1 odoo --version | ✅ Odoo Server 19.0-20260817 |
| 找 home menu 源码 | ls .../web/static/src/webclient/、grep -rln 'home_menu\|HomeMenu\|apps_menu' web/static/src | ✅ 命中 navbar/navbar.xml、menus/menu_helpers.js —— Odoo 19 的术语已变成 AppsMenu |
| 取 Odoo 原文 | docker exec ... sed -n '75,140p' .../navbar/navbar.xml | ✅ 见 §2 |
| OCA 模块清单 | gh api 'repos/OCA/web/contents?ref=19.0' --jq '.[].name' | ✅ 19.0 分支模块可用；含 web_responsive |
| OCA manifest | gh api -H 'Accept: application/vnd.github.raw' 'repos/OCA/web/contents/web_responsive/__manifest__.py?ref=19.0' | ✅ LGPL-3 / 19.0.1.1.0 / Production-Stable |
| OCA 搜索 | gh api 'search/repositories?q=dashboard+org:OCA' | ❌ 空返回（search API 无鉴权受限；未再尝试） |
| raw.githubusercontent | curl https://raw.githubusercontent.com/OCA/web/19.0/web_responsive/__manifest__.py | ❌ curl: (35) Recv failure: Connection reset by peer（http_code 000）⇒ 全程改用 gh api raw 模式 |
| Moodle 设置 | 先试 admin/settings/appearance.php?ref=main | ❌ 404 —— **Moodle 5.x 把 admin 移到了 public/ 下**（gh api .../git/trees/main?recursive=1 找到 public/admin/settings/appearance.php） |
| Canvas 控制器 | contents/app/controllers/dashboard_controller.rb?ref=master | ❌ 404 —— Canvas 的 dashboard 在 users#user_dashboard，没有独立 dashboard_controller（在 config/routes.rb 里确认，见 §5） |
| docs.moodle.org | web_fetch https://docs.moodle.org/en/Dashboard | ❌ TypeError: fetch failed（未取到官方文档原文；结论以源码为准） |
| Canvas 官方指南 | community.canvaslms.com/.../What-is-the-Dashboard/ta-p/98 | ⚠ 被跨域重定向到 community.instructure.com，未跟随；源码已足够 |
| 钉钉帮助中心 | help.dingtalk.com/portal/index.htm | ⚠ SPA 壳，无正文 |
| 钉钉文档索引 | curl https://help.dingtalk.io/_llms/zh/product.md 后 grep 工作台 | ⚠ 仅 1 条间接命中（见 §6） |
| 飞书帮助 | https://www.feishu.cn/hc/zh-CN/articles/360024819713 | ❌ 404 |
| 企业微信帮助 | https://work.weixin.qq.com/help2/pc/19868 | ⚠ 正文与工作台无关 |
| 搜索引擎 | web_search / Exa(mcporter) / DuckDuckGo / Bing | ❌ 额度用尽 / 未配置 / 连接被拒 / 302 |

## 8. 未验证 / 待确认

1. **国内三家（钉钉/企业微信/飞书）工作台结构**：未验证（原因见 §6）；
2. **Odoo 官方文档对「Home Menu」在 19.0 的措辞**：未取到 docs.odoo.com 页面（本轮网络受限），只有源码证据；
3. **OCA 其他仓库（vertical-education / server-backend）是否有门户首页合并类模块**：未做穷举（search API 空返回）；vertical-education 的 19.0 空仓结论来自本仓既有调研 docs/research/scheduling-approaches.md，本轮未复核；
4. **Moodle Dashboard 的实际页面结构**（块布局）未读源码，只读了「默认首页」这一层；对本任务（入口数量）已够；
5. GitHub 上 Moodle/Canvas 的引用取自 main/master **当天快照**，会漂移；本文引用的都是**片段原文**而不是行号。

## 9. 对本仓的裁定（先例 → 设计方向）

外部先例一致指向：**一个落地页** + **页内（或浮层）功能宫格**；没有任何一家把「我的主页」和「应用面板」做成两个并列的首页式页面。

因此本任务采用：

1. **保留 /my/home 为唯一入口**，名字沿用「我的主页」（它同时是登录落点、品牌标链接、面包屑「家」的落点，全仓 118 处活引用——改名字/改路径的成本与风险都远大于把宫格搬进来）；
2. 把原先挂在 /my/apps 的**门户功能宫格**、以及 /apps 的**后台应用瓦片**，内嵌到教师版 /my/home（原两块的卡片去重后同页呈现）；
3. /my/apps、/apps 对**纯教师**收口为 303 → /my/home（与 H-1「学生/家长宫格合并」同口径：路由保留 ⇒ 旧书签不 404）；
4. 导航（侧栏 / 用户菜单 / 面包屑）对纯教师只留「我的主页」一条；**教务/管理员/学生/家长的行为不动**。

依据：§1 结论 1–6（Odoo 19 浮层启动器、OCA 增强仍是浮层、Moodle 单一默认首页、Canvas root=Dashboard 内嵌课程卡）。

## 10. 附：本仓既有内部先例

- **H-1（校长拍板 2026-09-18）**：学生/家长的 /my/apps 已收口为 303 → /my/home，学生首页 = 原全量宫格 + 待办窄条。证据与判据：docs/plans/student-portal-home-profile-design.md §8.1/§8.2、tests/smoke/ux_v3_route_matrix.py 的 ROUTE_RULINGS。
- 本次教师侧收口**沿用同一形状**，只是把「工作台」放在宫格之上（教师有教学专属内容，学生没有）。