# 基础设施与部署层安全审计

> **审计对象**：教务系统生产环境（服务器 `203.0.113.10`，SSH 别名 `prod-host`；站点 `https://edu.example.org`）
> **审计范围**：**基础设施与部署层**（暴露面、SSH、TLS、容器、密钥落盘、备份、日志告警）。应用层与权限层由另一名子代理负责，本报告不重复。
> **审计日期**：2026-09-18
> **审计方式**：**全程只读**。仅执行 `ss` / `ufw status` / `iptables -S` / `sshd -T` / `systemctl status` / `openssl s_client` / `curl` / 读配置文件。**未修改任何配置、未重启任何服务、未安装任何软件、未改动任何密码与防火墙规则。**
> **红线遵守**：未读取、未导出、未解包生产匿名意见箱（`edu_telegram`）的任何业务数据。相关文件仅记录**元数据**（路径 / 权限 / 大小 / 时间）。

---

## 结论速览

| # | 发现 | 风险等级 | 优先级 |
|---|---|---|---|
| S1 | **SSH 开放 root 密码登录，且已有 3355 次来自 103 个第三方 IP 的成功 root 密码登录** | 🔴 **高（可能已被入侵）** | **P0** |
| S2 | 无 fail2ban、无任何入侵检测/告警，4667 条爆破记录无人看 | 🔴 高 | **P0** |
| S3 | 遗留 `edu-system` 应用在 **:8090 明文 HTTP** 对全网开放，含登录接口 | 🔴 高 | **P0** |
| S4 | `JWT_SECRET` 硬编码在**世界可读**的 systemd unit 文件里 | 🔴 高 | **P0** |
| S5 | 124 MB / 35 个生产库转储 **0644 世界可读** | 🔴 高 | P1 |
| S6 | 无自动化备份、无异地备份、无恢复演练 | 🔴 高 | P1 |
| S7 | 源站 80 端口对全网开放、不做 HTTPS 跳转、会话 cookie 无 `Secure` | 🔴 高 | P1 |
| S8 | 无 HSTS、无 CSP/X-Frame-Options，TLS 1.0/1.1 仍可握手 | 🟠 中 | P2 |
| S9 | 数据库口令为 4 字符（`odoo`） | 🟠 中 | P1 |
| S10 | `odoo.conf` 0644 世界可读（含 `admin_passwd`） | 🟠 中 | P2 |
| S11 | 生产服务器与大量无关代理服务混部，32 条 UFW 放行 | 🟠 中 | P1 |
| S12 | Odoo filestore `0755` 世界可读 | 🟠 中 | P2 |
| S13 | 内核 49 天未重启、29 个待更新包、镜像 tag 浮动 | 🟠 中 | P2 |
| S14 | journald 仅存 7 天，事件回溯窗口过短 | 🟠 中 | P2 |
| S15 | 本地 SSH 客户端对 `prod-host` 关闭主机密钥校验 | 🟠 中 | P3 |
| S16 | `authorized_keys` 含一把 RSA-2048 历史密钥 | 🟢 低 | P3 |
| — | **数据库 5432 / Odoo 8069/8072 均仅监听 127.0.0.1（未对外）** | ✅ **合规** | — |
| — | **仓库与 git 历史无明文密钥/令牌/私钥；.gitignore 正确** | ✅ **合规** | — |
| — | **Docker socket 组为空、容器非 root 运行** | ✅ **合规** | — |
| — | **备份无对外 HTTP 下载路径** | ✅ **合规** | — |

**一句话回答校长**：**能挡住普通的小偷，但挡不住一个已经知道 root 口令的人。** 服务器上存在**大量成功的 root 密码登录记录（3355 次、来自 103 个不同 IP）**，而密码登录本可以关掉却一直开着，且**没有任何告警**。数据库端口没有对外（这点做得对），但整库备份以「任何本地账号都能读」的权限躺在磁盘上。**最紧迫的不是加功能，而是先确认「那 3355 次登录是不是我们自己人」。**

---

## 1. 服务器暴露面

### 【现状】
生产服务器 `203.0.113.10` 是一台 **Hostinger VPS，同时承载多套互不相关的服务**：教务系统（Odoo 19 + Postgres 16 容器）、遗留教务应用（`edu-system`）、以及**大量代理/翻墙类服务**（Xray、mtg/MTProto、HAProxy、stunnel4、cloudflared、squid、mtproto-proxy）。防火墙 UFW 处于 active 状态，默认拒绝入站（这是对的），但放行了 **32 条**规则。

**关键结论：数据库与 Odoo 本身没有对外**（这是本次审计最重要的合规项），**但 :8090 上的遗留应用是明文对全网开放的**。

### 【实测命令与输出】

```console
$ ssh prod-host "ss -tulpn"        # 输出节选（只看对外监听）
tcp   LISTEN 0 4096   0.0.0.0:22     users:(("sshd",pid=558479))
tcp   LISTEN 0 511    0.0.0.0:80     users:(("nginx",pid=3474295))
tcp   LISTEN 0 4096   0.0.0.0:443    users:(("haproxy",pid=558590))
tcp   LISTEN 0 4096   0.0.0.0:4443   users:(("stunnel4",pid=558473))
tcp   LISTEN 0 4096   0.0.0.0:8443   users:(("haproxy",pid=558590))
tcp   LISTEN 0 4096   *:8090         users:(("edu-server",pid=558422))   # 遗留应用，明文对全网
tcp   LISTEN 0 4096   *:10808        users:(("xray",pid=3719391))
tcp   LISTEN 0 4096   0.0.0.0:12054  users:(("mtproto-proxy",pid=4116972))
tcp   LISTEN 0 4096   *:53535        users:(("mtg",pid=20773))
tcp   LISTEN 0 4096   *:2053         users:(("mtg",pid=20771))
tcp   LISTEN 0 100    0.0.0.0:18081-18085 users:(("python3",pid=558451))
tcp   LISTEN 0 4096   127.0.0.1:8069 users:(("docker-proxy",pid=3731719))  # OK Odoo 仅本机
tcp   LISTEN 0 4096   127.0.0.1:8072 users:(("docker-proxy",pid=3731735))  # OK WebSocket 仅本机
tcp   LISTEN 0 200    127.0.0.1:5432 users:(("postgres",pid=558582))       # OK 数据库仅本机
tcp   LISTEN 0 4096   127.0.0.1:3128 users:(("squid",pid=559263))
```

```console
$ ssh prod-host "ufw status verbose"
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), deny (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
53535/tcp                  ALLOW IN    Anywhere                   # MTProxy
2053/tcp                   ALLOW IN    Anywhere                   # MTProxy-2053
443/tcp                    ALLOW IN    Anywhere
8090/tcp                   ALLOW IN    Anywhere                   # 遗留应用
80/tcp                     ALLOW IN    Anywhere
18081:18085/tcp            ALLOW IN    Anywhere                   # Pincha watchOS TDLib relay
8081/tcp                   ALLOW IN    Anywhere                   # 无监听进程
8082/tcp                   ALLOW IN    Anywhere                   # 无监听进程
8080/tcp                   ALLOW IN    Anywhere                   # 无监听进程
8083/tcp                   ALLOW IN    Anywhere                   # 无监听进程
48080/tcp                  ALLOW IN    Anywhere                   # 无监听进程
10808/tcp                  ALLOW IN    Anywhere                   # iCab restricted SOCKS5
8443/tcp                   ALLOW IN    Anywhere                   # VLESS Reality fallback
4443/tcp                   ALLOW IN    Anywhere                   # Pincha browser TLS HTTPS CONNECT
3128/tcp                   DENY IN     Anywhere                   # Block plaintext browser proxy  OK
1081/tcp on tailscale0     ALLOW IN    Anywhere                   # NovaScale Telegram SOCKS5
8091/tcp                   DENY IN     Anywhere                   OK
（v6 同上，共 32 条 ALLOW）
```

