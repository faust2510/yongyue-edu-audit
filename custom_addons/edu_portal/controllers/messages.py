# -*- coding: utf-8 -*-
"""v2.1-B9：轻量双向私信（edu.message 门户会话界面）。

1) /my/messages 会话列表：与我相关的全部会话按最近消息倒序分组，
   行内未读数徽标；顶部「发起新对话」选择器只列出熟人圈可见对象
   （复用 B8 通讯录同一套可见性计算，见 _circle_user_ids）。
2) /my/messages/<uid> 对话视图：双方消息时间线，打开即把对方发来的
   消息标记已读；越权访问直接拦截（redirect 提示，不渲染任何数据）。
3) /my/messages/send 发送：POST 前再次校验目标在本人熟人圈内，
   教师↔教师第一版不开放；越权一律拒绝并给出提示。
4) /my/messages/poll 轮询小请求：返回我的未读数 / 各会话未读数 /
   指定会话的新消息（返回即标记已读），供 30s 轮询与未读角标刷新。
5) 系统通知（本次修复）：对手方为技术账号（_TECH_LOGINS，如 __system__）
   的会话过去被 _participant 判为 None 而整行丢弃 —— 角标（原始未读计数）
   算它、列表与对话页却打不开，未读永远清不掉。现在：列表照常列出并统一
   标识为「系统通知」（按 _TECH_LOGINS 规则，不硬编码某个登录名）、对话页
   允许打开以触发既有的「打开即已读」，但**只读**（隐藏回复框，发送路径
   照旧拒绝）且不进「发起新对话」选择器（_circle_user_ids 不变）。
  人类账号的越权拦截一字未改。

权限矩阵（同 B8 通讯录可见性，Q2.1 拍板）：
- 管理员：全部（含教师；教师↔教师限制只约束普通教师互发）
- 教师：本班学生/家长 + 管理员；教师↔教师不开放
- 学生：自己的教师 + 管理员
- 家长：自己孩子的任课教师/孩子 + 管理员
写路径沿用 edu_portal 纪律：控制器 sudo() + 显式权限校验。
"""
from psycopg2.errors import UndefinedColumn, UndefinedTable

from odoo import fields, http
from odoo.fields import Datetime as Dt
from odoo.http import request

from odoo.addons.edu_schedule.models.identity import (
    faculty_of_user, parent_of_user, student_of_user, users_of_profile)

from .contacts import _TECH_LOGINS
from .main import current_student
from .roles import current_faculty, current_parent

# 正文长度上限（轻量纯文本私信）
_BODY_LIMIT = 5000
# 会话列表防御性上限：只装载最近 N 条我参与的消息（避免个人消息量极大时
# 全表载入内存）；行级分页/游标留给后续迭代（评审非阻塞建议，当前量级安全）。
_LIST_MSG_CAP = 1000


def _messages_ready():
    """edu.message 可用性探测（部署窗口降级守卫）。

    代码先于 -u 升级落地（或升级中断）时，模型可能已随 Python 导入注册、
    但表/列尚未创建——`'edu.message' in env` 判存拦不住这种情况，必须在
    表级再用 UndefinedTable/UndefinedColumn 兜底（对齐 batch2.py 内
    safe_count 的 try/except 惯例）。注意：捕获 SQL 错误后必须用
    savepoint() 回滚到内层保存点，否则事务已中止，本请求后续任何查询
    （其他卡片计数/渲染）都会以 InFailedSqlTransaction 复炸成 500。
    旧库期间：
    - /my/home 计数静默返回 0（私信提醒卡不渲染，页面照常可用）；
    - 私信路由统一重定向回首页，不抛 500；
    - 轮询返回空未读 JSON（客户端角标逻辑不受影响）。
    """
    if 'edu.message' not in request.env:
        return False
    try:
        with request.env.cr.savepoint():
            request.env['edu.message'].sudo().search_count([('id', '=', 0)])
        return True
    except (UndefinedTable, UndefinedColumn):
        return False


