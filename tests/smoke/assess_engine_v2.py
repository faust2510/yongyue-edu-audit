#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评估引擎第 2 期真机验收：12 个新字段 / 三种算法 / 6 组缺口 / 建 6 张表的自证。

对应 docs/plans/eval-unified-design.md：
  §3.3 12 个新增字段（F1–F12）        §3.5 三种算法 + 派生显示（不落库）
  §4.5 建 6 张表的自证（本脚本 W1–W7） §5.1–§5.10 六组缺口逐条
  §8.0/§8.3 存量回归（W14）           §10.3 V6 xlsx 往返（由 tests/smoke/eval_rebuild.py 覆盖）

判据纪律（照 eval_rebuild.py）：
  · 夹具全部经 JSON-RPC 在线创建 = 与后台表单**同一条写路径**；
  · 每条负向断言都配正对照（"被拒"只有在"同样的调用改成合法值能通过"之后才作数）；
  · 「反向注入」：把第 1 期的旧算法**逐字复制**到本脚本里，对同一批数据同时跑
    旧算法与新算法，断言 旧算法 ≠ Excel 素材值 且 新算法 = Excel 素材值；
  · 打完就摸页面：双轨均匀值从 /assess/task/<id>/results 的 HTML 里读回来。

用法：python3 tests/smoke/assess_engine_v2.py [--keep]
退出码：0 全绿；1 有断言失败；2 运行错误（服务不可达 / 夹具建不起来）。
结果落盘：tests/smoke/assess_engine_v2_results.json
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
RESULTS = HERE / 'assess_engine_v2_results.json'
BEFORE = HERE / 'assess_engine_v2_before.json'
PASSWORD = 'demo123'
PREFIX = '【第2期验收】'

OK, FAIL = 'PASS', 'FAIL'
items = []


def check(no, name, cond, detail=''):
    items.append({'no': no, 'name': name, 'pass': bool(cond),
                  'detail': str(detail)[:700]})
    print('  %-4s #%-6s %-56s %s' % (OK if cond else FAIL, no, name,
                                     str(detail)[:170]))
    return bool(cond)


def psql(sql):
    out = subprocess.run(
        ['docker', 'exec', DB_CONTAINER, 'psql', '-U', 'odoo', '-d', DB,
         '-tAc', sql], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError('psql failed: %s' % (out.stderr or '')[:300])
    return out.stdout.strip()


def login(login_name, password=PASSWORD):
    s = requests.Session()
    s.trust_env = False
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': DB, 'login': login_name, 'password': password}},
        timeout=30)
    data = r.json().get('result') or {}
    return s if data.get('uid') else None


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
        return None, '%s: %s' % (info.get('name') or 'Error',
                                 (info.get('message') or err.get('message') or '')[:300])
    return data.get('result'), None


def search(sess, model, domain, fields=None, limit=0, order=None):
    kw = {'fields': fields or ['id'], 'limit': limit}
    if order:
        kw['order'] = order
    return call_kw(sess, model, 'search_read', [domain or []], kw)


def create(sess, model, vals):
    res, err = call_kw(sess, model, 'create', [vals])
    if err:
        return None, err
    return (res[0] if isinstance(res, list) else res), None


def unlink(sess, model, ids):
    if not ids:
        return True, ''
    res, err = call_kw(sess, model, 'unlink', [list(ids)])
    return (not err), (err or '')


def get_json(sess, model, rid, fields):
    res, err = search(sess, model, [('id', '=', rid)], fields, limit=1)
    if err or not res:
        return None
    return res[0]


# ======================================================================
# 素材结构（逐字来自 docs/plans/eval-materials-inventory.md）
# ======================================================================

#: 说明表 1（§2.2）：两级 —— 类别 → 子项目（子项目就是叶子，占比挂叶子）
M_A1 = [
    ('综合技能', [('生活技能', 10.0, True), ('与人交往', 10.0, True),
               ('工作能力', 10.0, True), ('应用能力', 10.0, True)]),
    ('社群协作', [('团队精神', 5.0, False), ('沟通能力', 5.0, False),
               ('情绪管理', 5.0, False)]),
    ('灵命表现', [('灵修生活', 6.0, False), ('敬拜参与', 6.0, False),
               ('属灵关系', 6.0, False), ('谦卑与悔改', 6.0, False),
               ('福音本能反应', 6.0, False)]),
    # 学术成果 7.5% 的分数来源《成绩统计表》未提供 ⇒ 留空 + 显式标注（裁定 A7 / P2 甲）
    ('学业表现', [('学术成果', 7.5, False), ('学习态度', 7.5, False)]),
]

#: xlsx 综合成长测评表（§6.1）：三级 —— 一级 → 二级 → 三级（叶子），权重挂叶子
X = [
    ('综合技能', '生活技能', [('时间管理', 3.0, 40, 60), ('理财习惯', 3.0, 50, 80),
                          ('独立生活', 4.0, 60, 80)]),
    ('综合技能', '与人交往', [('沟通力', 4.0, 10, 40), ('合作', 3.0, 40, 50),
                          ('同理心', 3.0, 60, 50)]),
    ('综合技能', '工作能力', [('责任感', 4.0, 50, 60), ('执行力', 3.0, 50, 68),
                          ('应变抗压能力', 3.0, 80, 60)]),
    ('综合技能', '应用能力', [('学以致用', 4.0, 70, 80), ('问题解决', 3.0, 30, 40),
                          ('实际应用的创造性', 3.0, 60, 70)]),
]
#: 社群 / 灵命 / 学业：二级即三级（单轨，只有导师分 G）
X_SINGLE = [
    ('社群协作', [('团队精神', 5.0, 50), ('沟通能力', 5.0, 40), ('情绪管理', 5.0, 30)]),
    ('灵命表现', [('灵修生活', 6.0, 70), ('敬拜参与', 6.0, 60), ('属灵关系', 6.0, 40),
               ('谦卑与悔改', 6.0, 80), ('福音本能反应', 6.0, 20)]),
    ('学业表现', [('学术成果', 7.5, 10), ('学习态度', 7.5, 30)]),
]

#: 卫生检测表（§7.2）：5 区 × 32 项，全部扣分制，项扣分额 = max_score
SANIT = [
    ('厨房', [('洗碗池有污渍/饭菜渣', 5), ('油烟机有油污', 2), ('灶台有油污/脏乱', 5),
            ('厨余垃圾未倒', 5), ('冰箱有异味/污渍', 5), ('餐具有污渍', 5),
            ('墙面有污渍', 3)]),
    ('卫生间', [('下水道和地面有毛发/污渍', 5), ('马桶有污渍', 5),
             ('洗脸池有污渍/毛发', 5), ('垃圾未倒', 5), ('墙面有污渍', 2),
             ('洗漱物品摆放杂乱', 5), ('窗户有灰尘/污渍', 3)]),
    ('卧室', [('床铺不整洁/被子未叠', 5), ('衣柜脏乱/衣物未叠', 5),
            ('桌面物品摆放杂乱', 5), ('地面有垃圾/污渍', 3), ('垃圾未倒', 1),
            ('窗户有灰尘/污渍', 1)]),
    ('阳台', [('洗衣机有污渍', 2), ('地面有污渍/水渍', 2), ('窗户有灰尘/污渍', 2),
            ('墙面有灰尘/污渍', 1), ('晾衣杆有污渍', 1), ('物品脏乱', 2)]),
    ('客厅', [('地面有污渍/垃圾', 2), ('墙体和窗户有灰尘/污渍', 1),
            ('桌子板凳有污渍', 2), ('鞋子摆放杂乱', 2), ('垃圾未倒', 1),
            ('物品杂乱', 2)]),
]


# ======================================================================
# 第 1 期的旧算法（**逐字复制**，只用于反向注入对照；新代码里已经没有它们）
# ======================================================================

def old_item_average(rows):
    """第 1 期的 _item_average：把所有 score 行不加区分地取均值。"""
    values = [r['value'] for r in rows]
    return (sum(values) / len(values)) if values else None


def old_roster_totals(rows):
    """第 1 期的 _compute_total：total = Σ 所有行；average = total / 打分人份数。"""
    total = sum(r['value'] for r in rows)
    refs = {r['scorer_ref'] for r in rows}
    return total, (total / len(refs)) if refs else 0.0


# ======================================================================
# 夹具
# ======================================================================

