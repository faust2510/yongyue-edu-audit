#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""课程分组点击直达性：改前/改后对照（同一关键词、同一账号）。

本机容器会被别的会话 docker compose restart（实测两次把我打得 ConnectionError），
所以所有请求都带重试：连不上=环境抖动，不是业务结论。
"""
import re, time, requests, json, sys
BASE='http://localhost:8069'; DB='edu19'
TAG = sys.argv[1] if len(sys.argv)>1 else 'after'
TAGRE=re.compile(r'<[^>]+>'); WS=re.compile(r'\s+')
def vis(t): return WS.sub(' ', TAGRE.sub(' ', t)).strip()

def _req(s, method, url, **kw):
    last=None
    for _ in range(20):
        try:
            return getattr(s, method)(url, **kw)
        except Exception as e:
            last=e; time.sleep(4)
    raise last

def _get(s, url, **kw):
    return _req(s, 'get', url, **kw)

def sess(login):
    s=requests.Session(); s.trust_env=False
    _get(s, BASE+'/web/login', timeout=30)
    _req(s, 'post', BASE+'/web/session/authenticate',
         json={'jsonrpc':'2.0','params':{'db':DB,'login':login,'password':'demo123'}}, timeout=30)
    return s

def courses(html):
    i=html.find('搜索结果')
    if i<0: return []
    j=html.find('edu-footer', i); block=html[i: j if j>0 else len(html)]
    out=[]
    for m in re.finditer(r'<h5 class="mt-3 mb-2 text-primary">(.*?)</h5>\s*<div class="list-group mb-2">(.*?)</div>', block, re.S):
        if '课程' not in vis(m.group(1)): continue
        for a in re.finditer(r'<a[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', m.group(2), re.S):
            out.append({'href': a.group(1), 'name': vis(a.group(2))})
    return out

rows=[]
for login in ['stu@local','parent@local','faculty@local']:
    s=sess(login)
    for kw in ['课程','选修']:
        r=_get(s, BASE+'/my/search', params={'q':kw}, timeout=60)
        for it in courses(r.text):
            g=_get(s, BASE+it['href'], allow_redirects=False, timeout=60)
            rows.append({'login':login,'kw':kw,'name':it['name'],'href':it['href'],
                         'status':g.status_code,'location':g.headers.get('Location')})
for x in rows:
    verdict='落回列表(点不进去)' if x['status']==303 else ('可打开' if x['status']==200 else '异常')
    print('%-16s q=%-4s 课程命中 %-18s -> %-24s HTTP=%-3s %s %s' % (
        x['login'], x['kw'], x['name'][:18], x['href'], x['status'], (x['location'] or ''), verdict))
n303=sum(1 for x in rows if x['status']==303)
print('\n合计 %d 条课程命中：可打开 %d，落回列表 %d' % (len(rows), len(rows)-n303, n303))
json.dump(rows, open('tests/smoke/out_search_diag/course_click_%s.json'%TAG,'w'), ensure_ascii=False, indent=1)
