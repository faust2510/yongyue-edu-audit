#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全站 axe 无障碍审计门禁（t105 · M9 收口）。

背景：M1–M10 里 M9（无障碍/一致性）是唯一"部分完成"项 —— aria 中文化 / 对比度 / ≥44px 触点
由 t16 与既有门禁覆盖，但**从未做全站 axe 审计**。本脚本把它变成**可复跑的量具 + 可行动清单**。

设计要点（本轮纪律）
1. **先证量具再读数**：`--selftest` 用两个极端样本 —— ① 必然违规页（无 alt 图片、无 lang、
   无标签表单、对比度不足）→ 断言**会红且命中预期规则**；② 无障碍正确页 → 断言**不报**
   （证明它不是"什么都报"）。selftest 不通过则不采信任何读数。
2. **axe-core 注入**：优先用本地缓存（`/tmp/edu_axe/axe-<版本>.min.js`），缺则从官方 CDN 取一次并缓存。
   扫描时用 `add_script_tag(content=…)` ⇒ **扫描本身不需要联网**；取不到 axe 时按 ENV 处理（exit 2）。
3. **名单来源**（B 组 2026-09-26 切换）：**tests/ui/surface.json**（登记表，A 组维护）里
   gates 含 accessibility 的条目 —— 表读不到 ⇒ 退出码 3（INCOMPLETE，不崩栈、不判 FAIL）。
   表里静态登记 33 条（2026-09-28 读数；含 **2 条后台页**，见 6）= 取样去重路径 33 条。
4. **取样口径**（"用哪个身份打开哪一页" —— 这一层留在本脚本，表没有等价字段）：
   **口径条数不写死在文档里** —— 跑 `--list` 或 `--coverage` 读当前值（写死的读数会烂，
   见 code-map §6 第 15 条）。构成 = 公开 6 + 学生 8 + 教师 6 + 家长 4 + 教务 4
   + 测评门户 4（2026-09-29 加）+ **2026-09-29 补的身份/页面缺口 4 条**
   （`/assess` 的 backoffice 与 faculty、`/assess/review` 的 backoffice、`/registrar/curriculum` 的
   backoffice —— 三条都写在 AUDIT_ROUTES 里，各带"为什么原先没覆盖"的实测理由）
   **+ 后台 7 条**（backoffice × 列表/看板/表单三种形态；**「设置」形态本栈无可用样本**，
   如实记为覆盖缺口 —— /odoo/settings 对谁都打不开，见 AUDIT_ROUTES 注释）；
   表新增登记（脚本口径未收录）按 scope/roles 自动补样；覆盖各角色"首页/列表/表单/详情"
   四类形态；口径里的路径若**不在表内**也**不在补偿清单内** ⇒ 不扫并点名（登记方口径优先，
   例：edu_telegram 退役路由），**绝不静默缩小**。
5. **分级**：按 axe 的 impact 四档 critical/serious/moderate/minor；**基线存常量**，变多即报（漂移），
   变少提示下调。
6. **后台页覆盖（2026-09-28 新增；本门禁原先是「门户专用」）**：扫描面原先 29 条路径**零后台页**，
   于是 .oe_topbar_name（后台公司名）这类「只在后台出现、且只在我们的品牌蓝上是错的」元素
   **永远无人覆盖**（实测：90% 白压 --brand-action = 4.372 ✗ < AA 4.5）。
   补上后，后台样本的判定口径分两层（纪律见 SHELL_SELECTOR 上方注释）：
     · **判据（零容忍，计入基线）**＝ 外壳 .o_navbar 里的 color-contrast ＋ 任何**未登记**规则
       ＋ 本地对比度检查 shell-contrast；
     · **核心清单（只读数、逐条打印、落 JSON）**＝ Odoo 核心渲染的页面主体与核心 ARIA 结构
       （role-img-alt / label / meta-viewport / html-has-lang / role=menu 结构…）。**这不是豁免**：
       出现未登记规则即判红，且每次跑都把清单原样印出来。
   ⚠ 为什么还需要**本地对比度检查**（axe 扫不到这个缺陷）：axe 的 color-contrast 匹配函数遇到
     isDisabled 会短路返回 false，而 isDisabled **向上继承**；本库只有一个公司 ⇒ Odoo 把
     「公司切换器」按钮渲染成 disabled ⇒ 里面的公司名 span **结构上永远扫不到**
     （实测 + 源码依据见 SHELL_TEXT_JS 上方注释）。本地检查按「文字色（含 α 合成）vs 有效底色」
     逐条实算，**不跳过 disabled**，并以 shell-contrast 计入判据。

用法
    python3 scripts/check_accessibility.py --selftest     # 只证量具（约 20–40s；a3 起 31 条断言）
    python3 scripts/check_accessibility.py                # 全站审计（实测 72 页，约 6–10 分钟）
    python3 scripts/check_accessibility.py --list         # 只读打印名单 + 对账（不连站点、不起浏览器）
    python3 scripts/check_accessibility.py --json out.json # 落盘（含 backend_samples / backend_core_inventory）
    python3 scripts/check_accessibility.py --only /odoo/students,/odoo/contacts
                                                          # 定向重扫：**样本被缩小**，只用于复现/演练
                                                          # （注入违例→必须变红 的复跑入口）
退出码：0=在基线内 ｜ 1=selftest/工具自身失败 ｜ 2=ENV（axe 取不到 / 站点不可达 / 浏览器起不来）
        也含「超出基线」｜ 3=INCOMPLETE（有页面未扫到 / 后台外壳量不到 / 表读不到）
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'

# ---------------------------------------------------------------- 自证
REVISION = 'a5'      # 2026-09-29：违规归属**按元素来源分流**（自研视图声明的按钮名 ⇒ 判据；
                    #   核心渲染 ⇒ 只读数）—— 规则名只说明「这条规则在核心里常见」，说明不了谁的账
                    # a4 = 2026-09-29：**后台覆盖 2 页 → 7 页**（抹掉「其余模型的列表/表单页没逐页验过」
                    #   这个缺口）+ 后台样本**形态断言**（BACKEND_EXPECT_VIEW / backend_view_ok：
                    #   带记录 id 的样本一旦静默回落成默认视图 ⇒ 判 INCOMPLETE，不判绿）
                    # a3 = 2026-09-28：补**后台页覆盖**（原先 29 条路径零后台页 ⇒ .oe_topbar_name
                    #   这类「只在后台出现」的元素永远无人覆盖）+ 外壳判据 / 核心清单分流
                    #   + 本地对比度检查（补 axe 的结构盲区：disabled 控件内的文字）
                    #   + --only 定向重扫（复现/演练用）
                    # a2 = 2026-09-26 B 组：名单改从 tests/ui/surface.json 读（gates 含 accessibility）
                    #   取样口径（身份 × 路径）留在脚本；退出码 += 3=INCOMPLETE（表读不到 / 有页未扫到）
SELFTEST_CASES = 39         # 断言条数（selftest 实际计数比对，漂移即 FAIL）
                            # a3 新增 16 条：对比度量具（4.372 / 5.019 两个实测档）+ 后台路径判据
                            #   + 大字判据 + shell_contrast_violations 三条 + partition_backend
                            #   + gated_to_violations + JS 选择器与常量一致
                            # a5 新增 3 条：违规归属分流（自研视图声明的按钮 ⇒ 判据 / 核心渲染 ⇒ 只读数
                            #   / 按钮名集合确实从仓内 XML 扫出来）
                            # a4 新增 4 条：形态断言三态（命中 / 回落不命中 / 未登记预期不受门槛）
                            #   + 「每个后台样本都必须登记形态预期」这条不变式
                            # 2026-09-26 B 组 +7：名单读取的纯函数（静态上级、默认取样身份 ×3、
                            # 表外口径剔除 ×2、表外口径不扫）—— 不连站点、不读真实表。
RUN_STAMP = datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def _self_fingerprint():
    """自身文件 md5 前 8 位（运行时算；不靠人 bump）。"""
    with open(os.path.abspath(__file__), 'rb') as fh:
        return hashlib.md5(fh.read()).hexdigest()[:8]


def self_attest_line():
    return 'REVISION=%s · 指纹 %s · 断言 %d 条 · 运行时刻 %s' % (
        REVISION, _self_fingerprint(), SELFTEST_CASES, RUN_STAMP)


# ---------------------------------------------------------------- axe
AXE_VERSION = '4.10.2'
AXE_URL = 'https://cdn.jsdelivr.net/npm/axe-core@%s/axe.min.js' % AXE_VERSION


def axe_cache_path():
    d = os.path.join(tempfile.gettempdir(), 'edu_axe')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'axe-%s.min.js' % AXE_VERSION)


def axe_source():
    """返回 axe-core 源码；取不到 → (None, 原因)。缓存优先，避免扫描期联网。"""
    p = axe_cache_path()
    if os.path.exists(p) and os.path.getsize(p) > 100000:
        return open(p, encoding='utf-8').read(), 'cache:%s' % p
    try:
        r = requests.get(AXE_URL, timeout=25)
        if r.status_code == 200 and len(r.content) > 100000:
            with open(p, 'wb') as fh:
                fh.write(r.content)
            return r.text, 'cdn:%s' % AXE_URL
    except Exception as e:
        return None, 'ERR %s' % str(e)[:80]
    return None, 'HTTP %s / 内容过短' % r.status_code


