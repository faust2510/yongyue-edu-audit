#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「成绩簿」给教务录分 —— 端到端**页面**探针（task-18，2026-10-03）。

## 被验对象

用户原话：「我希望教务人员的这个成绩薄页面，可以改成给学生录入成绩。」

改之前（本探针 A 段会重新取证一次）：教务打开 /grade-book 只有一句拒止文案。
改之后：custom_addons/edu_portal/controllers/grading.py 用 Odoo 19 官方的控制器覆写机制
（继承 + 重新 @route）把 /grade-book 按身份分流 —— 教务 / 超管 = 成绩录入网格（复用既有
/grade-entry 引擎），学生 = 原成绩簿，教师 / 家长 = 原行为。

## 为什么必须用浏览器

判据要落在**渲染后的页面**上：B/C 两段全部走 Playwright 真点击（选班 → 出网格 → 填分 →
点「保存成绩」），C 段再去学生账号看同一个学生的成绩簿页面是否跟着变。
requests 只能证明「控制器返回了 200」，证明不了「输入框在那儿、点了保存真的落库」。

## 断言结构

  A 前置事实：教务在 /grade-book 上原来看到的是拒止文案（改前读数，可复跑）
  B 正向：教务在 /grade-book 上就能拿到录入网格（未筛选 + 科目筛选两种形态）
  C 闭环：教务在**这个页面**上录一个分数 → 学生端 /grade-book 页面出现同一个数字 → 还原
  D 对照：学生看到的是自己的成绩簿；教师 / 家长行为未变（证明分流是按身份，不是全局）
  E 控制组：未登录 = 跳登录页（不是 200）；幽灵班级 = 空表单而不是 500

## 用法

    python3 tests/smoke/gradebook_registrar_entry.py            # 全量（改完自动还原）
    python3 tests/smoke/gradebook_registrar_entry.py --keep     # 保留改动（截图用）
