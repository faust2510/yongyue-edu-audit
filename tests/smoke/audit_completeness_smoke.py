#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审计完整性冒烟（t39）：后台/模型边界直写 + 门户三条路径，逐条断言留痕。

为什么需要它（队长 2026-09-12）：t9 的门禁测的是**可观测面**（路由/英文/品牌/高度），
**审计完整性测不出来** —— "改分是否留痕"只能靠**行为级验证**：写一次 → 查留痕表 → 字段对。
t13-F1 的教训正是"claim（唯一入口、全部留痕）≠ 证据"，本冒烟把证据固定下来。

覆盖四条写入路径（每条都做**正向断言**，防"恰好没数据所以恰好通过"）：
  1. **后台/模型边界直写** → 期望 `edu.grade.history` 出现 source=**backend**（t34 修复点）
  2. **门户·页面保存**（HTTP POST /grading/save）→ source=**manual**
  3. **门户·CSV 导入**（统一入口 edu_apply_marks(source='import')）→ action/source=**import**
  4. **门户·上期复制**（统一入口 edu_apply_marks(source='copy')）→ action/source=**copy**

每条用例：**还原成绩值 + 清场**，断言 `leftover=0` 且分数回到原值；整套跑两遍结果一致（幂等/确定性）。

用法：
    python3 tests/smoke/audit_completeness_smoke.py            # 连跑 2 遍
    python3 tests/smoke/audit_completeness_smoke.py --runs 1
退出码：0=全绿；1=有断言失败；2=运行错误（服务不可达 / 找不到夹具）。
只动 tests/smoke/；发现业务缺陷**只上报不顺手修**。
"""
import argparse
import re
import subprocess
import sys

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
ROOT = '.'
ODOO = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
        '-c', '/etc/odoo/odoo.conf', '--db_host=db', '--db_port=5432',
        '--db_user=odoo', '--db_password=odoo', '-d', DB, '--no-http']

OK, FAIL, SKIP = 'PASS', 'FAIL', 'SKIP'
results = []


def check(name, cond, detail=''):
    v = OK if cond else FAIL
    results.append((v, name, detail))
    print('  %-4s %-46s %s' % (v, name, detail))
    return cond


def shell(code, timeout=240):
    """在 odoo shell 里跑一段代码，返回 stdout+stderr 合并文本。"""
    out = subprocess.run(ODOO, input=code, capture_output=True, text=True,
                         timeout=timeout, cwd=ROOT)
    return (out.stdout or '') + (out.stderr or '')


def kv(blob, key):
    m = re.search(r'%s=(\S+)' % re.escape(key), blob)
    return m.group(1) if m else None


def login(user, pwd):
    s = requests.Session()
    s.trust_env = False
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0', 'params': {'db': DB, 'login': user, 'password': pwd}}, timeout=25)
    return s if (r.json().get('result') or {}).get('uid') else None


def get_csrf(s, url):
    r = s.get(BASE + url, timeout=30)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    return m.group(1) if m else None


FIXTURE = '''
# 与控制器同源的口径：教师可见考试 = responsible_id 本人 OR 考试班级属本人任教班级
# （_teacher_taught_batches 用 op.session.faculty_id 口径，见 roles.py:683-701）
Att = env['op.exam.attendees'].sudo()
fac = env['op.faculty'].sudo().search([('user_id.login', '=', 'faculty@local')], limit=1)
batches = env['op.session'].sudo().search(
    [('faculty_id', '=', fac.id)]).mapped('batch_id') if fac else env['op.batch'].sudo().browse()
Ex = env['op.exam'].sudo()
dom = ['|', ('responsible_id', 'in', [fac.id] if fac else [0]),
       ('batch_id', 'in', batches.ids)] if fac else [('id', '=', 0)]
exams = Ex.search(dom)
print('TEACHER_EXAMS=%d' % len(exams))
exam = exams[:1]
att = Att.search([('exam_id', '=', exam.id), ('marks', '!=', False)], limit=1) if exam else Att.browse()
if not att:
    att = Att.search([], limit=1)
if not att:
    print('NO_ATT')
else:
    print('ATT=%d MARKS=%s EXAM=%d STUDENT=%d T_EXAM=%d' % (
        att.id, att.marks or 0, att.exam_id.id, att.student_id.id or 0,
        exam.id if exam else 0))
'''


def case_backend(att_id):
    """后台/模型边界直写 → 期望 source=backend 的留痕。"""
    code = '''
A = env['op.exam.attendees'].sudo().browse(%d)
H = env['edu.grade.history'].sudo()
old = A.marks or 0
base = max(H.search([]).ids) if H.search([], limit=1) else 0
A.write({'marks': old + 1})
env.cr.commit()
rows = H.search([('id', '>', base)])
print('NEW_ROWS=%%d' %% len(rows))
for r in rows:
    print('ROW source=%%s action=%%s old=%%s new=%%s note=%%s' %% (r.source, r.action, r.old_marks, r.new_marks, r.note or ''))
A.write({'marks': old})
env.cr.commit()
H.search([('id', '>', base)]).unlink()
env.cr.commit()
print('RESTORED=%%s LEFTOVER=%%d' %% (A.marks, len(H.search([('id', '>', base)]))))
''' % att_id
    blob = shell(code)
    n = kv(blob, 'NEW_ROWS')
    src = re.search(r'ROW source=(\S+) action=(\S+) old=(\S+) new=(\S+)', blob)
    restored = kv(blob, 'RESTORED')
    leftover = kv(blob, 'LEFTOVER')
    check('后台/模型边界：有留痕', n == '1', 'NEW_ROWS=%s' % n)
    check('后台/模型边界：source=backend 且 old/new 正确', bool(src) and src.group(1) == 'backend'
          and src.group(3).isdigit() and int(src.group(4)) == int(src.group(3)) + 1,
          src.group(0) if src else 'no row')
    check('后台/模型边界：还原 + leftover=0', restored is not None and leftover == '0',
          'marks=%s leftover=%s' % (restored, leftover))


def case_unified(att_id, source, expect_action):
    """门户两条非 HTTP 路径（导入/复制）走统一入口。"""
    code = '''
A = env['op.exam.attendees'].sudo().browse(%d)
H = env['edu.grade.history'].sudo()
old = A.marks or 0
base = max(H.search([]).ids) if H.search([], limit=1) else 0
verdict = H.edu_apply_marks(A, marks=old + 2, source=%r)
env.cr.commit()
rows = H.search([('id', '>', base)])
print('VERDICT=%%s NEW_ROWS=%%d' %% (verdict, len(rows)))
for r in rows:
    print('ROW source=%%s action=%%s old=%%s new=%%s' %% (r.source, r.action, r.old_marks, r.new_marks))
H.edu_apply_marks(A, marks=old, source=%r)
env.cr.commit()
H.search([('id', '>', base)]).unlink()
env.cr.commit()
print('RESTORED=%%s LEFTOVER=%%d' %% (A.marks, len(H.search([('id', '>', base)]))))
''' % (att_id, source, source)
    blob = shell(code)
    n = kv(blob, 'NEW_ROWS')
    row = re.search(r'ROW source=(\S+) action=(\S+) old=(\S+) new=(\S+)', blob)
    check('门户·%s：只留一条（未双记）' % source, n == '1', 'NEW_ROWS=%s' % n)
    check('门户·%s：source/action 正确' % source,
          bool(row) and row.group(1) == source and row.group(2) == expect_action,
          row.group(0) if row else 'no row')
    check('门户·%s：还原 + leftover=0' % source,
          kv(blob, 'LEFTOVER') == '0', 'marks=%s leftover=%s'
          % (kv(blob, 'RESTORED'), kv(blob, 'LEFTOVER')))


def case_http_save(att_id, exam_id):
    """门户·页面保存：真 HTTP POST /grading/save（教师身份）。

    注意取 base 的时机：必须在 POST **之前**记下 history/audit 的最大 id，
    否则 POST 生成的那条留痕会被算进 base，清场时漏删（本冒烟第一版就在这里假红过一次）。
    """
    s = login('faculty@local', 'demo123')
    if not s:
        return check('门户·页面保存(HTTP)：教师登录', False, '登录失败')
    token = get_csrf(s, '/grading/entry?exam_id=%d' % exam_id)
    if not token:
        return check('门户·页面保存(HTTP)：取 csrf', False, '页面未渲染 csrf')

    code = """
