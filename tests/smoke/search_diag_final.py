#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""终局校验：清理探针后重跑同一取证仪 + 内部用户邀请码分组（另一会话的脏改动路径）不回归。"""
import re, time, requests, json, subprocess, sys
BASE='http://localhost:8069'; DB='edu19'
TAGRE=re.compile(r'<[^>]+>'); WS=re.compile(r'\s+')
def vis(t): return WS.sub(' ', TAGRE.sub(' ', t)).strip()
def _req(s, m, url, **kw):
    last=None
    for _ in range(20):
        try: return getattr(s,m)(url, **kw)
        except Exception as e: last=e; time.sleep(4)
    raise last
def sess(login):
    s=requests.Session(); s.trust_env=False
    _req(s,'get',BASE+'/web/login',timeout=30)
    _req(s,'post',BASE+'/web/session/authenticate',
         json={'jsonrpc':'2.0','params':{'db':DB,'login':login,'password':'demo123'}}, timeout=30)
    return s
def groups(html):
    i=html.find('搜索结果')
    if i<0: return None
    j=html.find('edu-footer', i); block=html[i: j if j>0 else len(html)]
    out=[]
    for m in re.finditer(r'<h5 class="mt-3 mb-2 text-primary">(.*?)</h5>\s*<div class="list-group mb-2">(.*?)</div>', block, re.S):
        label=re.sub(r'\s*\d+$','',vis(m.group(1))).strip()
        items=[{'name':vis(a.group(2))[:38],'href':a.group(1)} for a in re.finditer(r'<a[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', m.group(2), re.S)]
        out.append({'group':label,'n':len(items),'items':items})
    return out

print('== ① 学生：删探针后重跑（同一关键词集）==')
s=sess('stu@local')
for kw in ['ZZ越权探针','zzz_no_such_thing','成绩','账单','公告','教材','选修']:
    r=_req(s,'get',BASE+'/my/search',params={'q':kw},timeout=60)
    gs=groups(r.text) or []
    print('  q=%-16s HTTP=%s 无结果提示=%-5s %s' % (kw, r.status_code, '没有找到与' in r.text,
          ' | '.join('%s(%d): %s' % (g['group'], g['n'], '，'.join(i['name'] for i in g['items'][:2])) for g in gs)))

print('== ② 内部用户：邀请码分组（另一会话 edu_action_href 路径）不回归 ==')
for login in ['faculty@local','backoffice@local']:
    s2=sess(login)
    for kw in ['a','冒烟','VIP']:
        r=_req(s2,'get',BASE+'/my/search',params={'q':kw},timeout=60)
        gs=groups(r.text) or []
        inv=[g for g in gs if g['group']=='邀请码']
        print('  %-17s q=%-4s HTTP=%s 分组=%s 邀请码=%s' % (login, kw, r.status_code,
              [g['group'] for g in gs], inv[0]['items'][:2] if inv else '无'))

print('== ③ 学生：测验/网课/请假（同一函数未改动的分组，确认无副作用）==')
for kw in ['计算机','要理','LV']:
    r=_req(s,'get',BASE+'/my/search',params={'q':kw},timeout=60)
    gs=groups(r.text) or []
    print('  q=%-6s %s' % (kw, ' | '.join('%s(%d)' % (g['group'],g['n']) for g in gs) or '（无分组）'))
