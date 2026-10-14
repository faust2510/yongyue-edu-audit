#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静态门禁：UI 表面覆盖完整性（v1）。

触发事件：门户页面由三个 UI 门禁分头覆盖，但**名单各写各的** ⇒ 新页面自动落在名单外。
活证：新模块 edu_assess（10 页）上线后，三个门禁一个都没覆盖它。

不变式（三条缺一不可，逐条对应下面的实现）：
  1. 登记完备（路由 ↔ tests/ui/surface.json 双向）：仓内每条 @http.route 声明都必须能在
     pages[].path 找到（未登记 ⇒ 报红「新路由未登记」+ 打印 **文件:行号**）；
     反向：登记了但仓内已无此路由 ⇒ 报红「登记已失效」。
     （上游模块渲染、本项目不声明该路由的条目 —— 如 '/' 由 Odoo website 核心渲染 —— 用
     ALLOW_NO_ROUTE 显式豁免；命中时打一行 ALLOW，不是静默放过。）
  2. 覆盖有据：kind==page 的登记 gates 必须非空；为空则 reason 必须非空。
     kind==endpoint 豁免渲染门禁，但要求 roles 非空或 reason 非空。
     （gates 是闭集 route_matrix|accessibility|english|ui_surface，闭集外的值与未知 kind 另报。）
  3. 名单一致：抽取三个门禁脚本**模块级名单常量**里的路由字面量，与 surface.json 互相印证 ——
     surface 说某页由 X 覆盖 ⇒ 该路由必须真出现在 X 脚本的名单里；反之亦然，不一致报红。
     （正方向允许「脚本写短式、登记写动态长式」；反方向只认归一后相等 —— 详见下面解析口径。）
     **函数体内的字面量一律不算覆盖声明**：三个脚本的 selftest 夹具 / prove_invariant 样本
     长得和真名单一模一样，拿它们当名单 = 「判据量到的是工具自己的零件」（见解析口径第 3 条）。
     若某脚本已改成从 surface.json 读（文本含 surface.json）⇒ 只判「确实是从文件读的」，
     不再逐路由比对。两种形态**自动识别**（B 组逐脚本迁移，混合态是常态，必须都能跑）。

设计约束：零环境依赖（不连 DB / 不发 HTTP / 不读容器，停机可跑）；**只读**，绝不生成/修改 surface.json；
退出码 0=OK 1=FAIL 2=ENV 3=INCOMPLETE；自证行 打印 REVISION · 指纹 · 断言数 · 时刻。
⚠️ surface.json 不存在 ⇒ 退出码 **3=INCOMPLETE**，明说「surface.json 尚未生成」，**不崩栈、不判 FAIL**
（那张表由生成方产出，本门禁是消费者；缺表不是本次改动的错，判 FAIL 只会教人忽略红灯）。

解析口径（两处都是刻意的，不是随手写的正则）：
  · 路由字面量走**字符扫描 + 装饰器括号配对**，不用行正则：@http.route 可以写成列表形式
    （仓内已有 5 处 @http.route([...])），规格里的行正则只取得到第一个串，
    那几条路由就永远不会被不变式 1 看见 —— 漏报比误报危险。对单串形式，两种解析同解。
  · 动态段归一：<int:leave_id> / <leave_id> / <task_id> 一律折成 <>，再按**路径段边界**比前缀，
    于是门禁名单里的 '/leave/approvals' 与登记里的 '/leave/approvals/<int:leave_id>' 判为同一路由。
    没有这一步，动态路由页会被判成「覆盖缺失」，而那正是本仓最常见的路由形态。
    方向不对称也是刻意的：**正方向**（surface 说 X 覆盖 ⇒ X 脚本名单里得有）允许前缀，
    因为门禁脚本对动态路由习惯写前缀；**反方向**（X 脚本名单里有 ⇒ surface 得登记 X）只认相等，
    否则脚本里一句 '/leave/approvals' 会把该子树下每条页全判成「未登记该脚本」。
  · 覆盖声明**只认模块级顶层赋值**（ROUTES = [...] / PAGES = [...] / REDIRECT_STRICT = {...} 之类），
    用 ast 只走 Module.body —— 函数体内的字面量、注释里提到的旧路由，统统不算数。
    这条是被一次**假红**教出来的：/web/register 的真名单里没有它（check_english 的真身是 /register），
    但脚本的 selftest 夹具（def selftest 内的 inv_cases）与 prove_invariant 样本里有它，
    于是本门禁反过来指控 surface「漏登记了 check_english 的覆盖」——判据量到的是工具自己的零件。
    若某脚本的名单不可静态解析（路由字面量只出现在函数体内 / 语法错），则**不逐路由比对**，
    只把该脚本标为「不可静态核对」并在表头点名；绝不拿函数里的样本凑数。
