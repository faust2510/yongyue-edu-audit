#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可见英文门禁 v3.2 —— 公开页 + 四角色的**可见文案**扫描，分类分流后按 must-fix/brand 判红。

=== 覆盖声明（可审计；由 --coverage 原样打印）===
覆盖的位置：
  1. **文本节点**：`>…<` 之间的可见文本（先剔除 <script>/<style>/注释/<template> 与编辑器 navbar 区块）；
  2. **4 类可见属性**：`title` / `placeholder` / `aria-label` / `alt`（双引号与单引号写法都认）。
不覆盖的位置（**互补 ≠ 并集完备**，与 check_odoo_trace 合起来也不等于"全位置覆盖"）：
  · 其它属性：`value`、`aria-description`、`aria-valuetext`、`data-tooltip`、`data-*` 等；
  · 图片内文字、PDF/Office 附件内容、邮件模板渲染结果、CSS 伪元素(::before/::after)生成的内容；
  · 纯中文串（按设计跳过）—— 但其中若含品牌 token（odoo/openeducat）会由 **brand** 桶抓出。
新增可见位置（例如将来模板用了 aria-description）时，**必须在此声明并加扫描**，否则会出现
「两个门禁都报 0」的假绿（2026-09-12 的 core tooltip 事件即为此类，见 UX_V3_GATE.md §2.1/§5.2）。

=== 分类与验收口径 ===
  must-fix  = 我们模板里、用户或读屏可见、应当汉化的**英文**（必须为 0）
  brand     = **中英混排里的品牌痕迹**（如「转到您的Odoo应用程序」，必须为 0；t37 新增）
  whitelist = 正当保留（品牌名/口号、Zoom/Telegram、语言自称 English、语言代码 EN）
  data      = 数据而非文案（课程代码、文件后缀、编号、邮箱、URL、账号显示名）
  theme     = website 编辑器 navbar 区块内（data-name="Navbar"）的命中，需 edu_brand 视图覆写才能改
名单来源（B 组 2026-09-26 切换）：**tests/ui/surface.json**（登记表，A 组维护）里 gates 含
english 的条目 —— 下方三张常量（PUBLIC/PORTAL/TEACHER_ROUTES）现在只回答「哪些角色看哪些页」
（口径），不再单独定义名单；表读不到 ⇒ 退出码 3（INCOMPLETE，不判 FAIL、不崩栈、不退回写死名单）。
口径里有、表里没有、也不在 SURFACE_MISSING（逐条写明理由的补偿清单）里的路径 ⇒ **不扫并点名**
（登记方口径优先：例 scope=retired 的 edu_telegram 路由 —— 生产上不存在，扫它=假读数）。
退出码：0 = must-fix 与 brand 均为 0；2 = 任一 > 0；1 = 运行错误（登录失败等）；
        3 = INCOMPLETE（tests/ui/surface.json 读不到 —— 名单无来源）。

每条 must-fix/brand 都会附「示例路由 + 来源文件:行号」，可直接去改（见 UX_V3_GATE.md §2、§2.1）。

用法：
    python3 scripts/check_english.py                    # 匿名公开页 + 四角色全量
    python3 scripts/check_english.py --role student     # 只跑一个角色
    python3 scripts/check_english.py --selftest         # 自证：分类与属性扫描（不连服务）
    python3 scripts/check_english.py --coverage         # 覆盖/不覆盖声明 + 自证行（不连服务）
    python3 scripts/check_english.py --list             # 只读打印名单 + 对账（不连服务、不发请求）

自证（t60）：正式输出与 --selftest 汇总都带 `REVISION · 指纹 · 断言 N 条`；
指纹是**自身文件 md5 前 8 位、运行时算**（不靠人 bump），断言条数与声明的 `SELFTEST_CASES` **实际计数比对，漂移即 FAIL**。
    python3 scripts/check_english.py stu@local demo123  # 兼容旧用法：单账号
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'

# 自证三元组（照 check_view_xpath 的形态，见 t60）：
#   REVISION  — 改动行为时同步 +1（人维护，回答"哪一版语义"）
#   指纹      — 自身文件 md5 前 8 位，**运行时算**（无需人 bump，也不可能"记错版本"）
#   断言条数  — 声明值；selftest 实际计数比对，**漂移即 FAIL**
REVISION = 'v3.8'      # 2026-09-26 B 组：名单改从 tests/ui/surface.json 读（gates 含 english）
                       #   —— 三张 ROUTES 常量降级为「口径」（哪些角色看哪些页）；退役模块路由自然出局
# v3.7（2026-09-18）评估系统重建第 1 期：扫描面 += 新引擎
                       #   /assess · /assess/my（学生/门户）· /assess/review（教师）；
                       #   /eval/my · /eval/review 登记为「已 303 → /assess/my」的旧地址壳
                       #   （旧模块一行未删，三期删旧两套时一并摘掉这两条登记）
# v3.6（t103）：+ 夹具残留的**并发守卫**（在跑夹具标 ENV，不报成泄漏）
SELFTEST_CASES = 48      # 2026-09-26 B 组 +5：名单读取的纯函数（静态上级 / 默认口径 /
                        #   表外剔除）—— 不连服务、不读真实表

# 运行时刻（t71）：与 check_odoo_trace 同款 —— **单一来源**（模块导入时取一次），
# 作用是**协作用途**（判断某份读数是否落在测试窗口内），**不是防篡改证据**：
# 保存下来的输出仍可被手工编辑。指纹（内容 md5）才是"跑的是哪一版"，两者别混用 ——
# **指纹不证明运行时刻，运行时刻也不证明版本**。
RUN_STAMP = datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def _self_fingerprint():
    """自身文件的 md5 前 8 位（**运行时算**）。

    自证机制不能依赖人的记性：本轮出过"手工记的 md5 被一次普通改动弄过期"
    与"旧快照往返"两次事故 —— 指纹必须由代码现算。
    """
    import hashlib
    import os
    with open(os.path.abspath(__file__), 'rb') as fh:
        return hashlib.md5(fh.read()).hexdigest()[:8]


def self_attest_line():
    """贴一行即自证：REVISION · 指纹 · 断言条数。"""
    return 'REVISION=%s · 指纹 %s · 断言 %d 条 · 运行时刻 %s' % (
        REVISION, _self_fingerprint(), SELFTEST_CASES, RUN_STAMP)

ROLES = {
    'student':    ('stu@local', 'demo123', '学生'),
    'faculty':    ('faculty@local', 'demo123', '教师'),
    'parent':     ('parent@local', 'demo123', '家长'),
    'backoffice': ('backoffice@local', 'demo123', '教务'),
}
ROLE_ORDER = ['guest', 'student', 'faculty', 'parent', 'backoffice']

PUBLIC_ROUTES = [
    '/', '/about', '/programs', '/admissions', '/journal', '/alumni',
    '/alumni/jobs', '/campus/jobs', '/digital-library', '/courses-offered',
    '/booking', '/online-exams', '/apply',
    '/help', '/help/student', '/help/faculty', '/help/parent', '/help/registrar',
    # t71：真身是 /register（t4 改名）；旧的 '/web/register' 现为 **302 替身**
    # （→ /register），放进清单只会让门禁扫到空响应体且一直报绿 —— 已替换。
    '/register',
    # v3 交付中的别名（t4 三层落点；状态见 ROUTE_STATUS 白名单）
    '/login', '/apps',
]

PORTAL_ROUTES = [
    '/my', '/my/home', '/my/apps', '/my/study',
    '/student/profile', '/student/timetable', '/student/attendance',
    '/student/exam', '/student/assignment/details', '/grade-book',
    '/library/media', '/my-library', '/subject/details', '/subject/registration',
    '/course/change/request', '/my/notice_board/notice', '/my/time_off',
    '/my/grievances', '/certificate', '/requested/queue/list',
    '/meeting/information', '/online/meeting', '/users/result-overview',
    '/my/academic-calendar', '/my/checkins', '/my/journals',
    # 评估系统重建第 1 期（2026-09-18）：新引擎门户页进扫描面。
    '/assess', '/assess/my',
    '/downloads', '/downloads/mine', '/downloads/stats', '/quiz', '/quiz/my',
    '/my/courses', '/my/messages', '/my/contacts', '/my/calendar', '/my/fees',
    '/my/assets', '/my/dms', '/my/thesis', '/my/points', '/my/notify',
    '/my/password', '/my/help', '/my/search', '/my/child',
]