def _is_admin_user(user):
    """管理员口径：系统管理员（superuser/system 组）或教务处后台管理员。"""
    return user._is_admin() or user.has_group(
        'openeducat_core.group_op_back_office_admin')


def _fmt_time(dt):
    """UTC naive → 用户时区墙钟展示（与校历/课表页口径一致）。"""
    if not dt:
        return ''
    return Dt.context_timestamp(request.env.user, dt).strftime('%m-%d %H:%M')


def _identity_user_ids():
    """已挂接身份档案（学生/家长/教师）的账号 id 集合。

    口径统一走 identity.users_of_profile（双向并集）：原实现只认记录自身的
    user_id 列（教师那列=partner.user_id 销售员列）⇒ 脚本新建的账号**不出现
    在任何人的熟人圈里**（私信静默不可达）。
    """
    env = request.env
    users = users_of_profile(env['op.student'].sudo().search([]))
    users |= users_of_profile(env['op.parent'].sudo().search([]))
    users |= users_of_profile(env['op.faculty'].sudo().search([]))
    return set(users.ids)


def _admin_user_ids():
    """管理员账号集合（系统组/教务处后台组，排除技术账号）。
    有身份档案的管理员在通讯录以本人身份出现，无档案的以「管理员」徽标
    出现在老师组——两类管理员都可作为私信对象（管理员=全部）。"""
    env = request.env
    groups = [
        env.ref('base.group_system').id,
        env.ref('openeducat_core.group_op_back_office_admin').id,
    ]
    candidates = env['res.users'].sudo().search(
        [('group_ids', 'in', groups), ('active', '=', True)])
    return {u.id for u in candidates if u.login not in _TECH_LOGINS}


def _circle_user_ids():
    """当前登录用户的私信熟人圈（可发起对话的目标账号 id 集合）。

    与 B8 通讯录可见性一致：管理员=全部身份账号+管理员；
    教师=本班学生/家长+管理员；学生=自己教师+管理员；
    家长=孩子任课教师/孩子+管理员；无身份账号=空集。
    """
    env = request.env
    me = request.env.user
    Fac = env['op.faculty'].sudo()
    Stu = env['op.student'].sudo()
    Par = env['op.parent'].sudo()
    Session = env['op.session'].sudo()
    StuCourse = env['op.student.course'].sudo()

    if _is_admin_user(me):
        # 管理员=全部
        return _identity_user_ids() | _admin_user_ids()

    out = set()
    fac = current_faculty()
    stu = current_student()
    par = current_parent()
    if fac:
        batches = Session.search(
            [('faculty_id', '=', fac.id)]).mapped('batch_id')
        s_ids = Stu.search(
            [('course_detail_ids.batch_id', 'in', batches.ids)]).ids
        # 学生 / 家长也用双向并集（只认 user_id 列会漏掉脚本新建的账号）
        out |= set(users_of_profile(Stu.browse(s_ids)).ids)
        out |= set(users_of_profile(
            Par.search([('student_ids', 'in', s_ids)])).ids)
        return out | _admin_user_ids()
    if stu:
        batches = StuCourse.search(
            [('student_id', '=', stu.id)]).mapped('batch_id')
        f_ids = Session.search(
            [('batch_id', 'in', batches.ids)]).mapped('faculty_id').ids
        out |= set(users_of_profile(Fac.browse(f_ids)).ids)
        # 学生→自己的教师+管理员（不含其他学生/家长，教师↔教师互发同理不开放）
        return out | _admin_user_ids()
    if par:
        s_ids = list(set(par.student_ids.ids))
        batches = StuCourse.search(
            [('student_id', 'in', s_ids)]).mapped('batch_id')
        f_ids = Session.search(
            [('batch_id', 'in', batches.ids)]).mapped('faculty_id').ids
        out |= set(users_of_profile(Fac.browse(f_ids)).ids)
        # 自己的孩子（通讯录「自知即可见」同款）
        out |= set(users_of_profile(Stu.browse(s_ids)).ids)
        return out | _admin_user_ids()
    return out


