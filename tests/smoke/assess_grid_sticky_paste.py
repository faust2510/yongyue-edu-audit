#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「像 Excel 一样好用」验收：E6 冻结表头/首列 + E7 Excel 整块粘贴（2026-09-29）。

被测对象（custom_addons/edu_assess，三条证据缺一不可）：
  E6 冻结
    · static/src/css/assess_grid.css —— 矩阵自己当滚动容器（.yy-assess-scroll）
      + 整段 <thead> 冻结（含一级/二级分组行，不是只冻最后一行）+ 首列冻结；
    · views/assess_portal.xml 里那层 <div class="yy-assess-scroll">。
  E7 粘贴
    · static/src/js/assess_grid.js 的 paste 监听：TSV → 按行列铺进**既有的**
      <input name="v_<roster>_<item>">，提交路径 / 服务端校验一个字不改。

为什么必须真浏览器（不是看代码说"做了"）：
  · 冻结的判据是**几何位移**：滚 200px 后表头相对滚动容器顶边的位移必须 ≈0，
    而同一时刻 tbody 首行必须跟着走 ≈-200（否则"整张表没滚"也能假装通过）；
  · 粘贴的判据是**逐格相等**：真剪贴板（navigator.clipboard）+ 真 Ctrl/Cmd+V
    事件 → DOM 逐格 → 提交 → 重新加载后服务端回填的逐格 → SQL 逐格。

三段证据（照 docs/dev-workflow.md）：
  正向 P / F / V 段；控制组 C 段（单行 / 单列 / 空剪贴板 / 非表格中文 / 越界 /
  键盘移动未被弄坏 / 非矩阵输入框的粘贴不被劫持）；反向注入窗口用 --only f / --only v。
  反向注入的做法（跑完必须还原）：
    · 把 assess_grid.css 里的 position: sticky 注掉 ⇒ F 段必须变红；
    · 把 assess_grid.js 的 parseTsv 注坏（例如只 split('\n') 不 split('\t')）⇒ V 段必须变红；
    · 把 assess_grid.js 里 init() 的 fitHeight()/watchLayout() 两行注掉 ⇒
      **G5/G6/G7 必须变红**，且 G5 的读数必须是「底边 984.05 > 视口 900」
      （2026-09-29 实测留档：tests/smoke/assess_grid_sticky_paste_inject_g.json）；
    · B6 是**在浏览器里当场注入**的反向对照（add_style_tag 关掉 thead sticky）：
      表头立刻变成跟着滚 ⇒ 证明"冻住"来自那条规则；同时断言页面不坏（降级形态）。

夹具：《卫生检测表》形态 —— 5 区 × 2 分类 × 2 项 = **20 个叶子项**（三层表头），
      27 行名单（对齐素材 xlsx 的 A1:I27 行列规模）。跑完默认清场，--keep 保留。

判据纪律（照抄 tests/smoke/assess_portal_gaps.py）：
  · 只读 SQL + HTTP + 真浏览器；不升级、不重启、不动别人的模型文件；
  · 每条断言都留原始读数（offset / rect / 逐格值），不写"看着对"；
  · 失败不静默：每条都打印实际值。

2026-09-29 第二轮补齐（上一轮自己列出的 4 个缺口，见本文件 B/S/D 段与 G5–G8）：
  · 高度预算不再"拍脑袋留 24rem"：assess_grid.js 的 fitHeight() 按容器**实测顶边**算，
    并新增**保存后（提示条可见）底边 <= 视口高**的硬断言（G5）；纯 CSS 保留为无脚本兜底（H4）。
  · 跨引擎：同一组冻结断言在 **Chromium 与 WebKit** 上各出一套读数（B 段）。
  · 小屏形态：390×844 / 768×1024 下矩阵的实际形态与断言（S 段；结构性测不到的打印 N/A 理由）。
  · 双轨 (项,轨) 列键：只查不做（D 段）—— 今天没有任何模板会产生第二轨，登记触发条件。

用法：
    python3 tests/smoke/assess_grid_sticky_paste.py              # 全量（建夹具 → 断言 → 清场）
    python3 tests/smoke/assess_grid_sticky_paste.py --keep       # 保留夹具（排查用）
    python3 tests/smoke/assess_grid_sticky_paste.py --only f     # 只跑 F 段（反向注入窗口）
    python3 tests/smoke/assess_grid_sticky_paste.py --only v     # 只跑 V 段（反向注入窗口）
    python3 tests/smoke/assess_grid_sticky_paste.py --only a     # 只跑无障碍 A 段
    python3 tests/smoke/assess_grid_sticky_paste.py --only g     # 只跑高度预算 G 段（反向注入窗口）
    python3 tests/smoke/assess_grid_sticky_paste.py --only b     # 只跑跨引擎 B 段
    python3 tests/smoke/assess_grid_sticky_paste.py --only s     # 只跑小屏 S 段
    python3 tests/smoke/assess_grid_sticky_paste.py --only d     # 只跑双轨核查 D 段（不建浏览器）
退出码：0=全绿；1=有断言失败；2=ENV（站点不可达 / 夹具建不起来 / 库读不到 / 无 playwright）。
结果落盘：tests/smoke/assess_grid_sticky_paste_results.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                  # 仓根（D 段要读被测源码的**原文**）
sys.path.insert(0, str(HERE))
import assess_portal_gaps as G          # noqa: E402  复用登录 / RPC / psql / 建模板

import requests                          # noqa: E402

BASE = G.BASE
DB = G.DB
RESULTS = HERE / 'assess_grid_sticky_paste_results.json'

#: 夹具前缀（清场只按它们，绝不动既有数据）
MARK = '【矩阵冻结粘贴】'
PERIOD = 'FZP-'
ROWS = 27                                # 数据行数（对齐 xlsx A1:I27）
AREA_COUNT = 5                           # 5 个区（三层表头的第一层各不相同）

#: 三层树：区 → 分类 → 项；20 个叶子项 ⇒ 1 列行标签 + 20 列 = 21 列，
#: 宽出卡片 ⇒ 横向有真实行程（900 视口下也够）
TREE = [
    ('%s区%d' % (MARK, a + 1),
     [('清洁', [('窗户有灰尘/污渍', 20.0), ('灶台油渍', 20.0)]),
      ('归置', [('垃圾未倒', 20.0), ('杂物堆积', 20.0)])])
    for a in range(AREA_COUNT)
]

PASTE_KEY = 'Meta+V' if sys.platform == 'darwin' else 'Control+V'
AXE_FILE = os.path.join(os.environ.get('TMPDIR') or '/tmp',
                        'edu_axe', 'axe-4.10.2.min.js')

OK, FAIL = 'PASS', 'FAIL'
items = []
nas = []                                  # N/A 清单（明确不计入通过）
readings = {}


def check(no, name, cond, detail=''):
    items.append({'no': no, 'name': name, 'pass': bool(cond),
                  'detail': str(detail)[:1500]})
    print('  %-4s #%-6s %-56s %s' % (OK if cond else FAIL, no, name,
                                     str(detail)[:200]))
    return bool(cond)


def note(msg):
    print('  ---- %s' % msg)


def na(no, name, reason):
    """结构性测不到 / 引擎不可用 ⇒ 打 N/A 并写明理由，**不计通过也不计失败**。

    本仓既有惯例（见 docs/dev-workflow.md 与 UUID 脚本的 SKIP 口径）：
    测不到的事不许静默当绿 —— 打印理由，并单独计数。
    """
    nas.append({'no': no, 'name': name, 'reason': str(reason)[:500]})
    print('  %-4s #%-6s %-56s %s' % ('N/A', no, name, str(reason)[:200]))
    return True


def die(msg):
    print('CANNOT: %s' % msg)
    json.dump({'error': msg, 'items': items, 'when': time.strftime('%Y-%m-%d %H:%M:%S')},
              open(RESULTS, 'w'), ensure_ascii=False, indent=1)
    sys.exit(2)


# ----------------------------------------------------------------------
# 夹具
# ----------------------------------------------------------------------

def build_fixture(adm, target='student', scorer='teacher', tag=''):
    """建三层模板 + 任务 + 27 行名单。返回 (tpl_id, task_id, roster_ids, item_ids)。

    target='student' 用于整班打分页（/assess/grade）；target='faculty' + scorer='student'
    用于学生填写页（/assess/fill）—— 两页共用同一段矩阵模板，但页面版式不同
    （矩阵顶边 311px vs 379px），冻结与高度预算要分别实测。
    """
    tpl = G.rpc_create(adm, 'edu.assess.template', {
        'name': MARK + '卫生检测表（三层）' + tag, 'kind': 'other',
        'target_kind': target, 'total': 100.0, 'pass_line': 60.0,
        'excellent_line': 90.0, 'weight_mode': 'multiplier',
        'state': 'active', 'score_visible': True})
    leaves = []
    for area, subs in TREE:
        gid = G.rpc_create(adm, 'edu.assess.item', {
            'template_id': tpl, 'name': area, 'item_kind': 'group',
            'sequence': 10})
        for sname, checks in subs:
            sid = G.rpc_create(adm, 'edu.assess.item', {
                'template_id': tpl, 'parent_id': gid, 'name': sname,
                'item_kind': 'group', 'sequence': 10})
            for cname, mx in checks:
                iid = G.rpc_create(adm, 'edu.assess.item', {
                    'template_id': tpl, 'parent_id': sid, 'name': cname,
                    'item_kind': 'leaf', 'score_mode': 'add',
                    'max_score': mx, 'weight': 1.0, 'sequence': 10})
                leaves.append(iid)
    task = G.rpc_create(adm, 'edu.assess.task', {
        'template_id': tpl, 'period': PERIOD + '冻结粘贴' + tag,
        'state': 'open', 'scorer_kind': scorer, 'anonymous': False})
    # 名单 27 行：被评学生复用同一名（subject_ref 唯一即可）——
    # 本探针量的是**几何位移与逐格值**，人名是否重复不影响判据。
    stu, _e = G.search(adm, 'op.student', [], ('id',), 1)
    sid = stu[0]['id'] if stu else False
    rosters = []
    for i in range(ROWS):
        rosters.append(G.rpc_create(adm, 'edu.assess.roster', {
            'task_id': task, 'student_id': sid, 'subject_ref': 's:%d' % (90000 + i)}))
    return tpl, task, rosters, leaves


