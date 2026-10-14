#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户评估缺口验收（2026-09-29）：矩阵区名分组 / 被评教师历程 / 家长看孩子。

三块被测对象（custom_addons/edu_assess）：
  M. 矩阵表头：/assess/grade/<task> 的评分列表头加「区名（一级分组）」行 ——
     三层模板里跨区同名项（窗户有灰尘/污渍 ×3 …）靠它才分得出是哪一列。
     xlsx 侧早已用「区名 / 项名」列头（controllers/portal.py 的 _item_label），
     页面侧此前只写裸项名。
  T. 教师历程：GET /assess/faculty/history —— 被评教师本人的历次评估（跨任务、时间序）。
  P. 家长看孩子：/my/child 内嵌「孩子的评估」+ GET /assess/child/<id>/history。

判据纪律（照 tests/smoke/assess_history.py 与 docs/dev-workflow.md）：
  · 正向断言必须与**库读数**对照（SQL 的树/计数 vs 页面结构），不是页面看着有东西；
  · 每条负向断言都配**正对照**（控制组：该拿的人拿得到）；
  · 「页面没显示」不算越权证明 —— 越权还要证明**数据层**拿不到（JSON-RPC 直读）；
  · 空态必须与库读数同时成立，且不许编造。

用法：
    python3 tests/smoke/assess_portal_gaps.py            # 全量（建夹具 → 断言 → 清场）
    python3 tests/smoke/assess_portal_gaps.py --keep     # 跑完保留夹具（排查用）
    python3 tests/smoke/assess_portal_gaps.py --only m   # 只跑某一段（反向注入窗口用）
退出码：0=全绿；1=有断言失败；2=运行错误（站点不可达 / 夹具建不起来 / 库读不到）。
结果落盘：tests/smoke/assess_portal_gaps_results.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

BASE = os.environ.get('SMOKE_BASE', 'http://localhost:8069')
DB = 'edu19'
DB_CONTAINER = os.environ.get('EDU_DB_CONTAINER', 'edu19-clone-db-1')
HERE = Path(__file__).resolve().parent
RESULTS = HERE / 'assess_portal_gaps_results.json'
PASSWORD = 'demo123'

# 夹具命名（清场只按这些前缀，绝不动既有数据）
MARK = '【门户缺口验收】'
PERIOD = 'GAP-'
PARENT_B_LOGIN = 'gap-parent-b@local'
PARENT_B_NAME = MARK + '家长B'
CHILD_B_NAME = MARK + '孩子B'
CHILD_C_NAME = MARK + '孩子C'  # 家长 B 的第二个孩子：只用来验「诚实空态」
FAC_B_LOGIN = 'gap-fac-b@local'
FAC_B_NAME = MARK + '教师乙'

# 跨区同名项（照素材《卫生检测表》的形态；一层区名 + 二层分类名 = 两条分组行）
TREE = [
    ('厨房', [('清洁', [('窗户有灰尘/污渍', 2.0), ('灶台油渍', 5.0)]),
              ('垃圾', [('垃圾未倒', 4.0)])]),
    ('卧室', [('清洁', [('窗户有灰尘/污渍', 2.0)]),
              ('垃圾', [('垃圾未倒', 4.0), ('床铺不整', 3.0)])]),
    ('阳台', [('清洁', [('窗户有灰尘/污渍', 2.0)])]),
]
#: 扁平模板（控制组：改动前后逐字节一致）
FLAT_ITEMS = [('平铺项甲', 3.0), ('平铺项乙', 4.0)]

OK, FAIL = 'PASS', 'FAIL'
items = []


def check(no, name, cond, detail=''):
    verdict = OK if cond else FAIL
    items.append({'no': no, 'name': name, 'pass': bool(cond),
                  'detail': str(detail)[:900]})
    print('  %-4s #%-5s %-58s %s' % (verdict, no, name, str(detail)[:180]))
    return bool(cond)


def die(msg):
    print('CANNOT: %s' % msg)
    json.dump({'error': msg, 'items': items}, open(RESULTS, 'w'),
              ensure_ascii=False, indent=1)
    sys.exit(2)


def psql(sql):
    out = subprocess.run(
        ['docker', 'exec', DB_CONTAINER, 'psql', '-U', 'odoo', '-d', DB,
         '-tAc', sql], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError('psql: %s' % (out.stderr or '')[:300])
    return out.stdout.strip()


def psql_int(sql):
    try:
        return int(psql(sql) or 0)
    except ValueError:
        raise RuntimeError('psql 返回非整数: %r' % psql(sql)[:200])


def login(login_name, password=PASSWORD):
    s = requests.Session()
    s.trust_env = False
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': DB, 'login': login_name, 'password': password}},
        timeout=30)
    data = r.json().get('result') or {}
    return (s if data.get('uid') else None), data.get('uid')


def call_kw(sess, model, method, args=None, kwargs=None):
    payload = {'jsonrpc': '2.0', 'method': 'call', 'params': {
        'model': model, 'method': method,
        'args': args or [], 'kwargs': kwargs or {}}}
    r = sess.post(BASE + '/web/dataset/call_kw', json=payload, timeout=60)
    try:
        data = r.json()
    except Exception:
        return None, 'HTTP %s（非 JSON）' % r.status_code
    if 'error' in data:
        err = data['error']
        info = err.get('data') or {}
        return None, '%s: %s' % (
            info.get('name') or 'Error',
            (info.get('message') or err.get('message') or '')[:200])
    return data.get('result'), None


def rpc_create(sess, model, vals):
    res, err = call_kw(sess, model, 'create', [vals])
    if err:
        raise RuntimeError('%s.create 失败：%s' % (model, err))
    return res[0] if isinstance(res, list) else res


def search(sess, model, domain, fields=('id',), limit=0):
    res, err = call_kw(sess, model, 'search_read', [domain],
                       {'fields': list(fields), 'limit': limit})
    return (res or []), err


def unlink(sess, model, ids):
    if not ids:
        return
    _res, err = call_kw(sess, model, 'unlink', [list(ids)])
    if err:
        print('      （清场 %s %s 失败：%s）' % (model, ids, err))


def get(sess, path):
    r = sess.get(BASE + path, timeout=40, allow_redirects=True)
    return r, (r.text or '')


def table_seg(html, table_id):
    """取某张表在 HTML 里的片段（含表头）。"""
    i = (html or '').find('id="%s"' % table_id)
    if i < 0:
        return ''
    j = html.find('</table>', i)
    return html[i:j if j > 0 else len(html)]


