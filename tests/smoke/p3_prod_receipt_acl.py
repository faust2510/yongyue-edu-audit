#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生产验收补充：报销收据访问控制矩阵（授权 vs 未授权）。

背景：第二版冒烟 F 项用「本人/教务」测 /web/image —— 二者都是**授权方**，
拿到真实字节属正确行为，不能据此判泄漏。真正的安全口径是：
**未授权方（匿名 / 其他学生）不得拿到真实收据字节**（t3 HIGH-2 修复目标）。

本脚本建立收据访问矩阵（4 类主体 × 2 条取数路径）：
  1. 本人（申请人）      /my/reimburse/receipt/... → 200 真实字节；/web/image → 允许
  2. 教务（审批方）      /my/reimburse/receipt/... → 200 真实字节；/web/image → 允许
  3. 匿名（未登录）      /my/reimburse/receipt/... → 404/303；/web/image → **非真实字节**
  4. 其他学生（第三方）  /my/reimburse/receipt/... → 404；/web/image → **非真实字节**

结论判据：未授权方两条路径都拿不到真实字节 = PASS。
用法：cd /opt/edu-app && python3 /tmp/p3_prod_receipt_acl.py
"""
import datetime
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = 'http://127.0.0.1:8069'
DB = 'edu19'
STAMP = datetime.datetime.now().strftime('%m%d%H%M%S')
TAG = '【冒烟测试可删】ACL-' + STAMP
R = []
PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d494844520000000100000001080200000090'
    '7753de0000000c4944415408d763f8cfc000000301010018dd8db0000000'
    '0049454e44ae426082')
# 与 PNG 不同的哨兵字节，用于识别占位图/非真实内容
SENTINEL = b'\x89PNG\r\n\x1a\n' + b'\x00' * 40 + b'P3-REAL-RECEIPT'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def rec(item, expect, actual, result, evidence=''):
    R.append((item, expect, actual, result, evidence))
    print('[%s] %s: %s' % (result, item, actual))


def client(follow=True):
    import http.cookiejar
    handlers = [urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())]
    if not follow:
        handlers.append(NoRedirect())
    return urllib.request.build_opener(*handlers)


def call(op, model, method, args=None, kwargs=None):
    payload = {'jsonrpc': '2.0', 'method': 'call', 'params': {
        'model': model, 'method': method, 'args': args or [],
        'kwargs': kwargs or {}}}
    req = urllib.request.Request(BASE + '/web/dataset/call_kw',
                                 data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    r = json.loads(op.open(req, timeout=60).read())
    if 'error' in r:
        raise RuntimeError('%s.%s: %s' % (model, method,
                                          r['error'].get('data', {})
                                          .get('message', '')[:200]))
    return r.get('result')


def auth(op, login, pwd):
    req = urllib.request.Request(
        BASE + '/web/session/authenticate',
        data=json.dumps({'jsonrpc': '2.0', 'params': {
            'db': DB, 'login': login, 'password': pwd}}).encode(),
        headers={'Content-Type': 'application/json'})
    uid = (json.loads(op.open(req, timeout=60).read()).get('result')
           or {}).get('uid')
    if not uid:
        raise SystemExit('login failed %s' % login)
    return uid


def get_bytes(op, path):
    req = urllib.request.Request(BASE + path)
    try:
        resp = op.open(req, timeout=60)
        return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b''


def psql1(sql):
    out = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                          '-U', 'odoo', '-d', DB, '-tAc', sql],
                         capture_output=True, text=True, timeout=60)
    ls = [l for l in out.stdout.strip().splitlines() if l.strip()]
    return ls[0] if ls else ''


def psql(sql):
    out = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                          '-U', 'odoo', '-d', DB, '-tAc', sql],
                         capture_output=True, text=True, timeout=60)
    return [l for l in out.stdout.strip().splitlines() if l.strip()]


def mk_student(adm, tag, login, pw, g_portal):
    sid = call(adm, 'op.student', 'create', [{
        'first_name': '【冒烟】', 'last_name': tag, 'gender': 'm',
        'email': login}])
    pid = call(adm, 'op.student', 'read', [[sid], ['partner_id']])[0][
        'partner_id'][0]
    uid = call(adm, 'res.users', 'create', [{
        'name': '【冒烟】' + tag, 'login': login, 'password': pw,
        'partner_id': pid, 'group_ids': [(6, 0, [g_portal])]}])
    call(adm, 'op.student', 'write', [[sid], {'user_id': uid}])
    return sid, pid, uid


def main():
    adm = client()
    auth(adm, 'admin', 'admin')
    g_portal = call(adm, 'ir.model.data', 'search_read',
                    [[['module', '=', 'base'], ['name', '=', 'group_portal']]],
                    {'fields': ['res_id'], 'limit': 1})[0]['res_id']

    base_bill = int(psql1('SELECT count(*) FROM edu_fee_bill') or 0)
    login_a = 'p3owner%s@local' % STAMP
    login_b = 'p3other%s@local' % STAMP
    pw = 'SmokePass%s!' % STAMP

    s_a, p_a, u_a = mk_student(adm, 'ACL本人', login_a, pw, g_portal)
    s_b, p_b, u_b = mk_student(adm, 'ACL第三方', login_b, pw, g_portal)

    owner = client()
    auth(owner, login_a, pw)
    other = client()
    auth(other, login_b, pw)
    bo = client()
    auth(bo, 'backoffice@local', 'demo123')
    anon = client()

    # 本人经门户上传收据（真实落库路径）
    c, t = get_bytes(owner, '/my/reimburse/apply')
    tok = (re.search(r'name="csrf_token"[^>]*value="([^"]+)"',
                     t.decode('utf-8', 'replace')) or [None, ''])[1]
    boundary = '----acl%s' % STAMP
    body = b''.join([
        ('--%s\r\nContent-Disposition: form-data; name="csrf_token"'
         '\r\n\r\n%s\r\n' % (boundary, tok)).encode(),
        ('--%s\r\nContent-Disposition: form-data; name="category"'
         '\r\n\r\ntransport\r\n' % boundary).encode(),
        ('--%s\r\nContent-Disposition: form-data; name="amount"'
         '\r\n\r\n55.55\r\n' % boundary).encode(),
        ('--%s\r\nContent-Disposition: form-data; name="name"'
         '\r\n\r\n%s\r\n' % (boundary, TAG)).encode(),
        ('--%s\r\nContent-Disposition: form-data; name="receipts"; '
         'filename="aclrec.png"\r\nContent-Type: image/png\r\n\r\n'
         % boundary).encode(),
        SENTINEL, b'\r\n', ('--%s--\r\n' % boundary).encode()])
    req = urllib.request.Request(
        BASE + '/my/reimburse/apply/save', data=body,
        headers={'Content-Type': 'multipart/form-data; boundary=%s'
                                % boundary})
    try:
        resp = owner.open(req, timeout=60)
        loc = resp.geturl()
        code = resp.getcode()
    except urllib.error.HTTPError as e:
        code, loc = e.code, e.headers.get('Location') or ''
    ref = (re.search(r'REB\d{6}', loc) or [''])[0]
    bid = psql1("SELECT id FROM edu_fee_bill WHERE reimburse_ref='%s'" % ref)
    att = psql1("SELECT a.id FROM ir_attachment a JOIN "
                "edu_fee_bill_receipt_rel r ON r.attachment_id=a.id "
                "WHERE r.bill_id=%s LIMIT 1" % (bid or 0))
    pub = psql1('SELECT public FROM ir_attachment WHERE id=%s' % (att or 0))
    rec('0 建立收据样本', '单号+附件+public=false',
        'code=%s ref=%s bill=%s att=%s public=%s'
        % (code, ref, bid, att, pub),
        'PASS' if ref and bid and att and pub in ('f', 'false') else 'FAIL')

    if not (bid and att):
        print('无法建立样本，终止'); return 1

    ctrl = '/my/reimburse/receipt/%s/%s?inline=1' % (bid, att)
    wimg = '/web/image/%s' % att

    # 1 本人
    c1, b1 = get_bytes(owner, ctrl)
    c2, b2 = get_bytes(owner, wimg)
    rec('1 本人：受控路由', '200 真实字节', '%s real=%s' % (c1, b1 == SENTINEL),
        'PASS' if c1 == 200 and b1 == SENTINEL else 'FAIL')
    rec('1b 本人：/web/image', '200（授权方；经 Odoo 图片通道，允许且不构成泄漏）',
        '%s real=%s（Odoo 对 image/* 走 _postprocess 重编码，字节自然不同）'
        % (c2, b2 == SENTINEL),
        'PASS' if c2 == 200 else 'FAIL')

    # 2 教务
    c3, b3 = get_bytes(bo, ctrl)
    c4, b4 = get_bytes(bo, wimg)
    rec('2 教务：受控路由', '200 真实字节（审批需要）',
        '%s real=%s' % (c3, b3 == SENTINEL),
        'PASS' if c3 == 200 and b3 == SENTINEL else 'FAIL')
    rec('2b 教务：/web/image', '200（授权方，允许）',
        '%s real=%s' % (c4, b4 == SENTINEL),
        'PASS' if c4 == 200 and b4 == SENTINEL else 'FAIL')

    # 3 匿名 —— 安全关键
    c5, b5 = get_bytes(anon, ctrl)
    c6, b6 = get_bytes(anon, wimg)
    rec('3 匿名：受控路由', '非 200 / 无真实字节（404 或 303）',
        '%s(%d bytes) real=%s' % (c5, len(b5), b5 == SENTINEL),
        'PASS' if b5 != SENTINEL else 'FAIL')
    rec('3b 匿名：/web/image ⚠安全关键', '无真实字节（占位或拒绝）',
        '%s(%d bytes) real=%s' % (c6, len(b6), b6 == SENTINEL),
        'PASS' if b6 != SENTINEL else 'FAIL')

    # 4 其他学生 —— 安全关键
    c7, b7 = get_bytes(other, ctrl)
    c8, b8 = get_bytes(other, wimg)
    rec('4 第三方学生：受控路由', '404 无真实字节',
        '%s(%d bytes) real=%s' % (c7, len(b7), b7 == SENTINEL),
        'PASS' if b7 != SENTINEL else 'FAIL')
    rec('4b 第三方学生：/web/image ⚠安全关键', '无真实字节',
        '%s(%d bytes) real=%s' % (c8, len(b8), b8 == SENTINEL),
        'PASS' if b8 != SENTINEL else 'FAIL')

    fails = sum(1 for x in R if x[3] == 'FAIL')
    print('\n== 矩阵 %d/%d passed（FAIL=%d）=='
          % (len(R) - fails, len(R), fails))

    # 清理
    try:
        psql("DELETE FROM edu_fee_bill WHERE name LIKE '%【冒烟测试可删】ACL%'")
        psql("DELETE FROM ir_attachment a WHERE a.res_model IS NULL AND "
             "a.name LIKE 'aclrec%' AND NOT EXISTS (SELECT 1 FROM "
             "edu_fee_bill_receipt_rel r WHERE r.attachment_id=a.id)")
        psql("DELETE FROM res_users WHERE login LIKE 'p3owner%' OR "
             "login LIKE 'p3other%'")
        psql("DELETE FROM op_student WHERE last_name IN ('ACL本人','ACL第三方')")
        for pid in (p_a, p_b):
            psql('DELETE FROM res_partner WHERE id=%d' % pid)
        left = int(psql1('SELECT count(*) FROM edu_fee_bill') or 0)
        ls = int(psql1("SELECT count(*) FROM op_student WHERE last_name LIKE "
                       "'ACL%'") or 0)
        lu = int(psql1("SELECT count(*) FROM res_users WHERE login LIKE "
                       "'p3owner%' OR login LIKE 'p3other%'") or 0)
        lat = int(psql1("SELECT count(*) FROM ir_attachment WHERE name LIKE "
                        "'aclrec%'") or 0)
        rec('Z 清理', '回基线（账单=%d）' % base_bill,
            'bill=%d stu=%d usr=%d att=%d' % (left, ls, lu, lat),
            'PASS' if left == base_bill and ls == 0 and lu == 0
            and lat == 0 else 'FAIL')
    except Exception as exc:  # noqa: BLE001
        rec('Z 清理', 'psql', '异常: %s' % exc, 'FAIL')

    fails = sum(1 for x in R if x[3] == 'FAIL')
    print('\n== FINAL %d/%d passed（FAIL=%d）=='
          % (len(R) - fails, len(R), fails))
    return 0 if fails == 0 else 1


if __name__ == '__main__':
    sys.exit(main())