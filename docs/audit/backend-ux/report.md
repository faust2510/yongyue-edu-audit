# 后台（Odoo 管理界面）UI/UE 审计报告 —— T3 死角

> 任务：共享卡 `task-8` ｜ 执行：teammate `backend-ux` ｜ 日期：2026-10-02 ｜ 本地栈：edu19-clone（http://127.0.0.1:8069，库 `edu19`）
> 写作用域：`custom_addons/edu_brand`、`custom_addons/edu_zh`、`custom_addons/edu_nav`、`docs/audit/backend-ux/**`
> 本报告所有读数都可用文末命令复跑；每条断言都标注了证据文件。

---

## 0. 一句话结论

**后台确实是三套 UI 门禁的结构性盲区，而且不是「扫得少」而是「扫了也永远绿」。**
我把它的文案面真正量了一遍：登录态下 admin 的 321 条菜单里有 **8 条纯英文**、教务 143 条里 **4 条**、教师 74 条里 **2 条**；
`/odoo/action-649`（在线测验）与 `/odoo/action-650`（作答记录）**整页英文**。
已修掉 **40 条记录**（含教务/教师可见的全部），教务与教师侧英文菜单**清零**；admin 剩 2 条被 Odoo 的 noupdate 规则结构性挡住（见 §6）。

| 读数 | 改前 | 改后 | 证据 |
|---|---|---|---|
| admin 纯英文菜单名 | 8 | **2** | `evidence/menus_before.json` → `evidence/menus_after.json` |
| 教务 backoffice | 4 | **0** | 同上 |
| 教师 faculty | 2 | **0** | 同上 |
| `/odoo/action-649` 渲染出的英文 | 8 项 | **0** | `evidence/pages_before.json` → `evidence/pages_after.json` |
| `/odoo/action-650` 渲染出的英文 | 6 项 | **0** | 同上 |
| `scripts/check_english.py`（门户口径） | must-fix 0 | must-fix 0 | `evidence/check_english_portal.txt`（**两条读数都是 0，因为它根本看不到后台** —— 见 §2） |

---

## 1. 取证方法（先证明「我真的打开过后台」，不是读源码猜的）

后台是 **JS 客户端渲染**：`/odoo/<action>` 的 HTTP 响应体只有 **6890 字节的空壳**，
所有可见文案要么在 `<script>` 里、要么由 RPC 取回后渲染。所以本轮的取证分三层，
每层都留了可复跑的探针：**`docs/audit/backend-ux/backend_probe.py`**。

### 1.1 登录态（admin）

```
POST /web/session/authenticate  db=edu19 login=admin password=demo123
  -> 200, result.uid = 2, user_context.lang = zh_CN
```

三个角色账号：`admin`(uid=2) / `backoffice@local`(uid=12，教务) / `faculty@local`(uid=11，教师)，口令均为 `demo123`。

### 1.2 三个读数面

| 面 | 手段 | 为什么必须用它 |
|---|---|---|
| **menu 源** | 登录态 `GET /web/webclient/load_menus` | 服务端返回的菜单树是**用户顶栏真正看到的**；按角色取 |
| **dom 源** | Playwright 真浏览器渲染后取 `innerText` | 用户真正看到的按钮/列标签/徽章；HTTP 响应体里一个都没有 |
| **落库源** | `psql` 直读 `ir_ui_menu.name` / `ir_actions.name` / `ir_model_fields.field_description` | 判「词条到底有没有生效」，不看日志 |

### 1.3 复跑命令

```bash
export no_proxy=127.0.0.1,localhost
python3 docs/audit/backend-ux/backend_probe.py --selftest                 # 离线自证 15/15
python3 docs/audit/backend-ux/backend_probe.py --menus  --json /tmp/m.json
python3 docs/audit/backend-ux/backend_probe.py --pages  --role admin \
    --urls '在线测验列表=/odoo/action-649,作答记录=/odoo/action-650'
```

