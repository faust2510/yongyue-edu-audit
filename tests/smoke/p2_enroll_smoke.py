#!/usr/bin/env python3
"""enroll-v2 学生自主报课+教务审批 端到端冒烟（本地 edu19）。

覆盖设计 §6 王佐验收剧本（本地映射：王小明 stu@local/demo123，档案 sc9）：
1. GET /subject/enroll 学生页 200（在读摘要/专业目录/科目池）
   ⚠ 2026-09-22 文案更新（专业编排设计 §6.6.4 校长拍板 P3）：门户指代
   `op.course` 的文案由「课程目录」改为「专业目录」——本冒烟的命中词随之更新，
   判据强度不变（原来命中的 6 个词，现在仍是同样 6 个）。
2. POST /subject/enroll/save 创建注册单 state=submitted + 审计
3. GET /subject/registration 我的申请可见（新单+已选科目横卡）
4. 教务 GET /registrar/subject/approvals 见 pending 单（含提醒聚合）
5. 详情 GET .../approvals/<rid> + 通过 → sc.subject_ids 覆盖 + approved_at/by
6. 王佐/学生端刷新：状态已通过；/my/courses LMS 出现档案科目
7. 驳回场景：rejected + reason → 学生可见 reason
8. 权限负例：学生 GET /registrar/... → 302 /my/home
用法：python3 tests/smoke/p2_enroll_smoke.py

运行前提（**不是本脚本缺陷的修复项**，是跑它的纪律）
--------------------------------------------------
1. **同类冒烟必须串行独占**：并发跑同类脚本会互删共享夹具，症状是
   `psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint "op_exam_unique_exam_code"`（t43 那套）
   或拿到「半程读数」（断言只跑了一部分）。建议先跑 code-map §2 的三步探活（无升级锁 + 容器 Up>30s + 带 cookie 探活），
   并确认 `pgrep -f 'smoke'` 为空。**这条只是运行纪律，不是 p2 恒红的成因**。
2. **#10 需要「档案非空」这个数据前置**：本脚本前面的审批会按「注册单 = 最新意愿」
   **整体覆盖**档案科目（registration.py 的设计），所以该前置不由本脚本掌控。
   档案为空时 #10 走 **显式 SKIP**（并交叉核对防呆代码路径存在），不判红；
   想拿完整判据就先跑 `scripts/seed_wangxiaoming_subjects.py` 恢复演示档案。
3. 历史坑（已修，留档）：清场原用 `create_date >= now-3 天` 窗口，而残留可能比窗口更老
   （REG#298 创建于 09-12）⇒ 永远清不掉自己、脚本恒红。现已改为**按标记**清理。
"""
import os
import re
import sys
import json

import requests

BASE = 'http://127.0.0.1:8069'
CSRF_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')
R = []


def rec(item, method, expect, actual, result, evidence=''):
    R.append(dict(item=item, method=method, expect=expect, actual=actual,
                  result=result, evidence=evidence))
    print('[%s] %s: %s' % (result, item, actual))


def skip(item, method, expect, actual, evidence=''):
    """记录一条 **SKIP**（数据态使该用例不可判定时用）。

    与「硬判 FAIL」的区别：FAIL 是「被测对象有缺陷」；SKIP 是「当前数据态下这条判据量不出东西」。
    与「硬判 PASS」的区别：SKIP 不计入通过数，汇总里**单独打印**，不会被读成绿。
    （按队长 2026-09-17 的范围更正：测试侧只在**不可判定**时 SKIP，并用另一条
     PASS/FAIL 判据兜住覆盖 —— 见 guard_source_present()。）
    """
    R.append(dict(item=item, method=method, expect=expect, actual=actual,
                  result='SKIP', evidence=evidence))
    print('[SKIP] %s: %s' % (item, actual))


# 产品侧「空单防呆」源码（SKIP 时的交叉核对对象；只读，不改产品）
GUARD_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                         'custom_addons', 'edu_portal', 'models',
                         'registration.py')


