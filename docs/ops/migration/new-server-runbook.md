# 新服务器迁移 Runbook —— 203.0.113.11 从零到生产可用

> **目标机**：`root@203.0.113.11`（Hostinger，hostname `srv2026013`，吉隆坡 MY，与旧机同城同商）
> **本手册的性质**：执行清单 + 实测基线。**凡标「未实测 / 未验证」的条目，都不许当结论用。**
> **取证时刻**：2026-10-01 21:2x–21:3x Asia/Shanghai（宿主 UTC 13:2x）。每条读数都附可复跑命令。
> **配套**：DNS/HTTPS 切换见 [dns-and-tls-cutover.md](dns-and-tls-cutover.md)；旧机抢救结论见 [step0-recover-old-server.md](step0-recover-old-server.md)。

---

## 0. 这台机器现在长什么样（实测，可复跑）

~~~bash
ssh prod-host 'hostnamectl | head -6; cat /etc/os-release | head -3; uname -r; nproc; free -m; df -h /; \
  docker --version; docker compose version; python3 --version; nginx -v; certbot --version; \
  timedatectl | head -4; ufw status; ls /opt/edu-app'
~~~

2026-10-01 实测输出（原样摘录）：

~~~
Static hostname: srv2026013
PRETTY_NAME="Ubuntu 26.04.1 LTS"        VERSION_ID="26.04"   VERSION_CODENAME=resolute
Linux srv2026013 7.0.0-34-generic #34-Ubuntu SMP PREEMPT_DYNAMIC x86_64
2                                        # nproc
Mem: 7935 total / 512 used / 6751 free  Swap: 0
/dev/sda1  96G  2.0G  94G  3% /
Docker version 29.8.2, build 7fc2dff
Docker Compose version v5.5.1
Python 3.14.4
nginx version: nginx/1.28.3 (Ubuntu)
certbot 4.0.0
Local time: Thu 2026-10-01 13:26:59 UTC   Time zone: Etc/UTC (UTC, +0000)
Status: inactive                          # ufw
/opt/edu-app/{backup,config,custom_addons,data,openeducat_erp,scripts}   # 空骨架，无文件
~~~

**与旧生产的差异（必须知道的四点）**

| 项 | 新机实测 | 影响 |
|---|---|---|
| Ubuntu | **26.04.1 LTS（resolute）**，Python **3.14.4**，kernel 7.0.0 | 官方文档里的 Ubuntu 22/24 路径、pip 写法**不能照抄**；见 §2.4 与 §6 |
| pip | `python3 -m pip` → **No module named pip**；`/usr/lib/python3.14/EXTERNALLY-MANAGED` 存在 | **没有任何 pip 依赖可用**。好消息：本流程要用的两个宿主脚本 `scripts/check_live_registry.py`、`scripts/health_check_alert.py` **只用标准库**（实测其 import 行：argparse/http.cookiejar/json/os/re/subprocess/sys/urllib + datetime/time）⇒ 不需要装任何 Python 包 |
| docker-compose | **没有 v1 命令**（`/usr/bin/docker-compose` 不存在），只有 `docker compose` 插件 v5.5.1 | 仓库脚本用的都是 `docker compose`（带空格），不受影响 |
| 时区/swap/防火墙 | UTC、无 swap、ufw inactive | §2.1 三条一次性设置 |

**已就绪**（队长 2026-10-01 装好，实测版本）：nginx 1.28.3 / certbot 4.0.0（插件 nginx + standalone 均在）/ rsync 3.4.1 / ufw 0.36.2；nginx `:80` 已被**默认站点**占用（`sites-enabled/default` 存在）——见 §2.6 必须先处理。

---

## 1. 机型够不够：按旧生产实测规模判断

旧生产实测口径（**2026-09-24 的取证块，原文见 `docs/deploy-malaysia.md` 同一日各节**，不得据行号定位代码）：

| 指标 | 旧生产读数 | 来源 |
|---|---|---|
| Odoo workers | **2** | `deploy/odoo.conf.server` |
| 宿主负载 | `load 0.14` | docs/deploy-malaysia.md「静态资源缓存修复」节 |
| 容器内 TTFB | **8 ms** | 同上 |
| 首页 HTML | 6.8 KB (gzip) | 同上 |
| 登录洪峰阈值 | 约 **40–60 并发** | docs/code-map.md §2「压测结论」 |
| 页面重量 | 5.74 MB / 14 请求（第三刀后） | docs/deploy-malaysia.md「前端瘦身第三刀」 |
| 模块数 | 116 | 同上 |
| 库 dump 体积 | 10.25–10.28 MB（pg_dump） | docs/deploy-malaysia.md 各次升级前备份 |

