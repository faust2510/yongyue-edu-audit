# -*- coding: utf-8 -*-
"""灵命生活：打卡类型定义。

edu.checkin.type：可配置的打卡项（读经/灵修/周记……），支持 daily/weekly
两种频率；weekly 类型带每周目标次数与截止星期（0=周日 …… 6=周六）。
"""
import datetime
import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# 截止星期取值口径：0=周日、1=周一 …… 6=周六
DEADLINE_WEEKDAY_NAMES = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

# ---------------------------------------------------------------------------
# 演示数据的确定性锁（t12 / F4）—— 修的是什么
# ---------------------------------------------------------------------------
# 历史问题：`_load_demo_records()` 原来按“今天”取**滚动 7 天窗口**
# （读经 range(0,7)、灵修 range(1,7)），进来一天窗口就往前挪一天
# ⇒ 每次 `-u edu_life` 都会把“窗口里还没有的那几天”再补一遍，
# 演示数据越滚越多（2026-09-17 实测一次 `-u edu_life` 就写了 9 条，
# ids 53–61，写入者 __system__、同一秒）。而且它写的是**业务表**、
# **不带【演示】标记**，与真实打卡混同一张表（认定只能靠
# uid/create_date/student 反推）。
#
# 现在的三件套及其分工（请勿只修其一）：
#   1) **一次性开关**（DEMO_SEED_KEY）：记“哪些演示学生已播种”。
#      这是“**任何次数的升级都不再改计数**”的**唯一硬保证**；
#      按 student_id 存而不是布尔，语义是“**每个演示学生只播一次**”
#      （将来新增演示学生也能各自播一次，不会漏、也不会重复）。
#   2) **固定绝对窗口**（_demo_window）：决定首次播种写哪些日期。
#      **绝对日期、不随日历漂移**；一旦存进开关，就永远只认它。
#   3) **兜底**：若开关被清，但该学生在窗口内**已有任意一行**
#      打卡或周记 ⇒ **整段跳过**，防“开关没了就又补一批”。
#
# 行标识规则（供后人反查，不回填历史行）：
#   **凡本函数写入的打卡行，`note` 一律以【演示】开头**；t12 之前的历史行
#   不在规则内，按 id/时间戳清单识别（如 id 53–61）。
DEMO_SEED_KEY = 'edu_life.demo_checkin_seed'

# “到堂打卡”类型的唯一口径（t13 / F3）。
# 取值必须与 t5 迁移脚本（scripts/merge_checkins.py）一致，否则新库自带的这条
# 会与脚本 get-or-create 出来的那条长不一样（同名不同字段 ⇒ 两条）。
ATTEND_TYPE_NAME = '到堂打卡'
ATTEND_TYPE_LABEL = '到堂打卡'
ATTEND_TYPE_FREQUENCY = 'daily'
ATTEND_TYPE_WEEKLY_TARGET = 1
ATTEND_TYPE_DEADLINE_WEEKDAY = 0
ATTEND_TYPE_SEQUENCE = 5
ATTEND_TYPE_ICON = 'fa-check-circle-o'
ATTEND_TYPE_DESCRIPTION = ('每日到堂打卡（由 edu_portal 旧“每日打卡”到堂维度并入）。')
DEMO_NOTE_PREFIX = '【演示】'


