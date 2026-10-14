# task-12：窄屏卡片化 C（门户台账 / 课程编排 / 家长账单 + 批量排课）

> 2026-10-02 本机栈实测（`http://localhost:8069`，`db=edu19`）；视口 **375×812（手机）** / **1440×900（桌面）**；
> 每页按**该页真正的角色**登录（`/ledger`、`/registrar/curriculum`、`/timetable/bulk` = backoffice，`/my/fees` = parent）。
> 截图：[before/](before) vs [after/](after)（外加 [before-ledger-curriculum/](before-ledger-curriculum)，理由见 §1 末注）。

## 0. 结论：四条验收逐条给读数

| # | 验收 | 读数 |
|---|---|---|
| ① | `find_squeezed_tables.py` → OK | **8/8 RESULT=OK**（4 页 × 2 轮，防单次假绿） |
| ② | 桌面 1440 下 thead computed display 仍是 `table-header-group` | 4 页 **全部 `table-header-group`**（改前改后一致 ⇒ 媒体查询只在 <768px 生效，桌面一字未变） |
| ③ | 375 视口横向溢出仍 ≤8px | 4 页 **`overflow=0px`**（改前改后都是 0；本轮的缺陷是「挤成一团/被裁」，不是整页溢出） |
| ④ | 改前/改后 375 截图 | [before/](before) 与 [after/](after) 各 4 张手机图 + 4 张桌面图（人眼可对照：逐字换行 → 「标签左灰 / 值右对齐」卡片） |
| ⑤ | `safe_upgrade.sh` EXIT=0 | `bash scripts/safe_upgrade.sh edu_portal,edu_schedule` → **EXIT=0**，失败特征 **0 条**（日志 `/tmp/edu19_upgrade.20261002-210131.log`） |
| ⑥ | `check_view_xpath` / `check_md_tables` / `check_docs_index` | **RESULT=OK，三者 exit=0**（26 / 10757 / 306 条断言） |

## 1. 四页 before → after（375 视口，逐表读数）

| 页面（角色） | 改前 | 改后 |
|---|---|---|
| `/ledger`（backoffice） | 10 列，表宽 **573** > 容器 345，`thead=table-header-group` ⇒ SQUEEZED | **`thead=none`**（卡片），表宽 345，`edu-card-table` ✓，`td[data-label]`×20 |
| `/registrar/curriculum`（backoffice） | 6 列，**362** > 345 ⇒ SQUEEZED | **`thead=none`**，345，卡片 ✓，data-label×432 |
| `/my/fees`（parent） | 6 列，**371** > 345 ⇒ SQUEEZED | **`thead=none`**，345，卡片 ✓，data-label×12 |
| `/timetable/bulk`（backoffice） | 6 列，**421** > 容器 313 ⇒ SQUEEZED | **`thead=none`**，313，卡片 ✓，data-label×85 |

（data-label 计数含 tbody 里的多行 × 每行每个 td，所以远大于列数。）

**为什么有 `before-ledger-curriculum/` 这个额外目录**：我改完这 4 个文件时，**别人的 `safe_upgrade -u edu_portal` 先把其中两个（ledger/curriculum）加载进库了**
（`safe_upgrade` 串行锁只保证不并发升级，不保证「只有我在升级我的文件」）⇒ 我第一时间抓到的「改前」截图其实是改后态。
为了拿到**真的改前图**，我把这两个文件的 t-call 与类名临时还原、升级、截图（`before-ledger-curriculum/`，读数与工具都是 SQUEEZED），再立刻还原并升级。
`/my/fees` 与 `/timetable/bulk` 没被提前加载，改前图取自最初那次采集（`before/`）。

## 2. 改了什么（4 个文件，全部在写作用域内）

| 文件 | 改动 |
|---|---|
| `edu_portal/views/ledger.xml` | `/ledger` 10 列表：表前 `<t t-call="edu_portal.edu_narrow_table_cards"/>` + 表加 `edu-card-table` + 10 个 td 各补 `data-label` |
| `edu_portal/views/curriculum.xml` | `/registrar/curriculum` 6 列表：同上（6 个 td 补 label） |
| `edu_portal/views/fees.xml` | 家长/教师/内部那张单表：加 `edu-card-table` + 6~7 个 td 补 label；**另把共用样式的 t-call 上移到页面级**（见 §3） |
| `edu_schedule/views/templates.xml` | `/timetable/bulk` 的「批量停用某班课时」表：t-call + 类名 + 5 个 td 补 label（最后一个「停用…」操作列**故意不加** label，CSS 会隐藏无 label 的 ::before） |

没有新造样式、没有改栅格、没有动任何文案；媒体查询之外零规则 ⇒ 桌面端 DOM 与观感不变（§0 ② 是它的机械证明）。

## 3. 过程中踩到并修掉的一个真坑：**样式 t-call 挂在角色分支里 ⇒ 类名形同虚设**

按卡片给的修法给 `/my/fees` 家长分支表加类名后，实测**没生效**：

```
# 家长身份、375 视口（第一次改完、升级后）
  /my/fees   cols=6  w=371  container=345  thead=table-header-group   card=True  labels=12   SQUEEZED
                                                                    ^^^^^^^^^ 有类名      ^^^^^^^ 样式没上来
```