**结论**：新机 **2 vCPU / 7935 MB / 96 G** 与旧生产同档（旧机同为 Hostinger KVM 2 级），按上表读数**容量不是瓶颈**。真正要盯的是内存分配，不是 CPU：

- `workers=2` 维持不变（**不要**为了"机器更大"提到 6——本机是同一档，而 Odoo worker 峰值内存由 `limit_memory_hard` 决定）。
- Postgres 16 默认 `shared_buffers=128MB`，8 G 机器上偏小；是否调 `shared_buffers=1GB` / `work_mem` 需按恢复后的库大小实测（**未实测：本机数据库尚未恢复**）。
- 磁盘 94 G 可用（实测），dump + filestore 远小于此；**但 filestore 体积未验证**（旧机数据已丢，只能等 Aug-30 备份的实际体积），若 Aug-30 前的 filestore 很大需复核。
- **无 swap**（实测 `Swap: 0`）。8 G 机器跑 Odoo+PG 建议加 2 G swap 兜底 OOM 峰值 —— 命令见 §2.1，**但「加了 swap 后 OOM 是否真的减少」本手册未实测**。

---

## 2. 从零到生产可用

> 顺序不可颠倒：**系统层 → 目录 → 代码 → 配置/密钥 → 容器 → nginx → 证书 → 数据恢复 → 模块升级 → 闸门**。
> 每一步都有「验收判据」，不满足就不许进下一步（这是本项目一贯的「假绿」防御）。

### 2.1 系统层（一次性）

~~~bash
# ① 时区：与旧生产对齐（旧机 UTC+8，cron/日志对照方便）。Odoo 内部存 UTC，不受影响。
timedatectl set-timezone Asia/Shanghai && timedatectl | head -3

# ② swap 兜底 2G（当前 Swap: 0）
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
free -m | head -2

# ③ 防火墙：ufw 实测 inactive。开 22/80/443。
#    ⚠ 80/443 必须对公网开放：cn.edu.example.org 是**灰云**直连，绕不过去（见 dns-and-tls-cutover.md）。
#    若以后只用隧道/只经 CF，可把 80/443 限制到 Cloudflare 段；本阶段先全开，切完 DNS 再收紧。
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable && ufw status verbose
~~~

**验收**：`timedatectl` 显示 `Asia/Shanghai (+0800)`；`free -m` 的 Swap 行非 0；`ufw status` 为 active 且 22/80/443 为 ALLOW。

### 2.2 目录布局（与旧生产逐字一致）

~~~bash
mkdir -p /opt/edu-app/{config,custom_addons,openeducat_erp,data/db,data/web,scripts,backup}
~~~

| 路径 | 内容 | 来源 |
|---|---|---|
| `/opt/edu-app/docker-compose.yml` | 生产编排 | 仓库 `deploy/docker-compose.prod.yml` |
| `/opt/edu-app/config/odoo.conf.server` | 运行配置（compose 只挂这个文件名） | 仓库 `deploy/odoo.conf.server` |
| `/opt/edu-app/custom_addons` `openeducat_erp` | 应用代码，与本地 rsync 字节一致 | 仓库同名目录 |
| `/opt/edu-app/data/db` | PGDATA 宿主目录（**必须归 postgres/uid 999，权限 700**） | compose 挂载 |
| `/opt/edu-app/data/web` | Odoo data_dir → `/var/lib/odoo`，**filestore 在 `data/web/filestore`** | compose 挂载 |
| `/opt/edu-app/scripts` | 宿主侧脚本（注册表门禁、健康探活、本手册闸门） | 仓库 `scripts/` |
| `/opt/edu-app/backup` | pg_dump 落地点（旧生产同路径） | docs/deploy-malaysia.md |

> ⚠ **宿主机目录属主**：容器内 `odoo`=uid 100、`postgres`=uid 999。**切勿递归 chown `data/db`**（PGDATA 必须 700 且归 postgres）——这是旧生产写进档案的教训。

