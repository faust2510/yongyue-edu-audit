#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静态资源对账（只读）：static/src 下每个 js/css/scss 是否被 manifest 的 assets 段引用、
被谁引用（列出文件与行号）、是第几行、属哪个 bundle。

判据（inventory.md 会照抄）：
  manifest_hit = 该资产**文件名**出现在同模块 __manifest__.py 里（行号给出）
  bundle       = 往上最近的 'web.assets_*' 键（行扫描，不解析 Python）
  code_refs    = 其它 .py/.xml/.js/.css/.scss 提到该文件名的位置（排除自身）

用法：/opt/homebrew/bin/python3 docs/audit/redundancy/asset_audit.py --json docs/audit/redundancy/assets_report.json
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
ADDONS = os.path.join(ROOT, 'custom_addons')
SKIP_DIRS = ('.git', '__pycache__', '.agent-teams', 'data', 'node_modules', '.zcode')
SELF_DIR = os.path.join('docs', 'audit', 'redundancy')  # 本审计自己的产物不算「引用」
EXTS = ('.js', '.css', '.scss')
BUNDLE = re.compile(r"'(web\.[A-Za-z0-9_.]*|website\.[A-Za-z0-9_.]*)'\s*:")


def assets():
    for dirpath, dirnames, filenames in os.walk(ADDONS):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if '/static/src' not in dirpath.replace(os.sep, '/'):
            continue
        for fn in filenames:
            if fn.endswith(EXTS):
                yield os.path.join(dirpath, fn)


def refs_in(root):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(('.py', '.xml', '.js', '.css', '.scss', '.md', '.sh', '.json')):
                rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
                if rel.startswith(SELF_DIR + os.sep):
                    continue
                files.append(os.path.join(dirpath, fn))
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default=os.path.join(HERE, 'assets_report.json'))
    args = ap.parse_args()

    scan = refs_in(ROOT)
    rows = []
    for path in sorted(assets()):
        rel = os.path.relpath(path, ROOT)
        base = os.path.basename(path)
        mod = rel.split(os.sep)[1]
        manifest = os.path.join(ADDONS, mod, '__manifest__.py')
        mline, bundle = None, None
        if os.path.exists(manifest):
            cur = None
            for i, line in enumerate(open(manifest, encoding='utf-8').read().splitlines(), 1):
                m = BUNDLE.search(line)
                if m:
                    cur = m.group(1)
                if base in line:
                    mline, bundle = i, cur
                    break
        others = []
        for f in scan:
            if f == path:
                continue
            try:
                for i, line in enumerate(open(f, encoding='utf-8', errors='ignore'), 1):
                    if base in line:
                        others.append({'file': os.path.relpath(f, ROOT), 'line': i,
                                       'text': line.strip()[:140]})
                        break
            except Exception:
                continue
        rows.append({'file': rel, 'manifest_line': mline, 'bundle': bundle,
                     'manifest': os.path.relpath(manifest, ROOT) if os.path.exists(manifest) else None,
                     'other_refs': others})
        print('%-58s manifest=%s bundle=%-24s other_refs=%d' % (
            rel, ('L%s' % mline) if mline else 'MISS', bundle or '-', len(others)))
    miss = [r for r in rows if not r['manifest_line']]
    print()
    print('assets=%d manifest_miss=%d' % (len(rows), len(miss)))
    for r in miss:
        print('  MISS ' + r['file'])
    json.dump(rows, open(args.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('wrote ' + args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