def parse_head(seg):
    """<thead> → [[(tag, attrs, text), ...], ...]（一行一组）。"""
    m = re.search(r'<thead[^>]*>(.*?)</thead>', seg or '', re.S)
    if not m:
        return []
    rows = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(1), re.S):
        cells = []
        for tag, attrs, inner in re.findall(r'<(th|td)([^>]*)>(.*?)</\1>',
                                            tr, re.S):
            text = re.sub(r'<[^>]+>', '', inner).strip()
            cells.append((tag, attrs.strip(), text))
        rows.append(cells)
    return rows


def _span(attrs, name):
    m = re.search(name + r'="(\d+)"', attrs or '')
    return int(m.group(1)) if m else 1


def head_grid(rows):
    """按 HTML 表格规则把 thead 展开成网格：grid[r][c] = (tag, attrs, text) 或 None。"""
    span_occ = {}
    for r, cells in enumerate(rows):
        c = 0
        for tag, attrs, text in cells:
            while (r, c) in span_occ:
                c += 1
            cs, rs = _span(attrs, 'colspan'), _span(attrs, 'rowspan')
            for i in range(cs):
                for rr in range(r, r + rs):
                    span_occ[(rr, c + i)] = (tag, attrs, text)
            c += cs
    width = max([max(k[1] for k in span_occ) + 1] if span_occ else [0])
    grid = [[span_occ.get((r, c)) for c in range(width)]
            for r in range(len(rows))]
    return grid

def head_item_columns(grid, header_rows, lead=None):
    """(列序号, 分组链, 项名)：分组链 = 该列上方所有 td 格（按行自上而下）。

    lead = 行标签列（学生 / 被评对象）的文案：那一列是**行头**不是评分项列，
    剔除它 —— 口径与 assess_task_portal H1.1 的 heads[1:] 一致。
    """
    out = []
    width = len(grid[0]) if grid else 0
    for c in range(width):
        cells = [grid[r][c] for r in range(header_rows)]
        if not cells[-1] or cells[-1][0] != 'th':
            continue
        if 'scope="colgroup"' in (cells[-1][1] or ''):
            continue          # 分组格自己不是评分列
        if lead and cells[-1][2] == lead:
            continue          # 行标签列（学生 / 被评对象）
        # 分组链 = 该列上方所有 scope="colgroup" 的格（自上而下）
        chain = [t for _tag, a, t in cells[:-1]
                 if a and 'scope="colgroup"' in a and t]
        out.append((c, chain, cells[-1][2]))
    return out


def th_texts(seg):
    """表内所有 <th> 的纯文本（**含**分组格 —— 只用来做"裸名重复"这类原始读数）。"""
    return [re.sub(r'<[^>]+>', '', t).strip()
            for t in re.findall(r'<th[^>]*>(.*?)</th>', seg or '', re.S)]


def scoring_heads(seg):
    """<thead> 里的**评分列**名 —— 口径与 tests/smoke/assess_task_portal.py 的 H1.1
    逐字一致：取最后一行、排除 scope="colgroup" 的分组格、再去掉行标签列。

    为什么两处必须同口径：分组表头上线后，原始 <th> 数 = 叶子数 + 分组格数；
    H1.1 守的是「分组节点不得成为评分列」，所以两边都按「评分列」数。
    """
    thead = re.search(r'<thead[^>]*>(.*?)</thead>', seg or '', re.S)
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>',
                      thead.group(1) if thead else '', re.S)

    def cells(tr):
        return [(tag, attrs, re.sub(r'<[^>]+>', '', inner).strip())
                for tag, attrs, inner in
                re.findall(r'<(th|td)([^>]*)>(.*?)</\1>', tr, re.S)]

    first = cells(rows[0]) if rows else []
    label = first[0][2] if first else ''
    return [t for tag, attrs, t in (cells(rows[-1]) if rows else [])
            if tag == 'th' and 'scope="colgroup"' not in attrs and t != label]


# ----------------------------------------------------------------------
# 夹具
# ----------------------------------------------------------------------

def cleanup(adm, verbose=True, skip=False):
    """按夹具前缀/名字清场（幂等：跑两次读数一致）；skip=True 保留夹具（--keep）。"""
    if skip:
        return
    tpls, _e = search(adm, 'edu.assess.template',
                      [('name', 'like', MARK + '%')])
    tpl_ids = [t['id'] for t in tpls]
    tasks, _e = search(adm, 'edu.assess.task',
                       [('period', 'like', PERIOD + '%')])
    task_ids = [t['id'] for t in tasks]
    items_, _e = search(adm, 'edu.assess.item',
                        [('template_id.name', 'like', MARK + '%')])
    item_ids = [i['id'] for i in items_]
    if task_ids:
        scores, _e = search(adm, 'edu.assess.score',
                            [('task_id', 'in', task_ids)])
        unlink(adm, 'edu.assess.score', [s['id'] for s in scores])
        rosters, _e = search(adm, 'edu.assess.roster',
                             [('task_id', 'in', task_ids)])
        unlink(adm, 'edu.assess.roster', [r['id'] for r in rosters])
    unlink(adm, 'edu.assess.task', task_ids)
    unlink(adm, 'edu.assess.item', item_ids)
    unlink(adm, 'edu.assess.template', tpl_ids)
    # 家长 B（账号 → op.parent → 孩子 → 伙伴），顺序 = 先解除引用再删
    pars, _e = search(adm, 'op.parent', [('name.name', '=', PARENT_B_NAME)],
                      ('id', 'name', 'student_ids', 'user_id'))
    for p in pars:
        unlink(adm, 'op.parent', [p['id']])
        pid = (p.get('name') or [False])[0]
        uid = (p.get('user_id') or [False])[0]
        unlink(adm, 'res.users', [uid] if uid else [])
        unlink(adm, 'res.partner', [pid] if pid else [])
    kids, _e = search(adm, 'op.student',
                      [('name', 'in', [CHILD_B_NAME, CHILD_C_NAME])],
                      ('id', 'partner_id'))
    for k in kids:
        pid = (k.get('partner_id') or [False])[0]
        unlink(adm, 'op.student', [k['id']])
        unlink(adm, 'res.partner', [pid] if pid else [])
    # 教师 B 夹具：账号 → op.faculty（_inherits 委托，删它会一并删掉它的伙伴）
    us, _e = search(adm, 'res.users', [('login', '=', FAC_B_LOGIN)])
    for u in us:
        unlink(adm, 'res.users', [u['id']])
    facs, _e = search(adm, 'op.faculty', [('name', '=', FAC_B_NAME)], ('id',))
    for f in facs:
        unlink(adm, 'op.faculty', [f['id']])
    if verbose:
        print('    ... 清场：模板 %d / 任务 %d / 评分项 %d / 家长 %d / 孩子 %d / 教师 %d'
              % (len(tpl_ids), len(task_ids), len(item_ids), len(pars),
                 len(kids), len(facs)))


