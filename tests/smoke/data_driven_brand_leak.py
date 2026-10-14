#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据驱动的品牌泄漏门禁（t9 固定检查项）。

为什么单列这一类（队长 2026-09-12 定）：
    页面渲染 `create_uid` / `write_uid` / `user_id` 的**显示名**时，如果这条数据的
    创建人/操作人是**技术账号**（基座把超级用户改名成 `OpenEducat Bot`，res_users.id=1），
    基座品牌就会出现在学生可见页面上。
    这类泄漏**随数据出现/消失**：今天数据里没有机器人建的行 → 门禁全绿；
    明天有人用机器人账号建一条 → 立刻冒出来。它不会被「路由全 200」或「静态文本扫描」稳定拦住。

本脚本做三件事：
    1) 取数：数库内由技术账号（id=1）创建、且会渲染到页面上的记录（edu_download_file / edu_audit_log 等）；
       —— 有既有数据就**只读复用**（不造样本）；没有才用 `--create-sample` 经 odoo shell 造一条【冒烟】样本；
    2) 断言：逐角色抓页面，**可见文本**里不得出现 `OpenEducat` 家族字样；若有技术账号数据，
       对应列必须出现「系统」（正向断言，防"恰好没数据所以恰好没有"）；
    3) 清场：造过样本就删除，并输出 `leftover=0`。

用法：
    python3 tests/smoke/data_driven_brand_leak.py
    python3 tests/smoke/data_driven_brand_leak.py --create-sample   # 库内无技术账号数据时补样本
    python3 tests/smoke/data_driven_brand_leak.py --json /tmp/leak.json
退出码：0=通过；1=发现泄漏；2=运行错误（无法取数 / 登录失败）。
"""
import argparse
import json
import re
import subprocess
import sys

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
ROOT = '.'
PSQL = ['docker', 'compose', 'exec', '-T', 'db', 'psql', '-U', 'odoo', '-d', DB, '-tAc']
ODOO_SHELL = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
              '-c', '/etc/odoo/odoo.conf', '--db_host=db', '--db_port=5432',
              '--db_user=odoo', '--db_password=odoo', '-d', DB, '--no-http']
ROLES = {'student': ('stu@local', 'demo123'), 'faculty': ('faculty@local', 'demo123'),
         'backoffice': ('backoffice@local', 'demo123')}
# 会渲染「操作人/上传人」列的页面（覆盖 create_uid 显示名的三类落点）
PAGES = [('student', '/downloads'), ('student', '/downloads/mine'),
         ('faculty', '/downloads'), ('backoffice', '/downloads?mode=manage'),
         ('backoffice', '/edu/audit')]
# 技术账号 id=1 创建的数据源（列名 -> 用于「有数据就必须显示系统」的正向断言）
TECH_SOURCES = [('edu_download_file', 'uploader 列（/downloads）'),
                ('edu_audit_log', '操作人列（/edu/audit）')]
BRAND_PAT = re.compile(r'OpenEducat(\s+Bot)?', re.I)
SCRIPT_RE = re.compile(r'<script[\s\S]*?</script>', re.I)
STYLE_RE = re.compile(r'<style[\s\S]*?</style>', re.I)
TAG_RE = re.compile(r'<[^>]+>')
SAMPLE_MARK = '【冒烟】机器人上传人渲染测试'


def db_scalar(sql):
    out = subprocess.run(PSQL + [sql], capture_output=True, text=True, timeout=60, cwd=ROOT)
    return out.stdout.strip()


def tech_counts():
    counts = {}
    for table, label in TECH_SOURCES:
        v = db_scalar('select count(*) from %s where create_uid = 1' % table)
        counts[table] = int(v) if v.isdigit() else 0
    return counts


def visible_text(html):
    body = SCRIPT_RE.sub(' ', STYLE_RE.sub(' ', html))
    return TAG_RE.sub(' ', body)


def make_sample():
    """造一条【冒烟】样本（创建人=超级用户 id=1），返回创建的 id 列表。"""
    # 注意：不要用 % 格式化拼这段代码 —— 代码体内本身含 %s/%d，会与占位符冲突
    code = ('mark = ' + repr(SAMPLE_MARK) + """
rec = env['edu.download.category'].sudo().with_user(1).create({'name': mark})
env.cr.commit()
print('SAMPLE_IDS=%s' % rec.id)
""")
    out = subprocess.run(ODOO_SHELL, input=code, capture_output=True, text=True,
                         timeout=180, cwd=ROOT)
    m = re.search(r'SAMPLE_IDS=(\d+)', out.stdout)
    return [int(m.group(1))] if m else []


def drop_sample():
    code = ('mark = ' + repr(SAMPLE_MARK) + """
