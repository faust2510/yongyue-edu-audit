# Telegram 发注册码机器人（`edu_tg_bind`）设计
> **状态**：`已上线` ｜ **主题**：`注册码机器人` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「不部署生产」（那是 T-E 任务当时划定的范围），实际该模块已随 `scripts/deploy_myedu.sh` 上线：生产 `edu_tg_bind/models/tg_claim.py` 与本地 md5 一致，且已被 web 进程加载（2026-09-26 核对发现）。正文未改动。

> 任务：**T-E**（设计 + 实现 + 本地验证，**不部署生产**）｜取证时间：2026-09-17
> 取证环境：本机 docker 栈（库 `edu19`，运行镜像 `odoo:19`；Odoo 19.0 + PostgreSQL 16.15）
> 本文先于代码写成。文中每条「实测」都可原样复现，命令附在对应小节。
> 关联：`docs/code-map.md` §4/§5/§6｜`docs/plans/invite-code-tiers-design.md`（层级码 `edu.invite.code`）｜`docs/audit/deprecated-inventory.md`（v2.2 退役登记）

---

## 0. 结论速览（TL;DR）

1. **学生私聊机器人 → 回一张学生层级邀请码**，一个 Telegram 账号**只能领一张**；同一个人再来 → **回显原码**，不消耗新码。
2. **「一账号一张码」由数据库两条唯一约束保证**：`edu_tg_claim.chat_id` 唯一（一账号一码）+ `edu_tg_claim.invite_code_id` 唯一（一码一人）。**不是靠 if 判断**。
3. **⚠ 本设计最重要的一手发现：Odoo 19 的事务隔离级别是 `REPEATABLE READ`**（`odoo/sql_db.py:373` 无条件设置；本机运行时实测 `show transaction_isolation` → `repeatable read`）。
   这意味着**教科书式的「`SELECT … FOR UPDATE SKIP LOCKED` 取一张空码」在 Odoo 里不够**：快照过期的那个事务**看不见**别人已提交的领取记录，会**再次选中同一张码**。本机已复现（§5.3 实验 B）。
   ⇒ 正确做法 = `SKIP LOCKED`（挡住**在途**并发）+ **唯一约束**（挡住**已提交**并发）+ **整事务回滚后重试**（重试必须换快照才收敛，§5.4 实验证明 savepoint 内重试会**永远撞同一张**）。
4. **出网：容器内能直连 `api.telegram.org`**（本机实测：容器内 `getMe` 拿到 Telegram 真实 `401 Unauthorized`，DNS `203.0.113.9`）⇒ **同步发送**，不需要第二跳中继。
   （本机**宿主机**反而不通：DNS 被解析到 `203.0.113.9` 并超时。这是本机网络环境，不是生产结论。）
5. **Webhook 鉴权走官方头 `X-Telegram-Bot-Api-Secret-Token`，且 fail-closed**：`edu_tg_bind.webhook_secret` **未配置时拒绝一切请求**（不是「没配就不校验」）。
6. **码池不改 `edu_portal`**：用 `edu.invite.code.batch_ref` 前缀标记（跨模块加字段 = 改 `edu_portal`，不做）。
7. 只处理**私聊**；群 / 频道 / 非 message 更新**一律忽略**（否则一个群能把 200 张码刷空）。

---

## 1. 边界（先读这一节，否则下一个人一定踩雷）

### 1.1 生产上跑着**另一个**同名模块：`edu_telegram` = 匿名意见箱

| | 生产那个 `edu_telegram` | 本模块 `edu_tg_bind` |
|---|---|---|
| 是什么 | **匿名意见收集机器人**（学生私聊吐槽，教务看汇总） | 学生私聊领一张注册邀请码 |
| 关键模型 | `edu.feedback` / `edu.feedback.session` / `edu.telegram.outbox` | `edu.tg.claim` |
| 系统参数 | `edu_telegram.*` | `edu_tg_bind.*` |
| webhook 路由 | `/telegram/webhook` | **`/telegram/tgb/webhook`** |
| 出网方式 | 写 outbox 表，宿主中继常驻投递 | **容器内直接同步调用** Bot API |
| 匿名承诺 | **不存明文 chat_id，只存 HMAC 指纹** | 必须存明文 chat_id（否则做不到「一账号一码」） |

> **为什么这条必须写死**：意见箱的匿名性建立在「不保存明文 chat_id、只保存 HMAC 指纹」上。
> 一旦有人把两个模块的 chat_id 并排放进同一张表 / 同一个后台页，学校的匿名承诺当场作废——而且是**不可逆**的（历史行已经存了明文）。
> 本模块的 chat_id 只能出现在 `edu_tg_claim` 里，**永远不要**与意见箱的数据做 join、导出、对比。

### 1.2 本模块的硬边界（违反即事故）

- ❌ 不读写 `edu_telegram_outbox`（意见箱的投递队列）。
- ❌ 不读不写任何 `edu_telegram.*` 系统参数。
- ❌ 不占用 `/telegram/webhook`（生产意见箱在用）。
- ❌ `depends` 里**不出现** `edu_telegram`（生产那个同名模块若被本模块拖进依赖图，`-u` 会连带升级/触碰它）。
- ❌ 不复用 `scripts/telegram_relay.py`（**它认领的正是 `edu_telegram_outbox`，且只认一个 `TG_TOKEN`**，见 §2.2）。

### 1.3 与本仓 `custom_addons/edu_telegram`（v2.2 四角色前端）也没关系