探针**复用 `scripts/check_english.py` 自己的分类器**（`importlib` 载入 `classify()` 与白名单），
所以读数与门户门禁是**同一套判据**，不是另造词表。自证输出带两边指纹：

```
== backend_probe fp=... · check_english REVISION=v3.8 指纹=c9b87745 · 运行时刻 ... ==
  selftest: 15/15
```

---

## 2. 结构性发现（本轮最重要的结论）：后台不是「没扫到」，是「扫了永远绿」

### 2.1 门禁名单里根本没有后台的 english 登记

`tests/ui/surface.json` 共 302 条登记，其中 `/odoo/*` 有 7 条，但它们的 gate 是：

```
{"key": "backend-students", "path": "/odoo/students", ..., "gates": ["accessibility"]}
{"key": "backend-contacts", "path": "/odoo/contacts", ..., "gates": ["accessibility"]}
...
```

`scripts/check_english.py` 只扫 `gates` 含 `english` 的 89 条 —— **`/odoo/*` 一条都不在里面**。
`scripts/check_ui_usability.py` 的四轴（横向溢出/主操作越界/中文措辞/空态出口）同样由门户路由派生。

### 2.2 控制组：**把后台登记进 english 门禁，它照样报绿**（决定性证据）

我造了一份控制组 surface（把 `/odoo/apps`、`/odoo/action-649`、`/odoo/action-650`、`/odoo/students`
登记为 `gates:["english"]`），跑 `check_english.py --surface ...`：

```
本门禁扫描：91 条路径 × 角色 = ... backoffice 91
对账：扫描集 − 表 = （空） ｜ 表 − 扫描集 = （空）      <- 后台页确实进了扫描名单
  /odoo/action-649                 200 OK              <- 扫了
  /odoo/action-650                 200 OK              <- 扫了
```

**`OK` = must-fix 0。** 而同一时刻、同一 URL，用浏览器渲染：

```
/odoo/action-649   HTTP 200   6890 bytes   scan_body 命中 0
/odoo/action-650   HTTP 200   6890 bytes   scan_body 命中 0
/odoo/students     HTTP 200   6890 bytes   scan_body 命中 0
/odoo/apps         HTTP 200   6890 bytes   scan_body 命中 0     <- 但浏览器在这一页数到 32 条英文
```

根因（可复算）：`check_english.py` 的 `scan_body()` 显式剔除 `<script>`/`<style>`/注释/`<template>`
（`SCRIPT_RE` 等），而后台空壳的**全部文本节点都在 `<script>` 里** ⇒ 恒 0 命中。

> **结论：把 `/odoo` 登记进 english 门禁 = 造一个永久假绿的门禁。** 谁想做这件事，先证明这条判据能变红。
> 证据：`evidence/control_check_english_blindness.json`、`evidence/check_english_control_backend.txt`。

### 2.3 附带发现：门禁的「探活」口径对后台是空转

`/odoo`、`/odoo/apps`、`/odoo/action-649` 全部返回 **200 + 6890 字节**（同一份空壳）。
所以 **HTTP 200 不能证明后台能用** —— 本轮我就实测到一次「全部 200，但后台白屏」：
`/web/webclient/translations` 返回 **500**，整个 Web 客户端起不来，而 `/odoo` 依旧 200（见 §5）。

---

## 3. 逐角色审计

### 3.1 菜单面（`load_menus`，服务端真值）

| 角色 | uid | 菜单条数 | 可见根 | 纯英文菜单名（改前） | 改后 |
|---|---|---|---|---|---|
| admin | 2 | 321 | 14 | 8 | **2** |
| 教务 | 12 | 143 | 12 | 4 | **0** |
| 教师 | 11 | 74 | 9 | 2 | **0** |

改前逐条（`evidence/menus_before.json`）：

