# -*- coding: utf-8 -*-
"""机器人指令分发 —— **业务逻辑都在这**，控制器只做鉴权与解包（便于单测）。

指令注册表**自动发现**：凡是模型名以 edu.tg.assist. 开头、且实现了
_tg_assist_commands() 的模型，其返回的 {指令: 方法名} 会自动并入本表。
⇒ **加一条指令不需要改本文件**（多个任务并行时零写冲突）。

同类挂点（都靠自动发现，谁都不用改本文件）：
  · _tg_assist_group_commands() -> {指令: 方法名}  群指令（/notify 等）
  · _tg_assist_handle_callback(cq) -> dict|None     内联按钮回填
  · _note_group_message(msg, chat, rec, text)       群消息监听（@提醒用）
  · _tg_assist_note_private_message(msg, chat, person, text) -> 私聊自由消息（材料归档 F7 用）
返回约定：私聊处理函数签名 (person, rest, msg, chat) -> (reply_text, reply_markup) 或 None；
挂点函数返回 (reply_text, reply_markup) 表示「我处理了，用这段回话」，返回 None 表示「不归我」。
⚠ 挂点只在**指令没命中**时被调用：见过 /dm 这类真指令的人，材料归档不会去抢他的指令。
"""
import logging

from odoo import api, models

from odoo.addons.edu_tg_assist import menutext

_logger = logging.getLogger(__name__)

# 常驻底部键盘挂哪儿：2026-10-13 起改成「教职工的任何私聊回复都挂」
# （见 _keyboard_reply）——先前只挂 /start 家族与 /help，结果老师发一句自由
# 文本（被材料归档接手，markup 为空）回复就不带键盘，键盘一旦被客户端
# 收起就再也回不来，用户的原话是「我根本都没看到按钮」。

BASE_COMMANDS = {
    '/start': '_cmd_start',
    # '/assist' 是同义别名，给 SCRTS 前门分流用（edu_tg_gate，2026-10-08 用户裁定复用
    # @sctrs_bot）：老师发 /assist 时前门判据必然把他送到这里登记，不必先猜指令。
    '/assist': '_cmd_start',
    '/help': '_cmd_help',
    '/name': '_cmd_name',
    '/whoami': '_cmd_whoami',
    # D3：停止一对一私发（隐私出口）。用户 2026-10-10 反馈「功能太少」后补。
    '/stop': '_cmd_stop',
}

# 教程文案的**唯一来源**（设计文档 §9.12.7）：/help、/start、未知指令兜底三处都从这里取，
# 免得同一套说明在三个地方各写一份、改一处漏两处。
# ⚠ 硬规矩写进教程（B14）：**密码只在网站登录页输入，绝不要在 Telegram 里发密码** ——
#   机器人侧永远不需要密码，凡是索要密码的都是假的。
SITE_URL_PARAM = 'edu_tg_assist.site_url'
DEFAULT_SITE_URL = 'https://edu.example.org'


def help_text(person=None, site_url=DEFAULT_SITE_URL):
    """教职工版新手教程（纯函数，便于单测直接断言文案，不必起 Odoo）。"""
    base = (site_url or DEFAULT_SITE_URL).rstrip('/')
    if person is not None and getattr(person, 'role', '') == 'admin':
        perm = '（你是管理员：/dm 与 /notify 可用。）'
    else:
        perm = '（/dm 与 /notify 需要管理员权限；你不是管理员，发这两条会回「你没有这个权限」。）'
    return chr(10).join([
        '新手教程（行政 / 教师）',
        '不想记指令？点输入框下面那排按钮就行（按钮不见了就发一句 /menu 叫回来）。',
        '① 绑定身份：找管理员要一张绑定码，发 /bind BIND-XXXXXX（或点他给的链接）。',
        '② 绑定后，你在这里发任何消息都会进班务助手 —— 不用记指令。',
        '③ 常用指令：',
        '   /dm 张三 请交表 —— 一对一私发（仅管理员）',
        '   /bindcode 教师 张三 —— 生成一张身份绑定码给对方（仅管理员）',
        '   /tpl —— 看现成的文案模板',
        '   /menu —— 把按钮菜单叫回来（发通知 / 私发 / 模板，一步步点）',
        '   /whoami —— 看我登记成什么样',
        '   /stop —— 停止一对一私发（重新发 /start 可恢复）',
        '   /help —— 这条教程',
        '④ 群里：/notify 短名 内容 —— 广播；/alias 短名 —— 给本群起短名。',
        '⑤ 网站：' + base + '/login —— 用邮箱或学号 + 密码登录（帮助中心：' + base + '/help）。',
        '⑥ 安全：密码只在网站登录页输入，**绝不要在 Telegram 里发密码**。',
        '⑦ 隐私：本机器人保存你的 Telegram 号与真名，只用于私发与提醒；',
        '   它和学生匿名意见箱是两套独立系统，数据不互通、不合并。',
        perm,
    ])


