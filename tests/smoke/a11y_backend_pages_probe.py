#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台页**逐页读数**量具（2026-09-29 扩覆盖）：把 axe 的每一条违规连**选择器 + 元素 HTML**打出来。

## 为什么需要它（与三把既有尺子的分工）

· scripts/check_accessibility.py          = **门禁**：判据 / 基线 / 退出码；后台页只给「外壳判据 N 条 ｜ 核心清单 M 条」
  —— 它**按规则聚合**，看不到「这条违规到底是页面上哪个元素」。
· tests/smoke/a11y_ax_tree_probe.py       = 浏览器 AX 树，只回答「checkbox 有没有可访问名」。
· tests/smoke/a11y_label_dom_compare.py   = 列表选择框的 DOM 层（label 实体 / id / 父链）。
· 本脚本                                   = **逐页、逐条、带元素定位**的读数，并把每条违规标成
                                            「判据」还是「已登记核心规则（只读数）」。

三轮扩覆盖时它正是用来把「image-alt ×5 / aria-prohibited-attr ×5 / list ×4」拆到具体元素的。

## 形态断言（反假绿）

--expect-form 打开后：每一页都必须渲染出与 scripts/check_accessibility.py 的 BACKEND_EXPECT_VIEW
一致的视图根。带记录 id 的样本（/odoo/students/5）一旦记录消失，URL **仍返 200** 只是静默回落成
默认视图 —— 那种情况下本脚本 **FAIL**，绝不报「0 违规」。

## 跑法

    python3 tests/smoke/a11y_backend_pages_probe.py                    # 7 页（门禁登记的后台样本）
    python3 tests/smoke/a11y_backend_pages_probe.py --path /odoo/apps --dump
    python3 tests/smoke/a11y_backend_pages_probe.py --expect-form      # 带形态断言

## 退出码

0 = 全部页量到（且形态断言通过，若开了）｜ 1 = **判据失败**（某页量不到 / 形态不符 / --strict 下有未登记规则）
｜ 2 = ENV（升级锁 / 站点不可达 / 登录不上 / 浏览器起不来）—— ENV 不当通过。

## 自清