本仓那份 = 「Edu Telegram Bot」v2.2（`op.telegram.chat` / `edu.telegram.binding` / `flow` / `push`），**从未部署**、已由用户裁定退役（本轮 doc-only 登记，见 §13）。
它**也**占了 `/telegram/webhook`（`controllers/main.py:990`）——**本模块同样不碰它**，路由改走 `/telegram/tgb/webhook`。

---

## 2. 调研（铁律 0：先查成熟实现）

### 2.1 Odoo 19 核心源码（一手：运行镜像内 `/usr/lib/python3/dist-packages/odoo/`）

| 结论 | 证据 |
|---|---|
| 隔离级别是 **REPEATABLE READ**（无条件设置） | `odoo/sql_db.py:373` `self.connection.set_isolation_level(ISOLATION_LEVEL_REPEATABLE_READ)` |
| 运行时口径一致 | `odoo shell` 实测 `env.cr.execute('show transaction_isolation')` → `('repeatable read',)` |
| 核心自带**行锁 API**（用 `SKIP LOCKED`，注释说明了为什么不用 `NOWAIT`） | `odoo/orm/models.py:5591 try_lock_for_update()`、`:5563 lock_for_update()` |
| 该 API 用 `FOR NO KEY UPDATE` 的理由（正是本模块的场景） | 同上 docstring：`allow_referencing: Acquire a row lock which allows for other transactions to reference this record` |
| 核心对「并发取一件」的既有解法 = `FOR NO KEY UPDATE SKIP LOCKED` + WHERE 条件兜底 | `odoo/addons/base/models/ir_cron.py:325-365`（注释逐条讲 (i) 两个 worker 不能取同一件 (ii) 已处理的不能重复处理） |
| 队列式认领先例（本仓脚本同款 SQL） | `odoo/tools/sql.py:699`、本仓 `scripts/telegram_relay.py` 的 `CLAIM_SQL` |
| **请求级并发重试是框架内建的**（`MAX_TRIES_ON_CONCURRENCY_FAILURE = 5`，指数退避） | `odoo/service/model.py:160 retrying()` + `odoo/http.py:2303/2329`；可重试集合 = `LockNotAvailable / SerializationFailure / DeadlockDetected`（`service/model.py:29`）——**UniqueViolation 不在其中**，故唯一约束冲突必须在控制器内自己接住 |
| 控制器内手动 `cr.commit()` 有先例（并发场景） | `odoo/addons/mail/controllers/discuss/public_page.py:85`（并发建频道撞唯一约束后 `request.env.cr.commit()` 再查） |

### 2.2 本仓既有实现：能复用 / 不能复用

| 对象 | 结论 | 理由 |
|---|---|---|
| `scripts/telegram_relay.py` + `telegram_relay.sh`（宿主常驻中继） | **不复用** | ① 它认领 `edu_telegram_outbox` = 意见箱的表（硬边界）；② `TG_TOKEN` 是**单 token** 环境变量，加第二个 bot 要改成多 token；③ 它靠 `docker exec psql` 直连库，是给「容器不能出网」的年代写的（§6 实测容器**能**出网） |
| `custom_addons/edu_telegram/controllers/main.py` 的 webhook 写法 | **抄思路，不抄文件** | 抄：`auth='public'` + `csrf=False` + `X-Telegram-Bot-Api-Secret-Token` 头校验 + `dry_run` 回显（本地可测）；**不抄**：路由、参数名、outbox 出网 |
| `edu.invite.code`（edu_portal） | **直接用，不改** | 它就是「发给谁的码」的既有事实源；注册侧 `/register` 已经认它 |
| 除 `edu.tg.claim` 外再建「绑定」模型 | 不做 | 本轮只要「谁领走了哪张」，一张表够 |

### 2.3 Telegram 官方文档（一手：`core.telegram.org/bots/api`，本机经容器取回 860 KB 原文后摘录）

| 事实 | 原文（摘） |
|---|---|
| 鉴权头的官方名字 | `secret_token`：`A secret token to be sent in a header "X-Telegram-Bot-Api-Secret-Token" in every webhook request, 1-256 characters. Only characters A-Z, a-z, 0-9, _ and - are allowed.` |
| 端点返回码语义 | `setWebhook`：`In case of an unsuccessful request (a request with response HTTP status code different from 2XY), we will repeat the request and give up after a reasonable amount of attempts.` |
| **并发投递**（本设计必须假设有并发） | `max_connections`：`The maximum allowed number of simultaneous HTTPS connections to the webhook for update delivery, 1-100. Defaults to 40` ⇒ **默认 40 条更新可同时打进来** |
| 只收需要的更新类型 | `allowed_updates`（本模块只注册 `["message"]`） |
| 排障字段 | `WebhookInfo.pending_update_count`（`Number of updates awaiting delivery`）、`last_error_message`、`max_connections` |
| 端点网络要求 | `url` 必须是 **HTTPS**；`Ports currently supported for webhooks: 443, 80, 88, 8443`；自签证书走 `certificate` 参数 |
| **chat_id 不能用 32 位整数** | `User.id`：`This number may have more than 32 significant bits ... But it has at most 52 significant bits` ⇒ 见 §3 的字段选型 |

### 2.4 外部先例（OCA / Apps Store / 同类系统）

