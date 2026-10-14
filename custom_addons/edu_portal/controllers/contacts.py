# -*- coding: utf-8 -*-
"""v2.1-B8：门户通讯录 + 老账号补挂身份后台小工具。

1) /my/contacts 门户「通讯录」页：
   按 op.faculty / op.student / op.parent 三类记录自动归为
   老师 / 学生 / 家长 三组，可见性按熟人圈矩阵过滤（与 Q2.1 拍板一致）：
   - 家长：自己孩子的任课教师 + 管理员（**看不到别人家孩子** —— 校长拍板 P4）
   - 学生：自己的教师 + 管理员 + **同班同学（需求 7 G6，另起一段）**
   - 教师：本班学生/家长 + 管理员
   - 管理员：全部
   学生段的「同班同学」按校长拍板 P3-(a) 只显示**姓名 + 班名**：
   没有学号、没有头像、没有邮箱、没有手机（模板里根本不渲染这些元素，
   见 views/contacts.xml 的 #edu-classmates 段）。
   组内另含本人（家长含本人与孩子），属「自知即可见」，不构成越权。
   无档案的管理员账号（如 admin / backoffice）对非管理员可见，
   归入「老师」组并以「管理员」徽标区分。

2) /edu/backend/relink_identity 老账号补挂身份（教务 + 系统管理员，t13 起）：
   列出尚未挂接 op.student / op.parent / op.faculty 的账号，
   逐行选择身份与对应人员后批量挂接 user_id（一人一挂）。
   写路径沿用 edu_portal 纪律：控制器 sudo() + 后台组门槛校验。
"""
from odoo import http
from odoo.http import request

# 身份反查/正向的**唯一实现**（edu_portal 依赖 edu_schedule，无环）。
# 禁止在本文件另写 (user_id, '=', uid) / partner.user_id 单链反查。
from odoo.addons.edu_schedule.models.identity import (
    faculty_of_user, parent_of_user, student_of_user, users_of_profile)

from .main import current_student, is_backoffice
from .roles import current_faculty, current_parent

# 技术账号（公众用户 / OdooBot / 系统用户）：不出现在通讯录与补挂列表
_TECH_LOGINS = {'__system__', '__oe__', 'OdooBot', 'public'}


def _is_admin():
    """管理员口径：系统管理员（superuser/system 组）或教务处后台管理员。"""
    user = request.env.user
    return user._is_admin() or user.has_group(
        'openeducat_core.group_op_back_office_admin')


def _truncate(text, limit=60):
    text = (text or '').strip()
    return text if len(text) <= limit else text[:limit - 1] + '…'


def relink_guard_reason(user, person):
    """老账号补挂身份的「一人一挂」写入前置守卫；返回 None = 可挂，否则人话原因。

    为什么必须**双向**（判漏都造成不可逆的身份错挂，不是「显示为空」）：
      · 档案侧判漏 ⇒ 同一份学生/教师/家长档案被绑到两个账号上：甲的成绩、
        课表、账单会出现在乙的账号里；通知、权限、账单归属变成「谁后绑谁说话」。
      · 账号侧判漏 ⇒ 同一个账号连挂两份档案（原实现**完全不查**这一侧）。

    口径（全部来自唯一实现 edu_schedule/models/identity.py，禁止第二套）：
      · 档案 → 账号：users_of_profile = ① 档案自身 user_id ∪ ② 伙伴 user_id
        ∪ ③ 伙伴 user_ids（Odoo 19 规范反向，core res_partner.py:287）。
        原实现只查 ①② ⇒ 漏掉链③（「文件账号挂在该伙伴名下、销售员列为空」
        这种脚本/接口建号形态），实测复现见 tests/smoke/identity_guard_batch1.py。
      · 账号 → 档案：student_of_user / faculty_of_user / parent_of_user（①→②）。
      两侧都是「只加不减」：原实现判「已占用」的每一条，改后仍判「已占用」。

    **幂等**：同一个「账号 ↔ 档案」对重新提交必须仍然放行（守卫只拒别人）。
    """
    if not user or not person:
        return '账号或对应人员无效'
    owners = users_of_profile(person) - user
    if owners:
        return '该人员已绑定其他账号（%s），请先在后台解绑后再挂接' % '、'.join(
            owners.mapped('login'))
    held = []
    for finder, model in ((student_of_user, 'op.student'),
                          (faculty_of_user, 'op.faculty'),
                          (parent_of_user, 'op.parent')):
        rec = finder(user.env, user.id)
        if rec and rec != person:
            held.append('%s#%s' % (model, rec.id))
    if held:
        return '该账号已挂接其他身份档案（%s），一个账号只能挂一份档案' % '、'.join(held)
    return None


