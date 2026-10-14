# -*- coding: utf-8 -*-
"""辅助增强批次4冒烟：操作审计 / 教师作业管理 / 公告有效期与附件。"""
import re
import subprocess
import sys

import requests

BASE = 'http://localhost:8069'
PASS, FAIL = [], []


def check(name, cond, extra=''):
    (PASS if cond else FAIL).append(name)
    print('%s %s%s' % ('PASS' if cond else 'FAIL', name,
                       (' | ' + str(extra)[:140]) if (extra and not cond) else ''))


def login(login_name, password='demo123'):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': 'edu19', 'login': login_name,
                   'password': password}}, timeout=20)
    return s if (r.status_code == 200 and r.json().get('result')) else None


def odoo_shell(snippet):
    cmd = ("docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf "
           "-d edu19 --db_host=db -r odoo -w odoo --http-port=8099")
    p = subprocess.run(cmd, shell=True, input=snippet.encode() +
                       b"\nexit()\n", capture_output=True, timeout=180)
    return p.stdout.decode(errors='replace') + p.stderr.decode(
        errors='replace')


TAG = u'【冒烟】aux4'


def kv(blob, key):
    m = re.search(r'%s=(\S+)' % re.escape(key), blob)
    return m.group(1) if m else None


def cleanup_aux4():
    """删除本冒烟造的全部夹具（幂等）。

    与 t80 对 F_roles_smoke 同一形态：**先记 tag → finally 自清 → 断言 leftover=0**。

    历史教训（t82）：本脚本原先**完全不自清**，每跑一次就留下
    1 条审计 + 2 条公告 + 1 套作业夹具；跑到第 4 次时 `check_english` 全量报
    must-fix 1 —— 因为审计行的 detail 是**可见英文** `smoke-detail-x`。
    门禁没错，是夹具没走。故此处：① 把 detail 改成中文（连瞬时可见英文都不留）；
    ② 按 tag 自清；③ 清完断言 leftover=0。
    """
    return odoo_shell(
        "T = u'" + TAG + "'\n"
        "A = env['edu.audit.log'].sudo()\n"
        "A.search([('action', '=', u'审计冒烟'), ('detail', '=', T + u' 审计明细')]).unlink()\n"
        "N = env['edu.notice'].sudo().with_context(active_test=False)\n"
        "N.search([('name', 'like', T)]).unlink()\n"
        "GA = env['grading.assignment'].sudo().with_context(active_test=False)\n"
        "ga = GA.search([('name', 'like', T)])\n"
        "env['op.assignment'].sudo().with_context(active_test=False).search(\n"
        "    [('grading_assignment_id', 'in', ga.ids)]).unlink()\n"
        "ga.unlink()\n"
        "env.cr.commit()\n"
        "print('LEFT_AUDIT=%d' % A.search_count([('action', '=', u'审计冒烟'), ('detail', '=', T + u' 审计明细')]))\n"
        "print('LEFT_NOTICE=%d' % N.search_count([('name', 'like', T)]))\n"
        "print('LEFT_ASG=%d' % GA.search_count([('name', 'like', T)]))\n")


