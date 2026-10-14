# task-19：老师的「我的主页」与「应用面板」合并

> 用户原话（2026-10-03）：「我希望老师的我的主页和应用面板功能可以合并，不要分开了。」
> 本机栈实测（`http://localhost:8069`，`db=edu19`）；判据全部落在**渲染后的页面**（Playwright）。
> 证据：`verify-before/after.json`（角色矩阵+链接并集）、`merged-final2.json`（三缺口复核）、`shots/`（375 与 1440 截图）。

## 0. 结论：教师只剩一个入口，功能零丢失（逐条见 §4）

| 项 | 改前 | 改后 |
|---|---|---|
| 教师门户里的「首页类」入口 | **3 个**：我的主页 / 应用面板（/apps）/ 全部应用（/my/apps） | **1 个**：我的主页（/my/home，工作台 + 应用宫格同页） |
| 面包屑 | 家 / **应用面板** / 我的主页 | 家 / 我的主页（`merged-final2.json`: `breadcrumb=['/my/home']`） |
| 用户下拉 | 我的主页 + **应用面板** | 我的主页（教师） |
| 上手清单第 1 条 | 承诺「点击左侧导航『应用面板』…」（对教师已是假话） | 教师回落到「点击左侧导航或首页卡片进入各功能」 |
| 可达站内链接（教师三页并集） | 70 条 | 65 条 = 70 − 4 条**拒止死卡** − 1 条**被合并的重复入口**（§4 逐条） |

## 1. 铁律 0 调研

> **外部先例的完整调研见队长文档：[`docs/research/teacher-home-apps-merge.md`](../../research/teacher-home-apps-merge.md)**（2026-10-03，commit 96b13b9）——
> 结论：Odoo 19 把应用启动器做成**导航栏下拉/侧滑浮层**；OCA `web_responsive`(LGPL-3) 是**全屏浮层 + 搜索**；
> Moodle `defaulthomepage` **同一时刻只落地一个**首页（Site home / Dashboard / My courses 三选一）；Canvas 根路由就是 Dashboard。
> ⇒ **「仪表盘一页 + 应用面板一页」并列在四家主流实现里没有先例**，合并成一个落地页是共识做法。
> 本节只保留**我自己**跑过的一手读数，与队长那份互为交叉验证。

| # | 查了什么 | 方式 | 结论 |
|---|---|---|---|
| 1 | **Odoo 19 核心**怎么处理「应用启动器 vs 各应用首页」 | 读部署镜像内源码：`odoo/addons/web/static/src/webclient/navbar/navbar.xml` | **启动器是顶栏组件，不是独立页面**：`:10-12 <!-- Apps Menu --> <t t-call="web.NavBar.AppsMenu"> <t t-set="apps" t-value="menuService.getApps()"/>`；`:75-89` `o_navbar_apps_menu` 下拉网格；`:104-111` `AppsMenu.Sidebar` 里「All Apps」按钮 → `/odoo`。另一处 `menus/menu_helpers.js:18` 注释 "with keys \"apps\" and \"menuItems\" (HomeMenu props)" |
| 2 | OCA 有没有现成的「门户首页与应用面板合并」模块 | `gh api repos/OCA/website/contents --jq '.[].name'` + `gh api repos/OCA/web`（1233★） | **没有可直接用的**：OCA/website 里与 portal 相关的只有 `portal_invitation_by_website`（邀请注册）；OCA/web 的 `web_responsive` 只作用于**后台 assets**，够不到门户 QWeb（队长文档 §3 有 manifest 级证据） |
| 3 | 本仓自己的同类先例 | `docs/plans/student-portal-home-profile-design.md:19 / :36` | **H-1（2026-09-18 校长拍板，已上线）**：学生「唯一保留的门户首页 = /my/home，其内容改为『全部应用』界面；/my/apps 降级为兼容层」。本轮教师合并**照抄这条口径**，不再新立规矩。 |


