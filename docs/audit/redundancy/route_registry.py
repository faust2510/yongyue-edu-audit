#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路由注册表快照（审计用，只读）：从跑着的 odoo 进程用 odoo shell 导出 routing_map 的全部规则。

证据用途：区分「路由不存在（真 404）」与「路由存在、控制器自己 404」。
用法：/opt/homebrew/bin/python3 docs/audit/redundancy/route_registry.py --json docs/audit/redundancy/routing_map.json
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

BODY = """
import json
m = env['ir.http'].routing_map()
rows = []
for r in m.iter_rules():
    rows.append({'rule': str(r), 'endpoint': getattr(r, 'endpoint', None) and ('%s.%s' % (r.endpoint.__module__, r.endpoint.__name__))})
print('JSON-BEGIN')
print(json.dumps(rows, ensure_ascii=False))
print('JSON-END')
"""

SHELL_CMD = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
             '-c', '/etc/odoo/odoo.conf', '-d', 'edu19',
             '--db_host=db', '-r', 'odoo', '-w', 'odoo', '--no-http']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default=os.path.join(HERE, 'routing_map.json'))
    args = ap.parse_args()
    p = subprocess.run(SHELL_CMD, input=BODY, capture_output=True, text=True, cwd=REPO, timeout=300)
    out = p.stdout or ''
    if 'JSON-BEGIN' not in out:
        print('NO OUTPUT; stderr tail:\n' + (p.stderr or '')[-800:])
        return 1
    blob = out.split('JSON-BEGIN', 1)[1].split('JSON-END', 1)[0].strip()
    rows = json.loads(blob)
    json.dump(rows, open(args.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('routing rules=%d -> %s' % (len(rows), args.json))
    return 0


if __name__ == '__main__':
    sys.exit(main())
