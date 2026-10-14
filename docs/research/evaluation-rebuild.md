# 评估系统重建调研 —— 「参数丰富 + 可自定义 + Excel 式自由编辑」外部可复用性

> **决策问题**（校长原话）：「我建议直接把它们删除掉。重新做一个，我们目前的这个综合评估用起来很不舒服。我希望**参数能够丰富一点，并且可以自定义**，就像是我使用 **excel 表格**那样自由方便，并且我希望你**真的做成 excel 表格**，这样修改起来很方便。你最好参考参考现有的方案再来做。」
> **本档回答的唯一问题**：「参数丰富 + 可自定义 + Excel 式自由编辑」的评估系统，**外面有没有现成的可以装 / 可以抄？**
>
> **取证环境**：docker `edu19-clone-web-1`（镜像 `odoo:19`，`odoo.release.version_info = (19, 0, 0, FINAL, 0)`，见容器内 `/usr/lib/python3/dist-packages/odoo/release.py:15`）；库 `edu19`（容器 `edu19-clone-db-1`）。测试日期 **2026-09-18 CST**。
> **行号漂移警告**：本文所有 `odoo/addons/...:行号` 均为 **2026-09-18 上午** 实测快照，上游换版即可能偏移，实施时以本机实测为准。
> **合规**：企业版源码仅指 `30-资源/odoo源代码企业版/`（只读参考，不进仓库，铁律见 `/Users/qwe/odoo-enterprise-ref/README.md`）；Odoo 核心源码只给路径 + 行号，不贴码。
> **结论纪律**：每条结论带一手来源；无法核实的一律标「未验证」并集中列在 §8，**不得当结论使用**。

---

## 0. 结论速览

### 0.1 一句话回答

**不能「不写代码就装出来」。** 但同样重要的是：**也不需要自研表格引擎**——「表格 + xlsx 导入 + xlsx 导出」这三件事在 Odoo 19 **社区版（LGPL-3）里是白送的**（原生列表视图 + `base_import`），真正缺的只有一块：**「列 = 可自定义评分项」的矩阵语义**（= 队长定义的 B）。Odoo 自带的 `spreadsheet` 在社区版是**只读**的，`web_grid` / `hr_appraisal` 是**企业版独占（OEEL-1，闭源许可）**，`survey` 的计分是「判对错」而不是「评分」，且**矩阵题与量表题在 Odoo 19 里根本不计分**。

### 0.2 三条路径 × 需求 A / B / D 逐条打分

> 需求定义（队长 2026-09-18 补充）：**A 录入像 Excel**（行=学生，列=评分项，直接在格子里打分）；**B 设计像 Excel**（评分项本身能在表格里自由增删改）；**C = A + B**；**D 进出都是 Excel 文件**（整批导入评分项、导出成绩）← **队长定为必须项**。

| 路径 | A 录入像 Excel | B 设计像 Excel | D xlsx 进出 | 关键依据 |
|---|---|---|---|---|
| **A：Odoo 原生列表视图内联编辑** | **部分**（行=记录可编辑、`multi_edit` 可批量同值；但列=模型字段，不能自由增删） | **部分**（`Properties` 可在界面在线加「列」，但形态是"每记录键值"，不是"学生×评分项"矩阵） | **满足**（导入/导出 xlsx 白送，且是 ORM 级往返） | `list_arch_parser.js:191/199-206`、`import_records.js:42-48`、`export_all.js:34-38`、`orm/fields_properties.py:32-51` |
| **B：Odoo 内置 spreadsheet** | **不满足**（社区版只读：`mode` 只允许 `dashboard`/`readonly`） | **不满足**（编辑动作 `action_edit_dashboard` 属企业版 OEEL-1） | **部分**（引擎有 `exportXLSX`；但门户公开分享页的 Excel 下载要求 `base.group_allow_export`，学生拿不到） | `o_spreadsheet.js:78149/78288`、`public_readonly.js:58`、企业版 `spreadsheet_dashboard_edition/models/spreadsheet_dashboard.py:37`、`share.py:48`、`base_groups.xml:61-66` |
| **C：第三方电子表格嵌入** | **满足** | **满足** | **满足，但要两件套**——⚠ 实测发现：**Univer OSS / jspreadsheet CE **都不含** xlsx 读写**（Univer 的 xlsx 在**付费的 `@univerjs-pro/exchange-client`**；jspreadsheet CE 明确不含），xlsx 必须另配 **SheetJS CE（Apache-2.0）**；或直接复用 **Odoo 自带 `o-spreadsheet`（LGPLv3，引擎内置 `exportXLSX`）** | 见 §6.3、§6.4；Univer 包清单 `gh api repos/dream-num/univer/contents/packages`、`@univerjs/sheets-import-xlsx` npm `Not Found`、`@univerjs-pro/exchange-client` `license: null` |

### 0.3 推荐（详见 §7）

**A + C 组合，以 A 为主干**：后台配置 + 成绩总览走 Odoo 原生列表视图（零前端成本拿到 A 的一部分与 D 的全部）；**门户侧"自由单元格"录入面**按需引入 **Univer（Apache-2.0）** 作为纯录入组件，落库仍走 ORM；**B 用 `Properties` + 评分项行表解决**。
**明确不要**：装 `survey` 当评估引擎（§2.1）；指望**纯社区版** `spreadsheet` 编辑（§2.2，社区版只读；OCA 的 `spreadsheet_oca` 虽能补齐但 **AGPL-3.0**）；买企业版用 `web_grid`（§2.3，列是时间轴）；用 Studio 加字段（§2.5.2，企业版独占）；用 Handsontable（§6.4，非开源）。

---

## 1. 需求拆解与现状（本仓）

| 项 | 事实 | 来源 |
|---|---|---|
| A 套引擎 | `custom_addons/edu_portal/models/evaluation.py`（145 行）→ `edu.eval.template / .template.line / .task / .score`；路由 `/my/evaluation*`、`/eval/my`、`/eval/review`、`/eval/fill/<id>` | `docs/code-map.md:97-101`、`:226`、`:228`；`custom_addons/edu_portal/models/evaluation.py:20/47/71` |
| B 套引擎 | `custom_addons/edu_eval/models/admin_eval.py`（138 行）→ `edu.admin.eval.*`（模型名必须带 admin，否则与 A 撞注册表）；**0/0/0 从未使用** | `docs/code-map.md:97-99` |
| 真实资产 | 生产 A 套 4 模板 / 13 评分项 / 1 任务 / **0 条打分**；B 套 0/0/0 | 队长 2026-09-18 转述校长确认 |
| 旧合并设计 | `docs/plans/eval-merge-design.md`（t4，2026-09-17）的结论是「留 A 套、B 并入 A」 | 该文档 §0 |

> **参考与排除**：`docs/plans/eval-merge-design.md` **已被推翻**——它的前提是「A 套有存量、B 套零记录，所以保留 A 最便宜」，而现在校长已确认那个唯一的真实模板「学生表现分」**不是他在用的**，两套**都要删**。因此本文**不采信**该设计的任何结论（包括它的 6 口径 `type_code` 与匿名 HMAC 方案——那些是为「合并两套」服务的，与「重建一套」无关），仅把它登记为「已作废的前提」。

---

## 2. Odoo 19 核心源码取证（读源码，不猜）

### 2.0 本部署的基线：**社区版，无企业版**

`docker-compose.yml`（仓根）的 `web` 服务只有 3 个挂载：`./openeducat_erp:/mnt/extra-addons`、`./custom_addons:/mnt/custom-addons`、`./config/odoo.conf`——**没有企业版 addons 路径**。库内实测：

```bash
docker exec edu19-clone-db-1 psql -U odoo -d edu19 -tAc \
  "select name,state from ir_module_module where name in ('survey','spreadsheet','spreadsheet_dashboard','web_grid','hr_appraisal','base_import') order by name"
```

| 模块 | 库内状态 | 说明 |
|---|---|---|
| `survey` | `uninstalled` | 可装（社区版自带） |
| `spreadsheet` | **`installed`** | 已装（LGPL-3） |
| `spreadsheet_dashboard` | **`installed`** | 已装（LGPL-3） |
| `base_import` | **`installed`** | 已装（`auto_install=True`，LGPL-3，`base_import/__manifest__.py:28/43`） |
| `web_grid` | **不存在** | 企业版独占（§2.3） |
| `hr_appraisal` | `uninstallable` | 模块记录在库，**代码不在镜像里**（企业版独占，§2.4） |

社区版相关模块的 license 全部 **LGPL-3**：`web/__manifest__.py:557`、`survey/__manifest__.py:113`、`spreadsheet/__manifest__.py`、`spreadsheet_dashboard/__manifest__.py:12`、`base_import/__manifest__.py:43`、`website_slides_survey/__manifest__.py:50`。

---

### 2.1 `survey`（社区版 LGPL-3，本库未装）——**能不能直接当评估引擎用？不能。**

#### 2.1.1 题型：9 种，够「丰富」

`survey/models/survey_question.py:87-97`：
`simple_choice`（单选）· `multiple_choice`（多选）· `text_box`（多行文本）· `char_box`（单行文本）· `numerical_box`（数值）· `scale`（量表）· `date` · `datetime` · `matrix`（矩阵）

**量表被硬限在 0–10**：`survey_question.py:220-223`
```
_scale = models.Constraint(
    "CHECK (question_type != 'scale' OR (scale_min >= 0 AND scale_max <= 10 AND scale_min < scale_max))",
    'The scale must be a growing non-empty range between 0 and 10 (inclusive)')
```
⇒ **「参数丰富」在量表这条线上先天受限**：不能做 0–100 分制量表，也不能做负分。

#### 2.1.2 矩阵题：**真的渲染成 HTML 表格**，但**不计分**

- 数据结构：列 = `suggested_answer_ids`（`survey_question.py:117-119`，注释原文 "Labels used for proposed choices: simple choice, multiple choice and **columns of matrix**"）；行 = `matrix_row_ids`（`:124-126`）；`matrix_subtype` = `simple`（每行单选）/ `multiple`（`:121-123`）。
- 渲染：`survey/views/survey_templates.xml:634` 模板 `question_matrix`；`:651` `t-foreach="question.matrix_row_ids"`（行）× `:653` 列 `suggested_answer_ids`；单元格 `:657` 是 `radio`/`checkbox`。**这是 Odoo 里唯一真正的「行×列」网格**。
- **但矩阵不计分**：`survey_question.py:378-400` `_compute_is_scored_question`：
  - `:391-397` 只处理 `date` / `datetime` / `numerical_box` / `simple_choice` / `multiple_choice`
  - `:399-400` `else: question.is_scored_question = False`
  ⇒ **`matrix` 与 `scale` 都落到 else，恒为不计分。**
