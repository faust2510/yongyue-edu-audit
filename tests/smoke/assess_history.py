#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评估「历程」页验收 —— 跨任务聚合（零新模型）+ 越权反向 + 空态 + 未完成不暴露。

被测对象（custom_addons/edu_assess）：
  · GET /assess/my/history                  学生本人：自己的历次评估（时间序）
  · GET /assess/student/<id>/history        教师/教务：某个学生的历次评估

判据纪律（照 tests/smoke/eval_rebuild.py 与 docs/dev-workflow.md 的判据强度五兄弟）：
  · 正向断言必须与**库读数**对照（psql 计数 vs 页面条数），不是"页面看着有东西"；
  · **每一条负向断言都配正对照**：拿不到 0 只有在该拿的人拿到非 0 之后才作数；
  · 「页面没显示」不算越权证明 —— 越权还要证明**数据层**拿不到（JSON-RPC 直读）；
  · 空态必须与库读数（0 行）同时成立，且不许编造；
  · 反向注入：本脚本的每条断言都要能被一次**故意注入**打红（见 README 段落
    "反向证伪" 的三步命令，注入样例：把 _history_domain 的 student_id 收敛去掉）。

用法：
    python3 tests/smoke/assess_history.py            # 全量（自建夹具 → 断言 → 清场）
    python3 tests/smoke/assess_history.py --keep     # 跑完保留夹具（排查用）
退出码：0=全绿；1=有断言失败；2=运行错误（服务不可达 / 夹具建不起来 / 库读不到）。
结果落盘：tests/smoke/assess_history_results.json
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
RESULTS = HERE / 'assess_history_results.json'
PASSWORD = 'demo123'

# 夹具命名（清场按这两个前缀，绝不动既有数据）
TPL_PREFIX = '【评估历史验收】'
PERIOD_PREFIX = 'HIST-'
EMPTY_STUDENT_NAME = '【评估历史验收·空态】学生'

# 身份（与三个 UI 门禁同一批账号）
STU_LOGIN = 'stu@local'          # 王小明 = op.student 5（唯一有登录的学生）
BO_LOGIN = 'backoffice@local'    # 教务
FAC_LOGIN = 'faculty@local'      # 教师
ADM_LOGIN = 'admin'              # 系统管理员（口令 demo123，见 tests/smoke/ux_v3_route_matrix.py 的实测）

OK, FAIL = 'PASS', 'FAIL'
items = []


def check(no, name, cond, detail=''):
    verdict = OK if cond else FAIL
    items.append({'no': no, 'name': name, 'pass': bool(cond),
                  'detail': str(detail)[:800]})
    print('  %-4s #%-5s %-58s %s' % (verdict, no, name, str(detail)[:170]))
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


def table_cells(html):
    """取历程表内的所有单元格文本（只在 yy-assess-history-table 区间里找）。"""
    i = html.find('yy-assess-history-table')
    if i < 0:
        return []
    seg = html[i:html.find('</table>', i) if html.find('</table>', i) > 0 else len(html)]
    return [t.strip() for t in re.findall(r'>([^<>]{1,40})<', seg)]


def cell_numbers(html):
    """表内出现的数字（整数或小数）—— 「看不到这个分数」的判据用严格单元格匹配。"""
    nums = set()
    for cell in table_cells(html):
        if re.fullmatch(r'-?\d+(\.\d+)?', cell):
            nums.add(float(cell))
    return nums


def table_row_count(html):
    """历程表里的数据行数（<tbody> 内的 <tr> 个数）—— 与库计数逐行对照用。"""
    i = html.find('yy-assess-history-table')
    if i < 0:
        return 0
    j = html.find('</table>', i)
    seg = html[i:j if j > 0 else len(html)]
    body = seg.split('</thead>', 1)[1] if '</thead>' in seg else seg
    return body.count('<tr')


def get(sess, path):
    r = sess.get(BASE + path, timeout=40, allow_redirects=True)
    return r, r.text or ''