# ---------------------------------------------------------------- 取样口径
ROLE_LOGINS = {
    'student': ('stu@local', 'demo123'),
    'faculty': ('faculty@local', 'demo123'),
    'parent': ('parent@local', 'demo123'),
    'backoffice': ('backoffice@local', 'demo123'),
}
# 取样口径（**身份 × 路径**）—— 名单本身来自 tests/ui/surface.json（见下方 load_surface()），
# 这张表只回答「用哪个身份打开哪一页」。切换时逐条对过账：口径里的 22 条路径 = 表内 21 条
# + 表缺登记补偿 1 条（'/'），所以切换前后扫描集**逐条相同**（差集空）。
AUDIT_ROUTES = [
    # (角色, 路径)
    ('guest', '/'), ('guest', '/programs'), ('guest', '/admissions'),
    ('guest', '/help'), ('guest', '/login'), ('guest', '/register'),
    # 2026-10-04（第 97 轮）：补**公开站**页面 —— 此前只扫了 /、/programs、/admissions、
    #   /help、/login、/register 六个 guest 页，而 /about、/contactus、/alumni、/apply、
    #   /journal 都没扫过。这五个是**外部访客**（招生季的家长/学生）第一眼看到的页面，
    #   而「外部访客」就在校长定的优先序里 ⇒ 值得进扫描集。
    ('guest', '/about'), ('guest', '/contactus'), ('guest', '/alumni'),
    ('guest', '/apply'), ('guest', '/journal'),
    ('student', '/my/home'), ('student', '/my/apps'), ('student', '/my/study'),
    # 2026-10-03（第 108 轮）补：/grade-book 的**学生**视角此前不在扫描集里（作者登记为缺口）。
    #   教务在该 URL 上渲染的是录入网格（同源于 /grade-entry），学生才是原成绩簿 ⇒ 这一条补的是学生侧。
    ('student', '/grade-book'),
    ('student', '/my/fees'), ('student', '/my/time_off'),
    ('student', '/student/timetable'), ('student', '/my/messages'),
    ('student', '/downloads'),
    ('faculty', '/my/home'), ('faculty', '/attendance/take'),
    ('faculty', '/grading/entry'), ('faculty', '/assignment/manage'),
    ('faculty', '/leave/approvals'), ('faculty', '/notice/publish'),
    ('parent', '/my/home'), ('parent', '/my/child'),
    ('parent', '/my/fees'), ('parent', '/my/messages'),
    ('backoffice', '/my/home'), ('backoffice', '/ledger'),
    ('backoffice', '/edu/audit'), ('backoffice', '/downloads'),
    # ---- 测评门户（2026-09-29 补；队长指派：edu_assess 的门户页此前只登记 route_matrix/english）----
    # 为什么必须补：edu_assess 新增的 <th scope="rowgroup" rowspan=N>（评分项表的行分组）此前
    # 只由该组自带的 axe 脚本覆盖，**没进站点门禁**。四条都是**静态可探**的页面，各定一个取样身份。
    # ⚠ 只把条目写进 tests/ui/surface.json 的 gates **不等于**被扫：本门禁的扫描面是
    #   「表里 gates 含 accessibility」∩「有可用的取样身份」，身份与路径的对应口径留在本脚本（见 docstring §4）；
    #   而带 <int:...> 的 /assess/*（fill / grade / task/<id>/results / templates/<id> …）在表里是
    #   dyn 行、**不可裸探**（裸探到的是 404），它们的覆盖语义是「经上级继承」—— 别当成已扫页面。
    ('student', '/assess'), ('student', '/assess/my'),
    ('faculty', '/assess/review'), ('faculty', '/assess/faculty/history'),
    # ---- 2026-09-29 补「身份 × 页面」缺口（实测：扫到的渲染路径 ≠ 用户看到的渲染路径）----
    # ⚠ 为什么补：本门禁的判据是「身份 × 路径」，而 /assess 原先**只有 student 一个身份**。
    #   但 /assess 的「整班打分」卡片挂在 can_grade = _is_school_admin() or _is_teacher()
    #   （edu_assess/controllers/portal.py 的 assess_home；卡片片段见 views/assess_portal.xml 的
    #   edu_assess_home）—— **学生身份结构上看不到这张卡** ⇒ 它的整条渲染路径（卡片 HTML +
    #   「进入整班打分」按钮 + 空态两句 + 计数）从未进过站点门禁，只有该组自带的
    #   tests/smoke/assess_home_grade_entry.py 扫过（那不是站点门禁，不进本站点门禁的页数读数）。
    #   /assess/review 同样只取了 faculty，而它的门禁是 教务组·系统组 ∪ 教师组
    #   （edu_assess/controllers/portal.py 的 assess_review）⇒ 教务那条渲染分支也没样本。
    #   补法 = 同一路径多取一个身份（门户页的取样口径本来就是「一页可多身份」，见 docstring §4）。
    ('backoffice', '/assess'), ('faculty', '/assess'),
    ('backoffice', '/assess/review'),
    # ---- 2026-09-29 补 /registrar/curriculum（教务天天用的课程编排页）----
    # ⚠ 为什么补：该页在 tests/ui/surface.json 里原为 gates=[] / status=gap ⇒ **三张 UI 门禁
    #   没有一张扫它**，它写的任何无障碍问题都无人发现（本仓刚有一条 carve-out 让紫胶囊活了几个月）。
    #   本轮同步把它登记进 surface.json（只加 accessibility），身份取 backoffice
    #   —— 路由 auth='user' + privileged_staff() 门禁（非教务 303 /my/home），
    #   本脚本有会话的身份里只有 backoffice 是教务。
    #   ⚠ 裸路径就够：控制器 EnrollCurriculum 在**未带 course_id 时默认落在第一个有科目清单的
    #   专业**（edu_portal/controllers/enroll.py 的 EduCurriculumPortal.curriculum，无参分支），
    #   所以不用挂 ?course_id=<id> —— 挂上反而会让取样路径与 tests/ui/surface.json 的登记路径
    #   对不上账（build_samples 按字面路径比对 ⇒ 会被当成「口径里有、表里没有」而不扫）。
    ('backoffice', '/registrar/curriculum'),
    # ---- 后台 Web 客户端（2026-09-28 起；补的正是「只在后台出现」的那类元素）----
    # 为什么必须补：扫描面原先**全是门户/公开页**（29 条路径零后台页）。于是
    # .oe_topbar_name（公司名）这类元素**永远无人覆盖** —— 它是 90% 白压我们品牌蓝
    # 只有 4.372 ✗（AA 需 4.5），而它只在后台导航栏出现，门户页上根本不存在。
    # 身份用 backoffice（教务处，内部用户；本脚本无 admin 会话，见 LOGIN_ROLES）。
    #
    # 2026-09-29 扩覆盖：上一轮只验了 2 页，其余模型的列表/表单页**逐页没验过** ⇒ 本轮补到 7 页，
    # 按**视图形态**取代表（每条的实测渲染形态见下方 BACKEND_EXPECT_VIEW 的登记值，采集时刻与
    # 复跑命令见 tests/smoke/UX_V3_GATE.md §12；形态断言会把「样本悄悄变成另一页」判成 INCOMPLETE）：
    #   · 列表 list    /odoo/contacts            核心 res.partner（80 行 / 81 选择框，最稳）
    #                 /odoo/batches             自研 op.batch（17 行 / 35 选择框）+ 应用内区段导航
    #                 /odoo/grade-configuration 另一个应用（时间表/考试）的**配置分区**，
    #                                           区段形态最复杂（6 个扁平 menuitem + 8 个下拉按钮）
    #   · 看板 kanban  /odoo/students            自研应用根 op.student（14 卡）+ 区段导航
    #                 /odoo/apps                核心 ir.module.module（73 卡带图标）**无区段**，与上一行成对照
    #   · 表单 form    /odoo/contacts/1          核心 res.partner 记录表单（无区段）
    #                 /odoo/students/5          自研 op.student 记录表单（有区段）
    #   · 设置 settings **本栈无可用样本 ⇒ 如实登记为覆盖缺口，不拿别的页冒名顶替**：
    #                 /odoo/settings 在 backoffice 下是 Access Error（res.config.settings 只放行
    #                 「角色 / 管理员」），在 admin 下是 HTTP 200 + 整页 RPC 500：
    #                 Field res.config.settings.edu_apply_deadline must have type
    #                 'boolean','integer','float','char','selection','many2one' or 'datetime'
    #                 （抛点 base/models/res_config.py 的 _get_classified_fields，经 default_get ⇒ onchange）。
    #                 即**任何人**都打不开设置页；已上报队长另派专人修。修好之前不登记本页 ——
    #                 登记它只会得到「200 + 错误弹窗」的假覆盖（BACKEND_EXPECT_VIEW 里刻意没有它）。
    ('backoffice', '/odoo/contacts'), ('backoffice', '/odoo/students'),
    ('backoffice', '/odoo/batches'), ('backoffice', '/odoo/apps'),
    ('backoffice', '/odoo/contacts/1'), ('backoffice', '/odoo/students/5'),
    ('backoffice', '/odoo/grade-configuration'),
]

# ---------------------------------------------------------------- 后台页专属判据（2026-09-28 新增）
# 背景（实测，见本轮报告）：把后台页纳入扫描后，同一次 axe 运行会同时扫到**两种东西**：
#   ① 我们自己拥有的**共享外壳**（.o_navbar 及其内容）：导航栏底色 = --brand-action、
#      条目字色 = --NavBar-entry-color/--NavBar-brand-color（backend_b11.css 管这两档）
#      —— 「紫胶囊」「4.372 白字」这一族缺陷全在这里，**零容忍**；
#   ② Odoo 核心渲染的页面主体与核心 ARIA 结构（role=menu 的子节点、role=img 的活动图标、
#      后端 layout 的 meta viewport / html[lang]、列表视图里的 checkbox 标签…）——
#      不在本仓可改范围（要改得动核心模板/JS），但**绝不静默**：逐条打印 + 规则级漂移报警。
# 三条纪律（对应「不许加豁免伪造绿色」）：
#   · 判据只收**外壳里的 color-contrast** + 本地对比度检查（下面 SHELL_CONTRAST_RULE）；
#   · 核心里**出现新规则**（不在 CORE_RULES_KNOWN 里的 axe 规则 id）⇒ **当场判红**（不是豁免）；
#   · 每次跑都把两份清单逐条打出来，读数落 JSON —— 看不到的例外才算豁免，这里没有。
SHELL_SELECTOR = '.o_navbar'      # 后台共享外壳：<header class="o_navbar">（nav.o_main_navbar 是它的子）
BACKEND_PREFIXES = ('/odoo', '/web')   # Odoo 19 后台挂载前缀（/odoo 为主；/web 为兼容别名）

# 外壳里**已知且不属于本仓可改范围**的 axe 规则（核心 ARIA 结构）。任一**其余**规则在外壳里
# 出现 ⇒ 计入判据并判红 —— 这条让「外壳里长出新东西」不可能被静默吞掉。
SHELL_RULES_KNOWN = ('aria-required-children', 'aria-required-parent')
# 后台页**整页**已登记的核心规则（读数，不是豁免）：出现未登记规则 ⇒ 计入判据并判红。
CORE_RULES_KNOWN = ('aria-allowed-attr', 'aria-required-children', 'aria-required-parent',
                    'button-name', 'color-contrast', 'html-has-lang', 'label',
                    'meta-viewport', 'role-img-alt')
SHELL_RULES_ALWAYS_GATED = ('color-contrast',)   # 外壳里的对比度问题**永远**判红（不看白名单）
SHELL_CONTRAST_RULE = 'shell-contrast'           # 本地对比度检查（补 axe 的结构盲区，见下）
BACKEND_NEW_RULE = 'backend-rule-drift'          # 出现未登记规则

# 后台样本的**形态断言**（2026-09-29 扩覆盖时加）—— 为什么必须有：
#   带记录 id 的样本（/odoo/students/5）一旦那条记录被删掉或换了 id，URL **仍然返回 200**，
#   只是**静默回落成默认视图**（实测：/odoo/students/1 不存在 ⇒ 渲染 kanban 而不是 form）。
#   那一刻门禁量到的已经不是登记的那一页，而读数会显示「0 违规 / 在基线内」——
#   这正是本项目最忌讳的假绿形态：**覆盖悄悄变成另一页，门禁还说绿**。
#   故：登记了后台样本 ⇒ 必须同时登记**预期形态**；渲染形态不符 ⇒ 按未扫到处理（exit 3 INCOMPLETE），
#   与「外壳量不到」同一条纪律（绝不当作零违规通过）。
# ⚠ 这张表**故意没有 /odoo/settings**：它在本栈整页打不开（见 AUDIT_ROUTES 注释），
#   与其登记一个只会得到「200 + 错误弹窗」的假覆盖，不如空着并在报告里写明缺哪一类形态。
BACKEND_VIEW_KEYS = ('list', 'kanban', 'form', 'settings')
BACKEND_EXPECT_VIEW = {
    '/odoo/contacts': 'list', '/odoo/batches': 'list', '/odoo/grade-configuration': 'list',
    '/odoo/students': 'kanban', '/odoo/apps': 'kanban',
    '/odoo/contacts/1': 'form', '/odoo/students/5': 'form',
}