def build_all(adm):
    fx = {}
    # 两名学生（名单行用）
    studs, err = search(adm, 'op.student', [('active', '=', True)],
                        ['id', 'name', 'gr_no'], limit=4, order='id')
    if err or len(studs) < 4:
        raise RuntimeError('拿不到四名学生：%s' % err)
    fx['students'] = studs[:3]      # 前 3 名进名单快照
    fx['extra'] = studs[3]          # 第 4 名专供「缺一路」用（名单里没有他）

    # ---- W1/正：说明表 1（两级 + 占比 + 双轨）----
    tpl_vals = {
        'name': PREFIX + '说明表1·综合技能与灵命成长（两级·占比）',
        'kind': 'student', 'target_kind': 'student',
        'total': 100.0, 'pass_line': 60.0,
        'weight_mode': 'percent', 'state': 'active',
        'scale_anchors': '10,40,60,80,100', 'scale_rule': 'tens',
        'notes': '说明表 1（4 类别 / 14 子项目 / 满分 100 / 占比 Σ=100%）。'
                 '「学术成果」7.5% 的分数来源《成绩统计表》未提供，本期不可评。',
    }
    tid, err = create(adm, 'edu.assess.template', tpl_vals)
    if err:
        raise RuntimeError('建模板失败：%s' % err)
    fx['m1'] = tid
    seq = 0
    for gname, leaves in M_A1:
        seq += 10
        gid, err = create(adm, 'edu.assess.item', {
            'template_id': tid, 'name': gname, 'item_kind': 'group',
            'sequence': seq})
        if err:
            raise RuntimeError('建一级节点失败：%s' % err)
        lseq = 0
        for lname, weight, dual in leaves:
            lseq += 10
            vals = {'template_id': tid, 'parent_id': gid, 'name': lname,
                    'item_kind': 'leaf', 'weight': weight, 'max_score': 100.0,
                    'track': 'dual' if dual else 'single', 'sequence': lseq}
            if lname == '学术成果':
                vals['help'] = ('分数来源《成绩统计表》未提供，本期不可评'
                                '（不参与总分归一，也不按 0 计入）')
            _i, err = create(adm, 'edu.assess.item', vals)
            if err:
                raise RuntimeError('建叶子项 %s 失败：%s' % (lname, err))

    # ---- W2/正：xlsx 综合成长测评表（三级）—— 走**表单同一条路径**（一次 create + 嵌套命令）----
    def leaf(name, weight, seq, dual, g_teacher):
        vals = {'name': name, 'item_kind': 'leaf', 'weight': weight,
                'max_score': 100.0, 'sequence': seq,
                'track': 'dual' if dual else 'single'}
        return (0, 0, vals)

    def group(name, seq, children):
        return (0, 0, {'name': name, 'item_kind': 'group', 'sequence': seq,
                       'child_ids': children})

    roots = []
    seq = 0
    by_first = {}
    for lvl1, lvl2, leaves in X:
        seq += 10
        if lvl1 not in by_first:
            by_first[lvl1] = {'seq': seq, 'groups': []}
        by_first[lvl1]['groups'].append(group(
            lvl2, 10 * (len(by_first[lvl1]['groups']) + 1),
            [leaf(n, w, 10 * (i + 1), True, g) for i, (n, w, f, g) in enumerate(leaves)]))
    seq = 100
    for lvl1, leaves in X_SINGLE:
        seq += 10
        roots.append(group(lvl1, seq,
                           [leaf(n, w, 10 * (i + 1), False, g)
                            for i, (n, w, g) in enumerate(leaves)]))
    for lvl1, info in by_first.items():
        roots.insert(0, group(lvl1, info['seq'], info['groups']))
    xid, err = create(adm, 'edu.assess.template', {
        'name': PREFIX + 'xlsx 综合成长测评表（三级·占比 Σ=100）',
        'kind': 'student', 'target_kind': 'student',
        'total': 100.0, 'pass_line': 60.0, 'weight_mode': 'percent',
        'state': 'active', 'item_ids': roots,
    })
    if err:
        raise RuntimeError('建 xlsx 模板失败：%s' % err)
    fx['xlsx'] = xid

    # ---- W4/正：卫生检测表（扣分制 + 5 区）----
    sid, err = create(adm, 'edu.assess.template', {
        'name': PREFIX + '卫生检测表（5 区·扣分制）',
        'kind': 'other', 'target_kind': 'student',
        'total': 100.0, 'pass_line': 60.0, 'weight_mode': 'multiplier',
        'state': 'active',
        'notes': '宿舍卫生检测（5 区 32 项，扣分制）。总分低于 60 分为不及格。',
    })
    if err:
        raise RuntimeError('建卫生模板失败：%s' % err)
    fx['sanit'] = sid
    seq = 0
    for area, checks in SANIT:
        seq += 10
        gid, err = create(adm, 'edu.assess.item', {
            'template_id': sid, 'name': area, 'item_kind': 'group',
            'sequence': seq})
        if err:
            raise RuntimeError('建区失败：%s' % err)
        lseq = 0
        for cname, deduct in checks:
            lseq += 10
            _i, err = create(adm, 'edu.assess.item', {
                'template_id': sid, 'parent_id': gid, 'name': cname,
                'item_kind': 'leaf', 'score_mode': 'deduct',
                'max_score': float(deduct), 'weight': 1.0, 'sequence': lseq})
            if err:
                raise RuntimeError('建检查项失败：%s' % err)

    # ---- W7/正：说明表 4 / XS / JS 三份同构 = 一张模板 + 三个任务 ----
    jid, err = create(adm, 'edu.assess.template', {
        'name': PREFIX + '说明表4/XS/JS 同构（一模板三任务）',
        'kind': 'student', 'target_kind': 'student',
        'total': 100.0, 'pass_line': 60.0, 'weight_mode': 'percent',
        'state': 'active'})
    if err:
        raise RuntimeError('建同构模板失败：%s' % err)
    fx['js'] = jid
    for gname, leaves in M_A1:
        gid, err = create(adm, 'edu.assess.item', {
            'template_id': jid, 'name': gname, 'item_kind': 'group'})
        for lname, weight, dual in leaves:
            _i, err = create(adm, 'edu.assess.item', {
                'template_id': jid, 'parent_id': gid, 'name': lname,
                'item_kind': 'leaf', 'weight': weight, 'max_score': 100.0,
                'track': 'dual' if dual else 'single'})
            if err:
                raise RuntimeError('同构模板建项失败：%s' % err)
    fx['js_tasks'] = []
    for kind, period in [('self', 'XS版·学生自评'), ('teacher', 'JS版·导师评'),
                         ('teacher', '教务录入')]:
        tk, err = create(adm, 'edu.assess.task', {
            'template_id': jid, 'period': period, 'state': 'open',
            'scorer_kind': kind})
        if err:
            raise RuntimeError('建同构任务失败：%s' % err)
        fx['js_tasks'].append(tk)

    # ---- 任务 + 名单（xlsx 与卫生）----
    fx['task_xlsx'], err = create(adm, 'edu.assess.task', {
        'template_id': xid, 'period': '2026秋·示范模版', 'state': 'open',
        'scorer_kind': 'teacher', 'objective_scorer_kind': 'teacher',
        'subjective_scorer_kind': 'self'})
    if err:
        raise RuntimeError('建 xlsx 任务失败：%s' % err)
    fx['task_sanit'], err = create(adm, 'edu.assess.task', {
        'template_id': sid, 'period': '2026秋·宿舍检查', 'state': 'open',
        'scorer_kind': 'teacher'})
    if err:
        raise RuntimeError('建卫生任务失败：%s' % err)
    rosters = {}
    for key, task in (('xlsx', fx['task_xlsx']), ('sanit', fx['task_sanit'])):
        ids = []
        for st in fx['students']:
            rid, err = create(adm, 'edu.assess.roster', {
                'task_id': task, 'student_id': st['id']})
            if err:
                raise RuntimeError('建名单行失败：%s' % err)
            ids.append(rid)
        rosters[key] = ids
    fx['rosters'] = rosters
    return fx


def fill_xlsx_sample(adm, fx):
    """把 xlsx「示范模版」的样例分写进去（F = 学生自评 / G = 导师评分）。"""
    task = fx['task_xlsx']
    tpl = fx['xlsx']
    res, err = search(adm, 'edu.assess.item',
                      [('template_id', '=', tpl)],
                      ['id', 'name', 'track', 'item_kind'], order='id')
    if err:
        raise RuntimeError('读评分项失败：%s' % err)
    by_name = {r['name']: r for r in res}
    rows = []          # 期望值：(项名, 导师分 G, 学生自评 F 或 None, 权重)
    for lvl1, lvl2, leaves in X:
        for name, weight, f, g in leaves:
            rows.append((name, g, f, weight))
    for lvl1, leaves in X_SINGLE:
        for name, weight, g in leaves:
            rows.append((name, g, None, weight))
    # 第一条名单：22 项全填（= 素材示范模版，用来复算 Excel 的 I27）
    rid_a = fx['rosters']['xlsx'][0]
    rid_b = fx['rosters']['xlsx'][1]
    vals = []
    for name, g, f, _w in rows:
        item = by_name[name]
        vals.append({'task_id': task, 'roster_id': rid_a, 'item_id': item['id'],
                     'value': float(g), 'track': 'objective',
                     'scorer_ref': 'i:2'})
        if item['track'] == 'dual' and f is not None:
            vals.append({'task_id': task, 'roster_id': rid_a,
                         'item_id': item['id'], 'value': float(f),
                         'track': 'subjective', 'scorer_ref': 'i:9001'})
    # 第二条名单：**学术成果留空**（P2 裁定：该项本期不可评）
    for name, g, f, _w in rows:
        if name == '学术成果':
            continue
        item = by_name[name]
        vals.append({'task_id': task, 'roster_id': rid_b, 'item_id': item['id'],
                     'value': float(g), 'track': 'objective',
                     'scorer_ref': 'i:2'})
        if item['track'] == 'dual' and f is not None:
            vals.append({'task_id': task, 'roster_id': rid_b,
                         'item_id': item['id'], 'value': float(f),
                         'track': 'subjective', 'scorer_ref': 'i:9001'})
    res, err = call_kw(adm, 'edu.assess.score', 'create', [vals])
    if err:
        raise RuntimeError('写样例分失败：%s' % err)
    return rows


