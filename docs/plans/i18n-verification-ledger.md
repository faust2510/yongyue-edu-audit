# i18n / 渲染验证判据台账（Verification Ledger）
> **状态**：`归档` ｜ **主题**：`i18n 汉化验证判据` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> **这份文件是什么**：本仓在「汉化 / 去品牌化 / 译文覆盖 / 渲染断言」这条线上攒下的**判据与证据索引**。
> 每条都是**踩过一次坑之后测出来的**，附原始命令、数字与日期，便于后人复核而不是重新试错。
>
> **这份文件不是什么**：不是流程、不是门禁规范、不带任何任务/进度状态。权威版本在别处（见 §7）。
>
> **维护约定（本文件属「活文档」，与「历史记录」规则不同）**：
> · **可以且应当**继续维护 —— 一份写着旧数字的判据索引**比没有更糟**：后人照旧数去复核 → 得出「文档与现实不符」 → 从此不信这份文档。
> · 更新前**必须实跑文中的复核命令**（否则改完仍可能是旧数）；更新后**报告 diff 与理由**。
> · **权威值永远在工具里**（`scripts/check_odoo_trace.py`、`scripts/check_english.py`），本文件只引用、不定义；
>   发现两者不一致时，**以工具为准并回来改这里**。
> · **红线**：不得改写任何**历史判定**（评审 verdict、验收结论、门禁留档读数）—— 那类只允许加**指针**。
> · 实证依据：本文件首次提交后数分钟内就被发现有两处已过期（§1.2 的样本已翻篇、§4/§5/§6 的数字已变）
>   —— **「写完即旧」在这条链路上是常态，不是意外**，所以维护是职责而非越界。
>
> 最后更新：2026-09-12（新增 §9 修复能力档位实测；维护约定见上；每次更新请连同本行日期一起改）

---

## 0. 三条最快能救命的判据（先看这里）

1. **自研 .po 默认不覆盖已有译文** → 必须 `--i18n-overwrite`（§1.1）。
2. **noupdate=t 的记录，连 `--i18n-overwrite` 都覆盖不了** → 只能用 `<function>` 重放（§1.2）。
3. **渲染断言的探针必须从真实发送路径派生** → 否则模板一加条件分支，探针静默退化、报假绿（§3）。

---

## 1. PO（.po 词条）的三条硬限制

### 1.1 DB 词条路径：默认不覆盖，必须 `--i18n-overwrite`

- **判据**：当目标词条属于**别的模块**且 DB 里**已有一份译文**（例如 Odoo 官方 zh_CN 的机翻）时，
  `overwrite=False` 下**数据库既有值优先**，自研 PO 灌不进去。
- **证据**：
  - 机制源码 `odoo/addons/base/models/ir_module.py` → `_load_module_terms(..., overwrite)` 与
    `odoo/tools/translate.py` → `TranslationImporter.save(overwrite=...)`。
  - 实测（2026-09-12）：`website.layout` 的 tooltip「转到您的Odoo应用程序」（官方 zh_CN 译文）
    在 `--i18n-overwrite` 之前覆盖不生效，加上之后渲染变为「转到您的应用」。
- **如何复核**：
  ```bash
  UPGRADE_EXTRA_ARGS="--i18n-overwrite" bash scripts/safe_upgrade.sh -u edu_zh
  # 日志必须出现：loading translation file .../edu_zh/i18n_extra/zh_CN.po for language zh_CN
  docker compose exec -T db psql -U odoo -d edu19 -At -F '|' -c \
    "SELECT substring(arch_db->>'zh_CN' from position('o_frontend_to_backend_apps_btn' in arch_db->>'zh_CN')-90 for 90) FROM ir_ui_view WHERE key='website.layout'"
  ```
- **注**：`edu_zh` 的 PO 放在 `i18n_extra/`；Odoo 会同时读 `i18n/` 与 `i18n_extra/`
  （`odoo/tools/translate.py` → `get_po_paths`）。

### 1.2 `noupdate=t` 的记录，连 `--i18n-overwrite` 都覆盖不了

- **判据**：目标记录若在 `ir_model_data` 里 `noupdate = true`，**任何 PO 覆盖（含 overwrite）都不生效**，
  普通 `<record>` 在 `-u` 时也会被跳过。