- 佐证：`survey_user_input.py:776-795` `_compute_answer_score` 同样只覆盖 choice 与 date/datetime/numerical_box；`survey_user_input.py:67-86` 汇总口径 `total_possible_score` 也只累加这三类 + 单选题取最大正分。

> **反直觉但决定性**：评估系统最需要的两种题型（矩阵、量表）恰好是 Odoo 19 survey **唯一不计分**的两种。

#### 2.1.3 计分口径 = **判对错**，不是「打分」

- 题目级：`answer_score`（`survey_question.py:108`）+ 约束 `_positive_answer_score CHECK (answer_score >= 0)`（`:208-211`，原文 "An answer score for a non-multiple choice question cannot be negative!"）⇒ **题目级不能负分**。
- 选项级：`survey.question.answer.answer_score`（`:866`，help 原文 "A positive score indicates a correct choice; a negative or null score indicates a wrong answer"）⇒ 只有**选择题选项**能负分。
- 通过线：`scoring_success_min` 默认 80.0（`survey_survey.py:114`）；`scoring_success = scoring_percentage >= scoring_success_min`（`survey_user_input.py:88-91`）。
- 官方文档口径确认："To indicate correct answers, click on the Questions tab and choose a question… check the **Is a correct answer** box for the choice that is the correct answer and attach a score value." —— <https://www.odoo.com/documentation/19.0/applications/marketing/surveys/scoring.html>

#### 2.1.4 结构缺口：**没有「被评估对象」**

`survey.user_input`（= 一份答卷）的字段里只有**答卷人**：`partner_id` / `email` / `nickname`（`survey_user_input.py:47-49`）；`survey.user_input.line`（= 一条答案）的全部字段是 `user_input_id / survey_id / question_id / page_id / question_sequence / lang_id / skipped / answer_type / value_* / suggested_answer_id / matrix_row_id / answer_score / answer_is_correct`（`:693-726`）——**没有任何字段指向「被评价的老师/学生/课程」**。
矩阵的「行」只是一条 `survey.question.answer` 标签记录，**不是学生记录**，无法与学生档案建立外键。
⇒ **「教师给整班学生逐个打分」这件事，survey 在数据模型层面就表达不了。**

#### 2.1.5 匿名 / 多次作答 / 认证 / 报表（如实记录，供「可抄」用）

| 能力 | 事实 | 行号 |
|---|---|---|
| 访问控制 | `access_mode` = `public`（凭链接）/ `token`（仅受邀）；`users_login_required` | `survey_survey.py:92-97` |
| 多次作答 | `is_attempts_limited` + `attempts_limit`（默认 1）；仅对 token/登录场景生效 | `:117-119`、`:284-290` |
| 尝试计数 | 用 `invite_token`/partner/email 关联的 SQL 计数 | `survey_user_input.py:124-165` |
| **匿名** | **无「匿名」概念**。答卷**总是**绑 `partner_id`/`email`；不存在「不落身份」开关 | `survey_user_input.py:47-49` |
| 认证 | `certification` + 证书 PDF（6 套配色）+ `certification_give_badge` + 自动邮件 | `survey_survey.py:123-145`、`:1228-1272` |
| 结果报表 | 统计页只有 **Print（HTML→PDF）** 按钮 | `survey/views/survey_templates_statistics.xml:25` |
| 门户作答 | `/survey/start/<token>`、`/survey/begin/...`、`/survey/submit/...` 等 **`auth='public', website=True`** | `survey/controllers/main.py:156-210, 490-522, 662` |
| 条件题（可抄） | `triggering_answer_ids`（题目显示依赖） | `survey_question.py:163-171` |

#### 2.1.6 **题目不能用 xlsx 批量导入**（队长问题 2 的答案）

- `survey.question` 的列表视图是 **`create="false"`**：`survey/views/survey_question_views.xml:294`
- 而 `base_import` 的「Import records」菜单**显式要求 create 未禁用**：`base_import/static/src/import_records/import_records.js:42-48`
  ```js
  isDisplayed: ({ config, isSmall }) =>
      !isSmall &&
      config.actionType === "ir.actions.act_window" &&
      ["kanban", "list"].includes(config.viewType) &&
      exprToBoolean(config.viewArch.getAttribute("import"), true) &&
      exprToBoolean(config.viewArch.getAttribute("create"), true),
  ```
- `survey.user_input`（`:117`）、`survey.user_input.line`（`:203`）、`survey.question.answer`（`:339`）**全部 `create="false"`**
- 题目的唯二入口是 survey 表单里的 `question_and_page_ids` 内嵌列表（`survey/views/survey_survey_views.xml:75`，widget `question_page_one2many`）⇒ **只能一条一条建**。

**导出侧则相反**：`create="false"` **不挡导出**——`web/views/list/export_all/export_all.js:34-38` 的显示条件是 *viewType ∈ {list,kanban} ∧ 无选中 ∧ `user.hasGroup("base.group_allow_export")` ∧ `export_xlsx` 未禁用*，与 `create` 无关。
⇒ **管理员**可把 Participants / Detailed Answers 导出 xlsx；**但 `base.group_allow_export` 只 implied_by `group_system`**（`base/security/base_groups.xml:61-66`），**门户学生与普通内部用户默认没有导出权**。

#### 2.1.7 小结：survey 离「评估系统」差多远

| 校长要的 | survey 能否 |
|---|---|
| 参数丰富 | 中（9 题型，但量表限 0–10） |
| 可自定义（评分项） | 差（后台一条条建，且不能批量导入） |
| A 行=学生、列=评分项、格子里打分 | **不能**（无被评对象字段；矩阵行是标签不是学生） |
| 能用于评分表 | **不能**（矩阵/量表不计分；计分 = 判对错） |
| 匿名评教 | **不能**（无匿名概念，必落身份） |
| D 批量导入评分项 | **不能**（题目列表 `create="false"`） |
| D 导出成绩 | 能（仅管理员，xlsx） |

**结论：survey 不能直接当评估引擎用。** 它的价值是「可以抄的机制」：`access_mode`+token 的受邀作答、`is_attempts_limited`、`certification`+徽章+证书 PDF 模板、触发式条件题。
**旁证**：Odoo 企业版自己的 `hr_appraisal` 也是把「评估表」存在 `survey.survey` 里——官方文档原文："**Appraisal templates are housed in the Surveys app.**"（<https://www.odoo.com/documentation/19.0/applications/hr/appraisals.html>）⇒ 官方也把 survey 当评估表的底座，但**底座之上那些业务壳（被评人、评分人、终评、目标、技能）全是企业版才有的自研部分**。

---

### 2.2 `spreadsheet` 系列（社区版 LGPL-3，**本库已装**）

#### 2.2.1 Odoo 19 内置的电子表格引擎是什么

- 引擎本体 = **`o-spreadsheet`**，Odoo 自研并开源：<https://github.com/odoo/o-spreadsheet>，**LGPLv3**（LICENSE 原文："o-spreadsheet is published under the GNU LESSER GENERAL PUBLIC LICENSE, Version 3 (LGPLv3)"，<https://github.com/odoo/o-spreadsheet/blob/19.0/LICENSE>；npm `@odoo/o-spreadsheet@19.0.50`；GitHub `pushed_at 2026-09-17`，289★）。
- 打进 Odoo 的是 AOT 产物：容器内 `spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js:4-8` 头部注明 `@version 19.0.46 / @date 2026-08-10 / https://github.com/odoo/o-spreadsheet`（全文 78763 行）。
- 社区版实际存在的模块：`spreadsheet`、`spreadsheet_dashboard`、`spreadsheet_account`、`spreadsheet_dashboard_{account,event_sale,hr_expense,hr_timesheet,im_livechat,pos_hr,pos_restaurant,sale,sale_timesheet,stock_account,website_sale,website_sale_slides}`、`test_spreadsheet`。

#### 2.2.2 社区版只能看，不能编辑（决定性）

| 证据 | 内容 |
|---|---|
| `o_spreadsheet.js:78149` | `isReadonly: () => this.config.mode === "readonly" \|\| this.config.mode === "dashboard"` |
| `o_spreadsheet.js:78288` | `const isReadonly = config.mode === "readonly" \|\| config.mode === "dashboard"` |
| `spreadsheet/static/src/public_readonly_app/public_readonly.js:58` | `mode: this.props.mode === "dashboard" ? "dashboard" : "readonly"` —— 公开页**只可能是这两种只读模式** |
| `spreadsheet_dashboard/models/spreadsheet_dashboard.py` 方法清单 | 只有 `_compute_is_favorite / action_toggle_favorite / _get_serialized_readonly_dashboard / _get_sample_dashboard / _dashboard_is_empty / _get_dashboard_translation_namespace / copy_data` —— **没有** `action_edit_dashboard` |
| 企业版 `spreadsheet_dashboard_edition/models/spreadsheet_dashboard.py:37` | `def action_edit_dashboard(self)` —— **编辑能力由 OEEL-1 模块提供** |
| 企业版 `spreadsheet_edition/__manifest__.py` | `'license': 'OEEL-1'`，`'depends': ['spreadsheet', 'mail', 'web_enterprise']` |
| 社区版 `spreadsheet.mixin` 的使用者 | 全仓 grep 只有 `spreadsheet.dashboard`、`spreadsheet.dashboard.share`、`test_spreadsheet` |

⇒ **社区版内置 spreadsheet = 只读仪表盘 + 只读公开分享页**。「用户能编辑的电子表格」在官方口径里是企业版（`spreadsheet_edition` + `spreadsheet_dashboard_edition`，OEEL-1）。
**但——存在一条合法补齐路径**：`OCA/spreadsheet` 的 `spreadsheet_oca`（19.0 分支已有），README 原文："This module adds a functionality for **adding and editing Spreadsheets using Odoo CE**. It is an **alternative to the proprietary module `spreadsheet_edition`** of Odoo Enterprise Edition."（详见 §3.2，**代价是 AGPL-3.0**）。

#### 2.2.3 能否嵌入门户？——能「分享」，但**学生拿不到 Excel**

公开只读页路由：`spreadsheet_dashboard/controllers/share.py`
- `:41-63` `@http.route(['/dashboard/share/<int:share_id>/<token>'], type='http', auth='public')` → 渲染 `spreadsheet.public_spreadsheet_layout`
- `:48-49` 下载按钮**有条件**：`if request.env.user.has_group('base.group_allow_export'): download_url = f"/dashboard/download/{share.id}/{token}"`
- `:65-75` `/dashboard/download/...` 是 **`auth='user'`** 且二次校验 `group_allow_export`，否则 `UserError("You don't have the rights to export data…")`
- `base/security/base_groups.xml:61-66`：`group_allow_export` 的 `user_ids=[base.user_root]`、`implied_by_ids=[group_system]`

