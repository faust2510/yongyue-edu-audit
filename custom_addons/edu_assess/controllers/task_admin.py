# -*- coding: utf-8 -*-
"""评估任务生命周期 —— 门户原生管理页（教务自助：新建 / 发布 / 名单 / 结束）。

## 为什么有这个文件（这是「割裂感」的真正根因那一环）

门户此前**已经有**评估的大部分能力：/assess、/assess/my、/assess/fill、/assess/grade、
/assess/review、/assess/task/<id>/results、导出空表、导出结果、xlsx 导入 ——
填表、打分、看结果、导出全在门户。

**唯独「评估任务」本身（新建 / 发布 / 排名单 / 结束）在门户上没有入口**，只能进
Odoo 后台做（已核：`controllers/portal.py` 与 `template_admin.py` 的全部 route 里
没有任务管理）。而用户极度厌恶后台 ⇒ 任务建了、发布了，**没人去后台把它结束**。
实测（2026-09-28，本地 edu19）：3 个任务全部 `open`、`closed` = 0 ⇒
`/assess/my` 的「我收到的评估结果」永远是空的 ⇒ **学生看不到任何评估结果**。

本文件把这段生命周期搬进门户，用与门户其它页**同一套**体例
（`edu_portal.edu_page` 外壳、卡片、`btn btn-sm`、`?saved=1` 回执），不新造视觉体系。

## 零新模型 / 零新字段

只用**既有**模型与**既有**字段：`edu.assess.task`（含它自己的
`action_open` / `action_close` / `action_reopen` / `action_build_roster` /
`action_add_roster_from_text`）、`edu.assess.roster`、`edu.assess.template`。
`models/assess.py`、`security/**`、`views/assess_template_admin.xml` 一行未改。

**发布/结束一律走模型自己的 `action_*`**（不在控制器里再写一遍 `state = 'open'`）——
状态机只有一份实现，后台与门户不会各走各的。控制器只负责三件事：
① 门禁；② 参数解析与白名单；③ **守卫**（见下）与人话回执。

## 权限（四层收口，code-map §6.12 第 3 条）

门禁型管理页 ⇒ `edu_portal.controllers.roles.privileged_staff()`
（教务处组 ∪ 系统组）放行，与 `/downloads` 管理模式、`/assess/templates`、
`/ledger` **同一口径**，本文件不自造第二套判据。

非授权一律 **fail-closed**：进函数第一件事就是判身份，判空**直接 303 回 `/my/home`**
（与 `/assess/my`、`template_admin.py` 的既有写法逐字同款）—— 不 fallthrough、
不做「隐藏按钮」式的假权限。9 条路由全部 `auth='user'`（未登录走 Odoo 登录兜底）、
5 条写路由全部 `methods=['POST']` + `csrf=True`，且**先判权限再解析任何参数**。

## 守卫（本文件的核心交付，逐条给理由；没有一条是"静默放行"）

**发布 draft → open**（四条硬拦，全部在写库前判）
  1. 只有 `draft` 能发布（状态机不跳级）；
  2. 模板必须是启用状态 —— 否则学生侧 `/assess` 页自己就把它过滤掉了（`template_id.state =
     'active'`），发布了也没人看得见；
  3. 模板必须**至少有一个可打分的叶子项** —— 没有列 ⇒ 矩阵是空的，发布出来是个死任务；
  4. `action_open()` 会顺带建名单快照，**名单为空则整笔回滚**（savepoint）并报错。
     这条直接对着本次的病根：名单空 ⇒ 永远收不到打分 ⇒ 结束后 `/assess/my` 还是空的。

**结束 open → closed**（三条"必须显式确认"，不勾选一律拒绝并回显数字）
  1. 还有被评对象一行分都没收到（`roster.state != 'done'`）⇒ 提示"结束后他们的结果会
     永久停在未评"，列出**具体人数**；
  2. **匿名任务**且有效答卷份数 < 匿名门槛 ⇒ 明确写出"结束后谁都不会看到明细"
     （结果页与 /assess/my 都会显示样本不足）—— 这正是"发布了个看不见的任务"的复发点；
  3. 模板设了"结果不对被评者公开" ⇒ 明确写出"结束后学生端不会出现这次结果"。
  **为什么是"确认"而不是"硬拦"**：一个班 30 人里总有人不填，硬拦会把教务锁死在
  "永远结束不了"里 —— 那正是本次要消灭的那种"链子断在半路"。所以放行但要**知情**：
  确认后照常结束，未评人数/答卷份数**写进审计**（`edu.audit.log`），事后可查。

**重新打开 closed → open**：永远要显式确认，因为 /assess/my 只展示 `state = 'closed'`
的任务 ⇒ 一重开，被评者端这次结果**立刻消失**。

**名单增删**
  · 任务 `closed` 时**冻结名单**（生成/添加/删除全部拒绝，提示先重新打开）——
    已结束的历史名单不该再长出新行；
  · 删除一行时**双钉**：既要它属于本任务（`task_id`），又要它自己的被评对象外键
    （`student_id` / `faculty_id`）与派生键 `subject_ref` **互相对得上**。
    只认 `subject_ref` 是不够的 —— 它是普通 Char 且 RPC 可写，单独用它收敛会被伪造；
  · **有打分记录的行拒绝删除**（`score.roster_id` 是 ondelete='cascade'，删名单会
    静默连带删掉打分）。口径与评分项一致（`edu.assess.item` 也是"有数据拒删、
    引导改用停用"），不静默丢数据。

**改任务**
  · 已有名单或已有打分的任务**不许换模板**：换掉之后旧打分指向的评分项属于另一个
    模板，结果页会静默错位（模型层没有这条约束，故放在页面守卫里，报告已写明）；
  · 范围（批/专业）随时可改，但**不会自动改已生成的名单**（名单是快照）——
    页面明说，要补用「按范围生成名单」（幂等增量，不删已有行）。

## 一处与 `template_admin.py` 的关系（有意为之，不是复制）

表单解析/回执/审计/写库包装（`_back` `_num` `_flag` `_text` `_need_choice`
`_write_or_error` `_audit`）**从 `template_admin` import**，不复制第二份 ——
两页同一套体例、同一套错误文案。只有"门禁"这两个函数（`_is_allowed` / `_deny`）
本地写：它们必须**直接**落在 `privileged_staff()` 上（本文件受命复用的口径就是它），
不隔着另一个文件的内部函数。

## 实测得到的两条 Odoo 19 事实（别绕回去）

1. `@http.route` 的 `**post` 拿不到**多选值**：`Request.get_http_params()` 是
   `{**args, **form, **files}`（odoo/http.py），同名键只留**第一个**值 ⇒
   多选框（班级/专业）必须走 `request.httprequest.form.getlist()`（见 `_form_list`）。
2. 表单里 `<select>` 的"留空"要真的能表达"跟随打分人"：Selection 字段写 `False`
   是合法值（不是 `''`），故 `_choice_or_false` 把空串/非法值统一折成 `False`。
"""
import datetime
import logging

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.edu_portal.controllers.roles import privileged_staff

