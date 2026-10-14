#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「评估任务生命周期」门户化 —— 端到端验收（正向闭环 + 反向守卫 + 控制组 + 越权残留）。

## 为什么有这个脚本

2026-09-28 已查实的根因链：门户**已经有**评估的填表/打分/看结果/导出，**唯独
「评估任务」本身（新建/发布/排名单/结束）只能在 Odoo 后台做**；而用户极度厌恶后台
⇒ 任务建了、发布了，**没人去后台把它结束**。实测本地库：3 个任务全部 open、
closed = 0 ⇒ /assess/my 的「我收到的评估结果」**永远是空的** ⇒ 学生看不到任何结果。

本脚本要证死的**正是那一环**，而且不是"看着对"：

  A 前置事实（可复跑）
      A1 库里 closed 任务数 / A2 学生端 /assess/my 的空态读数 / A3 /assess 上的门户入口
  B 正向生命周期（**每步都有 SQL 前后对照**）
      B1 门户建任务（POST /assess/tasks/save）→ draft 落库
      B2 门户发布（POST /state action=open）→ state=open + 名单快照从 0 到 N
      B3 名单管理：手工添加一行 → 行数 +1 → 再移除 → 回到原值（逐条增删真落库）
      B4 教师打分（既有门户路由 /assess/grade/<id>/save）→ 打分落库、名单行转"已评"
      B5 门户结束（POST /state action=close）→ state=closed 落库
      B6 审计留痕（edu_audit_log 里发布/结束两条，含未评人数）
  C 闭环（**本任务的症状**：学生端从空变有）
      C1 结束前 /assess/my 不含本次任务；结束后**必须**出现（两次页面读数逐字留档）
      C2 页面上出现的分数 == SQL 里该行的打分值（不是"页面有了点什么"就通过）
      C3 因果对照：重新打开 → 学生端又变空；再次结束 → 又出现
         （**证明"结束"这一步是因果，不是巧合**）
  D 守卫（反向：拒绝 + 零副作用）
      D1 有未评行时**不带确认**结束 → 被拒且 state 不变（注入①时此条必须变红）
      D2 结束后的名单**冻结**：生成/添加/删除全部被拒、行数不变
      D3 状态机不跳级：已结束再结束 / 草稿直接结束 → 被拒
      D4 越权跨任务删除：拿别任务的名单行 id 来删 → 被拒且不落库
      D5 换模板护栏：已有名单的任务改模板 → 被拒且库内模板不变
  E 越权（3 身份 × 全部 9 条新路由）
      E1 4 条 GET × 学生/教师/家长 = 12 探 → 全部 303 /my/home
      E2 5 条 POST × 学生/教师/家长 = 15 探（**带各自会话的合法 csrf**，不是拿 403 糊）
         → 全部 303 /my/home
      E3 **越权写入残留 0**：探完逐项 SQL 快照相等（任务数/名单数/打分条数/目标任务状态）
      E4 未登录 → 303 到 /web/login（auth='user' 兜底）
  F 控制组（断言不是恒真/恒假）
      F1 系统组（admin）访问同一批页面 → 200（"200"可达）
      F2 学生会话访问他自己该看到的页 → 200（"303"不是处处 303）
      F3 不存在的任务 id → 303 带错误（"200"断言在坏路径上会失败 ⇒ 非恒真）
      F4 未登记路由 /assess/tasks 之外的 404 对照（不把 404 当权限）

判据纪律（照抄同模块 tests/smoke/assess_template_portal.py 的纪律）：
  · 303 一律 allow_redirects=False + Location 精确匹配，不靠"最终 200"糊过去；
  · 每条负向断言都配正对照；夹具自带清理（同名前缀先清后建，跑完保留可复跑）；
  · 只走 HTTP + 只读 SQL，不升级、不重启、不动别人的模型文件。

用法：
    python3 tests/smoke/assess_task_portal.py                 # 全量（建夹具 + 保留）
    python3 tests/smoke/assess_task_portal.py --only d        # 只跑 D 段（注入时用）
    python3 tests/smoke/assess_task_portal.py --only e        # 只跑 E 段（注入时用）
    python3 tests/smoke/assess_task_portal.py --purge         # 只清夹具（跑完再清）
退出码：0=全绿；1=有断言失败；2=运行错误（服务不可达 / 登不上）。
结果落盘：tests/smoke/assess_task_portal_results.json
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
RESULTS = HERE / 'assess_task_portal_results.json'
PASSWORD = 'demo123'

#: 【冒烟】前缀：夹具用完可整批清掉（脚本每次开跑先清同名夹具，跑完默认保留便于复看）
MARK = '\u3010\u5192\u70df\u3011'
PERIOD = MARK + '门户生命周期验收'
NOTES = MARK + '本夹具由 tests/smoke/assess_task_portal.py 建，跑完可用 --purge 清'
STUDENT_LOGIN = 'stu@local'
STUDENT_GR_NO = 'TEST-2026-001'

LIST_PATH = '/assess/tasks'
NEW_PATH = '/assess/tasks/new'
SAVE_PATH = '/assess/tasks/save'

GET_ROUTES = ('', '/new')                       # 补成 /assess/tasks...
DYN_GET = ('', '/roster')
POST_ACTIONS = ('state', 'roster/build', 'roster/add', 'roster/delete')

OK, FAIL, SKIP = 'PASS', 'FAIL', 'SKIP'
rows = []
facts = {}


def check(no, name, cond, detail=''):
    verdict = OK if cond else FAIL
    rows.append({'no': no, 'name': name, 'pass': bool(cond),
                 'detail': str(detail)[:1200]})
    print('  %-4s #%-6s %-56s %s' % (verdict, no, name, str(detail)[:210]))
    return bool(cond)


def note(no, name, detail=''):
    """记录事实（不判红绿）—— 前置读数、前后对照这类"证据"，不是断言。"""
    rows.append({'no': no, 'name': name, 'pass': True, 'info': True,
                 'detail': str(detail)[:1200]})
    print('  INFO #%-6s %-56s %s' % (no, name, str(detail)[:210]))


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


def csrf_of(sess, path):
    """从**该身份自己能看**的页面取 csrf（拿不到就没有资格谈"越权写入"）。"""
    r = sess.get(BASE + path, timeout=40, allow_redirects=True)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    return (m.group(1) if m else None), r


def call_kw(sess, model, method, args=None, kwargs=None):
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


def loc(r):
    return r.headers.get('Location') or ''


# ----------------------------------------------------------------------
# 夹具：清 → 建 → 发布 → 打分 → 留一个未评行
# ----------------------------------------------------------------------

def purge_fixtures():
    """清掉本脚本此前留下的夹具（含注入实验里被越权建出来的那些）。

    顺序：打分 → 名单 → 任务 → 评分项（叶子先、分组后）→ 模板。
    只清**本脚本自己的**夹具：任务按 period/notes 的【冒烟】标记，模板按名字里的标记。
    走 SQL 直删是刻意的：夹具清理不该被"有分拒删"的 ORM 护栏卡住（那是给产品用的）。
    """
    out = psql("SELECT id FROM edu_assess_task WHERE period = '%s' OR notes LIKE '%%%s%%'"
               % (PERIOD, MARK))
    ids = [int(x) for x in out.splitlines() if x.strip()]
    if ids:
        joined = ','.join(map(str, ids))
        psql('DELETE FROM edu_assess_score WHERE task_id IN (%s)' % joined)
        psql('DELETE FROM edu_assess_roster WHERE task_id IN (%s)' % joined)
        psql('DELETE FROM edu_assess_task WHERE id IN (%s)' % joined)
    tpls = [int(x) for x in psql(
        "SELECT id FROM edu_assess_template WHERE name LIKE '%%%s%%'" % MARK
    ).splitlines() if x.strip()]
    if tpls:
        joined = ','.join(map(str, tpls))
        psql("DELETE FROM edu_assess_item WHERE template_id IN (%s) "
             "AND item_kind = 'leaf'" % joined)
        psql('DELETE FROM edu_assess_item WHERE template_id IN (%s)' % joined)
        psql('DELETE FROM edu_assess_template WHERE id IN (%s)' % joined)
    return ids, tpls


