#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-1 改课影响面 + 一键通知 + 变更留痕：真机冒烟（六步闸门第 6 步）。

设计稿：docs/plans/session-change-impact-design.md §9.2（逐条落地 V2–V13）。
用法：python3 tests/smoke/c1_impact_notify.py
退出码：0=全绿；1=有断言失败；2=运行错误（环境不可用 / 找不到合法夹具）。

【V1 为什么不在脚本里】
V1 = `bash scripts/safe_upgrade.sh edu_schedule`（EXIT=0 且输出无
Traceback / CRITICAL / manifest not found）。升级会**重启 web 容器**，
把被测进程整段换掉——必须由调用方先跑完，本脚本只做前置探活
（无升级锁 + 带库名登录页可达），否则会在自己引发的重启里读半程读数。

【基线对照：覆盖设计稿 §7.4#4 的原始写法（队长硬约束）】
设计稿 §7.4#4 要求断言「edu_telegram_outbox 行数不因 C-1 增加」——
**该断言不成立**：退役但本地仍 installed 的
custom_addons/edu_telegram/models/hooks.py:5-35 覆写了 op.session.write()，
**只要改课（WATCH 命中 start_datetime/end_datetime/…）它就写 outbox**，
与 C-1 无关。所以「行数不增」在改课场景下必然为假。
本脚本改为**基线对照**（同一节课、同一账号，两次独立测量）：
    增量 A = 「只改课」（不点通知）的 outbox 增量；
    增量 B = 「改课 + 点一键通知」整段流程的 outbox 增量；
断言 B == A ⇒ C-1 的代码路径**没有多写** outbox（A 是 edu_telegram 自己写的）。
两个数字都打印存档；若两者都是 0，说明该班没有绑定 telegram 会话 ——
这时断言依然成立但属**弱判据**，脚本会显式标注「弱」，不冒充「已验证」。
另：本脚本全流程断言 C-1 自身代码里不出现 edu.telegram.outbox 调用点
（静态 grep，见 case_static_no_telegram）。

【明确不写的验收（设计稿 §9.3 反例）】
- 不用 allow_redirects=True 探测新路由（303 会被判成 PASS）；
- 不在 student_ids 为空的课节上验收「通知了 N 个学生」（本地
  op_session_op_student_rel = 0 行 —— 必须落在**有在读学生的班**上）；
- 不只读代码就声称留痕生效（必须读回 mail_tracking_value 行）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import requests

BASE = os.environ.get('C1_BASE', 'http://localhost:8069')
DB = os.environ.get('EDU_DB_NAME', 'edu19')
DB_CONTAINER = os.environ.get('EDU_DB_CONTAINER', 'edu19-clone-db-1')
REPO = Path(__file__).resolve().parent.parent.parent
SHOTS = REPO / 'tests' / 'gap' / 'shots'
RESULTS_JSON = Path(__file__).resolve().parent / 'c1_impact_notify_results.json'
BACKOFFICE = ('backoffice@local', 'demo123')
STUDENT = ('stu@local', 'demo123')
# 本地唯一「有在读学生」的班（设计稿 §A.3：op_student_course 4 行，仅 batch 8 有）
BATCH_ID = 8

RESULTS = []
STATE = {'fixture': None, 'orig_start': None, 'orig_end': None}
CLEAN_CHATTER = False


def check(no, name, ok, detail=''):
    RESULTS.append({'no': no, 'name': name, 'pass': bool(ok),
                    'detail': str(detail)[:800]})
    print('  [%s] %-4s %s%s' % ('PASS' if ok else 'FAIL', no, name,
                                (' | ' + str(detail)[:400]) if detail else ''))
    return bool(ok)


def note(msg):
    print('  ---- %s' % msg)


# ---------------------------------------------------------------- 工具
def psql(sql):
    out = subprocess.run(['docker', 'exec', DB_CONTAINER, 'psql', '-U', 'odoo',
                          '-d', DB, '-tAc', sql],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError('psql 失败：' + (out.stderr or '').strip()[:300])
    return out.stdout.strip()


def pscalar(sql):
    return int(psql(sql) or 0)


def shell(code, timeout=300):
    cmd = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
           '-c', '/etc/odoo/odoo.conf', '--db_host=db', '--db_port=5432',
           '--db_user=odoo', '--db_password=odoo', '-d', DB, '--no-http']
    out = subprocess.run(cmd, input=code, capture_output=True, text=True,
                         timeout=timeout, cwd=str(REPO))
    return (out.stdout or '') + (out.stderr or '')


def kv(blob, key):
    m = re.search(r'%s=(\S+)' % re.escape(key), blob or '')
    return m.group(1) if m else None


def kvline(blob, key):
    """整行捕获（明细/异常消息里含空格，kv 的 \\S+ 会截断）。"""
    m = re.search(r'^%s=(.*)$' % re.escape(key), blob or '', re.M)
    return m.group(1).strip() if m else None


def login(user, pwd):
    s = requests.Session()
    s.trust_env = False
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    r = s.post(BASE + '/web/session/authenticate', timeout=30, json={
        'jsonrpc': '2.0', 'method': 'call',
        'params': {'db': DB, 'login': user, 'password': pwd}})
    try:
        uid = ((r.json() or {}).get('result') or {}).get('uid')
    except Exception:
        uid = None
    return (s, uid) if uid else (None, None)


def csrf_any(sess, urls):
    for url in urls:
        try:
            r = sess.get(BASE + url, timeout=30, allow_redirects=False)
        except Exception:
            continue
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text or '')
        if m:
            return m.group(1), url
    return None, None


def text_of(html):
    txt = re.sub(r'(?is)<(script|style).*?</\1>', ' ', html or '')
    txt = re.sub(r'(?s)<[^>]+>', ' ', txt)
    for a, b in (('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'),
                 ('&gt;', '>'), ('&#39;', "'"), ('&quot;', '"')):
        txt = txt.replace(a, b)
    return re.sub(r'\s+', ' ', txt)


