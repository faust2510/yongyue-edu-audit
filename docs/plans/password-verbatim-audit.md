# 改密码「逐字保存」审计（2026-09-24）
> **状态**：`归档` ｜ **主题**：`改密码逐字保存` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

**事故类**：Odoo 登录端（`session.authenticate` / `_check_credentials`）对提交的口令**不做任何归一化**，
而任何把密码两端 `strip()` 掉的入口都会让「用自己敲的密码登录」永久失败。
2026-09-24 生产事故的第一处是邀请码注册（`controllers/register.py`，已修）；
本文是**全表面清点**与第二处的处置。

## 1. 结论一览

| # | 门（用户实际走的路） | file:line（strip 发生处） | 会不会 strip | 处置 |
|---|---|---|---|---|
| 1 | 门户自助改密 `/my/password` → `/my/password/save` | `controllers/my_password.py:53` → `res.users.change_password` → core `base/models/res_users.py:920` `new_passwd = new_passwd.strip()` | **会（改前）** | ✅ 本次修：`models/res_users_password.py:44` 覆盖 `_change_password`，逐字保存；控制器里「新密码首尾不能有空格」的自保守卫同时撤除（它只是 core strip 的权宜之计，与注册/登录口径不一致） |
| 2 | 后台「修改密码」向导（管理员给别人设密码）`change.password.wizard` | `base/models/res_users.py:1461` → `:1481` `line.user_id._change_password(line.new_passwd)` | **会（改前）** | ✅ 同一 choke point，已被覆盖；odoo shell 实测「带尾空格 → 可登录 / 去空格 → 不可」 |
| 3 | 个人偏好里的自助向导 `change.password.own` | `base/models/res_users.py:1501` `self.env.user._change_password(self.new_password)` | **会（改前）** | ✅ 同一 choke point；该方法是 `@check_identity` 的 HTTP-only 动作（shell 跑不到），故只留代码级证据 |
| 4 | 后台用户表单「管理员设/改用户密码」 | 19.0 的用户表单**没有** `new_password` 字段（`ir.ui.view` 实测：全库只有 `change.password.own` 表单与门户模板出现该名）；Security 页只剩两个按钮 → `:995 action_change_password_wizard` / `:1004 preference_change_password`，都进 `:1481`/`:1501` | 同 2/3 | ✅ 已覆盖（表单本身没有独立的写值入口） |
| 5 | 邮箱重置令牌 `/web/reset_password?token=…` | `auth_signup/controllers/main.py:87-121` → `models/res_users.py:63` `partner_user.write(values)`；取值处 `:153-157` 原样 | **不会** | 无需改。**未端到端验证**：本机没有邮件服务器，重置邮件正文取不到 token（见 §4） |
| 6 | 邀请码注册 `/register/submit` | `controllers/register.py:127` `Users.create({'password': …})` | **不会**（2026-09-24 已修） | 回归：`tests/smoke/register_password_verbatim.py` |
| 7 | auth_signup 自助建号 `_signup_create_user` | `auth_signup/models/res_users.py:118-127` → `copy(values)` | **不会**（落点 `write/copy`，实测逐字） | 本机该门被外层门禁拒（`不允许未经邀请的用户注册`），未端到端 |
| 8 | **core portal `/my/security` 页的改密表单** | **`portal/controllers/portal.py:877-879`**：`post['old'].strip(), post['new1'].strip(), post['new2'].strip()` | **会 —— 而且在控制器里，先于模型** | ⚠ **core 未改（越界）**：strip 发生在进模型之前，模型层覆盖**够不到**。导航改指 `/my/password`（见 §3）；core 路由原样保留、URL 仍可访问 |
| 9 | 哈希与存储 | `_set_password` → `_set_encrypted_password`（pbkdf2_sha512） | —— | **一行未动**（本次只改「值」） |

门 8 的实测复现：在该页把密码改成 `"DoorsPass456 "` → 页面回「Password Updated」，
但登录只认 `"DoorsPass456"`（`tests/smoke/password_doors_verbatim.py`）。

## 2. 改法（为什么在模型层）

`custom_addons/edu_portal/models/res_users_password.py:44` 覆盖 `res.users._change_password`：
保留 core 的全部语义（空值/纯空格明确拒收、同样的改密审计日志），只去掉那句 `strip`，
末行仍是 `self.password = new_passwd`（哈希/字段不变）。
一个 choke point 同时罩住门 1/2/3/4；注册与重置本就不 strip，无需动。

## 3. 导航决策（2026-09-24，负责人拍板 **B**）

