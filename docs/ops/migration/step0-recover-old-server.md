# 旧机数据抢救（原「产物 A / step0」）—— **已作废（2026-10-01 队长裁定）**

> **状态：不是行动项。** 用户已确认旧机数据「全没了」；旧机 Hostinger VPS（`203.0.113.10`，rDNS `srv1868290.hstgr.cloud`）欠费关机后 TCP 22/443 全不可达，SSH 无法登录。
> 文件名保留（`step0-recover-old-server.md`）以免其它文档的引用悬空；内容降级为**政策取证存档**，供以后不再犯同一类错误时复用。
> 取证时刻：2026-10-01（Asia/Shanghai）。**下面每一条都带一手 URL 与原文摘录；查不到的写在 §3。**

---

## 1. 事故的系统性根因（一句话）

**备份只放在被备份的那台机器上**（旧生产全部 `/root/pre_ship_20260929_1632.gz` 等），机器一停 ⇒ **数据与备份同时消失**。
本机（Mac）只剩 2026-08-30 的两份 dump（`~/Documents/edu19-backups/edu19_post_cleanup_0830.dump`、`edu19_local_dev_0830.dump`）⇒ 即使新机起来，也只能恢复到 **8/30 的状态**。
教训：异地备份不是"可选项"，是**恢复能力的唯一载体**（对应的新机制见 backup-restore 队友的写作用域：`scripts/backup_pull.sh` / `docs/ops/backup-policy.md`）。

---

## 2. Hostinger 官方政策（一手 URL + 原文，2026-10-01 核实）

> 取证方法：Hostinger 支持站是 WordPress，正文可通过其 REST API 直取：
> `https://www.hostinger.com/support/wp-json/wp/v2/posts?slug=<slug>&_fields=title,link,modified,content`
> （用 `web_fetch` 抓取，纯文本剥标签后逐条引用。主站 `www.hostinger.com` 是 Nuxt SPA，直接抓页面拿不到正文。）

### 2.1 「过期 / 取消 / 暂停」是三种不同的事

**来源**：What to do if your hosting plan becomes inactive at Hostinger（modified 2026-09-15）
https://www.hostinger.com/support/4146981-what-to-do-if-your-hosting-plan-becomes-inactive-at-hostinger/

- **Expired（欠费过期）**："your hosting plan has expired due to non-payment. As a result, your websites will stop working, and you won't be able to manage them"；**续费即可恢复**："To restore access, you can renew your hosting plan, and services will resume as soon as the payment is fully processed."
- **Canceled（因欠费被取消）**："If your hosting plan was canceled due to non-payment and expired **less than 30 days ago**, you still have the option to **restore** it. **After 30 days, the plan is permanently deleted and cannot be renewed or restored.**"
- **Suspended（暂停）**：这是 **ToS 违规**触发，不是欠费；处理方式是申诉/补材料。

### 2.2 未付款的账单与"什么时候停"

**来源**：Managing unpaid invoices at Hostinger（modified 2026-08-05）
https://www.hostinger.com/support/5401909-how-to-delete-an-unpaid-invoice-at-hostinger/

- "For most services, the advance invoice remains active for **7 days after the original expiration date**. If the invoice is not paid within this period, it is automatically deleted."
- **"Unpaid services are suspended when they reach the expiration date."**

### 2.3 主动不续费会发生什么

**来源**：How to cancel a Hostinger service（modified 2026-09-15）
https://www.hostinger.com/support/1583775-how-to-cancel-a-hosting-plan-at-hostinger/

- "**Terminating any service, be it due to expiration or refund, will permanently delete all its associated data.** Therefore, it is recommended to download a manual backup of your website files, databases and email to your local device."
- 关自动续费后："the service will remain active until its expiration date. After this date, the service will be automatically canceled and deleted from your account."

### 2.4 VPS 的备份/快照机制（**关键**）

**来源**：How to back up or restore a Hostinger VPS（modified 2026-09-15）
https://www.hostinger.com/support/1583232-how-to-back-up-or-restore-a-vps-at-hostinger/

