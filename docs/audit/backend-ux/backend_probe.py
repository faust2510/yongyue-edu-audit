#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台（Odoo 管理界面）文案与可达性探针 —— 后台是 check_english.py 的结构性盲区，
本脚本补上那把尺子，且**复用 check_english.py 自己的分类器**（同一套白名单/判据），
不另造一套词表。

为什么必须另起一把尺子（根因，可复算）：
  scripts/check_english.py 扫的是 HTTP 响应体里的文本节点/可见属性；而后台
  /odoo/<action> 的响应体是一个 6.9KB 的 **JS 外壳**（实测 http://127.0.0.1:8069/odoo/students），
  全部可见文本都在 <script> 里，而 scan_body() 显式剔除 <script>（SCRIPT_RE）。
  ⇒ 把 /odoo 登记进 surface.json 的 english 门禁只会得到一个**永久假绿**。
  后台真正的文案面在两处，本脚本两处都量：
    A. menu 源：/web/webclient/load_menus 的 menu name（登录态、按角色）—— 服务端真值；
    B. dom  源：真浏览器渲染后的 innerText（Playwright）—— 用户真正看到的东西。

用法：
    python3 docs/audit/backend-ux/backend_probe.py --menus --json out.json
    python3 docs/audit/backend-ux/backend_probe.py --pages --role admin --depth 1 --shots shots/
    python3 docs/audit/backend-ux/backend_probe.py --selftest        # 离线自证：分类器与判据
    python3 docs/audit/backend-ux/backend_probe.py --inject "Fake English Button"   # 反向注入
退出码：0 = must-fix 为 0；2 = 有 must-fix；1 = 运行错误；3 = INCOMPLETE（分类器读不到）。
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import sys

BASE = 'http://127.0.0.1:8069'
DB = 'edu19'
ROLES = {
    'admin':      ('admin', 'demo123', '系统管理员'),
    'backoffice': ('backoffice@local', 'demo123', '教务'),
    'faculty':    ('faculty@local', 'demo123', '教师'),
}
RUN_STAMP = datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def _here():
    return os.path.dirname(os.path.abspath(__file__))


def _repo_root():
    d = _here()
    while True:
        if os.path.isfile(os.path.join(d, 'scripts', 'check_english.py')):
            return d
        up = os.path.dirname(d)
        if up == d:
            raise RuntimeError('找不到仓库根（scripts/check_english.py）')
        d = up


