
# -*- coding: utf-8 -*-
"""Extract docx (paragraphs + tables w/ merges) and xlsx (cells + merges + formats).
READ-ONLY on source files."""
import sys, os, zipfile, json, re
from xml.etree import ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def q(tag): return W + tag

def para_text(p):
    """Concatenate w:t, insert tab for w:tab, break for w:br"""
    out = []
    for node in p.iter():
        t = node.tag
        if t == q('t'):
            out.append(node.text or '')
        elif t == q('tab'):
            out.append('\t')
        elif t == q('br'):
            out.append('\n')
    return ''.join(out)

def run_fmt(p):
    """detect bold/underline/italic/highlight across runs"""
    flags = set()
    for r in p.findall(q('r')):
        rPr = r.find(q('rPr'))
        if rPr is None: continue
        if rPr.find(q('b')) is not None: flags.add('B')
        if rPr.find(q('u')) is not None: flags.add('U')
        if rPr.find(q('i')) is not None: flags.add('I')
        if rPr.find(q('highlight')) is not None: flags.add('HL')
        if rPr.find(q('color')) is not None:
            c = rPr.find(q('color')).get(q('val'))
            if c and c not in ('auto','000000','FFFFFF'): flags.add('C:'+c)
    return ''.join(sorted(flags))

def style_of(p):
    pPr = p.find(q('pPr'))
    if pPr is None: return ''
    ps = pPr.find(q('pStyle'))
    if ps is None:
        # maybe numPr
        npr = pPr.find(q('numPr'))
        if npr is not None: return '[numbered]'
        return ''
    v = ps.get(q('val'))
    npr = pPr.find(q('numPr'))
    if npr is not None: v += '+numbered'
    return v or ''

def para_indent(p):
    pPr = p.find(q('pPr'))
    if pPr is None: return ''
    ind = pPr.find(q('ind'))
    if ind is None: return ''
    l = ind.get(q('left')) or ind.get(q('start')) or ''
    f = ind.get(q('firstLine')) or ''
    return ('ind:l=' + l + ',f=' + f) if (l or f) else ''

def table_struct(tbl, tidx):
    rows = []
    for r in tbl.findall(q('tr')):
        cells = []
        for c in r.findall(q('tc')):
            tcPr = c.find(q('tcPr'))
            span = 1; vmerge = ''
            gridspan = None
            if tcPr is not None:
                gs = tcPr.find(q('gridSpan'))
                if gs is not None:
                    span = int(gs.get(q('val')) or '1'); gridspan = span
                vm = tcPr.find(q('vMerge'))
                if vm is not None:
                    vmerge = vm.get(q('val')) or 'continue'
            # gather all text inside cell (paragraphs w/ newline)
            ps = []
            for p in c.findall(q('p')):
                ps.append(para_text(p))
            txt = '\n'.join([x for x in ps])
            cells.append({'text': txt, 'colspan': span, 'vmerge': vmerge})
        rows.append(cells)
    return rows

def parse_docx(path):
    z = zipfile.ZipFile(path)
    xml = z.read('word/document.xml')
    root = ET.fromstring(xml)
    body = root.find(q('body'))
    out = []
    p_idx = 0; t_idx = 0
    for child in body:
        if child.tag == q('p'):
            p_idx += 1
            txt = para_text(child)
            st = style_of(child); fm = run_fmt(child); ind = para_indent(child)
            if txt.strip() == '' and not st:
                continue
            out.append({'kind':'P','n':p_idx,'style':st,'fmt':fm,'ind':ind,'text':txt})
        elif child.tag == q('tbl'):
            t_idx += 1
            rows = table_struct(child, t_idx)
            out.append({'kind':'TBL','n':t_idx,'rows':rows})
    # sections / headers footers
    extra = {}
    for name in z.namelist():
        if re.match(r'word/(header|footer)\d*\.xml', name):
            try:
                r2 = ET.fromstring(z.read(name))
                txts = [para_text(p) for p in r2.iter(q('p'))]
                txts = [x for x in txts if x.strip()]
                if txts: extra[name] = txts
            except Exception as e:
                extra[name] = ['<err %s>' % e]
    return out, extra

def fmt_docx(path, dest):
    out, extra = parse_docx(path)
    lines = []
    lines.append('='*100)
    lines.append('FILE: %s' % os.path.basename(path))
    lines.append('SIZE: %d bytes' % os.path.getsize(path))
    lines.append('='*100)
    nP = sum(1 for b in out if b['kind']=='P'); nT = sum(1 for b in out if b['kind']=='TBL')
    lines.append('ELEMENTS: %d paragraphs, %d tables' % (nP, nT))
    if extra:
        lines.append('HEADERS/FOOTERS:')
        for k,v in extra.items(): lines.append('  %s: %s' % (k, ' | '.join(v)))
    lines.append('')
    for b in out:
        if b['kind']=='P':
            meta = ' '.join(x for x in [b['style'], b['fmt'], b['ind']] if x)
            lines.append('[P%03d]%s %s' % (b['n'], (' <%s>'%meta) if meta else '', b['text']))
        else:
            lines.append('')
            lines.append('----- TABLE %d : %d rows -----' % (b['n'], len(b['rows'])))
            for ri, row in enumerate(b['rows'], 1):
                parts = []
                for ci, c in enumerate(row, 1):
                    tag = ''
                    if c['colspan'] > 1: tag += '(span%d)' % c['colspan']
                    if c['vmerge'] == 'continue': tag += '(vmerge-cont)'
                    elif c['vmerge'] == 'restart': tag += '(vmerge-start)'
                    parts.append('c%d%s=%s' % (ci, tag, c['text'].replace('\n',' / ')))
                lines.append('  R%02d | %s' % (ri, ' || '.join(parts)))
            lines.append('----- END TABLE %d -----' % b['n'])
            lines.append('')
    open(dest,'w',encoding='utf-8').write('\n'.join(lines))
    return '%s -> %s (%d lines)' % (os.path.basename(path), dest, len(lines))

if __name__ == '__main__':
    src, dest = sys.argv[1], sys.argv[2]
    print(fmt_docx(src, dest))