def pick_template():
    """挑一个"学生被评 + 结果对被评者可见 + 启用"的模板（优先既有，找不到才建）。"""
    out = psql("SELECT id, name FROM edu_assess_template WHERE target_kind = 'student' "
               "AND score_visible AND state = 'active' AND active "
               "ORDER BY id LIMIT 1")
    if out:
        tid, name = out.split('|')
        return int(tid), name, False
    return None, None, False


def pick_batch_of_student(gr_no):
    out = psql("SELECT l.batch_id FROM op_student s "
               "JOIN op_student_course l ON l.student_id = s.id "
               "WHERE s.gr_no = '%s' AND l.batch_id IS NOT NULL "
               "ORDER BY l.id LIMIT 1" % gr_no)
    return int(out) if out else None


def pick_extra_student(exclude_ids):
    """挑一个"不在本任务名单里"的学生：优先有学号的，其次**唯一**的姓名。

    本地库学生很少（6 个、其中只有 1 个带学号）⇒ 不能写成"再找一个第三个人"，
    那样夹具会直接建不起来（假红）。
    """
    rows = psql("SELECT s.id, coalesce(nullif(trim(s.gr_no), ''), ''), "
                "coalesce(p.name, '') FROM op_student s "
                "JOIN res_partner p ON p.id = s.partner_id WHERE s.active")
    cands = []
    for line in rows.splitlines():
        parts = (line.split('|') + ['', ''])[:3]
        sid, gr, name = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not sid or int(sid) in exclude_ids:
            continue
        cands.append((int(sid), gr or name, bool(gr)))
    for sid, token, _has_gr in sorted(cands, key=lambda x: (not x[2], x[0])):
        if token:
            return sid, token
    return None, None


def task_state(tid):
    return psql('SELECT state FROM edu_assess_task WHERE id = %d' % tid)


def roster_count(tid):
    return int(psql('SELECT count(*) FROM edu_assess_roster WHERE task_id = %d' % tid))


def snapshot(tid):
    """越权残留的对照快照（逐项都是可再算的标量）。"""
    return {
        'tasks': int(psql('SELECT count(*) FROM edu_assess_task')),
        'rosters': int(psql('SELECT count(*) FROM edu_assess_roster')),
        'scores': int(psql('SELECT count(*) FROM edu_assess_score')),
        'state': task_state(tid),
        'task_roster': roster_count(tid),
        'audit': int(psql('SELECT count(*) FROM edu_audit_log')),
    }


def build_fixture(bo, fac, stu):
    """建一个走完整生命周期的任务；返回 (tid, 学生行 id, 未评行 id, 模板 id, 评分项)。"""
    purged = purge_fixtures()
    if purged[0] or purged[1]:
        note('B0', '清掉旧夹具', '已删任务 %s ｜ 模板 %s' % (purged[0], purged[1]))

    tpl_id, tpl_name, _ = pick_template()
    if not tpl_id:
        check('B0.1', '找到"学生被评 + 结果可见"的启用模板', False, '库内没有可用模板')
        return None
    note('B0.1', '夹具模板', 'id=%d name=%s' % (tpl_id, tpl_name))

    batch_id = pick_batch_of_student(STUDENT_GR_NO)
    sid = int(psql("SELECT id FROM op_student WHERE gr_no = '%s'" % STUDENT_GR_NO))
    note('B0.2', '学生身份（被评者）', 'op.student id=%d batch=%s' % (sid, batch_id))

    token, _r = csrf_of(bo, NEW_PATH)
    if not check('B1.0', '新建页拿到 csrf_token', bool(token), 'token 存在=%s' % bool(token)):
        return None

    before_draft = int(psql("SELECT count(*) FROM edu_assess_task WHERE period = '%s'" % PERIOD))
    r = bo.post(BASE + SAVE_PATH, data={
        'csrf_token': token, 'task_id': '', 'template_id': str(tpl_id),
        'period': PERIOD, 'date_begin': '', 'date_due': '2026-12-31',
        'scope_batch_ids': [str(batch_id)] if batch_id else [],
        'scorer_kind': 'teacher', 'objective_scorer_kind': '',
        'subjective_scorer_kind': '', 'summary_min': '3',
        'anonymous': '', 'active': '1', 'notes': NOTES,
    }, timeout=40, allow_redirects=False)
    after_draft = int(psql("SELECT count(*) FROM edu_assess_task WHERE period = '%s'" % PERIOD))
    m = re.match(r'^/assess/tasks/(\d+)(?:\?|$)', loc(r))
    tid = int(m.group(1)) if m else None
    check('B1.1', '门户建任务 → 303 回任务页且库里出现 draft 行',
          r.status_code == 303 and bool(tid) and after_draft == before_draft + 1
          and task_state(tid) == 'draft',
          'HTTP %s Location=%s ｜ 库内行数 %d→%d ｜ state=%s'
          % (r.status_code, loc(r), before_draft, after_draft,
             task_state(tid) if tid else '（无）'))
    if not tid:
        return None
    scope = psql('SELECT count(*) FROM edu_assess_task_batch_rel WHERE task_id = %d' % tid)
    check('B1.2', '多选的"参与班级"真的写进了 m2m 关系表（**不是只取第一个**）',
          scope == ('1' if batch_id else '0'),
          '关系行数=%s（期望 %s）—— 路由 **post 拿不到多选，必须走 form.getlist' %
          (scope, 1 if batch_id else 0))

    token, _r = csrf_of(bo, '/assess/tasks/%d' % tid)
    r = bo.post(BASE + '/assess/tasks/%d/state' % tid,
                data={'csrf_token': token, 'action': 'open'},
                timeout=40, allow_redirects=False)
    n_roster = roster_count(tid) if tid else 0
    check('B2.1', '门户发布 → 303 且 state 落库为 open、名单快照从 0 到 N',
          r.status_code == 303 and task_state(tid) == 'open' and n_roster > 0,
          'HTTP %s Location=%s ｜ state=%s ｜ 名单行数 0→%d'
          % (r.status_code, loc(r), task_state(tid), n_roster))

    row = psql('SELECT id FROM edu_assess_roster WHERE task_id = %d AND student_id = %d'
               % (tid, sid))
    if not row:
        token, _r = csrf_of(bo, '/assess/tasks/%d/roster' % tid)
        bo.post(BASE + '/assess/tasks/%d/roster/add' % tid,
                data={'csrf_token': token, 'names': STUDENT_GR_NO},
                timeout=40, allow_redirects=False)
        row = psql('SELECT id FROM edu_assess_roster WHERE task_id = %d AND student_id = %d'
                   % (tid, sid))
    if not check('B2.2', '被评者（stu@local 的学生档案）在名单里', bool(row),
                 'roster_id=%s' % (row or '（无）')):
        return None
    roster_id = int(row.splitlines()[0])

    # B3 手工添加 / 逐条移除（用范围外的另一个学生，避免打到被评者那一行）
    in_roster = [int(x) for x in psql(
        'SELECT student_id FROM edu_assess_roster WHERE task_id = %d AND student_id IS NOT NULL'
        % tid).splitlines() if x.strip()]
    extra_id, extra_gr = pick_extra_student(set(in_roster + [sid]))
    if extra_id:
        n0 = roster_count(tid)
        token, _r = csrf_of(bo, '/assess/tasks/%d/roster' % tid)
        ra = bo.post(BASE + '/assess/tasks/%d/roster/add' % tid,
                     data={'csrf_token': token, 'names': extra_gr},
                     timeout=40, allow_redirects=False)
        n1 = roster_count(tid)
        new_row = psql('SELECT id FROM edu_assess_roster WHERE task_id = %d AND student_id = %d'
                       % (tid, extra_id))
        check('B3.1', '名单手工添加一行 → 303 且库内 +1',
              ra.status_code == 303 and n1 == n0 + 1 and bool(new_row),
              'HTTP %s ｜ 行数 %d→%d ｜ roster_id=%s'
              % (ra.status_code, n0, n1, new_row or '（无）'))
        if new_row:
            rd = bo.post(BASE + '/assess/tasks/%d/roster/%s/delete' % (tid, new_row),
                         data={'csrf_token': token}, timeout=40,
                         allow_redirects=False)
            n2 = roster_count(tid)
            check('B3.2', '名单逐条移除 → 303 且库内回到原值',
                  rd.status_code == 303 and n2 == n0,
                  'HTTP %s ｜ 行数 %d→%d' % (rd.status_code, n1, n2))
    else:
        check('B3.1', '找到范围外的第二个学生用于增删探针', False, '库里没有可用学生')

    # 留一个"一行未评"的行：结束守卫（D1）要靠它 —— 就用刚才那个范围外的学生
    # **再加回来**（加/删各已证过一轮；本地库学生极少，别去赌"还有第三个人"）。
    keep_id, keep_row = extra_id, ''
    if extra_id:
        token, _r = csrf_of(bo, '/assess/tasks/%d/roster' % tid)
        bo.post(BASE + '/assess/tasks/%d/roster/add' % tid,
                data={'csrf_token': token, 'names': extra_gr},
                timeout=40, allow_redirects=False)
        keep_row = psql('SELECT id FROM edu_assess_roster WHERE task_id = %d '
                        'AND student_id = %d' % (tid, extra_id))
    pending_rows = psql('SELECT count(*) FROM edu_assess_roster WHERE task_id = %d '
                        'AND state <> \'done\'' % tid)
    check('B3.3', '构造出一个"一行未评"的行（结束守卫的确定性前置）',
          bool(keep_row) and int(pending_rows) >= 1,
          'keep_row=%s ｜ 未评行数=%s' % (keep_row or '（无）', pending_rows))

    # B4 教师打分（既有门户路由）
    items = [tuple(x.split('|')) for x in psql(
        "SELECT id, max_score FROM edu_assess_item WHERE template_id = %d "
        "AND item_kind = 'leaf' AND active ORDER BY sequence, id" % tpl_id
    ).splitlines() if x.strip()]
    fac_token, fr = csrf_of(fac, '/assess/grade/%d' % tid)
    payload = {'csrf_token': fac_token}
    for iid, mx in items:
        payload['v_%d_%s' % (roster_id, iid)] = mx if float(mx) else '10'
    rg = fac.post(BASE + '/assess/grade/%d/save' % tid, data=payload,
                  timeout=40, allow_redirects=False)
    n_score = int(psql('SELECT count(*) FROM edu_assess_score WHERE task_id = %d' % tid))
    row_state = psql('SELECT state FROM edu_assess_roster WHERE id = %d' % roster_id)
    check('B4.1', '教师走既有门户路由打分 → 303 且打分落库、名单行转"已评"',
          rg.status_code == 303 and n_score >= len(items) and row_state == 'done',
          'HTTP %s Location=%s ｜ 打分条数=%d ｜ 该行 state=%s ｜ csrf 来源 /assess/grade/%d（HTTP %s）'
          % (rg.status_code, loc(rg), n_score, row_state, tid, fr.status_code))

    r = stu.get(BASE + '/assess/my', timeout=40)
    check('C1.1', '结束**前**：学生端 /assess/my 不含本次任务（此刻链接还未闭合）',
          PERIOD not in r.text and 'edu_assess_task' not in r.text,
          'HTTP %s ｜ 页面出现本次任务=%s' % (r.status_code, PERIOD in r.text))

    # B5 结束（带确认）
    token, _r = csrf_of(bo, '/assess/tasks/%d' % tid)
    rc = bo.post(BASE + '/assess/tasks/%d/state' % tid,
                 data={'csrf_token': token, 'action': 'close', 'confirm': '1'},
                 timeout=40, allow_redirects=False)
    check('B5.1', '门户结束 → 303 且 state 落库为 closed',
          rc.status_code == 303 and task_state(tid) == 'closed',
          'HTTP %s Location=%s ｜ state=%s' % (rc.status_code, loc(rc), task_state(tid)))

    audit = psql("SELECT count(*) FROM edu_audit_log WHERE model = 'edu.assess.task' "
                 "AND res_id = %d AND action IN ('评估任务发布', '评估任务结束')" % tid)
    detail = psql("SELECT detail FROM edu_audit_log WHERE model = 'edu.assess.task' "
                  "AND res_id = %d AND action = '评估任务结束' LIMIT 1" % tid)
    check('B6.1', '发布与结束都留下审计（含未评行数）',
          int(audit) == 2 and '未评' in detail,
          '审计条数=%s ｜ 结束详情=%s' % (audit, detail[:160]))

    return {'tid': tid, 'tpl_id': tpl_id, 'roster_id': roster_id,
            'sid': sid, 'keep_row': int(keep_row) if keep_row else None,
            'items': items, 'n_roster': roster_count(tid)}


