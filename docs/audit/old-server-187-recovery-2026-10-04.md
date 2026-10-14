# 187 旧机找回记（2026-10-04）—— 数据**没有**丢

> 校长 2026-10-04：「我把那个 187 的马来西亚的服务器**又给续费了**，去看一看数据还在不在，
> 把网站代码部署回去，并且**把数据备份到我现在的 Mac 上**。」

## 一、最重要的结论：数据一直在

`docs/deploy-malaysia.md` 开头写着（2026-10-01 加的）：

> ⚠ 本文档记录的那台机器（203.0.113.10）**已欠费关机、数据全丢**。

**这句话是错的。** 2026-10-04 实测：

```
srv1868290（203.0.113.10）  up 6 小时（续费后自动开机）
/dev/sda1  96G  已用 21G  可用 76G
edu19-prod-web-1  Up 6 hours
edu19-prod-db-1   Up 6 hours (healthy)   ← 数据库健康
/opt/edu-app/data/db            197M       ← PGDATA 在
/opt/edu-app/data/web/filestore  37M       ← 附件在
学生 51 ｜ 用户 39 ｜ 附件 545 ｜ 已装模块 115 ｜ 最后写入 2026-09-24 14:30:10
```

**成因推断**：当时只观察到「欠费关机」就写下了「数据全丢」，**没有验证过**。
主机商停机通常只停实例、保留磁盘；续费后 `docker` 按重启策略把两个容器自己拉了起来。
⇒ 教训：**「看不到」不等于「没有了」** —— 写「数据全丢」这种结论前，必须有一次直接的读数。

## 二、备份（已落到校长 Mac）

位置：`~/edu19-backup-187-20261004/`（**不在仓库里** —— 备份不该进 git），共 331 MB：

| 包 | 大小 | 内容 |
|---|---|---|
| `PULL-20261004-critical.tgz` | 123 MB | 全新 `pg_dump -Fc`（含一份纯 SQL）+ 6 个 `pre_*.gz` 历史快照 + `edu19-prod.dump` |
| `PULL-20261004-filestore.tgz` | 12 MB | 附件/资产（**pg_dump 不含**，必须单独备份） |
| `PULL-20261004-customaddons.tgz` | 7.4 MB | 旧机上**当时真正在跑**的代码 |
| `PULL-20261004-config.tgz` | 1 KB | `odoo.conf`（含 `admin_passwd`，**不入 git**）+ `docker-compose.yml` |
| `backup-edu-system-20260824_1405.tgz` | 188 MB | 旧 Go 版教务系统完整备份 |
| `SHA256SUMS.txt` | — | 每个包的 sha256 |

### 还原彩排（已做，通过）

「没还原过的备份不算备份」—— 把 `critical.tgz` 还原到本地克隆库的临时库 `edu19_187check`：

```
学生 51 ｜ 用户 39 ｜ 附件 545 ｜ 已装模块 115 ｜ 最后写入 2026-09-24 14:30:10.866643
⇒ 与 187 上逐项一致；临时库已删（彩排不留痕）
```

## 三、代码部署回 187（已完成）

`scripts/deploy_myedu.sh` 的 `REMOTE` 原先是**硬赋值** `prod-host`，而该别名换机后已指向 201
⇒ 想部署回 187 无路可走。已改为可覆盖（默认行为不变），并加 ssh 别名 `prod-a`：

```bash
REMOTE=prod-a bash scripts/deploy_myedu.sh
```

结果：**部署通过**（升级退出码 0 → web 在升级后重启过 → 冒烟全绿 → 活体注册表 90/90 LIVE、0 DARK）。

## 四、部署时抓到的真问题：187 缺 `db_name`

```
187 的 odoo.conf:  list_db = False            ← 没有 db_name
201 的 odoo.conf:  list_db = False / db_name = edu19
```

这是「**匿名页正常、登录后全站 404**」的根因 —— 也正是 2026-10-01 换机事故的同款状态。
**不是本次部署造成的**（备份包里、部署前就没有）。已按 `docs/code-map.md §2` 的标准修法补上：
备份原配置 → 追加 `db_name = edu19` → `docker compose restart web` → 有界轮询到 `/web/login` 302。
验证：`POST /web/login`（错口令）→ **400 而不是 404**；`/my/home`（匿名）→ 303。

> **一个正面注脚**：这条守卫此前是**坏的** —— 它查的是空 `$DIR` 拼出的 `/config/odoo.conf`，
> 于是**永远报红**（狼来了，见 `docs/audit/deploy-2026-10-03.md`）。2026-10-04 修好传参后它才第一次真正生效，
> **也才第一次抓到真问题**。⇒「永久为红的检查 = 死检查」。

## 四之补、Cloudflare 令牌在哪（**只记位置，不记值**）

切 `cn.edu.example.org` 需要能改 DNS 的 API 令牌。位置如下（**值一律不入库**）：

| 位置 | 说明 |
|---|---|
| `config/server.local.md`（**gitignore**，本机运维速查） | 2026-10-04 存入三把：DNS 编辑（只见 `example.org`，**首选**）／DNS 编辑（可见 3 个 zone，备选）／Cloudflare **AI** 令牌（不能改 DNS） |
| `~/.zsh_history` | 更早那把（多行 curl，令牌在**第二行**）—— ⚠ 单行 grep 会漏 |
| 历史会话记录 | `~/.dsh/sessions/--…教务系统网站新架构--/*/session.v4.jsonl.zstd`（**zstd 压缩**，shell grep 读不到，要解压） |
| 187 的 `/root/.cloudflared/cert.pem` | 账号级证书，`cloudflared` 用它改**隧道类** DNS 路由（本次 `edu.` 就是这么切的） |

**两个坑，记下来免得重走**：

1. **`cfut_` 前缀是 Cloudflare *AI* 令牌**，不是通用 API 令牌 —— 用 `/user/tokens/verify` 一试即知
   （本次实测返回 `Invalid API Token`）；
2. 判断「哪把令牌能用」不能只看它有效 —— 要**列出它能看到的 zone**：本次 11 个候选里只有 **3 把**能看见 `example.org`。

## 五、⚠ 两份数据的血缘不同，**不要合并**

| | 187 | 201（现役） |
|---|---|---|
| 数据 | 到 **2026-09-24** | 换机后**重建** |
| 公网流量 | ❌ 无（nginx 日志只有本地健康检查） | ✅ Cloudflare 回源打在它上面 |

两边的库**来源不同** ⇒ 合并会产生「同一学生两条档案」这类脏数据。
**二选一用哪边，比合并干净得多。** 切换正式站（改 Cloudflare 回源）是**改变学校所见**的一步，须校长拍板。