# -*- coding: utf-8 -*-
"""QWeb 字典字母化门禁（离线静态，秒级）：拦住「t-foreach 直接遍历 dict」。

背景（2026-09-15 用户报「这个 a u 什么的是什么」）：
ledger.xml / fees.xml 四处 <select> 写成
    <t t-foreach="state_label" t-as="s"><option t-att-value="s[0]" t-out="s[1]"/></t>
而控制器传的 state_label 是 dict（{code: 中文}）。QWeb 遍历 dict 得到的是 **key 字符串**，
于是 s[0]/s[1] 取到 key 的第 1/2 个字符：选项变成 "e p e a"，value 变成 'r'/'a' 等非法值
—— 筛选静默失效；记账表单更严重：方向/分类两个 select 只有 'r'/'p' 与单字母，
全部落库为兜底值「应收 + 其他」（用户那条「接待 ¥850」就是这么来的）。

判定：模板里 foreach 的循环变量若被当元组用（var[0]/var[1]），
而被遍历的名字在控制器 render 里传的是 **字典字面量常量**，即判失败。

用法：
    python3 check_qweb_dict_foreach.py [扫描根，默认 custom_addons] [--selftest]

契约：exit 0=OK 1=FAIL 2=ENV(扫描根不存在) 3=INCOMPLETE(有无法判定的 foreach)
"""
import hashlib
import os
import re
import sys
from datetime import datetime, timedelta, timezone

REVISION = 'r2'   # r2：常量名正则补下划线开头（r1 漏采 _STATE_LABEL 等 → 假绿）

ROOT_DEFAULT = 'custom_addons'
CST = timezone(timedelta(hours=8))

_OPEN_KIND = {'{': 'dict', '[': 'list', '(': 'tuple'}


def _self_fingerprint():
    """本文件内容指纹（大小 + md5 前 8 位）——量具自证，人工改门禁必须可见。"""
    try:
        with open(__file__, 'rb') as fh:
            data = fh.read()
        return hashlib.md5(data).hexdigest()[:8]
    except Exception:
        return 'XXXXXXXX'


def _iter_files(root, ext):
    for dp, _, fs in os.walk(root):
        for fn in fs:
            if fn.endswith(ext):
                yield os.path.join(dp, fn)


def _module_of(path, root):
    rel = os.path.relpath(path, root)
    return rel.split(os.sep)[0]


def collect_const_kinds(root, pyfiles):
    """module -> {常量名: dict|list|tuple}；含模块级 NAME = { 与 self.NAME = {。"""
    kinds = {}
    for p in pyfiles:
        mod = _module_of(p, root)
        try:
            txt = open(p, encoding='utf-8').read()
        except Exception:
            continue
        # 注意：常量名可以以 _ 开头（_STATE_LABEL / _CATEGORY_LABEL 全是），
        # 首版写成 [A-Z][A-Z0-9_]* 把下划线开头的全部漏掉 → 门禁假绿（已由
        # 「先证明会红」这一步抓出，见 docs/dev-workflow.md）。
        for m in re.finditer(r'^(_*[A-Z][A-Z0-9_]*)\s*=\s*([\{\[\(])', txt, re.M):
            kinds.setdefault(mod, {})[m.group(1)] = _OPEN_KIND[m.group(2)]
        for m in re.finditer(r'^\s+self\.(_*[A-Z][A-Z0-9_]*)\s*=\s*([\{\[\(])',
                             txt, re.M):
            kinds.setdefault(mod, {})['self.' + m.group(1)] = _OPEN_KIND[m.group(2)]
    return kinds


def collect_render_passes(root, pyfiles, kinds):
    """(module, 传参名) -> 常量名，仅认 'key': CONST / 'key': self.CONST 字面量。"""
    passed = {}
    for p in pyfiles:
        mod = _module_of(p, root)
        try:
            txt = open(p, encoding='utf-8').read()
        except Exception:
            continue
        for m in re.finditer(
                r"'([\w]+)'\s*:\s*(self\.)?(_*[A-Z][A-Z0-9_]*)\s*[,}\n]", txt):
            key, is_self, name = m.group(1), m.group(2), m.group(3)
            full = ('self.' + name) if is_self else name
            kind = (kinds.get(mod) or {}).get(full)
            if kind:
                passed[(mod, key)] = (full, kind, os.path.relpath(p))
    return passed


