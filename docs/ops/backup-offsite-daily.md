# 每天自动异地备份（systemd timer）——安装与验证手册

> 目标机：生产服务器 **`prod-host`（= 203.0.113.10）**，Ubuntu 24.04 / `/opt/edu-app`
>
> 🔄 **2026-10-05：本文命令里的 `prod-host` 别名已重指向 187**（原指向 201，201 已退货）。
> 备份任务已按本文步骤装到 187 并实跑通过；`deploy/systemd/*` 与 `scripts/backup_daily.sh` 无需改动。
> 装/换机的注意事项与踩过的坑见 [decommission-201-2026-10-04.md](decommission-201-2026-10-04.md)。
> 脚本：`scripts/backup_daily.sh`　单元：`deploy/systemd/*`　配置样例：`deploy/systemd/edu19-backup.env.example`
> 配套：`docs/ops/backup-policy.md`（策略）、`scripts/backup_pull.sh`（开发机拉取路径，自带彩排）

---

## 0. 这套东西要解决的唯一问题

2026-10-01 旧机欠费关机，**备份和生产机在同一个故障域**，35 个转储全丢。
所以：**备份脚本必须自己会跑（不靠人记得），而且必须落到另一台机器/对象存储上；每份备份在推出去之前必须能还原一次。**

拓扑（建议两份异地副本，至少一份在第三方）：

```
 生产机 edu19 (docker: edu19-prod-db-1 / edu19-prod-web-1)
   └─ scripts/backup_daily.sh  ← systemd timer 每天 02:30 Asia/Shanghai
        ├─ pg_dump -Fc            → /opt/edu-app/backup/edu19_<UTC>.dump   （本机暂存，不算异地）
        ├─ tar filestore/edu19    → …_filestore.tar.gz                   （附件实体文件）
        ├─ 还原彩排：用同一个 PG 容器建 scratch 库，pg_restore + 断言关键表行数
        └─ rsync/rclone 推异地    → OFFSITE_TARGET（另一台机器 / 对象存储）

 开发机（这份副本由人工/定期跑，自带彩排）
   └─ scripts/backup_pull.sh → ~/Documents/edu19-backups/（+ 还原彩排 PASS 才算数）
```

---

## 1. 交付文件（都在仓库里，尚未装到服务器）

| 文件 | 作用 |
|---|---|
| `scripts/backup_daily.sh` | 服务器上跑的备份主体：dump + filestore + 彩排 + 推异地 + 保留 + manifest |
| `deploy/systemd/edu19-backup.service` | 执行备份的 oneshot 服务 |
| `deploy/systemd/edu19-backup.timer` | 每天 02:30（Asia/Shanghai）触发；`Persistent=true` 补跑 |
| `deploy/systemd/edu19-backup-drill.service` | 月度演练：把保留期内**最老**的一份重新还原一次 |
| `deploy/systemd/edu19-backup-drill.timer` | 每月 1 日 04:30（Asia/Shanghai）触发演练 |
| `deploy/systemd/edu19-backup.env.example` | `/etc/edu19-backup.env` 样例 |

两份 OnCalendar 已在**真机**用 `systemd-analyze calendar` 校验过（只读命令）：

```
$ ssh prod-host 'systemd-analyze calendar "*-*-* 02:30:00 Asia/Shanghai"'
Normalized form: *-*-* 02:30:00 Asia/Shanghai
    Next elapse: Thu 2026-10-01 18:30:00 UTC      # = 2026-10-02 02:30 CST
$ ssh prod-host 'systemd-analyze calendar "*-*-01 04:30:00 Asia/Shanghai"'
Normalized form: *-*-01 04:30:00 Asia/Shanghai
    Next elapse: Sat 2026-10-31 20:30:00 UTC      # = 2026-11-01 04:30 CST
```
服务器 `TZ=Etc/UTC`，所以**必须带时区后缀**，否则 02:30 会变成 UTC 的 02:30（= 北京 10:30）。

---

## 2. 安装步骤（服务器写操作 —— 由运维执行）