def load_classifier():
    """复用 scripts/check_english.py 的 classify/WHITELIST/DATA_NAMES（同一套判据）。"""
    path = os.path.join(_repo_root(), 'scripts', 'check_english.py')
    spec = importlib.util.spec_from_file_location('check_english_ruler', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CE = load_classifier()


def self_attest():
    with open(os.path.abspath(__file__), 'rb') as fh:
        fp = hashlib.md5(fh.read()).hexdigest()[:8]
    return 'backend_probe fp=%s · check_english REVISION=%s 指纹=%s · 运行时刻 %s' % (
        fp, CE.REVISION, CE._self_fingerprint(), RUN_STAMP)


def login(login_name, password):
    import requests
    s = requests.Session()
    s.trust_env = False          # 绕过系统代理（本机 127.0.0.1:12450）
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': DB, 'login': login_name, 'password': password}}, timeout=30)
    res = r.json().get('result') or {}
    return s, res.get('uid')


def load_menus(sess):
    raw = sess.get(BASE + '/web/webclient/load_menus', timeout=40).text
    data = json.loads(raw)
    return data if 'root' in data else data.get('result', data)


def menu_tree(data):
    """返回 [(depth, id, name, xmlid, actionID, actionPath)]，根序保序。"""
    out = []

    def walk(node, depth):
        for cid in (node.get('children') or []):
            n = data.get(str(cid))
            if not n:
                continue
            out.append((depth, n.get('id'), n.get('name') or '', n.get('xmlid') or '',
                        n.get('actionID'), n.get('actionPath')))
            walk(n, depth + 1)
    walk(data.get('root', {}), 0)
    return out


def classify_value(raw, source, role, xmlid='', kind='text'):
    got = CE.classify(raw, None, None, kind=kind)
    if not got:
        return None
    value, bucket = got
    return dict(value=value, bucket=bucket, source=source, role=role,
                xmlid=xmlid, kind=kind)


def scan_menus(rows, role):
    """menu 源：纯英文菜单名（含 CJK 的由 classify 自己跳过/归 brand）。"""
    hits = []
    for depth, mid, name, xmlid, _a, _p in rows:
        got = classify_value(name, 'menu', role, xmlid=xmlid)
        if got:
            got['depth'] = depth
            got['menu_id'] = mid
            hits.append(got)
    return hits


# ------------------------------------------------------------------ DOM 面
DOM_PROBE = """
() => {
  const pick = (sel) => {
    const e = document.querySelector(sel);
    return e ? e.innerText : '';
  };
  return {
    title: document.title,
    navbar: pick('.o_main_navbar'),
    content: pick('.o_content'),
    body: pick('body'),
    has_form: !!document.querySelector('.o_form_view'),
    has_list: !!document.querySelector('.o_list_renderer'),
    has_kanban: !!document.querySelector('.o_kanban_renderer'),
    rows: document.querySelectorAll('.o_data_row').length,
    breadcrumb: pick('.o_breadcrumb'),
  };
}
"""


def scan_dom(payload, role, path):
    """dom 源：把渲染后的可见文本按行分类（用户真正看到的）。"""
    hits = []
    for region in ('navbar', 'breadcrumb', 'content', 'body'):
        text = payload.get(region) or ''
        if region == 'body' and payload.get('content'):
            continue                       # body 是 content 的超集，避免重复计数
        for line in text.split('\n'):
            line = line.strip()
            if not line or len(line) > 90:
                continue
            got = classify_value(line, 'dom:' + region, role)
            if got:
                got['path'] = path
                hits.append(got)
    got = classify_value(payload.get('title') or '', 'dom:title', role, kind='attr')
    if got:
        got['path'] = path
        hits.append(got)
    return hits


def render_pages(role, targets, shots=None, quiet=False):
    from playwright.sync_api import sync_playwright
    login_name, password, _label = ROLES[role]
    out = []
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={'width': 1440, 'height': 900}, locale='zh-CN')
        ctx.set_default_timeout(20000)     # 硬超时：页面被 modal/忙循环卡住时 evaluate 不会永久挂
        ctx.set_default_navigation_timeout(30000)
        pg = ctx.new_page()
        pg.goto(BASE + '/web/login?db=' + DB, wait_until='domcontentloaded')
        pg.fill('input[name="login"]', login_name)
        pg.fill('input[name="password"]', password)
        pg.press('input[name="password"]', 'Enter')
        pg.wait_for_timeout(6000)
        for label, path in targets:
            rec = dict(label=label, path=path, role=role)
            try:
                resp = pg.goto(BASE + path, wait_until='load', timeout=45000)
                rec['status'] = resp.status if resp else None
                # 等 Web 客户端真的挂载（冷缓存时 4s 不够，会拿到只有 <body> 的空壳 = 假读数）
                try:
                    pg.wait_for_selector('.o_web_client, .o_main_navbar, .o_login, .oe_apps_menu',
                                         timeout=25000, state='attached')
                except Exception:                      # noqa: BLE001
                    rec['client_boot'] = 'timeout'
                pg.wait_for_timeout(2500)
                payload = pg.evaluate(DOM_PROBE)
                rec.update(url=pg.url, title=payload['title'],
                           has_form=payload['has_form'], has_list=payload['has_list'],
                           has_kanban=payload['has_kanban'], rows=payload['rows'],
                           navbar=payload['navbar'][:400], text=payload['body'][:2500])
                rec['english'] = scan_dom(payload, role, path)
                if shots:
                    fn = os.path.join(shots, '%s_%s.png' % (role, re.sub(r'[^A-Za-z0-9]+', '_', label).strip('_')))
                    pg.screenshot(path=fn, full_page=False)
                    rec['shot'] = fn
            except Exception as exc:                     # noqa: BLE001
                rec['error'] = str(exc)[:160]
            out.append(rec)
            if not quiet:
                print('  %-26s %-40s %s | title=%r | EN=%d' % (
                    label, path, rec.get('status'), rec.get('title'), len(rec.get('english') or [])))
        br.close()
    return out