def build_template(adm, name, tree, flat=None, score_visible=True,
                   target='student'):
    """建模板：tree = [(区, [(分类, [(项, 扣分额)])])]；序列号与 id 同序（真实建表口径）。"""
    tpl = rpc_create(adm, 'edu.assess.template', {
        'name': name, 'kind': 'other', 'target_kind': target,
        'total': 100.0, 'pass_line': 60.0, 'excellent_line': 90.0,
        'weight_mode': 'multiplier', 'state': 'active',
        'score_visible': score_visible})
    leaves = []
    for area, subs in (tree or []):
        gid = rpc_create(adm, 'edu.assess.item', {
            'template_id': tpl, 'name': area, 'item_kind': 'group',
            'sequence': 10})
        for sname, checks in subs:
            sid = rpc_create(adm, 'edu.assess.item', {
                'template_id': tpl, 'parent_id': gid, 'name': sname,
                'item_kind': 'group', 'sequence': 10})
            for cname, ded in checks:
                iid = rpc_create(adm, 'edu.assess.item', {
                    'template_id': tpl, 'parent_id': sid, 'name': cname,
                    'item_kind': 'leaf', 'score_mode': 'deduct',
                    'max_score': ded, 'weight': 1.0, 'sequence': 10})
                leaves.append((area, sname, cname, iid))
    for cname, mx in (flat or []):
        iid = rpc_create(adm, 'edu.assess.item', {
            'template_id': tpl, 'name': cname, 'item_kind': 'leaf',
            'max_score': mx, 'weight': 1.0, 'sequence': 10})
        leaves.append(('', '', cname, iid))
    return tpl, leaves


def expected_columns(tpl):
    """库里的**列序与祖先链**（判据的对照面）：[(项名, [区, 分类])]。"""
    rows = psql("with recursive up as ("
                " select i.id leaf_id, i.id node_id, i.name, i.parent_id, 1 lvl"
                " from edu_assess_item i where i.template_id = %d and i.item_kind = 'leaf'"
                " union all"
                " select up.leaf_id, p.id, p.name, p.parent_id, up.lvl + 1"
                " from edu_assess_item p join up on p.id = up.parent_id)"
                " select leaf_id || '|' || lvl || '|' || coalesce(name, '')"
                " from up order by leaf_id, lvl desc" % tpl)
    chains = {}
    for line in rows.splitlines():
        if not line.strip():
            continue
        leaf, _lvl, name = line.split('|', 2)
        chains.setdefault(int(leaf), []).append(name)
    order = psql('select id from edu_assess_item where template_id = %d '
                 "and item_kind = 'leaf' order by sequence, id" % tpl)
    out = []
    for line in order.splitlines():
        if not line.strip():
            continue
        lid = int(line)
        chain = chains.get(lid) or []
        out.append((chain[-1] if chain else '', chain[:-1]))
    return out

# ----------------------------------------------------------------------
# M 矩阵表头：区名分组
# ----------------------------------------------------------------------

