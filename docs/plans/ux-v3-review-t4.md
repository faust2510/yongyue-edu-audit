# t4 独立评审：Odoo 痕迹清零（评审人 i18n-eng / t10）
> **状态**：`归档` ｜ **主题**：`Odoo 痕迹清零评审` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 评审时间：2026-09-12 ｜ 被评审任务：**t4**（实现者 brand-eng，status=completed）
> 评审方式：**只读取证**。所有数字均为本轮独立执行，未复用实现者自述。
> 被评审对象 commit：`7b43a49`（批次聚合提交，见 §7 归因限制）。

## 结论：**needs_revision**

**5 条 acceptance 字面上全部通过**（逐条证据见 §1），但 acceptance 本身**覆盖不足**：
t4 的 objective 写的是「在**所有用户可见界面**上都看不到 Odoo 字样、odoo.com 外链」，
而**邮件面**（密码重置邮件、每周摘要邮件）仍存在两处用户可见的 Odoo 痕迹，
且门禁 `check_odoo_trace.py` **结构上无法发现**它们（只扫 HTTP 路由，不扫邮件）。
按「对用户可见结果负责，而不是看代码是否跑了」的评审要求，判 needs_revision。

> **后续（指针，2026-09-12 追加）**：本报告 F1–F5 已由 t31（F1/F3/F4/F5）与 t44（F2 治根）处理；
> 其中 F1（密码重置邮件）与 F2（每周摘要）经 **t45 复评实测 pass**（真实渲染 odoo=0 / odoo.com=0）。
> **本报告判定保持原样**（时间点快照，不改写 verdict 与 findings 正文）。

---

## 1. 五条 acceptance 逐条判定

### AC1 `check_odoo_trace.py` 0 命中（4 角色 + 公开站）→ ✅ 通过

- 实测：`python3 scripts/check_odoo_trace.py` → **exit 0**，
  「PASS：Odoo / 基座品牌痕迹 0 命中（公开站 23 + 4 角色 26 + 后台 1 = 50 条静态路由，另含动态发现）」。
- 路由覆盖（`--list-routes`）：公开站 23 + 学生 10 + 教师 5 + 家长 3 + 教务 8 + 后台 1 = 50，
  另含**动态发现**（`/my/study/<id>`、`/my/study/session/<id>/join`、`/my/courses/lesson/<id>`、`/my/calendar/ics/<token>`）。
- 自证：`--selftest` → **exit 0**，10 个样本判定全部符合预期，v3 必需路由确在清单内，动态发现 4/4。
- ⚠️ 两点必须记录：
  1. **门禁不是 t4 交付时那一版**。当前工作区的 `scripts/check_odoo_trace.py` 有**未提交改动**
     （+207/−41，标注 t22），补了 v3 新路由、加了 `openeducat` 命中规则、加了 `--selftest`。
     我核对过 diff：**是加强不是放宽**，所以「0 命中」的结论比 t4 交付时更强。
  2. 该门禁**只扫 HTTP 路由**，结构上看不到邮件与 JS 运行时渲染的用户菜单 → 见 F1/F2/F3。

### AC2 /login、/register、/apps 可用；旧路由 302 → ✅ 通过（一处口径出入）

| 路由 | 实测 | 判定 |
|---|---|---|
| `/login` | 200 | ✅ |
| `/register` | 200 | ✅ |
| `/apps` | 匿名 303 → /my/home；内部用户 200 | ✅（与实现者声明的分层一致） |
| `/web/login` | **302 → /login** | ✅ |
| `/web/register` | **302 → /register** | ✅ |
| `/openeducat/apps_menu` | 匿名 303 → /my/home；**内部用户 302 → /apps** | ✅（口径出入见下） |

口径出入：AC 原文写「均 302」，实测 `/openeducat/apps_menu` 对匿名是 **303**、对内部用户才是 302。
303 是 See Other、语义正确（避免 POST 重放），不构成缺陷，但**验收标准与实测不一致**，记此澄清。

### AC3 教师登录落门户；门户侧栏对教师无后台入口 → ✅ 通过