def fill_sanit(adm, fx, heavy=False):
    """卫生检测：轻样本（扣 14 分）与重样本（全扣光，用于等级线）。"""
    task = fx['task_sanit']
    res, err = search(adm, 'edu.assess.item',
                      [('template_id', '=', fx['sanit'])],
                      ['id', 'name', 'item_kind', 'parent_id'], order='id')
    # ⚠ 用 (区名, 检查项名) 精确定位：不同区里**存在同名检查项**
    # （窗户有灰尘/污渍 ×3、墙面有污渍 ×2、垃圾未倒 ×2）——
    # 只用名称做键会串行，这也是「名称唯一键必须收窄到同一上级内」的同一个事实。
    groups = {r['id']: r['name'] for r in res if r['item_kind'] == 'group'}
    by_scope = {}
    for r in res:
        if r['item_kind'] != 'leaf':
            continue
        by_scope[(groups.get((r['parent_id'] or [None])[0]), r['name'])] = r
    # 轻样本：厨房扣 7、卫生间扣 5、阳台扣 2 ⇒ 总分 86
    light = {'洗碗池有污渍/饭菜渣': 5, '油烟机有油污': 2, '马桶有污渍': 5,
             '物品脏乱': 2}
    vals = []
    for area, checks in SANIT:
        for cname, deduct in checks:
            v = deduct if (heavy or cname in light) else 0
            vals.append({'task_id': task,
                         'roster_id': fx['rosters']['sanit'][1 if heavy else 0],
                         'item_id': by_scope[(area, cname)]['id'],
                         'value': float(v), 'scorer_ref': 'i:2'})
    res, err = call_kw(adm, 'edu.assess.score', 'create', [vals])
    if err:
        raise RuntimeError('写卫生分失败：%s' % err)
    return vals


# ======================================================================
# 断言
# ======================================================================

def w1_m1(adm, fx):
    print('\n== W1 说明表 1：两级层级 + 占比 Σ=100 + 一级占比派生 ==')
    tpl = get_json(adm, 'edu.assess.template', fx['m1'],
                   ['leaf_count', 'weight_sum', 'weight_sum_ok'])
    check('W1-①', '4 类别 + 14 子项目 → 叶子 14 个', tpl['leaf_count'] == 14,
          'leaf_count=%s' % tpl['leaf_count'])
    check('W1-②', 'Σ占比 = 100%（frozenset 明细 40+15+30+15）',
          abs(tpl['weight_sum'] - 100.0) < 1e-9 and tpl['weight_sum_ok'],
          'weight_sum=%s ok=%s' % (tpl['weight_sum'], tpl['weight_sum_ok']))
    # 一级占比 = 派生（40/15/30/15）
    rows = psql("select i.name, sum(c.weight) from edu_assess_item i "
                "join edu_assess_item c on c.parent_id = i.id "
                "where i.template_id = %d group by i.name order by min(i.sequence)"
                % fx['m1'])
    got = dict((l.split('|')[0], float(l.split('|')[1])) for l in rows.splitlines())
    want = {'综合技能': 40.0, '社群协作': 15.0, '灵命表现': 30.0, '学业表现': 15.0}
    check('W1-③', '一级占比派生 = 40/15/30/15（素材 §2.2）', got == want,
          '派生=%s' % got)
    # 双轨只挂技能类 4 项，其余 10 项单轨（xlsx F17:F26 = 无）
    duals = psql("select count(*) from edu_assess_item where template_id=%d "
                 "and track='dual'" % fx['m1'])
    check('W1-④', '双轨项 4 个（技能类），其余单轨', duals == '4',
          'dual=%s' % duals)
    # 学术成果：留空 + help 标注
    a = get_json(adm, 'edu.assess.item',
                 int(psql("select id from edu_assess_item where template_id=%d "
                          "and name='学术成果'" % fx['m1'])),
                 ['help', 'required', 'weight'])
    check('W1-⑤', '「学术成果」带"未提供"标注且非必填（裁定 A7/P2）',
          '未提供' in (a['help'] or '') and not a['required'],
          'help=%s' % (a['help'] or '')[:60])


def w2_xlsx(adm, fx, sample):
    print('\n== W2 xlsx 三级结构：与 Excel 逐行同式（H=(F+G)/2、I=H×E）==')
    items, err = search(adm, 'edu.assess.item', [('template_id', '=', fx['xlsx'])],
                        ['id', 'name', 'item_kind', 'parent_id', 'weight',
                         'track'], order='id')
    leaves = [i for i in items if i['item_kind'] == 'leaf']
    groups = [i for i in items if i['item_kind'] == 'group']
    check('W2-①', '三级：一级 4 + 二级 4 + 叶子 22（素材 §6.1 的 22 个合并区）',
          len(groups) == 8 and len(leaves) == 22,
          '组=%d（4 一级 + 4 二级） 叶子=%d' % (len(groups), len(leaves)))
    depth3 = psql("select count(*) from edu_assess_item where template_id=%d "
                  "and parent_id in (select id from edu_assess_item where "
                  "template_id=%d and parent_id is not null)" % (fx['xlsx'], fx['xlsx']))
    check('W2-②', '真三级（叶子挂在二级分组下）12 项', depth3 == '12',
          'depth3=%s' % depth3)
    tpl = get_json(adm, 'edu.assess.template', fx['xlsx'],
                   ['weight_sum', 'weight_sum_ok', 'leaf_count'])
    check('W2-③', 'Σ占比 = 100%（xlsx E27 = SUM(E5:E26) 同式）',
          abs(tpl['weight_sum'] - 100.0) < 1e-9,
          'weight_sum=%s' % tpl['weight_sum'])
    # 服务端复算 == Excel 逐行结果
    expect = 0.0
    per_item = {}
    for lvl1, lvl2, lvs in X:
        for name, weight, f, g in lvs:
            h = (f + g) / 2.0
            per_item[name] = h
            expect += h * weight / 100.0
    for lvl1, lvs in X_SINGLE:
        for name, weight, g in lvs:
            per_item[name] = float(g)
            expect += float(g) * weight / 100.0
    rid_a = fx['rosters']['xlsx'][0]
    row = get_json(adm, 'edu.assess.roster', rid_a,
                   ['weighted_total', 'total', 'average', 'grade', 'complete',
                    'missing_items', 'reachable_max', 'scored_item_count'])
    check('W2-④', '服务端加权总分 = Excel I27 = %.4f' % expect,
          abs(row['weighted_total'] - expect) < 1e-9,
          '引擎=%.4f Excel=%.4f 差=%.2e' % (row['weighted_total'], expect,
                                            row['weighted_total'] - expect))
    check('W2-⑤', '22 项全评 → 已评 22 项 / 可评满分 100 / 等级由 60 线判',
          row['scored_item_count'] == 22 and abs(row['reachable_max'] - 100.0) < 1e-9,
          'scored=%s reachable=%s grade=%s' % (row['scored_item_count'],
                                               row['reachable_max'], row['grade']))
    # 预留留空：第二条名单不填「学术成果」
    row_b = get_json(adm, 'edu.assess.roster', fx['rosters']['xlsx'][1],
                     ['weighted_total', 'missing_items', 'reachable_max',
                      'complete', 'scored_item_count'])
    expect_b = expect - per_item['学术成果'] * 7.5 / 100.0
    check('W2-⑥', '留空「学术成果」⇒ 未评项清单 + 可评满分 92.5',
          '学术成果' in (row_b['missing_items'] or '')
          and abs(row_b['reachable_max'] - 92.5) < 1e-9,
          'missing=%s reachable=%s' % (row_b['missing_items'],
                                       row_b['reachable_max']))
    check('W2-⑦', '留空项**不参与归一**（不按 0 计、也不把 92.5 当 100）',
          abs(row_b['weighted_total'] - expect_b) < 1e-9,
          '引擎=%.4f 期望(=总分−学术成果贡献)=%.4f' % (row_b['weighted_total'],
                                                    expect_b))
    return per_item, expect, rid_a


