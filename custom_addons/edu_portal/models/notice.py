# -*- coding: utf-8 -*-
"""布告栏轻量模型。

社区版 OpenEduCat 没有布告栏（notice board）模型（企业版才有），
这里自建一个轻量模型支撑 /my/notice_board/notice 页面。
"""
import html
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# F4：公告定向人群（模板与公告共用一套选项）
NOTICE_AUDIENCE = [
    ('all', '全体'),
    ('student', '仅学生'),
    ('faculty', '仅教师'),
    ('parent', '仅家长'),
    ('staff', '仅教务/管理员'),
]


class EduNotice(models.Model):
    _name = 'edu.notice'
    _description = 'Notice Board Notice'
    _order = 'date desc, id desc'

    name = fields.Char('Title', required=True, size=256)
    content = fields.Text('Content')
    sender = fields.Char('Sender', size=128)
    date = fields.Date('Date', default=fields.Date.today)
    active = fields.Boolean('Active', default=True)
    # 类别：后台列表/表单与发布表单共用（v3 补回字段定义——
    # views/notice_admin.xml 一直在引用它，缺定义会让视图装载失败）
    category = fields.Char('类别', default='notice', index=True)
    # 4b：有效期——填写后公告在该日期之后自动从布告栏/横幅/搜索中消失
    date_until = fields.Date('有效期至',
                             help='留空长期有效；到期后自动不再展示')


    # 门户顶部公告横幅（对标 tokenrouter 式蓝底横幅；开关在后台/发布表单）
    banner_enabled = fields.Boolean('横幅展示', default=False, index=True,
                                    help='开启后本公告以蓝底横幅展示在门户页顶部')
    banner_badge = fields.Char('横幅徽标', size=64,
                               help='横幅左侧胶囊短文字，如：截止 8 月 31 日，留空不显示')
    banner_cta = fields.Char('横幅按钮文字', size=32, default='查看详情',
                             help='横幅右侧链接文字，留空用默认「查看详情」')
    banner_url = fields.Char('横幅链接', size=256,
                             help='点击横幅按钮打开的地址，留空打开布告详情页')
    banner_seq = fields.Integer('横幅排序', default=10,
                                help='多条横幅时数字小的先展示')

    # ---- F4：定时发布 + 定向人群 + 三通道 ----
    publish_at = fields.Datetime(
        '定时发布时间', index=True,
        help='留空=立即发布；到点由定时任务转为发布并推送通知')
    audience = fields.Selection(
        NOTICE_AUDIENCE, string='定向人群', default='all',
        help='用于选择站内信/邮件/Telegram 的收件人范围')
    channel_site = fields.Boolean('站内信', default=True)
    channel_email = fields.Boolean('邮件', default=False)
    channel_telegram = fields.Boolean(
        'Telegram', default=False,
        help='勾上后，发布时把公告发到《班务机器人》里勾了'
             '「接收网站公告」的群（后台：班务机器人 → 群与短名）。')
    template_id = fields.Many2one('edu.notice.template', '套用模板')

    def mark_read_for(self, user):
        """为指定用户记录已读（幂等）。v2-B5 未读引擎。"""
        self.ensure_one()
        Read = self.env['edu.notice.read'].sudo()
        rec = Read.search([('user_id', '=', user.id),
                           ('notice_id', '=', self.id)], limit=1)
        if rec:
            return rec
        try:
            with self.env.cr.savepoint():
                return Read.create({'user_id': user.id,
                                    'notice_id': self.id})
        except Exception:
            return Read.search([('user_id', '=', user.id),
                                ('notice_id', '=', self.id)], limit=1)


    # ------------------------------------------------------------------
    # F4：定时发布（ir.cron 记录见 views/notice_admin.xml）
    # ------------------------------------------------------------------
    @api.model
    def _cron_publish_scheduled(self):
        """到点发布：publish_at <= 现在 且未激活的公告 → 发布并推送。

        用 active 做「未发布」载体：布告栏列表读的是 active=True 的记录，
        因此定时公告在到点前不会提前出现在任何列表（无需改 batch2）。
        """
        now = fields.Datetime.now()
        due = self.sudo().search([
            ('active', '=', False),
            ('publish_at', '!=', False),
            ('publish_at', '<=', now)])
        for rec in due:
            rec.write({'active': True, 'date': rec.publish_at.date()})
            rec.write({'publish_at': False})
            rec._send_channels()
            self.env['edu.audit.log'].sudo()._log(
                '定时发布公告', 'edu.notice', rec.id, rec.name or '')
        if due:
            _logger.info('scheduled notices published: %s', len(due))
        return len(due)

    def _audience_users(self):
        """定向人群 → 门户/内部账号集合（不建自定义组，按身份表与基座组取）。"""
        self.ensure_one()
        env = self.env
        users = env['res.users'].sudo().browse()
        aud = self.audience or 'all'
        try:
            if aud in ('all', 'student'):
                users |= env['op.student'].sudo().search([]).mapped('user_id')
            if aud in ('all', 'parent'):
                users |= env['op.parent'].sudo().search([]).mapped('user_id')
        except Exception:
            _logger.warning('notice audience identity lookup failed id=%s',
                            self.id, exc_info=True)
        groups = []
        if aud in ('all', 'faculty'):
            groups.append('openeducat_core.group_op_faculty')
        if aud in ('all', 'staff'):
            groups.append('openeducat_core.group_op_back_office_admin')
            groups.append('base.group_system')
        for xmlid in groups:
            grp = env.ref(xmlid, raise_if_not_found=False)
            if grp:
                users |= grp.user_ids
        return users.filtered(lambda u: u.active)

    def _send_channels(self, users=None):
        """三通道推送（站内信/邮件/Telegram）；单通道失败不影响其它通道。"""
        self.ensure_one()
        users = users if users is not None else self._audience_users()
        body = '【公告】%s\n%s' % (
            self.name or '', (self.content or '')[:1500])
        if self.channel_site:
            for user in users:
                try:
                    self.env['edu.message']._notify_event(
                        'notice_publish', user, body)
                except Exception:
                    _logger.warning('notice site notify failed uid=%s',
                                    user.id, exc_info=True)
        if self.channel_email:
            emails = [e for e in users.mapped('email') if e]
            if emails:
                try:
                    mail = self.env['mail.mail'].sudo().create({
                        'subject': self.name or '公告',
                        'body_html': '<pre style="white-space:pre-wrap">'
                                     '%s</pre>' % html.escape(
                                         self.content or ''),
                        'email_to': ','.join(sorted(set(emails))),
                    })
                    mail.send()
                except Exception:
                    _logger.warning('notice email failed id=%s',
                                    self.id, exc_info=True)
        if self.channel_telegram:
            # 优先走《班务助手》的 Telegram 出网口（对接 a，2026-10-14）：
            # 学校自己的群登记在它自己的表里（后台：班务机器人 → 群与短名），
            # 只有勾了「接收网站公告」的群会收到。这里只按模型名探在不在，
            # 不写进依赖——班务助手卸掉也不会影响门户发布公告。
            handled = False
            if 'edu.tg.assist.bridge' in self.env:
                try:
                    sent, failed = self.env[
                        'edu.tg.assist.bridge'].sudo().push_site_notice(self)
                    handled = True
                    _logger.info(
                        'notice telegram via tg-assist id=%s sent=%s failed=%s',
                        self.id, sent, failed)
                except Exception:
                    _logger.warning(
                        'notice telegram via tg-assist failed id=%s',
                        self.id, exc_info=True)
            if not handled:
                # 旧路（诺亚 @qnj251079_bot）：op.telegram.chat → edu.telegram.outbox。
                # 生产上的 edu_telegram 是「意见箱版」，没有 op.telegram.chat 这个
                # 模型；这段只对还装着旧版教学 telegram 的部署有效，异常一律吞掉，
                # 绝不因为一个通道把公告发布拖垮。
                role_map = {'all': None, 'student': 'student',
                            'faculty': 'faculty', 'parent': 'parent',
                            'staff': 'admin'}
                try:
                    Chat = self.env['op.telegram.chat'].sudo()
                    domain = []
                    role = role_map.get(self.audience or 'all')
                    if role:
                        domain.append(('role', '=', role))
                    Out = self.env['edu.telegram.outbox'].sudo()
                    for chat in Chat.search(domain):
                        Out.enqueue(chat.chat_id, body[:2000])
                except Exception:
                    _logger.warning('notice telegram legacy failed id=%s',
                                    self.id, exc_info=True)
        return len(users)


