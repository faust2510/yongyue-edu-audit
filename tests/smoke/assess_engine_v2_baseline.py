#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 2 期改造前的存量算分基线（只读，落盘 JSON）。"""
import json, os, subprocess, sys, urllib.request, http.cookiejar

BASE = 'http://localhost:8069'
DB = 'edu19'

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.addheaders = [('Accept-Language', 'zh-CN,zh;q=0.9')]

def rpc(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                headers={'Content-Type': 'application/json'})
    with op.open(req, timeout=60) as r:
        return json.loads(r.read().decode())

def call(model, method, args=None, kwargs=None):
    d = rpc('/web/dataset/call_kw', {'jsonrpc':'2.0','method':'call','params':{
        'model': model, 'method': method, 'args': args or [], 'kwargs': kwargs or {}}})
    if 'error' in d:
        raise SystemExit('RPC error %s: %s' % (model, json.dumps(d['error'])[:400]))
    return d.get('result')

auth = rpc('/web/session/authenticate', {'jsonrpc':'2.0','params':{
    'db': DB, 'login': 'admin', 'password': 'demo123'}})
uid = (auth.get('result') or {}).get('uid')
print('uid =', uid)

snap = {}
for m, fields in [
    ('edu.assess.template', ['id','name','kind','target_kind','total','pass_line','excellent_line','state']),
    ('edu.assess.item', ['id','template_id','name','max_score','weight','score_kind','sequence','active']),
    ('edu.assess.task', ['id','template_id','period','state','target_kind','anonymous','scorer_kind','summary_min']),
    ('edu.assess.roster', ['id','task_id','subject_ref','state','total','weighted_total','average','scorer_count','subject_name']),
    ('edu.assess.score', ['id','task_id','roster_id','item_id','value','scorer_ref','note']),
]:
    recs = call(m, 'search_read', [[], fields], {'order': 'id'})
    snap[m] = recs
    print(m, len(recs))
out = 'tests/smoke/assess_engine_v2_before.json'
os.makedirs('tests/smoke', exist_ok=True)
with open(out, 'w') as f:
    json.dump(snap, f, ensure_ascii=False, indent=1)
print('wrote', out)
# psql 行数（只读）
sql = ("select 'edu_assess_template', count(*) from edu_assess_template union all "
       "select 'edu_assess_item', count(*) from edu_assess_item union all "
       "select 'edu_assess_task', count(*) from edu_assess_task union all "
       "select 'edu_assess_roster', count(*) from edu_assess_roster union all "
       "select 'edu_assess_score', count(*) from edu_assess_score union all "
       "select 'edu_eval_template', count(*) from edu_eval_template union all "
       "select 'edu_eval_score', count(*) from edu_eval_score union all "
       "select 'edu_admin_eval_template', count(*) from edu_admin_eval_template union all "
       "select 'edu_admin_eval_score', count(*) from edu_admin_eval_score")
p = subprocess.run(['docker','exec','edu19-clone-db-1','psql','-U','odoo','-d','edu19','-tAc',sql],
                   capture_output=True, text=True)
print(p.stdout, p.stderr)
