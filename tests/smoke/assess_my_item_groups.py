#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""/assess/my「评分项 / 得分」表的**行分组**验收（2026-09-29）。

被测量的问题：/assess/my 的结果表是**行 = 评分项**。矩阵表头上一轮已经把
「区名分组」做进了列（<th scope="colgroup" colspan>，见
tests/smoke/assess_portal_gaps.py 的 M 段），但这张行表仍是裸项名 ⇒
《卫生检测表》那类**跨区同名项**（窗户有灰尘/污渍 ×3）在这张表上长得一模一样，
人眼分不出这一行属于哪个区。

行轴的正确做法（与列轴同一棵树、同一套语义手法，只是轴反过来）：
  · 一棵树：controllers/portal.py 的 _item_chain（分组信息的唯一来源）；
  · 一个格：<th scope="rowgroup" rowspan=N> —— 列轴是 scope="colgroup" + colspan，
    行轴的镜像就是 scope="rowgroup" + rowspan（读屏用户靠它拿到行组语义）；
  · 一条口径：连续若干行共享同一条祖先链时合并成一个行组格，链文字 = 祖先链
    （与 xlsx 列头 _item_label 同一分隔符），项名格**仍是裸项名**（既有断言按裸名匹配）。

判据纪律（同 assess_portal_gaps.py）：
  · 正向断言与**库读数**对照（SQL 递归祖先链 vs 页面逐行链），不是「页面看着有」；
  · 控制组：扁平模板（全是深度 1 的项）**不得新增任何列/格**（改动是条件生效的）；
  · 反向基线：改动前本脚本 V2-V6 必须变红，且原始读数里每行只有 [项名, 得分] 两格。

用法：
    python3 tests/smoke/assess_my_item_groups.py              # 全量（建夹具 -> 断言 -> 清场）
    python3 tests/smoke/assess_my_item_groups.py --keep       # 保留夹具（排查用）
    python3 tests/smoke/assess_my_item_groups.py --axe        # 额外跑一次 axe（需要 playwright/chrome）
退出码：0=全绿；1=有断言失败；2=ENV（站点不可达 / 夹具建不起来 / 库读不到）。
结果落盘：tests/smoke/assess_my_item_groups_results.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import assess_portal_gaps as G          # noqa: E402  复用其夹具构造器与 RPC 助手

BASE = G.BASE
RESULTS = HERE / 'assess_my_item_groups_results.json'
LABEL_SEP = ' / '                       # 与 controllers/portal.py 的 LABEL_SEP 同值

# 夹具命名（清场只按这些前缀，绝不动既有数据）
MARK = '【我的评分分组】'
PERIOD = 'MYGRP-'
TREE = G.TREE                           # 同一张《卫生检测表》形态（跨区同名项）
FLAT_ITEMS = G.FLAT_ITEMS               # 扁平控制组

MEANINGLESS = 'zzz不存在的入口zzz'
OK, FAIL = 'PASS', 'FAIL'
items = []
readings = {}


def check(no, name, cond, detail=''):
    items.append({'no': no, 'name': name, 'pass': bool(cond),
                  'detail': str(detail)[:1200]})
    print('  %-4s #%-6s %-52s %s' % (OK if cond else FAIL, no, name,
                                     str(detail)[:190]))
    return bool(cond)


def note(msg):
    print('  ---- %s' % msg)


def die(msg):
    print('CANNOT: %s' % msg)
    json.dump({'error': msg, 'items': items}, open(RESULTS, 'w'),
              ensure_ascii=False, indent=1)
    sys.exit(2)


def probe():
    """探活（**不走系统代理**）：macOS 系统代理会被 requests 的 trust_env 读到，
    裸 requests.get 可能被代理转成 502 —— 那是 ENV 噪音，不是站点故障
    （同一 URL 在 trust_env=False 下 302/200）。"""
    s = requests.Session()
    s.trust_env = False
    return s.get(BASE + '/web/login?db=%s' % G.DB, timeout=15)