| 菜单名（英文） | 菜单 id | xmlid | 谁看得见 | 处置 |
|---|---|---|---|---|
| Quizzes | 505 | edu_quiz.menu_edu_quiz | **三个角色全部** | 已修 → 在线测验 |
| Attempts | 506 | edu_quiz.menu_edu_quiz_attempts | **三个角色全部** | 已修 → 作答记录 |
| All Conversations | 510 | im_livechat.menu_livechat_all_conversations | admin + 教务 | 已修 → 全部会话 |
| Looking for Help | 511 | im_livechat.menu_livechat_looking_for_help | admin + 教务 | 已修 → 待接入咨询 |
| Technical Pages | 231 | website.menu_website_technical_pages | admin | 已修 → 技术页面 |
| Event Questions | 380 | event.event_question_menu | admin | 已修 → 活动提问 |
| EMail | 91 | mail.menu_mail_mail | admin | **未修**（noupdate 挡住，见 §6） |
| IAP | 81 | iap.iap_root_menu | admin | **未修**（同上） |

### 3.2 页面面（真浏览器渲染）

| 页面 | 改前 | 改后 |
|---|---|---|
| `/odoo/action-649` 在线测验 | title=**Quiz**；顶栏 **Quizzes / Attempts**；列 **Quiz Name / Category / Course / Total Points / Duration (min) / State**；徽章 **Published**（共 8 项） | title=**在线测验**；顶栏 在线测验 / 作答记录；列 测验名称 / 分类 / 课程 / 总分 / 时长（分钟）/ 状态；徽章 已发布（**0 项**） |
| `/odoo/action-650` 作答记录 | title=**Quiz Attempts**；列 **Quiz / Student / Score / Total Points / Percentage / State**（共 6 项） | title=**作答记录**；列 在线测验 / 学生 / 得分 / 总分 / 百分比 / 状态（**0 项**） |
| `/odoo/action-649/1` 在线测验**记录表单** | 字段标签 Question / Qtype / Option A-D / Correct Answer / Points / Answers 全英文 | title=**计算机基础入门测验**，**0 项**（22 条字段标签已落库） |
| `/odoo/students` 学生 | 干净（仅出现 `stu@local` 等邮箱，分类器判 `data`，不是文案） | 干净 |
| `/odoo/batches` 班级 | 干净 | 干净 |
| `/odoo/apps` 应用（模块看板） | **32 项英文**（见 §6.3） | **32 项**（未修，超出本卡边界） |

前后截图（人眼可复核）：

| 图 | 文件 |
|---|---|
| 改前 在线测验列表 | `shots/admin_Quizzes.png`（18:36 采集，早于修复） |
| 改后 在线测验列表 | `shots/after-desktop_quiz-list.png` |
| 改后 作答记录 | `shots/after-desktop_quiz-attempts.png` |
| 改后 手机 390×844 | `shots/after-mobile_quiz-list.png` |
| 改后 模块看板（英文残留） | `shots/after-desktop_odoo-apps-modules.png` |

### 3.3 人眼复核才看得见的问题（DOM grep 抓不到，机械门禁更抓不到）

**① 区段导航栏是一整条 18 项平铺、且大量重名 —— 「功能折叠/藏太深」的真实形态**

从截图原样抄下的顶栏（admin，在线测验页）：

```
时间表  作业  考试  时间表  考勤  在线测验  作答记录  课次管理  周期排课（批量）停课管理  校历活动  配置  报告  学习进度  配置  报告  配置  配置
```

- **「时间表」出现 2 次、「配置」出现 4 次、「报告」出现 2 次**，且互不从属、没有分隔或分组标题；
  用户无法从字面判断哪个「配置」是哪一块的配置（对应调研 `docs/research/ui-usability-discoverability.md` 的 D4「只能靠记忆」）。
- 这是 Odoo 的 `o_menu_sections` 扁平渲染：**同一应用下多个子树的同名叶子被压平到一行**。
- 属于「措辞与层级割裂」，修它要动各模块 `menuitem` 的命名/分组（多个模块的 views，超出本卡写作用域）⇒ 见 §7 移交。

**② 手机端（390×844）列被截断，需要横向滚动**