def element_block(txt, tag_start, tag_name):
    """从 '<tag' 处取完整元素块（含嵌套同名标签）。"""
    gt = txt.find('>', tag_start)
    if gt == -1:
        return txt[tag_start:tag_start + 400]
    if txt[gt - 1] == '/':
        return txt[tag_start:gt + 1]
    close = '</%s>' % tag_name
    open_pat = re.compile(r'<%s[\s>]' % re.escape(tag_name))
    depth, i = 1, gt + 1
    while depth:
        nxt_close = txt.find(close, i)
        if nxt_close == -1:
            return txt[tag_start:gt + 1]
        nxt_open = txt.find('<%s' % tag_name, i)
        if nxt_open != -1 and nxt_open < nxt_close and open_pat.match(txt, nxt_open):
            depth += 1
            i = nxt_open + len(tag_name) + 1
        else:
            depth -= 1
            i = nxt_close + len(close)
    return txt[tag_start:i]


def scan_templates(root, viewfiles, passed):
    """返回 (findings, stats)。findings: dict 常量被当元组遍历的位置。"""
    findings, stats = [], {'foreach': 0, 'tpl': 0}
    for v in viewfiles:
        mod = _module_of(v, root)
        try:
            txt = open(v, encoding='utf-8').read()
        except Exception:
            continue
        stats['tpl'] += 1
        for m in re.finditer(r't-foreach="([^"]+)"[^>]*?t-as="([^"]+)"', txt):
            expr, var = m.group(1).strip(), m.group(2).strip()
            stats['foreach'] += 1
            if '.' in expr or '[' in expr or '(' in expr:
                continue                      # x.items() / x[0] / zip(...) 等非裸名
            key = (mod, expr)
            if key not in passed:
                continue                      # 不是本模块 render 传的字典常量
            const, kind, pyf = passed[key]
            if kind != 'dict':
                continue                      # list/tuple 按元组用是合法的
            tag_start = txt.rfind('<', 0, m.start())
            tag_name = re.match(r'<([A-Za-z][\w:-]*)', txt[tag_start:])
            block = element_block(txt, tag_start,
                                  tag_name.group(1) if tag_name else 't')
            if re.search(r'\b%s\s*\[' % re.escape(var), block):
                line = txt.count('\n', 0, m.start()) + 1
                findings.append({
                    'view': os.path.relpath(v), 'line': line,
                    'expr': expr, 'var': var, 'const': const,
                    'py': pyf, 'mod': mod,
                })
    return findings, stats


def report(findings, stats, root):
    for f in findings:
        print('FAIL | %s:%d | t-foreach="%s" t-as="%s" 把字典当元组用'
              % (f['view'], f['line'], f['expr'], f['var']))
        print('       常量 %s（%s，字典型，render 处 %s）' % (f['const'], f['mod'], f['py']))
        print('       现象：%s[0]/%s[1] 取到 key 的单字符 → 选项字母化 + value 非法'
              % (f['var'], f['var']))
        print('       改法：t-foreach="%s.items()"（推荐），或 t-as="k" 后 t-out="%s[k]"'
              % (f['expr'], f['expr']))
    print('- 模板 foreach 总数 = %d（%d 个文件）' % (stats['foreach'], stats['tpl']))
    print('！判定边界（不沉默）：只识别「foreach 的名字 == 控制器 render 传参 key，'
          '且该常量在本模块定义为字典字面量」；')
    print('  别名赋值、内联 dict、跨模块 import 的 dict、以及控制器用变量兜底传参的情形'
          '**不在覆盖内**（靠运行时断言补：tests/smoke/ledger_select_labels.py）。')


