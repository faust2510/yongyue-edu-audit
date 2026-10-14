#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 课程中心内嵌只读周课表 —— 真机门禁 + 改前/改后取证。

设计：docs/plans/study-scheduling-design.md §7.2（P0，3 处改动）、§8（V1–V3、V13）。

判据（每条都对应设计文档里写死的一条验收，不放宽、不只看 HTTP 200）：
  V1  /my/study 的「本周课表」课节集合 == 该角色数据域的 op.session 集合（SQL oracle，
      逐条比对 日期/科目/起始时刻），不是「有这块 DOM」就算过；
  V2  同一角色同一周：/my/study 的集合 == /student/timetable?view=week 的集合
      （多集相等，按 科目+起止 计）—— 这条是「口径与既有课表同源」的防漂移断言；
  V3  零写路径：区块内不得有 form/POST；整轮前后 op_session 与
      op_session_op_student_rel 行数不变；/my/study 页面不得出现 method="post"
      的表单落在本区块内；
  V4  三角色（学生/教师/家长）各自的数据域口径 = 既有 C1 口径：
      学生=档案班、教师=本人任教、家长=孩子档案班合集、教务=全校只读。

【为什么要有 --capture】用户要求「正反双向自证」：既要证明改后看得见，也要保留
改前看不见的原始证据。同一把量具在改动前后各跑一次，改前 FAIL / 改后 PASS，
比任何文字描述都硬。--capture 只抓取落盘、不做断言。

【夹具纪律】本仓 2026-09-18 有过代理误删别人夹具的事故。本脚本：
  ① 只建、只删**自己创建的那一条** op.session（记下 id，按 id 精确删除）；
  ② 建之前用 SQL 断言该时段对 batch 8 / faculty 43 无重叠（避免触发基座四查）；
  ③ 删之后断言 leftover = 0（该 id 不存在 + op_session 总数回到建前读数）。
  为什么必须造这一节：本地 stu@local 的档案班（batch 8）真实排课数据截止
  2026-09-18，**当前周本来就是空的** —— 不造一节，「学生页非空且与课表页逐条
  相同」这条就永远只能拿到 0==0 的弱证据。

用法：
  python3 tests/smoke/study_week_schedule.py                 # 全量断言（含夹具）
  python3 tests/smoke/study_week_schedule.py --capture before  # 只抓取落盘（改前证据）
  python3 tests/smoke/study_week_schedule.py --no-fixture      # 只读模式（不建夹具）
退出码：0=全绿；1=有断言失败；2=运行错误（环境不可用）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault('NO_PROXY', 'localhost,127.0.0.1')
os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
os.environ['no_proxy'] = 'localhost,127.0.0.1'

try:
    import requests
except ImportError:  # pragma: no cover
    print('FATAL | 需要 requests'); sys.exit(2)

BASE = os.environ.get('SMOKE_BASE', 'http://localhost:8069')
DB = os.environ.get('EDU_DB_NAME', 'edu19')
DB_CONTAINER = os.environ.get('EDU_DB_CONTAINER', 'edu19-clone-db-1')
REPO = Path(__file__).resolve().parent.parent.parent
OUT = Path(__file__).resolve().parent / 'out_study_week'

USERS = {
    'stu': ('stu@local', 'demo123', '学生'),
    'fac': ('faculty@local', 'demo123', '教师'),
    'par': ('parent@local', 'demo123', '家长'),
    'bo': ('backoffice@local', 'demo123', '教务'),
}
ROLE_ORDER = ['stu', 'fac', 'par', 'bo']

