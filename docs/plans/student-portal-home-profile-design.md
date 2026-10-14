# 学生门户「我的主页 ↔ 全部应用」合并 + 资料卡头像统一设计
> **状态**：`已上线` ｜ **主题**：`门户主页合并` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「仅设计（本次未写一行代码）」，实际已于 `6b47565` 交付（2026-09-26 核对发现）。正文未改动。

> **历史状态**：仅设计（第 0 步「落地前查重」+ 第 3 步「读参考」+ 第 4 步「设计摘要」）。
> **本文件不代表已实施**——本次**未写一行代码**、未新建模块、**未动 `custom_addons/`**、**未动 `openeducat_erp/`**、未动生产。
> **需求来源**：校长原话（需求 5 / 需求 6），见 §1.1。**队长追加指令（2026-09-18）**：需求 6 的「四项必填」**取消**，
> 只保留「头像统一」与「点卡片头像可直接改头像」两件事；**仍然禁止给任何字段加模型层 `required`**。
> **口径来源**：`docs/dev-workflow.md` 第 0 步与六步闸门 ｜ `docs/research/README.md`（调研索引）｜ `docs/plans/study-hub-v3-design.md`（`/my/apps` 的由来）
> **采集时刻**：**2026-09-18**；读数口径 = 本地库 `edu19`（只读 SELECT）+ 容器 `edu19-clone-web-1`（Odoo 19.0-20260817 源码）+ 仓内既有截图。
> **未验证项**一律集中写在 §12，**不得当结论用**（本仓规范）。

---

## 0. 结论速览（TL;DR）

| 项 | 结论 |
|---|---|
| **裁定（三选一）** | **合并（入口收口）**：唯一保留的学生门户首页 = **`/my/home`**，其内容改为「全部应用」界面（既有模板 `edu_portal.edu_dashboard_v2`）；`/my/apps` 对学生/家长 **303 → `/my/home`**；**对内部用户（教师/教务/管理员）`/my/apps` 保持 200 不变** |
| **为什么保留 `/my/home` 而不是 `/my/apps`** | 全仓活的 `/my/home` 引用 **118 处**（`request.redirect('/my/home')` **96** + `href="/my/home"` **22**），`/my/apps` 只有 **4 处**。反过来收口 = 118 处要么改、要么变成两级跳 |
| **头号重复对象** | **同一个「门户首页」有两套实现**：`batch2.py:1895`（Timeline 工作台 = 现 `/my/home`）与 `batch2.py:1945`（全量卡片宫格 = 现 `/my/apps`）。两者的卡片引擎、侧栏、顶栏、收藏契约**本来就是同一套**（`batch2.py:1949-1951` 作者自述） |
| **需求 6 病灶（已定位到行）** | 不是"没有头像"，是**同一页两种头像写法**：页头 = `t-if image_1920` + FA 人形兜底（**看着有头像**）；侧栏资料卡 = 裸 `<img src=.../image_256>`，空图时被 Odoo 换成 **灰底相机占位图**（**看着没有**）。见 §5.2 |
| **统一手段（能接就不造）** | **复用 Odoo 19 内置 `avatar.mixin`**：把两处都改成 `/web/image/res.partner/<id>/avatar_128`（空图时 Odoo 自动生成**姓名首字彩色头像**，实测 424 B SVG）；**统一数据源**为 `request.env.user.partner_id`（= 上传写入口 `avatar.py:22` 的那个 partner） |
| **点卡片头像改头像** | **零新路由、零新 JS**：把卡片 `<img>` 包成 `<button data-bs-toggle="modal" data-bs-target="#b11-avatar-modal">`——该弹窗**已在同页**（`edu_page` 外壳 `edu_portal_templates.xml:90-116`），提交仍走既有 `POST /my/avatar/upload` |
| **四项必填（学号/年龄/性别/Telegram 昵称）** | **本轮取消**（校长裁定）。设计稿仍逐条给出**现状结论与写入口证据**（§5.3），供后续需要时一次性决策 |
| **独立缺口（队长指定必答）** | **学生门户里没有任何地方能填 学号 / 出生日期 / 性别**（路由级证据见 §6）。是否补入口**不在本次范围**，请队长裁定 |
| **升级风险** | `-u edu_portal` **不写任何业务表**（`data` 里只有 2 处 `<function>`，都是改 `ir.ui.menu` 的 group_ids）；本次不需 migration、不新增演示数据（§7） |
| **待校长拍板** | **4 项**（入口名 / 旧主页「待办三桶」留不留 / 无照片时的默认头像样式 / 学号可见性），见 §11 |

---

## 1. 需求、目标、非目标

### 1.1 需求原文（校长）

- **需求 5**：「学生端的『我的主页』我希望直接改成『全部应用』这个界面，一目了然。把他们俩合并，原先的『我的主页』这一页不要了。全部应用被合并入我的主页。」
- **需求 6**：「该图当中的这个头像应该统一（右上角有头像，下面那个没有）。我希望当用户点击下面这个头像的时候，可以直接修改头像。」+（原提「学号/年龄/性别/Telegram 昵称必填」，**已由校长裁定取消**）
  配图：学生**王佐**的门户页面截图——顶部搜索框 + 右上角头像；主区一张资料卡：圆形相机占位头像、姓名「王佐」、两个标签「人文一年级」「教育学士」、按钮「编辑资料」、链接「修改密码」。

### 1.2 目标（本设计只覆盖这两件）

| # | 能力 | 用户感受 |
|---|---|---|
| G1 | 学生端只剩**一个**门户首页，且是「全部应用」那种一眼看完的界面 | 不再有"两个首页、功能各半" |
| G2 | 资料卡头像与页头**永远一致**，且点资料卡头像**直接改头像** | 头像不再是"上面有、下面没有" |

### 1.3 非目标（明确不做）

- **不加任何模型层 `required`**（队长指令，禁止项）。
- **不改 `openeducat_erp/`**（只读快照）。
- **不动内部用户（教师/教务/管理员）的门户**：校长说的是「学生端」；教师 `/my/home` 仍是教师工作台（`edu_dashboard_teacher`），教师 `/my/apps` 仍是卡片页。
- **不做"学生档案字段填写入口"**（§6 只给证据与选项，做不做由队长裁定）。
- **不删任何路由/记录**（本仓红线：只隐藏 / 迁移 / 重定向）。

---

## 2. 第 3 步「读参考」的调研回引（铁律 0）

> 本次**不新增调研文件**：两个页面都是**本仓已实现**的东西，不是外部对标；需要"读参考"的是 **Odoo 19 核心源码**（§4）与**本仓既有约定**。
> 索引已读：`docs/research/README.md`（收录规范 + 6 篇条目 + 2 篇历史调研）。

