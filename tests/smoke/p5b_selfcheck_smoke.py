# -*- coding: utf-8 -*-
"""第 5 批 B 冒烟：QR 限时自助签到全链路（教师开码→学生扫码→落考勤）。"""
import re
import subprocess
import sys

import requests

BASE = 'http://localhost:8069'
REPO = '/Users/qwe/Documents/文件大总管/10-项目/教务系统网站新架构'
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


def today():
    p = subprocess.run(
        ["docker", "compose", "exec", "-T", "web", "date", "+%Y-%m-%d"],
        capture_output=True, text=True, cwd=REPO)
    return p.stdout.strip()


def main():
    fac = login('faculty@local')
    stu = login('stu@local')
    check('登录', bool(fac and stu))

    out = odoo_shell(
        "u = env['res.users'].sudo().search([('login','=','stu@local')], limit=1)\n"
        "stu = env['op.student'].sudo().search([('user_id','=',u.id)], limit=1)\n"
        "sc = env['op.student.course'].sudo().search([('student_id','=',stu.id)], limit=1)\n"
        "print('BATCH', sc.batch_id.id if sc else 0)\n"
        "env.cr.commit()\n")
    m = re.search(r'BATCH (\d+)', out)
    bid = m.group(1) if m and m.group(1) != '0' else None
    check('找到学生班级', bool(bid), out[-150:])
    if not bid:
        print('\nPASS=%d FAIL=%d' % (len(PASS), len(FAIL)))
        return

    d = today()
    out = odoo_shell(
        "sheet = env['op.attendance.sheet'].sudo().search(\n"
        "    [('batch_id','='," + bid + "),\n"
        "     ('attendance_date','=',__import__('datetime').date.today().strftime('%Y-%m-%d'))], limit=1)\n"
        "print('SHEET', sheet.id if sheet else 0)\n")
    has_sheet = 'SHEET 0' not in out
    if not has_sheet:
        out = odoo_shell(
            "sc = env['op.student.course'].sudo().search([('batch_id','='," + bid + ")], limit=1)\n"
            "sheet = env['op.attendance.sheet'].sudo().search(\n"
            "    [('batch_id','='," + bid + "),\n"
            "     ('attendance_date','=',__import__('datetime').date.today().strftime('%Y-%m-%d'))], limit=1)\n"
            "if not sheet and sc:\n"
            # 建簿走教师侧同一个取或建实现：基座没有 start_date/end_date、code 是
            # required+unique（原夹具照抄了教师侧的历史缺陷，全新 (课程,班级) 上必崩）
            "    from odoo.addons.edu_portal.controllers.roles import attendance_register\n"
            "    reg = attendance_register(env, sc.course_id, sc.batch_id)\n"
            "    sheet = env['op.attendance.sheet'].sudo().create(\n"
            "        {'register_id': reg.id, 'course_id': sc.course_id.id,\n"
            "         'batch_id': sc.batch_id.id,\n"
            "         'attendance_date': __import__('datetime').date.today(),\n"
            "         'faculty_id': env['op.faculty'].sudo().search([], limit=1).id})\n"
            "    line = env['op.attendance.line'].sudo().search(\n"
            "        [('attendance_id','=',sheet.id),('student_id','=',sc.student_id.id)], limit=1)\n"
            "    if not line:\n"
            "        env['op.attendance.line'].sudo().create(\n"
            "            {'attendance_id': sheet.id, 'student_id': sc.student_id.id,\n"
            "             'present': False, 'late': False, 'absent': True,\n"
            "             'excused': False, 'course_id': sc.course_id.id,\n"
            "             'batch_id': sc.batch_id.id,\n"
            "             'attendance_date': __import__('datetime').date.today()})\n"
            "env.cr.commit()\n"
            "print('SHEET2', env['op.attendance.sheet'].sudo().search_count(\n"
            "    [('batch_id','='," + bid + "), ('attendance_date','=',__import__('datetime').date.today().strftime('%Y-%m-%d'))]))\n")
        has_sheet = 'SHEET2 0' not in out
    check('存在当日点名表', has_sheet, out[-200:])

    rp = fac.get(BASE + '/attendance/take?batch_id=' + bid, timeout=30)
    c = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', rp.text)
    r = fac.post(BASE + '/attendance/selfcheck/start', data={
        'csrf_token': c.group(1) if c else '',
        'batch_id': bid, 'date': d}, timeout=30,
        allow_redirects=False)
    check('开启自助签到 303', r.status_code in (302, 303), r.status_code)
    loc = r.headers.get('Location', '/attendance/take')
    r = fac.get(BASE + loc, timeout=30)
    check('take 页出现 QR 卡片', 'selfcheck-card' in r.text
          and '/report/barcode' in r.text)
    m3 = re.findall(r'/attendance/selfcheck/([A-Za-z0-9_\-]+)', r.text)
    scan_path = ('/attendance/selfcheck/' + m3[0]) if m3 else None
    check('页面含扫码地址', bool(scan_path), scan_path)
    if scan_path:
        r2 = stu.get(BASE + scan_path, timeout=30)
        ok = r2.status_code == 200 and ('签到成功' in r2.text
                                        or '已经签过' in r2.text)
        check('学生扫码签到成功/幂等', ok, (r2.status_code, r2.text[:120]))
        out3 = odoo_shell(
            "u = env['res.users'].sudo().search([('login','=','stu@local')], limit=1)\n"
            "stu = env['op.student'].sudo().search([('user_id','=',u.id)], limit=1)\n"
            "ln = env['op.attendance.line'].sudo().search(\n"
            "    [('student_id','=',stu.id),\n"
            "     ('attendance_date','=',__import__('datetime').date.today().strftime('%Y-%m-%d')),\n"
            "     ('batch_id','='," + bid + ")], limit=1)\n"
            "print('PRESENT', bool(ln) and bool(ln.present))\n")
        check('考勤行已置到堂', 'PRESENT True' in out3, out3[-200:])
        r4 = fac.get(BASE + scan_path, timeout=30, allow_redirects=False)
        check('教师扫码被引导回主页', r4.status_code in (302, 303),
              r4.status_code)

    print('\nPASS=%d FAIL=%d' % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