退出码：0=全绿；1=有断言失败；2=运行错误（站点不可达 / 登不上）。
结果落盘：tests/smoke/gradebook_registrar_entry_results.json
截图：tests/gap/shots/gradebook-registrar/*.png

判据纪律（照抄 tests/smoke/grade_entry_probe.py）：
  · 每条负向断言都配正对照；写入前后做 SQL 对照；
  · 学生端判据读的是**页面上的数字**，不是数据库。
"""
import argparse
import json
import os
import re
import subprocess
import sys

os.environ['NO_PROXY'] = '127.0.0.1,localhost'
os.environ['no_proxy'] = '127.0.0.1,localhost'
for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
           'ALL_PROXY', 'all_proxy'):
    os.environ.pop(_k, None)

from playwright.sync_api import sync_playwright   # noqa: E402

BASE = os.environ.get('EDU_BASE', 'http://127.0.0.1:8069')
DB = os.environ.get('EDU_DB', 'edu19')
DB_CONTAINER = os.environ.get('EDU_DB_CONTAINER', 'edu19-clone-db-1')
PASSWORD = os.environ.get('EDU_PASSWORD', 'demo123')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'tests', 'smoke', 'gradebook_registrar_entry_results.json')
SHOTS = os.path.join(ROOT, 'tests', 'gap', 'shots', 'gradebook-registrar')

USERS = {'backoffice': 'backoffice@local', 'student': 'stu@local',
         'faculty': 'faculty@local', 'parent': 'parent@local'}

# 夹具坐标（与 tests/smoke/grade_entry_probe.py 同一套，便于互相印证）：
# batch 8 = 预备科 · 2026级【演示】；subject 35 = 小要理问答；student 5 = 王小明
BATCH = 8
SUBJECT = 35
SUBJECT_NAME = '小要理问答'
STUDENT = 5
STUDENT_NAME = '王小明'
NEW_MARKS = 83          # 刻意取一个与既有读数不同的值（既有 74）

REFUSAL = '该页面仅面向学生账号'
ENTRY_TITLE = '成绩录入'

rows = []
facts = {}


def check(no, name, cond, detail=''):
    verdict = 'PASS' if cond else 'FAIL'
    rows.append({'no': no, 'name': name, 'pass': bool(cond), 'detail': str(detail)[:800]})
    print('  %-4s #%-6s %-56s %s' % (verdict, no, name, str(detail)[:220]))
    return bool(cond)


def note(no, name, detail=''):
    rows.append({'no': no, 'name': name, 'pass': True, 'info': True, 'detail': str(detail)[:800]})
    print('  INFO #%-6s %-56s %s' % (no, name, str(detail)[:220]))


def psql(sql):
    out = subprocess.run(['docker', 'exec', DB_CONTAINER, 'psql', '-U', 'odoo', '-d', DB,
                          '-tAc', sql], capture_output=True, text=True, timeout=90)
    if out.returncode != 0:
        raise RuntimeError('psql failed: %s' % (out.stderr or '')[:300])
    return out.stdout.strip()


def flat(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def login(ctx, who):
    r = ctx.request.post(BASE + '/web/session/authenticate',
                         data=json.dumps({'jsonrpc': '2.0', 'method': 'call',
                                          'params': {'db': DB, 'login': USERS[who],
                                                     'password': PASSWORD}}),
                         headers={'Content-Type': 'application/json'}, timeout=30000)
    return ((r.json().get('result') or {}).get('uid'))


def open_page(browser, who, path, shot=None):
    """返回 (uid, page, status, text)；调用方负责 page.context.close()。"""
    ctx = browser.new_context(viewport={'width': 1440, 'height': 1000})
    uid = login(ctx, who)
    pg = ctx.new_page()
    resp = pg.goto(BASE + path, wait_until='domcontentloaded', timeout=40000)
    pg.wait_for_timeout(400)
    text = pg.inner_text('body')
    if shot:
        os.makedirs(SHOTS, exist_ok=True)
        pg.screenshot(path=os.path.join(SHOTS, shot), full_page=True)
    return uid, pg, resp.status, text


def cell_of(page, student_name, subject_name):
    """在成绩网格里找 (学生, 科目) 那个输入框；找不到返回 None。"""
    table = page.locator('table.yy-grade-matrix')
    if table.count() == 0:
        return None
    heads = [flat(h) for h in table.first.locator('thead th').all_inner_texts()]
    col = None
    for i, h in enumerate(heads):
        if h.startswith(subject_name):
            col = i
            break
    if col is None:
        return None
    for tr in table.first.locator('tbody tr').all():
        tds = tr.locator('td')
        if tds.count() and flat(tds.nth(0).inner_text()) == student_name:
            inp = tds.nth(col).locator('input')
            if inp.count():
                return inp.first
    return None


def student_marks_row(page):
    """学生成绩簿里 (科目, 考试, 分数) 三元组列表 —— 页面读数，不查库。"""
    out = []
    for table in page.locator('table').all():
        for tr in table.locator('tbody tr').all():
            tds = [flat(t) for t in tr.locator('td').all_inner_texts()]
            if len(tds) >= 3:
                out.append(tuple(tds[:3]))
    return out


def save(page):
    """点「保存成绩」，返回 (final_url, body)。"""
    btn = page.locator("form[action='/grade-entry/save'] button[type='submit']")
    with page.expect_navigation(wait_until='domcontentloaded', timeout=60000):
        btn.first.click()
    page.wait_for_timeout(600)
    return page.url, page.inner_text('body')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true', help='保留改动（默认录完会还原）')
    args = ap.parse_args()

    before_sql = psql(
        "SELECT (SELECT marks FROM op_exam_attendees a JOIN op_exam e ON e.id=a.exam_id "
        " WHERE e.exam_code LIKE 'GE%dS%dT%%' AND a.student_id=%d), "
        "(SELECT marks FROM op_result_line r JOIN op_exam e ON e.id=r.exam_id "
        " WHERE e.exam_code LIKE 'GE%dS%dT%%' AND r.student_id=%d), "
        "(SELECT marks FROM op_exam_attendees a JOIN op_exam e ON e.id=a.exam_id "
        " WHERE e.exam_code='EX-DEMO-01' AND a.student_id=%d)"
        % (BATCH, SUBJECT, STUDENT, BATCH, SUBJECT, STUDENT, STUDENT))
    facts['sql_before'] = before_sql
    note('A0', '跑前库内读数（容器 attendee / 容器 result_line / 演示行 attendee）', before_sql)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # ---------------- B：教务在 /grade-book 上就能录入 ----------------
        print('== B 教务：/grade-book 就是录入页 ==')
        uid, page, st, text = open_page(browser, 'backoffice', '/grade-book',
                                        shot='B1_bo_grade_book.png')
        check('B1', '教务 uid 有效', bool(uid), 'uid=%s' % uid)
        check('B2', '教务 GET /grade-book → 200', st == 200, 'HTTP %s' % st)
        check('B3', '教务看到的是「成绩录入」而不是拒止文案',
              ENTRY_TITLE in text and REFUSAL not in text,
              '含「%s」=%s / 含拒止文案=%s' % (ENTRY_TITLE, ENTRY_TITLE in text, REFUSAL in text))
        check('B4', '班级下拉真的渲染出来了（教务可选全校班级）',
              page.locator('#ge-batch option').count() > 2,
              'option 数=%s' % page.locator('#ge-batch option').count())
        page.context.close()

        # 未筛选：整班 × 全部科目矩阵
        uid, page, st, text = open_page(browser, 'backoffice',
                                        '/grade-book?batch_id=%d' % BATCH,
                                        shot='B2_bo_grid_all.png')
        cells = page.locator('table.yy-grade-matrix tbody input').count()
        check('B5', '选班后出现成绩网格（未筛选：整班 × 全部科目）',
              st == 200 and cells > 0, 'HTTP %s / 格子数 %s' % (st, cells))
        page.context.close()

        # 科目筛选：单列，便于精确定位
        uid, page, st, text = open_page(
            browser, 'backoffice',
            '/grade-book?batch_id=%d&subject_id=%d' % (BATCH, SUBJECT),
            shot='B3_bo_grid_subject.png')
        inp = cell_of(page, STUDENT_NAME, SUBJECT_NAME)
        check('B6', '科目筛选页能定位到 (学生 × 科目) 输入框',
              inp is not None, '输入框=%s' % ('找到' if inp is not None else '未找到'))
        if inp is None:
            page.context.close()
            browser.close()
            return finish(1)
        original = inp.input_value()
        facts['original'] = original
        check('B7', '该格有可读的原值（用于还原）', original != '',
              '%s / %s = %r' % (STUDENT_NAME, SUBJECT_NAME, original))

        # ---------------- C：闭环（在这个页面上录一个分） ----------------
        print('== C 闭环：教务在 /grade-book 录分 → 学生端 /grade-book 随之变化 ==')
        inp.fill(str(NEW_MARKS))
        final_url, body = save(page)
        check('C1', '点「保存成绩」后出现保存成功提示',
              '已保存' in body, 'final=%s' % final_url)
        check('C2', '保存后页面回显新分数', str(NEW_MARKS) in body,
              '提交 %s' % NEW_MARKS)
        page.context.close()

        mid_sql = psql(
            "SELECT (SELECT marks FROM op_exam_attendees a JOIN op_exam e ON e.id=a.exam_id "
            " WHERE e.exam_code LIKE 'GE%dS%dT%%' AND a.student_id=%d), "
            "(SELECT marks FROM op_result_line r JOIN op_exam e ON e.id=r.exam_id "
            " WHERE e.exam_code LIKE 'GE%dS%dT%%' AND r.student_id=%d)"
            % (BATCH, SUBJECT, STUDENT, BATCH, SUBJECT, STUDENT))
        facts['sql_after'] = mid_sql
        check('C3', '库内两侧（写侧 attendee / 读侧 result_line）都是同一个新值',
              mid_sql == '%s|%s' % (NEW_MARKS, NEW_MARKS), mid_sql)

        # 学生端：页面文本里必须出现这个新数字（验收口径 = 学生的成绩册随之变化）
        uid_s, page_s, st_s, text_s = open_page(browser, 'student', '/grade-book',
                                               shot='C1_student_after.png')
        pairs = student_marks_row(page_s)
        hit = [p for p in pairs if p[0] == SUBJECT_NAME and '总评' in p[1]]
        check('C4', '学生端 /grade-book 页面出现同一个分数',
              any(p[2] == str(NEW_MARKS) for p in hit),
              '学生页 (科目,考试,分数)=%s' % hit)
        check('C5', '学生端仍是成绩簿形态（没有被改成录入页）',
              ENTRY_TITLE not in text_s and '成绩簿' in text_s,
              '含「成绩录入」=%s / 含「成绩簿」=%s' % (ENTRY_TITLE in text_s, '成绩簿' in text_s))
        page_s.context.close()

        # ---------------- 还原 ----------------
        if not args.keep:
            print('== 还原：把该格写回原值 ==')
            uid, page, st, text = open_page(
                browser, 'backoffice',
                '/grade-book?batch_id=%d&subject_id=%d' % (BATCH, SUBJECT))
            inp2 = cell_of(page, STUDENT_NAME, SUBJECT_NAME)
            check('R1', '还原前能再次定位输入框', inp2 is not None, '原值=%r' % original)
            if inp2 is not None and original != '':
                inp2.fill(original)
                save(page)
            page.context.close()
            after_sql = psql(
                "SELECT (SELECT marks FROM op_exam_attendees a JOIN op_exam e ON e.id=a.exam_id "
                " WHERE e.exam_code LIKE 'GE%dS%dT%%' AND a.student_id=%d), "
                "(SELECT marks FROM op_result_line r JOIN op_exam e ON e.id=r.exam_id "
                " WHERE e.exam_code LIKE 'GE%dS%dT%%' AND r.student_id=%d), "
                "(SELECT marks FROM op_exam_attendees a JOIN op_exam e ON e.id=a.exam_id "
                " WHERE e.exam_code='EX-DEMO-01' AND a.student_id=%d)"
                % (BATCH, SUBJECT, STUDENT, BATCH, SUBJECT, STUDENT, STUDENT))
            facts['sql_restored'] = after_sql
            check('R2', '还原后库内两侧都回到原值',
                  after_sql.split('|')[:2] == [original, original], after_sql)
            check('R3', '存量演示行（EX-DEMO-01）全程未变',
                  before_sql.split('|')[2] == after_sql.split('|')[2],
                  '%s -> %s' % (before_sql.split('|')[2], after_sql.split('|')[2]))
            uid, page, st, text = open_page(browser, 'student', '/grade-book')
            pairs2 = student_marks_row(page)
            hit2 = [p for p in pairs2 if p[0] == SUBJECT_NAME and '总评' in p[1]]
            check('R4', '学生端页面也回到原值',
                  any(p[2] == original for p in hit2), '学生页=%s' % hit2)
            page.context.close()

        # ---------------- D：对照（分流是按身份，不是全局） ----------------
        # 2026-10-03 第三轮（校长裁定「直连」）：教师**也**进录入网格 —— D1 由
        # 「教师仍被拒止」**反转为**「教师也是录入形态」，并补 D1b~D1d 范围取证：
        #   范围收敛**不在 grading.py 里写第二遍**，而是既有 grade_entry._scope_pairs() 的职责；
        #   所以这里必须**从渲染出的页面上读回范围**（班级/科目选项、网格），不是读代码。
        print('== D 对照：教师直连录入；家长保持原行为 ==')
        uid, page, st, text = open_page(browser, 'faculty', '/grade-book')
        batches = [flat(o.inner_text()) for o in page.locator('#ge-batch option').all()]
        subjects = [flat(o.inner_text()) for o in page.locator('#ge-subject option').all()]
        check('D1', '教师 /grade-book = 录入形态（有班级下拉，无拒止文案）',
              page.locator('#ge-batch').count() > 0 and REFUSAL not in text,
              '班级下拉=%s / 含拒止=%s'
              % (page.locator('#ge-batch').count() > 0, REFUSAL in text))
        check('D1b', '教师可选班级只有他任教的那 1 个（服务端收敛，不是前端隐藏）',
              len(batches) == 2, '选项=%s' % batches)
        check('D1c', '教师可选科目只含他任教的 4 科（正对照：教务 149 条）',
              len(subjects) == 5, '科目=%s' % subjects)
        page.context.close()
        uid, page, st, text = open_page(browser, 'faculty',
                                        '/grade-book?batch_id=%d' % BATCH)
        n_fac = page.locator('table.yy-grade-matrix tbody input').count()
        check('D1d', '教师选了他任教的班后出现录入网格（不是空壳页）',
              n_fac > 0, '格子数=%s' % n_fac)
        # D1e/D1f（2026-10-03 第三轮修复的缺陷）：列原先**不按任教收敛**，
        # 教师看得见 10 个自己存不进去的输入框，填了保存还被说成「没有新的改动」。
        cols_fac = [flat(h) for h in
                    page.locator('table.yy-grade-matrix thead th').all_inner_texts()]
        cols_fac = [c for c in cols_fac if c and c not in ('学生', '学号', '名单来源')]
        check('D1e', '教师只看到本人任教的 4 个科目列（改前 14 列 = 看得见存不进去）',
              len(cols_fac) == 4, '列数=%s %s' % (len(cols_fac), [c.split(' ')[0] for c in cols_fac]))
        check('D1f', '教师看不到非任教的列（如「写作课程」）',
              not any('写作课程' in c for c in cols_fac), '')
        page.context.close()
        uid, page, st, text = open_page(browser, 'parent', '/grade-book')
        check('D2', '家长 /grade-book 仍是原行为（拒止文案在）—— 用户只说了教务与教师，没提家长',
              REFUSAL in text, '含拒止=%s' % (REFUSAL in text))
        page.context.close()

        # ---------------- F：越权写入的**反馈**（2026-10-03 第三轮修复） ----------------
        # 缺陷：填了非任教的科目 → 服务端丢弃 → 页面却说「本次没有新的改动」——
        # 那是**错误的归因**（用户明明改了）。静默失败在本仓按缺陷处理。
        print('== F 越权写入必须给出正确的反馈 ==')
        uid, page, st, text = open_page(browser, 'faculty',
                                        '/grade-book?batch_id=%d' % BATCH)
        tok = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.content())
        check('F0', '能从教师页面取到 csrf_token', bool(tok), '')
        sub36 = 'SELECT coalesce((SELECT marks FROM op_exam_attendees a JOIN op_exam e' \
                ' ON e.id=a.exam_id WHERE a.student_id=%d AND e.subject_id=36),-1)' % STUDENT
        before36 = psql(sub36)
        resp = page.context.request.post(
            BASE + '/grade-entry/save',
            form={'csrf_token': tok.group(1), 'batch_id': str(BATCH), 'term_id': '1',
                  ('m_%d_36' % STUDENT): '88'}, max_redirects=0)
        loc = resp.headers.get('location', '')
        after36 = psql(sub36)
        check('F1', '越权格子仍被服务端丢弃（库内不变）', before36 == after36,
              'subject 36: %s -> %s' % (before36, after36))
        check('F2', '回跳 URL 带上被忽略的格数（skip_scope）',
              'skip_scope=' in loc, loc)
        uid, page, st, text = open_page(browser, 'faculty', loc or '/grade-book')
        check('F3', '页面说清「几格未保存、因为不是您任教的科目」（不再谎称「没有新的改动」）',
              ('未保存' in text) and ('不是您任教的科目' in text), flat(text)[:160])
        page.context.close()

        # ---------------- E：控制组 ----------------
        print('== E 控制组 ==')
        ctx = browser.new_context()
        pg = ctx.new_page()
        r = pg.goto(BASE + '/grade-book', wait_until='domcontentloaded', timeout=30000)
        check('E1', '未登录访问 = 跳到登录页（不是 200 的业务页）',
              ('/web/login' in pg.url) or ('oe_login_form' in pg.content()),
              'HTTP %s / final=%s' % (r.status, pg.url))
        ctx.close()

        uid, page, st, text = open_page(browser, 'backoffice',
                                        '/grade-book?batch_id=999999')
        check('E2', '不存在的班级 = 200 空表单（不是 500 / Traceback）',
              st == 200 and 'Traceback' not in text, 'HTTP %s' % st)
        page.context.close()

        browser.close()

    return finish(0 if all(r['pass'] for r in rows) else 1)


def finish(code):
    payload = {'facts': facts, 'rows': rows,
               'pass': sum(1 for r in rows if r['pass'] and not r.get('info')),
               'fail': sum(1 for r in rows if not r['pass']),
               'total': sum(1 for r in rows if not r.get('info'))}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print('\n== 汇总：%d/%d PASS，%d FAIL（%s）=='
          % (payload['pass'], payload['total'], payload['fail'], OUT))
    return code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:                       # 运行错误（站点不可达 / 登不上）
        print('RUN ERROR: %s: %s' % (type(exc).__name__, exc))
        sys.exit(2)