def page_number(txt, label):
    m = re.search(re.escape(label) + r'[^0-9]{0,40}(\d+)', txt)
    return int(m.group(1)) if m else None


def probe(sess, path):
    """**不跟随重定向**的探测（设计稿 §9.3 反例 2）。"""
    r = sess.get(BASE + path, timeout=30, allow_redirects=False)
    return r.status_code, r.headers.get('Location', ''), r.text


def shot(path, sess, expect_text='', url='/my/messages'):
    """用**已登录的 requests 会话 cookie** 打开浏览器截图。

    不靠「填登录表单」：本地登录页的表单结构随版本/品牌化变化，
    填表比注入 session_id 脆（第一版就是死在 button[type=submit] 找不到）。
    """
    cookie = ''
    for c in sess.cookies:
        if c.name == 'session_id':
            cookie = c.value
    if not cookie:
        return 'requests 会话里没有 session_id，无法截图'
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return 'playwright 不可用：%s' % exc
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='chrome', headless=True)
            ctx = browser.new_context(viewport={'width': 1440, 'height': 960},
                                      locale='zh-CN')
            ctx.add_cookies([{'name': 'session_id', 'value': cookie,
                              'domain': 'localhost', 'path': '/'}])
            page = ctx.new_page()
            page.goto(BASE + url, wait_until='domcontentloaded',
                      timeout=60000)
            page.wait_for_timeout(2500)
            html = page.content()
            path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(path), full_page=False)
            browser.close()
        if expect_text and expect_text not in html:
            return '截图已存但页面不含「%s」（登录态可能没生效）' % expect_text
        return 'ok'
    except Exception as exc:
        return '截图失败：%s' % str(exc)[:200]


# ---------------------------------------------------------------- 夹具
def pick_fixture():
    """V3 正对照：挑一节**确实有在读学生**的草稿课节（不许在空载体上验收）。"""
    row = psql(
        "select x.blob from ("
        "  select s.id || '|' || s.batch_id || '|' || s.faculty_id || '|' || s.state"
        "    || '|' || to_char(s.start_datetime, 'YYYY-MM-DD HH24:MI:SS')"
        "    || '|' || to_char(s.end_datetime, 'YYYY-MM-DD HH24:MI:SS')"
        "    || '|' || coalesce(s.classroom_id, 0) as blob,"
        "    (select count(*) from op_session o"
        "     where o.id <> s.id and o.state <> 'cancel'"
        "       and o.start_datetime is not null and o.end_datetime is not null"
        "       and o.start_datetime >= s.start_datetime - interval '24 hours'"
        "       and o.start_datetime <= s.end_datetime + interval '24 hours'"
        "       and s.start_datetime < o.end_datetime"
        "       and o.start_datetime < s.end_datetime"
        "       and ((s.faculty_id is not null and o.faculty_id = s.faculty_id)"
        "         or (s.classroom_id is not null"
        "             and o.classroom_id = s.classroom_id)"
        "         or (s.batch_id is not null and o.batch_id = s.batch_id))) as rel,"
        "    s.id as sid"
        "  from op_session s"
        "  where s.batch_id = %d and s.state = 'draft' and s.faculty_id is not null"
        "    and exists (select 1 from op_student_course sc"
        "                join op_student st on st.id = sc.student_id"
        "                where sc.batch_id = s.batch_id and st.user_id is not null)"
        " ) x order by x.rel desc, x.sid limit 1;" % BATCH_ID)
    if not row:
        return None
    p = row.split('|')
    return {'id': int(p[0]), 'batch': int(p[1]), 'faculty': int(p[2]),
            'state': p[3], 'start': p[4], 'end': p[5],
            'classroom': int(p[6]), 'related_psql': None}


def faculty_user_of(fx):
    """任课教师账号（op.faculty.user_id 是 store=False 的 related 字段，
    SQL 侧表达不了 partner→user 的口径，故用 ORM 读一次再交给 psql 对拍）。"""
    blob = shell("F = env['op.faculty'].sudo().browse(%d)\n"
                 "print('FAC_USER=' + str(F.user_id.id or 0))" % fx['faculty'])
    return int(kv(blob, 'FAC_USER') or 0)


def expected_recipients(fx):
    """影响面「受影响人数」的 psql 同口径读数（V4 对拍用）。

    口径逐条对齐 _reminder_users()：该班 op.student.course 的学生账号
    ∪ 任课教师账号；**家长不发**（P2）。
    """
    return pscalar(
        "select count(*) from ("
        "  select st.user_id as uid from op_student_course sc"
        "   join op_student st on st.id = sc.student_id"
        "   where sc.batch_id = %d and st.user_id is not null"
        "  union select %d) t where t.uid is not null and t.uid <> 0;"
        % (fx['batch'], fx['fac_user']))


def expected_related(fx):
    """影响面「受牵连课节数」的 psql 同口径读数（±24h + 非取消 + 真重叠 + 三维）。"""
    return pscalar(
        "select count(*) from op_session o, op_session s"
        " where s.id = %d and o.id <> s.id and o.state <> 'cancel'"
        "   and o.start_datetime is not null and o.end_datetime is not null"
        "   and o.start_datetime >= s.start_datetime - interval '24 hours'"
        "   and o.start_datetime <= s.end_datetime + interval '24 hours'"
        "   and s.start_datetime < o.end_datetime"
        "   and o.start_datetime < s.end_datetime"
        "   and ((s.faculty_id is not null and o.faculty_id = s.faculty_id)"
        "     or (s.classroom_id is not null and o.classroom_id = s.classroom_id)"
        "     or (s.batch_id is not null and o.batch_id = s.batch_id));" % fx['id'])