### 2.3 代码落地

~~~bash
# 本机（Mac）仓库根目录执行。SSH 加固参数与 scripts/deploy_myedu.sh 一致：
#   本机出口有代理干扰，ssh 会断也会挂 ⇒ 必须带 ConnectTimeout / ServerAlive*。
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=3"

rsync -az --exclude='__pycache__' -e "ssh $SSH_OPTS" \
  custom_addons openeducat_erp root@203.0.113.11:/opt/edu-app/
# 只挑两个宿主侧门禁脚本（它们只用标准库，新机无 pip 也能跑）
rsync -az -e "ssh $SSH_OPTS" \
  --include='check_live_registry.py' --include='health_check_alert.py' --include='*/' --exclude='*' \
  scripts/ root@203.0.113.11:/opt/edu-app/scripts/
scp $SSH_OPTS deploy/docker-compose.prod.yml root@203.0.113.11:/opt/edu-app/docker-compose.yml
scp $SSH_OPTS deploy/odoo.conf.server      root@203.0.113.11:/opt/edu-app/config/odoo.conf.server

ssh $SSH_OPTS root@203.0.113.11 'cd /opt/edu-app && chmod -R a+rX custom_addons openeducat_erp scripts'
~~~

**验收**：`ssh prod-host 'ls /opt/edu-app/custom_addons | wc -l'` 与本地一致；`md5sum` 抽 3 个文件双向比对一致（旧生产反复踩过「rsync 整目录漏文件」——2026-09-07 记录在 docs/deploy-malaysia.md）。

### 2.4 配置与密钥（**安全红线，不能照抄仓库**）

1. **`admin_passwd` 必须重新生成**。仓库里的 `deploy/odoo.conf.server` 写着 `admin_passwd = 25f2daef005f8f63eb623c26a3d37c79`，`config/odoo.conf` 写着 `changeme-master-2026` —— **这两个值已进 git，等于公开**。
   ~~~bash
   # 新机生成并写回（不要回传仓库、不要 commit）
   NEWPW=$(openssl rand -hex 16) && sed -i "s/^admin_passwd.*/admin_passwd = $NEWPW/" /opt/edu-app/config/odoo.conf.server
   chmod 600 /opt/edu-app/config/odoo.conf.server
   ~~~
2. **数据库口令**：`deploy/docker-compose.prod.yml` 里 `POSTGRES_PASSWORD=odoo`（db 端口未映射到宿主，仅 docker 内网可达，风险有限但仍是默认口令）。若要改：
   - **首次 `up` 之前**改环境变量 → initdb 时生效；
   - 若库已经 initdb 过再改环境变量，**PG 里的口令不会跟着变**（初始化只在空 PGDATA 时跑一次）；此时要 `ALTER USER odoo WITH PASSWORD '…';` 并同步 `odoo.conf.server` 的 `db_password`。
   - **未实测**：本次恢复流程用哪条路径（改环境变量 vs ALTER USER）由队长按恢复顺序定。
3. **`web.base.url`**：必须 `https://edu.example.org` 且 `freeze=True`（旧生产口径）。恢复的 dump 里若已是该值则不用动；**新库（无 dump）必须用 admin 在 设置→技术→系统参数 里设**。
4. **`proxy_mode = True`**：仓库的 `deploy/odoo.conf.server` 已有（实测该文件第 6 行），确保在 nginx 反代后 `X-Forwarded-*` 被采信（否则门户链接与 IP 判定都会错）。

### 2.5 起容器

> 实测（2026-10-01，**只读、未落盘**）：把仓库那份 prod compose 通过 stdin 喂给新机的 compose，
> ```bash
> ssh prod-host 'docker compose -f - config >/dev/null && echo COMPOSE_CONFIG_OK' < deploy/docker-compose.prod.yml
> # → COMPOSE_CONFIG_OK
> ```
> ⇒ **Compose v5.5.1 能正确解析仓库里的生产编排**（无 version 字段弃用报错、无语法问题）。

~~~bash
ssh prod-host 'cd /opt/edu-app && docker compose pull && docker compose up -d'
ssh prod-host 'cd /opt/edu-app && docker compose ps'
~~~