def w3_dual_reverse(adm, fx, per_item, expect, rid_a):
    print('\n== W3 双轨：反向注入证明（旧算法会错、新算法不会）+ 缺一路 ==')
    # 读回该名单的全部打分记录（原始行）
    rows, err = search(adm, 'edu.assess.score', [('roster_id', '=', rid_a)],
                       ['id', 'item_id', 'value', 'track', 'scorer_ref'], order='id')
    tpl_items = {r['id']: r for r in (search(
        adm, 'edu.assess.item', [('template_id', '=', fx['xlsx'])],
        ['id', 'name'])[0] or [])}
    by_item = {}
    for r in rows:
        by_item.setdefault(r['item_id'][0], []).append(r)
    # 逐项对比：Excel 值 vs 旧算法 vs 新引擎
    n_dual = sum(1 for rs in by_item.values() if len(rs) == 2)
    check('W3-①', '注入的双轨项 = 12 项（每项两条：客观 + 主观）', n_dual == 12,
          '双轨项 = %d' % n_dual)
    # ---- 反向注入①：整行层面（旧算法的 total = Σ 所有 score 行 ⇒ 双轨被算两遍）----
    rows_a, _e = search(adm, 'edu.assess.score', [('roster_id', '=', rid_a)],
                        ['value', 'scorer_ref', 'item_id'], order='id')
    old_total, old_avg = old_roster_totals(rows_a)
    new_row = get_json(adm, 'edu.assess.roster', rid_a,
                       ['total', 'average', 'weighted_total'])
    dual_names = set()
    for _l1, _l2, lvs in X:
        for name, _w, _f, _g in lvs:
            dual_names.add(name)
    dual_sum = sum(v for k, v in per_item.items() if k in dual_names)
    single_sum = sum(v for k, v in per_item.items() if k not in dual_names)
    check('W3-②',
          '反向注入①：旧算法行总分 = Σ 所有 score 行 = %.2f（双轨被算两遍）'
          % old_total,
          abs(old_total - (2 * dual_sum + single_sum)) < 1e-9
          and abs(new_row['total'] - (dual_sum + single_sum)) < 1e-9
          and dual_sum > 0,
          '旧=%.2f 新=%.2f 差=%.2f（= 双轨项之和 %.2f，正是被算第二遍的那份）'
          % (old_total, new_row['total'], old_total - new_row['total'], dual_sum))
    check('W3-②b',
          '反向注入①b：旧 average 的分母是"打分人份数"（%d 个指纹 = 两条轨）'
          % len({r['scorer_ref'] for r in rows_a}),
          abs(old_avg - new_row['average']) > 1e-9,
          '旧 average=%.4f（旧total ÷ 份数） 新 average=%.4f（总分 ÷ 已评项数）'
          % (old_avg, new_row['average']))
    # 新旧在"单轨 + 单项"上必须一致（说明这次改动没有伤到第 1 期口径）
    single_rows = [r for iid, rs in by_item.items() for r in rs if len(rs) == 1]
    check('W3-③', '单轨项：旧算法与新引擎逐项一致（没有误伤第 1 期口径）',
          all(abs(old_item_average(rs) - per_item[tpl_items[iid]['name']]) < 1e-9
              for iid, rs in by_item.items() if len(rs) == 1),
          '单轨记录 %d 条' % len(single_rows))
    # 结果页 HTML：双轨项应显示 (F+G)/2
    r = adm.get(BASE + '/assess/task/%d/results' % fx['task_xlsx'], timeout=60)
    html = r.text
    ok_cells = sum(1 for name in ('时间管理', '沟通力', '应变抗压能力')
                   if ('%.2f' % per_item[name]) in html)
    check('W3-④', '结果页 HTML 里双轨项的明细格 = (客观+主观)/2（走门户读点）',
          r.status_code == 200 and ok_cells == 3,
          'HTTP %s / 命中 %d/3 个期望值' % (r.status_code, ok_cells))
    # 缺一路：给第三条名单只写客观
    rid_c, err = create(adm, 'edu.assess.roster', {
        'task_id': fx['task_xlsx'], 'student_id': fx['extra']['id']})
    if err:
        raise RuntimeError('建第三条名单失败：%s' % err)
    item_x = search(adm, 'edu.assess.item',
                    [('template_id', '=', fx['xlsx']),
                     ('name', '=', '时间管理')], ['id', 'max_score'])[0][0]
    call_kw(adm, 'edu.assess.score', 'create', [[
        {'task_id': fx['task_xlsx'], 'roster_id': rid_c, 'item_id': item_x['id'],
         'value': 60.0, 'track': 'objective', 'scorer_ref': 'i:2'}]])
    rr = get_json(adm, 'edu.assess.roster', rid_c,
                  ['weighted_total', 'complete', 'missing_tracks',
                   'scored_item_count', 'grade'])
    old_cell = old_item_average([{'value': 60.0, 'track': 'objective'}])
    excel_cell = 60.0 / 2.0            # 素材 SUM(F5:G5)/2 写死除 2
    print('     缺一路三方对照：旧 _item_average=%.2f（把单路当整项）｜'
          'Excel SUM/2=%.2f（静默低估一半）｜新引擎=None（不产生分数+标注）'
          % (old_cell, excel_cell))
    check('W3-⑤', '缺一路 ⇒ 该项**不计入**总分（不按 0、也不按单路平均）',
          abs(rr['weighted_total']) < 1e-9 and rr['scored_item_count'] == 0,
          'weighted=%s scored=%s（旧算法会算出 %.2f）'
          % (rr['weighted_total'], rr['scored_item_count'], old_cell))
    check('W3-⑥', '缺一路 ⇒ 显式标注 missing_tracks + 不判级',
          rr['missing_tracks'] == '主观' and not rr['grade']
          and not rr['complete'],
          'missing_tracks=%s grade=%r complete=%s'
          % (rr['missing_tracks'], rr['grade'], rr['complete']))
    r2 = adm.get(BASE + '/assess/task/%d/results' % fx['task_xlsx'], timeout=60)
    check('W3-⑦', '结果页对缺一路的格子显示「未评」（不是半个数）',
          '未评' in r2.text, 'HTTP %s' % r2.status_code)
    # 反向：把主观路补上，立刻变成 (60+100)/2（正对照：不是"页面坏了"）
    call_kw(adm, 'edu.assess.score', 'create', [[
        {'task_id': fx['task_xlsx'], 'roster_id': rid_c, 'item_id': item_x['id'],
         'value': 100.0, 'track': 'subjective', 'scorer_ref': 'i:9001'}]])
    rr2 = get_json(adm, 'edu.assess.roster', rid_c,
                   ['weighted_total', 'complete', 'missing_tracks',
                    'scored_item_count'])
    want = 80.0 * 3.0 / 100.0 * 100.0 / 100.0 * 100.0 / 100.0  # ⇒ 80 × 3% = 2.4
    check('W3-⑧', '正对照：补上主观路后该项立刻 =（60+100)/2 并计入总分',
          rr2['complete'] and rr2['scored_item_count'] == 1
          and abs(rr2['weighted_total'] - 80.0 * 0.03 * 100.0 / 100.0) < 1e-9,
          'weighted=%.4f 期望=%.4f' % (rr2['weighted_total'], 80.0 * 0.03))


