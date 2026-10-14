#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生产冒烟 P3（强化版）：财务总账 + 报销 —— 镜像学生走真实门户全流程。

对齐验收契约：
  「生产冒烟：/my/fees 200、报销申请路由可达、/ledger 门禁正确（非教务 302）；
    用占位/镜像学生走一笔报销→打勾→付款平账（清理验证数据）」
做法（同 enroll-v2 生产冒烟先例：临时账号 + 镜像档案 + 结束全量清理）：
  A. admin 建临时【冒烟】学生（op.student → 自动 partner）+ portal 账号；
  B. 学生门户：GET /my/fees 200 → GET /my/reimburse/apply 200（申请路由可达）
     → POST /my/reimburse/apply/save 带真实 PNG 收据 → 303 REB 单号落库；
  C. 门禁（**非教务** = 该临时学生，阻断重定向取原始码）：
     /ledger、/ledger/new、/ledger/reimburse 均 303 → /my/home；匿名 → /web/login；
  D. 教务 backoffice@local：/ledger 200、/ledger/reimburse 200、
     /my/fees 200、/ledger/export CSV 200；
  E. 打勾同意（改金额 88.50→80.00）→ 付款登记平账 paid + edu.fee.payment 流水
     → 学生 /my/fees 显示「已付款」；
  F. 收据受控预览：本人 200 且字节一致、/web/image 非真实文件（public=False）；
  G. 驳回：缺原因 box=need_reason；填原因 → refused；
  H. 通知 reimburse_result + 审计 edu.audit.log；
  I. 清理：临时账号/学生/档案/账单/流水/附件/通知/审计 全删，回到基线。

用法：cd /opt/edu-app && python3 /tmp/p3_prod_ledger_smoke2.py；exit 0 = 全绿。

凭据（t81 收口）—— 本脚本打的是**生产**，纪律比仓内其它脚本更严：
  · **不给任何口令默认值**（旧版写死 admin/admin；在一个可能打生产的脚本里写死
    "我们猜的口令"本身就是事故源）；
  · 只从环境变量读：P3_ADMIN_LOGIN / P3_ADMIN_PASSWORD、
    P3_BACKOFFICE_LOGIN / P3_BACKOFFICE_PASSWORD；
  · **读不到就在任何写入之前**明确报错退出（main() 第一行就查）；
  · 口令不出现在任何输出里（打印只出现登录名）；
  · 不 import 仓内模块/常量 —— 本脚本按用法是**拷到 /tmp 执行**的，import 会失败。
登录失败本身旧版已响亮（auth() 直接 SystemExit）；这里只是把凭据来源收口。
"""
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = 'http://127.0.0.1:8069'
DB = 'edu19'
STAMP = datetime.datetime.now().strftime('%m%d%H%M%S')
TAG = '【冒烟测试可删】P3-' + STAMP
LOGIN_S = 'p3smokestu%s@local' % STAMP
PW = 'SmokePass%s!' % STAMP
R = []
STUDENT_ID = USER_ID = PARTNER_ID = 0
bill_ids = []
att_id = 0

# 真实最小 PNG（1x1 红点）——走 Odoo 附件解码路径
PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d494844520000000100000001080200000090'
    '7753de0000000c4944415408d763f8cfc000000301010018dd8db0000000'
    '0049454e44ae426082')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """阻断重定向：取原始状态码 + Location。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def rec(item, expect, actual, result, evidence=''):
    R.append((item, expect, actual, result, evidence))
    print('[%s] %s: %s' % (result, item, actual))


def client(follow=True):
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    handlers = [urllib.request.HTTPCookieProcessor(cj)]
    if not follow:
        handlers.append(NoRedirect())
    return urllib.request.build_opener(*handlers)


