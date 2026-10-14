# -*- coding: utf-8 -*-
"""Telegram Mini App（网页版面板）—— 设计文档 §9.17。

用户 2026-10-13 问「d Telegram 里的网页版 Mini App（最贵，需要 initData 鉴权 + 前端工程）。
能做吗」。结论：能做，且**不新建模块、不碰任何边界**——两条路由挂在 edu_tg_assist 里，
复用本模块已有的 chat / person / material / forward / api。

两条路由（路径用模块级常量、与 webhook.py 同形，不占任何别人的路由）：
    GET  /edu_tg_assist/app      面板页面（auth='public'：Telegram 的 WebView 里没有 Odoo 会话）
    POST /edu_tg_assist/app/api  JSON 接口（auth='public' + csrf=False）

身份怎么认：Telegram 客户端打开页面时会给每一条 initData（含 user.id 与 hash），
面板把它原样回传，服务端用**官方算法**校验签名（edu_tg_assist/miniapp_auth.py，
官方文档一手复核见该文件头）=> 校验通过才认「你是那个人」，再按 tg_user_id 找
edu.tg.assist.person。**没有签名 = 一律 403**，页面本身公开无所谓（它只有壳，没有数据）。

权限口径与指令流一致：面板动作先按 person.role 判；管理动作（发通知/私发/人员名单/定时群发）
只有 role == 'admin' 能调，越权照样写一条 state=denied 留痕（与 /notify、/dm 同口径）。

边界（B1/B2/B5 不变）：只用本模块的表与参数；不碰 edu_telegram.* / edu.feedback.* /
edu.tg.claim；token 与 init_data 原文都不写日志（校验失败只记短码 reason）。
"""
import logging

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.edu_tg_assist import miniapp_auth

_logger = logging.getLogger(__name__)

APP_PATH = '/edu_tg_assist/app'
API_PATH = '/edu_tg_assist/app/api'
BOT_USERNAME_PARAM = 'edu_tg_assist.bot_username'
DEFAULT_BOT_USERNAME = 'sctrs_bot'

STAFF_ROLES = ('admin', 'teacher', 'dorm_head')
ROLE_LABELS = {
    'admin': '行政', 'teacher': '教师', 'dorm_head': '宿舍长',
    'student': '学生', 'other': '其他',
}
#: 只有 admin 能调的面板动作（与 /notify、/dm 同口径）。
#: 定时群发（reminder_*）整族也是管理动作：只有行政能设定时发到哪个群。
ADMIN_ACTIONS = ('notify', 'dm', 'staff',
                 'reminders', 'reminder_create', 'reminder_toggle',
                 'reminder_run', 'reminder_delete')
#: 教职工（行政/教师/宿舍长）才能调的面板动作 —— 材料归档与对外转发，
#: 学生身份的人即使混进面板也看不到别人的材料。
STAFF_ACTIONS = ('materials', 'forward')
ACTIONS = ('whoami', 'help', 'groups', 'staff', 'materials', 'notify', 'dm', 'forward',
           'reminders', 'reminder_create', 'reminder_toggle', 'reminder_run', 'reminder_delete')
MAX_TEXT = 3500
MAX_ROWS = 50
NO_PERM = '你没有这个权限。'
NOT_REGISTERED = '这个 Telegram 账号还没在班务助手里登记。请私聊机器人发一句 /assist 或 /name 你的真名。'
BAD_IDENTITY = '身份校验没通过。请回到机器人对话，点底部的「🖥 打开面板」重新进来。'


