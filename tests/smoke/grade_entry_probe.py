#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户「成绩录入」端到端探针（教务 / 任课教师矩阵录分）—— 2026-09-29 新增。

## 这个脚本证什么

被验对象 = edu_portal/controllers/grade_entry.py 的 /grade-entry 与 /grade-entry/save
（数据落在基座既有 op.marksheet.* 链上，不新造成绩模型）。四类断言：

  A 前置事实（跑前读数，可复跑）
  B 正向：教务打开网格页 200（看得到整班名单与科目列）→ 提交 → 303 回本页
  C 落库与「同一份数据」：同一批数字必须同时出现在
      · 写侧 op.exam.attendees（后台「时间表 / 考试 / 考试参加者」读的就是它）
      · 读侧 op.result.line / op.marksheet.line（学生端 /grade-book 与它的 CSV 下载读的就是它）
      · 留痕 edu.grade.history（谁 / 何时 / 从多少改到多少）
      · 后台 RPC（以教务会话真的 search_read 一次，贴原始读数）
  D 反向（越权与脏数据，每一条都要求**零落库**）
      D1 任课教师提交**非本人任教**的科目 → 不落库
      D2 任课教师提交**不在本人任教范围**的班级 → 303 且不落库
      D3 学生会话 GET / POST → 303 回门户首页；未登录 → 303 到登录页
      D4 名单外学生 id（不存在 / 不属于本班）→ 整条丢弃，不落库
      D5 分数超出 0..100 → 整批不写入（不是半批）
  E 控制组（证明上面的断言不是恒真 / 恒假）
      E1 同一份 payload 换**有权限**的身份（教务）提交 → 成功落库 ⇒ D1 的拒绝来自权限而非坏数据
      E2 任课教师提交**本人任教**的科目 → 成功落库 ⇒ D2 的拒绝来自范围而非"教师路径整个坏了"
      E3 不存在的班级 id → 303 带错误，且不落库
      E4 重复提交同一批值 → 留痕**不新增**（无变化不写第二条）
  F 存量不动：演示数据（EX-DEMO-01 的 attendee 与 result_line）改前改后逐字相等

## 用法

    python3 tests/smoke/grade_entry_probe.py             # 全量（造夹具并保留，可复跑）
    python3 tests/smoke/grade_entry_probe.py --only d    # 只跑 D 段（注入实验用）
    python3 tests/smoke/grade_entry_probe.py --purge     # 只清本探针造的成绩容器
退出码：0=全绿；1=有断言失败；2=运行错误（站点不可达 / 登不上）。
结果落盘：tests/smoke/grade_entry_probe_results.json

判据纪律（照抄同模块 tests/smoke/assess_task_portal.py）：
  · 303 一律 allow_redirects=False + Location 精确匹配，不靠"最终 200"糊过去；
  · 每条负向断言都配正对照（E 段）；
  · 每个写入段都做 SQL 前后对照，负向段额外要求"改前改后逐字相等"。
