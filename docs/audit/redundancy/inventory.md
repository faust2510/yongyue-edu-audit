# 去冗余审计与处置清单（T1 · 2026-10-02）

> 共享卡：task-6（写范围 `custom_addons/*.py` + `docs/audit/redundancy/**`）。
> 本文是**可复核**的处置记录：每条删除/迁移都带「命令 + 原样输出」，每条「留」也带理由。
> 所有读数带采集时刻；带行号的一律是**取证块**（code-map §6 第 15 条：不得据此定位代码）。

## 0. 一句话读数（2026-10-02 18:15–18:45，本地 edu19-clone）

| 组 | 范围 | 读数 | 处置 |
|---|---|---|---|
| A 散件 | `custom_addons/` 根下非模块 .py | **10 个**（全部 git 跟踪、0 处可执行引用） | **迁 7 / 删 3** |
| B 静态资源 | `*/static/src/**` 的 js/css/scss | **30 个**（14 js + 14 css + 2 scss） | **留 30 / 删 0**（30/30 在活跃 bundle 里） |
| C 路由 | `custom_addons/edu_*/` 的 @http.route | **309 条**（307 个 handler / 40 个文件） | **删 0**（0 条未注册；0 条真死路由） |

**结论：本轮的「冗余」几乎全在 A 组（放错地方的散件）；B/C 两组是真·在用，不该动。**
C 组唯一的真问题不是「有死路由」，而是**判据极易过量**：309 条里有 20+ 条 0 代码入链，
但它们靠 JS 端点 / DB 菜单 / 外部系统 / 卡片引擎 key 进入 —— 直接按「0 入链」删会删掉生产入口。

## 1. 判据（先说清「零引用」怎么算）

### 1.1 三源对账（路由）
1. **代码声明**：`docs/audit/redundancy/route_probe.py`（AST 解析 `@http.route`，能解模块级常量路径，
   如 `edu_tg_bind` 的 `WEBHOOK_PATH`）→ `routes.json`，**309 条**。
2. **运行态注册表**：`route_registry.py` 走 `odoo shell` 导 `env['ir.http'].routing_map()`
   → `routing_map.json`，**769 条规则**（含核心/基座）。比对：自定义 309 条 **0 条未注册**。
3. **实测可达性**：`route_reach.py`，6 个身份（anon/stu/fac/par/bo/admin）× 309 条，记录状态码 + Location；
   `route_audit.py` 把三源 + 入链并成一张表（`routes_report.json`）。

### 1.2 「0 入链 ≠ 死」——入链判据必须覆盖四类入口
入链口径：在 `custom_addons/**`、`docs/`、`tests/`、`scripts/`、`specs/` 里，
**带链接特征的行**（`href` / `action=` / `fetch(` / `redirect(` / `url:` …）命中该路由路径，且不是该路由的
`@http.route` 声明行；再叠加**卡片引擎 key 写法**（`/my/checkin` 是 `/my/checkin/board` 的前缀这类情况必须两者都算，见 §4.4）。
四类真实入口（全部实测过）：

| 入口类型 | 例子（本仓实测） | 只按「0 入链」判会怎样 |
|---|---|---|
| JS data-fetch | `/my/search/suggest` ← `search_suggest.js` 的 `ENDPOINT` | 误判为死 |
| DB 菜单（不在代码里） | `/booking` `/online-exams` `/courses-offered` `/program-offered` `/alumni/job/card` ← `website.menu` 表 | 误判为死 |
| 外部系统 | `/telegram/tgb/webhook`（Telegram setWebhook）、`/my/calendar/ics/<token>`（手机日历订阅一次长期拉取） | 误判为死 |
| 卡片引擎 key（运行时拼 href） | `'student/progression'` → `'href': '/' + href`（batch2.py 的 `cards()`） | 误判为死 |

### 1.3 工具必须能被注入变红
见 §7：散件守卫三条注入全部变红；路由探针与入链判据各自被实跑证伪过一次并修好（§7.2）。

## 2. A 组：`custom_addons/` 根下 10 个散件

### 2.1 处置表（逐条理由）

| # | 文件（原位置） | 是什么 | 引用证据 | 判定 | 理由（一行） |
|---|---|---|---|---|---|
| 1 | `fix_menus.py` | 2026-08-22 一次性：把 `website.menu` 挪到站点真根 + 定 sequence | 0 处可执行引用；仅 2 处文档提及（其一自称「历史脚本」） | **删** | 已被 `scripts/seed_d1_nav.py`（数据驱动、幂等）取代，后者注释自陈「沿用 fix_menus 的 sequence 约定」⇒ 约定已保全 |
| 2 | `seed_menus.py` | 2026-08-22 一次性：按原站导航补 `website.menu` | 0 处可执行引用；1 处文档提及（「历史脚本」） | **删** | 同上：导航入口现由 `scripts/seed_d1_nav.py` + `scripts/setup_nav_yongyue.py` 维护 |
| 3 | `seed_fees.py` | 2026-09-17 改过文案：给演示学生造 **account.move 发票** | 0 处可执行引用 | **删** | ① 与页面数据源**不是同一个模型**（证据②）② 同功能替代 `scripts/seed_fees_demo.py` 才是本地库现存账单的来源（证据③） |
| 4 | `seed_demo.py` | 第一批演示数据（课程/批次/科目/时段/教室/教师/演示学生） | 被 `seed_batch1.py` 报错文案点名「先跑 seed_demo.py」；docs 多处引用 | **迁** `scripts/` | 仍是本地演示环境的第一块骨牌，删了后面几批种子无源；code-map §7 早已把它登记在 `scripts/种子/演示` 名下 |
| 5 | `seed_batch1.py` | 考勤/考试/作业/活动演示数据 | 带幂等守卫（`search_count` 分支） | **迁** | 本地造数链一环 |
| 6 | `seed_batch2.py` | 图书馆媒体/成绩单/布告栏演示数据 | 同上 | **迁** | 同类；另被 `docs/research/gradebook-entry.md` 引为「手写绕过 generate_result」的**证据件** ⇒ 迁走比删掉稳 |
| 7 | `seed_batch3.py` | 请假/申诉/科目注册/校历演示数据 | 同上 | **迁** | 同类 |
| 8 | `fix_user.py` | 本地夹具：建 `stu@local` 门户账号并绑定学生 | 被 `docs/audit/identity-lookup-unification.md` 第 17 条点名（**该文档写的路径就是 `scripts/fix_user.py`**） | **迁** | 测试身份 `stu@local` 是 `tests/smoke/ux_v3_route_matrix.py` 等在用的夹具；迁走让文档与现实一致 |
| 9 | `seed_tg_demo.py` | 退役模块 `edu_telegram` 的演示数据 | 0 处可执行引用 | **迁** | 该模块已按用户裁定退役（`docs/audit/deprecated-inventory.md` B8，生产从未部署）；它仍属「种子」类，归 `scripts/`，不替队长做模块删除决定 |
| 10 | `seed_tg_users.py` | 同上：建演示学生/教师/家长门户账号 | 0 处可执行引用 | **迁** | 同上 |