- 在线测验列表在 390px 下只露出 测验名称/分类/课程/总分，「时长」「状态」被切在屏幕外（截图 `after-mobile_quiz-list.png`）。
- 这正是 `check_ui_usability.py` 的「横向溢出」轴要抓的东西 —— 但**它的 148 页名单全是门户页，后台 0 覆盖**。
- 这是 §2 那条结构性盲区的**可复现后果**：门户有尺子，后台没有。

**③ 模块看板暴露「启用/升级」按钮，对学校是危险面**

- `/odoo/apps` 列 67 个模块，其中 销售 / 餐厅 / 发票 / CRM / MRP II / 库存 / 会计 等**带「启用」「升级」按钮**；
  点一下就会真的装 ERP 模块。对只有 4 类身份的学校教务系统，这是无关却高危的入口。
- 左侧「类别」筛选里 **Education** 是英文，与同列的 销售/网站/服务台/会计 混排。

---

### 3.4 补记（2026-10-02 晚，队长复量）：§3.3 的 ② 与 ③ **是「管理员面」的问题，不是学校职工面**

本轮想接着修 §3.3 的遗留，于是**先复量再动手**，结论与原报告的口径有重要差别 ——
原报告的取证身份是 **admin**（见 §1.1），下面补上「**非管理员**看到什么」这一半。

**（1）`/odoo/*` 对非管理员是打不开的 —— 会被重定向到 `/apps`**

实测（`backoffice@local` 教务专员、390×844）：

```
GET /odoo/quiz.quiz     status=200  →  落地 URL: /apps
GET /odoo/op.student    status=200  →  落地 URL: /apps
（页面文本 = 门户应用面板：帮助 资料下载 教务审批 财务管理 … 修改密码）
```

⇒ **§3.3② 「手机端后台列表被截断」对教务/教师不可达** —— 他们根本进不去那个列表。
而这是**有意设计**：`edu_portal/controllers/main.py:330` 有 `redirect('/apps', code=302)`，
code-map §6 也把「点进去落到 `/apps` 应用面板」登记为**权限缺口的已知症状**，
并写明处置是「把菜单收回到它真正需要的功能组 + 超管」，**不是**给教务补功能组。
（这也解释了 §3.3② 点出的那条结构性事实：`check_ui_usability.py` 的名单全是门户页 ——
在「非管理员不进后台」这个设计下，那不是漏扫，而是**画对了范围**。）

**（2）§3.3③ 的「危险面」对非管理员不成立**

实测（教务专员 / 教师，访问 `/odoo/apps`）：**「启用/升级」按钮数 = 0**。
即 Odoo 只对 `base.group_system` 渲染那些按钮 —— 危险面**只对管理员存在**，而管理员本就能做任何事。

另查：`应用`(id=15/48)、`主要应用`(49)、`第三方应用程序`(51)、`更新应用程序列表`(53)
这些菜单**都挂在「角色 / 管理员」组**下（`edu_nav/data/menu_consolidation_data.xml:427-451`，
注释写明「根+子树一起挂超管组」）⇒ 非管理员的**菜单里根本看不到「应用」**；
他们能打开 `/odoo/apps` 只是因为知道 URL，且打开后是**只读目录、无按钮**。

**（3）残留（低，供裁定）**：非管理员直连 `/odoo/apps` 仍能看到 67 个 ERP 模块目录
（销售/会计/人力资源/营销…）。无按钮、无害，但对学校身份而言是**噪音**。
若要关掉，做法是把 `base.menu_ir_property` 那条动作的组也收一次（另开卡，属产品口径）。

⇒ 结论：**§3.3 ②③ 不作为待修项**；① （18 项重名区段导航）**本机无 admin 口令，无法复现**，
维持原报告的「移交」状态。

## 4. 修复清单（明确项）

**改动只落在 `custom_addons/edu_zh/i18n_extra/{zh_CN,zh_TW}.po`**（写作用域内），
**不改基座 `openeducat_erp/`、不改 Odoo 核心、不改 `edu_portal`**。做法沿用本仓既有约定：
词条**按 xmlid 定点覆盖**（`#: model:...` 引用行），不按 msgid 全局生效。