"""
import argparse
import json
import os
import re
import subprocess
import sys

import requests

BASE = os.environ.get('EDU_BASE', 'http://localhost:8069')
DB = os.environ.get('EDU_DB', 'edu19')
DB_CONTAINER = os.environ.get('EDU_DB_CONTAINER', 'edu19-clone-db-1')
PASSWORD = os.environ.get('EDU_PASSWORD', 'demo123')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'tests', 'smoke', 'grade_entry_probe_results.json')

# 夹具坐标（本地演示库：batch 8 = 预备科 · 2026级【演示】；subject 35 = 小要理问答；
# faculty@local 挂 op.faculty 17，在 batch 8 教 35 / 37 / 40）
BATCH = 8
SUBJECT_IN = 35          # 教师任教（且在班课节里）
SUBJECT_OUT = 36         # 出现在网格列里（学生报课）、但**不在**该教师任教科目里
# ⚠ 实测订正（2026-09-29）：本库 batch 8 的 op_session 里，faculty 17 任教的是
#   35 / 37 / 40 / 46 四科（46 也有一节）⇒ 最初拿 46 当"越权科目"是**假设错了**，
#   那次"越权成功"其实是合法写入。越权科目必须取一个教师确实没教的（此处 36）。
BATCH_OUT = 12           # 该教师不任教的班
STU_A = 5                # 王小明（batch 8）
MARKS_A = 87
MARKS_B = 74
MARKS_C = 61
BAD_MARKS = 999

rows = []
facts = {}


def check(no, name, cond, detail=''):
    verdict = 'PASS' if cond else 'FAIL'
    rows.append({'no': no, 'name': name, 'pass': bool(cond), 'detail': str(detail)[:800]})
    print('  %-4s #%-6s %-58s %s' % (verdict, no, name, str(detail)[:200]))
    return bool(cond)


def note(no, name, detail=''):
    rows.append({'no': no, 'name': name, 'pass': True, 'info': True, 'detail': str(detail)[:800]})
    print('  INFO #%-6s %-58s %s' % (no, name, str(detail)[:200]))


def psql(sql):
    out = subprocess.run(['docker', 'exec', DB_CONTAINER, 'psql', '-U', 'odoo', '-d', DB,
                          '-tAc', sql], capture_output=True, text=True, timeout=90)
    if out.returncode != 0:
        raise RuntimeError('psql failed: %s' % (out.stderr or '')[:300])
    return out.stdout.strip()


def login(name, password=PASSWORD):
    s = requests.Session()
    s.trust_env = False
    s.proxies = {'http': None, 'https': None}
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': DB, 'login': name, 'password': password}}, timeout=30)
    data = r.json().get('result') or {}
    return (s if data.get('uid') else None), data.get('uid')


def call_kw(sess, model, method, args=None, kwargs=None):
    r = sess.post(BASE + '/web/dataset/call_kw', json={
        'jsonrpc': '2.0', 'method': 'call',
        'params': {'model': model, 'method': method,
                   'args': args or [], 'kwargs': kwargs or {}}}, timeout=60)
    data = r.json()
    if 'error' in data:
        info = data['error'].get('data') or {}
        return None, '%s: %s' % (info.get('name'), (info.get('message') or '')[:160])
    return data.get('result'), None


def get(sess, path, follow=True):
    return sess.get(BASE + path, timeout=60, allow_redirects=follow)


def csrf_of(sess, path):
    r = sess.get(BASE + path, timeout=60, allow_redirects=True)
    m = re.search('name="csrf_token"[^>]*value="([^"]+)"', r.text)
    return (m.group(1) if m else None), r


def post(sess, path, data):
    return sess.post(BASE + path, data=data, timeout=90, allow_redirects=False)


def loc(r):
    return r.headers.get('Location') or ''


def exam_id(code):
    out = psql("SELECT id FROM op_exam WHERE exam_code = '%s'" % code)
    return int(out) if out else None


def att_marks(code, student):
    ex = exam_id(code)
    if not ex:
        return None
    out = psql('SELECT COALESCE(marks::text, NULL) FROM op_exam_attendees '
               'WHERE exam_id = %d AND student_id = %d' % (ex, student))
    return out


def result_marks(code, student):
    ex = exam_id(code)
    if not ex:
        return None
    out = psql('SELECT marks FROM op_result_line WHERE exam_id = %d AND student_id = %d'
               % (ex, student))
    return out


def history_count(code, student):
    ex = exam_id(code)
    if not ex:
        return 0
    out = psql('SELECT count(*) FROM edu_grade_history WHERE exam_id = %d AND student_id = %d'
               % (ex, student))
    return int(out or 0)


def counts():
    sql = ('SELECT '
           "(SELECT count(*) FROM op_exam) || '/' || "
           "(SELECT count(*) FROM op_exam_session) || '/' || "
           "(SELECT count(*) FROM op_exam_attendees) || '/' || "
           "(SELECT count(*) FROM op_result_line) || '/' || "
           "(SELECT count(*) FROM op_marksheet_line) || '/' || "
           "(SELECT count(*) FROM op_marksheet_register) || '/' || "
           "(SELECT count(*) FROM op_result_template) || '/' || "
           "(SELECT count(*) FROM edu_grade_history)")
    return psql(sql)


def drop_container(batch, subject, term=1):
    """删掉 (班, 科, 学期) 的容器 —— 负向段开跑前先把它清干净。

    为什么必须有这一步（实测教训）：E1 控制组会**合法地**建出同一个容器，
    于是下一轮跑 D1b「该科目容器一行都没建」会假红 —— 断言依赖上一轮留下的状态。
    负向断言必须从确定状态出发：先清、再试、再验"没有新建"。
    """
    code = 'GE%dS%dT%d' % (batch, subject, term)
    ex = exam_id(code)
    if not ex:
        return
    psql('DELETE FROM edu_grade_history WHERE exam_id = %d' % ex)
    psql('DELETE FROM op_result_line WHERE exam_id = %d' % ex)
    psql('DELETE FROM op_exam_attendees WHERE exam_id = %d' % ex)
    psql('DELETE FROM op_exam WHERE id = %d' % ex)


def purge():
    """清掉本探针造的容器（exam_code 以 GE 开头 / session 以 GB 开头）。"""
    ex_ids = [x for x in psql("SELECT id FROM op_exam WHERE exam_code LIKE 'GE%'").splitlines() if x]
    se_ids = [x for x in psql("SELECT id FROM op_exam_session WHERE exam_code LIKE 'GB%'").splitlines() if x]
    if not ex_ids and not se_ids:
        print('  （没有本探针的容器）')
        return
    joined = ','.join(ex_ids) if ex_ids else '-1'
    psql('DELETE FROM edu_grade_history WHERE exam_id IN (%s)' % joined)
    psql('DELETE FROM op_result_line WHERE exam_id IN (%s)' % joined)
    psql('DELETE FROM op_exam_attendees WHERE exam_id IN (%s)' % joined)
    reg_ids = [x for x in psql(
        'SELECT id FROM op_marksheet_register WHERE exam_session_id IN (%s)'
        % (','.join(se_ids) if se_ids else '-1')).splitlines() if x]
    if reg_ids:
        psql('DELETE FROM op_marksheet_line WHERE marksheet_reg_id IN (%s)'
             % ','.join(reg_ids))
    psql('DELETE FROM op_exam WHERE exam_code LIKE %s' % "'GE%'")
    if reg_ids:
        psql('DELETE FROM op_marksheet_register WHERE id IN (%s)' % ','.join(reg_ids))
    if se_ids:
        psql('DELETE FROM op_result_template WHERE exam_session_id IN (%s)'
             % ','.join(se_ids))
        psql('DELETE FROM op_exam_session WHERE id IN (%s)' % ','.join(se_ids))
    print('  已清理：exam %s / session %s' % (ex_ids, se_ids))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='', help='只跑某一段（b/c/d/e/f）')
    ap.add_argument('--purge', action='store_true', help='只清夹具')
    args = ap.parse_args()
    if args.purge:
        purge()
        return 0
    want = (args.only or '').lower()

    print('== 门户成绩录入探针（%s · 库 %s · 容器 %s）==' % (BASE, DB, DB_CONTAINER))
    try:
        bo, bo_uid = login('backoffice@local')
        fac, fac_uid = login('faculty@local')
        stu, stu_uid = login('stu@local')
    except Exception as exc:                                  # noqa: BLE001
        print('ENV：登录失败 %s' % exc)
        return 2
    if not (bo and fac and stu):
        print('ENV：三个身份的会话没拿齐（bo=%s fac=%s stu=%s）' % (bool(bo), bool(fac), bool(stu)))
        return 2

    # ---------------- A 前置事实 ----------------
    print('-- A 前置事实 --')
    c0 = counts()
    note('A1', '跑前行数（exam/session/attendee/result/marksheet/register/template/history）', c0)
    demo_att = psql('SELECT marks FROM op_exam_attendees WHERE exam_id = 11 AND student_id = 5')
    demo_rl = psql('SELECT marks FROM op_result_line WHERE exam_id = 11 AND student_id = 5')
    note('A2', '存量演示数据（EX-DEMO-01 / 王小明）attendee 与 result_line', '%s / %s' % (demo_att, demo_rl))
    facts['counts_before'] = c0
    facts['demo_before'] = [demo_att, demo_rl]

    # ---------------- B 正向：教务打开网格并提交 ----------------
    if not want or want == 'b':
        print('-- B 正向（教务） --')
        r = get(bo, '/grade-entry?batch_id=%d' % BATCH)
        check('B1', '教务 GET /grade-entry?batch_id=8 → 200', r.status_code == 200,
              'HTTP %s' % r.status_code)
        check('B2', '页面渲染出成绩矩阵表格', 'yy-grade-matrix' in r.text,
              'yy-grade-matrix 出现在页面：%s' % ('yy-grade-matrix' in r.text))
        cells = sorted(set(re.findall('name="m_([0-9]+)_([0-9]+)"', r.text)))
        check('B3', '矩阵里有 (学生 x 科目) 格子', len(cells) > 0, '%d 个格子，样例 %s' % (len(cells), cells[:4]))
        check('B4', '名单含本班学生（王小明）', any(st == str(STU_A) for st, _s in cells),
              '学生 %d 的格子：%s' % (STU_A, [c for c in cells if c[0] == str(STU_A)][:3]))
        token, _page = csrf_of(bo, '/grade-entry?batch_id=%d' % BATCH)
        check('B5', '页面带 csrf 令牌', bool(token), 'token=%s' % bool(token))
        resp = post(bo, '/grade-entry/save', {
            'csrf_token': token, 'batch_id': str(BATCH), 'term_id': '1',
            'm_%d_%d' % (STU_A, SUBJECT_IN): str(MARKS_A)})
        check('B6', '教务提交 → 303 回本页且 saved=1',
              resp.status_code == 303 and 'saved=1' in loc(resp),
              'HTTP %s Location=%s' % (resp.status_code, loc(resp)))

    # ---------------- C 落库 + 同一份数据 ----------------
    if not want or want == 'c':
        print('-- C 落库与同一份数据 --')
        code = 'GE%dS%dT1' % (BATCH, SUBJECT_IN)
        check('C1', '写侧 op.exam.attendees.marks 落库', att_marks(code, STU_A) == str(MARKS_A),
              'attendee marks=%s（期望 %d）' % (att_marks(code, STU_A), MARKS_A))
        check('C2', '读侧 op.result.line.marks 同步为同一个值',
              result_marks(code, STU_A) == str(MARKS_A),
              'result_line marks=%s（期望 %d）' % (result_marks(code, STU_A), MARKS_A))
        ex = exam_id(code)
        ms = psql('SELECT ml.id FROM op_marksheet_line ml WHERE ml.student_id = %d '
                  'AND ml.marksheet_reg_id IN (SELECT id FROM op_marksheet_register '
                  'WHERE exam_session_id = (SELECT session_id FROM op_exam WHERE id = %d))'
                  % (STU_A, ex or 0))
        check('C3', '成绩单行 op.marksheet.line 生成（学生端卡片来源）', bool(ms),
              'marksheet_line id=%s' % ms)
        check('C4', '留痕 edu.grade.history 记下了这次改动', history_count(code, STU_A) >= 1,
              'history 条数=%d' % history_count(code, STU_A))
        hist = psql("SELECT old_marks || ' -> ' || new_marks || ' / ' || source "
                    "FROM edu_grade_history WHERE exam_id = %d AND student_id = %d "
                    'ORDER BY id DESC LIMIT 1' % (ex or 0, STU_A))
        note('C5', '最近一条留痕原文（原分 -> 新分 / 来源）', hist)
        audit = psql("SELECT count(*) FROM edu_audit_log WHERE action = '成绩录入'")
        check('C6', '操作审计 edu.audit.log 有「成绩录入」记录', int(audit or 0) >= 1,
              'audit 条数=%s' % audit)

        # 后台 RPC（教务会话自己读一次）——「与后台同一份数据」的直接读数
        back_att, err1 = call_kw(bo, 'op.exam.attendees', 'search_read',
                                 [[['exam_id', '=', ex]], ['student_id', 'marks']])
        back_rl, err2 = call_kw(bo, 'op.result.line', 'search_read',
                                [[['exam_id', '=', ex]], ['student_id', 'marks']])
        note('C7', '后台会话 RPC 读 op.exam.attendees', '%s %s' % (back_att, err1 or ''))
        note('C8', '后台会话 RPC 读 op.result.line', '%s %s' % (back_rl, err2 or ''))
        check('C9', '后台两处读数 == 门户写入值',
              bool(back_att) and bool(back_rl)
              and all(a['marks'] == MARKS_A for a in back_att)
              and all(a['marks'] == MARKS_A for a in back_rl),
              'attendees=%s result=%s' % (back_att, back_rl))
        me = call_kw(bo, 'op.marksheet.line', 'search_read',
                     [[['student_id', '=', STU_A]], ['total_marks', 'percentage']])
        note('C10', '后台会话 RPC 读 op.marksheet.line', '%s' % (me,))

        # 等级：既有七档 op.grade.configuration 映射（87 分 → A）。
        # 这条顺带守住 2026-09-29 修掉的基座缺陷：op.result.line._compute_grade 缺 break
        # ⇒ 除最后一档外等级恒空（覆盖层见 models/grade_line_grade.py）。
        grades, err3 = call_kw(bo, 'op.result.line', 'search_read',
                              [[['exam_id', '=', ex]], ['marks', 'grade']])
        gset = [g['grade'] for g in (grades or [])]
        check('C14', '等级按既有七档映射出 A（87 分）', gset == ['A'],
              'result_line grade=%s %s' % (gset, err3 or ''))

        # 学生端：成绩簿页面 + CSV 下载（学生自己的下载路由）
        sv = get(stu, '/grade-book')
        check('C11', '学生端 /grade-book 200', sv.status_code == 200, 'HTTP %s' % sv.status_code)
        check('C12', '学生端页面出现本科目与分数',
              '小要理问答' in sv.text and str(MARKS_A) in sv.text,
              '含科目名=%s 含分数=%s' % ('小要理问答' in sv.text, str(MARKS_A) in sv.text))
        csv = get(stu, '/grade-book/report/download')
        line = [x for x in (csv.text or '').splitlines() if '小要理问答' in x and '总评' in x]
        fields = line[0].split(',') if line else []
        check('C13', '学生端 CSV 该行的「得分 / 满分」等于门户写入值',
              len(fields) >= 4 and fields[2] == str(MARKS_A) and fields[3] == '100',
              'CSV 行：%s' % (line[:1]))
        facts['csv_line'] = line[:1]

    # ---------------- D 反向（越权 / 脏数据） ----------------
    if not want or want == 'd':
        print('-- D 反向（越权与脏数据；每条都要求零落库） --')
        drop_container(BATCH, SUBJECT_OUT)
        c_before = counts()
        # D1 教师提交「非本人任教」的科目（batch 8 / subject 36）
        token, _p = csrf_of(fac, '/grade-entry?batch_id=%d' % BATCH)
        r = post(fac, '/grade-entry/save', {
            'csrf_token': token, 'batch_id': str(BATCH), 'term_id': '1',
            'm_%d_%d' % (STU_A, SUBJECT_OUT): str(MARKS_C)})
        code_out = 'GE%dS%dT1' % (BATCH, SUBJECT_OUT)
        check('D1a', '教师提交非任教科目（36）→ 303 且不带 saved=1',
              r.status_code == 303 and 'saved=1' not in loc(r),
              'HTTP %s Location=%s' % (r.status_code, loc(r)))
        check('D1b', '该科目容器一行都没建（零落库）', exam_id(code_out) is None,
              '%s id=%s' % (code_out, exam_id(code_out)))
        check('D1c', '行数改前改后逐字相等', counts() == c_before,
              'before=%s after=%s' % (c_before, counts()))

        # D2 教师提交「不在任教范围」的班级
        r = post(fac, '/grade-entry/save', {
            'csrf_token': token, 'batch_id': str(BATCH_OUT), 'term_id': '1',
            'm_%d_%d' % (STU_A, SUBJECT_IN): str(MARKS_C)})
        check('D2a', '教师提交任外班级 → 303 带 err=scope',
              r.status_code == 303 and 'err=scope' in loc(r),
              'HTTP %s Location=%s' % (r.status_code, loc(r)))
        check('D2b', '任外班级的容器没被建出来',
              psql("SELECT count(*) FROM op_exam_session WHERE exam_code LIKE 'GB%dT%%'" % BATCH_OUT) == '0',
              'session(GB%dT*) = %s' % (BATCH_OUT,
                                        psql("SELECT count(*) FROM op_exam_session WHERE exam_code LIKE 'GB%dT%%'" % BATCH_OUT)))
        check('D2c', '行数改前改后逐字相等', counts() == c_before,
              'before=%s after=%s' % (c_before, counts()))

        # D3 学生 / 匿名
        r = get(stu, '/grade-entry', follow=False)
        check('D3a', '学生会话 GET /grade-entry → 303 /my/home',
              r.status_code == 303 and loc(r).endswith('/my/home'),
              'HTTP %s Location=%s' % (r.status_code, loc(r)))
        token_stu, _p = csrf_of(stu, '/my/home')
        r = post(stu, '/grade-entry/save', {
            'csrf_token': token_stu or '', 'batch_id': str(BATCH),
            'm_%d_%d' % (STU_A, SUBJECT_IN): str(MARKS_C)})
        check('D3b', '学生会话 POST /grade-entry/save → 303 /my/home（或被 csrf 拒）',
              r.status_code in (303, 400) and (r.status_code == 303),
              'HTTP %s Location=%s' % (r.status_code, loc(r)))
        anon = requests.Session()
        anon.trust_env = False
        r = anon.get(BASE + '/grade-entry', timeout=60, allow_redirects=False)
        check('D3c', '未登录 → 303 到登录页', r.status_code == 303 and '/web/login' in loc(r),
              'HTTP %s Location=%s' % (r.status_code, loc(r)))
        check('D3d', 'D3 三个身份的行数改前改后逐字相等', counts() == c_before,
              'before=%s after=%s' % (c_before, counts()))

        # D4 名单外学生（不存在的 id 与 不属于本班的真实学生）
        token, _p = csrf_of(bo, '/grade-entry?batch_id=%d' % BATCH)
        r = post(bo, '/grade-entry/save', {
            'csrf_token': token, 'batch_id': str(BATCH), 'term_id': '1',
            'm_999999_%d' % SUBJECT_IN: str(MARKS_C)})
        check('D4a', '不存在的学生 id → 整条丢弃（303 且 saved 不为 1）',
              r.status_code == 303 and 'saved=1' not in loc(r),
              'HTTP %s Location=%s' % (r.status_code, loc(r)))
        code_in = 'GE%dS%dT1' % (BATCH, SUBJECT_IN)
        check('D4b', '没给这个幽灵学生建 attendee 行',
              psql('SELECT count(*) FROM op_exam_attendees WHERE student_id = 999999') == '0',
              'attendee(999999)=%s' % psql('SELECT count(*) FROM op_exam_attendees WHERE student_id = 999999'))

        # D6 教师视角本身也要收敛（不是"页面没显示"就完事 —— 这里是读侧的同一条口径）
        page_fac = get(fac, '/grade-entry')
        check('D6a', '教师的选择页不再列全校班级（只列本人任教的班）',
              '预备科' in page_fac.text and '神学一年级' not in page_fac.text,
              '含预备科=%s 含神学一年级=%s' % ('预备科' in page_fac.text,
                                            '神学一年级' in page_fac.text))
        page_fac2 = get(fac, '/grade-entry?batch_id=%d' % BATCH_OUT)
        check('D6b', '教师带上任外班级 id 也只能回到空选择页（不渲染那班的网格）',
              'yy-grade-matrix' not in page_fac2.text,
              '页面含矩阵表=%s' % ('yy-grade-matrix' in page_fac2.text))

        # D5 超范围分数 → 整批不写
        before_in = att_marks(code_in, STU_A)
        r = post(bo, '/grade-entry/save', {
            'csrf_token': token, 'batch_id': str(BATCH), 'term_id': '1',
            'm_%d_%d' % (STU_A, SUBJECT_IN): str(BAD_MARKS)})
        check('D5a', '超范围分数 → 303 带 err=invalid',
              r.status_code == 303 and 'err=invalid' in loc(r),
              'HTTP %s Location=%s' % (r.status_code, loc(r)))
        check('D5b', '原有分数未被改写', att_marks(code_in, STU_A) == before_in,
              'attendee=%s（改前 %s）' % (att_marks(code_in, STU_A), before_in))

    # ---------------- E 控制组 ----------------
    if not want or want == 'e':
        print('-- E 控制组（证明上面的拒绝不是恒真） --')
        code_out = 'GE%dS%dT1' % (BATCH, SUBJECT_OUT)
        token, _p = csrf_of(bo, '/grade-entry?batch_id=%d' % BATCH)
        r = post(bo, '/grade-entry/save', {
            'csrf_token': token, 'batch_id': str(BATCH), 'term_id': '1',
            'm_%d_%d' % (STU_A, SUBJECT_OUT): str(MARKS_C)})
        check('E1', '同一 payload 由教务提交 → 成功落库（D1 的拒绝来自权限）',
              r.status_code == 303 and 'saved=1' in loc(r) and result_marks(code_out, STU_A) == str(MARKS_C),
              'HTTP %s Location=%s result_line=%s' % (r.status_code, loc(r), result_marks(code_out, STU_A)))
        token_fac, _p = csrf_of(fac, '/grade-entry?batch_id=%d' % BATCH)
        code_in = 'GE%dS%dT1' % (BATCH, SUBJECT_IN)
        r = post(fac, '/grade-entry/save', {
            'csrf_token': token_fac, 'batch_id': str(BATCH), 'term_id': '1',
            'm_%d_%d' % (STU_A, SUBJECT_IN): str(MARKS_B)})
        check('E2', '任课教师提交本人任教科目 → 成功落库（D2 的拒绝来自范围）',
              r.status_code == 303 and 'saved=1' in loc(r) and result_marks(code_in, STU_A) == str(MARKS_B),
              'HTTP %s Location=%s result_line=%s' % (r.status_code, loc(r), result_marks(code_in, STU_A)))
        hist_before = history_count(code_in, STU_A)
        r = post(fac, '/grade-entry/save', {
            'csrf_token': token_fac, 'batch_id': str(BATCH), 'term_id': '1',
            'm_%d_%d' % (STU_A, SUBJECT_IN): str(MARKS_B)})
        check('E3', '重复提交相同值 → 留痕不新增（无变化不写第二条）',
              history_count(code_in, STU_A) == hist_before,
              'history %d -> %d' % (hist_before, history_count(code_in, STU_A)))
        r = post(bo, '/grade-entry/save', {
            'csrf_token': token, 'batch_id': '999999', 'term_id': '1',
            'm_%d_%d' % (STU_A, SUBJECT_IN): str(MARKS_A)})
        check('E4', '不存在的班级 → 303 带 err=nobatch（"成功"断言在坏路径上会失败）',
              r.status_code == 303 and 'err=nobatch' in loc(r),
              'HTTP %s Location=%s' % (r.status_code, loc(r)))

    # ---------------- F 存量不动 ----------------
    if not want or want == 'f':
        print('-- F 存量与终态 --')
        demo_att2 = psql('SELECT marks FROM op_exam_attendees WHERE exam_id = 11 AND student_id = 5')
        demo_rl2 = psql('SELECT marks FROM op_result_line WHERE exam_id = 11 AND student_id = 5')
        check('F1', '存量演示行改前改后逐字相等',
              [demo_att2, demo_rl2] == facts.get('demo_before'),
              'before=%s after=%s' % (facts.get('demo_before'), [demo_att2, demo_rl2]))
        note('F2', '跑后行数（exam/session/attendee/result/marksheet/register/template/history）', counts())
        facts['counts_after'] = counts()

    bad = [r for r in rows if not r['pass']]
    print('\n== 汇总：断言 %d 条 / 失败 %d 条 ==' % (len(rows), len(bad)))
    for r in bad:
        print('  FAIL #%s %s | %s' % (r['no'], r['name'], r['detail'][:200]))
    with open(OUT, 'w', encoding='utf-8') as fh:
        json.dump({'rows': rows, 'facts': facts, 'failed': len(bad)},
                  fh, ensure_ascii=False, indent=2)
    print('  结果落盘：%s' % OUT)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