def section_m(adm, bo, stu):
    print('\n== M 矩阵表头：区名分组（跨区同名项可分）==')
    tpl, leaves = build_template(adm, MARK + '卫生检测表（三层·区名）', TREE)
    flat_tpl, flat_leaves = build_template(adm, MARK + '扁平控制组', None, FLAT_ITEMS)
    sids = [int(x) for x in psql('select id from op_student where active order by id limit 2').splitlines() if x.strip()]
    tid = rpc_create(adm, 'edu.assess.task', {
        'template_id': tpl, 'period': PERIOD + '矩阵表头', 'state': 'open',
        'scorer_kind': 'teacher'})
    for sid in sids:
        rid = rpc_create(adm, 'edu.assess.roster',
                         {'task_id': tid, 'student_id': sid})
        for _a, _s, _c, iid in leaves:
            rpc_create(adm, 'edu.assess.score', {
                'task_id': tid, 'roster_id': rid, 'item_id': iid,
                'value': 1.0, 'scorer_ref': 'i:2', 'track': 'objective'})
    flat_tid = rpc_create(adm, 'edu.assess.task', {
        'template_id': flat_tpl, 'period': PERIOD + '扁平控制组',
        'state': 'open', 'scorer_kind': 'teacher'})
    rpc_create(adm, 'edu.assess.roster',
               {'task_id': flat_tid, 'student_id': sids[0]})
    print('    夹具：三层模板 %d / 任务 %d（%d 叶子）；扁平模板 %d / 任务 %d'
          % (tpl, tid, len(leaves), flat_tpl, flat_tid))

    r, html = get(bo, '/assess/grade/%d' % tid)
    seg = table_seg(html, 'yy-assess-grade-table')
    rows = parse_head(seg)
    n_leaf = len(leaves)
    check('M1a', '整班打分页 200 且拿到矩阵表（不是被弹走）',
          r.status_code == 200 and bool(seg),
          'HTTP %s ｜ 表片段 %d 字' % (r.status_code, len(seg)))
    ths = th_texts(seg)
    dup = sorted(set(n for n in ths if ths.count(n) > 1))
    n_win = ths.count('窗户有灰尘/污渍')
    check('M1b', '反向基线：裸 <th> 里「窗户有灰尘/污渍」出现多次，只看 <th> 文本分不出是哪一列',
          n_win >= 3, '同名 <th> 次数 = %d ｜ 重复文本 = %s' % (n_win, dup))

    groups = [a for a, _c in TREE] + [s for _a, subs in TREE for s, _c in subs]
    grid = head_grid(rows)
    cols = head_item_columns(grid, len(rows), lead='学生')
    exp = expected_columns(tpl)
    check('M2a', '表头列数 == 库里的叶子数（%d）' % n_leaf,
          len(cols) == n_leaf == len(exp),
          '页面列 %d ｜ 库叶子 %d ｜ 期望列 %d' % (len(cols), n_leaf, len(exp)))
    check('M2b', '逐列比对：每列的分组链 == 库里祖先链（区 → 分类）',
          [c[1] for c in cols] == [e[1] for e in exp],
          '页面链 %s ｜ 库里链 %s' % ([c[1] for c in cols], [e[1] for e in exp]))
    check('M2c', '逐列比对：项名与列序 == 库 order by sequence, id',
          [c[2] for c in cols] == [e[0] for e in exp],
          '页面项名 %s ｜ 库里项名 %s' % ([c[2] for c in cols], [e[0] for e in exp]))
    same = [(c, ch) for c, ch, n in cols if n == '窗户有灰尘/污渍']
    check('M2d', '同名项可分：3 个「窗户有灰尘/污渍」的分组链两两不同',
          len(same) == 3 and len(set(tuple(ch) for _c, ch in same)) == 3,
          '列→链 = %s' % [(c + 1, ch) for c, ch in same])
    group_cells = [(tag, a, t) for c2 in rows[:-1] for tag, a, t in c2
                   if t not in ('学生', '被评对象')]
    check('M2e', '分组格是 <th scope="colgroup" colspan>（读屏用户靠它拿分组语义）',
          bool(group_cells)
          and all(tag == 'th' and 'scope="colgroup"' in a
                  for tag, a, _t in group_cells),
          '分组格 = %s' % group_cells[:4])

    heads = scoring_heads(seg)
    check('M4a', '既有契约（H1.1 改口径后逐字同源）：**评分列**数 == 叶子数',
          len(heads) == n_leaf and len(cols) == len(heads),
          '评分列 %d 个 / 叶子 %d 个 ｜ 原始 <th> %d 个（= 评分列 + 分组格）'
          % (len(heads), n_leaf, len(ths)))
    leaf_names = set(e[0] for e in exp)
    stray = [t for c2 in rows for tag, a, t in c2
             if tag == 'th' and 'scope="colgroup"' not in (a or '')
             and t not in ('学生', '被评对象') and t not in leaf_names]
    check('M4b', '既有契约：表头里非 colgroup 的格全是叶子项名（分组节点没变成列）',
          not any(g in heads for g in groups) and not stray,
          '混入的分组名 = %s ｜ 非叶子的表头格 = %s'
          % ([g for g in groups if g in heads], stray or '无'))
    # 原始 <th> 匹配数 = 1（`<thead ...>` 自身也命中 <th[^>]*>，于是它和它后面第一个
    # `</th>` 里的行标签格被并成一条）+ 评分列 + 分组格 —— 这就是旧口径「掐掉第 1 个」
    # 的来历；新口径不再依赖那个巧合（见 scoring_heads 的注释）。
    check('M4c', '形态记录：原始 <th> 数 = 1（thead 前缀并掉行标签）+ 评分列 + 分组格',
          len(ths) == 1 + len(heads) + len(group_cells),
          '原始 <th> %d = 1 + 评分列 %d + 分组格 %d'
          % (len(ths), len(heads), len(group_cells)))

    r2, html2 = get(bo, '/assess/task/%d/results' % tid)
    seg2 = table_seg(html2, 'yy-assess-result-table')
    rows2 = parse_head(seg2)
    cols2 = head_item_columns(head_grid(rows2), len(rows2), lead='被评对象')
    check('M5a', '结果页同样带分组行（同一子模板，逐列链与库一致）',
          len(rows2) == 3 and [c[1] for c in cols2] == [e[1] for e in exp],
          'HTTP %s ｜ 表头 %d 行 ｜ 前 3 列链 %s'
          % (r2.status_code, len(rows2), [c[1] for c in cols2][:3]))

    r3, html3 = get(bo, '/assess/grade/%d' % flat_tid)
    seg3 = table_seg(html3, 'yy-assess-grade-table')
    rows3 = parse_head(seg3)
    flat_cells = [(t, a, x) for t, a, x in (rows3[0] if rows3 else [])]
    want = [('th', 'style="min-width:120px"', '学生')]
    want += [('th', 'title=""', n) for n, _m in FLAT_ITEMS]
    check('M3a', '控制组：扁平模板表头只有一行（不加分组行）', len(rows3) == 1,
          '表头 %d 行' % len(rows3))
    check('M3b', '控制组：扁平表头逐格逐属性 == 改动前的标记（名称 + title 空串）',
          flat_cells == want, '实际 %s ｜ 期望 %s' % (flat_cells, want))
    thead3 = re.search(r'<thead[^>]*>.*?</thead>', seg3, re.S)
    check('M3c', '控制组：扁平 <thead> 里一个 <td> 都没有',
          bool(thead3) and '<td' not in thead3.group(0),
          'thead 长度 %d' % (len(thead3.group(0)) if thead3 else -1))

    return {'tid': tid, 'tpl': tpl, 'flat_tid': flat_tid, 'sids': sids}

# ----------------------------------------------------------------------
# T 被评教师本人的历程
# ----------------------------------------------------------------------

def fac_of_login(login_name):
    """登录名 → op.faculty id（两条链都查：partner.user_id ∪ partner.user_ids）。"""
    sql = ("select f.id from op_faculty f join res_partner p on p.id = f.partner_id "
           "where p.user_id = (select id from res_users where login = '%s') "
           "or exists (select 1 from res_users u where u.partner_id = p.id "
           "and u.login = '%s') limit 1" % (login_name, login_name))
    raw = psql(sql)
    return int(raw) if raw.strip().isdigit() else None


def cell_numbers(html):
    """页面里出现的数字（严格单元格匹配：只看 <td>/<b>/<span> 这类格的纯数字内容）。"""
    nums = set()
    for cell in re.findall(r'>([^<>]{1,20})<', html or ''):
        cell = cell.strip()
        if re.fullmatch(r'-?\d+(\.\d+)?', cell):
            nums.add(float(cell))
    return nums


def sql_fac_rows(fac_id):
    return psql_int("select count(*) from edu_assess_roster r "
                    "join edu_assess_task t on t.id = r.task_id "
                    "where r.faculty_id = %d and t.state = 'closed' "
                    "and t.period like '%s%%'" % (fac_id, PERIOD))

