# -*- coding: utf-8 -*-
"""去 Odoo / 基座品牌痕迹门禁（v3.8）：4 角色 + 公开站 + 后台 + v3 新交付路由 + 属性值 + 数据不变量。

本版新增（t22 2026-09-12 / **t26 同日追加 4-6 项**）
--------------------------------------------------
1. **补齐 v3 新交付路由**（此前是盲区：/downloads 上的 `OpenEducat Bot` 泄漏本门禁没报到）：
   /downloads、/downloads/mine、/downloads/manage、/downloads/stats、/my/apps、/my/study、
   /login、/register、/apps、/my/courses、/my/calendar 等，见下方 *_ROUTES / ROLES 表。
2. **动态发现 ID/token 类路由**：/my/study/<id>、/my/study/session/<id>/join、
   /my/courses/lesson/<id>、/my/calendar/ics/<token>、/downloads/(need-ack|unacked)/<id>
   无法静态列举，改为从已扫页面里按 FOLLOW_RE 抽取后一并扫描（**每个角色最多 FOLLOW_MAX=5 条**）。
   .ics 订阅流不是 HTML，单独走纯文本品牌扫描（brand-text-feed）。
3. **自证有效性 `--selftest`**：用真实泄漏样本（/downloads 的 OpenEducat Bot 单元格）
   + 构造样本断言"能报出来"，并用干净样本断言"不误报"；同时断言 v3 必需路由确已在清单里。
   没有这一步，"补了清单"只是形式。
4. **属性值提取（t26）**：TEXT_RE 只取标签**之间**的文本节点 —— Odoo core 门户按钮的
   `<a title="转到您的Odoo应用程序" class="o_frontend_to_backend_apps_btn">` 只在属性里，
   旧口径永远看不到。现按 ATTR_RE 追加扫描 title / placeholder / aria-label / alt / content，
   并把该真实样例写进 SELFTEST_CASES（离线硬编码，不抓线上）。
5. **数据不变量（t26）**：技术账号（uid=1 或 TECH_LOGINS）显示名含 openeducat/odoo/bot 即 FAIL。
   治的是"页面级扫描天生抽样、修好一页不等于根因干净"。**有意只查技术账号** ——
   学员/机构名里含 odoo/bot 会误报，而误报会训练大家忽略门禁；selftest 有反向样本断言。
6. **FOLLOW_RE 补 t8 两条路由**（/downloads/need-ack/<id>、/downloads/unacked/<id>），
   并在注释里写明**有意不跟进** POST-only 的 ack/remind save 路由与 /downloads/file/<id> 文件流。
7. **邮件面（t31 F3）**：邮件是学生/教师/家长的**必达通道**，页面级扫描看不到它
   （t10 评审的 F1/F2 两处 high 泄漏在本门禁下恒为 0 命中）。新增 `--mail` 模式：
   在 odoo shell 内 `ir.qweb._render` 渲染 mail_notification_layout / light、
   auth_signup.reset_password_email、digest.digest_mail_main 四支模板并断言不含 odoo/odoo.com；
   **渲染失败的模板显式列入「未覆盖」清单并计入失败**（"验不了"≠"干净"），不静默跳过。
   结果并入默认运行的退出码。
8. **/reset_password 纳入清单（t31 F4）**：该友好别名 302 到上游 /web/reset_password，
   地址栏 /web/ 前缀属**已记录取舍**（不动认证链路）→ 路由进清单但**显式豁免 /web 导航规则**，
   其余维度照常扫；`--list-routes` 现在同时打印动态发现模式数（N 类）与邮件面模板清单，
   完整运行末尾另报「本次实际跟随 M 条」，让覆盖边界自解释。

9. **修好认证 + 让退出码恢复意义（t79，2026-09-28）** —— 本门禁曾**长期静默失效**：
   `BACKEND` 写死 `admin/admin`，而本库 admin 口令是 `demo123` ⇒ 实测
   `/web/session/authenticate(admin/admin)` 返回 HTTP 200 + **Access Denied**（uid=None），
   脚本在**第 5 个（后台）面**上直接 `return 2` 退出。为什么这比"红"更糟：
   ① 它退在**汇总之前** —— 数据不变量面、邮件面、边界计数、退出码判定一次都没跑过；
   ② `2` 的语义是"环境不可用（没扫过）"，调用方读作"这次没看成"，
      于是前四个面**已经扫出来的命中**（真实案例：`/alumni` 的
      `/web/login?redirect=%2Falumni`）永远变不成 `FAIL` ——
      门禁打印了 HIT，结论却永远是"环境问题"。
   处置（三条，缺一即可复发）：
   · 口令只在一处声明 `CRED_DEFAULTS`，可被 `TRACE_<KEY>_LOGIN/PASSWORD` 覆盖，
     并把已知失效组合登记进 `KNOWN_DEAD_CREDENTIALS`，由 selftest 断言**不得回退**；
   · 登录失败**登记为未验证面**（`AUTH_UNVERIFIED`）后**继续扫其余面**；
     未验证面按 t55 口径默认判失败（严格 1 / `--lenient` 3）——**绝不产生 PASS**；
   · 只有"一个面都没登上"（站点/凭据整体不可用）才走 ENV 退出码 2。
   同族补两个洞（都属"结论不可信"，不是"看起来不严"）：
   · **5xx 路由**此前被当普通正文扫描 —— 500 错误页里本来就没有品牌字样 ⇒ **假 PASS**；
     现按未验证面登记（正文不是目标页，`classify_status()` 纯函数 + selftest 断言）。
   · `main()` 里 `PASS：…` 那行写在 `return code` **之后**（死代码）⇒ 退出码 0 时
     **一句话都不打印**，绿没有任何自述。现抽出纯函数 `verdict_line()`：
     四个退出码各有自己的结论行，并由 selftest 断言（结论行缺失，人眼在满屏 OK 里看不出来）。
   自证钩子 `TRACE_EXTRA_ROUTES`（与 `TRACE_FORCE_*` 同族）：给公开站注入额外路由，
   用于**就地证明"红是可达的"**（红线要求的正反双向自证），默认不启用。

自证行（t58/t68）：`REVISION · 指纹（运行时算的脚本 md5 前 8 位）· 断言条数 · 运行时刻`
------------------------------------------------------------------
· **指纹**证明「跑的是哪一版脚本」（内容变则变，无需人工维护）；
· **运行时刻**是**协作用途**（配合窗口公告判断某份读数是否落在测试窗口内），
  **不是防篡改证据** —— 保存的输出仍可被手工编辑；两者互补，别混用：**指纹不证明运行时刻**。
· 断言条数只作**漂移自检**（与 EXPECTED_ASSERTIONS 比对）；**新增断言必须同改动同步该常量**，
  否则门禁会红在"常量忘了 +1"而不是真问题。

ENV 通道（t73）：**环境不可用必须能与「检查通过」区分**
------------------------------------------------------------------
· `requests` 类异常（超时/断连）= **环境问题**：登记为 ENV 面、**不带 traceback**、退出码 **2**；
· **非 requests 异常 = bug**：照旧抛出（保持响亮，不伪装成"环境问题"）；
· 「容器本次运行期间重启过」会打印 **WARN** 并登记为未验证面（读数可能跨越重启而失真）；
· 退出码优先级：**命中 1 > 环境 2 > 未验证面（strict 1 / lenient 3）> OK 0**。
  为什么 ENV 单列：调用方（CI / safe_upgrade）要能区分"发现了问题"与"这次没看成" ——
  **缺了"未知"这一档，红与绿都会被误读**。构造实测：`TRACE_FORCE_HTTP_ENV_FAIL=1`。

退出码契约（t55，与 scripts/check_view_xpath.py 统一）
------------------------------------------------------------------
0 = OK         所有面都**已验证**且 0 命中
1 = FAIL       有命中；或（**默认 strict**）存在未验证面
2 = ENV        站点/环境根本不可用（没扫过）
3 = INCOMPLETE `--lenient` 下的未验证面：不是失败，但**也绝不是通过**
「未验证面」（例：`odoo shell` 起不来 → 邮件面没扫）**默认判失败**，汇总行写
**INCOMPLETE** 并逐条列出原因 —— 因为注册表 P0 期间曾出现"邮件面整段未扫却报 PASS"
（study-eng 发现、队长采纳为 t55）。构造实测：`TRACE_FORCE_MAIL_UNAVAILABLE=1`。

覆盖声明（可审计，t41 补 —— 覆盖率必须是**显式声明**而不是隐含假设）
------------------------------------------------------------------
本门禁覆盖的面：
1) **页面面**：52 条静态路由（公开站 24 + 学生 10 + 教师 5 + 家长 3 + 教务 8 + 后台 1）
   + 动态发现 5 类（每角色最多 FOLLOW_MAX 条）。
2) **文本 + 属性值**：标签之间的文本节点，以及
   **title / placeholder / aria-label / alt / content** 的属性值。
   ⚠ **新增可见属性必须在此登记并同步加入 ATTR_RE**，否则会出现
   「check_odoo_trace 与 check_english 同时漏」——互补 ≠ 并集完备。
3) **邮件面**：4 支模板**按各自忠实上下文渲染**断言（见 MAIL_PROBE_TEMPLATE；
   「探针上下文必须与真实发送路径一致，否则是假绿」）+ **可达数据面**：
   mail.template.subject / body_html、digest.digest.name（逐安装语言）。
4) **数据不变量**：uid=1 与技术账号集合（TECH_LOGINS，对齐 contacts.py:27）的显示名。

**明确不覆盖（有意，属已记录取舍，不要当成漏扫）**：
- <script>/<style> 内的 JS 运行时标识（var odoo / __session_info__ / 资产 URL）；
- `/odoo/action-…` 等功能性后台 URL 与 /web、/odoo 核心命名空间路径
  （改它要动核心 URL 生成；已记录取舍，见 §7 与 t29 记录）；
- Odoo core **父视图 arch** 里的品牌词（例如 digest.digest_section_mobile）——
  我们靠继承在渲染期抹掉、不改 core；判据是**可达性**（渲染结果），不是 arch 文本；
- **技术属性**不扫：class / style / id / data-*（它们是实现细节，不是用户可见文案；
  但 data-tooltip / aria-description 这类**可能承载可见文案**的属性一旦启用，必须登记进 ATTR_RE）；
- **跨模块继承的父模板**（Odoo core 视图，如 digest.digest_section_mobile）不在扫描面内；
- 任何**不被模板或发送路径触达**的数据（例：digest.tip 已由 t49 在数据层清空）；
- **动态构造出来的标识符 / 属性访问**（例：JS 里 `el['title']`、`data-` 前缀拼接、
  `setAttribute('aria-' + x, ...)`）—— 本门禁扫的是**静态 HTML 文本**，
  这类"运行时才拼出来"的可见文案**不被覆盖**；
  本条**不是"等它出事再修"**（对后果不可逆的项，事件型唤醒等于不做），而是点名在此：
  **它是已知的覆盖缺口，读者不得把"没报"当成"没有"**。
  （判据现状**是劈开的**，两条边界样本已写进 selftest：`data-tooltip` 不在 ATTR_RE 清单 → **不扫**；
  `data-title` 因含子串 `title=` → **会被扫到**（机会型覆盖）。前者是缺口，后者是意外收获，
  两条都记录下来，免得后人以为"data-* 一律不扫"。）

口径（与 docs/research/odoo19-debranding-i18n.md §6.1 一致，未变）
----------------------------------------------------------------
1) 先剔除 <script>/<style> 块再扫：`var odoo = {...}`、`odoo.__session_info__`、
   资产 URL 属 **JS 运行时标识**，不是用户可见文案，**有意不计入命中**。
2) 命中规则（任一即命中）：
   - 可见文本（>...<）出现 odoo（忽略大小写）或 "Powered by" 或 openeducat
     **以及属性值**（title / placeholder / aria-label / alt / content，t26 追加）
   - HTML 里出现 odoo.com / apps.odoo.com / services.odoo.com 外链
   - <meta name="generator" content="Odoo">
   - noreply@odoo.com
   - 公开站 / 门户页面上对外可见的 /web 导航链接（严格口径）
     放行两类：① 功能性资源：/web/assets、/web/image、/web/static、/web/content、
     /web/binary、/web/webmanifest；② 一个功能性入口：站内搜索 action="/website/search"。
     其余任何 /web/xxx、/web#action=、/web#menu_id=，**以及精确的 "/web"**，一律计为残留
     （2026-10-13 起：门户侧栏的「管理后台」入口已删除，裸 /web 由服务端 303 到 /apps）。
3) 后台（/web、/odoo）页面只扫可见文本与外链，不扫 /web 导航链接。

用法
----
    python3 scripts/check_odoo_trace.py                # 完整扫描（公开站 + 4 角色 + 后台）
    python3 scripts/check_odoo_trace.py --selftest     # 只跑自证有效性（离线，不访问站点）
    python3 scripts/check_odoo_trace.py --list-routes  # 只打印路由覆盖

凭据（t79）：`TRACE_<KEY>_LOGIN` / `TRACE_<KEY>_PASSWORD`（KEY ∈ STU/FAC/PAR/BO/ADMIN）
可覆盖 `CRED_DEFAULTS` 的本地演示账号；口令只在这一处声明，且**不出现在任何输出里**。

退出码（t79 补全）：0 = 全部面都已验证且零命中；1 = 有命中，或（默认 strict）有未验证面；
2 = 环境不可用（站点连不上，或**所有**登录面都登不上 ⇒ 本轮无结论）；
3 = `--lenient` 下的未验证面；selftest 失败同样返回 1。
"""
import datetime
import hashlib
import os
import re
import subprocess
import sys