# ----------------------------------------------------------------------
# 夹具
# ----------------------------------------------------------------------

def fixture_ids(adm):
    tpls, _e = search(adm, 'edu.assess.template',
                      [('name', 'like', TPL_PREFIX + '%')])
    tasks, _e2 = search(adm, 'edu.assess.task',
                        [('period', 'like', PERIOD_PREFIX + '%')])
    items_, _e3 = search(adm, 'edu.assess.item',
                         [('template_id.name', 'like', TPL_PREFIX + '%')])
    return ([t['id'] for t in tpls], [t['id'] for t in tasks],
            [i['id'] for i in items_])


def cleanup(adm, keep=False, verbose=True):
    """按夹具前缀清场（幂等：跑两次读数一致）。"""
    if keep:
        return
    tpl_ids, task_ids, item_ids = fixture_ids(adm)
    scores, _e = search(adm, 'edu.assess.score', [('task_id', 'in', task_ids)])
    unlink(adm, 'edu.assess.score', [s['id'] for s in scores])
    rosters, _e = search(adm, 'edu.assess.roster', [('task_id', 'in', task_ids)])
    unlink(adm, 'edu.assess.roster', [r['id'] for r in rosters])
    unlink(adm, 'edu.assess.task', task_ids)
    unlink(adm, 'edu.assess.item', item_ids)
    unlink(adm, 'edu.assess.template', tpl_ids)
    # 空态夹具学生（含其伙伴）
    students, _e = search(adm, 'op.student',
                          [('name', '=', EMPTY_STUDENT_NAME)], ('id', 'partner_id'))
    for s in students:
        pid = (s.get('partner_id') or [False])[0]
        unlink(adm, 'op.student', [s['id']])
        if pid:
            unlink(adm, 'res.partner', [pid])
    if verbose:
        print('    ... 清场：模板 %d / 任务 %d / 评分项 %d / 学生 %d'
              % (len(tpl_ids), len(task_ids), len(item_ids), len(students)))


def build(adm, stu_id, other_id):
    """建夹具：3 个模板 × 5 个任务 × 名单与打分。全部走后台同一条写路径（JSON-RPC）。"""
    fx = {}

    def ensure_tpl(name, score_visible):
        tid = rpc_create(adm, 'edu.assess.template', {
            'name': name, 'kind': 'student', 'target_kind': 'student',
            'total': 100.0, 'pass_line': 60.0, 'excellent_line': 90.0,
            'score_visible': score_visible})
        iid = rpc_create(adm, 'edu.assess.item', {
            'template_id': tid, 'name': '验收评分项', 'max_score': 100.0,
            'sequence': 10})
        return tid, iid

    tpl_vis, item_vis = ensure_tpl(TPL_PREFIX + '可见', True)
    tpl_hid, item_hid = ensure_tpl(TPL_PREFIX + '不公开', False)
    tpl_anon, item_anon = ensure_tpl(TPL_PREFIX + '匿名', True)

    def ensure_task(tpl, period, state, anonymous=False):
        return rpc_create(adm, 'edu.assess.task', {
            'template_id': tpl, 'period': period, 'state': state,
            'scorer_kind': 'teacher', 'anonymous': anonymous, 'summary_min': 3})

    def add_row(task_id, sid, value, scorer_ref='u:12', with_score=True):
        vals = {'task_id': task_id, 'student_id': sid,
                'subject_ref': 's:%d' % sid, 'state': 'done'}
        rid = rpc_create(adm, 'edu.assess.roster', vals)
        if with_score:
            rpc_create(adm, 'edu.assess.score', {
                'task_id': task_id, 'roster_id': rid,
                'item_id': (item_anon if task_id in (fx['task_anon'],)
                            else item_vis if task_id in (fx['task_c1'],
                                                         fx['task_c2'],
                                                         fx['task_open'])
                            else item_hid),
                'value': value, 'scorer_ref': scorer_ref})
        return rid

    fx['tpl_vis'], fx['tpl_hid'], fx['tpl_anon'] = tpl_vis, tpl_hid, tpl_anon
    # K1 / K2：已结束且对本人可见（两条 → 能算出「与上次相比」）
    fx['task_c1'] = ensure_task(tpl_vis, PERIOD_PREFIX + 'C1', 'closed')
    fx['task_c2'] = ensure_task(tpl_vis, PERIOD_PREFIX + 'C2', 'closed')
    # K_OPEN：进行中（未完成）—— 分数必须不出现在学生页面
    fx['task_open'] = ensure_task(tpl_vis, PERIOD_PREFIX + 'OPEN', 'open')
    # K_HID：已结束但模板设置为「结果不向学生公开」
    fx['task_hid'] = ensure_task(tpl_hid, PERIOD_PREFIX + 'HID', 'closed')
    # K_ANON：已结束的匿名评估，只有 1 份答卷 < 门槛 3
    fx['task_anon'] = ensure_task(tpl_anon, PERIOD_PREFIX + 'ANON', 'closed',
                                  anonymous=True)

    fx['row_c1_a'] = add_row(fx['task_c1'], stu_id, 77.0)
    fx['row_c1_b'] = add_row(fx['task_c1'], other_id, 41.0, scorer_ref='u:12')
    fx['row_c2_a'] = add_row(fx['task_c2'], stu_id, 80.0, scorer_ref='u:11')
    fx['row_open_a'] = add_row(fx['task_open'], stu_id, 55.0)
    fx['row_hid_a'] = add_row(fx['task_hid'], stu_id, 66.0)
    fx['row_anon_a'] = add_row(fx['task_anon'], stu_id, 88.0, scorer_ref='h:deadbeef')
    return fx


