#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户入口「绕后台闪屏」度量：点一个门户入口，数主框架导航次数 + 首次门户内容时刻。

缺陷（用户实测）：从门户点「资料下载」会先进 /odoo/action-<act_url id>（整屏 Odoo
后台外壳 + 「正在加载」），再由 webclient 的 JS 执行 window.location = url 跳门户，
于是用户看到「先闪一遍后台老界面，再变成门户页」。

度量口径（全部限主框架，iframe 不计）：
  href            点击前该入口 anchor 的 href 原始值
  navs            主框架 framenavigated 的 URL 序列（改前应 2 条：先 /odoo/action-N
                  再目标页；改后应 1 条）
  docs            主框架 document 响应的 URL 序列（与 navs 互为佐证）
  t_backend_ms    点击 -> 首个后台外壳（.o_web_client）出现，页面内计时（Date.now）
  t_portal_ms     点击 -> 首个门户内容（.b11-shell）出现
  backend_seen    是否出现过后台外壳
  nav_count       主框架导航次数

页面内计时探针用 add_init_script 注入，随每次文档导航重装；起点 t0 由 harness 在
点击前写入 sessionStorage（同源跨导航保持）。这样 t_* 不含 Playwright click 自身
的往返延迟。

用法：
  python3 tests/smoke/portal_entry_direct_href.py --tag before
  python3 tests/smoke/portal_entry_direct_href.py --tag after
产出：
  tests/smoke/portal_entry_direct_href_<tag>.json
  tests/smoke/out_portal_entry/<tag>-<case>[-flash|-final].png
退出码：0 = 全部用例判定通过；1 = 有用例未通过；2 = 环境/登录错误。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8069'
DB = 'edu19'
OUT_DIR = Path('tests/smoke/out_portal_entry')

# 登录（与 scripts/shoot_ux_v3.py 同口径：凭据唯一声明点，可用 EDU_* 覆盖；
# 判据是会话 uid，不是 DOM）
USERS = {
    'backoffice': ('BO', 'backoffice@local', 'demo123'),
    'admin': ('ADMIN', 'admin', 'demo123'),
}

# 页面内探针：随每次导航重装。t0 由 harness 在点击前写入 sessionStorage。
PROBE_JS = """
(() => {
  const g = (k) => window.sessionStorage.getItem(k);
  const s = (k, v) => { if (g(k) === null) window.sessionStorage.setItem(k, String(v)); };
  const tick = () => {
    const t0 = parseInt(g('__edu_probe_t0') || '0', 10);
    if (!t0) return;
    if (document.querySelector('.o_web_client')) s('__edu_probe_backend', Date.now() - t0);
    if (document.querySelector('.b11-shell')) {
      s('__edu_probe_portal', Date.now() - t0);
      return;
    }
    window.requestAnimationFrame(tick);
  };
  window.requestAnimationFrame(tick);
})();
"""

SESSION_PROBE = """async () => {
  const r = await fetch('/web/session/get_session_info', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({jsonrpc:'2.0',method:'call',params:{}})});
  const j = await r.json();
  return (j.result || {}).uid || 0;
}"""


# 用例：
#   key         用例名
#   page        入口所在页
#   opener      先点一下（展开下拉）再点入口
#   selectors   依次尝试的点击选择器
#   expect_kind 'portal'  = 入口本身就是门户页（改后必须直达、全程无后台外壳）
#               'backend' = 入口本来就是后台动作（前后都不变：仍进后台）
#   expect_href 期望 href 字面值
#   note        判定依据
CASES = [
    dict(key='apps_downloads', page='/apps', opener=None,
         selectors=['a.o_app:has(.o_app_name:text-is("资料下载"))'],
         expect_kind='portal', expect_href='/downloads',
         note='menu 608 资料下载 root -> ir.actions.act_url 755 url=/downloads'),
    dict(key='topnav_downloads', page='/my/home',
         hover='.o_frontend_to_backend_nav',
         opener='.o_frontend_to_backend_apps_btn',
         selectors=['.o_frontend_to_backend_apps_menu a:text-is("资料下载")'],
         expect_kind='portal', expect_href='/downloads',
         note='core website.layout 浮动「转到您的应用」下拉里的同名入口'),
    dict(key='reg_student_info', page='/apps', opener=None,
         selectors=['a.o_app:has(.o_app_name:text-is("学生信息"))'],
         expect_kind='backend', expect_href='/odoo/action-382',
         note='menu 257 act_window 382（op.student 列表）——本来就是后台'),
    dict(key='reg_timetable', page='/apps', opener=None,
         selectors=['a.o_app:has(.o_app_name:text-is("时间表"))'],
         expect_kind='backend', expect_href='/odoo/action-456',
         note='menu 341 act_window 456（op.session）——本来就是后台'),
    dict(key='reg_finance', page='/apps', opener=None,
         selectors=['a.o_app:has(.o_app_name:text-is("财务管理"))'],
         expect_kind='backend', expect_href='/odoo/action-720',
         note='menu 579 无动作 -> BFS 首个有动作子孙 580 账单管理 act_window 720'),
]