⇒ 设计依据 = **Odoo 核心的「启动器是导航组件」** + **本仓 H-1 的学生先例**；两者都指向同一做法：把内容合并到一个首页，把重复入口收掉。

## 2. 改了什么（4 个文件）

| 文件 | 改动 |
|---|---|
| `controllers/batch2.py` | ① 抽出 `_apps_grid_values()`（宫格上下文装配，`/my/apps` 与合并首页共用，避免两处漂移）；② `edu_home` 教师分支：渲染 `edu_dashboard_v2` 并把 `_teacher_dashboard()` 的上下文合进去（`merged_apps=True`）；③ `edu_apps`：教师 303 → `/my/home`（教务/管理员不变）；④ `_teacher_dashboard()` 新增「应用面板（后台）」卡（指向 `/apps`）+ `merged_apps` 键；⑤ 合并时**按 href 去掉宫格已有的工作台卡**（`dup_dropped` 记录被去掉的标题） |
| `views/batch2.xml` | ① 把教师工作台 body 抽成 partial `edu_teacher_workbench`（教师页与合并首页共用，零重复 markup）；② `edu_dashboard_v2` 在教师角色下 `t-call` 该 partial（紧跟迷你头部）；③ 侧栏「快速操作」里 4 条学生专属入口加 `t-if="student"`（对教师**和家长**都消失）；④ 合并页不渲染 W1「常用应用」置顶条（宫格自身有该类目，两条 `[data-fav-grid]` 会让 JS 抓错容器）；⑤ 合并页侧栏快捷条按 href 去重（课程中心/校历与宫格重复 ⇒ 只留「证书」） |
| `views/edu_portal_templates.xml` | **直改源模板**（不再用继承视图）：面包屑 / 用户菜单 / 侧栏「应用面板」/ 侧栏「全部应用」/ 上手清单第 1 条 —— 五处各追加 `and not b11_fac` |
| `models/menu_labels.py` | **未改**：它管的是后台 `ir.ui.menu`（停用旧菜单、统一菜单名），与本门户导航无关；grep 全文件无 `/apps`、`我的主页`、`应用面板` 命中 ⇒ 无需动（如实说明，不为凑写范围而改） |

## 3. 三个缺口的处置（独立复核报的，逐条给证据）

**缺口 1 —— 侧栏「快速操作」4 项是拒止页**（考勤/作业/考试/成绩簿；教师新接入后中招，**家长是既有缺陷**）
- 修法：4 条加 `t-if="student"`（判据与控制器 `_STUDENT_ONLY_CARDS` 同源，不另立一套）。
- 渲染后实测（`merged-final2.json`）：`faculty 侧栏「快速操作」3 项，其中拒止 0 项`；`parent 3 项，拒止 0`；**student 仍是 7 项、拒止 0**（学生没被误伤）。
- ⚠ 复核方指出 `probe_home_cards` / `probe_nav_deadlinks` 的选择器扫不到 `.oe-qa-side` ⇒ 两条门禁**报不出来**。**我没有改这两个脚本**（写范围是 4 个文件），已请队长按他说的「另外跟进」；在那之前本页的拒止判定用本卡的 `check_merged.py`（逐项请求 + 文案判「仅面向」）。

**缺口 2 —— 上手清单第 1 条对教师仍是错的**（继承视图静默失效）
- 复核方的诊断我复核了：`//li[@t-if="request.env.user.has_group('base.group_user')"]` 在 `edu_page` 里有**两个** li（用户菜单项 + 清单项），继承只改到一个。
- 修法：**放弃继承视图**，回到源模板直改（`edu_portal_templates.xml` 的那一个 li）。
- 实测：`faculty: 上手清单「应用面板」句 0 次；回落句 1 次`（`student/backoffice` 行为不变）。

**缺口 3 —— 同屏重复块**