from ..models.assess import (
    ROSTER_STATES, SCORER_KINDS, TASK_STATES, TARGET_KINDS)
from .template_admin import (
    _audit, _back, _flag, _need_choice, _text, _write_or_error)

_logger = logging.getLogger(__name__)

#: 表单里可编辑的任务字段（全集；顺序 = 页面区块顺序）
TASK_FIELDS = ('template_id', 'period', 'date_begin', 'date_due',
               'scope_batch_ids', 'scope_program_ids', 'scorer_kind',
               'objective_scorer_kind', 'subjective_scorer_kind',
               'anonymous', 'summary_min', 'notes', 'active')
#: 复选框字段（表单里"勾选 = 1 / 未勾选 = 不提交"）
TASK_CHECKS = ('anonymous', 'active')
#: 生命周期动作 ⇒ 模型入口（**状态机只有模型那一份实现**）
TASK_ACTIONS = {'open': 'action_open', 'close': 'action_close',
                'reopen': 'action_reopen'}
ACTION_LABELS = {'open': '发布', 'close': '结束', 'reopen': '重新打开'}
STATE_LABELS = dict(TASK_STATES)


# ----------------------------------------------------------------------
# 门禁 + 小工具
# ----------------------------------------------------------------------

def _is_allowed():
    """门禁（唯一判据）：教务处组 ∪ 系统组 —— code-map §6.12 第 3 条的"业务管理"层。

    直接落在 `privileged_staff()` 上（与 /downloads 管理模式、/assess/templates、
    /ledger 同款），本文件不写第二套身份判据。
    """
    return privileged_staff()


