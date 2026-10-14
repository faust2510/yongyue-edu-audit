#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户 UI 表面清单（单一来源）与覆盖率量具（A 组 · 2026-09-26）。

触发事件：三个 UI 门禁**各写各的页面名单**，而且三份都是**手写清单**：
    tests/smoke/ux_v3_route_matrix.py   ROUTES 99 条（另有 3 条重定向强断言）
    scripts/check_accessibility.py      AUDIT_ROUTES 22 条
    scripts/check_english.py            PUBLIC/PORTAL/TEACHER 合计 88 条
三份名单互不一致，且**新页面自动落在名单外** —— 新模块 edu_assess 的门户页在
2026-09-18 之前零覆盖，不是因为它没问题，而是因为**没有任何人想起它**。
在「面」被定义之前，任何覆盖率读数都只是「名单很短」，而不是「覆盖率很高」。

不变式（本门禁给出的可复算读数）：
  1. tests/ui/surface.json 是**路由登记表**（单一来源）：custom_addons/**/*.py 里
     每条 @http.route 都要在册（本轮 277 条去重路径 = 页面 159 + 端点 118）；
     **覆盖率只量其中的门户页 120 条** —— 登记全、量得窄，这 120 条才是本次的分母；
  2. 在册行分两种：kind=page 且属门户范围的行，gates 要么非空（被门禁实际登记）、
     要么为空且写明 reason 并标 status=gap（缺口 = 分母里没有任何门禁看着的那部分）；
     其余行（公开站 / 登录 / 后台 / 写路由 / 导出端点）gates 为空时必须写 reason
     说明**为什么不需门禁覆盖** —— 这条同时是 E 组消费门禁
     （scripts/check_ui_surface.py）不变式 2 的要求，两边口径逐字对齐；
  3. surface.json 可由源码**重新生成**（--generate）：人工填过的 gates/status/
     evidence/roles 不得被覆盖；新路由自动补入；消失的路由保留并标出。
理由：门禁名单是人的记忆，会漏；表面清单是从源码抽的，不会漏。**先把面冻住**，
覆盖率才是一个有分母、可比较、能下降的数字。

设计约束：零环境依赖（不连 DB / 不发 HTTP / 不读容器 / 不 import odoo，停机可跑）；
退出码 0=OK 1=FAIL 2=ENV 3=INCOMPLETE；自证行 REVISION · 指纹 · 断言数 · 时刻。
**只读三个门禁脚本，不改它们**（补名单是 B 组的活）。

用法：
    python3 scripts/ui_surface_report.py --coverage    # 打印覆盖率与死角
    python3 scripts/ui_surface_report.py --generate    # 从路由重生成 tests/ui/surface.json
    python3 scripts/ui_surface_report.py               # 核对：surface.json 是否与源码同步
    python3 scripts/ui_surface_report.py --selftest    # 反例自检（/tmp 夹具，不碰真仓库）

退出码：
    0=OK          核对模式：surface.json 与源码一致；--coverage：量具跑通
    1=FAIL        surface.json 里有源码已不存在的幽灵路由 / 生成失败
    2=ENV         仓库结构不对（缺 custom_addons / 缺门禁脚本 / 缺 surface.json）
    3=INCOMPLETE  源码里有门户页面尚未登记进 surface.json —— 需要 --generate

============================ 冻结的口径（与 E 组逐字一致）============================
kind   : page ｜ endpoint（导出 / 文件 / 数据接口）
scope  : portal ｜ public ｜ endpoint ｜ retired ｜ other（**本轮新增**，队长 2026-09-26 裁定：
         把「范围」变成机器可读的；覆盖率只量 scope=='portal'。判据见 row_scope + RETIRED_MODULES）
gates  : 门禁名闭集 route_matrix ｜ accessibility ｜ english ｜ ui_surface。
         **语义收紧（队长 2026-09-26 二次裁定）：gates = 实际探这条 URL 的门禁。**
         「上级列表页在名单里」不算覆盖本页（那会制造假绿）—— 该补进哪个门禁写 pending_gate。
pending_gate : route_matrix ｜ accessibility ｜ english ｜ ''（**待办不是覆盖**：值 = 它**应该**
         被哪个门禁探；取上级门禁里排序最靠前的一个。补样本 id 的来源见该行 evidence）
status : unverified ｜ verified ｜ gap ｜ n/a（n/a = 退役模块的行，不适用任何门禁）
roles  : student ｜ faculty ｜ parent ｜ backoffice ｜ admin ｜ anon
         取自 ux_v3_route_matrix.py 的 USERS 账号 stu@ / faculty@ / parent@ /
         backoffice@ / admin（去掉域名后的身份名；E 组冻结示例用的就是
         backoffice / faculty 这组写法）。与矩阵内部短键的映射：
             stu -> student ｜ fac -> faculty ｜ par -> parent ｜ bo -> backoffice
reason : 仅当 gates 为空数组时必填（gates 为空 = 没人登记它；gap 行在这里写明
         「为什么它是缺口」，有登记的登记行留空字符串）
====================================================================================

抽取口径（**装饰器括号配对**，可复算；读数见 --coverage 的自证段）：
  0) 抽取方式 = **装饰器括号配对**：逐文件定位 @http.route( ，向右做括号配对拿到整个
     调用体（字符串与注释里的括号不计），再从调用体内取**所有**以 / 开头的字符串
     字面量。**不用单字符串正则** —— 正则 @http.route\\(\\s*['\"]([^'\"]+)['\"] 会
     漏掉 5 处列表形式 @http.route([...])（共 6 条路由：/my/evaluation/new、
     /my/child/<int:child_id>、/my/child/<int:child_id>/leave、
     /my/child/<int:child_id>/leave/saved、/campus/jobs/<int:posting_id>、
     /campus/jobs/<int:posting_id>/sent），其中 4 条是家长门户页。
     另用 ast 做**交叉核对**（两条路径必须给出同一路径集，差集非空即点名）。
  1) 声明：命中上一步的 (声明, 路径) 对 => 295 条；其中 1 条声明的路径是变量
     （edu_tg_bind 的 webhook 常量），静态抽不到 —— --coverage 逐条点名，不静默吞。
  2) 去重：按路径字符串去重（首个声明胜）=> 277 条不同路径。
  3) 分流：有 methods 且不含 GET => 写路由 88 条；否则可读路由 189 条。
  4) 页面 vs 端点：路径命中 (export|download|/file|[.]xlsx|[.]csv|/pdf|[.]json|blank|
     report)（忽略大小写）或含 /data/ 或含 /ics/ => 端点 30 条；其余页面 159 条。
  5) 门户：路径命中门户前缀（PORTAL_HEADS，见 is_portal 的逐段判据）的**页面**
     => 门户页 120 条（本次范围）。
  6) 覆盖：门禁登记集 ∩ 门户页；匹配 = 路径**精确相等**。不做参数归一化 ——
     归一化会把「详情页 vs 列表页」合并，而那正是本轮要量出来的那类死角。
     登记集取：
       route_matrix  = ROUTES 的首元素 ＋ REDIRECT_STRICT / REDIRECT_STRICT_BY_ROLE 里
                       **所有以 / 开头的字符串**（含被强断言的落点，如 /my/checkins/export）
       accessibility = AUDIT_ROUTES 的路径（含 guest 公开页）
       english       = PUBLIC_ROUTES ∪ PORTAL_ROUTES ∪ TEACHER_ROUTES
     route_matrix 连落点一起收：E 组消费门禁按「脚本里的路由字面量」比对（不变式 3），
     只收首元素会让落点路径显示成「没人登记」，两边每天互相报红。
  7) 登记：全部 277 条去重路径都写进 surface.json（不只门户页）——
     kind=page（159）｜ kind=endpoint（118 = 30 条导出/数据端点 + 88 条写路由）；
     非门户行填 reason（为什么不需门禁），门户行填 gates/status。
     消费方 = scripts/check_ui_surface.py（E 组），本脚本与它逐条对齐。
  8) 覆盖读数**三数并列，不许合并**（队长 2026-09-26 二次裁定）：
       门禁真探 M（gates 非空 = 真的有条门禁探这条 URL）
       待补样本 P（pending_gate 已定：上级已在某门禁名单里，本页没被探过）
       无着落 K（连上级门禁都没有，要人判）
     M + P + K = 门户页数。把 P 记进 M 就是用没量过的数字冒充覆盖。