def call(opener, model, method, args=None, kwargs=None):
    payload = {'jsonrpc': '2.0', 'method': 'call', 'params': {
        'model': model, 'method': method,
        'args': args or [], 'kwargs': kwargs or {}}}
    req = urllib.request.Request(
        BASE + '/web/dataset/call_kw',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'})
    r = json.loads(opener.open(req, timeout=60).read())
    if 'error' in r:
        raise RuntimeError('%s.%s failed: %s' % (
            model, method,
            r['error'].get('data', {}).get('message', str(r['error'])[:300])))
    return r.get('result')


# ---- 凭据（t81）：**生产脚本，没有任何默认口令** ----
# 角色 -> (login 环境变量, password 环境变量)
CRED_ENV = {
    'admin': ('P3_ADMIN_LOGIN', 'P3_ADMIN_PASSWORD'),
    'backoffice': ('P3_BACKOFFICE_LOGIN', 'P3_BACKOFFICE_PASSWORD'),
}


def creds(role):
    """(login, password)：**只从环境变量读**；读不到就明确报错退出（不写任何东西）。

    为什么一个默认值都不给：本脚本按文件头用法在生产机（cd /opt/edu-app）上跑，
    写死口令等于"把某个库的口令当成生产口令"—— 旧版 admin/admin 就是这么失效的。
    """
    lk, pk = CRED_ENV[role]
    login, pwd = os.environ.get(lk), os.environ.get(pk)
    missing = [k for k, v in ((lk, login), (pk, pwd)) if not v]
    if missing:
        raise SystemExit('缺少环境变量 %s：本脚本打的是**生产**，按 t81 纪律不给任何口令'
                         '默认值。请显式提供后再跑（未做任何写入）。' % '、'.join(missing))
    return login, pwd


def auth(opener, login, pwd):
    req = urllib.request.Request(
        BASE + '/web/session/authenticate',
        data=json.dumps({'jsonrpc': '2.0', 'params': {
            'db': DB, 'login': login, 'password': pwd}}).encode(),
        headers={'Content-Type': 'application/json'})
    r = json.loads(opener.open(req, timeout=60).read())
    uid = (r.get('result') or {}).get('uid')
    if not uid:
        raise SystemExit('登录失败（login=%s）：凭据无效或站点异常 —— 本轮无结论，'
                         '且不会留下任何写入。' % login)
    return uid


def get(opener, path, follow=True):
    req = urllib.request.Request(BASE + path, headers={
        'Accept-Language': 'zh-CN,zh;q=0.9'})
    try:
        resp = opener.open(req, timeout=60)
        return resp.getcode(), resp.read().decode('utf-8', 'replace'), ''
    except urllib.error.HTTPError as e:
        return e.code, '', (e.headers.get('Location') or '')


def get_raw(opener, path):
    """阻断重定向的 GET（返回 bytes，用于字节比对）。"""
    req = urllib.request.Request(BASE + path, headers={
        'Accept-Language': 'zh-CN,zh;q=0.9'})
    try:
        resp = opener.open(req, timeout=60)
        return resp.getcode(), resp.read(), ''
    except urllib.error.HTTPError as e:
        return e.code, b'', (e.headers.get('Location') or '')


def post(opener, path, data):
    body = urllib.parse.urlencode(data, doseq=True).encode()
    req = urllib.request.Request(BASE + path, data=body, headers={
        'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        resp = opener.open(req, timeout=60)
        return resp.getcode(), resp.geturl()
    except urllib.error.HTTPError as e:
        return e.code, (e.headers.get('Location') or '')


def post_multipart(opener, path, fields, files):
    """multipart/form-data 上传（收据）。"""
    boundary = '----p3smoke%s' % STAMP
    parts = []
    for k, v in fields.items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"'
                      '\r\n\r\n%s\r\n' % (boundary, k, v)).encode())
    for k, (fn, content, ct) in files.items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"; '
                      'filename="%s"\r\nContent-Type: %s\r\n\r\n'
                      % (boundary, k, fn, ct)).encode())
        parts.append(content)
        parts.append(b'\r\n')
    parts.append(('--%s--\r\n' % boundary).encode())
    body = b''.join(parts)
    req = urllib.request.Request(BASE + path, data=body, headers={
        'Content-Type': 'multipart/form-data; boundary=%s' % boundary})
    try:
        resp = opener.open(req, timeout=60)
        return resp.getcode(), resp.geturl()
    except urllib.error.HTTPError as e:
        return e.code, (e.headers.get('Location') or '')