> 迁移用 `git mv`（**只入暂存区、不 commit**），便于队长在 `git status` 里一眼看到 rename 而不是「删+新增」。

### 2.2 三条删除的零引用证据（命令 + 原样输出）

**命令（2026-10-02 18:31，仓根）**

```bash
for f in fix_menus seed_menus seed_fees; do
  grep -rn -F "$f.py" --include='*.py' --include='*.sh' --include='*.md' --include='*.xml' \
    --include='*.yml' --include='*.json' --include='*.txt' . | grep -v '^./.git/' | grep -v '/.agent-teams/'
  grep -rn -F "$f.py" --include='*.sh' --include='*.yml' --include='Makefile' --include='*.py' .
done
```

**原样输出（关键部分）**

```
===== fix_menus.py 引用 =====
./tests/gap/exec_U.md:7:2. 历史脚本 `custom_addons/seed_menus.py`、`fix_menus.py` 正是通过创建/移动 `website.menu` 记录来控制导航的。
./tests/gap/exec_U.md:10:→ 按任务分支规定，采用**数据驱动方案**：新建幂等种子脚本 `scripts/seed_d1_nav.py`（…）。顺序参照 … 与 `fix_menus.py` 的 sequence 约定。
./scripts/seed_d1_nav.py:73:# ---- 一级入口（seq 沿用 fix_menus.py 的原站顺序约定）----
  -- 可执行引用: ./scripts/seed_d1_nav.py:73（**注释**，非调用）  ⇒ 0 处可执行引用
===== seed_menus.py 引用 =====
./tests/gap/exec_U.md:7:2. 历史脚本 `custom_addons/seed_menus.py`、`fix_menus.py` …
  -- 可执行引用: (空)  ⇒ 0 处可执行引用
===== seed_fees.py 引用 =====
./docs/plans/review-t5-i18n.md:37:| ec335a7 | …、seed_fees.py、scripts/{i18n_glossary.json,seed_fees_demo.py}、… |
  -- 可执行引用: (空)  ⇒ 0 处可执行引用
```

**证据②（`seed_fees.py` 写错了模型：页面读 `edu.fee.bill`，它写 `account.move`）**

```bash
grep -n "edu.fee.bill\|account.move" custom_addons/edu_portal/controllers/fees.py
```
```
66:        Bill = env['edu.fee.bill'].sudo()
144:        Bill = env['edu.fee.bill'].sudo()
203:        bill = env['edu.fee.bill'].sudo().browse(bill_id)
239:        Bill = env['edu.fee.bill'].sudo()
283:        Bill = env['edu.fee.bill'].sudo()
351:            '报销申请', 'edu.fee.bill', bill.id,
```
它的自我说明是「给演示学生造费用发票（档案页 Fees tab / 首页 Fees Statements 卡）」，实际写的是
`account.move`（`move_type='out_invoice'`）—— **与页面数据源无交集** ⇒ 说明本身已失真。

**证据③（本地库里真正生效的那份是 `scripts/seed_fees_demo.py`）**

```bash
# ① 该脚本自己的 FEE-SEED 标记票：0 行
python3 docs/audit/redundancy/orm_query.py --model account.move --domain '[["ref","like","FEE-SEED"]]' --fields ref,state
# → []
# ② 页面读的模型里正好是 scripts/seed_fees_demo.py 造的两笔（账单名逐字相同）
python3 docs/audit/redundancy/orm_query.py --model edu.fee.bill --domain '[]' --fields id,name,student_id,state
# → id1【演示】2026 春季统筹费 open / id2【演示】教材资料费 partial
grep -n 'ensure_bill(' scripts/seed_fees_demo.py
# → 40:ensure_bill('【演示】2026 春季统筹费', 12000.0,
# → 42:ensure_bill('【演示】教材资料费', 300.0,
```

### 2.3 迁移的知识保全：`fix_menus.py` 的 sequence 约定原文（删前抄录）

```python
seq_map = {'商店': 20, '现在预订': 30, '图书馆': 40, '考试': 50,
           '活动': 60, '论坛': 70, '博客': 80, '入场': 90,
           '工作机会': 100, '工作': 110, '校友': 130,
           'Courses': 140, '展示位置': 150}
```

同一约定已活在 `scripts/seed_d1_nav.py` 的「一级入口」段落；「展示位置（Placements）」由
`setup_brand_yongyue.py`/`seed_d1_nav.py` 明确跳过（企业版独有）。

### 2.4 落地动作（已执行，未 commit）

