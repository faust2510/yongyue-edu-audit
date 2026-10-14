# -*- coding: utf-8 -*-
"""班级分配与管理（需求 7）—— 把学生真正放进班级，补上教学链上断掉的那一环。

设计：docs/plans/class-batch-management-design.md（裁定 = **复用**，见 §0/§8.1）
    · 班 + 学生归属 + 回收站 = 基座 op.batch（含内建 active）+ op.student.course.batch_id
    · ⇒ **零新模块 / 零新模型 / 零新表 / 零新字段**
    · §9.2 流程 A（分班）/ §9.6 真删护栏 / §10 归档权限 / §11 级联三档

本文件的落点（自研代码面的其余三处：views/class_batch_views.xml、
data/class_batch_data.xml、controllers/contacts.py）：

  ① OpStudent.action_edu_assign_batch()        —— 教务在学生页面分班的入口（G1）
  ② OpStudentCourse.create()/write()           —— 写 batch_id 时收口「待分配」标记
  ③ OpBatch.write()                            —— 「停用 / 恢复」归教务（设计 §10 档②）
  ④ OpBatch.unlink()                           —— 真删护栏（照 models/fees.py:128-138 先例）
  ⑤ ir.ui.menu.edu_apply_class_batch_menu_groups() —— 「批次」菜单对教师可见（G2）

⚠ 与设计稿 §8.4 收口触发条件 T1 的关系（如实登记）：T1 说「出现第二个 op.batch 的
  _inherit ⇒ 停手回到第 0 步」。本文件**确实**给 op.batch 加了一处 _inherit ——
  但它正是 §9.1「自研」栏逐条裁定的那一处（unlink 护栏 + 归档护栏），
  **不是第二套实现**：班级实体、回收站（active）、学生归属三者仍 100% 复用基座，
  本文件不新增字段、不新增表、不写 op_batch 之外的任何新事实源。
  若将来出现**另一处** op.batch 覆写（第二个 _inherit 文件），才是 T1 真正要拦的情形。
"""
import logging

from odoo import api, models
from odoo.exceptions import UserError

from .invite_code import _PENDING_PREFIX

_logger = logging.getLogger(__name__)

# 四层权限口径（不建自定义组，复用既有组；见 docs/code-map.md:245）：
#   教务处 group_op_back_office_admin（id 40）/ 系统管理员 base.group_system
_REGISTRAR_GROUPS = (
    'openeducat_core.group_op_back_office_admin',
    'base.group_system',
)

# 真删护栏的三档（逐条实测口径见设计 §7-Q5 / §11.1）：
#   hard  = RESTRICT：真删会被数据库挡住（现状是英文 ForeignKeyViolation）
#   soft  = SET NULL：真删**静默成功**，记录被清空班级（学生「没有班了」且无人告知）
#   cascade = CASCADE：子记录跟着被删
# 每项 = (模型, 字段, 计数文案)。模型在本部署可能不存在（如未装 openeducat_fees）
# ⇒ 计数时逐个探活，缺模型只记日志、不报错（升级/删除都不因此失败）。
_UNLINK_HARD = [
    ('op.session', 'batch_id', '节课节'),
    ('op.assignment', 'batch_id', '份作业'),
    ('op.attendance.register', 'batch_id', '本考勤登记簿'),
    ('op.exam.session', 'batch_id', '个考试安排'),
]
_UNLINK_SOFT = [
    ('op.student.course', 'batch_id', '名学生（真删会让他们静默失去班级）'),
    ('op.subject.registration', 'batch_id', '份选课/换课注册单'),
    ('op.exam', 'batch_id', '场考试'),
    ('op.attendance.sheet', 'batch_id', '张点名表'),
    ('op.student.fees.details', 'batch_id', '条费用明细'),
    ('op.classroom', 'batch_id', '间教室'),
    ('edu.event', 'batch_id', '个校历活动'),
    ('edu.schedule.holiday', 'batch_id', '个停课日'),
    ('op.admission', 'batch_id', '份招生记录'),
]
_UNLINK_CASCADE = [
    ('edu.attend.self.token', 'batch_id', '个自助签到码'),
]


def _edu_is_registrar(env):
    """教务口径：教务处组 / 系统管理员；超管与系统进程（env.su）一律放行。

    与 controllers/roles.py:154 privileged_staff() 同源（教务 + 系统组），
    但这里是**模型层**（脚本、导入、XML-RPC 都过这里），故额外认 env.su。
    """
    if env.su:
        return True
    user = env.user
    return any(user.has_group(g) for g in _REGISTRAR_GROUPS)