- **证据（记录级，2026-09-12 实测；现状同日照录）**：
  | 记录 | noupdate | 用 PO 覆盖的结果 | 记录现状 |
  |---|---|---|---|
  | `mail.group_mail_notification_type_inbox` (res.groups) | **t** | **不生效** | **至今仍是「在 Odoo 系统中接收通知」**（PO 无效且未走 function） |
  | `auth_totp_mail.mail_template_totp_invite` (mail.template) | **t** | **不生效** | 已由 `<function>` 修好：zh_CN「邀请您在教务系统帐户上激活双因素身份验证」/ zh_TW「邀請你為你的教務系統帳戶啟用雙重要素身份驗證」 |
  | `web.login_layout` (ir.ui.view) | f | **成功** | 页脚已为「由永约学坊提供支持」 |
  | `account.report_statement` (ir.ui.view) | f | **成功** | 已去 Odoo |

  > **这一对样本正好互为对照**：同一个 noupdate 标志下，**PO 路线无效、`<function>` 路线有效**；
  > 而另一个记录至今还是原文 —— 说明「**覆盖了但没生效**」是真会发生、且会**静默留在库里**的动作。
  > 这两条 PO 词条目前**仍在** `edu_zh/i18n_extra/zh_CN.po` 里（留着不生效、也无害），可作为「PO 试过、无效」的存证。
- **如何复核**：
  ```bash
  docker compose exec -T db psql -U odoo -d edu19 -At -F '|' -c \
    "SELECT d.noupdate, t.subject->>'zh_CN' FROM mail_template t \
     JOIN ir_model_data d ON d.model='mail.template' AND d.res_id=t.id \
     WHERE d.name='mail_template_totp_invite'"
  # 期望：noupdate = t
  #   —— 若后续为 t 且文本仍含品牌词，说明该条**只能**走 <function>/模板覆盖（PO 路线已证明无效）
  ```
- **唯一可行出口**：**`<function>` 每次 `-u` 重放**；翻译字段必须**逐语言**给 context：
  ```xml
  <function model="mail.template" name="write" context="{'lang': 'zh_CN'}"
            eval="[[ref('auth_totp_mail.mail_template_totp_invite')], {'subject': '邀请您为账户启用双因素身份验证'}]"/>
  ```
  同法适用于 `digest.digest.name`、`res.company`、`digest.tip` 等（写法要点：翻译字段一次只写当前语言）。
- **附带判据**：`mail.template.body_html` / `subject` 是**数据列**，经
  `mail.render.mixin._render_template(..., engine='qweb')` 渲染，**不是 `ir.qweb` 具名模板** ——
  所以对它们 `ir.qweb._render('auth_signup.set_password_email')` 会「找不到模板」，**`t-inherit`/xpath 也无从谈起**。

### 1.3 `code:addons` 词条：只能补「缺译」，改不动「错译」

- **判据**：PO 里的 `#: code:addons/...` 词条（Python `_()` / JS `_t()`）**不会进 DB**，
  但会进 webclient 的 `translatedTermsGlobal`（**全局兜底**）。取词顺序是
  `translatedTerms[模块][源串] ?? translatedTermsGlobal[源串] ?? 源串`
  （`web/static/src/core/l10n/translation.js`）——**模块自带译文优先**，兜底只在**缺译**时生效。
- **推论**：
  - **缺译** → 自研 PO 的 code 词条可以补；
  - **错译**（模块自己已有译文）→ **兜底无效，必须 JS patch / 资产覆盖**。
- **证据（2026-09-12）**：
  - 正例（补缺译成功）：`code_translations.get_web_translations('edu_zh','zh_CN')` 返回 15 条，
    且 web 自身字典里**没有**这些源串（如 `Are you sure you want to delete the selected record?`）→ 兜底生效。
  - 反例（错译改不动）：`web/static/src/webclient/actions/action_service.js` 的
    「Odoo的弹出窗口已被浏览器阻止弹出…」在 `web` 自带 `zh_CN` 里已有译文 → 自研 PO 覆盖**无效**。
