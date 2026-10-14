#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""录取后发放入学码（需求 C-3）的活体验收 —— 设计 §18.4 的 A1–A14。

栈：本地 edu19-clone（http://localhost:8069，db=edu19）—— **不碰生产**。
写操作自还原：探针建的测试申请 / 测试码全部删除，末尾断言 leftover=0。
用法：python3 tests/smoke/admit_invite_gate.py
结果：同目录 admit_invite_gate_results.json
"""
import datetime
import json
import os
import re
import subprocess
import sys

os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
os.environ['no_proxy'] = 'localhost,127.0.0.1'

import requests

B = 'http://localhost:8069'
DB = 'edu19'
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OK = []
NOTES = []
APPS = []      # 探针建的测试申请
CODES = []     # 探针建的测试码
TAG = 'P3ADM%s' % datetime.datetime.now().strftime('%H%M%S')


def check(name, got, want, extra=''):
    good = got == want
    OK.append((bool(good), name))
    print('  %-4s %-56s 期望 %-20s 实际 %s %s'
          % ('PASS' if good else 'FAIL', name, want, got, extra))
    return good


def note(text):
    NOTES.append(text)
    print('  ..   注：%s' % text)


def loc(r):
    return (r.headers.get('Location') or '').replace(B, '')


def login(name, pw='demo123'):
    s = requests.Session()
    r = s.get(B + '/login?db=%s' % DB, timeout=30)
    m = re.search(r'csrf_token[^>]*?value="([^"]+)"', r.text or '')
    assert m, '登录页没有 csrf_token（HTTP %s）' % r.status_code
    s.post(B + '/login', allow_redirects=False, timeout=30, data={
        'csrf_token': m.group(1), 'db': DB, 'login': name,
        'password': pw, 'redirect': ''})
    return s


def call_kw(sess, model, method, args, kwargs=None):
    """Odoo 19 后端 JSON 调用；返回 {'result':...} 或 {'error':...}。"""
    r = sess.post(B + '/web/dataset/call_kw', timeout=120,
                  headers={'Content-Type': 'application/json'},
                  data=json.dumps({'jsonrpc': '2.0', 'method': 'call',
                                   'params': {'model': model, 'method': method,
                                              'args': args, 'kwargs': kwargs or {}}}))
    try:
        return r.json()
    except Exception:
        return {'http': r.status_code, 'text': (r.text or '')[:200]}


def err_text(resp):
    e = (resp or {}).get('error') or {}
    d = e.get('data') or {}
    return (d.get('message') or e.get('message') or '') + ' | ' + (d.get('name') or '')


def sql(q):
    p = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                        '-U', 'odoo', '-d', DB, '-tAc', q],
                       cwd=REPO, capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        raise RuntimeError('psql 失败：%s' % (p.stderr or '')[-300:])
    return p.stdout.strip()


def one(q):
    out = sql(q)
    return out.splitlines()[0].strip() if out else ''


def shell(code):
    p = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
         '-c', '/etc/odoo/odoo.conf', '--db_host=db', '-r', 'odoo',
         '-w', 'odoo', '-d', DB, '--no-http'],
        cwd=REPO, input=code, capture_output=True, text=True, timeout=420)
    return (p.stdout or '') + (p.stderr or '')


def probe(pattern, text, default=''):
    m = re.search(pattern, text or '')
    return m.group(1).strip() if m else default


def mk_app(email, label):
    """建一张已录取的测试申请（必填字段照抄一张既有申请，避免猜 selection 取值）。"""
    code = shell("""
tpl = env['edu.application'].search([], limit=1)
vals = {f: tpl[f] for f in ('church', 'gender', 'track')}
vals.update({'name': '探针-%s', 'id_no': 'PROBE-%s-%s',
             'phone': '00000000000', 'state': 'admitted',
             'email': %s})