"""
import argparse
import ast
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime

REVISION = 'v1.0'
SELFTEST_CASES = 25          # 反例断言条数（实际计数比对，漂移即 FAIL）
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ADDONS = 'custom_addons'
SURFACE = os.path.join('tests', 'ui', 'surface.json')
SURFACE_VERSION = 'v1'
SOURCE_DESC = 'custom_addons/**/*.py :: @http.route'
# 门禁形态判据（与 E 组 check_ui_surface.py 同款）：脚本文本里出现这个标记 ⇒ 该门禁已改成
# **从 surface.json 读名单**（形态 B，B 组 2026-09-26 起逐脚本迁移）。此时它的登记集 =
# 表里 gates 含该门禁的行 —— 必须从表里读回来，否则读数会崩成「只剩脚本里的残留字面量」。
FROM_FILE_MARK = 'surface.json'

GATE_FILES = {
    'route_matrix': os.path.join('tests', 'smoke', 'ux_v3_route_matrix.py'),
    'accessibility': os.path.join('scripts', 'check_accessibility.py'),
    'english': os.path.join('scripts', 'check_english.py'),
}
# 门禁名闭集（冻结）。ui_surface = 本脚本自己：本轮**不给自己记覆盖** ——
# 它现在只负责「读表」，还没开始逐条断言；给自己记覆盖会把 45 条死角一夜清零。
GATE_NAMES = ('route_matrix', 'accessibility', 'english', 'ui_surface')
COUNTED_GATES = ('route_matrix', 'accessibility', 'english')

KINDS = ('page', 'endpoint')
# 行的**范围**（2026-09-26 队长裁定新增，additive：E 组消费门禁只校验 kind/gates/reason，
# 多余字段忽略）。判据见 row_scope()：
#   portal   = kind=page 且命中门户前缀（= 本次 UI 优化的目标集，120 条）
#   public   = kind=page、非门户、且 auth='public'（匿名可访问的公开站 / 营销 / 帮助页）
#   endpoint = kind=endpoint（导出 / 文件 / 数据接口，含 methods 不含 GET 的写路由）
#   other    = 其余（登录 / 注册 / 后台兼容路由等，需登录或内部使用）
# **覆盖率只量 scope=='portal'** —— 让下一个人不必再靠前缀正则重新推导目标集。
SCOPES = ('portal', 'public', 'endpoint', 'retired', 'other')
# 退役模块登记：**本仓代码快照里有、但生产上不存在**的模块。命中它的行 scope='retired'、
# status='n/a'、gates=[]（不纳入门禁，也不进覆盖率分母）。
# 判据（队长 2026-09-26 查证）：① scripts/deploy_myedu.sh 的部署模块清单里没有它；
#   ② docs/code-map.md:142-144 明写「从未部署；2026-09-17 用户裁定退役」；
#   ③ 弃用台账 docs/audit/deprecated-inventory.md §B8 同款登记。
# ⚠ 同名不同物的雷：生产上跑着的 edu_telegram 是**另一个模块**（匿名意见收集机器人），
#   本仓这只是 v2.2 历史快照 —— 所以不能按模块名去生产上找这些路由。
RETIRED_MODULES = {
    'edu_telegram': '本仓 edu_telegram v2.2 已退役、从未部署（deploy_myedu.sh 不含）；'
                    '生产上同名模块是另一个（匿名意见箱）——代码快照同名不同物',
}
# n/a = 不适用（退役模块的行：既不缺口也不可能被门禁覆盖），队长 2026-09-26 裁定新增。
STATUSES = ('unverified', 'verified', 'gap', 'n/a')
ROLES = ('student', 'faculty', 'parent', 'backoffice', 'admin', 'anon')
ROLE_SHORT = {'stu': 'student', 'fac': 'faculty', 'par': 'parent',
              'bo': 'backoffice', 'admin': 'admin'}
LOGGED_ROLES = ('student', 'faculty', 'parent', 'backoffice')
DEFAULT_LOGGED = list(LOGGED_ROLES)

# 门户页前缀（本次范围，冻结）
PORTAL_HEADS = ('my', 'student', 'registrar', 'leave', 'grading', 'timetable', 'eval',
                'assess', 'quiz', 'ledger', 'attendance', 'course', 'subject',
                'checkins', 'journals', 'downloads', 'help', 'library', 'my-library',
                'certificate', 'meeting', 'online', 'users', 'requested', 'result',
                'fees', 'assets', 'jobs', 'parent', 'class')
# 端点判据（队长的规则，去掉前导斜杠那一处笔误；全部用字符类写，便于复核）
ENDPOINT_TOKENS = ('export', 'download', '/file', '.xlsx', '.csv', '/pdf', '.json',
                   'blank', 'report')
# handler 源码里的身份谓词 -> 允许身份（本仓既有 helper：
# edu_schedule.models.identity 的 *_of_user、edu_portal/controllers/roles.py 的
# privileged_staff / current_student / current_faculty / current_parent，
# 以及 edu_assess / edu_quiz / edu_life 的模块内同名私有 helper）。
ROLE_TOKENS = (
    (('current_student', 'student_of_user', 'self._student'), ('student',)),
    (('current_faculty', 'faculty_of_user', '_faculty_or_none', '_is_teacher',
      '_require_teacher', 'self._teacher'), ('faculty',)),
    (('current_parent', 'parent_of_user'), ('parent',)),
    (('privileged_staff', '_is_school_admin', '_is_staff', '_materials_admin',
      'require_internal', 'group_op_back_office_admin'), ('backoffice', 'admin')),
    (('base.group_system',), ('admin',)),
)

ROUTE_CALL_RE = re.compile('[@](http[.])?route[(]')
STR_VALUE_RE = re.compile('["' + chr(39) + ']([^"' + chr(39) + ']*)["' + chr(39) + ']')
METHODS_RE = re.compile('methods\\s*=\\s*\\[([^]]*)\\]')
QM = chr(39)
NEWLINE = chr(10)


def self_fingerprint():
    """自身文件 md5 前 8 位（运行时算；不靠人 bump）。"""
    try:
        with open(os.path.abspath(__file__), 'rb') as fh:
            return hashlib.md5(fh.read()).hexdigest()[:8]
    except OSError:
        return '????????'


# ------------------------------------------------------------------ 抽取：装饰器括号配对
def _pair_paren(text, i):
    """从 text[i] == '(' 起配对括号 -> (调用体文本, 结束下标)；配不上返回 (None, len)。

    字符串字面量与 # 注释里的括号**不计入深度** —— 否则一句
    @http.route('/a', website=True)  # 说明（含括号）
    就会把配对带偏。这是本函数唯一的难点，反例见 --selftest。
    """
    depth, j, n = 0, i, len(text)
    quote = None
    while j < n:
        c = text[j]
        if quote:
            if c == chr(92):
                j += 2
                continue
            if c == quote:
                quote = None
        elif c in ('"', QM):
            quote = c
        elif c == '#':
            k = text.find(NEWLINE, j)
            j = n if k < 0 else k
            continue
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j
        j += 1
    return None, n


def _methods_in_body(body):
    """调用体里的 methods=[...] -> 方法名集合；没有该关键字返回 None。"""
    m = METHODS_RE.search(body or '')
    if not m:
        return None
    return set(x.upper() for x in STR_VALUE_RE.findall(m.group(1)))


def scan_text_routes(text):
    """括号配对扫 @http.route(...) -> ([dict(path, line, methods)], [无路径的声明行])。

    **这是本脚本的主口径**（队长 2026-09-26 修正）：取调用体内**所有**以 / 开头的
    字符串字面量。列表形式 @http.route([...]) 因此自然被覆盖 ——
    单字符串正则 @http.route\\(\\s*['\"]([^'\"]+)['\"] 会漏掉它们（本仓 5 处、6 条路由）。
    """
    out, empty = [], []
    for m in ROUTE_CALL_RE.finditer(text):
        body, _end = _pair_paren(text, m.end() - 1)
        if body is None:
            continue
        line = text.count(NEWLINE, 0, m.start()) + 1
        paths = [v for v in STR_VALUE_RE.findall(body) if v.startswith('/')]
        methods = _methods_in_body(body)
        if not paths:
            empty.append(line)
        for p in paths:
            out.append(dict(path=p, line=line, methods=methods, body=body))
    return out, empty


def scan_ast_routes(text):
    """ast 结构化扫同一批声明 -> ([(path, line, methods, auth, node)], 非字面量声明列表)。

    与 scan_text_routes 是**两条独立路径**，用来交叉核对（差集非空即点名）。
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None, None
    hits, nonliteral = [], []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            f = dec.func if isinstance(dec, ast.Call) else dec
            if (getattr(f, 'attr', None) or getattr(f, 'id', None)) != 'route':
                continue
            kw, arg = {}, None
            if isinstance(dec, ast.Call):
                if dec.args:
                    try:
                        arg = ast.literal_eval(dec.args[0])
                    except Exception:
                        arg = None
                for k in dec.keywords:
                    if k.arg:
                        try:
                            kw[k.arg] = ast.literal_eval(k.value)
                        except Exception:
                            kw[k.arg] = None
            paths = [arg] if isinstance(arg, str) else (
                [x for x in arg if isinstance(x, str)] if isinstance(arg, list) else [])
            for p in paths:
                hits.append(dict(path=p, line=node.lineno, methods=kw.get('methods'),
                                 auth=kw.get('auth'), func=node.name, node=node))
            if not paths:
                nonliteral.append(dict(line=node.lineno, func=node.name,
                                       kind=('list' if isinstance(arg, list)
                                             else 'variable' if arg is None
                                             else type(arg).__name__),
                                       raw=list(arg) if isinstance(arg, list) else []))
    return hits, nonliteral


def extract_routes(modules_dir=None, repo=None):
    """扫全部 @http.route -> (decls, nonliteral, notes)。

    decls = 每个 (声明, 路径) 一条：dict(path, module, file, line, func, methods, auth)。
    nonliteral = 路径抽不到的声明（点名，不静默吞）。
    notes = 抽取期内需要报告的事实（交叉核对差集、ast 不可解析的文件）。
    """
    base = repo or REPO
    root = modules_dir or os.path.join(base, ADDONS)
    decls, nonliteral, notes = [], [], []
    if not os.path.isdir(root):
        return decls, nonliteral, notes
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != '__pycache__']
        for fn in sorted(fns):
            if not fn.endswith('.py'):
                continue
            fpath = os.path.join(dp, fn)
            try:
                with io.open(fpath, encoding='utf-8') as fh:
                    text = fh.read()
            except OSError:
                continue
            rel = os.path.relpath(fpath, base)
            parts = rel.split(os.sep)
            module = parts[1] if len(parts) > 1 else ''
            text_hits, text_empty = scan_text_routes(text)
            ast_hits, ast_nonliteral = scan_ast_routes(text)
            if ast_hits is None:
                notes.append('%s：ast 解析失败，只用括号配对（%d 条路径）'
                             % (rel, len(text_hits)))
                ast_hits, ast_nonliteral = [], None
            tp = set(h['path'] for h in text_hits)
            ap = set(h['path'] for h in ast_hits)
            if tp != ap:
                notes.append('%s：抽取分歧 括号配对独有 %s ｜ ast 独有 %s'
                             % (rel, sorted(tp - ap), sorted(ap - tp)))
            # 富字段（methods/auth/func/node）以 ast 为准；缺用时退回文本口径
            rich = {}
            for h in ast_hits:
                rich.setdefault(h['path'], h)
            for h in text_hits:
                r = rich.get(h['path']) or {}
                decls.append(dict(path=h['path'], module=module, file=rel,
                                  line=h.get('line') or r.get('line'),
                                  func=r.get('func') or '', methods=r.get('methods', h.get('methods')),
                                  auth=r.get('auth'), node=r.get('node')))
            # 路径抽不到的声明一律点名（不静默吞）：ast 有解析就用它的，
            # ast 解析不了才退回文本口径的"这次调用里没有 / 开头的字面量"。
            nl_src = ast_nonliteral if ast_nonliteral is not None else [
                dict(line=l, func='', kind='unparsed', raw=[]) for l in text_empty]
            for nl in (nl_src or []):
                rec = dict(nl)
                rec.update(file=rel, module=module)
                nonliteral.append(rec)
    return decls, nonliteral, notes


def dedupe_by_path(decls):
    """按路径字符串去重（首个声明胜）-> {path: decl}。"""
    out = {}
    for r in decls:
        out.setdefault(r['path'], r)
    return out


def ast_paths_of(repo=None, modules_dir=None):
    """独立复算 ast 路径集（交叉核对用，不做富字段装配）。"""
    base = repo or REPO
    root = modules_dir or os.path.join(base, ADDONS)
    out = set()
    if not os.path.isdir(root):
        return out
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != '__pycache__']
        for fn in sorted(fns):
            if not fn.endswith('.py'):
                continue
            try:
                with io.open(os.path.join(dp, fn), encoding='utf-8') as fh:
                    text = fh.read()
            except OSError:
                continue
            hits, _nl = scan_ast_routes(text)
            for h in hits or []:
                out.add(h['path'])
    return out


def is_write(decl):
    methods = [str(m).upper() for m in (decl.get('methods') or [])]
    return bool(methods) and 'GET' not in methods


def is_endpoint(path):
    low = path.lower()
    for tok in ENDPOINT_TOKENS:
        if tok in low:
            return True
    return '/data/' in path or '/ics/' in path


def is_portal(path):
    """门户前缀判据（逐段；等价于 ^/(my|...|class) 后跟词边界）：
      /my                    命中（前缀本身）
      /my/courses            命中（后接 /）
      /my/child/<int:...>    命中（后接 <）
      /my-courses            命中（后接 -，即词边界）
      /online-exams          命中；/courses、/courses-offered 不命中（course 后接 s）
    """
    for head in PORTAL_HEADS:
        p = '/' + head
        if path == p:
            return True
        if path.startswith(p) and len(path) > len(p) and path[len(p)] in ('/', '<', '-'):
            return True
    return False


def make_key(path, taken=None):
    """路径 -> 稳定 slug：'/leave/approvals/<int:leave_id>' -> 'leave_approvals_detail'。"""
    segs = []
    for s in [x for x in path.split('/') if x]:
        if s.startswith('<') and s.endswith('>'):
            segs.append('detail')
        else:
            segs.append(re.sub('[^0-9a-zA-Z]+', '_', s).strip('_'))
    key = '_'.join(x for x in segs if x) or 'root'
    if taken is not None:
        base, n = key, 2
        while key in taken:
            key = '%s_%d' % (base, n)
            n += 1
    return key


