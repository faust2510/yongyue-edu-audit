# 备份与还原策略（edu19 / 永约学坊教务系统）

> 生效日期：2026-10-01　适用：生产 `edu.example.org`（`/opt/edu-app`，库 `edu19`）
>
> ## 🔄 2026-10-05 更新：生产机换回 187，201 已退货
>
> - **正式站已切回 203.0.113.10**（续费找回，数据完好）；**203.0.113.11 已退货退款**；
> - **每日备份任务已从 201 搬到 187**（脚本 + `/etc/edu19-backup.env` + 4 个 systemd 单元），
>   并**实跑通过**：本地产物齐全、异地 `203.0.113.9:/srv/edu19-backup/` 也出现了同一份；
> - ssh 别名已重排：**`prod-host` → 187**（本文档所有 `prod-host` 命令因此仍然有效）、`prod-b` → 201、`prod-a` → 187；
> - 细节与踩过的坑（异地机 `authorized_keys` 的 `from=` 只白名单了 201 的 IP）见
>   [decommission-201-2026-10-04.md](decommission-201-2026-10-04.md)。
>
> ### ✅ 顺带解决了一个「永久」问题
>
> 本文 §128 原记：「新机（201）`ir_attachment` 971 行、`store_fname` 非空 709 行，磁盘上只有 73 个 ⇒
> **636 个附件实体文件永久缺失**，要恢复只能从旧机磁盘取」。**旧机回来了，且其 filestore 完好（37M / 545 个附件）** ——
> 切回 187 之后，学校现在用的就是**有附件的那台**。⇒ 那 636 个附件**并未永久丢失**，该结论作废。
> 配套脚本：`scripts/backup_pull.sh`（开发机拉取+彩排）、`scripts/restore_rehearsal.sh`（彩排门禁）、`scripts/backup_daily.sh`（生产机每天自动备份）、`tests/smoke/restore_gate_injection.sh`（门禁反向注入自检）
> 配套单元与手册：`deploy/systemd/*`、`docs/ops/backup-offsite-daily.md`（每天自动异地备份的安装与验证步骤）

---

## 0. 一句话

**备份必须异地；每份备份必须经过还原彩排才算有效；没彩排过的备份等于没有备份。**

---

## 1. 为什么（本次事故，2026-10-01）

| 时间 | 事件 |
|---|---|
| 2026-08-30 19:38 CST | 生产库清理后手工转储 `edu19_post_cleanup_0830.dump`，放在**同一台生产机**的 `/opt/edu-app/backup/`；同目录还有 `edu19_before_cleanup_0830.dump`。当晚把这份 dump 与本地开发库 dump 拷回了开发机 |
| 2026-08-31 ~ 09-17 | 又陆续在生产机 `/opt/edu-app/backup/`、`/opt/edu-app/backups/`、`/root/edu19-backup/` 手工放了 **35 个** 转储（最新一份 `edu19-pre-t16-20260917-1729.sql.gz`），全部是 pre-deploy 手工快照，**没有 cron、没有异地、没有恢复演练** |
| 2026-10-01 | 生产机**欠费关机且不可达**。`/opt/edu-app/**` 与 `/root/edu19-backup/**` 的所有转储随机器一起失联 ⇒ 最坏的备份形态全部命中 |
| 现在 | 开发机只剩 `~/Documents/edu19-backups/` 里 2026-08-30 的两份 dump。**可恢复点 = 2026-08-30 19:38 CST** |
| 2026-10-01 晚 | **新生产机上线**（Hostinger srv2026013，`prod-host` = 203.0.113.11，Ubuntu 26.04 / Docker 29.8.2）。用那份 8-30 快照还原 + `-u all` 升级成功（139 模块），站点重新起来。**但备份机制仍是零**：新机上依然只有一份手工放进 `/opt/edu-app/backup/` 的 8-30 dump。本文件 §3/§8A 记录的就是这一天建的自动化与真机验证 |

一句话：**备份和机器同归于尽，等于没备份。** 这不是「备份没做」，是「备份的物理位置和生产机同一个故障域」。

依据（仓库内一手记录）：`docs/audit/security-audit-infra.md` §7「备份与恢复」（35 个世界可读转储、最新 2026-09-17 17:29、无自动备份计划、无异地、无恢复演练）；`docs/handoff-prompt.md` 第 22 行（备份位置清单）。

---