class EduCheckinType(models.Model):
    _name = 'edu.checkin.type'
    _description = '打卡类型'
    _order = 'sequence, id'

    name = fields.Char(string='名称', required=True)
    label = fields.Char(string='显示标签', required=True,
                        help='门户展示名称；演示数据统一以【演示】结尾。')
    description = fields.Text(string='说明')
    frequency = fields.Selection(
        [('daily', '每日'), ('weekly', '每周')],
        string='频率', required=True, default='daily')
    weekly_target = fields.Integer(string='每周目标次数', default=1,
                                   help='weekly 频率时每周期望完成的打卡次数。')
    deadline_weekday = fields.Integer(
        string='截止星期（0=周日）', default=0,
        help='0=周日、1=周一……6=周六；如周记每周日截止则填 0。')
    sequence = fields.Integer(string='序号', default=10)
    active = fields.Boolean(string='启用', default=True)
    icon = fields.Char(string='门户图标', default='fa-check-circle-o',
                       help='Font Awesome 类名（如 fa-book），门户卡片展示用。')

    # ------------------------------------------------------------------
    # “到堂打卡”类型：模块自带（t13 / F3 未闭合项）
    # ------------------------------------------------------------------

    @api.model
    def _ensure_attend_checkin_type(self):
        """get-or-create “到堂打卡”（模块 data 的 <function> 调用）。

        为什么不能用固定 xmlid 直接 create：老库里这条类型是 t5 迁移脚本
        get-or-create 出来的（本库 id=5），并没有对应的 ir_model_data 行；
        若用固定 xmlid 直接建，会在这种库上**造出第二条同名类型**。
        所以只能按 `name` 先查：命中就复用（并把缺失的展示字段补齐），
        缺失才新建。**不刷新业务字段**（不改 name/active）；若该行被
        后台改名过，本函数会再建一条——那是有意的取舍：宁可
        多一条同名配置，也不拿用户改过的配置去冒名覆盖。
        """
        Type = self.env['edu.checkin.type'].sudo()
        rec = Type.search([('name', '=', ATTEND_TYPE_NAME)], limit=1)
        if rec:
            patch = {}
            if not rec.icon:
                patch['icon'] = ATTEND_TYPE_ICON
            if patch:
                rec.write(patch)
            _logger.info(
                'edu_life 到堂类型已存在：id=%s（复用，不新建）' % rec.id)
            return rec
        try:
            with self.env.cr.savepoint():
                rec = Type.create({
                    'name': ATTEND_TYPE_NAME,
                    'label': ATTEND_TYPE_LABEL,
                    'frequency': ATTEND_TYPE_FREQUENCY,
                    'weekly_target': ATTEND_TYPE_WEEKLY_TARGET,
                    'deadline_weekday': ATTEND_TYPE_DEADLINE_WEEKDAY,
                    'sequence': ATTEND_TYPE_SEQUENCE,
                    'icon': ATTEND_TYPE_ICON,
                    'active': True,
                    'description': ATTEND_TYPE_DESCRIPTION,
                })
        except Exception:      # noqa: BLE001  竞态：别人刚好建了 ⇒ 重查
            rec = Type.search([('name', '=', ATTEND_TYPE_NAME)], limit=1)
            if not rec:
                raise
        _logger.info('edu_life 到堂类型已新建：id=%s' % rec.id)
        return rec
    def deadline_display(self):
        """截止星期的中文展示（QWeb 内不做逻辑，Python 预先算好）。"""
        self.ensure_one()
        if self.deadline_weekday < 0 or self.deadline_weekday > 6:
            return '-'
        return DEADLINE_WEEKDAY_NAMES[self.deadline_weekday]

    # ------------------------------------------------------------------
    # 演示数据：确定性播种（t12 / F4）
    # ------------------------------------------------------------------

    @api.model
    def _demo_window(self):
        """演示窗口 = **上一个完整的 ISO 周**（周一到周日），返回 (start, end, week_key)。

        为什么不用“今天往前 7 天”：那是**滚动窗口**，每过一天窗口
        就往前挪一天，于是每次升级都会补一批新日期——这正是 F4 的病因。
        改成“已结束的这一周”后，**同一周内任意次数、任意日期跑出来的
        窗口都一模一样**（只在周一跨界时才会变，而变了也不会再写，见开关）；
        周记的 `week` 字段也恰好就是这个完整周的 ISO 周次，不再出现“窗口跨周而
        周次取上一周”的错配。
        """
        today = datetime.date.today()
        end = today - datetime.timedelta(days=today.weekday() + 1)  # 上周日
        start = end - datetime.timedelta(days=6)                    # 上周一
        iso_year, iso_week = start.isocalendar()[:2]   # 周次取周一（ISO 周归属周一头），不是周日
        return start, end, '%04d-W%02d' % (iso_year, iso_week)

    @api.model
    def _demo_seeded_map(self):
        """读开关：{学生 id -> 播种记录}。值不是合法 JSON 时当空处理并记日志。"""
        raw = self.env['ir.config_parameter'].sudo().get_param(DEMO_SEED_KEY, '')
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            _logger.warning('演示播种开关 %s 不是合法 JSON，按未播种处理：%r'
                            % (DEMO_SEED_KEY, raw[:120]))
            return {}
        return data if isinstance(data, dict) else {}

    @api.model
    def _load_demo_records(self):
        """由 data/demo_life.xml 的 <function> 调用：为演示学生播一段确定的演示打卡与周记。

        行为口径（修改前必读）：
          - **首次**（学生不在开关里）：窗口 = 上一个完整 ISO 周（周一到周日）；
            按 (学生, 类型, 日期) 逐键查重后补齐缺口，写入行一律带
            【演示】前缀；周记按 (student, week) 查重后补一篇；最后把**该学生**
            记入开关。
          - **之后任意次升级**：该学生已在开关里 ⇒ **直接跳过**（不查日期、
            不写任何东西）。这是“任意次数升级都不再改计数”的唯一硬保证。
          - **开关被清后又跑**：若该学生在窗口内**已有任意一行**打卡或
            周记 ⇒ **整段跳过**（兜底）；否则才重新播种并重置开关。

        红线：不删除任何行，不回填历史行（t12 之前的演示行按 id/时间戳清单识别）。
        """
        student = self.env['op.student'].sudo().search(
            [('user_id.login', '=', 'stu@local')], limit=1)
        if not student:
            _logger.info(
                'edu_life 演示数据跳过：未找到 stu@local 关联的 op.student')
            return
        start, end, week_key = self._demo_window()
        window = (start.isoformat(), end.isoformat())
        seeded = self._demo_seeded_map()
        key = str(student.id)
        if seeded.get(key):
            _logger.info(
                'edu_life 演示数据跳过：学生 %s 已播种（窗口 %s..%s，%s）'
                % (student.id, window[0], window[1],
                   (seeded.get(key) or {}).get('seeded_on', '?')))
            return

        Record = self.env['edu.checkin.record'].sudo()
        Journal = self.env['edu.journal.entry'].sudo()
        # 兜底：窗口内已有任一行打卡或周记 ⇒ 整段跳过（防“开关没了又补一批”）
        has_rows = bool(Record.search_count([
            ('student_id', '=', student.id),
            ('checkin_date', '>=', start),
            ('checkin_date', '<=', end),
        ]) or Journal.search_count([
            ('student_id', '=', student.id),
            ('week', '=', week_key),
        ]))
        if has_rows:
            _logger.info(
                'edu_life 演示数据跳过：窗口 %s..%s 内已有记录（兜底命中）'
                % window)
            return

        today = datetime.date.today()
        bible = self.env.ref('edu_life.checkin_type_bible')
        devotion = self.env.ref('edu_life.checkin_type_devotion')
        note = '%s固定窗口 %s..%s' % (DEMO_NOTE_PREFIX, window[0], window[1])
        created = 0
        days = [start + datetime.timedelta(days=i) for i in range(7)]
        for type_rec in (bible, devotion):
            for day in days:
                if day > today:
                    continue
                if Record.search_count([
                        ('student_id', '=', student.id),
                        ('type_id', '=', type_rec.id),
                        ('checkin_date', '=', day)]):
                    continue
                Record.create({
                    'student_id': student.id,
                    'type_id': type_rec.id,
                    'checkin_date': day,
                    'note': note,
                })
                created += 1

        journal_created = False
        if not Journal.search_count([('student_id', '=', student.id),
                                     ('week', '=', week_key)]):
            admin = self.env.ref('base.user_admin', raise_if_not_found=False)
            Journal.create({
                'student_id': student.id,
                'week': week_key,
                'title': '在忙碌中保持安静【演示】',
                'content': (
                    '这一周课业比较紧张，但我仍然坚持每天早晨读一章经文。'
                    '最触动我的一句话是：得力在乎平静安稳。\n'
                    '（本篇为系统生成的演示数据）'),
                'state': 'reviewed',
                'feedback': '写得很真诚，继续保持每日灵修与记录的习惯，加油！【演示】',
                'reviewer_id': admin.id if admin else self.env.user.id,
            })
            journal_created = True

        seeded[key] = {
            'seeded_on': today.isoformat(),
            'window': list(window),
            'week': week_key,
            'created': created,
            'journal_created': journal_created,
            'seeded_by': '演示播种（t12）',
        }
        self.env['ir.config_parameter'].sudo().set_param(
            DEMO_SEED_KEY, json.dumps(seeded, ensure_ascii=False, sort_keys=True))
        _logger.info(
            'edu_life 演示数据已播种：学生 %s，窗口 %s..%s，打卡 +%s 条，周记 %s'
            % (student.id, window[0], window[1], created,
               '补一篇' if journal_created else '已存在，跳过'))