# ----------------------------------------------------------------------
# A 前置事实
# ----------------------------------------------------------------------

def phase_a(bo, stu):
    print('')
    print('== A 前置事实（"没人结束任务"这个病根的读数）==')
    closed = psql("SELECT count(*) FROM edu_assess_task WHERE state = 'closed'")
    total = psql('SELECT count(*) FROM edu_assess_task')
    note('A1', '结束前的任务状态分布（SQL）',
         '任务总数=%s ｜ closed=%s' % (total, closed))
    r = stu.get(BASE + '/assess/my', timeout=40)
    empty = '暂无已结束的评估结果' in r.text
    note('A2', '学生端 /assess/my 的"我收到的评估结果"读数',
         'HTTP %s ｜ 空态文案在页面上=%s ｜ 页面长度=%d' % (r.status_code, empty, len(r.text)))
    r = bo.get(BASE + '/assess', timeout=40)
    check('A3', '门户 /assess 上出现「评估任务」入口（不必再进后台）',
          '/assess/tasks' in r.text and '管理评估任务' in r.text,
          'HTTP %s ｜ 含 /assess/tasks=%s' % (r.status_code, '/assess/tasks' in r.text))


# ----------------------------------------------------------------------
# C 闭环
# ----------------------------------------------------------------------

def phase_c(bo, stu, fx):
    print('')
    print('== C 闭环：结束后学生端**必须**出现这次结果（从空变有）==')
    tid = fx['tid']
    before = stu.get(BASE + '/assess/my', timeout=40)
    note('C0', '结束前的页面读数', '含本次任务=%s ｜ 含「暂无已结束」=%s'
         % (PERIOD in before.text, '暂无已结束的评估结果' in before.text))

    after = stu.get(BASE + '/assess/my', timeout=40)
    check('C1.2', '结束**后**：学生端 /assess/my 出现本次任务的结果卡（本任务要修的症状）',
          PERIOD in after.text,
          'HTTP %s ｜ 含本次任务=%s ｜ 读数：%s'
          % (after.status_code, PERIOD in after.text,
             _result_excerpt(after.text, PERIOD)))
    cells = psql('SELECT round(value::numeric, 2) FROM edu_assess_score '
                 'WHERE task_id = %d AND roster_id = %d ORDER BY id' % (tid, fx['roster_id']))
    want = [x for x in cells.splitlines() if x.strip()]
    shown = _shown_scores(after.text, PERIOD)
    check('C2.1', '页面上的分数 == SQL 里该行的打分值（不是"有了点什么"就算过）',
          bool(want) and all(any(w.rstrip('0').rstrip('.') == s for s in shown)
                             for w in want),
          'SQL=%s ｜ 页面读出=%s' % (want, shown))

    # C3 因果对照：重开 → 又空；再结束 → 又出现
    token, _r = csrf_of(bo, '/assess/tasks/%d' % tid)
    rr = bo.post(BASE + '/assess/tasks/%d/state' % tid,
                 data={'csrf_token': token, 'action': 'reopen', 'confirm': '1'},
                 timeout=40, allow_redirects=False)
    mid = stu.get(BASE + '/assess/my', timeout=40)
    rc = bo.post(BASE + '/assess/tasks/%d/state' % tid,
                 data={'csrf_token': token, 'action': 'close', 'confirm': '1'},
                 timeout=40, allow_redirects=False)
    final = stu.get(BASE + '/assess/my', timeout=40)
    check('C3.1', '因果对照：重开后学生端又变空、再次结束后又出现（"结束"就是那一步）',
          rr.status_code == 303 and mid is not None and PERIOD not in mid.text
          and rc.status_code == 303 and PERIOD in final.text,
          '重开 HTTP %s → 含任务=%s ｜ 再结束 HTTP %s → 含任务=%s ｜ state=%s'
          % (rr.status_code, PERIOD in mid.text, rc.status_code,
             PERIOD in final.text, task_state(tid)))