TEACHER_ROUTES = [
    '/attendance/take', '/assignment/manage', '/assignment/publish',
    '/grading/entry', '/leave/approvals', '/grievances/approvals',
    '/notice/publish', '/journals/review', '/checkins/stats',
    '/registrar/subject/approvals', '/edu/audit', '/ledger', '/ledger/reimburse',
    '/timetable/bulk', '/my/rollcall', '/my/marks',
    '/my/subject-reg',
    # 评估系统重建第 1 期：教师侧新引擎审阅队列（只列本人任教班）。
    '/assess/review',
]

# ---------------------------------------------------------------- 名单来源（B 组 2026-09-26 切换）
# **单一来源** = tests/ui/surface.json（登记表，A 组维护）：gates 含 english 的条目就是本门禁的名单。
# 上面三张常量（PUBLIC/PORTAL/TEACHER_ROUTES）降级为**口径**：只回答「哪些角色看哪些页」——
# 表没有等价字段（表的 roles 是「允许身份」，不是「用哪个身份扫」），所以这一层留在脚本。
# 切换时逐条对过账：口径 88 条路径 = 表内 84 条（含 3 条 scope=retired 的 edu_telegram 退役路由，
# 按登记方口径**出局**）+ 表缺登记补偿 1 条（'/'）。差集逐条见交付回复。
SURFACE = 'tests/ui/surface.json'
SURFACE_GATE = 'english'
# 表缺登记的补偿：**唯一一处手写名单**，每条都要写清为什么表里没有它；补进表后应当删空。
# 2026-09-28（B 组）：**已删空** —— 唯一那条 '/' 已补进表（key=root、gates 含 english）。
#   删后 --list 实测：扫描仍 85 条路径 × 角色（guest 21 / student 69 / faculty 85 / parent 69 /
#   backoffice 85），对账「扫描集 − 表 = 空 ｜ 表 − 扫描集 = 空」，guest / 照旧在名单里
#   （'/' 由表行进入）：覆盖没有变小。留空 dict = 保留这处「表缺登记时必须写理由」的显式落点。
SURFACE_MISSING = {}
DYN_SEG_RE = re.compile(r'(/<[^>]+>)+$')
_SURFACE_CACHE = None


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
    dyn    = [(path, 上级候选 list)]：带 <参数> 的登记 —— 不能裸探（探 '/x/<int:id>' 只会拿 404，
             在**本门禁**里更糟：404 会撞上「被扫路由必须 200」不变量，变成假红）；
    err    = 读不到 / 解析失败的人话原因（调用方判 INCOMPLETE，不判 FAIL）。
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
    """表新增路由的默认口径（**与既有口径同型**）：
      · scope=portal（= PORTAL_ROUTES 同型）→ 四个登录角色都扫（文案要在每个身份的变体上都看）；
      · scope=public（= PUBLIC_ROUTES 同型）→ 四个登录角色 + guest（匿名侧）；
      · 其余（endpoint/other）→ 按登记 roles 里有会话的身份；roles 含 anon 再加 guest。
    与 check_accessibility 的默认口径**故意不同**：那边是 axe 取样（一页一个代表身份就够）。
    """
    out = set()
    if scope in ('portal', 'public'):
        out |= set(ROLES)
    if 'anon' in roles or scope == 'public':
        out.add('guest')
    for r in roles:
        if r in ROLES:
            out.add(r)
    if not out and 'anon' in roles:
        out.add('guest')
    return out


def filter_legacy(paths, table_paths, missing=None):
    """口径名单 → 可扫名单：表内 ∪ 补偿清单；表外其余**剔除并点名**（登记方口径优先）。

    返回 (keep, dropped)：keep 保原序（输出与切换前逐条一致），dropped 由调用方打印。
    为什么要这一层：口径里留着**改名/退役**的替身时，门禁会扫到空壳却一直报绿（t71 的
    /web/register 就是这么来的）；表是唯一真源，故表外的一律不扫 —— 但**必须点名**，不许静默。
    """
    missing = set(SURFACE_MISSING if missing is None else missing)
    keep, dropped = [], []
    for p in paths:
        if p in table_paths or p in missing:
            keep.append(p)
        else:
            dropped.append(p)
    return keep, dropped


def scan_plan(path=None):
    """表 + 口径 → {角色: [路径]} + 诊断。表读不到 ⇒ 返回 (None, None, 原因)。

    产出：
      plan[role]   = 本角色的扫描名单（口径保序 + 表新增追加）
      info         = {fp, static, dyn_rows, dropped, added, notes, err}
    """
    global _SURFACE_CACHE
    if _SURFACE_CACHE is None:
        static, dyn, fp, err = load_surface(path=path)
        _SURFACE_CACHE = dict(static=static, dyn=dyn, fp=fp, err=err)
    st = _SURFACE_CACHE
    if st['err']:
        return None, None, st['err']
    static = st['static']
    table_paths = set(p for p, _r, _s in static)
    legacy_all = set(PUBLIC_ROUTES) | set(PORTAL_ROUTES) | set(TEACHER_ROUTES)
    plan, dropped_all, added, notes = {}, set(), [], []
    for role in ROLE_ORDER:
        keep, dropped = filter_legacy(routes_for_legacy(role), table_paths)
        dropped_all |= set(dropped)
        extra = []
        for path, roles, scope in static:
            if path in legacy_all:
                continue
            if role in default_roles_for(roles, scope):
                extra.append(path)
                if path not in added:
                    added.append(path)
        plan[role] = keep + sorted(extra)
    dyn_rows = [(p, next((c for c in cands
                          if any(c in plan[r] for r in ROLE_ORDER)), '')) for p, cands in st['dyn']]
    nosample = sorted(p for p, roles, _s in static
                      if not default_roles_for(roles, _s) and p not in legacy_all)
    for p in nosample:
        notes.append('表新增登记 %s 无可用扫描角色（roles 与本脚本会话无交集）—— 需要人工决定口径' % p)
    info = dict(fp=st['fp'], static=static, dyn_rows=dyn_rows,
                dropped=sorted(dropped_all), added=added, notes=notes, err=None)
    return plan, info, None


def print_coverage(plan, info, title='名单来源'):
    """打印「名单从哪来 / 扫了什么 / 两处不一致」——每次跑都打，防止名单悄悄漂移。"""
    static = info.get('static') or []
    table_paths = set(p for p, _r, _s in static)
    scanned = set(p for r in ROLE_ORDER for p in (plan or {}).get(r, []))
    print('== %s ==' % title)
    print('  %s（指纹 %s）· gates=english 登记 %d 条 = 静态 %d + 参数化 %d'
          % (SURFACE_USED or SURFACE, info.get('fp'), len(static) + len(info.get('dyn_rows') or []),
             len(static), len(info.get('dyn_rows') or [])))
    print('  本门禁扫描：%d 条路径 × 角色 = %s'
          % (len(scanned), '，'.join('%s %d' % (r, len((plan or {}).get(r, []))) for r in ROLE_ORDER)))
    print('  对账：扫描集 − 表 = %s ｜ 表 − 扫描集 = %s'
          % ('、'.join(sorted(scanned - table_paths)) or '（空）',
             '、'.join(sorted(table_paths - scanned)) or '（空）'))
    if info.get('dropped'):
        print('  ⚠ 口径里有、表里没有且未登记补偿 %d 条 ⇒ **不扫**（登记方口径优先，'
              '例如 scope=retired 的退役路由）：%s'
              % (len(info['dropped']), '、'.join(info['dropped'])))
    if info.get('added'):
        print('  ⚠ 表新增登记 %d 条（口径未收录，按 scope/roles 默认口径扫描）：%s'
              % (len(info['added']), '、'.join(info['added'])))
    nodyn = [p for p, par in (info.get('dyn_rows') or []) if not par]
    if info.get('dyn_rows'):
        print('  参数化 %d 条：静态上级在扫描面内 %d 条%s'
              % (len(info['dyn_rows']), len(info['dyn_rows']) - len(nodyn),
                 '' if not nodyn else '｜⚠ 无上级 %d 条（覆盖缺口）：%s'
                 % (len(nodyn), '、'.join(nodyn))))
    for n in info.get('notes') or []:
        print('  note：%s' % n)


def print_list(plan, info):
    """--list：**只读**打印名单与对账（不连服务、不发请求）；TAG 前缀供对账脚本取用。"""
    print_coverage(plan, info, title='名单（只读打印）')
    for role in ROLE_ORDER:
        print('-- %s（%d 条）--' % (role, len(plan[role])))
        for p in plan[role]:
            print('[ROUTE] %-11s %s' % (role, p))
    print('-- 表登记（静态）--')
    for path, roles, scope in (info.get('static') or []):
        print('[TABLE] %-32s roles=%-40s scope=%s' % (path, ','.join(sorted(roles)) or '(空)', scope))
    print('-- 表缺登记补偿（本门禁仍在扫）--')
    for p, why in sorted(SURFACE_MISSING.items()):
        print('[MISSING] %-30s %s' % (p, why))
    print('-- 参数化登记（不可裸探；登记语义 = 覆盖经上级继承）--')
    for p, par in (info.get('dyn_rows') or []):
        print('[DYN] %-36s 静态上级=%s' % (p, par or '⚠ 无（在扫描面内找不到上级）'))
    print('== 退出码 0 = 名单读得到（--list 只打印，不判门禁）==')
    return 0


