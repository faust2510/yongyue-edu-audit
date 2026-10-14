#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""班级分配与管理（需求 7）真机冒烟：六步闸门第 6 步。

设计稿：docs/plans/class-batch-management-design.md
用法：python3 tests/smoke/class_batch_mgmt.py
结果落盘：tests/smoke/class_batch_mgmt_results.json

覆盖（逐条对应校长拍板与设计稿验收表）：
  CB1  载体合法：四角色账号/身份先自证（学生、教师、教务、家长）
  CB2  夹具合法：演示班 + 真实注册路径产出的【待分配】学生（先断言夹具生效）
  CB3  断链证据链：建【待分配】学生 → 教务分班 → 学生登录看到课表课时 → 前缀消失
  CB4  分班入口：教务可选（action_edu_assign_batch 指向正确载体）、教师被拒
  CB5  老师建/编辑班级：菜单（口径 B load_menus）+ 建班 + 改班 + 不能删（正对照齐全）
  CB6  回收站：停用 → 列表消失/回收站可见 → 学生侧不受影响 → 零副作用 → 恢复
  CB7  归档权限（校长拍板①+设计 §10 档②）：教师改 active 被拒；改班名不受影响
  CB8  真删护栏：有课节拒绝、只有学生拒绝、零引用放行（且拒绝时数据未变）
  CB9  同学可见性（校长拍板②③）：只姓名 + 班名；无异班学生；家长看不到别人家孩子
  CB10 清理：leftover = 0

红线（本仓 dev-workflow「判据强度五兄弟」）：
  · 探测**不跟随重定向**（allow_redirects=False）；
  · 不只断言「页面 200」——要看页面内容与库里的行；
  · 载体必须先被断言合法（夹具生效、四角色身份成立）再谈被测行为；
  · 越权断言配正对照（同学 B 在 / 异班 C 不在）；
  · 量具无副作用：夹具只用本脚本自己的标记定位，**不按 max(id)**、不碰别人数据。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

BASE = os.environ.get('CBM_BASE', 'http://localhost:8069')
DB = os.environ.get('EDU_DB_NAME', 'edu19')
REPO = Path(__file__).resolve().parent.parent.parent
RESULTS_JSON = Path(__file__).resolve().parent / 'class_batch_mgmt_results.json'
LOCK = os.path.join(os.environ.get('TMPDIR') or '/tmp', 'edu19_upgrade.lock')

TAG = '【演示】班级分配冒烟'
STU_NAME_A = '班级分配冒烟甲【演示】'
STU_NAME_B = '班级分配冒烟乙【演示】'
STU_NAME_C = '班级分配冒烟丙【演示】'
LOGIN_A = 'cbm_smoke_a@local'
LOGIN_B = 'cbm_smoke_b@local'
CODE_A = 'CBM-SMOKE-A'
CODE_B = 'CBM-SMOKE-B'
COURSE_ID = 18                      # 预备科（既有课程：不新建课程，减少夹具面）
PENDING = '【待分配】'

BACKOFFICE = ('backoffice@local', 'demo123')
TEACHER = ('faculty@local', 'demo123')
PARENT = ('parent@local', 'demo123')

RESULTS = []
FX = {}
SNAP = {}


def check(no, name, ok, detail=''):
    RESULTS.append({'no': no, 'name': name, 'pass': bool(ok),
                    'detail': str(detail)[:900]})
    print('  [%s] %-6s %s%s' % ('PASS' if ok else 'FAIL', no, name,
                                (' | ' + str(detail)[:400]) if detail else ''))
    return bool(ok)


def note(msg):
    print('  ---- %s' % msg)


# ------------------------------------------------------------------ 工具
def psql(sql):
    out = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                          '-U', 'odoo', '-d', DB, '-tAc', sql],
                         capture_output=True, text=True, timeout=180, cwd=str(REPO))
    if out.returncode != 0:
        raise RuntimeError('psql 失败：' + (out.stderr or '').strip()[:300])
    return out.stdout.strip()


def pscalar(sql):
    return int(psql(sql) or 0)


def q(s):
    return "'" + str(s).replace("'", "''") + "'"


def shell(code, timeout=420):
    cmd = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
           '-c', '/etc/odoo/odoo.conf', '--db_host=db', '--db_port=5432',
           '--db_user=odoo', '--db_password=odoo', '-d', DB, '--no-http']
    out = subprocess.run(cmd, input=code, capture_output=True, text=True,
                         timeout=timeout, cwd=str(REPO))
    return (out.stdout or '') + (out.stderr or '')


def shell_json(body, timeout=420):
    code = ('import json\nOUT = {}\n' + body +
            "\nprint('@@CBMJSON@@' + json.dumps(OUT, ensure_ascii=False, "
            "default=str))\n")
    blob = shell(code, timeout)
    m = re.search(r'@@CBMJSON@@(.*)', blob)
    if not m:
        p = '/tmp/cbm_shell_fail.txt'
        Path(p).write_text(blob)
        raise RuntimeError('odoo shell 未返回 JSON（完整输出见 %s）：%s'
                           % (p, blob[-1200:]))
    return json.loads(m.group(1))


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


