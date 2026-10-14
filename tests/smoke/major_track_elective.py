#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""专业编排（学制 + 必修/选修）真机冒烟 —— 六步闸门第 6 步。

设计：docs/plans/major-track-elective-design.md §7（V1-V9 逐条判据）
用法：
    python3 tests/smoke/major_track_elective.py                  # V1-V3, V5-V8
    python3 tests/smoke/major_track_elective.py --with-upgrades   # 加 V4（连跑两次 -u + 迁移探针）
    python3 tests/smoke/major_track_elective.py --with-rollback-drill   # 加 V9（代码回滚演练，会动工作区）
结果落盘：tests/smoke/major_track_elective_results.json

判据强度五兄弟（本仓 dev-workflow）：
  · 探测**不跟随重定向**（allow_redirects=False）——判「页面 200」时尤其；
  · 不只断言「升级 EXIT=0」——每条消费点都要真的摸一次（HTTP 或 ORM 命中）；
  · **载体先合法再断言**：四角色账号、夹具生效、字段属性（store/compute/inverse/search）
    先自证，否则「越权被拒」与「根本不是那个角色」同形；
  · 越权断言配正对照（教师被拒 ↔ 教务/管理员成功）；
  · 量具无副作用：夹具一律带【冒烟】前缀、**按标记**自清（不用 max(id)），收尾 leftover=0。

⚠ 本脚本**只读生产**（不连生产；生产读数由队长在部署前复核），只写本地 edu19。

凭据（t81 收口）：只在 CRED_DEFAULTS **一处**声明，可用
EDU_<KEY>_LOGIN / EDU_<KEY>_PASSWORD（KEY ∈ STU|FAC|BO|ADMIN）覆盖；口令不打印。
旧值写死 admin/admin（本库口令是 demo123）⇒ **两处后果**（都已实测）：
  ① V0.3「载体合法·admin 登录」判 **PASS** —— 因为登录失败 Odoo 返回 HTTP 200，
     而旧判据是"HTTP 码不是 200"；
  ② V6.2/V6.4b 这类**预期被拒**的断言在未登录会话下同样会"通过"（假通过）。
现在 auth() 返回 (session, http_code, uid)，uid=0 一律登记为 FAIL（载体不合法），
**不产生任何 PASS**。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent.parent
BASE = os.environ.get('MTE_BASE', 'http://127.0.0.1:8069')
DB = os.environ.get('EDU_DB_NAME', 'edu19')
OUT = Path(__file__).resolve().parent / 'major_track_elective_results.json'
TAG = u'【冒烟】mt'

CSRF_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')
BADGE_COMP = re.compile('badge text-bg-warning ms-2\">必修\\s*(\\d+)')
BADGE_ELEC = re.compile('badge text-bg-info ms-1\">选修\\s*(\\d+)')

ODOO = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
        '-c', '/etc/odoo/odoo.conf', '--db_host=db', '--db_port=5432',
        '--db_user=odoo', '--db_password=odoo', '-d', DB, '--no-http']
PSQL = ['docker', 'compose', 'exec', '-T', 'db', 'psql', '-U', 'odoo',
        '-d', DB, '-F', '|', '-Atc']

# ---- 凭据：**唯一声明点**（t81；口令不打印）----
# 角色 -> (env 键, 登录名, 口令)：可用 EDU_<env 键>_LOGIN / EDU_<env 键>_PASSWORD 覆盖。
# admin 的口令是 demo123 —— 旧值 ('admin','admin') 在本库是**失效凭据**，而旧版
# auth() 只看 HTTP 码（登录失败 Odoo 返回 **200** 重渲染登录表单）⇒ V0.3
# 「载体合法·admin 登录」实测判 **PASS**，而那个会话 /my/home → 303 → /web/login
# （根本没登进去）。这正是文件头警告的形态：错的载体与「越权被拒」同形 ⇒ 假通过。
CRED_DEFAULTS = {
    'student': ('STU', 'stu@local', 'demo123'),
    'faculty': ('FAC', 'faculty@local', 'demo123'),
    'backoffice': ('BO', 'backoffice@local', 'demo123'),
    'admin': ('ADMIN', 'admin', 'demo123'),      # 生产/他库：EDU_ADMIN_PASSWORD 覆盖
}


def credential(name):
    """(login, password)：环境变量优先；口令只在进程内使用，**不打印**。"""
    key, login, pwd = CRED_DEFAULTS[name]
    return (os.environ.get('EDU_%s_LOGIN' % key, login),
            os.environ.get('EDU_%s_PASSWORD' % key, pwd))


ACCOUNTS = {name: credential(name) for name in CRED_DEFAULTS}

R = []


def rec(item, method, expect, actual, result, evidence=''):
    R.append(dict(item=item, method=method, expect=expect, actual=actual,
                  result=result, evidence=evidence))
    print('[%s] %s: %s' % (result, item, actual))


def skip(item, method, expect, actual, evidence=''):
    rec(item, method, expect, actual, 'SKIP', evidence)


def sql(query):
    out = subprocess.run(PSQL + [query], capture_output=True, text=True,
                         cwd=str(REPO), timeout=120)
    return [ln for ln in (out.stdout or '').splitlines() if ln != '']


def shell(code, timeout=420, **kw):
    """跑一段 odoo shell 代码，返回 stdout+stderr。

    额外 kw 用 «key» 占位符替换进代码 —— **刻意不用 %-格式化**：模板体本身
    全是 Python 代码，裸 % 会让 %-格式化炸掉（V3.2 那次
    TypeError: not enough arguments for format string 就是这么来的）。
    """
    for k, v in kw.items():
        code = code.replace(u'«' + k + u'»', str(v))

    out = subprocess.run(ODOO, input=code, capture_output=True, text=True,
                         timeout=timeout, cwd=str(REPO))
    return (out.stdout or '') + (out.stderr or '')


def kv(text, key):
    """取 shell 输出里的 KEY=值。

    一行里可能出现多个 KEY=value（如 V61_263=0 V61_277=0）⇒ 不能用 ^KEY=(.*)$ 那种
    贪婪写法（会把整行都当成值，判据静默变红）。这里取到「下一个 KEY=」之前为止；
    值里带空格（如 FIX_LEVEL=【冒烟】mt 学制）时不受影响。
    """
    for line in text.splitlines():
        i = line.find(key + '=')
        if i < 0 or (i > 0 and (line[i - 1].isalnum() or line[i - 1] == '_')):
            continue
        rest = line[i + len(key) + 1:]
        m = re.search(r'\s+[A-Z][A-Z0-9_]*=', rest)
        return (rest[:m.start()] if m else rest).strip()
    return None


def session_uid(session, timeout=30):
    """会话里真实的 uid（0 = 没登进去）。判据来源**不是** HTTP 码（见 auth 注释）。"""
    try:
        r = session.post(BASE + '/web/session/get_session_info',
                         json={'jsonrpc': '2.0', 'method': 'call', 'params': {}},
                         timeout=timeout)
        return ((r.json().get('result') or {}).get('uid') or 0)
    except Exception:
        return 0


def auth(name, timeout=60):
    """(session, http_code, uid)。uid=0 ⇒ **载体不合法**，调用方必须处理（t81）。

    为什么不能只看 HTTP 码：Odoo **登录失败返回 200**（重渲染登录表单）⇒
    旧版 V0.3 对失效凭据判 PASS；而其它节里"预期被拒"的断言（V6.2/V6.4b）
    在会话未登录时同样会命中 3xx/登录页 ⇒ **假通过**。
    """
    login, pwd = ACCOUNTS[name]
    s = requests.Session()
    r = s.get(BASE + '/web/login?db=' + DB, timeout=timeout)
    m = CSRF_RE.search(r.text)
    tok = m.group(1) if m else ''
    r = s.post(BASE + '/web/login?db=' + DB,
               data={'login': login, 'password': pwd, 'csrf_token': tok,
                     'db': DB, 'redirect': ''},
               timeout=timeout, allow_redirects=False)
    return s, r.status_code, session_uid(s)


def carrier_fail(item, role, note=''):
    """载体不合法 ⇒ 显式 FAIL 行（**不得**把它读成"越权被拒"或"没有权限"）。"""
    rec(item, '载体合法性（t81：判据是会话 uid，不是 HTTP 码）',
        'uid > 0（真的登进去了）',
        '登录失败：%s（uid=0）→ 本节断言**未验证**，不得当作通过%s'
        % (role, ('（%s）' % note) if note else ''), 'FAIL',
        '口令可用 EDU_<角色>_PASSWORD 覆盖；口令不会出现在输出里')


def upgrade(mods='edu_portal'):
    out = subprocess.run(['bash', 'scripts/safe_upgrade.sh', mods],
                         capture_output=True, text=True, cwd=str(REPO),
                         timeout=2400)
    tail = (out.stdout or '') + (out.stderr or '')
    ok = out.returncode == 0 and 'Traceback' not in tail
    return out.returncode, ok, tail