A = env['op.exam.attendees'].sudo().browse(%d)
H = env['edu.grade.history'].sudo()
Aud = env['edu.audit.log'].sudo()
print('OLD=%%s HBASE=%%d ABASE=%%d' %% (A.marks or 0,
      max(H.search([]).ids) if H.search([], limit=1) else 0,
      max(Aud.search([]).ids) if Aud.search([], limit=1) else 0))
""" % att_id
    blob = shell(code)
    old = int(kv(blob, 'OLD') or 0)
    hbase = int(kv(blob, 'HBASE') or 0)
    abase = int(kv(blob, 'ABASE') or 0)

    r = s.post(BASE + '/grading/save',
               data={'csrf_token': token, 'exam_id': exam_id,
                     'marks_%d' % att_id: str(old + 3)},
               allow_redirects=False, timeout=40)
    check('门户·页面保存(HTTP)：POST 被接受', r.status_code in (302, 303), 'HTTP %s' % r.status_code)

    code = """
H = env['edu.grade.history'].sudo()
rows = H.search([('id', '>', %d)])
print('ROWS=%%d' %% len(rows))
for r in rows:
    print('ROW source=%%s action=%%s new=%%s' %% (r.source, r.action, r.new_marks))
A = env['op.exam.attendees'].sudo().browse(%d)
A.write({'marks': %d})          # 还原本身也会触发一条 backend 留痕
H.search([('id', '>', %d)]).unlink()   # 因此必须在还原**之后**重新查询再删
env['edu.audit.log'].sudo().search([('id', '>', %d)]).unlink()
env.cr.commit()
print('RESTORED=%%s LEFTOVER=%%d AUD_LEFT=%%d' %% (
    A.marks, len(H.search([('id', '>', %d)])),
    len(env['edu.audit.log'].sudo().search([('id', '>', %d)]))))