def backend_view_ok(path, views):
    """后台样本形态断言 → (是否命中预期, 人话说明)。

    · 未登记形态预期的页 ⇒ (True, ...)：这是对**已登记样本**的加强，不给别的页加门槛；
    · views 为 None（探针没回来）⇒ 判不通过（量不到的样本不许算通过）；
    · 命中判据是「预期形态的根在选择器里存在」（有的页会同时挂 form + kanban，属实况，不算错）。
    """
    want = BACKEND_EXPECT_VIEW.get(path)
    if not want:
        return True, '未登记形态预期'
    if views is None:
        return False, '量不到视图根'
    got = [k for k in BACKEND_VIEW_KEYS if views.get(k)]
    if views.get(want):
        return True, '形态=%s' % want
    return False, '预期 %s，实际 %s' % (want, '/'.join(got) or '（无视图根）')

# 本地对比度检查为什么必须有（本轮查实的**机制性**盲区）：
#   axe 的 color-contrast 匹配函数开头有一行 isDisabled/isInert 短路返回 false
#   （axe-core 4.10.2 lib/rules/color-contrast-matches.js），而 isDisabled 会**向上继承**
#   （lib/commons/forms/is-disabled.js：非表单元素走 virtualNode.parent 递归）。
#   本库只有一个公司 ⇒ Odoo 把「公司切换器」按钮渲染成 button[disabled] ⇒
#   它里面的 span.oe_topbar_name.d-none.d-lg-block.text-truncate（永约学坊）
#   **结构上永远扫不到**（实测：把同款 span 克隆进 .o_menu_systray 立刻被判 4.36 违规；
#   放在原按钮里则 violations/incomplete/passes 三处皆无）。
#   而 WCAG 1.4.3 对 disabled 控件是豁免的，所以这不是 axe 的 bug，是**我们的覆盖盲区**。
#   ⇒ 这里自己按「文字色（含 α 合成）vs 有效底色的对比度」逐条实算，**不跳过 disabled**，
#     读数落 JSON，逐条可复核。
SHELL_TEXT_JS = r'''
() => {
  const SHELL = '.o_navbar';
  const shell = document.querySelector(SHELL);
  if (!shell) return {missing: true, rows: []};
  const parse = (c) => { const m = c.match(/rgba?[(]([^)]+)[)]/); if (!m) return null;
    const p = m[1].split(',').map(parseFloat);
    return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const over = (fg, bg) => ({r: fg.r * fg.a + bg.r * (1 - fg.a),
                             g: fg.g * fg.a + bg.g * (1 - fg.a),
                             b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1});
  const effBg = (el) => { const st = []; let c = el, complex = false;
    while (c) { const cs = getComputedStyle(c);
      const bgi = cs.backgroundImage;
      if (bgi && bgi !== 'none') complex = true;
      const bg = parse(cs.backgroundColor); if (bg && bg.a > 0) st.push(bg); c = c.parentElement; }
    let o = {r: 255, g: 255, b: 255, a: 1};
    for (let i = st.length - 1; i >= 0; i--) o = over(st[i], o);
    return {rgb: o, complex: complex}; };
  const ownText = (el) => { let t = ''; el.childNodes.forEach(n => { if (n.nodeType === 3) t += n.textContent; });
    return t.trim(); };
  const inDisabled = (el) => { let c = el;
    while (c) { if (c.disabled === true) return true;
      if (c.getAttribute && c.getAttribute('aria-disabled') === 'true') return true; c = c.parentElement; }
    return false; };
  const rows = [];
  shell.querySelectorAll('*').forEach(el => {
    const text = ownText(el);
    if (!text) return;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const fg = parse(cs.color);
    const bg = effBg(el);
    rows.push({
      sel: el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).trim().replace(/[/]s+/g, '.') : ''),
      text: text.slice(0, 24),
      color: fg ? [fg.r, fg.g, fg.b, fg.a] : null,
      bg: [bg.rgb.r, bg.rgb.g, bg.rgb.b],
      bg_complex: bg.complex,
      size: parseFloat(cs.fontSize),
      weight: parseInt(cs.fontWeight, 10) || 400,
      rect: [r.width, r.height],
      visible: (r.width > 0 && r.height > 0) && cs.visibility !== 'hidden'
               && cs.display !== 'none' && parseFloat(cs.opacity) > 0,
      disabled_control: inDisabled(el),
    });
  });
  return {missing: false, rows: rows};
}
'''
def is_backend_path(path):
    """后台 Web 客户端路径（/odoo/*；/web 是兼容别名）。纯函数，可离线自证。"""
    p = (path or '').strip()
    return any(p == pre or p.startswith(pre + '/') for pre in BACKEND_PREFIXES)


def _srgb(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb):
    return 0.2126 * _srgb(rgb[0]) + 0.7152 * _srgb(rgb[1]) + 0.0722 * _srgb(rgb[2])


def composite(fg_rgba, bg_rgb):
    """α 合成：前景（可半透明）压在底色上 → 实际看到的颜色。"""
    a = fg_rgba[3] if len(fg_rgba) > 3 else 1.0
    return [fg_rgba[i] * a + bg_rgb[i] * (1 - a) for i in range(3)]


def contrast_ratio(fg_rgb, bg_rgb):
    la, lb = relative_luminance(fg_rgb), relative_luminance(bg_rgb)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def needs_large_ratio(size_px, weight):
    """WCAG：大字（>=24px，或 >=18.66px 且粗体）按 3:1，其余 4.5:1。"""
    return 3.0 if (size_px >= 24 or (size_px >= 18.66 and weight >= 700)) else 4.5


def shell_contrast_violations(rows):
    """外壳文字行 → 违规清单（本地检查，**不看 disabled**）。返回 (violations, skipped)。

    跳过 != 豁免：每一类跳过都**计数并打印**（不可测的复杂底 / 不可见 / 无颜色）。
    """
    bad, skipped = [], {'invisible': 0, 'complex_bg': 0, 'no_color': 0}
    for row in rows or []:
        if not row.get('visible'):
            skipped['invisible'] += 1
            continue
        if row.get('bg_complex'):
            skipped['complex_bg'] += 1
            continue
        if not row.get('color'):
            skipped['no_color'] += 1
            continue
        if row['color'][3] == 0:
            skipped['invisible'] += 1
            continue
        bg = row['bg']
        fg = composite(row['color'], bg)
        need = needs_large_ratio(row.get('size') or 0, row.get('weight') or 400)
        got = round(contrast_ratio(fg, bg), 3)
        if got < need:
            bad.append({'rule': SHELL_CONTRAST_RULE, 'impact': 'serious',
                        'sel': row.get('sel') or '(unknown)', 'text': row.get('text') or '',
                        'ratio': got, 'need': need,
                        'color': 'rgba(%s)' % ','.join(str(round(v, 3)) for v in row['color']),
                        'bg': 'rgb(%d,%d,%d)' % (round(bg[0]), round(bg[1]), round(bg[2])),
                        'disabled_control': bool(row.get('disabled_control'))})
    return bad, skipped


def axe_rule_ids(violations):
    return sorted(set(v['id'] for v in (violations or [])))

# ---------------------------------------------------------------- 名单来源（B 组 2026-09-26 切换）
# **单一来源** = tests/ui/surface.json（登记表，A 组维护）：gates 含 accessibility 的条目就是本门禁
# 的扫描面；AUDIT_ROUTES 只是「身份 × 路径」的取样口径。
# 两条纪律（与 check_ui_surface / ux_v3_route_matrix 同款）：
#   ① 表读不到 ⇒ 退出码 3 = INCOMPLETE（**不判 FAIL、不崩栈、不退回写死名单** —— 那等于把刚拆掉的
#      第二份名单重新长出来）；
#   ② 口径里有、表里没有 ⇒ 只有写进 SURFACE_MISSING（逐条写明为什么表里没有）才扫，其余**不扫并
#      点名**（登记方口径优先：例 scope=retired 的 edu_telegram 路由 —— 生产上不存在，扫它=假读数）。
SURFACE = 'tests/ui/surface.json'
SURFACE_GATE = 'accessibility'
LOGIN_ROLES = ('student', 'faculty', 'parent', 'backoffice')   # 本脚本有会话的角色（无 admin/anon 账号）
# 表缺登记的补偿：**唯一一处手写名单**，每条都要写清为什么表里没有它；补进表后应当删空。
# 2026-09-28（B 组）：**已删空** —— 唯一那条 '/' 已补进表（key=root、gates 含 accessibility）。
#   删后 --list 实测：取样仍是 28 页（去重路径 22）＝ 口径 28，对账
#   「取样口径路径 − 表 = 空 ｜ 表 − 取样集 = 空」，guest / 照旧在扫描名单里
#   （'/' 由表行进入）：覆盖没有变小。留空 dict = 保留这处「表缺登记时必须写理由」的显式落点。
SURFACE_MISSING = {}
DYN_SEG_RE = re.compile(r'(/<[^>]+>)+$')


SURFACE_USED = None      # load_surface() 解析出的实际路径（--surface 覆盖时与常量不同；打印用）


def find_surface(override=None):
    """找登记表：--surface 覆盖 ＞ 从脚本目录**向上**找（不靠 cwd）；找不到返回 None。"""
    if override:
        return override if os.path.isfile(override) else None
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        cand = os.path.join(d, 'tests', 'ui', 'surface.json')
        if os.path.isfile(cand):
            return cand
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    cand = os.path.abspath(SURFACE)
    return cand if os.path.isfile(cand) else None


def surface_fp(path):
    """登记表指纹（内容 md5 前 8 位）—— 让读数能对上「跑的是哪一版表」。"""
    with open(path, 'rb') as fh:
        return hashlib.md5(fh.read()).hexdigest()[:8]


def static_ancestors(path):
    """参数化路由的静态上级候选（长 → 短）：剥尾部动态段 + 逐段上溯。

    与 E 组 check_ui_surface._covered_parent 同口径（按**段边界**，'/my' 不会吞掉 '/my-library'）。
    """
    out = []

    def push(v):
        v = DYN_SEG_RE.sub('', v)
        if v and v != '/' and v not in out:      # '/' 本身不算上级（它是根，不是某一页的上级）
            out.append(v)

    cur = path
    push(cur)
    while '/' in cur[1:]:
        cur = cur.rsplit('/', 1)[0]
        push(cur)
    return out