- `faculty@local` 登录后 GET `/web/login` → 最终 `/my/home` 200；GET `/login` → 最终 `/my/home` 200。
- `/my/home` 与 `/my/apps`：**无「管理后台」字样**、`/web#` 计数 = **0**。
- 对照（三层策略）：`backoffice@local` 访问 `/web/login` → 最终 `/web` 200（教务/管理员保留后台，符合设计）。

### AC4 无 /shop 残留、无前台搜索弹窗 → ✅ 通过

- 公开站 10 条路由（`/ /about /programs /admissions /journal /contactus /login /register /apply /courses`）
  逐页 grep `/shop(/cart|/wishlist)?` → **全部 0 处**。
- DB：`ir_ui_view.key='website_sale.search'` → `active = f`（停用，且实现者已声明为可回滚项）。
- 覆盖：`website_sale.header_cart_link`、`website_sale_wishlist.header_wishlist_link` 均由 edu_brand 视图覆写
  （`yy_hide_wsale_cart` / `yy_hide_wsale_wishlist`，实测存在于 ir_ui_view）。

### AC5 默认发件人非 noreply@odoo.com；用户菜单无 odoo.com 外链 → ✅ 通过

- `mail.default.from = scrtsschool@gmail.com`（ir_config_parameter）；`res_company.email = scrtsschool@gmail.com`。
- `edu_brand/models/ir_mail_server.py` 覆盖 `_get_test_email_to()`（Odoo 19 里唯一 `noreply@odoo.com` 来源）。
- 用户菜单：`session_info` 中 **无 odoo.com**，且 `support_url = "/my/help"`（`ir.http.session_info` 覆盖生效）。
- `edu_brand/static/src/js/user_menu_debrand.js` 的 `items.remove("support")` 与
  `items.remove("odoo_account")` —— **我逐字核对了 Odoo 19 核心源码**：
  `user_menu_items.js` 末尾 `registry.category("user_menuitems").add(...)` 注册名正是
  `support / shortcuts / separator / preferences / odoo_account / install_pwa / log_out`。
  注意 `odooAccountItem` 内部字段是 `id: "account"`，但**注册键是 `odoo_account`**，
  `registry.remove()` 按注册键生效 → 两个 remove 均**有效**（我最初误判为 no-op，核对源码后推翻）。
- 该 JS 确实进了 bundle：`__manifest__.py` 的 `web.assets_backend` 声明，实测
  `/web/assets/769edb1/web.assets_web.min.js` 6,980,338 bytes 可取回。

---

## 2. Findings（阻塞项）

### F1 —— 密码重置邮件仍渲染 Odoo 与 odoo.com 外链（severity: **high**）

- **问题**：`auth_signup.reset_password_email` **没有任何模块覆盖**（实测
  `SELECT v.key ... WHERE d.module='edu_brand' AND v.inherit_id IN (SELECT id FROM ir_ui_view WHERE key LIKE 'auth_signup%')` → 空）。
  我**实际渲染**该模板（odoo shell，`ir.qweb._render`），输出 4695 字节，其中包含：

  ```html
  <tr><td style="text-align: center; font-size: 13px;"> 技术支持
    <a target="_blank" href="https://www.odoo.com?utm_source=db&amp;utm_medium=auth"
       style="color: #875A7B;">Odoo</a> </td></tr>
  ```

- **为什么用户一定看得到**：登录页有可见入口
  `<a class="btn btn-link btn-sm" href="/reset_password?db=edu19">重置密码</a>`；
  该模板由 `auth_signup/models/res_users.py:206` 在标准重置流程中引用。
  学生/教师/家长重置密码 → 收到的邮件页脚写着「技术支持 Odoo」+ 指向 www.odoo.com。
- **为什么 AC1 抓不到**：`check_odoo_trace.py` 只扫 HTTP 路由；邮件不是路由 → **结构性假阴性**。
  且注意译文把 "Powered by" 翻成了「技术支持」，门禁的 `Powered by` 启发式也失效。
- **file**: `custom_addons/edu_brand/views/odoo_debrand.xml`（邮件类覆写已有先例：
  `yy_mail_notification_layout` / `yy_mail_notification_light` 就在这里）
- **requiredFix**：新增 t-inherit 覆盖 `auth_signup.reset_password_email`，
  把页脚那个 `<a ...odoo.com...>Odoo</a>` 所在节点 replace 成 `<span/>` 或品牌文案（照抄 yy_totp_login_doc 的写法）。
  改完必须**渲染验证**（`ir.qweb._render` → 断言不含 `odoo.com`），不能只看 arch。

