# t32 复评报告：t31「repair-round-2」（评审人 i18n-eng）
> **状态**：`归档` ｜ **主题**：`邮件去 Odoo 复评` ｜ **取代**：`t45-review-round3.md` ｜ **核对**：`2026-09-26`
> ⚠️ 本文已被 [`t45-review-round3.md`](t45-review-round3.md) 取代，请优先阅读后者。

> 复评对象：**t31**（实现者 brand-eng，status=completed）
> 复评依据：我 t10 的 5 条 findings（F1 密码重置邮件 / F2 每周摘要 / F3 门禁邮件面 / F4 /reset_password / F5 example 配置）
> 方法：**全部自己实渲染**，不采信自述；渲染用 `ir.qweb._render`，并对「探针上下文是否忠实于真实发送路径」做了专项核查。

## 结论：**needs_revision**

- **AC1 ✅ / AC4 ✅ / AC5 ✅** —— 修复到位，且我独立复现。
- **AC2 ❌** —— 摘要**名称**与 **by_odoo 页脚**确实修好了，但**真实摘要邮件**仍含 20 处 `odoo` + 1 处 `odoo.com` + 5 处 `/odoo/action-…` 后台链接 + 5 张 odoocdn.com 图片。根因是 **F2 只覆盖了"降级渲染"里可见的部分**（详见 §2.1）。
- **AC3 ⚠️ 判失败** —— `--mail` 模式本身实现完整（在默认退出码内、未覆盖计入失败），但 **探针上下文对 `digest.digest_mail_main` 不忠实**：探针渲染 3662 字节并报 odoo=0，而**忠实上下文渲染 34052 字节、odoo=20**。门禁给出的是**假绿**（详见 §2.2）。

> **后续（指针，2026-09-12 追加）**：本报告 F1（真实摘要邮件泄漏）与 F2（探针失真→假绿）已由 **t44 治根**，
> 经 **t45 复评 pass**（探针与忠实渲染同构 28358 vs 28359；真实渲染 odoo=0 / odoo.com=0 / odoocdn=0）。
> **本报告判定保持原样**（时间点快照，不改写 verdict 与 findings 正文）。

---

## 1. 逐条判定

### AC1 覆盖 auth_signup.reset_password_email 且渲染断言不含 odoo.com → ✅ 通过

- 代码：`custom_addons/edu_brand/views/odoo_debrand.xml:186` `<template id="yy_reset_password_email" inherit_id="auth_signup.reset_password_email">`。
- 锚点选得对：用 `//td[a[contains(@href,'odoo.com')]]` 而非 `contains(., 'Powered by')` ——
  中文 arch 里该文案已译为「技术支持」，按英文文本匹配会漏（我 t10 派单时提醒过这个坑，实现者照做了）。
- **我自己的渲染**（ir.qweb._render，admin 用户）：`len=4595  odoo=0  odoo.com=0`
  （t10 复评时同一模板为 4657 字节、odoo=2、odoo.com=1）。**修复成立**。

### AC2 摘要名称三语言中文 + 覆写 digest.digest_mail_main 页脚 → ❌ 失败（见 §2.1）

- 名称部分 **✅**：实测 en_US/zh_CN = 「系统状态摘要」、zh_TW = 「系統狀態摘要」，且**在 `-u` 重放后仍保持正确**
  （三个 `<function context="{'lang': ...}">` 写法正确；我特意在跑完一次 `-u edu_brand,edu_portal` 后重测，未退化、未串语言）。
- 页脚部分 **✅**（就它覆盖到的两块而言）：`div.by_odoo`、`p.by_odoo#powered` 已替换。
- **但整封邮件仍未去品牌化** ❌ —— 见 §2.1。

### AC3 增加 --mail 模式并并入默认退出码；未覆盖显式列出 → ⚠️ 判失败（见 §2.2）

- 形式完整 ✅：`MAIL_TEMPLATES` 4 支；`--mail` 单独可跑（MAIL_EXIT=0，4/4 覆盖 0 未覆盖）；
  **默认运行已包含邮件面**（完整运行输出第 96–101 行）；`uncovered → total[0] += 1 → main 返回 1`，**"验不了≠干净"的语义成立**（我读了代码路径确认）。
- **但探针不忠实 → 假绿** ❌，见 §2.2。