- **如何复核**：
  ```bash
  # 看自研 PO 的 code 词条是否被读进 webclient 字典
  docker compose exec -T web odoo shell --db_host=db --db_user=odoo --db_password=odoo \
    --no-http -c /etc/odoo/odoo.conf -d edu19 <<'EOF'
  from odoo.tools.translate import code_translations
  t = code_translations.get_web_translations('edu_zh', 'zh_CN')
  print('edu_zh code entries:', len(t['messages']))
  web = code_translations.get_web_translations('web', 'zh_CN')
  src = {m['id'] for m in web['messages']}
  print('某源串是否已在 web 字典里（在 = 改不动）:', 'Install Odoo' in src)
  EOF
  ```
- **配套**：PO 的 code 行**必须同时带** `#. module: <模块>` 与 `#. odoo-javascript`；
  缺前者 `PoFileReader.__iter__` 的 `re.match(r"(module[s]?): (\w+)", entry.comment).groups()` 会直接抛 `AttributeError`（实测踩过）。
- **生效条件**：code 词条改的是**进程内缓存**，**改完必须重启 web** 才生效（`CodeTranslations` 常驻内存）。

---

## 2. 译文回退语义：ORM 与「直读 jsonb」结果不同

- **判据**：**译文槽位为空时，Odoo 回退到源语言**。因此
  `rec.with_context(lang=lg)[field]`（真实渲染路径）**可能返回源语言文本**，
  而直接读 `field->>'lg'` 得到 `NULL`。**对「收件人/用户实际看到什么」这个问题，只有 ORM 口径是对的。**
- **证据（2026-09-12 实测）**：`mail_template` id=4（`Settings: New Portal User Invite`）的 `subject`：

  | 口径 | zh_TW 取值 |
  |---|---|
  | `rec.with_context(lang='zh_TW').subject` | `'Your account at {{ object.company_id.name }}'`（**回退到 en_US**） |
  | SQL `subject->>'zh_TW'` | `NULL`（槽位确实为空） |

- **后果（血泪）**：用 SQL 直读 jsonb 统计「三语言命中组合数」会**低估**——
  我实测 23，门禁实测 29，差额全部来自「空槽位 + 源语言回退」。**门禁的 29 是对的，我的 23 是错的。**
- **可复现命令（推荐直接抄）**：
  ```bash
  docker compose exec -T web odoo shell --db_host=db --db_port=5432 --db_user=odoo \
    --db_password=odoo --no-http -c /etc/odoo/odoo.conf -d edu19 <<'EOF'
  rec = env['mail.template'].sudo().browse(4)
  for lg in ('en_US', 'zh_CN', 'zh_TW'):
      print('ORM  %-6s -> %r' % (lg, (rec.with_context(lang=lg).subject or '')[:50]))
  env.cr.execute("SELECT subject->>'en_US', subject->>'zh_TW' FROM mail_template WHERE id=4")
  print('SQL 槽位      ->', env.cr.fetchone())
  EOF
  ```
- **教训（写给未来的自己）**：**在把矛头指向别人的量具之前，先验证自己的量具。**

---

## 3. 渲染断言的探针必须从真实发送/渲染路径派生

- **判据**：凡是「渲染某模板 → 断言输出不含 X」的门禁，**探针上下文必须逐字段照搬真实发送路径**。
  否则模板里任何一个条件分支都会让探针**静默地只渲染一个退化子集**，门禁因此**给出看起来像证据的绿色结论**（假绿）。
- **证据（2026-09-12，同一条模板两次测量）**：
  | 探针口径 | digest 邮件渲染长度 | odoo 计数 |
  |---|---|---|
  | 通用合成上下文（缺 `kpi_data`/`preferences`/`display_mobile_banner`） | **3 662 B** | **0** ← 假绿 |
  | 忠实上下文（照 `_action_send_to_user` 逐字段） | **34 052 B** | **20** |
- **再深一层的根因：探针的「身份」也要对**。
  `digest/models/digest.py` 的 preferences 区块**只对 `base.group_erp_manager` 渲染**；
  用普通教师构造上下文 → 该区块整块消失 → 又一种假绿。**探针用户必须能触达目标区块。**
- **修好后的判据（可当验收）**：探针与独立忠实渲染**同构**。
  实测：门禁探针 `len=28358` vs 独立忠实渲染 `len=28359` —— **相差 1 字节**（unsubscribe token / 日期长度差异）。