"""
import argparse, ast, contextlib, hashlib, io, json, os, shutil, sys, tempfile
from datetime import datetime

REVISION = 'v1.0'
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SURFACE = 'tests/ui/surface.json'
ADDONS = 'custom_addons'

# 三个 UI 门禁脚本 ↔ surface.json 的 gates 名。闭集里第四项 ui_surface 是本脚本自身：
# 它是**登记表的维护者**，不是又一份名单，故不参与不变式 3 的逐路由比对（下面只记数并说明）。
GATES = (
    ('route_matrix', 'tests/smoke/ux_v3_route_matrix.py'),
    ('accessibility', 'scripts/check_accessibility.py'),
    ('english', 'scripts/check_english.py'),
)
GATE_NAMES = ('route_matrix', 'accessibility', 'english', 'ui_surface')
KINDS = ('page', 'endpoint')
FROM_FILE_MARK = 'surface.json'   # 脚本文本出现它 ⇒ 认定该脚本已改为从注册表读（形态 B）

# 例外登记：确需不登记的仓内路由（键=路由字面量，值=理由）。**只豁免不变式 1**，
# 不变式 2 / 3 照查 —— 例外不是免检，否则这张表迟早变成垃圾桶。初始为空（当前无例外）。
ALLOW_UNREGISTERED = {}

# 表内存在、但仓内没有对应 @http.route 的条目（由上游模块渲染）。
# 例外必须显式且带理由，否则「登记了却不存在」会静默通过。
# 只豁免不变式 1 的**反方向**（登记已失效）；命中时会打一行 ALLOW 让人看见，不是静默放过。
ALLOW_NO_ROUTE = {
    '/': 'Odoo website 核心渲染；本项目不声明该路由（见 custom_addons/edu_brand 的首页模板覆盖）',
    # 2026-09-28（后台覆盖）：Odoo 19 后台 Web 客户端路由 —— 核心 web 模块渲染，本仓不声明。
    # 登记理由：无障碍门禁原先**只扫门户/公开页**，导航栏那批「只在后台出现、只在品牌蓝上是错的」
    # 元素永远无人覆盖；这两条是补进去的后台代表页（扫描身份 backoffice）。
    '/odoo/contacts': 'Odoo 19 后台 web 客户端路由（核心 res.partner 列表视图）：核心渲染，本仓不声明；'
                      '为 scripts/check_accessibility.py 的后台覆盖而登记',
    '/odoo/students': 'Odoo 19 后台 web 客户端路由（本校「学生信息」应用根）：核心渲染 + 核心动作，本仓不声明；'
                      '同上（该页导航栏带 o_menu_sections 区段条目）',
    # 2026-09-29（后台扩覆盖 2 页 → 7 页）：上一轮只验 2 页，其余模型的列表/表单页没逐个量过。
    # 这一批仍是**同一类**豁免，理由也同一句话：路径由 Odoo 19 **核心 web 客户端**的路由表解析
    # （/odoo/<action path>[/<record id>]），渲染在核心的 Owl 组件里，custom_addons 里**没有**对应的
    # @http.route —— 所以 A 组的路由抽取器（遍历 custom_addons 的 @http.route）**结构上看不见它们**。
    # 不豁免的后果不是"少一条"，而是「登记已失效」⇒ 本门禁 exit 1 —— 那会把一条**正确**的登记判成坏表。
    # 与前面两条一样：命中只豁免不变式 1 的反方向，不变式 2（覆盖有据）照查，且会打 ALLOW 行。
    '/odoo/batches': 'Odoo 19 后台 web 客户端路由（自研 op.batch 列表，路径由核心 action 的 path 字段解析）：'
                     '核心渲染，custom_addons 无 @http.route；为 scripts/check_accessibility.py 的后台'
                     '「列表」形态覆盖而登记（2026-09-29 扩覆盖）',
    '/odoo/apps': 'Odoo 19 后台 web 客户端路由（核心 ir.module.module 卡片看板）：核心渲染，'
                  'custom_addons 无 @http.route；为后台「看板」形态覆盖而登记（图片/卡片那条线只在它上面有样本）',
    '/odoo/contacts/1': 'Odoo 19 后台 web 客户端路由（核心 res.partner **记录表单**，末段是记录 id 而不是静态路径段）：'
                        '核心渲染，custom_addons 无 @http.route；为后台「表单」形态覆盖而登记',
    '/odoo/students/5': 'Odoo 19 后台 web 客户端路由（自研 op.student **记录表单**，末段是记录 id）：'
                        '核心渲染，custom_addons 无 @http.route；为自研模块的「表单」形态覆盖而登记',
    '/odoo/grade-configuration': 'Odoo 19 后台 web 客户端路由（另一应用「时间表/考试」的配置分区列表）：'
                                 '核心渲染，custom_addons 无 @http.route；它的导航栏区段形态最复杂'
                                 '（6 个扁平 menuitem + 8 个下拉按钮），为 aria-required-children 那条线而登记',
}

# 字符常量：全程不写反斜杠转义，免得被别的层吃掉（check_docs_index 把反引号写成 chr(96) 是同一教训）。
NL = chr(10)
SQ, DQ = chr(39), chr(34)
DYN = '<' + '>'                    # 动态段归一后的占位
RC_NAME = {0: 'OK', 1: 'FAIL', 2: 'ENV', 3: 'INCOMPLETE'}

# 违规类别 → 中文标签（打印顺序即此顺序）
CATS = (
    ('unregistered', '新路由未登记'),
    ('stale', '登记已失效'),
    ('gate_missing', '页无门禁且无理由'),
    ('endpoint_naked', 'endpoint 无角色且无理由'),
    ('gate_unknown', '门禁名或 kind 不在闭集'),
    ('list_missing', '名单不一致：surface 说 X 覆盖，X 脚本里没有'),
    ('list_extra', '名单不一致：X 脚本里有，surface 未登记 X'),
)


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def self_fingerprint():
    try:
        with open(os.path.abspath(__file__), 'rb') as fh:
            return hashlib.md5(fh.read()).hexdigest()[:8]
    except OSError:
        return '????????'


def read_text(path):
    """读文本；读不到 / 不是 UTF-8 返回 None（调用方记 INCOMPLETE，绝不猜）。"""
    try:
        return io.open(path, encoding='utf-8').read()
    except (OSError, UnicodeDecodeError):
        return None


def norm_path(p):
    """路由归一：去空白 / 去尾斜杠 / 动态段（<...>）一律折成 <>。"""
    s = (p or '').strip()
    while len(s) > 1 and s.endswith('/'):
        s = s[:-1]
    out = []
    i = 0
    while i < len(s):
        if s[i] == '<':
            j = s.find('>', i)
            if j < 0:
                out.append(s[i:])
                break
            out.append(DYN)
            i = j + 1
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def same_route(a, b):
    """同一路由：归一后相等，或一方是另一方的**路径段**前缀（动态段写在任一侧都算）。

    只按段边界比（a + 分隔符），所以 '/my' 不会误吞 '/my-library'；
    空值一律判不同，免得空 path 的坏登记把任何字面量都吸过来。
    """
    a, b = norm_path(a), norm_path(b)
    if not a or not b:
        return False
    if a == b:
        return True
    return b.startswith(a + '/') or a.startswith(b + '/')


def allow_no_route_reason(path):
    """命中 ALLOW_NO_ROUTE 则返回理由（键按归一后比对），否则 None。"""
    n = norm_path(path)
    for k, v in ALLOW_NO_ROUTE.items():
        if norm_path(k) == n:
            return v
    return None


def quoted_literals(text):
    """字符扫描取引号字面量 → [(值, 行号, 前一个字符)]。

    ⚠️ 它**不**用于覆盖判定（那件事交给 module_level_routes 的 ast 走树）：
    原始文本扫描连注释与 selftest 夹具里的串都算，正是 /web/register 假红的来源。
    这里只用来回答一个诊断问题：这个脚本里到底还有没有路由字面量（据此区分
    「名单不可静态解析」与「压根没写名单」），以及给 parse_routes 做装饰器取字面量。
    """
    out = []
    line = 1
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == NL:
            line += 1
            i += 1
            continue
        if ch == SQ or ch == DQ:
            start_line = line
            j = i + 1
            buf = []
            while j < n and text[j] != ch:
                if text[j] == NL:
                    line += 1
                buf.append(text[j])
                j += 1
            out.append((''.join(buf), start_line, text[i - 1] if i > 0 else ''))
            i = j + 1
            continue
        i += 1
    return out


def parse_routes(text):
    """取每个 @http.route 装饰器的整段文本（括号配对），抽出其中以 / 打头的路由字面量。

    返回 [(route, lineno)]；列表形式 @http.route(['/a', '/b']) 两条都算。
    """
    out = []
    key = '@http.route('
    pos = 0
    n = len(text)
    while True:
        k = text.find(key, pos)
        if k < 0:
            return out
        line0 = text.count(NL, 0, k) + 1
        i = k + len(key) - 1        # 指向装饰器的左括号
        depth = 0
        j = i
        while j < n:
            c = text[j]
            if c == SQ or c == DQ:  # 跳过字符串，免得括号出现在串里把配对带偏
                jj = j + 1
                while jj < n and text[jj] != c:
                    jj += 1
                j = jj + 1
                continue
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        for val, rel, _prev in quoted_literals(text[i:j + 1]):
            v = val.strip()
            if v.startswith('/'):
                out.append((v, line0 + rel - 1))
        pos = k + len(key)


def module_level_routes(text):
    """只取**模块级顶层赋值**里的路由字面量 → [(值, 行号)]；语法解析不了返回 None。

    为什么挑食：三个门禁脚本里都有 selftest 夹具 / prove_invariant 样本，它们长得和真名单
    一模一样（同一批路由字面量），拿它们当覆盖声明就是「判据量到的是工具自己的零件」——
    /web/register 那条假红正是这么来的：真名单（PUBLIC_ROUTES/PORTAL_ROUTES/...）里没有它，
    只有夹具里有。顶层赋值才是脚本对外的覆盖声明，def 里的一切天然出局。

    实现走 ast 而不是正则：注释里的旧路由、HTML 片段、f-string 碎片都不会被误当成路由
    （f-string 在树上是 JoinedStr，整段跳过，免得把它的固定前缀也算成一条路由）。
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    out = []
    for node in tree.body:                      # 只走顶层 ⇒ def / class / with 里的一切出局
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            value = node.value
        else:
            continue
        if value is None:
            continue
        stack = [value]
        while stack:
            cur = stack.pop()
            if isinstance(cur, ast.JoinedStr):
                continue
            if isinstance(cur, ast.Constant) and isinstance(cur.value, str):
                v = cur.value.strip()
                if v.startswith('/'):
                    out.append((v, getattr(cur, 'lineno', 0)))
                continue
            for child in ast.iter_child_nodes(cur):
                stack.append(child)
    return out