def student_of_login(login_name):
    """登录名 -> op.student id（与 identity.profile_of_user 同口径的**双向并集**：

    链① = op_student.user_id == uid；链①落空才查链② = partner_id.user_ids 含 uid。
    实测踩过：按 res_partner.user_id（**销售员列**，Odoo 19 的同名陷阱）查
    stu@local 会返回空 —— 本仓学生档案挂在 op_student.user_id 上。
    """
    sql = ("select s.id from op_student s "
           "where s.user_id = (select id from res_users where login = '%s' "
           "limit 1) or exists (select 1 from res_users u "
           "where u.partner_id = s.partner_id and u.login = '%s') "
           "order by s.id limit 1" % (login_name, login_name))
    raw = G.psql(sql)
    return int(raw) if raw.strip().isdigit() else None


# ----------------------------------------------------------------------
# 页面解析：把「评分项 / 得分」表按 HTML 表格规则展开成网格
# ----------------------------------------------------------------------

def item_table(html, marker):
    """任务名 marker 之后的第一张 <table>（/assess/my 每题一张卡、卡内一张表）。"""
    i = (html or '').find(marker)
    if i < 0:
        return ''
    j = html.find('<table', i)
    if j < 0:
        return ''
    k = html.find('</table>', j)
    return html[j:k + 8] if k > 0 else html[j:]


def raw_cells(tag_html):
    out = []
    for tag, attrs, inner in re.findall(r'<(th|td)([^>]*)>(.*?)</\1>',
                                        tag_html, re.S):
        out.append({'tag': tag, 'attrs': attrs.strip(),
                    'text': re.sub(r'<[^>]+>', '', inner).strip()})
    return out


def table_rows(seg):
    """-> (thead 行, tbody 行)，每行 = [格]（未展开 rowspan）。"""
    h = re.search(r'<thead[^>]*>(.*?)</thead>', seg or '', re.S)
    b = re.search(r'<tbody[^>]*>(.*?)</tbody>', seg or '', re.S)
    split = lambda s: [raw_cells(tr) for tr in re.findall(
        r'<tr[^>]*>(.*?)</tr>', s or '', re.S)]
    return split(h.group(1) if h else ''), split(b.group(1) if b else '')


def _span(attrs, name):
    m = re.search(name + r'="(\d+)"', attrs or '')
    return int(m.group(1)) if m else 1


def row_grid(rows):
    """按 rowspan 把每行的格展开（被上面 rowspan 覆盖的格 = 该格的副本）。

    为什么要展开：合并格只在**组的第一行**出现，后续行靠 rowspan 继承；
    读「第 N 行属于哪个组」必须按浏览器的表格模型算，不能只看那一行的 DOM。
    """
    occ = {}
    for r, cells in enumerate(rows):
        c = 0
        for cell in cells:
            while (r, c) in occ:
                c += 1
            cs, rs = _span(cell['attrs'], 'colspan'), _span(cell['attrs'], 'rowspan')
            for i in range(cs):
                for rr in range(r, r + rs):
                    occ[(rr, c + i)] = cell
            c += cs
    width = max([max(k[1] for k in occ) + 1] if occ else [0])
    return [[occ.get((r, c)) for c in range(width)] for r in range(len(rows))]


def chains_from_page(grid):
    """展开后的网格 -> [(链, 项名, 得分文本)]（无链列时链 = ''）。"""
    out = []
    for row in grid:
        cells = [c for c in row if c]
        if len(cells) >= 3:
            out.append((cells[0]['text'], cells[1]['text'], cells[2]['text']))
        elif len(cells) == 2:
            out.append(('', cells[0]['text'], cells[1]['text']))
    return out


# ----------------------------------------------------------------------
# 夹具
# ----------------------------------------------------------------------

