#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""静态门禁：docs/**.md 的 GFM 表格「行宽 = 表头格数」自洽（表头驱动）。

触发事件（2026-09-28）：为核对三处已知错列，写了一个**表头驱动**的格数校验器；它跑全仓
docs/**.md 报出「28 个文件 / 116 行异常」。但那个检测器**没被验证过**，而它当时每个裸竖线
都切格 —— 于是把本仓**大量合法的转义竖线**（`\|`）整片误判。先验检测器、再谈清扫，
结论是：误报 74/116，真畸形只有 42 行。本脚本落的就是**验过之后的判据**。

不变式（三条，逐条对应下面的实现；判据依据 = cmark-gfm 自带用例 test/extensions.txt「Tables」）：
  1. 表头行与分隔行必须同格 —— GFM 原话「The header and delimiter row must match」，
     不同格时**根本不成表**（整块退化成段落）。故不成表的不报、成表的先校验这一对；
  2. 正文每行格数 == 表头格数。两个方向的**后果不同**，故分开报：
     · 多格：GFM「Rows longer than the header are truncated」⇒ **多余格被丢弃，内容真丢**；
     · 少格：GFM「any of the body rows can be shorter」⇒ 渲染会**补空格**、不丢内容，
       但几乎总意味着内容被并进邻格或整行被硬换行截断（实物：A3 行、F5 行）⇒ 仍算畸形。
  3. 切分口径 = GFM：**反斜杠转义的竖线不切格**（含代码跨内 —— cmark-gfm 用例逐字证明
     「Within `\|code\| is okay` too」渲染成 <code>|code| is okay</code>）；
     围栏代码块内的「表样式」文本**不是表格**，不参与比对。

为什么必须修这两条（第一版检测器的实测误报，全部可复现）：
  · 不做转义感知 ⇒ 本仓 77 行合法表被报红（占它自报 116 行的 66%）；
  · 不做围栏感知 ⇒ 代码块里的伪表被报红。
反面（不许为了统计好看而放宽）：转义感知**只**取消转义位，不取消别的判据 ——
自检里专设 N6/N7 两条反例，证明「有 \| 就放过」和「围栏内跳过」都不会掩盖真畸形。

渲染级复核（真实解析器 markdown-it 实测，2026-09-28；判据与 cmark-gfm 用例一致）：
  · 表头 2 格 / 某行 4 格 ⇒ 渲染出的 <td> **只有 2 个** —— 多出来的格确实被丢弃（内容真丢）；
  · 表头 3 格 / 某行 1 格 ⇒ 渲染补 <td></td> —— **不丢内容**，但该行内容落在错列上；
  · @BT@x @BS@| y@BT@ **不切格**（渲染出 2 格，不是 3 格）。

规则 3 登记（KNOWN_UNFIXABLE）：只登记「按规则 1 拆格要编内容、按规则 2 改表头又会破坏同表其它
正确行」的行；键是**整行原文的指纹**，行一改就失效并打 WARN。它**不放宽判据**，自检里专门证明
「登记项命中时不报、同一行被改一个字符时照报」。

已知覆盖缺口（**不要凭本脚本下「无缺陷」的结论**）：
  「表行与表行之间夹了一行不以竖线开头的正文」这一形态**本脚本看不见** —— 它按 GFM 口径在那行
  结束表格，那行与它之后的表行都不再比对。实测 markdown-it 会把那行**吸收成表格的一行**
  （实物：docs/plans/ux-v3-delivery.md 第 19 行起的 M1–M10 表，中间夹了 2 行注解
  ⇒ 渲染出 2 行伪表行，注解文字落进「指标」列）；cmark-gfm 是否改成「在此断开表格」
  **未核实**（两种解释都算缺陷，但本脚本目前一条都不报）。

设计约束：零环境依赖（不连 DB / 不发 HTTP），**只读**，不改任何文档；
退出码 0=OK 1=FAIL 2=ENV 3=INCOMPLETE；自证行打印 REVISION · 指纹 · 断言数 · 时刻。

用法：
    python3 scripts/check_md_tables.py                 # 扫 docs/**.md（门禁）
    python3 scripts/check_md_tables.py --selftest      # 正反样本自证（临时目录，不碰真仓库）
    python3 scripts/check_md_tables.py --list          # 逐条列出（默认只列前 40 条）
    python3 scripts/check_md_tables.py --file docs/code-map.md   # 只查一份（排查用）

⚠ 覆盖边界（本脚本**不能**证明的）：围栏未闭合且其后真有内容 ⇒ 记 INCOMPLETE(3)，
**不当 OK**；围栏开在最后一行（其后无内容）⇒ 只记 WARN（覆盖损失为 0）。
"""
import argparse, hashlib, io, os, re, shutil, sys, tempfile
from datetime import datetime

REVISION = 'v1.0'
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DOCS_REL = 'docs'
TICK = chr(96)          # 反引号（写成 chr(96) 免得被别处的转义吃掉）
BSLASH = chr(92)
FENCE = TICK * 3

# ── 按「规则 3」登记的已知不可改行（**例外不是免检**）──────────────────────────
# 键 = 表格行原文（strip 后）的 md5 前 12 位；值 = (仓库相对路径, 为什么规则 1/2 两条路都走不通)。
# 只在「路径 + 整行**逐字**相同」时豁免：该行一旦被改动、移动或删除，登记项立刻失效并打 WARN，
# 逼着重新审一次。**判据本身不放宽** —— 这里只登记那些「按规则 1 拆格要编内容、按规则 2 改表头
# 又会破坏同表其它正确行」的行；能用规则 1/2 改的，一行都不许进来。
KNOWN_UNFIXABLE = {
    'b412321d581b': ('docs/audit/portal-color-token-map-t4.md',
             '表头 + 分隔行 + 3 条姊妹行一致为 4 格 ⇒ 异常方是**这一行**而不是表头 ⇒ 规则 2 不适用'
             '（改表头会一次性破坏那 3 条正确行）；该行是「角色限定」叙事例外行，全文只点出 '
             '--warning（面）与 --warning-ink（字），**通道列根本没有值** ⇒ 按规则 1 拆成 3 格必然要'
             '填空列、或把 ⚠ 那段现场例证硬塞进「通道（供 rgba(var(--x-rgb), α) 用）」列 = 编造结构。'
             '渲染后果有界：2 格行只是被补 2 个空格，不丢内容、不影响同表其它行。'),
}

# 分隔行的一格：:--- / --- / :---:（至少 2 个连字符，本仓口径）
SEP_CELL_RE = re.compile(r'^:?-{2,}:?$')
# 围栏行：3 个及以上的反引号或波浪号（GFM 两种围栏都认；长度要记住，闭合方必须 >= 开方，否则短围栏会被误当闭合）
FENCE_RE = re.compile(r'^(' + TICK + r'{3,}|~{3,})(.*)$')
# 整行是否为一行分隔行（仅用「与表头同格」比较时用作形态判定）


def row_key(text):
    """表格行原文（strip 后）的指纹：登记项按**内容**匹配，行一改（含移位）就失效。"""
    return hashlib.md5((text or '').strip().encode('utf-8')).hexdigest()[:12]


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


def split_row(line):
    r"""GFM 表格行 → 单元格列表。

    \| **不切格**（含代码跨内）；其余裸竖线一律切格。首尾若为空段则视为定界符去掉。
    这是本脚本与第一版检测器的唯一实质差别，也是 66% 误报的来源。
    """
    s = line.rstrip(BSLASH + 'r' + BSLASH + 'n')
    parts, cur, i = [], '', 0
    while i < len(s):
        if s[i] == BSLASH and i + 1 < len(s) and s[i + 1] == '|':
            cur += '|'
            i += 2
            continue
        if s[i] == '|':
            parts.append(cur)
            cur = ''
            i += 1
            continue
        cur += s[i]
        i += 1
    parts.append(cur)
    if parts and parts[0].strip() == '':
        parts = parts[1:]
    if parts and parts[-1].strip() == '':
        parts = parts[:-1]
    return parts


def is_sep_row(cells):
    """整行都是分隔格（|:--|--:|），且至少一格。"""
    return len(cells) > 0 and all(SEP_CELL_RE.match(c.strip()) for c in cells)


def scan(text):
    """跑一份文档。

    返回 (findings, stats)：
      findings = [{'row','got','expect','kind'}]；kind = 'row'(正文行) | 'sep'(分隔行)
      stats    = {'tables','rows','fence_open','fence_tail','lines'}
    'fence_open'：文件结束时**还开着的围栏的起始行号**，且其后还有内容（⇒ 覆盖损失，记 INCOMPLETE）
    'fence_tail'：围栏开在最后一行（其后 0 行，覆盖损失为 0 ⇒ 只 WARN）
    """
    lines = text.split('\n')
    findings, stats = [], {'tables': 0, 'rows': 0, 'fence_open': 0, 'fence_tail': 0, 'lines': len(lines)}
    stack = []          # 当前开着的围栏栈：(字符, 长度, 行号)
    n = 0
    while n < len(lines):
        raw = lines[n]
        st = raw.strip()
        m = FENCE_RE.match(st)
        if m:
            ch, ln, body = m.group(1)[0], len(m.group(1)), m.group(2)
            if stack and stack[-1][0] == ch and ln >= stack[-1][1]:
                stack.pop()
            elif not stack:
                stack.append((ch, ln, n + 1))
            else:
                # 围栏内又出现别的围栏：忽略（GFM 里内层围栏要更长的同类字符才算，见上分支）
                pass
            n += 1
            continue
        if stack:
            n += 1
            continue
        if not st.startswith('|'):
            n += 1
            continue
        if n + 1 >= len(lines) or not lines[n + 1].strip().startswith('|'):
            n += 1
            continue
        sep = split_row(lines[n + 1])
        if not is_sep_row(sep):
            n += 1
            continue
        expect = len(split_row(lines[n]))
        stats['tables'] += 1
        if len(sep) != expect:
            findings.append({'row': n + 2, 'got': len(sep), 'expect': expect, 'kind': 'sep',
                             'text': lines[n + 1].strip()})
        n += 2
        while n < len(lines) and lines[n].strip().startswith('|'):
            got = len(split_row(lines[n]))
            stats['rows'] += 1
            if got != expect:
                findings.append({'row': n + 1, 'got': got, 'expect': expect, 'kind': 'row',
                                 'text': lines[n].strip()})
            n += 1
    if stack:
        if stack[0][2] >= len(lines):
            stats['fence_tail'] = stack[0][2]
        elif len(lines) - stack[0][2] > 1:
            stats['fence_open'] = stack[0][2]
        else:
            stats['fence_tail'] = stack[0][2]
    return findings, stats


def iter_docs(root=REPO):
    docs = os.path.join(root, DOCS_REL)
    out = []
    for dirpath, dirnames, filenames in os.walk(docs):
        dirnames.sort()
        for fn in sorted(filenames):
            if fn.endswith('.md'):
                out.append(os.path.join(dirpath, fn))
    return out


def check(root=REPO, quiet=False, list_all=False):
    docs = os.path.join(root, DOCS_REL)
    if not os.path.isdir(docs):
        print('ENV：目录不存在 %s' % docs)
        return {'rc': 2, 'findings': {}, 'n_assert': 0}
    files = iter_docs(root)
    F = {}
    allowed, used_keys = [], set()
    unreadable, fence_warn, n_tables, n_rows, n_assert = [], [], 0, 0, 0
    for p in files:
        rel = os.path.relpath(p, root)
        text = read_text(p)
        n_assert += 1
        if text is None:
            unreadable.append(rel)
            continue
        findings, stats = scan(text)
        n_tables += stats['tables']
        n_rows += stats['rows']
        if stats['fence_open']:
            F.setdefault('fence', []).append((rel, stats['fence_open']))
        if stats['fence_tail']:
            fence_warn.append((rel, stats['fence_tail']))
        for f in findings:
            k = row_key(f.get('text'))
            ent = KNOWN_UNFIXABLE.get(k)
            if ent and ent[0] == rel:
                allowed.append((rel, f, ent[1]))
                used_keys.add(k)
                continue
            F.setdefault(rel, []).append(f)
    n_bad = sum(len(v) for v in F.values())
    n_bad_files = len(F)
    n_over = sum(1 for v in F.values() for f in v if f['got'] > f['expect'])
    n_under = n_bad - n_over
    rc = 0
    if F.get('fence'):
        rc = 3
    elif F:
        rc = 1
    if not quiet:
        print('== docs/**.md 表格行宽（表头驱动 · GFM 切分 · 围栏感知）==')
        print('扫描文档 %d 份｜表格 %d 张｜正文行 %d 条｜未变格 %d 行'
              % (len(files), n_tables, n_rows, n_rows - n_bad))
        print('畸形行 %d 条（多格 %d / 少格 %d）｜涉及文件 %d 份｜规则 3 登记豁免 %d 条'
              % (n_bad, n_over, n_under, n_bad_files, len(allowed)))
        shown = 0
        for rel in sorted(F):
            for f in F[rel]:
                if f['kind'] == 'sep':
                    print('  FAIL %s:%d 表头 %d 格 / 分隔行 %d 格（GFM 要求两者相同，否则不成表）'
                          % (rel, f['row'], f['expect'], f['got']))
                elif f['got'] > f['expect']:
                    print('  FAIL %s:%d 表头 %d 格 / 本行 %d 格（多 %d 格 ⇒ 渲染会截断，内容真丢）'
                          % (rel, f['row'], f['expect'], f['got'], f['got'] - f['expect']))
                else:
                    print('  FAIL %s:%d 表头 %d 格 / 本行 %d 格（少 %d 格 ⇒ 渲染补空，多为内容并格或被硬换行截断）'
                          % (rel, f['row'], f['expect'], f['got'], f['expect'] - f['got']))
                shown += 1
                if not list_all and shown >= 40:
                    print('  …（只列前 40 条，-—list 全列）')
                    break
            if not list_all and shown >= 40:
                break
        for rel, f, why in sorted(allowed):
            print('  ALLOW %s:%d 表头 %d 格 / 本行 %d 格 —— 按规则 3 登记（只报不动，判据未放宽）：%s'
                  % (rel, f['row'], f['expect'], f['got'], why))
        for k in sorted(set(KNOWN_UNFIXABLE) - used_keys):
            print('  WARN 登记项已失效（那一行已被改动/移动/删除），请重新审：%s（%s）'
                  % (k, KNOWN_UNFIXABLE[k][0]))
        for rel, ln in F.get('fence', []):
            print('  INCOMPLETE %s：第 %d 行开着的围栏到文末仍未闭合 ⇒ 其后内容被整段跳过、未参与比对' % (rel, ln))
        for rel, ln in fence_warn:
            print('  WARN %s：第 %d 行的围栏未闭合（它在最后一行之后无内容，本次覆盖损失为 0）' % (rel, ln))
        for rel in unreadable:
            print('  INCOMPLETE 文档读不到：%s' % rel)
        print('结论：%s' % {0: 'OK', 1: 'FAIL', 2: 'ENV', 3: 'INCOMPLETE'}[rc])
        print('自证：REVISION=%s · 指纹 %s · 断言 %d 条 · 时刻 %s'
              % (REVISION, self_fingerprint(), n_assert + n_rows,
                 datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        print('契约：exit 0=OK 1=FAIL 2=ENV(docs 不存在) 3=INCOMPLETE(文档读不到 / 围栏未闭合导致漏检)')
    return {'rc': rc, 'findings': F, 'n_assert': n_assert + n_rows,
            'n_bad': n_bad, 'n_over': n_over, 'n_under': n_under, 'files': files}


def selftest():
    """正反样本自证：临时目录造样本，**绝不碰真仓库**。

    正例 8 个（正常表 / 转义竖线 / 围栏里的伪表 / 两行表头 / 代码跨内转义 / HTML / 缩进表 /
    围栏闭合后紧接真表），反例 7 个（多格 / 少格 / 代码跨裸竖线 / 纯文本裸竖线 / 五格行 /
    既有转义又真多一格 / 围栏外同一行真超格）。
    **专设两条「不许一转义就放过」的反例**（N6/N7）—— 放宽判据换绿是本仓明令禁止的，
    这两条就是那条红线的自检。
    """
    ok = True
    n_red = n_green = 0

    def chk(name, cond, extra=''):
        nonlocal ok
        print('  %-4s %s %s' % ('PASS' if cond else 'FAIL', name, extra))
        ok = ok and bool(cond)

    Q = TICK
    B = BSLASH
    F = FENCE
    NL = chr(10)

    def detect(lines):
        return scan(NL.join(lines) + NL)[0]

    POS = [
        ('普通 3 列表', ['| 项 | 状态 | 依据 |', '|---|---|---|', '| A | 已上线 | f5988d6 |', '| B | 在研 | 实测 |']),
        ('含转义竖线的表（GFM 合法）',
         ['| 命令 | 说明 |', '|---|---|',
          '| ' + Q + 'grep -n "a' + B + '|b"' + Q + ' | 转义竖线不切格 |', '| x ' + B + '| y | 同上 |']),
        ('围栏代码块里的「表样式」文本',
         ['说明：', F + 'text', '| 伪表头 | 少 | 格 |', '|---|---|', '| 只有 | 两格 |', F]),
        ('两行表头（首行渲染为段落，不误报）',
         ['| 指标 | 本期 | 上期 |', '| (单位) | 人次 | 人次 |', '|---|---|---|', '| 到课率 | 98 | 97 |']),
        ('代码跨内用转义竖线',
         ['| 表达式 | 含义 |', '|---|---|', '| ' + Q + 'a ' + B + '| b' + Q + ' | 位或 |']),
        ('单元格含 HTML',
         ['| 页面 | 说明 |', '|---|---|', '| /x | <span class="b">新</span><br>只读 |']),
        ('列表缩进的表',
         ['- 表：', '', '  | A | B |', '  |---|---|', '  | 1 | 2 |']),
        ('围栏闭合后紧接的真表（防围栏状态没归零）',
         [F + 'bash', 'ps aux | grep odoo | head', F, '| A | B |', '|---|---|', '| 1 | 2 |']),
    ]
    NEG = [
        ('多一格（渲染截断）',
         ['| 项 | 状态 | 依据 |', '|---|---|---|', '| A | 已上线 | f5988d6 |', '| B | 在研 | 实测 | 多的一格 |']),
        ('少一格（渲染补空）',
         ['| 项 | 状态 | 依据 |', '|---|---|---|', '| A | 已上线 | f5988d6 |', '| B | 在研 |']),
        ('代码跨里的裸竖线（本仓真实缺陷形态）',
         ['| 想要 | 找法 | 结果 |', '|---|---|---|',
          '| 整块粘贴 | 全仓 ' + Q + 'grep -rn -iE "paste|clipboard"' + Q + ' | 没有 |']),
        ('纯文本里的裸竖线',
         ['| 能力 | 命中 | 结论 |', '|---|---|---|',
          '| 冻结 | 实测 ' + Q + 'sticky|freeze' + Q + ' 命中 0 | 无 |']),
        ('五格行 / 四格表头',
         ['| A | B | C | D |', '|---|---|---|---|', '| 1 | 2 | 3 | 4 |', '| 1 | 2 | 3 | 4 | 5 |']),
        ('N6 既有转义竖线、又真多一格（不许一转义就放过）',
         ['| A | B | C |', '|---|---|---|', '| x ' + B + '| y | z | 1 | 2 |']),
        ('N7 围栏内是代码，围栏外同一处真超格（不许围栏内跳过掩盖外面）',
         [F, '| 代码 | 里的 | 假表 |', '|---|---|', '| 只有 | 两格 |', F,
          '| A | B |', '|---|---|', '| 1 | 2 | 3 |']),
    ]
    tmp = tempfile.mkdtemp(prefix='cmt_selftest_')
    try:
        for name, lines in POS:
            hits = detect(lines)
            n_green += 1
            chk('正例·不该报红：%s' % name, not hits, ('← 却报了 %s' % hits) if hits else '')
        for name, lines in NEG:
            hits = detect(lines)
            n_red += 1
            chk('反例·必须报红：%s' % name, bool(hits), '' if hits else '← 漏报！')
        # 分隔行与表头不同格 ⇒ GFM 说根本不成表，本脚本单独报一类
        hits = detect(['| a | b | c |', '| --- | --- |', '| x | y | z |'])
        n_red += 1
        chk('分隔行与表头不同格 ⇒ 报「不成表」一类', bool(hits) and hits[0]['kind'] == 'sep',
            '← got %s' % hits)
        # 同一条真畸形放在围栏内 ⇒ 不算表（正例），放在围栏外 ⇒ 必须报（反例）—— 防「跳过=放过」
        inside = [F, '| a | b |', '|---|---|', '| 1 | 2 | 3 |', F]
        outside = [F, 'x', F] + ['| a | b |', '|---|---|', '| 1 | 2 | 3 |']
        n_green += 1
        chk('围栏内的超格行不报（是代码，不是表）', not detect(inside))
        n_red += 1
        chk('围栏外的同一条超格行照报', bool(detect(outside)))
        # 围栏未闭合：其后有内容 ⇒ INCOMPLETE 口径（stats.fence_open）；在后面内容为空 ⇒ 只 WARN
        _, s1 = scan(NL.join([F, '| a | b |', '|---|---|', '| 1 | 2 | 3 |']) + NL)
        _, s2 = scan(NL.join(['x', F]) + NL)
        chk('围栏未闭合且其后有内容 ⇒ fence_open（记 INCOMPLETE）', bool(s1['fence_open']))
        chk('围栏开在最后一行 ⇒ 只 fence_tail（WARN）', bool(s2['fence_tail']) and not s2['fence_open'])
        # ── 规则 3 登记豁免机制自证：只豁免「路径 + 整行逐字相同」的那一行 ────────────
        # 这条专治「拿白名单把门禁刷绿」：登记项必须**窄**——同一行被改一个字符就不再豁免。
        d = os.path.join(tmp, 'docs')
        os.makedirs(d, exist_ok=True)
        reg = os.path.join(d, 'reg.md')
        io.open(reg, 'w', encoding='utf-8').write(NL.join(
            ['| a | b |', '|---|---|', '| 1 | 2 | 3 |']) + NL)
        k = row_key('| 1 | 2 | 3 |')
        KNOWN_UNFIXABLE[k] = ('docs/reg.md', '自检用的登记项（不是真仓库条目）')
        try:
            r1 = check(root=tmp, quiet=True)
            n_green += 1
            chk('登记项命中 ⇒ 该行不再算畸形（rc=0）', r1['rc'] == 0 and r1['n_bad'] == 0,
                'rc=%s n_bad=%s' % (r1['rc'], r1['n_bad']))
            io.open(reg, 'w', encoding='utf-8').write(NL.join(
                ['| a | b |', '|---|---|', '| 1 | 2 | 3 | 4 |']) + NL)
            r2 = check(root=tmp, quiet=True)
            n_red += 1
            chk('同一行被改一个字符 ⇒ 登记项失效、照报红（rc=1）', r2['rc'] == 1 and r2['n_bad'] == 1,
                'rc=%s n_bad=%s' % (r2['rc'], r2['n_bad']))
        finally:
            del KNOWN_UNFIXABLE[k]
        # 指纹/读文件不炸
        chk('自证指纹可算出', len(self_fingerprint()) == 8)
        print('自证 %d/%d 报红 · %d/%d 不报红' % (n_red, len(NEG) + 3, n_green, len(POS) + 2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('== 反例自检 %s ==' % ('通过' if ok else '未通过'))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true', help='正反样本自证（不碰真仓库）')
    ap.add_argument('--file', default='', help='只查一份文档（仓库相对路径或绝对路径）')
    ap.add_argument('--list', action='store_true', help='逐条列全部畸形行（默认只列前 40 条）')
    ap.add_argument('--root', default=REPO, help='仓库根（自检用；默认为脚本所在仓库）')
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.file:
        p = args.file if os.path.isabs(args.file) else os.path.join(args.root, args.file)
        text = read_text(p)
        if text is None:
            print('INCOMPLETE 文档读不到：%s' % p)
            return 3
        findings, stats = scan(text)
        rel = os.path.relpath(p, args.root)
        findings = [f for f in findings if not (
            KNOWN_UNFIXABLE.get(row_key(f.get('text')), ('',))[0] == rel)]
        print('== %s ==' % args.file)
        print('表格 %d 张｜正文行 %d 条｜畸形 %d 条' % (stats['tables'], stats['rows'], len(findings)))
        for f in findings:
            print('  FAIL 第 %d 行：表头 %d 格 / 本行 %d 格（%s）'
                  % (f['row'], f['expect'], f['got'], '多格 ⇒ 渲染截断' if f['got'] > f['expect'] else '少格 ⇒ 渲染补空'))
        return 1 if findings else 0
    return check(root=args.root, list_all=args.list)['rc']


if __name__ == '__main__':
    sys.exit(main())
