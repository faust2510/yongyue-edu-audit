# 201（新机）退货前检查清单 —— 2026-10-04

> 校长 2026-10-04：「那我可就把新服务器先给退货退款了啊」。
> 正式站已于同日切回 **187**（见 [cutover-back-to-187-2026-10-04.md](../audit/cutover-back-to-187-2026-10-04.md)），
> 本文记录**退货前必须搬走的东西**与**搬完后的状态**。

## 一、⛔ 差点漏掉的一件事：**每日备份跑在 201 上**

退货前实测：

```
edu19-backup.timer   → edu19-backup.service → /opt/edu-app/scripts/backup_daily.sh
  Description=edu19 生产库异地备份（pg_dump + filestore + 本机还原彩排 + 推异地）
  下次运行：2h37m 后 ｜ 上次：21h 前（连续三天成功）
edu19-backup-drill.timer  每月 31 号还原彩排
```

**直接退货 = 学校同时失去**：① 每日备份任务 ② 已有全部备份 ③ 每月还原彩排 ⇒ **等于零备份**。
而备份正是 2026-10-04 找回 187 数据的唯一底牌。

## 二、搬走了什么（已完成）

| 项目 | 去向 | 验证 |
|---|---|---|
| 201 上 7 份备份（94M） | 校长 Mac `~/edu19-backup-201-20261004/backup/` | rsync 落地 101M、7 份 dump ✓ |
| 备份工具链（脚本+env+4 个 systemd 单元） | 同目录 `backup-toolchain.tgz`，并**已装到 187** | `/etc/systemd/system/edu19-backup*.{service,timer}` ✓ |
| 201 最终库快照 | 同目录 `edu19-201-final.dump`（10M） | sha256 已记 ✓ |
| 备份用的 SSH 私钥 | 201 → **187** `/root/.ssh/edu19_backup_ed25519` | 两边指纹一致 `SHA256:Xc1zir4Z…` ✓ |

## 三、187 上的备份**已实跑通过**

```
systemctl start edu19-backup.service
  00:03:14  Finished edu19-backup.service      ← 成功（exit=0）
本机产物：edu19_20261004T160223Z.dump 9.1M + filestore 12M + MANIFEST.tsv + .sha256
异地落地（203.0.113.9:/srv/edu19-backup/）也出现了同一份：
  edu19_20261004T160223Z.dump              9.1M
  edu19_20261004T160223Z_filestore.tar.gz   12M
定时器：edu19-backup.timer enabled+active，下次 2026-10-05 02:30 CST；drill 每月 1 号 04:30
```

### 中间踩的一个坑（值得记）

异地机 212 的 `authorized_keys` 里写的是：

```
restrict,from="203.0.113.11" ssh-ed25519 … edu19-backup@srv2026013
```

**`from=` 只允许 201 的 IP** ⇒ 密钥搬到 187 后仍然 `Permission denied (publickey)`。
已改成 `from="203.0.113.11,203.0.113.10"`（保留 201 直到真退），改前备份了原文件到 212 的 `/root/`。

## 四、退货前还应确认的三件事

1. **DNS 已全部指向 187**：`edu.example.org`（隧道 CNAME）✓、`cn.edu.example.org`（灰云 A → 203.0.113.10）✓；
2. **ssh 别名已重排**：`prod-host` → **187**（所有引用它的脚本自动跟着走，含 `deploy_myedu.sh` 的默认 `REMOTE`）、
   `prod-b` → 201（过渡期用）、`prod-a` → 187；
3. **`web.base.url`** 两边都是 `https://edu.example.org` ✓，切机不影响。

## 五、退货后如果发现要回头

- **数据**：187 上的库完好（学生 51 / 用户 39 / 附件 545）；201 的最终快照在校长 Mac 上；
- **回滚到 201** 已**不再可能**（机器退了）⇒ 任何回滚只能回到 187 自己的备份：
  `187:/opt/edu-app/backup/` 最近 7 份 + 异地 `212:/srv/edu19-backup/`。