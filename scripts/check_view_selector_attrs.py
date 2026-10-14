#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视图继承选择器门禁：拦住「用翻译属性当选择器」的 <xpath expr> / 继承节点。

## 为什么立它（2026-10-14 真实升级失败，非推演）

    bash scripts/safe_upgrade.sh edu_schedule edu_portal
    odoo.tools.convert.ParseError: while parsing None:2115
    解析或验证视图时出错：View inheritance may not use attribute 'aria-label' as a selector.
    View error context: {'file': '/mnt/custom-addons/edu_portal/views/roles.xml',
                         'name': 'Edu Timetable Availability Entry',
                         'view': ir.ui.view(3837,),
                         'xmlid': 'edu_timetable_availability_btn'}

事故当时那一行（现已修复，但仍要挡住下一次）：

    <xpath expr="//div[@aria-label='周导航']" position="after">

`aria-label` 是**翻译属性**：值随语言/翻译库变化，装载期无法把它稳定映射到 arch
节点，core 因此直接拒绝整个视图 —— 一次升级整批回滚。

## 真源（照抄，不猜）

- `/usr/lib/python3/dist-packages/odoo/addons/base/models/ir_ui_view.py`
  - `:405-424` `_valid_inheritance()`
  - `:135` `TRANSLATED_ATTRS_RE`
  - `:412` `<xpath>` 的 `expr` 命中翻译属性 ⇒ 抛错（本次事故就是这条）
  - `:417-423` **非 `<xpath>`** 的继承节点自身带翻译属性 ⇒ 同样抛错（第二分支）
  - `:136` `WRONGCLASS`（`@class` 当选择器）只是 **warning**（建议 `hasclass()`），
    本门禁只提示、**不算 FAIL**
- `/usr/lib/python3/dist-packages/odoo/tools/translate.py:75` `TRANSLATED_ATTRS`
  - 基名：aria-label, aria-placeholder, aria-valuetext, aria-roledescription,
    aria-keyshortcuts, title, string, help, alt, placeholder, label, data-tooltip,
    confirm, confirm-label, confirm-title, cancel-label, add-label, value_label,
    avg, sum
  - `:81` 另生成 `t-attf-<attr>` 变体 ⇒ 也属翻译属性

## 可复算的复现命令（在部署机 / WSL 上跑；本机 macOS 无 odoo 源码）

    # 1) 打印 core 实际认下的翻译属性全集（本门禁常量的真源）
    python3 - <<'PY'
    import odoo.tools.translate as t
    print(sorted(t.TRANSLATED_ATTRS))
    PY
    # 2) 直接读源：常量定义处 + t-attf 变体生成处 + 判据处
    sed -n '70,90p'           /usr/lib/python3/dist-packages/odoo/tools/translate.py
    sed -n '130,140p;405,424p' /usr/lib/python3/dist-packages/odoo/addons/base/models/ir_ui_view.py

## 判据口径（运行时也打一行）

- 扫描 `custom_addons/*/views/**`（含 `views/*.xml` 与子目录）；
- `<xpath ... position="...">`：从 `expr` 里抽 `@属性名`，命中 `TRANSLATED_ATTRS`
  （含 `t-attf-` 变体）⇒ FAIL 一条，输出 `文件:行号 + expr + 属性名`；
- 非 `<xpath>` 但带 `position=` 的继承节点：节点**自身**属性命中 ⇒ FAIL 一条；
- `@t-att-<base>`（非 t-attf）是**动态属性**，一律不判 FAIL：`t-att-` 形式不在
  translate.py 的集合里（集合只额外含 `t-attf-` 变体），实测 `@t-att-href` 不误报；
- 合法：`@name/@id/@role/@type/@href/@t-if/hasclass(...)/@data-*`（非 data-tooltip）；
- `@class` 作选择器 ⇒ 仅 WARN（对齐 core `WRONGCLASS`，不计 FAIL）。

用法：
    python3 scripts/check_view_selector_attrs.py [--root custom_addons]
    python3 scripts/check_view_selector_attrs.py --selftest
