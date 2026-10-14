#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t43 端到端越权实测：成绩入口 + 批量审批（可复跑）。

不变量（本轮踩坑固化，勿删）：
1. **只写自建夹具**：本脚本自建【冒烟】考试/考生/审批单；真实行只读。
   一次性评审可用事务内 rollback；可复跑脚本会被并发跑、也可能被中断在
   commit 之前——落在真实学生成绩行上就是污染。
2. **越权判据以 DB 未变为准**，不只看返回码（读回原值）。
3. **「不泄露存在性」比整个响应**（状态码+跳转+长度+关键文案）。
4. **「连跑两次一致」同时比 DB 终态**。
5. 构造不出的入口**如实写明实际观测行为**，不伪造路径。
6. leftover 用 active_test=False 复核（search() 默认过滤 archived）。
7. **升级锁路径必须三方同源**（t5）：本文件的 upgrade_lock_path() 与
   scripts/safe_upgrade.sh 的 LOCK=、scripts/check_view_xpath.py 的 _lock_path()
   解析规则必须一致（EDU_UPGRADE_LOCK 覆盖 ＞ TMPDIR 未设/空则 /tmp ＞ 固定名）。
   曾因本文件**硬编码** /tmp/edu19_upgrade.lock，在 macOS（TMPDIR=/var/folders/…/T）
   上永远看不见锁 —— 门没接上，"升级进行中跑冒烟"不会被拦（t5 修）。

用法：python3 tests/smoke/authz_endtoend_smoke.py
退出码：0 全绿；1 有失败；2 前置探活未过（环境问题，不伪装成断言失败）
"""
import json
import io
import os
import re
import subprocess
import sys
import time
import urllib.parse

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
ROOT = '.'
TAG = u'\u3010\u5192\u70df\u3011t43'
FAKE_ID = 99999991
ODOO = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
        '-c', '/etc/odoo/odoo.conf', '--db_host=db', '--db_port=5432',
        '--db_user=odoo', '--db_password=odoo', '-d', DB, '--no-http']

results, cannot, FAILED_ENDPOINTS = [], [], []
INTRUDER_LOGIN = 't43intruder@smoke.local'


def check(name, cond, detail=''):
    results.append(('PASS' if cond else 'FAIL', name, detail))
    print('  %-4s %-50s %s' % ('PASS' if cond else 'FAIL', name, detail))
    return cond


def shell(code, timeout=300):
    out = subprocess.run(ODOO, input=code, capture_output=True, text=True,
                         timeout=timeout, cwd=ROOT)
    return (out.stdout or '') + (out.stderr or '')


_FX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_fixtures.py')
try:
    with io.open(_FX_PATH, encoding='utf-8') as _fh:
        FIXTURE_SRC = _fh.read()
except OSError:
    FIXTURE_SRC = ''


def shell_fx(code, timeout=300):
    """把 tests/smoke/_fixtures.py 源码注入 shell 会话后再跑 code。

    共享夹具不依赖容器内仓库路径（源码宿主侧读出、拼进 stdin），
    因此在 odoo shell 里直接可用，无需配置 sys.path。
    """
    return shell(FIXTURE_SRC + '\n' + code, timeout=timeout)


def kv(blob, key):
    m = re.search(r'%s=(\S+)' % re.escape(key), blob)
    return m.group(1) if m else None


def login(user, pwd):
    s = requests.Session()
    s.trust_env = False
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': DB, 'login': user, 'password': pwd}}, timeout=25)
    return s if (r.json().get('result') or {}).get('uid') else None


def get_csrf(s, url):
    r = s.get(BASE + url, timeout=30)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    return m.group(1) if m else None


def resp_sig(r):
    """整响应签名：状态码 + 跳转目标 + 长度 + 是否含 traceback。"""
    loc = r.headers.get('Location') or ''
    return (r.status_code, loc.split('?')[0], len(r.content),
            'Traceback' in r.text)


UPGRADE_LOCK_ENV = 'EDU_UPGRADE_LOCK'


def upgrade_lock_path():
    """升级锁路径（t5 统一口径，**三方同源**）。

    解析顺序与 scripts/safe_upgrade.sh 的 LOCK=、scripts/check_view_xpath.py 的
    _lock_path() 完全一致：
       EDU_UPGRADE_LOCK 覆盖 ＞ TMPDIR（未设或为空 ⇒ /tmp）＞ 固定名 edu19_upgrade.lock

    ⚠ 历史坑（t5 修）：本函数原先**硬编码** '/tmp/edu19_upgrade.lock'，而 macOS 的
    TMPDIR=/var/folders/…/T ⇒ 与 safe_upgrade.sh 写的锁**不是同一个文件**，
    本 preflight 在这类机器上永远查不到锁（门没接上）：升级进行中跑本脚本不会被拦住，
    会拿到跨升级的"半程读数"。
    """
    return (os.environ.get(UPGRADE_LOCK_ENV)
            or os.path.join(os.environ.get('TMPDIR') or '/tmp',
                            'edu19_upgrade.lock'))


def preflight():
    # 锁是**目录**（safe_upgrade.sh 用 mkdir 原子占锁）；这里用 exists 而非 isdir，
    # 与 check_view_xpath._lock_state() 同判据：宁可多拦一次（fail-closed），
    # 不要因为"路径上是个文件"就当成无锁放行。
    lock = upgrade_lock_path()
    if os.path.exists(lock):
        print('PREFLIGHT: 升级锁存在（%s；他人升级中），请稍后重跑' % lock)
        return False
    try:
        # 本机探活**不得走系统代理**：requests 默认 trust_env=True 会读 macOS 系统代理，
        # 于是 localhost 也被代理掉 → 502 → 本 preflight 判「站点不可达」，
        # 整条 verify 在**站点健康**时也恒为 exit 2（t5 实测：curl=302 / requests=502，
        # 同一时刻同一 URL）。与本文件 login() 及 portal_regression_smoke.py 同口径。
        s = requests.Session()
        s.trust_env = False
        r = s.get(BASE + '/web/login?db=' + DB, timeout=15,
                  allow_redirects=False)
    except Exception as exc:
        print('PREFLIGHT: 站点不可达 %s' % exc); return False
    if r.status_code not in (200, 302, 303):
        print('PREFLIGHT: 探活返回 %s' % r.status_code); return False
    print('PREFLIGHT: OK（无锁 %s + 带库探活 %s）' % (lock, r.status_code))
    return True


BUILD = u"""
from odoo import fields
Ex = env['op.exam'].sudo().with_context(active_test=False)
Ex.search([('name', 'like', u'%(tag)s')]).unlink()
owner = env['op.faculty'].sudo().search([('user_id.login', '=', 'faculty@local')], limit=1)
# 越权方：本地没有第二个**活跃**教师账号（fac@local 用户已归档、无 user 绑定）
# → 按"只写自建夹具"原则自建，teardown 一并删除。
# 幂等清理顺序必须是 faculty → users → partner：
# 反序会撞 res.partner._unlink_except_user（"您不能删除与活动用户关联的联系人"）
env['op.faculty'].sudo().with_context(active_test=False).search(
    [('last_name', '=', u'越权教师')]).unlink()