⇒ 分享链接对学生**可见只读表格**，**但下载不了 xlsx**。

#### 2.2.4 出口格式

- 引擎内置 `exportXLSX`（`o_spreadsheet.js:78506` 导出符号）；公开页通过 `props['downloadExcelUrl']` 触发（`spreadsheet/views/public_readonly_spreadsheet_templates.xml`，`o_download_btn`）。
- `spreadsheet_dashboard/models/spreadsheet_dashboard_share.py:15` `excel_export = fields.Binary()`，由 `action_get_share_url` 在创建分享时**预生成**（`:25-33`）。
- 官方文档（<https://www.odoo.com/documentation/19.0/applications/productivity/spreadsheet/share_collaborate.html>）原文：「Any user with access to a spreadsheet can download it as an **.xlsx** file by clicking File ‣ Download… If the spreadsheet contained dynamic data, **the values are frozen at the moment of download**」；且「静态表可内外分享，**连库的动态表只能内部分享**」。

#### 2.2.5 与「评估 / 评分」有没有现成结合点？——**只有企业版有**

| 模块 | license | 作用 |
|---|---|---|
| `documents_spreadsheet_survey`（企业版） | OEEL-1 | `'summary': 'Spreadsheet for Survey results'`，`depends: ['documents_spreadsheet', 'survey']` —— **官方唯一的 survey↔spreadsheet 桥** |
| `hr_appraisal_survey`（企业版） | OEEL-1 | `'summary': '360 Feedback'`，`depends: ['hr_appraisal', 'survey']` |
| `spreadsheet_dashboard_*`（社区版） | LGPL-3 | 均为**业务报表**桥（sale / stock / expense / timesheet），**没有一个与评估相关** |

**结论：Path B 在纯社区版不成立；企业版也不满足 B**——企业版的 spreadsheet 是「自由表格」，不是「评估矩阵」，它的「列」要么绑 Odoo 数据源字段，要么是手工格子，**没有"评分项"这个一等公民**。

---

### 2.3 `web_grid`（Grid 视图）——**不是「类 Excel 的矩阵录入」，社区版没有**

- **社区版不存在**：`odoo/addons/` 下无 `web_grid`；`web/static/src/views/` 只有 `calendar / form / graph / kanban / list / pivot`（`view.js:75-88` 的 `ViewType` 联合类型里写有 `"grid"`，那只是 arch 解析器的类型声明，**不代表实现存在**）。
- **企业版独占**：`web_grid/__manifest__.py:29` `'license': 'OEEL-1'`，`'depends': ['web']`，`'auto_install': True`；官方文档 Grid 章节首行原文 **"Grid ¶ Enterprise feature"**（<https://www.odoo.com/documentation/19.0/developer/reference/user_interface/view_architectures.html>）。Odoo 官方 editions 对照表亦将「Grid view」标为 Enterprise ✓ / Community ✗（<https://www.odoo.com/page/editions>）。
- **官方文档自陈局限**（同 URL，原文）：
  > "This view is a work in progress… **only date column fields have been tested**, selection and many2one are nominally implemented and supported but have not been tested, **datetime is not implemented at all**. **column cells are hardly configurable and must be numerical**; cell adjustment is disabled by default…"
- 源码语义（企业版 `web_grid/static/src/views/grid_arch_parser.js:73-110`）：`row` 字段（可多个）→ `col` 字段（**单个**，`_extractRanges` 生成 day/week/month 区间）→ `measure` 字段（**单个数值度量**）。`grid_model.js:426`：`this.columnFieldIsDate = this.fieldsInfo[params.columnFieldName].type === "date"`。`models.py:11-18` 的 `grid_update_cell(domain, measure_field_name, value)` 也说明「一格 = 一个聚合度量」。

⇒ **web_grid 的「列」是时间轴（日/周/月），不是「评分维度」。** 想用它做「行=被评估项、列=维度」是**方向性错误**；即便买了企业版也不成立。

---

### 2.4 `hr_appraisal`（员工考评）——**思路可抄，代码不可用**

- **企业版独占**：`hr_appraisal/__manifest__.py:53` `'license': 'OEEL-1'`，`'depends': ['calendar', 'hr_gantt']`（`hr_gantt` 本身也是企业版）；容器内无该模块代码，库内 `ir_module_module` 状态为 `uninstallable`。
- **可抄的 3 点**：
  1. **模板极薄**：`hr.appraisal.template`（`hr_appraisal/models/hr_appraisal_template.py:12-19`）只有 `department_ids` + 两段 HTML 反馈模板 —— 真正可配置的参数**不在模板里**，而在下一项。
  2. **自定义评估项 = `Properties` 字段**：`hr_appraisal/models/hr_appraisal.py:88`
     `appraisal_properties = fields.Properties("Properties", definition="department_id.appraisal_properties_definition", precompute=False)`
     —— **这是 Odoo 官方用来做「可自定义评估参数」的原生机制**，且 `Properties` 在社区版内核（§2.6）。
  3. **多源反馈 + 状态机**：`state: 1_new → 2_pending → 3_done`（`:58-63`）；`manager_ids`（`:64-68`）；员工/经理双份反馈 + 各自「是否公开」开关（`:73-82`）；终评 `assessment_note`（`:85`，员工不可见）。
- **官方文档补充的事实**：Appraisal 流程 = plans → 自评 → 经理反馈 → **Ask for feedback（360 Feedback）** → Appraisal review → 技能复盘 → Complete → **Provide a final rating** → Appraisal analysis（<https://www.odoo.com/documentation/19.0/applications/hr/appraisals.html>）；且**模板存在 `survey.survey` 里**（见 §2.1.7）。
- **不可用的**：代码不能进仓库，也不能装（OEEL-1 + 需企业版运行时）。

---

### 2.5 Odoo 列表视图本身的「Excel 式」能力边界（Path A 的地基）

> 注：Odoo 19 官方**没有独立的「List view」用户文档页**（在 19.0 的 `searchindex.js` 里搜 `list view` / `optional columns` 均 0 命中）。权威出处是**开发者参考**的 List 章节。

#### 2.5.1 官方文档与源码双重确认的能力

官方 `<list>` 属性文档（<https://www.odoo.com/documentation/19.0/developer/reference/user_interface/view_architectures.html#list>）：

| 属性 | 官方原文要点 | 源码 | 对我们的意义 |
|---|---|---|---|
| `editable` = `top`/`bottom` | "Make the view's records **editable in-place**, and allow creating new records from a row of the list." | `list_arch_parser.js:199`、`:204-206` | **格子里直接改** = A 的一半 |
| `multi_edit` = `'1'` | "Activate the multi-editing feature that allows **updating a field to the same value for multiple records at once**." | `list_arch_parser.js:200-202`、`list_renderer.js:1718` | 选中多行批量同值 |
| `import` | "Disable/enable record import from data on the view."（默认 **True**） | `import_records.js:42-48` | **D 的地基** |
| `export_xlsx` | "Disable/enable record export to data on the view."（默认 **True**） | `list_arch_parser.js:191` | **D 的地基** |
| `create` / `edit` / `delete` | 三者默认 True | `list_arch_parser.js:190-196` | 关掉 create 会**连导入一起关掉**（survey 就栽在这，§2.1.6） |
| 字段级 `optional` = `show`/`hide` | "Make the visibility of the field optional. **The field's column can be hidden or shown through a button on the view's header.**" | `list_renderer.xml:49-72`、`list_renderer.js:630-657` | **增删列**的官方形态 |

- **筛选 / 分组**：官方 <https://www.odoo.com/documentation/19.0/applications/essentials/search.html> 原文 "Odoo allows for the searching, filtering, and grouping of records in a view… click the (dropdown) icon to access the **Filter, Group By, and Favorites** drop-down menus"；自定义过滤 "Match all… (AND)" / "Match any… (OR)"。
- **批量选择**：官方 <https://www.odoo.com/documentation/19.0/applications/essentials/export_import_data.html> 原文 "activate the list view (List) icon… **tick the checkbox next to the corresponding record**. Finally, click the Action button, and select Export."
- **Excel 导出**：`web/controllers/export.py:688-723` `@http.route('/web/export/xlsx', type='http', auth='user')`，用 `xlsxwriter`（`:170-174`），行数超限报错 `:195`；`/web/export/formats`（`:291-304`）实测返回 `XLSX` 与 `CSV` 两项。
  ⚠ **官方文档用词滞后**：export_import_data 页仍写 "export in two formats: `.csv` and `.xls`"，但源码、路由与视图属性名一律是 **xlsx**（`export_xlsx`）。
- **Excel 导入**：`base_import`（已装、`auto_install=True`）客户端动作 `tag: "import"`，入口 `import_records.js:29-36`；官方文档 "Data can be imported on any Odoo business object using either Excel (.xlsx) or CSV (.csv) formats"。
- **Pivot 视图**：只读（控制器无编辑路径），但可直接下载 xlsx：`web/static/src/views/pivot/pivot_controller.xml:17`（`o_pivot_download`，tooltip "Download xlsx"）。

#### 2.5.2 **导入不能创建新字段**（对「加一列 = 加一个评分项」是硬约束）

官方文档 "Field missing to map column" 一节给出的唯一解法是：
> "check the **Show fields of relation fields (advanced)** option, then a complete list of fields becomes available for each column."
—— **只能从既有字段里挑，不能新建字段**。
源码侧：`base_import/models/base_import.py` **没有**创建 `ir.model.fields` 的代码路径（`:830` 那处 `IrModelFieldsUs` 只是以 en_US 语境读取字段描述；全文件无字段创建）。要加字段的正路是**写模块**或 **Studio（企业版独占**：官方 editions 对照表 Customization→Studio = Community ✗ / Enterprise ✓；`addons/web_studio` 在 odoo/odoo 的 16.0–19.0 全部不存在）。

#### 2.5.3 哪里**不像** Excel（必须讲清楚）

1. **列 = 模型字段** ⇒「加一列」= 改数据库 schema（需开发者写模块，或企业版 Studio），**不是**在界面上加一格。
2. **没有自由单元格**：不能合并/拆分、不能插入空白行、不能随便在任意格子写公式。
3. **一个单元格 = 一条记录的一个字段值**，不是「任意二维表」。
4. **列表视图没有公式引擎**；Pivot 能汇总但不能回写。
5. 真正的「批量填一张表」体验要**靠分组模拟**：「按学生分组 + 评分项各占一行 + 内联编辑」，视觉上是「每个学生一个小块」，**不是一整张连续大表**。

#### 2.5.4 一个常被忽略的取舍：**行列可以转置**

