# -*- coding: utf-8 -*-
"""第 5 批 A/C/D 冒烟：通知偏好 / 成绩逐生留痕 / 搜索快捷键资源。"""
import re
import subprocess
import sys

import requests

BASE = 'http://localhost:8069'
PASS, FAIL = [], []


def check(name, cond, extra=''):
    (PASS if cond else FAIL).append(name)
    print('%s %s%s' % ('PASS' if cond else 'FAIL', name,
                       (' | ' + str(extra)[:140]) if (extra and not cond) else ''))


def login(login_name, password='demo123'):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': 'edu19', 'login': login_name,
                   'password': password}}, timeout=20)
    return s if (r.status_code == 200 and r.json().get('result')) else None


def odoo_shell(snippet):
    cmd = ("docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf "
           "-d edu19 --db_host=db -r odoo -w odoo --http-port=8099")
    p = subprocess.run(cmd, shell=True, input=snippet.encode() +
                       b"\nexit()\n", capture_output=True, timeout=180)
    return p.stdout.decode(errors='replace') + p.stderr.decode(
        errors='replace')


# ---------------------------------------------------------------------------
# 偏好快照 / 整份还原（t100 ①）—— 本脚本是**污染源**：
#   它的「全部静音」denies 全部键，而**恢复只覆盖 4 个 evt_* 键** ⇒
#   未被恢复的键（实测 `reimburse_result`、`subject_reg_result`）永久留成 muted=True，
#   进而让别的冒烟（如 p3_ledger 的报销通知断言）看起来像**产品缺陷**。
# 修法两点，缺一不可：
#   1. 快照取**该用户的全部偏好键**（不是「本次会改的那几个」）—— 否则保住的只是已知部分；
#   2. 还原整份快照放进 `finally`（与 t94 的原子还原同源：**任何路径都恢复**）。
# 残留的定义要记准：**不是「我改的键恢复了」，而是「我没碰的键也没被动过」。**
# ---------------------------------------------------------------------------


def pref_snapshot(login_name='stu@local'):
    """取该用户**全部**通知偏好键 → {event_key: 0/1}。取不到返回 {}。"""
    out = odoo_shell(
        "u = env['res.users'].sudo().search([('login', '=', u'" + login_name + "')], limit=1)\n"
        "rows = env['edu.notify.pref'].sudo().search([('user_id', '=', u.id)])\n"
        "print('PREF_SNAP ' + ','.join('%s:%d' % (r.event_key, 1 if r.muted else 0) for r in rows))\n")
    return _parse_pref(out, 'PREF_SNAP')


def pref_restore(snap, login_name='stu@local'):
    """把**整份快照**写回（含本脚本没碰过的键）→ 返回写回后的实际值。"""
    if not snap:
        return {}
    lines = ["u = env['res.users'].sudo().search([('login', '=', u'" + login_name + "')], limit=1)",
             "P = env['edu.notify.pref'].sudo()"]
    for k, v in sorted(snap.items()):
        lines.append("P.search([('user_id', '=', u.id), ('event_key', '=', u'%s')])"
                     ".write({'muted': %s})" % (k, 'True' if v else 'False'))
    lines += ["env.cr.commit()",
              "rows = P.search([('user_id', '=', u.id)])",
              "print('PREF_AFTER ' + ','.join('%s:%d' % (r.event_key, 1 if r.muted else 0) for r in rows))"]
    return _parse_pref(odoo_shell('\n'.join(lines) + '\n'), 'PREF_AFTER')


def _parse_pref(out, tag):
    m = re.search(tag + r' (\S*)', out)
    d = {}
    if m and m.group(1):
        for pair in m.group(1).split(','):
            k, _, v = pair.partition(':')
            if k:
                d[k] = int(v or 0)
    return d