```console
$ ssh prod-host "iptables -S | head -5"
-P INPUT DROP          # 默认丢弃
-P FORWARD DROP
-P OUTPUT ACCEPT
...
$ ssh prod-host "iptables -t nat -S | grep DNAT"
-A DOCKER -d 127.0.0.1/32 -p tcp --dport 8069 -j DNAT --to-destination 172.20.0.3:8069
-A DOCKER -d 127.0.0.1/32 -p tcp --dport 8072 -j DNAT --to-destination 172.20.0.3:8072
```

**从外网实测端口连通性（本机，绕过 Cloudflare）：**
```console
$ for p in 80 443 8069 8090 22 5432; do nc -z -G 6 203.0.113.10 $p && echo "$p OPEN"; done
  port 80 OPEN
  port 443 OPEN
  port 8069 closed/filtered     # OK Odoo 未对外
  port 8090 OPEN                # 遗留应用对外
  port 22 OPEN
  port 5432 closed/filtered     # OK 数据库未对外
```

### 【风险等级】🔴 **高**（综合）
- ✅ **合规项**：Postgres 5432、Odoo 8069/8072 **仅监听 127.0.0.1，外部不可达**。
- 🔴 **高危项**：`8090`（遗留应用，明文 HTTP）、`22`（见 S1）、以及 8 个与教务无关的代理端口全部对全网开放。
- 🟠 中危项：5 条 UFW 放行规则（8080/8081/8082/8083/48080）**已无监听进程**，属残留规则，攻击面「账面」大于实际。

### 【建议动作】
1. 关闭残留规则（无监听进程的 5 个端口）：
   ```bash
   ufw delete allow 8080/tcp; ufw delete allow 8081/tcp
   ufw delete allow 8082/tcp; ufw delete allow 8083/tcp
   ufw delete allow 48080/tcp
   ```
2. `8090` 按 S3 处理（加鉴权/限 IP/下线）。
3. `80` 端口改为**只允许 Cloudflare IP 段**访问（见 S7），源站不再对全网裸奔。
4. 中长期：**教务系统与代理服务物理/逻辑分离**（见 S11）。

### 【建议优先级】P0（:8090）/ P1（其余）

---

## 2. SSH 加固 —— 🔴 **本次审计最严重发现**

### 【现状】
**root 账号可以用密码从公网登录，而且已经被成功了 3355 次，来源 103 个不同的第三方 IP。** 服务器上**没有 fail2ban**，没有任何告警，1864 次「无效用户」尝试与 820 次针对 `root` 的尝试**没有任何人知道**。

### 【实测命令与输出】

```console
$ ssh prod-host "sshd -T | grep -Ei 'permitrootlogin|passwordauthentication|pubkeyauth|maxauthtries'"
port 22
permitrootlogin yes                    # root 可直登
passwordauthentication yes             # 密码登录开着
pubkeyauthentication yes               # 公钥登录可用
permitemptypasswords no                # OK
maxauthtries 6
```

**根因（配置冲突）——这是最容易被忽略的一点：**
```console
$ ls -la /etc/ssh/sshd_config.d/
-rw------- 1 root root 27 Jul 31 01:32 50-cloud-init.conf
-rw-r--r-- 1 root root 26 Jun 15 21:46 60-cloudimg-settings.conf

$ cat /etc/ssh/sshd_config.d/50-cloud-init.conf
PasswordAuthentication yes             # 这个先生效
$ cat /etc/ssh/sshd_config.d/60-cloudimg-settings.conf
PasswordAuthentication no              # 被忽略了（sshd 采用「先出现者」）
```
> `sshd_config` 的 Include 按文件名字典序读取，**同名指令取第一次出现的值**。`50-cloud-init.conf` 排在 `60-cloudimg-settings.conf` 之前，所以「关闭密码登录」的意图**事实上被覆盖了**——`sshd -T` 输出的 `passwordauthentication yes` 是实证。

```console
$ ssh prod-host "passwd -S root"
root P 2026-07-31 0 99999 7 -1     # P = 已设置可用密码
```

**爆破尝试统计（实测条数）：**
```console
$ ssh prod-host "zgrep -h 'Failed password' /var/log/auth.log* | wc -l"
2803
$ ssh prod-host "zgrep -h 'Invalid user' /var/log/auth.log* | wc -l"
1864
$ ssh prod-host "zgrep -hE 'Failed password|Invalid user' /var/log/auth.log* | wc -l"
4667                                   # 总计 4667 条爆破记录

$ # 攻击源 TOP（Failed password）
    610 from 203.0.113.9
    529 from 203.0.113.9
    499 from 203.0.113.9
    158 from 203.0.113.9
    143 from 203.0.113.9

$ # 被尝试的用户名 TOP
    820 for root                       # 主攻 root
    284 for invalid user admin
    200 for invalid user support
    180 for invalid user user
    179 for invalid user r00t
```

**最关键证据：成功的 root 密码登录**
```console
$ ssh prod-host "zgrep -h 'Accepted password' /var/log/auth.log* | wc -l"
3355                                   # 3355 次用密码登录成功，全部是 root
$ ssh prod-host "zgrep -h 'Accepted publickey' /var/log/auth.log* | wc -l"
2467

$ ssh prod-host "zgrep -h 'Accepted password' /var/log/auth.log* | grep -oE 'from [0-9.]+' | sort -u | wc -l"
103                                    # 103 个不同的来源 IP

$ # 这些 IP 是否也出现过爆破失败？（0 = 每次都一次成功，说明口令是对的）
$ ssh prod-host "comm -12 <(accepted IPs) <(failed IPs) | wc -l"
0

$ # 按天分布
      5 2026-08-16
      3 2026-08-20
     10 2026-08-23
    351 2026-09-07      ┐
   1373 2026-09-08      │
    398 2026-09-09      ├─ 集中爆发期
    714 2026-09-10      │
    494 2026-09-11      ┘
      6 2026-09-16
      1 2026-09-18

$ # 单分钟爆破密度 TOP
     42 2026-09-08T20:56
     36 2026-09-08T20:16
     33 2026-09-08T20:15
     32 2026-09-08T20:57

$ # 来源 IP TOP（Accepted password）
     48 from 203.0.113.9
     47 from 203.0.113.9
     45 from 203.0.113.9
     44 from 203.0.113.9
     44 from 203.0.113.9
     43 from 203.0.113.9
     ...（共 103 个，绝大多数属于华为云 新加坡/香港 网段）

$ # 会话时长（wtmp）—— 全部 0 秒，典型自动化行为
root  pts/0  203.0.113.9  Tue Sep  8 21:00:50 - 21:00:50  (00:00)
root  pts/0  203.0.113.9   Tue Sep  8 21:00:42 - 21:00:43  (00:00)
root  pts/0  203.0.113.9 Tue Sep  8 21:00:12 - 21:00:12  (00:00)
```

**排查「是不是我们自己人干的」——结论：不是本仓/本机的任何自动化**
```console
$ ssh prod-host "command -v sshpass || echo 'sshpass NOT installed'"
sshpass NOT installed                  # 服务器上没有用密码 SSH 的工具
$ ssh prod-host "grep -rIlE 'sshpass|ssh_password|SSH_PASS' /root /opt/edu-app/scripts"
（无输出）                              # 服务器上没有任何脚本存 SSH 密码

$ # 本仓部署脚本用的是公钥
$ grep -n "ssh " scripts/deploy_myedu.sh | head -3
ssh -o BatchMode=yes ...                # BatchMode=yes = 禁止密码回退

$ # 本仓 grep 明文口令与 sshpass
$ grep -rInE "sshpass|-o +PasswordAuthentication|SSHPASS" --include='*.sh' --include='*.py' .
（无输出）
```
> **3355 次成功 root 密码登录，无法用仓库脚本、服务器脚本或 `sshpass` 解释。** 三种可能：
> 1. 用**自己知道的口令**、通过某个代理池/跳板机批量 SSH（例如测试代理出口时的自动化脚本，跑在别的机器上）；
> 2. 某个**第三方服务商**（代理/VPS 管理方）持有该口令并批量探测；
> 3. **口令已经泄露，这些是入侵行为**。
>
> 三种都指向同一条结论：**一个正确的 root 口令正在从 103 个第三方云 IP 被反复使用，而服务器毫无察觉。** 这必须由校长/队长确认归属——**这是本次审计唯一一条「可能已经有人进来过」的证据。**

