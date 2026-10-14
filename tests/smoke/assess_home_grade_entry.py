#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「整班打分」入口常驻化验收（2026-09-29）。

被测量的问题（用户原话：「综合评估里这个整版打分给我放进去」）
----------------------------------------------------------
「整班打分」的真实落点是 GET /assess/grade/<task_id>，可它此前**两个入口都挂在任务上**
（审阅队列每行的「打分」、首页「我任教的班级评估」每行的「打分」）；首页那张写着
「整班打分」的卡片又挂在 faculty（= 有 op.faculty 档案）上 ⇒ **教务账号在 /assess 上
一个入口都没有**。实测（改前，2026-09-29 15:29 +08:00，backoffice@local uid=12）：
/assess 返回 200、整页出现「整班打分」= False；同一页「管理评估任务」= True。
⇒ 根因不是「要先把任务建出来」，是**这张卡的判据把教务排除在外**了。

本轮的交付（零新模型 / 零新字段 / **零新路由**）
--------------------------------------------
· /assess 的「整班打分」卡片改挂 can_grade = 教务组·系统组 ∪ 教师组 —— 与目标路由
  /assess/review 的门禁**同一句判据**（卡片上出现的入口一定点得开）；
· 有进行中的任务：写清有几个 + 「进入整班打分」（落点 = 审阅队列，每行可打分）；
  数字与审阅队列走**同一份实现**（controllers/portal.py 的 _review_rows）；
· 没有进行中的任务：**不给死按钮**，直说空态（教务给「去新建任务」→ /assess/tasks）；
  空态是两句不同的话：「还没有进行中的评估任务」（全库一个都没有）vs
  「没有你可以打分的任务」（有任务、但名单里没有你任教班级的学生）；
· 已结束的任务行不再给「打分」按钮（那个按钮点了也存不了：save 会拒绝）。

判据纪律（照 tests/smoke/assess_portal_gaps.py）
--------------------------------------------
· 正向断言与**库读数**对照（SQL vs 页面结构），不是「页面看着有东西」；
· 每条负向断言都配**正对照**（学生/家长拿不到 ≠ 教师也拿不到；控制组必须拿得到）；
· 「页面没显示」不算越权证明 —— 越权还要证明**数据层**拿不到（JSON-RPC 直读）；
· 空态**不许编造**：注入「没有进行中的任务」的窗口里，卡片片段里不许出现任何
  打分矩阵 / 打分链接 / 数字输入框；
· 两个窗口都**自还原并逐字校验**（任务状态直方图 / 视图 arch 逐字节）。

用法
----
    python3 tests/smoke/assess_home_grade_entry.py             # 全量
    python3 tests/smoke/assess_home_grade_entry.py --no-axe    # 跳过无障碍段
    python3 tests/smoke/assess_home_grade_entry.py --only a    # 只跑某段（注入窗口排查用）
    python3 tests/smoke/assess_home_grade_entry.py --keep      # 保留夹具
    python3 tests/smoke/assess_home_grade_entry.py --restore-states   # 崩溃后手工还原任务状态