def new_id(result):
    """Odoo 19 的 create 经 JSON-RPC 返回**id 列表**（model_create_multi）⇒ 归一成 int。"""
    if isinstance(result, int):
        return result
    if isinstance(result, (list, tuple)) and result:
        return result[0]
    return None


def probe(sess, path):
    """**不跟随重定向**的探测。"""
    return sess.get(BASE + path, timeout=40, allow_redirects=False)


def call_kw(sess, model, method, args, kwargs=None):
    """JSON-RPC 调用：成功 → (result, None)；失败 → (None, 人话错误消息)。"""
    payload = {'jsonrpc': '2.0', 'method': 'call',
               'params': {'model': model, 'method': method,
                          'args': args, 'kwargs': kwargs or {}}}
    r = sess.post(BASE + '/web/dataset/call_kw', json=payload, timeout=90)
    try:
        j = r.json()
    except Exception:
        return None, 'HTTP %s 非 JSON' % r.status_code
    if 'error' in j:
        err = j['error'] or {}
        data = err.get('data') or {}
        msg = data.get('message') or err.get('message') or str(err)
        return None, msg
    return j.get('result'), None


def menu_nodes(sess):
    """口径 B：/web/webclient/load_menus 的**顶层**字典（Odoo 19 无 result 包装）。

    实测结构（2026-09-18）：顶层是 {菜单 id 字符串: 节点字典}，
    节点的 children 是**子菜单 id 列表**（不是嵌套字典）
    ⇒ 全部顶层值即该角色可见的全部菜单节点。
    """
    r = sess.get(BASE + '/web/webclient/load_menus', timeout=40)
    try:
        data = r.json()
    except Exception:
        return None, 'HTTP %s 非 JSON' % r.status_code
    if not isinstance(data, dict):
        return None, '非字典：%s' % type(data)
    out = [{'id': v.get('id'), 'name': v.get('name'),
            'actionPath': v.get('actionPath'), 'actionID': v.get('actionID'),
            'xmlid': v.get('xmlid')}
           for v in data.values() if isinstance(v, dict)]
    return out, None


def classmates_section(html):
    m = re.search(r'<section id="edu-classmates".*?</section>', html or '',
                  re.S)
    return m.group(0) if m else None