recs = env['edu.download.category'].sudo().search([('name', '=', mark)])
n = len(recs)
recs.unlink()
env.cr.commit()
print('DELETED=%d' % n)
print('LEFTOVER=%d' % env['edu.download.category'].sudo().search_count([('name', '=', mark)]))
""")
    out = subprocess.run(ODOO_SHELL, input=code, capture_output=True, text=True,
                         timeout=180, cwd=ROOT)
    blob = (out.stdout or '') + (out.stderr or '')
    deleted = re.search(r'DELETED=(\d+)', blob)
    # leftover 以 **psql 直查**为准：odoo shell 的 print 有缓冲/被日志淹没的可能，
    # 不能拿不到回显就当"清干净了"（本脚本第一版就在这里判过 -1）。
    v = db_scalar("select count(*) from edu_download_category where name = '%s'"
                  % SAMPLE_MARK.replace("'", "''"))
    left = int(v) if v.isdigit() else -1
    return (int(deleted.group(1)) if deleted else -1, left)


def login(role):
    user, pwd = ROLES[role]
    s = requests.Session()
    s.trust_env = False
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0', 'params': {'db': DB, 'login': user, 'password': pwd}}, timeout=25)
    return (s, None) if (r.json().get('result') or {}).get('uid') else (None, '登录失败')


def main():
    ap = argparse.ArgumentParser(description='数据驱动的品牌泄漏门禁（t9 固定检查项）')
    ap.add_argument('--create-sample', action='store_true',
                    help='库内没有技术账号数据时，造一条【冒烟】样本并在结束时清场')
    ap.add_argument('--json', dest='json_out')
    args = ap.parse_args()

    try:
        counts = tech_counts()
    except Exception as e:
        print('无法取数（数据库不可达？）: %s' % str(e)[:100])
        return 2
    print('技术账号（id=1）创建的数据：' + '、'.join('%s=%d' % (t, n) for t, n in counts.items()))

    created = []
    if args.create_sample and sum(counts.values()) == 0:
        created = make_sample()
        print('已造【冒烟】样本 id=%s（用后删除）' % created)

    sessions, results, leaks = {}, [], []
    for role in set(r for r, _p in PAGES):
        s, err = login(role)
        if err:
            print('无法继续：%s %s' % (role, err))
            return 2
        sessions[role] = s

    for role, path in PAGES:
        r = sessions[role].get(BASE + path, timeout=40, allow_redirects=False)
        if r.status_code != 200:
            results.append(dict(role=role, path=path, status=r.status_code, note='跳过（非 200）'))
            print('  %-11s %-26s %s 跳过' % (role, path, r.status_code))
            continue
        vis = visible_text(r.text)
        hits = BRAND_PAT.findall(vis)
        sys_n = vis.count('系统')
        results.append(dict(role=role, path=path, status=200,
                            brand_hits=len(hits), sys_label=sys_n))
        flag = 'OK' if not hits else 'LEAK'
        print('  %-11s %-26s 200  品牌字样=%d  「系统」出现=%d  %s'
              % (role, path, len(hits), sys_n, flag))
        if hits:
            leaks.append('%s %s: %s' % (role, path, sorted(set(hits))))

    leftover = 0
    if created:
        deleted, leftover = drop_sample()
        print('清场：删除 %d 条，leftover=%d' % (deleted, leftover))
    else:
        print('未造样本（复用库内既有技术账号数据）；leftover=0')

    has_tech_data = sum(tech_counts().values()) > 0
    if has_tech_data and not any(x.get('sys_label') for x in results if x.get('status') == 200):
        leaks.append('库内存在技术账号创建的数据，但抓到的页面里没有出现「系统」占位 → 正向断言失败')
    if leftover:
        leaks.append('样本清理不干净 leftover=%d' % leftover)

    print('\n============ 汇总 ============')
    print('页面 %d 个：品牌字样泄漏 %d 处%s'
          % (len([x for x in results if x.get('status') == 200]), len(leaks),
             (' → ' + '；'.join(leaks)) if leaks else '（无）'))
    print('结论：%s' % ('通过' if not leaks else '发现泄漏，需 owner 修 _uploader_label/_audit_user_label 口径'))
    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as f:
            json.dump(dict(tech_counts=counts, results=results, leaks=leaks, leftover=leftover),
                      f, ensure_ascii=False, indent=1)
        print('-> %s' % args.json_out)
    return 1 if leaks else 0


if __name__ == '__main__':
    sys.exit(main())
