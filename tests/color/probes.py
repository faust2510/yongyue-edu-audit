#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t5 专项探针（captain 2026-09-15 裁定采纳）。

⚠ 本工具与冻结基线**严格分离**：
  · **绝不写** tests/color/baseline-local.json（它冻结在 15:50:33 那份）；
  · 结果写到独立文件（默认 tests/color/probes-t5.json）；
  · README 里写明「探针 ≠ 基线」—— 探针回答的是「机制有没有进产物 / 元素在不在」，
    不是 §7.3 的色数读数。

为什么要它：eng-backend（t5）的 B 机制修复（$o-navbar-background 按名重赋）目标是导航栏下拉的
#71639E，而该值在本地**压根没渲染** ⇒ 色数读数在这个点上不可观测。没有探针，t9/t10
无法区分「没修好」与「看不见」。

探针 A（DOM 定向读）：/odoo/contacts 上读相关控件的 computed background-color。
    元素不存在时**明确记「本地不可观测，需生产复测」**，绝不记 0、更不记成漏修。
探针 B（产物定向读）：在后台编译产物里按**值**grep（$o-navbar-background 不落成 CSS 变量名，
    所以按名 grep 恒为 0），并**记录产物 hash**，否则后人无法复现。

用法
    python3 tests/color/probes.py --out tests/color/probes-t5.json        # A + B
    python3 tests/color/probes.py --only b --out tests/color/probes-t5.json
退出码：0=成功 ｜ 1=探针自身失败 ｜ 2=ENV（站点不可达 / 取色器不可用）
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
TABBIT = os.path.expanduser('~/.local/bin/tabbit-cli')
TASK = 'ui-color-audit-t12'
BASE = 'http://127.0.0.1:8069'
DB = 'edu19'
LOGIN = ('faculty@local', 'demo123')

# Probe B 追踪的值集合。按**值**而非名字 grep —— 实测 --o-navbar-background 不落成 CSS 变量名（count=0）。
TRACKED = ['#71639e', '#0c6dd7', '#0e7bf2', '#dee2e6', '#212529', '#714b67',
           '#005fcc']  # #005FCC：疑 Chrome UA 默认焦点环。若产物里 0 处定义 ⇒ 确证是浏览器默认环、非本仓产物

# ---- 探针 C：字面 SCSS 变量指纹（captain 2026-09-15 裁定：**必须限定到本方文件**）----
# 判据：编译产物里出现 $o- / $brand- **字面字符串** ⇒ 该 SCSS 变量未被插值 ⇒ 浏览器取空值。
# ⚠ **整包跑会永久命中 2 处官方误报**（来源是 Odoo 核心，本仓管不到也不该管）。不限定范围的话，
#   t9 复测会天天亮红灯 → 最后必然被人忽略 → 门禁白设。所以必须按**源文件归属**判定。
# 归属依据：产物保留了 /* /path/to/file.scss */ 源标注（实测 1001 个），取每个命中点**之前最近**的那个。
FINGERPRINT_RE = re.compile(r'\$o-[a-zA-Z0-9-]+|\$brand-[a-zA-Z0-9-]+')
# ⚠ 必须同时匹配 .scss **与 .css**：本方门户文件是 .css（如 edu_portal/.../custom_home.css），
#   只匹配 .scss 会把本方命中误归到 unclassified —— 这是本探针 selftest 抓到的真实缺口。
SRC_ANNOT_RE = re.compile(r'/\*\s*([^*\n]{4,160}?\.s?css)\s*\*/')

# 已定位的上游命中（**仅记录不修**：odoo/addons 是官方快照，本仓纪律基座不改）。
# 价值：这是「自定义属性值必须 #{} 插值」这条规则**在官方编译产物里的第一手现场证据**。
UPSTREAM_ALLOW = {
    ('$o-gray-200',
     '/website/static/src/client_actions/website_preview/website_builder_action.dark.scss'),
    ('$o-theme-text-colors',
     '/im_livechat/static/src/core/web/livechat_channel_info_list.scss'),
}