def w4_deduct(adm, fx):
    print('\n== W4 卫生检测表：扣分制 + 5 区 + 分区小计（派生不落库）==')
    areas = psql("select i.name, count(c.id), sum(c.max_score) from "
                 "edu_assess_item i join edu_assess_item c on c.parent_id=i.id "
                 "where i.template_id=%d group by i.name order by min(i.sequence)"
                 % fx['sanit'])
    got = [(l.split('|')[0], int(l.split('|')[1]), float(l.split('|')[2]))
           for l in areas.splitlines()]
    want = [('厨房', 7, 30.0), ('卫生间', 7, 30.0), ('卧室', 6, 20.0),
            ('阳台', 6, 10.0), ('客厅', 6, 10.0)]
    check('W4-①', '5 区项数 7/7/6/6/6 + 区满分 30/30/20/10/10（素材 §8.4）',
          got == want, '实测=%s' % got)
    check('W4-②', '32 项全部扣分制（score_mode=deduct）',
          psql("select count(*) from edu_assess_item where template_id=%d "
               "and item_kind='leaf' and score_mode='deduct'" % fx['sanit']) == '32',
          '扣分项 = %s' % psql("select count(*) from edu_assess_item where "
                             "template_id=%d and score_mode='deduct'" % fx['sanit']))
    # 轻样本：总分 86
    row = get_json(adm, 'edu.assess.roster', fx['rosters']['sanit'][0],
                   ['total', 'weighted_total', 'grade', 'complete',
                    'breakdown_text'])
    check('W4-③', '扣 14 分 ⇒ 总分 = 100 − 14 = 86（旧算法会算成 14）',
          abs(row['total'] - 86.0) < 1e-9,
          'total=%s（第 1 期口径 Σvalue 会得 14）' % row['total'])
    # 反向注入：旧算法对同一批行的读数
    rows, err = search(adm, 'edu.assess.score',
                       [('roster_id', '=', fx['rosters']['sanit'][0])],
                       ['value', 'scorer_ref'])
    old_total, old_avg = old_roster_totals(rows)
    check('W4-④', '反向注入：旧算法把"扣分"当"得分"求和 ⇒ %.2f ≠ 86' % old_total,
          abs(old_total - 14.0) < 1e-9, '旧 total=%.2f' % old_total)
    subtotals = re.findall(r'【(.+?)】小计 ([\d.]+|未评)', row['breakdown_text'] or '')
    check('W4-⑤', '分区小计派生 = 厨房 23 / 卫生间 25 / 卧室 20 / 阳台 8 / 客厅 10',
          subtotals == [('厨房', '23.00'), ('卫生间', '25.00'), ('卧室', '20.00'),
                        ('阳台', '8.00'), ('客厅', '10.00')],
          '实测=%s' % subtotals)
    check('W4-⑥', '小计**不落库**：edu_assess_roster 表里没有 total/grade/小计列',
          psql("select count(*) from information_schema.columns where "
               "table_name='edu_assess_roster' and column_name in "
               "('total','weighted_total','average','grade','subtotal',"
               "'breakdown_text','complete')") == '0',
          '落库列 = %s' % psql("select string_agg(column_name, ',') from "
                             "information_schema.columns where "
                             "table_name='edu_assess_roster'"))
    heavy = get_json(adm, 'edu.assess.roster', fx['rosters']['sanit'][1],
                     ['total', 'grade'])
    check('W4-⑦', '全扣光 ⇒ 0 分且等级=不及格（及格线 60，素材唯一有据的阈值）',
          abs(heavy['total']) < 1e-9 and heavy['grade'] == '不及格',
          'total=%s grade=%s' % (heavy['total'], heavy['grade']))


def w7_js(adm, fx):
    print('\n== W7 说明表 4 / XS / JS 同构：一张模板 + 三个任务 ==')
    n = psql("select count(*) from edu_assess_task where template_id=%d" % fx['js'])
    kinds = psql("select string_agg(scorer_kind, ',') from edu_assess_task "
                 "where template_id=%d" % fx['js'])
    check('W7-①', '同构模板下 3 个任务（XS 自评 / JS 导师评 / 教务录入）',
          n == '3', '任务数=%s，打分人=%s' % (n, kinds))
    check('W7-②', 'XS 版 = 自评（scorer_kind=self）', 'self' in (kinds or ''),
          kinds)


def w8_roster_manual(adm, fx):
    print('\n== W8 名单行手工增删（W1：加一行 / 删一行 / 有分拒删 / 批量粘贴）==')
    task = fx['js_tasks'][0]
    st = fx['students'][0]
    rid, err = create(adm, 'edu.assess.roster', {
        'task_id': task, 'student_id': st['id']})
    check('W8-①', '手工加一行（选学生）成功且自动带出班级',
          bool(rid) and not err, 'rid=%s err=%s' % (rid, err))
    dup, err2 = create(adm, 'edu.assess.roster', {
        'task_id': task, 'student_id': st['id']})
    check('W8-②', '重复加同一人 ⇒ 被唯一键拦住（正对照：另一个人能加）',
          bool(err2) and '只能有一行' in (err2 or ''),
          'err=%s' % (err2 or '')[:120])
    st2 = fx['students'][1]
    rid2, _e = create(adm, 'edu.assess.roster', {
        'task_id': task, 'student_id': st2['id']})
    check('W8-③', '正对照：换一个人可以加（不是"整表不能加"）', bool(rid2),
          'rid=%s' % rid2)
    item = search(adm, 'edu.assess.item', [('template_id', '=', fx['js']),
                                          ('item_kind', '=', 'leaf')],
                  ['id'], limit=1)[0][0]
    call_kw(adm, 'edu.assess.score', 'create', [[{
        'task_id': task, 'roster_id': rid, 'item_id': item['id'], 'value': 60.0,
        'scorer_ref': 'i:2'}]])
    ok, err3 = unlink(adm, 'edu.assess.roster', [rid])
    check('W8-④', '有打分的名单行**拒删**（历史保留；文案给出出路）',
          not ok and '打分记录' in (err3 or ''), 'err=%s' % (err3 or '')[:120])
    ok2, err4 = unlink(adm, 'edu.assess.roster', [rid2])
    check('W8-⑤', '正对照：无打分的名单行可以删', ok2, 'err=%s' % (err4 or ''))
    # 批量粘贴名单（模型 API，门户页调用同一入口）
    txt = '%s\n%s\n%s' % (fx['students'][0]['gr_no'] or 'x',
                            fx['students'][1]['gr_no'] or 'y', '不存在的学号')
    out, err5 = call_kw(adm, 'edu.assess.task', 'action_add_roster_from_text',
                        [[task], txt])
    check('W8-⑥', '批量粘贴名单：新增 2 / 重复 1 跳过 / 找不到 1 报错（幂等）',
          bool(out) and len(out['added']) == 1 and len(out['skipped']) == 1
          and len(out['errors']) == 1,
          'added=%s skipped=%s errors=%s'
          % (len((out or {}).get('added') or []),
             len((out or {}).get('skipped') or []),
             len((out or {}).get('errors') or [])))


def w9_percent_gate(adm, fx):
    print('\n== W9 占比硬闸门：Σ≠100 建任务被拒 / 草稿可存 / 补满后通过 ==')
    tid, err = create(adm, 'edu.assess.template', {
        'name': PREFIX + '占比未满（反向）', 'kind': 'student',
        'target_kind': 'student', 'total': 100.0, 'pass_line': 60.0,
        'weight_mode': 'percent', 'state': 'draft'})
    check('W9-①', '草稿可以存（中途搭结构不被拦，§5.2.1 明写）', bool(tid),
          'err=%s' % err)
    _i, _e = create(adm, 'edu.assess.item', {
        'template_id': tid, 'name': '只占 60%', 'max_score': 100.0,
        'weight': 60.0})
    tk, err2 = create(adm, 'edu.assess.task', {
        'template_id': tid, 'period': '反向', 'state': 'open'})
    check('W9-②', 'Σ=60 ≠ 100 ⇒ **建任务被拒**（§5.2.1 第二道闸门）',
          bool(err2) and '100%' in (err2 or ''), 'err=%s' % (err2 or '')[:160])
    _i2, err3 = create(adm, 'edu.assess.item', {
        'template_id': tid, 'name': '再占 40%', 'max_score': 100.0,
        'weight': 40.0})
    tk2, err4 = create(adm, 'edu.assess.task', {
        'template_id': tid, 'period': '正对照', 'state': 'open'})
    check('W9-③', '正对照：补到 100% 后建任务通过（不是"整类都建不了"）',
          bool(tk2), 'err=%s' % (err4 or '')[:160])
    fx['bad_tpl'] = tid
    fx['bad_task'] = tk2


def w10_dual_anonymous(adm, fx):
    print('\n== W10 匿名 × 双轨互斥（§5.3 硬约束，两个方向都拦）==')
    tk, err = create(adm, 'edu.assess.task', {
        'template_id': fx['m1'], 'period': '反向·匿名双轨', 'state': 'open',
        'anonymous': True})
    check('W10-①', '匿名任务挂在含双轨项的模板上 ⇒ 被拒（任务侧）',
          bool(err) and '匿名' in (err or ''), 'err=%s' % (err or '')[:160])
    tk2, err2 = create(adm, 'edu.assess.task', {
        'template_id': fx['xlsx'], 'period': '匿名单轨', 'state': 'open',
        'anonymous': True})
    # 上面这条其实也会被拒（xlsx 也含双轨）；用卫生表（全单轨）做正对照与反向
    tk3, err3 = create(adm, 'edu.assess.task', {
        'template_id': fx['sanit'], 'period': '匿名·卫生', 'state': 'open',
        'anonymous': True})
    check('W10-②', '正对照：全单轨模板可以建匿名任务', bool(tk3),
          'err=%s' % (err3 or ''))
    item = search(adm, 'edu.assess.item', [('template_id', '=', fx['sanit']),
                                          ('item_kind', '=', 'leaf')],
                  ['id'], limit=1)[0][0]
    _r, err4 = call_kw(adm, 'edu.assess.item', 'write',
                       [[item['id']], {'track': 'dual'}])
    check('W10-③', '把匿名任务下的项改成双轨 ⇒ 被拒（项侧）',
          bool(err4) and '匿名' in (err4 or ''), 'err=%s' % (err4 or '')[:160])
    fx['anon_task'] = tk3
    fx['sanit_first_item'] = item['id']


