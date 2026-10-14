#!/usr/bin/env python3
"""括号感知地提取原站 bundle 的 oe-* 门户样式，保留 @media 结构。"""
import re

SRC = '/tmp/site_frontend.css'
DST = 'custom_addons/edu_portal/static/src/css/enterprise.css'
PAT = re.compile(
    r'oe-(exam|asg|att|pf|adm|rc|ach|act|lib|norec|mhead|hero|kpi|mhero|'
    r'chart|donut|trend|chip|sidebar|side-card|cal|upcoming|edit-btn|'
    r'stat|bar|greeting|subtitle|search-ic|notif)')

css = open(SRC, encoding='utf-8', errors='ignore').read()

top_rules = []          # (media_stack_tuple, [rule_texts])
stack = []              # ('media', header) / ('sel', selector)
buf = ''
i, n = 0, len(css)
cur_media = tuple()
collected = {}          # media_key -> list[rule]
order = []

while i < n:
    ch = css[i]
    if ch == '{':
        sel = buf.strip()
        buf = ''
        if sel.startswith('@'):
            stack.append(('media', sel))
            key = sel
            if key not in collected:
                collected[key] = []
                order.append(key)
        else:
            stack.append(('sel', sel))
    elif ch == '}':
        if not stack:
            buf = ''
            i += 1
            continue
        kind, val = stack.pop()
        if kind == 'sel':
            body_start = css.rfind('{', 0, i)
            body = css[body_start + 1:i].strip()
            sel = val
            if PAT.search(sel) and len(sel) < 500:
                rule = f'{sel}{{{body}}}'
                if stack and stack[-1][0] == 'media':
                    mkey = stack[-1][1]
                    if mkey not in collected:
                        collected[mkey] = []
                        order.append(mkey)
                    collected[mkey].append(rule)
                else:
                    if '' not in collected:
                        collected[''] = []
                        order.append('')
                    collected[''].append(rule)
            buf = ''
        # media 关闭时无需动作（分组已按 key 收集）
    else:
        buf += ch
    i += 1

out_parts = ['/* 原站企业版 oe-* 门户样式（括号感知提取，保留 @media） */\n']
for key in order:
    rules = collected[key]
    # 去重保序
    seen, uniq = set(), []
    for r in rules:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    if key == '':
        out_parts.append('\n'.join(uniq))
    else:
        out_parts.append(f'{key} {{\n' + '\n'.join(uniq) + '\n}')

out = '\n\n'.join(out_parts)
open(DST, 'w', encoding='utf-8').write(out)

# 自检：解析回读验证括号平衡 + 桌面规则存在
depth = 0
for ch in out:
    if ch == '{':
        depth += 1
    elif ch == '}':
        depth -= 1
desk_grid = re.search(r'(?<![\w-])oe-charts-row[^{]*\{[^}]*display:\s*grid', out)
print(f"规则输出 {len(out)//1024}KB, 括号平衡: {'✅' if depth == 0 else '❌ 差' + str(depth)}")
print(f"桌面 charts-row grid 规则: {'✅' if desk_grid else '❌'}")