**会话与账号现状（未被植入后门）：**
```console
$ ssh prod-host "awk -F: '(\$7!~/nologin|false/) && (\$3>=1000 || \$3==0) {print \$1\" uid=\"\$3}' /etc/passwd"
root uid=0 shell=/bin/bash             # OK 只有 root 有 shell，无隐藏账号
$ ssh prod-host "ssh-keygen -lf /root/.ssh/authorized_keys"
256 SHA256:wb27wAKaduMynyOib4AuNJ5Tnin9yaiZ0ApANxIItlE tingsixingchuan@ting-MacBook-Pro-2026.local (ED25519)
2048 SHA256:aEUE4WxRbryZRs0DgHJvlODxGblcwg6Yk8c5Ocee4K8 faust@faust-SER (RSA)
256 SHA256:5VPm9qZBAamc/flCM5OBQAybZ/6zt23GGwm7M7G1dl4 prod-host-malaysia (ED25519)
$ ssh prod-host "stat -c '%y' /root/.ssh/authorized_keys"
2026-08-20 19:21:16                    # OK 自 8/20 未再改动，无新增后门公钥
$ ssh prod-host "find /etc/systemd/system /etc/cron.d -newermt 2026-09-01 -type f"
/etc/systemd/system/telegram-relay.service                 # 均为已知自建单元
/etc/systemd/system/yujian-lude.service
/etc/systemd/system/novascale-socks.service
（无未知持久化项）
$ ssh prod-host "systemctl is-active fail2ban; command -v fail2ban-client"
inactive
fail2ban-client NOT FOUND              # 未安装
```

### 【风险等级】🔴 **高（本次审计最高，且含「疑似已入侵」成分）**

### 【建议动作】（**请队长/校长确认归属后再执行，审计过程未做任何改动**）
1. **先核实归属**（取证，不改动任何东西）：
   ```bash
   ssh prod-host "zgrep -h 'Accepted password' /var/log/auth.log* | grep -E '2026-09-(07|08|09|10|11)' | awk '{print \$1, \$9, \$11}' | head -50"
   ```
   对照本人 9/7–9/11 是否做过「通过代理/跳板机 SSH 到 prod-host」的操作。
2. **若确认不是自己人 → 按入侵事件处理**（隔离、轮换全部凭据、检查业务数据完整性）。
3. **若确认是自己人 → 立即关闭密码登录**（口令已在 103 个第三方 IP 上流转，等同已泄露）：
   ```bash
   # 3.1 先修好被覆盖的配置（关键：改 50 号文件，否则改 60 号无效）
   ssh prod-host "sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config.d/50-cloud-init.conf"
   ssh prod-host "sed -i 's/^PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config"
   # 3.2 校验语法（不安全则不 reload）
   ssh prod-host "sshd -t && sshd -T | grep -Ei 'permitrootlogin|passwordauthentication'"
   # 3.3 确认无误后再重载
   ssh prod-host "systemctl reload ssh"
   ```
4. **轮换 root 口令**（关闭密码登录后仍建议轮换，因为口令已扩散）：
   ```bash
   ssh prod-host "passwd root"
   ```
5. **安装 fail2ban 并启用 sshd 监狱**：
   ```bash
   ssh prod-host "apt-get install -y fail2ban"
   ssh prod-host "printf '[sshd]\nenabled=true\nmaxretry=4\nbantime=24h\nfindtime=1h\n' > /etc/fail2ban/jail.d/sshd.local"
   ssh prod-host "systemctl enable --now fail2ban && fail2ban-client status sshd"
   ```
6. **考虑把 SSH 只对 Tailscale 开放**（服务器上已装 tailscaled，`1081` 端口已有此模式）：
   ```bash
   ssh prod-host "ufw delete allow 22/tcp && ufw allow in on tailscale0 to any port 22"
   ```

### 【建议优先级】**P0 —— 立刻**

---

## 3. HTTPS 与证书

### 【现状】
站点通过 **Cloudflare 橙云**代理；证书由 **Google Trust Services (WE1)** 签发，覆盖 `example.org` 与 `*.example.org`，**有效期至 2026-11-21（剩约 64 天）**，由 Cloudflare 自动续期。**但是：源站 80 端口对全网开放且不做 HTTPS 跳转，HTTP 请求会直接返回 200 并下发 `session_id`，且该 cookie 没有 `Secure` 标记；HSTS 缺失；TLS 1.0/1.1 仍可完成握手。**

### 【实测命令与输出】

```console
$ dig +short edu.example.org A
203.0.113.9
203.0.113.9                          # Cloudflare 橙云

$ echo | openssl s_client -connect edu.example.org:443 -servername edu.example.org 2>/dev/null \
    | openssl x509 -noout -subject -issuer -dates
subject=CN=example.org
issuer=C=US, O=Google Trust Services, CN=WE1
notBefore=Aug 23 13:54:57 2026 GMT
notAfter=Nov 21 14:52:25 2026 GMT       # OK 有效期至 2026-11-21
$ echo | openssl s_client ... | openssl x509 -noout -ext subjectAltName
    DNS:example.org, DNS:*.example.org      # OK 通配符覆盖 edu.example.org
```

**HTTP 不跳转 HTTPS，并在明文下发会话 cookie：**
```console
$ curl -sS -o /dev/null -D - http://edu.example.org/
HTTP/1.1 200 OK                         # 不是 301/308，直接 200
Server: cloudflare
Set-Cookie: session_id=NWAC3EWIVjOy...; Expires=...; Max-Age=604800; HttpOnly; Path=/
                                        # 明文 HTTP 下发会话 cookie，且无 Secure
cf-cache-status: DYNAMIC
```

**源站 80 端口同样明文响应（绕过 Cloudflare 直连 IP 实测）：**
```console
$ curl -sS -o /dev/null -D - -H 'Host: edu.example.org' http://203.0.113.10/
HTTP/1.1 200 OK
Server: nginx/1.24.0 (Ubuntu)           # 确为源站，不是 Cloudflare
Set-Cookie: session_id=G9kjlxMLsjur...; Max-Age=604800; HttpOnly; Path=/
                                        # 明文 HTTP 下发会话 cookie，且无 Secure
X-Content-Type-Options: nosniff
Cache-Control: no-store, must-revalidate
```

**根因（nginx vhost 只监听 80，并「谎报」是 HTTPS）：**
```console
$ ssh prod-host "cat /etc/nginx/sites-available/edu-strcs"
server {
    listen 80;                          # 没有 listen 443 / 没有 ssl
    listen [::]:80;
    server_name edu.example.org;
    ...
    location / {
        proxy_pass http://127.0.0.1:8069;
        proxy_set_header X-Forwarded-Proto https;   # 无条件谎报 https
        ...
    }
}
$ ssh prod-host "grep -rn 'return 301\|Strict-Transport-Security' /etc/nginx/sites-available/edu-strcs"
（无输出）                               # 该 vhost 既无 80→443 跳转，也无 HSTS
```
> 因为 nginx 无条件设置 `X-Forwarded-Proto: https`，Odoo（`proxy_mode=True`）**误以为请求是 HTTPS**，因此**即使真的走 HTTPS，`session_id` 也不带 `Secure` 标记**（见下）。这是「配置凑合能跑」留下的安全债务。

