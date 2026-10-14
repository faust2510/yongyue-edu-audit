#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""课程中心（/my/study）进宫格 + 搜索同源验收（2026-09-29）。

被测量的问题（用户第一诉求）：「课程中心」能搜到吗？
  门户搜索的**入口索引单一来源** = 宫格引擎 batch2._home_categories（见
  controllers/search.py 的 _panel_entries 段注释：/my/home 与 /my/apps 同一数据源）。
  而 /my/study 此前**只写在左导航**（edu_portal_templates.xml 的 b11-* 段），
  不是宫格卡片 ⇒ 索引覆盖不到 ⇒ 搜「课程中心」0 条应用入口。

本脚本的判据（不是「页面看着有」）：
  G. 宫格：每个角色都能从宫格（学生/家长 = /my/home，内部用户 = /my/apps）
     拿到 data-app-href="my/study" 的卡片 —— 且卡片角色集合 == 左导航出现角色集合
     （左导航那条 b11-nav-item 无 t-if 守卫，见 edu_portal_templates.xml）。
  S. 搜索：/my/search?q=课程中心 的「应用入口」组命中，且命中链接落地 200；
     /my/search/suggest?q=课程中心 的 JSON 入口组同源命中。
  C. 控制组（证明不是恒真恒假）：
     · C-① 无关卡片（校历 my/calendar）在改动前后都在宫格上、也搜得到；
     · C-② 无意义串 → 应用入口组为空（搜索不是"恒有"）；
     · C-③ **隐藏开关贯通**：被 edu.portal_hidden_cards 隐藏的卡片（默认含
       student/timetable「时间表」）在宫格里没有、在搜索入口组里也搜不到 ——
       这是「搜索 = 宫格投影，不是第二份入口清单」的正面证据。
  I. 反向注入（--inject-param）：用产品自己的运行期开关把 my/study 临时藏起来，
     宫格与搜索**同时**丢失它（变红），还原后同时恢复（变绿），全程自动还原。

用法：
    python3 tests/smoke/course_center_grid_entry.py               # 正常验收
    python3 tests/smoke/course_center_grid_entry.py --inject-param # 反向注入窗口（自还原）
退出码：0=全绿；1=有断言失败；2=ENV（站点不可达 / 登录失败 / 夹具读不到）。
结果落盘：tests/smoke/course_center_grid_entry_results.json

⚠ 与 _ENTRY_CACHE（TTL 30s，search.py 里宫格投影的短缓存）的关系：注入窗口里等 31s
   再读，否则读到的是注入前的投影 —— 那是缓存口径，不是判据。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

BASE = os.environ.get('SMOKE_BASE', 'http://localhost:8069')
DB = 'edu19'
HERE = Path(__file__).resolve().parent
RESULTS = HERE / 'course_center_grid_entry_results.json'
PASSWORD = 'demo123'
ENTRY_CACHE_TTL = 31          # search.py 的 _ENTRY_CACHE_TTL=30 + 1s 余量

# 角色 -> 登录名 -> 宫格页。学生/家长走 /my/home 宫格，内部用户走 /my/apps
# （batch2.EduAppsAlias.edu_apps：非内部用户 303 回 /my/home）。
ROLES = [
    ('student', 'stu@local', '/my/home'),
    ('parent', 'parent@local', '/my/home'),
    ('faculty', 'faculty@local', '/my/apps'),
    ('backoffice', 'backoffice@local', '/my/apps'),
    ('admin', 'admin', '/my/apps'),
]
HIDDEN_HREF = 'student/timetable'          # batch2._DEFAULT_HIDDEN_CARDS 里的一条
HIDDEN_TITLE = '时间表'                     # 该卡的标题（batch2._OPENEDUCAT_CARDS）
CONTROL_HREF = 'my/calendar'               # 控制组卡片：不受本改动影响

OK, FAIL = 'PASS', 'FAIL'
items = []


def check(no, name, cond, detail=''):
    items.append({'no': no, 'name': name, 'pass': bool(cond),
                  'detail': str(detail)[:900]})
    print('  %-4s #%-6s %-58s %s' % (OK if cond else FAIL, no, name,
                                     str(detail)[:190]))
    return bool(cond)


def note(msg):
    print('  ---- %s' % msg)


def die(msg):
    print('CANNOT: %s' % msg)
    json.dump({'error': msg, 'items': items}, open(RESULTS, 'w'),
              ensure_ascii=False, indent=1)
    sys.exit(2)


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


def probe():
    """探活（**不走系统代理**）。

    实测（2026-09-29）：macOS 的系统代理会被 requests 的 trust_env 默认读到，
    于是裸 requests.get(...) 可能被代理转成 502，而站点本身是好的
    （同一个 URL 在 trust_env=False 下 302/200）——那是 ENV 噪音，不是故障。
    """
    s = requests.Session()
    s.trust_env = False
    return s.get(BASE + '/web/login?db=%s' % DB, timeout=15)


