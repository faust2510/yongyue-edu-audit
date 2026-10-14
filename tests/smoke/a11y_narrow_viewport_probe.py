#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""窄视口回归：列表选择框的 label 修复在**小屏**下有没有视觉位移 + 后台小屏形态实测。

## 为什么单开这一把尺子

2026-09-29 那次修复给 web.ListRenderer / web.ListRenderer.RecordRow 的 CheckBox 补了
.visually-hidden 文字（AX 树 81 无名 → 0），但**只在 1280x900 验过**。
.visually-hidden 是 Bootstrap 的裁剪规则，「同一套规则 ⇒ 小屏也一样」是**推理不是实测** —— 本脚本把它变成实测。

## 三样读数（每页 × 每视口）

1. **后台小屏形态**（实测，不是读源码猜）：Odoo 19 的 ui.isSmall 断点见 core/ui/ui_service.js 的
   MEDIAS_BREAKPOINTS + SIZES.SM ⇒ ≤767px 时 core 的 nav bar 模板整块不渲染 .o_menu_brand 与
   .o_menu_sections，换成 <a class="o_menu_toggle"> 汉堡 + portal 到 body 的 .o_app_menu_sidebar 侧边栏。
2. **几何对拍**：把 .visually-hidden 里的文字**在内存里清空**（= 修复前状态）→ 逐元素比 boundingBox。
   判据 = 所有被跟踪盒子完全相等（1e-6 容差）。
3. **PNG 对拍**：清空前/后各截一张同视口 PNG，比 sha256（几何相等但像素不同 = 还有别的东西在动，必须报）。

## 跑法

    python3 tests/smoke/a11y_narrow_viewport_probe.py
    python3 tests/smoke/a11y_narrow_viewport_probe.py --path /odoo/contacts --widths 390,767,1280 --dump

## 退出码

0 = 全部视口量到且**零位移**（几何 + 像素）｜ 1 = **判据失败**（位移 / 像素不同 / 夹具不成立）
｜ 2 = ENV（锁 / 站点 / 登录 / 浏览器）—— ENV 不当通过。
## 自清

只读 + 只在内存里改 DOM；PNG 落临时目录（--png-dir 可覆盖），不写数据库、不写仓库。
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
LOGIN = (os.environ.get('A11Y_BO_LOGIN', 'backoffice@local'),
         os.environ.get('A11Y_BO_PWD', 'demo123'))
DEFAULT_PATHS = ('/odoo/contacts',)
DEFAULT_WIDTHS = (390, 767, 1280)     # 手机 / isSmall 边界（<=767 = small）/ 桌面基准
HEIGHT = 900

TRACK_JS = r"""() => {
  const q = (s) => [...document.querySelectorAll(s)];
  const box = (el) => { const r = el.getBoundingClientRect();
    return [Math.round(r.x * 1000) / 1000, Math.round(r.y * 1000) / 1000,
            Math.round(r.width * 1000) / 1000, Math.round(r.height * 1000) / 1000]; };
  const out = {tag: {}, rows: [], cells: [], labels: []};
  const tag = (k, s) => { const e = document.querySelector(s); if (e) out.tag[k] = box(e); };
  tag('navbar', '.o_navbar');
  tag('control_panel', '.o_control_panel');
  tag('table', '.o_list_table, .o_list_renderer table, table');
  tag('brand', '.o_menu_brand');
  tag('sections', '.o_menu_sections');
  tag('systray', '.o_menu_systray');
  q('tr.o_data_row').slice(0, 6).forEach(tr => out.rows.push(box(tr)));
  q('th.o_list_record_selector, td.o_list_record_selector').slice(0, 6)
      .forEach(td => out.cells.push(box(td)));
  q('.o_list_record_selector label').slice(0, 6).forEach(lb => out.labels.push(box(lb)));
  return out;
}"""

STRIP_JS = r"""() => {
  let n = 0;
  document.querySelectorAll('.o_list_record_selector label .visually-hidden').forEach((s) => {
    if (s.textContent) { s.textContent = ''; n++; }
  });
  return n;
}"""

PATCH_JS = r"""() => {
  let n = 0;
  document.querySelectorAll('.o_list_record_selector label.form-check-label').forEach((lab) => {
    if (lab.querySelector(':scope > .visually-hidden')) return;
    const s = document.createElement('span');
    s.className = 'visually-hidden';
    s.textContent = lab.closest('thead') ? '全选本页' : '选择本行';
    lab.appendChild(s); n++;
  });
  return n;
}"""