def _deny():
    """fail-closed 的唯一落点：非教务/超管一律 303 回门户首页。"""
    return request.redirect('/my/home')


def _int(raw):
    """整数表单值；空串/非数字返回 None（**不静默转 0** —— 0 是合法的外键"空"）。"""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _as_int(raw):
    """查询串里的计数（`?added=3`）→ int；缺省 / 非数字 → None（模板据此决定显不显示）。"""
    val = (raw or '').strip()
    return int(val) if val.isdigit() else None


def _date(raw):
    """日期表单值 → 原样 ISO 串。

    返回：`False` = 用户留空（合法，两个日期都可空）；`None` = 格式非法（拒绝）。
    "空"与"非法"必须分开 —— 混成一个值会让留空被判成错误、或让乱填静默入库。
    """
    val = (raw or '').strip()
    if not val:
        return False
    try:
        datetime.datetime.strptime(val, '%Y-%m-%d')
    except ValueError:
        return None
    return val


def _choice_or_false(raw, choices):
    """Selection 的"留空"侧：空串 / 非法值统一折成 `False`（表示"跟随打分人"）。"""
    val = (raw or '').strip()
    return val if val in dict(choices) else False


def _form_list(key):
    """多选值：从 werkzeug 的 MultiDict 取**全部**同名值。

    为什么不用路由 `**post`：Odoo 19 的 `Request.get_http_params()` 是
    `{**self.httprequest.args, **self.httprequest.form, **self.httprequest.files}`，
    同名键只留第一个值 ⇒ `post.get('scope_batch_ids')` 拿不到多选的全集（已读源码核实）。
    """
    try:
        raw = request.httprequest.form.getlist(key)
    except Exception:                                     # 表单非 urlencoded 时不炸页面
        _logger.warning('读取多选参数失败：%s', key, exc_info=True)
        return []
    return [str(v).strip() for v in raw if str(v).strip()]


def _checked_ids(key, model):
    """多选白名单：只保留**库里确实存在**的 id。

    空集是合法语义（模型口径：范围为空 = 全部在读学生 / 全部教师），
    但"伪造的 id"必须被丢掉，不能让表单注入任意主键。
    """
    ids = set()
    for value in _form_list(key):
        num = _int(value)
        if num is not None:
            ids.add(num)
    if not ids:
        return []
    return request.env[model].sudo().search(
        [('id', 'in', sorted(ids))]).ids


# ----------------------------------------------------------------------
# 数据读取（门户页一律 sudo + 页内显式收敛到"本任务"，口径同 template_admin）
# ----------------------------------------------------------------------

def _tasks():
    """全部任务（含已停用），按模型自己的 _order。"""
    return (request.env['edu.assess.task'].sudo()
            .with_context(active_test=False).search([]))


def _task(task_id):
    """按 id 取任务（含已停用）；不存在返回空记录集。"""
    return (request.env['edu.assess.task'].sudo()
            .with_context(active_test=False).browse(_int(task_id) or 0))


def _templates():
    """模板集合（含已停用；停用的照常显示并标注，便于老任务继续引用）。"""
    return (request.env['edu.assess.template'].sudo()
            .with_context(active_test=False).search([]))


def _task_stats(task):
    """任务进度读数（与模型 `_compute_counts` 同口径，只是额外拆出"未评行数"）。"""
    rosters = task.roster_ids
    pending = rosters.filtered(lambda r: r.state != 'done')
    refs = set(task.score_ids.mapped('scorer_ref'))
    return {
        'roster_n': len(rosters),
        'done_n': len(rosters) - len(pending),
        'pending_n': len(pending),
        'score_n': len(task.score_ids),
        'refs_n': len(refs),
        'progress': task.progress,
    }


def _leaf_items(template):
    """模板里**可打分**的叶子项（停用的不算列）。"""
    return [i for i in template.with_context(active_test=False).item_ids
            if i.item_kind == 'leaf' and i.active]