def cleanup(adm):
    """按夹具前缀清场（幂等；只删自己建的东西）。"""
    tpls, _e = G.search(adm, 'edu.assess.template', [('name', 'like', MARK + '%')])
    tpl_ids = [t['id'] for t in tpls]
    tasks, _e = G.search(adm, 'edu.assess.task', [('period', 'like', PERIOD + '%')])
    task_ids = [t['id'] for t in tasks]
    item_ids = [i['id'] for i in G.search(
        adm, 'edu.assess.item', [('template_id.name', 'like', MARK + '%')])[0]]
    if task_ids:
        sc = [s['id'] for s in G.search(
            adm, 'edu.assess.score', [('task_id', 'in', task_ids)])[0]]
        G.unlink(adm, 'edu.assess.score', sc)
        ro = [r['id'] for r in G.search(
            adm, 'edu.assess.roster', [('task_id', 'in', task_ids)])[0]]
        G.unlink(adm, 'edu.assess.roster', ro)
    G.unlink(adm, 'edu.assess.task', task_ids)
    G.unlink(adm, 'edu.assess.item', item_ids)
    G.unlink(adm, 'edu.assess.template', tpl_ids)
    print('    ... 清场：模板 %d / 任务 %d / 评分项 %d'
          % (len(tpl_ids), len(task_ids), len(item_ids)))


# ----------------------------------------------------------------------
# 浏览器
# ----------------------------------------------------------------------

def cookies_of(sess):
    return [{'name': c.name, 'value': c.value, 'domain': 'localhost',
             'path': c.path or '/'} for c in sess.cookies]


def open_browser():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:                                  # pragma: no cover
        die('playwright 不可用：%s' % exc)
    return sync_playwright


#: 一次把「容器 + 表头 + 首列 + tbody 首行」的几何全量取回（相对滚动容器左上角，
#: 吸附判据看的就是这些差值；坐标在**同一次** evaluate 里取，不会跨帧错位）。
JS_STATE = r"""
() => {
  const box = document.querySelector('.yy-assess-scroll');
  if (!box) { return {error: 'no .yy-assess-scroll'}; }
  const table = box.querySelector('.yy-assess-matrix');
  const thead = table.querySelector('thead');
  const headRows = Array.prototype.slice.call(thead.querySelectorAll('tr'));
  const bodyRows = Array.prototype.slice.call(table.querySelectorAll('tbody tr'));
  const bx = box.getBoundingClientRect();
  const rel = (el) => { const r = el.getBoundingClientRect();
                        return {top: +(r.top - bx.top).toFixed(2),
                                left: +(r.left - bx.left).toFixed(2)}; };
  const lead = thead.querySelector('th');
  const row0 = bodyRows[0];
  return {
    viewport: {w: window.innerWidth, h: window.innerHeight},
    boxHeight: +bx.height.toFixed(2), boxWidth: +bx.width.toFixed(2),
    maxScrollTop: box.scrollHeight - box.clientHeight,
    maxScrollLeft: box.scrollWidth - box.clientWidth,
    scrollTop: box.scrollTop, scrollLeft: box.scrollLeft,
    rows: bodyRows.length, cols: row0 ? row0.children.length : 0,
    headRowCount: headRows.length,
    headTops: headRows.map((tr) => rel(tr.querySelector('th')).top),
    headLefts: headRows.map((tr) => rel(tr.querySelector('th')).left),
    headTexts: headRows.map((tr) => (tr.querySelector('th') || {}).textContent || ''),
    bodyRow0Top: rel(row0).top,
    col0Left: rel(row0.children[0]).left,
    col2Left: rel(row0.children[2]).left,
    leadTop: rel(lead).top, leadLeft: rel(lead).left,
    theadPos: getComputedStyle(thead).position,
    leadPos: getComputedStyle(lead).position,
    td0Pos: getComputedStyle(row0.children[0]).position,
    boxOverflow: getComputedStyle(box).overflowX + '/' + getComputedStyle(box).overflowY,
    boxMaxHeight: getComputedStyle(box).maxHeight,
  };
}
"""

JS_SCROLL = r"""
([dy, dx]) => {
  const box = document.querySelector('.yy-assess-scroll');
  box.scrollTop += dy;
  box.scrollLeft += dx;
  return {scrollTop: box.scrollTop, scrollLeft: box.scrollLeft};
}
"""


#: 绝对几何（文档坐标 + 视口高）：只为「容器底边在不在首屏内」这一条边界读数。
#: 另带三条**机制读数**（哪来的高度预算、提示条在不在、滚动盒宽窄）——
#: 「底边合规」必须能追到是谁给的预算，否则样式挪一下就会变成假绿。
JS_STATE_ABS = r"""
() => {
  const box = document.querySelector('.yy-assess-scroll');
  if (!box) { return {found: false}; }
  const t = box.querySelector('.yy-assess-matrix');
  const r = box.getBoundingClientRect();
  const ok = document.querySelector('.alert-success');
  const thead = t.querySelector('thead');
  const headRows = Array.prototype.slice.call(thead.querySelectorAll('tr'));
  const bodyRows = Array.prototype.slice.call(t.querySelectorAll('tbody tr'));
  const relTop = (el) => +(el.getBoundingClientRect().top - r.top).toFixed(2);
  const relLeft = (el) => +(el.getBoundingClientRect().left - r.left).toFixed(2);
  const row0 = bodyRows[0];
  return {found: true,
          docTop: +(r.top + window.scrollY).toFixed(2),
          boxH: +r.height.toFixed(2),
          boxW: +r.width.toFixed(2),
          bottom: +r.bottom.toFixed(2),
          vh: window.innerHeight,
          vw: window.innerWidth,
          maxH: getComputedStyle(box).maxHeight,
          fitVar: box.style.getPropertyValue('--yy-assess-fit-h') || '',
          savedBanner: ok ? (ok.textContent || '').replace(/\s+/g, ' ').trim()
                          : null,
          maxScrollTop: box.scrollHeight - box.clientHeight,
          maxScrollLeft: box.scrollWidth - box.clientWidth,
          rows: bodyRows.length,
          headRowCount: headRows.length,
          // 相对容器的纵向/横向几何：B 段用**一次** evaluate 就同时拿到
          // 「绝对底边」与「表头/首行位移」，不与 JS_STATE 的读数打架。
          headTops: headRows.map((tr) => relTop(tr.querySelector('th'))),
          bodyRow0Top: row0 ? relTop(row0) : null,
          col0Left: row0 ? relLeft(row0.children[0]) : null,
          col2Left: row0 ? relLeft(row0.children[2]) : null,
          theadPos: getComputedStyle(thead).position,
          leadPos: getComputedStyle(thead.querySelector('th')).position,
          td0Pos: row0 ? getComputedStyle(row0.children[0]).position : null};
}
"""

#: 小屏段用：只读形态，不滚动（避免把 S 段的读数搅在一起）
JS_SHAPE = r"""
() => {
  const box = document.querySelector('.yy-assess-scroll');
  if (!box) { return {found: false}; }
  const table = box.querySelector('.yy-assess-matrix');
  const lead = table.querySelector('tbody tr td');
  const cell = table.querySelector('tbody tr td:nth-child(2)');
  const r = box.getBoundingClientRect();
  const lr = lead.getBoundingClientRect();
  return {found: true,
          boxW: +r.width.toFixed(2), boxH: +r.height.toFixed(2),
          top: +r.top.toFixed(2), bottom: +r.bottom.toFixed(2),
          vw: window.innerWidth, vh: window.innerHeight,
          maxScrollLeft: box.scrollWidth - box.clientWidth,
          maxScrollTop: box.scrollHeight - box.clientHeight,
          leadW: +lr.width.toFixed(2),
          cellW: cell ? +cell.getBoundingClientRect().width.toFixed(2) : null,
          rows: table.querySelectorAll('tbody tr').length,
          inputs: table.querySelectorAll('input[type="number"]').length,
          headRowCount: table.querySelectorAll('thead tr').length,
          fitVar: box.style.getPropertyValue('--yy-assess-fit-h') || '',
          maxH: getComputedStyle(box).maxHeight,
          docScrollW: document.documentElement.scrollWidth,
          bodyScrollW: document.body.scrollWidth,
          leadPos: getComputedStyle(lead).position,
          theadPos: getComputedStyle(table.querySelector('thead')).position};
}
"""


def state(page):
    return page.evaluate(JS_STATE)


def scroll(page, dy, dx):
    return page.evaluate(JS_SCROLL, [dy, dx])


#: 粘贴：真剪贴板 + 真 Ctrl/Cmd+V。锚点 = 第 row 行（0 基，tbody 行）第 col 列
#: （0 基，**数字输入框**序号，不含行标签列）。
JS_FOCUS = r"""
([r, c]) => {
  const t = document.querySelector('.yy-assess-matrix');
  const tr = t.querySelectorAll('tbody tr')[r];
  const inputs = tr.querySelectorAll('input[type="number"]');
  const input = inputs[c];
  input.focus();
  input.value = '';
  input.dispatchEvent(new Event('input', {bubbles: true}));
  return {name: input.getAttribute('name')};
}
"""


def paste_block(page, row, col, text):
    """把 text 放进真剪贴板 → 在指定格粘贴 → 返回锚点 input 的 name。"""
    anchor = page.evaluate(JS_FOCUS, [row, col])
    page.evaluate('(t) => navigator.clipboard.writeText(t)', text)
    page.keyboard.press(PASTE_KEY)
    page.wait_for_timeout(250)
    return anchor


JS_GRID = r"""
() => {
  const t = document.querySelector('.yy-assess-matrix');
  return Array.prototype.map.call(t.querySelectorAll('tbody tr'), (tr) =>
    Array.prototype.map.call(tr.querySelectorAll('input[type="number"]'), (i) =>
      ({name: i.getAttribute('name'), value: i.value,
        invalid: i.classList.contains('is-invalid')})));
}
"""