def cleanup(adm, skip=False):
    if skip:
        return
    tpls, _e = G.search(adm, 'edu.assess.template', [('name', 'like', MARK + '%')])
    tpl_ids = [t['id'] for t in tpls]
    tasks, _e = G.search(adm, 'edu.assess.task', [('period', 'like', PERIOD + '%')])
    task_ids = [t['id'] for t in tasks]
    if task_ids:
        scores, _e = G.search(adm, 'edu.assess.score', [('task_id', 'in', task_ids)])
        G.unlink(adm, 'edu.assess.score', [s['id'] for s in scores])
        rosters, _e = G.search(adm, 'edu.assess.roster', [('task_id', 'in', task_ids)])
        G.unlink(adm, 'edu.assess.roster', [r['id'] for r in rosters])
    G.unlink(adm, 'edu.assess.task', task_ids)
    itms, _e = G.search(adm, 'edu.assess.item',
                        [('template_id.name', 'like', MARK + '%')])
    G.unlink(adm, 'edu.assess.item', [i['id'] for i in itms])
    G.unlink(adm, 'edu.assess.template', tpl_ids)
    print('    ... 清场：模板 %d / 任务 %d / 评分项 %d'
          % (len(tpl_ids), len(task_ids), len(itms)))


def expected_rows(tpl):
    """库口径的期望行：[(链, 项名)]，链 = 祖先名以 LABEL_SEP 连接（根->父）。"""
    return [(LABEL_SEP.join(chain), name) for name, chain in
            G.expected_columns(tpl)]


def expected_scores(tpl, written=1.0):
    """库口径的期望**得分**（页面「得分」列）：扣分制下 = max_score - 写入值。

    口径来源：models/assess.py 的 EduAssessRoster._item_cell（_item_average 是它
    第 1 期名字的保留壳）—— 扣分项按 score_mode 转成得分；一条 score 行 = 一个人
    的一次扣分。所以页面显示的是**得分**，不是原始 value（实测：value=1.0、
    max_score=5.0 的项页面显示 4）。
    """
    rows = G.psql('select id || \'|\' || max_score from edu_assess_item '
                  "where template_id = %d and item_kind = 'leaf' "
                  'order by sequence, id' % tpl)
    out = []
    for line in rows.splitlines():
        if line.strip():
            _i, mx = line.split('|')
            out.append('%g' % (float(mx) - written))
    return out


def group_spans(exp_chains):
    """连续同链的行组 -> [(起始行号, 长度)]（与视图的合并规则同口径）。"""
    out, i = [], 0
    while i < len(exp_chains):
        j = i
        while j < len(exp_chains) and exp_chains[j] == exp_chains[i]:
            j += 1
        out.append((i, j - i))
        i = j
    return out