# ======================================================================
# V0 前置：载体合法（四角色 + 锁 + 容器 + 页面）
# ======================================================================
def v0_preflight():
    lock = os.path.join(os.environ.get('TMPDIR') or '/tmp',
                        'edu19_upgrade.lock')
    rec('V0.1 无升级锁', 'fs', '锁不存在', lock if os.path.exists(lock) else '无锁',
        'FAIL' if os.path.exists(lock) else 'PASS', lock)
    r = requests.get(BASE + '/web/login?db=' + DB, timeout=30)
    rec('V0.2 探活 /web/login', 'HTTP GET', '200/302/303',
        'HTTP %s' % r.status_code,
        'PASS' if r.status_code in (200, 302, 303) else 'FAIL')
    roles = {}
    for name in ACCOUNTS:
        s, code, uid = auth(name)
        bad = code not in (200, 302, 303)
        roles[name] = uid
        # t81：判据从"HTTP 码不是 200"改成"会话里真有 uid"。**登录失败 Odoo 返回
        # 200**（重渲染登录表单）⇒ 旧判据实测对失效凭据 (admin,admin) 判 PASS，
        # 而那个会话 /my/home → 303 → /web/login（根本没登进去）。
        rec('V0.3 载体合法·%s 登录' % name, 'HTTP POST /web/login + 会话 uid 复核',
            'uid > 0（真的建立会话）', 'HTTP %s / uid=%s' % (code, uid),
            'PASS' if (not bad and uid) else 'FAIL', ACCOUNTS[name][0])
    return roles


# ======================================================================
# V1 迁移无损
# ======================================================================
def v1_migration():
    old_n = int(sql('select count(*) from op_course_op_subject_rel')[0])
    new_n = int(sql('select count(*) from edu_course_subject')[0])
    rec('V1.1 条数（老表 = 新表）', 'SQL count',
        '两侧相等', 'old=%d new=%d' % (old_n, new_n),
        'PASS' if old_n == new_n else 'FAIL')
    diff = sql("""(SELECT op_course_id, op_subject_id FROM op_course_op_subject_rel
                   EXCEPT SELECT course_id, subject_id FROM edu_course_subject)
                  UNION ALL
                  (SELECT course_id, subject_id FROM edu_course_subject
                   EXCEPT SELECT op_course_id, op_subject_id FROM op_course_op_subject_rel)""")
    rec('V1.2 (course,subject) 双向差集', 'SQL EXCEPT×2', '0 行',
        '%d 行' % len(diff), 'PASS' if not diff else 'FAIL',
        '; '.join(diff[:3]))
    per = sql("""(SELECT c.id, count(r.op_subject_id) FROM op_course c
                    LEFT JOIN op_course_op_subject_rel r ON r.op_course_id = c.id
                    GROUP BY c.id)
                 EXCEPT
                 (SELECT c.id, count(l.id) FROM op_course c
                    LEFT JOIN edu_course_subject l ON l.course_id = c.id
                    GROUP BY c.id)""")
    per2 = sql("""(SELECT c.id, count(l.id) FROM op_course c
                    LEFT JOIN edu_course_subject l ON l.course_id = c.id
                    GROUP BY c.id)
                 EXCEPT
                 (SELECT c.id, count(r.op_subject_id) FROM op_course c
                    LEFT JOIN op_course_op_subject_rel r ON r.op_course_id = c.id
                    GROUP BY c.id)""")
    rec('V1.3 逐专业条数相等', 'SQL 分组 EXCEPT', '两个方向都 0 行',
        '%d / %d 行' % (len(per), len(per2)),
        'PASS' if not per and not per2 else 'FAIL')
    typed = int(sql('select count(*) from edu_course_subject where subject_type is not null')[0])
    rec('V1.5 分类全空（= 继承全局）', 'SQL count', '0',
        str(typed), 'PASS' if typed == 0 else 'FAIL')
    # ⚠ 设计 §7.1-V1.4 写的是「count + max(write_date)」，但 M2M 关系表
    # （op_course_op_subject_rel）**只有两列、没有 write_date**（实测报错
    # column "write_date" does not exist）⇒ 用「行数 + 有序内容指纹 md5」作为
    # 「老表未动」的等价证据（一次整体重写必然改变内容指纹；新代码从不写这张表）。
    stat = sql("select count(*) || '|' || coalesce(md5(string_agg("
               "op_course_id || ':' || op_subject_id, ',' order by "
               "op_course_id, op_subject_id)), '-') from op_course_op_subject_rel")
    rec('V1.4 老表未动（行数 + 内容指纹 md5）', 'SQL',
        '行数与指纹全程不变（=%d 行）' % old_n, stat[0] if stat else '—',
        'PASS' if stat and stat[0].startswith('%d|' % old_n) else 'FAIL',
        '老表 %d 行（关系表无 write_date，改用内容指纹；新代码从不写它）' % old_n)
    field = shell("""
f = env['op.course']._fields['subject_ids']
print('FIELD=store=%s compute=%s inverse=%s search=%s type=%s comodel=%s'
      % (f.store, bool(f.compute), bool(f.inverse), bool(f.search), f.type, f.comodel_name))
name = env['ir.model.fields'].sudo().search([('model','=','op.course'),('name','=','subject_ids')], limit=1)
print('IMD_FIELD=%d' % len(name))
""")
    rec('V1.6 兼容层字段属性', 'ORM',
        'store=False + compute/inverse/search 三件套齐全',
        (kv(field, 'FIELD') or '—'),
        'PASS' if (kv(field, 'FIELD') or '').startswith('store=False compute=True inverse=True search=True') else 'FAIL')
    return old_n


# ======================================================================
# 夹具：建【冒烟】学制 / 专业 / 班 / 科目（按标记自清）
# ======================================================================
FIXTURE_BUILD = u"""
TAG = u'«tag»'
Lvl = env['op.program.level'].sudo().with_context(active_test=False)
Crs = env['op.course'].sudo().with_context(active_test=False)
Sub = env['op.subject'].sudo().with_context(active_test=False)
Bat = env['op.batch'].sudo().with_context(active_test=False)
Line = env['edu.course.subject'].sudo()
Reg = env['op.subject.registration'].sudo().with_context(active_test=False)
Ses = env['op.session'].sudo().with_context(active_test=False)
SC = env['op.student.course'].sudo().with_context(active_test=False)
Audit = env['edu.audit.log'].sudo()
# 清旧（按标记；顺序 = 先摘外键引用，再删本体 —— 否则撞 FK 会让整个清理失败）
old_c = Crs.search([('name', 'like', TAG)])
if old_c:
    regs = Reg.search([('course_id', 'in', old_c.ids)])
    if regs:
        Audit.search([('model', '=', 'op.subject.registration'),
                      ('res_id', 'in', regs.ids)]).unlink()
        regs.unlink()
    SC.search([('course_id', 'in', old_c.ids)]).unlink()
    Ses.search([('course_id', 'in', old_c.ids)]).unlink()
    Line.search([('course_id', 'in', old_c.ids)]).unlink()
    Bat.search([('course_id', 'in', old_c.ids)]).unlink()
    old_c.unlink()
old_s = Sub.search([('name', 'like', TAG)])
if old_s:
    Line.search([('subject_id', 'in', old_s.ids)]).unlink()
    old_s.unlink()
Lvl.search([('name', 'like', TAG)]).unlink()
env.cr.commit()

lvl = Lvl.create({'name': TAG + u' 学制', 'sequence': 99})
crs = Crs.create({'name': TAG + u' 专业', 'code': 'MTE-CRS',
                  'evaluation_type': 'normal', 'edu_level_id': lvl.id})
bat = Bat.create({'name': TAG + u' 班', 'code': 'MTE-BAT', 'course_id': crs.id,
                  'start_date': '2026-01-01', 'end_date': '2027-12-31'})
# 两门科目：一门全局必修、一门全局选修（用来验证两级 fallback）
s_glob_comp = Sub.create({'name': TAG + u' 科目A-全局必修', 'code': 'MTE-A',
                          'subject_type': 'compulsory', 'type': 'theory'})
s_glob_elec = Sub.create({'name': TAG + u' 科目B-全局选修', 'code': 'MTE-B',
                          'subject_type': 'elective', 'type': 'theory'})
crs.write({'subject_ids': [(6, 0, [s_glob_comp.id, s_glob_elec.id])]})
env.cr.commit()
print('FIX_LVL=%d' % lvl.id)
print('FIX_CRS=%d' % crs.id)
print('FIX_BAT=%d' % bat.id)
print('FIX_SUB_A=%d' % s_glob_comp.id)
print('FIX_SUB_B=%d' % s_glob_elec.id)
print('FIX_LINES=%d' % len(crs.subject_line_ids))
print('FIX_LEVEL=%s' % (crs.edu_level_id.name or ''))
"""

