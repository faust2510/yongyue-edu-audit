# -*- coding: utf-8 -*-
"""资料下载中心 v2：两级文件夹 + 资料（可见范围）+ 下载审计。

管理台（/downloads/manage）供教务处/管理员在门户内自建文件夹、
批量上传/删除/移动；下载端 /downloads 按 audience 过滤。
"""
import base64

from odoo import api, fields, models
from odoo.exceptions import UserError


class EduDownloadCategory(models.Model):
    _name = 'edu.download.category'
    _description = '资料文件夹'
    _order = 'sequence, id'

    name = fields.Char('文件夹名称', required=True)
    parent_id = fields.Many2one(
        'edu.download.category', string='上级文件夹', index=True,
        ondelete='restrict',
        help='最多两级：只能挂在顶级文件夹下')
    description = fields.Char('描述')
    sequence = fields.Integer('排序', default=10)
    active = fields.Boolean('启用', default=True)

    file_count = fields.Integer(
        '资料数', compute='_compute_file_count')

    @api.constrains('parent_id')
    def _check_parent_depth(self):
        for rec in self:
            if rec.parent_id and rec.parent_id.parent_id:
                raise UserError('文件夹最多两级，不能再往深处挂。')

    def _compute_file_count(self):
        # Odoo19 _read_group 对 m2o groupby 返回 recordset 键，须按 .id 归一
        groups = self.env['edu.download.file'].sudo()._read_group(
            [('active', '=', True)], ['category_id'], ['__count'])
        counts = {row[0].id: row[1] for row in groups}
        for rec in self:
            rec.file_count = counts.get(rec.id, 0)

    def unlink(self):
        """非空文件夹禁止删除：先清空/移走资料与子文件夹。"""
        for rec in self:
            n_files = self.env['edu.download.file'].sudo().search_count(
                [('category_id', '=', rec.id)])
            n_children = self.search_count([('parent_id', '=', rec.id)])
            if n_files or n_children:
                raise UserError(
                    '「%s」里还有 %d 份资料、%d 个子文件夹，'
                    '请先清空或移动后再删除。'
                    % (rec.name, n_files, n_children))
        return super().unlink()


