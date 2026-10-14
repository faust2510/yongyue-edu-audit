# 行政与班务辅助机器人（edu_tg_assist）设计

> **状态**：`在研` ｜ **主题**：`行政班务机器人` ｜ **取代**：`—` ｜ **核对**：`2026-10-12`

## 1. 为什么新建一个模块，而不是「完善」现有的

校长给的《机器人开发.docx》要的是一个**行政与班务辅助机器人**（定时提醒 / @提醒 / 广播 / 一对一私发）。
本仓已有三个 Telegram 相关的东西，**没有一个能直接拿来改**：

| 东西 | 是什么 | 为什么不能用 |
|---|---|---|
| **生产** edu_telegram（**不在本仓**） | **匿名意见箱**（学生私聊吐槽 → 教务看汇总） | ⛔ **红线**：它的匿名性建立在「不保存明文 chat_id、只存 HMAC 指纹」上。任何把两个模块的 chat_id **并表 / join / 并排导出**的动作，都会作废学校对学生的匿名承诺，**且无法撤回** |
| 本仓 edu_tg_bind | 学生私聊领注册邀请码（**生产在跑** ✓） | 职责单一（只发码），且**只处理私聊**；给它加群聊/广播会污染它的安全边界 |
| 本仓 edu_telegram v2.2 | 四角色教务前端 | **2026-09-17 校长裁定退役**；且它占用了 /telegram/webhook、edu_telegram.* 参数、edu.telegram.outbox 表名 —— 与生产那个**同名不同物**，硬上会撞 |

⇒ **结论：新建 edu_tg_assist，与上面三者零共享。**

> ⚠ **2026-10-08 裁定变更（用户拍板，见 §9）**：班务机器人**复用 @sctrs_bot**（就是 edu_tg_bind 那个）。
> 上表「edu_tg_bind 不能用」这条**已被推翻**：不是给 bind 加群聊能力，而是在它**前面**加一个纯分发层
> **edu_tg_gate**（新模块，新路由 /telegram/sctrs/webhook）；bind 的代码与语义基本不动（只把私聊领码流程
> 抽成模型方法，供两条路由共用），旧路由保留作一键回滚。**B1–B6 全部不变**，新增 B7/B8。

## 2. 硬边界（违反即事故）

| # | 边界 | 理由 |
|---|---|---|
| B1 | **绝不**读写 edu.feedback.* | 匿名红线，见 §1 |
| B2 | **绝不**读写 edu_telegram_outbox / edu_telegram.* 系统参数 | 那是生产匿名意见箱的投递链路 |
| B3 | **绝不**占用 /telegram/webhook 路由 | 生产匿名意见箱在用；本模块用 /telegram/assist/webhook |
| B4 | **绝不**依赖 edu_telegram（两个版本都不依赖） | 依赖会在装载期撞 comodel 断言 |
| B5 | 本模块的 chat_id 与 edu.feedback.* 的指纹**永不 join、永不并排导出** | 同上 |
| B6 | token **绝不写进日志** | 沿用 edu_tg_bind 的纪律 |

## 3. 能力清单（来自《机器人开发.docx》）

| # | 文档要的 | 本设计怎么落 | 优先级 |
|---|---|---|---|
| F1 | **定时提醒**：周一学习日发链接@学委；周末卫生日发提醒+检测表 | ir.cron + edu.tg.assist.reminder 规则表 | **P0** |
| F2 | **一对一私发**：/dm 张经理 请确认… | edu.tg.assist.person 人员映射 + /dm 指令（**2026-10-10 加 /stop 停发与登记引导**，见 §9.10） | **P0** |
| F3 | **广播**：/notify 行政 各位请注意… | 群别名登记 + /notify 指令 | **P0** |
| F4 | **内联按钮回填**：宿舍长点「已完成并达标 / 有异常需上报」 | callback_query 处理 + 回填记录（**2026-10-10 接通 F1**：定时提醒勾「带打卡按钮」→「打卡统计」看谁没回，见 §9.9） | P1 |
| F5 | **@提醒**：群里 @我 15 分钟没回 → 私聊提醒 | 群消息监听 + 待办表 + cron 扫描 | P1 |
| F6 | **模板库**：节日/生日/会议 | edu.tg.assist.template | P2 |
| F7 | **AI 分类归档 → Notion** | ✅ **2026-10-10 用户拍板「做」** ⇒ 材料智能归档（本地表 + 规则/LLM 抽取 + 可选 Notion 导出），见 §9.11 | P2 |

## 4. 出网方式：照抄 edu_tg_bind（已验证），不用退役版那套

- ✅ **本设计采用**（edu_tg_bind 法）：容器**直连** api.telegram.org，用 requests 同步发。
  实测依据：容器内 getMe 拿到 Telegram 真实 401 应答（DNS 203.0.113.9）⇒ 不需要宿主中继。
- ❌ 不采用（退役版 v2.2 法）：把回复写进 HTTP 响应体让 Telegram 代发。它能免出网，但
  **只适用于「被动回复」**；本模块要**主动推送**（定时提醒、超时私聊），必须能主动出网。

## 5. 数据模型（草案）

| 模型 | 作用 | 关键字段 |
|---|---|---|
| edu.tg.assist.chat | 群/私聊登记 | chat_id（唯一）、chat_type、title、alias（给 /notify 用的短名） |
| edu.tg.assist.person | 人员-ID 映射 | tg_user_id（唯一）、name、role、chat_id |
| edu.tg.assist.reminder | 定时规则 | name、cron 关联、target_chat_id、template_id、active |
| edu.tg.assist.template | 文案模板 | name、body（含 {name}/{date} 占位符）、scene |
| edu.tg.assist.mention | @提醒待办 | chat_id、message_id、mentioned_at、replied_at、dm_sent_at |
| edu.tg.assist.send_log | 发送记录（**不叫 outbox**，避嫌） | chat_id、text、ok、error、sent_at、kind |
| edu.tg.assist.reply | 按钮回填（@提醒待办的 `ck:` 前缀） | mention_id、tg_user_id、choice、replied_at |
| edu.tg.assist.poll | 打卡（一次带按钮的群发，§9.9） | chat_id、reminder_id、options、expected_role、state、message_id、sent_at + 统计四件套 |
| edu.tg.assist.poll.reply | 打卡回填：谁点了哪个选项（`p:` 前缀） | poll_id、tg_user_id（`unique(poll_id, tg_user_id)`）、choice、replied_at |

## 6. 隐私口径（与匿名意见箱的区别，必须写清）

- 本模块**是管理工具**，**必须**存 chat_id 与真实姓名（否则没法一对一私发）—— 这是**明示**的，
  与匿名意见箱的承诺**不冲突**，因为两者**不同表、不同参数、不同路由、不 join**（§2 的 B1–B5）。
- 人员映射表**只收**「主动向机器人发过 /start 并自报姓名」的人（Telegram 平台限制：机器人不能
  主动向从未说过话的用户发私聊）。
- **不做**「扫群成员自动建人」：那会把没同意的人拉进来。

## 7. 待校长拍的两件

1. ~~**F7（AI + Notion）要不要做**~~ —— **2026-10-10 用户拍板「做」**，已按「LLM 未配=零出网 / Notion 默认关 / 出网前脱敏 / 原文只存本库」实现，见 §9.11。
2. **admin_key 要换掉** —— 生产上 edu_telegram.admin_key 只有 10 字符且是可猜的 ADMIN-2026
   （那是**匿名意见箱**的参数，不是本模块的；但既然查到了就该换）。**这条与本模块无关，独立成立。**

## 8. 实施顺序

1. **骨架**（Lead）：模块目录 + manifest + 出网客户端 + webhook 路由 + 安全模型 + 最小视图
2. **F1 定时提醒**（可并行）：规则表 + cron + 发送
3. **F2/F3 私发与广播**（可并行）：人员映射 + 群别名 + 两条指令
4. **F4/F5 按钮回填与 @提醒**（可并行）：callback_query + 待办扫描
5. **F6 模板库**（最后）
6. 全量门禁 + 部署 + 生产验证

## 9. 2026-10-08 裁定变更：复用 @sctrs_bot + 新增前门模块 edu_tg_gate

### 9.1 新裁定

- 用户原话：**「我就要乙，他被造的目的本来就是这样的。」** ⇒ 班务机器人挂在 **@sctrs_bot**（edu_tg_bind 那个 bot）。
- §1 的原裁定「给 edu_tg_bind 加群聊/广播会污染它的安全边界」**被本次裁定取代**。落地方式改为：
  **不扩展 bind**，而是新建 **edu_tg_gate**（前门分发层）；bind 只做最小化改动（把私聊领码流程抽成
  `edu.tg.claim.handle_private_message(message)`，让自带路由与前门**共用同一段实现**，防止两份拷贝漂移）。

### 9.2 为什么必须有前门（一个机器人只能挂一个 webhook）

2026-10-08 在服务器上实测：

- @sctrs_bot 的 webhook 只能是 `https://edu.example.org/telegram/tgb/webhook`（原来那条）；
- 想退回轮询绕开前门 → `getUpdates` 直接 **409 Conflict: can't use getUpdates method while webhook is active**；
- 于是不写前门，update 只会进 edu_tg_bind，assist **永远收不到消息**。

### 9.3 分发判据（`custom_addons/edu_tg_gate/routing.py`，纯函数 + 单测 37 条）

| 来的是什么 | 去哪 | 为什么 |
|---|---|---|
| `callback_query` | assist | bind 只用 url / copy_text 按钮，从不产生 callback_query |
| 群 / 超级群消息 | assist | bind 明确只处理私聊（对群消息回 `not_private`） |
| 私聊，chat_id / tg_user_id 属于**已标为教职工**的人（edu.tg.assist.person.role ∈ admin/teacher/dorm_head 且 active） | assist | ⚠ 只认**后台显式标注**的角色，**不**按「登记过」判：学生若误发 /name 也会被登记成 role=other，若按「登记过」改道，他以后发 /start 就再也拿不到码（这正是要避免的） |
| 私聊，首词 ∈ `/assist /dm /name /notify /tpl /whoami` | assist | 教职工白名单指令 |
| **其余一切（含 `/start`、`/help`、自由文本）** | **bind** | **fail-safe：学生流逐字不变** |
| assist 未装载 | 私聊一律 bind、群消息 ignore | 前门不许把消息变没，也不许把群消息丢给 bind |

- 新路由 **/telegram/sctrs/webhook**（参数 `edu_tg_gate.webhook_secret`，fail-closed 403）。
- **三条路由并存**，一条都没被占：/telegram/webhook（意见箱）、/telegram/tgb/webhook（bind，保留作回滚）、
  /telegram/assist/webhook（assist，保留）、/telegram/sctrs/webhook（前门，Telegram 现在打这条）。
- 副作用（明示）：学生与老师共用一个 bot ⇒ **老师第一次要用班务助手请发 `/assist`**（`/assist` 与 assist 里的
  `/start` 同义，HELP 已写明）；老师若发 `/start` 会走进领码流（因为 `/start` 刻意留给学生）。

### 9.4 新增边界（在 B1–B6 之外）

| # | 边界 | 理由 |
|---|---|---|
| B7 | edu_tg_gate **只做分发**：无模型、无表、无 ACL、无 data；不写任何数据 | 前门是最小可信层，出问题必须能一眼看完 |
| B8 | 前门路由与两条旧路由**三条并存**且各自 fail-closed；bind 旧路由保留 | 出问题把 Telegram 指回旧路由即可一键回滚 |

### 9.5 代价（已明示并接受）

1. 多一个模块、多一条路由、多一个密钥，多一个故障点；
2. 学生与行政**共用同一个 token**：token 泄漏的爆炸半径 = 学生领码流 + 行政群发流；
3. 必须关 @sctrs_bot 的**隐私模式**（F5 @提醒 要读群消息），不可逆地扩大它的数据面；
   `allowed_updates` 还要从 `["message"]` 加上 `callback_query`（F4 按钮回填要用）；
4. assist 要存真实姓名 + chat_id（§6），会与 bind 的学生 chat_id 落在**同一个 bot 名下** ——
   但仍然**不 join、不并排导出**（B5 不变）。

### 9.6 生产接线记录（2026-10-08，已上线）

**代码**：前门模块与 bind 最小化改动已提交 `855979c`（feat(tg-gate)，15 文件 +537/-70）；
生产首装用 `ACTION=-i bash scripts/deploy_myedu.sh edu_tg_gate`（DEPLOY_RC=0，升级→重启配对自证
StartedAt 15:17:36Z > 升级完成 15:17:15Z），活体注册表门禁 14 模块 / 102 模型 LIVE / 0 DARK。

**系统参数**（值一律不落日志不落文档，只记长度）：

| 参数 | 处置 |
|---|---|
| `edu_tg_gate.webhook_secret` | 生产容器内 `secrets.token_hex(16)` 生成（len=32），未进宿主进程表 |
| `edu_tg_assist.token` | 库内复制 `edu_tg_bind.token`（len=46，**同一串**；@sctrs_bot 仍只此一个 bot） |
| `edu_tg_assist.dry_run` | 置 `0`（真发）；回调试改 `1` |
| `edu_tg_bind.*` | **一字未动**（含生产既有的 `dry_run=0` 与旧路由密钥） |

写参数后**必须** `docker compose restart web`：新参数对活着的进程不可见，未重启前带正确密钥也一律 403（本地与生产各踩过一次）。

**Telegram 侧**：`setWebhook(url=https://edu.example.org/telegram/sctrs/webhook, secret_token=<前门密钥>,
allowed_updates=["message","callback_query"])` → `ok=true` / `result=true` / `"Webhook was set"`；
`getWebhookInfo` → url 正确、`pending_update_count=0`、`last_error=None`、allowed 含 callback_query。

**接线后实测**：

| 探针 | 结果 |
|---|---|
| 前门不带密钥 / 错密钥 | 403（fail-closed） |
| 前门正确密钥 + 空 update / 频道消息 | 200 `{"ok":true,"ignored":"gate_ignore"}` |
| 前门正确密钥（公网 https://edu.example.org/…） | 200 |
| bind 旧路由正确密钥 + 群消息 | 200 `{"ok":true,"ignored":"not_private"}` ⇒ 抽出的 `handle_private_message` 在活体生效且不耗码 |
| bind 旧路由错密钥 / assist 自带路由 / `/telegram/webhook` | 403 / 200 `no_message` / 403 ⇒ 三条路由各自上锁、意见箱未被占 |
| 判据自证（shell 直调 `edu.tg.gate.router.route()`，无副作用） | 学生 `/start`、`/help`、自由文本 → bind；老师 `/assist`、`/name@Scrts_bot` → assist；群消息、callback_query → assist；频道、edited_message → ignore；ASSIST_READY=True、STAFF_COUNT=0 |

**真发管线自证（2026-10-08，合成探针，探针行已清理）**：

- 合成私聊 `/assist` 打**生产前门** → assist 真出网 → Telegram 回 `HTTP 400: Bad Request: chat not found`
  ⇒ **token 有效、出网通、发送管线活**（收件人是我编的假 chat，故 400）；`edu.tg.assist.send_log` 逐字记下错误原文；
- 合成超级群消息经前门 → assist 群消息落库；合成 `callback_query` → assist 正常受理且无副作用；
- **学生 `/start` 未做合成探针**：前门该走 bind，而 bind 的语义是「任何私聊 = 出一张码」；
  当时 `_pool_has_candidates()=True`（码池非空），合成探针会**真消耗一个学生的邀请码**，故不做；
  该判据（`/start → bind`）由路由纯函数与本地端到端测试覆盖（本地实测 `created=false`、不耗码）。

**回滚**：`setWebhook` 指回 `https://edu.example.org/telegram/tgb/webhook`（bind 自带路由 + 未动过的旧密钥，实测 200）
⇒ 学生领码立即回到改动前状态，无需改代码、无需重部署。

**到 2026-10-08 收尾时尚未完成的（都不在代码侧）**：

1. **关隐私模式**：BotFather `/setprivacy` → @sctrs_bot → Disable。这是 F5 @提醒 的前提（实测
   `can_read_all_group_messages=false`），且「@校长」这类消息在开着隐私模式时根本不会投递给机器人。
2. **真人真收验证**：管线已由上面的合成探针证明活着，但「真人收到回复」还需一位真人私聊发 `/assist`
   （生产 `edu.tg.assist.person` 为空，STAFF_COUNT=0）；bind 的 33 个学生 chat_id 是红线，**不读取不展示**，故没有可用的测试收件人。
3. **登记业务数据**：拉 @sctrs_bot 进「我爱学习群」「清洁能源站群」→ 后台「群与短名」起短名，
   后台「人员映射」把学委/宿舍长/教师标好角色（角色是前门判据之一，见 §9.3）。
4. **F5 三参数 + cron**：`edu_tg_assist.owner_user_id`（不配 = 不建待办）、可选 `owner_username` /
   `mention_timeout_minutes`（默认 15），并打开定时任务「edu_tg_assist: @提醒超时扫描」（id 46，默认 false）。

### 9.7 生产端到端验证（2026-10-09，探针已全部清理）

**方法**：在 web 容器内用 urllib 打**生产前门的真实网址** `http://127.0.0.1:8069/telegram/sctrs/webhook`（带真密钥头），
update 里的 chat id 全是编造的（私聊 777000001 / 777000002 / 777000009，群 -1005550000001 / -1006660000002）⇒
assist 每一次真出网都只可能拿到 `HTTP 400: Bad Request: chat not found`，**不会有任何真人收到消息**；所有探针行随后删除。

