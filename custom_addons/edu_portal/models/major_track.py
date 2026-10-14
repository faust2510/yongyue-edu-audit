# -*- coding: utf-8 -*-
"""专业编排（学制 + 必修/选修）—— 模型层。

设计：docs/plans/major-track-elective-design.md（校长四轮拍板定稿）
  §5   学制复用基座 op.program.level（不新建表、不走 op.program 中间层）
  §6.2 关系表 edu.course.subject（单一事实源）+ op.course 兼容层
  §6.3 subject_ids 必须**保留原名**改成非存储 computed M2M + inverse + search
  §6.5 报课页读取口径：两级 fallback（专业行值 → 科目全局值），学制不参与判定

三条不可动摇的约束（违者是静默数据损坏，见设计 §6.1/§6.3）
--------------------------------------------------------------
1. **绝不**把 `op.course.subject_ids` 改挂到新关系表上当普通 M2M：
   普通 M2M 的 `[(6, 0, ids)]` 会 **DELETE 全表再 INSERT**，把教务已配好的
   `subject_type` 逐行重置（Odoo 19 运行时源码：odoo/orm/models.py:4490-4501 /
   :4661-4733、fields.py:1930-1932；内核同型先例 res.users.all_group_ids）。
2. `_inverse_subject_ids` 只做「删多余 / 增缺失 / 其余行一条不动」——
   已配的行**连 write 都不发**，subject_type 因此原样保住。
3. `edu.course.subject.subject_type` **不 required、无 default、可空**；
   空值 = 继承科目的全局 subject_type。迁移过来的 334 行全部留空 ⇒ 教务零重配。
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

# 「必修/选修」的界面用词（与车门户 enroll.py 的 _SUBJECT_TYPE_LABEL 同源同义）
SUBJECT_TYPE_LABEL = {'compulsory': '必修', 'elective': '选修'}

# 两级 fallback 的最后兜底：宁可当必修，不静默丢课（S.subject_type 本身是
# required + default='compulsory'，理论上到不了这一层）。
FALLBACK_TYPE = 'compulsory'


class EduCourseSubject(models.Model):
    """专业 × 科目：该专业规定哪些科目必修 / 哪些选修（单一事实源）。"""

    _name = 'edu.course.subject'
    # mail.thread：设计 §6.2.1 要求 course_id/subject_id 带 tracking（谁改了哪一行留痕）；
    # 没有 mail.thread 时 Odoo 会**静默忽略** tracking 参数（装载期 WARNING
    # "unknown parameter 'tracking'"）⇒ 这里按设计补上，并把真正要留痕的那一格
    # subject_type（必修↔选修）也开 tracking。
    _inherit = ['mail.thread']
    _description = '专业科目配置（必修/选修）'
    _rec_name = 'subject_id'
    _order = 'sequence, id'

    course_id = fields.Many2one(
        'op.course', '专业', required=True, ondelete='cascade',
        index=True, tracking=True)
    subject_id = fields.Many2one(
        'op.subject', '科目', required=True, ondelete='restrict', index=True,
        tracking=True)
    # ⚠ 可空是本设计的支点：空 = 继承 op.subject.subject_type（全局默认值）
    subject_type = fields.Selection(
        [('compulsory', '必修'), ('elective', '选修')], '必修/选修',
        tracking=True,
        help='留空 = 继承「科目」自身的必修/选修默认值（科目表单上的那个字段）。')
    sequence = fields.Integer('排序', default=10)

    # 后台清单的只读辅助列（非存储，供教务一眼看出「这行现在算必修还是选修」）
    subject_code = fields.Char(
        '科目代码', related='subject_id.code', readonly=True)
    # ⚠ related 字段**不能**再写 selection 列表（Odoo 忽略并告警：selection
    # attribute will be ignored as the field is related）—— 选项自动继承目标字段。
    global_subject_type = fields.Selection(
        related='subject_id.subject_type', string='科目默认值', readonly=True,
        help='科目自身（全局）的必修/选修值。行上的「必修/选修」留空时按本值执行。')
    effective_type_label = fields.Char(
        '实际生效', compute='_compute_effective_type_label')

    _edu_course_subject_uniq = models.Constraint(
        'unique(course_id, subject_id)',
        '同一专业下的一门科目只能配置一行（必修/选修只配一次）。')

    @api.depends('subject_type', 'subject_id.subject_type')
    def _compute_effective_type_label(self):
        for rec in self:
            t = rec.subject_type or rec.subject_id.subject_type or FALLBACK_TYPE
            rec.effective_type_label = SUBJECT_TYPE_LABEL.get(t, t)


class OpCourse(models.Model):
    """专业（op.course）的编排面：学制 + 科目清单（必修/选修）+ 兼容层。"""

    _inherit = 'op.course'

    edu_level_id = fields.Many2one(
        'op.program.level', '学制', ondelete='restrict', tracking=True,
        help='本科 / 专科 / 硕士…（字典由「学制」菜单维护；可停用不可误删）')
    subject_line_ids = fields.One2many(
        'edu.course.subject', 'course_id', string='科目与必修/选修')

    # ------------------------------------------------------------------
    # 兼容层：名字 / 类型 / 语义三者都没变，只把存储换到 edu_course_subject。
    # 既有 19 个消费点（设计 §6.3.1）里 17 条一行都不用改。
    # ------------------------------------------------------------------
    subject_ids = fields.Many2many(
        'op.subject', string='Subject(s)',
        compute='_compute_subject_ids',
        inverse='_inverse_subject_ids',
        search='_search_subject_ids',
        store=False)

    @api.depends('subject_line_ids.subject_id')
    def _compute_subject_ids(self):
        for rec in self:
            rec.subject_ids = rec.subject_line_ids.subject_id

    def _inverse_subject_ids(self):
        """只做「删多余 / 增缺失 / 其余行一条不动」。

        ⚠ 已存在的行**绝不 write**：一旦碰它，教务配好的 subject_type
        就会被覆盖成新值（那就是设计 §6.1 要杜绝的静默数据损坏）。
        不 sudo() ⇒ 教师写 subject_ids 会在建/删行时撞 AccessError 并整体回滚
        （edu.course.subject 的 ACL 只给教务与系统管理员，设计 §6.7 / V6.3）。
        """
        Line = self.env['edu.course.subject']
        for rec in self:
            wanted = set(rec.subject_ids.ids)
            lines = rec.subject_line_ids
            to_remove = lines.filtered(
                lambda l: l.subject_id.id not in wanted)
            if to_remove:
                to_remove.unlink()
            kept = {l.subject_id.id for l in (lines - to_remove)}
            missing = [sid for sid in wanted if sid not in kept]
            if missing:
                Line.create([{'course_id': rec.id, 'subject_id': sid}
                             for sid in missing])

    @api.model
    def _search_subject_ids(self, operator, value):
        """非存储计算字段进 domain 必走 search（fields.py:1930-1932）。"""
        return [('subject_line_ids.subject_id', operator, value)]

    # ------------------------------------------------------------------
    # 报课页口径（设计 §6.5）：一个 helper，多处调用 —— 页面显示与服务端
    # 「必修全量补齐」必须同源，否则会出现「页面显示选修、服务端按必修补齐」。
    # ------------------------------------------------------------------
    def edu_effective_type(self, subject):
        """该专业下某科目的有效必修/选修（两级 fallback，学制不参与判定）。

        ① 专业行存在且 subject_type 非空 → 行值
        ② 否则                          → 科目自身的 subject_type
        ③ 兜底                          → compulsory（宁可当必修，不静默丢课）
        """
        self.ensure_one()
        sid = subject.id if hasattr(subject, 'id') else int(subject)
        line = self.subject_line_ids.filtered(
            lambda l: l.subject_id.id == sid)[:1]
        if line and line.subject_type:
            return line.subject_type
        s = self.env['op.subject'].sudo().browse(sid)
        return s.subject_type or FALLBACK_TYPE

    def edu_subject_pool(self):
        """报课页科目池（一次查询取全部行，避免 N+1）。

        返回的 dict 与 enroll.py 原有口径同形；学分/容量/先修阻断仍由
        enroll.py 的 edu.subject.prereq 逻辑填（本设计不碰先修/学分/容量），
        这里只负责「哪些科目 + 每门算必修还是选修」。
        """
        self.ensure_one()
        types = {l.subject_id.id: l.subject_type
                 for l in self.subject_line_ids if l.subject_type}
        rows = []
        for s in self.subject_ids:
            if not s.active:
                continue
            t = types.get(s.id) or s.subject_type or FALLBACK_TYPE
            rows.append({
                'id': s.id,
                'subject': s,
                'name': s.name or '',
                'code': s.code or '',
                'type': SUBJECT_TYPE_LABEL.get(t, t),
                'type_key': t,
                'type_label': SUBJECT_TYPE_LABEL.get(t, t),
                'compulsory': t == 'compulsory',
                'credit': getattr(s, 'credit_points', 0) or 0,
                'capacity': getattr(s, 'capacity', 0) or 0,
                'enrolled': 0,
                'blockers': [],
                'blocked': False,
            })
        return rows

    def edu_compulsory_subject_ids(self):
        """该专业的必修科目 id（服务端「必修全量补齐」口径，与页面同源）。

        口径 = 科目池（active）里 edu_effective_type == compulsory 的那些
        —— 与 enroll.py:235-236 原来的 pool.filtered(...) 逐位等价。
        """
        self.ensure_one()
        pool = self.subject_ids.filtered(lambda s: s.active)
        return pool.filtered(
            lambda s: self.edu_effective_type(s) == 'compulsory').ids


class OpSubject(models.Model):
    """科目（op.subject）真删护栏（设计 §6.2.1：被专业引用的科目不能真删）。

    FK 已设 ondelete='restrict'（数据库层挡住），这里补的是**人话错误 + 替代方案**：
    否则教务删科目时看到的是一句 psycopg2 外键报错。
    """

    _inherit = 'op.subject'

    def unlink(self):
        for rec in self:
            used = self.env['edu.course.subject'].sudo().search_count(
                [('subject_id', '=', rec.id)])
            if used:
                raise UserError(
                    '科目「%s」已被 %d 个专业编入（必修/选修配置），不能删除。\n\n'
                    '请改为「停用」：学生已修/在读记录不受影响，'
                    '新的专业编排与报课不再出现该科目。' % (rec.name, used))
        return super().unlink()


class OpProgramLevel(models.Model):
    """学制（op.program.level）的必要补偿：软删 + 排序（设计 §5.4）。

    基座这张表**没有 active**（program.py:46-54 通读确认），而本仓红线是
    零业务记录删除、且 edu_level_id 是 ondelete='restrict' ⇒ 一条被专业引用的
    学制删不掉；再不给「停用」，教务加错了就无路可走。
    ⚠ Odoo 19 的归档动作**只在视图含 active 字段时**才出现 ⇒ 列表与表单两处都要暴露
      （views/major_track_views.xml）。
    """

    _inherit = 'op.program.level'

    active = fields.Boolean('启用', default=True)
    sequence = fields.Integer('排序', default=10)
    course_count = fields.Integer('专业数', compute='_compute_course_count')

    def _compute_course_count(self):
        Course = self.env['op.course'].sudo().with_context(active_test=False)
        for rec in self:
            rec.course_count = Course.search_count(
                [('edu_level_id', '=', rec.id)])

    def unlink(self):
        """被专业引用的学制不许删（给出可执行的替代方案：停用）。"""
        for rec in self:
            used = self.env['op.course'].sudo().with_context(
                active_test=False).search_count([('edu_level_id', '=', rec.id)])
            if used:
                names = ', '.join(self.env['op.course'].sudo()
                                  .with_context(active_test=False)
                                  .search([('edu_level_id', '=', rec.id)],
                                          limit=3).mapped('name'))
                raise UserError(
                    '学制「%s」已被 %d 个专业使用（%s…），不能删除。\n\n'
                    '请改为「停用」：已用它的专业不受影响，新建专业时不再出现该选项。'
                    % (rec.name, used, names))
        return super().unlink()