**验收**：`docker compose ps` 两个容器 `running`；`db` 的 healthcheck 变 healthy；宿主 `ss -tlnp | grep 8069` 只见 `127.0.0.1:8069`（**不得暴露到公网**，compose 已把 web 端口绑在 127.0.0.1）。

### 2.6 nginx

现状（实测）：nginx 1.28.3 已装、`nginx -t` 通过、`/etc/nginx/sites-enabled/default` 存在并占用 `:80`。

~~~bash
# —— 本机（Mac，仓库根目录）：把四份现成配置送上去 ——
scp $SSH_OPTS docs/ops/nginx-edu-strcs.conf   root@203.0.113.11:/etc/nginx/sites-available/edu-strcs
scp $SSH_OPTS docs/ops/edu-cn.conf            root@203.0.113.11:/etc/nginx/sites-available/edu-cn
scp $SSH_OPTS docs/ops/edu-cn-tls.conf        root@203.0.113.11:/etc/nginx/sites-available/edu-cn-tls
scp $SSH_OPTS docs/ops/edu-cn-ratelimit.conf  root@203.0.113.11:/etc/nginx/conf.d/edu-cn-ratelimit.conf

# —— 新机：建立软链并在摘掉默认站点后 reload ——
ssh $SSH_OPTS root@203.0.113.11 '
  rm -f /etc/nginx/sites-enabled/default
  ln -sf /etc/nginx/sites-available/edu-strcs /etc/nginx/sites-enabled/edu-strcs
  ln -sf /etc/nginx/sites-available/edu-cn    /etc/nginx/sites-enabled/edu-cn
  # edu-cn-tls 的 server 块在证书就绪前不要启用（否则 nginx -t 会因证书缺失而失败）
  nginx -t && systemctl reload nginx
'
~~~

> ⚠ **本机没有 xray/mtg**：旧机的 `edu-cn-tls.conf` 监听 `127.0.0.1:10443 + proxy_protocol`、由 HAProxy 按 SNI 分流。新机若不跑 HAProxy，需要一份「nginx 直接听 443」的变体 —— 两个方案与取舍见 [dns-and-tls-cutover.md](dns-and-tls-cutover.md) §4。**照抄旧 conf 会起不来**（端口/real_ip 都对不上）。

**验收**：`nginx -t` 通过；`curl -sI -H 'Host: edu.example.org' http://127.0.0.1/ | head -1` 得 200/302（**此时容器已起才会 200**）。

### 2.7 数据库与 filestore 恢复

> **本手册只给路径与判据**；还原彩排与备份拉取脚本由 **backup-restore** 队友负责（其写作用域 `scripts/backup_pull.sh`、`scripts/restore_rehearsal.sh`、`docs/ops/backup-policy.md`）。**以他们的脚本为准**，本节不重复实现。

~~~bash
# 宿主机（或 db 容器内）恢复；数据库名 edu19，用户 odoo
cd /opt/edu-app
docker compose exec -T db psql -U odoo -d postgres -c 'DROP DATABASE IF EXISTS edu19;'
docker compose exec -T db psql -U odoo -d postgres -c 'CREATE DATABASE edu19 OWNER odoo;'
cat /opt/edu-app/backup/<dump 文件> | docker compose exec -T db pg_restore -U odoo -d edu19 --no-owner --role=odoo
# filestore：必须与 dump **同一时刻**的备份，解到 data/web/filestore
#   （compose 把 ./data/web 挂成 /var/lib/odoo ⇒ filestore 落 /opt/edu-app/data/web/filestore）
chown -R 100:100 /opt/edu-app/data/web/filestore
~~~

**判据（硬）**：`op_student` 等关键表存在（见 §2.9 闸门）；`ir_attachment` 条数与 filestore 目录文件数同量级；**filestore 与 dump 必须同源同时刻**（跨时刻拼接 = 附件 404/错文件，这是通用 Odoo 铁律，本仓旧事故也有同类形态）。

### 2.8 模块安装 / 升级

**首次在新库上安装**（若恢复的是全量 dump，则模块已装，跳过 `-i`，直接 §2.9）：