### F2 —— 每周摘要：zh_TW 名称含 "Odoo"，且摘要邮件渲染 odoo.com（severity: **high**）

- **问题 1（数据）**：`digest_digest` id=1，`state='activated'`、`periodicity='weekly'`，其
  `name = {"en_US": "Your Odoo Periodic Digest", "zh_CN": "系统各功能状态日报", "zh_TW": "你的 Odoo 定期摘要"}`
  → **zh_TW 用户看到的是「你的 Odoo 定期摘要」**，字面含 Odoo。
  （本仓 `faculty@local` 的语言正是 `zh_TW`，非空想。）
- **问题 2（模板）**：`digest.digest_mail_main` 渲染输出含 `odoo.com`，且**无任何模块覆盖**。
- **可触发性**：`ir_config_parameter.digest.default_digest_emails = True`（新内部用户默认收到摘要）。
- **file**: `custom_addons/edu_brand/data_brand/brand_debrand_data.xml`（数据面）+
  `custom_addons/edu_brand/views/odoo_debrand.xml`（模板面）
- **requiredFix**：① 用 `<function model="digest.digest" name="write">`（照抄同文件里 res.company 的写法，
  每次 -u 重放）把三条语言的 name 都改成中文（zh_TW 去掉 "Odoo"）；
  ② 覆写 `digest.digest_mail_main` 的 odoo.com 页脚。若判定「本地不开摘要」，
  至少要显式 `state='deactivated'` 并在评审记录里写明理由。

### F3 —— 门禁结构性地看不见邮件面（severity: **medium**）

- **问题**：AC1 依赖的 `check_odoo_trace.py` 只遍历 HTTP 路由。F1/F2 两处**用户可见**泄漏
  在门禁下**恒为 0 命中**——这正是任务书要求我核查的「扫描覆盖是否存在假阴性」。
  相似地，后台 `/web` 只扫首屏 HTML 文本+外链，**JS 运行时渲染**的用户菜单项（本次已确认安全）
  与后台设置页的摘要名称都不在其视野内。
- **file**: `scripts/check_odoo_trace.py`
- **requiredFix**：加一个 `--mail` 模式：在 odoo shell 内渲染邮件类模板
  （`mail.mail_notification_layout`、`mail_notification_light`、`auth_signup.reset_password_email`、
  `digest.digest_mail_main`）并断言不含 `odoo.com`/`odoo`；把它并入默认退出码。
  无法渲染的模板要**显式列进「未覆盖」清单**，不能静默跳过。

### F4 —— `/reset_password` 把用户甩到 `/web/reset_password`（severity: **low**）

- **问题**：`/reset_password?db=edu19` → **302 → `/web/reset_password?db=edu19`** → 200。
  即 t4 新加的友好别名只做了转发，用户地址栏最终停在 `/web/...`。
  按门禁自己的规则「其余任何 `/web/xxx` 一律计为残留」，若该路由被扫描就会命中；
  而 `--list-routes` 的公开站清单里**没有** `/reset_password` → 又一处覆盖盲区。
- **file**: `custom_addons/edu_portal/controllers/main.py`
- **requiredFix**：要么让 `/reset_password` 真正渲染表单（像 `/login`、`/register` 那样 200），
  要么把它加进门禁路由清单并接受 /web 前缀（二者选一，写进注释）。

### F5 —— 去品牌化所依赖的 config 未进版本库（severity: **low**）

- **问题**：`config/odoo.conf` 被 `.gitignore:12` 忽略，实测含 `list_db = False`、`db_name = edu19`；
  但受版本控制的 `config/odoo.conf.example` 仍是 **`list_db = True`**（最近一次提交 9ac86b9）。
  即「隐藏数据库列表/管理器/选择器」这项成果**无法从仓库复现**（新克隆会带出 Manage Databases）。
- **file**: `config/odoo.conf.example`
- **requiredFix**：把 example 里的 `list_db` 改为 `False` 并加一行注释说明原因
  （与 docs/research §1「官方文档明确推荐」对齐）。

---

## 3. 铁律合规检查