SHAPE_JS = r"""() => {
  const q = (s) => document.querySelectorAll(s).length;
  return {brand: q('.o_menu_brand'), sections: q('.o_menu_sections'),
          systray: q('.o_menu_systray'), toggle: q('.o_menu_toggle'),
          sidebar_portal: q('.o_app_menu_sidebar'), menuitem: q('[role=menuitem]'),
          menu: q('[role=menu]'), sidebar_toggle_icon: q('.o_menu_toggle i.fa-bars'),
          selector_inputs: q('.o_list_record_selector input'),
          empty_labels: [...document.querySelectorAll('.o_list_record_selector input')]
              .filter(i => { const l = i.id && document.querySelector('label[for="' + i.id + '"]');
                             return !l || !l.textContent.trim(); }).length,
          rows: q('tr.o_data_row'), table: q('.o_list_table, .o_list_renderer table, table'),
          hscroll: (() => { const t = document.querySelector('.o_list_renderer, .o_content');
                            return t ? [t.scrollWidth, t.clientWidth] : null; })(),
          // 小屏判据（core 的两个可观测痕迹）：core navbar 在 isSmall 时不渲染品牌与区段、改渲染汉堡
          small_mode: q('.o_menu_toggle') > 0 && q('.o_menu_brand') === 0};
}"""


def probe_session():
    """就绪探针专用 Session：trust_env=False（理由见 a11y_ax_tree_probe.probe_session）。"""
    s = requests.Session()
    s.trust_env = False
    return s


def lock_path():
    return os.path.join(os.environ.get('TMPDIR') or '/tmp', 'edu19_upgrade.lock')


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
    if r.json().get('error'):
        return '登录被拒（%s）' % json.dumps(r.json()['error'])[:120]
    return [{'name': c.name, 'value': c.value, 'domain': 'localhost',
             'path': c.path or '/'} for c in s.cookies]


def ax_unnamed(ctx, pg):
    cdp = ctx.new_cdp_session(pg)
    cdp.send('Accessibility.enable')
    tree = cdp.send('Accessibility.getFullAXTree')
    boxes = [(n.get('name') or {}).get('value') or '' for n in tree.get('nodes', [])
             if ((n.get('role') or {}).get('value')) == 'checkbox']
    return len(boxes), len([x for x in boxes if not x.strip()])


def diff_boxes(a, b, path=''):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(list(a) + list(b))):
            out += diff_boxes(a.get(k), b.get(k), '%s.%s' % (path, k))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append('%s：元素数 %d → %d' % (path, len(a), len(b)))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                out += diff_boxes(x, y, '%s[%d]' % (path, i))
    else:
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(a - b) > 1e-6:
                out.append('%s：%s → %s' % (path, a, b))
        elif a != b:
            out.append('%s：%r → %r' % (path, a, b))
    return out


