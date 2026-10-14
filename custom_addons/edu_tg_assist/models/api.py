# -*- coding: utf-8 -*-
"""Telegram Bot API 出网客户端 —— 本模块**唯一**的出网口。

照抄 edu_tg_bind/models/tg_bot.py 的纪律（那个模块已在生产验证）：
  · 容器内可**直连** api.telegram.org（实测 getMe 拿到真实 401 应答，DNS 203.0.113.9）；
  · 本客户端**不抛异常**：出网失败只回报 (False, 原因)，由调用方记进 edu.tg.assist.send_log；
  · **绝不把 token 写进日志**；
  · 纯文本消息的 payload 与带键盘的**逐字节可控**（加键盘不影响既有分支）；
  · 超时 (5, 8)：webhook 必须尽快返回，出网不能无限等。

⚠ 本模块**不用** scripts/telegram_relay.py —— 它认领的是 edu_telegram_outbox（生产匿名意见箱的表）。
"""
import logging
import time

import requests

from odoo import api, models
from odoo.addons.edu_tg_assist.tgtext import clamp_telegram_text, TELEGRAM_TEXT_LIMIT

_logger = logging.getLogger(__name__)

API_BASE = 'https://api.telegram.org'
TOKEN_PARAM = 'edu_tg_assist.token'
DRY_RUN_PARAM = 'edu_tg_assist.dry_run'
TIMEOUT = (5, 8)
MAX_ERROR = 500
CAPTION_LIMIT = 1024      # 文件说明（caption）上限：官方 1024 字符，超了整条拒收

# —— 重试口径 ——
# 只重试「**服务端回过话**」的 429 / 5xx：请求异常（超时/断网）状态未知，
# 重试有可能把同一条消息发第二遍 —— 宁可少发也不能重复发。
RETRY_STATUSES = frozenset((429, 500, 502, 503, 504))
RETRY_MAX = 2           # 最多再试 2 次（总共 3 次请求）
RETRY_BACKOFF = (1.0, 3.0)
RETRY_AFTER_MAX = 5.0   # 官方让等更久就直接放弃：webhook 必须尽快返回