import requests

ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
FLAGS = {a for a in sys.argv[1:] if a.startswith('--')}
BASE = ARGS[0] if ARGS else 'http://localhost:8069'
DB = 'edu19'

# ---- 公开站（匿名）----
PUBLIC_ROUTES = [
    '/', '/about', '/programs', '/admissions', '/journal', '/contactus',
    '/help', '/help/student', '/help/faculty', '/help/parent', '/help/registrar',
    '/login', '/register',                      # v3 友好别名（t4）
    '/courses', '/courses-offered', '/program-offered',
    '/digital-library', '/online-exams', '/booking', '/alumni',
    '/alumni/jobs', '/campus/jobs', '/apply',
    # t31 F4：/reset_password 纳入扫描（此前是覆盖盲区）。
    # 该路由是「302 → 上游 /web/reset_password」的友好别名：地址栏最终停在 /web/ 前缀属
    # **已记录的取舍**（上游路由硬编码在 /web/*，不改核心命名空间是队长裁决；
    # 动认证链路的风险大于装饰性收益）。因此对它**显式豁免 /web 导航链接规则**，
    # 其余维度（odoo 字样 / 外链 / meta generator / 属性值）照常扫。
    '/reset_password',
]
# 逐路由豁免：这些页面允许出现 /web 前缀（见上方 /reset_password 的说明）
WEB_LINK_EXEMPT = {'/reset_password'}
# ---- 凭据（t79：本门禁长期静默失效的根因就在这几行）----
# 环境事实（2026-09-28 复核；与 tests/smoke/ux_v3_route_matrix.py:41-49 同一份取证）：
#   本库 **admin 的口令是 demo123，不是 admin**。旧值 ('admin','admin') 实测
#   POST /web/session/authenticate → HTTP 200 但 "Access Denied"（uid=None）
#   ⇒ login() 返回 False ⇒ main() 在后台面上 return 2 退出，汇总一行都没打印。
# 由此定下三条纪律（缺一即复发）：
#   ① 口令**只在一处声明**，且可被环境变量覆盖 —— 不在断言路径里写死某个环境的口令；
#   ② 登录失败 = **未验证面**（AUTH_UNVERIFIED），继续扫其余面；未验证面默认判失败；
#   ③ 只有"一个面都没登上"才走 ENV(2)。
CRED_DEFAULTS = {
    'STU':   ('stu@local', 'demo123'),
    'FAC':   ('faculty@local', 'demo123'),
    'PAR':   ('parent@local', 'demo123'),
    'BO':    ('backoffice@local', 'demo123'),
    # 后台（webclient）面：本地库管理员口令见上（生产用 TRACE_ADMIN_PASSWORD 覆盖）
    'ADMIN': ('admin', 'demo123'),
}
# 已知失效的凭据组合：实测无效，出现即配置错误（selftest 断言默认值**不得**落在这里）
KNOWN_DEAD_CREDENTIALS = {('admin', 'admin')}


def credential(key):
    """(login, password)：环境变量 TRACE_<KEY>_LOGIN / TRACE_<KEY>_PASSWORD 优先。

    口令只在进程内使用，**不打印、不入日志**（打印只出现 login）。
    """
    login_d, pw_d = CRED_DEFAULTS[key]
    return (os.environ.get('TRACE_%s_LOGIN' % key, login_d),
            os.environ.get('TRACE_%s_PASSWORD' % key, pw_d))


# ---- 登录态四角色（第二项是 CRED_DEFAULTS 的键，不再是写死的口令）----
ROLES = [
    ('学生', 'STU',
     ['/my/home', '/student/profile', '/student/attendance', '/my/time_off',
      '/my/apps', '/my/study',                    # v3 t6
      '/downloads', '/downloads/mine',            # v3 t8（此前漏扫，品牌泄漏盲区）
      '/my/courses', '/my/calendar']),
    ('教师', 'FAC',
     ['/my/home', '/assignment/manage', '/my/calendar', '/my/apps', '/my/study']),
    ('家长', 'PAR',
     ['/my/home', '/my/child', '/my/apps']),
    ('教务', 'BO',
     ['/my/home', '/apps', '/ledger', '/edu/audit', '/my/apps', '/my/study',
      '/downloads', '/downloads/manage', '/downloads/stats']),
]
# ---- 后台（webclient）表面：只扫文本与外链 ----
# 2026-10-13：目标从裸 '/web' 换成 '/odoo/settings'。裸 /web、/odoo 现在由
# edu_portal 服务端 303 到 /apps（见 custom_addons/edu_portal/controllers/main.py
# 的 EduHomeRedirect.web_client），而门禁**不跟随 3xx**（classify_status ⇒ 'redir'
# ⇒ 不计命中、也不算已验证）——留着一个 303 的目标等于把后台面静默缩成空扫
# （假 PASS 家族）。/odoo/settings 是本库实测 200 的后台页，扫到的外壳与裸入口同一份。
BACKEND = [('管理员后台', 'ADMIN', ['/odoo/settings'])]
# 自证钩子（t79）：把额外路由追加进公开站面（逗号分隔），用于证明"红是可达的"。
# 默认空 ⇒ 不改变任何覆盖面；启用时输出里会显式点名"这不是声明覆盖面"。
# ⚠ 选目标时注意：门禁**不跟随 3xx**（fetch 直接中止），所以注入 3xx 路由不会变红 ——
#   实测排除过的死路：'/web'、'/web?db=edu19'、'/my' 都是 303（即使 303 的 body 里
#   确实有 /web 链接），`TRACE_EXTRA_ROUTES=/web` 实测 exit **0** ——
#   看着像"门禁抓不到"，其实是被跳转挡住，别据此判定门禁失效。
#   可用的红样本（本库实测，均 HTTP 200）：
#     TRACE_EXTRA_ROUTES='/web/reset_password'                        → 1 处（web-nav-link）
#     TRACE_EXTRA_ROUTES='/web/reset_password,/web/database/selector' → 11 处
#   （'/'、'/login'、'/alumni' 等公开页是**干净**的，注入它们仍 exit 0 ——
#     那是回归对照，不是红样本。）
EXTRA_ROUTES = [x.strip() for x in os.environ.get('TRACE_EXTRA_ROUTES', '').split(',')
                if x.strip()]

ASSET_PREFIXES = ('/web/assets', '/web/image', '/web/static', '/web/content',
                  '/web/binary', '/web/webmanifest')
# 功能性放行（口径 5 第②条）：站内搜索端点。
# 2026-10-13 起不再放行 '/web'：那个「中性中文管理后台入口」已删除（见文件头口径），
# 精确 /web 链接现在和 /web/xxx 一样计残留 —— 这个补丁正是要它别再出现。
NAV_ALLOW = ('/website/search',)
SCRIPT_RE = re.compile(r'<script[\s\S]*?</script>', re.I)
STYLE_RE = re.compile(r'<style[\s\S]*?</style>', re.I)
TEXT_RE = re.compile(r'>([^<>]{2,200})<')
GEN_RE = re.compile(r'<meta[^>]+name="generator"[^>]+content="Odoo"', re.I)
ODOO_WORD_RE = re.compile(r'odoo', re.I)
POWERED_RE = re.compile(r'Powered by', re.I)
OPENEDUCAT_RE = re.compile(r'openeducat', re.I)
EXT_URL_RE = re.compile(r'(?:href|action|src)="([^"]*(?:odoo\.com|odoo\.online|'
                        r'odoo\.com/apps)[^"]*)"', re.I)
# 只匹配 /web 本身与 /web/<路径>（含 /web#…、/web?…）；
# /website/… 是前台路由（站内搜索/表单），不属于后台路径，故不匹配。
HREF_RE = re.compile(r'(?:href|action)="(/web(?:[/#?][^"]*)?)"', re.I)
# 属性值提取（t26）：TEXT_RE 只取标签**之间**的文本节点，属性里的痕迹永远看不到。
# 真实案例：Odoo core 在门户页渲染的
#   <a title="转到您的Odoo应用程序" class="o_frontend_to_backend_apps_btn">
# 只在 title 属性里 —— 所以在 ODOO_WORD_RE 之前补一层属性扫描
# （check_english 一直是扫属性的，这不是"做不到"，是本门禁少了一层）。
ATTR_RE = re.compile(
    r'(?:title|placeholder|aria-label|alt|content)\s*=\s*"([^"]{2,300})"', re.I)
# 数据不变量（t26）：**只**查 uid=1 与技术 login 集合的显示名。
# 有意**不**遍历全部 res.partner.name —— 将来学员/机构名里含 odoo/bot（教会名、昵称）
# 会误报，而门禁误报会训练大家忽略门禁（队长采纳 verifier 的设计约束，2026-09-12）。
# 技术账号集合：**以仓内权威集合 contacts.py:27 为准**（t41 对齐）。
# 同步约束：改动这里必须同步 custom_addons/edu_portal/controllers/contacts.py 的
# _TECH_LOGINS，反之亦然 —— 门禁与应用侧用两套集合迟早会出现
# 「应用侧认为是技术账号、门禁不认」的互相矛盾结论。
# 其中 __oe__ / OdooBot 在本地库并不存在，属**防御性登记**（标准 Odoo 库里会有），
# 故意保留：换了部署环境不会因此漏判。
TECH_LOGINS = ('__system__', '__oe__', 'OdooBot', 'public')
# SQL/比较一律用**小写**集合：OdooBot 是混合大小写，而 SQL 侧用 lower(login) 比较，
# 不统一会让「OdooBot 该命中却不命中」（selftest 一把就抓到了这一点）。
TECH_LOGINS_LC = tuple(l.lower() for l in TECH_LOGINS)
BRAND_TOKEN_RE = re.compile(r'openeducat|odoo|\bbot\b', re.I)
# 动态发现：ID/token 类路由（无法静态列举）
FOLLOW_RE = re.compile(
    r'href="(/(?:my/study/\d+|my/study/session/\d+/join|'
    r'my/courses/lesson/\d+|my/calendar/ics/[^"?#]+|'
    r'downloads/(?:need-ack|unacked)/\d+))"')
# 有意不跟进的三类（免得后人以为漏了）：
#   /downloads/ack/<fid>/save、/downloads/remind/<fid>/save —— POST-only 兄弟路由，
#   门禁只跟 href，天然不会踩；/downloads/file/<fid> —— 二进制文件流，扫它无意义。
FOLLOW_MAX = 5                      # 每个角色最多跟进几条（与文件头说明一致），避免扫描爆炸
# 动态发现覆盖的 5 类（打印用；与 FOLLOW_RE 一一对应，改正则必须同步这里）
FOLLOW_KINDS = ('/my/study/<id>', '/my/study/session/<id>/join',
                '/my/courses/lesson/<id>', '/my/calendar/ics/<token>',
                '/downloads/(need-ack|unacked)/<id>')
NONHTML_BRAND_RE = re.compile(r'odoo|openeducat|powered by', re.I)


def prime(session):
    """多库开发环境：先带 ?db= 访问一次 /web/login，让会话记住库名。
    否则后续请求落进 nodb 路由表 → 全部 404（2026-09-12 实测，生产单库无此问题）。"""
    try:
        session.get(BASE + '/web/login?db=' + DB, timeout=20,
                    allow_redirects=True)
    except Exception as exc:
        # t79：**不许 `except: pass`** —— 这一步失败意味着后面每条匿名请求都可能落进
        # nodb 路由表拿到 404，读数是"没扫到"而不是"干净"（假绿家族）。
        # 按 fetch 同款口径分类：requests 类异常 → ENV 面（退出码 2）；
        # 非 requests 异常照旧抛出（那是 bug，不伪装成环境问题）。
        kind, why = classify_fetch_exception(exc)
        if kind == 'ENV':
            _mark_http_env('选库探活 %s：%s' % (DB, why))
            print('  [ENV] 选库探活失败（匿名面读数可能失真）：%s' % why)
            return
        raise


