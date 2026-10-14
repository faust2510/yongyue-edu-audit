# -*- coding: utf-8 -*-
"""冒烟测试 B：学生提交（stu@local）+ 教师闭环（faculty@local）写操作级冒烟。

目标: http://localhost:8069 (Odoo 19 edu19 演示库, docker edu19-clone)
规则: 每项失败自动重试一次再判 FAIL；演示库允许造数，报告中标注「已造数」。
输出: tests/smoke/B_submit_faculty.md
"""
import re
import sys
from datetime import datetime

import requests

BASE = 'http://localhost:8069'
STU_TITLE = '冒烟测试申诉（可删）'
ASG_TITLE = '冒烟测试作业（可删）'
NOTICE_TITLE = '冒烟测试公告（可删）'


def new_session(login_name):
    s = requests.Session()
    s.trust_env = False  # 绕过系统代理直连本机
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': 'edu19', 'login': login_name,
                   'password': 'demo123'}}, timeout=20)
    assert r.status_code == 200, f'login {login_name} -> {r.status_code}'
    j = r.json()
    assert j.get('result', {}).get('uid'), f'login {login_name} failed: {j}'
    return s


def csrf_of(s, path):
    html = s.get(BASE + path, timeout=20).text
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html) or \
        re.search(r'value="([^"]+)"\s*name="csrf_token"', html)
    return m.group(1) if m else ''


def tag_attr(tag_html, name):
    """从单个标签 HTML 中取属性值（容忍 data-oe-* 等属性夹在中间）。"""
    m = re.search(r'%s="([^"]*)"' % re.escape(name), tag_html)
    return m.group(1) if m else ''


class Res:
    def __init__(self, status, actual, evidence=''):
        self.status, self.actual, self.evidence = status, actual, evidence

    def __repr__(self):
        return f'{self.status}: {self.actual}'


def attempt(fn):
    """失败自动重试一次。"""
    r = fn()
    if r.status == 'PASS':
        return r, 1
    r2 = fn()
    return (r2 if r2.status in ('PASS', 'WARN') or
            (r2.status == 'FAIL' and r.status != 'FAIL') else r2), 2


ROWS = []


def record(item, method, expect, res, tries=1):
    ROWS.append((item, method, expect, res.actual, res.status, res.evidence))
    print(f'[{res.status}] {item} ({tries}次) {res.evidence[:120]}')


# ---------------------------------------------------------------- 学生提交
STU_SLR = ''  # 第1步新建请假单号，供 T4 精确复核


def stu_time_off(stu):
    global STU_SLR
    token = csrf_of(stu, '/my/time_off')
    if not token:
        return Res('FAIL', '未取到 csrf_token')
    r = stu.post(BASE + '/my/time_off/save', data={
        'csrf_token': token, 'leave_type': 'sick',
        'date_from': '2026-09-01', 'date_to': '2026-09-02',
        'reason': '感冒发烧（冒烟测试可删）'}, timeout=20,
        allow_redirects=True)
    ok1 = 'box=submitted' in r.url or '已提交' in r.text
    h = stu.get(BASE + '/my/time_off', timeout=20).text
    m = re.search(r'SLR\d{6}', h)
    if m:
        STU_SLR = m.group(0)
    ok2 = m is not None and 'box=error' not in r.url
    ev = f'submit→{r.status_code} url含box=submitted={ok1}; 列表单号={m.group(0) if m else "无"}'
    return Res('PASS' if (ok1 and ok2) else 'FAIL',
               '提交成功且列表出现 SLR 单号' if ok1 and ok2
               else ('提交成功但未见单号' if ok1 else '提交未成功'),
               ev + ' [已造数]')


def stu_grievance(stu):
    token = csrf_of(stu, '/my/grievances')
    if not token:
        return Res('FAIL', '未取到 csrf_token')
    r = stu.post(BASE + '/my/grievances/save', data={
        'csrf_token': token, 'subject': STU_TITLE,
        'category': '图书馆 / 设施问题',
        'description': '冒烟测试自动提交'}, timeout=20,
        allow_redirects=True)
    ok1 = 'box=submitted' in r.url or '已提交' in r.text
    h = stu.get(BASE + '/my/grievances', timeout=20).text
    ok2 = STU_TITLE in h
    return Res('PASS' if ok1 and ok2 else 'FAIL',
               '提交成功且列表出现标题' if ok1 and ok2 else
               ('提交成功但列表未见标题' if ok1 else '提交未成功'),
               f'submit→{r.status_code} box=submitted={ok1} 列表含标题={ok2} [已造数]')