| 回引 | 与本设计的关系 |
|---|---|
| [`docs/research/onestop-learning-and-repetitive-work.md`](../research/onestop-learning-and-repetitive-work.md) §1（"下一步该做什么"= Moodle Timeline 三桶）/ §4（国内同类：钉钉工作台式宫格） | `/my/home`（Timeline）与 `/my/apps`（宫格）**同源于这篇调研的两条不同结论**。合并 = 在二者之间做一次取舍：**保留宫格为主体**，Timeline 的独有内容单列（§8.3） |
| [`docs/research/ui-design.md`](../research/ui-design.md) §3.3（Odoo 19 的**QWeb 模板字面量** SCSS 够不到）/ §4（`--bs-*` 前缀为空、令牌桥接） | 头像与卡片的样式改动**只在模板 + 既有 CSS 类**上做，不碰 SCSS 变量体系；新样式若必须加，走 `custom_home.css` 既有 `.b11-*` 命名族 |
| [`docs/research/invite-code-tiers.md`](../research/invite-code-tiers.md)（层级码注册直接建 `op.student`，只写 partner/gender/user） | **解释了"为什么必然有学生没有学号/生日"**：层级码建出的档案只有 `partner_id + gender + user_id`（`edu_portal/models/invite_code.py:353-356`）⇒ 任何"字段必填"都只能落在门户表单层（§5.4） |
| [`docs/audit/peer-research.md`](../audit/peer-research.md)（同类系统辅助功能调研，历史档案） | 结论：同类系统均允许"先有账号、后补档案"，**没有**把学号/生日做成注册硬门槛的先例 ⇒ 支撑"不锁死入口、只做提示"的方向 |
| Telegram Bot API：官方 [Bot API](https://core.telegram.org/bots/api) 的 User 对象（`first_name` 必带；`last_name` / `username` 可选），镜像佐证 [python-telegram-bot User](https://docs.python-telegram-bot.org/en/stable/telegram.user.html) | 「Telegram 昵称」的**唯一可能来源**是 bot 收到的名字（§5.3-④）。⚠ 官方页本次抓取失败（`fetch failed`），标注见 §12-2 |
| `docs/plans/study-hub-v3-design.md` §4/§5（`/my/apps` 是 t6 新建的"全量卡片目录"）、§6（零功能丢失对照表） | **本设计修订它的 IA 结论**：v3 当时的取舍是「首页瘦身成 Timeline、全量卡片迁往 `/my/apps`」；校长现在要求**反过来**——首页就是全量卡片。§6 的对照表可直接复用为"零功能丢失"清单 |

**学什么 / 砍什么（一句话）**：**学** Odoo 核心自带的「头像回退」与「门户侧栏」范式（`avatar.mixin`、`portal.side_content`）；**砍**我们自造的第二种头像写法（裸 `image_256`）与两套首页壳。

---

## 3. 第 0 步①：先信 code-map

| 位置 | 内容 | 对本设计的含义 |
|---|---|---|
| `docs/code-map.md` §4 `edu_portal` 段 | 「`controllers/main.py`：/my 重定向、**/my/home 首页分发**（学生卡片页 / 教师工作台分支）」；「`controllers/batch2.py`：**首页卡片引擎**（`_YONGYUE_CARDS` + `cards()`）」 | 两处描述**已经是"旧口径"**（v3 后 `/my/home` 是 Timeline、卡片在 `/my/apps`）⇒ 实施时须同步 §4/§5（本次不改 code-map） |
| `docs/code-map.md` §4 `edu_portal` 段（v3 一条龙） | 「`views/study.xml`…`edu_home_timeline`」 | Timeline 模板落在 `study.xml`，**不在 batch2.xml**（影响面评估要点） |
| `docs/code-map.md` §5 路由速查 | 「学生门户 `/my/home, /student/*, /my/*`（batch1/2/3.py）」 | 合并后路由族不变，只是 `/my/apps` 降级为兼容层 |
| `docs/code-map.md` §6 / `docs/dev-workflow.md`「陷阱 2」 | 「改了路由 ⇒ 必须有**一条"打完就摸页面"的判据**；探针**不许跟随重定向**」 | §10 的验收全部写成 `allow_redirects=False` + `Location` 精确匹配 |
| `docs/dev-workflow.md` 第 0 步③ | 「没有『既有实现对照』这一节的 design **不进入第 4 步**」 | 本文 §5 即该节 |
| `docs/audit/deprecated-inventory.md` §4「台账 C：URL 级兼容层」 | 「旧地址不 404 ⇒ **实现必须留着**；删掉重定向 = 用户书签 404」 | `/my/apps` 的 303 属这一类，须登记（§9 已登记） |

---

## 4. 第 3 步：读参考（Odoo 19 核心源码，行级取证）

> 容器内源码路径：`/usr/lib/python3/dist-packages/odoo`（Odoo **19.0-20260817**）。
> ⚠ 本仓合规红线：**基座源码只给路径 + 行号，不贴进仓库**。

### 4.1 头像：Odoo 19 自带"无图回退"，我们不必自造

| # | 事实 | 位置（路径 + 行号） | 结论 |
|---|---|---|---|
| R1 | `avatar_1920`…`avatar_128` 是 **computed（不落库）** 字段，由 `image_1920` 派生 | `base/models/avatar_mixin.py:29,32-34` | 用 `avatar_*` 就自动拿到缩略图，**不需要**自己写 `image_128/256` 两套 URL |
| R2 | 空图时：**有 id 且有 name** ⇒ 生成 SVG 头像（姓名首字 + 由 name/create_date 派生的 HSL 底色）；否则用占位图 | `base/models/avatar_mixin.py:35-42`（`_compute_avatar`）、`:66-77`（`_avatar_generate_svg`）、`:76-80`（占位图路径 `base/static/img/avatar_grey.png`） | **"无照片也有头像"是核心行为，不是我们的需求**——直接用即可 |
| R3 | 但裸 `image_128/image_256` **没有**这层回退：`/web/image` 对空值返回 `web/static/img/placeholder.png`（灰底相机+"+"） | 实测：`curl /web/image/res.partner/35/image_256` → 200 / **6078 B**（与容器内 `web/static/img/placeholder.png` 字节数一致）；截图放大见 §5.2 | 这就是校长看到的"相机占位头像" |
| R4 | ORM 层实测同一 partner：`image_1920`/`image_128` **为空**；`avatar_128`/`avatar_256` = **424 B 生成 SVG** | `odoo shell -d edu19` 只读读字段（命令见 §5.2 证据栏） | 换成 `avatar_*` 后**必然**从"灰相机"变成"彩色首字头像" |
| R5 | 核心自己的门户侧栏也用 `avatar_128` | `portal/views/portal_templates.xml:718-737`（`portal.side_content`：`t-att-src="image_data_uri(user_id.partner_id.avatar_128)"`、name、"Edit information" → `/my/account`） | **我们的资料卡就是它的仿制品**（`batch2.xml:1109` 注释自述"对齐原站 oe-sidebar"）⇒ 统一方向就是**回到核心那种写法** |

### 4.2 「编辑资料」到底是什么页（回答队长问题 2 / 问题 3 的前半）

| # | 事实 | 位置 | 结论 |
|---|---|---|---|
| R6 | 门户 `编辑资料` 按钮指向 `/my/account` | `custom_addons/edu_portal/views/batch2.xml:1144`（`href="/my/account"`）；全仓**只有这一处**「编辑资料」 | 见 §5.2-#9 |
| R7 | 核心 `/my/account` → 模板 `portal.portal_my_details` | `portal/controllers/portal.py:190-193`、`:201-215` | 是**核心页**，不是我们的 |
| R8 | `portal.portal_my_details` = **地址表单**（POST 到 `/my/address/submit`，AJAX/JSON 机制） | `portal/views/address_templates.xml:407-431`；处理函数 `portal/controllers/portal.py:466-490`（`portal_address_submit` → `_create_or_update_address`） | Odoo 19 把"我的详情"重写成了**地址簿机制**，扩展点比旧版（`op=details` 表单）更绕 |
| R9 | 表单字段全集 = `name/email/phone/company_name/vat/street/street2/zip/city/country_id/state_id` + 隐藏 `required_fields='name,email'` | `portal/views/address_templates.xml:165,179,189,208,221,260,274,288,299,325,356,383` | **一个 `op.student` 字段都没有** |
| R10 | 我们只改了其中 3 个**标签**：`company_name→院系`、`vat→年级`、`street2→学制` | `custom_addons/edu_portal/views/partner_labels.xml:4-15`（t-inherit `portal.address_form_fields`）；模型级同名字段在 `models/partner_edu.py:17-20` | ⇒ 校长截图里"院系/年级/学制"是**我们的标签 + 核心的 res.partner 字段**，**与学籍无关** |

### 4.3 基座（OpenEduCat）字段事实复核（队长给的线索逐条复验）

| # | 线索 | 复核结果 | 位置（`openeducat_erp/`，只给路径+行号） |
|---|---|---|---|
| R11 | 学号 `roll_number` 在 `op.student.course` 上 | ✅ **成立** | `openeducat_core/models/student.py:25`（`class OpStudentCourse`）→ `:31 student_id` / `:33 course_id` / `:35 roll_number`；三条唯一约束 `:43-51`（含 `unique(roll_number,course_id,batch_id)`） |
| R12 | 生日字段真名 `birth_date`（挂 `op.student`） | ✅ **成立** | `:70 birth_date = fields.Date('Birth Date')`；约束 `:136-141 _check_birthdate`（不得晚于今天） |
| R13 | 性别 `gender` 在 `op.student` | ✅ **成立**，且**本来就是 `required=True, default='m'`** | `:81-85`（Selection `m/f/o`） |
| R14 | `op.student` 是 `_inherits = {'res.partner': 'partner_id'}`（委托继承） | ✅ | `:61-65`；`name/email` 是 related（`:103-104`）⇒ 门户改 name/email 就是改 partner |
| R15 | 学号还有**第二个**候选：`op.student.gr_no`（"Registration Number"，unique） | ✅ **线索漏了这条** | `:93 gr_no`、`:106-107 _unique_gr_no`；`size=20` |
| R16 | 基座有没有 `enrollment_number / student_number / age` 之类字段 | ❌ **没有** | `grep -rn "enrollment_number\|enrolment_number\|enroll_no\|student_number" openeducat_erp/` → 只命中 `student.py:93/107` 的 "Registration Number"；`grep "age = fields\\|fields.Integer('Age'" openeducat_erp/` → 0 命中（仅 `grade_weightage`/`percentage` 之类误命中） |
| R17 | `create_student_user()` 会给学生建账号且 `partner_id = record.partner_id` | ✅ | `:161-174` ⇒ **正常路径下学生档案与账号同 partner**（"分裂"是例外，见 §5.2-#10） |

---

## 5. 第 0 步②：既有实现对照（逐条：查了什么 / 命令 / 命中 / 为什么不复用）

> 规矩：**"没找到"也要写清搜索范围与方式**；**不允许"我记得没有"**。
> 本节命令均在 2026-09-18 实跑；DB 读数只读 SELECT。

### 5.1 需求 5：门户首页查重（两条路由 + 两套模板）

| # | 查了什么 | 命令 / 方式 | 命中（行号） | 结论（复用/合并/新建） |
|---|---|---|---|---|
| 1 | 全仓 `/my/home` 引用 | `grep -rn "/my/home" custom_addons/` | **152 命中**；其中活代码 `request.redirect('/my/home')` = **96**、模板 `href="/my/home"` = **22** | **URL 必须保留**（`学习 hub` 的 118 处落点） |
| 2 | 全仓 `/my/apps` 引用 | `grep -rn "/my/apps" custom_addons/` | **6 命中**：路由 `controllers/batch2.py:1945`；侧栏 `views/edu_portal_templates.xml:153`；快捷入口 `controllers/batch2.py:1005`；注释 `batch2.py:1923`、`study.xml:252`、`main.py:214` | 改造成本极低 |
| 3 | `/my/home` 的**生效实现** | 读 `controllers/main.py:107` 与 `controllers/batch2.py:1895`（Odoo 路由叶子类机制） | `main.py` 的同名路由**被 batch2 的子类覆盖**（`batch2.py:1585-1586` 自述；`main.py:107` 是**旧实现残留**） | 合并只改 batch2 一处；`main.py` 不动（登记为"被覆盖的旧实现"） |
| 4 | `/my/home` 的学生分支渲染什么 | 读 `batch2.py:1908-1943` | 学生/家长 → `edu_home_timeline`（`views/study.xml:254-326`：今日课节 / 待办三桶 / 我的课程≤3 / 快捷入口≤8） | Timeline 的**独有内容**只有「待办三桶」+「我的课程≤3」（§8.3） |
| 5 | `/my/apps` 渲染什么 | 读 `batch2.py:1945-1977` + `views/batch2.xml:663-840` | `edu_dashboard_v2`：迷你头部（`:672-676`，头像用 `avatar_256`）+ 今日课表预览（`:693-721`）+ 欢迎 hero + 统计卡 + 全量分类卡片 + `t-call edu_sidebar`（`:833`） | **它就是校长想要的界面**⇒ 合并 = 让 `/my/home` 渲染它 |
| 6 | 两个页面的卡片引擎是不是同一套 | `batch2.py:1949-1951` docstring + 读 `_home_categories`/`_build_favorites` | 作者自述"刻意复用同一套卡片引擎与模板 ⇒ `o_portal_index_card` 标记、`[data-fav-grid]` 收藏契约与 `home_favs.js` 收藏编辑照旧可用" | **零功能丢失的现成保证**：合并后收藏/角标/分类**不需要重做** |
| 7 | 旧首页（`main.py:62-116` 的 `_dashboard_cards` + `edu_dashboard` 模板）是否还在用 | 读 `main.py:107-116`、`views/edu_portal_templates.xml:229-258` | 模板 `edu_dashboard` 仍存在，但 `/my/home` 已被 batch2 覆盖 ⇒ 该模板**只被旧路由引用**（实际不可达） | **不动**（零删除红线）；实施时在注释里标注"已被 v3 取代"，不删模板 |
| 8 | 有没有"第三套"门户首页 | `grep -rn "edu_dashboard\|edu_home_timeline" custom_addons/` | `edu_dashboard`(旧) / `edu_dashboard_v2`(=/my/apps) / `edu_dashboard_teacher`(=/my/home 教师分支) / `edu_home_timeline`(=/my/home 学生分支) | **共 4 个模板、2 个活路由**：合并后学生侧只剩 `edu_dashboard_v2` |
| 9 | 内部用户的 `/my/apps` 是谁在用 | 读 `batch2.py:485-495`（`internal` 常用区含 `openeducat/apps_menu`「应用面板·全部应用入口」）+ `main.py:204-224`（`/apps` 与旧路径都 303 回 `/my/home`） | 教师/教务/管理员在门户**只有** `/my/apps` 能看到分类宫格 | ⇒ **303 只能对学生/家长生效**，否则误伤内部用户（§8.1） |

**没找到（负结论）**：

| 负结论 | 搜索范围与方式（原样可复现） |
|---|---|
| 全仓没有第三个"门户首页"路由 | `grep -rn "auth='user'\|auth=\"user\"" custom_addons/*/controllers/*.py` 里逐条筛 `website=True` 的首页型路由；再对照 `docs/code-map.md` §5 路由速查 |
| 没有任何 v3 后的文档把 `/my/apps` 写成"将被合并" | `grep -rn "my/apps" docs/` → 命中 `docs/plans/study-hub-v3-design.md`（新建时的设计）、`docs/code-map.md`、`tests/`；**无一**提到合并 |
| 没有既有的「首页 → 应用面板」收口先例可抄 | `grep -rn "303.*my/home\|redirect('/my/home'" custom_addons/edu_portal/controllers/main.py` → 只有"未登录/非内部用户回首页"，**没有"首页互相合并"的先例** ⇒ 本设计是第一次 |

### 5.2 需求 6：头像查重（四种写法 + 两个 partner 源）

**查了什么 / 命令**：`grep -rn "image_128\|image_1920\|image_256\|avatar_" custom_addons/`（命中 11 处，逐条读上下文）。

| # | 位置（行号） | 现在怎么写 | 空图时的实际表现 | 判定 |
|---|---|---|---|---|
| 9 | `edu_portal/views/edu_portal_templates.xml:67-73`（**页头**，出现在所有门户页） | `t-if="request.env.user.partner_id.image_1920"` → `/web/image/res.partner/<uid.partner>/image_128`；`t-else` → `<i class="fa fa-user-o"/>`（`.b11-user-avatar` = 蓝渐变圆底，`custom_home.css:547-552`） | **看着"有头像"**（蓝底人形） | ✅ 保留语义，但**源码要换成 `avatar_128`**（否则有图时它和卡片一致、无图时却不一致） |
| 10 | `edu_portal/views/batch2.xml:1114-1116`（**侧栏资料卡**，只在 `/my/apps`） | 裸 `<img src="/web/image/res.partner/<partner>/image_256">`，**无 `t-if`** | `/web/image` 返回 `web/static/img/placeholder.png`（**灰底相机 + "+"**，实测 6078 B） | ❌ **病灶**（校长的"下面那个没有"） |
| 11 | `edu_portal/views/batch2.xml:674`（apps 页迷你头部） | `avatar_256` | Odoo 生成**姓名首字彩色头像**（实测 424 B SVG） | ✅ 已经是正确写法（**同页两种写法并存**，这就是"不统一"的直接证据） |
| 12 | `edu_portal/views/messages.xml:70,104`；`contacts.xml:28` | `avatar_256` | 首字彩色头像 | ✅ 保持 |
| 13 | `edu_portal/views/roles.xml:17`（家长看孩子）、`edu_public/views/edu_public_views.xml:253`（公开页学生墙） | `image_256` | 灰相机占位 | ⚠ 同族问题（**不在本次范围**，登记在 §9 唤醒条件） |
| 14 | 头像**上传**入口 | `controllers/avatar.py:15-25`（`POST /my/avatar/upload`，写 `request.env.user.partner_id.image_1920`）；弹窗 `edu_portal_templates.xml:90-116`；入口 `:81`（用户菜单「修改头像」） | 只改**账号 partner** | ✅ **完全复用**：卡片只需把 `<img>` 包成 `<button data-bs-toggle="modal" data-bs-target="#b11-avatar-modal">`——弹窗**已经在同一页**（`edu_page` 外壳），**零新路由、零新 JS** |
| 15 | 卡片头像的数据源 | `batch2.py:1705`：`partner = student.partner_id if student else None`（供 `edu_sidebar`） | 读的是**学生档案的 partner**；而上传写的是**账号的 partner** | ❌ **两个源可能不是同一条记录**（见 #16） |
| 16 | 本地库实测"分裂" | `select s.partner_id, s.user_id, u.partner_id from op_student s join res_users u on u.id=s.user_id;` | → `35 / 8 / 38`（全库唯一一个可登录学生：**档案 partner 35 ≠ 账号 partner 38**，两条 partner 同名"王小明"、"王小明"） | ⇒ 若卡片继续读 `student.partner_id`，**上传成功也不会生效**（用户会再报一次"改了没用"） |
| 17 | 两种写法的字节级证据 | ① `curl /web/image/res.partner/35/image_256` → **6078 B**（= 容器内 `web/static/img/placeholder.png` 大小）；② `odoo shell` 读 `browse(35)`：`image_1920/image_128` **空**、`avatar_128/avatar_256` = **424 B**；③ 仓内截图 `shots/local/smoke_08b_my_apps.png` 放大后可见"灰相机 + 蓝+" | 三条互相印证 | 结论：**不是没数据，是取图路径不同** |

**为什么"线索里没命中『编辑资料』『修改密码』"——我方复核结果是命中的（把搜索方式写清）**：

| 串 | 我方实跑结果 | 说明 |
|---|---|---|
| `编辑资料` | **1 命中**：`custom_addons/edu_portal/views/batch2.xml:1145` | 全仓搜（无 include 过滤，覆盖 `custom_addons/ openeducat_erp/ docs/ scripts/ tests/`）；**只在 .xml 模板里**，任何"只搜 `*.py`"或"只搜控制器"的方式都会漏 |
| `修改密码` | **8 命中**：`views/batch2.xml:855`（"我的课程"页顶部链接）、`:1148`（**资料卡上的链接**）、`views/my_password_views.xml:8`、`controllers/my_password.py:17`、`scripts/gen_manual.py:69,71,251`、`tests/smoke/ux_v3_route_matrix.py:123` | 其中**只有 `:1148` 是校长截图上的那一处**（资料卡 → `/my/password`） |
| 英文对照 | Odoo 核心同一位置的文案是 `Edit information` | 容器内 `portal/views/portal_templates.xml:732`（核心 `portal.side_content`）⇒ 若按英文原文搜也只会命中核心，不会命中我们的仿制模板 |

**可能没命中的 4 个原因（供排查）**：① 只搜 `*.py`（这两串在模板里）；② 搜了 `edu_portal` 但漏了 `views/batch2.xml`（1237 行，资料卡段在 `:1110-1150`）；③ 用了词界参数（`grep -w` 对中文无效）；④ 搜了 `edu_portal/views/` 之外的同名目录（仓内有 `reference/`、`scrape/` 等素材目录）。
**判定依据（回答"资料卡在哪个路由/模板"）**：这两个串**同时出现在同一块 DOM**（`batch2.xml:1110-1150` 的 `edu_sidebar` 模板）里；而 `edu_sidebar` **全仓只有一处 `t-call`**（`views/batch2.xml:833`，在 `edu_dashboard_v2` 内）⇒ `edu_dashboard_v2` **只被 `/my/apps` 渲染**（`controllers/batch2.py:1977`）⇒ **校长截图的资料卡 = `/my/apps` 页面的侧栏**（另证：仓内截图 `shots/local/smoke_08b_my_apps.png` 与该卡的视觉特征逐项一致）。

**没找到（负结论）**：

| 负结论 | 搜索范围与方式 |
|---|---|
| 全仓**没有**任何"头像回退"的自研逻辑（没有 JS 兜底、没有 onerror） | `grep -rn "onerror\|avatar\|image_1920" custom_addons/*/static/` → 只命中 CSS 尺寸类；**没有任何 JS 处理头像** |
| 全仓**没有**头像裁剪/上传校验工具 | `grep -rn "base64\|image/*\|accept=" custom_addons/edu_portal/controllers/avatar.py custom_addons/edu_portal/views/edu_portal_templates.xml` → 仅弹窗 `accept="image/*"` 与控制器 `b64encode`；**无尺寸/类型/大小白名单**（§12-3） |
| 全仓**没有**第二个上传头像的写路由 | `grep -rn "image_1920'" custom_addons/` → **只有 `controllers/avatar.py:23` 一处写** |

### 5.3 四项字段的现状（逐条给结论；**本轮不做必填**）

| 字段 | 现状结论 | 证据（路径 + 行号） |
|---|---|---|
| ① **学号** | **有两个候选、都不是"学生档案里的学号"，且学生端只能"看"不能"填"**：<br>· `op.student.gr_no`（"Registration Number"，unique，size=20）= **教务口径的学号**（导入按它查重、成绩导入按它匹配、在读证明按它打印）<br>· `op.student.course.roll_number` = **学生×课程×班级的报名号**（三条唯一约束），档案页展示的就是它 | `openeducat_core/models/student.py:25/35/43-51/93/106-107`；教务导入 `edu_portal/controllers/roles.py:1653,1674-1679,1689,1744`；成绩导入按 `gr_no` 匹配 `roles.py:2058,2065-2066,2289,2298`；在读证明 `views/roles.xml:1806,1838`；档案页只读展示 `views/batch1.xml:590,698-699`（数据来自 `controllers/batch1.py:321`） |
| ② **年龄** | **基座与本仓都没有 `age` 字段**，只有 `op.student.birth_date`（Date，可空，校验"不得晚于今天"）。**判断：年龄不该存成字段**——它是出生日期的派生值且**随时间变化**（存下来必然与生日脱节，还会被"今年几岁"这类口径反复拷问）；需要展示就在控制器里算（`date.today() - birth_date`），需要筛选就按 `birth_date` 区间 | 字段 `student.py:70`；约束 `:136-141`；`grep "age = fields\|Integer('Age'" openeducat_erp/` **0 命中**；门户展示 `controllers/batch1.py:304` + `views/batch1.xml:626`（显示的是**出生日期**，不是年龄） |
| ③ **性别** | **已经是模型层必填**（`required=True, default='m'`）——但**门户没有任何地方能改**；而教务导入在缺值时**不写该键**（`if rec.get('gender') in ('m','f')`）⇒ 缺值行静默落到 **默认 'm'（男）**。这是"看起来必填、实际可能填错"的坑：女生若没在后台被改过，就是"男" | 字段 `student.py:81-85`；导入 `roles.py:1680-1682,1746-1747`；门户只读映射 `controllers/batch1.py:288` + `views/batch1.xml:622`；另见 `edu_portal/models/invite_code.py:71-76`（取"第一个合法选项"作为默认值的既有做法） |
| ④ **Telegram 昵称** | **不存在任何"学生/联系人身上的 Telegram 昵称"字段**。最接近的两处：<br>· `edu.tg.claim.telegram_name`（"Telegram 姓名"，来源 = Bot API `message.from.first_name + last_name`）与 `.username`（`@` 后那串，**很多人没设置，可空**）——它们挂在**领码记录**上，**不挂学生**（只能经 `claim.invite_code_id → edu.invite.code.used_by` 反查）<br>· 已退役的 v2.2 `edu_telegram` 有 `op.telegram.chat.telegram_name`（且带 `student_id`），但**从未部署**，且生产上"同名模块"是**另一个**匿名意见箱（不存明文 chat_id）⇒ **不可用** | 字段 `edu_tg_bind/models/tg_claim.py:65-70`；来源 `edu_tg_bind/controllers/webhook.py:66-71`；反查链 `edu_portal/models/invite_code.py:135-137`（`used_by`）；退役与同名不同物 `docs/code-map.md:124-128`、`docs/audit/deprecated-inventory.md` §0.1；Bot API 依据见 §2 表 |
| — | **Bot API 能不能拿到昵称**：能，但**只在对方跟 bot 说过话之后**：`first_name` 必带，`last_name`/`username` 可选；**没有任何接口能列出"全体学生的 TG 昵称"** | `webhook.py:66-71`（本仓实际消费三字段）+ Bot API User 对象（§2 表） |

### 5.4 需求 6 的"必填"部分：两种口径的代价对比（**结论已作废但仍留档**）

> 校长已裁定**取消必填**，所以本节**不作为实施依据**；保留它是为了：① 若将来重提，不必再查一遍；② 说明"为什么当时建议**不**加模型层 required"。

| 口径 | 做法 | 代价（逐条实测/可复现） | 判定 |
|---|---|---|---|
| **A. 模型层 `required=True`**（加在 `op.student.birth_date/gr_no` 或新字段上） | 改基座/自研模型的字段声明 | ① **既有数据 100% 不达标**：本地 4 名学生中 `gr_no` **4/4 为空**、`birth_date` **3/4 为空**（`select count(*) filter (where gr_no is null or gr_no='') … from op_student` → `4\|4\|3\|2\|2\|0\|3`）；② **打爆既有写入方**：层级码注册建学生只传 `partner_id/gender/user_id`（`invite_code.py:353-356`）、列表导入 commit 只传 `partner_id/first_name/last_name/gr_no`（`roles.py:1740-1750`）、种子脚本 `seed_demo.py:54-57`、`fix_user.py:22-24`；③ 本仓已有**反面先例**：为满足基座必填，层级码建教师时只能给 `birth_date = today()` 的**占位值**（`invite_code.py:375-382` 注释自述）⇒ 必填会把"空"换成"假数据" | ❌ 不建议（且**本轮明令禁止**） |
| **B. 门户表单层校验** | 只在门户表单上标必填 + 控制器校验 | ① 只影响"学生自己填"这一条路径，导入/后台/注册**不受影响**；② 但**必须先有表单**——而 §6 证明"学生档案字段**没有任何门户入口**"⇒ B 的前提是**先新建/扩展一个档案表单**（工作量大头在表单，不在校验）；③ 核心 `address_form_fields` 的必填是隐藏域 `required_fields='name,email'`（`address_templates.xml:383`）由 `_create_or_update_address(required_fields=…)` 消费——**扩展核心地址表单要动 Odoo 19 的 JSON 地址机制**，不划算 | ⚠ 若将来恢复需求，**推荐 B + 自建档案表单**（写 `op.student`，不走核心地址表单） |
| **C. 只做提示不做拦截** | 门户首页/资料页显示"资料待补全"提示条，不阻断任何操作 | 成本最低、零数据风险；与本仓"提示而非拦截"的既有做法一致（`edu_pending_setup` 待分配标记 `invite_code.py:471-475`） | ✅ 若将来做，**建议从 C 起步** |

---

## 6. 独立缺口：学生档案字段（学号 / 出生日期 / 性别）**在门户里无处可填**

> 队长指定必答。**结论：目前一个都填不了**——不是"藏在某个角落"，而是**没有任何写入口**。以下逐条给路由级证据。

| 字段 | 门户能**看**吗 | 门户能**填**吗 | 证据（路由 + 行号） |
|---|---|---|---|
| 性别 | 能（只读） | **不能** | 展示：`GET /student/profile`（`controllers/batch1.py:236` 是**唯一**一条 `/student/profile` 路由，全仓只此一条）→ 模板 `views/batch1.xml:622` 渲染 `info['gender']`（控制器 `:288` 把 `m/f` 映射成中文） |
| 出生日期 | 能（只读） | **不能** | 同上模板 `views/batch1.xml:626`；值来自 `controllers/batch1.py:304`（`student.birth_date`） |
| 学号 | 能（只读） | **不能** | `views/batch1.xml:590`（资料卡 chip，来源 `sc.roll_number` → `controllers/batch1.py:321`）、`:698-699`（入学详情卡）。另一条 `gr_no` **门户完全不显示**，只在教务工具与证书里出现（`roles.py:1675`、`roles.xml:1806,1838`） |

**为什么"填不了"——把页面上的写入口全查了一遍**：

1. `/student/profile` 页面上**共有 4 个 POST 表单，全部与档案无关**：`/my/skill/save`（技能 chips，`views/batch1.xml:737`）、`/my/leave/withdraw`（`:787`）、`/my/offer/set_state`（`:842, :848`）、`/my/apology/save`（`:969`）。
2. 页面上**唯一的"编辑"按钮**是资料卡的 `编辑资料` → `/my/account`（`views/batch2.xml:1144`）——那是**Odoo 核心的联系人地址表单**（§4.2 R6-R10），字段只有 `name/email/phone/company_name/vat/street/street2/zip/city/country_id/state_id`，**一个 `op.student` 字段都没有**；我们只把其中 3 个标签改成了院系/年级/学制（`partner_labels.xml:4-15`）——所以校长看到的那些"填空"**全是 res.partner 字段**。
3. 门户其它可能写档案的地方也查了：`/my/password`（改密码）、`/my/notify`（通知偏好）、`/my/avatar/upload`（头像）、`/register`（注册时只写 name/email/password）；**均不写 `op.student` 的 `gender/birth_date/gr_no/roll_number`**。
   - 命令：`grep -rn "birth_date\|gr_no\|roll_number" custom_addons/edu_portal/controllers/` → 命中的**写操作**只有导入（`roles.py:1744,1749`）与后台动作，**门户路由 0 处**。
4. **唯一能改的是"教务"**：后台 学生信息(257) 的 `op.student` 表单（基座自带），以及列表导入 `/edu/import/students`（`roles.py:1636-1763`）。**学生本人无路可走**。

**选项（请队长裁定是否属于本次范围；本设计不实施）**：

| 选项 | 内容 | 成本 / 风险 |
|---|---|---|
| **D1 什么都不做** | 只把"档案缺字段"做成只读提示（例如资料卡上给一条"资料待补全，请联系教务处"） | 最小；但校长原话"如果没有这几个填空，你就得添加它"未被满足 |
| **D2 自建「补充档案」表单**（推荐形态） | 在 `/student/profile` 增加一块「补充档案」：**学生可改** 性别 / 出生日期；**学号只读**（教务口径，学生自填会破坏 `gr_no` 唯一性与导入查重） | 中：1 个模板块 + 1 条 `POST /student/profile/save`（须 csrf、白名单字段、写 `op.student`）；**不加 required**，只做"填了就存" |
| **D3 扩核心 `/my/account` 表单** | t-inherit `portal.address_form_fields` + 扩 `_create_or_update_address` | 高：Odoo 19 已改成 JSON 地址机制（`portal.py:466-490`），且核心表单与 `/my/addresses` 共用，改它容易踩上游 |
| **D4 教务侧加"学生档案编辑"** | 门户侧给教务一个学生档案编辑页（写入口在教务，不在学生） | 中；适合学号类"官方字段"，与 D2 互补 |

> **学号归属的判断（供拍板）**：`gr_no` 是**教务处发的号**（导入查重、成绩匹配、证明打印都用它，`roles.py:1675/2065/2298`、`roles.xml:1806`）⇒ 建议**学生只读**；`roll_number` 是报名记录号，同样不建议学生自填。

---

## 7. 第 0 步④⑤：升级会不会动业务数据 + 演示数据策略

### 7.1 ④ 升级影响（manifest 自查，命令实跑）

```bash
grep -nE "'data'|'demo'" custom_addons/edu_portal/__manifest__.py
grep -rn "<function" custom_addons/edu_portal/data/
```

- **只有 `data` 键，没有 `demo` 键**（`__manifest__.py:33-75`；`assets` 在 `:76-101`）。
- `data/` 里 `<function>` **命中 2 处**，都在 `data/menu_reachability.xml:7,9`：`ir.ui.menu.edu_apply_reachability_groups`——**只改菜单 `group_ids`，幂等，不碰业务表**。
- ⇒ **本次改动（1 个控制器分支 + 2 个模板写法 + 1 处 303）不会写任何业务行**；`op_student / res_partner / op_session / ir_attachment` 在 `-u edu_portal` 前后**行数与内容不变**。
- ⇒ **不需要 migration**（`custom_addons/edu_portal/migrations/` 无新增）。
- ⚠ 与 **F1（菜单重放）** 无关：本次不动菜单 XML；但若实施期顺手跑 `-u edu_portal`，**backoffice 可见根会从 12 打回 17**（`docs/audit/deprecated-inventory.md` §6 F1）——实施验收后要按 `edu_nav` 口径复核一次。

### 7.2 ⑤ 演示数据策略

- **不新增演示数据**：合并与头像统一都是**渲染层**改动，没有新模型/新字段/新表。
- 若实施期需要"已上传头像"的样例账户：**只能通过门户上传**（写 `res.partner.image_1920`，Odoo 19 落 `ir_attachment`，`res_field='image_1920'`；本地库现有 `res.partner` 的 `image_1920` 附件 16+ 条可作参照）。**严禁**把头像塞进 `data/`（每次 `-u` 重放会覆盖真人头像）。
- 将来若要预置演示头像：走 **`demo` 键** + 文件名/记录带【演示】标记；**禁止**在 `data/` 里放写业务表的 `<function>`（F5 教训：`edu_life/data/demo_life.xml` 的演示注入把无标记行写进了业务表）。
- 清理口径：若产生演示头像，用 `scripts/cleanup_demo_data.py`（既有工具）或直接删对应 partner 的 `image_1920` 附件；**不删 partner 记录**。

---

## 8. 第 0 步③ + 第 4 步：需求 5 设计（合并）

### 8.1 裁定（三选一）= **合并（入口收口）**，理由

| 备选 | 内容 | 为什么不选 |
|---|---|---|
| 复用 | 只做"首页加一个「全部应用 →」" | **不满足需求**（校长要的是"合并成一页"） |
| **合并** ✅ | `/my/home` 保留 URL、内容换成宫格；`/my/apps` 降级为兼容层（**学生/家长** 303） | 改动最小（1 个分支 + 1 条重定向）、118 处引用全部保持有效、卡片引擎/收藏契约**本来就是同一套** |
| 新建（并存） | 新做第三个页面 | 制造**第三个**首页 = 第 0 步闸门明令禁止的"多长出一套" |

**逐条理由**：

1. **引用面**：`/my/home` 118 处活引用 vs `/my/apps` 4 处 ⇒ 保留 `/my/home` 是唯一不需要大批改引用的选择。
2. **语义**：校长原话"**全部应用被合并入我的主页**" ⇒ 保留"我的主页"这个入口，把"全部应用"的内容搬进来。
3. **零功能丢失**：宫格页本就是"零功能丢失载体"（`batch2.py:1947` 自述），收藏编辑（`[data-fav-grid]`/`home_favs.js`）在新首页照旧可用。
4. **不误伤内部用户**：教师/教务的 `/my/home` 是工作台、`/my/apps` 是宫格 ⇒ **303 只对学生/家长生效**（校长说的是"学生端"）。

### 8.2 路由清单（改后）

| 路由 | 角色 | 改前 | 改后 | 说明 |
|---|---|---|---|---|
| `/my/home` | 学生/家长 | Timeline 工作台（`edu_home_timeline`） | **全部应用宫格（`edu_dashboard_v2`）** | 传值 = 原 `/my/apps` 那套（`batch2.py:1956-1976`）+ `apps_page=True` |
| `/my/home` | 教师/教务/管理员 | 教师工作台 | **不变** | 分支判据 `batch2.py:1908-1911` 不动 |
| `/my/apps` | 学生/家长 | 200 宫格 | **303 → `/my/home`** | 与 `/my/checkin*` 收口同口径；**必须保留路由**（书签不 404） |
| `/my/apps` | 教师/教务/管理员 | 200 宫格 | **不变（200）** | 分流写法照抄既有 `main.py:211-217`（`/apps` 对非内部用户 303） |
| `/my` | 全部 | 302 `/my/home` | 不变 | `main.py:118-120` |
| `/apps`、`/openeducat/apps_menu` | 内部/非内部 | 非内部用户 303 `/my/home` | 不变 | `main.py:211-224`；**顺手改 `:214` 的注释**（"t6 交付 /my/apps 后改指它"随合并作废） |
| `/student/profile` | 学生 | 只读档案页 | 不变 | 见 §6 |

### 8.3 数据流

```
学生 GET /my/home
  └─ EduPortalHomeV2.edu_home (batch2.py:1895)
       ├─ 教师/教务/管理员 且 非学生非家长 → edu_dashboard_teacher      [不变]
       └─ 其余（学生/家长/管理员带学生档案）→ **edu_dashboard_v2**      [本次改这一行]
            ├─ 顶栏/侧栏：edu_page 外壳（含 #b11-avatar-modal）
            ├─ 内容：迷你头部 + 今日课表预览 + 欢迎 hero + 统计卡 + 全量分类卡片
            ├─ 侧栏：edu_sidebar（资料卡头像 → **改读账号 partner / avatar_***）
            └─ 收藏：_home_categories → [data-fav-grid] + home_favs.js（契约不变）

学生 GET /my/apps → 303 Location: /my/home   （路由保留，书签不 404）
教师 GET /my/apps → 200（原样）
```

### 8.4 零功能丢失对照（旧 `/my/home` 四块 → 新首页落点）

| 旧块（`study.xml:254-326`） | 新首页是否已有 | 落点 / 处置 |
|---|---|---|
| ① 今日课节（`study.xml:263-270`） | ✅ 已有 | `batch2.xml:693-721`「今日课表」预览卡（同数据源 `today_classes`，带时间/教室 chip + 日视图入口） |
| ② 待办三桶（已逾期/未来 7 天/未来 30 天，`study.xml:273-300`） | ❌ **没有** | **唯一真损失** ⇒ §11-2 请校长拍板：建议在合并页**顶部保留一条窄条**（空则不渲染） |
| ③ 我的课程≤3（`study.xml:303-311`） | ⚠ 部分 | 新首页有「在读课程」统计卡 + `/my/study` 课程中心（`study.xml:14-94`，含进度与"进入本科目"）⇒ 信息在，**按课节展开的进度列表**不在 |
| ④ 快捷入口≤8（`study.xml:314-323`） | ✅ 超集 | 新首页「快速操作」侧栏卡（`batch2.xml:1153-1185`）+ 全量分类卡片 |

### 8.5 需要同步的"引用点清单"（实施时逐条改；本文不改）

| # | 位置 | 现状 | 怎么改 |
|---|---|---|---|
| 1 | `controllers/batch2.py:1945-1977` | `/my/apps` 渲染宫格 | 拆成两段：学生/家长 → `303 /my/home`；内部用户 → 原逻辑 |
| 2 | `controllers/batch2.py:1895-1943` | `/my/home` 学生分支渲染 Timeline | 学生分支改渲染 `edu_dashboard_v2`（传值照 §8.3） |
| 3 | `controllers/batch2.py:1923` 注释 | "全量卡片迁往 /my/apps" | 改写为"全量卡片即首页" |
| 4 | `controllers/main.py:214` 注释 | "t6 交付 /my/apps 后改指它" | 改写为"资源面板类入口对学生一律回 /my/home" |
| 5 | `views/edu_portal_templates.xml:122-126`（侧栏） | 「我的主页」+「全部应用」两条 | **学生/家长隐藏「全部应用」**（点进去就是同一页）；**内部用户保留**（他们的宫格仍在 `/my/apps`） |
| 6 | `views/edu_portal_templates.xml:25,34,77,214`（顶栏品牌/面包屑/用户菜单/移动底栏） | 4 处指 `/my/home` | **不动**（仍然正确）。可选：`:214` 移动底栏文案「首页」随拍板项 1 改名 |
| 7 | `views/batch1.xml:76,208,421,564`、`views/batch2.xml:43,135,395`、`views/batch3.xml:95`、`views/roles.xml:1355`、`edu_life/views/portal_templates.xml:12`、`edu_schedule/views/templates.xml:12`、`edu_eval/views/eval_portal.xml:8`、`edu_quiz/views/edu_quiz_portal_views.xml:138`、`edu_brand/views/odoo_debrand.xml:277`、`edu_portal/views/help_center.xml:62,144,199` | 共 **17 处** `href="/my/home"` | **全部不动**（这是保留 `/my/home` 的直接红利）；仅 `help_center` 3 处**文案**建议随拍板项 1 同步 |
| 8 | `controllers/*.py` 的 `request.redirect('/my/home')` **96 处** | 各业务路由的"回首页" | **全部不动** |
| 9 | `tests/audit/verify_consolidation.py:48` | `("student","GET","/my/apps","功能卡网格")` 期望 200 | 改成「**303 + Location 精确 `/my/home`**」（C5 口径，探针不得跟随重定向） |
| 10 | `tests/smoke/ux_v3_route_matrix.py:42,74` | `PENDING_V3` 含 `/my/apps`；矩阵期望 200 | 同步：`/my/apps` 学生 → 303；内部用户 → 200（两种角色各一条） |
| 11 | `tests/_edu_eval_smoke.py:89-90` | 断言 `/my/home` = 200 | **仍成立，不动**。⚠ 2026-09-29 补：该文件是 edu_eval（行政评估）的专属冒烟，**随模块删除而整体删除** ⇒ 本行引用的取证文件已不存在；`/my/home` 的可达性现由 `tests/smoke/ux_v3_route_matrix.py`（`tests/ui/surface.json` 登记、gates 含 route_matrix）继续覆盖 |
| 12 | `docs/code-map.md` §4/§5 | `main.py` 描述为"首页分发"、路由表未提宫格 | 实施后同步（**本次不改**） |
| 13 | `docs/plans/study-hub-v3-design.md` §5 | "全量卡片迁往 `/my/apps`" | 实施后在文首加**修订说明**（文档历史保留，不改结论行） |

---

## 9. 第 4 步：需求 6 设计（头像统一 + 点击可改）

### 9.1 裁定

| 项 | 决定 | 依据 |
|---|---|---|
| **统一到哪种取图** | **`/web/image/res.partner/<pid>/avatar_128`（页头）/ `avatar_256`（卡片）** | Odoo 19 `avatar.mixin` 自带"无图 → 首字彩色头像"回退（§4.1 R2），**零自研**；且 apps 页迷你头部（`batch2.xml:674`）与通讯录/私信（`contacts.xml:28`、`messages.xml:70,104`）**已经这么写** ⇒ 只是把落队的卡片与页头拉齐 |
| **统一到哪个 partner** | **账号 partner（`request.env.user.partner_id`）** | 上传写的就是它（`avatar.py:22`）⇒ 读完就一致；否则"改完不生效"（§5.2-#16 实测分裂） |
| **点卡片头像** | 复用 `#b11-avatar-modal`（同页已在）+ `POST /my/avatar/upload` | 校长要"点下面那个头像就能改"；本仓**已有**弹窗与写路由（§5.2-#14）⇒ 能接就不造 |
| **是否新增路由/JS** | **0 条** | 弹窗与上传全在 `edu_page` 外壳里，宫格页通过 `t-call` 继承同一外壳 |

### 9.2 改动点（实施时；本设计不含代码）

| # | 文件（行号） | 改动 |
|---|---|---|
| A | `views/batch2.xml:1114-1116` | 卡片头像：`image_256` → **`avatar_256`**（或 128）；`t-att-src` 的 partner 由 `partner`（= `student.partner_id`）改为**账号 partner**；外面包一层 `<button type="button" class="... " data-bs-toggle="modal" data-bs-target="#b11-avatar-modal" aria-label="修改头像">`（按钮需要 CSS：`.oe-profile-avatar` 已是圆形，补 `padding:0;border:0;background:none`） |
| B | `views/edu_portal_templates.xml:67-73` | 页头：去掉 `t-if image_1920` / `t-else fa-user-o` 双分支，统一成 `avatar_128`（**改完页头与卡片在"有图/无图"两种状态下都一致**） |
| C | `views/batch2.xml:674` | 迷你头部：已是 `avatar_256`；只需确认 partner 源与 A 一致 |
| D | `controllers/batch2.py:1705` | `_sidebar_values`：`partner` 由 `student.partner_id` 改为 **当前用户 partner**（`request.env.user.partner_id`），并在 sidebar values 里保留 `student` 供姓名/标签使用 |
| E | （可选，同族同修）`views/roles.xml:17`、`edu_public/views/edu_public_views.xml:253` | `image_256` → `avatar_256`；**本轮可不做**（不在校长指的那张图上），登记在 §10 唤醒条件 |

### 9.3 已知边界（写清，避免"改完还是不像"）

1. **上传无校验**：`avatar.py:19-24` 只判 `filename` 与空内容，**不校验类型/大小**（弹窗文案却说"支持 JPG/PNG"）⇒ 大图会直接进 `ir_attachment`；是否补校验属**可选加固**（不在校长需求内）。
2. **无成功提示**：上传后 303 回 referrer（`avatar.py:25`），页面无 banner ⇒ 用户可能不确定成功。可选加固：回跳带 `?avatar_ok=1` 并显示提示。
3. **分裂 partner 的语义**：统一到账号 partner 后，若某学生"档案 partner ≠ 账号 partner"（本地实测 1 例），卡片显示的是**账号**头像/姓名首字。这正是"页头与卡片一致"的语义；**是否需要教务侧提示"档案与账号不一致"**列在 §11-4。
4. **首字取自 partner.name**（`avatar_mixin.py:66-77`）⇒ 无照片时显示的是**姓名首字**（王佐 →「王」），不是相机图标。**这是校长要拍板的视觉项**（§11-3）。

---

## 10. 复用 vs 自研边界 / 真机验收

### 10.1 边界表

| 能力 | 裁定 | 载体 |
|---|---|---|
| 门户首页（宫格） | **复用** | `edu_portal.edu_dashboard_v2` + `batch2._home_categories`（既有） |
| 卡片引擎 / 分类 / 角标 / 收藏 | **复用（零改动）** | `batch2.py` `cards()` / `[data-fav-grid]` / `home_favs.js` |
| 旧首页 URL | **复用（保留 `/my/home`）** | `batch2.py:1895` |
| `/my/apps` | **改为兼容层（合并）** | 303 → `/my/home` |
| 无图头像回退 | **复用（Odoo 内置）** | `base/models/avatar_mixin.py:35-42` + `/web/image` 的 `avatar_*` |
| 头像上传（UI + 写路由） | **复用（零新增）** | `#b11-avatar-modal`（`edu_portal_templates.xml:90-116`）+ `POST /my/avatar/upload`（`avatar.py:15`） |
| 学生档案字段填写入口 | **本次不做**（缺口，§6） | —— |
| Timeline 待办三桶 | **待拍板**（保留 / 迁走 / 删除） | 现 `study.xml:273-300` |

### 10.2 真机验收标准（可机读、可复现）

> 前置：`docs/code-map.md` 门禁三件套（无升级锁 / 容器 Up > 30s / 带 cookie jar 访问 `/web/login?db=edu19` 非 404）。
> 现状基线（**本次实跑**）：未登录 `/my/home`、`/my/apps`、`/my` 均 `303 → /web/login?redirect=…`。

| # | 判据 | 命令（登录态用 `tests/audit/audit_lib.py:33 login()` 或 `tests/smoke/ux_v3_route_matrix.py:215`） | 期望 |
|---|---|---|---|
| 1 | 升级不炸 | `bash scripts/safe_upgrade.sh -u edu_portal` | EXIT=0 且输出无 `Traceback`/`CRITICAL`/`manifest not found` |
| 2 | **学生** `/my/apps` 是兼容层 | `curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' -b jar http://localhost:8069/my/apps`（**不带 -L**） | `303 http://localhost:8069/my/home` |
| 3 | **学生** `/my/home` 已是宫格 | `curl -s -b jar http://localhost:8069/my/home \| grep -c 'o_portal_index_card'`；并确认 **不含** `ux3-hero-title">工作台`（若拍板保留待办窄条，则只断言"含宫格且含待办窄条"两种标记） | ≥1 且 Timeline 标记为 0 |
| 4 | **点卡片头像能开弹窗**（HTML 级） | `curl -s -b jar http://localhost:8069/my/home \| grep -c 'data-bs-target="#b11-avatar-modal"'` | ≥2（页头 1 + 卡片 1） |
| 5 | **两处头像同源**（这是"统一"的机械判据） | `curl -s -b jar http://localhost:8069/my/home \| grep -o '/web/image/res.partner/[0-9]*/avatar_1\?[0-9]*' \| sort -u` | **只有 1 个 partner id**（页头与卡片同 id） |
| 6 | 无图时是"首字头像"而不是相机占位 | `curl -s -b jar "http://localhost:8069/web/image/res.partner/<pid>/avatar_128" \| wc -c`；`…\|head -c 20` | `424`（生成 SVG，实测值）且开头是 `<?xml`；**不是** 6078（`placeholder.png`） |
| 7 | **上传后立刻两处一致** | 1) POST `/my/avatar/upload`（带 csrf + 真图片）→ 期望 303 回 referrer；2) 重取 `/my/home`，对两处 `src` 各取一次图片并 `shasum` | 两个 hash **相同**（同 partner、同图；尺寸不同则退化为"同 partner 且非占位图"） |
| 8 | **内部用户不回归** | 教师/教务会话 GET `/my/apps`（**不带 -L**）→ 200；GET `/my/home` → 含教师工作台标记（`edu_dashboard_teacher` 的特征串） | 200 / 工作台 |
| 9 | 审计与矩阵 | `python3 tests/audit/verify_consolidation.py --phase after`；`python3 tests/smoke/ux_v3_route_matrix.py` | 全 PASS（含第 9/10 项改过的断言；**探针不得跟随重定向**） |
| 10 | 汉化闸门 | `python3 scripts/check_english.py` | must-fix = **0** |
| 11 | 视图安全（若新增 t-inherit） | `python3 scripts/check_view_xpath.py` | 退出码 0，无"未命中 xpath" |
| 12 | 截图留档（第 6 步） | 学生登录 → `/my/home` 截图；点卡片头像 → 弹窗截图；上传后回页截图 | 存 `tests/gap/shots/`（dev-workflow 第 6 步口径） |