| 铁律 | 实测 | 判定 |
|---|---|---|
| Odoo 19 语法（`group_ids`/`<list>`/`invisible` 表达式） | 本次改动以视图继承/JS patch/模型覆写为主，未引入旧语法；`edu_brand` 新模型用 `_inherit` 覆写 `ir.http`/`ir.mail_server`/`publisher.warranty.contract` | ✅ |
| 不建自定义组 | 新增代码未见自定义 `res.groups`；`base.menu_theme_store`/`menu_third_party` 复用 `base.group_no_one` | ✅ |
| 门户页外壳 `t-call="edu_portal.edu_page"` | 本次改动集中在`website.layout` 层（登录页/页脚/门户侧栏），未新开门户内容页 | ✅（不适用） |
| 写操作 POST+csrf 兄弟路由 | 本次改动新增路由（`/login`、`/register`、`/apps`、`/reset_password`）均为 GET 读取或 302 转发；`/web/login` 的 POST **原样放行**（实现者注释已说明 302 会降级成 GET 丢失凭据） | ✅ |
| `openeducat_erp/` 零改动 | `git show --name-only 7b43a49` 中无 `openeducat_erp/` 文件 | ✅ |
| 用户可见文案全中文 | 公开站/门户正文与 `check_english` must-fix=0 ✅；但**邮件面**存在英文/Odoo 字样（F1/F2） | ⚠️ 见 F1/F2 |

## 4. 超出 inScope 的文件（任务要求列出）

批次提交中出现、**不在 t4 契约 inScope** 的改动，共 **7 个**，与队长 2026-09-12 的**书面授权清单逐一对应**：

| 文件 | 授权状态 |
|---|---|
| `custom_addons/edu_brand/__init__.py` | ✅ 队长书面授权（计划不可编辑，无法登记进 inScope） |
| `custom_addons/edu_brand/models/__init__.py` | ✅ 同上 |
| `custom_addons/edu_brand/models/ir_http.py` | ✅ 同上 |
| `custom_addons/edu_brand/models/ir_mail_server.py` | ✅ 同上 |
| `custom_addons/edu_brand/models/publisher_warranty.py` | ✅ 同上 |
| `custom_addons/edu_portal/views/register.xml` | ✅ 同上（原无主） |
| `custom_addons/edu_portal/controllers/search.py` | ✅ 同上（原无主） |

> 结论：**无未授权的越界改动**。实现者没有碰 `openeducat_erp/`、`tests/`、别人的 inScope。

## 5. 评审限制（必须随报告传递）

1. **归因限制**：t4 的改动被并进**批次聚合提交 `7b43a49`**（t4+t5+t6+t7 一起），
   无法用 `git diff` 精确切出 t4 的文件集。§4 的结论依赖「文件内容与队长授权清单/实现者声明相匹配」，
   属**强推断**而非逐提交证明。批次内另有约 30 个文件（study.py、batch*.xml、ux_v3.css、
   edu_schedule、tests/smoke、docs/research 等）无法归因到单一任务，**不能据此指责 t4 越界**。
2. **门禁版本**：AC1 采信的是**加强后**的 `check_odoo_trace.py`（工作区未提交版本，+207/−41）。
   若评审要求严格复现 t4 交付时的门禁行为，需 `git stash` 后重跑——但那会削弱证据，故未做。
3. **未做的验证**：未用真实浏览器确认后台用户菜单的**运行时**渲染（仅从源码注册键 + bundle 内容推断）；
   未实际发送邮件（用 `ir.qweb._render` 直接渲染模板取真实输出）。
4. **生产未验证**：本评审全部在本地 `edu19` 进行。**生产是否受影响：未确认。**

## 6. 附：本轮关键命令（可复现）

```bash
export no_proxy="localhost,127.0.0.1"
python3 scripts/check_odoo_trace.py --selftest      # exit 0
python3 scripts/check_odoo_trace.py --list-routes   # 50 条静态 + 动态发现
python3 scripts/check_odoo_trace.py                 # exit 0，0 命中
curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}\n' 'http://localhost:8069/web/login?db=edu19'
# 渲染邮件模板（odoo shell）见脚本 /tmp/i18neng/rp2.py 与 mail_scan.py
```