```bash
for f in seed_demo seed_batch1 seed_batch2 seed_batch3 fix_user seed_tg_demo seed_tg_users; do
  git mv custom_addons/$f.py scripts/$f.py        # 7 次 rename（入暂存区）
done
rm custom_addons/{fix_menus,seed_menus,seed_fees}.py   # 3 次删除
rm custom_addons/__pycache__/*.pyc                     # 10 个陈旧字节码（源已迁/删）
```
迁移后 `custom_addons/` 根**只剩模块目录**（12 个）；`scripts/seed_batch{1,2,3}.py` 用法注释里的
`< custom_addons/seed_batchN.py` 已同步改为 `< scripts/seed_batchN.py`（自洽，避免下次照抄错路径）。

## 3. B 组：`static/src` 下 30 个 js/css/scss —— 全部留，0 删

**对账方法**：`docs/audit/redundancy/asset_audit.py` —— 逐文件查 ① 文件名是否出现在同模块
`__manifest__.py`（给行号 + 所属 bundle）② 其它 `.py/.xml/.js/.css/.scss/.md/.sh/.json` 是否引用它
（排除自身与本审计目录，避免自证污染）。

```bash
/opt/homebrew/bin/python3 docs/audit/redundancy/asset_audit.py --json docs/audit/redundancy/assets_report.json
# → assets=30 manifest_miss=0
```

**全表（30/30 命中，0 个 MISS）** —— 判定栏一律「留」，理由见下方：

| 文件 | manifest 行 | bundle | 其它引用（文件数） | 判定 |
|---|---|---|---|---|
| `custom_addons/edu_apply/static/src/css/apply.css` | L18 | `web.assets_frontend` | 1：`custom_addons/edu_apply/__manifest__.py` | 留 |
| `custom_addons/edu_apply/static/src/js/apply_form.js` | L17 | `web.assets_frontend` | 2：`custom_addons/edu_apply/__manifest__.py`, `custom_addons/edu_portal/views/register.xml` | 留 |
| `custom_addons/edu_assess/static/src/css/assess_grid.css` | L50 | `web.assets_frontend` | 8：`custom_addons/edu_assess/__manifest__.py`, `custom_addons/edu_assess/static/src/js/assess_grid.js`…(+6) | 留 |
| `custom_addons/edu_assess/static/src/js/assess_grid.js` | L51 | `web.assets_frontend` | 10：`custom_addons/edu_assess/__manifest__.py`, `custom_addons/edu_assess/static/src/css/assess_grid.css`…(+8) | 留 |
| `custom_addons/edu_brand/static/src/css/backend_b11.css` | L41 | `web.assets_backend` | 17：`custom_addons/edu_brand/__manifest__.py`, `custom_addons/edu_portal/static/src/js/apps_panel_chip.js`…(+15) | 留 |
| `custom_addons/edu_brand/static/src/css/brand.css` | L26 | `web.assets_frontend` | 11：`custom_addons/edu_brand/__manifest__.py`, `custom_addons/edu_portal/static/src/css/custom_home.css`…(+9) | 留 |
| `custom_addons/edu_brand/static/src/js/backend_doc_link.js` | L43 | `web.assets_backend` | 1：`custom_addons/edu_brand/__manifest__.py` | 留 |
| `custom_addons/edu_brand/static/src/js/user_menu_debrand.js` | L42 | `web.assets_backend` | 4：`custom_addons/edu_brand/__manifest__.py`, `custom_addons/edu_brand/views/odoo_debrand.xml`…(+2) | 留 |
| `custom_addons/edu_brand/static/src/scss/backend_variables.scss` | L48 | `web._assets_primary_variables` | 9：`custom_addons/edu_brand/__manifest__.py`, `custom_addons/edu_brand/static/src/css/backend_b11.css`…(+7) | 留 |
| `custom_addons/edu_brand/static/src/scss/brand_tokens.scss` | L51 | `web._assets_primary_variables` | 17：`custom_addons/edu_brand/__manifest__.py`, `custom_addons/edu_brand/static/src/css/backend_b11.css`…(+15) | 留 |
| `custom_addons/edu_portal/static/src/css/banner.css` | L148 | `web.assets_frontend` | 5：`custom_addons/edu_portal/__manifest__.py`, `docs/audit/portal-color-token-map-t4.md`…(+3) | 留 |
| `custom_addons/edu_portal/static/src/css/batch1.css` | L132 | `web.assets_frontend` | 4：`custom_addons/edu_portal/__manifest__.py`, `docs/audit/portal-color-token-map-t4.md`…(+2) | 留 |
| `custom_addons/edu_portal/static/src/css/batch3.css` | L134 | `web.assets_frontend` | 6：`custom_addons/edu_portal/__manifest__.py`, `docs/audit/portal-color-token-map-t4.md`…(+4) | 留 |
| `custom_addons/edu_portal/static/src/css/custom_home.css` | L136 | `web.assets_frontend` | 22：`custom_addons/edu_brand/static/src/scss/brand_tokens.scss`, `custom_addons/edu_portal/__manifest__.py`…(+20) | 留 |
| `custom_addons/edu_portal/static/src/css/enroll.css` | L139 | `web.assets_frontend` | 3：`custom_addons/edu_portal/__manifest__.py`, `docs/audit/portal-color-token-map-t4.md`…(+1) | 留 |
| `custom_addons/edu_portal/static/src/css/enterprise.css` | L135 | `web.assets_frontend` | 10：`custom_addons/edu_portal/__manifest__.py`, `docs/audit/portal-color-token-map-t4.md`…(+8) | 留 |
| `custom_addons/edu_portal/static/src/css/portal.css` | L133 | `web.assets_frontend` | 13：`custom_addons/edu_portal/__manifest__.py`, `docs/audit/edu-eval-removal.md`…(+11) | 留 |
| `custom_addons/edu_portal/static/src/css/search_suggest.css` | L152 | `web.assets_frontend` | 1：`custom_addons/edu_portal/__manifest__.py` | 留 |
| `custom_addons/edu_portal/static/src/css/ux_rework.css` | L138 | `web.assets_frontend` | 10：`custom_addons/edu_portal/__manifest__.py`, `docs/audit/portal-color-token-map-t4.md`…(+8) | 留 |
| `custom_addons/edu_portal/static/src/css/ux_v3.css` | L141 | `web.assets_frontend` | 8：`custom_addons/edu_portal/__manifest__.py`, `docs/audit/portal-color-token-map-t4.md`…(+6) | 留 |
| `custom_addons/edu_portal/static/src/js/alerts_read.js` | L144 | `web.assets_frontend` | 4：`custom_addons/edu_portal/__manifest__.py`, `custom_addons/edu_portal/static/src/js/msg_poll.js`…(+2) | 留 |
| `custom_addons/edu_portal/static/src/js/apps_menu_redirect.js` | L160 | `web.assets_backend` | 1：`custom_addons/edu_portal/__manifest__.py` | 留 |
| `custom_addons/edu_portal/static/src/js/apps_panel_chip.js` | L161 | `web.assets_backend` | 5：`custom_addons/edu_portal/__manifest__.py`, `docs/plans/color-system-v4.md`…(+3) | 留 |
| `custom_addons/edu_portal/static/src/js/home_favs.js` | L146 | `web.assets_frontend` | 8：`custom_addons/edu_portal/__manifest__.py`, `custom_addons/edu_portal/controllers/batch2.py`…(+6) | 留 |
| `custom_addons/edu_portal/static/src/js/home_search.js` | L143 | `web.assets_frontend` | 3：`custom_addons/edu_portal/__manifest__.py`, `tests/smoke/E_quiz_cross.md`…(+1) | 留 |
| `custom_addons/edu_portal/static/src/js/msg_poll.js` | L145 | `web.assets_frontend` | 4：`custom_addons/edu_portal/__manifest__.py`, `custom_addons/edu_portal/views/batch2.xml`…(+2) | 留 |
| `custom_addons/edu_portal/static/src/js/notice_banner.js` | L149 | `web.assets_frontend` | 3：`custom_addons/edu_portal/__manifest__.py`, `custom_addons/edu_portal/controllers/batch2.py`…(+1) | 留 |
| `custom_addons/edu_portal/static/src/js/quick_login.js` | L142 | `web.assets_frontend` | 4：`custom_addons/edu_portal/__manifest__.py`, `docs/deploy-malaysia.md`…(+2) | 留 |
| `custom_addons/edu_portal/static/src/js/search_focus.js` | L147 | `web.assets_frontend` | 4：`custom_addons/edu_portal/__manifest__.py`, `custom_addons/edu_portal/static/src/js/search_suggest.js`…(+2) | 留 |
| `custom_addons/edu_portal/static/src/js/search_suggest.js` | L153 | `web.assets_frontend` | 5：`custom_addons/edu_portal/__manifest__.py`, `custom_addons/edu_portal/controllers/search.py`…(+3) | 留 |

