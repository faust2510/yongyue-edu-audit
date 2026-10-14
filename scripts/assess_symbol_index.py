#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""行号索引：custom_addons/edu_assess/models/assess.py 的「符号 → 现行行号」。

为什么有这个脚本（2026-09-30）：
    上一轮实测：docs/plans/eval-unified-design.md 里 38 处 assess.py:NNN 引用，
    **29 处已失效** —— 该文件从 507 行长到 1517 行，行号只反映**写引用那一刻**。
    同病扩散在 5 份文档 + 2 处代码/脚本注释里。

    队长的判断（本脚本服务的规矩）：**行号不是可维护的引用形式**。
    ⇒ 文档与注释只引「文件 + **符号名**」；行号只允许出现在**显式标注了取证时刻**的取证块里。
    ⇒ 本脚本是这条规矩的**复核工具**：拿符号名问「现在在第几行」。
      读文档的人不必信文档里的数字，当场跑一条命令就能对账。

用法：
    python3 scripts/assess_symbol_index.py                 # 全量索引（人类可读）
    python3 scripts/assess_symbol_index.py --grep cell     # 单查（子串匹配，大小写不敏感）
    python3 scripts/assess_symbol_index.py --kind field    # 只看某一类
    python3 scripts/assess_symbol_index.py --file <py>     # 换一份文件排查（结构性自证降级）
    python3 scripts/assess_symbol_index.py --selftest      # 正反样本自证（临时目录，不碰真仓库）

契约：exit 0=OK 1=FAIL 2=ENV（目标文件不存在）。
    · 解析出 0 个符号 ⇒ **FAIL(1)**，不许静默成功；
    · 内置自证不过（符号数不足 / 模型类缺失 / 抽查 3+ 个已知符号与 grep -n 不一致）⇒ FAIL(1)；
    · --grep 查不到任何符号 ⇒ FAIL(1)（「你引的符号不存在」必须响亮，不能看起来像跑通了）。

自证（每次正常跑都执行，--selftest 只额外证明反例会红）：
    1. 符号总数 >= MIN_SYMBOLS，且 class/method/field/constraint/const 五类都非空；
    2. REQUIRED_CLASSES 六个模型类必须都在；
    3. SPOT_CHECKS 的每个符号，用独立工具（grep -n）实测行号，与 AST 索引逐条比对；
       grep 模式命中行数 != 1 视为**量具歧义**（同样 FAIL，不放行）。

覆盖边界（**不要**拿本脚本下「符号齐全」的结论）：
    · AST 语法级索引 ⇒ 只看得见**写出来的**定义。动态生成（循环里 create 字段）、
      运行期从别的模块 _inherit 进来的字段、以及 Selection 的取值本身，都不在覆盖内；
    · 行号 = class / def / 赋值语句的**首行**，不含装饰器行、不含多行调用的第 2 行起；
    · 它不是「引用有效性」检查器：符号名写对了但它是不是**语义上对的那个符号**，本脚本答不了
      （已知陷阱见 docs/plans/eval-unified-design.md 的「第 2 期已落地的两处语义变更」）。