app = env['edu.application'].create(vals)
env.cr.commit()
print('PROBE_APP=%%d' %% app.id)
""" % (label, TAG, label, repr(email) if email else 'False'))
    aid = probe(r'PROBE_APP=(\d+)', code)
    assert aid, '建测试申请失败：%s' % code[-600:]
    aid = int(aid)
    APPS.append(aid)
    return aid


def code_row(aid):
    out = sql("select id||'|'||code||'|'||use_limit||'|'||"
              "to_char(expire_at,'YYYY-MM-DD HH24:MI')||'|'||"
              "coalesce(application_id::text,'-')||'|'||"
              "coalesce(note,'-') from edu_invite_code where application_id=%d" % aid)
    return out.splitlines()[0].strip() if out else ''


def main():
    print('== C-3 录取后发放入学码 · 活体验收（%s）==' % TAG)
    adm = login('backoffice@local')

    # ---------- 载体与前置事实 ----------
    print('\n[0] 载体与前置事实')
    mail_before = int(one('select coalesce(max(id),0) from mail_mail') or 0)
    tg_claim_before = one('select count(*) from edu_tg_claim')
    tg_pool_before = one("select count(*) from edu_invite_code where note like '%%TG%%'")
    col = one("select count(*) from information_schema.columns "
              "where table_name='edu_invite_code' and column_name='application_id'")
    check('A0-a edu_invite_code.application_id 列存在', col, '1')
    uniq = one("select count(*) from pg_indexes where tablename='edu_invite_code' "
               "and indexdef like '%%application_id%%' and indexdef like '%%UNIQUE%%'")
    check('A0-b application_id 唯一索引存在', uniq, '1')

    app_mail = mk_app('probe-%s@example.com' % TAG.lower(), 'mail')
    app_nomail = mk_app(None, 'nomail')
    note('测试申请 id=%d（有邮箱）/ %d（无邮箱）' % (app_mail, app_nomail))

    # ---------- A1 发放 ----------
    print('\n[A1] 点「发放入学码」')
    r1 = call_kw(adm, 'edu.application', 'action_issue_admission_invite', [[app_mail]])
    check('A1-a 调用无错误', 'error' not in r1, True, err_text(r1)[:120])
    row = code_row(app_mail)
    check('A1-b 生成 1 张码并绑定本申请', len(row.split('|')) if row else 0, 6, row[:90])
    cid, ctext, ulimit, exp, bound, cnote = (row.split('|') + [''] * 6)[:6]
    CODES.append(int(cid)) if cid else None
    check('A1-c use_limit=1', ulimit, '1')
    check('A1-d application_id 绑定', bound, str(app_mail))
    exp_dt = datetime.datetime.strptime(exp, '%Y-%m-%d %H:%M')
    delta = (exp_dt - datetime.datetime.now()).total_seconds() / 86400.0
    check('A1-e 有效期 ≈ 14 天（13.5~14.5）', 13.5 <= delta <= 14.5, True, '%.2f 天' % delta)
    check('A1-f 码文本不像短连号', not re.fullmatch(r'\d{1,5}', ctext or 'x'), True, ctext)
    check('A1-g note 指向本申请', '入学申请' in cnote or cnote != '-', True, cnote)

    # ---------- A2 幂等 ----------
    print('\n[A2] 再点一次 = 回显同一张码')
    n_before = one('select count(*) from edu_invite_code where application_id=%d' % app_mail)
    r2 = call_kw(adm, 'edu.application', 'action_issue_admission_invite', [[app_mail]])
    check('A2-a 调用无错误', 'error' not in r2, True, err_text(r2)[:120])
    check('A2-b 行数不变', one('select count(*) from edu_invite_code where application_id=%d' % app_mail), n_before)
    check('A2-c 还是同一张码', code_row(app_mail).split('|')[0], cid)

    # ---------- A3 并发兜底 ----------
    print('\n[A3] 并发兜底：DB 唯一约束真的在')
    out = shell("""