队长定义的 A 是「**行 = 学生，列 = 评分项**」。Odoo 列表视图与 Moodle grader report 都是「**行 = 记录、列 = 字段**」——把「评分项」做成字段就把行列关系对上了，代价是**每次加评分项都要发版**；反之把「评分项」做成行（`edu.eval.item` 表）则**加评分项零成本**，但表格变成「一列分数」。
**这个取舍是本次设计最关键的一处**，且两边都有成熟先例（Moodle = 列是成绩项；宜搭子表单 = 行是明细）。**待向校长确认口径**（见 §8 #15）。

---

### 2.6 `Properties` 字段（社区版内核）——B 的关键原生机制

`odoo/orm/fields_properties.py:32-51`（docstring 原文）：
> "Field that contains a list of properties (aka 'sub-field') based on a definition defined on a container. Properties are **pseudo-fields**, acting like Odoo fields but **without being independently stored in database**. This field allows a light customization based on a container record. … **New properties can be created on the fly without changing the structure of the database.**"

- 底层列类型 `jsonb`（`:53` `_column_type = ('jsonb', 'jsonb')`）；`store=True, readonly=False, precompute=True`（`:59-61`）。
- 允许的类型（`:80-87`）：`boolean / integer / float / text / char / html / date / datetime / monetary / many2one / many2many / selection / tags / separator`。
- 定义容器侧用 `PropertiesDefinition`（`:844`）；`definition="<record>.<field>"` 形式（`:93-102`）。
- **界面侧在社区版**：`web/static/src/views/fields/properties/`（`properties_field.js`、`property_definition.js/.xml` 等 20 余个文件），注册点 `properties_field.js:1012` `registry.category("fields").add("properties", propertiesField)`。
- **在列表视图里表现为「可选列」并可分组增删**：`list_renderer.js:630-657`（`col.relatedPropertyField` → `propertyGroups[id]`）。
- 官方用户文档专章：<https://www.odoo.com/documentation/19.0/applications/essentials/property_fields.html>。

**它的边界**：Properties 是「**每条记录一份键值字典**」，**不是「列 = 评分项」的矩阵**。想用它表达「学生 × 评分项」的二维网格，需要自研一层「定义(sub-field) ↔ 评分项」映射并把 `Properties` 放对模型——**能解决 B 的「在线加参数」，但解决不了 A 的「一整张表」**。

---

### 2.7 D 的地基：`base_import` + 导出

| 事实 | 依据 |
|---|---|
| `base_import` 已装、`auto_install=True`、**LGPL-3** | `base_import/__manifest__.py:28/43`；库内 `state=installed` |
| 导入支持 `.xlsx` / `.csv` | 官方文档 export_import_data |
| 导入菜单出现条件 = list/kanban ∧ `import` 未禁用 ∧ **`create` 未禁用** | `import_records.js:42-48` |
| 导出菜单出现条件 = list/kanban ∧ 无选中 ∧ **`base.group_allow_export`** ∧ `export_xlsx` 未禁用 | `export_all.js:34-38` |
| 导入可**按 External ID 反复更新同一批记录**（不产生重复） | 官方文档原文 "**Update imports**: import the same file several times without creating duplicates."（须勾 "I want to update data (import-compatible export)"） |
| 导入**不能新建字段** | §2.5.2 |

> **结论（本报告最可操作的一条）**：**任何自研模型，只要它的列表视图不写 `create="false"`，就免费获得「xlsx 批量导入 + xlsx 导出 + 按外部 ID 幂等更新」**。这正好就是队长定为必须项的 **D**，也是钉钉宜搭「子表单」与 Canvas `gradebook_csv` 走通的同一条路。

---

## 3. OCA（先看 license）

### 3.1 结论：**OCA 侧没有任何现成的「可自定义评估 / 评分表」模块可装**

| 检查项 | 一手结论 | 依据 |
|---|---|---|
| `OCA/vertical-education` 19.0 分支 | **存在，但零模块**。`git/trees/19.0` 只有 **14 项**且全是配置/许可证：`.copier-answers.yml / .editorconfig / .gitattributes / .github / .gitignore / .pre-commit-config.yaml / .pylintrc / .pylintrc-mandatory / .ruff.toml / LICENSE / README.md / checklog-odoo.cfg / eslint.config.cjs / prettier.config.cjs` | `gh api repos/OCA/vertical-education/git/trees/19.0` |
| 该仓 license | **AGPL-3.0**（默认分支 18.0，`pushed_at 2025-09-30`） | `gh api repos/OCA/vertical-education` |
| `OCA/hr` 19.0 | **无 `hr_appraisal_oca`**（19.0 只有 11 个 `hr_employee_*` 类模块 + `hr_course`）。逐分支：16.0 ✅ / 17.0 ❌ / 18.0 ✅ / **19.0 ❌**；未见 19.0 迁移 PR | `gh api repos/OCA/hr/contents/?ref=19.0` |
| `OCA/knowledge` 19.0 | 只有 `document_page*` / `document_knowledge` / `document_url`，**无评估类** | — |
| 全组织搜索 `appraisal` / `grade` / `assessment` / `score` / `rating` / `criteria` / `competency` | **各 0 条**；`evaluation` 只命中 `OCA/maintainer-tools`（无关） | `gh search repos --owner OCA …` |

### 3.2 但有两个**真的能用**的 OCA 件（均 AGPL-3.0）

| 模块 | 19.0 可用 | license | 作用 | 对我们 |
|---|---|---|---|---|
| **`OCA/survey`**（19.0 有 **18 个模块**，`pushed_at 2026-09-14`） | ✅ | **AGPL-3.0** | 最相关的：`survey_question_type_model_selection`（**新增题型「从模型选取」**，README 原文 "This module add **Model selection field question type**"，maturity Beta）、`survey_result_mail`（答卷邮件 + QWeb 报表）、`survey_certification_sending`、`survey_answer_generation`（"Link and compare answers from another survey"）、`survey_skip_start`、`survey_multi_company` 等 | **「答案绑真实记录」的唯一 OCA 线索**——正好补 §2.1.4 的缺口。⚠ 但 `survey_xlsx`（答卷导出 XLSX）**只在 18.0 有，19.0 没有** |
| **`OCA/spreadsheet`**（19.0 有 4 个模块，`pushed_at 2026-08-19`，84★） | ✅ | **AGPL-3.0** | `spreadsheet_oca`（19.0.1.0.1）manifest 原文：`"summary": "Allow to edit spreadsheets"`，`depends: ["spreadsheet", "base_sparse_field", "bus"]`；DESCRIPTION 原文：**"This module adds a functionality for adding and editing Spreadsheets using Odoo CE. It is an alternative to the proprietary module `spreadsheet_edition` of Odoo Enterprise Edition."** | **这是 Path B 在社区版唯一被验证过的补齐路径**（§6.2）——**代价是 AGPL-3.0** |

### 3.3 ⚠ AGPL-3.0 传染性红线（必须先评估再决定）

OCA 全部相关仓库均为 **AGPL-3.0**。AGPLv3 第 13 条把 GPLv3 第 3 条义务扩展到**网络交互**：以 AGPL 代码构成的服务通过网络提供交互时，必须向使用者提供对应源码。参考：<https://www.gnu.org/licenses/agpl-3.0.html>（§13 Remote Network Interaction）。
**对本项目的含义**：本项目是**面向学生/教师的网络服务**，属 AGPL 第 13 条的典型场景。引入任何 AGPL-3.0 模块（哪怕一个）都可能触发**整站源码开放义务**争议。
⇒ **在拿到法律意见前，不要把 `OCA/survey` / `spreadsheet_oca` 等 AGPL 模块装进生产**；若确需「抄思路」，应**只读源码后在 `custom_addons/edu_*` 从零实现**（与仓内既有做法一致：`/Users/qwe/odoo-enterprise-ref/README.md` 三条铁律）。
⚠ 注意 `spreadsheet_oca` `depends` 的 `spreadsheet` 本身是 **LGPL-3**（§2.2.1）；AGPL 只来自 OCA 那层薄壳——所以「不看 OCA 代码、直接基于 LGPL 的 `o-spreadsheet` 自研一层编辑动作」在许可上是干净的（但那就等于自己写代码）。

---

## 4. 同类开源系统（Moodle / Canvas）

> 取证方式：`docs.moodle.org` 全站 Cloudflare 403（直连与代理 `http://127.0.0.1:12450` 均 403，返回 "Moodle challenge" 页），Moodle 文档正文取自 **Wayback Machine 2024 快照**并同时给出官方 URL；代码结论一律以 `raw.githubusercontent`（分支 + 行号）为准。Canvas API 文档 `canvas.instructure.com/doc/api/` 可直连（200）。

### 4.1 Moodle

| 能力 | 结论 | 一手来源 |
|---|---|---|
| **Feedback 活动**题型 | 8 种：Captcha / Information / Label / Longer Text / Multiple choice / **Multiple choice (Rated)**（选项带分值）/ Numeric / Short Text；另有题目依赖（Dependence item / Dependence value） | `mod/feedback/item/` 目录 <https://github.com/moodle/moodle/tree/MOODLE_405_STABLE/mod/feedback/item>；<https://docs.moodle.org/en/Building_Feedback> |
| Feedback **是否计分** | **不计分**。`mod/feedback/lib.php:66-67` `case FEATURE_GRADE_HAS_GRADE: return false; case FEATURE_GRADE_OUTCOMES: return false;`，全文件 `grade_item_update` 出现 0 次 | <https://github.com/moodle/moodle/blob/MOODLE_405_STABLE/mod/feedback/lib.php#L66-L67> |
| Feedback 多次作答 / 匿名 / 导出 | 全部支持：`multiple_submit`（`mod_form.php:82-99`）、`anonymous`（`:64-68`）、`analysis_to_excel.php`（Excel 导出） | 同上 |
| **Questionnaire 插件**（第三方，非核心） | 题型含 **Scale**（文档原文 "can customize in many ways"）；导出 csv / xlsx / HTML / json / ods / pdf **6 种**；**有成绩**：`lib.php:470 questionnaire_grade_item_update()` → `:487-491 gradetype = GRADE_TYPE_VALUE / GRADE_TYPE_SCALE` → Moodle `grade_update()` | <https://github.com/PoetOS/moodle-mod_questionnaire/blob/MOODLE_500_STABLE/lib.php#L470-L491>（91★，**无 main 分支**） |
| Questionnaire 的「矩阵题 / 重复问题」 | **未验证**（文档题型表与 README 均无，源码未核实） | — |
| **Rubric（评分量规）** | 三层结构：`grading_definitions`（表单定义）→ `gradingform_rubric_criteria`（**行**：sortorder / description）→ `gradingform_rubric_levels`（**列**：score / definition）；SQL 见 `grade/grading/form/rubric/lib.php:310-340`；编辑器元素 `rubriceditor`（`edit_form.php:29`） | <https://github.com/moodle/moodle/blob/MOODLE_405_STABLE/grade/grading/form/rubric/lib.php#L310-L340> |
| Rubric 的权重怎么表达 | **官方文档原文**：给某 criterion 的 level 设 0/1/2/3 与 0/2/4/6，则后者影响是前者**两倍**——**权重靠分值表达，不需要单独的 weight 字段**；**支持负分**（如迟交扣分）；有 Remarks；可用 Tab 键快速录入；3.2+ 支持 "minimum score of 0" | <https://docs.moodle.org/en/Rubrics> |
| **Gradebook 能否自定义列 / 加权 / 手工录入** | 能。官方原文 "**Grade items are represented by columns in the grader report**"；Gradebook setup → Add grade item（Grade type: None / Value / Scale / Text）；类别聚合支持 weighted mean of grades、Drop the lowest、Keep the highest；grader report 可直接改分、可切 Single view | <https://docs.moodle.org/en/Grade_items>、<https://docs.moodle.org/en/Grade_categories>、<https://docs.moodle.org/en/Gradebook> |
| **有没有「行=被评估项、列=维度」的矩阵批量录入** | **没有**。grader report 是「**列=成绩项、行=学生**」（与队长要的 A 恰好**转置**）；rubric 是「每次一个提交」的表单；Feedback / Questionnaire 的分析页是只读统计 | 同上一行 + `grade/grading/form/rubric/` 目录 |

