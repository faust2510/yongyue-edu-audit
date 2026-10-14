# -*- coding: utf-8 -*-
"""发送记录 —— **刻意不叫 outbox**：生产匿名意见箱有一张 edu_telegram_outbox，避嫌。

只记「发过什么、成没成」，用于排障与审计；不做重试队列（重试会打乱提醒语义）。
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# D2：保留天数（系统参数）。默认 90 天；显式配 0 = 永久保留、什么都不清。
KEEP_DAYS_PARAM = 'edu_tg_assist.send_log_keep_days'
KEEP_DAYS_DEFAULT = 90


class EduTgAssistSendLog(models.Model):
    _name = 'edu.tg.assist.send_log'
    _description = 'Telegram 发送记录'
    _order = 'sent_at desc, id desc'

    chat_id = fields.Char('目标 chat_id', required=True, index=True)
    text = fields.Text('内容')
    ok = fields.Boolean('成功', default=False)
    error = fields.Char('失败原因')
    kind = fields.Char('来源', help='manual / cron / mention / dm / notify …')
    sent_at = fields.Datetime('时间', default=fields.Datetime.now, required=True)

    @api.model
    def log(self, chat_id, text, ok, error, kind):
        return self.sudo().create({
            'chat_id': str(chat_id),
            'text': text or '',
            'ok': bool(ok),
            'error': (error or '')[:500],
            'kind': (kind or 'manual')[:32],
        })

    # ------------------------------------------------------------------
    # D2 自动清理（发送记录会一直涨：定时提醒一天几条、广播一次一群一条）
    # ------------------------------------------------------------------
    @api.model
    def _keep_days(self):
        '保留天数：参数 KEEP_DAYS_PARAM；读不出/非法按默认 90；0 = 不清。',
        raw = (self.env['ir.config_parameter'].sudo()
               .get_param(KEEP_DAYS_PARAM) or '').strip()
        try:
            days = int(raw)
        except (TypeError, ValueError):
            return KEEP_DAYS_DEFAULT
        return max(days, 0)

    @api.model
    def _prune_old(self):
        '删掉「保留天数」之前的发送记录，返回删除条数。0 天 = 一条也不删。',
        days = self._keep_days()
        if days <= 0:
            return 0
        limit = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        old = self.sudo().search([('sent_at', '<', limit)])
        count = len(old)
        if count:
            old.unlink()
            _logger.info('edu_tg_assist: 清理 %s 天前的发送记录 %s 条', days, count)
        return count

    @api.model
    def _cron_prune(self):
        'cron 入口（data/ir_cron_data.xml 里写的就是这个名字）。',
        self._prune_old()
        return True

    def action_prune_now(self):
        '后台「清理发送记录」菜单：立刻清一次，并弹一句结果。',
        count = self.sudo()._prune_old()
        days = self.sudo()._keep_days()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '清理完成',
                'message': (('已删除 %s 条（保留最近 %s 天）。' % (count, days)) if days > 0
                            else '保留天数设为 0（永久保留），什么都没有删。'),
                'type': 'success',
                'sticky': False,
            },
        }