**判定：0 删除。** 30 个文件**逐个**都写在自己模块 manifest 的**活跃 bundle** 里
（`web.assets_frontend` / `web.assets_backend` / `web._assets_primary_variables`），
没有一个是「没有 manifest 入口的孤儿文件」；另有一批被测试与设计文档当**证据件**引用
（如 `assess_grid.js` 被 `tests/smoke/assess_grid_sticky_paste.py`、`backend_b11.css` 被 `tests/color/*`）——
删任何一个都会同时打断多个门禁，收益为负。

> 诚实的边界：本表只证明「**文件被注册/被引用**」，**不**证明「文件内部没有死代码」
> （例如无人使用的 CSS 规则）。那是另一把尺子（`tests/color/color_audit.py`、`scripts/check_accessibility.py`），
> 不在本卡「文件级去冗余」的范围。

## 4. C 组：309 条路由 —— 0 条可判死

### 4.1 三源读数

```
route_probe.py    → handlers=307 routes=309 files=40 unparsed=0
route_registry.py → routing rules=769 → docs/audit/redundancy/routing_map.json
route_reach.py    → 6 身份 × 309 条；relogin events: 5（§7.2 判据修正）
```

| 判据 | 读数 | 说明 |
|---|---|---|
| 代码里有、跑着的进程没有 | **0** | 无「声明了却没注册」的路由 |
| 任一角色 5xx / 响应含 Traceback | **0** | 探针全程无服务端错误 |
| 全角色 404 | **2** | 均为 token 路由，见 §4.2（已证 200） |
| 0 代码入链 | 见 §4.3 / §4.4 | 逐条人工复核后**全部有真实入口或已登记** |

### 4.2 「全角色 404」两条 —— 逐条证伪（为什么不能删）

**① `/my/calendar/ics/<token>`（edu_portal/controllers/ical.py）**
探针传的是占位符 `token=1` ⇒ 404 **是设计上的 fail-closed**。用真 token 实测：

```bash
python3 docs/audit/redundancy/orm_query.py --model res.users --domain '[["login","=","stu@local"]]' --fields id,login,edu_ical_token
# → [{"id":8,"login":"stu@local","edu_ical_token":"971c5610a2fcc69f99335de497b92d66"}]
curl -s -o /tmp/ics.out -w 'status=%{http_code} type=%{content_type} bytes=%{size_download}\n' \
  'http://127.0.0.1:8069/my/calendar/ics/971c5610a2fcc69f99335de497b92d66'
```
```
status=200 type=text/calendar; charset=utf-8 bytes=394
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Yongyue Edu//Portal Calendar//CN
X-WR-CALNAME:永约学坊·我的日历
```
⇒ 它是**外部订阅入口**（手机日历/Google Calendar/Outlook 订阅一次即持续同步），0 入链是它的本性。