def ensure_empty_student(adm):
    """空态夹具学生：没有任何名单行（也不给登录账号，用教务视角看）。"""
    sid = rpc_create(adm, 'op.student',
                     {'name': EMPTY_STUDENT_NAME, 'gender': 'm'})
    return sid


# ----------------------------------------------------------------------
# 断言
# ----------------------------------------------------------------------

def h1_positive(stu, adm, stu_id, fx):
    """H1 正向：学生本人看得到自己的历次评估，条数与库计数一致。"""
    print('\n== H1 正向（学生本人 / 条数 vs 库计数）==')
    sql_n = psql_int(
        "select count(*) from edu_assess_roster r "
        "join edu_assess_task t on t.id = r.task_id "
        "where r.student_id = %d and r.subject_ref = 's:%d' "
        "and t.state = 'closed' and t.period like '%s%%'"
        % (stu_id, stu_id, PERIOD_PREFIX))
    r, html = get(stu, '/assess/my/history')
    check('H1a', '学生本人 /assess/my/history → 200 且是本页（不是被弹走）',
          r.status_code == 200 and '/assess/my/history' in r.url
          and '我的评估历程' in html, 'HTTP %s → %s' % (r.status_code, r.url))
    rows = [p for p in (PERIOD_PREFIX + x for x in
                        ('C1', 'C2', 'OPEN', 'HID', 'ANON'))
            if p in html]
    page_rows = table_row_count(html)
    check('H1b', '页面**逐行**条数 == 库计数（已结束名单行）', page_rows == sql_n,
          '页面 %d 行（周期 %s）｜ SQL %d 行' % (page_rows, rows, sql_n))
    nums = cell_numbers(html)
    check('H1c', '两次可见结果的分数都在页面（77 / 80）',
          77.0 in nums and 80.0 in nums, '表内数字 %s' % sorted(nums))
    check('H1d', '「与上次相比」算出 +3.0 个百分点（80-77）',
          '+3.0' in html, '页面含 +3.0：%s' % ('+3.0' in html))
    check('H1e', '趋势条出现（≥2 次可比才出现）',
          'yy-assess-history-trend' in html, 'trend 节点在：%s'
          % ('yy-assess-history-trend' in html))
    check('H1f', '同任务内的跨学生隔离：A 的页面里没有 B 的分数（41）',
          41.0 not in nums, '表内数字 %s' % sorted(nums))
    return {'sql_n': sql_n, 'html_rows': page_rows, 'nums': sorted(nums)}