### AC4 /reset_password 二选一 + 注释 → ✅ 通过（选了 ②）

- `scripts/check_odoo_trace.py` 公开站清单已含 `/reset_password`（`--list-routes` 可见）；
  并有 `WEB_LINK_EXEMPT = {'/reset_password'}` 与一段**写明取舍理由的注释**（上游路由硬编码在 /web/*，不改核心命名空间是队长裁决）。
- 实测 `/reset_password → 302 → /web/reset_password`，与注释所述一致。
- 附：`odoo_debrand.xml:136-137` 还把页面上显示的链接改成 `/reset_password`（避免页面里出现 /web 链接），是个正确的加分项。

### AC5 config/odoo.conf.example list_db → ✅ 通过

- `config/odoo.conf.example`：`# list_db = False 与生产一致：隐藏数据库列表/管理器/选择器（去 Odoo 化的一部分）` + `list_db = False`（提交 4753b81）。
- 附注：`db_name` 那行是注释掉的（`# db_name = edu19`）—— 合理，db_name 是本地多库权宜，不应进可复用模板。

---

## 2. Findings（阻塞项）

### F1 —— 真实每周摘要邮件仍大量泄漏 Odoo（severity: **high**）

**问题**：用**忠实的**上下文（照 `digest/models/digest.py:159-178` 的 `_action_send_to_user` 逐字段构造：
`object/title/top_button_url/user/unsubscribe_token/formatted_date/display_mobile_banner/kpi_data/preferences/tips`）
渲染 `digest.digest_mail_main`，结果：

| 上下文 | 长度 | odoo | odoo.com | odoocdn |
|---|---|---|---|---|
| 门禁探针（`tips: []`、无 kpi_data） | 3662 | **0** | **0** | 0 |
| 忠实（`tips: []`，含 kpi_data/preferences） | 31582 | **14** | 1 | 5 |
| 忠实 + 真实 tips（`_compute_tips`） | 34052 | **20** | 1 | 5 |

泄漏分类（忠实渲染，按出现种类）：
- `https://www.odoo.com/web/image/38874595-…/odoo-mobile.png`，**`alt="Odoo移动端"`** ← 来自 `display_mobile_banner` 区块，
  正是 F2「页脚」之外没覆盖到的那一块（收件人会真的去 odoo.com 拉图）。
- **`/odoo/action-…` 后台命名空间链接 5 条**：`/odoo/action-account.action_move_out_invoice_type?menu_id=142`、
  `/odoo/action-im_livechat.im_livechat_report_operator_action` ×2、`/odoo/action-hr.open_view_employee_list_my?menu_id=196`、
  `/odoo/action-website.backend_dashboard?menu_id=218` —— 来自 KPI 区块，**连原始 action/模型名一起泄漏给收件人**。
- `odoocdn.com` 图片 5 张（`/digests/website/…`、`/digests/digest/…`）。
- tip 正文里的「Odoo」5 处，例如「**Odoo** 与 Unsplash 集成…」「在访问者使用 **Odoo** 社交应用程序浏览您的网站时监控他们」。

**为什么 F2 会漏**：F2 的验收（我 t10 写的）只点了「页脚 odoo.com」，实现者就只替换了 `div.by_odoo` / `p.by_odoo#powered` 两块。
**这是我 t10 验收写得不够完整**（只点了页脚，没点 `display_mobile_banner` 的 odoo.com 图与 KPI 的 /odoo 链接），
但客观结果是：**每周摘要邮件仍在给教务/教师发 Odoo 品牌与 odoo.com 外链**，与 t31 objective「所有用户可见界面上看不到 Odoo 字样/外链」冲突。

**file**: `custom_addons/edu_brand/views/odoo_debrand.xml`（F2 的继承就在这里）
**requiredFix**：在 `digest.digest_mail_main` 的继承里继续覆盖
① `display_mobile_banner` 区块（去掉 www.odoo.com 图片与 `alt="Odoo移动端"`）；
② KPI 区块里的 `/odoo/action-…` 链接（改为门户路由，或整块不渲染外链）；
③ tip 正文与 `odoocdn.com` 图片（要么改 `digest.tip` 数据、要么不渲染 tips）；
改完**必须用 §2.2 的忠实上下文**复验，不接受探针绿。

### F2 —— `--mail` 探针上下文不忠实，门禁给假绿（severity: **high**）

**问题**：`scripts/check_odoo_trace.py` 的 `MAIL_PROBE_TEMPLATE` 用**一套通用合成上下文**渲染全部 4 支模板：
`{'object': env.user, 'user': ..., 'digest': digest, 'tips': [], 'unsubscribe_token': 'PROBE-TOKEN', ...}`，
**缺 `kpi_data` / `preferences` / `title` / `formatted_date` / `display_mobile_banner`**。
对 `digest.digest_mail_main` 而言，缺 `kpi_data` 会让 KPI 区块整段不渲染 → 渲染 3662 字节而非真实 34052 字节 →
**F1 的全部泄漏点都落在探针看不见的那 90% 里**。

这不是"未覆盖"（探针确实渲染成功了）却也不是"干净"——**是探针口径与真实发送路径不一致造成的假绿**。
危险之处：门禁打印 `[邮件面] ok digest.digest_mail_main odoo=0`，任何人都会认为摘要邮件干净。

**file**: `scripts/check_odoo_trace.py`（MAIL_PROBE_TEMPLATE，约 275-292 行）
**requiredFix**：按模板分别构造**忠实上下文**，与真实发送路径一致：
- `digest.digest_mail_main` → 照 `digest/models/digest.py:_action_send_to_user` 逐字段构造（含 `kpi_data`、`preferences`、`tips=_compute_tips(..., consumed=False)`、`display_mobile_banner=True`）；
- `auth_signup.reset_password_email` → 含 `object`(res.users)/`user`/`company`/`email`；
- `mail.mail_notification_layout`/`light` → 含 `message`/`company`/`show_footer`。
并在注释里写明「探针上下文必须与真实发送路径一致，否则是假绿」。
可选加固：把真实发送路径的 values 抽成一个可复用的 helper，探针与发送共用，杜绝再次漂移。

---

## 3. 超出 inScope 的文件

t31 的改动**全部落在其 5 个 inScope 文件内**，无越界：

| 文件 | 状态 |
|---|---|
| `custom_addons/edu_brand/views/odoo_debrand.xml` | 工作区已改（+48），inScope ✅ |
| `custom_addons/edu_brand/data_brand/brand_debrand_data.xml` | 工作区已改（+22），inScope ✅ |
| `scripts/check_odoo_trace.py` | 工作区已改（+504/-42），inScope ✅ |
| `custom_addons/edu_portal/controllers/main.py` | 已提交（`/reset_password` 路由），inScope ✅ |
| `config/odoo.conf.example` | 已提交（4753b81），inScope ✅ |

**关于实现者自述的"迁回 odoo_debrand.xml"**：已核实 —— `custom_addons/edu_brand/views/mail_debrand.xml` **确实不存在**；
`edu_brand/__manifest__.py` 与基线无差异；工作区里 `edu_brand` 只有上述 2 个文件被改。**自述属实**。

> 工作区里另有 `edu_portal/controllers/roles.py`、`edu_portal/models/exam_session_ext.py`、`docs/dev-workflow.md`、
> `docs/plans/ux-v3-delivery.md`、`tests/smoke/*` 等改动，属其他任务（t13 复评、t7 相关、prod banner 素材），**不能归因 t31**。

## 4. 复评限制

1. **AC1 的渲染忠实度未做同等强度核查**：reset_password_email 我用了合理上下文（4595 字节 vs 实现者 4557），
   两者一致且 odoo=0；但我没有像对 digest 那样逐字段比对核心发送路径（该模板上下文简单，风险低）。若要求同等强度，需要再核一轮。
2. `mail.mail_notification_layout`/`light` 同理：我 t10 与本次渲染均为 odoo=0，未做发送路径逐字段比对。
3. 全部在本地 `edu19` 进行。**生产未验证。**
4. 我未修改任何被测文件（复评只读）。

## 5. 附：复评命令（可复现）

```bash
# 忠实上下文渲染摘要邮件（关键判据）
docker compose exec -T web odoo shell --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo \
  --no-http -c /etc/odoo/odoo.conf -d edu19 < /tmp/i18neng/real_digest3.py
# 门禁
python3 scripts/check_odoo_trace.py --mail
python3 scripts/check_odoo_trace.py --list-routes
python3 scripts/check_odoo_trace.py
```