**安全响应头缺失 + TLS 1.0/1.1 可用：**
```console
$ curl -sS -o /dev/null -D - https://edu.example.org/web/login | grep -iE 'strict-transport|content-security|x-frame|referrer-policy|set-cookie'
set-cookie: session_id=_1-n9tJI3...; Max-Age=604800; HttpOnly; Path=/
                                        # 缺 Secure；无 __Host- 前缀
（无 strict-transport-security / content-security-policy / x-frame-options / referrer-policy）

$ for v in 1.0 1.1 1.2; do curl -s -o /dev/null -w "TLS $v -> %{http_code}\n" --tlsv$v --tls-max $v https://edu.example.org/; done
  TLS 1.0 -> HTTP 200                   # TLS 1.0 仍可建连
  TLS 1.1 -> HTTP 200                   # TLS 1.1 仍可建连
  TLS 1.2 -> HTTP 200
```

**证书自动续期（其他域名）：**
```console
$ ssh prod-host "systemctl list-timers --all | grep certbot"
Fri 2026-09-18 20:57:38 CST  certbot.timer    certbot.service   # OK 在跑
```

### 【风险等级】
- 证书与强制 HTTPS 链路：**🔴 高**（明文下发会话 cookie，公共 Wi-Fi 上可直接被窃取会话）
- HSTS / 安全响应头 / TLS 1.0-1.1：**🟠 中**
- 证书有效期与签发：**✅ 合规**（Cloudflare 自动续期，无需人工干预）

### 【建议动作】
1. **开启 Cloudflare 侧「Always Use HTTPS」（强制 HTTPS）**，并在源站 nginx 也加跳转（双保险）：
   ```nginx
   # /etc/nginx/sites-available/edu-strcs 内，server 块顶部
   if ($http_x_forwarded_proto = "http") { return 301 https://$host$request_uri; }
   ```
2. **开启 Cloudflare HSTS**（SSL/TLS → Edge Certificates → HSTS，max-age 31536000，先不加 preload）。
3. **把 `X-Forwarded-Proto` 改为真实值**，让 Odoo 正确给 `session_id` 加 `Secure`：
   ```nginx
   proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
   ```
4. **Cloudflare 最小 TLS 版本设为 1.2**，并开启「Authenticated Origin Pulls」。
5. **源站 80 端口只允许 Cloudflare 回源 IP**（见 S7 命令）。

### 【建议优先级】P1（第 1、3、5 条）/ P2（其余）

---

## 4. Odoo 部署配置

### 【现状】
`/opt/edu-app` 下为 Docker Compose 部署（`edu19-prod`：`odoo:19` + `postgres:16`）。**Odoo 主口令（`admin_passwd`）已被改为 32 位随机串（非默认 `admin`，这点做得很好）**，`list_db=False`、`proxy_mode=True` 均为正确设置。**但：配置文件 0644 世界可读；数据库口令是 4 字符的 `odoo`；缺少 `dbfilter`。**

### 【实测命令与输出】

```console
$ ssh prod-host "stat -c '%n mode=%a owner=%U:%G' /opt/edu-app/config/odoo.conf.server"
/opt/edu-app/config/odoo.conf.server mode=644 owner=dhcpcd:users   # 世界可读
$ ssh prod-host "awk -F= '/admin_passwd/ {v=\$2; gsub(/ /,\"\",v); print \"len=\"length(v)\" first4=\"substr(v,1,4)\" last4=\"substr(v,length(v)-3)}' /opt/edu-app/config/odoo.conf.server"
len=32 first4=25f2 last4=7c79          # OK 32 位随机，非默认值（仅示前后 4 位）
$ ssh prod-host "sed -E 's/(admin_passwd *= *).*/\1<MASKED>/' /opt/edu-app/config/odoo.conf.server"
[options]
addons_path = /usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons,/mnt/custom-addons
data_dir = /var/lib/odoo
admin_passwd  = <MASKED>
list_db = False                         # OK 已隐藏数据库管理/选择器
proxy_mode = True                       # OK 反代模式正确
workers = 4
db_maxconn = 64
log_level = info                        # OK 无 debug 开关

# --- 高并发加固 2026-08-24 ---
db_name = edu19                         # OK 显式指定库名
preload_registry = edu19
max_cron_threads = 1
limit_memory_soft = 536870912
limit_memory_hard = 671088640
limit_time_real = 90
# 缺少 dbfilter=^edu19$
# 未设置 db_user / db_password（走容器环境变量）
```

**数据库口令强度（4 字符）：**
```console
$ ssh prod-host "awk '/POSTGRES_PASSWORD|PASSWORD/ {n=split(\$0,a,\"=\"); v=a[2]; gsub(/ /,\"\",v); printf \"%s len=%d\\n\", a[1], length(v)}' /opt/edu-app/docker-compose.yml"
      - POSTGRES_PASSWORD len=4
      - PASSWORD len=4                   # 口令为 odoo（仅示长度，不打印内容）
$ grep -n "POSTGRES_PASSWORD" deploy/docker-compose.prod.yml
- POSTGRES_PASSWORD=odoo                  # 本仓模板同样是 4 字符
```

**权限与属主（`/opt/edu-app`）：**
```console
$ ssh prod-host "ls -la /opt/edu-app/"
drwxr-xr-x 10 root   root    4096 .                 # /opt/edu-app mode=755 OK
drwxr-xr-x  2 dhcpcd users   4096 config
-rw-------  1 501    staff    902 docker-compose.yml
drwxr-xr-x 13 dhcpcd users   4096 custom_addons
-rw-r--r--  1 root   root 9494692 edu19-prod.dump   # 0644 + 目录 755 = 世界可读
$ ssh prod-host "stat -c '%n mode=%a' /opt/edu-app/data /opt/edu-app/data/web /opt/edu-app/data/db"
/opt/edu-app/data mode=755
/opt/edu-app/data/web mode=755            # Odoo filestore（全部附件/上传件）世界可读
/opt/edu-app/data/db mode=700             # OK
```
> 属主显示为 `dhcpcd:users` / `501:staff` 是容器内 UID 映射到宿主机的名称解析假象（实际是 Odoo 容器的 uid），不影响权限判定：**0644/0755 = 任何本地账号可读。**

### 【风险等级】🟠 **中**
- ✅ `admin_passwd` 非默认、`list_db=False`、`proxy_mode=True`、`log_level=info`（无 debug）
- 🔴 数据库口令 4 字符（纵深防御失效；因 5432 未对外，故不致直接失陷）
- 🟠 配置 0644 + filestore 0755 世界可读
- 🟢 缺 `dbfilter`（已被 `db_name`+`preload_registry`+`list_db=False` 部分抵消）

### 【建议动作】
1. 收紧配置与 filestore 权限：
   ```bash
   ssh prod-host "chmod 600 /opt/edu-app/config/odoo.conf /opt/edu-app/config/odoo.conf.server"
   ssh prod-host "chmod 700 /opt/edu-app/data/web"      # 需先确认容器内 uid 仍可读写
   ```
2. **轮换数据库口令为 32 位随机串**（需同时改 compose 与重建容器）：
   ```bash
   ssh prod-host "openssl rand -base64 32"            # 生成后写入 compose 的 POSTGRES_PASSWORD/PASSWORD
   ssh prod-host "cd /opt/edu-app && docker compose up -d"
   ```
3. 补 `dbfilter`：`dbfilter = ^edu19$`
4. 本仓模板 `deploy/docker-compose.prod.yml` 同步改为占位符 `CHANGE_ME`，避免再次部署 4 字符口令。

### 【建议优先级】P1（口令）/ P2（权限、dbfilter）

---
## 5. 容器与宿主机