def _participant(user):
    """账号资料卡（对话列表/对话页头部复用）。"""
    env = request.env
    uid = user.id
    if not user.exists() or user.login in _TECH_LOGINS:
        return None
    Stu = env['op.student'].sudo()
    s = student_of_user(env, uid)
    if s:
        sc = env['op.student.course'].sudo().search(
            [('student_id', '=', s.id), ('state', '=', 'running')],
            limit=1) or env['op.student.course'].sudo().search(
            [('student_id', '=', s.id)], limit=1)
        line = ' / '.join(x for x in (
            sc.course_id.name if sc and sc.course_id else '',
            sc.batch_id.name if sc and sc.batch_id else '') if x)
        return {
            'id': uid, 'name': s.name or user.name or '',
            'role': '学生', 'badge_cls': 'text-bg-success',
            'subtitle': line or '学生',
            'avatar': s.partner_id.id if s.partner_id else 0,
        }
    # 教师：双向并集（原写法把 user_id 与 partner_id.user_id 并列成 OR ——
    # op.faculty.user_id 就是 related partner_id.user_id，两条逐字生成相同
    # 的 SQL，是同义反复而非兜底）
    f = faculty_of_user(env, uid)
    if f:
        return {
            'id': uid, 'name': f.name or user.name or '',
            'role': '教师', 'badge_cls': 'text-bg-primary',
            'subtitle': '教师',
            'avatar': f.partner_id.id if f.partner_id else 0,
        }
    p = parent_of_user(env, uid)
    if p:
        kids = '、'.join(p.student_ids.mapped('name'))
        return {
            'id': uid, 'name': p.name.name or user.name or '',
            'role': '家长', 'badge_cls': 'text-bg-info',
            'subtitle': ('家长（孩子：' + kids + '）') if kids else '家长',
            'avatar': p.name.id if p.name else 0,
        }
    if _is_admin_user(user):
        return {
            'id': uid, 'name': user.name or user.login,
            'role': '管理员', 'badge_cls': 'text-bg-dark',
            'subtitle': '学校管理员',
            'avatar': user.partner_id.id if user.partner_id else 0,
        }
    return None


def _is_tech_user(user):
    """技术/系统账号判定：与通讯录共用同一份 _TECH_LOGINS 名单。

    不硬编码 '__system__'——技术登录名可能不止一个，且未来可能新增。
    """
    return bool(user) and user.exists() and user.login in _TECH_LOGINS


def _system_info(uid):
    """「系统通知」会话资料卡（对手方为技术账号时替代 _participant）。

    技术账号的 user.name 是内部名（系统 / OdooBot），直接展示既无意义又
    泄露内部实现；统一折叠成一类可识别的「系统通知」入口。is_system 供
    模板区分图标与隐藏回复框。
    """
    return {
        'id': uid, 'name': '系统通知', 'role': '系统',
        'badge_cls': 'text-bg-secondary',
        'subtitle': '系统自动发送的提醒，仅可查看，不可回复',
        'avatar': 0,
        'is_system': True,
    }


def _conversation_info(user):
    """会话对手方资料卡：技术账号 → 系统通知；其余沿用 _participant。

    仅供**会话列表/对话页渲染**使用。写路径（发送）与选择器仍用 _participant
    与 _circle_user_ids，因此技术账号始终不可回复、不可作为新对话对象。
    """
    if _is_tech_user(user):
        return _system_info(user.id)
    return _participant(user)