IU = env['res.users'].sudo().with_context(active_test=False).search(
    [('login', '=', '%(ilogin)s')])
if IU:
    IU.unlink()
env['res.partner'].sudo().with_context(active_test=False).search(
    [('name', '=', u'%(tag)s 越权教师')]).unlink()
# 教师载体：统一走 tests/smoke/_fixtures.make_teacher（内部含
# 「必须能被 current_faculty() 解析」的前置断言，漏写 partner.user_id 必报错）
cleanup_teachers(env, u'%(tag)s', logins=['%(ilogin)s'])
intr = make_teacher(env, tag=u'%(tag)s', login='%(ilogin)s',
                    first_name=u'%(tag)s ', last_name=u'越权教师')
IU = intr.user_id
_look = teacher_lookup(env, IU.id)
print('INTR_FAC=' + str(intr.id) + ' INTR_USER=' + str(IU.id) +
      ' INTR_LOOKUP=' + str(_look.ids))
stu = env['op.student'].sudo().search([], limit=1)
sub = env['op.subject'].sudo().search([], limit=1)
crs = env['op.course'].sudo().search([], limit=1)
print('OWNER_FAC=%%d INTR_FAC=%%d OWNER_U=%%d INTR_U=%%d STU=%%d' %% (
    owner.id or 0, intr.id or 0, owner.user_id.id or 0, intr.user_id.id or 0, stu.id or 0))
# 夹具考试 responsible_id=OWNER 且 batch_id 留空 →
# 教师可见域 ['|', responsible_id in [fac], batch_id in taught_batches]
# 对越权方两条均不成立（不可见）；对属主第一条成立（可见）。
exam = Ex.create({
    'name': u'%(tag)s 越权夹具考试', 'exam_code': 'SMOKE-T43',
    'subject_id': sub.id, 'course_id': crs.id,
    'start_time': fields.Datetime.now(), 'end_time': fields.Datetime.now(),
    'total_marks': 100, 'min_marks': 60,
    'responsible_id': [(6, 0, [owner.id])]})
att = env['op.exam.attendees'].sudo().create({
    'exam_id': exam.id, 'student_id': stu.id, 'marks': 60, 'status': 'present'})
# 请假夹具（批量审批·请假 需要一条可被越权处置的目标；不伪造路径）
Lv = env['edu.leave'].sudo().with_context(active_test=False)
lv = Lv.create({'student_id': stu.id, 'state': 'request',
                'date_from': fields.Date.today(),
                'date_to': fields.Date.today(),
                'name': u'%(tag)s 请假'})
