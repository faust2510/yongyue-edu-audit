# t11：菜单收口的"重放"缺陷（F1）——复现、根因、修法与证据

> 责任：menu-eng ｜ 日期：2026-09-17 ｜ 环境：本地 edu19（docker compose）
> 关联：t2（菜单收口落库）、t7（独立验证提出的 F1）、`scripts/consolidation_persist.py`

## 1. 现象与复现（先证伪"看起来没事"）

复现步骤（改动前）：

```bash
bash scripts/safe_upgrade.sh edu_portal      # 升级"别的"模块
# 现场实测（前端 load_menus，新会话）
#   admin 14 → 19 ｜ backoffice 12 → 17（**超验收线 12**）｜ faculty 9 → 12
```

复活的 5 棵根（实测逐条）：

| 根菜单 | id | xmlid 归属 | -u edu_portal 后 |
|---|---|---|---|
| 邀请码 | 542 | `edu_portal.menu_edu_invite_code_root` | active=True groups=[4,40] |
| 日常管理 | 543 | `edu_portal.menu_edu_welfare_root` | active=True groups=[1] |
| 在线课程 | 576 | `edu_portal.menu_edu_lms_root` | active=True groups=[1] |
| 行政评估 | 597 | `edu_eval.menu_edu_admin_eval_root` | active=True groups=[1] |
| 老账号补挂身份 | 606 | `edu_portal.menu_edu_relink_identity` | active=True groups=[4,40] |

## 2. 根因（读 Odoo 19 源码确认，不靠猜）

- 这些菜单的 `ir.model.data.noupdate = False`（实测全库 605 条都是 0）。
- 任何模块被 `-u` 时，会用**自己 XML 里的原定义**写回它的记录：
  `odoo/orm/models.py::_load_records`
  ```python
  if not (update and d_noupdate):     # update=True 即升级；d_noupdate 来自 xmlid 记录
      to_update.append(data)
  ```
- 因此"谁最后跑谁赢"：`-u edu_portal` 把 5 棵根写回收口前的值，而 `edu_nav` 不在这条升级链路里。

**影响面**：`edu_nav` 数据文件覆盖的 **357 条菜单分布在 47 个模块**（account 53 / mail 33 /
hr_recruitment 27 / … / edu_portal 10 / openeducat_* 13）。也就是说 **47 个模块都是潜在重放源**。
（"改 47 处 XML 源码"不可行：多数属 Odoo 核心与 `openeducat_erp/` 基座——后者是只读红线。）

## 3. 修法：保护菜单 xmlid（`noupdate=1`）

`ir_model.py::_build_update_xmlids_query`：
```sql
INSERT INTO ir_model_data ... ON CONFLICT (module, name)
DO UPDATE SET (model, res_id, write_date) = (EXCLUDED.model, EXCLUDED.res_id, now())
-- **不含 noupdate** ⇒ noupdate 一旦置 1，不会被后续升级重置
```
⇒ 把受影响菜单的 xmlid 记录置 `noupdate=1`：其它模块升级时"不改值"（跳过 write），
但记录本身仍在（xmlid 存在 ⇒ 不会产生重复菜单）。

工具：`python3 scripts/consolidation_persist.py --status|--dry-run|--protect|--unprotect`
（`--apply/--rollback` 为兼容别名；`--protect` 先写备份 `noupdate-backup.json`）。

### 3.1 ⚠ 顺序陷阱（实测踩到）

`noupdate=1` **也会挡住 edu_nav 自己**（同一条 `_load_records` 分支）。所以"改菜单"的顺序必须是：

```bash
python3 scripts/consolidation_persist.py --unprotect    # 1
python3 scripts/gen_menu_data.py --state=baseline       # 2
bash scripts/safe_upgrade.sh edu_nav                    # 3
python3 scripts/consolidation_persist.py --protect      # 4
```
只跑 2/3 会"升级成功但菜单没变"（实测：仍是 19/17/12，不是 14/12/9）。

## 4. 证据

### 4.1 逐个模块升级（6 个代表）后仍保持收口

| 升级的模块 | admin 根 | backoffice 根 | faculty 根 | 判定 |
|---|---|---|---|---|
| edu_portal | 14 | 12 | 9 | ✅ |
| edu_eval | 14 | 12 | 9 | ✅ |
| edu_life | 14 | 12 | 9 | ✅ |
| edu_apply | 14 | 12 | 9 | ✅ |
| edu_quiz | 14 | 12 | 9 | ✅ |
| base | 14 | 12 | 9 | ✅ |

### 4.2 一次性升级 **45 个归属模块**（更强证据）