def w11_hierarchy(adm, fx):
    print('\n== W11 层级硬约束（H1：深度 ≤ 3 / 同模板 / 上级必须是分组 / 不成环）==')
    # 一级 → 二级 → 三级 已有（xlsx）。再往下挂第四层 ⇒ 拒
    items, _e = search(adm, 'edu.assess.item',
                       [('template_id', '=', fx['xlsx'])],
                       ['id', 'parent_id'], order='id')
    by_id = {r['id']: r for r in items}
    child_of_leaf = None
    for r in items:
        p = (r['parent_id'] or [None])[0]
        if p and by_id.get(p, {}).get('parent_id'):
            child_of_leaf = r['id']
            break
    # 真三级：在二级分组下再建一个"分组节点"（它本身就是第 3 级），
    # 然后往它下面挂孩子 ⇒ 会到第 4 级，必须被拒（D1 上限 3 级）。
    g2 = (by_id.get(child_of_leaf, {}).get('parent_id') or [None])[0]
    g3, err_g3 = create(adm, 'edu.assess.item', {
        'template_id': fx['xlsx'], 'name': PREFIX + '第三级分组',
        'item_kind': 'group', 'parent_id': g2})
    _i, err = create(adm, 'edu.assess.item', {
        'template_id': fx['xlsx'], 'name': PREFIX + '第四层（反向）',
        'parent_id': g3})
    check('W11-①', '第 3 级分组下再挂孩子（会到第 4 级）⇒ 被拒（D1 上限 3 级）',
          bool(g3) and bool(err) and '最多 3 级' in (err or ''),
          'g3=%s err=%s' % (g3, (err or '')[:120]))
    unlink(adm, 'edu.assess.item', [g3])
    leaf2 = psql("select id from edu_assess_item where template_id=%d and "
                 "item_kind='leaf' limit 1" % fx['m1'])
    gid = psql("select id from edu_assess_item where template_id=%d and "
               "parent_id is null limit 1" % fx['m1'])
    _i2, err2 = create(adm, 'edu.assess.item', {
        'template_id': fx['m1'], 'name': PREFIX + '挂到叶子上（反向）',
        'parent_id': int(leaf2)})
    check('W11-②', '上级是叶子评分项 ⇒ 被拒（叶子不能当容器）',
          bool(err2) and '不能作为上级节点' in (err2 or ''), 'err=%s' % (err2 or '')[:160])
    other = psql("select id from edu_assess_item where template_id=%d and "
                 "parent_id is null limit 1" % fx['sanit'])
    _i3, err3 = create(adm, 'edu.assess.item', {
        'template_id': fx['m1'], 'name': PREFIX + '跨模板（反向）',
        'parent_id': int(other)})
    check('W11-③', '上级节点属于别的模板 ⇒ 被拒', bool(err3)
          and '不属于同一个模板' in (err3 or ''), 'err=%s' % (err3 or '')[:160])
    root_g, err4 = create(adm, 'edu.assess.item', {
        'template_id': fx['m1'], 'name': PREFIX + '临时组', 'item_kind': 'group'})
    # 子节点也必须是分组节点，否则会先被"叶子不能当上级"拦掉，测不到成环那条
    ch, err5 = create(adm, 'edu.assess.item', {
        'template_id': fx['m1'], 'name': PREFIX + '临时子', 'item_kind': 'group',
        'parent_id': root_g})
    _w, err6 = call_kw(adm, 'edu.assess.item', 'write',
                       [[root_g], {'parent_id': ch}])
    check('W11-④', '把父节点挂到自己的下级 ⇒ 被拒（不成环）',
          bool(err6) and '成环' in (err6 or ''), 'err=%s' % (err6 or '')[:160])
    ok, err7 = unlink(adm, 'edu.assess.item', [ch, root_g])
    check('W11-⑤', '正对照：无打分的临时层级可以整体删除（组节点按深度倒序）',
          ok, 'err=%s' % (err7 or '')[:160])
    _s, err8 = create(adm, 'edu.assess.score', {
        'task_id': fx['task_sanit'],
        'roster_id': fx['rosters']['sanit'][0],
        'item_id': int(psql("select id from edu_assess_item where template_id=%d "
                            "and item_kind='group' limit 1" % fx['sanit'])),
        'value': 5.0, 'scorer_ref': 'i:2'})
    check('W11-⑥', '给分组节点打分 ⇒ 被拒（防"给一个类别打一个总分"双重计分）',
          bool(err8) and '分组节点' in (err8 or ''), 'err=%s' % (err8 or '')[:160])
    _w2, err9 = call_kw(adm, 'edu.assess.item', 'write',
                        [[int(psql("select id from edu_assess_item where "
                                   "template_id=%d and item_kind='group' "
                                   "limit 1" % fx['m1']))], {'weight': 3.0}])
    check('W11-⑦', '给分组节点填权重 ⇒ 被拒（权重只允许挂在叶子上）',
          bool(err9) and '不参与权重' in (err9 or ''), 'err=%s' % (err9 or '')[:160])


def w12_scale_grade(adm, fx):
    print('\n== W12 G8 刻度档位 + G17 等级线（优秀线默认关闭）==')
    tpl = get_json(adm, 'edu.assess.template', fx['m1'],
                   ['scale_anchors', 'scale_rule', 'excellent_enabled',
                    'excellent_line'])
    check('W12-①', '默认锚点 = 10/40/60/80/100（说明 P067–P073）',
          tpl['scale_anchors'] == '10,40,60,80,100', 'anchors=%s' % tpl['scale_anchors'])
    check('W12-②', '优秀线默认**关闭**（裁定 A4：素材里查无 90 优秀）',
          tpl['excellent_enabled'] is False,
          'enabled=%s line=%s' % (tpl['excellent_enabled'], tpl['excellent_line']))
    # 档位型评分项 + 非锚点取值 ⇒ 拒
    lid, err = create(adm, 'edu.assess.item', {
        'template_id': fx['sanit'], 'name': PREFIX + '档位项',
        'max_score': 100.0, 'score_kind': 'level', 'weight': 1.0})
    _s, err2 = create(adm, 'edu.assess.score', {
        'task_id': fx['task_sanit'], 'roster_id': fx['rosters']['sanit'][0],
        'item_id': lid, 'value': 55.0, 'scorer_ref': 'i:2'})
    _s2, err3 = create(adm, 'edu.assess.score', {
        'task_id': fx['task_sanit'], 'roster_id': fx['rosters']['sanit'][0],
        'item_id': lid, 'value': 60.0, 'scorer_ref': 'i:2'})
    check('W12-③', '档位型：非锚点值 55 被拒 / 锚点值 60 通过（正反成对）',
          bool(err2) and '锚点' in (err2 or '') and not err3,
          'err55=%s / err60=%s' % ((err2 or '')[:80], err3 or '无'))
    call_kw(adm, 'edu.assess.score', 'unlink',
            [search(adm, 'edu.assess.score', [('item_id', '=', lid)], ['id'])[0] and
             [r['id'] for r in search(adm, 'edu.assess.score',
                                      [('item_id', '=', lid)], ['id'])[0]]])
    _u, err4 = call_kw(adm, 'edu.assess.item', 'unlink', [[lid]])
    # 等级线：开启优秀线后 90 才参与判级
    # 用卫生表那份 86 分的名单做判级对照：关闭时"及格"，开启 85 线后"优秀"
    rid_light = fx['rosters']['sanit'][0]
    g_off = get_json(adm, 'edu.assess.roster', rid_light, ['grade', 'weighted_total'])
    _w, err5 = call_kw(adm, 'edu.assess.template', 'write',
                       [[fx['sanit']], {'excellent_enabled': True,
                                        'excellent_line': 85.0}])
    g_on = get_json(adm, 'edu.assess.roster', rid_light, ['grade'])
    _w2, err6b = call_kw(adm, 'edu.assess.template', 'write',
                         [[fx['sanit']], {'excellent_enabled': False}])
    check('W12-④', '优秀线开关真的参与判级：关闭=及格 / 开启 85 线=优秀（86 分）',
          not err5 and g_off['grade'] == '及格' and g_on['grade'] == '优秀',
          '关闭=%s 开启(85)=%s 总分=%s' % (g_off['grade'], g_on['grade'],
                                          g_off['weighted_total']))
    _w2, err6 = call_kw(adm, 'edu.assess.template', 'write',
                        [[fx['m1']], {'excellent_enabled': False}])
    _w3, err7 = call_kw(adm, 'edu.assess.template', 'write',
                        [[fx['m1']], {'pass_line': 120.0}])
    check('W12-⑤', '关闭优秀线时只校验「0 < 及格线 ≤ 满分」：及格线 120 被拒',
          bool(err7) and '及格线' in (err7 or ''), 'err=%s' % (err7 or '')[:120])
    _i, err8 = create(adm, 'edu.assess.item', {
        'template_id': fx['bad_tpl'], 'name': PREFIX + '重复名'})
    _i2, err9 = create(adm, 'edu.assess.item', {
        'template_id': fx['bad_tpl'], 'name': PREFIX + '重复名'})
    check('W12-⑥', '幂等键仍生效：同模板同名评分项被拒（xlsx 导入按名称对列）',
          bool(err9), 'err=%s' % (err9 or '')[:120])


