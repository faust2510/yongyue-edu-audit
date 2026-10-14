#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零功能丢失门禁：L1 路由可达 + L2 IA 覆盖 + 共享类契约。

依据：docs/plans/study-hub-v3-design.md §6（旧首页 35 张卡逐项落点）与 §10.3（本脚本提案）。
目的：把「零丢失」从设计声明变成机器可验证的回归门禁 ——
      （2026-09-29：旧 B 套两卡 eval/my + eval/review 并成一张 assess/my ⇒ 名单实为 34 张）
      **只有 L2 能抓到「卡被悄悄删掉」**（L1 只证明 URL 打得开，不证明用户还点得到）。

三层断言：
  L1 可达性：34 张旧卡 + 9 张动态注入卡的 href 逐条 GET，期望 200 / 3xx→最终 <400；
             6 张默认隐藏卡同样必须可达（隐藏 ≠ 删除）。
  L2 IA 覆盖：抓 /my/apps 的 HTML，断言 34 条 href 都出现在里面（默认隐藏卡豁免，见 §10.3）。
  L0 类契约：o_portal_index_card 类被 7 个模板共用，首页重构不得改名/删除 ——
             本脚本核对 /my/messages、/my/contacts、/my/child 仍有该类。

身份：L1 默认用 admin（超集，避免 notice/publish、timetable/* 这类角色门禁误报）+ student 复核列；
      L2 用 student（/my/apps 是学生的页面），学生不可达时回退 admin。

用法：
  python3 tests/smoke/zero_loss_reachability.py
  python3 tests/smoke/zero_loss_reachability.py --role student
  python3 tests/smoke/zero_loss_reachability.py --json /tmp/zl.json
退出码：0=全绿；1=有缺失（不可达 / 未出现在 /my/apps / 类契约被破坏）；2=运行错误（登录失败、服务不可达、
        /my/apps 未交付 → L2 无法判定）。
"""
import argparse
import json
import re
import sys
import time

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
APPS_PATH = '/my/apps'

# ---------------------------------------------------------------- 常量（单一真源 = 设计文档 §6）
# 旧首页的卡：_OPENEDUCAT_CARDS(26) + _COMMON_CARDS(2) + _YONGYUE_CARDS(6)
# 2026-09-29 起实为 **34 张**：原 _YONGYUE_CARDS 里的 eval/my（我的评分）与
# eval/review（评教填答）两张卡，随 edu_eval（行政评估）模块删除而**并成一张**
# assess/my（我的评估）—— batch2.py 的 spec_map 以 href 为键，两张同 href 的卡
# 会渲染成两张一模一样的瓦片，故并卡是唯一正确形态。
# 常量名保留 STALE_35_HREFS（历史名）：改名会牵动本文件 6 处引用与两份留档，
# 与「修掉删除带来的失配」无关。
STALE_35_HREFS = [
    'student/profile', 'my/fees', 'my-library', 'library/media',
    'meeting/information', 'my/notice_board/notice', 'users/result-overview',
    'my/time_off', 'student/progression', 'subject/details', 'my/asset-request',
    'student/assignment/details', 'student/exam', 'my/grievances', 'my-courses',
    'certificate', 'student/attendance', 'student/newregistration/info',
    'student/timetable', 'grade-book', 'course/change/request', 'subject/enroll',
    'subject/registration', 'my/academic-calendar', 'my/thesis', 'online/meeting',
    'my/addresses', 'my/password',   # 2026-09-24：'my/security' → 我们自己的逐字安全改密页
    'my/checkins', 'my/journals', 'assess/my', 'help',
    'downloads', 'my/reimburse/apply',
]
# 动态注入卡（不在 35 内，同样不得丢失）
DYNAMIC_HREFS = [
    'my/child', 'quiz', 'notice/publish', 'timetable/bulk',
    'my/contacts', 'my/calendar', 'my/messages', 'alumni/job/list',
]
# 6 张默认隐藏卡（batch2.py:292 _DEFAULT_HIDDEN_CARDS 同名单）：L1 必须可达、L2 豁免
HIDDEN_L2_EXEMPT = {'help', 'student/timetable', 'my/academic-calendar',
                    'student/newregistration/info', 'my/rfq', 'my/purchase'}
# 改动前就 404 的路由（batch2.py:293-294 注释自认「路由缺失」；2026-09-12 实测 404）：
# 属历史欠账，不是本轮重构的回归 —— 如实列出但不判 FAIL。
BASELINE_MISSING = {'my/rfq', 'my/purchase', 'student/newregistration/info'}
# 共享类契约：这些页面必须继续渲染 .o_portal_index_card（7 模板共用，改了会连锁返工）
CLASS_CONTRACT = [('student', '/my/messages'), ('student', '/my/contacts'),
                  ('parent', '/my/child')]
CLASS_NAME = 'o_portal_index_card'
ROLE_ACCOUNTS = {
    'student': ('stu@local', 'demo123'),
    'parent': ('parent@local', 'demo123'),
    'faculty': ('faculty@local', 'demo123'),
    'backoffice': ('backoffice@local', 'demo123'),
    'admin': ('admin', 'admin'),
}
ERR_MARKS = ('Traceback (most recent call last)', 'Internal Server Error',
             'odoo.exceptions.', 'werkzeug.exceptions.')


def login(role):
    login_name, pwd = ROLE_ACCOUNTS[role]
    s = requests.Session()          # cookie jar：session_id 全程复用
    s.trust_env = False
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    last = ''
    for attempt in (1, 2):
        try:
            r = s.post(BASE + '/web/session/authenticate', json={
                'jsonrpc': '2.0',
                'params': {'db': DB, 'login': login_name, 'password': pwd},
            }, timeout=25)
            payload = r.json()
            if (payload.get('result') or {}).get('uid'):
                return s, None
            err = payload.get('error') or {}
            last = (err.get('data', {}).get('message') or err.get('message')
                    or 'HTTP %s 无 uid' % r.status_code)
        except Exception as e:
            last = '登录异常 %s' % str(e)[:80]
        if attempt == 1:
            time.sleep(5)
    return None, last


def fetch(sess, path, max_hops=4):
    """跟随跳转（最多 4 跳），返回 dict(status, hops, final, marks)。"""
    url = BASE + ('/' + path if not path.startswith('/') else path)
    hops, marks = [], []
    for _ in range(max_hops):
        try:
            r = sess.get(url, timeout=40, allow_redirects=False)
        except Exception as e:
            return dict(status='EXC', hops=hops, final=url,
                        marks=['请求异常 %s' % str(e)[:60]])
        hops.append(r.status_code)
        body = r.text or ''
        marks += [m for m in ERR_MARKS if m in body]
        if 300 <= r.status_code < 400:
            loc = r.headers.get('Location', '')
            if not loc:
                break
            if loc.startswith('http'):
                if 'localhost:8069' in loc or '127.0.0.1:8069' in loc:
                    url = loc
                else:                      # 外链（如 Zoom）：视为可达
                    return dict(status=r.status_code, hops=hops, final=loc, marks=marks)
            else:
                url = BASE + (loc if loc.startswith('/') else '/' + loc)
            continue
        return dict(status=r.status_code, hops=hops, final=url, marks=marks)
    return dict(status=hops[-1] if hops else 0, hops=hops, final=url, marks=marks)


def l1_verdict(href, res):
    """返回 (结果, 备注)。结果 ∈ PASS/FAIL/BASELINE-404。"""
    if 'error' in res or res['status'] == 'EXC':
        return 'FAIL', '请求异常'
    if res['marks']:
        return 'FAIL', '响应含 ' + '/'.join(sorted(set(res['marks'])))[:60]
    if any(isinstance(c, int) and c >= 500 for c in res['hops']):
        return 'FAIL', 'HTTP ' + '→'.join(str(c) for c in res['hops'])
    final = res['status']
    if final == 404 and href in BASELINE_MISSING:
        return 'BASELINE-404', '路由改动前就不存在（历史欠账，非本轮回归）'
    if isinstance(final, int) and final >= 400:
        return 'FAIL', 'HTTP %s%s' % ('→'.join(str(c) for c in res['hops']),
                                      ' 最终 %s' % res['final'].replace(BASE, ''))
    if final == 200:
        hop_txt = '→'.join(str(c) for c in res['hops'])
        return 'PASS', ('跳转 ' + hop_txt) if len(res['hops']) > 1 else '200'
    return 'FAIL', '最终 %s' % final


def href_in_html(href, html):
    """/my/apps 里是否出现该 href（允许相对/绝对、允许带 query/hash）。"""
    pat = re.compile(r'href=["\']/?%s(?:["\'?#])' % re.escape(href))
    return bool(pat.search(html))


def main():
    ap = argparse.ArgumentParser(description='零功能丢失：L1 可达 + L2 IA 覆盖 + 类契约')
    ap.add_argument('--role', action='append', choices=list(ROLE_ACCOUNTS),
                    help='L1 复核身份，默认 admin + student')
    ap.add_argument('--json', dest='json_out', help='结果落盘 JSON')
    args = ap.parse_args()

    l1_roles = args.role or ['admin', 'student']
    sessions = {}
    for role in set(l1_roles) | {'student'} | {r for r, _ in CLASS_CONTRACT}:
        s, err = login(role)
        if err:
            print('无法继续：角色 %s 登录失败：%s' % (role, err))
            return 2
        sessions[role] = s
    print('登录 OK：' + '，'.join(sorted(sessions)))

    all_hrefs = STALE_35_HREFS + DYNAMIC_HREFS
    results = {}
    counts = {'PASS': 0, 'FAIL': 0, 'BASELINE-404': 0}

    print('\n============ L1 路由可达（逐条 GET，期望 200 / 3xx→<400）============')
    for href in all_hrefs:
        row = {}
        for role in l1_roles:
            res = fetch(sessions[role], '/' + href)
            v, note = l1_verdict(href, res)
            row[role] = dict(verdict=v, note=note, status=res['status'],
                             hops=res['hops'], final=res['final'])
        # 主判定用第一个角色（默认 admin）
        main_v = row[l1_roles[0]]['verdict']
        if main_v != 'BASELINE-404':
            counts[main_v] = counts.get(main_v, 0) + 1
        else:
            counts['BASELINE-404'] += 1
        tag = 'HIDDEN' if href in HIDDEN_L2_EXEMPT else ('DYNAMIC' if href in DYNAMIC_HREFS else 'STALE35')
        results[href] = dict(tag=tag, l1=row)
        cells = ' '.join('%s=%s' % (r[:3], row[r]['status']) for r in l1_roles)
        print('%-6s %-5s %-34s %s  %s' % (main_v, tag, href, cells,
                                          '' if main_v == 'PASS' else row[l1_roles[0]]['note'][:60]))

    # ---------------- L2 IA 覆盖 ----------------
    print('\n============ L2 IA 覆盖（%d 张卡的 href 必须出现在 %s）============'
          % (len(STALE_35_HREFS), APPS_PATH))
    apps_html, apps_status, apps_role = '', None, None
    for role in ('student', 'admin'):
        r = sessions[role].get(BASE + APPS_PATH, timeout=40, allow_redirects=False)
        apps_status, apps_role = r.status_code, role
        if r.status_code == 200:
            apps_html = r.text
            break
    if apps_status != 200:
        print('%s 返回 %s（角色 %s）—— 页面尚未交付，L2 无法判定' % (APPS_PATH, apps_status, apps_role))
        print('L1 结果仍有效；exit 2。')
        if args.json_out:
            with open(args.json_out, 'w', encoding='utf-8') as f:
                json.dump(dict(l1=results, l2=None, apps_status=apps_status), f,
                          ensure_ascii=False, indent=1)
        return 2
    print('使用角色 %s 抓取 %s（%d bytes）' % (apps_role, APPS_PATH, len(apps_html)))

    l2_missing, l2_exempt, l2_present = [], [], []
    for href in STALE_35_HREFS:
        present = href_in_html(href, apps_html)
        results[href]['l2'] = present
        if present:
            l2_present.append(href)
        elif href in HIDDEN_L2_EXEMPT:
            l2_exempt.append(href)
        else:
            l2_missing.append(href)
    for href in STALE_35_HREFS:
        mark = 'OK ' if results[href].get('l2') else ('豁免' if href in HIDDEN_L2_EXEMPT else 'MISS')
        if not results[href].get('l2'):
            print('  %-4s %s' % (mark, href))
    print('L2：出现 %d / 豁免 %d / 缺失 %d（共 %d 张）'
          % (len(l2_present), len(l2_exempt), len(l2_missing), len(STALE_35_HREFS)))

    # ---------------- L0 共享类契约 ----------------
    print('\n============ L0 共享类契约（.%s 不得改名/删除）============' % CLASS_NAME)
    class_fail = []
    for role, path in CLASS_CONTRACT:
        r = sessions[role].get(BASE + path, timeout=40, allow_redirects=True)
        n = len(re.findall(CLASS_NAME, r.text or ''))
        okc = r.status_code == 200 and n > 0
        print('  %-4s %-16s %s %s 处' % ('OK' if okc else 'FAIL', path, r.status_code, n))
        if not okc:
            class_fail.append('%s(%s)' % (path, role))
    home_r = sessions['student'].get(BASE + '/my/home', timeout=40, allow_redirects=True)
    home_n = len(re.findall(CLASS_NAME, home_r.text or ''))
    print('  INFO %-16s %s %s 处（首页卡片数会被重构下调，仅记录不判失败；本次基线 47）'
          % ('/my/home', home_r.status_code, home_n))

    n_fail = counts['FAIL'] + len(l2_missing) + len(class_fail)
    print('\n============ 汇总 ============')
    print('L1：PASS %d / FAIL %d / BASELINE-404 %d（共 %d 条）'
          % (counts['PASS'], counts['FAIL'], counts['BASELINE-404'], len(all_hrefs)))
    print('L2：缺失 %d%s' % (len(l2_missing), (' → ' + '、'.join(l2_missing)) if l2_missing else ''))
    print('L0：类契约失败 %d%s' % (len(class_fail), (' → ' + '、'.join(class_fail)) if class_fail else ''))
    print('结论：%s' % ('全绿' if n_fail == 0 else '有 %d 项缺失' % n_fail))

    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as f:
            json.dump(dict(l1=results, l2=dict(present=l2_present, exempt=l2_exempt,
                                              missing=l2_missing),
                           class_contract_fail=class_fail, home_card_count=home_n,
                           generated=time.strftime('%Y-%m-%d %H:%M:%S')),
                      f, ensure_ascii=False, indent=1)
        print('-> %s' % args.json_out)
    return 1 if n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