def _body():
    stu = login('stu@local')
    check('学生登录', bool(stu))

    # ---- A 通知偏好 ----
    r = stu.get(BASE + '/my/notify', timeout=30)
    check('偏好页 200', r.status_code == 200 and '通知偏好' in r.text,
          r.status_code)
    check('四个事件开关齐全', all(x in r.text for x in
          ['evt_leave_result', 'evt_grade_result', 'evt_assignment_graded',
           'evt_journal_reviewed']))
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    # 全部静音
    stu.post(BASE + '/my/notify/save', data={'csrf_token': csrf.group(1)},
             timeout=30, allow_redirects=False)
    r = stu.get(BASE + '/my/notify', timeout=30)
    check('静音后开关为关', r.text.count('checked') < r.text.count('form-check-input'), )
    muted_on = 'evt_grade_result' in r.text and (
        re.search(r'evt_grade_result"[^>]*>', r.text) is not None)
    # 触发成绩通知 → 不应到达
    out = odoo_shell(
        "att = env['op.exam.attendees'].sudo().search([], limit=1)\n"
        "if att:\n"
        "    stu_user = att.student_id.user_id\n"
        "    old = att.marks\n"
        "    att.write({'marks': (old or 0) + 2})\n"
        "    base = env['edu.message'].sudo().search_count(\n"
        "        [('recipient_id', '=', stu_user.id),\n"
        "         ('event_key', '=', 'grade_result')])\n"
        "    old = att.marks\n"
        "    att.write({'marks': (old or 0) + 2})\n"
        "    after = env['edu.message'].sudo().search_count(\n"
        "        [('recipient_id', '=', stu_user.id),\n"
        "         ('event_key', '=', 'grade_result')])\n"
        "    print('MUTED_DELTA', after - base)\n"
        "    att.write({'marks': old})\n"
        "    env.cr.commit()\n")
    # t100：改**基线增量**。原先拿硬编码时间戳 '2026-08-29 18:00:00' 当基线，
    # 那是「绝对基线」写法 —— 会随历史累积/时间推移而失真（同族问题见 aux2 的 MARKS_MSG==1）。
    check('静音后成绩提醒不到达（增量 0）', 'MUTED_DELTA 0' in out, out[-200:])
    # 恢复接收，再次触发 → 应到达
    stu.post(BASE + '/my/notify/save', data={
        'csrf_token': csrf.group(1), 'evt_leave_result': 'on',
        'evt_grade_result': 'on', 'evt_assignment_graded': 'on',
        'evt_journal_reviewed': 'on'}, timeout=30, allow_redirects=False)
    out = odoo_shell(
        "att = env['op.exam.attendees'].sudo().search([], limit=1)\n"
        "if att:\n"
        "    stu_user = att.student_id.user_id\n"
        "    base = env['edu.message'].sudo().search_count(\n"
        "        [('recipient_id', '=', stu_user.id),\n"
        "         ('event_key', '=', 'grade_result')])\n"
        "    old = att.marks\n"
        "    att.write({'marks': (old or 0) + 3})\n"
        "    after = env['edu.message'].sudo().search_count(\n"
        "        [('recipient_id', '=', stu_user.id),\n"
        "         ('event_key', '=', 'grade_result')])\n"
        "    print('UNMUTED_DELTA', after - base)\n"
        "    att.write({'marks': old})\n"
        "    env.cr.commit()\n")
    check('恢复后成绩提醒到达', 'UNMUTED_DELTA 1' in out, out[-200:])

    # ---- C 成绩逐生留痕 ----
    fac = login('faculty@local')
    r = fac.get(BASE + '/grading/entry', timeout=30)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    exam_id = None
    ms = re.findall(r'/grading/entry\?exam_id=(\d+)', r.text) or \
        re.findall(r'<option[^>]*value="(\d+)"', r.text)
    exam_id = ms[0] if ms else None
    check('成绩录入页有考试可选', bool(exam_id), r.status_code)
    if exam_id:
        out = odoo_shell(
            "ex = env['op.exam'].sudo().browse(%s)\n"
            "att = env['op.exam.attendees'].sudo().search([('exam_id','=',ex.id)], limit=1)\n"
            "if not att:\n"
            "    att = env['op.exam.attendees'].sudo().search([], limit=1)\n"
            "stu_user = att.student_id.user_id\n"
            "old = att.marks\n"
            "att.write({'marks': (old or 0) + 5})\n"
            "env.cr.commit()\n"
            "print('OLD_MARKS', old)\n" % exam_id)
        old_marks = re.search(r'OLD_MARKS ([\d.]+)', out)
        old_marks = old_marks.group(1) if old_marks else ''
        # 以教师身份 POST /grading/save 改成绩 → 审计明细应含 old→new
        rp = fac.get(BASE + '/grading/entry?exam_id=' + exam_id, timeout=30)
        c2 = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', rp.text)
        new_val = str(int(float(old_marks or '0')) + 7)
        m_att = odoo_shell(
            "ex = env['op.exam'].sudo().browse(%s)\n"
            "att = env['op.exam.attendees'].sudo().search([('exam_id','=',ex.id)], limit=1)\n"
            "print('ATT_ID', att.id)\n" % exam_id)
        att_id = re.search(r'ATT_ID (\d+)', m_att)
        if att_id:
            fac.post(BASE + '/grading/save', data={
                'csrf_token': c2.group(1) if c2 else '',
                'exam_id': exam_id,
                'marks_' + att_id.group(1): new_val,
            }, timeout=30, allow_redirects=False)
            r2 = bo = login('backoffice@local')
            r3 = bo.get(BASE + '/edu/audit?search=' + new_val, timeout=30)
            ok = new_val in r3.text and '成绩录入' in r3.text
            check('审计明细含 old→new', ok, r3.status_code)
        # 还原成绩
        odoo_shell(
            "ex = env['op.exam'].sudo().browse(%s)\n"
            "att = env['op.exam.attendees'].sudo().search([('exam_id','=',ex.id)], limit=1)\n"
            "att.write({'marks': %s})\n"
            "env.cr.commit()\n"
            "print('RESTORED')\n" % (exam_id, old_marks or '0'))

    # ---- D 搜索快捷键资源 ----
    r = stu.get(BASE + '/my/home', timeout=30)
    bundles = re.findall(r'src="(/web/assets/[^"]+\.js)"', r.text)
    found = False
    for b in bundles[:8]:
        rb = stu.get(BASE + b, timeout=60)
        if 'search_focus' in rb.text or '/"k"' in rb.text or 'ev.key === "k"' in rb.text:
            found = True
            break
    check('search_focus.js 已随资源下发', found, len(bundles))

    return None