契约：exit 0=OK 1=FAIL 2=ENV（扫描根不存在 / 扫不到视图 xml）
"""
import hashlib
import io
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

REVISION = 'r1'

ROOT_DEFAULT = 'custom_addons'
CST = timezone(timedelta(hours=8))

# ── 翻译属性全集 ── 真源：odoo/tools/translate.py:75 TRANSLATED_ATTRS
#    （t-attf-<attr> 前缀变体由同文件 :81 生成，必须一并剥成基名比对）
TRANSLATED_ATTRS_BASE = (
    'aria-label', 'aria-placeholder', 'aria-valuetext', 'aria-roledescription',
    'aria-keyshortcuts', 'title', 'string', 'help', 'alt', 'placeholder',
    'label', 'data-tooltip', 'confirm', 'confirm-label', 'confirm-title',
    'cancel-label', 'add-label', 'value_label', 'avg', 'sum',
)
TRANSLATED_ATTRS = frozenset(TRANSLATED_ATTRS_BASE) | frozenset(
    't-attf-' + a for a in TRANSLATED_ATTRS_BASE)

TRANSLATED_ATTRS_RE_SRC = ':135 TRANSLATED_ATTRS_RE'

# 逐个元素 token：注释 / CDATA 整块吃掉；其余抓「标签名 + 属性串 + 是否自闭合」
TOKEN_RE = re.compile(
    r"<!--.*?-->|<!\[CDATA\[.*?\]\]>"
    r"|<([A-Za-z_][\w:.\-]*)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*?)(/?)>",
    re.S)
ATTR_RE = re.compile(r"""([A-Za-z_][\w:.\-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
# expr 里的属性选择器：只认 @name，不认裸词（hasclass() 因此天然免疫）
XPF_ATTR_RE = re.compile(r'@([A-Za-z_][A-Za-z0-9_.\-]*)')

CORE_ERR_XPATH = 'ir_ui_view.py:412（<xpath> expr 命中 TRANSLATED_ATTRS_RE）'
CORE_ERR_NODE = 'ir_ui_view.py:417-423（非 xpath 继承节点自身带翻译属性）'
CORE_WARN_CLASS = 'ir_ui_view.py:136 WRONGCLASS（@class 作选择器 → 建议 hasclass()，仅 warning）'


def _self_fingerprint():
    """本文件内容指纹（md5 前 8 位）——量具自证，人工改门禁必须可见。"""
    try:
        with io.open(__file__, 'rb') as fh:
            return hashlib.md5(fh.read()).hexdigest()[:8]
    except Exception:
        return 'XXXXXXXX'


def parse_attrs(s):
    out = {}
    for m in ATTR_RE.finditer(s or ''):
        out[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    return out


def scan_text(text, view):
    """扫一段视图文本 → (findings, warnings)。纯函数，selftest 直接喂字符串。"""
    findings, warnings = [], []
    for m in TOKEN_RE.finditer(text):
        tag = m.group(1)
        if tag is None:                      # 注释 / CDATA
            continue
        attrs = parse_attrs(m.group(2))
        if 'position' not in attrs:          # 只审继承指令
            continue
        line = text.count('\n', 0, m.start()) + 1
        if tag == 'xpath':
            expr = attrs.get('expr', '')
            bad = []
            for hit in XPF_ATTR_RE.finditer(expr):
                tok = hit.group(1)
                if tok in TRANSLATED_ATTRS:
                    if tok not in bad:
                        bad.append(tok)
                elif tok == 'class':
                    warnings.append({'view': view, 'line': line, 'tag': tag,
                                     'reason': CORE_WARN_CLASS, 'expr': expr})
            if bad:
                findings.append({'kind': 'xpath', 'view': view, 'line': line,
                                 'tag': tag, 'attrs': bad, 'expr': expr,
                                 'reason': CORE_ERR_XPATH})
        else:
            bad = [k for k in attrs if k != 'position' and k in TRANSLATED_ATTRS]
            if bad:
                findings.append({'kind': 'node', 'view': view, 'line': line,
                                 'tag': tag, 'attrs': sorted(bad),
                                 'expr': None, 'reason': CORE_ERR_NODE})
    return findings, warnings


def collect_view_files(root, allow_fallback=True):
    """优先 `*/views/**`（含嵌套）；一个都没有时（--root 指到扁平夹具目录）退化为全 xml。"""
    hits = []
    for dp, dns, fns in os.walk(root):
        dns.sort()
        if 'views' in os.path.relpath(dp, root).split(os.sep):
            hits += [os.path.join(dp, fn) for fn in sorted(fns) if fn.endswith('.xml')]
    if hits:
        return sorted(hits), '*/views/**/*.xml'
    if not allow_fallback:
        return [], '*/views/**/*.xml'
    hits = []
    for dp, dns, fns in os.walk(root):
        dns.sort()
        hits += [os.path.join(dp, fn) for fn in sorted(fns) if fn.endswith('.xml')]
    return sorted(hits), '**/*.xml（回退：没找到 views 目录）'


def evaluate(root):
    """(rc, files, findings, warnings)；rc 2=ENV（根不存在 / 无视图 xml）。"""
    if not os.path.isdir(root):
        return 2, [], [], [], 'root-missing'
    files, pat = collect_view_files(root)
    if not files:
        return 2, [], [], [], pat
    findings, warnings = [], []
    for p in files:
        try:
            raw = io.open(p, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        f, w = scan_text(raw, p)
        findings += f
        warnings += w
    return (1 if findings else 0), files, findings, warnings, pat


def _stamp():
    return datetime.now(CST).strftime('%Y-%m-%dT%H:%M:%S%z')


def _verdict_line(label, n_fail, n_assert):
    return ('RESULT=%s REVISION=%s · 指纹 %s · 断言 %d 条 · 运行 %s'
            % (label, REVISION, _self_fingerprint(), n_assert, _stamp()))


# ── selftest：正反两向都断言（反例含 2026-10-14 事故原文）──
SELFTEST_SAMPLES = [
    # (名称, 期望 FAIL 条数, 期望 WARN 条数, 视图文本)
    ('事故原文@aria-label', 1, 0,
     '<odoo><template id="t" inherit_id="m.p">'
     '<xpath expr="//div[@aria-label=\'周导航\']" position="after"/>'
     '</template></odoo>'),
    ('@t-attf-title 变体', 1, 0,
     '<odoo><template id="t" inherit_id="m.p">'
     '<xpath expr="//span[@t-attf-title=\'x\']" position="before"/>'
     '</template></odoo>'),
    ('@title 明文选择器', 1, 0,
     '<odoo><template id="t" inherit_id="m.p">'
     '<xpath expr="//div[@title=\'x\']" position="after"/>'
     '</template></odoo>'),
    ('@data-tooltip 选择器', 1, 0,
     '<odoo><template id="t" inherit_id="m.p">'
     '<xpath expr="//div[@data-tooltip=\'x\']" position="after"/>'
     '</template></odoo>'),
    ('非xpath节点带title', 1, 0,
     '<odoo><template id="t" inherit_id="m.p">'
     '<div title="x" position="after"/>'
     '</template></odoo>'),
    ('非xpath节点带t-attf-string', 1, 0,
     '<odoo><template id="t" inherit_id="m.p">'
     '<span t-attf-string="x" position="after"/>'
     '</template></odoo>'),
    ('@t-att-href 不误报', 0, 0,
     '<odoo><template id="t" inherit_id="m.p">'
     '<xpath expr="//a[@t-att-href=\'x\']" position="after"/>'
     '</template></odoo>'),
    ('合法选择器全家桶', 0, 0,
     '<odoo><template id="t" inherit_id="m.p">'
     '<xpath expr="//div[@id=\'a\'][@role=\'b\'][hasclass(\'c\')]'
     '[@type=\'d\']//a[@href=\'/x\'][@t-if=\'y\'][@data-bs-toggle=\'z\']"'
     ' position="inside"/>'
     '</template></odoo>'),
    ('@class 只 WARN', 0, 1,
     '<odoo><template id="t" inherit_id="m.p">'
     '<xpath expr="//div[contains(@class,\'a\')]" position="inside"/>'
     '</template></odoo>'),
]
EXITCODE_SAMPLES = 3


def selftest():
    """① 内联样本的命中数断言；② 退出码契约（1=FAIL / 0=OK / 2=ENV）断言。"""
    ok = True
    for name, want_f, want_w, text in SELFTEST_SAMPLES:
        findings, warnings = scan_text(text, name)
        good = (len(findings) == want_f and len(warnings) == want_w)
        ok = ok and good
        print('SELFTEST %-7s %-26s 期望 FAIL=%d WARN=%d 实得 FAIL=%d WARN=%d'
              % ('ok' if good else 'MISMATCH', name, want_f, want_w,
                 len(findings), len(warnings)))

    tmp = tempfile.mkdtemp(prefix='gate_selftest_')
    try:
        bad_dir = os.path.join(tmp, 'bad')
        os.makedirs(os.path.join(bad_dir, 'mod', 'views'))
        io.open(os.path.join(bad_dir, 'mod', 'views', 'v.xml'), 'w',
                encoding='utf-8').write(SELFTEST_SAMPLES[0][3])
        good_dir = os.path.join(tmp, 'good')
        os.makedirs(os.path.join(good_dir, 'mod', 'views'))
        io.open(os.path.join(good_dir, 'mod', 'views', 'v.xml'), 'w',
                encoding='utf-8').write(SELFTEST_SAMPLES[7][3])
        rc_bad = evaluate(bad_dir)[0]
        rc_good = evaluate(good_dir)[0]
        rc_missing = evaluate(os.path.join(tmp, 'nope'))[0]
        codes_ok = (rc_bad == 1 and rc_good == 0 and rc_missing == 2)
        ok = ok and codes_ok
        print('SELFTEST %-7s 退出码契约：bad=%d(期望1) good=%d(期望0) missing=%d(期望2)'
              % ('ok' if codes_ok else 'MISMATCH', rc_bad, rc_good, rc_missing))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    n = len(SELFTEST_SAMPLES)
    if ok:
        print('SELFTEST PASS：%d 个样本 + 退出码契约样本' % n)
    else:
        print('SELFTEST FAIL：%d 个样本里存在不符（拒绝判绿）' % n)
    print(_verdict_line('OK（失败项 0）' if ok else 'FAIL（失败项 1）',
                        0 if ok else 1, n + EXITCODE_SAMPLES))
    return 0 if ok else 1


def main(argv):
    root = ROOT_DEFAULT
    args = argv[1:]
    if '--root' in args:
        i = args.index('--root')
        if i + 1 >= len(args):
            print('SKIP-ENV：--root 缺参数')
            print(_verdict_line('ENV（环境未就绪 ≠ 检查通过）', 0, 0))
            return 2
        root = args[i + 1]
    elif args and not args[0].startswith('--'):
        root = args[0]

    if '--selftest' in args:
        return selftest()

    rc, files, findings, warnings, pat = evaluate(root)
    print('==' * 32)
    print('视图继承选择器门禁（翻译属性作选择器）  REVISION=%s  扫描根=%s  口径=%s'
          % (REVISION, root, pat))
    print('口径：只看带 position= 的继承节点；xpath 取 expr 里的 @属性名并比对'
          ' translate.py:75 的 TRANSLATED_ATTRS（含 t-attf- 变体）；'
          '@t-att-*（非 t-attf）属动态属性不判 FAIL；@class 仅 WARN。')
    print('-' * 64)
    if rc == 2:
        print('SKIP-ENV：%s'
              % ('扫描根不存在：%s' % root if not os.path.isdir(root)
                 else '扫描根下找不到视图 xml：%s' % root))
        print(_verdict_line('ENV（环境未就绪 ≠ 检查通过）', 0, 0))
        return 2

    print('已扫描视图 xml %d 个 ｜ FAIL %d 条 ｜ WARN %d 条'
          % (len(files), len(findings), len(warnings)))
    for w in warnings:
        print('WARN  | %s:%d | expr=%s | %s' % (w['view'], w['line'], w['expr'], w['reason']))
    for f in findings:
        if f['kind'] == 'xpath':
            print('FAIL  | %s:%d | expr=%s | 属性=%s'
                  % (f['view'], f['line'], f['expr'], ','.join(f['attrs'])))
        else:
            print('FAIL  | %s:%d | <%s ... position=%s> | 属性=%s'
                  % (f['view'], f['line'], f['tag'], '...', ','.join(f['attrs'])))
        print('        原因：%s' % f['reason'])
    print('-' * 64)
    print('契约：exit 0=OK 1=FAIL 2=ENV（%s）' % TRANSLATED_ATTRS_RE_SRC)
    print(_verdict_line('FAIL（失败项 %d）' % len(findings) if findings else 'OK（失败项 0）',
                        len(findings), len(files)))
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
