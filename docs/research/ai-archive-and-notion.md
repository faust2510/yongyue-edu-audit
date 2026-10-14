# AI 材料分类归档 + 外部知识库（Notion）落库调研

> **铁律 0 产物**（CLAUDE.md 铁律 0 / docs/dev-workflow.md 六步闸门第 2 步）。
> 任务：F7「转发材料给机器人 → AI 提取关键信息 + 评估紧急程度 → 分类保存到 Notion 项目库并打标签」——本文件只做调研，实现见 `docs/plans/tg-assist-bot-design.md` §9.11。
> **取证时间**：2026-10-10（本机 docker 栈 + 上游源码分支/URL 直取）。
> **取证方式的限制（必须先读）**：本机 `web_search` 不可用（返回 `HTTP 400 BAD_REQUEST — You have insufficient credits`），
> 因此本轮**只能按已知 URL 直取一手页面**，无法做检索式全网扫；凡是没取到正文的一律标「未验证」，不得当结论用。

**一句话结论**：Odoo 19 **官方有与 F7 高度重合的三件套**（Ask AI / AI 字段 / **AI 文档分类归档**），但**在本仓的部署形态里一件也装不上**
—— `addons/ai` 在社区版 `odoo/odoo` 19.0 里**不存在**（raw 404），AI 字段要 **Studio**、文档分类要 **Documents** 应用，都是企业版/订阅能力；
OCA 19.0 分支只有一个 `ai_tool`（AGPL-3，2026 年新建的「AI 工具注册表」雏形），**没有**任何「消息 → 抽取 → 分类 → 落库 → 外部同步」的流水线；
Notion 官方 API 能承载「建页 + 写属性」，但**属性键必须匹配目标 data source 的 schema**、且 integration 必须**先被 share 进那个库**，
⇒ **结论：自研有据**（不是懒得找，是三条路都有明确排除理由），且给了 5 条硬约束（§6）。

---

## 1. 取证环境与方法（可复现）

| 项 | 值 / 命令 | 备注 |
|---|---|---|
| 本机 Odoo 19 社区版 | `docker exec edu19-clone-web-1 sh -c 'ls /usr/lib/python3/dist-packages/odoo/addons/ \| wc -l'` → **685** | 只有社区版模块 |
| 本机有没有 AI 模块 | 同上目录 `grep -i -E "^(ai\|llm\|mail_ai\|iap)"` → 只命中 `iap` `iap_crm` `iap_mail`（Odoo 自家计费服务网关） | **没有 `ai` 模块** |
| 上游社区版源码 | `https://raw.githubusercontent.com/odoo/odoo/19.0/addons/ai/__manifest__.py` → **`404: Not Found`** | 同批探测 `addons/ai_app`、`addons/mail_ai` 也是 404 |
| 上游文档**源码直取**技巧 | Sphinx 站可直取未渲染 rst：`https://www.odoo.com/documentation/19.0/_sources/applications/productivity/ai.rst.txt` | 绕开「导航栏吃满 100 KB 截断」；技巧来源 `docs/research/leave-approval.md:23` |
| OCA 仓库清单 | `https://api.github.com/repos/OCA/ai/contents/`（默认分支 19.0） | 目录级清单可直接取 |
| Notion 文档直取技巧 | `developers.notion.com` 是 Mintlify 站，**URL 末尾加 `.md` 得正文**：`https://developers.notion.com/reference/post-page.md` | 直接 GET 页面拿到的是 JS 壳，无正文 |

---

## 2. Odoo 19 官方给的是什么（能不能装）

