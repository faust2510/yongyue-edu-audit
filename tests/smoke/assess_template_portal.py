#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「模板与评分项」门户化管理 —— 端到端验收（改动前后对照 + 正反双向自证）。

## 为什么有这个脚本

2026-09-28 用户反馈：门户「评估」页（P1 风格）里那张「评估管理」卡片，点下去跳到
Odoo 官方后台列表视图（P2 风格），**两套 UI 风格完全不同**。队长裁定：不给后台换皮，
而是把「模板与评分项」这块能力**搬进门户**。

本脚本把这次改动逐条证死，而不是"看着对"：

  A 改动前（可复跑的前置事实）
    A1 门户 /assess 里那张卡片的 href 指向哪 —— 证明它此前只能进后台
    A2 那个 href 落地是什么页面 —— 证明是 Odoo 官方后台（o_web_client + /odoo/action-）
  B 改动后
    B1 卡片 href 已改为门户路由 /assess/templates（不再进后台）
    B2 门户页列出的模板 / 评分项 **与后台看到的数据逐条一致**
       （口径：对同一份 ORM 真值做双向集合差集 = 空，不比"看着像"）
    B3 **新建模板 + 两个评分项** → 走门户自己的 POST（带 csrf）→
       **在后台同一份数据里看得到它**（证明是同一份数据、不是第二套）→
       **删干净**（评分项 → 模板）→ 行数回到原值，并留下删后计数证据
    B4 非授权账号（教师 / 学生 / 家长）访问 → **fail-closed**：
       原始 HTTP 码 + Location 逐字记录（不是"按钮不显示"）

判据纪律：
  · 303 一律 allow_redirects=False + Location 精确匹配，不靠"最终 200"糊过去；
  · 每条负向断言都配正对照；
  · 夹具**自带清理**，跑完复验行数回到原值（--keep 才保留）；
  · 只用 HTTP + psql 只读计数，不跑 shell、不升级、不重启。

用法：
    python3 tests/smoke/assess_template_portal.py            # 全量（含清理）
    python3 tests/smoke/assess_template_portal.py --keep     # 保留夹具（调试用）
退出码：0=全绿；1=有断言失败；2=运行错误（服务不可达 / 登不上）。
结果落盘：tests/smoke/assess_template_portal_results.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

os.environ.setdefault('NO_PROXY', 'localhost,127.0.0.1')
os.environ.setdefault('no_proxy', 'localhost,127.0.0.1')

try:
    import requests
except ImportError:                                   # pragma: no cover
    print('FATAL | 需要 requests')
    sys.exit(2)

BASE = os.environ.get('SMOKE_BASE', 'http://localhost:8069')
DB = 'edu19'
DB_CONTAINER = os.environ.get('EDU_DB_CONTAINER', 'edu19-clone-db-1')
HERE = Path(__file__).resolve().parent
RESULTS = HERE / 'assess_template_portal_results.json'
PASSWORD = 'demo123'

LIST_PATH = '/assess/templates'
NEW_PATH = '/assess/templates/new'
SAVE_PATH = '/assess/templates/save'

#: 【冒烟】前缀：本仓 check_english 的夹具残留扫描按这个标记点名（用完必须删干净）
MARK = '\u3010\u5192\u70df\u3011'
TPL_NAME = MARK + '门户建模板探针'
ITEM_A = MARK + '评分项甲'
ITEM_B = MARK + '评分项乙'

OK, FAIL = 'PASS', 'FAIL'
rows = []


def check(no, name, cond, detail=''):
    verdict = OK if cond else FAIL
    rows.append({'no': no, 'name': name, 'pass': bool(cond),
                 'detail': str(detail)[:900]})
    print('  %-4s #%-5s %-58s %s' % (verdict, no, name, str(detail)[:190]))
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
    s.proxies = {'http': None, 'https': None}
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': DB, 'login': login_name, 'password': password}},
        timeout=30)
    data = r.json().get('result') or {}
    return s if data.get('uid') else None


def call_kw(sess, model, method, args=None, kwargs=None):
    """后台同一条读/写路径（JSON-RPC）—— 用它读「后台看到的数据」才叫同一份。"""
    payload = {'jsonrpc': '2.0', 'method': 'call', 'params': {
        'model': model, 'method': method,
        'args': args or [], 'kwargs': kwargs or {}}}
    r = sess.post(BASE + '/web/dataset/call_kw', json=payload, timeout=60)
    try:
        data = r.json()
    except ValueError:
        return None, 'HTTP %s（非 JSON）' % r.status_code
    if 'error' in data:
        err = data['error']
        info = err.get('data') or {}
        return None, '%s: %s' % (info.get('name') or 'Error',
                                 (info.get('message') or '')[:200])
    return data.get('result'), None