### 10.3 收口触发条件（"何时可以彻底删 `/my/apps`"）

> 本仓红线是**不删记录**；此处回答的是"**303 兼容层**与路由将来若真要下线，先满足什么"。

| 条件 | 判据 |
|---|---|
| **T1 零报障** | 自本登记日起**连续 30 天**无 `/my/apps` 的 404/书签报障（**不删路由就没有 404**，所以此条只对"下线兼容层"生效） |
| **T2 内部用户有落点** | **前置**：教师/教务的卡片宫格已在别处有着落（否则 `/my/apps` **永远不能下线**——它对内部用户仍是 200 的活页） |
| **T3 引用归零** | `grep -rn "/my/apps" --include="*.py" --include="*.xml" custom_addons/ scripts/ tests/` 只剩注释/历史文档（`docs/` 不算） |
| **T4 断言已改强** | `verify_consolidation.py:48` 与 `ux_v3_route_matrix.py:74` 已按"303 + Location 精确"改写并全绿（**不许"跟随后 200"**） |
| **T5 队长书面确认** | 台账 §8 登记行由队长确认（含"永久兼容层还是可下线"的书面裁定） |

> **默认结论：无计划删除**（T2 未满足前，`/my/apps` 是内部用户唯一的宫格入口）。

### 10.4 台账登记（已追加一行到 `docs/audit/deprecated-inventory.md` §8）