FIXTURE_SUBJECT = 35          # batch 8 真实在上的科目之一（本地实测 41 节）
FIXTURE_BATCH = 8             # stu@local 的档案班（预备科 · 2026级【演示】）
# faculty 17 = faculty@local 本人的教师档案（batch 8 真实任课教师之一）——
# 故意选**真教师**而不是「待定」(43)：同一节夹具因此同时落在
#   学生（batch_id=8）/ 家长（孩子的档案班=8）/ 教师（faculty_id=17）
# 三个角色的数据域里 ⇒ 一节夹具就能证明三种角色都「看得见」，
# 且都能与既有 /student/timetable 逐条对上。
# 代价：基座 create() 会为该教师的账号加一条 mail.followers（由 unlink 清理，
# 断言 leftover=0 —— 见 V7-f）。
FIXTURE_FACULTY = 17
FIXTURE_TYPE = 'lecture'

RESULTS = []


def check(no, name, ok, detail=''):
    RESULTS.append({'no': no, 'name': name, 'pass': bool(ok), 'detail': str(detail)[:900]})
    print('  [%s] %-4s %s%s' % ('PASS' if ok else 'FAIL', no, name,
                                (' | ' + str(detail)[:600]) if detail else ''))
    return bool(ok)


def note(msg):
    print('  ---- %s' % msg)