```bash
# ① 脚本上机（rsync 整个 scripts/ 也行；只要 backup_daily.sh 落在 /opt/edu-app/scripts/）
scp scripts/backup_daily.sh root@prod-host:/opt/edu-app/scripts/
ssh prod-host 'chmod 755 /opt/edu-app/scripts/backup_daily.sh'

# ② 配置（0600，只有 root 能读——里面可能有异地密钥路径/主机名）
ssh prod-host 'install -m 600 /dev/null /etc/edu19-backup.env'
scp deploy/systemd/edu19-backup.env.example root@prod-host:/etc/edu19-backup.env
ssh prod-host 'chmod 600 /etc/edu19-backup.env && vi /etc/edu19-backup.env'  # 改 OFFSITE_TARGET

# ③ 装单元（4 个文件）
scp deploy/systemd/edu19-backup.service deploy/systemd/edu19-backup.timer \
    deploy/systemd/edu19-backup-drill.service deploy/systemd/edu19-backup-drill.timer \
    root@prod-host:/etc/systemd/system/
ssh prod-host 'systemctl daemon-reload && systemd-analyze verify /etc/systemd/system/edu19-backup.service /etc/systemd/system/edu19-backup.timer /etc/systemd/system/edu19-backup-drill.service /etc/systemd/system/edu19-backup-drill.timer'

# ④ 先干跑检查（不写任何东西），必须 exit 0
ssh prod-host '/opt/edu-app/scripts/backup_daily.sh --check'

# ⑤ 手动跑一次真备份（第一次跑完看一眼日志与 manifest）
ssh prod-host 'systemctl start edu19-backup.service; echo exit=$?'
ssh prod-host 'tail -40 /var/log/edu19-backup.log'
ssh prod-host 'cat /opt/edu-app/backup/MANIFEST.tsv'

# ⑥ 打开定时器
ssh prod-host 'systemctl enable --now edu19-backup.timer edu19-backup-drill.timer'
ssh prod-host 'systemctl list-timers edu19-backup.timer edu19-backup-drill.timer --all'
```

异地免密（若 OFFSITE_KIND=rsync）：

```bash
ssh prod-host 'ssh-keygen -t ed25519 -N "" -f /root/.ssh/edu19_backup_ed25519'
ssh prod-host 'cat /root/.ssh/edu19_backup_ed25519.pub'   # 把这行加到异地机的 authorized_keys
# 然后在 /etc/edu19-backup.env 里：OFFSITE_SSH_KEY=/root/.ssh/edu19_backup_ed25519
ssh prod-host 'rsync -a --mkpath -e "ssh -i /root/.ssh/edu19_backup_ed25519" /opt/edu-app/backup/MANIFEST.tsv backup@offsite:/srv/edu19-backup/ && echo OK'
```
（服务器 rsync 是 3.4.1，支持 `--mkpath`；开发机自带的 openrsync 不支持，脚本已做回退。）

---

## 3. 装完必须做的验证（含反向验证 —— 不能变红的门禁是假门禁）

| # | 命令 | 期望 |
|---|---|---|
| 1 | `ssh prod-host '/opt/edu-app/scripts/backup_daily.sh --check'` | `RESULT: OK`，exit 0 |
| 2 | `ssh prod-host 'systemctl start edu19-backup.service; echo $?'` | 0；日志里 `总判定: PASS` |
| 3 | 异地机 `ls -l /srv/edu19-backup/` | 有 `.dump`、`_filestore.tar.gz`、两个 `.sha256` |
| 4 | **反向**：把 `OFFSITE_TARGET` 改成不存在的远端主机（如 `backup@10.255.255.1:/x/`）再跑一次 | **非 0**，日志有 `rsync 推 … 失败`；改回来后复绿 |
| 5 | **反向**：`truncate -s 1M` 一个 dump 的副本，手工 `backup_daily.sh --drill` 前先替换最老的那份 | 演练必须**非 0**（`解析不了/损坏`） |
| 6 | `ssh prod-host 'systemctl list-timers edu19-backup.timer'` | NEXT 是次日 02:30 CST（= 当日 18:30 UTC） |
| 7 | 停掉 db 容器再跑一次 `backup_daily.sh` | 非 0 且**不产生新转储**（前置检查先红） |