**只读**：会话认证 + GET；不点按钮、不发写请求、不建夹具。
"""
import argparse
import json
import os
import sys

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
LOGIN = (os.environ.get('A11Y_BO_LOGIN', 'backoffice@local'),
         os.environ.get('A11Y_BO_PWD', 'demo123'))
# 门禁登记的后台样本（与 scripts/check_accessibility.py 的 AUDIT_ROUTES 后台段一致）
DEFAULT_PATHS = ('/odoo/contacts', '/odoo/students', '/odoo/batches', '/odoo/apps',
                 '/odoo/contacts/1', '/odoo/students/5', '/odoo/grade-configuration')

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
try:
    import check_accessibility as GATE          # 复用门禁的常量与算法（单一来源，不抄第二份）
except Exception as exc:                        # pragma: no cover
    print('ENV：读不到 scripts/check_accessibility.py 的常量（%s）' % exc)
    sys.exit(2)

PROBE_JS = r"""async () => {
  const vq = (s) => document.querySelectorAll(s).length;
  const shell = document.querySelector('.o_navbar');
  const opts = {resultTypes: ['violations'],
                runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa']}};
  const r = await axe.run(document, opts);
  const innav = (el) => !!(el && el.closest && el.closest('.o_navbar'));
  const out = (r.violations || []).map(v => ({
    id: v.id, impact: v.impact, help: v.help,
    nodes: (v.nodes || []).map(n => {
      let el = null;
      try { el = document.querySelector(n.target.join(' ')); } catch (e) { el = null; }
      return {target: n.target.join(' '),
              elem_name: (el && el.getAttribute) ? (el.getAttribute('name') || '') : '',
              elem_id: (el && el.id) ? el.id : '',
              in_navbar: innav(el),
              html: (el ? el.outerHTML : '').replace(/\s+/g, ' ').slice(0, 170),
              text: (el && el.innerText ? el.innerText.replace(/\s+/g, ' ').slice(0, 60) : ''),
              summary: (n.failureSummary || '').replace(/\s+/g, ' ').slice(0, 160)};
    })
  }));
  return {violations: out,
          view: {list: vq('.o_list_view'), kanban: vq('.o_kanban_view'),
                 form: vq('.o_form_view'), settings: vq('.o_settings_container')},
          navbar: {exists: !!shell,
                   sections: vq('.o_menu_sections'), systray: vq('.o_menu_systray'),
                   rows: vq('.o_data_row'), cards: vq('.o_kanban_record'),
                   checkboxes: vq('input[type=checkbox]')},
          shell_text: shell ? (""" + GATE.SHELL_TEXT_JS + r""")() : {missing: true, rows: []}};
}"""


def lock_path():
    return os.path.join(os.environ.get('TMPDIR') or '/tmp', 'edu19_upgrade.lock')


def probe_session():
    """就绪探针专用 Session：trust_env=False（理由见 a11y_ax_tree_probe.probe_session）。"""
    s = requests.Session()
    s.trust_env = False
    return s


def preflight():
    if os.path.isdir(lock_path()):
        return '有升级在进行（%s 存在）' % lock_path()
    try:
        r = probe_session().get(BASE + '/web/login?db=' + DB, timeout=15, allow_redirects=False)
    except Exception as exc:
        return '站点不可达：%s' % exc
    if r.status_code not in (200, 302, 303):
        return '站点未就绪（/web/login → %s）' % r.status_code
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate', json={'jsonrpc': '2.0', 'params': {
        'db': DB, 'login': LOGIN[0], 'password': LOGIN[1]}}, timeout=25)
    if r.status_code != 200:
        return '登录失败（HTTP %s）' % r.status_code
    d = r.json()
    if d.get('error'):
        return '登录被拒（%s）' % json.dumps(d['error'])[:120]
    return [{'name': c.name, 'value': c.value, 'domain': 'localhost',
             'path': c.path or '/'} for c in s.cookies]


def ax_unnamed(ctx, pg):
    """浏览器自己的 AX 树：按 role 统计「没有可访问名」的控件数（独立于 axe）。"""
    cdp = ctx.new_cdp_session(pg)
    cdp.send('Accessibility.enable')
    tree = cdp.send('Accessibility.getFullAXTree')
    roles = {}
    for n in tree.get('nodes', []):
        role = ((n.get('role') or {}).get('value')) or ''
        name = ((n.get('name') or {}).get('value')) or ''
        if role in ('checkbox', 'radio', 'combobox', 'textbox', 'button', 'link',
                    'searchbox', 'spinbutton', 'menuitem', 'switch'):
            slot = roles.setdefault(role, [0, 0])
            slot[0] += 1
            if not name.strip():
                slot[1] += 1
    return {k: {'total': v[0], 'unnamed': v[1]} for k, v in sorted(roles.items())}


def main():
    ap = argparse.ArgumentParser(description='后台页逐页 axe 读数（含元素定位）')
    ap.add_argument('--path', default=','.join(DEFAULT_PATHS))
    ap.add_argument('--dump', action='store_true', help='打印每条违规的元素 HTML')
    ap.add_argument('--expect-form', action='store_true',
                    help='开启形态断言（与门禁 BACKEND_EXPECT_VIEW 同一张表）')
    ap.add_argument('--strict', action='store_true',
                    help='出现**未登记**规则即 FAIL（与门禁判据同口径）')
    ap.add_argument('--json', dest='json_out', help='读数落盘')
    args = ap.parse_args()

    pre = preflight()
    if isinstance(pre, str):
        print('ENV：%s ⇒ 本轮作废（不是判据失败，也不当通过）' % pre)
        return 2
    cookies = pre
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print('ENV：playwright 不可用：%s' % exc)
        return 2

    paths = [p.strip() for p in args.path.split(',') if p.strip()]
    fails, rows = [], {}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(channel='chrome', headless=True, args=['--no-proxy-server'])
            for path in paths:
                ctx = b.new_context(viewport={'width': 1280, 'height': 900}, locale='zh-CN')
                ctx.add_cookies(cookies)
                pg = ctx.new_page()
                # console 报错 / 未捕获异常计数：Owl 模板继承命不中 xpath 会**抛错并让整个资产包挂掉**
                # （2026-09-29 的教训），那种失败会在这里现形 —— 比对着一张干净页面更有说服力。
                js_errs, page_errs = [], []
                pg.on('console', lambda m: js_errs.append(m.text[:160]) if m.type == 'error' else None)
                pg.on('pageerror', lambda e: page_errs.append(str(e)[:160]))
                try:
                    r = pg.goto(BASE + path, wait_until='domcontentloaded', timeout=90000)
                    status = r.status if r else 0
                    pg.wait_for_selector('.o_navbar', timeout=25000)
                    pg.wait_for_timeout(3000)
                    pg.add_script_tag(content=GATE.axe_source()[0] or '')
                    data = pg.evaluate(PROBE_JS)
                    ax = ax_unnamed(ctx, pg)
                    gated, core, notes, localbad, skipped = GATE.partition_backend(
                        # 与门禁同口径：把 elem_name / elem_id 一起交给 partition_backend，
                        # 否则探针会把「自研视图声明的按钮」误报成核心只读数（2026-09-29 踩过）。
                        [{'id': v['id'], 'impact': v['impact'],
                          'nodes': [{'target': [n['target']], 'elem_name': n.get('elem_name', ''),
                                     'elem_id': n.get('elem_id', '')} for n in v['nodes']]}
                         for v in data['violations']],
                        [], data['shell_text'].get('rows') or [])
                    rows[path] = {'status': status, 'view': data['view'], 'navbar': data['navbar'],
                                  'console_errors': js_errs, 'page_errors': page_errs,
                                  'ax': ax, 'violations': data['violations'],
                                  'gated': [g['rule'] for g in gated], 'notes': notes,
                                  'local_contrast': localbad, 'local_skipped': skipped}
                    print('== %-30s HTTP %s ｜ 形态 %s ｜ 行/卡 %s/%s ｜ 选择框 %s'
                          % (path, status, '/'.join(k for k, v in data['view'].items() if v) or '（无）',
                             data['navbar']['rows'], data['navbar']['cards'],
                             data['navbar']['checkboxes']))
                    if status != 200:
                        fails.append('%s：HTTP %s' % (path, status))
                    if not data['navbar']['exists']:
                        fails.append('%s：量不到后台外壳（.o_navbar 不存在）' % path)
                    if args.expect_form:
                        ok, why = GATE.backend_view_ok(path, data['view'])
                        print('   %s 形态断言：%s' % ('PASS' if ok else 'FAIL', why))
                        if not ok:
                            fails.append('%s：形态断言失败（%s）' % (path, why))
                    nameless = {k: v['unnamed'] for k, v in ax.items() if v['unnamed']}
                    print('   console 报错 %d 条 / 未捕获异常 %d 条%s'
                          % (len(js_errs), len(page_errs),
                             ('（例：%s）' % (js_errs + page_errs)[0][:90]) if (js_errs or page_errs) else ''))
                    if js_errs or page_errs:
                        fails.append('%s：console/未捕获异常 %d 条：%s'
                                     % (path, len(js_errs) + len(page_errs),
                                        (js_errs + page_errs)[0][:120]))
                    print('   AX 树无名控件：%s ｜ 判据违规 %s ｜ 本地对比度 %s（跳过 复杂底%s/不可见%s）'
                          % (nameless or '0',
                             sorted(set(g['rule'] for g in gated)) or 0, len(localbad),
                             skipped['complex_bg'], skipped['invisible']))
                    for v in data['violations']:
                        kind = ('**判据**' if v['id'] not in GATE.CORE_RULES_KNOWN
                                else '核心清单')
                        print('   [%s] %-22s %-9s x%d' % (kind, v['id'], v['impact'], len(v['nodes'])))
                        for n in v['nodes']:
                            nav = '（导航栏内）' if n['in_navbar'] else ''
                            print('        %s %s' % (n['target'][:96], nav))
                            if args.dump:
                                print('          html: %s' % n['html'])
                                print('          why : %s' % n['summary'])
                    if args.strict:
                        for v in data['violations']:
                            if v['id'] not in GATE.CORE_RULES_KNOWN:
                                fails.append('%s：未登记规则 %s x%d'
                                             % (path, v['id'], len(v['nodes'])))
                except Exception as exc:
                    fails.append('%s：量不到（%s）' % (path, str(exc)[:90]))
                    print('== %-30s EXC %s' % (path, str(exc)[:90]))
                finally:
                    ctx.close()
            b.close()
    except Exception as exc:
        print('ENV：浏览器不可用（%s）' % str(exc)[:120])
        return 2

    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1)
        print('-> %s' % args.json_out)
    if fails:
        print('RESULT=FAIL')
        for f in fails:
            print('  - %s' % f)
        return 1
    print('RESULT=OK %d 页全部量到（形态断言=%s；门禁口径的判据条数见 --strict）'
          % (len(paths), '开' if args.expect_form else '关'))
    return 0


if __name__ == '__main__':
    sys.exit(main())