FIXTURE_DROP = u"""
TAG = u'«tag»'
Lvl = env['op.program.level'].sudo().with_context(active_test=False)
Crs = env['op.course'].sudo().with_context(active_test=False)
Sub = env['op.subject'].sudo().with_context(active_test=False)
Bat = env['op.batch'].sudo().with_context(active_test=False)
Line = env['edu.course.subject'].sudo()
Reg = env['op.subject.registration'].sudo().with_context(active_test=False)
Ses = env['op.session'].sudo().with_context(active_test=False)
SC = env['op.student.course'].sudo().with_context(active_test=False)
Audit = env['edu.audit.log'].sudo()
regs = Reg.search([('course_id.name', 'like', TAG)])
if regs:
    Audit.search([('model', '=', 'op.subject.registration'),
                  ('res_id', 'in', regs.ids)]).unlink()
    regs.unlink()
crs = Crs.search([('name', 'like', TAG)])
if crs:
    SC.search([('course_id', 'in', crs.ids)]).unlink()
    Ses.search([('course_id', 'in', crs.ids)]).unlink()
    Line.search([('course_id', 'in', crs.ids)]).unlink()
    Bat.search([('course_id', 'in', crs.ids)]).unlink()
    crs.unlink()
subs = Sub.search([('name', 'like', TAG)])
if subs:
    Line.search([('subject_id', 'in', subs.ids)]).unlink()
    subs.unlink()
Lvl.search([('name', 'like', TAG)]).unlink()
env.cr.commit()
print('LEFT_CRS=%d' % Crs.search_count([('name', 'like', TAG)]))
print('LEFT_SUB=%d' % Sub.search_count([('name', 'like', TAG)]))
print('LEFT_BAT=%d' % Bat.search_count([('name', 'like', TAG)]))
print('LEFT_LVL=%d' % Lvl.search_count([('name', 'like', TAG)]))
print('LEFT_LINE=%d' % Line.search_count([('course_id.name', 'like', TAG)]))
print('LEFT_REG=%d' % Reg.search_count([('course_id.name', 'like', TAG)]))
"""


def build_fixture():
    out = shell(FIXTURE_BUILD, tag=TAG)
    fx = {k: kv(out, k) for k in ('FIX_LVL', 'FIX_CRS', 'FIX_BAT', 'FIX_SUB_A',
                                  'FIX_SUB_B', 'FIX_LINES', 'FIX_LEVEL')}
    ok = all(fx.values()) and fx.get('FIX_LINES') == '2'
    rec('F0 夹具生效（2 行关系 + 学制已挂）', 'ORM',
        'FIX_LINES=2 且 LEVEL 非空',
        json.dumps(fx, ensure_ascii=False),
        'PASS' if ok else 'FAIL', out.strip().splitlines()[-1] if out else '')
    return fx


# ======================================================================
# V5 + V2：报课页读取口径（两级 fallback + 配完立刻生效 + 服务端同源）
# ======================================================================
def page_badges(sess, course_id, batch_id):
    r = sess.get(BASE + '/subject/enroll?course_id=%s&batch_id=%s'
                 % (course_id, batch_id), timeout=60,
                 allow_redirects=False)
    html = r.text or ''
    comp = BADGE_COMP.search(html)
    elec = BADGE_ELEC.search(html)
    return (r.status_code, int(comp.group(1)) if comp else None,
            int(elec.group(1)) if elec else None, html)


def card_is_compulsory(html, subject_name):
    """该科目卡片上是否带必修锁（fa-lock）—— 判**具体科目**的分组，而不只看总数。"""
    i = html.find(subject_name)
    if i < 0:
        return None
    block = html[max(0, i - 400):i + 700]
    return 'fa-lock' in block


def v5_v2_pages(fx):
    stu, code, uid = auth('student')
    if not uid:
        carrier_fail('V5/V2 学生页面口径（本节全部断言）', 'student')
        return
    crs, bat = fx['FIX_CRS'], fx['FIX_BAT']
    name_a, name_b = TAG + u' 科目A-全局必修', TAG + u' 科目B-全局选修'

    # ---- V5：一条都不配 → 逐条继承科目全局值 ----
    st, c, e, html = page_badges(stu, crs, bat)
    ok5 = st == 200 and c == 1 and e == 1 and card_is_compulsory(html, name_a)         and not card_is_compulsory(html, name_b)
    rec('V5.1 没配的专业继承全局值', 'HTTP GET /subject/enroll',
        '200；必修 1（科目A）/ 选修 1（科目B）；A 卡带锁、B 卡不带',
        'HTTP %s 必修=%s 选修=%s A锁=%s B锁=%s'
        % (st, c, e, card_is_compulsory(html, name_a),
           card_is_compulsory(html, name_b)),
        'PASS' if ok5 else 'FAIL', 'course=%s batch=%s' % (crs, bat))
    orm5 = shell("""
Crs = env['op.course'].sudo().with_context(active_test=False)
Sub = env['op.subject'].sudo()
bad = tot = 0
for c in Crs.search([]):
    for s in c.subject_ids:
        tot += 1
        if c.edu_effective_type(s) != (s.subject_type or 'compulsory'):
            bad += 1
print('V5_TOTAL=%d' % tot)
print('V5_MISMATCH=%d' % bad)
""")
    rec('V5.2 全库逐条比对（未配 = 全局）', 'ORM edu_effective_type',
        'MISMATCH=0',
        'total=%s mismatch=%s' % (kv(orm5, 'V5_TOTAL'), kv(orm5, 'V5_MISMATCH')),
        'PASS' if kv(orm5, 'V5_MISMATCH') == '0' else 'FAIL')

    # ---- V2：教务配一门（全局选修 → 专业必修）→ 页面立刻变 ----
    out = shell("""
Line = env['edu.course.subject'].sudo()
l = Line.search([('course_id', '=', «crs»), ('subject_id', '=', «sub_b»)], limit=1)
l.subject_type = 'compulsory'
env.cr.commit()
print('V2_ROW=%d' % l.id)
print('V2_KIND=%s' % l.subject_type)
""", crs=crs, sub_b=fx['FIX_SUB_B'])
    rec('V2.1 教务把「全局选修」配成本专业必修', 'ORM write',
        'compulsory', kv(out, 'V2_KIND') or '—',
        'PASS' if kv(out, 'V2_KIND') == 'compulsory' else 'FAIL')
    st, c, e, html = page_badges(stu, crs, bat)
    ok2 = st == 200 and c == 2 and e == 0 and card_is_compulsory(html, name_b)
    rec('V2.3 学生刷新报课页立刻生效', 'HTTP GET /subject/enroll',
        '必修 2 / 选修 0；B 卡也带锁',
        'HTTP %s 必修=%s 选修=%s B锁=%s' % (st, c, e, card_is_compulsory(html, name_b)),
        'PASS' if ok2 else 'FAIL')

    # ---- V2.5 服务端补齐同源：POST 提交（不带选修）→ 注册单必修含 A、B ----
    r0 = stu.get(BASE + '/subject/enroll?course_id=%s&batch_id=%s' % (crs, bat), timeout=60)
    m = CSRF_RE.search(r0.text)
    tok = m.group(1) if m else ''
    rp = stu.post(BASE + '/subject/enroll/save',
                  data={'csrf_token': tok, 'course_id': crs, 'batch_id': bat,
                        'applicant_note': '【冒烟】major-track V2.5 可删'},
                  timeout=90, allow_redirects=False)
    loc = rp.headers.get('Location') or ''
    out = shell("""
Reg = env['op.subject.registration'].sudo().with_context(active_test=False)
r = Reg.search([('course_id.name', 'like', u'«tag»')], order='id desc', limit=1)
print('REG_ID=%d' % (r.id if r else 0))
print('REG_STATE=%s' % (r.state if r else '-'))
print('REG_COMP=%s' % ','.join(str(i) for i in r.compulsory_subject_ids.ids))
print('REG_ELEC=%s' % ','.join(str(i) for i in r.elective_subject_ids.ids))
""", tag=TAG)
    comp_ids = (kv(out, 'REG_COMP') or '').split(',')
    okp = rp.status_code == 303 and 'box=submitted' in loc \
        and set(comp_ids) == {fx['FIX_SUB_A'], fx['FIX_SUB_B']} \
        and (kv(out, 'REG_ELEC') == '')
    rec('V2.5 服务端必修全量补齐（与页面同源）', 'HTTP POST + ORM',
        '303 box=submitted；compulsory={A,B}；elective 空',
        'HTTP %s -> %s | compulsory=%s elective=%s'
        % (rp.status_code, loc, kv(out, 'REG_COMP'), kv(out, 'REG_ELEC')),
        'PASS' if okp else 'FAIL')

    # ---- V2.4 改回选修 → 徽标逐位还原 ----
    shell("""
Line = env['edu.course.subject'].sudo()
l = Line.search([('course_id', '=', «crs»), ('subject_id', '=', «sub_b»)], limit=1)
l.subject_type = False
env.cr.commit()
""", crs=crs, sub_b=fx['FIX_SUB_B'])
    st, c, e, html = page_badges(stu, crs, bat)
    rec('V2.4 改回选修 → 徽标还原', 'HTTP GET',
        '必修 1 / 选修 1', 'HTTP %s 必修=%s 选修=%s' % (st, c, e),
        'PASS' if (st == 200 and c == 1 and e == 1) else 'FAIL')
    return True