## 2. 三条硬规矩

### 规矩 1：异地（off-host）

- 任何转储的落盘位置**不得**与生产机在同一台机器、同一块云盘、同一个账号的存储桶里。
- 判定标准很土但有效：**把生产机电源拔掉，备份还能不能读到？** 不能 = 不合格。
- 至少两份介质：开发机/办公机本地盘 **+** 一个云对象存储或外置盘（推荐 `rclone` 到对象存储；本仓脚本先覆盖「拉到开发机/指定目录」，云那一步用系统的同步工具补）。
- `scripts/backup_pull.sh` 内置硬保险：`--out` 指向 `/opt/edu-app/*` 或 `/root/*` 时**直接非 0 退出**（防止把「拉备份」写成「从生产机拷到生产机」）。

### 规矩 2：每份备份必须经过还原彩排（restore rehearsal）

- 「转储文件存在」不是证据，「`pg_restore -l` 能列目录」也不是证据，**只有「真的还原进一个空库 + 关键表有行数」才是证据**。
- 门禁 = `scripts/restore_rehearsal.sh`：
  1. 档案非空、`pg_restore -l` 能解析（截断/损坏的档案在这一步必须红）；
  2. 归档目录里必须含关键表（拿错库的档案必须红）；
  3. `pg_restore --no-owner --no-privileges` 退出码为 0 **且 stderr 里一条 `error` 都没有**（不吞错）；
  4. 还原后的库里关键表存在、行数不低于下限，`ir_module_module` 有已装模块，`ir_config_parameter.web.base.url` 非空。
- 任何一条不成立 ⇒ 非 0 退出 + 人话。**没有 `--allow-fail`、没有白名单、没有「已知可忽略错误」清单**——豁免开关会让门禁永久失明。
- `backup_pull.sh` 默认在拉取后立刻跑彩排；彩排不通过 ⇒ 整个拉取失败（非 0）。显式 `--skip-rehearsal` 时退出码 **3**（拉到但未验证），绝不返回 0。
- 建议：**每次生产部署前**跑一次彩排（最近一份即可），每月至少一次对最老的那份跑一次（防止「最近的能还原，最老的早就烂了」）。

### 规矩 3：门禁自己必须能被证伪

- `tests/smoke/restore_gate_injection.sh` 是门禁的自检：好档案→绿；截断档案/垃圾文件/空库的转储/空库→**必须红**；然后再跑一次好档案→复绿（控制组，证明门禁不是「永远红」）。
- 该自检自己也会因「坏输入仍然绿」而非 0 退出 —— 门禁失效必须比门禁本身更早暴露。
- 本仓铁律参见 `docs/dev-workflow.md`（判据强度五兄弟、量具不许有副作用）。

---

## 3. 用法

```bash
# 1) 起一个本地 scratch postgres（只用于彩排，别和生产/开发库共用）：
#    initdb -D ~/edu19-scratch/pgdata55432 -U odoo --auth=trust --encoding=UTF8 --locale=C
#    env LC_ALL=C pg_ctl -D ~/edu19-scratch/pgdata55432 -o '-p 55432 -c listen_addresses=127.0.0.1' start
#    macOS 必须带 LC_ALL，否则 postmaster 会因 'became multithreaded during startup' 起不来

# 2) 还原彩排（可直接吃本机 2026-08-30 的两份 dump）：
bash scripts/restore_rehearsal.sh --pgbin /opt/homebrew/opt/postgresql@16/bin \
  ~/Documents/edu19-backups/edu19_post_cleanup_0830.dump
bash scripts/restore_rehearsal.sh --pgbin /opt/homebrew/opt/postgresql@16/bin \
  ~/Documents/edu19-backups/edu19_local_dev_0830.dump

# 3) 门禁自检（反向注入三连 + 控制组）：
bash tests/smoke/restore_gate_injection.sh --pgbin /opt/homebrew/opt/postgresql@16/bin

# 4) 异地拉全量备份（换新服务器时用 --host/--dir/--out 覆盖）：
bash scripts/backup_pull.sh --host prod-host --dir /opt/edu-app \
  --out ~/Documents/edu19-backups --db edu19 --keep 7 --keep-monthly 12

# 5) 生产机自己每天自动备份（systemd timer；安装步骤见 docs/ops/backup-offsite-daily.md）：
#    服务器上：/opt/edu-app/scripts/backup_daily.sh --check      # 只检查，不写任何东西
#              systemctl start edu19-backup.service           # 跑一次真备份（dump+彩排+推异地）
#    仓库里：  deploy/systemd/edu19-backup.{service,timer} + edu19-backup-drill.{service,timer}
#              deploy/systemd/edu19-backup.env.example -> /etc/edu19-backup.env
# 注：backup_pull.sh 的默认 --dir 就是 /opt/edu-app、默认 --host 就是 prod-host —— 新机布局与默认值一致，无需改脚本
```

