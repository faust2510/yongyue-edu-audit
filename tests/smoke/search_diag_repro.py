#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户统一搜索（/my/search）定性复现 —— 只读，不改任何数据。

输出：tests/smoke/out_search_diag/<tag>.json
用法：python3 tests/smoke/search_diag_repro.py before
"""
import json, os, re, sys
import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
PW = 'demo123'
TAG = sys.argv[1] if len(sys.argv) > 1 else 'before'
OUT = os.path.join('tests/smoke/out_search_diag', '%s.json' % TAG)

ACCOUNTS = ['stu@local', 'parent@local', 'faculty@local', 'backoffice@local']
# 关键词来自库中真实数据（见 build/keywords）
KEYWORDS = ['圣经', '小要理问答', '作业', '账单', '布告', 'a', 'zzz_no_such_thing']

TAGRE = re.compile(r'<[^>]+>')
WSRE = re.compile(r'\s+')


def visible(t):
    return WSRE.sub(' ', TAGRE.sub(' ', t)).strip()


def sess(login):
    s = requests.Session()
    s.trust_env = False
    s.headers.update({'User-Agent': 'search-diag/1.0'})
    r = s.post(BASE + '/web/session/authenticate',
               json={'jsonrpc': '2.0', 'params': {'db': DB, 'login': login, 'password': PW}},
               timeout=30)
    uid = (r.json().get('result') or {}).get('uid')
    return s, uid


def parse_groups(html):
    """从结果页抽 [组名, [ (name, href), ... ] ]。"""
    groups = []
    for m in re.finditer(r'<h5[^>]*>(.*?)</h5>(.*?)(?=<h5|$)', html, re.S):
        gm = re.search(r'<t t-out="grp\[0\]"/>', m.group(1))
        label = visible(m.group(1))
        items = [(visible(a.group(2)), a.group(1))
                 for a in re.finditer(r'<a t-att-href="?([^"\s>]+)"?[^>]*>(.*?)</a>', m.group(2), re.S)]
        groups.append({'raw_label': label, 'items': [{'name': n, 'href': h} for n, h in items]})
    return groups


out = {'tag': TAG, 'probes': []}
# 0) 未登录直接访问（应跳登录页，不算 bug）
anon = requests.Session(); anon.trust_env = False
r = anon.get(BASE + '/my/search?q=圣经', allow_redirects=False, timeout=30)
out['anon'] = {'status': r.status_code, 'location': r.headers.get('Location')}

for login in ACCOUNTS:
    s, uid = sess(login)
    rec = {'login': login, 'uid': uid, 'probes': []}
    # 输入框可用性：先取一个带搜索框的页面，核对表单三要素
    page = s.get(BASE + '/my/home', timeout=30)
    form = re.search(r'<form[^>]*action="/my/search"[^>]*>.*?</form>', page.text, re.S)
    rec['form_html'] = WSRE.sub(' ', form.group(0)) if form else None
    for kw in KEYWORDS:
        url = BASE + '/my/search?q=' + requests.utils.quote(kw)
        try:
            g = s.get(url, timeout=60)
            body = g.text
            is_err = ('Traceback' in body) or ('Internal Server Error' in body) or g.status_code >= 500
            err_line = ''
            if is_err:
                mm = re.search(r'(Invalid field[^<\n]*|AttributeError[^<\n]*|Error[^<\n]{0,160})', visible(body))
                err_line = mm.group(1) if mm else visible(body)[:300]
            groups = parse_groups(body)
            rec['probes'].append({
                'kw': kw, 'url': url, 'status': g.status_code,
                'error': is_err, 'error_sample': err_line,
                'empty_msg': ('没有找到与' in body),
                'need_kw_msg': ('请输入关键词' in body),
                'groups': [gg['raw_label'] for gg in groups],
                'groups_full': groups,
            })
        except Exception as e:
            rec['probes'].append({'kw': kw, 'url': url, 'exception': repr(e)})
    out['probes'].append(rec)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

# 精简打印
print('ANON', out['anon'])
for rec in out['probes']:
    print('\n== %s uid=%s' % (rec['login'], rec['uid']))
    print('  FORM:', (rec['form_html'] or '')[:200])
    for p in rec['probes']:
        if 'exception' in p:
            print('  q=%-18s EXC %s' % (p['kw'], p['exception'])); continue
        print('  q=%-18s HTTP=%s err=%s empty=%s needkw=%s groups=%s' % (
            p['kw'], p['status'], p['error'], p['empty_msg'], p['need_kw_msg'], p['groups']))
        if p['error']:
            print('      ERR_SAMPLE:', p['error_sample'][:250])
        for gg in p['groups_full']:
            for it in gg['items'][:3]:
                print('      - [%s] %s -> %s' % (gg['raw_label'], it['name'][:40], it['href']))
print('\nWROTE', OUT)
