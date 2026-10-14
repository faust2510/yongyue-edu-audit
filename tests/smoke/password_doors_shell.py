# -*- coding: utf-8 -*-
"""「其他设密码门」审计（odoo shell 版；配合 tests/smoke/password_doors_verbatim.py）。

为什么要有 shell 版：下面这些门的入口不是 HTTP 路由而是 ORM/向导方法，
XML-RPC 跑不到（有的是 @check_identity 的 HTTP-only 方法），只能进 odoo shell 跑。

跑法（**新进程**，会重新 import 当前代码，故能看到刚改的覆盖）：
  docker compose cp tests/smoke/password_doors_shell.py web:/tmp/doors.py
  docker compose exec -T -u root web chmod 644 /tmp/doors.py
  docker compose exec -T web bash -lc "odoo shell --db_host=db --db_port=5432 \
    --db_user=odoo --db_password=odoo -c /etc/odoo/odoo.conf -d edu19 --no-http < /tmp/doors.py"

判据：每一门都期望「逐字」——typed(带尾空格) 能过 / stripped(去空格) 不能过。
账号前缀 cpw-audit-*@cpw.local，脚本自清（用户 + 伙伴 + 自己产生的 mail.mail 行）。
"""
import json

Users = env['res.users'].sudo()
portal = env.ref('base.group_portal')
INIT = 'InitPass123'
PW = 'AuditPass456 '
STRIPPED = PW.strip()
MADE = []


def mk(login, pw=INIT):
    u = Users.create({'name': '审计 ' + login, 'login': login, 'email': login,
                      'password': pw, 'group_ids': [(6, 0, [portal.id])]})
    MADE.append(u.id)
    return u


def cred(u, pw):
    try:
        u.authenticate({'type': 'password', 'login': u.login, 'password': pw},
                       {'interactive': True})
        return True
    except Exception:
        return False


def verdict(u):
    return {'typed(带空格)_ok': cred(u, PW), 'stripped(去空格)_ok': cred(u, STRIPPED)}


def counts():
    return {'res_users': env['res.users'].search_count([]),
            'res_partner': env['res.partner'].search_count([]),
            'mail_message': env['mail.message'].search_count([]),
            'mail_mail': env['mail.mail'].search_count([])}


BASE = counts()
RES = {}

# 门 1：res.users.create(password=…) —— 注册 / 邀请码写入口（register.py 走这条）
u1 = mk('cpw-audit-create@cpw.local', PW)
RES['create(注册写入口)'] = verdict(u1)

# 门 2：后台「修改密码」向导（管理员给别人设密码）
u2 = mk('cpw-audit-wizard@cpw.local')
w = env['change.password.wizard'].sudo().create(
    {'user_ids': [(0, 0, {'user_id': u2.id, 'new_passwd': PW})]})
w.change_password_button()
RES['backoffice_wizard(change.password.wizard)'] = verdict(u2)

# 门 3：同上，逐行方法本身（base/models/res_users.py:1481 的 _change_password 调用点）
u3 = mk('cpw-audit-line@cpw.local')
w2 = env['change.password.wizard'].sudo().create(
    {'user_ids': [(0, 0, {'user_id': u3.id, 'user_login': u3.login})]})
w2.user_ids.write({'new_passwd': PW})
w2.user_ids.change_password_button()
RES['backoffice_wizard_line(base:1481)'] = verdict(u3)

# 门 4：res.users.write({'password': …}) —— 邮箱重置/signup 的落点
#      （auth_signup/models/res_users.py:63 partner_user.write(values)）
u4 = mk('cpw-audit-writepw@cpw.local')
u4.write({'password': PW})
RES['write_password(signup/reset 落点)'] = verdict(u4)

# 门 5：auth_signup 自己建号（邀请/自助注册）：_signup_create_user(values)
try:
    nu = Users._signup_create_user({'name': '审计 signup', 'login': 'cpw-audit-signup@cpw.local',
                                    'email': 'cpw-audit-signup@cpw.local', 'password': PW})
    MADE.append(nu.id)
    RES['signup_create_user(auth_signup)'] = verdict(nu)
except Exception as exc:
    RES['signup_create_user(auth_signup)'] = {'error': str(exc)[:200]}

# 门 6：res.users.write({'new_password': …}) —— 19.0 用户表单已无此字段（ir.ui.view 实测），
#      仅剩模型层 API；实测为**静默空操作**（INIT 仍可登录，typed/stripped 都不可）。
u6 = mk('cpw-audit-newpw@cpw.local')
u6.write({'new_password': PW})
RES['form_new_password_API(base:414-426)'] = {'INIT_仍可登录': cred(u6, INIT), **verdict(u6)}

env.cr.commit()
print('RESULT ' + json.dumps(RES, ensure_ascii=False))

# ---- 清场：用户 + 伙伴 + 本脚本自己产生的 mail.mail 行（安全通知邮件）----
mails = env['mail.mail'].sudo().search(['|', ('email_to', 'ilike', 'cpw.local'),
                                        ('email_to', 'ilike', 'cpwd.local')]).ids
Users.browse(MADE).unlink()
pids = env['res.partner'].sudo().search([('email', 'like', 'cpw-audit-%@cpw.local')]).ids
if pids:
    env['res.partner'].sudo().browse(pids).unlink()
if mails:
    env['mail.mail'].sudo().browse(mails).unlink()
env.cr.commit()
print('COUNTS ' + json.dumps({'base': BASE, 'after_cleanup': counts(),
                              'removed_mail_rows': len(mails)}, ensure_ascii=False))
print('LEFT_USERS ' + str(env['res.users'].sudo().search_count(
    [('login', 'like', 'cpw-audit-%@cpw.local')])))
print('LEFT_PARTNERS ' + str(env['res.partner'].sudo().search_count(
    [('email', 'like', 'cpw-audit-%@cpw.local')])))