**② `/telegram/report/<string:token>`（edu_telegram，退役模块）**
控制器自己解析 token：`exp, sig = token.split('-', 1)` 失败即 `request.not_found()`（`controllers/main.py` 的
`telegram_report`，取证时刻 2026-10-02）。探针传 `token=1` ⇒ 必然 404。**路由是匹配上的**（注册表在册），
这类 404 是鉴权/参数语义，不是死路由。该模块已退役（deprecated-inventory B8），**是否随模块一并删除由队长裁定**，本卡不动。

### 4.3 「0 代码入链」逐条判定（人工复核）

| 路由（定义文件） | 6 身份实测（2026-10-02 18:2x） | 入口证据 | 判定 |
|---|---|---|---|
| `/student/progression`（`edu_portal/controllers/batch2.py`） | anon 303→/web/login；其余 5 身份 **200** | 卡片 key：`batch2.py:234 ('student/progression', '进展',`、`:431 'student/progression': ('fa-line-chart', …)`；href 由 `'href': '/' + href` 运行时拼出（取证块） | 留 |
| `/my/asset-request`（`batch3.py`） | anon 303；其余 5 身份 **200** | 卡片 key：`batch2.py:240 ('my/asset-request', '资产请求', …)`、`:327`、`:432` | 留 |
| `/my/thesis`（`batch3.py`） | anon 303；其余 5 身份 **200** | 卡片 key：`batch2.py:282 ('my/thesis', '论文', …)`、`:441`、`:850` | 留 |
| `/my/dms`（`batch3.py`） | anon 303；其余 5 身份 **200** | **custom_addons 内 0 具名引用**；仅 `scripts/review_spotcheck_t2.py:173` 的路由清单里出现 `"my/dms"`（batch2.py:342 只有一行注释点名） | 留（**孤儿页**，登记） |
| `/student/subjects`（`enroll.py`） | stu **200**；fac/par/bo/admin 303→`/my/home` | **custom_addons 内 0 具名引用**（只有 `views/enroll.xml`/`study.xml` 两处自身模板注释） | 留（**孤儿页**，登记） |
| `/my/points/me`（`welfare.py`） | stu **200**；其余 303→`/my/home` | **custom_addons 内 0 具名引用**（只有 `views/welfare.xml:347` 自身模板注释） | 留（**孤儿页**，登记） |
| `/my/checkin/board`（`welfare.py`） | stu **303→/my/checkins**；fac/bo/admin **200**；par 303 | **custom_addons 内 0 具名引用**；但 `docs/audit/deprecated-inventory.md` **C-04** 明写「保留功能（教师/教务全员到堂看板），无计划删除」 | 留 |
| `/my/search/suggest`（`search.py`） | stu/fac/par/bo/admin **200**；anon 303 | JS 端点：`static/src/js/search_suggest.js:23 var ENDPOINT = "/my/search/suggest"`（渐进增强，无脚本时回退表单 GET `/my/search`） | 留 |
| `/my/calendar/ics/<token>`（`ical.py`） | 占位 token 全 404；**真 token 200 text/calendar** | `controllers/calendar.py:150 return '%s/my/calendar/ics/%s' % (base.rstrip('/'), token)` 生成订阅 URL（页面渲染时出现）；本质是**外部订阅入口** | 留 |
| `/my/lang/<string:code>`（`search.py`） | 6 身份全 303→`/my/home` | 控件已按裁定撤除（`edu_portal_templates.xml` 与 `brand_templates.xml:241` 两处注释写明根因 + **恢复步骤**） | 留（恢复路径的一环） |
| `/web/register`（`main.py` + `register.py` 各注册一次） | 6 身份全 **302→/register** | 旧地址兼容壳 `EduRegisterAlias(EduRegister)`（`main.py:341`）与父类同路径**双注册**；友好页 `/register` 实测 **200**（标题「Edu Register (Invite Code)｜永约学坊」） | 留（**同上路径双注册**已登记，见 §4.5） |
| `/web/register/submit`（同上双注册） | GET 全 **405**（POST 专用） | 同上 | 留 |
| `/online-exams`（`edu_public/main.py`） | 6 身份 **200** | **DB 菜单**：`website.menu` id=18「考试」→`/online-exams`（ORM 实测） | 留 |
| `/booking`（同上） | 6 身份 **200** | DB 菜单 id=181「现在预订」 | 留 |
| `/courses-offered`（同上） | 6 身份 **200** | DB 菜单 id=186「开设课程」 | 留 |
| `/program-offered`（同上） | 6 身份 **200** | DB 菜单 id=187「培养项目」 | 留 |
| `/alumni/job/card`（同上） | 6 身份 **200** | DB 菜单 id=189「校友招聘」（挂在「工作机会」下） | 留 |
| `/telegram/webhook`（`edu_telegram`） | GET 全 **405** | **外部入口**：Telegram 服务器回调；宿主模块已退役（B8） | 留（随模块退役处置） |
| `/telegram/report/<string:token>`（`edu_telegram`） | 全 **404**（token 不可伪造） | **外部入口**：Telegram 消息里的签名下载链（§4.2②） | 留（随模块退役处置） |
| `/telegram/tgb/webhook`（`edu_tg_bind`） | GET 全 **405** | **外部入口**：官方 setWebhook；`X-Telegram-Bot-Api-Secret-Token` + fail-closed（模块文档 §7） | 留 |

> 「6 身份实测」列的原样读数是 `/tmp/reach.json`（探针输出），可复跑（§9）。
> 「入口证据」里的行号是 **2026-10-02 的取证块**（code-map §6 第 15 条：不得据此定位代码，用符号名复核）。

**关于两条「孤儿页」（`/student/subjects`、`/my/points/me`）**：判据只能证明「0 代码入链」，
**不能证明没人用** —— 同一把尺子把 `/my/calendar/ics/<token>`（外部订阅入口）也判成了 0 入链。
所以处置是**登记不删**，交队长/产品裁量：真要删，判据应是「产品确认无入口 + 模板/文档同步清理 + 303 兼容壳」，
不是「grep 没命中」。