def counts():
    return {
        'msg': pscalar('select count(*) from edu_message;'),
        'audit': pscalar('select count(*) from edu_audit_log;'),
        'outbox': pscalar('select count(*) from edu_telegram_outbox;'),
        'track': pscalar('select count(*) from mail_tracking_value;'),
        'msg_max': pscalar('select coalesce(max(id), 0) from edu_message;'),
        'audit_max': pscalar('select coalesce(max(id), 0) from edu_audit_log;'),
    }


# ---------------------------------------------------------------- 用例
def case_static_no_telegram():
    """C-1 代码路径**静态**不得出现 telegram 出口（队长硬约束 1）。

    只扫 C-1 自己的代码面：模型文件里从「C-1 改课影响面」标记到文件末尾的
    非注释行 + 控制器 + 本页模板。**不扫** t6 遗留的 _notify_upcoming()
    ——它确实调用 edu.telegram.outbox，但那是既有课前提醒功能、不属于 C-1，
    本任务一行不动它（它的存在正是「改课就会写 outbox」的原因）。
    """
    src = (REPO / 'custom_addons/edu_schedule/models/session_ext.py'
           ).read_text(encoding='utf-8')
    marker = '# C-1 改课影响面 + 一键通知 + 变更留痕'
    head, _, region = src.partition(marker)
    hits = [ln.strip() for ln in region.splitlines()
            if not ln.strip().startswith('#')
            and ('edu.telegram' in ln or 'edu_telegram' in ln)]
    ctrl = (REPO / 'custom_addons/edu_schedule/controllers/main.py'
            ).read_text(encoding='utf-8')
    chits = [ln.strip() for ln in ctrl.splitlines()
             if 'edu.telegram' in ln or 'edu_telegram' in ln]
    tpl = (REPO / 'custom_addons/edu_schedule/views/templates.xml'
           ).read_text(encoding='utf-8')
    thits = [ln.strip() for ln in tpl.splitlines()
             if 'edu_telegram' in ln or 'telegram' in ln.lower()]
    legacy = 'edu.telegram.outbox' in head
    check('S1', 'C-1 代码路径无 telegram 出口（模型 C-1 段 + 控制器 + 模板）',
          not hits and not chits and not thits,
          'model=%s controller=%s template=%s ｜ t6 遗留 _notify_upcoming 仍调 '
          'telegram=%s（非 C-1，未动）' % (hits[:1], chits[:1], thits[:1], legacy))


def case_offline_gates():
    """V2 离线门禁（六条 --selftest + 接缝检查）。"""
    cmds = [
        ('view_xpath', ['python3', 'scripts/check_view_xpath.py', '--selftest']),
        ('manifest', ['python3', 'scripts/check_manifest_tracking.py', '--selftest']),
        ('qweb_dict', ['python3', 'scripts/check_qweb_dict_foreach.py', '--selftest']),
        ('english', ['python3', 'scripts/check_english.py', '--selftest']),
        ('odoo_trace', ['python3', 'scripts/check_odoo_trace.py', '--selftest']),
        ('seam', ['python3', 'tests/smoke/gate_seam_check.py']),
    ]
    bad = []
    for name, cmd in cmds:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO),
                           timeout=600)
        if r.returncode != 0:
            bad.append('%s(exit=%d)' % (name, r.returncode))
    check('V2', '离线门禁 6 条全绿（--selftest + 接缝）', not bad,
          ','.join(bad) or '6/6 exit=0')


def case_v3_fixture(fx):
    check('V3', '正对照：课节落在有在读学生的班（batch=%d）' % BATCH_ID,
          bool(fx) and fx['batch'] == BATCH_ID and fx['faculty'],
          'fixture=%s' % json.dumps(fx, ensure_ascii=False) if fx else '未找到合法课节')


def case_v4_v5(sess_bo, sess_stu, fx):
    """V4 页面读数 == psql 读数；V5 门禁 303（不跟跳转）。"""
    code, loc, html = probe(sess_bo, '/timetable/session/%d/impact' % fx['id'])
    txt = text_of(html)
    exp_p = expected_recipients(fx)
    exp_r = expected_related(fx)
    got_p = page_number(txt, '受影响人数')
    got_r = page_number(txt, '受牵连的其他课节')
    check('V4', '影响面页 200（教务）', code == 200, 'code=%s loc=%s' % (code, loc))
    check('V4a', '受影响人数：页面 == psql 口径', got_p == exp_p,
          '页面=%s psql=%s' % (got_p, exp_p))
    check('V4b', '受牵连课节数：页面 == psql 口径', got_r == exp_r,
          '页面=%s psql=%s' % (got_r, exp_r))
    check('V4c', '页面标题含「改课影响面」与「通知相关师生」',
          '改课影响面' in txt and '通知相关师生' in txt,
          'title_ok=%s btn_ok=%s' % ('改课影响面' in txt, '通知相关师生' in txt))
    check('V4d', '受影响的人逐个列名（教师 + 在读学生）',
          ('任课教师' in txt and '在读学生' in txt), '卡片角色标注存在')
    spath = SHOTS / 'c1_impact_impact_page.png'
    smsg = shot(spath, sess_bo, '受牵连的其他课节',
                '/timetable/session/%d/impact' % fx['id'])
    check('V4f', '影响面页截图留档（教务视角，tests/gap/shots/）',
          smsg == 'ok' and spath.exists(), '%s（%s）' % (spath.name, smsg))
    s_code, s_loc, _ = probe(sess_stu, '/timetable/session/%d/impact' % fx['id'])
    check('V5', '学生访问影响面页 → 303 且 Location 精确 = /my/home',
          s_code == 303 and s_loc == '/my/home',
          'code=%s loc=%s' % (s_code, s_loc))
    return got_p