根因：`edu_portal.edu_narrow_table_cards` 的 `<style>` 在 `fees.xml` 里**原来是挂在 `edu_fees_bill_list` 的「学生分支」（`t-if="role == 'student' and bills"`）里**的 ——
家长/教师/内部走的是 `t-elif="bills"` 那段，**根本渲染不到那份 `<style>`**，我加的 `edu-card-table` 自然没有规则可依。

修法：把 t-call 上移到 `edu_fees_page`（页面级、全角色一次），并删掉学生分支里那处（否则学生侧会出现两份 `<style>`；
家长有 N 个孩子时，原写法还会输出 N 份）。**学生分支的两张表、它们的类名与 data-label 一字未动。**

> 这条值得记：**「加了类名」不等于「样式生效」**；判据必须落到「thead 的 computed display」这种**渲染后**的读数上，
> 而不是源码里 grep 到 `edu-card-table`。

## 4. 跨模块 t-call 的未声明依赖：**我原来的建议是错的，正解待架构裁定**

`/timetable/bulk` 在 **edu_schedule** 模块里，而共用模板在 **edu_portal** 里；`edu_schedule/__manifest__.py` 的 `depends` **没有 edu_portal**
（只有 `openeducat_timetable` + `website`）。本部署里 edu_portal 是门户中枢、必然在装，所以运行正常；
但严格说这是一条**未声明的模块依赖**：真要做「只装 edu_schedule」的最小安装，这个模板会解析不到。

我原本的建议是「照 `edu_life` 的先例（commit `c05f97b`）给 edu_schedule 的 depends 补一行」——**队长查环后否掉了，方向对但会成环**：

```
edu_portal 的 depends 里**本来就含 edu_schedule**
⇒ 反向再声明 edu_schedule → edu_portal 就是循环依赖，Odoo 直接装不上
对比：edu_life 能加，是因为 edu_portal **不依赖** edu_life（同一个症状、两个模块，修法相反）
```

⇒ 结论与纪律已由队长写进 **`docs/code-map.md` §6 第 16 条**（commit **bdac028**）：**t-call 了谁就要声明谁，但声明前必须先查会不会成环**。
edu_schedule 的正解（把共用 partial 挪到双方都依赖的低层模块 / 或者自带一份）两条都有代价，**本轮未动**，留给产品与架构裁定；
现状只在「单装 edu_schedule」时才会炸，日常运行无影响。

> 自省：我提建议时只比对了「edu_life 这么修过」，没有查反向依赖 —— 这正是本仓「先查再改」那类返工。
> 报告保留这条修正记录（而不是悄悄改掉），因为下一个遇到同类问题的人多半也会先想到「补 depends」。

## 5. 判据工具的一次假绿（照实报，建议加固）

第一次跑四条页面时，`/registrar/curriculum` 报过 **`RESULT=OK（无挤扁表）`**；随后同一命令**连跑 3 次都是 `RESULT=SQUEEZED`**（6 列 362 > 345），
我自己的独立探针（直接注入会话 cookie + 读 DOM）也稳定量到 362 > 345。⇒ 那一次 OK 是**假绿**，不是页面真的变好了。

最可能的原因：工具的 `login()` 走浏览器表单（`form.oe_login_form`），而本仓登录页把 core 那个表单渲染成 `d-none`（隐藏），
一旦某次登录流程没落地，`/registrar/curriculum` 会落到没有表格的页面 ⇒ 「无挤扁表」被当成「通过」。
根因与修法：队长认下这是**工具缺陷**并已修（commit **58a43ce**）—— `login()` 原先不校验登录结果，登不进去 ⇒ 页面上没有表 ⇒ 被判成「无挤扁表」。
现在登录后必须确认① 已离开 `/web/login` ② 拿到 `session_id` cookie，否则**抛错记 ENV**（不是通过）。

> 这是本仓反复出现的同一条：**「读数没变」既可能是没问题、也可能是量具没工作** —— 这次是量具。
> 我当时的建议（把「登录失败 / 无表」与「有表但不挤」分开、前者记 ENV）与最终修法一致；
> 但**建议归建议**：在工具修好之前，本卡的判据一律跑两轮并用渲染读数交叉验证，不单吃一次结论。

本卡因此把每条判据跑了**两轮**（§0 ①：8/8 OK），并用 §1 的渲染读数交叉验证，不单吃工具的一次结论。

## 6. 复跑命令

```bash
# 判据（375 视口，按页面角色）
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy \
  no_proxy=127.0.0.1,localhost /opt/homebrew/bin/python3 \
  scripts/find_squeezed_tables.py --path /ledger --role backoffice
#   /registrar/curriculum --role backoffice ｜ /my/fees --role parent ｜ /timetable/bulk --role backoffice

# 截图 + 逐表读数（375 与 1440 两档，含 thead display / 表宽 / 容器宽 / data-label 计数 / 页面溢出）
/opt/homebrew/bin/python3 docs/audit/narrow-tables-c/shots.py docs/audit/narrow-tables-c/after

# 升级（唯一路径；串行锁）
bash scripts/safe_upgrade.sh edu_portal,edu_schedule
```