# ------------------------------------------------------- 路由状态不变量（t71）
# 为什么需要：清单里若留着**改名后的替身**，scan_role 对它 allow_redirects=False
# → 只拿到 302 的空响应体 → **整页从未被扫，而门禁一直报绿**（2026-09-12 的 /web/register 实例；
# 全仓 86 条清单逐条审计后，确认**它是唯一的替身**）。因此：**被扫路由必须 200**，
# 非 200 只允许两类，且都要能说清"为什么这不算走错了面"：
#   ① 角色/匿名门禁：302/303 跳到 ALLOWED_REDIRECT_TARGETS 中的目标；
#   ② 显式登记：EXEMPT_ROUTES 里写明的 (路径, 角色) + 原因。
ALLOWED_REDIRECT_TARGETS = ('/my/home', '/apps', '/web/login', '/login')


# ------------------------------------------- 夹具残留（【冒烟】标记）不变量（t84）
# 为什么需要：本轮**三次**同类事故（t80 F_roles 无前缀不自清 / t75 并发读到 GONE /
# t82 aux4 漏清 4+6+4 条）—— 判据都对、门禁没错，**错在没人负责夹具的生命周期**。
# "每个脚本记得写 finally"已被证明会失效三次，所以改在**门禁侧**兜底：
#   **扫描面（页面文本）出现 【冒烟】 标记即点名报警** —— 要报的是「**夹具没走**」。
SMOKE_MARKER = '【冒烟】'
# 例外必须**显式登记 + 写明理由**。这两条是 append-only 视图：报它们等于把**正常工作**当故障
# （实测本机：/edu/audit 19 条、/my/messages 1–5 条，全部来自**已发生**的通知与审计动作；
#  i18n-eng 另测 edu_message.body 有 189 条同类 ⇒ 一概不报）。
# 一句话判据：**要报的是「夹具没走」，不是「夹具来过」**。
SMOKE_EXEMPT_ROUTES = {
    '/edu/audit': '审计留痕 append-only：它记录的是「夹具来过」，删历史本身就是错的',
    '/my/messages': '站内信/通知流 append-only：已发出的通知无法也不该收回',
}


EXEMPT_ROUTES = {
    # 请假分级审批（S5 登记，2026-09-24）：**家长身份**的 /my/time_off 是 S3 的
    # **有意分流**，不是改名后的替身 —— 家长既不是学生（不套学生单），也不是教职
    # （家长不算教职单，判据见 leave-split-approval-design.md §5.3），他的入口归
    # 孩子的请假页 /my/child（S3 报告 §6-1 与 batch3.py 的门禁跳转注释同款）。
    # 学生/教师/教务/系统身份下该路由仍是 200（照常扫描英文）。**不要**改成 200。
    ('/my/time_off', 'parent'): '家长身份 → 303 /my/child（S3 有意分流：家长不套学生单/'
                               '教职单，入口归孩子页；其余角色仍 200）',
    ('/apps', '*'): '门户/匿名 → 303 /my/home；内部用户 200（t4 三层落点设计）',
    ('/login', '*'): '匿名 200；已登录 → 303 /my/home；内部用户 → 303 /web（t4 三层落点设计）',
    ('/my', '*'): '门户入口统一 303 /my/home（重定向壳，不是内容页）',
    ('/quiz/my', '*'): '非学生身份（教师/家长/内部）→ 303 回 /quiz（角色门禁；学生为 200）',
}


def route_status_ok(role, path, status, location):
    """非 200 的放行判定 → (是否放行, 原因)。"""
    if status == 200:
        return True, ''
    # 登记只放行**重定向**（302/303）：登记过的路径若 404/500/异常，仍然判违规 ——
    # 否则白名单会顺带把"这条路由彻底没了"也放过。
    if status in (302, 303):
        if (path, role) in EXEMPT_ROUTES:
            return True, '登记：' + EXEMPT_ROUTES[(path, role)]
        if (path, '*') in EXEMPT_ROUTES:
            return True, '登记：' + EXEMPT_ROUTES[(path, '*')]
    if status in (302, 303) and any(location.startswith(t) for t in ALLOWED_REDIRECT_TARGETS):
        return True, '角色/匿名门禁 → %s' % location
    return False, ''


# ---------------------------------------------------- 夹具残留的并发守卫（t103）
# 问题：**"正在跑的夹具"与"跑完没走的残留"在时点快照里长得一模一样**（t84 实测两轮各命中
# 3–4 条，其中 3 条是别的脚本正在跑；t102 的 【冒烟】P3学生 也是 p3_prod_ledger_smoke 运行期活夹具）。
# 处置：检测"当前是否有冒烟脚本在跑" → **有则该轮把 smoke-leftover 标 ENV/跳过**（与就绪判据同族：
# 别把"环境正在被夹具使用"报成"数据泄漏"）。
# **明确不做**：不给 【冒烟】 加白名单豁免 —— 那会掩盖"真实残留夹具"这一整类，恰是本门禁的价值。
SMOKE_PROC_MARKER = 'tests/smoke/'
SMOKE_PROC_EXTRA = ('assertion_audit.py',)   # 审计器会顺序拉起冒烟 ⇒ 同样算"夹具在用"


def smoke_running(ps_text=None):
    """当前是否有冒烟脚本在跑 → (bool, [匹配命令行])。

    实现选择与理由：用 **ps -ef 文本**（而不是 pgrep -f）——
      · macOS 的 `pgrep -f` 只匹配命令行的前约 200 字符，而本仓路径很长，
        路径前缀 `…/tests/smoke/` 常被截掉 ⇒ 会漏检；
      · 也不用 /proc（macOS 无）。
    另外**接受注入的 ps_text**，使 selftest 能构造"有/无并发"两种反例而无需真跑脚本。
    取不到进程表时返回 (False, []) —— 不阻塞门禁，但调用方须在输出里说明。
    """
    if ps_text is None:
        try:
            ps_text = subprocess.run(['ps', '-ef'], capture_output=True,
                                     text=True, timeout=10).stdout
        except Exception:
            return False, []
    hits = []
    for line in (ps_text or '').splitlines():
        if SMOKE_PROC_MARKER not in line:
            continue
        if 'check_english.py' in line or 'grep' in line:
            continue
        if line.rstrip().endswith('.py') or any(x in line for x in SMOKE_PROC_EXTRA):
            hits.append(line.strip()[:110])
    return bool(hits), hits


def smoke_leftover_verdict(concurrency, hits):
    """夹具残留的最终判定 → ('CLEAN' | 'ENV_SKIP' | 'REPORT', 说明)。"""
    if not hits:
        return 'CLEAN', ''
    if concurrency:
        return 'ENV_SKIP', '检测到冒烟脚本在跑 ⇒ **在跑夹具 ≠ 残留**，本轮标 ENV/跳过'
    return 'REPORT', '无冒烟在跑 ⇒ 命中即真残留，点名报警'


def smoke_leftover_for(path, html):
    """夹具残留判定（唯一真源，t84）：返回 (是否豁免, 命中数, [(标记, 上下文)])。

    判据：**要报的是「夹具没走」，不是「夹具来过」** —— append-only 视图（审计留痕、
    站内信/通知流）里出现标记属**正常工作**，按 SMOKE_EXEMPT_ROUTES 豁免（返回 0）；
    活体实体页出现标记才是残留，命中即点名。
    """
    if path in SMOKE_EXEMPT_ROUTES:
        return True, 0, []
    n = (html or '').count(SMOKE_MARKER)
    return False, n, (scan_smoke_markers(html) if n else [])


def scan_smoke_markers(html, limit=3):
    """扫描页面文本里的夹具标记 → [(标记, 上下文片段)]（去重、限 limit 条）。

    上下文取标记前后各 24 字，便于**点名**到"哪条数据"。
    """
    out = []
    idx = 0
    while True:
        i = html.find(SMOKE_MARKER, idx)
        if i < 0:
            break
        seg = re.sub(r'\s+', ' ', html[max(0, i - 24):i + len(SMOKE_MARKER) + 24]).strip()
        if seg not in [s for _m, s in out]:
            out.append((SMOKE_MARKER, seg))
            if len(out) >= limit:
                break
        idx = i + len(SMOKE_MARKER)
    return out


