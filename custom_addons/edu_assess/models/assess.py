# -*- coding: utf-8 -*-
"""评估引擎数据模型（形态甲：评分项 = 数据行，列不是模型字段）。

设计依据：
  · 第 1 期：docs/plans/evaluation-rebuild-design.md §4（五层模型）§5（行表 vs Properties）
    §8.3（权限口径）§8.4（匿名口径 = ③ HMAC 指纹）。
  · 第 2 期：docs/plans/eval-unified-design.md
      §3.3 12 项新增字段（F1–F12，**零新模型**）
      §3.5 三种算法（A1 倍率 / A2 占比 / A3 双轨平均）+ 派生显示（小计/合计**不落库**）
      §5.0–§5.10 六组缺口解法（H1 层级 / H2 占比 / H3 双轨 / H4 扣分+多区段 /
      H5 评语 / W1 名单行 / G8 刻度 / G17 等级线）

五层：模板 edu.assess.template → 评分项（= 一列）edu.assess.item →
任务 edu.assess.task → 名单快照（= 一行）edu.assess.roster → 单元格 edu.assess.score。

「在线加一个评分项」= 往 edu.assess.item 插一行数据：不新增 ir.model.fields、
不改 schema、不发版；四个面（门户矩阵 / 后台列表 / 结果页 / xlsx）都在**请求时**
读 item_ids 渲染。第 2 期把「评分项」扩成「节点」：分组节点（item_kind=group）
只做分类与小计，叶子项（leaf）才是可打分的一列。

第 2 期新增的 12 个字段**全部带默认值** ⇒ 存量记录（3 模板/7 项/3 任务/7 名单/8 打分）
语义与算分不变（§8.0、§8.3）；小计 / 合计 / 占比合计 / 等级一律**派生、不落库**（§3.5）。

## 两个「唯一的算法入口」（设计 §3.5 明令只允许一处实现）

1. EduAssessRoster._item_cell(item) —— 一个评分项在一个被评对象上的**得分**。
   双轨合并 (客观 + 主观) / 2 **只在这里实现一次**；结果页 / xlsx / 打印一律调用它，
   禁止任何地方再写一遍「两路相加除 2」（调研结论：Moodle 5.0 的合并入口也只有一处）。
2. EduAssessRoster._compute_derived() —— 行总分 / 加权总分 / 平均分 / 等级 /
   完整度 / 未评项清单，全部由 _item_cell 逐项汇总，因此**自动带上**
   score_mode（加分/扣分）与 track（单轨/双轨）语义。

⚠ **第 2 期修掉的两处静默算错**（第 1 期的 rec.average = total / len(refs) 与
_item_average 把所有 score 行不加区分地平均）：双轨按「同一评分项下成对的两条
score 行」落库后，那两处会把客观/主观两条轨**当成两个人**再平均一遍（静默把总分砍半），
且不报错。现在两处都改为走 _item_cell。

## 有意偏离设计文档的地方（实现前已核对，逐条写在此处与报告里）

- §5.3 / D3 的「双轨缺一路 ⇒ 可选开关（模板级，默认关闭）按已填路数平均」：
  §3.3 的 12 字段清单里**没有这个开关字段** ⇒ 本期用模块常量
  ALLOW_PARTIAL_DUAL = False 固定「默认关闭」这一侧语义（缺一路不产生分数）；
  将来要放开只需加 1 个模板级布尔字段。
- §5.7 的「已有打分的名单行只可停用」：停用需要一个 roster 级 active 语义位，
  同样不在 12 字段清单里 ⇒ 本期只落地**硬护栏**（有打分拒删，报错引导）。

## init() 迁移的三条硬规矩（2026-09-28 生产事故后立）

1. **每个模型的 init() 只碰自己的表。** Odoo 的 `Registry.init_models()` 是**逐模型**
   跑 `model._auto_init()` → `model.init()`（`odoo/orm/registry.py` 的 `init_models`），
   所以「别的表的列已经建好」这件事**没有任何保证**。第 2 期那三条 item 回填 + 一条
   score 回填原先都写在 `EduAssessTemplate.init()` 里 ⇒ 面对**第 1 期状态的库**必然炸
   `psycopg2.errors.UndefinedColumn: column "item_kind" does not exist`
   ⇒ `Failed to load registry` ⇒ **整站升级失败**（生产实测退出码 255）。
   本地全绿只是假象：本地库早升过一次、那些列早在，把顺序问题掩盖了。
2. **回填前先问 `information_schema`（`odoo.tools.sql.column_exists`），列不在就跳过。**
   裸 SQL 里表名/列名都是写死的，再出一次顺序问题（或写错名字）的代价是**整站升级失败**，
   而多一句查询的代价可以忽略 —— 代价严重不对称，所以宁可多问一句。
   （`ALTER TABLE ... DROP CONSTRAINT IF EXISTS` 本身幂等，但表名写错同样是炸 ⇒ 配 `table_exists`。）
3. **回填值一字不改。** 这些是等值迁移（NULL → 字段声明的默认值），不是业务改写；
   动这里等于静默改存量数据。
"""
import hashlib
import hmac
import secrets

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.sql import column_exists, table_exists

KIND_SELECTION = [
    ('teaching', '评教'),
    ('student', '学生综合'),
    ('admin', '行政考评'),
    ('intern', '实习评估'),
    ('other', '其他'),
]
TARGET_KINDS = [
    ('student', '学生'),
    ('faculty', '教师'),
]
SCORER_KINDS = [
    ('student', '学生评教师'),
    ('teacher', '教师评学生'),
    ('self', '自评'),
    ('peer', '互评'),
]
TEMPLATE_STATES = [
    ('draft', '草稿'),
    ('active', '启用'),
    ('archived', '归档'),
]
TASK_STATES = [
    ('draft', '草稿'),
    ('open', '进行中'),
    ('closed', '已结束'),
]
ROSTER_STATES = [
    ('pending', '未评'),
    ('done', '已评'),
]
SCORE_KINDS = [
    ('number', '分值'),
    ('level', '档位'),
]

# ---------------------------------------------------------------------------
# 第 2 期新增枚举（设计 §3.3 / §5.1 / §5.4 / §5.8 / §5.9）
# ---------------------------------------------------------------------------
#: F12 节点类型：group = 分类/区（不打分，满分与小计派生）；leaf = 可打分的评分项。
ITEM_KINDS = [
    ('group', '分组节点'),
    ('leaf', '叶子评分项'),
]
#: F2 评分轨：single = 一条路；dual = 客观路 + 主观路（两路取平均）。
ITEM_TRACKS = [
    ('single', '单轨'),
    ('dual', '双轨'),
]
#: F3 计分方式：add = 得分（越大越好）；deduct = 扣分（score.value 存"扣了多少"）。
SCORE_MODES = [
    ('add', '加分制'),
    ('deduct', '扣分制'),
]
#: F5 权重模式：multiplier = 倍率（存量默认）；percent = 占比（Σ 必须 = 100%）。
WEIGHT_MODES = [
    ('multiplier', '倍率'),
    ('percent', '占比'),
]
#: F7 刻度校验规则：free = 自由；tens = 只允许 10 的倍数；integer = 只允许整数。
SCALE_RULES = [
    ('free', '自由'),
    ('tens', '只许 10 的倍数'),
    ('integer', '只许整数'),
]
#: F10 打分轨（单元格级）：单轨项恒 objective（不区分轨）。
SCORE_TRACKS = [
    ('objective', '客观'),
    ('subjective', '主观'),
]

#: H1 层级上限（D1 裁定）：xlsx 表头最多三层，无限层级会让表头与冻结同时塌。
MAX_ITEM_DEPTH = 3
#: H2 占比合计（D2）：素材里占比带一位小数（7.5%），因此按 0.01 容差判等。
PERCENT_SUM = 100.0
PERCENT_EPS = 0.01
#: G8 预设刻度锚点（说明 P067–P073：5 档 + 只许中间值 10 的倍数）。
DEFAULT_SCALE_ANCHORS = '10,40,60,80,100'
#: §5.3 / D3 的「缺一路按已填路数平均」开关：**默认关闭**（见模块 docstring 的偏离说明）。
ALLOW_PARTIAL_DUAL = False

#: 匿名指纹盐（ir.config_parameter）。**不要**把盐写进代码或模板：
#: 盐一旦泄漏，配合小空间的 user_id 就能穷举反推（设计稿 §8.4 口径 ③ 已书面告知校长）。
SALT_PARAM = 'edu_assess.anon_salt'


def anon_salt(env):
    """取（或首次生成）匿名指纹盐。"""
    Param = env['ir.config_parameter'].sudo()
    salt = Param.get_param(SALT_PARAM)
    if not salt:
        salt = secrets.token_hex(16)
        Param.set_param(SALT_PARAM, salt)
    return salt


def anon_fingerprint(env, task_id, user_id):
    """口径 ③：scorer_ref = 'h:' || HMAC-SHA256(盐, task_id + user_id)。

    能查重、能防重复提交；**不能**反推是谁 —— 前提是盐不外泄、且结果页有样本门槛。
    本模块任何匿名任务一律**不写** scorer_id（详见 models 与 controllers 的注释）。
    """
    key = anon_salt(env).encode('utf-8')
    msg = ('%s:%s' % (task_id, user_id)).encode('utf-8')
    return 'h:' + hmac.new(key, msg, hashlib.sha256).hexdigest()


def _mean(values):
    """算术平均；空序列返回 None（**None 表示"没有分"，不是 0**）。"""
    return (sum(values) / len(values)) if values else None