### 4.2 Canvas（Instructure）

| 能力 | 结论 | 一手来源 |
|---|---|---|
| **Rubrics** 数据结构 | `Rubric`（`points_possible` / **`reusable`** / `free_form_criterion_comments` / `hide_score_total`）；`RubricCriterion`（`points` / `criterion_use_range` / `ratings[]`）；`RubricRating`（`points`）；`RubricAssociation`（purpose = **grading / peer_review / provisional_grade**） | <https://canvas.instructure.com/doc/api/rubrics.html> |
| 可复用到多个作业 | 有。`scope :publicly_reusable, -> { where(reusable: true)… }`；源码注释原文 "The other purpose of this class is just to **make rubrics reusable**." | `app/models/rubric.rb#L80`、`app/models/rubric_association.rb#L24` |
| 自由文本 / 区间给分 | 有：`free_form_criterion_comments`（API 文档原文 "Whether or not you can write custom comments in the ratings field for a rubric"）、`criterion_use_range` | 同上 API 文档 |
| **Outcomes** | 含 `mastery_points` / `calculation_method` / `ratings`，可内嵌 rubric criterion；**计算方式枚举**（源码 `app/models/outcome_calculation_method.rb:26-45`）：`decaying_average / weighted_average / standard_decaying_average / n_mastery(1..10) / highest / latest` | <https://canvas.instructure.com/doc/api/outcomes.html>、<https://canvas.instructure.com/doc/api/outcome_results.html>、`app/models/outcome_calculation_method.rb#L26-L45` |
| Outcome 与评分怎么挂 | `rubric_criterion.rb:25 belongs_to :learning_outcome`；`rubric.rb:58 has_many :learning_outcome_alignments`；评分时生成 `learning_outcome_result`，在 Learning Mastery Gradebook 查看 | `app/models/rubric_criterion.rb#L25` |
| Gradebook 能否像 Excel 批量编辑 | **最接近的一条**：批量改分 API `POST /api/v1/courses/:course_id/submissions/update_grades`；可加自定义列（Custom Gradebook Columns API，原文 "API for adding additional columns to the gradebook"）；**有 CSV 批量导入/导出**（`gradebook_csv.rb` / `gradebook_upload.rb` / `gradebook_csvs_controller.rb` / `gradebook_uploads_controller.rb`） | <https://canvas.instructure.com/doc/api/submissions.html>、<https://canvas.instructure.com/doc/api/custom_gradebook_columns.html>、`app/models/gradebook_csv.rb` |
| SpeedGrader | **逐个学生 / 逐个提交**的界面，不是批量录入 | `app/models/speed_grader/assignment.rb`；官方指南正文 JS 渲染，**未逐字验证** |
| 有没有「行=被评估项、列=维度」矩阵 | **没有**。Canvas 最「像 Excel」的是 Gradebook 网格（横向批量改分 + 自定义列 + CSV 往返） | 同上 |

### 4.3 对我们最可抄的 3 点

1. **把「评估表」建模成「模板 + 行(criteria) + 列(levels/分值) + 关联(实例)」三层**，模板可复用、可排序、可版本化。
   Moodle：`grading_definitions → rubric_criteria(sortorder) → rubric_levels(score)`；Canvas：`Rubric(reusable) → RubricCriterion(points) → RubricRating(points)` + `RubricAssociation`。**表格是模板，每次评估只是一个实例**——这正是「参数丰富 + 可自定义」的成熟形态。
2. **「权重」用分值表达，另加「区间给分 + 自由评语」两件套**，比「每格一个数」强。Moodle 文档明写 score 0/2/4/6 即两倍影响且支持负分；Canvas 有 `criterion_use_range` 与 `free_form_criterion_comments`。⇒ 建议我们的单元格模型 = **分值 + 可选区间 + 可选评语**。
3. **批量录入优先抄「网格 + CSV/xlsx 往返 + 自定义列」，而不是自造矩阵编辑器**——Canvas `gradebook_csv` / `custom_gradebook_columns` / 批量 `update_grades` 与 Moodle grader report + Add grade item 都是这个套路。**先做「导出空表 → 填 → 导回」，再做真·网格**，成本低且被两套成熟系统验证过。
   附带可抄项：Canvas Outcomes 的 `calculation_method` 六个枚举可直接做成「综合评估汇总算法」下拉；Moodle Feedback 的 Dependence item/value 可抄成评估项的显示依赖。
   若要「评估结果进成绩册」，**抄 Questionnaire 而不是 Feedback**（Questionnaire 实现了 `grade_item_update`；Feedback 显式 `FEATURE_GRADE_HAS_GRADE: return false`）。

---

## 5. 国内同类（功能名 + 官方 URL 级证据）

### 5.1 逐产品事实

**问卷星**（帮助中心基址 `https://www.wjx.cn/help/help.aspx?helpid=N`，helpid 索引取自官网页脚）

| 功能名 | URL | 核验 |
|---|---|---|
| 评分题（评分单选题，选项带分值） | <https://www.wjx.cn/help/help.aspx?helpid=225> | ✅「设置选项以及分值」 |
| 评价题（打分 + 每分值挂标签 + 自主评价） | <https://www.wjx.cn/help/help.aspx?helpid=534> | ✅ |
| 矩阵题 / 矩阵量表题（选项可设分值，出「行平均分」） | <https://www.wjx.cn/help/help.aspx?helpid=160> | ✅ 含行平均分公式 |
| 表格题（表格下拉框 / 表格填空） | <https://www.wjx.cn/help/help.aspx?helpid=168> | ✅ |
| 自增表格题（可增行 + 列属性校验） | <https://www.wjx.cn/help/help.aspx?helpid=423> | ✅「默认显示行数/最大允许行数/列标题/**列属性**…年龄可验证为整数并设最小最大值」 |
| **360度评估**（维度设置 + 维度权重占比 + 上级/下级/同事分别设权） | <https://www.wjx.cn/help/help.aspx?helpid=368>、向导 <https://www.wjx.cn/help/help.aspx?helpid=246> | ✅「**权重加总必须等于100%**」 |
| **AHP 层次分析模型**（自动算权重 + 一致性检验 + 判断矩阵） | <https://www.wjx.cn/help/help.aspx?helpid=718> | ✅ |

**腾讯问卷**（官方文档，云文档域）

| 功能名 | URL | 核验 |
|---|---|---|
| **矩阵评价**（多个问题 × 带分值评价选项，逐行评分，自动统计各维度得分） | <https://cloud.tencent.com/document/product/1304/133322> | ✅ 含「统计公式」小节 |
| 矩阵量表（两极文案、量表 1–100） | <https://cloud.tencent.com/document/product/1304/133321> | ✅ |
| 矩阵单选 / 多选 / 矩阵填空 | `…/133319`、`…/133320`、`…/133308` | ✅ |
| 评价打分（图形数量选择） | <https://cloud.tencent.com/document/product/1304/133311> | ✅ |
| 自增表格（用户自主增加表格行数） | <https://cloud.tencent.com/document/product/1304/133307> | ✅ |
| 开放能力（API / Webhook / 自定义字段） | <https://wj.qq.com/docs/> | ✅ |

**校管家**（真实域名 **xiaogj.com**；注意不是 xiaoguanjia.com）

| 功能名 | URL | 核验 |
|---|---|---|
| 老师课堂点评的评价维度 | <https://helpcenter.xiaogj.com/help-list/detail-113.html> | ✅「设置评价维度 > 新增」，**适用科目可多选/不限** |
| 家长评价老师的评价维度 | <https://helpcenter.xiaogj.com/help-list/detail-141.html> | ✅ 自定义维度名 + **显示顺序** + **必评项** |
| 评测管理 | <https://wiki.xiaogj.com/docs/ping-ce-guan-li> | ✅ 但那是**考试闭环**（题库→组卷→自动评分→成绩报告），不是加权评分表 |
| **结论** | 有「自定义评价维度」，**未发现「自定义评估表模板 + 指标权重」**；形态是「送星星打分」，**无 Excel 网格** | — |

**希沃**（教育评价做得最深）

| 功能名 | URL | 核验 |
|---|---|---|
| 综合评价管理员操作手册 | <https://help.seewo.com/webcube/DC89yqZER5> | ✅ |
| 校级学生评价指标修改（一级/二级指标 + 点评项） | <https://help.seewo.com/zp/rwbsCqQKrl> | ✅ |
| **教师自定义指标权限**（教师自定义指标自动与学校一二级指标关联 + 管理员审核） | <https://help.seewo.com/zp/Gha2miK2K4> | ✅ |
| 班级评价体系设置（**批量导入点评项目**、起始分、周/月汇算） | <https://help.seewo.com/zp/b2AWn4cHrJ> | ✅ |
| **结论** | 多层指标体系 + 教师自定义 + 审核 + **指标批量导入**；但**填报端是点选送星**，**未发现权重** | — |

**钉钉**（宜搭「子表单」是全国最像 Excel 的一块）