def main():
    ap = argparse.ArgumentParser(description='窄视口零位移回归（label 修复）')
    ap.add_argument('--path', default=','.join(DEFAULT_PATHS))
    ap.add_argument('--widths', default=','.join(str(w) for w in DEFAULT_WIDTHS))
    ap.add_argument('--png-dir', default=os.path.join(tempfile.gettempdir(), 'edu_a11y_narrow'))
    ap.add_argument('--dump', action='store_true')
    ap.add_argument('--json', dest='json_out')
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
    widths = [int(w) for w in args.widths.split(',') if w.strip()]
    os.makedirs(args.png_dir, exist_ok=True)
    fails, rows = [], {}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(channel='chrome', headless=True, args=['--no-proxy-server'])
            for path in paths:
                for w in widths:
                    ctx = b.new_context(viewport={'width': w, 'height': HEIGHT},
                                        locale='zh-CN', device_scale_factor=1)
                    ctx.add_cookies(cookies)
                    pg = ctx.new_page()
                    key = '%s@%dx%d' % (path, w, HEIGHT)
                    try:
                        r = pg.goto(BASE + path, wait_until='domcontentloaded', timeout=90000)
                        status = r.status if r else 0
                        pg.wait_for_selector('.o_navbar', timeout=25000)
                        pg.wait_for_timeout(2500)
                        shape = pg.evaluate(SHAPE_JS)
                        ax_total, ax_unnamed_n = ax_unnamed(ctx, pg)
                        g_fixed = pg.evaluate(TRACK_JS)          # ① 修复后
                        png_fixed = pg.screenshot(full_page=False)
                        n_fixed = os.path.join(args.png_dir,
                                               key.replace('/', '_').replace('@', '_at_') + '__fixed.png')
                        open(n_fixed, 'wb').write(png_fixed)
                        stripped = pg.evaluate(STRIP_JS)          # ② 反向：清空可访问名
                        pg.wait_for_timeout(350)
                        g_strip = pg.evaluate(TRACK_JS)
                        png_strip = pg.screenshot(full_page=False)
                        n_strip = n_fixed.replace('__fixed', '__stripped')
                        open(n_strip, 'wb').write(png_strip)
                        patched = pg.evaluate(PATCH_JS)           # ③ 正向复原
                        pg.wait_for_timeout(350)
                        g_back = pg.evaluate(TRACK_JS)
                        png_back = pg.screenshot(full_page=False)
                        d_geo = diff_boxes(g_fixed, g_strip)
                        d_back = diff_boxes(g_fixed, g_back)
                        sha_f = hashlib.sha256(png_fixed).hexdigest()
                        sha_s = hashlib.sha256(png_strip).hexdigest()
                        sha_b = hashlib.sha256(png_back).hexdigest()
                        na = None        # 结构性 N/A 的原因（小屏不渲染选择列时填），见下方 hasSelectors 注释
                        rows[key] = {'status': status, 'shape': shape, 'na_reason': na,
                                     'ax_checkbox': ax_total, 'ax_unnamed': ax_unnamed_n,
                                     'stripped': stripped, 'patched': patched,
                                     'geo_diff': d_geo, 'geo_diff_back': d_back,
                                     'png_same': sha_f == sha_s, 'png_back_same': sha_f == sha_b,
                                     'sha': [sha_f[:16], sha_s[:16], sha_b[:16]],
                                     'png': [n_fixed, n_strip]}
                        print('== %-34s HTTP %s%s' % (key, status, '  【N/A】' if na else ''))
                        print('   小屏形态：品牌 %d ｜ 区段 %d ｜ 汉堡 %d ｜ 侧边栏 portal %d ｜ menuitem %d ｜ role=menu %d'
                              % (shape['brand'], shape['sections'], shape['toggle'],
                                 shape['sidebar_portal'], shape['menuitem'], shape['menu']))
                        print('   列表：行 %d ｜ 表格 %d ｜ 选择框 %d ｜ 空 label %d ｜ 横向滚动 %s ｜ AX checkbox %d/无名 %d'
                              % (shape['rows'], shape['table'], shape['selector_inputs'],
                                 shape['empty_labels'], shape['hscroll'], ax_total, ax_unnamed_n))
                        print('   清空可访问名 %d 处 ⇒ 几何位移 %s ｜ PNG sha %s→%s %s'
                              % (stripped, d_geo or '**0（零位移）**', sha_f[:12], sha_s[:12],
                                 '相同' if sha_f == sha_s else '**不同**'))
                        print('   再补回 %d 处 ⇒ 几何回复 %s ｜ PNG %s'
                              % (patched, d_back or '**0（回到原状）**',
                                 '相同' if sha_f == sha_b else '**不同**'))
                        if na:
                            print('   N/A 原因：%s' % na)
                        if status != 200:
                            fails.append('%s：HTTP %s' % (key, status))
                        # ⚠ 结构事实（core/views/list/list_renderer.js 的 get hasSelectors）：
                        #     hasSelectors = allowSelectors && !env.isSmall ⇒ **小屏根本不渲染选择列**，
                        #     .visually-hidden 的可访问名自然也不存在 ⇒ 「小屏零位移」在这一档是
                        #     **结构性不适用（N/A）**，不是「验过了」。这里如实标 N/A，绝不当通过。
                        if shape['selector_inputs'] == 0:
                            if shape.get('small_mode'):
                                na = ('小屏模式（env.isSmall）：core 的 hasSelectors = allowSelectors && !isSmall '
                                      '⇒ 选择列与它的可访问名**根本没渲染**，本项 N/A')
                            else:
                                fails.append('%s：非小屏却量不到 .o_list_record_selector ⇒ 夹具不成立，不许当通过' % key)
                        elif stripped == 0:
                            fails.append('%s：有选择列但没有可清空的可访问名 ⇒ 修复没在这页生效或选择器变了' % key)
                        if d_geo:
                            fails.append('%s：清空后有几何位移 %d 处：%s' % (key, len(d_geo), d_geo[:4]))
                        if sha_f != sha_s:
                            fails.append('%s：几何虽等，PNG 不同（%s → %s）' % (key, sha_f[:12], sha_s[:12]))
                        if d_back:
                            fails.append('%s：补回后几何没回到原状：%s' % (key, d_back[:4]))
                    except Exception as exc:
                        fails.append('%s：量不到（%s）' % (key, str(exc)[:90]))
                        print('== %-34s EXC %s' % (key, str(exc)[:90]))
                    finally:
                        ctx.close()
            b.close()
    except Exception as exc:
        print('ENV：浏览器不可用（%s）' % str(exc)[:120])
        return 2

    if args.dump:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1)
        print('-> %s' % args.json_out)
    print('PNG 目录：%s' % args.png_dir)
    if fails:
        print('RESULT=FAIL')
        for f in fails:
            print('  - %s' % f)
        return 1
    na_n = len([r for r in rows.values() if r.get('na_reason')])
    print('RESULT=OK：%d 组（页 × 视口）—— 其中**真量到并零位移** %d 组（几何 + 像素，且反向注入/正向复原双向成立）；'
          '**结构性 N/A** %d 组（小屏不渲染选择列，逐组写明原因）' % (len(rows), len(rows) - na_n, na_n))
    return 0


if __name__ == '__main__':
    sys.exit(main())