class EduContacts(http.Controller):

    # ------------------------------------------------------------------
    # 门户通讯录 /my/contacts
    # ------------------------------------------------------------------
    @http.route('/my/contacts', type='http', auth='user', website=True)
    def my_contacts(self, **kw):
        env = request.env
        Fac = env['op.faculty'].sudo()
        Stu = env['op.student'].sudo()
        Par = env['op.parent'].sudo()
        Session = env['op.session'].sudo()
        StuCourse = env['op.student.course'].sudo()

        fac = current_faculty()
        stu = current_student()
        par = current_parent()
        admin = _is_admin()

        # ---- 熟人圈矩阵：算出三类可见记录 id 集合 ----
        f_ids, s_ids, p_ids = set(), set(), set()
        # 学生专属：同班同学（只姓名 + 班名）；其余角色保持 None（不渲染该段）
        classmates, my_class_label = None, ''
        if admin:
            f_ids = set(Fac.search([]).ids)
            s_ids = set(Stu.search([]).ids)
            p_ids = set(Par.search([]).ids)
        elif fac:
            f_ids = {fac.id}
            batches = Session.search(
                [('faculty_id', '=', fac.id)]).mapped('batch_id')
            s_ids = set(Stu.search(
                [('course_detail_ids.batch_id', 'in', batches.ids)]).ids)
            p_ids = set(Par.search(
                [('student_ids', 'in', list(s_ids))]).ids)
        elif stu:
            s_ids = {stu.id}
            batches = StuCourse.search(
                [('student_id', '=', stu.id)]).mapped('batch_id')
            f_ids = set(Session.search(
                [('batch_id', 'in', batches.ids)]).mapped('faculty_id').ids)
            # 需求 7 G6 / 校长拍板 P3-(a)：学生看得见**同班同学**，
            # 但只给「姓名 + 班名」——不给学号、头像、邮箱、手机。
            # 口径与全线一致：凡 batch_id 相同即为同班（合班亦然）；
            # 一个学生可能属多个班 ⇒ 同班同学取**并集**
            # （照 study.py:30-40 的 mapped('batch_id') 口径）。
            my_batches = StuCourse.search(
                [('student_id', '=', stu.id)]).mapped('batch_id')
            my_class_label = ' / '.join(
                n for n in dict.fromkeys(my_batches.mapped('name')) if n)
            mate_ids = sorted({sid for sid in StuCourse.search(
                [('batch_id', 'in', my_batches.ids),
                 ('student_id', '!=', stu.id)]).mapped('student_id').ids})
            classmates = []
            for mate in Stu.search([('id', 'in', mate_ids)], order='name'):
                names = []
                for sc in StuCourse.search(
                        [('student_id', '=', mate.id),
                         ('batch_id', 'in', my_batches.ids)]):
                    bname = sc.batch_id.name if sc.batch_id else ''
                    if bname and bname not in names:
                        names.append(bname)
                classmates.append({
                    'name': mate.name or '',
                    'class_name': ' / '.join(names),
                })
        elif par:
            s_ids = set(par.student_ids.ids)
            p_ids = {par.id}
            child_ids = list(s_ids)
            batches = StuCourse.search(
                [('student_id', 'in', child_ids)]).mapped('batch_id')
            f_ids = set(Session.search(
                [('batch_id', 'in', batches.ids)]).mapped('faculty_id').ids)

        # ---- 管理员（无档案的 admin 账号）对非管理员可见 ----
        staff = self._admin_staff() if not admin else []

        def _teacher_entry(f):
            parts = []
            if f.main_department_id:
                parts.append(f.main_department_id.name)
            subs = f.faculty_subject_ids.mapped('name')
            if subs:
                parts.append('、'.join(subs))
            return {
                'name': f.name or f.partner_id.name or '',
                'role': '教师',
                'badge_cls': 'text-bg-primary',
                'subtitle': _truncate(' · '.join(parts)) or '教师',
                'email': (f.partner_id.email or '') if f.partner_id else '',
                'phone': (f.partner_id.phone or '') if f.partner_id else '',
                'partner_id': f.partner_id.id if f.partner_id else 0,
            }

        def _student_entry(s):
            sc = StuCourse.search(
                [('student_id', '=', s.id), ('state', '=', 'running')],
                limit=1) or StuCourse.search(
                [('student_id', '=', s.id)], limit=1)
            line = ' / '.join(x for x in (
                sc.course_id.name if sc and sc.course_id else '',
                sc.batch_id.name if sc and sc.batch_id else '') if x)
            return {
                'name': s.name or '',
                'role': '学生',
                'badge_cls': 'text-bg-success',
                'subtitle': _truncate(line, 40) or '学生',
                'email': (s.partner_id.email or '') if s.partner_id else '',
                'phone': (s.partner_id.phone or '') if s.partner_id else '',
                'partner_id': s.partner_id.id if s.partner_id else 0,
            }

        def _parent_entry(p):
            kids = '、'.join(p.student_ids.mapped('name'))
            return {
                'name': p.name.name or '',
                'role': '家长',
                'badge_cls': 'text-bg-info',
                'subtitle': _truncate(('孩子：' + kids) if kids else '家长', 40),
                'email': p.email or (p.name.email or ''),
                'phone': p.mobile or (p.name.phone or ''),
                'partner_id': p.name.id if p.name else 0,
            }

        teachers = [_teacher_entry(f) for f in Fac.search(
            [('id', 'in', sorted(f_ids))], order='name')]
        teachers += staff
        students = [_student_entry(s) for s in Stu.search(
            [('id', 'in', sorted(s_ids))], order='name')]
        parents = [_parent_entry(p) for p in Par.search(
            [('id', 'in', sorted(p_ids))], order='name')]

        groups = []
        if teachers:
            groups.append({'key': 'teachers', 'title': '老师',
                           'icon': 'fa-user-circle-o', 'items': teachers})
        if students:
            groups.append({'key': 'students', 'title': '学生',
                           'icon': 'fa-graduation-cap', 'items': students})
        if parents:
            groups.append({'key': 'parents', 'title': '家长',
                           'icon': 'fa-users', 'items': parents})

        return request.render('edu_portal.edu_contacts', {
            'title': '通讯录',
            'page_name': 'contacts',
            'groups': groups,
            'classmates': classmates,
            'my_class_label': my_class_label,
        })

    def _admin_staff(self):
        """无档案的学校管理员账号（系统组/教务处后台组），供熟人圈展示。"""
        env = request.env
        Users = env['res.users'].sudo()
        Stu = env['op.student'].sudo()
        Par = env['op.parent'].sudo()
        Fac = env['op.faculty'].sudo()
        groups = [
            env.ref('base.group_system').id,
            env.ref('openeducat_core.group_op_back_office_admin').id,
        ]
        candidates = Users.search(
            [('group_ids', 'in', groups), ('active', '=', True)])
        # 仅按登录名排除技术账号（本库 admin 用户 id=2，不能按 id 排除）
        candidates = candidates.filtered(
            lambda u: u.login not in _TECH_LOGINS)
        if not candidates:
            return []
        linked = set()
        linked |= set(Stu.search(
            [('user_id', 'in', candidates.ids)]).mapped('user_id').ids)
        linked |= set(Par.search(['|',
            ('user_id', 'in', candidates.ids),
            ('name.user_id', 'in', candidates.ids)]).mapped('user_id').ids)
        linked |= set(Fac.search(
            [('user_id', 'in', candidates.ids)]).mapped('user_id').ids)
        out = []
        for u in candidates:
            if u.id in linked:
                continue
            out.append({
                'name': u.name or u.login,
                'role': '管理员',
                'badge_cls': 'text-bg-dark',
                'subtitle': '学校管理员',
                'email': u.email or '',
                'phone': '',
                'partner_id': u.partner_id.id if u.partner_id else 0,
            })
        return out


