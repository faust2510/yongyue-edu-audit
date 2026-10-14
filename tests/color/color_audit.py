#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全站配色取色量具（t12 · 冻结版）。

为什么存在
    docs/audit/ui-color-audit-2026-09-15.md 的基线抓自**生产** edu.example.org，
    而改动的达标判据要求「同环境 before/after 对照」（§7.5）。本工具把当时一次性调用的
    Tabbit 取色固化成**仓库内可复跑**的量具，并在代码未改动前归档一份**本地 before 基线**。

口径 = §7.3（冻结，before/after 必须同一支量具）
    · 页面集合：见 tests/color/pages.json（frozen6 / legacy4）
    · 属性：text(border 见下) / bg / border / anchor 四列，逐元素 computed 值去重计数
    · 归一：rgba(r,g,b,a) -> rgb(r,g,b)（合并 alpha 变体）
    · 剔除：纯白 rgb(255,255,255)、纯黑 rgb(0,0,0)
    · 实算：legacy4（最初归档的 4 页）= 53；frozen6（§7.2 补页后）= 69  ← 见 selftest 的 F1 断言

属性取值（浏览器侧，见 tests/color/capture_page.js）
    text   = getComputedStyle(el).color
    bg     = getComputedStyle(el).backgroundColor
    border = getComputedStyle(el).borderTopColor
    anchor = <a> 元素的 getComputedStyle(el).color，按归档 schema 追加 " | -"
    可见性 = display!=none 且 visibility!=hidden 且 opacity!=0 且 rect 宽高不全为 0

用法
    python3 tests/color/color_audit.py selftest                      # 只证量具（离线，秒级）
    python3 tests/color/color_audit.py aggregate RAW.json --set legacy4 --expect 53
    python3 tests/color/color_audit.py aggregate RAW.json --set frozen6 --list
    python3 tests/color/color_audit.py capture --base-url http://localhost:8069 --out tests/color/baseline-local-before.json

退出码：0=通过 ｜ 1=量具/门禁失败（读数不一致）｜ 2=ENV（取色器不可用 / 页面未登录 / 页面缺失）
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES_JSON = os.path.join(HERE, 'pages.json')
CAPTURE_JS = os.path.join(HERE, 'capture_page.js')
ARCHIVED_PRODUCTION = os.path.join(HERE, '..', '..', 'docs', 'audit', 'ui-color-raw-2026-09-15.json')
TABBIT = os.path.expanduser('~/.local/bin/tabbit-cli')
TASK = 'ui-color-audit-t12'

# ⚠⚠ 每次 capture 必须用**全新**的 request-id。
#   实测 tabbit 按 (task, request-id) 命中并**回放**上一次的 receipt —— 复用同一个 id 时，
#   nodejs 会直接返回旧结果（连 receipt 的 startedAt 都是旧的），于是「重取」其实什么都没测。
#   2026-09-15 实际踩到：worktree 重取拿回了 15:18:59 的旧读数，一度被误读成
#   「干净重取与污染版完全一致 ⇒ t3 改动等值」。真相是 receipt 回放。
RUN_ID = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')


def _rid(name):
    """带本次运行令牌的 request-id，杜绝 receipt 回放。"""
    return 'cap-%s-%s' % (RUN_ID, name)

PROPS = ('text', 'bg', 'border', 'anchor')
PURE_WHITE = 'rgb(255, 255, 255)'
PURE_BLACK = 'rgb(0, 0, 0)'

# §7.3 冻结读数（selftest 逐条断言；漂移即红）
FROZEN = {
    'legacy4': 53,   # 最初归档的 4 页 —— §7.3 的「= 53」即此数
    'frozen6': 69,   # §7.2 补齐 /my/calendar?view=week 与 /apps 之后的真实全量
}
SELFTEST_CASES = 52

# ------------------------------------------------------------------ ④ 禁用色（v4-t8）
# 背景：docs/plans/color-system-v4.md §6.2.3 曾把 /odoo/contacts 上那一处 bg `#714B67`
# 以 **carve-out → t8** 从判据里扣掉（原文：「判据写『令牌外色 = 0（扣除 carve-out）』」）。
# t8 把那个紫色消灭之后，**carve-out 必须同时消失**——否则它会变成一个永久盲区：
# 后人只要照着 carve-out 表扣，同一处紫色再长回来也不会被任何门禁点名。
# 所以这里把「撤销 carve-out」从一句承诺变成**机械判据**：四属性里出现即 FAIL，
# 并且**不给例外项**（要豁免就得改这张表，改动会被 review 看见）。
FORBIDDEN_COLORS = (
    ('rgb(113, 75, 103)', '#714B67 · Odoo 企业版原厂主色'),
    ('rgb(113, 99, 158)', '#71639E · Odoo 社区版原厂紫'),
)


# ------------------------------------------------------------------ 口径实现
def norm_color(raw):
    """rgba(r,g,b,a) -> rgb(r,g,b)；其余原样返回。' | ' 之后的来源标注丢弃。"""
    c = raw.split('|')[0].strip()
    m = re.match(r'^rgba?\(([^)]+)\)$', c)
    if not m:
        return c
    parts = [p.strip() for p in m.group(1).split(',')]
    return 'rgb(%s)' % ', '.join(parts[:3])


def forbidden_hits(entries):
    """四属性（text/bg/border/anchor）里出现的禁用色 → [(page, prop, color, name, count)]。

    ⚠ 按**归一后**匹配（rgba 变体合并），所以 rgba(113,75,103,.35) 这类半透明写法
    与实色 `#714B67` 一起被抓 —— 它们本来就是同一个紫色，只有实色能过是假门禁。
    """
    out = []
    for e in entries:
        page = e.get('_key') or e.get('key') or '?'
        for prop in PROPS:
            for raw, n in e.get(prop, []) or []:
                got = norm_color(raw)
                for c, name in FORBIDDEN_COLORS:
                    if got == c:
                        out.append((page, prop, got, name, n))
    return out


def load_pages():
    with open(PAGES_JSON, encoding='utf-8') as fh:
        return json.load(fh)


def page_key_of(entry, pages):
    """归档/新抓的条目 -> pages.json 里的 key。"""
    if entry.get('key'):
        return entry['key']
    p = urlparse(entry.get('url', ''))
    tail = p.path + (('?' + p.query) if p.query else '')
    for pg in pages['pages']:
        if pg['path'] == tail:
            return pg['key']
    return None


def select(entries, pages, set_name):
    """按 §7.3 页面集合筛选；集合内有页面缺失 -> ENV(2)，绝不静默少数。"""
    for e in entries:
        e['_key'] = page_key_of(e, pages)
    if set_name in (None, 'all'):
        return entries, None
    want = pages['sets'][set_name]
    have = {e['_key'] for e in entries}
    missing = [k for k in want if k not in have]
    if missing:
        return None, '页面集合 %s 缺页：%s（归档不完整，读数无效）' % (set_name, ','.join(missing))
    return [e for e in entries if e['_key'] in want], None


def distinct(entries):
    """§7.3：四属性 union，rgba 归并，剔除豁免集（纯黑/纯白含全部 α 变体 + transparent）。"""
    s = set()
    for e in entries:
        for p in PROPS:
            for c, _n in e.get(p, []) or []:
                if is_exempt(c):
                    continue
                s.add(norm_color(c))
    return s


def is_exempt(raw):
    """豁免集（captain 2026-09-15 放宽，按**归一后**匹配）。

    归一后为纯黑或纯白的**任何值、含全部 α 变体**（rgba(0,0,0,.7) / rgba(255,255,255,.95) /
    color(srgb 0 0 0 / .097) / #000 / #fff），以及 transparent 与全透明 —— 一律豁免。
    不这样放宽的话，黑色遮罩会被误判成「令牌外色」。
    ⚠ 只豁免「恰好 0 或 255」；rgb(1,1,1)、rgb(254,254,254) 这类近黑近白**仍计入**（与 §7.3 一致）。
    """
    c = raw.split('|')[0].strip().lower()
    if c in ('transparent', ''):
        return True
    col = _rgb(c)
    if col is None:
        return False
    r, g, b, a = col
    if a <= 0.0:
        return True
    if round(r) == 0 and round(g) == 0 and round(b) == 0:
        return True
    if round(r) == 255 and round(g) == 255 and round(b) == 255:
        return True
    return False


def alt_counts(entries):
    """辅助读数：不剔黑白 / 只算 text —— 让「口径绑定」这件事可自证。"""
    keep, text_only = set(), set()
    for e in entries:
        for p in PROPS:
            for c, _n in e.get(p, []) or []:
                keep.add(norm_color(c))
                if p == 'text':
                    text_only.add(norm_color(c))
    return {'keep_black_white': len(keep), 'text_only': len(text_only)}


def per_page_table(entries, pages):
    order = {k: i for i, k in enumerate(pages['sets']['frozen6'])}
    rows = []
    for e in sorted(entries, key=lambda x: order.get(x['_key'], 99)):
        rows.append((e['_key'], e.get('title', '?'), {p: len(e.get(p, []) or []) for p in PROPS}))
    return rows