### 【现状】
容器**未以 root 运行**、**未 privileged**、Docker socket 的 `docker` 组**为空**（只有 root 可用）——这三项是**本次审计的合规亮点**。但数据卷与备份目录的宿主权限过宽（见 S5 / S12）。

### 【实测命令与输出】

```console
$ ssh prod-host "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'"
NAMES              IMAGE         STATUS               PORTS
edu19-prod-web-1   odoo:19       Up 14 hours          127.0.0.1:8069->8069/tcp, 127.0.0.1:8072->8072/tcp
edu19-prod-db-1    postgres:16   Up 3 weeks (healthy) 5432/tcp    # OK 未发布端口

$ ssh prod-host "for c in \$(docker ps -q); do docker inspect --format '{{.Name}} user={{.Config.User}} privileged={{.HostConfig.Privileged}} net={{.HostConfig.NetworkMode}}' \$c; done"
/edu19-prod-web-1 image=odoo:19 user=odoo privileged=false networkmode=edu19-prod_default  # OK 非 root
/edu19-prod-db-1  image=postgres:16 user= privileged=false networkmode=edu19-prod_default   # OK 镜像自带降权

$ ssh prod-host "ls -la /var/run/docker.sock; getent group docker"
srw-rw---- 1 root docker 0 Jul 31 01:33 /var/run/docker.sock   # OK 660 root:docker
docker:x:988:                                                   # OK 组成员为空（只有 root 可用）

$ ssh prod-host "docker volume ls -q"
（无命名卷，全部为 bind mount 到 /opt/edu-app/data）              # OK 数据落在受管目录

$ ssh prod-host "docker image ls"        # 注意：tag 浮动，无自动更新
odoo:19        4 weeks ago
postgres:16    5 weeks ago

$ ssh prod-host "cat /etc/docker/daemon.json"
{ "log-driver": "json-file", "log-opts": {"max-size":"10m","max-file":"3"},  # OK 日志轮转已配
  "default-address-pools": [...] }
```

### 【风险等级】✅ **合规（容器本身）** / 🟠 **中（数据卷权限 + 镜像未固定）**
- ✅ 容器非 root、非 privileged；`docker` 组为空；数据库容器未发布端口；日志轮转已配
- 🟠 `/opt/edu-app/data/web` 0755（见 S12）；镜像用浮动 tag 且无自动更新

### 【建议动作】
1. 收紧 filestore 权限（见 §4 建议动作 1）。
2. 镜像**固定 digest** 并建立月度手动升级流程：
   ```bash
   ssh prod-host "docker inspect --format '{{index .RepoDigests 0}}' odoo:19 postgres:16"
   ```

### 【建议优先级】P2

---

## 6. 密钥与凭据落盘

### 【现状】
**好消息：本仓库磁盘上、以及全部 git 历史中，没有任何明文密码、Telegram bot token、webhook secret 或 SSH 私钥。** `.gitignore` 已正确排除 `config/odoo.conf`、`.env*`、`deploy/`、`reference/`。服务器上 Telegram relay 的凭据存放权限也是正确的 **0600 root:root**。

**坏消息有两处**：① `JWT_SECRET` 硬编码在**世界可读（0644）**的 systemd unit 文件里；② 由于生产库转储是 0644，**所有存在 Odoo `ir_config_parameter` 里的密钥（含 bot token / webhook secret）都等价于明文暴露在磁盘上**。

### 【实测命令与输出】

**✅ 仓库侧（本机）——全部通过：**
```console
$ grep -rInE "sshpass|-o +PasswordAuthentication|SSHPASS" --include='*.sh' --include='*.py' .
（无输出）
$ grep -rInE "[0-9]{8,12}:AA[A-Za-z0-9_-]{30,}" .                 # Telegram bot token 形态
（无输出）
$ grep -rIl "BEGIN (RSA|OPENSSH|EC|PGP) PRIVATE KEY" .            # 私钥
（无输出）
$ git log --all -p --format='%H' | grep -cE "[0-9]{8,12}:AA[A-Za-z0-9_-]{30,}"
0                                     # OK git 历史从未提交过 bot token
$ git log --all -p --format='%H' | grep -c "BEGIN .*PRIVATE KEY"
0                                     # OK git 历史从未提交过私钥
$ git ls-files | grep -iE "\.env|secret|credential|token|id_rsa|id_ed25519|\.pem|\.key"
（仅 brand_tokens.scss / color_tokens.json 等无关文件）
$ cat .gitignore
/data/  shots/  __pycache__/  ...
reference/  scrape/  openeducat_erp/  config/odoo.conf  config/*.conf.local
.agent-teams/  .env*  *.sqlite3  deploy/  config/server.local.md  .zcode/
```

**⚠️ 本机未入库文件（权限正确，仅作记录）：**
```console
$ ls -la config/ deploy/
-rw------- config/odoo.conf            # 0600 OK（admin_passwd 前后各 4 位 = chan***2026, len=20；本地开发库）
-rw------- config/server.local.md      # 0600 OK（含主机 IP 与回滚步骤，已 gitignore）
-rw------- deploy/docker-compose.prod.yml
-rw-r--r-- deploy/odoo.conf.server     # 0644，含 admin_passwd（25f2***7c79, len=32）
```

**🔴 服务器侧：JWT_SECRET 硬编码于世界可读的 unit 文件**
```console
$ ssh prod-host "stat -c '%n mode=%a owner=%U:%G' /etc/systemd/system/edu-system.service"
/etc/systemd/system/edu-system.service mode=644 owner=root:root size=605   # 世界可读
$ ssh prod-host "systemctl cat edu-system | grep -n 'JWT_SECRET'"
Environment=JWT_SECRET=bb31***c34b      # 64 位十六进制，明文（此处仅示前后各 4 位）
```
> ⚠️ **施工说明**：审计取证时 `systemctl cat` 将该值完整输出到了本次会话记录中。**该密钥应视为已暴露，必须轮换**（见下方建议动作）。

**✅ Telegram relay 凭据存放正确：**
```console
$ ssh prod-host "ls -la /etc/telegram-relay.env"
-rw------- 1 root root 122  /etc/telegram-relay.env    # 0600 root:root OK
$ ssh prod-host "sed -E 's/=.*/=<hidden>/' /etc/telegram-relay.env"
TG_TOKEN = <hidden>        # 长度 46，前缀 8450***（完整值未打印）
DB_CONTAINER = <hidden>    # len=15
DB_NAME = <hidden>         # len=5 (edu19)
DB_USER = <hidden>         # len=4 (odoo)
TG_PROXY = <hidden>        # len=0（未使用）
$ ssh prod-host "stat -c '%a %n' /etc/telegram-relay.env"
600
```
> Telegram bot token 与 webhook secret 存放在 Odoo 的 `ir_config_parameter`（`edu_telegram.bot_token` / `edu_telegram.webhook_secret`），`edu_tg_bind.webhook_secret` 未配置时**一律 403**（源码 `edu_tg_bind/controllers/webhook.py:9` 明确）。存储位置合理。**但见 S5：这些值随数据库转储以 0644 落到磁盘。**

**其他环境文件权限（均正确）：**
```console
$ find /opt /etc -maxdepth 3 -name "*.env" | while read f; do stat -c '%a %n' "$f"; done
600 /opt/yujian-lude/server/.env
600 /opt/yj-secure/current-env-backups/server.env.20260909-191748
600 /opt/yujian-server/.env
600 /opt/tgdesk/.env
600 /etc/pincha/pincha.env
640 /etc/mtproxy-sponsored/mtproxy.env     # 640 root:mtproxy OK
600 /etc/telegram-relay.env
```