class EduDownloadFile(models.Model):
    _name = 'edu.download.file'
    _description = '下载资料'
    _order = 'category_id, name'

    name = fields.Char('标题', required=True)
    category_id = fields.Many2one(
        'edu.download.category', string='文件夹', required=True,
        ondelete='cascade')
    description = fields.Text('说明')
    file = fields.Binary('附件', required=True, attachment=True)
    file_name = fields.Char('文件名', readonly=True)
    active = fields.Boolean('启用', default=True)
    download_count = fields.Integer('下载次数', default=0, readonly=True)
    # 可见范围 v3（四组勾选；管理员恒可见可下）：
    # 公开=四组全勾；仅教务=教务处+教师；仅学生=只勾学生；排除某组=取消勾
    visible_registrar = fields.Boolean('教务处可见', default=True)
    visible_teacher = fields.Boolean('教师可见', default=True)
    visible_student = fields.Boolean('学生可见', default=True)
    visible_parent = fields.Boolean('家长可见', default=True)
    # v3 课程资料归属：非空 = 课程资料（按科目过滤）；空 = 行政表格。
    subject_id = fields.Many2one(
        'op.subject', string='所属科目', index=True, ondelete='set null',
        help='课程资料请选所属科目；行政/通用表格留空。')
    # v3 第五个可见维度：本课程学员（对齐 Odoo eLearning 的 Course Attendees）
    visible_course = fields.Boolean(
        '本课程学员可见', default=False,
        help='勾选后，选修了「所属科目」的学员可见（需先指定所属科目）。')

    _visibility_not_empty = models.Constraint(
        'CHECK (visible_registrar OR visible_teacher OR '
        'visible_student OR visible_parent OR visible_course)',
        '可见范围至少要勾选一个组。',
    )

    # ---- v3（t8）需确认已读：官方无此原语，自建确认表 ----
    # 范式参考：钉钉班级通知「已读未读一目了然」、飞书广播号「点击我已知悉」。
    # 依据 docs/research/onestop-learning-and-repetitive-work.md §4.4
    ack_mode = fields.Selection(
        [('none', '无需确认'),
         ('soft', '需确认（不阻断下载）'),
         ('hard', '需确认（确认后方可下载与预览）')],
        string='确认已读', default='none', required=True)
    ack_n = fields.Integer('已确认人数', compute='_compute_ack_n')
    # ---- v3（t8）有效期：国内钉盘/微盘/云文档均无此能力，需自建 ----
    publish_from = fields.Datetime(
        string='定时上架',
        help='到点自动上架；**触发一次后自动清空**（一次性触发器，'
             '否则手动停用过的文件会被反复复活）。')
    expire_at = fields.Datetime(
        string='有效期至', help='到期后由定时任务自动下架（active=False）。')
    expired_at = fields.Datetime(
        string='自动下架时间', readonly=True, copy=False)

    file_size = fields.Integer(
        '文件大小(字节)', compute='_compute_file_size', store=True)

    @api.depends('file')
    def _compute_file_size(self):
        for rec in self:
            # 存的是 base64 文本，解码后才是真实字节数（v1 误存 base64 长度）
            rec.file_size = len(base64.b64decode(rec.file or b'')) if rec.file else 0

    def _compute_ack_n(self):
        Ack = self.env['edu.download.ack'].sudo()
        for rec in self:
            rec.ack_n = Ack.search_count([('file_id', '=', rec.id)])

    # ---- v3（t8）需确认已读 ----
    def mark_ack(self, user):
        """记录一条已读回执；幂等（同人同资料只有一条），并发走 savepoint 兜底。"""
        self.ensure_one()
        Ack = self.env['edu.download.ack'].sudo()
        domain = [('file_id', '=', self.id), ('user_id', '=', user.id)]
        rec = Ack.search(domain, limit=1)
        if rec:
            return rec
        try:
            with self.env.cr.savepoint():
                return Ack.create({'file_id': self.id, 'user_id': user.id})
        except Exception:
            return Ack.search(domain, limit=1)

    def target_users(self):
        """应确认人群。

        口径决策（本仓自定，国内范式未定义发布者是否计入）：
        教务处/管理员**不计入**——他们是发布者，计入会让未读名单永远挂着管理员。
        课程资料（有 subject_id）：该科目在读学生 ∪ 该科目授课教师。
        行政表格（无 subject_id）：按四组可见范围取并集。
        """
        self.ensure_one()
        env = self.env
        users = env['res.users'].sudo()
        if self.subject_id:
            scs = env['op.student.course'].sudo().search(
                [('subject_ids', 'in', self.subject_id.id)])
            users |= scs.mapped('student_id').mapped('user_id')
            ses = env['op.session'].sudo().search(
                [('subject_id', '=', self.subject_id.id)])
            users |= ses.mapped('faculty_id').mapped('user_id')
            return users.filtered(lambda u: u.active)
        if self.visible_student:
            users |= env['op.student'].sudo().search(
                []).mapped('user_id')
        if self.visible_parent:
            users |= env['op.parent'].sudo().search([]).mapped('user_id')
        for flag, xmlid in (('visible_teacher',
                             'openeducat_core.group_op_faculty'),
                            ('visible_registrar',
                             'openeducat_core.group_op_back_office_admin')):
            if not getattr(self, flag):
                continue
            grp = env.ref(xmlid, raise_if_not_found=False)
            if grp:
                users |= env['res.users'].sudo().search(
                    [('group_ids', 'in', [grp.id])])
        return users.filtered(lambda u: u.active)

    def unacked_users(self):
        """未确认人群 = 应确认人群 − 已确认人群。"""
        self.ensure_one()
        acked = set(self.env['edu.download.ack'].sudo().search(
            [('file_id', '=', self.id)]).mapped('user_id').ids)
        return self.target_users().filtered(lambda u: u.id not in acked)

    @api.model
    def cron_expire_downloads(self):
        """每小时：到期自动下架 + 定时上架（一次性消费）。返回计数供干跑取证。

        幂等：下架只命中 active=True 的行；上架额外要求 expired_at 为空，
        保证已自动下架的资料不会被复活。
        """
        now = fields.Datetime.now()
        File = self.sudo()
        due = File.search([('expire_at', '!=', False),
                           ('expire_at', '<=', now),
                           ('active', '=', True)])
        due.write({'active': False, 'expired_at': now})
        ready = File.search([('publish_from', '!=', False),
                             ('publish_from', '<=', now),
                             ('active', '=', False),
                             ('expired_at', '=', False)])
        ready.write({'active': True, 'publish_from': False})
        return {'expired': len(due), 'published': len(ready)}

    def init(self):
        """升级修正：file_size 重算 + 旧 audience 三档等值迁移到四组勾选。

        迁移幂等条件：只处理仍处于“四组全勾”默认态的行（用户手动改过
        勾选的行不会再命中），旧 audience 列保留在表中不删。"""
        # savepoint 包裹：init 里任何失败都不得毒化升级事务
        # （曾因废弃列已删 + bare except 吞错导致事务中止、registry 加载失败）
        try:
            with self.env.cr.savepoint():
                # v3：可见范围约束扩到第五维（本课程学员）。Odoo 只「新增
                # 缺失的」同名 SQL 约束、不替换旧定义；不先 DROP 的话旧的
                # 四维 CHECK 会继续拦「只勾本课程学员」的行。先 DROP 再 ADD，
                # 结果与执行顺序无关（init 早于/晚于 _add_sql_constraints
                # 都得到同一终态）。
                cr = self.env.cr
                cr.execute("""
                    SELECT 1 FROM information_schema.columns
                     WHERE table_name = 'edu_download_file'
                       AND column_name = 'visible_course'""")
                if cr.fetchone():
                    cr.execute('ALTER TABLE edu_download_file DROP '
                               'CONSTRAINT IF EXISTS '
                               'edu_download_file_visibility_not_empty')
                    cr.execute(
                        'ALTER TABLE edu_download_file ADD CONSTRAINT '
                        'edu_download_file_visibility_not_empty CHECK '
                        '(visible_registrar OR visible_teacher OR '
                        'visible_student OR visible_parent OR '
                        'visible_course)')
                recs = self.search([('file', '!=', False)])
                if recs:
                    self.env.add_to_compute(self._fields['file_size'], recs)
                    self.env.flush_all()
                cr = self.env.cr
                # 旧 audience 列在字段移除后的某次升级会被 Odoo 清理，
                # 迁移前先确认列仍在（全新库/已迁移库都自然跳过）
                cr.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'edu_download_file' "
                    "AND column_name = 'audience'")
                if cr.fetchone():
                    cr.execute("""
                        UPDATE edu_download_file
                           SET visible_teacher = TRUE, visible_student = FALSE,
                               visible_parent = FALSE
                         WHERE audience = 'staff'
                           AND visible_registrar AND visible_teacher
                           AND visible_student AND visible_parent
                    """)
                    cr.execute("""
                        UPDATE edu_download_file
                           SET visible_teacher = FALSE, visible_registrar = FALSE
                         WHERE audience = 'student'
                           AND visible_registrar AND visible_teacher
                           AND visible_student AND visible_parent
                    """)
                    # audience='all' → 保持四组全勾，无需 UPDATE
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _dedup_name(self, category_id, name):
        """同文件夹下同名追加 (2)/(3)…，供批量上传防撞名。"""
        File = self.env['edu.download.file'].sudo()
        base_names = set(File.search([
            ('category_id', '=', category_id)]).mapped('name'))
        if name not in base_names:
            return name
        stem, dot, ext = name.rpartition('.')
        if not dot:
            stem, ext = name, ''
        n = 2
        while True:
            cand = '%s (%d)%s' % (stem, n, ('.' + ext) if ext else '')
            if cand not in base_names:
                return cand
            n += 1

    def action_download(self):
        """后台清单/表单快捷下载（可选）。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/downloads/file/%d' % self.id,
            'target': 'self',
        }


class EduDownloadAck(models.Model):
    """资料已读回执（v3 t8 自建）。

    Odoo 与 Moodle 核心均无「需确认已读」原语（调研 §3/§4.4 已核实），
    故自建确认表；形状照抄既有 EduNoticeRead（user_id + 父对象 + 日期 +
    UNIQUE），只把父对象换成 edu.download.file。
    """
    _name = 'edu.download.ack'
    _description = '资料已读回执'
    _order = 'ack_date desc, id desc'

    file_id = fields.Many2one(
        'edu.download.file', string='资料', required=True,
        ondelete='cascade', index=True)
    user_id = fields.Many2one(
        'res.users', string='确认人', required=True,
        ondelete='cascade', index=True)
    ack_date = fields.Datetime(
        string='确认时间', default=fields.Datetime.now, required=True)

    # Odoo19 新约束 API（旧 _sql_constraints 会被静默忽略）
    _ack_user_file_uniq = models.Constraint(
        'UNIQUE (user_id, file_id)', '同一用户对同一资料只能确认一次。')


class EduDownloadLog(models.Model):
    _name = 'edu.download.log'
    _description = '资料下载记录（审计）'
    _order = 'create_date desc, id desc'

    file_id = fields.Many2one(
        'edu.download.file', string='资料', required=True,
        ondelete='cascade', index=True)
    user_id = fields.Many2one(
        'res.users', string='下载人', required=True, index=True,
        default=lambda self: self.env.uid)

    def _log_download(self, file_id):
        """同人同文件同日只记一条；计数仍在 file.download_count 累计。"""
        day_start = fields.Datetime.start_of(
            fields.Datetime.now(), 'day')
        if self.search_count([
                ('file_id', '=', file_id),
                ('user_id', '=', self.env.uid),
                ('create_date', '>=', day_start)]):
            return
        self.create({'file_id': file_id})