| 验证面 | 结果 |
|---|---|
| 学生路（gate → bind → 出码） | 合成私聊 `/start` → 200 `{"ok":true,"created":true,"sent":false,…}`，回复含邀请码 + 两个内联按钮（去注册 / copy_text）；同一 chat 再发一次 → `created=false`「你已经领过邀请码了，这是你原来那张」 ⇒ **幂等分支也验过**；claim 落库、`notify_state=failed`、`notify_attempts=1`、`notify_error=HTTP 400…`（只因收件人不存在） |
| 学生流仍走 bind（未白名单的私聊） | `/help` 与自由文本 → 走出码（学生体验一字未变）⇒ **这正是不把判据写成「登记过就走 assist」的理由** |
| 老师路 | `/whoami` 回「姓名 PROBEBOSS / 角色 行政」；`/assist` → 登记；**自由文本 → assist 回「我不认识这条指令。」**（§9.3 的 role 判据在生产活体生效） |
| `/dm` 命中 | 收件人已登记 → `edu.tg.assist.dm` 一行 `state=failed`、`target_chat_id` 正确、`raw` 留痕，回复「发给 TargetWang 失败：HTTP 400…」（失败原因如实回执） |
| `/dm` 找不到人 | `state=not_found`，回复「没找到「NobodyX」。（一对一私发只能发给跟机器人说过话的人：请让对方私聊…/start，再回 /name 真名。）」 |
| 越权 | 非 admin 发 `/dm` 与群 `/notify` → 回「你没有这个权限。」并在 `edu.tg.assist.dm` 留痕（`sender_role=other`、`state=denied`） |
| `/notify` 短名 | 短名存在 → 真发（`send_log.kind=notify`）并回执「广播失败：…」；短名不存在 → 「没有这个群：NOSUCH（现有：PROBEGRP）」**绝不模糊匹配** |
| F1 定时提醒（整条链） | 建规则 → 自动生成 `ir.cron`：`interval=1/weeks`、`nextcall=2026-10-12 00:00 UTC`（= 周一 08:00 Asia/Shanghai，**时区换算正确**）、`code=model._cron_send(<id>)`；`cron.method_direct_trigger()` 走**真实 cron 通道** → `send_log.kind=reminder`，正文渲染出「周五 2026-10-09 …」；把它 cron 停用后跑自愈 → 「检查 1 条，修复 1 条」 |
| F5 前提 | `edu_tg_assist.owner_user_id` 仍未配 ⇒ **不建待办**（按设计绝不猜谁是校长）；cron 46（mention）/ 47（reminder）都在、仍默认停用 |

**代价与纪律（必须记住的一课）**：两次探针的**回显里出现了真实邀请码** —— 一次是学生路 `/start`，一次是 `/help` 走 bind 出码。
根因**不是**掩码逻辑写错，而是 **odoo shell 的事务是 REPEATABLE READ，看不见 web 进程刚提交的行**（探针里 `created_row=False` 就是证据），
于是「取 code 去掩码」拿到空值 ⇒ 原样打印。处置：**作废这两张码**（`edu.invite.code` id 43 / 44 → `state=used`、`used_count=1`、
`use_limit=1`、`expire_at` 置过去、note 写明原因），可用码池 **166 → 164**，33 条已领记录不变、**无学生受影响**。
纪律：①在 shell 里发出**带外写请求**后，必须先 `env.cr.commit()` + `env.invalidate_all()` 再查询，否则读到的是旧快照；
②合成探针**只发白名单指令**（`/assist /name /whoami /dm /tpl`），别发 `/help` 或自由文本 —— 那会真的走 bind 发码。

**清理后收尾读数（2026-10-09）**：`edu_tg_assist` 六张业务表全 0（person / chat / template / reminder / dm / mention），
`send_log` 只剩早前那条 DRY_RUN 自检；`ir.cron` 41 条（探针 cron 随规则 `unlink` 一并删除，无孤儿）；
`edu.tg.claim` 33 行、可用码池 164。

### 9.8 命令菜单（2026-10-09，起因：用户反馈「我怎么只有这一点功能啊」）

**发现**：`getMyCommands`（`default` 与 `all_private_chats` 两个 scope）**都只有一条**
`zhuce — 获得邀请码，一人仅一码`；全仓（`custom_addons` + `scripts`）与生产 addons/scripts 里
`setMyCommands` **0 命中** ⇒ 这份菜单是当年有人在 BotFather 里**手工设的，没有任何代码在维护它**。
后果：用户在 Telegram 里点 "/" 只看得到一条命令，看不到 `/assist`，于是既找不到班务助手、也以为"功能很少"。

**同一现象的第二个成因**（不是 bug，是 §9.3 的 fail-safe）：用户私聊发的是自由文本「你好」，
而他还不在「人员映射」里（`STAFF_COUNT=0`）⇒ 按判据**走 bind 出码**，于是收到「你已经领过邀请码了，这是你原来那张」。
⇒ 让老师"进来"的动作只有一个：私聊发 `/assist`；随后由管理员在后台把人标成 行政/教师/宿舍长，
之后他发什么都会进班务助手（这条已在生产验过，见 §9.7）。**登记动作刻意不自动化**：
任何"按聊天记录自动认人"的做法都可能把误发过指令的学生改道，破坏 §9.3 的 fail-safe。

**处置**：用 `setMyCommands` 发布三份菜单 —— `default` 与 `all_private_chats` 同一份
（8 条：`start` / `zhuce` / `assist` / `name` / `whoami` / `dm` / `tpl` / `notify`），
`all_group_chats` 一份（2 条：`notify` / `assist`）；三条 `setMyCommands` 均 `ok=true`，
`getMyCommands` 逐 scope 回读通过。可复用脚本 **`scripts/set_bot_commands.sh`**
（本仓第一个 `setMyCommands` 调用；token 走参数或 `TG_TOKEN`，脚本只打印 API 应答、不打印 token）。

**纪律**：菜单是**全 bot 共用**的（学生也看得到老师那几条）⇒ 每条描述必须写清"谁用"；
且**不要把 `/help` 列进菜单** —— `/help` 不在前门白名单里、仍走 bind 出码（§9.3、§9.7 已实测烧掉一张码），
列它等于让用户点了看到邀请码；要列就得先把它加进白名单，那会改道学生的 `/help`，本裁定不做。


### 9.9 F4 打卡闭环接通 F1（2026-10-10，计划 B1）

**背景（用户 2026-10-10 反馈「我怎么只有这一点功能啊」后的整改之一）**：F4（内联按钮）原本**只服务 @提醒待办**
（`edu.tg.assist.reply`，`ck:` 前缀），与 F1 定时提醒**没有接通** —— 宿舍长点击的按钮**发不出来**，
「谁没回」也就无从统计。本轮把两者接上：**一次带按钮的群发 → 谁点了什么落库 → 后台看已回/应回/未回名单**。

**数据模型裁定：另立两张表**（`edu.tg.assist.poll` / `edu.tg.assist.poll.reply`），
**不给 reply 加列、也不写 `edu.checkin.record`**。理由：
① reply 的语义是「同一条 @提醒待办的一条回填」（`unique(mention_id, tg_user_id)`），塞进群发打卡会让 F5 的统计含糊；
② 打卡是**一次群发对多人**，与「待办对单人」不是同一种东西，分开后两边各自唯一约束、各自视图；
③ 写 `edu.checkin.record` 就是跨模块耦合，本轮**不做**（要接 Odoo 考勤域时另立桥接模块）。

**分流**：两张表用两个回调前缀 —— `ck:`（reply，F5）与 `p:`（poll，F4 打卡）。
`polls.parse_callback` 只认 3 段且首段 `p`，`reply.parse_callback` 只认首段 `ck` ⇒ **互不抢**；
三条入口（前门 / assist 自带路由 / 后台「立即发送一次」）口径一致。

**数据流**：
```
定时提醒(勾「带打卡按钮」) → _do_send → _create_poll(建 poll，state=draft)
  → api.send_message_full(..., reply_markup=打卡键盘) → 拿到 message_id
  → poll._mark_sent(ok, result, err) → state=sent / sent_at / message_id
宿舍长点按钮 → callback_query(p:12:done) → poll.reply._tg_assist_handle_callback
  → 落 edu.tg.assist.poll.reply（重复点 = 改选项，不新增）
后台「打卡统计」→ expected / replied / missing（未回名单）
```

**实现要点（都为了「不许静默失败」）**：
1. `api.send_message` 拆出 `send_message_full`（多返回 Telegram 的 `result`，打卡要 `message_id`）——
   `send_message` 变成薄封装，**同一段实现**，不带按钮的调用方行为与从前逐字节相同。
2. `callback_data` 受 Telegram **64 字节**硬限 ⇒ 只用 ASCII 短值；`build_callback` 超限返回 `None`，
   整条打卡**放弃按钮、降级纯文本**并在 `note` 里写明 —— 宁可没有按钮，也不能让 Telegram 把整条消息拒掉。
   `with_buttons` **默认关闭** ⇒ 老规则的 payload 不变。
3. 未登记的人点按钮**不落库**（toast 引导「先私聊 /start」）；`state != 'sent'` 的按钮一律 toast，不写数据。
4. 统计口径 = 「人员映射」里 `role == expected_role` 且 `active=True` 的人；`expected_role='all'` 为全体已登记的人。
   **只统计主动登记过的人**（Telegram 不允许机器人主动私聊从没说过话的人，这是平台机制不是我们的选择）。
5. toast 只有**一份实现**（`edu.tg.assist.reply._answer`），打卡复用它，避免两处出网口径漂移。

**验证（2026-10-10，本地克隆库；探针已全部清理）**：离线单测 `tests/unit/tg_assist_poll_test.py` **27/27 通过**
（64 字节边界、`p:`/`ck:` 分流、角色过滤、未回名单）；`odoo shell` 端到端：`with_buttons` 发一条 → poll 状态 sent、
两个按钮、`callback_data=p:1:done`；**不勾**的规则**不建 poll 行**（回归）；未登记的人点击**不落库**；
同一人连点两次 → **1 行、选项被改成第二次**；统计 `expected=1 / replied=1 / missing=0`（老师与停用的人不计）；
关闭后再点 → `closed_poll`；`ck:` 仍走 `edu.tg.assist.reply`（返回 `missing_record`，不碰打卡）。
`docker compose stop web && bash scripts/safe_upgrade.sh edu_tg_assist` → `SAFE_RC=0`，离线门禁全绿。

### 9.10 上手体验整改：C 组（登记引导/群短名/回执）+ D 组（自检/清理/停发）（2026-10-10）

**背景**：用户再次反馈「我怎么只有这一点功能啊」（上一次催生了 §9.8 命令菜单与 §9.9 打卡闭环）。这一轮解决的是
「登记完不知道下一步」「群短名只能回后台手填」「私发回执看不出发给谁」「出问题只能靠猜」以及运营面的「发送记录只涨不清」。

#### C 组 —— 让上手路径自己走通

- **C1 登记引导 + 待标注筛选 + 新登记通知**：`_cmd_start` 回话末尾加「等管理员在后台把你标成 行政/教师/宿舍长 后，你发任何消息都会进班务助手」；
  人员映射加搜索视图（筛「待标注角色（其他）」/「已标成教职工」/按角色分组）；新人私聊登记后，
  `person.notify_new_if_needs_label()` 私聊 `edu_tg_assist.owner_user_id` 那个人（**未配则只写日志、不猜**），提示去后台标角色。
  （原文写的是「`upsert_from_user` 首次 create 时调 `_notify_owner_new_person()`」——2026-10-13 修正为先分发后通知，
  否则绑定码路径会给刚绑好的人发假警报，见 §9.12.10。）
  **为什么必须做**：前门判据是「role ∈ staff」（§9.3），**没标角色的老师发自由文本仍会被送去领码流** —— 必须在登记那一刻就把人引到
  「去后台标角色」，否则他永远以为这机器人只会认几条指令。
- **C2 群内 `/alias`**：管理员在群里发 `/alias 学习群` 就给**当前群**起短名（不必再回后台手填）；撞名回「短名「X」已经被「Y」占用了，请换一个。」
  并在 `edu.tg.assist.dm` 留痕（state=alias_taken），**绝不覆盖**已有短名。写操作包在 savepoint 里，撞库异常也回同一句话。
- **C3 学生误发 `/name` 的提示**：`/name` 在前门白名单里（§9.3），学生手滑会走进班务流；成功回执后追加
  「（如果你是学生、要的是注册邀请码，请发 /start。）」——不给他一句回头的指引就会卡死在那儿。
- **C4 回执更明确**：`/dm` 成功回执带 `（角色：X／Telegram：@yyy）`；`/notify` 成功回执带群短名与 Telegram `message_id`
  （改用 `send_message_full` 取 `result.message_id`；dry-run 时显示 `—`）。

#### D 组 —— 运营面（自检 / 清理 / 停发）

- **D1 后台「自检」**：瞬态模型 `edu.tg.assist.selfcheck`（**无表**，打开即跑 `api.selfcheck_lines()`）：token 与两个 webhook 密钥**只报长度**、
  前门 `edu_tg_gate` 是否装载、`edu_tg_assist.token` 与 `edu_tg_bind.token` 是否同值（**比对但不打印**）、`dry_run`、owner 参数与 owner 是否已登记、
  两条 cron 的开关、各表条数；另调 Telegram `getMe`（`can_read_all_group_messages=false` ⇒ 提示去 BotFather 关隐私模式）与 `getWebhookInfo`
  （网址与 `web.base.url + /telegram/sctrs/webhook` 比对、pending、`allowed_updates` 是否含 `callback_query`、`last_error_message`）。**只读**，出网仅这两个方法。
- **D2 发送记录清理**：默认**开**的 cron（每天 03:30 **UTC**）+ 后台菜单「清理发送记录」手动清一次；
  保留天数 = 系统参数 `edu_tg_assist.send_log_keep_days`（默认 90；**0 = 一条也不清**）。日志只记「清理 N 条」，不记内容。
- **D3 `/stop` + 隐私说明**：`/stop`（私聊）把 person 的 `active` 置假并**清空 `chat_id`**（保留 `tg_user_id`），再发 `/start` 自动恢复；
  `/help` 增加两行隐私说明（保存 Telegram 号与真名、只用于私发与提醒、与匿名意见箱是两套独立系统）。
  **联动改动（关键）**：前门 `_staff_chat_ids()` 与 `person.upsert_from_user()` 的查人一律 `with_context(active_test=False)` ——
  归档只该决定「我不发给他」，**不该决定「他的消息进哪个模块」**；否则停用过的老师发 `/start` 会被判成学生流去领邀请码，再也回不来。
- **D4 本轮明确不做**：webhook 健康告警。放在 Odoo 里等于**自己告自己的警**（Odoo 挂了才不会告警），要做得放服务器脚本侧，单独立项。

#### 验证（2026-10-10，本地克隆库；探针全部 rollback、未留数据）

`docker compose stop web && bash scripts/safe_upgrade.sh edu_tg_assist` → **SAFE_RC=0**（web 自动起、就绪 302）；离线门禁全绿
（`tg_gate_router_test` 37 / `tg_assist_text_test` 26 / `tg_assist_poll_test` 27 + `check_english` / `check_odoo_trace` / `check_manifest_tracking` /
`check_view_xpath` / `check_alias_not_extended` / `check_docs_index` / `check_md_tables` / `check_qweb_dict_foreach` / `tests/smoke/init_cross_table_check.py`）。
`odoo shell` 端到端：`/start` → person `active=True`、`chat_id` 写入 → `/stop` → `active=False`、`chat_id` 清空 →
前门 `router.route()` 对已归档的 teacher 仍返回 **assist** → 再 `/start` 恢复；群内 `/alias` 设置成功、撞名回
「短名「学习群」已经被「我爱学习群」占用了，请换一个。」；`/notify` 回「已广播到「学习群」。（消息 id：—）」（dry-run）；
自检 13 行；`_prune_old()` 对 200 天前的记录删 1 条、`keep_days=0` 时删 0 条并弹「保留天数设为 0（永久保留），什么都没有删。」；
人员映射搜索视图三个 filter 就位（`filter_role_other` / `filter_staff` / `group_role`）。


#### 生产上线与验证（2026-10-10）

`bash scripts/deploy_myedu.sh edu_tg_assist` → **DEPLOY_RC=0**；自证「web 在升级完成之后启动过」（升级完成 06:38:53Z < web `StartedAt` 06:39:20Z）、
就绪约 3 秒 `/web/login → 302`、公开页 200/302、门户 303、活体注册表门禁 **106/106 模型 LIVE、0 DARK**。
改动文件与生产 **md5 13/13 完全一致**（`set_bot_commands.sh` 不属模块、不进 rsync，单独 `scp` 到服务器后运行）。

- **命令菜单已发布**：`default` 与 `all_private_chats` 各 **9 条**（start/zhuce/assist/name/whoami/dm/tpl/notify/stop）、`all_group_chats` **3 条**（notify/alias/assist），回读核对一致；
  仍**故意不列 `/help`**（不在前门白名单，一走就变学生领码流）。
- **生产库结构核对**：`ir_cron` 51「edu_tg_assist: 发送记录清理」`active=t`、`nextcall=2026-10-11 03:30:00`（UTC）；`ir_act_server` 788「清理发送记录」（`state=code`）；
  菜单 647「清理发送记录」/648「自检」（父 630）；模型 `edu.tg.assist.selfcheck` 与它的 `ir.model.access` 都在。
- **生产功能探针**（`odoo shell`，全程事务内、结尾 `env.cr.rollback()`；`edu_tg_assist` 全模块**没有一处 `cr.commit()`**，psql 事后复核 `person=1 / chat=0 / claim=33 / send_log=2` 未变）：
  `/stop` → `active=False` 且 `chat_id` 清空 ⇒ 随后发自由文本 `chat_id` **保持为空**（不再被写回）⇒ `/start` 恢复 `active=True` 且地址写回；
  被归档的 `teacher` 走前门仍返回 **assist**；`/dm 探针乙 …` 回执「已私发给 探针乙（角色：其他／Telegram：probeB）。」；
  群内 `/alias 探针群` 成功、第二群同名被拒（「短名「探针群」已经被「探针群」占用了，请换一个。」）；新登记触发 `admin_notice` 私聊通知；
  `action_prune_now()` 回「已删除 0 条（保留最近 90 天）」；`selfcheck_lines()` 15 行全部符合预期。
- **真发验证**：`send_message_full()` 给管理员登记的那个号真发一条自检消息 → `ok=True`、`message_id=110`、`send_log` 记 `kind=verify ok=True`。
- **生产现状**：`edu_tg_assist.dry_run=0`、`edu_tg_assist.token` 46 字符、前门密钥 32 字符、`owner_user_id`/`owner_username` 已配、
  `can_read_all_group_messages=true`（隐私模式已关）、`getWebhookInfo` = `https://edu.example.org/telegram/sctrs/webhook`、`pending=0`、`allowed_updates=['message','callback_query']`；
  人员 1 条（`role=admin`）、群 **0 条** ⇒ 唯一还没做的用户侧动作是**把 @sctrs_bot 拉进群**。
#### 顺手记下的两个 Odoo 19 坑

1. **`<search>` 里的 `<group>` 只收 `<field>`**（RNG 无 `string` / `expand` 属性）⇒「按角色分组」必须用带 `group_by` context 的
   `<filter context="{'group_by': 'role'}"/>`，否则整份视图报「定义无效」。
2. **`ir.cron` 的 `nextcall` 在 XML `eval` 里**：`convert.py` 是 `from datetime import datetime, timedelta` ⇒ `datetime` 是**类**，
   要写 `(datetime.now() + timedelta(days=1))`；写成 `datetime.datetime.now()` 会 `AttributeError: type object 'datetime.datetime' has no attribute 'datetime'`，
   表现为升级到一半 `ParseError: while parsing .../data/ir_cron_data.xml`。