def _close_warnings(task):
    """结束前的守卫清单（人话列表；空 = 无风险可直接结束）。

    三条分别对应三类"结束后才发现不对"的情形；**不给硬拦**（会把教务锁死在
    "永远结束不了"），但**没有勾选确认就不放行**（见模块 docstring 的守卫一节）。
    """
    out = []
    pending = task.roster_ids.filtered(lambda r: r.state != 'done')
    if pending:
        out.append(
            '还有 %d 名被评对象一行分都没收到（名单共 %d 行）—— 结束后他们的结果会永远 '
            '停在"未评"。' % (len(pending), len(task.roster_ids)))
    refs = len(set(task.score_ids.mapped('scorer_ref')))
    if task.anonymous and refs < task.summary_min:
        out.append(
            '这是匿名任务，当前有效答卷只有 %d 份，低于匿名汇总门槛 %d 份 —— 结束后'
            '结果页与学生的"我的评估"都**不会**显示任何明细（会显示样本不足）。'
            % (refs, task.summary_min))
    if not task.template_id.score_visible:
        out.append(
            '模板「%s」设为"结果不对被评者公开"—— 结束后学生端不会出现这次结果。'
            % task.template_id.name)
    return out


def _task_form_values(task):
    """表单初值：编辑 = 记录现值（日期转成 input[type=date] 要的 ISO 串）；
    新建 = **模型自己的字段默认值**（`default_get`，不在页面写第二份默认值）。
    """
    if task:
        return {
            'template_id': task.template_id.id or 0,
            'period': task.period or '',
            'date_begin': task.date_begin.strftime('%Y-%m-%d')
                          if task.date_begin else '',
            'date_due': task.date_due.strftime('%Y-%m-%d') if task.date_due else '',
            'scope_batch_ids': task.scope_batch_ids.ids,
            'scope_program_ids': task.scope_program_ids.ids,
            'scorer_kind': task.scorer_kind or '',
            'objective_scorer_kind': task.objective_scorer_kind or '',
            'subjective_scorer_kind': task.subjective_scorer_kind or '',
            'anonymous': bool(task.anonymous),
            'summary_min': int(task.summary_min or 0),
            'notes': task.notes or '',
            'active': bool(task.active),
        }
    defaults = request.env['edu.assess.task'].sudo().default_get(
        list(TASK_FIELDS))
    return {
        'template_id': 0,
        'period': defaults.get('period') or '',
        'date_begin': '',
        'date_due': '',
        'scope_batch_ids': [],
        'scope_program_ids': [],
        'scorer_kind': defaults.get('scorer_kind') or 'teacher',
        'objective_scorer_kind': defaults.get('objective_scorer_kind') or '',
        'subjective_scorer_kind': defaults.get('subjective_scorer_kind') or '',
        'anonymous': bool(defaults.get('anonymous')),
        'summary_min': int(defaults.get('summary_min') or 3),
        'notes': '',
        'active': True,
    }


def _roster_rows(task):
    """名单表行：学生任务显示学号，教师任务显示"教师"（`op.faculty` 没有工号列）。"""
    faculty_target = task.target_kind == 'faculty'
    rows = []
    for row in task.roster_ids:
        subject = row.faculty_id if faculty_target else row.student_id
        rows.append({
            'id': row.id,
            'name': subject.name or '（对象已删除）',
            'gr_no': '' if faculty_target else (getattr(subject, 'gr_no', '') or ''),
            'batch': row.batch_id.name or '',
            'state': dict(ROSTER_STATES).get(row.state, row.state),
            'done': row.state == 'done',
            'score_n': len(row.score_ids),
            # 有打分的行不给删除按钮：score.roster_id 是 ondelete='cascade'，
            # 删名单会静默连带删掉打分（与 edu.assess.item 的护栏同口径）。
            'deletable': not row.score_ids and bool(subject),
        })
    return rows


def _task_page(task, **extra):
    """任务页渲染（列表/表单/名单三页共用一份 context 建造，避免三处漂移）。"""
    ctx = {
        'title': '评估任务',
        'page_name': 'assess_task_admin',
        'task': task,
        'v': _task_form_values(task),
        'templates': _templates(),
        'batches': request.env['op.batch'].sudo().search([]),
        'programs': request.env['op.program'].sudo().search([]),
        'states': STATE_LABELS,
        # 状态徽标配色只在这里定义一次：模板里用 class 名字，不再散落三处三元表达式
        'state_badges': {'draft': 'text-bg-secondary', 'open': 'text-bg-primary',
                         'closed': 'text-bg-success'},
        'scorers': dict(SCORER_KINDS),
        'targets': dict(TARGET_KINDS),
    }
    ctx.update(extra)
    return ctx


# ----------------------------------------------------------------------
# 门户页面
# ----------------------------------------------------------------------