~~~bash
# 模块清单 = scripts/deploy_myedu.sh 的 -u 列表 + edu_zh
#   edu_life,edu_schedule,edu_apply,edu_portal,edu_brand,edu_quiz,edu_public,edu_zh,edu_tg_bind,edu_assess
#   （edu_nav 只同步、**不进 -u 列表**，理由见该脚本 2026-09-29 注释：引用已卸载模块的 xmlid 会 exit 255）
docker compose run --rm --name deploy-upg web odoo -c /etc/odoo/odoo.conf -d edu19 \
  -i edu_life,edu_schedule,edu_apply,edu_portal,edu_brand,edu_quiz,edu_public,edu_zh,edu_tg_bind,edu_assess \
  --db_host=db -r odoo -w odoo --stop-after-init --http-port=8099 2>&1 | tee /tmp/upg.log
grep -qE 'Modules loaded' /tmp/upg.log && ! grep -qE 'Traceback \(most recent call last\)|CRITICAL' /tmp/upg.log && echo UPGRADE_OK
docker compose restart web      # ⚠ 必须：注册表重载 ≠ 重启（2026-09-24 生产事故）
~~~

> ⚠ **`-i` 与 `-u` 不是等价的**（仓库实测结论）：`-i` 对**已安装**模块**不重载 data/view 文件**，会制造「升级成功但页面没变」的假象。首次装用 `-i`，之后一律 `-u`。
> ⚠ **`edu_zh` 升级必须带 `--i18n-overwrite`**（否则 PO 覆盖不生效）。
> ⚠ **注册表铁律**：改了 `custom_addons/**` 的 `.py`（尤其新增文件/字段）⇒ **必须 `docker compose restart web`**；判据 `python3 scripts/check_live_registry.py`（有 DARK ⇒ exit 1）。

### 2.9 验证闸门（**能变红**）

把下面这段落成 `/opt/edu-app/scripts/verify_restore_gate.sh`（chmod +x）。它**不是打印一句绿字**：任一判据不过就 `exit 1` 并打印「恢复不完整」。

~~~bash
#!/usr/bin/env bash
# 恢复完整性闸门（可自证、能变红）—— /opt/edu-app/scripts/verify_restore_gate.sh
# 判据：关键表存在 + 关键表最小行数 + 站点就绪 + 活体注册表门禁；任一不过 = exit 1 并打印「恢复不完整」。
# --selftest：往必需表里注入一个必然不存在的表名，尺子必须因此报红；报红=尺子准(exit 0)，仍判绿=尺子坏了(exit 3)。
set -u
SELFTEST=0
[ "${1:-}" = "--selftest" ] && SELFTEST=1

DB=${GATE_DB:-edu19}
PSQL_BIN=${GATE_PSQL:-"docker compose -f /opt/edu-app/docker-compose.yml exec -T db psql -U odoo -d $DB -A -t -c"}
BASE_URL=${GATE_BASE_URL:-http://127.0.0.1:8069}
REGISTRY_GATE=${GATE_REGISTRY:-/opt/edu-app/scripts/check_live_registry.py}

REQUIRED_TABLES="res_users res_partner ir_model_data ir_module_module op_student op_student_course op_session op_batch op_subject ir_attachment"
MIN_ROWS="res_users:2 ir_model_data:500 op_student:1"
[ "$SELFTEST" = "1" ] && REQUIRED_TABLES="$REQUIRED_TABLES __gate_selftest_must_be_missing__"

q() { $PSQL_BIN "$1" 2>/dev/null; }

missing=""
for t in $REQUIRED_TABLES; do
  n=$(q "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='$t'")
  [ "$n" = "1" ] || missing="$missing $t"
done

if [ -n "$missing" ]; then
  echo "缺表：$missing"
  if [ "$SELFTEST" = "1" ]; then
    case " $missing " in
      *" __gate_selftest_must_be_missing__ "*)
        echo "尺子自证通过：注入的缺失表被检出（反向注入能变红）。"; exit 0 ;;
      *) echo "尺子坏了：注入了缺失表，检出集合里却没有它。"; exit 3 ;;
    esac
  fi
  echo "恢复不完整：以上关键表不在库里 —— 这次恢复不是完整恢复，不要开站。"
  exit 1
fi
if [ "$SELFTEST" = "1" ]; then
  echo "尺子坏了：注入了缺失表，闸门仍然判绿（DB 检查是死代码）。"; exit 3
fi

