# -*- coding: utf-8 -*-
"""后台菜单/动作改名（与 views/menu_labels.xml 配套）：**只有 noupdate 记录走这条 ORM 路**。

一次 noupdate，两处咬人（2026-09-22 本地实测 + Odoo 19 源码取证）：
  ① **声明式 <record forcecreate="0"> 被静默跳过**：这批改名 4 条记录里 3 条
     （菜单 265 / 动作 380 / 动作 388）声明式一次就生效，唯独菜单 259 的 xmlid
     openeducat_core.menu_op_faculty_main 在 ir_model_data 里 noupdate = t
     ⇒ 升级 exit 0、日志无异常，而 ir_ui_menu.name->>'en_US' 实测**仍是 Faculties**。
     复现 SQL：
       SELECT module||'.'||name, noupdate FROM ir_model_data
         WHERE model='ir.ui.menu' AND res_id IN (259, 265);
       → menu_op_faculty_main = t ／ menu_op_department_sub = f
  ② **PO 覆盖也到不了它**（改了 source 后中文仍是旧名）：Odoo 19 译文导入器的规则是
     odoo/tools/translate.py:1609-1610、1663 ——
       「For a record with 'noupdate' in ir_model_data, its existing translations will be
         overwritten if force_overwrite or (not noupdate and overwrite)」
     ⇒ -u 配 --i18n-overwrite（overwrite=True, force_overwrite=False）**对 noupdate 记录无效**
     —— 那是本仓文档说的「-u 必须带 --i18n-overwrite」的下一层：带了也没用。
     实测：动作 388 zh=教职员工（noupdate=f），菜单 259 zh 仍是「院系」（noupdate=t），
     两者在同一个 PO 词条里、同一次 -u edu_zh。

处置（本文件）：先把这个 xmlid 的 noupdate 规范成 False（幂等、查不到就跳过），再写
source 名；中文仍交给 edu_zh 的 PO（用户可见中文一律不写进 Python）。
规范之后 259 与它的三个兄弟记录行为一致：基座即使重装/升级把名字写回来，
下一次 -u edu_portal 加 -u edu_zh 即自愈（升级顺序见 menu_labels.xml 头注释）。

写法照 models/menu_reachability.py 的先例：按 xmlid 查、**查不到就跳过并记日志**
（升级永不因改名失败而中断）、值相同不写（幂等，可重复 -u）。
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# (记录 xmlid, 新的 source 名, 为什么改)。中文词条在 edu_zh/i18n_extra/*.po。
RENAMES = [
    ('openeducat_core.menu_op_faculty_main', 'Teaching Staff',
     '它就是 op.faculty（教职员工人事档案），不是「院系」；且为 noupdate=t 记录'),
]


# (记录 xmlid, 为什么停用)。与 RENAMES 同一套纪律：noupdate 先规范、值相同不写、缺记录跳过。
RETIRE_MENUS = [
    ('edu_portal.menu_edu_checkin_mgmt',
     '指向已退休的 edu.daily.checkin（数据停在 2026-09-17）；'
     '现役同类入口在 edu_life「灵命生活 → 打卡记录」（读 edu.checkin.record）'),
    # 2026-10-03（第 59 轮后台菜单复核）：**这是本仓自己文档里写着「收口未做」的那件事的用户可见部分**。
    # docs/plans/README.md:44 「④ 评估收口第二步：旧两套（edu.eval.* in edu_portal / …）冻结 → 备份 → 删除
    # （新建的 edu_assess 已上线，旧两套仍在仓内且仍被引用）｜🟡 设计完成，收口未做」。
    # 实测症状：后台「综合评估」下**并排 6 个菜单**，其中两个**同名「评估任务」**
    #   （edu_portal 的 menu_edu_eval_task → edu.eval.task，1 条**无名字**的残留记录；
    #    edu_assess 的 menu_edu_assess_task → edu.assess.task，4 条真实验收任务）
    # ⇒ 教务点进去分不清哪套是现役。
    # 本轮只停**菜单**（用户可见的那一半），不动物理表/代码 —— 与文档里「冻结→备份→删除」的次序一致，
    # 且完全可逆（把 xmlid 从本表移走、重跑本函数即可）。
    ('edu_portal.menu_edu_eval_task',
     '旧一套评估（edu.eval.*）的入口，已被 edu_assess 取代（见 docs/plans/README.md:44「收口未做」）；'
     '与 edu_assess 的同名菜单「评估任务」并排显示，教务分不清 ⇒ 本轮停用之，保留 edu_assess 那套'),
    ('edu_portal.menu_edu_eval_template',
     '同上：旧一套评估（edu.eval.template）的入口，已被 edu_assess「模板与评分项」取代'),
    # ⚠ 2026-10-14：**根应用 588 绝不能停用** —— 曾短暂加进本表，实测立刻回滚。
    # 原因：新引擎 edu_assess 的 4 条菜单（793 模板与评分项 / 794 评估任务 / 795 结果与导出 /
    #   796 打分记录）**parent 就是 edu_portal.menu_edu_eval_root**
    #   （custom_addons/edu_assess/views/assess_views.xml:261-276）。
    #   ⇒ 「综合评估」这个根应用不是旧壳，而是**新引擎的后台容器**；停用它等于把新引擎的后台入口一起关掉。
    # 判据（下次别再踩）：停用任何菜单前先查它的**活子菜单**
    #   `select id,name->>'en_US' from ir_ui_menu where parent_id=<id> and active;`
    #   —— 只看定义处（`views/evaluation.xml:90` 无 action）会误判成空壳。
    # 结论：第 ③ 步（旧路由 303 + 旧菜单停用）**已经全部完成**，此处无需再动。
]


class IrUiMenuLabels(models.Model):
    """ir.ui.menu 上的改名动作（由 views/menu_labels.xml 的 <function> 调用）。"""

    _inherit = 'ir.ui.menu'

    @api.model
    def edu_apply_menu_label_renames(self):
        """规范 noupdate + 写 source 名。幂等；记录缺失一律跳过，绝不让升级失败。"""
        changed, unchanged, skipped, unflagged = [], [], [], []
        imd_model = self.env['ir.model.data']
        for xmlid, new_name, why in RENAMES:
            module, _, name = xmlid.partition('.')
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if not menu:
                skipped.append('%s（菜单不存在）' % xmlid)
                continue
            # ① 规范 noupdate：否则声明式覆盖与 PO 中文都到不了这条记录（见文件头注释）
            imd = imd_model.search(
                [('module', '=', module), ('name', '=', name),
                 ('model', '=', 'ir.ui.menu')], limit=1)
            if imd and imd.noupdate:
                imd.write({'noupdate': False})
                unflagged.append(xmlid)
            # ② 写 source 名（中文由 edu_zh 的 PO 出词条）
            if menu.name == new_name:
                unchanged.append(xmlid)
                continue
            menu.write({'name': new_name})
            changed.append('%s → %r（%s）' % (xmlid, new_name, why))
        _logger.info(
            '[edu_portal] 菜单改名（noupdate 记录走 ORM）：改写 %d 条 %s；解除 noupdate %s；'
            '已是目标值 %d 条；跳过 %s',
            len(changed), changed or '无', unflagged or '无', len(unchanged), skipped or '无')
        return True

    @api.model
    def edu_apply_menu_retirements(self):
        """把已退休的菜单停用。幂等；记录缺失一律跳过，绝不让升级失败。

        **为什么必须走 ORM 而不是声明式 `<record>`**（2026-10-03 实测，见文件头注释 ①）：
        该 xmlid 的 `ir_model_data.noupdate = t` ⇒ 声明式写 `active` 会被**静默跳过**。
        实证：先在 `views/welfare.xml` 给菜单加 `active="False"`、`-u edu_portal` ⇒ DB 里 active 仍为 t；
        再在 `edu_nav/data/menu_consolidation_data.xml`（它的权威声明处）改成 `active=False`、
        `-u edu_nav` ⇒ active **仍是 t**。两处都改不动，因为 noupdate 是**按 xmlid**咬的、与哪个模块的
        数据文件无关 ⇒ 只能走 ORM（与 259 改名那条同因同治）。
        """
        done, skipped, unflagged = [], [], []
        imd_model = self.env['ir.model.data']
        for xmlid, why in RETIRE_MENUS:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if not menu:
                skipped.append('%s（菜单不存在）' % xmlid)
                continue
            module, _, name = xmlid.partition('.')
            imd = imd_model.search(
                [('module', '=', module), ('name', '=', name),
                 ('model', '=', 'ir.ui.menu')], limit=1)
            if imd and imd.noupdate:
                imd.write({'noupdate': False})
                unflagged.append(xmlid)
            if menu.active:
                menu.write({'active': False})
                done.append('%s（%s）' % (xmlid, why))
        _logger.info(
            '[edu_portal] 退休菜单停用：停用 %d 条 %s；解除 noupdate %s；跳过 %s',
            len(done), done or '无', unflagged or '无', skipped or '无')
        return True