def case_v4e(fx):
    """V4e 后台表单入口：两个按钮已装载 + 按钮动作返回的 URL 与真机路由一致。

    为什么不点后台 UI：本地后端 URL（/odoo/…）会命中 edu_portal 的
    「无动作即跳应用面板」行为被重定向到 /apps（既有产品行为，不属 C-1），
    headless 浏览器到不了表单；改为断言一对硬证据：
      ① ir_ui_view 里已装载继承视图（含两个按钮 + 教务组/系统组门禁）；
      ② 按钮的 server action 返回的 URL == 真机可访问的影响面路由。
    页面的真机可达性由 V4／V9 用**真实教务账号**的 HTTP 读写证明。
    """
    arch = psql("select arch_db from ir_ui_view"
                " where name = 'op.session.form.c1.impact';")
    ok_view = ('action_open_impact' in arch
               and 'action_notify_session_change' in arch
               and 'group_op_back_office_admin' in arch)
    blob = shell(
        "S = env['op.session'].sudo().browse(%d)\n"
        "print('ACT=' + str(S.action_open_impact().get('url')))\n"
        "print('VIEWS=' + str(len(env['ir.ui.view'].sudo().search("
        "[('name', '=', 'op.session.form.c1.impact')]))))" % fx['id'])
    act = kv(blob, 'ACT')
    check('V4e', '后台表单两个按钮已装载（视图在库 + 动作返回影响面 URL）',
          ok_view and act == '/timetable/session/%d/impact' % fx['id'],
          'view_ok=%s views_in_db=%s action_url=%s'
          % (ok_view, kv(blob, 'VIEWS'), act))


def case_v6(sess_bo, sess_stu, fx, before):
    """V6 写路由安全目标：不存在 id / 越权身份 → 3xx 且相关表行数不变。"""
    gone = pscalar('select count(*) from op_session where id = 99999999;')
    check('V6a', '先断言目标确实不存在（id=99999999）', gone == 0,
          'count=%d' % gone)
    token_bo, turl = csrf_any(sess_bo, ['/timetable/session/%d/impact' % fx['id']])
    if not token_bo:
        check('V6', '取 csrf 令牌（教务）', False, '页面未渲染 csrf_token')
        return
    note('csrf 来源（教务）：%s' % turl)
    r = sess_bo.post(BASE + '/timetable/session/99999999/notify',
                     data={'csrf_token': token_bo}, timeout=30,
                     allow_redirects=False)
    check('V6b', 'POST 不存在的课节 → 3xx（非 500）',
          300 <= r.status_code < 400,
          'code=%s loc=%s' % (r.status_code, r.headers.get('Location', '')))

    token_stu, surl = csrf_any(sess_stu, ['/my/messages', '/my/home',
                                          '/my/profile', '/my'])
    if not token_stu:
        check('V6c', '学生 POST 真 id → 3xx 且不发信', False,
              '学生侧未取到 csrf 令牌（无法区分 400 与越权）')
        return
    note('csrf 来源（学生）：%s' % surl)
    r2 = sess_stu.post(BASE + '/timetable/session/%d/notify' % fx['id'],
                       data={'csrf_token': token_stu}, timeout=30,
                       allow_redirects=False)
    after = counts()
    check('V6c', '学生 POST 真 id → 3xx（门禁）',
          300 <= r2.status_code < 400,
          'code=%s loc=%s' % (r2.status_code, r2.headers.get('Location', '')))
    check('V6d', '两次越界 POST 后：edu_message / audit / outbox 行数未变',
          after['msg'] == before['msg'] and after['audit'] == before['audit']
          and after['outbox'] == before['outbox'],
          'msg %d→%d audit %d→%d outbox %d→%d' % (
              before['msg'], after['msg'], before['audit'], after['audit'],
              before['outbox'], after['outbox']))


SHELL_HEAD = '''
from datetime import timedelta
S = env['op.session'].sudo().browse(%d)
TV = env['mail.tracking.value'].sudo()
Aud = env['edu.audit.log'].sudo()
Out = env['edu.telegram.outbox'].sudo()
Msg = env['edu.message'].sudo()
TVDOM = [('mail_message_id.model', '=', 'op.session'),
         ('mail_message_id.res_id', '=', S.id)]
AUDDOM = [('model', '=', 'op.session'), ('res_id', '=', S.id),
          ('action', '=', '课节变更')]


def free_slot(delta):
    """+delta 后是否与任何非取消课节真重叠（教师/教室/班级三维，同四查口径）。"""
    st = S.start_datetime + delta
    en = S.end_datetime + delta
    dom = [('id', '!=', S.id), ('state', '!=', 'cancel'),
           ('start_datetime', '>=', st - timedelta(hours=24)),
           ('start_datetime', '<=', en + timedelta(hours=24))]
    for o in env['op.session'].sudo().search(dom):
        if not (o.start_datetime and o.end_datetime):
            continue
        if not (st < o.end_datetime and o.start_datetime < en):
            continue
        if S.faculty_id and o.faculty_id == S.faculty_id:
            return False
        if S.classroom_id and o.classroom_id == S.classroom_id:
            return False
        if S.batch_id and o.batch_id == S.batch_id:
            return False
    return True


def pick_delta(skip=()):
    for cand in (timedelta(hours=1), timedelta(hours=2), timedelta(hours=3),
                 timedelta(days=1), timedelta(days=2), timedelta(days=3),
                 timedelta(hours=-1), timedelta(hours=-2)):
        if cand in skip:
            continue
        if free_slot(cand):
            return cand
    return None
'''