def routes_for_legacy(role):
    """**口径**（哪些角色看哪些页）—— 名单本身来自表，见 scan_plan()/routes_for()。"""
    if role == 'guest':
        return list(PUBLIC_ROUTES)
    if role in ('faculty', 'backoffice'):
        return list(PUBLIC_ROUTES) + list(PORTAL_ROUTES) + list(TEACHER_ROUTES)
    return list(PUBLIC_ROUTES) + list(PORTAL_ROUTES)


def routes_for(role):
    """本角色的扫描名单 = 表（gates 含 english 的静态登记 → 该角色）∪ 表缺登记补偿。

    表读不到 ⇒ 返回 []（main 已先判 INCOMPLETE 并返回 3，走不到这里）；**不兜底写成死名单**
    —— 那等于把刚拆掉的第二份名单重新长出来。
    """
    plan, _info, _err = scan_plan()
    return list((plan or {}).get(role, []))


# ---------------------------------------------------------------- 分类规则
WHITELIST = {
    'COVENANT REFORMED SEMINARY',    # 品牌英文名
    'COVENANT · REFORMED · TRUTH',   # 品牌口号（队长 2026-09-12 判定保留）
    'Zoom',                          # 第三方产品名
    'English',                       # 语言自称（brand_templates.xml:252 语言切换）
    'EN',                            # 语言代码/自称缩写（顶栏语言切换器显示文本：出处
                                     # edu_portal_templates.xml:48 / brand_templates.xml:20 /
                                     # batch3.xml:1188）——判据：语言自称或语言代码不算残留
    'Telegram',                      # 第三方产品名（队长 2026-09-12 批准，与 Zoom 同性质）
}
# 数据型的「人名/账号显示名」：来自 res.users 数据而非模板文案。
# Odoo 默认管理员账号显示名就是 Administrator —— 改不改由用户决定，
# 扫描端按 data 归类（队长 2026-09-12 确认口径）。
DATA_NAMES = {'Administrator'}
TEXT_RE = re.compile(r'>([^<>]*[A-Za-z][^<>]{1,80})<')
ATTR_RE = re.compile(
    r'\b(?:placeholder|title|aria-label|alt)\s*=\s*"([^"]*)"'
    r"|\b(?:placeholder|title|aria-label|alt)\s*=\s*'([^']*)'", re.I)
SCRIPT_RE = re.compile(r'<script[\s\S]*?</script>', re.I)
STYLE_RE = re.compile(r'<style[\s\S]*?</style>', re.I)
COMMENT_RE = re.compile(r'<!--[\s\S]*?-->')
# QWeb <template> 块（含 name="..." 这类结构性属性）不是用户可见文案，整体剔除
TEMPLATE_RE = re.compile(r'<template[\s\S]*?</template>', re.I)
# website 编辑器的 navbar 区块（含 d-lg-none 的移动端副本）：aria-label=Main/Mobile 出自这里
EDITOR_NAV_RE = re.compile(r'<nav[^>]*data-name="Navbar"[\s\S]*?</nav>', re.I)
CJK_RE = re.compile(r'[\u4e00-\u9fff]')
# 品牌痕迹：中英混排值里也照样抓（t37）。check_odoo_trace 管文本节点与专项扫描，
# 这里管**可见属性**里被「含 CJK 即跳过」漏掉的品牌串 —— 两者是互补而非互替。
BRAND_RE = re.compile(r'odoo|openeducat', re.I)
# 数据型 token：编号/代码/邮箱/URL/文件后缀
DATA_RE = re.compile(
    r'^[A-Za-z]{1,6}[-/]\d'
    r'|^\d'
    r'|@'
    r'|^[A-Z]\d{2,}'
    r'|^[A-Z][-+]?$'
    r'|^\S*\d\S*$'
    r'|/'
    r'|Vol\.'
    r'|^[{[]'
    # t71：编号**格式占位符**（如 EDU-XXXXXX）。注册页长期未被扫，纳入后它一度被
    # 判 must-fix —— 但它是"机读编号格式"而非英文文案，归数据型；判据收紧到
    # 「大写前缀-全为 X/数字」，不会吞掉真实英文词。
    r'|^[A-Z]{2,8}-[Xx0-9]{3,}$')
# 纯字母课程/专业代码（CRS-MCS、EDU-BTH 之类）与文件后缀（pdf、docx）
# 注：文件后缀是**数据**不是 UI 文案；纯文本类（txt/md/log/sql/ics…）必须在内，
# 否则真实资料一上传（如 x.txt）就会让门禁报红 —— 对正常文件类型报红会训练大家忽略门禁
# （study-eng 2026-09-12 实测 must-fix 2 = {txt:2}，队长确认为真）。
CODE_RE = re.compile(r'^[A-Z]{2,5}(?:[- ][A-Z]{2,5})+$')
FILE_EXT_RE = re.compile(
    r'^(?:pdf|docx?|xlsx?|pptx?|csv|txt|text|md|markdown|rtf|odt|ods|odp|json|xml|ya?ml'
    r'|log|sql|ics|html?|htm|epub|zip|rar|7z|tar|gz|png|jpe?g|gif|bmp|webp|svg|mp4|mov|mp3|wav)$',
    re.I)


COVERAGE_DECLARATION = """覆盖声明（本门禁到底扫哪些位置，可审计）：
  覆盖位置：
    1) 文本节点 `>…<`（先剔除 <script>/<style>/注释/<template> 与编辑器 navbar 区块）
    2) 4 类可见属性：title / placeholder / aria-label / alt（单双引号都认）
  不覆盖位置（互补 ≠ 并集完备；与 check_odoo_trace 合起来也不等于全位置覆盖）：
    · 其它属性：value / aria-description / aria-valuetext / data-tooltip / data-* 等
    · 图片内文字、PDF/Office 附件内容、邮件模板渲染结果、CSS 伪元素生成内容
    · 纯中文串（按设计跳过；其中含 odoo/openeducat 品牌 token 的由 brand 桶抓出）
  路由状态（t71）：**被扫路由必须 200**；非 200 只放行两类 ——
    ① 角色/匿名门禁（302/303 跳 /my/home、/web、/web/login、/login）；
    ② EXEMPT_ROUTES 里显式登记并写明原因（/apps、/login、/my、/quiz/my×backoffice）。
    非 200 未登记即判失败并点名 —— 典型根因是**改名后留下的 302 替身**
    （门禁拿到空壳响应体、整页从未被扫却一直报绿；实例 /web/register → /register）。
    自证：python3 scripts/check_english.py --prove-invariant（替身必须报红、真身必须放行）。
  夹具残留（t84）+ 并发守卫（t103）：扫描面出现 【冒烟】 标记即**点名报警**（要报的是"夹具没走"）；
    但**开跑时若检测到冒烟脚本在跑**（ps -ef 见 tests/smoke/*.py 或 assertion_audit.py），
    本轮该类**标 ENV/跳过**（"环境正在被夹具使用" ≠ "数据泄漏"），并在输出显式打印 ENV 标注；
    **【冒烟】标记本身不豁免**（那会掩盖"真实残留夹具"这一整类），换无并发轮次仍会点名。
    append-only 视图**显式豁免**（SMOKE_EXEMPT_ROUTES 逐条写明理由）：
    · /edu/audit —— 审计留痕（实测 19 条）；· /my/messages —— 站内信/通知流（实测 1–5 条）。
    退出码归属：**单列一类（smoke-leftover）**，不是 must-fix（它不是英文问题），但同属"发现问题" → 同落 **exit 2**。
  名单来源（B 组 2026-09-26 切换）：路由名单来自 **tests/ui/surface.json**（gates 含 english 的
    登记）—— 本脚本的三张常量（PUBLIC/PORTAL/TEACHER_ROUTES）只回答「哪些角色看哪些页」（口径）。
    表读不到 ⇒ 退出码 3=INCOMPLETE（不判 FAIL、不崩栈、**不退回写死名单**）；
    口径里有、表里没有、也不在 SURFACE_MISSING（逐条写明理由的补偿清单）里的路径 ⇒ **不扫并点名**
    （登记方口径优先：例 scope=retired 的 edu_telegram 退役路由 —— 生产上不存在，扫它=假读数）。
  判据：新增可见位置（如将来用 aria-description）必须在 docstring 与本声明登记并加扫描，
        否则会出现「两个门禁都报 0」的假绿（实例见 UX_V3_GATE.md §2.1/§5.2）。"""


def _intervals(html, regex):
    return [(m.start(), m.end()) for m in regex.finditer(html)]