def section_t(adm, bo, stu, par, fac):
    print('\n== T 被评教师本人的历程 /assess/faculty/history ==')
    fac_a = fac_of_login('faculty@local')
    if not fac_a:
        die('找不到 op.faculty（faculty@local=%s）' % fac_a)
    # 教师 B 用**夹具**而不是 fac@local：实测 fac@local(uid 9) 的口令不是 demo123，
    # 登不进去（Access Denied）—— 拿一个登不进的账号做越权对照等于没做。
    gid_fac = int(psql("select res_id from ir_model_data where module = "
                       "'openeducat_core' and name = 'group_op_faculty'"))
    rpc_create(adm, 'op.faculty', {'name': FAC_B_NAME, 'first_name': '缺口',
                                   'last_name': '教师乙',
                                   'birth_date': '1980-01-01', 'gender': 'male'})
    recs, _e = search(adm, 'op.faculty', [('name', '=', FAC_B_NAME)],
                      ('id', 'partner_id'))
    if not recs:
        die('教师 B 夹具没建起来')
    fac_b = recs[0]['id']
    partner_b = (recs[0].get('partner_id') or [False])[0]
    rpc_create(adm, 'res.users', {
        'name': FAC_B_NAME, 'login': FAC_B_LOGIN, 'password': PASSWORD,
        'partner_id': partner_b, 'group_ids': [(6, 0, [gid_fac])]})
    fac2, _uid = login(FAC_B_LOGIN)
    if not fac2:
        die('教师 B 夹具账号登不进去（%s）' % FAC_B_LOGIN)
    print('    教师 A = op.faculty %d（faculty@local）｜教师 B = op.faculty %d（夹具 %s）'
          % (fac_a, fac_b, FAC_B_LOGIN))

    # 夹具分两套口径：
    #   · 三层 TREE 模板 → 只为 T6a（学生填评教页的分组表头结构）；
    #   · 计分模板（加法制、满分 100）→ 历程页的分数断言要用得上简单可读的数字
    #     （扣分制项的值 = 扣分额，37 这种值会被模型当场拒掉）。
    tpl, leaves = build_template(adm, MARK + '评教（三层·公开）', TREE, target='faculty')
    tpl_vis, leaves_vis = build_template(adm, MARK + '评教（可见·计分）', None,
                                         [('评教总分', 100.0)], target='faculty')
    tpl_hid, flat_hid = build_template(adm, MARK + '评教（不公开）', None,
                                       [('评教总分', 100.0)], score_visible=False,
                                       target='faculty')
    tpl_anon, flat_anon = build_template(adm, MARK + '评教（匿名）', None,
                                        [('评教总分', 100.0)], target='faculty')

    def mk_task(tpl_id, period, state, anonymous=False):
        return rpc_create(adm, 'edu.assess.task', {
            'template_id': tpl_id, 'period': period, 'state': state,
            'scorer_kind': 'student', 'anonymous': anonymous,
            'summary_min': 3})

    def add_row(tid, fac_id, item_id, value, ref='u:8'):
        rid = rpc_create(adm, 'edu.assess.roster',
                         {'task_id': tid, 'faculty_id': fac_id, 'state': 'done'})
        rpc_create(adm, 'edu.assess.score', {
            'task_id': tid, 'roster_id': rid, 'item_id': item_id,
            'value': value, 'scorer_ref': ref})
        return rid

    task_vis = mk_task(tpl_vis, PERIOD + 'T-可见', 'closed')
    task_hid = mk_task(tpl_hid, PERIOD + 'T-不公开', 'closed')
    task_anon = mk_task(tpl_anon, PERIOD + 'T-匿名', 'closed', anonymous=True)
    task_fill = mk_task(tpl, PERIOD + 'T-待填', 'open')
    add_row(task_vis, fac_a, leaves_vis[0][3], 37.0)
    add_row(task_hid, fac_a, flat_hid[0][3], 66.0)
    add_row(task_anon, fac_a, flat_anon[0][3], 88.0, ref='h:deadbeef')
    print('    夹具：任务 可见 %d / 不公开 %d / 匿名 %d / 待填 %d'
          % (task_vis, task_hid, task_anon, task_fill))

    # ---- 正向：教师 A 本人的历程 ----
    sql_rows = sql_fac_rows(fac_a)
    r, html = get(fac, '/assess/faculty/history')
    nums = cell_numbers(html)
    check('T1a', '教师本人 /assess/faculty/history → 200 且是本页',
          r.status_code == 200 and '/assess/faculty/history' in r.url
          and '教师评估历程' in html,
          'HTTP %s → %s' % (r.status_code, r.url))
    check('T1b', '同一个人的历次评估连在一页：库里有 %d 条已结束名单行，页面逐行对齐'
          % 3,
          sql_rows == 3 and all(p in html for p in
                                (PERIOD + 'T-可见', PERIOD + 'T-不公开', PERIOD + 'T-匿名')),
          'SQL 名单行 = %d ｜ 三个任务名都在页面 = %s'
          % (sql_rows, all(p in html for p in (PERIOD + 'T-可见',
                                            PERIOD + 'T-不公开', PERIOD + 'T-匿名'))))
    check('T2a', '可见任务的分数在页面上（37 分 / 满分 100；与库读数一致）',
          37.0 in nums and 100.0 in nums
          and psql_int('select round(value::numeric, 0)::int from edu_assess_score '
                       'where task_id = %d' % task_vis) == 37,
          '表内数字 %s ｜ SQL 该任务的分 = 37' % sorted(nums))
    check('T2b', 'score_visible=False 的任务：不下发数字（66 不在页面）',
          66.0 not in nums, '表内数字 %s' % sorted(nums))
    check('T2c', '且该行仍在、并给出理由（不是静默消失）',
          '本次评估结果不向被评者公开' in html, '理由文字在：%s'
          % ('本次评估结果不向被评者公开' in html))
    check('T2d', '匿名样本不足（1 份 < 门槛 3）：不下发数字（88 不在页面）',
          88.0 not in nums, '表内数字 %s' % sorted(nums))
    check('T2e', '控制组：66 / 88 确实在库里（不是没数据才看不到）',
          psql_int('select count(*) from edu_assess_score where task_id in (%d, %d)'
                   % (task_hid, task_anon)) == 2, '打分记录 = 2 条（各 1）')

    # ---- 空态：教师 B 此刻没有任何已结束的评教 ----
    b_rows = psql_int("select count(*) from edu_assess_roster r "
                      "join edu_assess_task t on t.id = r.task_id "
                      "where r.faculty_id = %d and t.state = 'closed'" % fac_b)
    r_b, html_b = get(fac2, '/assess/faculty/history')
    check('T3a', '空态：零名单行的教师 → 200 + 空态节点，且与库读数同时成立',
          r_b.status_code == 200 and 'yy-assess-history-empty' in html_b
          and b_rows == 0, 'HTTP %s ｜ 空态 %s ｜ SQL 行 = %d'
          % (r_b.status_code, 'yy-assess-history-empty' in html_b, b_rows))

    # ---- 反向：教师 A 读不到教师 B 的历程 ----
    task_b = mk_task(tpl_vis, PERIOD + 'T-B的', 'closed')
    add_row(task_b, fac_b, leaves_vis[0][3], 41.0, ref='u:9')
    _r_a, html_a2 = get(fac, '/assess/faculty/history')
    nums_a = cell_numbers(html_a2)
    check('T4a', 'A 的页面上没有 B 的分数（41）', 41.0 not in nums_a,
          'A 页面数字 %s' % sorted(nums_a))
    check('T4b', 'A 的页面上没有 B 的任务名',
          PERIOD + 'T-B的' not in html_a2,
          '含 B 任务名：%s' % (PERIOD + 'T-B的' in html_a2))
    _r_b2, html_b2 = get(fac2, '/assess/faculty/history')
    nums_b = cell_numbers(html_b2)
    check('T4c', '控制组：B 自己的页面看得到 41（不是对谁都不显示）',
          41.0 in nums_b, 'B 页面数字 %s' % sorted(nums_b))
    rows_ab, err_ab = search(fac, 'edu.assess.roster',
                             [('faculty_id', '=', fac_b)], limit=0)
    check('T4d', '数据层：A 用 JSON-RPC 直读 B 的名单行 → 0 行（行级规则收敛）',
          not err_ab and not rows_ab, 'rows=%s err=%s' % (len(rows_ab or []), err_ab))
    rows_bb, err_bb = search(fac2, 'edu.assess.roster',
                             [('faculty_id', '=', fac_b)], limit=0)
    check('T4e', '数据层正对照：B 直读自己的名单行 → ≥1 行（被评者本人可读）',
          not err_bb and len(rows_bb or []) >= 1,
          'rows=%s err=%s' % (len(rows_bb or []), err_bb))

    # ---- 既有契约 H5f 复刻 ----
    r6, _h6 = get(fac, '/assess/my/history')
    check('T5a', '既有契约（H5f）：教师请求 /assess/my/history → 仍弹回门户',
          '/assess/my/history' not in r6.url, 'HTTP %s → %s' % (r6.status_code, r6.url))
    r_s, _hs = get(stu, '/assess/faculty/history')
    r_p, _hp = get(par, '/assess/faculty/history')
    check('T5b', '学生与家长访问 /assess/faculty/history → 弹回门户（fail-closed）',
          '/assess/faculty/history' not in r_s.url
          and '/assess/faculty/history' not in r_p.url,
          'stu → %s ｜ par → %s' % (r_s.url, r_p.url))

    # ---- 学生填评教页也用同一份分组表头 ----
    rf, htmlf = get(stu, '/assess/fill/%d' % task_fill)
    segf = table_seg(htmlf, 'yy-assess-fill-table')
    rowsf = parse_head(segf)
    colsf = head_item_columns(head_grid(rowsf), len(rowsf), lead='被评对象')
    expf = expected_columns(tpl)
    check('T6a', '学生填评教页：同一份分组表头，逐列链与库一致',
          rf.status_code == 200 and len(rowsf) == 3
          and [c[1] for c in colsf] == [e[1] for e in expf],
          'HTTP %s ｜ 表头 %d 行 ｜ 前 3 列链 %s'
          % (rf.status_code, len(rowsf), [c[1] for c in colsf][:3]))
    return {'tpl': tpl, 'fac_a': fac_a, 'fac_b': fac_b, 'task_vis': task_vis,
            'task_hid': task_hid, 'task_anon': task_anon}