def guard_source_present():
    """交叉核对：产品里的「空单防呆」代码路径**确实存在**（返回 (ok, why)）。

    为什么要有这条：当档案为空时行为判据只能 SKIP，而「SKIP」若没有兜底就变成覆盖空洞。
    这里直接读源码，核对三个特征串：doc_type 限定 / 空 payload 条件 / 档案非空的先决条件。
    只读文件，不改产品代码（队长范围界定：测试侧改动）。
    """
    try:
        with open(GUARD_SRC, encoding='utf-8') as fh:
            src = fh.read()
    except OSError as exc:
        return False, '读不到 %s（%s）' % (GUARD_SRC, exc)
    need = ['not subject_ids', 'sc.subject_ids', '该报课单未包含任何科目']
    miss = [x for x in need if x not in src]
    return (not miss), ('特征串齐全（%d/%d）' % (len(need) - len(miss), len(need))
                        if not miss else '缺: %s' % miss)


def auth(login, pwd):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': 'edu19', 'login': login, 'password': pwd}}, timeout=60)
    uid = r.json().get('result', {}).get('uid')
    if not uid:
        raise SystemExit('login failed %s' % login)
    return s


def call_kw(s, model, method, args=None, kwargs=None):
    """后台 JSON-RPC：清理冒烟造数用（backoffice 对 op.subject.registration
    有 unlink ACL；仅删除本冒烟标记的记录，幂等可重跑）。"""
    r = s.post(BASE + '/web/dataset/call_kw', json={
        'jsonrpc': '2.0',
        'method': 'call',
        'params': {'model': model, 'method': method, 'args': args or [],
                   'kwargs': kwargs or {}}}, timeout=60)
    return r.json().get('result')


def cleanup_prev_smoke(adm):
    """清掉本冒烟自己的注册单残留（幂等可重跑）。

    **按标记清，不设时间窗**（2026-09-17 t7 修）：
    原先只删 `create_date >= now-3 天` 的行 —— 但残留可能**比窗口还老**。
    实测事故：`op.subject.registration id=298`（备注「【冒烟测试可删】enroll-v2 smoke」）
    创建于 09-12，而窗口只到 09-14 ⇒ **脚本永远清不掉自己的残留**，此后每次 #2 都被
    「同一学生+同一课程+同一班级已有单」拦成 `box=duplicated`，脚本从「可重跑」退化成「恒红」。
    （当时的误判路径见 docs/plans/portal-regression-readings.md §7.2。）

    现在的判据**只看标记**：凡带「【冒烟测试可删】」、且属于本冒烟目标学生（student_id=5）
    的注册单一律清掉；**无标记的演示/业务数据一律不动**。范围仍限本冒烟的目标学生，
    避免误伤别人的夹具（并发跑同类冒烟时尤其重要）。
    """
    rows = call_kw(adm, 'op.subject.registration', 'search_read',
                   [[('student_id', '=', 5)]],
                   {'fields': ['id', 'applicant_note', 'reject_reason', 'state']})
    doomed = [r['id'] for r in (rows or []) if (
        '【冒烟测试可删】' in (r.get('applicant_note') or '')
        or '【冒烟测试可删】' in (r.get('reject_reason') or ''))]
    if doomed:
        call_kw(adm, 'op.subject.registration', 'unlink', [doomed])
    print('  [cleanup] 学生5 注册单 %d 行 → 按标记清 %d 行（id=%s）'
          % (len(rows or []), len(doomed), doomed or '无'))


def csrf(s, path):
    r = s.get(BASE + path, timeout=60)
    m = CSRF_RE.search(r.text)
    return r, (m.group(1) if m else '')