| 项 | 改前 | 改后 | 说明 |
|---|---|---|---|
| 「常用应用」出现次数 | 2 | **1** | 合并页不再渲染工作台 W1 置顶条（宫格自身有该类目）；顺带修掉「两条 `[data-fav-grid]` ⇒ `home_favs.js` 的 `querySelector` 只抓第一条、宫格那条『编辑』变死按钮」 |
| 工作台卡 vs 宫格卡 | 4 条重复（校历/私信/通讯录/资料下载） | **0** | 控制器按 href 去掉宫格已有的工作台卡（`dup_dropped` 记录标题）；宫格是目录、工作台只留独有动作 |
| 侧栏快捷条 vs 宫格 | 课程中心、校历重复 | **0** | 合并页隐藏这两条（宫格「学业」类目里有）；保留「证书」——宫格里没有它，删了就少一个入口 |
| 剩余重复（教师 /my/home） | — | `/my/messages`×3、`/my/calendar`×2、`/my/notice_board/notice`×2 | 都是**宫格自身的既有性质**（「常用应用」类目镜像其它类目的卡）+ 顶部/侧栏导航与月历挂件标题链接；**学生页一模一样**（学生 `/my/messages`×2、`/my/calendar`×3…）⇒ 属既有设计，不在本次合并范围；要一并去重需动宫格引擎（会影响学生），**请队长定** |

## 4. 功能不丢对照表（教师三页并集 70 → 65，缺失 5 条**逐条**给理由）

```
改动后不可达: ['/grade-book', '/my/apps', '/student/assignment/details',
              '/student/attendance', '/student/exam']
```

| 缺失链接 | 为什么不是「功能丢失」 |
|---|---|
| `/student/attendance`、`/student/assignment/details`、`/student/exam`、`/grade-book` | 这 4 条对教师是**拒止页**（HTTP 200 + 文案「仅面向学生账号」）—— 独立复核方实测确认。删掉的是**死卡**，不是功能 |
| `/my/apps` | 被合并掉的**重复入口**本身；路由仍在，教师访问会 303 回 `/my/home`（旧书签不 404，与学生 H-1 同口径） |

其余 65 条逐条都在（`verify-after.json` 可复算）。教师工作台侧的关键入口（周记批阅 /journals/review、待批请假 /leave/approvals、申诉 /grievances/approvals、周期排课 /timetable/bulk、报销申请 /my/reimburse/apply、打卡统计 /checkins/stats）一条不少。

## 4.1 `/my/apps` 对教师是 **303**：选的是「真的合并掉」，并且**同步改了那两条硬断言的期望**

队长提出两条路：a) 教师侧真的合并掉（入口不出现 + 路由做收口处理）并同步更新硬断言；b) 让 /my/apps 对教师仍 200、只是不给第二个入口。**选的是 a**，理由：

1. 与学生 H-1 完全同口径（学生/家长本来就是 303 → `/my/home`）——同一件事只有一套语义，后来人不用记两套；
2. 选 b 会留下一个**没有任何入口、却仍能打开**的孤儿页，教师从旧书签进去看到的是「没有工作台」的半个首页，反而更容易困惑；
3. a 需要动的是**断言的期望值**（不是删断言）：`tests/smoke/ux_v3_route_matrix.py` 的 `REDIRECT_STRICT_BY_ROLE` 里
   `('/my/apps', 'fac', 200, None, …)` → `('/my/apps', 'fac', 303, '/my/home', '教师：工作台+宫格已并入 /my/home（2026-10-03）')`，
   另一条在 `tests/audit/verify_consolidation.py`。**这两处由队长在 commit 936ad9b 里落**（他同时保留了 `bo` 的 200 —— 教务行为未变）。

**复跑证据**（我执行的原始读数）：