def load_surface(gate=SURFACE_GATE, path=None):
    """读登记表 → (static, dyn, fp, err)。

    static = [(path, roles:set, scope)]：**静态可探**登记（保表序）；
    dyn    = [(path, 上级候选 list)]：带 <参数> 的登记 —— 不能裸探（探 '/x/<int:id>' 只会拿 404），
             表侧 evidence 也写明「非直探本页，覆盖经上级继承」；
    err    = 读不到 / 解析失败的人话原因（调用方判 INCOMPLETE）。
    """
    global SURFACE_USED
    path = find_surface(path)
    if not path:
        return None, None, None, '文件不存在（%s）' % SURFACE
    SURFACE_USED = path
    try:
        with open(path, encoding='utf-8') as fh:
            doc = json.load(fh)
        pages = doc['pages']
        if not isinstance(pages, list):
            raise ValueError('pages 不是列表')
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return None, None, None, '读不出 / 解析失败（%s: %s）' % (SURFACE, exc)
    static, dyn = [], []
    for rec in pages:
        if not isinstance(rec, dict):
            continue
        p = (rec.get('path') or '').strip()
        if not p or gate not in (rec.get('gates') or []):
            continue
        if '<' in p:
            dyn.append((p, static_ancestors(p)))
            continue
        static.append((p, set(rec.get('roles') or []), rec.get('scope') or ''))
    return static, dyn, surface_fp(path), None


def default_roles_for(roles, scope):
    """表新增路由的默认取样身份：**按登记 roles 取**（一页一样本 × 可见身份）+ 匿名侧 guest。

    与 check_english 的默认口径**故意不同**：那边是文案扫描（一个页面要在每个身份的变体上都扫，
    所以 portal 页四角色全扫）；这边是 axe 取样（每页一个代表身份就够，表 roles 就是「谁能看」）。
    · roles 含 'anon' 或 scope='public' → 加 guest（匿名侧）；
    · 其余按登记 roles 里**有会话的**身份取样；
    · 与脚本会话无交集（如只有 admin）⇒ 交回空集，调用方点名（不静默少扫）。
    """
    out = set()
    if 'anon' in roles or scope == 'public':
        out.add('guest')
    for r in roles:
        if r in LOGIN_ROLES:
            out.add(r)
    return out


def build_samples(static, dyn, policy=None):
    """表 → 取样集（policy 默认 = 模块级 AUDIT_ROUTES；可注入以便自证）。返回 (samples, dropped, added, dyn_rows, notes)。

    · samples = [(role, path, src)]：**真会跑的取样**（src = '口径' / '表新增' / '表缺登记补偿'）；
    · dropped = 口径里有、但表里没有且不在补偿清单内的路径（**不扫并点名**，登记方口径优先）；
    · added   = 表里有、口径里没有的静态登记（按 default_roles_for 取样；这才是「新页面不再落空」）；
    · dyn_rows= [(path, 上级 or '')]：参数化登记，核对上级是否真在取样面内。
    """
    policy = list(AUDIT_ROUTES if policy is None else policy)
    table_paths = set(p for p, _r, _s in static)
    covered = set(p for _role, p in policy)
    samples, dropped, added, notes, uncovered = [], [], [], [], []
    for role, path in policy:
        if path in table_paths or path in SURFACE_MISSING:
            samples.append((role, path, '口径'))
        else:
            dropped.append(path)
    for path in sorted(set(SURFACE_MISSING) - table_paths):
        for role in sorted(default_roles_for({'anon'}, 'public')) or ['guest']:
            if not any(p == path for _rl, p, _s in samples):
                samples.append((role, path, '表缺登记补偿'))
    for path, roles, scope in static:
        if path in covered:
            continue
        want = sorted(default_roles_for(roles, scope)) or []
        if not want:
            # ⚠ 这不是"备注"，是**覆盖缺口**：表说这一页要扫 accessibility，而脚本没有能打开它的
            #   会话身份（例如只登记 roles=['admin']）⇒ 该页永远不会被扫。把它当 INCOMPLETE
            #   （exit 3）而不是一行 note —— 「登记了却没人扫」正是本轮要治的那类假绿。
            notes.append('表新增登记 %s 无可用取样身份（roles=%s）—— 需要人工决定口径'
                         % (path, ','.join(sorted(roles)) or '(空)'))
            uncovered.append((path, ','.join(sorted(roles)) or '(空)'))
            continue
        for role in want:
            samples.append((role, path, '表新增'))
        added.append(path)
    ref_paths = set(p for _rl, p, _s in samples) | set(p for p, _c in dyn)
    dyn_rows = [(p, next((c for c in cands if c in ref_paths), '')) for p, cands in dyn]
    return samples, sorted(set(dropped)), added, dyn_rows, notes, uncovered


def print_coverage(fp, static, dyn_rows, samples, dropped, added, notes, title='名单来源',
                   uncovered=()):
    """打印「名单从哪来 / 取样了什么 / 两处不一致」——每次跑都打，防止名单悄悄漂移。"""
    table_paths = set(p for p, _r, _s in static)
    by_src = {}
    for _role, _path, src in samples:
        by_src[src] = by_src.get(src, 0) + 1
    print('== %s ==' % title)
    print('  %s（指纹 %s）· gates=accessibility 登记 %d 条 = 静态 %d + 参数化 %d'
          % (SURFACE_USED or SURFACE, fp, len(static) + len(dyn_rows), len(static), len(dyn_rows)))
    print('  本轮取样 %d 页（去重路径 %d）＝ %s'
          % (len(samples), len(set(p for _r, p, _s in samples)),
             ' + '.join('%s %d' % (k, v) for k, v in sorted(by_src.items()))))
    print('  对账：取样口径路径 − 表 = %s ｜ 表 − 取样集 = %s'
          % ('、'.join(sorted(set(p for _r, p, _s in samples) - table_paths)) or '（空）',
             '、'.join(sorted(table_paths - set(p for _r, p, _s in samples))) or '（空）'))
    if dropped:
        print('  ⚠ 口径里有、表里没有且未登记补偿 %d 条 ⇒ **不扫**（登记方口径优先，'
              '例如 scope=retired 的退役路由）：%s' % (len(dropped), '、'.join(dropped)))
    if added:
        print('  ⚠ 表新增登记 %d 条（脚本口径未收录，按 scope/roles 默认取样）：%s'
              % (len(added), '、'.join(added)))
    if uncovered:
        print('  ✗ **覆盖缺口 %d 条**：表登记了 accessibility、但本脚本没有能打开它的会话身份'
              '（该页永远不会被扫）⇒ 按 INCOMPLETE 处理（exit 3）：%s'
              % (len(uncovered), '、'.join('%s（roles=%s）' % u for u in uncovered)))
    nodyn = [p for p, par in dyn_rows if not par]
    if dyn_rows:
        print('  参数化 %d 条：静态上级在取样面内 %d 条%s'
              % (len(dyn_rows), len(dyn_rows) - len(nodyn),
                 '' if not nodyn else '｜⚠ 无上级 %d 条（覆盖缺口）：%s'
                 % (len(nodyn), '、'.join(nodyn))))
    empty = [p for p, _r, _s in static if not (set(_r) & set(LOGIN_ROLES)) and 'anon' not in _r]
    if empty:
        print('  ⚠ 表 roles 与本脚本会话无交集 %d 条（取样会落到 guest；如需覆盖请登记角色或补账号）：%s'
              % (len(empty), '、'.join(sorted(empty)[:8])))
    for n in notes:
        print('  note：%s' % n)


def print_list(static, dyn_rows, samples, dropped, added, notes, fp, uncovered=()):
    """--list：**只读**打印名单与对账（不连站点、不起浏览器）；TAG 前缀供对账脚本取用。"""
    print_coverage(fp, static, dyn_rows, samples, dropped, added, notes, title='名单（只读打印）',
                   uncovered=uncovered)
    print('-- 取样集（角色 × 路径）--')
    for role, path, src in samples:
        print('[SAMPLE] %-11s %-32s %s' % (role, path, src))
    print('-- 表登记（静态）--')
    for path, roles, scope in static:
        print('[TABLE] %-32s roles=%-40s scope=%s' % (path, ','.join(sorted(roles)) or '(空)', scope))
    print('-- 表缺登记补偿（本门禁仍在扫）--')
    for p, why in sorted(SURFACE_MISSING.items()):
        print('[MISSING] %-30s %s' % (p, why))
    print('-- 参数化登记（不可裸探；登记语义 = 覆盖经上级继承）--')
    for p, par in dyn_rows:
        print('[DYN] %-36s 静态上级=%s' % (p, par or '⚠ 无（在取样面内找不到上级）'))
    print('== 退出码 0 = 名单读得到（--list 只打印，不判门禁）==')
    return 0


# 基线（2026-09-13 全站实测；存常量 ⇒ 漂移即报，机制同 t53/t96）
BASELINE = {
    # 2026-09-14 全站实测（**28/28 页** × axe 4.10.2；取样口径见 AUDIT_ROUTES；读数见报告 §27）。
    # 规则分布：color-contrast 649 / select-name 33 / button-name 25 / label 20 /
    #           image-alt 7 / link-in-text-block 3 / link-name 1。
    # **漂移即报**（与 t53/t96 同机制）；修复后应下调本常量。
    # 2026-09-14 t112 下调（**28/28 页**可比轮实测；指纹 71953d4b 改前=改后）：
    #   **color-contrast 已 0**（t111 令牌轮 + t112 残余收口）。剩余：
    #   select-name 33 / button-name 25 / label 20 / image-alt 7 = 85 critical
    #   + link-in-text-block 1 / link-name 1 = 2 serious（B/C 组，不在 A 组范围）。
    # 2026-09-14 t119 当轮下调（**28/28 页**可比轮实测 12:47:52；指纹 d1e9b15c）：
    #   B 组「表单可访问名」收口 —— **select-name 0 / label 0**（33 + 20 条清零）。
    #   剩余：button-name 25 / image-alt 7 = 32 critical + link-in-text-block 1 / link-name 1 = 2 serious。
    # 2026-09-14 t120 当轮下调到**最终值 0**（**28/28 页**可比轮实测 13:09:39；指纹 8ff6b22c）：
    #   C 组收尾 —— button-name / image-alt / link-name / link-in-text-block 全部清零；
    #   A 组 color-contrast 与 B 组 select-name/label 保持 0（无回退）。
    #   零余量 ⇒ 之后**任何一条**新违规都会立刻报警（这是要的）。
    'critical': 0,
    'serious': 0,
    'moderate': 0,
    'minor': 0,
    'total': 0,
    'pages': len(AUDIT_ROUTES),
}
IMPACT_ORDER = ('critical', 'serious', 'moderate', 'minor')


# ---------------------------------------------------------------- 工具
def login_session(login, pwd):
    s = requests.Session()
    s.trust_env = False
    try:
        s.post(BASE + '/web/session/authenticate',
               json={'jsonrpc': '2.0',
                     'params': {'db': DB, 'login': login, 'password': pwd}},
               timeout=25)
    except Exception:
        pass
    return s