def login(session, login_name, password):
    try:
        resp = session.post(BASE + '/web/session/authenticate', json={
            'jsonrpc': '2.0',
            'params': {'db': DB, 'login': login_name, 'password': password},
        }, timeout=20)
    except Exception as exc:                     # t73：登录请求也会超时/断连，别让它带 traceback 崩掉
        kind, why = classify_fetch_exception(exc)
        if kind == 'ENV':
            _mark_http_env('登录 %s：%s' % (login_name, why))
            print('  [ENV] 登录请求失败（环境不可用）：%s' % why)
            return False
        raise
    try:
        return resp.status_code == 200 and bool(resp.json().get('result'))
    except Exception:
        return False


def login_or_note(title, key, session, n_routes):
    """登录成功返回 True；失败**登记未验证面**并返回 False（t79）。

    旧实现在这里 `return 2` —— 那句话把"后台面没看成"升级成"整份门禁没结论"：
    汇总不打印、退出码是 ENV(2)，调用方读作"这次没看成"，
    于是前面四个面已经扫出来的命中**永远变不成 FAIL**（本门禁静默失效的成因）。
    现在：继续扫其余面 + 该面登记未验证面（默认判失败），既不静默也不吞掉已有命中。
    """
    login_name, password = credential(key)      # 口令只进函数调用，不进任何输出
    if login(session, login_name, password):
        return True
    why = ('%s 面：登录失败（login=%s）—— 该面 %d 条路由本轮**未验证**；'
           '口令可用 TRACE_%s_PASSWORD 覆盖' % (title, login_name, n_routes, key))
    if why not in AUTH_UNVERIFIED:
        AUTH_UNVERIFIED.append(why)
    print('  %-22s 登录失败：%s（登记为未验证面：不产生 PASS，也不吞掉已扫面的命中）'
          % (title, login_name))
    return False


def _mark_http_env(why):
    if why not in HTTP_UNVERIFIED:
        HTTP_UNVERIFIED.append(why)


def scan(body, check_web_links, nonhtml=False):
    """返回命中列表（(规则, 片段)）。nonhtml=True 时按纯文本流（如 .ics）扫品牌字样。"""
    hits = []
    if nonhtml:
        for m in NONHTML_BRAND_RE.finditer(body or ''):
            hits.append(('brand-text-feed', (body[max(0, m.start() - 30):m.start() + 40]
                                             .replace('\n', ' ').strip())[:90]))
        return hits
    if GEN_RE.search(body):
        hits.append(('meta-generator', 'meta name=generator content=Odoo'))
    for url in EXT_URL_RE.findall(body):
        hits.append(('odoo-external-url', url[:90]))
    visible = SCRIPT_RE.sub(' ', STYLE_RE.sub(' ', body))
    for text in TEXT_RE.findall(visible):
        if ODOO_WORD_RE.search(text):
            hits.append(('visible-odoo-text', text.strip()[:90]))
        elif POWERED_RE.search(text):
            hits.append(('visible-powered-by', text.strip()[:90]))
        elif OPENEDUCAT_RE.search(text):
            hits.append(('visible-openeducat', text.strip()[:90]))
    for value in ATTR_RE.findall(visible):
        snippet = value.strip()
        if snippet == 'Odoo' and GEN_RE.search(body):
            continue                     # meta generator 已由 GEN_RE 计过一次，不重复
        if ODOO_WORD_RE.search(snippet):
            hits.append(('attr-odoo-value', snippet[:90]))
        elif POWERED_RE.search(snippet):
            hits.append(('attr-powered-by', snippet[:90]))
        elif OPENEDUCAT_RE.search(snippet):
            hits.append(('attr-openeducat', snippet[:90]))
    for raw in re.findall(r'noreply@odoo\.com', body, re.I):
        hits.append(('noreply-sender', raw))
    if check_web_links:
        for link in HREF_RE.findall(body):
            if link.startswith(ASSET_PREFIXES) or link in NAV_ALLOW:
                continue
            hits.append(('web-nav-link', link[:90]))
    return hits


def classify_status(code):
    """HTTP 状态分类（纯函数，selftest 可断言 t79）。

    · `ok`         2xx/4xx：拿到正文，照常扫（4xx 错误页也是**真实可达**的页面，
                    其品牌痕迹照算命中；不因"页面不存在"就免检）。
    · `redir`      3xx：门禁不跟随跳转（目标另有路由覆盖），不计命中、也不算已验证。
    · `unverified` 5xx：正文是错误页，**不是**被探目标页 ⇒ 登记未验证面。
                    旧实现把 500 当普通正文扫 —— 错误页里本来就没有品牌字样，
                    于是"站点半死"会被读成 0 命中（假 PASS 家族）。
    """
    if 300 <= code < 400:
        return 'redir'
    if code >= 500:
        return 'unverified'
    return 'ok'


def fetch(session, path):
    if os.environ.get('TRACE_FORCE_HTTP_ENV_FAIL'):
        # 验收用构造钩子（t73）：把"fetch 类环境故障"变成**可复现实测**（真实故障难以按需制造）
        _mark_http_env('%s ConnectionError: TRACE_FORCE_HTTP_ENV_FAIL=1（构造）' % path)
        return None, 'ENV ConnectionError（构造：TRACE_FORCE_HTTP_ENV_FAIL=1）'
    try:
        resp = session.get(BASE + path, timeout=30, allow_redirects=False)
    except Exception as exc:                     # 网络异常也要报出来
        kind, why = classify_fetch_exception(exc)
        if kind == 'ENV':
            _mark_http_env('%s %s' % (path, why))
            return None, 'ENV %s' % why
        raise                                    # 非 requests 异常 = bug：保持响亮，不伪装成环境问题
    status = classify_status(resp.status_code)
    if status == 'redir':
        return None, 'REDIR %s -> %s' % (resp.status_code,
                                         str(resp.headers.get('Location'))[:60])
    if status == 'unverified':
        note = '%s HTTP %d（5xx 正文不是目标页）' % (path, resp.status_code)
        if note not in ROUTE_UNVERIFIED:
            ROUTE_UNVERIFIED.append(note)
        return None, 'UNVERIFIED HTTP %d（正文不是目标页 ⇒ 登记未验证面，不产生 PASS）' % (
            resp.status_code)
    return resp, None


def _scan_one(title, session, path, check_web_links, total, nonhtml=False):
    resp, note = fetch(session, path)
    if resp is None:
        print('  %-22s %-40s %s' % (title, path, note))
        return
    hits = scan(resp.text, check_web_links, nonhtml=nonhtml)
    if hits:
        print('  %-22s %-40s %s HIT x%d' % (title, path, resp.status_code, len(hits)))
        for rule, snippet in hits[:6]:
            print('        - %-18s %s' % (rule, snippet))
        total[0] += len(hits)
    else:
        print('  %-22s %-40s %s OK' % (title, path, resp.status_code))


def run_surface(title, session, routes, check_web_links, total, seen=None):
    seen = seen if seen is not None else set()
    followed = 0
    for path in routes:
        resp, note = fetch(session, path)
        if resp is None:
            print('  %-22s %-40s %s' % (title, path, note))
            continue
        route_web_links = check_web_links and path not in WEB_LINK_EXEMPT
        if check_web_links and path in WEB_LINK_EXEMPT:
            print('  %-22s %-40s （/web 前缀按已记录取舍豁免）' % (title, path))
        hits = scan(resp.text, route_web_links)
        if hits:
            print('  %-22s %-40s %s HIT x%d' % (title, path, resp.status_code,
                                                len(hits)))
            for rule, snippet in hits[:6]:
                print('        - %-18s %s' % (rule, snippet))
            total[0] += len(hits)
        else:
            print('  %-22s %-40s %s OK' % (title, path, resp.status_code))
        # 动态发现 ID/token 类路由（每角色最多 FOLLOW_MAX 条）
        if followed < FOLLOW_MAX:
            for extra in FOLLOW_RE.findall(resp.text):
                if followed >= FOLLOW_MAX:
                    break
                if extra in seen:          # 去重：同一 ID/token 路由只扫一次
                    continue
                seen.add(extra)
                followed += 1
                is_ics = '/ics/' in extra
                print('  %-22s %-40s （动态发现）' % (title, extra))
                _scan_one(title, session, extra, check_web_links, total,
                          nonhtml=is_ics)
    return total


# ---- 邮件面（t31 F3）：邮件是必达通道，页面级扫描看不到它 ----
MAIL_TEMPLATES = ['mail.mail_notification_layout', 'mail.mail_notification_light',
                  'auth_signup.reset_password_email', 'digest.digest_mail_main',
                  # t52：按**可达性**扩到「我们真会发」的认证类邮件（2026-09-12 数据面扫描
                  # 发现 mail.template 44/47 条含品牌 token，其中这 5 条属真实发送路径）。
                  # 只在白名单里加**真会发**的；其余未启用应用的模板留在「待修面」输出中显式呈现。
                  'auth_signup.set_password_email',
                  'auth_signup.portal_set_password_email',
                  'auth_signup.mail_template_user_signup_account_created',
                  'auth_totp_mail.mail_template_totp_invite']
# 与探针里的 QWEB_TEMPLATES **必须一致**（探针在外层命名空间之外执行，只能各自定义）
QWEB_MAIL_TEMPLATES = ('mail.mail_notification_layout', 'mail.mail_notification_light',
                       'auth_signup.reset_password_email', 'digest.digest_mail_main')
# ---- 自证行（t58，study-eng/flow-eng 同款）：指纹**运行时算**，不写死常量 ----
REVISION = 'v3.8'
# v3.8（t79）：认证修好（admin/admin 在本库失效 ⇒ 每次都 return 2 退出，汇总一行都没跑）；
#   登录失败改为"未验证面 + 继续扫其余面"；5xx 路由登记未验证面；抽 verdict_line() 补回
#   被写在 return 之后的 PASS 结论行；新增 TRACE_EXTRA_ROUTES 自证钩子。
#   同族再补两处"静默": prime() 的 except: pass（选库失败 ⇒ 后面全是 404 ⇒ 假绿）、
#   邮件探针 len=0 被算作"渲染成功"（三语全失败照样上报 OK）。断言 40 → 53。
# v3.7（t12）：初始探活从裸 requests.get() 改为 trust_env=False 的 session —— 原写法会读
#   本机系统代理：代理连不上时抛 ProxyError ⇒ 站点健康也报「环境不可用」exit 2（假红）；
#   代理能连时拿回 502 **响应**（不抛异常）⇒ 探活形同虚设。断言条数不变（仍未 40）。
EXPECTED_ASSERTIONS = 53      # 声明值；与运行时实际执行数比对，漂移即 FAIL
# 组成：16 扫描样本（t79 +1 友好别名干净样本）+ 4 退出码契约 + 7 数据不变量
#       + 1 规则族覆盖 + 3 自证行(t68) + 3 fetch 异常分类 + 2 ENV 退出码（t73）
#       + 1 结论行（t79）+ 4 HTTP 状态分类（t79）+ 3 凭据（t79）
#       + 4 邮件探针行解析（t79：len=0 不得算"渲染成功"）
# ⚠ 实现注意（t68，i18n-eng 读码核出）：**任何新增断言都必须同一改动内同步本常量**，
#   否则门禁会红在"常量忘了 +1"，而不是红在真问题 —— 这是最不值的一种红。
#   为自证行加字段（运行时刻）属 **print-only**，不新增断言，故与上面这条无关 ✓。
# 运行时刻：**只算一次**（单一来源，与 MAIL_SUMMARY 同规矩：同一份输出只允许一处口径）。
# 作用范围：**协作用途**（拿它对窗口公告），**不是防篡改证据**（保存的输出仍可手改）；
#   指纹只证明**脚本版本**、不证明**运行时刻** —— 两者互补，别混用。
RUN_STAMP = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
# ---- ENV 通道（t73）：环境不可用必须可与"检查通过"区分（CI 的红/绿/未知三分）----
# 规则：**requests 类异常 = 环境问题（ENV，退出码 2，不带 traceback）**；
#      其它异常仍照旧抛出（那是 bug，必须响，不能被伪装成"环境问题"）。
HTTP_UNVERIFIED = []          # 本次因网络/超时而未验证的路由（去重）
AUTH_UNVERIFIED = []          # 本次因登录失败而未验证的表面（t79：不再"return 2 一了百了"）
ROUTE_UNVERIFIED = []         # 本次拿到 5xx 的路由（正文不是目标页 ⇒ 不得计入 PASS）
CONTAINER_RESTARTED = []      # 本次运行期间容器重启过的服务（可读信号；读数可能失真）