# ------------------------------------------------- 回归锚点（captain 2026-09-15 追加）
# ① 锚点恒等：门户代表页上 --body-color 必须等于 --text-3 的计算值（且非空）。
#    背景：custom_home.css 原有一行
#      :root, [data-bs-theme] body{ --body-color:#5E6779; ... }
#    靠「同特异度 (0,1,1) + 源码顺序」压过 core 的 [data-bs-theme="light"] body。
#    实现时若把它退化成裸 :root，--body-color 会**无声退回** core 的 #6b7385，
#    压在 --bg #F4F7FA 上 = 4.42 ✗（t112 已修好的对比度回退，且不报错）。
# ② 对比度：数字面上的 (前景, 有效背景) 对里，任何 < 4.5 的文本对都算违规；
#    另把 captain 指名的两对（审计 §3 原始 6 条之外的二次核校新增）列为「出现即 FAIL」。
ANCHOR_PAGES = ('my_home', 'calendar')

# 校名/链接色锚点（eng-web 建议）：判据 = **等于 --brand-action 的 rgb**。
# ⚠ 明确**不**采用「不等于 #0F34C3」这种写法：auto-contrast(o-cc1-link) 会派生 #0955A7，
#   它同样令牌外，却能让「!= #0F34C3」的判据通过 ⇒ 那是又一次「抓不住真问题的门禁」。
BRAND_ANCHOR_TOKENS = ('--brand-action', '--brand-500', '--brand-action-hover')
BRAND_TRAP_VALUES = {
    ('#0f34c3',): '原 auto-contrast 派生链接蓝（审计 §1.3 点名）',
    ('#0955a7',): 'auto-contrast 的**另一个**派生蓝 —— 只改 o-cc1-link 而未进排除表时出现',
    ('#0a217c',): 'derive 出的 hover 蓝',
}


def check_brand_anchor(entry):
    """返回 (ok, 说明)。校名色必须**等于某个品牌令牌值**（优先 --brand-action）。"""
    b = entry.get('brand') or {}
    if not b:
        return False, 'brand 字段缺失（旧版取色存档，需重抓）'
    if not b.get('found'):
        return False, '本页没有 a.navbar-brand 元素（该页不适用，不应静默通过）'
    got = (b.get('color') or '').strip()
    toks = entry.get('tokens') or {}
    want = (toks.get('--brand-action') or '').strip()
    if not got:
        return False, 'brand.color 为空'
    if not want:
        return False, '--brand-action 为空'
    cg, cw = _canon(got), _canon(want)
    ok = bool(cg) and cg == cw
    where = '--brand-action'
    if not ok:
        for names, why in BRAND_TRAP_VALUES.items():
            if cg and cg == _canon(names[0]):
                return False, 'brand.color=%s 命中陷阱：%s（期望 --brand-action=%s）' % (got, why, want)
    return ok, 'brand.color=%s ｜ --brand-action=%s' % (got, want)
ANCHOR_PAIR = ('--body-color', '--text-3')

# (前景, 背景, 可读名, 审计值) —— 出现即 FAIL
REGRESSION_PAIRS = [
    ('#6b7385', '#F4F7FA', '#6b7385 / #F4F7FA', 4.42),
    ('#0E7BF2', '#F4F7FA', '#0E7BF2 / #F4F7FA', 3.80),
]

# color-arch 本轮发现的 3 处「样本外」不合格对（不在审计 §3 原始 6 条内）——
# 同样列为显式检查项、出现即 FAIL。数值已由本工具独立复算核对：2.9703 / 3.5297 / 4.1557。
# 注意：前景是实色、背景是**半透明叠加** ⇒ 必须按 alpha 合成后比，
# 不能用「合并 alpha」的 _canon（那会把 rgba(255,165,0,.18) 与实色 rgb(255,165,0) 混为一谈）。
OUT_OF_SAMPLE_PAIRS = [
    ('#c27d00', 'rgba(255, 165, 0, 0.18)', '#c27d00 / rgba(255,165,0,.18)', 2.97),
    ('#ad7000', 'rgba(255, 165, 0, 0.22)', '#ad7000 / rgba(255,165,0,.22)', 3.53),
    ('#d91f1f', 'rgba(217, 31, 31, 0.12)', '#d91f1f / rgba(217,31,31,.12)', 4.15),
]

ALL_REGRESSION_PAIRS = REGRESSION_PAIRS + OUT_OF_SAMPLE_PAIRS

# 回归监控项（captain 2026-09-15 登记）：**在途待修的已知缺陷**，点名跟踪 + 验证消失。
# 与 REGRESSION_PAIRS 的区别：后者是「设计上不许出现的令牌外色」，这些是「已归因、已派活、按 = 0 核」。
# (前景, 背景, 可读名, 实算值, 归口)
# 权威源：color-arch 规范 §3.2 矩阵（docs/plans/color-system-v4.md 第 567-571 行）。
# 本工具已逐对独立复算，与规范完全一致（无差异）：
#   --fill-active #E8EFF8 → 4.3336 ｜ rgba(--brand-500-rgb,.10) 叠白 #E7F2FE → 4.4284 ｜ b11 active #E1EEFF → 4.2720
# 规范处置（§3.2 第 581 行）：浅蓝调面上的文字**一律改用 --brand-action-hover #0A63CC**（4.59–5.15 ✓）。
MONITOR_PAIRS = [
    ('rgb(12, 109, 215)', 'rgb(207, 229, 252)',
     'B类: --brand-action 压 --brand-100 蓝调面（/apply 按钮文字）',
     3.89, 't4 批B / t8 —— 改用 --brand-action-hover 或 --brand-700'),
    ('rgb(12, 109, 215)', 'rgb(232, 239, 248)',
     'B类: --brand-action 压 --fill-active #E8EFF8',
     4.33, 't4 批B / t8 —— 改用 --brand-action-hover #0A63CC（规范 §3.2）'),
    ('rgb(12, 109, 215)', 'rgb(231, 242, 254)',
     'B类: --brand-action 压 rgba(--brand-500-rgb,.10) 叠白 #E7F2FE',
     4.43, 't4 批B / t8 —— 改用 --brand-action-hover #0A63CC（规范 §3.2）'),
    ('rgb(12, 109, 215)', 'rgb(225, 238, 255)',
     'B类: --brand-action 压 b11 active 面 #E1EEFF',
     4.27, 't4 批B / t8 —— 改用 --brand-action-hover #0A63CC（规范 §3.2）'),
]


# 焦点环回归监控项（captain 2026-09-15 指定）：**t5 修完后这 5 组应全部转 PASS**。
# ⚠ 这条登记的存在理由（captain 原话）：若只覆盖 outline，我们会以为焦点环没问题就发布了。
# (页面, 形态, 环色, 参照背景, 可读名, 实算, 归口)
# ⚠ 归口校准（captain 2026-09-15）：**归口依据 = 页面所属 bundle**，不是环的形态。
#   原先按「环形态像 backend_b11.css:58」把 5 组全部归 t5 —— 那是**按形态猜**，忽略了可达性：
#     · backend bundle（/odoo/*）  → 归 t5
#     · frontend/门户 bundle       → 归 t4 / t6 / t7 / t8（t5 的两个文件够不到门户）
#   报告里必须**分清「归口依据」与「实际可达性」**两列，否则会像上一版那样把门户的环算成 t5 漏修。
# (页面, 形态, 环色, 参照背景, 可读名, 实算, bundle, 归口)
MONITOR_FOCUS = [
    ('home', 'box-shadow', 'rgba(12, 109, 215, 0.25)', 'rgb(255, 255, 255)',
     '.btn-primary 焦点环', 1.43, 'frontend', 't4 / t6 / t7 / t8'),
    ('apply', 'box-shadow', 'rgba(12, 109, 215, 0.25)', 'rgb(255, 255, 255)',
     '.btn-primary 焦点环', 1.43, 'frontend', 't4 / t6 / t7 / t8'),
    ('contacts', 'outline', 'rgb(0, 95, 204)', 'rgb(14, 123, 242)',
     'outline 环（疑 Chrome UA 默认环 #005FCC，产物 0 处定义）', 1.46, 'backend', 't5'),
    ('contacts', 'box-shadow', 'rgba(194, 198, 202, 0.5)', 'rgb(255, 255, 255)',
     '次级控件 box-shadow 环', 1.29, 'backend', 't5'),
    ('contacts', 'outline', 'rgb(0, 95, 204)', 'rgb(113, 75, 103)',
     'Odoo 原厂紫面上的 outline 环', 1.21, 'backend', 't5'),
]


def focus_monitor_status(entries):
    """逐项报告焦点环监控对是否仍出现。返回 [(page, form, name, ratio, count, owner)]。"""
    seen_map = {}
    for e in entries:
        page = e.get('_key') or e.get('key') or '?'
        for p in e.get('focus', []) or []:
            if len(p) < 3:
                continue
            form = p[3] if len(p) > 3 else '?'
            seen_map.setdefault(page, []).append((p[0], p[1], p[2], form))
    out = []
    for page, form, ring, bg, name, val, bundle, owner in MONITOR_FOCUS:
        cnt = 0
        for r, b, c, f in seen_map.get(page, []):
            if f == form and _canon(r) == _canon(ring) and _canon(b) == _canon(bg):
                cnt += c
        out.append((page, form, name, contrast_ratio(ring, bg), cnt, bundle, owner))
    return out