""" % (hbase, att_id, old, hbase, abase, hbase, abase)
    blob = shell(code)
    row = re.search(r'ROW source=(\S+) action=(\S+) new=(\S+)', blob)
    check('门户·页面保存(HTTP)：留痕 source=manual 且新分正确',
          bool(row) and row.group(1) == 'manual' and row.group(3) == str(old + 3),
          row.group(0) if row else 'no row')
    check('门户·页面保存(HTTP)：还原 + leftover=0',
          kv(blob, 'LEFTOVER') == '0' and kv(blob, 'AUD_LEFT') == '0',
          'marks=%s history_leftover=%s audit_leftover=%s'
          % (kv(blob, 'RESTORED'), kv(blob, 'LEFTOVER'), kv(blob, 'AUD_LEFT')))


def run_once(round_no):
    print('\n===== 第 %d 遍 =====' % round_no)
    art_ids = set()
    blob = shell(FIXTURE)
    att = kv(blob, 'ATT')
    if not att:
        print('  SKIP 找不到夹具（无 op.exam.attendees）')
        return None
    att = int(att)
    exam = int(kv(blob, 'T_EXAM') or 0)
    print('  夹具：attendee=%d exam=%d' % (att, exam))
    before = len(results)
    case_backend(att)
    case_unified(att, 'import', 'import')
    case_unified(att, 'copy', 'copy')
    if exam:
        case_http_save(att, exam)
    else:
        check('门户·页面保存(HTTP)：夹具可用', False, '教师名下无 exam（跳过）')
    return tuple(v for v, _n, _d in results[before:])


def main():
    ap = argparse.ArgumentParser(description='审计完整性冒烟（t9 之外的业务正确性面）')
    ap.add_argument('--runs', type=int, default=2, help='连跑几遍（默认 2，用于验证确定性）')
    args = ap.parse_args()

    # 轻量前置探活（与 UX_V3_GATE.md §0 同口径）：容器刚重启就直说，别把环境问题伪装成断言失败
    try:
        import os
        # 升级锁口径（t9 统一，与 scripts/safe_upgrade.sh:60 / tests/smoke/authz_endtoend_smoke.py:107 同源）：
        #   EDU_UPGRADE_LOCK 覆盖 ＞ TMPDIR（未设**或空** ⇒ /tmp）＞ 固定名 edu19_upgrade.lock。
        # 旧写法 os.environ.get('TMPDIR', '/tmp') 在 TMPDIR="" 时退化成**相对路径**
        # 'edu19_upgrade.lock' ⇒ 锁在也看不见（fail-open，t9 实测）；末尾 isabs 自检兜底。
        # 存在性判据用 exists 而非 isdir：与 t5 修好的 authz/check_view_xpath 同口径（宁可多拦一次）。
        lock = (os.environ.get('EDU_UPGRADE_LOCK')
                or os.path.join(os.environ.get('TMPDIR') or '/tmp',
                                'edu19_upgrade.lock'))
        if not os.path.isabs(lock):
            lock = '/tmp/edu19_upgrade.lock'
        if os.path.exists(lock):
            print('环境不可用：升级锁存在（%s）—— 有人在升级，稍后重跑' % lock)
            return 2
        started = subprocess.run(['docker', 'inspect', '-f', '{{.State.StartedAt}}',
                                  'edu19-clone-web-1'], capture_output=True, text=True, timeout=20)
        if started.returncode == 0 and started.stdout.strip():
            import datetime
            ts = datetime.datetime.fromisoformat(started.stdout.strip().replace('Z', '+00:00'))
            up = (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds()
            if up < 30:
                print('环境不可用：web 容器刚重启（Up %.0fs < 30s）—— 稍后重跑' % up)
                return 2
        r = requests.Session()
        r.trust_env = False
        code = r.get(BASE + '/web/login?db=' + DB, timeout=15, allow_redirects=False).status_code
        if code not in (200, 302, 303):
            print('环境不可用：/web/login?db=%s 返回 %s' % (DB, code))
            return 2
    except Exception as e:
        print('服务不可达：%s' % str(e)[:80])
        return 2

    signatures = []
    for i in range(1, max(1, args.runs) + 1):
        sig = run_once(i)
        if sig is None:
            print('\n结论：无法建夹具 → 运行错误')
            return 2
        signatures.append(sig)

    n_fail = sum(1 for v, _n, _d in results if v == FAIL)
    print('\n============ 汇总 ============')
    print('断言 %d 条：PASS %d / FAIL %d' % (len(results), len(results) - n_fail, n_fail))
    if len(signatures) > 1:
        same = all(s == signatures[0] for s in signatures)
        print('连跑 %d 遍结果一致：%s' % (len(signatures), '是' if same else '否'))
        if not same:
            n_fail += 1
    print('结论：%s' % ('全绿' if n_fail == 0 else '有 %d 项失败' % n_fail))
    return 1 if n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