# ------------------------------------------------------------------ 门禁登记集
def _assignments(tree):
    out = {}
    for node in getattr(tree, 'body', []):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value
    return out


def _name_sets(tree):
    """模块级「名字 -> 字符串集合」映射（ALL5 = {...} 这类角色常量）。"""
    out = {}
    for name, node in _assignments(tree).items():
        vals = None
        if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
            try:
                vals = [ast.literal_eval(e) for e in node.elts]
            except Exception:
                vals = None
        if vals and all(isinstance(v, str) for v in vals):
            out[name] = set(vals)
    return out


def _str_list(node):
    if not isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        return []
    out = []
    for e in node.elts:
        try:
            v = ast.literal_eval(e)
        except Exception:
            v = None
        if isinstance(v, str):
            out.append(v)
    return out


def _tuple_heads(node):
    """ROUTES / REDIRECT_STRICT 这类「元组列表」-> 每行第一个字符串元素。"""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    out = []
    for el in node.elts:
        if isinstance(el, (ast.Tuple, ast.List)) and el.elts:
            try:
                v = ast.literal_eval(el.elts[0])
            except Exception:
                v = None
            if isinstance(v, str):
                out.append(v)
    return out


def _tuple_paths(node):
    """元组列表 -> 每行里**所有以 / 开头的字符串**（含重定向的落点）。

    为什么要连落点一起收：REDIRECT_STRICT 的第二/第三个字符串是被**强断言**的
    落点路径（Location 精确相等），只收第一个元素会让 /my/checkins/export 这类
    落点路径在表里显示成「没人登记」—— E 组的消费门禁
    （scripts/check_ui_surface.py，不变式 3）按脚本里的**路由字面量**比对，
    两边口径必须一致，否则每天互相报红。
    """
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    out = []
    for el in node.elts:
        if not isinstance(el, (ast.Tuple, ast.List)):
            continue
        for sub in el.elts:
            try:
                v = ast.literal_eval(sub)
            except Exception:
                v = None
            if isinstance(v, str) and v.startswith('/'):
                out.append(v)
    return out


def load_gates(repo=None, surface_doc=None):
    """读三个门禁的登记集 -> (gates, matrix_roles, 缺失文件列表, 形态表)。

    **两种形态都要认**（B 组 2026-09-26 起逐脚本迁移，混合态是常态）：
      · 形态 A（脚本自带名单）：按名单解析。route_matrix 的登记集 = ROUTES ∪
        REDIRECT_STRICT ∪ REDIRECT_STRICT_BY_ROLE（后两张是同样在跑的强断言；
        /my/checkin/save 只被 REDIRECT_STRICT 覆盖，只读 ROUTES 会把它误判成死角）。
      · 形态 B（脚本文本含 surface.json ⇒ 已改成**从表读**）：该门禁的登记集 =
        **表里 gates 含该门禁的行**。必须从表里读回来 —— 否则读数会崩成「只剩脚本里
        残留的字面量」（实测：矩阵切形态 B 后，真探数从 68 掉到 5，全是这个原因）。
    """
    base = repo or REPO
    gates, roles_by_path, missing, modes = {}, {}, [], {}
    rows = (surface_doc or {}).get('pages') or []
    for gname, rel in GATE_FILES.items():
        path = os.path.join(base, rel)
        try:
            with io.open(path, encoding='utf-8') as fh:
                text = fh.read()
        except OSError:
            missing.append(rel)
            gates[gname] = set()
            modes[gname] = 'missing'
            continue
        if FROM_FILE_MARK in text:
            # 形态 B：名单就在表里（「gates 含本门禁的行」就是它的名单）
            modes[gname] = 'surface'
            gates[gname] = set(r.get('path') for r in rows
                               if isinstance(r, dict)
                               and gname in (r.get('gates') or []))
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            tree = None
        if tree is None:
            missing.append(rel)
            gates[gname] = set()
            modes[gname] = 'broken'
            continue
        modes[gname] = 'hardcoded'
        asg = _assignments(tree)
        consts = _name_sets(tree)
        if gname == 'route_matrix':
            paths = set(_tuple_heads(asg.get('ROUTES')))
            paths |= set(_tuple_paths(asg.get('REDIRECT_STRICT')))
            paths |= set(_tuple_paths(asg.get('REDIRECT_STRICT_BY_ROLE')))
            routes = asg.get('ROUTES')
            els = routes.elts if isinstance(routes, (ast.List, ast.Tuple)) else []
            for el in els:
                if not isinstance(el, (ast.Tuple, ast.List)) or not el.elts:
                    continue
                try:
                    p = ast.literal_eval(el.elts[0])
                except Exception:
                    p = None
                exp = el.elts[1] if len(el.elts) > 1 else None
                short = set()
                if isinstance(exp, ast.Name):
                    short = consts.get(exp.id, set())
                elif isinstance(exp, (ast.Set, ast.Tuple, ast.List)):
                    short = set(_str_list(exp))
                if isinstance(p, str) and short:
                    roles_by_path[p] = set(
                        ROLE_SHORT[s] for s in short if s in ROLE_SHORT)
        elif gname == 'accessibility':
            paths = set()
            aud = asg.get('AUDIT_ROUTES')
            els = aud.elts if isinstance(aud, (ast.List, ast.Tuple)) else []
            for el in els:
                if isinstance(el, (ast.Tuple, ast.List)) and len(el.elts) >= 2:
                    try:
                        v = ast.literal_eval(el.elts[1])
                    except Exception:
                        v = None
                    if isinstance(v, str):
                        paths.add(v)
        else:
            paths = set()
            for key in ('PUBLIC_ROUTES', 'PORTAL_ROUTES', 'TEACHER_ROUTES'):
                paths |= set(_str_list(asg.get(key)))
        gates[gname] = paths
    return gates, roles_by_path, missing, modes


# route_matrix 的**期望角色集**回填（队长 2026-09-26 裁定）。
# 为什么需要：B 组把矩阵从「脚本写死 ROUTES」迁到「读 surface.json」时，
# **只搬了「覆盖哪些页」，没搬「用什么身份断言什么」** —— 迁移后 91 条的 roles
# 与旧期望不一致，其中 22 条与探针角色**无交集** ⇒ 矩阵对它们不再断言「必须 200」，
# 只判「不 5xx / 不 404」（**静默削弱**）。本表把旧脚本写死的期望集搬回来，
# 由 roles_for() 以**最高优先级**采用（高于矩阵登记 / handler 扫描 / 兜底）。
#
# ⚠ 2026-09-28（B 组）实测：本表**对已登记的行不生效** —— merge_rows()（本文件 :1049-1050）
#   「prev.roles 非空即保留」优先于 roles_for()，所以表里那 22 条 anon-only 行的期望集
#   并不会因为 --generate 被填上（本表只在**新登记**的行上用到）。后果：矩阵至今仍对这 22 条
#   不做「必须 200」断言，只判「不 5xx / 不 404」——矩阵每次运行都会打印
#   「⚠ 表 roles 与探针角色无交集 22 条」把这件事显式说出来。
#   本轮按**两条证据**（① 源码 @http.route 的 auth= / 正文是否有角色判定；
#   ② 真机逐身份实测 http 码）把其中 19 条回填进 tests/ui/surface.json（表指纹 786809f8 → 921c3dc6）：
#   这 19 条源码侧全是 auth='public' 且正文无 _require_*/redirect（edu_brand/controllers/main.py:12,16,20,24；
#   edu_public/controllers/main.py:43,74,89,141,148,161,213,247,253；edu_apply/controllers/main.py:64；
#   edu_portal/controllers/help_center.py:35,40,45,50,55），真机侧 5 个身份**全部直接 200**
#   （矩阵全量跑两遍：10:29 与 10:43 各 480/480 PASS）。回填后矩阵期望集为空的只剩 3 条。
#   剩 3 条**故意不填** —— 它们的行为是「按设计跳转」，填成「必须 200」就是假断言：
#     · /apps         auth='public' 但正文对 stu/par 303→/my/home（edu_portal/controllers/main.py:317；
#                     该行为已由矩阵 REDIRECT_STRICT_BY_ROLE 强断言接管）；fac/bo/admin 实测 200。
#     · /login        已登录身份一律 303→/my/home（教务/管理 303→/web），只有匿名 200
#                     （edu_portal/controllers/main.py:255 起）。
#     · /web/register 已登录 303→/my/home、匿名 302→/register（main.py:359 / register.py:66）。
#   回填后矩阵的 ⚠ 由 22 条降到 3 条（正是上面三条）。要让本表对存量行也生效，必须同时改
#   merge_rows 的保留策略 —— 那是表生成口径变更，需队长裁定，本轮未做。
ROLE_BACKFILL = {
    '/about': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/admissions': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/alumni': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/alumni/jobs': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/apply': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/apps': ('backoffice', 'faculty', 'parent', 'student',),
    '/assignment/manage': ('backoffice', 'faculty',),
    '/assignment/publish': ('backoffice', 'faculty',),
    '/attendance/take': ('backoffice', 'faculty',),
    '/booking': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/campus/jobs': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/certificate': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/checkins/stats': ('backoffice', 'faculty',),
    '/course/change/request': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/courses': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/courses-offered': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/digital-library': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/downloads': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/downloads/manage': ('admin', 'backoffice',),
    '/downloads/mine': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/downloads/stats': ('admin', 'backoffice',),
    '/edu/audit': ('backoffice',),
    '/edu/import/students': ('backoffice',),
    # 2026-09-29：edu_eval（行政评估）已删 ⇒ 旧地址 /eval/my、/eval/review 现为 404，
    # 本表改登记新引擎 edu_assess 的同义页（学生门户页 / 教师·教务审阅页）。
    '/assess/my': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/assess/review': ('backoffice', 'faculty',),
    '/grade-book': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/grading/entry': ('backoffice', 'faculty',),
    '/grievances/approvals': ('backoffice', 'faculty',),
    '/help': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/help/faculty': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/help/parent': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/help/registrar': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/help/student': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/journal': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/journals/review': ('backoffice', 'faculty',),
    '/leave/approvals': ('backoffice', 'faculty',),
    '/ledger': ('backoffice',),
    '/ledger/new': ('backoffice',),
    '/ledger/reimburse': ('backoffice', 'faculty',),
    '/library/media': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/login': ('backoffice', 'faculty', 'parent', 'student',),
    '/meeting/information': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my-courses': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my-library': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/academic-calendar': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/apps': ('backoffice', 'faculty', 'parent', 'student',),
    '/my/asset-request': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/assets': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/calendar': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/checkin': ('student',),
    '/my/checkin/board': ('backoffice', 'faculty',),
    '/my/checkins': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/contacts': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/courses': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/dms': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/evaluation': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/evaluation/results': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/fees': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/grievances': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/help': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/home': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/journals': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/messages': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/notice_board/notice': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/notify': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/password': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/points': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/search': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/study': ('backoffice', 'faculty', 'parent', 'student',),
    '/my/thesis': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/my/time_off': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/notice/publish': ('backoffice', 'faculty',),
    '/online-exams': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/online/meeting': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/program-offered': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/programs': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/quiz': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/registrar/subject/approvals': ('backoffice',),
    '/requested/queue/list': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/student/assignment/details': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/student/attendance': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/student/exam': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/student/profile': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/student/progression': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/student/timetable': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/subject/details': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/subject/registration': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/timetable/bulk': ('backoffice', 'faculty',),
    '/users/result-overview': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
    '/web/register': ('admin', 'backoffice', 'faculty', 'parent', 'student',),
}


