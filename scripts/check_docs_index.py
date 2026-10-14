#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静态门禁：docs/plans/ 头部状态行 ↔ README.md 索引登记（防计划文档腐化）。

触发事件：docs/plans/ 攒到 68 份、没有索引；每份文档的状态靠**正文自称**，而且常与事实不符 ——
「已上线」「待实施」「已完成」在不同文档里互相打架，接手的人只能挨个读正文猜；
最危险的一幕是**被取代的旧文档仍留在原地自称现行**，于是有人照旧文档去实施。
更近的一次是同一份文档头部**并存两行「状态」**（旧的「> **状态**：仅设计（…）」与新的机器行），
读者看到两个互相矛盾的字段 —— 这正是本门禁要消灭的病，故不变式 2 拆成 2a / 2b 两条。

不变式（五条缺一不可，逐条对应下面的实现）：
  1. 登记完备且唯一：docs/plans/*.md（除 README.md）每份在 README 里**恰好登记一次**
     （登记行 = 表格行首格是反引号包裹的 xxx.md）：0 次 = 未登记，≥2 次 = 重复登记；
  2. 状态行合法：前 20 行内 (2a) **有且仅有 1 行**匹配严格模板（逐字，见 STATUS_RE），
     且 (2b) **不得再有别的以「> **状态**」开头的行** —— 哪怕它不匹配模板。
     理由：那种旧行在读者眼里就是同一个字段，两行并存 = 两个矛盾的状态值。
     （历史遗留的老行改名成「> **历史状态**：…」即通过：它不再以「状态」打头。）
  3. 索引与头部一致：README 登记行的「主题 / 状态 / 取代」三列与头部状态行**逐字相同**；
  4. 取代链合法：取代值为 —，或指向本目录内**真实存在**的 .md；链上**无环**（打印环路径）；
  5. 取代必有横幅：设了取代的文档正文必须有一行横幅，且横幅**链接目标 = 取代值**。

理由：这一页是给「下一个人（或下一个 AI）」的路由表，不是文档汇编。一致性必须交给机器守 ——
人手工同步 68 行必然漂移，而**漂移的索引比没有索引更危险**：它看起来可信，于是没人去核。
连带作用：状态只有真被核对过才写得出来，于是「文档自称已上线」这种话说不出口了。

设计约束：零环境依赖（不连 DB / 不发 HTTP / 不读容器，停机可跑）；**只读**，不改任何文档；
退出码 0=OK 1=FAIL 2=ENV 3=INCOMPLETE；自证行 打印 REVISION · 指纹 · 断言数 · 时刻。
"""
import argparse, hashlib, io, os, re, shutil, sys, tempfile
from datetime import datetime

REVISION = 'v1.0'
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PLANS_REL = 'docs/plans'
README_NAME = 'README.md'
HEAD_LINES = 20          # 只认前 20 行：状态行藏在正文里等于没写

# 例外登记：确需不登记的文档（键=仓库相对路径，值=理由）。
# 只豁免不变式 1，其余四条照查 —— 例外不是免检，否则这张表迟早变成垃圾桶。
ALLOW_UNLISTED = {}

# 反引号常量（ASCII 96）：状态行契约逐字要求这个字符；写成 chr(96) 免得被别处的转义吃掉。
TICK = chr(96)

# 不变式 2a 的唯一合法形态（逐字）。三处易错点，都是这份契约最容易被写歪的地方：
#   · 分隔符是全角 ｜，左右**各一个半角空格**；写成半角竖线或不带空格都算非法；
#   · 四个值**必须**用反引号包裹，主题长度按反引号内字符数判（1–24）；
#   · 结尾 $：状态行是**一整行**，不许在后面追加别的字段（要写就另起一行）。
STATUS_RE = re.compile(
    r'^> \*\*状态\*\*：`(设计中|在研|已上线|归档)` ｜ '
    r'\*\*主题\*\*：`([^`]{1,24})` ｜ '
    r'\*\*取代\*\*：`(—|[^`]+\.md)` ｜ '
    r'\*\*核对\*\*：`(\d{4}-\d{2}-\d{2})`$')

# 不变式 2b 的判据：任何以「> **状态**」打头的行都算「同一字段又写了一遍」。
# 注意 **历史状态** 不会被它命中（** 之后是「历史」而不是「状态」）—— 那正是老行的合法出路。
STATUS_MARK_RE = re.compile(r'^> +\*\* *状态 *\*\*')

# 登记行：**首格**是反引号包裹的 .md 文件名。不做猜测式归一化 ——
# xxx.md 算；裸 xxx.md、[x](x.md)、反引号包住子目录路径、x.MD 都不算。
REG_CELL_RE = re.compile(r'^`([^`]+\.md)`$')

# 不变式 5 的横幅。**两处防假红，都来自实物**（第一版这里栽过跟头，教训写进注释）：
#   · ⚠️ 允许写成不带变体选择符的 ⚠（有的编辑器会吞掉它）；
#   · 仓内 7 条真实横幅都收尾于「... 取代，请优先阅读后者。」—— 把整行锚在「取代」上
#     （$ 紧跟「取代」）会把它们全判成「缺横幅」，于是把后缀做成**可选**组；
#   · 链接文本/目标用 [^...]+ 精确取第一组，而不是贪婪的 .*（横幅里出现第二个链接时不致取错）。
# 实质判据不变：横幅里的**链接目标必须等于取代值**（check 里与头部取代逐字比对）。
BANNER_RE = re.compile(r'^> ⚠️? 本文已被 \[`([^`]+)`\]\(([^)]+)\) 取代(，请优先阅读后者。)?$')

# 违规类别 → 中文标签（打印顺序即此顺序）
CATS = (
    ('unlisted', '未登记'),
    ('dup', '重复登记'),
    ('head_missing', '状态行缺失'),
    ('head_illegal', '状态行非法'),
    ('head_multiple', '状态行重复（多条合规行）'),
    ('head_conflict', '同字段双状态行（旧行未改名）'),
    ('mismatch', '索引与头部不一致'),
    ('supersede_missing', '取代指向不存在'),
    ('cycle', '取代成环'),
    ('banner', '缺横幅/横幅目标不符'),
)
LABEL = {'topic': '主题', 'status': '状态', 'supersede': '取代'}


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
    r"""表格行 → 单元格列表（去掉首尾竖线与空白）。

    ⚠ 本函数**不做转义竖线处理**。原注释写「本仓表格不用转义竖线」—— 那句话**是错的**：
    2026-09-28 实测 docs/**.md 里有 **76 行**在用 GFM 的转义竖线 \|（渲染成字面竖线）。
    此处仍然不处理，但理由换成可核查的那一条：本函数**只**被 parse_registrations 用来解析
    docs/plans/README.md 的登记行，而登记行的唯一判据是「首格 = 反引号包裹的 xxx.md」，
    登记行里从不出现转义竖线 ⇒ 这个口径对**本函数要判的东西**没有影响。
    要按 GFM 正确切分全仓表格，看 scripts/check_md_tables.py（那里才是按表格判的门禁）。
    本次只订正这句话，**判据一行未动**。
    """
    s = line.strip()
    if s.startswith('|'):
        s = s[1:]
    if s.endswith('|'):
        s = s[:-1]
    return [c.strip() for c in s.split('|')]


def strip_ticks(cell):
    """剥掉整体包裹的反引号（两侧口径一致：索引格与头部格里的是同一串字符）。"""
    c = (cell or '').strip()
    if len(c) >= 2 and c.startswith('`') and c.endswith('`'):
        return c[1:-1].strip()
    return c


def parse_registrations(text):
    """README 里的登记行 → [{行号, 文件, 主题, 状态, 取代, 格数}]。

    只看**首格**：首格是反引号包裹的 xxx.md 即算一次登记（这是不变式 1 的唯一判据，
    所以「家族指针」「保留原位」那些表格的首格不能写成这种形式，否则会被计成第二次登记）。
    """
    out = []
    for i, raw in enumerate(text.splitlines(), 1):
        if not raw.lstrip().startswith('|'):
            continue
        cells = split_row(raw)
        if not cells:
            continue
        m = REG_CELL_RE.match(cells[0])
        if not m:
            continue
        out.append({'row': i, 'file': m.group(1),
                    'topic': strip_ticks(cells[1]) if len(cells) > 1 else '',
                    'status': strip_ticks(cells[2]) if len(cells) > 2 else '',
                    'supersede': strip_ticks(cells[3]) if len(cells) > 3 else '',
                    'cells': len(cells)})
    return out


def parse_head(text, limit=HEAD_LINES):
    """→ (合规命中列表, 其他「状态」行列表)。

    命中项 = {行号, 状态, 主题, 取代, 核对}；其他 = (行号, 原文)，即不变式 2b 要抓的旧行。
    行尾空白先 rstrip 再匹配（不给「行尾多一个空格」报假红），行首缩进**不宽容**：
    状态行必须顶格，缩进过的引用块行不算 —— 否则它会被当成普通正文而漏检。
    """
    hits, others = [], []
    for i, raw in enumerate(text.splitlines()[:limit], 1):
        line = raw.rstrip()
        m = STATUS_RE.match(line)
        if m:
            hits.append({'line': i, 'status': m.group(1), 'topic': m.group(2),
                         'supersede': m.group(3), 'checked': m.group(4)})
        elif STATUS_MARK_RE.match(line):
            others.append((i, line.strip()))
    return hits, others


def find_cycles(graph):
    """取代图里的环 → [[a, b, a], ...]（按起点排序，同一环只报一次）。

    为什么要单独报环：A→B→A 时「谁取代谁」没有答案，读者会同时看到两份都自称现行；
    而只报「链不合法」指不出环在哪，排查者得自己画图。这里直接把路径打出来。
    """
    cycles, seen = [], set()
    for start in sorted(graph):
        path, cur = [], start
        while cur in graph and cur not in path:
            path.append(cur)
            cur = graph[cur]
        if cur in path:
            cyc = path[path.index(cur):] + [cur]
            key = frozenset(cyc)
            if key not in seen:
                seen.add(key)
                cycles.append(cyc)
    return cycles


def longest_chain(graph):
    """最长取代链（跳数）。环上的节点记 None 并跳过，不参与长度比较、也不会递归爆栈。"""
    memo = {}

    def depth(node, stack):
        if node in memo:
            return memo[node]
        nxt = graph.get(node)
        if not nxt:
            memo[node] = 0
            return 0
        if nxt in stack:
            memo[node] = None
            return None
        d = depth(nxt, stack | {node})
        memo[node] = None if d is None else d + 1
        return memo[node]

    best = 0
    for node in sorted(graph):
        d = depth(node, set())
        if d:
            best = max(best, d)
    return best


def extract_ticks(targets):
    """展示用：把「反引号包住文件名」形式的目标还原成裸文件名。"""
    out = []
    for t in targets:
        if len(t) >= 2 and t.startswith('`') and t.endswith('`'):
            out.append(t[1:-1].strip())
        else:
            out.append(t)
    return out


def check(root=REPO, quiet=False):
    """跑五条不变式。返回 {rc, findings, docs, regs, incomplete, graph, cycles, nhead, asserts}。"""
    plans = os.path.join(root, PLANS_REL)
    if not os.path.isdir(plans):
        if not quiet:
            print('ENV：目录不存在 %s —— 无法判定（这不是通过）' % plans)
        return {'rc': 2, 'findings': {}, 'docs': [], 'regs': [], 'incomplete': [],
                'graph': {}, 'cycles': [], 'nhead': 0, 'asserts': 0}
    readme_path = os.path.join(plans, README_NAME)
    readme = read_text(readme_path)
    if readme is None:
        # 索引页本身读不到 ⇒ 无法判定登记完备性。**不能算通过**（这正是它存在的意义）。
        if not quiet:
            print('INCOMPLETE：读不到 %s —— 无法判定登记完备性（这不是通过）' % readme_path)
        return {'rc': 3, 'findings': {}, 'docs': [], 'regs': [], 'incomplete': [readme_path],
                'graph': {}, 'cycles': [], 'nhead': 0, 'asserts': 0}
    docs = sorted(f for f in os.listdir(plans)
                  if f.endswith('.md') and f != README_NAME
                  and os.path.isfile(os.path.join(plans, f)))
    regs = parse_registrations(readme)
    by_file = {}
    for r in regs:
        by_file.setdefault(r['file'], []).append(r)

    F = dict((k, []) for k, _ in CATS)
    incomplete, graph, nhead_ok, n_assert = [], {}, 0, 0

    for name in docs:
        rel = '%s/%s' % (PLANS_REL, name)
        text = read_text(os.path.join(plans, name))
        if text is None:
            incomplete.append(rel)
            continue

        # ── 不变式 1：登记完备且唯一 ──────────────────────────────────────
        rows = by_file.get(name, [])
        n_assert += 1
        if not rows:
            if rel not in ALLOW_UNLISTED:
                F['unlisted'].append((name, 'README 里没有以它打头的登记行'))
        elif len(rows) > 1:
            F['dup'].append((name, '登记了 %d 次（第 %s 行）'
                             % (len(rows), '、'.join(str(r['row']) for r in rows))))

        # ── 不变式 2：状态行合法（2a 唯一合规行 / 2b 不得并存旧「状态」行）──
        hits, others = parse_head(text)
        n_assert += 2
        if not hits:
            if others:
                F['head_illegal'].append((name, '第 %d 行写了状态行但格式或取值非法：%s'
                                          % (others[0][0], others[0][1])))
            else:
                F['head_missing'].append((name, '前 %d 行内没有状态行' % HEAD_LINES))
            continue
        if len(hits) > 1:
            F['head_multiple'].append((name, '第 %s 行各有一行合规状态行（必须只有 1 行）'
                                       % '、'.join(str(h['line']) for h in hits)))
            # 仍拿第一行参与后续比对：否则一致性/取代/横幅会被整体跳过 == 漏检
        if others:
            F['head_conflict'].append((name, '第 %d 行还有一行旧「状态」：%s —— 读者会看到两个'
                                      '矛盾的状态值，须改名成「历史状态」或删除'
                                      % (others[0][0], others[0][1])))
        h = hits[0]
        nhead_ok += 1

        # ── 不变式 3：索引与头部逐字一致 ─────────────────────────────────
        for r in rows:
            n_assert += 1
            if r['cells'] != 6:
                F['mismatch'].append((name, '登记行（第 %d 行）只有 %d 格，应为 6 格'
                                      '（文件/主题/状态/取代/要点/判定依据）'
                                      % (r['row'], r['cells'])))
                continue
            diff = [k for k in ('topic', 'status', 'supersede') if r[k] != h[k]]
            if diff:
                F['mismatch'].append((name, '登记行（第 %d 行）与头部不一致：%s'
                                      % (r['row'], '；'.join(
                                          '%s 索引=%s 头部=%s' % (LABEL[k], r[k], h[k])
                                          for k in diff))))

        # ── 不变式 4：取代链合法（存在 + 无环）───────────────────────────
        sup = h['supersede']
        if sup != '—':
            n_assert += 1
            if '/' in sup or not os.path.isfile(os.path.join(plans, sup)):
                F['supersede_missing'].append((name, '取代 = %s（本目录内不存在；须写文件名'
                                               '而不是路径）' % sup))
            else:
                # 只把**真实存在**的目标放进图：悬空目标单独报，免得它再连带报一圈环
                graph[name] = sup

            # ── 不变式 5：取代必有横幅且链接目标 = 取代值 ────────────────
            n_assert += 1
            targets = [m.group(2).strip()
                       for m in (BANNER_RE.match(l.rstrip()) for l in text.splitlines()) if m]
            norm = [t[2:] if t.startswith('./') else t for t in targets]
            if not targets:
                F['banner'].append((name, '缺横幅：正文应有「> ⚠️ 本文已被 [%s%s%s](%s) 取代」'
                                    % (TICK, sup, TICK, sup)))
            elif sup not in norm:
                F['banner'].append((name, '横幅目标不符：头部取代 = %s，正文横幅指向 %s'
                                    % (sup, '、'.join(extract_ticks(targets)))))

    # ── 不变式 4（续）：环 ───────────────────────────────────────────────
    cycles = find_cycles(graph)
    for cyc in cycles:
        n_assert += 1
        F['cycle'].append((' → '.join(cyc), '环上每份都自称现行，读者无法判断该信谁'))

    rc = 1 if any(F.values()) else (3 if incomplete else 0)
    if not quiet:
        print('== docs/plans 头部状态行 ↔ README 索引登记 ==')
        print('文档 %d 份（%s/*.md，除 README.md）｜登记行 %d 条 / 覆盖 %d 份｜头部合法 %d 份'
              % (len(docs), PLANS_REL, len(regs), len(by_file), nhead_ok))
        print('未登记 %d｜重复登记 %d｜状态行缺失 %d｜状态行非法 %d｜状态行重复 %d｜双状态行 %d'
              '｜索引不一致 %d｜取代悬空 %d｜取代成环 %d｜缺横幅 %d'
              % (len(F['unlisted']), len(F['dup']), len(F['head_missing']), len(F['head_illegal']),
                 len(F['head_multiple']), len(F['head_conflict']), len(F['mismatch']),
                 len(F['supersede_missing']), len(F['cycle']), len(F['banner'])))
        for key, label in CATS:
            for name, extra in F[key]:
                print('  FAIL %s：%s%s' % (label, name, ('（%s）' % extra) if extra else ''))
        for p, why in ALLOW_UNLISTED.items():
            print('  ALLOW 例外登记（只豁免「登记完备」这一条）：%s（%s）' % (p, why))
        for p in incomplete:
            print('  INCOMPLETE 文档读不到：%s' % p)
        print('结论：%s' % {0: 'OK', 1: 'FAIL', 2: 'ENV', 3: 'INCOMPLETE'}[rc])
        print('自证：REVISION=%s · 指纹 %s · 断言 %d 条 · 时刻 %s'
              % (REVISION, self_fingerprint(), n_assert,
                 datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        print('契约：exit 0=OK 1=FAIL 2=ENV(目录不存在) 3=INCOMPLETE(README/文档读不到)')
    return {'rc': rc, 'findings': F, 'docs': docs, 'regs': regs, 'incomplete': incomplete,
            'graph': graph, 'cycles': cycles, 'nhead': nhead_ok, 'asserts': n_assert}


def coverage(root=REPO):
    """登记覆盖率报告。**这不是门禁**：有违规也 exit 0（报告应当始终出得来），只在目录不存在时 2。

    汇总者靠它回答「还剩多少没登记」「家族取代链有多深」；
    对自证的意义是：骨架 README 状态下它必须如实打印 0/68，而不是装作没事。
    """
    plans = os.path.join(root, PLANS_REL)
    if not os.path.isdir(plans):
        print('ENV：目录不存在 %s' % plans)
        return 2
    docs = sorted(f for f in os.listdir(plans)
                  if f.endswith('.md') and f != README_NAME
                  and os.path.isfile(os.path.join(plans, f)))
    readme = read_text(os.path.join(plans, README_NAME))
    if readme is None:
        print('⚠ 读不到 %s ⇒ 已登记按 0 计（先把数报出来，这不是通过）'
              % os.path.join(PLANS_REL, README_NAME))
        regs = []
    else:
        regs = parse_registrations(readme)
    names = set(r['file'] for r in regs)
    registered = [d for d in docs if d in names]
    graph, status_count, nheads = {}, {}, 0
    for d in docs:
        text = read_text(os.path.join(plans, d))
        if text is None:
            continue
        hits, _others = parse_head(text)
        if len(hits) != 1:
            continue
        nheads += 1
        status_count[hits[0]['status']] = status_count.get(hits[0]['status'], 0) + 1
        sup = hits[0]['supersede']
        if sup != '—' and os.path.isfile(os.path.join(plans, sup)):
            graph[d] = sup
    depth = longest_chain(graph)
    ratio = (100.0 * len(registered) / len(docs)) if docs else 0.0
    print('== docs/plans 覆盖统计 ==')
    print('扫描文档 %d 份（%s/*.md，除 README.md）｜已登记 %d 份｜登记/总数 %d/%d (%.1f%%)'
          '｜登记行 %d 条（重复登记 %d 条）｜头部合规 %d 份'
          % (len(docs), PLANS_REL, len(registered), len(registered), len(docs), ratio,
             len(regs), len(regs) - len(names), nheads))
    print('最长取代链 %d 跳（取代边 %d 条）｜例外登记 %d 条'
          % (depth, len(graph), len(ALLOW_UNLISTED)))
    dist = '｜'.join('%s %d' % (k, status_count[k])
                     for k in ('设计中', '在研', '已上线', '归档') if k in status_count)
    print('状态分布：%s' % (dist or '（还没有一行合规状态行）'))
    print('自证：REVISION=%s · 指纹 %s · 断言 %d 条 · 时刻 %s'
          % (REVISION, self_fingerprint(), len(docs) + len(regs),
             datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    return 0


def selftest():
    """反例自检：临时目录造样本，**绝不碰真仓库**。

    反例 9 个（覆盖五条不变式的 10 类违规），正例 4 个（最小规范文档 / 取代链 / 归档件 + 历史状态行 / 短式横幅）。
    反例固化在脚本里而不是靠 /tmp 手工夹具 —— 夹具会没，反例不会；而且这份门禁判的是
    「文档写对了吗」，判据自己被改坏时必须先自曝，所以这里连正则的近似写法一起测。
    """
    ok = True

    def chk(name, cond, extra=''):
        nonlocal ok
        print('  %-4s %s %s' % ('PASS' if cond else 'FAIL', name, extra))
        ok = ok and bool(cond)

    NL = chr(10)
    Q = TICK

    def head(status, topic, sup, checked='2026-09-26'):
        return ('> **状态**：' + Q + status + Q + ' ｜ **主题**：' + Q + topic + Q +
                ' ｜ **取代**：' + Q + sup + Q + ' ｜ **核对**：' + Q + checked + Q)

    def banner(target):
        # 与仓内 7 条真实横幅**逐字同形**（含后缀）。教训：夹具若只造自己顺手写的形状，
        # 就是「尺子自证全绿、一量实物全红」——本门禁第一版正是这样漏掉了 7 条正确横幅。
        return ('> ⚠️ 本文已被 [' + Q + target + Q + '](' + target + ') 取代，请优先阅读后者。')

    def banner_short(target):
        # 短式（无后缀）也合法：后缀在 BANNER_RE 里是可选的。
        return '> ⚠️ 本文已被 [' + Q + target + Q + '](' + target + ') 取代'

    def reg(name, topic, status, sup, note='要点', why='依据'):
        return ('| ' + Q + name + Q + ' | ' + topic + ' | ' + Q + status + Q + ' | ' + Q + sup +
                Q + ' | ' + note + ' | ' + why + ' |')

    tmp = tempfile.mkdtemp(prefix='cdi_selftest_')
    try:
        plans = os.path.join(tmp, 'docs', 'plans')
        os.makedirs(plans)
        files, rows = {}, []

        # ── 正例 1：最小的规范文档（只有一行状态行也合法）─────────────────
        files['v1-min.md'] = head('设计中', '最小样例', '—') + NL
        rows.append(reg('v1-min.md', '最小样例', '设计中', '—'))
        # ── 正例 2：合法取代链 v4 → v3 → v2（两跳，横幅齐全）──────────────
        files['v2-base.md'] = head('已上线', '请假审批', '—') + NL
        files['v3-sup.md'] = head('归档', '请假审批', 'v2-base.md') + NL + banner('v2-base.md') + NL
        files['v4-sup2.md'] = head('归档', '请假审批', 'v3-sup.md') + NL + banner('v3-sup.md') + NL
        rows += [reg('v2-base.md', '请假审批', '已上线', '—'),
                 reg('v3-sup.md', '请假审批', '归档', 'v2-base.md'),
                 reg('v4-sup2.md', '请假审批', '归档', 'v3-sup.md')]
        # ── 正例 3：归档件 + 取代 + 横幅，且带一行**改名后的历史状态** ────
        # 「> **历史状态**：…」必须不被判违规 —— 那 7 份老文档正是靠它合法上岸，
        # 这里错了会一次性报 7 个假红，把整批改造拦死。
        files['v5-arch.md'] = (head('归档', '请假审批', 'v2-base.md') + NL +
                               '> **历史状态**：定稿（t2 交付物）· 版本 v4.2' + NL +
                               banner('v2-base.md') + NL)
        rows.append(reg('v5-arch.md', '请假审批', '归档', 'v2-base.md'))
        # ── 正例 4：短式横幅（不带后缀）同样合法 ─────────────────────────
        files['v6-short.md'] = (head('归档', '请假审批', 'v2-base.md') + NL +
                                banner_short('v2-base.md') + NL)
        rows.append(reg('v6-short.md', '请假审批', '归档', 'v2-base.md'))

        # ── 反例 1：缺登记（状态行合法，但 README 里没有它）───────────────
        files['s1-unlisted.md'] = head('设计中', '未登记样例', '—') + NL
        # ── 反例 2：重复登记（同一份登记两次）─────────────────────────────
        files['s2-dup.md'] = head('在研', '重复登记样例', '—') + NL
        rows += [reg('s2-dup.md', '重复登记样例', '在研', '—'),
                 reg('s2-dup.md', '重复登记样例', '在研', '—')]
        # ── 反例 3：状态行缺失（登记了，头部压根没写）─────────────────────
        files['s3-nostat.md'] = '# 没有状态行' + NL + '正文……' + NL
        rows.append(reg('s3-nostat.md', '缺状态行', '设计中', '—'))
        # ── 反例 4：状态值非法（写了，值不在四值内）──────────────────────
        files['s4-badvalue.md'] = head('开发中', '非法值', '—') + NL
        rows.append(reg('s4-badvalue.md', '非法值', '设计中', '—'))
        # ── 反例 5：索引与头部不一致（头部 已上线、索引 在研）────────────
        files['s5-mismatch.md'] = head('已上线', '请假审批', '—') + NL
        rows.append(reg('s5-mismatch.md', '请假审批', '在研', '—'))
        # ── 反例 6（一个家族，三类违规）：取代悬空 / 取代成环 / 缺横幅 ────
        files['s6-dangling.md'] = (head('归档', '悬空取代', 'ghost-missing.md') + NL +
                                   banner('ghost-missing.md') + NL)
        rows.append(reg('s6-dangling.md', '悬空取代', '归档', 'ghost-missing.md'))
        files['s6-cycle-a.md'] = (head('归档', '成环', 's6-cycle-b.md') + NL +
                                  banner('s6-cycle-b.md') + NL)
        files['s6-cycle-b.md'] = head('归档', '成环', 's6-cycle-a.md') + NL   # ← 故意不写横幅
        rows += [reg('s6-cycle-a.md', '成环', '归档', 's6-cycle-b.md'),
                 reg('s6-cycle-b.md', '成环', '归档', 's6-cycle-a.md')]
        # ── 反例 7：机器行 + 旧「状态」行并存（不变式 2b 的正样本）────────
        old_line = '> **状态**：仅设计（第 0 步「落地前查重」+ 第 3 步「读参考」）。'
        files['s7-conflict.md'] = head('设计中', '双状态行', '—') + NL + old_line + NL
        rows.append(reg('s7-conflict.md', '双状态行', '设计中', '—'))
        # ── 反例 8：前 20 行内两条合规状态行（只能有一条）────────────────
        files['s8-multi.md'] = (head('设计中', '重复行', '—') + NL + NL +
                                head('在研', '重复行', '—') + NL)
        rows.append(reg('s8-multi.md', '重复行', '设计中', '—'))
        # ── 反例 9：横幅存在，但链接目标 != 头部取代值（第二类横幅违规）──
        files['s9-badtarget.md'] = (head('归档', '横幅指错', 'v2-base.md') + NL +
                                    banner('v3-sup.md') + NL)
        rows.append(reg('s9-badtarget.md', '横幅指错', '归档', 'v2-base.md'))

        for name in sorted(files):
            io.open(os.path.join(plans, name), 'w', encoding='utf-8').write(files[name])
        readme = (['# 夹具索引', '',
                   '| 文件 | 主题 | 状态 | 取代 | 要点 | 判定依据 |',
                   '|---|---|---|---|---|---|'] + rows + [''])
        io.open(os.path.join(plans, README_NAME), 'w', encoding='utf-8').write(NL.join(readme))

        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = check(root=tmp)
            cov_rc = coverage(root=tmp)
        out = buf.getvalue()
        F = res['findings']

        def blob():
            return '  ||  '.join('%s %s' % (nm, ex) for _c, _l in CATS for nm, ex in F[_c])

        def red(names):
            # 只按**出问题的文件名**归属，不拿整段说明文字做子串匹配 —— 否则反例 9 的解释
            # （正文横幅指向 v3-sup.md）会把无辜的正例 2 连坐判红（脚手架自己的坑）。
            return any(n == nm or n in nm
                       for _c, _l in CATS for nm, _e in F[_c] for n in names)

        defect = [('反例① 缺登记', ['s1-unlisted.md']),
                  ('反例② 重复登记', ['s2-dup.md']),
                  ('反例③ 状态行缺失', ['s3-nostat.md']),
                  ('反例④ 状态值非法', ['s4-badvalue.md']),
                  ('反例⑤ 索引与头部不一致', ['s5-mismatch.md']),
                  ('反例⑥ 取代悬空 + 成环 + 缺横幅',
                   ['s6-dangling.md', 's6-cycle-a.md', 's6-cycle-b.md']),
                  ('反例⑦ 旧「状态」行与机器行并存（2b）', ['s7-conflict.md']),
                  ('反例⑧ 两条合规状态行（2a 唯一性）', ['s8-multi.md']),
                  ('反例⑨ 横幅目标 != 取代值', ['s9-badtarget.md'])]
        good = [('正例① 最小规范文档', ['v1-min.md']),
                ('正例② 取代链 v4→v3→v2', ['v2-base.md', 'v3-sup.md', 'v4-sup2.md']),
                ('正例③ 归档件 + 取代 + 横幅 + 历史状态行', ['v5-arch.md']),
                ('正例④ 短式横幅（无后缀）', ['v6-short.md'])]
        n_red = sum(1 for _l, ns in defect if red(ns))
        n_green = sum(1 for _l, ns in good if not red(ns))

        chk('反例存在 ⇒ 总判 FAIL（rc=1）', res['rc'] == 1, 'rc=%s' % res['rc'])
        for lbl, ns in defect:
            chk('%s：如期报红' % lbl, red(ns))
        for lbl, ns in good:
            chk('%s：不报红' % lbl, not red(ns))
        cls = [('未登记', 'unlisted', 's1-unlisted.md'), ('重复登记', 'dup', 's2-dup.md'),
               ('状态行缺失', 'head_missing', 's3-nostat.md'),
               ('状态行非法', 'head_illegal', 's4-badvalue.md'),
               ('索引与头部不一致', 'mismatch', 's5-mismatch.md'),
               ('取代指向不存在', 'supersede_missing', 's6-dangling.md'),
               ('取代成环', 'cycle', 's6-cycle-a.md'), ('缺横幅', 'banner', 's6-cycle-b.md'),
               ('同字段双状态行', 'head_conflict', 's7-conflict.md'),
               ('状态行重复', 'head_multiple', 's8-multi.md')]
        n_cls = sum(1 for _l, key, nm in cls if any(nm == n or nm in n for n, _e in F[key]))
        for lbl, key, nm in cls:
            chk('分类命中：%s' % lbl, any(nm == n or nm in n for n, _e in F[key]))
        chk('取代成环：打印出环路径（不是只说「有环」）',
            's6-cycle-a.md → s6-cycle-b.md → s6-cycle-a.md' in out)
        chk('索引不一致：点出是哪一列不一致', '状态 索引=在研 头部=已上线' in out)
        chk('2b：报出旧行原文，便于定位改名', '仅设计（第 0 步' in out)
        chk('历史状态行不算违规（防 7 份老文档假红）',
            not red(['v5-arch.md']) and '定稿（t2 交付物）' not in blob())
        chk('--coverage 对夹具出报告（exit 0）', cov_rc == 0, 'rc=%s' % cov_rc)
        chk('--coverage 取到最长取代链 2 跳', '最长取代链 2 跳' in out)

        # 正则自检：模板必须逐字匹配；近似写法必须**不**匹配
        tmpl = ('> **状态**：' + Q + '已上线' + Q + ' ｜ **主题**：' + Q + '请假审批' + Q +
                ' ｜ **取代**：' + Q + '—' + Q + ' ｜ **核对**：' + Q + '2026-09-26' + Q)
        chk('正则：模板逐字匹配', bool(STATUS_RE.match(tmpl)))
        chk('正则：｜ 前少空格 ⇒ 不匹配', not STATUS_RE.match(tmpl.replace(' ｜ ', '｜ ')))
        chk('正则：换成半角竖线 ⇒ 不匹配', not STATUS_RE.match(tmpl.replace('｜', '|')))
        chk('正则：漏掉反引号 ⇒ 不匹配', not STATUS_RE.match(tmpl.replace(Q, '')))
        chk('正则：状态值非法 ⇒ 不匹配', not STATUS_RE.match(tmpl.replace('已上线', '开发中')))
        chk('正则：主题超 24 字 ⇒ 不匹配',
            not STATUS_RE.match(tmpl.replace('请假审批', '主' * 25)))
        chk('正则：末尾追加字段 ⇒ 不匹配', not STATUS_RE.match(tmpl + ' ｜ **补充**：' + Q + 'x' + Q))
        chk('正则：半角冒号 ⇒ 不匹配', not STATUS_RE.match(tmpl.replace('：', ': ')))
        chk('横幅正则：模板匹配', bool(BANNER_RE.match(banner('v2-base.md'))))
        _rp = os.path.join(REPO, PLANS_REL, 'downloads-design.md')
        _txt = read_text(_rp)
        _real = None
        for _l in (_txt or '').splitlines():
            if '本文已被' in _l:
                _real = _l.rstrip()
                break
        chk('对照：夹具横幅与真实文件逐字同形（判据必须量真东西）',
            _real is not None and _real == banner('downloads-v2-design.md'),
            '真实=%s' % (_real or '（该文件里找不到横幅行）'))
        _m_short = BANNER_RE.match(banner_short('v2-base.md'))
        _m_long = BANNER_RE.match(banner('v2-base.md'))
        _m_tgt = BANNER_RE.match(banner('v3-sup.md'))
        chk('横幅正则：长式（带后缀）与短式都匹配', bool(_m_long) and bool(_m_short))
        chk('横幅正则：链接目标可解析，用于与取代值比对',
            bool(_m_tgt) and _m_tgt.group(2) == 'v3-sup.md')
        chk('横幅正则：句式不符 ⇒ 不匹配',
            not BANNER_RE.match('> ⚠️ v2-base.md 已被取代'))
        chk('「历史状态」不被 STATUS_MARK_RE 命中（老行的合法出路）',
            not STATUS_MARK_RE.match('> **历史状态**：定稿（t2 交付物）'))

        print('自证 %d/%d 报红 · %d/%d 不报红 · 违规类型 %d/%d 命中'
              % (n_red, len(defect), n_green, len(good), n_cls, len(cls)))
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
