#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路由可达性探针（审计用，只读；不起浏览器）。

对每条注册路由，用 5 个角色的登录会话 GET 一次，记录状态码与落地 Location。
- 静态路径（无 <converter>）：直接探。
- 动态路径（含 <converter>）：标 kind=dynamic，并把 <...> 换成 1 做一次「路由是否匹配」探针
  （命中路由但控制器自己抛 404 的情况会被单独标 no_match_or_missing，人工复核）。

判定口径写在 inventory.md：0 入链 且 5 角色均 404 才叫死路由候选。

用法：
  /opt/homebrew/bin/python3 docs/audit/redundancy/route_reach.py --json /tmp/reach.json
  ... --roles stu,bo          # 只跑部分角色
"""
import argparse
import json
import os
import re
import sys

import requests

BASE = 'http://127.0.0.1:8069'
DB = 'edu19'
USERS = {
    'anon': None,
    'stu': ('stu@local', 'demo123'),
    'fac': ('faculty@local', 'demo123'),
    'par': ('parent@local', 'demo123'),
    'bo': ('backoffice@local', 'demo123'),
    'admin': ('admin', 'demo123'),
}
CONV = re.compile(r'<[^>]*?:(?P<name>[A-Za-z_][A-Za-z0-9_]*)>|<(?P<name2>[A-Za-z_][A-Za-z0-9_]*)>')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
ROUTES = os.path.join(ROOT, 'custom_addons')


def login(sess, login_name, password, db=DB):
    r = sess.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0', 'method': 'call',
        'params': {'db': db, 'login': login_name, 'password': password},
    }, timeout=30)
    data = r.json()
    res = data.get('result') or {}
    if not res.get('uid'):
        raise SystemExit('LOGIN FAILED %s: %s' % (login_name, json.dumps(data)[:300]))
    return res['uid']


def probe(sess, path, timeout=20):
    try:
        r = sess.get(BASE + path, allow_redirects=False, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return {'status': 'EXC', 'detail': str(exc)[:120], 'loc': None}
    body = ''
    if r.status_code == 200 and len(r.content) < 400000:
        body = r.text
    return {
        'status': r.status_code,
        'loc': r.headers.get('Location'),
        'traceback': ('Traceback' in body) or ('Internal Server Error' in body),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default='/tmp/reach.json')
    ap.add_argument('--roles', default='anon,stu,fac,par,bo,admin')
    args = ap.parse_args()

    handlers = json.load(open('/tmp/routes.json') if os.path.exists('/tmp/routes.json')
                         else open(os.path.join(HERE, 'routes.json'), encoding='utf-8'))
    role_keys = [r for r in args.roles.split(',') if r in USERS]

    sess = {}
    uids = {}
    for role in role_keys:
        s = requests.Session()
        s.trust_env = False
        if USERS[role]:
            uids[role] = login(s, *USERS[role])
        sess[role] = s
    print('logged in: %s' % uids)

    def relogin(role):
        s = requests.Session()
        s.trust_env = False
        login(s, *USERS[role])
        sess[role] = s

    out = []
    n_relogin = 0
    for h in handlers:
        for route in h['routes']:
            kind = 'dynamic' if ('<' in route) else 'static'
            probe_path = CONV.sub('1', route) if kind == 'dynamic' else route
            row = {
                'route': route, 'probe_path': probe_path, 'kind': kind,
                'file': h['file'], 'func': h['func'],
                'auth': h['auth'], 'methods': h['methods'], 'type': h['type'],
                'roles': {},
            }
            for role in role_keys:
                res = probe(sess[role], probe_path)
                # 会话被前面某条路由（例如 /logout）掐掉时，anon 之外的角色会拿到
                # 「/web/login?redirect=...」——那不是这条路由的真实读数。
                # 判据：3xx 且 Location 指向登录页 ⇒ 重登一次再探，避免整轮串味。
                loc = res.get('loc') or ''
                if USERS[role] and isinstance(res['status'], int) and \
                        300 <= res['status'] < 400 and '/web/login' in loc:
                    relogin(role)
                    n_relogin += 1
                    res2 = probe(sess[role], probe_path)
                    res2['relogged'] = True
                    res = res2
                row['roles'][role] = res
            out.append(row)
            codes = ','.join('%s=%s' % (k, v['status']) for k, v in row['roles'].items())
            print('%-58s %s' % (route[:58], codes))

    json.dump(out, open(args.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('relogin events: %d' % n_relogin)
    print('wrote ' + args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
