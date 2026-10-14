#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户里的 act_url 入口清点：**有没有哪个入口渲染成了后台深链**（= 会先闪后台）。

为什么要它：ir.actions.act_url 的机制是「先把后台 webclient 起起来，再由 JS 执行
window.location = url」。所以门户里任何一处把 act_url 写成 /odoo/action-<id>，
用户点下去都会**先整屏闪一遍 Odoo 后台外壳**（蓝顶栏 + 空白 + 「正在加载」）再落到
门户页 —— 用户实测缺陷（edu.example.org 点「资料下载」）。

判据（对着**真渲染出来的 HTML** 判，不对着代码判）：
  · FAIL：门户页（/apps、/my/home、/my/search）里出现 href="/odoo/action-<id>"，
          而该 id 的动作用户可见且是 url 非空的 ir.actions.act_url；
  · OK  ：该 act_url 的入口渲染成它的 url（直达），或它根本不是门户入口（只在后台菜单里）。
  · 正对照：门户页里必须仍看得到若干 /odoo/action-<id>（act_window 那些本来就该进后台）
            —— 否则说明我们根本没抓到入口，判定无效（不静默通过）。
  · 负对照：凭空造的 action id 必须不出现。

清点表按 act_url 逐条打印：url / target / 绑定菜单 / 是否出现在门户 HTML / 判定。

用法：python3 tests/smoke/portal_act_url_inventory.py [--role backoffice|admin]
退出码：0 = 无「门户里的后台深链 act_url」；1 = 有；2 = ENV（栈没起 / psql 不可用）。
"""
import argparse
import http.cookiejar
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

BASE = os.environ.get('EDU_BASE', 'http://127.0.0.1:8069')
DB = os.environ.get('EDU_DB', 'edu19')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CREDS = {
    'backoffice': ('backoffice@local', 'demo123'),
    'admin': ('admin', 'demo123'),
}
# 门户面：入口能被用户点到的三个地方（/apps 卡片、任意门户页的浮动「转到您的应用」下拉、
# 全站搜索结果分组）。
PAGES = ['/apps', '/my/home', '/my/search?q=' + urllib.parse.quote('邀请码')]
NEGATIVE_PROBE_ID = 987654321     # 负对照：这个 id 不该出现在任何页面里


def opener_for():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def post_json(op, path, payload):
    req = urllib.request.Request(
        BASE + path, data=payload.encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with op.open(req, timeout=30) as fh:
        import json
        return json.loads(fh.read().decode('utf-8'))


_ANCHOR_RE = re.compile(r'<a\s([^>]*)>(.*?)</a>', re.S)


def anchors(html):
    """(href, 纯文本) 列表 —— 入口判定要**按锚文本归属**，不能只看 url 字符串出现过。"""
    out = []
    for m in _ANCHOR_RE.finditer(html):
        href = re.search(r'href="([^"]*)"', m.group(1))
        text = re.sub(r'<[^>]+>', ' ', m.group(2))
        out.append((href.group(1) if href else None,
                    re.sub(r'\s+', ' ', text).strip()))
    return out


def fetch(op, path):
    with op.open(BASE + path, timeout=30) as fh:
        return fh.read().decode('utf-8', 'replace')


def login(op, user, pwd):
    """走 JSON-RPC /web/session/authenticate。**不要**用表单 POST /web/login ——
    它要 csrf_token，脚本拿不到（实测 400 BAD REQUEST）；本门禁要的只是"以某身份取
    门户 HTML"，不需要经过登录页。"""
    import json as _json
    payload = _json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': {
        'db': DB, 'login': user, 'password': pwd}})
    j = post_json(op, '/web/session/authenticate', payload)
    return (j.get('result') or {}).get('uid') or 0