| 功能名 | URL | 核验 |
|---|---|---|
| 智能填表 | <https://open.dingtalk.com/document/development/intelligent-form-filling-overview> | ✅ |
| 宜搭·评分字段（总分值=星级上限、半星、显示分数） | <https://docs.aliwork.com/docs/yida_support/wtwabe/up3ftx/gg9qu3> | ✅ |
| **宜搭·子表单** | <https://docs.aliwork.com/docs/yida_support/wtwabe/up3ftx/in0w72> | ✅ 官方原句：「**支持 Excel 批量导入数据**（50条/次）」「支持主表单数据 + 子表单数据**一并导出**」「导出本地 Excel 后，经数据内容编辑，**子表内容支持重新导回到宜搭表单数据中**」，另有 **子表列宽自定义、列冻结最多 5 列、表格/平铺两种排列** |
| 表单公式（100+ 函数） | <https://docs.aliwork.com/docs/yida_support/wtwabe/cnzrgo/gvtpe4> | ✅ |

**企业微信**

- **收集表** <https://open.work.weixin.qq.com/help2/pc/cat?doc_id=17723> ✅ 题型含文本/单选/多选/下拉/数字/金额/图片/文件/签名题/**表格题**…
  ⚠ **收集表没有「评分/打分/量表」题型**；表格题「可在一道题中收集多份答案」但仅 1–10 行 ⇒ **不能原生做加权评分表**。
- **智能表格** <https://open.work.weixin.qq.com/help2/pc/19678> ✅ 公式、查找引用、自动编号、操作记录、AI 字段、公式模板库、接收外部数据、API 批量管理数据（<https://developer.work.weixin.qq.com/document/path/99896> 🟡 仅导航可证）。**企微侧真正的评估表载体是智能表格，不是收集表。**

**飞书·多维表格 Bitable**（最像 Excel，且双向可嵌）

- 官网 <https://base.feishu.cn/> ✅「是 ai 表格，也是业务系统的 ai 搭建平台」
- **评分字段** <https://www.feishu.cn/hc/zh-CN/articles/788252329598> ✅「星星/爱心/数字图标…最小值默认 1 可选 0 或 1；最大值默认 5 可选 1–10 中任意整数…可作为看板视图的分组依据」；支持把多行文本/数字/单选/公式/查找引用**转换为评分字段**
- **公式字段** <https://www.feishu.cn/hc/zh-CN/articles/360049067853> ✅「支持 100 多个函数」，整列引用 `SUM([数据表].[目标字段])`（**即 Excel 的 A:A 语义**）
- **开放能力（双向）**
  - 出：OpenAPI 开放 App / 数据表 / 视图 / 记录 / 字段 / 仪表盘 / 高级权限 <https://open.feishu.cn/document/server-docs/docs/bitable-v1/bitable-overview.md> ✅；限制：单次批量 1000 条、全成或全败、单表同时只发一次写
  - 入：**多维表格插件**，开发者可「直接在多维表格中嵌入自己开发的产品」<https://open.feishu.cn/document/base-extensions/base-extension-introduction.md> ✅

**其他更贴切的国产评教 / 综评 SaaS**

| 产品 | 功能名 | URL | 核验 |
|---|---|---|---|
| **校管易·易评教**（最贴切的国产评教 SaaS） | 听课评课 / 学生评教 / 多维统计 / 透视 | <https://xiaoguanyi.com/products/easy-teaching-evaluation> | ✅「**灵活拆解并赋分指标**」「**评价总表按需输出**，不再手工合算」「**指标自定义关联数据**」「评课打分随堂录入，**指标模板可配置**」「结果匿名汇总」 |
| 问卷网 | 评价打分题（分值说明 + 标签 + 启用写评价）；另有 **360评估** 产品线 | <https://www.wenjuan.com/helpcenter/detail/5dd63cdba320fc570b6f6e83/>、<https://www.wenjuan.com/helpcenter/> | ✅ |
| 金数据 | 表格字段 / 计算字段 / 矩阵字段 / 表单关联字段 | <https://help.jinshuju.net/next/category/build-and-publish/> | ✅ |
| 恒谦教育 学生发展评价 | 个性化评价指标 | <https://www.hengqian.co/html/main/product/studentEval.html> | ❌ 未验证 |
| 物思 学生综合素质评价 | 自定义评价体系 | <https://www.topeti.com/h-nd-490.html> | ❌ 未验证 |

### 5.2 国内产品里最像 Excel 的三条事实

1. **钉钉宜搭「子表单」是唯一把「Excel 往返」做进表单的产品**：官方原文明确「支持 Excel 批量导入数据（50 条/次）」「主表 + 子表数据一并导出」「导出编辑后**支持重新导回**」，加上子表列宽自定义、列冻结最多 5 列、表格/平铺两种排列 —— 数据在「表格」与「Excel 文件」之间**可往返**，别家都没有。
2. **飞书多维表格是唯一「既是表格、也是系统」且双向可嵌的载体**：字段层有**评分字段**（1–10 星/心/数字）+ **公式字段**（100+ 函数，整列引用 = Excel 的 A:A 语义）+ 仪表盘；开放层 OpenAPI 直接开放文档/记录/字段/视图；反向还有插件把第三方产品嵌入多维表格内部。
3. **问卷类（问卷星/腾讯问卷/问卷网）只做到「网格题」，没有「自由单元格」**：三家都稳定提供矩阵题/矩阵量表/矩阵评价 + 表格题/自增表格，自增表格甚至能动态加行并按列做类型校验 —— **但列结构由设计者预先固定，填写者永远不能自由增删列**。真正做「维度 + 权重」的是**另一条产品线**：问卷星的 **360度评估**（维度权重占比，加总必须 = 100%）与 **AHP 层次分析模型**（自动算权重 + 一致性检验 + 判断矩阵）。

> **对本项目的映射**：「参数丰富 + 可自定义」在国产产品里的成熟答案 = **维度/指标字典 + 权重占比 + 必评标记**（问卷星 360度评估、希沃一/二级指标、校管家评价维度、校管易「指标模板可配置」）；「像 Excel」的成熟答案 = **评分字段 + 公式字段 + xlsx 往返**（飞书多维表格、宜搭子表单）。**「真的做成自由单元格 Excel」——国内没有任何一家做成。**

---

## 6. 三条路径逐条给证据 + 代价 + 风险

### 6.1 路径 A：Odoo 原生列表视图内联编辑

**能到什么程度**
- **格子里直接改**：`editable="bottom"`（官方原文 "editable in-place"；`list_arch_parser.js:199`）
- **选中多行批量同值**：`multi_edit="1"`（官方原文 "updating a field to the same value for multiple records at once"）
- **筛选 / 分组 / 排序 / 可选列 / 列宽拖拽**：原生（`list_renderer.xml:49-72`；`:42` 双击重置列宽）
- **xlsx 导入**：`base_import`，任何 `create` 未禁用的 list/kanban 视图免费获得（`import_records.js:42-48`）
- **xlsx 导出**：`/web/export/xlsx`（`web/controllers/export.py:688`），`export_xlsx` 默认 true（`list_arch_parser.js:191`）
- **Pivot 汇总 + 下载 xlsx**（只读）
- 全部能力在 `addons/web`（社区版），**非 Enterprise**

**哪里不像 Excel**
- 列 = 模型字段，「加一列」= 改 schema（`base_import` 不能建字段，§2.5.2）
- 无自由单元格（合并 / 插行 / 任意公式）
- 「行=学生、列=评分项」的连续大表要**靠分组模拟**（按学生分组 + 评分项各占一行），视觉上是「每个学生一个小块」
- 无公式引擎

**代价**：写一个 Odoo 模块（模型 + 视图 + ACL / 门户控制器），**不写表格引擎、不写导入导出**。工作量集中在数据模型与权限。
**风险**：低（LGPL-3 原生能力）。**唯一的坑**：把评分项做成真实字段 ⇒ 每次加评分项都要发版；必须改用 `Properties`（§2.6）或「评分项行表」建模规避。
**打分**：A **部分** / B **部分** / D **满足**。

---

### 6.2 路径 B：Odoo 内置 spreadsheet

**能否嵌入门户**：能分享**只读**页（`/dashboard/share/<id>/<token>`，`auth='public'`，`share.py:41`）。
**能否持久化用户编辑**：**纯社区版不能**（`o_spreadsheet.js:78149/78288` 只允许 `readonly`/`dashboard` 两种只读模式；`action_edit_dashboard` 属 OEEL-1）。
**出口**：`exportXLSX` 在引擎里（`o_spreadsheet.js:78506`）；公开页 `excel_export` 由 `action_get_share_url` 预生成（`spreadsheet_dashboard_share.py:15/25-33`）——但**门户学生下载不了**（§2.2.3）。
**许可与维护状态**：引擎 `o-spreadsheet` = **LGPLv3**（可自由使用）；**编辑能力 = OEEL-1 闭源企业版**（`spreadsheet_edition`、`spreadsheet_dashboard_edition` 均 `'license': 'OEEL-1'`）。上游活跃（`pushed_at 2026-09-17`）。
**唯一的社区版补齐路径**：`OCA/spreadsheet` 的 `spreadsheet_oca`（19.0 已有，README 原文 "adding and editing Spreadsheets using Odoo CE… an **alternative to the proprietary module `spreadsheet_edition`**"）——**技术可行，但 license = AGPL-3.0**（§3.3 红线）。

**结论**：**纯社区版 Path B 出局**（只读）；**AGPL 补齐路径出局**（许可红线）；**企业版也不满足 B**——它是「自由表格」，「评分项」不是它的一等公民，评分项的增删改仍要在别处做。

---

### 6.3 路径 C：第三方电子表格嵌入

**⚠ 最重要的一个坑：Univer OSS（Apache-2.0）里没有 xlsx 读写**。实测其 60 个 `packages/*` 清单（`gh api repos/dream-num/univer/contents/packages`）**不含任何 xlsx 导入/导出包**；`@univerjs/sheets-import-xlsx` 在 npm 上 `Not Found`；唯一做 xlsx 交换的是 **`@univerjs-pro/exchange-client`（npm 元数据 `license: null`，即商业授权）**，其 `@univerjs-pro/*` 包**包内无 LICENSE 文件、package.json 无 license 字段**，靠 license key 插件执行，官方原文："Univer Pro is released under the Univer Commercial License. You can use it without a license for evaluation, but there will be limits such as watermark, import size, and collaboration quotas."
⇒ **要免费拿到 D（xlsx 进出），必须「Univer OSS 做界面 + SheetJS CE 做 xlsx 读写」两件套**，或改用 jspreadsheet CE，或买商业授权。