### 4.4 自动判据的两次修正（v1 → v2 → v3，防误判）

1. **v1**：只全文找「带前导斜杠的路径」⇒ 把卡片引擎 key（`student/progression`）当 0 入链。**误**。
2. **v2**：追加「带引号的无斜杠多段路径」（依据：batch2.py 的 `cards()`/`card_href` 分支写的是
   `'href': '/' + href`，即 key 无斜杠、href 有斜杠）；但改用合并正则 `findall` 做判定 —— 而 `findall` 是
   **非重叠**匹配，长路径会吃掉自己那段，导致作为其**前缀**的短路由（`/my/checkin` ⊂ `/my/checkin/board`）漏判。**又一误**。
3. **v3（现行）**：合并正则只做**快速排除**（C 层扫描），命中行再逐 key 精确判定 ⇒ 既有 v1 的完备性，又有 v2 的速度。

### 4.5 附带发现：`/web/register` 同路径双声明（登记，不动）

`register.py` 的 `EduRegister` 声明 `/web/register`（渲染表单，`sitemap=True`）与 `/web/register/submit`；
`main.py` 的 `EduRegisterAlias(EduRegister)` 又声明同名两条（分别改成 302→`/register` 与 `super()` 转发）。
实测（2026-10-02）：

```bash
# 跑着的进程里，同路径只剩别名类那几条；父类那两条**根本不在注册表**
python3 -c "import json;rows=json.load(open('docs/audit/redundancy/routing_map.json'));
print([(x['rule'], x['endpoint']) for x in rows if x['rule'] in ('/web/register','/register')])"
# → [('/register', '…controllers.main.register_form'), ('/web/register', '…controllers.main.register_form_legacy')]
# 父类（controllers/register.py）在注册表里的规则数：
# → 0
# 站点地图只收友好页（/register 200），旧地址是 302 壳
curl -s http://127.0.0.1:8069/sitemap.xml | grep -o '<loc>[^<]*</loc>'   # 28 条，含 /register，不含 /web/register
```

**判定：留，不动。** 理由：① 父类**实现**是活的（别名类的 `/register` 与两条 submit 都经 `super()` 调到它），死的只是父类那两条
**路由声明**；② 别名壳正是「旧地址兼容」的实现（`redirect('/register', code=302)`）；③ 只凭「声明不可达」就删代码，风险与收益不成比例
（要动就动 `register.py` 的 `@http.route`，且必须重跑注册冒烟）。⇒ 登记在案（见 §8 F7）。

## 5. 对 `scripts/deploy_myedu.sh` rsync 清单的影响：**零改动**

**原样引用（`scripts/deploy_myedu.sh` 第 182–183 行，取证时刻 2026-10-02）**：

```bash
rsync -az --exclude='__pycache__' -e "$RSYNC_SSH" \
  edu_life edu_schedule edu_apply edu_portal edu_brand edu_quiz edu_public edu_zh edu_tg_bind edu_assess edu_nav "$REMOTE:$DIR/custom_addons/"
```

| 问题 | 答案 | 证据 |
|---|---|---|
| 删/迁的散件在 rsync 清单里吗？ | **不在** | 清单只列 11 个**模块目录**；散件是 `custom_addons/*.py` 文件，rsync 从不搬运 |
| 删掉会从生产消失吗？ | **不会** | 生产那 10 个副本来自 2026-10-01 换机的**整树同步**；此后部署脚本不再触碰 ⇒ 本地删除**不回收**远端副本 |
| 要改 rsync 清单吗？ | **不需要** | 清单语义 = 「哪些模块上生产」，与散件无关；改清单反而会把非模块文件推上生产 |
| 要顺手删生产上的散件吗？ | **本卡不做**（纪律：不碰生产） | 记一条运维待办：新机 `/opt/edu-app/custom_addons/` 下 10 个 `.py` 是无主副本，随下次维护清理（`ssh` 与删除均需队长执行） |
| 静态资源/路由有影响吗？ | **没有**（0 删） | §3 / §4 |
| 其它清单会不会耦合？ | 已核，不会 | 部署里的 `chmod -R a+rX` 走整树、不枚举文件（`deploy_myedu.sh` 注自陈「消灭两份列表」）；`safe_upgrade.sh` gate A 只关心「manifest 引用集 ⊆ git 跟踪集」 |

## 6. 门禁读数（命令 + 原样输出，2026-10-02）

### 6.1 `check_stray_addons.py`（本卡新增的防复发守卫，离线）
```
$ python3 docs/audit/redundancy/check_stray_addons.py
散件守卫：绿（custom_addons 根 0 游离文件；模块 12 个；迁移台账 7 项全部就位）
EXIT=0
```
判据（**零豁免**）：**R1** `custom_addons/` 根下不得有游离文件；**R2** 名字符合 Odoo 模块名规则
（`^\w{1,256}$`，与 `odoo/modules/module.py` 的 `MODULE_NAME_RE` 同源）的目录必须有 `__manifest__.py`；
**R3** 迁移台账里的文件必须在 `scripts/` 就位、且不在原位置。

