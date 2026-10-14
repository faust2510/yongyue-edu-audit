# -*- coding: utf-8 -*-
"""辅助增强批次1冒烟：CSV 导出 / 在线预览 / iCal 订阅（只读验证）。"""
import re
import sys

import requests

BASE = 'http://localhost:8069'
PASS, FAIL = [], []


def check(name, cond, extra=''):
    (PASS if cond else FAIL).append(name)
    print('%s %s%s' % ('PASS' if cond else 'FAIL', name,
                       (' | ' + str(extra)[:120]) if (extra and not cond) else ''))


def login(login_name, password='demo123'):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': 'edu19', 'login': login_name,
                   'password': password}}, timeout=20)
    return s if (r.status_code == 200 and r.json().get('result')) else None


def anon_get(path):
    s = requests.Session()
    s.trust_env = False
    url = path if path.startswith('http') else BASE + path
    return s.get(url, timeout=20, allow_redirects=False)


def csrf_of(session, path):
    t = session.get(BASE + path, timeout=20).text
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', t)
    return m.group(1) if m else ''


def main():
    stu = login('stu@local')
    fac = login('faculty@local')
    check('学生登录', bool(stu))
    check('教师登录', bool(fac))

    # ---- 1a CSV 导出（学生 7 条 + 教师 1 条 + 越权 2 条）----
    exports = {
        '考勤导出': '/student/attendance/export',
        '请假导出': '/my/time_off/export',
        '申诉导出': '/my/grievances/export',
        '账单导出': '/my/fees/export',
        # t9：旧导出入口已收口为 303，不再当“可 200 的导出”列在这里；
        # 真实导出路径 /my/checkins/export 在下方单独断言。
        '下载记录导出': '/downloads/mine/export',
    }
    for name, path in exports.items():
        r = stu.get(BASE + path, timeout=30)
        ok = (r.status_code == 200
              and 'text/csv' in r.headers.get('Content-Type', '')
              and r.content[:3] == b'\xef\xbb\xbf')
        check(name, ok, r.status_code)
    r = stu.get(BASE + '/my/checkins/export', timeout=30)
    check('灵命打卡导出(edu_life)', r.status_code == 200
          and 'text/csv' in r.headers.get('Content-Type', ''), r.status_code)
    # t9：旧导出必须 303 且 Location 精确（不跟随重定向；否则“跟随后 200”会把旧入口判成健康）
    r_old = stu.get(BASE + '/my/checkin/export', timeout=30,
                    allow_redirects=False)
    old_loc = r_old.headers.get('Location', '')
    check('旧福利打卡导出入口 -> 303 /my/checkins/export',
          r_old.status_code == 303 and old_loc.endswith('/my/checkins/export'),
          'HTTP %s Location=%s' % (r_old.status_code, old_loc))
    r_old2 = stu.get(BASE + '/my/checkin', timeout=30, allow_redirects=False)
    old_loc2 = r_old2.headers.get('Location', '')
    check('旧打卡页 -> 303 /my/checkins',
          r_old2.status_code == 303 and old_loc2.endswith('/my/checkins'),
          'HTTP %s Location=%s' % (r_old2.status_code, old_loc2))
    r = fac.get(BASE + '/checkins/stats/export', timeout=30)
    check('教师打卡统计导出', r.status_code == 200
          and 'text/csv' in r.headers.get('Content-Type', ''), r.status_code)
    r = stu.get(BASE + '/checkins/stats/export', timeout=30,
                allow_redirects=False)
    check('学生被挡在统计导出外', r.status_code in (302, 303), r.status_code)
    r = stu.get(BASE + '/downloads/stats/export', timeout=30,
                allow_redirects=False)
    check('学生被挡在下载统计导出外', r.status_code in (302, 303),
          r.status_code)

    # ---- 1b 在线预览 ----
    # 先由教务上传一个【冒烟】PDF（保证有可预览文件），结束后不清理（幂等）
    bo = login('backoffice@local')
    check('教务登录', bool(bo))
    pdf_csrf = csrf_of(bo, '/downloads?mode=manage')
    check('管理模式取到 csrf', bool(pdf_csrf))
    if bo and pdf_csrf:
        page = bo.get(BASE + '/downloads?mode=manage', timeout=20).text
        m = re.search(r'<select[^>]*name="category_id"[^>]*>(.*?)</select>',
                      page, re.S)
        opts = re.findall(r'value="(\d+)"', m.group(1)) if m else []
        if not opts:
            bo.post(BASE + '/downloads/folder/save',
                    data={'csrf_token': pdf_csrf,
                          'name': '【冒烟】预览文件夹'},
                    timeout=20, allow_redirects=False)
            page = bo.get(BASE + '/downloads?mode=manage',
                          timeout=20).text
            m = re.search(
                r'<select[^>]*name="category_id"[^>]*>(.*?)</select>',
                page, re.S)
            opts = re.findall(r'value="(\d+)"', m.group(1)) if m else []
        cat_id = opts[0] if opts else ''
        tiny_pdf = (b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>'
                    b'endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>'
                    b'endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox'
                    b'[0 0 200 200]>>endobj\nxref\n0 4\n'
                    b'trailer<</Size 4/Root 1 0 R>>\n%%EOF')
        bo.post(BASE + '/downloads/upload/save',
                data={'csrf_token': pdf_csrf,
                      'category_id': cat_id, 'new_category': '',
                      'vis_registrar': 'on', 'vis_teacher': 'on',
                      'vis_student': 'on', 'vis_parent': 'on'},
                files=[('files', ('aux冒烟预览.pdf', tiny_pdf,
                                  'application/pdf'))],
                timeout=30)
    r = stu.get(BASE + '/downloads', timeout=30)
    check('下载页可访问', r.status_code == 200, r.status_code)
    m = re.search(r'href="(/downloads/file/\d+\?inline=1)"', r.text)
    check('下载页出现预览按钮(有PDF/图片时)', bool(m))
    if m:
        r2 = stu.get(BASE + m.group(1), timeout=30)
        disp = r2.headers.get('Content-Disposition', '')
        check('预览走 inline + 白名单类型', disp.startswith('inline')
              and ('application/pdf' in r2.headers.get('Content-Type', '')
                   or 'image/' in r2.headers.get('Content-Type', '')),
              (r2.status_code, disp[:60]))

    # ---- 1c iCal ----
    r = stu.get(BASE + '/my/calendar?sub=1', timeout=30)
    check('校历页带 sub 打开', r.status_code == 200, r.status_code)
    m = re.search(r'value="(https?://[^"]+/my/calendar/ics/[0-9a-f]+)"',
                  r.text)
    check('订阅面板出现 ics 链接', bool(m))
    if m:
        feed = m.group(1)
        rr = anon_get(feed)
        body = rr.text
        check('ics 200 + 正确类型',
              rr.status_code == 200
              and 'text/calendar' in rr.headers.get('Content-Type', ''),
              (rr.status_code, rr.headers.get('Content-Type')))
        check('ics 结构完整', body.startswith('BEGIN:VCALENDAR')
              and body.rstrip().endswith('END:VCALENDAR'))
        check('ics 含日历名', 'X-WR-CALNAME' in body)
    rr = anon_get('/my/calendar/ics/deadbeef')
    check('错 token 404', rr.status_code == 404, rr.status_code)
    r = stu.get(BASE + '/my/calendar', timeout=30)
    check('普通校历页无订阅面板', 'my/calendar/ics/' not in r.text)
    r = anon_get('/student/attendance/export')
    check('未登录导出 303', r.status_code in (302, 303), r.status_code)

    print('\nPASS=%d FAIL=%d' % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