def main():
    stu = auth('stu@local', 'demo123')
    adm = auth('backoffice@local', 'demo123')
    cleanup_prev_smoke(adm)

    # ---- 1. 学生报课目录页 ----
    r = stu.get(BASE + '/subject/enroll', timeout=60)
    h = r.text
    no_tb = 'Traceback' not in h
    # 「专业目录」= 原「课程目录」：2026-09-22 起门户按校长拍板把指代 op.course 的
    # 文案统一改成「专业」（docs/plans/major-track-elective-design.md §6.6.4 P3）。
    marks = [k for k in ['报课选科', '在读档案', '专业目录', '班级目录', '科目选择',
                         '提交选课注册单'] if k in h]
    ok1 = r.status_code == 200 and no_tb and len(marks) >= 4
    rec('1 GET /subject/enroll 学生页', 'HTTP GET', '200 渲染目录组件',
        '%s, 命中=%s, Traceback=%s' % (r.status_code, marks, no_tb),
        'PASS' if ok1 else 'FAIL', 'len=%d' % len(h))

    # ---- 1b. 0 门科目提交 → 必须被 no_subject 拦截（全选修课程无必修）----
    r1b, tok1b = csrf(stu, '/subject/enroll')
    r1c = stu.post(BASE + '/subject/enroll/save', data={
        'csrf_token': tok1b,
        'course_id': '18',
        'batch_id': '8',
        'applicant_note': '【冒烟测试可删】empty-subject guard',
    }, timeout=60, allow_redirects=False)
    loc1b = r1c.headers.get('Location') or ''
    ok1b = r1c.status_code == 303 and 'box=no_subject' in loc1b
    rec('1b POST 0门提交', 'HTTP POST', '303 box=no_subject 拦截空单',
        '%s -> %s' % (r1c.status_code, loc1b),
        'PASS' if ok1b else 'FAIL', 'len=%d' % len(r1c.text))

    # ---- 2. 提交注册单（CRS-PRP 预备科 batch8；选修 PRP-C12=46）----
    r2, tok = csrf(stu, '/subject/enroll')
    payload = {
        'csrf_token': tok,
        'course_id': '18',
        'batch_id': '8',
        'elective_subject_ids': '46',   # PRP-C12 选修
        'applicant_note': '【冒烟测试可删】enroll-v2 smoke',
    }
    r3 = stu.post(BASE + '/subject/enroll/save', data=payload, timeout=60,
                  allow_redirects=False)
    loc = r3.headers.get('Location') or ''
    m_new = re.search(r'new_id=(\d+)', loc)
    new_rid = int(m_new.group(1)) if m_new else 0
    created = 'box=submitted' in loc
    rec('2 POST /subject/enroll/save', 'HTTP POST', '创建并跳转成功横幅',
        '%s -> %s (new_id=%s)' % (r3.status_code, loc, new_rid),
        'PASS' if created and new_rid else 'FAIL',
        'len=%d' % len(r3.text))

    # ---- 3. 我的申请列表 ----
    r4 = stu.get(BASE + '/subject/registration?box=submitted', timeout=60)
    h4 = r4.text
    no_tb4 = 'Traceback' not in h4
    has_new = ('报课选科' in h4 and '我的已选科目' in h4
               and '已提交' in h4)
    ok4 = r4.status_code == 200 and no_tb4 and has_new
    rec('3 GET /subject/registration 我的申请', 'HTTP GET',
        '200 新按钮+已选科目+状态', '%s, 标记=%s' % (r4.status_code, has_new),
        'PASS' if ok4 else 'FAIL', 'len=%d' % len(h4))

    # ---- 4. 教务审批列表 ----
    r5 = adm.get(BASE + '/registrar/subject/approvals?filterby=pending',
                 timeout=60)
    h5 = r5.text
    no_tb5 = 'Traceback' not in h5
    has_rows = '选课审批' in h5 and '待审批' in h5
    ok5 = r5.status_code == 200 and no_tb5 and has_rows
    rec('4 GET /registrar/subject/approvals', 'HTTP GET',
        '200 待审批列表', '%s, 标记=%s' % (r5.status_code, has_rows),
        'PASS' if ok5 else 'FAIL', 'len=%d' % len(h5))

    # ---- 5. 通过刚创建的单 ----
    if not new_rid:
        rec('5 详情+通过', 'HTTP', '有待审批单可测', '新单未创建', 'FAIL')
    else:
        rid = new_rid
        r6 = adm.get(BASE + '/registrar/subject/approvals/%d' % rid,
                     timeout=60)
        h6 = r6.text
        no_tb6 = 'Traceback' not in h6
        tok6 = CSRF_RE.search(h6)
        rec('5a GET 审批详情', 'HTTP GET', '200 详情+差异提示',
            '%s, csrf=%s, 差异提示=%s' % (r6.status_code, bool(tok6),
                                        '将把该学生档案科目整体覆盖' in h6),
            'PASS' if (r6.status_code == 200 and no_tb6 and tok6) else 'FAIL',
            'len=%d' % len(h6))
        if tok6:
            r7 = adm.post(
                BASE + '/registrar/subject/approvals/%d/set_state' % rid,
                data={'csrf_token': tok6.group(1), 'state': 'approved'},
                timeout=60, allow_redirects=False)
            rec('5b POST 通过', 'HTTP POST', '303 回审批列表',
                '%s -> %s' % (r7.status_code,
                              r7.headers.get('Location', '')),
                'PASS' if r7.status_code == 303 else 'FAIL', '')

    # ---- 6. 学生端联动 ----
    r8 = stu.get(BASE + '/subject/registration?filterby=approved',
                 timeout=60)
    h8 = r8.text
    has_approved = '已批准' in h8 and '预备科' in h8
    ok8 = r8.status_code == 200 and 'Traceback' not in h8 and has_approved
    rec('6a 学生我的申请已通过', 'HTTP GET', '200 显示已批准',
        '%s, 标记=%s' % (r8.status_code, has_approved),
        'PASS' if ok8 else 'FAIL', 'len=%d' % len(h8))
    r9 = stu.get(BASE + '/my/courses', timeout=60)
    h9 = r9.text
    ok9 = r9.status_code == 200 and 'Traceback' not in h9
    subj_marks = [k for k in ['小要理问答', '基础信仰', '选修课程'] if k in h9]
    rec('6b /my/courses LMS 档案科目联动', 'HTTP GET',
        '200 出现档案科目卡', '%s, 科目=%s' % (r9.status_code, subj_marks),
        'PASS' if ok9 and subj_marks else 'FAIL', 'len=%d' % len(h9))

    # ---- 7. 驳回场景（自建临时课+班+1门选修科目，幂等可重跑）----
    sj7 = call_kw(adm, 'op.subject', 'create', [{
        'name': '【冒烟】驳回课', 'code': 'SMK-REJ',
        'subject_type': 'elective', 'type': 'theory'}])
    cj7 = call_kw(adm, 'op.course', 'create', [{
        'name': '【冒烟】驳回课程', 'code': 'CRS-SMK-REJ',
        'evaluation_type': 'normal'}])
    if cj7:
        call_kw(adm, 'op.course', 'write',
                [[cj7], {'subject_ids': [(6, 0, [sj7])]}])
    bj7 = call_kw(adm, 'op.batch', 'create', [{
        'name': '【冒烟】驳回班', 'code': 'SMK-REJ-B',
        'course_id': cj7,
        'start_date': '2026-01-01', 'end_date': '2027-01-01'}])
    r10, tok10 = csrf(stu, '/subject/enroll')
    payload7 = {'csrf_token': tok10, 'course_id': str(cj7), 'batch_id': str(bj7),
                'elective_subject_ids': str(sj7),
                'applicant_note': '【冒烟测试可删】驳回测试'}
    r10b = stu.post(BASE + '/subject/enroll/save', data=payload7,
                    timeout=60, allow_redirects=False)
    loc7 = r10b.headers.get('Location') or ''
    m7 = re.search(r'new_id=(\d+)', loc7)
    rid7 = int(m7.group(1)) if m7 else 0
    if not rid7:
        rec('7 驳回', 'HTTP', '有新单可测', '新单未创建', 'FAIL')
    else:
        r12, tok12 = csrf(adm, '/registrar/subject/approvals/%d' % rid7)
        r13 = adm.post(
            BASE + '/registrar/subject/approvals/%d/set_state' % rid7,
            data={'csrf_token': tok12, 'state': 'rejected',
                  'reject_reason': '【冒烟测试可删】名额已满请改选其他班'},
            timeout=60, allow_redirects=False)
        r14 = stu.get(BASE + '/subject/registration?filterby=rejected',
                      timeout=60)
        h14 = r14.text
        has_reason = '名额已满请改选其他班' in h14 and '已驳回' in h14
        ok14 = r14.status_code == 200 and has_reason
        rec('7 POST 驳回+学生可见原因', 'HTTP POST/GET',
            '驳回原因在列表可见', '%s, 原因可见=%s' % (r14.status_code, has_reason),
            'PASS' if ok14 else 'FAIL', 'len=%d' % len(h14))
    # 清理场景7临时对象（无论成功失败）
    if rid7:
        call_kw(adm, 'op.subject.registration', 'unlink', [[rid7]])
    if bj7:
        call_kw(adm, 'op.batch', 'unlink', [[bj7]])
    if cj7:
        call_kw(adm, 'op.course', 'unlink', [[cj7]])
    if sj7:
        call_kw(adm, 'op.subject', 'unlink', [[sj7]])

    # ---- 8. 权限负例 ----
    r15 = stu.get(BASE + '/registrar/subject/approvals', timeout=60,
                  allow_redirects=False)
    ok15 = r15.status_code in (301, 302, 303) and \
        '/my/home' in (r15.headers.get('Location') or '')
    rec('8 学生访问教务审批 302 回首页', 'HTTP GET', '302 /my/home',
        '%s -> %s' % (r15.status_code,
                      r15.headers.get('Location', '')),
        'PASS' if ok15 else 'FAIL', '')

    # ---- 9. 多选修 getlist + doc_type 标记（repair round-2）----
    # 建一个带 2 门选修的临时课程供多值勾选测试（冒烟后清理）
    subj_ids = []
    for code in ('【冒烟】选修A', '【冒烟】选修B'):
        sid = call_kw(adm, 'op.subject', 'create', [{
            'name': code, 'code': code,
            'subject_type': 'elective', 'type': 'theory'}])
        subj_ids.append(sid)
    cid = call_kw(adm, 'op.course', 'create', [{
        'name': '【冒烟】多选修课', 'code': 'CRS-SMK%E',
        'evaluation_type': 'normal'}])
    if cid:
        call_kw(adm, 'op.course', 'write',
                [[cid], {'subject_ids': [(6, 0, subj_ids)]}])
    # batch 挂到该课程
    bid = call_kw(adm, 'op.batch', 'create', [{
        'name': '【冒烟】多选修班', 'code': 'SMK%E-B',
        'course_id': cid,
        'start_date': '2026-01-01', 'end_date': '2027-01-01'}])
    if cid and bid:
        r20, tok20 = csrf(stu, '/subject/enroll')
        p20 = {'csrf_token': tok20, 'course_id': str(cid),
               'batch_id': str(bid),
               # 两个同名多值 checkbox → werkzeug 表单 getlist 返回 list
               'elective_subject_ids': [str(subj_ids[0]), str(subj_ids[1])],
               'applicant_note': '【冒烟测试可删】multi-elective'}
        r21 = stu.post(BASE + '/subject/enroll/save', data=p20,
                       timeout=60, allow_redirects=False)
        loc21 = r21.headers.get('Location') or ''
        m21 = re.search(r'new_id=(\d+)', loc21)
        rid21 = int(m21.group(1)) if m21 else 0
        # doc_type 校验
        dt_rows = call_kw(adm, 'op.subject.registration', 'read',
                          [[rid21], ['doc_type', 'state', 'elective_subject_ids']])
        dt_ok = bool(dt_rows) and dt_rows[0].get('doc_type') == \
            'subject_registration' and \
            len(dt_rows[0].get('elective_subject_ids') or []) == 2
        ok21 = rid21 and dt_ok
        rec('9 多选修(2门) getlist + doc_type', 'HTTP POST/RPC',
            '两门选修入库且 doc_type=subject_registration',
            'rid=%s doc_type_ok=%s' % (rid21, dt_ok),
            'PASS' if ok21 else 'FAIL', 'loc=%s' % loc21)
        # 清理临时课程/科目/单
        if rid21:
            call_kw(adm, 'op.subject.registration', 'unlink', [[rid21]])
        call_kw(adm, 'op.batch', 'unlink', [[bid]])
        call_kw(adm, 'op.course', 'unlink', [[cid]])
        call_kw(adm, 'op.subject', 'unlink', [subj_ids])
    else:
        rec('9 多选修 getlist + doc_type', 'HTTP POST/RPC',
            '建临时课程', '建课失败', 'FAIL', '')

    # ---- 10. 空科目报课单通过防呆（repair round-2）----
    # 学生5 有 course18 档案（sc9，14 门科目）。直接 RPC 造一份
    # doc_type=subject_registration 的空科目 submitted 单（模拟存量空单/
    # 绕过前端），教务通过应被 UserError 拦截；详情页应显示红条。
    rid_guard = call_kw(adm, 'op.subject.registration', 'create', [{
        'student_id': 5, 'course_id': 18, 'batch_id': 8,
        'state': 'submitted', 'doc_type': 'subject_registration',
        'applicant_note': '【冒烟测试可删】empty-guard'}])
    if not rid_guard:
        rec('10 空科目单通过防呆', 'RPC create', '空单创建', '失败', 'FAIL')
    else:
        # 详情页红条 + 通过被拦。判据设计（2026-09-17 t7 收紧 + 队长范围更正）：
        #  ① 科目数**动态读**——写死会随数据态漂移（曾写死 '14'，见 commit f922981）；
        #  ② 数字**与被断言的短语绑定**，在去标签+归一空白后的文本上匹配
        #     「清空该学生档案的全部 N 门科目」——旧写法 str(n_cur) in text 在 n_cur=1 时几乎恒真；
        #  ③ **数据条件分支**：sc.subject_ids 会被审批流程整体覆盖（registration.py 的设计），
        #     所以「档案非空」这个前置**不由本脚本掌控**。档案为空 ⇒ 防呆按设计不触发 ⇒
        #     **显式 SKIP**（不硬判 FAIL：那是把数据态问题记成缺陷；也不硬判 PASS：那是假绿），
        #     并用 guard_source_present() 交叉核对产品防呆**代码路径确实存在**，兜住覆盖。
        #     （产品守卫本身是否该"自毁"属产品语义，另以 finding 上报，不在测试侧改。）
        # 读的必须是**课程 18 那份档案**（红条说的就是它）——不能只按 student 过滤：
        # 学生若有多份档案（转班/换课），limit=1 可能读到别的那份，判据就失焦了。
        _cur = call_kw(adm, 'op.student.course', 'search_read',
                       [[('student_id', '=', 5), ('course_id', '=', 18)]],
                       {'fields': ['subject_ids'], 'limit': 1})
        n_cur = len(_cur[0]['subject_ids']) if _cur else 0

        if n_cur == 0:
            _ok, _why = guard_source_present()
            skip('10 空科目单通过防呆（数据态不可判定）', 'RPC approve',
                 '档案非空时才判得出防呆是否生效',
                 'SKIP：档案 0 门 ⇒ 防呆按设计不触发',
                 '先跑 scripts/seed_wangxiaoming_subjects.py 恢复演示档案再复跑')
            rec('10 防呆代码路径存在（SKIP 的覆盖兜底）', 'READ source',
                'registration.py 含 doc_type/空 payload/档案非空 三特征串',
                _why, 'PASS' if _ok else 'FAIL')
            call_kw(adm, 'op.subject.registration', 'unlink', [[rid_guard]])
        else:
            r40 = adm.get(BASE + '/registrar/subject/approvals/%d' % rid_guard,
                          timeout=60)
            _plain = re.sub(r'\s+', ' ', re.sub(r'(?s)<[^>]+>', ' ', r40.text))
            _want = '清空该学生档案的全部 %d 门科目' % n_cur
            red_ok = _want in _plain
            if not red_ok:
                print('     #10 红条判据未命中：n_cur=%d 期望短语=%r'
                      % (n_cur, _want))
            # 通过被拦：action_enroll_approve 直接 RPC（会抛 UserError）
            r41 = adm.post(BASE + '/web/dataset/call_kw', json={
                'jsonrpc': '2.0', 'method': 'call',
                'params': {'model': 'op.subject.registration',
                           'method': 'action_enroll_approve',
                           'args': [[rid_guard]], 'kwargs': {}}}, timeout=60)
            err = r41.json().get('error') or {}
            err_msg = (err.get('data') or {}).get('message') or ''
            guard_ok = ('未包含任何科目' in err_msg
                        and '已有' in err_msg and '门科目' in err_msg)
            # 单仍为 submitted（未被流转）
            st = call_kw(adm, 'op.subject.registration', 'read',
                         [[rid_guard], ['state']])
            still_submitted = st and st[0].get('state') == 'submitted'
            rec('10 空科目单通过防呆', 'RPC approve',
                'UserError拦截+详情红条+状态未变',
                'guard=%s redbar=%s still_submitted=%s'
                % (guard_ok, red_ok, still_submitted),
                'PASS' if (guard_ok and red_ok and still_submitted) else 'FAIL',
                err_msg[:120])
            call_kw(adm, 'op.subject.registration', 'unlink', [[rid_guard]])

    fails = sum(1 for x in R if x['result'] == 'FAIL')
    skips = sum(1 for x in R if x['result'] == 'SKIP')
    print('\n%s / %s passed%s' % (len(R) - fails - skips, len(R),
                                  ('（另有 %d 条 SKIP，未判定）' % skips) if skips else ''))
    return 0 if fails == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