### 6.2 `scripts/safe_upgrade.sh edu_portal`（硬验收：升级链没坏）
```
$ bash scripts/safe_upgrade.sh edu_portal        # 2026-10-02 18:33
[safe_upgrade] manifest 跟踪检查通过（scripts/check_manifest_tracking.py）
[safe_upgrade] 静态检查通过（scripts/check_view_xpath.py RESULT=OK)
[safe_upgrade] shell 变量静态检查通过（scripts/check_shell_exitcode.py）
[safe_upgrade] init() 跨表回填静态检查通过（tests/smoke/init_cross_table_check.py）
[safe_upgrade] 挂载自检：抽查 1 个近期改动文件，失步 0 个
[safe_upgrade] 已取锁：-u edu_portal
…（省略升级明细，完整日志 /tmp/edu19_upgrade.20261002-183326.log）
[safe_upgrade] 重启 web 以清进程内缓存…
 Container edu19-clone-web-1 Restarting
 Container edu19-clone-web-1 Started
[safe_upgrade] 就绪：/web/login?db=edu19 → 302
[safe_upgrade] 结束：edu_portal（无失败特征；完整日志 /tmp/edu19_upgrade.20261002-183326.log）
EXIT=0

$ grep -c 'Traceback' /tmp/edu19_upgrade.20261002-183326.log
0
```
**两条诚实说明**：
1. **第一次跑是红的，红在跨队 gate C，不在我**：18:30 那次 `EXIT=6`，gate C `check_shell_exitcode.py`
   报 19 命中（全部来自 `scripts/backup_daily.sh / backup_pull.sh / restore_rehearsal.sh`，2026-10-01 22:34 入库）。
   我做了控制组（§7.3）把「19 条 100% 来自哪三个文件」钉死并报队长；队长 18:32 按仓规改成 `${VAR}` 后归零，
   18:33 复跑即上面的绿读数。
2. 升级日志里唯一一条 `ERROR` 是 `<string>:16: (ERROR/3) Unexpected indentation` —— docutils 渲染模块描述
   RST 的**排版告警**，不是升级失败特征（升级本身 EXIT=0、无 Traceback、就绪探活 302）。见 §8 F6。

### 6.3 `scripts/check_ui_usability.py`（硬验收：站点没坏）
```
$ /opt/homebrew/bin/python3 scripts/check_ui_usability.py     # 2026-10-02 18:35
================ 汇总 ================
探页 148 条 = 99 页 × 身份；探到 142 ｜ 非环境失败 0 ｜ 环境失败 0 ｜ 排除 31
命中（原始）：A 0 ｜ B 0 ｜ C 0 ｜ D 0 = 0 条；去重键 0 个（报红 0 条 / 0 页）
读数落盘：tests/ui/readings/usability-20261002-1837.json（指纹 4f53cda18c2baa0c）
采集时刻 2026-10-02T18:35:04+08:00 ｜ 并发 quiet ｜ 容器 edu19-clone-web-1（样本有效=True）
探页引擎：browser 重启 4 次（每 30 条一次，重启点 [31, 61, 91, 121]）｜ 探页异常（非环境）0 条
自证行：REVISION=v1.0 · 指纹 475b211f · 运行时刻 2026-10-02T18:35:04+08:00
EXIT=0
```
**诚实说明（环境型假红不是红，但也不能当通过）**：18:31 那次跑到一半时，我并发启动了 `safe_upgrade`，
它重启了 web 容器 ⇒ 该轮被自己判成 `ENV：采样期间 web 容器重启 ⇒ 样本作废`（`EXIT=2`）。
停掉升级后 18:35 复跑才有上面这份**样本有效=True** 的读数。⇒ 门禁与升级要**串行**跑。

### 6.4 `route_audit.py`（三源合并，v3 判据）
```
$ python3 docs/audit/redundancy/route_audit.py
routes=309  未注册=0  0 代码入链=22（其中连 key/文档引用也没有=8）  全角色 404=2
```
「连 key/文档引用也没有＝8」的精确名单（复跑命令：`python3 -c "import json;rows=json.load(open('docs/audit/redundancy/routes_report.json'));"…`）：
`/web/register` 与 `/web/register/submit`（各在 `main.py` 与 `register.py` 声明一次 ⇒ 4 条规则）、`/my/search/suggest`、`/my/checkin/board`、`/my/points/me`、`/telegram/report/<string:token>`。
其中：旧地址双声明见 §4.5（`/register` 实测 200）；`/my/search/suggest` 由 JS 端点进入；`/my/checkin/board` 由 deprecated-inventory C-04 背书；`/my/points/me` 是真孤儿页（登记不删）；`/telegram/report` 是外部入口。
⇒ 这 8 条**没有一条能判死**：它们要么有非代码入口、要么有台账背书、要么只是「没人链接」而不可证伪其无用。

## 7. 反向自证

### 7.1 散件守卫：三条注入 → 三条变红 → 还原复绿（原样输出）

```
$ python3 docs/audit/redundancy/check_stray_addons.py          # 基线
散件守卫：绿（custom_addons 根 0 游离文件；模块 12 个；迁移台账 7 项全部就位）
EXIT=0

$ git checkout HEAD -- custom_addons/seed_fees.py            # 注入 1：把判定为「删」的还原
$ python3 docs/audit/redundancy/check_stray_addons.py
散件守卫：红（1 条）
  R1 游离文件（不是模块）：custom_addons/seed_fees.py
EXIT=1
$ rm custom_addons/seed_fees.py

$ git checkout HEAD -- custom_addons/seed_menus.py           # 注入 2：另一条「删」
$ python3 docs/audit/redundancy/check_stray_addons.py
散件守卫：红（1 条）
  R1 游离文件（不是模块）：custom_addons/seed_menus.py
EXIT=1
$ rm custom_addons/seed_menus.py

$ mv scripts/seed_demo.py /tmp/seed_demo.proof.py            # 注入 3：把「迁」走的藏起来
$ python3 docs/audit/redundancy/check_stray_addons.py
散件守卫：红（1 条）
  R3 迁移台账说它在 scripts/，但找不到：scripts/seed_demo.py
EXIT=1
$ mv /tmp/seed_demo.proof.py scripts/seed_demo.py

$ python3 docs/audit/redundancy/check_stray_addons.py        # 还原后
散件守卫：绿（custom_addons 根 0 游离文件；模块 12 个；迁移台账 7 项全部就位）
EXIT=0
```

⇒ 量具不是恒真：删掉的东西「复活」、迁走的东西「失踪」，它都当场报红；还原即复绿。

### 7.2 检查器自己的三次修复（判据纠错记录，避免后人重踩）

