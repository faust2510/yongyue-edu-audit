# -*- coding: utf-8 -*-
"""模板与评分项 —— 门户原生管理页（教务自助，不必再进 Odoo 后台）。

## 为什么有这个文件

评估相关能力此前 **10 条路由都在门户**，唯独「模板与评分项」只能从
`views/assess_portal.xml` 的「评估管理」卡片跳到
`/odoo/action-edu_assess.action_edu_assess_template`（Odoo 官方后台列表视图，蓝顶栏）。
教务因此必须**离开门户 UI** 才能建模板、加评分项 —— 这正是本次要消掉的那一段。

本文件把那部分能力搬进门户，用与门户其它页**同一套**体例
（`edu_portal.edu_page` 外壳、卡片、`btn btn-sm`、`/my/home` 面包屑、`?saved=1` 回执），
不新造视觉体系。

## 只做 CRUD，不碰模型

本文件只对 **既有** `edu.assess.template` 与 `edu.assess.item` 做增删改查：
**不新增字段、不新增模型、不改任何约束、不动 ACL**（`security/**` 一行未改）。
下拉选项**直接从 `models/assess.py` 的常量取**
（KIND_SELECTION / TARGET_KINDS / TEMPLATE_STATES / SCORE_KINDS）——
枚举只有一个来源，将来加值这里自动跟上，不会出现「模型有、界面没有」的第二份名单。
表单提交的枚举值再按同一批常量**白名单校验**：非法值一律拒绝，不接受手改表单注入。

## 区块化（为下一步的 12 个字段留位）

界面按区块组织，每个区块 = `docs/plans/eval-unified-design.md` §4 边界表的一段。
新增维度只往**对应区块里加一行**，不动页面结构：

  · 区块 A「模板基本信息」  §4 #1–#3（名称 / 说明 / 评估类型 / 被评对象）
  · 区块 B「分值与等级线」  §4 #4–#6、#10（满分 / 及格线 / 优秀线；「启用等级线」开关落此区块）
  · 区块 C「可见性与自评」  §4 #22–#23（结果对被评者可见 / 允许自评）
  · 区块 D「评分项」        §4 #9–#13、#15–#18（增删改 / 排序 / 停用；weight_mode、
                            track、score_mode、层级 parent_id 都将落在这个区块的项表里）

目标对象 `target_kind` **不写死为 student**（§4 #3 明确要求新增能力与 target_kind 正交），
选项表直接来自模型常量，将来放开 `faculty` 之外的值不需要改模板。

## 权限（四层收口，code-map §6.12 第 3 条）

门禁型管理页 ⇒ 用 `edu_portal.controllers.roles.privileged_staff()`
（教务处组 ∪ 系统组）放行，与 `/downloads` 管理模式、`/ledger`、`/notice/publish`
**同一口径**，本文件不自造第二套判据（那正是 code-map §6 反复点名的那类返工）。

非授权一律 **fail-closed**：进函数第一件事就是判身份，判空**直接 303 回 `/my/home`**
（与 `/assess/my`、`/assess/review` 的既有写法逐字同款），**不 fallthrough、不做
「隐藏按钮」式的假权限** —— 后者等于没做权限。四个写路由全部
`methods=['POST']` + `csrf=True`，且**先判权限再解析任何参数**。
"""
import logging

import psycopg2

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.edu_portal.controllers.roles import privileged_staff

from ..models.assess import (
    KIND_SELECTION, SCORE_KINDS, TARGET_KINDS, TEMPLATE_STATES)

_logger = logging.getLogger(__name__)

#: 复选框字段（表单里"勾选 = 1 / 未勾选 = 不提交"）
TPL_CHECKS = ('active', 'score_visible', 'allow_self')
ITEM_CHECKS = ('required', 'active')

#: 表单里可编辑的模板字段（区块 A/B/C 的全集）。顺序 = 页面区块顺序。
TPL_FIELDS = ('name', 'kind', 'target_kind', 'total', 'pass_line',
              'excellent_line', 'score_visible', 'allow_self', 'state', 'notes',
              'active')


# ----------------------------------------------------------------------
# 小工具（与本模块既有控制器同口径，不发明第二套）
# ----------------------------------------------------------------------

def _deny():
    """fail-closed 的唯一落点：非教务/超管一律 303 回门户首页。"""
    return request.redirect('/my/home')


def _is_allowed():
    return privileged_staff()


