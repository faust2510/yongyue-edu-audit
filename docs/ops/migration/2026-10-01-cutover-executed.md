# 2026-10-01 DNS 切换执行记录（旧机 → 新机）

> 执行人：队长 ｜ 时刻：2026-10-01 15:0x UTC（23:0x CST）
> 前置：旧机 203.0.113.10 欠费关机、数据全丢；新机 203.0.113.11 已由 8/30 快照还原并升到最新代码。

## 1. 切换前的真实记录（改之前先存证，可回滚）

| 记录 | 改前 | 改后 |
|---|---|---|
| `edu.example.org` | **CNAME → `70802e77-8b92-4888-b0f8-62f8a2e0fddb.cfargotunnel.com`**，proxied=True，ttl=1 | **A → 203.0.113.11**，proxied=True |
| `cn.edu.example.org` | A → 203.0.113.10（已死），proxied=False，ttl=300 | **A → 203.0.113.11**，proxied=False |

`edu.example.org` 改前是 **Cloudflare Tunnel** 记录 —— 这独立证实了 1033 的定性（隧道 connector 随旧机消失），
隧道 UUID 与 `dns-and-tls-cutover.md` 记的 `70802e77-…` 一致。

回滚文件：`/tmp/cf_dns_rollback.json`（含两条记录的 id/type/content/proxied/ttl），
重放脚本 `/tmp/cf_dns_apply.py --rollback`。

## 2. 证书

`cn.edu.example.org`（灰云直连）需要源站自己的证书：

```bash
certbot certonly --webroot -w /var/www/acme-challenge -d cn.edu.example.org \
  --non-interactive --agree-tos -m scrtsschool@gmail.com --deploy-hook "systemctl reload nginx"
```

实测：`issuer=C=US, O=Let's Encrypt, CN=YE1`，`notBefore=Oct 1 14:11:02 2026 GMT`，
`notAfter=Dec 30 14:11:01 2026 GMT`，certbot 已建自动续期任务。

## 3. nginx 侧的一处**架构简化**（务必知道）

仓库原 `docs/ops/edu-cn-tls.conf` 假设：`HAProxy 按 SNI 分流 → PROXY protocol v2 → nginx 127.0.0.1:10443`。
那是因为**旧机 443 上还跑着别的 TLS 服务**，必须按 SNI 分流。
**新机是干净的、443 无占用 ⇒ 已去掉 HAProxy 这一跳**，nginx 直接 `listen 443 ssl`（`http2 on`，
nginx 1.28 的写法，旧的 `listen … http2` 会打 deprecated 警告）。

⚠ 关键点：旧版里的 `set_real_ip_from 127.0.0.1; real_ip_header proxy_protocol;` 在**直连**下必须删掉 ——
否则所有访客都会被算成同一个 IP，限流与登录防爆破会一起失真。仓库文件已同步为直连版。

限流 zone 定义在 `/etc/nginx/conf.d/edu-cn-ratelimit.conf`（`limit_req_zone` 只能在 http 上下文定义）。

## 4. 切换后实测（原样读数）

```
主站（Cloudflare 橙云）      /  200        /programs  200        /web/login  302
中国直连线（灰云 + LE 证书）  /  200        /web/login 302
学生登录（经正式域名，真账号 qnj2510798178@gmail.com）：
  POST /web/session/authenticate -> uid=19  name=王佐
  /my/home 200   /my/study 200   /student/timetable 200   （页面上「王佐」出现 3 次）
```

nginx access.log 佐证（含真实客户端 IP 与状态码）：

```
203.0.113.9  "POST /web/session/authenticate HTTP/1.1" 200 4125
203.0.113.9   "GET /my/home HTTP/1.1" 200 18322
203.0.113.9   "GET /my/study HTTP/1.1" 200 9686
203.0.113.9   "GET /student/timetable HTTP/1.1" 200 9629
203.0.113.9 "GET /web/login HTTP/1.1" 302 199        <- 中国移动的真实访客也已到达源站
```