def _pick_second_option(s):
    page = s.get(BASE + '/course/change/request', timeout=20).text
    m = re.search(r'name="course_id"[^>]*>\s*<option[^>]*>.*?</option>\s*'
                  r'<option value="(\d+)"', page, re.S)
    return (m.group(1), page) if m else ('', page)


def stu_course_change(stu):
    course_id, page = _pick_second_option(s=stu)
    if not course_id:
        return Res('FAIL', '下拉无可选课程')
    token = csrf_of(stu, '/course/change/request')
    r = stu.post(BASE + '/course/change/request/save', data={
        'csrf_token': token, 'course_id': course_id},
        timeout=20, allow_redirects=True)
    ok1 = 'box=submitted' in r.url or '已提交' in r.text
    h = stu.get(BASE + '/course/change/request', timeout=20).text
    sr = re.search(r'SR\d{4}', h)
    ok2 = (sr is not None or '已提交' in h)
    return Res('PASS' if ok1 and ok2 else 'FAIL',
               '提交成功且回显 SR 单号/已提交' if ok1 and ok2 else
               ('提交成功但未见回显' if ok1 else '提交未成功'),
               f'course_id={course_id} submit→{r.status_code} '
               f'box=submitted={ok1} 回显SR={sr.group(0) if sr else "无"} [已造数]')


# ---------------------------------------------------------------- 教师闭环
def pending_leave_ids(fac):
    h = fac.get(BASE + '/leave/approvals', timeout=20).text
    ids = []
    for f in re.findall(r'<form[^>]*action="/leave/set_state"[^>]*>.*?</form>',
                        h, re.S):
        m = re.search(r'name="leave_id"[^>]*value="(\d+)"', f)
        if m:
            ids.append(int(m.group(1)))
    return sorted(set(ids), reverse=True), h


def fac_approvals(fac, stu, before_ids):
    now_ids, h = pending_leave_ids(fac)
    if not now_ids:
        return Res('WARN', '审批页无待审单', f'待审id列表为空(此前快照={before_ids})')
    target = None
    for i in now_ids:
        if i not in before_ids:
            target = i  # 优先批准第1步新造的请假单
            break
    src = '新提交SLR' if target else '既有待审单(最大id)'
    lid = target or now_ids[0]
    token = csrf_of(fac, '/leave/approvals')
    r = fac.post(BASE + '/leave/set_state', data={
        'csrf_token': token, 'leave_id': str(lid),
        'state': 'approved'}, timeout=20, allow_redirects=True)
    after_ids, _h2 = pending_leave_ids(fac)
    gone = lid not in after_ids
    hs = stu.get(BASE + '/my/time_off', timeout=20).text
    # 精确复核：在本run新建的 SLR 单所在行附近找最近的状态标签
    near = ''
    if STU_SLR:
        i = hs.find(STU_SLR)
        if i >= 0:
            win = hs[max(0, i - 300):i + 900]
            labs = [(win.find(t), t) for t in ('已批准', '已拒绝', '已申请')
                    if win.find(t) >= 0]
            near = min(labs)[1] if labs else ''
    stu_ok = (near == '已批准') if STU_SLR else '已批准' in hs
    ok = (r.status_code == 200 and gone and stu_ok)
    return Res('PASS' if ok else ('WARN' if r.status_code == 200 else 'FAIL'),
               '状态变为已批准且移出待审' if ok else
               ('POST成功但复核证据不足' if r.status_code == 200 else
                f'set_state→{r.status_code}'),
               f'目标leave_id={lid}({src}) 复核: 移出待审={gone} '
               f'学生页[{STU_SLR or "未捕获单号"}]最近状态标签={near or "无"} '
               f'[已造数:改状态]')


