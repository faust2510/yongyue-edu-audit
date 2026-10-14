#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路由审计（只读）：注册表 × 可达性 × 入链，三源对账。

三源：
  1. route_probe.py   -> 代码里声明的路由（309 条）
  2. route_registry.py-> 跑着的 odoo 进程的 routing_map（真注册表）
  3. route_reach.py   -> 6 个角色实测状态码（存在 /tmp/reach.json）

入链口径：在 custom_addons/**/*.{xml,js,py} + docs/ + tests/ + scripts/ 里 grep 路径字面量
（动态段取 '<' 之前的前缀），排除定义该路由的文件本身、__pycache__、.agent-teams、data/。

用法：/opt/homebrew/bin/python3 docs/audit/redundancy/route_audit.py --json docs/audit/redundancy/routes_report.json
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SKIP_DIRS = ('.git', '__pycache__', '.agent-teams', 'data', 'node_modules', 'reference', 'scrape', '.zcode')
SELF_DIR = os.path.join('docs', 'audit', 'redundancy')  # 本审计自己的产物不算「引用」
SCAN_ROOTS = ['custom_addons', 'docs', 'tests', 'scripts', 'specs', 'deploy', 'config']


def scan_files():
    for base in SCAN_ROOTS:
        top = os.path.join(ROOT, base)
        if not os.path.isdir(top):
            continue
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if fn.endswith(('.py', '.xml', '.js', '.css', '.scss', '.csv', '.json', '.md', '.sh', '.txt')):
                    rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
                    if rel.startswith(SELF_DIR + os.sep):
                        continue
                    yield os.path.join(dirpath, fn)


LINKISH = re.compile(
    r'href|action\s*=|fetch\(|\.open\(|url\s*[:=]|redirect\(|location|data-url|t-attf-href|data-href', re.I)
ROUTE_DEF = re.compile(r'@http\.route')


def key_patterns(r):
    """一条路由 -> (主路径写法, 卡片 key 写法)。

    ① 主路径：带前导斜杠的路径（href="/my/home"、request.redirect('/my/x')…）。
    ② 卡片 key：**不带前导斜杠、带引号**的写法 —— 门户宫格引擎的 key 就是这样存的，
       运行时才拼成 href：batch2.py 的 cards()/card_href 分支写的是
       "'href': '/' + href"（见 batch2.py 的 cards / _OPENEDUCAT_CARDS）。
       只对「含 / 的多段路径」生效，避免把 'quiz' 这种单词当命中去撞全文。
    两类命中分开计数：key 命中**不等于**链接命中（那一行不是链接，链接是运行时拼的）。
    """
    k = r if '<' not in r else r.split('<')[0]
    k2 = k.lstrip('/')
    key_pats = ["'" + k2 + "'", '"' + k2 + '"'] if '/' in k2 else []
    return k, key_pats


