# 交接提示词：给教务系统的「班务机器人」选一个 Telegram 机器人并接上

> 把下面整段（从这个标题到文件末尾）复制给另一个窗口的助手即可。
> 它要么只回答第二节的决策问题，要么在有服务器权限时一路做到第五节落地。

---

## 你的任务

一所学校（永约学坊）的教务系统上，我刚写好并**已经部署到生产**了一个「行政班务机器人」模块，
但**它现在还发不出任何消息**，因为缺一个 Telegram bot 的 token。
请你帮我定「用哪个机器人」，有条件的话直接把它接通并测通。

## 一、已经确定的事实（都是我实测的读数，不用再查）

**生产系统**：Odoo 19，服务器 `203.0.113.10`（ssh 别名 `prod-a` / `prod-host`），站点 `https://edu.example.org`，
容器 `edu19-prod-web-1` / `edu19-prod-db-1`，库名 `edu19`。

**已部署的模块**：`edu_tg_assist`（name「Edu TG Assist 行政班务机器人」），状态 installed，
后台已出现菜单「班务机器人」，11 个模型、2 条默认关闭的定时任务。
它的 webhook 路径是 `/telegram/assist/webhook`，密钥放在系统参数 `edu_tg_assist.webhook_secret`。
它需要的参数：`edu_tg_assist.token`、`edu_tg_assist.webhook_secret`、`edu_tg_assist.dry_run`（现在**一个都没配**）。

**生产上已有的两个机器人**（我用 `getMe` / `getWebhookInfo` 实测的）：

| 库里存的参数名 | 机器人名 | 用户名 | Telegram id | 能读全部群消息 | 当前 webhook | 它现在实际在干什么 |
|---|---|---|---|---|---|---|
| `edu_telegram.bot_token` | **诺亚** | `@qnj251079_bot` | 8450111115 | ✅ true（隐私模式已关） | `https://edu.example.org/telegram/webhook` | 学生**匿名意见箱** |
| `edu_tg_bind.token` | **SCRTS** | `@sctrs_bot` | 8647708957 | ❌ false（隐私模式没关） | `https://edu.example.org/telegram/tgb/webhook` | 学生私聊**领注册邀请码** |

两个 bot 的 `pending_update_count` 都是 0、`last_error` 都是 None —— 都在正常收消息，没坏。

**「诺亚」对不上的地方（需要你确认）**：
用户说「诺亚是负责接收维修的」，但生产上诺亚的 webhook 指向的是**学生匿名意见箱**：

- 代码原文：`controllers/main.py:37`「👋 你好！这里是教务系统意见箱。」；`main.py:40`「你的反馈是匿名的，我们只看内容、不记录你是谁。」
- 键盘按钮：💡功能建议 / 🐞问题反馈；模型 `edu.feedback` 的 `_description = 意见反馈`；库里已有 **10 条**反馈。
- **这套系统里没有任何维修/报修模块**：生产 `/opt/edu-app/custom_addons` 只有
  edu_apply edu_assess edu_brand edu_life edu_nav edu_portal edu_public edu_quiz edu_schedule
  edu_telegram edu_tg_assist edu_tg_bind edu_zh；仓库全文搜「维修」「报修」命中 **0**；
  用户自己的笔记（整个「文件大总管」目录、Downloads、桌面、凭据密钥库）搜「诺亚」也是 **0 条**。

## 二、要你解决的三件事

1. **「诺亚」到底该干什么？** 是用户记错了（诺亚 = 意见箱），还是当初接错线（诺亚本该接维修）？
   请给一个明确结论。如果它本该接维修 —— 那是一个**独立的、从零开始的新项目**，不要和班务机器人混在一起做。
2. **班务机器人用哪个 bot？** 见下面的三个选项，请选定一个并说明理由。
3. **接上并测通**（如果有服务器权限就做；没有就只回答 1 和 2，并把需要我做的事列清楚）。

## 三、硬约束（不能违反）

- **一个 Telegram 机器人只能挂一个 webhook URL。** 两个现成 bot 的 URL 都已被占 ⇒
  直接把现成 token 拿来给班务机器人用，会让原模块**收不到消息**（等于拆东墙补西墙）。
  要复用就必须先写一个「一个网址、分发给两个模块」的前门控制器。
- **绝对不要把班务机器人接到「诺亚」上。** 那会把「行政群消息流」和「学生匿名私聊流」混进同一个 bot，
  当场作废学校对学生「不记录你是谁」的承诺，而且**不可逆**。
- **token / webhook_secret 绝不能写进日志、聊天记录、git 或任何文档。**
  查参数时只查长度：`select key, length(value) from ir_config_parameter where key like 'edu_tg%';`