### 4.1 数量

| 项 | 数量 |
|---|---|
| 新增词条（zh_CN） | **39 条**（zh_TW 同步 39 条） |
| 引用行 | 44 条/语言（一条词条可挂多个 xmlid，如 State 同时覆盖两个字段） |
| **落库并改变的记录** | **40 条** = 菜单/动作 10 + 字段标签 22 + 选择值 8 |

### 4.2 落库实物复核（psql 直读，不信用日志）

```
字段标签  22 / 22 已落 zh_CN
选择值     8 /  8 已落 zh_CN
菜单+动作 12 条目标里 10 条已变为目标中文（余 2 条见 §6）
```

举例：

```
edu_quiz.menu_edu_quiz                       Quizzes          -> 在线测验
edu_quiz.menu_edu_quiz_attempts              Attempts         -> 作答记录
edu_quiz.action_edu_quiz                     Quiz             -> 在线测验
edu_quiz.field_edu_quiz__duration            Duration (min)   -> 时长（分钟）
edu_quiz.field_edu_quiz_question__answer     Correct Answer   -> 正确答案
edu_quiz.selection__edu_quiz__state__published  Published     -> 已发布
event.event_question_action                  Event Question   -> 活动提问   （原机翻「事务问题」）
```

### 4.3 顺带修掉的「标签与实际不符」

| 位置 | 原文（机翻） | 改为 | 为什么不符 |
|---|---|---|---|
| 事件提问动作 512 | **事务问题** | 活动提问 | `Event Question` 的机翻是「事务问题」（transaction problem），与「活动提问」毫无关系 |
| 在线聊天 511 | Looking for Help | 待接入咨询 | 这就是「等待人工接入」的会话队列 |
| 在线聊天 510 | All Conversations | 全部会话 | 对照 511 才有意义（全部 vs 待接入） |

### 4.4 选词依据（不是随手翻）

- 「在线测验」= 门户页自己的标题（`edu_quiz/views/edu_quiz_portal_views.xml` 的 `<h2>在线测验</h2>`），
  后台与门户**用同一个词**，避免同一功能两个名字；
- 「作答记录」= `edu_quiz/models/models.py` 文件头自述「测验 / 题目 / 作答记录」；
- 其余按「该字段在这张表单上的职责」直译（`State`→状态、`Total Points`→总分、`Percentage`→百分比）。

### 4.5 白名单：**本轮新增 0 条**

`check_english.py` 的 `WHITELIST`（品牌名/口号/Zoom/English/EN/Telegram）**一个字没动**。
本轮 39 条词条里没有任何一条走「豁免」：全部是真译文。
为通过而放宽判据的事，本轮没有发生（见 §5 的反向自证）。

---

## 5. 过程中的两个真实坑（都是「证据纪律」救回来的）

### 5.1 我一度把整个后台搞挂了，根因是 PO 的一条**运行时硬要求**

第一版词条我只写了 `#:` 引用行，没写 `#. module: <模块>`。结果：

```
GET /web/webclient/translations -> 500
浏览器控制台: Error while fetching translations
症状: /odoo 仍返回 200，但 Web 客户端**白屏**（什么都渲染不出来）
```

根因（读容器内源码定位）：`odoo/tools/translate.py` 的 `CodeTranslations.__iter__`

```python
match = re.match(r"(module[s]?): (\w+)", entry.comment)
_, module = match.groups()        # entry.comment 为空 -> match=None -> AttributeError
```

**每一条 PO 词条必须带 `#. module: xxx`，这不是注释礼节，是运行时契约。**
补上后 `/web/webclient/translations` 恢复 **200（510345 字节）**。

> 这条值得写进仓规：它是**后者才会踩的坑**，而且失败信号极具误导性 ——
> 页面返回 200、后台却白屏，只有真打开浏览器才看得见。判据可离线自检：
> 每个词条块的第一个 `#.` 行必须匹配 `#. module(s): \w+`（本报告 §9 附了脚本）。