| 库 | 官方 URL | license（精确） | 维护状态（2026-09-18 实测） | 能否嵌入 Odoo 门户 | 移动端 | xlsx 进出（D） |
|---|---|---|---|---|---|---|
| **Univer OSS** ⭐ | <https://github.com/dream-num/univer> · <https://univer.ai> | **Apache-2.0**（根 LICENSE + 实测 60 个 `packages/*/package.json` 全为 Apache-2.0）。**`@univerjs-pro/*` 除外 = 商业授权** | **活跃**：`pushed_at 2026-09-18T01:02:16Z`，**14396★**，release **v0.25.2（2026-09-17）**；**但仓库根版本仍是 `1.0.0-rc.0`（未 GA）** | ✅ 最合适：纯前端 TS SDK，可直接进 `web.assets_frontend` / OWL 组件 | **官方标 experimental**（"Mobile Support" 章节；移动/桌面 UI 插件互斥） | ❌ **OSS 内没有**；要靠 `@univerjs-pro/exchange-client`（商业） |
| Luckysheet | <https://github.com/dream-num/Luckysheet> | **MIT** | **已归档**：`archived: true`，最后 commit `2025-08-19`（仅改文档链接），**最后 npm 发布 2.1.13（2021-01-19）**，16639★；README 推荐迁 Univer | 技术上可（canvas + jQuery 2.2.4），已弃用 | ❌ 无官方移动支持 | 需另配 Luckyexcel |
| x-spreadsheet | <https://github.com/myliang/x-spreadsheet> | **MIT**；npm `x-data-spreadsheet@1.1.9` MIT | **弃坑**：最后 commit `2023-08-15`，末次 release **v1.1.7（2020-09-13）**；继任者 `wolf-table/table` 也停在 `2024-08-07`（676★） | 可 UMD 引入 | ❌ issue #329 "Use on mobile phones" 仍 open | 无 |
| **Handsontable** ⛔ | <https://github.com/handsontable/handsontable> · <https://handsontable.com> | **非开源（source-available）**。`LICENSE.txt` 原文："dual-licensed — depending on whether your use for commercial purposes… **If your use is strictly personal or solely for evaluation purposes**, you agree to be bound by the terms included in the 'handsontable-non-commercial-license.pdf'… **Your use of this software for commercial purposes is subject to the terms included in an applicable license agreement.**"；npm `handsontable@18.1.1` `license: "SEE LICENSE IN LICENSE.txt"`。**改授权的版本 = 7.0.0（2019-03-06）**：v6.2.2 还是 MIT，v7.0.0 release notes 原文 "The MIT license has been replaced with custom, **free for non-commercial** license." | 活跃（`pushed_at 2026-09-17`，22043★，18.1.1 / 2026-09-15） | 技术上好嵌，**授权上不能** | ✅ 触控最强（CHANGELOG 2026 年仍在修 iPad/触控） | 有，但**须付费**（Standard **$999/开发者**起，Priority $1299 起；免费 Hobby 仅 "personal, exploratory projects"） |
| jspreadsheet **CE** | <https://github.com/jspreadsheet/ce> · <https://jspreadsheet.com> | **CE = MIT**；**Pro = 商业**（npm `jspreadsheet-ce@5.0.4` 的 license 字段为 `None`，属元数据缺失） | 活跃（CE `pushed_at 2026-09-17`，7226★；npm 5.0.4 / 2025-08-25） | ✅ 轻量直接嵌（UMD/CDN），无需构建链 | ⚠️ 官方有 "Mobile touch improvements" 记录，**手机端最省心** | ❌ **CE 不含 xlsx 导入导出**；Pro（Enterprise $249/月·$2499/年·$7499 永久）才有 |
| **SheetJS / `xlsx`** | <https://git.sheetjs.com/sheetjs/sheetjs> · <https://sheetjs.com>（GitHub 已是镜像 <https://github.com/SheetJS/sheetjs>） | **CE = Apache-2.0**：<https://docs.sheetjs.com/docs/miscellany/license> 原文 "SheetJS Community Edition is licensed under the 'Apache 2.0 License'. All rights not explicitly granted by the Apache 2.0 License are reserved by SheetJS LLC."，**并强制署名**（要求把 "SheetJS Community Edition -- https://sheetjs.com/… " 放入开源声明页）；**Pro 另按商业条款（价格未公开 → 未验证）**。⚠ `cdn.sheetjs.com` 上没有单独授权页（`/LICENSE`、`/terms` 实测 404） | 新仓库最后 commit **2026-02-09**，当前 **0.20.3**；**npm 公共 registry 的 `xlsx` 停在 0.18.5（2022-03-24）**，新版只从 cdn.sheetjs.com 发；GitHub 镜像 `pushed_at 2024-04-18`，36339★ | ✅ 不是 UI，是纯读写引擎，可配任何方案 | —（无 UI）；手机上传/下载 xlsx 反而必需 | ✅ **CE 就是干这个的** |
| **Odoo `o-spreadsheet`**（可直接复用的引擎） | <https://github.com/odoo/o-spreadsheet> | **LGPLv3**（LICENSE 原文；npm `@odoo/o-spreadsheet@19.0.50`） | 活跃（`pushed_at 2026-09-17`，289★） | ✅ 就是 Odoo 自己的前端组件，与 Odoo 同源、**无需适配层** | 与 Odoo 移动端一致 | ✅ 引擎内置 `exportXLSX`（`o_spreadsheet.js:78506`）；缺的只是「编辑动作」那一层 |
| `OCA/spreadsheet` `spreadsheet_oca` | <https://github.com/OCA/spreadsheet> | **AGPL-3.0** | 活跃（`pushed_at 2026-08-19`，84★） | 能（后端集成好） | 与 Odoo 一致 | 能 |
| 其他：AG Grid | <https://github.com/ag-grid/ag-grid> | **Community = MIT**；**Enterprise = Commercial**（`packages/ag-grid-enterprise/package.json`） | 活跃（`pushed_at 2026-09-17`，15601★） | ✅ 但是「数据网格」不是电子表格 | ✅ | ⚠ **Excel 导出属 Enterprise 专属**（仓库文档源码 `excel-export/index.mdoc` 的 `enterprise: true`） |
| 其他：Grist | <https://github.com/gristlabs/grist-core> | **Apache-2.0** | 活跃（`pushed_at 2026-09-16`，11815★） | ⚠️ 自托管应用，只能 iframe 整站 | ✅ | 有 |
| 其他：NocoDB | <https://github.com/nocodb/nocodb> | **非开源**："Sustainable Use License v1.0"（<https://github.com/nocodb/nocodb/blob/develop/LICENSE.md>） | 活跃（`pushed_at 2026-09-17`，64999★） | ⚠️ 非组件 | ✅ | 有 |
| 其他：Teable | <https://github.com/teableio/teable> | 核心应用 **AGPL-3.0**，`packages/*` **MIT**（<https://github.com/teableio/teable/blob/develop/LICENSE>），§7 品牌附加条款 | 活跃（`pushed_at 2026-09-17`，21801★） | ⚠️ 自托管应用 | ✅ | 有 |
| 飞书多维表格（SaaS，非库） | 见 §5.1 | 商业 SaaS；其扩展块 SDK `@lark-base-open/js-sdk@1.0.2` = ISC（<https://www.npmjs.com/package/@lark-base-open/js-sdk>） | — | ❌ 该 SDK 只能写「多维表格内部的扩展块」，**不能把表格嵌进自建网站** | 好 | 走开放平台 REST API |

**移动端结论（供门户排期用）**：Luckysheet / x-spreadsheet **无官方移动支持，不要用于学生手机门户**；Univer 官方标 experimental（须显式切移动 UI 插件、桌面/移动互斥）；jspreadsheet CE 手机端最省心但 **CE 没有 xlsx**；Handsontable 触控最强但**付费**。⇒ **门户手机端若要求稳，优先 jspreadsheet CE 或 Odoo 原生列表视图，而不是 Univer**。

### 6.4 ⚠ 封闭系统的 license 红线（必须写清）

1. **AGPL-3.0（OCA 全部相关仓库）= 高危**。AGPLv3 §13 把义务扩展到网络交互：以 AGPL 代码提供服务时须向使用者提供源码。本项目是**面向学生/教师的网络服务**，属典型场景 ⇒ **装一个都可能触发整站源码开放争议**。参考 <https://www.gnu.org/licenses/agpl-3.0.html>。
   **结论：生产环境不装 AGPL 模块** —— 含 `OCA/survey` 19.0（AGPL-3.0）与 `spreadsheet_oca`（AGPL-3.0）。
2. **商业授权（Handsontable）= 不能白用**。`LICENSE.txt` 明确区分 personal / evaluation 与 commercial；学校自建系统投入生产即属 commercial。另有「不得用于开发与其竞争的产品」条款。**除非付费，不要用。**
3. **LGPLv3（Odoo 社区版 / `o-spreadsheet`）= 安全但有条件**：作为**未修改的库**动态使用不传染（可保持闭源）；**一旦修改库本身**，修改部分需按 LGPL 发布。⇒ 直接使用 `o-spreadsheet` 并把改动留作补丁是可接受路径；fork 后大改再闭源不可接受。
4. **Apache-2.0 / MIT（Univer OSS / jspreadsheet CE / Luckysheet / x-spreadsheet / SheetJS CE / Grist / AG Grid Community）= 安全**，可闭源集成，保留版权与许可声明即可；**SheetJS CE 额外要求把署名文本放进「开源声明」页**（<https://docs.sheetjs.com/docs/miscellany/license>）。
   ⚠ 但注意：**Luckysheet 已归档、x-spreadsheet 已停更（继任者亦停）** —— 许可安全 ≠ 可长期维护。
5. **商业授权的隐藏陷阱**：**Handsontable 早在 7.0.0（2019-03-06）就退出了 MIT**（v6.2.2 仍是 MIT），现为 source-available；**`@univerjs-pro/*` 在 npm 上像普通包，但包内无 LICENSE 文件、package.json 无 license 字段**，靠 license key 插件执行 —— **不能当 Apache-2.0 用**。**"看得到源码" ≠ 免费用。**
6. **前端 JS 库用 AGPL/GPL 的边界（⚠ 工程判断，非法务意见）**：
   (a) **分发层**：前端库会被打包送给每个浏览器用户，这本身就是分发，GPL/AGPL 第 6 条的源码提供义务立刻生效；
   (b) **传染范围**：闭源宿主是否必须开源，取决于"库与你的应用是否构成**单一结合作品**"，与前后端位置无关。FSF 判据：聚合 vs 结合 <https://www.gnu.org/licenses/gpl-faq.html#MereAggregation>；AGPL 网络交互 <https://www.gnu.org/licenses/gpl-faq.html#AGPLv3InteractingRemotely>；AGPL 服务器角色 <https://www.gnu.org/licenses/gpl-faq.html#AGPLv3ServerAsUser>（FSF 原文："It doesn't matter if you call the program a 'client' or a 'server'"）。
   实操落点：**静态 import 进同一 bundle、同 DOM/同进程深度调用 = 高风险**（很可能被认定结合作品，需开源应用代码）；**iframe 独立页 + 仅 HTTP 通信 = 低风险**（典型聚合/独立程序）；独立后端进程 + API 也低风险（但该服务自身源码仍须按 AGPL 提供）。
   **本项目应一律以「不引入 AGPL/GPL 依赖」为红线**。⚠ 上述均**无判例支撑，需法务定论**（见 §8）。