| # | 错在哪 | 怎么发现的 | 修法（判据化，不写白名单） |
|---|---|---|---|
| 1 | **探针会话串味**：跑到 `/logout` 之后，5 个登录身份的会话全被登出，后续路由一律 `303 → /web/login` | 读数与手工 curl **矛盾**：同一条 `/my/checkin/board`，探针 303、curl 200 | 凡 3xx 且 Location 指向登录页 ⇒ **重登一次再探**。修后 `relogin events: 5`（正好 5 个登录身份），读数恢复 |
| 2 | **入链判据漏掉卡片 key**：只找带前导斜杠的路径 ⇒ 把 `'student/progression'` 这类运行时 key 当 0 入链 | 直接 grep `_OPENEDUCAT_CARDS` 有命中，与自动判据对不上 | 追加「带引号的无斜杠多段路径」并**单列 key 桶**（不与 link 桶混算） |
| 3 | **改用合并正则后短路径漏判**：`findall` 是**非重叠**匹配，长路径吃掉自己那段，作为其前缀的短路由（`/my/checkin` ⊂ `/my/checkin/board`）漏判 | v2 读数从 22 条「0 入链」涨到 30 条 —— **变多本身就是信号** | 合并正则只做**快速排除**，命中行再逐 key 精确判定（v3：22 条，与人工复核一致） |

### 7.3 控制组（用于 §6.2 的跨队阻塞判定）

```bash
# 反事实 A：scripts/*.sh 里**除 3 个备份脚本外**的 8 个 → 临时目录
python3 scripts/check_shell_exitcode.py "$d"
扫描 8 个 shell 脚本｜跳过 0
RESULT=OK（命中 0 / 跳过 0）
# 反事实 B：只放那 3 个
python3 scripts/check_shell_exitcode.py "$d2"
BOUNDARY-DRIFT 命中数 19 ≠ 常量 0 —— 有意变更请同步 EXPECTED_HITS
RESULT=FAIL（命中 19 / 跳过 0）
```

⇒ 「19 条 100% 来自那 3 个文件」，我的改动贡献 0 条。另：我顺手做了门禁**技术前提**的控制实验
（`echo "x $STAGE_DIR（含…）"` 实测正常输出 ⇒ 全角括号不会被吞），队长据此把 gate 的**理由**更正为
「书写约定」（判据强度不变，并把 `${BASE}_x` 这个真反例写进注释）。

## 8. 遗留与建议（不在本卡写范围内，交队长派单）

| # | 事项 | 证据 / 建议 |
|---|---|---|
| F1 | `docs/code-map.md` §7「scripts/ 分类索引」把 `seed_batch1-3 / seed_demo / seed_fees / seed_menus / fix_menus / fix_user` 都登记在 `scripts/` 下，而它们此前在 `custom_addons/` 根 | 本轮迁移让其中 7 条**变真**；`seed_fees / seed_menus / fix_menus` 已删 ⇒ 建议从 §7 删掉这三个名字（一行改动） |
| F2 | 4 处**过期路径引用**（迁移后） | `specs/batch2.md:20`、`tests/gap/exec_U.md:7`、`docs/research/gradebook-entry.md:307/309` 仍写 `custom_addons/seed_*.py`。**未改**：前两条是历史施工记录、后两条是带行号的**取证块**（code-map §6 第 15 条：历史取证块保留不动）⇒ 建议队长各加一行「该文件已于 2026-10-02 迁至 scripts/」 |
| F3 | 生产机 `/opt/edu-app/custom_addons/` 上仍有 10 个散件副本 | 见 §5；本地删除不回收远端 ⇒ 记运维待办（队长执行） |
| F4 | 两条孤儿页 `/student/subjects`、`/my/points/me`（可达但 0 代码入链） | 见 §4.3 末段；建议列入 `docs/audit/deprecated-inventory.md` 台账（登记不删），不要拿 grep 结果直接删 |
| F5 | `custom_addons/__pycache__/` | 本轮已清掉 10 个陈旧 `.pyc`；目录未跟踪，无需处置 |
| F6 | safe_upgrade 日志里 `<string>:16: (ERROR/3) Unexpected indentation`（docutils 渲染模块描述的 RST 排版告警，非升级失败） | 升级本身无 Traceback、无失败特征（EXIT=0）；若要消掉这条噪音，修的是模块 description 的 RST 排版，属另一条线 |
| F7 | `/web/register` 同路径双声明：父类 `register.py` 的两条 @http.route 在跑着的注册表里为 0 条（被同名路径覆盖），活的是别名类的壳 | 见 §4.5；建议写入 `docs/audit/deprecated-inventory.md`「有意双声明」一行，避免后人误删父类实现（父类实现经 `super()` 在用） |

## 9. 复跑手册（三分钟）

```bash
cd /Users/qwe/Documents/文件大总管/10-项目/教务系统网站新架构
python3 docs/audit/redundancy/check_stray_addons.py             # 散件守卫（离线）
/opt/homebrew/bin/python3 docs/audit/redundancy/asset_audit.py  # 静态资源对账（离线）
/opt/homebrew/bin/python3 docs/audit/redundancy/route_probe.py --json /tmp/routes.json
/opt/homebrew/bin/python3 docs/audit/redundancy/route_registry.py
/opt/homebrew/bin/python3 docs/audit/redundancy/route_reach.py --json /tmp/reach.json   # 需本地站
/opt/homebrew/bin/python3 docs/audit/redundancy/route_audit.py                          # 三源合并
```
> 探针依赖本地站（`http://127.0.0.1:8069`）与演示账号（`stu@local / faculty@local / parent@local /
> backoffice@local / admin`，口令均 `demo123`，取自 `tests/smoke/ux_v3_route_matrix.py` 的既有口径）。
> **反证提示**：若有人把某条路由判死并删掉，`route_reach.py` 该条必须从 200/303 变成真 404
> —— 这就是这套判据「能变红」的定义。