def classify_fetch_exception(exc):
    """fetch 类异常分类：('ENV', 说明) 或 ('BUG', 说明)。

    抽成纯函数是为了 **selftest 能用构造异常断言**（不必真去制造网络故障）。
    """
    if isinstance(exc, requests.exceptions.RequestException):
        return 'ENV', '%s: %s' % (type(exc).__name__, str(exc)[:60])
    return 'BUG', '%s: %s' % (type(exc).__name__, str(exc)[:60])


def _web_started_at():
    """web 容器的 StartedAt（用于"本次运行期间是否重启过"的可读信号）。"""
    try:
        out = subprocess.run(['docker', 'compose', 'ps', '-q', 'web'],
                             capture_output=True, text=True, errors='replace',
                             timeout=20)
        cid = (out.stdout or '').strip().splitlines()[0] if out.stdout.strip() else ''
        if not cid:
            return ''
        ins = subprocess.run(['docker', 'inspect', '-f', '{{.State.StartedAt}}', cid],
                             capture_output=True, text=True, errors='replace', timeout=20)
        return (ins.stdout or '').strip()
    except Exception:
        return ''


RUN_WEB_STARTED = None        # 在 main() 开头采样（None=未启用该信号）
# 规则族清单（t68）：扫描器会生成的规则名。**每族至少要有一个"必须命中"的离线样本** ——
#   即 study-eng 那句「你能描述一个让它变红的场景吗？」的机器化版本；
#   缺失的族 = 从没打算被判假 = 占位符 → selftest 直接 FAIL 并点名。
ALL_RULES = ('attr-odoo-value', 'attr-openeducat', 'attr-powered-by', 'brand-text-feed',
             'meta-generator', 'noreply-sender', 'odoo-external-url', 'visible-odoo-text',
             'visible-openeducat', 'visible-powered-by', 'web-nav-link')
# t74：每个 must-hit 样本还要声明**期望触发的规则名** —— 「样本红了」不等于「红的正是目标规则」：
# 目标规则若被改坏或被前置分支绕过，样本可能**由别的规则接管**照样红，断言照样通过 ✗。
# 于是断言升级为：**红了 且 红的正是预期那条**（构造反例见 selftest）。
EXPECT_RULES = {
    '真实泄漏样本：/downloads 的 OpenEducat Bot 单元格': ('visible-openeducat',),
    '构造：可见 Odoo 文本': ('visible-odoo-text', 'visible-powered-by'),
    '构造：user menu 外链': ('odoo-external-url',),
    '构造：meta generator': ('meta-generator',),
    '构造：/web 导航链接': ('web-nav-link',),
    '构造：精确 /web 入口（2026-10-13 收口后应为命中）': ('web-nav-link',),
    '构造：noreply 发件人': ('noreply-sender', 'visible-odoo-text'),
    '真实样本：Odoo core 按钮 tooltip（**只在 title 属性里**）': ('attr-odoo-value',),
    '构造：aria-label 里的品牌字样': ('attr-odoo-value',),
    '构造：属性值里的基座品牌名（OpenEduCat）': ('attr-openeducat',),
    '构造：属性值里的 Powered by（非 odoo 也要抓）': ('attr-powered-by',),
    '构造：data-title 因含 title= 子串被扫到（边界样本 ②，机会型覆盖）': ('attr-odoo-value',),
}
NONHTML_SAMPLE = '订阅流：Powered by Odoo / OpenEduCat'   # 非 HTML 通道样本
NONHTML_EXPECT = ('brand-text-feed',)
BOUNDARY_DESIGN = ('技术属性（class/style/id/data-*，不在 ATTR_RE 清单）',
                   'core 父模板 arch（靠继承在渲染期抹掉，判据是可达性）',
                   '内部核心链接（/odoo/…、/web/…，属核心命名空间取舍）')


def _fingerprint():
    """自身文件 md5 前 8 位（运行时算 —— 旧快照往返的根治，见 t58）。"""
    try:
        with open(__file__, 'rb') as fh:
            return hashlib.md5(fh.read()).hexdigest()[:8]
    except Exception:
        return '????????'


def revision_line(assertions=None):
    """自证行：脚本版本 + 内容指纹 + 断言条数 + 运行时刻。

    运行时刻是**协作用途**（配合窗口公告判断某份读数是否落在测试窗口内），
    **不是防篡改证据** —— 保存下来的输出仍可被手工编辑；防篡改靠指纹，
    而指纹只证明脚本版本、不证明运行时刻。两者互补，别混用。
    """
    return 'REVISION=%s · 指纹 %s · 断言 %s 条 · 运行 %s' % (
        REVISION, _fingerprint(), EXPECTED_ASSERTIONS if assertions is None else assertions,
        RUN_STAMP)


# ---- 数据面可达性登记（t58 / t64）：按**本部署**判定，每条给理由 + **失效条件** ----
# 判据是「**可达性**」，不是「改不动」；而且它**会漂移** —— 所以每条都写明**失效条件（重评触发）**：
# 一旦该条件成立，这条登记即失效，必须重新评估（而不是被当成永久结论）。
# 纪律（i18n-eng §5）：**登记表不是"看着没用就塞进去"的垃圾桶**，每条都要能回答三问：
#   ① 为什么现在不可达？ ② 证据是什么？ ③ 什么条件下它重新变成可达面？
# 反例（故意留在可达侧）：calendar 4 条会议模板**判可达、留在待修** —— 本部署确在用日历会议。
UNREACHABLE_MODULES = {
    'base_install_request': '模块安装请求邮件：本部署永不发送（失效条件：真用后台「应用」页走安装审批流程时重评）',
    'account': '电子发票/订阅通知：account_peppol 未装、account_move=0（i18n-eng 实测不可达）（失效条件：安装 account_peppol 或开始产生发票/订阅记录时重评）',
    'gamification': '徽章通知：本部署未使用徽章（失效条件：启用徽章/排行榜并开始发徽章通知时重评）',
    'event': '活动邀请/提醒：本部署未启用活动报名（失效条件：启用活动报名并开始发邀请时重评）',
    'website_profile': '个人资料验证邮件：本部署未启用（失效条件：启用个人资料验证流程时重评）',
}
MAIL_UNVERIFIED = []          # 本次未验证的邮件面原因（汇总里点名，不静默）
DATA_UNVERIFIED = []          # 数据不变量面未验证原因（同为"验不了"的一面）
# t55 口径：**默认 strict** —— 有未验证面即判失败（"验不了"≠"干净"）；
# `--lenient` 退出降级为 3=INCOMPLETE，供"只在环境齐备时判绿"的场合使用。
STRICT = '--lenient' not in FLAGS


def exit_code(total_hits, unverified, strict=True, env_failures=0):
    """退出码契约（t55/t73，与 check_view_xpath 统一）：0=OK 1=FAIL 2=ENV 3=INCOMPLETE。

    优先级：**命中(1) > 环境不可用(2) > 未验证面(strict→1 / lenient→3) > OK(0)**。
    环境不可用单列 2 而不是并进"未验证面"，是因为调用方（CI/safe_upgrade）要能区分
    "发现了问题"与"这次没看成" —— 缺了"未知"这一档，红绿都会被误读（队长 t73 口径）。

    抽成**纯函数**是为了能被 selftest 断言 —— 口径必须可测，否则又是一处"人读的绿"。
    """
    if total_hits:
        return 1
    if env_failures:
        return 2
    if unverified:
        return 1 if strict else 3
    return 0


def verdict_line(code, hits, n_unverified, n_env):
    """结论行（纯函数：**四个退出码各有自己的结论文本**）。

    为什么要抽成纯函数并被 selftest 断言：本门禁曾把 `PASS：…` 写在 `return code`
    **之后**（死代码）⇒ 退出码 0 时**一行都不打印**，"绿"没有任何自述；而"结论行缺失"
    这种事在满屏 OK 里人眼看不出来，机器看得出来（t79）。
    """
    if code == 0:
        return ('PASS：Odoo / 基座品牌痕迹 0 命中；公开站 %d + 4 角色 %d + 后台 %d = %d 条'
                '静态路由（另含动态发现 / 数据不变量 / 邮件面）**全部已验证**'
                % (len(PUBLIC_ROUTES), sum(len(r[2]) for r in ROLES),
                   sum(len(b[2]) for b in BACKEND), route_count()))
    if code == 1 and hits:
        return 'FAIL：Odoo / 基座品牌痕迹命中 %d 处（明细见上方 HIT 行）' % hits
    if code == 1:
        return ('INCOMPLETE：有 %d 个未验证面 —— **不得计入 PASS**（默认 strict 判失败；'
                '加 --lenient 可拿到 INCOMPLETE 专用的退出码 3）' % n_unverified)
    if code == 2:
        return ('ENV：有 %d 条路由因环境不可用（网络/超时）未验证 —— '
                '**既不是通过、也不是发现命中**，请重跑' % n_env)
    return ('INCOMPLETE：有 %d 个未验证面（--lenient：退出码 3 而非失败）' % n_unverified)


MAIL_SUMMARY = {}             # **汇总的唯一来源**：mail_check 填，所有打印处读它
                              # （同一行两套口径就是假绿家族，故只允许一处计算）
QUIET_DATA_FACE = '--quiet-data-face' in FLAGS   # 只报计数不报样本（自动化场景用）
# 数据面口径用：URL 与承载文案的属性（alt/title/content）—— 去掉它们后若仍有 token，
# 才算「可见文案」命中（t52 对账：i18n-eng 报 15 条记录 / 我先前误报 44 是把
# 「记录×字段×语言」的组合数当成了记录数，基线不可复现，故把口径写死在这里）。
_HREF_ATTR_RE = re.compile(
    r'(?:href|src|t-attf-href|t-att-href|alt|title|content)\s*=\s*"[^"]*"', re.I)
# 内部核心命名空间链接（/odoo/… 与 /web/…）：与**页面口径一致** —— 不算品牌命中
# （已记录取舍：不改 core 的 URL 生成；而 odoo.com 等**外链**仍算命中）。
# 注意要同时匹配**绝对 URL**：实测渲染出来的是 http://host:8069/odoo/action-…
_CORE_LINK_RE = re.compile(
    r'(?:href|t-attf-href|t-att-href)\s*=\s*"[^"]*?/(?:odoo|web)/[^"]*"', re.I)


def _count_brand(html):
    """(品牌文本, odoo.com, odoocdn, 内部核心链接数) —— 剥离内部核心链接后再数品牌 token。"""
    core = len(_CORE_LINK_RE.findall(html))
    stripped = _CORE_LINK_RE.sub('href="[core]"', html)
    low = stripped.lower()
    return low.count('odoo'), low.count('odoo.com'), low.count('odoocdn'), core