- **Backups**："Automated weekly backups (and daily if enabled), stored separately from your server. **Up to four are retained, two daily and two weekly.**"
- **Snapshots**："A manual, on-demand capture of your entire VPS. **Only one can be stored at a time**, it is deleted if you reinstall the OS or restore from a backup, and it **expires after 1 day**."
- 还原路径：控制台 → VPS → Manage → Backups & Monitoring → Snapshots & Backups → 在某个日期旁点 **Restore**。期间 VPS 会被锁、不可管理。
- **不能下载**："**Downloading backups or snapshots directly to a local device is not supported. Instead, use SFTP.**"（即：想拿走数据，必须**先有一台能连上的服务器**，用 SFTP 取。）

### 2.5 买了新套餐也不等于续上

**来源**：What to do if you bought a new Hostinger plan instead of renewing（modified 2026-09-15）
https://www.hostinger.com/support/new-hosting-instead-renewal-hostinger/

- "purchasing a new plan creates a **separate service** rather than extending an existing one. Hosting plans **cannot be merged**, and content is **not moved automatically**."
- "If your previous hosting plan expired **less than 30 days ago, you can reactivate it**. This is the fastest way to bring your websites and email back online without performing manual processes."
- 过期套餐取数据：过期 **< 30 天**时，控制台可对**过期套餐**生成备份下载链接（面向网站文件+数据库）；"If the plan expired **more than 30 days ago**, it **cannot be renewed or accessed**. In this case, a **local backup** stored on your computer is required."

---

## 3. 查不到 / 未验证（写明具体原因，不许当结论用）

1. **「VPS 备份能否还原到另一台新 VPS」：未验证——官方没有任何一处支持这个说法。**
   逐篇读完 §2.4 的官方文章后，Restore 的语义始终是"把**这台** VPS 恢复到某个时刻"，且官方明确"下载备份到本地设备**不支持**（用 SFTP 取）"。
   ⇒ 我们**不能**声称"续费后可以把备份还原到新买的机器"；能站得住的说法只有：**续费恢复原机 → 用 SFTP/scp 把数据取出 → 再迁到新机**。
2. **本次未做（也不需要做）的验证**：没有续费、没有登录 hPanel（旧机账号层面的操作已无意义）。
3. **检索工具故障（记录在案）**：`web_search` 全程返回 `HTTP 400 … insufficient credits`（额度不足），因此本次全部靠**指定 URL 的 `web_fetch`** + Hostinger 支持站 REST API 检索；
   - `lite.duckduckgo.com` / `html.duckduckgo.com`：`web fetch failed: TypeError: fetch failed`；
   - `bing.com`：跨域重定向到 `cn.bing.com`；成功后结果页以营销链接为主，且页面自述"为回应符合本地法律要求的通知，部分搜索结果未予显示"；
   - Hostinger 主站与 `/legal/universal-terms-of-service-agreement`：**Nuxt SPA，正文由 JS 渲染**，抓到的是壳（约 586 字符）；
   - 支持站自身的 `?search=` 相关性差（WordPress 全文检索），最终改用 **sitemap + REST API** 逐篇核对。
4. **VPS 类服务是否同样适用 30 天规则**：官方 4146981 用 "hosting plan" 字样，**没有逐字点明 VPS**；本文按"同一套 billing 语义"处理，并**明确标为推断**（一手文章未逐字覆盖 VPS）。

---

## 4. 一手 URL 清单

| # | 主题 | URL |
|---|---|---|
| 1 | 过期/取消/暂停三态与 30 天删除 | https://www.hostinger.com/support/4146981-what-to-do-if-your-hosting-plan-becomes-inactive-at-hostinger/ |
| 2 | 未付款账单 7 天作废 + 到期即暂停 | https://www.hostinger.com/support/5401909-how-to-delete-an-unpaid-invoice-at-hostinger/ |
| 3 | 终止/过期即永久删除数据 | https://www.hostinger.com/support/1583775-how-to-cancel-a-hosting-plan-at-hostinger/ |
| 4 | VPS 备份/快照机制与还原边界 | https://www.hostinger.com/support/1583232-how-to-back-up-or-restore-a-vps-at-hostinger/ |
| 5 | 买了新套餐 ≠ 续费；<30 天可重新激活 | https://www.hostinger.com/support/new-hosting-instead-renewal-hostinger/ |
| 6 | 退款政策（VPS 30 天、180 天冷却） | https://www.hostinger.com/support/9088216-what-is-hostinger-refund-policy/ |
| 7 | 续费周期（KVM VPS：1/12/24 个月） | https://www.hostinger.com/support/1583589-how-to-pay-for-hostinger-services-in-advance/ |