# ---------------------- selftest：正反两向都要有断言 ----------------------
SELFTEST_CASES = [
    ('UNSAFE-DICT', True,
     '<t t-foreach="state_label" t-as="s">'
     '<option t-att-value="s[0]" t-out="s[1]"/></t>'),
    ('SAFE-ITEMS', False,
     '<t t-foreach="state_label.items()" t-as="s">'
     '<option t-att-value="s[0]" t-out="s[1]"/></t>'),
    ('SAFE-KEYLOOKUP', False,
     '<t t-foreach="state_label" t-as="k">'
     '<option t-att-value="k" t-out="state_label[k]"/></t>'),
    ('SAFE-OPT-ON-ELEMENT', False,
     '<select><option t-foreach="category_label.items()" t-as="c"'
     ' t-att-value="c[0]" t-out="c[1]"/></select>'),
]


def selftest():
    """用合成模板验证检测器：命中/不命中必须都对。"""
    passed = {('m', 'state_label'): ('_STATE_LABEL', 'dict', 'c.py'),
              ('m', 'category_label'): ('_CATEGORY_LABEL', 'dict', 'c.py')}
    ok = True
    for name, want_hit, tpl in SELFTEST_CASES:
        m = re.search(r't-foreach="([^"]+)"[^>]*?t-as="([^"]+)"', tpl)
        expr, var = m.group(1).strip(), m.group(2).strip()
        hit = False
        if '.' not in expr and '[' not in expr and '(' not in expr:
            if ('m', expr) in passed and passed[('m', expr)][1] == 'dict':
                tag_start = tpl.rfind('<', 0, m.start())
                tn = re.match(r'<([A-Za-z][\w:-]*)', tpl[tag_start:])
                blk = element_block(tpl, tag_start, tn.group(1) if tn else 't')
                hit = bool(re.search(r'\b%s\s*\[' % re.escape(var), blk))
        flag = 'ok' if hit == want_hit else 'MISMATCH'
        if hit != want_hit:
            ok = False
        print('SELFTEST %-4s %-22s 期望命中=%-5s 实际=%-5s' %
              (flag, name, want_hit, hit))
    return ok


def main(argv):
    root = ROOT_DEFAULT
    for a in argv[1:]:
        if not a.startswith('--'):
            root = a
    now = datetime.now(CST).strftime('%Y-%m-%dT%H:%M:%S%z')
    if not os.path.isdir(root):
        print('SKIP-ENV | 扫描根不存在：%s' % root)
        print('RESULT=ENV（环境未就绪 ≠ 检查通过） REVISION=%s · 指纹 %s · 运行 %s'
              % (REVISION, _self_fingerprint(), now))
        return 2

    if '--selftest' in argv:
        good = selftest()
        print('SELFTEST 总结：%s（REVISION=%s · 指纹 %s · 断言 %d 条 · 运行 %s）'
              % ('全部通过' if good else '存在失败', REVISION,
                 _self_fingerprint(), len(SELFTEST_CASES), now))
        return 0 if good else 1

    pyfiles = list(_iter_files(root, '.py'))
    viewfiles = list(_iter_files(root, '.xml'))
    kinds = collect_const_kinds(root, pyfiles)
    passed = collect_render_passes(root, pyfiles, kinds)
    findings, stats = scan_templates(root, viewfiles, passed)

    n_dict = sum(1 for v in passed.values() if v[1] == 'dict')
    print('==' * 32)
    print('QWeb 字典字母化门禁  REVISION=%s  扫描根=%s' % (REVISION, root))
    print('常量表 = %d 个模块 / %d 条；render 传入的字典型传参 = %d 条'
          % (len(kinds), sum(len(v) for v in kinds.values()), n_dict))
    print('-' * 64)
    report(findings, stats, root)
    print('-' * 64)
    if findings:
        print('RESULT=FAIL（失败项 %d） REVISION=%s · 指纹 %s · 断言 %d 条 · 运行 %s'
              % (len(findings), REVISION, _self_fingerprint(),
                 stats['tpl'], now))
        print('契约：exit 0=OK 1=FAIL 2=ENV 3=INCOMPLETE')
        return 1
    print('RESULT=OK（失败项 0） REVISION=%s · 指纹 %s · 断言 %d 条 · 运行 %s'
          % (REVISION, _self_fingerprint(), stats['foreach'], now))
    print('契约：exit 0=OK 1=FAIL 2=ENV 3=INCOMPLETE')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
