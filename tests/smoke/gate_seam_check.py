#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨工具「接缝测试」（t48）：两个门禁的提取口径合起来是否守住可见面。

=== 为什么需要它 ===
两个门禁各有 `--selftest`，但**接缝**没人测：各自全绿，接缝断了也不知道。
2026-09-12 的实例：`title="转到您的Odoo应用程序"`（CJK + 品牌 token）——
check_odoo_trace 当时只扫文本节点、check_english 遇 CJK 即跳过 →
**两个盲区落在同一个样本上（重叠盲区）**。修完后该样本被两边同时抓到（**重叠覆盖**）。
本脚本把这条接缝固化成断言：**样本 × 期望「至少一个门禁报红」**，不绑定具体工具。

=== 本脚本的覆盖范围（二阶边界，务必读完再用） ===
本脚本把两个**提取器**直接喂样本，验证的是 **提取 + 分类口径**；
**路由/角色覆盖面不在它射程内** —— 某条路由从门禁清单里漏掉，本脚本仍会全绿
（路由覆盖由 `check_odoo_trace --list-routes` 与矩阵脚本各自负责）。
所以它证明的是"**同一段 HTML 里的可见痕迹不会被两边同时放过**"，不是"整站已被完全覆盖"。

=== 样本表 ===
  (a) 纯英文属性值     title="Notifications"            ≥1 报   ｜ 注：**职责差异**，见下
  (b) 纯英文文本节点   <div>Odoo</div>                   ≥1 报
  (c) CJK+品牌 属性值  title="转到您的Odoo应用程序"        ≥1 报   ｜ 本次事故样本
  (d) CJK+品牌 文本节点                                    ≥1 报
  (e) 纯中文对照       <div>转到您的应用</div>             0 报    ｜ **对照组：判据强度的一半**
  (f) 未登记属性里的品牌 token  data-tooltip="Odoo"        0 报    ｜ **known-gap（预期沉默，非失败）**
职责差异说明：(a) 只有 check_english 报，是因为 check_odoo_trace 的职责是**品牌痕迹**而非通用英文。
**不要为了让它报而去扩品牌门禁的属性范围** —— 那会把品牌门禁变成英文门禁。
(f) 的三个用途：① 把残余风险变成可执行断言；② 若将来有人**扩大**某门禁属性范围，(f) 会翻成"报" →
提示**覆盖声明已过期**（此时应更新 docstring / UX_V3_GATE.md §2.1 并把 (f) 升格为正向样本）；
③ 让覆盖声明从"会腐烂的注释"变成**被测试锁定的契约**。

=== 用法 ===
    python3 tests/smoke/gate_seam_check.py                     # 全绿应 exit 0
    python3 tests/smoke/gate_seam_check.py --inject-fault historical-blindspot
        ↑ 复现 2026-09-12 事故的**双侧隐藏**（check_english 又遇 CJK 就跳过 + check_odoo_trace 又不扫属性）
          → **接缝测试必须变红**（双向证据）。
    python3 tests/smoke/gate_seam_check.py --inject-fault english-attr   # 单侧降级：(a) 只有它报 → 会红
    python3 tests/smoke/gate_seam_check.py --inject-fault trace-attr     # 单侧降级：另一门禁兜住 → **不一定红**
说明：单侧降级未必变红，**正是重叠覆盖的价值**（备线还在）；只有"两侧同时退化"才重现当日的重叠盲区。
      故本脚本把 **historical-blindspot 必须红** 作为断言，单侧降级只作诊断信息。