JS_STATUS = r"""
() => {
  const p = document.querySelector('.yy-assess-paste-status');
  return p ? {text: p.textContent, role: p.getAttribute('role'),
              live: p.getAttribute('aria-live')} : null;
}
"""


def grid(page):
    return page.evaluate(JS_GRID)


def grid_map(page):
    out = {}
    for row in grid(page):
        for cell in row:
            out[cell['name']] = cell
    return out


def rows_cols(page, r0, c0, nrow, ncol):
    g = grid(page)
    out = []
    for r in range(r0, r0 + nrow):
        for c in range(c0, c0 + ncol):
            out.append(g[r][c])
    return out


#: 无障碍**绝对口径**：与 scripts/check_accessibility.py 同一个 axe 标签集
#: （runOnly WCAG A/AA）。best-practice 类规则（page-has-heading-one / heading-order）
#: 不在该门禁口径内 —— 矩阵页今天在这套口径下就是 0 条，本文件按同一把尺子量。
AXE_WCAG = ('{resultTypes:["violations"], runOnly:{type:"tag", '
            'values:["wcag2a","wcag2aa","wcag21a","wcag21aa"]}}')


def axe(page, label, url=None, wcag_only=False):
    """对当前页跑 axe（读本地缓存；只看 violations）。

    wcag_only=True ⇒ 用门禁口径（只跑 WCAG A/AA 标签）；False ⇒ 全规则（含
    best-practice），用于「冻结态 vs 改动前」的相对 A/B。
    """
    if not os.path.isfile(AXE_FILE):
        return {'env': 'axe 缓存缺失：%s' % AXE_FILE}
    src = open(AXE_FILE, encoding='utf-8').read()
    page.add_script_tag(content=src)
    res = page.evaluate('async () => await axe.run(document, %s)'
                        % (AXE_WCAG if wcag_only else '{resultTypes:["violations"]}'))
    viols = []
    for v in res.get('violations') or []:
        nodes = v.get('nodes') or []
        viols.append({'id': v['id'], 'impact': v.get('impact'),
                      'nodes': len(nodes),
                      'targets': [','.join(n.get('target') or [])
                                  for n in nodes][:4]})
    rule_set = sorted(v['id'] for v in viols)
    print('    [axe] %s -> %d 条规则 / %d 个节点：%s'
          % (label, len(rule_set), sum(v['nodes'] for v in viols),
             ', '.join('%s(x%d)' % (v['id'], v['nodes']) for v in viols) or '无'))
    return {'violations': viols, 'rules': rule_set,
            'nodes': sum(v['nodes'] for v in viols)}


# ----------------------------------------------------------------------
# 段
# ----------------------------------------------------------------------

def section_p(page, task_id, res):
    """P 前置事实：三张矩阵都在自有滚动容器里，且它真的是滚动盒。"""
    print('== P 前置事实 ==')
    note('页面：/assess/grade/%d（三层模板 = 分组表头两行 + 叶子项名行）' % task_id)
    st = state(page)
    readings['P_state'] = st
    check('P1', '矩阵在自己的滚动容器 .yy-assess-scroll 里',
          'error' not in st, 'boxOverflow=%s maxHeight=%s box=%.1f×%.1f'
          % (st.get('boxOverflow'), st.get('boxMaxHeight'),
             st.get('boxWidth', 0), st.get('boxHeight', 0)))
    check('P2', '容器是真的滚动盒（横向 & 纵向都有行程）',
          st.get('maxScrollTop', 0) > 100 and st.get('maxScrollLeft', 0) > 100,
          'maxScrollTop=%s maxScrollLeft=%s（行程不足则冻结无从判定）'
          % (st.get('maxScrollTop'), st.get('maxScrollLeft')))
    check('P3', '表头是多行的（三层模板：分组行 ≥2 + 叶子项名行）',
          st.get('headRowCount', 0) >= 3,
          'thead 行数=%s｜各行首格=%s' % (st.get('headRowCount'), st.get('headTexts')))
    check('P4', '行数/列数 = 夹具口径（27 行 × 20 项）',
          st.get('rows') == ROWS and st.get('cols') == len(TREE) * 4 + 1,
          'rows=%s cols=%s' % (st.get('rows'), st.get('cols')))
    check('P5', '三处 sticky 都在（thead / 交叉格 / tbody 首列）',
          st.get('theadPos') == 'sticky' and st.get('leadPos') == 'sticky'
          and st.get('td0Pos') == 'sticky',
          'thead=%s 交叉格=%s 首列=%s'
          % (st.get('theadPos'), st.get('leadPos'), st.get('td0Pos')))
    # P6 打印路径的回归护栏：高度预算从"纯 CSS"改成"CSS 变量"之后，@media print 里
    # 那条 max-height:none / position:static 必须仍然压得住（否则打印会裁掉表格）。
    page.emulate_media(media='print')
    pr = page.evaluate("""() => {
      const b = document.querySelector('.yy-assess-scroll');
      const th = document.querySelector('.yy-assess-matrix thead');
      return {maxH: getComputedStyle(b).maxHeight,
              overflow: getComputedStyle(b).overflow,
              theadPos: getComputedStyle(th).position};
    }""")
    page.emulate_media(media='screen')
    readings['P_print'] = pr
    check('P6', '打印媒体下：高度预算关掉（max-height:none）+ 冻结关掉（position:static）',
          pr.get('maxH') == 'none' and pr.get('theadPos') == 'static',
          'print 口径：max-height=%s overflow=%s thead.position=%s'
          % (pr.get('maxH'), pr.get('overflow'), pr.get('theadPos')))


def section_f(page):
    """F 冻结（正向）：纵向滚表头不动、横向滚首列不动，且同期内容必须真的在走。"""
    print('== F 冻结（正向）==')
    scroll(page, -100000, -100000)          # 先回到原点
    a = state(page)
    scroll(page, 200, 0)
    b = state(page)
    scroll(page, 0, 300)
    c = state(page)
    readings['F_at_origin'] = a
    readings['F_after_vscroll'] = b
    readings['F_after_hscroll'] = c
    note('原点：headTops=%s bodyRow0Top=%.2f col0Left=%.2f'
         % (a['headTops'], a['bodyRow0Top'], a['col0Left']))
    note('纵滚 200 后：headTops=%s bodyRow0Top=%.2f（scrollTop=%s）'
         % (b['headTops'], b['bodyRow0Top'], b['scrollTop']))
    note('再横滚 300 后：headLefts=%s col0Left=%.2f col2Left=%.2f（scrollLeft=%s）'
         % (c['headLefts'], c['col0Left'], c['col2Left'], c['scrollLeft']))

    dv = [round(b['headTops'][i] - a['headTops'][i], 2)
          for i in range(len(a['headTops']))]
    print()
    check('F1', '纵滚 200：**全部**表头行相对容器位移 ≈ 0（含分组行）',
          all(abs(x) < 1.5 for x in dv), '各行位移=%s（判据 |Δ|<1.5）' % dv)
    check('F2', '同一时刻 tbody 首行确实在走（Δ≈-200）⇒ 不是「整表没滚」',
          abs((b['bodyRow0Top'] - a['bodyRow0Top']) + 200) < 3,
          'bodyRow0Top %.2f→%.2f（Δ=%.2f，scrollTop %s→%s）'
          % (a['bodyRow0Top'], b['bodyRow0Top'],
             b['bodyRow0Top'] - a['bodyRow0Top'], a['scrollTop'], b['scrollTop']))
    check('F3', '冻结后表头仍在容器可视区内（分组行没被冻没）',
          all(0 <= t < b['boxHeight'] for t in b['headTops']),
          'headTops=%s boxHeight=%.2f' % (b['headTops'], b['boxHeight']))
    check('F4', '横滚 300：首列相对容器位移 ≈ 0',
          abs(c['col0Left'] - b['col0Left']) < 1.5,
          'col0Left %.2f→%.2f（Δ=%.2f）'
          % (b['col0Left'], c['col0Left'], c['col0Left'] - b['col0Left']))
    check('F5', '同一时刻第 3 列确实在走（Δ≈-300）⇒ 不是「横向没滚」',
          abs((c['col2Left'] - b['col2Left']) + 300) < 3,
          'col2Left %.2f→%.2f（Δ=%.2f，scrollLeft %s→%s）'
          % (b['col2Left'], c['col2Left'], c['col2Left'] - b['col2Left'],
             b['scrollLeft'], c['scrollLeft']))
    check('F6', '交叉格（thead 首列）两轴都不动',
          abs(c['leadLeft'] - b['leadLeft']) < 1.5
          and abs(c['leadTop'] - b['leadTop']) < 1.5,
          'lead %.2f,%.2f → %.2f,%.2f'
          % (b['leadLeft'], b['leadTop'], c['leadLeft'], c['leadTop']))
    scroll(page, -100000, -100000)