---

## 9.11 F7 落地设计：材料智能归档（2026-10-10 用户拍板「做」）

### 9.11.1 批准与前置调研

- 用户原话（m01239）：**「做」**（回答「F7 要不要做」）⇒ §3 表格里 F7 的「⏸ 本轮不做」与 §7.1 的「建议先不做」**同时作废**，以本节为准。
- 铁律 0 前置调研已落盘：`docs/research/ai-archive-and-notion.md`。三条排除理由（社区版 `odoo/odoo` 19.0 的 `addons/ai` 直取 **404**、AI 字段要 **Studio**、文档分类要 **Documents** 应用；OCA 19.0 只有 `ai_tool`（AGPL-3，无流水线）；Notion 属性强依赖目标库 schema）。

### 9.11.2 做什么 / 不做什么（边界先写死）

**做**：老师把材料**转发**给 @sctrs_bot（私聊）→ 立即落库 + 立即回执 → cron 用**规则**（永远有）或 **LLM**（配了才用）抽取「标题 / 类别 / 紧急度 / 截止日期 / 摘要 / 关键信息 / 标签」→ 后台「材料归档」可看·可改·可重跑 → 可选导出 Notion。

**不做**（四条，防止范围蔓延）：
1. **不下载文件本体**：只记 `file_name / mime / file_id / caption`，避免大文件与额外出网；
2. **不自动建/改 Notion 库**：用户自己建库并把 integration **share 进库**（Notion 侧动作，程序无法代办）；
3. **不给学生用**：只有「角色 ∈ 教职工」的私聊才进归档，学生流**一字不变**；
4. **不把原文自动送 Notion**：默认只送 AI 摘要与关键信息（`notion_include_raw=1` 才带原文）。

### 9.11.3 数据流（一眼看懂谁在什么时刻做了什么事）

```
老师私聊转发 ──(前门 edu_tg_gate：role∈staff ⇒ assist)──► bot._handle_private
   ├─ 建 edu.tg.assist.material  state=new          ← 先落库（本仓铁律），立刻 cr.commit()
   ├─ 立刻回执「已收下，正在分类…」                    ← 不让老师等 LLM
   └─ cron「材料分类归档」（每 1 分钟）state=new 的记录：
        ├─ 规则抽取（永远执行一次，兜底）
        ├─ 参数配齐了？→ 出网前脱敏 → POST {llm_base_url}/v1/chat/completions → 严格 JSON
        │     └─ notion_enabled=1 且 token+库 id 都在？→ 导出（保底 title + 正文块）
        └─ 私聊回执第二条：类别 / 紧急度 / 结论（LLM 失败也回，并把错误原文落 llm_error）
```

**为什么分析放 cron 而不是 webhook 里同步做**：① Telegram 的 webhook 有超时（超时会被重投，等于重复处理）；② 本仓铁律是「先落库再出网」；③ LLM 抖动不该让老师看到失败。

### 9.11.4 模型与参数

**新模型 `edu.tg.assist.material`**（表 `edu_tg_assist_material`）字段：
`name`（标题，AI 给的或原文首行）、`source_person_id`、`source_chat_id`、`message_id`、`kind`（text/document/photo/voice/other）、`raw_text`、
`file_name` / `file_mime` / `file_id`、`category`（Selection）、`urgency`（low/normal/high/urgent）、`deadline`（Date）、`summary`、`key_points`、`tags`、
`ai_state`（rule/llm/llm_failed）、`llm_model`、`llm_error`、`notion_state`（off/pending/ok/failed）、`notion_page_id`、`notion_url`、`notion_error`、
`state`（new/analyzed）、`analyzed_at`、`active`。

**服务模型（无表）**：`edu.tg.assist.llm`（OpenAI 兼容客户端）、`edu.tg.assist.notion`（Notion 客户端）；
**纯函数**放 `models/mattext.py`（JSON 宽容提取、字段净化、脱敏、中文日期解析、规则抽取、Notion payload 组装）—— 全部进单测。

**系统参数（全部 `edu_tg_assist.*`；查值一律只查长度，秘密值不打印）**：

| 参数 | 默认 | 作用 |
|---|---|---|
| `llm_base_url` / `llm_model` | 空 | **任一为空 = 零出网**（退规则抽取） |
| `llm_api_key` | 空 | 只报长度 |
| `llm_timeout` | 20 | 秒 |
| `llm_max_chars` | 4000 | 送进模型的原文上限（超出截断并在 `llm_error` 标注 `truncated`） |
| `notion_token` / `notion_db_id` | 空 | **任一为空 = 只存本库** |
| `notion_api_version` | `2026-03-11` | 版本头（调研里是未验证项，故做成可配） |
| `notion_parent_type` | `database` | `database` / `data_source`（Notion 2025 起两套并存，调研未验证 4） |
| `notion_enabled` | `0` | 默认关；开也只对「属性谈得上」的库生效 |
| `notion_include_raw` | `0` | 默认不把原文送 Notion |
| `material_keep_days` | 365 | 归档保留天数（0 = 永久） |
| `material_auto_analyze` | `1` | cron 是否自动分析（关掉只留手动按钮） |

### 9.11.5 硬边界（B1–B8 之后续编，两条都不能破）

- **B9**：LLM 与 Notion **默认零出网**（参数没配齐就一个包都不发）；所有失败只落库、绝不抛给 Telegram 回执。
- **B10**：出网前必须脱敏（手机号 / 身份证号 / 银行卡号 / 本仓邀请码 `STU-*` → 占位符）；脱敏是纯函数且**必须有单测**。
- **B11**：材料原文**只存本库**；送 Notion 默认只有摘要与关键信息；仍**不读写** `edu.feedback.*`、不与匿名意见箱任何数据 join（B1/B5 不变）。
- **B12**：归档只对「角色 ∈ admin/teacher/dorm_head」的私聊生效；**前门判据（§9.3）不改**，学生与未知角色走原路、一字不变。

### 9.11.6 降级表（每一种「不顺利」都要有确定行为）

| 情形 | 行为 |
|---|---|
| 没配 LLM | 规则抽取（中文日期 / 金额 / 急词 / 关键词类别），`ai_state=rule`，回执注明「未配 AI（规则抽取）」 |
| LLM 返回不是 JSON | 宽容提取第一段 `{...}`；仍失败 ⇒ 保留规则结果，`ai_state=llm_failed` + `llm_error` 落库 |
| LLM 超时/网络错 | 同上（`llm_error` 记 `type(exc).__name__`，**不记 key**） |
| Notion 未开 / 未配 | `notion_state=off`（后台显示「未开启」），本地归档照常 |
| Notion 属性对不上 schema | **保底**只写 `title` + 正文块（摘要 / 关键信息 / 来源），`notion_state=ok` |
| Notion 401/403/404/400 | `notion_state=failed` + 错误原文进后台，**不回滚**本地归档 |

### 9.11.7 本地实现与实测读数（2026-10-10）

**新增文件**：`custom_addons/edu_tg_assist/mattext.py`（418 行纯函数：脱敏 / JSON 宽容提取 / 字段净化 / 中文日期解析 / 规则抽取 / Notion payload 组装）、
`models/llm.py`（OpenAI 兼容客户端，唯一大模型出网口）、`models/notion.py`（Notion 客户端）、`models/material.py`（归档模型 + 挂点 + cron + 按钮）、
`views/assist_material_views.xml`、`tests/unit/tg_assist_material_test.py`。

**改动文件**：`models/bot.py`（私聊挂点 `_note_private_message`：**空文本**与**不是指令**两条路都先问挂点）、`models/__init__.py`、`__manifest__.py`、
`security/ir.model.access.csv`（材料表**只给 `base.group_system`** —— 含原文，不开放只读）、`data/ir_cron_data.xml`（+2 条 cron，均默认开）。
挂点与群挂点同款自动发现（谁实现 `_tg_assist_note_private_message` 谁生效）⇒ `bot.py` 里没有一行提到 material 这个模型。

**离线门禁（全 rc=0）**：`tests/unit/tg_assist_material_test.py` **72/72**、`tg_gate_router_test.py` 37、`tg_assist_text_test.py` 26、`tg_assist_poll_test.py` 27；
`check_english` / `check_odoo_trace` / `check_manifest_tracking` / `check_view_xpath` / `check_alias_not_extended` / `check_docs_index` / `check_md_tables` / `check_qweb_dict_foreach` / `tests/smoke/init_cross_table_check.py`。

**本地升级**：`bash scripts/safe_upgrade.sh edu_tg_assist` ⇒ **EXIT=0**；库内核对：`edu.tg.assist.material` 表与全部字段已建、2 条新 cron（「材料分类归档」1 分钟 / 「材料归档清理」1 天，均 active）、菜单「材料归档」（id 822）、ACL 1 条。

**端到端探针**（本地库，单事务 + 末尾 `env.cr.rollback()`，事后 material/person 计数 0/0）：

| 用例 | 读数 |
|---|---|
| A1 老师私聊自由文本（内含手机号） | 建材料；规则抽取 `notice` / `high` / `ai_state=rule` / `state=analyzed`；**原文保留手机号**（只存本库，B11）；回执 `DRY_RUN` |
| A2 学生私聊自由文本 | 材料数 **0**，回话与改前逐字一致（B12） |
| A3 老师转发文件（document） | `kind=document`，`file_name` / `file_id` / `file_size` 落库，当场规则分析 |
| A4 空消息（既无文本也无附件） | 仍回 `non_text_private` |
| B1 LLM 路径（假 200） | 端点 `…/v1/chat/completions`；载荷里**手机号已脱敏**（占位符在、原号不在）；LLM 结果覆盖规则（标题/类别/紧急度/截止/标签），`ai_state=llm`、`llm_raw` 留档 |
| B2 LLM 返回非 JSON | `ai_state=llm_failed` + `llm_error='模型没有给出可解析的 JSON：…'`，规则结果保留 |
| B3 LLM 超时 | `ai_state=llm_failed` + `llm_error='Timeout: probe timeout'`，**key 未泄漏** |
| C1 Notion 未配 | `notion_state=off` |
| C2 Notion 假 200 | 只写**有值的格子**（Name / Summary / Category / Urgency / Tags）；正文不含原文手机号（B11） |
| C3 Notion 400 | 自动用保底 `title` + 正文重试一次 ⇒ `notion_state=ok`、`notion_fallback=True`、tries=2 |
| C4 Notion 401 | `notion_state=failed` + 错误原文进后台；本地行仍在（不回滚） |
| D1 cron 开关 | `material_auto_analyze=0` ⇒ 返回 0；`=1` ⇒ 返回 2 |
| D2 清理 | `material_keep_days=0` ⇒ 删 0 条 |
| 脱敏纯函数 | 手机号 / 银行卡 / 邀请码 / 邮箱 4 处全替换（`hits=4`） |

**生产实测（2026-10-10 部署后）**：`bash scripts/deploy_myedu.sh edu_tg_assist` ⇒ **DEPLOY_RC=0**（升级完成 09:59:55Z < web StartedAt 10:00:25Z；就绪 3 秒 302；公开页 200/302、门户 303；活体注册表 **109/109 模型 LIVE、0 DARK**）。
本地↔生产 **10/10 文件 md5 一致（0 drift）**；生产库核对：`edu.tg.assist.material`（35 字段）、cron 52「材料分类归档」1 分钟 active=t / cron 53「材料归档清理」1 天 active=t、菜单 649「材料归档」父 630、ACL 1 条。
**B9 零出网自证**：生产 `edu_tg_assist.llm% / notion% / material%` 参数条数 = **0**；生产端到端探针（同一脚本，单事务 + `rollback`）读数与上表**逐条一致**，事后 `material=0 / person=1 / chat=0 / claim=33`（探针未留痕、未真发消息、未动学生流）。
**生产形态（本轮部署后）**：`llm_*` 与 `notion_*` 参数**一律不配** ⇒ 生产上 F7 = 「规则抽取 + 只存本库」，**零出网**（B9）；
要开大模型或 Notion 是用户侧单独决定的事（改参数即可，不需要改代码）。BotFather 侧**无需任何改动**（F7 不加新指令，靠私聊转发触发）。

## 9.12 新手教程（甲）+ 学号登录（乙）+ 身份绑定码（2026-10-12 用户裁定）

### 9.12.1 为什么有这一节

用户 2026-10-12 连提三件：

1. 「这个玩意要不要注册吗？我比如说那个老师使用，她最好可以绑定身份不是吗」⇒ 现状老师要**三步**
   （私聊 `/assist` → `/name 真名` → 管理员在后台把人标成 行政/教师/宿舍长），标注之前她的自由文本
   会被前门判成学生流（§9.3 判据）。**痛点是真的**：没有「绑定身份」这一步的入口。
2. 「你最好这样做，让这个机器人呢有一套完整的新手教程，要引导用户注册和登录使用。根据：学号+密码来登录注册。」
   ⇒ 实测**「学号 + 密码」当时并不成立**：注册页填「邀请码 + 姓名 + 邮箱 + 密码（+ 学号选填）」，
   登录页填「邮箱 + 密码」（`custom_addons/edu_portal/controllers/register.py:138` `'login': vals['email']`；
   `docs/plans/invite-code-tiers-design.md:59`）。所以给出**甲/乙/丙**三选：
   · 甲 = 教程照现状写（邮箱登录）；
   · 乙 = **加一条「学号 + 密码」登录通道**（邮箱登录保持不变）；
   · 丙 = 取消邀请码、学号即注册（**否决**：拆掉「谁能注册」的闸门，且会让未注册学号被冒领）。
3. 「那就甲加乙。」+ 三个群 ID ⇒ **甲、乙都做，并加身份绑定码**。

### 9.12.2 做与不做

**做**：

- **身份绑定码**（assist）：管理员生成一次性码（后台「绑定码」页，或私聊 `/bindcode 教师 张三`）⇒
  老师点深链或发 `/bind <码>` ⇒ **姓名 + 角色一次绑定**，不必再等管理员在后台点。
- **新手教程**（分身份，两边各一份，不新造第二套说明）：
  · **学生版**（`edu_tg_bind` 领码回复，学生只会走到这里）：领码 → 去注册（填码/姓名/邮箱/密码，学号选填）
    → 去登录（邮箱+密码，或学号+密码）→ 使用指南 `/help/student`；
  · **教职工版**（assist `/start`、`/help`）：绑定身份 → 可用指令 → 群里的用法 → 隐私说明。
- **学号登录**（`edu_portal`）：登录页的「登录名」栏**同时接受邮箱与学号**（学号按 `op.student.gr_no`
  解析到该学生账号的登录名再认证），失败限速，纯函数单测。

**不做**：

- 不取消邀请码、不改注册页必填项（丙否决）；
- 不在 `res.partner` 新开学号字段（学号唯一真身是 `op.student.gr_no`，
  见 `custom_addons/edu_portal/models/partner_edu.py:33`）；
- 不让「学号」成为**新**账号体系：学号只是登录名的**别名**，认证仍然是 Odoo 的 `res.users` 密码；
- 不在 Telegram 里收密码（教程里明写：**密码只在网站登录页输入**）。

### 9.12.3 绑定码数据流

```
管理员                       老师（Telegram）                      机器人
  生成绑定码 ──┐
   /bindcode 教师 张三         点 https://t.me/sctrs_bot?start=BIND-XXXXXX
                              （或手输 /bind BIND-XXXXXX）
                                    │
                         前门 edu_tg_gate 判据：
                           /start <载荷> 且载荷匹配签发格式 → assist
                           /bind → assist（在白名单里）
                                    ▼
                     edu.tg.assist.bindcode.redeem(code, person)
                       · 码不存在/已用/过期 → 回「这个绑定码无效或已经用过了」
                       · 命中 → person.name = 码上的姓名，person.role = 码上的角色，
                                person.active = True，码置 used + person_id + used_at
                     ◀── 回执：已绑定：张三（教师）。现在你发任何消息都进班务助手。
```

### 9.12.4 模型与参数

新表 `edu_tg_assist_bindcode`（模型 `edu.tg.assist.bindcode`）：`code`(Char, required, unique) /
`name`(Char, required) / `role`(Selection，同 person) / `state`(new/used/void) / `person_id`(M2O) /
`expire_at` / `used_at` / `note` / `active`。

参数（全部 `edu_tg_assist.*`，查值只查长度）：`bot_username`（默认 `sctrs_bot`，只用于拼深链）、
`bind_code_days`（默认 14，绑定码有效期）。

### 9.12.5 硬边界（新增）

- **B13 绑定码只改「身份标注」，不改判据**：前门 §9.3 的分流规则一字不动；绑定码只是把
  「管理员在后台点角色」换成「老师自己点一次」。学生流仍逐字不变。
- **B14 学号登录只做别名解析**：只在登录时把「学号」翻成该学生账号的登录名，**绝不**凭学号
  建账号 / 发邀请码 / 改密码；解析失败与密码错误回同一句提示（不给「这个学号存在吗」的探针）。
- **B15 教程里绝不引导在 Telegram 发密码**：网站登录页是唯一输密码的地方；两版教程都明写这一条。

### 9.12.6 降级表

| 情况 | 行为 |
|---|---|
| 绑定码过期/已用/不存在 | 回「这个绑定码无效或已经用过了，请找管理员要一张新的。」，**不改** person |
| 没配 `bot_username` | 用默认 `sctrs_bot` 拼深链；深链打不开时 `/bind <码>` 仍可用 |
| 学号查不到账号 / 一个学号对应多个账号 | 视为解析失败 ⇒ 按普通登录失败处理（不猜、不提示「学号存在」） |
| 学生没有学号（生产 51 位学生里 6 位无学号） | 教程里写明「没有学号就用邮箱登录」 |
| 登录失败次数过多 | 落库的失败计数拦下（15 分钟内 8 次 ⇒ 封 15 分钟）⇒ 仍按普通失败回话（不泄露是否被限速） |

### 9.12.7 教程文案口径（两边各自的唯一来源）

- 学生版：`custom_addons/edu_tg_bind/models/tg_claim.py` 的 `reply_text(created)`（首次领码 / 重复领码两版）；
- 教职工版：`custom_addons/edu_tg_assist/models/bot.py` 的 `help_text()` 与 `_cmd_start`（`/help` 按角色分版）；
- 网站侧使用指南：`custom_addons/edu_portal/controllers/help_center.py` 的学生/教师页（补「学号也能登录」一句）。

### 9.12.8 实现与实测读数（2026-10-12）

**新增/改动文件**