# ----------------------------------------------------------------------
# 主体
# ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--axe', action='store_true')
    args = ap.parse_args()

    print('== 探活 ==')
    try:
        probe()
    except Exception as exc:
        die('站点不可达：%s' % exc)
    adm, adm_uid = G.login('admin')
    stu, stu_uid = G.login('stu@local')
    if not (adm and stu):
        die('登录失败（adm=%s stu=%s）' % (bool(adm), bool(stu)))
    sid = student_of_login('stu@local')
    if not sid:
        die('找不到 stu@local 对应的 op.student')
    print('    登录 OK：admin uid=%s ｜ stu uid=%s ｜ op.student = %s'
          % (adm_uid, stu_uid, sid))

    print('\n== 夹具：清场 -> 建表 ==')
    cleanup(adm)
    tpl, leaves = G.build_template(adm, MARK + '卫生检测表（三层·区名）', TREE)
    flat_tpl, flat_leaves = G.build_template(adm, MARK + '扁平控制组', None,
                                             FLAT_ITEMS)

    def mk_task(tpl_id, period):
        tid = G.rpc_create(adm, 'edu.assess.task', {
            'template_id': tpl_id, 'period': period, 'state': 'closed',
            'scorer_kind': 'teacher', 'anonymous': False, 'summary_min': 1})
        rid = G.rpc_create(adm, 'edu.assess.roster',
                           {'task_id': tid, 'student_id': sid, 'state': 'done'})
        return tid, rid

    def add_scores(tid, rid, leaf_list):
        for item in leaf_list:
            iid = item[3]
            G.rpc_create(adm, 'edu.assess.score', {
                'task_id': tid, 'roster_id': rid, 'item_id': iid,
                'value': 1.0, 'scorer_ref': 'i:%d' % adm_uid, 'track': 'objective'})

    tid, rid = mk_task(tpl, PERIOD + '三层')
    add_scores(tid, rid, leaves)
    flat_tid, flat_rid = mk_task(flat_tpl, PERIOD + '扁平控制组')
    add_scores(flat_tid, flat_rid, flat_leaves)
    exp = expected_rows(tpl)
    print('    夹具：三层模板 %d / 任务 %d（%d 叶子）；扁平模板 %d / 任务 %d'
          % (tpl, tid, len(leaves), flat_tpl, flat_tid))
    print('    库口径期望行（链 | 项名）：')
    for ch, nm in exp:
        print('        %-18s | %s' % (ch or '（无链）', nm))

    # ---------------- 页面 ----------------
    print('\n== V /assess/my：行分组读数 ==')
    r, html = G.get(stu, '/assess/my')
    seg = item_table(html, MARK + '卫生检测表（三层·区名）')
    thead_rows, tbody_rows = table_rows(seg)
    grid = row_grid(tbody_rows)
    page = chains_from_page(grid)
    readings['tree'] = {
        'task': MARK + '卫生检测表（三层·区名）', 'http': r.status_code,
        'thead': [[c['tag'] + '|' + c['attrs'] + '|' + c['text']
                   for c in row] for row in thead_rows],
        'tbody_raw': [[c['tag'] + '|' + c['attrs'] + '|' + c['text']
                       for c in row] for row in tbody_rows],
        'page_rows': page,
        'db_rows': exp,
    }
    print('    原始行（第 1 行起，最多 6 行）：')
    for i, row in enumerate(tbody_rows[:6]):
        print('        [%d] %s' % (i, ' ｜ '.join(
            '<%s%s>%s' % (c['tag'], (' ' + c['attrs']) if c['attrs'] else '',
                          c['text']) for c in row)))
    print('    展开后的网格（链 | 项名 | 得分）：')
    for i, row in enumerate(page):
        print('        [%d] %-18s | %-16s | %s' % (i, row[0] or '—', row[1], row[2]))

    check('V1', '页面拿得到这张表（任务名 + 行数 > 0；防「页面根本没渲染」的假绿）',
          bool(seg) and bool(tbody_rows), 'HTTP %s ｜ tbody 行 %d ｜ 表片段 %d 字'
          % (r.status_code, len(tbody_rows), len(seg)))
    check('V2', '行数 == 库里的叶子数（%d）' % len(leaves),
          len(page) == len(leaves) == len(exp),
          '页面行 %d ｜ 库叶子 %d' % (len(page), len(leaves)))
    check('V3', '既有契约：每行的**项名**仍是裸项名，且与库 order by sequence, id 同序',
          [p[1] for p in page] == [e[1] for e in exp],
          '页面 %s ｜ 库 %s' % ([p[1] for p in page], [e[1] for e in exp]))
    check('V4', '逐行比对：每行的**分组链** == 库祖先链（区 -> 分类）',
          [p[0] for p in page] == [e[0] for e in exp],
          '页面链 %s ｜ 库链 %s' % ([p[0] for p in page], [e[0] for e in exp]))
    same = [(i, p) for i, p in enumerate(page) if p[1] == '窗户有灰尘/污渍']
    check('V5', '跨区同名项可分：三条「窗户有灰尘/污渍」行的链两两不同',
          len(same) == 3 and len({p[0] for _i, p in same}) == 3,
          '行 -> 链 = %s' % [(i, p[0]) for i, p in same])
    spans = group_spans([e[0] for e in exp])
    first_of_span = {i: n for i, n in spans}
    group_cells = [(i, c['attrs']) for i, row in enumerate(tbody_rows)
                   for c in row if c['tag'] == 'th']
    ok_scope = bool(group_cells) and all(
        'scope="rowgroup"' in a for _i, a in group_cells)
    ok_span = all(_span(a, 'rowspan') == first_of_span.get(i, 1)
                  for i, a in group_cells) and len(group_cells) == len(spans)
    check('V6', '分组格是 <th scope="rowgroup" rowspan=N>（N = 该连续链组的行数）',
          ok_scope and ok_span,
          '分组格 = %s ｜ 库期望组 = %s' % (group_cells[:6], spans))
    exp_scores = expected_scores(tpl)
    check('V7', '得分列口径未变：逐行 == max_score - 写入值（扣分制，库读数）',
          [p[2] for p in page] == exp_scores,
          '页面 = %s ｜ 库 = %s' % ([p[2] for p in page], exp_scores))
    check('V8', '链文字来自库（不是把项名复制一遍）：链集合 == 库链集合，且链 != 项名',
          {p[0] for p in page} == {e[0] for e in exp}
          and all(p[0] != p[1] for p in page),
          '链集合 %s' % sorted({p[0] for p in page}))

    # ---------------- 控制组：扁平模板 ----------------
    print('\n== C 控制组：扁平模板（全是深度 1 的项）不得新增列/格 ==')
    r2, html2 = G.get(stu, '/assess/my')
    seg2 = item_table(html2, MARK + '扁平控制组')
    thead2, tbody2 = table_rows(seg2)
    grid2 = row_grid(tbody2)
    page2 = chains_from_page(grid2)
    readings['flat'] = {'thead': [[c['tag'] + '|' + c['text'] for c in row]
                                  for row in thead2],
                        'tbody_raw': [[c['tag'] + '|' + c['attrs'] + '|' + c['text']
                                       for c in row] for row in tbody2],
                        'page_rows': page2}
    print('    扁平表原始行：')
    for i, row in enumerate(tbody2):
        print('        [%d] %s' % (i, ' ｜ '.join(
            '<%s%s>%s' % (c['tag'], (' ' + c['attrs']) if c['attrs'] else '',
                          c['text']) for c in row)))
    flat_names = [n for n, _s in FLAT_ITEMS]
    check('C1', '控制组：扁平表仍是 2 列（表头 2 格、tbody 每行 2 格、无 th 格）',
          bool(seg2) and len(thead2) == 1 and len(thead2[0]) == 2
          and all(len(row) == 2 for row in tbody2)
          and not any(c['tag'] == 'th' for row in tbody2 for c in row),
          'thead %d 行/%d 格 ｜ tbody 行格数 %s'
          % (len(thead2), len(thead2[0]) if thead2 else 0,
             [len(x) for x in tbody2]))
    check('C2', '控制组：扁平表逐行 == [裸项名, 得分]，顺序与库一致（改动对它零影响）',
          [p[1] for p in page2] == flat_names
          and all(p[0] == '' for p in page2),
          '页面 = %s ｜ 库 = %s' % ([p[1] for p in page2], flat_names))
    check('C3', '控制组：表头仍是「评分项 / 得分」两格（行分组不加表头列）',
          [[c['text'] for c in row] for row in thead2] == [['评分项', '得分']],
          'thead = %s' % [[c['text'] for c in row] for row in thead2])

    # ---------------- axe（可选） ----------------
    if args.axe:
        print('\n== A axe 定向读数（/assess/my，本页三张评估表的语义结构）==')
        a11y = axe_scan(stu, '/assess/my')
        readings['axe'] = a11y
        if a11y.get('env'):
            note('axe 未读数（ENV）：%s（不判红）' % a11y['env'])
        else:
            bad = [v for v in a11y['violations']
                   if v['id'] in ('th-has-data-cells', 'scope-attr-valid',
                                  'td-headers-attr', 'table-duplicate-name',
                                  'empty-table-header', 'color-contrast')]
            note('axe 规则命中：%s' % (a11y['rules'] or '无'))
            check('A1', 'axe：新行组表没有 th/scope/表头类或对比度违规',
                  not bad, '命中 = %s' % (bad or '无'))

    print('\n== 清场 ==')
    cleanup(adm, skip=args.keep)
    left = G.psql_int("select count(*) from edu_assess_task "
                      "where period like '%s%%'" % PERIOD)
    if args.keep:
        note('（--keep：跳过清场核对）')
    else:
        check('Z9a', '清场后夹具任务为 0（幂等可复跑）', left == 0,
              'fixture tasks = %d' % left)

    passed = sum(1 for i in items if i['pass'])
    failed = [i for i in items if not i['pass']]
    print('\n== 小结：%d/%d 通过 ==' % (passed, len(items)))
    for i in failed:
        print('   FAIL %s %s ｜ %s' % (i['no'], i['name'], i['detail'][:200]))
    json.dump({'base': BASE, 'when': time.strftime('%Y-%m-%d %H:%M:%S'),
               'readings': readings, 'items': items, 'passed': passed,
               'failed': len(failed)}, open(RESULTS, 'w'),
              ensure_ascii=False, indent=1)
    print('结果落盘：%s' % RESULTS)
    return 1 if failed else 0