class EduAssessTemplate(models.Model):
    _name = 'edu.assess.template'
    _description = '评估模板'
    _order = 'name, id'

    name = fields.Char(string='模板名称', required=True)
    kind = fields.Selection(
        KIND_SELECTION, string='评估类型', default='teaching', required=True)
    target_kind = fields.Selection(
        TARGET_KINDS, string='被评对象', default='faculty', required=True)
    total = fields.Float(string='满分', default=100.0, required=True)
    pass_line = fields.Float(string='及格线', default=60.0, required=True)
    #: F6：优秀线默认**关闭**（裁定 A4：「90 优秀」在 6 份素材里查无出处）。
    #: 字段本身保留且**不清理存量值**（存量 3 个模板仍写 90），只是"未启用"时不参与判级。
    excellent_enabled = fields.Boolean(
        string='启用优秀线', default=False,
        help='6 份素材里只有「低于 60 分不及格」这一条有据；「90 分优秀」查无出处'
             '（裁定 A4）。默认关闭：关闭时不参与判级、界面不显示。')
    excellent_line = fields.Float(
        string='优秀线', default=90.0, required=True,
        help='仅在勾选「启用优秀线」后生效。系统不做任何自动改写，'
             '存量模板里的 90 需要教务自己决定是否启用。')
    #: F7：刻度锚点 + 校验规则（G8）。锚点用字符串存是 §3.3 的取舍（少一个子表）。
    scale_anchors = fields.Char(
        string='评分刻度锚点', default=DEFAULT_SCALE_ANCHORS,
        help='逗号分隔（默认 %s）。「给分方式 = 档位」的评分项，'
             '其下拉选项就是这些锚点；分值型评分项也可按「刻度校验」规则校验。'
             % DEFAULT_SCALE_ANCHORS)
    scale_rule = fields.Selection(
        SCALE_RULES, string='刻度校验', default='free',
        help='默认「自由」（对不需要刻度的表不强加校验）。选「只许 10 的倍数」'
             '即复刻说明 P073「尽量写整数，方便计算」的有效取值集合。')
    #: F5：权重模式。倍率为**存量默认**，行为与第 1 期逐字节一致。
    weight_mode = fields.Selection(
        WEIGHT_MODES, string='权重模式', default='multiplier', required=True,
        help='倍率 = 得分 × 权重后求和（存量口径）；'
             '占比 = 每个叶子项的权重是它占总分的百分比，合计必须 = 100%，'
             '得分按 (得分 / 满分) × 占比% × 满分 折算（与素材 xlsx 的 I = H × E 同式）。')
    score_visible = fields.Boolean(string='结果对被评者可见', default=False)
    allow_self = fields.Boolean(string='允许自评', default=False)
    state = fields.Selection(
        TEMPLATE_STATES, string='状态', default='active', required=True,
        index=True)
    notes = fields.Text(string='说明')
    active = fields.Boolean(string='启用', default=True)
    item_ids = fields.One2many(
        'edu.assess.item', 'template_id', string='评分项')
    task_ids = fields.One2many(
        'edu.assess.task', 'template_id', string='评估任务')
    item_count = fields.Integer(
        string='节点数', compute='_compute_item_count')
    #: 派生的只读量（§4 #8 / #10 / #13）：小计与占比合计一律服务端算，不给编辑入口。
    leaf_count = fields.Integer(
        string='叶子评分项数', compute='_compute_weight_sum')
    weight_sum = fields.Float(
        string='占比合计', compute='_compute_weight_sum',
        help='启用中的叶子评分项权重之和（占比模式下应 = 100%）。')
    weight_sum_ok = fields.Boolean(
        string='占比合计 = 100%', compute='_compute_weight_sum')

    def init(self):
        """等值规范化：把新增列的 NULL 收成字段声明的默认值（只做一次，幂等）。

        为什么需要：Odoo 给**新增的非必填列**回填默认值时，Selection 会回填
        （实测 weight_mode / item_kind / track / score_mode / score.track 都被填上了），
        但 **Boolean 不回填** —— 存量 3 个模板的 excellent_enabled 在 SQL 里是 NULL。
        ORM 读 NULL 布尔 = False，语义等价；可这颗 NULL 会让「默认值」口径在 SQL 侧
        含糊（where excellent_enabled = false 会漏掉存量行）。
        照 edu_portal/models/downloads.py 的 init() 等值迁移先例处理，**不改语义**。

        ⚠ **本方法只许碰 edu_assess_template 自己的表**（规则见模块 docstring
        「init() 迁移的三条硬规矩」）。第 2 期这里曾**顺手 UPDATE 了别的表**
        （edu_assess_item 的三列 + edu_assess_score.track）—— 那就是 2026-09-28
        生产事故的直接原因：Odoo 逐模型跑 _auto_init() → init()（odoo/orm/registry.py
        的 init_models），处理到本模板时那两张表的新列**还没建** ⇒ UndefinedColumn
        ⇒ Failed to load registry ⇒ 整站升级失败。现已搬到各自模型的 init()。
        """
        cr = self.env.cr
        if column_exists(cr, 'edu_assess_template', 'excellent_enabled'):
            cr.execute(
                "UPDATE edu_assess_template SET excellent_enabled = false "
                "WHERE excellent_enabled IS NULL")
        if column_exists(cr, 'edu_assess_template', 'weight_mode'):
            cr.execute(
                "UPDATE edu_assess_template SET weight_mode = 'multiplier' "
                "WHERE weight_mode IS NULL")
        return super().init()

    @api.depends('item_ids')
    def _compute_item_count(self):
        for tpl in self:
            tpl.item_count = len(tpl.item_ids)

    @api.depends('item_ids', 'item_ids.weight', 'item_ids.item_kind',
                 'item_ids.active')
    def _compute_weight_sum(self):
        for tpl in self:
            leaves = tpl._weighted_leaves()
            tpl.leaf_count = len(leaves)
            tpl.weight_sum = sum(leaves.mapped('weight'))
            tpl.weight_sum_ok = abs(tpl.weight_sum - PERCENT_SUM) < PERCENT_EPS

    # ------------------------------------------------------------------
    # 节点集合（H1 层级的三个口径，别混用）
    # ------------------------------------------------------------------
    def _weighted_leaves(self):
        """参与「占比合计」的叶子项 = **启用中**的叶子（停用项不再计入 Σ）。"""
        self.ensure_one()
        return self.with_context(active_test=False).item_ids.filtered(
            lambda i: i.item_kind == 'leaf' and i.active)

    def _all_leaves(self):
        """模板的**全部**叶子项（含已停用的历史项）。

        汇总走这一份：第 1 期口径是「停用后新打分不再出现该列，历史得分仍保留可查」
        ⇒ 停用项的历史分必须继续计入总分，否则升级会静默改掉存量读数。
        """
        self.ensure_one()
        return self.with_context(active_test=False).item_ids.filtered(
            lambda i: i.item_kind == 'leaf')


    def _anchor_values(self):
        """刻度锚点列表（G8）：门户下拉、档位校验、测试都用这一处解析。"""
        self.ensure_one()
        out = []
        for chunk in (self.scale_anchors or '').replace('，', ',').split(','):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                out.append(float(chunk))
            except ValueError:
                raise ValidationError(
                    '模板「%s」的评分刻度锚点「%s」不是数字：请用逗号分隔的数字，'
                    '例如 %s。' % (self.name, chunk, DEFAULT_SCALE_ANCHORS))
        return out

    def _scale_violation(self, value):
        """刻度校验（G8）：返回违规说明字符串，通过返回 None。

        默认 scale_rule='free' ⇒ 永远返回 None（对不需要刻度的表不强加）。
        """
        self.ensure_one()
        if self.scale_rule == 'tens' and abs(value % 10.0) > 1e-9:
            return '请填 10 的倍数（说明 P073：尽量写整数，方便计算）'
        if self.scale_rule == 'integer' and abs(value - round(value)) > 1e-9:
            return '请填整数'
        return None

    def _grade_of(self, value):
        """等级（派生，§4 的三条边界原则之三：派生量只读）。

        优秀线**未启用**时只有「及格 / 不及格」两档 —— 不许系统自己编一档「优秀」。
        """
        self.ensure_one()
        if self.excellent_enabled and value >= self.excellent_line:
            return '优秀'
        return '及格' if value >= self.pass_line else '不及格'

    def _ensure_percent_ready(self):
        """占比模式的**硬闸门**（§5.2.1）：Σ(启用叶子权重) 必须 = 100（容差 0.01）。

        两处调用：① 模板启用；② 创建评估任务前。草稿（state=draft）可存 —— 中途
        正在搭结构，强制 100 会让人没法保存（这是设计写死的口径，不是偷懒）。
        空模板（还没建任何叶子项）放行：否则「新建即 active」的默认流程根本建不出来。
        """
        self.ensure_one()
        if self.weight_mode != 'percent':
            return
        leaves = self._weighted_leaves()
        if not leaves:
            return
        total = sum(leaves.mapped('weight'))
        if abs(total - PERCENT_SUM) >= PERCENT_EPS:
            raise ValidationError(
                '模板「%s」是占比模式：所有启用中的叶子评分项权重合计必须 = 100%%，'
                '当前为 %g%%（差 %+.2f%%）。请补齐或调整各项占比。'
                % (self.name, total, PERCENT_SUM - total))

    def action_check_weight_sum(self):
        """界面上的「校验占比」入口：只读回执，不改任何数据。"""
        self.ensure_one()
        leaves = self._weighted_leaves()
        total = sum(leaves.mapped('weight'))
        ok = abs(total - PERCENT_SUM) < PERCENT_EPS
        if self.weight_mode == 'percent' and leaves and not ok:
            self._ensure_percent_ready()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if ok else 'warning',
                'title': '占比校验',
                'message': '启用中的叶子评分项 %d 个，权重合计 %g%%（%s）。'
                           % (len(leaves), total,
                              '通过' if ok else '占比模式下应等于 100%'),
                'sticky': False,
            },
        }


    def _weight_rollup(self):
        """派生：每个节点（一级/二级）的权重合计与满分合计（§4 #8「一级占比只读派生」）。

        说明表 1 的 40% / 15% / 30% / 15% 原文只有 vmerge 空单元格，是**按子项加总**
        推导出来的 —— 因此这里只算不存，也不给编辑入口。
        """
        self.ensure_one()
        out = []

        def walk(item, level):
            leaves = item._leaf_descendants()
            out.append({
                'item': item,
                'level': level,
                'weight_sum': sum(leaves.mapped('weight')),
                'max_sum': sum(leaves.mapped('max_score')),
                'leaf_count': len(leaves),
            })
            for child in item.child_ids.sorted(lambda i: (i.sequence, i.id)):
                walk(child, level + 1)

        for root in self.item_ids.filtered(
                lambda i: not i.parent_id).sorted(
                lambda i: (i.sequence, i.id)):
            walk(root, 1)
        return out

    @api.constrains('pass_line', 'excellent_line', 'total', 'excellent_enabled')
    def _check_lines(self):
        """G17 等级线（裁定 A4）。

        第 1 期的约束是 0 < 及格线 ≤ 优秀线 ≤ 满分 且优秀线**必填**，
        它直接挡住了「不设优秀线」⇒ 关闭时**跳过**优秀线那一支（否则「默认关闭」
        落不了地：存量 90 也会一直卡着）。
        """
        for tpl in self:
            if tpl.excellent_enabled:
                if not (0 < tpl.pass_line <= tpl.excellent_line <= tpl.total):
                    raise ValidationError(
                        '启用优秀线时需满足：0 < 及格线 ≤ 优秀线 ≤ 满分。')
            elif not (0 < tpl.pass_line <= tpl.total):
                raise ValidationError('等级线需满足：0 < 及格线 ≤ 满分。')

    @api.constrains('weight_mode', 'state', 'item_ids')
    def _check_percent_ready(self):
        """启用（state≠draft）时占比必须 = 100；草稿放行（§5.2.1）。

        ⚠ 已知边界（已写进报告）：Odoo 的 @api.constrains 不会因为**子表行**被改写
        而重跑父模型约束 ⇒「模板已经是 active 之后又去改某个叶子项的权重」这一条路径
        不会在这里被拦。那一条由「创建任务前必须 Σ=100」＋界面常驻的占比合计红字
        ＋「校验占比」按钮共同兜住。
        """
        for tpl in self:
            if tpl.state == 'draft':
                continue
            tpl._ensure_percent_ready()

    def unlink(self):
        for tpl in self:
            if tpl.task_ids:
                raise UserError(
                    '模板「%s」下已有 %d 个评估任务，不能删除；'
                    '如不再使用请改为「归档」。' % (tpl.name, len(tpl.task_ids)))
        # parent_id 是 ondelete='restrict'（Postgres 的 RESTRICT 立即校验：
        # 同一条 DELETE 里父子同删照样报错）⇒ 先按深度倒序删子节点，再删父节点。
        for tpl in self:
            items = tpl.with_context(active_test=False).item_ids
            for item in items.sorted(lambda i: -i.depth):
                item.unlink()
        return super().unlink()