class OpBatch(models.Model):
    """班级（基座 op.batch）的护栏层：归档归教务 + 真删先数引用。"""

    _inherit = 'op.batch'

    # ------------------------------------------------------------------
    # ③ 「停用 / 恢复」归教务（设计 §10 的「陷阱」）
    #
    # 陷阱原文：**「归档」没有独立 ACL，用的就是 write 权限，而教师本来就有
    # write**（基座 ir.model.access.csv:8 = 1,1,1,0）。⇒ 只把菜单开给教师，
    # 教师就能经表单/XML-RPC 改 active。纯 ACL 拦不住，必须另加一层。
    # 本实现选设计 §10 的三选一里的 **② write() 覆写**（精准按字段拦）：
    #   · 只拦「active 的值真的发生变化」的写，幂等写（同值）不算越权；
    #   · 不限制教师改班名/日期 —— 需求 2 明确要教师能编辑班级；
    #   · 教务与超管放行（校长拍板：删除与归档都归教务）。
    # ------------------------------------------------------------------
    def _edu_check_active_permission(self, new_active):
        wanted = bool(new_active)
        if all(bool(rec.active) == wanted for rec in self):
            return                      # 值没变：不是归档/恢复动作
        if _edu_is_registrar(self.env):
            return
        raise UserError(
            '「停用 / 恢复」班级是教务处的业务动作，教师不能办理。\n\n'
            '您可以照常新建与编辑班级（班名、起止日期、所属课程）；'
            '若某个班需要停用或恢复，请联系教务处。')

    def write(self, vals):
        if 'active' in vals:
            self._edu_check_active_permission(vals['active'])
        return super().write(vals)

    def action_edu_stop(self):
        """「停用」按钮（校长拍板 P6-(a) 的用词：停用 / 恢复，不用「归档 / 取消归档」）。

        与 Odoo 自带的「存档」是同一件事（active=False，零外键副作用、可一键恢复），
        只是**按钮名按校长的用词**，并写一条审计。列表与表单上各有一个入口；
        权限与 write() 护栏同源（教师点了会拿到人话拒绝，不静默失败）。
        """
        self._edu_check_active_permission(False)
        for rec in self:
            if rec.active:
                rec.write({'active': False})
                self.env['edu.audit.log'].sudo()._log(
                    '停用班级', 'op.batch', rec.id, rec.name or '',
                    '班级已停用（学生归属、课表、成绩全部保留，可随时恢复）')
        return True

    def action_edu_restore(self):
        """「恢复」按钮（回收站里的一键恢复）。"""
        self._edu_check_active_permission(True)
        for rec in self:
            if not rec.active:
                rec.write({'active': True})
                self.env['edu.audit.log'].sudo()._log(
                    '恢复班级', 'op.batch', rec.id, rec.name or '',
                    '班级已从回收站恢复（重新出现在分班/选课下拉里）')
        return True

    # ------------------------------------------------------------------
    # ④ 真删护栏（设计 §9.6 裁定 (a)：有引用则拒绝并引导「停用」，零引用放行）
    #
    # 本仓先例：models/fees.py:128-138（被账单引用的分类禁删 + 文案引导「停用」）、
    #           models/downloads.py:44-55（非空文件夹禁删）。
    # 为什么不改基座 ACL（设计 §9.6 方案 b）：基座是官方源码快照，只读不改；
    # 且改 ACL 会让教务处也删不掉，与校长拍板「删除归教务」直接冲突。
    # ------------------------------------------------------------------
    def _edu_unlink_ref_counts(self):
        """逐档数引用：返回 (hard, soft, cascade)，每项 = [(文案, 数量)]（数量>0）。"""
        env = self.env
        buckets = ([], [], [])
        for idx, spec in enumerate((_UNLINK_HARD, _UNLINK_SOFT, _UNLINK_CASCADE)):
            for model, fname, label in spec:
                if model not in env:
                    _logger.debug('[edu_portal] 跳过的引用模型（本部署没有）：%s',
                                  model)
                    continue
                try:
                    n = env[model].sudo().with_context(
                        active_test=False).search_count(
                        [(fname, '=', self.id)])
                except Exception:                     # 字段缺失等：只告警
                    _logger.warning('[edu_portal] 引用计数失败 %s.%s',
                                    model, fname, exc_info=True)
                    continue
                if n:
                    buckets[idx].append(('%s %s' % (n, label), n))
        return buckets

    @staticmethod
    def _edu_join_counts(items):
        return '、'.join(text for text, _n in items)

    def unlink(self):
        """有引用（课节/作业/考勤簿/考试安排/学生/注册单…）一律拒绝并引导「停用」。

        零引用放行 —— 给「建错的空班」留真删出口（设计 §9.6 裁定）。
        """
        for rec in self:
            hard, soft, cascade = rec._edu_unlink_ref_counts()
            if cascade and (hard or soft):
                _logger.info('[edu_portal] 班级「%s」删除时 %s 会一并失效',
                             rec.name or '', rec._edu_join_counts(cascade))
            if hard or soft:
                parts = []
                if hard:
                    parts.append('还有 %s。' % rec._edu_join_counts(hard))
                if soft:
                    parts.append(
                        '还有 %s；真删会让这些记录**静默失去班级归属**（不再有任何提示）。'
                        % rec._edu_join_counts(soft))
                if cascade:
                    parts.append('另有 %s 会一并失效。'
                                 % rec._edu_join_counts(cascade))
                raise UserError(
                    '班级「%s」不能删除：%s\n\n'
                    '请改用「停用」：课表、成绩与学生归属全部保留，'
                    '该班只是不再出现在新的分班/选课下拉里，随时可以「恢复」。'
                    % (rec.name or '', ''.join(parts)))
        # ⚠ 审计用的名字必须在**删除之前**取：super().unlink() 之后记录集已不存在，
        # 再读 rec.name 会抛 MissingError —— 真机冒烟当场抓出过这一条
        # （表现为「删成功了但事务回滚、夹具清不掉」）。
        names = ', '.join('%s(%s)' % (rec.name or '', rec.id) for rec in self)
        res = super().unlink()
        self.env['edu.audit.log'].sudo()._log(
            '删班', 'op.batch', 0, names,
            '零引用的班级已真删（课节/学生/注册单等均无引用）')
        return res