def fac_attendance(fac):
    r = fac.get(BASE + '/attendance/take',
                params={'course_id': 6}, timeout=20)
    if r.status_code != 200:
        return Res('FAIL', f'/attendance/take?course_id=6 → {r.status_code}',
                   f'HTTP {r.status_code}')
    h = r.text
    # 班级来自下拉（优先 selected，否则第一个）
    mb = re.search(r'name="batch_id"[^>]*>(.*?)</select>', h, re.S)
    batch = ''
    if mb:
        ms = re.search(r'<option value="(\d+)"[^>]*selected', mb.group(1)) or \
            re.search(r'<option value="(\d+)"', mb.group(1))
        batch = ms.group(1) if ms else ''
    md = re.search(r'name="date"[^>]*value="([\d-]+)"', h)
    date = md.group(1) if md else datetime.now().strftime('%Y-%m-%d')
    if not batch:
        return Res('FAIL', '无班级可选', 'batch 下拉为空')
    # 选定班级后取点名表
    h2 = fac.get(BASE + '/attendance/take',
                 params={'course_id': 6, 'batch_id': batch, 'date': date},
                 timeout=20).text
    mf = re.search(r'<form[^>]*action="/attendance/save"[^>]*>(.*?)</form>',
                   h2, re.S)
    if not mf:
        return Res('FAIL', '未渲染点名表(/attendance/save 表单缺失)',
                   f'batch={batch} date={date} 页面无 save 表单')
    body = mf.group(1)
    token_m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body)
    token = token_m.group(1) if token_m else ''
    hid = {}
    for tag in re.findall(r'<input\b[^>]*type="hidden"[^>]*>', body):
        nm, vl = tag_attr(tag, 'name'), tag_attr(tag, 'value')
        if nm and nm != 'csrf_token':
            hid[nm] = vl
    students = sorted(set(re.findall(r'name="(status_\d+)"', body)))
    if not (token and hid.get('batch_id') and hid.get('course_id')):
        return Res('FAIL', '表单字段不全', f'token={bool(token)} hidden={hid}')
    data = {'csrf_token': token, **hid, 'date': date}
    for st in students:
        data[st] = 'present'
    r2 = fac.post(BASE + '/attendance/save', data=data, timeout=20,
                  allow_redirects=True)
    ok_main = (r2.status_code == 200 and 'saved=1' in r2.url)
    # 非法参数: 存在班级/课程不存在 → 应 error=1 而非白屏
    bad = fac.post(BASE + '/attendance/save',
                   data={'csrf_token': token, 'batch_id': '999999',
                         'course_id': '999999', 'date': date},
                   timeout=20, allow_redirects=True)
    ok_bad = (bad.status_code < 500 and len(bad.text) > 100 and
              ('error=1' in bad.url or '考勤' in bad.text))
    if ok_main and ok_bad:
        st_, act = 'PASS', f'合法保存 saved=1; 非法参数跳转 error=1'
    elif ok_main:
        st_, act = 'WARN', '合法保存成功，非法参数表现异常'
    elif ok_bad:
        st_, act = 'FAIL', '合法保存失败'
    else:
        st_, act = 'FAIL', '合法与非法均失败'
    ev = (f'batch={hid.get("batch_id")} course={hid.get("course_id")} '
          f'date={date} 学生行={len(students)} 合法→{r2.status_code} '
          f'url含saved=1={ok_main}; 非法→{bad.status_code} '
          f'url={bad.url.split("?")[-1][:40]} [已造数:考勤表]')
    return Res(st_, act, ev)


def fac_grading(fac):
    h = fac.get(BASE + '/grading/entry', timeout=20).text
    me = re.search(r'name="exam_id".*?<option value="(\d+)"', h, re.S)
    if not me:
        return Res('WARN', '无现有考试可选', 'exam 下拉为空 → 缺「现有考试」')
    exam_id = me.group(1)
    h2 = fac.get(BASE + '/grading/entry', params={'exam_id': exam_id},
                 timeout=20).text
    mf = re.search(r'<form[^>]*action="/grading/save"[^>]*>(.*?)</form>',
                   h2, re.S)
    if not mf:
        return Res('WARN', '选定考试后无录入表单', f'exam_id={exam_id}')
    body = mf.group(1)
    token_m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body)
    token = token_m.group(1) if token_m else ''
    mm = re.search(r'name="marks_(\d+)"[^>]*value="([\d.]*)"', body)
    if not (token and mm):
        return Res('WARN', '无现有考生行(marks_*)可录',
                   f'exam_id={exam_id} 表单缺 marks_* 输入')
    att_id, cur = mm.group(1), mm.group(2)
    ms = re.search(r'name="st_%s"[^>]*>(.*?)</select>' % att_id, body, re.S)
    st_val = 'present'
    if ms and '<option value=' in ms.group(1):
        st_val = re.search(r'<option value="(\w+)"', ms.group(1)).group(1)
    write_val = cur if cur.isdigit() else '60'
    r = fac.post(BASE + '/grading/save', data={
        'csrf_token': token, 'exam_id': exam_id,
        f'marks_{att_id}': write_val, f'st_{att_id}': st_val},
        timeout=20, allow_redirects=True)
    saved_ok = 'saved=1' in r.url and 'scount=1' in r.url
    h3 = fac.get(BASE + '/grading/entry', params={'exam_id': exam_id},
                 timeout=20).text
    echo = f'value="{write_val}"' in h3 or f'>{write_val}</input>' in h3 or \
        re.search(r'name="marks_%s"[^>]*value="%s"' % (att_id, write_val), h3)
    if saved_ok and echo:
        return Res('PASS', '成绩保存并回显',
                   f'exam_id={exam_id} attendee={att_id} 原值回写={write_val} '
                   f'(不改演示数据) redirect含saved=1&scount=1={saved_ok} '
                   f'回显={bool(echo)} [已造数:原值写入]')
    return Res('WARN' if saved_ok else 'FAIL',
               '保存成功但回显未确认' if saved_ok else '保存失败',
               f'redirect={r.url.split("?")[-1][:50]} 回显={bool(echo)}')