# **表内非仓内路由**：它不在 custom_addons 的 @http.route 里（由 Odoo website 核心渲染），
# 但三张门禁都真的会探它，所以必须登记。队长 2026-09-26 裁定；E 组已落 ALLOW_NO_ROUTE
# 例外（命中不报 [stale]，且打 ALLOW 行 —— 可见、非静默），并已用真表做过端到端证明。
# roles 取旧矩阵对该页的期望集（ALL5 = 五个身份都该 200）。
EXTRA_ROUTES = (
    dict(path='/', module='(odoo-website-core)', kind='page', scope='public',
         roles=['admin', 'backoffice', 'faculty', 'parent', 'student'],
         gates=['route_matrix', 'accessibility', 'english'],
         pending_gate='', pending_parent=None, sample_note=None,
         auth='public', write=False, role_src='extra'),
    # 2026-09-28（后台覆盖）：Odoo 19 后台 Web 客户端代表页 —— 同样**不在** custom_addons 的
    # @http.route 里（核心 web 模块渲染），但无障碍门禁**真的会探它们**
    # （scripts/check_accessibility.py 以 backoffice 会话扫描后台导航栏外壳），故必须登记。
    # 不登记的后果：下一次 --generate 会把它们当「消失的路由」移出表 —— 删除护栏会打印被删清单
    # （可见），但**覆盖已经丢了**；与其靠护栏提醒，不如在这里显式留下。
    # roles 取「谁能打开」：超管 + 教务处（内部用户）；scope 用闭集里的 other（覆盖率只量 portal，
    # 后台页不属于该统计口径，它的门禁归属写在 gates 里）。
    dict(path='/odoo/contacts', module='(odoo-webclient-core)', kind='page', scope='other',
         roles=['admin', 'backoffice'], gates=['accessibility'],
         pending_gate='', pending_parent=None, sample_note=None,
         auth='user', write=False, role_src='extra'),
    dict(path='/odoo/students', module='(odoo-webclient-core)', kind='page', scope='other',
         roles=['admin', 'backoffice'], gates=['accessibility'],
         pending_gate='', pending_parent=None, sample_note=None,
         auth='user', write=False, role_src='extra'),
    # 2026-09-29（后台扩覆盖 2 页 → 7 页）：同上一条，路径由 Odoo 19 **核心 web 客户端**解析
    # （/odoo/<action path>[/<record id>]），custom_addons 里没有 @http.route ⇒ 生成器的路由扫描
    # **结构上看不见它们**。不登记在这一段的话，下一次 --generate 会把它们当「消失的路由」降级成
    # ghost 行（gates 虽保留，status 会变成 gap）—— 那正是「覆盖悄悄丢掉」的形态，故在此显式留下。
    # roles 同前：超管 + 教务处（内部用户）；scope 用闭集里的 other。
    dict(path='/odoo/batches', module='(odoo-webclient-core)', kind='page', scope='other',
         roles=['admin', 'backoffice'], gates=['accessibility'],
         pending_gate='', pending_parent=None, sample_note=None,
         auth='user', write=False, role_src='extra'),
    dict(path='/odoo/apps', module='(odoo-webclient-core)', kind='page', scope='other',
         roles=['admin', 'backoffice'], gates=['accessibility'],
         pending_gate='', pending_parent=None, sample_note=None,
         auth='user', write=False, role_src='extra'),
    dict(path='/odoo/contacts/1', module='(odoo-webclient-core)', kind='page', scope='other',
         roles=['admin', 'backoffice'], gates=['accessibility'],
         pending_gate='', pending_parent=None, sample_note=None,
         auth='user', write=False, role_src='extra'),
    dict(path='/odoo/students/5', module='(odoo-webclient-core)', kind='page', scope='other',
         roles=['admin', 'backoffice'], gates=['accessibility'],
         pending_gate='', pending_parent=None, sample_note=None,
         auth='user', write=False, role_src='extra'),
    dict(path='/odoo/grade-configuration', module='(odoo-webclient-core)', kind='page', scope='other',
         roles=['admin', 'backoffice'], gates=['accessibility'],
         pending_gate='', pending_parent=None, sample_note=None,
         auth='user', write=False, role_src='extra'),
)


# ------------------------------------------------------------------ 行装配
def roles_for(decl, matrix_roles, repo=None):
    """允许身份 -> (roles, 来源)。来源 ∈ matrix / handler / default-public / default-logged。

    优先级：① 矩阵登记的角色集（人手判定，最可信）> ② handler 源码里的身份谓词
    （本仓既有 helper 名）> ③ 兜底。兜底条数会在 --coverage 里报出 ——
    兜底是「还没人判过」，不是「已判定为全身份」。
    """
    base = repo or REPO
    # ① 期望角色集回填（队长 2026-09-26 裁定）—— 旧矩阵写死的期望集，**最高优先级**：
    # 迁移时它没被搬过来，导致矩阵对 22 条路由**不再断言「必须 200」**（静默削弱）。
    if decl['path'] in ROLE_BACKFILL:
        return list(ROLE_BACKFILL[decl['path']]), 'backfill'
    if decl['path'] in matrix_roles:
        return sorted(matrix_roles[decl['path']]), 'matrix'
    src = ''
    if decl.get('node') is not None:
        try:
            with io.open(os.path.join(base, decl['file']), encoding='utf-8') as fh:
                src = ast.get_source_segment(fh.read(), decl['node']) or ''
        except (OSError, ValueError):
            src = ''
    got = set()
    for toks, rs in ROLE_TOKENS:
        for tok in toks:
            if tok in src:
                got |= set(rs)
                break
    if got:
        return sorted(got), 'handler'
    if (decl.get('auth') or 'user') == 'public':
        return ['anon'], 'default-public'
    return list(DEFAULT_LOGGED), 'default-logged'

# ------------------------------------------------------------------ 范围与继承
def row_scope(module, endpoint, path, auth):
    """行的范围（机器可读，2026-09-26 队长裁定新增）：
    portal / public / endpoint / retired / other。

    判据（与 docstring 的冻结表逐字一致，**顺序即优先级**）：
      retired  = module 在 RETIRED_MODULES 里（本仓有快照、生产上不存在 ⇒ 先排除，
                 否则退役模块的 /my/* 会被当成目标集里的活页面 —— 本项目已踩过两次的雷）
      endpoint = kind=endpoint（导出 / 文件 / 数据接口，含 methods 不含 GET 的写路由）
      portal   = 其余里命中**门户前缀谓词** is_portal() 的（= 本次 UI 优化的目标集）
      public   = 其余里 auth==public 的（匿名可访问的公开站 / 营销 / 帮助页）
      other    = 剩下那些（登录 / 注册 / 后台兼容路由等）
    **覆盖率只量 portal** —— 下一个人不必再靠前缀正则重新推导目标集。
    """
    if module in RETIRED_MODULES:
        return 'retired'
    if endpoint:
        return 'endpoint'
    if is_portal(path):
        return 'portal'
    if (auth or 'user') == 'public':
        return 'public'
    return 'other'



# 「**待补样本**」登记表（队长 2026-09-26 裁定，取代原先的「继承上级门禁」）：键=子页，值=上级列表页。
#
# 为什么不能记成 gates：门禁探的是**具体 URL**，这些子页**没有任何门禁真探过**（上级被探 != 本页被探）。
# 把「上级在名单里」算成覆盖，就是**用没被量过的数字冒充覆盖** —— 本次体检刚证明过这类假绿
# （/grading/entry 登记了矩阵、教务被 303 弹回、矩阵仍判 PASS）。所以：
#   · gates 保持**空数组**（语义收紧为「**实际探这条 URL 的门禁**」）；
#   · 该补进哪个门禁写进 pending_gate（**这是待办，不是覆盖**）；
#   · status 仍是 gap，reason 写明「上级已在 X 扫描集内、需补样本 id」。
#
# 判据：这一页是**从上级列表页点进去**的（可达性判断 = 人判；路径形状推不出来 —— 反例：
# /assess/fill/<int:task_id> 也挂在 /assess 下，但它是从 /assess/my 点进去的任务页，队长裁定不登记）。
# 表里没有的同形状页面**仍然是「无着落」** —— 新页面必须被人看一眼，这正是要的。
# apply_pending() 逐条校验（子页在册 / 上级在册 / 上级确有门禁），校验不过就丢弃并告警。
PENDING_PARENT = (
    ('/journals/review/<int:entry_id>', '/journals/review'),
    ('/leave/approvals/<int:leave_id>', '/leave/approvals'),
    ('/my/child/<int:child_id>', '/my/child'),
    ('/my/child/<int:child_id>/leave', '/my/child'),
    ('/my/child/<int:child_id>/leave/saved', '/my/child'),
    ('/my/courses/<int:subject_id>', '/my/courses'),
    ('/my/courses/<int:subject_id>/rep', '/my/courses'),
    ('/my/messages/<int:uid>', '/my/messages'),
    ('/my/study/<int:subject_id>', '/my/study'),
    ('/quiz/<int:qid>/result/<int:aid>', '/quiz'),
    ('/quiz/<int:qid>/take', '/quiz'),
    ('/registrar/subject/approvals/<int:rid>', '/registrar/subject/approvals'),
    ('/library/media/info/<int:mid>', '/library/media'),
    ('/my/courses/lesson/<int:lesson_id>', '/my/courses'),
    ('/my/evaluation/task/<int:task_id>', '/my/evaluation'),
)

# 样本 id 从哪来（队长 2026-09-26 要求落成数据：B 组补覆盖时不必回头问 A 组）。
# 键=路径；值=一句话来源（写进该行的 evidence）。含「需造样本」标记的 2 条真要造数据。
SAMPLE_ID = {
    '/my/child/<int:child_id>':
        '样本：op.student.id 且 ∈ parent.student_ids（roles.py: child_id in parent.student_ids.ids）',
    '/my/child/<int:child_id>/leave':
        '样本：同上（op.student.id，须为该家长名下的孩子）',
    '/my/child/<int:child_id>/leave/saved':
        '样本：同上（回执页；须先 POST /my/child/<id>/leave/save 才可达）',
    '/leave/approvals/<int:leave_id>':
        '样本：edu.leave 行（state 为待批，且当前账号过 leave_portal_approver()）',
    '/journals/review/<int:entry_id>':
        '样本：edu.journal.entry 行（且当前账号有教师档案：_require_teacher）',
    '/registrar/subject/approvals/<int:rid>':
        '样本：op.subject.registration 行（待审选课单）',
    '/my/courses/<int:subject_id>':
        '样本：op.subject.id 且须在 _subjects_for(...) 结果里（lms.py:114）',
    '/my/study/<int:subject_id>':
        '样本：op.subject.id 且须在 _subjects_for(...) 结果里（study.py）',
    '/my/messages/<int:uid>':
        '样本：熟人圈账号的 res.users id（messages.py _identity_user_ids：已挂身份档案的账号）',
    '/quiz/<int:qid>/take':
        '样本：edu.quiz.id 且 state=published',
    '/quiz/<int:qid>/result/<int:aid>':
        '样本：edu.quiz.attempt.id（须 student_id=本人 且 quiz_id=URL 的 qid，portal.py:160-168）；**需造样本**',
    '/my/courses/<int:subject_id>/rep':
        '样本：edu.course.rep 在任课代表绑定（lms.py active_rep_for(student, subject)）；**需造样本**',
    '/library/media/info/<int:mid>':
        '样本：op.media.id（batch2.py:1400 browse）',
    '/my/courses/lesson/<int:lesson_id>':
        '样本：edu.lesson.id，须 state=published 且 subject_id ∈ _subjects_for(...)（lms.py:164-175）',
    '/my/evaluation/task/<int:task_id>':
        '样本：edu.eval.task.id（evaluation.py:112 且当前账号过 _is_staff()）',
}