def monitor_status(entries):
    """逐项报告监控对是否仍出现。返回 [(name, seen, ratio, count, owner)]。"""
    out = []
    for fg, bg, name, _val, owner in MONITOR_PAIRS:
        seen = 0
        for e in entries:
            for p in e.get('contrast', []) or []:
                if len(p) < 2:
                    continue
                if _canon(p[0]) == _canon(fg) and _canon(p[1]) == _canon(bg):
                    seen += p[2] if len(p) > 2 else 1
        out.append((name, seen > 0, contrast_ratio(fg, bg), seen, owner))
    return out

MIN_CONTRAST = 4.5
# WCAG 1.4.11：非文本（含焦点环）对比度 >= 3:1
FOCUS_MIN_CONTRAST = 3.0

# ⚠ 生产归档里有 2/6 页带 caps 字段（/my/calendar 与 /apps：text30/bg30/border20/anchor14）
#   —— 说明当年那两页是**带上限**抓的。本工具不设上限；若某页的某属性种类数超过该上限，
#   就说明「生产基线在该属性上是截断值」，本地/生产在该轴上不可比。aggregate 会就此告警。
PROD_CAPS = {'text': 30, 'bg': 30, 'border': 20, 'anchor': 14}


def _rgb(s):
    """'#RRGGBB' / 'rgb()' / 'rgba()' / 'color(srgb r g b / a)' -> (r,g,b,a)；解析不了返回 None。

    必须覆盖 color(srgb …)：Chrome 在混色/分层场景会输出这种形式（归档里实际出现过
    color(srgb 0 0 0 / 0.097647)），漏掉它就会把「带 α 的纯黑」当成一个独立的令牌外色。
    """
    s = (s or '').strip()
    m = re.match(r'^#([0-9a-fA-F]{6})$', s)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    m = re.match(r'^rgba?\(([^)]+)\)$', s)
    if m:
        p = [x.strip() for x in m.group(1).split(',')]
        try:
            v = [float(x) for x in p[:3]]
            a = float(p[3]) if len(p) > 3 else 1.0
        except ValueError:
            return None
        return (v[0], v[1], v[2], a)
    m = re.match(r'^color\(srgb\s+([^)]+)\)$', s)
    if m:
        body = m.group(1).replace('/', ' ').split()
        try:
            v = [float(x) for x in body[:3]]
            a = float(body[3]) if len(body) > 3 else 1.0
        except (ValueError, IndexError):
            return None
        if len(v) < 3:
            return None
        return (v[0] * 255.0, v[1] * 255.0, v[2] * 255.0, a)
    return None


def _canon(s):
    """把颜色归一成 'r,g,b' 便于跨写法比较（#5E6779 == rgb(94, 103, 121)）。"""
    c = _rgb(s)
    if not c:
        return None
    return '%d,%d,%d' % (round(c[0]), round(c[1]), round(c[2]))


def _same_color(a, b, tol=0.5):
    """按 rgba 四元组比较（**不合并 alpha**）—— 回归对必须精确匹配，含透明度。"""
    ca, cb = _rgb(a), _rgb(b)
    if not ca or not cb:
        return False
    return all(abs(ca[i] - cb[i]) <= tol for i in range(4))