def _result_excerpt(html, needle):
    """把结果卡那一段抠出来（给报告留原始读数，不靠"我说有"）。"""
    i = html.find(needle)
    if i < 0:
        return '（页面里没有这个名字）'
    seg = re.sub(r'<[^>]+>', ' ', html[max(0, i - 200):i + 900])
    return re.sub(r'\s+', ' ', seg).strip()[:400]


def _shown_scores(html, needle):
    i = html.find(needle)
    if i < 0:
        return []
    seg = html[i:i + 2000]
    return [x.strip() for x in re.findall(r'text-end">\s*([0-9]+\.?[0-9]*)\s*<', seg)]


# ----------------------------------------------------------------------
# D 守卫
# ----------------------------------------------------------------------

def phase_d(bo, fx):
    print('')
    print('== D 守卫（每条都要求"拒绝 + 零副作用"）==')
    tid = fx['tid']
    # 构造一个 open 的任务：先把夹具重开（C3 结束时它是 closed）
    token, _r = csrf_of(bo, '/assess/tasks/%d' % tid)
    if task_state(tid) == 'closed':
        bo.post(BASE + '/assess/tasks/%d/state' % tid,
                data={'csrf_token': token, 'action': 'reopen', 'confirm': '1'},
                timeout=40, allow_redirects=False)
    note('D0', 'D 段起点', '任务 %d state=%s ｜ 名单 %d 行 ｜ 未评行 %s'
         % (tid, task_state(tid), roster_count(tid),
            psql('SELECT count(*) FROM edu_assess_roster WHERE task_id = %d '
                 "AND state <> 'done'" % tid)))

    # D1 无确认结束 → 拒绝
    r = bo.post(BASE + '/assess/tasks/%d/state' % tid,
                data={'csrf_token': token, 'action': 'close'},
                timeout=40, allow_redirects=False)
    check('D1.1', '有未评行时不带确认结束 → **被拒**（303 带 error）且 state 不变',
          r.status_code == 303 and 'error=' in loc(r) and task_state(tid) == 'open',
          'HTTP %s Location=%s ｜ state=%s' % (r.status_code, loc(r)[:160], task_state(tid)))

    # D3 状态机不跳级（此时是 open）
    r = bo.post(BASE + '/assess/tasks/%d/state' % tid,
                data={'csrf_token': token, 'action': 'reopen', 'confirm': '1'},
                timeout=40, allow_redirects=False)
    check('D3.1', '进行中的任务不能再"重新打开"（状态机不跳级）',
          r.status_code == 303 and 'error=' in loc(r) and task_state(tid) == 'open',
          'HTTP %s Location=%s ｜ state=%s' % (r.status_code, loc(r)[:160], task_state(tid)))
    r = bo.post(BASE + '/assess/tasks/%d/state' % tid,
                data={'csrf_token': token, 'action': 'open'},
                timeout=40, allow_redirects=False)
    check('D3.2', '已发布的任务不能再"发布"一次',
          r.status_code == 303 and 'error=' in loc(r) and task_state(tid) == 'open',
          'HTTP %s Location=%s' % (r.status_code, loc(r)[:160]))

    # D4 越权跨任务删除：拿**别的任务**的名单行来删
    other = psql('SELECT id FROM edu_assess_roster WHERE task_id <> %d ORDER BY id LIMIT 1'
                 % tid)
    if other:
        n0 = roster_count(tid)
        r = bo.post(BASE + '/assess/tasks/%d/roster/%s/delete' % (tid, other),
                    data={'csrf_token': token}, timeout=40, allow_redirects=False)
        alive = psql('SELECT count(*) FROM edu_assess_roster WHERE id = %s' % other)
        check('D4.1', '拿别任务的名单行 id 来删 → **被拒**且那行还在、本任务行数不变',
              r.status_code == 303 and 'error=' in loc(r) and alive == '1'
              and roster_count(tid) == n0,
              'HTTP %s Location=%s ｜ 目标行仍在=%s ｜ 本任务行数 %d→%d'
              % (r.status_code, loc(r)[:150], alive, n0, roster_count(tid)))

    # D5 换模板护栏：已有名单的任务改模板 → 拒绝
    other_tpl = psql('SELECT id FROM edu_assess_template WHERE id <> %d ORDER BY id LIMIT 1'
                     % fx['tpl_id'])
    if other_tpl:
        r = bo.post(BASE + SAVE_PATH, data={
            'csrf_token': token, 'task_id': str(tid), 'template_id': other_tpl,
            'period': PERIOD, 'date_begin': '', 'date_due': '2026-12-31',
            'scorer_kind': 'teacher', 'summary_min': '3', 'active': '1',
            'notes': NOTES}, timeout=40, allow_redirects=False)
        now_tpl = psql('SELECT template_id FROM edu_assess_task WHERE id = %d' % tid)
        check('D5.1', '已生成名单的任务换模板 → **被拒**且库内模板不变',
              r.status_code == 303 and 'error=' in loc(r)
              and now_tpl == str(fx['tpl_id']),
              'HTTP %s Location=%s ｜ 库内模板 %s（期望 %d）'
              % (r.status_code, loc(r)[:150], now_tpl, fx['tpl_id']))

    # D2 结束后的名单冻结
    r = bo.post(BASE + '/assess/tasks/%d/state' % tid,
                data={'csrf_token': token, 'action': 'close', 'confirm': '1'},
                timeout=40, allow_redirects=False)
    n_closed = roster_count(tid)
    if r.status_code == 303 and task_state(tid) == 'closed':
        rb = bo.post(BASE + '/assess/tasks/%d/roster/build' % tid,
                     data={'csrf_token': token}, timeout=40, allow_redirects=False)
        ra = bo.post(BASE + '/assess/tasks/%d/roster/add' % tid,
                     data={'csrf_token': token, 'names': STUDENT_GR_NO},
                     timeout=40, allow_redirects=False)
        target_row = fx['keep_row'] or fx['roster_id']
        rd = bo.post(BASE + '/assess/tasks/%d/roster/%d/delete' % (tid, target_row),
                     data={'csrf_token': token}, timeout=40, allow_redirects=False)
        check('D2.1', '结束后名单冻结：生成/添加/删除三条写路由全部被拒且行数不变',
              all(x.status_code == 303 and 'error=' in loc(x)
                  for x in (rb, ra, rd)) and roster_count(tid) == n_closed,
              'build=%s add=%s delete=%s ｜ 行数 %d→%d'
              % (loc(rb)[:40], loc(ra)[:40], loc(rd)[:40], n_closed, roster_count(tid)))
        r = bo.post(BASE + '/assess/tasks/%d/state' % tid,
                    data={'csrf_token': token, 'action': 'close', 'confirm': '1'},
                    timeout=40, allow_redirects=False)
        check('D3.3', '已结束的任务不能再结束一次',
              r.status_code == 303 and 'error=' in loc(r) and task_state(tid) == 'closed',
              'HTTP %s Location=%s' % (r.status_code, loc(r)[:160]))
    else:
        check('D2.1', 'D 段收尾时结束夹具任务', False,
              'close 失败：HTTP %s state=%s' % (r.status_code, task_state(tid)))


