# -*- coding: utf-8 -*-
"""op.session 冲突分色扩展（S1，视图层增强，零上游改动）。

- conflict_kind:   只读计算字段——与同时段其他课节的冲突维度
  （faculty / classroom / batch_subject / batch，无冲突为空）。
- conflict_color:  只读计算字段——日历事件颜色 **Integer 数值 0-3**
  （Odoo calendar 前端 getColor() 仅对 typeof number 走 0-55 索引色板档，
  字符串/Selection 值会走 hash 分支产生随机色——实证见 t14 B1）。
  Integer 0/1/2/3 → o_calendar_color_0/1/2/3：
  0=无冲突默认档 / 1=教师冲突红 / 2=教室冲突橙 / 3=班级(含班级+科目)黄琥珀。
  _KIND_HEX 仅供前端图例/文案层展示，不进入视图 color 字段。

口径与上游约束 check_timetable_fields 完全同构：
±24h 窗口预筛 + sudo 全量可见 + state != cancel 不参与冲突；
仅在课节所属时段周边做一次检查，store=False 不落库、不触发写入路径。
"""
import datetime
from datetime import timedelta

import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .identity import users_of_profile

_logger = logging.getLogger(__name__)

# 冲突维度 → Integer 色板索引（compute 用；0=默认/1=教师/2=教室/3=班级）
_KIND_INDEX = {
    '': 0,                    # 默认档
    'faculty': 1,             # 教师冲突 · 红
    'classroom': 2,           # 教室冲突 · 橙
    'batch_subject': 3,       # 班级+科目冲突 · 琥珀（并入班级档）
    'batch': 3,               # 班级冲突 · 黄（并入班级档）
}
_KIND_HEX = {
    0: '',                    # 默认色
    1: '#DC2626',             # 教师冲突 · 红
    2: '#E7650A',             # 教室冲突 · 橙
    3: '#D97706',             # 班级+科目/班级冲突 · 琥珀/黄
}
_KIND_LABEL = {
    0: '无冲突',
    1: '教师冲突',
    2: '教室冲突',
    3: '班级冲突（含班级+科目）',
}


# ----------------------------------------------------------------------
# C-1 改课影响面共用的小工具（模块级：模板/审计/通知三处同一份口径）
# ----------------------------------------------------------------------
def _impact_when(rec, start, end):
    """UTC naive 时刻 → 用户时区的展示文本（与门户课表同一换算口径）。"""
    if not start:
        return ''
    text = fields.Datetime.context_timestamp(rec, start).strftime(
        '%Y-%m-%d %H:%M')
    if end:
        text += '–' + fields.Datetime.context_timestamp(
            rec, end).strftime('%H:%M')
    return text


def _session_dt(value):
    """vals 里的时间值 → naive datetime（None/False 原样返回 None）。

    拦截判定要在**基座字段转换之前**跑，这里与 fields.Datetime.to_datetime
    同一口径，避免「字符串/date 对象」两种输入判出两种结果。
    """
    if not value:
        return None
    return fields.Datetime.to_datetime(value)


def _impact_field_text(rec, field_name, value):
    """字段值 → 可读文本（old→new 摘要与审计明细共用一份口径）。"""
    if field_name == 'state':
        return rec.IMPACT_STATE_LABELS.get(value or '', value or '（空）')
    if isinstance(value, models.BaseModel):
        return value.display_name or '（空）'
    if isinstance(value, datetime.datetime):
        return fields.Datetime.context_timestamp(rec, value).strftime(
            '%Y-%m-%d %H:%M')
    if value in (None, False, ''):
        return '（空）'
    return str(value)


def _impact_same(a, b):
    """写入前后是否同一个值（many2one 比 id，其余比真值；不用展示文本比，
    否则「同分钟内秒数不同」这类真实改动会被判成没变）。"""
    if isinstance(a, models.BaseModel) or isinstance(b, models.BaseModel):
        a_id = a.id if isinstance(a, models.BaseModel) else a
        b_id = b.id if isinstance(b, models.BaseModel) else b
        return (a_id or 0) == (b_id or 0)
    return a == b


