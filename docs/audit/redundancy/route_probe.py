#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路由清点器（审计用，只读）：从 custom_addons 里抽出所有 @http.route。

输出 JSON：file, func, routes[], auth, methods, type, site
模块级字符串常量（如 WEBHOOK_PATH = '/x'）会被解析。

用法：python3 docs/audit/redundancy/route_probe.py [--json out.json]
"""
import argparse
import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
ADDONS = os.path.join(ROOT, 'custom_addons')


def iter_py():
    for dirpath, dirnames, filenames in os.walk(ADDONS):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for fn in filenames:
            if fn.endswith('.py'):
                yield os.path.join(dirpath, fn)


def literals(node, consts):
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = literals(node.left, consts), literals(node.right, consts)
        if left and right:
            return [a + b for a in left for b in right]
        return None
    try:
        val = ast.literal_eval(node)
    except Exception:
        return None
    if isinstance(val, str):
        return [val]
    if isinstance(val, (list, tuple)) and all(isinstance(v, str) for v in val):
        return list(val)
    return None


def kw(node, name):
    for k in node.keywords:
        if k.arg == name:
            try:
                return ast.literal_eval(k.value)
            except Exception:
                return '<expr>'
    return None


def module_consts(tree):
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                val = ast.literal_eval(node.value)
            except Exception:
                continue
            if isinstance(val, str):
                out[node.targets[0].id] = [val]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json')
    args = ap.parse_args()

    rows, unparsed = [], []
    for path in sorted(iter_py()):
        rel = os.path.relpath(path, ROOT)
        try:
            tree = ast.parse(open(path, encoding='utf-8').read(), filename=path)
        except SyntaxError as exc:
            print('PARSE-ERR %s: %s' % (rel, exc), file=sys.stderr)
            continue
        consts = module_consts(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and dec.func.attr == 'route'):
                    continue
                if not dec.args:
                    continue
                paths = literals(dec.args[0], consts)
                if paths is None:
                    unparsed.append('%s:%s' % (rel, node.name))
                    continue
                rows.append({
                    'file': rel, 'func': node.name, 'routes': paths,
                    'auth': kw(dec, 'auth'), 'methods': kw(dec, 'methods'),
                    'type': kw(dec, 'type') or 'http', 'site': kw(dec, 'website'),
                })
    total = sum(len(r['routes']) for r in rows)
    print('handlers=%d routes=%d files=%d unparsed=%d' % (len(rows), total, len(set(r['file'] for r in rows)), len(unparsed)))
    for u in unparsed:
        print('UNPARSED ' + u, file=sys.stderr)
    if args.json:
        json.dump(rows, open(args.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('wrote ' + args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
