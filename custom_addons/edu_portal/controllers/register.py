# -*- coding: utf-8 -*-
"""邀请码注册：/register（公开；/web/register 为 302 兼容入口）。

流程：后台发放邀请码（文本可自定义/层级/次数/有效期，见 models/invite_code.py）
→ 访客在注册页提交 码+姓名+邮箱+密码（+ **学号，选填**）→ 校验通过即建账号并按码落层
（绑人码挂接对应档案；层级码写层级组 + 学生层**先认领教务预建的既有档案**、认领不到
才建「待分配」档案，学号就是认领用的第一顺位依据），随后自动登录。

原生 /web/signup 仍然不可用，但原因不是「auth_signup 未安装」——它是 auto_install
模块（本机实测 installed）；真正关掉公开注册的是网站设置
website.auth_signup_uninvited='b2b'（取证见 docs/research/invite-code-tiers.md §1.2）。
"""
import re
from urllib.parse import urlencode

from odoo import http
from odoo.http import request

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class EduRegister(http.Controller):

    def _prep(self, **post):
        """从提交值提取字段与错误；返回 (vals, error)。"""
        # 只归一化该归一化的三个字段：邀请码（大写）、姓名、邮箱（首尾空格）。
        vals = {k: (post.get(k) or '').strip()
                for k in ('code', 'name', 'email')}
        # 「学号（选填）」：层级码注册用它认领教务预建的既有档案（比姓名可靠：
        # op.student.gr_no 有唯一约束）。**它进了 vals，但绝不能进下面那道必填
        # 名单** —— 否则不填学号的人就注册不了；旧表单根本没有这个字段，
        # 留空可用是兼容性硬要求。
        vals['gr_no'] = (post.get('gr_no') or '').strip()
        # 密码（含确认）**逐字**取值 —— 两端空格是密码本身的一部分，绝不 strip。
        # 2026-09-24 生产事故：旧实现把 password/confirm 一并 .strip()，而登录端不
        # strip（Odoo core auth_signup 的 _prepare_signup_values 也只原样取值、原样
        # 比对 confirm；base/models/res_users.py 只对 new_passwd 做空值校验，没有对
        # 登录口令做任何归一化）⇒ 手机输入法在密码后带的那个空格被静默吃掉，学生
        # 用自己敲的密码永远登不上（当日 4 个新注册账号全部锁死）。
        # 回归：tests/smoke/register_password_verbatim.py
        vals['password'] = post.get('password') or ''
        vals['confirm'] = post.get('confirm') or ''
        # 邀请码统一按大写比对（库里也按大写存）：输入框的 text-uppercase 只是 CSS，
        # 用户手输小写时必须照样命中（t16 码文本可自定义后的必然要求）
        vals['code'] = vals['code'].upper()
        # 必填名单**显式列出**：vals 里现在还装着选填的 gr_no，写成
        # all(vals.values()) 会把选填字段也变成必填（拦住所有不出示学号的人）。
        if not all(vals.get(k) for k in
                   ('code', 'name', 'email', 'password', 'confirm')):
            return vals, '所有字段都必须填写'
        if not _EMAIL_RE.match(vals['email']):
            return vals, '邮箱格式不正确'
        # 纯空格密码（如 "        "）几乎必是误输入：明确拒收。注意这里只做**判断**
        # —— 拒绝不改值，也不把用户敲的东西悄悄换成别的（那是本轮事故的成因）。
        if not vals['password'].strip():
            return vals, '密码不能只由空格组成'
        # 长度按逐字值算：密码中的空格计入长度，与登录端一致。
        if len(vals['password']) < 6:
            return vals, '密码至少 6 位'
        if vals['password'] != vals['confirm']:
            return vals, '两次输入的密码不一致'
        return vals, None

    @http.route('/web/register', type='http', auth='public',
                website=True, sitemap=True)
    def register_form(self, **kw):
        if request.session.uid and request.env.user._is_public() is False:
            return request.redirect('/my/home')
        return request.render('edu_portal.edu_register', {
            'error': kw.get('error'),
            # 重复提交的「输家」落点（判据见 register_submit）：页面换成
            # 「你已注册成功，请直接登录」，不再给一张会让本人再点一次的空表单。
            'registered': kw.get('registered'),
            'email': kw.get('email', ''),
            'code': kw.get('code', ''),
            'name': kw.get('name', ''),
            # 学号（选填）随错误回跳原样带回：填过的人不用重敲一遍
            'gr_no': kw.get('gr_no', ''),
        })

    @http.route('/web/register/submit', type='http', auth='public',
                methods=['POST'], website=True, csrf=True)
    def register_submit(self, **post):
        vals, err = self._prep(**post)
        code_rec = None
        if not err:
            Code = request.env['edu.invite.code'].sudo()
            code_rec = Code.search([('code', '=', vals['code'])], limit=1)
            if not code_rec:
                err = '邀请码无效'
            else:
                err = code_rec._validate_view()
        # 重复提交的「输家」（2026-09-24 生产事故）：码已被**同一个登录邮箱**消费
        # ⇒ 上一次提交其实已经注册成功并自动登录，只是浏览器渲染了后到的这个响应。
        # 旧行为只会回「该邀请码已被使用」，把一次成功的注册说成失败（学生/校长据此
        # 以为一码发给了两个人）。这里换一个如实的落点：**不建第二个账号**，把人送到
        # 「你已注册成功，请直接登录」。真正被别人用掉的码仍走下面的错误分支 ——
        # 「一个码一个账号」的保证一分未让。判据在码记录上（models/invite_code.py
        # 的 _used_by_login），控制器只决定落点。
        if code_rec and code_rec._used_by_login(vals['email']):
            return request.redirect('/register?' + urlencode({
                'registered': '1',
                'email': vals['email'],
                'code': vals['code'],
            }))
        # v2.1-B8：绑身份码在创建账号前先验对应人员可用（未挂他人）
        if not err:
            err = code_rec._validate_identity()
        if not err:
            Users = request.env['res.users'].sudo()
            if Users.sudo().search_count([('login', '=', vals['email'])]):
                err = '该邮箱已被注册'
        if err:
            # 错误回跳指向**活页面** /register：自 v3 起 /web/register 只是 302 兼容
            # 别名（controllers/main.py 的 EduRegisterAlias），它不透传 query string
            # ——错误会被静默丢掉，用户只看到一张干净的空表单「点了没反应」。
            # 查询串一律交给 urlencode：手工拼接时中文、井号、& 与空格会截断或污染参数。
            return request.redirect('/register?' + urlencode({
                'error': err,
                'email': vals['email'],
                'code': vals['code'],
                'name': vals['name'],
                'gr_no': vals.get('gr_no', ''),
            }))

        portal = request.env.ref('base.group_portal')
        # v2.1-B8：邀请码带身份 → 新账号复用对应人员的 partner（一人一档案），
        # 注册成功后由 code_rec.attach_identity(user) 挂接 user_id。
        person = code_rec.identity_record() if code_rec.identity else None
        # t16 层级码：账号直接落在该层级的组里（学生/家长 = 门户组；教师/教务 = 内部组）。
        # 注意 Odoo 不允许同一账号同时属 portal 与 internal 两类组
        # （base/models/res_users.py 的 _check_disjoint_groups），所以这里是二选一。
        tier_group = code_rec.tier_group()
        # 评审 F1：带身份路径下 user_vals 只传 partner_id + login/password/组，
        # 绝不携带注册人输入的 name/email —— Odoo19 中 res_users 的 name/email
        # 落在 res_partner 上，传了会把人员档案的规范姓名/邮箱覆盖成注册输入。
        user_vals = {
            'login': vals['email'],
            'password': vals['password'],
            'group_ids': [(6, 0, [(tier_group or portal).id])],
        }
        if person is not None:
            if code_rec.identity == 'parent' and person.name:
                user_vals['partner_id'] = person.name.id
            elif code_rec.identity in ('student', 'faculty'):
                user_vals['partner_id'] = person.partner_id.id
        else:
            # 普通码（无身份绑定）：维持原行为，账号独立 partner 用注册输入
            user_vals['name'] = vals['name']
            user_vals['email'] = vals['email']
        user = Users.create(user_vals)
        # F1 兜底：仅当人员档案 partner 连规范姓名都没有时才回填注册名
        # （正常档案不会触发；回填只写 name，不动 email）
        if person is not None:
            pname = (person.name.name if code_rec.identity == 'parent'
                     else person.partner_id.name)
            if not pname:
                if code_rec.identity == 'parent' and person.name:
                    person.name.write({'name': vals['name']})
                else:
                    person.partner_id.write({'name': vals['name']})
        if person is not None:
            code_rec.attach_identity(user)
        # t16 层级码：学生/教师层自动建「待分配」档案并挂接（家长/教务层不建，理由见
        # models/invite_code.py 的 TIER_ARCHIVE 注释）
        if tier_group is not None:
            # 学生层会拿 gr_no 先去认领教务预建的既有档案（按学号 → 姓名，
            # 认领不到才新建「待分配」档案）；教师/家长层忽略该参数。
            # gr_no 是选填：没有它时一切照旧（只按姓名匹配）。
            code_rec.create_pending_archive(
                user, vals['name'], gr_no=vals.get('gr_no'))
        code_rec.consume(user)
        # 自动登录（Odoo 19：env + credential 字典）
        try:
            request.session.authenticate(request.env, {
                'login': vals['email'],
                'password': vals['password'],
                'type': 'password',
            })
        except Exception:
            pass  # 极端情况下自动登录失败，注册本身已成功
        return request.redirect('/my/home')


# v2.1-B8：通讯录（/my/contacts）与老账号补挂工具控制器。
# 在本文件底部导入，使新增控制器随本模块注册（保持 B8 改动都在
# 契约 inScope 内，不动 controllers/__init__.py）。
from . import contacts  # noqa: E402,F401