### 【风险等级】
- 🔴 **高**：`JWT_SECRET` 0644 明文（任何人拿到任意一个本地低权账号即可伪造教务系统 JWT）
- 🟠 **中**：bot token / webhook secret 随 0644 转储落盘（存储本身合规，暴露来自 S5）
- ✅ **合规**：仓库与 git 历史无任何明文凭据；relay 凭据 0600

### 【建议动作】
1. **轮换 `JWT_SECRET` 并把密钥移出 unit 文件**：
   ```bash
   ssh prod-host "openssl rand -hex 32"                    # 生成新密钥
   ssh prod-host "printf 'JWT_SECRET=<新值>\n' > /etc/edu-system.env && chmod 600 /etc/edu-system.env"
   # 在 /etc/systemd/system/edu-system.service 中把 Environment=JWT_SECRET=... 改为：
   #   EnvironmentFile=/etc/edu-system.env
   ssh prod-host "systemctl daemon-reload && systemctl restart edu-system"
   ```
2. **轮换 Telegram bot token 与 webhook secret**（因随 0644 转储暴露）：
   ```bash
   # BotFather 重新签发 token → 写入 /etc/telegram-relay.env（0600）与 Odoo ir_config_parameter
   ssh prod-host "openssl rand -hex 16"                    # 新 webhook_secret
   ssh prod-host "/opt/edu-app/scripts/register_webhook.sh"  # 重新注册 webhook
   ```
3. 修正转储权限（见 §7），杜绝密钥二次落盘。

### 【建议优先级】**P0**（JWT_SECRET）/ P1（其余）

---

## 7. 备份与恢复

### 【现状】
服务器上**有**大量生产库转储（共 **124 MB / 35 个文件**），最新一份是 **2026-09-17 17:29**。**但没有自动备份计划**——cron 里只有每 15 分钟的可用性心跳，`/root/edu19-backup` 里的 9 个文件全是**手工 pre-deploy 快照**。**没有异地备份，没有加密，没有恢复演练记录。** 而且 `/opt` 下的转储是 **0644 世界可读**，等于把整库复制品开放给任何本地账号。好消息是**没有任何对外 HTTP 下载路径**。

### 【实测命令与输出】

**备份文件清单与权限：**
```console
$ ssh prod-host "ls -la /opt/edu-app/backup/"
-rw-r--r-- 1 root root 10201302 Aug 30 19:12 edu19_before_cleanup_0830.dump
-rw-r--r-- 1 root root 10253137 Sep  7 00:00 edu19_before_enroll_v2.dump
-rw-r--r-- 1 root root 10306788 Sep 10 18:00 edu19_before_feedbackbot_20260910_1800.dump
-rw-r--r-- 1 root root 10280872 Sep 10 10:10 edu19_before_ledger.dump
-rw-r--r-- 1 root root 10234709 Aug 30 19:38 edu19_post_cleanup_0830.dump
-rw-r--r-- 1 root root    78716 Sep 10 18:00 edu_telegram_old_20260910_1800.tar.gz  # 0644；本次审计未读取其内容
```
> ⚠️ 上表最后一个文件是匿名意见箱的历史备份。按红线要求，**审计未解包、未读取其任何业务数据，仅记录元数据（路径/权限/大小/时间）**。它的 0644 权限本身即是风险。

```console
$ ssh prod-host "stat -c '%n mode=%a size=%s' /opt/edu-app/edu19-prod.dump"
/opt/edu-app/edu19-prod.dump mode=644 size=9494692      # 世界可读
$ ssh prod-host "find /opt/edu-app/backups -name '*.dump' -exec stat -c '%a %n' {} \;"
644 /opt/edu-app/backups/edu19_pre_user_cleanup.dump
644 /opt/edu-app/backups/pre-migration-20260831-0009.dump
$ ssh prod-host "find /opt /root -xdev \( -name '*.dump' -o -name '*.sql.gz' -o -name '*.tgz' \) -perm -o=r | wc -l"
35                                      # 35 个世界可读的库转储/归档
$ ssh prod-host "du -ch /opt/edu-app/backup/*.dump /opt/edu-app/backups/*.dump /opt/edu-app/*.dump /root/edu19-backup/*.sql.gz | tail -1"
124M    total                            # 124 MB 生产数据
```

**最近的备份（`/root/edu19-backup`，权限受 `/root` 0700 保护 ✅）：**
```console
$ ssh prod-host "ls -la --time-style=long-iso /root/edu19-backup/"
-rw-r--r-- 1 root root 5367419 2026-09-17 10:23 edu19-pre-applyacl-20260917-1023.sql.gz
-rw-r--r-- 1 root root 5369587 2026-09-17 09:50 edu19-pre-bulkfix-20260917-0950.sql.gz
-rw-r--r-- 1 root root 5292580 2026-09-14 14:14 edu19-pre-deploy-20260914-1414.sql.gz
-rw-r--r-- 1 root root 5392351 2026-09-17 17:29 edu19-pre-t16-20260917-1729.sql.gz   # 最近一次
...
$ ssh prod-host "stat -c '%a %n' /root /root/edu19-backup"
700 /root                               # OK 目录 0700，实际受保护
755 /root/edu19-backup
```

**没有任何自动备份计划：**
```console
$ ssh prod-host "crontab -l"
*/15 * * * * /opt/edu-monitor/health.sh        # 只有可用性心跳，不是备份
$ ssh prod-host "grep -rInE 'backup|dump|pg_dump' /etc/cron.d/ /etc/crontab"
（无输出）
$ ssh prod-host "systemctl list-timers --all | grep -iE 'backup|dump'"
（无输出）                              # 无备份定时器
```

**✅ 备份无对外 HTTP 下载路径：**
```console
$ ssh prod-host "grep -rnE 'root |alias ' /etc/nginx/sites-available/ | grep -vE '#'"
/etc/nginx/sites-available/yujian-lude:5:  root /opt/yujian-lude;
/etc/nginx/sites-available/default:41:     root /var/www/html;
/etc/nginx/sites-available/tgdesk:7:       root /var/www/letsencrypt;
（无任何指向 /opt/edu-app 或 /root 的 root/alias）   # OK 备份无法通过 Web 下载
```

### 【风险等级】🔴 **高**
- 🔴 无自动备份、无异地/离线副本、无加密、无恢复演练（一次勒索软件或误删 = 全损）
- 🔴 35 个转储 0644 世界可读（本地提权即等于全库泄露）
- ✅ 备份无对外下载路径；`/root` 目录 0700 保护有效

### 【建议动作】
1. **立即收紧权限**（一次性，覆盖 35 个文件）：
   ```bash
   ssh prod-host "chmod 600 /opt/edu-app/backup/* /opt/edu-app/backups/*.dump /opt/edu-app/*.dump"
   ssh prod-host "chmod 700 /opt/edu-app/backup /opt/edu-app/backups"
   ```
2. **建立每日自动备份 + 异地同步**（每日 03:00 导出并加密）：
   ```bash
   ssh prod-host "cat > /etc/cron.d/edu-backup <<'EOF'
   0 3 * * * root cd /opt/edu-app && docker exec edu19-prod-db-1 pg_dump -U odoo -Fc edu19 | gzip > /var/backups/edu19/edu19-\$(date +\%F).dump.gz && chmod 600 /var/backups/edu19/*
   EOF"
   # 再配 rclone 同步 /var/backups/edu19 到学校自己的对象存储（异地）
   ```
3. **做一次恢复演练**（在本地 docker 里 `pg_restore` 验证备份可用），并把结论写入文档。

### 【建议优先级】P1（权限可立即做，属 P0 级低成本高收益）

---

## 8. 日志与告警

### 【现状】
**没有任何入侵检测，没有任何安全告警。** UFW 日志级别为 low，journald 只保留 7 天，`auditd` 未激活，唯一的定时任务是每 15 分钟做一次**可用性**心跳（还会自动重启 `edu-system`）——**它不是安全监控**。4667 条爆破记录、3355 次成功密码登录，全部**无人知晓**。