def _first_select(body, name):
    m = re.search(r'name="%s"[^>]*>(.*?)</select>' % name, body, re.S)
    if not m:
        return ''
    sel = re.search(r'<option value="(\d+)"[^>]*selected', m.group(1))
    if sel:
        return sel.group(1)
    any_opt = re.search(r'<option value="(\d+)"', m.group(1))
    return any_opt.group(1) if any_opt else ''


def fac_assignment(fac, stu):
    h = fac.get(BASE + '/assignment/publish', timeout=20).text
    mf = re.search(r'<form[^>]*action="/assignment/publish_save"[^>]*>'
                   r'(.*?)</form>', h, re.S)
    if not mf:
        return Res('FAIL', '发布作业表单缺失')
    body = mf.group(1)
    token_m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body)
    token = token_m.group(1) if token_m else ''
    subject = _first_select(body, 'subject_id')
    type_id = _first_select(body, 'type_id') or '1'
    batch = _first_select(body, 'batch_id')
    # 学生详情页按其本人 course+batch 过滤；course 取考勤页与该班级
    # 实际配对渲染的课程 id（而非全量下拉的第一个）
    course = ''
    if batch:
        ha = fac.get(BASE + '/attendance/take',
                     params={'course_id': 6, 'batch_id': batch,
                             'date': '2026-08-23'}, timeout=20).text
        mc = re.search(r'name="course_id"[^>]*value="(\d+)"', ha)
        course = mc.group(1) if mc else ''
    if not course:
        course = _first_select(body, 'course_id')
    r = fac.post(BASE + '/assignment/publish_save', data={
        'csrf_token': token, 'name': ASG_TITLE, 'marks': '100',
        # 模型字段为 required Datetime，用服务端规范格式
        'issued_date': '2026-08-23 08:00:00',
        'submission_date': '2026-09-15 23:59:59',
        'description': '冒烟测试自动发布，可删除。',
        'subject_id': subject, 'type_id': type_id,
        'course_id': course, 'batch_id': batch},
        timeout=25, allow_redirects=False)
    loc = r.headers.get('Location', '')
    created = r.status_code in (302, 303) and \
        loc.startswith('/student/assignment/details')
    cross = False
    detail = ''
    if created:
        rd = stu.get(BASE + '/student/assignment/details', timeout=20)
        cross = rd.status_code == 200 and ASG_TITLE in rd.text
        detail = f'学生端详情页→{rd.status_code} 含标题={cross}'
    if created:
        st_ = 'PASS' if cross else 'WARN'
        act = '创建成功' + ('，学生端可见' if cross else '，学生端交叉验证未确认')
    else:
        st_, act = 'FAIL', f'publish_save→{r.status_code}'
    ev = (f'subject={subject} type={type_id} course={course} batch={batch} '
          f'POST→{r.status_code} Location={loc[:45]} {detail} [已造数]')
    return Res(st_, act, ev)


def fac_notice(fac, stu):
    token = csrf_of(fac, '/notice/publish')
    if not token:
        return Res('FAIL', '公告表单/csrf 缺失')
    r = fac.post(BASE + '/notice/publish_save', data={
        'csrf_token': token, 'name': NOTICE_TITLE,
        'content': '冒烟测试自动发布，可删除。'},
        timeout=20, allow_redirects=True)
    ok_fac = (r.status_code == 200 and
              r.url.endswith('/my/notice_board/notice'))
    hs = stu.get(BASE + '/my/notice_board/notice', timeout=20)
    cross = hs.status_code == 200 and NOTICE_TITLE in hs.text
    if ok_fac and cross:
        st_, act = 'PASS', '公告创建成功且学生布告栏可见'
    elif ok_fac:
        st_, act = 'WARN', '教师端创建成功，学生端未见'
    else:
        st_, act = 'FAIL', f'publish_save→{r.status_code}'
    return Res(st_, act, f'教师跳转布告栏={ok_fac} '
                         f'学生端含标题={cross} [已造数]')