def site_ready():
    """站点就绪探针。

    ⚠ 必须走同一个 Session 并 trust_env=False：否则环境里的 HTTP(S)_PROXY
    会把探针带到代理上 ⇒ 本地站点反而报“不可达”（归因错误）。
    """
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.get(BASE + '/web/login?db=' + DB, timeout=15, allow_redirects=False)
        return r.status_code in (200, 302, 303)
    except Exception:
        return False


def concurrency_note():
    """并发状态（四件套之一）：此刻是否有冒烟/门禁在跑。"""
    try:
        out = subprocess.run(['ps', '-ef'], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return 'unknown', []
    hits = [l.strip()[:90] for l in (out or '').splitlines()
            if (('tests/smoke/' in l) or ('scripts/check_' in l))
            and 'grep' not in l and 'check_accessibility' not in l]
    return ('busy' if hits else 'quiet'), hits


SELFTEST_BAD = """<!DOCTYPE html>
<html><head><title>bad</title></head><body>
  <img src="x.png">
  <form><input type="text" name="q"><button>OK</button></form>
  <div style="color:#8a8a8a;background:#ffffff;font-size:12px">低对比度文字</div>
  <a href="#"></a>
</body></html>"""

SELFTEST_GOOD = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>好页面</title></head><body>
  <main><h1>标题</h1>
  <img src="x.png" alt="示意图">
  <form><label for="q">关键词</label><input id="q" type="text" name="q">
    <button type="submit">提交</button></form>
  <p style="color:#111;background:#fff">正文</p>
  <a href="#main">跳到主内容</a></main>
</body></html>"""


def gated_to_violations(gated):
    """判据项（partition_backend 的产物）→ axe 形状，供 summarize / by_rule / 落盘复用。"""
    slots = {}
    for g in gated or []:
        slot = slots.setdefault(g['rule'], {'id': g['rule'], 'impact': g.get('impact') or 'minor',
                                            'help': g.get('where') or '', 'nodes': []})
        tgts = g.get('targets') or ['']
        for i in range(int(g.get('nodes') or 0)):
            node = {'target': [tgts[min(i, len(tgts) - 1)]]}
            if i == 0 and g.get('detail'):
                node['failureSummary'] = g['detail']
            slot['nodes'].append(node)
    return list(slots.values())


def first_targets(violation, limit=3):
    out = []
    for node in (violation.get('nodes') or [])[:limit]:
        tgt = node.get('target') or ['']
        out.append(tgt[0] if isinstance(tgt, list) else str(tgt))
    return out

def run_axe(page, source, target=None):
    """对当前页（或 data: URL）跑 axe → results 字典。"""
    page.add_script_tag(content=source)
    if target:
        page.goto(target, wait_until='domcontentloaded', timeout=45000)
        page.add_script_tag(content=source)
    return page.evaluate("async () => await axe.run(document, "
                         "{resultTypes:['violations'], runOnly:{type:'tag',"
                         "values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}})")


def summarize(results):
    """axe results → {impact: n}、规则明细。"""
    per_impact = {k: 0 for k in IMPACT_ORDER}
    rules = []
    for v in (results or {}).get('violations', []) or []:
        impact = v.get('impact') or 'minor'
        n = len(v.get('nodes') or [])
        per_impact[impact] = per_impact.get(impact, 0) + n
        rules.append({'id': v.get('id'), 'impact': impact, 'nodes': n,
                      'help': (v.get('help') or '')[:80],
                      'sample': ((v.get('nodes') or [{}])[0].get('target') or [''])[0]})
    return per_impact, rules


def selftest():
    """证明量具生效：必然违规页要红、正确页不报。"""
    from playwright.sync_api import sync_playwright
    ok = True
    emitted = 0

    # ---- 名单读取的纯函数（构造夹具断言：防「读取口径」悄悄漂移；不连站点、不读真实表）----
    for _label, _got, _want in (
            # 候选**含路径自身**（不以动态段结尾时），调用方按「在不在取样面内」过滤 ⇒ 自身自动出局
            ('static_ancestors(参数化子页)',
             static_ancestors('/my/child/<int:child_id>/leave'),
             ['/my/child/<int:child_id>/leave', '/my/child', '/my']),
            ('default_roles_for(public+anon)',
             sorted(default_roles_for({'anon'}, 'public')), ['guest']),
            ('default_roles_for(portal×2 身份)',
             sorted(default_roles_for({'student', 'faculty'}, 'portal')),
             ['faculty', 'student']),
            ('default_roles_for(仅 admin)',
             sorted(default_roles_for({'admin'}, 'other')), [])):
        good = (_got == _want)
        ok = ok and good
        emitted += 1
        print('  %s %-26s 期望 %s 实际 %s' % ('PASS' if good else 'FAIL', _label, _want, _got))
    # 表外口径剔除 + 表新增自动收录（这条纪律必须被证明：少扫几页不许静默）
    _st = [('/allowed', {'student'}, 'portal'), ('/newpage', {'parent'}, 'portal')]
    _sam, _dropped, _added, _dyn, _notes, _unc = build_samples(
        _st, [], policy=[('student', '/allowed'), ('student', '/retired-route')])
    _st2 = [('/allowed', {'student'}, 'portal'), ('/adminonly', {'admin'}, 'other')]
    _sam2, _d2, _a2, _dy2, _n2, _unc2 = build_samples(
        _st2, [], policy=[('student', '/allowed')])
    for _label, _got, _want in (
            ('表外口径剔除', _dropped, ['/retired-route']),
            ('表新增自动收录', _added, ['/newpage']),
            # ⚠ 覆盖缺口必须判 INCOMPLETE（不是一行 note 就放过）：登记了却没人扫 = 假绿的温床
            ('无取样身份⇒覆盖缺口', [p for p, _r in _unc2], ['/adminonly'])):
        good = (_got == _want)
        ok = ok and good
        emitted += 1
        print('  %s %-26s 期望 %s 实际 %s' % ('PASS' if good else 'FAIL', _label, _want, _got))
    good = '/retired-route' not in [p for _r, p, _s in _sam]
    ok = ok and good
    emitted += 1
    print('  %s %-26s 期望 %s 实际 %s'
          % ('PASS' if good else 'FAIL', '表外口径不扫', '不扫', '不扫' if good else '仍扫'))

    # ---- a3 新增（2026-09-28）：后台覆盖 = 对比度量具 + 后台判据 + 分流 ----
    # ① 对比度量具先证「数得准」：两个数就是本轮查实的实测档（品牌蓝底上的两种白）
    _brand = [12, 109, 215]
    _bad95 = composite([255, 255, 255, 0.9], _brand)
    for _label, _got, _want in (
            ('cc_white_on_brand', round(contrast_ratio([255, 255, 255], _brand), 3), 5.019),
            ('cc_90white_on_brand', round(contrast_ratio(_bad95, _brand), 3), 4.372),
            ('composite_90white_on_brand', [round(v, 1) for v in _bad95], [230.7, 240.4, 251.0]),
            ('is_backend(/odoo/contacts)', is_backend_path('/odoo/contacts'), True),
            ('is_backend(/my/home)', is_backend_path('/my/home'), False),
            ('large_ratio(24px)', needs_large_ratio(24, 400), 3.0),
            ('large_ratio(14px)', needs_large_ratio(14, 400), 4.5),
            ('shell_js_selector_matches_const', SHELL_SELECTOR in SHELL_TEXT_JS, True)):
        good = (_got == _want)
        ok = ok and good
        emitted += 1
        print('  %s %-34s 期望 %s 实际 %s' % ('PASS' if good else 'FAIL', _label, _want, _got))
    # ② 本地对比度检查：抓得住「disabled 控件里的白字」（axe 结构上扫不到的那类）
    _row_fail = {'sel': 'span.oe_topbar_name', 'text': '永约学坊', 'color': [255, 255, 255, 0.9],
                 'bg': _brand, 'size': 14, 'weight': 400, 'rect': [56, 46], 'visible': True,
                 'bg_complex': False, 'disabled_control': True}
    _row_pass = dict(_row_fail, color=[255, 255, 255, 1.0])
    _rows_skip = [dict(_row_fail, visible=False), dict(_row_fail, bg_complex=True)]
    _bad1, _skip1 = shell_contrast_violations([_row_fail])
    _bad2, _ = shell_contrast_violations([_row_pass])
    _bad3, _skip3 = shell_contrast_violations(_rows_skip)
    for _label, _got, _want in (
            ('shell_contrast_catches_disabled', [len(_bad1), (_bad1[0]['rule'] if _bad1 else ''),
                                                (_bad1[0]['disabled_control'] if _bad1 else None)],
             [1, SHELL_CONTRAST_RULE, True]),
            ('shell_contrast_passes_white', len(_bad2), 0),
            ('shell_contrast_counts_skips', [len(_bad3), _skip3['invisible'], _skip3['complex_bg']],
             [0, 1, 1])):
        good = (_got == _want)
        ok = ok and good
        emitted += 1
        print('  %s %-34s 期望 %s 实际 %s' % ('PASS' if good else 'FAIL', _label, _want, _got))
    # ③ 分流器：外壳的 color-contrast 进判据；已登记核心规则进清单；**未登记规则进判据**
    _gshell = [{'id': 'color-contrast', 'impact': 'serious',
                'nodes': [{'target': ['.o_menu_brand']}] * 4},
               {'id': 'aria-required-children', 'impact': 'critical',
                'nodes': [{'target': ['.o_menu_systray']}] * 2}]
    _gpage = [{'id': 'role-img-alt', 'impact': 'serious',
               'nodes': [{'target': ['i.fa']}] * 3},
              {'id': 'brand-new-rule', 'impact': 'critical', 'nodes': [{'target': ['x']}]}]
    _gated, _core, _notes, _lbad, _lskip = partition_backend(_gpage, _gshell, [_row_fail])
    _gv = gated_to_violations(_gated)
    for _label, _got, _want in (
            ('partition_gated_ids', sorted(x['rule'] for x in _gated),
             sorted(['color-contrast', 'brand-new-rule', SHELL_CONTRAST_RULE])),
            ('partition_core_nodes', sum(s['nodes'] for s in _core.values()), 5),
            ('gated_to_violations_nodes', sum(len(v['nodes']) for v in _gv), 6),
            ('partition_unregistered_note', len([n for n in _notes if '未登记' in n]), 1)):
        good = (_got == _want)
        ok = ok and good
        emitted += 1
        print('  %s %-34s 期望 %s 实际 %s' % ('PASS' if good else 'FAIL', _label, _want, _got))
    # ④ 后台样本**形态断言**（2026-09-29 a4 新增）：三态各证一次 ——
    #   命中（form 与 kanban 同时挂也算命中）+ **回落必须不命中**（这条才是加它的理由）
    #   + 未登记形态预期的页不受门槛；最后加一条不变式：每个后台样本都得登记预期形态。
    for _label, _got, _want in (
            ('view_assert_hit(形式共存)', backend_view_ok('/odoo/students/5', {'kanban': 1, 'form': 1})[0], True),
            ('view_assert_miss(回落视图)', backend_view_ok('/odoo/students/5', {'kanban': 1, 'form': 0})[0], False),
            ('view_assert_unregistered', backend_view_ok('/odoo/not-registered', {'list': 1})[0], True),
            ('view_assert_covers_all_backend',
             sorted(set(p for _r, p in AUDIT_ROUTES if is_backend_path(p)) - set(BACKEND_EXPECT_VIEW)), [])):
        good = (_got == _want)
        ok = ok and good
        emitted += 1
        print('  %s %-34s 期望 %s 实际 %s' % ('PASS' if good else 'FAIL', _label, _want, _got))
    # ⑤ 违规归属分流（2026-09-29 队长批准）：**按元素来源**判，不按规则名。
    #   双向各证一次：自研视图声明的按钮名 ⇒ 判据；核心里那个写死 id 的布尔单元格 ⇒ 只读数。
    _ours_v = {'id': 'button-name', 'impact': 'critical',
               'nodes': [{'elem_name': 'action_edu_stop', 'target': ['button'], 'elem_id': ''}]}
    _core_v = {'id': 'label', 'impact': 'critical',
               'nodes': [{'elem_name': '', 'target': ['input#boolean_checkbox'], 'elem_id': 'boolean_checkbox'}]}
    for _label, _got, _want in (
            ('provenance_ours_is_gated', page_core_or_gated('button-name', _ours_v)[0] is not None, True),
            ('provenance_core_is_readonly', page_core_or_gated('label', _core_v)[0] is None, True),
            ('provenance_button_set_from_repo',
             ['action_edu_stop' in custom_addon_buttons(),
              'action_edu_stop' in custom_addon_buttons()][0], True)):
        good = (_got == _want)
        ok = ok and good
        emitted += 1
        print('  %s %-34s 期望 %s 实际 %s' % ('PASS' if good else 'FAIL', _label, _want, _got))

    source, where = axe_source()
    print('== axe 来源：%s ==' % where)
    good = source is not None
    ok = ok and good
    emitted += 1
    print('  %s %-26s %s' % ('PASS' if good else 'FAIL', 'axe_available', where))
    if not good:
        print('== 自证 不通过（取不到 axe → ENV）== %s' % self_attest_line())
        return 2

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', headless=True,
                                     args=['--no-proxy-server'])
        page = browser.new_page()
        # ① 必然违规页 → 必须报
        page.goto('data:text/html;charset=utf-8,' + requests.utils.quote(SELFTEST_BAD),
                  wait_until='domcontentloaded', timeout=30000)
        bad_impact, bad_rules = summarize(run_axe(page, source))
        bad_total = sum(bad_impact.values())
        good = bad_total > 0
        ok = ok and good
        emitted += 1
        print('  %s %-26s 违规=%d 例=%s' % ('PASS' if good else 'FAIL',
                                            'bad_page_alarms', bad_total,
                                            [r['id'] for r in bad_rules][:4]))
        want_ids = ('image-alt', 'html-has-lang')
        got_ids = [r['id'] for r in bad_rules]
        good = any(w in got_ids for w in want_ids)
        ok = ok and good
        emitted += 1
        print('  %s %-26s 期望含 %s，实际 %s' % ('PASS' if good else 'FAIL',
                                                 'bad_page_rule_ids', want_ids,
                                                 got_ids[:5]))
        # ② 正确页 → 不应报（证明不是"什么都报"）
        page.goto('data:text/html;charset=utf-8,' + requests.utils.quote(SELFTEST_GOOD),
                  wait_until='domcontentloaded', timeout=30000)
        good_impact, good_rules = summarize(run_axe(page, source))
        good_total = sum(good_impact.values())
        good = (good_total == 0)
        ok = ok and good
        emitted += 1
        print('  %s %-26s 违规=%d%s' % ('PASS' if good else 'FAIL',
                                        'good_page_quiet', good_total,
                                        '' if good else ' 例=%s' % [r['id'] for r in good_rules][:3]))
        # ③ 分级函数
        for label, per, want in (
                ('summarize_impact_critical', {'critical': 2, 'minor': 1}, 2),
                ('summarize_total', {'critical': 2, 'minor': 1}, 3)):
            got = (per.get('critical', 0) if 'critical' in label else sum(per.values()))
            good = (got == want)
            ok = ok and good
            emitted += 1
            print('  %s %-26s 期望 %s 实际 %s' % ('PASS' if good else 'FAIL', label, want, got))
        # ④ 基线漂移判定（纯函数）
        for label, cur, base, want in (
                ('drift_up_detected', {'total': 3}, {'total': 1}, True),
                ('no_drift_when_equal', {'total': 1}, {'total': 1}, False),
                ('drift_ignored_when_baseline_zero', {'total': 0}, {'total': 0}, False)):
            got = baseline_drift(cur, base)
            good = (got == want)
            ok = ok and good
            emitted += 1
            print('  %s %-26s 期望 %s 实际 %s' % ('PASS' if good else 'FAIL', label, want, got))
        browser.close()

    drift = emitted != SELFTEST_CASES
    ok = ok and not drift
    print('  %s %-26s 实际 %d / 声明 %d%s'
          % ('PASS' if not drift else 'FAIL', 'selftest_cases', emitted, SELFTEST_CASES,
             '' if not drift else '（漂移：请同步 SELFTEST_CASES）'))
    print('== 自证 %s == %s' % ('通过' if ok else '不通过', self_attest_line()))
    return 0 if ok else 1


# 后台页一次取三样（同一次页面加载，避免重复导航）：
#   ① 页面主体 − 外壳 的 axe 违规（核心渲染清单，**不与外壳重复计数**：用 exclude 精确扣除）
#   ② 外壳（.o_navbar）自己的 axe 违规（判据主体）
#   ③ 外壳逐条文字行（本地对比度检查的原料；不跳 disabled —— 那是 axe 的结构盲区）
# 视图形态探测（与上面 BACKEND_EXPECT_VIEW 配套）：一次页面加载里数各视图根，不额外导航。
BACKEND_VIEW_JS = ("const vq = (s) => document.querySelectorAll(s).length;"
    "  const views = {list: vq('.o_list_view'), kanban: vq('.o_kanban_view'),"
    "                 form: vq('.o_form_view'), settings: vq('.o_settings_container')};")

# 逐节点带出 elem_name / elem_id：判「这条违规是谁的账」（自研视图 vs 核心渲染）要用它，见 partition_backend。
# ⚠ 写成常量并单独做语法自检（scripts/check_accessibility.py --selftest 会跑）：第一版手写进拼接串时
#   少了一个右括号，浏览器直接 SyntaxError ⇒ 全部门禁样本变 INCOMPLETE（exit 3）。
#   失败是响的（好），但白跑一轮；单独成串 + node 语法自检能挡住这类手滑。
BACKEND_MAPV_JS = (
    "const mapV = (vs) => (vs || []).map((v) => ({"
    "  id: v.id, impact: v.impact, help: v.help,"
    "  nodes: (v.nodes || []).map((n) => {"
    "    let el = null;"
    "    try { el = document.querySelector(n.target.join(' ')); } catch (e) { el = null; }"
    "    return {target: n.target, failureSummary: n.failureSummary,"
    "            elem_name: (el && el.getAttribute) ? (el.getAttribute('name') || '') : '',"
    "            elem_id: (el && el.id) ? el.id : ''};"
    "  }),"
    "}));")

BACKEND_PROBE_JS = ("async () => {"
    "  const opts = {resultTypes:['violations'], runOnly:{type:'tag', values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}};"
    "  " + BACKEND_VIEW_JS +
    # 逐节点带出 elem_name / elem_id：判「这条违规是谁的账」（自研视图 vs 核心渲染）要用它，见 partition_backend。
    "  " + BACKEND_MAPV_JS +
    "  " +
    "  const shell = document.querySelector('" + SHELL_SELECTOR + "');"
    "  const rect = shell ? shell.getBoundingClientRect() : null;"
    "  const laid_out = !!(rect && rect.width > 0 && rect.height > 0);"
    "  const pageRes = await axe.run({exclude: shell ? [shell] : []}, opts);"
    "  const shellRes = (shell && laid_out) ? await axe.run(shell, opts) : {violations: []};"
    "  const text = shell ? (" + SHELL_TEXT_JS + ")() : {missing: true, rows: []};"
    "  return {page: mapV(pageRes.violations), shell: mapV(shellRes.violations),"
    "          text: (text && text.rows) || [], shell_rect: rect ? [rect.width, rect.height] : null,"
    "          views: views,"
    "          shell_missing: !shell || !laid_out || !!text.missing};"
    "}")

# ---------------------------------------------------------------- 违规属于谁的账（2026-09-29 队长批准的分流）
# 背景（实测）：后台样本扩到 7 页后，核心清单里出现 button-name x17，全部来自
#   custom_addons/edu_portal/views/class_batch_views.xml 的
#   <button name="action_edu_stop" type="object" icon="fa-pause-circle-o" title="停用（…）"/>
#   —— **我们自己的视图**声明的按钮（核心只是把它画出来），却被按规则名归进了
#   「核心渲染·只读数」。本仓吃过一次这种豁免的亏（一条 carve-out 让一个紫胶囊活了几个月：
#   既没人修、也永远不再报警）⇒ 改判据：**按元素来源分流，不按规则名**。
# 判据必须机器可判定（人肉清单会腐烂）：名字集合从仓内 XML 直接扫出来，不连数据库、不随环境变化。
_CUSTOM_BUTTONS = None


def custom_addon_buttons(root=None):
    """custom_addons/**/*.xml 里声明过的 <button name="..."> 名字集合（进程内缓存）。

    只认 XML arch 里的 button name：列表行按钮的 name 会原样出现在渲染出的 <button name=...> 上，
    所以「元素的 name ∈ 这个集合」是可判定的来源信号。
    ⚠ 刻意**不**扫 <field name=...>：字段名（active / name / code…）在核心与自研视图里大量重名，
    拿它判来源会把核心的锅算到我们头上（正是上一版按规则名一刀切的反向错误）。
    """
    global _CUSTOM_BUTTONS
    if _CUSTOM_BUTTONS is None:
        root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        found = set()
        pat = re.compile(r'<button\b[^>]*?\bname="([^"]+)"', re.S)
        for dirpath, _dirs, files in os.walk(os.path.join(root, 'custom_addons')):
            for fn in files:
                if not fn.endswith('.xml'):
                    continue
                try:
                    with open(os.path.join(dirpath, fn), encoding='utf-8') as fh:
                        found.update(pat.findall(fh.read()))
                except (OSError, UnicodeDecodeError):
                    continue
        _CUSTOM_BUTTONS = found
    return _CUSTOM_BUTTONS


def page_core_or_gated(rid, v):
    """页面主体里的一条违规 → (判据条目 or None, 核心清单节点数, 归属说明)。

    · 规则不在 CORE_RULES_KNOWN ⇒ 原本就当判据（调用方处理）；
    · 规则在 CORE_RULES_KNOWN、但节点带**自研视图声明的 button name** ⇒ **判据**（我们的账）；
    · 其余 ⇒ 核心清单（只读数）。
    """
    nodes = v.get('nodes') or []
    ours = [n for n in nodes if (n.get('elem_name') or '') in custom_addon_buttons()]
    names = sorted(set(n.get('elem_name') for n in ours))
    if ours:
        g = {'rule': rid, 'impact': v.get('impact') or 'minor', 'nodes': len(ours),
             'where': '页面主体（**自研视图**声明）',
             'targets': [((n.get('target') or [''])[0] if isinstance(n.get('target'), list)
                          else n.get('target') or '') for n in ours][:4]}
        return g, len(nodes) - len(ours), names
    return None, len(nodes), []


def partition_backend(page_violations, shell_violations, text_rows):
    """后台页违规 → (判据项, 核心清单, 提示, 本地对比度违规, 跳过计数)。

    判据项（进 per_impact/by_rule ⇒ 参与基线漂移判定）：
      · 外壳里的 color-contrast —— **永零容忍**（这一族就是本仓品牌色造成的）；
      · 外壳里的**未登记**规则（不在 SHELL_RULES_KNOWN）—— 外壳长出新品类即判红；
      · 页面主体里的**未登记**规则（不在 CORE_RULES_KNOWN）—— 核心渲染出现新品类即判红；
      · 本地对比度检查（SHELL_CONTRAST_RULE）。
    核心清单（**只打印 + 落 JSON，不进判据**）：已登记的核心规则读数 —— 不是豁免：
      它们逐条印出来，且「出现新规则」会立刻变成判据项。
    """
    gated, core, notes = [], {}, []
    for v in shell_violations or []:
        rid, n = v.get('id'), len(v.get('nodes') or [])
        if rid in SHELL_RULES_ALWAYS_GATED or rid not in SHELL_RULES_KNOWN:
            gated.append({'rule': rid, 'impact': v.get('impact') or 'minor', 'nodes': n,
                          'where': '外壳(.o_navbar)', 'targets': first_targets(v)})
            if rid not in SHELL_RULES_ALWAYS_GATED:
                notes.append('⚠ 外壳出现**未登记**规则 %s（x%d）⇒ 计入判据' % (rid, n))
        else:
            slot = core.setdefault(rid, {'impact': v.get('impact'), 'nodes': 0, 'where': '外壳(核心结构)'})
            slot['nodes'] += n
    for v in page_violations or []:
        rid, n = v.get('id'), len(v.get('nodes') or [])
        if rid in CORE_RULES_KNOWN:
            # 分流：规则名只说明「这条规则在核心里很常见」，**不能**说明这条违规是谁的账。
            g, rest, names = page_core_or_gated(rid, v)
            if g:
                gated.append(g)
                notes.append('⚠ 规则 %s 命中**自研视图声明的按钮**（name=%s）⇒ 计入判据（不是核心渲染）'
                             % (rid, '/'.join(names[:3])))
            if rest:
                slot = core.setdefault(rid, {'impact': v.get('impact'), 'nodes': 0,
                                             'where': '页面主体(核心渲染)'})
                slot['nodes'] += rest
        else:
            gated.append({'rule': rid, 'impact': v.get('impact') or 'minor', 'nodes': n,
                          'where': '页面主体', 'targets': first_targets(v)})
            notes.append('⚠ 后台页出现**未登记**规则 %s（x%d）⇒ 计入判据' % (rid, n))
    bad, skipped = shell_contrast_violations(text_rows)
    for item in bad:
        gated.append({'rule': item['rule'], 'impact': item['impact'], 'nodes': 1,
                      'where': '外壳本地对比度', 'targets': [item['sel']],
                      'detail': '%s %s 压 %s = %.3f < %s%s'
                                % (item['text'], item['color'], item['bg'], item['ratio'], item['need'],
                                   '（在 disabled 控件内：axe 扫不到，本地检查兜住）'
                                   if item['disabled_control'] else '')})
    return gated, core, notes, bad, skipped

def baseline_drift(cur, base):
    """当前 > 基线 ⇒ 漂移（True）；≤ 基线 ⇒ False。"""
    return int(cur.get('total', 0)) > int(base.get('total', 0))


def audit(json_out=None, quiet=False, plan=None):
    from playwright.sync_api import sync_playwright
    plan = plan or {}
    samples = plan.get('samples') or []
    conc, procs = concurrency_note()
    print('== 全站 axe 审计 ==  并发状态=%s%s' % (conc, ('（%d 个）' % len(procs)) if procs else ''))
    if not site_ready():
        print('ENV：站点不可达（%s）—— 本轮作废' % BASE)
        return 2
    source, where = axe_source()
    if source is None:
        print('ENV：axe-core 取不到（%s）' % where)
        return 2
    print('== axe 来源：%s ==' % where)
    print_coverage(plan.get('fp'), plan.get('static') or [], plan.get('dyn_rows') or [],
                   samples, plan.get('dropped') or [], plan.get('added') or [],
                   plan.get('notes') or [], title='全站 axe 审计',
                   uncovered=plan.get('uncovered') or ())
    print('== 取样口径：%d 页（**不在此写死分项**，逐条清单见上方「取样集」与 AUDIT_ROUTES）=='
          % len(samples))

    per_impact = {k: 0 for k in IMPACT_ORDER}
    by_rule = {}
    core_all = {}          # 后台页「核心渲染清单」读数（只打印/落盘，不进判据；见 partition_backend）
    page_rows, failed = [], []
    sessions = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='chrome', headless=True,
                                         args=['--no-proxy-server'])
            for role, path, _src in samples:
                ctx = browser.new_context(viewport={'width': 1280, 'height': 900},
                                          locale='zh-CN')
                pg = ctx.new_page()
                try:
                    if role in ROLE_LOGINS:
                        login, pwd = ROLE_LOGINS[role]
                        sess = sessions.get(login) or login_session(login, pwd)
                        sessions[login] = sess
                        # 用会话 cookie 注入，避免每页走登录表单
                        cookies = [{'name': c.name, 'value': c.value,
                                    'domain': 'localhost', 'path': c.path or '/'}
                                   for c in sess.cookies]
                        if cookies:
                            ctx.add_cookies(cookies)
                    # 重页（/my/home、/my/apps 等）在负载下 45s 常不够 ⇒ 90s + 一次重试
                    resp, status = None, 0
                    for _try in (1, 2):
                        try:
                            resp = pg.goto(BASE + path, wait_until='domcontentloaded',
                                           timeout=90000)
                            status = resp.status if resp else 0
                            break
                        except Exception as _e:
                            if _try == 2:
                                raise
                            time.sleep(2)
                            pg.reload(wait_until='domcontentloaded', timeout=90000)
                    if status != 200:
                        failed.append('%s %s -> %s' % (role, path, status))
                        continue
                    # 2026-10-03：**先展开折叠区块再扫**。
                    #   axe 会跳过不可见内容，而本仓多张表单默认收在 `.collapse` 里
                    #   （如 `/my/time_off` 的请假表单、`/grievances/approvals` 的批量区）⇒
                    #   那些控件**从来没被无障碍门禁看过**。
                    #   而门禁报「0 违规」时，读者会以为是「这些页干净」，实际是「这些页没量到」。
                    #   （同族教训见本文件头部对「假绿」的记载。）
                    try:
                        pg.evaluate(
                            "() => document.querySelectorAll('.collapse')"
                            ".forEach(c => c.classList.add('show'))")
                        pg.wait_for_timeout(250)
                    except Exception:
                        pass
                    # ⚠ 2026-10-03 的一条**反面教训**，写给下一个想「顺手加个自研判据」的人：
                    #   我曾用一个自写启发式（控件有没有 for/id/aria-label/包裹 label）扫出
                    #   「8 个字段没有可访问名称」，兴冲冲要改；**先用 axe 复核，全判 OK** ——
                    #   那条启发式是**假阳性**（axe 的可访问名称算法比「for/id」宽得多）。
                    #   ⇒ 本仓纪律：**判据要落在权威工具/渲染结果上**，不要用 grep 或自写启发式下结论。
                    #   展开折叠这一步本身仍要保留：axe 会跳过不可见内容，
                    #   不展开就报「0 违规」，读者会误读成「这些页干净」，实际是「这些页没量到」。
                    backend_extra = None
                    if is_backend_path(path):
                        # 后台是 Owl **异步挂载**：domcontentloaded 时导航栏常常还没渲染
                        # （实测：外壳在 DOM 里但 rect=0，本地检查会把整条导航栏当"不可见"跳过
                        #  ⇒ 覆盖变成 0 页却看着"没违规"）。故先等外壳出现并稳定，再量。
                        try:
                            pg.wait_for_selector(SHELL_SELECTOR, timeout=20000)
                            pg.wait_for_timeout(1500)
                        except Exception:
                            pass
                        # 先注入 axe（非后台页由 run_axe 注入），再一次取三样
                        # （三样 = 页面主体 − 外壳 / 外壳本身 / 外壳逐条文字行，见 BACKEND_PROBE_JS）
                        pg.add_script_tag(content=source)
                        probe = pg.evaluate(BACKEND_PROBE_JS)
                        if probe.get('shell_missing'):
                            # 外壳量不到 ⇒ 这一页**没有**形成覆盖：按未扫到处理（exit 3 INCOMPLETE），
                            # 绝不当作"零违规通过"（这正是本项目最忌讳的假绿形态）。
                            failed.append('%s %s -> 外壳缺失/未渲染(rect=%s)'
                                          % (role, path, probe.get('shell_rect')))
                            continue
                        vok, vwhy = backend_view_ok(path, probe.get('views'))
                        if not vok:
                            # 形态断言失败 ⇒ 这一页**没有**按登记的样子渲染（例：带记录 id 的样本
                            # 静默回落成默认视图）⇒ 同样按未扫到处理。把「量到的是别的视图」
                            # 当成「这一页零违规」，就是本项目最忌的假绿。
                            failed.append('%s %s -> 形态断言失败(%s)' % (role, path, vwhy))
                            continue
                        gated, core, notes, localbad, skipped = partition_backend(
                            probe.get('page'), probe.get('shell'), probe.get('text'))
                        res = {'violations': gated_to_violations(gated)}
                        for rid, slot in core.items():
                            slot.setdefault('pages', []).append('%s %s' % (role, path))
                            acc = core_all.setdefault(rid, {'impact': slot.get('impact'),
                                                            'nodes': 0,
                                                            'where': slot.get('where')})
                            acc['nodes'] += int(slot.get('nodes') or 0)
                        backend_extra = {'shell_missing': bool(probe.get('shell_missing')),
                                         'views': probe.get('views'),
                                         'view_assert': {'expected': BACKEND_EXPECT_VIEW.get(path),
                                                         'ok': bool(vok), 'note': vwhy},
                                         'shell_violations': [
                                             {'id': v.get('id'), 'impact': v.get('impact'),
                                              'nodes': len(v.get('nodes') or []),
                                              'targets': first_targets(v)}
                                             for v in (probe.get('shell') or [])],
                                         'page_core': core,
                                         'local_contrast': {'violations': localbad,
                                                            'skipped': skipped},
                                         'notes': notes,
                                         'text_rows': probe.get('text') or [],
                                         'shell_rect': probe.get('shell_rect'),
                                         'gated': [{'rule': g['rule'], 'where': g['where'],
                                                    'nodes': g['nodes'], 'detail': g.get('detail'),
                                                    'targets': g.get('targets')} for g in gated]}
                        for n in notes:
                            print('  %s' % n)
                        for item in localbad:
                            print('  ✗ %-12s %-30s %s %s 压 %s = %.3f < %s%s'
                                  % ('本地对比度', item['sel'][:30], item['text'][:12],
                                     item['color'], item['bg'], item['ratio'], item['need'],
                                     '（disabled 控件内）' if item['disabled_control'] else ''))
                    else:
                        res = run_axe(pg, source)
                    imp, rules = summarize(res)
                    for k, v in imp.items():
                        per_impact[k] = per_impact.get(k, 0) + v
                    for r in rules:
                        slot = by_rule.setdefault(r['id'], {'impact': r['impact'],
                                                            'nodes': 0, 'pages': []})
                        slot['nodes'] += r['nodes']
                        if r['nodes']:
                            slot['pages'].append('%s %s' % (role, path))
                    page_rows.append({'role': role, 'path': path, 'status': status,
                                      'impact': imp, 'rules': rules,
                                      'backend': bool(backend_extra),
                                      'backend_detail': backend_extra})
                    if not quiet:
                        total = sum(imp.values())
                        flag = 'OK' if total == 0 else ' '.join(
                            '%s=%d' % (k, imp[k]) for k in IMPACT_ORDER if imp.get(k))
                        extra = ''
                        if backend_extra:
                            core_nodes = sum(s['nodes'] for s in (backend_extra['page_core'] or {}).values())
                            extra = (' 后台：外壳判据 %d ｜ 本地对比度 %d ｜ 核心清单 %d 条/%d 种'
                                     ' ｜ 形态 %s%s'
                                     % (sum(r['nodes'] for r in rules), len(backend_extra['local_contrast']['violations']),
                                        core_nodes, len(backend_extra['page_core'] or {}),
                                        vwhy,
                                        '  ⚠ 外壳没找到' if backend_extra['shell_missing'] else ''))
                        print('  %-11s %-30s %s%s' % (role, path, flag, extra))
                except Exception as e:
                    failed.append('%s %s -> EXC %s' % (role, path, str(e)[:50]))
                finally:
                    ctx.close()
            browser.close()
    except Exception as e:
        print('ENV：浏览器不可用（%s）' % str(e)[:100])
        return 2

    total = sum(per_impact.values())
    print('')
    print('================ 汇总 ================')
    print('违规合计 = %d 条（critical %d / serious %d / moderate %d / minor %d）'
          % (total, per_impact['critical'], per_impact['serious'],
             per_impact['moderate'], per_impact['minor']))
    print('扫描成功页 = %d / %d' % (len(page_rows), len(samples)))
    if by_rule:
        print('-- 规则明细（按条数降序，含影响面）--')
        for rid, slot in sorted(by_rule.items(), key=lambda kv: -kv[1]['nodes'])[:20]:
            print('  %-28s %-9s x%-4d 例: %s'
                  % (rid, slot['impact'], slot['nodes'], (slot['pages'] or [''])[0]))
    if failed:
        print('-- 未扫到的页 --')
        for f in failed[:10]:
            print('  %s' % f)
    backend_rows = [r for r in page_rows if r.get('backend')]
    if backend_rows:
        print('')
        print('-- 后台页覆盖（2026-09-28 新增）：判据 vs 核心清单 --')
        print('   样本 %d 页：%s' % (len(backend_rows),
                                  '、'.join('%s %s' % (r['role'], r['path']) for r in backend_rows)))
        gate_nodes = sum(sum((r['impact'] or {}).values()) for r in backend_rows)
        local_nodes = sum(len(((r['backend_detail'] or {}).get('local_contrast') or {}).get('violations') or [])
                          for r in backend_rows)
        skipped = {'invisible': 0, 'complex_bg': 0, 'no_color': 0}
        for r in backend_rows:
            for k, v in (((r['backend_detail'] or {}).get('local_contrast') or {}).get('skipped') or {}).items():
                skipped[k] = skipped.get(k, 0) + int(v or 0)
        print('   判据（零容忍，计入上面基线）：%d 条 ｜ 其中**本地对比度**（axe 结构盲区）= %d 条'
              % (gate_nodes, local_nodes))
        print('   本地检查跳过（**计数，不是豁免**）：复杂底 %d ｜ 不可见/全透明 %d ｜ 无颜色 %d'
              % (skipped.get('complex_bg', 0), skipped.get('invisible', 0), skipped.get('no_color', 0)))
        print('   判据范围 = 外壳(.o_navbar) 的 color-contrast ＋ 未登记规则 ＋ 本地对比度；'
              '其余核心条目只读数（下表，出现**新规则**即判红）')
        if core_all:
            print('   核心渲染清单（Odoo 核心渲染，**不在本仓可改范围**）：规则 %d 种 / 节点 %d 条'
                  % (len(core_all), sum(s['nodes'] for s in core_all.values())))
            for rid, slot in sorted(core_all.items(), key=lambda kv: -kv[1]['nodes']):
                print('     %-24s %-9s x%-4d %s'
                      % (rid, slot.get('impact'), slot['nodes'], slot.get('where') or ''))
        else:
            print('   核心渲染清单：空')
    cur = dict(per_impact)
    cur['total'] = total
    cur['pages'] = len(page_rows)
    # pages 随当轮**有效取样集**写入：表会变，写死在常量里就成了假绿（少扫几页也照样"在基线内"）。
    BASELINE['pages'] = len(samples)
    # 可比性守卫：**页面集不完整时不得判绿**（否则少扫几页 = 总数变小 = 假"在基线内"）
    comparable = (len(page_rows) == len(samples))
    drift = baseline_drift(cur, BASELINE) if comparable else False
    print('基线（常量）：%s' % json.dumps(BASELINE, ensure_ascii=False))
    print('本轮：%s' % json.dumps(cur, ensure_ascii=False))
    if not comparable:
        print('漂移判定：**跳过**（本轮只扫到 %d/%d 页 ⇒ 样本不可比，按 INCOMPLETE 处理）'
              % (len(page_rows), len(samples)))
    else:
        print('漂移判定：%s' % ('**超出基线 → 报警**' if drift else '在基线内'))
    print('自证：%s' % self_attest_line())
    print('并发状态：%s' % conc)
    if json_out:
        with open(json_out, 'w', encoding='utf-8') as fh:
            json.dump({'stamp': RUN_STAMP, 'revision': REVISION,
                       'fingerprint': _self_fingerprint(), 'impact': cur,
                       'baseline': BASELINE, 'by_rule': by_rule,
                       'pages': page_rows, 'failed': failed,
                       'concurrency': conc,
                       # 本轮新增：后台页判据/核心清单的机器可读读数（逐条，便于复核与回归比对）
                       'backend_core_inventory': core_all,
                       'backend_samples': [
                           {'role': r['role'], 'path': r['path'],
                            'gated_impact': r['impact'], 'gated_rules': [x['id'] for x in (r['rules'] or [])],
                            'core': (r['backend_detail'] or {}).get('page_core') or {},
                            'local_contrast': ((r['backend_detail'] or {}).get('local_contrast') or {}).get('violations') or [],
                            'local_skipped': ((r['backend_detail'] or {}).get('local_contrast') or {}).get('skipped') or {},
                            'shell_missing': (r['backend_detail'] or {}).get('shell_missing'),
                            'shell_rect': (r['backend_detail'] or {}).get('shell_rect'),
                           'views': (r['backend_detail'] or {}).get('views'),
                           'view_assert': (r['backend_detail'] or {}).get('view_assert'),
                            'text_rows': (r['backend_detail'] or {}).get('text_rows') or [],
                            'notes': (r['backend_detail'] or {}).get('notes') or []}
                           for r in backend_rows]}, fh, ensure_ascii=False, indent=1)
        print('-> %s' % json_out)
    if failed or plan.get('uncovered'):
        if plan.get('uncovered'):
            print('⇒ INCOMPLETE：表里登记了 accessibility 却有 %d 条没有可用取样身份（未扫）'
                  % len(plan['uncovered']))
        return 3                     # INCOMPLETE：有页面未扫到 / 有登记无法取样
    return 2 if drift else 0


def main():
    ap = argparse.ArgumentParser(description='全站 axe 无障碍审计门禁（t105）')
    ap.add_argument('--selftest', action='store_true', help='只证量具（不连站点）')
    ap.add_argument('--json', dest='json_out', help='结果落盘 JSON')
    ap.add_argument('--quiet', action='store_true', help='只出汇总')
    ap.add_argument('--list', action='store_true',
                    help='只读打印名单 + 对账（不连站点、不起浏览器）')
    ap.add_argument('--surface', default=None,
                    help='登记表路径（默认 tests/ui/surface.json）—— 审读/按冻结快照复算用')
    ap.add_argument('--only', default=None,
                    help='定向重扫：只跑这些路径（逗号分隔）。**不是门禁口径** —— '
                         '样本被缩小，读数只对这几页有效，用于复现/演练（注入违例→必须变红）')
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    # ---- 名单来源：tests/ui/surface.json（单一来源；B 组 2026-09-26 切换）----
    static, dyn, fp, err = load_surface(path=args.surface)
    if err:
        print('INCOMPLETE：%s %s' % (SURFACE, err))
        print('  名单没有来源 ⇒ 本轮不扫、不判 FAIL（退出码 3）。登记表由 A 组维护，'
              '生成：python3 scripts/ui_surface_report.py --generate')
        print('  这里**不退回写死名单** —— 那等于把刚拆掉的第二份名单重新长出来。')
        return 3
    samples, dropped, added, dyn_rows, notes, uncovered = build_samples(static, dyn)
    if args.only:
        wanted = [p.strip() for p in args.only.split(',') if p.strip()]
        keep = [s for s in samples if s[1] in wanted]
        if not keep:
            print('ENV：--only 的路径一条都不在本轮取样集内：%s' % '、'.join(wanted))
            return 2
        hit = set(s[1] for s in keep)
        print('⚠ 定向重扫（--only %s）：样本 %d → %d 页 —— **不能代表全站门禁**，'
              '只用于复现/演练；判定仍按同一条基线（0）' % (', '.join(wanted), len(samples), len(keep)))
        rest = [w for w in wanted if w not in hit]
        if rest:
            print('  （不在取样集内，已忽略：%s）' % '、'.join(rest))
        samples = keep
    if args.list:
        return print_list(static, dyn_rows, samples, dropped, added, notes, fp, uncovered=uncovered)
    return audit(json_out=args.json_out, quiet=args.quiet,
                 plan=dict(samples=samples, static=static, dyn_rows=dyn_rows, fp=fp,
                           dropped=dropped, added=added, notes=notes, uncovered=uncovered))


if __name__ == '__main__':
    sys.exit(main())
