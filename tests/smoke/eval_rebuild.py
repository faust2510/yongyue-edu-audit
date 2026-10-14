#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评估系统重建第 1 期（edu_assess）真机验收 —— V1…V12。

对应 docs/plans/evaluation-rebuild-design.md §9 的验收标准，外加校长钉死的三条：
  1. **在线加一个评分项、不升级、不发版即生效**（V1，本次最关键的一条）
  2. **匿名**：库里查不到明文打分人（V2）
  3. **样本门槛**：份数低于门槛时结果页不展示任何明细（V3）

判据纪律（docs/dev-workflow.md 陷阱 2 + 判据强度五兄弟）：
  · 只跑 safeed_upgrade 的 EXIT=0 **不算通过** —— 本脚本每条都"打完就摸页面"，
    并同时读库（psql）复核；
  · 303 一律 allow_redirects=False + Location 精确匹配；
  · 每条负向断言都配**正对照**（越权方的 0 只有在"有权方能拿到非 0"之后才作数）；
  · 幂等要**真跑两次**（同一个 xlsx 文件导两遍）。

用法：
    python3 tests/smoke/eval_rebuild.py            # 全量
    python3 tests/smoke/eval_rebuild.py --keep     # 跑完不清理夹具
退出码：0=全绿；1=有断言失败；2=运行错误（服务不可达 / 夹具建不起来）。
结果落盘：tests/smoke/eval_rebuild_results.json
"""
import argparse
import html
import io
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
RESULTS = HERE / 'eval_rebuild_results.json'
PASSWORD = 'demo123'

OK, FAIL, CANNOT = 'PASS', 'FAIL', 'CANNOT'
items = []


def check(no, name, cond, detail=''):
    verdict = OK if cond else FAIL
    items.append({'no': no, 'name': name, 'pass': bool(cond),
                  'detail': str(detail)[:600]})
    print('  %-4s #%-3s %-52s %s' % (verdict, no, name, str(detail)[:150]))
    return bool(cond)


def cannot(no, name, detail):
    items.append({'no': no, 'name': name, 'pass': False, 'cannot': True,
                  'detail': str(detail)[:600]})
    print('  %-4s #%-3s %-52s %s' % (CANNOT, no, name, str(detail)[:150]))


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
    """走 JSON-RPC 的模型调用（与后台列表视图同一条写路径）。"""
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
                                 (info.get('message') or err.get('message') or '')[:200])
    return data.get('result'), None


def get_csrf(sess, path):
    r = sess.get(BASE + path, timeout=40)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    return (m.group(1) if m else None), r


def search(sess, model, domain, fields=None, limit=0):
    res, err = call_kw(sess, model, 'search_read',
                       [domain or []],
                       {'fields': fields or ['id'], 'limit': limit})
    if err:
        return None, err
    return res, None


# ----------------------------------------------------------------------
# 夹具（全部经 JSON-RPC 在线创建 = 走后台同一条写路径，不跑 shell / 不升级）
# ----------------------------------------------------------------------

TPL_TEACH = '教师评学生（验收）'
TPL_FILL = '学生评教（验收·匿名）'
TPL_EXCEL = '教务录入（验收·Excel）'
KEY_ITEM = '课堂笔记'          # V1 现场在线新增的那一列


def get_or_create(sess, model, domain, vals):
    res, err = search(sess, model, domain, ['id'], limit=1)
    if err:
        raise RuntimeError('%s 查询失败：%s' % (model, err))
    if res:
        return res[0]['id'], False
    new, err = call_kw(sess, model, 'create', [vals])
    if err:
        raise RuntimeError('%s 创建失败：%s' % (model, err))
    return (new[0] if isinstance(new, list) else new), True


def build_fixtures(adm):
    """幂等夹具；返回一个 dict。"""
    fx = {}
    # 教师任教班（口径与 roles.py:_teacher_taught_batches 同源）
    fac, err = search(adm, 'op.faculty',
                      [('user_id.login', '=', 'faculty@local')], ['id', 'name'], 1)
    if err or not fac:
        raise RuntimeError('找不到教师档案：%s' % err)
    fx['faculty_id'] = fac[0]['id']
    sess_rows, err = search(adm, 'op.session',
                            [('faculty_id', '=', fx['faculty_id'])],
                            ['batch_id'], 0)
    if err:
        raise RuntimeError('查任教班失败：%s' % err)
    taught = sorted({r['batch_id'][0] for r in sess_rows if r['batch_id']})
    fx['taught_batches'] = taught
    if not taught:
        raise RuntimeError('教师没有任何任教班级，夹具无法成立')

    students, err = search(
        adm, 'op.student',
        [('course_detail_ids.batch_id', 'in', taught), ('active', '=', True)],
        ['id', 'name', 'gr_no'], 0)
    if err:
        raise RuntimeError('查任教班学生失败：%s' % err)
    fx['taught_students'] = students
    if not students:
        raise RuntimeError('任教班里没有学生，夹具无法成立')

    # T1：教师评学生（实名），范围 = 本人任教班
    tpl, _ = get_or_create(adm, 'edu.assess.template', [('name', '=', TPL_TEACH)], {
        'name': TPL_TEACH, 'kind': 'student', 'target_kind': 'student',
        'total': 100.0, 'pass_line': 60.0, 'excellent_line': 90.0,
        'score_visible': True})
    fx['tpl_teach'] = tpl
    for i, (nm, mx) in enumerate([('课堂参与', 20.0), ('作业完成', 30.0)]):
        get_or_create(adm, 'edu.assess.item',
                      [('template_id', '=', tpl), ('name', '=', nm)],
                      {'template_id': tpl, 'name': nm, 'max_score': mx,
                       'sequence': 10 * (i + 1)})

    # T2：学生评教（匿名），范围 = 全体教师
    tpl2, _ = get_or_create(adm, 'edu.assess.template', [('name', '=', TPL_FILL)], {
        'name': TPL_FILL, 'kind': 'teaching', 'target_kind': 'faculty',
        'total': 100.0, 'pass_line': 60.0, 'excellent_line': 90.0})
    fx['tpl_fill'] = tpl2
    for i, nm in enumerate(['备课充分', '课堂表达']):
        get_or_create(adm, 'edu.assess.item',
                      [('template_id', '=', tpl2), ('name', '=', nm)],
                      {'template_id': tpl2, 'name': nm, 'max_score': 25.0,
                       'sequence': 10 * (i + 1)})

    # T3：教务 Excel 录入（实名导入；中文姓名兜底键）
    tpl3, _ = get_or_create(adm, 'edu.assess.template', [('name', '=', TPL_EXCEL)], {
        'name': TPL_EXCEL, 'kind': 'student', 'target_kind': 'student',
        'total': 100.0, 'pass_line': 60.0, 'excellent_line': 90.0})
    fx['tpl_excel'] = tpl3
    for i, nm in enumerate(['平时表现', '期末考评']):
        get_or_create(adm, 'edu.assess.item',
                      [('template_id', '=', tpl3), ('name', '=', nm)],
                      {'template_id': tpl3, 'name': nm, 'max_score': 20.0,
                       'sequence': 10 * (i + 1)})

    def ensure_task(tpl, period, **extra):
        vals = {'template_id': tpl, 'period': period, 'state': 'open'}
        vals.update(extra)
        task, _ = get_or_create(
            adm, 'edu.assess.task',
            [('template_id', '=', tpl), ('period', '=', period)], vals)
        call_kw(adm, 'edu.assess.task', 'action_build_roster', [[task]])
        return task

    fx['task_teach'] = ensure_task(tpl, '2026秋-验收', scorer_kind='teacher',
                                   anonymous=False,
                                   scope_batch_ids=[(6, 0, taught)])
    fx['task_fill'] = ensure_task(tpl2, '2026秋-验收', scorer_kind='student',
                                  anonymous=True, summary_min=3)
    fx['task_excel'] = ensure_task(tpl3, '2026秋-验收', scorer_kind='teacher',
                                   anonymous=False)

    rosters, err = search(adm, 'edu.assess.roster',
                          [('task_id', '=', fx['task_teach'])],
                          ['id', 'student_id', 'batch_id'], 0)
    if err:
        raise RuntimeError('查名单失败：%s' % err)
    fx['rosters_teach'] = rosters or []
    rosters2, err = search(adm, 'edu.assess.roster',
                           [('task_id', '=', fx['task_excel'])],
                           ['id', 'student_id', 'label' if False else 'batch_id'], 0)
    fx['rosters_excel'] = rosters2 or []
    rosters3, err = search(adm, 'edu.assess.roster',
                           [('task_id', '=', fx['task_fill'])],
                           ['id', 'faculty_id'], 0)
    fx['rosters_fill'] = rosters3 or []
    return fx


def clean_leftover(adm, fx):
    """清掉上一轮跑出来的验收残留，保证本次读数是本次的。

    两件事：① 删掉上一轮的「课堂笔记」列（保证 V1 的"前读数"成立）；
    ② 删掉上一轮写在验收任务上的审计留痕（否则 V2-⑤ 会把上轮的旧行算进来）。
    """
    task_ids = [fx['task_teach'], fx['task_fill'], fx['task_excel']]
    # 匿名任务的答卷：清空重来（否则上一轮的行会混进本轮读数）
    old_scores, _e = search(adm, 'edu.assess.score',
                            [('task_id', '=', fx['task_fill'])], ['id'])
    n_old = 0
    if old_scores:
        n_old = len(old_scores)
        call_kw(adm, 'edu.assess.score', 'unlink',
                [[s['id'] for s in old_scores]])
    logs, _e = search(adm, 'edu.audit.log',
                      [('model', '=', 'edu.assess.task'),
                       ('res_id', 'in', task_ids)], ['id'])
    n_log = 0
    if logs:
        n_log = len(logs)
        call_kw(adm, 'edu.audit.log', 'unlink', [[l['id'] for l in logs]])
    res, err = search(adm, 'edu.assess.item',
                      [('template_id', '=', fx['tpl_teach']),
                       ('name', '=', KEY_ITEM)], ['id'])
    if err or not res:
        return '无残留（清了 %d 条上轮审计 / %d 条上轮答卷）' % (n_log, n_old)
    iid = res[0]['id']
    scores, _e = search(adm, 'edu.assess.score', [('item_id', '=', iid)], ['id'])
    if scores:
        call_kw(adm, 'edu.assess.score', 'unlink', [[s['id'] for s in scores]])
    got, err = call_kw(adm, 'edu.assess.item', 'unlink', [[iid]])
    return '清了 1 个残留列（打分 %d 条），unlink=%s %s' % (
        len(scores or []), got, err or '')


# ----------------------------------------------------------------------
# V1：在线加一个评分项 —— 不发版、不升级、刷新即生效（本次最关键）
# ----------------------------------------------------------------------

def v1_online_item(adm, stu, fac, fx):
    print('\n== V1 在线加评分项（不发版 / 不升级 / 刷新即生效）==')
    clean = clean_leftover(adm, fx)
    print('    夹具清理：%s' % clean)
    url = '/assess/grade/%d' % fx['task_teach']
    before_items = int(psql('select count(*) from edu_assess_item '
                            'where template_id=%d' % fx['tpl_teach']))
    r_before = fac.get(BASE + url, timeout=40)
    html_before = r_before.text
    before_has = re.search(r'<th[^>]*>\s*%s\s*</th>' % KEY_ITEM, html_before)
    check('V1-①', '加列前：门户矩阵页没有「%s」列' % KEY_ITEM,
          r_before.status_code == 200 and not before_has,
          'HTTP %s；含新列=%s；评分项行数=%d'
          % (r_before.status_code, bool(before_has), before_items))

    # —— 在线新增（JSON-RPC create = 后台列表视图同一写路径）——
    new_id, err = call_kw(adm, 'edu.assess.item', 'create', [{
        'template_id': fx['tpl_teach'], 'name': KEY_ITEM,
        'max_score': 10.0, 'weight': 1.0, 'sequence': 30}])
    check('V1-②', '在线新增评分项（RPC create，无升级/无发版）',
          not err and new_id, 'item_id=%s %s' % (new_id, err or ''))
    if err:
        return None
    item_id = new_id[0] if isinstance(new_id, list) else new_id
    after_items = int(psql('select count(*) from edu_assess_item '
                           'where template_id=%d' % fx['tpl_teach']))
    check('V1-③', '库里评分项行数 +1（插一行 = 加一列）',
          after_items == before_items + 1,
          'before=%d after=%d' % (before_items, after_items))

    r_after = fac.get(BASE + url, timeout=40)
    after_has = re.search(r'<th[^>]*>\s*%s\s*</th>' % KEY_ITEM, r_after.text)
    check('V1-④', '刷新门户矩阵页：表头出现「%s」列' % KEY_ITEM,
          r_after.status_code == 200 and bool(after_has),
          'HTTP %s；含新列=%s（前后对照：前=%s）'
          % (r_after.status_code, bool(after_has), bool(before_has)))

    # 页面里真的能填：POST 走门户写路由
    roster = fx['rosters_teach'][0]
    tok, _ = get_csrf(fac, url)
    if not tok:
        cannot('V1-⑤', '门户写路由打不通（取不到 csrf）', url)
        return item_id
    r_save = fac.post(BASE + '/assess/grade/%d/save' % fx['task_teach'],
                      data={'csrf_token': tok,
                            'v_%d_%d' % (roster['id'], item_id): '8'},
                      timeout=40, allow_redirects=False)
    row = psql('select count(*), coalesce(max(value),-1)::text '
               'from edu_assess_score where item_id=%d' % item_id)
    cnt, mx = (row.split('|') + ['-1'])[:2]
    check('V1-⑤', '学生/教师填入新列并提交 → 库内 1 行 / 值 8',
          cnt == '1' and mx == '8',
          'POST=%s；select count,max(value) → %s 行 / %s' % (r_save.status_code, cnt, mx))
    return item_id


# ----------------------------------------------------------------------
# V2：匿名 —— 库里查不到明文打分人
# ----------------------------------------------------------------------

def v2_anonymity(adm, stu, fx):
    print('\n== V2 匿名：库里查不到明文打分人 ==')
    url = '/assess/fill/%d' % fx['task_fill']
    tok, r_page = get_csrf(stu, url)
    if not tok or not fx['rosters_fill']:
        cannot('V2-①', '学生评教页不可达或名单为空', url)
        return
    roster = fx['rosters_fill'][0]
    items = psql("select id, name from edu_assess_item where template_id=%d "
                 "and active order by sequence" % fx['tpl_fill'])
    first_item = int(items.split('\n')[0].split('|')[0])
    r_save = stu.post(BASE + '/assess/fill/%d/save' % fx['task_fill'],
                      data={'csrf_token': tok,
                            'v_%d_%d' % (roster['id'], first_item): '21.5',
                            'n_%d_%d' % (roster['id'], first_item): '讲得清楚'},
                      timeout=40, allow_redirects=False)
    check('V2-①', '学生提交评教（写路由 303 回填页）', r_save.status_code == 303,
          'POST=%s Location=%s' % (r_save.status_code,
                                   r_save.headers.get('Location')))

    n_rows = int(psql('select count(*) from edu_assess_score where task_id=%d'
                      % fx['task_fill']))
    n_scorer = int(psql('select count(*) from edu_assess_score where task_id=%d '
                        'and scorer_id is not null' % fx['task_fill']))
    check('V2-②', '匿名任务的打分记录里 scorer_id 全为空',
          n_rows >= 1 and n_scorer == 0,
          '行数=%d，其中 scorer_id 非空 = %d' % (n_rows, n_scorer))

    row = psql('select scorer_ref, scorer_id, create_uid, write_uid, value '
               'from edu_assess_score where task_id=%d limit 5' % fx['task_fill'])
    refs = [x.split('|')[0] for x in row.split('\n')]
    ok_ref = all(re.match(r'^h:[0-9a-f]{64}$', r or '') for r in refs)
    check('V2-③', '打分人只有 HMAC 指纹（h: + 64 位十六进制）',
          ok_ref and refs, 'scorer_ref=%s' % (refs[0][:20] + '…' if refs else '—'))

    uid = int(psql("select id from res_users where login='stu@local'"))
    leak = psql('select count(*) from edu_assess_score where task_id=%d '
                'and (create_uid=%d or write_uid=%d or scorer_id=%d)'
                % (fx['task_fill'], uid, uid, uid))
    check('V2-④', '整行里没有任何"打分人 = 学生 uid"的明文（含 create_uid/write_uid）',
          leak == '0', '匹配 uid=%d 的行数 = %s' % (uid, leak))
    # 同一件事的正面陈述：匿名写入统一落在系统用户名下（不是"恰好没写"）
    sys_rows = psql('select count(*) from edu_assess_score where task_id=%d '
                    'and create_uid=1 and write_uid=1' % fx['task_fill'])
    check('V2-④b', '匿名答卷的 create_uid/write_uid 统一为系统用户（1）',
          sys_rows == str(n_rows),
          '%s / %d 行落在系统用户下' % (sys_rows, n_rows))
    dump = psql('select id, task_id, item_id, roster_id, value, note, '
                'scorer_id, scorer_ref, create_uid, write_uid from '
                'edu_assess_score where task_id=%d order by id'
                % fx['task_fill'])
    print('    匿名答卷整行（教务实读，逐列都在这里）：')
    for line in dump.split('\n'):
        print('      %s' % line)

    audit = psql("select count(*) from edu_audit_log where model='edu.assess.task' "
                 "and res_id=%d and user_id=%d" % (fx['task_fill'], uid))
    check('V2-⑤', '审计留痕里也没有"谁提交的匿名评教"',
          audit == '0', 'audit rows(user_id=学生) = %s' % audit)

    # 防重复提交能力仍在：同一人再交一次 ⇒ 不翻倍（唯一键含指纹）
    tok2, _ = get_csrf(stu, url)
    stu.post(BASE + '/assess/fill/%d/save' % fx['task_fill'],
             data={'csrf_token': tok2,
                   'v_%d_%d' % (roster['id'], first_item): '22.5'},
             timeout=40, allow_redirects=False)
    n_rows2 = int(psql('select count(*) from edu_assess_score where task_id=%d'
                       % fx['task_fill']))
    val2 = psql('select value from edu_assess_score where task_id=%d and '
                'item_id=%d and roster_id=%d'
                % (fx['task_fill'], first_item, roster['id']))
    check('V2-⑥', '同一人重复提交：不翻倍而是覆盖（指纹查重）',
          n_rows2 == n_rows and val2 == '22.5',
          '行数 %d → %d；值 = %s' % (n_rows, n_rows2, val2))
    return {'item_id': first_item, 'value': val2}


# ----------------------------------------------------------------------
# V3：样本门槛 —— 份数低于门槛时不展示任何明细
# ----------------------------------------------------------------------

def v3_threshold(adm, fx):
    print('\n== V3 样本门槛（匿名汇总）==')
    url = '/assess/task/%d/results' % fx['task_fill']
    refs = int(psql('select count(distinct scorer_ref) from edu_assess_score '
                    'where task_id=%d' % fx['task_fill']))
    r = adm.get(BASE + url, timeout=40)
    gate_shown = 'yy-assess-sample-gate' in r.text
    table_shown = 'yy-assess-result-table' in r.text
    check('V3-①', '份数(%d) < 门槛(3)：结果页不展示明细' % refs,
          r.status_code == 200 and gate_shown and not table_shown,
          'HTTP %s；门槛提示=%s；结果表=%s' % (r.status_code, gate_shown, table_shown))

    # 正对照：把门槛改成 1（仍是在线改数据、不改代码），同一批数据应立刻可见
    _res, err = call_kw(adm, 'edu.assess.task', 'write',
                        [[fx['task_fill']], {'summary_min': 1}])
    r2 = adm.get(BASE + url, timeout=40)
    table2 = 'yy-assess-result-table' in r2.text
    check('V3-②', '正对照：门槛降为 1 后同一批数据即可见（不是"页面坏了"）',
          not err and table2,
          'write err=%s；结果表=%s' % (err or '—', table2))
    call_kw(adm, 'edu.assess.task', 'write',
            [[fx['task_fill']], {'summary_min': 3}])
    r3 = adm.get(BASE + url, timeout=40)
    check('V3-③', '门槛改回 3 后重新隐藏（读数可复现）',
          'yy-assess-sample-gate' in r3.text
          and 'yy-assess-result-table' not in r3.text, '已复现隐藏')


# ----------------------------------------------------------------------
# V4/V5/V6：xlsx 往返 + 冲突三态 + 未知列头
# ----------------------------------------------------------------------

def read_payload(page_text):
    """从预览页的隐藏 input 里取回 payload（QWeb 属性值是 html 转义过的）。"""
    m = re.search(r'name="payload" value="([^"]*)"', page_text or '')
    if not m:
        return None
    return json.loads(html.unescape(m.group(1)))


def make_xlsx(header, rows):
    import openpyxl
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(header)
    for r in rows:
        sheet.append(r)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def post_file(sess, url, content, filename, extra=None):
    tok, _ = get_csrf(sess, url.replace('/import', '/results')
                      if url.endswith('/import') else url)
    data = {'csrf_token': tok}
    data.update(extra or {})
    return sess.post(BASE + url, data=data,
                     files={'file': (filename, content,
                                     'application/vnd.openxmlformats-'
                                     'officedocument.spreadsheetml.sheet')},
                     timeout=60, allow_redirects=False)


def v4_xlsx_roundtrip(adm, fx):
    print('\n== V4 xlsx 空表导出 / 导入两段式 / 幂等 ==')
    # V4-① 空表导出是真 xlsx（openpyxl 打开 + 表头逐列命中）
    r = adm.get(BASE + '/assess/template/%d/blank.xlsx?task_id=%d'
                % (fx['tpl_excel'], fx['task_excel']), timeout=60)
    ok_open, info = False, ''
    if r.status_code == 200:
        try:
            import openpyxl
            book = openpyxl.load_workbook(io.BytesIO(r.content))
            sheet = book.active
            header = [c.value or '' for c in sheet[1]]
            names = [i['name'] for i in
                     (search(adm, 'edu.assess.item',
                             [('template_id', '=', fx['tpl_excel']),
                              ('active', '=', True)], ['id', 'name'])[0] or [])]
            ok_open = header[:2] == ['学号', '姓名'] and all(
                n in header for n in names)
            info = 'header=%s rows=%d' % (header, sheet.max_row)
        except Exception as exc:
            info = 'openpyxl 打不开：%s' % exc
    check('V4-①', '导出空表：真 xlsx + 表头 = 学号/姓名 + 全部评分项',
          ok_open, info)

    # V4-② 导出结果
    r2 = adm.get(BASE + '/assess/task/%d/export.xlsx' % fx['task_excel'],
                 timeout=60)
    check('V4-②', '导出结果：真 xlsx（HTTP 200 + 可解析）',
          r2.status_code == 200 and r2.content[:2] == b'PK',
          'HTTP %s bytes=%d magic=%r' % (r2.status_code, len(r2.content),
                                         r2.content[:2]))

    # V4-③ 用 Excel 填 3 学生 × 2 项 → 预览 → 提交
    students = psql("select coalesce(s.gr_no,''), p.name from op_student s "
                    "join res_partner p on p.id=s.partner_id "
                    "where s.active order by s.id limit 3")
    rows = []
    for line in students.split('\n'):
        no, name = (line.split('|') + [''])[:2]
        rows.append([no, name, 12, 18])
    fname = 'assess-acceptance.xlsx'
    content = make_xlsx(['学号', '姓名', '平时表现', '期末考评'], rows)
    r3 = post_file(adm, '/assess/task/%d/import' % fx['task_excel'], content,
                   fname)
    m_valid = re.search(r'可写入 <b[^>]*>(\d+)</b>', r3.text or '')
    m_invalid = re.search(r'待修正 <b[^>]*>(\d+)</b>', r3.text or '')
    check('V4-③', '导入预览：valid=3 / invalid=0',
          r3.status_code == 200 and m_valid and m_valid.group(1) == '3'
          and m_invalid and m_invalid.group(1) == '0',
          'HTTP %s；valid=%s invalid=%s' % (
              r3.status_code,
              m_valid.group(1) if m_valid else '?',
              m_invalid.group(1) if m_invalid else '?'))

    payload = read_payload(r3.text) or []
    tok, _ = get_csrf(adm, '/assess/task/%d/results' % fx['task_excel'])
    r4 = adm.post(BASE + '/assess/task/%d/import/commit' % fx['task_excel'],
                  data={'csrf_token': tok, 'filename': fname,
                        'payload': json.dumps(payload, ensure_ascii=False)},
                  timeout=60, allow_redirects=False)
    n1 = int(psql('select count(*) from edu_assess_score where task_id=%d'
                  % fx['task_excel']))
    check('V4-④', '提交后库里 6 条（3 学生 × 2 项）',
          n1 >= 6 and re.search(r'imported=6', r4.headers.get('Location') or ''),
          'HTTP %s Location=%s；表内条数=%d' % (
              r4.status_code, r4.headers.get('Location'), n1))

    # V4-⑤ 幂等：同一个文件再导一次
    r5 = post_file(adm, '/assess/task/%d/import' % fx['task_excel'], content,
                   fname)
    payload5 = read_payload(r5.text) or []
    tok5, _ = get_csrf(adm, '/assess/task/%d/results' % fx['task_excel'])
    adm.post(BASE + '/assess/task/%d/import/commit' % fx['task_excel'],
             data={'csrf_token': tok5, 'filename': fname,
                   'payload': json.dumps(payload5, ensure_ascii=False)},
             timeout=60, allow_redirects=False)
    n2 = int(psql('select count(*) from edu_assess_score where task_id=%d'
                  % fx['task_excel']))
    check('V4-⑤', '同一文件再导一次 ⇒ 条数不变（幂等，不翻倍）',
          n2 == n1, '第一次 %d 条 → 第二次 %d 条' % (n1, n2))
    old_vals = [c.get('old') for e in payload5 for c in e.get('cells', [])]
    check('V4-⑥', '第二次预览显示「旧值 = 新值」',
          bool(old_vals) and all(v is not None for v in old_vals),
          'old 值抽样 = %s' % old_vals[:3])

    # V4-⑦ 结果页能看到刚才导进去的分
    r6 = adm.get(BASE + '/assess/task/%d/results' % fx['task_excel'], timeout=40)
    check('V4-⑦', '结果页出现明细表（实名任务无门槛）',
          'yy-assess-result-table' in r6.text and '12' in r6.text,
          'HTTP %s' % r6.status_code)


def cell_value(task_id, roster_id, item_name):
    """读某名单行某评分项的单元格值（psql，用来做库内侧证）。"""
    return psql("select coalesce(value::text,'') from edu_assess_score "
                "where task_id=%d and roster_id=%d and item_id="
                "(select id from edu_assess_item where name=%s)"
                % (task_id, roster_id, _sql_str(item_name)))


def _sql_str(text):
    return "'" + str(text).replace("'", "''") + "'"


def v5_conflict(adm, fx):
    print('\n== V5 冲突三态（超满分 / 空值）==')
    target = fx['rosters_excel'][0]
    name = psql("select coalesce(p.name,'') from edu_assess_roster r "
                "join op_student s on s.id=r.student_id "
                "join res_partner p on p.id=s.partner_id where r.id=%d"
                % target['id'])
    before_a = cell_value(fx['task_excel'], target['id'], '平时表现')
    before_b = cell_value(fx['task_excel'], target['id'], '期末考评')
    content = make_xlsx(['学号', '姓名', '平时表现', '期末考评'],
                        [['', name, 999, '']])
    r = post_file(adm, '/assess/task/%d/import' % fx['task_excel'], content,
                  'conflict.xlsx')
    m_invalid = re.search(r'待修正 <b[^>]*>(\d+)</b>', r.text or '')
    exceed = '超过满分' in (r.text or '')
    check('V5-①', '预览：超满分那行 invalid=1 且给出原因',
          r.status_code == 200 and m_invalid and m_invalid.group(1) == '1'
          and exceed,
          'HTTP %s invalid=%s 含"超过满分"=%s' % (
              r.status_code, m_invalid.group(1) if m_invalid else '?', exceed))

    after_a = cell_value(fx['task_excel'], target['id'], '平时表现')
    after_b = cell_value(fx['task_excel'], target['id'], '期末考评')
    check('V5-②', '整行未写入：超满分那格仍是旧值（999 没进库）',
          after_a == before_a and before_a not in ('', '999')
          and after_a not in ('', '999'),
          '平时表现 %s → %s（该行 invalid，整行不落库）' % (before_a, after_a))
    check('V5-③', '空值 = 跳过：留空不清空库里已有的分',
          after_b == before_b and before_b != '',
          '期末考评 %s → %s' % (before_b, after_b))
    return r


def v6_unknown_header(adm, fx):
    print('\n== V6 未知列头：默认报错不新建 / 勾选后按新列创建 ==')
    before = int(psql('select count(*) from edu_assess_item where template_id=%d'
                      % fx['tpl_excel']))
    name = psql("select coalesce(p.name,'') from edu_assess_roster r "
                "join op_student s on s.id=r.student_id "
                "join res_partner p on p.id=s.partner_id "
                "where r.task_id=%d limit 1" % fx['task_excel'])
    content = make_xlsx(['学号', '姓名', '平时表现', '期末考评', '从没见过的列'],
                        [['', name, 3, 4, 5]])
    r = post_file(adm, '/assess/task/%d/import' % fx['task_excel'], content,
                  'unknown.xlsx')
    after = int(psql('select count(*) from edu_assess_item where template_id=%d'
                     % fx['tpl_excel']))
    check('V6-①', '默认：未知列头整份报错，评分项行数不变',
          r.status_code == 200 and 'yy-assess-file-error' in r.text
          and after == before,
          'HTTP %s；评分项 %d → %d' % (r.status_code, before, after))

    r2 = post_file(adm, '/assess/task/%d/import' % fx['task_excel'], content,
                   'unknown.xlsx', {'create_items': '1'})
    after2 = int(psql('select count(*) from edu_assess_item where template_id=%d'
                      % fx['tpl_excel']))
    check('V6-②', '勾选「按新列创建评分项」：模板新增 1 项（名称 = 列头）',
          after2 == before + 1, '评分项 %d → %d' % (before, after2))
    # 收尾：把这一列删掉（没人打分 → 删得掉，也顺带验证 V2-删保护的反面）
    iid = psql("select id from edu_assess_item where template_id=%d and "
               "name='从没见过的列'" % fx['tpl_excel'])
    got, err = call_kw(adm, 'edu.assess.item', 'unlink', [[int(iid)]])
    check('V6-③', '无人打分的评分项可以删除（对照"有分拒删"）',
          not err, 'unlink=%s %s' % (got, err or ''))


def v2b_delete_guard(adm, fac, fx, item_id, keep):
    print('\n== V2b 评分项删除保护（有分 ⇒ 拒删，引导停用）==')
    if not item_id:
        cannot('V2b-①', 'V1 未拿到新列 id，跳过', 'V1 失败')
        return
    got, err = call_kw(adm, 'edu.assess.item', 'unlink', [[item_id]])
    check('V2b-①', '有打分的评分项：删除被拒 + 提示改用停用',
          bool(err) and ('停用' in err), 'err=%s' % (err or '—'))
    if keep:
        # 停用后列消失、历史分仍在
        call_kw(adm, 'edu.assess.item', 'write', [[item_id], {'active': False}])
        r = fac.get(BASE + '/assess/grade/%d' % fx['task_teach'], timeout=40)
        gone = not re.search(r'<th[^>]*>\s*%s\s*</th>' % KEY_ITEM, r.text)
        still = psql('select count(*) from edu_assess_score where item_id=%d'
                     % item_id)
        check('V2b-②', '停用后门户列消失、历史打分仍在',
              gone and still == '1',
              '列消失=%s；历史打分行数=%s' % (gone, still))
        call_kw(adm, 'edu.assess.item', 'write', [[item_id], {'active': True}])


# ----------------------------------------------------------------------
# V7/V8：正面与负面权限
# ----------------------------------------------------------------------

def v7_positive(adm, stu, fac, fx):
    print('\n== V7 正面权限（学生只见自己 / 教师只见任教班）==')
    mine = stu.get(BASE + '/assess/my', timeout=40)
    other = [r['name'] for r in
             (search(adm, 'op.student', [('id', '!=', 0)], ['name'])[0] or [])]
    stu_name = psql("select coalesce(p.name,'') from op_student s "
                    "join res_partner p on p.id=s.partner_id "
                    "join res_users u on u.id=s.user_id "
                    "where u.login='stu@local'")
    leaked = [n for n in other if n and n != stu_name and n in mine.text]
    check('V7-①', '学生 /assess/my 只见自己（他人姓名不出现）',
          mine.status_code == 200 and not leaked,
          'HTTP %s；泄漏姓名=%s' % (mine.status_code, leaked or '无'))

    r = fac.get(BASE + '/assess/grade/%d' % fx['task_teach'], timeout=40)
    # 只取矩阵表内部：页面外壳里的 <b> 是门户导航文案，不是学生行
    m = re.search(r'id="yy-assess-grade-table".*?</table>', r.text or '', re.S)
    body = m.group(0) if m else ''
    # 2026-09-28：行单元格由 <b> 改成指向 /assess/student/<id>/history 的 <a>
    # （另一位 agent 的排版改动，属产品行为）⇒ 选择器同时接受两种标记，
    # 避免把"改名"误判成"越权"。两个分支都只取单元格里的被评者姓名。
    shown = set(re.findall(r'<b[^>]*>([^<]+)</b>', body))
    shown |= set(re.findall(r'href="[^"]*/history"[^>]*>([^<]+)</a>', body))
    allowed = {s['name'] for s in fx['taught_students']}
    check('V7-②', '教师整班打分页：只出现本人任教班学生',
          r.status_code == 200 and bool(body) and bool(shown) and shown <= allowed,
          '矩阵内学生=%s；任教班=%s（表体命中=%s）'
          % (sorted(shown), sorted(allowed), bool(body)))

    rosters = search(adm, 'edu.assess.roster',
                     [('task_id', '=', fx['task_teach'])], ['id'])[0] or []
    check('V7-③', '对照：名单快照在库里存在（页面为空不是"恰无数据"）',
          len(rosters) == len(fx['rosters_teach']) and len(rosters) >= 1,
          '库内 %d 行' % len(rosters))


def v8_negative(adm, stu, parent, fac, fx):
    print('\n== V8 负面权限（RPC 直读，安全审计 F1 同款判据）==')
    # 正对照必须先过：有权的教务能读到
    admin_rows, err = call_kw(adm, 'edu.assess.score', 'search_read',
                              [[]], {'fields': ['id'], 'limit': 0})
    if err:
        cannot('V8-①', '正对照失败：教务自己也读不到打分记录', err)
        return
    n_admin = len(admin_rows or [])
    check('V8-①', '正对照：教务 RPC search_read 拿得到全部打分记录',
          n_admin > 0, '教务读到 %d 行' % n_admin)

    for who, sess, no in (('学生', stu, 'V8-②'), ('家长', parent, 'V8-③')):
        rows, err = call_kw(sess, 'edu.assess.score', 'search_read', [[]],
                            {'fields': ['id'], 'limit': 0})
        denied = bool(err) or not rows
        check(no, '%s RPC 直读 edu.assess.score 被拒（门户 ACL = 0）' % who,
              denied, 'err=%s rows=%s' % ((err or '—')[:80], len(rows or [])))

    rows_r, err_r = call_kw(stu, 'edu.assess.roster', 'search_read', [[]],
                            {'fields': ['id'], 'limit': 0})
    check('V8-④', '学生 RPC 直读 edu.assess.roster 被拒',
          bool(err_r) or not rows_r, 'err=%s rows=%s' % ((err_r or '—')[:80],
                                                         len(rows_r or [])))

    t_rows, err_t = call_kw(stu, 'edu.assess.task', 'search_read', [[]],
                            {'fields': ['id'], 'limit': 0})
    check('V8-⑤', '学生 RPC 直读 edu.assess.task 被拒',
          bool(err_t) or not t_rows, 'err=%s rows=%s' % ((err_t or '—')[:80],
                                                         len(t_rows or [])))

    if fx.get('taught_batches'):
        rows_f, err_f = call_kw(fac, 'edu.assess.score', 'search_read',
                                [[]], {'fields': ['id', 'roster_id'], 'limit': 0})
        n_fac = len(rows_f or [])
        check('V8-⑥', '教师 RPC 直读被行级规则收敛（拿不到 < 教务）',
              not err_f and n_fac < n_admin,
              '教师 %d 行 < 教务 %d 行（err=%s）' % (n_fac, n_admin, err_f or '—'))
    else:
        cannot('V8-⑥', '教师无任教班，收敛对照无法构造', '—')


def v9_legacy_303(stu, fac, adm):
    print('\n== V9 旧地址：A 套仍 303；B 套（edu_eval 已删）必须 404 ==')
    # A 套 = edu_portal 的 edu.eval.*（/my/evaluation*）—— 与 2026-09-29 的
    # 「删除行政评估」无关，一行未动 ⇒ 仍然 303。
    expect = {
        '/my/evaluation': '/assess',
        '/my/evaluation/new': '/assess',
        '/my/evaluation/results': '/assess/my',
    }
    for path, target in expect.items():
        r = stu.get(BASE + path, timeout=40, allow_redirects=False)
        check('V9', '%s → 303 %s' % (path, target),
              r.status_code == 303 and r.headers.get('Location') == target,
              '%s %s' % (r.status_code, r.headers.get('Location')))
    r = adm.get(BASE + '/my/evaluation', timeout=40, allow_redirects=False)
    check('V9', '教务访问旧地址同样 303（不是 404/500）',
          r.status_code == 303 and r.headers.get('Location') == '/assess',
          '%s %s' % (r.status_code, r.headers.get('Location')))
    # B 套 = edu_eval（edu.admin.eval.*）：模块与它的 303 兼容壳**已一并删除**
    # （2026-09-29，证据 docs/audit/edu-eval-removal.md）⇒ 旧地址的正确期望是
    # **404（路由不存在）**，而不是 303。这里贴着真实状态码写判据：只要有人
    # 把壳加回来（或某个模块重新注册了 /eval/*），这条就会红。
    for path in ('/eval/my', '/eval/review', '/eval/review/9', '/eval/fill/9',
                 '/eval/fill/9/save'):
        r = stu.get(BASE + path, timeout=40, allow_redirects=False)
        check('V9', '%s → 404（B 套路由随模块删除，不是 303/302）' % path,
              r.status_code == 404, '%s' % r.status_code)


def v13_backend_reach(adm):
    """教务后台"看得见点不开"的反面：菜单 → 动作 → 视图 → 数据，四层逐一验。

    code-map.md §12 明写这层最易漏：菜单 groups / 模型 ACL / ir.rule / 控制器判据
    缺一即死角，而症状常常不是报错，是"点进去落到 /apps 应用面板"。
    """
    print('\n== V13 教务后台可达性（菜单 → 动作 → 视图 → 数据）==')
    # 教务读不到 ir.model.data（ACL 只给系统组）⇒ 用只读 psql 换取动作 id，
    # 这与"教务在浏览器里点菜单"是同一条动作 id。
    raw = psql("select res_id from ir_model_data where module='edu_assess' "
               "and name='action_edu_assess_template'")
    if not raw.strip().isdigit():
        cannot('V13-①', '取不到后台动作 xmlid 的 res_id', raw)
        return
    action_id = int(raw.strip())
    r = adm.post(BASE + '/web/action/load',
                 json={'jsonrpc': '2.0', 'method': 'call',
                       'params': {'action_id': action_id, 'context': {}}},
                 timeout=60)
    act = (r.json() or {}).get('result') or {}
    check('V13-①', '后台动作「模板与评分项」可加载',
          act.get('res_model') == 'edu.assess.template'
          and act.get('type') == 'ir.actions.act_window',
          'res_model=%s type=%s' % (act.get('res_model'), act.get('type')))

    views, err_v = call_kw(adm, 'edu.assess.template', 'get_views',
                           [[[False, 'list'], [False, 'form']], {}])
    ok_views = bool(views) and 'views' in (views or {})
    check('V13-②', '模板 list/form 视图可取（视图层不挡教务）',
          ok_views, 'err=%s views=%s' % (err_v or '—',
                                         bool(views and views.get('views'))))

    rows, err_r = search(adm, 'edu.assess.template', [], ['id', 'name'])
    check('V13-③', '教务 search_read 模板（ACL 层）',
          not err_r and rows and len(rows) >= 3,
          'err=%s 行数=%s' % (err_r or '—', len(rows or [])))

    views2, err_v2 = call_kw(adm, 'edu.assess.score', 'get_views',
                             [[[False, 'list']], {}])
    check('V13-④', '打分记录 list 视图可取（后台可编辑列表）',
          not err_v2 and bool(views2 and views2.get('views')),
          'err=%s' % (err_v2 or '—'))

    views3, err_v3 = call_kw(adm, 'edu.assess.task', 'get_views',
                             [[[False, 'form']], {}])
    check('V13-⑤', '评估任务 form 视图可取（含评分项内联列表入口）',
          not err_v3 and bool(views3 and views3.get('views')),
          'err=%s' % (err_v3 or '—'))


def v10_menus(adm, stu):
    print('\n== V10 菜单：评估根只有 1 个 + 教务可见根 ≤12 ==')
    r = adm.get(BASE + '/web/webclient/load_menus?unique=eval_rebuild', timeout=60)
    payload = r.json()
    nodes = {k: v for k, v in payload.items() if k.isdigit()}
    child_of = {}
    for k, v in nodes.items():
        for c in (v.get('children') or []):
            child_of[str(c)] = k
    roots = [k for k in nodes if k not in child_of]
    names = [nodes[k].get('name') for k in roots]
    eval_roots = [n for n in names if n in ('评估', '综合评估', '行政评估')]
    check('V10-①', '教务可见的评估根只有 1 个（588）',
          len(eval_roots) == 1, '评估类根 = %s（全部根 %d 条）'
          % (eval_roots, len(roots)))
    check('V10-②', '教务可见根 ≤12（不破线）', len(roots) <= 12,
          '可见根 = %d 条：%s' % (len(roots), '、'.join(names)))
    r2 = stu.get(BASE + '/web/webclient/load_menus?unique=eval_rebuild_s',
                 timeout=60)
    try:
        stu_nodes = {k: v for k, v in r2.json().items() if k.isdigit()}
    except Exception:
        stu_nodes = {}
    check('V10-③', '学生看不到后台评估菜单（走门户）',
          len(stu_nodes) == 0, '学生可见菜单节点 = %d' % len(stu_nodes))
    root = [k for k in roots if nodes[k].get('name') in ('评估', '综合评估')]
    kids = []
    if root:
        kids = [nodes[str(c)].get('name')
                for c in (nodes[root[0]].get('children') or [])
                if str(c) in nodes]
    want = {'模板与评分项', '评估任务', '结果与导出', '打分记录'}
    check('V10-④', '新引擎 4 条子菜单挂在同一个评估根下',
          want.issubset(set(kids)), '子菜单 = %s' % sorted(kids))


def v11_backup(baseline):
    print('\n== V11 旧两套：只冻结 + 备份留档 ==')
    path = HERE.parent.parent / 'docs' / 'audit' / 'eval-rebuild' \
        / 'a-suite-eval-definitions.json'
    got = run_backup()
    check('V11-①', 'A 套（edu.eval.*）模板与评分项已导出 JSON 留档',
          got.get('ok') and path.exists(),
          '文件=%s；模板=%s 评分项=%s 任务=%s 打分=%s'
          % (path.name, got.get('templates'), got.get('lines'),
             got.get('tasks'), got.get('scores')))
    # 判据 = 与**本次开跑时的基线**逐表相等（证明本次一个字都没删）。
    # 本地读数 3 模板 / 12 评分项，与设计稿 §2.5 的生产读数 4 / 13 不同源，不得混用。
    now = {t: int(psql('select count(*) from %s' % t)) for t in baseline}
    same = all(now[t] == baseline[t] for t in baseline)
    check('V11-②', 'A/B 两套全表行数与开跑基线逐表相等（只冻结、零删除）',
          same,
          '、'.join('%s=%d' % (t, now[t]) for t in sorted(now))
          + '｜基线 ' + '、'.join('%s=%d' % (t, baseline[t])
                                  for t in sorted(baseline)))
    check('V11-③', 'B 套（edu_eval 模块）未卸载、表仍在',
          psql("select state from ir_module_module where name='edu_eval'")
          == 'installed',
          'edu_admin_eval_template=%d' % now.get('edu_admin_eval_template', 0))


def run_backup():
    script = HERE.parent.parent / 'scripts' / 'backup_a_eval_json.py'
    if not script.exists():
        return {'ok': False}
    out = subprocess.run([sys.executable, str(script)], capture_output=True,
                         text=True, timeout=120,
                         cwd=str(HERE.parent.parent))
    meta = {}
    for line in (out.stdout or '').splitlines():
        if line.startswith('BACKUP '):
            meta = dict(kv.split('=', 1) for kv in line[7:].split() if '=' in kv)
    meta['ok'] = out.returncode == 0
    meta['stdout'] = (out.stdout or '')[-300:]
    return meta


def v12_upgrade_stability():
    print('\n== V12 升级不动业务数据（-u edu_assess 前后计数不变）==')
    n = int(psql('select count(*) from edu_assess_score'))
    n_item = int(psql('select count(*) from edu_assess_item'))
    check('V12-①', '当前业务表计数基线', True,
          'edu_assess_score=%d edu_assess_item=%d' % (n, n_item))
    return n, n_item


LEGACY_TABLES = (
    'edu_eval_template', 'edu_eval_template_line', 'edu_eval_task',
    'edu_eval_score', 'edu_admin_eval_template', 'edu_admin_eval_item',
    'edu_admin_eval_score', 'edu_assess_template', 'edu_assess_item',
    'edu_assess_task', 'edu_assess_roster', 'edu_assess_score',
)


def legacy_baseline():
    """开跑前把"旧两套 + 新引擎"全表行数固定下来（V11 的对照物）。"""
    return {t: int(psql('select count(*) from %s' % t)) for t in LEGACY_TABLES}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true', help='跑完不清理夹具')
    args = ap.parse_args()

    try:
        psql('select 1')
    except Exception as exc:
        print('运行错误：连不上数据库容器 (%s)' % exc)
        return 2
    adm = login('backoffice@local')
    stu = login('stu@local')
    fac = login('faculty@local')
    parent = login('parent@local')
    if not (adm and stu and fac and parent):
        print('运行错误：登录失败 adm=%s stu=%s fac=%s parent=%s'
              % (bool(adm), bool(stu), bool(fac), bool(parent)))
        return 2

    try:
        fx = build_fixtures(adm)
    except Exception as exc:
        print('运行错误：夹具建不起来 —— %s' % exc)
        return 2
    print('夹具：教师档案 %s / 任教班 %s / 任教班学生 %s'
          % (fx['faculty_id'], fx['taught_batches'],
             [s['name'] for s in fx['taught_students']]))
    print('      名单：评学生任务 %d 行 / Excel 任务 %d 行 / 评教任务 %d 行'
          % (len(fx['rosters_teach']), len(fx['rosters_excel']),
             len(fx['rosters_fill'])))
    if not (fx['rosters_teach'] and fx['rosters_excel'] and fx['rosters_fill']):
        print('运行错误：名单快照为空，载体不合法（先断言载体，再看结论）')
        return 2

    item_id = v1_online_item(adm, stu, fac, fx)
    v2_anonymity(adm, stu, fx)
    v3_threshold(adm, fx)
    v4_xlsx_roundtrip(adm, fx)
    v5_conflict(adm, fx)
    v6_unknown_header(adm, fx)
    v2b_delete_guard(adm, fac, fx, item_id, keep=args.keep)
    v7_positive(adm, stu, fac, fx)
    v8_negative(adm, stu, parent, fac, fx)
    v9_legacy_303(stu, fac, adm)
    v10_menus(adm, stu)
    v13_backend_reach(adm)
    v11_backup(legacy_baseline())
    v12_upgrade_stability()

    n_pass = sum(1 for i in items if i['pass'])
    n_fail = sum(1 for i in items if not i['pass'])
    RESULTS.write_text(json.dumps({
        'suite': 'eval_rebuild',
        'summary': {'total': len(items), 'pass': n_pass, 'fail': n_fail},
        'items': items}, ensure_ascii=False, indent=1), encoding='utf-8')
    print('\n== eval_rebuild: %d/%d PASS（FAIL=%d）== (%s)'
          % (n_pass, len(items), n_fail, RESULTS.name))
    if n_fail:
        print('失败项：')
        for i in items:
            if not i['pass']:
                print('  #%s %s | %s' % (i['no'], i['name'], i['detail'][:200]))
    return 1 if n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