- **加固做法**：门禁输出里**打印渲染字节数**作为「是否真用了忠实上下文」的审计信号
  ——旧退化渲染约 3.6 KB、忠实渲染 28 KB+，**一眼可辨**。
- **如何复核**：
  ```bash
  python3 scripts/check_odoo_trace.py --mail     # 看每行的 len= 是否在忠实量级（KB 级，不是 3.6KB）
  # 再自跑忠实上下文对照：
  #   tips = d._compute_tips(company, user, tips_count=3, consumed=False)   # 注意：返回的是 HTML 字符串列表，不是 recordset
  #   vals = {... 照 _action_send_to_user 逐字段 ...}
  #   html = env['ir.qweb']._render('digest.digest_mail_main', vals)
  ```
- **相关坑**：`_compute_tips()` 返回**渲染好的 HTML 字符串列表**（不是 recordset）；当成 recordset 用会得到
  `'Markup' object has no attribute 'id'`。

---

## 4. 内部核心链接不算品牌命中（外链仍算）

- **判据**：`/odoo/…` 与 `/web/…` 是**核心命名空间**（不改 core 的 URL 生成，已记录的取舍）
  → **不算品牌命中**；而 `odoo.com` / `apps.odoo.com` / `services.odoo.com` / `odoocdn.com` 这类**外链仍算命中**。
- **实现要点（易错）**：剥离规则必须匹配**绝对 URL** ——
  实测渲染出来的是 `http://host:8069/odoo/action-…`，所以模式要用宽松前段吃掉 scheme/host
  （参考 `scripts/check_odoo_trace.py` 的 `_CORE_LINK_RE`）。
- **曾经的净差与现状（2026-09-12）**：数据面 headline 一度用「剥掉**全部** href」的规则，
  未应用「内部链接 vs 外链」口径 → `命中记录 11` 里混进了 1 条**只有内部链接**的
  （`mail_template_base_install_request`，id=7，其 odoo 只出现在 `t-attf-href="/odoo/{{ ... }}/action-…"`）。
  **现已统一**：headline 实测由 **11 → 10**，与邮件面口径一致。
- **更进一步：内部链接型现已「单列在行内」而不是被静默减掉**（2026-09-12 复核）——
  数据面现在这样报：
  `命中记录 10/47（其中 1 条属内部核心链接型，按 /odoo、/web 口径不计；可见文案 8 条；匹配组合 29）`。
  **为什么这点重要**：若只报 10，读者不知道少掉的那 1 条是什么性质，就得自己做减法 ——
  而「口径不同的数字混用」正是本项目 44 vs 15 那次基线不可复现的成因（见 §6）。
  **教训：计数永远要带上「它是怎么来的」**。
  → **留档价值**：这类「同一仓库里两套 href 剥离口径并存」是**静默发生的**；
  改动剥离规则时，**必须同时检查页面、邮件面、数据面三处是否还在同一口径上**。
- **如何复核**：
  ```bash
  docker compose exec -T db psql -U odoo -d edu19 -At -F '|' -c \
    "SELECT substring(body_html->>'en_US' from position('odoo' in body_html->>'en_US')-60 for 120) \
     FROM mail_template WHERE id=7"
  # 期望看到 t-attf-href="/odoo/{{ ... }}/action-…" ← 内部核心链接
  ```

---

## 5. 可达性口径：**不可达的登记，不修**

- **判据**：判断某条品牌残留是否值得处理，先问三件事：
  1. **所属应用是否启用**？2. **该记录是否被任何视图/动作引用**？3. **在真实渲染路径上能否被触发**？
  三者皆否 → **登记为「不可达」而不是修**（core 只读项同理：改渲染路径，不归零）。