第 4/5 条是这套东西的价值所在：**备份失败必须吵**，而不是安静地留一个坏文件。

---

## 4. 退出码与判定

| 退出码 | 含义 | 什么时候出现 |
|---|---|---|
| 0 | PASS：dump + filestore + 本机彩排 + 已推异地，四件齐全 | 正常 |
| 1 | FAIL：任何硬失败（容器没起、pg_dump 失败、彩排还原报错、关键表行数不达标、推送失败） | 必须人工介入 |
| 2 | 用法/环境错误（选项写错、磁盘不足、异地配置不全） | 改配置 |
| 3 | 落盘但不完整/未验证：`filestore` 0 个文件、或异地未配（`OFFSITE_KIND=none`）、或 `--no-rehearse` | systemd 会把它记为 failed，**这是故意的** |

判定会写进 `/opt/edu-app/backup/MANIFEST.tsv`（TSV，含 sha256、verdict、fs_state、fs_files、offsite）。

---

## 5. 排障速查

| 症状 | 先看 |
|---|---|
| `容器 … 没在跑` | `ssh prod-host 'docker compose -f /opt/edu-app/docker-compose.yml ps'` |
| `pg_dump 失败` | `docker logs edu19-prod-db-1 \| tail`；磁盘是否写满 |
| 彩排 `关键表 … 不存在` | 转储是不是别的库；或 DB 名/用户配置错 |
| `扩展 pg_stat_statements 在本机容器不可用` | WARN 不致命：新机没预载该扩展，它只是统计用；数据表照常还原 |
| `filestore 一个文件都没有` | 生产确实还没附件，还是 `data/web/filestore/edu19` 挂错了？`ssh prod-host 'find /opt/edu-app/data/web/filestore/edu19 -type f \| wc -l'` |
| 定时器没跑 | `systemctl status edu19-backup.timer`；`journalctl -u edu19-backup.service -n 50` |

---

## 6. 与本机拉取路径（backup_pull.sh）的关系

- **服务器侧（本文件）**：每天自动 dump → 彩排 → 推异地。它保证「每天都有一份可还原的备份在别处」。
- **开发机侧**（`scripts/backup_pull.sh`，2026-10-01 已用真机跑通）：人工/定期从生产机拉一份到本机盘，拉完立刻用 `restore_rehearsal.sh` 在本地 scratch 库还原并断言。
- 两条路互不替代：服务器侧防「忘记备份」，开发机侧防「服务器上的备份是真能还原的吗 + 本机也要有一份」。
- 回滚：`ssh prod-host 'systemctl disable --now edu19-backup.timer edu19-backup-drill.timer'`（脚本与已落盘的备份都留着，不删数据）。

---

## 7. 本手册的验证状态（别把没跑过的当跑过）

- ✅ `backup_daily.sh` 的逻辑已在**开发机用 docker shim + 真 PostgreSQL** 全流程跑过：
  彩排 PASS → 判定 PASS（exit 0）；异地未配 → INCOMPLETE（exit 3）；`--drill` → exit 0；`--check` 未配异地 → exit 1、配好 → exit 0；保留策略按「最近 3 份 + 每月 1 份」删除。
- ✅ `--check` 已在**真机**通过 stdin 执行（不落任何文件）：容器在跑、filestore 路径存在、磁盘余量 94GB、异地未配被如实报红（exit 1）。
- ✅ 两条 `OnCalendar` 已在**真机** `systemd-analyze calendar` 校验。
- ✅ **已在生产机执行过** `backup_daily.sh` 的完整写路径并装上 timer（2026-10-01，运维执行）：`--check` exit 0、真备份 PASS、异地收到档案且 sha256 双向一致、两条反向验证（推送失败 / 损坏档）都如实变红后又复绿。逐条原样证据见 **§8**。
- ⏳ **首次自动触发尚未发生**（装机时 NEXT = 2026-10-01 18:34 UTC = 次日 02:34 CST）；次日复核 `systemctl list-timers` 的 LAST 与 `MANIFEST.tsv` 新行，才算端到端闭环。