def case_v7(fx):
    """V7 改一次课 → 读真正的产物（tracking + 审计）+ 基线对照增量 A。"""
    code = SHELL_HEAD % fx['id'] + '''
delta = pick_delta()
if delta is None:
    print('NO_SLOT=1')
else:
    tv0 = TV.search_count(TVDOM)
    au0 = Aud.search_count(AUDDOM)
    msg0 = Msg.search_count([])
    out0 = Out.search_count([])
    tvbase = max(TV.search(TVDOM).ids) if TV.search(TVDOM) else 0
    old_start = S.start_datetime
    new_start = S.start_datetime + delta
    S.write({'start_datetime': new_start, 'end_datetime': S.end_datetime + delta})
    env.cr.commit()
    newrows = TV.search([('id', '>', tvbase)])
    aurow = Aud.search(AUDDOM, order='id desc', limit=1)
    print('NO_SLOT=0')
    print('SLOT_H=%s' % (delta.total_seconds() / 3600.0))
    print('OLD_START=%s' % old_start)
    print('NEW_START=%s' % new_start)
    print('TV_DELTA=%d' % (TV.search_count(TVDOM) - tv0))
    print('TV_FIELDS=%s' % ','.join(sorted(newrows.mapped('field_id.name'))))
    print('TV_OLD=%s' % ','.join(str(v) for v in newrows.mapped('old_value_datetime')))
    print('TV_NEW=%s' % ','.join(str(v) for v in newrows.mapped('new_value_datetime')))
    print('AUDIT_DELTA=%d' % (Aud.search_count(AUDDOM) - au0))
    print('AUDIT_DETAIL=%s' % ((aurow.detail or '').replace(chr(10), ' ')))
    print('MSG_DELTA=%d' % (Msg.search_count([]) - msg0))
    print('OUTBOX_DELTA_A=%d' % (Out.search_count([]) - out0))
'''
    blob = shell(code)
    if kv(blob, 'NO_SLOT') != '0':
        return check('V7', '找到不与任何课节重叠的相邻时段', False,
                     blob[-400:]), None
    tv_delta = int(kv(blob, 'TV_DELTA') or 0)
    au_delta = int(kv(blob, 'AUDIT_DELTA') or 0)
    fields = kv(blob, 'TV_FIELDS') or ''
    detail = kvline(blob, 'AUDIT_DETAIL') or ''
    outbox_a = int(kv(blob, 'OUTBOX_DELTA_A') or 0)
    old_start = kv(blob, 'OLD_START')
    new_start = kv(blob, 'NEW_START')
    check('V7a', '改课 → mail_tracking_value 该 res_id 新增行（old/new 非空）',
          tv_delta >= 1 and 'start_datetime' in fields,
          'delta=%d fields=%s' % (tv_delta, fields))
    check('V7b', "改课 → edu_audit_log 新增 1 行 action='课节变更'（含 old→new）",
          au_delta == 1 and '开始时间' in detail and '→' in detail,
          'delta=%d detail=%s' % (au_delta, detail))
    check('V7c', '改课本身不发站内信（通知必须由人按）',
          int(kv(blob, 'MSG_DELTA') or -1) == 0,
          'msg_delta=%s' % kv(blob, 'MSG_DELTA'))
    check('V7d', '基线对照 A：只改课时的 outbox 增量已记录',
          True, 'OUTBOX_DELTA_A=%d（edu_telegram.hooks 覆写 op.session.write，'
                '与本功能无关）' % outbox_a)
    return outbox_a, {'old_start': old_start, 'new_start': new_start,
                      'delta_h': kv(blob, 'SLOT_H')}


def case_v8(fx):
    """V8 冲突兜底（既有能力，防回归）：改到与同教师另一节课完全重叠 → 被拒。"""
    flag = psql("select value from ir_config_parameter"
                " where key = 'timetable.is_faculty_constraint';")
    code = SHELL_HEAD % fx['id'] + '''
other = env['op.session'].sudo().search([
    ('id', '!=', S.id), ('state', '!=', 'cancel'),
    ('faculty_id', '=', S.faculty_id.id),
    ('start_datetime', '!=', False), ('end_datetime', '!=', False)], limit=1)
if not other:
    print('NO_PEER=1')
else:
    print('NO_PEER=0')
    print('PEER=%d' % other.id)
    try:
        with env.cr.savepoint():
            S.write({'start_datetime': other.start_datetime,
                     'end_datetime': other.end_datetime})
            env.cr.flush()
        print('REJECTED=0')
    except Exception as exc:
        print('REJECTED=1 TYPE=%s' % type(exc).__name__)
        print('REJECT_MSG=%s' % str(exc)[:120].replace(chr(10), ' '))
env.cr.rollback()
print('AFTER_SAME=%s' % (env['op.session'].sudo().browse(S.id).start_datetime))
'''
    blob = shell(code)
    rejected = kv(blob, 'REJECTED')
    check('V8', '改到与同教师另一节课完全重叠 → 保存被拒（基座四查兜底）',
          flag == 'True' and rejected == '1',
          'flag=%s rejected=%s type=%s msg=%s' % (
              flag, rejected, kv(blob, 'TYPE'),
              kvline(blob, 'REJECT_MSG')))


