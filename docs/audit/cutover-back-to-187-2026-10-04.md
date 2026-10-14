# 正式站切回 187（2026-10-04）

> 校长指令：「**切回去**」（把正式站从 201 切回续费后的旧机 187）。

## 一、为什么切回去没有代价（先量后动）

切换前实测两边的数据：

| | 201（换机后重建） | 187（旧机，数据完整） |
|---|---|---|
| `op_student` | **1** | **51** |
| `res_users` | **8** | **39** |
| `ir_attachment` | — | **545** |
| `op_session` | 216（**全部**是 09-24 后新建 = 演示/重建数据） | — |
| 最新写入 | **2026-08-28** | 2026-09-24 |

⇒ 201 上**没有任何 8 月之后被写过的真实业务数据**；切回 187 **不丢东西，反而是把数据找回来**。
（这也印证了「两份数据血缘不同、**不要合并**」的判断。）

## 二、机制：不是代理 A，而是**隧道**

换机方案（`docs/ops/migration/dns-and-tls-cutover.md`）当时记录 edu 走 Cloudflare Tunnel；实测确认：

- **187 上 `cloudflared` 在跑**（systemd active），隧道 `edu-tunnel-v2` = `70802e77-8b92-4888-b0f8-62f8a2e0fddb`，
  2026-10-04T06:06 注册连接，出口 IP `2a02:4780:5e:eacd::1`（= 187）；
- **187 的隧道配置本就是为 edu 准备的**（`/etc/cloudflared/config-v2.yml`）：
  ```yaml
  tunnel: 70802e77-…
  ingress:
    - hostname: edu.example.org
      service: http://localhost:80
  ```
- **201 上没有 cloudflared** ⇒ 换机时走的是「代理 A → 201」，隧道被 orphan；
- 187 上有**账号级凭据** `/root/.cloudflared/cert.pem` ⇒ `cloudflared` 可改 DNS 路由。

## 三、切换动作（一条命令）

```bash
# 在 187 上执行
cloudflared tunnel route dns --overwrite-dns \
  70802e77-8b92-4888-b0f8-62f8a2e0fddb edu.example.org
# 输出：INF Added CNAME edu.example.org which will route to this tunnel
```

**切换前先验证落点**：`curl -H "Host: edu.example.org" http://127.0.0.1:80/` → **200**（隧道要打的就是这里）。

## 四、验证（决定性证据）

从 Mac 打 `https://edu.example.org/` → 200、`/web/login` → 302，然后看**两台机器各自的日志**：

```
187 的容器日志（出现了我这次请求）：
  14:02:44  werkzeug: 203.0.113.9 - "GET / HTTP/1.1" 200
  14:02:46  werkzeug: 203.0.113.9 - "GET /web/login HTTP/1.1" 302
  14:03:24  werkzeug: 203.0.113.9 - "GET / HTTP/1.1" 200
  14:03:25  werkzeug: 203.0.113.9 - "GET /web/login HTTP/1.1" 302

201 的容器日志：**最近 3 分钟一条回源都没有**（对照通过）
```

⚠ 读日志时注意：**隧道是从本机连 nginx 的**，所以隧道回源在 187 的 nginx 日志里表现为 `127.0.0.1`，
不要把它当成「只有健康检查」——187 的 nginx 里每 5 分钟一次的 `127.0.0.1 "GET /"` 才是健康检查。

### 登录链路（db_name 修复的验证）

```
取 CSRF（跟随 302 到 /login）→ 用**错口令** POST /web/login
  -> 200，响应 18579 字节，仍是登录页（含 oe_login_form），404 计数 0
```
⇒ 「匿名页正常、登录后全站 404」的根因（缺 `db_name`，见 old-server-187-recovery 文档）**已消除**。

## 五、⚠ 还剩一条记录没改（需要 CF 后台或 API 令牌）

**`cn.edu.example.org` 仍是灰云 A → 203.0.113.11**（实测 `dig +short cn.edu.example.org A`）。
它是**中国直连**那条线；`cloudflared` 只能建隧道 CNAME，**改不了普通 A 记录** ⇒
需要有人在 Cloudflare 后台把它改回 **203.0.113.10**（或给我一个 API 令牌，我来改）。

## 六、回滚（如果需要退回 201）

`edu.example.org` 原值 = **A → 203.0.113.11，Cloudflare 代理（橙云）**。
回滚 = 在 Cloudflare 后台删掉现在的隧道 CNAME，重建上述 A 记录（201 仍在运行，随时可接）。