- **登记表以代码为权威**：`scripts/check_odoo_trace.py` 的 `UNREACHABLE_MODULES`（每条带理由，可直接复核）。
  当前登记 **5 条**（照录，2026-09-12 **含 t64 加入的失效条件**）：
  | 模块族 | 登记理由（原文，含失效条件） |
  |---|---|
  | `base_install_request` | 模块安装请求邮件：本部署永不发送（**失效条件**：真用后台「应用」页走安装审批流程时重评） |
  | `account` | 电子发票/订阅通知：account_peppol 未装、account_move=0（i18n-eng 实测不可达）（**失效条件**：安装 account_peppol 或开始产生发票/订阅记录时重评） |
  | `gamification` | 徽章通知：本部署未使用徽章（**失效条件**：启用徽章/排行榜并开始发徽章通知时重评） |
  | `event` | 活动邀请/提醒：本部署未启用活动报名（**失效条件**：启用活动报名并开始发邀请时重评） |
  | `website_profile` | 个人资料验证邮件：本部署未启用（**失效条件**：启用个人资料验证流程时重评） |

  > **本节（台账）与代码现在同口径**：下面「重评触发条件」那条纪律**不只是在文档里说说** ——
  > 代码侧的 `UNREACHABLE_MODULES` 已把**每条各自的失效条件**写在登记项里（t64）。
  > 两者若哪天不一致，**按维护约定以工具为准并回来改本节**。
- **另有两条单独登记的 core 侧不可达项**：
  | 对象 | 证据 |
  |---|---|
  | `digest.digest_section_mobile`（core arch 残留） | core 文件只读；该 section 未进入实际渲染路径 |
  | `account` 的 `mail_template_einvoice_notification` / `mail_template_invoice_subscriber` | 公司国家 = **US**；`account_peppol` **uninstalled**；`account_move` = **0**；`invoice_subscriber` 在**任何 `arch_db` 里 0 引用**（本节复核命令即为此项的取证） |
- **反例同样重要**：`calendar` 的 4 条会议邀请/提醒模板被判**可达**（本部署确实在用日历会议），
  因此它们**留在「待修」**而没进登记表 —— **登记表不是「看着没用就塞进去」的垃圾桶**，每条都要能回答上面那三问。
- **当前数据面读数（2026-09-12 复核）**：
  `命中记录 10/47（可达 4 条 / 不可达登记 6 条）｜内部链接型 1 条（按 /odoo、/web 口径不计）｜可见文案 8 条｜匹配组合 29`。
- **如何复核**：
  ```bash
  docker compose exec -T db psql -U odoo -d edu19 -At -F '|' -c \
    "SELECT (SELECT count(*) FROM account_move) AS moves, \
            (SELECT count(*) FROM ir_ui_view WHERE arch_db::text ILIKE '%invoice_subscriber%') AS refs"
  docker compose exec -T db psql -U odoo -d edu19 -At -F '|' -c \
    "SELECT name, state FROM ir_module_module WHERE name IN ('account_peppol','account_edi_ubl_cii')"
  ```
- **重评触发条件：登记不是永久豁免**（2026-09-12 补，verifier 提出、brand-eng 转达）——
  任一被登记的模块**一旦启用**（或首次出现真实的收件人可达路径），该登记**立即失效**，
  必须回到「待修」重判。否则登记表会随时间退化成「当年判过一次、此后没人再看」的豁免清单。
  **复核方式**：启用模块前后各跑一次数据面，看 `可达命中 / 不可达登记` 两个数是否随之移动
  （若登记项启用后仍停在"不可达"侧，说明标定没跟上现实）。
  这也是本表的**自检问句**：**你上次重评是什么时候？**
- **纪律**：不可达**不等于已清**——它是在「已清 / 待修 / 不可达」三分里明确落在第三类，
  而不是混进「已清」的计数里。见 §6。

---

## 6. 不计入判据的面，不得当成「已清」

- **判据**：门禁的 **PASS 只覆盖它声明的判据维度**。输出里若同时存在「待修面」「未覆盖」「未验证面」，
  读 PASS 时**必须同时读这些行**，否则会把「没检查」当成「没问题」。
- **证据（2026-09-12，同一次运行的输出同时含）**：
  - 四维判据 PASS（`Odoo / 基座品牌痕迹 0 命中`）
  - 邮件面 `覆盖 4/4 支模板，未覆盖 0 支`
  - **`[数据面] mail.template 命中记录 10/47（其中 1 条属内部核心链接型，按 /odoo、/web 口径不计；可见文案 8 条；匹配组合 29）（待修，见样本）`**
  - `[数据面] 可达命中 4 条 / 不可达登记 6 条（按本部署可达性口径，登记理由见代码 UNREACHABLE_MODULES）`
  - `[数据面] ⚠ 本轮待修面：mail.template —— 这些记录能到达收件人，命中即报`