# ------------------------------------------------------------------ 夹具
FIXTURE = """
import json

from odoo import fields

OUT = {}
env = env
TAG = @@TAG@@
LOGIN_A = @@LOGIN_A@@
LOGIN_B = @@LOGIN_B@@
CODE_A = @@CODE_A@@
CODE_B = @@CODE_B@@
COURSE_ID = @@COURSE_ID@@
PENDING = @@PENDING@@
NAMES = (@@NAMES@@)

Bd = env['op.batch'].sudo().with_context(active_test=False)
Se = env['op.session'].sudo().with_context(active_test=False)
Sc = env['op.student.course'].sudo().with_context(active_test=False)
St = env['op.student'].sudo().with_context(active_test=False)
Us = env['res.users'].sudo().with_context(active_test=False)
Pa = env['res.partner'].sudo().with_context(active_test=False)
Ic = env['edu.invite.code'].sudo()

# ---------- 0) 幂等清场：只按本脚本自己的标记定位（绝不按 max(id)/绝不碰别人数据）----------
def wipe():
    batches = Bd.search([('name', 'like', TAG + '%')])
    users = Us.search([('login', 'in', (LOGIN_A, LOGIN_B))])
    students = St.search([('name', 'like', '%班级分配冒烟%')])
    students |= St.search([('user_id', 'in', users.ids)])
    if batches:
        Se.search([('batch_id', 'in', batches.ids)]).unlink()
        Sc.search([('batch_id', 'in', batches.ids)]).unlink()
    if students:
        Sc.search([('student_id', 'in', students.ids)]).unlink()
    codes = Ic.search([('code', 'in', (CODE_A, CODE_B))])
    partners = students.mapped('partner_id') | users.mapped('partner_id')
    if students:
        students.unlink()
    if codes:
        codes.unlink()
    if users:
        users.unlink()
    for p in partners:
        if p.exists():
            try:
                p.unlink()
            except Exception as exc:
                OUT.setdefault('wipe_partner_skip', []).append(repr(exc)[:120])
    if batches:
        batches.unlink()
    env.cr.commit()

wipe()
# 清场基线（判据的"终态"）：本脚本跑完必须回到这两个数
OUT['students_before'] = St.search_count([])
OUT['users_before'] = Us.search_count([])

# ---------- 1) 演示班（甲=有课节、乙=异班、丙=只有学生、空=零引用）----------
BD = {'start_date': '2026-09-01', 'end_date': '2027-07-31',
      'course_id': COURSE_ID}
b_a = Bd.create(dict(BD, name=TAG + '·甲班', code='CBM-A'))
b_b = Bd.create(dict(BD, name=TAG + '·乙班', code='CBM-B'))
b_c = Bd.create(dict(BD, name=TAG + '·丙班', code='CBM-C'))
b_empty = Bd.create(dict(BD, name=TAG + '·空班', code='CBM-EMPTY'))

# ---------- 2) 课节（今天；学生课表窗口 = 自然周）----------
course = env['op.course'].sudo().browse(COURSE_ID)
sub = course.subject_ids[:1] or env['op.subject'].sudo().search([], limit=1)
ref_ses = Se.search([('batch_id', '=', 8)], limit=1)
fac = ref_ses.faculty_id or env['op.faculty'].sudo().search([], limit=1)
tim = ref_ses.timing_id
today = fields.Date.today().strftime('%Y-%m-%d')
# ⚠ 教师同一天不能有重叠课时（基座 op.session.check_timetable_fields）。
# 既有库里今天已有 08:00/09:00/10:30 三段（batch 8）⇒ 本夹具取傍晚时段，
# 既落在同一个自然周（学生课表窗口）又不与他人课时冲突。
ses1 = Se.create({'course_id': COURSE_ID, 'batch_id': b_a.id,
                  'subject_id': sub.id, 'faculty_id': fac.id,
                  'timing_id': tim.id if tim else False,
                  'start_datetime': today + ' 18:15:00',
                  'end_datetime': today + ' 19:00:00', 'state': 'draft'})
ses2 = Se.create({'course_id': COURSE_ID, 'batch_id': b_a.id,
                  'subject_id': sub.id, 'faculty_id': fac.id,
                  'timing_id': tim.id if tim else False,
                  'start_datetime': today + ' 20:15:00',
                  'end_datetime': today + ' 21:00:00', 'state': 'draft'})

# ---------- 3) 学生：甲/乙走**真实注册路径**（层级码 → create_pending_archive）----------
def reg_student(login, code_str, real_name):
    partner = Pa.create({'name': real_name})
    user = Us.create({'name': real_name, 'login': login,
                      'password': 'demo123', 'partner_id': partner.id,
                      'group_ids': [(6, 0, [env.ref('base.group_portal').id])]})
    code = Ic.create({'code': code_str, 'code_kind': 'tier', 'tier': 'student',
                      'use_limit': 0, 'note': TAG})
    stu = code.create_pending_archive(user, real_name)
    return stu, user

stu_a, user_a = reg_student(LOGIN_A, CODE_A, NAMES[0])
stu_b, user_b = reg_student(LOGIN_B, CODE_B, NAMES[1])
# 丙：异班同学（负对照），不需要账号
# ⚠ 两个实测坑（都在这里踩过）：
#   ① op.student.gender 取值是 'm'/'f'（不是 'male'/'female'）；
#   ② **必须先建档案、再写 partner 名** —— 基座 op.student.create
#      （openeducat_core/models/student.py:120-131）在没有 first/last name 时会把
#      name 写成 'New'，而 name 是 partner 的委托字段 ⇒ 直接给 partner 起名会被覆盖。
#      第一版就是因此把「异班同学」造成了名为 'New' 的记录 ⇒ 负对照退化成
#      「页面里没有 New」这种弱信号（假绿），且按名字清场也漏掉了它。
p_c = Pa.create({'name': 'tmp'})
stu_c = St.create({'partner_id': p_c.id,
                   'gender': env['op.student']._fields['gender'].selection[0][0]})
p_c.write({'name': NAMES[2]})
env.cr.commit()

OUT['batch_a'] = b_a.id
OUT['batch_b'] = b_b.id
OUT['batch_c'] = b_c.id
OUT['batch_empty'] = b_empty.id
OUT['stu_a'] = stu_a.id
OUT['stu_b'] = stu_b.id
OUT['stu_c'] = stu_c.id
OUT['user_a'] = user_a.id
OUT['user_b'] = user_b.id
OUT['faculty'] = fac.id
OUT['subject'] = sub.id
OUT['subject_name'] = sub.name or ''
OUT['faculty_name'] = fac.name or ''
OUT['session_ids'] = [ses1.id, ses2.id]
OUT['name_a'] = stu_a.name
OUT['name_b'] = stu_b.name
OUT['name_c'] = stu_c.name
OUT['pending_a'] = bool(stu_a.edu_pending_setup)
OUT['a_sc_count'] = Sc.search_count([('student_id', '=', stu_a.id)])
OUT['phone_b'] = user_b.partner_id.phone or ''
OUT['email_b'] = user_b.partner_id.email or ''
env.cr.commit()
"""