class EduNoticeTemplate(models.Model):
    """公告模板（F4）：正文/前缀/默认人群与通道，发布时可一键套用。"""
    _name = 'edu.notice.template'
    _description = '公告模板'
    _order = 'sequence, id'

    name = fields.Char('模板名称', required=True, size=128)
    category = fields.Char('类别', size=64, default='notice')
    title_prefix = fields.Char(
        '标题前缀', size=64, help='套用后拼在标题前，例如「教务通知：」')
    content = fields.Text(
        '正文模板', help='可用占位符：{日期} {学生} {班级}，发布时替换')
    audience = fields.Selection(
        NOTICE_AUDIENCE, string='默认人群', default='all')
    channel_site = fields.Boolean('站内信', default=True)
    channel_email = fields.Boolean('邮件', default=False)
    channel_telegram = fields.Boolean('Telegram', default=False)
    sequence = fields.Integer('排序', default=10)
    active = fields.Boolean('启用', default=True)

    def render_content(self, **values):
        """占位符替换（未知占位符原样保留，避免误吞花括号）。"""
        text = self.content or ''
        for key, val in values.items():
            text = text.replace('{%s}' % key, str(val or ''))
        return text


class EduNoticeRead(models.Model):
    _name = 'edu.notice.read'
    _description = '布告已读记录'
    user_id = fields.Many2one(
        'res.users', string='用户', required=True,
        index=True, ondelete='cascade')
    notice_id = fields.Many2one(
        'edu.notice', string='布告', required=True,
        index=True, ondelete='cascade')
    read_date = fields.Date(string='阅读日期', default=fields.Date.today)

    # Odoo19 新约束 API
    _read_user_notice_uniq = models.Constraint(
        'UNIQUE (user_id, notice_id)',
        '同一名用户对同一布告只能有一条已读记录。')
