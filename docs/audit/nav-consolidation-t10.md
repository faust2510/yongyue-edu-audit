# t10：导航重复入口收口 + 校友岗位页中文化

> 责任：menu-eng ｜ 日期：2026-09-17 ｜ 环境：本地 edu19
> 工具：`scripts/fix_nav_duplicates.py`（--export/--dry-run/--apply/--rollback）、`scripts/check_nav_reachable.py`

## 0. 一句话结论

导航里 3 个指向**空页 `/jobs`** 的重复「工作/Jobs」入口已收口为 **0 个**；
「工作机会」改指有效页 `/campus/jobs`；**24 条导航目标在游客态与登录态全部可达**；
`/alumni/job/list` 的用户可见英文已中文化（`check_english.py` 仍 0 must-fix）。
`website.menu` 40 → 37 条；删除前有备份，`--rollback` **实测按原 id 重建**。

## 1. 收口前后对照（导出为证）

| 项 | 收口前 | 收口后 |
|---|---|---|
| `website.menu` 条数 | 40 | **37** |
| 指向 `/jobs`（原生空页）的入口 | **3**（191 工作 / 197 Jobs / 198 Jobs） | **0** |
| 「工作机会」(188) 的 url | `#`（空锚点，点了没反应） | **`/campus/jobs`**（200，2 条在招岗位） |
| 导航目标数（去重） | — | 24（游客/登录各请求一次） |

导出文件：`docs/audit/menu-consolidation/nav-tree-after.json`（含每条 id/name/url/parent/sequence）。

### 1.1 为什么「3 个重复入口」是"空页"而不是"404"

`/jobs` 实测 **HTTP 200 但内容空壳**：原生 `hr_job = 0` 条，页面正文只有页头与 JS 引导。
即"可达 ≠ 有内容"。这正是验收标准要防的形态：**只看状态码会把空页判成绿**。
（本仓 `check_english` 的门禁也秉持同一口径：路由状态不变量是"被扫路由必须 200"，
那是**必要条件**，不能替代"页面有内容"。）

## 2. 导航逐条可达（游客态 + 登录态）

判据（写在 `scripts/check_nav_reachable.py` 里，可复跑）：

1. 直接 200 → 通过；
2. 302/303 但**跟随跳转后 200**、且在显式登记的"设计性跳转"清单里 → 通过；
3. 404/5xx、或不在清单里的跳转 → 失败。

结果：**24/24 通过**。登记的三条设计性跳转：

| url | 行为 | 为什么是设计 |
|---|---|---|
| `/my-courses` | 游客 303 → `/web/login`；登录 200 | 受保护页的登录门禁 |
| `/login` | 已登录 303 → `/web` | 原生行为 |
| `/forum` | 302 → `/forum/帮助-1` | 原生 `website_forum` 唯一论坛跳转 |

## 3. `/alumni/job/list` 中文化

| 位置 | 改前 | 改后 |
|---|---|---|
| `models/alumni_job.py` state 标签 | Recruiting / Pending / Closed | **招聘中 / 待发布 / 已结束**（与仓内 `edu_eval` 的「已结束」口径一致） |
| `views/roles.xml` KPI 标签 | My Job Posts / Recruiting / Pending / Closed | **我的岗位 / 招聘中 / 待发布 / 已结束** |
| `views/roles.xml` 行内状态映射 | 同英文三词 | 同中文三词 |
| `views/roles.xml` 薪资行 | `Alumni Salary {n} · Payable At {x}` | **`校友薪资 {n} · 结算方式 {按月/按周/按年}`** |

验证：登录后打开 `/alumni/job/list` → HTTP 200，六个中文标签全部出现、5 个旧英文串 0 残留；
`python3 scripts/check_english.py` → **must-fix 0 / brand 0 / 路由状态违规 0**。

## 4. 备份与回滚（实测一次，留证）

```bash
python3 scripts/fix_nav_duplicates.py --apply     # 先写 nav-menu-backup.json，再删 3 条 + 188 改指
python3 scripts/fix_nav_duplicates.py --rollback  # 依备份按**原 id** 重建 + 还原 188
```

实测三次读数：

| 阶段 | `website.menu` 条数 | 指向 `/jobs` 的 id | 188 的 url |
|---|---|---|---|
| 收口后 | 37 | — | `/campus/jobs` |
| **rollback 后** | **40** | **191 / 197 / 198（按原 id 重建）** | `#`（原值） |
| 再 apply | 37 | — | `/campus/jobs` |

### 4.1 回滚实现踩过的两个坑（写下来供复用）

1. **ORM `create` 忽略显式 id**：第一版"重建"出来的是 203/204/205（新 id），回滚不可逆。
   修法：ORM 建记录 → SQL `UPDATE ... SET id = 原值`（并 `setval` 补齐序列）。
2. **`website_menu.name` 是 jsonb 翻译字段**：直接 SQL 插字符串报
   `invalid input syntax for type json`。修法：字段值交给 ORM 写，SQL 只改 id。
3. 另修一个**备份策略缺陷**：rollback 之后再 `--apply` 时 `drop=0`，
   若直接覆盖备份就会把"可回滚能力"静默摧毁；现在规则是"新备份可还原内容不减少才覆盖"。

## 5. 待办（本任务按口径**不改**）

- **「校友招聘」(189) 名实不符**：它指向 `/alumni/job/card`（一个"卡片/详情"式页面），
  名称却是"招聘"。登记为**下一轮岗位合并**处理（`edu.alumni.job`(3) 与 `edu.job.posting`(2)
  的合并属 t4 设计范围），本任务不改口径。
- 导航里仍有 2 条英文名（`Alumni & Careers`(124)、`Courses`(56/64)、`Shop`(201)）——
  属"术语/命名"而非本次验收面（本次只要求 `/alumni/job/list` 页面的用户可见英文），
  如需统一中文，它们是现成的下一批（改 `website.menu.name`，成本 1 条 SQL/条）。

## 6. 升级后仍生效

`--apply` 改的是 `website.menu` **记录值**（不是模块 XML），因此模块升级不会重放覆盖它；
实测：`bash scripts/safe_upgrade.sh edu_portal` 之后重查导航树仍为 **37 条、0 个 `/jobs` 指向、
188 仍指 `/campus/jobs`**。
