# -*- coding: utf-8 -*-
"""F3 广播（/notify）—— 设计文档 §3 F3 的落地。

指令（**群里**用）：
    /notify 行政 各位同事请注意，本周五下午停水检修

安全口径（队长 2026-10-08 定）：
  1. **短名找不到就把可选项列出来**：回「没有这个群：行政（现有：行政/清洁能源站/…）」，
     不许猜、不许模糊匹配 —— 广播发错群的代价是全校都看见。
  2. **防误发**：正文去掉空白后短于 4 个字符，或**只有一个字母/数字/汉字都没有**（例如
     「…」「！！！」「。」这种手滑）=> **不发出**，回话要求显式确认；
     确认方式 = 再发一次并在正文前加「确认」二字。
  3. 广播成功走 api.send_message(kind='notify') => send_log 里按 kind=notify 可查
     「谁在什么时候广播了什么」（send_log 由 api.py 自己写，本文件不重复记）。
  4. **只有 role == 'admin' 的人能广播**（队长 2026-10-08 裁定，与 /dm 同口径）：
     其他人回「你没有这个权限」，并且**写一条 state=denied 的留痕行**；
     权限校验排在**短名解析之前** —— 非 admin 连「这个群存不存在」都探不到。
     （学委将来要往自己班群发：加 role 白名单即可，本轮不做。）

群指令的规矩（bot.py:136-138, 166-168）：**不认识的群指令静默**，群里不刷屏；
本文件只处理 /notify 一条，其余一概不管。
硬边界（设计文档 §2）：本文件不读写 edu.feedback.* / edu_telegram*（B1–B5）。
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

USAGE = '用法：/notify 行政 各位同事请注意…'
NO_PERM = '你没有这个权限。'
MIN_LEN = 4
CONFIRM_PREFIX = '确认'
MAX_ALIAS_SHOWN = 12


def _compact(text):
    """去掉所有空白（含全角空格），用来量「到底有几个字」。"""
    return ''.join((text or '').split())


def _has_meat(text):
    """有没有「实质内容」：任一个字符 isalnum() 为真即可。

    为什么不用正则字符类：**汉字、字母、数字的 isalnum() 都是 True**，标点/符号是 False，
    正好是我们要的判据（例：「。」「！！！」=> False；「停水」=> True）。
    """
    return any(ch.isalnum() for ch in text)


class EduTgAssistNotify(models.AbstractModel):
    """广播指令（不另立一张表：广播本身就是一条 send_log，账不重复记）。"""

    _name = 'edu.tg.assist.notify'
    _description = 'Telegram 群广播指令（/notify）'

    # ------------------------------------------------------------------
    # 指令注册（bot.py 自动发现）
    # ------------------------------------------------------------------
    @api.model
    def _tg_assist_group_commands(self):
        """**群**指令表（bot.py:154-168）。"""
        return {'/notify': '_cmd_notify', '/alias': '_cmd_alias'}

    @api.model
    def _tg_assist_commands(self):
        """私聊里也认领 /notify，只为回一句「广播要在群里发」——
        否则私聊发 /notify 会落到「我不认识这条指令」，看着像功能不存在。"""
        return {'/notify': '_cmd_notify_private'}

    @api.model
    def _cmd_notify_private(self, person, rest, msg, chat):
        return ('广播要在群里发：' + USAGE, None)

    # ------------------------------------------------------------------
    # 群指令本体
    # ------------------------------------------------------------------
    @api.model
    def _cmd_notify(self, rec, rest, msg, chat):
        """群指令契约（bot.py:167）：(rec, rest, msg, chat) -> dict。

        群指令**不会自动回复** => 每一句回话都自己调 api.send_message
        （回话 kind=notify_guard，真正广播 kind=notify：后者是队长指定的事后追查口径）。
        """
        # ① 权限（队长 2026-10-08 裁定）：与 /dm 同口径，且**排在短名解析之前** ——
        #    非 admin 不该能靠「发一条 /notify 看回话」探出哪个短名存在。
        sender = self._sender_person(msg)
        if not sender or sender.role != 'admin':
            self._audit_denied(sender, rest)
            return self._say(chat, NO_PERM, 'denied')

        alias, _, body = (rest or '').strip().partition(' ')
        alias, body = alias.strip(), body.strip()
        if not alias or not body:
            return self._say(chat, USAGE, 'usage')

        target = self.env['edu.tg.assist.chat'].find_by_alias(alias)
        if not target:
            return self._say(chat, '没有这个群：%s（现有：%s）'
                             % (alias, self._alias_choices()), 'no_such_group')

        force = False
        if body.startswith(CONFIRM_PREFIX):
            force = True
            body = body[len(CONFIRM_PREFIX):].strip()
            if not body:
                return self._say(chat, USAGE, 'usage')

        if not force and self._needs_confirm(body):
            return self._say(
                chat,
                '这条没有发出：正文少于 %d 个字、或一个字母/数字/汉字都没有。' % MIN_LEN +
                '确认要广播，请再发一次并在正文前加「%s」：' % CONFIRM_PREFIX +
                chr(10) + '/notify %s %s <正文>' % (alias, CONFIRM_PREFIX),
                'needs_confirm')

        # C4：用 full 版拿 message_id —— 出事能拿它去 Telegram 侧对账（原来是 2 元返回）
        ok, err, res = self.env['edu.tg.assist.api'].sudo().send_message_full(
            target.chat_id, body, kind='notify')
        if not ok:
            _logger.warning('edu_tg_assist: /notify 广播失败（群 id=%s）', target.id)
            return self._say(chat, '广播失败：%s' % (err or '未知原因'), 'failed')
        mid = (res or {}).get('message_id')
        return self._say(chat, '已广播到「%s」。（消息 id：%s）'
                         % (target.alias or target.title or '', mid or '—'), 'sent')

    @api.model
    def _cmd_alias(self, rec, rest, msg, chat):
        """C2 —— 在群里给**当前这个群**起短名：/alias 学习群。

        广播要写短名、后台也要手填 —— 群里一句话就能设好，不必跑后台。
        口径与 /notify 一致：只有 admin 能设，越权照样写 state=denied 留痕。
        已有短名**绝不覆盖**（撞名回话让人换一个；真要改，先在后台清掉旧短名）。
        """
        sender = self._sender_person(msg)
        if not sender or sender.role != 'admin':
            self._audit_denied(sender, ('alias ' + (rest or '')).strip())
            return self._say(chat, NO_PERM, 'denied')
        if not rec:
            return self._say(chat, '我这边没有这个群的记录，请先在这个群里发一条消息。',
                             'no_chat')
        alias = (rest or '').strip().split(' ')[0].strip()[:32]
        if not alias:
            now = (rec.alias or '').strip()
            return self._say(chat, ('这个群的短名是「%s」。' % now) if now
                             else '这个群还没有短名。用法：/alias 学习群', 'alias_show')
        taken = self.env['edu.tg.assist.chat'].sudo().search(
            [('alias', '=', alias), ('id', '!=', rec.id)], limit=1)
        if taken:
            return self._say(chat, '短名「%s」已经被「%s」占用了，请换一个。'
                             % (alias, taken.title or taken.alias), 'alias_taken')
        try:
            # savepoint：唯一约束兜底（并发下 search 与 write 之间可能被插队），
            # 回滚到存盘点后还能继续发回话，不会把整条 update 打挂。
            with self.env.cr.savepoint():
                rec.sudo().write({'alias': alias})
        except Exception:  # noqa: BLE001
            return self._say(chat, '短名「%s」已经被占用了，请换一个。' % alias,
                             'alias_taken')
        return self._say(chat, '这个群的短名已设为「%s」。广播：/notify %s 内容'
                         % (alias, alias), 'alias_set')

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @api.model
    def _sender_person(self, msg):
        """按 from.id **只读**查登记人。

        为什么不用 person.upsert_from_user()：那是私聊路径的写法，它会把**当前 chat_id**
        写进对方的 chat_id 字段 —— 群里调用会把私聊 chat_id 覆盖成群 id，之后私发就发错地方。
        这里只查不写；查不到 = 没登记过 = 非 admin（设计文档 §6：只收主动 /start 并报真名的人）。
        """
        uid = ((msg or {}).get('from') or {}).get('id')
        Person = self.env['edu.tg.assist.person'].sudo()
        if not uid:
            return Person.search([('tg_user_id', '=', '')], limit=1)
        return Person.search([('tg_user_id', '=', str(uid))], limit=1)

    @api.model
    def _audit_denied(self, sender, rest):
        """越权留痕：写进 edu.tg.assist.dm（与 /dm 共用同一张审计表，state=denied）。

        为什么复用那张表：队长要求「与 /dm 同口径」；广播与私发同属「替学校发话」，
        在一张表里按结果筛「被拒绝（越权尝试）」比分散两张表更好查。
        raw 字段记完整的 '/notify …'，与 /dm 的行一眼可分。**永不抛异常**。
        """
        try:
            self.env['edu.tg.assist.dm'].sudo().create({
                'sender_name': (sender.name if sender else '') or '',
                'sender_tg_user_id': (sender.tg_user_id if sender else '') or '',
                'sender_role': (sender.role if sender else '') or '',
                'raw': ('/notify ' + (rest or '')).strip()[:255],
                'target_name': (rest or '').strip().partition(' ')[0][:255],
                'state': 'denied',
                'error': '无权限（需要 admin）：群广播',
            })
        except Exception as exc:  # noqa: BLE001
            _logger.warning('edu_tg_assist: 写广播越权留痕失败：%s', type(exc).__name__)

    @api.model
    def _needs_confirm(self, body):
        """要不要拦下来确认：去空白后短于 MIN_LEN，或一个 alnum 字符都没有。"""
        compact = _compact(body)
        if len(compact) < MIN_LEN:
            return True
        return not _has_meat(compact)

    @api.model
    def _alias_choices(self):
        """现有短名（给「没有这个群」那句用）。**只读 chat 表**，不碰任何别的表。"""
        recs = self.env['edu.tg.assist.chat'].sudo().search(
            [('active', '=', True), ('alias', '!=', False)], order='alias asc')
        names = [r.alias for r in recs if (r.alias or '').strip()]
        if not names:
            return '还没有登记任何短名（先在后台「群与短名」里加）'
        return '/'.join(names[:MAX_ALIAS_SHOWN]) + ('…' if len(names) > MAX_ALIAS_SHOWN else '')

    @api.model
    def _say(self, chat, text, state):
        """在群里回一句（自己发；群指令契约不会替我发）。永不抛异常。"""
        ok, err = self.env['edu.tg.assist.api'].sudo().send_message(
            chat.get('id'), text, kind='notify_guard')
        return {'ok': bool(ok), 'notify': state, 'error': err or ''}