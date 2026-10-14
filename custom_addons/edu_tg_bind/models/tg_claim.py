# -*- coding: utf-8 -*-
"""Telegram 领码记录 edu.tg.claim —— 「一个 TG 账号只能领一张码」的唯一事实源。

⚠ 边界（别把本模型与生产那个同名模块混在一起）：
   生产上跑的 edu_telegram = 匿名意见收集机器人（edu.feedback.* / edu_telegram.outbox /
   edu_telegram.* 系统参数 / /telegram/webhook）。本模块 edu_tg_bind 与它没有关系：
   不读不写它的表与参数、不占它的路由、depends 里也没有它。
   本模块的 chat_id 是**明文**（否则做不到「一账号一张码」）——因此**永远不要**把它与
   意见箱的数据 join / 导出 / 并排展示（那会作废学校对学生的匿名承诺，且不可逆）。
   完整边界见 docs/plans/tg-invite-bot-design.md §1。

并发设计（依据 = 本机实测，见设计 §5）：
  · Odoo 19 的事务隔离级别是 REPEATABLE READ（odoo/sql_db.py:373 无条件设置；
    运行时实测 show transaction_isolation -> repeatable read）。
  · ⇒ **裸 SELECT ... FOR UPDATE SKIP LOCKED 不足以**防「两个学生拿到同一张码」：
    快照过期的事务看不见别人**已提交**的领取记录（本机复现：同一张码被选中两次，
    只被唯一约束挡住，设计 §5.3 实验 B）。
  · ⇒ 三层防线：SKIP LOCKED（挡**在途**）+ unique(chat_id) / unique(invite_code_id)
    （挡**已提交**，数据库级，不是 if 判断）+ 整事务 ROLLBACK 后重试（换快照才收敛，
    设计 §5.4 实测：savepoint 内重取会一直撞同一张）。
"""
import logging
import time

from psycopg2 import errors as pg_errors

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# ---- 码池判据（与设计文档 §4 一一对应；改这里必须同步改文档）----
POOL_PREFIX_PARAM = 'edu_tg_bind.pool_batch_prefix'
DEFAULT_POOL_PREFIX = 'TGB-STU-'
REGISTER_URL_PARAM = 'edu_tg_bind.register_url'
DEFAULT_REGISTER_URL = 'https://edu.example.org/register'
# 网站根地址（教程里的「去登录 / 使用指南」按钮要用）。刻意与注册地址分开两个参数：
# 注册地址可能被换成短链，而登录页与帮助中心永远在同一台站点上。
SITE_URL_PARAM = 'edu_tg_bind.site_url'
DEFAULT_SITE_URL = 'https://edu.example.org'
DRY_RUN_PARAM = 'edu_tg_bind.dry_run'

# 冲突重试上界（用尽 -> 回「系统繁忙」，**不 500**）
MAX_CLAIM_ATTEMPTS = 4
# 重试之间的退避（秒）。睡眠时**没有持有任何锁**（上一轮的锁随 ROLLBACK 一起释放），
# 目的只是让挤在同一条池子上的一批请求错开，避免活锁。
RETRY_BACKOFF = 0.05
NOTIFY_ERROR_MAX = 500
TEXT_FIELD_MAX = 128

# 领码流的文案 —— **只有这一份**：edu_tg_bind 自带 webhook 与 edu_tg_gate 前门共用
# handle_private_message()，两处不许各写一套（否则「空池」与「繁忙」的措辞会漂移）。
POOL_EMPTY_TEXT = '暂时没有可用的邀请码，请联系教务处。'
BUSY_TEXT = '系统繁忙，请稍后再发一条消息。'

