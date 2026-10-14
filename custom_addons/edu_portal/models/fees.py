# -*- coding: utf-8 -*-
"""财务总账 + 报销：学坊自建「应收/应付双向」账单/流水。

三期（docs/plans/ledger-design.md）在不新建模块前提下，把既有
edu.fee.bill（统筹费应收，fees-design.md）扩展为双向台账：
- direction=receivable（应收：统筹费/罚款/教材，默认值=旧单全兼容）
- direction=payable（应付：报销付款单/手工应付）；其中报销单另有
  reimburse_state 两段式状态机：request → approved → paid 或
  request → refused，approved_amount 为教务同意的金额（可改）。
门户只读（deny-by-default），学生/教师只能发起报销申请（request），
教务经控制器/后台方法 approve/refuse/pay（均带审计 + 通知）。
"""
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.edu_schedule.models.identity import (
    users_of_partner, users_of_profile)

_logger = logging.getLogger(__name__)

# 账目分类已改为**可配置字典**（edu.fee.category，见下方模型）——
# 校长 2026-09-16 要求「可以自己创建」（后补：也可以删除）。
# 旧常量 FEE_CATEGORIES 已退场；迁移映射见 migrations/19.0.2.0.0/。

# 报销单状态机（仅 payable 报销单使用）
REIMBURSE_STATES = [
    ('request', '申请中'),
    ('approved', '已同意待付'),
    ('refused', '已驳回'),
    ('paid', '已付款'),
]

# 报销事件类目（/my/notify 偏好开关）
NOTIFY_EVENT_REIMBURSE = 'reimburse_result'


class EduFeeCategory(models.Model):
    """费用分类（校方自助维护的字典表）。

    同构先例：edu.download.category（校方自助维护的资料文件夹），照抄其写法。
    调研依据：docs/research/fee-categories.md（Odoo 19 核心的费用类别是
    product.product，但其宿主 hr_expense 未装；校管家官方证实「收支类别」
    支持校方自助新增 ⇒ 自建小字典表是行业已验证做法）。

    删除语义（校长 2026-09-16：「可以自定义新建和删除」）：
    - 没被任何账单引用 → **真删除**；
    - 已被账单引用 → 拒绝删除，并提示改用「停用」（active=False）：
      历史账必须保住分类名，否则台账会出现「无分类」的窟窿。
    """
    _name = 'edu.fee.category'
    _description = '费用分类'
    _order = 'sequence, id'

    name = fields.Char('分类名称', required=True)
    code = fields.Char('代码', required=True, index=True,
                       help='英文/拼音短码；CSV 导出与脚本按它引用，建后不建议改')
    sequence = fields.Integer('排序', default=10)
    active = fields.Boolean('启用', default=True)
    direction_hint = fields.Selection(
        [('receivable', '应收'), ('payable', '应付')], string='方向倾向',
        help='留空=两边都能用；填了则只在所选方向的记账表单里出现，避免选错')
    note = fields.Char('说明')

    bill_count = fields.Integer('账单数', compute='_compute_bill_count')

    _code_uniq = models.Constraint('UNIQUE(code)', '分类代码不能重复。')

    def _compute_bill_count(self):
        # Odoo19 _read_group 对 m2o groupby 返回 recordset 键，须按 .id 归一
        groups = self.env['edu.fee.bill'].sudo()._read_group(
            [], ['category_id'], ['__count'])
        counts = {row[0].id: row[1] for row in groups}
        for rec in self:
            rec.bill_count = counts.get(rec.id, 0)

    # ------------------------------------------------------------------
    # 供控制器调用的三个入口（表单选项 / 筛选 domain / 表单提交解析）
    # ------------------------------------------------------------------
    @api.model
    def selectable(self, direction='', keep_id=0):
        """表单可选分类。

        - 只列启用中的；
        - 给了 direction 时按「方向倾向」过滤（留空=两边都能用）；
        - 当前选中项即使已停用也保留，否则筛选栏会莫名跳回「全部」。
        """
        cats = self.search([('active', '=', True)], order='sequence, id')
        if direction in ('receivable', 'payable'):
            cats = cats.filtered(
                lambda c: not c.direction_hint
                or c.direction_hint == direction)
        if keep_id:
            cats |= (self.browse(keep_id).exists() - cats)
        return cats

    @api.model
    def domain_for(self, param):
        """分类筛选参数（分类 id 字符串）→ (domain 片段, 选中 id)。

        非法值一律忽略（返回空 domain + 0），不报错也不静默换条件。
        """
        p = (param or '').strip()
        if not p.isdigit():
            return [], 0
        cid = int(p)
        if not self.browse(cid).exists():
            return [], 0
        return [('category_id', '=', cid)], cid

    @api.model
    def resolve_id(self, raw, fallback_code='qita'):
        """表单提交的分类参数 → 有效分类 id。

        优先级：参数是有效 id → 用；否则按 fallback_code 找兜底分类；
        再否则取第一个启用项。返回 0 表示一个可用分类都没有
        （调用方应回跳报错，**不要静默丢分类**）。
        """
        raw = (raw or '').strip()
        if raw.isdigit():
            rec = self.browse(int(raw)).exists()
            if rec:
                return rec.id
        rec = self.search([('code', '=', fallback_code)], limit=1)
        if not rec:
            rec = self.search([('active', '=', True)],
                              order='sequence, id', limit=1)
        return rec.id if rec else 0

    def unlink(self):
        """被账单引用的分类不许删（给出可执行的替代方案）。"""
        for rec in self:
            used = self.env['edu.fee.bill'].sudo().search_count(
                [('category_id', '=', rec.id)])
            if used:
                raise UserError(
                    '分类「%s」已被 %d 张账单使用，不能删除。\n\n'
                    '请改为「停用」：历史账单仍显示原名，新记账不再出现该选项。'
                    % (rec.name, used))
        return super().unlink()