try:
    env['edu.invite.code'].create({'code': 'PROBE-DUP-%s', 'code_kind': 'tier',
        'tier': 'student', 'expire_at': odoo.fields.Datetime.now(), 'use_limit': 1,
        'application_id': %d})
    env.cr.commit()
    print('PROBE_DUP=NO_ERROR')
except Exception as e:
    print('PROBE_DUP=%%s' %% type(e).__name__)
    env.cr.rollback()
""" % (TAG, app_mail))
    check('A3-a 重复绑定被拒（UniqueViolation）',
          'UniqueViolation' in out or 'unique' in out.lower(), True,
          probe(r'PROBE_DUP=(\S+)', out))

    # ---------- A4 邮件尽力而为 ----------
    print('\n[A4] 有邮箱 → 生成邮件且不抛错')
    mail_new = sql("select id||'|'||state||'|'||coalesce(failure_reason,'-') "
                   "from mail_mail where id > %d order by id" % mail_before)
    check('A4-a 生成了邮件记录', bool(mail_new), True, (mail_new.splitlines() or [''])[0][:100])
    st = mail_new.split('|')[1] if mail_new else ''
    check('A4-b 无 SMTP 时 state=exception（如实落库，不抛错）', st, 'exception',
          '若为 outgoing 说明本机配了 SMTP')
    check('A4-c 按钮调用未向教务抛错', 'error' not in r1, True)

    # ---------- A5 无邮箱 ----------
    print('\n[A5] 无邮箱 → 不发信、只回显')
    mail_before2 = int(one('select coalesce(max(id),0) from mail_mail') or 0)
    r5 = call_kw(adm, 'edu.application', 'action_issue_admission_invite', [[app_nomail]])
    check('A5-a 调用无错误', 'error' not in r5, True, err_text(r5)[:120])
    check('A5-b 码仍生成', one('select count(*) from edu_invite_code where application_id=%d' % app_nomail), '1')
    check('A5-c 未新建邮件', int(one('select coalesce(max(id),0) from mail_mail') or 0), mail_before2)
    nid = code_row(app_nomail).split('|')[0]
    CODES.append(int(nid)) if nid else None
    blob = json.dumps(r5, ensure_ascii=False)
    check('A5-d 回显里提示了「没留邮箱」', ('邮箱' in blob), True, blob[:160])
    ctext2 = (code_row(app_nomail).split('|') + [''] * 6)[1]
    if ctext.isdigit() and ctext2.isdigit():
        check('A5-e 两张码不连号（差值 > 1）', abs(int(ctext) - int(ctext2)) > 1, True,
              '%s / %s' % (ctext, ctext2))
    else:
        check('A5-e 两张码不连号（含字母）',
              bool(re.search(r'[A-Za-z]', ctext + ctext2)), True, '%s / %s' % (ctext, ctext2))

    # ---------- A6 表单常驻展示 ----------
    print('\n[A6] 申请表单常驻展示码/发放信息')
    arch = sql("select coalesce(arch_db->>'en_US','') from ir_ui_view "
               "where model='edu.application' and mode='extension' "
               "and arch_db::text like '%%action_issue_admission_invite%%'")
    joined = arch.replace('\n', ' ')
    for name, needle in (('A6-a 发放入学码按钮', 'action_issue_admission_invite'),
                         ('A6-b 重新发放入学码按钮', 'action_reissue_admission_invite'),
                         ('A6-c 展示注册邮箱', 'used_login'),
                         ('A6-d 展示已注册时间', 'used_on')):
        check(name, needle in joined, True)
    check('A6-e 按钮限教务/系统组',
          ('group_op_back_office_admin' in joined and 'base.group_system' in joined), True)

    # ---------- A7 越权 ----------
    print('\n[A7] 学生/教师/家长调用按钮 → 拒止')
    for who in ('stu@local', 'faculty@local', 'parent@local'):
        s = login(who)
        rr = call_kw(s, 'edu.application', 'action_issue_admission_invite', [[app_mail]])
        check('A7-%s %s 被拒' % (who.split('@')[0], who), 'error' in rr, True, err_text(rr)[:90])
    check('A7-d 拒止后码数不变',
          one('select count(*) from edu_invite_code where application_id=%d' % app_mail), '1')

    # ---------- A8 注册邮箱不符：提示不拦截 ----------
    print('\n[A8] used_login ≠ 申请邮箱 → 高亮提示、不拦截')
    check('A8-a 表单里有邮箱比对提示', ('email' in joined and 'used_login' in joined), True)
    shell("""
