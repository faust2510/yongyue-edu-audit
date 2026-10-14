#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读 ORM 查询小工具（审计用）：登录本地库，跑一次 search_read / search_count。

用法：
  /opt/homebrew/bin/python3 docs/audit/redundancy/orm_query.py --model account.move --domain '[["ref","like","FEE-SEED"]]' --fields ref,state,amount_total
  /opt/homebrew/bin/python3 docs/audit/redundancy/orm_query.py --model res.users --domain '[["login","=","stu@local"]]' --fields login,edu_ical_token,id
  ... --count            # 只数行数
  ... --login admin --password demo123
"""
import argparse
import json
import sys

import requests

BASE = 'http://127.0.0.1:8069'
DB = 'edu19'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True)
    ap.add_argument('--domain', default='[]')
    ap.add_argument('--fields', default='id')
    ap.add_argument('--limit', type=int, default=20)
    ap.add_argument('--count', action='store_true')
    ap.add_argument('--login', default='admin')
    ap.add_argument('--password', default='demo123')
    args = ap.parse_args()

    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0', 'method': 'call',
        'params': {'db': DB, 'login': args.login, 'password': args.password}})
    res = r.json().get('result') or {}
    if not res.get('uid'):
        print('LOGIN FAILED: ' + json.dumps(r.json())[:300])
        return 2

    method = 'search_count' if args.count else 'search_read'
    kw = {'domain': json.loads(args.domain)}
    if not args.count:
        kw['fields'] = [f for f in args.fields.split(',') if f]
        kw['limit'] = args.limit
    payload = {'jsonrpc': '2.0', 'method': 'call',
               'params': {'model': args.model, 'method': method, 'args': [], 'kwargs': kw}}
    r2 = s.post(BASE + '/web/dataset/call_kw', json=payload)
    data = r2.json()
    if 'error' in data:
        print('ORM ERROR: ' + json.dumps(data['error'], ensure_ascii=False)[:600])
        return 1
    print(json.dumps(data['result'], ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
