# -*- coding: utf-8 -*-
"""「课程编排的必修/选修」到底管不管用 + 选完课表里有没有课 —— 端到端实测（2026-09-29）。

回答用户两问（逐条落在断言的 name 上）：
  Q1 学生那边能不能选课？课程编排勾的「必修 / 选修」到底改了学生页面的什么？
     → A 段：改一行 subject_type，**同一学生账号**再取一次报课页，逐位对读数。
  Q2 选好之后课表里有没有每日课程？
     → B 段：学生课表 /student/timetable 与校历 /my/calendar 的**渲染读数**
       与数据库 op.session 对齐；C 段（另一个文件）量「选课动作是否产生课节」。
  Q3 复核「排课挂批、学生按档案班过滤」这条可疑点今天是否仍成立
     → B 段：全库班级 × {总课节, 本周课节, 学生数} + 合班批单独列。

证据三类（每个结论都配齐）：
  · 正向：改配置 → 学生页面读数确实变（并回到库里的值）；
  · 反向注入：改成相反值 → 读数按预期翻转；再清空 → 退回「继承」档；
  · 控制组：① 不改任何东西连取两次，读数逐位相同（排除抖动/缓存）；
            ② 同一账号同一页面换一周 → 有课（证明"空周"不是页面坏了）；
            ③ 有权限身份改得动（见 curriculum_bulk.py 的 E1）。

⛔ 只读 + 可还原：本文件对课程的写入**只有** course 18 的行值（开测记录快照、
   结束逐行还原 + psql 校验）；不新建/删除任何业务记录。
用法：python3 tests/smoke/enroll_timetable_chain.py [--json 结果文件]
退出码：0 全绿 / 1 有断言失败 / 2 环境不可用。
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

import requests

BASE = os.environ.get('EDU_BASE', 'http://127.0.0.1:8069')
DB = os.environ.get('EDU_DB', 'edu19')
BO = os.environ.get('EDU_LOGIN', 'backoffice@local')
STU = os.environ.get('EDU_STU_LOGIN', 'stu@local')
PWD = 'demo123'
COURSE = int(os.environ.get('EDU_COURSE', '18'))
BATCH = int(os.environ.get('EDU_BATCH', '8'))
TZ = ZoneInfo('Asia/Shanghai')

ok = fail = 0
RESULTS = []


def check(name, cond, detail=''):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    RESULTS.append({'name': name, 'pass': bool(cond), 'detail': detail})
    print('%s | %s | %s' % ('PASS' if cond else 'FAIL', name, detail))


def note(text):
    print('   · %s' % text)


def psql(sql):
    r = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql', '-U',
                        'odoo', '-d', DB, '-At', '-F', '|', '-c', sql],
                       capture_output=True, text=True, timeout=60,
                       cwd=os.path.dirname(os.path.dirname(
                           os.path.dirname(os.path.abspath(__file__)))))
    if r.returncode != 0:
        raise RuntimeError('psql：%s' % (r.stderr or r.stdout)[:300])
    return [ln.split('|') for ln in r.stdout.strip().splitlines() if ln.strip()]


def login(name):
    s = requests.Session()
    s.trust_env = False
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    r = s.post(BASE + '/web/session/authenticate', timeout=30, json={
        'jsonrpc': '2.0', 'params': {'db': DB, 'login': name, 'password': PWD}})
    if not r.json().get('result', {}).get('uid'):
        raise SystemExit('登录失败：%s' % name)
    return s


def plain(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


def csrf(sess, url):
    t = sess.get(BASE + url, timeout=30).text
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', t)
    return m.group(1) if m else ''


def curriculum_write(sess, action=None, picks=None, rows=None):
    tok = csrf(sess, '/registrar/curriculum?course_id=%d' % COURSE)
    data = {'csrf_token': tok, 'course_id': str(COURSE)}
    if action:
        data['bulk_action'] = action
    if picks:
        data['pick'] = [str(x) for x in picks]
    if rows:
        data.update(rows)
    return sess.post(BASE + '/registrar/curriculum/save', timeout=40,
                     data=data, allow_redirects=True)


def enroll_page(sess):
    """学生报课页读成结构化读数（页面渲染，不查库）。"""
    t = sess.get(BASE + '/subject/enroll?course_id=%d&batch_id=%d'
                 % (COURSE, BATCH), timeout=30).text
    p = plain(t)
    m = re.search(r'必修 (\d+) 选修 (\d+)', p)
    return {
        'compulsory_n': int(m.group(1)) if m else -1,
        'elective_n': int(m.group(2)) if m else -1,
        'selectable': [int(x) for x in re.findall(
            r'name="elective_subject_ids"\s*value="(\d+)"', t)],
        'locked_cards': t.count('title="必修"'),
        'lock_hint': '必修科目随专业自动生效，无需也不能取消' in p,
        'no_compulsory_hint': '该专业无必修科目，请从下方勾选至少 1 门选修科目' in p,
        'html_len': len(t),
    }


def curriculum_stats(sess):
    t = sess.get(BASE + '/registrar/curriculum?course_id=%d' % COURSE,
                 timeout=30).text
    p = plain(t)
    out = {}
    for key, pat in (('eff_c', r'实际生效：必修 (\d+)'),
                     ('eff_e', r'实际生效：选修 (\d+)'),
                     ('exp_c', r'显式必修 (\d+)'),
                     ('exp_e', r'显式选修 (\d+)')):
        m = re.search(pat, p)
        out[key] = int(m.group(1)) if m else -1
    return out


def line_state(course):
    return {int(a): (None if b == '' else b) for a, b in psql(
        'SELECT id, COALESCE(subject_type, %s) FROM edu_course_subject '
        'WHERE course_id=%d ORDER BY sequence, id'
        % ("''", course))}


def monday_of(day):
    return day - datetime.timedelta(days=day.weekday())


def week_utc(day_local):
    lo = datetime.datetime.combine(day_local, datetime.time.min)
    hi = lo + datetime.timedelta(days=7)
    return (lo - datetime.timedelta(hours=8), hi - datetime.timedelta(hours=8))


def sessions_in(batch, lo, hi):
    return int(psql("SELECT count(*) FROM op_session WHERE batch_id=%d "
                    "AND state <> 'cancel' AND start_datetime < '%s' "
                    "AND end_datetime >= '%s'"
                    % (batch, hi.strftime('%Y-%m-%d %H:%M:%S'),
                       lo.strftime('%Y-%m-%d %H:%M:%S')))[0][0])


# ==================================================================
def main():
    global ok, fail
    bo, stu = login(BO), login(STU)

    own = [int(r[0]) for r in psql(
        'SELECT id FROM edu_course_subject WHERE course_id=%d '
        'ORDER BY sequence, id' % COURSE)]
    snap = line_state(COURSE)
    subj_of = {int(a): (b, c) for a, b, c in psql(
        'SELECT l.id, s.name, COALESCE(s.subject_type, %s) FROM '
        'edu_course_subject l JOIN op_subject s ON s.id = l.subject_id '
        "WHERE l.course_id = %d ORDER BY l.sequence, l.id" % ("''", COURSE))}
    # ⚠ 报课页复选框 name="elective_subject_ids" 的 value 是 **op.subject.id**，
    #   不是 edu.course.subject 行 id —— 两者必须分开，否则断言会拿错集合
    #   （首版就是这么错的，A1/A7 假红）。
    line2subj = {int(a): int(b) for a, b in psql(
        'SELECT id, subject_id FROM edu_course_subject WHERE course_id=%d '
        'ORDER BY sequence, id' % COURSE)}
    target = own[0]
    tname, tglobal = subj_of[target]
    tsubj = line2subj[target]
    note('学生账号=%s，专业 %d / 班 %d；目标行 id=%d（科目「%s」，科目自身默认=%s）'
         % (STU, COURSE, BATCH, target, tname, tglobal))
    note('起始：14 行全部「留空（继承）」= %s'
         % all(v is None for v in snap.values()))

    # ---------------- A 段：必修/选修 → 学生报课页 ----------------
    a0 = enroll_page(stu)
    check('A1 基线：学生报课页 必修 %d / 选修 %d，%d 门全可勾（科目池=专业科目清单）'
          % (a0['compulsory_n'], a0['elective_n'], len(a0['selectable'])),
          a0['compulsory_n'] == 0 and a0['elective_n'] == len(own)
          and sorted(a0['selectable']) == sorted(line2subj.values())
          and a0['no_compulsory_hint'],
          'compulsory_n=%d elective_n=%d selectable=%d'
          % (a0['compulsory_n'], a0['elective_n'], len(a0['selectable'])))

    a0b = enroll_page(stu)
    check('A2 控制组：不改任何东西连取两次，报名页读数逐位相同',
          {k: a0[k] for k in ('compulsory_n', 'elective_n', 'selectable')}
          == {k: a0b[k] for k in ('compulsory_n', 'elective_n', 'selectable')},
          '两次都是 必修 %d / 选修 %d' % (a0b['compulsory_n'], a0b['elective_n']))

    try:
        r = curriculum_write(bo, 'compulsory', [target])
        check('A3 教务批量把「%s」设为必修：写成功（box=bulk_saved）' % tname,
              'box=bulk_saved' in r.url, 'url=%s' % r.url.split('?')[-1][:70])
        a1 = enroll_page(stu)
        check('A4 同一学生再取报课页：必修 %d → %d，选修 %d → %d（学生侧确实跟着变）'
              % (a0['compulsory_n'], a1['compulsory_n'],
                 a0['elective_n'], a1['elective_n']),
              a1['compulsory_n'] == 1 and a1['elective_n'] == len(own) - 1,
              'now 必修 %d / 选修 %d' % (a1['compulsory_n'], a1['elective_n']))
        check('A5 该科目从「可勾选」集合里消失，并渲染成必修卡（锁定、不可取消）',
              tsubj not in a1['selectable'] and a1['locked_cards'] == 1
              and a1['lock_hint'],
              '可勾 %d 门（原 %d）；锁定卡 %d；提示句=%s'
              % (len(a1['selectable']), len(a0['selectable']),
                 a1['locked_cards'], a1['lock_hint']))
        cur = curriculum_stats(bo)
        check('A6 编排页「实际生效」与报课页同源：实际生效 必修 %d / 选修 %d'
              % (cur['eff_c'], cur['eff_e']),
              cur['eff_c'] == a1['compulsory_n']
              and cur['eff_e'] == a1['elective_n'],
              '编排页 %s / 报课页 %d,%d'
              % (cur, a1['compulsory_n'], a1['elective_n']))

        r2 = curriculum_write(bo, 'elective', [target])
        a2 = enroll_page(stu)
        check('A7 反向注入：同一行改成「选修」⇒ 报课页翻回 必修 %d / 选修 %d，'
              '该科目重新可勾' % (a2['compulsory_n'], a2['elective_n']),
              a2['compulsory_n'] == 0 and a2['elective_n'] == len(own)
              and tsubj in a2['selectable'],
              'box=%s' % ('bulk_saved' if 'bulk_saved' in r2.url else r2.url[-30:]))

        r3 = curriculum_write(bo, 'clear', [target])
        a3 = enroll_page(stu)
        check('A8 清空回「继承」档：读数与基线一致（留空 ≠ 消失，走科目自身的默认值）',
              a3['compulsory_n'] == a0['compulsory_n']
              and sorted(a3['selectable']) == sorted(a0['selectable']),
              '必修 %d 选修 %d，可勾 %d'
              % (a3['compulsory_n'], a3['elective_n'], len(a3['selectable'])))
        check('A9 数据层读回：该行 subject_type = NULL（psql，不是看页面）',
              line_state(COURSE)[target] is None,
              'line %d = %s' % (target, line_state(COURSE)[target]))
    finally:
        curriculum_write(bo, 'clear', own)
        for lid, val in snap.items():
            if val:
                curriculum_write(bo, rows={'line_%d' % lid: val})
    check('A10 还原：14 行全部回到起始值（psql 比对）',
          line_state(COURSE) == snap, 'now=%s' % line_state(COURSE))

    # ---------------- B 段：课表链 ----------------
    rows = psql(
        "SELECT b.id, b.name, COALESCE(b.code,''), "
        "(SELECT count(*) FROM op_session s WHERE s.batch_id = b.id), "
        "(SELECT count(*) FROM op_student_course sc WHERE sc.batch_id = b.id) "
        'FROM op_batch b ORDER BY b.id')
    now_local = datetime.datetime.now(TZ)
    lo, hi = week_utc(monday_of(now_local.date()))
    table = []
    for bid, bname, bcode, total, nstu in rows:
        wk = sessions_in(int(bid), lo, hi)
        table.append({'id': int(bid), 'name': bname, 'code': bcode,
                      'sessions': int(total), 'week': wk, 'students': int(nstu)})
    zero_week = [r['name'] for r in table if r['week'] == 0]
    merged = [r for r in table if '合班' in r['name'] or r['code'] == 'B1234']
    note('本周窗口（Asia/Shanghai）：%s ~ %s'
         % (monday_of(now_local.date()), monday_of(now_local.date())
            + datetime.timedelta(days=6)))
    note('全库 %d 个班：总课节 %d，本周零课节 %d 个 —— %s'
         % (len(table), sum(r['sessions'] for r in table), len(zero_week),
            zero_week))
    note('合班批 %d 个：课节 %d，学生数合计 %d'
         % (len(merged), sum(r['sessions'] for r in merged),
            sum(r['students'] for r in merged)))
    check('B1 复核可疑点①：全库有课的班在本周是少数（%d/%d 个班本周零课节 —— '
          '与 2026-09-29 之前的读数同量级）'
          % (len(zero_week), len(table)),
          len(table) == 17 and len(zero_week) >= 8,
          'zero=%d/%d' % (len(zero_week), len(table)))
    check('B2 复核可疑点②：合班批的课节 %d 节、挂在其上的学生 %d 人 '
          '⇒ 合班批的课**没有任何学生**能看见'
          % (sum(r['sessions'] for r in merged),
             sum(r['students'] for r in merged)),
          sum(r['sessions'] for r in merged) > 0
          and sum(r['students'] for r in merged) == 0,
          '合班批 %s' % [(r['name'], r['sessions'], r['students'])
                         for r in merged])

    # 身份反查口径 = edu_schedule/models/identity.py::student_of_user 的**双向并集**
    # （① op.student.user_id == uid；② partner.user_ids ∋ uid）。本库王小明就是
    # ①的形态：op_student.user_id=8，但它的 partner(35) 与账号 partner(38) 不是同一条。
    sc = psql(
        "SELECT sc.id, sc.course_id, sc.batch_id, sc.state FROM op_student_course sc "
        "WHERE sc.state = 'running' AND sc.student_id IN ("
        'SELECT st.id FROM op_student st WHERE st.user_id = '
        "(SELECT id FROM res_users WHERE login = '%s') "
        'UNION SELECT st.id FROM op_student st '
        'JOIN res_users u ON u.partner_id = st.partner_id '
        "WHERE u.id = (SELECT id FROM res_users WHERE login = '%s'))"
        % (STU, STU))
    check('B3 学生档案：running 档案 %d 条，档案班 = %s'
          % (len(sc), sc[0][2] if sc else None),
          bool(sc) and sc[0][2] == str(BATCH),
          'sc=%s' % sc)
    b8 = [r for r in table if r['id'] == int(sc[0][2])][0]
    note('学生档案班 %d「%s」总课节 %d，本周 %d 节'
         % (b8['id'], b8['name'], b8['sessions'], b8['week']))
    last = psql('SELECT max(start_datetime)::date FROM op_session WHERE batch_id=%d'
                % b8['id'])[0][0]
    note('该班最后一节课：%s' % last)

    # 控制组②：同一账号同一页换一周就有课
    w0 = stu.get(BASE + '/student/timetable?w=0', timeout=30).text
    w2 = stu.get(BASE + '/student/timetable?w=-2', timeout=30).text
    n0 = len(re.findall(r'<div class="fw-bold">', w0))
    n2 = len(re.findall(r'<div class="fw-bold">', w2))
    lo2 = monday_of(now_local.date()) - datetime.timedelta(weeks=2)
    plo, phi = week_utc(lo2)
    db2 = sessions_in(b8['id'], plo, phi)
    check('B4 学生课表 w=0（本周）：渲染 %d 节课（库里 %d 节）—— 与库一致'
          % (n0, b8['week']),
          n0 == b8['week'], 'psql=%d 页面=%d' % (b8['week'], n0))
    check('B5 控制组②：同一账号同一页 w=-2（%s 那周）渲染 %d 节，库里 %d 节 '
          '⇒ 空周不是页面坏了，是那个班那周真没课' % (lo2, n2, db2),
          n2 == db2 and n2 > 0, 'psql=%d 页面=%d' % (db2, n2))

    # ⚠ 月视图**每天只画前 4 个片**，其余折成「+N 项」—— 只数 oe-cal-chip 会漏
    #   （首版就是这么错的：9 月数出 34，库里 52）。判据 = 片数 + 各日「+N 项」的和。
    def month_chips(sess, y, m):
        t = sess.get(BASE + '/my/calendar?y=%d&m=%d' % (y, m), timeout=30).text
        chips = re.findall(r'class="oe-cal-chip"[^>]*title="([^"]*)"', t)
        over = sum(int(x) for x in re.findall(r'\+([0-9]+) 项', t))
        return len(chips) + over, chips, over

    def month_db(y, m):
        lo = datetime.datetime(y, m, 1, 0, 0) - datetime.timedelta(hours=8)
        hi = (datetime.datetime(y, m, 1, 0, 0) + datetime.timedelta(days=32)
              ).replace(day=1) - datetime.timedelta(hours=8)
        return int(psql("SELECT count(*) FROM op_session WHERE batch_id=%d "
                        "AND state <> 'cancel' AND start_datetime >= '%s' "
                        "AND start_datetime < '%s'"
                        % (b8['id'], lo.strftime('%Y-%m-%d %H:%M:%S'),
                           hi.strftime('%Y-%m-%d %H:%M:%S')))[0][0])

    c9, chips9, over9 = month_chips(stu, 2026, 9)
    c10, _c, _o = month_chips(stu, 2026, 10)
    db9, db10 = month_db(2026, 9), month_db(2026, 10)
    check('B6 校历 /my/calendar 每日课程：2026-09 共 %d 节课片（含折叠 %d），库里 %d 节；'
          '2026-10 共 %d，库里 %d' % (c9, over9, db9, c10, db10),
          c9 == db9 and db9 > 0 and c10 == db10 == 0,
          '9月 页面 %d / 库 %d；10月 页面 %d / 库 %d；样例片=%s'
          % (c9, db9, c10, db10, chips9[:2]))

    print('\n合计：PASS %d / FAIL %d' % (ok, fail))
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default='')
    args = ap.parse_args()
    try:
        rc = main()
    except SystemExit:
        raise
    except Exception as exc:            # noqa: BLE001
        print('运行错误（环境不可用）：%s' % exc)
        sys.exit(2)
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump({'at': datetime.datetime.now().isoformat(), 'results': RESULTS,
                       'pass': ok, 'fail': fail}, fh, ensure_ascii=False, indent=1)
    sys.exit(rc)