class OpSessionConflictExt(models.Model):
    _inherit = 'op.session'

    conflict_kind = fields.Char(
        string='冲突类型', compute='_compute_conflict', store=False,
        help='与同时段其他课节的冲突维度；无冲突为空。')
    conflict_color = fields.Integer(
        string='冲突配色', compute='_compute_conflict', store=False,
        help='日历事件颜色索引（0=默认/1=教师/2=教室/3=班级）；'
             'Integer 数值走 Odoo calendar 0-55 色板档（o_calendar_color_0-3）。')

    def conflict_kind_label(self):
        """展示用中文标签（模板/弹窗可选使用）。"""
        return _KIND_LABEL.get(self.conflict_color, '')

    def _compute_conflict(self):
        for rec in self:
            rec.conflict_kind = ''
            rec.conflict_color = 0
        recs = self.filtered(lambda r: r.state != 'cancel'
                             and r.start_datetime and r.end_datetime)
        if not recs:
            return
        dt_min = min(recs.mapped('start_datetime')) - timedelta(hours=24)
        dt_max = max(recs.mapped('end_datetime')) + timedelta(hours=24)
        others = self.env['op.session'].sudo().search([
            ('state', '!=', 'cancel'),
            ('start_datetime', '>=', dt_min),
            ('start_datetime', '<=', dt_max),
        ])
        # 批量计算（日历视图一次读取整窗口事件）时，self 内互相冲突的
        # 课时必须彼此可见：others 取「窗口内全部非取消课时」（含 self，
        # 循环内按 id 跳过自身），不能从 domain 排除整个 recs——
        # 否则同批两条冲突课时互相看不到，视图上不显色。
        # 单记录计算时 others 含其余课时，行为与上游四查同构不变。

        def _overlaps(a, b):
            return (a.start_datetime < b.end_datetime
                    and b.start_datetime < a.end_datetime)

        kind_by_id = {}
        for rec in recs:
            kind = ''
            for other in others:
                if other.id == rec.id:
                    continue
                if not _overlaps(rec, other):
                    continue
                if rec.faculty_id and other.faculty_id \
                        and rec.faculty_id.id == other.faculty_id.id:
                    # 教师冲突最重（红），命中即定级并提前结束扫描
                    kind = 'faculty'
                    break
                if rec.classroom_id and other.classroom_id \
                        and rec.classroom_id.id == other.classroom_id.id:
                    kind = kind or 'classroom'
                elif rec.batch_id and other.batch_id \
                        and rec.batch_id.id == other.batch_id.id:
                    if rec.subject_id and other.subject_id \
                            and rec.subject_id.id == other.subject_id.id:
                        kind = kind or 'batch_subject'
                    else:
                        kind = kind or 'batch'
            kind_by_id[rec.id] = kind
        for rec in recs:
            kind = kind_by_id.get(rec.id, '')
            rec.conflict_kind = kind
            rec.conflict_color = _KIND_INDEX.get(kind, 0)

    # ==================================================================
    # v3 课节级会议链接 + 课前提醒
    # 决策依据：docs/research/onestop-learning-and-repetitive-work.md
    #   §2「Odoo 19 原生会议链接位」§2.1#1（按课节存 join URL）
    #   §2「send_ical_notifications 每 5 分钟独立计划任务」
    #   §5#10「复用 videocall_location + access_token，不自建 URL 体系」
    # ==================================================================
    calendar_event_id = fields.Many2one(
        'calendar.event', string='关联日程', ondelete='set null', copy=False,
        help='会议链接存放于该日程的原生「Meeting URL」字段，不自建 URL 体系。')
    meeting_url = fields.Char(
        string='会议链接', related='calendar_event_id.videocall_location',
        readonly=True)
    reminder_sent_at = fields.Datetime(
        string='课前提醒已发送', readonly=True, copy=False)

    # ---- 参数（系统参数，零 schema 变更）----
    @api.model
    def _meeting_param(self, key, default):
        """读系统参数并转 int；缺失/空值/不可解析一律回落 default。

        坑：ir.config_parameter.get_param 在参数不存在时返回 False，
        而 int(False) == 0——不做 None/False/'' 判空的话，默认值永远
        不生效（课前提醒窗口会缩成 now..now+5min，提前入会分钟数变 0）。
        """
        val = self.env['ir.config_parameter'].sudo().get_param(key)
        if val in (None, False, ''):
            return default
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def _join_lead_minutes(self):
        """最早可入会分钟数（对应 mod_zoom 的 firstjoin / leadtime）。"""
        return self._meeting_param('edu.meeting.join_lead_minutes', 15)


    # ---- 写入：URL 只落原生 calendar.event.videocall_location ----
    def set_meeting_url(self, url):
        """设置/清除课节级会议链接。传空串则解除关联并删除对应日程。"""
        self.ensure_one()
        url = (url or '').strip()
        Event = self.env['calendar.event'].sudo()
        if not url:
            ev = self.calendar_event_id.sudo()
            self.calendar_event_id = False
            if ev:
                ev.unlink()
            return True
        if not url.startswith(('http://', 'https://')):
            raise ValidationError(_('会议链接必须以 http:// 或 https:// 开头。'))
        time_vals = {
            'start': self.start_datetime,
            'stop': self.end_datetime or self.start_datetime,
        }
        if self.calendar_event_id:
            self.calendar_event_id.sudo().write(dict(
                time_vals, videocall_location=url))
        else:
            ev = Event.create(dict(
                time_vals,
                name='【课节】%s' % (self.subject_id.name or self.name or '上课'),
                videocall_location=url,
                privacy='public'))
            self.calendar_event_id = ev.id
        return True

    # ---- 入会时间窗 ----
    def join_state(self):
        """当前入会状态（模板只做纯输出，文案在控制器/模型侧算好）。"""
        self.ensure_one()
        now = fields.Datetime.now()
        url = self.meeting_url or ''
        if not url:
            return {'ready': False, 'has_url': False,
                    'label': '待教师发布会议链接', 'url': ''}
        if not self.start_datetime:
            return {'ready': True, 'has_url': True, 'label': '进入会议', 'url': url}
        opens_at = self.start_datetime - timedelta(
            minutes=self._join_lead_minutes())
        if now < opens_at:
            mins = int((opens_at - now).total_seconds() // 60) + 1
            return {'ready': False, 'has_url': True, 'url': url,
                    'label': '还有 %d 分钟可入会' % mins}
        return {'ready': True, 'has_url': True, 'label': '进入会议', 'url': url}

    # ---- 课前提醒 ----
    def _reminder_body(self):
        self.ensure_one()
        when = fields.Datetime.context_timestamp(
            self, self.start_datetime).strftime('%m月%d日 %H:%M')
        return ('【课前提醒】%s 将于 %s 开始，会议链接：%s'
                % (self.subject_id.name or self.name or '课节', when,
                   self.meeting_url or ''))

    def _session_student_users(self):
        """本节学生的登录账号（C-1 收件人解析的唯一口径）。

        兜底：课节的 student_ids 是「选 Batch 时自动填充」，而经 ORM/种子/
        导入创建的课节不跑 onchange，该字段会为空——此时回退到该班级的
        在读学生（op.student.course）。本地库 op_session_op_student_rel
        **0 行**（全员为空）⇒ 不做这一步回退就会静默发给 0 人。
        """
        self.ensure_one()
        students = self.student_ids
        if not students and self.batch_id:
            scs = self.env['op.student.course'].sudo().search(
                [('batch_id', '=', self.batch_id.id)])
            students = scs.mapped('student_id')
        # 双向并集（identity.users_of_profile）：只取 student.user_id 会漏掉
        # 「账号由脚本新建（只按 res.users.partner_id 挂）」的学生 ⇒ 静默少发。
        return users_of_profile(students)

    def _reminder_users(self):
        """收件人 = 课节学生 ∪ 任课教师（课前提醒与 C-1 一键通知共用）。"""
        self.ensure_one()
        users = self.env['res.users'].sudo()
        students = self._session_student_users()
        if students:
            users |= students
        # 任课教师同样走双向并集：只认 faculty_id.user_id（= partner.user_id，
        # 销售员列）会漏掉脚本新建的教师账号 ⇒ 收件人被静默算成 0 人。
        if self.faculty_id:
            users |= users_of_profile(self.faculty_id)
        return users

    def _notify_upcoming(self):
        """站内信 + Telegram（均运行时查找，缺模块不报错）。返回是否发出。"""
        self.ensure_one()
        body = self._reminder_body()
        users = self._reminder_users()
        if not users:
            return False
        sent = failed = 0
        # ① 站内信：逐条 try —— 单条失败不影响其余人，且失败**可计数**
        #    （t51：原先整段 except pass，导致「没有到点课节」与「发送失败」
        #     在 cron 返回值与日志上完全同形，属静默失败家族）
        sender = self.env.ref('base.user_root', raise_if_not_found=False) \
            or self.env.user
        try:
            Msg = self.env['edu.message'].sudo()
        except Exception:
            Msg = None
            failed += len(users)
            _logger.warning('课前提醒：站内信模型不可用 session=%s',
                            self.id, exc_info=True)
        if Msg is not None:
            for usr in users:
                try:
                    Msg.create({'sender_id': sender.id,
                                'recipient_id': usr.id, 'body': body})
                    sent += 1
                except Exception:
                    failed += 1
                    _logger.warning(
                        '课前提醒：站内信发送失败 session=%s user=%s',
                        self.id, usr.id, exc_info=True)
        # ② Telegram：外部模块可能在也可能不在
        try:
            Outbox = self.env['edu.telegram.outbox'].sudo()
            Chat = self.env['op.telegram.chat'].sudo()
            faculty_users = users_of_profile(self.faculty_id) \
                if self.faculty_id else self.env['res.users']
            for usr in users:
                chat = False
                stu = self.env['op.student'].sudo().search(
                    [('user_id', '=', usr.id)], limit=1)
                if stu:
                    chat = Chat.search([('student_id', '=', stu.id)], limit=1)
                if not chat and usr.id in faculty_users.ids:
                    chat = Chat.search(
                        [('faculty_id', '=', self.faculty_id.id)], limit=1)
                if chat:
                    try:
                        Outbox.enqueue(chat.chat_id, body)
                        sent += 1
                    except Exception:
                        failed += 1
                        _logger.warning(
                            '课前提醒：Telegram 入队失败 session=%s chat=%s',
                            self.id, chat.chat_id, exc_info=True)
        except Exception:
            _logger.warning('课前提醒：Telegram 通道不可用 session=%s',
                            self.id, exc_info=True)
        return sent > 0, failed

    @api.model
    def cron_session_reminder(self):
        """每 5 分钟扫描「T-30min 未提醒」且已配会议链接的课节并提醒。

        形态抄 Moodle mod_zoom 的独立计划任务；幂等靠 reminder_sent_at：
        一旦写入不再命中，重复跑 cron 不会重复发送。
        返回值 = 本次发送条数（可作干跑证据）。
        """
        now = fields.Datetime.now()
        lead = self._meeting_param('edu.meeting.reminder_minutes', 30)
        win_start = now + timedelta(minutes=lead)
        win_end = win_start + timedelta(minutes=5)
        sessions = self.sudo().search([
            ('state', '!=', 'cancel'),
            ('calendar_event_id', '!=', False),
            ('reminder_sent_at', '=', False),
            ('start_datetime', '>=', win_start),
            ('start_datetime', '<', win_end),
        ])
        sent = failed = 0
        for ses in sessions:
            ok, nfail = ses._notify_upcoming()
            failed += nfail
            if ok:
                ses.reminder_sent_at = now
                sent += 1
        result = {'due': len(sessions), 'sent': sent, 'failed': failed}
        if failed:
            _logger.warning(
                '课前提醒：本次存在发送失败 due=%d sent=%d failed=%d',
                len(sessions), sent, failed)
        return result
    # ==================================================================
    # C-1 改课影响面 + 一键通知 + 变更留痕
    #
    # 设计稿：docs/plans/session-change-impact-design.md（第 0/3/4 步产物，
    # 裁定 = 复用 + 既有模块内扩展；零新模块 / 零新模型 / 零新表 / 零新字段）。
    # 校长已拍板 P1–P4：
    #   P1 入口页「改课影响面」／动作按钮「通知相关师生」／通知标题「调课通知」；
    #   P2 **只发站内信**（edu.message，不发邮件）；收件人 = 任课教师 + 该班
    #      全部在读学生；家长不发；事件 key session_change 默认 muted=False；
    #   P3 留痕可见范围**仅教务**（/edu/audit），不做对师生可见的痕迹界面；
    #   P4 停课（state='cancel'）走同一套通知与留痕。
    # 队长硬约束：本段任何路径都**不得**触碰 edu.telegram.outbox /
    #   edu_telegram（退役件 + 出口与生产匿名意见箱同名同表）。
    # 复用口径：conflict 定级顺序、_reminder_users 的班级回退、基座四查开关。
    # ==================================================================
    IMPACT_CHANGE_ACTION = '课节变更'
    IMPACT_NOTIFY_ACTION = '课节变更通知'
    IMPACT_EVENT_KEY = 'session_change'
    # 与基座 _NOTIFY_WORTHY_FIELDS（timetable.py:507-510）同集合：
    # 「值得通知的课表事实」正是值得留痕的字段。
    IMPACT_WATCH_FIELDS = (
        'state', 'start_datetime', 'end_datetime', 'faculty_id',
        'classroom_id', 'subject_id', 'batch_id', 'timing_id',
    )
    IMPACT_FIELD_LABELS = {
        'state': '状态',
        'start_datetime': '开始时间',
        'end_datetime': '结束时间',
        'faculty_id': '任课教师',
        'classroom_id': '教室',
        'subject_id': '科目',
        'batch_id': '班级',
        'timing_id': '时段',
        'course_id': '课程',
    }
    IMPACT_STATE_LABELS = {
        'draft': '草稿',
        'confirm': '已确认',
        'done': '已结束',
        'cancel': '停课',
    }
    IMPACT_DIM_LABELS = {
        'faculty': '教师冲突',
        'classroom': '教室冲突',
        'batch_subject': '班级+科目冲突',
        'batch': '班级冲突',
        # G4：排课预览新增的格状态（教师已登记不可用），与四个开关无关
        'faculty_leave': '教师不可用时间',
    }
    # ------------------------------------------------------------------
    # G4 教师不可用（F-1）：数据落 Odoo 原生资源（models/faculty_ext.py），
    # 判定只看教师**登记过的例外**；常规工时（resource_calendar_id）不参与。
    # ------------------------------------------------------------------
    #: 逃逸口 context 键：批量导入脚本 / 教务强行排课用，使用即写 edu.audit.log
    SKIP_TEACHER_LEAVE_KEY = 'edu_skip_teacher_leave'
    TEACHER_LEAVE_ACTION = '忽略教师不可用'
    TEACHER_LEAVE_NOTICE = '该教师未登记不可用时间：系统按「可用」处理，排课前请与教师确认。'

    # ------------------------------------------------------------------
    # 一、影响面（请求时计算，不落库）
    # ------------------------------------------------------------------
    def _impact_flags(self):
        """四查开关（与基座 check_timetable_fields 同源，只读系统参数）。

        基座判的是 search([...]).value 的**字符串真值**（'False' 亦为真），
        本处照抄同一口径——影响面要预报**基座真实会拦什么**，
        不能比基座本身聪明。
        """
        Param = self.env['ir.config_parameter'].sudo()
        return {
            'faculty': bool(
                Param.get_param('timetable.is_faculty_constraint')),
            'classroom': bool(
                Param.get_param('timetable.is_classroom_constraint')),
            'batch_subject': bool(
                Param.get_param('timetable.is_batch_and_subject_constraint')),
            'batch': bool(
                Param.get_param('timetable.is_batch_constraint')),
        }

    def _impact_overlap_dims(self, other):
        """本节与另一节课的重叠维度（定级顺序同 conflict_kind 的口径）。"""
        self.ensure_one()
        dims = []
        if self.faculty_id and other.faculty_id \
                and self.faculty_id.id == other.faculty_id.id:
            dims.append('faculty')
        if self.classroom_id and other.classroom_id \
                and self.classroom_id.id == other.classroom_id.id:
            dims.append('classroom')
        if self.batch_id and other.batch_id \
                and self.batch_id.id == other.batch_id.id:
            if self.subject_id and other.subject_id \
                    and self.subject_id.id == other.subject_id.id:
                dims.append('batch_subject')
            dims.append('batch')
        return dims

    def _impact_related(self):
        """受牵连的其他课节：±24h 预筛 + 非取消 + 时间真重叠。

        口径逐条对齐基座 check_timetable_fields（不调用它——它是
        @api.constrains，不能当查询用），并给出「会不会被系统拦下」的判词。
        """
        self.ensure_one()
        if not (self.start_datetime and self.end_datetime):
            return []
        flags = self._impact_flags()
        dt_min = self.start_datetime - timedelta(hours=24)
        dt_max = self.end_datetime + timedelta(hours=24)
        others = self.env['op.session'].sudo().search([
            ('id', '!=', self.id),
            ('state', '!=', 'cancel'),
            ('start_datetime', '>=', dt_min),
            ('start_datetime', '<=', dt_max),
        ], order='start_datetime asc, id asc')
        rows = []
        for other in others:
            if not (other.start_datetime and other.end_datetime):
                continue
            if not (self.start_datetime < other.end_datetime
                    and other.start_datetime < self.end_datetime):
                continue
            dims = self._impact_overlap_dims(other)
            if not dims:
                continue
            blocked = any(flags.get(dim) for dim in dims)
            rows.append({
                'id': other.id,
                'subject': other.subject_id.name or other.name or '',
                'batch': other.batch_id.name or '',
                'faculty': other.faculty_id.name or '',
                'when': _impact_when(self, other.start_datetime,
                                     other.end_datetime),
                'state': self.IMPACT_STATE_LABELS.get(
                    other.state, other.state or ''),
                'dims_text': '、'.join(
                    self.IMPACT_DIM_LABELS.get(d, d) for d in dims),
                'blocked': blocked,
                'verdict': '保存会被系统拦下' if blocked
                           else '不会拦，但人是受影响者',
            })
        return rows

    def _impact_tv_text(self, tv, side, field_name):
        """mail.tracking.value 的 old/new → 可读中文（与审计同一展示口径）。"""
        raw = None
        for kind in ('char', 'text', 'datetime', 'integer', 'float'):
            raw = getattr(tv, '%s_value_%s' % (side, kind), None)
            if raw not in (None, False, ''):
                break
        if field_name == 'state':
            return self.IMPACT_STATE_LABELS.get(raw or '', raw or '（空）')
        if raw in (None, False, ''):
            return '（空）'
        if isinstance(raw, str) and re.match(
                r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}', raw):
            try:
                return fields.Datetime.context_timestamp(
                    self, fields.Datetime.to_datetime(raw)
                ).strftime('%Y-%m-%d %H:%M')
            except Exception:
                return raw
        return str(raw)

    def _impact_changes(self):
        """最近一次字段级变更（口径 = chatter 的 mail.tracking.value）。

        设计稿 §7.4#2：通知必须自证是「这一次的变更」⇒ 取**最新一条带
        跟踪值的 chatter 消息**逐字段列 old→new；不新增任何字段。
        """
        self.ensure_one()
        TV = self.env['mail.tracking.value'].sudo()
        tvs = TV.search([
            ('mail_message_id.model', '=', 'op.session'),
            ('mail_message_id.res_id', '=', self.id),
        ], order='id desc', limit=40)
        if not tvs:
            return []
        newest = tvs[0].mail_message_id.id
        rows = []
        for tv in tvs:
            if tv.mail_message_id.id != newest:
                break
            name = tv.field_id.name or ''
            rows.append({
                'field': name,
                'label': self.IMPACT_FIELD_LABELS.get(
                    name, tv.field_id.field_description or name),
                'old': self._impact_tv_text(tv, 'old', name),
                'new': self._impact_tv_text(tv, 'new', name),
            })
        return rows

    def _impact_recipients(self):
        """收件人清单（带角色标注，P2：教师 + 该班在读学生，家长不发）。"""
        self.ensure_one()
        faculty_user = users_of_profile(self.faculty_id) if self.faculty_id \
            else self.env['res.users']
        rows = []
        for usr in self._reminder_users():
            rows.append({
                'id': usr.id,
                'name': usr.name or usr.login or '',
                'login': usr.login or '',
                'role': '任课教师' if usr.id in faculty_user.ids else '在读学生',
            })
        return rows

    def _impact_data(self):
        """影响面快照（模板只做纯输出）。"""
        self.ensure_one()
        recipients = self._impact_recipients()
        related = self._impact_related()
        faculty_count = len([r for r in recipients if r['role'] == '任课教师'])
        return {
            'session': self,
            'recipients': recipients,
            'recipient_count': len(recipients),
            'faculty_count': faculty_count,
            'student_count': len(recipients) - faculty_count,
            'related': related,
            'related_count': len(related),
            'blocked_count': len([r for r in related if r['blocked']]),
            'changes': self._impact_changes(),
            'last_notify': self._impact_last_notify(),
            'state_label': self.IMPACT_STATE_LABELS.get(
                self.state, self.state or ''),
            'when_text': _impact_when(
                self, self.start_datetime, self.end_datetime),
        # G3「被规则限制」档：规则不让排的事实（本期唯一可判 = 教师例外不可用）
        'rule_notes': self._impact_rule_notes(),
    }
    def _impact_last_notify(self):
        """最近一次「通知相关师生」= edu.audit.log 该 res_id 最近一条。

        数据源就是审计表（零新字段）：页面上的「最近一次通知：<时刻> ·
        <人数> 人」与「是否补发过」都由它回答。
        """
        self.ensure_one()
        try:
            Audit = self.env['edu.audit.log'].sudo()
        except Exception:
            return None
        row = Audit.search([
            ('action', '=', self.IMPACT_NOTIFY_ACTION),
            ('model', '=', 'op.session'),
            ('res_id', '=', self.id),
        ], limit=1)
        if not row:
            return None
        hit = re.search(r'(\d+)\s*人', row.detail or '')
        return {
            'when': fields.Datetime.context_timestamp(
                self, row.create_date).strftime('%Y-%m-%d %H:%M'),
            'count': int(hit.group(1)) if hit else 0,
            'by': row.user_id.name or '',
            'detail': row.detail or '',
            'action': row.action,
        }

    # ------------------------------------------------------------------
    # 二、一键通知（P2：只发站内信；不发邮件、不碰 telegram 出口）
    # ------------------------------------------------------------------
    @api.model
    def _impact_is_muted(self, Pref, user):
        """该用户是否把 session_change 静音。

        用于把「静音跳过」与「发送失败」分开计数——_notify_event 对两者
        都返回 False，不单独查偏好就分不清（设计稿 §7.4#3 要求失败可计数）。
        """
        if Pref is None or not user:
            return False
        try:
            return bool(Pref.search_count([
                ('user_id', '=', user.id),
                ('event_key', '=', self.IMPACT_EVENT_KEY),
                ('muted', '=', True)]))
        except Exception:
            return False

    def _session_change_body(self):
        """通知正文：必须带 old→new 变更摘要（设计稿 §7.4#2）。"""
        self.ensure_one()
        lines = ['【调课通知】%s'
                 % (self.subject_id.name or self.name or '课节')]
        if self.batch_id:
            lines.append('班级：%s' % self.batch_id.name)
        when = _impact_when(self, self.start_datetime, self.end_datetime)
        if when:
            lines.append('时间：%s' % when)
        if self.faculty_id:
            lines.append('任课教师：%s' % self.faculty_id.name)
        if self.classroom_id:
            lines.append('教室：%s' % self.classroom_id.name)
        changes = self._impact_changes()
        if changes:
            lines.append('变更明细：%s' % '；'.join(
                '%s %s → %s' % (c['label'], c['old'], c['new'])
                for c in changes))
        else:
            lines.append('变更明细：本节暂无字段级变更留痕，请以课表最新安排为准。')
        if self.state == 'cancel':
            lines.append('本节已停课，请勿前往教室。')
        return '\n'.join(lines)

    def _notify_session_change(self, sender_uid=None):
        """一键通知（页面按钮与后台按钮共用同一实现）。

        - 收件人 = 任课教师 + 该班全部在读学生（复用 _reminder_users：
          student_ids 为空时按 op.student.course 的 batch 回退——本地库
          op_session_op_student_rel = 0 行，不回退就会静默发给 0 人）；
        - 失败不阻断、逐人计数（对齐 session_ext.py:243-293 的教训），
          并把「静音跳过」与「失败」分开数；
        - 留一条 edu.audit.log('课节变更通知')：页面的「最近一次通知：
          <时刻> · <人数> 人」与补发判定都由它回答（零新字段）。
        """
        self.ensure_one()
        users = self._reminder_users()
        body = self._session_change_body()
        sent = failed = muted = 0
        try:
            Msg = self.env['edu.message'].sudo()
        except Exception:
            Msg = None
            _logger.warning('调课通知：站内信模型不可用 session=%s',
                            self.id, exc_info=True)
        if users and Msg is None:
            failed = len(users)
        elif users:
            can_event = hasattr(Msg, '_notify_event')
            Pref = self.env['edu.notify.pref'].sudo() \
                if 'edu.notify.pref' in self.env else None
            for usr in users:
                ok = False
                try:
                    if can_event:
                        # 站内信主通道：带偏好静音（edu_portal 的 B5 引擎）
                        ok = bool(Msg._notify_event(
                            self.IMPACT_EVENT_KEY, usr, body,
                            sender_uid=sender_uid))
                    else:
                        Msg.create({
                            'sender_id': sender_uid or self.env.uid,
                            'recipient_id': usr.id,
                            'body': body[:2000],
                            'sent_at': fields.Datetime.now(),
                        })
                        ok = True
                except Exception:
                    ok = False
                    _logger.warning(
                        '调课通知：站内信发送失败 session=%s user=%s',
                        self.id, usr.id, exc_info=True)
                if ok:
                    sent += 1
                elif self._impact_is_muted(Pref, usr):
                    muted += 1
                else:
                    failed += 1
        detail = '通知 %d 人（静音跳过 %d · 失败 %d）' % (sent, muted, failed)
        try:
            self.env['edu.audit.log'].sudo()._log(
                self.IMPACT_NOTIFY_ACTION, 'op.session', self.id,
                self.name or '', detail)
        except Exception:
            _logger.warning('调课通知：审计写入失败 session=%s', self.id,
                            exc_info=True)
        return {'sent': sent, 'failed': failed, 'muted': muted,
                'total': len(users), 'body': body}

    # ------------------------------------------------------------------
    # 三、变更留痕（G3：改课写入点补审计；字段级留痕由 chatter 自动完成）
    # 可见范围 = 仅教务（/edu/audit，校长拍板 P3）
    # ------------------------------------------------------------------
    def write(self, vals):
        """在改课写入点补 edu.audit.log('课节变更'，old→new 摘要)。

        批量排课已有先例（controllers/main.py:475-477）；这里补齐「单节
        改课」这条真实最常用的路径（表单保存与日历拖拽都走它）。

        这里同时是「单节改课」的教师不可用拦截点（G4 §10.3）——与基座四查
        同形态：先查后写，命中即 ValidationError。
        """
        if [f for f in ('faculty_id', 'start_datetime', 'end_datetime')
                if f in vals]:
            Faculty = self.env['op.faculty'].sudo()
            for rec in self:
                faculty = Faculty.browse(vals['faculty_id'] or 0) \
                    if 'faculty_id' in vals else rec.faculty_id
                self._check_teacher_leave(
                    faculty,
                    _session_dt(vals.get('start_datetime')
                                or rec.start_datetime),
                    _session_dt(vals.get('end_datetime') or rec.end_datetime),
                    rec=rec)
        watched = [f for f in self.IMPACT_WATCH_FIELDS if f in vals]
        olds = {}
        if watched:
            for rec in self:
                olds[rec.id] = {f: rec[f] for f in watched}
        res = super().write(vals)
        if watched:
            self._impact_log_changes(olds, watched)
        return res

    def _impact_log_changes(self, olds, watched):
        """把本次写入的 old→new 记进审计（失败只告警、绝不阻断业务事务）。"""
        try:
            Audit = self.env['edu.audit.log'].sudo()
        except Exception:
            _logger.warning('课节变更：审计模型不可用', exc_info=True)
            return
        for rec in self:
            old = olds.get(rec.id) or {}
            parts = []
            for field_name in watched:
                before, after = old.get(field_name), rec[field_name]
                if _impact_same(before, after):
                    continue
                parts.append('%s：%s → %s' % (
                    rec.IMPACT_FIELD_LABELS.get(field_name, field_name),
                    _impact_field_text(rec, field_name, before),
                    _impact_field_text(rec, field_name, after)))
            if not parts:
                continue
            Audit._log(rec.IMPACT_CHANGE_ACTION, 'op.session', rec.id,
                       rec.name or '', '；'.join(parts)[:2000])

    # ------------------------------------------------------------------
    # 三点五、教师不可用（G4 §10.2–§10.4）
    # 判定只看教师登记过的例外；拦截与基座四查同形态（写时抛 ValidationError）。
    # ------------------------------------------------------------------
    def _teacher_leave_hits(self, faculty, start, end):
        """新时段撞到的教师个人例外（UTC naive 三元组列表）——判定唯一入口。"""
        if not (faculty and faculty.exists() and start and end):
            return []
        return faculty._leave_intervals_utc(start, end)

    def _teacher_leave_skipped(self):
        """逃逸口是否生效：context 键 + **仅教务组/系统组**（口径同 main.privileged_staff）。

        越权塞 context 不是「静默忽略」而是直接报错——否则门户用户加个键就能绕过。
        """
        if not self.env.context.get(self.SKIP_TEACHER_LEAVE_KEY):
            return False
        user = self.env.user
        if user.has_group('openeducat_core.group_op_back_office_admin') \
                or user.has_group('base.group_system'):
            return True
        raise ValidationError(_('只有教务处或系统管理员可以「忽略教师不可用」。'))

    def _log_teacher_leave_skip(self, faculty, start, end, hits, rec=None):
        """逃逸口被使用即留痕：审计原生记「谁/何时」，这里补「绕了哪一节」。"""
        detail = '绕过教师不可用：%s · 教师「%s」已登记 %s' % (
            _impact_when(self.env['op.session'], start, end),
            faculty.name or '',
            '、'.join('%s%s' % (
                _impact_when(self.env['op.session'], hit[0], hit[1]),
                '（%s）' % hit[2] if hit[2] else '') for hit in hits[:5]))
        try:
            self.env['edu.audit.log'].sudo()._log(
                self.TEACHER_LEAVE_ACTION, 'op.session',
                rec.id if rec else 0, (rec.name if rec else '') or '',
                detail[:2000])
        except Exception:
            _logger.warning('教师不可用：审计写入失败', exc_info=True)

    def _check_teacher_leave(self, faculty, start, end, rec=None):
        """新时段与教师已登记的例外相交 ⇒ ValidationError（与基座四查同形态）。

        逃逸口 = context[SKIP_TEACHER_LEAVE_KEY]（仅教务组/系统组），使用即写审计。
        """
        hits = self._teacher_leave_hits(faculty, start, end)
        if not hits:
            return
        if self._teacher_leave_skipped():
            self._log_teacher_leave_skip(faculty, start, end, hits, rec=rec)
            return
        detail = '、'.join('%s%s' % (
            _impact_when(self.env['op.session'], hit[0], hit[1]),
            '（%s）' % hit[2] if hit[2] else '') for hit in hits[:3])
        raise ValidationError(_(
            '教师「%s」已登记不可用时间：%s。请换时段或换教师；确需强行排课时，'
            '由教务处勾选「忽略教师不可用」（会在审计里留痕）。'
        ) % (faculty.name or '', detail))

    @api.model_create_multi
    def create(self, vals_list):
        """落库拦截（§10.3）：批量排课逐节走这里，命中者由调用方计入 failed。"""
        Faculty = self.env['op.faculty'].sudo()
        for vals in vals_list:
            self._check_teacher_leave(
                Faculty.browse(vals.get('faculty_id') or 0),
                _session_dt(vals.get('start_datetime')),
                _session_dt(vals.get('end_datetime')))
        return super().create(vals_list)

    def _impact_rule_notes(self):
        """影响面页「被规则限制」档（G3 §8.1）：不是与别的课节冲突，而是规则不让排。

        本节唯一可判的规则源 = 教师例外不可用（F-1）；停课日/周次范围/单双周是
        排课表单的参数，不属于某一节课的属性，故不在本页。
        未登记 ⇒ 可用，但**不静默**：给灰字提示（§10.4）。
        """
        self.ensure_one()
        notes = []
        faculty = self.faculty_id
        if not faculty:
            return notes
        if not faculty._has_leave_records():
            notes.append({'level': 'notice', 'text': self.TEACHER_LEAVE_NOTICE})
            return notes
        for hit in self._teacher_leave_hits(
                faculty, self.start_datetime, self.end_datetime):
            notes.append({
                'level': 'rule',
                'text': '教师不可用：教师「%s」已登记 %s%s，保存会被系统拦下。' % (
                    faculty.name or '',
                    _impact_when(self, hit[0], hit[1]),
                    '（%s）' % hit[2] if hit[2] else ''),
            })
        return notes

    @api.model
    def teacher_leave_roster(self, faculty_ids=None):
        """教师不可用登记名册（只读）——供 S2「排课完成度」看板算教师登记率。

        签名 teacher_leave_roster(self, faculty_ids=None)
          faculty_ids：可选的 op.faculty id 列表；缺省 = 全部教师
          返回 (rows, summary)：
            rows = [{faculty_id, faculty_name, resource_id, leave_count,
                     registered, placeholder}]
            summary = {total, registered, unregistered, rate}
                      （rate = 已登记 / 教师总数 的百分数整数，无教师为 0）
        零新字段：数据源就是 resource.calendar.leaves。
        """
        Faculty = self.env['op.faculty'].sudo()
        domain = [('id', 'in', list(faculty_ids))] if faculty_ids else []
        leaves = self.env['resource.calendar.leaves'].sudo()
        rows = []
        for faculty in Faculty.search(domain, order='name asc, id asc'):
            resource = faculty.resource_id
            count = leaves.search_count(
                [('resource_id', '=', resource.id)]) if resource else 0
            rows.append({
                'faculty_id': faculty.id,
                'faculty_name': faculty.name or '',
                'resource_id': resource.id if resource else 0,
                'leave_count': count,
                'registered': bool(count),
                'placeholder': faculty._is_placeholder(),
            })
        registered = len([row for row in rows if row['registered']])
        total = len(rows)
        return rows, {
            'total': total,
            'registered': registered,
            'unregistered': total - registered,
            'rate': int(round(100.0 * registered / total)) if total else 0,
        }

    # ------------------------------------------------------------------
    # 四、后台入口（表单上的两个按钮；不新增菜单，挂既有「时间表」应用）
    # ------------------------------------------------------------------
    def action_open_impact(self):
        """后台按钮：新窗口打开「改课影响面」页。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/timetable/session/%d/impact' % self.id,
            'target': 'new',
        }

    def action_notify_session_change(self):
        """后台按钮：一键通知（与页面按钮同一实现，少一次跳转）。"""
        self.ensure_one()
        res = self._notify_session_change()
        msg = '已通知 %d 人' % res['sent']
        if res['muted']:
            msg += '，静音跳过 %d 人' % res['muted']
        if res['failed']:
            msg += '，失败 %d 人' % res['failed']
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '调课通知',
                'message': msg,
                'type': 'warning' if res['failed'] else 'success',
                'sticky': False,
            },
        }

    # ------------------------------------------------------------------
    # 五、§18 各年级分开排（2026-09-18 校长裁定）
    #
    # 设计稿：docs/plans/scheduling-overhaul-design.md §18。
    # 校长原话：英语这类课「各上各的」（不是一起上）+「按年级重排」（不是脚本拆）。
    # 为什么不能脚本拆：基座 openeducat_timetable/models/timetable.py:243-337
    #   的教师维硬约束 —— 同一位教师同一时段重叠直接抛 ValidationError（§18.2）。
    #   所以正确做法 = 教务用工具重排（时间错开）+ 旧合班课时批量停用（不删行）。
    #
    # 影响面口径**复用 C-1**（_reminder_users：任课教师 + 该班在读学生，家长不发）。
    # 本段不触碰 edu_telegram / edu.telegram.outbox（退役件 + 生产同名不同物）。
    # ------------------------------------------------------------------
class OpBatchGradeSplit(models.Model):
    """op.batch 扩展：§18 合班批组成推导 + 影响面 + 批量停用（**零新表**）。

    推导规则（只认严格形状；认不出就返回空 ⇒ 页面显示「未推导出组成」，
    **绝不硬猜**）：
      · 合法代号形如 B1234 / A23 / A123B34 / A123+B34（字母 1-2 位 + 数字串，
        段间可有可无 + 号）；
      · 数字串逐位展开成单年级：B1234 → B1/B2/B3/B4；
      · 认不出的（含 -、字母超过 2 位、无字母）一律返回空列表。
    批名/代号自己编码了组成（B1234 的批名就是「B1-B4全体」），故可从 code
    推导；但**推导 != 事实** ⇒ 一律带 need_confirm=True，页面须显式标注。
    """

    _inherit = 'op.batch'

    _CODE_FULL_RE = re.compile(r'[A-Za-z]{1,2}\d+(\+?[A-Za-z]{1,2}\d+)*')
    _CODE_SEG_RE = re.compile(r'([A-Za-z]{1,2})(\d+)')

    def _deactivate_composition(self):
        """本班课时的「合班批 → 组成年级」推导（只读；显示用，需人工确认）。"""
        self.ensure_one()
        code = (self.code or '').strip()
        empty = {'code': code, 'is_combined': False, 'parts': [],
                 'parts_label': '', 'unknown': [], 'need_confirm': False}
        if not code or not self._CODE_FULL_RE.fullmatch(code):
            return empty
        tokens = []
        for letters, digits in self._CODE_SEG_RE.findall(code):
            for ch in digits:
                token = '%s%s' % (letters.upper(), ch)
                if token not in tokens:
                    tokens.append(token)
        Batch = self.env['op.batch'].sudo()
        parts = []
        for token in tokens:
            other = Batch.search(
                [('id', '!=', self.id), ('code', '=', token)],
                order='active desc, id asc', limit=1)
            parts.append({
                'code': token,
                'name': other.name or '',
                'batch_id': other.id or 0,
                'exists': bool(other),
                'active': bool(other.active) if other else False,
            })
        if len(parts) < 2:
            return empty
        return {
            'code': code,
            'is_combined': True,
            'parts': parts,
            'parts_label': '、'.join(p['code'] for p in parts),
            'unknown': [p['code'] for p in parts if not p['exists']],
            'need_confirm': True,
        }

    def _batch_deactivate_users(self, sessions):
        """一批课时的收件人并集（**复用 C-1 的 _reminder_users 口径**）。

        C-1 口径：任课教师 + 该班全部在读学生，家长不发；student_ids 为空时
        按 op.student.course 回退（本地库 op_session_op_student_rel 为 0 行，
        不回退就会静默算成 0 人 —— 这是 C-1 已经踩过的坑）。
        """
        users = self.env['res.users'].sudo()
        for ses in sessions:
            users |= ses._reminder_users()
        return users

    def _is_batch_faculty_user(self, sessions, user):
        """user 是否在这批课时的任课教师里（影响面的角色标注用）。

        先把这批课时的任课教师**一次性**换成账号集合再判：逐节调用会在
        filter 里产生「每节 1~2 条查询」（一批 72 节 = 上百条），没必要。
        """
        if not user:
            return False
        return user.id in users_of_profile(sessions.mapped('faculty_id')).ids

    def _batch_deactivate_impact(self):
        """批量停用的影响面（只读；请求时算，不落库、不新增字段）。

        看什么（复用 C-1 影响面页 §7.2/§7.3 的问法）：
          ① 会消失多少节、分几个科目、时间跨度多长；
          ② 会影响到谁（任课教师 + 在读学生，逐人列出）；
          ③ 已经停用过多少节（避免重复点后看不清真实影响）。
        """
        self.ensure_one()
        Session = self.env['op.session'].sudo()
        live = Session.search([
            ('batch_id', '=', self.id),
            ('state', '!=', 'cancel'),
        ], order='start_datetime asc, id asc')
        already = Session.search_count([
            ('batch_id', '=', self.id),
            ('state', '=', 'cancel'),
        ])
        users = self._batch_deactivate_users(live)
        faculty_users = users.filtered(
            lambda u: self._is_batch_faculty_user(live, u))
        by_subject = {}
        for ses in live:
            key = ses.subject_id.name or ses.name or '（未命名）'
            row = by_subject.setdefault(key, {
                'subject': key, 'count': 0, 'first': False, 'last': False})
            row['count'] += 1
            start = ses.start_datetime
            if start and (not row['first'] or start < row['first']):
                row['first'] = start
            if start and (not row['last'] or start > row['last']):
                row['last'] = start
        subjects = sorted(by_subject.values(), key=lambda r: -r['count'])
        for row in subjects:
            row['first_text'] = (
                _impact_when(self, row['first'], None) if row['first'] else '')
            row['last_text'] = (
                _impact_when(self, row['last'], None) if row['last'] else '')
        firsts = live[:1].mapped('start_datetime')
        lasts = live[-1:].mapped('start_datetime')
        recipients = [{
            'id': usr.id,
            'name': usr.name or usr.login or '',
            'login': usr.login or '',
            'role': '任课教师' if usr.id in faculty_users.ids else '在读学生',
        } for usr in users]
        return {
            'batch': self,
            'composition': self._deactivate_composition(),
            'session_count': len(live),
            'already_count': already,
            'subjects': subjects,
            'subject_count': len(subjects),
            'recipients': recipients,
            'recipient_count': len(recipients),
            'faculty_count': len(faculty_users),
            'student_count': len(recipients) - len(faculty_users),
            'first_text': _impact_when(self, firsts[0], None) if firsts else '',
            'last_text': _impact_when(self, lasts[0], None) if lasts else '',
            'can_deactivate': bool(len(live)),
        }

    def deactivate_batch_sessions(self):
        """批量停用本班全部未停用课时：只置 state='cancel'，**不删行**。

        返回 {'cancelled', 'already', 'total', 'detail'}。
        审计：写一条 edu.audit.log（动作名 '课节批量停用'，调用口径同 C-1）。
        逐节的字段级留痕由 C-1 的 write() 钩子自动补（state 在
        IMPACT_WATCH_FIELDS 里 ⇒ 每节再留一条 '课节变更'，两条留痕互补）。
        """
        self.ensure_one()
        Session = self.env['op.session'].sudo()
        live = Session.search([
            ('batch_id', '=', self.id),
            ('state', '!=', 'cancel'),
        ])
        already = Session.search_count([
            ('batch_id', '=', self.id),
            ('state', '=', 'cancel'),
        ])
        composition = self._deactivate_composition()
        if live:
            live.write({'state': 'cancel'})
        detail = '停用 %d 节 · 跳过已停用 %d 节' % (len(live), already)
        if composition.get('is_combined'):
            detail += ' · 推导组成：%s' % (composition.get('parts_label') or '')
        try:
            self.env['edu.audit.log'].sudo()._log(
                '课节批量停用', 'op.session', 0, self.name or '', detail)
        except Exception:
            _logger.warning('批量停用：审计写入失败 batch=%s', self.id,
                            exc_info=True)
        return {'cancelled': len(live), 'already': already,
                'total': len(live) + already, 'detail': detail}
