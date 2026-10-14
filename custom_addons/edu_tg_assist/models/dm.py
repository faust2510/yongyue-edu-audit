# -*- coding: utf-8 -*-
"""F2 一对一私发（/dm）—— 设计文档 §3 F2 的落地。

指令：
    /dm 张经理 请确认本月的行政管理表

⭐ 安全口径（队长 2026-10-08 定，三条都不是可选项）：
  1. **只在私聊里能用**：/dm 注册在 _tg_assist_commands（私聊指令表）里。
     群里发 /dm 走的是 _tg_assist_group_commands 的未知分支 ⇒ **静默**
     （bot.py:166-168「不是我的群指令就什么也不做」），群里不会因此刷屏。
  2. **只有 role == 'admin' 的人能用**：其他人回「你没有这个权限」，
     并且**写一条 state=denied 的审计行**（谁在什么时候试过，要查得到）。
  3. **找人不唯一必须问，不许猜**：person.find_by_name 返回多条时列出候选、
     要求写全名；**绝不「取第一条」**（取错人 = 把行政公文发给不相干的人）。

⚠ 硬边界（设计文档 §2）：本文件不读写 edu.feedback.* / edu_telegram*，
   本模块的 chat_id 与匿名意见箱的指纹**永不 join、永不并排导出**（B1–B5）。
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

USAGE = '用法：/dm 张经理 请确认本月的行政管理表'
NO_PERM = '你没有这个权限。'


class EduTgAssistDm(models.Model):
    """一对一私发的**审计记录**：一条指令一行，成功失败都留痕。

    刻意与 edu.tg.assist.send_log 分工：send_log 记「这条消息出网成没成」（api.py 自己写，
    全模块共用）；本表记「谁以什么身份、想把什么发给谁、最后判成了哪一类」。
    权限被拒、重名、找不到人这三种**没有出网**的情况只会出现在本表。
    """

    _name = 'edu.tg.assist.dm'
    _description = 'Telegram 一对一私发记录'
    _order = 'create_date desc, id desc'

    # ---- 发起人（登记过的人；没登记过也要能留痕，所以是普通 Char 而不是强制 m2o）----
    sender_name = fields.Char('发起人', help='发起人在 edu.tg.assist.person 里登记的姓名（没登记则为空）。')
    sender_tg_user_id = fields.Char('发起人 tg_user_id', index=True)
    sender_role = fields.Char('发起时角色', help='留痕用：被判「无权限」时这张单子就是证据。')

    # ---- 收件人 ----
    raw = fields.Char('原始指令', help='去掉「/dm」之后的原文，原样留痕（重名/找不到人时尤其有用）。')
    target_name = fields.Char('收件人（指令里写的）')
    person_id = fields.Many2one('edu.tg.assist.person', string='收件人（匹配到的人）',
                                ondelete='set null', index=True)
    target_chat_id = fields.Char('收件 chat_id', help='真正发往的私聊 chat_id。')
    text = fields.Text('内容', help='真正发出去（或本该发出去）的正文。')

    # ---- 结果 ----
    state = fields.Selection([
        ('sent', '已发出'),
        ('failed', '发送失败'),
        ('denied', '无权限（已拒绝）'),
        ('ambiguous', '重名（要求写全名）'),
        ('not_found', '没找到这个人'),
        ('no_chat', '对方没登记私聊'),
    ], string='结果', required=True, default='sent', index=True)
    error = fields.Char('说明', help='失败原因 / 拒绝理由 / 候选名单。')

    # ------------------------------------------------------------------
    # 指令注册（bot.py 自动发现：模型名以 edu.tg.assist. 开头 + 实现了本方法）
    # ------------------------------------------------------------------
    @api.model
    def _tg_assist_commands(self):
        """注册成**私聊**指令（表里没有 /dm ⇒ 群里那套永远不会执行到本方法）。"""
        return {'/dm': '_cmd_dm'}

    @api.model
    def _cmd_dm(self, person, rest, msg, chat):
        """私聊指令契约（bot.py:12）：(person, rest, msg, chat) -> (reply_text, markup) 或 None。

        bot 会把返回的文本替我发回去（kind=private_cmd），所以这里**不要**自己再发一条，
        否则用户会收到两条；真正的私发（发给收件人）才用 api.send_message。
        """
        if not person or person.role != 'admin':
            self._audit(person, '', rest, state='denied',
                        error='发起人角色=%s（需要 admin）' % (person.role if person else '未登记'))
            _logger.info('edu_tg_assist: /dm 被拒绝（发起人 tg=%s）',
                         (person.tg_user_id if person else 'unknown'))
            return (NO_PERM, None)

        target_name, _, body = (rest or '').strip().partition(' ')
        target_name, body = target_name.strip(), body.strip()
        if not target_name or not body:
            return (USAGE, None)

        Person = self.env['edu.tg.assist.person']
        matches = Person.find_by_name(target_name)
        if len(matches) > 1:
            candidates = '/'.join(matches.mapped('name'))
            self._audit(person, target_name, rest, state='ambiguous',
                        error='重名：%s' % candidates)
            return ('找到多个：%s，请写全名。' % candidates, None)
        if not matches:
            self._audit(person, target_name, rest, state='not_found',
                        error='没有登记过这个名字')
            return ('没找到「%s」。' % target_name +
                    '（一对一私发只能发给跟机器人说过话的人：' +
                    '请让对方私聊本机器人发 /start，再回 /name 真名。）', None)

        target = matches[0]
        if not target.chat_id:
            self._audit(person, target_name, rest, state='no_chat', person_id=target.id,
                        error='对方没登记私聊 chat_id')
            return ('%s 没有可用的私聊会话（请让对方先私聊机器人一次）。' % target.name, None)

        ok, err = self.env['edu.tg.assist.api'].sudo().send_message(
            target.chat_id, body, kind='dm')
        self._audit(person, target_name, rest, state='sent' if ok else 'failed',
                    person_id=target.id, target_chat_id=target.chat_id,
                    text=body, error='' if ok else err)
        if ok:
            # C4：回执带上角色与昵称 —— 同名/相似名很多时，发起人一眼能核对发给了谁
            role = dict(target._fields['role'].selection).get(target.role) or target.role
            return ('已私发给 %s（角色：%s／Telegram：%s）。'
                    % (target.name, role, target.tg_name or '—'), None)
        return ('发给 %s 失败：%s' % (target.name, err or '未知原因'), None)

    # ------------------------------------------------------------------
    # 内部：写审计行
    # ------------------------------------------------------------------
    @api.model
    def _audit(self, person, target_name, raw, state, person_id=False,
               target_chat_id='', text='', error=''):
        """写一条留痕。**永不抛异常**（审计写不进去也不能反过来把指令打挂）。"""
        try:
            self.sudo().create({
                'sender_name': (person.name if person else '') or '',
                'sender_tg_user_id': (person.tg_user_id if person else '') or '',
                'sender_role': (person.role if person else '') or '',
                'raw': (raw or '')[:255],
                'target_name': (target_name or '')[:255],
                'person_id': person_id or False,
                'target_chat_id': target_chat_id or '',
                'text': text or '',
                'state': state,
                'error': (error or '')[:255],
            })
        except Exception as exc:  # noqa: BLE001
            _logger.warning('edu_tg_assist: 写私发审计行失败：%s', type(exc).__name__)