def section_v(page, sess, task_id):
    """V 粘贴（正向）：3×4 真剪贴板 → DOM 逐格 → 提交 → 服务端回填逐格 → SQL 逐格。"""
    print('== V Excel 整块粘贴（正向）==')
    block = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]
    # Excel 的真实形状：\t 分列、\r\n 分行、末尾还带一个换行
    tsv = '\r\n'.join('\t'.join(str(v) for v in row) for row in block) + '\r\n'
    r0, c0 = 1, 2
    anchor = paste_block(page, r0, c0, tsv)
    cells = rows_cols(page, r0, c0, 3, 4)
    got = [[cell['value'] for cell in cells[i * 4:(i + 1) * 4]] for i in range(3)]
    status = page.evaluate(JS_STATUS)
    readings['V_block'] = block
    readings['V_cells'] = cells
    readings['V_status'] = status
    readings['V_anchor'] = anchor
    note('锚点 = %s（第 %d 行第 %d 个数字格）' % (anchor['name'], r0 + 1, c0 + 1))
    note('提示条：%s' % (status or {}))
    check('V1', '剪贴板 3×4（CRLF + 末尾空行）→ 12 格**逐格相等**',
          got == [[str(v) for v in row] for row in block],
          'DOM 实读=%s（期望=%s）' % (got, block))
    check('V2', '提示条存在且说清了写入格数',
          bool(status) and '写入 12' in (status or {}).get('text', ''),
          'role=%s aria-live=%s text=%s'
          % ((status or {}).get('role'), (status or {}).get('live'),
             (status or {}).get('text')))
    check('V3', '提示条是读屏可读的活区（role=status + aria-live=polite）',
          (status or {}).get('role') == 'status'
          and (status or {}).get('live') == 'polite', '%s' % (status or {}))

    # 只勾这 12 格的 name（其余格在控制组里另有断言，这里先只提交本块）
    names = [cell['name'] for cell in cells]
    page.click('form[action*="/assess/grade/"] button[type="submit"]')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(400)
    back = grid_map(page)
    after = [back[n]['value'] for n in names]
    want = [str(v) for row in block for v in row]
    readings['V_after_reload'] = after
    check('V4', '提交后重新加载：服务端回填的 12 格**逐格相等**（落库往返）',
          after == want, '回填=%s（期望=%s）' % (after, want))

    sql_rows = []
    for name in names:
        m = name.split('_')
        rid, iid = int(m[1]), int(m[2])
        raw = G.psql('select value::text from edu_assess_score where task_id=%d '
                     'and roster_id=%d and item_id=%d' % (task_id, rid, iid))
        sql_rows.append(raw.strip())
    readings['V_sql'] = sql_rows
    # 空串（该格没写库）不能把探针自己打崩：转不成数字就记 None，照常判红。
    sql_vals = []
    for raw in sql_rows:
        try:
            sql_vals.append(float(raw))
        except ValueError:
            sql_vals.append(None)
    check('V5', 'SQL 逐格对照：edu_assess_score 的 value 与剪贴板逐格相等',
          sql_vals == [float(v) for v in want], 'SQL=%s' % sql_rows)
    return names


def section_c(page, task_id):
    """C 控制组：单行/单列/空剪贴板/非表格中文/越界/键盘/非矩阵输入框。"""
    print('== C 控制组 ==')
    # C1 单行（1×4）：只改 4 格
    before = grid_map(page)
    paste_block(page, 3, 5, '7\t8\t9\t10')
    after = grid_map(page)
    changed = [n for n in before if before[n]['value'] != after[n]['value']]
    row3 = rows_cols(page, 3, 5, 1, 4)
    check('C1', '单行 1×4 粘贴：只改这 4 格（值逐格相等）',
          [c['value'] for c in row3] == ['7', '8', '9', '10'] and len(changed) == 4,
          '该行=%s｜全表变化格数=%d %s'
          % ([c['value'] for c in row3], len(changed), sorted(changed)[:6]))

    # C2 单列（3×1）：只改 3 格
    before = grid_map(page)
    paste_block(page, 4, 6, '11\r\n12\r\n13\r\n')
    after = grid_map(page)
    changed = [n for n in before if before[n]['value'] != after[n]['value']]
    col = [c['value'] for c in rows_cols(page, 4, 6, 3, 1)]
    check('C2', '单列 3×1 粘贴：只改这 3 格',
          col == ['11', '12', '13'] and len(changed) == 3,
          '该列=%s｜全表变化格数=%d' % (col, len(changed)))

    # C3 空剪贴板：零变化、页面不坏
    before = grid_map(page)
    paste_block(page, 5, 5, '')
    after = grid_map(page)
    changed = [n for n in before if before[n]['value'] != after[n]['value']]
    check('C3', '空剪贴板：零格变化，页面照常（提示条不新增噪音）',
          not changed, '变化格数=%d' % len(changed))

    # C4 非表格文本（一段中文，含换行）：零写入 + 逐格标红 + 页面可继续用
    text = '今天天气不错，学生表现良好。\r\n整体评价：认真、守时。\r\n请继续保持。'
    before = grid_map(page)
    paste_block(page, 6, 5, text)
    after = grid_map(page)
    changed = [n for n in before if before[n]['value'] != after[n]['value']]
    status = page.evaluate(JS_STATUS)
    invalid = [n for n in after if after[n]['invalid']]
    readings['C4_status'] = status
    check('C4', '一段中文（3 行）→ 零格写入 + 提示「非数字忽略 3」',
          not changed and (status or {}).get('text', '').find('非数字忽略 3') >= 0,
          '变化格数=%d｜提示=%s' % (len(changed), (status or {}).get('text')))
    check('C5', '被拒的格标红（既有 paint 通道），且不影响其它格',
          len(invalid) >= 3, '标红格数=%d' % len(invalid))

    # C6 越界：从最后一行最后一格粘 2×2 ⇒ 至少 1 格被舍弃、1 格写入
    st = state(page)
    r_last, c_last = st['rows'] - 1, st['cols'] - 2
    paste_block(page, r_last, c_last, '21\t22\r\n23\t24')
    status = page.evaluate(JS_STATUS)
    row_last = [c['value'] for c in rows_cols(page, r_last, c_last, 1, 1)]
    readings['C6_status'] = status
    check('C6', '越界块：落得下的写入、落不下的**明说**舍弃（不静默丢弃）',
          row_last == ['21'] and '超出矩阵范围舍弃 3' in (status or {}).get('text', ''),
          '最后一格=%s｜提示=%s' % (row_last, (status or {}).get('text')))

    # C7 键盘：粘贴后 Enter / ↓ 仍能走（E8 没被弄坏）
    page.evaluate(JS_FOCUS, [8, 5])
    name0 = page.evaluate('() => document.activeElement.getAttribute("name")')
    page.keyboard.press('Enter')
    name1 = page.evaluate('() => document.activeElement.getAttribute("name")')
    page.keyboard.press('ArrowRight')
    name2 = page.evaluate('() => document.activeElement.getAttribute("name")')
    page.keyboard.press('ArrowDown')
    name3 = page.evaluate('() => document.activeElement.getAttribute("name")')
    readings['C7_focus'] = [name0, name1, name2, name3]
    check('C7', '键盘移动（Enter/→/↓）在冻结容器里照常工作',
          name0 and name1 != name0 and name2 != name1 and name3 != name2,
          '焦点链=%s' % [name0, name1, name2, name3])

    # C8 非矩阵输入框的粘贴不被劫持（页面级行为保留）
    target = page.evaluate(r"""() => {
      const el = Array.prototype.find.call(
        document.querySelectorAll('input[type=text], input[type=search], input:not([type])'),
        (i) => !i.closest('.yy-assess-matrix') && i.offsetParent !== null);
      return el ? {name: el.getAttribute('name'), id: el.id,
                   cls: (el.className || '').slice(0, 40)} : null;
    }""")
    if not target:
        check('C8', '非矩阵输入框的粘贴不被劫持', False,
              '页面上找不到矩阵之外的可见文本输入框（ENV：无法取证）')
    else:
        sel = ('#%s' % target['id']) if target['id'] else ('input[name="%s"]' % target['name'])
        before_cells = grid_map(page)
        page.fill(sel, '')
        page.focus(sel)
        page.evaluate('(t) => navigator.clipboard.writeText(t)', '外部粘贴不受影响')
        page.keyboard.press(PASTE_KEY)
        page.wait_for_timeout(200)
        val = page.input_value(sel)
        after_cells = grid_map(page)
        changed = [n for n in before_cells
                   if before_cells[n]['value'] != after_cells[n]['value']]
        check('C8', '非矩阵输入框的粘贴不被劫持（浏览器默认行为保留）',
              val == '外部粘贴不受影响' and not changed,
              '%s 值=%r｜矩阵变化格数=%d' % (sel, val, len(changed)))
    return True


def axe_ab(page, url, tag, with_paste=True):
    """同一页面的 axe A/B：改动后（冻结生效）vs 改动前（重构：去掉容器类 + 提示条）。

    为什么在同一页面重构「改动前」：跨版本读数会混进别的改动与并行 agent 的升级
    噪音；摘掉容器类后，DOM 差异只剩一层**无类名的 div**（对 axe 不可见），
    这是同一次会话里能做到的最干净的对照。
    """
    print('== %s 无障碍（axe 4.10.2；矩阵页不在 check_accessibility 取样面内）==' % tag)
    page.goto(url, wait_until='networkidle', timeout=60000)
    page.wait_for_timeout(300)
    frozen = axe(page, '%s 改动后（冻结生效态）' % tag)
    page.evaluate(r"""() => {
      document.querySelectorAll('.yy-assess-scroll').forEach(
        (el) => el.classList.remove('yy-assess-scroll'));
      document.querySelectorAll('.yy-assess-paste-status').forEach(
        (el) => el.remove());
    }""")
    before = axe(page, '%s 改动前（重构：无容器类 / 无提示条）' % tag)
    after_paste = None
    if with_paste:
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(300)
        paste_block(page, 7, 8, '1\t2\t3')
        after_paste = axe(page, '%s 改动后（粘贴后 · 提示条有文字）' % tag)
    return {'frozen': frozen, 'before': before, 'after_paste': after_paste}


def section_a_strict(browser, pages):
    """A5–A7：三张矩阵页在**门禁口径**（WCAG A/AA 标签）下必须 0 条 —— 绝对判据。

    为什么是绝对判据而不是「相对改动前没变」：本仓无障碍基线是 **0 零余量**
    （scripts/check_accessibility.py 的 BASELINE 已收到 0），而矩阵页**不在这套
    门禁的 55 页取样面内**（它要登录、要夹具）⇒ 这里自己补测，用同一套 axe 标签口径。
    改前读数（2026-09-29 15:19，本地 edu19，Chromium 147）：三页 WCAG 口径均 0 条；
    同刻全规则口径另报 best-practice 的 page-has-heading-one ×1（结果页另有
    heading-order ×1）—— 不在门禁口径内，登记为读数、不当作缺陷面。
    """
    print('== A·无障碍**绝对口径**（WCAG A/AA 标签 = check_accessibility.py 的口径）==')
    out = {}
    for no, tag, cred, url in pages:
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
        ctx.add_cookies(cred)
        pg = ctx.new_page()
        pg.goto(url, wait_until='networkidle', timeout=60000)
        pg.wait_for_timeout(300)
        strict = axe(pg, '%s WCAG 口径' % tag, wcag_only=True)
        full = axe(pg, '%s 全规则（仅读数）' % tag, wcag_only=False)
        out[tag] = {'url': url, 'strict': strict, 'full': full}
        check(no, '%s WCAG 口径 0 条违规（零余量）' % tag,
              strict.get('nodes') == 0,
              'WCAG 口径 nodes=%s rules=%s｜同刻全规则（含 best-practice）nodes=%s rules=%s'
              % (strict.get('nodes'), strict.get('rules'),
                 full.get('nodes'), full.get('rules')))
        ctx.close()
    readings['A_strict'] = out