# ------------------------------------------------------------------ 自证
def selftest():
    """离线自证：分类器确实能把后台的英文抓出来、且不误伤白名单/数据/中文。"""
    cases = [
        ('Quizzes', 'must-fix'),
        ('Attempts', 'must-fix'),
        ('Technical Pages', 'must-fix'),
        ('All Conversations', 'must-fix'),
        ('Looking for Help', 'must-fix'),
        ('Manage Students, Faculties and Education Institute', 'must-fix'),
        ('学生信息', None),
        ('【演示】王小明', None),
        ('COVENANT REFORMED SEMINARY', 'whitelist'),
        ('Zoom', 'whitelist'),
        ('Administrator', 'data'),
        ('CRS-MCS', 'data'),
        ('EDU-2026-0001', 'data'),
        ('转到您的Odoo应用程序', 'brand'),
        ('OpenEduCat Core', None),          # 中英混排无 CJK... 实为品牌 token -> brand
    ]
    fails = 0
    for value, expect in cases:
        got = CE.classify(value)
        bucket = got[1] if got else None
        ok = (bucket == expect)
        if value == 'OpenEduCat Core':
            ok = bucket in ('brand', 'must-fix')       # 含品牌 token，必须被抓（不得为 None/whitelist）
            expect = 'brand|must-fix'
        if not ok:
            fails += 1
        print('  %-52r 期望 %-14s 实得 %-14s %s' % (value, expect, bucket, 'OK' if ok else 'FAIL'))
    print('  selftest: %d/%d' % (len(cases) - fails, len(cases)))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--menus', action='store_true')
    ap.add_argument('--pages', action='store_true')
    ap.add_argument('--role', default=None)
    ap.add_argument('--depth', type=int, default=1)
    ap.add_argument('--json', default=None)
    ap.add_argument('--shots', default=None)
    ap.add_argument('--inject', default=None)
    ap.add_argument('--urls', default=None,
                    help='定点渲染：label=path,label=path（与 --pages/--depth 二选一）')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    print('== %s ==' % self_attest())
    if a.selftest:
        return selftest()

    roles = [a.role] if a.role else list(ROLES)
    report = dict(stamp=RUN_STAMP, attest=self_attest(), roles={})
    all_hits = []
    for role in roles:
        sess, uid = login(*ROLES[role][:2])
        if not uid:
            print('!! %s 登录失败 —— INCOMPLETE' % role)
            return 3
        data = load_menus(sess)
        rows = menu_tree(data)
        roots = [r for r in rows if r[0] == 0]
        entry = dict(uid=uid, menus=len(rows), roots=len(roots),
                     root_names=[r[2] for r in roots])
        print('== %-11s uid=%s 菜单 %d 条 / 可见根 %d 条 ==' % (role, uid, len(rows), len(roots)))
        print('   可见根：%s' % '、'.join(entry['root_names']))
        if a.menus:
            hits = scan_menus(rows, role)
            entry['menu_hits'] = hits
            all_hits += hits
            mf = [h for h in hits if h['bucket'] == 'must-fix']
            print('   menu 源命中：must-fix %d / brand %d / whitelist %d / data %d'
                  % (len(mf), len([h for h in hits if h['bucket'] == 'brand']),
                     len([h for h in hits if h['bucket'] == 'whitelist']),
                     len([h for h in hits if h['bucket'] == 'data'])))
            for h in mf:
                print('     [MUST-FIX] %-46r depth=%s id=%s %s'
                      % (h['value'], h['depth'], h['menu_id'], h['xmlid']))
        if a.pages and a.urls:
            uniq = []
            for item in a.urls.split(','):
                label, _, path = item.partition('=')
                uniq.append((label or path, path or label))
            print('   dom 源定点渲染 %d 页' % len(uniq))
            pages = render_pages(role, uniq, shots=a.shots)
            entry['pages'] = pages
            for p in pages:
                all_hits += p.get('english') or []
            report['roles'][role] = entry
            continue
        if a.pages:
            targets = [(r[2] or r[3] or ('#%s' % r[1]),
                        ('/odoo/%s' % r[5]) if r[5] else ('/odoo/action-%s' % r[4]))
                       for r in rows if r[0] <= a.depth and r[4]]
            seen, uniq = set(), []
            for label, path in targets:
                if path in seen:
                    continue
                seen.add(path)
                uniq.append((label, path))
            print('   dom 源渲染 %d 页（depth<=%d）' % (len(uniq), a.depth))
            pages = render_pages(role, uniq, shots=a.shots)
            entry['pages'] = pages
            for p in pages:
                all_hits += p.get('english') or []
        report['roles'][role] = entry

    if a.inject:
        got = CE.classify(a.inject)
        print('== 反向注入 ==')
        print('   注入 %r -> bucket=%s（必须非 None，否则尺子抓不到后台英文）'
              % (a.inject, got[1] if got else None))
        all_hits.append(dict(value=a.inject, bucket=(got[1] if got else None),
                             source='inject', role='-', xmlid=''))

    mf = [h for h in all_hits if h['bucket'] == 'must-fix']
    brand = [h for h in all_hits if h['bucket'] == 'brand']
    print('== 汇总 ==')
    print('   探测项 %d ｜ must-fix %d ｜ brand %d' % (len(all_hits), len(mf), len(brand)))
    for h in sorted({(h['value'], h['source']) for h in mf}):
        print('   [MUST-FIX] %-46r <- %s' % h)
    if a.json:
        report['must_fix'] = mf
        report['brand'] = brand
        report['all_hits'] = all_hits
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        print('   证据已写 %s' % a.json)
    return 0 if not mf and not brand else 2


if __name__ == '__main__':
    sys.exit(main())