CLEANUP = """
env = env
Sc = env['op.student.course'].sudo().with_context(active_test=False)
St = env['op.student'].sudo().with_context(active_test=False)
Us = env['res.users'].sudo().with_context(active_test=False)
Pa = env['res.partner'].sudo().with_context(active_test=False)
Bd = env['op.batch'].sudo().with_context(active_test=False)
Se = env['op.session'].sudo().with_context(active_test=False)
Ic = env['edu.invite.code'].sudo()
TAG = @@TAG@@
LOGINS = (@@LOGIN_A@@, @@LOGIN_B@@)
BASELINE_STUDENTS = @@BASE_STUDENTS@@
BASELINE_USERS = @@BASE_USERS@@

batches = Bd.search([('name', 'like', TAG + '%')])
users = Us.search([('login', 'in', LOGINS)])
students = St.search([('name', 'like', '%班级分配冒烟%')])
students |= St.search([('user_id', 'in', users.ids)])
if batches:
    Se.search([('batch_id', 'in', batches.ids)]).unlink()
    Sc.search([('batch_id', 'in', batches.ids)]).unlink()
if students:
    Sc.search([('student_id', 'in', students.ids)]).unlink()
Ic.search([('note', '=', TAG)]).unlink()
# 教师建的班（CB5）也归到清理里
tb = Bd.search([('name', 'like', '%CB5教师建班%')])
if tb:
    Se.search([('batch_id', 'in', tb.ids)]).unlink()
    Sc.search([('batch_id', 'in', tb.ids)]).unlink()
partners = students.mapped('partner_id') | users.mapped('partner_id')
if students:
    students.unlink()
if users:
    users.unlink()
for p in partners:
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass
if batches:
    batches.unlink()
if tb:
    tb.unlink()
env.cr.commit()
OUT['leftover_batch'] = Bd.search_count([('name', 'like', TAG + '%')])
OUT['leftover_student'] = St.search_count([('name', 'like', '%班级分配冒烟%')])
OUT['leftover_user'] = Us.search_count([('login', 'in', LOGINS)])
OUT['leftover_code'] = Ic.search_count([('note', '=', TAG)])
OUT['leftover_teacher_batch'] = Bd.search_count([('name', 'like', '%CB5教师建班%')])
# 更强的终态：总人数回到基线（只按名字查会漏掉"名字不是标记名"的残留 —— 实测踩过）
OUT['students_now'] = St.search_count([])
OUT['users_now'] = Us.search_count([])
OUT['students_delta'] = OUT['students_now'] - BASELINE_STUDENTS
OUT['users_delta'] = OUT['users_now'] - BASELINE_USERS
"""


