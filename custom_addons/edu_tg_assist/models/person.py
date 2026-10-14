# -*- coding: utf-8 -*-
"""人员-ID 映射 —— /dm 张经理 靠它找人的私聊 chat_id。

⚠ 只收「主动向机器人发过 /start 并自报姓名」的人。
Telegram 平台限制：机器人不能主动向从未和它说过话的用户发私聊 —— 这是平台机制，不是我们的选择。
**不做**「扫群成员自动建人」：那会把没同意的人拉进来。
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class EduTgAssistPerson(models.Model):
    _name = 'edu.tg.assist.person'
    _description = 'Telegram 人员映射'
    _order = 'name, id'

    tg_user_id = fields.Char('Telegram 用户 ID', required=True, index=True,
                             help='from.id。唯一：一个人只登记一次。')
    chat_id = fields.Char('私聊 chat_id', required=True,
                          help='私聊的 chat.id。多数情况下等于 tg_user_id，但不假定相等。')
    name = fields.Char('姓名', required=True, help='对方自报的真实姓名。')
    tg_name = fields.Char('Telegram 昵称', help='仅供教务认人，不是身份校验。')
    role = fields.Selection([
        ('admin', '行政'),
        ('teacher', '教师'),
        ('dorm_head', '宿舍长'),
        ('student', '学生'),
        ('other', '其他'),
    ], string='角色', default='other', required=True)
    active = fields.Boolean('启用', default=True)
    note = fields.Char('备注')
    # 网站账号（对接选项 b 用）：站内通知桥要按它把「发给某个网站用户的站内信」
    # 转成这个人的 Telegram 私聊。留空 = 这个人没接网站账号，桥只认得出别人。
    user_id = fields.Many2one('res.users', '网站账号', index=True,
                              ondelete='set null',
                              help='把这个人接到教务网站上的账号；站内通知桥按它找收件人。')

    # ---- 按钮化界面的中间状态（2026-10-13 用户反馈「不想记指令」后加）----
    # 老师点「📢 发通知到群」→ 点群名之后，机器人要**等他下一条正文**才知道发什么。
    # 这段等待就存在本人这条登记上（不另立表）：ui_state 说「在等什么」、
    # ui_target 说「发给谁」、ui_draft 是已经收到、待他确认的那段正文。
    # 任何一条指令、任何一次取消、任何一次发完，都会立刻清空它。
    ui_state = fields.Selection([
        ('notify', '待发群通知（等正文）'),
        ('dm', '待发一对一私发（等正文）'),
    ], string='按钮流程状态')
    ui_target = fields.Char('按钮流程目标',
                            help='edu.tg.assist.chat 或 edu.tg.assist.person 的记录 id。')
    ui_draft = fields.Text('待确认正文')

    # Odoo 19 新约束 API（旧 _sql_constraints 只打 WARNING、不再被消费）
    _tg_user_id_uniq = models.Constraint(
        'unique(tg_user_id)', '一个 Telegram 账号只能登记一次。')

    @api.model
    def upsert_from_user(self, user, chat_id):
        uid = user.get('id')
        if not uid:
            return self.browse()
        # active_test=False：被 /stop 停用（Odoo 归档）的人必须还能被认出来，
        # 否则这里会再 create 一条同 tg_user_id 的记录 —— 撞唯一约束直接报错（D3 配套）。
        rec = self.sudo().with_context(active_test=False).search(
            [('tg_user_id', '=', str(uid))], limit=1)
        tg_name = ' '.join(x for x in [user.get('first_name'), user.get('last_name')] if x)
        vals = {'chat_id': str(chat_id), 'tg_name': tg_name}
        if rec:
            # D3 配套：被 /stop 停用的人（active=False）**不许**因为随后任何一条消息
            # 把私聊地址写回来 —— 否则「不再私聊打扰你」当场破功（一句「你好」就复活）。
            # 只有他自己发 /start 才恢复地址，由 _cmd_start 显式写回。
            if not rec.active:
                vals.pop('chat_id')
            rec.write(vals)
            return rec
        # 首次见到：姓名先留 Telegram 昵称，等对方 /start 时自报真名再改
        rec = self.sudo().create(dict(vals, tg_user_id=str(uid), name=tg_name or str(uid)))
        # C1 通知**不在这里发**（2026-10-13 修）：本方法只负责建人，而「这个人还需不需要
        # 人工标角色」要等这条消息被处理完才知道。带绑定码的首次登记（/start BIND-XXXXXX）
        # 是同一请求里先 create（role=other）再 redeem（role=admin）—— 在这里发就会给一个
        # **刚刚已经是行政**的人发「新登记…请去后台标成行政/教师/宿舍长」的假警报
        # （2026-10-12 Sarah💌 的真实案例）。改由调用方在分发结束后调
        # notify_new_if_needs_label(rec, was_new)。
        return rec

    @api.model
    def notify_new_if_needs_label(self, rec, was_new):
        """C1（2026-10-13 修）：新人通知只在「这条消息处理完之后他仍需要人工标角色」时才发。

        调用点：`edu.tg.assist.bot._handle_private` 的**分发结束处**（回复发出去之后）。
        两类人**不发**：
        · was_new=False —— 老熟人，通知只发一次（首次登记那次）。
        · role != 'other' —— 这一条消息里他已经把身份绑好了（/start BIND-XXXXXX → /bind），
          这时候再叫管理员「去后台把他标成行政/教师/宿舍长」是过时的假警报。
        **永不抛异常**：通知发不出去不能反过来把对方的 /start 打挂。
        """
        if not was_new or not rec:
            return False
        if rec.role != 'other':
            return False
        return self._notify_owner_new_person(rec)

    @api.model
    def _notify_owner_new_person(self, rec):
        """C1 —— 有人新登记时，私聊通知管理员（edu_tg_assist.owner_user_id）。

        为什么按 owner 参数：与 F5 @提醒完全同一套口径（谁在管这个机器人）。
        未配置 owner、或 owner 本人还没私聊登记过 ⇒ **只写日志，不猜人**。
        **永不抛异常**：通知发不出去不能反过来把对方的 /start 打挂。
        """
        try:
            owner_tg = (self.env['ir.config_parameter'].sudo()
                        .get_param('edu_tg_assist.owner_user_id') or '').strip()
            if not owner_tg:
                _logger.info('edu_tg_assist: 未配置 edu_tg_assist.owner_user_id，'
                             '新登记 #%s 不发通知', rec.id)
                return False
            owner = self.sudo().search(
                [('tg_user_id', '=', owner_tg), ('active', '=', True)], limit=1)
            if not owner or not owner.chat_id:
                _logger.info('edu_tg_assist: owner（tg=%s）还没登记私聊，新登记 #%s 不发通知',
                             owner_tg, rec.id)
                return False
            self.env['edu.tg.assist.api'].sudo().send_message(
                owner.chat_id,
                '新登记：%s（Telegram：%s）。' % (rec.name or '—', rec.tg_name or '—') +
                chr(10) + '这个人第一次私聊机器人，身份还没绑定。' +
                chr(10) + '若是教职工：到后台「班务机器人 → 人员映射」把角色标成 行政/教师/宿舍长，'
                '或直接发他一张绑定码（他发 /bind BIND-XXXXXX 即可自动绑定）。' +
                chr(10) + '标好之后他发任何消息都会进班务助手；在那之前只认指令。',
                kind='admin_notice')
            return True
        except Exception as exc:  # noqa: BLE001
            _logger.warning('edu_tg_assist: 新登记通知失败：%s', type(exc).__name__)
            return False

    @api.model
    def find_by_name(self, name):
        """/dm 张经理 —— 支持精确与包含匹配；多个命中时由调用方提示「不唯一」。"""
        name = (name or '').strip()
        if not name:
            return self.browse()
        exact = self.sudo().search([('name', '=', name), ('active', '=', True)], limit=2)
        if exact:
            return exact
        return self.sudo().search([('name', 'ilike', name), ('active', '=', True)], limit=5)
