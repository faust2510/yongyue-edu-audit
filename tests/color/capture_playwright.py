#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/color/capture_playwright.py —— 取色量具的 Playwright 替代驱动。

为什么要它（ENV 不是结论）
    color_audit.py 的 capture 子命令走 ~/.local/bin/tabbit-cli 驱动真实浏览器（Tabbit）。
    2026-09-28 本机实测该 CLI 直接返回：
        {"error":{"name":"Error","message":"Cannot connect to Browser Runtime Service",
                  "code":"BROWSER_RUNTIME_UNAVAILABLE"},"ok":false}
    ⇒ 官方驱动路径是 ENV（exit 2），门禁在当晚跑不起来。为了不让「跑不起来」
    变成「看起来没问题」，这里补一个驱动；测量代码逐字取自 tests/color/capture_page.js
    （运行时从该文件里切片，不复制、不改写），保证口径与冻结量具同源。

诚实边界（不要当成跨驱动等价证明）
    · 测量代码同一份 ⇒ 口径同一份；产物的四属性/锚点/焦点结构逐字段相同；
    · 但驱动不同（Tabbit 的浏览器实例 vs Playwright Chromium）⇒「跨驱动逐色读数相等」
      这件事本轮没有测（tabbit 不可用，无从对照）。
    · 因此本驱动的产物不得与 tabbit 抓的 baseline-local.json 做逐色相减/色数对比；
      它只用于绝对判据（禁用色命中、监控对、令牌值、锚点恒等、焦点环）。
    · 产物 doc 里写 driver=playwright + driver_note，防后人误当同一支驱动。

用法
    python3 tests/color/capture_playwright.py --base-url http://127.0.0.1:8069 \
        --out /tmp/color-raw-pw.json --set frozen6
退出码：0=成功 ｜ 1=量具自身失败（切片失败/结果为空） ｜ 2=ENV（站点不可达/登录失败/缺页）
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURE_JS = os.path.join(HERE, 'capture_page.js')

# 从冻结的取色程序里切出「测量函数本体」的两个锚点。切片失败必须硬失败 ——
# 切不到就说明量具被改过形状，此时静默降级成「抓了个空读数」比报错危险得多。
MARK_BEGIN = 'await tab.evaluate((names) => {'
MARK_END = '}, TOKEN_NAMES);'


def load_measurement():
    """返回 (fn_body, token_names)。fn_body 是 (names) => {...} 的函数体。"""
    with open(CAPTURE_JS, encoding='utf-8') as fh:
        js = fh.read()
    i = js.find(MARK_BEGIN)
    j = js.find(MARK_END)
    if i < 0 or j < 0 or j <= i:
        raise SystemExit('FAIL: 无法从 %s 切出测量函数（锚点缺失或顺序变了）' % CAPTURE_JS)
    body = js[i + len(MARK_BEGIN):j]
    if len(body) < 500:
        raise SystemExit('FAIL: 切出的测量函数只有 %d 字节，明显不是本体' % len(body))
    m = re.search(r'const TOKEN_NAMES = \[(.*?)\];', js, re.S)
    if not m:
        raise SystemExit('FAIL: 取不到 TOKEN_NAMES')
    names = re.findall(r'"([^"]+)"', m.group(1))
    if len(names) < 10:
        raise SystemExit('FAIL: TOKEN_NAMES 只解析到 %d 项' % len(names))
    return body, names


def settle(page, rounds=40, step_ms=600, stable_need=5):
    """与冻结程序同口径：元素数连续 5 次采样不变才取（固定 sleep 会取到偏小读数）。"""
    last_n, stable = -1, 0
    for _ in range(rounds):
        n = page.evaluate('() => document.querySelectorAll("body *").length')
        if n == last_n:
            stable += 1
            if stable >= stable_need:
                break
        else:
            stable, last_n = 0, n
        page.wait_for_timeout(step_ms)
    page.wait_for_timeout(800)


def capture_one(ctx, base, key, path, body, names, timeout_ms=120000):
    page = ctx.new_page()
    try:
        page.goto(base + path, wait_until='domcontentloaded', timeout=timeout_ms)
        try:
            page.wait_for_load_state('networkidle', timeout=5000)
        except Exception:
            pass
        try:
            page.wait_for_selector('.o_web_client, .o_action_manager, main, #wrap', timeout=8000)
        except Exception:
            pass
        settle(page)
        data = page.evaluate('(names) => {' + body + '}', names)
        data['key'] = key
        data['base_url'] = base
        return data
    finally:
        page.close()