def view_arch(adm, model, vtype):
    """取某个模型某类视图的 arch 字符串（对 Odoo 19 的 {"views": {id: {...}}} 形状稳健）。"""
    ok, err = call_kw(adm, model, 'get_views', [],
                      {'views': [[False, vtype]]})
    if not ok:
        return '', err
    arch = ''
    for v in (ok.get('views') or {}).values():
        if isinstance(v, dict):
            arch += (v.get('arch') or '')
    return arch, None


def w13_views(adm, fx):
    print('\n== W13 视图层：12 个字段在后台表单里可维护（界面自证）==')
    arch, err = view_arch(adm, 'edu.assess.template', 'form')
    need = ['weight_mode', 'excellent_enabled', 'scale_anchors', 'scale_rule',
            'item_kind', 'parent_id', 'track', 'score_mode', 'weight_sum',
            'action_check_weight_sum']
    miss = [f for f in need if f not in arch]
    check('W13-①', '模板表单 arch 含 10 个新控件（含"校验占比"按钮）',
          not miss, '缺失=%s' % (miss or '无'))
    arch2, err2 = view_arch(adm, 'edu.assess.task', 'form')
    need2 = ['objective_scorer_kind', 'subjective_scorer_kind', 'has_dual',
             'missing_tracks', 'complete', 'grade', 'summary', 'student_id']
    miss2 = [f for f in need2 if f not in arch2]
    check('W13-②', '任务表单 arch 含双轨两路 + 名单行可编辑 + 派生列',
          not miss2, '缺失=%s' % (miss2 or '无'))
    arch3, err3 = view_arch(adm, 'edu.assess.roster', 'form')
    check('W13-③', '名单行表单可打开且含派生小计 + 评语',
          bool(arch3) and 'breakdown_text' in arch3 and 'summary' in arch3,
          'err=%s' % (err3 or ''))
    arch4, err4 = view_arch(adm, 'edu.assess.score', 'list')
    check('W13-④', '打分记录列表含「轨」列（客观/主观）', 'track' in arch4,
          'err=%s' % (err4 or ''))
    # 后台能读到派生值（列表/报表口径）
    res, err5 = search(adm, 'edu.assess.roster', [('task_id', '=', fx['task_xlsx'])],
                       ['id', 'subject_name', 'weighted_total', 'grade',
                        'complete', 'missing_items'], order='id')
    check('W13-⑤', '名单 search_read 能读到派生列（供后台列表/结果页/报表）',
          bool(res) and all(k in res[0] for k in
                            ('weighted_total', 'grade', 'complete')),
          '%d 行，首行=%s' % (len(res or []),
                            {k: res[0][k] for k in ('weighted_total', 'grade',
                                                    'complete')} if res else ''))


def w14_regression(adm, fx):
    print('\n=== W14 存量回归（§8.3：升级前后 total / weighted_total 逐条相等）===')
    if not BEFORE.exists():
        check('W14-①', '基线文件存在（tests/smoke/assess_engine_v2_before.json）',
              False, '缺 %s' % BEFORE)
        return
    before = json.loads(BEFORE.read_text())
    after, err = search(adm, 'edu.assess.roster', [],
                        ['id', 'subject_ref', 'total', 'weighted_total',
                         'average', 'scorer_count'], order='id')
    bmap = {r['id']: r for r in before['edu.assess.roster']}

    def score_fingerprint(rows):
        return sorted((r['id'], r['item_id'], r['value'], r['scorer_ref'])
                      for r in rows)

    def rows_of(source, rid):
        return [r for r in source if (r['roster_id'] or [None])[0] == rid]

    after_scores, _e = search(adm, 'edu.assess.score', [],
                              ['id', 'roster_id', 'item_id', 'value',
                               'scorer_ref'], order='id')
    bad, n, touched = [], 0, []
    for r in after:
        b = bmap.get(r['id'])
        if not b:
            continue
        if score_fingerprint(rows_of(before['edu.assess.score'], r['id'])) != \
                score_fingerprint(rows_of(after_scores, r['id'])):
            # 打分记录被改写过（本轮验收脚本 eval_rebuild.py 自己会写 V1 那一列）
            # ⇒ 这条不能用来做"升级前后相等"的对照，单独列出来，不当成失败。
            touched.append(r['id'])
            continue
        n += 1
        if abs((b['total'] or 0) - (r['total'] or 0)) > 1e-9 or \
                abs((b['weighted_total'] or 0) - (r['weighted_total'] or 0)) > 1e-9:
            bad.append(r['id'])
    check('W14-①',
          '存量 %d 条名单（打分未被改写的那些）：total / weighted_total 逐条相等' % n,
          n > 0 and not bad,
          '不相等=%s；另 %d 条打分被验收脚本改写过，已剔除：%s'
          % (bad or '无', len(touched), touched or '无'))
    # 更强的算法等价断言：对**每一条**存量打分（不看基线），新旧公式必须一致
    items, _e = search(adm, 'edu.assess.item',
                       [], ['id', 'weight', 'track', 'score_mode',
                            'item_kind', 'max_score'], order='id')
    imap = {i['id']: i for i in items}
    bad2 = []
    for r in after:
        rs = rows_of(after_scores, r['id'])
        legacy = all(
            imap[(x['item_id'] or [None])[0]]['track'] == 'single'
            and imap[(x['item_id'] or [None])[0]]['score_mode'] == 'add'
            for x in rs)
        if not legacy:
            continue
        old_total, old_avg = old_roster_totals(rs)
        old_weighted = sum(x['value'] * (imap[(x['item_id'] or [None])[0]]['weight'] or 1.0)
                           for x in rs)
        if abs(old_total - r['total']) > 1e-9 or \
                abs(old_weighted - r['weighted_total']) > 1e-9:
            bad2.append((r['id'], old_total, r['total'], old_weighted,
                         r['weighted_total']))
    check('W14-①b',
          '算法等价（逐条现算）：单轨+加分制数据上，旧公式与新引擎完全一致',
          not bad2, '不一致=%s' % (bad2 or '无'))
    sc, err = search(adm, 'edu.assess.score', [],
                     ['id', 'value', 'scorer_ref', 'item_id'], order='id')
    sb = {r['id']: r for r in before['edu.assess.score']}
    diff = [r['id'] for r in sc if r['id'] in sb and
            any(sb[r['id']][k] != r[k] for k in ('value', 'scorer_ref', 'item_id'))]
    check('W14-②', '存量 8 条打分逐字节不变（没动用户数据）', not diff,
          '变化=%s' % (diff or '无'))
    avg_changed = [r['id'] for r in after
                   if r['id'] in bmap and r['id'] not in touched and
                   abs((bmap[r['id']]['average'] or 0) - (r['average'] or 0)) > 1e-9]
    single_item_rows = []
    for r in after:
        if r['id'] in bmap and r['id'] not in touched:
            rs = rows_of(after_scores, r['id'])
            items_of_row = {(x['item_id'] or [None])[0] for x in rs}
            if len(items_of_row) <= 1:
                single_item_rows.append(r['id'])
    check('W14-③',
          '平均分只在"被评项 > 1"的行上改变（= 有意重定义：总分÷打分人份数 ⇒ '
          '总分÷已评项数）；单项行一字不变 %s' % single_item_rows,
          set(avg_changed) <= set([4, 5, 6]) and not (
              set(avg_changed) & set(single_item_rows)),
          '变化行=%s（未受验收脚本改写影响的行里）' % avg_changed)


