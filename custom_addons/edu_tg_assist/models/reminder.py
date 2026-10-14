# -*- coding: utf-8 -*-
"""定时提醒规则（F1）—— 管理员在后台配「周几、几点、发到哪个群、发什么」。

校长要的两条：周一早上往「我爱学习群」发测试链接；周末往「清洁能源站群」发大扫除提醒 + 卫生检测表链接。

★ 触发方式（为什么不写「每 5 分钟扫一次」的 cron）
  · **每条规则自带一个 ir.cron**：interval_number=1 + interval_type='weeks'，
    nextcall = 下一个「周几 几点」的时刻。发送时机由 **cron 自己**控制；
  · 于是到点只发一次；服务器当时宕机，Odoo 会在下次调度时**补跑**逾期任务
    （ir_cron 取 nextcall <= now 的任务，这是它原生行为）；
  · 代码里**没有**「datetime.now().weekday() == 0」这类「今天该不该发」的判断 ——
    那种写法在扫描型 cron 里一旦去重没做严，就会变成「每 5 分钟发一次」，本项目吃过大亏。
  ⚠ 实测（2026-10-08，本地 edu19）：Odoo 19 的 ir.cron **没有 cron 表达式字段**，
    interval_type 只有 minutes/hours/days/weeks/months ⇒「周几几点」只能用
    weeks + nextcall 表达（这也正是 Odoo 原生定时动作的做法）。
  ⚠ 时区：「周几 几点」按规则自己的 tz 解释（默认取建规则的人的个人时区，兜底 Asia/Shanghai）。
    服务器按 UTC 存时间 —— 不换算的话，管理员配 08:00 会在北京时间 16:00 发出去。
"""
import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.edu_tg_assist import polls

from .template import MAX_TEXT, WEEKDAYS_CN

_logger = logging.getLogger(__name__)

# 改了这些字段就要重算 cron（nextcall 跟着「周几几点」走）
SCHEDULE_FIELDS = {'name', 'active', 'weekday', 'send_hour', 'send_minute', 'tz'}


# ----------------------------------------------------------------------
# 纯函数区：调度数学与时区换算（不碰 ORM ⇒ 可以脱离数据库单测，见回报里的自证读数）
# ----------------------------------------------------------------------
def safe_tz(name, log_id=None):
    """时区对象。名字不认识时退回 Asia/Shanghai（并记日志，不静默用错时区）。"""
    name = (name or '').strip() or 'Asia/Shanghai'
    try:
        return pytz.timezone(name)
    except Exception:  # noqa: BLE001
        _logger.warning('edu_tg_assist: 时区「%s」不认识（规则 %s），按 Asia/Shanghai 处理',
                        name, log_id)
        return pytz.timezone('Asia/Shanghai')


def localize_wall(tz, naive):
    """把「墙上时间」落到时区上。夏令时跳变/重叠时退回标准时解释（宁可晚一小时，也不炸）。"""
    try:
        return tz.localize(naive)
    except Exception:  # noqa: BLE001 —— AmbiguousTimeError / NonExistentTimeError
        try:
            return tz.localize(naive, is_dst=False)
        except Exception:  # noqa: BLE001
            return naive.replace(tzinfo=pytz.utc)


def next_call_utc(weekday, hour, minute, tz_name, now_utc=None):
    """下一个「周几 几点」的 **UTC naive** 时刻（直接喂 ir.cron.nextcall）。

    weekday: '0'..'6'（周一..周日）或 'daily'；「几点」按 tz_name 解释。
    :param now_utc: 参考时刻（UTC naive）；默认取当前时间 —— 显式传入是为了可单测。
    """
    tz = safe_tz(tz_name)
    now_local = pytz.utc.localize(now_utc or fields.Datetime.now()).astimezone(tz)
    hh = min(max(int(hour or 0), 0), 23)
    mm = min(max(int(minute or 0), 0), 59)
    target_wd = None if weekday == 'daily' else int(weekday or 0)
    for offset in range(0, 15):
        day = (now_local + timedelta(days=offset)).date()
        if target_wd is not None and day.weekday() != target_wd:
            continue
        cand = localize_wall(tz, datetime.combine(day, time(hour=hh, minute=mm)))
        if cand > now_local:
            return cand.astimezone(pytz.utc).replace(tzinfo=None)
    return None   # 15 天内必有命中，正常到不了这里


