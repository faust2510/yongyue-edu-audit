#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台页「表单控件有没有可访问名」——**用浏览器自己的 AX 树量，不依赖 axe**。

## 为什么需要这把尺子

axe 的读数会**随口径变化**：同一页 /odoo/contacts，视口 900px 报 19 条 label 违规、
视口 2700px 报 63 条，命中集合永远是 DOM 顺序的前缀（只判"首屏可见行"）。
而真实缺陷面是 **81 条**（用浏览器自己的 AX 树数出来：81 个 checkbox、81 个可访问名全空）。
⇒ 判「axe 报得对不对」需要一把**独立量具**，本脚本就是它：
走 CDP（Chrome DevTools Protocol）的 Accessibility.getFullAXTree 取**浏览器算出来的**可访问名。

它回答的是一个具体问题：**后台页上还有多少个 checkbox 没有可访问名**（应为 0）。
edu_brand 对 web.ListRenderer / web.ListRenderer.RecordRow 的 CheckBox 用法补了
.visually-hidden 文字（slot → label → 名字），本脚本就是那次修复的**回归尺子**。

## 跑法

    python3 tests/smoke/a11y_ax_tree_probe.py          # 默认查 /odoo/contacts
    python3 tests/smoke/a11y_ax_tree_probe.py --path /odoo/students,/odoo/contacts --dump

## 退出码

0 = 通过（无名 checkbox 0 个）｜ 1 = **判据失败**（有控件没有可访问名，逐条打印名字与计数）
｜ 2 = ENV（有升级锁 / 站点不可达 / 登录不上 / 浏览器起不来）—— ENV 不当通过。

## 自清

**只读**：只做一次会话认证 + GET 页面，不点任何按钮、不发写请求、不建夹具。
"""
import argparse
import os
import sys

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
LOGIN = ('backoffice@local', 'demo123')
DEFAULT_PATHS = ('/odoo/contacts',)


def lock_path():
    return os.path.join(os.environ.get('TMPDIR') or '/tmp', 'edu19_upgrade.lock')


def probe_session():
    """就绪探针专用 Session：**trust_env=False**。

    ⚠ 为什么必须（2026-09-29 实测）：macOS 的系统代理（scutil --proxy 里 HTTPProxy=127.0.0.1:12450）
    会被 module 级 requests.get 自动采用 ⇒ 探 http://localhost:8069 反而经代理拿到 **502** ⇒
    探针误报「站点未就绪」，把三把尺子整体判成 ENV（ENV 不当通过，于是三条读数一个也拿不到）。
    scripts/check_accessibility.py 的 site_ready() 早已写明这条纪律，这里补齐。
    """
    s = requests.Session()
    s.trust_env = False
    return s


def preflight():
    if os.path.isdir(lock_path()):
        return '有升级在进行（%s 存在）' % lock_path()
    try:
        r = probe_session().get(BASE + '/web/login?db=' + DB, timeout=15, allow_redirects=False)
    except Exception as exc:
        return '站点不可达（%s）：%s' % (BASE, exc)
    if r.status_code not in (200, 302, 303):
        return '站点未就绪（/web/login → %s）' % r.status_code
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.post(BASE + '/web/session/authenticate',
                   json={'jsonrpc': '2.0', 'params': {'db': DB, 'login': LOGIN[0],
                                                      'password': LOGIN[1]}}, timeout=25)
    except Exception as exc:
        return '登录请求失败：%s' % exc
    if r.status_code != 200:
        return '登录失败（HTTP %s）' % r.status_code
    return (s, [{'name': c.name, 'value': c.value, 'domain': 'localhost',
                 'path': c.path or '/'} for c in s.cookies])


def ax_checkboxes(ctx, pg):
    cdp = ctx.new_cdp_session(pg)
    cdp.send('Accessibility.enable')
    tree = cdp.send('Accessibility.getFullAXTree')
    boxes = [(n.get('name') or {}).get('value') or '' for n in tree.get('nodes', [])
             if ((n.get('role') or {}).get('value')) == 'checkbox']
    return boxes


def main():
    ap = argparse.ArgumentParser(description='后台页表单控件可访问名（浏览器 AX 树口径）')
    ap.add_argument('--path', default=','.join(DEFAULT_PATHS), help='逗号分隔的后台路径')
    ap.add_argument('--dump', action='store_true', help='打印全部读数（含命名样例）')
    args = ap.parse_args()

    pre = preflight()
    if isinstance(pre, str):
        print('ENV：%s ⇒ 本轮作废（不是判据失败，也不当通过）' % pre)
        return 2
    _sess, cookies = pre

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
                try:
                    r = pg.goto(BASE + path, wait_until='domcontentloaded', timeout=90000)
                    status = r.status if r else 0
                    pg.wait_for_selector('.o_navbar', timeout=25000)
                    pg.wait_for_timeout(3000)
                    boxes = ax_checkboxes(ctx, pg)
                    dom = pg.evaluate(
                        "() => document.querySelectorAll('.o_list_record_selector input').length")
                    unnamed = [x for x in boxes if not x.strip()]
                    rows[path] = {'status': status, 'ax_checkbox_total': len(boxes),
                                  'ax_unnamed': len(unnamed), 'dom_selector_inputs': dom,
                                  'named_samples': [x for x in boxes if x.strip()][:3]}
                    print('== %s ｜ HTTP %s' % (path, status))
                    print('   AX 树：checkbox %d 个 ｜ **无可访问名 %d 个** ｜ 命名样例 %s ｜ DOM 选择框 %d 个'
                          % (len(boxes), len(unnamed), [x for x in boxes if x.strip()][:3], dom))
                    if status != 200:
                        fails.append('%s：HTTP %s' % (path, status))
                    if unnamed:
                        fails.append('%s：仍有 %d 个 checkbox 没有可访问名'
                                     '（AX 树口径，独立于 axe）' % (path, len(unnamed)))
                except Exception as exc:
                    fails.append('%s：量不到（%s）' % (path, str(exc)[:90]))
                finally:
                    ctx.close()
            b.close()
    except Exception as exc:
        print('ENV：浏览器不可用（%s）' % str(exc)[:120])
        return 2

    if args.dump:
        import json
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    if fails:
        print('RESULT=FAIL')
        for f in fails:
            print('  - %s' % f)
        return 1
    print('RESULT=OK %d 页：AX 树里没有可访问名的 checkbox = 0' % len(paths))
    return 0


if __name__ == '__main__':
    sys.exit(main())