class EduTgAssistBot(models.AbstractModel):
    _name = 'edu.tg.assist.bot'
    _description = '行政班务机器人指令处理'

    @api.model
    def _feature_models(self):
        """所有 edu.tg.assist.* 模型（自动发现，无需登记）。"""
        for name in sorted(self.env.registry):
            if name.startswith('edu.tg.assist.'):
                m = self.env.get(name)
                if m is not None:
                    yield name, m

    @api.model
    def _commands(self):
        """返回 {指令: (注册者模型, 方法名)}。

        ⚠ **必须记住注册者**：功能模型注册的处理器**不在 bot 模型上** —— 早先只存方法名，
        分发时 `getattr(self, name)` 必然 AttributeError，被控制器兜住后表现为
        「这条指令没反应」= **静默失败**（narrow-a 发现，2026-10-08）。
        群指令那条路本来就是对的（用注册者 m），这里对齐成同一口径。
        """
        table = {cmd: (self, meth) for cmd, meth in BASE_COMMANDS.items()}
        for name, m in self._feature_models():
            fn = getattr(m, '_tg_assist_commands', None)
            if callable(fn):
                try:
                    for cmd, meth in (fn() or {}).items():
                        table[cmd] = (m, meth)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning('edu_tg_assist: %s 注册指令失败：%s', name, type(exc).__name__)
        return table

    @api.model
    def handle_update(self, update, route=''):
        """处理一条 Telegram update。**不抛异常**，只记日志并返回结果字典。

        :param route: 入口名（gate / assist_webhook / 手工），只写进去重表留痕。
        """
        if not isinstance(update, dict):
            return {'ok': True, 'ignored': 'not_a_dict'}
        # 幂等（B3）：Telegram 在网络抖动、或我方没能在时限内回 200 时会**重投同一条
        # update（update_id 不变）—— 不去重就是重复私发 / 重复广播 / 重复留痕。
        if not self.env['edu.tg.assist.update_log'].sudo().claim(
                update.get('update_id'), self._update_kind(update), route):
            return {'ok': True, 'duplicate': True}
        if update.get('callback_query'):
            return self._handle_callback(update['callback_query'])
        # edited_message **整体忽略**（B3 续）：Telegram 给每条「编辑」发的是**新的
        # update_id**，所以幂等挡不住它 —— 把消息编辑一下就能让 /notify /dm 再跑一遍。
        # 三处入口口径一致：edu_tg_gate 的判据、edu_tg_bind 的控制器、这里，都不处理编辑。
        if update.get('edited_message'):
            return {'ok': True, 'ignored': 'edited_message'}
        msg = update.get('message') or {}
        if not msg:
            return {'ok': True, 'ignored': 'no_message'}
        chat = msg.get('chat') or {}
        ctype = chat.get('type')
        if ctype == 'private':
            return self._handle_private(msg, chat)
        if ctype in ('group', 'supergroup'):
            return self._handle_group(msg, chat)
        return {'ok': True, 'ignored': 'chat_type_%s' % ctype}

    @api.model
    def _update_kind(self, update):
        """update 的类型名（只用于去重表留痕）。"""
        for key in ('callback_query', 'message', 'edited_message', 'channel_post'):
            if update.get(key):
                return key
        return ','.join(sorted(k for k in update if k != 'update_id'))[:32]

    @api.model
    def _handle_private(self, msg, chat):
        user = msg.get('from') or {}
        persons = self.env['edu.tg.assist.person']
        # 先记「这条消息之前他是不是已经登记过」——C1 新人通知要等分发结束才发，
        # 而那时候人已经被 upsert 建出来了，只能在这里取事实。
        was_new = not persons.sudo().with_context(active_test=False).search(
            [('tg_user_id', '=', str(user.get('id') or ''))], limit=1)
        person = persons.upsert_from_user(user, chat.get('id'))
        text = (msg.get('text') or '').strip()
        if not text:
            # F7：非文本私聊（转发文件/图片/语音）也可能就是「要归档的材料」，先给挂点。
            reply = self._keyboard_reply(
                person, self._note_private_message(msg, chat, person, ''))
            if reply is None:
                return {'ok': True, 'ignored': 'non_text_private'}
            rtext, markup = reply
            ok, err = self.env['edu.tg.assist.api'].sudo().send_message(
                chat.get('id'), rtext, reply_markup=markup, kind='private_material')
            persons.notify_new_if_needs_label(person, was_new)
            return {'ok': ok, 'cmd': '', 'error': err}
        cmd, _, rest = text.partition(' ')
        cmd, rest = cmd.split('@')[0].lower(), rest.strip()
        if cmd == '/start' and rest:
            # 深链载荷（Telegram 只把 ?start=<载荷> 塞进 /start，没有别的载体）：
            # 归 /bind 处理，本文件不写绑定逻辑。前门只在载荷是我们签发的格式时
            # 才把 /start 送到这里（edu_tg_gate 的 bind_payload 判据），
            # 所以学生的 /start（无载荷）永远走不到这一行、领码流一字不变。
            cmd = '/bind'
        entry = self._commands().get(cmd)
        if entry:
            owner, meth = entry
            # 发指令 = 放弃没走完的按钮流程（2026-10-13）：否则他前一步的草稿会在
            # 下一秒被误当成「正文」发出去 —— 一条没人确认过的广播就此出网。
            self.env['edu.tg.assist.menu'].sudo()._clear_state(person)
            # 教职工的回复一律顺手挂上常驻底部键盘（老师从此不用记指令）。
            reply = self._keyboard_reply(person, getattr(owner, meth)(person, rest, msg, chat))
        else:
            # 按钮化界面（2026-10-13）：底部键盘按钮、以及「等正文」时发来的那句话，
            # 先问菜单层；它说「不归我」（None）再按老路走材料归档，最后才是兜底提示。
            reply = self.env['edu.tg.assist.menu'].sudo()._tg_assist_menu_reply(
                person, text, msg, chat)
            if reply is None:
                # F7：**不是指令**的自由消息先问一遍材料归档（只有教职工会接手）；
                # 挂点说「不归我」（学生、空内容）才回那句兜底提示。
                reply = self._note_private_message(msg, chat, person, text)
            # 材料归档（F7）的回执原本不带 markup —— 键盘收起后就此消失，这里补上。
            reply = self._keyboard_reply(person, reply)
            if reply is None:
                reply = ('我不认识这条指令。' + chr(10) + chr(10) + self._help_text(person),
                         menutext.reply_keyboard(self._keyboard_role(person), self._site_url()))
        if reply is None:
            persons.notify_new_if_needs_label(person, was_new)
            return {'ok': True, 'handled': cmd}
        rtext, markup = reply
        ok, err = self.env['edu.tg.assist.api'].sudo().send_message(
            chat.get('id'), rtext, reply_markup=markup, kind='private_cmd')
        # C1（2026-10-13 修）：新人的「请去后台标角色」通知必须等这条消息处理完再发 ——
        # 顺序反了就会给刚刚用 /start BIND-XXXXXX 绑好身份的人发假警报（Sarah💌 那次）。
        persons.notify_new_if_needs_label(person, was_new)
        return {'ok': ok, 'cmd': cmd, 'error': err}

    @api.model
    def _cmd_start(self, person, rest, msg, chat):
        # D3：/stop 之后又发 /start（或别名 /assist）= 本人明确要恢复，就恢复启用。
        # **只有这条指令**会恢复 —— 别的消息不偷偷复活（否则隐私出口等于没做）。
        if person and not person.active:
            # 地址被 /stop 清空过：恢复时必须把私聊地址一并写回来，
            # 否则人复活了却永远收不到 /dm 与提醒。
            cid = str(chat.get('id') or '') or person.chat_id
            person.sudo().write({'active': True, 'chat_id': cid})
        # C1 + 2026-10-12 绑定码：告诉他「身份怎么绑」，否则他不知道为什么
        # 之后发什么都被当前门当学生流（判据见 edu_tg_gate/routing.py）。
        tail = (chr(10) + '（身份还没绑定：找管理员要一张绑定码，发 /bind BIND-XXXXXX，' + chr(10) +
                '或直接点他给的链接 —— 绑定后你发任何消息都会进班务助手；在那之前只认指令。）')
        if person and person.role in ('admin', 'teacher', 'dorm_head'):
            head = '你已经绑定过了，%s。' % person.name
            return (head + chr(10) + self._help_text(person), None)
        if person and person.name and person.name != person.tg_name:
            return (('你已经登记过了，%s。' % person.name) + tail +
                    chr(10) + chr(10) + self._help_text(person), None)
        return ('你好！我是永约学坊的行政与班务助手。' + chr(10) +
                '请回一条：/name 你的真名' + chr(10) +
                '（一对一私发要靠真名找人，所以必须填。）' + tail +
                chr(10) + chr(10) + self._help_text(person), None)

    @api.model
    def _site_url(self):
        """网站地址（参数 edu_tg_assist.site_url，默认 https://edu.example.org）。

        教程里的「去登录 / 帮助中心」链接要用它；不读 edu_tg_bind 的 register_url
        （那是领码流的参数，两个模块不共享参数，见 B2 的同款口径）。
        """
        raw = (self.env['ir.config_parameter'].sudo().get_param(SITE_URL_PARAM, '') or '').strip()
        return raw or DEFAULT_SITE_URL

    @api.model
    def _keyboard_role(self, person):
        """底部键盘用哪个布局：只有 admin 那排才有「发通知 / 私发」两格。

        非 admin（教师/宿舍长/还没标角色的新人）给精简版 —— 按下去会被回「你没有这个权限」，
        不如一开始就不给他按。
        """
        return 'admin' if (person and person.role == 'admin') else 'teacher'

    @api.model
    def _keyboard_reply(self, person, reply):
        """给教职工的私聊回复补上常驻底部键盘（2026-10-13 用户「我根本都没看到按钮」）。

        只补「本来就没带 markup」的回复：按钮流程（菜单层）自己的 reply_markup
        是精心排的，不能覆盖。学生一律不补 —— 学生走前门时根本到不了 assist，
        这里再挡一道，谁的回复都不许多挂键盘（B12 学生流一字不变）。
        """
        if not isinstance(reply, tuple) or len(reply) != 2 or reply[1] is not None:
            return reply
        if not person or person.role == 'student':
            return reply
        return (reply[0], menutext.reply_keyboard(self._keyboard_role(person), self._site_url()))

    @api.model
    def _help_text(self, person=None):
        return help_text(person, self._site_url())

    @api.model
    def _cmd_help(self, person, rest, msg, chat):
        return (self._help_text(person), None)

    @api.model
    def _cmd_name(self, person, rest, msg, chat):
        name = (rest or '').strip()
        if not name:
            return ('用法：/name 张三', None)
        if len(name) > 32:
            return ('名字太长了，请写 32 字以内。', None)
        if person:
            person.sudo().write({'name': name})
        # C3：学生误发 /name 时给一句指路（学生要领的是注册邀请码，走领码流）
        return ('记下了：%s。' % name + chr(10) +
                '（如果你是学生、要的是注册邀请码，请发 /start。）', None)

    @api.model
    def _cmd_whoami(self, person, rest, msg, chat):
        if not person:
            return ('我这边没有你的记录，请先发 /start。', None)
        role = dict(person._fields['role'].selection).get(person.role) or person.role
        return ('姓名：%s' % person.name + chr(10) +
                '角色：%s' % role + chr(10) +
                'Telegram：%s' % (person.tg_name or '—'), None)

    @api.model
    def _cmd_stop(self, person, rest, msg, chat):
        """D3 —— 停止一对一私发：停用这条登记，并清掉私聊 chat_id。

        为什么清 chat_id：它是本模块里唯一能把消息**投递到你这个人**的地址，
        清掉之后 /dm 与各种提醒都发不到你（最稳）。tg_user_id 保留 ⇒ 重新 /start
        时还能认出是同一个人、直接恢复，不必重新登记。

        chat_id 是 required 字段：Odoo 只在 create 时校验 required，write 成空串合法
        （本地克隆实测 WRITE_EMPTY_OK）。
        """
        if not person:
            return ('我这边没有你的记录，本来就收不到一对一私发。', None)
        person.sudo().write({'active': False, 'chat_id': ''})
        return ('已停止一对一私发。' + chr(10) +
                '（登记已停用：/dm 和提醒都不会再打扰你；重新发 /start 即可恢复。）', None)

    @api.model
    def _handle_group(self, msg, chat):
        rec = self.env['edu.tg.assist.chat'].upsert_from_update(chat)
        text = (msg.get('text') or '').strip()
        self._note_group_message(msg, chat, rec, text)
        if text.startswith('/'):
            return self._handle_group_command(rec, msg, chat, text)
        return {'ok': True, 'group': rec.id if rec else None, 'noted': True}

    @api.model
    def _note_group_message(self, msg, chat, rec, text):
        """群消息监听挂点（@提醒用）。谁实现 _note_group_message 谁生效。"""
        for name, m in self._feature_models():
            fn = getattr(m, '_tg_assist_note_group_message', None)
            if callable(fn):
                try:
                    res = fn(msg, chat, rec, text)
                    if res:
                        return res
                except Exception as exc:  # noqa: BLE001
                    _logger.warning('edu_tg_assist: %s 处理群消息失败：%s', name, type(exc).__name__)
        return None

    @api.model
    def _note_private_message(self, msg, chat, person, text):
        """私聊自由消息挂点（F7 材料归档用）。

        谁实现 _tg_assist_note_private_message 谁生效；与群挂点同款自动发现，
        所以加业务不用改本文件。挂点抛异常只记日志（绝不把失败抛回给老师）。
        返回 None = 不归它管（学生、纯空消息）。
        """
        for name, m in self._feature_models():
            fn = getattr(m, '_tg_assist_note_private_message', None)
            if callable(fn):
                try:
                    res = fn(msg, chat, person, text)
                    if res:
                        return res
                except Exception as exc:  # noqa: BLE001
                    _logger.warning('edu_tg_assist: %s 处理私聊消息失败：%s', name, type(exc).__name__)
        return None

    @api.model
    def _handle_group_command(self, rec, msg, chat, text):
        cmd, _, rest = text.partition(' ')
        key = cmd.split('@')[0].lower()
        for name, m in self._feature_models():
            fn = getattr(m, '_tg_assist_group_commands', None)
            if callable(fn):
                try:
                    table = fn()
                except Exception as exc:  # noqa: BLE001
                    _logger.warning('edu_tg_assist: %s 注册群指令失败：%s', name, type(exc).__name__)
                    continue
                if key in table:
                    return getattr(m, table[key])(rec, rest.strip(), msg, chat)
        return {'ok': True, 'ignored': 'unknown_group_command'}

    @api.model
    def _handle_callback(self, cq):
        for name, m in self._feature_models():
            fn = getattr(m, '_tg_assist_handle_callback', None)
            if callable(fn):
                try:
                    res = fn(cq)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning('edu_tg_assist: %s 处理按钮失败：%s', name, type(exc).__name__)
                    continue
                if res:
                    return res
        cq_id = cq.get('id')
        if cq_id:
            self.env['edu.tg.assist.api'].sudo().call('answerCallbackQuery', {
                'callback_query_id': cq_id, 'text': '收到'})
        return {'ok': True, 'callback': 'default'}