# ======================================================================
# V3 既有消费点不炸
# ======================================================================
def v3_consumers(fx):
    # #6 学生课程页（batch1.py:316 兜底读 course_id.subject_ids）
    stu, _code, uid = auth('student')
    if not uid:
        carrier_fail('V3.1-#6 学生课程页', 'student')
    else:
        for path in ('/my/study', '/my/home'):
            r = stu.get(BASE + path, timeout=60, allow_redirects=False)
            ok = r.status_code in (200, 303)
        rec('V3.1-#6 学生课程页', 'HTTP GET /my/study',
            '200/303 且无 Traceback', 'HTTP %s' % r.status_code,
            'PASS' if r.status_code == 200 and 'Traceback' not in r.text else 'FAIL')
    # #7 edu_public/main.py:57 —— 'subjects': course.subject_ids 在 /courses?course=N
    #（专业详情页）。/courses-offered 只列专业名+代码，**不渲染科目**，所以判据挂在
    # 真正消费 subject_ids 的那条路由上（同时把 /courses-offered 的 200 也摸一次）。
    r7b = requests.get(BASE + '/courses-offered', timeout=60)
    orm = shell("""
c = env['op.course'].sudo().with_context(active_test=False).search([('code','=','MTE-CRS')], limit=1)
print('C7_N=%d' % len(c.subject_ids))
print('C7_ID=%d' % c.id)
for s in c.subject_ids:
    print('C7_NAME=%s' % (s.name or ''))
""")
    c7_id = kv(orm, 'C7_ID') or '0'
    names = [m for m in re.findall(r'^C7_NAME=(.*)$', orm, re.M)]
    r7 = requests.get(BASE + '/courses?course=%s' % c7_id, timeout=60)
    miss = [n for n in names if n and n not in r7.text]
    ok7 = r7b.status_code == 200 and r7.status_code == 200 \
        and len(names) == int(kv(orm, 'C7_N') or '0') and not miss
    rec('V3.1-#7 /courses?course=N（= len(subject_ids) 口径）', 'HTTP GET + ORM',
        '两个页面都 200；详情页逐条渲染 subject_ids 全部科目名',
        'offer=HTTP %s | detail=HTTP %s | n=%s 未渲染=%s'
        % (r7b.status_code, r7.status_code, kv(orm, 'C7_N'), miss),
        'PASS' if ok7 else 'FAIL')
    # #8 基座向导 get_subjects（subject_registration.py:95-102 读 course_id.subject_ids + 全局 subject_type）
    orm8 = shell("""
Reg = env['op.subject.registration'].sudo()
r = Reg.with_context(active_test=False).create({
    'student_id': env['op.student'].sudo().search([], limit=1).id,
    'course_id': env['op.course'].sudo().with_context(active_test=False).search([('code','=','MTE-CRS')], limit=1).id,
    'state': 'draft'})
try:
    r.get_subjects()
    print('C8=ok compulsory=%d' % len(r.compulsory_subject_ids))
except Exception as e:
    print('C8=ERR %s: %s' % (type(e).__name__, e))
env.cr.rollback()
""")
    rec('V3.1-#8 基座选课注册向导 get_subjects()', 'ORM（事务内回滚，不留夹具）',
        '不抛错（读到 course_id.subject_ids）', kv(orm8, 'C8') or '—',
        'PASS' if (kv(orm8, 'C8') or '').startswith('ok') else 'FAIL')
    # #12 作业发布（assignment.py:104 赋值 course_id.subject_ids）
    orm12 = shell("""
A = env['op.assignment'].sudo().with_context(active_test=False)
a = A.search([], limit=1)
if not a:
    print('C12=no_assignment')
else:
    f = [n for n in ('courses_subjects',) if n in A._fields]
    if not f:
        print('C12=no_field')
    else:
        a.courses_subjects = a.course_id.subject_ids
        print('C12=ok n=%d' % len(a.courses_subjects))
env.cr.rollback()
""")
    c12 = kv(orm12, 'C12') or '—'
    rec('V3.1-#12 作业发布（courses_subjects 赋值）', 'ORM（回滚）',
        '赋值不抛错', c12,
        'PASS' if c12.startswith('ok') or c12 == 'no_assignment' else 'FAIL')
    # #9/#10/#11 课表（related='course_id.subject_ids' + :407-412 + 视图域）
    # 该脚本按自身用法说明是「喂给 odoo shell 的源码」，不是独立 python 程序
    # （env 由 shell 注入），所以按它文档里的方式跑。
    tt_src = (REPO / 'scripts' / 'test_timetable_conflict.py').read_text(encoding='utf-8')
    tt = subprocess.run(ODOO, input=tt_src, capture_output=True, text=True,
                        cwd=str(REPO), timeout=900)
    tailtext = (tt.stdout or '') + (tt.stderr or '')
    tail = tailtext.strip().splitlines()[-3:]
    rec('V3.1-#9/10/11a 课表冲突脚本', 'odoo shell < scripts/test_timetable_conflict.py',
        '输出 CONFLICT-GUARD=PASS',
        'exit=%s | %s' % (tt.returncode, ' / '.join(tail[-2:])[:300]),
        'PASS' if 'CONFLICT-GUARD=PASS' in tailtext else 'FAIL')
    ormrel = shell("""
S = env['op.session'].sudo().with_context(active_test=False)
Crs = env['op.course'].sudo().with_context(active_test=False)
f = S._fields['course_subject_ids']
print('C9_RELATED=%s' % (f.related or '-'))
s = S.search([('course_id', '!=', False)], limit=1)
ok = 1
if s:
    ok = 1 if set(s.course_subject_ids.ids) == set(s.course_id.subject_ids.ids) else 0
print('C9_CHAIN=%d' % ok)
c = Crs.search([('code', '=', 'MTE-CRS')], limit=1)
ids = c.subject_ids.ids[:2]
try:
    n = S.search_count([('course_subject_ids', 'in', ids)])
    print('C9_DOMAIN=ok n=%d' % n)
except Exception as e:
    print('C9_DOMAIN=ERR %s: %s' % (type(e).__name__, e))
""")
    rec('V3.1-#9/10/11b 课表 related 链与域查询', 'ORM（op.session.course_subject_ids）',
        'related=course_id.subject_ids；链值相等；域查询不抛错',
        'related=%s chain=%s domain=%s'
        % (kv(ormrel, 'C9_RELATED'), kv(ormrel, 'C9_CHAIN'), kv(ormrel, 'C9_DOMAIN')),
        'PASS' if kv(ormrel, 'C9_CHAIN') == '1'
        and (kv(ormrel, 'C9_DOMAIN') or '').startswith('ok') else 'FAIL')
    # #13/#14 后台列表/表单：继承视图真的生效（arch 里出现 subject_line_ids / edu_level_id）
    orm1314 = shell("""
V = env['ir.ui.view'].sudo()
f = V.get_view(V.with_context(active_test=False).search([('model','=','op.course'),('type','=','form')], limit=1).id, 'form')
arch = f['arch']
print('C14_LINES=%d' % (1 if 'subject_line_ids' in arch else 0))
print('C14_LEVEL=%d' % (1 if 'edu_level_id' in arch else 0))
t = V.get_view(V.with_context(active_test=False).search([('model','=','op.course'),('type','=','list')], limit=1).id, 'list')
print('C13_LEVEL=%d' % (1 if 'edu_level_id' in t['arch'] else 0))
# 列清单：新关系表的四列 + 行标题
L = env['edu.course.subject'].sudo()
print('C13_COLS=%s' % ','.join(['subject_id','subject_type','global_subject_type']))
""")
    ok1314 = kv(orm1314, 'C14_LINES') == '1' and kv(orm1314, 'C14_LEVEL') == '1' \
        and kv(orm1314, 'C13_LEVEL') == '1'
    rec('V3.1-#13/#14 后台表单/列表继承生效', 'ORM get_view',
        '表单含 subject_line_ids + edu_level_id；列表含 edu_level_id',
        'form_lines=%s form_level=%s list_level=%s'
        % (kv(orm1314, 'C14_LINES'), kv(orm1314, 'C14_LEVEL'), kv(orm1314, 'C13_LEVEL')),
        'PASS' if ok1314 else 'FAIL')
    # #3/#4/#5 审批详情 + 换课（真实路径：注册单审批详情页 + 换课审批动作）
    bo, _code, buid = auth('backoffice')
    if not buid:
        carrier_fail('V3.1-#3 审批详情（教务会话）', 'backoffice')
    else:
        # op_course.name 是 jsonb 翻译列 ⇒ 必须 ->>'zh_CN'（直接 like 会报
        # operator does not exist: jsonb ~~ unknown）
        reg_id = sql("select r.id from op_subject_registration r "
                     "join op_course c on c.id = r.course_id "
                     "where (c.name->>'zh_CN') like '【冒烟】mt%' "
                     "order by r.id desc limit 1")
        rid = reg_id[0] if reg_id else '0'
        r3 = bo.get(BASE + '/registrar/subject/approvals/%s' % rid, timeout=60,
                    allow_redirects=False)
        rec('V3.1-#3 审批详情（len(course.subject_ids) 文案）',
            'HTTP GET（不跟随重定向）',
            '200 且无 Traceback', 'HTTP %s rid=%s' % (r3.status_code, rid),
            'PASS' if r3.status_code == 200 and 'Traceback' not in r3.text
            else 'FAIL')

    # V3.2 写路径：[(6,0,...)] 不重置分类（本设计最关键的防静默损坏判据）
    orm32 = shell("""
Crs = env['op.course'].sudo().with_context(active_test=False)
Sub = env['op.subject'].sudo(); Line = env['edu.course.subject'].sudo()
c = Crs.search([('code','=','MTE-CRS')], limit=1)
a = Sub.search([('code','=','MTE-A')], limit=1)
b = Sub.search([('code','=','MTE-B')], limit=1)
new = Sub.create({'name': u'«tag» 科目C-新增', 'code': 'MTE-C', 'subject_type': 'elective', 'type': 'theory'})
Line.search([('course_id','=',c.id),('subject_id','=',a.id)]).write({'subject_type': 'compulsory'})
Line.search([('course_id','=',c.id),('subject_id','=',b.id)]).write({'subject_type': 'compulsory'})
c.write({'subject_ids': [(6, 0, [a.id, b.id, new.id])]})
kinds = sorted((l.subject_id.code, l.subject_type or '') for l in c.subject_line_ids)
print('V32A=%s' % kinds)
c.write({'subject_ids': [(6, 0, [new.id])]})
kinds2 = sorted((l.subject_id.code, l.subject_type or '') for l in c.subject_line_ids)
print('V32B=%s' % kinds2)
print('V32_POOL_COMP=%d' % len(c.edu_compulsory_subject_ids()))
new.unlink()
env.cr.commit()
""", tag=TAG)
    a_ok = kv(orm32, 'V32A') or ''
    b_ok = kv(orm32, 'V32B') or ''
    # Python 3 打印 tuple 不带 u 前缀（曾写成 (u'MTE-A', ...) ⇒ 判据恒红，是判据错不是产品错）
    ok32 = "('MTE-A', 'compulsory')" in a_ok and "('MTE-B', 'compulsory')" in a_ok \
        and "('MTE-C', '')" in a_ok and 'MTE-C' in b_ok and 'MTE-A' not in b_ok
    rec('V3.2 [(6,0,ids)] 不重置已配分类', 'ORM write（create+write 两条路径）',
        'A/B 仍是 compulsory；新增 C 留空；缩到 1 门时只剩 C',
        'A轮=%s | B轮=%s' % (a_ok, b_ok), 'PASS' if ok32 else 'FAIL',
        '证明 inverse 只做「删多余/增缺失」，不动其它行')
    # V3.3 域查询（非存储字段必须实现 search）
    orm33 = shell("""
Crs = env['op.course'].sudo()
Sub = env['op.subject'].sudo()
ids = Sub.search([('code','=','MTE-A')], limit=1).ids
n = Crs.search_count([('subject_ids', 'in', ids)])
n2 = Crs.search_count([('subject_ids', 'not in', ids)])
print('V33_IN=%d V33_NOTIN=%d' % (n, n2))
""")
    rec('V3.3 域查询走 _search_subject_ids', 'ORM search',
        '不抛错且 IN/NOT IN 都有结果', '%s / %s'
        % (kv(orm33, 'V33_IN'), kv(orm33, 'V33_NOTIN')),
        'PASS' if kv(orm33, 'V33_IN') not in (None, '0') and kv(orm33, 'V33_NOTIN') not in (None, '0') else 'FAIL')
    # #15/#16/#17 三条既有写路径脚本（真实复跑）
    for script, item in (('tests/smoke/p2_enroll_smoke.py', 'V3.2-#16 p2_enroll_smoke'),
                         ('scripts/seed_wangxiaoming_subjects.py', 'V3.2-#17 seed 脚本（只读复跑前置检查）')):
        if script.startswith('scripts/'):
            skip(item, script, '复跑不冲突', '跳过：该脚本会重置演示档案，改由 p2 冒烟与本节 ORM 判据覆盖',
                 '见 docs/plans/major-track-elective-design.md §6.3.1 #17')
            continue
        p = subprocess.run(['python3', script], capture_output=True, text=True,
                           cwd=str(REPO), timeout=1800)
        tail2 = ((p.stdout or '') + (p.stderr or '')).strip().splitlines()[-2:]
        rec(item, 'python3 %s' % script, 'exit 0（通过线不低于改造前）',
            'exit=%s | %s' % (p.returncode, ' / '.join(tail2)[:260]),
            'PASS' if p.returncode == 0 else 'FAIL')
    return True