MAIL_PROBE_TEMPLATE = r'''import re
env = env
Qweb = env['ir.qweb'].sudo()
# 探测脚本必须**自带**依赖：它在外层模块之外执行（odoo shell 的命名空间），
# 引用外层常量会直接 NameError（实测踩过一次）。
_HREF_ATTR_RE = re.compile(
    r'(?:href|src|t-attf-href|t-att-href|alt|title|content)\s*=\s*"[^"]*"', re.I)
# 与页面口径一致：/odoo/… 与 /web/… 属内部核心命名空间 → 不算品牌命中（外链仍算）
_CORE_LINK_RE = re.compile(
    r'(?:href|t-attf-href|t-att-href)\s*=\s*"[^"]*?/(?:odoo|web)/[^"]*"', re.I)


def _count_brand(html):
    core = len(_CORE_LINK_RE.findall(html))
    stripped = _CORE_LINK_RE.sub('href="[core]"', html)
    low = stripped.lower()
    return low.count('odoo'), low.count('odoo.com'), low.count('odoocdn'), core


def _digest_values(digest):
    """照 digest/models/digest.py:_action_send_to_user 逐字段构造（2026-09-12 核对字段名）。
    探针上下文必须与真实发送路径一致，否则是假绿 —— t44 的教训：早先探针缺
    kpi_data / tips / display_mobile_banner，渲染约 3.6KB 判全绿；忠实上下文里却有
    20 处 odoo（含 www.odoo.com 图片、7 张 download.odoocdn.com 图、/odoo/action- 外链）。
    这里直接调用 digest 自己的 _compute_kpis / _compute_tips / _compute_preferences，
    不手搓数据，避免与真实发送路径再次漂移。"""
    # 关键：**用 ERP 管理员**（base.group_erp_manager）—— digest.py:352-364 的两条
    # preferences（'Prefer a broader overview?' / 'Want to customize this email?'
    # 后者带 /odoo/digest.digest/<id> 链接）**只对 erp_manager 渲染**；
    # 早先探针用普通教师用户 → preferences 为空 → 该区块整块消失，
    # 于是「探针绿、忠实渲染红」（i18n-eng t32/t45 两次打回的都是这一类）。
    erp = env.ref('base.group_erp_manager')
    user = env['res.users'].sudo().search([('group_ids', 'in', erp.id)], limit=1) or env.user
    return {
        'object': digest,
        'title': digest.name,
        'top_button_label': 'Connect',
        'top_button_url': digest.get_base_url(),
        'company': user.company_id,
        'user': user,
        'unsubscribe_token': digest._get_unsubscribe_token(user.id),
        'tips_count': 5,
        'formatted_date': '2026-09-12',
        'display_mobile_banner': True,
        'kpi_data': digest._compute_kpis(user.company_id, user),
        'tips': digest._compute_tips(user.company_id, user, tips_count=5, consumed=False),
        'preferences': digest._compute_preferences(user.company_id, user),
    }


def _values_for(name):
    """每支模板**分别**构造忠实上下文（一个字典打天下正是假绿来源）。"""
    msg = env['mail.message'].sudo().search([], limit=1)
    user = env['res.users'].sudo().search([('login', '=', 'faculty@local')], limit=1) or env.user
    common = {
        'company': env.company, 'user': user, 'message': msg, 'record': msg,
        'record_name': '记录', 'model_description': '记录',
        'show_footer': True, 'show_unfollow': False, 'signature': '',
        'email': user.email or 'probe@example.com', 'token': 'probe',
        'token_validity_hours': 24,
    }
    if name.startswith('auth_signup.'):
        # 认证类模板（reset/set/password、注册通知）都用 object 指用户/记录 + user/company/email
        return dict(common, object=user, partner=user.partner_id,
                    token='probe-token', signup_url='/web/signup')
    if name.startswith('auth_totp_mail.'):
        return dict(common, object=user, partner=user.partner_id, record=user,
                    totp_secret='PROBE', totp_url='/odoo/action-auth_totp' )
    if name == 'digest.digest_mail_main':
        return _digest_values(env['digest.digest'].sudo().search([], limit=1))
    return common



def _data_face():
    """可达数据面（t41）：只有会被渲染进「发给收件人」的邮件的字段才算。
    逐安装语言扫（译文也要扫，漏语言=漏一半）。
    命中即**打印并计数**，进入「本轮待修面」汇总；不计入本门禁四维命中。"""
    langs = env['res.lang'].sudo().search([('active', '=', True)]).mapped('code') or ['en_US']
    for model, fields in (('mail.template', ['subject', 'body_html']),
                          ('digest.digest', ['name'])):
        recs = env[model].sudo().search([])
        bad, bad_recs, bad_text_recs = [], set(), set()
        for rec in recs:
            for fname in fields:
                for lg in langs:
                    try:
                        val = rec.with_context(lang=lg)[fname]
                    except Exception:
                        continue
                    if not (isinstance(val, str) and re.search(r'odoo|openeducat', val, re.I)):
                        continue
                    m = re.search(r'.{0,40}(?:odoo|openeducat).{0,30}', val, re.I)
                    sample = re.sub(r'\s+', ' ', m.group(0)) if m else val[:60]
                    bad.append((rec.id, fname, lg, sample[:70]))
                    # 口径与邮件面**同一套**（t58）：内部核心链接（/odoo/…、/web/…）不计品牌命中。
                    core_stripped = _CORE_LINK_RE.sub('href="[core]"', val)
                    if not re.search(r'odoo|openeducat', core_stripped, re.I):
                        # t63：**内部链接型**单列计数（不直接从 headline 悄悄减掉 ——
                        # 「减掉的面也要说清是什么」，与「不计入判据的面不得当成已清」是姊妹条）
                        if model == 'mail.template':
                            ext0 = rec.get_external_id().get(rec.id, '')
                            print('DATAFACE_LINKONLY|%s|%s|%s'
                                  % (model, ext0.split('.')[0] or '-', ext0))
                        continue
                    bad_recs.add(rec.id)
                    # 再剥 URL/属性后仍有 token → 属**可见文案**；否则只是功能性链接/属性
                    stripped = _HREF_ATTR_RE.sub(' ', core_stripped)
                    vis = 1 if re.search(r'odoo|openeducat', stripped, re.I) else 0
                    if vis:
                        bad_text_recs.add(rec.id)
                    if model == 'mail.template':
                        ext = rec.get_external_id().get(rec.id, '')
                        print('DATAFACE_HIT|%s|%s|%s|%d'
                              % (model, ext.split('.')[0] or '-', ext, vis))
        # 口径写死（队长要求，避免 44 vs 15 那种不可复现的基线）：
        #   第 1 个数 = 命中**记录数**（去重）；第 2 个 = 总记录数；
        #   第 3 个 = 其中属**可见文案**的记录数（去掉 href/src/alt/title/content 后仍有 token）；
        #   第 4 个 = 匹配**组合数**（记录×字段×语言），便于与逐组合扫描对账。
        print('DATAFACE|%s|%d|%d|%d|%d' % (model, len(bad_recs), len(recs),
                                          len(bad_text_recs), len(bad)))
        for b in bad[:2]:
            print('DATAFACE_SAMPLE|%s|%s|%s|%s' % b)


_data_face()


QWEB_TEMPLATES = ('mail.mail_notification_layout', 'mail.mail_notification_light',
                 'auth_signup.reset_password_email', 'digest.digest_mail_main')


def _render_mail_template(name):
    """mail.template 是**数据记录**（不在 ir.qweb 模板表里）—— t52 实测：
    对 auth_signup.set_password_email 用 ir.qweb._render 会报「没找到模板」。
    必须走它自己的发送渲染路径 _render_field('body_html', ...)，
    并**逐语言**渲染（品牌 token 在翻译字段里，只查源语言会漏一半）。"""
    tpl = env.ref(name)
    user = env['res.users'].sudo().search([('login', '=', 'faculty@local')], limit=1) or env.user
    total_odoo = total_com = total_cdn = total_core = 0
    size = 0
    sample = ''
    for lg in ('en_US', 'zh_CN', 'zh_TW'):
        try:
            body = tpl.with_context(lang=lg)._render_field('body_html', [user.id])[user.id]
            subject = tpl.with_context(lang=lg)._render_field('subject', [user.id])[user.id]
        except Exception:
            continue
        blob = (str(subject) + ' ' + str(body))
        o, c, d, core = _count_brand(blob)
        total_odoo += o
        total_com += c
        total_cdn += d
        total_core += core
        if len(blob) > size:
            size = len(blob)
            m = re.search(r'.{0,45}(?:odoo|openeducat).{0,35}', blob, re.I)
            sample = re.sub(r'\s+', ' ', m.group(0)) if m else ''
    return size, total_odoo, total_com, total_cdn, total_core, sample


for name in MAIL_TEMPLATES:
    try:
        if name in QWEB_TEMPLATES:
            html = Qweb._render(name, _values_for(name))
            o, c, d, core = _count_brand(html)
            print('MAILPROBE|%s|OK|%d|%d|%d|%d|%d' % (name, len(html), o, c, d, core))
        else:
            size, o, c, d, core, sample = _render_mail_template(name)
            print('MAILTPL|%s|OK|%d|%d|%d|%d|%s|%d'
                  % (name, size, o, c, d, sample[:80], core))
    except Exception as exc:
        print('MAILPROBE|%s|UNCOVERED|%s' % (name, str(exc).replace(chr(10), ' ')[:120]))'''


def _mail_env_unavailable(total, why):
    """邮件面「环境不可用」的统一处理：默认**显式登记为未验证面**并在汇总里点名；
    加 --strict 时计入失败（要求"验不了就不能算绿"的场合用）。

    为什么不默认判红：本机常有别人的在途注册表/升级窗口，会把"环境暂时不可用"
    误当成泄漏；但**绝不静默** —— 每次都会打印并进入「本次未验证面」清单。
    """
    if '--strict' in FLAGS:
        total[0] += 1
        print('  [邮件面] 环境不可用（--strict 下计失败）：%s' % why)
    else:
        print('  [邮件面] 环境不可用，登记为未验证面：%s' % why)
        MAIL_UNVERIFIED.append(why)
    return None


def probe_row_len(parts):
    """探针行里的渲染字节数（MAILPROBE / MAILTPL 的 parts[3]）；缺失或非数字 → None。"""
    return int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None


def render_is_empty(probe_len):
    """`len=0` ⇒ **没看成**，不是"干净"（t79）。

    探针里逐语言 `try: 渲染 except Exception: continue`；三种语言**全部**渲染失败时，
    探针仍会上报一行 `…|OK|0|0|0|0|…` —— 旧实现把这行计入"渲染成功"，
    于是"一个字都没渲染出来"和"渲染出来且干净"在汇总里长得一模一样（假绿家族）。
    判据：**len=0 → 未覆盖（计入失败）**；len 缺失 → 不是空（那是 UNCOVERED 行，另走分支）。
    """
    return probe_len == 0