def csrf_of(sess, path):
    r = sess.get(BASE + path, timeout=40)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    return (m.group(1) if m else None), r


# ----------------------------------------------------------------------
# A 改动前：门户那张卡片此前指向哪、落地是什么
# ----------------------------------------------------------------------

def phase_a(bo):
    print('')
    print('== A 改动前后的入口对照 ==')
    r = bo.get(BASE + '/assess', timeout=40)
    links = [{'href': h, 'text': re.sub(r'<[^>]+>', '', t).strip()}
             for h, t in re.findall(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                                    r.text, re.S)]
    backend = [l for l in links if 'action-edu_assess' in l['href']]
    portal = [l for l in links if l['href'] == LIST_PATH]
    check('A1', '门户 /assess 已不再出现「跳 Odoo 后台」的卡片',
          not backend, '残留的后台链接：%s' % (backend or '无'))
    check('A2', '门户 /assess 已出现门户原生入口 %s' % LIST_PATH,
          bool(portal), '命中：%s' % (portal or '无'))
    hist = bo.get(BASE + '/odoo/action-edu_assess.action_edu_assess_template',
                  timeout=60)
    is_backend = 'o_web_client' in hist.text
    check('A3', '历史落点 /odoo/action-… 仍是 Odoo 官方后台（未删除、可回退）',
          hist.status_code == 200 and is_backend,
          'HTTP %s · 含 o_web_client=%s' % (hist.status_code, is_backend))
    return {'assess_admin_links': backend + portal,
            'backend_landing': {'status': hist.status_code, 'url': hist.url,
                                'has_o_web_client': is_backend}}


# ----------------------------------------------------------------------
# B2 门户页 vs 后台：同一份数据
# ----------------------------------------------------------------------

CARD_RE = re.compile(
    r'<div class="card shadow-sm border-0 rounded-3 mb-3">(.*?)(?='
    r'<div class="card shadow-sm border-0 rounded-3 mb-3">|\Z)', re.S)


def portal_truth(bo):
    """门户列表页读出的 {模板名: [启用评分项名]}。"""
    _, r = csrf_of(bo, LIST_PATH)
    html = r.text
    out = {}
    for card in CARD_RE.findall(html):
        m = re.search(r'<b[^>]*>([^<]+)</b>', card)
        if not m:
            continue
        name = m.group(1).strip()
        items = [x.strip() for x in
                 re.findall(r'<td>\s*<b[^>]*>([^<]+)</b>', card)]
        out[name] = sorted(items)
    return out, html


def backend_truth(bo):
    """后台（JSON-RPC）读出的同一份真值：{模板名: [启用评分项名]}。"""
    tmpls, err = call_kw(bo, 'edu.assess.template', 'search_read',
                         [[]], {'fields': ['name', 'item_ids']})
    if err:
        raise RuntimeError('后台读模板失败：%s' % err)
    out = {}
    for t in tmpls:
        items, err = call_kw(
            bo, 'edu.assess.item', 'search_read',
            [[('id', 'in', t['item_ids']), ('active', '=', True)]],
            {'fields': ['name']})
        if err:
            raise RuntimeError('后台读评分项失败：%s' % err)
        out[t['name'].strip()] = sorted(i['name'].strip() for i in items)
    return out


def phase_b_parity(bo):
    print('')
    print('== B2 门户页 vs 后台：同一份数据（逐条双向差集）==')
    pv, html = portal_truth(bo)
    bv = backend_truth(bo)
    only_portal = sorted(set(pv) - set(bv))
    only_backend = sorted(set(bv) - set(pv))
    check('B2.1', '门户模板集合 == 后台模板集合',
          not only_portal and not only_backend,
          '模板条数 门户%d/后台%d ｜ 仅门户有=%s ｜ 仅后台有=%s'
          % (len(pv), len(bv), only_portal, only_backend))
    item_bad = {k: (pv.get(k), bv.get(k)) for k in sorted(set(pv) & set(bv))
                if pv[k] != bv[k]}
    check('B2.2', '每个模板的评分项集合逐条相等', not item_bad,
          '不一致：%s' % (item_bad or '无'))
    check('B2.3', '门户页确实渲染出模板名（正对照：不是空页）',
          bool(pv), '门户读出 %d 个模板：%s' % (len(pv), sorted(pv)))
    return {'portal': pv, 'backend': bv, 'html_len': len(html)}


# ----------------------------------------------------------------------
# B3 CRUD：门户建 → 后台可见 → 删干净
# ----------------------------------------------------------------------