def _guard_task(task_id):
    """任务类页面的共用前置：权限 + 任务存在。

    为什么抽出来（2026-10-02）：这 5 行在 6 个路由里**逐字重复**（实测 6 处 byte-identical）。
    其中「任务不存在或已被删除。」与回跳目标写在那 6 份拷贝里 —— 改一次措辞就要改 6 处，
    漏一处就会出现两种提示。抽成一处后，改一次即全站一致。
    返回 (task, resp)：resp 非空即应当直接 return 它（权限不足 / 任务不存在）。
    """
    if not _is_allowed():
        return None, _deny()
    task = _task(task_id)
    if not task.exists():
        return None, _back('/assess/tasks', error='任务不存在或已被删除。')
    return task, None

class EduAssessTaskAdmin(http.Controller):
    """评估任务：列表 / 新建 / 编辑 / 发布 / 结束 / 重新打开 / 名单管理。"""

    # ---------------- 页面 ----------------

    @http.route('/assess/tasks', type='http', auth='user', website=True)
    def assess_tasks(self, saved=None, error=None, **kw):
        """任务列表：一条任务一行，状态/进度/三个入口（管理、名单、结果）。"""
        if not _is_allowed():
            return _deny()
        rows = []
        for task in _tasks():
            row = {'task': task}
            row.update(_task_stats(task))
            rows.append(row)
        # 草稿排最前（还没发布的最需要人手处理），其余按模型自己的顺序
        rows.sort(key=lambda r: (r['task'].state != 'draft', r['task'].id))
        return request.render('edu_assess.edu_assess_tasks', _task_page(
            None, rows=rows, saved=saved, error=error))

    @http.route('/assess/tasks/new', type='http', auth='user', website=True)
    def assess_task_new(self, error=None, **kw):
        """新建任务表单（初值 = 模型默认值）。"""
        if not _is_allowed():
            return _deny()
        return request.render('edu_assess.edu_assess_task_form', _task_page(
            None, error=error, is_new=True))

    @http.route('/assess/tasks/<int:task_id>', type='http', auth='user',
                website=True)
    def assess_task_edit(self, task_id, saved=None, error=None, **kw):
        """任务详情：基本信息表单 + 生命周期动作（发布/结束/重开）。"""
        task, denied = _guard_task(task_id)
        if denied:
            return denied
        return request.render('edu_assess.edu_assess_task_form', _task_page(
            task, saved=saved, error=error, is_new=False,
            stats=_task_stats(task), warnings=_close_warnings(task)))

    @http.route('/assess/tasks/<int:task_id>/roster', type='http', auth='user',
                website=True)
    def assess_task_roster(self, task_id, saved=None, error=None, added=None,
                           skipped=None, **kw):
        """名单管理页：按范围生成（幂等）、手工添加、逐行移除。"""
        task, denied = _guard_task(task_id)
        if denied:
            return denied
        return request.render('edu_assess.edu_assess_task_roster', _task_page(
            task, saved=saved, error=error,
            added=_as_int(added), skipped=_as_int(skipped),
            stats=_task_stats(task), rows=_roster_rows(task)))

    # ---------------- 写路由 ----------------

    @http.route('/assess/tasks/save', type='http', methods=['POST'],
                auth='user', website=True, csrf=True)
    def assess_task_save(self, **post):
        """新建（无 task_id）或编辑（有 task_id）一个评估任务。

        **先判权限，再解析任何参数**（template_admin 的同款纪律）。
        """
        if not _is_allowed():
            return _deny()
        raw_id = (post.get('task_id') or '').strip()
        back = '/assess/tasks/%s' % (raw_id or 'new')
        task = _task(raw_id) if raw_id else None

        template = (request.env['edu.assess.template'].sudo()
                    .with_context(active_test=False)
                    .browse(_int(post.get('template_id')) or 0))
        if not template.exists():
            return _back(back, error='请选择一个评估模板（模板不存在或已被删除）。')

        period = _text(post.get('period'), 200)
        if not period:
            return _back(back, error='「评估周期」不能为空（例：2026春）。')

        dates = {}
        for field, label in (('date_begin', '开始日期'), ('date_due', '截止日期')):
            value = _date(post.get(field))
            if value is None:
                return _back(back, error='「%s」必须写成 2026-09-01 这样的日期，'
                                         '或留空。' % label)
            dates[field] = value
        if dates['date_begin'] and dates['date_due'] \
                and dates['date_begin'] > dates['date_due']:
            return _back(back, error='开始日期不能晚于截止日期。')

        summary_min = _int(post.get('summary_min'))
        if summary_min is None or summary_min < 1:
            return _back(back, error='匿名汇总门槛必须是 1 以上的整数。')

        if task and task.exists() and template.id != task.template_id.id \
                and (task.roster_ids or task.score_ids):
            return _back(back, error='本任务已经生成名单或已有打分记录，不能再换评估模板 '
                                     '—— 换掉之后旧打分对不上新的评分项，结果会静默错位。'
                                     '请新建一个任务来做这次评估。')

        vals = {
            'template_id': template.id,
            'period': period,
            'date_begin': dates['date_begin'],
            'date_due': dates['date_due'],
            'scope_batch_ids': [(6, 0, _checked_ids('scope_batch_ids', 'op.batch'))],
            'scope_program_ids': [(6, 0, _checked_ids('scope_program_ids',
                                                      'op.program'))],
            'scorer_kind': _need_choice(post.get('scorer_kind'), SCORER_KINDS,
                                        'teacher'),
            'objective_scorer_kind': _choice_or_false(
                post.get('objective_scorer_kind'), SCORER_KINDS),
            'subjective_scorer_kind': _choice_or_false(
                post.get('subjective_scorer_kind'), SCORER_KINDS),
            'summary_min': summary_min,
            'notes': _text(post.get('notes')) or False,
        }
        for field in TASK_CHECKS:
            vals[field] = _flag(post.get(field))

        Task = request.env['edu.assess.task'].sudo()
        if task and task.exists():
            _res, err = _write_or_error(Task, lambda: task.write(vals))
        else:
            task, err = _write_or_error(Task, lambda: Task.create(vals))
        if err:
            # 日期顺序 / 匿名不能双轨 / 占比不等于 100 等约束由模型把关，
            # 这里只把它的原话回显（不在这里复写一遍规则）
            return _back(back, error=err)
        _audit('评估任务保存' if raw_id else '评估任务新建', 'edu.assess.task',
               task.id, task.name,
               '%s任务「%s」（模板：%s，周期：%s）'
               % ('编辑' if raw_id else '新建', task.name,
                  task.template_id.name, task.period))
        return _back('/assess/tasks/%d' % task.id, saved=1)

    @http.route('/assess/tasks/<int:task_id>/state', type='http',
                methods=['POST'], auth='user', website=True, csrf=True)
    def assess_task_state(self, task_id, **post):
        """生命周期：发布（draft→open）/ 结束（open→closed）/ 重新打开（closed→open）。

        一律调用模型自己的 `action_open` / `action_close` / `action_reopen`：
        状态机不在控制器里再写一遍（否则后台与门户会各有一套）。
        """
        task, denied = _guard_task(task_id)
        if denied:
            return denied
        back = '/assess/tasks/%d' % task.id
        action = (post.get('action') or '').strip()
        if action not in TASK_ACTIONS:
            return _back(back, error='未知操作。')
        current = STATE_LABELS.get(task.state, task.state)

        # ---- 发布 ----
        if action == 'open':
            if task.state != 'draft':
                return _back(back, error='只有「草稿」状态的任务可以发布'
                                         '（当前：%s）。' % current)
            template = task.template_id
            if not template.active or template.state != 'active':
                return _back(back, error='模板「%s」不是「启用」状态，发布了学生端也'
                                         '看不到 —— 请先到「模板与评分项」把它启用。'
                             % template.name)
            if not _leaf_items(template):
                return _back(back, error='模板「%s」没有一个可打分的评分项（叶子项），'
                                         '发布会得到一个空矩阵 —— 请先到'
                                         '「模板与评分项」加评分项。' % template.name)

            def _publish():
                task.action_open()
                if not task.roster_ids:
                    raise UserError(
                        '发布失败：按当前评估范围生成不出任何被评对象（名单是空的）——'
                        '请先在「评估范围」里选班级或专业，或确认范围内确实有在读学生。'
                        '名单为空的任务收不到任何打分，结束后被评者那边也不会出现结果。')

            _res, err = _write_or_error(request.env['edu.assess.task'].sudo(),
                                        _publish)
            if err:
                return _back(back, error=err)
            _audit('评估任务发布', 'edu.assess.task', task.id, task.name,
                   '发布任务「%s」：草稿 → 进行中；名单 %d 行。'
                   % (task.name, len(task.roster_ids)))
            return _back(back, saved=1)

        # ---- 结束 ----
        if action == 'close':
            if task.state != 'open':
                return _back(back, error='只有「进行中」的任务可以结束'
                                         '（当前：%s）。' % current)
            warnings = _close_warnings(task)
            if warnings and not _flag(post.get('confirm')):
                return _back(back, error='结束前请先确认以下 %d 条（勾选页面上的'
                                         '确认框后重试）：%s'
                             % (len(warnings), '；'.join(warnings)))
            pending = len(task.roster_ids.filtered(lambda r: r.state != 'done'))
            refs = len(set(task.score_ids.mapped('scorer_ref')))
            _res, err = _write_or_error(request.env['edu.assess.task'].sudo(),
                                        task.action_close)
            if err:
                return _back(back, error=err)
            _audit('评估任务结束', 'edu.assess.task', task.id, task.name,
                   '结束任务「%s」：进行中 → 已结束；名单 %d 行（未评 %d 行）、'
                   '答卷 %d 份%s。'
                   % (task.name, len(task.roster_ids), pending, refs,
                      '；结束前已确认 %d 条风险提示' % len(warnings)
                      if warnings else ''))
            return _back(back, saved=1)

        # ---- 重新打开 ----
        if task.state != 'closed':
            return _back(back, error='只有「已结束」的任务可以重新打开'
                                     '（当前：%s）。' % current)
        if not _flag(post.get('confirm')):
            return _back(back, error='重新打开后，被评者（学生）端这次结果会立刻消失'
                                     '（"我的评估"只展示已结束的任务）—— 确认后请再'
                                     '点一次。')
        _res, err = _write_or_error(request.env['edu.assess.task'].sudo(),
                                    task.action_reopen)
        if err:
            return _back(back, error=err)
        _audit('评估任务重开', 'edu.assess.task', task.id, task.name,
               '重新打开任务「%s」：已结束 → 进行中。' % task.name)
        return _back(back, saved=1)

    @http.route('/assess/tasks/<int:task_id>/roster/build', type='http',
                methods=['POST'], auth='user', website=True, csrf=True)
    def assess_task_roster_build(self, task_id, **post):
        """按范围生成/补齐名单（幂等增量：已在名单里的不重复建、一行不删）。"""
        task, denied = _guard_task(task_id)
        if denied:
            return denied
        back = '/assess/tasks/%d/roster' % task.id
        if task.state == 'closed':
            return _back(back, error='任务已结束：名单已冻结。如需增删名单，'
                                     '请先回任务页「重新打开」。')
        before = len(task.roster_ids)
        _res, err = _write_or_error(request.env['edu.assess.task'].sudo(),
                                    task.action_build_roster)
        if err:
            return _back(back, error=err)
        after = len(task.roster_ids)
        _audit('评估名单生成', 'edu.assess.roster', task.id, task.name,
               '按范围生成名单：新增 %d 行（%d → %d）。'
               % (after - before, before, after))
        return _back(back, saved=1, added=after - before)

    @http.route('/assess/tasks/<int:task_id>/roster/add', type='http',
                methods=['POST'], auth='user', website=True, csrf=True)
    def assess_task_roster_add(self, task_id, **post):
        """手工添加名单行（一行一个学号/姓名；设计 §5.7 W1 的手工增删）。"""
        task, denied = _guard_task(task_id)
        if denied:
            return denied
        back = '/assess/tasks/%d/roster' % task.id
        if task.state == 'closed':
            return _back(back, error='任务已结束：名单已冻结。如需增删名单，'
                                     '请先回任务页「重新打开」。')
        text = _text(post.get('names'), 20000)
        if not text:
            return _back(back, error='请填写要加入名单的学号或姓名（一行一个）。')
        if task.target_kind == 'faculty':
            result = _add_faculty_from_text(task, text)
        else:
            # 学生侧走模型自己的对公入口（学号优先、重名/找不到都报人话）
            result = task.action_add_roster_from_text(text)
        _audit('评估名单手工添加', 'edu.assess.roster', task.id, task.name,
               '手工添加名单：新增 %d 行、跳过 %d 行、失败 %d 行。'
               % (len(result['added']), len(result['skipped']),
                  len(result['errors'])))
        # 逐条明细走查询串（与 template_admin 的 ?error=<人话> 同款），最多回显 3 条
        detail = '；'.join(result['errors'][:3])
        return _back(back, saved=1, added=len(result['added']),
                     skipped=len(result['skipped']),
                     error=detail or None)

    @http.route('/assess/tasks/<int:task_id>/roster/<int:roster_id>/delete',
                type='http', methods=['POST'], auth='user', website=True,
                csrf=True)
    def assess_task_roster_delete(self, task_id, roster_id, **post):
        """逐条移除名单行（**双钉** + 有打分拒删，见模块 docstring）。"""
        task, denied = _guard_task(task_id)
        if denied:
            return denied
        back = '/assess/tasks/%d/roster' % task.id
        if task.state == 'closed':
            return _back(back, error='任务已结束：名单已冻结。如需增删名单，'
                                     '请先回任务页「重新打开」。')
        Roster = request.env['edu.assess.roster'].sudo()
        # 第一钉：这一行必须属于本任务（不能拿别的任务的 roster_id 来删）
        row = Roster.search([('id', '=', int(roster_id or 0)),
                             ('task_id', '=', task.id)], limit=1)
        if not row.exists():
            return _back(back, error='名单行不存在或不属于该任务。')
        # 第二钉：行自己的被评对象外键必须与派生键 subject_ref 对得上。
        # 只认 subject_ref 是不够的 —— 它是普通 Char，RPC 可写，可被伪造成别的对象。
        faculty_target = task.target_kind == 'faculty'
        subject = row.faculty_id if faculty_target else row.student_id
        expected_ref = ('f:%d' % subject.id) if faculty_target \
            else ('s:%d' % subject.id)
        if not subject or row.subject_ref != expected_ref:
            _logger.warning('名单行 %s 的被评对象与 subject_ref 不一致：%s',
                            row.id, row.subject_ref)
            return _back(back, error='这一行的被评对象与任务口径不一致，拒绝删除'
                                     '（数据异常，请联系管理员）。')
        if row.score_ids:
            return _back(back, error='「%s」已有 %d 条打分记录，不能从名单移除 ——'
                                     '删除会连带删掉这些打分（不可恢复）。'
                                     '如确需留档，先到结果页导出。'
                             % (subject.name or '', len(row.score_ids)))
        name = subject.name or ''
        _res, err = _write_or_error(Roster, row.unlink)
        if err:
            return _back(back, error=err)
        _audit('评估名单移除', 'edu.assess.roster', task.id, task.name,
               '从任务「%s」的名单里移除「%s」。' % (task.name, name))
        return _back(back, saved=1)