# ----------------------------------------------------------------------
# P 家长看孩子
# ----------------------------------------------------------------------

def section_p(adm, bo, stu, par, sids, par_uid):
    print('\n== P 家长看孩子（/my/child 内嵌 + /assess/child/<id>/history）==')
    # ---- 0) 绑定口径取证（先核实、不假设）----
    par_a = int(psql('select id from op_parent where user_id = %d limit 1' % par_uid))
    kids_a = [x for x in psql('select op_student_id from op_parent_op_student_rel '
                              'where op_parent_id = %d order by op_student_id'
                % par_a).splitlines() if x.strip()]
    print('    取证：op_parent %d（parent@local）→ student_ids = %s'
          % (par_a, kids_a))
    child_a = int(kids_a[0]) if len(kids_a) == 1 else 0
    check('P0a', '绑定唯一且可判定：家长 A 恰有 1 个孩子（op_parent_op_student_rel）',
          len(kids_a) == 1 and child_a > 0,
          'op_parent %d 的孩子 = %s' % (par_a, kids_a))

    # ---- 夹具：家长 B（新账号 + 2 个孩子）+ 已结束的评估 ----
    portal_gid = int(psql("select res_id from ir_model_data where module = 'base' "
                         "and name = 'group_portal'"))
    rel_id = int(psql('select id from op_parent_relationship limit 1'))
    partner_b = rpc_create(adm, 'res.partner', {'name': PARENT_B_NAME,
                                               'is_parent': True})
    uid_b = rpc_create(adm, 'res.users', {
        'name': PARENT_B_NAME, 'login': PARENT_B_LOGIN, 'password': PASSWORD,
        'group_ids': [(6, 0, [portal_gid])]})
    child_b = rpc_create(adm, 'op.student', {'name': CHILD_B_NAME, 'gender': 'm'})
    child_c = rpc_create(adm, 'op.student', {'name': CHILD_C_NAME, 'gender': 'f'})
    par_b = rpc_create(adm, 'op.parent', {
        'name': partner_b, 'user_id': uid_b, 'relationship_id': rel_id,
        'student_ids': [(6, 0, [child_b, child_c])]})
    par_b_sess, _uid = login(PARENT_B_LOGIN)
    if not par_b_sess:
        die('家长 B 账号建好了但登不进去（%s）' % PARENT_B_LOGIN)

    # 计分模板（加法制、满分 100）：扣分制项的值 = 扣分额，71/41 这种值会被模型当场拒掉。
    tpl, leaves = build_template(adm, MARK + '学生综合（公开）', None,
                                 [('综合总分', 100.0)])
    tpl_hid, leaves_hid = build_template(adm, MARK + '学生综合（不公开）', None,
                                         [('综合总分', 100.0)], score_visible=False)
    tid = rpc_create(adm, 'edu.assess.task', {
        'template_id': tpl, 'period': PERIOD + 'P-可见', 'state': 'closed',
        'scorer_kind': 'teacher'})
    tid_hid = rpc_create(adm, 'edu.assess.task', {
        'template_id': tpl_hid, 'period': PERIOD + 'P-不公开', 'state': 'closed',
        'scorer_kind': 'teacher'})
    for sid, val in ((child_a, 71.0), (child_b, 41.0)):
        rid = rpc_create(adm, 'edu.assess.roster',
                         {'task_id': tid, 'student_id': sid, 'state': 'done'})
        rpc_create(adm, 'edu.assess.score', {
            'task_id': tid, 'roster_id': rid, 'item_id': leaves[0][3],
            'value': val, 'scorer_ref': 'u:12'})
    rid_hid = rpc_create(adm, 'edu.assess.roster',
                         {'task_id': tid_hid, 'student_id': child_a,
                          'state': 'done'})
    rpc_create(adm, 'edu.assess.score', {
        'task_id': tid_hid, 'roster_id': rid_hid, 'item_id': leaves_hid[0][3],
        'value': 66.0, 'scorer_ref': 'u:12'})
    print('    夹具：家长 B(uid %s)/孩子 %d、%d；任务 可见 %d / 不公开 %d'
          % (uid_b, child_b, child_c, tid, tid_hid))

    # ---- 正向：家长 A 在既有页面看到自己孩子的评估 ----
    sql_a = psql_int("select count(*) from edu_assess_roster r "
                     "join edu_assess_task t on t.id = r.task_id "
                     "where r.student_id = %d and t.state = 'closed' "
                     "and t.period like '%s%%'" % (child_a, PERIOD))
    r, html = get(par, '/my/child')
    nums = cell_numbers(html)
    check('P1a', '家长 A /my/child → 200 且出现「评估历程」块（1 个孩子 = 1 块）',
          r.status_code == 200 and html.count('评估历程') == 1 and sql_a == 2,
          'HTTP %s ｜ 块数 %d ｜ SQL 该生已结束名单行 = %d'
          % (r.status_code, html.count('评估历程'), sql_a))
    check('P1b', '可见任务的分发数字在页面上（71 分 / 满分 100）',
          71.0 in nums, '页面数字 %s' % sorted(nums))
    check('P1c', '不公开的任务：不下发数字，但给出理由（66 不在页面）',
          66.0 not in nums and '本次评估结果不向孩子公开' in html,
          '数字 %s ｜ 理由在：%s' % (sorted(nums),
                                   '本次评估结果不向孩子公开' in html))
    check('P1d', '控制组：66 确实在库里（不是没数据才看不到）',
          psql_int('select count(*) from edu_assess_score where task_id = %d'
                   % tid_hid) == 1, '不公开任务的打分 = 1 条')
    # 孩子仪表盘（/my/child/<id>）：同一块评估数据也挂在这里（队长 2026-09-29 批准）
    r_dash, html_dash = get(par, '/my/child/%d' % child_a)
    nums_dash = cell_numbers(html_dash)
    check('P1e', '孩子仪表盘 /my/child/<id> 也挂上「评估历程」块（仪表盘主体一行未改）',
          r_dash.status_code == 200 and '评估历程' in html_dash
          and 71.0 in nums_dash and 66.0 not in nums_dash,
          'HTTP %s ｜ 块在 %s ｜ 数字 %s'
          % (r_dash.status_code, '评估历程' in html_dash, sorted(nums_dash)))

    # ---- 完整历程页：家长 A 看自己孩子 ----
    r2, html2 = get(par, '/assess/child/%d/history' % child_a)
    nums2 = cell_numbers(html2)
    check('P2a', '家长 A 看自己孩子的完整历程 → 200 且是本页',
          r2.status_code == 200 and '/assess/child/' in r2.url
          and '孩子的评估历程' in html2,
          'HTTP %s → %s' % (r2.status_code, r2.url))
    check('P2b', '页内数字与库读数一致（71 在，66 不在）',
          71.0 in nums2 and 66.0 not in nums2, '页面数字 %s' % sorted(nums2))

    # ---- 越权反向：家长 A → 家长 B 的孩子（页面层 + 数据层）----
    r3, html3 = get(par, '/assess/child/%d/history' % child_b)
    check('P3a', '家长 A 请求家长 B 的孩子历程 → 303 回 /my/child（不渲染该生）',
          r3.status_code == 200 and r3.url.endswith('/my/child'),
          'HTTP %s → %s' % (r3.status_code, r3.url))
    nums3 = cell_numbers(html3)
    check('P3b', '弹回后的响应里没有 B 的孩子的分数（41）与姓名',
          41.0 not in nums3 and CHILD_B_NAME not in html3,
          '数字 %s ｜ 含 B 孩子姓名：%s' % (sorted(nums3), CHILD_B_NAME in html3))
    r4, html4 = get(par, '/assess/child/%d/history' % child_c)
    check('P3c', '同上：家长 A → 家长 B 的第二个孩子，也弹回（不是漏判一个）',
          r4.url.endswith('/my/child') and CHILD_C_NAME not in html4,
          'HTTP %s → %s ｜ 含 C 姓名=%s'
          % (r4.status_code, r4.url, CHILD_C_NAME in html4))
    _r5, html5 = get(par, '/my/child')
    check('P3d', '家长 A 的 /my/child 里没有 B 的孩子姓名，也没有 B 的分数',
          CHILD_B_NAME not in html5 and 41.0 not in cell_numbers(html5),
          '含 B 孩子姓名=%s ｜ 含 41=%s' % (CHILD_B_NAME in html5,
                                            41.0 in cell_numbers(html5)))
    r_db, html_db = get(par, '/my/child/%d' % child_b)
    check('P3e', '家长 A → 家长 B 的孩子的**仪表盘**同样弹回（越权判据仍是父类那一份）',
          r_db.url.endswith('/my/child')
          and 41.0 not in cell_numbers(html_db)
          and CHILD_B_NAME not in html_db,
          'HTTP %s → %s ｜ 含 41=%s ｜ 含 B 孩子姓名=%s'
          % (r_db.status_code, r_db.url, 41.0 in cell_numbers(html_db),
             CHILD_B_NAME in html_db))
    rows_a, err_a = search(par, 'edu.assess.roster', [], limit=0)
    check('P4a', '数据层：家长 A 用 JSON-RPC 直读 edu.assess.roster → 被拒（门户 ACL = 0）',
          (err_a and 'Access' in err_a) or not rows_a,
          'rows=%s err=%s' % (len(rows_a or []), (err_a or '—')[:70]))
    rows_b, err_b = search(par_b_sess, 'edu.assess.score', [], limit=0)
    check('P4b', '数据层：家长 B 直读 edu.assess.score 同样被拒（门户整体闭）',
          (err_b and 'Access' in err_b) or not rows_b,
          'rows=%s err=%s' % (len(rows_b or []), (err_b or '—')[:70]))
    rows_adm, err_adm = search(adm, 'edu.assess.roster',
                               [('student_id', '=', child_b)], limit=0)
    check('P4c', '控制组（数据在，不是空库）：教务直读 B 的孩子的名单行 → 1 行',
          not err_adm and len(rows_adm or []) == 1,
          'rows=%s err=%s' % (len(rows_adm or []), err_adm))

    # ---- 正对照：家长 B 看得到自己的孩子 ----
    _r6, html6 = get(par_b_sess, '/my/child')
    nums6 = cell_numbers(html6)
    check('P5a', '控制组：家长 B 的 /my/child 看得到自己孩子（41）与另一个孩子的空态',
          41.0 in nums6 and '暂无已结束的评估记录' in html6,
          'B 页面数字 %s ｜ 空态文字在：%s' % (sorted(nums6),
                                             '暂无已结束的评估记录' in html6))
    sql_c = psql_int('select count(*) from edu_assess_roster where student_id = %d'
                     % child_c)
    check('P5b', '空态诚实：孩子 C 的名单行 = 0，页面写的是「暂无」而不是编造',
          sql_c == 0, 'SQL 名单行 = %d' % sql_c)
    _r7b, html7b = get(par_b_sess, '/my/child/%d' % child_c)
    check('P5d', '孩子 C 的**仪表盘**也是诚实空态（不编造，且与 SQL=0 同时成立）',
          _r7b.status_code == 200 and '暂无已结束的评估记录' in html7b
          and sql_c == 0,
          'HTTP %s ｜ 空态文字 %s ｜ SQL 名单行 %d'
          % (_r7b.status_code, '暂无已结束的评估记录' in html7b, sql_c))
    _r7, html7 = get(par_b_sess, '/assess/child/%d/history' % child_c)
    check('P5c', '孩子 C 的完整历程页 = 诚实空态（无数据表）',
          'yy-assess-history-empty' in html7
          and 'yy-assess-history-table' not in html7,
          '空态 %s ｜ 表 %s' % ('yy-assess-history-empty' in html7,
                               'yy-assess-history-table' in html7))

    # ---- 家长看得到孩子 ≠ 越权：教务同一条链看到的是同一批数字 ----
    sql_all = psql_int("select count(*) from edu_assess_roster r "
                       "join edu_assess_task t on t.id = r.task_id "
                       "where t.period like '%sP-%%'" % PERIOD)
    check('P6a', '口径收口：孩子 A 的行数 < 全夹具行数（家长 A 只看得到自己那一个孩子）',
          sql_a == 2 and sql_all == 3,
          '孩子 A 的已结束行 = %d ｜ 全夹具已结束行 = %d' % (sql_a, sql_all))
    return {'child_a': child_a, 'child_b': child_b, 'child_c': child_c,
            'par_a': par_a, 'par_b': par_b, 'tid': tid, 'tid_hid': tid_hid}

# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true', help='跑完保留夹具（排查用）')
    ap.add_argument('--only', default='', help='只跑 m / t / p 中的一段（注入实验窗口用）')
    args = ap.parse_args()

    print('== 探活 ==')
    try:
        requests.get(BASE + '/web/login?db=%s' % DB, timeout=15)
    except Exception as exc:
        die('站点不可达：%s' % exc)
    adm, adm_uid = login('admin')
    stu, stu_uid = login('stu@local')
    bo, bo_uid = login('backoffice@local')
    fac, fac_uid = login('faculty@local')
    par, par_uid = login('parent@local')
    if not (adm and stu and bo and fac and par):
        die('登录失败（adm=%s stu=%s bo=%s fac=%s par=%s）'
            % (bool(adm), bool(stu), bool(bo), bool(fac), bool(par)))
    print('    登录 OK：admin uid=%s ｜ stu uid=%s ｜ bo uid=%s ｜ fac uid=%s ｜ par uid=%s'
          % (adm_uid, stu_uid, bo_uid, fac_uid, par_uid))
    sids = [int(x) for x in psql('select id from op_student where active '
                                 'order by id limit 2').splitlines() if x.strip()]
    if not sids:
        die('库里没有在读学生，夹具建不起来')

    print('\n== 阶段 0：清场 → 干净态 ==')
    cleanup(adm)

    only = (args.only or '').strip().lower()
    try:
        if not only or only == 'm':
            section_m(adm, bo, stu)
        if not only or only == 't':
            section_t(adm, bo, stu, par, fac)
        if not only or only == 'p':
            section_p(adm, bo, stu, par, sids, par_uid)
    except requests.exceptions.RequestException as exc:
        # 共享工作区有并行 agent：升级/重启窗口里请求会断。这不是断言红，是环境作废
        # （口径同 ux_v3_route_matrix 的 ENV）—— 明说、退回 2，不把噪音当结论。
        die('站点中途不可达（多半是并行 agent 在跑 safe_upgrade 重启 web）：%s' % exc)

    print('\n== 清场 ==')
    cleanup(adm, verbose=True, skip=args.keep)
    left = psql_int("select count(*) from edu_assess_task "
                    "where period like '%s%%'" % PERIOD)
    if args.keep:
        print('    （--keep：跳过后清场核对 Z9a）')
    else:
        check('Z9a', '清场后夹具任务为 0（幂等可复跑）', left == 0,
              'fixture tasks = %d' % left)

    passed = sum(1 for i in items if i['pass'])
    failed = [i for i in items if not i['pass']]
    print('\n== 小结：%d/%d 通过 ==' % (passed, len(items)))
    for i in failed:
        print('   FAIL %s %s ｜ %s' % (i['no'], i['name'], i['detail'][:200]))
    json.dump({'base': BASE, 'items': items, 'passed': passed,
               'failed': len(failed)}, open(RESULTS, 'w'),
              ensure_ascii=False, indent=1)
    print('结果落盘：%s' % RESULTS)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())