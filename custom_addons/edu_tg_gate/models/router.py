# -*- coding: utf-8 -*-
"""前门分发模型 —— 把判据（routing.decide）接到两个模块的**公开 API** 上。

为什么是独立模块 edu_tg_gate，而不是把这段塞进 edu_tg_bind：
  · bind 的文档化身份是「职责单一只发码、且只处理私聊」（tg-invite-bot-design.md §1），
    塞分发器会让它自我矛盾；
  · 前门是**这个 bot**（@sctrs_bot）的设施，不是领码模块的功能；
  · 用户 2026-10-08 的裁定（复用 SCRTS）本身就要求「一个网址分发给两个模块」，
    交接提示词 §三 也写明要「先写前门」。

依赖方向：edu_tg_gate → edu_tg_bind（manifest depends）。
edu_tg_assist 走**运行时注册表检查**，不写进 depends：
assist 没装 / 被卸时，前门必须继续把私聊送到领码流（学生流优先级最高）。

本模块不落任何表、不留 chat_id（边界 B8）：chat_id 只在 bind / assist 各自的表里。
"""
import logging

from odoo import api, models

from odoo.addons.edu_tg_gate.routing import (
    DEFAULT_BIND_PAYLOAD_RE,
    ROUTE_ASSIST,
    ROUTE_BIND,
    STAFF_ROLES,
    decide,
)

_logger = logging.getLogger(__name__)

ASSIST_BOT = 'edu.tg.assist.bot'
ASSIST_PERSON = 'edu.tg.assist.person'
BIND_CLAIM = 'edu.tg.claim'


class EduTgGateRouter(models.AbstractModel):
    _name = 'edu.tg.gate.router'
    _description = 'Telegram 前门分发（一个 webhook → 领码 / 班务）'

    @api.model
    def _assist_ready(self):
        """班务模块是否已装载。用注册表判断，不用 depends。"""
        return self.env.get(ASSIST_BOT) is not None

    @api.model
    def _staff_chat_ids(self):
        """role ∈ STAFF_ROLES 的私聊 chat_id（含 tg_user_id，两者都匹配更稳）。

        active_test=False（2026-10-10 加）：/stop 停用过的人被 Odoo 归档，若这里按
        active 过滤，他之后发的 /start 会被判成学生流、直接领邀请码 —— 再也回不到
        班务助手。归档只该管「我不发给他」，不该管「他的消息进哪个模块」。
        """
        Person = self.env.get(ASSIST_PERSON)
        if Person is None:
            return frozenset()
        rows = Person.sudo().with_context(active_test=False).search_read(
            [('role', 'in', list(STAFF_ROLES))],
            ['chat_id', 'tg_user_id'])
        ids = set()
        for row in rows:
            for key in ('chat_id', 'tg_user_id'):
                if row.get(key):
                    ids.add(str(row[key]))
        return frozenset(ids)

    @api.model
    def _menu_chat_ids(self):
        """正在走按钮流程的人（person.ui_state 有值）的 chat_id / tg_user_id。

        为什么需要：角色字段要管理员标了才是 admin/teacher，而按钮在他发 /assist 的
        那一刻就已经给他了。没有这条，他点完按钮发来的正文会被判成学生流、回一张邀请码。
        active_test=False 与 _staff_chat_ids 同口径：/stop 归档只该管「我不发给他」，
        不该管「他的消息进哪个模块」。assist 没装 / 老版本没这两个字段 ⇒ 返回空集，
        前门退回旧判据。
        """
        Person = self.env.get(ASSIST_PERSON)
        if Person is None or 'ui_state' not in Person._fields:
            return frozenset()
        rows = Person.sudo().with_context(active_test=False).search_read(
            [('ui_state', '!=', False)], ['chat_id', 'tg_user_id'])
        ids = set()
        for row in rows:
            for key in ('chat_id', 'tg_user_id'):
                if row.get(key):
                    ids.add(str(row[key]))
        return frozenset(ids)

    @api.model
    def _button_texts(self):
        """底部键盘按钮的文案 —— 唯一来源 edu_tg_assist.menutext.BUTTON_ACTIONS。

        取不到（assist 没装 / 老版本没有这个文件）⇒ 空集，前门退回旧判据：
        学生的 /start、/help、任意自由文本一字不变。
        """
        try:
            from odoo.addons.edu_tg_assist import menutext
        except Exception:  # noqa: BLE001
            return frozenset()
        return frozenset(menutext.BUTTON_ACTIONS)

    @api.model
    def _bind_payload_re(self):
        """深链载荷正则 —— 从 edu.tg.assist.bindcode 取（**唯一来源**，不在这里再写一份）。

        取不到（assist 没装 / 老版本没有这个方法）时用 routing 里的兜底常量：
        只影响「老师的 /start 深链归谁」，学生的 /start 永远无载荷、永远走领码流。
        """
        m = self.env.get('edu.tg.assist.bindcode')
        if m is not None:
            try:
                pattern = m.payload_pattern()
                if pattern:
                    return pattern
            except Exception as exc:  # noqa: BLE001
                _logger.warning('edu_tg_gate: 取绑定码载荷正则失败（%s）', type(exc).__name__)
        return DEFAULT_BIND_PAYLOAD_RE

    @api.model
    def route(self, update):
        """这条 update 归谁：'assist' / 'bind' / 'ignore'（判据全在 routing.decide）。"""
        return decide(update, assist_ready=self._assist_ready(),
                      staff_chat_ids=self._staff_chat_ids(),
                      bind_payload_re=self._bind_payload_re(),
                      menu_chat_ids=self._menu_chat_ids(),
                      button_texts=self._button_texts())

    @api.model
    def dispatch(self, update):
        """按 route() 把 update 交给对应模块的公开 API，返回可直接当 webhook 响应的 dict。

        两侧都用**已有**的公开入口，本模块不复制任何业务逻辑：
          · assist —— edu.tg.assist.bot.handle_update(update)（不抛异常）
          · bind   —— edu.tg.claim.handle_private_message(message)（领码流唯一实现）
        """
        target = self.route(update)
        if target == ROUTE_ASSIST:
            # route 只用于去重表留痕（B3）：同一条 update 从哪个口进来的，排障时一眼看到。
            return self.env[ASSIST_BOT].sudo().handle_update(update, route='gate')
        if target == ROUTE_BIND:
            message = update.get('message') or {}
            return self.env[BIND_CLAIM].sudo().handle_private_message(message)
        return {'ok': True, 'ignored': 'gate_ignore'}