```
PASS /my/apps    [stu] 强断言 303 /my/home  303->/my/home  <- 学生：宫格已合并进 /my/home
PASS /my/apps    [par] 强断言 303 /my/home  303->/my/home  <- 家长：同上
PASS /my/apps    [fac] 强断言 303 /my/home  303->/my/home  <- 教师：工作台+宫格已并入 /my/home（2026-10-03）
PASS /my/apps    [bo] 强断言 200 -  200->-  <- 教务：门户宫格入口不变
旧打卡入口强断言（303 + Location 精确）：3 条 / 失败 0
H-1 /my/apps 角色强断言（学生/家长 303 + Location 精确；内部用户 200）：失败 0
检查点 540：PASS 540 / WARN 0 / PENDING 0 / FAIL(真红) 0 / ENV(环境) 0
```

⇒ 断言没有放松：**303 侧仍要求「码 303 + Location 精确等于 /my/home」**（这正是 dev-workflow 陷阱 2 里那条「旧入口改成 303 在矩阵里永远 PASS 是假绿」的补丁），只是把 `fac` 从 200 侧挪到了 303 侧。

## 5. 取舍（供用户拍板）

| 取舍点 | 我的选择 | 理由 / 另一条路 |
|---|---|---|
| 保留哪个名字 | **「我的主页」** | 用户说的是「合并」，没说改名；`/my/home` 是登录落地页、全仓 118 处活引用、学生 H-1 也保留了它 ⇒ 改动面最小 |
| 页面顺序 | 工作台在上（待办提醒 / 常用应用 / 教师快捷卡 / 本周我教的课），宫格在下 | 教师开首页第一眼要看到「现在该干什么」，浏览目录是第二动作 |
| `/apps`（后台应用网格） | **保留页面 + 首页一张「应用面板（后台）」卡**；不占导航位、也不做 303 | 门户宫格装不下后台菜单（图标是 `web_icon`、深链是 `/odoo/action-*`）；若让它 303 回 `/my/home`，这张卡就变成**死链**（`probe_nav_deadlinks` 的判据正是「落到 /my/home ⇒ 死链」）⇒ 保留 200 才对 |
| 重复的「常用应用」留哪一个 | 留**宫格**那一个（顶部 W1 条在合并页不渲染） | 宫格那条带「N 项」计数与编辑按钮、且在页面下方成体系；两条并存会抢同一个 JS 容器 |
| 剩余 chrome 级重复 | 不动 | 见 §3 缺口 3 末行 |

## 6. 过程中踩到并写进本报告的两个坑

1. **从模块里删掉一个视图后，`-u` 不会清理库里已存在的 `ir.ui.view`** ⇒ 那个残留视图的 xpath 找不到宿主元素，整个升级 **255 失败**（`ParseError: 上级视图内找不到元素`）。本地库的处置：确认无误后删掉该记录（`ir_model_data` + `ir_ui_view` 各 1 行），**全新安装不受影响**（`--fresh-install` 里从来没有这条记录）。⇒ 教训：模板继承是**加了就要善后**的东西。
2. **继承视图静默失效**：`//li[@t-if="…group_user…"]` 在 `edu_page` 里有**两个**同 t-if 的 li，实测只改到了一个。⇒ 不管用哪种方式改模板，**改完必须读 DB arch 或渲染文本确认**（本轮就是靠渲染计数才发现「上手清单那句还在」）。

## 7. 门禁与复跑命令

```bash
# 渲染后三角验证
/opt/homebrew/bin/python3 docs/audit/faculty-home-merge/verify.py after        # 角色矩阵 + 功能并集
/opt/homebrew/bin/python3 docs/audit/faculty-home-merge/check_merged.py final2  # 入口收口 / 拒止卡 / 同屏重复
/opt/homebrew/bin/python3 scripts/probe_nav_deadlinks.py                        # 导航死链（四角色 67 条）

# 升级与全量门禁
bash scripts/safe_upgrade.sh edu_portal
bash scripts/check_all.sh --fresh-install
```
