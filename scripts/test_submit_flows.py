# -*- coding: utf-8 -*-
"""端到端验证：请假/申诉/换课提交 + 证书下载（Phase 3/4 验收）。

用法：python3 scripts/test_submit_flows.py
"""
import datetime
import re

import requests

# 2026-10-04（第 63 轮）：原先请假用的是**写死的过去日期** 2026-09-01/02 —— 一条「验收脚本」
#   不该依赖「今天是哪天」。改成按当天推算的未来日期，脚本才真的可重复执行。
_TODAY = datetime.date.today()
_D1 = (_TODAY + datetime.timedelta(days=3)).isoformat()
_D2 = (_TODAY + datetime.timedelta(days=4)).isoformat()

BASE = 'http://localhost:8069'


def csrf_of(session, path):
    html = session.get(BASE + path, timeout=20).text
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html) or \
        re.search(r'value="([^"]+)"\s*name="csrf_token"', html)
    return m.group(1) if m else ''


def main():
    s = requests.Session()
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': 'edu19', 'login': 'stu@local',
                   'password': 'demo123'}} if False else {
        'jsonrpc': '2.0',
        'params': {'db': 'edu19', 'login': 'stu@local',
                   'password': 'demo123'}}, timeout=15)
    print('login', r.status_code)

    token = csrf_of(s, '/my/time_off')
    ok = bool(token)
    print('csrf token:', 'OK' if ok else 'MISSING')
    if not ok:
        return 1

    # ---- 请假提交 ----
    r = s.post(BASE + '/my/time_off/save', data={
        'csrf_token': token,
        'leave_type': 'sick',
        'date_from': _D1,
        'date_to': _D2,
        'reason': '感冒发烧，需要休息（验收测试）',
        # 2026-10-04（第 63 轮）：**病假连续两天及以上必须给证明**（条例二·3，控制器
        #   models/leave_flow.py:139/141 会退回并提示「请先填写「证明方式」」）。
        #   原脚本不传这个字段 ⇒ 被正确挡回 ⇒ 报 FAIL。**是脚本漏填，不是产品坏了**：
        #   实测渲染后的学生表单**有** proof_kind 字段（还带 proof_file / oral_proof_by /
        #   oral_proof_relation），只是脚本没传。合法值 file / oral / none，
        #   oral 要求 oral_proof_by 非空、file 要求有附件（见 leave_flow.py:347 help）。
        'proof_kind': 'oral',
        'oral_proof_by': '家长（验收测试）',
    }, timeout=20, allow_redirects=True)
    ok1 = 'box=submitted' in r.url or ('已提交' in r.text)
    print('leave submit:', 'PASS' if ok1 else 'FAIL', r.status_code, r.url[:70])

    # ---- 申诉提交 ----
    r = s.post(BASE + '/my/grievances/save', data={
        'csrf_token': token,
        'subject': '图书馆座位预约异常（验收测试）',
        'category': '图书馆 / 设施问题',
        'description': '验收测试自动提交，可删除。',
    }, timeout=20, allow_redirects=True)
    ok2 = 'box=submitted' in r.url or ('已提交' in r.text)
    print('grievance submit:', 'PASS' if ok2 else 'FAIL', r.status_code)

    # ---- 换课提交（课程 ID 从页面下拉框动态取） ----
    page = s.get(BASE + '/course/change/request', timeout=20).text
    mopt = re.search(r'name="course_id"[^>]*>\s*<option[^>]*>.*?</option>\s*'
                     r'<option value="(\d+)"', page, re.S)
    course_id = mopt.group(1) if mopt else ''
    r = s.post(BASE + '/course/change/request/save', data={
        'csrf_token': token,
        'course_id': course_id,
    }, timeout=20, allow_redirects=True)
    ok3 = 'box=submitted' in r.url or ('已提交' in r.text)
    print('course change submit:', 'PASS' if ok3 else 'FAIL', r.status_code)

    # ---- 提交结果落库复核（页面出现新单号） ----
    h = s.get(BASE + '/my/time_off', timeout=20).text
    ok1b = re.search(r'SLR\d{6}', h) is not None
    print('leave record visible:', 'PASS' if ok1b else 'FAIL')
    h = s.get(BASE + '/my/grievances', timeout=20).text
    ok2b = '图书馆座位预约异常' in h
    print('grievance visible:', 'PASS' if ok2b else 'FAIL')
    h = s.get(BASE + '/course/change/request', timeout=20).text
    ok3b = re.search(r'SR\d{4}', h) is not None and '已提交' in h
    print('course change visible:', 'PASS' if ok3b else 'FAIL')

    # ---- 证书列表与 PDF 下载 ----
    h = s.get(BASE + '/certificate', timeout=20).text
    m = re.search(r'/my/certificate/download/(\d+)', h)
    ok4 = bool(m)
    print('certificate listed:', 'PASS' if ok4 else 'FAIL')
    if ok4:
        d = s.get(BASE + '/my/certificate/download/' + m.group(1),
                  timeout=30)
        is_pdf = d.headers.get('Content-Type', '').startswith('application/pdf') \
            or d.content[:4] == b'%PDF'
        print('certificate pdf:', 'PASS' if is_pdf else 'FAIL',
              d.status_code, len(d.content), 'bytes')

    verdict = all([ok1, ok2, ok3, ok1b, ok2b, ok3b, ok4])
    print('OVERALL:', 'PASS' if verdict else 'FAIL')
    return 0 if verdict else 2


if __name__ == '__main__':
    raise SystemExit(main())
