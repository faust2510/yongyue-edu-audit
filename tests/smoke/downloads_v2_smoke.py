# -*- coding: utf-8 -*-
"""资料下载中心 v3 冒烟：四身份 × 可见范围矩阵（幂等，跑完清理归零）。

覆盖：下载端（分组/筛选/下载/审计/可见范围 v3 四组勾选）、管理台（两级
文件夹/批量上传/批量操作含改可见范围）、权限矩阵（学生/教师/家长/教务）。
注意：内部用户渲染的模板会注入 data-oe-* 属性，正则用
name="x"[^>]*value="y" 的宽容形式。
"""
import re
import sys

import requests

BASE = 'http://localhost:8069'
PASS, FAIL = [], []


def check(name, cond, extra=''):
    (PASS if cond else FAIL).append(name)
    print('%s %s%s' % ('PASS' if cond else 'FAIL', name,
                       (' | ' + str(extra)[:100]) if (extra and not cond) else ''))


def login(login_name, password):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': 'edu19', 'login': login_name,
                   'password': password}}, timeout=20)
    return s if (r.status_code == 200 and r.json().get('result')) else None


def csrf_of(session, path):
    t = session.get(BASE + path, timeout=20).text
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', t)
    return m.group(1) if m else ''


def smoke_file_rows(page_html):
    """表格行里带【冒烟】的资料：[(id, 行HTML), ...]"""
    rows = []
    for row in re.finditer(r'<tr[^>]*>.*?</tr>', page_html, re.S):
        chunk = row.group(0)
        if '冒烟' not in chunk:
            continue
        m = re.search(r'name="ids"[^>]*value="(\d+)"', chunk)
        if not m:
            continue
        rows.append((int(m.group(1)), chunk))
    return rows


def vis_all():
    return {'vis_registrar': 'on', 'vis_teacher': 'on',
            'vis_student': 'on', 'vis_parent': 'on'}


def vis_only(*groups):
    d = {k: '' for k in vis_all()}
    for g in groups:
        d['vis_' + g] = 'on'
    return {k: v for k, v in d.items() if v}


def cleanup(bo, csrf):
    """删光【冒烟】文件与文件夹（可反复调用直至归零）。"""
    for _ in range(5):
        t = bo.get(BASE + '/downloads?mode=manage', timeout=20).text
        fids = [fid for fid, _ in smoke_file_rows(t)]
        if fids:
            bo.post(BASE + '/downloads/manage/bulk', data={
                'csrf_token': csrf, 'action': 'delete',
                'ids': [str(i) for i in fids]}, timeout=20,
                allow_redirects=False)
        t = bo.get(BASE + '/downloads?mode=manage', timeout=20).text
        cids = [int(m.group(1)) for m in re.finditer(
            r'【冒烟】[^<]*.{0,600}?name="cid"[^>]*value="(\d+)"',
            t, re.S)]
        if not fids and not cids:
            return True
        for cid in cids:
            bo.post(BASE + '/downloads/folder/delete', data={
                'csrf_token': csrf, 'cid': str(cid)}, timeout=20,
                allow_redirects=False)
    return False


# ---------- 四身份登录 ----------
stu = login('stu@local', 'demo123')
fac = login('faculty@local', 'demo123')
par = login('parent@local', 'demo123')
bo = login('backoffice@local', 'demo123')
check('stu login', stu is not None)
check('faculty login', fac is not None)
check('parent login', par is not None)
check('backoffice login', bo is not None)

# ---------- 下载端基础（回归） ----------
r = stu.get(BASE + '/downloads', timeout=20)
check('GET /downloads = 200', r.status_code == 200)
r = stu.get(BASE + '/downloads?q=请假&sort=hot', timeout=20)
check('搜索筛选态 200', r.status_code == 200)
r = stu.get(BASE + '/downloads/mine', timeout=20)
check('我的下载记录 200', r.status_code == 200)
r = stu.get(BASE + '/downloads/stats', timeout=20, allow_redirects=False)
check('学生访问统计被拒(303)', r.status_code in (302, 303))
r = fac.get(BASE + '/downloads?mode=manage', timeout=20)
check('教师访问管理模式回落普通页', r.status_code == 200
      and '新建文件夹' not in r.text)

# ---------- 管理台 ----------
r = bo.get(BASE + '/downloads?mode=manage', timeout=20)
check('管理模式 200', r.status_code == 200)
check('管理模式含上传面板/文件夹面板/批量条',
      all(k in r.text for k in ('批量上传', '新建文件夹', 'dl_bulk_form')))
check('批量条含改可见范围', '改范围' in r.text and 'vis_registrar' in r.text)
csrf = csrf_of(bo, '/downloads?mode=manage')
check('管理模式取到 csrf', bool(csrf))
check('预清理【冒烟】残留完成', cleanup(bo, csrf))

# 1) 文件夹（两级）
bo.post(BASE + '/downloads/folder/save', data={
    'csrf_token': csrf, 'name': '【冒烟】上级文件夹',
    'sequence': '1'}, timeout=20, allow_redirects=False)
t = bo.get(BASE + '/downloads?mode=manage', timeout=20).text
top_cid = int(re.search(r'【冒烟】上级文件夹.{0,600}?name="cid"[^>]*value="(\d+)"',
                        t, re.S).group(1))
bo.post(BASE + '/downloads/folder/save', data={
    'csrf_token': csrf, 'name': '【冒烟】子文件夹',
    'parent_id': str(top_cid)}, timeout=20, allow_redirects=False)