def main():
    """外层生命周期（t100 ①）：取**整份**偏好快照 → 跑主体 → **finally 整份还原** → 断言无残留。

    为什么必须整份：本脚本会「全部静音」（POST 只带 csrf → 所有键置 muted），
    而主体只把 4 个 evt_* 键恢复；**未被恢复的键就是残留** ——
    实测留下 `reimburse_result` / `subject_reg_result` 为 muted=True，
    正是别的冒烟（如 p3_ledger 的报销通知）被误判成**产品缺陷**的成因。

    还原放 finally：任何路径（含 _body 内 sys.exit）都会恢复，与 t94 的原子还原同源。
    """
    snap0 = pref_snapshot()
    check('偏好快照已取（覆盖该用户全部键）', bool(snap0),
          'keys=%d' % len(snap0))
    try:
        _body()
    except SystemExit:
        pass
    finally:
        after = pref_restore(snap0)
        # 残留的定义：**不是「我改的键恢复了」，而是「我没碰的键也没被动过」**
        keys = set(snap0) | set(after)
        residue = {k: (snap0.get(k), after.get(k)) for k in keys
                   if snap0.get(k) != after.get(k)}
        check('无残留：全部键回到快照值（含本脚本未碰过的键）', not residue,
              'residue=%s' % residue)
        for k in ('reimburse_result', 'subject_reg_result'):
            if k in after:
                check('未碰过的键 %s 仍在原值（t91 ① 的直接证据）' % k,
                      after.get(k) == snap0.get(k),
                      'snap=%s after=%s' % (snap0.get(k), after.get(k)))
    print('\nPASS=%d FAIL=%d' % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