def _inside(pos, intervals):
    for a, b in intervals:
        if a <= pos < b:
            return True
        if a > pos:
            return False
    return False


def classify(raw, pos=None, editor_iv=None, kind='text'):
    """返回 (值, 分类) 或 None。

    分类 ∈ must-fix / brand / whitelist / data / theme。
    **brand** 专治「中英混排里的品牌痕迹」：这类值过去因为「含 CJK 即跳过」被整体放过，
    例如 Odoo 自带 website_templates 的 `title="Go to your Odoo Apps"` →
    官方 zh_CN 渲染成「转到您的Odoo应用程序」的悬停 tooltip（t26 补属性提取后才被照出来）。
    """
    s = re.sub(r'\s+', ' ', raw or '').strip()
    if not s:
        return None
    if CJK_RE.search(s):
        # 含中文：一般是中文文案 → 跳过；但**含品牌 token 的中英混排**必须报（t37）
        if BRAND_RE.search(s):
            return s, 'brand'
        return None
    if BRAND_RE.search(s):
        return s, 'must-fix'   # 纯英文里的品牌串仍按英文残留处理（保持既有语义）
    if not re.match(r'^[A-Za-z]', s):
        return None
    if len(s) > 80:
        return None
    if s in WHITELIST:
        return s, 'whitelist'
    if s in DATA_NAMES:
        return s, 'data'
    if CODE_RE.match(s) or FILE_EXT_RE.match(s):
        return s, 'data'
    if DATA_RE.search(s):
        return s, 'data'
    if pos is not None and editor_iv and _inside(pos, editor_iv):
        return s, 'theme'
    return s, 'must-fix'


def scan_body(html):
    """返回 list[dict(value, kind, bucket)]（按出现顺序，保留重复）。"""
    # 注意：_inside 假定区间按起点有序（命中即停），多组区间拼接后必须重新排序，
    # 否则「文档位置靠后的 script」会先被判成"已越过"而漏掉前面的 template 区间。
    skip_iv = sorted(_intervals(html, SCRIPT_RE) + _intervals(html, STYLE_RE)
                     + _intervals(html, COMMENT_RE) + _intervals(html, TEMPLATE_RE))
    editor_iv = _intervals(html, EDITOR_NAV_RE)
    out = []
    for m in TEXT_RE.finditer(html):
        if _inside(m.start(), skip_iv):
            continue
        got = classify(m.group(1), m.start(1), editor_iv, kind='text')
        if got:
            out.append(dict(value=got[0], kind='text', bucket=got[1]))
    for m in ATTR_RE.finditer(html):
        if _inside(m.start(), skip_iv):
            continue
        raw = m.group(1) if m.group(1) is not None else m.group(2)
        got = classify(raw, m.start(), editor_iv, kind='attr')
        if got:
            out.append(dict(value=got[0], kind='attr', bucket=got[1]))
    return out


# ---------------------------------------------------------------- 来源定位（must-fix 专用）
_SRC_CACHE = {}


def _src_priority(fp):
    """视图模板优先：views/*.xml > 其他 xml > js > py > css（css 多为样式表里的类名）。"""
    if '/views/' in fp and fp.endswith('.xml'):
        return 0
    if fp.endswith('.xml'):
        return 1
    if fp.endswith('.js'):
        return 2
    if fp.endswith('.py'):
        return 3
    return 4


# 命中位于这些属性值里 → 是 CSS 类名/内联样式/结构 id，不是渲染文案
_ATTR_VALUE_TAIL_RE = re.compile(r'(?:class|style|id|data-[\w-]+)\s*=\s*["\'][^"\']*$')


def _needle_re(needle):
    """短英文串按**词边界**匹配：避免 oe-norec-txt / text 里的 'txt' 这类子串误命中。"""
    if re.match(r'^[A-Za-z0-9 ._&-]+$', needle):
        return re.compile(r'(?<![-\w])' + re.escape(needle) + r'(? ![-\w])'.replace(' ', ''))
    return re.compile(re.escape(needle))


def source_of(needle, roots=('custom_addons',), limit=3):
    """在自研代码里找该英文字串的出处，返回 ['文件:行号', ...]（视图模板优先）。

    这是**启发式**（词边界 + 排除 class/style/id 属性值与 py 注释/docstring），
    定位仅供参考，真正改动前请打开文件确认。已知盲区：中英混排串按原样子串匹配；
    JS 里的字符串仍可能命中非渲染路径。
    """
    if needle in _SRC_CACHE:
        return _SRC_CACHE[needle]
    rx = _needle_re(needle)
    hits = []
    try:
        import os
        for root in roots:
            for dirpath, _dirs, files in os.walk(root):
                for fn in files:
                    if not fn.endswith(('.xml', '.js', '.py')):
                        continue
                    fp = os.path.join(dirpath, fn)
                    is_py = fp.endswith('.py')
                    try:
                        with open(fp, encoding='utf-8', errors='ignore') as f:
                            in_doc = False
                            for i, line in enumerate(f, 1):
                                if is_py:
                                    # 三引号块内的内容（docstring）不是渲染路径
                                    if in_doc:
                                        if '"""' in line or "'''" in line:
                                            in_doc = False
                                        continue
                                    if (line.count('"""') % 2 or line.count("'''") % 2):
                                        if not rx.search(line):
                                            in_doc = True
                                            continue
                                        in_doc = True
                                m = rx.search(line)
                                if not m:
                                    continue
                                head = line[:m.start()]
                                # ① 属性值里的（class="oe-norec-txt"）不是文案
                                if _ATTR_VALUE_TAIL_RE.search(head):
                                    continue
                                # ② py 的注释行不是渲染路径
                                if is_py and '#' in head:
                                    continue
                                hits.append((_src_priority(fp), '%s:%d' % (fp, i)))
                                break
                    except Exception:
                        continue
    except Exception:
        pass
    hits.sort(key=lambda x: x[0])
    out = [h for _p, h in hits[:limit]]
    _SRC_CACHE[needle] = out
    return out


# ---------------------------------------------------------------- HTTP
def make_session():
    s = requests.Session()          # cookie jar：session_id 全程复用
    s.trust_env = False             # 绕过系统代理，否则 localhost 走代理变 502
    return s


def login(login_name, password):
    s = make_session()
    try:
        r = s.post(BASE + '/web/session/authenticate', json={
            'jsonrpc': '2.0',
            'params': {'db': DB, 'login': login_name, 'password': password},
        }, timeout=20)
        ok = r.status_code == 200 and bool(r.json().get('result', {}).get('uid'))
    except Exception:
        ok = False
    return s, ok


def scan_role(role, verbose=True):
    if role == 'guest':
        sess, login_ok = make_session(), True
    else:
        login_name, password, _label = ROLES[role]
        sess, login_ok = login(login_name, password)
    label = ROLES.get(role, ('-', '-', '匿名'))[2]
    if verbose:
        print('== 角色 %s（%s）登录 %s' % (role, label, 'OK' if login_ok else 'FAIL'))
    if not login_ok:
        return dict(role=role, login=False, rows=[], totals=Counter())

    rows, totals = [], Counter()
    for path in routes_for(role):
        try:
            resp = sess.get(BASE + path, timeout=30, allow_redirects=False)
        except Exception as e:
            totals['route-status'] += 1
            rows.append(dict(path=path, status='EXC', route_bad=True,
                             note=str(e)[:60]))
            if verbose:
                print('  %-32s EXC ROUTE-BAD（期望 200）%s' % (path, str(e)[:40]))
            continue
        st = resp.status_code
        if 300 <= st < 400:
            loc = str(resp.headers.get('Location', ''))[:60]
            ok_route, why = route_status_ok(role, path, st, loc)
            if not ok_route:
                # t71：非 200 且未登记 → 门禁正在扫一个"空壳"（典型：改名后留下的 302 替身）
                totals['route-status'] += 1
                rows.append(dict(path=path, status=st, route_bad=True,
                                 note='ROUTE-BAD 未登记的非 200 -> ' + loc))
                if verbose:
                    print('  %-32s %s ROUTE-BAD 非 200 且未登记 → %s'
                          % (path, st, loc[:36]))
            else:
                rows.append(dict(path=path, status=st, note='REDIR -> ' + loc))
                if verbose:
                    print('  %-32s %s REDIR -> %-28s [%s]'
                          % (path, st, loc[:28], why[:34]))
            continue
        if st >= 400:
            totals['route-status'] += 1
            rows.append(dict(path=path, status=st, route_bad=True,
                             note='404 路由不存在' if st == 404 else 'HTTP %s' % st))
            if verbose:
                print('  %-32s %s ROUTE-BAD（期望 200）%s'
                      % (path, st, '路由不存在/已改名' if st == 404 else 'ERROR'))
            continue
        finds = scan_body(resp.text or '')
        counts = Counter(f['bucket'] for f in finds)
        for k, v in counts.items():
            totals[k] += v
        must = [f['value'] for f in finds if f['bucket'] == 'must-fix']
        # t84：夹具残留扫描（append-only 视图显式豁免，见 SMOKE_EXEMPT_ROUTES）
        exempt, smoke_n, smoke = smoke_leftover_for(path, resp.text or '')
        if exempt:
            smoke_n = -1                    # -1 = 本页豁免，明示"扫了但按规则不报"
        elif smoke_n:
            totals['smoke-leftover'] += smoke_n
        rows.append(dict(path=path, status=st, finds=finds, counts=dict(counts),
                         smoke_n=smoke_n, smoke=smoke))
        if verbose:
            flag = 'OK' if not must else 'MUST-FIX %d' % len(must)
            if smoke:
                flag += ' SMOKE-LEFTOVER %d' % smoke_n
                for _m, seg in smoke:
                    print('  %-32s %s 夹具残留 → %s' % (path, st, seg[:70]))
            detail = dict(Counter(must)) if must else ''
            extra = ' '.join('%s=%d' % (k, counts[k]) for k in ('whitelist', 'data', 'theme')
                             if counts.get(k))
            print('  %-32s %s %-12s %s %s' % (path, st, flag, detail, extra))
    return dict(role=role, login=True, rows=rows, totals=totals)


