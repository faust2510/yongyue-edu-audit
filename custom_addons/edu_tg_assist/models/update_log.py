# -*- coding: utf-8 -*-
"""Telegram update 幂等去重 —— 同一条 update 只处理一次。

为什么必须有它：Telegram 在网络抖动、或我方没能在时限内回 200 时会**重投同一条
update（update_id 不变）**。不去重意味着「/dm 张三 明天交表」可能被处理两遍 ——
对管理工具就是重复私发、重复广播、重复留痕。

口径：
  · 用 update_id（Telegram 给的全局序号）做唯一键；
  · **没有 update_id 的 update 一律放行**（手工 curl 探针、本地单测）——
    去重只针对平台真的会重投的那种输入，别让本地演练被它挡住；
  · 这张表只看「最近有没有重投」，1 天前的记录顺手清掉（不用长期长）。
"""
import logging

from psycopg2 import IntegrityError as PgIntegrityError

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

KEEP_DAYS = 1
PRUNE_LIMIT = 200


class EduTgAssistUpdateLog(models.Model):
    _name = 'edu.tg.assist.update_log'
    _description = 'Telegram update 幂等去重'
    _order = 'id desc'

    update_id = fields.Char('update_id', required=True, index=True,
                            help='Telegram 的 update_id；同一条 update 只处理一次。')
    kind = fields.Char('类型', help='callback_query / message / edited_message …')
    route = fields.Char('入口', help='这条 update 从哪个入口进来（gate / assist_webhook / 手工）。')
    received_at = fields.Datetime('收到时间', default=fields.Datetime.now,
                                  required=True, index=True)

    # Odoo 19 新约束 API（旧 _sql_constraints 只打 WARNING、不再被消费）
    _update_id_uniq = models.Constraint(
        'unique(update_id)', '同一条 update 只能处理一次。')

    @api.model
    def claim(self, update_id, kind='', route=''):
        """认领一条 update。

        :param route: 入口名（只写进表里留痕，排障时看「这条是从哪进来的」）。
        :return: True = 首次见到、可以处理；False = 平台重投，跳过。
        """
        uid = str(update_id or '').strip()
        if not uid:
            # 没有 update_id 不拦：本地探针/单测造的 update 本来就该能跑。
            return True
        if self.sudo().search_count([('update_id', '=', uid)], limit=1):
            return False
        try:
            # savepoint：唯一键冲突只回滚这一条插入，不影响外层事务
            with self.env.cr.savepoint():
                self.sudo().create({'update_id': uid, 'kind': (kind or '')[:32],
                                    'route': (route or '')[:32]})
        except PgIntegrityError:
            # 并发重投（两个 worker 同时处理同一条）：先到者赢，后来者安静跳过
            _logger.info('edu_tg_assist: update %s 重投，已跳过', uid)
            return False
        self._prune()
        return True

    @api.model
    def _prune(self):
        """清掉 KEEP_DAYS 天前的记录（有界，失败绝不影响本次处理）。"""
        try:
            cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=KEEP_DAYS)
            old = self.sudo().search([('received_at', '<', cutoff)], limit=PRUNE_LIMIT)
            if old:
                old.unlink()
        except Exception as exc:  # noqa: BLE001
            _logger.warning('edu_tg_assist: 清理 update_log 失败：%s', type(exc).__name__)
