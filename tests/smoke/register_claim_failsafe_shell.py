#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""层级码注册认领（学生层）—— **fail-safe 故障注入**（odoo shell 版）。

为什么要有 shell 版：HTTP 请求进的是**跑着的** web 进程，从外面没法给它打补丁；
而硬要求是「匹配逻辑出错绝不能让人注册不了」—— 只能进 odoo shell 把匹配器直接替换成
会抛异常的实现，再调 create_pending_archive()，看它是不是**照样退回新建待分配档案**。

跑法（由 tests/smoke/register_claim_archive.py 自动调用；也可手工跑）：
  docker compose exec -T web bash -lc "cat > /tmp/claim_fault.py && odoo shell \
    --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo \
    -c /etc/odoo/odoo.conf -d edu19 --no-http < /tmp/claim_fault.py"

读法：脚本打印 FAULT_JSON={...} 一行，键含义：
  outcome            —— 调用 create_pending_archive() 的结果（期望 no-exception）
  students_delta     —— 期望 1（退回老路：新建了一条待分配档案）
  fixture_claimed    —— 期望 False（savepoint 回滚 ⇒ 夹具档案**没被**挂上账号）
  new_archive_*      —— 新建档案的三个读数（edu_pending_setup/dup_suspect/note）
脚本自清（用户 + 伙伴 + 学生档案 + 邀请码），计数在 JSON 里。
"""
import json

STAMP = '__STAMP__'
Code = env['edu.invite.code'].sudo()          # noqa: F821
Users = env['res.users'].sudo()               # noqa: F821
Student = env['op.student'].sudo()            # noqa: F821
Partner = env['res.partner'].sudo()           # noqa: F821
portal = env.ref('base.group_portal')         # noqa: F821

FIX_NAME = '庚化名' + STAMP
FIX_GR = 'QA' + STAMP + 'F'
USER_LOGIN = 'claim-fault-' + STAMP + '@claim.local'
CODE_TEXT = 'CLAIM-FAULT-' + STAMP

made = {'codes': [], 'students': [], 'partners': [], 'users': []}

# 夹具：一条「可认领」的档案（名字与学号都指向它）；故障注入后它**不该**被挂上
fix_pid = Partner.create({'name': FIX_NAME}).id
made['partners'].append(fix_pid)
fix_sid = Student.create({'partner_id': fix_pid, 'name': FIX_NAME, 'gender': 'm',
                          'gr_no': FIX_GR}).id
made['students'].append(fix_sid)
code = Code.create({'code': CODE_TEXT, 'code_kind': 'tier', 'tier': 'student',
                    'note': '【冒烟】认领故障注入'})
made['codes'].append(code.id)
user = Users.create({'login': USER_LOGIN, 'password': 'demo123', 'name': '冒烟故障注入',
                     'email': USER_LOGIN, 'group_ids': [(6, 0, [portal.id])]})
made['users'].append(user.id)

# 注入故障：匹配器一律抛异常（模拟认领逻辑写错/查询炸掉）
Kls = type(Code)
_orig = Kls._edu_find_claimable_student
Kls._edu_find_claimable_student = (
    lambda self, name, gr_no: (_ for _ in ()).throw(RuntimeError('injected-claim-fault')))

before = Student.search_count([])
outcome = ''
new_sid = 0
try:
    rec = code.create_pending_archive(user, FIX_NAME, gr_no=FIX_GR)
    outcome = 'no-exception'
    new_sid = rec.id if rec else 0
except Exception as exc:                      # noqa: BLE001
    outcome = 'raised: %s' % (exc,)
after = Student.search_count([])
Kls._edu_find_claimable_student = _orig
env.cr.commit()                               # noqa: F821

new = Student.browse(new_sid)
res = {
    'outcome': outcome,
    'students_before': before,
    'students_after': after,
    'students_delta': after - before,
    'fixture_claimed': bool(Student.browse(fix_sid).user_id),
    'fixture_id': fix_sid,
    'new_archive_id': new_sid,
    'new_archive_name': new.name if new else '',
    'new_archive_pending': new.edu_pending_setup if new else None,
    'new_archive_dup_suspect': new.edu_dup_suspect if new else None,
    'new_archive_note': new.edu_claim_note if new else None,
    'new_archive_user_id_is_new_account': (new.user_id.id == user.id) if new else None,
}
print('FAULT_JSON=' + json.dumps(res, ensure_ascii=False))

# ---- 自清（本脚本造的东西一处不留）----
Student.browse([sid for sid in made['students'] + [new_sid] if sid]).exists().unlink()
Partner.browse(made['partners']).exists().unlink()
Code.browse(made['codes']).exists().unlink()
Users.browse(made['users']).exists().unlink()
env.cr.commit()                               # noqa: F821
print('FAULT_CLEAN=' + json.dumps({
    'students_left': Student.search_count([('id', 'in', made['students'] + [new_sid])]),
    'codes_left': Code.search_count([('id', 'in', made['codes'])]),
    'users_left': Users.search_count([('id', '=', user.id)]),
}, ensure_ascii=False))