SELFTEST_HTML = """
<html><head><title>Odoo</title></head><body>
  <nav data-name="Navbar" aria-label="Main" class="navbar d-none d-lg-block">
    <a href="/" aria-label="Main"></a>
  </nav>
  <nav data-name="Navbar" aria-label="Mobile" class="navbar d-block d-lg-none"></nav>
  <div class="kicker">Hello World</div>
  <input name="search" placeholder="Search anything..." aria-label="Search"/>
  <a href="#" title="Notifications">铃</a>
  <img src="x.png" alt="Profile photo"/>
  <div>COVENANT REFORMED SEMINARY</div>
  <span>Zoom</span><a href="/my/lang/en_US" title="English">EN</a>
  <template name="Apply" t-name="apply.kicker"><div>Apply</div></template>
  <div>COVENANT · REFORMED · TRUTH</div>
  <span>CRS-MCS</span> <span>pdf</span> <span>txt</span> <span>md</span> <span>CRS-BTH</span>
  <span>Telegram</span><span>Administrator</span>
  <a href="#" title="转到您的Odoo应用程序">图标</a>
  <div>纯中文文案不该命中</div>
  <input placeholder="请输入关键词"/>
  <img src="y.png" alt=""/>
  <script>var englishWords = "should be ignored";</script>
  <div>EDU-2026-0001</div>
</body></html>
"""
SELFTEST_EXPECT = {
    'Hello World': 'must-fix',       # 文本节点
    'Odoo': 'must-fix',              # <title> 文本
    'Search anything...': 'must-fix',  # placeholder（已知例子，必须命中）
    'Search': 'must-fix',            # aria-label
    'Notifications': 'must-fix',     # title 属性
    'Profile photo': 'must-fix',     # alt
    'Main': 'theme',                 # 编辑器 navbar 区块（不是白名单掩盖）
    'Mobile': 'theme',
    'COVENANT REFORMED SEMINARY': 'whitelist',
    'COVENANT · REFORMED · TRUTH': 'whitelist',
    'Zoom': 'whitelist',
    'English': 'whitelist',
    'CRS-MCS': 'data',
    'CRS-BTH': 'data',
    'pdf': 'data',
    'txt': 'data',                   # 纯文本类后缀（真实资料上传不得触发门禁，队长 2026-09-12 定）
    'md': 'data',
    'EDU-2026-0001': 'data',         # 数据（编号）
    'EN': 'whitelist',               # 语言代码/自称（队长 2026-09-12：不算残留）
    'Telegram': 'whitelist',         # 第三方产品名（队长批准，与 Zoom 同性质）
    'Administrator': 'data',         # 账号显示名（res.users 数据，非模板文案）
    '转到您的Odoo应用程序': 'brand',   # 中英混排 + 品牌 token → brand（t37；纯中文不报）
}
SELFTEST_MUST_BE_ABSENT = {
    '请输入关键词',                    # 中文
    '纯中文文案不该命中',               # 纯中文（无品牌 token）不得命中
    'should be ignored',              # <script> 内
    'Apply',                          # 只出现在 <template name="Apply"> 里 → 结构性属性/模板不渲染
}


def selftest():
    finds = scan_body(SELFTEST_HTML)
    got = {}
    for f in finds:
        got.setdefault(f['value'], set()).add(f['bucket'])
    ok = True
    emitted = 0                     # 实际断言条数（与 SELFTEST_CASES 比对，漂移即 FAIL）
    print('== check_english 自证（属性扫描 + 五类分流）')
    for value, want in sorted(SELFTEST_EXPECT.items()):
        buckets = got.get(value, set())
        good = want in buckets
        ok = ok and good
        emitted += 1
        print('  %s %-28s 期望 %-9s 实际 %s' % ('PASS' if good else 'FAIL', value,
                                                want, ','.join(sorted(buckets)) or '未命中'))
    for value in sorted(SELFTEST_MUST_BE_ABSENT):
        good = value not in got
        ok = ok and good
        emitted += 1
        print('  %s %-28s 不应命中' % ('PASS' if good else 'FAIL', value))
    must = sorted({f['value'] for f in finds if f['bucket'] == 'must-fix'})
    print('  —— must-fix %s / 共 %d 条命中' % (must, len(finds)))
    # 自证机制自身也要被断言（照 check_view_xpath t57 的做法）
    fp = _self_fingerprint()
    good = len(fp) == 8 and all(c in '0123456789abcdef' for c in fp)
    ok = ok and good
    emitted += 1
    print('  %s %-28s 指纹 %s' % ('PASS' if good else 'FAIL', 'self_fingerprint', fp))
    # t71：新不变量的**构造反例**（离线、确定性；这条不变量必须被证明会红）
    inv_cases = [
        # (role, path, status, location, 期望放行?)
        ('guest', '/web/register', 302, '/register', False),      # 清单腐坏反例：替身
        ('guest', '/register', 200, '', True),                    # 真身
        ('student', '/apps', 303, '/my/home', True),               # 登记（三层落点）
        ('backoffice', '/login', 303, '/apps', True),               # 登记（内部用户 → 应用面板）
        ('student', '/my/points', 302, '/somewhere-else', False),  # 未登记的重定向 → 违规
        ('student', '/quiz/my', 404, '', False),                   # 登记过但 404 → 仍违规（只放行重定向）
    ]
    # t84：夹具残留不变量 —— 含**179 条反例样本**的形态（append-only 页伪造大量标记 → 必须不报）
    forged_live = '<div>【冒烟】作业 F3-0912</div><div>【冒烟】布告 F4-0912</div>'
    forged_history = ''.join('<tr><td>【冒烟】审计条目 %d</td></tr>' % i for i in range(179))
    smoke_cases = [
        # (路径, 伪造页面, 期望命中数>0?, 说明)
        ('/my/notice_board/notice', forged_live, True, '活体实体页含标记 → 必须点名'),
        ('/my/messages', forged_history, False, '179 条 append-only 通知 → 必须不报'),
        ('/edu/audit', forged_history, False, '审计留痕 append-only → 必须不报'),
        ('/my/home', '<div>干净页面</div>', False, '无标记 → 不报'),
    ]
    for _p, _h, _want, _why in smoke_cases:
        _ex, _n, _hits = smoke_leftover_for(_p, _h)
        _got = (_n > 0)
        good = (_got == _want)
        ok = ok and good
        emitted += 1
        print('  %s %-28s %s（%s）' % ('PASS' if good else 'FAIL',
                                       'smoke_leftover(%s)' % _p,
                                       '报警 %d' % _n if _got else '不报',
                                       _why))
    _blank = [k for k, v in SMOKE_EXEMPT_ROUTES.items() if not (v or '').strip()]
    good = not _blank
    ok = ok and good
    emitted += 1
    print('  %s %-28s %d 条豁免均写明理由%s'
          % ('PASS' if good else 'FAIL', 'smoke_exempt_reasons',
             len(SMOKE_EXEMPT_ROUTES), '' if good else '（缺理由：%s）' % _blank))

    # t103：并发守卫的**双向**反例（构造 ps 文本，不真跑脚本）
    _ps_running = ('  501 12345 1 0 0:01 ?? 0:00.05 python3 tests/smoke/F_roles_smoke.py' + chr(10)
                   + '  501 12346 1 0 0:01 ?? 0:00.03 python3 tests/smoke/assertion_audit.py')
    _ps_idle = ('  501 1 1 0 0:00 ?? 0:00.01 /usr/bin/ps -ef' + chr(10)
                + '  501 2 1 0 0:00 ?? 0:00.02 python3 scripts/check_english.py')
    for _label, _txt, _want in (('smoke_running(有并发)', _ps_running, True),
                                ('smoke_running(无并发)', _ps_idle, False)):
        _got = smoke_running(_txt)[0]
        good = (_got == _want)
        ok = ok and good
        emitted += 1
        print('  %s %-28s 期望 %s 实际 %s'
              % ('PASS' if good else 'FAIL', _label, _want, _got))
    for _label, _conc, _hits, _want in (
            ('smoke_verdict(有并发+命中)', True, ['x'], 'ENV_SKIP'),
            ('smoke_verdict(无并发+命中)', False, ['x'], 'REPORT'),
            ('smoke_verdict(无命中)', False, [], 'CLEAN')):
        _got = smoke_leftover_verdict(_conc, _hits)[0]
        good = (_got == _want)
        ok = ok and good
        emitted += 1
        print('  %s %-28s 期望 %s 实际 %s'
              % ('PASS' if good else 'FAIL', _label, _want, _got))

    for role, path, st, loc, want in inv_cases:
        got, _why = route_status_ok(role, path, st, loc)
        good = (got == want)
        ok = ok and good
        emitted += 1
        print('  %s %-28s %s->%s 期望%s 实际%s'
              % ('PASS' if good else 'FAIL', 'route_status_ok(%s)' % path,
                 st, loc or '-', '放行' if want else '违规',
                 '放行' if got else '违规'))
    # 名单读取的纯函数（B 组 2026-09-26 加：防「读取口径」悄悄漂移；不连服务、不读真实表）
    for _label, _got, _want in (
            # 候选**含路径自身**（不以动态段结尾时），调用方按「在不在扫描面内」过滤 ⇒ 自身自动出局
            ('static_ancestors(参数化子页)',
             static_ancestors('/my/child/<int:child_id>/leave'),
             ['/my/child/<int:child_id>/leave', '/my/child', '/my']),
            ('default_roles_for(portal)',
             sorted(default_roles_for({'student'}, 'portal')),
             sorted({'student', 'faculty', 'parent', 'backoffice'})),
            ('default_roles_for(public+anon)',
             sorted(default_roles_for({'anon'}, 'public')),
             sorted({'guest', 'student', 'faculty', 'parent', 'backoffice'}))):
        good = (_got == _want)
        ok = ok and good
        emitted += 1
        print('  %s %-28s 期望 %s 实际 %s' % ('PASS' if good else 'FAIL', _label, _want, _got))
    _keep, _drop = filter_legacy(['/in', '/out', '/'], {'/in'}, missing={'/'})
    for _label, _got, _want in (('filter_legacy(表外剔除)', _drop, ['/out']),
                                ('filter_legacy(补偿清单仍扫)', _keep, ['/in', '/'])):
        good = (_got == _want)
        ok = ok and good
        emitted += 1
        print('  %s %-28s 期望 %s 实际 %s' % ('PASS' if good else 'FAIL', _label, _want, _got))

    drift = emitted != SELFTEST_CASES
    ok = ok and not drift
    print('  %s %-28s 实际 %d / 声明 %d%s'
          % ('PASS' if not drift else 'FAIL', 'selftest_cases', emitted,
             SELFTEST_CASES, '' if not drift else '（漂移：请同步 SELFTEST_CASES）'))
    print('== 自证 %s == %s' % ('通过' if ok else '不通过', self_attest_line()))
    print('== 覆盖口径 == %s' % COVERAGE_DECLARATION.splitlines()[0])
    return 0 if ok else 1