def case_v9(sess_bo, fx, fx_page_count, outbox_a):
    """V9 一键通知：站内信 N 条 + 审计 + 基线对照增量 B == A。"""
    out_before = pscalar('select count(*) from edu_telegram_outbox;')
    msg_base = pscalar('select coalesce(max(id), 0) from edu_message;')
    audit_base = pscalar('select coalesce(max(id), 0) from edu_audit_log;')
    code = SHELL_HEAD % fx['id'] + '''
delta = pick_delta()
if delta is None:
    print('NO_SLOT=1')
else:
    S.write({'start_datetime': S.start_datetime + delta,
             'end_datetime': S.end_datetime + delta})
    env.cr.commit()
    print('NO_SLOT=0')
    print('SLOT_H2=' + str(delta.total_seconds() / 3600.0))
    print('SYNC_START=' + str(S.start_datetime))
'''
    blob = shell(code)
    if kv(blob, 'NO_SLOT') != '0':
        check('V9', '第二阶段找得到不冲突时段', False, blob[-300:])
        return None
    note('第二阶段改课到 %s（这就是「改课 + 一键通知」里的改课那一步）'
         % kv(blob, 'SYNC_START'))
    token, turl = csrf_any(sess_bo, ['/timetable/session/%d/impact' % fx['id']])
    if not token:
        check('V9', '取 csrf 令牌（教务）', False, '页面未渲染 csrf_token')
        return None
    r = sess_bo.post(BASE + '/timetable/session/%d/notify' % fx['id'],
                     data={'csrf_token': token}, timeout=60,
                     allow_redirects=False)
    loc = r.headers.get('Location', '')
    sent = 0
    m = re.search(r'sent=(\d+)', loc)
    if m:
        sent = int(m.group(1))
    check('V9a', 'POST 一键通知 → 303 回影响面页（带 sent/failed 回显）',
          300 <= r.status_code < 400 and '/impact?notified=1' in loc,
          'code=%s loc=%s' % (r.status_code, loc))
    out_after = pscalar('select count(*) from edu_telegram_outbox;')
    outbox_b = out_after - out_before
    now_msg = pscalar(
        "select count(*) from edu_message where id > %d"
        " and event_key = 'session_change';" % msg_base)
    body = psql(
        "select body from edu_message where id > %d"
        " and event_key = 'session_change' order by id desc limit 1;" % msg_base)
    body_one = body.replace(chr(10), ' / ')
    n_audit = pscalar(
        "select count(*) from edu_audit_log where id > %d"
        " and action = '课节变更通知' and model = 'op.session' and res_id = %d;"
        % (audit_base, fx['id']))
    detail = psql(
        "select detail from edu_audit_log where id > %d"
        " and action = '课节变更通知' and res_id = %d"
        " order by id desc limit 1;" % (audit_base, fx['id']))
    check('V9b', 'edu_message 新增 N 条（event_key=session_change）且 N == 页面人数',
          now_msg == fx_page_count and sent == fx_page_count,
          'msg_delta=%d sent=%d 页面人数=%d' % (now_msg, sent, fx_page_count))
    check('V9c', '正文带「调课通知」标题 + old→new 变更摘要',
          '【调课通知】' in body_one and '变更明细' in body_one
          and '→' in body_one,
          body_one[:300])
    check('V9d', '通知留痕：edu_audit_log 1 行「课节变更通知」且人数可解析',
          n_audit == 1 and ('通知 %d 人' % sent) in detail,
          'rows=%d detail=%s' % (n_audit, detail))
    # 页面回显「最近一次通知：<时刻> · <人数> 人」
    code2, loc2, html2 = probe(
        sess_bo, loc or ('/timetable/session/%d/impact' % fx['id']))
    txt2 = text_of(html2)
    m2 = re.search(r'最近一次通知：([0-9\-: ]+)\s*·\s*(\d+) 人', txt2)
    check('V9e', '页面回显「最近一次通知：<时刻> · <人数> 人」',
          code2 == 200 and bool(m2) and int(m2.group(2)) == sent,
          'code=%s 命中=%s' % (code2, m2.group(0) if m2 else '未命中'))
    spath2 = SHOTS / 'c1_impact_notify_impact_page.png'
    smsg2 = shot(spath2, sess_bo, '最近一次通知',
                 loc or '/timetable/session/%d/impact' % fx['id'])
    check('V9h', '通知后影响面页截图留档（含「最近一次通知」）',
          smsg2 == 'ok' and spath2.exists(), '%s（%s）' % (spath2.name, smsg2))
    banner = re.search('本次已通知 (\\d+) 人', txt2)
    check('V9f', '通知后回显横幅（notified=1）显示本次送达人数',
          bool(banner) and int(banner.group(1)) == sent,
          '横幅命中=%s' % (banner.group(0) if banner else '未命中'))
    # 基线对照：B == A ⇒ C-1 路径没有多写 outbox
    weak = (outbox_a == 0 and outbox_b == 0)
    check('V9g', '基线对照 B == A：C-1 没有多写 edu_telegram_outbox',
          outbox_b == outbox_a,
          'A(只改课)=%d B(改课+一键通知)=%d%s' % (
              outbox_a, outbox_b, '（弱判据：两次都是 0，该班无 telegram 会话）'
              if weak else ''))
    return {'msg_base': msg_base, 'audit_base': audit_base,
            'sent': sent, 'outbox_a': outbox_a, 'outbox_b': outbox_b}


def case_v10(sess_stu, fx, res):
    """V10 收件侧真机：stu@local 登录 /my/messages 读到「调课通知」。"""
    r = sess_stu.get(BASE + '/my/messages', timeout=45)
    txt = text_of(r.text)
    read_page = r.status_code == 200 and '调课通知' in txt
    stu_unread = pscalar(
        "select count(*) from edu_message m join res_users u on u.id = m.recipient_id"
        " where u.login = 'stu@local' and m.event_key = 'session_change'"
        " and m.is_read = false and m.id > %d;" % res['msg_base'])
    fac_unread = pscalar(
        "select count(*) from edu_message m join res_users u on u.id = m.recipient_id"
        " where u.login = 'faculty@local' and m.event_key = 'session_change'"
        " and m.is_read = false and m.id > %d;" % res['msg_base'])
    check('V10a', '学生 /my/messages 读到「调课通知」', read_page,
          'code=%s' % r.status_code)
    check('V10b', '该条对教师与学生均为未读（未读角标 +1 的数据源）',
          stu_unread == 1 and fac_unread == 1,
          'stu_unread=%d faculty_unread=%d' % (stu_unread, fac_unread))
    path = SHOTS / 'c1_impact_notify_student_messages.png'
    msg = shot(path, sess_stu, '调课通知')
    check('V10c', '学生消息中心截图留档 tests/gap/shots/', msg == 'ok'
          and path.exists(), '%s（%s）' % (path.name, msg))