# ---------------------------------------------------------------- 环境
def psql(sql):
    out = subprocess.run(['docker', 'exec', DB_CONTAINER, 'psql', '-U', 'odoo',
                          '-d', DB, '-tAc', sql],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError('psql 失败：' + (out.stderr or '').strip()[:300])
    return out.stdout.strip()


def pscalar(sql):
    return int(psql(sql) or 0)


def login(user, pwd):
    s = requests.Session()
    s.trust_env = False
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    try:
        r = s.post(BASE + '/web/session/authenticate', timeout=30, json={
            'jsonrpc': '2.0', 'method': 'call',
            'params': {'db': DB, 'login': user, 'password': pwd}})
        uid = ((r.json() or {}).get('result') or {}).get('uid')
    except Exception as exc:
        print('  登录异常 %s: %s' % (user, exc)); uid = None
    return (s, uid) if uid else (None, None)


def get(sess, url):
    r = sess.get(BASE + url, timeout=60, allow_redirects=True)
    return r.status_code, r.text


def strip_tags(html):
    txt = re.sub(r'(?is)<(script|style).*?</\1>', ' ', html or '')
    txt = re.sub(r'(?s)<[^>]+>', ' ', txt)
    for a, b in (('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
                 ('&#39;', "'"), ('&quot;', '"'), ('&ndash;', '\u2013')):
        txt = txt.replace(a, b)
    return re.sub(r'\s+', ' ', txt)


# ---------------------------------------------------------------- 抽取
BLOCK_MARK = 'data-ux3-week="1"'
_ATTR = re.compile(r'([a-zA-Z0-9_\-]+)="([^"]*)"')


def extract_week_block(html):
    """取 /my/study 的「本周课表」区块 HTML；不存在返回 None。"""
    i = html.find(BLOCK_MARK)
    if i < 0:
        return None
    start = html.rfind('<div', 0, i)
    j = html.find('<div class="ux3-section"', i)
    return html[start:(j if j > 0 else len(html))]


def week_block_rows(block):
    """区块 → [(日期 iso, 科目, 起始 HH:MM, 结束 HH:MM)]（按渲染顺序）。"""
    rows = []
    if not block:
        return rows
    segs = block.split('<div class="ux3-row ux3-week-day"')
    for seg in segs[1:]:
        m = re.search(r'data-day="([^"]+)"', seg)
        day = m.group(1) if m else '?'
        for tag in re.findall(r'<span class="ux3-week-ses"([^>]*)>', seg):
            a = dict(_ATTR.findall(tag))
            rows.append((day, a.get('data-subject', ''),
                         a.get('data-start', ''), a.get('data-end', '')))
    return rows


def timetable_rows(html):
    """既有 /student/timetable 页 → {(科目, 起始, 结束)} 多集（页面自身即口径 oracle）。

    该页每节课渲染为：<div class="fw-bold">科目</div><div class="opacity-75">
    <span>HH:MM</span>–<span>HH:MM</span></div>（loose 桶同形）。
    """
    pat = re.compile(
        r'<div class="fw-bold">([^<]*)</div>\s*'
        r'<div class="opacity-75">\s*<span>(\d\d:\d\d)</span>\u2013<span>(\d\d:\d\d)</span>')
    return [(m.group(1), m.group(2), m.group(3)) for m in pat.finditer(html or '')]


# ---------------------------------------------------------------- SQL oracle
def oracle(login_name):
    """按既有 C1 口径算该账号「本周应看到的课节」：[(日期 iso, 科目, 起始 HH:MM)]。

    口径逐条对齐 custom_addons/edu_portal/controllers/scheduling.py:148-171：
      教师 faculty_id / 学生 档案班 batch_id / 家长 孩子档案班合集 / 内部 全校只读。
    周窗口 = week_utils.week_window_utc(monday_of(今天本地), 用户 tz)，state != cancel。
    """
    row = psql("select u.id, coalesce(p.tz,'') from res_users u "
               "join res_partner p on p.id=u.partner_id where u.login='%s'" % login_name)
    uid, tzname = (row.split('|') + ['', ''])[:2]
    uid = int(uid)
    tz = ZoneInfo(tzname or 'UTC')
    now_utc = datetime.strptime(psql('select now() at time zone \'UTC\''),
                                '%Y-%m-%d %H:%M:%S.%f')
    today_local = now_utc.replace(tzinfo=timezone.utc).astimezone(tz).date()
    monday = today_local - timedelta(days=today_local.weekday())
    ws = datetime(monday.year, monday.month, monday.day, tzinfo=tz).astimezone(timezone.utc)
    we = ws + timedelta(days=7)

    fac = pscalar("select coalesce(max(id),0) from op_faculty where partner_id in "
                  "(select partner_id from res_users where id=%d) "
                  "or partner_id in (select id from res_partner where user_id=%d)" % (uid, uid))
    stu = pscalar("select coalesce(max(id),0) from op_student where user_id=%d "
                  "or partner_id in (select partner_id from res_users where id=%d)" % (uid, uid))
    # op.parent 的伙伴字段是 name（m2o res.partner，核心模型如此）——见
    # edu_schedule/models/identity.py PROFILE_CHAINS['op.parent']
    par = pscalar("select coalesce(max(id),0) from op_parent where user_id=%d "
                  "or name = (select partner_id from res_users where id=%d)" % (uid, uid))

    where = []
    if fac:
        where.append('s.faculty_id=%d' % fac)
        scope = 'faculty_id=%d' % fac
    elif stu:
        b = pscalar("select coalesce(max(batch_id),0) from op_student_course "
                    "where student_id=%d and state='running'" % stu)
        if not b:
            b = pscalar("select coalesce(max(batch_id),0) from op_student_course "
                        "where student_id=%d" % stu)
        where.append('s.batch_id=%d' % b)
        scope = 'batch_id=%d' % b
    elif par:
        rel = "select student_id from op_parent_op_student_rel where op_parent_id=%d" % par
        sc = ("select batch_id from op_student_course where student_id in (%s) "
              "and state='running'" % rel)
        if pscalar('select count(*) from (%s) t' % sc) == 0:
            sc = ("select batch_id from op_student_course where student_id in (%s)" % rel)
        bs = [r for r in psql('select distinct batch_id from (%s) t where batch_id is not null' % sc).splitlines() if r]
        where.append('s.batch_id in (%s)' % (','.join(bs) if bs else '0'))
        scope = 'batch_id in (%s)' % (','.join(bs) if bs else '0')
    else:
        scope = '全校（只读）'
    dom = ('s.state <> \'cancel\' and s.start_datetime < \'%s\' and s.end_datetime >= \'%s\''
           % (we.strftime('%Y-%m-%d %H:%M:%S'), ws.strftime('%Y-%m-%d %H:%M:%S')))
    if where:
        dom += ' and ' + ' and '.join(where)
    rows = psql("select s.start_datetime, su.name from op_session s "
                "left join op_subject su on su.id=s.subject_id where %s "
                "order by s.start_datetime" % dom)
    exp = []
    for line in [x for x in rows.splitlines() if x.strip()]:
        dt_s, name = (line.split('|') + [''])[:2]
        dt = datetime.strptime(dt_s, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        loc = dt.astimezone(tz)
        exp.append((loc.date().isoformat(), name, loc.strftime('%H:%M')))
    return {'uid': uid, 'tz': tzname or 'UTC', 'monday': monday.isoformat(),
            'scope': scope, 'expected': exp, 'window_utc': (ws, we)}


# ---------------------------------------------------------------- 夹具
def shell(code, timeout=420):
    cmd = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
           '-c', '/etc/odoo/odoo.conf', '--db_host=db', '--db_port=5432',
           '--db_user=odoo', '--db_password=odoo', '-d', DB, '--no-http']
    out = subprocess.run(cmd, input=code, capture_output=True, text=True,
                         timeout=timeout, cwd=str(REPO))
    return (out.stdout or '') + (out.stderr or '')


def kv(blob, key):
    m = re.search(r'^' + re.escape(key) + r'=(.*)$', blob or '', re.M)
    return m.group(1).strip() if m else None


def fixture_slot(window_utc):
    """在周窗口内挑一个对 batch/faculty 都无重叠的 45 分钟槽（周四优先）。"""
    ws, we = window_utc
    for day_off, hour in ((3, 10), (3, 20), (4, 10), (2, 20), (1, 10)):
        st = ws + timedelta(days=day_off, hours=hour - 0)
        en = st + timedelta(minutes=45)
        if not (ws <= st and en <= we):
            continue
        clash = pscalar(
            "select count(*) from op_session where state<>'cancel' and "
            "start_datetime < '%s' and end_datetime > '%s' and "
            "(batch_id=%d or faculty_id=%d)"
            % (en.strftime('%Y-%m-%d %H:%M:%S'), st.strftime('%Y-%m-%d %H:%M:%S'),
               FIXTURE_BATCH, FIXTURE_FACULTY))
        if clash == 0:
            return st, en
    return None, None


def create_fixture(st, en):
    code = (
        "S = env['op.session']\n"
        "rec = S.create({'name': 'P0WEEKDemo', 'course_id': 18,\n"
        "  'batch_id': %d, 'faculty_id': %d, 'subject_id': %d,\n"
        "  'start_datetime': '%s', 'end_datetime': '%s',\n"
        "  'state': 'draft', 'type': '%s'})\n"
        "env.cr.commit()\n"
        "print('FIX_ID=%%s' %% rec.id)\n"
        % (FIXTURE_BATCH, FIXTURE_FACULTY, FIXTURE_SUBJECT,
           st.strftime('%Y-%m-%d %H:%M:%S'), en.strftime('%Y-%m-%d %H:%M:%S'),
           FIXTURE_TYPE))
    return shell(code)


def drop_fixture(fix_id):
    """删夹具并**把库还原**：ORM unlink（可能留下 mail.followers）+ 强制清残。

    FOL_AUTO = unlink 之后 ORM 自己没清掉、需要本脚本补删的 follower 行数。
    """
    code = ("S = env['op.session'].browse(%d)\n"
            "if S.exists():\n"
            "    S.unlink()\n"
            "env.cr.commit()\n"
            "F = env['mail.followers']\n"
            "dom = [('res_model', '=', 'op.session'), ('res_id', '=', %d)]\n"
            "left = F.search(dom)\n"
            "print('FOL_AUTO=%%s' %% len(left))\n"
            "left.unlink()\n"
            "env.cr.commit()\n"
            "print('LEFT_ROW=%%s' %% env['op.session'].search_count([('id', '=', %d)]))\n"
            "print('LEFT_FOL=%%s' %% F.search_count(dom))\n"
            % (fix_id, fix_id, fix_id))
    return shell(code)


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--capture', metavar='LABEL', default=None,
                    help='只抓取落盘、不做断言（改前/改后取证）')
    ap.add_argument('--label', default='after', help='断言模式下落盘目录名')
    ap.add_argument('--no-fixture', action='store_true', help='不建夹具（只读）')
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    work = OUT / (args.capture or args.label)
    work.mkdir(parents=True, exist_ok=True)

    print('== P0 课程中心内嵌只读周课表 · 真机取证/门禁 ==')
    print('   base=%s db=%s 输出=%s' % (BASE, DB, work))

    # 前置读数（V3 要断言整轮不变）
    sess_before = pscalar('select count(*) from op_session')
    rel_before = pscalar('select count(*) from op_session_op_student_rel')
    print('   op_session=%d  op_session_op_student_rel=%d' % (sess_before, rel_before))

    # oracle 先算（夹具会改变读数，故 oracle 在夹具存在时重算）
    oracles = {}
    pages = {}
    for key in ROLE_ORDER:
        login_name, pwd, zh = USERS[key]
        sess, uid = login(login_name, pwd)
        if not sess:
            print('FATAL | 登录失败：%s' % login_name); return 2
        st_my, html_my = get(sess, '/my/study')
        st_tt, html_tt = get(sess, '/student/timetable?view=week')
        (work / ('%s_my_study.html' % key)).write_text(html_my, encoding='utf-8')
        (work / ('%s_timetable.html' % key)).write_text(html_tt, encoding='utf-8')
        pages[key] = {'my': html_my, 'tt': html_tt, 'st_my': st_my, 'st_tt': st_tt}
        oracles[key] = oracle(login_name)
        note('%s(%s) /my/study=%s /student/timetable=%s 期望课节=%d 实测区块课节=%d'
             % (zh, login_name, st_my, st_tt, len(oracles[key]['expected']),
                len(week_block_rows(extract_week_block(html_my)))))
        print('     数据域=%s  tz=%s  周一起=%s'
              % (oracles[key]['scope'], oracles[key]['tz'], oracles[key]['monday']))

    # R1 真实数据测量（只读）：档案班 vs 合班批，同一周
    r1 = r1_measure(oracles['stu'])

    summary = {
        'when': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'op_session_before': sess_before,
        'op_session_op_student_rel_before': rel_before,
        'roles': {k: {'expected_n': len(oracles[k]['expected']),
                      'expected': oracles[k]['expected'],
                      'scope': oracles[k]['scope'], 'tz': oracles[k]['tz'],
                      'monday': oracles[k]['monday'],
                      'block_rows_n': len(week_block_rows(extract_week_block(pages[k]['my'])))}
                  for k in ROLE_ORDER},
        'r1': r1,
    }

    if args.capture:
        print('\n== --capture %s：只抓取，不做断言 ==' % args.capture)
        for k in ROLE_ORDER:
            block = extract_week_block(pages[k]['my'])
            print('   [%s] 区块存在=%s 区块课节=%d 期望=%d'
                  % (k, block is not None, len(week_block_rows(block)),
                     len(oracles[k]['expected'])))
        (work / '_summary.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
        print('   已落盘：%s' % work)
        return 0

    # ---------------- 断言 ----------------
    print('\n-- V1/V4 各角色「本周课表」区块存在 + 逐条等于 SQL oracle --')
    for k in ROLE_ORDER:
        block = extract_week_block(pages[k]['my'])
        check('V1-%s' % k, 'V4 %s 页存在「本周课表」区块' % USERS[k][2], block is not None,
              '未找到 %s（改前状态）' % BLOCK_MARK)
        if block is None:
            continue
        rows = week_block_rows(block)
        exp = oracles[k]['expected']
        got_flat = [(d, s, t) for (d, s, t, _e) in rows]
        check('V1-%s-b' % k, '%s 逐条等于该角色数据域（%s）' % (USERS[k][2], oracles[k]['scope']),
              sorted(got_flat) == sorted(exp),
              '页面=%s 期望=%s' % (json.dumps(got_flat, ensure_ascii=False),
                                   json.dumps(exp, ensure_ascii=False)))
        # 可见文本必须与 data-* 一致（不许属性一套、眼睛看另一套）
        vis = strip_tags(block)
        miss = [s for (_d, s, _t, _e) in rows if s and s not in vis]
        check('V1-%s-c' % k, '%s 区块可见文本含每条科目名' % USERS[k][2], not miss, str(miss))

    print('\n-- V2 与既有 /student/timetable 同源（多集相等：科目+起止）--')
    for k in ROLE_ORDER:
        block = extract_week_block(pages[k]['my'])
        mine = sorted((s, st_, en) for (_d, s, st_, en) in week_block_rows(block or ''))
        theirs = sorted(timetable_rows(pages[k]['tt']))
        extra = [x for x in mine if x not in theirs]
        lack = [x for x in theirs if x not in mine]
        check('V2-%s' % k, '%s /my/study 与 /student/timetable 逐条相同' % USERS[k][2],
              mine == theirs,
              '差集 只在我页=%s 只在课表页=%s（同页课节数 mine=%d theirs=%d）'
              % (json.dumps(extra, ensure_ascii=False), json.dumps(lack, ensure_ascii=False),
                 len(mine), len(theirs)))

    print('\n-- V3 零写路径 --')
    for k in ROLE_ORDER:
        block = extract_week_block(pages[k]['my']) or ''
        check('V3-%s-a' % k, '%s 区块内无表单/POST' % USERS[k][2],
              ('<form' not in block.lower()) and ('method="post"' not in block.lower()))
    # ⚠ 设计 §8 V3 的原话是「/my/study 页面**没有任何** POST 表单」——实测**不成立**：
    #   既有门户壳 edu_page 自带一个头像上传表单（POST /my/avatar/upload），
    #   改前 1 个、改后 1 个（见 out_study_week/before/*.html）。
    #   「不许为了好看而放宽断言」的反面同样成立：**不许把一个与事实不符的断言
    #   写成通过**。故这里换成两条更硬的判据：
    #     ① 页面上 POST 表单的 action 集合 ⊆ 既有壳的 action 集合，且逐条相同；
    #     ② 有改前基线时，改后 POST 表单数必须与改前**完全相等**（P0 一个没加）。
    FORM_RE = re.compile(r'<form[^>]*method="post"[^>]*>', re.I)
    ACN_RE = re.compile(r'action="([^"]*)"')
    SHELL_POST_ACTIONS = ['/my/avatar/upload']
    for k in ROLE_ORDER:
        acts = [ACN_RE.search(f).group(1) if ACN_RE.search(f) else '(无 action)'
                for f in FORM_RE.findall(pages[k]['my'])]
        check('V3-%s-b' % k, '%s 页 POST 表单只来自既有门户壳（P0 未新增写入口）'
              % USERS[k][2], sorted(acts) == sorted(SHELL_POST_ACTIONS),
              'POST action=%s' % json.dumps(acts, ensure_ascii=False))
    base_dir = OUT / 'before'
    if base_dir.is_dir():
        n_after = len(FORM_RE.findall(pages['stu']['my']))
        n_before = sum(len(FORM_RE.findall(f.read_text(encoding='utf-8')))
                       for f in [base_dir / 'stu_my_study.html']
                       if f.is_file())
        check('V3-b2', '学生页 POST 表单数与改前完全相等（改前 %d）' % n_before,
              n_after == n_before, '改后=%d 改前=%d' % (n_after, n_before))
    else:
        note('无改前基线（%s 不存在），跳过 POST 表单数对拍' % base_dir)

    print('\n-- V5 出口（P0-3）：完整课表 / 订阅 --')
    for k in ROLE_ORDER:
        block = extract_week_block(pages[k]['my']) or ''
        check('V5-%s' % k, '%s 两个出口都指向既有页' % USERS[k][2],
              ('/student/timetable?view=week' in block) and ('/my/calendar' in block))

    print('\n-- V6 R1 班级断点：如实呈现（只读测量，不做断言判红）--')
    print('   %s' % r1['verdict'])

    # ---------------- 夹具三段 ----------------
    if args.no_fixture:
        print('\n-- 夹具：--no-fixture，跳过 --')
    else:
        print('\n-- V7 夹具三段：造一节真课 → 读产物 → 还原 leftover=0 --')
        st, en = fixture_slot(oracles['stu']['window_utc'])
        if not st:
            check('V7-a', '周窗口内找到无冲突时段', False, '五个候选槽全部冲突')
        else:
            note('夹具时段 %s → %s（学生 tz=%s）'
                 % (st.strftime('%Y-%m-%d %H:%M'), en.strftime('%H:%M'), oracles['stu']['tz']))
            blob = create_fixture(st, en)
            fix_id = kv(blob, 'FIX_ID')
            check('V7-a', '夹具课节创建成功（op.session id 已记下）', bool(fix_id),
                  blob[-600:] if not fix_id else 'id=%s' % fix_id)
            if fix_id:
                fix_id = int(fix_id)
                try:
                    subj = psql('select name from op_subject where id=%d' % FIXTURE_SUBJECT)
                    loc = st.replace(tzinfo=timezone.utc).astimezone(
                        ZoneInfo(oracles['stu']['tz']))
                    want = (loc.date().isoformat(), subj, loc.strftime('%H:%M'))
                    # 夹具存在期间，四个角色全部重测一遍：既证「各自看得见这一节」，
                    # 又证「含这一节之后仍与既有课表页逐条相同」。
                    for key in ROLE_ORDER:
                        sess, _uid = login(*USERS[key][:2])
                        _s, html_my = get(sess, '/my/study')
                        _s2, html_tt = get(sess, '/student/timetable?view=week')
                        (work / ('%s_my_study_fixture.html' % key)).write_text(
                            html_my, encoding='utf-8')
                        (work / ('%s_timetable_fixture.html' % key)).write_text(
                            html_tt, encoding='utf-8')
                        rows = week_block_rows(extract_week_block(html_my))
                        got = [(d, s, t) for (d, s, t, _e) in rows]
                        ora2 = oracle(USERS[key][0])['expected']
                        check('V7-b-%s' % key,
                              '%s 含夹具时非空且逐条等于该角色数据域' % USERS[key][2],
                              len(ora2) >= 1 and sorted(got) == sorted(ora2),
                              '期望(%d)=%s 实得(%d)=%s'
                              % (len(ora2), json.dumps(ora2, ensure_ascii=False),
                                 len(got), json.dumps(got, ensure_ascii=False)))
                        check('V7-b2-%s' % key,
                              '%s 页含夹具那一节（日期+科目+时刻逐条命中）' % USERS[key][2],
                              want in got, '期望=%s' % json.dumps(list(want), ensure_ascii=False))
                        ttr = [r for r in timetable_rows(html_tt)
                               if r[0] == subj and r[1] == loc.strftime('%H:%M')]
                        check('V7-c-%s' % key,
                              '%s 同一节在既有 /student/timetable 也出现（同源）'
                              % USERS[key][2], bool(ttr),
                              '课表页对=%s' % json.dumps(ttr, ensure_ascii=False))
                        mine = sorted((s, a, b) for (_d, s, a, b) in rows)
                        theirs = sorted(timetable_rows(html_tt))
                        check('V7-d-%s' % key, '%s 含夹具后两页仍逐条相同' % USERS[key][2],
                              mine == theirs, 'mine=%d theirs=%d' % (len(mine), len(theirs)))
                finally:
                    blob2 = drop_fixture(fix_id)
                    left_row = kv(blob2, 'LEFT_ROW')
                    left_fol = kv(blob2, 'LEFT_FOL')
                    check('V7-e', '还原：该 id 已不存在（leftover=0）',
                          left_row == '0', 'LEFT_ROW=%s' % left_row)
                    check('V7-f', '还原：mail.followers 无残留',
                          left_fol == '0', 'LEFT_FOL=%s' % left_fol)

    # ---------------- V3 行数不变 ----------------
    sess_after = pscalar('select count(*) from op_session')
    rel_after = pscalar('select count(*) from op_session_op_student_rel')
    check('V3-c', '整轮前后 op_session 行数不变 (%d)' % sess_before,
          sess_after == sess_before, 'after=%d before=%d' % (sess_after, sess_before))
    check('V3-d', '整轮前后 op_session_op_student_rel 行数不变 (%d)' % rel_before,
          rel_after == rel_before, 'after=%d before=%d' % (rel_after, rel_before))

    summary['op_session_after'] = sess_after
    summary['op_session_op_student_rel_after'] = rel_after
    summary['results'] = RESULTS
    (work / '_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                        encoding='utf-8')
    n_pass = sum(1 for r in RESULTS if r['pass'])
    print('\n== %d/%d PASS ==  证据：%s' % (n_pass, len(RESULTS), work))
    return 0 if n_pass == len(RESULTS) else 1


def r1_measure(orc):
    """R1「班级断点」：档案班 vs 合班批 —— 学生课表只含档案班精确匹配的课节。"""
    ws, we = orc['window_utc']
    win = ("start_datetime < '%s' and end_datetime >= '%s' and state<>'cancel'"
           % (we.strftime('%Y-%m-%d %H:%M:%S'), ws.strftime('%Y-%m-%d %H:%M:%S')))
    names = {}
    for line in psql('select id, coalesce(name::text, code::text) from op_batch').splitlines():
        if '|' in line:
            i, n = line.split('|', 1); names[int(i)] = n
    per = {}
    for line in psql('select batch_id, count(*) from op_session where %s '
                     'group by 1 order by 1' % win).splitlines():
        if '|' in line:
            b, c = line.split('|', 1); per[int(b)] = int(c)
    # 档案班学生（本库仅 stu@local 一人有 running 档案）与其班
    stu_batch = pscalar("select coalesce(max(batch_id),0) from op_student_course "
                        "where state='running'")
    empty_batches = [b for b in sorted(names) if b not in per]
    text = ('R1 实测（本周窗口 %s → %s，只读 SQL）：有课的班 %s；'
            '全库 %d 个班里 %d 个本周零课节（%s）；'
            'stu@local 的档案班=%s(%s) 本周 %d 节。'
            '合班批（B1234/B34 之类）的课节**只对挂在该批下的课节生效**，'
            '档案班学生看不到 —— 本实现如实呈现，不做合班展开。'
            % (ws.strftime('%m-%d %H:%MZ'), we.strftime('%m-%d %H:%MZ'),
               json.dumps({names.get(b, b): c for b, c in per.items()}, ensure_ascii=False),
               len(names), len(empty_batches),
               json.dumps([names.get(b, b) for b in empty_batches], ensure_ascii=False),
               stu_batch, names.get(stu_batch, '?'), per.get(stu_batch, 0)))
    return {'per_batch': {names.get(b, str(b)): c for b, c in per.items()},
            'empty_batches': [names.get(b, str(b)) for b in empty_batches],
            'stu_batch': stu_batch, 'stu_batch_name': names.get(stu_batch, ''),
            'stu_week_n': per.get(stu_batch, 0), 'verdict': text}


if __name__ == '__main__':
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print('FATAL | %s' % exc); sys.exit(2)