def prove_invariant():
    """证明「被扫路由必须 200」不变量**会红**（t71 验收：检测本身要被证明会触发）。

    样本用**真实存在的改名替身** `/web/register`（302 → `/register`）：
      · 平时它不在任何清单里（清单扫的是真身 `/register` = 200）；
      · 注入后必须被判 ROUTE-BAD —— 否则说明这条不变量是死的。
    """
    print('== 不变量自证：把一个"改名替身"放进扫描清单，期望门禁报红 ==')
    print('   样本 = /web/register（302 → /register；2026-09-12 就是它让注册页整页从未被扫）')
    sess, _ = make_session(), None
    rows = []
    for role, path in (('guest', '/web/register'), ('guest', '/register')):
        try:
            resp = sess.get(BASE + path, timeout=25, allow_redirects=False)
            st = resp.status_code
            loc = str(resp.headers.get('Location', ''))
        except Exception as e:
            st, loc = 'EXC', str(e)[:40]
        ok_route, why = route_status_ok(role, path, st, loc)
        rows.append((path, st, loc, ok_route))
        print('   %-16s %-5s → %-28s %s' % (
            path, st, loc[:26] or '-',
            '放行（%s）' % why if ok_route else '**ROUTE-BAD：如期报红**'))
    alias_bad = [r for r in rows if r[0] == '/web/register' and not r[3]]
    real_ok = [r for r in rows if r[0] == '/register' and r[3]]
    good = bool(alias_bad) and bool(real_ok)
    print('== 结论：%s ==' % ('不变量有效（替身报红、真身放行）' if good
                              else '不变量失效（替身未报红或真身被误红）'))
    return 0 if good else 2


