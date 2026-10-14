# -*- coding: utf-8 -*-
"""站内通知桥（对接选项 b）：edu.message → Telegram。

教务网站本来就会发站内信：有人报名、请假批了、报销到账、课前提醒……
全部经 edu_portal 的通知引擎 `edu.message._notify_event()` 入库（B5）。本模块
**只读**那张表（运行时按模型名探在不在，**不写进 depends**），把新站内信按后台
配好的规则转到 Telegram 私聊或群里。

为什么是「轮询」而不是「在 edu.message 上挂钩子」：
· 挂钩子要在 edu.message 上 _inherit —— 那就必须 depends edu_portal，
  本模块的设计前提（§1：与门户零依赖、可单独装卸）当场作废；
· 轮询只看「id 比我上次处理到的更大、事件名匹配」的新记录，天然幂等，
  不碰对方任何代码，也不改对方任何行为。

硬边界（B1–B8 不变，本文件另加 B9/B10）：
· B9：绝不读 edu.feedback.* / edu_telegram.* / edu.tg.claim / edu.invite.* ——
  那几张表里有学生明文 chat_id 与匿名承诺所依赖的指纹，任何并排导出都会作废承诺。
  本文件把这几张表写进 DENY_MODELS，`_cron_bridge()` 每轮开头 fail-closed 检查一次：
  命中就一条都不发（宁可桥整个不动，也不许有任何一行读进那些表）。
· B10：只发文字，绝不把消息里的 chat_id / token 之类字段拼进文案。
"""
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# 只认这一张源表。改成别的表 = 改本模块的定位，必须同时改文档与单测。
SOURCE_MODEL = 'edu.message'

# 一次 cron 每张规则最多处理多少条（防止一个假期回来一次补发几百条）。
BATCH = 50

# 单条转出去的正文上限（Telegram 单条 4096；留出前缀与换行的余量）。
BODY_MAX = 1500

# B9：这些模型**永远**不许当源表（前缀匹配）。
DENY_MODELS = (
    'edu.feedback',      # 学生匿名意见箱
    'edu.telegram',      # 诺亚（教学 telegram）全套
    'edu.tg.claim',      # 学生领码表：明文 chat_id
    'edu.tg.bot',        # 领码 bot 出网口
    'edu.invite',        # 邀请码池
)

TARGETS = [
    ('recipient', '站内信的收件人本人（要先把他的网站账号接到人员映射）'),
    ('person', '指定的一个人'),
    ('group', '指定的一个群'),
    ('owner', '机器人管理员（系统参数 owner_user_id）'),
]

OWNER_PARAM = 'edu_tg_assist.owner_user_id'

# ---- 对接选项 a（2026-10-14）：网站公告 edu.notice → Telegram 群 ----
# 公告不能像站内信那样用「id 水位」轮询：edu.notice 的 active=False 是「未发布」的载体，
# 公告到点才翻成 active=True，先建草稿、几天后再发布的公告 id 会落在水位之下而永远漏发。
# 所以这条路是 edu_portal 发布那一刻**主动调用** push_site_notice()，而不是轮询。
# 与 b 相同：portal 只按模型名探在不在，两边没有 depends 关系。
NOTICE_KIND = 'notice'

# 单条公告正文上限（Telegram 单条 4096；与门户的 1500 字内容上限 + 标题留余量）。
NOTICE_MAX = 3500