def repo_routes(root):
    """遍历 custom_addons/**/*.py（跳过 __pycache__）→ (routes, unreadable)。

    routes = [(route, 仓库相对路径, 行号)]；custom_addons/ 不存在返回 (None, None)（调用方判 ENV）。
    """
    base = os.path.join(root, ADDONS)
    if not os.path.isdir(base):
        return None, None
    routes, bad = [], []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d != '__pycache__')
        for fn in sorted(filenames):
            if not fn.endswith('.py'):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace(os.sep, '/')
            text = read_text(p)
            if text is None:
                bad.append(rel)
                continue
            for route, line in parse_routes(text):
                routes.append((route, rel, line))
    return routes, bad


def gate_literals(root):
    """读三个门禁脚本 → {门禁名: {rel, ok, parse_ok, from_file, lits, n_raw}}。

    lits = **模块级名单常量**里的路由字面量（唯一可用于覆盖判定的东西）；
    n_raw = 全文里以 / 打头的引号字面量条数，只用于诊断「名单是不是动态构造的」。
    """
    info = {}
    for name, rel in GATES:
        text = read_text(os.path.join(root, rel))
        mod, n_raw, parse_ok = [], 0, False
        if text is not None:
            n_raw = len([1 for val, _ln, _p in quoted_literals(text)
                         if val.strip().startswith('/')])
            got = module_level_routes(text)
            if got is None:
                parse_ok = False
            else:
                parse_ok = True
                mod = got
        info[name] = {
            'rel': rel,
            'ok': text is not None,
            'parse_ok': parse_ok,
            'from_file': (text is not None) and (FROM_FILE_MARK in text),
            'lits': mod,
            'n_raw': n_raw,
        }
    return info