### 【实测命令与输出】

```console
$ ssh prod-host "for p in aide tripwire rkhunter chkrootkit ossec wazuh snort suricata auditd fail2ban crowdsec; do command -v \$p && echo INSTALLED; done"
（无输出）                              # 无任何 IDS/HIDS/审计工具
$ ssh prod-host "systemctl is-active auditd"
inactive                               # 内核审计未启用

$ ssh prod-host "crontab -l"
*/15 * * * * /opt/edu-monitor/health.sh

$ ssh prod-host "cat /opt/edu-monitor/health.sh"
#!/bin/bash
# 隧道+源站健康心跳 v2 — 带自愈
R=$(curl -s -o /dev/null -w "%{http_code} %{time_total}" --max-time 10 "https://edu.example.org/?hb=$RANDOM")
...
    systemctl start edu-system 2>/dev/null      # 自动重启，与安全无关
echo "$TS,${CODE:-000},${TT:-9},${ACTIVE:-unknown},$ACTION" >> "$LOG"
```
> 结论：这是一个**可用性**监控（HTTP 200 检查 + 自愈），**完全不涉及安全事件**。

```console
$ ssh prod-host "grep -i '^LOGLEVEL' /etc/ufw/ufw.conf"
LOGLEVEL=low                           # UFW 仅低级别日志

$ ssh prod-host "grep -E '^Storage|^SystemMaxUse|^MaxRetentionSec' /etc/systemd/journald.conf"
SystemMaxUse=1G
MaxRetentionSec=7day                   # 日志 7 天即清，事件回溯窗口过短
$ ssh prod-host "journalctl --disk-usage"
Archived and active journals take up 610.2M in the file system.

$ ssh prod-host "ls -la /var/log/auth.log*"
-rw-r----- 1 syslog adm  1357161 Sep 18 09:34 /var/log/auth.log
-rw-r----- 1 syslog adm  3808731 Sep 12 23:59 /var/log/auth.log.1
-rw-r----- 1 syslog adm   134703 Sep  6 00:00 /var/log/auth.log.2.gz
（auth.log 覆盖约 1 个月；7-8 月记录已丢失）
```

### 【风险等级】🔴 **高**（安全事件不可发现、不可回溯）

### 【建议动作】
1. **加最简登录告警**（登录成功即推送，成本最低、收益最高，复用已有 telegram-relay 通道）：
   ```bash
   ssh prod-host "cat > /etc/profile.d/ssh-alert.sh <<'EOF'
   #!/bin/bash
   [ -n \"\$SSH_CONNECTION\" ] && echo \"[prod-host] login \$(whoami) at \$(date)\" | curl -s -X POST https://api.telegram.org/bot<TOKEN>/sendMessage -d chat_id=<ID> -d text=\"\$(cat)\" >/dev/null
   EOF"
   ```
2. **启用 auditd** 并监控关键文件：
   ```bash
   ssh prod-host "apt-get install -y auditd && systemctl enable --now auditd"
   ssh prod-host "auditctl -w /etc/passwd -p wa -k identity; auditctl -w /root/.ssh/authorized_keys -p wa -k sshkeys"
   ```
3. **延长日志保留**至 90 天以支持事后取证：
   ```bash
   ssh prod-host "sed -i 's/^#\?MaxRetentionSec=.*/MaxRetentionSec=90day/' /etc/systemd/journald.conf && systemctl restart systemd-journald"
   ```
4. UFW 日志级别提到 `medium`，便于事后统计扫描行为。

### 【建议优先级】P1（登录告警、auditd）/ P2（日志保留）

---

## 9. 其他发现

### S11 生产服务器与大量无关代理服务混部 —— 🟠 中
**现状**：同一台 VPS 上运行 Xray、mtg（MTProto）、mtproto-proxy、HAProxy、stunnel4、cloudflared、squid 等 8 个以上与教务无关的代理服务，占用了 `443/8443/4443/10808/12054/53535/2053/18081-18085` 等端口，且全部对全网开放。
**实测**：`ss -tulpn` 输出（见 §1）；HAProxy 在 443/8443 做 SNI 路由给代理用：
```console
$ ssh prod-host "cat /etc/haproxy/haproxy.cfg"
frontend shared_tls_443
    bind 0.0.0.0:443
    bind 0.0.0.0:8443
    acl is_xray req.ssl_sni -i www.cloudflare.com
    use_backend xray_backend if is_xray
    default_backend mtg_backend          # 默认落到 MTProto 代理
backend mtg_backend
    server sponsored_mtproxy 127.0.0.1:12054 check
backend xray_backend
    server xray 127.0.0.1:1443
```
**风险**：教务站点与代理服务的**信任边界完全重合**——任一代理组件（Xray/HAProxy/mtg/stunnel，这些常年是 CVE 高发区）被攻破，攻击者直接落到持有**全校师生数据**的宿主机 root 边界上，而本报告 S1 已表明 root 边界本身就不牢靠。
**建议**：中长期把教务系统迁到独立 VPS/独立云账号；短期至少把代理服务改用非 root 专用账号（已部分做到：`xray`/`mtg`/`stunnel4` 均为 locked 账号 ✅）并给 UFW 规则加来源白名单。
**优先级**：P1

### S13 补丁与内核 —— 🟠 中
```console
$ ssh prod-host "uname -r; uptime"
6.8.0-134-generic
 09:34:16 up 49 days,  8:01              # 49 天未重启，内核更新未生效
$ ssh prod-host "apt-get -s upgrade | grep -c '^Inst'"
29                                       # 29 个待更新包
$ ssh prod-host "systemctl is-active unattended-upgrades"
active                                   # OK 自动安全更新已启用
$ ssh prod-host "grep 'Automatic-Reboot ' /etc/apt/apt.conf.d/50unattended-upgrades"
//Unattended-Upgrade::Automatic-Reboot "false";   # 不会自动重启 → 内核补丁悬空
```
**建议**：约定每月维护窗口重启一次（`ssh prod-host reboot`，需先确认容器 restart 策略为 unless-stopped ✅ 会自动拉起）。
**优先级**：P2

### S15 本地 SSH 客户端关闭主机密钥校验 —— 🟠 中
```console
$ grep -A8 "^Host prod-host" ~/.ssh/config
Host prod-host
    HostName 203.0.113.10
    User root
    IdentityFile ~/.ssh/my_edu_ed25519
    StrictHostKeyChecking no                 # 不校验主机密钥 → 可被中间人冒充
    UserKnownHostsFile /dev/null             # 完全不记录
```
**风险**：任何能在链路上插一脚的人（包括本机所连的公共 Wi-Fi、代理）都能冒充生产服务器，**在本机输入的生产口令/凭据会被直接窃取**。与 S1「服务器开着密码登录」叠加后风险显著放大。
**建议**：
```bash
ssh-keyscan -t ed25519 203.0.113.10 >> ~/.ssh/known_hosts   # 先记录正确指纹（需人工核对）
# 然后删除 prod-host 块中的 StrictHostKeyChecking no / UserKnownHostsFile /dev/null 两行
```
**优先级**：P3

### S16 authorized_keys 含历史 RSA-2048 密钥 —— 🟢 低
```console
$ ssh prod-host "ssh-keygen -lf /root/.ssh/authorized_keys"
256 SHA256:wb27wAKadu... tingsixingchuan@ting-MacBook-Pro-2026.local (ED25519)   # OK
2048 SHA256:aEUE4WxRbry... faust@faust-SER (RSA)                                 # 旧密钥，建议清理
256 SHA256:5VPm9qZBAamc... prod-host-malaysia (ED25519)                             # OK
$ ssh prod-host "stat -c '%y' /root/.ssh/authorized_keys"
2026-08-20 19:21:16                       # OK 之后未改动
```
**建议**：确认 `faust@faust-SER` 不再需要后移除（`ssh prod-host` 后编辑 `/root/.ssh/authorized_keys`）。
**优先级**：P3