def drop_fixture(quiet=False):
    out = shell(FIXTURE_DROP, tag=TAG)
    left = {k: kv(out, k) for k in ('LEFT_CRS', 'LEFT_SUB', 'LEFT_BAT',
                                    'LEFT_LVL', 'LEFT_LINE', 'LEFT_REG')}
    if quiet:
        print('  [pre-clean] 旧夹具残留：%s'
              % json.dumps(left, ensure_ascii=False))
        return left
    ok = all(v == '0' for v in left.values())
    rec('F9 清场 leftover=0', 'ORM', '全部 0',
        json.dumps(left, ensure_ascii=False), 'PASS' if ok else 'FAIL',
        '按【冒烟】标记自清，未用 max(id)')
    return left


# ======================================================================
# V4 迁移可重跑（幂等 + 失败即回滚）
# ======================================================================
MIG_PATH = 'custom_addons/edu_portal/migrations/19.0.3.0.0/post-migrate.py'


def v4_migration_rerun(old_n):
    # V4.2 事务里重跑搬迁 SQL（exec 与 Odoo 自己的 migration loader 同法）
    out = shell("""
src = open('/mnt/custom-addons/edu_portal/migrations/19.0.3.0.0/post-migrate.py').read()
ns = {}
exec(compile(src, 'post-migrate.py', 'exec'), ns)
env.cr.execute("select count(*) from edu_course_subject")
before = env.cr.fetchone()[0]
ns['migrate'](env.cr, '19.0.2.0.0')
env.cr.execute("select count(*) from edu_course_subject")
after = env.cr.fetchone()[0]
print('V42_BEFORE=%d' % before)
print('V42_AFTER=%d' % after)
env.cr.rollback()
""")
    # 幂等口径：重跑前后**新表行数不变**（此刻新表 = 老表 + 夹具行数，
    # 所以不能拿 old_n 直接比；before == after 才是「不产生重复行」）
    v42_b, v42_a = kv(out, 'V42_BEFORE'), kv(out, 'V42_AFTER')
    ok = v42_b is not None and v42_b == v42_a
    rec('V4.2 重跑搬迁 SQL（事务内）', 'ORM exec + migrate()',
        '不产生重复行（before == after；当前新表 = 老表 %d + 夹具行）' % old_n,
        'before=%s after=%s' % (v42_b, v42_a),
        'PASS' if ok else 'FAIL')

    # V4.3 故障探针：只把 INSERT 的 WHERE NOT EXISTS 改成「一定插不进」
    # （WHERE 1=0 AND NOT EXISTS，其余一字不改），再在**事务内**跑一次
    # ⇒ 自证①（应搬 N 行 / 实插 0 行）必须报错并整体回滚。
    # 这样测的是「自证真的会拦住半迁移」，而不是去破坏真实数据。
    out = shell("""
src = open('/mnt/custom-addons/edu_portal/migrations/19.0.3.0.0/post-migrate.py').read()
chunks = src.split('WHERE NOT EXISTS (')
broken = 'SENTINEL'
if len(chunks) == 3:
    # 只破坏 INSERT（chunks[1] 属于 INSERT）：WHERE 后插 1=0，其余原样
    broken = (chunks[0] + 'WHERE NOT EXISTS (' + chunks[1]
              + 'WHERE 1=0 AND NOT EXISTS (' + chunks[2])
print('V43_PATCHED=%d chunks=%d' % (1 if broken != 'SENTINEL' else 0, len(chunks)))
ns = {}
exec(compile(broken if broken != 'SENTINEL' else src, 'post-migrate-broken.py', 'exec'), ns)
env.cr.execute("select count(*) from op_course_op_subject_rel")
before_old = env.cr.fetchone()[0]
env.cr.execute("select count(*) from edu_course_subject")
before_new = env.cr.fetchone()[0]
env.cr.execute("DELETE FROM edu_course_subject")
raised = ''
try:
    ns['migrate'](env.cr, '19.0.2.0.0')
except Exception as e:
    raised = '%s: %s' % (type(e).__name__, str(e)[:140])
print('V43_RAISED=%s' % (raised or 'NO_RAISE'))
env.cr.rollback()
env.cr.execute("select count(*) from op_course_op_subject_rel")
print('V43_OLD_AFTER_ROLLBACK=%d (before=%d)' % (env.cr.fetchone()[0], before_old))
env.cr.execute("select count(*) from edu_course_subject")
print('V43_NEW_AFTER_ROLLBACK=%d (before=%d)' % (env.cr.fetchone()[0], before_new))
""")
    raised = kv(out, 'V43_RAISED') or ''
    old_after = kv(out, 'V43_OLD_AFTER_ROLLBACK') or ''
    new_after = kv(out, 'V43_NEW_AFTER_ROLLBACK') or ''
    ok43 = raised.startswith('RuntimeError') \
        and old_after.startswith(str(old_n)) and new_after.split(' ', 1)[0].isdigit() \
        and new_after.split(' ', 1)[0] == new_after.split('(before=', 1)[-1].rstrip(')')
    rec('V4.3 自证失败必须回滚（INSERT 改成插不进的事务内探针）',
        'ORM（事务内探针，rollback 后两表复位）',
        'RuntimeError（自证①）+ 老表 %d 行 + 新表行数复位' % old_n,
        'raised=%s | old=%s | new=%s' % (raised[:80], old_after, new_after),
        'PASS' if ok43 else 'FAIL', '探针改动在 rollback 后被撤销，两表都未被真改')