def finish(rc, F, notes, incomplete, stat, n_assert, quiet=False):
    """统一收尾：逐条点名的 FAIL 清单 + 结论 + 自证行 + 契约行（照 check_docs_index 体例）。"""
    if not quiet:
        if stat.get('loaded'):
            print('== UI 表面覆盖检查（%s）==' % SURFACE)
            print('仓内 @http.route %d 条（%d 个文件）｜登记 %d 条｜有门禁页 %d｜'
                  '无门禁但有理由的页 %d｜例外登记 %d 条'
                  % (stat['routes'], stat['files'], stat['pages'], stat['gated'],
                     stat['reasoned'], len(ALLOW_UNREGISTERED)))
            print('  门禁脚本形态：%s'
                  % (' · '.join('%s=%s' % (k, stat['mode'][k]) for k, _r in GATES) or '（无可判脚本）'))
            if stat.get('self_gate'):
                print('  note：%d 条登记的 gates 含 ui_surface —— 那是本脚本自身（登记表的维护者），'
                      '不参与逐路由名单比对' % stat['self_gate'])
            for nm in sorted(stat.get('unparsed') or {}):
                print('  note：%s 的名单不是模块级常量（%s）⇒ 不变式 3 对它只标注「不可静态核对」，'
                      '不逐路由比对（函数体内的样本不算覆盖声明）' % (nm, stat['unparsed'][nm]))
            n_hit = sum(len(F[k]) for k, _l in CATS)
            print('  违规 %d 条（%s）'
                  % (n_hit, '、'.join('%s %d' % (label, len(F[k])) for k, label in CATS)))
        for line in notes:
            print(line)
        for k, label in CATS:
            for name, why in F[k]:
                print('  FAIL %s：%s%s' % (label, name, ('（%s）' % why) if why else ''))
        for r in sorted(ALLOW_UNREGISTERED):
            print('  ALLOW 例外登记（只豁免不变式 1）：%s（%s）' % (r, ALLOW_UNREGISTERED[r]))
        for p in (stat.get('allow_no_route') or []):
            print('  ALLOW 表内条目无对应 @http.route（豁免「登记已失效」，仍计入登记数）：%s（%s）'
                  % (p, allow_no_route_reason(p) or ''))
        for p in incomplete:
            print('  INCOMPLETE %s' % p)
        print('结论：%s' % RC_NAME.get(rc, '?'))
        print('自证：REVISION=%s · 指纹 %s · 断言 %d 条 · 时刻 %s'
              % (REVISION, self_fingerprint(), n_assert, now()))
        print('契约：exit 0=OK 1=FAIL 2=ENV(custom_addons 不存在) '
              '3=INCOMPLETE(surface.json 尚未生成 / 读不到 / 门禁脚本读不到)')
    return {'rc': rc, 'findings': F, 'asserts': n_assert, 'incomplete': incomplete, 'stat': stat}