### 5.2 我的第一次反向自证**没变红**，因为读到了进程内缓存

第一次反向注入我用 `psql` 抹掉菜单 505 的 `zh_CN`，然后跑探针 —— 期望报红，**结果依旧是绿**。
原因不是判据失灵，是 `load_menus` 读的是**进程内缓存**：绕开 ORM 的 SQL 写入不会触发缓存失效。
**如果我当时就此收工，就会把一个「假绿」当成「已自证」。**
修正做法（§6.2）：注入后必须重启 web 清缓存，再跑探针 ⇒ 立刻报红。

---

## 6. 反向自证（三段，含未修项的负向对照）

### 6.1 正向 + 反向（已修的项，临时还原看是否报红）

```
[T0] 现状        menu 505 zh_CN = 在线测验
[T1] 反向注入    update ir_ui_menu set name = name - 'zh_CN' where id = 505;   -- en_US 回落 Quizzes
[T1b] 清缓存     docker compose restart web  （不清 = 假绿，见 §5.2）
[T2] 跑尺子    ⬇ 期望红，实测红
      menu 源命中：must-fix 1
        [MUST-FIX] 'Quizzes'   depth=1 id=505 edu_quiz.menu_edu_quiz
      汇总：探测项 1 ｜ must-fix 1
[T3] 还原        UPGRADE_EXTRA_ARGS=--i18n-overwrite bash scripts/safe_upgrade.sh edu_zh  -> EXIT=0
[T4] 再跑尺子  ⬇ 期望绿，实测绿
      menu 源命中：must-fix 0
```

⇒ 尺子的绿是**被修复动作造成的**，不是它自己恒绿。

### 6.2 控制组（未修的项，全绿说明判据不是恒红）

`/odoo/apps` 改前改后都有 32 条英文（§6.3），探针**照实报红**（`pages rc=2`）；
而同一份探针在已修页面上报 **0**（`pages rc=0`）。
⇒ 判据对「修好的」和「没修的」给出不同读数，不是恒红也不是恒绿。

### 6.3 我自己引入的缺陷也走同一把尺子

§5.1 那次后台白屏是我造成的，**不是靠门禁发现的，是靠真打开浏览器发现的**；
修好后 `/web/webclient/translations` 从 500 回到 200（`/odoo` 一直是 200，全程无法用状态码区分）。

---

## 7. 未修的明确项（已定位到根因，卡在写作用域之外）

### 7.1 两条英文菜单：`EMail`(91) 与 `IAP`(81) —— **Odoo 的 noupdate 规则结构性挡住**

这两条是 admin 侧仅剩的英文。我按 §4 的同一套词条投了，**但只有它们没生效**，
而 Odoo 源码里的规则**正好预测了这一点**：

`odoo/tools/translate.py` `save()`：

```
For a record with 'noupdate' in ir_model_data, its existing translations will be
overwritten if force_overwrite or (not noupdate and overwrite).
```

| 现象 | 记录 | 原因 |
|---|---|---|
| ✅ 生效 | `edu_quiz` 菜单 505/506（noupdate=**t**，但 zh_CN **为空**） | 走 insert 分支，不看 noupdate |
| ✅ 生效 | 其余 10 条（noupdate=**f**） | `not noupdate and overwrite` = True |
| ❌ 不生效 | `mail.menu_mail_mail`(91)、`iap.iap_root_menu`(81) | noupdate=**t** **且已有 zh** ⇒ 落在 keep-existing 分支 |

**这是一次干净的控制组**：源规则预测「只挡已有译文的 noupdate 记录」，实测**恰好只有那两条没生效**。

**为什么我没修**（不是不管，是修不了）：

1. 本仓对这类记录的既定修法在 `custom_addons/edu_portal/models/menu_labels.py` —— **`edu_portal` 不在本卡写作用域**；
2. 正确的家是 `edu_nav`（仓规明写它是「菜单收口的唯一落地处」），**但 `edu_nav` 今天升不动**：

