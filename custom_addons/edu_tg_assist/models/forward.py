# -*- coding: utf-8 -*-
"""选项 c —— 后台「一键转发材料」：在「材料归档」里点一下，把某份材料发给某人/某个群。

用户 2026-10-13 的原话：「在后台『材料归档』里点一下，把某份材料直接转给某人或某个群
（文件用 Telegram 的 file_id 转，不用重传）」。

边界（不许破）：
  · 全部在本模块内：只用本模块的 chat / person / material 与 edu.tg.assist.api 出网口，
    不碰 edu_telegram.*、edu.feedback.*、edu.tg.claim（B1/B2/B5 不变）；
  · 目标只可能是**本模块登记过**的群（有 chat_id）或**跟机器人说过话**的人（有 chat_id）：
    直接取记录里的 chat_id，不让人手抄数字，也绝不猜；
  · 文件走 file_id（sendDocument），**不重传**、不落盘；没有文件（纯文本材料）就发文本；
  · 出网只经 api.send_document / api.send_message —— 两条都会无条件记 send_log。
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

#: caption 上限按 900 收（官方 1024；留余量给「分类/紧急度/截止」那行的拼接）
CAPTION_MAX = 900


class EduTgAssistForward(models.TransientModel):
    _name = 'edu.tg.assist.forward'
    _description = '材料一键转发（后台 → 某人 / 某个群）'

    material_id = fields.Many2one(
        'edu.tg.assist.material', '材料', required=True, ondelete='cascade', index=True)
    target_kind = fields.Selection(
        [('group', '发到群里'), ('person', '私发给某人')], '发给',
        required=True, default='group')
    chat_id = fields.Many2one(
        'edu.tg.assist.chat', '群',
        help='只能选本模块登记过的群（有 chat_id 才能发）。')
    person_id = fields.Many2one(
        'edu.tg.assist.person', '收件人',
        help='只能发给跟机器人说过话的人（Telegram 平台限制：机器人不能主动私聊陌生人）。')
    note = fields.Char(
        '附言', size=200,
        help='可选。会写在文件说明（caption）最前面，例如「文熙姐，这份材料请查收」。')

    # ------------------------------------------------------------------
    # 组装
    # ------------------------------------------------------------------
    def _selection_label(self, field_name):
        """把材料上的 Selection 值翻成中文标签（沿用模型自己的 selection，不写第二份）。"""
        rec = self.material_id
        if field_name not in rec._fields:
            return ''
        label_map = dict(rec._fields[field_name].selection or [])
        raw = rec[field_name]
        return label_map.get(raw, raw or '')

    def _caption(self):
        """要发出去的正文/文件说明：附言 + 材料标题 + 分类/紧急度/截止 + 摘要。"""
        rec = self.material_id
        lines = []
        note = (self.note or '').strip()
        if note:
            lines.append(note)
        lines.append('📎 %s' % (rec.name or '（未命名材料）'))
        meta = '分类：%s ｜ 紧急度：%s' % (
            self._selection_label('category') or '—',
            self._selection_label('urgency') or '—')
        if rec.deadline:
            meta += ' ｜ 截止：%s' % rec.deadline
        lines.append(meta)
        summary = (rec.summary or '').strip()
        if summary:
            lines.append(summary)
        return '\n'.join(lines)[:CAPTION_MAX]

    def _target(self):
        """返回 (chat_id, 展示名)；选不到人/群就 UserError（宁可报错也不猜一个发出去）。"""
        if self.target_kind == 'group':
            if not self.chat_id:
                raise UserError('请先选择要发到哪个群（列表里只有本模块登记过的群）。')
            chat_id = (self.chat_id.chat_id or '').strip()
            who = '「%s」' % (self.chat_id.alias or self.chat_id.title or self.chat_id.chat_id)
            return chat_id, who
        if not self.person_id:
            raise UserError('请先选择要发给谁。')
        chat_id = (self.person_id.chat_id or '').strip()
        who = self.person_id.name or self.person_id.tg_name or self.person_id.tg_user_id
        if not chat_id:
            raise UserError('这个人还没跟机器人说过话（没有私聊会话），发不出去。')
        return chat_id, who

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------
    def action_send(self):
        """点「📤 发送」：有 file_id 走 sendDocument（不重传），否则发文本。"""
        self.ensure_one()
        rec = self.material_id
        if not rec:
            raise UserError('没有指定要转发的材料。')
        chat_id, who = self._target()
        if not chat_id:
            raise UserError('这个目标没有 Telegram 会话 id，发不出去。')

        caption = self._caption()
        api_client = self.env['edu.tg.assist.api'].sudo()
        if rec.file_id:
            ok, err = api_client.send_document(
                chat_id, rec.file_id, caption=caption, kind='material_forward')
        else:
            ok, err = api_client.send_message(
                chat_id, caption, kind='material_forward')
        if not ok:
            # 失败原因已由 api 层写进 send_log；这里把话原样回给操作的人。
            raise UserError('没发出去：%s' % (err or '未知原因（详见「发送记录」）'))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '转发材料',
                'message': '已把「%s」发给 %s。' % (rec.name or '（未命名材料）', who),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