def _num(raw):
    """表单里的数字：空串 / 非法一律返回 None（**不静默当成 0** —— 0 是合法满分/权重）。"""
    if raw is None or str(raw).strip() == '':
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _flag(raw):
    """复选框 → bool（未勾选时浏览器根本不提交该键）。"""
    return str(raw or '').strip().lower() in ('1', 'true', 'on', 'yes')


def _text(raw, limit=None):
    val = (raw or '').strip()
    if limit:
        val = val[:limit]
    return val


def _need_choice(raw, choices, default):
    """枚举白名单：只接受 `models/assess.py` 常量里现有的值，否则回落到默认值。"""
    val = (raw or '').strip()
    return val if val in dict(choices) else default


def _templates(include_inactive):
    """模板集合。默认口径 = 后台列表视图的默认口径（隐藏已停用）；`?inactive=1` 才带出。"""
    Tmpl = request.env['edu.assess.template'].sudo()
    if include_inactive:
        Tmpl = Tmpl.with_context(active_test=False)
    return Tmpl.search([])


def _template(template_id):
    """按 id 取模板（含已停用），不存在返回空记录集。"""
    return (request.env['edu.assess.template'].sudo()
            .with_context(active_test=False).browse(int(template_id or 0)))


def _items(template):
    """某模板下的评分项，按 (sequence, id) 排 —— 排序口径与门户矩阵列序同源。

    **含已停用项**：停用是「新打分不再出现该列」，不是删除；管理页必须还能看到并恢复它。
    """
    return (request.env['edu.assess.item'].sudo()
            .with_context(active_test=False)
            .search([('template_id', '=', template.id)]))


def _form_values(tpl):
    """表单初值：编辑 = 记录现值；新建 = **模型自己的字段默认值**（`default_get`）。

    为什么不在这里写一份默认值：那会是第二份「默认」定义，模型改了默认值而这里没跟，
    表单就会撒谎。`default_get` 让初值与模型永远同源。
    """
    if tpl:
        return {f: tpl[f] for f in TPL_FIELDS}
    defaults = request.env['edu.assess.template'].sudo().default_get(
        list(TPL_FIELDS))
    return {f: defaults.get(f) for f in TPL_FIELDS}


def _back(path, **params):
    """回跳（带提示）。`saved=1` / `error=<人话>` —— 与 /assess/fill 的 ?saved=1 同款。"""
    clean = {k: v for k, v in params.items() if v not in (None, '')}
    if not clean:
        return request.redirect(path)
    return request.redirect_query(path, clean)


def _write_or_error(model, make_and_apply):
    """把一次写库包进 savepoint，把**两类用户级失败**统一变成可读文案。

    返回 `(结果, 错误文案)`：成功 = (结果, None)，失败 = (None, 人话)。

    ### 为什么必须抓两族异常（本页实测踩到过，别删）
      · `UserError`：模型的 `@api.constrains`（等级线）与 `@api.ondelete` 守卫
        （有打分的评分项拒删）当场抛，直接可读；
      · **`psycopg2.IntegrityError`**：SQL 级约束（评分项同模板名称唯一、
        外键 restrict）。⚠ Odoo **在控制器之外**才把它翻成人话 ——
        `odoo/service/model.py:213` 的 `retrying()` 包着 `serve_func`，
        转换发生在我们的 `try` **外面**。实测（2026-09-28）：只接 UserError 时，
        重名评分项会吐一张 **HTTP 422 的 Odoo 错误页**，把用户甩出门户 UI。

    文案**不自己编**：用 Odoo 自己的 `_sql_error_to_message()`，
    它读的正是同一张 `ir.model.constraint` / `models.Constraint.message` 表，
    所以门户与后台看到的是**逐字同一句**（不制造第二份约束文案）。
    """
    try:
        with request.env.cr.savepoint():
            return make_and_apply(), None
    except UserError as exc:
        _logger.info('assess admin write rejected (user error): %s', exc)
        return None, str(exc)
    except psycopg2.IntegrityError as exc:
        _logger.info('assess admin write rejected (db constraint): %s', exc)
        try:
            return None, model._sql_error_to_message(exc)
        except Exception:                    # 连文案都生成不出来时也不甩 500
            _logger.warning('生成约束文案失败，回退为通用提示', exc_info=True)
            return None, '保存失败：与已有数据冲突（%s）。' % (
                (exc.diag.constraint_name if exc.diag else '') or '唯一性约束')


def _audit(action, res_model, res_id, res_name, detail):
    """审计留痕（本模块既有口径：`edu.audit.log._log`）。"""
    request.env['edu.audit.log'].sudo()._log(
        action, res_model, res_id, res_name, detail)


# ----------------------------------------------------------------------
# 门户页面
# ----------------------------------------------------------------------