def login(page, user, pwd, tries=3):
    last = ''
    for attempt in range(1, tries + 1):
        try:
            page.goto(BASE + '/web/login?db=' + DB, wait_until='load', timeout=45000)
            page.fill('input[name="login"]', user, timeout=15000)
            page.fill('input[name="password"]', pwd, timeout=15000)
            page.press('input[name="password"]', 'Enter')
            page.wait_for_load_state('load', timeout=30000)
            page.wait_for_timeout(500)
            uid = page.evaluate(SESSION_PROBE)
            if uid:
                return uid, page.url
            last = '登录后会话仍无 uid: %s' % page.url
        except Exception as e:
            last = '%s: %s' % (type(e).__name__, str(e)[:120])
        if attempt < tries:
            page.wait_for_timeout(3000)
    return 0, last


SLOW_FINAL_MS = [0]      # 见 --slow-final-ms


def run_case(page, case, tag):
    """跑一个用例，返回读数 dict。"""
    rec = {'case': case['key'], 'page': case['page'], 'note': case['note'],
           'expect_kind': case['expect_kind'], 'expect_href': case['expect_href']}
    navs, docs = [], []
    on_nav = lambda f: (navs.append(f.url) if f == page.main_frame else None)
    on_resp = lambda r: (docs.append(r.url)
                         if (r.request.resource_type == 'document'
                             and r.frame == page.main_frame) else None)
    page.on('framenavigated', on_nav)
    page.on('response', on_resp)
    try:
        page.goto(BASE + case['page'] + '?db=' + DB, wait_until='load', timeout=45000)
        page.wait_for_timeout(400)

        if case.get('hover'):
            # core 的浮动「转到您的应用」按钮默认缩在视口外（translateX(-250%)），
            # 必须像真人一样先 hover 容器把它滑出来，否则按钮中心点 x<0 点不到。
            page.hover(case['hover'], timeout=8000)
            page.wait_for_timeout(1000)
        if case['opener']:
            opened_via = 'click'
            try:
                page.click(case['opener'], timeout=8000)
            except PWError:
                # 兜底：直接把 bootstrap 下拉展开（只改可见性，不改 href），并如实登记
                page.evaluate(
                    "() => document.querySelector('.o_frontend_to_backend_apps_menu')"
                    ".classList.add('show')")
                opened_via = 'forced-show'
            rec['opener_via'] = opened_via
            page.wait_for_timeout(600)

        el = None
        for sel in case['selectors']:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state='attached', timeout=6000)
                el = loc
                break
            except PWError:
                continue
        if el is None:
            rec['error'] = '入口未找到（选择器都没命中）'
            return rec

        rec['label'] = (el.inner_text() or '').strip()
        rec['href'] = el.get_attribute('href')

        page.evaluate("() => window.sessionStorage.clear()")
        page.evaluate(
            "() => window.sessionStorage.setItem('__edu_probe_t0', String(Date.now()))")
        navs.clear()
        docs.clear()

        if SLOW_FINAL_MS[0]:
            # 只给「可视化取证」那一轮用：把最终页的文档请求人为延后，好让后台外壳
            # 在屏幕上多停一会儿、截得到那一帧。带此参数时计时数字不作数。
            page.route(
                '**' + case['expect_href'],
                lambda route: (time.sleep(SLOW_FINAL_MS[0] / 1000.0),
                               route.continue_()))
        el.click(timeout=15000)
        # 只有真的停在后台外壳上时才落「闪屏」图；否则不落一张误导性的空白图。
        rec['flash_shot'] = None
        try:
            page.wait_for_function(
                "() => window.sessionStorage.getItem('__edu_probe_backend') !== null",
                timeout=2000)
            name = '%s-%s-flash.png' % (tag, case['key'])
            path = OUT_DIR / name
            page.screenshot(path=str(path))
            # 诚实校验：这一帧里必须真的还停在后台外壳上（没被最终页盖掉），
            # 否则删图并如实记 None —— 不留一张名不副实的「闪屏」证据。
            on_shell = page.evaluate(
                "() => !!document.querySelector('.o_web_client')"
                " && !document.querySelector('.b11-shell')")
            if on_shell:
                rec['flash_shot'] = name
            else:
                path.unlink(missing_ok=True)
        except PWError:
            pass

        seen_portal = True
        try:
            page.wait_for_function(
                "() => window.sessionStorage.getItem('__edu_probe_portal') !== null",
                timeout=30000)
        except PWError:
            seen_portal = False
        try:
            page.wait_for_load_state('load', timeout=15000)
        except PWError:
            pass
        page.wait_for_timeout(300)

        probe = page.evaluate("""() => {
            const g = (k) => window.sessionStorage.getItem(k);
            return {backend: g('__edu_probe_backend'), portal: g('__edu_probe_portal')};
        }""")
        rec['probe'] = probe
        rec['t_backend_ms'] = int(probe['backend']) if probe.get('backend') else None
        rec['t_portal_ms'] = int(probe['portal']) if probe.get('portal') else None
        rec['backend_seen'] = probe.get('backend') is not None
        rec['portal_ok'] = seen_portal
        rec['navs'] = [u for u in navs if u and u != 'about:blank']
        rec['nav_count'] = len(rec['navs'])
        rec['docs'] = [u for u in docs if u]
        rec['final_url'] = page.url
        try:
            page.screenshot(
                path=str(OUT_DIR / ('%s-%s-final.png' % (tag, case['key']))))
        except PWError as e:
            rec['final_shot_error'] = str(e)[:120]
    except PWError as e:
        rec['error'] = '%s: %s' % (type(e).__name__, str(e)[:200])
    finally:
        page.remove_listener('framenavigated', on_nav)
        page.remove_listener('response', on_resp)
        if SLOW_FINAL_MS[0]:
            try:
                page.unroute('**' + case['expect_href'])
            except PWError:
                pass
    return rec