---

## 7. 推荐方案

### 7.1 推荐：**A + C 组合，以 A 为主干；B 用 `Properties` + 评分项行表解决**

| 需求 | 用什么实现 | 依据 |
|---|---|---|
| **A 行=学生、列=评分项、格子里打分** | 主干：Odoo 原生 list view（`editable="bottom"` + `multi_edit="1"` + 按学生分组）；若校长坚持「一整张连续大表」，在**门户侧**嵌入 **Univer（Apache-2.0）** 作纯录入面，提交后走 ORM 落库 | §2.5.1、§6.3 |
| **B 评分项自由增删改** | `Properties` 字段（社区版内核，jsonb，界面在线加「列」）+ 评分项行表双写；模板整批复制 | §2.6 |
| **D 进出都是 Excel** | **白送**：`base_import`（`.xlsx`，Import records 菜单）+ `/web/export/xlsx`（Export All）。**只要新模型的列表视图不写 `create="false"`** | §2.5.1、§2.5.2、§2.7 |
| 权重 | 抄 Moodle：**权重靠分值表达**（0/2/4/6 即两倍影响）+ 支持负分；不引入单独 weight 字段 | §4.3 |
| 单格模型 | **分值 + 可选区间 + 可选评语**（抄 Canvas `criterion_use_range` + `free_form_criterion_comments`） | §4.3 |
| 汇总算法 | 抄 Canvas Outcomes 的 `calculation_method` 六枚举（`decaying_average / weighted_average / standard_decaying_average / n_mastery / highest / latest`）做成下拉 | §4.2 |
| 匿名评教 | **必须自研**（survey 无匿名概念；Moodle `anonymous` 可作参考） | §2.1.5、§4.1 |
| 模板结构 | 抄 Moodle/Canvas 三层：`模板 → 评分项(行) → 档位/分值(列)` + 实例关联表；`sortorder` / reusable | §4.3 |
| 指标批量导入交互 | 抄希沃「批量导入点评项目」，落地上直接用 `base_import` | §5.1 |
| 门户「只看不改」的成绩表 | 用 Odoo 原生只读 list / pivot（社区版即可，无 xlsx 下载给门户） | §2.5.1 |

### 7.2 为什么不直接选 C（纯第三方表格）当唯一方案

- **代价**：要自研前端表格与 Odoo 后端的双向同步（单元格 ↔ 记录/字段）、权限、并发与离线，还要处理移动端 —— 这是一整套「自研电子表格」的工程量，与铁律 0「能装不写、能抄不造」相悖。
- **而 D 是白送的**：一旦接受「导出空表 → 人填 → 导回」（宜搭子表单与 Canvas `gradebook_csv` 验证过的套路），A 的「Excel 感」能被满足很大一部分，成本却是 0。
- **C 的正确定位 = 只在验收时校长仍不满意「Excel 感」时启用的增强层**，且：
  - **① 直接复用 Odoo 自带的 `o-spreadsheet` 引擎**（**LGPLv3**、与 Odoo 同源、零适配层、自带 `exportXLSX`）——**缺的只是「编辑动作」那一层薄壳**，自研它等于把 `spreadsheet_oca` 在 LGPL 干净的边界内自己实现一遍。**在"已经要写模块"的前提下，这是性价比最高的一条**。
  - **② Univer OSS 界面 + SheetJS CE 读写的两件套**（均 Apache-2.0）：优点是维护最活跃、为嵌进产品而设计；代价是 ①Univer 仍 `1.0.0-rc.0` 未 GA；②**官方 xlsx 能力在付费的 `@univerjs-pro`**，必须自己用 SheetJS 接；③移动端官方标 experimental。
  - **③ 轻量备选 jspreadsheet CE（MIT）+ SheetJS CE**：手机端最省心、无构建链；代价是 xlsx/图表/进阶公式在 Pro。
  - **禁止 Handsontable**（非开源，$999/开发者起）、**不推荐 Luckysheet / x-spreadsheet**（已归档 / 已停更，且无移动支持）
  - **不使用 `spreadsheet_oca`**（AGPL-3.0 红线）——但**可以读它的源码理解「编辑动作」需要什么**，然后自己写（合规做法与 `/Users/qwe/odoo-enterprise-ref/README.md` 三条铁律一致）

### 7.3 明确不做

- ❌ 装 `survey` 当评估引擎（矩阵/量表不计分、无被评对象、题目不能批量导入 ⇒ §2.1）
- ❌ 指望**纯社区版** `spreadsheet` 编辑（只读 ⇒ §2.2.2）
- ❌ 用 `spreadsheet_oca` 补齐社区版电子表格（AGPL-3.0 ⇒ §3.3、§6.4）
- ❌ 买企业版用 `web_grid`（列是时间轴，方向性错误 ⇒ §2.3）
- ❌ 用 Studio 加字段（企业版独占 ⇒ §2.5.2）
- ❌ 装任何 AGPL 模块（OCA ⇒ §6.4）

---

## 8. 未验证 / 待确认清单

> 以下**均不得当结论使用**，需要下一个人补证。

1. **Univer 的包级许可拆分**：仓库根 `LICENSE` = Apache-2.0（已核实），但**「`packages/` 下是否每个包都 Apache-2.0、是否存在 pro / 商业包」未验证**（本次 GitHub 内容 API 对该目录返回空）。
2. **Univer / jspreadsheet-CE / Luckysheet 在 Odoo 门户手机端的实际表现**：**未实测**。
3. **SheetJS 迁站后的现行许可**：`git.sheetjs.com` 的 LICENSE 需登录（raw 返回 302 → login），**新版条款未验证**；npm `xlsx@0.18.5` 仍标 Apache-2.0，但该版本已多年未更新。
4. **OCA 许可政策页正文**：<https://odoo-community.org/page/legal> **未渲染**；AGPL-3.0 传染性结论来自 GNU 官方 AGPL 文本与推演，**不是** OCA 官方释义。
5. **`gnu.org` 部分页面 curl 返回 000**（瞬时网络问题），相关引用未取到页面正文；要引用 GNU 官方措辞请本地复核 <https://www.gnu.org/licenses/agpl-3.0.html>。
6. **Moodle Questionnaire 的「矩阵题 / 重复问题」**：官方题型表与 README 均无，**源码未核实到** ⇒ 未验证。
7. **Canvas SpeedGrader / Gradebook CSV 导入的官方指南正文**：页面 JS 渲染，仅验证 URL 存在（HTTP 200），**措辞未逐字验证**；相关行为结论已改由 API 文档与源码支撑。
8. **Moodle 全部文档正文取自 Wayback 2024 快照**（`docs.moodle.org` 直连与代理均 Cloudflare 403），非实时页面；引用官方 URL 时请注意时效。
9. **希沃魔方综合评价产品页** <https://www.seewo.com/product/common/ZHPJ>：curl 返回 HTTP 000，**未验证**。
10. **恒谦教育学生发展评价系统 / 物思学生综合素质评价**：仅得搜索摘要，**未取正文** ⇒ 未验证。
11. **问卷星 `helpid=367`（问卷维度设置）、`helpid=373`（多个权重值的设置）正文**：URL 与标题取自 helpid=368 页内导航，**正文未渲染** ⇒ 功能存在由 helpid=368 / 246 交叉证实。
12. **飞书公式函数大全页**（`…/687638790379`）与**企微智能表格 API 文档**（`…/path/99896`）：🟡 仅标题/导航可证。
13. **Odoo 企业版模块的可装配性**：本文对企业版 `web_grid` / `hr_appraisal` / `spreadsheet_edition` 的判断基于**本地企业版源码快照 + 官方文档 + manifest 的 license 字段**，**未在真实企业版实例上实测**。
14. **`OCA/hr` 的 `hr_appraisal_oca` 是否会迁移到 19.0**：**未验证**（19.0 无该目录，未见迁移 PR）。
15. **OCA 各模块在真实 Odoo 19 实例上的安装可运行性**：**未验证**（只读了目录树与 `__manifest__.py`，未跑 Odoo）。
16. **「导入不能新建字段」是强推断**：官方文档无正面断言，仅有「映射到已有字段」的表述（§2.5.2）。
17. **「把 Odoo 原生 spreadsheet 编辑动作嵌进自定义门户模板」**：**未验证**（官方文档未提；能确证的只有 `auth='public'` 的公开只读分享页）。
18. **本仓门户内嵌第三方表格库的前置条件**：`custom_addons/*` 的 asset bundle 与 CSP 策略是否允许加载外部 JS 库，**未查**。
19. **行列口径待校长确认**：Moodle grader report 是「列=成绩项、行=学生」，与队长定义的 A **恰好转置**。若校长接受「列=学生、行=评分项」，Odoo 原生列表视图的贴合度会显著提高 —— 此项**属需求侧未验证**（见 §2.5.4）。
20. **Odoo 官方文档的 editions 标记**：文档页内部**不带 Enterprise 徽章**（grep 原始 HTML 仅命中侧边栏导航链接），Enterprise 结论一律取自 <https://www.odoo.com/page/editions> 对照表 + odoo/odoo 源码存在性。
21. **Univer Pro 的价格与能力边界**：`pro.univer.ai` 定价页被「暂停新购」公告覆盖、`docs.univer.ai` 的 Pro 指南页 404 ⇒ **价格未验证**（只能确认 Pro = Univer Commercial License，评估版有水印 / 导入大小 / 协作配额限制）。
22. **SheetJS Pro 价格**：官网仅 "Inquire at" ⇒ **未验证**。
23. **Handsontable 官方「移动端支持」文档页**：相关路径 404 或被 CloudFront 拦 ⇒ **未验证**（移动支持证据来自 CHANGELOG 条目）。
24. **AG Grid 官网文档**抓取一律 CloudFront 403 ⇒ 「Excel 导出属 Enterprise」取自仓库内文档源码（`excel-export/index.mdoc` 的 `enterprise: true`），**未从官网正文直证**。
25. **钉钉多维表格官方 JS SDK** ⇒ **未验证**（本次只核实了飞书的 `@lark-base-open/js-sdk@1.0.2` / ISC）。另：`github.com/larksuite/base-open-sdk` **实测 404 不存在**，飞书 SDK 的唯一一手来源是 <https://www.npmjs.com/package/@lark-base-open/js-sdk>。
26. **前端 JS 库用 AGPL 是否导致宿主闭源必须开源**：**无判例，须法务定论**（工程判断见 §6.4 第 6 条）。