| 查了什么 | 结论 | 一手来源 |
|---|---|---|
| OCA 有没有 Telegram 模块 | 有 `mail_gateway_telegram`（OCA/social）：**只有 16.0 与 18.0 分支，19.0 不存在**；license **AGPL-3** | https://github.com/OCA/social/tree/18.0/mail_gateway_telegram ｜ https://github.com/OCA/social/blob/18.0/mail_gateway_telegram/__manifest__.py |
| 它的定位 | Discuss **双向聊天网关**（把 Telegram 当成 mail/discuss 的一个渠道），依赖整套 `mail_gateway`；webhook 走 `/gateway/<usage>/<token>/update`（token 在 **URL 路径**里） | https://github.com/OCA/social/blob/18.0/mail_gateway/controllers/gateway.py |
| Apps Store | 搜 "telegram" 约 94 条结果（多为付费插件 / 聊天助手类） | https://apps.odoo.com/apps/modules/browse?search=telegram |
| 与本案需求（一次性注册码下发 + 一账号一张） | **没有任何现成模块覆盖** | —— |

**「能装不写」在这里不成立**，三条独立理由（任一条成立就足以否决安装）：
1. **版本**：现成模块最高 18.0，本仓是 Odoo 19（实测 `odoo.release.version_info = (19, 0, 0, FINAL, 0, '')`）⇒ 装不上；
2. **License**：AGPL-3 对 LGPL-3 生态是传染性风险，本仓 `docs/compliance-audit.md` 的口径是「自研 vs 第三方源码，版权干净」⇒ 不宜引入；
3. **定位不符**：它是长期双向聊天网关，本模块是一次性发码；为它引入 `mail_gateway` 全套，代价远超收益。

**Telegram 侧**不存在「装个官方库」的问题 —— Bot API 就是 HTTPS + JSON，本模块直接用 `requests` 调（§6）。

**另用官方服务端源码（tdlib/telegram-bot-api）交叉验证了 §2.3 的三条硬事实**：
`secret_token` 校验为 ≤256 字符 + Base64URL 字符集（`Client.cpp`，与文档原句「A-Z a-z 0-9 _ -」一致）；
头名逐字一致 `X-Telegram-Bot-Api-Secret-Token`（`WebhookActor.cpp:560`）；
端点必须返回 **2xx** 否则重投（`WebhookActor.cpp:618-652`）；
端口白名单 80/88/443/8443 与 HTTPS 要求同源（`WebhookActor.cpp:707-714`）。

---

## 3. 数据模型：`edu.tg.claim`（表 `edu_tg_claim`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `chat_id` | Char, required, index | Telegram 私聊 chat.id。**存字符串**：TG 用户 id 可超 32 位（§2.3 官方警告），Odoo `fields.Integer` 落库是 `int4` ⇒ 会**溢出** |
| `telegram_name` | Char | `from.first_name` + `from.last_name`（用户自填，仅供教务认人，**不是身份校验**） |
| `username` | Char | `from.username`（不带 `@`；很多人没设，允许空） |
| `invite_code_id` | Many2one `edu.invite.code`, required, `ondelete='restrict'` | 领走的那张码 |
| `invite_code` | Char, related=`invite_code_id.code` | 列表里直接看得到码 |
| `claimed_on` | Datetime, required, default now | 领取时刻 |
| `notify_state` | Selection(sent / failed / skipped / skipped_dry_run) | 回复是否真发出去了（**出网失败不吞**） |
| `notify_error` | Text | 失败原因（截断 500 字） |
| `notify_attempts` | Integer | 投递尝试次数 |

**两条唯一约束（本模块的核心不变量；Odoo 19 写法 `models.Constraint`）**：

```python
_claim_chat_uniq = models.Constraint('unique (chat_id)', '一个 Telegram 账号只能领一张邀请码。')
_claim_code_uniq = models.Constraint('unique (invite_code_id)', '这张邀请码已经发给别人了。')
```

- 第 1 条 = 用户明确要求的那条（**一 TG 账号一张码**），落在 `chat_id` 上；
- 第 2 条 = **并发兜底**：即使两个不同 chat 的请求因快照过期选中了同一张码（§5.3 实验 B），数据库也只允许一个 insert 成功。

**索引**：`chat_id` 唯一约束自带索引；池查询走 `edu_invite_code(batch_ref)` 既有普通索引 + `NOT EXISTS` 子查询（池 200 行量级，不是性能瓶颈）。

> ⚠ **不变量**：`edu.tg.claim` 只记「领」，**不写** `edu.invite.code.state/used_count`。
> 原因：`state='used'` / `used_count>=use_limit` 是**注册**侧消费后的状态（`_validate_view()`），
> 若机器人提前写它，学生拿着码去注册会被判「该邀请码已被使用」——直接堵死注册。

---

## 4. 码池规则（谁可以被发出去）

池 = `edu.invite.code` 中**同时**满足：

| 条件 | 值 | 为什么 |
|---|---|---|
| `batch_ref` | 以系统参数 `edu_tg_bind.pool_batch_prefix` 开头 | **用前缀标记而不是加字段**：给 `edu.invite.code` 加字段 = 改 `edu_portal`（跨模块），本轮明确不做 |
| `state` | `'unused'` | 注册侧 `_validate_view()` 的第一道判据 |
| `used_count` | `coalesce(used_count,0) = 0` | 列**可空**（实测 `is_nullable=YES`，当前 0 条 NULL），故用 coalesce |
| `expire_at` | `> 领取时刻` | 列 **NOT NULL**（实测），所以不需要 NULL 分支 |
| `code_kind` | `'tier'` | 只发层级码 |
| `tier` | `'student'` | 只发学生层码（本次需求：学生注册） |
| 未被领取 | `NOT EXISTS (select 1 from edu_tg_claim where invite_code_id = c.id)` | 池的「已领」判据 |

