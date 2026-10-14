# -*- coding: utf-8 -*-
"""按钮化界面（不用记斜杠命令）—— 2026-10-13 用户反馈后的落地。

用户原话（m02653）：「我总感觉这个机器人不够好用，尤其是对于不擅长写代码什么的人，
你让他使用斜杠命令是有点学习成本的，就不能搞得跟软件一样方便而且一目了然吗」

⇒ 本模型把「老师最常做的三件事」全变成**点按钮**：
  ① 📢 发通知到群：点按钮 → 点群名 → 发一段正文 → 看预览 → 点「✅ 确认发送」；
  ② ✉️ 私发给某人：点按钮 → 点人名 → 发一段正文 → 看预览 → 点「✅ 确认发送」；
  ③ 📄 文案模板：点按钮 → 点模板 → 看成品 → 想发就点「📢 发到群」→ 点群名。
斜杠命令**一条都没删**（老用户照旧可用），按钮只是把同样的能力包了一层壳。

三条纪律：
  · 每一步都**先预览、后发送**（广播与私发都是不可撤回的出网动作）；
  · 权限判据与指令版**逐字一致**（通知/私发只有 admin；越权照样写审计行）——
    按钮不能成为绕过权限的旁门；
  · 认不出、办不到、状态丢了 —— 一律**明说**并给回家的路（绝不静默失败）。

硬边界（设计文档 §2）：本文件不读写 edu.feedback.* / edu_telegram*（B1–B5、B7）。
"""
import logging

from odoo import api, fields, models

from odoo.addons.edu_tg_assist import menutext
from odoo.addons.edu_tg_assist.models.template import WEEKDAYS_CN

_logger = logging.getLogger(__name__)

STAFF_ROLES = ('admin', 'teacher', 'dorm_head')
#: 一个选择页最多列几个按钮（超过就提示去后台），免得一条消息几十行按钮。
PICK_LIMIT = 20
#: 草稿上限：Telegram 单条 4096，留出预览前后缀的余量。
DRAFT_MAX = 3500
#: 系统参数：私人聊天里那颗 **Telegram 自带**的菜单按钮要不要设成「面板」（默认 1 = 设）。
#: 设成面板后，输入框旁边那颗按钮一键开面板（官方列的 Mini App 启动方式，各端都给身份数据）。
MENU_BUTTON_PARAM = 'edu_tg_assist.menu_button'
#: 那颗按钮上的字（Telegram 限制 64 字符以内）。
MENU_BUTTON_TEXT = '打开面板'
NO_PERM = '你没有这个权限。'
ROLE_LABELS = {'admin': '行政', 'teacher': '教师', 'dorm_head': '宿舍长', 'other': '其他', 'student': '学生'}