def csrf(html):
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html or '')
    return m.group(1) if m else ''


def psql(sql):
    out = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'db', 'psql', '-U', 'odoo',
         '-d', DB, '-tAc', sql], capture_output=True, text=True, timeout=60)
    return [l for l in out.stdout.strip().splitlines() if l.strip()]


def psql1(sql):
    ls = psql(sql)
    return ls[0] if ls else ''


def gid(opener, xmlid):
    mod, name = xmlid.split('.')
    rows = call(opener, 'ir.model.data', 'search_read',
                [[['module', '=', mod], ['name', '=', name]]],
                {'fields': ['res_id'], 'limit': 1})
    return (rows or [{}])[0].get('res_id')


def main():
    global STUDENT_ID, USER_ID, PARTNER_ID, att_id
    # 凭据闸门放在**最前面**：缺环境变量时在建立任何连接、写入任何记录之前就退出。
    creds('admin')
    creds('backoffice')
    adm = client()
    auth(adm, *creds('admin'))
    base_bill = int(psql1('SELECT count(*) FROM edu_fee_bill') or 0)
    base_pay = int(psql1('SELECT count(*) FROM edu_fee_payment') or 0)
    base_msg = int(psql1("SELECT count(*) FROM edu_message") or 0)
    rec('0 基线快照', '记录生产原始计数',
        'bill=%d pay=%d msg=%d' % (base_bill, base_pay, base_msg),
        'PASS' if base_bill == 0 else 'WARN')

    g_portal = gid(adm, 'base.group_portal')

    # ---- A 临时镜像学生 + portal 账号 ----
    STUDENT_ID = call(adm, 'op.student', 'create', [{
        'first_name': '【冒烟】', 'last_name': 'P3学生', 'gender': 'm',
        'email': LOGIN_S}])
    PARTNER_ID = call(adm, 'op.student', 'read',
                      [[STUDENT_ID], ['partner_id']])[0]['partner_id'][0]
    USER_ID = call(adm, 'res.users', 'create', [{
        'name': '【冒烟】P3学生', 'login': LOGIN_S, 'password': PW,
        'partner_id': PARTNER_ID, 'group_ids': [(6, 0, [g_portal])]}])
    call(adm, 'op.student', 'write', [[STUDENT_ID], {'user_id': USER_ID}])
    rec('A 建镜像学生+门户账号', 'op.student/partner/res.users(portal) 就位',
        'student=%s partner=%s user=%s login=%s'
        % (STUDENT_ID, PARTNER_ID, USER_ID, LOGIN_S),
        'PASS' if STUDENT_ID and USER_ID else 'FAIL')

    stu = client()
    auth(stu, LOGIN_S, PW)
    bo = client()
    auth(bo, *creds('backoffice'))

    # ---- B 门户：/my/fees 200 + 申请路由可达 ----
    c, t, _ = get(stu, '/my/fees')
    # 模板口径：role='student' 且 bills 非空时才渲染「统筹费账单/我的报销」分段标题；
    # 镜像学生建单前 0 账单 → 属空态，断言放宽为 200 + 空态正常渲染。
    has_seg = '统筹费账单' in t and '我的报销' in t
    empty_ok = '暂无统筹费账单' in t or '暂无报销' in t or '暂无' in t
    rec('B1 学生 GET /my/fees', '200 正常渲染（首页 0 账单=空态）',
        '%s 分段标题=%s 空态=%s tb=%s len=%d'
        % (c, has_seg, empty_ok, 'Traceback' in t, len(t)),
        'PASS' if c == 200 and (has_seg or empty_ok)
        and 'Traceback' not in t else 'FAIL')

    c, t, _ = get(stu, '/my/reimburse/apply')
    tok = csrf(t)
    rec('B2 学生 GET /my/reimburse/apply', '200 申请表单可达',
        '%s 表单=%s csrf=%s tb=%s'
        % (c, all(x in t for x in ('name="category"', 'name="amount"',
                                   'name="receipts"')), bool(tok),
           'Traceback' in t),
        'PASS' if c == 200 and tok and 'Traceback' not in t else 'FAIL')

    # 带真实 PNG 收据提交
    code, loc = post_multipart(stu, '/my/reimburse/apply/save', {
        'csrf_token': tok, 'category': 'transport', 'amount': '88.50',
        'name': TAG + '交通费', 'note': TAG},
        {'receipts': ('p3receipt.png', PNG, 'image/png')})
    m = re.search(r'REB\d{6}', loc)
    ref_a = m.group(0) if m else ''
    bill_ids.append(psql1("SELECT id FROM edu_fee_bill WHERE "
                          "reimburse_ref='%s'" % ref_a) or 0)
    # Odoo 对 POST 后 redirect 语义返回 200 + 最终 URL（urllib 跟随）；
    # 判据以 Location 文案 + 单号落库为准，两者任一命中即通过。
    sub_ok = ('reimburse_submitted' in loc and ref_a.startswith('REB')
              and bill_ids[0])
    rec('B3 学生提交报销（带收据）', '落库 REB 单号 + 回跳 reimburse_submitted',
        'http=%s loc=%s ref=%s bill=%s'
        % (code, loc, ref_a, bill_ids[0]),
        'PASS' if sub_ok else 'FAIL')

    row = psql1("SELECT id||'|'||coalesce(public::text,'?')||'|'||"
                "coalesce(mimetype,'?') FROM ir_attachment WHERE res_model "
                "IS NULL AND name LIKE 'p3receipt%' ORDER BY id DESC LIMIT 1")
    if row:
        att_id = int(row.split('|')[0])
        pub = row.split('|')[1]
    else:
        pub = '?'
    rec('B4 收据附件 public=False', '未公开（受控预览）',
        'att=%s public=%s' % (att_id, pub),
        'PASS' if att_id and pub == 'false' else 'FAIL')

    # 学生列表可见
    c, t, _ = get(stu, '/my/fees')
    rec('B5 学生账单页显示报销单', '含单号 + 申请中',
        '%s ref=%s 申请中=%s' % (c, ref_a in t, '申请中' in t),
        'PASS' if c == 200 and ref_a in t and '申请中' in t else 'FAIL')

    # ---- C 门禁：非教务（该学生）原始码 ----
    gate = []
    for path in ('/ledger', '/ledger/new', '/ledger/reimburse'):
        g = client(follow=False)
        auth(g, LOGIN_S, PW)
        c, _, loc = get(g, path)
        gate.append('%s=%s->%s' % (path, c, '/my/home' if '/my/home' in loc
                                   else loc))
    c_ok = all('303->/my/home' in x for x in gate)
    rec('C1 门禁：非教务学生访问 /ledger*', '3 条全 303 → /my/home',
        '; '.join(gate), 'PASS' if c_ok else 'FAIL')

    anon = client(follow=False)
    c, _, loc = get(anon, '/ledger')
    rec('C2 门禁：匿名访问 /ledger', '303 → /web/login',
        '%s -> %s' % (c, loc),
        'PASS' if c in (301, 302, 303) and '/web/login' in loc else 'FAIL')

    # 学生直连 RPC 越权（模型层组守卫）
    rpc = urllib.request.build_opener()
    req = urllib.request.Request(
        BASE + '/web/session/authenticate',
        data=json.dumps({'jsonrpc': '2.0', 'params': {
            'db': DB, 'login': LOGIN_S, 'password': PW}}).encode(),
        headers={'Content-Type': 'application/json'})
    stu_uid = json.loads(rpc.open(req, timeout=60).read())['result']['uid']
    obj = __import__('xmlrpc.client', fromlist=['ServerProxy'])
    proxy = obj.ServerProxy(BASE + '/xmlrpc/2/object')
    try:
        proxy.execute_kw(DB, stu_uid, PW, 'edu.fee.bill',
                         'action_reimburse_approve', [[int(bill_ids[0])]])
        r1 = 'OK(越权!)'
    except Exception as exc:  # noqa: BLE001
        r1 = 'ERR(%s)' % str(exc)[:60]
    rec('C3 模型层守卫：学生 RPC 调 approve', 'ERR 被拒',
        r1, 'PASS' if r1.startswith('ERR') else 'FAIL')

    # ---- D 教务侧 ----
    c, t, _ = get(bo, '/my/fees')
    rec('D1 教务 GET /my/fees', '200 无 Traceback',
        '%s tb=%s' % (c, 'Traceback' in t),
        'PASS' if c == 200 and 'Traceback' not in t else 'FAIL')
    c, t, _ = get(bo, '/ledger')
    rec('D2 教务 GET /ledger', '200 应收+应付双向',
        '%s 应收=%s 应付=%s tb=%s' % (c, '应收' in t, '应付' in t,
                                    'Traceback' in t),
        'PASS' if c == 200 and '应收' in t and '应付' in t
        and 'Traceback' not in t else 'FAIL')
    c, t, _ = get(bo, '/ledger/reimburse')
    rec('D3 教务 GET /ledger/reimburse', '200 待批列表含单号',
        '%s 报销审批=%s 单号=%s' % (c, '报销审批' in t, ref_a in t),
        'PASS' if c == 200 and '报销审批' in t and ref_a in t else 'FAIL')
    c, t, _ = get(bo, '/ledger/export?direction=payable')
    rec('D4 /ledger/export CSV', '200 含「报销单号」表头',
        '%s len=%d 表头=%s' % (c, len(t), '报销单号' in t),
        'PASS' if c == 200 and '报销单号' in t else 'FAIL')

    # ---- E 打勾同意（改金额）→ 付款平账 ----
    c, t, _ = get(bo, '/ledger/reimburse')
    code, loc = post(bo, '/ledger/reimburse/set', {
        'csrf_token': csrf(t), 'bill_id': str(bill_ids[0]),
        'action': 'approve', 'approved_amount': '80.00'})
    dbst = psql1("SELECT reimburse_state||'|'||approved_amount FROM "
                 "edu_fee_bill WHERE id=%s" % bill_ids[0])
    rec('E1 打勾同意（改金额 88.50→80.00）', 'approved|80.00',
        'db=%s' % dbst, 'PASS' if dbst.startswith('approved|80.0') else 'FAIL')

    c, t, _ = get(bo, '/ledger/reimburse?filterby=approved')
    code, loc = post(bo, '/ledger/reimburse/set', {
        'csrf_token': csrf(t), 'bill_id': str(bill_ids[0]), 'action': 'pay',
        'method': 'bank', 'note': TAG})
    dbst = psql1("SELECT reimburse_state||'|'||state FROM edu_fee_bill "
                 "WHERE id=%s" % bill_ids[0])
    n_pay = int(psql1('SELECT count(*) FROM edu_fee_payment WHERE bill_id=%s'
                      % bill_ids[0]) or 0)
    amt = psql1('SELECT amount FROM edu_fee_payment WHERE bill_id=%s'
                % bill_ids[0])
    rec('E2 付款登记平账', 'payment 流水 80.00 + paid|paid',
        'db=%s pay=%d amt=%s' % (dbst, n_pay, amt),
        'PASS' if dbst.startswith('paid|paid') and n_pay == 1
        and amt.startswith('80.00') else 'FAIL')

    c, t, _ = get(stu, '/my/fees')
    rec('E3 学生见「已付款」', '200 含已付款',
        '%s 已付款=%s' % (c, '已付款' in t),
        'PASS' if c == 200 and '已付款' in t else 'FAIL')

    # ---- F 收据受控预览（正确口径：授权方可见 + 未授权方拿不到真实字节）----
    if att_id:
        u = '/my/reimburse/receipt/%s/%s?inline=1' % (bill_ids[0], att_id)
        c1, b1, _ = get_raw(stu, u)          # 本人（授权）
        c2, b2, _ = get_raw(bo, u)           # 教务（授权）
        # 未授权方：匿名 + /web/image（t3 HIGH-2 修复的靶心）
        c3, b3, _ = get_raw(client(follow=False), u)
        c4, b4, _ = get_raw(client(follow=False), '/web/image/%s' % att_id)
        c5, b5, _ = get_raw(bo, '/web/image/%s' % att_id)
        auth_ok = c1 == 200 and b1 == PNG and c2 == 200
        # 泄漏判据只看**未授权方**：匿名受控路由 + 匿名 /web/image。
        # 教务 /web/image 属授权访问（审批需要），返回真实字节是正确行为。
        leak_free = (b3 != PNG and b4 != PNG)
        rec('F 收据受控预览',
            '授权: 本人/教务 200 真实字节；未授权: 匿名两路径均无真实字节',
            '本人=%s 教务=%s 匿名受控=%s 匿名/web_image=%s(%dB) '
            '教务/web_image=%s(授权) 真实字节=%s'
            % (c1, c2, c3, c4, len(b4), c5, b1 == PNG),
            'PASS' if auth_ok and leak_free else 'FAIL')
    else:
        rec('F 收据受控预览', '本人 200 且字节一致', '无附件可测', 'FAIL')

    # ---- G 驳回 ----
    c, t, _ = get(stu, '/my/reimburse/apply')
    code, loc = post_multipart(stu, '/my/reimburse/apply/save', {
        'csrf_token': csrf(t), 'category': 'printing', 'amount': '12.34',
        'name': TAG + '打印费', 'note': TAG}, {})
    m = re.search(r'REB\d{6}', loc)
    ref_b = m.group(0) if m else ''
    bid_b = psql1("SELECT id FROM edu_fee_bill WHERE reimburse_ref='%s'"
                  % ref_b) or 0
    bill_ids.append(bid_b)
    c, t, _ = get(bo, '/ledger/reimburse')
    code, loc = post(bo, '/ledger/reimburse/set', {
        'csrf_token': csrf(t), 'bill_id': str(bid_b), 'action': 'refuse',
        'reject_reason': ''})
    rec('G1 驳回缺原因拦截', 'box=need_reason',
        'http=%s loc=%s' % (code, loc),
        'PASS' if 'need_reason' in loc else 'FAIL')
    code, loc = post(bo, '/ledger/reimburse/set', {
        'csrf_token': csrf(t), 'bill_id': str(bid_b), 'action': 'refuse',
        'reject_reason': '发票抬头不符'})
    dbst = psql1("SELECT reimburse_state||'|'||reject_reason FROM "
                 "edu_fee_bill WHERE id=%s" % bid_b)
    rec('G2 驳回（填原因）', 'refused + 原因落库',
        'db=%s' % dbst, 'PASS' if dbst.startswith('refused|发票抬头不符')
        else 'FAIL')

    # ---- H 通知 + 审计 ----
    nn = int(psql1("SELECT count(*) FROM edu_message WHERE "
                   "event_key='reimburse_result' AND (body LIKE '%%%s%%' OR "
                   "body LIKE '%%%s%%')" % (ref_a, ref_b)) or 0)
    rec('H1 通知 reimburse_result', '≥2 条（同意/付款/驳回）',
        '通知=%d' % nn, 'PASS' if nn >= 2 else 'FAIL')
    na = int(psql1("SELECT count(*) FROM edu_audit_log WHERE action IN "
                   "('报销申请','报销审批','报销付款','记账') AND res_name "
                   "IN ('%s','%s')" % (ref_a, ref_b)) or 0)
    rec('H2 审计 edu.audit.log', '≥2 条', '审计=%d' % na,
        'PASS' if na >= 2 else 'FAIL')

    fails = sum(1 for x in R if x[3] == 'FAIL')
    print('\n== 主体 %d/%d passed（FAIL=%d）=='
          % (len(R) - fails, len(R), fails))

    # ---- I 清理 ----
    print('--- cleanup ---')
    try:
        subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                        '-U', 'odoo', '-d', DB, '-c',
                        "DELETE FROM edu_fee_payment WHERE bill_id IN "
                        "(SELECT id FROM edu_fee_bill WHERE name LIKE "
                        "'%【冒烟测试可删】P3%');"],
                       capture_output=True, text=True, timeout=60)
        subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                        '-U', 'odoo', '-d', DB, '-c',
                        "DELETE FROM edu_fee_bill WHERE name LIKE "
                        "'%【冒烟测试可删】P3%' OR note LIKE "
                        "'%【冒烟测试可删】P3%';"],
                       capture_output=True, text=True, timeout=60)
        for sql in (
                "DELETE FROM edu_message WHERE event_key='reimburse_result' "
                "AND (body LIKE '%%%s%%' OR body LIKE '%%%s%%');"
                % (ref_a, ref_b),
                "DELETE FROM edu_audit_log WHERE res_name IN ('%s','%s');"
                % (ref_a, ref_b),
                "DELETE FROM ir_attachment a WHERE a.res_model IS NULL AND "
                "a.name LIKE 'p3receipt%' AND NOT EXISTS (SELECT 1 FROM "
                "edu_fee_bill_receipt_rel r WHERE r.attachment_id=a.id);"):
            subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                            '-U', 'odoo', '-d', DB, '-c', sql],
                           capture_output=True, text=True, timeout=60)
        if USER_ID:
            subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                            '-U', 'odoo', '-d', DB, '-c',
                            "DELETE FROM res_users WHERE id=%d;" % USER_ID],
                           capture_output=True, text=True, timeout=60)
        if STUDENT_ID:
            subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                            '-U', 'odoo', '-d', DB, '-c',
                            "DELETE FROM op_student WHERE id=%d;" % STUDENT_ID],
                           capture_output=True, text=True, timeout=60)
        if PARTNER_ID:
            subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                            '-U', 'odoo', '-d', DB, '-c',
                            "DELETE FROM res_partner WHERE id=%d;" % PARTNER_ID],
                           capture_output=True, text=True, timeout=60)
        b = int(psql1('SELECT count(*) FROM edu_fee_bill') or 0)
        p = int(psql1('SELECT count(*) FROM edu_fee_payment') or 0)
        msg = int(psql1('SELECT count(*) FROM edu_message') or 0)
        aud = int(psql1("SELECT count(*) FROM edu_audit_log WHERE res_name IN "
                        "('%s','%s')" % (ref_a, ref_b)) or 0)
        st_left = int(psql1('SELECT count(*) FROM op_student '
                            'WHERE last_name LIKE %s'
                            % "'%P3学生%'") or 0)
        usr_left = int(psql1("SELECT count(*) FROM res_users WHERE login "
                             "LIKE 'p3smokestu%'") or 0)
        clean = (b == base_bill and p == base_pay and msg == base_msg
                 and aud == 0 and st_left == 0 and usr_left == 0)
        rec('I1 清理回基线', '账单/流水/通知回到原始计数，账号/学生/档案 0 残留',
            'bill=%d(%d) pay=%d(%d) msg=%d(%d) aud=%d stu=%d usr=%d'
            % (b, base_bill, p, base_pay, msg, base_msg, aud, st_left,
               usr_left),
            'PASS' if clean else 'FAIL')
    except Exception as exc:  # noqa: BLE001
        rec('I1 清理回基线', 'psql delete', '清理异常: %s' % exc, 'FAIL')

    fails = sum(1 for x in R if x[3] == 'FAIL')
    print('\n== FINAL %d/%d passed（FAIL=%d）=='
          % (len(R) - fails, len(R), fails))
    return 0 if fails == 0 else 1


if __name__ == '__main__':
    sys.exit(main())