# 码池判据（**只有这一份**：取码与计数共用它，避免两处 SQL 判据漂移）
# 与设计文档 §4 的表一一对应：前缀 / unused / used_count=0 / 未过期 / 层级码 / 学生层 / 未被领走
_POOL_WHERE = """
           c.batch_ref LIKE %(prefix)s ESCAPE '!'
       AND c.state = 'unused'
       AND coalesce(c.used_count, 0) = 0
       AND c.expire_at > %(now)s
       AND c.code_kind = 'tier'
       AND c.tier = 'student'
       AND NOT EXISTS (SELECT 1 FROM edu_tg_claim k
                        WHERE k.invite_code_id = c.id)
"""


class EduTgClaim(models.Model):
    _name = 'edu.tg.claim'
    _description = 'Telegram 邀请码领取记录'
    _order = 'claimed_on DESC, id DESC'

    chat_id = fields.Char(
        'Telegram 会话 ID', required=True, index=True, copy=False,
        help='私聊 chat.id。存**字符串**：Telegram 用户 id 可超过 32 位'
             '（Bot API 官方警告），Odoo fields.Integer 落库是 int4 会溢出。')
    telegram_name = fields.Char('Telegram 姓名', help='来自对方自填的 Telegram 名字，仅供教务认人，不是身份校验。')
    username = fields.Char('Telegram 用户名', help='@ 后面的那串；很多人没设置，允许为空。')
    invite_code_id = fields.Many2one(
        'edu.invite.code', string='邀请码', required=True,
        ondelete='restrict', index=True)
    invite_code = fields.Char('码', related='invite_code_id.code', store=False)
    claimed_on = fields.Datetime(
        '领取时间', required=True, index=True, default=fields.Datetime.now, copy=False)
    notify_state = fields.Selection(
        [('sent', '已回复'),
         ('failed', '回复失败'),
         ('skipped_dry_run', '试运行未发送')],
        string='回复状态', default='failed', copy=False,
        help='回复是否真的发到了 Telegram。失败不吞：学生再发一条消息会重发同一张码。')
    notify_error = fields.Text('回复失败原因', readonly=True, copy=False)
    notify_attempts = fields.Integer('回复尝试次数', default=0, readonly=True, copy=False)

    # 本模块的两条硬约束（数据库级；见文件头的并发设计）
    _claim_chat_uniq = models.Constraint(
        'unique (chat_id)', '一个 Telegram 账号只能领一张邀请码（本条会话已经领过了）。')
    _claim_code_uniq = models.Constraint(
        'unique (invite_code_id)', '这张邀请码已经发给别的 Telegram 账号了。')

    # ------------------------------------------------------------------
    # 系统参数
    # ------------------------------------------------------------------
    @api.model
    def _param(self, key, default=None):
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    @api.model
    def _pool_prefix(self):
        return (self._param(POOL_PREFIX_PARAM) or DEFAULT_POOL_PREFIX).strip()

    @api.model
    def _register_url(self):
        return (self._param(REGISTER_URL_PARAM) or DEFAULT_REGISTER_URL).strip()

    @api.model
    def _site_url(self):
        """网站根地址（去掉结尾斜杠），用于拼 /login 与 /help/student。"""
        return (self._param(SITE_URL_PARAM) or DEFAULT_SITE_URL).strip().rstrip('/')

    @api.model
    def is_dry_run(self):
        """试运行：不真的调 Bot API，把「本来会发出去的话」放进 HTTP 响应里（本地验证用）。"""
        return str(self._param(DRY_RUN_PARAM) or '').strip().lower() in ('1', 'true', 'yes', 'on')

    @staticmethod
    def _like_escape(value):
        """把 LIKE 元字符转成普通字符（配合 SQL 里的 ESCAPE '!'）。

        用 '!' 而不是反斜杠：反斜杠要在 shell / SQL / Python 三层里各转一次，
        极易被吃掉；'!' 只在一层里出现。
        """
        return value.replace('!', '!!').replace('%', '!%').replace('_', '!_')

    # ------------------------------------------------------------------
    # 码池
    # ------------------------------------------------------------------
    @api.model
    def _pool_params(self):
        prefix = self._pool_prefix()
        return {'prefix': self._like_escape(prefix) + '%',
                'now': fields.Datetime.now()} if prefix else None

    @api.model
    def _pick_locked_code_id(self):
        """从码池里锁一张可用码，返回它的 id（行锁保持到本事务结束）。

        返回 None 有两种**不同**的含义，调用方必须用 _pool_has_candidates() 区分：
          (a) 池真的空了；
          (b) 池里有码，但这一瞬间全被别的请求锁着（在途）。
        实测踩坑（V7/V8）：把 (b) 当成 (a)，学生会收到「暂时没有可用的邀请码，请联系教务处」——
        而实际上只是撞车了，该说的是「稍后再试」。

        要点：
          · FOR NO KEY UPDATE SKIP LOCKED —— 不是 FOR UPDATE：本事务随后 INSERT 的
            claim 行会引用这张码（外键取 KEY SHARE 锁），FOR UPDATE 与 KEY SHARE 冲突。
            Odoo 核心同款用法与理由：odoo/addons/base/models/ir_cron.py:325-365，
            以及 odoo/orm/models.py:5591 try_lock_for_update(allow_referencing=True)。
          · 时刻由 Python 传入（UTC-naive），不用 SQL now()：edu_invite_code.expire_at 是
            timestamp without time zone，用 now()（timestamptz）会随会话时区漂移。
        """
        params = self._pool_params()
        if not params:
            return None
        self.env.cr.execute(
            "SELECT c.id FROM edu_invite_code c"
            " WHERE " + _POOL_WHERE +
            " ORDER BY c.id LIMIT 1 FOR NO KEY UPDATE SKIP LOCKED",
            params,
        )
        row = self.env.cr.fetchone()
        return row[0] if row else None

    @api.model
    def _pool_has_candidates(self):
        """池里是否**还挂着**可用的码（只读计数，不加锁、不跳过在途）。

        用途：把「取不到码」的两种原因分开 —— 池真空了 vs 都被别人锁着（见 _pick_locked_code_id）。
        """
        params = self._pool_params()
        if not params:
            return False
        self.env.cr.execute(
            "SELECT count(*) FROM edu_invite_code c WHERE " + _POOL_WHERE, params)
        return bool(self.env.cr.fetchone()[0])

    # ------------------------------------------------------------------
    # 领码（幂等 + 并发安全）
    # ------------------------------------------------------------------
    @api.model
    def claim_for_chat(self, chat_id, telegram_name=False, username=False):
        """为 chat_id 领一张码。幂等：已经领过就返回原来那条，不消耗新码。

        :return: (claim, created, busy)
            claim   —— edu.tg.claim 记录；空池或系统繁忙时是空 recordset
            created —— True = 这次真的新领了一张（调用方据此决定「先落库再出网」）
            busy    —— True = 连续冲突重试用尽（**不是空池**，两者文案不同）
        """
        chat_id = str(chat_id or '').strip()
        if not chat_id:
            return self.browse(), False, False
        for attempt in range(1, MAX_CLAIM_ATTEMPTS + 1):
            if attempt > 1:
                # 换快照：REPEATABLE READ 下**必须**结束当前事务，否则重试会一直撞同一张
                # （设计 §5.4 实测：savepoint 内重取 -> 又是同一张；ROLLBACK 后重取 -> 换到了）
                self.env.cr.rollback()
                # flush=False：回滚之后不得把缓存里的待写值再灌回新事务
                self.env.invalidate_all(flush=False)
                # 退避：此刻没有持有任何锁（锁随 ROLLBACK 释放），只是让撞车的批次错开
                time.sleep(RETRY_BACKOFF * attempt)
            existing = self.search([('chat_id', '=', chat_id)], limit=1)
            if existing:
                return existing, False, False
            code_id = self._pick_locked_code_id()
            if not code_id:
                if self._pool_has_candidates():
                    # 池里还有码，只是这一瞬间全被别人的事务锁着 -> 是可重试的「繁忙」，不是「空池」
                    _logger.info('edu_tg_bind: 第 %s 次没抢到空闲码（池非空，均被在途请求锁住），重试',
                                 attempt)
                    continue
                # 池真空了：交给调用方回「请联系教务处」
                return self.browse(), False, False
            try:
                with self.env.cr.savepoint():
                    claim = self.create({
                        'chat_id': chat_id,
                        'telegram_name': (telegram_name or '').strip()[:TEXT_FIELD_MAX],
                        'username': (username or '').strip()[:TEXT_FIELD_MAX],
                        'invite_code_id': code_id,
                    })
            except pg_errors.UniqueViolation as exc:
                # 两种可能：别人刚给同一个 chat 抢到了（chat 唯一），或同一张码被别人抢走了
                # （码唯一）。两种情况都靠下一次循环重来：重来第一步就是重新查 chat_id。
                _logger.info('edu_tg_bind: 领码冲突第 %s 次（约束 %s），重试',
                             attempt, exc.diag.constraint_name)
                continue
            return claim, True, False
        _logger.warning('edu_tg_bind: chat_id=%s 连续 %s 次冲突，放弃本次领取',
                        chat_id, MAX_CLAIM_ATTEMPTS)
        return self.browse(), False, True

    # ------------------------------------------------------------------
    # 文案与投递结果
    # ------------------------------------------------------------------
    def _tutorial_lines(self):
        """学生新手教程（2026-10-12 用户要求「要有一套完整的新手教程」）。

        为什么教程落在**这一侧**（而不是班务机器人那侧）：前门（edu_tg_gate）把
        「私聊 /start」判给学生领码流，学生的消息根本进不了 edu_tg_assist ——
        所以学生看到的说明只能由领码流的回复来给。班务机器人那侧给的是教职工版
        （见 edu_tg_assist/models/bot.py 的 help_text）。

        站点地址来自参数 edu_tg_bind.site_url（默认 https://edu.example.org）；
        /help/student 是网站已有的学生使用指南页（edu_portal 的帮助中心），不另写一份。
        """
        self.ensure_one()
        site = self._site_url()
        return [
            '',
            _('新手三步：'),
            _('① 打开注册地址，把上面的邀请码填进「邀请码」栏'),
            _('② 填姓名、邮箱（邮箱就是登录名）、密码（至少 6 位）→ 提交'),
            _('③ 打开 %s，用邮箱 + 密码登录', site + '/login'),
            '',
            _('网站使用指南：%s', site + '/help/student'),
            _('⚠ 密码只在网站登录页输入，绝不要在 Telegram 里发密码。'),
        ]

    def reply_text(self, created):
        """给这位学生的回复文案（全中文；文案口径见设计 §8 + 2026-10-12 教程）。"""
        self.ensure_one()
        code = self.invite_code_id.code or ''
        url = self._register_url()
        if created:
            head = [_('你的邀请码：%s', code), '', _('注册地址：%s', url)]
            foot = [_('（这个码只发给你一个人，请勿转发。）')]
        else:
            head = [_('你已经领过邀请码了，这是你原来那张：%s', code), '',
                    _('注册地址：%s', url)]
            foot = [_('（每个 Telegram 账号只能领一张邀请码。）')]
        return '\n'.join(head + self._tutorial_lines() + foot)

    # ------------------------------------------------------------------
    # 回复键盘（inline keyboard）—— 与文案**分开**构造
    #
    # 为什么分开：本轮只做「聊天里的按钮」；下一步要做 Telegram Mini App
    # （web_app 按钮 / 菜单按钮）。两件事都只动这一处，不用碰文案、也不用碰控制器。
    #
    # 按钮类型的依据（一手：Bot API 官方文档原文，2026-09-17 在本地容器内取回
    # https://core.telegram.org/bots/api ，页面显示当前为 Bot API 10.3）：
    #   · InlineKeyboardButton：「This object represents one button of an inline keyboard.
    #     Exactly one of the fields other than text, icon_custom_emoji_id, and style must be
    #     used to specify the type of the button.」⇒ 每个按钮**只能**选一种类型。
    #   · url：「Optional. HTTP or tg:// URL to be opened when the button is pressed.」
    #   · copy_text / CopyTextButton：「Optional. Description of the button that copies the
    #     specified text to the clipboard」/「text | String | The text to be copied to the
    #     clipboard; 1-256 characters」（引入时间有据：api-changelog「October 31, 2024
    #     Bot API 7.11 — Added the class CopyTextButton and the field copy_text in the class
    #     InlineKeyboardButton allowing bots to send and receive inline buttons that copy
    #     arbitrary text.」）
    # 本轮**不用**的按钮类型与理由：
    #   · callback_data：按官方文档，按下后会**新增一种更新** callback_query 进入 webhook
    #     （CallbackQuery 一节原文：「NOTE: After the user presses a callback button, Telegram
    #     clients will display a progress bar until you call answerCallbackQuery. It is,
    #     therefore, necessary to react by calling answerCallbackQuery even if no notification
    #     to the user is needed」）。要用它，生产 setWebhook 的 allowed_updates 必须从
    #     ["message"] 改成 ["message", "callback_query"]，且控制器要新增 answerCallbackQuery
    #     出网口。而本轮**没有任何「按了还要机器人再干活」的需求**（怎么用已经写在文案里）
    #     ⇒ 不引入这个依赖：少一处生产配置改动、少一条必须应答的分支。
    #   · web_app：那是下一步的 Mini App（在线文档原文：「Available only in private chats
    #     between a user and the bot」），本轮不做。
    #   · style（按钮颜色，api-changelog「Bot API 9.4 / 2026-02-09 — Added the field style to
    #     the classes KeyboardButton and InlineKeyboardButton, allowing bots to change the
    #     color of buttons.」）：纯客户端装饰，本地无法验证，本轮不用（默认样式由客户端决定）。
    @api.model
    def _button_url_ok(self, url):
        """这个地址能不能放进 url 按钮。

        为什么要守这一关：url 按钮里的地址不合法会让 Telegram **整条 sendMessage 400**，
        学生就一张码都收不到 —— 而我们只是想把地址做成按钮。
        ⇒ 只有 http / https / tg 开头的才配按钮；否则**不配 url 按钮**，
        文案里那行「注册地址：…」照旧（纯文本分支永远保底）。
        """
        return (url or '').lower().startswith(('http://', 'https://', 'tg://'))

    def reply_keyboard(self):
        """本模块的回复键盘；None = 这条回复不带按钮。

        与 reply_text() 分开构造：文本是文本，键盘是键盘。
        """
        self.ensure_one()
        rows = []
        url = self._register_url()
        if self._button_url_ok(url):
            rows.append([{'text': _('➡️ 去注册'), 'url': url}])
        code = (self.invite_code_id.code or '').strip()
        if 0 < len(code) <= 256:
            # copy_text.text 官方上限 256 字符；超了会被 Telegram 整条拒掉，故不配按钮
            rows.append([{'text': _('📋 复制邀请码'), 'copy_text': {'text': code}}])
        # 2026-10-12：教程里的「去登录 / 使用指南」也做成按钮（一行两个）。
        # 每个 url 都过 _button_url_ok —— 地址不合法会让**整条** sendMessage 400，
        # 学生会一张码都收不到；宁可少一个按钮也不能整条失败。
        site = self._site_url()
        second = []
        for label, target in ((_('🔑 去登录'), site + '/login'),
                              (_('📖 使用指南'), site + '/help/student')):
            if self._button_url_ok(target):
                second.append({'text': label, 'url': target})
        if second:
            rows.append(second)
        return {'inline_keyboard': rows} if rows else None

    def reply_body(self, created):
        """一次拿到「回复正文 + 键盘」——上下文里的唯一出入口。

        分开的第二层：调用方拿到 (text, reply_markup) 两件东西，
        将来换键盘（Mini App）不需要动文案，换文案也不需要动键盘。

        :return: (text: str, reply_markup: dict|None)
        """
        self.ensure_one()
        return self.reply_text(created), self.reply_keyboard()

    def record_notify(self, ok, error=''):
        """记下这次回复到底发出去没有（失败不吞，后台列表直接看得到）。"""
        self.ensure_one()
        self.write({
            'notify_state': 'sent' if ok else 'failed',
            'notify_error': (error or '')[:NOTIFY_ERROR_MAX],
            'notify_attempts': (self.notify_attempts or 0) + 1,
        })

    def mark_dry_run(self):
        """试运行：不发送，只标记（本地验证用）。"""
        self.ensure_one()
        self.write({'notify_state': 'skipped_dry_run', 'notify_error': ''})

    @api.model
    def handle_private_message(self, message):
        """一条私聊 message → 领码/回显的结果字典（**webhook 响应的唯一真相**）。

        为什么抽出来（2026-10-08 用户裁定复用 @sctrs_bot 之后）：
          SCRTS 现在由 edu_tg_gate 前门分发，Telegram 打的是前门那条路由；
          而 edu_tg_bind 自带的 /telegram/tgb/webhook 保留作一键回滚。
          **两条路由都必须走这一段** —— 两份拷贝必然漂移（本项目已有
          「互补 ≠ 并集完备」的教训）⇒ 单实现、双调用。控制器只做鉴权与解包。

        :return: dict，可直接作为 webhook 的 JSON 响应。
            非私聊 / 缺 chat_id → {'ok': True, 'ignored': ...}（不领码，不报错）。
        """
        chat = message.get('chat') or {}
        # 只处理私聊：群 / 超级群 / 频道一律忽略 —— 否则一个群能把码池刷空（设计 §8）
        if chat.get('type') != 'private':
            return {'ok': True, 'ignored': 'not_private'}
        chat_id = chat.get('id')
        if chat_id in (None, ''):
            return {'ok': True, 'ignored': 'no_chat_id'}

        sender = message.get('from') or {}
        display_name = ' '.join(
            part for part in (sender.get('first_name'), sender.get('last_name')) if part)
        claim, created, busy = self.claim_for_chat(
            chat_id, display_name, sender.get('username'))

        # 文案与键盘**分开**构造（键盘见 reply_keyboard）：
        # 空池 / 繁忙这两条没有可操作的按钮，永远是纯文本（键盘 None）。
        keyboard = None
        if busy:
            reply = BUSY_TEXT
        elif not claim:
            reply = POOL_EMPTY_TEXT
        else:
            reply, keyboard = claim.reply_body(created)

        if created:
            # 先落库再出网（设计 §5.6）。同时把行锁在出网之前释放：
            # 出网最长 8s，不能让它拖住别的学生。
            self.env.cr.commit()

        if self.is_dry_run():
            if claim:
                claim.mark_dry_run()
            # 试运行：把本来会发出去的话放进响应里，本地用占位 token 也能验完整链路
            return {'ok': True, 'created': created, 'dry_run': True,
                    'reply': reply, 'reply_markup': keyboard}

        ok, error = self.env['edu.tg.bot'].sudo().send_message(
            chat_id, reply, reply_markup=keyboard)
        if claim:
            claim.record_notify(ok, error)
        if not ok:
            _logger.warning('edu_tg_bind: 回复发送失败 chat_id=%s created=%s：%s',
                            chat_id, created, error)
        # 出网失败也返回 200：码已经落库，Telegram 不该重投，学生再发一条即重发同一张。
        # 响应里带 reply 是有意的（调用方必须持有 webhook secret；本地排障靠它）。
        return {'ok': True, 'created': created, 'sent': ok,
                'reply': reply, 'reply_markup': keyboard}
