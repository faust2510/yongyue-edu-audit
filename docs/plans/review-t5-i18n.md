# t5 独立评审报告（学坊本土化：译文覆盖 / 统筹费 / 币种 / 数据出处）
> **状态**：`归档` ｜ **主题**：`学坊本土化评审` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 评审人：brand-eng（t11）｜被评审：t5（i18n-eng，attempt 4，completed）
> 日期：2026-09-12 ｜ 取样：本机 edu19，只读；**所有数字均为本轮独立执行**（未复用实现者自述）
> 结论：**verdict = pass**（5/5 acceptance 通过；无 needs_revision 级问题；3 条非阻塞观察见 §5）

---

## 1. 逐条 acceptance 判定

| # | acceptance | 判定 | 我的独立证据 |
|---|---|---|---|
| 1 | 升级后 14 条机翻硬伤在页面上全部变为正确中文 | **通过（抽样 12/17 条）** | 真实登录态抓页：`/my/fees` 统筹费=2 学费=0；`/student/assignment/details` 进行中=1 开启=0；`/users/result-overview` 得分=2 且 收到的分数/尝试日期/完全错误 **均 0**；`/my/notice_board/notice` 通告=1 Circular=0；`/ledger` 统筹费=2 应收=5 学费=0。DB 复核：`ir_model_fields.field_description->>'zh_CN'` 命中错误机翻词（得到正式认可的/公认/被拒绝/被要求/颜色指数/迄今为止/收到的分数/尝试日期/完全错误/马克/地位）= **0 个字段**；命中正确词（已批准/已驳回/已申请/颜色序号/结束日期/得分/作答日期/答错题数/分数/状态）= **175 个字段** |
| 2 | 全仓 grep '学费' 用户可见面为 0 | **通过** | `grep -rn '学费' custom_addons/ --include=*.xml --include=*.py --include=*.js --include=*.csv --include=*.json`（排除 __pycache__）= **0 命中**；渲染面 学费=0（见 #1） |
| 3 | views/fees.xml 无硬编码 ¥；公司币种 CNY；金额与币种一致 | **通过** | `grep -n '¥' views/fees.xml` = 0；`res_company.currency_id` → **CNY**；渲染实测 `/my/fees` 金额 `¥12200 / ¥12000 / ¥0 / ¥300`、`/ledger` ¥×8 —— 页面里另外出现的 `$` **不是货币**（来自 session_info 的货币清单 `{"name":"USD","symbol":"$"}` 与 JS 模板串 `tz=${userTZ}`，均在 <script> 内，用户不可见） |
| 4 | docs/plans/data-provenance.md 覆盖公开页事实，每条有来源或【待确认】 | **通过** | 台账 285 行：§1 来源编号 S1–S3（含「仓库未归档」的诚实标注）、§2 /programs 逐专业（2.1–2.7）、§3 /admissions、§4 联系方式红线、**§5 六条【待确认】且逐条写「需要谁确认」**、§6 幻觉数据覆盖度复核、§8 学费→统筹费改写（含授权与可逆说明）、§9 币种切换（§9.1 切换前 / §9.3 切换后实测 / §9.4 影响面与回滚，并注明**仅本地、生产未动**）。抽样事实（学分/截止/经济资助/圣经高中）在台账中均有对应条目 |
| 5 | JS 类词条已用 patch/资产方式修正并在报告中说明 | **通过（机制比报告更强）** | edu_zh PO 含 **15 条 code 类条目**（引用 web/mail/portal 的 .js/.xml）。我实测 `GET /web/webclient/translations?lang=zh_CN`（匿名与内部用户两种会话，均 200 / 672KB）中 msgid 与**译文同时在册**：`Lack of inspiration?→暂无内容`、`Hide trailing zeros→隐藏末尾的零`、`Invalid Display Name→显示名称无效` → **code 词条确实下发到前端**，因此无需 JS patch；`edu_zh/__init__.py` 头部用源码行号（loading.py:232/241、ir_module.py:880/971）说明了两条关键结论（升级必须带 `--i18n-overwrite`；post_init 只在 install 跑） |

## 2. 铁律合规（逐项独立检查）

