# DNS 与 HTTPS 切换方案：edu.example.org + cn.edu.example.org → 203.0.113.11

> **状态**：方案 + 待执行清单。**本文不含任何已执行的 DNS 改动**（改 DNS 需用户点头）。
> **取证时刻**：2026-10-01 21:2x–21:3x Asia/Shanghai（DNS 读数、HTTP 探针、nginx 语法探针）。
> **配套**：[new-server-runbook.md](new-server-runbook.md)（新机从零到起）、[step0-recover-old-server.md](step0-recover-old-server.md)（旧机已放弃）。

---

## 0. 结论先行

1. **edu.example.org 现在挂的是 Cloudflare Tunnel**，不是普通 A 记录。旧机一死 connector 就断 ⇒ Cloudflare 返回 **530 + error code 1033**。**只要这条记录还是隧道，新机起了站外面也永远看不到**。
2. 隧道凭据（`/root/.cloudflared/*.json`）随旧机一起消失 ⇒ 重建隧道必须在 CF 后台操作；**放弃隧道改"代理 A → 新机"同样只在 CF 后台改一条记录**。
3. **推荐路线 B（放弃隧道，改代理 A）**，理由见 §3；路线 A（重建隧道）作为备选。
4. cn.edu.example.org 是**灰云 A → 旧 IP 203.0.113.10**（实测），**必须一起改**，否则中国直连那条线一直是死的。
5. 新机的 nginx **不需要 cloudflared**（选 B 的前提下）；若要 A，需要新装 cloudflared（Ubuntu 默认源里**没有**这个包，实测 `apt-cache policy cloudflared` 空）并加 CF 官方源或官方二进制。

---

## 1. 现状读数（实测，可复跑）

### 1.1 DNS

~~~bash
dig +short A edu.example.org @1.1.1.1 ; dig +short AAAA edu.example.org @1.1.1.1
dig +short A cn.edu.example.org @1.1.1.1 ; dig +short CNAME edu.example.org @1.1.1.1
dig edu.example.org @1.1.1.1 | sed -n '/ANSWER SECTION/,/^$/p'
~~~

2026-10-01 实测输出：

~~~
edu.example.org.     300  IN A     203.0.113.9
edu.example.org.     300  IN A     203.0.113.9
edu.example.org.           AAAA    2606:4700:3036::ac43:b910
edu.example.org.           AAAA    2606:4700:3037::6815:4c10
cn.edu.example.org.  300  IN A     203.0.113.10
dig +short CNAME edu.example.org  →  （空）
~~~

读法：
- edu 的 A/AAAA 是 **Cloudflare anycast 地址**（172.67/104.21 + 2606:4700:: 段），TTL **300**。
- **CNAME 查询为空不代表"没有隧道"**：记录一旦是 proxied，CF 只对外发布 anycast A/AAAA，**把底下的 CNAME 目标藏起来**。所以"只看到 A 记录"**不能**反推"这是普通 A 记录"。
- cn 是灰云直连（无 AAAA、内容就是源站 IP），TTL 300。

### 1.2 活着的那两个入口

~~~bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY curl -sS -D - -o /tmp/b.html --noproxy '*' https://edu.example.org/ ; cat /tmp/b.html
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY curl -sS -o /dev/null -w '%{http_code} %{time_total}\n' --noproxy '*' https://cn.edu.example.org/
~~~

实测输出（原样）：

~~~
HTTP/2 530
server: cloudflare
cf-ray: a43bcb7d19455e49-SJC
content-type: text/plain; charset=UTF-8
content-length: 17
（body）error code: 1033

cn.edu.example.org  →  curl: (28) Connection timed out after 15001 milliseconds   (http=000, 15.001s)
~~~

### 1.3 仓库侧佐证（隧道实体）

`docs/deploy-malaysia.md`（**2026-08-31 与 2026-09-24 的取证块**，不得据其行号定位代码）写明：
- `edu.example.org → CF 隧道 v2（kul01/sin14×2/sin18）→ nginx :80 → Odoo`；隧道为 **edu-tunnel-v2 / `70802e77-8b92-4888-b0f8-62f8a2e0fddb`**，凭据在旧机 `/root/.cloudflared/70802e77-*.json`，由 systemd 单元 `cloudflared.service` 托管。
- 更早那次迁移尝试还记录过：`edu.example.org` 曾是 `CNAME → 9a830247-….cfargotunnel.com`；且有过一次「把隧道记录误改灰云 ⇒ 全网 43 分钟不可达」的事故（**隧道类 hostname 记录必须保持橙云**）。

