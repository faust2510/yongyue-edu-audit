#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户搜索 前后对照取证仪（只读）。

用法：python3 tests/smoke/search_diag_evidence.py <tag>
输出：tests/smoke/out_search_diag/evidence_<tag>.json
覆盖：4 个账号 × 关键词；记录 HTTP 码 / 分组 / 每条命中的名字与 href /
      「没有找到」提示 / 申诉单是否越权（含他人 student_id 的记录名）。
"""
import json, os, re, sys
import requests

BASE = 'http://localhost:8069'; DB = 'edu19'; PW = 'demo123'
TAG = sys.argv[1] if len(sys.argv) > 1 else 'x'
OUT = 'tests/smoke/out_search_diag/evidence_%s.json' % TAG
TAGRE = re.compile(r'<[^>]+>'); WS = re.compile(r'\s+')
def vis(t): return WS.sub(' ', TAGRE.sub(' ', t)).strip()

def sess(login):
    s = requests.Session(); s.trust_env = False
    s.post(BASE + '/web/session/authenticate', json={'jsonrpc': '2.0',
           'params': {'db': DB, 'login': login, 'password': PW}}, timeout=30)
    return s

def parse(html):
    i = html.find('搜索结果')
    if i < 0: return []
    j = html.find('edu-footer', i); block = html[i: j if j > 0 else len(html)]
    out = []
    for m in re.finditer(r'<h5 class="mt-3 mb-2 text-primary">(.*?)</h5>\s*<div class="list-group mb-2">(.*?)</div>', block, re.S):
        label = re.sub(r'\s*\d+$', '', vis(m.group(1))).strip()
        items = [{'name': vis(a.group(2))[:44], 'href': a.group(1)}
                 for a in re.finditer(r'<a[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', m.group(2), re.S)]
        out.append({'group': label, 'n': len(items), 'items': items})
    return out

ACCOUNTS = ['stu@local', 'parent@local', 'faculty@local', 'backoffice@local']
KWS = ['ZZ越权探针', 'zzz_no_such_thing', '成绩', '账单', '公告', '选课', '教材', '要理']

res = {'tag': TAG, 'rows': []}
for login in ACCOUNTS:
    s = sess(login)
    for kw in KWS:
        r = s.get(BASE + '/my/search', params={'q': kw}, timeout=60)
        gs = parse(r.text)
        res['rows'].append({
            'login': login, 'kw': kw, 'status': r.status_code,
            'no_result_msg': ('没有找到与' in r.text),
            'groups': gs,
            'grievance_leak': [it['name'] for g in gs if g['group'] == '申诉单'
                               for it in g['items'] if 'ZZ越权探针' in it['name']],
        })
        summ = ' | '.join('%s(%d)' % (g['group'], g['n']) for g in gs)
        print('%-17s q=%-16s HTTP=%s 无结果提示=%-5s %s' % (login, kw, r.status_code, res['rows'][-1]['no_result_msg'], summ))
os.makedirs('tests/smoke/out_search_diag', exist_ok=True)
json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
leaks = [(x['login'], x['kw'], x['grievance_leak']) for x in res['rows'] if x['grievance_leak']]
print('\n越权命中（学生搜索页出现他人申诉）: %s' % (leaks or '无'))
print('WROTE', OUT)