```bash
bash scripts/safe_upgrade.sh account,mail,hr_recruitment,hr,website_slides,contacts,hr_attendance,\
hr_skills,gamification,calendar,openeducat_core,im_livechat,data_recycle,utm,event,openeducat_exam,\
spreadsheet_dashboard,hr_gamification,resource,account_payment,openeducat_attendance,website_slides_forum,\
openeducat_assignment,onboarding,digest,iap,phone_validation,privacy_lookup,sms,website_livechat,\
base_automation,rating,hr_recruitment_skills,auth_oauth,snailmail,board,base_import_module,web_tour,\
openeducat_admission,hr_skills_slides,hr_skills_event,edu_portal,edu_eval,edu_apply,edu_quiz
```
结果：**无失败特征**；升级后 **admin 14 ｜ backoffice 12 ｜ faculty 9**；
全库菜单 **605**、根 **40**、停用 **200**（与收口后完全一致）。

### 4.3 `--protect/--unprotect` 是**可逆**的（反向验证）

- `--unprotect` 后再 `-u edu_portal` → 5 棵复活（19/17/12）：证明保护确实是那条开关，不是巧合。
- 再按 §3.1 正确顺序执行 → 回到 14/12/9。

## 5. 副作用与维护规则（必须知道）

- **副作用**：被保护的 357 条菜单**不能再靠模块 XML 改**（改了不生效）。
- **所以菜单口径的唯一入口变成 `edu_nav` 的数据文件**，改菜单的流程固定为 §3.1 的四步。
  这与 t2 的施工方式一致（本就把菜单改动集中到 edu_nav）。
- 若某天要"交还"控制权：`--unprotect` 即还原（依备份），然后把相应 XML 改回即可。
- 不影响这些模块的其它数据；不影响 `ir.ui.menu` 记录本身（不增不删，全库仍 605 条）。

## 6. 未核项 / 残留风险

- 未逐个升级**全部 47 个模块**（做了 6 个代表 + 一次性 45 个合并升级）；合并升级已覆盖全部 45 个的
  重放路径，但"单模块顺序组合"未穷举。
- 保护是"按菜单 id"的，若将来有**新模块**定义同名菜单 xmlid 或新建根菜单，需重新跑 `--status` 复查。
- `noupdate` 保护不影响前端缓存；测量一律用**新登录会话**（`load_menus` 按会话缓存，t2 已踩过）。

## 7. 口径对照：**357** 与 **419** 不是同一个量（防"第四次两套数字"）

> 起因：队长独立抽验时查 `ir_model_data where model='ir.ui.menu' and noupdate=true` = **419**，
> 而我的报告写"357/357 受保护"。两个数都对，但**口径不同**，必须并列写清。

| 数 | 口径（谁能复算） | 当前值 | 该用它回答什么 |
|---|---|---|---|
| **357** | `edu_nav` **声明要改写**的菜单条数 = `ir_config_parameter edu_nav.consolidated_count`（由 `gen_menu_data.py` 写入，与模块常量 `MENU_CONSOLIDATED_COUNT` 同值） | 357 | "这次菜单收口动了多少条"、"守卫该不该报漂移" |
| **419** | **实际被置 `noupdate=1` 的菜单 xmlid 总数** = `select count(*) from ir_model_data where model='ir.ui.menu' and noupdate=true` | 419 | "有多少条菜单**不会再被模块升级重放**"（= 防护面） |
| 差额 **62** | 受保护但**不在 edu_nav 声明内**的那部分 | 62 | 说明这两个数为何必然不等 |

### 62 条的构成（实测）

- **合并进容器、或因收口而停用的子孙节点**（它们的父级被改写，子孙随之下线，但不在 `edu_nav` 的
  357 条声明里）；例如 `openeducat_core.menu_op_school_main`(258) / `menu_op_faculty_main`(259) 等；
- **`--protect` 按"当前可见/受影响集合"施加保护**时的边界外延（如 `base.menu_management`(15)、
  `website.menu_website_configuration`(218) 及其子孙）；
- 另含**非 edu_nav 目标的受保护记录**（例如导航侧 `/jobs` 入口 205/206 —— 它们是
  `website_hr_recruitment` 重建出来的，属导航问题，见 `scripts/check_nav_jobs_entries.py`）。

### 现状快照（同一时刻取，供复核对齐）

| 指标 | 值 |
|---|---|
| `edu_nav.consolidated_count`（声明条数） | **357** |
| `ir_model_data` 受保护菜单 xmlid（`noupdate=true`） | **419** |
| 其中菜单当前 `active` | 221 |
| 其中菜单当前 `inactive` | 198 |
| 受保护集合中被明确引用为"edu_nav 数据文件覆盖"的 | **357 / 357（覆盖率 100%）** |

> **一句话**：报"收口动了多少"用 **357**；报"防重放护住了多少"用 **419**。
> 两者都必须在同一句里带上口径名，否则就会变成"同一件事两个数"的第四次事故。