def fmt(tpl, **kw):
    out = tpl
    for k, v in kw.items():
        out = out.replace('@@%s@@' % k.upper(), json.dumps(v))
    return out
    out = tpl
    for k, v in kw.items():
        out = out.replace('@@%s@@' % k.upper(), json.dumps(v))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true', help='跑完不清理（排障用）')
    args = ap.parse_args()
    rc = 0

    # ---------------- CB0 前置：没有别的升级在跑，站点活着 ----------------
    print('== CB0 前置 ==')
    check('CB0.1', '无升级锁（避免跨升级半程读数）', not os.path.exists(LOCK),
          '锁路径 %s' % LOCK)
    anon = requests.Session()
    anon.trust_env = False
    r0 = anon.get(BASE + '/web/login?db=%s' % DB, timeout=30,
                  allow_redirects=False)
    check('CB0.2', '站点可达 /web/login', r0.status_code in (200, 302, 303),
          'HTTP %s' % r0.status_code)

    # ---------------- CB1 载体合法（四角色） ----------------
    print('== CB1 载体合法（四角色身份先自证） ==')
    sz, uid = login(*BACKOFFICE)
    check('CB1.1', '教务登录成功', bool(uid), 'uid=%s' % uid)
    tz, tuid = login(*TEACHER)
    check('CB1.2', '教师登录成功', bool(tuid), 'uid=%s' % tuid)
    pz, puid = login(*PARENT)
    check('CB1.3', '家长登录成功', bool(puid), 'uid=%s' % puid)
    if not (sz and tz and pz):
        print('  [FATAL] 三个后台/门户会话缺一，读数作废')
        write_results(rc=1)
        return 1
    r, err = call_kw(sz, 'res.users', 'has_group',
                     [[uid], 'openeducat_core.group_op_back_office_admin'])
    check('CB1.4', '教务账号确在教务处组', r is True, 'has_group=%s err=%s' % (r, err))
    r, err = call_kw(tz, 'op.faculty', 'search_read',
                     [[['user_id', '=', tuid]], ['id', 'name']])
    check('CB1.5', '教师账号能解析出 op.faculty 档案（否则「被拒」与「没身份」同形）',
          bool(r), 'faculty=%s' % (r or err))
    r, err = call_kw(sz, 'op.batch', 'check_access_rights', ['unlink'],
                     {'raise_exception': False})
    check('CB1.6', '教务对 op.batch 有 unlink 权（校长拍板：删除归教务）',
          r is True, 'unlink=%s err=%s' % (r, err))
    r, err = call_kw(tz, 'op.batch', 'check_access_rights', ['unlink'],
                     {'raise_exception': False})
    check('CB1.7', '教师对 op.batch 无 unlink 权（基座原样）', r is False,
          'unlink=%s err=%s' % (r, err))

    # ---------------- CB2 夹具（真实注册路径产出的【待分配】学生） ----------------
    print('== CB2 夹具（层级码注册 → 【待分配】档案） ==')
    try:
        out = shell_json(fmt(FIXTURE, tag=TAG, login_a=LOGIN_A, login_b=LOGIN_B,
                             code_a=CODE_A, code_b=CODE_B, course_id=COURSE_ID,
                             pending=PENDING,
                             names=[STU_NAME_A, STU_NAME_B, STU_NAME_C]))
    except Exception as exc:
        check('CB2.0', '夹具建立（odoo shell）', False, repr(exc)[:400])
        write_results(rc=1)
        return 1
    FX.update({k: v for k, v in out.items() if k != 'wipe_partner_skip'})
    note('甲=%s(批%s) 乙=%s(批%s) 丙=%s(批%s) 空班=%s'
         % (FX['stu_a'], FX['batch_a'], FX['stu_b'], FX['batch_b'],
            FX['stu_c'], FX['batch_c'], FX['batch_empty']))
    check('CB2.0', '负对照载体合法：异班学生丙的名字确实是标记名（不是基座默认 New）',
          FX['name_c'] == STU_NAME_C, 'name_c=%s' % FX['name_c'])
    check('CB2.1', '【待分配】学生甲由**真实注册路径**产出（名字带前缀）',
          out['name_a'].startswith(PENDING), 'name=%s' % out['name_a'])
    check('CB2.2', '学生甲 edu_pending_setup=True（机器标记同源）',
          out['pending_a'] is True, 'flag=%s' % out['pending_a'])
    check('CB2.3', '学生甲分班前**没有任何班级档案**（断链现场）',
          out['a_sc_count'] == 0, 'op_student_course 行数=%s' % out['a_sc_count'])
    check('CB2.4', '演示班有课节（载体：课表可见性靠它）',
          len(out['session_ids']) == 2, 'sessions=%s' % out['session_ids'])

    # ---------------- CB3 断链证据链（核心） ----------------
    print('== CB3 断链证据链：分班 → 课表出现课时 → 前缀消失 ==')
    sc = 'select count(*) from op_student_course where student_id=%d' % FX['stu_a']
    check('CB3.1', '分班前：库里 0 行班级档案', pscalar(sc) == 0,
          'count=%s' % pscalar(sc))
    # 学生甲登录（分班前）
    sa, auid = login(LOGIN_A, 'demo123')
    check('CB3.2', '学生甲（门户账号）登录成功', bool(auid), 'uid=%s' % auid)
    before = probe(sa, '/student/timetable')
    check('CB3.3', '分班前课表页 200 且处于「暂无排课」空态（负对照）',
          before.status_code == 200 and '暂无排课' in before.text,
          'HTTP %s · 含暂无排课=%s' % (before.status_code,
                                   '暂无排课' in (before.text or '')))
    # 教务分班（= 学生页「分配班级」对话框提交的那一次写）
    r, err = call_kw(sz, 'op.student.course', 'create',
                     [[{'student_id': FX['stu_a'], 'course_id': COURSE_ID,
                        'batch_id': FX['batch_a'], 'state': 'running'}]])
    check('CB3.4', '教务给学生甲分班（op.student.course + batch_id）',
          bool(new_id(r)), '新建档案 id=%s err=%s' % (new_id(r) or r, err))
    FX['sc_a'] = new_id(r)
    row = psql('select batch_id, state from op_student_course where student_id=%d'
               % FX['stu_a'])
    check('CB3.5', '库里档案指向演示甲班且 state=running',
          row.split('|')[0].strip() == str(FX['batch_a'])
          and 'running' in row, 'row=%s' % row)
    nm = psql('select p.name from op_student s join res_partner p on p.id=s.partner_id'
              ' where s.id=%d' % FX['stu_a'])
    check('CB3.6', '名字里的「【待分配】」前缀已消失（收口生效）',
          not nm.startswith(PENDING) and nm == STU_NAME_A, 'name=%s' % nm)
    flag = psql('select edu_pending_setup from op_student where id=%d' % FX['stu_a'])
    check('CB3.7', 'edu_pending_setup 已清（机器标记同源收口）',
          flag.strip() in ('f', ''), 'flag=%s' % flag.strip())
    after = probe(sa, '/student/timetable')
    ok_tt = (after.status_code == 200
             and FX['subject_name'] and FX['subject_name'] in after.text
             and '暂无排课' not in after.text)
    check('CB3.8', '分班后同一学生课表出现该班课时（科目名 + 非空态）', ok_tt,
          'HTTP %s · 含科目「%s」=%s' % (
              after.status_code, FX['subject_name'],
              FX['subject_name'] in (after.text or '')))
    check('CB3.9', '课表里能看到该班课节的任课教师',
          FX['faculty_name'] and FX['faculty_name'] in (after.text or ''),
          'faculty=%s' % FX['faculty_name'])

    # ---------------- CB4 分班入口（教务） ----------------
    print('== CB4 分班入口 ==')
    # 学生甲此时**已有**档案 → 入口应打开「该生的档案列表」对话框
    r, err = call_kw(sz, 'op.student', 'action_edu_assign_batch', [[FX['stu_a']]])
    ok_entry = (isinstance(r, dict) and r.get('res_model') == 'op.student.course'
                and r.get('target') == 'new'
                and r.get('domain') == [['student_id', '=', FX['stu_a']]]
                and (r.get('context') or {}).get('default_student_id') == FX['stu_a'])
    check('CB4.1', '教务点「分配班级」→ 打开该生的班级档案对话框',
          ok_entry, 'action=%s' % json.dumps(r, ensure_ascii=False)[:300])
    # 学生乙此刻**还没有**档案 → 入口应直接开「新建分班表单」（带分班专用视图）
    r2, err2 = call_kw(sz, 'op.student', 'action_edu_assign_batch',
                       [[FX['stu_b']]])
    ok_entry2 = (isinstance(r2, dict) and r2.get('view_mode') == 'form'
                 and r2.get('res_id') is False
                 and (r2.get('context') or {}).get('default_student_id')
                 == FX['stu_b'])
    check('CB4.1b', '无档案的学生 → 入口直接开「分班」新建表单（res_id=False）',
          ok_entry2, 'action=%s' % json.dumps(r2, ensure_ascii=False)[:300])
    r, err = call_kw(tz, 'op.student', 'action_edu_assign_batch', [[FX['stu_a']]])
    check('CB4.2', '教师调用分班入口被拒（分班改学籍归属）',
          r is None and err and '教务处' in err, 'err=%s' % err)

    # ---------------- CB5 老师建/编辑班级 ----------------
    print('== CB5 老师新建 / 编辑班级 ==')
    nodes, merr = menu_nodes(tz)
    hit = [n for n in (nodes or []) if n.get('actionPath') == 'batches']
    check('CB5.1', '教师 load_menus（口径 B）含「班级」且 actionPath=batches',
          bool(hit), '命中=%s（节点数 %s）'
          % (json.dumps(hit, ensure_ascii=False), len(nodes or [])))
    r, err = call_kw(tz, 'op.batch', 'create',
                     [[{'name': 'CB5教师建班' + TAG, 'code': 'CBM-T5',
                        'course_id': COURSE_ID, 'start_date': '2026-09-01',
                        'end_date': '2027-07-31'}]])
    check('CB5.2', '教师**能**新建班级（基座 ACL 本来就有 create）',
          bool(new_id(r)), 'id=%s err=%s' % (new_id(r) or r, err))
    FX['teacher_batch'] = new_id(r)
    r, err = call_kw(tz, 'op.batch', 'write',
                     [[FX['teacher_batch']], {'name': 'CB5教师改班' + TAG}])
    check('CB5.3', '教师**能**编辑班级（改班名）', r is True, 'write=%s err=%s' % (r, err))
    r, err = call_kw(tz, 'op.batch', 'unlink', [[FX['teacher_batch']]])
    check('CB5.4', '教师**不能**删除班级（无 unlink 权）',
          r is None and err, 'err=%s' % (err or '')[:200])

    # ---------------- CB6 回收站 ----------------
    print('== CB6 回收站：停用 → 可见 → 零副作用 → 恢复 ==')
    SNAP['sessions'] = pscalar('select count(*) from op_session where batch_id=%d'
                               % FX['batch_a'])
    SNAP['sc'] = pscalar('select count(*) from op_student_course where batch_id=%d'
                         % FX['batch_a'])
    SNAP['reg'] = pscalar('select count(*) from op_subject_registration where batch_id=%d'
                          % FX['batch_a'])
    SNAP['tok'] = pscalar('select count(*) from edu_attend_self_token where batch_id=%d'
                          % FX['batch_a'])
    r, err = call_kw(sz, 'op.batch', 'action_edu_stop', [[FX['batch_a']]])
    check('CB6.1', '教务「停用」班级（action_edu_stop）', r is True,
          'res=%s err=%s' % (r, err))
    act = psql('select active from op_batch where id=%d' % FX['batch_a'])
    check('CB6.2', '库里 active=false（回收站本体=基座 active，零新字段）',
          act.strip() == 'f', 'active=%s' % act.strip())
    ids, err = call_kw(sz, 'op.batch', 'search_read', [[], ['id']])
    live = {row['id'] for row in (ids or [])}
    check('CB6.3', '默认列表（active_test 生效）已看不见它',
          FX['batch_a'] not in live, '默认列表行数=%s' % len(live))
    ids, err = call_kw(sz, 'op.batch', 'search_read',
                       [[['active', '=', False]], ['id', 'name']],
                       {'context': {'active_test': False}})
    seen = {row['id']: row['name'] for row in (ids or [])}
    check('CB6.4', '回收站（已停用班级动作域）能看见它',
          FX['batch_a'] in seen, '回收站命中=%s' % seen.get(FX['batch_a']))
    stopped = probe(sa, '/student/timetable')
    check('CB6.5', '停用后学生侧不变：课表仍有该班课时（归档≠真删）',
          stopped.status_code == 200 and '暂无排课' not in stopped.text,
          'HTTP %s' % stopped.status_code)
    now = {
        'sessions': pscalar('select count(*) from op_session where batch_id=%d'
                            % FX['batch_a']),
        'sc': pscalar('select count(*) from op_student_course where batch_id=%d'
                      % FX['batch_a']),
        'reg': pscalar('select count(*) from op_subject_registration where batch_id=%d'
                       % FX['batch_a']),
        'tok': pscalar('select count(*) from edu_attend_self_token where batch_id=%d'
                       % FX['batch_a']),
    }
    check('CB6.6', '停用零副作用：课节/学生归属/注册单/签到令牌四个计数全不变',
          now == SNAP, '前 %s → 后 %s' % (SNAP, now))
    r, err = call_kw(sz, 'op.batch', 'action_edu_restore', [[FX['batch_a']]])
    ids, err2 = call_kw(sz, 'op.batch', 'search_read', [[], ['id']])
    live2 = {row['id'] for row in (ids or [])}
    check('CB6.7', '「恢复」后回到默认列表', r is True and FX['batch_a'] in live2,
          'restore=%s err=%s · 默认列表含=%s' % (r, err, FX['batch_a'] in live2))

    # ---------------- CB7 归档权限（校长拍板① + 设计 §10 档②） ----------------
    print('== CB7 归档权限：教师不能停用/恢复 ==')
    r, err = call_kw(tz, 'op.batch', 'write',
                     [[FX['batch_a']], {'active': False}])
    check('CB7.1', '教师改 active=false（停用）被拒',
          r is None and err and '教务处' in err, 'err=%s' % (err or '')[:200])
    check('CB7.2', '被拒后 active 未被改动（拒绝≠静默成功）',
          psql('select active from op_batch where id=%d' % FX['batch_a']).strip()
          == 't')
    r, err = call_kw(sz, 'op.batch', 'action_edu_stop', [[FX['batch_b']]])
    check('CB7.3', '（夹具）教务先把乙班停用', r is True, 'res=%s' % r)
    r, err = call_kw(tz, 'op.batch', 'write', [[FX['batch_b']], {'active': True}])
    check('CB7.4', '教师改 active=true（恢复）同样被拒',
          r is None and err and '教务处' in err, 'err=%s' % (err or '')[:200])
    r, err = call_kw(tz, 'op.batch', 'write', [[FX['batch_b']], {'active': True}])
    r2, err2 = call_kw(tz, 'op.batch', 'write',
                       [[FX['batch_a']], {'active': True}])
    check('CB7.5', '幂等写（值没变）不误伤教师：active=true 的班再写 true 通过',
          r2 is True, 'res=%s err=%s' % (r2, err2))
    # 教师改班名仍然可以（CB5.3 已证）；这里补一条：教务恢复乙班
    r, err = call_kw(sz, 'op.batch', 'action_edu_restore', [[FX['batch_b']]])
    check('CB7.6', '教务恢复乙班（把现场还原）', r is True, 'res=%s' % r)

    # ---------------- CB8 真删护栏 ----------------
    print('== CB8 真删护栏 ==')
    n0 = pscalar('select count(*) from op_batch')
    r, err = call_kw(sz, 'op.batch', 'unlink', [[FX['batch_a']]])
    check('CB8.1', '有课节的班删不掉（拒绝）', r is None and bool(err),
          'err=%s' % (err or '')[:160])
    check('CB8.2', '拒绝文案是人话且含「课节」+ 引导「停用」',
          bool(err) and '课节' in err and '停用' in err,
          'err=%s' % (err or '')[:300])
    check('CB8.3', '被拒后班级行仍在（「能走完」≠「没动数据」）',
          pscalar('select count(*) from op_batch where id=%d' % FX['batch_a']) == 1
          and pscalar('select count(*) from op_batch') == n0,
          'op_batch 行数 %s → %s' % (n0, pscalar('select count(*) from op_batch')))
    # 只有学生的班（丙班挂学生丙）
    r, err = call_kw(sz, 'op.student.course', 'create',
                     [[{'student_id': FX['stu_c'], 'course_id': COURSE_ID,
                        'batch_id': FX['batch_c'], 'state': 'running'}]])
    check('CB8.4', '（夹具）学生丙进丙班', bool(new_id(r)),
          'sc=%s err=%s' % (new_id(r) or r, err))
    r, err = call_kw(sz, 'op.batch', 'unlink', [[FX['batch_c']]])
    check('CB8.5', '「只有学生」的班也删不掉（防静默解绑）',
          r is None and bool(err) and '学生' in err,
          'err=%s' % (err or '')[:300])
    keep = psql('select batch_id from op_student_course where student_id=%d'
                % FX['stu_c'])
    check('CB8.6', '被拒后学生丙的班级归属未被清空（未发生 SET NULL）',
          keep.strip() == str(FX['batch_c']), 'batch_id=%s' % keep.strip())
    r, err = call_kw(sz, 'op.batch', 'unlink', [[FX['batch_empty']]])
    check('CB8.7', '零引用空班可真删（给「建错的班」留出口）',
          r is True and pscalar('select count(*) from op_batch where id=%d'
                                % FX['batch_empty']) == 0,
          'unlink=%s err=%s' % (r, err))
    alog = pscalar("select count(*) from edu_audit_log where action in "
                   "('停用班级','恢复班级','删班')")
    check('CB8.8', '归档/恢复/删班都有审计留痕（op.batch 无 tracking 字段）',
          alog >= 4, '审计行数=%s' % alog)

    # ---------------- CB9 同学可见性 ----------------
    print('== CB9 同班同学（校长拍板：只姓名 + 班名） ==')
    # 学生乙 = 甲的**同班同学**（夹具里已分到甲班）
    r, err = call_kw(sz, 'op.student.course', 'create',
                     [[{'student_id': FX['stu_b'], 'course_id': COURSE_ID,
                        'batch_id': FX['batch_a'], 'state': 'running'}]])
    check('CB9.1', '（夹具）学生乙分到甲班（成为同班同学）',
          bool(new_id(r)), 'sc=%s err=%s' % (new_id(r) or r, err))
    check('CB9.1b', '乙分班后「【待分配】」前缀同样被收口（同一条写路径）',
          pscalar('select count(*) from res_partner p join op_student s on '
                  's.partner_id=p.id where s.id=%d and p.name like %s'
                  % (FX['stu_b'], q(PENDING + '%'))) == 0,
          'name=%s' % psql('select p.name from res_partner p join op_student s '
                           'on s.partner_id=p.id where s.id=%d' % FX['stu_b']))
    page = probe(sa, '/my/contacts')
    sec = classmates_section(page.text or '')
    check('CB9.2', '学生甲 /my/contacts 200 且有「同班同学」段',
          page.status_code == 200 and sec is not None,
          'HTTP %s · 段长度=%s' % (page.status_code, len(sec or '')))
    sec = sec or ''
    check('CB9.3', '段内能看到同班同学乙的**姓名**', STU_NAME_B in sec,
          '期望=%s' % STU_NAME_B)
    check('CB9.4', '段内能看到**班名**', '甲班' in sec, '含甲班=%s' % ('甲班' in sec))
    check('CB9.5', '段内**没有**头像（无 img/avatar/web_image）',
          ('<img' not in sec and 'avatar' not in sec and 'web/image' not in sec),
          'img=%s avatar=%s webimage=%s'
          % ('<img' in sec, 'avatar' in sec, 'web/image' in sec))
    check('CB9.6', '段内**没有**邮箱 / 手机 / 学号',
          ('@' not in sec and 'fa-phone' not in sec and 'fa-envelope' not in sec
           and 'gr_no' not in sec),
          '含@=%s fa-phone=%s gr_no=%s'
          % ('@' in sec, 'fa-phone' in sec, 'gr_no' in sec))
    check('CB9.7', '段内显示「我的班级」', '我的班级' in sec)
    check('CB9.8', '越权反向断言：异班学生丙的姓名**不出现**在甲的页面里',
          FX['name_c'] and FX['name_c'] not in (page.text or ''),
          '含丙=%s' % (FX['name_c'] in (page.text or '')))
    check('CB9.9', '正对照：同班同学乙的姓名在整页出现（否则「丙不在」没意义）',
          STU_NAME_B in (page.text or ''))
    check('CB9.10', '学生看得到任课老师（老师组）',
          FX['faculty_name'] and FX['faculty_name'] in (page.text or ''),
          'faculty=%s' % FX['faculty_name'])
    ppage = probe(pz, '/my/contacts')
    check('CB9.11', '家长端**没有**「同班同学」段（家长看不到别人家孩子）',
          ppage.status_code == 200 and classmates_section(ppage.text or '') is None,
          'HTTP %s' % ppage.status_code)
    check('CB9.12', '家长页面不含学生乙/丙的姓名',
          STU_NAME_B not in (ppage.text or '')
          and FX['name_c'] not in (ppage.text or ''))

    # ---------------- CB10 清理 ----------------
    print('== CB10 清理（leftover = 0） ==')
    if args.keep:
        note('--keep：跳过清理，夹具保留现场')
    else:
        try:
            out2 = shell_json(fmt(CLEANUP, tag=TAG, login_a=LOGIN_A,
                                  login_b=LOGIN_B,
                                  base_students=FX.get('students_before', 0),
                                  base_users=FX.get('users_before', 0)))
            left = {k: v for k, v in out2.items()}
            named = {k: v for k, v in left.items()
                     if k not in ('students_now', 'users_now',
                                  'students_delta', 'users_delta')}
            check('CB10.1', '清理后 leftover = 0（班/学生/账号/邀请码/教师班）',
                  all(int(v or 0) == 0 for v in named.values()),
                  json.dumps(named, ensure_ascii=False))
            check('CB10.2', '总人数回到基线（按名字查会漏掉"名字非标记名"的残留）',
                  int(left.get('students_delta', 1)) == 0
                  and int(left.get('users_delta', 1)) == 0,
                  '学生 %s→%s（差 %s）· 账号 %s→%s（差 %s）'
                  % (FX.get('students_before'), left.get('students_now'),
                     left.get('students_delta'), FX.get('users_before'),
                     left.get('users_now'), left.get('users_delta')))
        except Exception as exc:
            check('CB10.1', '清理（odoo shell）', False, repr(exc)[:300])

    fails = [r for r in RESULTS if not r['pass']]
    rc = 1 if fails else 0
    write_results(rc=rc)
    print('\n== 汇总：%d 条断言，PASS %d / FAIL %d =='
          % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    for f in fails:
        print('  FAIL %s %s | %s' % (f['no'], f['name'], f['detail'][:200]))
    return rc


def write_results(rc=0):
    payload = {
        'revision': 'cb1',
        'when': subprocess.run(['date', '-Iseconds'], capture_output=True,
                               text=True).stdout.strip(),
        'base': BASE, 'db': DB,
        'design': 'docs/plans/class-batch-management-design.md',
        'fixture': FX,
        'snapshot': SNAP,
        'checks': RESULTS,
        'pass': len([r for r in RESULTS if r['pass']]),
        'fail': len([r for r in RESULTS if not r['pass']]),
        'rc': rc,
    }
    RESULTS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print('结果落盘：%s' % RESULTS_JSON)


if __name__ == '__main__':
    sys.exit(main())