| 铁律 | 结果 |
|---|---|
| 不建自定义组 | ✅ edu_zh 与 fees/ledger 控制器/模型内无 `res.groups` 创建 |
| 门户外壳 t-call | ✅ `views/fees.xml` 2 处、`views/ledger.xml` 4 处 `edu_portal.edu_page` |
| 写操作 POST+csrf | ✅ 触及的两个控制器中写路由均为 POST+csrf |
| Odoo 19 语法 | ✅ 无 `groups_id` / `<tree>` / `_sql_constraints` 残留 |
| openeducat_erp 零改动 | ✅ `git status --short openeducat_erp/` 为空 |
| 用户可见文案中文 | ✅ 见 acceptance #1/#2（另有跨任务残留见 §5-O3） |

## 3. inScope 合规（commit 级核对）

t5 自述 4 个 commit，逐条核对涉及文件：

| commit | 涉及文件 | 是否越界 |
|---|---|---|
| ec335a7 | edu_zh/{__init__,__manifest__,i18n_extra/zh_CN.po,zh_TW.po}、edu_portal/{models/fees.py,controllers/fees.py,controllers/ledger.py,views/fees.xml,views/ledger.xml}、seed_fees.py、scripts/{i18n_glossary.json,seed_fees_demo.py}、docs/plans/data-provenance.md | **否**（全部在 t5 inScope） |
| 2367579 | edu_zh/i18n_extra/{zh_CN,zh_TW}.po | 否 |
| 0e89d0d | edu_brand/views/pages.xml、docs/plans/data-provenance.md | 否 |
| 844c41d | edu_brand/views/pages.xml、docs/plans/data-provenance.md | 否 |

> 注：仓库里另有聚合提交 `7b43a49`（队长「已验收批次聚合提交」）含 `scripts/shoot_fees.py` 等；**不属 t5 的 4 个 commit**，不计入越界。

## 4. verify 命令可执行性（如实记录）

- verify#1 字面命令 `docker compose exec web odoo -c /etc/odoo/odoo.conf -d edu19 -u edu_zh --i18n-overwrite --stop-after-init` 在本环境**结构性不可执行**：① `exec` 绕过官方 entrypoint → 无 db_host → psycopg2 连 unix socket 失败；② 主服务常驻 8069，而 `--stop-after-init` 仍先 bind → Errno 98。t5 已在 output 如实披露，并用等价命令（带 `--db_host/--db_port/--db_user/--db_password/--no-http`）取证；队长已给 `safe_upgrade.sh` 加 `--i18n-overwrite` 透传（推荐路径）。
- 本次评审**未复跑升级**（避免打断他人采样窗口），改为在**数据层与渲染层**取证：DB 译文值已是 edu_zh 的修正值（#1）、前端 translations 负载含 edu_zh 的 code 译文（#5）——这比「重跑一次 -u」更能证明「覆盖真的生效」。

## 5. 非阻塞观察（不构成 needs_revision）

- **O1（文档）**：`docs/research/odoo19-debranding-i18n.md` §3/§4.3 的结论「用 PO 覆盖 `_()`/`_t()` 的 code 词条 → ❌ 不可能」**需要加限定**：该结论成立于**运行时导入器**路径（TranslationImporter 丢弃 type=code），但**模块加载期 .po 的 code 条目是生效的**（本次实测 15 条 code 译文确实下发前端）。建议队长补一句限定，避免后续成员据此放弃 PO 方案。
- **O2（流程）**：本次再次确认「契约里的字面 verify 命令必须先本地跑通」——t5/t6 两次都撞上同一结构性不可执行（与队长已立的铁律一致）。
- **O3（跨任务，不计入 t5）**：用户可见英文残留 `activate` ×3 于 `/edu/audit`（t9 发现，根因 `edu_portal/controllers/downloads.py:883-886` 映射字典缺键）与 Odoo core 的 `title="转到您的Odoo应用程序"` 按钮 tooltip —— 两者都不在 t5 inScope，已分别归 t28 / t26+t29。

## 6. 结论

**verdict = pass**。t5 的 5 条 acceptance 全部通过且有可复现证据；铁律与 inScope 均合规；PO 覆盖不是「写了文件就算数」——已在 DB 值与前端下发负载两处独立证实生效。