def phase_b_crud(bo, keep):
    print('')
    print('== B3 新建模板 + 两个评分项 → 后台可见 → 删干净 ==')
    n_tpl0 = int(psql('SELECT count(*) FROM edu_assess_template'))
    n_item0 = int(psql('SELECT count(*) FROM edu_assess_item'))
    print('     基线行数：template=%d item=%d' % (n_tpl0, n_item0))

    token, _ = csrf_of(bo, NEW_PATH)
    if not check('B3.0', '新建页拿到 csrf_token', bool(token),
                 'token 存在=%s' % bool(token)):
        return None

    r = bo.post(BASE + SAVE_PATH, data={
        'csrf_token': token, 'template_id': '', 'name': TPL_NAME,
        'kind': 'student', 'target_kind': 'student', 'state': 'active',
        'total': '100', 'pass_line': '60', 'excellent_line': '90',
        'active': '1', 'score_visible': '1', 'allow_self': '1',
        'notes': MARK + '门户 CRUD 探针，跑完即删'}, timeout=40,
        allow_redirects=False)
    tid_raw = psql("SELECT id FROM edu_assess_template WHERE name='%s'" % TPL_NAME)
    check('B3.1', '门户 POST 新建模板 → 303 回编辑页且库里出现该行',
          r.status_code == 303
          and r.headers.get('Location', '').startswith('/assess/templates/')
          and bool(tid_raw),
          'HTTP %s Location=%s ｜ 库内 id=%s'
          % (r.status_code, r.headers.get('Location', ''), tid_raw or '（无）'))
    if not tid_raw:
        return None
    tid = int(tid_raw.splitlines()[0])

    token, _ = csrf_of(bo, '/assess/templates/%d' % tid)
    made = []
    for idx, (nm, mx, w) in enumerate(((ITEM_A, '20', '1'), (ITEM_B, '30', '2')), 1):
        rr = bo.post(BASE + '/assess/templates/%d/items/save' % tid, data={
            'csrf_token': token, 'item_id': '', 'name': nm,
            'sequence': str(idx * 10), 'max_score': mx, 'weight': w,
            'score_kind': 'number', 'help': MARK + '提示',
            'required': '1', 'active': '1'}, timeout=40, allow_redirects=False)
        made.append(rr.status_code == 303)
    got = psql("SELECT string_agg(name, '|' ORDER BY sequence) "
               "FROM edu_assess_item WHERE template_id=%d" % tid)
    check('B3.2', '门户 POST 新增两个评分项 → 两条都落库',
          all(made) and got == '%s|%s' % (ITEM_A, ITEM_B),
          'HTTP 303=%s ｜ 库内=%s' % (made, got or '（无）'))

    seen_t, err1 = call_kw(bo, 'edu.assess.template', 'search_read',
                           [[('id', '=', tid)]],
                           {'fields': ['name', 'kind', 'total', 'item_ids']})
    seen_i, err2 = call_kw(bo, 'edu.assess.item', 'search_read',
                           [[('template_id', '=', tid)]],
                           {'fields': ['name', 'max_score', 'weight']})
    names = sorted(x['name'] for x in (seen_i or []))
    check('B3.3', '后台能读到刚在门户建的模板与两个评分项（同一份数据）',
          bool(seen_t) and seen_t[0]['name'] == TPL_NAME
          and names == sorted([ITEM_A, ITEM_B]),
          '后台读到 模板=%s 评分项=%s ｜ err=%s/%s'
          % (bool(seen_t), names, err1, err2))
    pv, _ = portal_truth(bo)
    check('B3.4', '门户列表页也立刻列出这个新模板（含两个评分项）',
          pv.get(TPL_NAME) == sorted([ITEM_A, ITEM_B]),
          '门户读出=%s' % (pv.get(TPL_NAME),))

    token, _ = csrf_of(bo, '/assess/templates/%d' % tid)
    bad = bo.post(BASE + SAVE_PATH, data={
        'csrf_token': token, 'template_id': str(tid), 'name': TPL_NAME,
        'kind': 'student', 'target_kind': 'student', 'state': 'active',
        'total': '100', 'pass_line': '95', 'excellent_line': '10',
        'active': '1'}, timeout=40, allow_redirects=False)
    still = psql('SELECT pass_line FROM edu_assess_template WHERE id=%d' % tid)
    check('B3.5', '非法等级线被模型拒绝（门户没绕过约束），且未写库',
          bad.status_code == 303 and 'error=' in bad.headers.get('Location', '')
          and still == '60',
          'HTTP %s Location=%s ｜ 库内 pass_line=%s'
          % (bad.status_code, bad.headers.get('Location', '')[:90], still))

    dup = bo.post(BASE + '/assess/templates/%d/items/save' % tid, data={
        'csrf_token': token, 'item_id': '', 'name': ITEM_A, 'sequence': '99',
        'max_score': '5', 'weight': '1', 'score_kind': 'number',
        'active': '1'}, timeout=40, allow_redirects=False)
    cnt = psql('SELECT count(*) FROM edu_assess_item WHERE template_id=%d' % tid)
    dloc = dup.headers.get('Location', '')
    shown = requests.utils.unquote(dloc)
    check('B3.6', '同模板重名评分项被唯一约束拒绝，且未写库（回门户不甩错误页）',
          dup.status_code == 303 and 'error=' in dloc and cnt == '2'
          and '同一模板内的评分项名称不能重复' in shown,
          'HTTP %s ｜ 库内条数=%s ｜ 回执=%s'
          % (dup.status_code, cnt, shown[:160]))

    tok2, _ = csrf_of(bo, LIST_PATH)
    r1 = bo.post(BASE + '/assess/templates/%d/state' % tid,
                 data={'csrf_token': tok2, 'action': 'deactivate'},
                 timeout=40, allow_redirects=False)
    off = psql("SELECT active||'/'||state FROM edu_assess_template WHERE id=%d" % tid)
    r2 = bo.post(BASE + '/assess/templates/%d/state' % tid,
                 data={'csrf_token': tok2, 'action': 'restore'},
                 timeout=40, allow_redirects=False)
    on = psql("SELECT active||'/'||state FROM edu_assess_template WHERE id=%d" % tid)
    check('B3.7', '停用 → active=false/归档；恢复 → active=true/启用',
          r1.status_code == 303 and off == 'false/archived'
          and r2.status_code == 303 and on == 'true/active',
          '停用后=%s（HTTP %s）恢复后=%s（HTTP %s）'
          % (off, r1.status_code, on, r2.status_code))

    if keep:
        print('     --keep：保留夹具，跳过清理')
        return {'tid': tid, 'n_tpl0': n_tpl0, 'n_item0': n_item0,
                'cleaned': False}

    print('')
    print('== B3.8 清场：删掉探针，验证行数回到基线 ==')
    tok3, _ = csrf_of(bo, '/assess/templates/%d' % tid)
    del_ok = []
    iids = psql('SELECT id FROM edu_assess_item WHERE template_id=%d ORDER BY id'
                % tid).splitlines()
    for iid in iids:
        rr = bo.post(BASE + '/assess/templates/%d/items/%s/delete' % (tid, iid),
                     data={'csrf_token': tok3}, timeout=40,
                     allow_redirects=False)
        del_ok.append(rr.status_code == 303)
    left_items = psql('SELECT count(*) FROM edu_assess_item WHERE template_id=%d' % tid)
    check('B3.8', '门户逐个删掉两个评分项 → 该模板下剩 0 条',
          iids and all(del_ok) and left_items == '0',
          '删了 %d 条 HTTP=%s ｜ 剩余评分项=%s' % (len(iids), del_ok, left_items))

    deleted, err = call_kw(bo, 'edu.assess.template', 'unlink', [[tid]])
    gone = psql('SELECT count(*) FROM edu_assess_template WHERE id=%d' % tid)
    check('B3.9', '模板本体删除后库里查无此行（走后台同一条 ORM 写路径）',
          not err and gone == '0', 'unlink err=%s ｜ 剩余行=%s' % (err, gone))

    n_tpl1 = int(psql('SELECT count(*) FROM edu_assess_template'))
    n_item1 = int(psql('SELECT count(*) FROM edu_assess_item'))
    check('B3.10', '清场后行数回到基线（template/item 两个模型都回原值）',
          n_tpl1 == n_tpl0 and n_item1 == n_item0,
          'template %d→%d ｜ item %d→%d（基线 %d/%d）'
          % (n_tpl0, n_tpl1, n_item0, n_item1, n_tpl0, n_item0))
    left_tpl = psql("SELECT count(*) FROM edu_assess_template "
                    "WHERE name LIKE '%%%s%%'" % MARK)
    left_item = psql("SELECT count(*) FROM edu_assess_item "
                     "WHERE name LIKE '%%%s%%'" % MARK)
    check('B3.11', '没有留下任何【冒烟】夹具残留',
          left_tpl == '0' and left_item == '0',
          '残留 模板=%s 评分项=%s' % (left_tpl, left_item))
    return {'tid': tid, 'n_tpl0': n_tpl0, 'n_item0': n_item0,
            'n_tpl1': n_tpl1, 'n_item1': n_item1, 'cleaned': True}