def verdict(rec):
    """portal 用例必须直达且全程无后台外壳；backend 用例必须与改前一致。"""
    if rec.get('error'):
        return False, rec['error']
    if rec['expect_kind'] == 'portal':
        problems = []
        if rec['href'] != rec['expect_href']:
            problems.append('href=%s != %s' % (rec['href'], rec['expect_href']))
        if rec['backend_seen']:
            problems.append('仍出现后台外壳 t=%sms' % rec['t_backend_ms'])
        if rec['nav_count'] != 1:
            problems.append('主框架导航 %s 次（应 1 次）: %s'
                            % (rec['nav_count'], ' -> '.join(rec['navs'])))
        if not rec['portal_ok']:
            problems.append('30s 内未出现门户内容')
        return (not problems), ('; '.join(problems) or '直达门户，1 次导航，无后台外壳')
    problems = []
    if rec['href'] != rec['expect_href']:
        problems.append('href=%s != %s（非 act_url 入口的行为不该变）'
                        % (rec['href'], rec['expect_href']))
    if not any('/odoo/action-' in u for u in rec['navs']):
        problems.append('未进后台深链: %s' % ' -> '.join(rec['navs']))
    if not rec['backend_seen']:
        problems.append('未出现后台外壳（回归口径是「仍进后台」）')
    return (not problems), ('; '.join(problems) or '仍进后台 /odoo/action-N，行为未变')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True, help='before / after（写进输出文件名）')
    ap.add_argument('--role', default='backoffice', choices=sorted(USERS))
    ap.add_argument('--only', default=None, help='只跑 key 含该子串的用例')
    ap.add_argument('--slow-final-ms', type=int, default=0,
                    help='仅可视化取证：把最终页文档请求延后 N ms，便于截到「闪」'
                         '的那一帧；带此参数时计时数字不作数')
    args = ap.parse_args()
    SLOW_FINAL_MS[0] = args.slow_final_ms

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key_env, user, pwd = USERS[args.role]
    user = os.environ.get('EDU_%s_LOGIN' % key_env, user)
    pwd = os.environ.get('EDU_%s_PASSWORD' % key_env, pwd)

    cases = [c for c in CASES if not args.only or args.only in c['key']]
    results, all_ok = [], True
    t_start = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(locale='zh-CN',
                                  viewport={'width': 1280, 'height': 900})
        page = ctx.new_page()
        page.add_init_script(PROBE_JS)
        uid, info = login(page, user, pwd)
        if not uid:
            print('登录失败（%s）：%s' % (args.role, info))
            browser.close()
            return 2
        print('登录 OK role=%s uid=%s' % (args.role, uid))
        for case in cases:
            rec = run_case(page, case, args.tag)
            ok, why = verdict(rec)
            rec['pass'], rec['verdict'] = ok, why
            all_ok = all_ok and ok
            results.append(rec)
            print('[%s] %-18s href=%-22s navs=%s backend_seen=%-5s '
                  't_backend=%-6s t_portal=%-6s :: %s'
                  % ('PASS' if ok else 'FAIL', rec['case'], rec.get('href'),
                     rec.get('nav_count'), rec.get('backend_seen'),
                     rec.get('t_backend_ms'), rec.get('t_portal_ms'), why))
        ctx.close()
        browser.close()

    out = {'tag': args.tag, 'role': args.role, 'db': DB, 'base': BASE,
           'collected_at': time.strftime('%Y-%m-%d %H:%M:%S'),
           'elapsed_s': round(time.time() - t_start, 1), 'results': results}
    path = Path('tests/smoke/portal_entry_direct_href_%s.json' % args.tag)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('落盘 %s  全绿=%s' % (path, all_ok))
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