---

## 8. 装机记录（2026-10-01 真机执行 —— 运维 ops-migration）

> 执行窗口：**2026-10-01 14:10–14:18 UTC（= 22:10–22:18 CST）**。目标机 `prod-host` = 203.0.113.11（Ubuntu 26.04.1 / systemd 259 / TZ=Etc/UTC）。
> 本节的每条读数都是**当场原样输出**；命令可直接复跑。

### 8.1 异地目标：选定 edu-prod（203.0.113.9）—— 以及为什么不是另外两个候选

| 候选 | 是否满足「异地 ≠ 同机」 | 能否**每天自动**落档 | 结论 |
|---|---|---|---|
| **edu-prod 203.0.113.9**（ssh 别名 `edu-prod`，Ubuntu 22.04.5，2 vCPU / 1 GB RAM / 20 GB 盘） | ✅ 物理独立的一台机 | ✅ 常在线、已配免密 | **选中** |
| 用户这台 Mac（`scripts/backup_pull.sh` 拉取路径） | ✅ | ❌ 会关机、且在 NAT 后面（生产机推不过去） | 作为**第二副本/人工路径**保留，不做每日自动目标 |
| 对象存储（rclone） | ✅ | ✅ | ❌ 当前**没有可用凭据**；需用户先给 bucket/key |

**为什么是它（三条硬理由）**

1. **本次事故的根因就是「备份和生产机同一个故障域」**；edu-prod 是当前唯一长期在线的另一台机器，能把故障域彻底分开。
2. Mac 只能"拉"不能"被推"：生产机在 NAT 后，Mac 又经常关机 ⇒ 不满足"不靠人记得"的目标；而对象存储缺凭据，今天装不上。
3. 干净落点：**专用用户 `edu19backup`（uid 1002）+ 专用目录 `/srv/edu19-backup`**，和那台机上原有的 `/opt/edu-system`、`/opt/yujian-lude` **完全不混**（这正是队长提醒的坑）。

**免密是怎么配的（受限密钥，不是裸 root 信任）**

~~~bash
# 生产机生成专用密钥
ssh prod-host 'ssh-keygen -t ed25519 -N "" -f /root/.ssh/edu19_backup_ed25519'
# edu-prod 上建用户/目录，并把公钥以**受限**方式写入
ssh edu-prod 'useradd --create-home --shell /bin/bash edu19backup; mkdir -p /srv/edu19-backup /home/edu19backup/.ssh; chmod 700 /home/edu19backup/.ssh; chown -R edu19backup:edu19backup /srv/edu19-backup /home/edu19backup/.ssh'
# authorized_keys 只有一行（restrict = 禁 pty/端口转发/agent；from = 只认生产机 IP）
#   restrict,from="203.0.113.11" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBb7UIHtikW+ylRg8RHOUZ44P7yu7s3dZjRwmWkogC1X edu19-backup@srv2026013
~~~

验证（原样）：

~~~
$ ssh prod-host 'ssh -i /root/.ssh/edu19_backup_ed25519 -o BatchMode=yes edu19backup@203.0.113.9 "echo PASSWORDLESS_OK; id"'
PASSWORDLESS_OK
uid=1002(edu19backup) gid=1002(edu19backup) groups=1002(edu19backup)

# 反向控制：不带这把私钥必须失败（证明免密不是"谁都能连"）
$ ssh prod-host 'ssh -o BatchMode=yes -o IdentityFile=/root/.ssh/id_ed25519 edu19backup@203.0.113.9 "echo SHOULD_NOT_HAPPEN"'
no such identity: /root/.ssh/id_ed25519: No such file or directory
edu19backup@203.0.113.9: Permission denied (publickey).
~~~

**已知风险（要盯）**：edu-prod **同时托管别的项目**，`/` 已用 **80%（剩 3.8 GB）**，内存仅 1 GB。当前每次备份约 **13.2 MB**（dump 10.7 MB + filestore 档 2.5 MB）；但 §8.5-F2 的清理缺口意味着它会持续增长 —— 必须加空间监控或先修脚本。

