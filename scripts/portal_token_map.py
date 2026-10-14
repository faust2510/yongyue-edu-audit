#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t4 台账生成器：门户颜色字面值 -> 令牌 对照（可复现，机械提取）。

唯一令牌输入：scripts/color_tokens.json（由 t3 从唯一令牌源机械提取，§7.4 冻结口径）。
该文件未落地时回退到 custom_home.css 的 :root 表，并在台账里标 PROVISIONAL（不得作为验收结论）。

用法：
    python3 scripts/portal_token_map.py
    python3 scripts/portal_token_map.py --out docs/audit/portal-color-token-map-t4.md
"""
import re, os, sys, json, collections, datetime

def _find_root():
    env = os.environ.get('T4_REPO_ROOT')
    cands = [env] if env else []
    cands += [os.path.dirname(os.path.dirname(os.path.abspath(__file__))), os.getcwd()]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, 'custom_addons')):
            return c
    return os.getcwd()

ROOT = _find_root()
PORTAL_CSS = [
    'edu_portal/static/src/css/portal.css',
    'edu_portal/static/src/css/batch1.css',
    'edu_portal/static/src/css/batch3.css',
    'edu_portal/static/src/css/enterprise.css',
    'edu_portal/static/src/css/ux_rework.css',
    'edu_portal/static/src/css/ux_v3.css',
    'edu_portal/static/src/css/banner.css',
    'edu_portal/static/src/css/enroll.css',
]
EXPECTED_ALPHA = [0.04, 0.05, 0.08, 0.10, 0.12, 0.16, 0.18, 0.35, 0.40, 0.50]  # 定稿（color-arch 数据推导版）
MASK_ALPHA = [0.70, 0.85]  # 阴影/遮罩专用档，不进品牌阶梯
WHITE_BLACK = {'#ffffff', '#fff', '#000000', '#000'}
CLASSIFY = {'background': '遮罩/面', 'background-image': '遮罩/面', 'box-shadow': '阴影',
            'text-shadow': '阴影', 'border-color': '描边', 'border': '描边', 'outline': '描边',
            'color': '文字', 'fill': '文字'}
BT = chr(96)
def q(s):
    return BT + s + BT

def norm_hex(c):
    c = c.strip().lower()
    if re.fullmatch(r'#[0-9a-f]{3}', c):
        c = '#' + ''.join(ch * 2 for ch in c[1:])
    return c

def load_tokens():
    p = os.path.join(ROOT, 'scripts', 'color_tokens.json')
    if os.path.exists(p):
        raw = json.load(open(p))
        out = {}
        for k, v in (raw.get('tokens') or {}).items():
            val = v.get('value') if isinstance(v, dict) else v
            if isinstance(val, str) and re.fullmatch(r'#[0-9a-fA-F]{3,8}', val.strip()):
                out[k if k.startswith('--') else '--' + k] = norm_hex(val)
        if out:
            return out, 'scripts/color_tokens.json（t3 机械提取；spec §6.2 唯一机读输入）', False
    # 次选：t3 已落地的唯一令牌源 brand_tokens.scss（spec §6.2 指定的唯一机读输入）
    toks = os.path.join(ROOT, 'custom_addons/edu_brand/static/src/scss/brand_tokens.scss')
    if os.path.exists(toks):
        txt = open(toks).read()
        scss = dict(re.findall(r'\$([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;', txt))
        out = {}
        for name, val in re.findall(r'(--[a-z0-9-]+)\s*:\s*([^;]+);', txt):
            v = val.strip()
            m = re.fullmatch(r'#\{\s*\$([a-z0-9-]+)\s*\}', v)
            if m and m.group(1) in scss:
                out[name] = norm_hex(scss[m.group(1)])
            elif re.fullmatch(r'#[0-9a-fA-F]{3,8}', v):
                out[name] = norm_hex(v)
        for _ in range(4):
            for a, b in re.findall(r'(--[a-z0-9-]+)\s*:\s*var\((--[a-z0-9-]+)\)\s*;', txt):
                if a not in out and b in out:
                    out[a] = out[b]
        if out:
            return out, 'custom_addons/edu_brand/static/src/scss/brand_tokens.scss（唯一令牌源，spec §6.2）', False
    src = open(os.path.join(ROOT, 'custom_addons/edu_portal/static/src/css/custom_home.css')).readlines()[82:139]
    decls = {}
    for ln in src:
        for m in re.finditer(r'(--[a-z0-9-]+)\s*:\s*([^;]+);', ln):
            decls[m.group(1)] = m.group(2).strip()
    res = {}
    def resolve(n, seen=()):
        if n in res: return res[n]
        if n in seen or n not in decls: return None
        v = decls[n]
        mv = re.fullmatch(r'var\((--[a-z0-9-]+)\)', v)
        r = resolve(mv.group(1), seen + (n,)) if mv else (norm_hex(v) if re.fullmatch(r'#[0-9a-fA-F]{3,8}', v) else None)
        res[n] = r
        return r
    for n in decls: resolve(n)
    return {n: v for n, v in res.items() if v}, 'custom_addons/edu_portal/static/src/css/custom_home.css:83-139（:root，临时回退）', True

def scan():
    hexes, rgba = [], []
    for rel in PORTAL_CSS:
        p = os.path.join(ROOT, 'custom_addons', rel)
        for i, line in enumerate(open(p), 1):
            for m in re.finditer(r'#[0-9a-fA-F]{3,8}\b', line):
                props = re.findall(r'[-a-z]+\s*:', line[:m.start()])
                hexes.append((rel, i, norm_hex(m.group(0)), props[-1].strip(' :') if props else '?'))
            for m in re.finditer(r'rgba?\(\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)\s*(?:,\s*([0-9.]+)\s*)?\)', line):
                props = re.findall(r'[-a-z]+\s*:\s*', line[:m.start()])
                rgba.append((rel, i, '%s,%s,%s' % (m.group(1), m.group(2), m.group(3)),
                             float(m.group(4)) if m.group(4) else None,
                             props[-1].strip(' :') if props else '?'))
    return hexes, rgba

def walk_selectors(f):
    """逐行 yield (行号, 行文本, 该行生效的选择器)。支持多行选择器与 @media 嵌套。"""
    buf = []
    stack = []
    for i, raw in enumerate(open(f), 1):
        line = raw.rstrip('\n')
        if '{' in line:
            sel = (''.join(buf) + line.split('{')[0]).strip()
            sel_line = sel or (stack[-1] if stack else None)
        else:
            sel_line = stack[-1] if stack else None
        yield i, line, sel_line
        if '{' in line:
            head, rest = line.split('{', 1)
            head = (''.join(buf) + head).strip()
            buf = []
            if head.startswith('@') or not head:
                stack.append(stack[-1] if stack else None)
            else:
                stack.append(head)
            for ch in rest:
                if ch == '{':
                    stack.append(stack[-1] if stack else None)
                elif ch == '}':
                    if stack:
                        stack.pop()
        else:
            s = line.strip()
            if s.endswith('}') or s.endswith(';'):
                buf = []
            elif s and not s.startswith('/*'):
                buf.append(line)

def color_of(lit):
    lit = lit.strip()
    if lit.startswith('#'):
        return norm_hex(lit)
    g = re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', lit)
    if g:
        return '#' + ''.join('%02x' % int(g.group(k)) for k in (1, 2, 3))
    return None

def pm(a):
    """alpha -> 千分位整数（禁止浮点比较：0.35-0.30 == 0.04999999999999999 < 0.05）"""
    return int(round(a * 1000))

def tier(a):
    ai = pm(a)
    return min(EXPECTED_ALPHA, key=lambda x: (abs(pm(x) - ai), pm(x)))

def rgb_of(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]

def main():
    tokens, src_label, provisional = load_tokens()
    by_val = collections.defaultdict(list)
    for n, v in tokens.items():
        by_val[v].append(n)
    hexes, rgba = scan()
    all_cnt = collections.Counter(h for _, _, h, _ in hexes)
    for _, _, base, _, _ in rgba:
        all_cnt['#' + ''.join('%02x' % int(x) for x in base.split(','))] += 1
    L = []
    A = L.append
    A('# t4 台账：门户颜色字面值 → 令牌 对照表')
    A('')
    A('> t4「门户 CSS 令牌收口：消灭硬编码与漂移色」交付物。路径经 captain 裁定，t4 独享；t2 规范附录只引用、不重复。')
    A('> 令牌输入：**%s**%s' % (src_label, '　←　**PROVISIONAL：t3 未落地，本表不得作为验收结论（§7.4）**' if provisional else ''))
    A('> 计数口径：审计 §7.3 冻结口径（逐元素 computed 去重；rgba(r,g,b,a)→rgb(r,g,b)；剔除纯白/纯黑）；spec §6.2 计数协议同此。')
    A('> 令牌集来源：**唯一机读输入**（spec §6.2 强制），不再从 ' + q('custom_home.css') + ' 抓取。')
    A('> 生成日期：%s' % datetime.date.today().isoformat())
    A('> **引用纪律（吸取本轮实测教训）**：**行号会漂移** —— 本任务亲历同一文件 ' + q('brand_tokens.scss') + ' 的同一批声明从 ' + q(':171-173') + ' 移到 ' + q(':191-193') + '（中间插入了别名行）。'
      + '故本文凡引用源码一律**以令牌名/选择器为锚**，行号仅作辅助定位；**规范引用以节号为准**（r 号会滚动；本文写作时规范已到 **r20 / 1455 行**，文中若干历史判断引的 r4/r7 是**当时**的判定依据，现行结论以节号为准）。')
    A('> **版本标记：t4 开工前基线**（captain 批准提前落盘的快照，防 /tmp 丢失）；t4 正式解锁后按届时裁定迭代 —— **落盘不等于冻结**。')
    A('')
    A('## 0. 复现')
    A('')
    A('    python3 scripts/portal_token_map.py --out docs/audit/portal-color-token-map-t4.md')
    A('')
    A('### 0.1 计数口径（可复现，供 t9 对账）')
    A('')
    A('- **范围**：仅 §0 列出的文件（8 个 edu_portal ＋ 1 个 edu_eval）。**不含** ' + q('custom_home.css') + '（t3 范围）。')
    A('')
    A('> ⚠ **2026-09-29 补注（读本文件的人先看这条）**：上句里的 edu_eval 文件'
      '（' + q('edu_eval/static/src/css/eval_portal.css') + '）**已随行政评估模块整体删除**'
      '（证据 docs/audit/edu-eval-removal.md）⇒ 本扫描的文件清单已从 9 个降为 8 个，'
      '§5.2 依赖表里的 ' + q('edu_eval') + ' 行同样是**删除前的历史读数**。'
      '本文其余内容是按当时那份清单算出的定稿读数，**保留原样当史料**、不重算。')
    A('- **匹配**：' + q('#[0-9a-fA-F]{3,8}') + ' 与逗号式闭合的 ' + q('rgba?(N,N,N[,A])') + '。')
    A('- **归一**：hex 归一小写并展开 3 位缩写；' + q('rgba()') + ' 只取 r,g,b，按 §7.3 与同色 hex **合并**计数。')
    A('- **出现处数** = 匹配次数；**不同值** = 归一后唯一色值数（hex 写法与 rgba 写法算同一个值）。')
    A('- **三种口径禁止混用（规范 §6.2.0 裁定）**：(a) **二元组数**（令牌名, 选择器）去重 = **判定口径**（判据 1/2 用）；(b) **出现处数** = **债务读数**（本表 §11 的 1067/905/613 即此口径）；(c) **不同色值数** = **债务读数**，**不得用于达标判定**。')
    A('- ⛔ **最易搞错**：(c) 是「**CSS 声明里的不同色值数**」，而 KPI 的「全站实测颜色 53→≤28」是「**取色器实测的渲染色数**」—— **两者不是一回事**（同一令牌在不同元素上渲染可能不同；同一渲染色也可能来自多个令牌）。凡涉及「色数」的判据一律以 §6.2 的 S1/S2/S3 ＋ t12 量具的**实测渲染**口径为准；(c) 只能描述「CSS 侧还有多少种写法」。')
    A('- **与 color-arch 复算的差异（已逐文件核对，非口径冲突）**：其 edu_portal 全域得 **299 处**，本表同 8 个 portal 文件得 **269 处**，差额恰为 ' + q('custom_home.css') + ' 的 **30 处**（t3 范围）。逐文件计数完全一致：portal 105 / enterprise 147 / banner 5 / batch1 3 / batch3 3 / enroll 3 / ux_rework 3 / ux_v3 0。')
    A('- **alpha 族差额**：全仓 ' + q('rgba(14,123,242,α)') + ' = **111 处** = 本表 **99 处** ＋ ' + q('custom_home.css') + ' **10** ＋ ' + q('backend_b11.css') + ' **2**。**并非因「.40 那一组」被排除**（巧合：本表 99 处里 .40 恰好也是 12 处）。')
    A('')
    A('扫描范围（t4 inScope，9 个文件）：')
    for rel in PORTAL_CSS:
        A('- ' + q('custom_addons/' + rel))
    A('')
    exact = [(h, c) for h, c in all_cnt.items() if h in by_val and h not in WHITE_BLACK]
    drift = [(h, c) for h, c in all_cnt.items() if h not in by_val and h not in WHITE_BLACK]
    wb = [(h, c) for h, c in all_cnt.items() if h in WHITE_BLACK]
    def nearest(h):
        best, bd = None, 10 ** 9
        if len(h) != 7:
            return None, bd
        r1 = rgb_of(h)
        for v in by_val:
            if len(v) != 7:
                continue
            d = sum(abs(a - b) for a, b in zip(r1, rgb_of(v)))
            if d < bd:
                bd, best = d, v
        return best, bd
    near = far = 0
    for h, c in all_cnt.items():
        if h in by_val or h in WHITE_BLACK:
            continue
        _, bd = nearest(h)
        if bd <= 24:
            near += c
        else:
            far += c
    form_change = sum(1 for r in rgba if r[2] == '14,123,242')
    A('## 0.2 t4 验收口径（captain 修正版，2026-09-15）')
    A('')
    A('原契约要求「门户代表页（' + q('/my/home') + '、' + q('/my/calendar?view=week') + '）真机取色：令牌外颜色数为 0」。**captain 已修正为**：')
    A('')
    A('| # | t4 的责任 | 判据 |')
    A('|---|---|---|')
    A('| 1 | ' + q('/my/home') + ' 令牌外色 = 0 | 真机取色（t9） |')
    A('| 2 | **本任务 9 个 CSS 文件对 ' + q('/my/calendar') + ' 的贡献 = 0** | 即 ' + q('ux_rework.css') + ' 等不再提供令牌外色 |')
    A('| 3 | ' + q('/my/calendar') + ' 的**图例圆点/边框色** | **归 t8**（controller 内联样式，t4 无权可达） |')
    A('')
    A('- **选项 B（扩 t4 inScope 到那两个文件）不采用**：' + q('edu_portal/') + ' 整体本就在 t8 的 inScope 内，**无须跨任务改权**（captain 裁定）。')
    A('- **t4 在该文件上仍有实活**：' + q('ux_rework.css') + ' 的 38 个令牌外字面值**真实渲染在预览页**（' + q('edu_schedule_preview') + '，独立路由）⇒ 仍属 t4 范围；'
      + '只是**不负责** ' + q('/my/calendar') + ' 的图例/边框那几处渲染色。')
    A('')
    A('> ⚠ **因果要点（t9 拆分判分时必读）**：该页图例与边框由 ' + q('edu_portal/controllers/calendar.py:33-38') + ' 的 ' + q('_KIND_COLOR') + ' 经 '
      + q('views/calendar.xml:116/142/209') + ' 写成**内联样式**；**内联样式压过样式表** ⇒ 无论 t4 把 CSS 收得多干净，那几处渲染色都不会变。'
      + '故**不得把 t8 的部分算到 t4 头上**。')
    A('')
    A('## 0.3 冲突仲裁规则（captain 裁定，**全队适用**）')
    A('')
    A('> 当队长的多条消息互相冲突时，以 **(a) 规范 r 版本 > (b) ' + q('color_tokens.json') + ' 的实际键名 > (c) 落地代码** 为准；')
    A('> **若这三者一致、而队长某条消息相反 ⇒ 那条是过期版本：不执行、回报他。**')
    A('')
    A('**为什么用三方物证而不是「谁的消息更新」**：时间戳会被截断/错序（本会话已多次发生消息交叉），而 (a)(b)(c) 三者都是**可读、可核对、可复现**的产物；'
      + '把冲突判定从**时间感知**降级成**物证对照**，任何成员都能独立执行、不依赖对「哪条更新」的记忆。')
    A('')
    A('**本会话实证（同一命名曾出现四版口径）**：')
    A('')
    A('| 版本 | 内容 | 判定 |')
    A('|---|---|---|')
    A('| ① | 收敛到 ' + q('--text-1') + ' | 作废 |')
    A('| ② | ' + q('--shadow-ink') + ' ＋ ' + q('--shadow-ink-rgb') + '（引规范 r4） | 作废（r7 撤回） |')
    A('| ③ | 沿用 ' + q('--shadow') + '（不改名） | 曾按此回退，后又收到「终版 ' + q('--shadow-ink') + '」而反复 |')
    A('| ④ **终版** | **' + q('--shadow') + ' ＋ ' + q('--shadow-rgb') + '** | **(a)(b)(c) 三者一致** ⇒ 据此定案 |')
    A('')
    A('> 台账 §4/§12.1 现即按 ④：' + q('--shadow') + ' ＋ ' + q('--shadow-rgb') + '、**69 处精确命中、ΔE 0.00，数值与结论一字未动**（键名由 ' + q('0a926e0') + ' 落定）。'
      + '本节规则的作用正是让这种反复**在第一次就停下**：任一成员按 (a)(b)(c) 一查即可判定，无须等下一封澄清信。')
    A('')
    A('## 1. 总量（口径 = captain 裁定的三分类）')
    A('')
    A('| 分类 | 处数 | 不同值 | 处理 |')
    A('|---|---|---|---|')
    A('| **令牌内** | %d | %d | 直接 ' % (sum(c for _, c in exact), len(exact)) + q('var()') + ' 替换；其中 **%d 处**为 ' % form_change + q('rgba()') + ' 写法，属「令牌内·需换形式」' + q('rgba(var(--brand-500-rgb), α)') + ' |')
    A('| **令牌外** | %d | %d | 细分：漂移（ΔRGB≤24）**%d 处** / 无令牌 **%d 处**；见 §2、§3、§4 |' % (near + far, len(drift), near, far))
    A('| 黑白豁免（§7.3 剔除） | %d | %d | 一律不动 |' % (sum(c for _, c in wb), len(wb)))
    A('| **合计（源码出现处数）** | **%d** | **%d** | 令牌内 %d ＋ 令牌外 %d ＋ 黑白 %d = %d ✓ |' % (
        sum(all_cnt.values()), len(all_cnt),
        sum(c for _, c in exact), near + far, sum(c for _, c in wb),
        sum(c for _, c in exact) + near + far + sum(c for _, c in wb)))
    A('')
    A('源码侧构成：%d 处十六进制字面值 + %d 处 ' % (len(hexes), len(rgba)) + q('rgba()') + ' = %d 处。' % (len(hexes) + len(rgba)))
    A('')
    A('> 本表计的是**源码出现处数**（卫生指标）。t9 判分用的是**6 个页面渲染出来的颜色**（§7.3），不是这个数。优先清会渲染的，其余尽力，不为降数改观感。')
    A('')
    A('## 2. 「旧字面值 → 令牌名」对照（按频次降序，高频优先）')
    A('')
    A('> **Δ 的定义**：逐通道差之和 ' + q('|ΔR|+|ΔG|+|ΔB|') + '（Δ≤24 视为漂移）。例：' + q('#14182d') + ' → ' + q('--text-1 #1A2233') + ' 的逐通道差为 **(6,10,6)**、Δ=**22**。')
    A('')
    A('| 序 | 旧字面值 | 处数 | 令牌 | 判定 |')
    A('|---|---|---|---|---|')
    rank = 0
    for h, c in sorted(drift + exact, key=lambda x: -x[1]):
        rank += 1
        if h in by_val:
            tok, verdict = ', '.join(q(n) for n in by_val[h][:3]), '精确'
        else:
            best, bd = nearest(h)
            if best and bd <= 24:
                tok, verdict = '~' + q(best) + '（Δ%d）' % bd, '漂移'
            else:
                tok, verdict = '**无令牌**（见 §4）', '令牌外'
        A('| %d | %s | %d | %s | %s |' % (rank, q(h), c, tok, verdict))
    A('')
    A('## 3. 「α 字面值 → 档位」对照（' + q('--brand-500') + ' 族）')
    A('')
    A('> **档位定义与阈值：一律以规范 §4 为唯一权威**（' + q('docs/plans/color-system-v4.md') + '）。本 §3 **不复述**档位/阈值，只做**逐处实例数据与映射**（color-arch 请求，已采纳）；不另建 α 台账。')
    A('> 下表「建议档」列的取值由生成器的**单一常量**产生（便于规范改动后一行重生成）—— 该常量与规范 §4 **不一致时以规范为准，并回报差异**（与 §0.3 物证优先同一条纪律）。')
    A('> 本次生成所用的档位快照（**仅供本表计算，非权威**）：' + ' / '.join('%.2f' % a for a in EXPECTED_ALPHA) + '；遮罩档 ' + ' / '.join('%.2f' % a for a in MASK_ALPHA) + '。')
    A('> **归并规则/阈值/例外清单：见规范 §4**（本表不复述）。')
    A('> ')
    A('> **适用范围三条**：①档位**只用于令牌族的 α**；②**白/黑叠加一律不量化**（真实的遮罩/反白层，量化会掉对比度）；③阴影/遮罩走 ' + q('.70/.85') + '，不进品牌阶梯。')
    A('> ')
    A('> ⚠ **规范硬约束（captain 采纳并升级）**：α 一律以**千分数整数**表示与比较（' + q('.20') + '→' + q('200') + '、' + q('.18') + '→' + q('180') + '），'
      + '阈值 = **Δ < 50‰ 归并 / Δ ≥ 50‰ 保留**（＝规范常量 ' + q('MERGE_DELTA_PERMILLE_LT = 50') + '）；**禁止任何浮点比较**。t3 门禁与 t9 复测必须用同一条整数规则，否则同一处会被判出两个结果。')
    A('> ⚠ 反面实证：' + q('0.20 - 0.18 == 0.020000000000000018') + '、' + q('0.35 - 0.30 == 0.04999999999999999') + ' —— 浮点会让**两个方向的误判同时发生**'
      + '（前者把「应归并」判成保留，后者把「应保留」判成归并）。我就先栽在 ' + q('.20→.18') + ' 上。')
    A('')
    fam = [r for r in rgba if r[2] == '14,123,242']
    agg = collections.defaultdict(collections.Counter)
    for _, _, _, a, prop in fam:
        agg[a][CLASSIFY.get(prop, prop)] += 1
    A('| 原 α | 建议档 | Δα | 用途 | 处数 | 动作 |')
    A('|---|---|---|---|---|---|')
    for a in sorted(agg):
        t = tier(a)
        d = abs(pm(t) - pm(a)) / 1000.0
        n = sum(agg[a].values())
        uses = ', '.join('%s×%d' % (k, v) for k, v in agg[a].most_common())
        act = '**保留原 α**' if abs(pm(t) - pm(a)) >= 50 else '归并 → %.2f' % t
        A('| %.2f | %.2f | %.2f | %s | %d | %s |' % (a, t, d, uses, n, act))
    A('')
    A('统一引用形式：' + q('rgba(var(--brand-500-rgb), α)') + '（**逗号通道 + 逗号引用**）—— 通道令牌下任何 α 均在令牌内。')
    A('')
    A('### 3.1 换档收益：越界处数 **17 → 5**（captain 要求留作换档证据）')
    A('')
    A('| 口径 | 仍越界（保留原 α）的处数 | 说明 |')
    A('|---|---|---|')
    A('| 旧五档 ' + q('.05/.08/.12/.20/.35/.50') + ' | **17 处** | ' + q('.28') + '×1 ＋ ' + q('.30') + '×2 ＋ **' + q('.40') + '×12** ＋ ' + q('.45') + '×1 ＋ ' + q('.55') + '×1 |')
    A('| 定稿十档 ' + ' / '.join('%.2f' % a for a in EXPECTED_ALPHA) + ' | **5 处** | ' + q('.28') + '×1 ＋ ' + q('.30') + '×2 ＋ ' + q('.45') + '×1 ＋ ' + q('.55') + '×1；' + q('.40') + ' 的 12 处全部落档 |')
    A('')
    A('> **精确归因（避免规范过度归功于阈值放宽）**：本范围内 17→5 的收益**全部来自 ' + q('.40') + ' 入档**（一档吃掉 12 处）；'
      + '阈值从 ' + q('≤0.02') + ' 放宽到 ' + q('<0.05') + ' 在本范围**没有额外效果** —— 因为本范围**没有任何 α 落在 (0.02, 0.05) 区间**。'
      + '该区间的收益出现在别处（如 ' + q('.22→.18') + ' Δ.04、' + q('.38→.35') + ' Δ.03）。')
    A('')
    A('### 3.2 保留原值清单（Δα ≥ 0.05，本范围实测）')
    A('')
    A('.28→.35（Δ.07）、.30→.35（Δ.05）、.45→（Δ.05）、.55→.50（Δ.05）—— 共 **5 处**。**一律保留原作者 α**，只换引用形式。')
    A('')
    A('### 3.3 α 底色的「基底归属」边界（color-arch 划定，我已逐格复算）')
    A('')
    A('| 承载文字的蓝调面 | 基底 ' + q('--brand-500') + ' | 基底 ' + q('--brand-action') + ' |')
    A('|---|---|---|')
    A('| ' + q('.10') + ' 压白 | ' + q('#E7F2FE') + ' → 字 ' + q('--brand-action') + ' **4.43 ✗** ／ 字 hover **5.05 ✓** | ' + q('#E7F0FB') + ' → **4.36 ✗** ／ **4.97 ✓** |')
    A('| ' + q('.12') + ' 压 ' + q('--bg') + ' | ' + q('#D8E8F9') + ' → **4.02 ✗** ／ **4.59 ✓** | ' + q('#D8E6F6') + ' → **3.96 ✗** ／ **4.52 ✓（余量仅 0.02）** |')
    A('')
    A('⇒ **①承载文字的 α 蓝调面基底留在 ' + q('--brand-500-rgb') + '**；其上文字**必须 ' + q('--brand-action-hover #0A63CC') + '**；'
      + '**②无 α 的实色选中/激活填充**用 ' + q('--brand-action') + '（白字 5.02 ✓）；'
      + '**③承载文字的面上禁止用 ' + q('rgba(--brand-action-rgb, .12)') + '**（只有 4.52）。')
    A('')
    A('## 4. 无令牌族 rgba 的归并（裁定：**收敛**，不新增档位）')
    A('')
    A('| 底座 | 处数 | 主用途 | 归并目标 | 备注 |')
    A('|---|---|---|---|---|')
    note = [
        ('20,24,45', q('--shadow'),
         '**精确命中**（' + q('--shadow: #14182D') + '，由 ' + q('--shadow-rgb: 20, 24, 45') + ' 派生）⇒ **69 处零改色，只换引用形式**。'
         + '69/69 全为 box-shadow ⇒ §7.3 四列量不到，对验收零影响。**captain 终版命名**：' + q('--shadow') + ' ＋ ' + q('--shadow-rgb') + '（逗号）；'
         + '作废的两版旧口径为：①「收敛到 ' + q('--text-1') + '」②「' + q('--shadow-ink') + ' ＋ ' + q('--shadow-ink-rgb') + '」。'),
        ('70,148,8', q('--success'), 'Δ150=(52,26,72)，原为不相干的绿；17/22 为 background（大面）→ 见 §4.2'),
        ('217,31,31', q('--danger'), 'Δ47=(25,8,14)；14/21 为 background（大面）→ 见 §4.2'),
        ('255,165,0', q('--warning'), 'Δ53=(23,18,12)；CSS ' + q('orange') + ' 遗留；13/15 为 background（大面）→ 本族收敛后对比度全过'),
        ('102,102,102', q('--neutral'), 'Δ28=(8,1,19)；12/14 为 background（大面）→ 见 §4.2'),
    ]
    for base, tgt, nt in note:
        lst = [r for r in rgba if r[2] == base]
        pc = collections.Counter(CLASSIFY.get(r[4], r[4]) for r in lst)
        A('| ' + q('rgba(%s,α)' % base) + ' | %d | %s | %s | %s |' % (len(lst),
          ', '.join('%s×%d' % (k, v) for k, v in pc.most_common()), tgt, nt))
    A('')
    A('**收敛必须区分「面」与「字」两个角色**：')
    A('')
    A('- **面**（其上要压文字）：收敛到扁平的 ' + q('--success-soft') + ' / ' + q('--danger-soft') + ' / ' + q('--warning-soft') + ' / ' + q('--neutral-soft') + '，**而不是**把 α 叠层的基底换掉；')
    A('- **字**：收敛到 ' + q('--success') + ' / ' + q('--danger') + ' / ' + q('--warning-ink') + ' / ' + q('--neutral') + '；')
    A('- 描边/阴影（其上无文字）可只换基底，无观感风险。')
    A('')
    A('**通道令牌为派生式**（' + q('--brand-500-rgb: #{red($brand-500)}, …') + '，逗号）⇒ 值的唯一来源是基色，本表不再另列字面值。')
    A('')
    A('**收敛后的最终引用（裁定已下，t4 可直接定稿）**：')
    A('')
    A('| 族 | 面（承载文字时） | 字 | 通道（供 ' + q('rgba(var(--x-rgb), α)') + ' 用） |')
    A('|---|---|---|---|')
    A('| success | ' + q('--success-soft') + ' | ' + q('--success') + ' | ' + q('--success-rgb') + ' = **18 122 80**（= ' + q('#127A50') + '） |')
    A('| danger | ' + q('--danger-soft') + ' | ' + q('--danger') + ' | ' + q('--danger-rgb') + ' = **192 39 45**（= ' + q('#C0272D') + '） |')
    A('| warning | **角色限定**：' + q('--warning #E8930C') + ' 是**面**令牌（白字压它 **2.44 ✗**、' + q('--text-1') + ' 压它 **6.52 ✓**）⇒ **它本身不能作文字**；作字须用 ' + q('--warning-ink #8F5700') + '（压 ' + q('--warning-soft') + ' = **5.45 ✓**）。'
      + '⚠ **本行曾误把「面」当「字」测**（旧文写「.10~.22 全 ✓ 4.62~5.46」，那其实是 ink 线）—— ' + q('--warning') + ' 作字压自家 α 底实测 **2.33/2.25/2.20/2.13/2.10/1.88/1.72 全 ✗**（color-arch 复算一致）。'
      + '这正是「区分面/字」规则要防的错，已在规范 §3.2 规则 3c 留作现场例证 |')
    A('| neutral | ' + q('--neutral-soft') + ' | ' + q('--neutral') + ' | ' + q('--neutral-rgb') + ' = **94 103 121**（= ' + q('#5E6779') + '） |')
    A('')
    A('> ⚠ **这四个值是「真令牌」的通道**（如 ' + q('--success-rgb') + ' = 18 122 80 = ' + q('#127A50') + '），**与会话早期提到的遗留色 ' + q('#469408') + ' 等完全不同**。'
      + '收敛的含义正是「把站点取值改成令牌色」⇒ 改成引用这些 ' + q('-rgb') + ' 之后，那些站点才**不再产生令牌外色**。'
      + '（若误按遗留色的通道值写 ' + q('-rgb') + '，就会造出「名字像令牌、值却是旧色」的假名令牌 —— 正是本文反复防的那类。）')
    A('')
    A('> **令牌层状态（eng-web 报告，本文引用其结论）**：t3 令牌层**内容冻结** —— 46 个令牌 ＋ 11 个通道令牌，**11 个通道的基色全部存在**（零例外、无需白名单），编译产物前后台双端各 ' + q('defs=1') + '。')
    A('')
    A('> 🏁 **影子族终局裁定（captain，三方物证一致）：A ＝ ' + q('--shadow') + ' ＋ ' + q('--shadow-rgb') + ' ＋ 墨色 ' + q('#14182D') + '，零动作。** 凡要求改名 ' + q('--shadow-ink') + ' 或改值 ' + q('#172B4D') + ' 的指令（无论来自谁、声称第几版）一律为过期版本：**不执行、回报队长**。三方物证：规范 §2.6 L409/L410/§486-495 ｜ 落地代码 ｜ ' + q('color_tokens.json') + ' 键名。')
    A('')
    A('> ✅ **影子族已收口**（captain 复核工作区）：① ' + q('brand_tokens.scss') + ' 的 ' + q('--shadow: #14182D') + ' 与由 ' + q('--shadow-rgb') + ' 派生的三档阴影**本来就是 #14182D 系**；'
      + '② 旧 ' + q(':root') + ' 令牌块**已整体迁出** ' + q('custom_home.css') + '（现 ' + q(':81') + ' 起为迁移说明注释），旧表中那几处 ' + q('rgba(23,43,77,α)') + ' 阴影值随之消失；'
      + '该迁移**已提交**：' + q('git log -S EAF4FF -- custom_home.css') + ' 定位到 ' + q('87eb534') + '（此后全仓再无旧令牌字面值）。'
      + '③ 旧墨 ' + q('rgba(23,43,77,α)') + ' / ' + q('#172B4D') + ' 全仓**已清零（0 处）** —— 最后 1 处 ' + q('custom_home.css:217') + ' 已由 eng-web 改掉；此为「3 处 → 1 处 → **0 处**」的收敛终态，我实测复核为空。'
      + '④ ' + q('--shadow') + ' 改名已撤回 ⇒ ' + q('--shadow') + '/' + q('--shadow-rgb') + ' 同名配对成立，判据 8 **不需要白名单**。')
    A('>')
    A('> 其含义：门户 69 处 ' + q('#14182D') + ' → ' + q('var(--shadow)') + ' = **零改色**（不是「收向 ' + q('#172B4D') + '」）。')
    A('>')
    A('> ✅ **命名已决（captain）：基色 ' + q('--shadow') + ' ＋ 通道 ' + q('--shadow-rgb') + '；' + q('--shadow-ink') + ' 方案作废，不改名**。')
    A('> 依据：**落地代码已是此态**（' + q('brand_tokens.scss:191/204') + '）⇒ **零改动**、判据 8 同名配对天然通过；改名方案（基色与通道同时改）纯属额外返工。')
    A('> 沿革（备查，勿再翻案）：①「收敛到 ' + q('--text-1') + '」作废；②「' + q('--shadow-ink') + ' ＋ ' + q('--shadow-ink-rgb') + '」作废；③**本条：' + q('--shadow') + ' ＋ ' + q('--shadow-rgb') + '（终版）**。')
    A('>')
    A('> **含义不变**：门户 69 处 ' + q('#14182D') + ' → ' + q('var(--shadow)') + ' = **精确命中、零改色**（§12.1 数值与结论不动，仅键名）。')
    A('>')
    A('> 🔒 **命名闸门（captain 正式采纳，★ 保留在本节）**：**台账与今后 t4 引用一律以 ' + q('color_tokens.json') + ' 的实际键名为准** —— '
      + '把命名之争交给**唯一机读输入**自解，不依赖任何人的口头确认。上游命名再翻几次，**只改数据、不改引用纪律** ⇒ **永不产出指向不存在令牌的无效引用**。'
      + '（本闸门与「逗号通道切换闸门」同源：两者都只认产物读数，不认叙述。）')
    A('>')
    A('> ⚠ **本轮新发现的同步缺口（已上报）：' + q('scripts/color_tokens.json') + ' 与其源不一致**。源已是**逗号通道**（' + q('brand_tokens.scss:196-204') + ' 十一个全逗号，mtime 15:44），'
      + '而 JSON 仍报**空格**（' + q('--brand-500-rgb') + ' = ' + q('"14 123 242"') + '，mtime 15:17，早于源的改动）⇒ **必须重新生成**。')
    A('> 影响：① 本文的**切换闸门**读 JSON 会得到**假阴性**（明明可切却判「仍是空格」）；② t9 读 JSON 会拿到过期通道值。'
      + '故闸门口径定为：**源与 JSON 不一致时以源为准、并立即上报**（与逗号通道同一条纪律）。')
    A('')
    A('**产出侧根因（captain 已立 t15 修；我实测复核）**：' + q('color_tokens.py') + ' 的 ' + q(':112') + ' 与 ' + q(':212') + ' 用空格格式串硬编码通道分隔（' + q('"%d %d %d"') + '），'
      + '而解析侧（' + q(':123') + '）已带**可选逗号的容错** ⇒ **只重跑仍会产出空格，必须先改产出**；另有 ' + q(':15') + ' 的注释仍是空格模板，需一并改。')
    A('')
    A('### 4.3 逗号切换的执行选择（t4 报告须写明）')
    A('')
    A('**本任务选择：现在就切（不等 t15）**，依据三条：')
    A('')
    A('1. **浏览器取的是源**：门户 CSS 引用的自定义属性由 ' + q('brand_tokens.scss') + ' 的编译产物提供，**源已是逗号** ⇒ ' + q('rgba(var(--brand-500-rgb), .1)') + ' 运行时展开为 ' + q('rgba(14, 123, 242, .1)') + ' ＝合法 CSS；')
    A('2. ' + q('color_tokens.json') + ' 只是**读取侧**产物（供门禁与 t9 复算），**不参与渲染** ⇒ 它过期不影响页面正确性；')
    A('3. 不切会让「令牌外色」多挂 168 处，与本任务目标相悖。')
    A('')
    A('**t15 落地后的复核：已完成（eng-web 修好产出侧后我实测）** —— 闸门读数**转正**：--brand-500-rgb.value 现为逗号式；**11/11 通道全含逗号**；11 个通道均带 base 基色；判定 **PASS ⇒ 逗号式为正确写法**。意义：我当初选「现在就切」依据的是**源**（当时 JSON 仍报空格，只能靠物证优先规则判断）；现在 artifact 已与我的写法一致 ⇒ **靠「源优先」做出的决定，事后被修好的 artifact 证实**，这就是规则的用法（一致时执行、修正后回填验证）。')
    A('')
    A('> **附带发现（建议并入 t15）**：' + q('--shadow-sm/md/lg') + ' 在源里有定义（' + q('brand_tokens.scss:191-193') + '），但因取值非纯 hex（形如 ' + q('0 1px 2px rgba(var(--shadow-rgb), .05)') + '），'
      + '被 ' + q('color_tokens.py:103') + ' 的 hex 提取过滤掉 ⇒ **JSON 的 ' + q('tokens') + ' 表比源少 3 个**（46 vs 源侧 49）。'
      + '对「四列渲染色」判分无影响（阴影不在量具内），但会让**「引用是否存在」的静态核对与令牌计数出现假阴性** —— 收紧 t15 时可一并提取。')
    A('>')
    A('> 附：规范 r6/r7 已吸收我三处取证（' + q('/my/calendar') + ' 四色归属改判 t8；新增「归属判定方法要求」；§2.5.1 上半张表标注陈旧）✓；' + q('#172B4D') + ' 已由「3 处」→「1 处」→「0 处」✓；计数口径「71 处＝全仓 / 69 处＝t4 范围」✓。')
    A('')
    A('### 4.2 收敛后的实测：不区分面/字会造出**新的不达标**（逐格实算）')
    A('')
    A('| 族 | 收敛后「字压自家 α 底」 | 判定 |')
    A('|---|---|---|')
    A('| success | ' + q('--success') + '：.09→4.73 ✓ ／ .12→4.53 ✓ ／ .14→4.39 ✗ ／ .18→4.15 ✗；**叠 ' + q('--bg') + ' 时 .09→4.42 ✗** | 部分 ✗ |')
    A('| danger | .06~.12 → 4.85~5.35 ✓；**.30→3.56 ✗ ／ .40→2.98 ✗** | 深档 ✗ |')
    A('| warning | .10~.22 → 4.62~5.46 全 ✓ | ✓ |')
    A('| neutral | .09~.12 → 4.54~5.04 ✓；**.16 叠 ' + q('--bg') + ' → 4.29 ✗** | 深档 ✗ |')
    A('')
    A('而**扁平 soft 对全过**：' + q('--success') + '/' + q('--success-soft') + ' **4.84 ✓**、' + q('--danger') + '/' + q('--danger-soft') + ' **5.12 ✓**、'
      + q('--warning-ink') + '/' + q('--warning-soft') + ' **5.45 ✓**、' + q('--neutral') + '/' + q('--neutral-soft') + ' **5.11 ✓**。')
    A('')
    A('> ⇒ **captain 已裁定采纳本口径**：承载文字的**面收敛到 ' + q('*-soft') + ' 扁平令牌**（不把原 α 叠层的基底换成令牌色）；**描边/阴影（其上无文字）只换基底**。'
      + '理由即上表：换基底会在 success 叠 ' + q('--bg') + '、danger 深档、neutral .16 三处造出新失败，与「对比度 6→0」直接冲突。')
    A('> ⚠ **' + q('--warning #E8930C') + ' 作实底必须配深色字**：白字仅 **2.44 ✗**。captain 已并入规范修订。')
    A('')
    A('## 5. CSS 覆盖不到的 inline 色值（移交 t7）')
    A('')
    A('| 位置 | 现值 | 问题 |')
    A('|---|---|---|')
    A('| %s | %s | 提交按钮棕金；t7 按裁定 A 处置（见 §5.1） |' % (
        q('custom_addons/edu_apply/views/templates.xml:109'), q('style="background:#8a6d3b;border-color:#8a6d3b;"')))
    A('| %s | %s | 成功页 check 图标：承载「成功」语义属**有意义图形**（WCAG 1.4.11 需 ≥3:1）；' % (
        q('custom_addons/edu_apply/views/templates.xml:125'), q('style="color:#c8a870;"'))
      + q('#C8A870') + ' 白底 2.26 ✗ ⇒ 改用 ' + q('var(--gold-ink)') + '（保金色语义，5.12 ✓） |')
    A('')
    A('### 5.1 t7 处置（captain 裁定 **A**：只删 inline，靠网站色板）')
    A('')
    A('- ' + q('templates.xml:109') + '：**删除 inline style**，由 t3 接线后的网站色板着色（终态＝统一蓝，不含金）。')
    A('  **t7 交付必须记录按钮改前/改后 computed 值**；t9 复测若仍非统一蓝 ⇒ **升级为阻塞并回报 captain**。')
    A('- ' + q('templates.xml:125') + '：改用 ' + q('var(--gold-ink)') + '；同页 ' + q('#C8A870') + ' 共 **5 处**（text 3 ＋ anchor 2），一并处置。')
    A('')
    A('### 5.2 顺序红线（t7 必守）')
    A('')
    A('实测依赖：' + q('edu_portal') + ' 直接依赖 ' + q('edu_brand') + '；' + q('edu_eval') + ' 经 ' + q('edu_portal') + ' 传递；'
      + q('edu_apply') + ' 仅依赖 ' + q('website') + '、' + q('mail') + '，**与 ' + q('edu_brand') + ' 无依赖路径**。')
    A('')
    A('| 模块 | 与 edu_brand 的依赖路径 | bundle 相对顺序 | 可否声明令牌 |')
    A('|---|---|---|---|')
    A('| edu_portal（t4） | 直接依赖 | 保证在 edu_brand 之后 | 只消费 |')
    A('| edu_eval（t4） | 传递依赖 | 保证在 edu_brand 之后 | 只消费 |')
    A('| edu_apply（t7） | **无依赖路径** | **不保证** | **只消费，禁止声明令牌** |')
    A('')
    A('### 5.3 通道令牌消费语法 + 门禁口径（已核实）')
    A('')
    A('| 规则 | 说明 | 现状核实 |')
    A('|---|---|---|')
    A('| **必须**用逗号式：令牌 ' + q('--brand-500-rgb: 14, 123, 242;') + ' ＋ 消费 ' + q('rgba(var(--brand-500-rgb), .08)') + ' | **captain 反转裁定**（eng-web 在 libsass 3.6.5 实测复现）：空格+斜杠 ' + q('rgb(var(--c-rgb) / .08)') + ' **编译失败**（libsass 把 ' + q('rgb(') + ' 当内置函数 ⇒ 缺 $green）；逗号式 rc=0 正常 | 本仓先例 ' + q('custom_home.css:636 --bs-primary-rgb: 12, 109, 215') + ' |')
    A('| **FAIL ①**：.scss 的**普通属性**上出现 ' + q('rgb(var(') + ' | 编译失败（libsass 把 ' + q('rgb(') + ' 当内置函数） | ⇒ 判据须有**两条限定**：① **限定「普通属性」**（自定义属性值内 opaque、合法可编译）；② **注释内不计**（先剥注释）。照字面写会**误杀合法写法**。eng-web 门禁已是限定版（其 ' + q('RX_PROP_SLASH') + ' 显式跳过 ' + q('--') + ' 开头者）并做过注入式反证 |')
    A('| 全仓 ' + q('rgb(var(') + ' 实况（eng-web 复核） | —— | **仅剩 1 处**：在 ' + q('backend_b11.css:6') + '，且**位于注释**（eng-backend 的规则说明）⇒ 被 ' + q('strip_comments') + ' 正确剥除、未误判 |')
    A('| **FAIL 6a（终局措辞，captain）**：' + q('--x-rgb') + ' 的值里**没有逗号** ⇒ **直接 FAIL**（与 §2.7 规则 1 逐字一致）；早期「空格＋逗号引用组合」的措辞**作废**。限定：**.scss 普通属性 ＋ 剥注释后**判定 |')
    A('| **FAIL ②（旧措辞，已作废）**：**空格分隔**的通道令牌被**逗号引用** | 展开成 ' + q('rgba(14 123 242, .08)') + ' ⇒ 无效 CSS、computed-value 静默失效 | 与判据①互为镜像，二者构成「分隔符必须配对」 |')
    A('| **PASS** = 逗号通道 ＋ 逗号引用 | 本表 269 处 ' + q('rgba()') + ' 一律按此改 | 全仓 ' + q('rgba(var(') + ' 现状 **0 处**（仍是有效底数，但不再是红线） |')
    A('| ⚠ 反转后**令牌源自身需三处联动改**（我已上报，不属 t4） | ① 通道改逗号（' + q('brand_tokens.scss:196-206') + '）；② ' + q('brand_tokens.scss:191-193') + ' 的 ' + q('rgb(var(--shadow-rgb) / .05)') + ' 必须改 ' + q('rgba(var(--shadow-rgb), .05)') + '（否则逗号通道下展开成 ' + q('rgb(20, 24, 45 / .05)') + ' ＝无效 CSS）；③ 24-29 行注释写的是旧规则，须重写 | spec 侧 §2.7 与 §6.3 判据 6 亦须同步反转 |')
    A('| ' + q('-rgb') + ' 为**派生式** | 名字与值由构造保证一致，「值须等于同名基色」自动成立 | 本表不列 ' + q('-rgb') + ' 的值 |')
    A('| 门禁：**(令牌名, 选择器) 二元组 + 逐批棘轮 ' + q('adopted_files') + '** | 只有已收口文件参与「集外裸色 FAIL」 | 债务计数见 §11 |')
    A('| **判重只认 **' + q(':root') + '** / **' + q('[data-bs-theme] body') + '** 级别的声明** | 选择器内的局部变量（如 ' + q('.ux3-page{--ux3-gold}') + '）属**组件作用域、不参与令牌判重**；**但其字面值仍计为「令牌外色」** | 故 ' + q('#8A6D3B') + ' 必须消除（按 §9.1 的消费点分流改蓝/中性，**不是**换成 ' + q('--gold-ink') + '）才不挂在 §1 |')
    A('')
    A('### 5.4 libsass 行为矩阵（captain 在容器内实跑，权威证据）')
    A('')
    A('环境：libsass **3.6.5+20231221**（容器内 ' + q('python3 sass') + ' 实跑）。')
    A('')
    A('| # | 写法 | 结果 | 判定 |')
    A('|---|---|---|---|')
    A('| A | 普通属性 ' + q('color: rgb(var(--c-rgb) / .08)') + ' | **ERROR: Function rgb is missing argument $green** | **编译失败** |')
    A('| B | **空格**通道 ＋ ' + q('rgba(var(--c-rgb), .08)') + ' | 编译过，输出 ' + q('--c-rgb: 14 123 242') + ' ⇒ 浏览器展开为 ' + q('rgba(14 123 242, .08)') + ' | **无效 CSS、静默失效** |')
    A('| C | **逗号**通道 ＋ ' + q('rgba(var(--c-rgb), .08)') + ' | 编译过，输出 ' + q('--c-rgb: 14, 123, 242') + ' ⇒ ' + q('rgba(14, 123, 242, .08)') + ' | ✅ **唯一合法组合** |')
    A('| D | **自定义属性值内** ' + q('rgb(var(--c-rgb) / .05)') + ' | 编译过（opaque token，不进 sass 求值） | 解释了令牌源 171-173 行为何现在能编译 |')
    A('| E | ' + q('--plain: $c;') + ' → 输出字面串 ' + q('$c') + '；' + q('--interp: #{$c};') + ' → 输出 ' + q('#0E7BF2') + ' | **不插值＝静默失败** | 别名/派生必须走 ' + q('#{}') + ' 插值 |')
    A('')
    A('**最终判据（三件套到位后生效）**：')
    A('')
    A('- ✅ **PASS = 逗号通道 ＋ 逗号引用**（C）；')
    A('- ❌ FAIL = .scss **普通属性**里出现 ' + q('rgb(var(') + '（A，编译失败）；')
    A('- ❌ FAIL = **空格通道 ＋ 逗号引用**（B，computed-value 静默失效）；')
    A('- 注：D 说明判据①必须限定**普通属性**，否则会误判令牌源自身的 ' + q('--shadow-sm/md/lg') + '（171-173 行）。')
    A('')
    A('**执行闸门（我 t4 侧的硬前置）**：消费方**在三件套齐备前维持现状**（纯 .css 不受 sass 影响，现状可跑）：')
    A('')
    A('1. ① t3 令牌源改逗号产出；② spec §2.7 改逗号口径；③ spec §6.3 判据 6 反向。**三者同时到位前不动消费方**。')
    A('2. 切换前先做**机械前置校验**：读 ' + q('scripts/color_tokens.json') + ' 的 ' + q('channels') + '，确认 ' + q('--brand-500-rgb.value') + ' 是 ' + q('"14, 123, 242"') + '（**含逗号**）——'
      + '若仍是 ' + q('"14 123 242"') + ' 就切换，会直接落进 B 情形的静默失效。这条可脚本化，不靠人眼。')
    A('3. 校验通过后**一次性**把 269 处 ' + q('rgba()') + ' 切到逗号引用，并复跑 axe/取色。')
    A('')
    A('> 备注：本条曾出现「eng-web 的信（逗号）／eng-web 的文件（空格）／spec §2.7（空格＋斜杠）／spec §6.3 判据 6（逗号 FAIL）」四方互斥；'
      + '在无 sass 编译器的环境下**不改并上报**是唯一稳妥处置（captain 已确认此处置正确，并给 eng-web 下了三件套返工指令）。')
    A('')
    A('## 6. 令牌消费方期望值（供 t9/t10 校验）')
    A('')
    A('| 令牌/属性 | 门户页期望观测值 | 来源 |')
    A('|---|---|---|')
    A('| ' + q('--body-color') + ' | ' + q('#5E6779') + '（= ' + q('--text-3') + '） | 全仓该族全局声明点仅 ' + q('custom_home.css:654') + ' 一处；特异度若丢失会退回 core 的 ' + q('#6b7385') + '，在 ' + q('--bg') + ' 上 = 4.42 ✗ |')
    A('| ' + q('--brand-500') + ' | ' + q('#0E7BF2') + ' | 令牌表 |')
    A('| ' + q('--brand-action') + ' | ' + q('#0C6DD7') + '（白底 4.5 档） | t112 对比度档 |')
    A('| 门户链接色 | **肯定式断言**：校名/导航链接的 computed 值 == ' + q('--brand-action') + ' 的 rgb（' + q('rgb(12, 109, 215)') + '） | **不要写成否定式**（如「不再是 ' + q('#0F34C3') + '」）—— ' + q('#0F34C3') + ' 是 ' + q('auto-contrast()') + ' 算出来的，改色板后可能派生成**另一个令牌外蓝 ' + q('#0955A7') + '** 从而蒙混过关；唯一让它落到令牌色的路径是走 ' + q('$o-user-color-palette') + '（' + q('secondary_variables.scss:217') + ' 会把 user-palette 键名自动 join 进排除表）。机制见 ' + q('docs/plans/color-tokens-t3.md') + ' §10（eng-web 发现） |')
    A('| ' + q('--gold-*') + ' | **门户/后台不得引用**（§2.5.1 终裁） | ' + q('--gold-ink') + ' 只服务公共网站浅底金字；门户侧应校验「无 ' + q('--gold-') + ' 引用」 |')
    A('')
    A('## 7. /apply 改前实测读数（t7 判据底数，来自审计原始数据归档）')
    A('')
    A('来源：' + q('docs/audit/ui-color-raw-2026-09-15.json') + ' 的 ' + q('https://edu.example.org/apply') + '。')
    A('')
    A('| 列 | 读数（值 × 元素数） |')
    A('|---|---|')
    A('| border | ' + q('rgb(118,118,118)') + ' × **31**（Chrome UA 默认）、' + q('rgb(243,242,242)') + ' ×9、' + q('rgb(2,109,222)') + ' ×1、' + q('rgb(138,109,59)') + ' ×1、' + q('rgba(200,168,112,.5)') + ' ×1 |')
    A('| text | ' + q('rgb(94,103,121)') + ' ×38、' + q('rgba(0,0,0,.65)') + ' ×12、白 ×10、' + q('rgb(182,176,176)') + ' × **9**、' + q('rgb(220,53,69)') + ' ×7、' + q('rgb(200,168,112)') + ' ×3、' + q('rgb(15,52,195)') + ' ×1 |')
    A('| bg | 白 ×32、' + q('rgb(138,109,59)') + ' × **10**、' + q('rgb(14,123,242)') + ' ×1、' + q('rgb(2,109,222)') + ' ×1、' + q('rgb(18,16,14)') + ' ×1 |')
    A('| anchor | ' + q('rgba(0,0,0,.65)') + ' ×12、' + q('rgb(182,176,176)') + ' × **9**、白 ×2、' + q('rgb(200,168,112)') + ' ×2、' + q('rgb(15,52,195)') + ' ×1、' + q('rgb(217,210,197)') + ' ×1 |')
    A('')
    A('与 t7 验收条款逐条吻合：' + q('rgb(118,118,118)') + ' **31 处** ✓、' + q('rgb(182,176,176)') + ' **18 处**（text 9＋anchor 9）✓、'
      + q('#DC3545') + ' **7 处** ✓、' + q('#8A6D3B') + ' **10 处**（bg）＋ border 1 ✓、' + q('#C8A870') + ' **5 处**（text 3＋anchor 2）。')
    A('')
    A('### 7.1 实测得出的关键结论（影响 :109 的落地）')
    A('')
    A('/apply 的 bg 列同时出现 ' + q('rgb(2,109,222)') + '（网站色板 ' + q('--o-cc1-btn-primary') + '）与 inline 棕金；而全仓唯一令牌化的 ' + q('.btn-primary') + ' 规则是 '
      + q('custom_home.css:443') + ' 的 ' + q('#wrapwrap.o_portal .btn-primary') + '——**实测未出现其值 ' + q('#0C6DD7') + '，即该规则在 /apply 不生效**'
      + '（/apply 走 ' + q('website.layout') + ' ＋ ' + q('#wrap.yylc-page') + '，非 portal 包裹层）。故 :109 终态由**网站色板**决定（t3 接线）。')
    A('')
    A('## 8. 「大面填充」逐处清单（逐处列出再动）')
    A('')
    A('筛选：属性为 background / background-image 且归一后属**令牌外**；令牌内与黑白豁免不计入。')
    A('')
    sites = []
    for rel in PORTAL_CSS:
        p = os.path.join(ROOT, 'custom_addons', rel)
        for i, line, sel in walk_selectors(p):
            for mm in re.finditer(r'(background(?:-image)?)\s*:\s*([^;]+);', line):
                for cm in re.finditer(r'#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)', mm.group(2)):
                    hx = color_of(cm.group(0))
                    if hx is None or hx in by_val or hx in WHITE_BLACK:
                        continue
                    sites.append((rel, i, sel, mm.group(1), cm.group(0).strip()))
    by_file = collections.Counter(s[0].split('/')[-1] for s in sites)
    by_col = collections.Counter(color_of(s[4]) for s in sites)
    A('共 **%d 处**，分布：%s。' % (len(sites), '、'.join('%s %d' % (k, v) for k, v in by_file.most_common())))
    A('')
    A('按底色归并（前 12）：%s' % '、'.join('%s ×%d' % (q(k), v) for k, v in by_col.most_common(12)))
    A('')
    A('| # | 文件:行 | 生效选择器 | 属性 | 现值 |')
    A('|---|---|---|---|---|')
    for n, (rel, i, sel, prop, val) in enumerate(sites, 1):
        A('| %d | %s | %s | %s | %s |' % (n, q('%s:%d' % (rel.split('/')[-1], i)), q((sel or '?')[:70]), prop, q(val)))
    A('')
    A('> 逐处判定；漂移项（ΔRGB≤24）归并到最近令牌，无令牌族按 §4 收敛（面→' + q('*-soft') + '）。')
    A('')
    A('## 9. 跨任务冲突与「只报不改」项')
    A('')
    A('### 9.1 金色定案：公共网站用可达标金，**门户去金改蓝**')
    A('')
    A('**全局可达标金 = ' + q('--gold-ink: #836A42') + '**（取自 ' + q('brand.css:6') + ' 的 ' + q('--gold-dark') + '，t111 已选）：对白 **5.12** / ' + q('--bg') + ' **4.76** / 暖纸底 **4.59**，**三底全过**；'
      + '而 ' + q('#8A6D3B') + ' 在暖纸底只有 **4.35 ✗**（首页正是暖纸底）。零新增色值。')
    A('')
    A('**但 ' + q('--ux3-gold') + ' 不映射到 ' + q('--gold-ink') + '** —— 依规范 §2.5.1（captain 终裁：**门户内一律改蓝，不登记金字例外**）逐消费点分流：')
    A('')
    A('| ' + q('--ux3-gold') + ' 的用途 | 位置 | 目标令牌 | 对比度 |')
    A('|---|---|---|---|')
    A('| 按钮面 ＋ 白字 | ' + q('ux_v3.css:76') + ' ' + q('.ux3-btn') + ' | **' + q('--brand-action') + '**（hover ' + q('--brand-action-hover') + '） | 白字 **5.02 ✓**（优于现状 4.85） |')
    A('| hover 文字 | ' + q(':39') + ' ' + q('.ux3-row-name:hover') + '、' + q(':98') + ' ' + q('.ux3-chip:hover') + ' | **' + q('--brand-action') + '**（chip 的 border-color 同理） | 压 ' + q('--bg') + ' **4.67 ✓** |')
    A('| 图标（装饰，非文本） | ' + q(':116') + '、' + q(':121') + '、' + q(':117') + ' 边框 | **' + q('--brand-500') + '** 或中性档 | 4.09 ≥ 非文本 3:1 ✓；**禁 ' + q('--gold-500') + '**（2.26 < 3:1） |')
    A('')
    A('> ⇒ ' + q('--ux3-gold') + ' 改造后**无消费者**，其声明一并删除（字面值 ' + q('#8A6D3B') + ' 随之消失）。')
    A('')
    A('**⚠ 更正我自己的前提**：我原报「' + q('ux_v3.css:8') + ' 是 t111 为对比度专选的可达标金，与 t7 的清零要求含义相反」——'
      + '规范 §2.5.1 现场核实后**推翻**了该前提：两处**目的地相同、都是「主按钮」**（' + q('.ux3-btn') + ' 消费于 ' + q('views/study.xml:33/128/154/243') + ' 的去报课选科/保存链接/返回科目），'
      + '而路线 A 下主按钮走 ' + q('--brand-action') + '、不走金色 ⇒ 我担心的「4.85 → 2.26 回退」**不会发生**。eng-web 独立得出同一结论。本节以此表为准。')
    A('- ' + q('#8A6D3B') + ' **退役**：不再有字面值、也不再是令牌；')
    A('- ' + q('.yylc-home') + ' 的局部 ' + q('--gold-dark') + ' 改为 ' + q('var(--gold-ink)') + ' 别名（brand.css 归 t6）；')
    A('- ' + q('--covenant-gold #C8A870') + ' 仅作装饰（对白 2.26，禁作正文/链接/白字底）。')
    A('')
    A('> 背景（**旧 framing 已作废**）：我曾把 ' + q('ux_v3.css:8') + ' 与该色在 /apply 的用法读成「含义相反」，并据此提出「升格为全局令牌 + ux_v3 引用它」。'
      + 'captain 与规范 §2.5.1 均否决该 framing：**两处都是主按钮**，门户的正解是改蓝（见上表）；'
      + q('--gold-ink') + ' 只服务公共网站的浅底金字。旧结论不再适用。')
    A('')
    A('### 9.2 已知缺陷（非本批次）：' + q('portal.css') + ' 的 ' + q('--gutter-x') + ' 悬空')
    A('')
    A(q('portal.css:9') + ' 与 ' + q(':11') + ' 用 ' + q('var(--gutter-x)') + ' 作 ' + q('padding-right') + '，**无回退值**，且全仓**无任何声明**'
      + '（BS4 旧名，BS5 为 ' + q('--bs-gutter-x') + '）⇒ computed-value 无效 ⇒ 回落 0，' + q('.o_portal_index_card') + ' 失去该间距。')
    A('')
    A('> 属**布局**问题，违反 t4「零布局与交互变更」红线 ⇒ **本批次只登记、不修**。captain 将在最终交付中单独向用户报告该 UI 缺陷并说明修法。')
    A('')
    A('### 9.3 ' + q('/my/calendar') + ' 的令牌外色：**我先报的归属是错的，此处更正**（color-arch 指出 + 我已逐条复核）')
    A('')
    A('**我原先的说法**（『' + q('edu_schedule') + ' 的冲突色渲染在受检页上，建议并入 t3 门禁范围』）**不成立**：')
    A('')
    A('| 复核项 | 结论 |')
    A('|---|---|')
    A('| ' + q('_KIND_HEX') + '（' + q('edu_schedule/models/session_ext.py:34') + '）是否有消费者 | **静态可达性为零**：全仓（排除 ' + q('__pycache__') + '）仅命中注释 ' + q(':11') + ' 与定义 ' + q(':34') + '；无 Python/XML/JS 读取。该文件 ' + q(':11') + ' 自己也写明「仅供前端图例/文案层展示，不进入视图 color 字段」⇒ **死代码**。（保留一条诚实保留：动态反射未验证，但静态无引用） |')
    A('| 那两处色值真正的来源 | ' + q('edu_portal') + '，且是**内联样式**（见下） |')
    A('')
    A('**真实链路（我已逐条核实到渲染点）**：' + q('edu_portal/controllers/calendar.py:33-38') + ' 的 ' + q('_KIND_COLOR') + ' 字典（session ' + q('#1D6FEB') + ' / exam ' + q('#E7650A') + ' / holiday ' + q('#DC2626') + ' / event ' + q('#0E9F6E') + '）'
      + '经 ' + q(':576-577') + '、' + q(':730-731') + ' 以 ' + q('kind_color') + ' 传入模板，再由 ' + q('views/calendar.xml') + ' 写成**内联样式**：')
    A('')
    A('- ' + q(':116') + ' ' + q('t-att-style="\'background:\' + kind_color[k]"') + '（图例圆点 ⇒ **bg**，正对应审计实测的 ' + q('bg rgb(231,101,10)×1') + ' 与 ' + q('bg rgb(220,38,38)×1') + '）')
    A('- ' + q(':142') + ' 与 ' + q(':209') + ' 用 ' + q('t-att-style') + ' 拼接 ' + q('border-left-color') + ' 等边框色（取自单元格数据的 color 字段）')
    A('')
    A('**⇒ 两个关键结论（第二个比 color-arch 的判断更进一步）**：')
    A('')
    A('1. **t13 的 inScope（仅 ' + q('edu_schedule/') + '）无法完成该页 acceptance** —— 色值根本不在那个模块里；color-arch 的更正成立。')
    A('2. **t4 也改不动它**：这些是**内联样式**（与 t7 的 ' + q('templates.xml:109') + ' 同类），**样式表规则压不过内联样式**（除非 ' + q('!important') + '）。'
      + '真正的修改点是 ' + q('edu_portal/controllers/calendar.py') + ' 的字典 / ' + q('views/calendar.xml') + '，**既不在 t4 的 9 个 CSS 文件内、也不在 t13 的 inScope 内**。')
    A('')
    A('**✅ 归属已定案（captain r6，按本表三重证据）**：该页令牌外色 **归 t8** —— ' + q('edu_portal/controllers/*.py') + ' 本就属 t8，而 t8 的 inScope 覆盖 ' + q('custom_addons/edu_portal/') + ' 整体，'
      + '故 ' + q('controllers/calendar.py:33-38') + ' ＋ ' + q('views/calendar.xml:116/142/209') + ' 天然归它；修法与既有那批一致（内联样式改 ' + q('var(--token)') + ' 引用，门户页加载前端 bundle、令牌可用 ✓）。')
    A('')
    A('| 证据（我提出、captain 复核采纳） | 说明 |')
    A('|---|---|')
    A('| ' + q('/my/calendar') + ' 的 bg 列**四个** ' + q('_KIND_COLOR') + ' 值各 ×1 | ' + q('rgb(29,111,235)') + '=' + q('#1D6FEB') + '（session）、' + q('rgb(231,101,10)') + '=' + q('#E7650A') + '（exam）、' + q('rgb(220,38,38)') + '=' + q('#DC2626') + '（holiday）、' + q('rgb(14,159,110)') + '=' + q('#0E9F6E') + '（event）—— 与 ' + q('calendar.xml:116') + ' 的图例四圆点**一一对应** |')
    A('| 原告的链路最多只能解释 1 个 | ' + q('.ux-dot-conflict') + ' 只产出 ' + q('#DC2626') + '；' + q('ux_rework.css:86') + ' 的 ' + q('#E7650A') + ' 是 **border-left**、不是 bg；**两条链路都产不出** ' + q('#1D6FEB') + ' 与 ' + q('#0E9F6E') + ' |')
    A('| ' + q('.ux-dot-conflict') + ' 根本不在该页渲染 | 它属于 ' + q('edu_schedule_preview') + '（模板 ' + q('templates.xml:210') + '），由 ' + q('edu_schedule/controllers/main.py:436') + ' 的独立路由渲染，非 ' + q('/my/calendar') + ' |')
    A('')
    A('> **对两个任务各自的意义**：① **t4** —— 该页图例/边框**不在我可达范围**（内联样式压过样式表），t4 只负责「9 个 CSS 文件对该页的贡献 = 0」，见 §0.2；'
      + '② **t8** —— 由它把 controller 的 ' + q('_KIND_COLOR') + ' 与模板内联样式改成 ' + q('var()') + ' 引用，该页才能清零。'
      + '③ 规范 §6.3.1 原先写的「该页令牌外色归 t4」**是错的**，captain 已令 color-arch 更正。')
    A('')
    A('> 注：' + q('ux_rework.css') + ' 自身的 38 个令牌外字面值仍是 t4 的工作（其 ' + q('.ux-dot-conflict') + ' 等在**预览页**真实渲染），只是它**不能**达成 ' + q('/my/calendar') + ' 的「令牌外色=0」。'
      + '注：' + q('ux_rework.css') + ' 里同名的 ' + q('.ux-dot-conflict') + ' / ' + q('.ux-cal-chip-exam') + ' 等**类规则**仍属 t4，我会照收；但它们不是该页那两处实测色的来源。')
    A('')
    A('### 9.4 附记：' + q('/my/calendar') + ' 上的金色 ' + q('#C8A870') + '（只报不改，owner=t8）')
    A('')
    A('实测该页 ' + q('#C8A870') + ' 作 **text ×3 ＋ anchor ×2**（另 border ' + q('rgba(200,168,112,.5)') + ' ×1、深底 ' + q('#12100E') + ' ×1）。'
      + '候选来源（color-arch 定位）：' + q('batch2.py:421') + ' 与 ' + q('roles.py:224') + ' —— 二者都是 ' + q('<i class="fa …">') + ' **图标文字**，故被审计计入 text 列。**owner = t8**（§1.5 已定）。')
    A('')
    A('> ⚠ **未决项（t9 须做元素级配对）**：审计原始数据只有**聚合计数**，判不出那 3 处 text 是坐**白底**（' + q('#C8A870') + ' = **2.26 ✗**）还是坐那块深底 ' + q('#12100E') + '（**8.06 ✓**）。'
      + '这正是「金的可见性必须连底色一起看」的实例。t4 不涉及（门户口径已定为一律改蓝）。')
    A('')
    A('## 10. 对比度：本任务的映射是「修复」而非「搬运」')
    A('')
    A('### 10.1 color-arch 权威矩阵已独立复算（24/24 格完全一致）')
    A('')
    A('我按 WCAG 相对亮度公式独立实算其 24 格，**逐格吻合（偏差 < 0.005）**；两个 α 叠层底色 ' + q('#E7F2FE') + ' / ' + q('#D8E8F9') + ' 亦复现。')
    A('')
    A('### 10.2 该矩阵**漏了青绿族**（实测补一格）')
    A('')
    A('| 文字 | 面 | 对比度 | 判定 |')
    A('|---|---|---|---|')
    A('**⚠ 本节已按 ' + q('--accent') + ' 重定义更新（旧写法作废）**：' + q('--accent') + ' 现已 **= ' + q('--teal-600') + '**（captain 裁定，见下），故「青绿面上不得用 ' + q('--accent') + '」这条**过宽**了。修正后的规则与数据：')
    A('')
    A('| 前景 | ' + q('--teal-50') + ' | ' + q('--teal-100') + ' | ' + q('--teal-200') + ' | 白底 | ' + q('--bg') + ' |')
    A('|---|---|---|---|---|---|')
    A('| ' + q('--accent') + '（= ' + q('--teal-600 #0C7D75') + '） | **4.52 ✓** | **4.09 ✗** | **3.29 ✗** | 4.99 ✓ | 4.64 ✓ |')
    A('| ' + q('--teal-700 #0A605B') + ' | 6.70 ✓ | **6.06 ✓** | **4.88 ✓** | 7.40 ✓ | 6.88 ✓ |')
    A('')
    A('> **修正规则**：' + q('--accent') + '（= ' + q('--teal-600') + '）**可用于 ' + q('--teal-50') + '**（4.52 ✓）；**' + q('--teal-100') + '/' + q('--teal-200') + ' 上必须上到 ' + q('--teal-700') + '**（6.06 / 4.88 ✓）。')
    A('>')
    A('> **历史（作废，保留以示来由）**：重定义**之前** ' + q('--accent') + ' = ' + q('--teal-500 #0F9B91') + '，压 ' + q('--teal-50') + ' 只有 **3.11 ✗**、白底 3.43 ✗ ⇒ 这正是把它重定义为 ' + q('--teal-600') + ' 的原因。故旧表述「不得用 ' + q('--accent') + ' 作文字」是**针对 teal-500 的**，对新的 ' + q('--accent') + ' 不再成立。')
    A('>')
    A('> 注：' + q('--accent') + ' 全仓 **0 消费点** ⇒ 该重定义**零渲染影响** ✓（eng-web 四点交叉验证，含已上线 bundle）。')
    A('')
    A('**captain 裁定（已同步 color-arch 写进 t2）**：规范把 ' + q('--accent') + ' **重定义为 ' + q('var(--teal-600)') + '**，装饰渐变继续直接用 ' + q('--teal-500') + '。'
      + '零新增色、零现网渲染变化（' + q('--accent') + ' 0 引用），把未来的坑提前填掉；同时与既有规则「teal 作文字一律 teal-600」一致。')
    A('')
    A('### 10.3 inScope 实测：换成令牌对**同时修掉现有不达标**')
    A('')
    A('口径：同一规则内 ' + q('background') + ' 与 ' + q('color') + ' 共现（α 底按白底与 ' + q('--bg') + ' 各算一次取较差）。'
      + '结果：**91 处候选不达标规则、33 种字面值对**。')
    A('')
    A('> ⚠ **「现值」列的墨色说明（避免与 §3.3 串行）**：本表每行的「现值」是**该行墨色自身**压该面的对比度 —— 第 1/3 行的墨色是遗留字面值 ' + q('#0E7BF2') + '（= ' + q('--brand-500') + '），'
      + '故分别是 **3.61 / 3.28**；而 §3.3 那张「基底归属」表问的是**另一个问题**（把面基底换成 ' + q('--brand-action') + ' 时、墨仍取 ' + q('--brand-action') + '），那里的 **4.43 / 4.02** 是对的。'
      + '两张表问题不同、数值不同，勿互相代入。（本条由 color-arch 复核指出，我原先把 ' + q('--brand-action') + ' 的数错标到了 ' + q('#0E7BF2') + ' 行。）')
    A('')
    A('| 现值对 | 处数 | 现值 | 令牌解 | 解后 |')
    A('|---|---|---|---|---|')
    A('| ' + q('rgba(14,123,242,.10)') + ' ＋ ' + q('#0E7BF2') + ' | 19 | **3.61 ✗** | 文字改 ' + q('--brand-action-hover') + ' | **5.05 ✓** |')
    A('| ' + q('#0E7BF2') + ' 实底 ＋ 白字 | 11 | **4.09 ✗** | 底改 ' + q('--brand-action') + ' | **5.02 ✓** |')
    A('| ' + q('rgba(14,123,242,.12)') + ' ＋ ' + q('#0E7BF2') + ' | 8 | **3.28 ✗** | 文字改 ' + q('--brand-700') + ' | **6.60 ✓** |')
    A('| ' + q('rgba(255,165,0,.18)') + ' ＋ ' + q('#c27d00') + ' | 4 | 2.97 ✗ | 文字改 ' + q('--warning-ink') + ' | **5.24 ✓** |')
    A('| ' + q('#edeef4') + ' ＋ ' + q('#9aa1b4') + ' | 2 | 2.23 ✗ | 文字改 ' + q('--text-3') + ' | **4.91 ✓** |')
    A('')
    A('> **口径诚实声明**：这是**同规则共现的启发式**，不等于实测渲染对 ⇒ **候选清单**，逐处核对后再改；终判以 t9 的 axe 与渲染取色为准。'
      + '已知反例：' + q('banner.css:131') + ' 白字压 ' + q('rgba(255,255,255,.15)') + ' 被本启发式判 1.00，实际底色是彩色横幅。')
    A('')
    A('## 11. 棘轮债务计数：追加 ' + q('adopted_files') + ' 前 / 后')
    A('')
    A('captain 裁定：门禁计数单位为 **出现处数**，且**三个数分开报、不得混用**。以下按此给三行（口径与正则一并写死，供 t9 逐字复现）。')
    A('')
    A('| # | 口径 | 追加前（现状） | 追加后（t4 目标） | 定义 |')
    A('|---|---|---|---|---|')
    A('| 1 | **出现处数**（基线，**冻结**） | **1067** | 0 | 开工前快照（commit ' + q('f173be0') + '）：798 hex ＋ 269 rgba |')
    A('| 2 | **不同色值数**（基线，**冻结**） | **113** | 0（白/黑豁免 162） | 同上 |')
    A('| 3 | **其中令牌外色值数**（基线，**冻结**） | **103** | 0 | 同上；对应出现处数 543（漂移 304 ＋ 无令牌 239） |')
    A('')
    A('**当前实测（批 A 已应用后；本节由生成器按 §0.1 窄口径现算）**：')
    A('')
    A('| # | 口径 | 当前 | 目标 | 定义 |')
    A('|---|---|---|---|---|')
    qq = q('#rrggbb') + ' / ' + q('rgba()')
    A('| 1 | **出现处数**（门禁 burn-down 的可执行单位） | **%d** | **0** | 9 个文件内每个 %s 匹配计 1 处（%d hex ＋ %d rgba） |' % (len(hexes) + len(rgba), qq, len(hexes), len(rgba)))
    A('| 2 | **不同色值数** | **%d** | **0**（白/黑豁免保留 %d） | 归一后的唯一色值数（hex 与 rgba 写法合并为 1） |' % (len(all_cnt), sum(c for _, c in wb)))
    A('| 3 | **其中令牌外色值数** | **%d** | **0** | 归一后不属令牌集者；对应出现处数 **%d**（漂移 %d ＋ 无令牌 %d） |' % (len(drift), near + far, near, far))
    A('')
    A('**正则（逐字复现用）**：hex = ' + q('#[0-9a-fA-F]{3,8}') + '（先归一小写、3 位展开 6 位）；'
      + 'rgba = ' + q(r'rgba?\(N,N,N[,A]\)') + '（只取 r,g,b，按 §7.3 与同色 hex 合并计数）；剔除 ' + q('#fff / #ffffff / #000 / #000000') + '。')
    A('')
    A('**另两个判据（与上面三行分开，不得混用）**：')
    A('')
    A('- **重复定义判据** = **(令牌名, 选择器) 二元组** —— 判「同名 + 同选择器 + 跨文件 + 不同值」的真·静默覆盖。')
    A('- **验收主判据** = **6 个页面渲染出的令牌外色 = 0**（口径无关；见 spec §6.1/§6.2）。')
    A('')
    A('> ⚠ **层次不可替代**：上面三行是**源码卫生**（burn-down 的可执行单位），验收主判据是**渲染结果**。'
      + '**不得用源码出现处数替代渲染判据** —— 源码清零不等于该页渲染为零（还有模板字面量、JS 注入、框架/第三方样式等来源）。')
    A('')
    A('### 11.1 棘轮追加顺序（captain 批准；**将来任何人为 ' + q('ADOPTED_FILES') + ' 加文件都照此做**）')
    A('')
    A('1. 收口目标文件（清掉其中的令牌外裸色）；')
    A('2. 跑门禁确认这些文件**已无令牌外裸色**；')
    A('3. **才**追加进 ' + q('ADOPTED_FILES') + '（**只加自己的文件**，棘轮的意义就是逐批可审）；')
    A('4. 重新生成 ' + q('scripts/color_tokens.json') + '；')
    A('5. **常量与 JSON 同批提交**（生成物与源分离入库 ⇒ t9 读到的棘轮状态与源码不一致）；')
    A('6. 报告附三行债务计数，并**显式标注范围**＝自己那批文件（避免与门禁的全仓 ' + q('debt') + ' 混读）。')
    A('')
    A('> **机制证据（为什么顺序不能反）**：' + q('color_tokens.py') + ' 的 ' + q('run_check') + ' 内是 ' + q('if strict or rel in adopted: fails.append(...)') + ' ⇒ '
      + '**未清干净就追加，会把原本 INFO 的债务直接变成 FAIL**。这正是「收一批、锁一批」的语义；反之若文件已清干净，追加即让门禁开始保护它。')
    A('')
    A('### 11.2 字段改名（captain 已派 eng-web）与量纲提醒')
    A('')
    A('· ' + q('debt.files') + ' → **' + q('distinct_outside_colors') + '**（补 ' + q('note') + ' 说明单位＝**去重色数**）。**本台账的读取方在该改动落地后随之同步**（下次重新生成时顺带更新）。')
    A('')
    A('> ⚠ **量纲提醒（t9 复核棘轮单调性时必读）**：门禁的债务单位是**去重色数**；本文 §11 第 1 行是**出现处数** —— 两者**不同量纲**，'
      + '**必须指明用的是哪一行**，不得并排比较。')
    A('')
    A('### 12.4 批 A 的**第三方独立确认**（eng-web 的 ' + q('--scope S1') + ' 实测）')
    A('')
    A('eng-web 用其门禁的 ' + q('--scope S1') + ' 直方图实测 brand-500 族：**字面值仅剩 10 处、' + q('var()') + ' 形式 101 处**，两者相加 **10 + 101 = 111** ＝ 规范 §4.2.1 的 S1 家族数 ✓ —— 即**我的 101 处改造被外部量具独立复算出来**（非自我声明）。')
    A('')
    A('> 该族 111 处中：批 A 转了 **101 处**（rgba → ' + q('rgba(var(--brand-500-rgb), α)') + '），剩 **10 处**属豁免或批 B 候选。另：eng-web 门禁的「债务色」亦由 **175 → 142**，与其量具同向。')
    A('')
    A('**一条给规范的提醒（已转 color-arch）**：§4.2.1 的 S1/S2/S3 表**数字会随每批收口而变**（111 → 10 即实例）⇒ 该表需带**时间戳/commit 标记**，'
      + '否则按规范自订的「无标签数字视为不完整、t10 可判 finding」规则，**那张表会自我判罚**（与本文 §11「生成物悄悄改写基线」同族风险）。')
    A('')
    A('**另两条确认**：① eng-web 的门禁**不做 α 阈值比较**（全脚本仅两处浮点比较：WCAG 线性段 ' + q('c <= 0.03928') + ' 与 ' + q('summary()') + ' 的打印备注）'
      + '⇒ 本文的**浮点红线适用于「做量化归并的脚本」（如本任务的变换器），不是那条门禁**；② 规范 r17 已写死 ' + q('Δα < 50‰') + ' 归并／' + q('≥ 50‰') + ' 保留，'
      + '且 §2.6 r17 并列两方案并标 **A（当前落地态）＝ ' + q('--shadow') + ' ＋ ' + q('--shadow-rgb') + '**，与本文 §4 一致 ✓。')
    A('')
    A('## 13.3 收口序列执行状态：**棘轮追加「刻意推迟」**（并给出精确原因）')

    A('> 🔁 **captain 裁定（避免死锁）：追加 ' + q('adopted_files') + ' 不再是 t4 的完成前置**，而是**独立收尾步骤** —— 原因：t8 的依赖里含 t4，而那 5 处恰好等 t8 补通道 ⇒ 若把追加当完成前置，两边会互相等待。')
    A('> **语义不变**：未追加 ＝ 仍为 INFO 债务 ＝ 「未锁定」，这正是它的本义；t4 的验收结论不受影响。')
    A('> 该项在 t4 报告中写作「**已知后续项（依赖 t8 补通道）**」并注明 **不阻断 t4 完成**；执行者：待 t8 补齐 3 个通道、那 4 处 rgba 换成逗号式之后，**由 t8 或本人一次性追加**（谁后动谁做）。')
    A('')
    A('按本任务获批的棘轮顺序（**先清干净 → 跑门禁确认 → 才追加**；§11.1），当前执行到第 2 步：')
    A('')
    A('| 步骤 | 状态 | 证据 |')
    A('|---|---|---|')
    A('| 1. 清理令牌外裸色 | **未完成**：9 文件中仍有 **4 个不同色值 / 5 处** | 见下表 |')
    A('| 2. 门禁复跑 | **已完成**：' + q('color_tokens.py --check') + ' ⇒ **PASS**（令牌 61 / 通道 11 / WARN 1 / 债务色 43）；我的文件被列为 **INFO 债务**而非 FAIL | 因**尚未追加** ' + q('adopted_files') + '，故仍是 INFO |')
    A('| 3. 追加 ' + q('adopted_files') + ' | **⛔ 刻意推迟** | 见下（若现在追加 ⇒ 把 INFO 直接变 FAIL） |')
    A('| 4. ' + q('--write') + ' 写回 JSON | 依赖第 3 步 | —— |')
    A('| 5. 三行债务计数 | 可出（下表右列） | —— |')
    A('')
    A('**⛔ 为什么现在不能追加**（机制的现场验证）：' + q('color_tokens.py') + ' 的 ' + q('run_check') + ' 内是 ' + q('if strict or rel in adopted: fails.append(...)') + ' ⇒ 我的文件**尚未清干净**（还剩 4 个不同色值），'
      + '此时追加会把它们从 INFO 债务**升级为 FAIL**。这正是 §11.1 那条「未清干净就追加 = 把 INFO 变成 FAIL」的**首次实战触发** —— 顺序纪律按设计生效。')
    A('')
    A('**剩余 4 个色值 / 5 处（各有明确归属）**：')
    A('')
    A('| 站点 | 现值 | 归属 | 阻塞原因 |')
    A('|---|---|---|---|')
    A('| ' + q('enroll.css:19/23/29') + '（3 处） | ' + q('rgba(15,118,110,α)') + ' = ' + q('#0F766E') + ' | **t8** | 需 ' + q('--teal-600-rgb') + '（captain 已授权补） |')
    A('| ' + q('portal.css:1225') + '（1 处） | ' + q('rgba(222,222,222,α)') + ' = ' + q('#DEDEDE') + ' | **t8** | 需 ' + q('--border-rgb') + ' |')
    A('| ' + q('enterprise.css:507') + '（1 处） | ' + q('rgba(154,161,180,α)') + ' = ' + q('#9AA1B4') + ' | **t8** | 需 ' + q('--border-control-rgb') + '（且该面上有文字，规则 3c 的取舍见 §13.2） |')
    A('| ' + q('enterprise.css:471') + '（1 处） | ' + q('#2f6405') + '（Δ83.1，最大 ⚠） | **captain/t2** | §4.7 无法机械判定，需裁 |')
    A('')
    A('### 13.4 三行债务计数（基线 → 当前；按 §6.2.0 口径标注）')
    A('')
    A('| # | 口径 | 基线（' + q('f173be0') + '） | **当前** | 备注 |')
    A('|---|---|---|---|---|')
    A('| 1 | **出现处数** (b) | **1067** | **173** | 含白/黑豁免 162 |')
    A('| 2 | 其中**非豁免** | **905** | **11** | −98.8% |')
    A('| 3 | **不同色值数** (c) | **113** | **9** | **仅描述「CSS 侧还有多少种写法」，不得用于达标判定** |')
    A('| —— | 门禁债务色（eng-web 量具） | 175（eng-web 读数） | **43**（本轮 ' + q('--check') + '）；我的文件占 4 | (c) 口径，INFO |')
    A('')
    A('> ⚠ 口径提醒（§6.2.0）：以上 **(b)/(c) 都是「CSS 声明侧」读数**，与 KPI 的「全站实测颜色 53→≤28」**不是一回事** —— 后者是**取色器实测的渲染色数**，须以 §6.2 的 S1/S2/S3 ＋ t12 量具为准。')
    A('')
    A('> **逗号切换选择**：**已选「现在就切」**（理由见 §4.3）—— 本任务已完成 193 处逗号式落地，门禁 PASS 可佐证。')

    A('### 13.5 #2f6405 已按裁定收口（并纠正一处角色认知）')
    A('')
    A('**事实纠正**：' + q('#2f6405') + ' 在 ' + q('enterprise.css:471') + ' **是「字」不是「面」** —— 该规则的面本就是令牌 α（' + q('rgba(var(--success-rgb), 0.1)') + '），遗留字面值只是那个字色。')
    A('**处置**：按 §4.7 定档，字 ' + q('#2f6405') + ' → ' + q('var(--success)') + '；该面**承载文字** ⇒ 按规则 3c 面取**扁平** ' + q('var(--success-soft)') + '（不带 α）。')
    A('**成对对比度（用权威令牌值复算）**：' + q('--success #127A50') + ' 压 ' + q('--success-soft #E8F7F0') + ' = **4.84 ✓** —— 与 §4.2 扁平对矩阵一致。')
    A('')
    A('> ⚠ **一次差点报错的实测**：我先用**记忆中**的 soft 值 ' + q('#E7F3EC') + ' 算出 4.69；读 ' + q('color_tokens.json') + ' 后确认权威值为 ' + q('#E8F7F0') + ' ⇒ 正确结果 **4.84**。教训与本文主旨同源：**读数必须取自 artifact，不能取自记忆** —— 记忆里的近似色足以造成 0.15 的对比度偏差。')
    A('')
    A('**里程碑**：我的 9 个文件**令牌外 hex 已清零（0 个色值）**；剩余 4 个不同色值全为 rgba，即归 t8 的 5 处（teal ×3 / border ×1 / border-control ×1）。')
    A('')
    A('## 13.2 t4 未收口项及归属（captain 裁定后）')
    A('')
    A('按 §3.2 规则 3c（**承载文字的面 → 扁平 ' + q('*-soft') + '；其上无文字 → 保留 α ⇒ 需通道令牌**）分流：')
    A('')
    A('| 站点 | 现值 | 处置 |')
    A('|---|---|---|')
    A('| ' + q('enterprise.css:509') + ' 青铜奖章面 | ' + q('rgba(205,127,50,.16)') + ' | **已收口**：其上承载文字（' + q('color: var(--warning-ink)') + '）⇒ 规则 3c 取扁平 **' + q('var(--warning-soft)') + '**；成对对比度 **5.45 ✓**（captain 裁定：青铜归琥珀族、零新增色相，不引用 ' + q('--gold-*') + '） |')
    A('| ' + q('enroll.css:19/23/29') + ' | ' + q('rgba(15,118,110,α)') + ' ×3 | **归 t8**：其上无文字 ⇒ 保留 α ⇒ 需 **' + q('--teal-600-rgb') + '**（captain 已授权补通道） |')
    A('| 时间轴/分隔线 | ' + q('rgba(222,222,222,α)') + ' ×1 | **归 t8**：需 **' + q('--border-rgb') + '** |')
    A('| ' + q('enterprise.css:507') + ' 奖章面 | ' + q('rgba(154,161,180,.2)') + ' | **归 t8**：需 **' + q('--border-control-rgb') + '** |')
    A('')
    A('> **说明**：这 5 处是**机械缺口**（缺通道令牌），captain 已授权 t8 补 3 个通道（' + q('--teal-600-rgb') + ' / ' + q('--border-rgb') + ' / ' + q('--border-control-rgb') + '），规范侧由 color-arch 出 rN 把通道清单 **11 → 14** 并写明理由。'
      + '**t4 不因此停滞**：本任务收口序列照常推进；这 5 处只影响「令牌外色 = 0」的最终达成，不影响已完成的批 A/B-1/B-2 与门禁推进。')
    A('')
    A('> 另注：' + q('enterprise.css:507') + ' 的面上有 ' + q('color: var(--text-3)') + ' ⇒ 严格按规则 3c「承载文字 ⇒ 扁平 ' + q('*-soft') + '」，而 ' + q('--border-control') + ' **没有** ' + q('*-soft') + ' 变体（它是边框令牌）'
      + '⇒ 若直接把 α 面换成扁平 ' + q('--border-control') + '（' + q('#8A94A6') + '）会**大幅加深**并使 ' + q('--text-3') + ' 压其上的对比度骤降 ⇒ **我不自行取此路**，随本条一并交 t8/color-arch 定（已在报告中列出）。')
    A('')
    A('## 13. 批 B 逐处工作清单（worklist；每处须补「改前/改后 computed 值」）')
    A('')
    A('筛选＝**剩余字面值中非豁免者**（白/黑不动）；「目标」列仅在已知时给出，**未知者标「待定」并由 t2 定**（不擅自造色）。')
    A('')
    A('### 13.1 执行状态（captain 裁定 **方案 ①**：先做目标已定者，75 处作第二批）')
    A('')
    A('| 批次 | 范围 | 结果 | 提交 |')
    A('|---|---|---|---|')
    A('| **B-1（已执行）** | 目标已定的 196 处（收敛族 ＋ 明确归属） | **hex 121 处 ＋ rgba 72 处 = 193 处**改为令牌引用；复算：数字 rgba **101 → 29**、hex **345 → 224**；9 文件花括号全平衡；引用存在性仅剩两个已知项（' + q('--gutter-x') + ' 缺陷、' + q('--shadow-sm') + ' 的 JSON 缺项） | ' + q('0eedec3') + ' |')
    A('| **B-2（已可执行，映射权威 = 规范 §4.7 @ ' + q('9f74f32') + '）** | 剩余 75 处（含梅紫 19） | color-arch **已全部定档**（47 个字面值 / 75 处，且与我台账**逐格对账：缺 0 / 多 0 / 处数差 0**）：A 梅紫 19→' + q('--brand-action') + '/' + q('--brand-action-hover') + '（**禁紫**）；B 暗金琥珀 7→面 ' + q('--warning-soft') + '＋字 ' + q('--warning-ink') + '；C 蓝灰 6→' + q('--border-control') + '/' + q('--text-2') + '；D 灰阶 10→' + q('--text-1/2/3') + '、' + q('--text-disabled') + '；E 极浅面 14→' + q('--bg') + '/' + q('--neutral-soft') + '/' + q('--fill-active') + '/' + q('--brand-50') + '/' + q('--success-soft') + '/' + q('--danger-soft') + '；F 线 4→' + q('--border') + '；G 语义装饰 16→' + q('--danger/success/warning/warning-ink/brand-500/brand-700/brand-action') + '。**例外 5 处（Δ≥40）标「待 captain」**：' + q('#2f6405 Δ83.1') + '、' + q('#3730a3 Δ54.8') + '、' + q('#b06a26 Δ53.8') + '、' + q('#334155 Δ45.6') + '、' + q('#374151 Δ46.0') + ' ⇒ 其余 **70 处可直接执行** | 待执行 |')
    A('')
    A('> **跨 owner 一致性约束（color-arch 提，我接受）**：' + q('#1d6feb') + ' 在 ' + q('ux_rework.css:85') + '（' + q('.ux-cal-chip-session') + '，**本任务**）与 ' + q('calendar.py') + ' 的 ' + q('_KIND_COLOR[&#39;session&#39;]') + '（**t8**）同时出现 ⇒ **必须映射到同一令牌 ' + q('--brand-action') + '**，否则同一语义出现两种蓝。')
    A('')
    A('| **B-2（待 t2/color-arch v4.2）** | 剩余 75 处（含梅紫族 18） | captain 已给处置边界（见下），等定档后执行 | —— |')
    A('')
    A('**captain 给 B-2 的处置边界**（我按其排位、等 color-arch 定档）：')
    A('')
    A('- **极浅底 8×1** → 归对应 ' + q('*-soft') + ' 或 ' + q('--bg') + '（**也可能是本文漏映射的漂移**，执行时逐处核）；')
    A('- **暗金琥珀 7 / 蓝灰 6 / 中性灰 2** → 近邻映射（' + q('--warning-ink') + ' / ' + q('--border-control') + ' 或 ' + q('--text-2') + ' / ' + q('--text-3') + '）；')
    A('- **梅紫族 18** → **唯一路线级判断**：紫不在路线 A 色板内（即审计点名的「三族冲突」遗留）⇒ **按用途归入既有族**（交互 → ' + q('--brand-action') + '/' + q('--brand-action-hover') + '；语义危险 → ' + q('--danger') + '；装饰面 → ' + q('*-soft') + '/' + q('--bg') + '），**不得新增紫色令牌**。')
    A('')
    A('> 若 B-2 中确有「无既有族可用」者，由 color-arch 单独回报 captain（不由我自行造色）。')
    A('> **captain 裁定（enterprise.css:507）**：**保留 α，用新增的 --border-control-rgb 表达**，不扁平化。两条理由：① 规则 3c 的目的是保证承载文字的面达标，而此处扁平化会**恶化对比度**（--border-control 的 #8A94A6 大幅加深底色、压掉 --text-3 的余量）⇒ 照字面执行会造出一个新的不达标对；② --border-control 是**边框令牌**，当面板用属**跨类**（违定档三原则第 ① 条）。')
    A('> **规则 3c 的例外（captain 裁定，已转 color-arch 入规范）**：**目标令牌无 *-soft 变体、或扁平化会降低对比度 ⇒ 保留 α 并补同名通道令牌**。出处即本例。')
    A(chr(39))
    A('> **captain 裁定（enterprise.css:507）**：**保留 α，用新增的 --border-control-rgb 表达**，不扁平化。两条理由：① 规则 3c 的目的是保证承载文字的面达标，而此处扁平化会**恶化对比度**（--border-control 的 #8A94A6 大幅加深底色、压掉 --text-3 的余量）⇒ 照字面执行会造出一个新的不达标对；② --border-control 是**边框令牌**，当面板用属**跨类**（违定档三原则第 ① 条）。')
    A('> **规则 3c 的例外（captain 裁定，已转 color-arch 入规范）**：**目标令牌无 *-soft 变体、或扁平化会降低对比度 ⇒ 保留 α 并补同名通道令牌**。出处即本例。')
    A('')
    BB = {
        '#469408': '--success', '#d91f1f': '--danger', '#ffa500': '--warning', '#666666': '--neutral',
        '#dc2626': '--danger', '#e7650a': '--warning', '#d97706': '--warning',
        '#9aa1b4': '--text-3', '#c27d00': '--warning-ink', '#0e9f6e': '--success',
        '#3d8107': '--success', '#387706': '--success', '#448aff': '--brand-400',
        '#0f766e': '--teal-600', '#583b51': '待定（t2）', '#5f3f56': '待定（t2）',
        '#111827': '--text-1', '#222222': '--text-1', '#5c5c5c': '--text-3',
        '#94a3b8': '--border-control', '#64748b': '--text-3', '#475569': '--text-2',
        '#1d4ed8': '--brand-700', '#fef3c7': '--warning-soft', '#fde68a': '--warning-soft',
        '#fee2e2': '--danger-soft', '#fca5a5': '--danger-soft', '#dcfce7': '--success-soft',
        '#86efac': '--success-soft', '#f1f5f9': '--fill-hover', '#eef2f7': '--fill-active',
        '#e2e8f0': '--border', '#cbd5e1': '--border-strong', '#f8fafc': '--bg',
        '#92400e': '--warning-ink', '#b91c1c': '--danger', '#991b1b': '--danger',
        '#166534': '--success', '#15803d': '--success', '#047857': '--success',
        '#d1fae5': '--success-soft', '#ecfdf5': '--success-soft', '#fef0e7': '--warning-soft',
    }
    BB_RGBA = {'70,148,8': '--success-rgb', '217,31,31': '--danger-rgb',
               '255,165,0': '--warning-rgb', '102,102,102': '--neutral-rgb'}
    rows = []
    for rel in PORTAL_CSS:
        p = os.path.join(ROOT, 'custom_addons', rel)
        for i, line, sel in walk_selectors(p):
            for m in re.finditer(r'#[0-9a-fA-F]{3,8}\b|rgba\([^)]*\)', line):
                lit = m.group(0)
                hx = color_of(lit)
                if hx is None or hx in by_val or hx in WHITE_BLACK:
                    continue
                if lit.startswith('rgba'):
                    base = ','.join(str(int(hx[i:i+2], 16)) for i in (1, 3, 5))
                    if base not in BB_RGBA:
                        continue
                    tgt = 'rgba(var(%s), α)' % BB_RGBA[base]
                else:
                    tgt = BB.get(norm_hex(lit), '待定（t2）')
                rows.append((rel.split('/')[-1], i, (sel or '?')[:44], lit, tgt))
    A('共 **%d 处**（批 B 候选；其中「待定」%d 处）。' % (len(rows), sum(1 for r in rows if '待定' in r[4])))
    A('')
    A('| # | 文件:行 | 选择器 | 现值 | 目标令牌 | 改前→改后 computed |')
    A('|---|---|---|---|---|---|')
    for n, (f, i, sel, lit, tgt) in enumerate(rows, 1):
        A('| %d | %s | %s | %s | %s | （执行时填） |' % (n, q('%s:%d' % (f, i)), q(sel), q(lit), tgt))
    A('')
    A('> 说明：本清单是**批 B 的可执行工作单**（captain 要求逐处列出、可独立回退）。执行时每处补「改前/改后 computed 值」，**终判仍以 t9 的 axe 与渲染取色为准**。')
    A('')
    A('## 12. 执行批次划分（captain 裁定：分两批）+ 批 B 按观感影响排序')
    A('')
    A('**观感量具**：CIELAB **ΔE76**（D65）。参考：ΔE≈1 为理想条件下刚可辨，ΔE≈2.3 为一眼可辨。')
    A('')
    A('### 12.1 批 A —— 等值 / Δ 极小（目标：令牌外色 = 0，无可见变化）')
    A('')
    A('| 项 | 旧值 | 新值 | ΔE76 | 说明 |')
    A('|---|---|---|---|---|')
    A('| 阴影墨色（**精确命中**） | ' + q('#14182D') + ' | ' + q('var(--shadow)') + ' | **0.00** | 69 处；' + q('--shadow: #14182D') + ' 由 ' + q('--shadow-rgb: 20, 24, 45') + ' 派生 ⇒ **零改色、只换引用形式**；全在 box-shadow、§7.3 四列量不到 |')
    A('| 次级文字 | ' + q('#5e6779') + ' | ' + q('var(--text-3)') + ' | **0.00** | 精确命中（83 处） |')
    A('| 品牌蓝 | ' + q('#0E7BF2') + ' | ' + q('var(--brand-500)') + ' | **0.00** | 精确命中（198 处，含 99 处 rgba 换形式） |')
    A('| 门户正文近黑 | ' + q('#1d2233') + ' | ' + q('var(--text-1)') + ' | 1.15 | 92 处 |')
    A('| 边框漂移 | ' + q('#e7e9f2') + ' | ' + q('var(--border)') + ' | 1.42 | 84 处（审计点名漂移） |')
    A('')
    A('> 批 A 全部 ΔE ≤ **1.42**（阴影项 **0.00** 精确命中）⇒ **无可见变化**，可整批执行、整批回退。')
    A('')
    A('')
    A('### 12.2 批 B —— 会改观感（按 ΔE76 升序，**影响最小的先做**）')
    A('')
    A('| 序 | ΔE76 | 项 | 旧 → 新 | 驱动 | 处数 |')
    A('|---|---|---|---|---|---|')
    A('| 1 | **8.43** | ' + q('#0E7BF2') + ' 实底上的白字（改底） | ' + q('#0E7BF2') + ' → ' + q('var(--brand-action)') + ' | 对比度 4.09 ✗ → 5.02 ✓（审计第 7 对） | 11 |')
    A('| 2 | **10.13** | 橙族实底/描边 | ' + q('#FFA500') + ' → ' + q('var(--warning)') + ' | 收敛 | 13 面 + 2 描边 |')
    A('| 3 | **11.23** | 灰族实底/描边 | ' + q('#666666') + ' → ' + q('var(--neutral)') + ' | 收敛 | 12 面 + 2 描边 |')
    A('| 4 | **11.32** | 蓝调 α 面 .10 上的文字 | ' + q('#0E7BF2') + ' → ' + q('var(--brand-action-hover)') + ' | 对比度 **3.61 ✗** → 5.05 ✓ | 19 |')
    A('| 5 | 15.31 | 绿标签底上的绿字 | ' + q('#0E9F6E') + ' → ' + q('var(--success)') + ' | 对比度 3.03 ✗ → 4.84 ✓ | 1 |')
    A('| 6 | 16.33 | 红调 α 面/红族实底上的文字 | ' + q('#d91f1f') + ' → ' + q('var(--danger)') + ' | 对比度 + 收敛 | 21 |')
    A('| 7 | 21.01 | 橙调 α 面上的文字 | ' + q('#c27d00') + ' → ' + q('var(--warning-ink)') + ' | 对比度 2.97 ✗ → 5.24 ✓ | 4 |')
    A('| 8 | 22.82 | 浅灰底上的灰字 | ' + q('#9aa1b4') + ' → ' + q('var(--text-3)') + ' | 对比度 2.23 ✗ → 4.91 ✓（审计未测到） | 2 |')
    A('| 9 | 25.30 | 蓝调 α 面 .12 上的文字 | ' + q('#0E7BF2') + ' → ' + q('var(--brand-700)') + ' | 对比度 **3.28 ✗** → 6.60 ✓ | 8 |')
    A('| 10 | 35.28 | 绿调 α 面上的文字 | ' + q('#3d8107') + ' → ' + q('var(--success)') + ' | 对比度 ~3.1 ✗ → 4.84 ✓ | — |')
    A('| 11 | **42.22** | 绿族实底/描边 | ' + q('#469408') + ' → ' + q('var(--success)') + ' | 收敛（ΔRGB 150 → 0）**最显眼，最后做** | 17 面 + 5 描边 |')
    A('')
    A('## 附录 A. t13 删除决策的证据附件（' + q('_KIND_HEX') + '）')
    A('')
    A('用途：captain 已裁定 t13 = **删除死代码**（零消费者；为不渲染的颜色立令牌与「令牌外色 = 0」背道而驰）。'
      + '本附录把原先按「收口到令牌」读法做的量化对照**转为删除决策的证据**，供将来真要重建时参考。')
    A('')
    A('**死代码判定证据**：' + q('edu_schedule/models/session_ext.py:34-39') + ' 的 ' + q('_KIND_HEX') + '，全仓（排除 ' + q('__pycache__') + '）'
      + '仅命中其注释 ' + q(':11') + ' 与定义本身；无 Python/XML/JS 消费者；' + q(':11') + ' 自述「仅供前端图例/文案层展示，不进入视图 color 字段」。captain 与 color-arch 均已独立复核。')
    A('')
    A('**三档原始数据（若将来重建，仍需面对的两个约束）**：')
    A('')
    A('| 档 | 现值 | 白字压底 | 深字(' + q('#1A2233') + ')压底 | 备注 |')
    A('|---|---|---|---|---|')
    A('| 高（教师冲突·红） | ' + q('#DC2626') + ' | **5.88 ✓** | — | 可配白字 |')
    A('| 中（教室冲突·橙） | ' + q('#E7650A') + ' | **3.35 ✗** | 4.74 ✓ | **不能配白字** |')
    A('| 低（班级冲突·琥珀） | ' + q('#D97706') + ' | **2.44 ✗** | 6.52 ✓ | **不能配白字** |')
    A('')
    A('> 两条告警（将来重建必读）：① **三档不能统一用白字**（中、低两档白字均 <4.5）；'
      + '② 现役 ' + q('#E7650A') + ' ↔ ' + q('#D97706') + ' 的**可辨性仅 1.05**（几乎不可辨），换成 danger↔warning 两族才拉开到 2.41 ⇒ 「三档分级」在现有三色上**本来就分不出来**。')
    A('')
    A('**执行清单（t13）**：grep 复核无动态访问（' + q('getattr') + ' / ' + q('globals()') + '）→ 删除 ' + q('session_ext.py:34-39') + ' 与 ' + q(':11') + ' 说明行 → 报告附「删除前后全仓引用数 = 0」。'
      + '（注：Odoo 0-55 日历色板 ' + q('conflict_color') + ' **不受影响**。）')
    A('')
    A('### 12.3 captain 对交付的两条硬要求（t4 报告必须满足）')
    A('')
    A('1. **必须区分「已渲染核实的」与「启发式候选」** —— 本表 §8 与 §10.3 均为**同规则共现启发式**（不等于实测渲染对；已知反例 ' + q('banner.css:131') + '）。'
      + 't4 报告里两类分列，不得混报。')
    A('2. **批 B 每一处都要给「改前/改后 computed 值」**，且可独立回退；**终判以 t9 的 axe ＋ 渲染取色为准**（不是本台账的静态推算）。')
    A('')
    if '--out' in sys.argv:
        out = os.path.join(ROOT, sys.argv[sys.argv.index('--out') + 1])
        open(out, 'w').write('\n'.join(L) + '\n')
        sys.stderr.write('written: %s (%d lines)\n' % (out, len(L)))
    else:
        print('\n'.join(L))

if __name__ == '__main__':
    main()