重叠对象 = 门户首页两套实现（`/my/home` Timeline vs `/my/apps` 宫格）；候选方案 = **合并（入口收口）**；替代路径 = `/my/home`（宫格）；附"何时可彻底删除 + 前置条件"与唤醒条件。

---

## 11. 需要校长拍板的用户可见项（**用户可见**口径）

| # | 事项 | 选项 | 建议 |
|---|---|---|---|
| 1 | **合并后首页叫什么**（影响侧栏 `edu_portal_templates.xml:122`、移动底栏 `:214`、用户菜单 `:77`、帮助中心 3 处文案 `help_center.xml:62,144,199`） | ① 仍叫「我的主页」 ② 改叫「全部应用」 ③ 叫「工作台」 | ①（校长原话是"合并入我的主页"）；若他要"名字也一目了然"，② 亦可——**三种都不影响路由** |
| 2 | 旧主页的**「待办三桶」**（已逾期 / 未来 7 天 / 未来 30 天）留不留 | ① 合并页**顶部保留一条窄条**（空则不渲染）② 迁到「课程中心」`/my/study` ③ 直接去掉 | ①（本仓「零功能丢失」是硬规矩；且这是旧主页**唯一**的独有内容） |
| 3 | **无照片时的默认头像样式** | ① Odoo 首字彩色头像（"王"）② 保持现在的蓝底人形图标 ③ 统一换成品牌默认头像图 | ①（**一次改动同时覆盖页头与卡片**，且与通讯录/私信一致；②做不到"上面和下面一样"） |
| 4 | 若某学生"档案 partner ≠ 账号 partner"（本地实测 1 例）：卡片显示 **账号**头像/姓名首字 | ① 就这样（页头=卡片）② 同时在教务侧给一条"档案与账号不一致"提示 | ①（本次范围）；②另立任务 |
| 5 | （**若队长把 §6 缺口纳入范围**）**学号可见性**：学生能否自填学号 | ① 只读展示（教务/导入填）② 允许学生自填 ③ 藏起来不显示 | ①（`gr_no` 是教务发的号：查重/成绩匹配/证明打印都靠它） |