# ----------------------------------------------------------------------
# 教师任务的「手工添加名单」
# ----------------------------------------------------------------------

def _add_faculty_from_text(task, text):
    """教师任务的手工添加：一行一个**姓名**（唯一才接受）。

    为什么这一段在控制器里：模型的对公入口 `action_add_roster_from_text` 明确
    **只支持学生任务**（学号优先 / 姓名兜底），被评对象=教师时直接返回错误。
    门户不能因此把教务赶回后台，故这里补上教师一侧，并**逐条对齐**那侧的口径：
    找不到 → 报错；重名 → 报错让人换唯一标识（`op.faculty` 没有工号列，
    姓名是当前库里唯一可用的标识）；已在名单里 → 跳过；其余逐行新建
    （`subject_ref` 由模型的 create 兜底生成，这里只显式给出被评对象外键）。
    """
    Faculty = request.env['op.faculty'].sudo()
    Roster = request.env['edu.assess.roster'].sudo()
    exists = set(Roster.search([('task_id', '=', task.id)]).mapped('subject_ref'))
    added, skipped, errors = [], [], []
    for raw in (text or '').replace('\r', '\n').split('\n'):
        token = raw.strip()
        if not token:
            continue
        found = Faculty.search([('name', '=', token)], limit=2)
        if not found:
            errors.append('%s：找不到这位教师。' % token)
            continue
        if len(found) > 1:
            errors.append('%s：有 %d 位同名教师，无法确定是哪一位。'
                          % (token, len(found)))
            continue
        ref = 'f:%d' % found[0].id
        if ref in exists:
            skipped.append('%s：本任务名单里已有。' % token)
            continue
        Roster.create({'task_id': task.id, 'faculty_id': found[0].id})
        exists.add(ref)
        added.append(token)
    return {'added': added, 'skipped': skipped, 'errors': errors}