class EduTgAssistMenu(models.AbstractModel):
    """把「指令」翻译成「按钮」的那一层。**不新立任何表**，状态挂在本模块自己的 person 上。"""

    _name = 'edu.tg.assist.menu'
    _description = '班务机器人按钮菜单（不用记指令）'

    # ------------------------------------------------------------------
    # 指令注册（bot.py 自动发现）
    # ------------------------------------------------------------------
    @api.model
    def _tg_assist_commands(self):
        """私聊 /menu —— 随时把按钮菜单叫回来（也顺手清掉没走完的草稿）。"""
        return {'/menu': '_cmd_menu'}

    @api.model
    def _cmd_menu(self, person, rest, msg, chat):
        """主菜单 + **两条入口**一起发（2026-10-14）。

        一条消息只能带一种 reply_markup：底部常驻键盘与内联按钮不能挂在同一条上，
        所以这里自己发两条（发完返回 None，让 bot.py 不要再发一遍）：
          ① 主菜单文案 + 底部常驻键盘（手机版就用这一条）；
          ② 内联「🖥 打开面板」按钮 —— 电脑版 Telegram 上底部键盘的 web_app 按钮不生效
             （点下去等于点了个普通链接，页面拿不到身份数据，只看到 no initData），
             内联 web_app 是官方列出的启动方式之一，各端都认。
        """
        self._clear_state(person)
        self._ensure_menu_button(chat, person)
        self._send(chat and chat.get('id'), self.home_text(person),
                   menutext.reply_keyboard(self._role(person)), kind='private_cmd')
        self._send_app_button(chat)
        return None

    @api.model
    def _send_app_button(self, chat):
        """补一条**内联**的「打开面板」按钮（电脑版走这条路；手机版两条都能用）。"""
        chat_id = (chat or {}).get('id')
        if not chat_id:
            return False
        return self._send(
            chat_id,
            '🖥 电脑版点这个按钮打开面板；手机版点底部那排「🖥 打开面板」也行。',
            menutext.app_inline(self.env['edu.tg.assist.bot'].sudo()._site_url()),
            kind='menu')

    @api.model
    def _ensure_menu_button(self, chat, person):
        """把私人聊天里那颗 **Telegram 自带**的菜单按钮设成「面板」（2026-10-14）。

        那颗按钮长在输入框旁边，是 Telegram 自己的 UI（不是消息里挂的按钮），默认开「命令列表」。
        设成 web_app 后它一键开面板，而且属于官方列出的 Mini App 启动方式、各端都给身份数据 ——
        正好补上「底部键盘的 web_app 按钮在电脑版打不开」那个洞（用户 m04148 反馈）。

        只按聊天设（setChatMenuButton 带 chat_id），**不动全局默认、不动群**；只给教职工设；
        系统参数 edu_tg_assist.menu_button = 0 可关（默认开）。失败只记日志 —— 绝不能因为这颗
        按钮没设上，把 /menu 的正常回复也搞没了。
        """
        chat = chat or {}
        if chat.get('type') != 'private' or not chat.get('id'):
            return False
        if (person and person.role) not in STAFF_ROLES:
            return False
        param = self.env['ir.config_parameter'].sudo().get_param(MENU_BUTTON_PARAM, '1')
        if (param or '').strip() in ('0', 'false', 'False', ''):
            return False
        try:
            site = self.env['edu.tg.assist.bot'].sudo()._site_url()
            ok, data = self.env['edu.tg.assist.api'].sudo().call('setChatMenuButton', {
                'chat_id': int(chat.get('id')),
                'menu_button': {'type': 'web_app', 'text': MENU_BUTTON_TEXT,
                                'web_app': {'url': menutext.app_url(site)}},
            })
        except Exception as exc:
            _logger.warning('tg-assist: setChatMenuButton 异常 %s', type(exc).__name__)
            return False
        if not ok:
            _logger.info('tg-assist: setChatMenuButton 没设上 chat=%s', chat.get('id'))
        return ok

    # ------------------------------------------------------------------
    # 文案
    # ------------------------------------------------------------------
    @api.model
    def _role(self, person):
        return (person.role if person and person.role else 'teacher')

    @api.model
    def home_text(self, person):
        rows = ['🏠 班务助手 —— 点下面的按钮就行，不用记指令。', '']
        if self._is_admin(person):
            rows += ['管理员常做的三件事：',
                     '· 📢 发通知到群 —— 点群名 → 发内容 → 确认',
                     '· ✉️ 私发给某人 —— 点人名 → 发内容 → 确认',
                     '· 📄 文案模板 —— 现成文案，可以直接发到群']
        else:
            rows += ['常做的事：',
                     '· 📄 文案模板 —— 现成文案，点开就能看',
                     '· 👤 我的身份 —— 看后台记的你是谁']
        rows += ['', '📚 使用说明 —— 全部功能；🔕 停止私发 —— 不想再收到私发时点它。']
        return chr(10).join(rows)

    @api.model
    def _preview(self, head, body):
        return chr(10).join([
            head, '', '——————————', body, '——————————', '',
            '核对无误请点「' + menutext.CONFIRM_LABEL + '」；不想发就点「' + menutext.CANCEL_LABEL + '」。',
        ])

    # ------------------------------------------------------------------
    # 底部键盘按钮（= 用户发来一段按钮文字）
    # ------------------------------------------------------------------
    @api.model
    def _tg_assist_menu_reply(self, person, text, msg, chat):
        """bot 私聊自由文本的挂点（_手动调用）。返回 (文案, markup) 或 None（= 不归我，交给材料归档）。"""
        text = (text or '').strip()
        # 底部键盘那颗「🖥 打开面板」是纯文字按钮 ⇒ 点了会把文案当消息发过来（2026-10-14）。
        # 回一条**带内联按钮**的消息：内联 web_app 是官方列的启动方式，电脑版/手机版都认。
        if menutext.is_app_tap(text):
            return ('🖥 点下面这颗按钮打开面板（手机版、电脑版都能开）。',
                    menutext.app_inline(self.env['edu.tg.assist.bot'].sudo()._site_url()))
        act = menutext.button_action(text)
        if act:
            return self._button(person, act, chat)
        return self._draft_input(person, text, chat)

    @api.model
    def _button(self, person, act, chat):
        self._clear_state(person)
        bot = self.env['edu.tg.assist.bot']
        if act == menutext.ACT_HOME:
            return (self.home_text(person), menutext.reply_keyboard(self._role(person)))
        if act == menutext.ACT_WHOAMI:
            return bot._cmd_whoami(person, '', {}, chat or {})
        if act == menutext.ACT_HELP:
            return (bot._help_text(person), menutext.reply_keyboard(self._role(person)))
        if act == menutext.ACT_STOP:
            return bot._cmd_stop(person, '', {}, chat or {})
        if act == menutext.ACT_TPL:
            return self._pick_template(person)
        if act in menutext.ADMIN_ONLY:
            if not self._is_admin(person):
                self._audit_denied(person, act)
                return (NO_PERM + chr(10) + '（这两个动作只有管理员能用；' +
                        '要发通知或私发，请找行政。）',
                        menutext.reply_keyboard(self._role(person)))
            if act == menutext.ACT_NOTIFY:
                return self._pick_group(person, menutext.ACT_GROUP)
            return self._pick_person(person)
        return (self.home_text(person), menutext.reply_keyboard(self._role(person)))

    # ------------------------------------------------------------------
    # 选择页
    # ------------------------------------------------------------------
    @api.model
    def _pick_group(self, person, action, tpl_id=None):
        """列群给用户点。action=grp（广播）或 tps（把模板发到群）。"""
        chats = self.env['edu.tg.assist.chat'].sudo().search(
            [('active', '=', True), ('chat_id', '!=', '')], limit=60)
        # 有短名的排前面（短名是「要发通知的群」最直接的标识）
        chats = sorted(chats, key=lambda c: (not (c.alias or '').strip(),
                                             (c.alias or c.title or '').strip()))
        if not chats:
            return ('后台还没有登记任何群。' + chr(10) +
                    '把机器人拉进群、在群里随便发一条消息，它就自动记下了；' +
                    '也可以去后台「班务机器人 → 群与短名」手动加。',
                    menutext.reply_keyboard(self._role(person)))
        rows, row = [], []
        for c in chats[:PICK_LIMIT]:
            label = menutext.truncate(c.alias or c.title or c.chat_id, 24)
            act = (action, tpl_id, c.id) if tpl_id else (action, c.id)
            row.append((label, act))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        if len(chats) > PICK_LIMIT:
            rows.append([('（还有更多群，请去后台「群与短名」看全）', menutext.ACT_HOME)])
        head = '📢 想发到哪个群？点一下：'
        if tpl_id:
            head = '📄 这条模板想发到哪个群？点一下：'
        return (head, menutext.inline(rows + [menutext.back_row()]))

    @api.model
    def _pick_person(self, person):
        people = self.env['edu.tg.assist.person'].sudo().search(
            [('role', 'in', list(STAFF_ROLES)), ('active', '=', True), ('chat_id', '!=', '')],
            limit=60)
        people = sorted(people, key=lambda p: (p.name or ''))
        if not people:
            return ('还没有可私发的人。' + chr(10) + chr(10) +
                    '一对一私发只能发给**跟机器人说过话**的人（Telegram 不允许机器人主动找陌生人）：' +
                    '请对方私聊本机器人，发一句 /start，再发 /name 真名；' +
                    '登记好之后，这里就会出现他的名字。',
                    menutext.reply_keyboard(self._role(person)))
        rows, row = [], []
        for p in people[:PICK_LIMIT]:
            label = menutext.truncate(p.name or p.tg_name or p.tg_user_id, 20)
            row.append((label, (menutext.ACT_TARGET, p.id)))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return ('✉️ 想私发给谁？点一下：', menutext.inline(rows + [menutext.back_row()]))

    @api.model
    def _pick_template(self, person):
        tpls = self.env['edu.tg.assist.template'].sudo().search(
            [('active', '=', True)], limit=PICK_LIMIT)
        if not tpls:
            return ('模板库里还没有启用的模板。' + chr(10) +
                    '去后台「班务机器人 → 文案模板」加几条，再回来点这个按钮。',
                    menutext.reply_keyboard(self._role(person)))
        rows = [[(t.name, (menutext.ACT_TPL_OPEN, t.id))] for t in tpls]
        return ('📄 模板库（%d 条）—— 点一条看成品：' % len(tpls),
                menutext.inline(rows + [menutext.back_row()]))

    # ------------------------------------------------------------------
    # 草稿输入（用户发来的那段正文）
    # ------------------------------------------------------------------
    @api.model
    def _has_meat(self, text):
        """有没有实质内容：任一个字符 isalnum（汉字/字母/数字都算），标点与表情不算。"""
        return any(ch.isalnum() for ch in (text or ''))

    @api.model
    def _browse_id(self, model, raw):
        try:
            rec = self.env[model].sudo().browse(int(raw))
        except (TypeError, ValueError):
            return self.env[model].sudo().browse()
        return rec if rec.exists() else self.env[model].sudo().browse()

    @api.model
    def _draft_input(self, person, text, chat):
        """有草稿状态时，用户发来的正文。返回 (预览, 确认键盘)；没状态 -> None（不认领）。"""
        if not person or not person.ui_state or not text:
            return None
        kind, target = person.ui_state, (person.ui_target or '')
        kb_back = menutext.reply_keyboard(self._role(person))
        if kind == 'notify':
            rec = self._browse_id('edu.tg.assist.chat', target)
            if not rec or not rec.chat_id:
                self._clear_state(person)
                return ('这个群不在登记表里了，请重新点「📢 发通知到群」。', kb_back)
            if not self._has_meat(text):
                return ('这句话没有实际内容（只有标点或表情），再发一次正文吧。', None)
            person.sudo().write({'ui_draft': text[:DRAFT_MAX]})
            head = '📢 将要发到「%s」：' % (rec.alias or rec.title or rec.chat_id)
            return (self._preview(head, text), menutext.inline(menutext.confirm_rows()))
        if kind == 'dm':
            rec = self._browse_id('edu.tg.assist.person', target)
            if not rec or not rec.chat_id:
                self._clear_state(person)
                return ('这个人现在没有可用的私聊会话，请重新点「✉️ 私发给某人」。', kb_back)
            if not self._has_meat(text):
                return ('这句话没有实际内容（只有标点或表情），再发一次吧。', None)
            person.sudo().write({'ui_draft': text[:DRAFT_MAX]})
            head = '✉️ 将要私发给 %s（%s）：' % (rec.name, ROLE_LABELS.get(rec.role, rec.role))
            return (self._preview(head, text), menutext.inline(menutext.confirm_rows()))
        return None

    # ------------------------------------------------------------------
    # 内联按钮回调
    # ------------------------------------------------------------------
    @api.model
    def _tg_assist_handle_callback(self, cq):
        """内联按钮挂点（bot.py 自动发现）。返回真值 = 已认领（认领了就必须 answer）。"""
        if not isinstance(cq, dict):
            return None
        parts = menutext.parse_callback(cq.get('data'))
        if not parts:
            return None
        frm = cq.get('from') or {}
        uid = str(frm.get('id') or '')
        person = self.env['edu.tg.assist.person'].sudo().search(
            [('tg_user_id', '=', uid)], limit=1)
        chat = ((cq.get('message') or {}).get('chat') or {})
        chat_id = chat.get('id') or (person.chat_id if person else None)
        self._answer(cq.get('id'))
        if not person:
            self._send(chat_id, '我这边没有你的记录，请先私聊我发一句 /start。')
            return {'ok': True, 'menu': 'unregistered'}
        try:
            self._dispatch_callback(person, parts, chat_id)
        except Exception as exc:  # noqa: BLE001
            # 按钮点下去**绝不能没反应**：出问题也要回一句，并给回家的路。
            _logger.warning('edu_tg_assist: 菜单按钮处理失败（%s）：%s',
                            parts[0], type(exc).__name__)
            self._send(chat_id, '这一步没做成（%s），请重新点一次菜单。' % type(exc).__name__,
                       menutext.reply_keyboard(self._role(person)))
        return {'ok': True, 'menu': parts[0]}

    @api.model
    def _dispatch_callback(self, person, parts, chat_id):
        act = parts[0]
        args = list(parts[1:])
        kb_back = menutext.reply_keyboard(self._role(person))
        bot = self.env['edu.tg.assist.bot']

        if act == menutext.ACT_HOME:
            self._clear_state(person)
            return self._send(chat_id, self.home_text(person), kb_back)
        if act == menutext.ACT_WHOAMI:
            text, markup = bot._cmd_whoami(person, '', {}, {})
            return self._send(chat_id, text, markup or kb_back)
        if act == menutext.ACT_HELP:
            return self._send(chat_id, bot._help_text(person), kb_back)
        if act == menutext.ACT_STOP:
            self._clear_state(person)
            text, markup = bot._cmd_stop(person, '', {}, {})
            return self._send(chat_id, text, markup or kb_back)
        if act == menutext.ACT_CANCEL:
            self._clear_state(person)
            return self._send(chat_id, '已取消。想做什么就点下面的按钮。', kb_back)
        if act == menutext.ACT_SEND:
            text, markup = self._do_send(person)
            return self._send(chat_id, text, markup or kb_back)
        if act == menutext.ACT_TPL:
            text, markup = self._pick_template(person)
            return self._send(chat_id, text, markup)
        if act == menutext.ACT_TPL_OPEN:
            return self._open_template(person, args, chat_id)
        if act == menutext.ACT_TPL_GROUP:
            if not self._require_admin(person, act):
                return self._send(chat_id, NO_PERM, kb_back)
            text, markup = self._pick_group(person, menutext.ACT_TPL_SEND,
                                            tpl_id=(args[0] if args else None))
            return self._send(chat_id, text, markup)
        if act == menutext.ACT_TPL_SEND:
            if not self._require_admin(person, act):
                return self._send(chat_id, NO_PERM, kb_back)
            text, markup = self._send_template_to_group(person, args)
            return self._send(chat_id, text, markup or kb_back)

        # ---- 广播 / 私发族：权限与指令版逐字一致 ----
        if act in (menutext.ACT_NOTIFY, menutext.ACT_GROUP, menutext.ACT_DM,
                   menutext.ACT_TARGET):
            if not self._require_admin(person, act):
                return self._send(chat_id, NO_PERM + chr(10) +
                                  '（发通知与私发只有管理员能用。）', kb_back)
        if act == menutext.ACT_NOTIFY:
            text, markup = self._pick_group(person, menutext.ACT_GROUP)
            return self._send(chat_id, text, markup)
        if act == menutext.ACT_GROUP:
            rec = self._browse_id('edu.tg.assist.chat', args[0] if args else '')
            if not rec:
                return self._send(chat_id, '这个群不在登记表里了，请重新点「📢 发通知到群」。', kb_back)
            person.sudo().write({'ui_state': 'notify', 'ui_target': str(rec.id),
                                 'ui_draft': ''})
            return self._send(
                chat_id,
                '好，接下来把要发到「%s」的内容发给我（就发一条文字）。' % (rec.alias or rec.title) +
                chr(10) + '我先给你看一遍预览，你点「' + menutext.CONFIRM_LABEL + '」才真的发出去。',
                menutext.inline([[(menutext.CANCEL_LABEL, menutext.ACT_CANCEL)], menutext.back_row()]))
        if act == menutext.ACT_DM:
            text, markup = self._pick_person(person)
            return self._send(chat_id, text, markup)
        if act == menutext.ACT_TARGET:
            rec = self._browse_id('edu.tg.assist.person', args[0] if args else '')
            if not rec or not rec.chat_id:
                return self._send(chat_id, '这个人现在没有可用的私聊会话，请重新点「✉️ 私发给某人」。', kb_back)
            person.sudo().write({'ui_state': 'dm', 'ui_target': str(rec.id), 'ui_draft': ''})
            return self._send(
                chat_id,
                '好，接下来把要私发给 %s（%s）的内容发给我（就发一条文字）。'
                % (rec.name, ROLE_LABELS.get(rec.role, rec.role)) +
                chr(10) + '我先给你看一遍预览，你点「' + menutext.CONFIRM_LABEL + '」才真的发出去。',
                menutext.inline([[(menutext.CANCEL_LABEL, menutext.ACT_CANCEL)], menutext.back_row()]))
        _logger.info('edu_tg_assist: 认不出的菜单动作 %r', act)
        return self._send(chat_id, self.home_text(person), kb_back)

    @api.model
    def _open_template(self, person, args, chat_id):
        tpl = self._browse_id('edu.tg.assist.template', args[0] if args else '')
        if not tpl:
            return self._send(chat_id, '这条模板找不到了，请重新点「📄 文案模板」。',
                              menutext.reply_keyboard(self._role(person)))
        res = self._render(tpl, person)
        tail = []
        if res['truncated']:
            tail.append('⚠ 超过 Telegram 单条上限，已截断。')
        if res['missing']:
            tail.append('⚠ 这些占位符没值（原样显示）：' + ' '.join('{%s}' % k for k in res['missing']))
        if res['unknown']:
            tail.append('⚠ 这些占位符不认识（原样显示）：' + ' '.join('{%s}' % k for k in res['unknown']))
        text = '（模板：%s）' % tpl.name + chr(10) + chr(10) + res['text']
        if tail:
            text += chr(10) + chr(10) + chr(10).join(tail)
        rows = [[('📢 发到群…', (menutext.ACT_TPL_GROUP, tpl.id))], menutext.back_row()]
        return self._send(chat_id, text, menutext.inline(rows))

    @api.model
    def _render(self, tpl, person):
        today = fields.Date.context_today(tpl)
        return tpl.render({
            'name': (person.name if person else None),
            'date': fields.Date.to_string(today),
            'weekday': WEEKDAYS_CN[today.weekday()],
            'group': None,
        })

    @api.model
    def _send_template_to_group(self, person, args):
        """args = [模板id, 群记录id]。"""
        tpl = self._browse_id('edu.tg.assist.template', args[0] if args else '')
        rec = self._browse_id('edu.tg.assist.chat', args[1] if len(args) > 1 else '')
        kb = menutext.reply_keyboard(self._role(person))
        if not tpl or not rec or not rec.chat_id:
            return ('模板或群找不到了，请重新点「📄 文案模板」。', kb)
        res = self._render(tpl, person)
        ok, err, out = self.env['edu.tg.assist.api'].sudo().send_message_full(
            rec.chat_id, res['text'], kind='notify')
        if not ok:
            _logger.warning('edu_tg_assist: 菜单发模板失败（群 id=%s）', rec.id)
            return ('发送失败：%s' % (err or '未知原因'), kb)
        mid = (out or {}).get('message_id')
        return ('✅ 已把模板「%s」发到「%s」。（消息 id：%s）'
                % (tpl.name, rec.alias or rec.title or '', mid or '—'), kb)

    # ------------------------------------------------------------------
    # 确认发送
    # ------------------------------------------------------------------
    @api.model
    def _do_send(self, person):
        """把 ui_draft 真发出去。调用方负责把状态清掉。"""
        kb = menutext.reply_keyboard(self._role(person))
        if not person or not person.ui_state:
            return ('没有待发送的内容了（可能已经发过或已取消）。' + chr(10) +
                    '点「📢 发通知到群」或「✉️ 私发给某人」重新开始。', kb)
        kind, target, body = person.ui_state, (person.ui_target or ''), (person.ui_draft or '')
        self._clear_state(person)
        if not body.strip():
            return ('待发送的内容是空的，请重新来一遍。', kb)
        api_model = self.env['edu.tg.assist.api'].sudo()
        if kind == 'notify':
            rec = self._browse_id('edu.tg.assist.chat', target)
            if not rec or not rec.chat_id:
                return ('这个群不在登记表里了，请重新点「📢 发通知到群」。', kb)
            ok, err, out = api_model.send_message_full(rec.chat_id, body, kind='notify')
            if not ok:
                _logger.warning('edu_tg_assist: 菜单广播失败（群 id=%s）', rec.id)
                return ('广播失败：%s' % (err or '未知原因'), kb)
            mid = (out or {}).get('message_id')
            return ('✅ 已广播到「%s」。（消息 id：%s）'
                    % (rec.alias or rec.title or '', mid or '—'), kb)
        if kind == 'dm':
            rec = self._browse_id('edu.tg.assist.person', target)
            if not rec or not rec.chat_id:
                return ('这个人现在没有可用的私聊会话，请重新点「✉️ 私发给某人」。', kb)
            ok, err = api_model.send_message(rec.chat_id, body, kind='dm')
            # 与 /dm 同口径：成功失败都留一行审计（谁、什么时候、想把什么发给谁）。
            self.env['edu.tg.assist.dm'].sudo()._audit(
                person, rec.name, '菜单私发', state='sent' if ok else 'failed',
                person_id=rec.id, target_chat_id=rec.chat_id, text=body,
                error='' if ok else err)
            if not ok:
                return ('发给 %s 失败：%s' % (rec.name, err or '未知原因'), kb)
            return ('✅ 已私发给 %s（%s）。' % (rec.name, ROLE_LABELS.get(rec.role, rec.role)), kb)
        return ('没有待发送的内容了。', kb)

    # ------------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------------
    @api.model
    def _is_admin(self, person):
        return bool(person) and person.role == 'admin'

    @api.model
    def _require_admin(self, person, act):
        if self._is_admin(person):
            return True
        self._audit_denied(person, act)
        return False

    @api.model
    def _audit_denied(self, person, act):
        """越权留痕：与 /dm、/notify 共用同一张审计表（state=denied）。**永不抛异常**。"""
        try:
            self.env['edu.tg.assist.dm'].sudo()._audit(
                person, '', '菜单:' + (act or ''), state='denied',
                error='无权限（需要 admin）：按钮菜单')
        except Exception as exc:  # noqa: BLE001
            _logger.warning('edu_tg_assist: 写菜单越权留痕失败：%s', type(exc).__name__)

    @api.model
    def _clear_state(self, person):
        if not person:
            return
        if person.ui_state or person.ui_target or person.ui_draft:
            person.sudo().write({'ui_state': False, 'ui_target': '', 'ui_draft': ''})

    @api.model
    def _answer(self, cq_id, text='好的'):
        """回一个 toast（**必须**答，不答客户端一直转圈）。"""
        if not cq_id:
            return
        ok, err = self.env['edu.tg.assist.api'].sudo().call(
            'answerCallbackQuery', {'callback_query_id': cq_id, 'text': text})
        if not ok:
            _logger.warning('edu_tg_assist: answerCallbackQuery 失败：%s', err)

    @api.model
    def _send(self, chat_id, text, markup=None, kind='menu'):
        if not chat_id:
            _logger.warning('edu_tg_assist: 菜单回话没有 chat_id，已跳过')
            return False
        ok, err = self.env['edu.tg.assist.api'].sudo().send_message(
            chat_id, text, reply_markup=markup, kind=kind)
        if not ok:
            _logger.warning('edu_tg_assist: 菜单回话失败：%s', err)
        return bool(ok)