> 校长**不需要**拍板的技术项（已由本设计与既有约定定死）：保留哪个 URL、303 还是 301、用 `avatar_*` 还是自研回退、加不加模型层 required（**不加**）。

---

## 12. 未查到 / 不确定（不得当结论用）

1. **生产库未核对（本轮禁止碰生产）**：无法确认校长截图里的**王佐**是否为"档案 partner ≠ 账号 partner"的分裂态。本地实测的 1 例是唯一的可登录学生（档案 partner 35 / 账号 partner 38）。**生产只读核对 SQL（交队长执行）**：
   ```sql
   select s.id, s.name, s.partner_id as stu_partner, u.id as uid, u.partner_id as user_partner,
          (select count(*) from ir_attachment a where a.res_model='res.partner'
             and a.res_field='image_1920' and a.res_id=s.partner_id) as stu_img,
          (select count(*) from ir_attachment a where a.res_model='res.partner'
             and a.res_field='image_1920' and a.res_id=u.partner_id)  as user_img
   from op_student s join res_users u on u.id = s.user_id;
   ```
   （判据：`stu_partner <> user_partner` 的行数 > 0 ⇒ 本设计的"统一数据源"就是修的正是这一条。）
2. **Telegram Bot API 官方页本次抓取失败**（`web_fetch https://core.telegram.org/bots/api` → `fetch failed`）⇒ User 对象三字段的结论以**镜像文档**（python-telegram-bot）+ **本仓消费代码**（`webhook.py:66-71`）+ **本仓字段帮助文本**（`tg_claim.py:70`"很多人没设置，允许为空"）为证据。若将来要用 bot 数据，需在真机用一次真实 update 复验。
3. **头像上传无校验/无提示**（`avatar.py:19-25`）——这是**现状事实**，不是缺陷判定；是否加固未定。
4. **"学生是否曾通过非门户途径填过性别/生日"未逐条追溯**：我只证明**门户无入口**；后台手工补录、导入文件里带值这两条路径存在且会写值（`roles.py:1746-1749`）。
5. **内部用户对 `/my/apps` 的实际使用量未测**（无访问统计）⇒ T2 的"何时可有落点"缺数据；若将来做整体收敛，需要先补一个使用量读数。
6. **校长原图不在仓内**：卡片是 `/my/apps` 的判定依据是"「编辑资料/修改密码」**只出现在** `edu_sidebar`（`batch2.xml:1144,1147`）+ 仓内等价截图 `shots/local/smoke_08b_my_apps.png` 与配图特征逐项对上（相机占位头像 / 两个 chip / 两个按钮）"，**未在校长原图上复核**。
7. **`/my/home` 的旧实现（`main.py:107-116` + `edu_dashboard` 模板）已不可达但仍在册**：是否清理**未定**（零删除红线 ⇒ 默认不删）。

---

## 13. 变更记录

| 日期 | 改动 | 责任 |
|---|---|---|
| 2026-09-18 | 建立本文（第 0 步查重 ①–⑤ + 第 3 步读参考 + 第 4 步设计摘要）；裁定 = **合并（入口收口）**，保留 `/my/home`；定位需求 6 病灶为"同页两种头像写法 + 两个 partner 源"，统一到 Odoo 内置 `avatar_*`；补 §6「学生档案字段无门户填写入口」缺口；按校长裁定**取消四项必填** | 设计子代理（学生门户主页/资料卡） |
```
```
