# -*- coding: utf-8 -*-
"""一体化校历 · 轻量活动模型 edu.event（v2.1-B10）。

门户「校历」月视图（/my/calendar）的第四路数据源：在课程 op.session、
考试 op.exam、停课日 edu.schedule.holiday 之外承载学校/班级级活动。

新建/修改活动走排课同款冲突拦截（对齐 openeducat_timetable 的
check_timetable_fields 规则）：
- 同教师时段重叠 → 拦截；
- 同教室时段重叠 → 拦截；
- 同班级时段重叠 → 拦截；
- 重叠判定为「严格开区间」（背靠背 10:00-11:00 / 11:00-12:00 不冲突）；
- 已取消的课程（state=cancel）不参与冲突；停用的活动不参与冲突。

约束放在模型层（@api.constrains + 事务内 sudo 全量搜索），后端直建
同样不可绕过；门户控制器在提交前先做一次同样检查以便红字明细提示。
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EduEvent(models.Model):
    _name = 'edu.event'
    _description = '校历活动'
    _order = 'start_datetime asc, id asc'

    name = fields.Char('标题', required=True)
    start_datetime = fields.Datetime('开始时间', required=True, index=True)
    end_datetime = fields.Datetime('结束时间', required=True)
    location = fields.Char('地点')
    event_type = fields.Selection([
        ('meeting', '会议'),
        ('activity', '活动'),
        ('ceremony', '典礼'),
        ('notice', '活动通知'),
        ('other', '其他'),
    ], string='类型', required=True, default='activity')
    # 空 = 全校活动；指定班级 = 仅该班可见（学生/家长过滤依据）
    batch_id = fields.Many2one('op.batch', string='限定班级（空=全校）')
    # 冲突检测维度（可空：空则不在该维度上检查，与排课拦截一致）
    faculty_id = fields.Many2one(
        'op.faculty', string='负责教师',
        help='用于冲突检测：与该教师已有课程/活动时段重叠时拦截。')
    classroom_id = fields.Many2one(
        'op.classroom', string='教室',
        help='用于冲突检测：与该教室已有课程/活动时段重叠时拦截。')
    active = fields.Boolean('启用', default=True)
    # 创建人 = Odoo 内建 create_uid（模板展示 create_uid.name），无需自建字段

    _date_order = models.Constraint(
        'CHECK (end_datetime >= start_datetime)',
        '结束时间不能早于开始时间。')

    @api.constrains('start_datetime', 'end_datetime', 'faculty_id',
                    'classroom_id', 'batch_id')
    def _check_time_window(self):
        for rec in self:
            if not (rec.start_datetime and rec.end_datetime):
                continue
            if rec.start_datetime > rec.end_datetime:
                raise ValidationError(_('结束时间不能早于开始时间。'))

    @api.constrains('start_datetime', 'end_datetime', 'faculty_id',
                    'classroom_id', 'batch_id')
    def _check_overlap(self):
        """排课同款冲突拦截：同教师/同教室/同班级时段重叠即拒绝。"""
        for rec in self:
            if not (rec.start_datetime and rec.end_datetime):
                continue
            conflicts = self._overlap_conflicts(
                rec.start_datetime, rec.end_datetime,
                rec.faculty_id.id, rec.classroom_id.id, rec.batch_id.id,
                exclude_event_id=rec.id)
            if conflicts:
                detail = '；'.join(
                    '%s「%s」（%s - %s）' % (
                        c['kind'], c['name'], c['start_str'], c['end_str'])
                    for c in conflicts[:5])
                if len(conflicts) > 5:
                    detail += ' 等 %d 项' % len(conflicts)
                raise ValidationError(_('时间冲突：%s') % detail)

    @api.model
    def _overlap_conflicts(self, start, end, faculty_id=False,
                           classroom_id=False, batch_id=False,
                           exclude_event_id=None, exclude_session_id=None):
        """与给定时段在任一冲突维度上重叠的已有排期。

        返回 [{'kind': '课程'/'活动', 'name': str, 'start': dt, 'end': dt,
               'start_str': str, 'end_str': str}]，按开始时间升序。
        规则对齐排课冲突拦截：严格开区间重叠；仅当维度有值时检查该维度；
        已取消课程与停用活动不参与。
        """
        out = []
        if not (start and end):
            return out

        def _fmt(dt):
            if not dt:
                return ''
            local = fields.Datetime.context_timestamp(
                self.env.user, dt).replace(tzinfo=None)
            return local.strftime('%m-%d %H:%M')

        window = [
            ('start_datetime', '<', end),
            ('end_datetime', '>', start),
        ]

        def _match_dims(rec):
            if faculty_id and rec.faculty_id.id == faculty_id:
                return True
            if classroom_id and rec.classroom_id.id == classroom_id:
                return True
            if batch_id and rec.batch_id.id == batch_id:
                return True
            return False

        # 学 校/班级活动（同模型，排除自身与已停用）
        ev_domain = [('active', '=', True)] + list(window)
        if exclude_event_id:
            ev_domain.append(('id', '!=', exclude_event_id))
        for ev in self.sudo().search(ev_domain):
            if _match_dims(ev):
                out.append({
                    'kind': '活动', 'name': ev.name or _('未命名活动'),
                    'start': ev.start_datetime, 'end': ev.end_datetime,
                    'start_str': _fmt(ev.start_datetime),
                    'end_str': _fmt(ev.end_datetime),
                })

        # 课 程（op.session：已取消的不参与，与排课拦截一致）
        ss_domain = [('state', '!=', 'cancel')] + list(window)
        if exclude_session_id:
            ss_domain.append(('id', '!=', exclude_session_id))
        sessions = self.env['op.session'].sudo().search(ss_domain)
        for ses in sessions:
            if _match_dims(ses):
                out.append({
                    'kind': '课程',
                    'name': ses.subject_id.name or ses.name or _('未命名课程'),
                    'start': ses.start_datetime, 'end': ses.end_datetime,
                    'start_str': _fmt(ses.start_datetime),
                    'end_str': _fmt(ses.end_datetime),
                })

        out.sort(key=lambda c: (c['start'] or start))
        return out