退出码：0=全绿；1=有断言失败；2=ENV（站点不可达 / 库读不到 / 夹具建不起来）
结果落盘：tests/smoke/assess_home_grade_entry_results.json
"""
import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import assess_portal_gaps as G          # noqa: E402  复用其登录 / RPC / psql 助手

BASE = G.BASE
DB = G.DB
RESULTS = HERE / 'assess_home_grade_entry_results.json'
AXE_FILE = os.path.join(os.environ.get('TMPDIR') or '/tmp',
                        'edu_axe', 'axe-4.10.2.min.js')
#: 注入窗口的还原快照（崩溃后可用 --restore-states 手工还原）
SNAP = Path(os.environ.get('TMPDIR') or '/tmp') / \
    'edu_assess_grade_entry_state_snapshot.json'
#: 反向注入窗口的 arch 快照（崩溃后可用 --restore-arch 手工还原）
ARCH_SNAP = Path(os.environ.get('TMPDIR') or '/tmp') / \
    'edu_assess_grade_entry_arch_snapshot.txt'

MARK = '【整班打分入口】'
PERIOD = 'ASG-'
FAC_LOGIN = 'asg-fac@local'
FAC_NAME = MARK + '无任教班教师'
VIEW_XMLID = ('edu_assess', 'edu_assess_home')

#: 与 scripts/check_accessibility.py / assess_grid_sticky_paste.py **同一个 axe 标签集**
AXE_WCAG = ('{resultTypes:["violations"], runOnly:{type:"tag", '
            'values:["wcag2a","wcag2aa","wcag21a","wcag21aa"]}}')

OK, FAIL = 'PASS', 'FAIL'
items = []
readings = {}
nas = []


def check(no, name, cond, detail=''):
    verdict = OK if cond else FAIL
    items.append({'no': no, 'name': name, 'pass': bool(cond),
                  'detail': str(detail)[:1200]})
    print('  %-4s #%-5s %-58s %s' % (verdict, no, name, str(detail)[:200]))
    return bool(cond)


def note(msg):
    print('  ---- %s' % msg)


def na(no, name, reason):
    """测不到的事不许静默当绿：打 N/A + 写明理由，不计通过也不计失败。"""
    nas.append({'no': no, 'name': name, 'reason': str(reason)[:400]})
    print('  %-4s #%-5s %-58s %s' % ('N/A', no, name, str(reason)[:200]))
    return True


def die(msg):
    print('CANNOT: %s' % msg)
    json.dump({'error': msg, 'items': items,
               'when': time.strftime('%Y-%m-%d %H:%M:%S')},
              open(RESULTS, 'w'), ensure_ascii=False, indent=1)
    sys.exit(2)


# ----------------------------------------------------------------------
# 页面解析（切片器：所有判据都切成「卡片片段 / 页面」两级，避免全页误命中）
# ----------------------------------------------------------------------

def _slice_div(html, start):
    """从 start（'<div' 的起点）起按 div 配平切出整段。"""
    depth, i = 0, start
    tag_re = re.compile(r'<(/?)div\b', re.I)
    while True:
        m = tag_re.search(html, i)
        if not m:
            return html[start:]
        depth += -1 if m.group(1) else 1
        i = m.end()
        if depth == 0:
            j = html.find('>', i)
            return html[start:j + 1]


def card_html(html, title):
    """页面上标题为 title 的那张门户卡的 HTML 片段（找不到返回空串）。

    形态 = edu_page 里既有的卡片：<div class="col"><div class="card ...">…</div></div>。
    量具自证见 S3（拿一段没有这张卡的 HTML 必须切出空串，否则切片器恒真）。
    """
    i = (html or '').find(title)
    if i < 0:
        return ''
    starts = list(re.finditer(r'<div class="col"', html[:i]))
    if not starts:
        return ''
    return _slice_div(html, starts[-1].start())


def page_text(html):
    t = re.sub(r'<script.*?</script>', ' ', html or '', flags=re.S)
    t = re.sub(r'<style.*?</style>', ' ', t, flags=re.S)
    t = re.sub(r'<[^>]+>', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def grade_links(html):
    """页面里指向 /assess/grade/<id> 的链接 id 集合。"""
    return sorted(int(m) for m in re.findall(
        r'href="/assess/grade/(\d+)"', html or ''))


def get(sess, path, allow_redirects=False):
    r = sess.get(BASE + path, timeout=40, allow_redirects=allow_redirects)
    return r, (r.text or '')


def status_loc(r):
    return '%s %s' % (r.status_code, r.headers.get('Location') or '-')


# ----------------------------------------------------------------------
# 库读数（判据的对照面）
# ----------------------------------------------------------------------

def db_grade_tasks():
    """库口径：教务（不受班级收敛）能整班打分的任务集合。

    与 controllers/portal.py 的 _review_rows 同口径的 SQL 版：
      state <> 'draft' · target_kind = 'student' · 名单非空（exists 保证）。
    返回 {task_id: state}（**全部**可打分任务，含已结束的）。
    """
    raw = G.psql('select t.id || chr(124) || t.state from edu_assess_task t '
                 "where t.state <> 'draft' and t.target_kind = 'student' "
                 'and exists (select 1 from edu_assess_roster r '
                 'where r.task_id = t.id) order by t.id')
    out = {}
    for line in (raw or '').splitlines():
        if line.strip():
            tid, st = line.split('|')
            out[int(tid)] = st
    return out


def task_states():
    raw = G.psql('select id || chr(124) || state from edu_assess_task order by id')
    out = {}
    for line in (raw or '').splitlines():
        if line.strip():
            tid, st = line.split('|')
            out[int(tid)] = st
    return out


def state_hist(states):
    h = {}
    for st in states.values():
        h[st] = h.get(st, 0) + 1
    return dict(sorted(h.items()))


def view_arch(view_id):
    return G.psql("select arch_db->>'en_US' from ir_ui_view where id = %d" % view_id)



# ----------------------------------------------------------------------
# 夹具（只建本探针自己的东西；清场按前缀/登录名，绝不动既有数据）
# ----------------------------------------------------------------------

def faculty_group_id(adm):
    rows, err = G.search(adm, 'ir.model.data',
                         [('module', '=', 'openeducat_core'),
                          ('name', '=', 'group_op_faculty')], ('res_id',))
    if err or not rows:
        return None
    return rows[0]['res_id']


def make_teacher_rpc(adm, gid):
    """建一个**保证合法**的教师（口径照 tests/smoke/_fixtures.py，只是走 RPC）。

    关键一步：op.faculty.user_id 委托到 res.partner.user_id，而 res.users.create
    **不会**自动回写它（Odoo 维护的是 partner.user_ids）—— 漏写的话
    faculty_of_user() 命不中，于是「越权被拒」与「根本没有教师身份被拒」同形。
    ⇒ 建完立刻用**同一判据**（op.faculty.user_id == uid）自证载体合法（D0）。
    """
    pid = G.rpc_create(adm, 'res.partner', {'name': FAC_NAME})
    uid = G.rpc_create(adm, 'res.users', {
        'name': FAC_NAME, 'login': FAC_LOGIN, 'password': 'demo123',
        'partner_id': pid, 'group_ids': [(6, 0, [gid])]})
    fid = G.rpc_create(adm, 'op.faculty', {
        'partner_id': pid, 'first_name': '无任教班', 'last_name': '教师',
        'gender': 'male', 'birth_date': '1985-01-01'})
    _r, err = G.call_kw(adm, 'res.partner', 'write', [[pid], {'user_id': uid}])
    return pid, uid, fid, err


def build_closed_task(adm, sid):
    """已结束的控制组任务（模板 1 项 + 1 行名单）—— 用来验「不再给死按钮」。"""
    tpl = G.rpc_create(adm, 'edu.assess.template', {
        'name': MARK + '已结束控制组', 'kind': 'other', 'target_kind': 'student',
        'total': 100.0, 'pass_line': 60.0, 'excellent_line': 90.0,
        'weight_mode': 'multiplier', 'state': 'active', 'score_visible': True})
    G.rpc_create(adm, 'edu.assess.item', {
        'template_id': tpl, 'name': '控制组项', 'item_kind': 'leaf',
        'max_score': 10.0, 'weight': 1.0, 'sequence': 10})
    tid = G.rpc_create(adm, 'edu.assess.task', {
        'template_id': tpl, 'period': PERIOD + '已结束', 'state': 'closed',
        'scorer_kind': 'teacher', 'anonymous': False, 'summary_min': 1})
    rid = G.rpc_create(adm, 'edu.assess.roster',
                       {'task_id': tid, 'student_id': sid})
    return tpl, tid, rid


def cleanup(adm, skip=False):
    if skip:
        return
    # 任务 / 名单 / 打分 / 模板 / 评分项
    tasks, _e = G.search(adm, 'edu.assess.task', [('period', 'like', PERIOD + '%')])
    tids = [t['id'] for t in tasks]
    if tids:
        sc = [s['id'] for s in G.search(
            adm, 'edu.assess.score', [('task_id', 'in', tids)])[0]]
        ro = [r['id'] for r in G.search(
            adm, 'edu.assess.roster', [('task_id', 'in', tids)])[0]]
        G.unlink(adm, 'edu.assess.score', sc)
        G.unlink(adm, 'edu.assess.roster', ro)
    G.unlink(adm, 'edu.assess.task', tids)
    itms, _e = G.search(adm, 'edu.assess.item',
                        [('template_id.name', 'like', MARK + '%')])
    G.unlink(adm, 'edu.assess.item', [i['id'] for i in itms])
    tpls, _e = G.search(adm, 'edu.assess.template', [('name', 'like', MARK + '%')])
    G.unlink(adm, 'edu.assess.template', [t['id'] for t in tpls])
    # 教师夹具：账号 → op.faculty（_inherits 委托，删它会一并删掉它的伙伴）
    us, _e = G.search(adm, 'res.users', [('login', '=', FAC_LOGIN)])
    G.unlink(adm, 'res.users', [u['id'] for u in us])
    facs, _e = G.search(adm, 'op.faculty', [('name', '=', FAC_NAME)])
    G.unlink(adm, 'op.faculty', [f['id'] for f in facs])
    print('    ... 清场：任务 %d / 模板 %d / 评分项 %d / 教师 %d'
          % (len(tids), len(tpls), len(itms), len(facs)))


# ----------------------------------------------------------------------
# 无障碍（axe 4.10.2，与门禁同一标签集；缺 playwright/axe 时打 N/A）
# ----------------------------------------------------------------------

def cookies_of(sess):
    return [{'name': c.name, 'value': c.value, 'domain': 'localhost',
             'path': c.path or '/'} for c in sess.cookies]


def run_axe(sessions, targets):
    """targets = [(角色, 路径)] -> ({label: 读数}, 错误原因)。"""
    if not os.path.isfile(AXE_FILE):
        return None, 'axe 缓存缺失：%s' % AXE_FILE
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return None, 'playwright 不可用：%s' % exc
    src = open(AXE_FILE, encoding='utf-8').read()
    out = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for role, path in targets:
                ctx = browser.new_context(viewport={'width': 1280,
                                                    'height': 900})
                ctx.add_cookies(cookies_of(sessions[role]))
                pg = ctx.new_page()
                pg.goto(BASE + path, wait_until='load', timeout=60000)
                pg.wait_for_timeout(500)
                pg.add_script_tag(content=src)
                res = pg.evaluate('async () => await axe.run(document, %s)'
                                  % AXE_WCAG)
                viols = [{'id': v['id'], 'impact': v.get('impact'),
                          'nodes': len(v.get('nodes') or []),
                          'targets': [','.join(n.get('target') or [])
                                      for n in (v.get('nodes') or [])][:4]}
                         for v in (res.get('violations') or [])]
                label = '%s %s' % (role, path)
                out[label] = {
                    'url': pg.url, 'violations': viols,
                    'rules': sorted(v['id'] for v in viols),
                    'nodes': sum(v['nodes'] for v in viols),
                    'passes': len(res.get('passes') or []),
                    'incomplete': len(res.get('incomplete') or []),
                }
                print('    [axe] %-18s -> 规则 %d / 节点 %d / passes %d ｜ %s'
                      % (label, len(viols), out[label]['nodes'],
                         out[label]['passes'],
                         ', '.join('%s(x%d)' % (v['id'], v['nodes'])
                                   for v in viols) or '无违规'))
                ctx.close()
        finally:
            browser.close()
    return out, None



# ----------------------------------------------------------------------
# S 量具自证（离线；先证尺子再读数）
# ----------------------------------------------------------------------

#: 切片器的正样本（形态照 edu_page 的卡片）
HTML_SAMPLE = ('<div class="col"><div class="card"><div class="card-body">'
               '<b>整班打分</b><a href="/assess/review">进入整班打分</a>'
               '</div></div></div>'
               '<div class="col"><div class="card">别的卡</div></div>')


def section_s():
    print('\n== S 量具自证（离线，不连站点）==')
    rejected = False
    try:
        ET.fromstring('<odoo><!-- a -- b --></odoo>')
    except ET.ParseError:
        rejected = True
    check('S1', '注释里连续两个减号的 XML 被判非良构（本仓踩过两次：升级被拒 exit 6）',
          rejected, '反例样本 <odoo><!-- a -- b --></odoo> -> %s'
          % ('ParseError（正确拒绝）' if rejected else '竟然被接受 ⇒ 尺子坏了'))
    view = HERE.parents[1] / 'custom_addons' / 'edu_assess' / 'views' / 'assess_portal.xml'
    src = view.read_text(encoding='utf-8') if view.exists() else ''
    parsed = False
    try:
        ET.fromstring(src)
        parsed = True
    except ET.ParseError:
        pass
    check('S2', '被改的视图良构，且带着新判据 can_grade、旧判据 faculty 已不在',
          parsed and 't-if="can_grade"' in src and 't-if="faculty"' not in src,
          '%s ｜ 良构=%s ｜ can_grade=%s ｜ 旧判据残留=%s'
          % (view.name, parsed, 't-if="can_grade"' in src,
             't-if="faculty"' in src))
    neg = ('<div class="col"><div class="card"><div class="card-body">'
           '<b>别的卡</b></div></div></div>')
    check('S3', '卡片切片器不是恒真：没有这张卡的页面切出空串，有卡的页面切得出',
          card_html(neg, '整班打分') == ''
          and card_html(HTML_SAMPLE, '整班打分') != '',
          '负样本=%r ｜ 正样本 %d 字'
          % (card_html(neg, '整班打分'), len(card_html(HTML_SAMPLE, '整班打分'))))


# ----------------------------------------------------------------------
# A 正向：常驻入口（有任务时）
# ----------------------------------------------------------------------

def section_a(sess, exp):
    print('\n== A 正向：教务/教师看得见「整班打分」常驻入口 ==')
    exp_open = sorted(tid for tid, st in exp.items() if st == 'open')
    readings['A'] = {'db_open': exp_open, 'db_all': exp}
    r, html = get(sess['backoffice'], '/assess')
    card = card_html(html, '整班打分')
    m = re.search(r'有\s*(\d+)\s*个进行中的评估可以整班打分', page_text(card))
    n = int(m.group(1)) if m else None
    readings['A']['backoffice'] = {
        'http': r.status_code, 'card': bool(card), 'count': n,
        'entry_link': '/assess/review' in card, 'cta': '进入整班打分' in card}
    check('A1', '教务 /assess：常驻卡片在 + 「进入整班打分」指向 /assess/review',
          r.status_code == 200 and bool(card) and '/assess/review' in card
          and '进入整班打分' in card,
          'HTTP %s ｜ 卡片 %s ｜ 入口链接 %s' % (r.status_code, bool(card),
                                                '/assess/review' in card))
    check('A2', '教务卡片计数 == 库读数的进行中任务数（%d）' % len(exp_open),
          n == len(exp_open) and n is not None,
          '页面计数 %s ｜ 库 %d' % (n, len(exp_open)))
    r2, h2 = get(sess['backoffice'], '/assess/review')
    links = grade_links(h2)
    check('A3', '同一批任务：审阅队列的「打分」链接集合 == 库读数（卡片与列表不会互相打脸）',
          r2.status_code == 200 and links == exp_open,
          'HTTP %s ｜ 页面 %s ｜ 库 %s' % (r2.status_code, links, exp_open))
    # 教师侧（另一侧的控制组 + 自洽计数）
    r3, h3 = get(sess['faculty'], '/assess')
    card3 = card_html(h3, '整班打分')
    r4, h4 = get(sess['faculty'], '/assess/review')
    links4 = grade_links(h4)
    m3 = re.search(r'有\s*(\d+)\s*个进行中的评估可以整班打分', page_text(card3))
    n3 = int(m3.group(1)) if m3 else None
    readings['A']['faculty'] = {'http': r3.status_code, 'card': bool(card3),
                                'count': n3, 'review_links': links4}
    check('A4', '教师 /assess：常驻卡片在 + 入口指向 /assess/review + 计数与自己的列表自洽',
          r3.status_code == 200 and bool(card3) and '/assess/review' in card3
          and n3 == len(links4),
          'HTTP %s ｜ 卡片 %s ｜ 计数 %s ｜ 自己列表 %d 条'
          % (r3.status_code, bool(card3), n3, len(links4)))
    check('A5', '教师侧不给「去新建任务」（/assess/tasks 是教务组页面，给了就是死按钮）',
          '去新建任务' not in card3, '卡片里「去新建任务」=%s'
          % ('去新建任务' in card3))


# ----------------------------------------------------------------------
# B 落点：审阅队列每行可打分 + 链接可达
# ----------------------------------------------------------------------

def section_b(sess, exp):
    print('\n== B 落点：审阅队列每行可打分、链接可达 ==')
    exp_open = sorted(tid for tid, st in exp.items() if st == 'open')
    r, html = get(sess['backoffice'], '/assess/review')
    links = grade_links(html)
    rows = len(re.findall(r'href="/assess/task/\d+/results"', html))
    check('B1', '审阅队列行数 == 库口径可整班打分的任务数（%d）' % len(exp),
          r.status_code == 200 and rows == len(exp),
          'HTTP %s ｜ 页面行 %d ｜ 库 %d' % (r.status_code, rows, len(exp)))
    check('B2', '每行「打分」按钮指向 /assess/grade/<id>，集合 == 库读数的进行中任务',
          links == exp_open, '页面 %s ｜ 库 %s' % (links, exp_open))
    if exp_open:
        tid = exp_open[0]
        r2, h2 = get(sess['backoffice'], '/assess/grade/%d' % tid)
        check('B3', '链接可达：GET /assess/grade/%d 200 且真的渲染出打分矩阵' % tid,
              r2.status_code == 200 and 'yy-assess-grade-table' in h2,
              'HTTP %s ｜ 矩阵表 %s' % (r2.status_code,
                                       'yy-assess-grade-table' in h2))
    else:
        na('B3', '链接可达（打分矩阵）', '库内没有进行中的可打分任务 ⇒ 没有可试的链接')


# ----------------------------------------------------------------------
# C 越权：入口与目标路由都挡住（含数据层）
# ----------------------------------------------------------------------

def section_c(sess, exp):
    print('\n== C 越权：学生/家长看不到入口，也进不去目标路由 ==')
    exp_open = sorted(tid for tid, st in exp.items() if st == 'open')
    tid = exp_open[0] if exp_open else None
    for role, positive in (('student', '我的评估'), ('parent', '孩子的评估')):
        r, html = get(sess[role], '/assess')
        check('C1-%s' % role,
              '%s /assess：没有「整班打分」入口，也没有 /assess/review 与 /assess/tasks 链接'
              % role,
              '整班打分' not in html and 'href="/assess/review"' not in html
              and 'href="/assess/tasks"' not in html,
              'HTTP %s ｜ 整班打分=%s ｜ review 链接=%s ｜ tasks 链接=%s'
              % (r.status_code, '整班打分' in html,
                 'href="/assess/review"' in html, 'href="/assess/tasks"' in html))
        check('C1b-%s' % role, '正对照：%s 的 /assess 确实渲染了（不是白屏/303 造成的假绿）'
              % role, r.status_code == 200 and positive in html,
              'HTTP %s ｜ 含「%s」=%s' % (r.status_code, positive, positive in html))
        r2, _h2 = get(sess[role], '/assess/review')
        check('C2-%s' % role, '%s GET /assess/review → 303 /my/home' % role,
              r2.status_code == 303 and (r2.headers.get('Location') or '').endswith('/my/home'),
              status_loc(r2))
        if tid:
            r3, _h3 = get(sess[role], '/assess/grade/%d' % tid)
            check('C3-%s' % role, '%s GET /assess/grade/%d → 303 /my/home' % (role, tid),
                  r3.status_code == 303
                  and (r3.headers.get('Location') or '').endswith('/my/home'),
                  status_loc(r3))
    # 数据层：门户组 ACL = 0 ⇒ 直读被拒（不是"页面没显示"）
    for role in ('student', 'parent'):
        res, err = G.call_kw(sess[role], 'edu.assess.roster', 'search_read', [[], ['id']])
        check('C4-%s' % role,
              '数据层：%s 用 JSON-RPC 直读 edu.assess.roster → 被拒（AccessError）' % role,
              res is None and bool(err) and 'Access' in err,
              'result=%s ｜ err=%s' % (res, err))
    rows, err = G.call_kw(sess['backoffice'], 'edu.assess.roster', 'search_read',
                          [[], ['id']], {'limit': 3})
    check('C5', '正对照：教务同一条 RPC 拿得到名单行（证明 C4 不是"全站都读不到"）',
          bool(rows) and not err, 'rows=%s ｜ err=%s' % (rows, err))



# ----------------------------------------------------------------------
# D 空态（教师侧）：有任务但名单里没有我的班
# ----------------------------------------------------------------------

def section_d(sess, adm, exp):
    print('\n== D 空态（教师侧）：有任务、但没有你任教班级的学生 ==')
    gid = faculty_group_id(adm)
    if not gid:
        na('D0', '教师夹具', '找不到 openeducat_core.group_op_faculty 的 res_id')
        return None
    pid, uid, fid, werr = make_teacher_rpc(adm, gid)
    nf, nuid = G.login(FAC_LOGIN, 'demo123')
    if not nf:
        check('D0', '新建教师能登录（载体可用）', False, 'login=%s uid=%s err=%s'
              % (FAC_LOGIN, nuid, werr))
        return None
    found, ferr = G.call_kw(adm, 'op.faculty', 'search_read',
                            [[('user_id', '=', uid)], ['id']])
    check('D0', '载体合法：op.faculty.user_id == uid 反查命中（faculty_of_user 同一判据）',
          bool(found) and found[0]['id'] == fid,
          'found=%s ｜ fid=%s ｜ err=%s' % (found, fid, ferr))
    r, html = get(nf, '/assess')
    card = card_html(html, '整班打分')
    txt = page_text(card)
    check('D1', '教师侧空态：卡片仍在（常驻）+ 「当前没有你可以打分的评估任务」+ 无「进入整班打分」',
          r.status_code == 200 and bool(card)
          and '当前没有你可以打分的评估任务' in txt and '进入整班打分' not in card,
          'HTTP %s ｜ 卡片 %s ｜ 空态文案 %s ｜ 死按钮 %s'
          % (r.status_code, bool(card), '当前没有你可以打分的评估任务' in txt,
             '进入整班打分' in card))
    check('D2', '教师侧不给「去新建任务」按钮（那是教务组的页面）',
          '去新建任务' not in card, '卡片里「去新建任务」=%s' % ('去新建任务' in card))
    r2, h2 = get(nf, '/assess/review')
    check('D3', '该教师 /assess/review：诚实空态（同一句话）+ 无「去新建任务」',
          r2.status_code == 200 and 'id="yy-assess-review-empty"' in h2
          and '当前没有你可以打分的评估任务' in h2 and '去新建任务' not in h2,
          'HTTP %s ｜ 空态块 %s ｜ 去新建任务 %s'
          % (r2.status_code, 'yy-assess-review-empty' in h2, '去新建任务' in h2))
    ah = get(sess['backoffice'], '/assess')[1]
    exp_open = sorted(tid for tid, st in exp.items() if st == 'open')
    if exp_open:
        ok, det = ('个进行中的评估可以整班打分' in ah), \
            '库内进行中可打分任务 %d 条 ⇒ 教务应显示计数' % len(exp_open)
    else:
        ok, det = ('还没有进行中的评估任务' in ah), '库内无进行中任务 ⇒ 教务应显示空态'
    check('D4', '正对照：同一时刻教务看到的不是同一句话（空态是按人算的，不是全站没任务）',
          ok, det)
    return {'pid': pid, 'uid': uid, 'fid': fid}


# ----------------------------------------------------------------------
# E 空态（教务侧，注入窗口：进行中的可打分任务临时改草稿）
# ----------------------------------------------------------------------

def section_e(sess):
    print('\n== E 空态（教务侧，注入窗口：open→draft，读完自还原）==')
    before = task_states()
    before_hist = state_hist(before)
    raw = G.psql("select id from edu_assess_task where state = 'open' "
                 "and target_kind = 'student' order by id")
    targets = [int(x) for x in (raw or '').split() if x.strip().isdigit()]
    t0 = time.strftime('%Y-%m-%d %H:%M:%S')
    SNAP.write_text(json.dumps(
        {'when': t0, 'states': {str(t): before.get(t, 'open') for t in targets}},
        ensure_ascii=False, indent=1), encoding='utf-8')
    print('    注入窗口 %s：%d 条 open→draft（快照 %s）' % (t0, len(targets), SNAP))
    readings['E'] = {'when': t0, 'targets': targets,
                     'before_hist': before_hist}
    try:
        G.psql("update edu_assess_task set state = 'draft' "
               "where state = 'open' and target_kind = 'student'")
        r, html = get(sess['backoffice'], '/assess')
        card = card_html(html, '整班打分')
        txt = page_text(card)
        readings['E']['card_text'] = txt[:400]
        check('E1', '教务空态：卡片仍在（常驻）+ 「还没有进行中的评估任务」+ 「去新建任务」→ /assess/tasks',
              r.status_code == 200 and bool(card)
              and '还没有进行中的评估任务' in txt
              and 'href="/assess/tasks"' in card and '去新建任务' in card,
              'HTTP %s ｜ 卡片 %s ｜ 空态 %s ｜ tasks 链接 %s'
              % (r.status_code, bool(card), '还没有进行中的评估任务' in txt,
                 'href="/assess/tasks"' in card))
        check('E2', '空态不给死按钮：卡片里没有「进入整班打分」',
              '进入整班打分' not in card, '卡片里「进入整班打分」=%s'
              % ('进入整班打分' in card))
        check('E3', '不编造：卡片片段里没有输入框 / 打分链接 / 表格；页面无任何 /assess/grade/ 链接',
              '<input' not in card and '/assess/grade/' not in card
              and '<table' not in card and not grade_links(html),
              '卡片 input=%s grade=%s table=%s ｜ 页面 grade 链接 %s'
              % ('<input' in card, '/assess/grade/' in card, '<table' in card,
                 grade_links(html)))
        take_shots(sess, [
            ('backoffice', '/assess', 'assess_backoffice_no_tasks.png',
             '教务 /assess：空态（还没有进行中的评估任务 + 去新建任务）'),
            ('backoffice', '/assess/review', 'assess_review_empty.png',
             '教务 /assess/review：诚实空态'),
        ])
        r2, h2 = get(sess['backoffice'], '/assess/review')
        check('E4', '审阅队列同样是诚实空态 + 「去新建任务」（不是一句"没有"就完了）',
              r2.status_code == 200 and 'id="yy-assess-review-empty"' in h2
              and '还没有进行中的评估任务' in h2 and 'href="/assess/tasks"' in h2,
              'HTTP %s ｜ 空态块 %s ｜ tasks 链接 %s'
              % (r2.status_code, 'yy-assess-review-empty' in h2,
                 'href="/assess/tasks"' in h2))
    finally:
        for tid in targets:
            G.psql("update edu_assess_task set state = '%s' where id = %d"
                   % (before.get(tid, 'open'), tid))
        after_hist = state_hist(task_states())
        readings['E']['after_hist'] = after_hist
        print('    还原完成 %s：%s' % (time.strftime('%Y-%m-%d %H:%M:%S'), after_hist))
        check('E5', '还原：任务状态直方图与注入前**逐字一致**',
              after_hist == before_hist,
              '注入前 %s ｜ 还原后 %s' % (before_hist, after_hist))
        back = get(sess['backoffice'], '/assess')[1]
        check('E6', '还原后入口回到「有 N 个」态（变绿）',
              '进入整班打分' in back and '个进行中的评估可以整班打分' in back,
              '进入链接=%s ｜ 计数=%s'
              % ('进入整班打分' in back, '个进行中的评估可以整班打分' in back))
        if SNAP.exists():
            SNAP.unlink()


# ----------------------------------------------------------------------
# F 已结束的任务：不给「打分」死按钮
# ----------------------------------------------------------------------

def section_f(sess, adm, exp, sid):
    print('\n== F 已结束的任务：不给「打分」死按钮（对照：进行中的行还在）==')
    tpl, tid, rid = build_closed_task(adm, sid)
    exp_open = sorted(t for t, st in exp.items() if st == 'open')
    r, html = get(sess['backoffice'], '/assess/review')
    check('F1', '已结束任务（id=%d）：审阅队列不给 /assess/grade/<id> 链接' % tid,
          r.status_code == 200 and ('href="/assess/grade/%d"' % tid) not in html,
          'HTTP %s ｜ grade 链接=%s' % (r.status_code,
                                       ('href="/assess/grade/%d"' % tid) in html))
    check('F2', '已结束任务：给「已结束，不能打分」+ 「结果」链接（说清而不是静默）',
          '已结束，不能打分' in html
          and ('/assess/task/%d/results' % tid) in html,
          '文案=%s ｜ 结果链接=%s' % ('已结束，不能打分' in html,
                                     ('/assess/task/%d/results' % tid) in html))
    check('F3', '对照：进行中的行仍有「打分」链接（集合 == 库读数）',
          grade_links(html) == exp_open,
          '页面 %s ｜ 库 %s' % (grade_links(html), exp_open))
    r2, h2 = get(sess['backoffice'], '/assess/grade/%d' % tid)
    m = re.search(r'csrf_token[^>]*?value="([^"]+)"', h2)
    token = m.group(1) if m else None
    loc = ''
    if token:
        r3 = sess['backoffice'].post(BASE + '/assess/grade/%d/save' % tid,
                                     data={'csrf_token': token}, timeout=40,
                                     allow_redirects=False)
        loc = r3.headers.get('Location') or ''
    else:
        r3 = None
    nscore = (G.psql('select count(*) from edu_assess_score where task_id = %d'
                     % tid) or '').strip()
    check('F4', '证明那按钮本来就点不动：POST /assess/grade/<已结束>/save → 303 error=closed、落库 0 条',
          token is not None and r3 is not None and r3.status_code == 303
          and 'error=closed' in loc and nscore == '0',
          'csrf=%s ｜ HTTP %s ｜ Location=%s ｜ 落库 %s'
          % (bool(token), (r3.status_code if r3 is not None else '-'), loc, nscore))



# ----------------------------------------------------------------------
# G 无障碍（axe；缺 playwright / axe 缓存时打 N/A，不静默当绿）
# ----------------------------------------------------------------------

def section_g(sess, no_axe):
    print('\n== G 无障碍（axe 4.10.2 / WCAG 2A+2AA，与门禁同一标签集）==')
    targets = [('backoffice', '/assess'), ('faculty', '/assess'),
               ('student', '/assess'), ('backoffice', '/assess/review'),
               ('faculty', '/assess/review')]
    if no_axe:
        na('G1', '无障碍读数（axe）', '命令行 --no-axe 显式跳过')
        return
    res, err = run_axe(sess, targets)
    if err:
        na('G1', '无障碍读数（axe）', err)
        return
    readings['G'] = res
    for i, (role, path) in enumerate(targets, start=1):
        lab = '%s %s' % (role, path)
        d = res.get(lab) or {}
        check('G%d' % i, '%s：axe 违规 0 条' % lab, (d.get('nodes') or 0) == 0,
              'url=%s ｜ 规则=%s ｜ nodes=%s ｜ passes=%s ｜ incomplete=%s'
              % (d.get('url'), d.get('rules'), d.get('nodes'), d.get('passes'),
                 d.get('incomplete')))


# ----------------------------------------------------------------------
# I 反向注入：卡片判据换回改动前的 faculty
# ----------------------------------------------------------------------

def section_i(sess, adm):
    print('\n== I 反向注入：把卡片判据换回改动前的 faculty（必须变红）→ 还原（必须变绿）==')
    raw = G.psql("select res_id from ir_model_data where module = '%s' "
                 "and name = '%s'" % VIEW_XMLID)
    vid = int(raw) if (raw or '').strip().isdigit() else 0
    arch0 = view_arch(vid) if vid else ''
    check('I0', '注入前：视图 arch 里有新判据 can_grade、没有旧判据 faculty',
          bool(arch0) and 't-if="can_grade"' in arch0
          and 't-if="faculty"' not in arch0,
          'view_id=%s ｜ len=%s ｜ can_grade=%s ｜ faculty=%s'
          % (vid, len(arch0), 't-if="can_grade"' in arch0,
             't-if="faculty"' in arch0))
    if not (vid and arch0 and 't-if="can_grade"' in arch0):
        return
    inj = arch0.replace('t-if="can_grade"', 't-if="faculty"')
    # 兜底：注入前把原文落盘（进程被杀也能用 --restore-arch 还原，见 restore_arch）
    ARCH_SNAP.write_text(arch0, encoding='utf-8')
    print('    注入窗口 %s：arch %d → %d 字（判据换回 faculty，快照 %s）'
          % (time.strftime('%Y-%m-%d %H:%M:%S'), len(arch0), len(inj), ARCH_SNAP))
    readings['I'] = {'view_id': vid, 'arch_len': len(arch0),
                     'when': time.strftime('%Y-%m-%d %H:%M:%S')}
    try:
        _r, werr = G.call_kw(adm, 'ir.ui.view', 'write', [[vid], {'arch_db': inj}])
        html = get(sess['backoffice'], '/assess')[1]
        check('I1', '注入后（教务）：/assess 上「整班打分」入口消失 —— 复现用户报的现象（红）',
              '整班打分' not in html and 'href="/assess/review"' not in html,
              '整班打分=%s ｜ review 链接=%s ｜ write err=%s'
              % ('整班打分' in html, 'href="/assess/review"' in html, werr))
        r2, _h2 = get(sess['backoffice'], '/assess/review')
        check('I2', '注入后：坏的不是整页（/assess/review 仍 200）—— 红的只是入口本身',
              r2.status_code == 200, status_loc(r2))
    finally:
        _r, werr = G.call_kw(adm, 'ir.ui.view', 'write', [[vid], {'arch_db': arch0}])
        back = view_arch(vid)
        print('    还原完成 %s（write err=%s）'
              % (time.strftime('%Y-%m-%d %H:%M:%S'), werr))
        if back == arch0 and ARCH_SNAP.exists():
            ARCH_SNAP.unlink()
        check('I3', '还原：DB 里的 arch 与注入前**逐字节一致**', back == arch0,
              'len %d → %d ｜ 一致=%s' % (len(arch0), len(back), back == arch0))
        html3 = get(sess['backoffice'], '/assess')[1]
        check('I4', '还原后（教务）：入口回来（绿）',
              '整班打分' in html3 and '进入整班打分' in html3,
              '整班打分=%s ｜ 进入整班打分=%s'
              % ('整班打分' in html3, '进入整班打分' in html3))


# ----------------------------------------------------------------------
# 截图（--shots DIR）：UI 改动的直接证据（文本判据之外的"真渲染"）
# ----------------------------------------------------------------------

SHOTS = None            # main() 里由 --shots 赋值；None = 不截图


def take_shots(sess, targets):
    """targets = [(角色, 路径, 文件名, 说明)]；截图落到 SHOTS 目录。"""
    if not SHOTS:
        return
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:                                  # pragma: no cover
        print('    [shot] 跳过（playwright 不可用：%s）' % exc)
        return
    outdir = Path(SHOTS)
    outdir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for role, path, name, desc in targets:
                ctx = browser.new_context(viewport={'width': 1440,
                                                    'height': 1000})
                ctx.add_cookies(cookies_of(sess[role]))
                pg = ctx.new_page()
                pg.goto(BASE + path, wait_until='load', timeout=60000)
                pg.wait_for_timeout(400)
                out = outdir / name
                pg.screenshot(path=str(out))
                print('    [shot] %-8s %-14s -> %s（%s）' % (role, path, out, desc))
                ctx.close()
        finally:
            browser.close()


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------

def restore_from_snapshot():
    """--restore-states：崩溃后按快照把任务状态还原（幂等）。"""
    if not SNAP.exists():
        print('没有快照文件 %s —— 无需还原' % SNAP)
        return 0
    data = json.loads(SNAP.read_text(encoding='utf-8'))
    states = data.get('states') or {}
    for tid, st in states.items():
        G.psql("update edu_assess_task set state = '%s' where id = %d"
               % (st, int(tid)))
    print('已按快照还原 %d 条任务状态（窗口 %s）' % (len(states), data.get('when')))
    print('当前直方图：%s' % G.psql('select state from edu_assess_task'))
    SNAP.unlink()
    return 0


def restore_arch(sess):
    """--restore-arch：按快照把 edu_assess_home 的 arch 写回（幂等）。"""
    if not ARCH_SNAP.exists():
        print('没有 arch 快照 %s —— 无需还原' % ARCH_SNAP)
        return 0
    arch = ARCH_SNAP.read_text(encoding='utf-8')
    raw = G.psql("select res_id from ir_model_data where module = '%s' "
                 "and name = '%s'" % VIEW_XMLID)
    vid = int(raw) if (raw or '').strip().isdigit() else 0
    if not vid:
        print('找不到视图 xmlid %s.%s' % VIEW_XMLID)
        return 2
    _r, err = G.call_kw(sess['admin'], 'ir.ui.view', 'write',
                        [[vid], {'arch_db': arch}])
    now = view_arch(vid)
    print('已按快照写回视图 %d（len %d → %d，一致=%s，err=%s）'
          % (vid, len(arch), len(now), now == arch, err))
    if now == arch:
        ARCH_SNAP.unlink()
    return 0 if now == arch else 1


def safety_restore():
    """异常路径的兜底：任务状态快照 + 视图 arch 快照（都幂等）。"""
    if SNAP.exists():
        print('    兜底：还原任务状态快照 %s' % SNAP)
        restore_from_snapshot()
    if ARCH_SNAP.exists():
        print('    兜底：arch 快照仍在 %s —— 需要 --restore-arch 手工还原（本进程已失去会话）'
              % ARCH_SNAP)


def main():
    ap = argparse.ArgumentParser(description='整班打分入口常驻化验收')
    ap.add_argument('--no-axe', action='store_true', help='跳过无障碍段')
    ap.add_argument('--keep', action='store_true', help='保留夹具（排查用）')
    ap.add_argument('--only', default=None,
                    help='只跑某段：s/a/b/c/d/e/f/g/i（逗号分隔）')
    ap.add_argument('--restore-states', action='store_true',
                    help='按快照还原任务状态（注入窗口崩溃后手工跑）')
    ap.add_argument('--restore-arch', action='store_true',
                    help='按快照写回 edu_assess_home 的 arch（注入窗口崩溃后手工跑）')
    ap.add_argument('--shots', default=None,
                    help='截图目录（有任务态 + 空态各一张；需要 playwright）')
    args = ap.parse_args()
    if args.restore_states:
        return restore_from_snapshot()
    want = set(x.strip() for x in (args.only or 's,a,b,c,d,e,f,g,i').split(',')
               if x.strip())

    print('== 探活 ==')
    s = requests.Session()
    s.trust_env = False
    try:
        rp = s.get(BASE + '/web/login?db=%s' % DB, timeout=15)
        print('    /web/login -> %s' % rp.status_code)
    except Exception as exc:
        die('站点不可达：%s' % exc)

    sess = {}
    for role, login_name in (('admin', 'admin'),
                             ('backoffice', 'backoffice@local'),
                             ('faculty', 'faculty@local'),
                             ('student', 'stu@local'),
                             ('parent', 'parent@local')):
        sess[role], uid = G.login(login_name, 'demo123')
        if not sess[role]:
            die('登录失败：%s' % login_name)
    print('    登录 OK：admin / backoffice@local / faculty@local / stu@local / parent@local')
    adm = sess['admin']

    exp = db_grade_tasks()
    readings['db_grade_tasks'] = {str(k): v for k, v in exp.items()}
    print('    库读数（可整班打分任务 id→state，教务口径）：%s' % exp)
    sid_raw = G.psql('select id from op_student where active order by id limit 1')
    sid = int(sid_raw) if (sid_raw or '').strip().isdigit() else None
    if sid is None:
        die('库读不到 op_student ⇒ 夹具建不起来')

    if args.restore_arch:
        return restore_arch(sess)
    global SHOTS
    SHOTS = args.shots
    try:
        if 's' in want:
            section_s()
        if 'a' in want:
            section_a(sess, exp)
        if 'b' in want:
            section_b(sess, exp)
        if 'c' in want:
            section_c(sess, exp)
        if 'd' in want:
            section_d(sess, adm, exp)
        if 'e' in want:
            section_e(sess)
        if 'f' in want:
            section_f(sess, adm, exp, sid)
        if 'g' in want:
            section_g(sess, args.no_axe)
        if 'i' in want:
            section_i(sess, adm)
        take_shots(sess, [
            ('backoffice', '/assess', 'assess_backoffice_with_tasks.png',
             '教务 /assess：常驻卡片 + 有 N 个进行中'),
            ('faculty', '/assess', 'assess_faculty_with_tasks.png',
             '教师 /assess：常驻卡片（无「去新建任务」）'),
            ('backoffice', '/assess/review', 'assess_review_backoffice.png',
             '教务 /assess/review：每行可打分'),
        ])
    except requests.exceptions.RequestException as exc:
        # 共享工作区纪律：并行 agent 的 safe_upgrade 会重启 web，请求中途断开。
        # 那是 ENV 作废，不是断言红 —— 先兜底还原两个注入窗口，再退回 2。
        safety_restore()
        die('站点中途不可达（并行 agent 的 safe_upgrade？）：%s' % exc)
    except Exception as exc:                     # noqa: BLE001 兜底还原后照样退 2
        safety_restore()
        die('运行期异常（已尽量还原）：%r' % exc)
    finally:
        cleanup(adm, skip=args.keep)

    passed = sum(1 for i in items if i['pass'])
    failed = [i for i in items if not i['pass']]
    print('\n== 小结：%d/%d 通过（N/A %d 条）=='
          % (passed, len(items), len(nas)))
    for i in failed:
        print('   FAIL %s %s ｜ %s' % (i['no'], i['name'], i['detail'][:200]))
    for n in nas:
        print('   N/A  %s %s ｜ %s' % (n['no'], n['name'], n['reason'][:160]))
    payload = {'base': BASE, 'when': time.strftime('%Y-%m-%d %H:%M:%S'),
               'items': items, 'passed': passed, 'failed': len(failed),
               'nas': nas, 'readings': readings}
    json.dump(payload, open(RESULTS, 'w'), ensure_ascii=False, indent=1)
    print('结果落盘：%s' % RESULTS)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