class EduAssessItem(models.Model):
    """评分项 = 矩阵的一列 / 层级里的一个节点（H1）。

    item_kind='group' 的节点**不参与打分**：它是"区/类别"，满分与小计都是
    派生值（Σ 子项）；item_kind='leaf' 才是可打分的一列。
    """
    _name = 'edu.assess.item'
    _description = '评估评分项'
    _order = 'sequence, id'

    template_id = fields.Many2one(
        'edu.assess.template', string='评估模板', required=True,
        ondelete='cascade', index=True)
    #: F1 自引用层级（先例：edu.download.category.parent_id，同样是"限层级 + 约束拦深"）。
    parent_id = fields.Many2one(
        'edu.assess.item', string='上级节点', ondelete='restrict', index=True,
        domain="[('template_id', '=', template_id), ('item_kind', '=', 'group')]",
        help='留空 = 顶层。层级最多 %d 级（一级类别 → 二级子项目 → 三级评分项）。'
             % MAX_ITEM_DEPTH)
    child_ids = fields.One2many(
        'edu.assess.item', 'parent_id', string='下级节点')
    #: F12 节点类型：区分「容器」与「可打分项」。
    item_kind = fields.Selection(
        ITEM_KINDS, string='节点类型', default='leaf', required=True,
        help='分组节点只做分类与小计（满分由下级汇总，派生、只读）；'
             '叶子评分项才是矩阵里可打分的一列。')
    #: F2 单轨 / 双轨（H3）。
    track = fields.Selection(
        ITEM_TRACKS, string='评分轨', default='single', required=True,
        help='双轨 = 客观路 + 主观路各打一次，取平均（素材：客观=导师、主观=学生自评）。'
             '匿名任务下不允许双轨（主观路是自评，身份天然已知）。')
    #: F3 加分 / 扣分（H4）。扣分项的 score.value 存「实际扣掉的分数」。
    score_mode = fields.Selection(
        SCORE_MODES, string='计分方式', default='add', required=True,
        help='加分制：value 存得分（0 ~ 满分）。'
             '扣分制：value 存**实际扣掉的分数**（0 = 未扣），该项得分 = 满分 − value。')
    name = fields.Char(string='评分项', required=True)
    help = fields.Char(string='填写提示')
    max_score = fields.Float(string='满分', default=10.0, required=True)
    weight = fields.Float(string='权重', default=1.0, required=True)
    required = fields.Boolean(string='必填项', default=False)
    score_kind = fields.Selection(
        SCORE_KINDS, string='给分方式', default='number', required=True,
        help='「档位」的取值必须是模板的评分刻度锚点之一（下拉）。')
    sequence = fields.Integer(string='排序', default=10)
    active = fields.Boolean(string='启用', default=True)
    score_count = fields.Integer(
        string='已打分', compute='_compute_score_count')
    #: 派生的只读量：层级、节点满分（区满分 = Σ 子项）、节点权重合计。
    depth = fields.Integer(string='层级', compute='_compute_depth')
    rollup_max_score = fields.Float(
        string='节点满分（派生）', compute='_compute_rollup',
        help='分组节点的满分 = 其下所有叶子项满分之和（不落库、不可编辑）。')
    rollup_weight = fields.Float(
        string='节点占比合计（派生）', compute='_compute_rollup',
        help='分组节点的占比 = 其下所有叶子项权重之和（说明表 1 的一级占比 40/15/30/15'
             ' 就是这么派生出来的）。')

    def init(self):
        """第 2 期新增列的等值回填 + 删掉第 1 期的「全模板名称唯一」约束。

        **为什么必须写在本模型自己的 init() 里**：Odoo 的 Registry.init_models() 是
        **逐模型**跑 model._auto_init() → model.init()（odoo/orm/registry.py 的
        init_models）。只有写在这里，才保证「本模型的列已建」先于「回填本模型」；
        这三条 UPDATE 原先写在 EduAssessTemplate.init() 里 —— 顺序上必然踩空：
        2026-09-28 生产事故就是这么来的（column "item_kind" does not exist，退出码 255）。

        **列存在性守卫**：回填是裸 SQL，表名/列名都写死。再出一次顺序问题、或名字写错，
        代价都是**整站升级失败**；而多一句 information_schema 查询的代价可以忽略。
        守卫用 Odoo 核心自己的 odoo.tools.sql.column_exists / table_exists（能装不写）。
        列真在时行为与**没有守卫逐字节相同** —— 同一条 UPDATE，回填值一字未改。

        刻意**不**照 downloads.py 那样用 savepoint + `except: pass` 兜底：那会把
        「迁移静默没跑」变成「升级成功」，正是本次事故的同一类失败（升级绿、schema 不对）。
        真出错就该炸在升级期，而不是留给生产去发现。
        """
        cr = self.env.cr
        # 第 2 期新增列：NULL → 字段声明的默认值（等值迁移，不是业务改写）
        if column_exists(cr, 'edu_assess_item', 'item_kind'):
            cr.execute(
                "UPDATE edu_assess_item SET item_kind = 'leaf' "
                "WHERE item_kind IS NULL")
        if column_exists(cr, 'edu_assess_item', 'track'):
            cr.execute(
                "UPDATE edu_assess_item SET track = 'single' WHERE track IS NULL")
        if column_exists(cr, 'edu_assess_item', 'score_mode'):
            cr.execute(
                "UPDATE edu_assess_item SET score_mode = 'add' "
                "WHERE score_mode IS NULL")
        # 删掉第 1 期的「全模板名称唯一」约束（_item_name_uniq）。
        # 它在第 2 期被收窄成「同一上级内唯一」并由 _check_name_scope 在 ORM 层守住：
        # 素材《卫生检测表》在不同区里有同名检查项，全模板唯一会强迫改写素材原文。
        # 声明里删掉它并不会自动删库上的旧约束（Odoo 只对“还声明着的对象”做 diff），
        # 所以在这里显式删除 —— 幂等（IF EXISTS），且下一次 -u 也不会再造回来。
        # 表名同样先问一句 table_exists：表名写错与列名写错一样是炸（代价不对称）。
        if table_exists(cr, 'edu_assess_item'):
            cr.execute(
                "ALTER TABLE edu_assess_item DROP CONSTRAINT IF EXISTS "
                "edu_assess_item_item_name_uniq")
        return super().init()

    #: ⚠ 第 2 期把「名称唯一」从**全模板**收窄到**同一上级内**，并在 init() 里删掉
    #: 第 1 期那条全模板唯一约束。原因（实测，不是推演）：素材《卫生检测表》5 个区里
    #: 有**同名检查项** —— 窗户有灰尘/污渍 ×3、墙面有污渍 ×2、垃圾未倒 ×2。
    #: 全模板唯一会强迫用户改写素材原文（§4.5 判定这张表"能建出来"就不成立了）。
    #: 收窄后对**扁平模板（没有上级节点）语义与第 1 期逐字节一致** ——
    #: 现存评分项的 parent_id 全为空（实测），xlsx 导入按名称对列的幂等键原样保留。
    #: ⚠ 这里刻意**不写"现存 N 个"**：条数随验收夹具变动（实测已从 10 → 7，还会再变），
    #: 写死必腐烂 —— 与文档禁止写死行号同一条理由，见 docs/plans/eval-unified-design.md §8.0.3。
    @api.constrains('name', 'parent_id', 'template_id')
    def _check_name_scope(self):
        for item in self:
            siblings = item.template_id.with_context(
                active_test=False).item_ids.filtered(
                lambda i: i.id != item.id and i.parent_id == item.parent_id
                and (i.name or '').strip() == (item.name or '').strip())
            if siblings:
                raise ValidationError(
                    '同一模板、同一上级下已有同名评分项「%s」：名称不能重复'
                    '（xlsx 导入按名称对列做幂等键）。'
                    '不同分区的同名检查项请挂到各自的分组节点下。' % item.name)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # 子节点自动继承父节点的模板：表单里在「下级节点」内联里加一行时，
            # Odoo 只会自动补上 child_ids 的逆字段 parent_id，而 template_id 是另一个
            # 必填字段 ⇒ 不补的话"三层结构一次建出来"会被必填校验拦死
            # （实测：建 xlsx 三级模板时报 '字段 评估模板 (template_id) 缺少必填值'）。
            if vals.get('parent_id') and not vals.get('template_id'):
                parent = self.browse(vals['parent_id'])
                vals['template_id'] = parent.template_id.id
        return super().create(vals_list)

    @api.depends('template_id')
    def _compute_score_count(self):
        Score = self.env['edu.assess.score']
        for item in self:
            item.score_count = Score.search_count([('item_id', '=', item.id)])

    @api.depends('parent_id')
    def _compute_depth(self):
        """层级 = 祖先链长度（1 起）。用循环而不是递归，避免成环时死循环。"""
        for item in self:
            depth = 1
            seen = {item.id}
            node = item.parent_id
            while node and node.id not in seen and depth < 50:
                seen.add(node.id)
                depth += 1
                node = node.parent_id
            item.depth = depth

    @api.depends('item_kind', 'max_score', 'weight', 'child_ids',
                 'child_ids.max_score', 'child_ids.weight',
                 'child_ids.child_ids')
    def _compute_rollup(self):
        for item in self:
            if item.item_kind == 'leaf':
                item.rollup_max_score = item.max_score
                item.rollup_weight = item.weight
            else:
                leaves = item._leaf_descendants()
                item.rollup_max_score = sum(leaves.mapped('max_score'))
                item.rollup_weight = sum(leaves.mapped('weight'))

    # ------------------------------------------------------------------
    # 层级工具（只读，供汇总/视图/测试复用）
    # ------------------------------------------------------------------
    def _descendant_items(self):
        """本节点之下的全部节点（含各级分组），成环时安全退出。"""
        self.ensure_one()
        out = self.env['edu.assess.item']
        todo = self.child_ids
        while todo:
            out |= todo
            todo = todo.child_ids - out
        return out

    def _leaf_descendants(self):
        """本节点之下的全部叶子评分项；叶子节点返回自身。"""
        self.ensure_one()
        if self.item_kind == 'leaf':
            return self
        return self._descendant_items().filtered(
            lambda i: i.item_kind == 'leaf')

    # ------------------------------------------------------------------
    # 约束（H1 层级 / H2 权重挂点 / H4 扣分 / H3 双轨 vs 匿名）
    # ------------------------------------------------------------------
    @api.constrains('max_score')
    def _check_max_score(self):
        for item in self:
            if item.item_kind == 'group':
                continue  # 分组节点的满分是派生值（Σ 子项），不校验用户输入
            if item.max_score <= 0:
                raise ValidationError('评分项「%s」的满分必须大于零。' % item.name)

    @api.constrains('weight')
    def _check_weight(self):
        for item in self:
            if item.item_kind == 'group':
                if abs(item.weight - 1.0) > 1e-9:
                    raise ValidationError(
                        '分组节点「%s」不参与权重：它的占比由下级评分项汇总得来。'
                        '请把权重挂在叶子评分项上，本节点保持 1。' % item.name)
                continue
            if item.weight <= 0:
                raise ValidationError('评分项「%s」的权重必须大于零。' % item.name)

    @api.constrains('parent_id', 'item_kind', 'template_id')
    def _check_parent(self):
        """H1 的三条硬约束：同模板 / 上级必须是分组节点 / 深度 ≤ 3（且不能成环）。"""
        for item in self:
            parent = item.parent_id
            if not parent:
                if item.item_kind == 'leaf' and item.child_ids:
                    raise ValidationError(
                        '评分项「%s」自己还有下级，不能再改回叶子节点。' % item.name)
                continue
            if parent == item:
                raise ValidationError('评分项「%s」不能把自己设为上级节点。' % item.name)
            if parent.template_id != item.template_id:
                raise ValidationError(
                    '上级节点「%s」不属于同一个模板：层级只能在模板内部建。'
                    % parent.name)
            if parent.item_kind != 'group':
                raise ValidationError(
                    '「%s」是叶子评分项，不能作为上级节点；'
                    '请先把它改成「分组节点」，或另建一个分组节点。' % parent.name)
            if parent in item._descendant_items():
                raise ValidationError(
                    '层级不能成环：「%s」已经是「%s」的下级，'
                    '不能反过来当它的上级。' % (parent.name, item.name))
            deepest = max([item.depth]
                          + [d.depth for d in item._descendant_items()])
            if deepest > MAX_ITEM_DEPTH:
                raise ValidationError(
                    '层级最多 %d 级（xlsx 表头最多可读三层，冻结表头也要靠固定层数）；'
                    '当前会到第 %d 级。' % (MAX_ITEM_DEPTH, deepest))

    @api.constrains('item_kind', 'track', 'score_mode')
    def _check_kind_fields(self):
        for item in self:
            if item.item_kind != 'group':
                continue
            if item.track != 'single' or item.score_mode != 'add':
                raise ValidationError(
                    '分组节点「%s」不参与打分，评分轨与计分方式只能保持默认'
                    '（单轨 / 加分制）。' % item.name)

    @api.constrains('track', 'item_kind', 'template_id')
    def _check_dual_vs_anonymous(self):
        """H3 硬约束（§5.3）：匿名任务**不允许**双轨项。

        主观路 = 学生自评，身份天然已知；双轨在匿名场景下既无意义，又会把匿名撕开
        一个口子。这里从「项」这一侧拦，另一侧（任务改成匿名）由 task 的约束拦。
        """
        for item in self:
            if item.track != 'dual' or item.item_kind != 'leaf':
                continue
            anonymous = item.template_id.task_ids.filtered(
                lambda t: t.anonymous)
            if anonymous:
                raise ValidationError(
                    '模板「%s」下已有匿名任务（%s），不能把「%s」设为双轨：'
                    '主观路是学生自评，身份天然已知，双轨会让匿名失效。'
                    % (item.template_id.name,
                       '、'.join(anonymous.mapped('name')),
                       item.name))

    @api.ondelete(at_uninstall=False)
    def _unlink_guard(self):
        """有打分记录时拒绝删除，引导改用「停用」（照 edu_portal/models/fees.py 先例）。

        分组节点另有外键 parent_id（ondelete='restrict'）兜底：还有下级时删不掉。
        """
        Score = self.env['edu.assess.score'].sudo()
        for item in self:
            n = Score.search_count([('item_id', '=', item.id)])
            if n:
                raise UserError(
                    '评分项「%s」已有 %d 条打分记录，不能删除；'
                    '请改用「停用」——停用后新打分不再出现该列，'
                    '历史得分仍保留可查。' % (item.name, n))