"""
import argparse
import ast
import hashlib
import os
import subprocess
import sys
import tempfile

REVISION = 'r1'

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TARGET_REL = 'custom_addons/edu_assess/models/assess.py'

EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2

#: 符号总数下限。实测 r1 = 208；放在 120 留出「合理的删减空间」，
#: 但任何「解析器被改坏 ⇒ 只认出十几个」的事故都会被这一条当场抓住。
MIN_SYMBOLS = 120

#: 六个模型类（含一处 res.users 扩展）—— 缺一个就说明解析器漏了整段。
REQUIRED_CLASSES = (
    'EduAssessTemplate', 'EduAssessItem', 'EduAssessTask',
    'EduAssessRoster', 'EduAssessScore', 'ResUsers',
)

#: 抽查清单：(限定名, grep -n 的模式)。模式必须**恰好命中 1 行**，否则算量具歧义。
#: 覆盖四种不同形态：类 / 字段赋值 / 方法 / 模块级常量 —— 解析器任一条路径坏了都会露。
SPOT_CHECKS = (
    ('EduAssessRoster', r'^class EduAssessRoster\('),
    ('EduAssessTemplate.pass_line', r'^    pass_line = fields\.Float\('),
    ('EduAssessRoster._item_cell', r'^    def _item_cell\(self, item\):'),
    ('SALT_PARAM', r'^SALT_PARAM = '),
)

#: 类属性里不算「字段」的元数据名（列出来是为了让它们仍能被索引到，类别标 meta）。
_META_ATTRS = ('_name', '_inherit', '_description', '_order', '_rec_name',
               '_check_company_auto')


class Sym(object):
    """一条索引记录。line = 定义首行（1-based）。"""

    __slots__ = ('line', 'kind', 'qualname', 'hint')

    def __init__(self, line, kind, qualname, hint=''):
        self.line = line
        self.kind = kind
        self.qualname = qualname
        self.hint = hint

    def __repr__(self):  # pragma: no cover - 仅供排查
        return 'Sym(%d, %s, %s)' % (self.line, self.kind, self.qualname)


def _unparse(node):
    try:
        return ast.unparse(node)
    except Exception:
        return ''


def _sig(fn):
    """(self, item) 这样的签名（失败返回空串，不编造）。"""
    try:
        return '(' + _unparse(fn.args).strip() + ')'
    except Exception:
        return ''


def _call_attr_name(value):
    """fields.Float(...) → ('fields', 'Float')；不是属性调用则 (None, None)。"""
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
        inner = value.func.value
        if isinstance(inner, ast.Name):
            return inner.id, value.func.attr
    return None, None


def _field_type(value):
    owner, attr = _call_attr_name(value)
    if owner == 'fields':
        return 'fields.%s' % attr
    return ''


def _constraint_names(node):
    """从 _sql_constraints = [...] 或 models.Constraint(...) 里取约束名（取不到就给占位）。"""
    names = []
    value = getattr(node, 'value', None)
    if isinstance(value, (ast.List, ast.Tuple)):
        for elt in value.elts:
            if isinstance(elt, (ast.Tuple, ast.List)) and elt.elts:
                first = elt.elts[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    names.append(first.value)
                    continue
            names.append('(匿名)')
    elif value is not None:
        owner, attr = _call_attr_name(value)
        if attr == 'Constraint':
            # models.Constraint('UNIQUE(...)', '名字') —— 第 2 个位置参数是约束名
            args = list(value.args)
            if len(args) > 1 and isinstance(args[1], ast.Constant) \
                    and isinstance(args[1].value, str):
                names.append(args[1].value)
            else:
                names.append('(匿名)')
    return names


def _target_name(node):
    """Assign / AnnAssign 的目标名（只认最简单的单个 Name）。"""
    if isinstance(node, ast.AnnAssign):
        return node.target.id if isinstance(node.target, ast.Name) else None
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        tgt = node.targets[0]
        if isinstance(tgt, ast.Name):
            return tgt.id
    return None


def _value_assign(node):
    if isinstance(node, ast.AnnAssign):
        return node.value
    if isinstance(node, ast.Assign):
        return node.value
    return None


def _class_members(cls):
    """类体里的方法 / 字段 / 约束 / 元数据。"""
    out = []
    for child in cls.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(Sym(child.lineno, 'method',
                           '%s.%s' % (cls.name, child.name), _sig(child)))
            continue
        if not isinstance(child, (ast.Assign, ast.AnnAssign)):
            continue
        name = _target_name(child)
        if not name:
            continue
        value = _value_assign(child)
        if name == '_sql_constraints':
            for cname in _constraint_names(child) or ['(匿名)']:
                out.append(Sym(child.lineno, 'constraint',
                               '%s._sql_constraints[%s]' % (cls.name, cname), ''))
            continue
        if name in _META_ATTRS:
            lit = value.value if isinstance(value, ast.Constant) else _unparse(value)
            out.append(Sym(child.lineno, 'meta',
                           '%s.%s' % (cls.name, name), str(lit)))
            continue
        if name.startswith('_') and isinstance(value, ast.Call) \
                and _call_attr_name(value)[1] == 'Constraint':
            out.append(Sym(child.lineno, 'constraint',
                           '%s.%s' % (cls.name, name), _unparse(value)[:60]))
            continue
        ftype = _field_type(value)
        if ftype:
            out.append(Sym(child.lineno, 'field',
                           '%s.%s' % (cls.name, name), ftype))
    return out


def parse_symbols(source, path_label='<source>'):
    """返回 [Sym]，按行号排序。source 必须能 ast.parse，否则抛 SyntaxError。"""
    tree = ast.parse(source, filename=path_label)
    out = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out.append(Sym(node.lineno, 'class', node.name,
                           ', '.join(b.id for b in node.bases
                                     if isinstance(b, ast.Name)) or '—'))
            out.extend(_class_members(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(Sym(node.lineno, 'func', node.name, _sig(node)))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            name = _target_name(node)
            if name:
                out.append(Sym(node.lineno, 'const', name,
                               _unparse(_value_assign(node))[:48]))
    out.sort(key=lambda s: (s.line, s.qualname))
    return out


# ------------------------------------------------------------------ 自证

def grep_line_number(path, pattern):
    """独立量具：用系统 grep -n 数这个模式命中的行。

    返回 (命中行号列表, 错误消息)。刻意**不复用** AST 路径 —— 自证的价值就在于两边
    是独立实现；同一个函数算两遍等于没算。
    """
    try:
        proc = subprocess.run(['grep', '-nE', pattern, path],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        return [], 'grep 不可用：%s' % exc
    if proc.returncode not in (0, 1):
        return [], 'grep 退出码 %d：%s' % (proc.returncode,
                                          proc.stderr.decode('utf-8', 'replace').strip())
    lines = []
    for raw in proc.stdout.decode('utf-8', 'replace').splitlines():
        head = raw.split(':', 1)[0]
        if head.isdigit():
            lines.append(int(head))
    return lines, ''


def self_check(symbols, path, canonical=True):
    """返回 (ok, 明细行列表)。canonical=False 时只查「非空」。"""
    detail, ok = [], True

    if not symbols:
        return False, ['FAIL 自证：解析出 **0 个符号** —— 解析器被改坏或文件为空，'
                       '不许静默成功（契约 exit 1）']

    counts = {}
    for s in symbols:
        counts[s.kind] = counts.get(s.kind, 0) + 1
    by_name = {}
    for s in symbols:
        by_name.setdefault(s.qualname, s)

    if not canonical:
        detail.append('SKIP 结构性自证：--file 指向非规范文件（%s），'
                      '只断言「符号数 > 0」；assess.py 的抽查清单不套用。' % path)
        return ok, detail

    if len(symbols) < MIN_SYMBOLS:
        ok = False
        detail.append('FAIL 自证：符号总数 %d < 下限 %d（解析器可能只认出了半张文件）'
                      % (len(symbols), MIN_SYMBOLS))
    else:
        detail.append('OK   自证：符号总数 %d >= 下限 %d' % (len(symbols), MIN_SYMBOLS))

    for kind in ('class', 'method', 'field', 'constraint', 'const'):
        if not counts.get(kind):
            ok = False
            detail.append('FAIL 自证：类别 %s 一个符号都没解析出来（该路径坏了）' % kind)
        else:
            detail.append('OK   自证：类别 %-10s %3d 个' % (kind, counts[kind]))

    missing = [c for c in REQUIRED_CLASSES if c not in by_name]
    if missing:
        ok = False
        detail.append('FAIL 自证：模型类缺失 %s' % ', '.join(missing))
    else:
        detail.append('OK   自证：六个模型类齐（%s）' % ', '.join(REQUIRED_CLASSES))

    for qualname, pattern in SPOT_CHECKS:
        sym = by_name.get(qualname)
        if sym is None:
            ok = False
            detail.append('FAIL 抽查：索引里没有 %s（符号被改名或删掉了）' % qualname)
            continue
        found, err = grep_line_number(path, pattern)
        if err:
            # 量具不可用 ⇒ 不计为通过，也不谎称失败原因在索引上
            ok = False
            detail.append('FAIL 抽查：%s 的独立量具不可用（%s）' % (qualname, err))
            continue
        if len(found) != 1:
            ok = False
            detail.append('FAIL 抽查：%s 的 grep 模式命中 %d 行（应为 1）⇒ 量具歧义'
                          '，先修模式再谈一致：%s' % (qualname, len(found), pattern))
            continue
        if found[0] != sym.line:
            ok = False
            detail.append('FAIL 抽查：%s 索引说第 %d 行，grep -n 实测第 %d 行'
                          % (qualname, sym.line, found[0]))
        else:
            detail.append('OK   抽查：%-30s 第 %4d 行（AST 索引 == grep -n 实测）'
                          % (qualname, sym.line))
    return ok, detail


# ------------------------------------------------------------------ 输出

def file_facts(path):
    with open(path, 'rb') as fh:
        data = fh.read()
    lines = data.count(b'\n') + (0 if data.endswith(b'\n') else 1)
    return {
        'bytes': len(data),
        'lines': lines,
        'sha256': hashlib.sha256(data).hexdigest()[:12],
    }


def print_index(symbols, facts, rel, grep=None, kind=None):
    rows = symbols
    if grep:
        needle = grep.lower()
        rows = [s for s in rows if needle in s.qualname.lower()]
    if kind:
        rows = [s for s in rows if s.kind == kind]

    print('=' * 78)
    print('assess.py 符号索引（符号 → 现行行号）  REVISION=%s' % REVISION)
    print('文件 = %s' % rel)
    print('       %d 行 / %d 字节 / sha256:%s'
          % (facts['lines'], facts['bytes'], facts['sha256']))
    print('=' * 78)
    print('！行号是**此刻**的快照，会随文件增长而腐烂。')
    print('  引用方式：文档/注释写「文件 + 符号名」，别写行号；')
    print('  行号只允许出现在**显式标注了取证时刻**的取证块里。')
    if grep:
        print('-- 过滤：--grep %r%s' % (grep, (' --kind %s' % kind) if kind else ''))
    elif kind:
        print('-- 过滤：--kind %s' % kind)
    print('-' * 78)

    if not rows:
        print('NO-MATCH：一条符号都没匹配上 —— 你引的符号名可能不存在（契约 exit 1）。')
        print('  排查：去掉过滤器看全量；或 grep -n "<片段>" %s' % rel)
        return False

    wname = max(len(s.qualname) for s in rows)
    wname = max(wname, 8)
    print('%s  %6s  %-10s %s' % ('符号'.ljust(wname), '行号', '类别', '备注'))
    for s in rows:
        print('%s  %6d  %-10s %s' % (s.qualname.ljust(wname), s.line, s.kind, s.hint))
    print('-' * 78)
    print('共 %d 条（全量 %d 条）' % (len(rows), len(symbols)))
    return True


# ------------------------------------------------------------------ selftest

_FIXTURE = '''# -*- coding: utf-8 -*-
"""夹具：刻意覆盖每一种类别 + 一个多行字段。"""
import os

SALT_PARAM = 'x.salt'
LIMIT = 3


def helper(env, a, b=1):
    return a


class Alpha(models.Model):
    _name = 'x.alpha'
    _description = '甲'

    name = fields.Char(string='名')
    weight = fields.Float(
        string='权重', default=1.0)

    _uniq = models.Constraint('UNIQUE(name)', '名称唯一')

    @api.constrains('name')
    def _check_name(self):
        pass

    def _compute_weight(self):
        pass


class Beta(models.Model):
    _inherit = 'res.users'

    _sql_constraints = [
        ('x_beta_uniq', 'UNIQUE(a)', '唯一'),
    ]
    flag = fields.Boolean()
'''

#: 夹具的真实期望：(限定名, 行号, 类别)。行号逐条数过，不是 copy 输出。
_FIXTURE_EXPECT = (
    ('SALT_PARAM', 5, 'const'),
    ('LIMIT', 6, 'const'),
    ('helper', 9, 'func'),
    ('Alpha', 13, 'class'),
    ('Alpha._name', 14, 'meta'),
    ('Alpha._description', 15, 'meta'),
    ('Alpha.name', 17, 'field'),
    # 多行调用：行号取**语句首行**（18），不是第 2 行
    ('Alpha.weight', 18, 'field'),
    ('Alpha._uniq', 21, 'constraint'),
    ('Alpha._check_name', 24, 'method'),
    ('Alpha._compute_weight', 27, 'method'),
    ('Beta', 31, 'class'),
    ('Beta._inherit', 32, 'meta'),
    ('Beta._sql_constraints[x_beta_uniq]', 34, 'constraint'),
    ('Beta.flag', 37, 'field'),
)


def _run(args):
    """跑一次真 CLI（子进程）—— 自证必须走用户走的同一条路。"""
    proc = subprocess.run([sys.executable, os.path.abspath(__file__)] + args,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout.decode('utf-8', 'replace') + \
        proc.stderr.decode('utf-8', 'replace')


def selftest():
    """正反两向都要有断言：解析正确 + **反例必须红**。"""
    cases = []
    tmp = tempfile.mkdtemp(prefix='asi_selftest_')

    def case(name, ok, note):
        cases.append((name, ok, note))

    # ---- 正例 1：夹具逐条比对（限定名 / 行号 / 类别）--------------------------------
    fixture = os.path.join(tmp, 'fixture.py')
    with open(fixture, 'w', encoding='utf-8') as fh:
        fh.write(_FIXTURE)
    with open(fixture, encoding='utf-8') as fh:
        syms = parse_symbols(fh.read(), fixture)
    got = {s.qualname: (s.line, s.kind) for s in syms}
    bad = []
    for qualname, line, kind in _FIXTURE_EXPECT:
        actual = got.get(qualname)
        if actual != (line, kind):
            bad.append('%s 期望 (%d, %s) 实际 %s' % (qualname, line, kind, actual))
    case('P1 夹具逐条解析（%d 条）' % len(_FIXTURE_EXPECT), not bad,
         '全部一致' if not bad else '；'.join(bad))

    # ---- 正例 2：符号总数与 --file 全量输出 ---------------------------------------
    case('P2 夹具符号总数 = %d' % len(_FIXTURE_EXPECT),
         len(syms) == len(_FIXTURE_EXPECT),
         '实际 %d 条（多出来的是解析器把不该算的算进去了）' % len(syms))

    rc, out = _run(['--file', fixture])
    case('P3 --file 夹具 exit 0 且打印符号表',
         rc == EXIT_OK and 'Alpha.weight' in out and 'SKIP 结构性自证' in out,
         'exit=%d；SKIP 标注=%s' % (rc, 'SKIP 结构性自证' in out))

    # ---- 反例 1：空文件 0 符号 ⇒ 必须非零 ----------------------------------------
    empty = os.path.join(tmp, 'empty.py')
    open(empty, 'w').close()
    rc, out = _run(['--file', empty])
    case('N1 空文件 0 符号 exit != 0', rc != EXIT_OK,
         'exit=%d；0 个符号的提示=%s' % (rc, '0 个符号' in out))

    # ---- 反例 2：全注释文件 0 符号 ⇒ 必须非零 ------------------------------------
    comments = os.path.join(tmp, 'comments.py')
    with open(comments, 'w', encoding='utf-8') as fh:
        fh.write('# 只有注释\n# 再来一行\n')
    rc, out = _run(['--file', comments])
    case('N2 全注释 0 符号 exit != 0', rc != EXIT_OK, 'exit=%d' % rc)

    # ---- 反例 3：文件不存在 ⇒ 非零（ENV=2）-----------------------------------------
    rc, out = _run(['--file', os.path.join(tmp, 'nope.py')])
    case('N3 文件不存在 exit = 2（ENV）', rc == EXIT_ENV,
         'exit=%d；SKIP-ENV 提示=%s' % (rc, 'SKIP-ENV' in out))

    # ---- 反例 4：语法坏掉 ⇒ 非零，不许当空索引混过去 --------------------------------
    broken = os.path.join(tmp, 'broken.py')
    with open(broken, 'w', encoding='utf-8') as fh:
        fh.write('class A(models.Model)\n    x = 1\n')
    rc, out = _run(['--file', broken])
    case('N4 语法错误 exit != 0 且提示原因', rc != EXIT_OK and 'SyntaxError' in out,
         'exit=%d；含 SyntaxError=%s' % (rc, 'SyntaxError' in out))

    # ---- 反例 5：--grep 查不到 ⇒ 非零（引了不存在的符号必须响亮）--------------------
    rc, out = _run(['--file', fixture, '--grep', 'NoSuchSymbolXyz'])
    case('N5 --grep 无命中 exit != 0', rc != EXIT_OK and 'NO-MATCH' in out,
         'exit=%d；NO-MATCH=%s' % (rc, 'NO-MATCH' in out))

    # ---- 正例 4：--grep 命中 ⇒ 0 且只有匹配项 --------------------------------------
    rc, out = _run(['--file', fixture, '--grep', 'weight'])
    case('P4 --grep weight 命中且 exit 0',
         rc == EXIT_OK and 'Alpha.weight' in out and 'Alpha.name' not in out,
         'exit=%d' % rc)

    # ---- 反例 6：抽查量具歧义必须报红（同一个模式命中 2 行就不放行）------------------
    ambig = os.path.join(tmp, 'ambig.py')
    with open(ambig, 'w', encoding='utf-8') as fh:
        fh.write('SALT_PARAM = 1\nSALT_PARAM = 2\n')
    with open(ambig, encoding='utf-8') as fh:
        syms2 = parse_symbols(fh.read(), ambig)
    ok2, detail2 = self_check(syms2, ambig, canonical=True)
    case('N6 抽查模式命中 2 行 ⇒ 自证报红',
         (not ok2) and any('量具歧义' in d for d in detail2), '')

    # ---- 反例 7：符号数不足 ⇒ 自证报红 --------------------------------------------
    tiny = os.path.join(tmp, 'tiny.py')
    with open(tiny, 'w', encoding='utf-8') as fh:
        fh.write('A = 1\n')
    with open(tiny, encoding='utf-8') as fh:
        syms3 = parse_symbols(fh.read(), tiny)
    ok3, detail3 = self_check(syms3, tiny, canonical=True)
    case('N7 符号数 < 下限 ⇒ 自证报红',
         (not ok3) and any('符号总数' in d for d in detail3), '')

    print('== assess_symbol_index --selftest ==')
    failed = 0
    for name, ok, note in cases:
        if not ok:
            failed += 1
        print('SELFTEST %-4s %-44s %s' % ('ok' if ok else 'FAIL', name, note))
    print('SELFTEST 总结：%s（REVISION=%s · 断言 %d 条 · 夹具目录 %s）'
          % ('全部通过' if not failed else '存在失败 %d 条' % failed,
             REVISION, len(cases), tmp))
    return EXIT_OK if not failed else EXIT_FAIL


# ------------------------------------------------------------------ main

def main(argv):
    ap = argparse.ArgumentParser(
        description='assess.py 符号 → 现行行号 索引（文档引用的复核工具）')
    ap.add_argument('--file', default=None,
                    help='换一份 .py（默认 %s，相对仓库根解析）' % TARGET_REL)
    ap.add_argument('--grep', default=None, help='按符号名子串过滤（大小写不敏感）')
    ap.add_argument('--kind', default=None,
                    choices=('class', 'method', 'field', 'constraint',
                             'meta', 'const', 'func'),
                    help='只列某一类')
    ap.add_argument('--selftest', action='store_true',
                    help='正反样本自证（临时目录，不碰真仓库）')
    args = ap.parse_args(argv[1:])

    if args.selftest:
        return selftest()

    if args.file:
        path = args.file if os.path.isabs(args.file) \
            else os.path.join(REPO, args.file)
        canonical = False
    else:
        path = os.path.join(REPO, TARGET_REL)
        canonical = True

    if not os.path.isfile(path):
        print('SKIP-ENV | 目标文件不存在：%s' % path)
        print('RESULT=ENV（环境未就绪 ≠ 索引为空） REVISION=%s' % REVISION)
        print('契约：exit 0=OK 1=FAIL 2=ENV')
        return EXIT_ENV

    rel = os.path.relpath(path, REPO)
    try:
        with open(path, encoding='utf-8') as fh:
            source = fh.read()
        symbols = parse_symbols(source, rel)
    except SyntaxError as exc:
        print('FAIL | 目标文件无法解析（SyntaxError: %s）' % exc)
        print('RESULT=FAIL REVISION=%s' % REVISION)
        return EXIT_FAIL

    facts = file_facts(path)
    ok_check, detail = self_check(symbols, path, canonical=canonical)
    listed = print_index(symbols, facts, rel, grep=args.grep, kind=args.kind)

    print()
    print('-- 自证 --')
    for line in detail:
        print('   ' + line)

    if not ok_check:
        print('RESULT=FAIL（自证不过） REVISION=%s' % REVISION)
        print('契约：exit 0=OK 1=FAIL 2=ENV')
        return EXIT_FAIL
    if not listed:
        print('RESULT=FAIL（--grep/--kind 无命中） REVISION=%s' % REVISION)
        print('契约：exit 0=OK 1=FAIL 2=ENV')
        return EXIT_FAIL
    print('RESULT=OK REVISION=%s' % REVISION)
    print('契约：exit 0=OK 1=FAIL 2=ENV')
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main(sys.argv))