| 官方能力 | 一手原文（节选） | 来源 | 本仓能不能用 |
|---|---|---|---|
| **Ask AI**（`Ctrl`+`k` 自然语言助手，能开视图、可 Send as Message / Log as Note / Open in Discuss） | 「The `Ask AI` feature allows users to receive assistance anywhere in an Odoo database. It understands natural language and can answer questions, open views, and improve content.」 | https://www.odoo.com/documentation/19.0/_sources/applications/productivity/ai.rst.txt | ❌ 没有 `ai` 模块（企业版/订阅） |
| **AI 字段** | 「AI fields can be added to a record through the **Studio** app or property field.」＋「Installing Studio may impact the current pricing plan」 | https://www.odoo.com/documentation/19.0/_sources/applications/productivity/ai/fields.rst.txt | ❌ 需 Studio（企业版订阅） |
| **AI 文档分类归档**（**与 F7 目标最接近**） | 「Odoo AI Document Automation enables automated **classification, routing, and processing** of documents using artificial intelligence … automatically sorting them into folders, **extracting key information**, and triggering business actions.」＋配置前提「The **Documents** application is installed」 | https://www.odoo.com/documentation/19.0/_sources/applications/productivity/ai/document_sort.rst.txt | ❌ 需 Documents 应用（企业版） |
| **AI 提供方与密钥** | 「Odoo supports both **Gemini and OpenAI (ChatGPT)** as providers in the AI application.」＋「**API keys are required** for Odoo.sh or On-premise databases to use AI features.」 | https://www.odoo.com/documentation/19.0/_sources/applications/productivity/ai/apikeys.rst.txt | ⚠ 只列两家提供方；我们的自研层按 **OpenAI 兼容**协议做，能接 Gemini 兼容网关与国内模型 |
| AI 应用还有子能力页 | 目录：`ai/apikeys` `ai/agents` `ai/default_prompts` `ai/document_sort` `ai/fields` `ai/live-chat` `ai/server-actions` `ai/email-templates` `ai/voice` `ai/improve_text` `ai/support_operations` | 同 ai.rst.txt 的 `toctree` | — |

**判读**：官方把 F7 想要的「抽取 + 分类 + 触发动作」做成了企业版的 Documents 自动化；我们跑的是**社区版 685 模块**的自建部署，
既没有 Documents/Studio，也没有 Odoo 订阅密钥 ⇒ **装不上**。若学校日后买企业版，F7 的「抽取」这一层可以换成官方的 AI 字段/文档分类，
而「转发 Telegram 材料」「本地归档表」「Notion 落库」这三件官方不提供的部分仍需自研（官方分类落到 Documents 文件夹，不是 Notion）。

---

## 3. OCA 有没有现成模块

- 仓库：**`OCA/ai`**，19.0 分支目录清单里**只有一个模块** `ai_tool`（`https://api.github.com/repos/OCA/ai/contents/`，ref=19.0）。
- `ai_tool/__manifest__.py` 原文要点（raw 直取）：`"name": "Ai Tool"`、`"version": "19.0.1.0.0"`、`"license": "AGPL-3"`、
  `"author": "Dixmit,Odoo Community Association (OCA)"`、`"depends": ["mail"]`、
  `"summary": "We want to generate some specific AI Tools that might be used in other places, like MCP or native."`、
  `data = security/ir.model.access.csv + views/menu.xml + views/ai_tool.xml + data/ai_tools.xml`。
- **判读**：它是「AI 工具（可被 MCP / 原生调用的函数）注册表」的雏形，**不含**消息入口、不含抽取 schema、不含分类落库、不含外部同步；
  它的目录形状（**工具定义放 `data/*.xml`**）与本仓 `edu.tg.assist.bot` 已有的「指令注册表自动发现」是同一思路，我们的实现已更贴合本场景。
- **不装**；AGPL-3 亦与本仓多数模块的 license 口径不同（要在同一进程内链接需谨慎）。

---

## 4. Notion 官方 API 的硬规矩（要写就得照它的来）

| 规矩 | 一手原文 | 来源 |
|---|---|---|
| 认证 = Bearer + **必须**带版本头 | 「Requests use the HTTP `Authorization` header … The Notion API accepts **bearer tokens** in this header.」索引示例里带 `-H "Notion-Version: 2026-03-11"`（即当前示例版本） | https://developers.notion.com/reference/authentication.md |
| 建页的 parent 只能给 page_id 或 **data_source**（内部集成不能建 workspace 级页） | 「In most cases, provide a `page_id` or `data_source` under the `parent` parameter …」＋「For internal connections, a page or data source parent is **currently required** in the API」 | https://developers.notion.com/reference/post-page.md |
| **属性键必须匹配目标库的 schema**（否则写不进去） | 「For a page in a data source, **property names or IDs must match the parent data source’s schema**.」 | 同上 |
| 只读属性不能写 | 「Formula, rollup, ID, creation, and last-edit values are set by Notion. … **Omit these fields** from `properties`」 | 同上 |
| 属性值形状 | 日期 `{"date": {"start": …}}`；`title/rich_text/people/relation/multi_select/files` 用**数组**；`select/date/number` 等清空用 `null`；数组是**整体替换**不是追加 | https://developers.notion.com/reference/page-property-values.md |
| 能力门槛 | 「Your connection must have **Insert Content capabilities** on the target parent page or database」 | https://developers.notion.com/reference/post-page.md |