def pending_gate_of(parent_row):
    """上级行 -> 该给子页填的 pending_gate：门禁名里**排序最靠前**的那个。

    补覆盖只需补进**一个**门禁（多补无益、成本更高），所以取第一个；
    上级的完整门禁集仍留在上级行的 gates 里。
    """
    for g in COUNTED_GATES:
        if g in (parent_row.get('gates') or []):
            return g
    return ''


def apply_pending(rows):
    """把「待补样本」写进 rows 的 pending_gate -> (命中条数, 告警列表)。

    **绝不写 gates**：门禁没探过就是没探过。校验子页在册、上级在册且上级确有门禁；
    校验不过就丢弃并告警（不静默登记，否则这张表会变成新的假绿来源）。
    """
    by = {}
    for r in rows:
        by[r['path']] = r
    hit, warns = 0, []
    for child, parent in PENDING_PARENT:
        c, p = by.get(child), by.get(parent)
        if c is None:
            warns.append('待补样本登记的子页不在册：%s' % child)
            continue
        if p is None:
            warns.append('待补样本登记的上级不在册：%s' % parent)
            continue
        g = pending_gate_of(p)
        if not g:
            warns.append('待补样本登记的上级没有门禁覆盖：%s' % parent)
            continue
        if c.get('scope') == 'retired':
            continue
        c['pending_gate'] = g
        c['pending_parent'] = parent
        hit += 1
    return hit, warns


def apply_sample(rows):
    """把样本 id 来源写进 rows 的 sample_note（SAMPLE_ID 表）-> 命中条数。"""
    n = 0
    for r in rows:
        note = SAMPLE_ID.get(r['path'])
        if note:
            r['sample_note'] = note
            n += 1
    return n


def pending_reason(row):
    """待补样本行的 reason（队长给定格式；门禁名/上级名都来自机器登记）。"""
    txt = ('上级 %s 已在 %s 扫描集内；本页需补样本 id 才能被真探'
           '（见 --coverage 的样本清单）'
           % (row.get('pending_parent'), row.get('pending_gate')))
    if row['path'] == '/my/evaluation/task/<int:task_id>':
        txt += '；另见 ui-gap-ledger 的 P1：同路径被 shim 遮蔽'
    return txt


def build_pages(gates, matrix_roles, repo=None, modules_dir=None):
    """源码 -> (登记行, decls, uniq, nonliteral, notes)。

    **登记集合 = 全部去重后的路由（不只门户页）**：E 组的消费门禁
    (scripts/check_ui_surface.py) 的不变式 1 是「仓内每条 @http.route 都要在表里」，
    不变式 2 是「kind=page 的行 gates 或 reason 必有一个非空」。于是：
      kind = 'page'     <=> 可读（methods 含 GET）且不命中端点判据
      kind = 'endpoint' <=> 其余（30 条导出/数据端点 + 88 条写路由）
    **覆盖率只量门户页**（in_portal，本次范围 120 条）；非门户行必须写 reason
    说明「为什么不需门禁覆盖」，否则 E 组门禁报红。
    """
    decls, nonliteral, notes = extract_routes(modules_dir=modules_dir, repo=repo)
    uniq = dedupe_by_path(decls)
    rows = []
    for path, decl in sorted(uniq.items()):
        write = is_write(decl)
        endpoint = write or is_endpoint(path)
        auth = decl.get('auth') or 'user'
        roles, role_src = roles_for(decl, matrix_roles, repo=repo)
        covered = [g for g in COUNTED_GATES if path in gates.get(g, ())]
        if decl['module'] in RETIRED_MODULES:
            covered = []          # 退役模块不走门禁（队长裁定）：这些路由生产上不存在
        rows.append(dict(path=path, module=decl['module'],
                         kind=('endpoint' if endpoint else 'page'),
                         scope=row_scope(decl['module'], endpoint, path, auth),
                         roles=roles, gates=covered, role_src=role_src,
                         auth=auth, write=write,
                         pending_gate='', pending_parent=None, sample_note=None))
    for extra in EXTRA_ROUTES:
        if extra['path'] not in uniq:
            rows.append(dict(extra))       # 表内非仓内路由（'/' 由 website 核心渲染）
    rows.sort(key=lambda r: r['path'])
    _hit, _warns = apply_pending(rows)
    apply_sample(rows)
    for w in _warns:
        notes.append('待补样本核对：%s' % w)   # 校验不过的登记**不静默丢弃**，报到 --coverage
    return rows, decls, uniq, nonliteral, notes


def nonportal_reason(row):
    """非门户行 gates 为空时的 reason：说明**为什么不需门禁覆盖**（E 组门禁要求必填）。"""
    if row.get('write'):
        return '写路由（methods 不含 GET）：不是可渲染页面，渲染 / 文案 / 无障碍门禁不适用'
    if row.get('kind') == 'endpoint':
        return '数据 / 导出端点（不是页面）：渲染 / 文案 / 无障碍门禁不适用'
    return ('不在本次门户范围（公开站 / 登录注册 / 后台等）：三张 UI 门禁按设计不含它，'
            '如需纳入请单独立项')


# 死角分型的判据（**用实际数据分，不照抄初判**）：
#   1 详情 / 子页（点进去之后）= 存在一个**已登记**的上级前缀路径 —— 症状是
#     「列表页有人看着、点进去就没人看」，这是初判里对的那一半；
#   2 写操作入口页 = 尾段是动作词（表单 / 提交 / 动作面）；
#   3 参数页 / 令牌页 = 尾段是参数且**没有**已登记的上级（token 直入、子资源）；
#   4 数据 / 轮询面 = 尾段是数据动词（这类其实是接口，被端点判据漏掉了，点名备用）；
#   5 其余 = 自助服务页 / 其它内容页。
ACTION_TAIL = ('new', 'import', 'apply', 'transfer', 'enroll', 'create', 'edit',
               'publish', 'submit', 'save', 'saved', 'upload', 'join', 'deactivate',
               'withdraw', 'delete', 'remove')
DATA_TAIL = ('poll', 'refresh', 'status', 'check')


def _covered_parent(path, covered_paths):
    """去掉尾部连续参数段后的上级是否**已登记**（且不是 1 段顶层头）。

    '/leave/approvals/<int:leave_id>' -> 上级 /leave/approvals（2 段、已登记）-> 命中
    '/assess/fill/<int:task_id>'      -> 上级 /assess（1 段，太宽）-> 不命中
    为什么排除 1 段：'/my' 这种顶层头本身已登记，若算命中则每个 /my/xxx 都成"详情页"，
    分型会退化成一句废话。
    """
    base = re.sub('(/<[^>]+>)+$', '', path)
    cands = [base]
    segs = [s for s in base.split('/') if s]
    if len(segs) >= 3 and not segs[-1].startswith('<'):
        # 再上溯一级：'/library/media/info/<int:mid>' 的上级其实是 /library/media
        cands.append('/' + '/'.join(segs[:-1]))
    for c in cands:
        cs = [s for s in c.split('/') if s]
        if len(cs) >= 2 and c in covered_paths:
            return True
    return False


def gap_type(row, covered_paths):
    """死角分型（判据见代码上方注释；covered_paths = 已被门禁登记的路径集）。"""
    p = row['path']
    tail = p.rsplit('/', 1)[-1]
    if tail in ACTION_TAIL:
        return '写操作面（表单 / 提交 / 回执 / 动作）'
    if tail in DATA_TAIL:
        return '数据 / 轮询面（接口被算成页面）'
    if re.search('/<[^>]+>', p):
        if _covered_parent(p, covered_paths):
            return '详情 / 子页（点进去之后：上级已登记，本级没有）'
        return '参数页 / 令牌页（有参数段，上级未登记）'
    return '自助服务页 / 其它内容页'


def gap_reason(row, covered_paths):
    """gates 为空时的 reason：说明**为什么它是缺口**（gap 行必填）。"""
    return '三个门禁均未登记该路由（口径：路径精确匹配）：%s' % gap_type(row, covered_paths)


# ------------------------------------------------------------------ surface.json
def load_surface(path=None):
    path = path or os.path.join(REPO, SURFACE)
    if not os.path.exists(path):
        return None
    try:
        with io.open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return None


def merge_rows(new_rows, old_doc):
    """保留已填的 gates/status/evidence/roles/key；补新路由；标出消失的路由。

    返回 (rows, added_paths, ghost_paths)。
    """
    old = {}
    for r in (old_doc or {}).get('pages', []) or []:
        if isinstance(r, dict) and r.get('path'):
            old.setdefault(r['path'], r)
    paths_now = set(r['path'] for r in new_rows)
    covered_now = set(r['path'] for r in new_rows if r.get('gates'))
    taken, rows, added, ghost = set(), [], [], []
    for r in new_rows:
        prev = old.get(r['path']) or {}
        row = dict(path=r['path'], module=r['module'], kind=r['kind'],
                   scope=r['scope'], roles=list(r['roles']),
                   role_src=r.get('role_src', '?'))
        if prev.get('roles'):
            row['roles'] = list(prev['roles'])
        row['key'] = prev.get('key') or make_key(r['path'], taken)
        taken.add(row['key'])
        if r.get('scope') == 'retired':
            # 退役模块（本仓有快照、生产上不存在）：不走门禁、不进覆盖率分母、
            # status=n/a。**不保留 prev 的 gates/status** —— 它们曾经被算成覆盖，
            # 那是快照路由，留着就是假绿。
            row['gates'] = []
            row['status'] = 'n/a'
            row['reason'] = prev.get('reason') if (prev.get('reason') or '').startswith('本仓 ') \
                else RETIRED_MODULES.get(r['module'], '退役模块，不纳入')
            row['evidence'] = prev.get('evidence') or ''
            row['pending_gate'] = ''
            row['pending_parent'] = None
            row['write'] = bool(r.get('write'))
            if r['path'] not in old:
                added.append(r['path'])
            rows.append(row)
            continue
        pg = prev.get('gates')
        row['gates'] = list(pg) if isinstance(pg, list) and pg else list(r['gates'])
        row['pending_gate'] = r.get('pending_gate') or ''
        if row['pending_gate']:
            # 队长 2026-09-26 二次裁定：待补样本行**没有任何门禁真探过** ⇒ gates 必须为空。
            # 这条要**压过「保留表里已填 gates」**的惯例：上一版把「继承」写进过 gates，
            # 那些值是没被量过的数字，留着就是假绿。
            row['gates'] = []
        row['pending_parent'] = r.get('pending_parent')
        # status 由 gates 派生（gap = 门户范围内没被真探；unverified = 被真探）；
        # 只有 verified 是**人的结论**，一律保留（被门禁登记 != 已验证）。
        if prev.get('status') == 'verified':
            row['status'] = 'verified'
        elif row['gates']:
            row['status'] = 'unverified'
        elif r.get('scope') == 'portal':
            row['status'] = 'gap'          # 本次范围内的缺口（待补样本 / 无着落都算）
        else:
            row['status'] = 'unverified'   # 范围外、按设计不进门禁
        # 冻结契约：reason **只在 gates 为空时**非空（有登记就必须留空字符串）
        if row['gates']:
            row['reason'] = ''
        elif r.get('scope') == 'portal':
            if row['pending_gate']:
                # 待补样本行的 reason 由机器给定（队长格式），**不保留上版可能残留的通用文案**
                row['reason'] = pending_reason(r)
            else:
                row['reason'] = prev.get('reason') or gap_reason(r, covered_now)
        else:
            row['reason'] = prev.get('reason') or nonportal_reason(r)
        row['write'] = bool(r.get('write'))
        # evidence：人工写过的优先；没写过的填 SAMPLE_ID 的样本来源（队长要求落成数据，
        # 让 B 组补覆盖时不必回头问）。样本来源 != 验证证据，措辞上已写明「样本：」。
        ev_prev = prev.get('evidence') or ''
        note = r.get('sample_note') or ''
        if note and note not in ev_prev:
            row['evidence'] = (note + ('；' + ev_prev if ev_prev else ''))
        else:
            row['evidence'] = ev_prev
        if r['path'] not in old:
            added.append(r['path'])
        rows.append(row)
    for path, prev in sorted(old.items()):
        if path in paths_now:
            continue
        row = dict(path=path, module=prev.get('module', ''),
                   kind=prev.get('kind', 'page'),
                   scope=prev.get('scope') or 'other',
                   roles=list(prev.get('roles') or []))
        row['key'] = prev.get('key') or make_key(path, taken)
        taken.add(row['key'])
        row['gates'] = list(prev.get('gates') or [])
        row['status'] = 'gap'
        note = '源码已无此声明（复算未见）：路由已消失或已改名'
        row['reason'] = prev.get('reason') or note
        ev = prev.get('evidence') or ''
        row['evidence'] = (note + '；' + ev).strip('；') if note not in ev else ev
        ghost.append(path)
        rows.append(row)
    rows.sort(key=lambda x: x['path'])
    return rows, added, ghost