class EduAssessTask(models.Model):
    _name = 'edu.assess.task'
    _description = '评估任务'
    _order = 'date_begin desc, id desc'

    name = fields.Char(string='任务', compute='_compute_name')
    template_id = fields.Many2one(
        'edu.assess.template', string='评估模板', required=True,
        ondelete='restrict', index=True)
    # 被评对象类型随模板走（store=True：教师侧域收敛与报表要按它过滤）
    target_kind = fields.Selection(
        string='被评对象', related='template_id.target_kind',
        store=True, readonly=True)
    period = fields.Char(
        string='评估周期', required=True,
        default=lambda self: '%s秋' % fields.Date.today().year)
    date_begin = fields.Date(string='开始日期')
    date_due = fields.Date(string='截止日期')
    state = fields.Selection(
        TASK_STATES, string='状态', default='draft', required=True, index=True)
    scope_batch_ids = fields.Many2many(
        'op.batch', 'edu_assess_task_batch_rel', 'task_id', 'batch_id',
        string='参与班级')
    scope_program_ids = fields.Many2many(
        'op.program', 'edu_assess_task_program_rel', 'task_id', 'program_id',
        string='参与专业')
    scorer_kind = fields.Selection(
        SCORER_KINDS, string='打分人', default='teacher', required=True)
    #: F9 双轨两路各由谁填（§5.3 的第 2 件事）。留空 ⇒ 回落到 scorer_kind。
    #: ⚠ 实测（2026-09-28）：Odoo 升级时会把 **Selection 字段的默认值回填给存量行**
    #: （存量 3 个任务被填成 teacher / self），因此「留空回落」这条只对**新记录**里
    #: 用户主动清空的场景生效；存量任务因为模板里没有双轨项，根本不参与双轨取分，
    #: 行为与第 1 期一致（已用存量 8 条打分逐条对拍验证）。
    objective_scorer_kind = fields.Selection(
        SCORER_KINDS, string='客观路打分人', default='teacher',
        help='双轨项的客观路由谁填（默认教师评学生）。留空则跟随上面的「打分人」。')
    subjective_scorer_kind = fields.Selection(
        SCORER_KINDS, string='主观路打分人', default='self',
        help='双轨项的主观路由谁填（默认学生自评）。留空则跟随上面的「打分人」。')
    has_dual = fields.Boolean(
        string='模板含双轨项', compute='_compute_has_dual')
    anonymous = fields.Boolean(
        string='匿名打分', default=False,
        help='匿名任务的打分记录只保存不可反推的指纹，不保存打分人身份；'
             '结果页另有样本门槛，低于门槛不展示任何明细。**匿名任务不能双轨。**')
    summary_min = fields.Integer(
        string='匿名汇总门槛（份）', default=3,
        help='同一被评对象收到的有效打分份数低于该门槛时，结果页不展示任何明细'
             '（防止只评了一两份时被反推）。')
    notes = fields.Text(string='说明')
    active = fields.Boolean(string='启用', default=True)

    roster_ids = fields.One2many(
        'edu.assess.roster', 'task_id', string='名单快照')
    score_ids = fields.One2many(
        'edu.assess.score', 'task_id', string='打分记录')

    roster_count = fields.Integer(
        string='被评对象数', compute='_compute_counts')
    done_count = fields.Integer(string='已评数', compute='_compute_counts')
    score_count = fields.Integer(string='打分条数', compute='_compute_counts')
    scorer_count = fields.Integer(string='答卷份数', compute='_compute_counts')
    progress = fields.Float(string='完成率', compute='_compute_counts')

    @api.depends('template_id.name', 'period')
    def _compute_name(self):
        for task in self:
            task.name = '%s · %s' % (
                task.template_id.name or '评估', task.period or '')

    @api.depends('template_id.item_ids', 'template_id.item_ids.track')
    def _compute_has_dual(self):
        for task in self:
            leaves = task.template_id.with_context(
                active_test=False).item_ids.filtered(
                lambda i: i.item_kind == 'leaf')
            task.has_dual = bool(leaves.filtered(lambda i: i.track == 'dual'))

    @api.depends('roster_ids', 'roster_ids.state', 'score_ids',
                 'score_ids.scorer_ref')
    def _compute_counts(self):
        for task in self:
            task.roster_count = len(task.roster_ids)
            task.done_count = len(
                task.roster_ids.filtered(lambda r: r.state == 'done'))
            task.score_count = len(task.score_ids)
            # 答卷份数 = 不同打分人指纹数（匿名口径下这就是能安全统计的上限）
            task.scorer_count = len(set(task.score_ids.mapped('scorer_ref')))
            task.progress = (
                100.0 * task.done_count / task.roster_count
                if task.roster_count else 0.0)

    @api.constrains('summary_min')
    def _check_summary_min(self):
        for task in self:
            if task.summary_min < 1:
                raise ValidationError('匿名汇总门槛至少为 1 份。')

    @api.constrains('date_begin', 'date_due')
    def _check_dates(self):
        for task in self:
            if task.date_begin and task.date_due \
                    and task.date_begin > task.date_due:
                raise ValidationError('开始日期不能晚于截止日期。')

    @api.constrains('anonymous', 'template_id')
    def _check_dual_anonymous(self):
        """H3 硬约束的另一侧：匿名任务不能挂在含双轨项的模板上（§5.3）。"""
        for task in self:
            if not task.anonymous:
                continue
            duals = task.template_id.with_context(
                active_test=False).item_ids.filtered(
                lambda i: i.item_kind == 'leaf' and i.track == 'dual')
            if duals:
                raise ValidationError(
                    '模板「%s」含双轨评分项（%s），不能设为匿名：'
                    '主观路是学生自评，身份天然已知。'
                    % (task.template_id.name,
                       '、'.join(duals[:5].mapped('name'))))

    @api.constrains('template_id')
    def _check_percent_template(self):
        """建任务前必须 Σ占比 = 100（§5.2.1 的第二道闸门）。"""
        for task in self:
            task.template_id._ensure_percent_ready()

    # ------------------------------------------------------------------
    # 换模板护栏（模型层）—— 2026-09-29
    #   「已有名单/打分就不许换模板」原先只有**门户控制器**一条判据
    #   （controllers/task_admin.py 的 assess_task_save）：在 Odoo 后台直接改
    #   template_id 绕得过去，换掉之后旧打分对不上新的评分项 ⇒ 结果静默错位。
    #   护栏分两处落地 —— Odoo 的机制决定它们各管一件事：
    #     ① write()：判**转移**（旧值 ≠ 新值 且 已有名单/打分）。
    #        @api.constrains 看不到旧值：write() 是**先改库、后跑 constrains**
    #        （odoo/orm/models.py 的 write → _validate_fields；本仓在 odoo:19
    #        镜像里读过源码确认），转移判据只能在 write() 里比新旧值。
    #        ⚠ 只用 constrains 会得到一条**假护栏**：名单行不携带模板信息，
    #        同为 student 类的两个模板之间从状态上看不出「换过」⇒ 红用例拦不住。
    #        同文件先例：EduAssessRoster.write 的「任务结束评语只读」。
    #     ② @api.constrains('template_id')：判**状态**（库里不许存在
    #        「任务的模板 ≠ 打分所属模板」的行）—— 与 EduAssessScore._check_value
    #        的「评分项不属于本任务的模板」互为反向，堵住绕过 write() 的写入口
    #        （外部 SQL、导入、将来新增的入口）。
    #   存量核查（2026-09-29，**只读** psql）：3 任务 / 10 名单 / 8 打分，
    #     「打分项模板 ≠ 任务模板」= 0 条、「名单种类 ≠ target_kind」= 0 条
    #     ⇒ 加约束不动存量，不需要迁移（复核命令见本轮报告）。
    # ------------------------------------------------------------------
    def write(self, vals):
        """有名单/打分后不许换评估模板（**模型层**，闭合后台直写绕过门户）。

        判据与门户控制器一字不差（controllers/task_admin.py 的 assess_task_save）：
        任务一旦有名单或已有打分，就不许再换模板。「原值写回」不算换模板 ——
        后台表单保存会把当前模板一起提交，若不区分，已发布的任务全都存不了。
        """
        if 'template_id' in vals:
            raw = vals['template_id']
            new_id = getattr(raw, 'id', raw) or False
            for task in self:
                if task.template_id.id == new_id:
                    continue          # 原值写回 = 不是换模板（后台表单常态）
                if task.roster_ids or task.score_ids:
                    raise ValidationError(
                        '任务「%s」已经生成名单（%d 行）或已有打分记录（%d 条），'
                        '不能再换评估模板 —— 换掉之后名单与评分项对不上，'
                        '结果会静默错位。请新建一个任务来做这次评估。'
                        % (task.name, len(task.roster_ids), len(task.score_ids)))
        return super().write(vals)

    @api.constrains('template_id')
    def _check_template_matches_scores(self):
        """状态不变量：任务的打分记录必须来自本任务**当前**模板的评分项。

        它拦的是「已经错位」的存量/旁路数据（例：先外部 SQL 换了模板，
        再用 ORM 写回同一个 template_id）—— 这类行一旦落库，结果页与 xlsx
        会按新模板的评分项去索引旧分，**不报错、只算错**。
        """
        for task in self:
            stray = task.score_ids.filtered(
                lambda s: s.item_id.template_id != task.template_id)
            if stray:
                raise ValidationError(
                    '任务「%s」的打分记录里有 %d 条属于**别的模板**的评分项'
                    '（如「%s」）—— 本任务当前的模板与已录分数不一致，'
                    '小计与总分都会静默错位。请把任务改回原模板，'
                    '或新建一个任务重新录分。'
                    % (task.name, len(stray),
                       '、'.join(stray[:3].mapped('item_name'))))

    def _track_scorer_kind(self, track):
        """某一路由谁填（F9）：任务级配置优先，未配置回落到 scorer_kind。"""
        self.ensure_one()
        if track == 'subjective':
            return self.subjective_scorer_kind or self.scorer_kind
        return self.objective_scorer_kind or self.scorer_kind

    def _leaf_items(self):
        """本任务的可打分列（叶子项，含历史停用项；分组节点不是列）。"""
        self.ensure_one()
        return self.template_id._all_leaves().sorted(
            lambda i: (i.sequence, i.id))

    # ------------------------------------------------------------------
    # 名单快照（一行 = 一个被评者）
    # ------------------------------------------------------------------

    def _roster_students(self):
        """参与学生：按参与班级 / 专业收敛；两者都空 = 全部在读学生。"""
        self.ensure_one()
        Student = self.env['op.student'].sudo()
        domain = [('active', '=', True)]
        if self.scope_batch_ids:
            domain.append(('course_detail_ids.batch_id', 'in',
                           self.scope_batch_ids.ids))
        elif self.scope_program_ids:
            domain.append(('course_detail_ids.course_id.program_id', 'in',
                           self.scope_program_ids.ids))
        return Student.search(domain, order='id')

    def _roster_faculties(self):
        """参与教师：指定班级时取任教该班的教师（op.session 口径），否则全部教师。"""
        self.ensure_one()
        Faculty = self.env['op.faculty'].sudo()
        if self.scope_batch_ids:
            fac_ids = self.env['op.session'].sudo().search(
                [('batch_id', 'in', self.scope_batch_ids.ids)]
            ).mapped('faculty_id').ids
            return Faculty.search([('id', 'in', fac_ids)], order='id')
        return Faculty.search([], order='id')

    def _student_batch(self, student):
        """学生在本任务参与范围内的班级（用于教师侧行级收敛的 batch_id 字段）。"""
        self.ensure_one()
        links = student.course_detail_ids.filtered(
            lambda l: l.batch_id
            and (not self.scope_batch_ids
                 or l.batch_id in self.scope_batch_ids))
        if links:
            return links[0].batch_id
        return student.course_detail_ids.filtered(
            lambda l: l.batch_id)[:1].batch_id

    def action_build_roster(self):
        """生成名单快照（幂等：已存在的一行不重复创建）。"""
        for task in self:
            task._build_roster()
        return True

    def _build_roster(self):
        self.ensure_one()
        Roster = self.env['edu.assess.roster'].sudo()
        existing = set(Roster.search(
            [('task_id', '=', self.id)]).mapped('subject_ref'))
        vals_list = []
        if self.target_kind == 'faculty':
            for fac in self._roster_faculties():
                if 'f:%d' % fac.id in existing:
                    continue
                vals_list.append({
                    'task_id': self.id,
                    'faculty_id': fac.id,
                    'subject_ref': 'f:%d' % fac.id,
                })
        else:
            for stu in self._roster_students():
                if 's:%d' % stu.id in existing:
                    continue
                vals_list.append({
                    'task_id': self.id,
                    'student_id': stu.id,
                    'batch_id': self._student_batch(stu).id or False,
                    'subject_ref': 's:%d' % stu.id,
                })
        if vals_list:
            Roster.create(vals_list)
        return len(vals_list)

    def _add_roster_from_text(self, text):
        """W1 名单行手工增删之「批量粘贴名单」（§5.7）。

        一行一个 **学号**（首选）或 **姓名**（仅在唯一时兜底，沿用 xlsx 导入口径）。
        幂等：本任务名单里已有的直接跳过。返回结构化结果，交给页面显示预览。
        """
        self.ensure_one()
        Student = self.env['op.student'].sudo()
        Roster = self.env['edu.assess.roster'].sudo()
        if self.target_kind == 'faculty':
            return {'added': [], 'skipped': [], 'errors': [
                '本任务被评对象是教师：批量粘贴名单只支持学生任务。']}
        exists = set(Roster.search(
            [('task_id', '=', self.id)]).mapped('subject_ref'))
        added, skipped, errors = [], [], []
        for raw in (text or '').replace('\r', '\n').split('\n'):
            token = raw.strip().replace('\t', ' ').strip()
            if not token:
                continue
            token = token.split(' ')[0].split(',')[0].strip()
            if not token:
                continue
            found = Student.search([('gr_no', '=', token)], limit=2)
            if not found:
                found = Student.search([('name', '=', token)], limit=2)
                if len(found) > 1:
                    errors.append('%s：有 %d 个同名同学，请改用学号。'
                                  % (token, len(found)))
                    continue
            if not found:
                errors.append('%s：找不到这个学号/姓名。' % token)
                continue
            stu = found[0]
            ref = 's:%d' % stu.id
            if ref in exists:
                skipped.append('%s（%s）：本任务名单里已有。' % (stu.name, token))
                continue
            Roster.create({
                'task_id': self.id,
                'student_id': stu.id,
                'batch_id': self._student_batch(stu).id or False,
                'subject_ref': ref,
            })
            exists.add(ref)
            added.append('%s（%s）' % (stu.name, token))
        return {'added': added, 'skipped': skipped, 'errors': errors}

    def action_add_roster_from_text(self, text):
        """W1 批量粘贴名单的**对公入口**（门户控制器与验收脚本都走它）。

        为什么需要这层薄壳：Odoo 禁止远程调用下划线开头的方法
        （odoo/orm/utils.py:70-75 + service/model.py:53「Private methods ... cannot be
        called remotely」），而名单粘贴必须能被页面/脚本调用 ⇒ 公开壳 + 私有实现。
        """
        self.ensure_one()
        return self._add_roster_from_text(text)

    def action_open(self):
        """发布：建档 + 名单快照 + 置为进行中。"""
        for task in self:
            task._build_roster()
            task.state = 'open'
        return True

    def action_close(self):
        self.write({'state': 'closed'})
        return True

    def action_reopen(self):
        self.write({'state': 'open'})
        return True


