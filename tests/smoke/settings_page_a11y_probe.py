#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""settings_page_a11y_probe.py —— **设置页自身**的 axe 读数（门禁扫不到那一页）。

为什么单独一个量具
  scripts/check_accessibility.py 的取样表**故意没有 /odoo/settings**（原文见其 AUDIT_ROUTES
  注释：本栈该页整页打不开 ⇒ 「设置」形态无可用样本）。t110 把它修好之后，那一页就**可以**被扫了，
  但取样表由另一组维护（tests/ui/surface.json），本任务不改它。于是这里的定位很明确：
    · 本脚本只回答「**修好后的设置页自己**有没有 axe 违规」，不冒充全站门禁；
    · 它把读数落盘，供取样表维护方决定要不要把 /odoo/settings 补进列表。
  这条覆盖缺口的性质：**不是豁免**，只是「本量具不替门禁下结论」。

口径与门禁同源（不另立一套）
  · axe 版本/取用顺序与 check_accessibility.py 一致：先本地缓存 /tmp/edu_axe/axe-<v>.min.js，
    取不到才联网一次；两处都拿不到 ⇒ ENV(exit 2)。
  · 只扫「渲染后的页面」（真浏览器 + 真登录），不扫静态 HTML —— Odoo 是 SPA。

用法：python3 tests/smoke/settings_page_a11y_probe.py --out /tmp/settings_a11y.json
退出码：0=无违规 ｜ 1=有违规（读数仍会落盘）｜ 2=ENV（axe 取不到/站点不可达）
"""
import argparse
import json
import os
import sys
import urllib.request

AXE_VERSION = '4.10.2'
AXE_CACHE = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'edu_axe', 'axe-%s.min.js' % AXE_VERSION)
AXE_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/axe-core/%s/axe.min.js' % AXE_VERSION


def get_axe():
    """与 check_accessibility.py 同口径：缓存优先，否则联网一次并缓存。"""
    if os.path.exists(AXE_CACHE):
        return open(AXE_CACHE, encoding='utf-8').read(), 'cache:%s' % AXE_CACHE
    try:
        with urllib.request.urlopen(AXE_CDN, timeout=30) as r:
            body = r.read().decode('utf-8')
    except Exception as e:                                     # noqa: BLE001
        return None, 'axe 取不到：%s' % str(e)[:120]
    os.makedirs(os.path.dirname(AXE_CACHE), exist_ok=True)
    with open(AXE_CACHE, 'w', encoding='utf-8') as fh:
        fh.write(body)
    return body, 'cdn:%s' % AXE_CDN


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-url', default='http://127.0.0.1:8069')
    ap.add_argument('--db', default='edu19')
    ap.add_argument('--login-user', default='admin')
    ap.add_argument('--login-pass', default='demo123')
    ap.add_argument('--path', default='/odoo/settings')
    ap.add_argument('--out')
    args = ap.parse_args()
    base = args.base_url.rstrip('/')

    axe_js, where = get_axe()
    print('axe 来源：%s' % where)
    if not axe_js:
        return 2

    from playwright.sync_api import sync_playwright
    out = {'path': args.path, 'axe': where}
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={'width': 1440, 'height': 1000})
        r = ctx.request.post(base + '/web/session/authenticate', data=json.dumps(
            {'jsonrpc': '2.0', 'params': {'db': args.db, 'login': args.login_user,
                                          'password': args.login_pass}}),
            headers={'Content-Type': 'application/json'})
        uid = (r.json().get('result') or {}).get('uid')
        if not uid:
            print('ENV: 登录失败', file=sys.stderr)
            return 2
        page = ctx.new_page()
        page.set_default_timeout(60000)
        page.goto(base + args.path, wait_until='domcontentloaded')
        page.wait_for_selector('.o_field_widget[name="edu_apply_deadline"] button', timeout=60000)
        page.wait_for_timeout(2500)
        page.add_script_tag(content=axe_js)
        res = page.evaluate('''async () => {
            const r = await axe.run(document, {resultTypes: ['violations']});
            return r.violations.map(v => ({id: v.id, impact: v.impact, help: v.help,
                                           nodes: v.nodes.length,
                                           sample: (v.nodes[0] && v.nodes[0].target) || []}));
        }''')
        out['violations'] = res
        out['total'] = sum(v['nodes'] for v in res)
        out['uid'] = uid
        out['url'] = page.url
        ctx.close()
        br.close()
    ok = out['total'] == 0
    out['verdict'] = 'PASS' if ok else 'FAIL'
    print('%s 设置页 axe：违规 %d 条 %s'
          % (out['verdict'], out['total'], json.dumps(res, ensure_ascii=False)[:400]))
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
        print('OUT=%s' % args.out)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