参数化要点（马上要换服务器，所以**不要**改脚本里的默认值去适配新机，用参数）：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--host` | `prod-host` | ssh 别名/主机；换新服务器只改这里 |
| `--dir` | `/opt/edu-app` | 远端项目目录（只用于存在性检查） |
| `--out` | `~/Documents/edu19-backups` | 异地落盘目录 |
| `--db` / `--db-user` | `edu19` / `odoo` | 库名与库用户 |
| `--db-container` / `--web-container` | 自动探测 | docker 容器名（换了编排就显式给） |
| `--format` | `custom` | `custom` = `pg_dump -Fc`；`plain` = `pg_dump \| gzip -9` |
| `--keep` / `--keep-monthly` | `7` / `12` | 保留最近 N 份 + 每月 1 份保留 M 个月 |
| `--no-filestore` | 关 | 显式跳过附件实体文件 ⇒ 判定 INCOMPLETE、退出码 3 |
| `--skip-rehearsal` | 关 | 跳过彩排 ⇒ 判定 UNVERIFIED、退出码 3 |

`pg_dump` 的 CUSTOM 格式把归档目录（TOC）写在**文件末尾**，所以截断的档案在 `pg_restore -l` 阶段就会失败——这正是彩排能在「还原之前」抓住坏档的原因（一手依据：[pg_dump 16 文档](https://www.postgresql.org/docs/16/app-pgdump.html)、[pg_restore 16 文档](https://www.postgresql.org/docs/16/app-pgrestore.html)）。

### 3.1 退出码口径（两个脚本一致）

| 码 | 含义 | 说明 |
|---|---|---|
| 0 | PASS | 数据库转储 + filestore + 还原彩排（+ 已推异地）四件齐全 |
| 1 | FAIL | 硬失败：ssh/容器不可达、pg_dump 失败、转储损坏、还原报 error、关键表缺失或低于下限、推送失败 |
| 2 | 用法/环境错 | 选项写错、目标 Postgres 不可达、磁盘不足、异地配置不全 |
| 3 | INCOMPLETE / UNVERIFIED | **文件在，但不算有效备份**：没彩排过、filestore 0 个文件、异地没配 —— 故意非 0，不许静默通过 |

---

## 4. 备份内容清单（缺一不可）

| 项 | 来源 | 说明 |
|---|---|---|
| 数据库全量转储 | `docker exec <db> pg_dump -U odoo -Fc -d edu19` | 表结构 + 数据 + 序列 |
| **filestore** | `docker exec <web> tar -czf - -C /var/lib/odoo filestore/edu19` | **附件实体文件。只拉 DB 不拉它 = 库能开，附件、图片、下载件全断** |
| sha256 + 大小 + 时间戳 | `backup_pull.sh` 自动落 `.sha256` 与 `MANIFEST.tsv` | 保证「拿到的就是拉到的那份」 |
| Odoo 配置 | `config/odoo.conf.server`（在 git 里） | 已在版本库，无需另行备份 |
| 自定义模块源码 | git（`custom_addons/**`） | 已在版本库，无需另行备份 |

**filestore 不能省**：2026-10-01 事故里，本机能拿到的只有**本地开发库**的 filestore（`data/web/filestore/edu19`，54 MB），**不是**生产库那份。

新生产机（203.0.113.11）的实测普查（2026-10-01 当天）：`ir_attachment` 971 行、其中 `store_fname` 非空 **709** 行，而新机 filestore 磁盘上只有 **73** 个（52 个文件，部分引用同文件）—— **636 个附件实体文件永久缺失**（旧机带走了）。所以新机现在这份 filestore 备份「拉得到、但内容是残缺的」；库能开，这些附件是断链的。**要恢复附件只能从旧机磁盘取，或让用户重新上传。**

---

## 5. 保留策略

- 默认：**最近 7 份**每份保留；**每月各留 1 份**，保留 **12 个月**；其余删除。
- 安全边界：保留策略**只删 `backup_pull.sh` 自己命名生成的档案**（`edu19_<host>_<UTC时间戳>.dump` / `.sql.gz`），手工丢进去的档案（例如 8-30 那两份）**永远不碰**。
- 删除时同步删 `.sha256`；先跑 `--dry-run` 看清单再真删。

---

## 6. 有效 / 无效的判定表（红绿口径）

| 情形 | 期望 | 由谁保证 |
|---|---|---|
| 好档案（能还原、关键表有数据） | 绿（退出码 0），打印行数表 | `restore_rehearsal.sh` |
| 档案被截断 / 传输损坏 / 不是 pg_dump 档案 | **红**（退出码 1）+ 「档案无法解析…备份不可用」 | 同上（TOC 解析） |
| 档案是别的库 / 归档里没有关键表 | **红** + 列出缺哪些表 | 同上（TOC 表清单） |
| 空库（没有表） | **红** + 「这是空库，或根本不是本项目的库」 | 同上（表存在性） |
| 表和结构都对但业务数据被清空（行数低于下限） | **红** + 表名/实际行数/下限 | 同上（行数下限） |
| 还原过程中任何一条 error | **红** + 前 20 行原始错误 | 同上（不吞 stderr） |
| `--out` 指向生产机目录 | **红**，拒绝执行 | `backup_pull.sh` |
| ssh/容器不可达、pg_dump 失败、转储太小 | **红**，且不留半成品（`.part` 自动清掉） | `backup_pull.sh` |
| 拉到了但没彩排（`--skip-rehearsal`） | **非 0（退出码 3）**，manifest 记为 UNVERIFIED | `backup_pull.sh` |
| filestore 一个文件都没有 | **非 0（退出码 3）** + `[WARN] 这不叫备份成功`，manifest 记 `EMPTY` | `backup_pull.sh` / `backup_daily.sh` |
| 异地没配（`OFFSITE_KIND=none`） | **非 0（退出码 3）**：文件只在本机 = 和生产机同故障域 | `backup_daily.sh` |
| 备份脚本推异地失败 | **非 0（退出码 1）**，systemd 记 failed | `backup_daily.sh` |

扩展缺失的处理（显式、如实、不静默）：彩排会读归档目录里的 `EXTENSION` 条目，逐个尝试在 scratch 库预建（并从还原清单剔除，避免重复创建报错）。**建不了的会打 WARN 并说明原因**（如 `pg_stat_statements` 需要 `shared_preload_libraries` 预载），数据表照常还原。这一条是「如实报告」而**不是**豁免：它不影响关键表断言，也不改变退出码。

---

## 7. 附录 A：关键表下限的实测来源（不是拍脑袋）

下限来自 2026-08-30 两份真实 dump 的实测读数（脚本文档 `restore_rehearsal.sh` 的 `REQ_PROJECT`）：

| 表 | 生产 `post_cleanup` | 本地 `local_dev` | 采用下限 |
|---|---|---|---|
| `res_company` | 1 | 1 | 1 |
| `res_users` | 8 | 10 | 1 |
| `res_partner` | 18 | 29 | 1 |
| `res_groups` | 88 | 88 | 1 |
| `ir_module_module` | 729（installed 136） | 729（installed 136） | 1 / installed ≥ 1 |
| `ir_model_fields` | 14056 | 14056 | 500 |
| `ir_model_data` | 31766 | 31767 | 1000 |
| `ir_ui_menu` | 599 | 599 | 100 |
| `ir_config_parameter` | 43 | 43 | 1 |
| `mail_message` | 404 | 610 | 1 |
| `ir_attachment` | 972 | 988 | 1 |
| `op_course` | 6 | 7 | 1 |
| `op_batch` | 1 | 1 | 1 |
| `op_student` | 1 | 4 | 1 |
| `edu_application` | 2 | 6 | 1 |
| `edu_notice` | 5 | 22 | 1 |
| `edu_alumni_job` | 3 | 3 | 1 |

用 `--profile core` 可退到只查 Odoo 核心表；用 `--min TABLE=N` 可逐表收紧。**放宽下限要写进本文件并说明理由**。

---

## 8. 附录 B：2026-08-30 两份 dump 的取证结论（用于判断「能恢复到什么程度」）

两份档案都能 `pg_restore` 还原，**0 error**；但它们**不是同一份数据**：

| 判据 | `edu19_post_cleanup_0830.dump` | `edu19_local_dev_0830.dump` |
|---|---|---|
| sha256 | `23fb0534f918f92e885c5b216b05dd5768fe6a5bc57947b64c105c92e1c0c484` | `9388830fa84e089f08b7cf0b66ed826148eb63bfb49864aba57d9ca97318e3a0` |
| 大小 / 归档时间 | 10234709 B / 头写 11:38:49（= 19:38:49 CST） | 10690076 B / 头写 11:39:09（= 19:39:09 CST） |
| `web.base.url` | **https://edu.example.org**（且 `web.base.url.freeze=True`） | http://localhost:8069 |
| 安装扩展 | `pg_trgm` + **`pg_stat_statements`** | 只有 `pg_trgm` |
| 演示数据 | **无**（`op_student` 只剩 1 行，是用户本人的档案 王佐） | 一堆：【演示】师生、`stu@local`/`fac@local`、`HTTP冒烟课程` |
| 真实业务痕迹 | **有**：`edu_application` 2 条「王茜茜 / 2392308645@qq.com」，通知邮件标题「【永约学坊】新入学申请：王茜茜」（2026-08-30 09:07 UTC） | 无（6 条全是【演示】） |
| 仓库侧记录 | `docs/handoff-prompt.md:22` 明写「生产 post-cleanup + 本地开发库」；`docs/audit/security-audit-infra.md:673` 在生产机 `ls -la /opt/edu-app/backup/` 里列出同名同大小（10234709）文件 | 同上 |

**结论：`edu19_post_cleanup_0830.dump` 是生产库快照，可恢复点 = 2026-08-30 19:38 CST（11:38:49 UTC）。**

时间口径的推导（可证伪）：归档头写 11:38:49，而库里最新一条 `mail_message` 是 2026-08-30 09:07:35（Odoo 存 UTC）。若 11:38 是本地时间（CST=UTC+8 ⇒ 03:38 UTC），则它早于库里最新记录，自相矛盾；所以 11:38 只能是 UTC ⇒ 19:38 CST。旁证：生产机 `ls` 显示同一文件的 mtime 是 `Aug 30 19:38`，本机副本 mtime 也是 `Aug 30 19:38 CST`。

它还回答了「恢复成什么样」：这是**清理演示数据之后、还没有真实教务运营数据**的状态 —— `op_faculty=0`、`op_session=0`、`edu_fee_bill=0`、`edu_leave=0`、`edu_checkin_record=0`，只有 1 个学生档案（用户本人）、6 门课程、1 个班、2 条真实报名、3 条校友岗位。**08-30 之后到 10-01 之间约 32 天的生产数据没有任何副本**（更近的 9-17 转储全在关机的那台机器上）。

---

## 8A. 真机验证记录（2026-10-01，新生产机 203.0.113.11）

### A. 开发机 → 生产机 全链路拉取（真的跑了，不是仿真）

```console
$ bash scripts/backup_pull.sh --host prod-host --out ~/Documents/edu19-backups --db edu19 --keep 7 --keep-monthly 12 \
      --pgbin /opt/homebrew/opt/postgresql@16/bin --port 55432     # 不给 --dir，验证默认值就是 /opt/edu-app
  ssh prod-host 通
  远端目录 /opt/edu-app 存在
  db 容器=edu19-prod-db-1  web 容器=edu19-prod-web-1
  远端 edu19 pg_isready 通过
  .../edu19_prod-host_20261001T134307Z.dump  (10663028 字节)
  pg_restore -l 解析通过
- **服务器侧每天自动备份尚未装机**：`scripts/backup_daily.sh` 与 `deploy/systemd/*` 已交付并在开发机全流程验证，但按分工不在生产机执行写操作 —— 装完请按 `docs/ops/backup-offsite-daily.md` §3 逐条验证（尤其第 4/5 条反向验证：推异地失败必须非 0、坏档案必须演练变红）。
- **异地那一跳的业务选择未定**：`OFFSITE_TARGET` 指向哪台机器/哪个对象存储由运维决定（服务器有 rsync 3.4.1，没装 rclone；要对象存储就先 `apt-get install rclone`）。在配好之前，生产机每天的备份都会以退出码 3（INCOMPLETE）收场——这是刻意设计，不是 bug。
- **附件实体文件的还原演练未做**：新机 filestore 里 709 个引用只有 73 个文件在盘（636 个随旧机丢失），所以「filestore 备份 → 还原回附件」这条路只能等有完整 filestore 之后再演练。
- **恢复后的 Odoo 起站验证**由运维完成（新机 `-u all` 已 135/139 模块、`/` 200）；本任务只覆盖到数据库层与备份链路。
  res_company=1 res_users=8 res_partner=18 ir_module_module=740(installed 139) ir_model_data=32573
  op_student=1 op_course=6 op_batch=1 edu_application=2 edu_notice=5 edu_alumni_job=3
  web.base.url = https://edu.example.org
  总判定: PASS    RESULT: PASS —— 已拉到异地，附件实体文件也在，且数据库真的还原成功
REAL_PULL_EXIT=0
```

连跑两次（相隔 38 秒）字节数相同但 sha256 不同（`f4bf1851…` vs `d7a7e9a7…`）——库是活的，正常。
**保留策略的安全边界同时也被验证了**：跑完两轮后，手工放进同目录的 `edu19_post_cleanup_0830.dump` / `edu19_local_dev_0830.dump` 的 sha256 与跑之前**逐字节相同**（保留策略只删自己命名的 `edu19_<host>_<ts>Z.*`）。

### B. 生产机侧 `backup_daily.sh --check`（真机执行、不落任何文件）

```console
$ cat scripts/backup_daily.sh | ssh prod-host 'bash -s -- --check --offsite-kind none'    # 服务器当前真实状态：还没配异地
  [ok]   docker/tar/sha256sum 都在（不需要 pip / python 包）
  [ok]   容器 edu19-prod-db-1 / edu19-prod-web-1 都在跑
  [ok]   edu19 pg_isready 通过
  [ok]   容器里 filestore 路径存在：/var/lib/odoo/filestore/edu19
  [ok]   磁盘余量 94179448KB
  [WARN] OFFSITE_KIND=none：这次备份只落在本机 /opt/edu-app/backup —— 和生产机同一个故障域，不算有效备份
RESULT: 有问题（见上）     exit=1     ← 这正是想要的：没异地就必须红

$ ... --check --offsite-kind rsync --offsite-target /root
  [ok]   异地=rsync:/root
  [ok]   异地目标可达（rsync -n 干跑通过）
RESULT: OK（前置条件满足） exit=0
```

新机事实：`TZ=Etc/UTC`、systemd 259、rsync 3.4.1（支持 `--mkpath`）、db 容器 PG **16.15**（与转储同版本）、`shared_preload_libraries` 为空（所以 `pg_stat_statements` 装了但查不了，彩排里如实报 WARN）。

### C. 服务器侧每天自动备份（`backup_daily.sh` + systemd）

逻辑已在开发机用 **docker shim + 真 PostgreSQL** 全流程跑过（`--check` 未配异地 → exit 1；不配异地跑备份 → INCOMPLETE exit 3；配 rsync 异地 → PASS exit 0；`--drill` 演练最老备份 → exit 0）。
**但它没有在生产机上执行过写路径**——按分工服务器写操作归运维。安装与验证步骤（含两条必做的反向验证）见 `docs/ops/backup-offsite-daily.md`。

---

## 9. 仍未验证 / 待办

- **服务器侧每天自动备份尚未装机**：`scripts/backup_daily.sh` 与 `deploy/systemd/*` 已交付并在开发机全流程验证，但按分工不在生产机执行写操作 —— 装完请按 `docs/ops/backup-offsite-daily.md` §3 逐条验证（尤其第 4/5 条反向验证：推异地失败必须非 0、坏档案必须演练变红）。
- **异地那一跳的目标未定**：`OFFSITE_TARGET` 指向哪台机器/哪个对象存储由运维决定（服务器有 rsync 3.4.1，没装 rclone）。在配好之前，生产机每天的备份都会以退出码 3（INCOMPLETE）收场 —— 这是刻意设计，不是 bug。
- **附件实体文件的还原演练未做**：新机 filestore 里 709 个引用只有 73 个文件在盘（636 个随旧机丢失），所以「filestore 备份 → 还原回附件」只能等有完整 filestore 之后再演练。
- **恢复后的 Odoo 起站验证**由运维完成（新机 `-u all` 升级成功、`/` 200）；本任务只覆盖到数据库层与备份链路。