# ----------------------------------------------------------------------
# E 越权
# ----------------------------------------------------------------------

def phase_e(bo, sessions, fx):
    print('')
    print('== E 越权（学生/教师/家长 × 全部 9 条新路由 + 写入残留 0）==')
    tid = fx['tid']
    proxy_row = fx['keep_row'] or fx['roster_id']
    paths_get = ['/assess/tasks', '/assess/tasks/new',
                 '/assess/tasks/%d' % tid, '/assess/tasks/%d/roster' % tid]
    posts = [
        ('/assess/tasks/save',
         {'task_id': '', 'template_id': str(fx['tpl_id']), 'period': PERIOD,
          'scorer_kind': 'teacher', 'summary_min': '3', 'notes': NOTES}),
        ('/assess/tasks/%d/state' % tid,
         {'action': 'close', 'confirm': '1'}),
        ('/assess/tasks/%d/roster/build' % tid, {}),
        ('/assess/tasks/%d/roster/add' % tid, {'names': STUDENT_GR_NO}),
        ('/assess/tasks/%d/roster/%d/delete' % (tid, proxy_row), {}),
    ]
    before = snapshot(tid)
    note('E0', '越权探之前的 SQL 快照', json.dumps(before, ensure_ascii=False))

    # 只探**非授权**的三个身份（教务/管理员本就该拿到 200，那是 F 段的控制组）
    unauth = {k: sessions[k] for k in ('学生', '教师', '家长') if k in sessions}
    bad_get, bad_post = [], []
    for who, sess in unauth.items():
        for p in paths_get:
            r = sess.get(BASE + p, timeout=40, allow_redirects=False)
            if not (r.status_code == 303 and loc(r).startswith('/my/home')):
                bad_get.append('%s %s → %s %s' % (who, p, r.status_code, loc(r)[:60]))
        token, page = csrf_of(sess, sess.csrf_path)
        if not token:
            check('E1.0', '%s 取到合法 csrf（越权探必须带真 token，不能拿 403 糊）'
                  % who, False, '来源 %s HTTP %s' % (sess.csrf_path, page.status_code))
            continue
        for p, data in posts:
            payload = dict(data)
            payload['csrf_token'] = token
            r = sess.post(BASE + p, data=payload, timeout=40, allow_redirects=False)
            if not (r.status_code == 303 and loc(r).startswith('/my/home')):
                bad_post.append('%s POST %s → %s %s' % (who, p, r.status_code, loc(r)[:60]))
    check('E1.1', '4 条页面路由 × 学生/教师/家长 = 12 探 → 全部 303 /my/home',
          not bad_get, '异常：%s' % (bad_get or '无'))
    check('E2.1', '5 条写路由 × 学生/教师/家长 = 15 探（带合法 csrf）→ 全部 303 /my/home',
          not bad_post, '异常：%s' % (bad_post or '无'))

    after = snapshot(tid)
    diff = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    check('E3.1', '越权写入残留 0：探完逐项快照相等（任务/名单/打分/状态/审计）',
          not diff, '前后差异：%s' % (diff or '无（逐项相等）'))

    anon = requests.Session()
    anon.trust_env = False
    anon.proxies = {'http': None, 'https': None}
    r = anon.get(BASE + '/assess/tasks', timeout=40, allow_redirects=False)
    check('E4.1', '未登录访问 → 走 auth=\'user\' 兜底（303 到登录页）',
          r.status_code in (302, 303) and '/web/login' in loc(r),
          'HTTP %s Location=%s' % (r.status_code, loc(r)[:160]))


# ----------------------------------------------------------------------
# F 控制组
# ----------------------------------------------------------------------

def phase_f(bo, sessions, fx):
    print('')
    print('== F 控制组（断言不是恒真/恒假）==')
    tid = fx['tid']
    adm = login('admin')
    codes = {}
    for p in ['/assess/tasks', '/assess/tasks/new', '/assess/tasks/%d' % tid,
              '/assess/tasks/%d/roster' % tid]:
        r = adm.get(BASE + p, timeout=40)
        codes[p] = r.status_code
    check('F1.1', '系统组（admin，同为授权层）访问同一批页面 → 200（"200"可达）',
          all(c == 200 for c in codes.values()), '读数=%s' % codes)

    stu = sessions['学生']
    r1 = stu.get(BASE + '/assess/my', timeout=40)
    fac = sessions['教师']
    r2 = fac.get(BASE + '/assess/grade/%d' % tid, timeout=40)
    check('F2.1', '学生/教师访问**自己该看的**页 → 200（"303"不是处处 303）',
          r1.status_code == 200 and r2.status_code == 200,
          '学生 /assess/my=%s ｜ 教师 /assess/grade/%d=%s'
          % (r1.status_code, tid, r2.status_code))

    r = bo.get(BASE + '/assess/tasks/999999', timeout=40, allow_redirects=False)
    check('F3.1', '不存在的任务 id → 303 带错误（"200"期望在坏路径上会失败 ⇒ 非恒真）',
          r.status_code == 303 and 'error=' in loc(r),
          'HTTP %s Location=%s' % (r.status_code, loc(r)[:160]))


# ----------------------------------------------------------------------
# G 被评教师视角（B 项）：/assess/my 对教师生效 + 反向隔离 + score_visible 闸门
# ----------------------------------------------------------------------

def _new(adm, model, vals):
    """夹具用：后台同一条写路径（JSON-RPC create），返回值可能是 int 或 [int]。"""
    res, err = call_kw(adm, model, 'create', [vals])
    if err:
        raise RuntimeError('%s create 失败：%s' % (model, err))
    return res[0] if isinstance(res, list) else res