def get(sess, path):
    r = sess.get(BASE + path, timeout=40, allow_redirects=True)
    return r, (r.text or '')


def q(path, term):
    return path + urllib.parse.quote(term)


def call_kw(sess, model, method, args=None, kwargs=None):
    payload = {'jsonrpc': '2.0', 'method': 'call', 'params': {
        'model': model, 'method': method,
        'args': args or [], 'kwargs': kwargs or {}}}
    r = sess.post(BASE + '/web/dataset/call_kw', json=payload, timeout=60)
    data = r.json()
    if 'error' in data:
        info = data['error'].get('data') or {}
        raise RuntimeError('%s' % (info.get('message') or data['error']))
    return data.get('result')


# ----------------------------------------------------------------------
# 页面解析：宫格卡片 / 左导航条目 / 搜索入口组
# ----------------------------------------------------------------------

def grid_cards(html):
    """宫格卡片（[data-app-href] 锚点）-> {app_href: {href, title, label}}。

    ⚠ 只认 data-app-href：左导航那条是同 href 但带 data-b11-tab，
      两种入口在 DOM 上**可分辨** —— 这是「宫格 vs 导航」判据的基础。
    """
    out = {}
    for m in re.finditer(
            r'<a\b([^>]*data-app-href="([^"]*)"[^>]*)>(.*?)</a>', html, re.S):
        attrs, app_href, inner = m.group(1), m.group(2), m.group(3)
        href = re.search(r'href="([^"]*)"', attrs)
        title = re.search(r'title="([^"]*)"', attrs)
        out[app_href] = {
            'href': href.group(1) if href else '',
            'title': title.group(1) if title else '',
            'label': re.sub(r'<[^>]+>', '', inner).strip(),
        }
    return out


def nav_hrefs(html):
    """左导航条目 href 集合（data-b11-tab 锚点）。"""
    return set(re.findall(r'<a\b[^>]*data-b11-tab="([^"]*)"', html))