- **判据含义**：数据面是「**命中即报、进入待修清单、不计入四维判据**」——
  所以「四维 PASS」**不等于**「邮件模板已全清」。
- **纪律**：口径不同的数字**不得混用**（本项目曾因此出现「44 vs 15」的不可复现基线：
  44 是「记录×字段×语言」的组合数、15 是记录数）。
  **报数字必须同时报口径**：扫哪些字段、哪些语言、按什么去重、是否计入内部链接。
- **同一条纪律的机器可检版本**：门禁的**退出码契约**已把它固化下来 ——
  `0=OK / 1=FAIL / 2=ENV / 3=INCOMPLETE`，且**默认 strict**（存在「未验证面」即判失败，`--lenient` 才降级为 3）。
  也就是「**验不了 ≠ 干净**」不再靠人读输出，而是**进退出码**。
  （契约细节见 `tests/smoke/UX_V3_GATE.md`；本文件只做索引。）
  **本条的证据等级要写明**（2026-09-12 复核）：`exit_code()` 是**纯函数**
  （`if total_hits: return 1` ／ `if unverified: return 1 if strict else 3` ／ `return 0`），
  三分支**读码确认**；但 `3=INCOMPLETE` 这一支**无法用执行观察到**（当前无未验证面，
  默认与 `--lenient` 实测都是 `EXIT=0`）。
  ⇒ **0/1 分支是执行验证，3 分支仅代码验证。** 把验证等级写进文档本身，正是 §5/§6 纪律用在自己身上。
- **如何复核**：
  ```bash
  python3 scripts/check_odoo_trace.py | grep -E '数据面|待修面|未覆盖|边界计数|PASS|REVISION'
  # 同时看退出码：0=OK 1=FAIL 2=ENV 3=INCOMPLETE（默认 strict，有未验证面即 1）
  ```

---

## 7. 权威版本在哪（本文件只做索引，不复制）

| 主题 | 权威文件 |
|---|---|
| 开发流程（六步闸门、标准改动闭环） | `docs/dev-workflow.md` |
| 门禁规范（四维判据、must-fix / brand 口径、路由×角色矩阵） | `tests/smoke/UX_V3_GATE.md` |
| Odoo 19 去品牌化 / 汉化的**源码级调研**（PO 四条硬限制的原始来源、触点清单 A–E） | `docs/research/odoo19-debranding-i18n.md` |
| 术语与改写口径（统筹费、公开页事实出处） | `docs/plans/data-provenance.md` |
| **本文件** | i18n 侧的**判据与证据索引**（上面各条的「为什么会这样」与「怎么复核」） |

---

## 8. 全局复核清单（一条命令跑完主干）

```bash
export no_proxy="localhost,127.0.0.1" NO_PROXY="localhost,127.0.0.1"

# 1) 覆盖生效（需 --i18n-overwrite）
UPGRADE_EXTRA_ARGS="--i18n-overwrite" bash scripts/safe_upgrade.sh -u edu_zh

# 2) 门禁四维 + 邮件面 + 数据面待修（三条都要看，见 §6）
python3 scripts/check_odoo_trace.py | grep -E 'PASS|FAIL|邮件面|数据面|待修面|未覆盖'

# 3) 可见英文（must-fix / brand 两个口径）
python3 scripts/check_english.py | tail -12

# 4) noupdate 陷阱自查（§1.2）：凡是打算用 PO 覆盖的目标，先查它是不是 noupdate
docker compose exec -T db psql -U odoo -d edu19 -At -F '|' -c \
  "SELECT model, count(*) FILTER (WHERE noupdate) AS noupdate_cnt, count(*) AS total \
   FROM ir_model_data WHERE model IN ('mail.template','ir.ui.view','res.groups') GROUP BY model"
```

## 9. 修复能力档位：能修什么 / 修不了什么（t65 实测，2026-09-12）

> **为什么单列一节**：此前对「function 重放能自愈到什么程度」只有**措辞**（注释里写着"幂等 + 已知片段自愈"），
> 没有反向用例。按本轮定下的规矩 —— **能力边界也是要被证明的对象**（没有反向用例，"能力有限"就只是谦虚措辞）—— 这里补实测。

