# -*- coding: utf-8 -*-
"""F4 内联按钮回填 —— 宿舍长点【已完成并达标 / 有异常需上报】，数据回传后台。

谁会发这条带按钮的消息？
  本轮**不**在这里造发送方：按设计文档 §3，带按钮的那条消息属于 F1「定时提醒」。
  本模型对外提供 build_keyboard(记录) 给 F1 用（它 send_message(..., reply_markup=build_keyboard(rec))），
  自己只负责**点击之后的那一半**：认领 callback_query -> 验身份 -> 落库 -> answerCallbackQuery。

callback_data 格式（Telegram 硬限 64 字节，中文会爆，所以**只用 ASCII**）：
    ck:<记录id>:<选项>       例如  ck:12:done  /  ck:12:abnormal
  · ck      = 本模块的短前缀，用来认领（不是我们的就直接让下一个模型处理）
  · 记录id  = edu.tg.assist.mention 的 id（F1 若改用别的表，把 build_keyboard 传的对象换掉即可）
  · 选项    = done / abnormal（ASCII，稳定，不随文案改）

纪律：
  · **必须**调 answerCallbackQuery：不调客户端会一直转圈（Telegram 的硬要求）。
  · 身份必须验：from.id 在 edu.tg.assist.person 里找不到 -> 回「你还没登记」，**不落库**。
  · 同一人对同一条记录重复点 -> **不重复插行**，改选项（点错了能改主意），仍然只回一次 toast。
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

CALLBACK_PREFIX = 'ck'
CALLBACK_MAX_BYTES = 64
#: 选项值与文案。值必须是 ASCII 短串（进 callback_data），文案才是给人看的。
CHOICES = (
    ('done', '已完成并达标'),
    ('abnormal', '有异常需上报'),
)


class EduTgAssistReply(models.Model):
    _name = 'edu.tg.assist.reply'
    _description = '按钮回填记录（宿舍长点按钮上报）'
    _order = 'replied_at desc, id desc'

    mention_id = fields.Many2one('edu.tg.assist.mention', string='关联待办', ondelete='set null',
                                 help='本轮按钮只挂在 @提醒待办上；'
                                      'F1 定时提醒建出 edu.tg.assist.reminder 后再加一列。')
    person_id = fields.Many2one('edu.tg.assist.person', string='上报人', ondelete='set null')
    tg_user_id = fields.Char('Telegram 用户 ID', index=True, required=True)
    tg_name = fields.Char('Telegram 昵称', help='点击时的昵称快照，便于认人。')
    choice = fields.Selection(CHOICES, string='选择', required=True)
    chat_id = fields.Char('发生按钮的 chat_id', index=True,
                          help='按钮所在消息的群/私聊 id。')
    raw_data = fields.Char('原始 callback_data', help='原样留档，便于排查格式变更。')
    replied_at = fields.Datetime('点击时间', default=fields.Datetime.now, required=True, index=True)
    note = fields.Char('备注')

    @api.model
    def _choices(self):
        return CHOICES

    @api.model
    def _label(self, value):
        return dict(CHOICES).get(value) or value

    # ------------------------------------------------------------ 给 F1 用的
    @api.model
    def build_keyboard(self, record):
        """生成带两个按钮的 inline keyboard（F1 定时提醒直接拿去当 reply_markup）。

        :param record: 有 .id 的记录（本轮是 edu.tg.assist.mention）。
        :return: 官方 InlineKeyboardMarkup 形状的 dict；**超长时返回 None 并记日志**
                 （宁可发一条没按钮的消息，也不要因为 64 字节被 Telegram 整条拒收）。
        """
        row = []
        for value, label in CHOICES:
            data = '%s:%s:%s' % (CALLBACK_PREFIX, record.id, value)
            if len(data.encode('utf-8')) > CALLBACK_MAX_BYTES:
                _logger.error('edu_tg_assist: callback_data 超过 %d 字节，按钮已放弃：%r',
                              CALLBACK_MAX_BYTES, data)
                return None
            row.append({'text': label, 'callback_data': data})
        return {'inline_keyboard': [row]}

    @api.model
    def parse_callback(self, data):
        """解析 callback_data -> (记录id, 选项)；不是本模块的或不合法 -> (None, None)。"""
        data = (data or '').strip()
        parts = data.split(':')
        if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
            return None, None
        try:
            rec_id = int(parts[1])
        except (TypeError, ValueError):
            return None, None
        if parts[2] not in dict(CHOICES):
            return None, None
        return rec_id, parts[2]

    @api.model
    def _answer(self, cq_id, text):
        """回一个 toast。**不抛异常**（call() 只回报 (ok, err)）；没有 cq_id 就跳过。"""
        if not cq_id:
            return
        ok, err = self.env['edu.tg.assist.api'].sudo().call('answerCallbackQuery', {
            'callback_query_id': cq_id,
            'text': text,
            # 不设 show_alert：toast 不打断群聊；「未登记」那种要看清的也用 toast，
            # 因为 callback 的 alert 在手机上同样是一闪而过，正文我们会另发私聊。
        })
        if not ok:
            _logger.warning('edu_tg_assist: answerCallbackQuery 失败：%s', err)

    # ------------------------------------------------------ 点击 -> 回填落库
    @api.model
    def _tg_assist_handle_callback(self, cq):
        """内联按钮挂点（bot.py 自动发现）。返回真值 = 已认领（**认领了就必须 answer**）。"""
        if not isinstance(cq, dict):
            return None
        rec_id, choice = self.parse_callback(cq.get('data'))
        if rec_id is None:
            return None  # 不是我们的按钮：不认领，交给下一个模型 / bot 兜底

        cq_id = cq.get('id')
        frm = cq.get('from') or {}
        uid = str(frm.get('id') or '')

        # --- 身份校验：必须是登记过的人。没登记 -> 回话 + **不落库**
        person = self.env['edu.tg.assist.person'].sudo().search(
            [('tg_user_id', '=', uid)], limit=1)
        if not person:
            _logger.info('edu_tg_assist: 未登记用户点了按钮（uid=%s），不落库', uid or '?')
            self._answer(cq_id, '你还没登记：先私聊我发 /start，再发 /name 你的真名。')
            return {'ok': True, 'callback': 'unregistered'}

        mention = self.env['edu.tg.assist.mention'].sudo().browse(rec_id).exists()
        if not mention:
            self._answer(cq_id, '这条提醒已经不在了，请联系教务。')
            return {'ok': True, 'callback': 'missing_record'}

        msg = cq.get('message') or {}
        chat_id = str((msg.get('chat') or {}).get('id') or '')
        tg_name = ' '.join(x for x in [frm.get('first_name'), frm.get('last_name')] if x) \
            or frm.get('username') or ''

        Reply = self.sudo()
        existing = Reply.search([('mention_id', '=', mention.id), ('tg_user_id', '=', uid)], limit=1)
        vals = {
            'mention_id': mention.id,
            'person_id': person.id,
            'tg_user_id': uid,
            'tg_name': tg_name,
            'choice': choice,
            'chat_id': chat_id,
            'raw_data': (cq.get('data') or '')[:64],
            'replied_at': fields.Datetime.now(),
        }
        if existing:
            # 重复点（含改主意）：改这一行的选项，**不新增行**
            existing.write(vals)
            rec = existing
        else:
            rec = Reply.create(vals)
        _logger.info('edu_tg_assist: 按钮回填 #%d -> %s（%s）', rec.id, choice, person.name)

        self._answer(cq_id, '已记录：%s。谢谢！' % self._label(choice))
        return {'ok': True, 'reply_id': rec.id, 'choice': choice}