def h2_unfinished(stu, fx):
    """H2 未完成不暴露：进行中任务的分数既不上页面，也不是"没数据"。"""
    print('\n== H2 未完成（进行中）不暴露 ==')
    sql_scores = psql_int(
        "select count(*) from edu_assess_score where task_id = %d"
        % fx['task_open'])
    _r, html = get(stu, '/assess/my/history')
    nums = cell_numbers(html)
    check('H2a', '进行中任务名不出现在学生页面',
          PERIOD_PREFIX + 'OPEN' not in html, '页面含 HIST-OPEN：%s'
          % (PERIOD_PREFIX + 'OPEN' in html))
    check('H2b', '进行中任务的分数（55）不出现在学生页面',
          55.0 not in nums, '表内数字 %s' % sorted(nums))
    check('H2c', '控制组：该分数的确在库里（不是"没数据"才看不到）',
          sql_scores == 1, 'edu_assess_score 里 HIST-OPEN 的行数=%d' % sql_scores)


def h3_empty(bo, stu, adm, empty_id):
    """H3 空态：没有数据的学生页面必须诚实空态。"""
    print('\n== H3 空态（不许编造）==')
    sql_n = psql_int(
        "select count(*) from edu_assess_roster where student_id = %d" % empty_id)
    r, html = get(adm, '/assess/student/%d/history' % empty_id)
    check('H3a', '教务看「零名单行」学生 → 200 + 空态节点',
          r.status_code == 200 and 'yy-assess-history-empty' in html,
          'HTTP %s ｜ 空态 %s ｜ 表 %s' % (
              r.status_code, 'yy-assess-history-empty' in html,
              'yy-assess-history-table' in html))
    check('H3b', '空态与库读数一致（该生名单行 = 0）', sql_n == 0,
          'SQL 名单行 = %d' % sql_n)
    check('H3c', '空态页面**没有**渲染数据表（不编造行）',
          'yy-assess-history-table' not in html,
          '表节点在：%s' % ('yy-assess-history-table' in html))
    # 学生本人：此刻他的历史里没有夹具之外的新数据 —— 空不等于报错
    _r2, html2 = get(stu, '/assess/my/history')
    check('H3d', '学生本人页面在「无该生数据」时也是可渲染的 200（无 500）',
          'Traceback' not in html2 and 'Internal Server Error' not in html2,
          '页面长度 %d' % len(html2))


def h4_deny(stu, other_id, fx):
    """H4 越权反向（必须红）：学生 A 拿不到学生 B 的评估历史 —— 页面层 + 数据层。"""
    print('\n== H4 越权反向（学生 A → 学生 B；必须拿不到）==')
    r, html = get(stu, '/assess/student/%d/history' % other_id)
    check('H4a', '学生 A 请求 B 的历程 → 被弹回门户首页（不是 200 本页）',
          '/assess/student/' not in r.url and 'my/home' in r.url,
          'HTTP %s → %s' % (r.status_code, r.url))
    check('H4b', 'A 的响应里没有 B 的分数（41）',
          41.0 not in cell_numbers(html), '表内数字 %s' % sorted(cell_numbers(html)))
    # —— 数据层：绕过页面直读模型 ——
    rows, err = search(stu, 'edu.assess.roster',
                       [('student_id', '=', other_id)], ('id',))
    check('H4c', '数据层：A 用 JSON-RPC 直读 edu.assess.roster → AccessError',
          rows in (None, []) and err and 'Access' in err,
          'rows=%s err=%s' % (rows, err))
    rows2, err2 = search(stu, 'edu.assess.score',
                         [('roster_id.student_id', '=', other_id)], ('id',))
    check('H4d', '数据层：A 用 JSON-RPC 直读 edu.assess.score → AccessError',
          rows2 in (None, []) and err2 and 'Access' in err2,
          'rows=%s err=%s' % (rows2, err2))
    # —— 参数注入：在学生**自己的**页面上塞别人的 id ——
    r3, html3 = get(stu, '/assess/my/history?student_id=%d&subject_ref=s:%d'
                    % (other_id, other_id))
    check('H4e', 'A 在自己的历程页上注入 ?student_id=B → 读数一字不变（域来自身份）',
          41.0 not in cell_numbers(html3) and PERIOD_PREFIX + 'C1' in html3,
          '表内数字 %s' % sorted(cell_numbers(html3)))
    # —— 控制组（证明 H4a/H4b 不是"对谁都不显示"）——
    check('H4f', '控制组：B 的分数确实在库里（41）',
          psql_int("select count(*) from edu_assess_roster where student_id = %d "
                   "and task_id = %d" % (other_id, fx['task_c1'])) == 1,
          'roster(student_id=%d, task=%d) 行数=1' % (other_id, fx['task_c1']))