```
bash scripts/safe_upgrade.sh edu_nav   -> EXIT=255
AssertionError: The ID "account_payment.payment_provider_menu" refers to an uninstalled module
  while parsing .../edu_nav/data/menu_consolidation_data.xml:1817
```

   即「菜单收口的唯一落地处」**当前无法加载** ⇒ **所有菜单类改动都被结构性阻塞**（这是本卡外的一个更大问题，见 §8）；
3. 该数据文件仓规明写「由 `scripts/gen_menu_data.py` 生成，**禁止手改**」，生成器与计划 JSON 都在写作用域外。

**对用户的实际影响：可忽略** —— 这两条都在 `设置 → 技术` / `网站 → 技术` 下，**仅超管可见**；
教务与教师侧英文已清零。

### 7.2 `/odoo/apps` 模块看板：32 条英文

内容：13 个 OpenEduCat 模块的**英文名 + 英文一句话说明**（如 `OpenEduCat Core / Manage Students, Faculties and Education Institute`，
其中 `Manage Assgiments` 还是基座自己的拼写错误）+ 类别筛选里的 `Education` + `POS`。

**为什么不修**：这些文案的所有者是 `openeducat_erp/*/__manifest__.py`（**基座快照，仓规「原则上不改」**）；
要改就得对 `ir.module.module` 的 `name` / `summary` 出 PO（需先核实其 xmlid 形态），属**另一条独立改动线**。

---

## 8. 移交（不在本卡边界内，写清楚给下一手）

| # | 事项 | 为什么移交 | 建议落点 |
|---|---|---|---|
| H1 | **`edu_nav` 升不动（exit 255）**：`menu_consolidation_data.xml` 引用了 5 个未安装模块的 xmlid（`account_payment` / `hr_skills_slides` / `website_livechat` / `website_slides` / `website_slides_forum`） | 生成器与计划 JSON 都在本卡写作用域外；且仓规禁止手改生成物 | 前置条件见 `docs/audit/menu-consolidation/deploy-shipping-gap.md`；**它是菜单类改动的前置阻塞项** |
| H2 | 两条 noupdate 菜单（§7.1） | 需 `edu_portal`/`edu_nav` 写权 | 照 `edu_portal/models/menu_labels.py` 先例：规范 noupdate=False → 再走 PO；H1 修好后放 `edu_nav` 更合适 |
| H3 | `/odoo/apps` 模块看板 32 条英文 + 「启用/升级」按钮对学校是危险面（§3.3③） | 文案所有者是只读基座；「隐藏 API」涉及菜单收口（=H1） | 产品决策 + H1 |
| H4 | 区段导航栏 18 项平铺、重名（时间表×2 / 配置×4 / 报告×2，§3.3①） | 要动多个模块的 `menuitem` 命名与分组，跨模块 | 与 H1 同批做（菜单收口本来就管这块） |
| H5 | 手机端后台列表横向溢出（§3.3②） | 若要修，得改各模块 list 视图的列可见性/`optional`；且**先要有尺子** | 把 `check_ui_usability.py` 的横向溢出轴扩到后台页（注意：**必须先证明它能变红**，否则重复 §2.2 的假绿） |
| H6 | **PO 词条必须带 `#. module:` 的运行时契约**（§5.1） | 属仓规沉淀，建议写进 `docs/code-map.md` §6 | 判据脚本见 §9 |
| H7 | 门户侧问题（本卡明确不改 `edu_portal/**`） | 边界 | 本轮未发现新的门户问题；队长已有 `docs/audit/ui-visual-review/report.md`（8 条）与 task-9 在跟 |

---

## 9. 验收读数（命令 + 原样输出）

### 9.1 升级：EXIT=0、无 Traceback

```bash
UPGRADE_EXTRA_ARGS="--i18n-overwrite" bash scripts/safe_upgrade.sh edu_zh
```

