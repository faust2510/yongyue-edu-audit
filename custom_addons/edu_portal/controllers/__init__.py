# -*- coding: utf-8 -*-
from . import main
from . import batch1
from . import batch2
from . import batch3
from . import roles
from . import register
from . import welfare
from . import scheduling
from . import lms
from . import fees
from . import assets
from . import search
from . import evaluation
# 评估系统重建第 1 期（2026-09-18）：/my/evaluation* 旧地址 303 兼容层。
# 必须**紧跟** evaluation 导入（父类先定义）；不删旧实现、不删旧表。
from . import eval_compat
from . import my_password
from . import help_center
from . import calendar

from . import avatar

from . import downloads
from . import ical
from . import favorite
from . import enroll
# 教师自助「不可用时间」（2026-10-14，排课链路 §10.2）：/my/availability。
# 只读依赖 roles（current_faculty）与 resource.calendar.leaves，零新模型。
from . import availability
# 教务端「报课池模式」设置页（2026-10-14，G1 §7.2）：/edu/enroll/pool_mode。
# 只 import enroll 的三档常量与 edu_pool_mode()（不复制语义），故排在 enroll 之后。
from . import enroll_settings
from . import ledger
# 成绩录入（2026-09-29）：教务 / 任课教师的整班矩阵录分（复用基座 op.marksheet.* 链）
from . import grade_entry
# 成绩簿按身份分流（2026-10-03）：教务 / 超管打开 /grade-book = 上面那个成绩录入网格。
# **必须排在 grade_entry 之后**（父类先定义；Odoo 的控制器覆写在装载期解析继承树）。
from . import grading

# 成绩中心批量 IO（2026-10-13）：批量 xlsx 导入 / 导出 + 逐行回报。
# 必须排在 grade_entry 之后（它 import 复用那里的容器 / 权限 / 名册口径）。
from . import grade_entry_io