class OpStudent(models.Model):
    """学生档案侧：分班入口 + 「待分配」标记收口。"""

    _inherit = 'op.student'

    # ------------------------------------------------------------------
    # ① 教务在学生页面分班（需求 7 G1 —— 这条链此前**没有任何入口**）
    #
    # 载体现成：基座动作 392「学生课程详情」（op.student.course）的菜单挂在
    # 已停用的 278 子树下（设计 §7-Q2），所以教务**打不开**它。
    # 本入口不新建动作、不新建模型：在学生表单上加一个按钮，就地打开
    # 「这名学生的班/课程档案」对话框 —— 新建或修改 op.student.course.batch_id
    # 就是分班本身（学生归属的事实源只有这一处，设计 §8.1 不新增事实源）。
    # 写 batch_id 之后的收口（去【待分配】前缀 + 清 edu_pending_setup）在
    # OpStudentCourse.create()/write() 里，**对所有写路径生效**（后台/导入/脚本）。
    # ------------------------------------------------------------------
    def action_edu_assign_batch(self):
        """返回「分班」对话框动作：无班级档案 → 直接开新建表单；已有 → 开该生档案列表。

        为什么两种形态（真机实测 2026-09-18，Playwright）：
          · 只给 list,form 时，对话框里的「新建」在 Odoo 19 里点不出表单
            （点了无反应、无 JS 报错）⇒ 对「18 个还没有任何档案的学生」这条路走不通；
          · 直接开 form（res_id=False + default_student_id）是 Odoo 的经典
            「新建并编辑」对话框，稳定可点。
        两种形态都不新建模型、不新建字段：写的仍然是 op.student.course 本身。
        """
        self.ensure_one()
        if not _edu_is_registrar(self.env):
            raise UserError('分班（学生班级归属）由教务处办理。')
        Sc = self.env['op.student.course'].sudo()
        has_archive = bool(Sc.search_count([('student_id', '=', self.id)]))
        action = {
            'type': 'ir.actions.act_window',
            'name': '分班：%s' % (self.name or ''),
            'res_model': 'op.student.course',
            'target': 'new',
            'context': {
                'default_student_id': self.id,
                'default_state': 'running',
                'search_default_student_id': self.id,
            },
        }
        # 分班专用表单（views/class_batch_views.xml 的 view_edu_assign_batch_form）：
        # 基座那个表单被 openeducat_fees 继承了**必填**的课程费用字段，
        # 教务在这里保存会被「Missing required fields」挡下（实测）。
        view = self.env.ref('edu_portal.view_edu_assign_batch_form',
                            raise_if_not_found=False)
        if has_archive:
            action.update({'view_mode': 'list,form',
                           'domain': [('student_id', '=', self.id)]})
            if view:
                # 列表用默认列表视图（基座 view_op_student_course_tree），
                # 表单用分班专用表单（不带费用必填）
                action['views'] = [(False, 'list'), (view.id, 'form')]
        else:
            action.update({'view_mode': 'form', 'res_id': False})
            if view:
                action['views'] = [(view.id, 'form')]
        return action

    def _edu_clear_pending_marker(self):
        """分班后收口注册流程打的「待分配」标记（人眼前缀 + 机器字段）。

        标记由 models/invite_code.py:337-390 create_pending_archive() 写下：
            · 人眼标记 = 账号 partner 名字前缀「【待分配】」（:389，写的是 partner.name，
              而 op.student 是 _inherits res.partner ⇒ student.name 即 partner.name）；
            · 机器标记 = op.student.edu_pending_setup（:473）。
        本方法**复用同一常量** _PENDING_PREFIX（import 自 invite_code，不发明第二套
        标记），对「前缀还在、但已有班级」的档案收口 —— 否则分完班名字还挂着「待分配」，
        班主任与点名表会一直看到这个错标记。
        """
        for rec in self:
            partner = rec.partner_id
            name = (partner.name or '')
            vals = {}
            if rec.edu_pending_setup:
                vals['edu_pending_setup'] = False
            if name.startswith(_PENDING_PREFIX):
                # op.student _inherits res.partner → name 委托写 partner.name
                stripped = name[len(_PENDING_PREFIX):].strip()
                if stripped:
                    vals['name'] = stripped
                else:
                    _logger.warning(
                        '[edu_portal] 学生 %s 的名字只有「待分配」前缀，未改写'
                        '（避免留空名）；请在档案里补真实姓名', rec.id)
            if vals:
                rec.sudo().write(vals)