FAIL=0
for spec in $MIN_ROWS; do
  t=${spec%%:*}; min=${spec##*:}
  c=$(q "SELECT count(*) FROM $t")
  case "$c" in
    ''|*[!0-9]*) echo "无法读数：$t 行数（得到 '$c'）—— 判红"; FAIL=1; continue ;;
  esac
  if [ "$c" -lt "$min" ]; then echo "恢复不完整：$t 只有 $c 行（要求 >= $min）"; FAIL=1; fi
done

code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$BASE_URL/web/login" 2>/dev/null) || code=000
case "$code" in
  200|302|303) ;;
  *) echo "站点未就绪：$BASE_URL/web/login -> $code"; FAIL=1 ;;
esac

if [ -f "$REGISTRY_GATE" ]; then
  python3 "$REGISTRY_GATE" >/tmp/gate_registry.log 2>&1 || { echo "活体注册表门禁非 0（DARK/ENV，见 /tmp/gate_registry.log）"; FAIL=1; }
else
  echo "活体注册表门禁脚本不存在：$REGISTRY_GATE（未验证，不计绿）"; FAIL=1
fi

[ "$FAIL" = "0" ] || { echo "恢复闸门判红：任一条不满足都代表「恢复不完整 / 站点不可用」。"; exit 1; }
echo "恢复闸门全绿：关键表齐全 -> 行数达标 -> 站点就绪 -> 活体注册表无 DARK。"
exit 0
~~~

**这道闸门自己做过控制组**（在 Mac 上用「假 psql / 假 curl / 假门禁」桩跑，**不含生产**；脚本与桩已在本机 `/tmp/gatetest/` 验证）：

| 组 | 输入 | 期望 | 实测 |
|---|---|---|---|
| T1 正例 | 表齐、行数够、HTTP 200、门禁 0 | exit 0 | exit 0，打印「恢复闸门全绿」 |
| T2 反例·缺表 | 真值表里没有 `op_session` | exit 1 + 「恢复不完整」 | exit 1，原样打印 `缺表： op_session` / `恢复不完整：…不要开站。` |
| T3 反例·行数 | `op_student` = 0 行 | exit 1 | exit 1，打印 `恢复不完整：op_student 只有 0 行（要求 >= 1）` |
| T4 反例·站点 | `/web/login` → 502 | exit 1 | exit 1，打印 `站点未就绪：… -> 502` |
| T6 反例·门禁 | 注册表门禁 exit 1 | exit 1 | exit 1，打印「活体注册表门禁非 0」 |
| **T5 自证** | `--selftest`（注入必然不存在的表） | 尺子检出 → exit 0 | exit 0，打印「尺子自证通过：注入的缺失表被检出」 |
| **T9 反自证** | 把量具打坏（任何表都报存在）再 `--selftest` | **必须 exit 3，不许绿** | exit 3，打印「尺子坏了：…DB 检查是死代码」 |

复跑命令（本机，桩在 /tmp）：

~~~bash
cd /tmp/gatetest && export PATH="/tmp/gatetest:$PATH"
env FAKE_HTTP=200 GATE_PSQL=/tmp/gatetest/fake_psql.sh GATE_REGISTRY=/tmp/gatetest/fake_gate.py bash gate.sh; echo "T1 EXIT=$?"
env FAKE_HTTP=200 MISSING=op_session GATE_PSQL=/tmp/gatetest/fake_psql.sh GATE_REGISTRY=/tmp/gatetest/fake_gate.py bash gate.sh; echo "T2 EXIT=$?"
env FAKE_HTTP=200 GATE_PSQL=/tmp/gatetest/fake_psql.sh GATE_REGISTRY=/tmp/gatetest/fake_gate.py bash gate.sh --selftest; echo "T5 EXIT=$?"
env FAKE_HTTP=200 FAKE_ALWAYS_PRESENT=1 GATE_PSQL=/tmp/gatetest/fake_psql.sh GATE_REGISTRY=/tmp/gatetest/fake_gate.py bash gate.sh --selftest; echo "T9 EXIT=$?"
~~~

**上线判定（全部必须满足，缺一不许宣布成功）**