def section_a(page, url, task_id):
    """A 无障碍（整班打分页）：三条判据 = 不新增规则 / 不涨命中数 / 动态态不新增。"""
    res = axe_ab(page, url, 'A·整班打分页')
    frozen, before, after_paste = res['frozen'], res['before'], res['after_paste']
    readings['A_grade'] = res
    new_rules = [r for r in frozen.get('rules', []) if r not in before.get('rules', [])]
    check('A1', '冻结态相对「改动前」没有新增任何 axe 规则',
          not new_rules, '新增规则=%s｜冻结态规则=%s' % (new_rules, frozen.get('rules')))
    grown = []
    bmap = {v['id']: v['nodes'] for v in before.get('violations', [])}
    for v in frozen.get('violations', []):
        if v['nodes'] > bmap.get(v['id'], 0):
            grown.append('%s %d->%d' % (v['id'], bmap.get(v['id'], 0), v['nodes']))
    check('A2', '冻结态没有任何规则的命中节点数上升', not grown, '上升=%s' % grown)
    new_after = [r for r in after_paste.get('rules', [])
                 if r not in frozen.get('rules', [])]
    check('A3', '粘贴后的动态态（提示条有文字）没有新增规则',
          not new_after, '新增=%s｜规则=%s' % (new_after, after_paste.get('rules')))


def section_r(page, task_id):
    """R 结果页矩阵（只读、无输入：滚动容器里没有可聚焦控件，是 a11y 的高危形状）。"""
    print('== R 结果页矩阵（冻结 + 尾部 rowspan 列）==')
    st = state(page)
    readings['R_state'] = st
    check('R1', '结果页矩阵也在自有滚动容器里，且是三层表头 + 尾部列',
          'error' not in st and st.get('headRowCount', 0) >= 3,
          'thead 行数=%s｜各行首格=%s｜maxScrollTop=%s'
          % (st.get('headRowCount'), st.get('headTexts'), st.get('maxScrollTop')))
    a = st
    scroll(page, 200, 0)
    b = state(page)
    dv = [round(b['headTops'][i] - a['headTops'][i], 2) for i in range(len(a['headTops']))]
    check('R2', '结果页：纵滚 200 表头不动、tbody 首行在走',
          all(abs(x) < 1.5 for x in dv)
          and abs((b['bodyRow0Top'] - a['bodyRow0Top']) + 200) < 3,
          '表头位移=%s｜首行 %.2f->%.2f' % (dv, a['bodyRow0Top'], b['bodyRow0Top']))
    scroll(page, 0, 300)
    c = state(page)
    check('R3', '结果页：横滚 300 首列不动、第 3 列在走',
          abs(c['col0Left'] - b['col0Left']) < 1.5
          and abs((c['col2Left'] - b['col2Left']) + 300) < 3,
          '首列 %.2f->%.2f｜第3列 %.2f->%.2f'
          % (b['col0Left'], c['col0Left'], b['col2Left'], c['col2Left']))
    scroll(page, -100000, -100000)


def section_g(page, fill_task_id):
    """G 学生填写页（/assess/fill）：同一段模板的另一个页面版式，含高度预算边界读数。"""
    print('== G 学生填写页（/assess/fill）==')
    page.goto('%s/assess/fill/%d' % (BASE, fill_task_id),
              wait_until='networkidle', timeout=60000)
    page.wait_for_timeout(300)
    st = page.evaluate(JS_STATE_ABS)
    readings['G_state'] = st
    check('G1', '学生填写页也在自有滚动容器里（27 行 × 20 项）',
          st.get('found') and st.get('rows') == ROWS and st.get('headRowCount', 0) >= 3,
          'docTop=%.2f boxH=%.2f 视口=%s 行=%s'
          % (st.get('docTop', -1), st.get('boxH', -1), st.get('vh'), st.get('rows')))
    a = state(page)
    scroll(page, 200, 0)
    b = state(page)
    dv = [round(b['headTops'][i] - a['headTops'][i], 2) for i in range(len(a['headTops']))]
    check('G2', '学生填写页：纵滚 200 表头不动、首行在走',
          all(abs(x) < 1.5 for x in dv)
          and abs((b['bodyRow0Top'] - a['bodyRow0Top']) + 200) < 3,
          '表头位移=%s｜首行 %.2f->%.2f' % (dv, a['bodyRow0Top'], b['bodyRow0Top']))
    scroll(page, 0, 300)
    c = state(page)
    check('G3', '学生填写页：横滚 300 首列不动、第 3 列在走',
          abs(c['col0Left'] - b['col0Left']) < 1.5
          and abs((c['col2Left'] - b['col2Left']) + 300) < 3,
          '首列 %.2f->%.2f｜第3列 %.2f->%.2f'
          % (b['col0Left'], c['col0Left'], b['col2Left'], c['col2Left']))
    scroll(page, -100000, -100000)
    # 高度预算边界（如实读数，不当结论外推）：容器底边是否在首屏内
    fit = st.get('bottom', 9999) <= st.get('vh', 0)
    check('G4', '学生填写页（未提交态）：容器底边在 1440×900 首屏内',
          fit, '容器顶边 docTop=%.2f + 高 %.2f = 底边 %.2f（视口 %s）｜max-height=%s'
          % (st.get('docTop', -1), st.get('boxH', -1), st.get('bottom', -1),
             st.get('vh'), st.get('maxH')))

    # ---------------------------------------------------------------
    # 保存态：**这一条是整个第 1 号缺口的判据**
    # 「已保存」提示条出现在矩阵**上方** ⇒ 顶边下推；纯 CSS 的固定预留
    # max(18rem, 100vh-24rem) 不认识这件事 ⇒ 底边被推出视口。
    # 实测（改动前）：顶边 378.67→468.05、预算仍是 516 ⇒ 底边 984.05 > 900。
    # ---------------------------------------------------------------
    page.click('form[action*="/assess/fill/"] button[type="submit"]')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(500)
    saved = page.evaluate(JS_STATE_ABS)
    readings['G_saved_state'] = saved
    note('已保存态读数：docTop=%.2f boxH=%.2f 底边=%.2f 视口=%s maxH=%s '
         '--yy-assess-fit-h=%s 提示条=%r'
         % (saved.get('docTop', -1), saved.get('boxH', -1),
            saved.get('bottom', -1), saved.get('vh'), saved.get('maxH'),
            saved.get('fitVar'), saved.get('savedBanner')))
    banner = saved.get('savedBanner') or ''
    check('G5', '保存后（「已保存」提示条可见）：容器底边 <= 视口高（1440×900）',
          ('已保存' in banner) and saved.get('bottom', 1e9) <= saved.get('vh', 0),
          '提示条=%r（必须真的在页面上，否则这条是空转）｜'
          '顶边 docTop=%.2f + 高 %.2f = 底边 %.2f（视口 %s）｜max-height=%s'
          % (banner[:40], saved.get('docTop', -1), saved.get('boxH', -1),
             saved.get('bottom', -1), saved.get('vh'), saved.get('maxH')))

    # G6：预算是**按实测顶边算出来的**，不是 CSS 那条固定预留碰巧成立。
    # 判据 = 高 ≈ 视口高 − 顶边 − 24px 留白，且明显不是 CSS 兜底值 516。
    want_h = saved.get('vh', 0) - saved.get('docTop', 0) - 24
    check('G6', '预算按**实测顶边**算：高 ≈ 视口高 − 顶边 − 24px（不是 CSS 兜底的 516）',
          saved.get('fitVar', '').endswith('px')
          and abs(saved.get('boxH', 0) - want_h) <= 2
          and abs(saved.get('boxH', 0) - 516) > 20,
          'CSS 兜底 max(18rem,100vh−24rem)=516px｜实高=%.2f 期望=%.2f'
          '（差 %.2f）｜--yy-assess-fit-h=%s'
          % (saved.get('boxH', -1), want_h,
             saved.get('boxH', 0) - want_h, saved.get('fitVar')))

    # G7/G8：resize 时要重算（并且不粘住旧值）
    page.set_viewport_size({'width': 1440, 'height': 700})
    page.wait_for_timeout(400)
    shrunk = page.evaluate(JS_STATE_ABS)
    readings['G_resized_700'] = shrunk
    # 契约（见 assess_grid.js 的 fitHeight）：高 = min(可用空间, max(288, 可用空间−24))
    # —— 矮视口会走下限分支，但**永不超过可用空间**（底边 ≤ 视口底是硬判据）。
    avail7 = 700 - shrunk.get('docTop', 0)
    want7 = min(avail7, max(288.0, avail7 - 24))
    check('G7', '窗口 resize（900→700）后重算：底边仍 <= 视口高，且高 = 契约算式',
          shrunk.get('vh') == 700 and shrunk.get('bottom', 1e9) <= 700
          and abs(shrunk.get('boxH', 0) - want7) <= 2,
          '顶边=%.2f 高=%.2f 底边=%.2f 视口=%s｜可用=%.2f 契约=%.2f 分支=%s｜'
          '--yy-assess-fit-h=%s'
          % (shrunk.get('docTop', -1), shrunk.get('boxH', -1),
             shrunk.get('bottom', -1), shrunk.get('vh'), avail7, want7,
             '下限' if avail7 - 24 < 288 else '留白', shrunk.get('fitVar')))
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.wait_for_timeout(400)
    back = page.evaluate(JS_STATE_ABS)
    readings['G_resized_back_900'] = back
    check('G8', '再 resize 回 900：预算跟着回到 900 的读数（没粘住小屏的值）',
          abs(back.get('boxH', 0) - saved.get('boxH', 0)) <= 2
          and abs(back.get('docTop', 0) - saved.get('docTop', 0)) <= 2,
          '700 时 %.2f → 900 时 %.2f（保存态基准 %.2f）'
          % (shrunk.get('boxH', -1), back.get('boxH', -1),
             saved.get('boxH', -1)))