class EduAssessTemplateAdmin(http.Controller):
    """模板与评分项：列表 / 新建 / 编辑 / 停用恢复 / 评分项增删改。"""

    # ---------------- 页面 ----------------

    @http.route('/assess/templates', type='http', auth='user', website=True)
    def assess_templates(self, saved=None, error=None, inactive=None, **kw):
        if not _is_allowed():
            return _deny()
        show_inactive = bool(inactive)
        templates = _templates(show_inactive)
        rows = [{'tpl': tpl, 'items': _items(tpl)} for tpl in templates]
        return request.render('edu_assess.edu_assess_templates', {
            'title': '模板与评分项',
            'page_name': 'assess_templates',
            'rows': rows,
            'show_inactive': show_inactive,
            'saved': saved,
            'error': error,
            'kinds': dict(KIND_SELECTION),
            'targets': dict(TARGET_KINDS),
            'states': dict(TEMPLATE_STATES),
            'score_kinds': dict(SCORE_KINDS),
        })

    @http.route('/assess/templates/new', type='http', auth='user',
                website=True)
    def assess_template_new(self, error=None, **kw):
        if not _is_allowed():
            return _deny()
        return request.render('edu_assess.edu_assess_template_form', {
            'title': '新建模板',
            'page_name': 'assess_template_new',
            'tpl': None,
            'v': _form_values(None),
            'items': [],
            'error': error,
            'kinds': dict(KIND_SELECTION),
            'targets': dict(TARGET_KINDS),
            'states': dict(TEMPLATE_STATES),
            'score_kinds': dict(SCORE_KINDS),
        })

    @http.route('/assess/templates/<int:template_id>', type='http',
                auth='user', website=True)
    def assess_template_edit(self, template_id, saved=None, error=None, **kw):
        if not _is_allowed():
            return _deny()
        tpl = _template(template_id)
        if not tpl.exists():
            return _back('/assess/templates', error='模板不存在或已被删除。')
        return request.render('edu_assess.edu_assess_template_form', {
            'title': '编辑模板',
            'page_name': 'assess_template_edit',
            'tpl': tpl,
            'v': _form_values(tpl),
            'items': _items(tpl),
            'saved': saved,
            'error': error,
            'kinds': dict(KIND_SELECTION),
            'targets': dict(TARGET_KINDS),
            'states': dict(TEMPLATE_STATES),
            'score_kinds': dict(SCORE_KINDS),
        })

    # ---------------- 写路由 ----------------

    @http.route('/assess/templates/save', type='http', methods=['POST'],
                auth='user', website=True, csrf=True)
    def assess_template_save(self, **post):
        """新建（无 template_id）或编辑（有 template_id）一个模板。"""
        if not _is_allowed():
            return _deny()
        template_id = (post.get('template_id') or '').strip()
        back = ('/assess/templates/%s' % template_id if template_id
                else '/assess/templates/new')

        name = _text(post.get('name'), 200)
        if not name:
            return _back(back, error='模板名称不能为空。')
        vals = {
            'name': name,
            'kind': _need_choice(post.get('kind'), KIND_SELECTION, 'teaching'),
            'target_kind': _need_choice(
                post.get('target_kind'), TARGET_KINDS, 'faculty'),
            'state': _need_choice(post.get('state'), TEMPLATE_STATES, 'active'),
            'notes': _text(post.get('notes')) or False,
        }
        for field, label in (('total', '满分'), ('pass_line', '及格线'),
                             ('excellent_line', '优秀线')):
            value = _num(post.get(field))
            if value is None:
                return _back(back, error='「%s」必须填数字。' % label)
            vals[field] = value
        for field in TPL_CHECKS:
            vals[field] = _flag(post.get(field))

        Tmpl = request.env['edu.assess.template'].sudo()
        if template_id:
            tpl = _template(template_id)
            if not tpl.exists():
                return _back('/assess/templates', error='模板不存在或已被删除。')
            _res, err = _write_or_error(Tmpl, lambda: tpl.write(vals))
        else:
            tpl, err = _write_or_error(Tmpl, lambda: Tmpl.create(vals))
        if err:
            # 等级线 / 唯一性等约束由模型把关（不在这里复写一遍规则）；失败回表单说人话
            return _back(back, error=err)
        _audit('评估模板保存' if template_id else '评估模板新建',
               'edu.assess.template', tpl.id, tpl.name,
               ('编辑模板「%s」' if template_id else '新建模板「%s」') % tpl.name)
        return _back('/assess/templates/%d' % tpl.id, saved=1)

    @http.route('/assess/templates/<int:template_id>/state', type='http',
                methods=['POST'], auth='user', website=True, csrf=True)
    def assess_template_state(self, template_id, **post):
        """停用 / 恢复：`active` 与 `state` 一起走（停用即归档，恢复即启用）。"""
        if not _is_allowed():
            return _deny()
        action = (post.get('action') or '').strip()
        if action not in ('deactivate', 'restore'):
            return _back('/assess/templates', error='未知操作。')
        tpl = _template(template_id)
        if not tpl.exists():
            return _back('/assess/templates', error='模板不存在或已被删除。')
        vals = ({'active': False, 'state': 'archived'} if action == 'deactivate'
                else {'active': True, 'state': 'active'})
        _res, err = _write_or_error(
            request.env['edu.assess.template'].sudo(), lambda: tpl.write(vals))
        if err:
            return _back('/assess/templates', error=err)
        _audit('评估模板停用' if action == 'deactivate' else '评估模板恢复',
               'edu.assess.template', tpl.id, tpl.name,
               '%s模板「%s」' % ('停用' if action == 'deactivate' else '恢复',
                                tpl.name))
        return _back('/assess/templates', saved=1)

    @http.route('/assess/templates/<int:template_id>/items/save',
                type='http', methods=['POST'], auth='user', website=True,
                csrf=True)
    def assess_item_save(self, template_id, **post):
        """新增（无 item_id）或编辑（有 item_id）一个评分项。"""
        if not _is_allowed():
            return _deny()
        tpl = _template(template_id)
        if not tpl.exists():
            return _back('/assess/templates', error='模板不存在或已被删除。')
        back = '/assess/templates/%d' % tpl.id
        item_id = (post.get('item_id') or '').strip()

        name = _text(post.get('name'), 200)
        if not name:
            return _back(back, error='评分项名称不能为空。')
        max_score = _num(post.get('max_score'))
        weight = _num(post.get('weight'))
        sequence = _num(post.get('sequence'))
        if max_score is None:
            return _back(back, error='评分项「%s」的满分必须填数字。' % name)
        if weight is None:
            return _back(back, error='评分项「%s」的权重必须填数字。' % name)
        vals = {
            'template_id': tpl.id,
            'name': name,
            'max_score': max_score,
            'weight': weight,
            'sequence': int(sequence) if sequence is not None else 10,
            'help': _text(post.get('help'), 200) or False,
            'score_kind': _need_choice(
                post.get('score_kind'), SCORE_KINDS, 'number'),
        }
        for field in ITEM_CHECKS:
            vals[field] = _flag(post.get(field))

        Item = request.env['edu.assess.item'].sudo().with_context(
            active_test=False)
        if item_id:
            item = Item.browse(int(item_id))
            if not item.exists() or item.template_id.id != tpl.id:
                return _back(back, error='评分项不存在或不属于该模板。')
            _res, err = _write_or_error(Item, lambda: item.write(vals))
        else:
            item, err = _write_or_error(Item, lambda: Item.create(vals))
        if err:
            # 「同模板内名称不重复」「满分/权重必须大于零」等由模型把关
            return _back(back, error=err)
        _audit('评估评分项保存', 'edu.assess.item', item.id, item.name,
               '模板「%s」·%s评分项「%s」'
               % (tpl.name, '编辑' if item_id else '新增', item.name))
        return _back(back, saved=1)

    @http.route('/assess/templates/<int:template_id>/items/<int:item_id>/delete',
                type='http', methods=['POST'], auth='user', website=True,
                csrf=True)
    def assess_item_delete(self, template_id, item_id, **post):
        """删除评分项。**有打分记录时模型会拒绝**（引导改用停用）—— 这里照实回显。"""
        if not _is_allowed():
            return _deny()
        tpl = _template(template_id)
        if not tpl.exists():
            return _back('/assess/templates', error='模板不存在或已被删除。')
        back = '/assess/templates/%d' % tpl.id
        item = (request.env['edu.assess.item'].sudo()
                .with_context(active_test=False).browse(int(item_id or 0)))
        if not item.exists() or item.template_id.id != tpl.id:
            return _back(back, error='评分项不存在或不属于该模板。')
        name = item.name
        _res, err = _write_or_error(
            request.env['edu.assess.item'].sudo(), item.unlink)
        if err:
            return _back(back, error=err)
        _audit('评估评分项删除', 'edu.assess.item', item_id, name,
               '模板「%s」·删除评分项「%s」' % (tpl.name, name))
        return _back(back, saved=1)