```
EXIT=0
tracebacks: 0
[safe_upgrade] 就绪：/web/login?db=edu19 -> 302
[safe_upgrade] 结束：edu_zh（无失败特征；完整日志 /tmp/edu19_upgrade.20261002-190009.log）
```
（共跑 4 次 `-u edu_zh`，日志留档在 `/tmp/upg_*.log`：**18:49** 首次、**18:54** 补选择值、**18:57** 反向自证还原、**19:00** 补表单字段；**四次全 EXIT=0、0 Traceback**）

### 9.2 后台仍能正常打开

```
/odoo                        200  len=6890
/web                         200  len=6890
/odoo/action-649             200  len=6890
/web/webclient/translations  200  len=510345     <- §5.1 白屏事故的回归判据
/web/webclient/load_menus    200  len=169942
```

> ⚠ 提醒：`/odoo` 恒 200（空壳），**不能**当「后台正常」的判据。真正的判据是
> `/web/webclient/translations` 200 **且** 浏览器能渲染出 `o_main_navbar`（探针 `--pages` 会等到元素挂载才取样）。

### 9.3 门户英文门禁未受影响（控制组）

```
python3 scripts/check_english.py        -> rc=0
guest       must-fix 0    brand 0
student     must-fix 0    brand 0
faculty     must-fix 0    brand 0
parent      must-fix 0    brand 0
backoffice  must-fix 0    brand 0
TOTAL must-fix = 0 条 / brand = 0 条 / 路由状态违规 = 0 条 / 夹具残留 = 0 条
```

### 9.4 探针自身的读数是三态（红/绿/未判定），不是二态

| 场景 | 退出码 |
|---|---|
| must-fix = 0 | 0（绿） |
| 有 must-fix / brand | 2（红） |
| 登录失败 ⇒ **不判 FAIL，判 INCOMPLETE** | 3 |

另：探针在渲染时若等不到 Web 客户端挂载会记 `client_boot=timeout`，**不把空壳当绿**（这就是 §2.2 那次空壳读数的成因）。

---

## 10. 证据文件清单（全部在 `docs/audit/backend-ux/`）

| 文件 | 内容 |
|---|---|
| `backend_probe.py` | 探针本体（复用 `check_english.classify`；`--selftest` 15/15） |
| `evidence/menus_before.json` / `.txt` | 三角色菜单英文读数（改前，must-fix 14） |
| `evidence/menus_after.json` / `.txt` | 改后（must-fix 2，且这 2 条已定位到 noupdate 规则） |
| `evidence/pages_before.json` / `.txt` | 浏览器渲染读数（改前；在线测验页整页英文） |
| `evidence/pages_after.json` / `.txt` | 改后（列表页 ×2 + **记录表单页** 全部 0 英文，rc=0） |
| `evidence/control_check_english_blindness.json` | 控制组：同一 URL，`scan_body()` 命中 0 vs 浏览器 32 |
| `evidence/check_english_control_backend.txt` | 控制组：把后台登记进 english 门禁，它照样报 OK |
| `evidence/check_english_portal.txt` | 门户门禁全量读数（rc=0，未受影响） |
| `shots/admin_Quizzes.png` / `after-desktop_quiz-list.png` | 改前 / 改后 对照截图 |
| `shots/after-mobile_*.png` | 手机 390×844（横向溢出证据） |
| `shots/after-desktop_odoo-apps-modules.png` | 模块看板英文 + 启用/升级按钮 |

---

## 11. 本卡没做的事（边界声明）

- **没动** `custom_addons/edu_portal/**`（另一个 teammate 负责空状态）；本轮在门户侧也未发现新问题可移交。
- **没动** `openeducat_erp/` 基座快照与 Odoo 核心源码。
- **没动** `评估表格/`。
- **没做 git commit**（队长统一提交）。
- **没碰生产服务器**（`ssh prod-host` 一次都没执行）。
- **没有新增/放宽任何白名单**来通过门禁。