def check(root=REPO, quiet=False):
    """跑三条不变式。quiet=True 时不打印（自证用）。"""
    root = os.path.abspath(root)
    F = dict((k, []) for k, _l in CATS)
    notes, incomplete = [], []
    stat = {'routes': 0, 'files': 0, 'pages': 0, 'gated': 0, 'reasoned': 0, 'self_gate': 0,
            'mode': {}, 'allow_no_route': []}
    n_assert = 0

    routes, bad = repo_routes(root)
    if routes is None:
        notes.append('ENV：找不到 %s/ —— 无法判定（这不是通过）' % ADDONS)
        return finish(2, F, notes, incomplete, stat, n_assert, quiet)
    stat['routes'] = len(routes)
    stat['files'] = len(set(rel for _r, rel, _l in routes))
    for rel in bad:
        incomplete.append('源码读不到（非 UTF-8 或不可读）：%s' % rel)

    # ---- surface.json 必须先读得出来，否则后面的判定全是猜 ----
    raw = read_text(os.path.join(root, SURFACE))
    if raw is None:
        notes.append('INCOMPLETE：%s 尚未生成（读不到）—— 三条不变式都无从判定，这不是通过；'
                     '登记表由生成方产出，本门禁只读不写。' % SURFACE)
        return finish(3, F, notes, incomplete, stat, n_assert, quiet)
    try:
        data = json.loads(raw)
        pages = data['pages']
        if not isinstance(pages, list):
            raise ValueError('pages 不是列表')
    except (ValueError, TypeError, KeyError) as exc:
        incomplete.append('%s 解析失败：%s' % (SURFACE, exc))
        notes.append('INCOMPLETE：%s 读不出 pages —— 登记表坏了，交生成方修，这里不判 FAIL。' % SURFACE)
        return finish(3, F, notes, incomplete, stat, n_assert, quiet)

    pages = [p for p in pages if isinstance(p, dict)]
    stat['loaded'] = True
    stat['pages'] = len(pages)

    # ---- 不变式 1：登记完备（双向）----
    for route, rel, line in routes:
        if norm_path(route) in ALLOW_UNREGISTERED:
            continue
        if not any(same_route(route, p.get('path')) for p in pages):
            F['unregistered'].append((route, '%s:%d' % (rel, line)))
    for idx, pg in enumerate(pages):
        path = (pg.get('path') or '').strip()
        if not path:
            F['stale'].append(('(空 path)', 'pages[%d] 的 path 为空' % idx))
            continue
        if not any(same_route(path, r) for r, _rel, _l in routes):
            if allow_no_route_reason(path) is not None:
                stat['allow_no_route'].append(path)   # 上游模块渲染的条目：豁免，但下面会打 ALLOW 行
                continue
            F['stale'].append((path, 'pages[%d]' % idx))

    # ---- 不变式 2：覆盖有据 ----
    for idx, pg in enumerate(pages):
        path = (pg.get('path') or '').strip() or '(空 path)'
        kind = pg.get('kind')
        raw_gates = pg.get('gates')
        gates = raw_gates if isinstance(raw_gates, list) else []
        reason = (pg.get('reason') or '').strip()
        roles = pg.get('roles') if isinstance(pg.get('roles'), list) else []
        if kind not in KINDS:
            F['gate_unknown'].append((path, 'pages[%d] kind=%r 不在闭集 %s' % (idx, kind, list(KINDS))))
        for g in gates:
            if g not in GATE_NAMES:
                F['gate_unknown'].append((path, 'pages[%d] gates 含闭集外的 %r' % (idx, g)))
        if kind == 'page':
            if not gates and not reason:
                F['gate_missing'].append((path, 'pages[%d] gates 为空且 reason 也为空' % idx))
        elif kind == 'endpoint':
            if not roles and not reason:
                F['endpoint_naked'].append((path, 'pages[%d] roles 为空且 reason 也为空' % idx))
    stat['gated'] = len([p for p in pages if p.get('gates')])
    stat['reasoned'] = len([p for p in pages
                            if p.get('kind') == 'page' and not (p.get('gates') or [])
                            and (p.get('reason') or '').strip()])
    stat['self_gate'] = len([p for p in pages if 'ui_surface' in (p.get('gates') or [])])

    # ---- 不变式 3：名单一致（形态自动识别，逐脚本判；只对模块级名单比对）----
    gi = gate_literals(root)
    stat['mode'], stat['unparsed'] = {}, {}
    for name, _rel in GATES:
        info = gi[name]
        if info['from_file']:
            mode = '读 surface.json（形态 B，跳过逐路由比对）'
        elif not info['ok']:
            mode = '读不到'
        elif not info['parse_ok']:
            mode = '名单不可静态解析（语法错）'
        elif info['lits']:
            mode = '写死名单（模块级 %d 条）' % len(info['lits'])
        elif info['n_raw']:
            mode = '名单不可静态解析（路由字面量只在函数体内）'
        else:
            mode = '无可读名单'
        stat['mode'][name] = mode
        if not info['ok']:
            incomplete.append('门禁脚本读不到：%s' % info['rel'])
        elif not info['parse_ok']:
            incomplete.append('门禁脚本无法静态解析（语法错）：%s —— 名单不可静态核对' % info['rel'])
        elif (not info['from_file']) and (not info['lits']):
            stat['unparsed'][name] = mode
    seen_extra = set()
    for name, _rel in GATES:
        info = gi[name]
        # 只有「模块级写死名单」才逐路由比对；形态 B 与不可静态解析都跳过 —— 绝不对着零件量实物。
        if not (info['ok'] and info['parse_ok'] and info['lits'] and not info['from_file']):
            continue
        for pg in pages:
            path = (pg.get('path') or '').strip()
            if not path or name not in (pg.get('gates') or []):
                continue
            if not any(same_route(lit, path) for lit, _ln in info['lits']):
                F['list_missing'].append((path, '脚本 %s 的模块级名单里没有该路由（该脚本仍是写死名单）'
                                          % info['rel']))
        for lit, ln in info['lits']:
            if norm_path(lit) in ALLOW_UNREGISTERED:
                continue
            for pg in pages:
                path = (pg.get('path') or '').strip()
                # 反方向**只认归一后相等**（正方向才允许前缀）：脚本里写的短式 '/leave/approvals'
                # 证明不了它覆盖了哪条子路由，拿前缀去反推会把该子树下每条页全判成「未登记该脚本」——
                # 那是假红，而假红会让这条不变式被整体无视（真实数据演练里 492 条里大半是这类）。
                if not path or norm_path(lit) != norm_path(path):
                    continue
                if name in (pg.get('gates') or []):
                    continue
                key = (name, path)
                if key in seen_extra:
                    continue
                seen_extra.add(key)
                F['list_extra'].append((lit, '脚本 %s:%d 的模块级名单里有它，但登记 %s 的 gates=%s 未含 %s'
                                        % (info['rel'], ln, path, pg.get('gates'), name)))
    n_hit = sum(len(F[k]) for k, _l in CATS)
    n_assert = len(routes) + len(pages) + (0 if not stat['mode'] else len(GATES))
    rc = 1 if n_hit else (3 if incomplete else 0)
    return finish(rc, F, notes, incomplete, stat, n_assert, quiet)


def coverage(root=REPO):
    """打印登记覆盖率（报告，不是门禁）。"""
    root = os.path.abspath(root)
    raw = read_text(os.path.join(root, SURFACE))
    ok = raw is not None
    pages = []
    if ok:
        try:
            data = json.loads(raw)
            pages = [p for p in data['pages'] if isinstance(p, dict)]
        except (ValueError, TypeError, KeyError) as exc:
            print('INCOMPLETE：%s 解析失败（%s）—— 无覆盖可统计（这不是通过）' % (SURFACE, exc))
            print('自证：REVISION=%s · 指纹 %s · 断言 0 条 · 时刻 %s' % (REVISION, self_fingerprint(), now()))
            return 3
    if not ok:
        print('INCOMPLETE：%s 尚未生成（读不到）—— 无覆盖可统计（这不是通过）' % SURFACE)
        print('自证：REVISION=%s · 指纹 %s · 断言 0 条 · 时刻 %s' % (REVISION, self_fingerprint(), now()))
        return 3
    n_page = len([p for p in pages if p.get('kind') == 'page'])
    gated = len([p for p in pages if p.get('gates')])
    reasoned = len([p for p in pages if p.get('kind') == 'page' and not (p.get('gates') or [])
                    and (p.get('reason') or '').strip()])
    print('== UI 表面覆盖统计 ==')
    print('登记路由数 %d ｜ 门户页数 %d ｜ 有门禁页数 %d ｜ 无门禁但有理由的页数 %d ｜ 例外登记条数 %d'
          % (len(pages), n_page, gated, reasoned, len(ALLOW_UNREGISTERED)))
    print('自证：REVISION=%s · 指纹 %s · 断言 %d 条 · 时刻 %s'
          % (REVISION, self_fingerprint(), len(pages), now()))
    return 0