class EduTgAssistMiniApp(http.Controller):

    # ------------------------------------------------------------------
    # 页面（只有壳；任何数据都要走 API 并验签）
    # ------------------------------------------------------------------
    @http.route(APP_PATH, type='http', auth='public', csrf=False,
                methods=['GET'], save_session=False)
    def miniapp_page(self, **kw):
        params = request.env['ir.config_parameter'].sudo()
        bot_username = (params.get_param(BOT_USERNAME_PARAM, '') or '').strip() or DEFAULT_BOT_USERNAME
        site_url = request.env['edu.tg.assist.bot'].sudo()._site_url()
        return request.render('edu_tg_assist.miniapp_page', {
            'api_path': API_PATH,
            'bot_username': bot_username,
            'site_url': site_url,
        })

    # ------------------------------------------------------------------
    # JSON 接口
    # ------------------------------------------------------------------
    @http.route(API_PATH, type='http', auth='public', csrf=False,
                methods=['POST'], save_session=False)
    def miniapp_api(self, **kw):
        payload = request.httprequest.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return self._fail('bad_request', '请求格式不对。', 400)
        env = request.env
        token = env['edu.tg.assist.api'].sudo()._token()
        ok, reason = miniapp_auth.check(payload.get('init_data') or '', token)
        if not ok:
            _logger.warning('edu_tg_assist: Mini App 身份校验未通过（%s）', reason)
            return self._fail('unauthorized', BAD_IDENTITY, 403, reason=reason)

        fields = miniapp_auth.parse_init_data(payload.get('init_data') or '')
        user = miniapp_auth.user_of(fields)
        person = env['edu.tg.assist.person'].sudo().with_context(active_test=False).search(
            [('tg_user_id', '=', str(user.get('id')))], limit=1)
        if not person or not person.active:
            return self._fail('not_registered', NOT_REGISTERED, 403)

        action = (payload.get('action') or '').strip()
        params = payload.get('params')
        if not isinstance(params, dict):
            params = {}
        if action not in ACTIONS:
            return self._fail('bad_action', '面板没有这个功能。', 400)
        if action in ADMIN_ACTIONS and person.role != 'admin':
            self._audit_denied(person, action)
            return self._fail('forbidden', NO_PERM, 403)
        if action in STAFF_ACTIONS and person.role not in STAFF_ROLES:
            self._audit_denied(person, action)
            return self._fail('forbidden', NO_PERM, 403)

        try:
            data = self._dispatch(person, action, params)
        except UserError as exc:
            return self._fail('user_error', str(exc), 200)
        except Exception as exc:  # noqa: BLE001 —— 面板任何一步都不许把异常甩给用户
            _logger.exception('edu_tg_assist: Mini App 动作 %s 失败：%s', action, type(exc).__name__)
            return self._fail('server_error', '这一步没做成，请重新点一次。', 200)
        return request.make_json_response({'ok': True, 'data': data})

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------
    def _dispatch(self, person, action, params):
        handler = getattr(self, '_act_' + action)
        return handler(person, params)

    def _act_whoami(self, person, params):
        return {
            'name': person.name or '',
            'tg_name': person.tg_name or '',
            'role': person.role or 'other',
            'role_label': ROLE_LABELS.get(person.role, '其他'),
            'is_admin': person.role == 'admin',
        }

    def _act_help(self, person, params):
        return {'text': request.env['edu.tg.assist.bot'].sudo()._help_text(person)}

    def _act_groups(self, person, params):
        recs = request.env['edu.tg.assist.chat'].sudo().search(
            [('active', '=', True), ('chat_id', '!=', False)], limit=MAX_ROWS)
        rows = [{
            'id': rec.id,
            'label': rec.alias or rec.title or rec.chat_id,
            'alias': rec.alias or '',
            'title': rec.title or '',
        } for rec in recs]
        rows.sort(key=lambda row: (not row['alias'], row['label']))
        return {'rows': rows}

    def _act_staff(self, person, params):
        recs = request.env['edu.tg.assist.person'].sudo().search(
            [('active', '=', True), ('role', 'in', list(STAFF_ROLES)),
             ('chat_id', '!=', False)], limit=MAX_ROWS)
        return {'rows': [{
            'id': rec.id,
            'label': rec.name or rec.tg_name or rec.tg_user_id,
            'role_label': ROLE_LABELS.get(rec.role, ''),
        } for rec in recs]}

    def _act_materials(self, person, params):
        model = request.env['edu.tg.assist.material'].sudo()
        cats = dict(model._fields['category'].selection or [])
        urgs = dict(model._fields['urgency'].selection or [])
        recs = model.search([('active', '=', True)], limit=MAX_ROWS, order='create_date desc, id desc')
        return {'rows': [{
            'id': rec.id,
            'name': rec.name or '',
            'category': cats.get(rec.category, rec.category or ''),
            'urgency': urgs.get(rec.urgency, rec.urgency or ''),
            'summary': (rec.summary or '').strip()[:200],
            'file_name': rec.file_name or '',
            'has_file': bool(rec.file_id),
            'when': rec.create_date and str(rec.create_date)[:16] or '',
        } for rec in recs]}

    def _act_notify(self, person, params):
        chat = self._record('edu.tg.assist.chat', params.get('target_id'))
        text = self._text(params)
        if not chat.active or not (chat.chat_id or '').strip():
            raise UserError('这个群还没登记好（没有 chat_id），发不了。')
        api = request.env['edu.tg.assist.api'].sudo()
        ok, err, res = api.send_message_full(chat.chat_id, text, kind='notify')
        if not ok:
            raise UserError('没发出去：%s' % (err or '未知原因'))
        return {'message_id': (res or {}).get('message_id'),
                'target': chat.alias or chat.title or chat.chat_id}

    def _act_dm(self, person, params):
        target = self._record('edu.tg.assist.person', params.get('target_id'))
        text = self._text(params)
        if not target.active or not (target.chat_id or '').strip():
            raise UserError('这个人还没有和机器人说过话，Telegram 不允许机器人主动私聊他。')
        api = request.env['edu.tg.assist.api'].sudo()
        ok, err = api.send_message(target.chat_id, text, kind='dm')
        request.env['edu.tg.assist.dm'].sudo()._audit(
            person, target.name or target.tg_name or '', '面板私发',
            'sent' if ok else 'failed', person_id=target.id,
            target_chat_id=target.chat_id, text=text, error=err or '')
        if not ok:
            raise UserError('没发出去：%s' % (err or '未知原因'))
        return {'target': target.name or target.tg_name or ''}

    def _act_forward(self, person, params):
        material = self._record('edu.tg.assist.material', params.get('material_id'))
        kind = (params.get('target_kind') or 'group').strip()
        if kind not in ('group', 'person'):
            raise UserError('请选择发给群还是发给人。')
        vals = {
            'material_id': material.id,
            'target_kind': kind,
            'note': (params.get('note') or '').strip()[:200],
        }
        raw_target = params.get('target_id')
        if kind == 'group':
            vals['chat_id'] = self._record('edu.tg.assist.chat', raw_target).id
        else:
            vals['person_id'] = self._record('edu.tg.assist.person', raw_target).id
        wizard = request.env['edu.tg.assist.forward'].sudo().create(vals)
        # 复用后台那条完全相同的路径（含 caption 组装、sendDocument 走 file_id、send_log）
        result = wizard.action_send()
        return {'sent': True, 'target_kind': kind,
                'message_id': (result or {}).get('res_id') or False}

    # ---- 定时群发（F1 的面板入口，2026-10-14）------------------------------
    # 后台表单一直有「定时提醒」，但它藏在 Odoo 里、还要先建模板；用户 2026-10-13 问过
    # 「还有定时群发功能呢？」。这里把「选群 → 写正文 → 选星期几点」搬到面板，
    # 一行调度都不新造：仍然走 edu.tg.assist.reminder（每条规则自带一个 ir.cron）。
    def _act_reminders(self, person, params):
        model = request.env['edu.tg.assist.reminder'].sudo()
        recs = model.with_context(active_test=False).search(
            [], limit=MAX_ROWS, order='weekday, send_hour, send_minute, id')
        return {'rows': [{
            'id': rec.id,
            'name': rec.name or '',
            'group': (rec.target_chat_id.alias or rec.target_chat_id.title
                      or rec.target_chat_id.chat_id or ''),
            'when': rec.schedule_label or '',
            'active': bool(rec.active),
            'last_result': rec.last_result or '',
            'last_sent_at': rec.last_sent_at and str(rec.last_sent_at)[:16] or '',
        } for rec in recs]}

    def _act_reminder_create(self, person, params):
        chat = self._record('edu.tg.assist.chat', params.get('target_id'))
        rule = request.env['edu.tg.assist.reminder'].sudo().quick_create(
            chat, params.get('text'), (params.get('weekday') or '').strip(),
            self._int(params.get('hour'), '几点'), self._int(params.get('minute'), '几分'))
        return {
            'id': rule.id,
            'group': rule.target_chat_id.alias or rule.target_chat_id.title or '',
            'when': rule.schedule_label or '',
            'next': rule.cron_id and str(rule.cron_id.nextcall)[:16] or '',
        }

    def _act_reminder_toggle(self, person, params):
        rule = self._record('edu.tg.assist.reminder', params.get('id'))
        active = bool(params.get('active'))
        rule.sudo().write({'active': active})
        return {'id': rule.id, 'active': bool(rule.active)}

    def _act_reminder_run(self, person, params):
        """「立即发一次」：配好规则当场验一条（与后台那个按钮同一条 _do_send 路径）。"""
        rule = self._record('edu.tg.assist.reminder', params.get('id'))
        ok, err = rule.sudo()._do_send(kind='manual')
        if not ok:
            raise UserError('没发出去：%s' % (err or '未知原因'))
        return {'id': rule.id}

    def _act_reminder_delete(self, person, params):
        rule = self._record('edu.tg.assist.reminder', params.get('id'))
        name = rule.name or ''
        rule.sudo().unlink()   # 规则自带的 ir.cron 由 reminder.unlink() 一起删
        return {'name': name}
    # ------------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------------
    def _record(self, model, raw):
        try:
            rec_id = int(raw)
        except (TypeError, ValueError):
            raise UserError('没选目标。')
        rec = request.env[model].sudo().browse(rec_id)
        if not rec.exists():
            raise UserError('选的东西已经不在后台了，请刷新页面重来。')
        return rec

    def _text(self, params):
        text = (params.get('text') or '').strip()
        if not text:
            raise UserError('正文是空的，没发出去。')
        if len(text) > MAX_TEXT:
            raise UserError('正文太长了（超过 %d 字），请分成两条。' % MAX_TEXT)
        return text

    def _int(self, raw, label):
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise UserError('「%s」没填对。' % label)

    def _audit_denied(self, person, action):
        try:
            request.env['edu.tg.assist.dm'].sudo()._audit(
                person, '', '面板:' + action, 'denied',
                error='无权限（需要 admin）：面板动作 %s' % action)
        except Exception as exc:  # noqa: BLE001 —— 留痕失败不许影响主流程
            _logger.warning('edu_tg_assist: 写面板越权留痕失败：%s', type(exc).__name__)

    def _fail(self, code, message, status=200, reason=None):
        payload = {'ok': False, 'error': code, 'message': message}
        if reason:
            payload['reason'] = reason
        return request.make_json_response(payload, status=status)