def axe_scan(sess, path):
    """用 playwright + 本地 axe 缓存扫一页（ENV 缺失时返回 {'env': 原因}）。"""
    try:
        import tempfile
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {'env': 'playwright 不可用：%s' % exc}
    axe_file = os.path.join(tempfile.gettempdir(), 'edu_axe',
                            'axe-4.10.2.min.js')
    if not os.path.isfile(axe_file):
        return {'env': 'axe 缓存缺失：%s' % axe_file}
    src = open(axe_file, encoding='utf-8').read()
    cookies = [{'name': c.name, 'value': c.value, 'domain': 'localhost',
                'path': c.path or '/'} for c in sess.cookies]
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(channel='chrome')
            ctx = b.new_context(viewport={'width': 1280, 'height': 900})
            ctx.add_cookies(cookies)
            page = ctx.new_page()
            page.goto(BASE + path, wait_until='domcontentloaded', timeout=45000)
            page.add_script_tag(content=src)
            res = page.evaluate('async () => await axe.run(document, '
                                '{resultTypes:["violations"]})')
            # 只看我们这张表所在卡片：全页其它块（门户外壳）不是本次改动面，
            # 但违规仍逐条打印出来，避免"看不到的豁免"。
            b.close()
    except Exception as exc:
        return {'env': 'axe 运行失败：%s' % exc}
    viols = []
    for v in res.get('violations') or []:
        nodes = v.get('nodes') or []
        viols.append({
            'id': v['id'], 'impact': v.get('impact'), 'nodes': len(nodes),
            # 命中元素的选择器：用来证明这些违规**不在**本次改动的那张表里
            # （逐条打印，不许"看不到的豁免"）。
            'targets': [','.join(n.get('target') or []) for n in nodes][:5],
        })
    return {'violations': viols,
            'rules': ', '.join('%s(%s x%d)' % (v['id'], v['impact'] or '-',
                                               v['nodes']) for v in viols)}


if __name__ == '__main__':
    # 共享工作区纪律（照 tests/smoke/assess_portal_gaps.py）：并行 agent 的
    # safe_upgrade 会重启 web，请求中途断开。那是 **ENV 作废**，不是断言红。
    try:
        sys.exit(main())
    except requests.exceptions.RequestException as exc:
        die('站点中途不可达（多半是并行 agent 在跑 safe_upgrade 重启 web）：%s' % exc)
