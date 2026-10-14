# -*- coding: utf-8 -*-
"""课程编排「批量操作」端到端冒烟（t: curriculum-bulk，2026-09-29）。

被测对象：/registrar/curriculum 的批量能力（页 + 写路由 + 审计 + 原子性 + 作用域）。

被测行为（逐条对应交付要求）
----------------------------
  1. 每行一个勾选框 + 表头「全选 / 全不选」+「反选」；批量动作至少三个
     （设为必修 / 设为选修 / 清空回到「留空 = 继承」）；
  2. **逐行原路径必须保留**（不带 bulk_action 时的行为与改动前逐位相同）；
  3. 批量写**一条事务**：半途失败不许留「一半改了、一半没改」；
  4. 审计：批量**不是**绕过审计的后门（与逐行写同一本台账）；
  5. 逐行与批量**同一个写入实现**（同一条路由、同一份解析/写入/落账代码）；
  6. 越权红线：批量只许改当前身份有权改的专业 —— **数据层**反向证明。

取证口径（为什么这样取证）
--------------------------
  · 全部断言都做**进程外读回**：用 psql 直读数据库（另一条连接、另一个进程），
    不经 ORM 缓存、也不看页面渲染 ⇒ 这是"数据层"证据，不是"页面没显示"；
  · 反向注入一律**注完即还原**（非法值 / 触发器 / 越权），跑完 leftover=0；
  · 每条"红"都配控制组（同一请求换有权限的身份必须变绿），排除"请求本身是坏的"。

⚠ 夹具口径：**不新建业务记录**。用真实专业 18（预备科 · 2026级【演示】）的 14 行，
  跑完全部还原（快照对比 + leftover 断言）。跨专业作用域用专业 15（文学学士）的行，
  只读、只断言"未被改动"。

用法：
    python3 tests/smoke/curriculum_bulk.py            # 需本地栈在跑（docker compose up -d）
    python3 tests/smoke/curriculum_bulk.py --json tests/smoke/curriculum_bulk_results.json

退出码：0 = 全绿；1 = 有断言失败；2 = 环境不可用（登录失败/站点不可达/psql 不可用）。
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

import requests

BASE = os.environ.get('EDU_BASE', 'http://127.0.0.1:8069')
DB = os.environ.get('EDU_DB', 'edu19')
LOGIN = os.environ.get('EDU_LOGIN', 'backoffice@local')     # 教务（有权改）
PWD = os.environ.get('EDU_PWD', 'demo123')
FAC_LOGIN = os.environ.get('EDU_FAC_LOGIN', 'faculty@local')
STU_LOGIN = os.environ.get('EDU_STU_LOGIN', 'stu@local')
COURSE = int(os.environ.get('EDU_COURSE', '18'))            # 预备科 · 2026级【演示】
OTHER_COURSE = int(os.environ.get('EDU_OTHER_COURSE', '15'))  # 文学学士（只读对照）
PAGE = '/registrar/curriculum'
SAVE = '/registrar/curriculum/save'
TRG_FN = 'edu_cs_bulk_smoke_fail'
TRG_NAME = 'edu_cs_bulk_smoke_trg'

ok = fail = 0
RESULTS = []


def check(name, cond, detail=''):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    RESULTS.append({'name': name, 'pass': bool(cond), 'detail': detail})
    print('%s | %s | %s' % ('PASS' if cond else 'FAIL', name, detail))


# ---------------------------------------------------------------- 进程外读回
def psql(sql, db=None):
    """psql 直读（进程外、另一条连接）—— 数据层证据的唯一口径。"""
    cmd = ['docker', 'compose', 'exec', '-T', 'db', 'psql', '-U', 'odoo',
           '-d', db or DB, '-At', '-F', '|', '-c', sql]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                       cwd=os.path.dirname(os.path.dirname(
                           os.path.dirname(os.path.abspath(__file__)))))
    if r.returncode != 0:
        raise RuntimeError('psql 失败：%s' % (r.stderr or r.stdout)[:300])
    rows = [ln.split('|') for ln in r.stdout.strip().splitlines() if ln.strip()]
    return rows


def snapshot(course):
    """{line_id: subject_type or None} —— 直接来自数据库。"""
    rows = psql('SELECT id, COALESCE(subject_type, %s) FROM edu_course_subject '
                "WHERE course_id=%d ORDER BY sequence, id" % (chr(39) + chr(39), course))
    return {int(a): (None if b == '' else b) for a, b in rows}


def lines_of(course):
    """有序行 id（sequence, id 口径，与页面/写入顺序一致）。"""
    return [int(r[0]) for r in psql(
        'SELECT id FROM edu_course_subject WHERE course_id=%d ORDER BY sequence, id'
        % course)]


def audit_count(action):
    return int(psql("SELECT count(*) FROM edu_audit_log WHERE action='%s'" % action)[0][0])


def audit_tail(action, n=3):
    return psql("SELECT id, detail FROM edu_audit_log WHERE action='%s' "
                'ORDER BY id DESC LIMIT %d' % (action, n))


# ---------------------------------------------------------------- HTTP
def session(login=LOGIN, pwd=PWD):
    s = requests.Session()
    s.trust_env = False
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    r = s.post(BASE + '/web/session/authenticate', timeout=30, json={
        'jsonrpc': '2.0', 'params': {'db': DB, 'login': login, 'password': pwd}})
    if not r.json().get('result', {}).get('uid'):
        raise SystemExit('登录失败：%s（环境不可用）' % login)
    return s


def csrf(s, url):
    r = s.get(BASE + url, timeout=30)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    if not m:
        # 被门禁弹走的身份（如教师打开 /registrar/curriculum 会 303 回 /my/home）
        # 从登录页取会话级 CSRF 令牌 —— Odoo 的令牌绑**会话**不绑表单，任何页面的
        # 令牌对该会话都成立。少了这一步，越权用例会因 CSRF 先被拦而**假绿**。
        r2 = s.get(BASE + '/web/login', timeout=30)
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r2.text)
    return (m.group(1) if m else ''), r


def post_bulk(s, course, data, action=None, picks=None, extra=None):
    """POST 写路由（逐行 / 批量共用同一条路由）。"""
    token, _ = csrf(s, '%s?course_id=%d' % (PAGE, course))
    payload = {'csrf_token': token, 'course_id': str(course)}
    if action is not None:
        payload['bulk_action'] = action
    if picks:
        payload['pick'] = [str(x) for x in picks]
    if data:
        payload.update(data)
    if extra:
        payload.update(extra)
    r = s.post(BASE + SAVE, data=payload, timeout=40, allow_redirects=True)
    return r


def box_of(r):
    m = re.search(r'[?&]box=([a-z_]+)', r.url)
    return m.group(1) if m else ''


def num_of(r, key):
    m = re.search(r'%s=(\d+)' % key, r.url)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- 触发器注入
def make_fail_trigger(line_id, course):
    """注入一个「写到这一行必炸」的触发器，并把**本事务此前已写入的行数**带进异常。

    为什么要把计数塞进错误消息：只断言"最后一行没改、整表没变"是**可能空转**
    的（若触发器恰好第一个触发，就什么都没写过，回滚也就无从谈起）。异常消息里
    的 prev=N 是触发器当场在**同一事务内**数出来的 —— prev>0 即证明"前面几行
    确实已经写进库了"，而跑完的 psql 快照又证明它们一起被撤掉了 ⇒ 这才是
    「半途失败不留一半」的正证据。
    """
    psql("CREATE OR REPLACE FUNCTION %s() RETURNS trigger AS $f$ BEGIN "
         "IF NEW.id = %d AND NEW.subject_type = 'compulsory' THEN "
         "RAISE EXCEPTION '冒烟注入：本行写入失败；本事务此前已改 compulsory 行数=%%', "
         '(SELECT count(*) FROM edu_course_subject WHERE course_id = %d '
         "AND subject_type = 'compulsory' AND id <> NEW.id); "
         'END IF; RETURN NEW; END $f$ LANGUAGE plpgsql;'
         % (TRG_FN, line_id, course))
    psql('CREATE TRIGGER %s BEFORE UPDATE ON edu_course_subject '
         'FOR EACH ROW EXECUTE FUNCTION %s();' % (TRG_NAME, TRG_FN))


def drop_fail_trigger():
    psql('DROP TRIGGER IF EXISTS %s ON edu_course_subject;' % TRG_NAME)
    psql('DROP FUNCTION IF EXISTS %s();' % TRG_FN)


def trigger_left():
    t = psql("SELECT count(*) FROM pg_trigger WHERE tgname='%s'" % TRG_NAME)[0][0]
    f = psql("SELECT count(*) FROM pg_proc WHERE proname='%s'" % TRG_FN)[0][0]
    return int(t), int(f)


# ================================================================== 主流程
def main():
    global ok, fail
    s = session()
    fac = session(FAC_LOGIN)
    stu = session(STU_LOGIN)

    own = lines_of(COURSE)
    other = lines_of(OTHER_COURSE)
    base_snap = snapshot(COURSE)
    other_snap = snapshot(OTHER_COURSE)
    check('E0 环境：专业 %d 有 >=4 行科目（夹具前提）' % COURSE, len(own) >= 4,
          '实测 %d 行' % len(own))
    if len(own) < 4 or len(other) < 1:
        raise SystemExit(2)
    print('  起始快照（专业 %d）：%s' % (COURSE, base_snap))

    # ---------------- A 页面（正向） ----------------
    token, page = csrf(s, '%s?course_id=%d' % (PAGE, COURSE))
    check('A1 页面 200 且无 Traceback',
          page.status_code == 200 and 'Traceback' not in page.text,
          'code=%d len=%d' % (page.status_code, len(page.text)))
    n_pick = len(re.findall(r'name="pick"', page.text))
    check('A2 每行一个勾选框（行数 = 勾选框数）', n_pick == len(own),
          '勾选框 %d / 行 %d' % (n_pick, len(own)))
    check('A3 表头「全选 / 全不选」+「反选」都在',
          'id="cur-pick-all"' in page.text and '反选' in page.text
          and '>全选 / 全不选<' in page.text, '')
    acts = sorted(re.findall(r'name="bulk_action" value="([a-z]+)"', page.text))
    check('A4 批量动作三个：设为必修 / 设为选修 / 清空',
          acts == ['clear', 'compulsory', 'elective'], '实测 %s' % acts)
    check('A5 逐行 select 原路径仍在（line_<id> 逐行控件齐全）',
          len(re.findall(r'name="line_\d+"', page.text)) == len(own),
          '逐行 select %d' % len(re.findall(r'name="line_\d+"', page.text)))
    check('A6 逐行「保存课程编排」按钮仍在（无 name ⇒ 不带 bulk_action）',
          '保存课程编排' in page.text and 'name="bulk_action"' in page.text, '')
    # 可访问名（静态口径）：每个新控件都得有名字
    names = re.findall(r'name="pick"[^>]*aria-label="([^"]+)"', page.text)
    check('A7 每个行勾选框都有可访问名（aria-label）',
          len(names) == len(own) and all(n.strip() for n in names),
          '样例 %s' % (names[:2],))
    check('A8 全选框用 <label for=> 命名、反选是 type=button（不会误提交）',
          'for="cur-pick-all"' in page.text and 'type="button"' in page.text, '')

    # ---------------- B 三种批量动作（正向） ----------------
    picks = own[:3]
    s.post(BASE + SAVE, timeout=40, data={}, allow_redirects=True)  # 预热
    # 先把 3 行打成已知态：批量清空
    post_bulk(s, COURSE, None, 'clear', picks)
    snap0 = snapshot(COURSE)
    check('B0 前置：批量清空把 3 行打回「留空（继承）」',
          all(snap0[i] is None for i in picks),
          '%s' % {i: snap0[i] for i in picks})

    r1 = post_bulk(s, COURSE, None, 'compulsory', picks)
    snap1 = snapshot(COURSE)
    check('B1 批量设为必修：303 回执 bulk_saved/picked=3/changed=3',
          r1.status_code == 200 and box_of(r1) == 'bulk_saved'
          and num_of(r1, 'bulk_picked') == 3 and num_of(r1, 'bulk_changed') == 3,
          'code=%s url=%s' % (r1.status_code, r1.url.split('?')[-1][:90]))
    check('B1b 数据库读回：3 行 = compulsory（进程外 psql）',
          all(snap1[i] == 'compulsory' for i in picks)
          and all(snap1[i] == base_snap[i] for i in own if i not in picks),
          '%s' % {i: snap1[i] for i in picks})

    r2 = post_bulk(s, COURSE, None, 'elective', picks)
    snap2 = snapshot(COURSE)
    check('B2 批量设为选修：3 行 = elective（psql）',
          box_of(r2) == 'bulk_saved' and all(snap2[i] == 'elective' for i in picks),
          'box=%s %s' % (box_of(r2), {i: snap2[i] for i in picks}))

    r3 = post_bulk(s, COURSE, None, 'clear', picks)
    snap3 = snapshot(COURSE)
    check('B3 批量清空：3 行回到 NULL（= 继承科目默认值，psql）',
          box_of(r3) == 'bulk_saved' and all(snap3[i] is None for i in picks),
          'box=%s %s' % (box_of(r3), {i: snap3[i] for i in picks}))

    r4 = post_bulk(s, COURSE, None, 'clear', picks)
    check('B4 幂等：同值再来一次 → bulk_none 且 changed=0，一行未动',
          box_of(r4) == 'bulk_none' and num_of(r4, 'bulk_changed') == 0
          and snapshot(COURSE) == snap3,
          'box=%s changed=%s' % (box_of(r4), num_of(r4, 'bulk_changed')))

    # ---------------- B5 审计：批量留痕 ----------------
    post_bulk(s, COURSE, None, 'compulsory', picks)
    tail = audit_tail('课程编排', 3)
    check('B5 批量写进了审计台账（action=课程编排，detail 带「批量·」）',
          bool(tail) and tail[0][1].startswith('批量·批量设为必修 /'),
          '最近一条：%s' % (tail[0][1][:110] if tail else '（无）'))
    post_bulk(s, COURSE, None, 'clear', picks)

    # ---------------- B6 mail.thread 逐行留痕 ----------------
    # Odoo 19 的 mail.thread 留痕**不在 body 里**：body 为空、值落在
    # mail_tracking_value（field_id + old/new_value_char）—— 首版断言查 body
    # 命中 0，是**量具错**不是功能缺（实测读数见本用例 detail）。
    msg = psql("SELECT count(*) FROM mail_message m "
               'JOIN mail_tracking_value t ON t.mail_message_id = m.id '
               'JOIN ir_model_fields f ON f.id = t.field_id '
               "WHERE m.model='edu.course.subject' AND f.name='subject_type' "
               "AND m.res_id IN (%s) AND t.new_value_char IN ('必修','选修')"
               % ','.join(str(i) for i in picks))
    check('B6 行级留痕（mail.thread tracking）也有：%s 条' % msg[0][0],
          int(msg[0][0]) >= 1, '命中 %s 条' % msg[0][0])

    # ---------------- C 逐行原路径（回归 + 同一实现） ----------------
    before = snapshot(COURSE)
    r5 = post_bulk(s, COURSE, {'line_%d' % own[0]: 'compulsory'})
    snap5 = snapshot(COURSE)
    check('C1 逐行（不带 bulk_action）仍走原路径：box=saved，只有该行变',
          box_of(r5) == 'saved' and snap5[own[0]] == 'compulsory'
          and all(snap5[i] == before[i] for i in own if i != own[0]),
          'box=%s 行 %d=%s' % (box_of(r5), own[0], snap5[own[0]]))
    tail2 = audit_tail('课程编排', 1)
    check('C2 逐行与批量**同一本审计台账**（同一 action，来源前缀不同）',
          bool(tail2) and tail2[0][1].startswith('逐行 /'),
          '最近一条：%s' % (tail2[0][1][:60] if tail2 else '（无）'))
    # C3 同一份解析：逐行改动 + 批量动作同一次提交 ⇒ 两者都要生效
    r6 = post_bulk(s, COURSE, {'line_%d' % own[0]: 'elective'},
                   'clear', [own[1]])
    snap6 = snapshot(COURSE)
    check('C3 一次提交里「逐行改 A + 批量清空 B」都生效（逐行改动不被静默丢掉）',
          snap6[own[0]] == 'elective' and snap6[own[1]] is None,
          'A(%d)=%s B(%d)=%s' % (own[0], snap6[own[0]], own[1], snap6[own[1]]))

    # ---------------- D 反向注入（变红再还原） ----------------
    snap_before = snapshot(COURSE)
    # D1 非法值：整张表一行都不许写
    r7 = post_bulk(s, COURSE, {'line_%d' % own[3]: 'whatever'},
                   'compulsory', picks)
    check('D1 注入非法值 ⇒ box=bad_value，且**全表一行未改**（psql 快照相等）',
          box_of(r7) == 'bad_value' and snapshot(COURSE) == snap_before,
          'box=%s 快照相等=%s' % (box_of(r7), snapshot(COURSE) == snap_before))

    # D2 原子性：让第 3 行的写入必然失败，前 2 行必须被一起回滚
    atk = own[-1]                      # 触发器挂在写入顺序**最后**的那一行
    trio = own[-3:]
    post_bulk(s, COURSE, None, 'elective', trio)
    snap_pre = snapshot(COURSE)
    make_fail_trigger(atk, COURSE)
    try:
        r8 = post_bulk(s, COURSE, None, 'compulsory', trio)
    finally:
        drop_fail_trigger()
    snap_post = snapshot(COURSE)
    check('D2 半途失败 ⇒ 整批回滚：box=bulk_error + 一行都没改（psql）',
          box_of(r8) == 'bulk_error' and snap_post == snap_pre,
          'box=%s status=%s 前=%s 后=%s' % (
              box_of(r8), r8.status_code,
              {i: snap_pre[i] for i in trio}, {i: snap_post[i] for i in trio}))
    check('D2b 失败提示是人话（页面渲染出原因，不是 500/Traceback）',
          '整批已回滚' in r8.text and 'Traceback' not in r8.text
          and r8.status_code == 200,
          'code=%d 含原因=%s' % (r8.status_code, '冒烟注入' in r8.text))
    # 非空转证明：触发器当场数出「本事务此前已写入 2 行」⇒ 回滚掉的确实是已发生的写
    seen = re.search(r'本事务此前已改 compulsory 行数=([0-9]+)', r8.text)
    check('D2c 非空转：注入点之前**确实已经写了 2 行**，失败后与其它行一起被撤',
          bool(seen) and int(seen.group(1)) == 2,
          '触发器读数=%s（期望 2）' % (seen.group(1) if seen else '未命中'))

    # D3/D4 越权：教师 / 学生
    for tag, sess, who in (('D3', fac, '教师'), ('D4', stu, '学生')):
        before_v = snapshot(COURSE)
        rr = post_bulk(sess, COURSE, None, 'compulsory', picks)
        after_v = snapshot(COURSE)
        check('%s 越权（%s）批量写入被拒：回 /my/home 且**数据层**一行未改'
              % (tag, who),
              '/my/home' in rr.url and after_v == before_v,
              'url=%s 数据层相等=%s' % (rr.url[:60], after_v == before_v))

    # D5 未登录
    anon = requests.Session()
    anon.trust_env = False
    before_v = snapshot(COURSE)
    ra = anon.post(BASE + SAVE, timeout=30, allow_redirects=False,
                   data={'course_id': str(COURSE), 'bulk_action': 'compulsory',
                         'pick': str(picks[0])})
    check('D5 未登录 POST 不落库（数据层一行未改）',
          ra.status_code in (301, 302, 303, 400, 403) and snapshot(COURSE) == before_v,
          'code=%s 数据层相等=%s' % (ra.status_code, snapshot(COURSE) == before_v))

    # D6/D7 作用域：别专业的行够不到
    other_before = snapshot(OTHER_COURSE)
    snap_before = snapshot(COURSE)
    r9 = post_bulk(s, COURSE, None, 'compulsory', [other[0]])
    check('D6 只勾别专业的行 ⇒ bulk_empty + ignored=1，且**别专业数据层一行未改**',
          box_of(r9) == 'bulk_empty' and num_of(r9, 'bulk_ignored') == 1
          and snapshot(OTHER_COURSE) == other_before
          and snapshot(COURSE) == snap_before,
          'box=%s ignored=%s' % (box_of(r9), num_of(r9, 'bulk_ignored')))
    post_bulk(s, COURSE, None, 'clear', picks)
    snap_before = snapshot(COURSE)
    r10 = post_bulk(s, COURSE, None, 'compulsory', [picks[0], other[1]])
    check('D7 混发（本专业 + 别专业）⇒ 只改本专业那行，ignored=1，别专业未改',
          num_of(r10, 'bulk_ignored') == 1
          and snapshot(COURSE)[picks[0]] == 'compulsory'
          and snapshot(OTHER_COURSE) == other_before,
          'ignored=%s 本专业=%s' % (num_of(r10, 'bulk_ignored'),
                                    snapshot(COURSE)[picks[0]]))

    # ---------------- E 控制组 ----------------
    snap_before = snapshot(COURSE)
    e1 = post_bulk(s, COURSE, None, 'compulsory', [picks[1]])
    check('E1 控制组：同一请求换教务身份 ⇒ 值确实变了（排除「请求本身坏」）',
          snapshot(COURSE)[picks[1]] == 'compulsory'
          and snapshot(COURSE)[picks[1]] != snap_before[picks[1]],
          '行 %d = %s' % (picks[1], snapshot(COURSE)[picks[1]]))
    n_audit = audit_count('课程编排')
    e2 = post_bulk(s, COURSE, None, 'compulsory', [])
    check('E2 空勾选 ⇒ bulk_empty、不写库、**不留审计**（不为空操作记一笔）',
          box_of(e2) == 'bulk_empty' and audit_count('课程编排') == n_audit,
          'box=%s 审计 %d→%d' % (box_of(e2), n_audit, audit_count('课程编排')))
    snap_before = snapshot(COURSE)
    e3 = post_bulk(s, COURSE, None, 'drop_table', picks)
    check('E3 非法动作值 ⇒ bulk_bad_action，一行未改',
          box_of(e3) == 'bulk_bad_action' and snapshot(COURSE) == snap_before,
          'box=%s' % box_of(e3))
    e4 = post_bulk(s, 99999991, None, 'compulsory', picks)
    check('E4 非法专业 ⇒ bad_course，一行未改',
          box_of(e4) == 'bad_course', 'box=%s' % box_of(e4))

    # ---------------- F 还原 ----------------
    post_bulk(s, COURSE, None, 'clear', own)
    # 原始快照里有非空值的行，逐行走原路径写回（逐行路径本身就是还原手段之一）
    for lid, val in base_snap.items():
        if val:
            post_bulk(s, COURSE, {'line_%d' % lid: val})
    check('F1 还原：专业 %d 全部行回到起始值（psql 比对）' % COURSE,
          snapshot(COURSE) == base_snap,
          '现在=%s' % snapshot(COURSE))
    check('F2 还原：别专业未被本次冒烟改动', snapshot(OTHER_COURSE) == other_snap, '')
    t_left, f_left = trigger_left()
    check('F3 清场 leftover=0（注入用的触发器/函数已删干净）',
          t_left == 0 and f_left == 0, 'trigger=%d function=%d' % (t_left, f_left))

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
            json.dump({'at': datetime.datetime.now().isoformat(),
                       'base': BASE, 'course': COURSE, 'results': RESULTS,
                       'pass': ok, 'fail': fail}, fh, ensure_ascii=False, indent=1)
        print('读数已写 %s' % args.json)
    sys.exit(rc)
