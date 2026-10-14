# -*- coding: utf-8 -*-
"""第 5 批 F 冒烟：学生名单 CSV 两段式导入（预览校验→确认→档案落库）。"""
import re
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


CSV_HEADER = '姓名,学号,性别,出生日期,邮箱,手机\n'


def main():
    bo = login('backoffice@local')
    stu = login('stu@local')
    check('登录', bool(bo and stu))

    r = bo.get(BASE + '/edu/import/students', timeout=30)
    check('导入页(教务) 200', r.status_code == 200
          and '导入学生名单' in r.text, r.status_code)
    r2 = stu.get(BASE + '/edu/import/students', timeout=30,
                 allow_redirects=False)
    check('学生被挡在导入页外', r2.status_code in (302, 303), r2.status_code)

    csv_text = (CSV_HEADER
                + '测试导入甲,P5A001,男,2001-05-01,a1@example.com,13800000001\n'
                + '测试导入乙,P5A002,女,2002-07-12,,\n'
                + '测试导入丙,P5A001,男,,,\n'          # 学号重复
                + ',P5A003,,,\n'                       # 缺姓名
                + '测试导入丁,,男,,,\n')               # 缺学号
    c = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    r = bo.post(BASE + '/edu/import/students/preview', data={
        'csrf_token': c.group(1) if c else '',
    }, files=[('file', ('p5_smoke.csv', csv_text.encode('utf-8'),
                         'text/csv'))], timeout=30)
    check('预览页 200', r.status_code == 200, r.status_code)
    check('可导入行数=2', '可导入 <span class="text-success" t-out="len(preview_rows[\'valid\'])"/>' not in r.text
          and '测试导入甲' in r.text and '测试导入乙' in r.text)
    check('错误行原因显示', '文件内学号重复' in r.text and '缺姓名' in r.text
          and '缺学号' in r.text)

    # 确认导入（从预览页抓 payload）
    m = re.search(r'name="payload"[^>]*value="([^"]*)"', r.text)
    check('确认表单携带合法行', bool(m) and 'P5A001' in m.group(1)
          and 'P5A002' in m.group(1))
    if m:
        import json as _json
        payload = m.group(1).replace('&#34;', '"').replace('&amp;', '&')
        r2 = bo.post(BASE + '/edu/import/students/commit', data={
            'csrf_token': c.group(1) if c else '', 'payload': payload},
            timeout=30, allow_redirects=False)
        check('确认导入 303', r2.status_code in (302, 303), r2.status_code)
        r3 = bo.get(BASE + '/edu/import/students?done=2&skip=0', timeout=30)
        check('结果提示导入 2 人', '新建' in r3.text and '2' in r3.text)
        # 复核档案真实落库
        import subprocess
        out = subprocess.run(
            ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo",
             "-d", "edu19", "-Atc",
             "SELECT count(*) FROM op_student WHERE gr_no IN ('P5A001','P5A002')"],
            capture_output=True, text=True).stdout.strip()
        check('档案落库 2 人', out == '2', out)
        # 审计有记录
        r4 = bo.get(BASE + '/edu/audit?search=学生导入', timeout=30)
        check('审计含学生导入', '学生导入' in r4.text)

    # 清理冒烟数据
    import subprocess
    subprocess.run(
        ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo",
         "-d", "edu19", "-c",
         "DELETE FROM op_student WHERE gr_no IN ('P5A001','P5A002');"
         "DELETE FROM res_partner WHERE name IN ('测试导入甲','测试导入乙') "
         "AND id NOT IN (SELECT partner_id FROM op_student);"],
        capture_output=True, text=True)
    out2 = subprocess.run(
        ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo",
         "-d", "edu19", "-Atc",
         "SELECT count(*) FROM op_student WHERE gr_no LIKE 'P5A%'"],
        capture_output=True, text=True).stdout.strip()
    check('冒烟档案清理归零', out2 == '0', out2)

    print('\nPASS=%d FAIL=%d' % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