def _main_body():
    fac = login('faculty@local')
    bo = login('backoffice@local')
    stu = login('stu@local')
    check('登录三身份', bool(fac and bo and stu))

    # ---- 4a 审计查询页 ----
    r = bo.get(BASE + '/edu/audit', timeout=30)
    check('审计页(教务) 200', r.status_code == 200, r.status_code)
    check('审计页标题与筛选', '操作审计' in r.text and 'filterby=all' in r.text)
    r = stu.get(BASE + '/edu/audit', timeout=30, allow_redirects=False)
    check('学生被挡在审计页外', r.status_code in (302, 303), r.status_code)
    r = fac.get(BASE + '/edu/audit?search=演示', timeout=30)
    check('审计搜索不炸', r.status_code == 200, r.status_code)

    # shell 造一条审计记录再验证页面可见
    out = odoo_shell(
        "env['edu.audit.log'].sudo()._log(\n"
        "    '审计冒烟', 'edu.notice', 0, u'" + TAG + " 审计条目',\n"
        "    u'" + TAG + " 审计明细')\n"
        "env.cr.commit()\n"
        "print('AUDIT_OK')\n")
    check('审计写入', 'AUDIT_OK' in out, out[-150:])
    # 用中文 tag 搜（原先搜的是可见英文 smoke-detail-x —— 它在页面上就是 must-fix）
    r = bo.get(BASE + '/edu/audit?search=aux4', timeout=30)
    check('审计页搜到冒烟条目', '审计冒烟' in r.text and '审计明细' in r.text)

    # ---- 4c 作业管理 ----
    r = fac.get(BASE + '/assignment/manage', timeout=30)
    check('作业管理列表 200', r.status_code == 200, r.status_code)
    check('作业管理含筛选 chips', 'filterby=publish' in r.text
          and '已发布' in r.text)
    # shell 造一条教师作业，验证编辑/名单/撤回
    out = odoo_shell(
        "u = env['res.users'].sudo().search([('login','=','faculty@local')], limit=1)\n"
        "fac = env['op.faculty'].sudo().search([('user_id','=',u.id)], limit=1)\n"
        "ga = env['grading.assignment'].sudo().create({\n"
        "    'name': u'" + TAG + " 作业管理测试', 'course_id': env['op.course'].sudo().search([], limit=1).id,\n"
        "    'issued_date': '2026-08-01 00:00:00',\n"
        "    'assignment_type': env['grading.assignment.type'].sudo().search([], limit=1).id,\n"
        "    'faculty_id': fac.id})\n"
        "asg = env['op.assignment'].sudo().create({\n"
        "    'grading_assignment_id': ga.id,\n"
        "    'batch_id': env['op.batch'].sudo().search([], limit=1).id,\n"
        "    'marks': 100,\n"
        "    'description': '冒烟', 'state': 'publish',\n"
        "    'submission_date': '2026-09-30 00:00:00'})\n"
        "env.cr.commit()\n"
        "print('ASG_ID', asg.id)\n")
    m = re.search(r'ASG_ID (\d+)', out)
    check('造作业成功', bool(m), out[-150:])
    if m:
        aid = m.group(1)
        r = fac.get(BASE + '/assignment/edit/%s' % aid, timeout=30)
        check('编辑页 200', r.status_code == 200
              and '编辑作业' in r.text, r.status_code)
        csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
        r2 = fac.post(BASE + '/assignment/edit/%s/save' % aid, data={
            'csrf_token': csrf.group(1) if csrf else '',
            'name': TAG + u' 作业管理测试(改)',
            'description': '冒烟改', 'marks': '90',
            'submission_date': '2026-10-15T23:59',
        }, timeout=30, allow_redirects=False)
        check('编辑保存 303', r2.status_code in (302, 303), r2.status_code)
        r3 = fac.get(BASE + '/assignment/submissions/%s' % aid, timeout=30)
        check('名单页 200', r3.status_code == 200
              and '提交名单' in r3.text, r3.status_code)
        r4 = fac.post(BASE + '/assignment/set_state', data={
            'csrf_token': csrf.group(1) if csrf else '',
            'aid': aid, 'state': 'cancel',
        }, timeout=30, allow_redirects=False)
        check('撤回 303', r4.status_code in (302, 303), r4.status_code)
        r5 = stu.get(BASE + '/student/assignment/details', timeout=30)
        check('学生作业页不含已撤销作业', '作业管理测试' not in r5.text)
        # 越权：学生访问编辑页
        r6 = stu.get(BASE + '/assignment/edit/%s' % aid, timeout=30,
                     allow_redirects=False)
        check('学生被挡在作业编辑外', r6.status_code in (302, 303),
              r6.status_code)

    # ---- 4b 公告有效期 ----
    # shell 造一条已过期+一条未过期公告，验证列表只显示未过期
    out = odoo_shell(
        "env['edu.notice'].sudo().create({'name': u'" + TAG + " 未过期公告',\n"
        "    'content': 'x', 'date_until': '2030-01-01'})\n"
        "env['edu.notice'].sudo().create({'name': u'" + TAG + " 已过期公告',\n"
        "    'content': 'x', 'date_until': '2020-01-01'})\n"
        "env.cr.commit()\n"
        "print('NTC_OK')\n")
    check('造公告成功', 'NTC_OK' in out, out[-150:])
    r = stu.get(BASE + '/my/notice_board/notice', timeout=30)
    check('布告栏显示未过期公告', '未过期公告' in r.text, r.status_code)
    check('布告栏不显示已过期公告', '已过期公告' not in r.text)
    r = stu.get(BASE + '/my/search', params={'q': '过期公告'}, timeout=30)
    check('搜索不含已过期公告', '已过期公告' not in r.text)

    return None


def main():
    """外层生命周期：先清残留 → 跑主体 → **finally 自清** → 断言 leftover=0。

    主体内部即使 sys.exit（失败退出）也会被 finally 兜住，故**任何路径都清场**。
    t82 的教训：原先完全没清场，跑 4 次就留下 4 条审计 + 6 条公告 + 4 套作业，
    最终让 check_english 全量报 must-fix 1（审计行 detail 是可见英文）。
    """
    cleanup_aux4()                      # 幂等：先清上次残留（含被中断的那次）
    try:
        _main_body()
    except SystemExit:
        pass
    finally:
        out = cleanup_aux4()
        check('自清·审计 leftover=0', kv(out, 'LEFT_AUDIT') == '0',
              'LEFT_AUDIT=%s' % kv(out, 'LEFT_AUDIT'))
        check('自清·公告 leftover=0', kv(out, 'LEFT_NOTICE') == '0',
              'LEFT_NOTICE=%s' % kv(out, 'LEFT_NOTICE'))
        check('自清·作业 leftover=0', kv(out, 'LEFT_ASG') == '0',
              'LEFT_ASG=%s' % kv(out, 'LEFT_ASG'))
    print('\nPASS=%d FAIL=%d' % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