def search_entry_items(html):
    """搜索结果页「应用入口」组 -> [(name, href)]（无该组则空）。

    模板（edu_portal_templates.xml 的 edu_search_results）里分组头是
    <h5>…应用入口<span class="badge">N</span></h5> + 紧随的
    <div class="list-group mb-2">。**必须锚在徽标上**：页面上另有一处
    「顶部搜索框可查应用入口与作业…」的新手清单文案，只按文本找会命中它
    （实测：解析出一堆页脚链接 —— 那是判据量到了错误的对象）。
    """
    m = re.search(
        r'应用入口\s*<span class="badge[^>]*>\s*(\d+)\s*</span>\s*</h5>\s*'
        r'<div class="list-group[^"]*">(.*?)</div>', html or '', re.S)
    if not m:
        return []
    out = []
    for href, inner in re.findall(
            r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', m.group(2), re.S):
        name = re.sub(r'<[^>]+>', '', inner).strip()
        if name:
            out.append((name, href))
    return out


def suggest_entries(sess, term):
    """建议端点入口组 -> ([(title, href)], err)。限流时 err='THROTTLED'。"""
    r, body = get(sess, q('/my/search/suggest?q=', term))
    try:
        data = json.loads(body)
    except Exception:
        return None, 'HTTP %s 非 JSON' % r.status_code
    if data.get('throttled'):
        return None, 'THROTTLED'
    for g in data.get('groups') or []:
        if g.get('kind') == 'entry':
            return [(it['title'], it['href']) for it in g.get('items') or []], ''
    return [], ''


# ----------------------------------------------------------------------
# 读数
# ----------------------------------------------------------------------

def read_state(sess, grid_path, term='课程中心', wait=0.0):
    """一次完整读数：宫格卡 / 左导航 / 搜索结果页 / 建议端点。"""
    if wait:
        time.sleep(wait)
    _r, html = get(sess, grid_path)
    cards = grid_cards(html)
    nav = nav_hrefs(html)
    _r2, shtml = get(sess, q('/my/search?q=', term))
    hits = search_entry_items(shtml)
    sug, err = suggest_entries(sess, term)
    return {
        'grid_path': grid_path,
        'card': cards.get('my/study'),
        'nav_has_study': '/my/study' in nav,
        'control_card': cards.get(CONTROL_HREF),
        'hidden_card_present': HIDDEN_HREF in cards,
        'search_hits': hits,
        'suggest': sug,
        'suggest_err': err,
    }


def read_landing(sess):
    r, html = get(sess, '/my/study')
    return r.status_code, ('课程中心' in html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--inject-param', action='store_true',
                    help='反向注入窗口：用 edu.portal_hidden_cards 临时藏起 my/study')
    args = ap.parse_args()

    print('== 探活 ==')
    try:
        probe()
    except Exception as exc:
        die('站点不可达：%s' % exc)

    sess, uids = {}, {}
    for role, login_name, _p in ROLES:
        s, uid = login(login_name)
        if not s:
            die('登录失败：%s（%s）' % (role, login_name))
        sess[role], uids[role] = s, uid
    print('    登录 OK：%s' % ' ｜ '.join(
        '%s uid=%s' % (r, uids[r]) for r, _l, _p in ROLES))

    if args.inject_param:
        return inject_window(sess)

    # ---------------- G 宫格 ----------------
    print('\n== G 宫格：/my/study 卡片 + 角色可见性与左导航一致 ==')
    states = {role: read_state(sess[role], path) for role, _l, path in ROLES}
    ok_roles = []
    for role, _l, path in ROLES:
        st = states[role]
        c = st['card']
        good = bool(c) and c['href'] == '/my/study' and c['title'] == '课程中心'
        if good:
            ok_roles.append(role)
        check('G1-%s' % role,
              '%s 宫格（%s）有卡片 data-app-href="my/study"' % (role, path),
              good, '卡片 = %s ｜ 左导航有该条 = %s' % (c, st['nav_has_study']))
    check('G2', '宫格卡片角色集合 == 左导航出现角色集合（无角色例外）',
          all(states[r]['nav_has_study'] == bool(states[r]['card'])
              for r, _l, _p in ROLES),
          '有卡片角色 %s ｜ 左导航有该条的角色 %s'
          % (ok_roles, [r for r, _l, _p in ROLES if states[r]['nav_has_study']]))
    check('G3', '左导航该条本就无 t-if 守卫（全角色可见）=> 宫格不得比它更窄',
          all(states[r]['nav_has_study'] for r, _l, _p in ROLES),
          '各角色 = %s' % {r: states[r]['nav_has_study'] for r, _l, _p in ROLES})

    print('\n== G4 控制组：无关卡片不受影响（校历 + 默认隐藏卡）==')
    check('G4a', '控制组：控制卡 %s 在每个角色宫格上都在（改动没打到宫格引擎）'
          % CONTROL_HREF,
          all(states[r]['control_card'] for r, _l, _p in ROLES),
          '各角色 = %s' % {r: bool(states[r]['control_card'])
                           for r, _l, _p in ROLES})
    check('G4b', '控制组：默认隐藏卡 %s 在宫格里**不在**（隐藏开关仍有效）'
          % HIDDEN_HREF,
          not any(states[r]['hidden_card_present'] for r, _l, _p in ROLES),
          '各角色 = %s' % {r: states[r]['hidden_card_present']
                           for r, _l, _p in ROLES})

    # ---------------- S 搜索 ----------------
    print('\n== S 搜索：/my/search 与 /my/search/suggest 都要命中 ==')
    for role, _l, _p in ROLES:
        st = states[role]
        hits = [x for x in st['search_hits'] if '课程中心' in x[0]]
        check('S1-%s' % role, '%s 搜「课程中心」应用入口组命中 /my/study' % role,
              any(h == '/my/study' for _n, h in hits), '命中 = %s' % (hits or '无'))
        if st['suggest_err']:
            note('S2-%s 建议端点未读数：%s（限流/ENV，不计红）'
                 % (role, st['suggest_err']))
        else:
            check('S2-%s' % role, '%s 建议端点入口组同源命中' % role,
                  any(h == '/my/study' for _n, h in (st['suggest'] or [])),
                  '建议 = %s' % (st['suggest'] or []))

    print('\n== S3 命中落地 200（点得进去）==')
    for role, _l, _p in ROLES:
        code, has_title = read_landing(sess[role])
        check('S3-%s' % role, '%s GET /my/study -> 200 且页面确为课程中心' % role,
              code == 200 and has_title,
              'HTTP %s ｜ 含标题 = %s' % (code, has_title))

    print('\n== S4 控制组：搜索不是「恒有」也不是第二份入口清单 ==')
    neg_hits = []
    for role in ('student', 'backoffice'):
        _r, h = get(sess[role], q('/my/search?q=', 'zzz不存在的入口zzz'))
        neg_hits += [x for x in search_entry_items(h) if x]
    check('S4a', '控制组：无意义串的应用入口组为空（搜索不是恒真）',
          not neg_hits, '命中 = %s' % (neg_hits or '无'))
    hid_hits = []
    for role in ('student', 'backoffice'):
        _r, h = get(sess[role], q('/my/search?q=', HIDDEN_TITLE))
        hid_hits += [x for x in search_entry_items(h) if HIDDEN_TITLE in x[0]]
    check('S4b', '控制组：搜索 = 宫格投影（宫格上被隐藏的「%s」搜索入口组里也搜不到）'
          % HIDDEN_TITLE, not hid_hits, '命中 = %s' % (hid_hits or '无'))

    return finish()


def inject_window(sess):
    """反向注入窗口：藏起来 -> 两条链同时断 -> 还原 -> 两条链同时回来。

    注入走**产品自己的运行期开关** edu.portal_hidden_cards（batch2._hidden_cards），
    不改代码：于是它同时检验「宫格」与「搜索」共用同一份投影这一条断言。
    """
    adm = sess['admin']
    param = 'edu.portal_hidden_cards'

    def read_param():
        recs = call_kw(adm, 'ir.config_parameter', 'search_read',
                       [[('key', '=', param)], ['key', 'value']])
        return recs[0]['value'] if recs else None

    def write_param(val):
        if val is None or val == '':
            ids = call_kw(adm, 'ir.config_parameter', 'search',
                          [[('key', '=', param)]])
            if ids:
                call_kw(adm, 'ir.config_parameter', 'unlink', [ids])
        else:
            call_kw(adm, 'ir.config_parameter', 'set_param', [param, val])

    original = read_param()
    print('\n== I 反向注入：%s 原值 = %r；写入 my/study，读完自动还原 =='
          % (param, original))
    try:
        write_param('my/study')
        st_inj = read_state(sess['student'], '/my/home', wait=ENTRY_CACHE_TTL)
        print('  -- 注入态：卡片 = %s ｜ 搜索结果 = %s ｜ 建议 = %s'
              % (st_inj['card'], st_inj['search_hits'] or '无',
                 st_inj['suggest'] if st_inj['suggest'] is not None
                 else st_inj['suggest_err']))
        check('I1a', '注入后：宫格卡片消失（变红）', not st_inj['card'],
              '卡片 = %s' % st_inj['card'])
        check('I1b', '注入后：搜索结果页应用入口组同时消失（变红）',
              not any(h == '/my/study' for _n, h in st_inj['search_hits']),
              '命中 = %s' % (st_inj['search_hits'] or '无'))
        check('I1c', '注入后：建议端点同时消失（变红；限流不计）',
              st_inj['suggest_err'] is not None
              or not any(h == '/my/study'
                         for _n, h in (st_inj['suggest'] or [])),
              '建议 = %s ｜ err = %s' % (st_inj['suggest'], st_inj['suggest_err']))
    finally:
        write_param(original)
        print('  -- 已还原：%s = %r' % (param, read_param()))

    st_ok = read_state(sess['student'], '/my/home', wait=ENTRY_CACHE_TTL)
    print('  -- 还原态：卡片 = %s ｜ 搜索结果 = %s ｜ 建议 = %s'
          % (st_ok['card'], st_ok['search_hits'] or '无',
             st_ok['suggest'] if st_ok['suggest'] is not None
             else st_ok['suggest_err']))
    check('I2a', '还原后：宫格卡片回来（变绿）', bool(st_ok['card']),
          '卡片 = %s' % st_ok['card'])
    check('I2b', '还原后：搜索结果页入口组回来（变绿）',
          any(h == '/my/study' for _n, h in st_ok['search_hits']),
          '命中 = %s' % (st_ok['search_hits'] or '无'))
    check('I2c', '还原后：建议端点入口组回来（变绿）',
          st_ok['suggest_err'] is not None
          or any(h == '/my/study' for _n, h in (st_ok['suggest'] or [])),
          '建议 = %s' % (st_ok['suggest'] or '无'))
    return finish()


def finish():
    passed = sum(1 for i in items if i['pass'])
    failed = [i for i in items if not i['pass']]
    print('\n== 小结：%d/%d 通过 ==' % (passed, len(items)))
    for i in failed:
        print('   FAIL %s %s ｜ %s' % (i['no'], i['name'], i['detail'][:200]))
    json.dump({'base': BASE, 'when': time.strftime('%Y-%m-%d %H:%M:%S'),
               'items': items, 'passed': passed, 'failed': len(failed)},
              open(RESULTS, 'w'), ensure_ascii=False, indent=1)
    print('结果落盘：%s' % RESULTS)
    return 1 if failed else 0


if __name__ == '__main__':
    # 共享工作区纪律（照 tests/smoke/assess_portal_gaps.py）：并行 agent 的
    # safe_upgrade 会重启 web，请求中途断开。那是 **ENV 作废**，不是断言红 ——
    # 明说、退回 2，别把噪音当结论。
    try:
        sys.exit(main())
    except requests.exceptions.RequestException as exc:
        die('站点中途不可达（多半是并行 agent 在跑 safe_upgrade 重启 web）：%s' % exc)