- **A（在 edu_portal 覆盖 `/my/security` 路由）不做**：等于复刻 core 控制器，且每次 Odoo 升级都要再复刻一次 —— 对本校而言漂移风险大于收益。
- **B（撤掉我们自己暴露的这扇门）已执行**：门户用户菜单、移动端底部 Tab、`/my/apps` 卡片、图标 SPEC 一律指 `/my/password`；
  标签同步改「修改密码」（落点是密码表单，标签就不能许诺「账户与安全」）。
  涉及：`views/edu_portal_templates.xml:82,240`、`controllers/batch2.py`（`_COMMON_CARDS` / `FA_HOME_ICONS` / 个人与设置分组）、
  `scripts/gen_icons.py:136`、`tests/smoke/zero_loss_reachability.py:48`。
- **core `/my/security` 路由未动**，URL 仍可访问（不破坏任何既有链接）。
- 历史文档里的旧引用（`docs/plans/study-hub-v3-design.md:244,362`、`tests/gap/R_roles.md:44`）是记录，不改写。

### 3.1 `/my/security` 有而我们的页没有的（**已裁定：不加「账户与安全」入口**）

| 区块 | 本机状态 | 说明 |
|---|---|---|
| 双重身份验证（TOTP） | `auth_totp` **已安装**，该页有 2FA 区块 | 全校**无人使用**（见下方裁定证据） |
| 撤销所有会话 | 页面有该按钮 | 会话管理入口 |
| 删除账户（自助注销） | 页面有（`portal._update_password` 同文件的 `deactivate_account`） | |
| API 密钥 | **不显示**（`portal.allow_api_keys` = False） | 本校未启用 |

**裁定（2026-09-24，负责人；生产库读数）**：**不**新增「账户与安全」入口 ——
生产 38 个账号里 `users_with_totp = 0`（`auth_totp` 模块装了但**无人启用**）。
一个只为暴露「没人用的功能」而存在的入口、且门后还挂着本文档 §1 门 8 的密码 strip 陷阱
（core `portal/controllers/portal.py:877-879`），净收益为负。core `/my/security` 路由
**保持原样、URL 仍可访问**：将来管理员真要开 2FA / 撤销会话 / 注销账户，手输 URL 即可。
⇒ 这里的「缺」是**决定**，不是遗漏；下次读到本页不要顺手把入口加回来。

## 4. 未验证 / 已知缺口

1. **重置令牌门**没跑成端到端：本机无邮件服务器，`/web/reset_password` 提交后回「指引已发送」但邮件正文取不到 token。
   已退一步用模型层证据：该门的落点就是 `write({'password': …})`，实测逐字（`tests/smoke/password_doors_shell.py` 门 4）。
2. **`change.password.own` 自助向导**（`@check_identity`，HTTP-only）未真跑，仅代码级证据。
3. **移动端底部 Tab 被在线聊天悬浮球压住**（本次实测发现，**非本次改动引入**）：最后一个 Tab 在 390px 视口下与聊天球重叠，
   真人点不到 —— 现在这个 Tab 指向的正是「修改密码」。证据：`tests/smoke/out_password_nav/06_mobile_overlay_blocks_tab.png`。
   **未修**（不属本任务 inScope），请另开任务。
4. **改密成功条看不到**（既有行为）：改密会让当前会话立即失效（session token 由口令哈希派生）⇒ 303 到
   `/my/password?ok=1` 后浏览器落到 `/login?redirect=…`，页面上「密码修改成功」的成功条实际不可达。
   本次未改（既不属 strip 事故，也涉及会话语义）。

## 5. 证据与复跑

| 证据 | 命令 | 结果 |
|---|---|---|
| 门户 + RPC 两门的改前/改后 | `python3 tests/smoke/change_password_verbatim.py before\|after` | before：敲的密码登录失败(200) / 去空格成功(303)；after：**反过来**；`_check_credentials` 同向。JSON：`change_password_verbatim_{before,after}.json` |
| 其余门（`/my/security`、重置令牌） | `python3 tests/smoke/password_doors_verbatim.py` | `/my/security` 如实记为**已知 core 缺口**（仍是 strip）；重置门记 SKIP + 原因 |
| 向导/写入口（shell） | 见 `tests/smoke/password_doors_shell.py` 头部的 `docker compose cp … odoo shell` 三段 | 门 1/2/3/4 全部「带尾空格 ✓ / 去空格 ✗」；门 6（`new_password` API）实测为静默空操作 |
| 真浏览器端到端（走导航） | `python3 tests/smoke/change_password_nav_browser.py` | ALL PASS；截图 + URL 落 `tests/smoke/out_password_nav/`（`nav_result.json` 记录每步 URL） |
| 清场 | 各脚本自清；邮件行由 odoo shell 的 sudo 清（`mail.mail` 的 unlink 规则不让 admin 走 RPC） | 一次性账号/伙伴/邮件行 0 残留；`change_password_verbatim.py` 自身核对 7/132/1744 → 7/132/1744 回基线（库里有其他 agent 并发写，故以脚本内 same-process 基线为准） |