**判读（这条决定了实现方式）**：Notion 的写入**强依赖用户库的 schema**，而我们的老师用的是随手建的库。
⇒ 不能写死属性名；必须**运行时读库、按名字谈匹配**，并且**保底路径必须只依赖 `title` + 页面正文（blocks）** —— 这两样任何库都有，
所以「AI 摘要 + 关键信息」即使一个属性都对不上也能落进 Notion。

---

## 5. 国内 IM / 同类产品（本轮只拿到索引级证据）

- 钉钉帮助中心是**静态 markdown 站**（任意文档 URL 加 `.md` 得正文；索引 `https://help.dingtalk.io/llms.txt`，其中含 `AI Table` 系列约 144 页/语种条目）。
  ⇒ 只能证明「钉钉把 AI 能力（AI 表格）做成了产品并写进帮助中心」，**未取到正文，不构成 F7 可复用/不可复用的结论（未验证）**。
- 飞书 / 企微 / 校管家：本轮**未取得一手页**（`web_search` 不可用）⇒ **未验证**。
- 可复用的既有调研：`docs/research/onestop-learning-and-repetitive-work.md`（2026-09-12）对国内 SaaS 做过「功能名级」证据与两个共性缺口分析，需要竞品结论时以它为准。

---

## 6. 结论与选型（F7 的 5 条硬约束）

1. **LLM 走 OpenAI 兼容协议**（`POST {base_url}/v1/chat/completions`），`base_url / model / api_key` 全部走系统参数；
   **未配置 = 零出网**，退化为「规则抽取」（正则日期/金额/急词），并在记录上标 `ai_state=rule`，**绝不假装是 AI 的结论**。
2. **先落库、再出网、异步分析**：转发消息立刻建本地归档记录并立刻回执；LLM 分类放进 cron（本仓铁律：先落库再出网；也避免 webhook 超时被 Telegram 重投）。
3. **Notion 默认关**（fail-closed）：未配 token/库 id 时一条都不发；开启后导出**保底只写 `title` + 正文块**，属性映射按运行时 schema 谈，谈不上的降级而不是报错；
   用户必须自己把 integration **share 进目标库**（Notion 侧动作，程序无法代办）。
4. **出网前脱敏**：手机号 / 身份证号 / 银行卡号 / 本仓邀请码（`STU-*`）在送给 LLM 与 Notion 之前替换为占位符；
   归档原文仍**只存在本库**，Notion 默认只收 AI 摘要与关键信息（附原文需显式开参数）。
5. **一切失败可见**：LLM/Notion 的错误原文落记录（后台可看），不进日志、不静默、不影响 Telegram 回执。

---

## 7. 未验证 / 待确认清单

1. **未验证**：本机 `web_search` 不可用（HTTP 400 insufficient credits）⇒ 本轮没有做检索式调研，全部结论限于「上述 URL 直取到的内容」。
2. **未验证**：`odoo/odoo` 19.0 是否另有 `ai` 模块（我探测的是 `addons/ai/__manifest__.py` = 404；同批 `ai_app`/`mail_ai` = 404，但 `addons/ai_fields` 探测时**网络超时**，未取到结论）。
3. **未验证**：官方 AI 能力是否需要 Odoo 订阅（文档只写「API keys are required for Odoo.sh or On-premise databases」，未写定价/授权细节）。
4. **未验证**：Notion API 的 `database_id` parent 是否仍被当前版本接受（文档正文以 `data_source` 为主，JSON schema 段里同时列了 `database_id`）⇒ 实现里做成可配 `parent 类型`，并在自检里体检。
5. **未验证**：`Notion-Version` 具体取值（认证页示例为 `2026-03-11`，post-page 与 property-values 页未见固定值）⇒ 实现里做成**可配参数**、默认取示例值。
6. **未验证**：飞书/企微/校管家的「AI 归档」是否有现成能力（无一手页）。
7. **未验证**：国内模型（DeepSeek/Qwen/智谱）的 OpenAI 兼容端点细节未逐家取证 ⇒ 实现只依赖最常见的 `chat/completions` 形状，并把 base_url 完全交给参数。