**前缀方案 vs 加字段（论证）**
- 加字段（如 `edu_tg_bind_eligible`）要 `_inherit` `edu.invite.code`，**字段落在同一张表上**，等于让本模块与 `edu_portal` 的表结构耦合；本任务是「新模块、不碰既有模块」，代价明显更大，且会牵动 `edu_portal` 的视图/导入。
- 前缀方案的代价：`batch_ref` 是**人可读的批次标签**（批量向导自动生成 `B20260917-101112`，且字段 `readonly=True`）⇒ 生产建 200 张码时要么建完批量改 `batch_ref`，要么用 ORM/脚本按前缀建。**这步不做，池就是空的**（学生只会收到「请联系教务处」）——已登记为 §12 遗留未决点 1。
- 前缀匹配必须**转义 LIKE 元字符**（`%` `_` `\`），否则前缀里的 `_` 会变成通配符，池会意外扩大。

**空池行为**：回一句人话（见 §8），HTTP **200**，**不写** `edu.tg.claim`，不 500。


---

## 5. 并发与幂等（含实测）

### 5.1 目标

1. 两个学生**同时**发 `/start` ⇒ **绝不同码**；
2. 同一个人连点两次 / 重放同一条 update ⇒ **同一张码**，且**码池可用数不变**。

### 5.2 方案（三层防线）

```sql
SELECT c.id FROM edu_invite_code c
 WHERE c.batch_ref LIKE %(prefix)s
   AND c.state = 'unused'
   AND coalesce(c.used_count, 0) = 0
   AND c.expire_at > %(now)s          -- 由 Python 传 UTC-naive 时刻，不用 now()：避免 timestamptz × 会话时区口径漂移
   AND c.code_kind = 'tier'
   AND c.tier = 'student'
   AND NOT EXISTS (SELECT 1 FROM edu_tg_claim k WHERE k.invite_code_id = c.id)
 ORDER BY c.id
 LIMIT 1
 FOR NO KEY UPDATE SKIP LOCKED        -- 不是 FOR UPDATE：本事务随后 INSERT 引用它的行，FK 取 KEY SHARE
```

| 层 | 挡什么 | 机制 |
|---|---|---|
| 1 | 同一 chat 重复 / 重放请求 | `unique(chat_id)`；命中即**回显原码**（幂等） |
| 2 | **在途**并发（两个请求同时在跑） | `FOR NO KEY UPDATE SKIP LOCKED`：第二个请求跳过被锁住的那张 |
| 3 | **已提交**并发（快照过期，第 2 层看不见） | `unique(invite_code_id)` + 整事务 `ROLLBACK` 后重试（**必须换快照**） |

重试上界 **4 次**（退避 50/100/200/300 ms，睡眠时不持锁）；用尽仍冲突 ⇒ 回一句
「系统繁忙，请稍后再发一条消息」，**不 500**（见 §5.6 实测）。

### 5.3 实测 ①：SKIP LOCKED 到底挡住了什么（用隔离级别做对照）

复现方式：`db` 容器内跑 4 个并发 psql 会话，用临时 schema `tg_probe`（`code` / `claim(chat_id unique, code_id unique)`）复刻真实结构。**验证后临时 schema 已 DROP**（§11 V12 清场自证）。

| 会话 | 隔离级别 | 取码时机 | 结果 | 说明 |
|---|---|---|---|---|
| A | REPEATABLE READ | t=0 | 取到 **1**，claim 提交 | 基准（拿锁 4s 后提交） |
| **C** | REPEATABLE READ | A **持锁期间** | 取到 **2** ✅ | **在途保护有效**（SKIP LOCKED 生效） |
| **B** | REPEATABLE READ | A 提交**之后**，但**快照取在提交之前** | 取到 **1** ❌ → `ERROR: duplicate key value violates unique constraint "claim_code_id_key"` | ⚠ **裸 SKIP LOCKED 不够**：过期快照看不见别人已提交的 claim，且行锁已释放 |
| D | READ COMMITTED | 与 B 同一时点 | 取到 **3** ✅ | 每条语句取新快照 ⇒ 看得见 A 的 claim。**反证 B 的失败是隔离级别造成的，不是 SQL 写错** |

⇒ 结论：**唯一约束不是「多一层保险」，它是 Odoo（REPEATABLE READ）下正确性的必要条件。**

### 5.4 实测 ②：输了以后怎么重试才收敛

同一实验里让「输家」按三种方式重试：

| 重试方式 | 结果 | 结论 |
|---|---|---|
| `SAVEPOINT` 内重取（同一事务） | 又取到 **1** | ❌ **永远撞同一张**（快照没变） |
| 整事务 `ROLLBACK` 后重取 | 取到 **2** ✅，INSERT 成功 | ✅ **重试必须结束当前事务以换取新快照** |

⇒ 控制器实现：**冲突 → `env.cr.rollback()` → `env.invalidate_all(flush=False)` → 重新查/重取 → 重试**。
（`flush=False` 的理由：回滚之后不得把缓存里的待写值再灌回新事务；`Environment.invalidate_all` 见 `odoo/orm/environments.py:357`。）

> 补：Odoo 19 的请求级 `service.model.retrying()` 会自动重跑**可重试的并发错误**（`SerializationFailure` / `DeadlockDetected` / `LockNotAvailable`），但 **UniqueViolation 不在集合里** ⇒ 唯一约束冲突必须在控制器内自己接住（这也是为什么不能只依赖框架）。

### 5.5 幂等（同一个人再来）

`chat_id` 唯一约束 + 先查后取：命中已有 `edu.tg.claim` ⇒ 直接回显 `invite_code_id.code`，**不取新码、不写新行** ⇒ 码池可用数**不变**（本地验证 V3 给前后读数）。

### 5.6 实测 ③：HTTP 层并发（真跑 webhook，不是 psql 模拟）

本地 Odoo 跑 `workers = 6`（`config/odoo.conf`）⇒ 并发请求落在**不同进程**上，是真并发。清空 claim 后实测：

| 用例 | 输入 | 结果 |
|---|---|---|
| V7 | **6 个不同 chat_id 同时** POST（`&` 并行） | 6 个请求全 200、`created=True`、拿到 **6 张互不相同**的码（去重后 = 6）；池可用 7→1；6 条 claim |
| V8 | **同一个 chat_id 并发 4 次** | 4 个响应里都是**同一张**码（1 次真领 + 3 次幂等回显）；**仅 1 条 claim**、池只减 1 |

**这一轮实测抓到一个设计缺陷（已修，留档防复发）**：`SKIP LOCKED` 取不到码有**两种完全不同**的原因 ——
(a) 池真的空了；(b) 池里还有码，但这一瞬间全被别人的事务锁着（在途）。
第一版把 (b) 也当成 (a) ⇒ 并发下学生收到「暂时没有可用的邀请码，请联系教务处」（**说错了话**：其实只是撞车）。
修法：取码失败时再用一条**不加锁的 count** 判一次「池里是否还有候选」——两处 SQL 共用同一份 WHERE 常量
（`_POOL_WHERE`），避免判据漂移；有候选 ⇒ 换快照重试（重试第一步永远是幂等查 chat，所以 V8 的输家拿到的是
「你已经领过…原码」而不是错误文案）；真没候选 ⇒ 才回空池文案。
重试上界 4 次、退避 50/100/200/300 ms（**睡眠时不持锁**：锁已随 ROLLBACK 释放）。

### 5.7 领取与回复的顺序（为什么先落库再出网）

```
校验 secret → 解析 update → [幂等查 / 取码 / 插入 claim] → cr.commit() → 调 Bot API 发送 → 记 notify_state → 200
```

- **先 commit 再发**：保证「一个账号一张码」在任何时刻都成立（不会出现「码已经发到学生手机上、但库里没记」）；
- 出网失败时**保持 200**（不 500）：码已经在库里，学生再发一条消息就会**重发同一张**，不会消耗新码；
- `cr.commit()` 让 `KEY SHARE` 行锁在**出网之前**释放：出网耗时（超时上限 8s）不拖住别的学生；
- 唯一代价（已认账）：进程若在 commit 与发送之间死掉，学生**收不到**消息但库里已有记录 —— 下一次发消息即自愈（回显原码）。**失败方向落在安全的那一侧**。


---

## 6. 出网（实测：容器能不能直连 api.telegram.org）

### 6.1 实测

```bash
$ docker compose exec -T web bash -lc 'curl -sS -m 8 -o /dev/null -w "HTTP=%{http_code} time=%{time_total}" https://api.telegram.org'
HTTP=302 time=2.234389                       # ← 官方 API 的根路径就是 302