~~~bash
ssh prod-host 'cd /opt/edu-app && bash scripts/verify_restore_gate.sh; echo "GATE=$?"'          # 期望 GATE=0
ssh prod-host 'cd /opt/edu-app && bash scripts/verify_restore_gate.sh --selftest; echo "SELFTEST=$?"'  # 期望 SELFTEST=0
ssh prod-host 'cd /opt/edu-app && python3 scripts/check_live_registry.py; echo "REG=$?"'         # 期望 REG=0，无 DARK
# 活体注册表 89/89（任务验收口径）：门禁输出里的 LIVE 计数 = 库里登记的自研模型/字段数，
#   口径与判据见 scripts/check_live_registry.py 头部注释；不给会话时字段级会明写 SKIP（不算绿、也不算红）
~~~

---

## 3. 回滚

| 回滚点 | 动作 | 代价 |
|---|---|---|
| nginx 配置 | 删 `sites-enabled/edu-strcs`、`edu-cn*`，`ln -s default`，`nginx -t && systemctl reload nginx` | 秒级 |
| 证书 | 停留 HTTP/自签；cf 侧 SSL 模式回 Flexible（见 cutover 文档） | 分钟级 |
| 容器 | `docker compose down`（**不要 `down -v`**，卷里是数据） | 分钟级 |
| 数据库 | 从 `/opt/edu-app/backup/` 的 dump 重灌（§2.7） | 分钟级，丢 dump 之后的数据 |
| 模块卸载 | **不可逆**（重装模块不恢复数据）；唯一回滚 = 恢复备份 | 高 |

---

## 4. 需要改的本机文件

| 文件 | 现状 | 要做什么 |
|---|---|---|
| `~/.ssh/config` 的 `Host prod-host` | **已改**：`HostName 203.0.113.11`（实测 2026-10-01；备份 `~/.ssh/config.bak-before-scrts1-removal` 里仍是 `203.0.113.10`） | **无需再动** |
| `scripts/deploy_myedu.sh` | `REMOTE=prod-host`、`DIR=/opt/edu-app`（实测 L55–56）；IP 只出现在第 2 行注释 | **无需改**（走别名，别名已指向新机） |
| `scripts/check_prod_menus.py` | 第 23 行注释里写旧 IP | 可选：更新注释（无功能影响） |
| `scripts/hallucinate.py` | 第 19 行 `("203.0.113.10", "192.0.2.10")` | **查是否有功能用途**后再定（本手册未判定） |
| `scripts/ops/retire_old_batches.py` | 第 8 行注释里写旧 IP | 可选：更新注释 |
| `docs/ops/edu-cn.conf` | 第 2 行注释写旧 IP | 切 DNS 后一并更新注释 |
| `README.md` / `docs/code-map.md` / `docs/deploy-malaysia.md` / `docs/deploy-a8-runbook.md` / `docs/plans/v2-checklist.md` / `docs/yongyue-rebrand.md` / `docs/curriculum/import-report.md` / `docs/research/gradebook-entry.md` / `docs/audit/security-audit-*.md` / `timetable_import/PRODUCTION_CHECKLIST.md` / `tests/smoke/sql_constraints_audit_results.json` | 含旧 IP（多数是历史取证块） | **历史取证块不要改**；新写的现状描述改新 IP。清单由 `grep -rn '203.0.113.10' .` 复跑得到 |

---

## 5. 未实测 / 未验证清单（不许当结论用）

1. **数据库恢复本身**：本手册未执行（归 backup-restore 队友）；§2.7 的命令是标准路径，**未在本机实测**。
2. **filestore 体积与 filestore↔dump 同源性**：旧机数据已丢，只能等 Aug-30 备份的实际内容；**未验证**。
3. **Postgres 调参与 swap 效果**：库未恢复，**未实测**。
4. **`-i` 安装清单在本机的实际结果**：未跑；模块清单来自 `scripts/deploy_myedu.sh` 的 `-u` 列表（读源码所得），**新库首装是否每个模块都干净可装未验证**。
5. **`odoo:19` / `postgres:16` 镜像拉取**：**未实测**（队长辖区，且拉镜像会改机器状态；本手册只验证了 compose 文件能被 Compose v5.5.1 解析）。
6. **`docker compose v5.5.1` 与旧生产 v2 的行为差异**：只验证了 `config` 解析（2026-10-01），**未实测 `run`/`up` 行为**（`--rm --name` 等参数语义需在真机跑一遍才算数）。
7. **89/89 的读数**：口径来自 `scripts/check_live_registry.py`；本次未拿到生产会话，**未实测该数字**。
8. **网页可达性**：新机 `/web/login` 是否 200 —— 容器未起，**未实测**。