def section_h(browser, cred, task_id):
    """H 渐进增强：**关掉页面 JS**，矩阵照样渲染、照样能提交（这是本文件的硬口径）。

    为什么单独立一段：E6/E7 都是增强件。关掉 JS 后应当只剩"纯 HTML 表单"的行为 ——
    服务端渲染的 input + 原生 form POST，提交路径一个字都不该依赖脚本。
    """
    print('== H 渐进增强（java_script_enabled=False）==')
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900},
                              java_script_enabled=False)
    ctx.add_cookies(cred)
    pg = ctx.new_page()
    url = '%s/assess/grade/%d' % (BASE, task_id)
    pg.goto(url, wait_until='load', timeout=60000)
    rows = pg.locator('.yy-assess-matrix tbody tr').count()
    inputs = pg.locator('.yy-assess-matrix input[name^="v_"]').count()
    want_inputs = ROWS * len(TREE) * 4
    check('H1', '关掉 JS：矩阵仍由服务端渲染完整（%d 行 × %d 格输入）'
          % (ROWS, want_inputs),
          rows == ROWS and inputs == want_inputs,
          '行=%d 输入格=%d（期望 %d / %d）' % (rows, inputs, ROWS, want_inputs))
    check('H2', '关掉 JS：没有任何粘贴提示条（增强件不在提交路径上）',
          pg.locator('.yy-assess-paste-status').count() == 0,
          '提示条数=%d' % pg.locator('.yy-assess-paste-status').count())
    first = pg.locator('.yy-assess-matrix input[name^="v_"]').first
    name = first.get_attribute('name')
    first.click()
    pg.keyboard.type('7.5')
    typed = first.input_value()
    pg.click('form[action*="/assess/grade/"] button[type="submit"]')
    pg.wait_for_load_state('load')
    rid, iid = int(name.split('_')[1]), int(name.split('_')[2])
    val = G.psql('select value::text from edu_assess_score where task_id=%d '
                 'and roster_id=%d and item_id=%d' % (task_id, rid, iid)).strip()
    readings['H_nojs'] = {'name': name, 'typed': typed, 'sql': val, 'url': pg.url}
    check('H3', '关掉 JS：真键盘输入 + 真点击提交 → 值落库（%s=7.5）' % name,
          typed == '7.5' and val == '7.5',
          '输入框读数=%r｜SQL=%r｜提交后 URL=%s' % (typed, val, pg.url))

    # H4 无脚本兜底（第 1 号缺口的渐进增强要求）：
    # 脚本不可用时高度预算**必须**回到纯 CSS 那条 max(18rem, 100vh−24rem)，
    # 也就是「与改动前逐字节等价」——可以不够聪明，但不许比现在差（不许变成 auto/none）。
    pg.goto(url, wait_until='load', timeout=60000)
    pg.wait_for_timeout(300)
    fb = pg.evaluate(r"""() => {
      const b = document.querySelector('.yy-assess-scroll');
      const cs = getComputedStyle(b);
      const r = b.getBoundingClientRect();
      return {maxH: cs.maxHeight, overflow: cs.overflowX + '/' + cs.overflowY,
              fitVar: b.style.getPropertyValue('--yy-assess-fit-h') || '',
              bottom: +r.bottom.toFixed(2), vh: window.innerHeight,
              rawVar: cs.getPropertyValue('--yy-assess-fit-h')};
    }""")
    readings['H_nojs_budget'] = fb
    check('H4', '关掉 JS：高度预算 = CSS 兜底 516px（=max(18rem,100vh−24rem)，与改动前逐字节等价）',
          fb.get('maxH') == '516px' and not fb.get('fitVar')
          and fb.get('overflow') == 'auto/auto',
          'computed max-height=%s（期望 516px）｜内联 --yy-assess-fit-h=%r｜'
          'overflow=%s｜底边=%.2f/视口=%s（兜底不保证保存态合规，这是它存在的边界）'
          % (fb.get('maxH'), fb.get('fitVar'), fb.get('overflow'),
             fb.get('bottom', -1), fb.get('vh')))
    ctx.close()


# ----------------------------------------------------------------------
# B 跨引擎（Chromium / WebKit）
# ----------------------------------------------------------------------

#: 两套读数：同一组断言、同一份夹具，只换渲染引擎
ENGINES = [('Chromium', 'chromium'), ('WebKit', 'webkit')]


def launch_engine(pw, key):
    if key == 'chromium':
        return pw.chromium.launch(channel='chrome')
    if key == 'webkit':
        return pw.webkit.launch()
    raise ValueError('未知引擎 %r' % key)


def section_b(pw, adm_cred, stu_cred, task_id, fill_task):
    """B 跨引擎冻结：thead 上的 position:sticky 各引擎支持度不同（Safari 历史上对
    thead / tr 的 sticky 支持差），只在 Chromium 上量等于没回答「别的引擎冻不冻」。

    设计 §6.6 把纯 CSS 记为**当时的选择**、不是不可改的约束 ⇒ 本段读数直接决定
    要不要改成「逐行 th sticky + JS 算 top 偏移」那种更兼容的写法。
    WebKit 起不来时打 N/A（写明原因），**不当通过**。
    """
    print('== B 跨引擎冻结（Chromium / WebKit，同一夹具同一断言）==')
    grade_url = '%s/assess/grade/%d' % (BASE, task_id)
    fill_url = '%s/assess/fill/%d' % (BASE, fill_task)
    out = {}
    for label, key in ENGINES:
        try:
            br = launch_engine(pw, key)
        except Exception as exc:                                   # pragma: no cover
            na('B-ALL-%s' % label, '引擎可用性',
               '本机起不来：%s' % repr(exc)[:180])
            out[key] = {'available': False, 'error': repr(exc)[:400]}
            continue
        out[key] = {'available': True, 'version': br.version}
        tagn = '[%s]' % label
        # ---- 整班打分页：三处 sticky 的几何 ----
        ctx = br.new_context(viewport={'width': 1440, 'height': 900})
        ctx.add_cookies(adm_cred)
        pg = ctx.new_page()
        pg.goto(grade_url, wait_until='load', timeout=60000)
        pg.wait_for_timeout(700)
        scroll(pg, -100000, -100000)
        a = state(pg)
        scroll(pg, 200, 0)
        b = state(pg)
        scroll(pg, 0, 300)
        c = state(pg)
        out[key]['grade'] = {'origin': a, 'vscroll': b, 'hscroll': c}
        if 'error' in a:
            check('B1%s' % tagn, '前置事实：矩阵在自有滚动容器里', False, '%s' % a)
            ctx.close()
            br.close()
            continue
        dv = [round(b['headTops'][i] - a['headTops'][i], 2)
              for i in range(len(a['headTops']))]
        dh = [round(c['headLefts'][i] - b['headLefts'][i], 2)
              for i in range(len(b['headLefts']))]
        out[key]['dv'] = dv
        out[key]['dh'] = dh
        check('B1%s' % tagn, '前置事实：三处 sticky 都在 + 三层表头 + 双向有行程',
              a['theadPos'] == 'sticky' and a['leadPos'] == 'sticky'
              and a['td0Pos'] == 'sticky' and a['headRowCount'] >= 3
              and a['maxScrollTop'] > 100 and a['maxScrollLeft'] > 100,
              '%s %s｜thead=%s 交叉格=%s 首列=%s｜行程 纵%s/横%s'
              % (label, br.version, a['theadPos'], a['leadPos'], a['td0Pos'],
                 a['maxScrollTop'], a['maxScrollLeft']))
        check('B2%s' % tagn, '纵滚 200：**全部**表头行位移 ≈0（整段 thead 一起冻）',
              all(abs(x) < 1.5 for x in dv),
              'headTops@0=%s → @200=%s（Δ=%s，判据 |Δ|<1.5）'
              % (a['headTops'], b['headTops'], dv))
        check('B3%s' % tagn, '同期 tbody 首行确实在走（Δ≈-200）',
              abs((b['bodyRow0Top'] - a['bodyRow0Top']) + 200) < 3,
              'bodyRow0Top %.2f→%.2f（Δ=%.2f，scrollTop %s→%s）'
              % (a['bodyRow0Top'], b['bodyRow0Top'],
                 b['bodyRow0Top'] - a['bodyRow0Top'], a['scrollTop'],
                 b['scrollTop']))
        check('B4%s' % tagn, '横滚 300：首列不动 + 第 3 列在走',
              abs(c['col0Left'] - b['col0Left']) < 1.5
              and abs((c['col2Left'] - b['col2Left']) + 300) < 3,
              'headLefts Δ=%s｜首列 %.2f→%.2f｜第3列 %.2f→%.2f'
              % (dh, b['col0Left'], c['col0Left'], b['col2Left'],
                 c['col2Left']))
        # ---- 反向注入（就在引擎里做，不靠改源码）----
        # 把 thead 的 sticky 当场关掉：① 表头必须跟着滚走 ⇒ 证明"冻住"确实来自这条
        # 规则（而不是别的什么）；② 页面**不坏**（还能聚焦、输入、滚动）⇒ 这就是
        # 「老引擎不支持 thead sticky 时的降级形态」的证据：退化成"不冻"，不是"坏"。
        pg.add_style_tag(content='.yy-assess-scroll .yy-assess-matrix thead'
                                 '{ position: static !important; }')
        scroll(pg, -100000, -100000)
        a2 = state(pg)
        scroll(pg, 200, 0)
        b2 = state(pg)
        dv2 = [round(b2['headTops'][i] - a2['headTops'][i], 2)
               for i in range(len(a2['headTops']))]
        usable = pg.evaluate("""() => {
          const i = document.querySelector('.yy-assess-matrix input[type="number"]');
          i.focus();
          i.value = '3';
          i.dispatchEvent(new Event('input', {bubbles: true}));
          const bx = document.querySelector('.yy-assess-scroll');
          // ⚠ 不能拿"当前 scrollTop > 0"当可用性判据：**聚焦会把单元格滚进视野**
          // （Chromium 会、WebKit 不一定）⇒ 那是聚焦的副作用，不是坏掉。
          // 判据改成"我让它滚，它真的滚了"，与焦点无关。
          const keep = bx.scrollTop;
          bx.scrollTop = Math.min(100, bx.scrollHeight - bx.clientHeight);
          const moved = bx.scrollTop > 0;
          bx.scrollTop = keep;
          return {focused: document.activeElement === i, value: i.value,
                  rows: document.querySelectorAll('.yy-assess-matrix tbody tr').length,
                  scrollable: moved,
                  scrollTopAfterFocus: keep};
        }""")
        out[key]['inject_static_thead'] = {'dv': dv2, 'usable': usable}
        check('B6%s' % tagn,
              '反向注入「关掉 thead sticky」：表头确实跟着走（证明冻结来自这条规则），'
              '且页面不坏（可聚焦 / 可输入 / 可滚动）',
              len(dv2) >= 3 and all(abs(x + 200) < 3 for x in dv2)
              and usable['focused'] and usable['value'] == '3'
              and usable['rows'] == ROWS and usable['scrollable'],
              '注入后表头位移=%s（期望 ≈-200）｜可用性=%s'
              % (dv2, usable))
        ctx.close()
        # ---- 学生填写页：冻结 + 第 1 号缺口的判据（保存后底边）----
        ctx2 = br.new_context(viewport={'width': 1440, 'height': 900})
        ctx2.add_cookies(stu_cred)
        pg2 = ctx2.new_page()
        pg2.goto(fill_url, wait_until='load', timeout=60000)
        pg2.wait_for_timeout(700)
        f0 = pg2.evaluate(JS_STATE_ABS)
        if not f0.get('found'):
            # 拿不到矩阵要**说清落地在哪**（多半是身份/任务门禁把页面跳走了），
            # 不能靠 999 假读数糊过去。
            note('%s 学生填写页没拿到矩阵：落地 URL=%s｜页内提示=%r'
                 % (tagn, pg2.url, pg2.evaluate(
                     "() => Array.prototype.map.call("
                     "document.querySelectorAll('.alert, h4'), "
                     "e => e.textContent.replace(/\\s+/g, ' ').trim().slice(0, 60))")))
        scroll(pg2, 200, 0)
        f1 = state(pg2)
        # ⚠ 不许空转：表头位移必须是**真读到的 3 行**（长度 <3 一律判红 —— 曾经
        # 因为 JS_STATE_ABS 没有 headTops 字段，这里静默成了 all([]) == True 的假绿）。
        tops0 = f0.get('headTops') or []
        tops1 = f1.get('headTops') or []
        dvf = ([round(tops1[i] - tops0[i], 2) for i in range(len(tops0))]
               if (f0.get('found') and 'error' not in f1
                   and len(tops0) == len(tops1) and len(tops0) >= 3) else [999])
        pg2.click('form[action*="/assess/fill/"] button[type="submit"]')
        pg2.wait_for_load_state('load')
        pg2.wait_for_timeout(600)
        fs = pg2.evaluate(JS_STATE_ABS)
        out[key]['fill'] = {'origin': f0, 'vscroll': f1, 'saved': fs}
        check('B5%s' % tagn, '学生填写页：纵滚表头不动（3 行实测）+ 保存态底边 <= 视口高',
              len(dvf) >= 3 and all(abs(x) < 1.5 for x in dvf)
              and ('已保存' in (fs.get('savedBanner') or ''))
              and fs.get('bottom', 1e9) <= fs.get('vh', 0),
              '表头行数=%s 位移=%s（长度必须 >=3，否则是空转）｜'
              '保存态 顶边=%.2f+高=%.2f=底边=%.2f（视口 %s）｜'
              '--yy-assess-fit-h=%s｜提示条=%r'
              % (len(tops0), dvf, fs.get('docTop', -1), fs.get('boxH', -1),
                 fs.get('bottom', -1), fs.get('vh'), fs.get('fitVar'),
                 (fs.get('savedBanner') or '')[:20]))
        ctx2.close()
        br.close()
    readings['B_engines'] = out
    if all(v.get('available') for v in out.values()):
        note('两引擎对照：纵滚表头位移 chromium=%s webkit=%s｜保存态 fitVar %s / %s'
             % (out['chromium'].get('dv'), out['webkit'].get('dv'),
                (out['chromium'].get('fill') or {}).get('saved', {}).get('fitVar'),
                (out['webkit'].get('fill') or {}).get('saved', {}).get('fitVar')))