def fac_apps_menu(fac):
    r = fac.get(BASE + '/openeducat/apps_menu', timeout=25)
    n = len(re.findall(r'class="o_app[" ]', r.text))
    ok = r.status_code == 200 and n >= 5
    return Res('PASS' if ok else 'FAIL',
               f'200 且 o_app 卡片 {n} 张' if ok
               else f'code={r.status_code} o_app={n}',
               f'o_app计数={n}')


def main():
    print('== 登录...')
    stu = new_session('stu@local')
    fac = new_session('faculty@local')

    before_ids, _ = pending_leave_ids(fac)
    print('审批前待审 leave ids:', before_ids)

    res, t = attempt(lambda: stu_time_off(stu))
    record('S1 学生请假提交', 'POST /my/time_off/save',
           'URL含box=submitted；GET /my/time_off 出现 SLR\\d{6}', res, t)

    res, t = attempt(lambda: stu_grievance(stu))
    record('S2 学生申诉提交', 'POST /my/grievances/save',
           '成功标志同上；GET /my/grievances 出现标题', res, t)

    res, t = attempt(lambda: stu_course_change(stu))
    record('S3 学生换课申请', 'POST /course/change/request/save',
           '成功标志同上；页面回显 SR\\d{4} 或「已提交」', res, t)

    res, t = attempt(lambda: fac_approvals(fac, stu, before_ids))
    record('T4 教师请假审批', 'POST /leave/set_state(state=approved)',
           '渲染审批列表；批准后状态变化、移出待审', res, t)

    res, t = attempt(lambda: fac_attendance(fac))
    record('T5 教师考勤点名', 'POST /attendance/save (+非法参数对照)',
           '非5xx、redirect含saved=1；非法参数 error=1 非白屏', res, t)

    res, t = attempt(lambda: fac_grading(fac))
    record('T6 教师成绩录入', 'POST /grading/save',
           'redirect saved=1&scount≥1 且分数回显', res, t)

    res, t = attempt(lambda: fac_assignment(fac, stu))
    record('T7 教师发布作业', 'POST /assignment/publish_save',
           '302→/student/assignment/details；学生端出现该作业', res, t)

    res, t = attempt(lambda: fac_notice(fac, stu))
    record('T8 教师发布公告', 'POST /notice/publish_save',
           '跳转布告栏；学生会话 /my/notice_board/notice 出现公告', res, t)

    res, t = attempt(lambda: fac_apps_menu(fac))
    record('T9 应用菜单', 'GET /openeducat/apps_menu',
           '200 且 HTML 含 class="o_app" 卡片若干', res, t)

    # ---- 报告 ----
    n_pass = sum(1 for r in ROWS if r[4] == 'PASS')
    n_warn = sum(1 for r in ROWS if r[4] == 'WARN')
    n_fail = sum(1 for r in ROWS if r[4] == 'FAIL')
    total = len(ROWS)
    lines = [
        '# 冒烟测试 B：学生提交 + 教师闭环（写操作级）',
        '',
        '- 目标: `http://localhost:8069`（Odoo 19 学校系统复刻，docker '
        '`edu19-clone`，库 `edu19`，演示库允许造数）',
        '- 账号: `stu@local`（学生）/ `faculty@local`（教师，内部用户）',
        '- 方法: `requests.Session` + `/web/session/authenticate`，CSRF 从表单页'
        '正则提取（范式 `scripts/test_submit_flows.py`）；每项失败重试一次。',
        '- 执行时间: %s　|　脚本: `scripts/smoke_b_submit_faculty.py`' %
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '- 说明: 所有写操作均为**已造数**（演示数据，标题带「可删」）；T6 成绩为'
        '**原值回写**以避免污染演示分数。',
        '',
        '| 项目 | 方法 | 预期 | 实际 | 结果(PASS/WARN/FAIL) | 证据/备注 |',
        '|---|---|---|---|---|---|',
    ]
    for item, method, expect, actual, st, ev in ROWS:
        lines.append(f'| {item} | {method} | {expect} | {actual} | {st} | '
                     f'{ev} |')
    lines += ['', f'**统计: PASS {n_pass}/{total}（WARN {n_warn}，'
                  f'FAIL {n_fail}）**', '']
    out = 'tests/smoke/B_submit_faculty.md'
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n报告已写入 {out}')
    print(f'OVERALL: PASS {n_pass}/{total} WARN={n_warn} FAIL={n_fail}')
    return 0 if n_fail == 0 else 2


if __name__ == '__main__':
    raise SystemExit(main())