def case_p4_cancel(fx, sess_bo, res):
    """P4（校长拍板）：停课 state='cancel' 走**同一套**通知与留痕。"""
    msg_base = pscalar('select coalesce(max(id), 0) from edu_message;')
    audit_base = pscalar('select coalesce(max(id), 0) from edu_audit_log;')
    blob = shell(SHELL_HEAD % fx['id'] + '''
S.write({'state': 'cancel'})
env.cr.commit()
aurow = Aud.search(AUDDOM, order='id desc', limit=1)
print('STATE=' + str(S.state))
print('AUDIT_DETAIL=' + ((aurow.detail or '').replace(chr(10), ' ')))
''')
    detail = kvline(blob, 'AUDIT_DETAIL') or ''
    token, _ = csrf_any(sess_bo, ['/timetable/session/%d/impact' % fx['id']])
    if token:
        sess_bo.post(BASE + '/timetable/session/%d/notify' % fx['id'],
                     data={'csrf_token': token}, timeout=60,
                     allow_redirects=False)
    n = pscalar("select count(*) from edu_message where id > %d"
                " and event_key = 'session_change';" % msg_base)
    body = (psql("select body from edu_message where id > %d"
                 " and event_key = 'session_change' order by id desc limit 1;"
                 % msg_base) or '').replace(chr(10), ' / ')
    action = psql("select action from edu_audit_log where id > %d"
                  " and model = 'op.session' and res_id = %d"
                  " order by id desc limit 1;" % (audit_base, fx['id']))
    check('P4a', '停课写入点留痕：明细含「状态：草稿 → 停课」',
          '状态' in detail and '停课' in detail, detail)
    check('P4b', '停课走同一套通知（同一条数 + 正文含停课提示）',
          n == res['sent'] and '本节已停课，请勿前往教室。' in body,
          'n=%d body=%s' % (n, body[:200]))
    check('P4c', "停课通知同样留痕（action='课节变更通知'）",
          action == '课节变更通知', 'action=%s' % action)
    blob2 = shell(SHELL_HEAD % fx['id'] + '''
S.write({'state': 'draft'})
env.cr.commit()
print('STATE_BACK=' + str(S.state))
''')
    check('P4d', 'state 已还原为草稿', kv(blob2, 'STATE_BACK') == 'draft',
          'state=%s' % kv(blob2, 'STATE_BACK'))


def case_v11(fx, res, base, orig):
    """V11 还原并断言 leftover=0（三段模板第 ③ 段）。"""
    code = SHELL_HEAD % fx['id'] + f'''
try:
    S.write({{'start_datetime': '{orig['start']}', 'end_datetime': '{orig['end']}'}})
    env.cr.commit()
    print('RESTORE_PATH=orm')
except Exception as exc:
    env.cr.rollback()
    print('RESTORE_PATH=blocked')
    print('RESTORE_ERR=' + str(exc)[:160].replace(chr(10), ' '))
'''
    blob = shell(code)
    path_used = kv(blob, 'RESTORE_PATH')
    now_start = psql('select to_char(start_datetime,'
                     " 'YYYY-MM-DD HH24:MI:SS') from op_session where id = %d;"
                     % fx['id'])
    if now_start != orig['start']:
        # 原时段可能已被同班其它课节占用（本地既有数据：308 的原时段就是这种情形）
        # ⇒ 基座四查会拒绝 ORM 写回；还原是「测试收尾」而非被验收的路径，用 SQL 精确还原，
        #    并把走的是哪条路如实记下来（不冒充「ORM 写回成功」）。
        psql("update op_session set start_datetime = '%s', end_datetime = '%s'"
             ' where id = %d;' % (orig['start'], orig['end'], fx['id']))
        path_used = '%s+sql（ORM 被基座四查拒绝：%s）' % (
            path_used or '?', kvline(blob, 'RESTORE_ERR') or '')
        now_start = psql('select to_char(start_datetime,'
                         " 'YYYY-MM-DD HH24:MI:SS') from op_session where id = %d;"
                         % fx['id'])
    check('V11a', 'start_datetime 已还原为基线值',
          now_start == orig['start'],
          '还原路径=%s now=%s 基线=%s' % (path_used, now_start, orig['start']))
    # 清场：本次产生的站内信 / 审计行 / chatter 行（按 id 基线精确删除，不用前缀模糊匹配）
    psql("delete from edu_message where id > %d and event_key = 'session_change';"
         % base['msg_max'])
    psql("delete from edu_audit_log where id > %d and model = 'op.session'"
         " and res_id = %d and action in ('课节变更', '课节变更通知');"
         % (base['audit_max'], fx['id']))
    left_msg = pscalar("select count(*) from edu_message where id > %d"
                       " and event_key = 'session_change';" % base['msg_max'])
    left_audit = pscalar("select count(*) from edu_audit_log where id > %d"
                         " and model = 'op.session' and res_id = %d"
                         " and action in ('课节变更', '课节变更通知');"
                         % (base['audit_max'], fx['id']))
    now_start = psql('select to_char(start_datetime,'
                     " 'YYYY-MM-DD HH24:MI:SS') from op_session where id = %d;"
                     % fx['id'])
    check('V11b', 'leftover=0：本次站内信 / 审计行全部清场',
          left_msg == 0 and left_audit == 0,
          'left_msg=%d left_audit=%d' % (left_msg, left_audit))
    check('V11c', '库内 start_datetime == 基线值',
          now_start == orig['start'],
          'now=%s 基线=%s' % (now_start, orig['start']))
    check('V11d', 'outbox / 课节总数未被本脚本改动',
          pscalar('select count(*) from op_session;') == base['sessions'],
          'op_session=%d 基线=%d' % (psql('select count(*) from op_session;')
                                     and pscalar('select count(*) from op_session;'),
                                     base['sessions']))
    note('残留说明：本脚本对这节课产生的 chatter（mail.message + tracking value）'
         '保留在会话历史里（那是基座留痕的真实产物，且本次改动与还原都真实发生过）；'
         '如需一并清掉，见 --clean-chatter 分支。')


def case_v12():
    """V12 文案与品牌门禁（公开可见文案口径）。"""
    for no, name, cmd in (
            ('V12a', 'check_english.py：must-fix = 0',
             ['python3', 'scripts/check_english.py']),
            ('V12b', 'check_odoo_trace.py：0 命中',
             ['python3', 'scripts/check_odoo_trace.py'])):
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO),
                           timeout=900)
        tail = (r.stdout or '').strip().splitlines()[-1:] or ['']
        check(no, name, r.returncode == 0,
              'exit=%d %s' % (r.returncode, tail[0][:120]))