### 8.2 装了什么（sha256 与仓库逐字节一致）

| 仓库文件 | 服务器路径 | 权限 | sha256（前 12 位） |
|---|---|---|---|
| `scripts/backup_daily.sh` | `/opt/edu-app/scripts/backup_daily.sh` | `755 root:root` | `2941f599002e` |
| `deploy/systemd/edu19-backup.service` | `/etc/systemd/system/` | `644` | `454f4b832fd6` |
| `deploy/systemd/edu19-backup.timer` | `/etc/systemd/system/` | `644` | `df0b880f850e` |
| `deploy/systemd/edu19-backup-drill.service` | `/etc/systemd/system/` | `644` | `cab76a248bda` |
| `deploy/systemd/edu19-backup-drill.timer` | `/etc/systemd/system/` | `644` | `6f8cc04398ab` |
| `deploy/systemd/edu19-backup.env.example` | `/etc/edu19-backup.env` | `600 root:root` | （按样例改了两行） |

`/etc/edu19-backup.env` 实际值（除异地主机外与样例一致）：

~~~
OFFSITE_KIND=rsync
OFFSITE_TARGET=edu19backup@203.0.113.9:/srv/edu19-backup/
OFFSITE_SSH_KEY=/root/.ssh/edu19_backup_ed25519
KEEP=7
KEEP_MONTHLY=12
REHEARSE=1
~~~

装机后 `systemd-analyze verify` 四个单元 → **exit 0**（唯一输出是系统自带 xfs_scrub 单元的无关告警）。

### 8.3 验收证据（四条，原样输出 + 退出码）

**① `--check` 必须 0**

~~~
$ ssh prod-host '/opt/edu-app/scripts/backup_daily.sh --check'
== 前置检查 ==
  [ok]   docker/tar/sha256sum 都在（不需要 pip / python 包）
  [ok]   容器 edu19-prod-db-1 / edu19-prod-web-1 都在跑
  [ok]   edu19 pg_isready 通过
  [ok]   容器里 filestore 路径存在：/var/lib/odoo/filestore/edu19
  [ok]   磁盘余量 94161736KB
  [ok]   异地=rsync:edu19backup@203.0.113.9:/srv/edu19-backup/
  [ok]   异地目标可达（rsync -n 干跑通过）

== --check：只检查，什么都没写 ==
RESULT: OK（前置条件满足）
CHECK_EXIT=0
~~~

**② 真备份（经 systemd 单元）必须 PASS**

~~~
$ ssh prod-host 'systemctl start edu19-backup.service; echo $?'
0
$ ssh prod-host 'systemctl show edu19-backup.service -p Result -p ExecMainStatus'
Result=success
ExecMainStatus=0
# /var/log/edu19-backup.log 尾部：
filestore: /opt/edu-app/backup/edu19_20261001T141408Z_filestore.tar.gz  [OK, 265 个文件]
本机彩排: PASS
异地: rsync edu19backup@203.0.113.9:/srv/edu19-backup/ (pushed=1)
总判定: PASS
~~~

彩排（本机容器内、scratch 库 `edu19_rehearsal`）逐表读数原样：`res_company=1 / res_users=8 / res_partner=19 / ir_module_module=740 / ir_model_data=32573 / ir_ui_menu=610 / ir_config_parameter=46 / mail_message=1099 / ir_attachment=971 / op_course=6 / op_batch=17 / op_student=1 / edu_application=2 / edu_notice=5 / edu_alumni_job=3`，`installed=139`，`web.base.url=https://edu.example.org`；`pg_restore 退出码=0 stderr 中 error 行数=0`。

`MANIFEST.tsv`（真机原样，含一次反向验证留下的 INCOMPLETE 行）：

