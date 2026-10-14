# -*- coding: utf-8 -*-
"""身份绑定码 —— 老师/宿舍长自己点一次就完成「姓名 + 角色」绑定（2026-10-12 用户裁定）。

为什么需要（用户原话：「我比如说那个老师使用，她最好可以绑定身份不是吗」）：
在此之前，一位老师要被班务机器人「认出来」要三步 ——
  ① 私聊发 /assist 或 /name 真名（登记进 edu.tg.assist.person，role 默认 other）
  ② 管理员在后台把人标成 行政/教师/宿舍长
  ③ 标注之后，他发任何消息才会被前门判给班务助手（判据见 edu_tg_gate/routing.py）
第 ② 步是人工瓶颈：老师自己不点，管理员就得替他点。绑定码把这步交回本人 ——
管理员发一张码，老师点一下（或发 /bind 码），姓名与角色一次绑定。

两种入口（同一份实现）：
  · 深链：https://t.me/sctrs_bot?start=BIND-XXXXXX —— Telegram 只把 `?start=<载荷>` 塞进
    `/start <载荷>`，所以前门必须能认出「载荷是我们签发的格式」（edu_tg_gate/routing.py
    的 bind_payload 判据，格式的唯一来源是本文件的 PAYLOAD_RE）；
  · 手输：/bind BIND-XXXXXX。

⚠ 硬边界（设计文档 §9.12.5 B13）：本文件**不改**前门判据、不碰学生领码流。
   它只做一件事 —— 把一张码上的「姓名 + 角色」写进 edu.tg.assist.person。
⚠ 本文件不读写 edu.feedback.* / edu_telegram*（B1–B5）。
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

# 纯函数部分（码的形状 / 深链 / 角色词）：用**模块方式**导入 —— 本文件也有一个
# deep_link() 方法，直接 import 名字会互相遮蔽。同一份实现在
# custom_addons/edu_tg_assist/bindtext.py，前门 edu_tg_gate 通过 payload_pattern() 取。
from odoo.addons.edu_tg_assist import bindtext

_logger = logging.getLogger(__name__)

CODE_PREFIX = bindtext.CODE_PREFIX
CODE_LEN = bindtext.CODE_LEN
MAX_CODE_TRIES = bindtext.MAX_CODE_TRIES
#: 深链载荷的正则（唯一来源在 bindtext.PAYLOAD_RE）。
PAYLOAD_RE = bindtext.PAYLOAD_RE

DAYS_PARAM = 'edu_tg_assist.bind_code_days'
USERNAME_PARAM = 'edu_tg_assist.bot_username'
DEFAULT_DAYS = bindtext.DEFAULT_DAYS
DEFAULT_USERNAME = bindtext.DEFAULT_USERNAME

ROLE_WORDS = bindtext.ROLE_WORDS
ROLE_HINT = bindtext.ROLE_HINT

USAGE_BIND = bindtext.USAGE_BIND
USAGE_BINDCODE = bindtext.USAGE_BINDCODE
NO_PERM = '你没有这个权限。'
INVALID_CODE = '这个绑定码无效或已经用过了，请找管理员要一张新的。'
NO_PERSON = '我这边还没记住你，请再发一次这条指令。'


class EduTgAssistBindcode(models.Model):
    """一张一次性身份绑定码（用掉即 used，不会第二次生效）。"""

    _name = 'edu.tg.assist.bindcode'
    _description = 'Telegram 身份绑定码'
    _order = 'create_date desc, id desc'

    code = fields.Char('绑定码', required=True, index=True,
                       help='形如 BIND-XXXXXX；留空由系统自动生成。')
    name = fields.Char('姓名', required=True,
                       help='绑定后写进 person.name 的真名（一对一私发要靠它找人）。')
    role = fields.Selection([
        ('admin', '行政'),
        ('teacher', '教师'),
        ('dorm_head', '宿舍长'),
        ('student', '学生'),
        ('other', '其他'),
    ], string='角色', required=True, default='teacher',
        help='绑定后写进 person.role —— 只有 行政/教师/宿舍长 会被前门判给班务助手。')
    state = fields.Selection([
        ('new', '未使用'),
        ('used', '已使用'),
        ('void', '已作废'),
    ], string='状态', required=True, default='new', index=True)
    person_id = fields.Many2one('edu.tg.assist.person', string='绑定到的人',
                                ondelete='set null', readonly=True)
    expire_at = fields.Datetime('有效期至', help='留空 = 永不过期。')
    used_at = fields.Datetime('使用时间', readonly=True)
    note = fields.Char('备注')
    active = fields.Boolean('启用', default=True)
    link = fields.Char('绑定链接', compute='_compute_link',
                       help='发给对方（点开即自动绑定）。随机器人用户名参数变化，不落库。')

    def _compute_link(self):
        for rec in self:
            rec.link = rec.deep_link() if rec.code else ''

    _code_uniq = models.Constraint(
        'unique(code)', '绑定码不能重复（这是学生邀请码之外的另一套码，不要混用）。')

    # ------------------------------------------------------------------
    # 生成
    # ------------------------------------------------------------------
    @api.model
    def _random_code(self):
        return bindtext.random_code()

    @api.model
    def _default_days(self):
        """有效期天数：参数 edu_tg_assist.bind_code_days，默认 14；<=0 = 永不过期。"""
        raw = (self.env['ir.config_parameter'].sudo().get_param(DAYS_PARAM, '') or '').strip()
        try:
            days = int(raw) if raw else DEFAULT_DAYS
        except (TypeError, ValueError):
            days = DEFAULT_DAYS
        return days

    @api.model_create_multi
    def create(self, vals_list):
        """后台手工新建时**自动补码与有效期** —— 管理员只需填姓名与角色。

        码的重复由数据库唯一约束兜底（并发窗口极小）；这里先查一次是为了
        不把「码已存在」这种必然失败抛给用户看。
        """
        days = self._default_days()
        expire = fields.Datetime.now() + timedelta(days=days) if days > 0 else False
        for vals in vals_list:
            if not (vals.get('code') or '').strip():
                for _try in range(MAX_CODE_TRIES):
                    code = self._random_code()
                    if not self.sudo().search_count([('code', '=', code)]):
                        vals['code'] = code
                        break
                else:                       # 8 次都撞上（32^6 空间，等于不可能）
                    raise ValueError('绑定码生成失败，请重试')
            if not vals.get('expire_at') and expire:
                vals['expire_at'] = expire
        return super().create(vals_list)

    @api.model
    def generate(self, name, role, days=None):
        """生成一张码（/bindcode 与后台按钮共用这一条路）。"""
        if days is None:
            days = self._default_days()
        expire = fields.Datetime.now() + timedelta(days=days) if days > 0 else False
        return self.sudo().create({'name': name, 'role': role, 'expire_at': expire})

    # ------------------------------------------------------------------
    # 给前门用的格式（唯一来源）
    # ------------------------------------------------------------------
    @api.model
    def payload_pattern(self):
        """深链载荷的正则（edu_tg_gate 在运行时取它，不另写一份）。"""
        return PAYLOAD_RE

    @api.model
    def bot_username(self):
        """拼深链用的机器人用户名（参数 edu_tg_assist.bot_username，默认 sctrs_bot）。"""
        raw = (self.env['ir.config_parameter'].sudo().get_param(USERNAME_PARAM, '') or '').strip()
        return (raw or DEFAULT_USERNAME).lstrip('@')

    def deep_link(self):
        self.ensure_one()
        return bindtext.deep_link(self.bot_username(), self.code)

    def _state_label(self):
        return dict(self._fields['state'].selection).get(self.state) or self.state

    def _usable(self):
        """这张码现在还能不能用（过期 / 已用 / 作废 / 停用 都不能）。"""
        self.ensure_one()
        if not self.active or self.state != 'new':
            return False
        if self.expire_at and self.expire_at < fields.Datetime.now():
            return False
        return True

    def redeem(self, code, person, chat_id=None):
        """兑现一张码：把码上的姓名 + 角色写进 person。

        :return: (ok: bool, text: str) —— text 是给用户看的中文回话。
        绝不抛异常（机器人任何一条路径都不能因为一张坏码 500）。
        """
        want = (code or '').strip().upper()
        if not want:
            return False, USAGE_BIND
        if not person:
            return False, NO_PERSON
        rec = self.sudo().search([('code', '=', want)], limit=1)
        if not rec or not rec._usable():
            _logger.info('edu_tg_assist: 绑定码不可用（tg=%s）', person.tg_user_id or '?')
            return False, INVALID_CODE
        vals = {'role': rec.role}
        if rec.name:
            vals['name'] = rec.name
        # /stop 过的人（active=False、chat_id 被清空）：绑定即视为本人明确要恢复
        if not person.active:
            vals['active'] = True
        cid = str(chat_id or '') or person.chat_id
        if cid:
            vals['chat_id'] = cid
        person.sudo().write(vals)
        rec.sudo().write({
            'state': 'used',
            'person_id': person.id,
            'used_at': fields.Datetime.now(),
        })
        role_label = dict(rec._fields['role'].selection).get(rec.role) or rec.role
        _logger.info('edu_tg_assist: 绑定码已兑现（bindcode=%s person=%s role=%s）',
                     rec.id, person.id, rec.role)
        return True, ('已绑定：%s（%s）。' % (person.name or rec.name, role_label) + chr(10) +
                      '现在你在这里发任何消息都会进班务助手，不用再记指令。')

    # ------------------------------------------------------------------
    # 指令注册（bot.py 自动发现）
    # ------------------------------------------------------------------
    @api.model
    def _tg_assist_commands(self):
        return {'/bind': '_cmd_bind', '/bindcode': '_cmd_bindcode'}

    @api.model
    def _cmd_bind(self, person, rest, msg, chat):
        """任何人可用：用一张码把自己绑成「姓名 + 角色」。

        只取第一段当码：老师常把码和别的话一起发（`/bind BIND-ABC123 谢谢`），
        整串拿去查库会回「无效或已用过」，看着像码坏了（见 bindtext.first_code_token）。
        """
        code = bindtext.first_code_token(rest)
        ok, text = self.sudo().redeem(code, person, chat_id=(chat or {}).get('id'))
        if ok:
            return (text, None)
        if code:
            return (text, None)
        return (USAGE_BIND, None)

    @api.model
    def _cmd_bindcode(self, person, rest, msg, chat):
        """仅管理员：生成一张码并把深链给他（发给对方即可）。"""
        if not person or person.role != 'admin':
            self.env['edu.tg.assist.dm'].sudo()._audit(
                person, '', rest, state='denied',
                error='发起人角色=%s（需要 admin）' % (person.role if person else '未登记'))
            return (NO_PERM, None)
        role, name = bindtext.split_role_and_name(rest)
        if not role:
            parts = (rest or '').split()
            if parts and parts[0] not in ROLE_WORDS:
                return ('认不出角色「%s」。%s' % (parts[0], ROLE_HINT), None)
            return (USAGE_BINDCODE, None)
        rec = self.sudo().generate(name, role)
        if not rec:
            return ('生成绑定码失败，请稍后重试或到后台「绑定码」页新建。', None)
        days = self._default_days()
        valid = ('有效期 %s 天' % days) if days > 0 else '长期有效'
        return (chr(10).join([
            '绑定码：%s' % rec.code,
            '姓名：%s' % rec.name,
            '角色：%s' % (dict(rec._fields['role'].selection).get(rec.role) or rec.role),
            valid,
            '',
            '把这条链接发给他/她（点开就自动绑定）：',
            rec.deep_link(),
            '打不开就让他私聊机器人发：/bind %s' % rec.code,
        ]), None)