def scss_fingerprint(blob):
    """返回 (hits, ours, upstream_known, unclassified)。hits 每项含 token/source/ours。"""
    marks = [(m.start(), m.group(1)) for m in SRC_ANNOT_RE.finditer(blob)]
    hits, ours, known, unk = [], [], [], []
    for m in FINGERPRINT_RE.finditer(blob):
        pos, tok = m.start(), m.group(0)
        src = ''
        for off, path in reversed(marks):
            if off < pos:
                src = path
                break
        rec = {'token': tok, 'source': src}
        hits.append(rec)
        if (tok, src) in UPSTREAM_ALLOW:
            known.append(rec)
        elif src and ('edu_' in src or 'custom_addons' in src or 'openeducat' in src):
            rec['ours'] = True
            ours.append(rec)
        else:
            unk.append(rec)
    return hits, ours, known, unk


# ---- 探针 D：产物合理性检查（eng-web 建议）----
# 背景：**Odoo 对 SCSS 编译错误是静默丢弃** —— 单文件编译失败不会让 -u 失败，只会让那份 CSS
# 从产物里消失。若 before 恰好取到「编译失败后的残缺旧版」，before 会偏低、after 会显得凭空变好。
# ⇒ 取数前先证明产物是「完整的」。
# ⚠ 标记必须**分前后台**：eng-web 建议的 #wrapwrap.o_portal 实测在**后台** bundle 里 count=0
#   （它是前台选择器，前台 1528），若不分场合使用会变成一条**永远红的假判据**。
PLAUSIBILITY = {
    'backend': ['--brand-action', '--brand-500', '--teal-500'],
    'frontend': ['#wrapwrap.o_portal', '--brand-action', '--teal-500'],
}
PLAUSIBILITY_MIN_BYTES = 100000


def bundle_plausibility(blob, kind):
    need = PLAUSIBILITY.get(kind, [])
    counts = {m: blob.count(m) for m in need}
    missing = [m for m in need if counts[m] == 0]
    too_small = len(blob) < PLAUSIBILITY_MIN_BYTES
    problems = []
    if too_small:
        problems.append('字节数 %d < 下限 %d' % (len(blob), PLAUSIBILITY_MIN_BYTES))
    if missing:
        problems.append('缺自定义标记：%s' % ','.join(missing))
    return {
        'kind': kind, 'bytes': len(blob), 'markers_present': counts,
        'missing_markers': missing,
        'verdict': ('FAIL：产物疑似被剥离或 SCSS 编译静默失败 ⇒ 读数不可信' if problems
                    else 'PASS：产物含全部自定义标记且非空，是完整产物'),
        'problems': problems,
    }