- 班务机器人**绝不读写** `edu.feedback.*` 表、`edu_telegram_outbox` 表、`edu_telegram.*` 参数；
  **绝不占用** `/telegram/webhook`（意见箱）和 `/telegram/tgb/webhook`（领码）这两条路由。

## 四、三个选项

- **甲（推荐）：新建第三个机器人，专给班务用。**
  在 Telegram 里找 `@BotFather` → `/newbot` → 起名 → 复制它回的那串 token。
  **0 行代码、0 耦合、边界全保**，唯一能让「行政广播」与「学生匿名」彻底不碰面的做法。
- **乙：复用 SCRTS**（用户说它「是公用的」）。
  可行，但要 (a) 写一个前门把 `/telegram/tgb/webhook` 的 update 分发给 `edu_tg_bind` 和 `edu_tg_assist`；
  (b) 去 `@BotFather` 用 `/setprivacy` 把 SCRTS 的隐私模式**关掉**，否则群 @提醒 收不到群消息。
  代价：从此学生领码与行政广播共用一个机器人，两个模块被绑在一起。
- **丙：复用诺亚。❌ 不做**，理由见上面的硬约束。

## 五、选定之后怎么接（如果由你来落地）

1. 后台 → 设置 → 技术 → 系统参数，新增三条：
   - `edu_tg_assist.token` = （BotFather 给的那串）
   - `edu_tg_assist.webhook_secret` = （随机 32 位，自己生成）
   - `edu_tg_assist.dry_run` = `1`（**先干跑**，只落库不出网，验证阶段用）
2. 把网址告诉 Telegram（把 `<TOKEN>` 与 `<SECRET>` 换成真值）：
   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d "url=https://edu.example.org/telegram/assist/webhook" \
     -d "secret_token=<SECRET>" \
     -d 'allowed_updates=["message","callback_query"]'
   ```
   期望返回 `{"ok":true,"result":true,"description":"Webhook was set"}`。
3. 用 `getWebhookInfo` 核对：`url` 正确、`pending_update_count` 为 0、`last_error_message` 为空。
4. 反向自证（**必须做**）：`curl -i -X POST https://edu.example.org/telegram/assist/webhook` **不带密钥**
   应得 **403**（**不是 404** —— 403 才说明路由在了但拒绝了你，404 说明根本没接上）。
   同时确认 `/telegram/webhook` 仍是 403（说明没占意见箱的路由）。
5. 私聊机器人发 `/start` 应回欢迎语；发 `/whoami` 应回你的身份；发 `/help` 应回指令表。
6. 把 `dry_run` 改成 `0`，真发一条测试消息，去后台「发送记录」菜单看这一条是否 `ok=true`。
7. 把机器人拉进群「我爱学习群」「清洁能源站群」，在后台「群与短名」登记短名，
   再到「人员映射」登记谁是学委、谁是宿舍长（**名字要能对上，对不上它会拒绝发，不会乱猜**）。
8. 要用「群里 @某人 15 分钟没回就私聊提醒」，必须去 `@BotFather` 用 `/setprivacy` → **Disable**
   （关掉隐私模式），否则机器人**读不到群消息**，这个功能永远不触发。

## 六、出问题怎么查

- 后台菜单「**发送记录**」（模型 `edu.tg.assist.send_log`）：每一次发送的成功/失败与**错误原文**都在这里。
- 定时任务两条**默认是关的**：`edu_tg_assist: @提醒超时扫描`（5 分钟）、`edu_tg_assist: 规则自愈`（1 天）。
  要用得自己去「设置 → 技术 → 计划动作」打开。
- 给用户看的说明书：`docs/ops/tg-assist-bot-howto.md`（大白话一页）。
- 设计边界（B1–B6）与能力清单（F1–F7）：`docs/plans/tg-assist-bot-design.md`。

## 七、它配好之后会什么（验收标准）

- **私聊**：`/start` `/help` `/whoami` `/name 张三`（登记自己）
  `/dm 张三 明天记得交表`（替管理员私发，只限管理员）
  `/tpl`（套现成文案，只读、不发群）
- **群里**：`/notify 学习群 各位同事请注意…`（广播，只限管理员）
- **后台菜单**：群与短名 / 人员映射 / 文案模板 / 私发记录 / @提醒待办 / 按钮回填 / 发送记录
- 名字打不全时**绝不自己挑一个发出去**，会回「找到多个：张三/张三丰，请写全名」；
  非管理员来发会回「你没有这个权限」**并留痕**。

## 八、我需要你回给我的东西

1. 「诺亚」的结论（记错了 / 接错线了）。
2. 选甲还是乙（还是你有更好的方案）。
3. 如果是甲：那串 token（**别发群里、别写进文档**）。
4. 如果是乙：确认可以由你改 `edu_tg_bind` 的 webhook 控制器 + 去关 SCRTS 的隐私模式。