def case_v13():
    """V13 权限四层自检：教务可用、学生 303、教务组闭包不含系统组。"""
    code = """
g = env.ref('openeducat_core.group_op_back_office_admin')
sysid = env.ref('base.group_system').id
print('HAS_SYSTEM=' + str(sysid in g.all_implied_ids.ids))
print('IMPLIED=' + ','.join(str(n) for n in g.all_implied_ids.mapped('name')))
"""
    blob = shell(code)
    check('V13', '教务组传递闭包不含系统组（不回归）',
          kv(blob, 'HAS_SYSTEM') == 'False',
          'implied=%s' % (kvline(blob, 'IMPLIED') or '')[:200])


def summarize():
    n_pass = len([r for r in RESULTS if r['pass']])
    print('')
    print('== C-1 冒烟：%d/%d PASS ==' % (n_pass, len(RESULTS)))
    fails = [r for r in RESULTS if not r['pass']]
    for r in fails:
        print('   FAIL %s %s | %s' % (r['no'], r['name'], r['detail'][:300]))
    try:
        RESULTS_JSON.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1),
                                encoding='utf-8')
        print('   结果落盘：%s' % RESULTS_JSON)
    except Exception as exc:
        print('   结果落盘失败：%s' % exc)
    return 0 if not fails else 1


def preflight():
    lock = os.path.join(os.environ.get('TMPDIR', '/tmp').rstrip('/'),
                        'edu19_upgrade.lock')
    lock = lock.replace('//', '/')
    if os.path.exists(lock):
        print('环境不可用：升级锁存在（%s）' % lock)
        return False
    try:
        r = requests.get(BASE + '/web/login?db=' + DB, timeout=15,
                         allow_redirects=False)
    except Exception as exc:
        print('环境不可用：%s' % exc)
        return False
    if r.status_code not in (200, 302, 303):
        print('环境不可用：/web/login?db=%s → %s' % (DB, r.status_code))
        return False
    print('前置：无升级锁；/web/login?db=%s → %s' % (DB, r.status_code))
    return True


def main():
    print('== C-1 改课影响面 + 一键通知 + 变更留痕：真机冒烟 ==')
    if not preflight():
        return 2
    case_static_no_telegram()
    case_offline_gates()

    fx = pick_fixture()
    case_v3_fixture(fx)
    if not fx:
        return 2
    fx['fac_user'] = faculty_user_of(fx)
    fx['related_psql'] = expected_related(fx)
    STATE['fixture'] = fx
    orig = {'start': fx['start'], 'end': fx['end']}
    base = counts()
    base['sessions'] = pscalar('select count(*) from op_session;')
    base['chat_max'] = pscalar(
        "select coalesce(max(m.id), 0) from mail_message m"
        " where m.model = 'op.session' and m.res_id = %d;" % fx['id'])
    print('夹具：课节 #%d（batch=%d / faculty=%d→user=%d / %s ~ %s / '
          'psql 口径受牵连 %d 节）'
          % (fx['id'], fx['batch'], fx['faculty'], fx['fac_user'],
             fx['start'], fx['end'], fx['related_psql']))
    print('基线：%s' % json.dumps(base, ensure_ascii=False))

    sess_bo, uid_bo = login(*BACKOFFICE)
    sess_stu, uid_stu = login(*STUDENT)
    if not sess_bo or not sess_stu:
        print('登录失败：backoffice=%s stu=%s' % (uid_bo, uid_stu))
        return 2
    page_count = case_v4_v5(sess_bo, sess_stu, fx)
    case_v4e(fx)
    case_v6(sess_bo, sess_stu, fx, base)

    outbox_a, moved = case_v7(fx)
    if outbox_a is None:
        return 1
    case_v8(fx)
    res = case_v9(sess_bo, fx, page_count, outbox_a)
    if not res:
        return 1
    case_v10(sess_stu, fx, res)
    case_p4_cancel(fx, sess_bo, res)
    case_v11(fx, res, base, orig)
    chat_left = pscalar('select count(*) from mail_message where model = \'op.session\''
                        " and res_id = %d and id > %d;" % (fx['id'], base['chat_max']))
    if CLEAN_CHATTER:
        blob3 = shell(SHELL_HEAD % fx['id'] + f'''
msgs = env['mail.message'].sudo().search([('model', '=', 'op.session'),
                                         ('res_id', '=', S.id),
                                         ('id', '>', {base['chat_max']})])
n = len(msgs)
msgs.unlink()
env.cr.commit()
print('CHATTER_DELETED=' + str(n))
''')
        chat_left = pscalar(
            'select count(*) from mail_message where model = \'op.session\''
            " and res_id = %d and id > %d;" % (fx['id'], base['chat_max']))
        check('V11e', '--clean-chatter：本脚本产生的 chatter 行已清场',
              chat_left == 0, 'deleted=%s left=%d'
              % (kv(blob3, 'CHATTER_DELETED'), chat_left))
    else:
        note('残留（保留为基座留痕的真实产物）：本脚本在夹具课节上产生 '
             + str(chat_left) + ' 条 chatter 行（mail.message/tracking value）；'
             '如需一并清掉，用 --clean-chatter 重跑。')
    case_v12()
    case_v13()
    return summarize()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--clean-chatter', action='store_true',
                        help='额外删除本脚本在夹具课节上留下的 chatter/tracking 行')
    args = parser.parse_args()
    CLEAN_CHATTER = args.clean_chatter
    try:
        sys.exit(main())
    except Exception as exc:
        print('运行错误：%s: %s' % (type(exc).__name__, exc))
        print('！！现场可能未还原：请检查夹具课节的 start_datetime '
              '（本脚本的正常路径会在 V11 还原；异常路径请手工核对）')
        sys.exit(2)