# ---------------------------------------------------------------- main
def run_roles(roles, json_out=None, quiet=False):
    # 名单来源（单一来源 = tests/ui/surface.json）；B 组 2026-09-26 起：
    #   「名单」来自表，「口径」（哪些角色看哪些页）留在脚本。
    plan, info, err = scan_plan()
    if err:
        print('INCOMPLETE：%s %s' % (SURFACE, err))
        print('  名单没有来源 ⇒ 本轮不扫、不判 FAIL（退出码 3）。登记表由 A 组维护，'
              '生成：python3 scripts/ui_surface_report.py --generate')
        print('  这里**不退回写死名单** —— 那等于把刚拆掉的第二份名单重新长出来。')
        return 3
    print_coverage(plan, info)
    # t103 并发守卫：开跑前探一次"是否有冒烟脚本在跑"（顺序很关键 —— 必须在扫描前取，
    # 否则别的脚本可能在我们扫到一半时才启动）。
    smoke_conc, smoke_procs = smoke_running()
    results, details, bad_login = [], [], []
    must_counter, brand_counter, other_counter = Counter(), Counter(), Counter()
    for role in roles:
        res = scan_role(role, verbose=not quiet)
        results.append(res)
        if not res['login']:
            bad_login.append(role)
            continue
        for row in res['rows']:
            for f in row.get('finds', []) or []:
                if f['bucket'] == 'must-fix':
                    must_counter[f['value']] += 1
                elif f['bucket'] == 'brand':
                    brand_counter[f['value']] += 1      # 品牌痕迹：中英混排，同样判失败（t37）
                else:
                    other_counter[(f['bucket'], f['value'])] += 1
                details.append(dict(role=role, path=row['path'], **f))
        print('')

    print('================ 汇总（验收口径：must-fix = 0 且 brand = 0）================')
    for res in results:
        if not res['login']:
            print('%-11s 登录失败，未扫描' % res['role'])
            continue
        t = res['totals']
        print('%-11s must-fix %-4d brand %-4d 白名单 %-4d 数据 %-4d 主题 %-4d '
              '路由违规 %-3d 夹具残留 %-3d（路由 %d 条）'
              % (res['role'], t.get('must-fix', 0), t.get('brand', 0), t.get('whitelist', 0),
                 t.get('data', 0), t.get('theme', 0), t.get('route-status', 0),
                 t.get('smoke-leftover', 0), len(res['rows'])))
        if smoke_conc and t.get('smoke-leftover', 0):
            print('            ↑ 夹具残留 %d（ENV：有冒烟在跑，不计入判据）'
                  % t.get('smoke-leftover', 0))
    total_must = sum(r['totals'].get('must-fix', 0) for r in results if r['login'])
    total_brand = sum(r['totals'].get('brand', 0) for r in results if r['login'])
    total_other = sum(sum(v for k, v in r['totals'].items() if k not in ('must-fix', 'brand'))
                      for r in results if r['login'])
    total_route_bad = sum(r['totals'].get('route-status', 0)
                          for r in results if r['login'])
    total_smoke_raw = sum(r['totals'].get('smoke-leftover', 0)
                          for r in results if r['login'])
    smoke_verdict, smoke_why = smoke_leftover_verdict(
        smoke_conc, [1] if total_smoke_raw else [])
    total_smoke = total_smoke_raw if smoke_verdict == 'REPORT' else 0
    if smoke_conc:
        print('  [ENV] 开跑时检测到冒烟脚本在跑（%d 个）⇒ 本轮 夹具残留 **标 ENV/跳过**（t103）：'
              % len(smoke_procs))
        for _p in smoke_procs[:3]:
            print('        · %s' % _p)
        print('        「环境正在被夹具使用」≠「数据泄漏」；【冒烟】标记本身**不豁免**，'
              '换个无并发的轮次仍会点名。')
    print('TOTAL must-fix = %d 条 / brand = %d 条 / **路由状态违规 = %d 条** / '
          '**夹具残留 = %d 条**（其余白名单/数据/主题合计 %d 条，不计失败）'
          % (total_must, total_brand, total_route_bad, total_smoke, total_other))
    if total_smoke_raw:
        print('  ⚠ 本轮扫描到 %d 处 %s 标记（%s）。'
              % (total_smoke_raw, SMOKE_MARKER, smoke_why))
        if smoke_verdict == 'REPORT':
            print('  ⚠ 夹具残留：扫描面出现 %s 标记 ⇒ **夹具跑完没走**（t84）。'
                  '要报的是"没走"，不是"来过"；append-only 视图已在 SMOKE_EXEMPT_ROUTES 登记豁免。'
                  % SMOKE_MARKER)
            print('　　判读提示：**在跑夹具与跑完没走的残留长得一样** ⇒ 先 `ps -ef | grep tests/smoke/` 交叉判读；'
                  '若命中项的 create_date 就在刚刚，那是**别的脚本正在跑**，不是残留。')
    if total_route_bad:
        print('  ⚠ 路由状态不变量：**被扫路由必须 200**；非 200 只允许'
              '「角色/匿名门禁跳 /my/home·/web」或 EXEMPT_ROUTES 显式登记。')
        print('    典型根因＝**改名后留下的 302 替身**（门禁拿到空响应体却一直报绿）。')
    # 自证行放在汇总处：贴这一行即可证明"跑的是哪一版、断言有几条、覆盖到哪"（t60）
    print('自证：%s' % self_attest_line())

    if must_counter:
        print('\n-- must-fix 清单（示例路由 + 来源文件:行号）--')
        for value, n in must_counter.most_common(40):
            ex = next(d for d in details if d['value'] == value and d['bucket'] == 'must-fix')
            srcs = source_of(value)
            print('  x%-4d %-36s 例: %s %s [%s]  来源: %s'
                  % (n, value[:36], ex['role'], ex['path'], ex['kind'],
                     '、'.join(srcs) if srcs else '（未在 custom_addons 找到，可能是 Odoo 自带或数据）'))
    if brand_counter:
        print('\n-- brand 清单（中英混排里的品牌痕迹；含 CJK 不再被跳过）--')
        for value, n in brand_counter.most_common(40):
            ex = next(d for d in details if d['value'] == value and d['bucket'] == 'brand')
            srcs = source_of(value)
            print('  x%-4d %-36s 例: %s %s [%s]  来源: %s'
                  % (n, value[:36], ex['role'], ex['path'], ex['kind'],
                     '、'.join(srcs) if srcs else '（未在 custom_addons 找到，可能是 Odoo 自带或数据）'))
    print('\n-- %s' % COVERAGE_DECLARATION.splitlines()[0])
    for _ln in COVERAGE_DECLARATION.splitlines()[1:]:
        print(_ln)
    if other_counter:
        print('\n-- 白名单/数据/主题（登记项，不判失败）--')
        for (bucket, value), n in other_counter.most_common(20):
            ex = next(d for d in details if d['value'] == value and d['bucket'] == bucket)
            print('  x%-4d [%-9s] %-32s 例: %s %s' % (n, bucket, value[:32], ex['role'], ex['path']))

    if json_out:
        with open(json_out, 'w', encoding='utf-8') as f:
            json.dump(dict(results=results, must_fix=dict(must_counter),
                           brand=dict(brand_counter),
                           registered={'%s/%s' % k: v for k, v in other_counter.items()}),
                      f, ensure_ascii=False, indent=1)
        print('-> %s' % json_out)

    if bad_login:
        return 1
    # 退出码契约（t84 归属说明）：0=全绿；1=登录/扫描失败；2=**有违规**
    # （must-fix / brand / 路由状态 / **夹具残留**）。夹具残留**单列一类**、
    # 不混进 must-fix（它不是"英文问题"），但同属"发现问题"⇒ 同样落 2。
    return 0 if (total_must == 0 and total_brand == 0
                 and total_route_bad == 0 and total_smoke == 0) else 2


def main():
    ap = argparse.ArgumentParser(description='可见英文门禁 v3.1（四类分流）')
    ap.add_argument('account', nargs='?', help='（兼容旧用法）单账号登录名')
    ap.add_argument('password', nargs='?', help='（兼容旧用法）单账号密码')
    ap.add_argument('--role', action='append', choices=ROLE_ORDER,
                    help='只扫指定角色，可重复；默认全部（guest + 四角色）')
    ap.add_argument('--json', dest='json_out', help='结果落盘 JSON 路径')
    ap.add_argument('--quiet', action='store_true', help='只输出汇总')
    ap.add_argument('--selftest', action='store_true', help='自证分类与属性扫描（不连服务）')
    ap.add_argument('--coverage', action='store_true', help='只打印覆盖/不覆盖声明（不连服务）')
    ap.add_argument('--list', action='store_true',
                    help='只读打印名单 + 对账（不连服务、不发请求）')
    ap.add_argument('--surface', default=None,
                    help='登记表路径（默认 tests/ui/surface.json）—— 审读/按冻结快照复算用')
    ap.add_argument('--prove-invariant', action='store_true',
                    help='证明「被扫路由必须 200」这条不变量**会红**（t71 验收要求）')
    args = ap.parse_args()

    if args.coverage:
        print('自证：%s' % self_attest_line())
        print(COVERAGE_DECLARATION)
        return 0
    if args.selftest:
        return selftest()
    if args.prove_invariant:
        return prove_invariant()

    # ---- 名单来源：tests/ui/surface.json（单一来源；B 组 2026-09-26 切换）----
    plan, info, serr = scan_plan(path=args.surface)
    if serr:
        print('INCOMPLETE：%s %s' % (SURFACE, serr))
        print('  名单没有来源 ⇒ 本轮不扫、不判 FAIL（退出码 3）。登记表由 A 组维护，'
              '生成：python3 scripts/ui_surface_report.py --generate')
        print('  这里**不退回写死名单** —— 那等于把刚拆掉的第二份名单重新长出来。')
        return 3
    if args.list:
        return print_list(plan, info)

    if args.account:  # 旧接口兼容：单账号扫描（名单同样来自表：口径 ∪ 补偿）
        table_paths = set(p for p, _r, _s in (info.get('static') or []))
        paths, _dropped = filter_legacy(
            PUBLIC_ROUTES + PORTAL_ROUTES + TEACHER_ROUTES, table_paths)
        s, ok = login(args.account, args.password or 'demo123')
        if not ok:
            print('login FAIL: %s' % args.account)
            return 1
        print('login OK: %s' % args.account)
        print_coverage({'guest': paths}, info, title='单账号扫描名单')
        must_counter, other_counter = Counter(), Counter()
        for path in paths:
            try:
                resp = s.get(BASE + path, timeout=30, allow_redirects=False)
            except Exception as e:
                print('%-34s EXC %s' % (path, str(e)[:50]))
                continue
            if resp.status_code != 200:
                print('%-34s %s (跳过)' % (path, resp.status_code))
                continue
            finds = scan_body(resp.text or '')
            must = [f['value'] for f in finds if f['bucket'] == 'must-fix']
            for f in finds:
                (must_counter if f['bucket'] == 'must-fix' else other_counter)[f['value']] += 1
            print('%-34s 200 must-fix=%s' % (path, dict(Counter(must)) or 0))
        n_must = sum(must_counter.values())
        print('\nTOTAL must-fix = %d（登记项 %d）' % (n_must, sum(other_counter.values())))
        print('must-fix 明细：' + (str(dict(must_counter)) if must_counter else '（无）'))
        print('自证：%s' % self_attest_line())
        return 0 if n_must == 0 else 2

    return run_roles(args.role or ROLE_ORDER, json_out=args.json_out, quiet=args.quiet)


if __name__ == '__main__':
    sys.exit(main())