def h5_staff(bo, fac, adm, stu_id, other_id):
    """H5 控制组：教师/教务视角 —— 该拿的人拿得到，不该拿的拿不到。"""
    print('\n== H5 控制组（教师/教务视角）==')
    r, html = get(bo, '/assess/student/%d/history' % other_id)
    nums = cell_numbers(html)
    check('H5a', '教务看 B 的历程 → 200 且看得到 41（同一路由换身份就拿到了）',
          r.status_code == 200 and 41.0 in nums,
          'HTTP %s ｜ 表内数字 %s' % (r.status_code, sorted(nums)))
    r2, html2 = get(bo, '/assess/student/%d/history' % stu_id)
    check('H5b', '教务看 A 的历程 → 看到 A 的 77 / 80',
          r2.status_code == 200 and 77.0 in cell_numbers(html2)
          and 80.0 in cell_numbers(html2),
          '表内数字 %s' % sorted(cell_numbers(html2)))
    r3, html3 = get(fac, '/assess/student/%d/history' % stu_id)
    check('H5c', '教师看**任教班内**学生 → 200 且非越界页',
          r3.status_code == 200 and 'yy-assess-history-scope' not in html3,
          'HTTP %s ｜ 越界页 %s' % (r3.status_code,
                                   'yy-assess-history-scope' in html3))
    r4, html4 = get(fac, '/assess/student/%d/history' % other_id)
    check('H5d', '教师看**非任教班**学生 → 越界页（fail-closed）',
          'yy-assess-history-scope' in html4
          and 41.0 not in cell_numbers(html4),
          '越界页 %s ｜ 表内数字 %s' % ('yy-assess-history-scope' in html4,
                                       sorted(cell_numbers(html4))))
    r5, html5 = get(adm, '/assess/student/%d/history' % other_id)
    check('H5e', '管理员看 B → 200 且有数据（再一重正对照）',
          r5.status_code == 200 and 41.0 in cell_numbers(html5),
          'HTTP %s' % r5.status_code)
    # 学生 /my/history 对教师：不是本页（教师没有"我的评估"）
    r6, html6 = get(fac, '/assess/my/history')
    check('H5f', '教师请求学生本人的 /assess/my/history → 弹回门户（不误开学生视角）',
          '/assess/my/history' not in r6.url,
          'HTTP %s → %s' % (r6.status_code, r6.url))