def psql(sql):
    """库真相（与 scripts/check_live_registry.py 同一条取数路径）。"""
    try:
        r = subprocess.run(
            ['docker', 'compose', 'exec', '-T', 'db', 'psql', '-U', 'odoo',
             '-d', DB, '-A', '-F', '|', '-t', '-c', sql],
            capture_output=True, text=True, cwd=ROOT, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return [ln.split('|') for ln in r.stdout.strip().splitlines() if ln.strip()]


def detect_offenders(act_url_rows, page_anchors):
    """判据核心（与渲染无关，可单独喂夹具）：

      门户页里出现 href="/odoo/action-<id>" 且该 id 是 **url 非空的 ir.actions.act_url**
      ⇒ 该入口会先闪后台 ⇒ 记一条失败项。

    ⚠ 判据**不按名字匹配**：锚文本只用于解释"是哪个人口"。
    返回 [(act_id, url, [(page, anchor_text), ...]), ...]。
    """
    by_id = {str(r[0]): r for r in act_url_rows}
    found = {}
    for page, items in page_anchors.items():
        for href, text in items:
            m = re.fullmatch(r'/odoo/action-(\d+)', href or '')
            if not m:
                continue
            row = by_id.get(m.group(1))
            if row is None:
                continue
            act_id, url, _target = row
            if url:
                found.setdefault(act_id, (url, []))[1].append((page, text))
    return [(k, v[0], v[1]) for k, v in sorted(found.items())]


def selftest():
    """夹具自证：判据该红时必须红、该绿时必须绿（防「永远绿」的假门禁）。"""
    rows = [(755, '/downloads', 'self'), (758, '/ledger', 'self'),
            (784, '', 'self')]          # 784 = url 为空的 act_url（不该被判）
    cases = [
        ('门户里是后台深链 → 必须红',
         {'/apps': [('/odoo/action-755', '资料下载')]}, [755]),
        ('门户里直达 → 必须绿',
         {'/apps': [('/downloads', '资料下载')]}, []),
        ('deep link 指向 url 为空的 act_url → 必须绿（无从直达）',
         {'/apps': [('/odoo/action-784', 'X')]}, []),
        ('deep link 指向 act_window（不在 act_url 清单里）→ 必须绿',
         {'/apps': [('/odoo/action-382', '学生信息')]}, []),
    ]
    ok = True
    for name, anchors, expect in cases:
        got = [a for a, _u, _w in detect_offenders(rows, anchors)]
        good = got == expect
        ok = ok and good
        print('SELFTEST %s %-46s 期望 %s 实得 %s'
              % ('PASS' if good else 'FAIL', name, expect, got))
    print('SELFTEST 总结：%s' % ('全部通过' if ok else '有失败'))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--role', default='backoffice', choices=sorted(CREDS))
    ap.add_argument('--selftest', action='store_true', help='只跑夹具自证，不连站点')
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    op = opener_for()
    user, pwd = CREDS[args.role]
    user = os.environ.get('EDU_%s_LOGIN' % args.role.upper(), user)
    pwd = os.environ.get('EDU_%s_PASSWORD' % args.role.upper(), pwd)
    try:
        uid = login(op, user, pwd)
    except Exception as e:
        print('ENV：登录不上本地栈（%s: %s）' % (type(e).__name__, e))
        return 2
    if not uid:
        print('ENV：登录后会话无 uid（凭据被拒？）')
        return 2

    pages = {}
    for p in PAGES:
        try:
            pages[p] = fetch(op, p)
        except Exception as e:
            print('ENV：取 %s 失败（%s）' % (p, e))
            return 2

    rows = psql("SELECT id, url, target FROM ir_act_url ORDER BY id")
    if rows is None:
        print('ENV：psql 取不到 act_url 清单（栈没起 / docker compose 不可用）')
        return 2

    # 正对照：门户页里必须仍看得到后台深链（act_window 那些本来就该进后台）
    all_action_hrefs = set()
    for html in pages.values():
        all_action_hrefs |= set(re.findall(r'href="(/odoo/action-\d+)"', html))
    n_positive = len(all_action_hrefs)
    negative_hit = any(str(NEGATIVE_PROBE_ID) in h for h in all_action_hrefs)
    print('正对照：门户页里的后台深链 /odoo/action-N 共 %d 个（应为 >0，否则没抓到入口）'
          % n_positive)
    print('负对照：凭空造的 action id %d %s'
          % (NEGATIVE_PROBE_ID, '出现（判定无效）' if negative_hit else '未出现 ✓'))

    print()
    print('%-6s %-34s %-7s %-28s %-9s %s'
          % ('id', 'url', 'target', '绑定菜单(id/名)', '门户HTML', '判定'))
    print('-' * 118)
    page_anchors = {p: anchors(html) for p, html in pages.items()}
    # 失败项判据**不看锚文本**（只看"门户里出现 href=/odoo/action-<act_url id>"），
    # 这样名字对不上也逃不掉；锚文本只在下面用来解释"是哪个人口"。
    offenders = detect_offenders(rows, page_anchors)
    off_by_id = {a: (u, w) for a, u, w in offenders}
    portal_entries, backend_only = [], []
    for act_id, url, target in rows:
        menus = psql("SELECT id, COALESCE(name->>'zh_CN', name->>'en_US') "
                     "FROM ir_ui_menu WHERE action = 'ir.actions.act_url,%s' "
                     "ORDER BY id" % act_id) or []
        names = [m[1] for m in menus if m[1]]
        menu_txt = '、'.join('%s/%s' % (m[0], m[1]) for m in menus) or '—（无菜单绑定）'
        # 「同上一个入口直达」只按名字归属判定：url 字符串（/ledger、/ 之类）本来
        # 就有别的门户链接在用，不按名字会假阳。
        seen_url = []
        for p, items in page_anchors.items():
            for href, text in items:
                hit = next((n for n in names if n in text), None)
                if hit and url and href == url:
                    seen_url.append('%s[%s]' % (p, hit))
        seen_deep = off_by_id.get(act_id, (None, []))[1]
        if seen_deep:
            verdict = 'FAIL 门户里是后台深链（会闪后台）'
        elif seen_url:
            verdict = 'OK 门户里按名字直达 %s' % url
            portal_entries.append((act_id, url, seen_url))
        elif menus:
            verdict = 'OK 门户里没有这个名字的入口（只在后台菜单里）'
            backend_only.append((act_id, url, menu_txt))
        else:
            verdict = 'OK 无菜单绑定（当前不可达）'
            backend_only.append((act_id, url, '—'))
        print('%-6s %-34s %-7s %-28s %-9s %s'
              % (act_id, (url or '(空)')[:34], target or '-', menu_txt[:28],
                 ('是' if seen_deep else ('直达' if seen_url else '否')), verdict))

    print()
    print('门户里按名字直达的 act_url：%d 条 —— %s'
          % (len(portal_entries),
             '、'.join('%s->%s（%s）' % (a, u, '、'.join(w))
                       for a, u, w in portal_entries) or '（无）'))
    print('门户里没有对应名字入口的 act_url：%d 条（只在后台菜单里 ⇒ 后台自己的 act_url'
          ' 跳转不属本缺陷面）' % len(backend_only))
    for a, u, where in backend_only:
        print('    · action %s（%s）绑定菜单：%s' % (a, u or '(空)', where))

    ok = (not offenders) and n_positive > 0 and not negative_hit
    if offenders:
        print()
        print('失败项：')
        for act_id, url, where in offenders:
            print('  · action %s（url=%s）在门户页渲染成 /odoo/action-%s：%s'
                  % (act_id, url, act_id,
                     '、'.join('%s「%s」' % (p, t) for p, t in where)))
    print()
    print('RESULT=%s（失败项 %d / 正对照 %d / 负对照 %s）'
          % ('OK' if ok else 'FAIL', len(offenders), n_positive,
             'clean' if not negative_hit else 'HIT'))
    print('契约：exit 0=OK 1=FAIL 2=ENV')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