$ docker compose exec -T web bash -lc 'curl -sS -m 10 https://api.telegram.org/bot000000:FAKE_TOKEN_FOR_PROBE/getMe'
{"ok":false,"error_code":401,"description":"Unauthorized: invalid token specified"}   # ← Telegram 真实应答（不是代理/劫持）
$ docker compose exec -T web bash -lc 'getent hosts api.telegram.org'
203.0.113.9  api.telegram.org              # ← 真实 Telegram IP

# 对照：本机宿主机（不是生产）
$ curl -sS -m 12 -o /dev/null -w "HTTP=%{http_code}" https://api.telegram.org
curl: (28) Connection timed out after 12003 milliseconds    # 宿主机不通；dig 得 203.0.113.9（非 Telegram）
```

**结论（实测）**：**容器内可直连 `api.telegram.org`**，且拿到的是 Telegram 的真实应答。
⇒ 本模块**同步调用 Bot API 发回复**（`requests.post`，`timeout=(5, 8)`，`requests 2.31.0` 已在镜像里）。

### 6.2 为什么不选另外几条路

| 路线 | 为什么不选 |
|---|---|
| 复用宿主中继 `scripts/telegram_relay.py` | **直接违反硬边界**：它认领的正是 `edu_telegram_outbox`（意见箱的表）；且只认一个 `TG_TOKEN` 环境变量，本模块是**第二个 bot、第二个 token**。改它 = 动生产意见箱的投递链路 |
| 自建队列 + cron（照抄 outbox 那套） | 给「即时性高、QPS 极低」的场景引入队列 + 常驻进程 + 重试状态机，**代价大于收益**：学生就等一句话。队列唯一的优势（抗 Telegram 抖动）已被「失败保持 200 + 下次消息重发同一张」覆盖 |
| 走代理（`TG_PROXY`） | 本机容器直连就通，无需代理；生产在马来西亚（同一台机器上 `curl https://api.telegram.org` 通），也不需要 |

### 6.3 对生产部署意味着什么（**本轮不执行，交给队长**）

1. 生产**不需要**再起一个中继进程；Odoo 容器自己发。
2. 需保证容器**能出网到 `api.telegram.org:443`**——部署前用 §6.1 的同一条命令在**生产**容器里验一次。**本地通不能证明生产通**（两条完全不同的网络路径）。
3. 出网故障的表现是**安静**的：学生收不到消息，但库里已记 `notify_state=failed` + 原因 ⇒ 后台列表一列就能看出来（这正是本模块要存 `notify_state` 的原因）。
4. webhook 要求 HTTPS + 端口 ∈ {443, 80, 88, 8443}：生产走 Cloudflare 443 ✅；⚠ 若 Cloudflare 开了 Bot Fight Mode / WAF 挑战，Telegram 的 POST 会被拦 ⇒ 必须把该路径加入放行（部署清单见 §7.3）。