env.cr.commit()
# 申诉靶子（t75 追加项）：原先批量矩阵对 edu.grievance 走到 M.search([], limit=1)
# 兜底 → 靶子是**真实行**（实测 id=23）。共享靶子任何人动过就红、与用例无关，
# 而**假红与假绿一样消耗信任**。故自建一条带 TAG 的申诉；state 必须是**未终态**，
# 越权若得逞才会变成 resolve → 负例**可观察**。
gv = env['edu.grievance'].sudo().with_context(active_test=False).create({
    'name': u'%(tag)s 申诉', 'state': 'submitted',
    'description': u'【冒烟测试可删】批量审批越权靶子'})
env.cr.commit()
print('EXAM=%%d ATT=%%d MARKS=%%d LEAVE=%%d GRIEV=%%d' %% (
    exam.id, att.id, att.marks, lv.id, gv.id))
"""

DROP = u"""
Ex = env['op.exam'].sudo().with_context(active_test=False)
recs = Ex.search([('name', 'like', u'%(tag)s')])
env['op.result.line'].sudo().with_context(active_test=False).search(
    [('exam_id', 'in', recs.ids)]).unlink()
env['edu.leave'].sudo().with_context(active_test=False).search(
    [('name', 'like', u'%(tag)s')]).unlink()   # 请假夹具
env['edu.grievance'].sudo().with_context(active_test=False).search(
    [('name', 'like', u'%(tag)s')]).unlink()
env['op.exam.attendees'].sudo().with_context(active_test=False).search(
    [('exam_id', 'in', recs.ids)]).unlink()