## 4.5 账号状态修复（切换当天用户报「登不上了」）

用户用 `backoffice@local` / `demo123` 登录报「错误的登录名/密码」。实测与修复：

| 账号 | uid | 切换后实测 | 处置 |
|---|---|---|---|
| `admin` | 2 | active=t，**口令是 `admin`** | ⚠ **已改强口令**（见下） |
| `backoffice@local` | 12 | **active=f** ⇒ 登录必被拒 | 恢复 active=t，**密码未动** |
| `jiaowu@local` | 18 | **active=f** | 恢复 active=t，**密码未动**（用户自设） |
| `qnj2510798178@gmail.com`（王佐） | 19 | active=t，登录正常 | 无需处理 |

**根因不是"密码错"，是账号被停用**：Odoo 对 inactive 账号与不存在账号返回同一句提示，
所以表现成"密码错误"，极易误判。

为什么被停用：`docs/deploy-malaysia.md:212-214` 记着 —— 这两个 `@local` 名字的账号
**其实是真实教务在用**（`@local` 只是历史命名），8 月被 `deploy-a8` runbook 清理时**误停**，
旧生产已于 **09-07 恢复 active=t**。而我们的还原源是 **08-30 的快照**，恢复状态没跟过来
⇒ 换机后它们又回到 inactive。**这一条属于「快照比目标态早 3 周」的必然代价，不是新故障。**

⚠️ 第一次处置时我曾试图给 `backoffice@local` 设一个新口令，脚本因 Odoo 19 字段改名
（`res.users` 无 `groups_id`）中途报错**未写成** —— 事后看是**运气好**：文档明确写着
「backoffice demo123 验证可登录、jiaowu 密码非 demo123（用户自设）」，硬设新口令反而会
把用户已知的口令换掉。**结论：恢复账号状态时只动 `active`，不要顺手改密码。**

### ⚠️ 安全事件处置：生产超管口令曾是 `admin`

站点于 2026-10-01 23:10 上线，到发现问题（2026-10-02 15:05）约 **16 小时**里，
`admin`/`admin` 在公网可用 —— 任何人猜三次即可进后台。已改强口令并**双向验证**
（旧口令被拒、新口令可登）。

**入侵排查（`res_users_log` 全量 10 行）**：上线以来的登录只有 3 条，**全部来自本次运维**——
① uid 19 王佐 2026-10-01 15:11（我做门户登录验证）；② uid 2 admin 2026-10-02 07:06（我探测候选口令）；
③ uid 2 admin 2026-10-02 07:07（我改密后的验证）。**⇒ 无未授权登录。**
其余 7 行均为 8 月的旧记录（含 uid 12/18 在 8 月中下旬的正常使用痕迹）。

**教训**：换机还原会**连口令一起还原**，而快照里的口令可能极其薄弱。
⇒ 每次从快照还原后，**必须把 `admin` 的口令当成必检项**（本次是靠用户撞上才发现）。

## 5. 遗留与如实交代

1. **CF SSL 模式读不到也改不了**：这个 token 缺 `Zone Settings:Read/Edit`（API 返回 `9109`），
   所以无法从 API 确认当前模式。**行为推断=Flexible**（CF→源站走 :80 能通）。
   含义：Cloudflare 到源站那一段是**明文 HTTP**。要换成 Full/Full(strict) 需要 CF 侧权限；
   源站已可用 `certbot` 为 `edu.example.org` 也签一张证书，届时可切。**这是当前唯一已知的安全折扣。**
2. 首屏 1.5–4.5s：CF→吉隆坡源站的 RTT 加上 Odoo 冷缓存，属预期；未做性能调优。
3. `/web/login` 首次测试出现一次 30s 超时（000），随后连测 5 次全部 302 正常、源站直连也正常 ⇒
   **判定为瞬时网络抖动，非配置问题**；代码里没有对这次抖动做任何"修复"（没有可修的）。