# surface.json 的字段表（与 E 组冻结的形状逐字一致）。内部辅助字段（role_src/auth）
# 在落盘时**必须**被剥掉，否则形状漂移。
# scope 是 2026-09-26 队长裁定新增的 additive 字段（E 组门禁只校验 kind/gates/reason）。
# pending_gate（2026-09-26 队长裁定）：**待办不是覆盖** —— 该由哪个门禁来探它（无则空串）。
# gates 的语义因此收紧为「**实际探这条 URL 的门禁**」：上级被探 != 本页被探。
SURFACE_FIELDS = ('key', 'path', 'module', 'kind', 'scope', 'roles', 'gates',
                  'pending_gate', 'reason', 'status', 'evidence')


def surface_doc(rows, stamp=None):
    pages = []
    for r in rows:
        row = dict((k, r.get(k, '')) for k in SURFACE_FIELDS)
        for k in ('roles', 'gates'):
            row[k] = list(r.get(k) or [])
        pages.append(row)
    return {'surface-version': SURFACE_VERSION,
            'generated': stamp or datetime.now().strftime('%Y-%m-%d'),
            'source': SOURCE_DESC,
            'pages': pages}


def write_surface(rows, path=None):
    path = path or os.path.join(REPO, SURFACE)
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(path, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(surface_doc(rows), ensure_ascii=False, indent=2))
        fh.write(NEWLINE)
    return path