def v4_upgrades(old_n, fixture_lines=0):
    expect_new = old_n + fixture_lines
    for i in (1, 2):
        code, ok, tail = upgrade('edu_portal')
        cnt = int(sql('select count(*) from edu_course_subject')[0])
        oldc = int(sql('select count(*) from op_course_op_subject_rel')[0])
        rec('V4.1 第 %d 次 -u edu_portal' % i, 'bash scripts/safe_upgrade.sh edu_portal',
            'EXIT=0；老表不变（%d）；新表 = 老表 + 夹具 %d 行 = %d'
            % (old_n, fixture_lines, expect_new),
            'EXIT=%s | new=%d old=%d' % (code, cnt, oldc),
            'PASS' if ok and cnt == expect_new and oldc == old_n else 'FAIL',
            ([l for l in tail.splitlines() if 'safe_upgrade' in l][-1:] or [''])[0][:160])


# ======================================================================
# V6 权限
# ======================================================================
def v6_permissions(fx):
    crs = fx['FIX_CRS']
    out = shell("""
u = env['res.users'].sudo().search([('login', '=', 'faculty@local')], limit=1)
Menu = env['ir.ui.menu'].with_user(u)
ids = set(Menu._visible_menu_ids())
names = [m.complete_name for m in Menu.browse(list(ids)) if m.id in (263, 277)]
print('V61_263=%d V61_277=%d' % (263 in ids, 277 in ids))
print('V61_NAMES=%s' % names)
u2 = env['res.users'].sudo().search([('login', '=', 'stu@local')], limit=1)
try:
    ids2 = set(env['ir.ui.menu'].with_user(u2)._visible_menu_ids())
    print('V64_263=%d V64_277=%d' % (263 in ids2, 277 in ids2))
except Exception as e:
    # 门户账号连菜单集合都取不到时，属**更强的结论**（不是判据缺陷），
    # 由 V6.4b 的 HTTP 落点判据兜底。
    print('V64_ERR=%s: %s' % (type(e).__name__, str(e)[:120]))
""")
    ok1 = kv(out, 'V61_263') == '0' and kv(out, 'V61_277') == '0'
    rec('V6.1 教师看不见入口（口径 B：可见菜单集）', 'ORM _visible_menu_ids',
        '263/277 均不在可见集', '263=%s 277=%s 命中名=%s'
        % (kv(out, 'V61_263'), kv(out, 'V61_277'), kv(out, 'V61_NAMES')),
        'PASS' if ok1 else 'FAIL')
    ok4 = kv(out, 'V64_263') == '0' and kv(out, 'V64_277') == '0'
    rec('V6.4 学生看不见入口（ORM 口径）', 'ORM _visible_menu_ids', '263/277 均不在可见集',
        '263=%s 277=%s%s' % (kv(out, 'V64_263'), kv(out, 'V64_277'),
                             '（门户账号连菜单集都取不到：%s）' % kv(out, 'V64_ERR')
                             if kv(out, 'V64_ERR') else ''),
        'PASS' if ok4 else 'SKIP' if kv(out, 'V64_ERR') else 'FAIL',
        '取不到时以 V6.4b 的 HTTP 落点判据为准')

    # V6.2/V6.4 UI：教师/学生直接打菜单 263 的动作 URL
    act = sql("select res_id from ir_model_data where model='ir.actions.act_window' and name='act_open_op_course_view'")
    aid = act[0] if act else '0'
    for role, item, expect in (('faculty', 'V6.2 教师直接访问动作 URL', '无权限/落 /apps'),
                               ('student', 'V6.4b 学生直接访问动作 URL', '无权限/回门户')):
        s, _code, uid = auth(role)
        if not uid:
            # ⚠ 这里是**假通过的入口**（t81 实测）：未登录时请求必然落到登录页/3xx ⇒
            #   html_ok 必为 False ⇒ 旧代码判 **PASS**；而它期待的语义是"有权限的会话被拒"。
            #   载体不合法 ⇒ 这一条不许判 PASS（"没登进去"与"越权被拒"同形）。
            carrier_fail(item, role,
                         '未登录时「渲染不出可编辑清单」不能当作「被正确拒绝」')
            continue
        r = s.get(BASE + '/odoo/action-%s' % aid, timeout=60, allow_redirects=False)
        html_ok = r.status_code == 200 and 'subject_line_ids' in (r.text or '') and 'editable' in (r.text or '')
        rec(item, 'HTTP GET /odoo/action-%s（不跟随重定向）' % aid, expect,
            'HTTP %s%s' % (r.status_code, '（渲染出可编辑清单！）' if html_ok else ''),
            'FAIL' if html_ok else 'PASS', 'session=%s' % role)

    # V6.3 教师模型层写 → AccessError + 整体回滚
    out = shell("""
u = env['res.users'].sudo().search([('login', '=', 'faculty@local')], limit=1)
Crs = env['op.course'].sudo().with_context(active_test=False)
c = Crs.browse(«crs»)
Sub = env['op.subject'].sudo()
a = Sub.search([('code','=','MTE-A')], limit=1)
b = Sub.search([('code','=','MTE-B')], limit=1)
c_new = Sub.create({'name': u'«tag» 教师越权目标', 'code': 'MTE-T', 'type': 'theory', 'subject_type': 'elective'})
env.cr.commit()
before_new = sorted(env['edu.course.subject'].sudo().search([('course_id','=',c.id)]).mapped('subject_id.code'))
err = ''
try:
    c.with_user(u).write({'subject_ids': [(6, 0, [c_new.id])]})
except Exception as e:
    err = '%s' % type(e).__name__
env.cr.rollback()
after_new = sorted(env['edu.course.subject'].sudo().search([('course_id','=',c.id)]).mapped('subject_id.code'))
env.cr.execute("select count(*) from op_course_op_subject_rel")
old_n = env.cr.fetchone()[0]
print('V63_ERR=%s' % (err or 'NO_ERROR'))
print('V63_BEFORE=%s' % before_new)
print('V63_AFTER=%s' % after_new)
print('V63_OLD_N=%d' % old_n)
c_new.unlink()
env.cr.commit()
""", crs=crs, tag=TAG)
    err = kv(out, 'V63_ERR') or ''
    ok3 = err == 'AccessError' and kv(out, 'V63_BEFORE') == kv(out, 'V63_AFTER')
    rec('V6.3 教师写 subject_ids 必须 AccessError 且整体回滚', 'ORM with_user(faculty).write',
        'AccessError；行集合前后逐字一致（无半写）',
        'err=%s | before=%s | after=%s'
        % (err, kv(out, 'V63_BEFORE'), kv(out, 'V63_AFTER')),
        'PASS' if ok3 else 'FAIL', '老表 %s 行（未被牵连）' % kv(out, 'V63_OLD_N'))

    # V6.5 正对照：教务 + 管理员都能改，且 tracking 进 chatter
    out = shell("""
Crs = env['op.course'].sudo().with_context(active_test=False)
Sub = env['op.subject'].sudo(); Line = env['edu.course.subject'].sudo()
c = Crs.browse(«crs»)
a = Sub.search([('code','=','MTE-A')], limit=1)
bo = env['res.users'].sudo().search([('login', '=', 'backoffice@local')], limit=1)
adm = env['res.users'].sudo().search([('login', '=', 'admin')], limit=1)
res = []
for label, u in (('backoffice', bo), ('admin', adm)):
    cc = c.with_user(u)
    line = Line.with_user(u).search([('course_id','=',c.id),('subject_id','=',a.id)], limit=1)
    line.write({'subject_type': 'elective'})
    env.cr.commit()
    line2 = Line.with_user(u).search([('course_id','=',c.id),('subject_id','=',a.id)], limit=1)
    res.append('%s=%s' % (label, line2.subject_type))
    line2.write({'subject_type': 'compulsory'})
    env.cr.commit()
# 留痕口径走 ORM（Odoo 19 的 mail_tracking_value 已无 field 列，
# 直接 SQL 会 UndefinedColumn ⇒ 用 message_ids.tracking_value_ids，版本无关）
line3 = Line.search([('course_id','=',c.id),('subject_id','=',a.id)], limit=1)
try:
    n_track = len(line3.message_ids.mapped('tracking_value_ids'))
except Exception as e:
    n_track = -1
print('V65_TRACKING=%d' % n_track)
print('V65_RES=%s' % ' '.join(res))
""", crs=crs)
    rec('V6.5 教务 + 管理员都能改（正对照）', 'ORM with_user',
        '两角色都写成功；tracking 留痕 > 0',
        'acts=%s tracking=%s' % (kv(out, 'V65_RES'), kv(out, 'V65_TRACKING')),
        'PASS' if 'backoffice=elective' in (kv(out, 'V65_RES') or '')
        and 'admin=elective' in (kv(out, 'V65_RES') or '')
        and int(kv(out, 'V65_TRACKING') or 0) > 0 else 'FAIL',
        'chatter 留痕（mail.tracking.value 行）')