| 文件 | 作用 |
|---|---|
| `custom_addons/edu_portal/login_alias.py` | 纯函数：学号判据 `looks_like_gr_no`、限速键 `bucket_key`、失败窗口策略 `next_failure_state` / `blocked_seconds` |
| `custom_addons/edu_portal/models/login_throttle.py` | 新表 `edu.portal.login.throttle`（跨进程共享的失败计数） |
| `custom_addons/edu_portal/models/login_alias.py` | `login_for_gr_no`（学号 → 登录名）、`blocked_seconds`、`note_attempt`（独立事务落库） |
| `custom_addons/edu_portal/controllers/main.py` | `_edu_alias_login()` 改写 `request.params['login']`；`web_login` POST 前后记结果 |
| `custom_addons/edu_portal/views/register.xml` | 登录页提示：学号也能登录（邮箱不变） |
| `custom_addons/edu_tg_assist/bindtext.py` | 纯函数：绑定码码表 / 载荷格式 / 深链 / 角色词 |
| `custom_addons/edu_tg_assist/models/bindcode.py` | 新表 `edu_tg_assist_bindcode` + `/bind` `/bindcode` |
| `custom_addons/edu_tg_assist/models/bot.py` | `help_text()`、`/start <载荷>` 转 `/bind`、教职工教程 |
| `custom_addons/edu_tg_gate/routing.py` / `models/router.py` | 深链载荷判据（`/start BIND-…` → assist；其余 `/start` 仍归学生领码流） |
| `custom_addons/edu_tg_bind/models/tg_claim.py` | 学生版教程 + 「🔑 去登录」「📖 使用指南」两键 |

**门禁**（全 rc=0）：`tg_gate_router_test` 60/60、`tg_assist_bindcode_test` 33/33、`edu_portal_login_alias_test` 42/42、`tg_assist_text_test` 26、`tg_assist_poll_test` 27、`tg_assist_material_test` 72、`check_english`、`check_odoo_trace`、`check_manifest_tracking`、`check_view_xpath`、`check_alias_not_extended`、`check_docs_index`、`check_md_tables`、`check_qweb_dict_foreach`、`check_shell_exitcode`、`tests/smoke/init_cross_table_check`。

**本地升级**：`bash scripts/safe_upgrade.sh edu_tg_assist,edu_tg_bind,edu_tg_gate,edu_portal` ⇒ `SAFE_RC=0`（web 自动重启、`/web/login?db=edu19 → 302`）。

**本地端到端读数（真 curl，本地克隆库）**

| 用例 | 读数 |
|---|---|
| `GET /login` | 新提示在（1 处）、「使用邀请码注册」链接仍在 |
| 学号 + 正确密码（`POST /login`，先取 csrf） | **303 → /my/home**，带 cookie 访问 `/my/home` = 200 |
| `POST /web/login`（核心路由）学号 + 正确密码 | **303 → /my/home** ⇒ 子类 `web_login` 对核心路由同样生效（不是只在 `/login`） |
| 学号 + 错密码 ×8 | 第 8 次起 `edu_portal_login_throttle` 落行：`failures=0`、`blocked_until=now+900s` |
| 封禁期内 + 正确密码 | **200**（被挡，按普通失败渲染），日志 `学号登录尝试过于频繁` |
| 邮箱 + 正确密码 | **303**（另一个限速键，完全未受影响） |
| 登录成功后 | 该键的行被删（`rows_after_success=0`） |

**关键发现（限速为什么从令牌桶改成落库）**：进程内令牌桶在多 worker 下被稀释 ——
本地 `odoo.conf` `workers = 6` 时，连打 8 次错密码后用**正确**密码仍 303 登录成功，
日志里「尝试过于频繁」计数为 0（6 个 worker 各有一份 `LOGIN_BUCKET`）。
生产同为多 worker（部署日志有「Stopping workers gracefully」）⇒ 改成**落库共享**
（`edu.portal.login.throttle`：独立事务写、成功即删行、只统计失败 ——
所以学校 NAT 后共用出口 IP 的正常师生不会被连坐）。实测第 8 次失败即封、封禁跨 worker 生效。

**本地现场恢复**：验证期间临时改过 `op.student` id=5 的 `gr_no`（→ `1234567`）与
`res.users` id=8 的密码（→ `GrProbe123!`），已恢复为 `TEST-2026-001` / `demo123`
（仓库既有 fixture，见 `scripts/check_english.py:97`），两个依赖学生登录的门禁
（`check_english` / `check_odoo_trace`）复跑 rc=0。
**教训**：Odoo 19 里 `res.users.password` 经 ORM 读出是**空串**（不能当快照依据），
快照要用 `psql` 读列。

### 9.12.9 生产部署与端到端探针（2026-10-12）

- **部署**：`bash scripts/deploy_myedu.sh edu_portal,edu_tg_assist,edu_tg_bind,edu_tg_gate` ⇒ `DEPLOY_RC=0`；
  自证「升级完成 2026-10-12T07:13:25Z < web 容器 StartedAt 07:13:53Z」；就绪约 3 秒 302；
  公开页 / 200 /programs 200 /apply 200 /contactus 200 /web/login 302、门户全 303；
  活体注册表 14 个模块 **112/112 模型 LIVE、0 DARK**（字段级 SKIP：匿名会话读不到 fields_get）。
- **生产端到端探针**（`odoo shell` + 结尾 `env.cr.rollback()`；事后 bindcode=0 / person=1 / throttle=0）：

| 用例 | 读数 |
|---|---|
| `/start BIND-ABC123`（含小写 `bind-abc123`） | assist |
| `/start`、`/start ref_12345` | bind（学生流不变） |
| `/bind …`、`/bindcode 教师 张三` | assist |
| assist 未装时的 `/start BIND-…` | bind（fail-safe） |
| 绑定码 generate → redeem | code `BIND-XXXXXX`、link `https://t.me/sctrs_bot?start=BIND-…`、pattern `^BIND-[A-Z0-9]{6,6}$`；首次回「已绑定：探针老师（教师）。…」；二次与坏码都回「这个绑定码无效或已经用过了…」；person 写成 name=探针老师 / role=teacher / active=True |
| 教职工教程 | `help_text()` 含 `/bind BIND-XXXXXX`；管理员版含「你是管理员」 |
| 学生领码回执 | 含「新手三步」「绝不要在 Telegram 里发密码」「help/student」；键盘 3 行 4 键（去注册 / 复制邀请码 / 去登录 / 使用指南） |
| 学号解析（真数据，只报长度） | 两个 10 位学号都解析出账号（login 长度 20 / 17）；未知学号与邮箱输入都返回空 |

- **生产探针抓到一条真 bug（已修）**：连打 9 次 `_bump` 后读数是 `failures=1 / blocked=False` ——
  第 8 次写 `failures=0 + blocked_until=now+900`，第 9 次 `next_failure_state` 看到 failures 已被清零
  ⇒ 算出 `(1, now, 0)` 把刚封上的 `blocked_until` **覆盖成 0 = 攻击者多试一次就自己解锁**。
  修法：`_bump` 先判这一行是否正在封禁中（`blocked_seconds(...) > 0`），是则只刷新 `last_attempt_at`，
  不改任何计数与封禁（模型层第二道保险；控制器在封禁期本来就不计数）。
  修后本地复验：9 次 ⇒ `failures=0 / blocked=True / blocked_s=900`，第 10 次仍封着。
- **回归门禁**：新增 `tests/smoke/login_throttle_probe.py`（16 条断言、**自带退出码**）并接进
  `scripts/check_all.sh` 的 E2E 段（`E2E login_throttle`）；本地容器实测 **RESULT=OK 16/16、exit 0**。
- **修后生产复验（2026-10-12）**：`bash scripts/deploy_myedu.sh edu_portal` ⇒ `DEPLOY_RC=0`
  （自证：升级完成 07:21:19Z < web StartedAt 07:22:04Z、就绪 3 秒 302、112/112 模型 LIVE / 0 DARK）；
  生产探针连打 10 次 ⇒ `failures=0 / blocked=True / blocked_s=900`（第 9、10 次仍封着）；
  生产文件与本地 md5 一致 `95b3abf3ec7352942eb09ec5541059f9`。
- **生产 HTTP 自证**：`GET https://edu.example.org/login` 含「学号」提示与「使用邀请码注册」链接；
  `POST /web/login` 用合成学号 `9999999999` + 错密码 ⇒ **200**（按普通失败渲染，不泄露是否被限速），
  且落库一行 `edu_portal_login_throttle`（键 `IP|9999999999`、failures=1）⇒ 证明「控制器 → 模型 → 独立事务落库」
  整条链路在生产活体生效；该合成行随后已删除（表 0 行）。
- **群短名补登**：`学习` = `-1002369779089`（*我爱学习*）、`清洁` = `-1003050833944`（清洁能源站）；
  现存 9 个群里 5 个已有短名（品茶 / AB / 班长 / 学习 / 清洁），其余 4 个待用户给名字。
- **命令菜单漏发与补发（2026-10-12）**：用户在 Telegram 里点「/」看不到 `/bind` `/bindcode` ——
  命令菜单由 `scripts/set_bot_commands.sh` 发布，绑定码上线时漏了同步这一步（后台菜单「绑定码」在，
  但老师根本不知道有这功能）。补：私聊菜单 9 → **11 条**（加 `/bind`、`/bindcode`），
  `help_text()` 常用指令补 `/bindcode` 一行；生产逐 scope 回读 = default / all_private_chats 各 11 条、
  all_group_chats 3 条。**规矩：新增指令必须同步本脚本并重发菜单**（提交 `dfae0b9`）。
- **生产 `/bindcode` 端到端复验（2026-10-12）**：管理员私聊 `/bindcode 教师 张三` ⇒ 回
  「绑定码：BIND-9UUH2S ｜ 姓名：张三 ｜ 角色：教师 ｜ 有效期 14 天」+ 深链 + `/bind` 说明（探针内 dry_run，未真发）；
  新老师私聊 `/bind BIND-EGQPF9` ⇒ 「已绑定：探针老师（教师）。现在你在这里发任何消息都会进班务助手，不用再记指令。」，
  `person` 写入 role=teacher / active=True / 有 chat_id，码 state=used；二次使用走无效码分支；
  `route('/bindcode')`=assist、`route('/help')`=bind（学生流不变）；探针全程 rollback（bindcode=0 / person=1），
  生产 `dry_run` 仍为 `0`。
### 9.12.10 修复：「新登记」通知在绑定码路径上是假警报（2026-10-13）

**起因**：2026-10-12 用户把一张绑定码发给 Sarah💌（行政）之后，机器人私聊了用户一条
「新登记：Sarah💌（Telegram：Sarah💌）。请到后台「班务机器人 → 人员映射」把他标成 行政/教师/宿舍长…」，
用户 2026-10-13 反复问「这是何意味啊？」（m02418 / m02422 —— 不是故障报修，但确实看不懂）。

**生产实读**（`ssh prod-host` → `docker exec edu19-prod-db-1 psql -U odoo -d edu19`）：
`edu_tg_assist_person` id=22 / name=`@sarah1212love` / tg_user_id `5685767636` / role=**admin** /
create_date 2026-10-12 10:16:18 UTC；`edu_tg_assist_bindcode` id=8 `BIND-NWJYEY`（name=`@sarah1212love`）
state=**used** / person_id=22 / used_at 10:16:19 ⇒ **她已经绑成功了**，那条「请去后台标角色」与事实矛盾。

**根因（顺序错）**：`person.upsert_from_user()` 在首次 `create` 分支里**立刻**调 `_notify_owner_new_person()`；
而 `bot._handle_private()` 的顺序是「先 upsert → 再分发 / `/bind` redeem」。带码深链 `/start BIND-NWJYEY`
在同一请求里先建 person（role 默认 other）→ 发通知 → 才把 role 改写成 admin ⇒ 通知比事实早了一瞬，
给一个**刚刚已经是行政**的人发了「请到后台标成行政/教师/宿舍长」的假警报。

**修法**：通知从 `upsert_from_user` 里移出，新增 `person.notify_new_if_needs_label(rec, was_new)`：
`was_new=False` 或 `rec.role != 'other'` 一律**不发**；`bot._handle_private` 开头先取一次
`was_new`（`with_context(active_test=False)`，与 D3 同口径），在**回复发出去之后**调它
（三条出口都接：非文本、无回复、正常回复）。通知文案同时改写：明说「这个人第一次私聊机器人、身份还没绑定」，
并给出两条出路（后台标角色 / 发一张绑定码），不再只骂一句「去后台标」。

**本地验证**（`odoo shell`，全程事务内、结尾 `env.cr.rollback()`；owner 参数临时指向合成管理员 990001）：

| 用例 | 读数 |
|---|---|
| 新人 `/assist` | `{'ok':True,'cmd':'/assist','error':'DRY_RUN'}`；person role=other；`admin_notice` **+1** |
| 新人 `/start BIND-…`（真码，role=admin） | `{'ok':True,'cmd':'/bind','error':'DRY_RUN'}`；person role=**admin**、name=探针乙；`admin_notice` **+0**；码 state=used |
| 老熟人再发自由文本 | `admin_notice` **+0** |

新文案回读：「新登记：探针甲（Telegram：探针甲）。／这个人第一次私聊机器人，身份还没绑定。／
若是教职工：到后台「班务机器人 → 人员映射」把角色标成 行政/教师/宿舍长，或直接发他一张绑定码
（他发 /bind BIND-XXXXXX 即可自动绑定）。／标好之后他发任何消息都会进班务助手；在那之前只认指令。」

**生产复验（2026-10-13）**：`bash scripts/deploy_myedu.sh edu_tg_assist` ⇒ `DEPLOY_RC=0`
（自证：升级完成 00:50:26Z < web 容器 `StartedAt` 00:50:43Z；就绪约 3 秒 302；活体注册表 **112/112 模型 LIVE、0 DARK**）。
改动两文件与生产 **md5 逐字一致**（`person.py 355cd4e8…` / `bot.py 0bab612a…`）。生产 `dry_run=0`、owner 已配（长度 10）——
也就是说**在真发状态下**跑回归用例：合成老师 `/start BIND-…` ⇒ `role=teacher`、码 `state=used`、`admin_notice` **+0**
（这条用例若在生产上仍带旧 bug，会当场真发一条假警报给管理员 —— 它没发生）；守卫负分支
`notify_new_if_needs_label(rec, False)` 返回 `False`；探针结尾 `env.cr.rollback()`，事后 `people / send_log / bindcode` 增量全 0。



## 9.13 按钮化界面：把「记指令」改成「点按钮」（2026-10-13 用户反馈）

### 9.13.1 起因与裁定

用户 2026-10-13 原话：「我总感觉这个机器人不够好用，尤其是对于不擅长写代码什么的人，你让他使用斜杠命令
是有点学习成本的，就不能搞得跟软件一样方便而且一目了然吗」。

**裁定（Phase 1）**：加一层**按钮界面** —— 常驻底部键盘 + 内联按钮分步流程；
**斜杠命令一条都不删**（老用户、老文档、/dm /notify 这类一次性指令照旧可用）。
Telegram Mini App（真网页 App）留作 Phase 2 再问用户：它要 initData 鉴权 + 前端工程，
成本高得多，而按钮层是任何更「像软件」方案的入口，先做不浪费。

### 9.13.2 组成（四个文件 + 两个新前门判据）

| 件 | 作用 |
|---|---|
| custom_addons/edu_tg_assist/menutext.py（新，纯函数、不 import odoo） | 按钮文案/布局/callback_data 的唯一来源：CALLBACK_PREFIX='mn'（与 reply 的 ck: 、poll 的 p: 不撞）、BUTTON_ACTIONS、layout_for(role)、reply_keyboard(role)（is_persistent=True，一直挂在输入框下面）、cb()/parse_callback()/inline()/confirm_rows()/back_row()/truncate() |
| custom_addons/edu_tg_assist/models/menu.py（新，AbstractModel edu.tg.assist.menu，**不新立表**） | 全部按钮逻辑：主页文案、选群/选人/选模板、草稿态、预览、确认发送、越权留痕、_tg_assist_handle_callback |
| models/person.py（改） | 三个字段：ui_state（notify/dm 草稿态）、ui_target（群或人记录 id）、ui_draft（待确认正文） |
| models/bot.py（改） | /menu 与 KEYBOARD_COMMANDS=('/start','/assist','/help')：这几条的回复顺手挂底部键盘；_handle_private 的**未知指令分支**先问 menu._tg_assist_menu_reply()（返回 None 才轮到材料归档/兜底） |
| edu_tg_gate/routing.py + models/router.py（改） | 两条新判据：① menu_chat_ids（person.ui_state 非空的人）② button_texts（menutext.BUTTON_ACTIONS 的六个按钮文案**逐字**匹配）⇒ 否则老师点了按钮/发了正文会被判成学生流、回一张邀请码 |

**为什么要加前门判据**：角色（admin/teacher）要管理员在后台标了才算，而底部键盘在老师发 /assist
那一刻就给出去了 —— 中间这段时间他的按钮与正文不能掉进领码流。

### 9.13.3 流程（点按钮的路径）

私聊 /menu（或 /start /help）
   └─ 底部键盘：📢 发通知到群 ｜ ✉️ 私发给某人 ｜ 📄 文案模板 ｜ 👤 我的身份 ｜ 📚 使用说明 ｜ 🔕 停止私发
        （行政版 3×2；非行政版 2×2，管理按钮不出现）

📢 发通知到群 → 内联列群（短名优先，每行 2 个）→ 点群 → 「把内容发给我」→ 发一条文字
   → 预览（虚线夹住正文）+「✅ 确认发送 / ✖️ 取消」→ 确认 → 真发出网 + 落 send_log
✉️ 私发给某人 → 内联列人（只列教职工，最多 20）→ 点人 → 同上预览/确认 → 真发 + 审计一行
📄 文案模板   → 列启用模板 → 点一条 → 渲染后发给发起人（只读）

### 9.13.4 安全与体验设计（每条都有理由）

1. **按钮绝不能没反应**：未知/过期的 callback 也回主页文案 + 底部键盘；answerCallbackQuery
   一定先答（不答客户端一直转圈）。
2. **草稿态遇到真指令就清掉**：否则他前一步的草稿会在下一秒被当成「正文」发出去 ——
   一条没人确认过的广播就此出网（bot._handle_private 命中指令时先 _clear_state）。
3. **权限与 /dm /notify 同口径**：只有 role=='admin' 能发通知/私发；越权**不留白**，
   写一行 edu.tg.assist.dm 审计（state='denied'、raw='菜单:<动作>'）。
4. **发出前必须过预览**：发送是「先预览、再确认」两步，按钮文案逐字核对（不模糊匹配）。
5. **不猜收件人**：选群/选人只列后台登记过的记录；列表里没有就是不列，绝不按相似名挑一个。

