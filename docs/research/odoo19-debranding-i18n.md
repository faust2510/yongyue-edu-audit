# Odoo 19 去品牌化 + 中文汉化/中国化 调研

> 日期：2026-09-12 ｜ 方法：源码级取证（不依赖二手文章）
> 取证口径：Odoo 19.0 官方源码 tarball 全树 grep（48,209 个 blob），HEAD = [`c50a4e0`](https://github.com/odoo/odoo/commit/c50a4e0513e5247f1b680ccbb5c0d27795a10b55)（2026-09-11）；[OCA/server-brand 19.0](https://github.com/OCA/server-brand/tree/19.0) 源码；官方文档 `_sources/*.rst.txt` 原文与 `searchindex.js`（1.4MB）全文检索。
> **行号注意**：下文行号对应该 commit。本机镜像（`/usr/lib/python3/dist-packages/odoo`）版本不同会有偏移——实施时**以本机实测行号为准**（例：本机 `addons/web/models/ir_http.py:109` 才是 `support_url`，而非本文的 :114）。

---

## 0. 最重要的一条前提

**Odoo 官方文档里没有任何去品牌化（debranding）说明。** 对 19.0 文档检索索引全文统计：`branding`=0、`debrand`=0、`white label`=0（对照：`portal`=24、`website`=258）。
来源：[`searchindex.js`](https://www.odoo.com/documentation/19.0/searchindex.js)。

→ 结论：**只能读源码 + 参考 OCA**。凡是声称"官方支持去品牌化"的说法都不成立。

---

## 1. 去品牌化做法对照

| 做法 | 19.0 适配 | 优点 | 代价/风险 | 来源 |
|---|---|---|---|---|
| 装 OCA/server-brand 模块组 | ✅ 有 19.0 分支（`19.0.1.0.0`）；2026-01 仍有功能 PR | 开箱即用、走标准视图继承/注册表 | 多数 **AGPL-3**；覆盖有限（不管 JS 硬编码、邮件模板本体、默认发件人、favicon、URL） | [OCA/server-brand](https://github.com/OCA/server-brand/tree/19.0) |
| **自研 xpath 继承覆盖模板** | ✅ 唯一能全覆盖的路子 | 可控、增量、随上游 diff 维护 | 每条都要跟上游模板变化 | [webclient_templates.xml#L87-L108](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/addons/web/views/webclient_templates.xml#L87-L108) |
| JS registry remove（`user_menuitems`） | ✅ 有效 | 官方注册表机制，最小侵入 | 19.0 的 id 是 `support/shortcuts/separator/preferences/odoo_account/install_pwa/log_out`；OCA 里 `remove("documentation")` 在 19.0 是**空操作** | [user_menu_items.js#L137-L145](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/addons/web/static/src/webclient/user_menu/user_menu_items.js#L137-L145) |
| 继承 `ir.http.session_info` 改 `support_url` | ✅ 必须自研 | 一处干掉用户菜单 Help 外链（19.0 硬编码 `odoo.com/buy`） | 需自研 | [ir_http.py#L114](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/addons/web/models/ir_http.py#L114) |
| `--no-database-list` / `list_db = False` | ✅ **官方文档明确推荐** | 一次性关闭数据库列表 + manager + selector，并自动隐藏登录页 "Manage Databases" | 需重启服务 | [部署文档](https://www.odoo.com/documentation/19.0/administration/on_premise/deploy.html)（rst L583-586/L710-712）；[config.py#L415-L418](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/odoo/tools/config.py#L415-L418)、[db.py#L441](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/odoo/service/db.py#L441)、[home.py#L148](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/addons/web/controllers/home.py#L148) |
| `web.base.url`（+ `web.base.url.freeze`） | ✅ 官方系统参数 | 域名干净 | 写错会导致邮件/链接错 | [ir_config_parameter.py#L22](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/odoo/addons/base/models/ir_config_parameter.py#L22) |
| favicon / 页面标题 | ⚠ 前端走 website 设置；**后端硬编码** `/web/static/img/favicon.ico`，DB manager 页 `<title>Odoo</title>` | — | 后端需 xpath 或替换资产 | [webclient_templates.xml#L23](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/addons/web/views/webclient_templates.xml#L23)、[database_manager.qweb.html#L4](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/addons/web/static/src/public/database_manager.qweb.html#L4) |
| itpp-labs `web_debranding`（老牌全功能） | ❌ 最高只到 **16.0** | 一个模块全覆盖 | 17/18/19 无维护，**不能直接用** | [access-addons-store](https://github.com/itpp-labs/access-addons-store) |
| 第三方 apps 商店模块（`powered_by_odoo_remove` 19.0） | 页面存在 | 省事 | **license/价格未核实**、闭源依赖风险 | [apps.odoo.com](https://apps.odoo.com/apps/modules/19.0/powered_by_odoo_remove) |
| 改后端 URL（`/odoo`、`/web`、`/web/database/manager`） | ❌ **路由硬编码** | — | 反代改写**未验证**、风险高 | [home.py#L46](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/addons/web/controllers/home.py#L46)、[http.py#L2857-L2860](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/odoo/http.py#L2857-L2860) |

### 1.1 OCA 可复用清单（模块 / 19.0 / license / 作用）

| 模块 | 19.0 | license | 作用（读源码确认） |
|---|---|---|---|
| [`disable_odoo_online`](https://github.com/OCA/server-brand/tree/19.0/disable_odoo_online) | ✅ | **AGPL-3** | 关掉 `publisher_warranty` 回连；把 Apps/主题商店/第三方应用三菜单重挂到技术菜单；Apps 菜单改为打开**本地**模块列表；JS 移除用户菜单 `support`/`odoo_account` |
| [`portal_debranding`](https://github.com/OCA/server-brand/tree/19.0/portal_debranding) | ✅ Beta | **LGPL-3** | 隐藏 `web.brand_promotion`、portal 侧栏、**登录页 "Powered by Odoo"** |
| [`website_debranding`](https://github.com/OCA/server-brand/tree/19.0/website_debranding) | ✅ | **LGPL-3** | 继承 `web.brand_promotion_message` 置空；`customize_show=True` 可在网站定制里开关 |
| [`mail_debranding`](https://github.com/OCA/server-brand/tree/19.0/mail_debranding) | ✅ | **AGPL-3** | 发送时用 lxml 剥掉正文里 odoo.com 的 `<a>`；**不改模板本体** |
| [`remove_odoo_enterprise`](https://github.com/OCA/server-brand/tree/19.0/remove_odoo_enterprise) | ✅ | **AGPL-3** | 过滤 `to_buy` 模块与设置页 `upgrade_boolean` 区块 |

> **本仓决策**：已有 `edu_brand/views/odoo_debrand.xml` 承担该职责，引入 OCA 会形成"一个关注点两个所有者"；且其中 4 个是 AGPL-3，与本仓 `docs/compliance-audit.md` 的版权干净要求冲突。
> → **只借其触点清单（即本文档），自研补齐。**

---

## 2. 必须自研的触点清单（19.0 实测）

**A. 页面模板（xpath 继承）**
- `web.brand_promotion_message` / `web.brand_promotion`：[webclient_templates.xml#L87-L108](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/addons/web/views/webclient_templates.xml#L87-L108)
- `web.login_layout`：同文件 #L110-L134（#L126 Manage Databases、#L128 Powered by Odoo）
- portal 页脚：[portal_templates.xml#L283](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/addons/portal/views/portal_templates.xml#L283)（Powered by + `/web/static/img/logo.png`）、#L510 API key 外链
- 其它：website #L345-L353、website_sale #L4242-L4244、survey #L56、hr_attendance kiosk #L134/#L139、im_livechat #L79

**B. 邮件模板（QWeb，必改，否则每封通知邮件都带 Odoo 外链）**
- [mail_templates_email_layouts.xml#L86](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/addons/mail/data/mail_templates_email_layouts.xml#L86)（`mail.mail_notification_layout`，定义在 #L4）与 #L160（`mail_notification_light`，#L96）
- 其它：auth_signup（#L93/#L240/#L339 + `auth_signup_templates_email.xml`#L81）、gamification #L78、im_livechat #L105、website_slides #L69、lunch #L135、digest #L441

**C. JS 里写死的 odoo.com（xpath 无效 → 需 asset patch / CSS 隐藏 / 继承改值）**
- 升级弹窗 `upgrade_dialog.js`#L20（→ `odoo.com/odoo-enterprise/upgrade`）、`upgrade_dialog.xml`#L15
- 设置页 "Copyright © 2004 Odoo S.A."：`res_config_edition.xml`#L14
- `install_scoped_app.xml`#L24、`documentation_link.js`#L29（所有"文档"图标 → odoo.com/documentation）
- DB manager 页：`database_manager.qweb.html` #L4 标题 `Odoo`、#L39、#L108 隐私政策外链、#L150

**D. 菜单 / 外链 action**
- [ir_module_views.xml#L212-L230](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/odoo/addons/base/views/ir_module_views.xml#L212-L230)：`base.menu_apps`/`menu_module_tree`/`menu_theme_store`/`menu_third_party`；#L67、#L184 模块卡 "Upgrade" → `odoo.com/pricing`
- **132 个** `__manifest__.py` 的 `website` 字段指向 www.odoo.com
- 用户菜单 Help：`support_url = "https://www.odoo.com/buy"`（`addons/web/models/ir_http.py`#L114；本机镜像实测 #L109）

**E. 默认值 / 回连**
- **默认发件人 `noreply@odoo.com`**：[ir_mail_server.py#L282](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/odoo/addons/base/models/ir_mail_server.py#L282) —— **每封邮件都会露，最高优先**（本机镜像需另行定位）
- 更新回连：`--publisher-warranty-url` 默认 `http://services.odoo.com/publisher-warranty/`（`config.py`#L215），19.0 模型在 `addons/mail/models/update.py`#L20
- OdooBot 话术外链 `mail_bot.py`#L47；小痕迹 `res_partner_views.xml`#L94/L189、`res_company_views.xml`#L49
- ✅ 好消息：19.0 "Update Apps List" **已不再外连** odoo.com（`odoo/modules/module.py`#L538-L547）——但这是上游行为变化，**不算我们的成果**

---

## 3. 中文汉化 / 中国化

| 做法 | 19.0 适配 | 数据/优点 | 代价/限制 | 来源 |
|---|---|---|---|---|
| 官方 zh_CN | ✅ | 覆盖率实测：base 98.9%（6570 条/71 空）、web 97.6%、mail 98.9%、portal 97.8%、website 91.0%；zh_TW base 93.6% | zh_CN 属"有官方内部译者"语言，社区**只能提 suggestion**，上游改错译很慢 | [translate.odoo.com](https://translate.odoo.com/)、[Translations wiki](https://github.com/odoo/odoo/wiki/Translations) |
| **自研 `i18n_extra/zh_CN.po` 覆盖他模块词条** | ✅ 可行，但**默认不覆盖已有译文** | PO 的 `#: model:…` 引用可指向别模块记录；`i18n_extra` 同模块内后加载 | 必须 `--i18n-overwrite`（且与 `-u` 同用）或 post_init hook；`noupdate` 记录连 overwrite 都不覆盖 | [translate.py#L1837-L1845](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/odoo/tools/translate.py#L1837-L1845)、[#L1606-L1615](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/odoo/tools/translate.py#L1606-L1615) |
| **用 PO 覆盖 `_()`/`_t()` 的 code 词条** | ⚠ **部分可行（见下）** | — | **导入路径**（translation import / `--i18n-overwrite` 灌库）确实丢弃 `type=='code'` 行；但 **webclient 运行时不走库**：`ir_http._get_translations_for_webclient()` 对每个已装模块调 `code_translations.get_web_translations(module, lang)`，读的是该模块 `i18n/` + `i18n_extra/` 下 PO 里的 code 行 → 进 `translatedTermsGlobal`，而 `translation.js` 取词是 `translatedTerms[模块][源串] ?? translatedTermsGlobal[源串] ?? 源串` | [translate.py#L1584-L1585](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/odoo/tools/translate.py#L1584-L1585) |

> **⚠ 修正（2026-09-12 实施期实测，i18n-eng 读源码 + 实测 15 条词条）**：上面这条原写作"PO 永远无效"，**过于绝对**。准确结论是：
> - **可以补充「缺失」的 JS 文案**：在自研模块 PO 里写 `#. module: edu_zh` + `#. odoo-javascript` + `#: code:addons/...`，该词条会进 `translatedTermsGlobal`，成为**兜底**（实测 `get_web_translations('edu_zh','zh_CN')` 返回 15 条）。
> - **不能覆盖「他模块已有」的 JS 译文**：模块级 `translatedTerms` 优先于 global —— 这既是限制，也天然避免了误伤（已有正确译文不会被我们改坏）。
> - 因此判据是：**缺译 → 可用 edu_zh PO 补；错译（他模块已有）→ 仍需 JS patch / 资产覆盖**。
> - 两个操作坑：① 缺 `#. module: edu_zh` 会让 `PoFileReader.__iter__` 的 `re.match(...).groups()` 抛 `AttributeError`；② **改完 PO 必须重启 web** 以清 `CodeTranslations` 进程内缓存（不动 DB）。
| 运行时导入 .po/.csv（设置→翻译→导入） | ✅ 官方 | `overwrite` 默认勾选 | 手工、不进版本库、换库/恢复后要重跑 | [base_import_language.py#L25-L49](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/odoo/addons/base/wizard/base_import_language.py#L25-L49) |
| 旧做法：导 CSV 到 `ir.translation` | ❌ **已死** | — | 19.0 源码树无该模型 | `translate.py`#L1926-L1935（仅迁移辅助） |
| 继承视图 xpath 直接替换文案 | ✅ | 立即生效 | **写死成单语言**，与简/繁/英三语需求冲突 → 只适合极少数品牌短语 | [convert.py#L273](https://github.com/odoo/odoo/blob/c50a4e0513e5247f1b680ccbb5c0d27795a10b55/odoo/tools/convert.py#L273) |
| OCA/l10n-china | ❌ 19.0 **只有脚手架** | 40★ 但 17/18/19 分支都只有 `.github`/`setup` | 不能依赖 | [l10n-china branches](https://github.com/OCA/l10n-china/branches) |
| 核心自带中国化 | ✅ 仅 `l10n_cn`（会计科目/增值税/省数据）+ `l10n_cn_city` | 19.0 addons 里就这两个 | 其余全自研 | `addons/l10n_cn/__manifest__.py` |
| 社区汉化包 | ⚠ **无高 star 通用包** | `guohuadeng/odoo13-cn`（27★，整仓 fork）、`chr00tt/cn_odoo`（4★）、`baoding-fenshuajiang/GoodERP_OCC`（10★ 整仓 fork）等 | 整仓 fork 随上游合并极难；独立模块只能补自家词条 | 各仓库实测 |

### 3.1 推荐结构（本仓已采纳）
`custom_addons/edu_zh/`：`i18n_extra/zh_CN.po` + `i18n_extra/zh_TW.po` + post_init hook。
- 每条**必须自带目标引用行**（如 `#: model:ir.model.fields,field_description:openeducat_exam.field_...`）
- 生效：`odoo -u edu_zh --i18n-overwrite` **或** hook 里 `TranslationImporter.load_file(...).save(overwrite=True)`
- 注意「官方 19.0 开发文档**未记载** `i18n_extra`」（已核对 `translations.rst` 原文），但源码支持

---

## 4. 坑（全部有一手依据）

1. **默认不覆盖已有译文**：`save()` 的 jsonb 合并顺序 `overwrite=False` → `noupdate_value || update_value || m.field`（DB 值优先）；`overwrite=True` → 导入值优先，但 **noupdate 记录仍保留 DB 值**。
2. **noupdate 记录连 overwrite 都不覆盖**（需 `force_overwrite`，19.0 仅邮件模板重置在用）→ 别指望 CLI 强制覆盖。
3. **code 词条不走 PO**（Python `_()` / JS `_t()`）。
   > ⚠ **限定（2026-09-12 实施期实测 + 独立评审复核）**：这句只成立于**运行时导入器**路径（`TranslationImporter` 丢弃 `type=code` 行）。
   > **模块加载期 `i18n`/`i18n_extra` PO 里的 code 条目是生效的** —— `ir_http._get_translations_for_webclient()` 会读取它们进 `translatedTermsGlobal`，由 `translation.js` 作兜底取词。
   > 实测证据：edu_zh 的 PO 含 **15 条 code 条目**，经 `/web/webclient/translations?lang=zh_CN`（匿名 + 内部会话均 200 / 672KB）确认 **msgid 与译文同时在册**（如 `Lack of inspiration?`→暂无内容、`Hide trailing zeros`→隐藏末尾的零）。
   > **准确判据**：**缺译 → 可用自研模块 PO 补；错译（他模块已有）→ 仍须 JS patch/资产覆盖**（模块级译文优先于 global，这既是限制也是保护）。
4. **`_update_translations` 只加载"正在升级的那个模块"** → `-u edu_zh` 不会重载 base/web 的 PO，**自研 PO 必须自带每一条目标引用**。
5. **语言安装向导走 `overwrite=True`** → 运维重装/新增语言可能覆盖手工译文。
6. **手工改 arch_db 会被 `-u` 按 XML 覆盖** → 一切改动留在自研模块的继承视图里。
7. **三语需求不能用 xpath 写死文案解决**；`zh_TW` 加载链是 `zh.po → zh_TW.po`。
8. OCA `disable_odoo_online` 在 19.0 的 `remove("documentation")` 是**空操作**；`support`/`odoo_account` 才有效。
9. **AGPL-3 传染性**：装进对外服务的合规性需法务确认（本仓已决定不装）。

---

## 5. 未验证 / 待确认

- OCA 模块名 18.0→19.0 有变化（18.0 是 `portal_odoo_debranding`），**迁移路径未验证**。
- `odoo.conf` 里 `--i18n-overwrite` 的 conf 键写法**未实测**（`list_db = False` 有官方文档背书）。
- 反代改写 `/odoo`、`/web` 等 URL 的可行性**未验证**。
- zh_CN 覆盖率为脚本解析 .po 统计（多行 msgstr 口径）的**近似值**，非官方数字；Weblate 待审条目数未核对。

---

## 6. 本机镜像实测补遗（2026-09-12 实施期反馈，已由队长独立复现）

调研用的是上游 19.0 HEAD（`c50a4e0`），**本机镜像行号与几处事实不同**。实施以实测为准，以下均已用 `docker compose exec -T web grep` 在本机复现：

| 项 | 上游调研结论 | **本机实测** | 影响 |
|---|---|---|---|
| `support_url`（用户菜单 Help 外链） | `addons/web/models/ir_http.py:114` | **`web/models/ir_http.py:109`** | 行号偏移，继承 `ir.http.session_info` 的做法不变 |
| `noreply@odoo.com` | `ir_mail_server.py:282`，被当作"默认发件人" | **本机只有一处：`base/models/ir_mail_server.py:298`，位于 `_get_test_email_to()`**（发件服务器表单的"测试邮件收件人"默认值）——**它不是邮件默认 From** | 结论修正：真正的 From 链是 `company.email` / 系统参数 `mail.default.from`。去 Odoo 化要改的是这两个 + 测试收件人，而不是"邮件默认发件人" |
| `<meta name="generator" content="Odoo"/>` | 原清单**未收录** | **`addons/website/views/website_templates.xml:123`**，每个公开页 head 都有 | **新增触点**：漏掉它则 check_odoo_trace 永远过不去 |
| 用户菜单 accounts.odoo.com 入口 | `user_menu_items.js` | 本机 `user_menu_items.js:83`；`remove('support'/'odoo_account')` 实测有效 | 既有实现正确，保留 |

> 教训（已写入 `docs/research/README.md` 收录规范）：**引用上游行号时必须标注取证 commit，实施前在本机重新定位。**

### 6.1 去品牌化的边界：JS 全局命名空间无法去除（有意保留）

2026-09-12 实测：公开首页 HTML 中仍有约 **11 处 `odoo` 字样**，逐条核对后**全部是框架运行时标识**：

| 形态 | 例子 | 能否去除 |
|---|---|---|
| JS 全局对象 | `var odoo = {`、`window.odoo = {}`、`odoo.__session_info__ = …` | ❌ 前端资产管线与全部 Owl 组件都依赖此命名空间；改名等于重写框架 |
| script 标签 id | `<script id="web.layout.odooscript">` | ❌ 模板硬编码 |
| 资产 URL / 错误钩子 | `/web.assets_frontend_lazy.min.js`、`onerror="__odooAssetError=1"` | ❌ 资产路由与错误上报机制 |

**结论与口径（有意边界，非疏漏）**：
- 这些都是**用户不可见**的（位于 `<script>` 与 URL 中，不渲染成文字）；
- 业界参考实现（OCA/server-brand 各模块）同样**不处理**这一层；
- 因此 `scripts/check_odoo_trace.py` 的扫描口径定为「**用户可见文本 + 外链 + 品牌字样**」，**不把 JS 命名空间计入命中** —— 否则门禁永不可能归零，等于失效；
- 若有人想彻底清除，唯一可行方向是**反代/资源管线别名**，本仓评估为「风险高、收益为零」，不做。