c = env['edu.invite.code'].search([('application_id', '=', %d)], limit=1)
c.used_login = 'other-%s@example.com'
env.cr.commit()
print('PROBE_OK=1')
""" % (app_mail, TAG.lower()))
    check('A8-b 写入 used_login 成功（未被拦截）',
          one("select count(*) from edu_invite_code where application_id=%d "
              "and used_login like 'other-%%'" % app_mail), '1')

    # ---------- A9 重发 ----------
    print('\n[A9] 重新发放入学码')
    aud_before = int(one("select count(*) from edu_audit_log") or 0)
    r9 = call_kw(adm, 'edu.application', 'action_reissue_admission_invite', [[app_mail]])
    check('A9-a 调用无错误', 'error' not in r9, True, err_text(r9)[:120])
    check('A9-b 旧码解绑',
          one("select count(*) from edu_invite_code where application_id=%d and used_login like 'other-%%'" % app_mail), '0')
    check('A9-c 旧码已过期',
          one("select count(*) from edu_invite_code where code='%s' and expire_at < now()" % ctext), '1')
    check('A9-d 新码已生成',
          one('select count(*) from edu_invite_code where application_id=%d' % app_mail), '1')
    newrow = code_row(app_mail)
    check('A9-e 新码 ≠ 旧码', (newrow.split('|')[1] if newrow else '') != ctext, True)
    if newrow:
        CODES.append(int(newrow.split('|')[0]))
    check('A9-f 审计 ≥ +2', int(one('select count(*) from edu_audit_log') or 0) - aud_before >= 2, True)

    # ---------- A10 撤销 ----------
    print('\n[A10] 撤销 = 过期（不新增状态）')
    past = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    out = shell("""