def phase_g(adm, sessions):
    print('')
    print('== G 被评教师在 /assess/my 能看到自己的评教结果（反向：看不到别人的）==')
    fac_a = psql("SELECT f.id FROM op_faculty f "
                 "JOIN res_partner p ON p.id = f.partner_id "
                 "JOIN res_users u ON u.id = p.user_id "
                 "WHERE u.login = 'faculty@local'")
    fac_b = psql('SELECT f.id FROM op_faculty f WHERE f.id <> %s '
                 'ORDER BY f.id LIMIT 1' % (fac_a or 0))
    if not fac_a or not fac_b:
        check('G0', '找到两位教师档案（A = faculty@local，B = 另一位）', False,
              'fac_a=%s fac_b=%s' % (fac_a, fac_b))
        return None
    fac_a, fac_b = int(fac_a), int(fac_b)
    tpl = _new(adm, 'edu.assess.template', {
        'name': MARK + '评教（被评教师视角）', 'kind': 'teaching',
        'target_kind': 'faculty', 'total': 100.0, 'pass_line': 60.0,
        'excellent_line': 90.0, 'weight_mode': 'multiplier',
        'state': 'active', 'score_visible': True})
    item_ids = [_new(adm, 'edu.assess.item', {
        'template_id': tpl, 'name': nm, 'max_score': mx, 'weight': 1.0,
        'sequence': i * 10}) for i, (nm, mx) in
        enumerate((('备课充分', 20.0), ('课堂表达', 30.0)), 1)]
    made = {}
    for key, fac_id, period, vals in (('a', fac_a, '评教A', (15.0, 25.0)),
                                      ('b', fac_b, '评教B', (7.0, 13.0))):
        tid = _new(adm, 'edu.assess.task', {
            'template_id': tpl, 'period': MARK + period, 'state': 'closed',
            'scorer_kind': 'student', 'anonymous': False, 'summary_min': 1,
            'notes': MARK + '被评教师视角夹具'})
        rid = _new(adm, 'edu.assess.roster', {'task_id': tid, 'faculty_id': fac_id})
        for iid, v in zip(item_ids, vals):
            _new(adm, 'edu.assess.score', {
                'task_id': tid, 'roster_id': rid, 'item_id': iid, 'value': v,
                'scorer_ref': 'i:2', 'track': 'objective'})
        made[key] = {'tpl': tpl, 'tid': tid, 'rid': rid, 'vals': vals,
                     'name': MARK + period}
    note('G0', '夹具', '模板=%s ｜ 任务A=%s（教师 %s）｜ 任务B=%s（教师 %s）'
         % (tpl, made['a']['tid'], fac_a, made['b']['tid'], fac_b))

    fac_sess = sessions['教师']
    r = fac_sess.get(BASE + '/assess/my', timeout=40)
    seg = r.text[r.text.find(made['a']['name']):]
    cells = re.findall(r'<td class="text-end">\s*([0-9.]+)', seg[:2500])
    check('G1.1', '被评教师打开 /assess/my → 200 且看到**自己被评**的分数',
          r.status_code == 200 and made['a']['name'] in r.text
          and cells[:2] == ['15', '25'],
          'HTTP %s ｜ 命中任务=%s ｜ 读到格子=%s（期望 15/25）'
          % (r.status_code, made['a']['name'] in r.text, cells[:2]))
    cards = r.text.count('card shadow-sm border-0 rounded-3 mb-3')
    check('G2.1', '反向：教师 A 拿不到教师 B 的评教结果（任务 B 名不在页面上，卡片只有 1 张）',
          made['b']['name'] not in r.text and cards == 1,
          '任务B名出现=%s ｜ 结果卡张数=%d（若域没收敛会是 2）'
          % (made['b']['name'] in r.text, cards))
    rb = sessions['教务'].get(
        BASE + '/assess/task/%d/results' % made['b']['tid'], timeout=40)
    check('G2.2', '控制组：任务 B 的数据确实在库里、教务看得到（A 看不到不是"数据没有"）',
          rb.status_code == 200 and '7.00' in rb.text and '13.00' in rb.text,
          'HTTP %s ｜ 含 B 的分值 7.00/13.00=%s'
          % (rb.status_code, '7.00' in rb.text and '13.00' in rb.text))

    call_kw(adm, 'edu.assess.template', 'write', [[tpl], {'score_visible': False}])
    r2 = fac_sess.get(BASE + '/assess/my', timeout=40)
    cells2 = re.findall(r'<td class="text-end">\s*([0-9.]+)',
                        r2.text[r2.text.find(made['a']['name']):][:2500])
    check('G4.1', '闸门：模板 score_visible=False ⇒ 教师端只看到"不公开"的说明、看不到分数',
          r2.status_code == 200 and '本次评估结果不向被评者公开' in r2.text
          and '15' not in cells2,
          'HTTP %s ｜ 解释文字=%s ｜ 数字格=%s'
          % (r2.status_code, '本次评估结果不向被评者公开' in r2.text, cells2[:2]))
    call_kw(adm, 'edu.assess.template', 'write', [[tpl], {'score_visible': True}])
    r3 = fac_sess.get(BASE + '/assess/my', timeout=40)
    cells3 = re.findall(r'<td class="text-end">\s*([0-9.]+)',
                        r3.text[r3.text.find(made['a']['name']):][:2500])
    check('G5.1', '控制组：开关打开后同一读数立刻回来（不是页面坏了）',
          cells3[:2] == ['15', '25'], '读到格子=%s' % cells3[:2])
    return made


# ----------------------------------------------------------------------
# H 三层模板：矩阵只列叶子（A 项）+ xlsx 区名往返（D 项）
# ----------------------------------------------------------------------

#: 仿《卫生检测表》：3 区 8 项，**跨区同名**（窗户有灰尘/污渍 ×3、垃圾未倒 ×2），全部扣分制
H_AREAS = [
    ('厨房', [('窗户有灰尘/污渍', 2.0), ('墙面有污渍', 3.0), ('灶台油渍', 5.0)]),
    ('卫生间', [('窗户有灰尘/污渍', 2.0), ('垃圾未倒', 4.0)]),
    ('卧室', [('窗户有灰尘/污渍', 2.0), ('垃圾未倒', 4.0), ('床铺不整', 3.0)]),
]


def _xlsx_rows(content):
    import io as _io
    import openpyxl
    book = openpyxl.load_workbook(_io.BytesIO(content))
    sheet = book.active
    return [[c.value for c in row] for row in sheet.iter_rows()]


def _post_file(sess, url, content, filename, csrf_path=None, extra=None):
    token, _r = csrf_of(sess, csrf_path or url.replace('/import', '/results'))
    data = {'csrf_token': token}
    data.update(extra or {})
    return sess.post(BASE + url, data=data,
                     files={'file': (filename, content,
                                     'application/vnd.openxmlformats-'
                                     'officedocument.spreadsheetml.sheet')},
                     timeout=60, allow_redirects=False)


def _preview_counts(html):
    m = re.search(r'可写入 <b[^>]*>(\d+)</b> 行，待修正 <b[^>]*>(\d+)</b> 行', html or '')
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _payload_of(html):
    import html as _html
    m = re.search(r'name="payload" value="([^"]*)"', html or '')
    return json.loads(_html.unescape(m.group(1))) if m else None


def _make_xlsx(header, rows):
    import io as _io
    import openpyxl
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    buf = _io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def _score_dump(tid):
    return psql('SELECT roster_id, item_id, round(value::numeric, 4) '
                'FROM edu_assess_score WHERE task_id = %d '
                'ORDER BY roster_id, item_id' % tid)


def _build_grouped_fixture(adm):
    """建三层夹具：3 区 8 叶子（跨区同名）+ 任务 + 2 名学生 + 每人每项扣 1 分。"""
    tpl = _new(adm, 'edu.assess.template', {
        'name': MARK + '卫生检测表（区名往返）', 'kind': 'other',
        'target_kind': 'student', 'total': 100.0, 'pass_line': 60.0,
        'excellent_line': 90.0, 'weight_mode': 'multiplier', 'state': 'active'})
    leaves = []
    seq = 0
    for area, checks in H_AREAS:
        seq += 10
        gid = _new(adm, 'edu.assess.item', {
            'template_id': tpl, 'name': area, 'item_kind': 'group',
            'sequence': seq})
        lseq = 0
        for cname, deduct in checks:
            lseq += 10
            leaves.append((cname, area, _new(adm, 'edu.assess.item', {
                'template_id': tpl, 'parent_id': gid, 'name': cname,
                'item_kind': 'leaf', 'score_mode': 'deduct',
                'max_score': deduct, 'weight': 1.0, 'sequence': lseq})))
    sids = [int(x) for x in psql('SELECT id FROM op_student WHERE active '
                                 'ORDER BY id LIMIT 2').splitlines() if x.strip()]
    tid = _new(adm, 'edu.assess.task', {
        'template_id': tpl, 'period': MARK + '区名往返', 'state': 'open',
        'scorer_kind': 'teacher', 'notes': MARK + 'xlsx 区名往返夹具'})
    rids = [_new(adm, 'edu.assess.roster', {'task_id': tid, 'student_id': sid})
            for sid in sids]
    for rid in rids:
        for _cname, _area, iid in leaves:
            _new(adm, 'edu.assess.score', {
                'task_id': tid, 'roster_id': rid, 'item_id': iid, 'value': 1.0,
                'scorer_ref': 'i:2', 'track': 'objective'})
    return {'tpl': tpl, 'tid': tid, 'leaf_ids': [x[2] for x in leaves],
            'leaves': leaves, 'rids': rids, 'sids': sids}


