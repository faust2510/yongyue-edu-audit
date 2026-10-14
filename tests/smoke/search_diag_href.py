#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""href 直达性：每个搜索结果点进去到底发生什么（匹配**渲染后**的 <a ... href="...">）。"""
import re, requests, json, sys
BASE='http://localhost:8069'; DB='edu19'
TAG = sys.argv[1] if len(sys.argv)>1 else 'before'
TAGRE=re.compile(r'<[^>]+>'); WS=re.compile(r'\s+')
def vis(t): return WS.sub(' ', TAGRE.sub(' ', t)).strip()
def sess(login):
    s=requests.Session(); s.trust_env=False
    s.post(BASE+'/web/session/authenticate', json={'jsonrpc':'2.0','params':{'db':DB,'login':login,'password':'demo123'}}, timeout=30)
    return s
def parse(html):
    i=html.find('搜索结果')
    if i<0: return []
    j=html.find('edu-footer', i); block=html[i: j if j>0 else len(html)]
    out=[]
    for m in re.finditer(r'<h5 class="mt-3 mb-2 text-primary">(.*?)</h5>\s*<div class="list-group mb-2">(.*?)</div>', block, re.S):
        label=re.sub(r'\s*\d+$','',vis(m.group(1))).strip()
        for a in re.finditer(r'<a[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', m.group(2), re.S):
            out.append({'group':label,'href':a.group(1),'name':vis(a.group(2))})
    return out

report=[]
for login in ['stu@local','faculty@local','backoffice@local','parent@local']:
    s=sess(login); seen=set()
    for kw in ['选课','教材','要理','小要理','冒烟','圣经','邀请码','计算机']:
        r=s.get(BASE+'/my/search', params={'q':kw}, timeout=60)
        for it in parse(r.text):
            key=(it['group'],it['href'])
            if key in seen: continue
            seen.add(key)
            g=s.get(BASE+it['href'], allow_redirects=False, timeout=60)
            m=re.search(r'<title>(.*?)</title>', g.text, re.S) if g.status_code==200 else None
            report.append({'login':login,'kw':kw,'group':it['group'],'name':it['name'][:40],
                           'href':it['href'],'status':g.status_code,
                           'location':g.headers.get('Location'),
                           'title':vis(m.group(1))[:50] if m else '',
                           'name_on_page':(it['name'][:8] in g.text) if g.status_code==200 else None,
                           'len':len(g.text)})
    print('--- %s done (%d items)' % (login, sum(1 for x in report if x['login']==login)))
print()
for x in report:
    print('%-16s [%-5s] %-30s -> %-32s HTTP=%-3s loc=%-24s name_on_page=%s | %s' % (
        x['login'], x['group'], x['name'], x['href'], x['status'], (x['location'] or '')[:22], x['name_on_page'], x['title']))
import os; os.makedirs('tests/smoke/out_search_diag', exist_ok=True)
json.dump(report, open('tests/smoke/out_search_diag/href_reach_%s.json'%TAG,'w'), ensure_ascii=False, indent=1)
print('\nWROTE tests/smoke/out_search_diag/href_reach_%s.json' % TAG)