~~~
# ts	host	db	dump	bytes	sha256	filestore	sha256	verdict	fs_state	fs_files	offsite
20261001T141311Z	srv2026013	edu19	edu19_20261001T141311Z.dump	10685889	74bd41b55a66…	edu19_20261001T141311Z_filestore.tar.gz	8917a6fa1b35…	PASS	OK	265	rsync
20261001T141408Z	srv2026013	edu19	edu19_20261001T141408Z.dump	10685889	2dfa2f194a4d…	edu19_20261001T141408Z_filestore.tar.gz	8917a6fa1b35…	PASS	OK	265	rsync
20261001T141541Z	srv2026013	edu19	edu19_20261001T141541Z.dump	10685911	8484fe31ffbe…	edu19_20261001T141541Z_filestore.tar.gz	8917a6fa1b35…	INCOMPLETE	OK	265	rsync
~~~

（第三行就是反向验证①那次：推送失败 ⇒ `pushed=0` ⇒ 判定 INCOMPLETE / exit 3。留着它当证据。）

**③ 异地机上有 dump + filestore + 两个 sha256，且 sha256 与源机逐字节一致**

~~~
$ ssh edu-prod 'ls -la /srv/edu19-backup/'
-rw-r--r-- 1 edu19backup edu19backup 10685889 edu19_20261001T141408Z.dump
-rw-r--r-- 1 edu19backup edu19backup      112 edu19_20261001T141408Z.dump.sha256
-rw-r--r-- 1 edu19backup edu19backup  2479961 edu19_20261001T141408Z_filestore.tar.gz
-rw-r--r-- 1 edu19backup edu19backup      124 edu19_20261001T141408Z_filestore.tar.gz.sha256
# 源机 vs 异地机 sha256 对账：
2dfa2f194a4de954d4b0f72bde45aef9c4b7b85bea5f331a77513b10e39e6eee  edu19_20261001T141408Z.dump
2dfa2f194a4de954d4b0f72bde45aef9c4b7b85bea5f331a77513b10e39e6eee  edu19_20261001T141408Z.dump
8917a6fa1b351e308b006365a8ab0e711bc8ce43f00da185f3ca54e9d6c6f33a  edu19_20261001T141408Z_filestore.tar.gz
8917a6fa1b351e308b006365a8ab0e711bc8ce43f00da185f3ca54e9d6c6f33a  edu19_20261001T141408Z_filestore.tar.gz
SHA256_MATCH：两侧逐字节一致
~~~

（脚本自己也做了这一步：`已推异地并经 --checksum 复核`。异地累计占用 **26 MB / 剩 3.8 GB**。）

**④ 两个 timer 的 NEXT 正确（服务器 TZ=UTC ⇒ 必须带时区后缀）**

~~~
$ ssh prod-host 'systemctl list-timers edu19-backup.timer edu19-backup-drill.timer --all'
NEXT                                  LEFT       UNIT                     ACTIVATES
Thu 2026-10-01 18:34:42 UTC       4h 16min      edu19-backup.timer       edu19-backup.service
Sat 2026-10-31 20:30:00 UTC 4 weeks 2 days      edu19-backup-drill.timer edu19-backup-drill.service
$ ssh prod-host 'systemctl is-enabled edu19-backup.timer edu19-backup-drill.timer; systemctl is-active edu19-backup.timer edu19-backup-drill.timer'
enabled
enabled
active
active
~~~

读法：备份 = **2026-10-02 02:30 CST**（显示 18:34:42 UTC 是因为带了 `RandomizedDelaySec=300` 的抖动，窗口 02:30–02:35）；演练 = **2026-11-01 04:30 CST**。

### 8.4 两条反向验证必须变红（**这套东西的价值就在这**）

**① 异地不可达 ⇒ 必须非 0，且说人话**

~~~
$ ssh prod-host '/opt/edu-app/scripts/backup_daily.sh --offsite-target edu19backup@offsite-unreachable.invalid:/srv/edu19-backup/'
rsync: connection unexpectedly closed (0 bytes received so far) [sender]
rsync error: unexplained error (code 255) at io.c(232) [sender=3.4.1]
  [FAIL] rsync 推 edu19_20261001T141541Z.dump 失败
异地: rsync edu19backup@offsite-unreachable.invalid:/srv/edu19-backup/ (pushed=0)
总判定: INCOMPLETE
RESULT: INCOMPLETE —— 文件在，但缺附件/缺异地（见上面 WARN），不算完整有效备份
PUSH_FAIL_EXIT=3        # ← 非 0，且 systemd 会把它记为 failed
~~~