class EduTgAssistReminder(models.Model):
    _name = 'edu.tg.assist.reminder'
    _description = 'Telegram 定时提醒规则'
    _order = 'weekday, send_hour, send_minute, id'

    name = fields.Char('规则名', required=True, help='例如「周一学习日提醒」。')
    active = fields.Boolean('启用', default=True,
                            help='停用后它的定时动作也会一起停（不会空转）。')
    target_chat_id = fields.Many2one('edu.tg.assist.chat', string='发到哪个群',
                                     required=True, ondelete='restrict',
                                     help='只能选机器人已经见过的群：把机器人拉进群、在群里随便说一句就登记上了。')
    template_id = fields.Many2one('edu.tg.assist.template', string='发什么（模板）',
                                  required=True, ondelete='restrict')
    person_id = fields.Many2one('edu.tg.assist.person', string='模板 {name} 取谁',
                                ondelete='set null',
                                help='可选。模板里写了 {name} 才需要选；不选则 {name} 原样发出（并在日志里点名）。')
    with_buttons = fields.Boolean('带打卡按钮', default=False,
                                  help='勾上后本条消息带【已完成并达标 / 有异常需上报】按钮，'
                                       '谁点了什么进「打卡统计」。默认关闭：不带按钮的规则发出的'
                                       'payload 与从前逐字节相同。')
    poll_options = fields.Char('按钮选项', default=polls.DEFAULT_OPTIONS,
                               help='竖线分隔的 ASCII 短值，默认 done|abnormal。')
    poll_expected_role = fields.Selection(polls.ROLE_SELECTION, string='应回的人',
                                          default='dorm_head',
                                          help='「打卡统计」按它算应回/未回名单（只含主动登记过的人）。')
    weekday = fields.Selection([
        ('0', '周一'), ('1', '周二'), ('2', '周三'), ('3', '周四'),
        ('4', '周五'), ('5', '周六'), ('6', '周日'), ('daily', '每天'),
    ], string='星期', default='0', required=True)
    send_hour = fields.Integer('几点（0-23）', default=8, required=True)
    send_minute = fields.Integer('几分（0-59）', default=0, required=True)
    tz = fields.Char('时区', default=lambda self: self.env.user.tz or 'Asia/Shanghai',
                     required=True,
                     help='「周几几点」按这个时区解释。服务器按 UTC 存时间，换算错了会差几个小时。')
    schedule_label = fields.Char('计划', compute='_compute_schedule_label',
                                 help='把「星期 + 几点几分 + 时区」拼成人话，列表里一眼看全。')
    cron_id = fields.Many2one('ir.cron', string='定时动作', readonly=True, copy=False,
                              ondelete='set null',
                              help='保存规则时自动建/更新。要停就停上面的「启用」，不用来这里改。')
    last_sent_at = fields.Datetime('最近一次尝试', readonly=True, copy=False,
                                   help='成功与失败都记（看「最近一次结果」）。')
    last_result = fields.Char('最近一次结果', readonly=True, copy=False)
    last_error = fields.Char('最近一次失败原因', readonly=True, copy=False)
    note = fields.Char('备注')

    _hour_range = models.Constraint(
        'CHECK(send_hour >= 0 AND send_hour <= 23)', '「几点」必须填 0 到 23。')
    _minute_range = models.Constraint(
        'CHECK(send_minute >= 0 AND send_minute <= 59)', '「几分」必须填 0 到 59。')

    # ------------------------------------------------------------------
    # 调度：规则 <-> ir.cron
    # ------------------------------------------------------------------
    def _tzinfo(self):
        """规则的时区对象（名字不认识会退回 Asia/Shanghai 并记日志）。"""
        return safe_tz(self.tz, log_id=self.id)

    def _next_call(self, after=None):
        """下一个触发时刻（UTC naive，喂给 ir.cron.nextcall）。"""
        self.ensure_one()
        return next_call_utc(self.weekday, self.send_hour, self.send_minute, self.tz, after)

    def _cron_vals(self, with_nextcall=True):
        self.ensure_one()
        vals = {
            'name': 'edu_tg_assist: 定时提醒 · %s' % (self.name or self.id),
            'model_id': self.env['ir.model']._get_id(self._name),
            'state': 'code',
            'code': 'model._cron_send(%d)' % self.id,
            'interval_number': 1,
            'interval_type': 'weeks',
            'active': bool(self.active),
            'user_id': self.env.ref('base.user_root').id,
        }
        if with_nextcall:
            nxt = self._next_call()
            if nxt:
                vals['nextcall'] = nxt
        return vals

    def _sync_cron(self, recompute_nextcall=False):
        """把规则与它的 ir.cron 对齐（缺则建、漂移则改）。返回 True = 动过。

        recompute_nextcall=False 时**不主动推迟**已有的 nextcall —— 否则自愈扫描会把
        「到点但还没跑」的任务一次次往后推，变成永远不发。
        """
        self.ensure_one()
        Cron = self.env['ir.cron'].sudo()
        if not self.active:
            if self.cron_id and self.cron_id.active:
                self.cron_id.sudo().write({'active': False})
                return True
            return False
        if self.cron_id:
            cron = self.cron_id.sudo()
            drift = (cron.name != 'edu_tg_assist: 定时提醒 · %s' % (self.name or self.id)
                     or cron.code != 'model._cron_send(%d)' % self.id
                     or cron.model_id.id != self.env['ir.model']._get_id(self._name)
                     or cron.interval_number != 1 or cron.interval_type != 'weeks'
                     or cron.active != bool(self.active))
            if not (drift or recompute_nextcall):
                return False
            cron.write(self._cron_vals(with_nextcall=recompute_nextcall or not cron.nextcall))
            return True
        cron = Cron.create(self._cron_vals(with_nextcall=True))
        self.sudo().write({'cron_id': cron.id})
        return True    # ------------------------------------------------------------------
    # 建/改/删 时同步定时动作
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        for rule in rules:
            try:
                rule._sync_cron(recompute_nextcall=True)
            except Exception:  # noqa: BLE001 —— 建规则不能因为定时动作建不出来而失败
                _logger.exception('edu_tg_assist: 规则 %s 建定时动作失败（可稍后跑自愈 cron 补）', rule.id)
        return rules

    def write(self, vals):
        res = super().write(vals)
        if SCHEDULE_FIELDS & set(vals):
            for rule in self:
                try:
                    rule._sync_cron(recompute_nextcall=True)
                except Exception:  # noqa: BLE001
                    _logger.exception('edu_tg_assist: 规则 %s 同步定时动作失败', rule.id)
        return res

    def unlink(self):
        crons = self.mapped('cron_id')
        res = super().unlink()
        if crons:
            crons.sudo().unlink()   # 规则没了，别留一个还在跑的定时动作
        return res

    @api.depends('weekday', 'send_hour', 'send_minute', 'tz')
    def _compute_schedule_label(self):
        week = dict(self._fields['weekday'].selection)
        for rule in self:
            rule.schedule_label = '%s %02d:%02d（%s）' % (
                week.get(rule.weekday, rule.weekday or ''),
                min(max(int(rule.send_hour or 0), 0), 23),
                min(max(int(rule.send_minute or 0), 0), 59),
                (rule.tz or 'Asia/Shanghai'))

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------
    def _placeholder_values(self):
        """给模板的占位符值。日期按**规则自己的时区**算，跟谁跑 cron 无关。"""
        self.ensure_one()
        tz = self._tzinfo()
        today = pytz.utc.localize(fields.Datetime.now()).astimezone(tz).date()
        return {
            'name': (self.person_id.name or None),
            'date': fields.Date.to_string(today),
            'weekday': WEEKDAYS_CN[today.weekday()],
            'group': (self.target_chat_id.alias or self.target_chat_id.title or None),
        }

    def _mention_target(self):
        """要 @ 的人（规则上的 person_id）。没选人 ⇒ None ⇒ 走纯文本，payload 逐字节不变。

        模板里写「@学委」+ 这里选上「学委」⇒ 变成 Telegram 真提及（tg://user?id=…，HTML 模式）。
        见 template.render 的 mention 参数与 mention_html 的 id 校验。
        """
        self.ensure_one()
        if not self.person_id:
            return None
        return {'name': self.person_id.name, 'user_id': self.person_id.tg_user_id}

    def _do_send(self, kind='reminder'):
        """真正发一条。返回 (ok, error)。**不吞失败**：结果写进规则字段 + send_log + 日志。"""
        self.ensure_one()
        if not self.active:
            return False, '规则已停用'
        if not self.target_chat_id or not self.target_chat_id.chat_id:
            return False, '没有目标群（或该群还没被机器人登记过）'
        if not self.template_id:
            return False, '没有选模板'
        res = self.template_id.render(self._placeholder_values(), mention=self._mention_target())
        # 打卡按钮（F4 接通 F1）：with_buttons 关着 ⇒ 不建 poll 行、markup=None，
        # 发出的 payload 与从前**逐字节相同**。
        poll = self._create_poll(res['text']) if self.with_buttons else None
        markup = poll.build_keyboard() if poll else None
        if poll and markup is None:
            _logger.error('edu_tg_assist: 打卡按钮生成失败（选项为空或过长），本条按纯文本发出')
        ok, err, result = self.env['edu.tg.assist.api'].sudo().send_message_full(
            self.target_chat_id.chat_id, res['text'], reply_markup=markup, kind=kind,
            parse_mode=res.get('parse_mode'))
        if poll:
            poll._mark_sent(ok, result, err, with_buttons=markup is not None)
        self.sudo().write({
            'last_sent_at': fields.Datetime.now(),
            'last_result': '成功' if ok else '失败',
            'last_error': ('' if ok else str(err))[:200],
        })
        if ok:
            _logger.info('edu_tg_assist: 提醒「%s」已发往 %s（%s）', self.name,
                         self.target_chat_id.alias or self.target_chat_id.title
                         or self.target_chat_id.chat_id, kind)
        else:
            _logger.warning('edu_tg_assist: 提醒「%s」发送失败：%s', self.name, err)
        return ok, err

    def _create_poll(self, text):
        """为这条规则建一条打卡记录（body 是**发出时的快照**，模板改了不影响历史统计）。"""
        self.ensure_one()
        return self.env['edu.tg.assist.poll'].sudo().create({
            'chat_id': self.target_chat_id.id,
            'reminder_id': self.id,
            'template_id': self.template_id.id,
            'body': text,
            'options': self.poll_options or polls.DEFAULT_OPTIONS,
            'expected_role': self.poll_expected_role or 'dorm_head',
            'state': 'draft',
        })

    # ------------------------------------------------------------------
    # ir.cron 入口（两个：发送 / 自愈）
    # ------------------------------------------------------------------
    @api.model
    def _send_rule(self, rule_id, kind='reminder'):
        """按 id 发一条规则。**任何异常都只记日志并回报** —— cron 抛异常会连败（本项目有过教训）。"""
        try:
            rule = self.sudo().browse(int(rule_id or 0))
        except (TypeError, ValueError):
            _logger.warning('edu_tg_assist: 提醒规则 id 非法：%r', rule_id)
            return False, 'id 非法'
        if not rule.exists():
            _logger.warning('edu_tg_assist: 提醒规则 %s 不存在，跳过', rule_id)
            return False, '规则不存在'
        try:
            return rule._do_send(kind=kind)
        except Exception as exc:  # noqa: BLE001
            _logger.exception('edu_tg_assist: 提醒规则 %s 发送异常', rule.id)
            try:
                rule.sudo().write({'last_result': '异常',
                                   'last_error': '%s: %s' % (type(exc).__name__, str(exc)[:180])})
            except Exception:  # noqa: BLE001 —— 连失败都记不进去也不能把 cron 打死
                _logger.exception('edu_tg_assist: 规则 %s 连失败原因都没写进去', rule.id)
            return False, str(exc)[:200]

    @api.model
    def _cron_send(self, rule_id):
        """ir.cron 入口（每条规则一条 cron，code = model._cron_send(<id>)）。"""
        ok, err = self._send_rule(rule_id, kind='reminder')
        return 'edu_tg_assist 提醒 #%s：%s' % (rule_id, '成功' if ok else '失败（%s）' % err)

    @api.model
    def _cron_resync_rules(self):
        """ir.cron 入口（data/ir_cron_reminder.xml 里那条，**默认停用**）：规则自愈。

        修「规则在、定时动作丢了 / 被停了 / 代码对不上」这类漂移（数据库还原、有人手工删过）。
        **不发任何消息**，所以开着也不会打扰人；也**不抛异常**。
        """
        rules = self.sudo().search([])
        fixed = 0
        for rule in rules:
            try:
                if rule._sync_cron(recompute_nextcall=False):
                    fixed += 1
            except Exception:  # noqa: BLE001
                _logger.exception('edu_tg_assist: 规则 %s 自愈失败', rule.id)
        return 'edu_tg_assist 提醒规则自愈：检查 %d 条，修复 %d 条' % (len(rules), fixed)

    # ------------------------------------------------------------------
    # 后台按钮
    # ------------------------------------------------------------------
    def action_send_now(self):
        """「立即发送一次」：配好规则当场验一条，不必等 cron。

        ⚠ 这是**新增**的测试入口（队长未要求）；不想要就删掉本方法与视图里那个按钮，无副作用。
        """
        self.ensure_one()
        ok, err = self._do_send(kind='manual')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '已发送' if ok else '发送失败',
                'message': ('规则「%s」已发出，看「最近一次结果」核对。' % self.name) if ok
                           else ('失败原因：%s' % (err or '未知')),
                'type': 'success' if ok else 'danger',
                'sticky': False,
            },
        }

    # ------------------------------------------------------------------
    # 面板/按钮的「定时群发」快速入口（2026-10-14，用户问「定时群发在哪」）
    #   管理员只需要回答三件事：发到哪个群、每周几几点、发什么（一句话正文）。
    #   模板是 template_id 的必填项 ⇒ 这里顺手建一个；同一段正文复用已有模板，
    #   撞名由 _unique_template_name 让开（模板名有 UNIQUE 约束，绝不覆盖别人的）。
    # ------------------------------------------------------------------
    @api.model
    def _unique_template_name(self, base):
        """模板名唯一约束（UNIQUE(name)）：撞名加「 2」「 3」…，不改动任何已有模板。"""
        names = set(self.env['edu.tg.assist.template'].sudo().search([]).mapped('name'))
        base = (base or '定时群发').strip()[:60] or '定时群发'
        if base not in names:
            return base
        for i in range(2, 50):
            cand = '%s %d' % (base, i)
            if cand not in names:
                return cand
        return '%s %d' % (base, len(names) + 1)

    @api.model
    def quick_create(self, chat, body, weekday, hour, minute):
        """一句话正文 → 模板 + 规则（规则自带 ir.cron），返回新建的规则记录。

        :param chat: edu.tg.assist.chat 记录（必须已登记 chat_id）
        :param body: 正文，支持 {name}/{date}/{weekday}/{group} 占位符
        :param weekday: '0'..'6'（周一..周日）或 'daily'
        :param hour/minute: 0-23 / 0-59
        :raises UserError: 正文空 / 星期或时间非法 / 群没登记好 —— 面板原样显示这句话
        """
        body = (body or '').strip()
        if not body:
            raise UserError('正文是空的，没建成定时群发。')
        if len(body) > MAX_TEXT:
            raise UserError('正文太长了（超过 %d 字），请分成两条。' % MAX_TEXT)
        if weekday not in dict(self._fields['weekday'].selection):
            raise UserError('「星期」没选对。')
        try:
            hour, minute = int(hour), int(minute)
        except (TypeError, ValueError):
            raise UserError('「几点」「几分」没填对。')
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise UserError('时间是 0-23 点、0-59 分。')
        if not chat or not chat.active or not (chat.chat_id or '').strip():
            raise UserError('这个群还没登记好（没有 chat_id），发不了。')

        Template = self.env['edu.tg.assist.template'].sudo()
        tpl = Template.search([('body', '=', body)], limit=1)
        if not tpl:
            first = (body.splitlines()[0] if body else '')[:20] or '定时群发'
            tpl = Template.create({
                'name': self._unique_template_name('%s（定时）' % first),
                'scene': 'remind',
                'body': body,
                'active': True,
                'note': '面板「定时群发」自动创建',
            })
        return self.create({
            'name': '定时群发：%s' % (chat.alias or chat.title or chat.chat_id),
            'active': True,
            'target_chat_id': chat.id,
            'template_id': tpl.id,
            'weekday': weekday,
            'send_hour': hour,
            'send_minute': minute,
            'tz': 'Asia/Shanghai',
        })
