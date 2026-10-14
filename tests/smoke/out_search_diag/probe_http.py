#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""越权证据固化：把 stu@local 搜索时页面里出现的『别人的申诉』原样存盘。"""
import re, requests, json, os
BASE='http://localhost:8069'; DB='edu19'
TAGRE=re.compile(r'<[^>]+>'); WS=re.compile(r'\s+')
def vis(t): return WS.sub(' ', TAGRE.sub(' ', t)).strip()
s=requests.Session(); s.trust_env=False
s.post(BASE+'/web/session/authenticate', json={'jsonrpc':'2.0','params':{'db':DB,'login':'stu@local','password':'demo123'}}, timeout=30)
out={}
for kw in ['ZZ越权探针','zzz_no_such_thing','账单','成绩']:
    r=s.get(BASE+'/my/search', params={'q':kw}, timeout=60)
    i=r.text.find('搜索结果'); j=r.text.find('edu-footer', i)
    block=r.text[i:j] if i>=0 else ''
    names=[vis(a.group(1)) for a in re.finditer(r'<a[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', block, re.S)]
    out[kw]={'status':r.status_code,'no_result_msg':('没有找到与' in r.text),
             'items':names,'raw_block':re.sub(r'\s+',' ',block)[:2500]}
os.makedirs('tests/smoke/out_search_diag', exist_ok=True)
json.dump(out, open('tests/smoke/out_search_diag/before_leak_proof.json','w'), ensure_ascii=False, indent=1)
for k,v in out.items():
    print('q=%-16s HTTP=%s 无结果提示=%s 命中=%s' % (k, v['status'], v['no_result_msg'], v['items']))
print()
print('ZZ越权探针 原始块:', out['ZZ越权探针']['raw_block'][:600])