# ----------------------------------------------------------------------
# S 小屏形态
# ----------------------------------------------------------------------

#: 小屏口径：手机竖屏 + 平板竖屏（都是「视口宽度 < 矩阵自然宽度」的真实形态）
SMALL_VIEWPORTS = [(390, 844, '手机竖屏'), (768, 1024, '平板竖屏')]


def section_s(browser, adm_cred, task_id):
    """S 小屏形态：上一轮只测了 1440×900，小屏**完全没测**。

    先回答「小屏下矩阵长什么样」：门户矩阵是**服务端渲染**、**没有小屏分支**
    （不像后台有 isSmall 直接不渲染）⇒ 小屏下矩阵照常存在、横向必然很宽，
    所以这里不是 N/A，而是必须给断言；真正测不到的（iOS 动态视口 / 触摸惯性）
    单独打 N/A，不当通过。
    """
    print('== S 小屏形态与断言 ==')
    url = '%s/assess/grade/%d' % (BASE, task_id)
    out = {}
    for w, h, tag in SMALL_VIEWPORTS:
        ctx = browser.new_context(viewport={'width': w, 'height': h})
        ctx.add_cookies(adm_cred)
        pg = ctx.new_page()
        pg.goto(url, wait_until='load', timeout=60000)
        pg.wait_for_timeout(700)
        sh = pg.evaluate(JS_SHAPE)
        scroll(pg, -100000, -100000)
        a = state(pg)
        scroll(pg, 200, 0)
        b = state(pg)
        dv = ([round(b['headTops'][i] - a['headTops'][i], 2)
               for i in range(len(a['headTops'] or []))]
              if 'error' not in a else [999])
        out['%dx%d' % (w, h)] = {'shape': sh, 'dv': dv, 'origin': a}
        tagn = '[%dx%d]' % (w, h)
        check('S1%s' % tagn, '小屏仍完整渲染 27 行 × 20 项，且容器就是滚动盒',
              sh.get('found') and sh.get('rows') == ROWS
              and sh.get('inputs') == ROWS * len(TREE) * 4
              and sh.get('maxScrollLeft', 0) > 100,
              '%s：box=%.0f×%.0f｜行=%s 输入格=%s｜横向行程=%s'
              % (tag, sh.get('boxW', -1), sh.get('boxH', -1), sh.get('rows'),
                 sh.get('inputs'), sh.get('maxScrollLeft')))
        check('S2%s' % tagn, '小屏横向必滚，且首列冻结是**最有用**的那一条（可见列数小）',
              sh.get('maxScrollLeft', 0) > 300 and sh.get('leadPos') == 'sticky'
              and sh.get('leadW', 0) > 0 and sh.get('boxW', 0) < 1000,
              '%s：容器宽 %.0f、自然宽 %.0f ⇒ 横向行程 %s px｜'
              '首列 %.0fpx（sticky=%s）⇒ 约 %.1f 个数字列可见'
              % (tag, sh.get('boxW', -1),
                 (sh.get('boxW', 0) + sh.get('maxScrollLeft', 0)),
                 sh.get('maxScrollLeft'), sh.get('leadW', -1),
                 sh.get('leadPos'),
                 max(0.0, (sh.get('boxW', 0) - sh.get('leadW', 0)) / 90.0)))
        check('S3%s' % tagn, '小屏纵滚 200 表头照样不动（冻结点没被窄屏吃掉）',
              all(abs(x) < 1.5 for x in dv),
              '%s：表头位移=%s（判据 |Δ|<1.5）｜纵向行程=%s'
              % (tag, dv, sh.get('maxScrollTop')))
        check('S4%s' % tagn, '小屏高度预算成立：容器底边 <= 视口高',
              sh.get('bottom', 1e9) <= sh.get('vh', 0),
              '%s：顶边=%.2f 高=%.2f 底边=%.2f（视口 %s）｜--yy-assess-fit-h=%s'
              % (tag, sh.get('top', -1), sh.get('boxH', -1),
                 sh.get('bottom', -1), sh.get('vh'), sh.get('fitVar')))
        check('S5%s' % tagn, '小屏：矩阵的宽度被容器吃住，**没有把整页撑出横向滚动条**',
              sh.get('docScrollW', 1e9) <= sh.get('vw', 0) + 1
              and sh.get('bodyScrollW', 1e9) <= sh.get('vw', 0) + 1,
              '%s：document.scrollWidth=%s body.scrollWidth=%s 视口宽=%s'
              % (tag, sh.get('docScrollW'), sh.get('bodyScrollW'),
                 sh.get('vw')))
        scroll(pg, -100000, -100000)
        ctx.close()
    readings['S_viewports'] = out
    # 真的测不到的（结构性）：打印理由，不当通过
    na('S-N/A-1', 'iOS 动态视口（地址栏收起/展开 ⇒ 100vh 会变）',
       'Playwright 的固定 viewport 复现不出动态视口，本机也没有 iOS Safari ⇒ '
       '结构性测不到；这不是「通过」，只是这一条今天没有判据')
    na('S-N/A-2', '触摸惯性横滑与 sticky 的交互',
       'Playwright 的鼠标滚轮 ≠ 真机触摸惯性；本机无触屏 ⇒ 测不到，不当通过')


# ----------------------------------------------------------------------
# D 双轨 (项,轨) 列键 —— 只查，不做
# ----------------------------------------------------------------------