def main():
    ap = argparse.ArgumentParser(description='取色量具的 Playwright 替代驱动')
    ap.add_argument('--base-url', default='http://127.0.0.1:8069')
    ap.add_argument('--out', required=True)
    ap.add_argument('--set', choices=['frozen6', 'legacy4'], default='frozen6')
    ap.add_argument('--db', default='edu19')
    ap.add_argument('--login-user', default='faculty@local')
    ap.add_argument('--login-pass', default='demo123')
    args = ap.parse_args()

    body, names = load_measurement()
    print('measurement: 从 %s 切片成功（%d 字节 / %d 个令牌）'
          % (os.path.basename(CAPTURE_JS), len(body), len(names)))

    with open(os.path.join(HERE, 'pages.json'), encoding='utf-8') as fh:
        pages = json.load(fh)
    want = pages['sets'][args.set]
    specs = [p for p in pages['pages'] if p['key'] in want]
    base = args.base_url.rstrip('/')

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print('ENV: playwright 不可用（%s）' % str(e)[:120], file=sys.stderr)
        return 2

    entries = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        try:
            public = [s for s in specs if not s['auth']]
            private = [s for s in specs if s['auth']]
            if public:
                ctx = br.new_context(viewport={'width': 1440, 'height': 900})
                # 游客态自证：/my/home 必须被挡（否则「公开页」读数名不副实）
                probe = ctx.request.get(base + '/my/home', max_redirects=0)
                if probe.status not in (301, 302, 303, 401, 403):
                    print('ENV: 游客态不成立（/my/home -> %s）' % probe.status, file=sys.stderr)
                    return 2
                print('  guest  /my/home -> %s（确认未登录）' % probe.status)
                for s in public:
                    e = capture_one(ctx, base, s['key'], s['path'], body, names)
                    print('  guest  %-9s %-34s scanned=%-5s visible=%-5s'
                          % (s['key'], e['url'], e.get('scanned'), e.get('visible')))
                    entries.append(e)
                ctx.close()

            if private:
                ctx = br.new_context(viewport={'width': 1440, 'height': 900})
                res = ctx.request.post(base + '/web/session/authenticate',
                                       data={'jsonrpc': '2.0', 'method': 'call',
                                             'params': {'db': args.db, 'login': args.login_user,
                                                        'password': args.login_pass}})
                if '"uid"' not in res.text():
                    print('ENV: 登录失败（%s）-> %s' % (args.login_user, res.text()[:160]),
                          file=sys.stderr)
                    return 2
                print('  login  %s ok' % args.login_user)
                for s in private:
                    e = capture_one(ctx, base, s['key'], s['path'], body, names)
                    print('  auth   %-9s %-34s scanned=%-5s visible=%-5s'
                          % (s['key'], e['url'], e.get('scanned'), e.get('visible')))
                    entries.append(e)
                ctx.close()
        finally:
            br.close()

    if not entries:
        print('ENV: 一页都没抓到', file=sys.stderr)
        return 2
    for e in entries:
        if '/web/login' in e.get('url', ''):
            print('ENV: 页面 %s 落到登录页（%s）—— 未登录读数无效' % (e['key'], e['url']),
                  file=sys.stderr)
            return 2
    order = {p['key']: i for i, p in enumerate(pages['pages'])}
    entries.sort(key=lambda x: order.get(x['key'], 99))

    doc = {
        'schema': 'color-gauge/v1',
        'driver': 'playwright',
        'driver_note': ('驱动 = Playwright Chromium；测量代码逐字取自 tests/color/capture_page.js。'
                        '官方驱动（tabbit-cli）本轮 ENV: BROWSER_RUNTIME_UNAVAILABLE。'
                        '跨驱动逐色读数未做对照 ⇒ 本产物只用于绝对判据，'
                        '不得与 tabbit 抓的 baseline-local.json 做色数相减。'),
        'captured_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        'base_url': base,
        'page_set': args.set,
        'spec': pages['spec'],
        'entries': entries,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print('归档 -> %s（%d 页，driver=playwright）' % (args.out, len(entries)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