---

## 2. 1033 的定性：是「隧道没连上」，不是「源站不可达」

Cloudflare 一手文档（**Last updated Apr 23, 2026**，抓取于 2026-10-01）：

| 错误 | 官方定义（原文要点） | 一手 URL |
|---|---|---|
| **1033** | "Error 1033: **Cloudflare Tunnel error** … The host is configured with **Cloudflare Tunnel**, and Cloudflare is currently unable to resolve it. … A 1033 error indicates your **tunnel is not connected**." | https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1033/ |
| 530 | "Cloudflare is **unable to resolve the origin hostname** … the **body of the response contains an 1XXX error code**." | https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-530/ |
| 521 | "Web server is down" | https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-521/ |
| 522 | "Connection timed out" | https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-522/ |
| 523 | "Origin is unreachable" | https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-523/ |

**判据（可反向证伪）**：
- 如果是**普通代理 A 记录 + 源站关着**，CF 只能报 **521/522/523**；
- 只有**记录被配置成 Cloudflare Tunnel**（或路由到隧道）时，CF 才会在 530 的 body 里回 **1033**；
- 实测拿到 530（status）+ body 恰好 17 字节的 `error code: 1033` ⇒ **这是隧道**。
- 反向对照：同一台机器上 `cn.edu.example.org`（灰云、不经 CF）表现是 **TCP 超时**（15s 无响应），而 `edu.example.org` 是**秒回 530**——两条路径的失败形态完全不同，正因为一条经过 CF 的隧道层、一条直连死 IP。

**⇒ 新机要不要配 cloudflared？** 取决于选哪条路：**选 B 不用**，选 A 必须用。

---

## 3. 两条路线：代价、风险、回滚、推荐

| | **A. 重建/接管隧道** | **B. 放弃隧道 → 代理 A 指向新机**（**推荐**） |
|---|---|---|
| CF 后台动作 | 进入 Zero Trust → Networks → Tunnels：老隧道 `70802e77`（若仍在）**重新下载凭据**或**新建隧道**；再把 hostname 路由指向新机 nginx | DNS 里把 `edu.example.org` 的**隧道记录**改成 **A → 203.0.113.11，橙云**（若该记录由隧道的 public hostname 自动生成，先删/改那条 route，避免被覆盖） |
| 新机动作 | 装 cloudflared（**apt 默认源没有**，实测）+ 落凭据 + systemd service + ingress 指向 `localhost:80` | nginx 按仓库 `docs/ops/nginx-edu-strcs.conf` 监听 :80（+ 视 SSL 模式加 :443） |
| 凭据依赖 | **强依赖**：凭据 json 已随旧机消失，必须在后台重建（不可从旧机拿） | **零依赖**：不碰任何丢失的东西 |
| 源站入向端口 | 可以不开 80/443（隧道是出向连接） | **必须开 80/443**（灰云 cn 线本来就必须开） |
| 源站 IP 暴露 | 不暴露 | 暴露（但 cn 灰云记录**早就暴露了同一台机的 IP**——增量有限） |
| 故障形态 | connector 挂掉 = 又是 1033（**静默型故障**，要有外部探活兜） | nginx/容器挂掉 = 521/522（CF 报错更直白） |
| 中国线路由 | 仍走 CF（历史实测：中国移动 → CF **洛杉矶**跨太平洋丢包 66.7%）；cn 直连入口照样要单独维护 | 不变：edu 走 CF、cn 灰云直连；**与旧架构一致** |
| 回滚 | 改回原隧道路由（回到 1033 故障态） | 把 A 改回原值（回到 1033 故障态）；**两者都无法回滚到"可用"**，因为可用态只能靠新机 |
| 额外风险 | 需要账号有 Tunnel 权限；凭据保管；多一个常驻进程 | CF 侧 **SSL/TLS 模式**必须配对（见 §4.3），否则 525/526 跳转环 |