def mail_check(total):
    """渲染邮件模板并断言不含 odoo / odoo.com（t31 F3）。

    - 走 docker compose exec odoo shell（与数据不变量同款只读探测）；
    - 单支模板渲染失败 → **显式列入未覆盖清单并计入失败**（"验不了"不能当"干净"）；
    - 整个探测跑不起来（无 docker / shell 非零退出）→ 明确打印跳过，不计命中。
    """
    if os.environ.get('TRACE_FORCE_MAIL_UNAVAILABLE'):
        # 验收用构造钩子（t55）：把"某个面不可用"变成可复现的实测，而不是靠真出故障。
        return _mail_env_unavailable(
            total, 'TRACE_FORCE_MAIL_UNAVAILABLE=1（构造：邮件面不可用）')
    probe = MAIL_PROBE_TEMPLATE.replace(
        'MAIL_TEMPLATES', repr(MAIL_TEMPLATES))
    try:
        out = subprocess.run(
            ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
             '-c', '/etc/odoo/odoo.conf', '--db_host=db', '-r', 'odoo',
             '-w', 'odoo', '-d', DB, '--no-http'],
            input=probe, capture_output=True, text=True, timeout=300)
    except Exception as exc:
        return _mail_env_unavailable(total, '无法调用 odoo shell：%s' % str(exc)[:70])
    rows = [ln for ln in (out.stdout or '').splitlines()
            if ln.startswith('MAILPROBE|') or ln.startswith('DATAFACE')
            or ln.startswith('MAILTPL|')]
    if not rows:
        return _mail_env_unavailable(
            total, 'odoo shell 未返回结果（exit=%s，多半是注册表/升级在途）'
            % out.returncode)
    uncovered, checked, hits = [], 0, 0   # hits 同时进 MAIL_SUMMARY['hits']（汇总唯一来源）
    df_hits, df_total, tpl_hits = [], {}, []
    df_reachable, df_unreachable, df_linkonly = [], [], []
    core_links = 0            # 邮件面本次剥离的内部核心链接数（边界计数用）
    for row in rows:
        if row.startswith('DATAFACE|'):
            parts = row.split('|')
            if len(parts) > 3 and parts[2].isdigit():
                df_total[parts[1]] = tuple(int(x) for x in parts[2:6])
                if int(parts[2]):
                    df_hits.append(parts[1])
            continue
        if row.startswith('MAILTPL|'):
            parts = row.split('|')
            if len(parts) > 5:
                if render_is_empty(probe_row_len(parts)):
                    uncovered.append((parts[1],
                                      '渲染结果为空（len=0：三种语言都没渲染成功）'
                                      '⇒ 未验证，不得计入 PASS'))
                    total[0] += 1
                    print('  [模板正文] 未覆盖   %-44s len=0（三语都没渲染出来 ⇒ '
                          '计入失败）' % parts[1])
                    continue
                n_o, n_c, n_d = int(parts[4]), int(parts[5]), int(parts[6])
                # MAILTPL 行格式：…|len|odoo|odoo.com|odoocdn|样本|core → core 在 parts[8]
                if len(parts) > 8 and parts[8].isdigit():
                    core_links += int(parts[8])
                if n_o or n_c or n_d:
                    tpl_hits.append((parts[1], n_o, n_c, n_d, parts[7] if len(parts) > 7 else ''))
                else:
                    print('  [模板正文] ok       %-44s len=%s' % (parts[1], parts[3]))
            continue
        if row.startswith('DATAFACE_LINKONLY|'):
            parts = row.split('|')
            if len(parts) > 3 and parts[3] not in [x[0] for x in df_linkonly]:
                df_linkonly.append((parts[3], parts[2]))
            continue
        if row.startswith('DATAFACE_HIT|'):
            parts = row.split('|')
            if len(parts) > 4:
                mod, xmlid, vis = parts[2], parts[3], parts[4]
                # 按 xmlid 去重：探针是逐 (字段×语言) 上报的，直接累加会重复计数
                if xmlid in [r[0] for r in df_reachable + df_unreachable]:
                    continue
                if mod in UNREACHABLE_MODULES:
                    df_unreachable.append((xmlid, mod, vis))
                else:
                    df_reachable.append((xmlid, mod, vis))
            continue
        if row.startswith('DATAFACE_SAMPLE|'):
            if not QUIET_DATA_FACE:
                print('    [数据面样本] %s %s %s：%s'
                      % tuple(row.split('|')[1:5]))
            continue
        parts = row.split('|')
        name, status = parts[1], parts[2]
        if status == 'OK':
            if render_is_empty(probe_row_len(parts)):
                uncovered.append((name, '渲染结果为空（len=0）⇒ 未验证，不得计入 PASS'))
                total[0] += 1
                print('  [邮件面] 未覆盖   %-38s len=0（正文为空 ⇒ 不只是"没命中"，'
                      '是"没看成"）' % name)
                continue
            checked += 1
            # 内部核心链接剥离数在**宿主侧**累计（探针只上报，不持有宿主变量 —— 踩过一次）
            # MAILPROBE 行格式：…|len|odoo|odoo.com|odoocdn|core → core 在 parts[7]
            core_links += int(parts[7]) if len(parts) > 7 and parts[7].isdigit() else 0
            odoo_n = int(parts[4]) if len(parts) > 4 else 0
            com_n = int(parts[5]) if len(parts) > 5 else 0
            cdn_n = int(parts[6]) if len(parts) > 6 else 0
            bad = odoo_n + com_n + cdn_n
            if bad:
                hits += bad
                total[0] += bad
                print('  [邮件面] HIT      %-38s len=%s odoo=%s odoo.com=%s odoocdn=%s'
                      % (name, parts[3], odoo_n, com_n, cdn_n))
            else:
                # 打印渲染字节数：这是「探针是否真的用了忠实上下文」的可审计信号
                # （旧探针缺数据时 digest 只有约 3.6KB，忠实上下文 18KB+）
                print('  [邮件面] ok       %-38s len=%s odoo=0 odoo.com=0 odoocdn=0'
                      % (name, parts[3]))
        else:
            uncovered.append((name, parts[3] if len(parts) > 3 else ''))
            total[0] += 1
            print('  [邮件面] 未覆盖   %-38s %s' % (name, uncovered[-1][1][:70]))
    for nm, n_o, n_c, n_d, sample in tpl_hits:
        print('  [模板正文] 待修     %-44s odoo=%d odoo.com=%d odoocdn=%d'
              % (nm, n_o, n_c, n_d))
        if not QUIET_DATA_FACE and sample:
            print('        %s' % sample[:100])
    if tpl_hits:
        print('  [模板正文] ⚠ 待修面 %d 条（mail.template 是数据记录：'
              '**xpath 改不了 body_html**，需 data_brand 的 function 重放）；'
              '不计入四维判据' % len(tpl_hits))
    # 先落盘 linkonly（数据面那行要**在打印前**读到它 —— 曾经因为顺序问题导致
    # 新加的说明文字没出现，属于"改了但没生效"类，靠实测输出才抓到）
    MAIL_SUMMARY['linkonly'] = df_linkonly
    if df_reachable or df_unreachable:
        print('  [数据面] 可达命中 %d 条 / 不可达登记 %d 条（按本部署可达性口径，'
              '登记理由见代码 UNREACHABLE_MODULES）'
              % (len(df_reachable), len(df_unreachable)))
        for xmlid, mod, vis in df_unreachable[:6]:
            print('        不可达：%s（%s）' % (xmlid, UNREACHABLE_MODULES[mod]))
    for model, vals in sorted(df_total.items()):
        bad, total, text_recs, combos = (list(vals) + [0, 0, 0, 0])[:4]
        # t63：把「内部链接型」**写进同一个括号里**（不是另起一段计数）——
        # 否则读者还得自己做减法，容易重演"口径不同数字混用"（44 vs 15 那次争议的成因）。
        inner = '可见文案 %d 条；匹配组合 %d' % (text_recs, combos)
        if model == 'mail.template' and MAIL_SUMMARY.get('linkonly'):
            inner = ('其中 %d 条属内部核心链接型，按 /odoo、/web 口径不计；%s'
                     % (len(MAIL_SUMMARY.get('linkonly', [])), inner))
        print('  [数据面] %-14s 命中记录 %d/%d（%s）%s'
              % (model, bad, total, inner, '（待修，见样本）' if bad else ''))
    if df_hits:
        print('  [数据面] ⚠ 本轮待修面：%s —— 这些记录**能到达收件人**，'
              '命中即报；修复需 edu_brand 数据/模板任务（不在本门禁 inScope）'
              % '、'.join(df_hits))
    # 汇总口径统一为四段式（t54 追加要求）：早先「覆盖 4/8」与「8 支全部覆盖」两处各算
    # 一套，读的人会误解 —— 同一行两种说法就是口径分支，属假绿家族。
    qweb_n = sum(1 for t in MAIL_TEMPLATES if t in QWEB_MAIL_TEMPLATES)
    tpl_n = len(MAIL_TEMPLATES) - qweb_n
    tpl_ok = sum(1 for t in MAIL_TEMPLATES if t not in QWEB_MAIL_TEMPLATES
                 and t not in [h[0] for h in tpl_hits]
                 # t79：len=0 的未覆盖行不得算作"渲染成功"（口径同 uncovered）
                 and t not in [u[0] for u in uncovered])
    MAIL_SUMMARY.update({'linkonly': df_linkonly, 'core_links': core_links,
                         'total': len(MAIL_TEMPLATES), 'qweb': qweb_n, 'tpl': tpl_n,
                         'ok': checked + tpl_ok, 'uncovered': len(uncovered),
                         'pending': len(tpl_hits), 'hits': hits})
    print('  [邮件面] 候选 %d 支（QWeb %d + mail.template %d）/ 渲染成功 %d / 未覆盖 %d / '
          '数据记录待修 %d%s'
          % (MAIL_SUMMARY['total'], qweb_n, tpl_n, MAIL_SUMMARY['ok'],
             MAIL_SUMMARY['uncovered'], MAIL_SUMMARY['pending'],
             '（未覆盖即计入失败，不做静默跳过）' if uncovered else ''))
    return uncovered


def route_count():
    return (len(PUBLIC_ROUTES) + sum(len(r[2]) for r in ROLES)
            + sum(len(b[2]) for b in BACKEND))


def print_routes():
    print('路由覆盖（静态）：公开站 %d + %s + 后台 %d = 合计 %d'
          % (len(PUBLIC_ROUTES),
             ' + '.join('%s %d' % (r[0], len(r[2])) for r in ROLES),
             sum(len(b[2]) for b in BACKEND), route_count()))
    print('  公开站：%s' % ' '.join(PUBLIC_ROUTES))
    for title, _key, routes in ROLES:
        print('  %s：%s' % (title, ' '.join(routes)))
    for title, _key, routes in BACKEND:
        print('  %s：%s' % (title, ' '.join(routes)))
    # 覆盖边界自解释（verifier 建议）：模式条数与「本次实际跟随条数」分开报，
    # 读的人不必翻注释就知道哪些是"配了但这次没出现在页面上"的。
    print('  动态发现模式：%d 类 / 每角色最多 %d 条 —— %s'
          % (len(FOLLOW_KINDS), FOLLOW_MAX, '、'.join(FOLLOW_KINDS)))
    print('    （模式数 = 已配置的抓取维度；**本次实际命中/跟随条数**在完整运行末尾统计，'
          '两者不同不代表漏扫）')
    print('  邮件面模板：%s' % ', '.join(MAIL_TEMPLATES))
    print('  凭据来源：%s（口令只在此处声明，env 可覆盖；输出从不打印口令）'
          % ' + '.join('%s=%s' % (k, credential(k)[0]) for k in CRED_DEFAULTS))
    if EXTRA_ROUTES:
        print('  ⚠ 自证钩子已启用：TRACE_EXTRA_ROUTES=%s —— **不是**声明覆盖面，'
              '仅用于证明"红是可达的"' % ' '.join(EXTRA_ROUTES))


# ---------------------------------------------------------------- selftest
SELFTEST_LEAK = ('<table><tr>'
                 '<td class="text-muted small text-nowrap d-none d-md-table-cell">'
                 'OpenEducat Bot</td></tr></table>')
SELFTEST_CASES = [
    # (名称, 样本, 是否要求命中)
    ('真实泄漏样本：/downloads 的 OpenEducat Bot 单元格', SELFTEST_LEAK, True),
    ('构造：可见 Odoo 文本', '<p>Powered by <b>Odoo</b></p>', True),
    ('构造：user menu 外链', '<a href="https://www.odoo.com/buy">帮助</a>', True),
    ('构造：meta generator', '<meta name="generator" content="Odoo"/>', True),
    ('构造：/web 导航链接', '<a href="/web/login?db=x">登录</a>', True),
    # 2026-10-13：门户侧栏「管理后台」入口删除后，精确 "/web" 也计残留
    # （原先它是 NAV_ALLOW 里的放行项，见该常量的注释）。
    ('构造：精确 /web 入口（2026-10-13 收口后应为命中）',
     '<a href="/web">管理后台</a>', True),
    ('构造：noreply 发件人', '<span>from noreply@odoo.com</span>', True),
    ('干净样本：JS 运行时标识 + 资产（有意不计）',
     '<script>var odoo = {csrf_token: "x"}; odoo.__session_info__ = {};</script>'
     '<link href="/web/assets/1/abc/web.assets_frontend.min.js"/>'
     '<a href="/web/image/website/1/logo">校徽</a>', False),
    ('干净样本：中文门户页',
     '<div class="oe-norec"><p class="oe-norec-txt">暂未获得结业证书</p></div>', False),
    ('构造：/website/search 放行', '<form action="/website/search"><input/></form>', False),
    # t79：登录墙必须走门户友好别名（真实缺陷样本的反面 —— 见 '构造：/web 导航链接'）
    ('干净样本：友好别名登录链接 /login?redirect=…（t79 修法）',
     '<a href="/login?redirect=%2Falumni">登录</a>', False),
    # --- t26 新增：属性值维度 ---
    ('真实样本：Odoo core 按钮 tooltip（**只在 title 属性里**）',
     '<a title="转到您的Odoo应用程序" class="o_frontend_to_backend_apps_btn">应用</a>', True),
    ('构造：aria-label 里的品牌字样',
     '<button aria-label="Odoo 快捷菜单">菜单</button>', True),
    ('干净样本：纯中文属性值（不误报）',
     '<span title="查看详情" aria-label="关闭" alt="校徽"></span>', False),
    # t78：data-* 的**两条边界样本**（写进测试，而不是只写在 docstring —— 否则边界随人记忆漂移）。
    # 实测发现这条边界是**劈开的**，比我原先的假设更细：
    #   ① data-tooltip 不在 ATTR_RE 清单里 → **不扫**（干净样本）；
    #   ② data-title 含子串 title= → **会被扫到**（机会型覆盖，命中；这是意外的正面结果）。
    ('干净样本：data-tooltip 不扫（边界样本 ①，已知缺口）',
     '<div data-tooltip="切换到 Odoo 应用"></div>', False),
    ('构造：data-title 因含 title= 子串被扫到（边界样本 ②，机会型覆盖）',
     '<div data-title="Odoo 应用"></div>', True),
    # --- t68 按"规则族覆盖"补齐的两条（此前 attr-openeducat / attr-powered-by 没有必须命中的样本）---
    ('构造：属性值里的基座品牌名（OpenEduCat）',
     '<span title="OpenEduCat 学院"></span>', True),
    ('构造：属性值里的 Powered by（非 odoo 也要抓）',
     '<a title="Powered by 某某基金会">说明</a>', True),
]
SELFTEST_REQUIRED_ROUTES = ['/downloads', '/my/apps', '/my/study', '/login',
                            '/register', '/apps']


def data_invariant_violation(login_name, name):
    """技术账号显示名命中基座品牌 token → 违规。

    **只看技术账号**（uid=1 或 TECH_LOGINS 里的 login）——有意不做全库 name 扫描：
    将来学员/机构名里含 odoo/bot 会误报，而门禁误报会训练大家忽略门禁。
    """
    if (login_name or '').lower() not in TECH_LOGINS_LC:
        return False
    return bool(BRAND_TOKEN_RE.search(name or ''))


