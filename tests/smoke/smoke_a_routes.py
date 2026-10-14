#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冒烟测试 A（学生角色）— edu19-clone @ http://localhost:8069，只读。
判定：HTTP 200、无 Traceback / Internal Server Error、包含预期标记之一；
失败先原样重试一次再判 FAIL。结果写入 tests/smoke/A_student.md
"""
import json, re, time
from urllib.parse import urlparse
import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
USER = 'stu@local'
PW = 'demo123'
OUT_MD = 'tests/smoke/A_student.md'
OUT_JSON = 'tests/smoke/A_student_raw.json'

TAG = re.compile(r'<[^>]+>')
WS = re.compile(r'\s+')
PAGER_PAT = re.compile(r'(pagination|pager|/page/|[?&]page=\d|下一页|上一页|fa-chevron|&laquo;|&raquo;|o_portal)', re.I)
EMPTY_HINTS = ['暂无', '没有找到', '无数据', '无记录', 'No record', 'no data',
               'not available', '尚未', '还没有', '为空', '没有']
LOGIN_HINT = re.compile(r'(/web/login|name="login"|登录|Log in)', re.I)


def visible(t):
    return WS.sub(' ', TAG.sub(' ', t)).strip()


def make_session():
    s = requests.Session()
    s.trust_env = False  # 本机代理环境变量会劫持 localhost，必须绕过
    s.headers.update({'User-Agent': 'smoke-a/1.0 (read-only smoke test)'})
    return s


def auth():
    s = make_session()
    r = s.post(f'{BASE}/web/session/authenticate',
               json={'jsonrpc': '2.0',
                     'params': {'db': DB, 'login': USER, 'password': PW}},
               timeout=15)
    try:
        uid = r.json().get('result', {}).get('uid')
    except Exception:
        uid = None
    return s, r, uid


ROUTES = [
    dict(path='/my/home', markers=['出勤趋势', '快速操作']),
    dict(path='/my', special='home_alias'),
    dict(path='/my/notice_board/notice', markers=['布告', '通知']),
    dict(path='/student/timetable', markers=['时间表']),
    dict(path='/student/attendance', markers=['考勤']),
    dict(path='/student/attendance?page=2', markers=['考勤'], need_pagination=True),
    dict(path='/student/profile', markers=['王小明', '档案', '个人资料']),
    dict(path='/student/exam', markers=['考试']),
    dict(path='/student/assignment/details', markers=['作业']),
    dict(path='/grade-book', markers=['成绩']),
    dict(path='/library/media', markers=['图书', '媒体']),
    dict(path='/library/media?page=2', markers=['图书', '媒体'], need_pagination=True),
    dict(path='/subject/details', markers=['科目', '课程详情']),
    dict(path='/subject/registration', markers=['选课', '注册']),
    dict(path='/my-library', markers=['借阅', '我的图书馆']),
    dict(path='/certificate', special='render_only', kw=['证书']),
    dict(path='/meeting/information', markers=['会议']),
    dict(path='/online/meeting', markers=['会议', '课堂']),
    dict(path='/my/academic-calendar', markers=['校历', '学年']),
    dict(path='/my/asset-request', markers=['资产']),
    dict(path='/my/dms', markers=['文档']),
    dict(path='/my/thesis', markers=['论文']),
    dict(path='/users/result-overview', markers=['成绩总览', '结果']),
    dict(path='/requested/queue/list', markers=['队列', '请求', '审批']),
    dict(path='/openeducat-omr/student/exam', markers=['OMR', '答题卡', '考试']),
    dict(path='/openeducat-omr/exam-result', special='render_only', kw=['成绩', '结果', '考试']),
]


def fetch(s, path):
    t0 = time.time()
    try:
        r = s.get(BASE + path, timeout=20, allow_redirects=True)
    except Exception as e:
        return dict(error=f'{type(e).__name__}: {e}', ms=int((time.time() - t0) * 1000))
    text = r.text or ''
    final_path = urlparse(r.url).path
    hits = []
    spec = next(x for x in ROUTES if x['path'] == path)
    markers = spec.get('markers') or []
    if spec.get('special') == 'home_alias':
        markers = ['出勤趋势', '快速操作']
    for m in markers:
        if m in text:
            hits.append(m)
    vis = visible(text)
    return dict(
        status=r.status_code,
        history=[f"{h.status_code}->{urlparse(h.headers.get('Location', '')).path}" for h in r.history],
        final_path=final_path,
        final_url=r.url,
        len=len(text),
        title=(re.search(r'<title[^>]*>(.*?)</title>', text, re.S | re.I).group(1).strip()
               if re.search(r'<title[^>]*>(.*?)</title>', text, re.S | re.I) else ''),
        marker_hits=hits,
        has_tb='Traceback' in text,
        has_ise='Internal Server Error' in text,
        login_redirect=bool(LOGIN_HINT.search(final_path) or final_path.endswith('/web/login')),
        has_pagination=bool(PAGER_PAT.search(text)),
        has_table='<table' in text.lower(),
        empty_hits=[h for h in EMPTY_HINTS if h in vis],
        kw_hits=[k for k in spec.get('kw', []) if k in vis],
        snippet=vis[:400],
        ms=int((time.time() - t0) * 1000),
    )


def attempt(s, path):
    """最多两次（原样重试一次），返回 (res, retried)。"""
    res = fetch(s, path)
    if 'error' in res or not base_ok(res) or not criteria_ok(res):
        res2 = fetch(s, path)
        return res2, True
    return res, False


def base_ok(res):
    if 'error' in res:
        return False
    return (res['status'] == 200 and not res['has_tb'] and not res['has_ise']
            and not res['login_redirect'])


def criteria_ok(res):
    """除基础判定外，路由自身标记/特殊要求是否满足。"""
    return bool(res['marker_hits']) or bool(res['kw_hits']) or (
        not res['marker_hits'] and res.get('_render_only'))


def judge(path, spec, res):
    """返回 (结果, 备注)。"""
    if 'error' in res:
        return 'FAIL', f'请求异常: {res["error"]}'
    note_bits = []
    if res['history']:
        note_bits.append('redirect: ' + ' '.join(res['history']))
    if res['login_redirect'] or res['final_path'].endswith('/web/login'):
        return 'FAIL', '被重定向到登录页(权限/会话失效) ' + '; '.join(note_bits)
    if res['status'] != 200:
        return 'FAIL', f'HTTP {res["status"]}' + ('; ' + '; '.join(note_bits) if note_bits else '')
    if res['has_tb'] or res['has_ise']:
        return 'FAIL', '响应含 Traceback/Internal Server Error'
    special = spec.get('special')
    if special == 'home_alias':
        if res['final_path'] == '/my/home' or res['marker_hits']:
            return 'PASS', ('跳转至 ' + res['final_path'] if res['history'] else '直接渲染等同 /my/home')
        return 'FAIL', f'未跳转到 /my/home，落在 {res["final_path"]}，标记未命中'
    if special == 'render_only':
        if res['kw_hits']:
            return 'PASS', '页面正常渲染，含关键词: ' + '/'.join(res['kw_hits'])
        return 'WARN', '页面正常渲染但疑似空数据(未见关键词 %s)%s' % (
            '/'.join(spec['kw']), ('；空态字样: ' + '/'.join(res['empty_hits'][:3])) if res['empty_hits'] else '')
    if res['marker_hits']:
        note_bits.append('命中: ' + '/'.join(res['marker_hits']))
        if spec.get('need_pagination'):
            if res['has_pagination']:
                note_bits.append('分页元素: 有')
                return 'PASS', '; '.join(note_bits)
            return 'WARN', '页面正常但未检出分页元素(可能数据不足一页)'
        extra = []
        if res['has_table']:
            extra.append('含表格')
        if res['empty_hits']:
            extra.append('空态字样: ' + '/'.join(res['empty_hits'][:3]))
        if extra:
            note_bits.append('; '.join(extra))
        return 'PASS', '; '.join(note_bits)
    # 200 且无报错但标记未命中
    if res['has_table'] or res['len'] > 5000:
        return 'WARN', f'页面正常渲染(含表格/内容 {res["len"]}B)但未见标记串; title={res["title"][:60]}'
    return 'FAIL', f'标记未命中且内容可疑; title={res["title"][:60]}'


def main():
    s, r, uid = auth()
    if not uid:
        print('AUTH FAILED', r.status_code, r.text[:300])
        return 1
    print(f'auth ok uid={uid}')
    rows, raw = [], []
    for spec in ROUTES:
        path = spec['path']
        res, retried = attempt(s, path)
        verdict, note = judge(path, spec, res)
        if retried:
            note = (note + '；[重试后]').strip('；')
        http_disp = str(res.get('status', 'ERR'))
        if res.get('history'):
            http_disp += ' (' + '→'.join(h.split('->')[0] for h in res['history']) + '→' + http_disp + ')'
        hits_disp = '/'.join(res.get('marker_hits', []) + res.get('kw_hits', [])) or '-'
        rows.append(dict(path=path, http=http_disp, hits=hits_disp, verdict=verdict, note=note))
        raw.append(dict(path=path, spec_markers=spec.get('markers'), res=res, verdict=verdict, note=note))
        print(f'{verdict:4} {path} http={http_disp} hits={hits_disp}')

    n_pass = sum(1 for x in rows if x['verdict'] == 'PASS')
    n_warn = sum(1 for x in rows if x['verdict'] == 'WARN')
    n_fail = sum(1 for x in rows if x['verdict'] == 'FAIL')
    total = len(rows)
    lines = [
        '# 冒烟测试 A — 学生角色（stu@local）',
        '',
        '- 目标: edu19-clone @ http://localhost:8069（db=edu19），只读 GET',
        '- 判定: HTTP 200、无 Traceback / Internal Server Error、含预期标记之一；失败原样重试一次',
        '- 时间: ' + time.strftime('%Y-%m-%d %H:%M:%S'),
        '',
        '| 路由 | HTTP | 标记命中 | 结果(PASS/WARN/FAIL) | 备注 |',
        '|---|---|---|---|---|',
    ]
    for x in rows:
        lines.append(f'| `{x["path"]}` | {x["http"]} | {x["hits"]} | {x["verdict"]} | {x["note"]} |')
    lines += ['', f'**统计: {n_pass}/{total} PASS，{n_warn} WARN，{n_fail} FAIL**', '']
    with open(OUT_MD, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(raw, f, ensure_ascii=False, indent=1)
    print(f'\nwrote {OUT_MD}: {n_pass}/{total} PASS, {n_warn} WARN, {n_fail} FAIL')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