def _lum(rgb):
    def ch(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


def contrast_ratio(fg_s, bg_s):
    """WCAG 对比度；半透明前景先压到背景上，半透明背景先压到白底。"""
    fg, bg = _rgb(fg_s), _rgb(bg_s)
    if not fg or not bg:
        return None
    if bg[3] < 1.0:
        bg = (bg[0] * bg[3] + 255 * (1 - bg[3]), bg[1] * bg[3] + 255 * (1 - bg[3]),
              bg[2] * bg[3] + 255 * (1 - bg[3]), 1.0)
    if fg[3] < 1.0:
        fg = (fg[0] * fg[3] + bg[0] * (1 - fg[3]), fg[1] * fg[3] + bg[1] * (1 - fg[3]),
              fg[2] * fg[3] + bg[2] * (1 - fg[3]), 1.0)
    l1, l2 = _lum(fg), _lum(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def check_anchor(entry):
    """outcome 级锚点：body 的**实际文字色**必须等于 --text-3 的计算值（且非空）。

    ⚠ 读取位置修正（captain/eng-web 2026-09-15 真机自证）：
      修复后的声明可能落在 **body 元素**上而非 :root，此时 documentElement 上的 --body-color
      可能仍不是我们的值 ⇒ **只读 documentElement 会误判**（这正是上一版锚点的缺陷）。
      body 的 used color 是最终渲染结果，与声明落点无关，才是可信的锚点。
      documentElement 的值仅作诊断输出，**不参与判定**。
    """
    toks = entry.get('tokens') or {}
    body_color = (entry.get('bodyColor') or '').strip()
    t3 = (toks.get('--text-3') or '').strip()
    diag = (toks.get('--body-color') or '').strip() or '(空)'
    if not body_color:
        return False, 'bodyColor 缺失（旧版取色存档，需用新版 capture 重抓）'
    if not t3:
        return False, '--text-3 为空'
    cb, ct = _canon(body_color), _canon(t3)
    ok = (cb == ct) if (cb and ct) else (body_color.lower() == t3.lower())
    return ok, 'body.color=%s ｜ --text-3=%s ｜ [框架值,不判] documentElement --body-color=%s' % (
        body_color, t3, diag)


def contrast_violations(entries, minimum=MIN_CONTRAST):
    """扫所有实测 (前景, 有效背景) 对，返回 (违规列表, 回归命中列表)。"""
    bad, hits = [], []
    reg = [(a, b, name) for a, b, name, _v in ALL_REGRESSION_PAIRS]
    for e in entries:
        for pair in e.get('contrast', []) or []:
            if len(pair) < 2:
                continue
            fg, bg = pair[0], pair[1]
            cnt = pair[2] if len(pair) > 2 else 0
            r = contrast_ratio(fg, bg)
            if r is None:
                continue
            for a, b, name in reg:
                if _same_color(fg, a) and _same_color(bg, b):
                    hits.append((e.get('_key', '?'), name, fg, bg, cnt, r))
            if r < minimum:
                bad.append((e.get('_key', '?'), fg, bg, cnt, r))
    bad.sort(key=lambda x: x[4])
    return bad, hits


def focus_violations(entries, minimum=FOCUS_MIN_CONTRAST):
    """焦点环对参照背景的对比度，< 3:1 即违规（WCAG 1.4.11）。

    覆盖**两种形态**：outline 与 box-shadow。后者是 Bootstrap 5 / Odoo 以及
    backend_b11.css:58（box-shadow: 0 0 0 .2rem rgba(14,123,242,.35)）用的形态 ——
    **只覆盖 outline 会得到「没抓到」的假绿**，因为我们真要修的那圈环就是 box-shadow。

    环色若带 alpha，contrast_ratio 会先按 alpha 合成到参照背景上再比 ——
    这正是 color-arch 推算 1.08 用的算法，故两者可比。
    返回 (key, ring, bg, count, ratio, form)。
    """
    bad = []
    for e in entries:
        for pair in e.get('focus', []) or []:
            if len(pair) < 2:
                continue
            ring, bg = pair[0], pair[1]
            cnt = pair[2] if len(pair) > 2 else 0
            form = pair[3] if len(pair) > 3 else '?'
            # 防御纵深：全透明环（Chrome 会输出 rgba(0,0,0,0)）不是「画出来的环」，
            # 不排掉会得到一批 1.00 的假违规。
            rg = _rgb(ring)
            if rg is not None and rg[3] <= 0.01:
                continue
            r = contrast_ratio(ring, bg)
            if r is None:
                continue
            if r < minimum:
                bad.append((e.get('_key', '?'), ring, bg, cnt, r, form))
    bad.sort(key=lambda x: x[4])
    return bad


# ------------------------------------------------------------------ tabbit 驱动
def _parse_json_stdout(out):
    for line in reversed((out or '').strip().splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def tabbit_nodejs(js, request_id, timeout_ms=90000):
    """提交一段 JS 给 Tabbit 浏览器端执行，返回 (value, error)。"""
    if not os.path.exists(TABBIT):
        return None, 'ENV: 找不到 tabbit-cli（%s）' % TABBIT
    cmd = [TABBIT, 'nodejs', '--task', TASK, '--request-id', request_id,
           '--timeout-ms', str(timeout_ms)]
    try:
        p = subprocess.run(cmd, input=js, capture_output=True, text=True,
                           timeout=timeout_ms / 1000.0 + 90)
    except subprocess.TimeoutExpired:
        return None, 'ENV: tabbit-cli 超时（request-id=%s）' % request_id
    resp = _parse_json_stdout(p.stdout) or _parse_json_stdout(p.stderr)
    if resp is None:
        return None, 'ENV: tabbit-cli 无 JSON 输出 rc=%s out=%s err=%s' % (
            p.returncode, (p.stdout or '')[:300], (p.stderr or '')[:300])
    status = resp.get('status')
    res = resp.get('result') or {}
    if status != 'succeeded':
        return None, 'ENV: request %s status=%s %s' % (
            request_id, status, json.dumps(res, ensure_ascii=False)[:400])
    # 结果既可能内联，也可能落成 resource 句柄
    if 'value' in res:
        return res['value'], None
    handle = res.get('resource') or res.get('resourceId') or (
        res.get('nextAction', {}) or {}).get('resource')
    if handle:
        rid = handle if isinstance(handle, str) else (handle.get('id') or handle.get('resourceId'))
        if rid:
            out = subprocess.run([TABBIT, 'resource', '--task', TASK, '--resource', str(rid),
                                  '--offset', '0', '--max-bytes', '65536'],
                                 capture_output=True, text=True, timeout=180)
            blob = _parse_json_stdout(out.stdout)
            if blob is not None:
                return blob, None
        return None, 'ENV: request %s 返回了 resource 句柄但读不回来' % request_id
    return None, 'ENV: request %s 结果形状未知: %s' % (
        request_id, json.dumps(res, ensure_ascii=False)[:400])


def _render_capture_js(url, label):
    with open(CAPTURE_JS, encoding='utf-8') as fh:
        js = fh.read()
    return js.replace('__URL__', url).replace('__LABEL__', label)


# ⚠ 不能 browser.newContext()：TabbitDance 拒绝 Target.createBrowserContext。
#   公开页改用共享 context + **按域**清 cookie（只清 localhost，绝不碰用户 edu.example.org 登录态）。
#   ⚠ 浏览器侧 Node realm 把 localhost 解析成 ::1，而 compose 只映了 IPv4 ⇒ 一律用 127.0.0.1。
RESET_JS = '''
const base = "__BASE__";
await context.clearCookies({ domain: "__HOST__" });
const probe = await context.request.get(base + "/my/home", { maxRedirects: 0 });
return { label: "reset", probeStatus: probe.status(),
         probeLocation: probe.headers()["location"] || null };
'''

LOGIN_JS = '''
const res = await context.request.post("__BASE__/web/session/authenticate", {
  data: { jsonrpc: "2.0", method: "call",
          params: { db: "__DB__", login: "__USER__", password: "__PASS__" } },
});
const body = await res.text();
return { label: "login", status: res.status(),
         authed: body.indexOf('"uid"') >= 0, body: body.slice(0, 200) };
'''


def capture_one(base, key, kind, attempts=2):
    """取单页；失败重试一次（高负载下 goto 偶发超时）。成功返回条目，失败打印 ENV 并返回 None。"""
    path = None
    for pg in load_pages()['pages']:
        if pg['key'] == key:
            path = pg['path']
    for attempt in range(1, attempts + 1):
        js = _render_capture_js(base + path, key)
        # 取色程序最坏 ≈ goto 120s + 兜底等待，逼近执行器上限 180s
        val, err = tabbit_nodejs(js, _rid('%s-%d' % (key, attempt)), timeout_ms=180000)
        if err:
            print('  重试%s: %s' % (attempt, err[:200]), file=sys.stderr)
            continue
        e = val.get('value') if isinstance(val, dict) else None
        if not e:
            print('  重试%s: %s 取色结果为空' % (attempt, key), file=sys.stderr)
            continue
        e['key'] = key
        e['base_url'] = base
        print('  %-5s  %-9s %-34s scanned=%-5s visible=%-5s' % (
            kind, key, e['url'], e.get('scanned'), e.get('visible')))
        return e
    print('ENV: %s 取色失败（已试 %d 次）' % (key, attempts), file=sys.stderr)
    return None


def cmd_capture(args):
    pages = load_pages()
    want = args.set or 'frozen6'
    keys = pages['sets'][want]
    specs = [p for p in pages['pages'] if p['key'] in keys]
    base = args.base_url.rstrip('/')
    entries = []

    public = [p for p in specs if not p['auth']]
    private = [p for p in specs if p['auth']]

    # 1) 公开页：先按域清 localhost cookie（保证「未登录」读数），再逐页取色
    if public:
        host = urlparse(base).hostname or 'localhost'
        val, err = tabbit_nodejs(
            RESET_JS.replace('__BASE__', base).replace('__HOST__', host), _rid('reset'), timeout_ms=60000)
        if err:
            print(err, file=sys.stderr)
            return 2
        # 清干净后 /my/home 必须被挡到登录页；否则「公开页」读数名不副实
        if val.get('probeStatus') not in (301, 302, 303, 401, 403):
            print('ENV: localhost 会话未清干净（/my/home -> %s %s），公开页读数不可信'
                  % (val.get('probeStatus'), val.get('probeLocation')), file=sys.stderr)
            return 2
        print('  reset  localhost cookie 已清（/my/home -> %s，确认是游客态）' % val.get('probeStatus'))
        for p in public:
            e = capture_one(base, p['key'], 'guest')
            if e is None:
                return 2
            entries.append(e)

    # 2) 登录（cookie 落在共享 context，供后续逐页取色复用）
    if private:
        js = (LOGIN_JS.replace('__BASE__', base).replace('__DB__', args.db)
              .replace('__USER__', args.login_user).replace('__PASS__', args.login_pass))
        val, err = tabbit_nodejs(js, _rid('login'), timeout_ms=60000)
        if err:
            print(err, file=sys.stderr)
            return 2
        if not val.get('authed'):
            print('ENV: 本地登录失败（%s）-> %s' % (args.login_user, val.get('body')), file=sys.stderr)
            return 2
        print('  login  %s ok' % args.login_user)

        for p in private:
            e = capture_one(base, p['key'], 'auth')
            if e is None:
                return 2
            entries.append(e)

    # 3) 登录态校验：受登录保护的页面不允许落到 /web/login
    for e in entries:
        if '/web/login' in e.get('url', '') or '/login' == urlparse(e['url']).path:
            print('ENV: 页面 %s 落到登录页（%s）—— 未登录读数无效' % (e['key'], e['url']), file=sys.stderr)
            return 2

    order = {p['key']: i for i, p in enumerate(pages['pages'])}
    entries.sort(key=lambda x: order.get(x['key'], 99))

    doc = {
        'schema': 'color-gauge/v1',
        'captured_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        'base_url': base,
        'page_set': want,
        'spec': pages['spec'],
        'entries': entries,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print('归档 -> %s（%d 页）' % (args.out, len(entries)))
    return 0


# ------------------------------------------------------------------ aggregate
def cmd_aggregate(args):
    pages = load_pages()
    with open(args.raw, encoding='utf-8') as fh:
        doc = json.load(fh)
    entries = doc['entries'] if isinstance(doc, dict) else doc
    sel, err = select(entries, pages, args.set)
    if err:
        print(err, file=sys.stderr)
        return 2

    print('source: %s' % args.raw)
    print('page set: %s (%d 页)' % (args.set, len(sel)))
    print('%-10s %-24s %5s %5s %5s %5s' % ('key', 'title', 'text', 'bg', 'bdr', 'link'))
    for k, t, c in per_page_table(sel, pages):
        print('%-10s %-24s %5d %5d %5d %5d' % (k, t[:24], c['text'], c['bg'], c['border'], c['anchor']))

    over = []
    for k, _t, c in per_page_table(sel, pages):
        for p in PROPS:
            if c[p] > PROD_CAPS[p]:
                over.append((k, p, c[p], PROD_CAPS[p]))
    if over:
        print()
        print('⚠ 超出生产归档上限（生产那两页是带上限抓的 ⇒ 该属性上不可比）：')
        for k, p, got, cap in over:
            print('    %-9s %-7s 实得 %d > 生产上限 %d' % (k, p, got, cap))

    S = distinct(sel)
    alt = alt_counts(sel)
    print()
    print('distinct（§7.3：四属性 union / rgba 归并 / 剔纯白纯黑） = %d' % len(S))
    print('  辅助：不剔黑白 = %d ｜ 只算 text = %d' % (alt['keep_black_white'], alt['text_only']))
    if args.list:
        for i, c in enumerate(sorted(S), 1):
            print('%3d. %s' % (i, c))

    if args.expect is None:
        return 0
    ok = len(S) == args.expect
    print()
    print('EXPECT %d -> %s' % (args.expect, 'PASS' if ok else 'FAIL'))
    return 0 if ok else 1


# ------------------------------------------------------------------ assert
def cmd_assert(args):
    """回归锚点门禁：① 锚点恒等 ② 对比度（含两对「出现即 FAIL」的回归对）。"""
    pages = load_pages()
    with open(args.raw, encoding='utf-8') as fh:
        doc = json.load(fh)
    entries = doc['entries'] if isinstance(doc, dict) else doc
    sel, err = select(entries, pages, args.set)
    if err:
        print(err, file=sys.stderr)
        return 2
    by_key = {e['_key']: e for e in sel}
    anchor_fail = []

    print('source: %s  ｜ page set: %s (%d 页)' % (args.raw, args.set, len(sel)))
    print()
    print('=== ① 锚点恒等（outcome 级）：body 的**实际文字色**必须 == --text-3（且非空）===')
    print('   （读取位置按 captain 2026-09-15 修正：判据 = ③ body.color；')
    print('     ② body 的 --body-color 与 ① documentElement 的 --body-color 一并打印，①为「框架值」不参与判定）')
    for k in ANCHOR_PAGES:
        e = by_key.get(k)
        if e is None:
            print('  FAIL  %-9s 缺页，无法判定' % k)
            anchor_fail.append('%s 缺页' % k)
            continue
        if not e.get('tokens'):
            print('  ENV   %-9s 存档无 tokens 字段（旧版取色），需用新版 capture 重抓' % k)
            anchor_fail.append('%s 无 tokens 数据' % k)
            continue
        ok, why = check_anchor(e)
        print('  %s  %-9s %s' % ('PASS ' if ok else 'FAIL ', k, why))
        if not ok:
            anchor_fail.append('%s: %s' % (k, why))

    print()
    print('=== ①b 校名/链接色锚点：必须 == --brand-action 的 rgb ===')
    print('   （**故意不写成 "!= #0F34C3"**：auto-contrast 会派生 #0955A7，同样令牌外却能骗过后者）')
    b_none = [k for k, e in by_key.items() if 'brand' not in e]
    b_app = [(k, e) for k, e in sorted(by_key.items()) if (e.get('brand') or {}).get('found')]
    b_na = [k for k, e in by_key.items() if (e.get('brand') or {}).get('found') is False]
    if b_none:
        print('  ENV   %d 页存档无 brand 字段（旧版取色）⇒ 该项在旧快照上不可判，需重抓' % len(b_none))
        anchor_fail.append('brand 字段缺失（旧存档）')
    for k, e in b_app:
        ok, why = check_brand_anchor(e)
        print('  %s  %-9s %s' % ('PASS ' if ok else 'FAIL ', k, why))
        if not ok:
            anchor_fail.append('%s 校名色: %s' % (k, why))
    if b_na:
        print('  --    以下页面无 a.navbar-brand，不适用（既不判过也不判错）：%s' % ','.join(b_na))

    print()
    print('=== ② 对比度：任何实测文本对 < %.1f:1 即违规 ===' % MIN_CONTRAST)
    bad, hits = contrast_violations(sel)
    for k, name, fg, bg, cnt, r in hits:
        print('  FAIL  回归对命中 %-9s %-22s %s on %s (x%d) = %.2f' % (k, name, fg, bg, cnt, r))
    if not hits:
        print('  PASS  两对二次核校回归对（#6b7385/#F4F7FA、#0E7BF2/#F4F7FA）均未出现')
    if bad:
        print('  不达标文本对共 %d 组（按对比度升序，最多列 %d）：' % (len(bad), args.max_show))
        for k, fg, bg, cnt, r in bad[:args.max_show]:
            print('    %-9s %-24s on %-24s x%-4d = %.2f' % (k, fg, bg, cnt, r))
    else:
        print('  PASS  无 < %.1f:1 的文本对' % MIN_CONTRAST)

    print()
    print('=== ②b 回归监控项（在途待修，按 = 0 核）===')
    mons = monitor_status(sel)
    for name, seen, r, cnt, owner in mons:
        if seen:
            print('  ✗ 仍出现 x%-3d = %.2f ｜ %s' % (cnt, r or 0, name))
            print('      归口：%s' % owner)
        else:
            # ⚠ 措辞刻意不用「已消失」：本页集没观测到 ≠ 已被修好（可能只是这 6 页不渲染该面）。
            print('  – 本页集未见（0）｜ %s' % name)
    still = [m for m in mons if m[1]]

    print()
    print('=== ③b 焦点环回归监控项（t5 修完后应全部转 PASS）===')
    fmons = focus_monitor_status(sel)
    print('  注：**归口依据 = 页面所属 bundle**（backend⇒t5；frontend/门户⇒t4/t6/t7/t8），不是环的形态；')
    print('      「仍出现」只表示该页当前仍可测到，**不等于归口方未修**（门户项 t5 本就不可达）。')
    for page, form, name, r, cnt, bundle, owner in fmons:
        if cnt:
            print('  ✗ 仍出现 %-9s [%-10s] x%-3d = %.2f ｜ %s' % (page, form, cnt, r or 0, name))
            print('       归口依据 bundle=%-8s ⇒ 归口 %s' % (bundle, owner))
        else:
            print('  ✓ 已消失 %-9s [%-10s]      ｜ bundle=%s ⇒ %s' % (page, form, bundle, owner))
    fstill = [m for m in fmons if m[4]]

    print()
    print('=== ③ 焦点环：outline + box-shadow 两种形态，环色(合成后) 对参照背景 < %.1f:1 即违规（WCAG 1.4.11）===' % FOCUS_MIN_CONTRAST)
    fbad = focus_violations(sel)
    have_focus = any(e.get('focus') is not None for e in sel)
    if not have_focus:
        print('  （本存档无 focus 字段 —— 旧版取色所生成，需重抓才纳入判定）')
    elif fbad:
        print('  不达标焦点环 %d 组：' % len(fbad))
        for k, ring, bg, cnt, r, form in fbad[:args.max_show]:
            print('    %-9s [%-10s] 环 %-27s on %-24s x%-3d = %.2f' % (k, form, ring, bg, cnt, r))
    else:
        print('  PASS 无 < %.1f:1 的焦点环' % FOCUS_MIN_CONTRAST)
    print('  覆盖说明：**outline 与 box-shadow 两种形态都覆盖**（后者是 backend_b11.css:58 那圈环的形态）；')

    print()
    print('=== ④ 禁用色：Odoo 原厂紫出现即 FAIL（carve-out 已于 v4-t8 撤销，本项**无例外**）===')
    fhits = forbidden_hits(sel)
    if fhits:
        for page, prop, color, name, cnt in fhits:
            print('  FAIL  %-9s %-7s %-20s x%-4d %s' % (page, prop, color, cnt, name))
        print('        → 撤销 carve-out 后这一处必须靠页面自己达标；')
        print('          历史出处见 docs/plans/color-system-v4.md §6.2.3（carve-out 表已作废）')
    else:
        print('  PASS  %d 个禁用色在 %d 页 × 四属性里 0 命中（本页集未观测到，不等于别处没有）'
              % (len(FORBIDDEN_COLORS), len(sel)))

    print()
    print('读数：对比度不达标文本对 = %d ｜ 监控项仍出现 = %d ｜ 焦点环监控仍出现 = %d ｜ 不达标焦点环 = %d ｜ 回归对命中 = %d ｜ 锚点失败（含校名色）= %d ｜ 禁用色命中 = %d'
          % (len(bad), len(still), len(fstill), len(fbad), len(hits), len(anchor_fail), len(fhits)))
    rc = 1 if (anchor_fail or hits or (have_focus and fbad) or still or fstill or fhits) else 0
    if args.expect_violations is not None:
        ok = (len(bad) == args.expect_violations)
        print('EXPECT 不达标对数 %d -> %s' % (args.expect_violations, 'PASS' if ok else 'FAIL'))
        if not ok:
            rc = 1
    print('VERDICT:', 'FAIL' if rc else 'PASS')
    return rc


# ------------------------------------------------------------------ tokens
def cmd_tokens(args):
    """逐页打印关键令牌计算值 —— 用来发现「换了令牌但页面没变」的静默失效。"""
    pages = load_pages()
    with open(args.raw, encoding='utf-8') as fh:
        doc = json.load(fh)
    entries = doc['entries'] if isinstance(doc, dict) else doc
    sel, err = select(entries, pages, args.set)
    if err:
        print(err, file=sys.stderr)
        return 2
    keys = ['--body-color', '--text-3', '--brand-action', '--bg']
    print('source: %s  ｜ page set: %s' % (args.raw, args.set))
    print('%-10s %-16s %-16s %-16s %-16s %-6s' % tuple(['key'] + keys + ['anchor']))
    miss = 0
    for e in sel:
        toks = e.get('tokens')
        if not toks:
            print('%-10s （无 tokens 字段 —— 旧版取色存档）' % e['_key'])
            miss += 1
            continue
        ok, _why = check_anchor(e)
        print('%-10s %-16s %-16s %-16s %-16s %-6s' % (
            e['_key'],
            (toks.get('--body-color') or '')[:16],
            (toks.get('--text-3') or '')[:16],
            (toks.get('--brand-action') or '')[:16],
            (toks.get('--bg') or '')[:16],
            'ok' if ok else 'FAIL'))
    if miss:
        print()
        print('⚠ %d 页无 tokens 数据：该存档由旧版 capture 生成，需重抓才能做令牌级 before/after 比对' % miss)

    # ---- 判据 ④：与令牌源逐项对比（绝对判据，不需要 before 里有同名字段）----
    src, serr = load_token_source()
    print()
    if serr:
        print(serr, file=sys.stderr)
        return 2
    checked, drift = token_drift(sel, src)
    sdrift = [d for d in drift if d[1] in STATUS_TOKENS]
    odrift = [d for d in drift if d[1] not in STATUS_TOKENS]
    print('=== ④ 状态色与令牌源对比（scripts/color_tokens.json，§7.4 唯一输入）===')
    print('   已比对 %d 项（仅统计两侧都有值的；%d 个令牌名 × %d 页）' % (checked, len(src), len(sel)))
    print('   **判据 = 状态色 %s 必须 == 令牌值**' % '/'.join(STATUS_TOKENS))
    if sdrift:
        print('   ✗ 状态色漂移 %d 项：' % len(sdrift))
        for k, name, got, want in sdrift:
            print('     %-9s %-12s 页面=%s  令牌源=%s' % (k, name, got, want))
    else:
        print('   ✓ 状态色无漂移（抓到几项就一致几项）')
    if odrift:
        print('   ℹ 其它字段漂移 %d 项（INFO，不判定）：' % len(odrift))
        for k, name, got, want in odrift[:10]:
            print('     %-9s %-18s 页面=%s  令牌源=%s' % (k, name, got, want))
        print('     注：documentElement 的 --body-color 在后台上取到 Bootstrap 默认值，')
        print('         属已知「框架值」现象（判据看 body.color），故不据此判失败。')
    rc = 0 if not sdrift else 1
    if miss:
        rc = 2
    print('VERDICT:', 'PASS' if rc == 0 else ('FAIL' if rc == 1 else 'ENV(存档缺字段)'))
    return rc


# ------------------------------------------------------------------ selftest
def selftest():
    cases = []

    def check(name, cond, detail=''):
        cases.append((name, bool(cond), detail))

    # 归一化规则
    check('norm: rgba 合并 alpha',
          norm_color('rgba(14, 123, 242, 0.5)') == 'rgb(14, 123, 242)',
          norm_color('rgba(14, 123, 242, 0.5)'))
    check('norm: rgb 原样',
          norm_color('rgb(33, 37, 41)') == 'rgb(33, 37, 41)', norm_color('rgb(33, 37, 41)'))
    check('norm: 非 rgb 形式原样',
          norm_color('color(srgb 0.5 0.5 0.5 / 0.2)') == 'color(srgb 0.5 0.5 0.5 / 0.2)',
          norm_color('color(srgb 0.5 0.5 0.5 / 0.2)'))
    check('norm: " | " 来源标注被丢弃',
          norm_color('rgb(78, 90, 112) | -') == 'rgb(78, 90, 112)',
          norm_color('rgb(78, 90, 112) | -'))

    # 剔除规则（正向：该剔的剔掉；反向：近似的别误剔）
    fixture = [{'text': [['rgb(255, 255, 255)', 9], ['rgb(0, 0, 0)', 9],
                         ['rgba(1, 2, 3, 1)', 1], ['rgb(254, 255, 255)', 1], ['rgb(1, 1, 1)', 1]],
                'bg': [], 'border': [], 'anchor': []}]
    got = distinct(fixture)
    check('剔除: 纯白/纯黑被剔除，近似色保留',
          got == {'rgb(1, 2, 3)', 'rgb(254, 255, 255)', 'rgb(1, 1, 1)'},
          sorted(got))

    # 豁免集放宽（captain 2026-09-15）：归一后纯黑/纯白的**全部 α 变体** + transparent 一律豁免。
    # 这条不做的后果：黑色遮罩会被误判成「令牌外色」。
    check('豁免: rgba(0, 0, 0, 0.7) 豁免',
          is_exempt('rgba(0, 0, 0, 0.7)') is True)
    check('豁免: rgba(255, 255, 255, 0.95) 豁免',
          is_exempt('rgba(255, 255, 255, 0.95)') is True)
    check('豁免: color(srgb 0 0 0 / 0.097647) 豁免 —— 本仓实际出现过，此前是漏网的',
          is_exempt('color(srgb 0 0 0 / 0.097647)') is True)
    check('豁免: color(srgb 1 1 1 / 0.5) 豁免',
          is_exempt('color(srgb 1 1 1 / 0.5)') is True)
    check('豁免: transparent 与全透明豁免',
          is_exempt('transparent') is True and is_exempt('rgba(0, 0, 0, 0)') is True)

    # ⚠ 反向：绝不能过度豁免 —— 生产 53 里就有 color(srgb 0.0352941 …) 这种深色，
    #   误豁免会直接改动冻结读数（53/69）。
    check('豁免: 不得误豁免近似色（含生产 53 里的 color(srgb …) 深色）',
          is_exempt('color(srgb 0.0352941 0.254902 0.290196 / 0.15)') is False
          and is_exempt('rgb(1, 1, 1)') is False
          and is_exempt('rgb(254, 254, 254)') is False
          and is_exempt('rgb(231, 215, 184)') is False)
    check('豁免: 锚点值 "rgb(78, 90, 112) | -" 的 " | " 后缀不影响判定',
          is_exempt('rgb(0, 0, 0) | -') is True and is_exempt('rgb(78, 90, 112) | -') is False)

    # 口径绑定：同一份数据，不同口径必须给出不同数（证明「口径不绑定则指标不可比」）
    a = {'text': [['rgb(200, 200, 200)', 1]], 'bg': [['rgb(9, 9, 9)', 1]],
         'border': [['rgb(255, 255, 255)', 1]], 'anchor': [['rgb(0, 0, 0)', 1]]}
    check('口径绑定: 剔黑白后只算 2 色，不剔则 4 色',
          len(distinct([a])) == 2 and alt_counts([a])['keep_black_white'] == 4,
          '%d vs %d' % (len(distinct([a])), alt_counts([a])['keep_black_white']))

    # ---- 回归锚点（captain 2026-09-15 追加；先证它俩都会红）----
    check('对比度: 黑白 = 21.000（WCAG 标定）',
          abs((contrast_ratio('rgb(0, 0, 0)', 'rgb(255, 255, 255)') or 0) - 21.0) < 0.005,
          '%.4f' % (contrast_ratio('rgb(0, 0, 0)', 'rgb(255, 255, 255)') or 0))
    check('对比度: #6b7385 / #F4F7FA = 4.42（与审计值相符）',
          abs((contrast_ratio('#6b7385', '#F4F7FA') or 0) - 4.42) < 0.005,
          '%.4f' % (contrast_ratio('#6b7385', '#F4F7FA') or 0))
    check('对比度: #0E7BF2 / #F4F7FA = 3.80（与审计值相符）',
          abs((contrast_ratio('#0E7BF2', '#F4F7FA') or 0) - 3.80) < 0.005,
          '%.4f' % (contrast_ratio('#0E7BF2', '#F4F7FA') or 0))
    check('对比度: #RRGGBB 与 rgb() 跨写法等价',
          contrast_ratio('#5E6779', '#F4F7FA') == contrast_ratio('rgb(94, 103, 121)', 'rgb(244, 247, 250)'))

    # color-arch 的 3 处「样本外」不合格对：数值必须与发现值相符（半透明背景要合成后再算）
    check('样本外: #c27d00 / rgba(255,165,0,.18) = 2.97',
          abs((contrast_ratio('#c27d00', 'rgba(255, 165, 0, 0.18)') or 0) - 2.97) < 0.02,
          '%.4f' % (contrast_ratio('#c27d00', 'rgba(255, 165, 0, 0.18)') or 0))
    check('样本外: #ad7000 / rgba(255,165,0,.22) = 3.53',
          abs((contrast_ratio('#ad7000', 'rgba(255, 165, 0, 0.22)') or 0) - 3.53) < 0.02,
          '%.4f' % (contrast_ratio('#ad7000', 'rgba(255, 165, 0, 0.22)') or 0))
    check('样本外: #d91f1f / rgba(217,31,31,.12) = 4.15',
          abs((contrast_ratio('#d91f1f', 'rgba(217, 31, 31, 0.12)') or 0) - 4.15) < 0.02,
          '%.4f' % (contrast_ratio('#d91f1f', 'rgba(217, 31, 31, 0.12)') or 0))

    # 三对都在 ALL_REGRESSION_PAIRS 里 ⇒ 出现即被命中（含半透明背景，且不得与实色混淆）
    _oos = [{'key': 'my_home', 'contrast': [['rgb(194, 125, 0)', 'rgba(255, 165, 0, 0.18)', 2]]}]
    _b4, _h4 = contrast_violations(_oos)
    check('样本外: 出现必被命中（3 对全部入列）',
          len(_h4) == 1 and len(_b4) == 1 and len(ALL_REGRESSION_PAIRS) == 5,
          'hits=%d bad=%d pairs=%d' % (len(_h4), len(_b4), len(ALL_REGRESSION_PAIRS)))
    _solid = [{'key': 'my_home', 'contrast': [['rgb(194, 125, 0)', 'rgb(255, 165, 0)', 2]]}]
    _b5, _h5 = contrast_violations(_solid)
    check('样本外: 不得把实色 rgb(255,165,0) 误判为半透明回归对',
          len(_h5) == 0, 'hits=%d' % len(_h5))

    # 焦点环：<3:1 必红、>=3:1 不误报（captain 提到现役贴按钮场景 1.08 ✗）
    _fr = [{'key': 'my_home', 'focus': [['rgb(200, 200, 200)', 'rgb(210, 210, 210)', 1]]}]
    check('焦点环: 贴按钮 1.08:1 必被判违规',
          len(focus_violations(_fr)) == 1,
          '%.2f' % (contrast_ratio('rgb(200, 200, 200)', 'rgb(210, 210, 210)') or 0))
    _fr2 = [{'key': 'my_home', 'focus': [['rgb(0, 0, 0)', 'rgb(255, 255, 255)', 1]]}]
    check('焦点环: 21:1 不误报', len(focus_violations(_fr2)) == 0)

    # box-shadow 形态（纳入本轮范围的决定性理由：backend_b11.css:58 那圈环就是这种形态）
    _bs = contrast_ratio('rgba(14, 123, 242, 0.35)', 'rgb(12, 109, 215)')
    check('焦点环: box-shadow rgba(14,123,242,.35) 合成到按钮面 #0C6DD7 → 1.08（与 color-arch 推算相符）',
          _bs is not None and abs(_bs - 1.08) < 0.01, '%.4f' % (_bs or 0))
    _fr3 = [{'key': 'my_home', 'focus': [['rgba(14, 123, 242, 0.35)', 'rgb(12, 109, 215)', 4, 'box-shadow']]}]
    _b6 = focus_violations(_fr3)
    check('焦点环: box-shadow 形态的违规必被命中且带 form 标注',
          len(_b6) == 1 and _b6[0][5] == 'box-shadow', str(_b6[:1]))
    _transparent = [{'key': 'home', 'focus': [['rgba(0, 0, 0, 0)', 'rgb(255, 255, 255)', 3, 'box-shadow']]}]
    check('焦点环: 全透明环 rgba(0,0,0,0) 不得算作违规（否则得到 1.00 的假违规）',
          len(focus_violations(_transparent)) == 0)

    # 判据 ④ 的机械比对：token_drift 必须能抓到状态色漂移，且不得误报
    _src = {'--success': {'value': '#127A50'}, '--info': {'value': '#0E7BF2'}}
    _ok_e = [{'key': 'home', 'tokens': {'--success': '#127A50', '--info': 'rgb(14, 123, 242)'}}]
    _bad_e = [{'key': 'home', 'tokens': {'--success': '#1FA971', '--info': '#0E7BF2'}}]
    _c1, _d1 = token_drift(_ok_e, _src)
    _c2, _d2 = token_drift(_bad_e, _src)
    check('判据④: 跨写法（#hex vs rgb()）不误报',
          _c1 == 2 and len(_d1) == 0, 'checked=%d drift=%d' % (_c1, len(_d1)))
    check('判据④: 状态色被改回旧值 #1FA971 必被抓到',
          _c2 == 2 and len(_d2) == 1 and _d2[0][1] == '--success', str(_d2[:1]))

    # 回归监控项（captain 登记）：必须能点名「仍出现」，也能确认「已消失」
    _m_seen = [{'key': 'apply', 'contrast': [['rgb(12, 109, 215)', 'rgb(207, 229, 252)', 1]]}]
    _m_gone = [{'key': 'apply', 'contrast': [['rgb(0, 0, 0)', 'rgb(255, 255, 255)', 1]]}]
    _ms1 = monitor_status(_m_seen)
    _ms2 = monitor_status(_m_gone)
    check('监控项: 3.89 那一对出现时必被点名，且实算值 ≈3.89（登记表现有 %d 项）' % len(MONITOR_PAIRS),
          len(_ms1) == len(MONITOR_PAIRS) and _ms1[0][1] is True
          and abs((_ms1[0][2] or 0) - 3.89) < 0.01,
          str(_ms1[:2]))
    check('监控项: 本页集未见时报 0（不得谎称「已消失」）',
          len(_ms2) == len(MONITOR_PAIRS) and all(m[1] is False for m in _ms2), str(_ms2[:2]))

    # B 类三对：数值必须与 color-arch 规范 §3.2 矩阵逐位相符（docs/plans/color-system-v4.md:567-571）
    _b1 = contrast_ratio('#0C6DD7', '#E8EFF8')
    _b2 = contrast_ratio('#0C6DD7', '#E7F2FE')
    _b3 = contrast_ratio('#0C6DD7', '#E1EEFF')
    _b4 = contrast_ratio('#0C6DD7', '#EAF4FF')
    check('B类三对与规范 §3.2 相符（4.33 / 4.43 / 4.27）',
          abs((_b1 or 0) - 4.33) < 0.01 and abs((_b2 or 0) - 4.43) < 0.01 and abs((_b3 or 0) - 4.27) < 0.01,
          '%.4f / %.4f / %.4f' % (_b1 or 0, _b2 or 0, _b3 or 0))
    check('B类临界值：--brand-50 上 --brand-action = 4.5127，余量仅 +0.0127（易被舍入翻面）',
          abs((_b4 or 0) - 4.5127) < 0.001 and 0 < (_b4 - 4.5) < 0.02,
          '%.4f (margin %+.4f)' % (_b4 or 0, (_b4 - 4.5)))

    # 焦点环监控项（captain 指定：t5 修完后这 5 组应全部转 PASS）
    _fm_seen = [{'key': 'home', 'focus': [['rgba(12, 109, 215, 0.25)', 'rgb(255, 255, 255)', 10, 'box-shadow']]}]
    _fm_gone = [{'key': 'home', 'focus': [['rgb(0, 0, 0)', 'rgb(255, 255, 255)', 1, 'outline']]}]
    _f1 = focus_monitor_status(_fm_seen)
    _f2 = focus_monitor_status(_fm_gone)
    check('焦点环监控: 5 项入列且 .btn-primary 那项出现时被点名（含 x10 与实算 1.43）',
          len(_f1) == 5 and _f1[0][4] == 10 and abs((_f1[0][3] or 0) - 1.43) < 0.01, str(_f1[:1]))
    check('焦点环监控: 修好后必须全部报「已消失」（t5 收口可验证）',
          all(m[4] == 0 for m in _f2), str([m[4] for m in _f2]))

    # 锚点：读 **body 的 used color**（outcome 级），不是 documentElement 的 --body-color。
    _ok = {'bodyColor': 'rgb(94, 103, 121)', 'tokens': {'--text-3': '#5E6779'}}
    _bad = {'bodyColor': 'rgb(107, 115, 133)', 'tokens': {'--text-3': '#5E6779'}}
    _empty = {'bodyColor': '', 'tokens': {'--text-3': '#5E6779'}}
    _notokens = {'bodyColor': 'rgb(94, 103, 121)', 'tokens': {}}
    check('锚点恒等: body.color == --text-3 跨写法（rgb() vs #hex）→ PASS',
          check_anchor(_ok)[0] is True)
    check('锚点恒等: body.color 退回主题灰 #6b7385 → 必须 FAIL（要抓的正是这条回归）',
          check_anchor(_bad)[0] is False)
    check('锚点恒等: bodyColor 缺失 → 必须 FAIL（旧存档不得静默通过）',
          check_anchor(_empty)[0] is False)
    check('锚点恒等: --text-3 缺失 → 必须 FAIL',
          check_anchor(_notokens)[0] is False)

    # ⭐ 读取位置修正的专项证明（captain 2026-09-15）：
    #   声明落在 body 上时，documentElement 的 --body-color 可能仍不是我们的值。
    #   旧实现只看 documentElement ⇒ 会误判；新实现看 body.color ⇒ 正确通过。
    _bodyside = {'bodyColor': 'rgb(94, 103, 121)',
                 'tokens': {'--body-color': '#6b7385', '--text-3': '#5E6779'}}
    check('锚点读取位置: documentElement --body-color 是旧值、但 body.color 正确 → PASS（旧实现会误判为 FAIL）',
          check_anchor(_bodyside)[0] is True)
    _reverse = {'bodyColor': 'rgb(107, 115, 133)',
                'tokens': {'--body-color': '#5E6779', '--text-3': '#5E6779'}}
    check('锚点读取位置: documentElement 正确但 body.color 错误 → 必须 FAIL（不许被声明落点骗过）',
          check_anchor(_reverse)[0] is False)

    # 校名/链接色锚点（eng-web 建议）：判据必须是「== --brand-action」，不得用「!= #0F34C3」
    _bt = {'--brand-action': '#0C6DD7'}
    _b_ok = {'brand': {'found': True, 'color': 'rgb(12, 109, 215)'}, 'tokens': _bt}
    _b_orig = {'brand': {'found': True, 'color': 'rgb(15, 52, 195)'}, 'tokens': _bt}
    _b_derived = {'brand': {'found': True, 'color': 'rgb(9, 85, 167)'}, 'tokens': _bt}
    check('校名锚点: == --brand-action → PASS',
          check_brand_anchor(_b_ok)[0] is True, check_brand_anchor(_b_ok)[1])
    check('校名锚点: 原派生蓝 #0F34C3 → 必须 FAIL',
          check_brand_anchor(_b_orig)[0] is False, check_brand_anchor(_b_orig)[1])
    check('校名锚点: **auto-contrast 的另一个派生蓝 #0955A7 → 必须 FAIL**（这条正是「!= #0F34C3」写法会放过的）',
          check_brand_anchor(_b_derived)[0] is False, check_brand_anchor(_b_derived)[1])
    check('校名锚点: 无 brand 字段的旧存档 → 必须 FAIL/ENV，不得静默通过',
          check_brand_anchor({'tokens': _bt})[0] is False)

    _hit = [{'key': 'my_home', 'contrast': [['rgb(107, 115, 133)', 'rgb(244, 247, 250)', 3]]}]
    _b, _h = contrast_violations(_hit)
    check('回归对: #6b7385 / #F4F7FA 出现必被命中且判不达标',
          len(_h) == 1 and len(_b) == 1, 'hits=%d bad=%d' % (len(_h), len(_b)))
    _clean = [{'key': 'my_home', 'contrast': [['rgb(94, 103, 121)', 'rgb(255, 255, 255)', 5]]}]
    _b2, _h2 = contrast_violations(_clean)
    check('回归对: 干净样本不误报（证明它不是「什么都报」）',
          len(_h2) == 0 and len(_b2) == 0, 'hits=%d bad=%d' % (len(_h2), len(_b2)))

    # ---- ④ 禁用色（v4-t8）：两个方向都要钉死 ----
    # 正向：紫色（含半透明变体）出现时必须被抓到，且要点名到页/属性。
    _purple = [{'key': 'contacts', 'bg': [['rgb(113, 75, 103)', 1]],
                'text': [], 'border': [], 'anchor': []},
               {'key': 'contacts', 'bg': [['rgba(113, 75, 103, 0.35)', 2]],
                'text': [], 'border': [], 'anchor': []}]
    _ph = forbidden_hits(_purple)
    check('禁用色: #714B67 实色与 .35 半透明变体都必须被抓到（rgba 归一）',
          len(_ph) == 2 and _ph[0][0] == 'contacts' and _ph[0][1] == 'bg',
          'hits=%d' % len(_ph))
    # 反向：干净样本不得误报 —— 否则它是一条「永远红」的判据，等于没有。
    _cleanpage = [{'key': 'contacts', 'bg': [['rgb(12, 109, 215)', 9]],
                   'text': [['rgb(255, 255, 255)', 9]], 'border': [], 'anchor': []}]
    check('禁用色: 品牌蓝/白字样本 0 命中（证明它不是「什么都报」）',
          forbidden_hits(_cleanpage) == [], str(forbidden_hits(_cleanpage)))

    # 门禁必须会红（否则「门禁」是摆设）
    import contextlib
    import io
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_aggregate(argparse.Namespace(
                raw=os.path.join(HERE, '..', '..', 'docs', 'audit', 'ui-color-raw-2026-09-15.json'),
                set='legacy4', expect=999, list=False))
    except SystemExit as e:
        rc = e.code
    check('门禁会红: legacy4 用错误期望值 999 必须 FAIL(exit 1)', rc == 1, 'exit=%s' % rc)

    # 归档生产基线：§7.3 冻结读数
    archived = os.path.join(HERE, '..', '..', 'docs', 'audit', 'ui-color-raw-2026-09-15.json')
    if not os.path.exists(archived):
        check('归档生产基线存在', False, archived)
    else:
        with open(archived, encoding='utf-8') as fh:
            doc = json.load(fh)
        ents = doc['entries'] if isinstance(doc, dict) else doc
        pages = load_pages()
        for set_name, want in FROZEN.items():
            sel, err = select([dict(e) for e in ents], pages, set_name)
            if err:
                check('归档生产基线 %s 可筛' % set_name, False, err)
                continue
            n = len(distinct(sel))
            check('归档生产基线 %s = %d（§7.3 冻结）' % (set_name, want), n == want, '实算 %d' % n)

    ok = sum(1 for _n, c, _d in cases if c)
    for n, c, d in cases:
        print('%s  %s%s' % ('PASS' if c else 'FAIL', n, ('   [%s]' % d) if (d and not c) else ''))
    print()
    print('selftest: %d/%d 通过（断言条数常量 %d）' % (ok, len(cases), SELFTEST_CASES))
    if len(cases) != SELFTEST_CASES:
        print('FAIL  selftest 断言条数漂移：实际 %d，常量 %d' % (len(cases), SELFTEST_CASES))
        return 1
    return 0 if ok == len(cases) else 1


# ------------------------------------------------- 令牌源对比（captain 判据 ④）
# §7.4 已把令牌集定为 scripts/color_tokens.json（由 t3 的 color_tokens.py 机械提取）。
# 这里用它做「状态色与令牌值是否一致」的机械判定 —— 注意这是**绝对判据**，
# 只依赖 after 快照 + 令牌源，**不需要 before 里有同名字段**。
TOKEN_SOURCE = os.path.join(HERE, '..', '..', 'scripts', 'color_tokens.json')

# 判据 ④ 的判定面：只有这四个状态色算「判据」，其余漂移作 INFO。
STATUS_TOKENS = ('--success', '--danger', '--warning', '--info')


def load_token_source():
    """返回 (tokens_map, err)。tokens_map: {name: {'value': ...}}"""
    if not os.path.exists(TOKEN_SOURCE):
        return None, 'ENV: 找不到令牌源 %s（§7.4 要求它是唯一输入）' % TOKEN_SOURCE
    try:
        with open(TOKEN_SOURCE, encoding='utf-8') as fh:
            d = json.load(fh)
    except Exception as e:
        return None, 'ENV: 令牌源解析失败 %s' % e
    t = d.get('tokens')
    if not isinstance(t, dict) or not t:
        return None, 'ENV: 令牌源里没有 tokens 映射'
    return t, None


def token_drift(entries, src):
    """逐页比对抓到的令牌计算值 vs 令牌源。返回 (checked, drift[(key,name,got,want)])。"""
    checked = 0
    drift = []
    for e in entries:
        toks = e.get('tokens') or {}
        for name, spec in src.items():
            want = spec.get('value') if isinstance(spec, dict) else None
            got = (toks.get(name) or '').strip()
            if not want or not got:
                continue
            checked += 1
            if _canon(got) != _canon(want):
                drift.append((e.get('_key', '?'), name, got, want))
    return checked, drift


# ------------------------------------------------------------------ status
def cmd_status(args):
    """生成**机器可读**的状态摘要，供 captain / t9 / 评审直接读取。

    存在理由：本轮已因「手抄数字」出错 6 次 —— 基线戳记 4 次（87 / 86 / 80 / 15:44）、
    selftest 条数 2 次（32 / 38）。根因不是谁不认真，而是**从会变的产物上手工誊写**。
    所以把「当前值」变成一条命令的输出，引用者读文件而不是读记忆。
    """
    out = {
        'schema': 'color-gauge-status/v1',
        'generated_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        'how_to_read': '引用任何数字前读本文件，不要凭记忆誊写（本轮已因此出错 6 次）。',
    }
    p = subprocess.run([sys.executable, os.path.abspath(__file__), 'selftest'],
                       capture_output=True, text=True)
    summary = ''
    for line in p.stdout.strip().splitlines():
        if line.startswith('selftest:'):
            summary = line.strip()
    out['selftest'] = {'exit': p.returncode, 'declared_cases': SELFTEST_CASES, 'summary': summary}

    bp = os.path.join(HERE, 'baseline-local.json')
    if os.path.exists(bp):
        with open(bp, encoding='utf-8') as fh:
            d = json.load(fh)
        pages = load_pages()
        n = None
        try:
            sel, err = select([dict(e) for e in d['entries']], pages, 'frozen6')
            n = None if err else len(distinct(sel))
        except Exception:
            pass
        out['baseline'] = {
            'file': 'tests/color/baseline-local.json',
            'status': d.get('status'), 'rev': d.get('git_revision'),
            'dirty': d.get('git_dirty_files'), 'captured_at': d.get('captured_at'),
            'frozen': d.get('frozen'), 'label': d.get('label'),
            'distinct_frozen6': n,
            'superseded': 'tests/color/baseline-local-before.json（勿用于 t9）',
        }
    pp = os.path.join(HERE, 'probes-t5.json')
    if os.path.exists(pp):
        with open(pp, encoding='utf-8') as fh:
            d = json.load(fh)
        b = d.get('probe_b_artifact') or {}
        out['probes'] = {
            'file': 'tests/color/probes-t5.json',
            'note': '探针 ≠ 基线：不参与 before/after 色数对照',
            'combined_sha256': b.get('combined_sha256'),
            'tracked_counts_by_value': b.get('tracked_counts_by_value'),
        }
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print('状态摘要 -> %s' % args.out)
    print('  selftest:', out['selftest']['summary'])
    if out.get('baseline'):
        bl = out['baseline']
        print('  基线: %s | rev %s + %s dirty | %s | %s 色' % (
            bl['status'], (bl['rev'] or '')[:12], bl['dirty'], bl['captured_at'], bl['distinct_frozen6']))
    if out.get('probes'):
        print('  探针: combined sha256=%s | #71639e=%s' % (
            (out['probes']['combined_sha256'] or '')[:16],
            (out['probes']['tracked_counts_by_value'] or {}).get('#71639e')))
    return 0


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description='全站配色取色量具（t12 冻结版）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('selftest', help='只证量具（离线）')

    ag = sub.add_parser('aggregate', help='对归档取色 JSON 复算 §7.3 口径')
    ag.add_argument('raw')
    ag.add_argument('--set', choices=['frozen6', 'legacy4', 'all'], default='frozen6')
    ag.add_argument('--expect', type=int, default=None)
    ag.add_argument('--list', action='store_true')

    cp = sub.add_parser('capture', help='用 Tabbit 真机取色并归档')
    cp.add_argument('--base-url', default='http://localhost:8069')
    cp.add_argument('--out', required=True)
    cp.add_argument('--set', choices=['frozen6', 'legacy4'], default='frozen6')
    cp.add_argument('--db', default='edu19')
    cp.add_argument('--login-user', default='faculty@local')
    cp.add_argument('--login-pass', default='demo123')

    asr = sub.add_parser('assert', help='回归锚点门禁：① --body-color==--text-3 ② 对比度不达标')
    asr.add_argument('raw')
    asr.add_argument('--set', choices=['frozen6', 'legacy4', 'all'], default='frozen6')
    asr.add_argument('--expect-violations', type=int, default=None)
    asr.add_argument('--max-show', type=int, default=15)

    stt = sub.add_parser('status', help='生成机器可读状态摘要（引用数字前读它，别凭记忆）')
    stt.add_argument('--out', default=os.path.join(HERE, 'status.json'))

    tk = sub.add_parser('tokens', help='逐页打印关键令牌计算值（查「换了令牌但页面没变」）')
    tk.add_argument('raw')
    tk.add_argument('--set', choices=['frozen6', 'legacy4', 'all'], default='frozen6')

    args = ap.parse_args()
    if args.cmd == 'selftest':
        return selftest()
    if args.cmd == 'aggregate':
        return cmd_aggregate(args)
    if args.cmd == 'capture':
        return cmd_capture(args)
    if args.cmd == 'assert':
        return cmd_assert(args)
    if args.cmd == 'tokens':
        return cmd_tokens(args)
    if args.cmd == 'status':
        return cmd_status(args)
    return 2


if __name__ == '__main__':
    sys.exit(main())