def data_invariant_check(total):
    """数据不变量（只读）：技术账号显示名不得含基座品牌 token。

    通过 docker compose exec db psql 查询；环境不支持时打印提示并跳过（不计命中）。
    """
    logins = "','".join(TECH_LOGINS_LC)
    sql = ("select u.id || '|' || u.login || '|' || p.name "
           "from res_users u join res_partner p on p.id = u.partner_id "
           "where u.id = 1 or lower(u.login) in ('%s')" % logins)
    try:
        out = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                              '-U', 'odoo', '-d', DB, '-tAc', sql],
                             capture_output=True, text=True, timeout=90)
    except Exception as exc:
        why = '数据不变量面：无法调用 docker/psql（%s）' % str(exc)[:60]
        print('  [数据不变量] 跳过：%s' % why)
        DATA_UNVERIFIED.append(why)
        return None
    if out.returncode != 0:
        why = '数据不变量面：psql 退出码 %s' % out.returncode
        print('  [数据不变量] 跳过：%s' % why)
        DATA_UNVERIFIED.append(why)
        return None
    rows = [r for r in (out.stdout or '').splitlines() if '|' in r]
    bad = 0
    for row in rows:
        uid, login_name, name = (row.split('|') + ['', '', ''])[:3]
        if data_invariant_violation(login_name, name):
            bad += 1
            total[0] += 1
            print('  [数据不变量] VIOLATION uid=%-3s login=%-12s name=%s'
                  % (uid, login_name, name))
        else:
            print('  [数据不变量] ok        uid=%-3s login=%-12s name=%s'
                  % (uid, login_name, name))
    print('  [数据不变量] 技术账号 %d 个，违规 %d 个' % (len(rows), bad))
    return bad