---

## 7. Webhook 鉴权

### 7.1 采用方式：**官方头 `X-Telegram-Bot-Api-Secret-Token`（不用路径里的 secret）**

- **为什么不用路径 secret**：URL 会进 nginx / Cloudflare 的 access log 与浏览器历史；头默认不进日志。官方 API 给的正是这个头（§2.3 原文）。
- **fail-closed**：`edu_tg_bind.webhook_secret` 为空 ⇒ **一律 403**，不是「没配就不校验」。
  （对比：本仓 v2.2 的写法是 `if secret and got != secret` —— 没配 secret 时**任何人都能打**。本模块刻意改成 fail-closed。）
- 比较用 `hmac.compare_digest`（常量时间），不用 `!=`。
- 头值可能缺失 ⇒ 先归一到空串再比。
- 端点固定返回 `{"ok": true, ...}`（**HTTP 200**），除非鉴权失败（403）或非 POST（405）：Telegram 对非 `2XY` 会重投（§2.3 原文），**403 是我们想要的语义**（伪造者不该被重投）。

### 7.2 本地怎么验（不出网）

`edu_tg_bind.dry_run=1` 时控制器**不调用** Bot API，把「本来会发出去的那句话」放进 HTTP 响应里 ⇒ 本地用占位 token 也能把整条链路验完（§11 V2–V8）。

### 7.3 生产要执行的 setWebhook（**只写进文档，不对生产执行**）

```bash
TOKEN='<BotFather 给的 token>'          # 在生产服务器上执行；不写进仓库
SECRET='<edu_tg_bind.webhook_secret>'   # openssl rand -hex 16；字符集只允许 A-Z a-z 0-9 _ -
curl -sS "https://api.telegram.org/bot$TOKEN/setWebhook" --data-urlencode "url=https://edu.example.org/telegram/tgb/webhook" --data-urlencode "secret_token=$SECRET" --data-urlencode 'allowed_updates=["message"]' -d drop_pending_updates=true
curl -sS "https://api.telegram.org/bot$TOKEN/getWebhookInfo"   # 核对 url / pending_update_count / last_error_message
```

⚠ 三条生产注意：
1. `drop_pending_updates=true` 只影响**本 bot**的积压更新（不影响意见箱那个 bot —— 不同的 bot、不同的 webhook URL）。
2. `allowed_updates` 只要 `message`：群消息 / 频道贴文不进站，§8 的「只处理私聊」是**第二道**（不是唯一一道）闸。
3. 验完看 `getWebhookInfo.pending_update_count` 是否归零、`last_error_message` 是否为空。


---

## 8. 行为规格（逐条）

| 输入 | 行为 |
|---|---|
| 私聊 + 任意消息（含 `/start`）+ 未领过 | 取一张码 → 建 claim → 回复「你的邀请码：…」+ 注册地址 + 一句人话说明 |
| 私聊 + 已领过 | **回显原码**（不取新码、码池可用数不变） |
| 私聊 + 池空 | 回「暂时没有可用的邀请码，请联系教务处。」；HTTP 200；不写 claim |
| **群聊 / 超级群 / 频道**（`chat.type != 'private'`） | **整条忽略**：不写库、不回消息、200 返回 `{"ignored": "non_private_chat"}` |
| 非 `message` 更新（`edited_message` / `callback_query` / `channel_post` …） | 忽略，200 |
| 非文字私聊消息（图片 / 贴纸） | **同样发码**——规则只有一条：私聊即领，不惩罚输入形式 |
| `message.chat.id` 缺失 / 非法 | 忽略，200（不抛异常） |
| 鉴权头不对 / 参数未配 | **403**，不写库 |

**回复文案（全中文）**

```
【未领过】
你的邀请码：{code}

注册地址：{register_url}

新手三步：
① 打开注册地址，把上面的邀请码填进「邀请码」栏
② 填姓名、邮箱（邮箱就是登录名）、密码（至少 6 位）→ 提交
③ 打开 {site_url}/login，用邮箱 + 密码登录

网站使用指南：{site_url}/help/student
⚠ 密码只在网站登录页输入，绝不要在 Telegram 里发密码。
（这个码只发给你一个人，请勿转发。）

【已领过】
你已经领过邀请码了，这是你原来那张：{code}

注册地址：{register_url}

新手三步：……（同上）
（每个 Telegram 账号只能领一张邀请码。）

【池空】
暂时没有可用的邀请码，请联系教务处。

【池取空但有人同时在领（重试 3 次仍冲突）】
系统繁忙，请稍后再发一条消息。
```

> 文案口径：与「只发码、不验证身份」一致——**不问姓名、不问学号、不做核对**；文案里不出现任何需要学生额外提供信息的暗示。
>
> **2026-10-12 加新手教程**（用户要求「有一套完整的新手教程」）：教程由 `models/tg_claim.py` 的 `_tutorial_lines()` 拼在码文案**之后**，
> 站点地址取参数 `edu_tg_bind.site_url`（默认 `https://edu.example.org`），指南页用网站已有的 `/help/student`（不另写一份会发散的说明）。
> 按钮由 `reply_keyboard()` 追加一行两键：「🔑 去登录」→ `/login`、「📖 使用指南」→ `/help/student`；每个 URL 都过 `_button_url_ok()`
> （地址不合法会让**整条** sendMessage 400 ⇒ 学生会一张码都收不到；宁可少一个按钮也不能整条失败）。
> 学生版教程落在**这一侧**的原因：前门把私聊 `/start` 判给学生领码流，学生的消息根本进不了 `edu_tg_assist`。

---

## 9. 权限挂层（四层口径）