def phase_h(bo, adm):
    print('')
    print('== H 三层模板：矩阵只列叶子（A）+ xlsx 区名往返（D）==')
    fx = _build_grouped_fixture(adm)
    n_leaves = len(fx['leaf_ids'])
    note('H0', '夹具', '模板=%s ｜ 任务=%s ｜ 叶子 %d 个 / 分组 3 个 ｜ 名单 %d 行'
         % (fx['tpl'], fx['tid'], n_leaves, len(fx['rids'])))

    # ---- A：门户矩阵的**评分列** = 叶子数，且不含分组名 ----
    # ⚠ 口径（2026-09-29 队长裁定后重写；改这里之前先读完这段）：
    #   本断言守的是「**分组节点不得成为评分列**」—— 第 1 期就是栽在把整棵
    #   item 树（含分组节点）当成列：三层模板会多出「区/分类」这种打不了分的列
    #   （打分会直接被模型 _check_value 拒）。它守的**不是**「表头里不许出现 th」。
    #   2026-09-29 起矩阵加了区名分组表头，分组格正是 <th scope="colgroup" colspan=N>
    #   —— 读屏用户靠它拿分组语义（跨区同名项正是这个功能的理由）。
    #   ⇒ 只数**评分列** = <thead> 最后一行里不带 scope="colgroup" 的 <th>，
    #     再去掉行标签列（"学生"/"教师"：扁平模板里它与评分列同行）。
    #   判据强度自证：把分组节点混进 items（= 让分组节点变成评分列）⇒ 分组名会出现在
    #   评分列里 ⇒ 本断言必须 FAIL（反向注入实验见报告与
    #   tests/smoke/assess_portal_gaps.py 的 M 段）。
    r = bo.get(BASE + '/assess/grade/%d' % fx['tid'], timeout=40)
    m = re.search(r'id="yy-assess-grade-table".*?</table>', r.text or '', re.S)
    body = m.group(0) if m else ''
    thead = re.search(r'<thead[^>]*>(.*?)</thead>', body, re.S)
    head_rows = re.findall(r'<tr[^>]*>(.*?)</tr>',
                           thead.group(1) if thead else '', re.S)

    def _head_cells(tr):
        out = []
        for tag, attrs, inner in re.findall(r'<(th|td)([^>]*)>(.*?)</\1>',
                                           tr, re.S):
            out.append((tag, attrs, re.sub(r'<[^>]+>', '', inner).strip()))
        return out

    first_cells = _head_cells(head_rows[0]) if head_rows else []
    row_label = first_cells[0][2] if first_cells else ''
    item_heads = [text for tag, attrs, text in
                  (_head_cells(head_rows[-1]) if head_rows else [])
                  if tag == 'th' and 'scope="colgroup"' not in attrs
                  and text != row_label]
    # 同一件事的另一半（这条才是真正挡住「分组节点变成列」的判据）：
    # 表头里**所有**不带 scope="colgroup" 的格（除行标签列）都必须是**叶子项名**。
    # 第 1 期的缺陷形态正是「整棵 item 树当列」——那时分组名（厨房/卫生间/卧室、
    # 以及二级的清洁/垃圾…）会以普通 <th> 出现在表头里；本判据当场 FAIL。
    # （只数最后一行的 th 会漏掉这种形态：分组节点的 <th> 带 rowspan，落在更上面一行。）
    leaf_names = set(n for n, _a, _i in fx['leaves'])
    stray = [text for tr in head_rows for tag, attrs, text in _head_cells(tr)
             if tag == 'th' and 'scope="colgroup"' not in attrs
             and text != row_label and text not in leaf_names]
    groups = [a for a, _c in H_AREAS]
    check('H1.1', '门户矩阵**评分列** == 叶子项数（%d），且分组节点没有变成列' % n_leaves,
          r.status_code == 200 and len(item_heads) == n_leaves
          and not any(g in item_heads for g in groups) and not stray,
          'HTTP %s ｜ 行标签=%s ｜ 评分列 %d 列=%s ｜ 分组名混入=%s ｜ 非叶子的表头格=%s'
          % (r.status_code, [row_label], len(item_heads), item_heads,
             [g for g in groups if g in item_heads] or '无', stray or '无'))
    check('H1.2', '对照：修前口径（含分组）会是 %d 列 —— 本次读数确实变了'
          % (n_leaves + len(groups)),
          len(item_heads) != n_leaves + len(groups),
          '现在评分列 %d ｜ 含分组会是 %d' % (len(item_heads), n_leaves + len(groups)))

    # ---- D：导出结果 → 同一文件导回 → 零变更 ----
    # ⚠ 导出/导入一律用 admin（uid=2）：导入的 scorer_ref 是 "i:<当前 uid>"（设计口径：
    # 导入 = 录分人以自己的身份写分）。夹具的分也是 i:2 写的 ⇒ 同一个人导回才是
    # "逐格零变更"；换个身份导回本来就会多出**另一个人**的一列记录（那是产品语义，不是 bug）。
    r2 = adm.get(BASE + '/assess/task/%d/export.xlsx' % fx['tid'], timeout=60)
    header, rows = [], []
    if r2.status_code == 200 and r2.content[:2] == b'PK':
        grid = _xlsx_rows(r2.content)
        header = [('' if c is None else str(c)) for c in (grid[0] if grid else [])]
        rows = grid[1:]
    labels = ['%s / %s' % (area, name) for name, area, _i in fx['leaves']]
    check('H2.1', '导出结果：列头 = 学号/姓名 + **区名 / 项名** 标签（%d 列），同名项可分'
          % n_leaves,
          header[:2] == ['学号', '姓名']
          and all(lb in header for lb in labels)
          and '窗户有灰尘/污渍' not in header,
          '表头=%s' % header)
    check('H2.2', '数据行列数 == 名单行数（导出没丢行）',
          len(rows) == len(fx['rids']), '数据行 %d 行 / 名单 %d 行'
          % (len(rows), len(fx['rids'])))

    before = _score_dump(fx['tid'])
    r3 = _post_file(adm, '/assess/task/%d/import' % fx['tid'], r2.content,
                    'roundtrip.xlsx', csrf_path='/assess/task/%d/results' % fx['tid'])
    valid, invalid = _preview_counts(r3.text)
    check('H3.1', '同一文件导回：预览可写入 %d 行 / 待修正 0 行，且**没有"未知列头"**'
          % len(fx['rids']),
          r3.status_code == 200 and valid == len(fx['rids']) and invalid == 0
          and '未知列头' not in r3.text,
          'HTTP %s ｜ 可写入=%s 待修正=%s ｜ 未知列头=%s'
          % (r3.status_code, valid, invalid, '未知列头' in r3.text))
    # 反向：把列头换回**裸项名**（旧写法）导同一份数据 —— 跨区同名时对不上，
    # 必须被点名挡住。这条是"区名前缀不是装饰"的反证（没有它，H3.1 只证明没崩）。
    bare_head = ['学号', '姓名'] + [n for n, _a, _i in fx['leaves']]
    bare_body = [['', ''] + [1] * n_leaves]
    r_bare = _post_file(
        adm, '/assess/task/%d/import' % fx['tid'],
        _make_xlsx(bare_head, bare_body), 'bare-names.xlsx',
        csrf_path='/assess/task/%d/results' % fx['tid'])
    check('H3.2', '反向：裸项名列头导回 → 被"同名项"提示挡住（区名前缀确有必要）',
          r_bare.status_code == 200 and '未知列头' in r_bare.text
          and '同名项' in r_bare.text,
          'HTTP %s ｜ 未知列头=%s ｜ 同名项提示=%s'
          % (r_bare.status_code, '未知列头' in r_bare.text,
             '同名项' in r_bare.text))

    payload = _payload_of(r3.text) or []
    r4 = adm.post(BASE + '/assess/task/%d/import/commit' % fx['tid'],
                 data={'csrf_token': csrf_of(adm, '/assess/task/%d/results' % fx['tid'])[0],
                       'filename': 'roundtrip.xlsx',
                       'payload': json.dumps(payload, ensure_ascii=False)},
                 timeout=60, allow_redirects=False)
    after = _score_dump(fx['tid'])
    check('H4.1', '原样导回后**逐格零变更**（幂等：导出→导回 = 不动数据）',
          r4.status_code == 303 and before == after and bool(before),
          'HTTP %s ｜ 格子 %d 个 ｜ 前后相同=%s'
          % (r4.status_code, len(before.splitlines()), before == after))

    # ---- D：空表导出同口径 ----
    r5 = adm.get(BASE + '/assess/template/%d/blank.xlsx' % fx['tpl'], timeout=60)
    blank_header = []
    if r5.status_code == 200 and r5.content[:2] == b'PK':
        g5 = _xlsx_rows(r5.content)
        blank_header = [('' if c is None else str(c)) for c in (g5[0] if g5 else [])]
    check('H5.1', '导出空表：同一套区名标签列，且没有分组列',
          r5.status_code == 200 and blank_header[:2] == ['学号', '姓名']
          and all(lb in blank_header for lb in labels)
          and not any(a in blank_header for a, _c in H_AREAS),
          '表头=%s' % blank_header)

    # ---- 控制组：扁平模板仍然能往返 ----
    flat = _new(adm, 'edu.assess.template', {
        'name': MARK + '扁平对照（两项）', 'kind': 'student',
        'target_kind': 'student', 'total': 100.0, 'pass_line': 60.0,
        'state': 'active'})
    for idx, nm in enumerate(('平时表现', '期末考评'), 1):
        _new(adm, 'edu.assess.item', {
            'template_id': flat, 'name': nm, 'max_score': 20.0, 'weight': 1.0,
            'sequence': idx * 10})
    ftid = _new(adm, 'edu.assess.task', {
        'template_id': flat, 'period': MARK + '扁平对照', 'state': 'open',
        'scorer_kind': 'teacher', 'notes': MARK + '扁平往返夹具'})
    frid = _new(adm, 'edu.assess.roster', {'task_id': ftid, 'student_id': fx['sids'][0]})
    r6 = adm.get(BASE + '/assess/task/%d/export.xlsx' % ftid, timeout=60)
    if r6.status_code == 200 and r6.content[:2] == b'PK':
        g6 = _xlsx_rows(r6.content)
        fh = [('' if c is None else str(c)) for c in (g6[0] if g6 else [])]
        fbefore = _score_dump(ftid)
        rr = _post_file(adm, '/assess/task/%d/import' % ftid, r6.content,
                        'flat.xlsx',
                        csrf_path='/assess/task/%d/results' % ftid)
        fv, fi = _preview_counts(rr.text)
        fpayload = _payload_of(rr.text) or []
        adm.post(BASE + '/assess/task/%d/import/commit' % ftid,
                data={'csrf_token': csrf_of(adm, '/assess/task/%d/results' % ftid)[0],
                      'filename': 'flat.xlsx',
                      'payload': json.dumps(fpayload, ensure_ascii=False)},
                timeout=60, allow_redirects=False)
        fafter = _score_dump(ftid)
        check('H6.1', '控制组：扁平模板（列头=项名，无前缀）仍可往返且零变更',
              fh[:2] == ['学号', '姓名'] and '平时表现' in fh
              and fv == 1 and fi == 0 and fbefore == fafter,
              '表头=%s ｜ 可写入=%s 待修正=%s ｜ 前后相同=%s'
              % (fh, fv, fi, fbefore == fafter))
    else:
        check('H6.1', '控制组：扁平模板导出成功', False, 'HTTP %s' % r6.status_code)
    return fx


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------