def h6_gates(bo, stu, adm, fx, stu_id):
    """H6/H7 两道闸门：匿名样本门槛 + 不向学生公开。"""
    print('\n== H6/H7 闸门（匿名门槛 / 不向学生公开）==')
    _r, html = get(stu, '/assess/my/history')
    nums = cell_numbers(html)
    check('H6a', '匿名任务只有 1 份 < 门槛 3 → 学生页面不出现该分值（88）',
          88.0 not in nums, '表内数字 %s' % sorted(nums))
    check('H6b', '控制组：该匿名记录确实在库（1 条打分）',
          psql_int("select count(*) from edu_assess_score where task_id = %d"
                   % fx['task_anon']) == 1, '打分记录=1')
    check('H7a', '模板「不向学生公开」→ A 自己看不到 66，但行还在（有解释）',
          66.0 not in nums and '本次评估结果不向学生公开' in html,
          '表内数字 %s ｜ 解释文字 %s' % (
              sorted(nums), '本次评估结果不向学生公开' in html))
    _r2, html2 = get(adm, '/assess/student/%d/history' % stu_id)
    check('H7b', '控制组：同一行在教务视角**看得到** 66（数据在，只是对本人不公开）',
          66.0 in cell_numbers(html2), '表内数字 %s' % sorted(cell_numbers(html2)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true', help='跑完保留夹具')
    args = ap.parse_args()

    print('== 探活 ==')
    try:
        requests.get(BASE + '/web/login?db=%s' % DB, timeout=15)
    except Exception as exc:
        die('站点不可达：%s' % exc)
    adm, adm_uid = login(ADM_LOGIN)
    stu, stu_uid = login(STU_LOGIN)
    bo, _ = login(BO_LOGIN)
    fac, _ = login(FAC_LOGIN)
    if not (adm and stu and bo and fac):
        die('登录失败（adm=%s stu=%s bo=%s fac=%s）' % (bool(adm), bool(stu),
                                                      bool(bo), bool(fac)))
    print('    登录：admin uid=%s ｜ %s uid=%s ｜ %s ｜ %s'
          % (adm_uid, STU_LOGIN, stu_uid, BO_LOGIN, FAC_LOGIN))

    stu_id = psql_int("select id from op_student where user_id = %d" % stu_uid)
    other_id = psql_int("select id from op_student where gr_no = 'DUP-001'")
    if not stu_id or not other_id:
        die('找不到学生档案（stu_id=%s other_id=%s）' % (stu_id, other_id))
    print('    身份：学生 A = op.student %d（%s）｜ 学生 B = op.student %d'
          % (stu_id, STU_LOGIN, other_id))

    print('\n== 阶段 0：清场 → 干净态 ==')
    cleanup(adm, args.keep)
    clean_rows = psql_int(
        "select count(*) from edu_assess_roster r join edu_assess_task t "
        "on t.id = r.task_id where t.period like '%s%%'" % PERIOD_PREFIX)
    check('H0a', '清场后夹具名单行为 0（读数是本次的）', clean_rows == 0,
          'fixture roster rows = %d' % clean_rows)
    _r0, html0 = get(stu, '/assess/my/history')
    check('H0b', '干净态（学生 A 无任何已结束评估）→ 诚实空态',
          r'yy-assess-history-empty' in html0
          and psql_int("select count(*) from edu_assess_roster r "
                       "join edu_assess_task t on t.id = r.task_id "
                       "where r.student_id = %d and t.state = 'closed'"
                       % stu_id) == 0,
          '空态节点 %s ｜ SQL closed 行 = 0' % ('yy-assess-history-empty' in html0))

    print('\n== 建夹具 ==')
    fx = build(adm, stu_id, other_id)
    empty_id = ensure_empty_student(adm)
    print('    任务 %s ｜ 名单行 %s ｜ 空态学生 %d'
          % ([fx['task_c1'], fx['task_c2'], fx['task_open'], fx['task_hid'],
              fx['task_anon']], [fx['row_c1_a'], fx['row_c1_b'], fx['row_c2_a'],
                                 fx['row_open_a'], fx['row_hid_a'],
                                 fx['row_anon_a']], empty_id))

    h1_positive(stu, adm, stu_id, fx)
    h2_unfinished(stu, fx)
    h3_empty(bo, stu, adm, empty_id)
    h4_deny(stu, other_id, fx)
    h5_staff(bo, fac, adm, stu_id, other_id)
    h6_gates(bo, stu, adm, fx, stu_id)

    print('\n== 清场 ==')
    cleanup(adm, args.keep)
    left = psql_int("select count(*) from edu_assess_task where period like '%s%%'"
                    % PERIOD_PREFIX)
    check('H9a', '清场后夹具任务为 0（幂等可复跑）', left == 0,
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