---

## 现在最该马上做的 3 件事

> ⚠️ 以下命令**均未执行**（审计全程只读）。请队长/校长确认后再实施。**第 1 件事必须先做，因为它决定后面两件是「加固」还是「事故响应」。**

### 第 1 件（P0）：核实那 3355 次 root 密码登录是不是自己人 —— 这决定一切

先取证（**纯只读**）：
```bash
ssh prod-host "zgrep -h 'Accepted password' /var/log/auth.log* | grep -E '2026-09-(07|08|09|10|11)' | awk '{print \$1, \$9, \$11}' | head -60"
```
把结果与本人 9/7–9/11 的操作对照（是否用过代理/跳板机/别的机器 SSH 进来）。

- **如果不是自己人 → 立即按入侵事件处理**：断开公网 SSH、保全 `/var/log/auth.log*` 与 `journalctl` 证据、轮换**全部**凭据（root 口令、DB 口令、JWT_SECRET、Telegram token、webhook secret、全部 SSH 密钥），并逐项核对业务数据是否被篡改。
- **如果是自己人 → 说明 root 口令已在 103 个第三方云 IP 上流转，等同泄露**，仍须执行下面第 2 件。

### 第 2 件（P0）：关闭 SSH 密码登录 + 轮换 root 口令 + 装 fail2ban

注意**必须改 `50-cloud-init.conf`**（`60-cloudimg-settings.conf` 里的 `PasswordAuthentication no` 是被覆盖的无效配置——这是本次审计最容易踩的坑）：
```bash
# (1) 修正被覆盖的配置
ssh prod-host "sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config.d/50-cloud-init.conf"
ssh prod-host "sed -i 's/^PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config"

# (2) 校验语法 + 确认生效（必须看到 passwordauthentication no 才继续）
ssh prod-host "sshd -t && sshd -T | grep -Ei 'permitrootlogin|passwordauthentication'"

# (3) 确认无误后重载（不要 restart）
ssh prod-host "systemctl reload ssh"

# (4) 轮换 root 口令
ssh prod-host "passwd root"

# (5) 装 fail2ban 挡住每天上千次爆破
ssh prod-host "apt-get install -y fail2ban"
ssh prod-host "printf '[sshd]\nenabled=true\nmaxretry=4\nbantime=24h\nfindtime=1h\n' > /etc/fail2ban/jail.d/sshd.local"
ssh prod-host "systemctl enable --now fail2ban && fail2ban-client status sshd"
```
> 实施前**务必确认本地公钥已能登录**（`ssh -o BatchMode=yes prod-host 'echo ok'` 已实测通过 ✅），否则会把自己锁在门外。

### 第 3 件（P0）：收敛三处「敞开的口」—— 明文遗留应用 + 0644 转储 + 明文 JWT 密钥

```bash
# (1) 遗留应用 :8090 —— 最短平快：只允许本机访问（彻底方案是下线或加 HTTPS）
ssh prod-host "ufw delete allow 8090/tcp"
ssh prod-host "ufw allow from 127.0.0.1 to any port 8090"

# (2) 35 个 0644 生产转储立刻收紧（124 MB 全校数据）
ssh prod-host "chmod 600 /opt/edu-app/backup/* /opt/edu-app/backups/*.dump /opt/edu-app/*.dump"
ssh prod-host "chmod 700 /opt/edu-app/backup /opt/edu-app/backups"

# (3) 明文 JWT 密钥移出世界可读的 unit 文件并轮换
ssh prod-host "openssl rand -hex 32"                       # 生成新 JWT_SECRET（记下输出）
ssh prod-host "printf 'JWT_SECRET=<上一步输出>\n' > /etc/edu-system.env && chmod 600 /etc/edu-system.env"
# 编辑 /etc/systemd/system/edu-system.service：把 Environment=JWT_SECRET=... 换成 EnvironmentFile=/etc/edu-system.env
ssh prod-host "systemctl daemon-reload && systemctl restart edu-system"

# (4) 顺带收紧源站配置权限
ssh prod-host "chmod 600 /opt/edu-app/config/odoo.conf /opt/edu-app/config/odoo.conf.server"
```

---

## 未验证 / 无法验证的事项及原因

| 项 | 原因 |
|---|---|
| **那 3355 次 root 密码登录的归属方** | 需要**人**（校长/队长）确认自己的运维历史，技术手段无法判定「这是不是我自己用代理池登的」。这是本次审计最重要的未决项。 |
| **是否已有数据被窃取/篡改** | 需要业务层交叉核对（登录审计、数据变更留痕），属应用与权限层范围；且 `journald` 仅存 7 天、`auth.log` 仅约 1 个月，7–8 月的痕迹已不可回溯。**本次审计全程未读取任何业务数据。** |
| **Cloudflare 侧配置**（Always Use HTTPS / HSTS / Minimum TLS / Origin 证书固定） | 需要 Cloudflare 控制台登录权限，本次只能从外部观测行为（实测：HTTP 未跳转、无 HSTS 头、TLS 1.0 可握手），无法读取仪表盘设置。 |
| **匿名意见箱（`edu_telegram`）的数据完整性** | **红线要求，主动不读取。** 仅记录其备份文件元数据（`edu_telegram_old_20260910_1800.tar.gz`，78,716 字节，0644）。 |
| **遗留应用 :8090 的具体数据内容与鉴权强度** | 只做**存在性与状态码**探测（`/api/students → 401`、`/api/auth/login → 400`、`/api/health → 200`），未提交任何凭据、未读取任何返回数据。其源码（`/opt/edu-system/api`）显示有 `auth`/`login_protect`/`ip_blacklist`/`behavior_analysis` 中间件，但**实际强度未做渗透验证**。 |
| **RSA-2048 那把 `faust@faust-SER` 密钥是否仍在使用** | 需向本人确认，无法从服务器侧判定。 |
| **`/opt/edu-app/data/web` 收紧到 0700 后容器是否仍能读写** | 未测试（会改动权限，违反只读铁律）。建议变更后在维护窗口内验证。 |
| **`edu.scrts.org` 相关 nginx vhost（`scrts` / `scrts-8443`）** | 该域名**当前无法解析**（`dig edu.scrts.org` 无结果），vhost 处于休眠状态，未做进一步验证。 |
| **:443/:8443 端口的 SNI 路由细节** | 实测发现直连 `203.0.113.10:443`（SNI=edu.example.org）返回的是 Cloudflare 响应头而非源站 nginx，说明 443 被 HAProxy 的 SNI 路由接管（默认落到 MTProto 代理）。**Odoo 的真正对外路径是 Cloudflare → 源站 :80 → 127.0.0.1:8069**。该路由的完整行为未逐条验证（属代理服务范畴）。 |

---

## 审计方法与合规声明

- **只读保证**：全程仅使用 `ss` / `ufw status` / `iptables -S` / `sshd -T` / `systemctl status` / `passwd -S` / `stat` / `cat` / `grep` / `zgrep` / `openssl s_client` / `curl` / `dig` / `nc -z`。**未执行任何写操作、未重启任何服务、未安装任何软件、未修改任何口令或防火墙规则。**
- **凭据保护**：报告与取证输出中，所有密钥仅呈现**前后各 4 位 + 长度**，不打印完整值。唯一例外是 `systemctl cat edu-system` 输出的 `JWT_SECRET`（`systemd` 原生命令行为）；**该值已在报告中隐去，并已列入「必须轮换」清单。**
- **匿名意见箱红线**：未读取、未导出、未解包 `edu_telegram` 的任何业务数据。
- **未修复声明**：本次审计**未修复任何问题**。所有高危项均以「建议动作」形式提交，由队长/校长决策后实施。