class EduAssessRoster(models.Model):
    _name = 'edu.assess.roster'
    _description = '评估名单快照'
    _order = 'task_id, id'

    task_id = fields.Many2one(
        'edu.assess.task', string='评估任务', required=True,
        ondelete='cascade', index=True)
    student_id = fields.Many2one(
        'op.student', string='被评学生', ondelete='cascade', index=True)
    faculty_id = fields.Many2one(
        'op.faculty', string='被评教师', ondelete='cascade', index=True)
    batch_id = fields.Many2one(
        'op.batch', string='班级', index=True,
        help='被评学生所在班级（教师侧行级规则的收敛依据）。')
    subject_ref = fields.Char(
        string='被评对象键', required=True, index=True, readonly=True,
        help='非空的唯一键（学生 s:<id> / 教师 f:<id>）；'
             '不用可空外键做唯一键 —— Postgres 里 NULL≠NULL，'
             '旧两套就栽在这一条上。')
    state = fields.Selection(
        ROSTER_STATES, string='状态', default='pending', index=True)
    #: F8 整表级评语（H5 / §5.5）：**行级** —— 评语是给这个人的，任务级会串人。
    summary = fields.Text(
        string='导师评语与建议',
        help='整表级评语（一名被评者一条）。学生不给自己写评语；'
             '任务结束后只读（保留历史）。')
    score_ids = fields.One2many(
        'edu.assess.score', 'roster_id', string='打分明细')
    scorer_count = fields.Integer(string='答卷份数', compute='_compute_derived')

    # ------------------------------------------------------------------
    # 派生显示（§3.5：小计 / 合计 / 等级**不落库**，请求时算）
    # ------------------------------------------------------------------
    total = fields.Float(string='总分', compute='_compute_derived')
    weighted_total = fields.Float(string='加权总分', compute='_compute_derived')
    average = fields.Float(string='平均分', compute='_compute_derived')
    scored_item_count = fields.Integer(
        string='已评项数', compute='_compute_derived')
    reachable_max = fields.Float(
        string='可评满分', compute='_compute_derived',
        help='已评项如果都拿满分会得到多少分。用于显示「本模板当前可评满分 92.5 分」'
             '（有评分项没有分数来源时，比如《成绩统计表》未提供）。')
    complete = fields.Boolean(
        string='算分完整', compute='_compute_derived',
        help='必填项都填了、双轨项两路齐全，才算完整。')
    missing_items = fields.Char(
        string='未评项', compute='_compute_derived')
    missing_tracks = fields.Char(
        string='缺一路', compute='_compute_derived',
        help='双轨项缺了哪一路。缺一路时该项**不计入总分**（不按 0 折算、'
             '也不按单路平均）—— 素材 xlsx 的 SUM(F5:G5)/2 会把"学生没填"'
             '静默算成导师分的一半，那是缺陷，不复刻。')
    grade = fields.Char(string='等级', compute='_compute_derived')
    breakdown_text = fields.Text(
        string='分组小计与合计（派生）', compute='_compute_breakdown_text')
    subject_name = fields.Char(
        string='被评对象', compute='_compute_subject_name')

    _roster_subject_uniq = models.Constraint(
        'UNIQUE (task_id, subject_ref)',
        '同一任务里的同一个被评对象只能有一行名单。')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('subject_ref'):
                if vals.get('student_id'):
                    vals['subject_ref'] = 's:%d' % vals['student_id']
                elif vals.get('faculty_id'):
                    vals['subject_ref'] = 'f:%d' % vals['faculty_id']
            # 手工加一行（W1）时补上班级：教师侧行级规则要靠 batch_id 收敛。
            if vals.get('student_id') and not vals.get('batch_id') \
                    and vals.get('task_id'):
                task = self.env['edu.assess.task'].browse(vals['task_id'])
                batch = task._student_batch(
                    self.env['op.student'].browse(vals['student_id']))
                if batch:
                    vals['batch_id'] = batch.id
        return super().create(vals_list)

    def write(self, vals):
        """§5.5-3：任务结束后评语只读（保留历史）。"""
        if 'summary' in vals:
            closed = self.filtered(lambda r: r.task_id.state == 'closed')
            if closed:
                raise UserError(
                    '评估任务已结束，导师评语与建议只读（保留历史）。'
                    '如需修改，请先由教务重新打开任务。')
        return super().write(vals)

    @api.depends('student_id', 'student_id.name', 'faculty_id',
                 'faculty_id.name')
    def _compute_subject_name(self):
        for rec in self:
            subject = rec.faculty_id if rec.faculty_id else rec.student_id
            rec.subject_name = subject.name or ''

    @api.model
    def _subject_domain(self, user=None, published_only=False):
        """「我（学生/教师）是被评者」的收敛域 —— 控制器与报表的**唯一口径**。

        ⚠ 为什么必须收在这里（不是控制器的私事）：安全层的门户规则只认
        student_id.user_id（security/security.xml 的历史口径），而**教师被评的行**
        （评教任务）**batch_id 为空** —— 用 batch_id 收敛教师永远得 0 行，于是
        「被评者本人看不到自己的结果」在教师侧是**数据层**就发生的（实测：
        faculty@local 在评教任务上 search_read 返回 0 行，教务同任务 2 行）。

        :param user: 默认当前用户
        :param published_only: True 时只返回「模板已公开结果」（score_visible=True）
            的行 —— 这是 score_visible 开关在**数据层**的真实消费者，
            与 security.xml 的 rule_edu_assess_roster_subject_read 同构。
        """
        user = user or self.env.user
        domain = ['|', ('student_id.user_id', '=', user.id),
                  '|', ('faculty_id.user_id', '=', user.id),
                  ('faculty_id.partner_id.user_ids', 'in', [user.id])]
        if published_only:
            return [('task_id.template_id.score_visible', '=', True)] + domain
        return domain

    @api.model
    def _my_subject_rows(self, user=None, published_only=False):
        """按上面的口径取行（控制器直接调，不要自己写 domain）。"""
        return self.sudo().search(
            self._subject_domain(user, published_only=published_only))

    def _report_nodes(self):
        """本行要展示 / 汇总的**节点**（分组 + 叶子），供 _breakdown 建树。

        口径：模板里启用的全部节点 + 本行有历史分的停用叶子 + 这些叶子的祖先
        （停用过的中间分组若不补回来，叶子会从树里"消失"）。
        ⚠ 必须是「节点」而不是「叶子」：分组节点是树的根，只取叶子会让
        「叶子全挂在区下面」的表（卫生检测表）一棵树都建不出来（实测踩过）。
        """
        self.ensure_one()
        tpl = self.task_id.template_id
        all_items = tpl.with_context(active_test=False).item_ids
        nodes = all_items.filtered(lambda i: i.active)
        scored_ids = set(self.score_ids.mapped('item_id').ids)
        nodes |= all_items.filtered(
            lambda i: i.item_kind == 'leaf' and i.id in scored_ids)
        for item in nodes:
            parent = item.parent_id
            while parent and parent not in nodes:
                nodes |= parent
                parent = parent.parent_id
        return nodes.sorted(lambda i: (i.sequence, i.id))

    # ------------------------------------------------------------------
    # ★ 唯一的双轨合并入口（设计 §3.5：A3 只允许一处实现）
    # ------------------------------------------------------------------
    def _item_rows(self, item):
        """某评分项在本行下的打分记录。"""
        self.ensure_one()
        return self.score_ids.filtered(lambda s: s.item_id.id == item.id)

    def _item_cell(self, item):
        """一个评分项在本行的**得分**（0 ≤ 得分 ≤ item.max_score）；未评返回 None。

        规则（三条，全部按 score_mode / track 分派）：
          1. **单轨项**：该项下所有打分记录取均值 —— 即第 1 期「N 人评同一维度」的
             口径，逐字节保留（_item_average 第 1 期的行为）。
          2. **双轨项**：先按 track 各自取均值，再 (客观 + 主观) / 2；
             **缺一路 ⇒ None**（D3：不按 0 折算、也不按单路平均）。
          3. **扣分制项**：score.value 存的是「扣掉的分数」⇒ 得分 = 满分 − 扣分。

        ⚠ 这里是全模块**唯一**实现「两路相加除 2」的地方：结果页、xlsx、打印、
        后台派生字段一律调用它，禁止各自再写一遍。
        """
        self.ensure_one()
        rows = self._item_rows(item)
        if not rows:
            return None
        if item.track == 'dual':
            by_track = {}
            for score in rows:
                by_track.setdefault(score.track or 'objective', []).append(
                    score.value)
            objective = by_track.get('objective') or []
            subjective = by_track.get('subjective') or []
            if not objective or not subjective:
                if not ALLOW_PARTIAL_DUAL:
                    return None
                raw = _mean(objective or subjective)
            else:
                raw = (_mean(objective) + _mean(subjective)) / 2.0
        else:
            raw = _mean([s.value for s in rows])
        if raw is None:
            return None
        if item.score_mode == 'deduct':
            return max(item.max_score - raw, 0.0)
        return raw

    def _item_track_state(self, item):
        """双轨项的两路填充情况：(有客观, 有主观)。非双轨项返回 (True, True)。"""
        self.ensure_one()
        if item.track != 'dual':
            return (True, True)
        tracks = set(self._item_rows(item).mapped('track'))
        return ('objective' in tracks, 'subjective' in tracks)

    def _item_contribution(self, item, cell):
        """该项折算进"加权总分"的分值（A1 倍率 / A2 占比，§3.5）。"""
        self.ensure_one()
        tpl = self.task_id.template_id
        if cell is None:
            return None
        if tpl.weight_mode == 'percent':
            top = item.max_score or 0.0
            if not top:
                return 0.0
            return (cell / top) * ((item.weight or 0.0) / 100.0) \
                * (tpl.total or 0.0)
        return cell * (item.weight or 1.0)

    def _group_subtotal(self, item):
        """分组节点的派生小计 = 其下（递归）叶子得分之和（不落库）。"""
        self.ensure_one()
        cells = [self._item_cell(leaf) for leaf in item._leaf_descendants()]
        cells = [c for c in cells if c is not None]
        return sum(cells) if cells else None

    def _breakdown(self):
        """派生：本行的层级汇总（一级 → 二级 → 叶子），**不落库**（§3.5）。

        返回 [{'item','depth','kind','subtotal','contribution','weight',
        'weight_sum','children'}]；结果页 / xlsx 小计行 / 打印都应当调用它，
        不要各自再遍历一遍 item_ids（那会再长出一份"小计算法"）。
        """
        self.ensure_one()
        items = self._report_nodes()

        def node(item):
            if item.item_kind == 'leaf':
                cell = self._item_cell(item)
                return {
                    'item': item, 'depth': item.depth, 'kind': 'leaf',
                    'subtotal': cell,
                    'contribution': self._item_contribution(item, cell),
                    'weight': item.weight, 'weight_sum': item.weight,
                    'children': [],
                }
            children = [
                node(child) for child in items.filtered(
                    lambda i: i.parent_id == item).sorted(
                    lambda i: (i.sequence, i.id))]
            subtotals = [c['subtotal'] for c in children
                         if c['subtotal'] is not None]
            return {
                'item': item, 'depth': item.depth, 'kind': 'group',
                'subtotal': sum(subtotals) if subtotals else None,
                'contribution': None,
                'weight': None,
                'weight_sum': sum(c['weight_sum'] or 0.0
                                  for c in children),
                'children': children,
            }

        roots = items.filtered(lambda i: not i.parent_id).sorted(
            lambda i: (i.sequence, i.id))
        return [node(root) for root in roots]

    @api.depends('score_ids', 'score_ids.value', 'score_ids.track',
                 'score_ids.item_id', 'score_ids.item_id.weight',
                 'score_ids.item_id.track', 'score_ids.item_id.score_mode',
                 'score_ids.item_id.max_score', 'score_ids.item_id.item_kind',
                 'score_ids.item_id.required', 'score_ids.item_id.active',
                 'score_ids.scorer_ref',
                 'task_id.template_id.weight_mode',
                 'task_id.template_id.total',
                 'task_id.template_id.item_ids',
                 'task_id.template_id.item_ids.weight')
    def _compute_derived(self):
        """行总分 / 加权总分 / 平均分 / 等级 / 完整度 / 未评项 —— 全部派生、不落库。

        ⚠ 两处第 1 期的静默算错在这里修掉：
          ① average = total / len(refs)：除数是**打分人份数**。双轨落库后，
             客观路与主观路会算成"两个人"，把总分**静默砍半**。
          ② _item_average：把该项下所有 score 行不加区分地平均（两轨被平均掉）。
        ⇒ 现在两者都只走 _item_cell（唯一合并入口），分母改为「已评项数」。
        """
        for rec in self:
            tpl = rec.task_id.template_id
            percent = tpl.weight_mode == 'percent'
            leaves = tpl._all_leaves()
            total = 0.0
            weighted = 0.0
            reachable = 0.0
            scored_n = 0
            missing_items = []
            missing_tracks = set()
            mandatory_missing = False
            for item in leaves.sorted(lambda i: (i.sequence, i.id)):
                cell = rec._item_cell(item)
                if cell is None:
                    has_rows = bool(rec._item_rows(item))
                    if has_rows and item.track == 'dual':
                        has_obj, has_sub = rec._item_track_state(item)
                        if not has_obj:
                            missing_tracks.add('客观')
                        if not has_sub:
                            missing_tracks.add('主观')
                    else:
                        missing_items.append(item.name)
                        if item.required:
                            mandatory_missing = True
                    continue
                scored_n += 1
                total += cell
                contribution = rec._item_contribution(item, cell)
                weighted += contribution or 0.0
                if percent:
                    reachable += ((item.weight or 0.0) / 100.0) \
                        * (tpl.total or 0.0)
                else:
                    reachable += (item.max_score or 0.0) * (item.weight or 1.0)
            rec.total = total
            rec.weighted_total = weighted
            rec.average = (total / scored_n) if scored_n else 0.0
            rec.scored_item_count = scored_n
            rec.reachable_max = reachable
            rec.missing_items = '、'.join(missing_items[:8])
            rec.missing_tracks = '、'.join(sorted(missing_tracks))
            rec.complete = bool(scored_n) and not mandatory_missing \
                and not missing_tracks
            rec.grade = tpl._grade_of(weighted) \
                if (scored_n and rec.complete) else ''
            rec.scorer_count = len(set(rec.score_ids.mapped('scorer_ref')))

    @api.depends('score_ids', 'score_ids.value', 'score_ids.track',
                 'score_ids.item_id',
                 'task_id.template_id.weight_mode',
                 'task_id.template_id.item_ids')
    def _compute_breakdown_text(self):
        """把派生小计 / 合计渲染成一段可读文字（后台表单与结果页都用它）。"""
        for rec in self:
            tpl = rec.task_id.template_id
            percent = tpl.weight_mode == 'percent'
            lines = []

            def walk(nodes, indent):
                for node in nodes:
                    pad = '　' * indent
                    item = node['item']
                    if node['kind'] == 'leaf':
                        if node['subtotal'] is None:
                            lines.append('%s· %s：未评' % (pad, item.name))
                            continue
                        lines.append(
                            '%s· %s：%.2f（权重 %g%s，计入 %.2f）' % (
                                pad, item.name, node['subtotal'],
                                item.weight, '%' if percent else '',
                                node['contribution'] or 0.0))
                    else:
                        subtotal = node['subtotal']
                        lines.append(
                            '%s【%s】小计 %s（派生占比 %g%s）' % (
                                pad, item.name,
                                '未评' if subtotal is None
                                else '%.2f' % subtotal,
                                node['weight_sum'],
                                '%' if percent else ''))
                        walk(node['children'], indent + 1)

            walk(rec._breakdown(), 0)
            lines.append(
                '合计：总分 %.2f / 加权总分 %.2f / 平均分 %.2f / 等级 %s'
                % (rec.total, rec.weighted_total, rec.average,
                   rec.grade or '（未判级）'))
            if rec.missing_tracks:
                lines.append('⚠ 缺一路：%s（该项不计入总分）'
                             % rec.missing_tracks)
            if rec.missing_items:
                lines.append('未评项：%s' % rec.missing_items)
            if rec.reachable_max:
                lines.append('可评满分：%.2f' % rec.reachable_max)
            rec.breakdown_text = '\n'.join(lines)

    @api.constrains('student_id', 'faculty_id')
    def _check_subject(self):
        for rec in self:
            if bool(rec.student_id) == bool(rec.faculty_id):
                raise ValidationError('名单行必须且只能有一个被评对象（学生或教师）。')

    @api.ondelete(at_uninstall=False)
    def _unlink_guard(self):
        """W1 的硬护栏（§5.7 约束 2）：有打分的行拒删，保住历史。

        本行不引入 roster 级「停用」位（不在 §3.3 的 12 字段清单里）⇒ 报错文案
        直接告诉用户两条出路：先删掉对应的打分记录，或保留该行。
        """
        for rec in self:
            if rec.score_ids:
                raise UserError(
                    '名单行「%s」已有 %d 条打分记录，不能删除（历史要保留）。'
                    '若确实不再评估此人，请先删除对应的打分记录。'
                    % (rec.subject_name or rec.subject_ref, len(rec.score_ids)))

    def _item_average(self, item):
        """某评分项在本行的分（**第 1 期的名字保留**：门户 3 个读点直接用它）。

        ⚠ 第 2 期修正：不再"把所有 score 行不加区分地平均"—— 改为走唯一入口
        _item_cell：双轨按 track 配对取平均、扣分项按 score_mode 转成得分。
        对第 1 期那种"单轨 + 加分 + 多人评同一项"的数据，两者**结果逐条相同**。
        """
        self.ensure_one()
        return self._item_cell(item)