### 9.13.5 真 bug 记录：跨文件方法名错位（单测与升级全绿，真人点才炸）

实现时 bot.py 里写的是 menu._menu_reply(...)，而 menu.py 里的挂点叫
_tg_assist_menu_reply。后果：模块装载正常、离线门禁全绿、升级日志无异常，
**直到真人点第一个按钮**才 AttributeError: 'edu.tg.assist.menu' object has no attribute '_menu_reply'
（被控制器/分发链吞掉后表现为「按了没反应」—— 这正是本模块历史上踩过的静默失败模式）。

**拦住的机制（已加进 tests/unit/tg_assist_menu_test.py 第 10 组）**：正则扫 bot.py 里所有
env['edu.tg.assist.menu'].sudo().<名字>( ，断言 menu.py 里真有 def <名字>( ；
并断言 menu.py 提供 _tg_assist_commands / _tg_assist_handle_callback / _tg_assist_menu_reply 三个挂点。
单测因此从 89 条涨到 **96 条**。

### 9.13.6 本地端到端读数（2026-10-13，odoo shell 合成 chat_id + 结尾 env.cr.rollback()，探针内 patch 出网层）

| 步骤 | 读数 |
|---|---|
| 新人 /assist | 回欢迎语 + 底部键盘（非行政版 2×2）；person role=other |
| /menu（标成 admin 后） | 主页文案 + 行政版 3×2 键盘（📢/✉️/📄/👤/📚/🔕） |
| 点「📢 发通知到群」 | 内联 `我爱学习群=>mn:grp:5` + `🏠 主菜单=>mn:home` |
| 点群 | answerCallbackQuery('好的') + 「把要发到「我爱学习群」的内容发给我」；ui_state='notify' ui_target='5' |
| 发正文 | 预览（虚线夹正文）+「✅ 确认发送 / ✖️ 取消 / 🏠 主菜单」；ui_draft 已存 |
| 点确认 | 真发 kind=notify → 「✅ 已广播到「我爱学习群」。（消息 id：…）」；ui_state 清空 |
| 非管理员点「✉️ 私发给某人」 | 「你没有这个权限。」+ 底部键盘；审计 **1 行** state=denied raw='菜单:notify' sender_role=teacher |
| 私发全流程 | 选人（只列教职工）→ 正文 → 预览 → 确认 ⇒ kind=dm 真发 + 审计 state=sent raw='菜单私发' target_name/target_chat_id/text 齐全 |
| 未知 callback（mn:zzz） | 不静默：回主页文案 + 键盘，并已 answerCallbackQuery |
| 草稿态下发 /whoami | 草稿被清空（ui_state=False），随后的自由文本**没有**被当成正文发出去 |
| 模板按钮（本地无模板） | 「模板库里还没有启用的模板。去后台…加几条，再回来点这个按钮。」 |

### 9.13.7 门禁读数（2026-10-13）

| 门禁 | 结果 |
|---|---|
| tests/unit/tg_assist_menu_test.py | **96/96 通过**（含第 10 组跨文件名字守卫） |
| tests/unit/tg_gate_router_test.py | **76/76 通过**（第 12 组 19 条：按钮文案/menu_chat_ids 走班务、老口径不变、学生 /start 仍领码） |
| tg_assist_text / tg_assist_poll / tg_assist_material / tg_assist_bindcode | 全 exit 0 |
| check_docs_index / check_md_tables / check_english / check_odoo_trace / check_manifest_tracking / check_view_xpath / check_alias_not_extended / init_cross_table_check | 全 exit 0 |
| 本地升级 docker compose stop web && bash scripts/safe_upgrade.sh edu_tg_assist | module loaded 0.66s / 706 queries；新列 ui_state ui_target ui_draft 已建；web 302 就绪 |

> 装载日志里那条 `<string>:10: (ERROR/3) Unexpected indentation.` **不是本次引入的**：
> 对 2026-10-12 16:47 起的每一份升级日志都有同一条、15:15 及更早的没有 —— 是 10 月 12 日
> 那次改动留下的字段 help/描述 RST 缩进告警，属本仓既有风格（edu_assess/edu_zh 等也有），
> 不影响装载与功能，门禁不拦。

### 9.13.8 生产上线与复验（2026-10-13）

部署：`bash scripts/deploy_myedu.sh edu_tg_assist` ⇒ **DEPLOY_RC=0**
（升级完成 2026-10-13T02:30:14Z < web StartedAt 02:30:33Z；约 3 秒后 /web/login → 302；
公开页 / programs apply contactus 200、/web/login 302；门户页 303；
活体注册表门禁 **113/113 模型 LIVE、0 DARK**）。

命令菜单：`scp scripts/set_bot_commands.sh prod-host:/opt/edu-app/` 后在远端回读——
`/menu` 已排在 default 与 all_private_chats 的**第一位**（描述「所有人：点按钮就行（把按钮菜单叫回来，不用记指令）」），
群菜单不变（notify / alias / assist），仍**刻意不列 /help**。

生产复验（odoo shell，合成 chat_id 9900012xx，出网口全部 monkeypatch 后 `env.cr.rollback()`，事后 people/dm 增量 0）：

| 造的 update | 生产回话 | 落库 |
|---|---|---|
| 新人 /assist | 欢迎语 + 非行政 2×2 底部键盘 | person 新建 role=other |
| 改 role=admin 后 /menu | 主页文案 + 行政 3×2 键盘 | — |
| 点「📢 发通知到群」 | answerCallbackQuery + 「📢 想发到哪个群？点一下：」+ 内联群列表（mn:grp:17 等） | — |
| 点群「AB」 | 「好，接下来把要发到「AB」的内容发给我…」+ 取消/主菜单 | ui_state=notify target=17 |
| 发正文 | 预览（虚线夹正文）+ 「✅ 确认发送 / ✖️ 取消 / 🏠 主菜单」 | ui_draft 已存 |
| 点「✅ 确认发送」 | 真发 kind=notify「…各位同事请注意，明天上午 9 点开例会。」+「✅ 已广播到「AB」。（消息 id：…）」 | ui_state 清空、draft 清空 |
| 教师点「✉️ 私发给某人」 | 「你没有这个权限。（发通知与私发只有管理员能用。）」+ 底部键盘 | **审计 1 行** state=denied raw=菜单:dm |
| 未知 callback mn:zzz | 不静默：回主页文案 + 键盘，且已 answerCallbackQuery | — |

图卡：第 4 张 `tg-assist-tutorial-4.png`（277401 字节）部署后可公网取到，
`https://edu.example.org/edu_tg_assist/static/tutorial/tg-assist-tutorial-4.png` → **200 / 277401 字节**（与本地一致）；
已用 sendPhoto 发给王佐 5592841801 与 Sarah 5685767636，**两次都 ok=True**。

> 教训（写进探针规范）：给 `handle_update` 造 update 时，**必须把回调包在 `callback_query` 键里**
> （`{'update_id':…, 'callback_query': {...}}`）。我第一次探针直接把 cq 字典当 update 传，
> 结果每次「点按钮」都被当成普通私聊文本、统一回「我不认识这条指令。」——
> 看上去像按钮全坏，其实是探针造错了信封。回话 kind 也能一眼看出：
> 走菜单的 kind='menu'，走私聊兜底的 kind='private_cmd'。


## 9.14 文件取回：老师转来的文件要能给教务下载（2026-10-13 用户要求）

### 9.14.1 起因

User said (m02907)：「这个机器人能收文件吗？然后再提供给教务sarah老师下载。」
F7 的归档此前**刻意不下载本体**（只记 file_name / file_mime / file_id / file_size），
老师转发来的合同、通知、表格在后台只能看到一个文件名 —— 说不上「收下了」。

### 9.14.2 为什么不在 webhook 里下载（最关键的一条）

那个钩子必须在秒级回 200，否则 Telegram 会把同一个 update **重投**
（`edu_tg_assist.update_log` 去重是兜底，不保证零重投）；一个 10 MB 附件在
马来西亚机房拉完可能要十几秒 —— 那就是「同一条材料归档两次 + 回执迟到」。
所以钩子里**只记元数据**（毫秒级），本体事后取：每分钟的 cron，或后台按钮。

### 9.14.3 数据与参数

| 项 | 值 |
|---|---|
| 参数 `edu_tg_assist.material_download` | `1`（默认）自动取回；`0` 关掉（回到「只记元数据」的旧行为） |
| 参数 `edu_tg_assist.material_max_mb` | 默认 `10`；≤0 或非法值回落 10。Telegram 官方 `getFile` 只允许下载 20 MB 以内的文件 |
| 字段 `file_data` | `fields.Binary(attachment=True)` —— 文件本体，落在本库附件表 |
| 字段 `file_fetched_at` / `file_error` | 取回时间 / 失败原因，后台表单直接可见 |

### 9.14.4 流程

老师转发文件 → `ingest()` 只写 file_id / file_name / file_size（state=new）→ 回执立刻出网 →
cron 60 秒内 `_analyze_one()` 标 analyzed → **同一轮 cron** `_fetch_file()`：
`getFile(file_id)` 拿 `file_path` → `https://api.telegram.org/file/bot<token>/<file_path>`
→ 字节 → base64 → `file_data` → 给老师回一条「📎 文件已存到后台：…（后台「材料归档」里可以下载，
或直接转发给教务。）」。后台表单 header 的「**⬇️ 取回文件**」（`action_fetch_file`）
可人工立刻取、并重试失败项（按钮会先清掉上次的 `file_error`）。

### 9.14.5 降级（每一种不顺利都有确定行为）

| 情形 | 行为 |
|---|---|
| cron 最多每条一分钟内发起 | 一轮 cron 最多取 `ANALYZE_BATCH`=20 条，取不完下一分钟继续 |
| getFile 失败 / 下载非 200 | 写 `file_error`，**cron 不再自动重试**（避免每分钟撞同一面墙），后台按钮可重试 |
| 文件超过上限 | 写「文件 X MB 超过上限 10 MB，未取回（可在 Telegram 里直接看）」，不下载 |
| `material_download=0` | 完全不取回，回到「只记元数据」的旧行为 |
| 老师撤回了文件 | Telegram 的 file_id 失效 → getFile 报错 → `file_error` 留痕（老师重发一次即可） |
| 留下的附件占空间 | `edu_tg_assist.material_keep_days`（默认 365 天，0=永久）按条删除，附件跟着走 |

### 9.14.6 隐私与边界

文件本体只落在**本库**（学校自购的机器），不进 LLM、不进 Notion（B9–B11 不变）；
直链用 token 拼，token 只从 `edu_tg_assist.token` 读、**绝不写日志**（B6）；
学生流没有一个字节改变（B12 不变，钩子里只有教职工才走到 ingest）。

### 9.14.7 证据

- `tests/unit/tg_assist_file_test.py` —— **36/36 通过**：逐字断言「钩子里不下载本体」
  （`_tg_assist_note_private_message` 方法体里没有 `requests.` / `_fetch_file`）、
  上限两道拦、失败写 `file_error` 而不抛、cron 跳过报过错的不重撞、视图有按钮与 `file_data`。
- 本地探针（edu19-clone，token 是假的 ⇒ 只验得动错误路径）：`_max_bytes()`=**10485760**；
  坏 file_id → `getFile 失败：HTTP 404: Not Found`；50 MB 记录 →
  「文件 50.0 MB 超过上限 10 MB，未取回（可在 Telegram 里直接看）。」；取回域 0 条；
  `env.cr.rollback()` 后 material=0。
- **生产真机端到端（2026-10-13，odoo shell，真 token）**：用 `sendDocument` 把教程图
  当附件发给王佐（5592841801）→ 拿到**真 file_id**（70 字符）、`file_size`=**268236** →
  按它建一条 material（state=new）→ `_cron_analyze()` 返回 **2**（分析 + 取回各一次）→
  `state=analyzed`、`file_data` 已写入、`file_fetched_at` 有值、`file_error` 为空 →
  解 base64 得 **268236 字节**、头部 `PNG` 魔数、与 Telegram 报的 `file_size` **逐字节相等**；
  另造坏 file_id → `getFile 失败：HTTP 400: Bad Request: invalid file_id`（不抛异常）；
  取回域剩 0 条；`deleteMessage` 把那条自检附件从对话里删掉（**DELETED=True**）；
  `env.cr.rollback()` 后 material=0（**零残留**）。
- 部署：`bash scripts/deploy_myedu.sh edu_tg_assist` ⇒ **DEPLOY_RC=0**（web StartedAt 晚于升级完成、
  就绪 302、公开页 200/302、113/113 模型 LIVE、0 DARK）。文档与单测门禁全绿
  （check_docs_index / check_md_tables / check_english / check_odoo_trace / check_manifest_tracking /
  check_view_xpath / check_alias_not_extended / tests/smoke/init_cross_table_check 全部 exit 0）。

---

## 9.15 网站侧权限、教务账号与「和网站对接」（2026-10-13）

### 9.15.1 起因

用户原话：「这五个群的短名可以鼓励sarah老师自己去改，对了，还有就是，能不能把机器人的功能和教务网站对接上。sarah老师可以给她开一个行政级别的账号。」
⇒ 拆成三件事：① 群短名让教务**自助**改 ② 机器人与教务网站**对接** ③ 给教务开一个**行政级账号**。

### 9.15.2 「对接」的真相：它本来就是网站的一部分

`edu_tg_assist` 不是外挂程序 —— 它和教务网站跑在**同一个 Odoo、同一个库（edu19）、同一个后台**里：

- 群与短名 / 人员映射 / 文案模板 / 定时提醒 / 打卡统计 / 材料归档都是网站后台的表；材料归档的文件本体存为 Odoo 附件（`file_data`，`attachment=True`），后台点「⬇️ 取回文件」即可下载或转发。
- 所以「数据层对接」已经存在；真正缺的是**双向事件流**：网站里发生的业务事件不会自动进 Telegram，Telegram 收到的东西目前只在「材料归档」里等人来翻。
- 本节只解决**权限与账号**（9.15.3–9.15.5）；事件流见 9.15.6 的四个待拍选项。

### 9.15.3 新增权限组「班务机器人管理员」

- 新增 `custom_addons/edu_tg_assist/security/assist_security.xml`：`group_assist_manager`，名「班务机器人管理员」，**不隐含 `base.group_system`**，无 category（可直接在用户表单勾选）。
- `security/ir.model.access.csv` 追加 14 行：配置类 **1,1,1,1**（`chat` / `person` / `template` / `reminder` / `material` / `bindcode` / `poll` / `poll.reply` / `mention` / `selfcheck`）、审计类 **1,0,0,0**（`send_log` / `update_log` / `dm` / `reply`：**能看、不能改**）。
- 根菜单（`views/assist_views.xml` 的 `menu_assist_root`）`groups` 由「仅 `base.group_system`」改为 `edu_tg_assist.group_assist_manager,base.group_system`；子菜单挂在根下，根不可见即整棵不出现。
- 为什么不让教务直接拿 `base.group_system`：系统管理员能看全部表与全部系统参数（含 token 参数与匿名意见箱相关参数），**办事不需要这个权限**。
- 加一条边界：菜单被收口了，但 CSV 里**原本就有** 5 条 `base.group_user` 只读行（`chat` / `mention` / `reply` / `template` / `reminder`）；也就是说任何内部用户在知道路径时仍可只读这 5 张表。这是**既有事实、非本次引入**，本次只把它从菜单里收口，不改老行（改老行会动到学生/教师既有权口径，需单独裁定）。

### 9.15.4 给教务开账号

- 组：`edu_portal.group_backend_full`（后台·完整视图）+ `openeducat_core.group_op_back_office_admin`（经理）+ `edu_tg_assist.group_assist_manager`（本次新增），与生产两个教务模板账号（`backoffice@local` 教务专员 / `jiaowu@local` 教务二号）同款再加管理组。
- ⚠ 生产 `ir.mail_server` 数量 = **0** ⇒ 站点发不出「密码重置邮件」，初始密码只能**人工交付**。
- 交付口径：密码在服务器容器内生成、经 ORM 写入，**不写日志 / 不进文档 / 不进聊天记录**；用 Telegram 直接私发本人（`api.call('sendMessage')`，刻意**不**走 `api.send_message` —— 后者会把正文写进 `edu.tg.assist.send_log`），并提醒首次登录后自行改密。登录入口 `https://edu.example.org/web/login`（库 `edu19`）。
- 附带：**管理员 Telegram 号只认 `role=admin` 的人**，所以给教务开账号与「让她的 Telegram 能广播」是两件事；后者靠后台「人员映射」里把她的角色标成 行政（`Sarah` 已是 admin）。

### 9.15.5 群短名自助

- 已有实现，**无需新代码**：群内发 `/alias 学习群` 给当前群起短名（`models/notify.py:127-161` `_cmd_alias`），仅 `role=admin` 可用，越权写 `edu.tg.assist.dm` `state=denied` 留痕；**已有短名绝不覆盖**；空参数回显现有短名。
- 2026-10-13 生产 10 个群中有短名的 5 个：`AB` / `品茶` / `学习` / `清洁` / `班长`；待命名 5 个：BZR交流群 / 弟兄组 / 姐妹组 / 东南西北 联姻群 / 王佐 & Sarah。
- 约束：改短名的人必须是后台里 `role=admin` 的那个 Telegram 账号本人（`_sender_person()` 只读查 person），所以「让 Sarah 自己改」= 她在那 5 个群里各发一句即可，不需要后台权限。

### 9.15.6 「和网站对接」的四个可选项（待拍）

| 选项 | 做什么 | 现状与代价 |
|---|---|---|
| a 网站公告 → 群 | `edu.notice` 发布时顺带推 Telegram | 现成通道是诺亚的（`edu_portal` 的 `channel_telegram` → `op.telegram.chat` → `edu_telegram.outbox`），而 **`op.telegram.chat` 在生产不存在（KeyError）**、5 条公告里 0 条开该通道、`scripts/telegram_relay.py` 在跑却没东西发 ⇒ 要么补一张群表，要么改走 assist（**会碰 B2 边界，需先裁定**） |
| b 业务事件 → 私聊 | 申请 / 请假 / 打卡等网站事件私聊提醒负责人 | 要新增事件钩子；assist 侧已有出网口，不改学生流 |
| c 后台一键转材料 | 材料归档里把某份直接转给某人 / 某群 | **成本最低**：`api` 出网口 + 人员/群映射都已就绪；本轮只把前提（教务账号 + 能下载文件）做完 |
| d 网页版（Mini App） | 在 Telegram 里直接打开网站界面 | **成本最高**：需要 `initData` 鉴权 + 前端工程 |

本节不替用户拍板，四个选项留待裁定（设计原则：能复用既有出网口，不新开机器人、不碰学生流）。

### 9.15.7 证据

- 静态门禁 `tests/unit/tg_assist_security_test.py` —— **26/26 通过**：组定义与「不隐含 system」、manifest 里 XML 在 CSV 之前、`models/*.py` 扫描出的每张具体表（14 张）都有管理组 ACL、配置类=1,1,1,1、审计类=1,0,0,0、既有 `base.group_system` 行 >=9 条仍在、CSV 无 `#` 注释行、根菜单 `groups` 正确。
- 本地库实测（edu19-clone）：组 `edu_tg_assist.group_assist_manager` = id 90「班务机器人管理员」；菜单 id 799 班务机器人 `active=True`、`group_ids=[班务机器人管理员, 角色 / 管理员]`，13 个子菜单全 `active`；管理组 ACL 14 条覆盖 14 个具体模型。
- 本地权限功能测试（odoo shell、假用户、`rollback` 结束）：带「后台·完整视图 + 经理 + 班务机器人管理员」的用户可读 chat/person/send_log/material/template，**create `send_log` 被 `AccessError` 拒**（审计只读生效），create `chat` 通过；`menu_assist_root` 在其 `_visible_menu_ids()` 中 = **True**，纯 `base.group_user` 用户 = **False**。
- 本地升级 `docker compose stop web && bash scripts/safe_upgrade.sh edu_tg_assist` ⇒ 无失败特征、就绪 302，加载顺序 `assist_security.xml` → `ir.model.access.csv`。
- ⚠ 排障记录：Odoo 19 的 `res.users` 字段是 **`group_ids`**（不是 `groups_id`），写错会 `ValueError: Invalid field 'groups_id' in 'res.users'`。
- **生产落地（2026-10-13）**：`bash scripts/deploy_myedu.sh edu_tg_assist` ⇒ **DEPLOY_RC=0**（升级完成 06:28:10Z < web StartedAt 06:28:25Z、就绪 302、113/113 模型 LIVE、0 DARK）。
- 生产账号：`res.users` **id 70**（`login=sarah@local`、`name=Sarah`、active），组 = 后台·完整视图 + 开放教育猫 / 经理 + **班务机器人管理员** + 角色/用户；
  实测 `menu_assist_root` 在其 `_visible_menu_ids()` = **True**，可读 chat(10)/material(0)/send_log(29)/bindcode(3)，**create send_log 被 AccessError 拒**，错密码 `_check_credentials` → `AccessDenied`（证明口令已生效）。
- 口令交付：容器内 `secrets.token_urlsafe(12)` 生成、ORM 写入、只用 `api.call('sendMessage')` 私发她本人（message_id **179** 账号与初始密码、**180** 群短名自助说明）；
  **`edu.tg.assist.send_log` 计数 29 → 29 未增**（刻意不用 `api.send_message`，否则正文会把口令带进审计表）。
- 记录：以上读数全部来自 odoo shell，`env.cr.rollback()` 只用于验证脚本；账号与两条私发已 `commit`。

---

## 9.16 后台「一键转发材料」（2026-10-13，用户裁定的选项 c）

### 9.16.1 起因

用户原话（2026-10-13）：「先做 c 后台一键转材料 ⭐ 在后台「材料归档」里点一下，把某份材料直接转给某人或某个群（文件用 Telegram 的 file_id 转，不用重传） 最低，全部在班务模块内，不碰任何边界。」

即：F7 材料归档此前只解决「收进来 + 存在本库」，教务拿到材料后**还要自己想办法送出去**。本节补上这一段：后台点一下就能转。

### 9.16.2 三条判据（每条都有理由）

1. **文件走 Telegram 的 `file_id`，不重传、不落盘**。同一机器人的文件可以直接把 `file_id` 塞进 `sendDocument` 的 `document` 参数：
   既不用先 `getFile` 下载、再 `multipart` 上传（多一次出网 + 撞 20 MB 的 `getFile` 上限），
   也不把学生材料多写一份到磁盘。实现见 `models/api.py` 新增的 `send_document(chat_id, file_id, caption=None, kind='manual')` ——
   形状与 `send_message` 完全一致（dry_run 只记日志不出网、失败只回报不抛异常、**无条件**写 `edu.tg.assist.send_log`）。
2. **目标只能从本模块的登记表里选**，不让人手抄 chat_id、更不猜：群取 `edu.tg.assist.chat.chat_id`，
   人取 `edu.tg.assist.person.chat_id`；没有私聊会话的人（`chat_id` 为空）直接 `UserError` 拒发
   —— Telegram 平台限制，机器人不能主动私聊陌生人，这一点和 F2 `/dm` 同口径。
3. **瞬态模型，不立新表**：`edu.tg.assist.forward`（`models/forward.py`）是 `models.TransientModel`，
   只承载「选目标 + 附言」这两步，发完即弃；一条材料可以被转发多次，不需要历史表（真实结果都在 `send_log` 里）。

### 9.16.3 流程

1. 后台 **班务机器人 → 材料归档** → 点开一条材料 → 表单右上角 **「📤 转发给…」**（`models/material.py` 的 `action_open_forward` 返回 `ir.actions.act_window`，`target='new'`，`context={'default_material_id': self.id}`）；
2. 弹窗里选「发到群里」或「私发给某人」（`target_kind`），再选具体群/人（下拉里只有登记过的目标），可写一句**附言**；
3. 点 **「📤 发送」**（`action_send`）：组装 caption = 附言 + 📎 标题 + 「分类 ｜ 紧急度 ｜ 截止」+ 摘要（上限 `CAPTION_MAX=900`，官方 caption 上限 1024）；
   有 `file_id` → `api.send_document(..., kind='material_forward')`；纯文本材料 → `api.send_message(..., kind='material_forward')`；
4. 成功回绿条通知「已把「X」发给 「Y」。」；失败把原因原样弹给操作的人（话术「没发出去：…（详见「发送记录」）」），**同时那条失败已进 `send_log`**。

### 9.16.4 降级（每种不顺利都有确定行为）

| 情况 | 行为 |
|---|---|
| 没选群/人 | `UserError`，不发 |
| 选的人 `chat_id` 为空（没跟机器人说过话） | `UserError`「这个人还没跟机器人说过话（没有私聊会话），发不出去。」 |
| 材料没有文件（纯文本） | 走 `send_message` 发文本，不报错 |
| `edu_tg_assist.dry_run=1` | 只写 `send_log`（`DRY_RUN（未出网）`），不出网 |
| Telegram 返回失败（含 400 文件失效） | 只弹错误 + 写 `send_log`，**不重试**（重试会把同一条发第二遍 —— 全模块统一口径） |
| caption 超长 | 按 900 截断后再发（超长 Telegram 整条拒收） |

### 9.16.5 边界（B1/B2/B5 不变）

- 只用本模块的 `chat` / `person` / `material` 与 `edu.tg.assist.api` 出网口，**没有**碰 `edu.feedback.*`、`edu_telegram.*`、`edu.tg.claim`（后者是学生领码流；本节的 `file_id` 与之无关）；
- 不新开路由、不新增系统参数、不碰另两条 webhook；
- `tests/unit/tg_assist_forward_test.py` 里有一条**剥掉 docstring 与行内注释**后逐字断言，防止以后有人把禁名写进代码。

### 9.16.6 证据

- 静态用例 `python3 tests/unit/tg_assist_forward_test.py` ⇒ **50/50 通过**（send_document 形状、caption 上限与截断、目标缺失即拒、file_id 走 sendDocument、kind 统一、ACL、视图按钮、边界禁名）。
- 权限：`security/ir.model.access.csv` 给 `edu.tg.assist.forward` 加两行（`base.group_system` 与 `edu_tg_assist.group_assist_manager` 都是 1,1,1,1）—— `tg_assist_security_test.py` 会扫描 `models/*.py` 并要求每张表都有管理组 ACL，瞬态模型也不例外。
- 本地升级（先停 web 的 §10.3 铁律）：`docker compose stop web && bash scripts/safe_upgrade.sh edu_tg_assist` ⇒ **SAFE_RC=0**，加载 `views/assist_material_views.xml`，就绪 302，日志里 `Unexpected indentation` **0 条**。
- 本地端到端探针（odoo shell，`dry_run=1`，结尾 `env.cr.rollback()`）：视图 `env.ref('edu_tg_assist.view_assist_forward_form')` 存在、`edu.tg.assist.forward` 的 ACL **2 行**；
  `action_open_forward` → `res_model=edu.tg.assist.forward`、`default_material_id=10`；群发（有 `file_id`）→ `send_log` 记 `kind=material_forward`、`ok=True`，正文 = 附言 + 📎标题 + 分类/紧急度；私发（纯文本）→ `sendMessage`；
  三种缺目标（人没 chat_id / 没选群 / 没选人）全部 `UserError`；`LOG_DELTA=2`（两次转发各一条）。
- 方法级自证（monkeypatch `api.call` 拦住出网）：有 `file_id` ⇒ `sendDocument`、`document=PROBE-FILE-ID`；无文件 ⇒ `sendMessage`（键 = `chat_id / disable_web_page_preview / text`）。
- **生产部署（2026-10-13）**：`bash scripts/deploy_myedu.sh edu_tg_assist` ⇒ **DEPLOY_RC=0**（升级无失败特征 → web 已重启并就绪 → 匿名冒烟 200/303 → 活体注册表门禁 **114/114 模型 LIVE、0 DARK**）。
- 生产端到端探针（同法：monkeypatch `api.call` 拦住出网、结尾 `rollback`）：`VIEW_FWD=True`、`ACL_FWD=2`、`MODEL_IN_DB=1`；`FILE_CALL=sendDocument document=PROBE-FILE-ID`；`TEXT_CALL=sendMessage chat=7779990001`；没私聊会话的人 → `UserError`；`LOG_DELTA=2`。
- 事后清理核对（生产）：`send_log=29`（未增）、`material=0`、`chat=10`、`person=2`；6 个文件本地/生产 md5 逐字一致：`forward.py 6121d67f706065c7256e43467a5adbbb`、`api.py 73fe331e736baf0ba94bb27789d7afdc`、`material.py 6aeee8251c3166fb3cd771ce6fe7b9ba`、`__init__.py 48177ffe91e51e1ae0c9d5ecf4ff09bf`、`assist_material_views.xml 33758485ffb07260f3712b1daaeb741f`、`ir.model.access.csv 44453af4d38c44d346d9cd69ef6bd280`。
- 同轮完成的另一件事（用户同一条指令的后半句）：用机器人**私聊提醒 Sarah 改初始密码** —— `api.call('sendMessage')` 直接发（**刻意不用** `api.send_message`，免得正文进审计表），`ok=True`、`message_id=181`、`send_log` 29 → 29 未增。

## 9.17 Telegram Mini App 面板（2026-10-13，用户问「d 能做吗」）

### 9.17.1 起因与可行性

用户在 9.15.6 的四个「和网站对接」选项里挑了最贵的 d：**Telegram 里的网页版 Mini App**（需要 initData 鉴权 + 前端工程）。
调研结论：**能做**，且不必新建模块、不碰任何边界。

一手依据（官方文档原文，2026-10-13 在生产机上 `curl https://core.telegram.org/bots/webapps` 拿到 154671 字节原文复核）：

- `data_check_string` = 除 `hash` 外所有字段按 key 字母序、以换行连成 `key=value`；
- `secret_key = HMAC_SHA256(<bot_token>, "WebAppData")` —— **"WebAppData" 是 key、token 是消息**（写反了就是「合法用户永远进不来」）；
- `hex(HMAC_SHA256(data_check_string, secret_key)) == hash` ⇒ 数据来自 Telegram；官方另要求自己校验 `auth_date` 时效；
- SDK 脚本 `https://telegram.org/js/telegram-web-app.js`；入口可为 菜单按钮 / 键盘按钮 / 内联按钮 / 直链。

上线前实测的两条环境事实：生产站 `curl -sSI https://edu.example.org/` **没有 CSP 头**（只有 `x-content-type-options: nosniff`）⇒ 页面可以引官方 SDK；
生产上的菜单按钮 `getChatMenuButton = {"type": "commands"}`（现在是命令列表）⇒ **不动它**（改成 web_app 会顶掉命令列表），入口改放**底部常驻键盘**。

### 9.17.2 为什么不新建模块 / 不碰边界

- 两条新路由挂在**既有** `edu_tg_assist` 里，页面与接口都只是它的一个新「出口」，复用它的 `person`（身份）、`chat`（群短名）、`material`（材料）、`forward`（转发）、`api`（出网与 send_log）；
- 不新增系统参数以外的任何基础设施：**只用** `edu_tg_assist.token`（验签密钥）与既有的 `edu_tg_assist.site_url`；
- B1–B8 一条不动：不读写 `edu.feedback.*` / `edu_telegram.*` / `edu.tg.claim`，不占 `/telegram/webhook`、`/telegram/tgb/webhook`、`/telegram/assist/webhook`；
- 单测里有一条**剥掉 docstring 与行内注释**后逐字断言（`tg_assist_miniapp_test.py`），防止以后有人把禁名写进面板代码。

### 9.17.3 验签（面板唯一的门）

`custom_addons/edu_tg_assist/miniapp_auth.py`（纯函数、不 import odoo ⇒ 可离线单测）：

| 常量 | 值 | 理由 |
|---|---|---|
| `DEFAULT_TTL` | 3600 秒 | 官方只说「自己定」；点开面板到操作完 1 小时足够 |
| `FUTURE_SKEW` | 300 秒 | 容忍客户端时钟略快；再多就是伪造 |
| `MAX_BYTES` | 8192 | 实测 initData 几百字节；超限直接拒 |
| `REASONS` | ok/empty/too_long/no_token/no_hash/bad_hash/bad_date/stale/future/no_user | 日志里只出现这些短码，**永不出现 init_data 内容** |

`check(raw, bot_token)` 用 `hmac.compare_digest` 比对；`reason` 只回短码。**token 与 initData 原文绝不写日志、不回显**（与 B6 同口径）。

### 9.17.4 两条路由与三层权限

| 路由 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/edu_tg_assist/app` | GET | 无（页面只是壳） | 出 `miniapp_page` 模板；把 `api_path / site_url / bot_username` 塞进 `data-*` 属性 |
| `/edu_tg_assist/app/api` | POST | **initData 验签** | 入参 `{init_data, action, params}`；返回 `{ok, data}` 或 `{ok:false, error, message}` |

页面本身**不含任何数据**：所有数据都要走 API，API 第一件事就是验签 ⇒ 把网址发给别人也看不到任何东西。

权限分三层（与斜杠命令同口径，不另立一套）：

| 层 | 动作 | 判据 | 越权行为 |
|---|---|---|---|
| 任何人（已登记） | whoami / help / groups | 有 `edu.tg.assist.person` 且 active | —— |
| 教职工（admin/teacher/dorm_head） | materials（材料归档）/ forward（转发） | `role in STAFF_ROLES` | 403 + 写 `denied` 审计 |
| 行政（admin） | notify（群发）/ dm（私发）/ staff（人员名单） | `role == 'admin'` | 同上 |

**材料归档从原来的「登记用户可读」收窄到「教职工可读」**：学生若误发 `/assist` 会被登记成 `role=other`，收窄后他即使混进面板也读不到别人的材料。

### 9.17.5 入口：底部键盘最后一行

`menutext.reply_keyboard(role, site_url)` 的最后一行固定追加一个 `web_app` 按钮「🖥 打开面板」：

- 所有调用点（menu.py 12 处、bot.py 2 处）**零改动**就都带上了入口；
- Telegram **只在私聊**接受 `web_app` 键盘按钮；本模块的键盘本来就只发给私聊（群消息走 `/notify`），因此不需要群内降级；
- bot 侧把配置的站点地址传进去（`app_url(self._site_url())`），不硬编码域名。

### 9.17.6 已知形态与取舍（写给接手的人）

1. `check_ui_surface.py` **只看得见字面量路径**（`@http.route('/x')`）：本模块与三条 webhook 一样用**常量式**声明路由，因此新路由**不登记** `tests/ui/surface.json`；登记了反而会被判「登记已失效」。这是已知形态，不是漏登记。
2. 模板 JS 写在 `<![CDATA[…]]>` 里，因此**不能用 JS 模板字符串**（QWeb 会先吃掉 `$` 后的花括号）；单测有一条断言守着。
3. 页面不引任何 Odoo 资产包（自包含 HTML + 官方 SDK 一个脚本）：避免门户布局/资产包把面板撑坏，也避免 `check_ui_surface` 之外的资产门禁牵连。
4. 只做**私聊入口**：群里没有这排按钮，群里的入口仍是「广播消息里自带的内联按钮」。

### 9.17.7 降级（每种不顺利都有确定行为）

| 情况 | 行为 |
|---|---|
| 没从 Telegram 打开（浏览器直开） | `tg.initData` 为空 ⇒ 页面提示「请回到机器人对话，点底部的「🖥 打开面板」重新进入」 |
| initData 过期/被改/换 token | `check` 失败 ⇒ 403 `unauthorized`，回通用的「身份校验没通过」文案，日志只记原因短码 |
| 没登记过的人 | 403 `not_registered` + 告诉他先私聊发 `/assist` 或 `/name 真名` |
| 未登记的人打开了面板 | 同样 403（`person.active` 为假也算未登记） |
| action 不在白名单 | 400 `bad_action` |
| 越权（教师点群发 / 学生看材料） | 403 `forbidden` + 写 `denied` 审计（后台私发记录可见） |
| 动作内部抛 UserError（比如选的东西已经不在后台） | 200 `{ok:false, error:'user_error', message:原文}`，页面弹横幅 |
| 动作内部抛未知异常 | 记 exception 后回 200「这一步没做成，请重新点一次。」（**绝不把 traceback 甩给用户**） |

### 9.17.8 证据（本地，2026-10-13）

- 新增 3 个文件：`miniapp_auth.py`、`controllers/miniapp.py`、`views/miniapp_templates.xml`；接线：`controllers/__init__.py`、`__manifest__.py`（模板排在 security 之后）、`menutext.py`（web_app 按钮）、`models/bot.py`（站点地址来源）。
- 静态用例 `python3 tests/unit/tg_assist_miniapp_test.py` ⇒ **50/50 通过**（按官方算法**独立实现**签名造真样本：真样本放行、改一个字节就拒、换 token 拒、过期拒、未来拒、缺字段拒；控制器路由/三层权限/审计/异常兜底/边界禁名；模板 SDK 与 CDATA、键盘最后一行、manifest 顺序）。同轮 `tg_assist_menu_test.py` 因键盘多一行同步改到 **98/98**。
- 本地升级（§10.3 先停 web）：`docker compose stop web && bash scripts/safe_upgrade.sh edu_tg_assist` ⇒ **SAFE_RC=0**，就绪 302。
- 本地端到端（真 HTTP 打 127.0.0.1:8069，容器内用**本地 token** 现算 initData，探针人 `900002` 用完即删）：
  `GET /edu_tg_assist/app` → 200 且含官方 SDK；空 initData → 403 `unauthorized`；坏 hash → 403；换 token → 403；没登记的人 → 403 `not_registered`；
  `whoami` → 200 带 name/role_label/is_admin；`groups` → 200（本地 1 个群）；`materials` 以 `other` 身份 → **403 forbidden**，把该人改成 `teacher` 后 → 200（**这就是「材料不外泄」的实测证据**）；
  `notify` 以 teacher 身份 → 403；`nope` → 400 `bad_action`；`staff` 以 admin 身份 → 200；`forward` 选一个不存在的材料 → 200 `user_error`「选的东西已经不在后台了」。
  探针事后清理：`person(900002)=0`、`dm(raw like '面板:%')=0`。

---

## 9.18 站内通知桥：网站的通知自动转到 Telegram（2026-10-14，用户裁定的选项 b）

### 9.18.1 起因与选项

用户 2026-10-13 问「能不能把机器人的功能和教务网站对接上」（m03043），我给出四个选项
（a 网站公告→群 / b 网站业务事件→私聊 / c 后台一键转材料 / d Mini App）。c 与 d 已分别见 §9.16、§9.17；
用户 2026-10-14 说「继续干吧」（m03486）⇒ 本轮做 **b**。a 仍待拍（它要碰诺亚的 B2 边界：生产
`op.telegram.chat` 模型根本不存在，公告的 Telegram 通道 0 条在用，见 §9.15）。

### 9.18.2 为什么是「读水位轮询」而不是「挂钩子」

- 网站的统一通知引擎是门户的 **`edu.message`**：`edu_portal/models/message.py:16` 定义
  `sender_id` / `recipient_id`(→`res.users`，required, index) / `body`(Text, required) / `sent_at` /
  `is_read` / `thread_key`；`edu_portal/models/notify_pref.py:53-91` 用 `_inherit` 加了 `event_key` 并定义
  **`_notify_event(self, event_key, recipient_user, body, sender_uid=None)`**（先查 `edu.notify.pref`，
  静音就 `return False`；否则 `sudo().create(body[:2000])`，失败只 warning、不回滚）。
- 它已被这些地方调用：`edu_portal`（notice / leave / leave_flow / grievance / registration /
  exam_session_ext / assignment / fees / course_rep）、`edu_life/controllers/life.py:455`、
  `edu_schedule/models/session_ext.py:301/689/697`。后两处**先 `hasattr(Msg, '_notify_event')` 再调**，
  是仓里既有的「按需探存」范式。
- 生产 `edu_message` 共 7 行，`event_key` 分布：`approval_escalate` 3 / `reimburse_result` 2 /
  `leave_result` 1 / 空字符串 1（课前提醒）；id 12–18，最后一条 2026-10-07 23:55。
- **不挂钩子**：在 `edu.message` 上 `_inherit`（哪怕只是加个钩子）必须 `depends = ['edu_portal']`，
  这会作废本模块「零依赖、可单独装卸」的前提（§1），且门户那条线的任何改动都要牵连重新验证。
- **改用 id 水位轮询**：每条规则记 `last_message_id`，只取 `id > last_message_id` 的新行
  ⇒ 天然幂等（`unique(rule_id, message_id)` 再兜一层）、不改对方一行代码、对方模块不在时自动静默。

### 9.18.3 数据模型（两张表，本模块自己的）

- `edu.tg.assist.bridge`：`name` / `event_key`（留空=全部）/ `target`(recipient｜person｜group｜owner) /
  `person_id` / `chat_id`(→`edu.tg.assist.chat`) / `prefix` / `include_body` / `last_message_id` /
  `sent_count` / `skip_count` / `active`；`unique(name)`。
- `edu.tg.assist.bridge_log`：`rule_id`(cascade) / `message_id` / `event_key` / `target_chat_id` /
  `ok` / `error` / `excerpt` / `sent_at`；`unique(rule_id, message_id)`（同一条站内信对同一条规则只转一次）。
- `edu.tg.assist.person` 新增 `user_id`(→`res.users`，`ondelete='set null'`)：把「网站账号」接到 Telegram 的人身上，
  `target='recipient'` 靠它找收件人；**查不到就跳过并记 skip，绝不猜人**。

### 9.18.4 边界（新增 B9 / B10）

- **B9**：桥的源表只能读，且**永不读** `edu.feedback` / `edu_telegram` / `edu.tg.claim` /
  `edu.tg.bot` / `edu.invite`（`DENY_MODELS` + `_check_source_allowed()`，`_cron_bridge()` 里
  fail-closed：命中就一条都不发并记 error 日志）。写源表的字段更是一个都没有。
- **B10**：桥只发**文字**（`api.send_message(..., kind='bridge')`），不下载任何东西、不转发附件、
  不写 `edu.message`、不改 `is_read`；出网照旧无条件进 `edu.tg.assist.send_log`。

### 9.18.5 时效与降级

| 情况 | 行为 |
|---|---|
| 网站模块没装 / 表还没建 | `_source_ready()` 两次探测（模型在不在 + 能不能 select）都为假 ⇒ 本轮空转，规则与菜单照旧可用 |
| 新规则 / 规则重新启用 | `create()`/`write()` 把水位推成**当前最大 id** ⇒ 不回放历史（想重看历史就把 id 改小） |
| 收件人没接网站账号 | 该条跳过并写桥接记录（`ok=false` + 原因），不算失败、不影响其他规则 |
| 出网失败（Telegram 4xx/5xx/断网） | `send_log` 记失败原因、桥接记录也记；水位**照常前进**（不重试同一条，避免坏消息卡住整条线） |
| 单条规则内部异常 | 只 warning，其他规则继续（`_cron_bridge` 逐条 try/except） |
| 没有规则 | cron 每 2 分钟空转一条 SELECT（想彻底停：停用 cron 或把规则停用） |

### 9.18.6 证据（本轮）

- 新增 `models/bridge.py`、`views/assist_bridge_views.xml`、`data/ir_cron_data.xml` 里的
  `cron_bridge_edu_message`（每 2 分钟，默认开）；改 `models/__init__.py`、`models/person.py`（`user_id`）、
  `views/assist_views.xml`、`security/ir.model.access.csv`（`bridge` 1,1,1,1 / `bridge_log` 1,0,0,0）、`__manifest__.py`。
- 静态用例：`python3 tests/unit/tg_assist_bridge_test.py`（读数见 §9.18.7）。

### 9.18.7 上线与复验（2026-10-14）

**本地**（容器 `edu19-clone-web-1`，`dry_run=1`）：`docker compose stop web && bash scripts/safe_upgrade.sh edu_tg_assist` ⇒ **SAFE_RC=0**（117 模块装载、就绪 302）。
odoo shell 探针（造人 `900777` + 规则 + 一条真 `edu.message`，结尾 `env.cr.rollback()`）：
`WATERMARK_INIT=2806`（建规则时把水位推到现在）→ `RUN1 total=1 sent=1 skip=0 logs=1 ok=True error=DRY_RUN excerpt=桥探针正文 A`，
`send_log` 多一行 `kind=bridge`；再跑一次 `RUN2 total=0 logs=1`（**不重复**）；
把收件人换成没接网站账号的人 ⇒ `skip=1 logs=1 ok=False error=收件人（DSH测试）还没把网站账号接到人员映射上`（**跳过并留痕，没猜人**）；
`DENY_CHECK feedback=edu.feedback telegram=edu.telegram claim=edu.tg.claim invite=edu.invite msg=（空=允许）`、`SOURCE_READY=True`。

**生产**（2026-10-14）：`bash scripts/deploy_myedu.sh edu_tg_assist` ⇒ **DEPLOY_RC=0**（117/117 模型 LIVE、0 DARK，含两个新表）。
odoo shell 探针（同样 rollback 收尾）：`CRON n=1 active=True model=edu.tg.assist.bridge`、两个菜单挂在「班务机器人」下、`MODELS in_db=2`、`dry_run=0`；
`WATERMARK_INIT=18` → `RUN1 total=0 sent=0 skip=1 logs=1 ok=False error=HTTP 400: Bad Request: chat not found`
（故意用假 `chat_id 999000002` 真打 Telegram：**管道验通且没打扰任何人**）、`send_log` 一行 `kind=bridge`；`RUN2 total=0 logs=1`（不重复）；
`SKIP_CASE skip=1 ok=False error=收件人（Sarah）还没把网站账号接到人员映射上`；`SRC_MAX=20`。
**生产预置了两条停用的示范规则**（id 3 `leave_result`→owner、id 4 `approval_escalate`→owner，`active=f`、水位 18）：
想用就点开「启用」，不想用就这样放着（停用 = 一条都不会转）。
**回归**：桥只新增两条只读路径，三条既有路由与两个 bot 的 webhook 一字未动 ⇒ 学生领码流与意见箱不受影响（本轮未再动 `edu_tg_gate` / `edu_tg_bind`）。

## 9.19 网站公告 → Telegram 群（对接选项 a，2026-10-14，用户授权「碰诺亚的线」）

### 9.19.1 起因与授权

用户 m03621：「没关系，那就碰诺亚的线，我允许了」——在此之前我把「a 网站公告 → 群」标为「需要拍板」，
因为门户那条线接的是诺亚（`edu_telegram`）的表与参数。这次授权后先做生产实读，再定接线方式。

### 9.19.2 生产实读：诺亚那条线在生产上本来就是断的

- `ir_model` 里 telegram 相关**只有 `edu.telegram.outbox`**（"Telegram 发件队列"）；**没有 `op.telegram.chat`**。
  数据库里 `public.op_telegram_chat` 表还在（`to_regclass` 非空）——那是旧版本卸载后留下的孤儿表，
  注册表里没有模型 ⇒ `env['op.telegram.chat']` 抛 KeyError。
- 生产 `/opt/edu-app/custom_addons/edu_telegram/models/` 只有 `__init__.py` / `feedback.py` / `outbox.py`
  ——生产跑的是**「意见箱版」**，与本仓那份（含 `telegram_chat.py` / `notice.py` / `flow.py`）不是同一套代码。
- `edu_notice` 共 5 条、`channel_telegram=True` 的 **0 条**；`edu_telegram_outbox` 2 行；
  参数 `edu_telegram.{bot_token(46), webhook_secret(32), dry_run(1), admin_key(10), last_notice_id(1)}`。

⇒ 结论：门户「公告 → Telegram」这条线在生产上**从未真正工作过**（KeyError 被 notice.py 的 try/except 吞掉，只留一条 warning）。
处置：**不再依赖那个不存在的模型**，把这条线接到班务助手；**不复活**退役的 v2.2
（复活 = 装一套与生产意见箱**同名路由、同名参数**的模块 ⇒ 抢路由，正是 §2 早已裁定的红线）。

### 9.19.3 为什么公告不能用「id 水位轮询」（与 §9.18 的 b 的差别）

`edu.notice` 用 `active=False` 当「未发布」载体（notice.py:86-106 的注释）：草稿先建（id 小、`active=False`），
到 `publish_at` 才翻成 `active=True`。水位轮询只能按 id 追：草稿建出来时不算「已发布」、不处理；
等它到点发布时 id 已经落在水位之下 ⇒ **永远漏发**。
⇒ 公告改由门户在**发布那一刻主动调用**：`_cron_publish_scheduled()`（定时）与门户「立即发布」（`controllers/roles.py:1574`）
两条路都走 `_send_channels()`，天然覆盖，也不需要新 cron。

### 9.19.4 接线（门户侧只探在不在，不写依赖）

- 门户 `custom_addons/edu_portal/models/notice.py::_send_channels()` 的 `if self.channel_telegram:` 分支：
  先 `'edu.tg.assist.bridge' in self.env`；在 ⇒ `bridge.push_site_notice(self)`、`handled=True`；
  不在（或抛异常）⇒ 回退旧路 `op.telegram.chat → edu.telegram.outbox`（保留给还装着旧版教学 telegram 的部署），
  异常一律吞掉 + warning，绝不因为一个通道拖垮公告发布。
- 班务助手 `custom_addons/edu_tg_assist/models/bridge.py` 新增：
  `NOTICE_KIND='notice'`、`NOTICE_MAX=3500`、
  `notice_targets()`（`active=True` + `notice_enabled=True` + `chat_id != False`）、
  `push_site_notice(notice)`（`getattr` 读 name/content，拼 `【公告】标题\n正文`，
  逐群 `api.send_message(chat_id, text, kind='notice')`，返回 `(sent, failed)`，单群异常只 warning + continue，**不抛**）。
- `edu.tg.assist.chat` 新增 `notice_enabled`（Boolean「接收网站公告」，默认 False、有索引）；
  「群与短名」列表与表单各加一个勾选框；`edu.notice.channel_telegram` 的 help 改指向它。
- 门户**没有** depends / import 本模块（探在不在靠 `in self.env`，与 §9.18 的 b 同一手法）；本模块 `depends` 仍只有 `base`。

### 9.19.5 边界

B1–B10 全部不变：公告这条路径的代码里 `edu_telegram` / `edu.feedback` / `edu.tg.claim` / `edu.invite` **0 命中**（单测断言）。
旧路（读 `op.telegram.chat`、写 `edu.telegram.outbox`）留在**门户**里，是门户自己的历史代码，班务助手一行都没碰。
反向也成立：把 `edu_tg_assist` 卸掉，门户照旧发布公告（Telegram 通道回到「什么都不发」的旧状态），发布流程不会报错。

### 9.19.6 证据（本轮）

**本地**（`edu19-clone-web-1`，`dry_run=1`）：`docker compose stop web && bash scripts/safe_upgrade.sh edu_tg_assist,edu_portal`
⇒ **SAFE_RC=0**（117 模块装载、就绪 302）。
odoo shell 探针（造两个群：`999000001` 勾「接收网站公告」/ `999000002` 不勾；造一条 `channel_telegram=True, audience='staff'` 的公告；结尾 `env.cr.rollback()`）：
`FIELD_OK True`、`NOTICE_LOGS 1`、`LOG 999000001 True DRY_RUN（未出网）【公告】探针公告|这是公告通道探针正文。`、
`C1_HIT 1`、`C2_HIT 0`、`OUTBOX_DELTA 0`（诺亚 outbox 一行没多）、`ASSIST_READY True`、`ROLLBACK_OK`。
单测 `python3 tests/unit/tg_assist_notice_test.py` ⇒ **31/31**。

**生产**（`prod-host`，库 edu19，`dry_run=0`，2026-10-14 00:54–00:56 CST）：
- 部署方式（**刻意不用 `deploy_myedu.sh edu_portal`**）：脚本第 1 步的 rsync 列表是**整目录**，会把并行「排课/成绩中心」工作流在 `custom_addons/edu_portal/` 与 `custom_addons/edu_schedule/` 里**未提交**的改动（`controllers/enroll.py`、`views/roles.xml`、`views/enroll.xml`、`__manifest__.py`、`controllers/__init__.py`、新文件 `controllers/availability.py`、`views/availability.xml`、`controllers/coverage.py`、`models/faculty_ext.py`、`views/coverage.xml`）一起推上生产、并在重启 web 后**直接生效**。
  ⇒ 改为**定点部署**：`rsync -az edu_tg_assist/` 整目录 + `rsync edu_portal/models/notice.py` 单文件（先核过生产 notice.py 的 md5 `b221d3509c1b2d36d5261228895c0a71` = 本仓 `git show HEAD:custom_addons/edu_portal/models/notice.py` 的 md5，说明该文件上只有本次改动），再 `chmod -R a+rX`。
- 定点升级：`docker compose run --rm --name deploy-upg web odoo -c /etc/odoo/odoo.conf -d edu19 -u edu_tg_assist,edu_portal --db_host=db -r odoo -w odoo --stop-after-init --http-port=8099` ⇒ **RC=0**、`TRACEBACK=0`、`CRITICAL=0`；`Module edu_tg_assist loaded in 1.02s`、`Module edu_portal loaded in 4.61s`、`Registry loaded in 12.791s`。
- 四个改动文件本地/生产 md5 逐字一致：`edu_tg_assist/models/bridge.py` `41d2f6844eac291fa512ed78f7a49d01`、`models/chat.py` `c5ab1659956b2068aa90713847c0ea64`、`views/assist_views.xml` `f4773790ed32fee88716970ff874c2e4`、`edu_portal/models/notice.py` `a2b3a3a4ce763d75bb057d0efb1ba699`。
- 重启自证：升级完成 `2026-10-13T16:54:18Z` < web `StartedAt 2026-10-13T16:54:37Z`；就绪 6 秒 `/web/login → 302`；公开页 `/ 200`、`/programs 200`、`/apply 200`、`/contactus 200`；活体注册表门禁 **117/117 模型 LIVE、0 DARK**。
- 生产端到端探针（odoo shell，造群 `999000001` 勾 / `999000002` 不勾 + 一条 `channel_telegram=True, audience='staff'` 公告，结尾 `env.cr.rollback()`）：
  `FIELD_OK True`、`NOTICE_LOGS 1`、`LOG 999000001 False HTTP 400: Bad Request: chat not found 【公告】探针公告对接A|这是公告通道探针正文。`（假 chat_id ⇒ 真出网、真被 Telegram 拒、除收件人不存在外无副作用）、`C1_HIT 1`、`C2_HIT 0`、`OUTBOX_DELTA 0`（诺亚 outbox 一行没多）、`TARGETS ['999000001']`、`DRY_RUN 0`、`ROLLBACK_OK`；服务端日志：`bridge: notice push failed chat=23 error=HTTP 400: Bad Request: chat not found`、`bridge: notice push id=17 sent=0 failed=1`、`edu_portal.models.notice: notice telegram via tg-assist id=17 sent=0 failed=1`。
- 上线开关：生产上把已有三个群勾上「接收网站公告」并已 psql 复核持久化 —— `13|学习|-1002369779089|t`、`14|班长|-1001745532452|t`、`18|清洁|-1003050833944|t`。其余群默认不勾（不会收到公告）。



## 9.20 面板「no initData」修复：SDK 自托管 + 三层兜底（2026-10-14 用户反馈）

### 9.20.1 现象

用户在 Telegram 里点「🖥 打开面板」，窗口白底，页头下面只有一条红字：**`no initData`**。

### 9.20.2 根因（两条叠加）

1. `custom_addons/edu_tg_assist/views/miniapp_templates.xml` 原第 12 行是
   `<script src="https://telegram.org/js/telegram-web-app.js?64"></script>` —— **直连 telegram.org**。
   该域名在用户网络里打不开时脚本静默失败，`window.Telegram` 根本没被定义。
2. 同文件 `call()` 在 `!tg || !tg.initData` 时先弹一句友好提示，紧接着 `Promise.reject(new Error('no initData'))`，
   被 `handleError` 用 `banner(err.message,'bad')` **盖成裸 `no initData`**
   ⇒ 界面上分不清「SDK 没加载」与「客户端没注入身份数据」，也就无法排障。

### 9.20.3 修法

- **SDK 自托管**：官方脚本取回后落在 `custom_addons/edu_tg_assist/static/vendor/telegram-web-app.js`
  （119731 字节，sha256 `124bdff7ba3fe86c8ba5143467afec21e020405e74abdb92cfdda6c0ee3b5908`，
  md5 `ca4a8297c04185dcabadf889be3e89f9`）；模板改引
  `/edu_tg_assist/static/vendor/telegram-web-app.js?v=19.0.1`，仓里再无 `telegram.org` 外链。
- **initData 三层来源**：`tg.initData` → `location.hash` 里的 `tgWebAppData`（`hashInitData()` + `currentInitData()`，带缓存）
  → `showNoIdentity()`（红 banner 中文指引 + info banner 诊断串 + 「重试」按钮）。
- `handleError(err)` 认 `err.code === 'no_identity'` 走 `showNoIdentity()`，友好提示不再被裸错误覆盖。
- `waitSdk()`：等 `window.Telegram.WebApp` 最多 2 秒（每 100ms 一次）再 `boot()`（boot 里先 ready + expand 再进业务）。
- 诊断串 `platformInfo()`：`tg=yes/no platform=… version=… initData=<长度> hash=<长度>`（只给长度，不给身份数据本身）。

### 9.20.4 证据

**本地**（`edu19-clone-web-1`，`dry_run=1`）：`docker compose stop web && bash scripts/safe_upgrade.sh edu_tg_assist` ⇒ **SAFE_RC=0**、就绪 302。
`curl http://127.0.0.1:8069/edu_tg_assist/static/vendor/telegram-web-app.js` ⇒ **200 / 119731 字节 / text/javascript**。
headless Chrome `--headless=new --virtual-time-budget=6000 --dump-dom http://127.0.0.1:8069/edu_tg_assist/app`
（真·没有 initData 的场景）⇒ DOM 命中「这个面板要在 Telegram 里打开」「要发给管理员的信息」「重试」，
诊断行 `tg=yes platform=unknown version=6.0 initData=0 hash=0` —— **SDK 已加载、身份确为空**，正是期望行为。
`python3 tests/unit/tg_assist_miniapp_test.py` ⇒ **54/54**。

**生产**（`prod-host`，库 edu19，2026-10-14 01:00–01:02 CST，定点部署，绝不整目录推 `edu_portal`/`edu_schedule`）：
- `rsync -az --exclude='__pycache__' -e ssh edu_tg_assist prod-host:/opt/edu-app/custom_addons/` + `chmod -R a+rX`；
  本地/生产 md5 逐字一致：`views/miniapp_templates.xml e94ff4fb61ee7c7fe62f8d0d35347d0c`、
  `static/vendor/telegram-web-app.js ca4a8297c04185dcabadf889be3e89f9`。
- `docker compose run --rm --name deploy-upg web odoo … -u edu_tg_assist --stop-after-init --http-port=8099` ⇒ **RC=0**、Traceback=0、CRITICAL=0；`DONE=2026-10-13T17:01:31Z`。
- `docker compose restart web` ⇒ `READY=302 after 6s`、`StartedAt=2026-10-13T17:01:47Z`（晚于升级完成）；
  `python3 scripts/check_live_registry.py` ⇒ **117/117 模型 LIVE、0 DARK**。
- `http://127.0.0.1:8069/edu_tg_assist/static/vendor/telegram-web-app.js` ⇒ **200 / 119731 / text/javascript**；
  公网 `https://edu.example.org/edu_tg_assist/static/vendor/telegram-web-app.js` ⇒ **200 / 119731**；
  `/edu_tg_assist/app` 的脚本标签为 `telegram-web-app.js?v=19.0.1`。

### 9.20.5 边界

SDK 是官方原版静态文件，只落在本模块 `static/` 下（Odoo 自带静态路由），**不新增路由、不碰任何 webhook / 参数 / 边界表**。
原先那条 `telegram.org` 外链是面板唯一的外部依赖，改自托管后反而少一个出网点。

## 9.21 面板里的「定时群发」：F1 第一次有用户点得到的入口（2026-10-14）

### 9.21.1 起因与裁定

- 2026-10-13 用户问「还有定时群发功能呢？」。能力其实早就在：`edu.tg.assist.reminder` 每条规则自带一个 ir.cron，
  后台「班务机器人 → 定时提醒」能建。
- 但 2026-10-14 08:45 生产体检读到 `edu_tg_assist_template` = 0 行、`edu_tg_assist_reminder` = 0 行
  ⇒ 这条旗舰能力（周一学习日 / 周末大扫除）**建好了却一条都没在用**；卡点是「先进 Odoo 后台建模板、再建规则」，
  对不懂后台的人门槛太高。
- 裁定：**不改调度，只加一个面板入口**。管理员在面板里回答三件事（发到哪个群、每逢星期几几点、发什么），其余照旧。

### 9.21.2 设计：一条 quick_create，三步走

- 面板动作（`custom_addons/edu_tg_assist/controllers/miniapp.py`）：`reminders`（列表）、`reminder_create`、
  `reminder_toggle`、`reminder_run`、`reminder_delete`。
- 后端只有一条新逻辑：`edu.tg.assist.reminder.quick_create(chat, body, weekday, hour, minute)`
  （`custom_addons/edu_tg_assist/models/reminder.py`）：
  · 校验：正文非空 / ≤ MAX_TEXT(3500) / weekday ∈ selection（'0'..'6'、'daily'）/ 0≤hour≤23、0≤minute≤59 /
    群已登记 chat_id 且 active —— 每条都 `raise UserError(中文原因)`，面板原样显示；
  · 正文 → 模板：同正文已有模板就**复用**（`Template.search([('body', '=', body)], limit=1)`），
    否则新建 `scene='remind'`、`note='面板「定时群发」自动创建'`；模板名有 UNIQUE(name) 约束，
    撞名由 `_unique_template_name()` 加「 2」「 3」…让开（最多到 50），**绝不覆盖已有模板**；
  · 模板 + 群 + 时刻 → `self.create({... 'tz': 'Asia/Shanghai'})`；`reminder.create()` 钩子自动建/改
    它自己的 ir.cron（interval 1 weeks + nextcall）。
- 面板三步：主菜单「⏰ 定时群发」→（列表）→「＋ 新建定时群发」→ 选群 → 正文 + 星期 + 几点（下拉框）→
  「✅ 建好，以后每周自动发」；列表里点这条进去可以「🚀 立即发一次 / ⏸ 停用 / ▶️ 启用 / 🗑 删掉」
  （删除时 `reminder.unlink()` 连带删它自带的 ir.cron）。
- 「立即发一次」复用后台那颗按钮的同一条路径 `rule._do_send(kind='manual')`：**调度与发送只有一份实现**。

### 9.21.3 权限

- 整族五个动作都进 `ADMIN_ACTIONS`（与 /notify、/dm 同口径）。生产实测：把探针人标成 `teacher` 并 commit 后，
  五个动作**全部 403 `{'ok': False, 'error': 'forbidden'}` + 「你没有这个权限。」**，
  psql 在 `edu_tg_assist_dm` 能看到 5 条 `state=denied`、`raw=面板:reminder_*`。
- 面板列表含**已停用**的规则（`with_context(active_test=False)`）；否则停用的规则会从面板里消失、再也启用不回来。

### 9.21.4 边界

- 不新增模型、不新增路由、不新增参数：只在既有 reminder / template / chat / api 上加一条方法；depends 仍只有 base。
- 不碰 edu.feedback / edu_telegram / edu.tg.claim / edu.invite（新增代码段逐字断言见
  `tests/unit/tg_assist_reminder_panel_test.py`）。

### 9.21.5 本地读数（edu19-clone-web-1，dry_run=1）

- `python3 tests/unit/tg_assist_reminder_panel_test.py` ⇒ **57/57 全绿**。
- `quick_create`：`R1 周六 09:30（Asia/Shanghai）`、cron 已建、nextcall `2026-10-17 01:30`、
  模板名「各位同事请注意：本周六上午大扫除，请各宿（定时）」；同正文第二次调用 `same_tpl=True`、模板增量 1
  （只建过一份）；删规则后它的 ir.cron 也没了（`R2_CRON_GONE True`）。
- 拒绝路径逐字：`正文是空的，没建成定时群发。` / `「星期」没选对。` / `时间是 0-23 点、0-59 分。` /
  `这个群还没登记好（没有 chat_id），发不了。`
- 面板 HTTP 全路径（伪造官方 initData，响应外层 `{ok, data}`）：whoami 200 admin、reminders 0→1→0 行、
  create 200 `周一 08:00（Asia/Shanghai）`、立即发一次在 dry_run 下 `last_result=成功`、
  停用后再立即发一次 ⇒ `没发出去：规则已停用`、toggle 开/关、delete 200、
  错误分支 `user_error` 各就各位（空正文 / 目标不存在 / 星期错 / 点数不是数字）。
- 门禁：全部 tests/unit 15 个文件 rc=0；check_docs_index / check_english / check_odoo_trace /
  check_manifest_tracking / check_view_xpath / check_alias_not_extended / check_qweb_dict_foreach /
  check_ui_surface / tests/smoke/init_cross_table_check 全部 rc=0
  （check_md_tables 仅并行「成绩中心」线的 gradebook 文档报红，不是本条）。

### 9.21.6 生产读数（prod-host，库 edu19，2026-10-14 00:54–00:56 UTC = 08:54–08:56 CST）

- 定点部署（只 rsync `edu_tg_assist`，绝不整目录推 edu_portal / edu_schedule）：三个文件本地/生产 md5 逐字一致 ——
  `models/reminder.py 7cce243fb57b2d971bb51e36322303b2`、
  `controllers/miniapp.py f29e7a62169ada68193476a36ea49f97`、
  `views/miniapp_templates.xml bf50d5a25802e041b0dc7fbba1810d39`。
- 一次性容器 `-u edu_tg_assist --stop-after-init` ⇒ RC=0、Traceback=0、CRITICAL=0，
  升级完成 `2026-10-14T00:54:23Z` < web StartedAt `2026-10-14T00:54:36Z`；重启后 4 秒 /web/login 302；
  `python3 scripts/check_live_registry.py` ⇒ **117/117 模型 LIVE、0 DARK**。
- 面板 HTTP 探针（dry_run=0，真出网，假群 `-999000091`，结尾全清）：whoami 200 admin；reminders 0→1→0 行；
  create 200 `周一 08:00（Asia/Shanghai）`、rule id=4、next `2026-10-19 00:00`；
  **立即发一次真出网** ⇒ 200 `user_error 没发出去：HTTP 400: Bad Request: chat not found`、
  规则 `last_result=失败`（证明请求真打到了 Telegram，只是那个群不存在）；toggle 开/关、delete 200；
  错误分支 `正文是空的…` / `「星期」没选对。` / `「几点」没填对。` / `选的东西已经不在后台了，请刷新页面重来。`
- 越权探针：标成 teacher 并 commit 后五个动作全部 403 `forbidden` + 「你没有这个权限。」，
  psql `edu_tg_assist_dm` 落 5 条 `面板:reminder_*` denied。
- 探针清理后：`send_log=36`、`person=2`、`chat=10`、`reminder=0`、`template=0`、`dm_probe=0`（与探针前一致）。

### 9.21.7 两个坑（写在这里免得下次再踩）

- **odoo shell 是 REPEATABLE READ**：探针里 `env.cr.commit()` 之后仍可能读不到 web 进程刚写进去的行
  （第一次清 `send_log` / `dm` 就因此漏删了 6 行，靠另开 psql 复查才发现并补删）
  ⇒ 复核「清理干净了没有」要**另开 psql**，不要信同一个 shell 事务里的 count。
- **改角色/改数据后必须 commit 才被 web 进程看见**：第一次越权探针在同一个未提交事务里把 role 改成 teacher
  就发 HTTP，结果五个动作全部 200（web 看到的还是 admin）——假绿；补 commit 后才是真 403。
## 9.22 电脑版「no initData」的读数与修法（2026-10-14 用户截图）

### 9.22.1 现象

用户（macOS）点底部键盘的「🖥 打开面板」后，页面显示「这个面板要在 Telegram 里打开…」+ 诊断行
`tg=yes platform=macos version=9.6 initData=0 hash=713`。

### 9.22.2 逐字读数（谁在错）

- `tg=yes` ⇒ SDK 自托管成功、`window.Telegram.WebApp` 在；
- `initData=0` ⇒ 客户端**没给**签名身份串；我们的 hash 兜底也拿不到 `tgWebAppData`（证据见下条，2026-10-14 又加了 `hkeys=`）；
- `hash=713` 但里面只有 `tgWebAppPlatform / tgWebAppVersion / tgWebAppThemeParams` 这类启动参数
  ⇒ 这次打开**不是**官方列的 Mini App 启动方式之一（从普通链接/浏览器打开不在其中，那种情况 initData 按官方定义就是空的）；
- 自托管 SDK 与官方当前文件**逐字节相同**（119731 字节、md5 `ca4a8297c04185dcabadf889be3e89f9`，2026-10-14 从
  `https://telegram.org/js/telegram-web-app.js?64` 现取对拍）⇒ **不是** SDK 版本或自托管的问题。

⇒ 判断：电脑版把**键盘上的 web_app 按钮**当成普通链接打开了（客户端没走 Mini App 启动流程），
所以页面拿不到身份数据、只能拒绝开门。

### 9.22.3 修法（不新增任何口子）

1. **内联入口**：`menutext.app_inline(site_url)` 产出内联 `web_app` 按钮（官方文档列出的启动方式之一，各端都认）。
   `/menu` 现在自己发**两条**消息（一条消息只能带一种 reply_markup，键盘与内联不能共存）：
   ① 主菜单文案 + 底部常驻键盘；② 内联「🖥 打开面板」。`menu._cmd_menu` 发完返回 `None`，
   `bot._handle_private` 的 `if reply is None` 分支因此不再重发（2026-10-13 那次「回复不带键盘」同理）。
2. **诊断可分辨**：诊断行新增 `hkeys=`，**只列 hash 的键名、绝不列值**（`tgWebAppData` 里是签名，不能进截图或日志）：
   有 `tgWebAppData` 却读不到 = 我们解析的问题；只有 `tgWebAppPlatform/ThemeParams` = 客户端没按 Mini App 打开。
3. 打不开时的红字改成给两条路：手机版点底部键盘 / 电脑版发 `/menu` 点内联按钮。

### 9.22.4 边界与验证

内联按钮与键盘按钮指向**同一个** `APP_PATH`、走同一套 initData 验签 ⇒ 没有新路由、没有新参数、没有新表；B1–B8 不变。
单测：`tests/unit/tg_assist_miniapp_test.py`（62 条，含内联按钮与 `hkeys=` 两条）、`tests/unit/tg_assist_menu_test.py`（108 条）。
真机验证只能由用户点一次（本机无外网、也没有真人 Telegram 会话）。
## 9.23 把「打开面板」做成三处入口（2026-10-14 用户 m04148 反馈）

### 9.23.1 用户原话与现象

User said (m04148): 「就是，我发现我可以点击机器人给我的信息按钮，但是我无法点击telegram官方自带的那个按钮」。
⇒ 消息里挂的**内联**按钮能开；Telegram **自己画的**那颗（底部常驻键盘最后一行、以及输入框旁边的菜单按钮）开不了。
（前者是本模块发的消息内容，后者是客户端 UI —— 两者在 Telegram 里属于不同机制，§9.22 已经证明键盘那颗在电脑版会被当普通链接。）

### 9.23.2 两处修法（都不新增路由/参数/表）

1. **底部键盘那颗「🖥 打开面板」改成纯文字按钮**（`menutext.reply_keyboard` 最后一行只剩 `{'text': WEBAPP_LABEL}`）：
   纯文字按钮是键盘最基本元素，任何客户端都发得出来；点了会把文案当消息发回来，
   `menu._tg_assist_menu_reply` 用 `menutext.is_app_tap(text)` 认出它，回一条**带内联 web_app 按钮**的消息。
   代价是多点一次，换来「每台设备都能进」（web_app 键盘按钮的电脑版缺陷见 §9.22）。
   `site_url` 参数保留在签名里，只为不动 14 处调用点。
2. **输入框旁边那颗 Telegram 自带菜单按钮设成「面板」**（`menu._ensure_menu_button`）：
   私人聊天里调 `setChatMenuButton(chat_id=…, menu_button={'type':'web_app','text':'打开面板','web_app':{'url':…}})`；
   它属于官方列出的启动方式、各端都给身份数据 ⇒ 电脑版**一步**就能开面板。
   `/menu` 时顺手设一次（幂等）；只给 role ∈ admin/teacher/dorm_head 设；只按聊天设（**不动全局默认、不动群**）；
   系统参数 `edu_tg_assist.menu_button = 0` 可关（默认 1）；整段包在 try/except 里只记日志 ——
   这颗按钮没设上，绝不能影响 /menu 的正常回复。

### 9.23.3 本地探针（/tmp/local_appbtn_probe2.py，api.call 与 api.send_message 全部 monkeypatch 记账，结尾 rollback）

- `/menu`（admin、私人 chat 999000777）：`SEND private_cmd` 主菜单+底部键盘（最后一行 = `[{'text': '🖥 打开面板'}]`，**没有** web_app）
  + `SEND menu` 内联按钮；`CALL setChatMenuButton chat=999000777 type=web_app text=打开面板 url=https://edu.example.org/edu_tg_assist/app`。
- 再把 `🖥 打开面板` 当普通文本发过去：`SEND private_cmd 🖥 点下面这颗按钮打开面板（手机版、电脑版都能开）。`，markup 是内联 web_app。
- `SAFE_RC=0`（日志 /tmp/edu19_upgrade.20261014-160019.log）。

### 9.23.4 边界

`setChatMenuButton` 用的是本模块自己的 `edu_tg_assist.token`（B6：不打印），只改本机器人私人聊天的 UI 按钮；
没有新路由、没有新参数表项（只有可选的 `edu_tg_assist.menu_button` 开关）、没有新表；B1–B8 不变。