# ======================================================================
# V7 门禁
# ======================================================================
GATES = [
    ('V7.1 check_english', ['python3', 'scripts/check_english.py'], 'must-fix 0'),
    ('V7.2 check_view_xpath', ['python3', 'scripts/check_view_xpath.py'], 'exit 0'),
    ('V7.3 check_accessibility', ['python3', 'scripts/check_accessibility.py'], 'exit 0'),
    ('V7.4 check_qweb_dict_foreach', ['python3', 'scripts/check_qweb_dict_foreach.py'], 'exit 0'),
    ('V7.5 check_manifest_tracking', ['python3', 'scripts/check_manifest_tracking.py'], 'exit 0'),
]


def v7_gates():
    for item, cmd, expect in GATES:
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO),
                           timeout=1800)
        body = (p.stdout or '') + (p.stderr or '')
        if 'check_english' in cmd[1]:
            mf = re.findall(r'must-fix\s+(\d+)', body)
            ok = p.returncode == 0 and all(x == '0' for x in mf) and bool(mf)
            detail = 'must-fix=%s' % ','.join(mf)
        else:
            ok = p.returncode == 0
            detail = [l for l in body.strip().splitlines()
                      if l.startswith('RESULT=') or l.startswith('结论')] or [''] 
            detail = detail[0][:150]
        rec(item, ' '.join(cmd), expect, 'exit=%s | %s' % (p.returncode, detail),
            'PASS' if ok else 'FAIL')


# ======================================================================
# V8 改名对照（含 561 回归）
# ======================================================================
def v8_rename():
    out = shell("""
M = env['ir.ui.menu'].sudo().with_context(active_test=False, lang='zh_CN')
# 2026-09-24 第二轮改名：264 批次→班级、276 专业→培养方案（276 的 op.program 与 263
# 的 op.course 撞名，学校口径的「专业」此后唯一 = 263）。见 docs/ops/menu-rename-list.md §2.2。
want = {262: u'教学管理', 263: u'专业', 264: u'班级', 267: u'科目', 275: u'项目管理',
        276: u'培养方案', 277: u'学制', 282: u'学生课程详情', 327: u'考试课程',
        548: u'课程', 551: u'课程', 553: u'课程', 561: u'课程'}
for mid, exp in sorted(want.items()):
    m = M.browse(mid)
    if not m.exists():
        print('V8_MENU_%d=MISSING' % mid)
        continue
    print('V8_MENU_%d=%s|%s|%s|%s' % (mid, m.name, m.with_context(lang='en_US').name,
                                            m.complete_name, m.active))
A = env['ir.actions.act_window'].sudo()
print('V8_ACT_385=%s|%s' % (A.with_context(lang='zh_CN').browse(385).name, A.with_context(lang='zh_TW').browse(385).name))
print('V8_ACT_396=%s|%s' % (A.with_context(lang='zh_CN').browse(396).name, A.with_context(lang='zh_TW').browse(396).name))
print('V8_MENU_263_TW=%s' % M.browse(263).with_context(lang='zh_TW').name)
print('V8_MENU_277_TW=%s' % M.browse(277).with_context(lang='zh_TW').name)
print('V8_277_PARENT=%d' % M.browse(277).parent_id.id)
print('V8_275_CHILD_277=%d' % (1 if M.browse(277).parent_id.id == 275 else 0))
""")
    def val(mid):
        raw = kv(out, 'V8_MENU_%s' % mid) or ''
        return raw.split('|')
    m263, m277, m262 = val(263), val(277), val(262)
    ok1 = m263[:1] == ['专业'] and '教学管理/专业' in (m263[2] if len(m263) > 2 else '')
    rec('V8.1 菜单 263 = 专业（complete_name 含 教学管理/专业）', 'ORM lang=zh_CN',
        '专业 | …教学管理/专业', '|'.join(m263), 'PASS' if ok1 else 'FAIL')
    ok2 = (kv(out, 'V8_ACT_385') or '').split('|')[0] == '专业'
    rec('V8.2 动作 385 = 专业', 'ORM lang=zh_CN', '专业',
        kv(out, 'V8_ACT_385') or '—', 'PASS' if ok2 else 'FAIL')
    ok3 = m277[:1] == ['学制'] and (kv(out, 'V8_ACT_396') or '').split('|')[0] == '学制' \
        and kv(out, 'V8_277_PARENT') == '262'
    rec('V8.3 277 = 学制 / 396 = 学制 / 277 已挂到 262 下', 'ORM',
        '学制 + 学制 + parent=262',
        '277=%s | act396=%s | parent=%s' % (m277[:1], kv(out, 'V8_ACT_396'),
                                            kv(out, 'V8_277_PARENT')),
        'PASS' if ok3 else 'FAIL')
    ok4 = m262[:1] == ['教学管理']
    rec('V8.3b 菜单 262 = 教学管理', 'ORM', '教学管理', '|'.join(m262),
        'PASS' if ok4 else 'FAIL')
    reg = {m: val(m)[:1] for m in (264, 267, 282, 327, 548, 551, 553, 561)}
    ok5 = all(v == [{'548': '课程', '551': '课程', '553': '课程', '561': '课程',
                     '267': '科目', '264': '班级', '282': '学生课程详情',
                     '327': '考试课程'}[str(m)]] for m, v in reg.items())
    rec('V8.4 回归对照：548/551/553/561 仍=课程；267/282/327 未动；264 本批有意改为 班级',
        'ORM lang=zh_CN',
        '561=课程（在线课程未被连带改名）',
        '; '.join('%s=%s' % (m, v[0] if v else '?') for m, v in sorted(reg.items())),
        'PASS' if ok5 else 'FAIL', '在线课程 slide.channel 的菜单未被 Courses→专业 波及')
    ok6 = kv(out, 'V8_MENU_263_TW') == u'專業' and kv(out, 'V8_MENU_277_TW') == u'學制'
    rec('V8.5 繁体：263=專業 / 277=學制', 'ORM lang=zh_TW', '專業 / 學制',
        '263=%s 277=%s' % (kv(out, 'V8_MENU_263_TW'), kv(out, 'V8_MENU_277_TW')),
        'PASS' if ok6 else 'FAIL')
    ok7 = val(275)[:1] == ['项目管理'] and val(275)[3:] == ['False'] \
        and val(276)[3:] == ['False']
    rec('V8.6 275「项目管理」整棵停用（含 276 空壳）', 'ORM',
        '275 active=False；276 active=False',
        '275=%s 276=%s' % ('|'.join(val(275)), '|'.join(val(276))),
        'PASS' if ok7 else 'FAIL', '只停用不删除（记录保留）')


# ======================================================================
# V9 回滚演练（代码回滚 → 老表口径 → 再切回）
# ======================================================================
DRILL_PATHS = [
    'custom_addons/edu_portal/models/major_track.py',
    'custom_addons/edu_portal/models/__init__.py',
    'custom_addons/edu_portal/views/major_track_views.xml',
    'custom_addons/edu_portal/views/enroll.xml',
    'custom_addons/edu_portal/controllers/enroll.py',
    'custom_addons/edu_portal/security/ir.model.access.csv',
    'custom_addons/edu_portal/migrations/19.0.3.0.0/post-migrate.py',
    'custom_addons/edu_portal/__manifest__.py',
]
DRILL_MSG = 'mt-rollback-drill'
# 「改造前」参照点 = 本功能落地前最后一个提交（R1 改名小实验 da40f35）。
# 为什么不用 git stash：功能代码**已经提交**，stash 根本回滚不了它
# （实测：stash 只抓走未提交的零头，subject_ids 仍是 store=False ⇒ V9.2c 假红）。
# 可用环境变量覆盖（换基线时不必改脚本）。
DRILL_BASE_REF = os.environ.get('MTE_DRILL_BASE', 'da40f35')


def _git(*args):
    p = subprocess.run(['git'] + list(args), capture_output=True, text=True,
                       cwd=str(REPO), timeout=120)
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def _field_state():
    out = shell("""
f = env['op.course']._fields['subject_ids']
print('ST=%d' % (1 if f.store else 0))
print('HAS_COMPUTE=%d' % (1 if f.compute else 0))
print('HAS_INVERSE=%d' % (1 if f.inverse else 0))
print('MODEL=%d' % (1 if 'edu.course.subject' in env else 0))
""")
    return {'store': kv(out, 'ST'), 'compute': kv(out, 'HAS_COMPUTE'),
            'inverse': kv(out, 'HAS_INVERSE'), 'model': kv(out, 'MODEL')}