| 层 | 谁 | 挂什么 |
|---|---|---|
| L1 开发者 | `base.group_system` | `edu.tg.claim` 全权（1,1,1,1）——清错误数据要有人能做 |
| **L2 教务** | `openeducat_core.group_op_back_office_admin` | `edu.tg.claim` **读 + 改（1,1,0,0）**：看得见「谁在何时领走了哪张码」、可纠正 `notify_state`；**不给 create / unlink** |
| L3 教师 | `openeducat_core.group_op_faculty` | **不给**（不是教学执行数据） |
| L4 门户 | `base.group_portal` | **不给**（ACL 里根本不出现 ⇒ deny by default）。公共（public）同理 |

- 菜单：挂 `openeducat_core.menu_op_school_config`（**261 学生信息 → 配置**，与「邀请码」「老账号补挂身份」同一位置），`groups="openeducat_core.group_op_back_office_admin,base.group_system"`（**并列写法** = 教务 + 系统管理员，管理员最高权）。
- **不给教务 delete 的理由**：删掉一条 claim 会让同一张码**重新进池**（池判据 `NOT EXISTS` 失效），直接破坏「一账号一张码」；真要删，由 L1 做。
- ⚠ 只挂菜单 groups 不算完：**菜单 groups + ACL 两处都要有**（本仓 §6.12 的「看得见点不开」教训）。
- webhook 路由本身是 `auth='public'`（Telegram 不带会话），它**不读任何用户身份**，只认 secret 头。

---

## 10. 配置项（系统参数）

| key | 默认 | 谁配 | 说明 |
|---|---|---|---|
| `edu_tg_bind.token` | 无 | **队长在生产配** | BotFather token。**绝不写进代码 / 测试 / 提交文件**；本地测试用占位值 + `dry_run` |
| `edu_tg_bind.webhook_secret` | 无 | 队长在生产配 | webhook 鉴权；**空 ⇒ 全拒（fail-closed）** |
| `edu_tg_bind.pool_batch_prefix` | `TGB-STU-` | 队长 | 码池 `batch_ref` 前缀 |
| `edu_tg_bind.register_url` | `https://edu.example.org/register` | 队长 | 回复里的注册地址（本地测试改成 localhost） |
| `edu_tg_bind.dry_run` | 无（= 关） | 本地 / 队长 | =1 时不真发，回复内容随 HTTP 响应返回 |

> 系统参数属 **L1 系统设置层**（只有 `base.group_system` 能改），这一点不由本模块改变。

⚠ **改了参数一定要让 web 进程重新读到（实测踩坑，务必写进部署清单）**：
`ir.config_parameter.get_param` 底层是 `_get_param`，它带 `@ormcache('key', cache='stable')`
（`odoo/addons/base/models/ir_config_parameter.py:60`）——**进程级 registry 缓存**。
从 **odoo shell / psql** 这类**另一个进程**改参数，web 进程不会立刻看到新值：
本机实测用 shell 清空 `edu_tg_bind.dry_run` 后，webhook 仍按 dry_run 处理（库里记 `skipped_dry_run`），
**重启 web 之后才真的出网**。
⇒ 生产改这 5 个参数：① 优先从后台「系统参数」界面改（同一进程会清缓存）；② 若用 shell/脚本改，**改完 `docker compose restart web`**。
（本地验证脚本同理——本文档 §11 的 V9 就是这么修的。）

---

## 11. 本地验证计划（可复核）

| # | 断言 | 怎么验 |
|---|---|---|
| V1 | 首装成功 | `bash scripts/safe_upgrade.sh -i edu_tg_bind` → EXIT=0、无 Traceback |
| V2 | 新 chat → 领到码，库里有记录 | POST 伪造 update（`dry_run=1`）→ 响应里的码 == `edu_tg_claim` 里那张 |
| V3 | 同 chat 再来 → **同一张码**，**码池可用数不变** | 再 POST → 码相同；前后各查一次池计数 |
| V4 | 第二个 chat → 另一张码 | 第三个 POST |
| V5 | 群聊 update → 不处理 | `chat.type='group'` 的 update → `{"ignored":...}`，且 claim 行数不变 |
| V6 | 空池 → 人话、无 500 | 把池抽干（或前缀改成不存在）→ HTTP 200 + 指定文案 |
| V7 | **并发**：同时两个新 chat → **两张不同的码** | 并行 curl + 断言两码不同 |
| V8 | 并发同一 chat → 一张码、一条 claim | 并行两个同 chat 请求 |
| V9 | 出网真发生（且失败不 500） | 关掉 `dry_run`、用**占位 token** → 库里 `notify_state=failed` + `notify_error` 含 401，HTTP 仍 200 |
| V10 | 鉴权 | 无头 / 错头 → 403；secret 未配 → 403 |
| V11 | 边界 | `grep` 证明没碰 `edu_telegram_outbox` / `edu_telegram.*` / `/telegram/webhook` |
| V12 | 清场 | 测试 claim / 测试码 / 测试参数全清，残留 = 0（逐条 SELECT 自证） |

门禁：`check_english.py`（动了用户可见文案）、`check_manifest_tracking.py`、`check_view_xpath.py`、`check_qweb_dict_foreach.py`（未动 QWeb，仍跑一遍自证）。


---

### 11.1 验证结果（2026-09-17 本机实跑，逐条带读数）