**三条配对用例（同一 `-u edu_brand` 周期内完成）**

| # | 字段类型 | 注入内容 | 期望 | 实测 |
|---|---|---|---|---|
| 1 | 链式替换（`portal_set_password_email`） | **已知片段**（`https://www.odoo.com` + `>Odoo</a>`） | 自愈 | ✅ 注入后含品牌=True → `-u` 后=False |
| 2 | 链式替换（同上） | **任意串**（`ARBITRARY-CORRUPTION Odoo leak xyz`） | **不**自愈 | ✅ `-u` 后**仍含 `Odoo`**（值被包装成 `<p>…</p>`，但品牌词还在） |
| 3 | 权威固定值（`set_password_email.body_html.zh_CN`） | 任意串（含品牌词） | 绝对自愈 | ✅ `-u` 后回到权威中文正文，含品牌=False |

**判据要点（第 2 条最容易写成假断言）**：反向用例的正确判据是"**`-u` 之后品牌词是否还在**"，
**不是**"字节是否与注入值相等" —— 值会被 Odoo 侧包装（`<p>`），字节相等判据会得出错误的"已自愈"。

**还原路径（先演练，后注入）**：
```bash
# ① 快照（jsonb 原文，按 id 排序）
docker compose exec -T db psql -U odoo -d edu19 -tAc \
  "select id || E'\\t' || coalesce(subject::text,'') || E'\\t' || coalesce(body_html::text,'') \
   from mail_template where id in (select res_id from ir_model_data \
   where model='mail.template' and module in ('auth_signup','auth_totp_mail')) order by id" > /tmp/t65_snapshot.tsv
md5 -q /tmp/t65_snapshot.tsv   # fa03754b43311fe8f017ad4e07de8eae
# ② 还原 = 用快照生成 update 语句（jsonb 原样写回）后比对 md5
# ③ 演练通过才允许注入；不通过则中止（本次演练通过后才执行了三组注入）
```
**演练不是形式**：本次实测中，第一个脚本**在注入之后**因编码问题崩溃，DB 停在脏状态；
正是**已演练过的还原路径**一次把它拉回（`FINAL_RESTORE_OK | fa03754b…` 与快照 md5 一致）。
→ 抽象规矩：**凡是要动活数据，先证明你的还原路径能走通**（备份必须演练过才能算备份）。

**验收口径（队长裁决 (a)）：接受「检测与自动修复分离」**
· 链式替换的价值在**跟着 core 走**，改成权威固定值会失去它（t54 只在"收件人必得、且长期不依赖 core 更新"的 `zh_CN` 正文上用了固定值）；
· "发现得了"由门禁保证：命中即报 + 待修面显式（见 §5/§6 与本轮门禁改造）；
· **缓解路径**：真出现"非已知片段"损坏时，修复手段是**人工按本节的还原路径处理**（该路径已演练过）。

**版本台账（引用请连指纹一起抄）**：`scripts/check_odoo_trace.py` 自证行 `REVISION=v3.6 · 指纹 0461231c · 断言 24 条`；
> **指纹怎么用（2026-09-12 补）**：上面这个 `0461231c` 是**本节三条用例测量时的修订锚点**，
> 属于**证据的一部分**，**不要**因为工具后来又改了就把它更新掉 —— 否则后人无法判断这些结论适用于哪个版本。
> 而**当前**口径请以工具自证行为准：截至本次复核，工具已前进到 `REVISION=v3.6 · 指纹 708f7792 · 断言 24 条`。
> ⇒ 规矩：**引用「测量结果」抄当时的指纹；引用「当前口径」现跑一次取指纹。** 两者混用就会重演「口径不同数字混用」。
本轮门禁输出：`[数据面] mail.template 命中记录 10/47（其中 1 条属内部核心链接型，按 /odoo、/web 口径不计；可见文案 8 条；匹配组合 29）`。
> **一句话总结这份台账**：这个项目在汉化上踩的坑，绝大多数不是「翻错了」，而是
> **「以为覆盖了其实没覆盖」（§1）**、**「以为查过了其实只查了退化子集」（§3）**、
> **「以为清了其实只是没算进去」（§5、§6）**。所以判据的核心永远是同一句：
> **口径说清楚、量具先自检、证据落到命令。**