#: 设计 §6.7 ③ 承诺列键 = 「(项, 轨)」、双轨项占两列（§5.3）；§6.8 也说列键要能从一轨走到另一轨。
#: 本段的职责不是「实现它」，而是**证明今天够不到触发条件**，并把触发条件写死在这里：
#: 一旦库里出现第一条第二轨，D1 立刻变红 ⇒ 那时才必须动列键。
DUAL_TODO = (
    '触发条件（出现即 D1 变红，必须改列键）：'
    '① 任何 edu.assess.item 的 track=dual（叶子项），或 '
    '② 任何 edu.assess.score 的 track=subjective，或 '
    '③ 同一个 (task_id,item_id,roster_id,scorer_ref) 下出现两条不同 track。'
    '届时要做的是：门户矩阵列键由 v_<roster>_<item> 改成能表达轨的形式（双轨项占两列）、'
    'xlsx 导出与导入按（项,轨）出两列、键盘移动与粘贴的 (行,列) 索引跟着改；'
    '在此之前**不要为一个不存在的场景写代码**。')


def section_d(adm):
    """D 双轨 (项,轨) 列键：先核实「今天到底有没有任何模板会产生第二轨」。"""
    print('== D 双轨 (项,轨) 列键核查（只查，不做）==')
    dual = G.psql_int("select count(*) from edu_assess_item where track = 'dual'")
    subj = G.psql_int("select count(*) from edu_assess_score where track = 'subjective'")
    multi = G.psql_int(
        'select count(*) from (select task_id, item_id, roster_id, scorer_ref, '
        'count(distinct track) c from edu_assess_score group by 1,2,3,4 '
        'having count(distinct track) > 1) x')
    leaves = G.psql_int("select count(*) from edu_assess_item where item_kind = 'leaf'")
    scores = G.psql_int('select count(*) from edu_assess_score')
    src = (ROOT / 'custom_addons/edu_assess/views/assess_portal.xml').read_text(
        encoding='utf-8')
    name_keys = re.findall(r"t-att-name=\"'v_%d_%d' % \(roster\.id, it\.id\)\"", src)
    has_track_key = 'it.track' in src
    portal = (ROOT / 'custom_addons/edu_assess/controllers/portal.py').read_text(
        encoding='utf-8')
    at = portal.index('def _write_scores')
    body = portal[at:portal.index('\ndef ', at + 10)]
    readings['D_dual'] = {
        'dual_items': dual, 'subjective_scores': subj,
        'multi_track_groups': multi, 'leaf_items': leaves, 'scores': scores,
        'view_column_key_count': len(name_keys),
        'view_key_has_track': has_track_key,
        'write_key_has_track': "'track'" in body,
        'write_key_snippet': [ln.strip() for ln in body.splitlines()
                              if 'scorer_ref' in ln or 'limit=' in ln][:4],
        'todo': DUAL_TODO}
    check('D1', '今天没有任何模板会产生第二轨（dual 项 / subjective 打分 / 双轨组 = 0）',
          dual == 0 and subj == 0 and multi == 0,
          'edu_assess_item.track=dual：%d（叶子项共 %d）｜'
          'edu_assess_score.track=subjective：%d（打分共 %d）｜'
          '同一 (task,item,roster,scorer_ref) 出现两条不同 track 的组数：%d%s'
          % (dual, leaves, subj, scores, multi,
             '' if dual == 0 and subj == 0 and multi == 0
             else ' ⚠ ' + DUAL_TODO))
    check('D2', '门户列键 = v_<roster>_<item>，**没有轨位**（列键只能等于物理列）',
          len(name_keys) == 2 and not has_track_key,
          'assess_portal.xml 里 v_<roster>_<item> 命名出现 %d 处（矩阵两页各一处）｜'
          '列键用到 it.track=%s' % (len(name_keys), has_track_key))
    check('D3', '写库的唯一键查询也不含 track（limit=1）⇒ 第二条轨没有位置可放',
          "'track'" not in body and 'limit=1' in body,
          'controllers/portal.py 的 _write_scores：含 track=%s｜%s'
          % ("'track'" in body, readings['D_dual']['write_key_snippet']))
    note('登记为待办（**不写代码**）：%s' % DUAL_TODO)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true', help='保留夹具（排查用）')
    ap.add_argument('--only', default='',
                    help='只跑某段：p/f/v/c/r/g/h/a/b/s/d（反向注入窗口用）')
    ap.add_argument('--no-axe', action='store_true', help='跳过 A 段（无 playwright 时）')
    args = ap.parse_args()

    t0 = time.strftime('%Y-%m-%d %H:%M:%S')
    print('== 评估矩阵 E6 冻结 / E7 整块粘贴 —— 真浏览器验收（%s）==' % t0)
    try:
        r = requests.Session()
        r.trust_env = False
        probe = r.get(BASE + '/web/login?db=%s' % DB, timeout=15)
        print('   站点探活：%s /web/login -> %s' % (BASE, probe.status_code))
    except Exception as exc:
        die('站点不可达：%s' % exc)

    adm, uid = G.login('backoffice@local')
    if not adm:
        die('backoffice@local 登不上（夹具建不起来）')

    print('-- 建夹具（三层模板 + 27 行名单 × 2 页：整班打分 / 学生填写）--')
    tpl, task_id, rosters, leaves = build_fixture(adm)
    tpl_f, fill_task, rosters_f, _leaves_f = build_fixture(
        adm, target='faculty', scorer='student', tag='（学生填）')
    print('   打分页：模板 %d｜叶子 %d｜任务 %d｜名单 %d'
          % (tpl, len(leaves), task_id, len(rosters)))
    print('   填写页：模板 %d｜任务 %d｜名单 %d' % (tpl_f, fill_task, len(rosters_f)))
    readings['fixture'] = {'template': tpl, 'task': task_id,
                           'rosters': len(rosters), 'leaves': len(leaves),
                           'rows': ROWS,
                           'fill_template': tpl_f, 'fill_task': fill_task}
    stu, _e = G.login('stu@local')
    if not stu:
        die('stu@local 登不上（填写页段取不了证）')

    only0 = (args.only or '').lower()
    if only0 in ('', 'd'):
        section_d(adm)                       # D 段不建浏览器：只读库 + 读源码

    sync_playwright = (None if only0 == 'd' else open_browser())
    ctx_kwargs = {'viewport': {'width': 1440, 'height': 900}}
    if sync_playwright is not None:
        try:
            with sync_playwright() as pw:
                b = pw.chromium.launch(channel='chrome')
                ctx = b.new_context(permissions=['clipboard-read', 'clipboard-write'],
                                    **ctx_kwargs)
                ctx.add_cookies(cookies_of(adm))
                page = ctx.new_page()
                url = '%s/assess/grade/%d' % (BASE, task_id)
                results_url = '%s/assess/task/%d/results' % (BASE, task_id)
                page.goto(url, wait_until='networkidle', timeout=60000)
                page.wait_for_timeout(400)
                print('   浏览器：Chromium %s｜视口 1440×900｜%s' % (b.version, url))
                readings['browser'] = {'version': b.version,
                                       'url': '/assess/grade/%d' % task_id,
                                       'viewport': '1440x900'}
                only = only0
                if only in ('', 'p'):
                    section_p(page, task_id, readings)
                if only in ('', 'f'):
                    section_f(page)
                if only in ('', 'v'):
                    section_v(page, adm, task_id)
                    page.goto(url, wait_until='networkidle', timeout=60000)
                    page.wait_for_timeout(300)
                if only in ('', 'c'):
                    section_c(page, task_id)
                if only in ('', 'r'):
                    section_r(page, task_id)
                if only in ('', 'g'):
                    ctx2 = b.new_context(permissions=['clipboard-read', 'clipboard-write'],
                                         **ctx_kwargs)
                    ctx2.add_cookies(cookies_of(stu))
                    page2 = ctx2.new_page()
                    section_g(page2, fill_task)
                    ctx2.close()
                if only in ('', 'h'):
                    section_h(b, cookies_of(adm), task_id)
                if only in ('', 'b'):
                    section_b(pw, cookies_of(adm), cookies_of(stu), task_id, fill_task)
                if only in ('', 's'):
                    section_s(b, cookies_of(adm), task_id)
                if only in ('', 'a') and not args.no_axe:
                    section_a(page, url, task_id)
                    if only == '':
                        res = axe_ab(page, results_url, 'A·结果页（只读矩阵）', with_paste=False)
                        readings['A_results'] = res
                        new_rules = [r for r in res['frozen'].get('rules', [])
                                     if r not in res['before'].get('rules', [])]
                        check('A4', '结果页（无输入矩阵）冻结态没有新增 axe 规则',
                              not new_rules,
                              '新增=%s｜冻结态规则=%s'
                              % (new_rules, res['frozen'].get('rules')))
                    # A5–A7：门槛口径（WCAG A/AA 标签）下的**绝对** 0 条
                    section_a_strict(b, [
                        ('A5', '整班打分页', cookies_of(adm), url),
                        ('A6', '学生填写页', cookies_of(stu),
                         '%s/assess/fill/%d' % (BASE, fill_task)),
                        ('A7', '结果页（只读矩阵）', cookies_of(adm), results_url)])
                b.close()

        except Exception as exc:
            if isinstance(exc, SystemExit):
                raise
            import traceback
            traceback.print_exc()
            die('浏览器段失败：%s' % repr(exc)[:300])

    if not args.keep:
        cleanup(adm)
    else:
        print('   （--keep：夹具保留，task=%d）' % task_id)

    failed = [i for i in items if not i['pass']]
    passed = len(items) - len(failed)
    print('\n== 小结：%d/%d 通过 + %d 条 N/A（%s）=='
          % (passed, len(items), len(nas), t0))
    for i in failed:
        print('   FAIL %s %s｜%s' % (i['no'], i['name'], i['detail'][:220]))
    for n in nas:
        print('   N/A  %s %s｜%s' % (n['no'], n['name'], n['reason'][:200]))
    json.dump({'base': BASE, 'when_start': t0,
               'when_end': time.strftime('%Y-%m-%d %H:%M:%S'),
               'readings': readings, 'items': items, 'na': nas,
               'passed': passed, 'failed': len(failed)},
              open(RESULTS, 'w'), ensure_ascii=False, indent=1)
    print('结果落盘：%s' % RESULTS)
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except requests.exceptions.RequestException as exc:
        print('ENV：请求失败（并行 agent 的 safe_upgrade 会重启 web）：%s' % exc)
        sys.exit(2)
