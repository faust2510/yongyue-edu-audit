# -*- coding: utf-8 -*-
"""F4 打卡闭环 —— 一次带按钮的群发 + 谁点了的记录（F1 定时提醒用它）。

数据模型决定（2026-10-10，计划 B1）：**新立两张表**，而不是给 edu.tg.assist.reply 加一列
poll_id —— reply 的既有语义是「@提醒待办的一条回填」，混进来会让 F5 的统计变得含糊；
分开后两边各自 unique、各自视图、各自回调前缀（ck: / p:），互不影响。

零耦合边界不变（设计文档 §2 B1–B8）：只写本模块自己的表（chat_id / 人名 / 选择），
**不写** edu.checkin.record（要把打卡接进 Odoo 考勤域时另立桥接模块，本轮不做）；
也**不碰** edu.feedback.* / edu_telegram.*（B1/B2/B5）。
"""
import logging

from odoo import api, fields, models

from odoo.addons.edu_tg_assist import polls

_logger = logging.getLogger(__name__)


class EduTgAssistPoll(models.Model):
    _name = 'edu.tg.assist.poll'
    _description = '打卡（一次带按钮的群发）'
    _order = 'id desc'

    name = fields.Char('标题', compute='_compute_name')
    chat_id = fields.Many2one('edu.tg.assist.chat', string='发到哪个群', required=True,
                              ondelete='cascade')
    reminder_id = fields.Many2one('edu.tg.assist.reminder', string='来源规则',
                                  ondelete='set null')
    template_id = fields.Many2one('edu.tg.assist.template', string='来源模板',
                                  ondelete='set null')
    body = fields.Text('正文（发出时的快照）')
    options = fields.Char('选项', default=polls.DEFAULT_OPTIONS, required=True,
                          help='竖线分隔的 ASCII 短值，例如 done|abnormal。')
    expected_role = fields.Selection(polls.ROLE_SELECTION, string='应回的人',
                                     default='dorm_head', required=True,
                                     help='按「人员映射」里的角色算应回/未回名单。'
                                          '名单只含**主动登记过**的人：Telegram 不允许机器人'
                                          '主动私聊从没说过话的人，所以没登记的人收不到这条。')
    state = fields.Selection([
        ('draft', '未发出'),
        ('sent', '已发出'),
        ('closed', '已关闭'),
    ], string='状态', default='draft', required=True, index=True)
    message_id = fields.Char('Telegram 消息 id', readonly=True)
    sent_at = fields.Datetime('发出时间', readonly=True)
    deadline = fields.Datetime('截止时间', help='只给人看，不参与逻辑。')
    reply_ids = fields.One2many('edu.tg.assist.poll.reply', 'poll_id', string='回填')
    expected_count = fields.Integer('应回人数', compute='_compute_stats')
    replied_count = fields.Integer('已回人数', compute='_compute_stats')
    missing_count = fields.Integer('未回人数', compute='_compute_stats')
    missing_names = fields.Char('未回名单', compute='_compute_stats',
                                help='最多列 20 个名字；完整明细看下面的「回填」。')
    note = fields.Char('备注')

    @api.depends('body', 'chat_id', 'sent_at', 'state')
    def _compute_name(self):
        for rec in self:
            when = fields.Datetime.to_string(rec.sent_at) if rec.sent_at else '未发出'
            head = ''
            if rec.body:
                head = (rec.body.strip().splitlines() or [''])[0][:40]
            rec.name = '%s %s' % (when, head or (rec.chat_id.alias or rec.chat_id.title or ''))

    @api.depends('reply_ids.tg_user_id', 'expected_role', 'options')
    def _compute_stats(self):
        for rec in self:
            roster = rec._roster_rows()
            replied = set(str(u) for u in rec.reply_ids.mapped('tg_user_id') if u)
            missing = polls.missing_uids(roster, replied)
            rec.expected_count = len(roster)
            missing_set = set(missing)
            rec.replied_count = len([r for r in roster
                                     if str(r.get('tg_user_id') or '') in replied])
            rec.missing_count = len(missing)
            names = [r.get('name') or r.get('tg_user_id') or '' for r in roster
                     if str(r.get('tg_user_id') or '') in missing_set]
            rec.missing_names = '、'.join(names[:20]) + ('…' if len(names) > 20 else '')

    def _roster_rows(self):
        """应回名单（person 里 active=True 且角色相符的人）。"""
        self.ensure_one()
        rows = self.env['edu.tg.assist.person'].sudo().search_read(
            [('active', '=', True)], ['name', 'role', 'tg_user_id', 'chat_id'])
        return polls.filter_roster(rows, self.expected_role)

    def build_keyboard(self):
        """这条打卡的 inline keyboard；任一按钮不合法 -> None（发纯文本，不整条被拒）。"""
        self.ensure_one()
        row = []
        for value in polls.parse_options(self.options):
            data = polls.build_callback(self.id, value)
            if data is None:
                return None
            row.append({'text': polls.label_for(value), 'callback_data': data})
        if not row:
            return None
        return {'inline_keyboard': [row]}

    def _mark_sent(self, ok, result, err='', with_buttons=True):
        """发送结果回写（由 reminder._do_send 调）。"""
        self.ensure_one()
        vals = {}
        if ok:
            vals['state'] = 'sent'
            vals['sent_at'] = fields.Datetime.now()
            mid = (result or {}).get('message_id')
            if mid:
                vals['message_id'] = str(mid)
            if not with_buttons:
                vals['note'] = '按钮已放弃（选项过长或为空），本条按纯文本发出。'
        else:
            vals['note'] = ('发送失败：%s' % (err or '未知'))[:120]
        self.sudo().write(vals)

    def action_close(self):
        """后台「关闭打卡」：关掉后按钮再点只会收到「已关闭」。"""
        self.ensure_one()
        self.sudo().write({'state': 'closed'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '已关闭',
                'message': '这条打卡关掉了，按钮再点不会落库。',
                'type': 'success',
                'sticky': False,
            },
        }