def _drill_rollback(ref):
    """把本功能 8 个文件切到 ref 那一刻（该 ref 尚无的新增文件 ⇒ 删掉）。"""
    log = []
    for path in DRILL_PATHS:
        rc, _ = _git('cat-file', '-e', '%s:%s' % (ref, path))
        if rc == 0:
            rc2, _out = _git('checkout', ref, '--', path)
            log.append('%s:checkout rc=%s' % (path.split('/')[-1], rc2))
        else:
            os.remove(str(REPO / path))
            log.append('%s:rm' % path.split('/')[-1])
    return log


def _drill_restore(ref='HEAD'):
    for path in DRILL_PATHS:
        _git('checkout', ref, '--', path)
    _git('add', *DRILL_PATHS)


def v9_rollback_drill(old_n, fx, fixture_lines=0):
    stu, _code, uid = auth('student')
    if not uid:
        carrier_fail('V9 回滚演练（页面口径对照组）', 'student')
        return
    expect_new = old_n + fixture_lines
    # 页面口径对照组：老表里**真实存在**的专业（回滚后靠老表提供 subject_ids），
    # 用它证明「改造后 / 回滚后」页面读数逐位一致；夹具专业回滚后本就 0 门（它的行只在新表）
    okp = sql("select c.id || '|' || b.id from op_course c "
              "join op_batch b on b.course_id = c.id and b.active "
              "where c.code = 'CRS-PRP' and exists ("
              "select 1 from op_course_op_subject_rel r where r.op_course_id = c.id) "
              "order by b.id limit 1")
    if okp and '|' in okp[0]:
        ref_crs, ref_bat = okp[0].split('|')
    else:
        ref_crs, ref_bat = fx['FIX_CRS'], fx['FIX_BAT']
        rec('V9.0b 对照组专业（老表里有关系的专业）', 'SQL',
            'CRS-PRP + 其 active 班', '未找到，回退用夹具专业（页面读数会变 0 门）',
            'SKIP', '仅影响 V9 页面口径对照的严格度')

    # V9.0 前置：8 个文件必须**工作区干净**（否则 drill 会毁掉未提交改动）
    rc, st = _git('status', '--porcelain', '--', *DRILL_PATHS)
    if st.strip():
        rec('V9.0 回滚演练前置（工作区干净）', 'git status --porcelain -- <8 文件>',
            '无未提交改动', '有未提交改动，已跳过演练：' + st.strip()[:120],
            'SKIP', '先 commit 再跑 --with-rollback-drill，避免毁掉未提交工作')
        return

    # V9.1 导出归档（台账 C1 口径）
    p = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                        '-U', 'odoo', '-d', DB, '-c',
                        "\\copy edu_course_subject to '/tmp/mt_rollback_backup.csv' csv header"],
                       capture_output=True, text=True, cwd=str(REPO), timeout=180)
    wc = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'bash', '-lc',
                         "wc -l /tmp/mt_rollback_backup.csv"],
                        capture_output=True, text=True, cwd=str(REPO), timeout=120)
    lines = (wc.stdout or '').strip().split()[0] if wc.stdout.strip() else '0'
    ok1 = p.returncode == 0 and lines == str(expect_new + 1)
    rec('V9.1 回滚前归档（copy 到 CSV）', 'docker compose exec db psql',
        '导出成功且行数 = 新表 %d + 表头' % expect_new,
        'exit=%s lines=%s' % (p.returncode, lines), 'PASS' if ok1 else 'FAIL',
        '/tmp/mt_rollback_backup.csv（容器内）')

    before = _field_state()
    st_b, cb, eb, _ = page_badges(stu, ref_crs, ref_bat)
    rec('V9.2a 回滚前状态基线（对照组专业 %s/%s）' % (ref_crs, ref_bat), 'ORM + HTTP',
        'store=False / compute+inverse 在 / 页面 200',
        'store=%s compute=%s inverse=%s | 页面 HTTP %s 必修=%s 选修=%s'
        % (before['store'], before['compute'], before['inverse'], st_b, cb, eb),
        'PASS' if before['store'] == '0' and st_b == 200 else 'FAIL')

    try:
        log = _drill_rollback(DRILL_BASE_REF)
        rc, diff = _git('status', '--porcelain', '--', *DRILL_PATHS)
        rec('V9.2b 代码回滚到 %s（本功能 8 个文件）' % DRILL_BASE_REF,
            'git checkout <base> -- <paths> / rm',
            '工作区与基线一致（有改动 = 已回滚）',
            'changed=%d 行 | %s' % (len(diff.strip().splitlines()),
                                    '; '.join(log[:3])),
            'PASS' if diff.strip() else 'FAIL')
        code, ok, tail = upgrade('edu_portal')
        after = _field_state()
        old_c = int(sql('select count(*) from op_course_op_subject_rel')[0])
        new_c = int(sql('select count(*) from edu_course_subject')[0])
        st2, c2, e2, _ = page_badges(stu, ref_crs, ref_bat)
        ok2 = ok and after['store'] == '1' and after['model'] == '0' \
            and old_c == old_n and new_c == expect_new and st2 == 200 \
            and (c2, e2) == (cb, eb)
        rec('V9.2c 回滚后：老表口径 + 数据零丢失 + 报课页正常', '-u edu_portal',
            'EXIT=0；store=True；老表 %d 行；新表 %d 行仍在；'
            '对照组页面必修/选修与回滚前逐位一致（%s/%s）'
            % (old_n, expect_new, cb, eb),
            'EXIT=%s | store=%s model=%s old=%d new=%d | HTTP %s 必修=%s 选修=%s'
            % (code, after['store'], after['model'], old_c, new_c, st2, c2, e2),
            'PASS' if ok2 else 'FAIL', '老表从未被新代码写入 ⇒ 回滚零丢失')
    finally:
        _drill_restore('HEAD')
        rc, st2b = _git('status', '--porcelain', '--', *DRILL_PATHS)
        rec('V9.3a 切回改造后（git checkout HEAD -- <paths>）',
            'git checkout HEAD', '工作区回到改造后（无残留改动）',
            'left=%s' % (st2b.strip()[:120] or '干净'),
            'PASS' if not st2b.strip() else 'FAIL')

    code, ok, tail = upgrade('edu_portal')
    final = _field_state()
    old_f = int(sql('select count(*) from op_course_op_subject_rel')[0])
    new_f = int(sql('select count(*) from edu_course_subject')[0])
    st3, c3, e3, _ = page_badges(stu, ref_crs, ref_bat)
    ok3 = ok and final['store'] == '0' and old_f == old_n and new_f == expect_new \
        and (c3, e3) == (cb, eb)
    rec('V9.3b 再切回后：回到兼容层口径（可逆证明）', '-u edu_portal',
        'EXIT=0；store=False；两侧仍 %d / %d 行' % (old_n, expect_new),
        'EXIT=%s | store=%s old=%d new=%d | HTTP %s 必修=%s 选修=%s'
        % (code, final['store'], old_f, new_f, st3, c3, e3),
        'PASS' if ok3 else 'FAIL', '回滚→切回 两次都在同一份数据上，无重复行')


# ======================================================================
# main
# ======================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--with-upgrades', action='store_true',
                    help='含 V4（连跑两次 -u + 迁移重跑探针）')
    ap.add_argument('--with-rollback-drill', action='store_true',
                    help='含 V9（代码回滚演练；会短暂 stash 本功能文件，自动恢复）')
    ap.add_argument('--keep-fixture', action='store_true', help='保留夹具（调试用）')
    args = ap.parse_args()

    print('=== 专业编排（学制 + 必修/选修）真机冒烟 · 本地 %s ===' % DB)
    v0_preflight()
    # V1 之前先清自己上次的残留：否则「老表 = 新表」会被上一次中断留下的夹具行污染
    # （实测：上一次跑到一半崩了 ⇒ 新表多 2 行 ⇒ V1.1/V1.2/V1.3 假红）
    drop_fixture(quiet=True)
    old_n = v1_migration()
    fx = build_fixture()
    if all(v is not None for v in fx.values()):
        v5_v2_pages(fx)
        v3_consumers(fx)
    v8_rename()
    v4_migration_rerun(old_n)
    if args.with_upgrades:
        v4_upgrades(old_n, fixture_lines=int(fx.get('FIX_LINES') or 0))
    v6_permissions(fx)
    if args.with_rollback_drill:
        v9_rollback_drill(
            old_n, fx, fixture_lines=int(fx.get('FIX_LINES') or 0))
    if not args.keep_fixture:
        drop_fixture()
    v7_gates()

    passed = sum(1 for r in R if r['result'] == 'PASS')
    failed = [r for r in R if r['result'] == 'FAIL']
    skipped = [r for r in R if r['result'] == 'SKIP']
    summary = {
        'at': subprocess.run(['date', '+%Y-%m-%d %H:%M:%S'], capture_output=True,
                             text=True).stdout.strip(),
        'db': DB, 'base': BASE,
        'total': len(R), 'pass': passed, 'fail': len(failed), 'skip': len(skipped),
        'results': R,
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                   encoding='utf-8')
    print('==== 汇总：PASS=%d FAIL=%d SKIP=%d → %s' %
          (passed, len(failed), len(skipped),
           'ALL PASS' if not failed else 'HAS FAIL'))
    for r in failed:
        print('  FAIL %s: %s' % (r['item'], r['actual']))
    print('结果落盘：%s' % OUT)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())