class EduMessages(http.Controller):

    # ------------------------------------------------------------------
    # /my/messages 会话列表
    # ------------------------------------------------------------------
    @http.route('/my/messages', type='http', auth='user', website=True)
    def messages_list(self, **kw):
        if not _messages_ready():
            # 旧库（edu_portal 未 -u 升级）：功能未就绪，回首页避免 500
            return request.redirect('/my/home')
        env = request.env
        me = request.env.user
        Msg = env['edu.message'].sudo()

        msgs = Msg.search(['|', ('sender_id', '=', me.id),
                           ('recipient_id', '=', me.id)],
                          order='id desc', limit=_LIST_MSG_CAP)
        # 倒序取回再翻转为正序：组内最后一条即最近一条
        other_msgs = {}
        for m in reversed(msgs):
            other = m.sender_id.id if m.recipient_id.id == me.id \
                else m.recipient_id.id
            other_msgs.setdefault(other, []).append(m)

        rows = []
        Users = env['res.users'].sudo()
        for other_id, lst in other_msgs.items():
            other = Users.browse(other_id)
            # 技术账号（系统通知）不再整行丢弃：角标既把它算作未读，
            # 列表就必须给出可点击的入口，否则未读永远清不掉。
            info = _conversation_info(other)
            if not info:
                continue
            last = lst[-1]
            unread = sum(1 for m in lst
                         if m.recipient_id.id == me.id and not m.is_read)
            rows.append({
                'href': '/my/messages/%d' % other_id,
                'info': info,
                'last': (last.body or '').strip().replace('\n', ' ')[:60],
                'last_at': _fmt_time(last.sent_at or last.create_date),
                'last_key': last.sent_at or last.create_date,
                'from_me': last.sender_id.id == me.id,
                'unread': unread,
            })
        rows.sort(key=lambda r: (r['last_key'] or r['last_at'], r['href']),
                  reverse=True)

        # 「发起新对话」选择器：熟人圈可见对象（含管理员），排除自己
        circle = sorted(_circle_user_ids() - {me.id})
        picker = []
        for uid in circle:
            info = _participant(Users.browse(uid))
            if info:
                picker.append(info)

        total_unread = sum(r['unread'] for r in rows)
        return request.render('edu_portal.edu_messages', {
            'title': '私信',
            'page_name': 'messages',
            'rows': rows,
            'picker': picker,
            'total_unread': total_unread,
            'has_records': bool(rows),
            'denied': kw.get('denied') == '1',
            'sent': kw.get('sent') == '1',
            'empty_contacts': not picker,
        })

    # ------------------------------------------------------------------
    # /my/messages/<uid> 对话视图
    # ------------------------------------------------------------------
    @http.route('/my/messages/<int:uid>', type='http', auth='user',
                website=True)
    def messages_chat(self, uid, **kw):
        if not _messages_ready():
            return request.redirect('/my/home')
        env = request.env
        me = request.env.user
        Users = env['res.users'].sudo()
        other = Users.browse(uid)
        other_info = _conversation_info(other)
        Msg = env['edu.message'].sudo()
        lo, hi = sorted((me.id, uid))
        thread = Msg.search([('thread_key', '=', '%d-%d' % (lo, hi))],
                            order='id asc')
        if other_info and other_info.get('is_system') and uid != me.id:
            # 系统通知：只放行本人确实参与过的会话（该 thread_key 下已有往来），
            # 技术账号因此不会变成任意 uid 的探测口；本会话只读，不可回复。
            if not thread:
                return request.redirect('/my/messages?denied=1')
        elif not other_info or uid == me.id or uid not in _circle_user_ids():
            # 越权访问（非本人、不在熟人圈、非参与者）一律拦截——人类账号口径未改
            return request.redirect('/my/messages?denied=1')
        # 打开会话即已读：把对方发来的未读消息标记已读
        incoming = thread.filtered(
            lambda m: m.recipient_id.id == me.id and not m.is_read)
        if incoming:
            incoming.write({'is_read': True})
        msgs = []
        for m in thread:
            msgs.append({
                'id': m.id,
                'from_me': m.sender_id.id == me.id,
                'body': m.body or '',
                'at': _fmt_time(m.sent_at or m.create_date),
            })
        last_id = thread[-1].id if thread else 0
        return request.render('edu_portal.edu_messages_chat', {
            'title': '与 %s 的私信' % (other_info['name'] or other.login),
            'page_name': 'messages',
            'other': other_info,
            'msgs': msgs,
            'last_id': last_id,
            'sent': kw.get('sent') == '1',
            # 系统通知只读：模板据此隐藏回复框（服务端发送路径同样拒绝）
            'readonly': bool(other_info.get('is_system')),
        })

    # ------------------------------------------------------------------
    # /my/messages/send 发送（越权拦截）
    # ------------------------------------------------------------------
    @http.route('/my/messages/send', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def messages_send(self, **post):
        if not _messages_ready():
            return request.redirect('/my/home')
        env = request.env
        me = request.env.user
        try:
            uid = int(post.get('uid') or 0)
        except (TypeError, ValueError):
            uid = 0
        target = env['res.users'].sudo().browse(uid)
        target_info = _participant(target)
        # 越权发送拦截：目标不在熟人圈/非参与者/给自己发 → 拒绝
        if not target_info or uid == me.id or uid not in _circle_user_ids():
            return request.redirect('/my/messages?denied=1')
        body = (post.get('body') or '').strip()
        if not body:
            return request.redirect('/my/messages/%d?denied=1' % uid)
        body = body[:_BODY_LIMIT]
        rec = env['edu.message'].sudo().create({
            'sender_id': me.id,
            'recipient_id': uid,
            'body': body,
            'sent_at': fields.Datetime.now(),
        })
        return request.redirect('/my/messages/%d?sent=1' % uid)

    # ------------------------------------------------------------------
    # /my/messages/poll 30s 轮询小请求（JSON）
    # ------------------------------------------------------------------
    @http.route('/my/messages/poll', type='http', auth='user',
                website=True)
    def messages_poll(self, **kw):
        if not _messages_ready():
            # 旧库降级：返回空未读 JSON，客户端角标逻辑不受影响
            return request.make_json_response({'unread': 0, 'convs': []})
        env = request.env
        me = request.env.user
        Msg = env['edu.message'].sudo()
        out = {
            'unread': Msg.unread_count_for(me),
            'convs': [],
        }
        # 各会话未读数（列表页徽标刷新用，只回传有未读的会话）
        if out['unread']:
            unread_msgs = Msg.search(
                [('recipient_id', '=', me.id), ('is_read', '=', False)],
                order='id asc')
            by_sender = {}
            for m in unread_msgs:
                by_sender[m.sender_id.id] = \
                    by_sender.get(m.sender_id.id, 0) + 1
            out['convs'] = [{'uid': sid, 'unread': n}
                            for sid, n in by_sender.items()]

        # 对话页轮询：with=<对方 uid>&after=<已见最大消息 id>
        try:
            with_id = int(kw.get('with') or 0)
            after = int(kw.get('after') or 0)
        except (TypeError, ValueError):
            with_id = after = 0
        if with_id and (with_id == me.id or
                        with_id not in _circle_user_ids()):
            # 越权轮询不返回任何消息内容（仅未读数）
            return request.make_json_response(out)
        if with_id:
            lo, hi = sorted((me.id, with_id))
            domain = [('thread_key', '=', '%d-%d' % (lo, hi))]
            if after:
                domain.append(('id', '>', after))
            news = Msg.search(domain, order='id asc')
            incoming = news.filtered(
                lambda m: m.recipient_id.id == me.id and not m.is_read)
            if incoming:
                incoming.write({'is_read': True})
            if news:
                out['new'] = [{
                    'id': m.id,
                    'from_me': m.sender_id.id == me.id,
                    'body': m.body or '',
                    'at': _fmt_time(m.sent_at or m.create_date),
                } for m in news]
            out['unread_with'] = Msg.search_count([
                ('recipient_id', '=', me.id),
                ('sender_id', '=', with_id),
                ('is_read', '=', False),
            ])
        return request.make_json_response(out)