class EduAssessScore(models.Model):
    _name = 'edu.assess.score'
    _description = '评估打分记录'
    _order = 'task_id, roster_id, item_id, id'

    task_id = fields.Many2one(
        'edu.assess.task', string='评估任务', required=True,
        ondelete='cascade', index=True)
    item_id = fields.Many2one(
        'edu.assess.item', string='评分项', required=True,
        ondelete='restrict', index=True)
    roster_id = fields.Many2one(
        'edu.assess.roster', string='被评对象', required=True,
        ondelete='cascade', index=True)
    #: F10 打分轨：单轨项恒 objective；双轨项客观/主观各一条（F11 唯一键因此要加它）。
    track = fields.Selection(
        SCORE_TRACKS, string='轨', default='objective', required=True,
        help='单轨项恒为「客观」；双轨项的客观分与主观分各存一条记录。')
    value = fields.Float(
        string='得分',
        help='加分制项存得分（0 ~ 满分）；扣分制项存**实际扣掉的分数**（0 = 未扣）。')
    note = fields.Text(string='评语')
    scorer_id = fields.Many2one(
        'res.users', string='打分人', ondelete='set null', index=True,
        help='**仅实名口径**写入；匿名任务的记录一律为空。')
    scorer_ref = fields.Char(
        string='打分人指纹', required=True, index=True,
        help='匿名任务 = h:<HMAC 指纹>（不可反推身份，但可查重）；'
             '实名任务 = u:<用户 id>；xlsx 导入 = i:<用户 id>。')
    item_name = fields.Char(string='评分项名', related='item_id.name')
    task_anonymous = fields.Boolean(
        string='匿名任务', related='task_id.anonymous')

    #: F11：唯一键追加 track —— 否则"同一个导师既给客观分又给主观分"写不进第二条。
    _score_uniq = models.Constraint(
        'UNIQUE (task_id, item_id, roster_id, scorer_ref, track)',
        '同一任务、同一评分项、同一被评对象、同一打分人、同一轨道只能有一条记录'
        '（重复提交按幂等更新处理）。')

    def init(self):
        """第 2 期新增列 track 的等值回填。

        **为什么必须写在本模型自己的 init() 里**：理由与列存在性守卫见
        EduAssessItem.init() 的同段说明 —— Odoo 逐模型跑 _auto_init() → init()，
        跨表回填在顺序上没有保证（2026-09-28 生产事故：这条 UPDATE 原先写在
        EduAssessTemplate.init() 里，而那时本表还没有 track 列）。
        """
        cr = self.env.cr
        if column_exists(cr, 'edu_assess_score', 'track'):
            cr.execute(
                "UPDATE edu_assess_score SET track = 'objective' "
                "WHERE track IS NULL")
        return super().init()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('scorer_ref'):
                vals['scorer_ref'] = 'u:%s' % (
                    vals.get('scorer_id') or self.env.uid)
            # 单轨项只有一条轨：不写 track 的调用方（xlsx 导入、门户旧路径）
            # 默认落 objective，与 F10「单轨项恒 objective」一致。
            if not vals.get('track'):
                vals['track'] = 'objective'
        return super().create(vals_list)

    @api.constrains('value', 'item_id', 'track', 'task_id')
    def _check_value(self):
        for rec in self:
            item = rec.item_id
            if item.item_kind != 'leaf':
                raise ValidationError(
                    '「%s」是分组节点，不参与打分：它的小计由下级评分项汇总。'
                    '请把分数填到它下面的具体评分项上。' % item.name)
            if item.template_id != rec.task_id.template_id:
                raise ValidationError(
                    '评分项「%s」不属于本任务的模板：跨模板打分会让总分算错。'
                    % item.name)
            if item.track == 'single' and rec.track != 'objective':
                raise ValidationError(
                    '「%s」是单轨评分项，只有一条轨（客观）；'
                    '要分客观/主观请先把该评分项设为双轨。' % item.name)
            top = item.max_score or 0.0
            if rec.value < 0 or rec.value > top:
                if item.score_mode == 'deduct':
                    raise ValidationError(
                        '「%s」是扣分制：扣分须在 0 ~ %g 之间（0 = 未扣）。'
                        % (item.name, top))
                raise ValidationError(
                    '「%s」得分须在 0 ~ %g 之间。' % (item.name, top))
            if item.score_kind == 'level':
                anchors = item.template_id._anchor_values()
                if anchors and abs(rec.value) > 1e-9 \
                        and not any(abs(rec.value - a) < 1e-9
                                    for a in anchors):
                    raise ValidationError(
                        '「%s」是档位型评分项：取值必须是模板的刻度锚点之一'
                        '（%s）。' % (item.name,
                                    '、'.join('%g' % a for a in anchors)))


class ResUsers(models.Model):
    """教师侧行级规则的收敛依据（纵深防御；见 security/security.xml）。"""
    _inherit = 'res.users'

    edu_taught_batch_ids = fields.Many2many(
        'op.batch', string='任教班级',
        compute='_compute_edu_taught_batch_ids',
        help='本人任教班级（op.session.faculty_id 口径），供行级权限使用。')

    @api.depends('partner_id')
    def _compute_edu_taught_batch_ids(self):
        Faculty = self.env['op.faculty'].sudo()
        Session = self.env['op.session'].sudo()
        for user in self:
            fac = Faculty.search([('user_id', '=', user.id)], limit=1)
            batches = Session.search(
                [('faculty_id', '=', fac.id)]).mapped('batch_id') if fac \
                else self.env['op.batch'].browse()
            user.edu_taught_batch_ids = batches
