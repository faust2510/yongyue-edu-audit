# -*- coding: utf-8 -*-
"""「选课 → 课表」链的运行层证据 + 权限第二道门（跑在本地 odoo shell 内）。

回答两件事（对应交付物 B 的第 2 问与「越权红线」）：
  C 段：**报课单被通过**时到底写了什么？会不会产生 op.session（= 学生课表里的课节）？
        —— 走真实动作 action_enroll_approve()（门户 /registrar/subject/approvals/<id>/set_state
           与后台按钮调用的都是它），量 op.session 前后计数。
  D 段：课程编排的写入**不只**靠控制器那一层门 —— edu.course.subject 的 ACL 是否也拦得住
        教师 / 学生（数据层第二道门）；对照：教务身份同一写入必须成功。

⛔ 零残留：全过程在**一个事务**里跑，结束 env.cr.rollback()；脚本再用进程外 psql
   复核「库里什么都没变」（比脚本内自证更强）。

用法：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 \
        --db_host=db -r odoo -w odoo --no-http \
        < tests/smoke/enroll_timetable_chain_shell.py
"""
from odoo.exceptions import AccessError

COURSE = 18
BATCH = 8
STU_LOGIN = 'stu@local'
BO_LOGIN = 'backoffice@local'
FAC_LOGIN = 'faculty@local'

ok = fail = 0


def check(name, cond, detail=''):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print('%s | %s | %s' % ('PASS' if cond else 'FAIL', name, detail))


def uid_of(login):
    return env['res.users'].sudo().search([('login', '=', login)], limit=1).id


# 学生 5：身份反查口径 = identity.student_of_user（实测本库走 op_student.user_id）
student = env['op.student'].sudo().search([('user_id', '=', uid_of(STU_LOGIN))],
                                          limit=1)
check('C0 拿到学生载体（stu@local → op.student）', bool(student),
      'student=%s' % (student.id if student else None))

sc = env['op.student.course'].sudo().search(
    [('student_id', '=', student.id), ('state', '=', 'running')], limit=1)
course = env['op.course'].sudo().browse(COURSE)
batch = env['op.batch'].sudo().browse(BATCH)
orig_subjects = sc.subject_ids.ids
n_sessions0 = env['op.session'].sudo().search_count([])
n_regs0 = env['op.subject.registration'].sudo().search_count([])
print('   · 起点：档案 %s 科目 %s；op.session=%d；报课单=%d'
      % (sc.id, orig_subjects, n_sessions0, n_regs0))

# 报课单 payload：故意与档案现有科目不同（否则「写了档案」与「没写」同形）。
# ⚠ 报课单里的都是 **op.subject.id**（不是 edu.course.subject 行 id）—— 本脚本
#   从科目池现取，并按「全库排课数 = 0」挑 3 门，好让 C3 的读数不被无关排课污染。
_pool = sorted(course.subject_line_ids.mapped('subject_id').ids)
_zero = [s for s in _pool
         if not env['op.session'].sudo().search_count([('subject_id', '=', s)])]
if len(_zero) < 3:
    raise SystemExit('科目池里排课数为 0 的科目不足 3 门，无法做 C3 的干净读数')
payload_c = [_zero[0]]        # 必修（服务端由 edu_compulsory_subject_ids() 自动补齐）
payload_e = _zero[1:3]        # 选修（学生在页面上勾的）
reg = env['op.subject.registration'].sudo().create({
    'student_id': student.id,
    'course_id': course.id,
    'batch_id': batch.id,
    'state': 'submitted',
    'doc_type': 'subject_registration',
    'compulsory_subject_ids': [(6, 0, payload_c)],
    'elective_subject_ids': [(6, 0, payload_e)],
})
reg.action_enroll_approve()
env.invalidate_all()
n_sessions1 = env['op.session'].sudo().search_count([])
subjects_now = set(sc.subject_ids.ids)
check('C1 通过报课单：op.session 计数**不变**（%d → %d）⇒ 选课**不产生课节**'
      % (n_sessions0, n_sessions1), n_sessions0 == n_sessions1,
      'session Δ=%d' % (n_sessions1 - n_sessions0))
check('C2 正对照：同一动作**确实写了**学生档案（科目 %s → %s）⇒ 动作真跑了，'
      '不是「什么都没发生」' % (orig_subjects, sorted(subjects_now)),
      subjects_now == set(payload_c) | set(payload_e) and reg.state == 'approved',
      'state=%s' % reg.state)
sess_of_payload = env['op.session'].sudo().search_count(
    [('subject_id', 'in', sorted(set(payload_c) | set(payload_e)))])
check('C3 该生这批「报了」的科目在全库的排课数 = %d ⇒ 报课与排课是两条链'
      % sess_of_payload, sess_of_payload == 0,
      '科目 %s' % sorted(set(payload_c) | set(payload_e)))
audit = env['edu.audit.log'].sudo().search([('action', '=', '选课审批')], limit=1)
check('C4 审批动作留下了审计（同一动作在门户/后台都走它）', bool(audit),
      'audit=%s' % (audit.id if audit else None))

# ---------------- D 段：ACL 第二道门 ----------------
line = course.subject_line_ids[:1]
bo_uid, fac_uid = uid_of(BO_LOGIN), uid_of(FAC_LOGIN)
stu_uid = uid_of(STU_LOGIN)
err = {}


def try_write(uid):
    try:
        env['edu.course.subject'].with_user(uid).browse(line.id).write(
            {'subject_type': 'compulsory'})
        return True, ''
    except AccessError as exc:
        return False, str(exc).splitlines()[0][:90]
    except Exception as exc:                     # noqa: BLE001
        return None, type(exc).__name__ + ': ' + str(exc)[:80]


bo_ok, bo_err = try_write(bo_uid)
fa_ok, fa_err = try_write(fac_uid)
st_ok, st_err = try_write(stu_uid)
check('D1 教务（backoffice@local）对 edu.course.subject 的 ORM 写入**成功**（控制组）',
      bo_ok is True, 'err=%s' % bo_err)
check('D2 教师（faculty@local）同一写入撞 AccessError ⇒ ACL 是第二道门，'
      '不是只靠控制器', fa_ok is False, 'err=%s' % fa_err)
check('D3 学生（stu@local）同一写入撞 AccessError', st_ok is False,
      'err=%s' % st_err)

env.cr.rollback()      # ★ 全部还原（本脚本不改库 —— 见进程外复核）
print('ROLLBACK_DONE op_session=%d regs=%d'
      % (env['op.session'].sudo().search_count([]),
         env['op.subject.registration'].sudo().search_count([])))
print('\n合计：PASS %d / FAIL %d' % (ok, fail))