class EduFeeBill(models.Model):
    _name = 'edu.fee.bill'
    _description = '学坊账单（应收/应付总账）'
    _order = 'due_date desc, id desc'

    # ------------------------------------------------------------------
    # 既有字段（原样保留；旧统筹费账单 direction 默认 receivable）
    # ------------------------------------------------------------------
    name = fields.Char(string='账单名称', required=True)
    student_id = fields.Many2one(
        'op.student', string='学生', required=False,
        index=True, ondelete='cascade')
    amount = fields.Monetary(string='金额', required=True)
    currency_id = fields.Many2one(
        'res.currency', string='币种',
        default=lambda self: self.env.company.currency_id)
    due_date = fields.Date(string='截止日期')
    note = fields.Text(string='备注')
    payment_ids = fields.One2many(
        'edu.fee.payment', 'bill_id', string='收付款记录')
    paid_amount = fields.Monetary(
        string='已收付合计', compute='_compute_state', store=True)
    state = fields.Selection(
        [('open', '待缴'), ('partial', '部分缴纳'),
         ('paid', '已缴清'), ('void', '作废')],
        string='状态', compute='_compute_state', store=True, index=True)

    # ------------------------------------------------------------------
    # 三期新增：双向台账 + 报销（全部带默认值，存量数据零迁移）
    # ------------------------------------------------------------------
    direction = fields.Selection(
        [('receivable', '应收'), ('payable', '应付')],
        string='方向', default='receivable', required=True,
        index=True, help='应收=学校收（统筹费/罚款/教材）；应付=学校付/报销。')
    # 2026-09-16：Selection → Many2one（校方可在后台自助增删分类）。
    # 列**有意可空**：-u 给存量表加「必填」列会撞 NOT NULL，故由应用层
    # （记账表单/报销表单）强制必填，并由 migrations/19.0.2.0.0 回填存量。
    category_id = fields.Many2one(
        'edu.fee.category', string='分类', ondelete='restrict', index=True,
        help='在「费用分类」档案里自助维护；被引用的分类不能删，只能停用。')
    partner_id = fields.Many2one(
        'res.partner', string='受理人',
        help='通用受理人（报销=申请人/垫付人 partner；应付给老师=老师 partner）。')
    faculty_id = fields.Many2one(
        'op.faculty', string='教师',
        help='应付给老师时记录对应教师档案（无档案期间用 partner_id 落库）。')
    created_by_partner = fields.Many2one(
        'res.partner', string='发起人', help='报销申请发起人（垫付人）。')
    source_ref = fields.Char(
        string='来源单号', help='@班级批量展开的父单号/手工备注/上级引用。')
    # 报销单两段式（仅 payable 报销单使用；应收单留空）
    reimburse_state = fields.Selection(
        REIMBURSE_STATES, string='报销状态', index=True)
    reimburse_ref = fields.Char(
        string='报销单号', index=True,
        help='报销申请单号 REB%06d（edu.reimburse.seq 序号）。')
    approved_amount = fields.Monetary(
        string='同意金额', help='教务同意的报销金额（默认=申请金额，可改）。')
    approved_by = fields.Many2one('res.users', string='审批人')
    approved_on = fields.Datetime(string='审批时间')
    reject_reason = fields.Text(string='驳回原因')
    receipt_attachment_ids = fields.Many2many(
        'ir.attachment', 'edu_fee_bill_receipt_rel',
        'bill_id', 'attachment_id', string='收据附件',
        help='报销收据/凭证：仅 jpg/png/pdf，单文件 ≤10MB。')

    # ------------------------------------------------------------------
    # 计算/约束
    # ------------------------------------------------------------------
    @api.depends('payment_ids.amount', 'amount', 'approved_amount',
                 'direction', 'reimburse_state', 'state')
    def _compute_state(self):
        for bill in self:
            paid = sum(bill.payment_ids.mapped('amount'))
            bill.paid_amount = paid
            if bill.state == 'void':
                continue
            # 应付·报销单：义务 = 教务同意金额（approved_amount），
            # 付款与同意金额平账即 paid（报销部分同意的场景）
            payable_goal = bill.approved_amount if (
                bill.direction == 'payable' and bill.reimburse_state
                and bill.approved_amount) else bill.amount
            if paid <= 0:
                bill.state = 'open'
            elif paid < payable_goal:
                bill.state = 'partial'
            else:
                bill.state = 'paid'

    _amount_positive = models.Constraint(
        'CHECK (amount > 0)', '账单金额必须大于零。')

    # ------------------------------------------------------------------
    # 收据可见性（受控预览用；不依赖 ir.attachment 的 public 开关）
    # ------------------------------------------------------------------
    def _is_backoffice_user(self):
        """当前用户是否 教务处/管理员。"""
        return bool(
            self.env.user.has_group(
                'openeducat_core.group_op_back_office_admin')
            or self.env.user.has_group('base.group_system'))

    def _user_can_view_receipt(self):
        """当前登录用户是否有权查看该报销单的收据（设计 §5 权限矩阵）。

        - 教务/管理员：全部可看（审批需要）；
        - 申请人本人：created_by_partner.user_ids 含当前账号，或
          student_id / faculty_id / partner_id 名下的账号是当前账号；
        - 其余（其他学生/教师/家长/匿名）：拒绝。

        账号解析统一走 identity.users_of_partner（**双向并集**：
        partner.user_id ∪ partner.user_ids）。原实现只读 partner.user_id
        这一列（销售员列）⇒ 对「账号由脚本新建」的教师/受理人恒判 False，
        收据被静默拒绝（repair-round-2 曾据此把 user_ids 误判为「恒空」）。
        """
        self.ensure_one()
        if self._is_backoffice_user():
            return True
        uid = self.env.uid

        def owns(partner):
            return bool(partner) and uid in users_of_partner(partner).ids

        if owns(self.created_by_partner):
            return True
        # 学生：op.student.user_id 是**独立存储列**（链①），必须一起算，
        # 否则按老口径挂好的学生会突然看不见自己的收据（新造回归）
        if self.student_id and uid in users_of_profile(self.student_id).ids:
            return True
        if self.faculty_id and owns(self.faculty_id.partner_id):
            return True
        if owns(self.partner_id):
            return True
        return False

    @api.constrains('reimburse_ref')
    def _check_reimburse_ref_unique(self):
        for rec in self:
            if rec.reimburse_ref:
                dup = self.search_count([
                    ('reimburse_ref', '=', rec.reimburse_ref),
                    ('id', '!=', rec.id)])
                if dup:
                    raise ValidationError(
                        '报销单号 %s 已存在。' % rec.reimburse_ref)

    # ------------------------------------------------------------------
    # 报销两段式：打勾 / 驳回 / 付款登记
    # ------------------------------------------------------------------
    def _require_backoffice(self):
        """组守卫：审批/付款/记账仅 教务处组 或 base.group_system 可执行。

        设计 §5 权限矩阵：记应收/应付总账、审批报销、付款登记均教务专属；
        学生/教师（仅 op.faculty 绑定）/家长一律拒绝，越权直接抛 ValidationError
        （不轻放为重定向，防止后台 RPC 直调 / 表单按钮绕过界面守卫）。
        """
        if not self.env.user.has_group(
                'openeducat_core.group_op_back_office_admin') \
                and not self.env.user.has_group('base.group_system'):
            raise ValidationError(
                '仅教务/管理员可执行此操作（报销审批、付款登记、记账）。')

    def _require_reimburse(self):
        for bill in self:
            if bill.direction != 'payable' or not bill.reimburse_ref:
                raise ValidationError(
                    '该账单不是报销单（应付/带报销单号），无法执行报销操作。')

    def _reimburse_notify(self, new_state):
        """报销状态流转 → 站内通知（事件 reimburse_result，收件人=申请人）。

        收件人解析优先级：申请人的门户账号（created_by_partner.user_id）>
        student_id.user_id（旧学生报销）> faculty_id.user_id（教师报销）。
        通知失败只告警，不阻断业务事务（对齐 leave/registration 写法）。
        金额口径：approved/paid 状态用 approved_amount（教务同意金额），
        其余（request/refused）用申请金额。
        """
        try:
            target = self.created_by_partner or self.student_id.partner_id \
                or (self.faculty_id.partner_id if self.faculty_id else None)
            user = None
            if target and target.user_ids:
                user = target.user_ids[:1]
            if not user:
                return
            if user.id == self.env.uid:
                return
            label = dict(REIMBURSE_STATES).get(new_state, new_state or '')
            if new_state in ('approved', 'paid') and self.approved_amount:
                shown_amount = self.approved_amount
            else:
                shown_amount = self.amount or 0
            body = '【报销通知】您的报销申请 %s（%s %s）%s。' % (
                self.reimburse_ref or self.name or '—',
                self.category_id.name or '',
                '%.2f' % (shown_amount or 0), label)
            if new_state == 'refused' and self.reject_reason:
                body += '\n驳回原因：%s' % self.reject_reason
            self.env['edu.message']._notify_event(
                NOTIFY_EVENT_REIMBURSE, user, body)
        except Exception:
            _logger.warning('reimburse notify failed bill=%s',
                            self.id, exc_info=True)

    def _reimburse_audit(self, action, detail=''):
        """报销审计写入（t30 加固）。

        隐患：action 由调用方以字符串传入，结构上与 t28 同型——一旦有人传
        英文码，就会原样落进用户可见的审计动作列。此处统一兜底：
        **非中文（或空）一律回落中性中文并记 warning，绝不原样落库**；
        中文照原样保留，故现有调用方行为不变。

        兜不在这里就兜在源头：真正彻底的收口点是 models/audit.py:_log()，
        但该文件不在 t30 inScope（任务描述把它写成了 controllers/downloads.py，
        实际定义在 models/audit.py:29），已在提交说明中上报申请。
        """
        label = (action or '').strip()
        if not label:
            label = '报销操作'
        elif not any('\u4e00' <= ch <= '\u9fff' for ch in label):
            _logger.warning(
                'reimburse audit action 非中文，已回落中性标签：%r', action)
            label = '报销操作'
        self.env['edu.audit.log'].sudo()._log(
            label, 'edu.fee.bill', self.id,
            self.reimburse_ref or self.name or '', detail)

    def action_reimburse_approve(self, amount=None):
        """打勾 ✓：request → approved（同意金额可改，默认=申请金额）。

        组守卫（教务/管理员）→ 校验存在 → 置 approved 状态 +
        approved_amount（传入或不传）+ approved_by/on；通知申请人 + 审计。
        """
        self._require_backoffice()
        self._require_reimburse()
        for bill in self:
            if bill.reimburse_state != 'request':
                raise ValidationError(
                    '报销单 %s 当前状态不是「申请中」，无法同意。'
                    % (bill.reimburse_ref or bill.name or ''))
            agree = amount
            if agree is None:
                agree = bill.amount
            try:
                agree = float(agree or 0)
            except (TypeError, ValueError):
                raise ValidationError('同意金额无效。')
            if agree <= 0:
                raise ValidationError('同意金额必须大于零。')
            bill.write({
                'reimburse_state': 'approved',
                'approved_amount': agree,
                'approved_by': self.env.uid,
                'approved_on': fields.Datetime.now(),
            })
            bill._reimburse_notify('approved')
            bill._reimburse_audit(
                '报销审批',
                '同意：同意金额 %.2f（申请 %.2f）'
                % (agree, bill.amount or 0))
        return True

    def action_reimburse_refuse(self, reason=''):
        """驳回 ✗：request → refused，原因必填；通知申请人 + 审计。"""
        self._require_backoffice()
        self._require_reimburse()
        reason = (reason or '').strip()
        if not reason:
            raise ValidationError('驳回报销必须填写驳回原因。')
        for bill in self:
            if bill.reimburse_state != 'request':
                raise ValidationError(
                    '报销单 %s 当前状态不是「申请中」，无法驳回。'
                    % (bill.reimburse_ref or bill.name or ''))
            bill.write({
                'reimburse_state': 'refused',
                'reject_reason': reason[:2000],
            })
            bill._reimburse_notify('refused')
            bill._reimburse_audit('报销审批', '驳回：原因 %s' % reason)
        return True

    def action_pay(self, method='bank', payment_date=None, note=''):
        """付款登记（应付侧）：建 edu.fee.payment + reimburse_state=paid。

        组守卫（教务/管理员）→ 复用既有 payment 流水与 state 汇总逻辑；
        已付/驳回单拒绝重复付。
        """
        self._require_backoffice()
        self._require_reimburse()
        for bill in self:
            if bill.reimburse_state not in ('approved',):
                raise ValidationError(
                    '报销单 %s 尚未同意（或已付款/已驳回），无法登记付款。'
                    % (bill.reimburse_ref or bill.name or ''))
            if bill.state == 'paid':
                raise ValidationError(
                    '报销单 %s 已平账，无需重复付款。'
                    % (bill.reimburse_ref or bill.name or ''))
            Payment = self.env['edu.fee.payment'].sudo()
            Payment.create({
                'bill_id': bill.id,
                'student_id': bill.student_id.id if bill.student_id else False,
                'amount': bill.approved_amount or bill.amount,
                'method': method if method in (
                    'bank', 'wechat', 'alipay', 'cash', 'other') else 'bank',
                'payment_date': payment_date or fields.Date.today(),
                'note': (note or '').strip()[:200] or '报销付款',
            })
            bill.write({
                'reimburse_state': 'paid',
                'approved_on': bill.approved_on or fields.Datetime.now(),
            })
            bill._reimburse_notify('paid')
            bill._reimburse_audit(
                '报销付款', '付款登记：金额 %.2f（方式 %s）'
                % (bill.approved_amount or bill.amount, method))
        return True

    # ------------------------------------------------------------------
    # 报销申请落库（门户控制器经 sudo 调用）+ 序号
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """报销申请（payable + request）自动生成 reimburse_ref（原子序号）。

        组守卫（账目创建口径，设计 §5）：
        - 「报销申请」（direction=payable 且 reimburse_state=request）允许
          学生/教师本人发起（由门户控制器校验身份后落库）；
        - 其余一切账目（应收记账、手工应付、直接建 approved/paid 等）
          均为教务记账入口 → 非 教务处组/管理员 抛 ValidationError。
        仅在报销申请且未显式传号时发 reimburse_ref（原子序号）。
        """
        for vals in vals_list:
            is_payable_request = (
                vals.get('direction') == 'payable'
                and vals.get('reimburse_state') == 'request')
            if not is_payable_request:
                self._require_backoffice()
            if is_payable_request and not vals.get('reimburse_ref'):
                vals['reimburse_ref'] = self._next_reimburse_ref()
        return super().create(vals_list)

    @api.model
    def _next_reimburse_ref(self):
        """原子取号：ir.sequence.next_by_code('edu.reimburse.seq')。

        Odoo 19 的 next_by_code 内部在事务中原子递增 number_next，
        天然无并发竞态；无需手工 number_next 写回或按最大单号兜底。
        """
        try:
            seq = self.env['ir.sequence'].sudo().next_by_code(
                'edu.reimburse.seq')
            if seq:
                return seq
        except Exception:
            _logger.warning('reimburse seq next_by_code failed',
                            exc_info=True)
        # 理论不可达的兜底（序列记录被删时）：按现有最大单号 + 1
        last = self.sudo().search(
            [('reimburse_ref', '!=', False)], order='reimburse_ref desc',
            limit=1)
        try:
            nxt = int((last.reimburse_ref or 'REB000000')[3:]) + 1
        except (TypeError, ValueError):
            nxt = 1
        return 'REB%06d' % nxt


class EduFeePayment(models.Model):
    _name = 'edu.fee.payment'
    _description = '缴费流水'
    _order = 'payment_date desc, id desc'

    bill_id = fields.Many2one(
        'edu.fee.bill', string='所属账单', required=True,
        ondelete='cascade', index=True)
    student_id = fields.Many2one(
        related='bill_id.student_id', string='学生',
        store=True, readonly=True)
    amount = fields.Monetary(string='本次到账', required=True)
    currency_id = fields.Many2one(related='bill_id.currency_id')
    method = fields.Selection(
        [('bank', '银行转账'), ('wechat', '微信'),
         ('alipay', '支付宝'), ('cash', '现金'), ('other', '其他')],
        string='方式', default='bank', required=True)
    payment_date = fields.Date(
        string='到账日期', default=fields.Date.today, required=True)
    received_by = fields.Many2one(
        'res.users', string='经手人', default=lambda self: self.env.user)
    note = fields.Char(string='附言')

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError('到账金额必须大于零。')