# ------------------------------------------------------------------ 读数
def self_attest_line():
    return 'REVISION=%s · 指纹 %s · 断言 %d 条 · 时刻 %s' % (
        REVISION, self_fingerprint(), SELFTEST_CASES,
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


def stats(decls, uniq):
    """口径六数：声明 / 去重 / 写 / 可读 / 页面 / 端点。"""
    write = [p for p, d in uniq.items() if is_write(d)]
    readable = [p for p, d in uniq.items() if not is_write(d)]
    endpoints = [p for p in readable if is_endpoint(p)]
    pages = [p for p in readable if not is_endpoint(p)]
    return dict(decl=len(decls), uniq=len(uniq), write=len(write),
                readable=len(readable), pages=len(pages), endpoints=len(endpoints))


def coverage_report(rows, decls, uniq, nonliteral, gates, notes=None, quiet=False,
                    modes=None):
    """打印覆盖率读数（口径六数 + 门户覆盖率 + 死角逐条 + 口径边界）。"""
    st = stats(decls, uniq)
    reg = [r for r in rows if r.get('kind') in KINDS]
    pages_all = [r for r in reg if r.get('kind') == 'page']
    # 覆盖率**只量 scope=='portal'**（队长 2026-09-26 裁定）：公开站 / 端点 / 其余
    # 照样登记（E 组门禁不变式 1），但不进这个分母。
    pages = [r for r in pages_all if r.get('scope') == 'portal']
    # 三数并列（队长 2026-09-26 裁定，**不许合并成一个「已覆盖」**）：
    #   门禁真探 M = 真的有条门禁去探这条 URL（gates 非空）
    #   待补样本 P = pending_gate 已定（上级已在某门禁名单里）但本页没被探过
    #   无着落   K = 连上级门禁都没有，得人判
    probed = [r for r in pages if r.get('gates')]
    pending = [r for r in pages if not r.get('gates') and r.get('pending_gate')]
    orphan = [r for r in pages if not r.get('gates') and not r.get('pending_gate')]
    gaps = pending + orphan
    per = dict((g, sum(1 for r in probed if g in r.get('gates', [])))
               for g in COUNTED_GATES)

    print('== 门户 UI 表面覆盖率 ==')
    print('抽样口径：custom_addons/**/*.py 的 @http.route（**装饰器括号配对**取全部 / 开头'
          '字面量）· 门户前缀页面 · 与门禁登记集**精确匹配**')
    print('路由声明 %d 条 ｜ 去重 %d 条 ｜ 写路由（methods 不含 GET）%d 条 ｜ '
          '可读路由 %d 条 = 页面 %d + 端点 %d'
          % (st['decl'], st['uniq'], st['write'], st['readable'], st['pages'],
             st['endpoints']))
    print('surface.json 登记 %d 条 = 页面 %d + 端点 %d（含写路由）；'
          '本次覆盖率只量 **scope=portal 的 %d 条**'
          % (len(reg), len(pages_all), len(reg) - len(pages_all), len(pages)))
    scope_cnt = dict((s, 0) for s in SCOPES)
    for r in reg:
        scope_cnt[r.get('scope', 'other')] = scope_cnt.get(r.get('scope', 'other'), 0) + 1
    print('scope 分布：' + ' ｜ '.join('%s %d' % (s, scope_cnt.get(s, 0)) for s in SCOPES))
    if modes:
        print('门禁形态：' + ' ｜ '.join(
            '%s=%s' % (g, {'hardcoded': '形态A（自带名单）', 'surface': '形态B（读表）',
                           'missing': '读不到', 'broken': '解析失败'}.get(m, m))
            for g, m in sorted(modes.items())))
    ret = [r for r in reg if r.get('scope') == 'retired']
    if ret:
        print('退役排除：%d 条（%s）—— 本仓有代码快照、生产上不存在，不纳入门禁与覆盖率分母'
              % (len(ret), '、'.join(sorted(set(r['module'] for r in ret)))))
        for r in sorted(ret, key=lambda x: x['path']):
            print('    retired  %s' % r['path'])
    print()
    print('门户 %d ｜ **门禁真探 %d** ｜ **待补样本（pending_gate 已定）%d** ｜ **无着落 %d**'
          % (len(pages), len(probed), len(pending), len(orphan)))
    print('  route_matrix  真探 %d' % per['route_matrix'])
    print('  accessibility 真探 %d' % per['accessibility'])
    print('  english       真探 %d' % per['english'])
    print('  （三条门禁计数有重叠；真探 = gates 非空 = 真的有条门禁去探这条 URL。'
          '待补样本 + 无着落 = 死角 %d）' % len(gaps))
    src_kind = {}
    for r in pages:
        src_kind[r.get('role_src', '?')] = src_kind.get(r.get('role_src', '?'), 0) + 1
    print('  角色来源：' + ' ｜ '.join('%s %d' % (k, v)
                                      for k, v in sorted(src_kind.items())))
    for n in (notes or []):
        print('  [抽取核对] %s' % n)
    probed_paths = set(r['path'] for r in probed)
    mods = {}
    for r in pages:
        m = mods.setdefault(r['module'], [0, 0])
        m[0] += 1
        if r.get('gates'):
            m[1] += 1
    print('  模块分布（门户页 / 真探）：' + ' ｜ '.join(
        '%s %d/%d' % (m, v[1], v[0]) for m, v in sorted(mods.items(),
                                                        key=lambda kv: -kv[1][0])))
    if not quiet:
        print()
        print('-- 待补样本 P（%d 条：pending_gate 已定，补齐样本 id 即可被真探）--' % len(pending))
        for i, r in enumerate(sorted(pending, key=lambda x: x['path']), 1):
            print('  %2d. %-50s → 补进 %-13s（上级 %s）'
                  % (i, r['path'], r.get('pending_gate') or '-',
                     r.get('pending_parent') or '-'))
            if r.get('evidence'):
                print('      %s' % r['evidence'])
        print()
        print('-- 无着落 K（%d 条：连上级门禁都没有，要人判）--' % len(orphan))
        for i, r in enumerate(sorted(orphan, key=lambda x: x['path']), 1):
            print('  %2d. %-50s [%-14s] %s'
                  % (i, r['path'], r['module'], gap_type(r, probed_paths)))
        by_type = {}
        for r in gaps:
            t = gap_type(r, probed_paths)
            slot = by_type.setdefault(t, [0, []])
            slot[0] += 1
            slot[1].append(r['path'])
        print()
        print('-- 死角分型（%d 条 = 待补样本 %d + 无着落 %d；代表路由 = 该型第一条）--'
              % (len(gaps), len(pending), len(orphan)))
        for k, v in sorted(by_type.items(), key=lambda kv: -kv[1][0]):
            print('  %-46s %2d   代表：%s' % (k, v[0], v[1][0]))
        print()
        print('-- 口径边界：路径为变量、静态抽不到的声明（不静默吞）--')
        if nonliteral:
            for r in nonliteral:
                print('  %s:%s %s(...) —— 路径是变量，无法静态解析'
                      % (r.get('file'), r.get('line'), r.get('func')))
        else:
            print('  （无）')
    print()
    print('自证：%s' % self_attest_line())
    return len(pages), len(probed), len(gaps), per


# ------------------------------------------------------------------ 动作
def _doc_fp(doc):
    """表指纹（md5 前 8 位）—— 改动摘要里要能对上「哪一版表」。"""
    try:
        blob = json.dumps(doc or {}, ensure_ascii=False, sort_keys=True).encode('utf-8')
        return hashlib.md5(blob).hexdigest()[:8]
    except (TypeError, ValueError):
        return '????????'


def _gates_diff(new_rows, old_doc):
    """-> (改动条数, 新增 gates 的路径, **疑似静默移除**的路径)。

    防静默丢失的核心判据（队长 2026-09-26 事故后加的护栏）：
      · 「疑似移除」= 表里原本有 gates，本次算出来是空，**且不是**规则驱动的清空
        （pending_gate 行按裁定必须为空、retired 行按裁定必须为空 —— 这两种不算）。
      · 只有「疑似移除」才会拦人：它意味着某个门禁的登记集塌了（典型成因：门禁切成
        形态 B 后脚本里没有字面量了，或表被删/被截断）。
    理由：surface.json 是单一来源，一次 --generate 就能静默清空覆盖 —— 那比门禁失效更危险。
    """
    old = {}
    for r in (old_doc or {}).get('pages', []) or []:
        if isinstance(r, dict) and r.get('path'):
            old[r['path']] = r
    added, removed, changed = [], [], 0
    for r in new_rows:
        prev = old.get(r['path'])
        cur = sorted(r.get('gates') or [])
        if prev is None:
            if cur:
                added.append(r['path'])
            continue
        pg = sorted(prev.get('gates') or [])
        if pg == cur:
            continue
        changed += 1
        rule_cleared = bool(r.get('pending_gate')) or r.get('scope') == 'retired'
        if pg and not cur and not rule_cleared:
            removed.append(r['path'])
    return changed, added, removed


def do_generate(path=None, quiet=False, repo=None, modules_dir=None, force=False):
    """从源码重生成 tests/ui/surface.json。

    **三条防静默丢失护栏**（队长 2026-09-26 事故后加，本仓先例：check_manifest_tracking
    的「例外必须显式且带理由」、deploy_myedu.sh 的「失败特征硬失败」）：
      A 门禁已是形态 B（名单只在表里）而表读不到 ⇒ 拒绝（否则覆盖整批清零）；
      B 形态 B 的门禁从表里读不到任何行、而磁盘上原本有 ⇒ 拒绝；
      C 本次会**移除**已有的 gates ⇒ 拒绝并打印清单，要 --force 才放行；
    无论是否 --force，都打印改动摘要（改动 N / 新增 X / 移除 Y / 表指纹）。
    """
    # 顺序很重要：**先读表再读门禁** —— 形态 B 的门禁（改成从表读名单）登记集就在表里。
    old = load_surface(path)
    gates, matrix_roles, missing, modes = load_gates(repo=repo, surface_doc=old)
    if missing:
        print('ENV：门禁脚本读不到 %s —— 无法判定覆盖（这不是通过）'
              % '、'.join(missing))
        return 2
    # 护栏 A
    if not (old or {}).get('pages') and any(m == 'surface' for m in modes.values()) \
            and not force:
        print('拒绝执行：至少一个门禁已是**形态 B（从表读名单）**，而 tests/ui/surface.json '
              '读不到/为空 —— 此时生成会把覆盖整批清零（本仓 2026-09-26 已发生过一次）。'
              '请先恢复表，或显式 --force。')
        return 2
    # 护栏 B
    for g, mode in sorted(modes.items()):
        if mode != 'surface' or gates.get(g):
            continue
        had = sum(1 for r in (old or {}).get('pages', [])
                  if isinstance(r, dict) and g in (r.get('gates') or []))
        if had and not force:
            print('拒绝执行：%s 是形态 B（从表读名单），但表里读不到任何 gates 含它的行'
                  '（磁盘上的表原本有 %d 条）—— 生成会把它们整批抹掉。'
                  '确认无误请加 --force。' % (g, had))
            return 2
    rows, decls, uniq, nonliteral, notes = build_pages(
        gates, matrix_roles, repo=repo, modules_dir=modules_dir)
    # 护栏 C
    changed, g_added, g_removed = _gates_diff(rows, old)
    print('gates 改动摘要：改动 %d 条 ｜ 新增 %d 条 ｜ 移除 %d 条 ｜ 表指纹 %s%s'
          % (changed, len(g_added), len(g_removed), _doc_fp(old),
             '（--force）' if force else ''))
    if g_removed and not force:
        print('拒绝执行：本次会**移除** %d 条已有的 gates —— surface.json 是单一来源，'
              '一次 --generate 不该静默清空覆盖。被移除的清单：' % len(g_removed))
        for p in g_removed[:20]:
            print('  - %s' % p)
        if len(g_removed) > 20:
            print('  …（共 %d 条）' % len(g_removed))
        print('确认无误请加 --force 重跑（改动摘要照常打印）。')
        return 2
    merged, added, ghost = merge_rows(rows, old)
    out = write_surface(merged, path)
    print('== 生成 %s ==' % os.path.relpath(out, repo or REPO))
    _reg = [r for r in merged if r.get('kind') in KINDS]
    print('登记 %d 条（页面 %d / 端点 %d；其中门户页 %d 条为本轮范围）；新登记 %d 条，消失 %d 条'
          % (len(_reg), len([r for r in _reg if r['kind'] == 'page']),
             len([r for r in _reg if r['kind'] == 'endpoint']),
             len([r for r in _reg if r.get('scope') == 'portal']), len(added), len(ghost)))
    print('写盘后表指纹：%s → %s' % (_doc_fp(old), _doc_fp(load_surface(path))))
    for p in added:
        print('  + 新页面：%s' % p)
    for p in ghost:
        print('  ! 源码已无此声明（保留在册并标 gap）：%s' % p)
    if not quiet:
        coverage_report(merged, decls, uniq, nonliteral, gates, notes=notes, modes=modes)
    return 0

def do_check(path=None, repo=None, modules_dir=None):
    """核对模式：surface.json 与源码是否同步（0=一致 / 1=幽灵 / 3=漏登记）。"""
    old = load_surface(path)
    gates, matrix_roles, missing, modes = load_gates(repo=repo, surface_doc=old)
    if missing:
        print('ENV：门禁脚本读不到 %s' % '、'.join(missing))
        return 2
    if old is None:
        print('ENV：%s 不存在或不是合法 JSON —— 先跑 --generate' % SURFACE)
        return 2
    rows, _decls, _uniq, _nl, notes = build_pages(
        gates, matrix_roles, repo=repo, modules_dir=modules_dir)
    declared = set(r['path'] for r in rows)
    on_disk = set(r.get('path') for r in (old.get('pages') or []) if r.get('path'))
    ghost = sorted(on_disk - declared)
    fresh = sorted(declared - on_disk)
    print('== 核对 %s vs 源码 ==' % SURFACE)
    print('在册 %d 条 ｜ 源码路由 %d 条（其中门户页 %d 条）'
          % (len(on_disk), len(declared),
             len([r for r in rows if r.get('scope') == 'portal'])))
    for p in ghost:
        print('  FAIL 幽灵路由（在册但源码已无声明）：%s' % p)
    for p in fresh:
        print('  INCOMPLETE 未登记的新页面（跑 --generate）：%s' % p)
    for n in (notes or []):
        print('  [抽取核对] %s' % n)
    rc = 1 if ghost else (3 if fresh else 0)
    print('结论：%s' % {0: 'OK（表与源码一致）', 1: 'FAIL（有幽灵路由）',
                     3: 'INCOMPLETE（有未登记页面）'}[rc])
    print('自证：%s' % self_attest_line())
    return rc


def do_coverage(surface_path=None, repo=None, modules_dir=None, quiet=False):
    old = load_surface(surface_path)
    if old is None:
        print('ENV：%s 不存在或不是合法 JSON —— 先跑 --generate' % SURFACE)
        return 2
    gates, matrix_roles, missing, modes = load_gates(repo=repo, surface_doc=old)
    if missing:
        print('ENV：门禁脚本读不到 %s —— 无法判定覆盖（这不是通过）'
              % '、'.join(missing))
        return 2
    rows, decls, uniq, nonliteral, notes = build_pages(
        gates, matrix_roles, repo=repo, modules_dir=modules_dir)
    merged, added, ghost = merge_rows(rows, old)
    coverage_report(merged, decls, uniq, nonliteral, gates, notes=notes,
                    quiet=quiet, modes=modes)
    on_disk = set(r.get('path') for r in (old.get('pages') or []))
    fresh = sorted(set(r['path'] for r in rows) - on_disk)
    if fresh:
        print('注意：surface.json 尚未登记 %d 条新页面（跑 --generate）：%s'
              % (len(fresh), '、'.join(fresh[:6])))
    if ghost:
        print('FAIL：surface.json 有 %d 条幽灵路由（源码已无声明）：%s'
              % (len(ghost), '、'.join(ghost)))
        return 1
    return 0


# ------------------------------------------------------------------ 反例自检
FIXTURE_CTRL = '''from odoo import http


class A(http.Controller):
    # 括号陷阱：下一行注释里带括号，配对不许被带偏
    @http.route('/my/thing', auth='user', website=True)  # 说明（含括号）
    def thing(self):
        return None

    @http.route(['/my/thing/<int:tid>'], auth='user')
    def thing_detail(self, tid):
        return None

    @http.route('/my/thing/save', methods=['POST'], auth='user')
    def thing_save(self):
        return None

    @http.route('/my/thing/export', auth='user')
    def thing_export(self):
        return None

    @http.route(PATH_CONST, auth='user')
    def thing_weird(self):
        return None

    @http.route('/public/page', auth='public')
    def public_page(self):
        return None
'''

FIXTURE_MATRIX = '''ALL5 = {'stu', 'fac', 'par', 'bo', 'admin'}

ROUTES = [
    ('/my/thing', ALL5, '夹具'),
]

REDIRECT_STRICT = []

REDIRECT_STRICT_BY_ROLE = []
'''

FIXTURE_A11Y = '''AUDIT_ROUTES = [
    ('student', '/my/thing'),
]
'''

FIXTURE_ENG = '''PUBLIC_ROUTES = ['/public/page']

PORTAL_ROUTES = ['/my/thing']

TEACHER_ROUTES = []
'''


def selftest():
    """反例自检（/tmp 造夹具，不碰真仓库）。

    要证三件事：
      1) 抽取不静默吞声明：列表形式 @http.route([...]) 必须被计入，路径为变量的
         那条必须被**点名**（单字符串正则会漏前者、静默跳过后者）；
      2) 分流判据的边界值（门户前缀 / 端点）都对 —— 抽错面比不抽更坏；
      3) --generate 的合并语义：人工填过的字段不被覆盖、消失的路由被标出。
    """
    ok = True
    emitted = 0

    def chk(name, cond, extra=''):
        nonlocal ok, emitted
        emitted += 1
        print('  %-4s %-40s %s' % ('PASS' if cond else 'FAIL', name, extra))
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix='ui_surface_selftest_')
    try:
        ctrl = os.path.join(tmp, 'custom_addons', 'modA', 'controllers')
        os.makedirs(ctrl)
        io.open(os.path.join(ctrl, 'a.py'), 'w', encoding='utf-8').write(FIXTURE_CTRL)
        os.makedirs(os.path.join(tmp, 'tests', 'smoke'))
        io.open(os.path.join(tmp, 'tests', 'smoke', 'ux_v3_route_matrix.py'),
                'w', encoding='utf-8').write(FIXTURE_MATRIX)
        os.makedirs(os.path.join(tmp, 'scripts'))
        io.open(os.path.join(tmp, 'scripts', 'check_accessibility.py'),
                'w', encoding='utf-8').write(FIXTURE_A11Y)
        io.open(os.path.join(tmp, 'scripts', 'check_english.py'),
                'w', encoding='utf-8').write(FIXTURE_ENG)

        gates, mroles, missing, _modes = load_gates(repo=tmp)
        rows, decls, uniq, nonliteral, notes = build_pages(gates, mroles, repo=tmp)
        tp = set(d['path'] for d in decls)
        chk('括号配对：注释里的括号不带偏配对', '/my/thing' in tp, '实际 %s' % sorted(tp))
        chk('夹具：路径声明 5 条（4 条字面量 + 1 条列表形参）',
            len(decls) == 5, '实际 %d' % len(decls))
        chk('夹具：列表形参 @http.route([...]) 被计入',
            '/my/thing/<int:tid>' in tp, '实际 %s' % sorted(tp))
        chk('夹具：变量形参被点名为非字面量（不静默吞）',
            len(nonliteral) == 1 and nonliteral[0].get('kind') == 'variable',
            '实际 %s' % [r.get('kind') for r in nonliteral])
        # ⚠ 期望值**由 EXTRA_ROUTES 现算**（2026-09-28 修）：原先写死 (6, 4, 2)，
        #   往 EXTRA_ROUTES 里加一条后台页就假红一次 —— 那条断言的本意是「EXTRA_ROUTES 行
        #   会被并入、且写路由/导出端点归 endpoint」，不是「EXTRA_ROUTES 只有 1 条」。
        _extra_page = len([e for e in EXTRA_ROUTES if e.get('kind') == 'page'])
        _extra_ep = len([e for e in EXTRA_ROUTES if e.get('kind') == 'endpoint'])
        chk('夹具：登记 = 夹具 5 条 + EXTRA_ROUTES %d 条（写路由与导出端点归 endpoint）'
            % len(EXTRA_ROUTES),
            (len(rows), len([r for r in rows if r['kind'] == 'page']),
             len([r for r in rows if r['kind'] == 'endpoint']))
            == (5 + len(EXTRA_ROUTES), 3 + _extra_page, 2 + _extra_ep),
            '实际 %s' % dict((r['path'], r['kind']) for r in rows))
        chk('夹具：scope=portal 的是 /my/thing + /my/thing/<int:tid>',
            [r['path'] for r in rows if r.get('scope') == 'portal']
            == ['/my/thing', '/my/thing/<int:tid>'],
            '实际 %s' % [r['path'] for r in rows if r.get('scope') == 'portal'])
        _sc = {}
        for r in rows:
            _sc[r['scope']] = _sc.get(r['scope'], 0) + 1
        # 同上：public/other 两档也按 EXTRA_ROUTES 现算（/ = public；后台页 = other）。
        _extra_pub = len([e for e in EXTRA_ROUTES if e.get('scope') == 'public'])
        _extra_other = len([e for e in EXTRA_ROUTES if e.get('scope') == 'other'])
        chk('夹具：scope 分布 = portal 2 ｜ public %d（夹具 1 + EXTRA %d）｜ endpoint 2 ｜ other %d'
            % (1 + _extra_pub, _extra_pub, _extra_other),
            (_sc.get('portal'), _sc.get('public'), _sc.get('endpoint'),
             _sc.get('other', 0)) == (2, 1 + _extra_pub, 2, _extra_other),
            '实际 %s' % _sc)
        _fake = [
            dict(path='/quiz', module='x', kind='page', scope='portal',
                 roles=['student'], gates=['route_matrix'], pending_gate='',
                 pending_parent=None),
            dict(path='/quiz/<int:qid>/take', module='x', kind='page', scope='portal',
                 roles=['student'], gates=[], pending_gate='', pending_parent=None),
            dict(path='/not-in-table/<int:x>', module='x', kind='page', scope='portal',
                 roles=['student'], gates=[], pending_gate='', pending_parent=None),
        ]
        for _r in _fake:
            _r['pending_gate'] = ''
            _r['pending_parent'] = None
        _hit, _warns = apply_pending(_fake)
        chk('待补样本：只对登记表内的「子页 <- 上级」生效，且**不写 gates**',
            _hit == 1 and _fake[1]['pending_gate'] == 'route_matrix'
            and _fake[1]['gates'] == [] and _fake[2]['pending_gate'] == '',
            '命中 %s ｜ 子页 gates=%s ｜ 表外 pending=%s'
            % (_hit, _fake[1]['gates'], _fake[2]['pending_gate']))
        _hit2, _warns2 = apply_pending([
            dict(path='/my/child', module='x', kind='page', scope='portal',
                 roles=['parent'], gates=[], pending_gate='', pending_parent=None),
            dict(path='/my/child/<int:child_id>', module='x', kind='page',
                 scope='portal', roles=['parent'], gates=[], pending_gate='',
                 pending_parent=None)])
        chk('待补样本：上级没有门禁覆盖时告警且不登记', _hit2 == 0 and bool(_warns2),
            '实际命中 %s ｜ 告警 %d 条' % (_hit2, len(_warns2)))
        _f3, _a3, _g3 = merge_rows([dict(path='/my/child/<int:child_id>', module='edu_portal',
                              kind='page', scope='portal', roles=['parent'],
                              gates=[], pending_gate='route_matrix',
                              pending_parent='/my/child', role_src='handler',
                              sample_note=SAMPLE_ID['/my/child/<int:child_id>'])], None)
        chk('待补样本行：status=gap、reason 含「需补样本 id」、evidence 有样本来源',
            _f3[0]['status'] == 'gap' and '需补样本 id' in _f3[0]['reason']
            and _f3[0]['evidence'].startswith('样本：'),
            '实际 %s ｜ %s' % (_f3[0]['status'], _f3[0]['reason'][:30]))
        chk('样本表：需造样本的恰好 2 条（/quiz/<qid>/result/<aid>、/my/courses/<id>/rep）',
            len([1 for v in SAMPLE_ID.values() if '需造样本' in v]) == 2,
            '实际 %s' % len([1 for v in SAMPLE_ID.values() if '需造样本' in v]))
        chk('退役模块：edu_telegram 的行 scope=retired、且压过 portal/endpoint 判据',
            row_scope('edu_telegram', False, '/my/marks', 'user') == 'retired'
            and row_scope('edu_telegram', True, '/telegram/webhook', 'user') == 'retired'
            and row_scope('edu_portal', False, '/my/marks', 'user') == 'portal',
            '实际 %s / %s' % (row_scope('edu_telegram', False, '/my/marks', 'user'),
                              row_scope('edu_portal', False, '/my/marks', 'user')))
        _rm, _ra, _rg = merge_rows([dict(path='/my/marks', module='edu_telegram',
                                        kind='page', scope='retired',
                                        roles=['faculty'], gates=[],
                                        role_src='matrix',
                                        pending_gate='', pending_parent=None)],
                                   {'pages': [dict(path='/my/marks', key='k',
                                                   module='edu_telegram', kind='page',
                                                   roles=['faculty'],
                                                   gates=['route_matrix', 'english'],
                                                   reason='', status='unverified',
                                                   evidence='')]})
        chk('退役行：gates 被清空、status=n/a、reason 写明退役（不保留旧的已覆盖）',
            _rm[0]['gates'] == [] and _rm[0]['status'] == 'n/a'
            and '已退役' in _rm[0]['reason'],
            '实际 %s / %s' % (_rm[0]['gates'], _rm[0]['status']))
        _m0, _a0, _g0 = merge_rows(rows, None)
        chk('夹具：gates 为空的行一律有 reason（E 组门禁不变式 2）',
            all(r['reason'] for r in _m0 if not r['gates']),
            '实际 %s' % [(r['path'], r['reason'][:16]) for r in _m0 if not r['gates']])
        chk('夹具：三个门禁都命中且顺序稳定',
            rows[0]['gates'] == ['route_matrix', 'accessibility', 'english'],
            '实际 %s' % rows[0]['gates'])
        chk('夹具：角色取自矩阵 expect 集（映射长名）',
            rows[0]['roles'] == ['admin', 'backoffice', 'faculty', 'parent', 'student'],
            '实际 %s' % rows[0]['roles'])
        chk('夹具：无抽取分歧（括号配对 vs ast）',
            not [n for n in notes if '抽取分歧' in n], '实际 %s' % notes)

        old_doc = {'pages': [
            dict(key='人工键', path='/my/thing', module='modA', kind='page',
                 roles=['student'], gates=['english'], reason='',
                 status='verified', evidence='人工填的证据'),
            dict(key='幽灵', path='/my/gone', module='modA', kind='page',
                 roles=['student'], gates=['route_matrix'], reason='',
                 status='unverified', evidence=''),
        ]}
        merged, added, ghost = merge_rows(rows, old_doc)
        byp = dict((r['path'], r) for r in merged)
        chk('合并：人工填的 gates 不被覆盖',
            byp['/my/thing']['gates'] == ['english'],
            '实际 %s' % byp['/my/thing']['gates'])
        chk('合并：人工填的 status / evidence 不被覆盖',
            byp['/my/thing']['status'] == 'verified'
            and byp['/my/thing']['evidence'] == '人工填的证据')
        chk('合并：人工填的 roles / key 不被覆盖',
            byp['/my/thing']['roles'] == ['student']
            and byp['/my/thing']['key'] == '人工键')
        chk('合并：源码里的新页面进 added',
            '/my/thing/<int:tid>' in added, '实际 %s' % added)
        chk('合并：消失的路由保留在册并标 gap',
            '/my/gone' in ghost and byp['/my/gone']['status'] == 'gap'
            and '已消失' in byp['/my/gone']['evidence'])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    chk('判据：门户前缀边界（连字符命中、复数不命中）',
        is_portal('/my') and is_portal('/my-courses') and is_portal('/online-exams')
        and is_portal('/my/child/<int:child_id>')
        and not is_portal('/courses') and not is_portal('/courses-offered'))
    chk('判据：端点 token（download / file / pdf 命中，grade-book 不命中）',
        is_endpoint('/downloads') and is_endpoint('/my/assignment/sub/<int:sid>/file')
        and is_endpoint('/my/invoice/pdf/<int:move_id>') and not is_endpoint('/grade-book'))
    chk('key：/leave/approvals/<int:leave_id> -> leave_approvals_detail',
        make_key('/leave/approvals/<int:leave_id>') == 'leave_approvals_detail',
        '实际 %s' % make_key('/leave/approvals/<int:leave_id>'))

    drift = emitted != SELFTEST_CASES
    ok = ok and not drift
    print('  %-4s %-40s 实际 %d / 声明 %d%s'
          % ('PASS' if not drift else 'FAIL', 'selftest_cases', emitted,
             SELFTEST_CASES, '' if not drift else '（漂移：请同步 SELFTEST_CASES）'))
    print('== 反例自检 %s == %s' % ('通过' if ok else '未通过', self_attest_line()))
    return 0 if ok else 1


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description='门户 UI 表面清单与覆盖率量具（A 组）')
    ap.add_argument('--coverage', action='store_true', help='打印覆盖率与死角')
    ap.add_argument('--generate', action='store_true',
                    help='从路由重生成 tests/ui/surface.json')
    ap.add_argument('--selftest', action='store_true', help='反例自检（/tmp 夹具，不连站点）')
    ap.add_argument('--surface', default=None, help='surface.json 路径（默认 tests/ui/surface.json）')
    ap.add_argument('--quiet', action='store_true', help='只出汇总，不列死角逐条')
    ap.add_argument('--force', action='store_true',
                    help='放行「会移除已有 gates」的生成（防静默丢失护栏的显式开关）')
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.generate:
        return do_generate(args.surface, quiet=args.quiet, force=args.force)
    if args.coverage:
        return do_coverage(args.surface, quiet=args.quiet)
    return do_check(args.surface)


if __name__ == '__main__':
    sys.exit(main())