class EduTgAssistBridge(models.Model):
    _name = 'edu.tg.assist.bridge'
    _description = '站内通知桥（edu.message → Telegram）'
    _order = 'name, id'

    name = fields.Char('规则名', required=True,
                       help='只给自己看，例如「请假结果 → 教务群」。')
    active = fields.Boolean('启用', default=True)
    event_key = fields.Char(
        '事件名（留空 = 全部事件）',
        help='站内信的事件类目。留空表示「不管什么事件都转」。'
             '已见过的：approval_escalate（审批超时）、leave_result（请假结果）、'
             'reimburse_result（报销结果）、course_rep_notice、attendance_rep_submitted；'
             '课前提醒等没有事件名（空字符串）。')
    target = fields.Selection(TARGETS, string='发给谁', default='owner', required=True)
    person_id = fields.Many2one('edu.tg.assist.person', '指定的人')
    chat_id = fields.Many2one('edu.tg.assist.chat', '指定的群')
    prefix = fields.Char('正文前缀', help='例如「【教务】」。留空则只发站内信原文。')
    include_body = fields.Boolean('附上站内信原文', default=True)
    last_message_id = fields.Integer('已处理到的站内信 id', default=0, readonly=True, copy=False,
                                     help='水位线：只处理 id 比它大的站内信。')
    sent_count = fields.Integer('已转发', default=0, readonly=True, copy=False)
    skip_count = fields.Integer('已跳过', default=0, readonly=True, copy=False)

    _name_uniq = models.Constraint('unique(name)', '规则名不能重复。')

    # ---------- 源表探活（不依赖 edu_portal） ----------

    @api.model
    def _source_ready(self):
        """源表在不在：模型名在 env 里，且表真的能查（部署窗口里模型在、列没建）。"""
        if SOURCE_MODEL not in self.env:
            return False
        try:
            self.env[SOURCE_MODEL].sudo().search_count([('id', '=', 0)])
            return True
        except Exception:  # noqa: BLE001
            return False

    @api.model
    def _source_max_id(self):
        if not self._source_ready():
            return 0
        rec = self.env[SOURCE_MODEL].sudo().search([], order='id desc', limit=1)
        return rec.id or 0

    @api.model_create_multi
    def create(self, vals_list):
        """新规则从「现在」开始看，不回放历史 —— 否则一建规则就把陈年站内信全转出去。"""
        for vals in vals_list:
            if not vals.get('last_message_id'):
                vals['last_message_id'] = self._source_max_id()
        return super().create(vals_list)

    def write(self, vals):
        # 重新启用一条停用过的规则：水位留在原处会补发停用期间的所有站内信，
        # 这是管理员大概率不想要的，故启用时把水位推到当前最大。
        res = super().write(vals)
        if vals.get('active'):
            for rec in self:
                rec.last_message_id = self._source_max_id()
        return res

    # ---------- 目标与文案 ----------

    def _target_chat(self, message=None):
        """算出这条站内信该发到哪个 Telegram 会话。

        返回 (chat_id, error)：chat_id 为空时 error 说明原因（会写进桥接记录）。
        **不猜人**：查不到对应登记就跳过，绝不给一个「名字差不多」的人发。
        """
        self.ensure_one()
        if self.target == 'person':
            if not self.person_id or not self.person_id.chat_id:
                return '', '规则选的这个人还没登记私聊地址'
            return self.person_id.chat_id, ''
        if self.target == 'group':
            if not self.chat_id or not self.chat_id.chat_id:
                return '', '规则选的这个群还没登记 chat_id'
            return self.chat_id.chat_id, ''
        if self.target == 'owner':
            owner_tg = (self.env['ir.config_parameter'].sudo()
                        .get_param(OWNER_PARAM) or '').strip()
            if not owner_tg:
                return '', '没配 edu_tg_assist.owner_user_id（机器人管理员）'
            owner = self.env['edu.tg.assist.person'].sudo().search(
                [('tg_user_id', '=', owner_tg), ('active', '=', True)], limit=1)
            if not owner or not owner.chat_id:
                return '', '机器人的管理员还没登记私聊地址'
            return owner.chat_id, ''
        # recipient：站内信的收件人 → 他的网站账号 → 人员映射里挂了同一个账号的人
        if not message or not message.recipient_id:
            return '', '这条站内信没有收件人'
        person = self.env['edu.tg.assist.person'].sudo().search(
            [('user_id', '=', message.recipient_id.id), ('active', '=', True)], limit=1)
        if not person or not person.chat_id:
            return '', '收件人（%s）还没把网站账号接到人员映射上' % (message.recipient_id.name or '—')
        return person.chat_id, ''

    def _render(self, message):
        """站内信正文 + 前缀。只发文字，不做任何字段拼接（B10）。"""
        self.ensure_one()
        head = (self.prefix or '').strip()
        body = (message.body or '').strip() if self.include_body else ''
        text = head + (chr(10) if head and body else '') + body
        return text[:BODY_MAX] or '（站内信没有正文）'

    # ---------- 扫描 ----------

    @api.model
    def _cron_bridge(self):
        """cron 入口：每条启用的规则各推进各的水位。**永不因为一条规则出错而停摆**。"""
        if not self._source_ready():
            return 0
        # B9 闸门：源表一旦被改成禁读清单里的表，宁可一条都不发（fail-closed）。
        if self._check_source_allowed(SOURCE_MODEL):
            _logger.error('edu_tg_assist: 站内通知桥源表 %s 命中禁读清单，已停发', SOURCE_MODEL)
            return 0
        total = 0
        for rule in self.sudo().search([('active', '=', True)]):
            try:
                total += rule._run_once()
            except Exception as exc:  # noqa: BLE001
                _logger.warning('edu_tg_assist: 站内通知桥规则 #%s 失败：%s',
                                rule.id, type(exc).__name__)
        return total

    def _run_once(self):
        """处理一批新站内信。返回成功转发条数。"""
        self.ensure_one()
        msg_model = self.env[SOURCE_MODEL].sudo()
        domain = [('id', '>', self.last_message_id or 0)]
        key = (self.event_key or '').strip()
        if key:
            domain.append(('event_key', '=', key))
        msgs = msg_model.search(domain, limit=BATCH, order='id')
        if not msgs:
            return 0
        sent = skipped = 0
        for msg in msgs:
            # 幂等兜底：水位没来得及写就崩了时，靠记录表认出「这条已经发过」
            if self.env['edu.tg.assist.bridge_log'].sudo().search_count(
                    [('rule_id', '=', self.id), ('message_id', '=', msg.id)]):
                continue
            chat_id, err = self._target_chat(msg)
            if not chat_id:
                skipped += 1
                self._log(msg, False, err)
                continue
            ok, error = self.env['edu.tg.assist.api'].sudo().send_message(
                chat_id, self._render(msg), kind='bridge')
            if ok:
                sent += 1
            else:
                skipped += 1
            self._log(msg, ok, error or '', chat_id)
        self.write({
            'last_message_id': max(msgs.ids),
            'sent_count': self.sent_count + sent,
            'skip_count': self.skip_count + skipped,
        })
        return sent

    def _log(self, message, ok, error, chat_id=''):
        """桥接记录。**永不抛异常**：记录写不进去不能反过来把转发搞挂。"""
        try:
            self.env['edu.tg.assist.bridge_log'].sudo().create({
                'rule_id': self.id,
                'message_id': message.id,
                'event_key': message.event_key or '',
                'target_chat_id': chat_id or '',
                'ok': ok,
                'error': (error or '')[:200],
                'sent_at': fields.Datetime.now(),
                'excerpt': (message.body or '')[:120],
            })
        except Exception:  # noqa: BLE001
            pass  # 撞唯一约束（同一条站内信重复处理）属正常

    # ---------- 后台按钮 ----------

    def action_adopt_watermark(self):
        """把水位推到当前最大：只对「从现在开始」的站内信生效。"""
        for rec in self:
            rec.last_message_id = self._source_max_id()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': '站内通知桥', 'type': 'success', 'sticky': False,
                       'message': '已跳过现有站内信，之后新来的才会转发。'},
        }

    def action_test_send(self):
        """发一条测试消息到这条规则的目标（不动水位、不写桥接记录）。"""
        self.ensure_one()
        chat_id, err = self._target_chat(None)
        if not chat_id:
            raise UserError('这条规则现在发不出去：%s' % (err or '目标不可用'))
        ok, error = self.env['edu.tg.assist.api'].sudo().send_message(
            chat_id, (self.prefix or '').strip() + (chr(10) if self.prefix else '') +
            '这是一条测试消息：站内通知桥规则「%s」已经配好。' % self.name,
            kind='bridge')
        if not ok:
            raise UserError('测试消息没发出去：%s' % (error or '未知原因'))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': '站内通知桥', 'type': 'success', 'sticky': False,
                       'message': '测试消息已发出，去 Telegram 看一眼。'},
        }

    @api.model
    def _check_source_allowed(self, model_name):
        """B9 守卫：源表名命中禁止前缀就直接拒绝（供规则校验与自检调用）。"""
        name = (model_name or '').strip()
        for bad in DENY_MODELS:
            if name == bad or name.startswith(bad + '.'):
                return bad
        return ''

    @api.model
    def notice_targets(self):
        """勾了「接收网站公告」的启用群（网站公告只发给这些群）。"""
        return self.env['edu.tg.assist.chat'].sudo().search([
            ('active', '=', True),
            ('notice_enabled', '=', True),
            ('chat_id', '!=', False)])

    @api.model
    def push_site_notice(self, notice):
        """把一条 edu.notice 推到所有「接收网站公告」的群，返回 (sent, failed)。

        由 edu_portal 发布公告时调用（它只按模型名探本模型在不在，没有 depends 关系）。
        单个群失败不影响其它群；本方法不抛异常（门户的发布流程不能被出网拖垮）。
        """
        name = (getattr(notice, 'name', '') or '').strip() or '公告'
        content = (getattr(notice, 'content', '') or '').strip()
        text = ('【公告】%s\n%s' % (name, content))[:NOTICE_MAX]
        api = self.env['edu.tg.assist.api'].sudo()
        sent = failed = 0
        for chat in self.notice_targets():
            try:
                ok, error = api.send_message(chat.chat_id, text, kind=NOTICE_KIND)
            except Exception:
                _logger.warning('notice push exception chat=%s', chat.id,
                                exc_info=True)
                failed += 1
                continue
            if ok:
                sent += 1
            else:
                failed += 1
                _logger.warning('notice push failed chat=%s error=%s',
                                chat.id, error)
        _logger.info('notice push id=%s sent=%s failed=%s',
                     getattr(notice, 'id', 0), sent, failed)
        return sent, failed


class EduTgAssistBridgeLog(models.Model):
    _name = 'edu.tg.assist.bridge_log'
    _description = '站内通知桥接记录'
    _order = 'id desc'

    rule_id = fields.Many2one('edu.tg.assist.bridge', '规则', required=True,
                              ondelete='cascade', index=True)
    message_id = fields.Integer('站内信 id', required=True, index=True)
    event_key = fields.Char('事件名')
    target_chat_id = fields.Char('发往 chat_id')
    ok = fields.Boolean('成功')
    error = fields.Char('原因')
    excerpt = fields.Char('正文摘要')
    sent_at = fields.Datetime('时间', default=fields.Datetime.now)

    _rule_message_uniq = models.Constraint(
        'unique(rule_id, message_id)', '同一条站内信对同一条规则只会转发一次。')