退出码：0=期望全部满足（或注入故障后如期变红）；1=期望被破坏 / 断言不足以发现断档；2=环境错误。
"""
import argparse
import re
import sys

sys.path.insert(0, 'scripts')
try:
    import check_english as ce
    import check_odoo_trace as ct
except Exception as e:                                    # pragma: no cover
    print('环境错误：无法导入门禁模块（%s）' % str(e)[:80])
    sys.exit(2)

NEVER = re.compile(r'(?!x)x')      # 永不匹配的正则：用于"故意改坏接缝"

SAMPLES = [
    dict(key='a', html='<input type="text" title="Notifications"/>',
         expect='at-least-one', label='纯英文属性值（职责差异：品牌门禁不管通用英文）'),
    dict(key='b', html='<div>Odoo</div>', expect='at-least-one', label='纯英文文本节点'),
    dict(key='c', html='<a href="#" title="转到您的Odoo应用程序">x</a>',
         expect='at-least-one', label='CJK+品牌 token 属性值（本次事故样本）'),
    dict(key='d', html='<div>转到您的Odoo应用程序</div>', expect='at-least-one',
         label='CJK+品牌 token 文本节点'),
    dict(key='e', html='<div>转到您的应用</div>', expect='none',
         label='纯中文对照组（两边都不报；防"什么都报"伪造绿）'),
    dict(key='f', html='<div data-tooltip="Odoo">x</div>', expect='none',
         label='未登记属性里的品牌 token（known-gap：预期沉默，非失败）'),
]


def evaluate(html):
    """返回 (english 命中列表, trace 命中列表)。"""
    eng = ['%s:%s' % (f['bucket'], f['value']) for f in ce.scan_body(html)]
    try:
        raw = ct.scan(html, check_web_links=False)
        hits = raw[0] if isinstance(raw, tuple) else raw
        tr = ['%s' % (h[0] if isinstance(h, tuple) else h) for h in (hits or [])]
    except Exception as e:
        tr = ['ERR:%s' % str(e)[:40]]
    return eng, tr


def run(inject=None):
    if inject == 'english-attr':
        ce.ATTR_RE = NEVER
        print('[fault] 已让 check_english 跳过属性提取（ATTR_RE 置为永不匹配）')
    elif inject == 'trace-attr':
        ct.ATTR_RE = NEVER
        print('[fault] 已让 check_odoo_trace 跳过属性提取（ATTR_RE 置为永不匹配）')
    elif inject == 'historical-blindspot':
        # 复现 2026-09-12 的重叠盲区：两侧同时退化
        ct.ATTR_RE = NEVER          # check_odoo_trace 回到"只扫文本节点"
        ce.BRAND_RE = NEVER         # check_english 回到"遇 CJK 即跳过"（品牌桶失效）
        print('[fault] 已复现历史重叠盲区：trace 不扫属性 + english 品牌桶失效')

    print('%-4s %-34s %-30s %-30s %s' % ('#', '样本', 'check_english', 'check_odoo_trace', '判定'))
    failures = []
    for s in SAMPLES:
        eng, tr = evaluate(s['html'])
        n = len(eng) + len(tr)
        ok = (n >= 1) if s['expect'] == 'at-least-one' else (n == 0)
        if not ok:
            failures.append((s, eng, tr))
        print('%-4s %-34s %-30s %-30s %s' % (
            '(%s)' % s['key'], s['label'][:32],
            ('; '.join(eng))[:28] or '—', ('; '.join(tr))[:28] or '—',
            'PASS' if ok else 'FAIL'))
    return failures


def main():
    ap = argparse.ArgumentParser(description='跨工具接缝测试（样本 × 至少一个门禁报红）')
    ap.add_argument('--inject-fault',
                    choices=['english-attr', 'trace-attr', 'historical-blindspot'],
                    help='故意改坏某门禁的属性提取（用于验证本测试会红）')
    args = ap.parse_args()

    print('===== 接缝矩阵（离线；直接喂两个提取器，不含路由覆盖）=====')
    failures = run(args.inject_fault)

    print('')
    print('============ 汇总 ============')
    if args.inject_fault:
        must_red = args.inject_fault in ('historical-blindspot', 'english-attr')
        if failures:
            print('故障注入 %s：接缝测试**变红**（%d 个样本失去全部报告者）'
                  % (args.inject_fault, len(failures)))
            for s, eng, tr in failures:
                print('  (%s) %s → english=%s trace=%s' % (s['key'], s['label'][:26],
                                                           eng or '—', tr or '—'))
            if must_red:
                print('→ 双向证据成立：该故障模式下断言确实会红。')
            else:
                print('→ 注：单侧降级下仍有样本变红属附加信息；本模式不要求必红。')
            return 0
        if must_red:
            print('故障注入 %s：接缝测试**没有变红** —— 断言不足以发现覆盖断档！' % args.inject_fault)
            return 1
        print('故障注入 %s：单侧降级未破网（另一门禁兜住）→ **这正是重叠覆盖的价值**'
              % args.inject_fault)
        return 0
    if failures:
        print('接缝被破坏 / 覆盖声明过期：%d 个样本期望未满足' % len(failures))
        for s, eng, tr in failures:
            want = '至少一个门禁报' if s['expect'] == 'at-least-one' else '两个门禁都不报'
            print('  (%s) %s：期望「%s」，实际 english=%s trace=%s'
                  % (s['key'], s['label'][:30], want, eng or '—', tr or '—'))
        print('提示：若是 (f) 翻转，多半是某门禁扩大了属性覆盖 → 请同步更新覆盖声明'
              '（check_english docstring / UX_V3_GATE.md §2.1）并把 (f) 升格为正向样本。')
        return 1
    print('六个样本期望全部满足：接缝未被两边同时放过；对照组与 known-gap 均按预期沉默')
    return 0


if __name__ == '__main__':
    sys.exit(main())