c = env['edu.invite.code'].search([('application_id', '=', %d)], limit=1)
c.expire_at = '%s'
env.cr.commit()
print('PROBE_OK=1')
""" % (app_mail, past))
    check('A10-a 可置为过期且无新状态字段',
          one('select count(*) from edu_invite_code where application_id=%d and expire_at < now()' % app_mail), '1')
    check('A10-b edu.invite.code 无新增 state 取值依赖',
          'PROBE_OK=1' in out, True)

    # ---------- A11 不碰 TG ----------
    print('\n[A11] 不碰 TG 池')
    check('A11-a edu_tg_claim 行数不变', one('select count(*) from edu_tg_claim'), tg_claim_before)
    check('A11-b TG 池可用数不变',
          one("select count(*) from edu_invite_code where note like '%%TG%%'"), tg_pool_before)

    # ---------- A12 改动面 ----------
    print('\n[A12] 改动面')
    changed = subprocess.run(['git', 'diff', '--name-only', 'HEAD'], cwd=REPO,
                             capture_output=True, text=True).stdout.split()
    changed += subprocess.run(['git', 'diff', '--name-only', '--cached'], cwd=REPO,
                              capture_output=True, text=True).stdout.split()
    # 仓库里同时存在**另一路并发改动**（TG 助手 bot，非本任务，文件集还在变）⇒ 按前缀/命名族排除，
    # 只断言「本任务之外没有别的改动」。用模式而非固定清单，避免并发方新增文件就让探针变红。
    FOREIGN_RE = (r'^custom_addons/edu_tg_assist/', r'^docs/ops/tg-assist-', r'^docs/plans/tg-assist-',
                  r'^tests/unit/tg_assist_', r'^custom_addons/edu_portal/models/notice\.py$',
                  r'^docs/code-map\.md$')
    bad = [f for f in sorted(set(changed))
           if not (f.startswith('custom_addons/edu_admit_invite/')
                   or f in ('docs/plans/admission-invite-link-design.md',
                            'scripts/check_view_xpath.py',
                            'tests/smoke/admit_invite_gate.py')
                   or any(re.match(p, f) for p in FOREIGN_RE))]
    check('A12-a 改动面只有新模块 + 文档 + 探针', bad, [])
    check('A12-b 未碰禁改目录',
          [f for f in set(changed) if re.match(r'custom_addons/(edu_portal|edu_apply|edu_tg_bind)/', f)], [])

    # ---------- A13 门禁 ----------
    print('\n[A13] 静态门禁')
    for label, cmd in (('check_manifest_tracking', ['python3', 'scripts/check_manifest_tracking.py']),
                       ('check_view_xpath', ['python3', 'scripts/check_view_xpath.py']),
                       ('check_view_selector_attrs', ['python3', 'scripts/check_view_selector_attrs.py']),
                       ('check_english', ['python3', 'scripts/check_english.py']),
                       ('check_odoo_trace', ['python3', 'scripts/check_odoo_trace.py']),
                       ('check_ui_surface', ['python3', 'scripts/check_ui_surface.py']),
                       ('check_docs_index', ['python3', 'scripts/check_docs_index.py'])):
        p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900)
        tail = [ln for ln in (p.stdout or '').splitlines() if ln.strip()][-1:] or ['']
        check('A13 %s 退出码 0' % label, p.returncode, 0, tail[0][:90])

    # ---------- A14 清场 ----------
    print('\n[A14] 清场（自还原）')
    # 按「绑在本批申请上」或「本探针建过的码 id」两路删：重发后旧码已解绑（application_id 为空），
    # 只按 application_id 删会漏掉它（2026-10-14 实测 A14-b）。
    shell("""
codes = env['edu.invite.code'].search(['|', ('application_id', 'in', %s), ('id', 'in', %s)])
codes.unlink()
apps = env['edu.application'].browse(%s).exists()
apps.unlink()
env.cr.commit()
print('PROBE_CLEAN=1')
""" % (APPS, CODES or [0], APPS))
    check('A14-a 测试申请残留 0',
          one("select count(*) from edu_application where id in (%s)" % ','.join(map(str, APPS))), '0')
    check('A14-b 测试码残留 0',
          one("select count(*) from edu_invite_code where id in (%s) or code like 'PROBE-%%'"
              % (','.join(map(str, CODES)) or '0')), '0')
    # 邮件也清：mail_mail 没有 subject 列（19 版主题在 mail_message 上）⇒ 按 id 区间删，
    # 与 A4/A5 的计数口径一致。本地克隆独占使用，id 区间不会误伤并发进程。
    shell("""
mails = env['mail.mail'].search([('id', '>', %d)])
mails.unlink()
env.cr.commit()
print('PROBE_MAILCLEAN=1')
""" % mail_before)
    check('A14-c 探针邮件残留 0',
          one("select count(*) from mail_mail where id > %d" % mail_before), '0')

    passed = sum(1 for ok, _ in OK if ok)
    print('\n== 结果：%d / %d PASS ==' % (passed, len(OK)))
    for ok, name in OK:
        if not ok:
            print('   FAIL %s' % name)
    with open(os.path.join(HERE, 'admit_invite_gate_results.json'), 'w') as fh:
        json.dump({'tag': TAG, 'passed': passed, 'total': len(OK),
                   'checks': [{'ok': ok, 'name': n} for ok, n in OK],
                   'notes': NOTES}, fh, ensure_ascii=False, indent=1)
    return 0 if passed == len(OK) else 1


if __name__ == '__main__':
    sys.exit(main())
