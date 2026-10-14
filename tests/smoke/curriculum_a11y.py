#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""/registrar/curriculum 批量控件：可访问名 + 键盘可达 + axe 读数（2026-09-29）。

为什么单独一把尺子：本仓三张 UI 门禁的路由名单来自 tests/ui/surface.json，
而「/registrar/curriculum」在表里是 gates=[] / status=gap（**没有任何门禁扫它**）
⇒ 本次新增控件落在门禁覆盖之外。于是按 code-map §6 第 10 条的口径自量：

  ① **浏览器 AX 树**（CDP Accessibility.getFullAXTree）——判定「有没有可访问名」
     的权威尺子（与 tests/smoke/a11y_ax_tree_probe.py 同一把）；
  ② **真键盘事件**：Tab / Space / Enter 走一遍「全选 → 批量清空」，证明键盘可达
     且能真的提交（批量清空是幂等动作：14 行本来就是「留空」，落库 box=bulk_none）；
  ③ axe-core（4.10.2）读数：**改后**（现状）与**改前反事实**（在真实渲染 DOM 上
     移除本次新增的控件 = 改动前的控件集合）各扫一次。

用法（必须用带 playwright 的解释器）：
    /opt/homebrew/bin/python3 tests/smoke/curriculum_a11y.py
    /opt/homebrew/bin/python3 tests/smoke/curriculum_a11y.py --json 结果文件

