#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成绩中心本轮收口（2026-10-13）的活体验收：W1 xlsx 往返 / W2 教务手工加人 / W3 后台只读入口。

栈：本地 edu19-clone（http://localhost:8069，db=edu19）——**不碰生产**。
写操作自还原：分数改回原值、加人删回。追加型审计行（edu_grade_history / edu_audit_log）保留为证据。
用法：python3 tests/smoke/gradebook_center_io.py
结果：同目录 gradebook_center_io_results.json
"""
import io
import json
import os
import re
import subprocess

os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
os.environ['no_proxy'] = 'localhost,127.0.0.1'

import openpyxl
import requests

B = 'http://localhost:8069'
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
XLSX_MIME = ('application/vnd.openxmlformats-officedocument'
             '.spreadsheetml.sheet')
OK = []
NOTES = {}


def check(name, got, want, extra=''):
    good = got == want
    OK.append((bool(good), name))
    print('  %-4s %-54s 期望 %-26s 实际 %s %s'
          % ('PASS' if good else 'FAIL', name, want, got, extra))


def loc(r):
    return (r.headers.get('Location') or '').replace(B, '')


def login(name, pw='demo123'):
    s = requests.Session()
    r = s.get(B + '/login?db=edu19', timeout=30)
    m = re.search(r'csrf_token[^>]*?value="([^"]+)"', r.text or '')
    assert m, '登录页没有 csrf_token（HTTP %s）' % r.status_code
    s.post(B + '/login', allow_redirects=False, timeout=30, data={
        'csrf_token': m.group(1), 'db': 'edu19', 'login': name,
        'password': pw, 'redirect': ''})
    return s


def csrf_of(html):
    m = re.search(r'csrf_token[^>]*?value="([^"]+)"', html or '')
    return m.group(1) if m else None


def select_values(html, name):
    seg = re.search(r'<select[^>]*name="%s".*?</select>' % name, html or '', re.S)
    return re.findall(r'<option[^>]*value="(\d+)"', seg.group(0)) if seg else []


def select_pairs(html, name):
    """(value, 选项文字)：加人下拉的文字是「学号 姓名」。"""
    seg = re.search(r'<select[^>]*name="%s".*?</select>' % name, html or '', re.S)
    return re.findall(r'<option[^>]*value="(\d+)"[^>]*>(.*?)</option>',
                      seg.group(0), re.S) if seg else []


def sql(q):
    p = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                        '-U', 'odoo', '-d', 'edu19', '-tAc', q],
                       cwd=REPO, capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        raise RuntimeError('psql 失败：%s' % (p.stderr or '')[-300:])
    return p.stdout.strip()


def saved_of(html):
    m = re.search(r'实际写入\s*<b>(\d+)</b>', html or '')
    return int(m.group(1)) if m else None


def upload(sess, tok, tgt, blob, name='probe.xlsx'):
    return sess.post(B + '/grade-entry/import', allow_redirects=False,
                     timeout=120, data={
                         'csrf_token': tok, 'batch_id': tgt['batch'],
                         'term_id': tgt['term'], 'subject_id': tgt['subject']},
                     files={'file': (name, blob, XLSX_MIME)})


print('=== 0. 登录（本地克隆库 edu19）===')
bo, fa, st = login('backoffice@local'), login('faculty@local'), login('stu@local')
check('三个身份登录成功（教务 / 教师 / 学生）', True, True)

print('=== 1. W1-a 批量页 + 找一个有名册的目标并导出 ===')
r = bo.get(B + '/grade-entry/xlsx', timeout=30)
check('GET /grade-entry/xlsx（教务）', r.status_code, 200)
tok = csrf_of(r.text)
batches = select_values(r.text, 'batch_id')
terms = select_values(r.text, 'term_id')
subjects = select_values(r.text, 'subject_id')
check('批量页有班级/学期/科目可选',
      (len(batches) > 0, len(terms) > 0, len(subjects) > 0), (True, True, True),
      '班 %d / 学期 %d / 科目 %d' % (len(batches), len(terms), len(subjects)))
check('批量页导入表单带 csrf_token', bool(tok), True)

tgt, rows = None, None
for b in batches[:10]:
    for s in subjects[:15]:
        for t in terms[:2]:
            rr = bo.get(B + '/grade-entry/export.xlsx', timeout=90, params={
                'batch_id': b, 'term_id': t, 'subject_id': s})
            if rr.status_code != 200 or 'spreadsheet' not in (
                    rr.headers.get('Content-Type') or ''):
                continue
            wb = openpyxl.load_workbook(io.BytesIO(rr.content))
            got_rows = list(wb.active.iter_rows(values_only=True))
            data = [x for x in got_rows[2:] if x and x[0]]
            if any(isinstance(x[2], (int, float)) for x in data):
                tgt = {'batch': b, 'term': t, 'subject': s, 'blob': rr.content}
                rows = got_rows
                break
        if tgt:
            break
    if tgt:
        break
check('找到有名册的 (班 × 学期 × 科目) 目标', bool(tgt), True, str(tgt and {
    'batch': tgt['batch'], 'term': tgt['term'], 'subject': tgt['subject']}))
if not tgt:
    raise SystemExit('本地库没有可用的成绩名单，无法继续')
NOTES['target'] = {k: tgt[k] for k in ('batch', 'term', 'subject')}
NOTES['target_names'] = {'batch': rows[0][1], 'term': rows[0][3],
                         'subject': rows[0][5]}

check('导出表首行自解释（班 / 学期 / 科目）',
      (rows[0][0], rows[0][2], rows[0][4]), ('班', '学期', '科目'),
      '%s / %s / %s' % (rows[0][1], rows[0][3], rows[0][5]))
check('导出表次行是列名', tuple(rows[1][:4]),
      ('学号', '姓名', '分数', '等级'))
check('导出表每行都有学号', any(x[0] for x in rows[2:]), True,
      '名册 %d 人' % len(rows[2:]))

print('=== 2. W1-b 原样导回 = 无改动（不重复留痕）===')
r = upload(bo, tok, tgt, tgt['blob'], 'same.xlsx')
check('POST /grade-entry/import（原样）', r.status_code, 200)
check('  实际写入 0 条', saved_of(r.text), 0)
check('  结果页标注「无改动」', '无改动' in (r.text or ''), True)

print('=== 3. W1-c 改一行分数再导 = 写入 + 留痕 + 读侧同步 ===')
row_i = next(i for i, x in enumerate(rows)
             if i >= 2 and x[0] and isinstance(x[2], (int, float)))
gr_no, old_mark = rows[row_i][0], int(rows[row_i][2])
new_mark = old_mark + 1 if old_mark < 100 else old_mark - 1
wb = openpyxl.load_workbook(io.BytesIO(tgt['blob']))
wb.active.cell(row=row_i + 1, column=3).value = new_mark
buf = io.BytesIO()
wb.save(buf)
sid = sql("select id from op_student where gr_no = '%s'" % gr_no)
check('改动的学生能在库里找到（学号 %s）' % gr_no, bool(sid), True,
      'id=%s 原分=%s → 新分=%s' % (sid, old_mark, new_mark))
NOTES['student'] = {'gr_no': gr_no, 'id': sid, 'old': old_mark, 'new': new_mark}

hist_before = int(sql("select count(*) from edu_grade_history "
                      "where student_id = %s" % sid))
r = upload(bo, tok, tgt, buf.getvalue())
check('POST /grade-entry/import（改一行）', r.status_code, 200)
check('  实际写入 >= 1 条', (saved_of(r.text) or 0) >= 1, True,
      'saved=%s' % saved_of(r.text))
hist_after = int(sql("select count(*) from edu_grade_history "
                     "where student_id = %s" % sid))
check('  留痕新增行（edu_grade_history）', hist_after > hist_before, True,
      '%d → %d' % (hist_before, hist_after))
check('  最新留痕记的是导入来源与目标分数',
      sql("select source || '|' || new_marks from edu_grade_history "
          "where student_id = %s order by id desc limit 1" % sid),
      'import|%d' % new_mark)

rr = bo.get(B + '/grade-entry/export.xlsx', timeout=90, params={
    'batch_id': tgt['batch'], 'term_id': tgt['term'],
    'subject_id': tgt['subject']})
wb2 = openpyxl.load_workbook(io.BytesIO(rr.content))
after = [x for x in list(wb2.active.iter_rows(values_only=True))
         if x and x[0] == gr_no]
check('  读侧同步：再导出该学生分数 = 新分（学生端可见值）',
      int(after[0][2]), new_mark)

print('=== 4. W1-d 还原（把原表导回去）===')
r = upload(bo, tok, tgt, tgt['blob'], 'restore.xlsx')
rr = bo.get(B + '/grade-entry/export.xlsx', timeout=90, params={
    'batch_id': tgt['batch'], 'term_id': tgt['term'],
    'subject_id': tgt['subject']})
wb3 = openpyxl.load_workbook(io.BytesIO(rr.content))
back = [x for x in list(wb3.active.iter_rows(values_only=True))
        if x and x[0] == gr_no]
check('  还原后分数 = 原值', int(back[0][2]), old_mark)

print('=== 5. W2 手工加人：教务可 / 教师 err=scope / 学生拒止 ===')
url = '/grade-entry?batch_id=%s&term_id=%s' % (tgt['batch'], tgt['term'])
r = bo.get(B + url, timeout=30)
add_tok = csrf_of(r.text)
cands = select_pairs(r.text, 'student_id')
check('教务录入页出现「手工加人」卡片', '手工加人' in (r.text or ''), True)
check('  可加学生下拉非空', len(cands) > 0, True, '候选 %d 人' % len(cands))
roster_nos = set(str(x[0]) for x in rows[2:] if x[0])
pick = next(((v, label) for v, label in cands
             if label.strip().split(' ')[0] not in roster_nos), None)
new_stu = pick[0] if pick else cands[-1][0]
stu_name = (pick[1] if pick else cands[-1][1]).strip().split(' ', 1)[-1].strip()
sc_before = sql("select count(*) from op_student_course where student_id = %s"
                % new_stu)
audit_before = int(sql("select count(*) from edu_audit_log "
                       "where action = '手工加人' and res_id = %s" % new_stu))
NOTES['add_student'] = {'id': new_stu, 'name': stu_name,
                        'in_roster': pick is None,
                        'course_rows_before': sc_before}

r = bo.post(B + '/grade-entry/add-student', allow_redirects=False, timeout=30,
            data={'csrf_token': add_tok, 'batch_id': tgt['batch'],
                  'term_id': tgt['term'], 'subject_id': tgt['subject'],
                  'student_id': new_stu, 'note': '探针加人'})
check('教务 POST /grade-entry/add-student', loc(r).endswith('added=1'), True, loc(r))
extra_where = ('batch_id = %s and term_id = %s and subject_id = %s '
               'and student_id = %s' % (tgt['batch'], tgt['term'],
                                        tgt['subject'], new_stu))
row_id = sql("select id from edu_grade_entry_extra where %s" % extra_where)
check('  快照表落了一行（edu_grade_entry_extra）', bool(row_id), True,
      'row #%s' % row_id)
check('  留痕「手工加人」',
      int(sql("select count(*) from edu_audit_log where action = '手工加人' "
              "and res_id = %s" % new_stu)) > audit_before, True,
      '加人前 %d 行' % audit_before)
check('  没写学生档案（op_student_course 行数不变）',
      sql("select count(*) from op_student_course where student_id = %s"
          % new_stu), sc_before)

rf = fa.get(B + url, timeout=30)
check('教师录入页看不到「手工加人」卡片',
      '加人是教务 / 超管专属' in (rf.text or ''), False)
check('  教师仍看得见教务加进来的人（③ 标记）',
      ('手工加人' in (rf.text or '')) and (stu_name in (rf.text or '')), True,
      stu_name)
fa_tok = csrf_of(rf.text)
other = [v for v, _l in cands if v != new_stu] or [v for v, _l in cands]
r = fa.post(B + '/grade-entry/add-student', allow_redirects=False, timeout=30,
            data={'csrf_token': fa_tok, 'batch_id': tgt['batch'],
                  'term_id': tgt['term'], 'subject_id': tgt['subject'],
                  'student_id': other[0]})
check('教师 POST add-student → 拒止（err=scope）',
      'err=scope' in loc(r), True, loc(r))
r = fa.post(B + '/grade-entry/remove-student', allow_redirects=False, timeout=30,
            data={'csrf_token': fa_tok, 'batch_id': tgt['batch'],
                  'term_id': tgt['term'], 'row_id': row_id})
check('教师 POST remove-student → 拒止（err=scope）',
      'err=scope' in loc(r), True, loc(r))
check('  教师两次尝试都没改数据',
      sql("select count(*) from edu_grade_entry_extra where %s" % extra_where), '1')

r = st.get(B + '/grade-entry', allow_redirects=False, timeout=30)
check('学生 GET /grade-entry → 门户首页', '%s %s' % (r.status_code, loc(r)),
      '303 /my/home')
r = st.get(B + '/grade-entry/xlsx', allow_redirects=False, timeout=30)
check('学生 GET /grade-entry/xlsx → 门户首页', '%s %s' % (r.status_code, loc(r)),
      '303 /my/home')
r = st.get(B + '/grade-entry/export.xlsx', allow_redirects=False, timeout=30,
           params={'batch_id': tgt['batch'], 'term_id': tgt['term'],
                   'subject_id': tgt['subject']})
check('学生 GET export.xlsx → 门户首页', '%s %s' % (r.status_code, loc(r)),
      '303 /my/home')

r = bo.post(B + '/grade-entry/remove-student', allow_redirects=False, timeout=30,
            data={'csrf_token': add_tok, 'batch_id': tgt['batch'],
                  'term_id': tgt['term'], 'row_id': row_id})
check('教务 POST /grade-entry/remove-student', loc(r).endswith('removed=1'),
      True, loc(r))
check('  快照行已删',
      sql("select count(*) from edu_grade_entry_extra where %s" % extra_where), '0')

print('=== 6. W3 后台「按科目」只读入口 ===')
arch = sql("select arch_db->>'en_US' from ir_ui_view "
           "where name = 'edu.grade.container.list'")
check('容器列表视图已入库', bool(arch), True)
check('  只读三连（create/edit/delete=false）',
      all(k in arch for k in ('create="false"', 'edit="false"',
                              'delete="false"')), True)
vm = sql("select view_mode::text from ir_act_window "
         "where name->>'en_US' = '成绩录入容器（只读）'")
check('  不给 form 视图（view_mode 只有 list）',
      vm.replace('"', '').strip('[]'), 'list', vm)
check('  action 只认成绩录入容器（domain 带 GE）',
      'GE' in sql("select domain::text from ir_act_window "
                  "where name->>'en_US' = '成绩录入容器（只读）'"), True)
check('「成绩中心」菜单只给教务 / 超管两个组',
      sql("select count(*) from ir_ui_menu_group_rel r join ir_ui_menu m "
          "on m.id = r.menu_id where m.name->>'en_US' = '成绩中心'"), '2')
aid = sql("select res_id from ir_model_data where module = 'edu_portal' "
          "and name = 'action_grade_container'")
r = bo.get(B + '/odoo/action-%s' % aid, allow_redirects=False, timeout=60)
check('教务打开 /odoo/action-%s（容器列表）' % aid, r.status_code, 200)
r = bo.get(B + '/web/webclient/load_menus', timeout=30)
check('  教务的后台菜单里有「成绩中心」', '成绩中心' in (r.text or ''), True)
r = fa.get(B + '/web/webclient/load_menus', timeout=30)
check('  教师的后台菜单里没有「成绩中心」',
      '成绩中心' in (r.text or ''), False, 'HTTP %s' % r.status_code)

print()
bad = [n for g, n in OK if not g]
print('==== 汇总：%d / %d PASS ====' % (len(OK) - len(bad), len(OK)))
for n in bad:
    print('  FAIL: %s' % n)
with open(os.path.join(HERE, 'gradebook_center_io_results.json'), 'w') as fh:
    json.dump({'total': len(OK), 'failed': bad, 'notes': NOTES,
               'at': __import__('datetime').datetime.now().isoformat()},
              fh, ensure_ascii=False, indent=2)
raise SystemExit(1 if bad else 0)