# ---- 探针 E：.text-* 状态色类在**产物级**的映射（captain 2026-09-15 改判）----
# 为什么走产物级：冻结页集上 .text-success 等**根本没有元素**（实测 count=0），无法做渲染取样；
# 而 $o-theme-text-colors 本来就是**编译期 map** ⇒ 产物里的映射就是决定性证据，且不依赖任何页面渲染。
# ⚠ 必须**按 bundle 分别取最后一条规则**：产物由 screen + print 两个 bundle 串成，
#   跨 bundle 取「最后一条」会拿错（实测两者内容一致，但那是巧合，不能依赖）。
TEXT_VARIANTS = {
    'text-success': '--success',
    'text-danger': '--danger',
    'text-warning': '--warning-ink',
    'text-info': '--info',
}
_RULE_COLOR_RE = re.compile(r'color\s*:\s*([^;!}]+)')
_VAR_RE = re.compile(r'var\(\s*(--[a-z0-9-]+)\s*\)')
_HEX_RE = re.compile(r'#([0-9a-fA-F]{6})')
_RGB_RE = re.compile(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', re.I)


def _resolve_color(raw, tokens):
    """把一条声明里的颜色归一成 hex；var(--x) 走令牌表解析。"""
    vm = _VAR_RE.search(raw)
    if vm:
        spec = tokens.get(vm.group(1)) or {}
        v = (spec.get('value') or '').strip().lower()
        if v.startswith('#'):
            return v, 'var(%s)' % vm.group(1)
        return '', 'var(%s)->未解析' % vm.group(1)
    hm = _HEX_RE.search(raw)
    if hm:
        return '#' + hm.group(1).lower(), 'literal'
    rm = _RGB_RE.search(raw)
    if rm:
        return '#%02x%02x%02x' % (int(rm.group(1)), int(rm.group(2)), int(rm.group(3))), 'literal'
    return '', raw.strip()[:40]


# ---- 探针 F：必填字段边框（captain 裁定的「三级降级」）----
# 背景：读 .o_required_modifier 的 border-**top**-color 会得到 currentColor（该边无边框）⇒ 空判据。
# 一级（DOM 定向读 bottom 边）已尝试，但 /odoo/contacts/new 首屏在本机反复撞执行器硬上限（ENV）。
# ⇒ 按裁定降到**二级：产物级**。产物实测给出决定性线索：该边框是 **border-bottom**，
#    且最后一条规则是 border-bottom-color: var(--brand-action) —— 即已令牌化。
# 判据：.o_required_modifier 的**最后一条** border-bottom(-color) 规则必须解析到 --brand-action。
REQUIRED_BORDER_SEL = '.o_required_modifier'
REQUIRED_BORDER_EXPECT = '--brand-action'


def required_border_check(bundles, tokens):
    out = []
    for name, blob in bundles.items():
        rules = re.findall(r'\.o_required_modifier[^{,]{0,80}\{([^}]*)\}', blob)
        last, last_rule = None, None
        for r in rules:
            m = re.search(r'border-bottom(?:-color)?\s*:\s*([^;!}]+)', r)
            if m:
                last, last_rule = m.group(1).strip(), r.strip()
        if last is None:
            out.append({'bundle': name, 'class': REQUIRED_BORDER_SEL, 'verdict':
                        'ENV：产物里找不到 .o_required_modifier 的 border-bottom 规则'})
            continue
        got, how = _resolve_color(last, tokens)
        want = ((tokens.get(REQUIRED_BORDER_EXPECT) or {}).get('value') or '').strip().lower()
        out.append({
            'bundle': name, 'class': REQUIRED_BORDER_SEL,
            'expected_token': REQUIRED_BORDER_EXPECT, 'expected_value': want,
            'found': got, 'found_raw': last, 'last_rule': last_rule[:110],
            'resolved_via': how,
            'verdict': 'PASS' if (got and got == want) else 'FAIL',
        })
    return out


def text_variant_check(bundles, tokens):
    """逐 bundle 取每个 .text-* 的**最后一条** color 规则，与期望令牌对比。"""
    out = []
    for name, blob in bundles.items():
        for cls, want_tok in TEXT_VARIANTS.items():
            rules = re.findall(r'\.' + re.escape(cls) + r'\s*\{([^}]*)\}', blob)
            last = None
            for r in rules:
                m = _RULE_COLOR_RE.search(r)
                if m:
                    last = m.group(1).strip()
            if last is None:
                out.append({'bundle': name, 'class': '.' + cls, 'expected_token': want_tok,
                            'found': None, 'verdict': 'ENV：产物里找不到该类的 color 规则'})
                continue
            got, how = _resolve_color(last, tokens)
            want = ((tokens.get(want_tok) or {}).get('value') or '').strip().lower()
            ok = bool(got) and got == want
            out.append({
                'bundle': name, 'class': '.' + cls, 'expected_token': want_tok,
                'expected_value': want, 'found': got, 'found_raw': last, 'resolved_via': how,
                'verdict': 'PASS' if ok else 'FAIL',
            })
    return out


PROBE_A_JS = '''
const base = "__BASE__";
await context.request.post(base + "/web/session/authenticate", {
  data: { jsonrpc: "2.0", method: "call",
          params: { db: "__DB__", login: "__USER__", password: "__PASS__" } },
});
const tab = await context.newPage();
try {
  await tab.goto(base + "/odoo/contacts", { waitUntil: "domcontentloaded", timeout: 90000 });
  await tab.waitForSelector(".o_web_client, .o_action_manager", { timeout: 15000 }).catch(() => {});
  await tab.waitForTimeout(4000);
  const out = await tab.evaluate(() => {
    const dump = (sel) => {
      const els = [...document.querySelectorAll(sel)];
      return { count: els.length, samples: els.slice(0, 4).map((e) => {
        const cs = getComputedStyle(e);
        return { tag: e.tagName, cls: String(e.className || "").slice(0, 50),
                 bg: cs.backgroundColor, color: cs.color };
      }) };
    };
    return { url: location.href, title: document.title,
             navbar: dump(".o_main_navbar"),
             dropdownInNavbar: dump(".o_main_navbar .o-dropdown"),
             dropdownToggle: dump("button.o-dropdown.dropdown-toggle"),
             chip: dump("#yy-apps-chip") };
  });
  return { label: "probeA", value: out };
} finally {
  await tab.close().catch(() => {});
}
'''


def _risk(msg):
    print('ENV: %s' % msg, file=sys.stderr)
    return 2


def _required_border_for_report():
    """必填边框的二级（产物级）判定 —— 复用同一次产物抓取。"""
    s = requests.Session()
    s.trust_env = False
    try:
        s.post(BASE + '/web/session/authenticate',
               json={'jsonrpc': '2.0', 'params': {'db': DB, 'login': LOGIN[0], 'password': LOGIN[1]}},
               timeout=25)
        page = s.get(BASE + '/odoo/contacts/new', timeout=90)
        try:
            with open(os.path.join(HERE, '..', '..', 'scripts', 'color_tokens.json'), encoding='utf-8') as fh:
                tokens = (json.load(fh) or {}).get('tokens') or {}
        except Exception:
            tokens = {}
        bundles = {}
        for u in re.findall(r'href="([^"]+\.css[^"]*)"', page.text):
            full = u if u.startswith('http') else BASE + u
            bundles[full.split('/')[-1]] = s.get(full, timeout=120).text
        return required_border_check(bundles, tokens)
    except Exception as e:
        return [{'error': 'ENV: %s' % str(e)[:120]}]


def _text_variants_for_report():
    """抓 screen + print 两个 bundle 并分别做 .text-* 产物级判定。"""
    s = requests.Session()
    s.trust_env = False
    try:
        s.post(BASE + '/web/session/authenticate',
               json={'jsonrpc': '2.0', 'params': {'db': DB, 'login': LOGIN[0], 'password': LOGIN[1]}},
               timeout=25)
        page = s.get(BASE + '/odoo/contacts', timeout=60)
        tokens = {}
        try:
            with open(os.path.join(HERE, '..', '..', 'scripts', 'color_tokens.json'), encoding='utf-8') as fh:
                tokens = (json.load(fh) or {}).get('tokens') or {}
        except Exception:
            tokens = {}
        bundles = {}
        for u in re.findall(r'href="([^"]+\.css[^"]*)"', page.text):
            full = u if u.startswith('http') else BASE + u
            bundles[full.split('/')[-1]] = s.get(full, timeout=120).text
        return text_variant_check(bundles, tokens)
    except Exception as e:
        return [{'error': 'ENV: %s' % str(e)[:120]}]


def probe_b():
    """产物定向读：抓后台 CSS 产物、记 hash、按值 grep。"""
    s = requests.Session()
    s.trust_env = False
    try:
        s.post(BASE + '/web/session/authenticate',
               json={'jsonrpc': '2.0', 'params': {'db': DB, 'login': LOGIN[0], 'password': LOGIN[1]}},
               timeout=25)
        page = s.get(BASE + '/odoo/contacts', timeout=60)
    except Exception as e:
        return None, '站点不可达：%s' % str(e)[:120]
    if page.status_code != 200:
        return None, '后台页 HTTP %s' % page.status_code
    urls = re.findall(r'href="([^"]+\.css[^"]*)"', page.text)
    if not urls:
        return None, '后台页里找不到 CSS 产物'
    bundles, blob = [], ''
    for u in urls:
        full = u if u.startswith('http') else BASE + u
        c = s.get(full, timeout=120).text
        blob += c
        bundles.append({'url': full, 'bytes': len(c),
                        'sha256': hashlib.sha256(c.encode()).hexdigest()})
    low = blob.lower()
    counts = {v: low.count(v.lower()) for v in TRACKED}
    hits, ours, known, unk = scss_fingerprint(blob)
    return {
        'plausibility_backend': bundle_plausibility(blob, 'backend'),
        'text_variants': _text_variants_for_report(),
        'required_border': _required_border_for_report(),
        'literal_scss_fingerprint': {
            'rule': '产物里出现 $o- / $brand- 字面串 ⇒ 该变量未被插值 ⇒ 浏览器取空值',
            'scope': '**按源文件归属判定**；整包跑会永久命中 2 处官方误报（见 upstream_known）',
            'total_hits': len(hits),
            'ours_count': len(ours),
            'ours': ours[:10],
            'upstream_known_count': len(known),
            'upstream_known': sorted({(h['token'], h['source']) for h in known}),
            'unclassified_count': len(unk),
            'unclassified': unk[:10],
            'verdict': ('FAIL：本方产物里有字面 SCSS 变量' if ours
                        else 'PASS：本方文件 0 命中（上游命中已按官方快照记录，不计入）'),
        },
        'bundles': bundles,
        'combined_bytes': len(blob),
        'combined_sha256': hashlib.sha256(blob.encode()).hexdigest(),
        'tracked_counts_by_value': counts,
        'grep_note': ('按**值** grep：#o-navbar-background 不落成 CSS 变量名（实测同名 count=0），'
                      '故机制证据只能用值计数 + 产物 hash 复现。'),
    }, None


def _parse_json_stdout(out):
    for line in reversed((out or '').strip().splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def probe_a():
    """DOM 定向读（真机浏览器）。"""
    if not os.path.exists(TABBIT):
        return None, '取色器不可用（%s）' % TABBIT
    js = (PROBE_A_JS.replace('__BASE__', BASE).replace('__DB__', DB)
          .replace('__USER__', LOGIN[0]).replace('__PASS__', LOGIN[1]))
    rid = 'probeA-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    try:
        p = subprocess.run([TABBIT, 'nodejs', '--task', TASK, '--request-id', rid,
                            '--timeout-ms', '170000'],
                           input=js, capture_output=True, text=True, timeout=280)
    except subprocess.TimeoutExpired:
        return None, '取色器超时'
    resp = _parse_json_stdout(p.stdout) or _parse_json_stdout(p.stderr)
    if not resp or resp.get('status') != 'succeeded':
        return None, '取色器未成功：%s' % json.dumps(resp or {}, ensure_ascii=False)[:200]
    val = (resp.get('result') or {}).get('value') or {}
    v = val.get('value') or {}
    # captain 要求：元素不存在时明确记「本地不可观测」，绝不记 0 / 漏修
    for k in ('navbar', 'dropdownInNavbar', 'dropdownToggle', 'chip'):
        d = v.get(k) or {}
        d['observable'] = bool(d.get('count'))
        if not d.get('count'):
            d['verdict'] = '本地不可观测，需生产复测'
        else:
            d['verdict'] = '可读'
    return v, None


def selftest():
    """证探针 C 的指纹**会红**（否则「本方 0 命中」只是没在测）。"""
    cases = []

    def check(name, cond, detail=''):
        cases.append((name, bool(cond), detail))

    upstream_blob = ('/* /website/static/src/client_actions/website_preview/'
                     'website_builder_action.dark.scss */\n'
                     '.o_x{--websitePreview-bg-color: $o-gray-200;}')
    ours_blob = ('/* /mnt/custom-addons/edu_portal/static/src/css/custom_home.css */\n'
                 '.o_y{--brand-x: $brand-500;}')
    clean_blob = '/* /mnt/custom-addons/edu_portal/x.scss */ .o_z{color:#5E6779;}'

    # 探针 D：合理性检查必须**分前后台**，且缺标记时要红
    big = 'x' * (PLAUSIBILITY_MIN_BYTES + 1)
    ok_b = bundle_plausibility(big + '--brand-action --brand-500 --teal-500', 'backend')
    bad_b = bundle_plausibility(big, 'backend')
    check('合理性: 标记齐全的大产物 → PASS',
          ok_b['verdict'].startswith('PASS'), ok_b['verdict'])
    check('合理性: 缺自定义标记 → **必须 FAIL**（否则残缺产物会被当完整用）',
          bad_b['verdict'].startswith('FAIL') and bad_b['missing_markers'],
          str(bad_b['missing_markers']))
    check('合理性: 过小产物 → 必须 FAIL',
          bundle_plausibility('--brand-action --brand-500 --teal-500', 'backend')['verdict'].startswith('FAIL'))
    check('合理性: 标记必须分前后台（#wrapwrap.o_portal 不是后台标记）',
          '#wrapwrap.o_portal' in PLAUSIBILITY['frontend']
          and '#wrapwrap.o_portal' not in PLAUSIBILITY['backend'])

    # 探针 E：.text-* 产物级映射必须能判对、也必须能判错
    _tok = {'--success': {'value': '#127A50'}, '--info': {'value': '#0E7BF2'}}
    _b = 'b1'
    _good = {_b: '.text-success{color: var(--success) !important;} .text-info{color: var(--info) !important;}'}
    _bad = {_b: '.text-success{color: var(--success) !important;} .text-info{color: #5E6779 !important;}'}
    _g = [x for x in text_variant_check(_good, _tok) if x['class'] in ('.text-success', '.text-info')]
    _bb = [x for x in text_variant_check(_bad, _tok) if x['class'] in ('.text-success', '.text-info')]
    check('产物级.text-*: var() 正确映射 → 两项皆 PASS',
          all(x['verdict'] == 'PASS' for x in _g), str([(x['class'], x['verdict']) for x in _g]))
    check('产物级.text-*: .text-info 落到 #5E6779 而非 --info → 必须 FAIL',
          [x['verdict'] for x in _bb if x['class'] == '.text-info'] == ['FAIL'],
          str([(x['class'], x['verdict'], x.get('found')) for x in _bb]))
    check('产物级.text-*: 逐 bundle 各取最后一条规则',
          len({x['bundle'] for x in text_variant_check(_good, _tok)}) == 1)

    # 探针 F：必填边框的二级判定必须能 PASS、也必须能 FAIL（不得是空判据）
    _btok = {'--brand-action': {'value': '#0C6DD7'}}
    _fgood = {'b': '.o_required_modifier{border-bottom-color: var(--brand-action);}'}
    _fbad = {'b': '.o_required_modifier{border-bottom-color: #714B67;}'}
    _fnone = {'b': '.o_required_modifier{color: #333;}'}
    _fg = required_border_check(_fgood, _btok)
    _fb = required_border_check(_fbad, _btok)
    _fn = required_border_check(_fnone, _btok)
    check('必填边框(二级): 解析到 var(--brand-action) → PASS',
          _fg[0]['verdict'] == 'PASS' and _fg[0]['found'] == '#0c6dd7', str(_fg[0])[:110])
    check('必填边框(二级): 若是原厂紫字面量 → 必须 FAIL（证明它不是空判据）',
          _fb[0]['verdict'] == 'FAIL', str(_fb[0])[:110])
    check('必填边框(二级): 产物无 border-bottom 规则 → 明确报 ENV，不得静默通过',
          _fn[0]['verdict'].startswith('ENV'), _fn[0]['verdict'])

    _, o1, k1, u1 = scss_fingerprint(upstream_blob)
    check('指纹: 上游命中归入 upstream_known，本方 0（不得算成本方失败）',
          len(o1) == 0 and len(k1) == 1 and len(u1) == 0,
          'ours=%d known=%d unk=%d' % (len(o1), len(k1), len(u1)))

    _, o2, k2, u2 = scss_fingerprint(ours_blob)
    check('指纹: 本方文件的字面朴素变量**必被抓到**（这才叫门禁）',
          len(o2) == 1 and len(k2) == 0, 'ours=%d known=%d' % (len(o2), len(k2)))

    _, o3, k3, u3 = scss_fingerprint(clean_blob)
    check('指纹: 干净产物不误报（证明它不是「什么都报」）',
          len(o3) == 0 and len(k3) == 0 and len(u3) == 0,
          'ours=%d known=%d unk=%d' % (len(o3), len(k3), len(u3)))

    # 无源标注时必须进 unclassified 而非静默放行 —— 否则「归属不明」会被当成「本方干净」
    _, o4, k4, u4 = scss_fingerprint('.o_w{--y: $o-gray-200;}')
    check('指纹: 归属不明时必须进 unclassified（不得静默当成本方干净）',
          len(o4) == 0 and len(u4) == 1, 'ours=%d unk=%d' % (len(o4), len(u4)))

    ok = sum(1 for _n, c, _d in cases if c)
    for n, c, d in cases:
        print('%s  %s%s' % ('PASS' if c else 'FAIL', n, ('   [%s]' % d) if (d and not c) else ''))
    print()
    print('probes selftest: %d/%d 通过' % (ok, len(cases)))
    return 0 if ok == len(cases) else 1


def main():
    ap = argparse.ArgumentParser(description='t5 专项探针（与冻结基线分离）')
    ap.add_argument('--selftest', action='store_true', help='只证探针指纹会红（离线）')
    ap.add_argument('--out', default=os.path.join(HERE, 'probes-t5.json'))
    ap.add_argument('--only', choices=['a', 'b'], default=None)
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    # 与既有文件**合并**：只跑 A 或只跑 B 时不该把另一半结果丢掉
    prev = {}
    if os.path.exists(a.out):
        try:
            with open(a.out, encoding='utf-8') as fh:
                prev = json.load(fh) or {}
        except Exception:
            prev = {}
    doc = {
        'schema': 'color-probes/v1',
        'note': ('**探针 ≠ 基线**。本文件不是 §7.3 的色数读数，也不参与 before/after 色数对照；'
                 '它只回答「机制有没有进产物」「元素在不在、可不可读」。'
                 '冻结基线见 baseline-local.json（15:50:33 那份），本工具绝不改写它。'),
        'captured_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        'base_url': BASE,
        'db': DB,
    }
    rc = 0
    if a.only in (None, 'b'):
        b, err = probe_b()
        if err:
            print('探针B 失败：%s' % err, file=sys.stderr)
            rc = 2
        else:
            doc['probe_b_artifact'] = b
            print('探针B（产物定向读）：产物 %d 个，合计 %d B，combined sha256=%s'
                  % (len(b['bundles']), b['combined_bytes'], b['combined_sha256'][:16]))
            for k, v in b['tracked_counts_by_value'].items():
                print('    %-10s 计数=%d' % (k, v))
    if a.only in (None, 'a'):
        v, err = probe_a()
        if err:
            print('探针A 失败：%s' % err, file=sys.stderr)
            rc = rc or 2
        else:
            doc['probe_a_dom'] = v
            print('探针A（DOM 定向读）：%s' % v.get('url'))
            for k in ('navbar', 'dropdownInNavbar', 'dropdownToggle', 'chip'):
                d = v.get(k) or {}
                print('    %-18s count=%-3s %s' % (k, d.get('count'), d.get('verdict')))

    if isinstance(prev, dict):
        for k, v in prev.items():
            if k not in doc:
                doc[k] = v
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print('探针结果 -> %s（基线未被触碰）' % a.out)
    return rc


if __name__ == '__main__':
    sys.exit(main())