class OpStudentCourse(models.Model):
    """学生班级归属（op.student.course）：写 batch_id = 分班，写后收口「待分配」标记。"""

    _inherit = 'op.student.course'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._edu_after_batch_write()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'batch_id' in vals:
            self._edu_after_batch_write()
        return res

    def _edu_after_batch_write(self):
        """分班落库后的收口：把学生的「待分配」标记清掉（幂等）。

        放在模型层 ⇒ 后台对话框、门户审批（registration.action_enroll_approve）、
        导入、脚本四条路径**同一处生效**（设计 §8.4 T3「写库语义收敛到一处」）。
        """
        for rec in self:
            if rec.batch_id and rec.student_id:
                rec.student_id._edu_clear_pending_marker()


class IrUiMenuClassBatch(models.Model):
    """「批次（班级）」菜单可见性：让教师真正能用上基座已给他的建/改权限（需求 7 G2）。

    事实（设计 §7-Q1 ④ 真机实测）：基座 ACL 早就允许教师 create/write 班级
    （ir.model.access.csv:8 = 1,1,1,0），挡住教师的是**菜单**——菜单
    openeducat_core.menu_op_batch_sub 的 groups 只挂教务处组。
    ⇒ 这不是「缺功能」，是「缺入口」，本方法只补这一行组关系。

    为什么用 <function> 而不是声明式 record（同 data/menu_reachability.xml 的理由）：
    record 键是**别的模块**的 xmlid，写法更硬；这里按 xmlid 查、查不到就跳过并记日志，
    升级永不因此失败；改写幂等（值相同就不写），且只写 ir.ui.menu（配置类记录），
    不碰任何业务表（设计 §5.2 硬约束）。
    """

    _inherit = 'ir.ui.menu'

    @api.model
    def edu_apply_class_batch_menu_groups(self):
        wanted_xmlids = [
            'openeducat_core.group_op_faculty',
            'openeducat_core.group_op_back_office_admin',
            'base.group_system',
        ]
        menu = self.env.ref('openeducat_core.menu_op_batch_sub',
                            raise_if_not_found=False)
        if not menu:
            _logger.info('[edu_portal] 未找到批次菜单（openeducat_core 未装？），跳过')
            return True
        gids = sorted({g.id for g in (
            self.env.ref(x, raise_if_not_found=False) for x in wanted_xmlids)
            if g})
        if not gids:
            _logger.warning('[edu_portal] 批次菜单的目标组一个都取不到，跳过')
            return True
        if sorted(menu.group_ids.ids) == gids:
            _logger.info('[edu_portal] 批次菜单组已是目标值（教师+教务+超管），无改动')
            return True
        before = sorted(menu.group_ids.ids)
        menu.write({'group_ids': [(6, 0, gids)]})
        _logger.info(
            '[edu_portal] 批次菜单对教师开放：组 %s → %s（需求 7 G2；'
            'ACL 已允许教师 create/write，缺的只是入口）', before, gids)
        return True
