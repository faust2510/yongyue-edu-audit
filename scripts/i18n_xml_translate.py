# -*- coding: utf-8 -*-
"""门户 XML 模板汉化流水线：抽取英文文本节点/属性 → Bing 机翻（术语表覆盖）→ 回写。

设计要点：
- 抽取与回写都基于原始文本的正则替换，保留文件里的一切注释/缩进/属性顺序。
- 译文缓存落盘 scripts/i18n_cache.json，可断点续跑、零重复调用。
- 术语表 scripts/i18n_glossary.json 精确匹配优先于机翻。

用法：
  python3 scripts/i18n_xml_translate.py                # 干跑：只统计与预览
  python3 scripts/i18n_xml_translate.py --apply        # 实际写回文件
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLOSSARY_PATH = ROOT / 'scripts' / 'i18n_glossary.json'
CACHE_PATH = ROOT / 'scripts' / 'i18n_cache.json'
DEFAULT_FILES = [
    ROOT / 'custom_addons/edu_portal/views/batch1.xml',
    ROOT / 'custom_addons/edu_portal/views/batch2.xml',
    ROOT / 'custom_addons/edu_portal/views/batch3.xml',
]

TEXT_RE = re.compile(r'>([^<>]*[A-Za-z][^<>]*)<')
ATTR_RE = re.compile(
    r'(title|placeholder|alt|aria-label)="([^"<>]*[A-Za-z][^"<>]*)"')

SKIP_RE = re.compile(
    r'^[\s0-9%.,()\-/|:;]*$'           # 纯数字/符号
    r'|^https?://|^/@|^/web|^/my|^/student|^/library|^/course'
    r'|[\u4e00-\u9fff]'                # 已含中日韩字符
    r'|^oe-|^o_|^btn|^fa\b|^\.css|^\{|^\(|^t-|^@|^#'
)

CODE_RE = re.compile(r'(<script[\s\S]*?</script>|<style[\s\S]*?</style>)', re.I)

def load_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8')) if Path(p).exists() else {}

def save_cache(cache):
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=1), encoding='utf-8')

def clean(s):
    return re.sub(r'\s+', ' ', s).strip()

def is_candidate(s):
    raw = clean(s)
    if not raw or len(raw) > 200:
        return False
    if not re.search(r'[A-Za-z]{2}', raw):
        return False
    if SKIP_RE.search(raw):
        return False
    return True

def bing(text, glossary, cache):
    key = clean(text)
    if key in glossary:
        return glossary[key], 'glossary'
    if key in cache:
        return cache[key], 'cache'
    import translators as ts
    for attempt in range(3):
        try:
            out = ts.translate_text(key, translator='bing', to_language='zh-Hans')
            cache[key] = out
            save_cache(cache)
            time.sleep(0.4)
            return out, 'mt'
        except Exception as e:
            print('  MT retry %d (%s): %s' % (attempt + 1, key[:40], str(e)[:80]))
            time.sleep(1.5 * (attempt + 1))
    return None, 'failed'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='实际写回文件')
    ap.add_argument('--files', nargs='*', help='目标 XML 文件，默认 edu_portal views')
    args = ap.parse_args()

    files = [Path(f) for f in args.files] if args.files else DEFAULT_FILES
    glossary = {k: v for k, v in load_json(GLOSSARY_PATH).items()
                if not k.startswith('_')}
    cache = load_json(CACHE_PATH)

    mapping = {}   # 原文(去空白) -> 译文
    stats = {'glossary': 0, 'cache': 0, 'mt': 0, 'failed': 0}
    for f in files:
        raw = f.read_text(encoding='utf-8')
        segments = CODE_RE.split(raw)
        text_segs = [s for i, s in enumerate(segments) if i % 2 == 0]
        cands = set()
        for seg in text_segs:
            for m in TEXT_RE.finditer(seg):
                if is_candidate(m.group(1)):
                    cands.add(clean(m.group(1)))
            for m in ATTR_RE.finditer(seg):
                if is_candidate(m.group(2)):
                    cands.add(clean(m.group(2)))
        print('%s: %d candidates' % (f.relative_to(ROOT), len(cands)))
        for c in sorted(cands):
            out, how = bing(c, glossary, cache)
            stats[how] += 1
            if out:
                mapping[c] = out
            else:
                print('  FAILED: %s' % c)
    print('unique=%d  %s' % (len(mapping), stats))

    if not args.apply:
        for k in sorted(mapping)[:12]:
            print('  %s => %s' % (k, mapping[k]))
        print('(dry-run, 未写回；加 --apply 生效)')
        return

    # ---- 回写：按上下文构造精确替换对，避免误伤代码 ----
    def sub_text(m):
        inner = m.group(1)
        out = mapping.get(clean(inner))
        if not out:
            return m.group(0)
        lead = inner[:len(inner) - len(inner.lstrip())]
        trail = inner[len(inner.rstrip()):]
        return '>' + lead + out + trail + '<'

    def sub_attr(m):
        inner = m.group(2)
        out = mapping.get(clean(inner))
        if not out:
            return m.group(0)
        return '%s="%s"' % (m.group(1), out.replace('"', '&quot;'))

    for f in files:
        raw = f.read_text(encoding='utf-8')
        segments = CODE_RE.split(raw)
        out_parts = []
        for i, seg in enumerate(segments):
            if i % 2 == 1:   # script/style 原样保留
                out_parts.append(seg)
                continue
            new = TEXT_RE.sub(sub_text, seg)
            new = ATTR_RE.sub(sub_attr, new)
            out_parts.append(new)
        new = ''.join(out_parts)
        if new != raw:
            f.write_text(new, encoding='utf-8')
            print('WROTE %s' % f.relative_to(ROOT))

if __name__ == '__main__':
    sys.exit(main())
