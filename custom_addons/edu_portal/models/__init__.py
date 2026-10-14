# -*- coding: utf-8 -*-
from . import notice
from . import leave
# 请假分级审批（S1 数据层）：转交留痕表 edu.leave.transfer（设计稿 §4.2 / §9.2）。
# 导入顺序在本阶段**冻结**为：leave → leave_transfer → course_rep → leave_flow。
from . import leave_transfer
# 课代表（需求：学生干部身份 + 课程内有限权限）。**必须排在 leave 之后**：
# 本文件的 EduLeaveRepExt 以 _inherit 引用 leave.py 定义的 edu.leave
# （规则 7 IMPORT-ORDER：被继承者必须先导入）。
from . import course_rep
from . import grievance
from . import certificate
from . import alumni_job
from . import alert_read
from . import assignment
from . import invite_code
from . import profile_extra
from . import welfare
from . import scheduling
from . import lms
from . import fees
from . import assets
from . import jobs
from . import evaluation
from . import jobs
# ⚠️ 导入顺序是硬约束：registration 定义 edu.grade.history，
# 而 exam_session_ext 里的 EduGradeHistoryExt 以 _inherit 引用它。
# **被继承的模型必须先于继承者导入**，否则注册表加载即抛
#   TypeError: Model 'edu.grade.history' does not exist in registry
# 后果是「站点照常服务、但任何 -u / odoo shell 全部失败」的假绿。
# 新增模型文件时请保持这条顺序依赖（导入顺序 ≠ 排版喜好）。
# 本约束已由 scripts/check_view_xpath.py **规则 7** 自动校验（IMPORT-ORDER /
# CIRCULAR-INHERIT），且该门禁已接在 safe_upgrade **取锁之前** —— 新增/修改
# _inherit 时不必依赖"记得手动跑"，升级前会被自动拦截。
from . import registration
# 成绩录入「手工加人」（名单第 ③ 条来源，2026-10-13）：独立新模型，不 _inherit 任何
# 仓内模型 ⇒ 对本文件上方的 IMPORT-ORDER 硬约束无影响（放哪都安全，放这里只为就近）。
from . import grade_entry_extra
from . import exam_session_ext
# 成绩等级口径修复（2026-09-29）：基座 op.result.line._compute_grade 缺 break ⇒ 除最后一档
# 外等级恒为空。只 _inherit 'op.result.line'（外部模块模型，无仓内导入顺序依赖）。
from . import grade_line_grade
from . import calendar_event
from . import message

from . import partner_edu

from . import downloads
from . import ical
from . import favorite
from . import audit
from . import notify_pref
from . import selfcheck
# 可达性收口（t1）：只 _inherit 'ir.ui.menu'（核心模型，无仓内顺序依赖）
from . import menu_reachability
# 菜单/动作改名：只有 noupdate=t 的 259 走 ORM（声明式 <record> 会被静默跳过，实测），
# 与 menu_reachability 同族写法（只 _inherit 'ir.ui.menu'，无仓内顺序依赖）。
from . import menu_labels
# 基座 openeducat_parent 缺陷覆盖（任务 G）：op.parent.create / op.student.unlink。
# 必须**排在 invite_code 之后**（同模块内后导入的层在 MRO 里更靠前，才能盖住基座那一层），
# 见该文件 docstring「实现细节」。
from . import parent_link_fix
# 班级分配与管理（需求 7）：分班入口 + 「待分配」标记收口 + 归档/真删护栏 + 批次菜单组。
# 排在 invite_code 之后：本文件 import 它的人眼前缀常量 _PENDING_PREFIX（不发明第二套标记）。
from . import class_batch
# 专业编排（学制 + 必修/选修）：edu.course.subject 关系表 + op.course 兼容层
# （subject_ids 非存储 computed + inverse + search）+ op.program.level 补 active。
# 见 docs/plans/major-track-elective-design.md §6。
from . import major_track
# 改密码逐字保存：覆盖 core res.users._change_password 的 new_passwd.strip()
# （base/models/res_users.py:920，与 2026-09-24 注册事故同源）。
# 只 _inherit 'res.users'（core 模型），无仓内导入顺序依赖。
from . import res_users_password
# 学号登录别名（乙，2026-10-12）：登录页「登录名」栏也能填学号。
# 只读解析（学号 → 该生账号的登录名），不建账号、不碰注册流程；
# 无仓内导入顺序依赖（纯 AbstractModel）。
# 先导入 login_throttle：login_alias 在**运行时**通过 env['edu.portal.login.throttle']
# 取它（不是 import），但注册表里必须有这个模型，否则限速读取会 KeyError。
from . import login_throttle
from . import login_alias
# 请假分级审批（S1 数据层 | 设计稿 §3.2/§5.4/§9.2）：edu.leave 的字段层
# （分级审批/转交/销假/证明/提前期/配额/补假）+ op.batch.homeroom_teacher_id。
# ⚠ **必须排在最后**：同模块内「后导入的层在 MRO 里更靠前」，leave_flow 要盖住
# leave.py / course_rep.py 的既有层，才能让 route_of() 与状态机成为唯一口径。
# 该顺序由 scripts/check_view_xpath.py **规则 7**（IMPORT-ORDER）自动校验，
# 且门禁接在 safe_upgrade 取锁之前 —— 不必依赖「记得手动跑」。
from . import leave_flow