| # | 结果 | 关键读数 |
|---|---|---|
| V1 | ✅ 首装 | `bash scripts/safe_upgrade.sh -i edu_tg_bind` → **EXIT=0**、无 Traceback、`Module edu_tg_bind loaded in 0.58s`、就绪探活 `302` |
| V2 | ✅ 新 chat 领到码 | HTTP 200、`created=True`、回 `TGPROBE-CODE-01`；池可用 **9→8**；claim **0→1** |
| V3 | ✅ 同 chat 再来 = 原码、池不变 | HTTP 200、`created=False`、仍是 `TGPROBE-CODE-01`；池可用 **8→8**；chat 111 的 claim 行数 **=1** |
| V4 | ✅ 第二个 chat 拿另一张 | HTTP 200、`TGPROBE-CODE-02`；池可用 **8→7** |
| V5 | ✅ 群聊 / 频道忽略 | `{"ok":true,"ignored":"not_private"}`，claim 行数不变 |
| V6 | ✅ 空池人话、无 500 | HTTP **200**、`暂时没有可用的邀请码，请联系教务处。`；chat 333 **未写库** |
| V7 | ✅ 并发 6 个不同 chat | 6 个 200 / 6 张**互不相同**的码（去重 = 6）、6 条 claim；池 7→1 |
| V8 | ✅ 并发 4 个同一 chat | 4 个响应同一张码（1 真领 + 3 幂等回显）；**1 条 claim**、池只减 1 |
| V9 | ✅ 出网真发生且失败不 500 | 关 dry_run + 形状正确的假 token → HTTP **200**、`sent=false`；库里 `notify_state=failed`、`notify_attempts=1`、`notify_error=HTTP 401: Unauthorized: invalid token specified`（**这段文本是 Telegram 自己回的**，容器内直接调同一 token 得到同一句）；服务端只打 WARNING，无异常栈 |
| V10 | ✅ 鉴权 fail-closed | 无头 / 错头 → **403**；非 POST → **405**；secret 未配 → 403 |
| V11 | ✅ 边界 | `grep` 证明本模块不含 `edu_telegram_outbox` / `edu_telegram.` / `/telegram/webhook` |
| V12 | ✅ 清场 | 测试 claim / 测试码 / 测试参数 / 临时 schema `tg_probe` 全清，逐条 SELECT 残留 = 0 |

---
## 12. 非目标 / 遗留未决点

**非目标（本轮明确不做）**

- ❌ 部署生产、配置真 token / 真 webhook（由队长做）。
- ❌ 身份校验（不问姓名 / 学号；已与用户确认「领取即发」）。
- ❌ 课表 / 成绩 / 通知（本轮**只发码**）。
- ❌ 改 `edu_portal`（含给 `edu.invite.code` 加字段）。
- ❌ 动生产那个 `edu_telegram` 意见箱的任何一行（§1）。

**遗留未决点（交给队长）**

1. **生产码池怎么建**：约 200 张学生层级码、`batch_ref` 统一前缀。`edu.invite.code.batch` 向导的 `batch_ref` 是**自动生成且只读**的 ⇒ 要么建完批量改 `batch_ref`，要么用脚本 / ORM 按前缀建。**这步不做，池就是空的**（学生只会收到「请联系教务处」）。
2. **`expire_at` 设多久**：向导默认 7 天。码在池里过期 = 学生领不到（且**过期后不会自动补**，因为池是惰性判定、无 cron）——建议生产发放时显式给一个较长的有效期。
3. **`edu_tg_bind.dry_run` 必须是关的**：部署清单里要显式确认（开着它，学生永远收不到消息，但库里会记 `skipped_dry_run`，可查）。
4. **反滥用边界**：本轮按用户要求**不验证身份**，因此本设计只保证「**一 TG 账号一张码**」，**不保证「一人一张码」**（一个人可以开两个 TG 账号领两张）。若要收紧，需要新增判据（如手机号 / 学号），属下一轮。
5. **未验证（明确标注）**：本机是 macOS + Docker Desktop，**生产（马来西亚 prod-host）的容器出网未在本轮验证**（§6.3 给了部署前的验证命令）。本地容器通 ≠ 生产容器通。

---

## 13. 顺带交付：本仓 v2.2 `edu_telegram` 的退役登记（doc-only）

> 本轮**不删文件、不改 v2.2 的任何代码**，只在两处文档登记退役：
> `docs/code-map.md` §4 的 edu_telegram 段 + `docs/audit/deprecated-inventory.md` 台账（沿用该台账既有的四栏格式）。

**事实（写死，防下一个人踩雷）**

- 本仓 `custom_addons/edu_telegram` = **「Edu Telegram Bot」v2.2**：四角色教务前端（`op.telegram.chat` / `edu.telegram.binding` / `flow` / `push` / `leave_request` / `outbox`），webhook `/telegram/webhook`（`controllers/main.py:990`），**从未部署**，用户已裁定**退役**。
- **生产上跑的 `edu_telegram` 是另一个东西**（匿名意见箱，`edu.feedback` / `edu_telegram.outbox` / `/telegram/webhook`）。**同名不同模块，本仓这套与它无关**——两者既不共享代码，也不共享表与参数。
- ⚠ **路由冲突是真实存在的**：本仓 v2.2 与生产意见箱都用 `/telegram/webhook`。所以本模块（`edu_tg_bind`）**必须**用新路径 `/telegram/tgb/webhook`，且**不能**把 v2.2 装上（那会与生产意见箱抢同一个路由）。
- 本模块与 v2.2 无依赖关系：`depends` 不含 `edu_telegram`，也不复用它的模型 / 路由 / 参数。

---

## 14. 变更记录

| 日期 | 改动 | 责任 |
|---|---|---|
| 2026-09-17 | 建立设计（含三个技术选择的实测证据：容器出网、REPEATABLE READ 并发对照实验、webhook 鉴权） | T-E |

