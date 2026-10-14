# -*- coding: utf-8 -*-
"""学号登录失败限速：**跨进程共享**的失败计数（落库）。

为什么不是进程内令牌桶（2026-10-12 实测推翻，见设计文档 §9.12.6）：
  controllers/search.py 的桶是模块级 dict，多 worker 下每个进程各一份 ——
  本地 odoo.conf `workers = 6`，连打 8 次错误密码后用**正确**密码登录
  仍然成功（303 /my/home），日志里「尝试过于频繁」计数为 0。
  生产同样是多 worker（部署日志有「Stopping workers gracefully」）⇒ 落库共享。

只统计**失败**：成功登录立刻删行，所以正常用户（含学校 NAT 后共用出口 IP 的
一群人）不会被误伤；被挡的只有「同一个 IP 反复试同一个学号」。
"""
import datetime
import logging

from odoo import api, fields, models

from odoo.addons.edu_portal.login_alias import (
    blocked_seconds,
    next_failure_state,
)

_logger = logging.getLogger(__name__)

#: 陈旧行（最后尝试在一天以前）在写失败时顺手清掉 —— 不另开 cron，表很小。
STALE_SECONDS = 86400


def _to_ts(value):
    """Datetime（naive UTC）→ Unix 秒；空值返回 None。"""
    if not value:
        return None
    return fields.Datetime.to_datetime(value).replace(
        tzinfo=datetime.timezone.utc).timestamp()


def _to_dt(ts):
    """Unix 秒 → Datetime（naive UTC）；0/None 返回 False。"""
    if not ts:
        return False
    return datetime.datetime.fromtimestamp(
        float(ts), datetime.timezone.utc).replace(tzinfo=None)


class EduPortalLoginThrottle(models.Model):
    _name = 'edu.portal.login.throttle'
    _description = '学号登录失败限速（跨进程共享）'

    bucket_key = fields.Char('限速键', required=True, index=True)
    failures = fields.Integer('窗口内失败次数', default=0)
    window_start = fields.Datetime('窗口起点')
    blocked_until = fields.Datetime('封禁到')
    last_attempt_at = fields.Datetime('最后尝试')

    _bucket_key_uniq = models.Constraint(
        'unique(bucket_key)', '同一个限速键只允许一行。')

    @api.model
    def blocked_seconds(self, key):
        """这个键还要等几秒（0 = 放行）。"""
        if not key:
            return 0
        rec = self.sudo().search([('bucket_key', '=', key)], limit=1)
        if not rec:
            return 0
        return blocked_seconds(_to_ts(rec.blocked_until), fields.Datetime.now().timestamp())

    @api.model
    def _bump(self, key):
        """记一次失败（窗口内累加，够数就封）。

        封禁中再来一次失败：**不叠加、不续期、也不清掉封禁** ——
        2026-10-12 生产探针实测到的坑：连打第 9 次时 next_failure_state 看到
        「failures 已被第 8 次清零」，会算出 (1, now, 0) 并把刚封上的
        blocked_until 覆盖成 0，等于攻击者自己把封禁解开。
        控制器在封禁期本来就不计数（见 controllers/main.py 的 _edu_alias_login），
        这里是模型层的第二道保险：谁调都不许解锁。
        """
        now = fields.Datetime.now()
        rec = self.sudo().search([('bucket_key', '=', key)], limit=1)
        if rec and blocked_seconds(_to_ts(rec.blocked_until), now.timestamp()) > 0:
            rec.sudo().write({'last_attempt_at': now})
            return
        failures, window_start, blocked_until = next_failure_state(
            rec.failures if rec else 0,
            _to_ts(rec.window_start) if rec else None,
            now.timestamp(),
        )
        vals = {
            'failures': failures,
            'window_start': _to_dt(window_start),
            'blocked_until': _to_dt(blocked_until),
            'last_attempt_at': now,
        }
        if rec:
            rec.sudo().write(vals)
        else:
            vals['bucket_key'] = key
            self.sudo().create(vals)
        self._prune_stale(now)

    @api.model
    def clear(self, key):
        """登录成功：把这个键的失败计数清零（删行）。"""
        if not key:
            return
        self.sudo().search([('bucket_key', '=', key)]).unlink()

    @api.model
    def _prune_stale(self, now):
        cutoff = _to_dt(now.timestamp() - STALE_SECONDS)
        try:
            self.sudo().search([('last_attempt_at', '<', cutoff)]).unlink()
        except Exception as exc:  # noqa: BLE001
            _logger.warning('edu_portal: 学号登录限速清理失败（%s）', type(exc).__name__)