**② 人为损坏"最老的那份" ⇒ `--drill` 必须非 0**

~~~bash
# 关键：--drill 用 ls -1tr（按 mtime）挑最老 ⇒ 截断后必须把 mtime 改回去，否则它会挑到别的文件（见 §8.5-F3）
OLDEST="$(ls -1tr /opt/edu-app/backup/edu19_*Z.dump | head -1)"
MT="$(stat -c %y "$OLDEST")"; cp -a "$OLDEST" /tmp/oldest.keep
truncate -s 1M "$OLDEST"; touch -d "$MT" "$OLDEST"
/opt/edu-app/scripts/backup_daily.sh --drill
~~~

原样输出：

~~~
OLDEST=edu19_20261001T141311Z.dump
SHA_BEFORE=74bd41b55a6665f21269f7c604154685744aa3d33f30df08f1080baa8ee26d66
--- drill 会挑中的文件（按 mtime 最老）---
edu19_20261001T141311Z.dump
DRILL_BAD_EXIT=1
11:  [FAIL] /opt/edu-app/backup/edu19_20261001T141311Z.dump 解析不了（损坏/截断/不是 pg_dump 档案）—— 这份备份不可用
13:RESULT: FAIL（老备份已不可还原，立刻人工介入）

# 还原真档后复绿：
SHA_AFTER=74bd41b55a6665f21269f7c604154685744aa3d33f30df08f1080baa8ee26d66
RESTORED_SHA_MATCH=yes
DRILL_GOOD_EXIT=0
RESULT: PASS（保留期内最老的那份仍可还原）
~~~

### 8.5 装机过程中发现的三个问题（**都不在本卡写作用域内：未改 `scripts/backup_daily.sh`，仅回报**）

**F1 `--check` 的可达性探测不认 `OFFSITE_SSH_KEY` ⇒ 用专用密钥的部署会**假红****

- 脚本里 `--check` 用的是裸 `rsync -n "$STAGE_DIR/" "$OFFSITE_TARGET/"`（**没有 `-e`**），而 `OFFSITE_SSH_KEY` 只在 `push_offsite` 里生效。
- 实测：`--check` 报 `[FAIL] 异地目标不可达/权限不足`、`CHECK_EXIT=1`；同一秒手工跑 `rsync -n -e "ssh -i /root/.ssh/edu19_backup_ed25519" …` → **exit 0**。可见是判据用错了身份，不是网络问题。
- 本卡的处置（**环境侧 workaround，已在生产机生效**）：`/root/.ssh/config` 追加一段，让默认身份也指向同一把专用密钥 ⇒ `--check` 复绿（exit 0）：
  ~~~
  Host 203.0.113.9 edu19-offsite
      HostName 203.0.113.9
      User edu19backup
      IdentityFile /root/.ssh/edu19_backup_ed25519
      IdentitiesOnly yes
      StrictHostKeyChecking accept-new
      ConnectTimeout 15
  ~~~
- 建议修法（脚本侧）：`--check` 复用 `push_offsite` 的 `extra=(-e "ssh -i $OFFSITE_SSH_KEY -o StrictHostKeyChecking=accept-new")`，否则**任何按手册用专用密钥的人都会看到假红**。

**F2 保留策略只清 `.dump`，`filestore.tar.gz` 与其 `.sha256` 永不清理（本机与异地都累积）**

- 代码事实：`retention()` 只遍历 `"$STAGE_DIR"/edu19_*Z.dump`，删除时 `rm -f "$f" "$f.sha256"`；异地只是 `rsync -a`，**没有任何删除逻辑**。
- 实证（放诱饵 + `--keep 1` 真跑一次）：
  ~~~
  已删除: edu19_20261001T000000Z.dump
  已删除: edu19_20261001T000000Z.dump.sha256
  仍在: edu19_20261001T000000Z_filestore.tar.gz          # ← 没被清
  仍在: edu19_20261001T000000Z_filestore.tar.gz.sha256   # ← 没被清
  ~~~