def selftest():
    fails = []
    print('=== selftest：扫描器有效性 ===')
    for name, sample, want_hit in SELFTEST_CASES:
        hits = scan(sample, True)
        got = bool(hits)
        ok = got == want_hit
        print('  %-4s %-52s 期望%s 实际%s'
              % ('PASS' if ok else 'FAIL', name[:52],
                 '命中' if want_hit else '不命中', '命中' if got else '不命中'))
        if not ok:
            fails.append('%s：期望 %s，实际 %s（%s）'
                         % (name, want_hit, got, [h[0] for h in hits][:3]))
    print('=== selftest：v3 必需路由确在清单里 ===')
    all_static = set(PUBLIC_ROUTES)
    for _t, _k, routes in ROLES:
        all_static |= set(routes)
    for _t, _k, routes in BACKEND:
        all_static |= set(routes)
    for path in SELFTEST_REQUIRED_ROUTES:
        ok = path in all_static
        print('  %-4s %s' % ('PASS' if ok else 'FAIL', path))
        if not ok:
            fails.append('路由清单缺少 %s' % path)
    print('=== selftest：动态发现正则能抓到 ID/token 类路由 ===')
    dyn = FOLLOW_RE.findall('<a href="/my/study/12">课</a>'
                            '<a href="/my/study/session/7/join">入会</a>'
                            '<a href="/my/courses/lesson/3">节</a>'
                            '<a href="/my/calendar/ics/AbC-123">订阅</a>')
    dyn2 = FOLLOW_RE.findall('<a href="/downloads/need-ack/9">确认</a>'
                             '<a href="/downloads/unacked/9">未读</a>')
    ok = len(dyn) == 4 and len(dyn2) == 2
    print('  %-4s 抓到 %d/4 + t8 %d/2：%s' % ('PASS' if ok else 'FAIL',
                                             len(dyn), len(dyn2), dyn + dyn2))
    if not ok:
        fails.append('FOLLOW_RE 未抓到全部动态路由：%s' % (dyn + dyn2))
    print('=== selftest：自证行（t68）===')
    ts_ok = bool(re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$', RUN_STAMP))
    parsed = None
    try:
        parsed = datetime.datetime.fromisoformat(RUN_STAMP)
    except Exception:
        parsed = None
    tz_ok = parsed is not None and parsed.tzinfo is not None
    line_ok = all(k in revision_line() for k in (REVISION, _fingerprint(), '运行 ' + RUN_STAMP))
    for ok, why in ((ts_ok, '运行时刻是带时区偏移的 ISO-8601（可解析）'),
                    (tz_ok, '运行时刻带时区信息（本地时区偏移）'),
                    (line_ok, '自证行同时含 REVISION/指纹/运行时刻')):
        print('  %-4s %s' % ('PASS' if ok else 'FAIL', why))
        if not ok:
            fails.append('自证行断言失败：%s' % why)

    print('=== selftest：fetch 类异常 → ENV 通道（t73）===')
    env_cases = [
        (requests.exceptions.ReadTimeout('timed out'), 'ENV', 'ReadTimeout（超时）→ ENV'),
        (requests.exceptions.ConnectionError('closed'), 'ENV', 'ConnectionError（断连）→ ENV'),
        (ValueError('bug'), 'BUG', '非 requests 异常 → BUG（保持响亮，不伪装成环境问题）'),
    ]
    for exc, want, why in env_cases:
        got, _msg = classify_fetch_exception(exc)
        ok = got == want
        print('  %-4s %-44s 期望 %s 实际 %s' % ('PASS' if ok else 'FAIL', why[:44], want, got))
        if not ok:
            fails.append('ENV 分类 %s：期望 %s 实际 %s' % (why, want, got))
    for hits, unv, env, want, why in ((0, [], 1, 2, '环境不可用 → 2（ENV），不进"未验证面"档'),
                                      (3, [], 1, 1, '有命中时命中优先 → 1（FAIL）')):
        got = exit_code(hits, unv, True, env)
        ok = got == want
        print('  %-4s %-44s 期望退出码 %s 实际 %s' % ('PASS' if ok else 'FAIL', why[:44], want, got))
        if not ok:
            fails.append('ENV 退出码 %s：期望 %s 实际 %s' % (why, want, got))

    print('=== selftest：规则族覆盖（每条规则都要有"必须命中"的样本，t68）===')
    covered = set()
    for _name, sample, want in SELFTEST_CASES:
        if want:
            covered |= {rule for rule, _ in scan(sample, True)}
    # 非 HTML 通道（brand-text-feed）走的是另一条路径，单独喂一个"必须命中"的纯文本样本
    covered |= {rule for rule, _ in scan('订阅流：Powered by Odoo / OpenEduCat', True, nonhtml=True)}
    missing = [r for r in ALL_RULES if r not in covered]
    for rule in ALL_RULES:
        ok = rule in covered
        print('  %-4s %s%s' % ('PASS' if ok else 'FAIL', rule,
                               '' if ok else '  ← 无 must-hit 样本：它从没打算被判假（占位符）'))
    if missing:
        fails.append('规则族缺少 must-hit 样本：%s' % missing)

    # ---- t74：期望规则名（红了必须「红的正是预期那条」）----
    rule_mismatch = []
    for _name, sample, want in SELFTEST_CASES:
        if not want:
            continue
        fired = {rule for rule, _ in scan(sample, True)}
        exp = set(EXPECT_RULES.get(_name, ()))
        if fired != exp:
            rule_mismatch.append('%s：期望 %s 实际 %s' % (_name[:28], sorted(exp), sorted(fired)))
    fired_nh = {rule for rule, _ in scan(NONHTML_SAMPLE, True, nonhtml=True)}
    if fired_nh != set(NONHTML_EXPECT):
        rule_mismatch.append('非 HTML 样本：期望 %s 实际 %s'
                             % (sorted(NONHTML_EXPECT), sorted(fired_nh)))
    ok = not rule_mismatch
    print('  %-4s 每个 must-hit 样本红的都是预期规则（%d 个样本 + 非 HTML 通道）'
          % ('PASS' if ok else 'FAIL', len(EXPECT_RULES)))
    for m in rule_mismatch[:3]:
        print('        - %s' % m)
    if not ok:
        fails.append('期望规则名不符：%s' % rule_mismatch[:2])

    # ---- t74 构造反例：期望写错时必须能被检出（否则这层形同虚设）----
    _demo = '<a href="/web/login?db=x">登录</a>'      # 实际只命中 web-nav-link
    _demo_rules = {rule for rule, _ in scan(_demo, True)}
    _wrong_exp = {'visible-odoo-text'}                  # 故意写错
    caught = _demo_rules != _wrong_exp
    print('  %-4s 构造反例：期望写错能被检出（实际规则 %s）'
          % ('PASS' if caught else 'FAIL', sorted(_demo_rules)))
    if not caught:
        fails.append('构造反例未被检出：期望规则名这层无法发现「被别的规则接管」')

    # ---- t74 漂移防护：ALL_RULES（声明） vs 文件里实际出现规则名字面量（事实）----
    try:
        _src = open(__file__, encoding='utf-8').read()
        actual_rules = set(re.findall(r"hits\.append\(\('([a-z0-9-]+)'", _src))
    except Exception as exc:
        actual_rules = set()
        print('  FAIL 规则名对拍无法读取本文件：%s' % str(exc)[:60])
        fails.append('RULES-DRIFT：无法对拍（读文件失败）')
    drift = sorted(actual_rules.symmetric_difference(set(ALL_RULES)))
    ok = not drift
    print('  %-4s RULES-DRIFT：实际 %d 条 vs 声明 %d 条%s'
          % ('PASS' if ok else 'FAIL', len(actual_rules), len(ALL_RULES),
             '' if ok else ' → 差异 %s（有意新增请同步 ALL_RULES，让它进 diff）' % drift))
    if not ok:
        fails.append('RULES-DRIFT：声明与实际不一致 %s' % drift)

    print('=== selftest：退出码契约（t55）===')
    ec_cases = [
        ((0, []), True, 0, '全部已验 + 0 命中 → OK'),
        ((3, []), True, 1, '有命中 → FAIL'),
        ((0, ['邮件面：odoo shell 不可用']), True, 1, '默认 strict：未验证面 → 失败'),
        ((0, ['邮件面：odoo shell 不可用']), False, 3, '形参 strict=False（--lenient）→ 3'),
    ]
    for (hits, unv), strict_flag, want, why in ec_cases:
        got = exit_code(hits, unv, strict_flag)
        ok = got == want
        print('  %-4s %-40s 期望退出码 %s 实际 %s'
              % ('PASS' if ok else 'FAIL', why[:40], want, got))
        if not ok:
            fails.append('退出码契约 %s：期望 %s 实际 %s' % (why, want, got))
    if STRICT:
        print('  PASS 默认 strict 生效（FLAGS 里没有 --lenient）')
    else:
        fails.append('默认应为 strict，但检测到 --lenient')

    print('=== selftest：数据不变量判定（含反向样本）===')
    inv_cases = [
        (('__system__', 'OpenEducat Bot'), True, '真实根因：技术账号显示名含品牌 token'),
        # t41：集合对齐 contacts.py:27 后的正向断言（这两个 login 本地库不存在，属防御性登记）
        (('OdooBot', 'OdooBot'), True, 'OdooBot 在集合内且名含品牌 token → 必须命中'),
        (('__oe__', 'OpenEduCat Bot'), True, '__oe__ 在集合内且名含品牌 token → 必须命中'),
        (('public', 'Public user'), False, 'public 在集合内但名字无品牌 token → 不 FAIL'),
        # 反向样本：**非**技术账号即使含品牌词也不得 FAIL（否则学员/机构名会误报）
        (('stu@local', 'Odootown 教会'), False, '反向样本：非技术账号含 odoo 不 FAIL'),
        (('mary@local', 'Bot 同学'), False, '反向样本：非技术账号含 bot 不 FAIL'),
        (('__system__', '系统'), False, '修好态：技术账号中性中文不 FAIL'),
    ]
    for (login_name, name), want_bad, why in inv_cases:
        got = data_invariant_violation(login_name, name)
        ok = got == want_bad
        print('  %-4s %-42s 期望%s 实际%s'
              % ('PASS' if ok else 'FAIL', why[:42],
                 'FAIL' if want_bad else '不FAIL', 'FAIL' if got else '不FAIL'))
        if not ok:
            fails.append('%s：期望 %s 实际 %s' % (why, want_bad, got))
    print('=== selftest：结论行（4 个退出码都必须有自述，t79）===')
    _vlines = {c: verdict_line(c, 3 if c == 1 else 0, 2, 1) for c in (0, 1, 2, 3)}
    ok = (all(_vlines.values()) and _vlines[0].startswith('PASS')
          and 'FAIL' in _vlines[1] and _vlines[2].startswith('ENV')
          and _vlines[3].startswith('INCOMPLETE'))
    print('  %-4s 退出码 0/1/2/3 各有结论行（0 的那条曾写在 return 之后 ⇒ 恒缺失）'
          % ('PASS' if ok else 'FAIL'))
    if not ok:
        fails.append('结论行缺失或与退出码不符：%s'
                     % {c: v[:24] for c, v in _vlines.items()})

    print('=== selftest：HTTP 状态分类（t79：5xx ⇒ 未验证面，不得冒充已验证）===')
    status_cases = [
        (200, 'ok', '2xx → 照常扫正文'),
        (404, 'ok', '4xx 错误页是真实可达页面 → 照常扫（其品牌痕迹照算命中）'),
        (302, 'redir', '3xx → 不跟随、不计命中'),
        (500, 'unverified', '5xx → 正文不是目标页 ⇒ 登记未验证面'),
    ]
    for _code, want, why in status_cases:
        got = classify_status(_code)
        ok = got == want
        print('  %-4s %-48s 期望 %s 实际 %s'
              % ('PASS' if ok else 'FAIL', why[:48], want, got))
        if not ok:
            fails.append('状态分类 %s：期望 %s 实际 %s' % (_code, want, got))

    print('=== selftest：凭据（t79：默认值不得回退到已知失效口令）===')
    _bak = os.environ.get('TRACE_STU_PASSWORD')
    os.environ['TRACE_STU_PASSWORD'] = 'env-probe'
    _override = credential('STU')[1] == 'env-probe'
    if _bak is None:
        os.environ.pop('TRACE_STU_PASSWORD', None)
    else:
        os.environ['TRACE_STU_PASSWORD'] = _bak
    _dead = sorted(k for k, v in CRED_DEFAULTS.items() if v in KNOWN_DEAD_CREDENTIALS)
    cred_cases = [
        (_override, 'env 覆盖生效：TRACE_<KEY>_PASSWORD 优先于默认值'),
        (not _dead, '默认凭据不含已知失效组合 admin/admin（它让本门禁静默失效）'),
        (all(credential(k)[0] and credential(k)[1] for k in CRED_DEFAULTS),
         '5 个登录面（4 角色 + 后台）都有非空 login/password'),
    ]
    for ok, why in cred_cases:
        print('  %-4s %s' % ('PASS' if ok else 'FAIL', why))
        if not ok:
            fails.append('凭据：%s%s' % (why, '（命中已知失效组合：%s）' % _dead if _dead else ''))

    print('=== selftest：邮件探针行解析（t79：len=0 不得算"渲染成功"）===')
    mail_row_cases = [
        ('MAILPROBE|mail.mail_notification_layout|OK|1005|0|0|0|7'.split('|'),
         1005, False, 'QWeb 行：len=1005 → 非空'),
        ('MAILTPL|auth_signup.set_password_email|OK|0|0|0|0||0'.split('|'),
         0, True, 'mail.template 行：len=0（三语全失败也照样上报 OK）→ 必须判空'),
        ('MAILTPL|x|OK|1|0|0|0||0'.split('|'), 1, False, '极短但非空 → 不算空（防过度判空）'),
        ('MAILPROBE|t|UNCOVERED|boom'.split('|'), None, False,
         '未覆盖行：len 字段缺失 → None（不是空，走另一个分支）'),
    ]
    for parts, want_len, want_empty, why in mail_row_cases:
        got_len = probe_row_len(parts)
        got_empty = render_is_empty(got_len)
        ok = got_len == want_len and got_empty == want_empty
        print('  %-4s %-50s len=%s 判空=%s'
              % ('PASS' if ok else 'FAIL', why[:50], got_len, got_empty))
        if not ok:
            fails.append('邮件探针行解析 %s：len 期望 %s 实际 %s；判空 期望 %s 实际 %s'
                         % (why, want_len, got_len, want_empty, got_empty))

    print('')
    if fails:
        print('SELFTEST FAIL：')
        for f in fails:
            print('  - %s' % f)
        return 1
    # +1 = 规则族覆盖；+3 = 自证行三条断言（t68；新增断言已同改动同步 EXPECTED_ASSERTIONS）
    # +1 = 规则族覆盖；+3 = 自证行三条断言（t68）；+2/+3 = t73/t74；
    # +1 = 结论行组；+len(status_cases) = t79 HTTP 状态分类；+len(cred_cases) = t79 凭据
    actual = (len(SELFTEST_CASES) + len(ec_cases) + len(inv_cases) + 1 + 3
              + len(env_cases) + 2 + 3 + 1 + len(status_cases) + len(cred_cases)
              + len(mail_row_cases))
    if actual != EXPECTED_ASSERTIONS:
        print('SELFTEST FAIL：断言条数漂移 —— 声明 %d，实际 %d（改断言必须同步 '
              'EXPECTED_ASSERTIONS）' % (EXPECTED_ASSERTIONS, actual))
        return 1
    print('  %s（含数据不变量 %d 个样本）' % (revision_line(actual), len(inv_cases)))
    print('SELFTEST PASS：%d 个扫描样本 + 规则族覆盖 %d 族 + %d 个退出码契约样本 + %d 个数据不变量样本'
          '（含正反断言）全部符合预期，v3 路由已纳入清单，动态发现可用'
          % (len(SELFTEST_CASES), len(ALL_RULES), len(ec_cases), len(inv_cases)))
    return 0


def main():
    if '--selftest' in FLAGS:
        return selftest()
    if '--list-routes' in FLAGS:
        print_routes()
        return 0
    if '--mail' in FLAGS:
        total = [0]
        print('=== 邮件面（渲染邮件模板断言，t31 F3） ===')
        mail_check(total)
        # 退出码一律走 exit_code()（契约唯一来源；t55）
        print('')
        if total[0]:
            print('FAIL：邮件面命中 %d 处' % total[0])
            return 1
        if MAIL_UNVERIFIED:
            print('INCOMPLETE：邮件面未验证（%s）'
                  % MAIL_UNVERIFIED[0][:70])
            print('  未验证面不得计入 PASS（t55 口径）：默认 strict 判失败，'
                  '--lenient 时才给 INCOMPLETE 专用的退出码 3')
            return 1 if STRICT else 3
        s = MAIL_SUMMARY
        print('PASS：邮件面品牌命中 %d（候选 %d 支 = QWeb %d + mail.template %d；渲染成功 %d；'
              '未覆盖 %d；数据记录待修 %d）'
              % (s.get('hits', 0), s.get('total', 0), s.get('qweb', 0), s.get('tpl', 0),
                 s.get('ok', 0), s.get('uncovered', 0), s.get('pending', 0)))
        return 0
    global RUN_WEB_STARTED
    RUN_WEB_STARTED = _web_started_at()      # 采样：用于"本次运行期间容器是否重启过"
    try:
        # t12：初始探活必须与下面几个正式 session 同口径（trust_env=False）。
        # 裸 requests.get() 会读本机（macOS）系统代理，于是这条探活两头都不对：
        #   · 代理**能连**时：拿回一个 502 **响应**（不抛异常）⇒ 探活"通过"，
        #     等于什么都没探到，站点真挂了也可能被代理的应答掩盖；
        #   · 代理**连不上**时：抛 ProxyError ⇒ 站点明明健康却报「环境不可用」exit 2（假红）。
        # ⚠ 别把它改回裸 requests.get()；本文件其它请求（下方 anon/session）早已 trust_env=False。
        _probe = requests.Session()
        _probe.trust_env = False
        _probe.get(BASE + '/web/login?db=' + DB, timeout=10)
    except Exception as exc:
        kind, why = classify_fetch_exception(exc)
        print('环境不可用（%s）：%s（%s）' % (kind, BASE, why))
        _mark_http_env('初始探活：%s' % why)
        print('  [ENV] 站点探测失败 → 退出码 2（ENV），不产出"通过"结论')
        return 2

    print_routes()
    print('')
    total = [0]
    seen = set()                    # 动态发现去重（跨角色共享，同一路由只扫一次）
    print('=== 公开站（匿名） ===')
    anon = requests.Session()
    anon.trust_env = False
    prime(anon)
    run_surface('公开站', anon, PUBLIC_ROUTES, True, total, seen)
    if EXTRA_ROUTES:
        print('=== 自证钩子：注入路由（TRACE_EXTRA_ROUTES）===')
        print('  声明：这几条**不是**本门禁的覆盖面，只用于就地证明"红是可达的"；'
              '默认关闭，不改变任何正常读数。')
        run_surface('注入路由', anon, EXTRA_ROUTES, True, total, seen)

    print('=== 登录态 4 角色 ===')
    n_auth_tried = n_auth_ok = 0
    for title, key, routes in ROLES:
        session = requests.Session()
        session.trust_env = False
        n_auth_tried += 1
        if not login_or_note(title, key, session, len(routes)):
            continue                       # t79：不 return 2 —— 该面登记未验证面，继续扫其余面
        n_auth_ok += 1
        run_surface(title, session, routes, True, total, seen)

    print('=== 后台（webclient，只扫文本与外链） ===')
    for title, key, routes in BACKEND:
        session = requests.Session()
        session.trust_env = False
        n_auth_tried += 1
        if not login_or_note(title, key, session, len(routes)):
            continue
        n_auth_ok += 1
        run_surface(title, session, routes, False, total, seen)

    if n_auth_tried and not n_auth_ok:
        # 一个面都没登上 = 凭据/站点整体不可用 ⇒ ENV(2)：本轮**没有任何结论**。
        # （与"个别面登不上"严格区分：后者是未验证面，走 1/3，且其余面的命中照报。）
        print('ENV：%d 个登录面**一个都没登上**（凭据或站点整体不可用）—— '
              '本轮不产出 PASS，也不产出命中结论；请修凭据后重跑' % n_auth_tried)
        return 2

    print('=== 数据不变量（技术账号显示名，只读查库） ===')
    data_invariant_check(total)

    print('=== 邮件面（渲染邮件模板断言，t31 F3） ===')
    mail_check(total)
    print('  动态发现：模式 %d 类 / 本次实际跟随 %d 条'
          % (len(FOLLOW_KINDS), len(seen)))

    # ---- t73：环境不可用（ENV）与容器重启（读数可能失真）都要显式可见 ----
    if HTTP_UNVERIFIED:
        print('=== ENV 通道（网络/超时导致未验证的路由；不计入命中） ===')
        for why in HTTP_UNVERIFIED[:6]:
            print('  [ENV] %s' % why[:90])
        print('  [ENV] 共 %d 条 —— 退出码 2=ENV（既不是"通过"，也不是"发现命中"）'
              % len(HTTP_UNVERIFIED))
    _now_started = _web_started_at()
    if RUN_WEB_STARTED and _now_started and _now_started != RUN_WEB_STARTED:
        CONTAINER_RESTARTED.append('web 容器在本次运行期间重启过（%s → %s）'
                                   % (RUN_WEB_STARTED[:19], _now_started[:19]))
    if CONTAINER_RESTARTED:
        print('=== 容器重启信号 ===')
        for why in CONTAINER_RESTARTED:
            print('  [WARN] %s —— 本次读数可能跨越重启，登记为未验证面' % why)

    print('=== 边界计数（按设计不覆盖，逐条对应 docstring 的覆盖声明） ===')
    print('  ① %s' % BOUNDARY_DESIGN[0])
    print('  ② %s' % BOUNDARY_DESIGN[1])
    linkonly_txt = ''
    _lo = MAIL_SUMMARY.get('linkonly', [])       # 单一来源：由 mail_check 填（曾误用局部变量 → NameError）
    if _lo:
        linkonly_txt = '；数据面 内部链接型 %d 条（%s）' % (
            len(_lo), '、'.join(x[0].split('.')[-1] for x in _lo[:3]))
    print('  ③ %s —— 本次邮件面剥离 %d 处%s'
          % (BOUNDARY_DESIGN[2], MAIL_SUMMARY.get('core_links', 0), linkonly_txt))
    print('  %s' % revision_line())

    # 未验证面（t55：**不得计入 PASS**）= 登录失败的表面 + 5xx 路由 + 邮件/数据面 + 容器重启
    unverified = (AUTH_UNVERIFIED + ROUTE_UNVERIFIED + MAIL_UNVERIFIED
                  + DATA_UNVERIFIED + CONTAINER_RESTARTED)
    for why in unverified:
        print('  本次未验证面：%s' % why[:80])

    print('')
    code = exit_code(total[0], unverified, STRICT, len(HTTP_UNVERIFIED))
    # t79：结论行由纯函数产出（旧实现把 PASS 行写在 return 之后 ⇒ 退出码 0 时一行都不打印）。
    print(verdict_line(code, total[0], len(unverified), len(HTTP_UNVERIFIED)))
    if total[0]:
        print('  命中 %d 处 —— 明细见上方逐条 HIT 行（规则名 + 片段）；'
              '本门禁不设豁免名单，命中即 FAIL' % total[0])
    if code in (1, 3) and not total[0]:
        for why in unverified:
            print('  - %s' % why[:90])
    if code == 2:
        for why in HTTP_UNVERIFIED[:5]:
            print('  - %s' % why[:90])
    return code


if __name__ == '__main__':
    sys.exit(main())