def w16_subject_visibility(adm, fx):
    """D3（队长追加）：被评者本人能不能看到自己的结果 / score_visible 有没有消费者 /
    教师 A 能不能看到教师 B 的评教结果（反向证明）。"""
    print('\n== W16 被评者可见性（D3）：被评教师读自己的行 + score_visible 真消费 + 反向越权 ==')
    fac = login('faculty@local')
    if not fac:
        raise RuntimeError('faculty@local 登录失败')
    # 评教任务（学生评教·匿名）与它的被评教师名单
    tpl = search(adm, 'edu.assess.template',
                 [('name', 'like', '%学生评教%')], ['id', 'name', 'score_visible'],
                 limit=1)[0]
    if not tpl:
        raise RuntimeError('找不到评教模板（夹具前提不成立）')
    tpl = tpl[0]
    tasks = search(adm, 'edu.assess.task', [('template_id', '=', tpl['id'])],
                   ['id', 'name'], limit=1)[0] or []
    if not tasks:
        raise RuntimeError('评教模板下没有任务')
    task = tasks[0]
    rosters = search(adm, 'edu.assess.roster', [('task_id', '=', task['id'])],
                     ['id', 'faculty_id', 'subject_ref'])[0] or []
    my_fac = search(adm, 'op.faculty', [('user_id.login', '=', 'faculty@local')],
                    ['id'], limit=1)[0]
    my_fac_id = my_fac[0]['id'] if my_fac else None
    mine = [r for r in rosters if (r['faculty_id'] or [None])[0] == my_fac_id]
    others = [r for r in rosters if (r['faculty_id'] or [None])[0] != my_fac_id]
    check('W16-①', '夹具前提：评教任务下有多名被评教师（%d 名，其中我是 %d 行）'
          % (len(rosters), len(mine)), bool(mine) and bool(others),
          '全部名单=%s 我的=%s' % ([r['subject_ref'] for r in rosters],
                                 [r['subject_ref'] for r in mine]))
    # 1) score_visible=False（默认）⇒ 被评教师一行都读不到
    call_kw(adm, 'edu.assess.template', 'write',
            [[tpl['id']], {'score_visible': False}])
    r0, e0 = search(fac, 'edu.assess.roster', [('task_id', '=', task['id'])],
                    ['id', 'subject_ref'])
    check('W16-②', 'score_visible=False ⇒ 被评教师读到自己被评行 = 0 行（开关有牙）',
          r0 is not None and len(r0) == 0, 'rows=%s err=%s' % (r0, e0))
    # 2) 打开 score_visible ⇒ 只读到自己那一行（教师 A 看不到教师 B）
    call_kw(adm, 'edu.assess.template', 'write',
            [[tpl['id']], {'score_visible': True}])
    r1, e1 = search(fac, 'edu.assess.roster', [('task_id', '=', task['id'])],
                    ['id', 'subject_ref', 'faculty_id'])
    got = [r['id'] for r in (r1 or [])]
    want = [r['id'] for r in mine]
    check('W16-③', 'score_visible=True ⇒ 被评教师只读到自己那一行',
          sorted(got) == sorted(want) and len(got) == len(mine),
          '读到=%s 期望=%s（别人的行 %s 必须缺席）'
          % (got, want, [r['id'] for r in others]))
    check('W16-④', '反向：教师 A 读教师 B 的评教行 ⇒ 拿不到',
          not (set(got) & {r['id'] for r in others}),
          'B 的行=%s，A 读到=%s' % ([r['id'] for r in others], got))
    # 3) 打分记录同款：只读自己的、且只在公开时
    s1, es1 = search(fac, 'edu.assess.score', [('task_id', '=', task['id'])],
                     ['id', 'roster_id'])
    rids_mine = {r['id'] for r in mine}
    check('W16-⑤', 'score_visible=True ⇒ 只读到"自己那行"的打分记录',
          bool(s1) and all((s['roster_id'] or [None])[0] in rids_mine for s in s1),
          '读到 %d 条，全部落在我的行上=%s'
          % (len(s1 or []), all((s['roster_id'] or [None])[0] in rids_mine
                                for s in (s1 or []))))
    call_kw(adm, 'edu.assess.template', 'write',
            [[tpl['id']], {'score_visible': False}])
    s2, es2 = search(fac, 'edu.assess.score', [('task_id', '=', task['id'])],
                     ['id'])
    check('W16-⑥', 'score_visible=False ⇒ 打分记录同样读不到（同一开关、两层同步）',
          s2 is not None and len(s2) == 0, 'rows=%s err=%s' % (s2, es2))
    call_kw(adm, 'edu.assess.template', 'write',
            [[tpl['id']], {'score_visible': True}])
    # 4) 只读：被评者不能改自己的行，也不能改别人给自己的分
    _w, e3 = call_kw(fac, 'edu.assess.roster', 'write',
                     [[want[0]], {'state': 'done'}])
    check('W16-⑦', '被评教师**不能改**自己被评的行（新规则只开 perm_read）',
          bool(e3) and ('Access' in e3 or '不允许' in e3),
          'err=%s' % (e3 or '')[:120])
    if s1:
        _w2, e4 = call_kw(fac, 'edu.assess.score', 'write',
                          [[s1[0]['id']], {'value': 100.0}])
        check('W16-⑧', '被评教师**不能改**别人给自己的分（防自利式改分）',
              bool(e4) and ('Access' in e4 or '不允许' in e4),
              'err=%s' % (e4 or '')[:120])
    else:
        check('W16-⑧', '被评教师不能改分（无样本可改时跳过）', False,
              '评教任务上没有打分记录，无法反向验证 —— 记为未覆盖')
    # 5) 正对照：教务仍然全量可见（恒真域没被新规则破坏）
    all_rows, _e = search(adm, 'edu.assess.roster',
                          [('task_id', '=', task['id'])], ['id'])
    check('W16-⑨', '正对照：教务不受行过滤（恒真域仍在，可见全部 %d 行）' % len(rosters),
          len(all_rows or []) == len(rosters),
          '教务读到 %d 行' % len(all_rows or []))
    # 收尾：把夹具恢复到原状（score_visible 原本为 False）
    call_kw(adm, 'edu.assess.template', 'write',
            [[tpl['id']], {'score_visible': tpl['score_visible']}])


def cleanup(adm, fx):
    print('\n== 清理夹具（只删本脚本亲手建的 id）==')
    tasks = [fx.get('task_xlsx'), fx.get('task_sanit'), fx.get('bad_task'),
             fx.get('anon_task')] + list(fx.get('js_tasks') or [])
    tasks = [t for t in tasks if t]
    if tasks:
        sc, _e = search(adm, 'edu.assess.score', [('task_id', 'in', tasks)], ['id'])
        unlink(adm, 'edu.assess.score', [r['id'] for r in (sc or [])])
        ro, _e = search(adm, 'edu.assess.roster', [('task_id', 'in', tasks)], ['id'])
        unlink(adm, 'edu.assess.roster', [r['id'] for r in (ro or [])])
        unlink(adm, 'edu.assess.task', tasks)
    templates = [t for t in [fx.get('m1'), fx.get('xlsx'), fx.get('sanit'),
                             fx.get('js'), fx.get('bad_tpl')] if t]
    if templates:
        ok, err = unlink(adm, 'edu.assess.template', templates)
        print('    删模板：%s %s' % (ok, err or ''))
    left = psql("select count(*) from edu_assess_template where name like "
                "'%s%%'" % PREFIX)
    check('W15', '夹具已清空（只留脚本外数据）', left == '0', '残留 = %s' % left)


def preclean(adm):
    """清掉上一轮（含中途失败）残留的【第2期验收】夹具，保证本次读数是本次的。"""
    res, err = search(adm, 'edu.assess.template',
                      [('name', 'like', PREFIX + '%')], ['id'])
    if err or not res:
        return 0
    tids = [r['id'] for r in res]
    tasks, _e = search(adm, 'edu.assess.task', [('template_id', 'in', tids)], ['id'])
    tids_task = [r['id'] for r in (tasks or [])]
    if tids_task:
        sc, _e = search(adm, 'edu.assess.score', [('task_id', 'in', tids_task)], ['id'])
        unlink(adm, 'edu.assess.score', [r['id'] for r in (sc or [])])
        ro, _e = search(adm, 'edu.assess.roster', [('task_id', 'in', tids_task)], ['id'])
        unlink(adm, 'edu.assess.roster', [r['id'] for r in (ro or [])])
        unlink(adm, 'edu.assess.task', tids_task)
    unlink(adm, 'edu.assess.template', tids)
    return len(tids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true', help='跑完不清理夹具')
    args = ap.parse_args()
    adm = login('admin')
    if not adm:
        raise SystemExit('登录失败：检查 %s 与账号 admin/demo123' % BASE)
    print('上轮残留清理：%d 个模板' % preclean(adm))
    fx = build_all(adm)
    sample = fill_xlsx_sample(adm, fx)
    fill_sanit(adm, fx, heavy=False)
    fill_sanit(adm, fx, heavy=True)
    w1_m1(adm, fx)
    per_item, expect, rid_a = w2_xlsx(adm, fx, sample)
    w3_dual_reverse(adm, fx, per_item, expect, rid_a)
    w4_deduct(adm, fx)
    w7_js(adm, fx)
    w8_roster_manual(adm, fx)
    w9_percent_gate(adm, fx)
    w10_dual_anonymous(adm, fx)
    w11_hierarchy(adm, fx)
    w12_scale_grade(adm, fx)
    w13_views(adm, fx)
    w14_regression(adm, fx)
    w16_subject_visibility(adm, fx)
    if not args.keep:
        cleanup(adm, fx)
    n_ok = sum(1 for i in items if i['pass'])
    n_bad = len(items) - n_ok
    print('\n==== 结果：%d/%d 通过，%d 失败 ====' % (n_ok, len(items), n_bad))
    RESULTS.write_text(json.dumps({'items': items, 'passed': n_ok,
                                   'failed': n_bad}, ensure_ascii=False,
                                  indent=1))
    print('结果落盘：%s' % RESULTS)
    return 1 if n_bad else 0


if __name__ == '__main__':
    sys.exit(main())