退出码：0 = 全绿；1 = 有断言失败；2 = ENV（站点不可达 / 浏览器起不来）。
"""
import argparse
import datetime
import json
import os
import sys
import tempfile

import requests

BASE = 'http://127.0.0.1:8069'
DB = 'edu19'
LOGIN = ('backoffice@local', 'demo123')
PATH = '/registrar/curriculum?course_id=18'
AXE_VERSION = '4.10.2'
AXE_URL = 'https://cdn.jsdelivr.net/npm/axe-core@%s/axe.min.js' % AXE_VERSION

ok = fail = 0
RESULTS = []


def check(name, cond, detail=''):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    RESULTS.append({'name': name, 'pass': bool(cond), 'detail': detail})
    print('%s | %s | %s' % ('PASS' if cond else 'FAIL', name, detail))


def preflight():
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.get(BASE + '/web/login?db=' + DB, timeout=15, allow_redirects=False)
    except Exception as exc:                                  # noqa: BLE001
        return '站点不可达：%s' % exc
    if r.status_code not in (200, 302, 303):
        return '站点未就绪（/web/login → %s）' % r.status_code
    r = s.post(BASE + '/web/session/authenticate', timeout=25, json={
        'jsonrpc': '2.0', 'params': {'db': DB, 'login': LOGIN[0],
                                     'password': LOGIN[1]}})
    if not r.json().get('result', {}).get('uid'):
        return '登录失败（%s）' % LOGIN[0]
    # ⚠ cookie 的 domain 必须与 BASE 的主机**逐字一致**：写成固定的 'localhost'
    #   而 BASE 是 127.0.0.1 时，浏览器根本不会带上这个 cookie ⇒ 页面停在登录页，
    #   于是 AX 树量到的是登录表单（首版实测：checkbox 0 个、焦点落在 password）。
    host = BASE.split('//', 1)[-1].split('/', 1)[0].split(':')[0]
    return [{'name': c.name, 'value': c.value, 'domain': host,
             'path': c.path or '/'} for c in s.cookies]


def axe_source():
    d = os.path.join(tempfile.gettempdir(), 'edu_axe')
    p = os.path.join(d, 'axe-%s.min.js' % AXE_VERSION)
    if os.path.exists(p):
        return open(p, encoding='utf-8').read()
    try:
        os.makedirs(d, exist_ok=True)
        r = requests.get(AXE_URL, timeout=30)
        r.raise_for_status()
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(r.text)
        return r.text
    except Exception as exc:                                  # noqa: BLE001
        print('ENV：axe 取不到（%s）⇒ axe 读数缺失（AX 树与键盘两把尺子不受影响）' % exc)
        return ''


def ax_nodes(ctx, pg):
    cdp = ctx.new_cdp_session(pg)
    cdp.send('Accessibility.enable')
    tree = cdp.send('Accessibility.getFullAXTree')
    out = []
    for n in tree.get('nodes', []):
        role = (n.get('role') or {}).get('value') or ''
        name = (n.get('name') or {}).get('value') or ''
        out.append((role, name))
    return out


def run_axe(pg, src):
    pg.add_script_tag(content=src)
    return pg.evaluate("() => axe.run(document, {resultTypes:['violations']})"
                       ".then(r => r.violations.map(v => ({id: v.id, impact: v.impact,"
                       " nodes: v.nodes.length})))")


def main():
    cookies = preflight()
    if isinstance(cookies, str):
        print('ENV：%s ⇒ 本轮作废' % cookies)
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:                                  # noqa: BLE001
        print('ENV：playwright 不可用：%s' % exc)
        return 2
    src = axe_source()
    rows = {}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(channel='chrome', headless=True,
                                   args=['--no-proxy-server'])
            ctx = b.new_context(viewport={'width': 1400, 'height': 1000},
                                locale='zh-CN')
            ctx.add_cookies(cookies)
            pg = ctx.new_page()
            pg.goto(BASE + PATH, wait_until='domcontentloaded', timeout=90000)

            # ---- ① AX 树：每个新增控件都要有可访问名 ----
            nodes = ax_nodes(ctx, pg)
            cbs = [n for r, n in nodes if r == 'checkbox']
            combos = [n for r, n in nodes if r == 'combobox']
            buttons = [n for r, n in nodes if r == 'button']
            unnamed = [n for n in cbs if not n.strip()]
            rows['ax'] = {'checkbox': cbs, 'combobox_n': len(combos),
                          'unnamed': unnamed, 'buttons': buttons}
            print('   AX 树：checkbox %d 个（无名 %d）｜combobox %d ｜button %s'
                  % (len(cbs), len(unnamed), len(combos), buttons))
            check('① AX 树：全部 %d 个复选框都有可访问名（无名 %d）'
                  % (len(cbs), len(unnamed)), not unnamed and len(cbs) >= 14,
                  '样例 %s' % cbs[:3])
            check('① AX 树：表头「全选 / 全不选」有名字',
                  any('全选' in n for n in cbs), '全选框名=%s'
                  % [n for n in cbs if '全选' in n])
            check('① AX 树：三个批量按钮都有可访问名',
                  all(any(k in n for n in buttons) for k in
                      ('批量设为必修', '批量设为选修', '批量清空')),
                  '按钮=%s' % buttons)
            check('① AX 树：逐行下拉（combobox）都在（%d 个）' % len(combos),
                  len(combos) >= 14, '')
            check('① AX 树：每个行复选框的名字都带科目名（勾选科目 …）',
                  sum(1 for n in cbs if n.startswith('勾选科目')) >= 14,
                  '命中 %d' % sum(1 for n in cbs if n.startswith('勾选科目')))

            # ---- ② 键盘可达：Tab → Space 全选 → Tab 到按钮 → Enter 提交 ----
            def focus_id():
                return pg.evaluate(
                    "() => { const e = document.activeElement; return e ? (e.id || "
                    "(e.textContent || '').trim().slice(0, 12)) : ''; }")

            pg.keyboard.press('Tab')
            focused = focus_id()
            hits = 0
            for _ in range(40):
                if focused == 'cur-pick-all':
                    break
                pg.keyboard.press('Tab')
                focused = focus_id()
                hits += 1
            check('② 键盘：Tab 能走到表头「全选 / 全不选」复选框（步数 %d）' % hits,
                  focused == 'cur-pick-all', '焦点=%s' % focused)
            before_checked = pg.evaluate(
                "() => document.querySelectorAll('input[name=pick]:checked').length")
            pg.keyboard.press('Space')
            pg.wait_for_timeout(200)
            after_checked = pg.evaluate(
                "() => document.querySelectorAll('input[name=pick]:checked').length")
            check('② 键盘：Space 触发全选（勾选 %d → %d 行）'
                  % (before_checked, after_checked),
                  after_checked == 14 and before_checked == 0,
                  'checked=%d' % after_checked)

            focused = focus_id()
            found = False
            # 批量动作条在 DOM 里位于表格**之前**，而焦点此刻在表头（表格内）⇒
            # 要绕整页一圈才回到按钮（14 行 × 2 控件 + 页头/侧栏 …）。首版只给
            # 40 次 Tab，没走到就判红 —— 那是量具不够长，不是控件键盘不可达。
            for _ in range(160):
                if focused and '批量清空' in focused:
                    found = True
                    break
                pg.keyboard.press('Tab')
                focused = focus_id()
            check('② 键盘：Tab 能走到「批量清空」按钮（无需鼠标）', found,
                  '焦点=%s' % focused)
            if found:
                pg.keyboard.press('Enter')
                pg.wait_for_load_state('domcontentloaded')
                pg.wait_for_timeout(500)
                rows['keyboard_url'] = pg.url
                check('② 键盘：Enter 真的提交了批量动作（14 行本来就是「留空」⇒ 零改动）',
                      'box=bulk_none' in pg.url or 'box=bulk_saved' in pg.url,
                      '落地 %s' % pg.url.split('?')[-1][:90])

            # ---- ③ axe 读数：改后 + 改前反事实 ----
            if src:
                after = run_axe(pg, src)
                rows['axe_after'] = after
                pg.evaluate("""() => {
                    document.querySelectorAll('#cur-pick-all').forEach(
                        e => e.closest('th').remove());
                    document.querySelectorAll('input[name=pick]').forEach(
                        e => e.closest('td').remove());
                    const bar = document.querySelector('button[name=bulk_action]');
                    if (bar) bar.closest('.card').remove();
                    const w = document.querySelector('.alert .small.mt-1');
                    if (w) w.remove();
                }""")
                before = run_axe(pg, src)
                rows['axe_before'] = before
                print('   axe 改后：%s' % after)
                print('   axe 改前（反事实，移除新增控件）：%s' % before)
                check('③ axe：改后没有新增违规规则（改前 %d 条 → 改后 %d 条）'
                      % (len(before), len(after)),
                      set(v['id'] for v in after) <= set(v['id'] for v in before),
                      '改后=%s' % [v['id'] for v in after])
            ctx.close()
            b.close()
    except Exception as exc:                                  # noqa: BLE001
        print('ENV：浏览器不可用（%s）' % str(exc)[:160])
        return 2

    print('\n合计：PASS %d / FAIL %d' % (ok, fail))
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump({'at': datetime.datetime.now().isoformat(), 'path': PATH,
                       'axe_version': AXE_VERSION, 'results': RESULTS,
                       'raw': rows, 'pass': ok, 'fail': fail}, fh,
                      ensure_ascii=False, indent=1)
        print('读数已写 %s' % args.json)
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default='')
    args = ap.parse_args()
    sys.exit(main())