# --------------------------------------------------------------------------
# 反例自检：全部在 tempfile 临时目录里造夹具，**绝不依赖真实文件**
# --------------------------------------------------------------------------
def mk(root, rel, text):
    p = os.path.join(root, rel)
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    io.open(p, 'w', encoding='utf-8').write(text)


def selftest():
    tmp = tempfile.mkdtemp(prefix='check_ui_surface_')
    defect, good = [], []
    ok = False
    try:
        addon_py = (
            'from odoo import http' + NL +
            'class Portal(http.Controller):' + NL +
            "    @http.route('/leave/approvals', type='http', auth='user')" + NL +
            '    def leave_list(self, **kw):' + NL +
            '        pass' + NL +
            "    @http.route('/leave/approvals/<int:leave_id>', type='http')" + NL +
            '    def leave_detail(self, leave_id, **kw):' + NL +
            '        pass' + NL +
            "    @http.route('/leave/approvals/<int:leave_id>/log', type='http')" + NL +
            '    def leave_log(self, leave_id, **kw):' + NL +
            '        pass' + NL +
            "    @http.route(['/assess/my', '/assess/review'], type='http')" + NL +
            '    def assess(self, **kw):' + NL +
            '        pass' + NL)
        new_py = (
            'from odoo import http' + NL +
            'class New(http.Controller):' + NL +
            "    @http.route('/brand/new/page', type='http', auth='user')" + NL +
            '    def brand_new(self, **kw):' + NL +
            '        pass' + NL)
        gate_rm = ("ROUTES = [" + NL +
                   "    ('/leave/approvals', 'faculty')," + NL +
                   ']' + NL)
        gate_a11y = "CASES = [('student', '/assess/my')]" + NL
        gate_en = 'import json' + NL + "SURFACE = 'tests/ui/surface.json'" + NL
        a11y_route = "'/assess/my'"

        def surface(pages):
            return json.dumps({'surface-version': 'v1', 'generated': '2026-09-26',
                               'source': 'custom_addons/**/*.py :: @http.route',
                               'pages': pages}, ensure_ascii=False, indent=1)

        def page(key, path, kind='page', gates=None, reason='', roles=None):
            return {'key': key, 'path': path, 'module': 'edu_portal', 'kind': kind,
                    'roles': roles if roles is not None else ['faculty'],
                    'gates': gates if gates is not None else [], 'reason': reason,
                    'status': 'unverified', 'evidence': ''}

        base_pages = [
            page('leave_list', '/leave/approvals', gates=['route_matrix']),
            page('leave_detail', '/leave/approvals/<int:leave_id>', gates=['route_matrix']),
            # 子路由挂在门禁短式 '/leave/approvals' 之下，但**没有**声明 route_matrix：
            # 反方向只认相等，故这一条必须不报红（前缀式反推是假红来源）。
            page('leave_log', '/leave/approvals/<int:leave_id>/log', gates=['english']),
            page('assess_my', '/assess/my', gates=['accessibility', 'english']),
            page('assess_review', '/assess/review', kind='endpoint', roles=[],
                 reason='JSON 端点，不渲染页面，无需渲染门禁'),
        ]

        def case(name, pages, extra_py=None, rm_text=gate_rm, with_surface=True):
            root = os.path.join(tmp, name)
            os.makedirs(root)
            mk(root, 'custom_addons/edu_portal/controllers/main.py', addon_py)
            if extra_py:
                mk(root, extra_py[0], extra_py[1])
            mk(root, GATES[0][1], rm_text)
            mk(root, GATES[1][1], gate_a11y)
            mk(root, GATES[2][1], gate_en)
            if with_surface:
                mk(root, SURFACE, surface(pages))
            return root

        res = {}
        # ---- 正例：登记齐、名单一致、动态段两侧写法不同、endpoint 有理由、english 已读文件 ----
        root = case('good', base_pages)
        res['good'] = check(root=root, quiet=True)
        good.append(('正例 · 登记齐 + 名单一致 + 动态段归一 + 形式 B 自动识别 ⇒ 零违规',
                     res['good']['rc'] == 0 and sum(len(v) for v in res['good']['findings'].values()) == 0))
        good.append(("动态段归一：门禁写短式 '/leave/approvals'，登记写长式 '/leave/approvals/<int:leave_id>' ⇒ 不算缺失",
                     not res['good']['findings']['list_missing']))
        good.append(('形式 B 自动识别：english 脚本只含 surface.json 字样、一个路由字面量都没有 ⇒ 不逐路由比对',
                     not any('check_english.py' in w for _n, w in res['good']['findings']['list_missing'])))
        good.append(('列表形式 @http.route([...]) 两条都抽到 ⇒ 无「登记已失效」误报',
                     not any(n == '/assess/review' for n, _w in res['good']['findings']['stale'])))
        good.append(('反方向只认相等：脚本里的短式 /leave/approvals 不把子路由 /leave/approvals/<int:leave_id>/log 判成「未登记该脚本」',
                     not any(n.endswith('/log') for n, _w in res['good']['findings']['list_extra'])))

        # ---- 正例：函数体内的夹具样本**不算**覆盖声明（/web/register 假红的回归守卫）----
        # 真名单（模块级 PUBLIC_ROUTES）里没有 /web/register，只有 def _selftest() 的样本里有；
        # 若把样本当名单，就会反过来指控 surface「漏登记了 check_english 的覆盖」。
        body_rm = ("ROUTES = [" + NL +
                   "    ('/leave/approvals', 'faculty')," + NL +
                   "    ('/web/register', 'guest')," + NL +
                   ']' + NL)
        body_en = ("PUBLIC_ROUTES = ['/about', '/assess/my', "
                   "'/leave/approvals/<int:leave_id>/log']" + NL + NL +
                   'def _selftest():' + NL +
                   "    inv_cases = ['/web/register']      # 夹具样本：长得像名单，但不是覆盖声明" + NL +
                   '    return inv_cases' + NL)
        body_pages = base_pages + [
            page('web_register', '/web/register', gates=['route_matrix']),
            page('about', '/about', gates=['english']),
        ]
        root = case('body_sample', body_pages, rm_text=body_rm, extra_py=(
            'custom_addons/edu_web/controllers/main.py',
            'from odoo import http' + NL +
            "class W(http.Controller):" + NL +
            "    @http.route('/web/register', type='http')" + NL +
            '    def w(self, **kw):' + NL +
            '        pass' + NL +
            "    @http.route('/about', type='http')" + NL +
            '    def a(self, **kw):' + NL +
            '        pass' + NL))
        mk(root, GATES[2][1], body_en)
        res['body_sample'] = check(root=root, quiet=True)
        good.append(('函数体内的夹具样本不算覆盖：/web/register 只在 english 的 def _selftest() 里出现 ⇒ 不报「名单不一致」',
                     res['body_sample']['rc'] == 0
                     and not any(n == '/web/register'
                                 for n, _w in res['body_sample']['findings']['list_extra'])))
        good.append(('同一夹具里英文脚本的模块级名单（/about 等）照常参与比对 ⇒ 不是「整段跳过」',
                     not any('check_english' in w
                             for _n, w in res['body_sample']['findings']['list_missing'])))

        # ---- 正例：名单是动态构造的（路由字面量只在函数体内）⇒ 判「不可静态核对」、跳过比对 ----
        dyn_rm = ('def routes():' + NL +
                  "    return ['/leave/approvals']      # 名单在函数里拼，模块级看不到" + NL)
        root = case('dynamic', base_pages, rm_text=dyn_rm)
        res['dynamic'] = check(root=root, quiet=True)
        good.append(('名单不可静态解析（只在函数体内）⇒ 表头点名 + 跳过逐路由比对，不拿样本凑数也不误报',
                     res['dynamic']['rc'] == 0
                     and res['dynamic']['stat']['mode']['route_matrix'].startswith('名单不可静态解析')
                     and 'route_matrix' in res['dynamic']['stat']['unparsed']))

        # ---- 反例 ① 新路由未登记 ----
        root = case('new_route', base_pages,
                    extra_py=('custom_addons/edu_new/controllers/main.py', new_py))
        res['new_route'] = check(root=root, quiet=True)
        # 期望的行号从夹具文本自身算出来，不写死 —— 改了夹具就跟着改，不会静默失配
        want = 'edu_new/controllers/main.py:%d' % (new_py.count(NL, 0, new_py.find('@http.route')) + 1)
        defect.append(('① 新路由未登记 ⇒ 报红且点名 文件:行号（%s）' % want,
                       any(n == '/brand/new/page' and w.endswith(want)
                           for n, w in res['new_route']['findings']['unregistered'])))

        # ---- 反例 ② 登记已失效 ----
        root = case('stale', base_pages + [page('ghost', '/ghost', gates=['route_matrix'])])
        res['stale'] = check(root=root, quiet=True)
        defect.append(('② 表里有 /ghost 但仓内无该路由、且不在 ALLOW_NO_ROUTE 里 ⇒ 必须报红「登记已失效」',
                       any(n == '/ghost' for n, _w in res['stale']['findings']['stale'])))

        # ---- 反例 ③ page 无 gates 且无 reason / endpoint 无 roles 且无 reason / 闭集外的门禁名 ----
        bad_pages = [
            page('leave_list', '/leave/approvals', gates=['route_matrix']),
            page('leave_detail', '/leave/approvals/<int:leave_id>', gates=[], reason=''),
            page('assess_my', '/assess/my', gates=['accessibility', 'english']),
            page('assess_review', '/assess/review', kind='endpoint', roles=[], reason=''),
            page('weird', '/assess/my', gates=['not_a_gate']),
        ]
        root = case('no_gate', bad_pages)
        res['no_gate'] = check(root=root, quiet=True)
        defect.append(('③ page 的 gates 为空且 reason 为空 ⇒ 报红',
                       any(n == '/leave/approvals/<int:leave_id>'
                           for n, _w in res['no_gate']['findings']['gate_missing'])))
        defect.append(('③b endpoint 的 roles 为空且 reason 为空 ⇒ 报红',
                       any(n == '/assess/review' for n, _w in res['no_gate']['findings']['endpoint_naked'])))
        defect.append(('③c gates 含闭集外的名字 ⇒ 报红',
                       any('not_a_gate' in w for _n, w in res['no_gate']['findings']['gate_unknown'])))

        # ---- 反例 ④ 名单不一致（两个方向）----
        fwd_pages = [dict(p) for p in base_pages]
        for _i, _p in enumerate(fwd_pages):     # 按键定位，不用下标（base_pages 会增删）
            if _p['key'] == 'assess_my':
                fwd_pages[_i] = page('assess_my', '/assess/my',
                                     gates=['accessibility', 'english', 'route_matrix'])
        root = case('list_missing', fwd_pages)
        res['list_missing'] = check(root=root, quiet=True)
        defect.append(('④a surface 说 route_matrix 覆盖 /assess/my，而脚本里没有 ⇒ 报红',
                       any(n == '/assess/my' and 'ux_v3_route_matrix' in w
                           for n, w in res['list_missing']['findings']['list_missing'])))

        rev_pages = base_pages + [page('extra', '/extra/route', gates=['english'])]
        extra_py = ('custom_addons/edu_extra/controllers/main.py',
                    'from odoo import http' + NL +
                    "class E(http.Controller):" + NL +
                    "    @http.route('/extra/route', type='http')" + NL +
                    '    def e(self, **kw):' + NL +
                    '        pass' + NL)
        root = case('list_extra', rev_pages, extra_py=extra_py,
                    rm_text=gate_rm + "MORE = ['/extra/route']" + NL)
        res['list_extra'] = check(root=root, quiet=True)
        defect.append(('④b 脚本里写了 /extra/route，而 surface 未登记该脚本覆盖 ⇒ 报红',
                       any(n == '/extra/route' and 'route_matrix' in w
                           for n, w in res['list_extra']['findings']['list_extra'])))

        # ---- 反例 ④c 模块级名单真缺一条：函数体内有样本也不能顶替 ⇒ 必须报红 ----
        miss_a11y = ("AUDIT_ROUTES = ['/assess/my']" + NL + NL +
                     'def prove_invariant():' + NL +
                     "    sample = ['/about']      # 样本里有、真名单里没有 ⇒ 仍应报红" + NL +
                     '    return sample' + NL)
        root = case('mod_missing', base_pages + [page('about', '/about', gates=['accessibility'])],
                    extra_py=('custom_addons/edu_about/controllers/main.py',
                              'from odoo import http' + NL +
                              "class A(http.Controller):" + NL +
                              "    @http.route('/about', type='http')" + NL +
                              '    def a(self, **kw):' + NL +
                              '        pass' + NL))
        mk(root, GATES[1][1], miss_a11y)
        res['mod_missing'] = check(root=root, quiet=True)
        defect.append(('④c 模块级名单真缺一条（函数体内的样本有它也不能顶替）⇒ 报红',
                       any(n == '/about' and 'check_accessibility' in w
                           for n, w in res['mod_missing']['findings']['list_missing'])))

        # ---- 反例 ⑤ surface.json 尚未生成 ⇒ 3=INCOMPLETE，不崩栈、不判 FAIL ----
        root = case('no_surface', [], with_surface=False)
        res['no_surface'] = check(root=root, quiet=True)
        defect.append(('⑤ surface.json 尚未生成 ⇒ exit 3=INCOMPLETE，不崩栈、不判 FAIL',
                       res['no_surface']['rc'] == 3))
        defect.append(('⑤b 缺表时不产生违规（不把「还没生成」当成错）',
                       sum(len(v) for v in res['no_surface']['findings'].values()) == 0))

        # ---- 正例 2：表里有 '/'（Odoo website 核心渲染，仓内无 @http.route）⇒ 命中 ALLOW_NO_ROUTE ----
        # 首页是真实存在的页面，理应能登记；没有这张例外表，「登记了却不存在」与
        # 「真实存在的上游路由」就分不开了（反例 ② 是同一条判据的负对照：/ghost 必须报红）。
        root = case('allow_root', base_pages + [page('home', '/', gates=['english'])])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res['allow_root'] = check(root=root, quiet=False)
        shown = buf.getvalue()
        good.append(("ALLOW_NO_ROUTE 例外：表里有 '/' 而仓内无该 @http.route ⇒ 不报「登记已失效」",
                     res['allow_root']['rc'] == 0
                     and not any(n == '/' for n, _w in res['allow_root']['findings']['stale'])
                     and '/' in res['allow_root']['stat']['allow_no_route']))
        good.append(('例外命中要**可见**：输出里打出 ALLOW 行（不是静默放过），且措辞点名豁免的是哪条不变式',
                     'ALLOW' in shown and '表内条目无对应 @http.route' in shown))

        # ---- 正例 3：ALLOW_UNREGISTERED 例外只豁免不变式 1 ----
        root = case('allow', base_pages, extra_py=(
            'custom_addons/edu_legacy/controllers/main.py',
            'from odoo import http' + NL +
            "class L(http.Controller):" + NL +
            "    @http.route('/legacy/hook', type='http')" + NL +
            '    def l(self, **kw):' + NL +
            '        pass' + NL))
        ALLOW_UNREGISTERED['/legacy/hook'] = '夹具：内部兼容钩子，v1 暂不登记'
        try:
            res['allow'] = check(root=root, quiet=True)
        finally:
            ALLOW_UNREGISTERED.clear()
        good.append(('ALLOW_UNREGISTERED 例外 ⇒ 只打 ALLOW、不报「新路由未登记」',
                     res['allow']['rc'] == 0
                     and not res['allow']['findings']['unregistered']))

        # ---- 正例 3：三个脚本都改成形态 B ⇒ 不比对路由字面量 ----
        root = case('all_from_file', base_pages, rm_text=gate_en, with_surface=True)
        mk(root, GATES[1][1], gate_en)
        res['all_from_file'] = check(root=root, quiet=True)
        good.append(('三个脚本都改成从 surface.json 读 ⇒ 名单比对自动让位、不误报',
                     res['all_from_file']['rc'] == 0))

        for desc, cond in defect:
            print('  %s %s' % ('报红 ✓' if cond else '报红 ✗', desc))
        for desc, cond in good:
            print('  %s %s' % ('不报红 ✓' if cond else '不报红 ✗', desc))
        cls = set()
        for key in sorted(res):
            for k, _l in CATS:
                if res[key]['findings'][k]:
                    cls.add(k)
        n_red = len([1 for _d, c in defect if c])
        n_green = len([1 for _d, c in good if c])
        print('自证 %d/%d 报红 · %d/%d 不报红 · 违规类型 %d/%d 命中'
              % (n_red, len(defect), n_green, len(good), len(cls), len(CATS)))
        ok = (n_red == len(defect)) and (n_green == len(good))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('== 反例自检 %s ==' % ('通过' if ok else '未通过'))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true', help='临时目录造反例/正例，自证判据有效')
    ap.add_argument('--coverage', action='store_true', help='打印登记覆盖率（报告，不是门禁）')
    ap.add_argument('--root', default=REPO, help='仓库根（自检用；默认为脚本所在仓库）')
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.coverage:
        return coverage(root=args.root)
    return check(root=args.root)['rc']


if __name__ == '__main__':
    sys.exit(main())