def inbound_index():
    """one pass: 每个候选 key -> 两类命中。

    link  = 行里有「真链接/跳转」特征（href / action= / fetch / redirect / url: ...）
            且这一行不是该路由的 @http.route 声明行 —— 这才算「入链」。
    ref   = 其余命中（文档、docstring 里的路径列举、登记表 JSON）——只作旁证。
    """
    keys = {}
    routes = json.load(open('/tmp/routes.json', encoding='utf-8'))
    for h in routes:
        for r in h['routes']:
            k, key_pats = key_patterns(r)
            keys[k] = key_pats
    hits = {k: {'link': [], 'ref': [], 'key': []} for k in keys}
    # 单一合并正则（C 层扫描）：pattern -> 路由 key。逐 key 逐行 in 太慢（~20k 文件）。
    all_pats = set()
    for k, key_pats in keys.items():
        all_pats.add(k)
        all_pats.update(key_pats)
    big = re.compile('|'.join(re.escape(p) for p in sorted(all_pats, key=len, reverse=True)))
    for path in scan_files():
        try:
            text = open(path, encoding='utf-8', errors='ignore').read()
        except Exception:
            continue
        rel = os.path.relpath(path, ROOT)
        for i, line in enumerate(text.splitlines(), 1):
            # 先合并正则做**快速排除**（C 层扫描），命中行再逐 key 精确判定。
            # ⚠ 不能直接用 findall 的结果当判据：findall 是非重叠匹配，长路径一旦吃掉了
            #   它自己那段，作为其前缀的短路由（如 /my/checkin ⊂ /my/checkin/board）会漏判。
            if not big.search(line):
                continue
            bucket = 'link' if (LINKISH.search(line) and not ROUTE_DEF.search(line)) else 'ref'
            for k, key_pats in keys.items():
                if k in line:
                    hits[k][bucket].append((rel, i, line.strip()[:160]))
                elif any(p in line for p in key_pats):
                    hits[k]['key'].append((rel, i, line.strip()[:160]))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default=os.path.join(HERE, 'routes_report.json'))
    args = ap.parse_args()

    routes = json.load(open('/tmp/routes.json', encoding='utf-8'))
    reach = {r['route']: r for r in json.load(open('/tmp/reach.json', encoding='utf-8'))}
    reg = json.load(open(os.path.join(HERE, 'routing_map.json'), encoding='utf-8'))
    registered = set(x['rule'] for x in reg)
    base_registered = set()
    for rule in registered:
        base_registered.add(rule.split('<')[0] if '<' in rule else rule)

    print('scanning inbound links ...')
    hits = inbound_index()

    rows = []
    for h in routes:
        for r in h['routes']:
            key = r if '<' not in r else r.split('<')[0]
            self_file = h['file']
            bucket = hits.get(key, {'link': [], 'ref': []})
            # 入链 = 真链接特征命中，且不在「声明该路由的那一行」
            ib_code = [x for x in bucket['link'] if x[0].startswith('custom_addons/')]
            ib_docs = [x for x in bucket['link'] if not x[0].startswith('custom_addons/')]
            ib_refs = [x for x in bucket['ref'] if x[0] != self_file]
            # key 桶**不排除自身文件**：卡片引擎的 key 列表与路由声明常在同一文件
            # （batch2.py 既声明 /student/progression 又存 'student/progression' 这个 key），
            # 而带引号的无斜杠写法不可能是 @http.route 声明行，不存在自证污染。
            ib_keys = list(bucket.get('key', []))
            rc = reach.get(r, {})
            st = {k: v['status'] for k, v in (rc.get('roles') or {}).items()}
            in_reg = (r in registered) or (key in base_registered)
            # ⚠ 落盘的命中只留**样本**（每桶最多 8 条）+ 总数：全量落盘会产出 ~19MB JSON，
            #   没必要（复跑一条命令就能重算）；判据用的计数一个不少。
            CAP = 8
            rows.append({
                'route': r, 'file': self_file, 'func': h['func'], 'auth': h['auth'],
                'methods': h['methods'], 'kind': rc.get('kind'),
                'registered': bool(in_reg),
                'inbound_code': ib_code[:CAP], 'inbound_code_n': len(ib_code),
                'inbound_other': ib_docs[:CAP], 'inbound_other_n': len(ib_docs),
                'refs': ib_refs[:CAP], 'refs_n': len(ib_refs),
                'key_refs': ib_keys[:CAP], 'key_refs_n': len(ib_keys),
                'status': st,
                'probe_path': rc.get('probe_path'),
            })

    n_unreg = [x for x in rows if not x['registered']]
    n_noib_code = [x for x in rows if not x['inbound_code']]
    n_noib_any = [x for x in n_noib_code if not x['key_refs'] and not x['inbound_other']]
    n_all404 = [x for x in rows if x['status'] and all(v == 404 for v in x['status'].values())]
    print('routes=%d  未注册=%d  0 代码入链=%d（其中连 key/文档引用也没有=%d）  全角色 404=%d'
          % (len(rows), len(n_unreg), len(n_noib_code), len(n_noib_any), len(n_all404)))
    print()
    print('== 未注册（代码里有、跑着的进程没有） ==')
    for x in n_unreg:
        print('  %-52s %s' % (x['route'][:52], x['file']))
    print()
    print('== 全角色 404 ==')
    for x in n_all404:
        print('  %-52s %-10s reg=%s %s' % (x['route'][:52], x['kind'], x['registered'], x['file']))
    print()
    print('== 0 代码入链（可能靠 JS/docs/外部入口） ==')
    for x in n_noib_code:
        extra = 'other=%d' % len(x['inbound_other'])
        print('  %-52s %-8s reg=%-5s %s %s' % (x['route'][:52], x['kind'], x['registered'], extra, x['file']))
    json.dump(rows, open(args.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print()
    print('wrote ' + args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