class EduIdentityRelink(http.Controller):
    """老账号补挂身份后台小工具（教务 + 系统管理员）。

    守卫与 main.is_backoffice 同源（= system 组 或 教务处后台组）：
    把老账号挂到学生/家长/教师档案属教务本职，与 ledger 的 _ledger_guard 同一口径。
    本工具只写 op.student/op.parent/op.faculty 的 user_id（一人一挂），
    **不涉及任何提权路径**（不写 res.users.group_ids）。
    """

    def _allowed(self):
        return is_backoffice(request.env.user)

    # ------------------------------------------------------------------
    # 列表：未挂接身份的账号
    # ------------------------------------------------------------------
    @http.route('/edu/backend/relink_identity', type='http', auth='user',
                website=True)
    def relink_form(self, **kw):
        if not self._allowed():
            return request.redirect('/my/home')
        env = request.env
        Users = env['res.users'].sudo()
        Stu = env['op.student'].sudo()
        Par = env['op.parent'].sudo()
        Fac = env['op.faculty'].sudo()
        StuCourse = env['op.student.course'].sudo()

        # 已挂接身份的账号集合（学生=自身 user_id；家长=自身/partner；
        # 教师=委托 partner.user_id）
        linked = set()
        linked |= set(Stu.search([('user_id', '!=', False)])
                      .mapped('user_id').ids)
        linked |= set(Par.search(['|', ('user_id', '!=', False),
                                  ('name.user_id', '!=', False)])
                      .mapped('user_id').ids)
        linked |= set(Fac.search([('user_id', '!=', False)])
                      .mapped('user_id').ids)

        users = []
        for u in Users.search([('active', '=', True)], order='login'):
            if u.login in _TECH_LOGINS or u.id in linked:
                continue
            users.append({
                'id': u.id,
                'login': u.login,
                'name': u.name or '',
                'group_label': '内部用户' if u.has_group('base.group_user')
                else '门户用户',
            })

        def _sc_label(sc):
            return ' / '.join(x for x in (
                sc.course_id.name if sc and sc.course_id else '',
                sc.batch_id.name if sc and sc.batch_id else '') if x)

        students = []
        for s in Stu.search([], order='name'):
            sc = StuCourse.search(
                [('student_id', '=', s.id), ('state', '=', 'running')],
                limit=1) or StuCourse.search(
                [('student_id', '=', s.id)], limit=1)
            label = s.name or ''
            line = _sc_label(sc)
            if line:
                label += '（' + line + '）'
            students.append({'id': s.id, 'label': label})
        parents = []
        for p in Par.search([], order='name'):
            kids = '、'.join(p.student_ids.mapped('name'))
            label = p.name.name or ''
            if kids:
                label += '（孩子：' + _truncate(kids, 20) + '）'
            parents.append({'id': p.id, 'label': label})
        faculties = []
        for f in Fac.search([], order='name'):
            faculties.append({'id': f.id, 'label': (f.name or '') + '（教师）'})

        return request.render('edu_portal.edu_relink_identity', {
            'title': '老账号补挂身份',
            'page_name': 'relink_identity',
            'users': users,
            'students': students,
            'parents': parents,
            'faculties': faculties,
            'ok_count': int(kw.get('ok', 0) or 0),
            'skip_count': int(kw.get('skip', 0) or 0),
        })

    # ------------------------------------------------------------------
    # 批量挂接（POST）
    # ------------------------------------------------------------------
    @http.route('/edu/backend/relink_identity/save', type='http',
                auth='user', methods=['POST'], website=True, csrf=True)
    def relink_save(self, **post):
        if not self._allowed():
            return request.redirect('/my/home')
        env = request.env
        Users = env['res.users'].sudo()
        Stu = env['op.student'].sudo()
        Par = env['op.parent'].sudo()
        Fac = env['op.faculty'].sudo()
        ok = skip = 0
        dbg = []
        for key, val in post.items():
            if not str(key).startswith('person_') or not val:
                continue
            try:
                uid = int(key[len('person_'):])
                role, pid_s = val.split(':', 1)
                pid = int(pid_s)
            except (ValueError, TypeError):
                dbg.append('parse-bad:%s=%s' % (key, val))
                skip += 1
                continue
            user = Users.browse(uid)
            if not user.exists():
                dbg.append('no-user:%s' % uid)
                skip += 1
                continue
            # 注意：Odoo 19 里 env['op.student'] 是空记录集（falsy），
            # 不能用 dict.get(role) 后判空——必须直接 if/elif 分支取模型
            if role == 'student':
                person = Stu.search([('id', '=', pid)], limit=1)
            elif role == 'parent':
                person = Par.search([('id', '=', pid)], limit=1)
            elif role == 'faculty':
                person = Fac.search([('id', '=', pid)], limit=1)
            else:
                person = None
            if not person:
                dbg.append('no-person-s:%s:%s:%s' % (uid, role, pid))
                skip += 1
                continue
            # 一人一挂（**写入前**守卫，双向）：口径与实现在 relink_guard_reason
            # （唯一实现 edu_schedule/models/identity.py）。原实现只查链①两条，
            # 且完全不查「该账号是否已挂别的档案」⇒ 抢绑与一人多绑都能过
            # （实测复现：tests/smoke/identity_guard_batch1.py 的 before 相位）。
            reason = relink_guard_reason(user, person)
            if reason:
                # 机器可读前缀 + 人话原因（页面横幅是既有的「跳过 N 个（…或
                # 人员已绑定其他账号）」，文案不动；dbg 让教务在 URL 上看到是哪一条）
                code = ('user-taken-skip'
                        if reason.startswith('该账号已挂接其他身份档案')
                        else 'linked-skip')
                detail = reason.replace(':', '·').replace(';', '·')
                dbg.append('%s:%s:%s:%s:%s' % (code, uid, role, pid, detail))
                skip += 1
                continue
            try:
                if role == 'faculty':
                    person.partner_id.write({'user_id': uid})
                else:
                    person.write({'user_id': uid})
                    if role == 'parent' and person.name:
                        person.name.write({'user_id': uid})
                ok += 1
            except Exception as e:
                dbg.append('write-err:%s:%s:%s:%s' % (uid, role, pid, repr(e)[:80]))
                skip += 1
        return request.redirect(
            f'/edu/backend/relink_identity?ok={ok}&skip={skip}'
            + ('&dbg=' + ';'.join(dbg) if dbg else ''))