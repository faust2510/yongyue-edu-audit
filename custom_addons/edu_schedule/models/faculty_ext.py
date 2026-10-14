# -*- coding: utf-8 -*-
"""教师档案 × 原生资源（resource.resource）：教师不可用时间的**数据侧**（G4 §10.1）。

**为什么是「加一列 resource_id + get-or-create 助手」而不是原方案的 resource.mixin**
——§10.1 的断言失败，按任务书回退；下面是判定证据，无新证据不要改回 mixin：

  resource.mixin 自带 company_id = fields.Many2one('res.company',
  related='resource_id.company_id')；而 op.faculty 现靠
  _inherits = {'res.partner': 'partner_id'} 把 company_id 委派给 res.partner
  （openeducat_core/models/faculty.py 里没有自己的 company_id 字段）。
  Odoo ORM 生成 _inherits 委派字段时**只补本模型还没有的字段名**
  （odoo/orm/model_classes.py:480-505，注释 "add inherited fields that are not
  redefined locally" 下的 if name not in model_cls._fields），而 _inherit 进来的
  字段先落地 ⇒ mixin 的 company_id 占住该名字 ⇒ 委派字段不再生成 ⇒ 写
  op.faculty.company_id 只改资源所属公司，**不再同步 res_partner.company_id**，
  多公司规则被破坏。故不接 mixin。

本文件只做两件事，判定逻辑不在这里（在 models/session_ext.py）：
  ① resource_id 列 + _get_or_create_resource()：建档案即建资源，存量靠迁移脚本补
     （scripts/migrations/backfill_faculty_resource.py）；
  ② _leave_intervals_utc()：该教师在某个窗口内**个人登记的例外**，全仓判定唯一入口。

不接常规工时：资源上的 calendar_id 保持公司默认，本模块不展示、不参与判定
（§10.2「判定只看例外」）——所以晚课/周末课不会被误判成不可用。
"""
import pytz

from odoo import api, fields, models


class OpFaculty(models.Model):
    _inherit = 'op.faculty'

    #: 占位教师名（生产实测：216 节课的任课教师全是「待定」——§8.1「待补」档判据）。
    #: 判成「致命」就是 216 条红，全红等于没有判据，所以只做「待补」。
    PLACEHOLDER_NAMES = ('待定', '待定教师', '未定', '未指定')

    resource_id = fields.Many2one(
        'resource.resource', string='资源', index=True, ondelete='set null',
        copy=False,
        help='教师不可用时间的宿主：resource.calendar.leaves 按该资源登记例外。'
             '不接 resource.mixin 的原因见 models/faculty_ext.py 文件头。')

    # ------------------------------------------------------------------
    # 一、资源随教师档案生成
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """建教师档案就顺手建资源（§10.1「资源随教师档案自动生成」）。"""
        faculties = super().create(vals_list)
        for faculty in faculties.filtered(lambda f: not f.resource_id):
            faculty._get_or_create_resource()
        return faculties

    def _get_or_create_resource(self):
        """取（缺则建）本教师的资源记录；登记不可用时间前必须走它。"""
        self.ensure_one()
        faculty = self.sudo()
        if faculty.resource_id:
            return faculty.resource_id
        resource = self.env['resource.resource'].sudo().create({
            'name': faculty.name or ('教师 #%d' % faculty.id),
            'company_id': faculty.partner_id.company_id.id or self.env.company.id,
        })
        faculty.resource_id = resource.id
        return resource

    def _is_placeholder(self):
        """是不是占位「待定」教师（「待补」档，不是「致命」档）。"""
        return (self.name or '').strip() in self.PLACEHOLDER_NAMES

    # ------------------------------------------------------------------
    # 二、判定唯一入口：只看例外
    # ------------------------------------------------------------------
    def _leave_intervals_utc(self, start_utc, end_utc):
        """该教师在 [start_utc, end_utc] 内**个人登记**的例外，UTC naive 三元组列表。

        返回 [(起, 止, 原因), ...]（无资源返回 []）。口径每条都是踩过的坑：
          · 只用 resource.calendar._leave_intervals_batch；**绝不用**
            _unavailable_intervals* / _get_unavailable_intervals /
            _work_intervals_batch —— 它们掺入「常规工时」，会把 19:15-21:15 的
            晚课与周末课误判成不可用（V14 就是这条的反例断言）。
          · 传**空** calendar（调用者是空记录集）⇒ 源码里 if self: 为假 ⇒ 跳过
            ('calendar_id','in',…) 过滤，例外不被某个工时日历挡住。
          · tz 必须传 **tzinfo 对象**（这里是 pytz.utc），**不能传字符串
            'UTC'**：core 在 resource_calendar.py:541 直接
            start = start_dt.astimezone(tz) 把它喂给 datetime.astimezone，
            字符串 ⇒ TypeError: tzinfo argument must be None or of a tzinfo
            subclass（线上真机踩过：整页 /timetable/bulk 500）。core 自己的
            默认值也来自 pytz.timezone((resource or self).tz)（:537）。
            传 pytz.utc ⇒ 返回值与 op.session 的入库口径（UTC naive）同轴，
            不受资源时区影响。
          · domain 里 resource_id != False：公共假期（无资源）归停课日管，
            不算「这位教师登记的不可用」。
        """
        self.ensure_one()
        resource = self.sudo().resource_id
        if not (start_utc and end_utc and resource):
            return []
        intervals = self.env['resource.calendar']._leave_intervals_batch(
            start_utc.replace(tzinfo=pytz.utc) if start_utc.tzinfo is None
            else start_utc,
            end_utc.replace(tzinfo=pytz.utc) if end_utc.tzinfo is None
            else end_utc,
            resources=resource,
            domain=[('time_type', '=', 'leave'), ('resource_id', '!=', False)],
            tz=pytz.utc,
        ).get(resource.id) or []
        rows = []
        for iv in intervals:
            # iv[2] 是这段区间背后的 leave 记录**集**，不是单条：core 会把
            # 相邻/重叠的例外并成一个区间（odoo/tools/intervals.py 的 Intervals），
            # 于是这里可能是多条记录 —— 直接 iv[2].name 会
            # ValueError: Expected singleton: resource.calendar.leaves(1, 2)
            # （真机踩过：/timetable/bulk 全页 500）。用 mapped 取名字列表。
            reason = '、'.join(n for n in iv[2].mapped('name') if n)
            rows.append((
                iv[0].astimezone(pytz.utc).replace(tzinfo=None),
                iv[1].astimezone(pytz.utc).replace(tzinfo=None),
                reason))
        return rows

    def _has_leave_records(self):
        """该教师有没有登记过任何不可用例外（§10.4 兜底：未登记 = 可用，但要说出来）。"""
        self.ensure_one()
        resource = self.resource_id
        if not resource:
            return False
        return bool(self.env['resource.calendar.leaves'].sudo().search_count(
            [('resource_id', '=', resource.id)]))
