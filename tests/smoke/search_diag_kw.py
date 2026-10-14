#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按占位文案提示的四个词实测 + 空结果对照。"""
import re, requests, json
BASE='http://localhost:8069'; DB='edu19'
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
        items=[{'href':a.group(1),'name':vis(a.group(2))} for a in re.finditer(r'<a[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', m.group(2), re.S)]
        out.append((label, items))
    return out
for login in ['stu@local','parent@local','faculty@local']:
    s=sess(login)
    print('\n########## %s ##########' % login)
    for kw in ['作业','课程','公告','账单','布告','公告栏','通知','费用','成绩']:
        r=s.get(BASE+'/my/search', params={'q':kw}, timeout=60)
        gs=parse(r.text)
        empty='没有找到与' in r.text
        summary=' | '.join('%s(%d): %s' % (l, len(it), '，'.join(x['name'][:16] for x in it[:2])) for l,it in gs)
        print('q=%-4s HTTP=%s 无结果提示=%-5s  %s' % (kw, r.status_code, empty, summary))