- 量级：filestore 档 **2.5 MB/份·天** ⇒ ≈ **75 MB/月 ≈ 0.9 GB/年**，且**无上限**；edu-prod 只剩 **3.8 GB**。dump 侧有 KEEP/KEEP_MONTHLY 兜底，filestore 侧没有。
- 建议修法：保留策略同时覆盖 `_filestore.tar.gz`（同一时间戳成套删），或给异地目标加 `--delete` + 保留清单。

**F3 `--drill` 按 **mtime** 挑"最老" ⇒ 直接用 `truncate` 造假档会**静默挑到别人**（我第一轮就被骗过一次）**

- `OLDEST="$(ls -1tr "$STAGE_DIR"/edu19_*Z.dump | head -1)"` —— `-t` 是按 mtime 排序；而 `truncate` 会**刷新 mtime**，于是被截断的那份不再"最老"。
- 实测：直接 `truncate -s 1M` 最老档后跑 `--drill` → 它挑中了另一份健康档，报 `RESULT: PASS`（**假绿**）；把 mtime 用 `touch -d "$MT"` 改回去后 → 正确报红（§8.4②）。
- 建议：要么按**文件名时间戳**排序（与保留策略的命名约定一致、也更符合"最老"的直觉），要么在文档/脚本里明确"损坏演练必须保住 mtime"。

**F4（方法论提醒，不是产品缺陷）** 用 `ssh host 'bash -s' <<EOF` 送多步脚本时，脚本内部的 `docker exec -i`（`psql_at` 等）会把 **heredoc 剩余内容读掉**，远端 bash 读到 EOF 就**静默结束**（本次两次都停在 drill 之后，后续 echo 全没执行，退出码还是 0）。⇒ 多步远程脚本一律先 `scp` 成文件再 `bash /tmp/x.sh`。

### 8.6 空间预算与待办

| 位置 | 现状 | 判断 |
|---|---|---|
| 生产机 `/opt/edu-app/backup` | 老档 10 MB + 3 份新档 ≈ **48 MB**（盘 96 G / 用 7%） | 无压力 |
| 异地 `edu-prod:/srv/edu19-backup` | **26 MB**（盘剩 **3.8 GB** / 80% 已用） | 短期够；**F2 不修就必须加监控** |

待办（都不属本卡写作用域）：① 修 F1/F2/F3（backup-restore 的 `scripts/`）；② 接 `OnFailure=` 通知（service 里已留注释行）；③ 把异地空间与 timer FAIL 纳入 `scripts/health_check_alert.py`；④ Mac 侧按 `scripts/backup_pull.sh` 定期拉第二副本。

### 8.7 回滚

~~~bash
# 停掉定时器（脚本与已落盘的备份都留着，不删数据）
ssh prod-host 'systemctl disable --now edu19-backup.timer edu19-backup-drill.timer'
# 撤销异地免密（两步都要做，否则留一把能写 edu-prod 的密钥）
ssh edu-prod 'sed -i "/srv\/edu19-backup/d; /edu19-backup@/d" /home/edu19backup/.ssh/authorized_keys'  # 删授权行（肉眼确认后再执行）
ssh prod-host 'shred -u /root/.ssh/edu19_backup_ed25519 2>/dev/null || rm -f /root/.ssh/edu19_backup_ed25519'
# 环境侧 workaround 的撤销：/root/.ssh/config 里删掉 Host 203.0.113.9 那一段
~~~

### 8.8 本次**没做**的验证（如实登记）

1. **§3 第 7 条（停掉 db 容器再跑备份）没做**：那一刻库里正在被 loss-ledger 做数据重建（B5→B6），停容器会打断它；这是破坏性测试，留给维护窗口或按开发机已验证的结论处理。
2. **首次自动触发尚未发生**（见 §7 的 ⏳）：装机时 NEXT 在 4 小时后；次日必须复核 `list-timers` 的 LAST 与 `MANIFEST.tsv` 的新行。
3. **edu-prod 的磁盘监控/告警未接**（F2 的直接后果）。
4. **`--check` 的假红只在"专用密钥 + ssh config"这一种组合下被消除**；脚本本身未修（F1）。