class EduTgAssistPollReply(models.Model):
    _name = 'edu.tg.assist.poll.reply'
    _description = '打卡回填（谁点了哪个选项）'
    _order = 'replied_at desc, id desc'

    poll_id = fields.Many2one('edu.tg.assist.poll', string='打卡', required=True,
                              ondelete='cascade', index=True)
    person_id = fields.Many2one('edu.tg.assist.person', string='回填人', ondelete='set null')
    tg_user_id = fields.Char('Telegram 用户 ID', required=True, index=True)
    tg_name = fields.Char('Telegram 昵称')
    choice = fields.Char('选择', required=True)
    chat_id = fields.Char('按钮所在群 chat_id', index=True)
    raw_data = fields.Char('原始 callback_data')
    replied_at = fields.Datetime('点击时间', default=fields.Datetime.now, required=True,
                                 index=True)

    _poll_user_uniq = models.Constraint(
        'unique(poll_id, tg_user_id)', '同一条打卡、同一个人只留一行（重复点改选项）。')

    @api.model
    def _tg_assist_handle_callback(self, cq):
        """打卡按钮挂点（bot.py 自动发现）。返回真值 = 已认领（认领了必须 answer）。"""
        if not isinstance(cq, dict):
            return None
        poll_id, choice = polls.parse_callback(cq.get('data'))
        if poll_id is None:
            return None  # 不是打卡按钮：不认领，交给 ck:（F5 待办）或别人

        cq_id = cq.get('id')
        frm = cq.get('from') or {}
        uid = str(frm.get('id') or '')
        # toast 复用 reply.py 的实现（同一份出网与失败口径，避免两处漂移）
        answer = self.env['edu.tg.assist.reply'].sudo()._answer

        person = self.env['edu.tg.assist.person'].sudo().search(
            [('tg_user_id', '=', uid)], limit=1)
        if not person:
            answer(cq_id, '你还没登记：先私聊我发 /start，再发 /name 你的真名。')
            return {'ok': True, 'callback': 'unregistered'}

        poll = self.env['edu.tg.assist.poll'].sudo().browse(poll_id).exists()
        if not poll:
            answer(cq_id, '这条打卡已经不在了。')
            return {'ok': True, 'callback': 'missing_poll'}
        if poll.state != 'sent':
            answer(cq_id, '这条打卡已经关闭了。')
            return {'ok': True, 'callback': 'closed_poll'}
        if choice not in polls.parse_options(poll.options):
            answer(cq_id, '这个选项不在这条打卡里。')
            return {'ok': True, 'callback': 'bad_choice'}

        msg = cq.get('message') or {}
        chat_id = str((msg.get('chat') or {}).get('id') or '')
        tg_name = ' '.join(x for x in [frm.get('first_name'), frm.get('last_name')] if x) \
            or frm.get('username') or ''

        Reply = self.sudo()
        vals = {
            'poll_id': poll.id,
            'person_id': person.id,
            'tg_user_id': uid,
            'tg_name': tg_name,
            'choice': choice,
            'chat_id': chat_id,
            'raw_data': (cq.get('data') or '')[:64],
            'replied_at': fields.Datetime.now(),
        }
        existing = Reply.search([('poll_id', '=', poll.id), ('tg_user_id', '=', uid)], limit=1)
        if existing:
            existing.write(vals)  # 重复点（含改主意）：改这一行，不新增
            rec = existing
        else:
            rec = Reply.create(vals)
        _logger.info('edu_tg_assist: 打卡 #%s 回填 -> %s（%s）', poll.id, choice, person.name)

        answer(cq_id, '已记录：%s。谢谢！' % polls.label_for(choice))
        return {'ok': True, 'poll_reply_id': rec.id, 'choice': choice}