recs.unlink()
_r = cleanup_teachers(env, u'%(tag)s', logins=['%(ilogin)s'])
print('CLEAN_TEACHER', _r)
env.cr.commit()
left = Ex.search([('name', 'like', u'%(tag)s')])
print('LEFTOVER_EXAM=%%d' %% len(left))
"""


# ---------------------------------------------------------------------------
# t75：自建合法【冒烟】选课单（t67 属主正对照的夹具）
#
# 为什么必须自建：库里 11 张注册单（10-19、72）**全部**带业务错误 SR0008
# （缺学生/课程/班级，或班级不属于该课程）→ 库里不存在「可被成功批准」的样本，
# 于是「越权 → ok=0」与「这条路批准不了任何单」**读数不可区分**。
#
# 关键设计（两处，都是想清楚才定下的）：
# 1. **作用域只看 student_id**（roles.approval_scope_domain 只返回 student_id 条件，
#    不约束 course/batch）→ 用**在作用域内的学生**(stu@local=学生5) 配
#    **自建课程/班级**，既进作用域，又只产生**新行**（该生此前没有这门课的档案），
#    因此全程不碰任何既有行。
# 2. **造两张单**：regA 给属主正对照（会被批准），regB 给越权负例。
#    只用一张的话，越权读数是在**已 approved** 的单上读的 —— 那时「状态没变」
#    既可能因为越权被拦、也可能因为已终态，**观察不到差别**。regB 保持 submitted，
#    越权若得逞就会变成 approved，负例才**可观察**。
T75_TAG = u'【冒烟】t75'

BUILD_T75 = u'''
T75 = u'%(tag)s'
Reg = env['op.subject.registration'].sudo().with_context(active_test=False)
Sub = env['op.subject'].sudo(); Crs = env['op.course'].sudo()
Bat = env['op.batch'].sudo(); SC = env['op.student.course'].sudo()
old = Reg.search([('course_id.name', 'like', T75)])
if old.mapped('course_id'):
    SC.with_context(active_test=False).search(
        [('course_id', 'in', old.mapped('course_id').ids)]).unlink()
old.unlink()
Bat.with_context(active_test=False).search([('name', 'like', T75)]).unlink()
Crs.with_context(active_test=False).search([('name', 'like', T75)]).unlink()
Sub.with_context(active_test=False).search([('name', 'like', T75)]).unlink()
env.cr.commit()
sub = Sub.create({'name': T75 + u' 科目', 'code': 'T75-SUB',
                  'subject_type': 'elective', 'type': 'theory'})
crs = Crs.create({'name': T75 + u' 课程', 'code': 'T75-CRS',
                  'evaluation_type': 'normal'})
crs.write({'subject_ids': [(6, 0, [sub.id])]})
bat = Bat.create({'name': T75 + u' 班级', 'code': 'T75-BAT', 'course_id': crs.id,
                  'start_date': '2026-01-01', 'end_date': '2027-01-01'})
env.cr.commit()
# 前置三行（在 shell 侧读，外层断言；审批行为本身是最终的端到端确认）
fac = env['op.faculty'].sudo().search([('user_id.login', '=', 'faculty@local')], limit=1)
batches = env['op.session'].sudo().search([('faculty_id', '=', fac.id)]).mapped('batch_id')
stu = SC.search([('batch_id', 'in', batches.ids)]).mapped('student_id')[:1]
print('T75_CRS=%%d T75_BAT=%%d T75_SUB=%%d T75_STU=%%d' %% (crs.id, bat.id, sub.id, stu.id if stu else 0))
print('T75_BIZ_OK=%%d' %% (1 if bat.course_id.id == crs.id else 0))
print('T75_STU_IN_SCOPE=%%d' %% (1 if stu else 0))
# 「是否改动既有行」的前置快照：该生**建单前**已有的档案 id 集合
print('T75_SC_BEFORE=%%s' %% ','.join(str(i) for i in SC.with_context(active_test=False).search([('student_id', '=', stu.id)]).ids) if stu else 'NONE')
'''

DROP_T75 = u'''
T75 = u'%(tag)s'
Reg = env['op.subject.registration'].sudo().with_context(active_test=False)
Crs = env['op.course'].sudo().with_context(active_test=False)
SC = env['op.student.course'].sudo().with_context(active_test=False)
crs = Crs.search([('name', 'like', T75)])
# 审批会为该生建档案（学生5 + 自建课）→ 按**反外键**先删档案，再删注册单/课程
SC.search([('course_id', 'in', crs.ids)]).unlink()
Reg.search([('course_id', 'in', crs.ids)]).unlink()
env['op.batch'].sudo().with_context(active_test=False).search(
    [('name', 'like', T75)]).unlink()
crs.unlink()
env['op.subject'].sudo().with_context(active_test=False).search(
    [('name', 'like', T75)]).unlink()
env.cr.commit()
print('T75_LEFT_REG=%%d' %% Reg.search_count([('course_id.name', 'like', T75)]))
print('T75_LEFT_SC=%%d' %% SC.search_count([('course_id.name', 'like', T75)]))
print('T75_LEFT_CRS=%%d' %% Crs.search_count([('name', 'like', T75)]))
# 「是否改动既有行」的后置读数：同一学生的档案 id 集合，应与 T75_SC_BEFORE 逐字一致
fac = env['op.faculty'].sudo().search([('user_id.login', '=', 'faculty@local')], limit=1)
bts = env['op.session'].sudo().search([('faculty_id', '=', fac.id)]).mapped('batch_id')
_stu = SC.search([('batch_id', 'in', bts.ids)]).mapped('student_id')[:1]
print('T75_SC_AFTER=%%s' %% ','.join(str(i) for i in SC.search([('student_id', '=', _stu.id)]).ids) if _stu else 'NONE')
'''


def bulk_counts(r):
    """从批量审批 302 的 Location 取 (ok, fail, skip)；取不到记为 None。"""
    loc = r.headers.get('Location') or ''
    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    def _i(k):
        v = (q.get(k) or [''])[0]
        return int(v) if v.isdigit() else None
    return _i('bulk_ok'), _i('bulk_fail'), _i('bulk_skip')


def marks_of(att_id):
    # 注意：外层用 + 拼接，别让 shell 代码里的 %s 与外层 % 格式化相撞
    code = ("a = env['op.exam.attendees'].sudo().browse(%d)\n" % att_id) + \
           "print('M=%s' % (a.marks if a.exists() else 'GONE'))\n"
    return kv(shell(code), 'M')


def fingerprint_of(model, rec_id):
    """「DB 未变」的强判据：state + write_date。

    只看 state 会漏掉「没改状态但改了别的字段」的写入 —— 而**任何**写入都会
    推进 write_date。故用它把「DB 未变」从**状态未变**升级为**行未被写过**。
    （t67 剩余矩阵项：DB 未变的行为断言，不只代码级推理。）
    """
    code = ("r = env['%s'].sudo().with_context(active_test=False).browse(%d)\n"
            % (model, rec_id)) + \
           "print('FP=%s|%s' % (r.state or '', r.write_date or ''))\n"
    return kv(shell(code), 'FP')


def state_of(model, rec_id):
    code = ("r = env['%s'].sudo().with_context(active_test=False).browse(%d)\n"
            % (model, rec_id)) + \
           "print('S=%s' % (r.state if r.exists() else 'GONE'))\n"
    return kv(shell(code), 'S')


def run_once(round_no):
    print('\n===== 第 %d 轮 =====' % round_no)
    blob = shell_fx(BUILD % {'tag': TAG, 'ilogin': INTRUDER_LOGIN})
    exam_id = kv(blob, 'EXAM')
    att_id = kv(blob, 'ATT')
    owner_u = kv(blob, 'OWNER_U')
    intr_u = kv(blob, 'INTR_U')
    if not (exam_id and att_id and intr_u):
        print('FIXTURE 构建失败:\n%s' % blob[-800:])
        return None
    exam_id, att_id = int(exam_id), int(att_id)
    print('  夹具 exam=%d att=%d（属主 user=%s / 越权 user=%s）' % (
        exam_id, att_id, owner_u, intr_u))

    # 前置断言（t56）：先证明「我是合法教师」，再谈越权。
    # 缺了这条，后面的"被拒"无法区分"越界被拒"与"无教师身份被拒"。
    check('前置：越权方是合法教师（current_faculty 口径命中 1 条）',
          kv(blob, 'INTR_LOOKUP') not in (None, '[]', '[]'),
          'INTR_LOOKUP=%s' % kv(blob, 'INTR_LOOKUP'))
    owner = login('faculty@local', 'demo123')
    intr = login(INTRUDER_LOGIN, 'demo123')
    if not owner or not intr:
        print('  登录失败 owner=%s intr=%s' % (bool(owner), bool(intr)))
        return None
    oc = get_csrf(owner, '/grading/entry') or ''
    ic = get_csrf(intr, '/grading/entry') or ''

    before = marks_of(att_id)
    # 弱判据守卫：基准值读不到（None）时必须立刻红，否则后续
    # "x == before" 会在双方都是 None 时假绿（本轮自查发现）
    check('夹具分数可读（基准值非 None）', before is not None, 'before=%s' % before)

    # ---------- 越权：成绩五入口（写/读都试）----------
    attacks = [
        ('成绩·单条 save', 'POST', '/grading/save',
         {'exam_id': exam_id, 'marks_%d' % att_id: 10, 'csrf_token': ic}),
        ('成绩·导入确认', 'POST', '/grading/import/commit',
         {'exam_id': exam_id,
          'payload': json.dumps([{'att_id': att_id, 'marks': 11}]),
          'csrf_token': ic}),
        ('成绩·上期复制', 'POST', '/grading/copy_prev',
         {'exam_id': exam_id, 'csrf_token': ic}),
    ]
    for name, method, path, data in attacks:
        if not ic:
            cannot.append('%s：越权方页面上取不到 csrf（实际观测：/grading/entry 未渲染表单）'
                          % name)
            continue
        r = intr.post(BASE + path, data=data, timeout=40, allow_redirects=False)
        m = marks_of(att_id)
        check('%s 越权后 DB 未变' % name, m == before,
              'before=%s after=%s http=%s' % (before, m, r.status_code))
        if m != before:
            FAILED_ENDPOINTS.append(name)

    # 只读入口：越权方不应看到该考试的内容（不泄露）
    for name, path, params in [
            ('成绩·导出', '/grading/export', {'exam_id': exam_id}),
            ('成绩·导入预览', '/grading/entry', {'exam_id': exam_id})]:
        r = intr.get(BASE + path, params=params, timeout=40,
                     allow_redirects=False)
        # 拆开强/弱信号（不放松断言，而是让判据可辨）：
        #  · 强信号 = 别的教师的**考试名**出现在页面里；
        #  · 弱信号 = 纯数字 att_id 作为子串出现 —— 38KB 页面里几乎必然偶合，
        #    单独用它判定会把"页码/URL/CSS 里的数字"误报成泄漏。
        hay = r.text
        by_name = u'越权夹具考试' in hay
        by_id = str(att_id) in hay
        # 判定只用**强信号（考试名）**；数字信号仅记录、不判定 ——
        # 实证：同一 URL/同一 http 200/同一 len=38482，数字命中在两轮里一次 True
        # 一次 False（纯属子串偶合），用它判定会让断言**随机变红**（不稳定的红
        # 比没有断言更坏：会训练人忽略红）。数字命中仍打印，不作隐藏。
        check('%s 不泄露该考试内容' % name, not by_name,
              'http=%s len=%d 名称命中=%s 数字命中=%s(仅记录不判定)' % (
                  r.status_code, len(r.content), by_name, by_id))

    # ---------- 不泄露存在性：真实越权 id vs 不存在 id ----------
    a = intr.post(BASE + '/grading/import/commit', data={
        'exam_id': exam_id, 'payload': json.dumps([{'att_id': att_id, 'marks': 12}]),
        'csrf_token': ic}, timeout=40, allow_redirects=False)
    b = intr.post(BASE + '/grading/import/commit', data={
        'exam_id': FAKE_ID, 'payload': json.dumps([{'att_id': att_id, 'marks': 12}]),
        'csrf_token': ic}, timeout=40, allow_redirects=False)
    check('不泄露存在性（越权 id 与不存在 id 响应不可区分）',
          resp_sig(a) == resp_sig(b), 'real=%s fake=%s' % (resp_sig(a), resp_sig(b)))

    # ---------- 正对照：属主做同一操作应当成功 ----------
    if oc:
        owner.post(BASE + '/grading/save', data={
            'exam_id': exam_id, 'marks_%d' % att_id: 77,
            'csrf_token': oc}, timeout=40, allow_redirects=False)
        m2 = marks_of(att_id)
        check('正对照·属主 save 成功改分（排除功能被锁死）', m2 == '77',
              'after_owner=%s' % m2)
        # 还原
        shell("a = env['op.exam.attendees'].sudo().browse(%d)\n"
              "a.write({'marks': %s})\n"
              "env.cr.commit()\n" % (att_id, before))
        m_restore = marks_of(att_id)
        check('还原越权/正对照改动',
              m_restore is not None and m_restore == before,
              'restored=%s（None 即 FAIL）' % m_restore)
    else:
        cannot.append('正对照·属主 save：属主会话取不到 csrf，无法构造（实际观测：未渲染表单）')

    # ---------- 自建靶子（t75 追加项）：批量矩阵不得拿**真实业务行**当靶子 ----------
    # 原先 申诉/选课 两处会走到 M.search([], limit=1) 兜底 → 靶子是真实行
    # （实测 申诉 id=23 / 选课 id=10）。那类**共享靶子**任何人动过就红、与用例毫无关系；
    # 而**假红与假绿一样消耗信任**（经常红的断言会教人忽略它，保护力归零）。
    # 故在矩阵之前先把 t75 的【冒烟】夹具建好 —— 矩阵与属主正对照**共用同一套夹具**。
    b75 = shell_fx(BUILD_T75 % {'tag': T75_TAG})
    crs75, bat75, sub75 = (kv(b75, 'T75_CRS'), kv(b75, 'T75_BAT'),
                           kv(b75, 'T75_SUB'))
    sc_before75 = kv(b75, 'T75_SC_BEFORE')
    reg_a = reg_b = 0
    stu_sess = login('stu@local', 'demo123')
    stu_tok = get_csrf(stu_sess, '/subject/enroll') if stu_sess else None
    if not (stu_sess and stu_tok and crs75 and bat75):
        cannot.append('t75 选课正对照：学生会话/csrf/夹具缺失 → 未执行断言')
    else:
        for _k in (0, 1):
            _r = stu_sess.post(BASE + '/subject/enroll/save', data={
                'csrf_token': stu_tok, 'course_id': crs75, 'batch_id': bat75,
                'elective_subject_ids': sub75,
                'applicant_note': u'【冒烟测试可删】t75 正对照夹具'},
                timeout=60, allow_redirects=False)
            _m = re.search(r'new_id=(\d+)', _r.headers.get('Location') or '')
            _rid = int(_m.group(1)) if _m else 0
            if _k == 0:
                reg_a = _rid
            else:
                reg_b = _rid

    # ---------- 批量审批三处 ----------
    bulk = [
        ('批量审批·请假', '/leave/set_state_bulk', 'edu.leave'),
        ('批量审批·申诉', '/grievances/set_state_bulk', 'edu.grievance'),
        ('批量审批·选课', '/registrar/subject/set_state_bulk',
         'op.subject.registration'),
    ]
    for name, path, model in bulk:
        if model == 'op.subject.registration' and reg_b:
            # t75 追加项：选课靶子用**自建【冒烟】单 regB**（保持 submitted → 越权得逞会变
            # approved，可观察），不再走 M.search([], limit=1) 兜底去抓真实行（原先抓 id=10）。
            sid, stv = str(reg_b), 'submitted'
        else:
            # t94：**删掉退化兜底**。原先这一行是 `r = r or M.search([], limit=1)` ——
            # TAG 夹具缺失时会**退回任意真实行**当靶子（实测曾抓到 申诉 id=23 / 选课 id=10）。
            # 那类**共享靶子**任何人动过就该条断言红、而与用例毫无关系；
            # 而**假红与假绿一样消耗信任**（经常红的断言会教人忽略它，保护力归零）。
            # 现在：**只按 TAG 找夹具**；找不到就落到下面的 cannot 分支并跳过该路由断言 ——
            # 与 t67「构造不出就如实记录、不伪造路径」同一口径。
            st = shell(("M = env['%s'].sudo().with_context(active_test=False)\n" % model) +
                       ("r = M.search([('name','like',u'%s')], limit=1)\n" % TAG) +
                       "print('SID=%d ST=%s' % (r.id, r.state or ''))\n")
            sid, stv = kv(st, 'SID'), kv(st, 'ST')
        if not sid or sid == '0':
            # 构造不出越权目标 → 如实记录，不伪造路径（任务明确要求）
            # t94 起这里**只会**因「TAG 夹具缺失」触发（不再有退回真实行的路径）。
            cannot.append('%s：库中无带 TAG 的 %s 夹具 → 无法在 HTTP 层构造越权目标'
                          '（实际观测：无对象可攻击，未执行断言；已按 t94 不退回真实行）'
                          % (name, model))
            continue
        data = {'ids': str(sid), 'state': 'approved', 'csrf_token': ic} \
            if model != 'edu.grievance' else \
            {'ids': str(sid), 'state': 'resolve', 'csrf_token': ic}
        if not ic:
            cannot.append('%s：越权方无 csrf' % name); continue
        fp_before = fingerprint_of(model, int(sid))
        intr.post(BASE + path, data=data, timeout=40, allow_redirects=False)
        fp_after = fingerprint_of(model, int(sid))
        check('%s 越权后 DB 未变（state+write_date 指纹一致）' % name,
              fp_after is not None and fp_after == fp_before,
              'id=%s before=%s after=%s' % (sid, fp_before, fp_after))

    # ---------- t75：选课批量的**属主正对照**（自建合法单）----------
    # 顺序纪律（任务明确要求）：**先确认正对照通过，再读越权那一行** ——
    # 否则越权读到的 0 可能只是「这条路对谁都批准不了」。
    # 夹具与两张【冒烟】单已在「批量审批三处」之前建好（矩阵与属主正对照共用同一套）；
    # 此处只做断言与正对照，不再重复造。
    check('t75 夹具·自建课程/班级/科目成立',
          bool(crs75 and bat75 and sub75),
          'crs=%s bat=%s sub=%s' % (crs75, bat75, sub75))
    check('t75 前置·业务前置「班级属于该课程」成立（SR0008 的正解）',
          kv(b75, 'T75_BIZ_OK') == '1', 'BIZ_OK=%s' % kv(b75, 'T75_BIZ_OK'))
    check('t75 前置·存在「在教师作用域内」的学生可挂单',
          kv(b75, 'T75_STU_IN_SCOPE') == '1', 'stu=%s' % kv(b75, 'T75_STU'))
    check('t75 自建【冒烟】注册单两张已创建（regA 正对照 / regB 越权负例）',
          bool(reg_a and reg_b), 'regA=%s regB=%s' % (reg_a, reg_b))

    if reg_a and reg_b:
        # 前置断言（任务要求的三行）：字段名对 / 对象确实存在 / 该单在作用域内
        pre75 = shell(
            "r = env['op.subject.registration'].sudo().with_context(active_test=False).browse(" + str(reg_a) + ")\n"
            "fac = env['op.faculty'].sudo().search([('user_id.login', '=', 'faculty@local')], limit=1)\n"
            "bts = env['op.session'].sudo().search([('faculty_id', '=', fac.id)]).mapped('batch_id')\n"
            "sts = env['op.student.course'].sudo().search([('batch_id', 'in', bts.ids)]).mapped('student_id')\n"
            "print('T75F=%d' % (1 if (r.student_id and r.course_id and r.batch_id) else 0))\n"
            "print('T75E=%d' % (1 if (r.student_id.exists() and r.course_id.exists() and r.batch_id.exists()) else 0))\n"
            "print('T75B=%d' % (1 if r.batch_id.course_id.id == r.course_id.id else 0))\n"
            "print('T75S=%d' % (1 if r.student_id.id in sts.ids else 0))\n"
            "print('T75ST=%s' % (r.state or ''))\n")
        check('t75 前置1·字段名对（student/course/batch 均非空）',
              kv(pre75, 'T75F') == '1', 'F=%s' % kv(pre75, 'T75F'))
        check('t75 前置2·对象确实存在（三件 browse().exists() 全真）',
              kv(pre75, 'T75E') == '1', 'E=%s' % kv(pre75, 'T75E'))
        check('t75 前置3·业务前置：班级确实属于该课程',
              kv(pre75, 'T75B') == '1', 'B=%s' % kv(pre75, 'T75B'))
        check('t75 前置4·该单确实在教师作用域内（镜像 approval_scope_domain）',
              kv(pre75, 'T75S') == '1', 'S=%s' % kv(pre75, 'T75S'))
        check('t75 前置5·新单初始状态为 submitted（否则无流转可测）',
              kv(pre75, 'T75ST') == 'submitted', 'state=%s' % kv(pre75, 'T75ST'))

        # ---- 属主正对照：教师（其任教版=8，作用域含该生）批量通过 ----
        oc75 = get_csrf(owner, '/registrar/subject/approvals') or ''
        if not oc75:
            cannot.append('t75 属主正对照：教师会话取不到 csrf（实际观测：未渲染表单）')
        else:
            rp = owner.post(BASE + '/registrar/subject/set_state_bulk',
                            data={'ids': str(reg_a), 'state': 'approved',
                                  'csrf_token': oc75},
                            timeout=40, allow_redirects=False)
            okv, fv, sv = bulk_counts(rp)
            check('t75 属主正对照·批量通过 ok=1（排除「功能被锁死」）',
                  okv == 1, 'ok=%s fail=%s skip=%s http=%s'
                  % (okv, fv, sv, rp.status_code))
            sta = state_of('op.subject.registration', reg_a)
            check('t75 属主正对照·状态变为 approved',
                  sta == 'approved', 'state=%s' % sta)

            # ---- 越权负例：打 regB（**仍 submitted**，得逞会变 approved → 可观察）----
            ri = intr.post(BASE + '/registrar/subject/set_state_bulk',
                           data={'ids': str(reg_b), 'state': 'approved',
                                 'csrf_token': ic},
                           timeout=40, allow_redirects=False)
            ok2, f2, s2 = bulk_counts(ri)
            check('t75 越权·ok=0 fail=0 skip=0（越权 id 静默丢弃、不计 skip）',
                  (ok2, f2, s2) == (0, 0, 0),
                  'ok=%s fail=%s skip=%s' % (ok2, f2, s2))
            sb = state_of('op.subject.registration', reg_b)
            check('t75 越权后 DB 未变（regB 仍 submitted，且本可观察）',
                  sb == 'submitted', 'state=%s（若为 approved 即越权得逞）' % sb)
            if sb not in (None, 'submitted'):
                FAILED_ENDPOINTS.append('批量审批·选课(t75 regB)')
            # 不泄露存在性：越权 id 与不存在 id 的响应签名须一致
            rn = intr.post(BASE + '/registrar/subject/set_state_bulk',
                           data={'ids': str(FAKE_ID), 'state': 'approved',
                                 'csrf_token': ic},
                           timeout=40, allow_redirects=False)
            check('t75 不泄露存在性（越权 id 与不存在 id 响应不可区分）',
                  resp_sig(ri) == resp_sig(rn),
                  'real=%s fake=%s' % (resp_sig(ri), resp_sig(rn)))

    # t75 清场 + 「是否改动既有行」的行为读数
    d75 = shell_fx(DROP_T75 % {'tag': T75_TAG})
    check('t75 清场·注册单 leftover=0',
          kv(d75, 'T75_LEFT_REG') == '0', 'REG=%s' % kv(d75, 'T75_LEFT_REG'))
    check('t75 清场·档案 leftover=0（含审批新建的那行）',
          kv(d75, 'T75_LEFT_SC') == '0', 'SC=%s' % kv(d75, 'T75_LEFT_SC'))
    check('t75 清场·课程 leftover=0',
          kv(d75, 'T75_LEFT_CRS') == '0', 'CRS=%s' % kv(d75, 'T75_LEFT_CRS'))
    check('t75 未改动既有行（该生审批前的档案 id 集合逐字一致）',
          sc_before75 is not None and sc_before75 == kv(d75, 'T75_SC_AFTER'),
          'before=%s after=%s' % (sc_before75, kv(d75, 'T75_SC_AFTER')))

    # ---------- 清场 ----------
    shell("a = env['op.exam.attendees'].sudo().browse(%d)\n"
          "a.write({'marks': %s})\n"
          "env.cr.commit()\n" % (att_id, before))
    drop = shell_fx(DROP % {'tag': TAG, 'ilogin': INTRUDER_LOGIN})
    left = kv(drop, 'LEFTOVER_EXAM')
    check('清场 leftover=0（active_test=False 复核）', left == '0',
          'LEFTOVER_EXAM=%s' % left)

    # 历史留痕清场（会自己产生，须复核）
    hl = shell("H = env['edu.grade.history'].sudo().with_context(active_test=False)\n"
               "ex = env['op.exam'].sudo().with_context(active_test=False).search("
               "[('name','like',u'%s')])\n" % TAG +
               "print('HL=%d' % H.search_count([('exam_id', 'in', ex.ids)]))\n")
    check('清场 成绩留痕 leftover=0', kv(hl, 'HL') == '0', 'HL=%s' % kv(hl, 'HL'))
    # 两轮一致的比较键必须是**有意义且两轮同形**的终态：
    # 清场后的 leaves（夹具已删，此时再读 marks 只能是"没有"——那样比的是
    # "空"与"空的两种写法"，会让断言随机变红）。改为比清场计数，二者都应为 0。
    return {'leftover_exam': kv(drop, 'LEFTOVER_EXAM'),
            'history_leftover': kv(hl, 'HL')}

def main():
    t0 = time.time()
    print('=== t43 端到端越权实测（TAG=%s）===' % TAG)
    if not preflight():
        return 2
    r1 = run_once(1)
    r2 = run_once(2)
    if r1 and r2:
        check('连跑两次 DB 终态一致', r1 == r2, '%s vs %s' % (r1, r2))
    print('\n===== 汇总 =====')
    npass = sum(1 for v, _n, _d in results if v == 'PASS')
    nfail = len(results) - npass
    print('断言 %d 条：PASS %d / FAIL %d' % (len(results), npass, nfail))
    if FAILED_ENDPOINTS:
        print('越权得逞（DB 被改）：%s' % '、'.join(FAILED_ENDPOINTS))
    if cannot:
        print('无法构造的入口（如实记录，未伪造路径）：')
        for c in cannot:
            print('  - %s' % c)
    print('耗时 %.1fs' % (time.time() - t0))
    # 防止"假绿"：一条断言都没跑出来时**必须判失败**，绝不能 exit 0
    # （夹具构建失败/登录失败都会走到这里；0 断言 ≠ 通过）
    if not results:
        print('未产生任何断言（夹具或登录失败）→ 判失败，不得视为通过')
        return 1
    return 1 if nfail or FAILED_ENDPOINTS else 0


if __name__ == '__main__':
    sys.exit(main())