t = bo.get(BASE + '/downloads?mode=manage', timeout=20).text
sub_cid = int(re.search(r'【冒烟】子文件夹.{0,600}?name="cid"[^>]*value="(\d+)"',
                        t, re.S).group(1))
check('两级文件夹就绪', top_cid > 0 and sub_cid > 0 and sub_cid != top_cid)

file_bytes = b'hello downloads v3'


def upload(bo, csrf, cat, vis, fname='冒烟资料.pdf'):
    data = {'csrf_token': csrf, 'category_id': str(cat),
            'description': 'smoke'}
    data.update(vis)
    return bo.post(BASE + '/downloads/upload/save', data=data,
                   files=[('files', (fname, file_bytes, 'application/pdf'))],
                   timeout=20, allow_redirects=False)


# 2) 三档可见范围上传 + 全不勾被拒
r = upload(bo, csrf, sub_cid, vis_all())
check('公开文件上传成功', 'uploaded=1' in r.headers.get('Location', ''))
r = upload(bo, csrf, sub_cid, vis_only('registrar', 'teacher'))
check('仅教职工文件上传成功', 'uploaded=1' in r.headers.get('Location', ''))
r = upload(bo, csrf, sub_cid, vis_only('student'))
check('仅学生文件上传成功', 'uploaded=1' in r.headers.get('Location', ''))
r = upload(bo, csrf, sub_cid, {})
check('全不勾可见被拒(err=novis)',
      'err=novis' in r.headers.get('Location', ''))

# 3) 管理台行识别（按可见标签）
t = bo.get(BASE + '/downloads?mode=manage', timeout=20).text
rows = smoke_file_rows(t)
check('管理台列出 3 份冒烟资料', len(rows) == 3, len(rows))
fid_pub = fid_staff = fid_stu = 0
for fid, chunk in rows:
    if '公开' in chunk:
        fid_pub = fid
    elif '教务处' in chunk:
        fid_staff = fid
    elif '仅学生' in chunk:
        fid_stu = fid
check('识别出 公开/仅教职工/仅学生 三档',
      bool(fid_pub and fid_staff and fid_stu),
      (fid_pub, fid_staff, fid_stu))


# 4) 四身份 × 三档 下载矩阵
def code(session, fid):
    return session.get(BASE + '/downloads/file/%d' % fid,
                       timeout=20, allow_redirects=False).status_code


if fid_pub:
    check('公开: 学生200/教师200/家长200',
          code(stu, fid_pub) == 200 and code(fac, fid_pub) == 200
          and code(par, fid_pub) == 200)
if fid_staff:
    check('仅教职工: 教师200/学生404/家长404',
          code(fac, fid_staff) == 200 and code(stu, fid_staff) == 404
          and code(par, fid_staff) == 404)
if fid_stu:
    check('仅学生: 学生200/教师404/家长404',
          code(stu, fid_stu) == 200 and code(fac, fid_stu) == 404
          and code(par, fid_stu) == 404)

# 5) 批量改可见范围：仅学生 → 仅家长 → 改回
if fid_stu:
    bo.post(BASE + '/downloads/manage/bulk', data={
        'csrf_token': csrf, 'action': 'visibility',
        'ids': str(fid_stu), 'vis_parent': 'on'},
        timeout=20, allow_redirects=False)
    check('批量改范围: 学生404/家长200',
          code(stu, fid_stu) == 404 and code(par, fid_stu) == 200)
    bo.post(BASE + '/downloads/manage/bulk', data={
        'csrf_token': csrf, 'action': 'visibility',
        'ids': str(fid_stu), 'vis_student': 'on'},
        timeout=20, allow_redirects=False)
    t = bo.get(BASE + '/downloads?mode=manage', timeout=20).text
    check('管理台可见列显示新标签', '仅学生' in t)

# 6) 停用/恢复回归（三份全部停用 → 学生端清空）
all_fids = [str(f) for f, _ in rows if f]
if all_fids:
    bo.post(BASE + '/downloads/manage/bulk', data={
        'csrf_token': csrf, 'action': 'deactivate',
        'ids': all_fids}, timeout=20, allow_redirects=False)
    t = stu.get(BASE + '/downloads', timeout=20).text
    check('全部停用后学生端不可见', '冒烟资料' not in t)
    bo.post(BASE + '/downloads/manage/bulk', data={
        'csrf_token': csrf, 'action': 'activate',
        'ids': all_fids}, timeout=20, allow_redirects=False)
    t = stu.get(BASE + '/downloads', timeout=20).text
    check('恢复后学生端可见', '冒烟资料' in t)

# 7) 非空文件夹删除守卫
r = bo.post(BASE + '/downloads/folder/delete', data={
    'csrf_token': csrf, 'cid': str(sub_cid)}, timeout=20,
    allow_redirects=False)
check('非空子文件夹删除被拒', 'err=folder_not_empty'
      in r.headers.get('Location', ''))

# 8) 统计页
t = bo.get(BASE + '/downloads/stats', timeout=20).text
check('统计页含冒烟文件', '冒烟资料' in t)

# ---------- 清理 ----------
check('清理【冒烟】数据归零', cleanup(bo, csrf))
t = bo.get(BASE + '/downloads?mode=manage', timeout=20).text
check('清理复核：页面无冒烟残留', '冒烟' not in t)

print('\n===== 冒烟结果: %d PASS / %d FAIL =====' % (len(PASS), len(FAIL)))
if FAIL:
    print('失败项:', *FAIL, sep='\n  - ')
    sys.exit(1)
