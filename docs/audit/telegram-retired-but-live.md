# 退役中的 edu_telegram 仍在**实际运行**（含一条可猜的管理码）

> 发现于 2026-10-03（第 51 轮）。**本文件只登记事实与证据，未改动该模块任何代码** ——
> 停不停它属产品/运维口径，须用户裁定。

## 一、本仓自己的话：它是「退役件」

代码里三处这么写：

```
edu_schedule/models/session_ext.py:391   edu_telegram（退役件 + 出口与生产匿名意见箱同名同表）
edu_schedule/models/session_ext.py:823   本段不触碰 edu_telegram / edu.telegram.outbox（退役件 + 生产同名不同物）
edu_tg_bind/controllers/webhook.py:5     本仓退役中的 v2.2 edu_telegram 也占着同一个路径。本模块**必须**另开一条
```

## 二、但它**装着、且每天都在跑**（实测）

```
ir.module.module:  edu_telegram  state = installed

ir.cron 25  「edu_telegram: 每日推送(待缴/作业截止/考试临近)」  active=True
            模型 edu.telegram.push  方法 model.cron_daily()  间隔 1 days
            最后运行 2026-10-02 10:13  下次 2026-10-03 08:48
ir.cron 33  「edu_telegram: 公告推送(每小时)」                active=True
            模型 op.notice          方法 model.push_new()   间隔 1 hours
            最后运行 2026-10-02 18:12  下次 2026-10-02 19:12

ir.ui.menu 792 「Telegram 领码记录」  active=True

ir.config_parameter:
  edu_telegram.bot_token     = 8450111115:AAF…（46 字符，**看起来是真实 token**）
  edu_telegram.dry_run       = 0        ← 非 dry-run ⇒ 会真的投递
  edu_telegram.admin_key     = ADMIN-2026
  edu_telegram.webhook_secret= 2d9d4c29…（32 字符）
```

## 三、⚠ 可猜的 admin_key（安全面）

`edu_telegram/models/telegram_chat.py:73-79`：

```python
key = self.env['ir.config_parameter'].sudo().get_param('edu_telegram.admin_key')
if key and number == key:
    vals = {'chat_id': chat_id, ..., 'role': 'admin', ...}   # ← 发对这句话就是管理员
```

即：**任何人给机器人发一句 `ADMIN-2026`，就被绑定成 `role=admin`**。而 admin 能拿到什么（同模块实测）：

```
main.py:465  '/概览': ('cmd_overview', {'admin'})          ← admin 专属命令
main.py:588  _notify_roles(env, ('faculty', 'admin'), ...)  ← 教职工/管理员通知的分发对象
```

⇒ 猜中即可收到**发给教职工与管理员的通知**。
（`ADMIN-2026` 全仓代码里**搜不到** ⇒ 它是 DB 里的配置值，不是代码默认值；
 代码在未配置时 `if key and ...` 直接不放行 ⇒ **不配置是安全的**，危险的是配了一个弱值。）

**建议（须用户执行，我没有改）**：在生产轮换 `bot_token` 与 `admin_key`，并明确该模块是留是停。

## 四、本地克隆库的一个隐患（本轮已处置）

本机 `edu19` 是从生产克隆的 ⇒ 带着**生产的 bot token** 且 `dry_run=0`，两个 cron 照跑。
实测 outbox 180 条：

```
今天的记录（10-02 10:13）只发给合成 id：900001 / 424242 / 999
真实观感的 10 位 id 5592841801 共 19 条，时间集中在 2026-08-22 → 2026-09-18
  ⇒ 判断为**克隆生产库时带过来的历史行**，非本机新发
```

**已处置**：把本地克隆库的 `edu_telegram.dry_run` 由 `0` 改为 `1`（该参数本意就是「本地调试」）。
注：`odoo shell` 退出会回滚，必须 `env.cr.commit()` —— 第一次改完查询仍是 0，就是这个原因。
这是**本地库配置**，不在仓库里、不影响生产；要验真实投递时把它改回 0 即可。

## 四之二、已修：webhook 的 **fail-open** 校验（2026-10-03 同日）

顺着「可猜的 admin_key」继续查凭据检查写法，全仓只找到 **2 处** `if <凭据> and ...` 形状，都在本模块：

```
controllers/main.py:1006      if secret and got != secret:     ← ⛔ fail-open
models/telegram_chat.py:76    if key and number == key:        ← ✅ 无妨（没配 ⇒ 谁都不是管理员）
```

**为什么 1006 是真问题**：路由是 `auth='public'`（公网可达）。一旦 `webhook_secret` 被清空或漏配，
`if secret and ...` 直接短路 ⇒ **完全不校验** ⇒ 任何人都能 POST 进来驱动机器人，
而 `bot_token` 是配好的 ⇒ 可**代机器人发消息**。（另：同文件 338 行本来就在用 `hmac.compare_digest`，
这一处却用 `!=`，非常量时间。）

**接替它的新模块早就点名了这个毛病** —— `edu_tg_bind/controllers/webhook.py:47-50`：

```python
# fail-closed：未配置 secret 时拒绝一切请求。
# （本仓 v2.2 edu_telegram 的写法是「if secret and got != secret」——没配 secret 时
#   就等于不校验 ✗）
if not secret or not hmac.compare_digest(secret, got):
```

**改法**：对齐新模块 —— fail-closed + `hmac.compare_digest`。
**行为影响**：secret 已配置时**行为不变**；只有「未配置」从「放行」变成「403」。

**验证（含危险用例本身）**：

```
错 secret            → 403 ✅
对 secret            → 200 ✅（行为不变）
无 secret 头          → 403 ✅
**把参数临时清空**后再打 → 403 ✅  ← 改前这里会直接放行（这才是被修掉的那条路）
恢复 32 字符 secret 后   → 对 secret 仍 200 ✅
```

## 五、未做的事（留给裁定）

· 未停用两个 cron（怕停掉学校正在用的通知渠道）；
· 未卸载模块（表里有历史数据）；
· 未改任何 edu_telegram 代码。