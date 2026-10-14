# -*- coding: utf-8 -*-
"""F5 @提醒 —— 群里 @校长、15 分钟内没回，就私聊提醒校长。

数据流（三段，互相独立、都可单测）：
  1) 群里出现 @校长的消息        -> _tg_assist_note_group_message() 建一条待办
  2) 校长本人在**同一个群**发言   -> 把该群所有未回待办标 replied_at（只清本群）
  3) cron 每 5 分钟扫一次        -> 超过 N 分钟未回且没私聊提醒过的 -> 私聊提醒一次

纪律（写在最前面，后来人别踩）：
  · 校长的 tg_user_id **只从系统参数 edu_tg_assist.owner_user_id 读**。
    未配置就**不建待办**、只记一条日志 —— **绝不猜**谁是校长（猜错=把别人的 @ 当校长）。
  · 超时分钟数是参数 edu_tg_assist.mention_timeout_minutes，默认 15，**不写死在代码里**。
  · 私聊提醒**只发一次**：dm_sent_at 非空就跳过（否则每 5 分钟骚扰一次）。
  · 「回复了」的判定只看**同一群**：chat_id 不同绝不互相清（跨群清会吞掉别的群的真待办）。
  · 中文注释 / Odoo 19 语法。
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

OWNER_PARAM = 'edu_tg_assist.owner_user_id'
#: 可选的补充参数：Telegram 的 mention 实体只给 @用户名 文本、**不给用户 id**，
#: 所以「@username 形式」的 @ 只有在本参数配了校长用户名时才能识别。
#: 未配置时只认 text_mention（那种带 user 对象的），**不猜**。
OWNER_NAME_PARAM = 'edu_tg_assist.owner_username'
TIMEOUT_PARAM = 'edu_tg_assist.mention_timeout_minutes'
DEFAULT_TIMEOUT_MINUTES = 15
#: 待办摘录进私聊时的最大长度（Telegram 单条 4096，这里远低于上限，只为好读）
MAX_EXCERPT = 120


class EduTgAssistMention(models.Model):
    _name = 'edu.tg.assist.mention'
    _description = '@提醒待办（群里 @校长 后等待其回复）'
    _order = 'mentioned_at desc, id desc'

    name = fields.Char('摘要', compute='_compute_name', store=False)

    chat_id = fields.Char('群 chat_id', required=True, index=True,
                          help='@ 发生的群。判定「回复了」只看这一列相同的记录。')
    chat_title = fields.Char('群名', help='建待办时从 Telegram 抓的群名，便于人工认。')
    message_id = fields.Char('消息 ID', help='Telegram message_id，便于回溯是哪条消息 @ 的。')
    message_text = fields.Text('原消息', help='@ 那条消息的文本（截断保存）。')

    mentioner_user_id = fields.Char('发起人 user id', index=True)
    mentioner_name = fields.Char('发起人')

    owner_user_id = fields.Char('被 @ 的校长 user id', index=True,
                                help='建待办时从系统参数抄一份快照：'
                                     '日后改了参数，也不会让老待办认错人或被错清。')

    mentioned_at = fields.Datetime('@ 时间', default=fields.Datetime.now, required=True, index=True)
    replied_at = fields.Datetime('校长回复时间',
                                 help='校长在**同一个群**发言即视为回复；空 = 还没回。')
    dm_sent_at = fields.Datetime('私聊提醒时间',
                                 help='非空表示已经私聊提醒过一次，不再重复发。')

    state = fields.Selection([
        ('waiting', '等待回复'),
        ('reminded', '已私聊提醒'),
        ('replied', '校长已回复'),
    ], string='状态', compute='_compute_state', store=False)

    @api.depends('replied_at', 'dm_sent_at')
    def _compute_state(self):
        for rec in self:
            if rec.replied_at:
                rec.state = 'replied'
            elif rec.dm_sent_at:
                rec.state = 'reminded'
            else:
                rec.state = 'waiting'

    @api.depends('chat_title', 'chat_id', 'mentioned_at')
    def _compute_name(self):
        for rec in self:
            who = rec.chat_title or rec.chat_id or '?'
            when = rec.mentioned_at and fields.Datetime.to_string(rec.mentioned_at) or '?'
            rec.name = '%s @ %s' % (who, when)

    # ------------------------------------------------------------------ 参数
    @api.model
    def _owner_user_id(self):
        """校长的 tg_user_id（字符串）。未配置返回 '' —— 调用方**必须**把它当「不建待办」。"""
        return (self.env['ir.config_parameter'].sudo().get_param(OWNER_PARAM) or '').strip()

    @api.model
    def _owner_username(self):
        """校长在群里的 @用户名（不含 @，小写）。未配置返回 ''。"""
        v = (self.env['ir.config_parameter'].sudo().get_param(OWNER_NAME_PARAM) or '').strip()
        return v.lstrip('@').lower()

    @api.model
    def _timeout_minutes(self):
        """超时分钟数。参数非法（空/非数字/<=0）一律回落到默认 15。"""
        raw = (self.env['ir.config_parameter'].sudo().get_param(TIMEOUT_PARAM) or '').strip()
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_TIMEOUT_MINUTES
        return n if n > 0 else DEFAULT_TIMEOUT_MINUTES

    # ------------------------------------------------------- 1) 群消息 -> 待办
    @api.model
    def _entity_is_owner(self, entity, text, owner_user_id):
        """这个 @ 实体指的是不是校长？

        · text_mention：Telegram 给了 user 对象 -> 直接比 id，**可靠**。
        · mention（@username 文本）：Telegram **不给** user id，只能在配了
          edu_tg_assist.owner_username 时比用户名；没配就返回 False（不猜）。
        """
        kind = entity.get('type')
        if kind == 'text_mention':
            uid = (entity.get('user') or {}).get('id')
            return uid is not None and str(uid) == str(owner_user_id)
        if kind == 'mention':
            known = self._owner_username()
            if not known:
                return False
            offset = entity.get('offset') or 0
            length = entity.get('length') or 0
            frag = (text or '')[offset:offset + length].lstrip('@').strip().lower()
            return bool(frag) and frag == known
        return False

    @api.model
    def _tg_assist_note_group_message(self, msg, chat, rec, text):
        """群消息监听挂点（bot.py 自动发现）。返回真值 = 已认领。"""
        owner = self._owner_user_id()
        chat_id = str((chat or {}).get('id') or '')
        if not owner:
            # 未配置校长 -> 不建待办。每条群消息都记一次太吵，只记 debug 级。
            _logger.debug('edu_tg_assist: 未配置 %s，@提醒不建待办', OWNER_PARAM)
            return None
        if not chat_id:
            return None

        frm = (msg or {}).get('from') or {}

        # --- 2) 校长本人在群里说话了 -> 清**本群**未回待办
        if str(frm.get('id') or '') == owner:
            return self._mark_replied(chat_id)

        entities = (msg or {}).get('entities') or (msg or {}).get('caption_entities') or []
        if not any((e or {}).get('type') in ('mention', 'text_mention') for e in entities):
            return None
        if not any(self._entity_is_owner(e, text, owner) for e in entities):
            return None

        return self._create_todo(msg, chat, rec, text, owner)

    @api.model
    def _mark_replied(self, chat_id):
        """把该群所有未回待办标 replied_at。**只动 chat_id 相同的**，绝不跨群。"""
        pending = self.sudo().search([('chat_id', '=', chat_id), ('replied_at', '=', False)])
        if not pending:
            return None
        pending.write({'replied_at': fields.Datetime.now()})
        _logger.info('edu_tg_assist: 校长在群 %s 发言，清掉 %d 条未回@待办', chat_id, len(pending))
        return {'mention_replied': len(pending), 'chat_id': chat_id}

    @api.model
    def _create_todo(self, msg, chat, rec, text, owner):
        frm = (msg or {}).get('from') or {}
        sender_name = ' '.join(
            x for x in [frm.get('first_name'), frm.get('last_name')] if x) or frm.get('username') or ''
        todo = self.sudo().create({
            'chat_id': str(chat.get('id')),
            'chat_title': (rec.title if rec else None) or chat.get('title') or '',
            'message_id': str(msg.get('message_id') or ''),
            'message_text': (text or '')[:1000],
            'mentioner_user_id': str(frm.get('id') or ''),
            'mentioner_name': sender_name,
            'owner_user_id': owner,
        })
        _logger.info('edu_tg_assist: 群 %s 有人 @校长，建待办 #%d', todo.chat_id, todo.id)
        return {'mention_created': todo.id}

    # --------------------------------------------------- 3) cron 扫描 -> 私聊
    @api.model
    def _cron_scan_timeouts(self):
        """cron 入口（data/ir_cron_data.xml 里写的就是这个名字）。返回提醒条数。"""
        owner = self._owner_user_id()
        if not owner:
            _logger.info('edu_tg_assist: 未配置 %s，跳过 @提醒超时扫描', OWNER_PARAM)
            return 0

        # 私聊 chat_id 从人员登记表拿：Telegram 不允许机器人主动私聊从没说过话的人，
        # 所以**没有登记就没有私聊通道**，此时不发（也不标 dm_sent_at，等登记后自然重试）。
        # active_test=False：走 /stop 把登记归档的人也要能被找到 —— 否则会落到
        # 「还没和机器人说过话」这句不准的日志上，实际问题被掩盖。
        person = self.env['edu.tg.assist.person'].sudo().with_context(
            active_test=False).search([('tg_user_id', '=', owner)], limit=1)
        if not person:
            _logger.info('edu_tg_assist: 校长（%s）还没和机器人说过话，无法私聊提醒', owner)
            return 0
        if not person.active:
            # D3：本人发过 /stop ⇒ 不再一对一私发（包括 @提醒超时提醒）。
            # 与 person.upsert_from_user / find_by_name 同口径：停用即出口全关。
            _logger.info('edu_tg_assist: 校长（%s）已发 /stop 停止一对一私发，跳过提醒', owner)
            return 0
        dm_chat_id = person.chat_id or owner

        minutes = self._timeout_minutes()
        deadline = fields.Datetime.now() - timedelta(minutes=minutes)
        todos = self.sudo().search([
            ('replied_at', '=', False),
            ('dm_sent_at', '=', False),
            ('mentioned_at', '<=', deadline),
        ])
        sent = 0
        for todo in todos:
            ok, err = self.env['edu.tg.assist.api'].sudo().send_message(
                dm_chat_id, self._dm_text(todo, minutes), kind='mention_dm')
            if ok:
                # 只发一次：成功才落 dm_sent_at；失败了下次扫描重试（避免静默丢失）
                todo.sudo().write({'dm_sent_at': fields.Datetime.now()})
                sent += 1
            else:
                _logger.warning('edu_tg_assist: 私聊提醒待办 #%d 失败：%s', todo.id, err)
        if sent:
            _logger.info('edu_tg_assist: @提醒超时扫描发出 %d 条私聊', sent)
        return sent

    @api.model
    def _dm_text(self, todo, minutes):
        """私聊提醒正文（纯文本；不带键盘，按钮是 F4 那套、由提醒方自己附）。"""
        excerpt = (todo.message_text or '').strip().replace(chr(10), ' ')
        if len(excerpt) > MAX_EXCERPT:
            excerpt = excerpt[:MAX_EXCERPT] + '…'
        lines = [
            '【@提醒】群里有人 @ 你，已经 %d 分钟没见你回复。' % minutes,
            '',
            '群：%s' % (todo.chat_title or todo.chat_id),
            '发起人：%s' % (todo.mentioner_name or '—'),
        ]
        if excerpt:
            lines.append('内容：%s' % excerpt)
        lines.append('')
        lines.append('回群里说一句就算回复（我这边会自动销掉这条待办）。')
        return chr(10).join(lines)