class EduTgAssistApi(models.AbstractModel):
    _name = 'edu.tg.assist.api'
    _description = 'Telegram Bot API 客户端（edu_tg_assist 专用）'

    @api.model
    def _token(self):
        return (self.env['ir.config_parameter'].sudo().get_param(TOKEN_PARAM) or '').strip()

    @api.model
    def _dry_run(self):
        """试运行开关：'1' 时只落库不出网，便于本地演练。

        默认（未配置）= 真发。与 edu_tg_bind 的口径一致。
        """
        v = (self.env['ir.config_parameter'].sudo().get_param(DRY_RUN_PARAM) or '').strip()
        return v == '1'

    @api.model
    def _retry_delay(self, status, data, attempt):
        """这次失败值不值得等一会儿再试一次？

        :return: 要等的秒数；None = 不重试（直接把失败回报给调用方）。
        只认 429 / 5xx；429 若官方 retry_after 超过 RETRY_AFTER_MAX 就放弃 ——
        webhook 有返回时限，不能为了重试把连接挂住。
        """
        if attempt >= RETRY_MAX or status not in RETRY_STATUSES:
            return None
        default = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
        if status != 429:
            return default
        params = data.get('parameters') if isinstance(data, dict) else None
        try:
            wait = float((params or {}).get('retry_after'))
        except (TypeError, ValueError):
            return default
        if wait > RETRY_AFTER_MAX:
            return None
        return max(wait, 0.0)

    @api.model
    def call(self, method, payload):
        """调任意 Bot API 方法。:return: (ok, data_or_error)

        有界重试：429 / 5xx 最多再试 RETRY_MAX 次（退避 1s / 3s）；
        **请求异常（超时/断网）不重试** —— 那时请求可能其实已经送达。
        """
        token = self._token()
        if not token:
            return False, '未配置系统参数 %s' % TOKEN_PARAM
        url = '%s/bot%s/%s' % (API_BASE, token, method)
        attempt = 0
        while True:
            try:
                resp = requests.post(url, json=payload, timeout=TIMEOUT)
            except requests.RequestException as exc:
                # 网络层失败（超时/DNS/连接被拒）——注意**不要把 token 写进日志**
                _logger.warning('edu_tg_assist: %s 失败（网络）：%s', method, type(exc).__name__)
                return False, '%s: %s' % (type(exc).__name__, str(exc)[:MAX_ERROR])
            try:
                data = resp.json() if resp.content else {}
            except ValueError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            if resp.status_code == 200 and data.get('ok'):
                return True, data.get('result') or {}
            detail = data.get('description') or (resp.text or '')[:200]
            delay = self._retry_delay(resp.status_code, data, attempt)
            if delay is None:
                return False, 'HTTP %s: %s' % (resp.status_code, detail)
            attempt += 1
            _logger.warning('edu_tg_assist: %s 得 HTTP %s，%.1fs 后重试（第 %s 次）',
                            method, resp.status_code, delay, attempt)
            time.sleep(delay)

    @api.model
    def send_message(self, chat_id, text, reply_markup=None, kind='manual',
                     parse_mode=None):
        """发一条消息（可选带 inline keyboard / parse_mode），并**无条件**记进 send_log。

        :param reply_markup: 官方 InlineKeyboardMarkup 形状的 dict；None = 不带键盘。
        :param parse_mode: 'HTML' / 'MarkdownV2'；**None = 不带**（默认）。
            加它是为了支持「真 @人」：Telegram 只有在 HTML 模式下才认
            `<a href="tg://user?id=123">张三</a>` 这种提及链接，纯文本的「@学委」不会提醒到人。
            ⚠ 传了 parse_mode 就必须由调用方负责转义正文里的 `<` `>` `&`（本函数不替它转）。
        超长（> 4096 个 UTF-16 码元）会被 clamp_telegram_text **截断后再发**：
        Telegram 对超长是整条拒收（400 MESSAGE_TOO_LONG），广播场景宁可截断也别整条丢。
        :return: (ok: bool, error: str)。**任何失败都只回报，不抛异常。**
        """
        ok, err, _result = self.send_message_full(
            chat_id, text, reply_markup=reply_markup, kind=kind, parse_mode=parse_mode)
        return ok, err

    @api.model
    def send_message_full(self, chat_id, text, reply_markup=None, kind='manual',
                          parse_mode=None):
        """send_message 的完整版：多返回 Telegram 的 result（打卡要 message_id）。

        与 send_message 是**同一段实现**（不做第二份，免得两处漂移）：
        不需要 result 的调用方一律用 send_message。
        :return: (ok: bool, error: str, result: dict)。失败时 result={}。
        """
        text, truncated = clamp_telegram_text(text)
        if truncated:
            _logger.warning('edu_tg_assist: 正文超过 %s 个 UTF-16 码元，已截断后再发（kind=%s）',
                            TELEGRAM_TEXT_LIMIT, kind)
        payload = {
            'chat_id': str(chat_id),
            'text': text,
            'disable_web_page_preview': True,
        }
        if reply_markup:
            payload['reply_markup'] = reply_markup
        if parse_mode:
            payload['parse_mode'] = parse_mode

        if self._dry_run():
            self.env['edu.tg.assist.send_log'].sudo().log(
                chat_id, text, True, 'DRY_RUN（未出网）', kind)
            return True, 'DRY_RUN', {}

        ok, res = self.call('sendMessage', payload)
        err = '' if ok else str(res)
        self.env['edu.tg.assist.send_log'].sudo().log(chat_id, text, ok, err, kind)
        return ok, err, (res if ok and isinstance(res, dict) else {})

    @api.model
    def send_document(self, chat_id, file_id, caption=None, kind='manual'):
        """把**已经在 Telegram 云端**的文件（file_id）转发给某个会话 —— 不重传文件本体。

        2026-10-13 用户要求（选项 c）：「文件用 Telegram 的 file_id 转，不用重传」。
        同一个机器人的文件可以直接复用 file_id（sendDocument 的 document 参数就吃它），
        既不下载也不上传：省带宽、不碰 20 MB 的 getFile 上限、也不把学生材料落到磁盘上。

        与 send_message 同纪律：dry_run 只记日志不出网；**任何失败只回报、不抛异常**；
        且**无条件**记进 edu.tg.assist.send_log（后台「发送记录」要看得见）。

        :param file_id: 原消息里的 Telegram file_id（不是本库 file_data 的附件 id）。
        :param caption: 附言（可选）；超过 CAPTION_LIMIT 就截断（超长 Telegram 整条拒收）。
        :return: (ok: bool, error: str)
        """
        text = (caption or '')[:CAPTION_LIMIT]
        if self._dry_run():
            self.env['edu.tg.assist.send_log'].sudo().log(
                chat_id, text or file_id, True, 'DRY_RUN（未出网）', kind)
            return True, 'DRY_RUN'

        payload = {'chat_id': str(chat_id), 'document': file_id}
        if text:
            payload['caption'] = text
        ok, res = self.call('sendDocument', payload)
        err = '' if ok else str(res)
        self.env['edu.tg.assist.send_log'].sudo().log(
            chat_id, text or file_id, ok, err, kind)
        return ok, err

    # ------------------------------------------------------------------
    # D1 自检（后台「自检」菜单）—— **只读**：不发消息、不改库、不打印 token 明文
    # ------------------------------------------------------------------
    @api.model
    def selfcheck_lines(self):
        """把「到底能不能发得出去」逐项读成人话（✅/⚠️/❌），返回 list[str]。

        给不懂技术的人看：每行一句结论 + 该怎么处理。出网只调 getMe / getWebhookInfo。
        """
        ICP = self.env['ir.config_parameter'].sudo()
        lines = []
        token = self._token()
        lines.append(('✅' if token else '❌') + ' 机器人 token（edu_tg_assist.token）：' +
                     (('已配置，%d 字符' % len(token)) if token
                      else '**未配置** —— 一条消息也发不出去'))
        gate = self.env.get('edu.tg.gate.router') is not None
        lines.append(('✅' if gate else '❌') + ' 前门 edu_tg_gate：' +
                     ('已安装（Telegram 应指向 /telegram/sctrs/webhook）' if gate
                      else '**未安装** —— 老师的私聊会落进学生领码流'))
        for label, key in (('前门密钥', 'edu_tg_gate.webhook_secret'),
                           ('本模块直连密钥', 'edu_tg_assist.webhook_secret')):
            val = (ICP.get_param(key) or '').strip()
            lines.append(('✅' if val else '⚠️') + ' %s（%s）：%s'
                         % (label, key, ('已配置，%d 字符' % len(val)) if val else '未配置'))
        bind_token = (ICP.get_param('edu_tg_bind.token') or '').strip()
        if token and bind_token:
            same = token == bind_token
            lines.append(('✅' if same else '❌') +
                         ' 与学生领码流同一个机器人（edu_tg_bind.token）：' +
                         ('是 —— 前门才能把两种私聊分给两个模块' if same
                          else '**不是** —— 前门只对其中一个 bot 生效，另一个的私聊不会经过前门'))
        else:
            lines.append('⚠️ 学生领码流 token（edu_tg_bind.token）：' +
                         ('已配置' if bind_token else '未配置'))
        dry = self._dry_run()
        lines.append(('❌' if dry else '✅') + ' 试运行开关（edu_tg_assist.dry_run）：' +
                     ('1 —— **只落库不出网**，上线前务必改 0' if dry else '未开启（真发）'))
        owner = (ICP.get_param('edu_tg_assist.owner_user_id') or '').strip()
        if not owner:
            lines.append('⚠️ 管理员 Telegram 号（edu_tg_assist.owner_user_id）：未配置 —— '
                         '@提醒不会建待办、新登记也不通知')
        else:
            reg = self.env['edu.tg.assist.person'].sudo().search(
                [('tg_user_id', '=', owner), ('active', '=', True)], limit=1)
            lines.append(('✅' if (reg and reg.chat_id) else '❌') +
                         ' 管理员 Telegram 号：%s，' % owner +
                         ('已登记、可私聊' if (reg and reg.chat_id)
                          else '**还没私聊登记过** —— 收不到提醒（让他发 /start 再发 /name 真名）'))
        for name in ('edu_tg_assist: @提醒超时扫描',
                     'edu_tg_assist: 发送记录清理'):
            cron = self.env['ir.cron'].sudo().search([('name', '=', name)], limit=1)
            if not cron:
                lines.append('❌ 定时任务「%s」：不存在（需要升级模块）' % name)
            else:
                lines.append(('✅' if cron.active else '⚠️') + ' 定时任务「%s」：%s'
                             % (name, '已启用' if cron.active else '**未启用**'))
        counts = []
        for model, label in (('edu.tg.assist.person', '人员'), ('edu.tg.assist.chat', '群'),
                             ('edu.tg.assist.template', '模板'),
                             ('edu.tg.assist.reminder', '定时规则'),
                             ('edu.tg.assist.poll', '打卡'),
                             ('edu.tg.assist.send_log', '发送记录')):
            try:
                counts.append('%s %d' % (label, self.env[model].sudo().search_count([])))
            except Exception:  # noqa: BLE001
                counts.append('%s ?' % label)
        lines.append('· 现有：' + '／'.join(counts))
        lines.extend(self._selfcheck_telegram())
        return lines

    @api.model
    def _selfcheck_telegram(self):
        """Telegram 侧两问：我是谁（getMe）、消息往哪投（getWebhookInfo）。只读。"""
        base = (self.env['ir.config_parameter'].sudo()
                .get_param('web.base.url') or '').strip().rstrip('/')
        expected = (base + '/telegram/sctrs/webhook') if base else ''
        if not self._token():
            return ['⚠️ Telegram 侧未查（没有 token）']
        out = []
        ok, me = self.call('getMe', {})
        if ok and isinstance(me, dict):
            out.append('✅ getMe：@%s（%s），可加群=%s'
                       % (me.get('username'), me.get('first_name'),
                          '是' if me.get('can_join_groups') else '否'))
            can_read = bool(me.get('can_read_all_group_messages'))
            out.append(('✅' if can_read else '⚠️') + ' 能读群内所有消息（隐私模式）：' +
                       ('已关闭隐私模式 —— @提醒可用' if can_read
                        else '**隐私模式还开着** —— 群里不 @机器人 的消息收不到，@提醒不会触发；'
                             '去 BotFather /setprivacy 选这个 bot → Disable'))
        else:
            out.append('❌ getMe 失败：%s' % me)
        ok, info = self.call('getWebhookInfo', {})
        url = (info or {}).get('url') if isinstance(info, dict) else ''
        if ok and isinstance(info, dict):
            out.append(('✅' if (expected and url == expected) else '❌') +
                       ' webhook：%s' % (url or '（空）'))
            pending = info.get('pending_update_count')
            out.append(('✅' if not pending else '⚠️') + ' 待处理消息：%s' % pending)
            allowed = info.get('allowed_updates')
            out.append('✅ 允许的更新类型：%s' % (allowed if allowed else '（默认）'))
            if 'callback_query' not in (allowed or []):
                out.append('⚠️ allowed_updates 里没有 callback_query —— 打卡/回填按钮点不动')
            err = info.get('last_error_message')
            out.append(('✅' if not err else '❌') + ' 最近一次投递错误：%s' % (err or '无'))
        else:
            out.append('❌ getWebhookInfo 失败：%s' % info)
        if expected and not url:
            out.append('（期望的 webhook 网址是 %s）' % expected)
        return out