**推荐 B，理由（每条都可证伪）**
1. **最短可达路径**：B 只需要「一条 DNS 记录 + 新机 nginx」，A 需要「后台重建隧道 + 新机装服务 + 凭据 + systemd」。
2. **不依赖任何已丢失物**：隧道凭据是这次事故里明确丢掉的东西；B 把它整个绕开。
3. **与仓库现有配置同形**：`docs/ops/nginx-edu-strcs.conf` 就是 `:80 + server_name edu.example.org`（B 的形态）；`deploy/docker-compose.prod.yml` 把 web 绑在 `127.0.0.1:8069`（也是给 nginx 反代用的）。
4. **与 cn 线一致**：cn 天生灰云直连，B 让两个入口都走"nginx 收口"，运维面更小。
5. 若日后确要"IP 不外露 / 不开入向端口"，再切 A 也不难（B 的 nginx 配置在 A 下同样可用）。

---

## 4. nginx + HTTPS 落地

### 4.1 主入口（edu.example.org）—— 配置语法**已探针实测**

主站配置沿用仓库 `docs/ops/nginx-edu-strcs.conf`，在其 `server` 块里加 4 行即支持 Full(strict) 回源：

~~~diff
  server {
      listen 80;
      listen [::]:80;
+     listen 443 ssl;
+     listen [::]:443 ssl;
+     http2 on;
+     ssl_certificate     /etc/letsencrypt/live/edu.example.org/fullchain.pem;
+     ssl_certificate_key /etc/letsencrypt/live/edu.example.org/privkey.pem;
      server_name edu.example.org;
      ...
~~~

**实测证据（新机 nginx 1.28.3，2026-10-01；探针把配置与自签占位证书放 `/dev/shm`，跑完即删，不改 /etc）**
> 探针文件 `/tmp/gatetest/edu-strcs-443.conf` = 把仓库 `docs/ops/nginx-edu-strcs.conf` 的 server 块原样外包一层最小 `worker/events/http`，再插入上面那 4 行 —— 逐字可复现。

~~~bash
# A. 仓库主站配置 + 上面 4 行 → 语法必须通过
ssh prod-host 'openssl req -x509 -newkey rsa:2048 -nodes -keyout /dev/shm/probe-key.pem \
  -out /dev/shm/probe-cert.pem -days 1 -subj "/CN=edu.example.org" >/dev/null 2>&1 \
  && cat > /dev/shm/probe.conf && nginx -t -c /dev/shm/probe.conf; rm -f /dev/shm/probe*' < /tmp/gatetest/edu-strcs-443.conf
# 实测：nginx: the configuration file /dev/shm/probe.conf syntax is ok
#       nginx: configuration file /dev/shm/probe.conf test is successful

# B. 负对照：同一份配置注入一行假指令 → 必须报红（证明这个探针不是永远绿）
# 实测：nginx: [emerg] unknown directive "bogus_directive_for_control" in /dev/shm/probe.conf:13
#       nginx: configuration file /dev/shm/probe.conf test failed
~~~

> `http2 on;` 是 nginx ≥1.25 的新写法：用的是新语法时**无告警**；反过来用旧写法 `listen 443 ssl http2;`，新机会打印
> `the "listen ... http2" directive is deprecated, use the "http2" directive instead`（实测）。
> **未实测**：`certbot --nginx` 自动改写配置的行为（本机没签发过证书）；本手册走"手写配置 + certbot certonly"。

### 4.2 中国直连入口（cn.edu.example.org）

旧机形态（`docs/ops/edu-cn-tls.conf`）是：**HAProxy :443 按 SNI 分流 → nginx `127.0.0.1:10443 ssl proxy_protocol`**。它存在的唯一理由是旧机 :443 上还跑着 mtg/xray，得用 SNI 分流。**新机没有 mtg/xray** ⇒ 两个选择：

**形态 1（沿用旧配置，需要 HAProxy）**：照抄 `docs/ops/edu-cn.conf` + `edu-cn-tls.conf` + `edu-cn-ratelimit.conf` + `docs/ops/haproxy-edu-cn.snippet.conf`，并安装 haproxy。**仅当以后确实要恢复 xray/mtg 时才选**。

**形态 2（推荐：去掉 HAProxy，nginx 直接听 443）**：以 `edu-cn-tls.conf` 为基础，改三处：

~~~diff
- listen 127.0.0.1:10443 ssl proxy_protocol http2;
+ listen 443 ssl;
+ http2 on;
- # HAProxy(TCP 模式) 传来 PROXY protocol —— 不恢复真实 IP 的话，
- # 限流会把所有人算成同一个 127.0.0.1 …
- set_real_ip_from 127.0.0.1;
- real_ip_header proxy_protocol;
  server_name cn.edu.example.org;
~~~

`location` 集（静态缓存 7 天、`/web/login` 限流 2r/s、`/websocket` → 127.0.0.1:8072、`/` → 127.0.0.1:8069）原样保留；限流 zone 仍来自 `docs/ops/edu-cn-ratelimit.conf`。去掉 `proxy_protocol` 后 `$remote_addr` 就是真实客户端 IP（直连场景本来就对），**限流与 Odoo 登录防爆破不会失真**。

> ⚠ 主站（edu）与 cn 若都想听 443：两个 `server` 块各自 `server_name` + 各自证书即可（SNI 分流由 nginx 自己做），**不需要** HAProxy。

### 4.3 Cloudflare 侧 SSL/TLS 模式（**这是最容易出 525/526 与跳转环的地方**）

一手文档：加密模式 https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/ ；Origin CA https://developers.cloudflare.com/ssl/origin-configuration/origin-ca/ ；TTL https://developers.cloudflare.com/dns/manage-dns-records/reference/ttl/

| 模式 | CF→源站 | 需要源站有什么 | 风险 |
|---|---|---|---|
| Flexible | HTTP :80（明文） | 只开 80 | **不推荐**：明文回源；且若源站把 HTTP 301 到 HTTPS，会形成**重定向环**（CF 又用 HTTP 回来） |
| **Full** | HTTPS :443（不校验证书） | 443 有任意证书 | 可接受，但自签不受校验 |
| **Full (strict)**（**推荐**） | HTTPS :443（校验证书） | 443 证书可被 CF 信任 | 证书过期/域名不匹配 ⇒ 526 |

两条拿证书的路子：
1. **Let's Encrypt（推荐，走 certbot）**：新机已装 `certbot 4.0.0`（apt 版；**snap 未安装**，实测 `which snap` 无输出，所以别照抄"用 snap 装 certbot"的官方推荐），`python3-certbot-nginx` 也在。ACME 出网实测可达（`https://acme-v02.api.letsencrypt.org/directory` → 200）。
2. **Cloudflare Origin CA**（只在 CF 代理下有效、Strict 兼容；需 CF 账号 + API Access 才能在后台创建）：适合"不想让 CF 每天来看 LE 续期"的场景。**未实测**（需要用户账号）。

**顺序提醒（避免证书拿不到）**：LE 的 HTTP-01 校验要打到**新机**的 80 端口，因此必须在 **DNS 已经指到新机之后**才能签发；这中间会有一段"解析已切、证书还没好"的窗口（HTTPS 报证书错误）。这段窗口是**无害的**——因为现在这两个域名本来就是死的。

---

## 5. 切换顺序（D 日剧本，**未经用户点头不得执行**）

### Phase 0 源站就绪（不动 DNS）
~~~bash
ssh prod-host 'cd /opt/edu-app && docker compose ps'                       # 两容器 running
ssh prod-host 'curl -sS -o /dev/null -w "%{http_code}\n" -H "Host: edu.example.org" http://127.0.0.1/'   # 200/302
ssh prod-host 'nginx -t && systemctl reload nginx'
~~~
判据：本地 Host 头取站 200/302；`nginx -t` 通过。

### Phase 1 CF 后台改记录（**需用户执行/点头**）
1. **cn.edu.example.org**：A 记录内容 `203.0.113.10` → **`203.0.113.11`**；保持**灰云**（DNS only）。
   > 灰云记录 TTL 可以设为 60s；现在实测是 300。**若要缩短切换窗口**，可先把 cn 的 TTL 降到 **60**，等 ≥ 旧 TTL（5 分钟）再改内容。橙云记录**没有这个自由度**（见下）。
2. **edu.example.org**：把**隧道记录**改成 **A → 203.0.113.11，橙云（Proxied）**。
   - 若该 hostname 是由隧道 **public hostname route** 自动生成的记录：先到 **Zero Trust → Networks → Tunnels** 里删掉/改掉这条 route，再回 DNS 建 A，避免被隧道配置覆盖回去。
   - **TTL 注意（一手依据）**：橙云记录的 TTL **强制 Auto = 300 秒，且不可编辑**（CF 文档原文：「By default, all proxied records have a TTL of Auto, which is set to 300 seconds. This value cannot be edited.」）⇒ **"先把 TTL 降到 60 再切"对 edu 不成立**；生效窗口 = 最长 300s + 递归/本机缓存。
3. **SSL/TLS 模式**：切完 DNS、证书就绪后设为 **Full (strict)**（若暂时只想先通，可先 Full；**不要**停 Flexible）。
4. 记下改动前的原值（本文 §1.1 已存档），作为回滚文本。

### Phase 2 证书
~~~bash
# cn（灰云直连，必须 DNS 已指向新机才有意义）
ssh prod-host 'certbot certonly --webroot -w /var/www/acme-challenge -d cn.edu.example.org --non-interactive --agree-tos -m <你的邮箱>'
# edu（CF 代理下，HTTP-01 经 CF 回源 :80；要求此刻 CF 能到源站 80，即 SSL 模式至少 Flexible/或记录已切）
ssh prod-host 'certbot certonly --webroot -w /var/www/acme-challenge -d edu.example.org --non-interactive --agree-tos -m <你的邮箱>'
ssh prod-host 'certbot renew --dry-run'
~~~
判据：`/etc/letsencrypt/live/{cn.,}edu.example.org/fullchain.pem` 存在；`renew --dry-run` 通过。
> 续期钩子：旧机有 `renewal-hooks/deploy/reload-nginx.sh`（续期后必须 reload，否则一直端着旧证书）。新机要照建一份。

### Phase 3 验证（§6 有逐条命令）
### Phase 4 收尾
- `scripts/health_check_alert.py`（仓库里有，`deploy_myedu.sh` 会 rsync 到 `/opt/edu-app/scripts/`）的 DNS 判据要更新：它现在断的是「`edu.example.org` 必须解析出 A 记录」（旧机灰云事故指纹）。**切 B 之后 edu 仍是橙云，这条判据语义要重新定义**（例如改为「解析结果 ∈ CF anycast 段」+「cn 必须等于新机 IP」）。
- 可把 `ufw` 的 80/443 收紧到 Cloudflare 段（**但 cn 灰云必须对全网开 443**，所以 443 只能全开；80 可选收紧）。

---

## 6. 怎么证明「中国线真的通了」

~~~bash
# ① DNS 指对了（从公共解析器）
dig +short A cn.edu.example.org @1.1.1.1        # 期望 203.0.113.11（且无 AAAA）
dig +short A cn.edu.example.org @8.8.8.8        # 期望同上

# ② 证书是给这个域名签的、且是 Let's Encrypt
openssl s_client -connect cn.edu.example.org:443 -servername cn.edu.example.org </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates

# ③ 走的是直连而不是 CF：响应头**不得**有 cf-ray（对比 edu 必须有）
curl -sS -D - -o /dev/null --noproxy '*' --max-time 20 https://cn.edu.example.org/web/login | grep -i -E '^(HTTP|cf-ray|server):'
curl -sS -D - -o /dev/null --noproxy '*' --max-time 20 https://edu.example.org/web/login       | grep -i -E '^(HTTP|cf-ray|server):'

# ④ 从这台中国本机测（绕开本机代理 TUN；旧档案里就是这么测的）
curl -sS -o /dev/null -w 'cn  code=%{http_code} time=%{time_total}\n' --noproxy '*' --interface en0 --max-time 25 https://cn.edu.example.org/
curl -sS -o /dev/null -w 'edu code=%{http_code} time=%{time_total}\n' --noproxy '*' --interface en0 --max-time 25 https://edu.example.org/

# ⑤ 源站侧：access.log 里必须是真实公网 IP（不是 127.0.0.1 / CF 段）
ssh prod-host 'tail -20 /var/log/nginx/access.log'
~~~

**判据汇总**：① 等于新 IP；② `issuer=Let's Encrypt`、`subject=CN=cn.edu.example.org`；③ cn **无** `cf-ray`、edu **有** `cf-ray`（这一条同时证明两条路没接错）；④ cn 成功且时延 < 2s（旧档案直连实测 0.65–0.69s）；⑤ 看到你的真实公网 IP。

**反例（控制组，今天实测过同一命令）**：现在 `cn.edu.example.org` 指向死 IP，同一条 curl 是
`curl: (28) Connection timed out after 15001 milliseconds`（http=000）。
⇒ 这条命令**能区分生死**，不是"回什么都算过"。若切换后仍是 000/超时，就是没通，不许报绿。

---

## 7. 回滚

| 项 | 回滚动作 | 结果 |
|---|---|---|
| edu 记录 | 改回原隧道记录（原值：CF 托管隧道 `70802e77-…cfargotunnel.com`，橙云） | 回到 **530/1033** 故障态（原状态本来就是坏的） |
| cn 记录 | 改回 `203.0.113.10` | 回到 **超时**（同样是坏的） |
| CF SSL 模式 | 改回改动前值（**改动前值未知，见 §8 未验证项**，切换前必须抄下来） | — |
| nginx | 删 `sites-enabled/edu-strcs` 与 `edu-cn*`，恢复 `default`，`nginx -t && systemctl reload nginx` | 秒级 |
| 证书 | 无副作用，可留着 | — |

> **回滚到"可用"的唯一途径是修好新机**，不是改 DNS 回去 —— 旧机数据与凭据都已不存在。

---

## 8. 待用户点头 / 待用户提供

1. **改 DNS**（本文全部动作）：edu 记录改 A（橙云）、cn 记录改 IP（灰云）。**必须由用户确认后执行**。
2. **CF 账号访问**：Zero Trust → Networks → Tunnels 看一眼 `70802e77` 是否还在；以及 DNS 页确认 edu 那条记录到底是"隧道 route 自动生成"还是手工 CNAME。**本机没有可用的 CF API token**（实测：本机 shell 历史里那个 Bearer 值调 `/user/tokens/verify` 与 DNS 列表接口都返回 **401 Authentication error**，故记录类型只能靠行为推断）。
3. **CF 侧 SSL/TLS 当前模式**：需用户在 SSL/TLS → Overview 抄下现值（回滚要用）。
4. **选 A 还是 B**（本方案推荐 B）；若选 A，需确认 VPN 之外的 Tunnel 编辑权限。
5. **新机是否恢复 xray/mtg**：决定 cn 走"HAProxy 分流"还是"nginx 直接 443"（§4.2）。

---

## 9. 未验证项（不许当结论用）

1. **CF 后台那条 edu 记录的原始形态**：无法验证（无 API token；dashboard 需用户）。本文的"隧道"定性来自 1033 一手文档 + 仓库档案 + 行为读数三方一致，**不是**从 CF 后台读到的记录类型。
2. **当前 zone SSL/TLS 模式**：未知（见 §8.3）。
3. **隧道 `70802e77` 是否仍存在于 CF 账号**：未知。
4. **certbot 真签发**：**未实测**（本机无指向它的域名，不能凭空签）；只实测了 certbot 4.0.0 已装、nginx/standalone 插件在、ACME 端点可达（200）。
5. **`certbot --nginx` 自动改写**：未实测；本方案改用手写配置 + `certonly`。
6. **切换后中国线路的真实丢包/时延**：未实测（现在打过去是超时）。旧档案里的对照数据（CF 2/5 成功 vs 直连 5/5）是 2026-09-24 的读数，**不能替代切换后的复测**。
7. **ufw 收紧到 CF 段**：未实测（本阶段建议全开）。
8. **`http2 on;` 与 Cloudflare 回源协议的实际协商**：配置语法已探针通过，**线上行为未实测**。
