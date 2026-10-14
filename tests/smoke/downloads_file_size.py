#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资料「大小 0KB」回归冒烟：store=True 的 compute 字段缺 @api.depends → 列恒 NULL。

为什么需要它（2026-09-24 生产事故，系统所有者报「上传文件资料失败」）
------------------------------------------------------------------
现象：/downloads 上传返回 303 uploaded=1、行已落库、字节完好，但列表「大小」列
恒显示 0B，于是被读成「上传失败 / 文件是空的」。
根因：models/downloads.py 的 file_size 是 store=True 的 compute 字段，却**没有
@api.depends('file')**（create 时 ORM 只跑过一次 compute，此刻附件尚未写入 ⇒
列留 NULL；此后 file 变化不再触发重算）。唯一重算入口是 init() 里手写的
add_to_compute —— 只在 -u 时跑、且被 try/except 吞错，因此「上传后立刻显示」
永远是 0B。页面渲染 _human_size(f.file_size or 0) ⇒ NULL 变成 "0B"。
教训：**没有断言盯住这个列，它就静默烂掉**（生产 3/3 行 NULL，无人发现）。

三层断言（任一层红即 exit 1）
----------------------------
  L1 静态（离线，不连站点）：edu_portal/models/*.py 里每个 store=True 的
     compute 字段，其 compute 方法必须带**紧邻的** @api.depends(...) 装饰器。
     —— 钉住「bug 类」，不是钉住这一行代码。
  L2 行为（真上传）：上传一个已知字节数的文件 → 断言
     ① 该行 file_size 非 NULL 且 == 上传字节数；② 列表页该行大小列不再是 0B；
     ③ 从 /downloads/file/<id> 下载回来的字节与上传逐位一致（sha256）；
     ④ 换文件（write 路径）后 file_size 跟着变。
  L3 不变式（全库）：凡有附件的资料行，file_size 必须非 NULL 且等于
     ir_attachment.file_size。事故发生时的读数就是这条会红（3/3 行 NULL）。

用法：python3 tests/smoke/downloads_file_size.py
退出码：0=全绿；1=有断言失败；2=运行错误（站点不可达 / 容器未起 / 登录失败）。
跑完自动删除本次【冒烟】文件（幂等，可反复跑）。
"""
import glob
import hashlib
import os
import re
import subprocess
import sys

import requests

BASE = os.environ.get('SMOKE_BASE', 'http://localhost:8069')
DB = os.environ.get('SMOKE_DB', 'edu19')
MODELS_GLOB = 'custom_addons/edu_portal/models/*.py'
MARK = '\u3010\u5192\u70df\u3011\u5927\u5c0f\u65ad\u8a00'  # 【冒烟】大小断言
UPLOAD_BYTES = 300000
REPLACE_BYTES = 4096

ODOO = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
        '-c', '/etc/odoo/odoo.conf', '--db_host=db', '--db_port=5432',
        '--db_user=odoo', '--db_password=odoo', '-d', DB, '--no-http']

PASS, FAIL = [], []
ENV_ERR = []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    tag = 'PASS' if cond else 'FAIL'
    print('%s %s%s' % (tag, name, (' | ' + str(detail)[:160]) if detail else ''))
    return cond


def shell(code, timeout=240):
    """在 odoo shell 里跑一段代码，返回 stdout+stderr 合并文本。"""
    try:
        out = subprocess.run(ODOO, input=code, capture_output=True,
                             text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:  # 环境不可用
        ENV_ERR.append(str(exc))
        return ''
    return (out.stdout or '') + (out.stderr or '')


def sql_cell(query, timeout=240):
    """跑一条单值 SQL，返回该值（None = SQL NULL）。"""
    blob = shell("env.cr.execute(%r)\nprint('CELL=%%r' %% (env.cr.fetchone(),))"
                 % query, timeout=timeout)
    m = re.search(r"CELL=\(\(?([^,)]+),?\)?\)", blob)
    if not m:
        ENV_ERR.append('no CELL in shell output: %s' % blob[-200:])
        return None
    raw = m.group(1).strip()
    return None if raw == 'None' else raw


# ---------------------------------------------------------------------------
# L1 静态：store=True 的 compute 字段必须有紧邻的 @api.depends
# ---------------------------------------------------------------------------
def static_depends_check():
    print('\n== L1 静态：stored compute 必须有 @api.depends ==')
    fields_seen, broken = 0, []
    for path in sorted(glob.glob(MODELS_GLOB)):
        text = open(path, encoding='utf-8').read()
        for m in re.finditer(
                r"(\w+)\s*=\s*fields\.(\w+)\(((?:[^()]|\([^()]*\))*?)\)\s*\n",
                text):
            fname, args = m.group(1), m.group(3)
            if 'compute=' not in args or 'store=True' not in args:
                continue
            method = re.search(r"compute=\s*['\"]([^'\"]+)", args).group(1)
            line_no = text[:m.start()].count('\n') + 1
            fields_seen += 1
            # 装饰器必须**紧邻** def（允许跨行的参数列表）
            dec = re.search(
                r"@api\.depends\((?:[^()]|\([^()]*\))*\)\s*\n\s*def\s+%s\s*\("
                % re.escape(method), text)
            if not dec:
                broken.append('%s:%d %s (compute=%s)'
                              % (os.path.basename(path), line_no, fname,
                                 method))
    check('L1.1 stored compute 字段存在（防"恰好没扫到所以通过"）',
          fields_seen > 0, 'fields_seen=%d' % fields_seen)
    check('L1.2 每个 stored compute 都有 @api.depends', not broken,
          '; '.join(broken) or 'all ok (%d fields)' % fields_seen)


# ---------------------------------------------------------------------------
# 会话工具
# ---------------------------------------------------------------------------
def login(login_name, password):
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.post(BASE + '/web/session/authenticate', json={
            'jsonrpc': '2.0',
            'params': {'db': DB, 'login': login_name,
                       'password': password}}, timeout=20)
    except requests.RequestException as exc:
        ENV_ERR.append(str(exc))
        return None
    return s if (r.status_code == 200 and r.json().get('result')) else None


def csrf_of(session, path):
    t = session.get(BASE + path, timeout=20).text
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', t)
    return m.group(1) if m else ''


def smoke_rows(page_html):
    """管理模式表格里带【冒烟】的行：[row_html, ...]（含 id 才能删干净）。"""
    rows = []
    for row in re.finditer(r'<tr[^>]*>.*?</tr>', page_html, re.S):
        chunk = row.group(0)
        if MARK not in chunk:
            continue
        if not re.search(r'name="ids"[^>]*value="(\d+)"', chunk):
            continue
        rows.append(chunk)
    return rows


def row_id_of(page_html):
    for chunk in smoke_rows(page_html):
        m = re.search(r'name="ids"[^>]*value="(\d+)"', chunk)
        if m:
            return int(m.group(1))
    return 0


def size_text_of(page_html):
    """该行「大小」列渲染出来的文本（如 293KB / 0B）。"""
    for chunk in smoke_rows(page_html):
        m = re.search(r'text-nowrap">([\d.]+\s?[KMG]?B)</td>', chunk)
        if m:
            return m.group(1).replace(' ', '')
    return ''


def cleanup(bo, csrf):
    """删掉本次【冒烟】文件（幂等）。"""
    for _ in range(5):
        t = bo.get(BASE + '/downloads?mode=manage', timeout=20).text
        chunks = smoke_rows(t)
        if not chunks:
            return True
        fids = [re.search(r'name="ids"[^>]*value="(\d+)"', c).group(1)
                for c in chunks]
        bo.post(BASE + '/downloads/manage/bulk', data={
            'csrf_token': csrf, 'action': 'delete', 'ids': fids},
            timeout=20, allow_redirects=False)
    return False


def vis_all():
    return {'vis_registrar': 'on', 'vis_teacher': 'on',
            'vis_student': 'on', 'vis_parent': 'on'}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    static_depends_check()

    print('\n== L2 行为：真上传 → 列非 NULL + 页面非 0B + 字节可逐位取回 ==')
    bo = login('backoffice@local', 'demo123')
    if bo is None:
        print('FAIL backoffice 登录失败（站点 %s / 库 %s 不可用？）' % (BASE, DB))
        return 2
    csrf = csrf_of(bo, '/downloads?mode=manage')
    check('L2.0 取到 csrf（管理模式可达）', bool(csrf))
    if not csrf:
        return 2
    cleanup(bo, csrf)

    # 目标文件夹：用页面上第一个已有文件夹；一个也没有就在库里挑一个 id
    t = bo.get(BASE + '/downloads?mode=manage', timeout=20).text
    m = re.search(r'name="category_id"[^>]*>\s*<option value="">[^<]*</option>'
                  r'\s*<option value="(\d+)"', t)
    cat = m.group(1) if m else ''
    if not cat:
        cat = sql_cell("select id from edu_download_category order by id"
                       " limit 1") or ''
    check('L2.1 有可用目标文件夹', bool(cat), 'cat=%s' % cat)
    if not cat:
        return 2

    payload = bytes(bytearray((i * 7 + 13) % 251 for i in range(UPLOAD_BYTES)))
    data = {'csrf_token': csrf, 'category_id': str(cat),
            'description': 'smoke file_size'}
    data.update(vis_all())
    r = bo.post(BASE + '/downloads/upload/save', data=data,
                files=[('files', (MARK + '.pdf', payload,
                                  'application/pdf'))],
                timeout=60, allow_redirects=False)
    check('L2.2 上传返回 303 uploaded=1',
          r.status_code in (302, 303) and 'uploaded=1' in
          r.headers.get('Location', ''), r.headers.get('Location', ''))

    t = bo.get(BASE + '/downloads?mode=manage', timeout=20).text
    fid = row_id_of(t)
    check('L2.3 管理页列出该行（拿到 id）', fid > 0, 'fid=%s' % fid)
    if not fid:
        return 1

    col = sql_cell('select file_size from edu_download_file where id=%d' % fid)
    check('L2.4 file_size 非 NULL（事故值：NULL）', col not in (None, 'None'),
          'file_size=%s' % col)
    check('L2.5 file_size == 上传字节数', col == str(UPLOAD_BYTES),
          'col=%s sent=%d' % (col, UPLOAD_BYTES))
    shown = size_text_of(t)
    check('L2.6 列表大小列不是 0B（事故表现）', shown not in ('', '0B'),
          'shown=%s' % shown)

    got = bo.get(BASE + '/downloads/file/%d' % fid, timeout=60)
    check('L2.7 下载回 200 且字节逐位一致',
          got.status_code == 200
          and hashlib.sha256(got.content).hexdigest()
          == hashlib.sha256(payload).hexdigest(),
          'http=%s bytes=%s' % (got.status_code, len(got.content)))

    # 换文件（write 路径）：file_size 必须跟着变
    repl = bytes(bytearray((i * 11 + 3) % 241 for i in range(REPLACE_BYTES)))
    rd = {'csrf_token': csrf, 'fid': str(fid), 'name': MARK + '.pdf',
          'category_id': str(cat), 'vis_registrar': 'on', 'active': '1'}
    bo.post(BASE + '/downloads/manage/file/update', data=rd,
            files=[('replace_file', (MARK + '.pdf', repl,
                                     'application/pdf'))],
            timeout=60, allow_redirects=False)
    col2 = sql_cell('select file_size from edu_download_file where id=%d' % fid)
    check('L2.8 换文件后 file_size 跟着变', col2 == str(REPLACE_BYTES),
          'col=%s sent=%d' % (col2, REPLACE_BYTES))

    print('\n== L3 不变式：全库 file_size == 真实附件字节数 ==')
    blob = shell(
        "env.cr.execute('''\n"
        "select count(*), count(*) filter (where f.file_size is null),\n"
        "       count(*) filter (where a.file_size is not null\n"
        "                            and f.file_size is distinct from a.file_size)\n"
        "  from edu_download_file f\n"
        "  left join ir_attachment a\n"
        "    on a.res_model = 'edu.download.file'\n"
        "   and a.res_field = 'file' and a.res_id = f.id\n"
        "''')\n"
        "print('INV=%r' % (env.cr.fetchone(),))\n")
    m = re.search(r'INV=\((\d+), (\d+), (\d+)\)', blob)
    if not m:
        ENV_ERR.append('no INV reading: %s' % blob[-200:])
        check('L3.0 读到全库不变式读数', False, blob[-160:])
    else:
        total, nulls, mismatch = (int(m.group(1)), int(m.group(2)),
                                  int(m.group(3)))
        check('L3.1 无 NULL 大小行（事故读数：3/3 行 NULL）', nulls == 0,
              'rows=%d null=%d' % (total, nulls))
        check('L3.2 无「列值 ≠ 附件真实字节数」的行', mismatch == 0,
              'rows=%d mismatch=%d' % (total, mismatch))

    ok = cleanup(bo, csrf)
    check('L4.1 清理【冒烟】文件归零', ok)

    print('\n===== 结果: %d PASS / %d FAIL =====' % (len(PASS), len(FAIL)))
    if FAIL:
        print('失败项:')
        for f in FAIL:
            print('  - ' + f)
        return 1
    return 0


if __name__ == '__main__':
    try:
        code = main()
    except Exception as exc:  # 环境错误与断言失败分开，便于门禁分流
        print('RUN ERROR: %r' % exc)
        code = 2
    if code == 2 and ENV_ERR:
        print('环境错误: %s' % ENV_ERR[-1][:200])
    elif ENV_ERR and code == 1:
        print('（提示：部分读数缺失，可能是环境问题）')
    sys.exit(code)