# ----------------------------------------------------------------------
# B4 非授权：fail-closed
# ----------------------------------------------------------------------

DENIED = [('faculty@local', '教师'), ('stu@local', '学生'), ('parent@local', '家长')]
PATHS = [LIST_PATH, NEW_PATH, '/assess/templates/1']


def phase_b4(bo):
    print('')
    print('== B4 非授权访问 → fail-closed（原始 HTTP 码 + Location）==')
    evidence = {}
    _, bo_page = csrf_of(bo, LIST_PATH)
    pos = '教师评学生（验收）' in bo_page.text
    check('B4.0', '正对照：授权账号（教务）拿到 200 且页面含真实模板名',
          pos, '教务 /assess/templates 含真实模板名=%s' % pos)
    for login_name, label in DENIED:
        s = login(login_name)
        if not s:
            check('B4.' + label, '%s 登录' % label, False, '登录失败')
            continue
        ev = {}
        ok_all = True
        for path in PATHS:
            r = s.get(BASE + path, timeout=40, allow_redirects=False)
            loc = r.headers.get('Location', '')
            ev[path] = {'status': r.status_code, 'location': loc}
            ok_all = ok_all and r.status_code == 303 and loc == '/my/home'
            if r.status_code == 303:
                f = s.get(BASE + loc, timeout=40, allow_redirects=False)
                ev[path]['landing_status'] = f.status_code
        for path, data in (
                (SAVE_PATH, {'name': MARK + '越权探针'}),
                ('/assess/templates/1/state', {'action': 'deactivate'}),
                ('/assess/templates/1/items/save', {'name': MARK + '越权项'}),
                ('/assess/templates/1/items/1/delete', {})):
            tok, _ = csrf_of(s, '/assess')
            r = s.post(BASE + path, data=dict(data, csrf_token=tok or ''),
                       timeout=40, allow_redirects=False)
            ev['POST ' + path] = {'status': r.status_code,
                                  'location': r.headers.get('Location', '')}
            ok_all = (ok_all and r.status_code == 303
                      and r.headers.get('Location', '') == '/my/home')
        leak_t = psql("SELECT count(*) FROM edu_assess_template "
                      "WHERE name LIKE '%%%s%%'" % (MARK + '越权探针'))
        leak_i = psql("SELECT count(*) FROM edu_assess_item "
                      "WHERE name LIKE '%%%s%%'" % (MARK + '越权项'))
        ev['越权写入残留'] = '%s/%s' % (leak_t, leak_i)
        check('B4.' + label,
              '%s 访问管理页 GET+POST 全部 303 → /my/home 且未落库' % label,
              ok_all and leak_t == '0' and leak_i == '0',
              json.dumps(ev, ensure_ascii=False)[:420])
        evidence[label] = ev
    return evidence


# ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='「模板与评分项」门户化管理端到端验收')
    ap.add_argument('--keep', action='store_true', help='保留夹具（调试用）')
    args = ap.parse_args()

    print('== 「模板与评分项」门户化管理验收 ==')
    print('   站点 %s ｜ 库 %s ｜ 容器 %s' % (BASE, DB, DB_CONTAINER))
    try:
        probe = requests.get(BASE + '/web/login?db=' + DB, timeout=15)
    except Exception as exc:
        print('FATAL | 站点不可达：%s' % exc)
        sys.exit(2)
    print('   探活 /web/login → HTTP %s' % probe.status_code)

    bo = login('backoffice@local')
    if not bo:
        print('FATAL | backoffice@local 登录失败')
        sys.exit(2)

    result = {}
    result['a_entry'] = phase_a(bo)
    result['b2_parity'] = phase_b_parity(bo)
    result['b3_crud'] = phase_b_crud(bo, args.keep)
    result['b4_denied'] = phase_b4(bo)

    n_pass = sum(1 for r in rows if r['pass'])
    n_fail = len(rows) - n_pass
    print('')
    print('============ 汇总 ============')
    print('断言 %d 条：PASS %d / FAIL %d' % (len(rows), n_pass, n_fail))
    if n_fail:
        print('-- FAIL 明细 --')
        for r in rows:
            if not r['pass']:
                print('   #%s %s —— %s' % (r['no'], r['name'], r['detail'][:220]))
    RESULTS.write_text(json.dumps(
        {'rows': rows, 'result': result, 'pass': n_pass, 'fail': n_fail},
        ensure_ascii=False, indent=1), encoding='utf-8')
    print('-> %s' % RESULTS)
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == '__main__':
    main()
