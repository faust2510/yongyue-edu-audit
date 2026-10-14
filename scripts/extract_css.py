#!/usr/bin/env python3
"""括号感知提取 CSS 规则（保留 @media 结构）。
用法: python3 scripts/extract_css.py <src> <dst> <pattern1,pattern2,...>
"""
import re
import sys


def extract(css: str, pat: re.Pattern):
    """返回 [(media_header_or_None, rule_text), ...] 按原顺序去重。"""
    results, seen = [], set()
    stack = []          # ('media', header) / ('sel', selector)
    buf = ''
    i, n = 0, len(css)
    while i < n:
        ch = css[i]
        if ch == ';':
            # 无块 at-rule（@import/@charset 等）直接丢弃
            if buf.strip().startswith('@'):
                buf = ''
            else:
                buf += ch
        elif ch == '{':
            sel = buf.strip()
            buf = ''
            if sel.startswith('@'):
                stack.append(('media', sel))
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
                rule = f'{val}{{{body}}}'
                if pat.search(val) and len(val) < 500 and rule not in seen:
                    seen.add(rule)
                    media = next((h for k, h in reversed(stack)
                                  if k == 'media'), None)
                    results.append((media, rule))
            buf = ''
        else:
            buf += ch
        i += 1
    return results


def main():
    src, dst, pats = sys.argv[1], sys.argv[2], sys.argv[3].split(',')
    pat = re.compile('|'.join(pats))
    css = open(src, encoding='utf-8', errors='ignore').read()
    results = extract(css, pat)

    out = [f'/* 括号感知提取 来源:{src} 规则数:{len(results)} */\n']
    last_media = None
    for media, rule in results:
        if media != last_media:
            if last_media is not None:
                out.append('}')
            if media:
                out.append(media + ' {\n')
            last_media = media
        out.append(rule + '\n')
    if last_media is not None:
        out.append('}')
    text = '\n'.join(out)
    open(dst, 'w', encoding='utf-8').write(text)

    depth = 0
    for c in text:
        depth += (c == '{') - (c == '}')
    status = 'OK' if depth == 0 else f'BRACE-DIFF {depth}'
    print(f'{dst}: {len(text)//1024}KB rules={len(results)} braces={status}')


if __name__ == '__main__':
    main()