class Sess(requests.Session):
    csrf_path = '/'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='',
                    help='只跑某些段：a,b,c,d,e,f,g,h（逗号分隔；默认全跑）')
    ap.add_argument('--purge', action='store_true', help='只清夹具')
    ap.add_argument('--keep', action='store_true',
                    help='跑完保留夹具（默认**清干净** —— 残留的【冒烟】数据会被'
                         'scripts/check_english.py 的夹具残留扫描判红，那是全仓门禁）')
    args = ap.parse_args()

    print('== 登录取会话 ==')
    bo = login('backoffice@local')
    fac = login('faculty@local')
    stu = login(STUDENT_LOGIN)
    par = login('parent@local')
    if not all((bo, fac, stu, par)):
        print('FATAL | 登录失败（bo=%s fac=%s stu=%s par=%s）' % tuple(
            bool(x) for x in (bo, fac, stu, par)))
        return 2
    # 越权探要带**该身份自己的**合法 csrf（否则只是拿 403 糊过去）。
    # 来源优先取该身份真能打开的页面；取不到就退回门户首页（同会话 token 同源）。
    for s in (stu, fac, par, bo):
        s.csrf_path = '/my/home'
    graded = psql("SELECT id FROM edu_assess_task WHERE state = 'open' "
                  "AND target_kind = 'student' ORDER BY id LIMIT 1")
    if graded:
        fac.csrf_path = '/assess/grade/%s' % graded.splitlines()[0]
    evals = psql("SELECT id FROM edu_assess_task WHERE state = 'open' "
                 "AND target_kind = 'faculty' AND scorer_kind = 'student' "
                 "ORDER BY id LIMIT 1")
    if evals:
        stu.csrf_path = '/assess/fill/%s' % evals.splitlines()[0]
    sessions = {'学生': stu, '教师': fac, '家长': par, '教务': bo}
    adm = login('admin')
    if not adm:
        print('FATAL | admin 登录失败（夹具建不起来）')
        return 2

    purged = purge_fixtures()
    if args.purge:
        print('已清夹具：任务 %s ｜ 模板 %s' % (purged[0] or '无', purged[1] or '无'))
        return 0
    if purged[0] or purged[1]:
        print('清掉旧夹具：任务 %s ｜ 模板 %s' % (purged[0] or '无', purged[1] or '无'))

    phases = set((args.only or 'a,b,c,d,e,f,g,h').split(','))
    phases = {p.strip() for p in phases if p.strip()}

    if 'a' in phases:
        phase_a(bo, stu)
    fx = build_fixture(bo, fac, stu)
    if not fx:
        print('FATAL | 夹具建不起来，后续段跳过')
        _dump()
        return 1
    if 'c' in phases:
        phase_c(bo, stu, fx)
    if 'd' in phases:
        phase_d(bo, fx)
    if 'e' in phases:
        phase_e(bo, sessions, fx)
    if 'f' in phases:
        phase_f(bo, sessions, fx)
    if 'g' in phases:
        phase_g(adm, sessions)
    if 'h' in phases:
        phase_h(bo, adm)

    failed = [r for r in rows if not r.get('info') and not r['pass']]
    # 夹具默认清干净：残留的【冒烟】数据会被 check_english 的「夹具残留」扫描判红
    # （exit 2），那是全仓门禁 —— 证据落在 results.json 与 stdout 里，不靠留在库里。
    if args.keep:
        print('（--keep：保留夹具，任务 id=%s ｜ 模板见上面 G0/H0 读数）' % fx['tid'])
    else:
        pu = purge_fixtures()
        print('（夹具已清：任务 %s ｜ 模板 %s）' % (pu[0] or '无', pu[1] or '无'))
        note('Z1', '夹具清理（默认口径；--keep 才保留）', '任务 %s / 模板 %s'
             % (pu[0] or '无', pu[1] or '无'))
    _dump()
    print('')
    print('== 汇总 == 断言 %d 条：PASS %d / FAIL %d'
          % (len(rows), len(rows) - len(failed), len(failed)))
    if failed:
        for r in failed:
            print('   FAIL #%s %s | %s' % (r['no'], r['name'], r['detail'][:200]))
        return 1
    print('全绿。')
    return 0


def _dump():
    RESULTS.write_text(json.dumps({
        'generated': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'mark': MARK, 'rows': rows}, ensure_ascii=False, indent=2),
        encoding='utf-8')
    print('（结果已落盘 %s）' % RESULTS.name)


if __name__ == '__main__':
    sys.exit(main())
