# -*- coding: utf-8 -*-
"""视图/路由静态自检（离线、不连库、2 秒级）：升级前把「装载期才炸」挡在门外。

用法：
    python3 check_view_xpath.py [扫描根，默认 custom_addons] [--selftest]

覆盖 6 条（每条都对应本仓真实踩过的坑）：
  1. XML well-formed（含内联 <script> 里未转义的裸 <）
  2. <xpath expr=...> 能否在父 arch 命中：翻译 hasclass 扩展函数；0 命中且父
     arch 只有 t-attf-X / t-att-X 时给 HINT（写 @href 匹配不到 t-attf-href）
  3. inherit_id 目标是否存在（本仓模块内缺失即报错；仓外父模板计入「未覆盖」）
  4. ir.ui.view arch 载荷：主视图必须单根且根不能是 <data>；继承视图的多指令
     与 <data> 分组均为合法写法（不误报）
  5. @http.route 归属歧义：同一路由被两个互不为父子关系的控制器类定义
     （Odoo 的 leaf 覆盖机制只对子类生效，否则归属随加载顺序漂移）
  7. Python 模型导入顺序（models/__init__.py）：A 文件 _inherit 的模型若由同
     模块 B 文件定义，则 B 必须先于 A 导入
     7a IMPORT-ORDER：违序但重排可解 → 报文件:行号 + 两个导入序号 + 改法
     7b CIRCULAR-INHERIT：互相 _inherit（重排无解）→ 列环上文件:行号与模型
  6. QWEB-ADJ：t-if/t-else 相邻性（渲染期才炸、-u 不报的那类）
     6a 插入到带 t-else/t-elif 的元素之前（position=before）
     6b 插入到 t-if 之后且其后紧跟 t-else/t-elif（position=after）
     6c 主视图 arch 内 t-else/t-elif 的前一个兄弟元素没有 t-if/t-elif

覆盖边界（重要，输出里会显式打印）：
  - 跨模块父模板（openeducat_*/website 等）在本仓之外，规则 2/6a/6b 对其**无法求值**，
    一律计入「未覆盖（跳过）」——跨模块继承恰恰是外键漂移风险最高的一类，
    因此本脚本 NOT 等于「继承 xpath 全绿」的证明。
  - 继承片段内的直接相邻性（6c 的继承版）不判定：片段经继承合并后兄弟关系可能变化，
    这类只能在渲染期验证。
  - **调用契约（t50 追加，来自一次真实 P0）**：本检查器应在**获取升级锁之前**
    调用（它只读文件，不需要锁）；它解析锁路径**只为判断他人是否在升级**，
    **不得把自己的调用者当作冲突**。曾发生：safe_upgrade 先取锁再调用本工具 →
    本工具把调用者自己的锁当成「他人持锁」→ SKIP-ENV → 拒绝升级（假红，
    与「假绿」互为镜像，已由调用方把静态检查移到取锁之前修复）。
  - 运行环境语义（t50）：升级锁（默认 ${TMPDIR:-/tmp}/edu19_upgrade.lock，
    可用 EDU_UPGRADE_LOCK 覆盖）被持有时打印 SKIP-ENV 并 **exit 2** ——
    「环境未就绪」不等于「检查通过」（对齐 t39 口径）；离线强跑用 --ignore-lock。
  - 瞬时快照防护（t36-F2）与它的上限（t50）：扫描前做 1 秒指纹对拍，正在被写盘的
    文件本次跳过并点名；但**连续 N 次（默认 3，EDU_VIEW_XPATH_TRANSIENT_LIMIT 可调）
    都被跳过的文件升级为失败（TRANSIENT-LIMIT）** —— 反复跳过不等于长期免检；
    计数状态在 ${TMPDIR:-/tmp}/edu19_view_xpath_transient.json（EDU_VIEW_XPATH_STATE 可覆盖），
    某文件本次稳定通过即清零（即使本次一个瞬时文件都没有，也会清零陈旧计数）。
    汇总里始终打印 TRANSIENT_SKIPPED 行。
    **已知盲区（不沉默）**：指纹对拍同为 1 秒窗口，若写入方以极快频率在两个内容
    间来回写，两次读取可能恰好同值 → 该次被当作「稳定」，瞬时态漏报；这类文件
    的真实错误会在下一次稳定读取时被正常报出（不会被永久吞掉）。
  - **退出码契约（t53 定稿，与 check_odoo_trace 对齐）**：0=OK｜1=FAIL｜2=ENV（升级锁
    被持有）｜3=INCOMPLETE（无失败但存在「本该验却没验」的面）。**--strict 把
    INCOMPLETE 归为 1**，供 CI 只判退出码、不 grep 正文；RESULT=OK|INCOMPLETE|FAIL
    为对应的机器可读结论词（在汇总末段输出）。
  - **运行时刻（t72）**：自证行末带「运行 <ISO 8601 带时区偏移>」，与
    check_odoo_trace / check_english 同形态，供**窗口公告即时核对**（这次读数是否
    落在某人正在动的活数据窗口内）。**作用范围 = 协作用途，非防篡改证据**：指纹
    证脚本版本、断言条数证覆盖规模、时刻只由本进程时钟产生；三者都能被改代码
    伪造，故只用于协作核对，不能当审计证据。
  - **跳过面分型判据（t53）**：问一句「如果环境恢复，这个面会不会被验、会不会自动
    变红？」——会 → **环境型**（本次跳过但下次会补上，绝不许当 PASS 看待：瞬时跳过
    计入未覆盖、连续 N 次升级 FAIL、升级锁则 exit 2）；不会 → **边界型**（按设计
    不可验，可 PASS 但必须显式计数 + 声明「这不是全绿」）。
  - **mode=primary 的 COW 副本（t57）**：ir.ui.view 的 mode 是真字段（ir_ui_view.py:177，
    默认 primary）；建库时「有 inherit_id → 默认 extension」（:567），**显式 mode=primary
    即 COW 副本**；继承遍历遇 primary 即停（:448/455），故其 arch 必须是完整 arch →
    直接按内容型判（单根 + 禁 data），**不看顶层有无 xpath**（能抓「带 xpath 但仍是
    primary」的混合形态）。边界：**当前仓库没有显式 mode=primary 的视图**，本档属
    预防性（防未来 COW 引入），selftest 用自造反例（多根带 xpath / 单根）覆盖。
  - **边界常量（t53）**：EXPECTED_SKIPPED_INHERIT / EXPECTED_EXTERNAL_MODELS 把当前
    已接受的边界写死在代码里；实测值与之不符 → 打印 BOUNDARY-DRIFT 并计入
    INCOMPLETE，迫使「边界变了」进入 diff 被 review（防静默漂移）。
    **t10 起**：无论漂不漂移都会打印「规则 7 外部模块清单」（= (模块, 外部模型) 组合的
    完整列表）；一旦与常量不符，还会补逐条 `文件:行号`。理由：过去只报「19 ≠ 常量 18」，
    复核者得自己重实现一遍口径才知道多出来的是谁（t10 实测花了一轮）——清单常驻后
    漂移可直接肉眼对账。
    断言条数见 SELFTEST_CASES（selftest 自校验，条数漂移直接 FAIL）；
    输出与 selftest 汇总都带 REVISION。
  - 规则 7 只判「同模块 models/ 目录内、且被 __init__.py 按顺序导入」的文件：
    外部模块（基座/OCA/官方）定义的模型一律计入「跳过」并打印计数；未被
    __init__.py 导入的文件无法排序、不参与判定；动态 import/运行期注册不在覆盖范围。
退出码：0 = 干净；1 = 存在失败项。
"""
import ast
import datetime
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

from lxml import etree


REVISION = 'r16'                 # 输出自证用：改动行为时同步 +1
# r16（2026-09-29，门户「成绩录入」）：EXPECTED_EXTERNAL_MODELS 31 → 32。
#   来由（有意为之，不是漂移）：新增 custom_addons/edu_portal/models/grade_line_grade.py，
#   它 _inherit 'op.result.line'（基座 openeducat_exam 定义、不在本仓）⇒ 规则 7 外部模块
#   组合 +1（edu_portal × op.result.line 此前不存在）。
#   为什么必须覆盖它：基座 op.result.line._compute_grade 缺 break ⇒ 除最后一档外等级恒空
#   （实测：74 分 → 空），且它拿原始分比百分比阈值。判据（可复算，同一工作区改前/改后各跑一次）：
#     改前（该文件暂时移开）：RESULT=OK，31 个外部模型、失败项 0；
#     改后：RESULT=INCOMPLETE，32 个、**失败项仍为 0**，唯一新增清单项 =
#       EXT edu_portal / op.result.line（custom_addons/edu_portal/models/grade_line_grade.py）
#     ⇒ 逐条 diff 只有新增、无消失项 = 合法边界扩张，故把常量跟到位。
# r15（2026-09-28，门户 act_url 入口不再绕后台——用户实测缺陷，见
#   custom_addons/edu_brand/models/menu_href.py）：
#   EXPECTED_SKIPPED_INHERIT 23 → 24、EXPECTED_EXTERNAL_MODELS 30 → 31，各 +1。
#   来由（两处新面，都是有意为之，不是漂移）：
#     ① edu_brand/views/odoo_debrand.xml 新增 yy_backend_switcher_act_url
#        （inherit_id="website.layout"，父模板在仓外）⇒ 跨模块继承跳过 +1（website x3 → x4）；
#     ② edu_brand/models/menu_href.py 新增 ir.ui.menu 扩展（edu_brand × ir.ui.menu
#        这个组合此前不存在）⇒ 规则 7 外部模块模型 +1。
#   依据（可复算）：同一份工作区的改前/改后两次运行 ——
#     改前（我的改动已还原）：RESULT=OK，23 处跨模块继承 [.. website x3]、30 个外部模型、失败项 0；
#     改后：RESULT=INCOMPLETE，24 处 [.. website x4]、31 个外部模型、**失败项仍为 0**，
#       唯一新增的清单项 = EXT edu_brand / ir.ui.menu（custom_addons/edu_brand/models/menu_href.py:38）；
#     逐条 diff **只有新增、无消失项** ⇒ 合法边界扩张，故把两个常量跟到位。
# r14（2026-09-24，未使用模块整族卸载）：EXPECTED_SKIPPED_INHERIT 25 → 23。
#   来由：电商/论坛/课程族 18 个模块被卸载（website_sale / website_slides / website_forum /
#   payment* / sale / website_event / website_blog …，见 docs/deploy-malaysia.md「前端瘦身第二刀」），
#   这些模块与本站自研模板之间的 2 处跨模块继承随之消失 ⇒ 跳过数合法收窄（25→23）。
#   判据：失败项 0、本文件输出逐条 diff 无**新增**未覆盖项，仅总数下降；
#   若日后数量回升，需按新边界重新记账。
# r13（2026-09-18，评估系统重建第 1 期）：EXPECTED_EXTERNAL_MODELS 23 → 24
#   （新模块 edu_assess 的 ResUsers(_inherit = 'res.users')
#    custom_addons/edu_assess/models/assess.py:490 —— ⚠ **2026-09-18 取证时刻的行号，不是引用**
#    （当时是 507 行版本，该处 = class ResUsers 的 docstring；第 2 期后该文件 1517 行、
#    ResUsers 在 1499 行）⇒ 定位请用符号名 `ResUsers`；教师侧行级规则需要一条
#    res.users 上的「任教班级」收敛依据；res.users 属 Odoo 核心、不在本仓定义 ⇒ 计入）。
#    依据（可复算）：本文件输出「规则 7 外部模块清单」由 23 → 24 条，逐条 diff 只多
#    edu_assess / res.users（文件:行号 = models/assess.py:490，**同为取证时刻读数**；
#    符号 = `ResUsers`），无消失项 ⇒ 合法边界扩张。
# r12（t19 边界）：EXPECTED_EXTERNAL_MODELS 22 → 23（op.parent 的 edu_pending_setup 扩展）。
# r11（t16 边界）：EXPECTED_EXTERNAL_MODELS 20 → 22（op.student / op.faculty 的
#   edu_pending_setup 扩展各 +1；失败项 0、无消失项 ⇒ 合法边界扩张，逐次来由见该常量上方）。
# r10（t11）：selftest 的 lock_exit2 判据从「--ignore-lock 子进程 exit 0」改为
#   `_lock_bypass_ok()`（rc != 2 且无 SKIP-ENV 且已打印 RESULT=）—— 原判据把「锁语义」
#   与「整仓此刻是否干净」耦合，队友编辑期间必假红（瞬时跳过 3 / 半成品 1）。
# r9（t10）：① 规则 7 外部模块清单改为**每次都打印**（漂移时附逐条 文件:行号）；
#             ② EXPECTED_EXTERNAL_MODELS 18 → 19（新模块 edu_nav 继承 ir.ui.menu，
#                证据链见该常量上方的「逐次来由」）。
# t72：本次运行时刻（本地时区，ISO 8601 带偏移）—— **模块级算一次，单一来源**，
# 所有打印处读同一个值。指纹仍只由**文件内容**决定，与本值无关（故同一份代码
# 两次运行：时刻不同、指纹相同）。
RUN_STAMP = datetime.datetime.now().astimezone().replace(
    microsecond=0).isoformat()
# r18（2026-10-06，登录页品牌化）：EXPECTED_SKIPPED_INHERIT 24 → 25（edu_brand 新增
#   yy_login_brand_head，继承 web.login —— 父模板在仓外，属**有意引入**的跨模块边界，
#   故更新常量使其进入 diff）。
EXPECTED_SKIPPED_INHERIT = 25   # 边界常量：跨模块继承（父模板在仓外）跳过数（r15：23→24，见上）
# 边界常量：规则 7 的「外部模块模型」**口径数**。
#
# 【它代表什么口径】逐模块统计：该模块 models/ 下（按 __init__.py 导入序）所有
#   `_inherit`/`_inherits` 的目标里，**不由本模块任何 `_name` 定义**的模型
#   （= Odoo 核心模型 + 其它模块的模型），再把各模块的这类模型数**相加**。
#   ⇒ 单位是「(模块, 外部模型) 组合」，不是「模型」：
#     `res.partner` 被 edu_portal 与 edu_life 各继承一次 = **2 条**。
#   ⇒ 本仓自己定义的模型（如 edu.deadline）**不计**；被继承的基座 op.* 计（它们不在本模块
#     的 _name 里），所以「基座模型」也进统计。
#
# 【何时该更新】任何新增/删除/改变一次「对外部模型的 _inherit」，或新增/移除一个带这类继承的
#   模块 —— 都要同步本常量，并在下面「逐次来由」追加一行（写清：谁 / 何物 / 何时 / 依据）。
#
# 【为什么必须同步，且不许无证据 +1】
#   · 不同步 ⇒ 报 BOUNDARY-DRIFT 并计入 INCOMPLETE（exit 3），长期停在 exit 3 会把真红淹没；
#   · 无证据直接 +1 ⇒ 「边界变了」被静默吞掉，等于把门禁改成橡皮图章。
#   正确顺序：先证明**多/少的是谁**——跑 `python3 scripts/check_view_xpath.py`，用输出里的
#   「规则 7 外部模块清单」逐条对账（t10 起该清单会直接打印，漂移时还给出 文件:行号），
#   确认是合法边界扩张（新模块 / 新继承）还是判据缺陷；前者才改本数，后者改判据。
#
# ⚠ **行号口径（2026-09-28 立）**：本段里的「文件:行号」一律是**该条写下的那一刻**的取证
#   读数，属**历史证据**，**不得据此定位代码**。实测：本段 r13 的 models/assess.py:490 在
#   当时**是对的**（第 1 期版本里 class ResUsers 正好在 489-491），而 edu_assess/models/assess.py
#   第 2 期后从 507 行长到 1517 行 ⇒ 同一批行号已指向别的符号（res.users 扩展挪到了 1499 行）。
#   要定位请用**符号名**：`python3 scripts/assess_symbol_index.py --grep <符号>`。
#   规则与来由见 `docs/plans/eval-unified-design.md` §8.0.3「引用纪律」。
#
# 【逐次来由】（每次改动都写一行，别只留最终数字）
#   17 → 18（2026-09-12，t88）：edu_portal 新增 `ResConfigSettings(_inherit =
#       'res.config.settings')`（edu_portal/models/registration.py）—— 核心模型被继承后
#       进入外部统计；同批 `edu.deadline`(AbstractModel) 由本模块 `_name` 定义，不计入。
#   18 → 19（2026-09-17，t10 采集 15:50）：新模块 **edu_nav** 的
#       `IrUiMenuConsolidation(_inherit = 'ir.ui.menu')`
#       （custom_addons/edu_nav/models/menu_consolidation.py:98）—— 菜单收口工作流新增的
#       声明式落地模块，`ir.ui.menu` 属 Odoo 核心、不在本仓定义 ⇒ 计入。
#       依据（可复算）：从设定 18 的那个 commit `85b8a68`（2026-09-13 00:15）取
#       `custom_addons` 快照复跑同一口径 = 18 条且**该快照里没有 edu_nav 目录**；
#       与当前逐条 diff 只多 `edu_nav / ir.ui.menu` 一条、无消失项。
#       ⇒ 判为**合法边界扩张**（新模块），不是判据缺陷。
#   19 → 20（2026-09-17，t1 perm-eng 采集 16:23）：edu_portal 新增
#       `IrUiMenuReachability(_inherit = 'ir.ui.menu')`
#       （custom_addons/edu_portal/models/menu_reachability.py:66）—— 后台可达性收口
#       （把「教务看得见点不开」的原生菜单收回到功能组）需要一条 ir.ui.menu 上的
#       幂等 <function> 入口；ir.ui.menu 属 Odoo 核心、不在本仓定义 ⇒ 计入。
#       依据（可复算）：`python3 scripts/check_view_xpath.py` 的「规则 7 外部模块清单」
#       由 19 → 20 条，逐条 diff 只多 `edu_portal / ir.ui.menu`（文件:行号
#       = models/menu_reachability.py:66），无消失项；该模块新增文件前同一口径为 19。
#       ⇒ 判为**合法边界扩张**（新增一处对外部模型的 _inherit），不是判据缺陷。
#       ⇒ 20 → 22（t16）：本次给 op.student / op.faculty 各加一处 _inherit（edu_pending_setup
#       「待分配」标记），按同口径计数 +2；失败项 0、无消失项 ⇒ 同类合法边界扩张。
#       复核方式同上：git archive 取定 20 的那个 commit 复跑本口径应得 20，逐条 diff 只多这两条。
#       ⇒ 22 → 23（t19）：本次给 op.parent 加一处 _inherit（家长层「待分配」标记），同口径 +1；
#       失败项 0、无消失项 ⇒ 同类合法边界扩张。承重方式同上（git archive 取定 22 的 commit 复跑应得 22）。
#   23 → 24（2026-09-18，评估系统重建第 1 期）：新模块 **edu_assess** 的
#       ResUsers(_inherit = 'res.users')
#       （custom_addons/edu_assess/models/assess.py:490 —— ⚠ **2026-09-18 取证时刻的行号**，
#       不是引用；该符号今用 `python3 scripts/assess_symbol_index.py --grep ResUsers` 定位）
#       —— 教师侧行级规则
#       （ir.rule: batch_id in user.edu_taught_batch_ids）需要一条 res.users 上的
#       收敛依据；res.users 属 Odoo 核心、不在本仓定义 ⇒ 计入。
#       依据（可复算）：python3 scripts/check_view_xpath.py 的「规则 7 外部模块清单」
#       由 23 → 24 条，逐条 diff 只多 edu_assess / res.users（文件:行号
#       = models/assess.py:490，**取证时刻读数**；符号 = `ResUsers`），无消失项
#       ⇒ 判为**合法边界扩张**（新模块 + 新继承），
#       不是判据缺陷。
#       2026-09-18（需求 7 班级分配）：24 → 26，逐条 diff 只多 op.batch 与 op.student.course
#       两处仓外模型 _inherit（models/class_batch.py 的分班写入口与 unlink/write 护栏），
#       无消失项 ⇒ 同为**合法边界扩张**。
#       2026-09-18（排课工具·各年级分开排）：26 → 27，只多 edu_schedule 对 op.batch 的一处
#       _inherit（models/session_ext.py 的合班批组成推导），无消失项 ⇒ 同为合法边界扩张。
#       2026-09-21（课代表，队长裁定 (b+)）：27 → 28，只多 edu_portal 对
#       op.attendance.sheet 的一处 _inherit（models/course_rep.py:448，课代表点名的
#       提交人/科目/时刻/建议四个自研字段，设计稿 §2.3 明文要求「仍落既有整班点名表」）。
#       依据（可复算）：本文件「规则 7 外部模块清单」由 27 → 28 条，逐条 diff 只多
#       edu_portal / op.attendance.sheet（= models/course_rep.py:448），无消失项
#       ⇒ 合法边界扩张（有意为之），故把边界常量跟到 28。
#   28 → 31（2026-09-22，专业编排（学制 + 必修/选修），设计稿
#       docs/plans/major-track-elective-design.md §6.2/§5.4）：edu_portal 一个文件里
#       新增三处**仓外模型** _inherit ——
#         · edu_portal / op.course       = models/major_track.py:76（学制字段 edu_level_id、
#           Subjects 页关系表 subject_line_ids、subject_ids 兼容层与两级 fallback helper）
#         · edu_portal / op.program.level = models/major_track.py:201（基座该表**没有 active**，
#           本仓红线又是零业务删除 + ondelete='restrict' ⇒ 必须补软删与排序）
#         · edu_portal / mail.thread     = models/major_track.py 的 EduCourseSubject
#           （设计 §6.2.1 要求 course_id/subject_id 带 tracking；**没有 mail.thread 时
#           Odoo 会静默忽略 tracking**，装载期报 unknown parameter ⇒ 必须给）
#       依据（可复算）：本文件「规则 7 外部模块清单」由 28 → 31 条，逐条 diff 只多上面三条
#       （文件:行号 = models/major_track.py:76 / :201 / EduCourseSubject），**无消失项**
#       ⇒ 合法边界扩张（有意为之），故把边界常量跟到 31。
#       ⚠ 待办（signup-eng 建议，本轮未做）：该常量每加一处模型扩展都要人肉跟一次 ——
#       可改成「按模块的期望清单 / 配置读取」，把这类摩擦从流程里去掉。
#   31 → 30（2026-09-25，「我的账户」学籍区 = 学号可填 + 删掉 院系/年级/学制 假标签）：
#       本批**没有**新增仓外模型 _inherit，反而**删掉一处**：
#         · edu_portal / res.partner = models/partner_edu.py（旧 ResPartnerEduLabels）
#           把 res.partner 的 company_name/vat/street2 改名成「院系/年级/学制」
#           （vat 是税号、street2 是地址第二行 ⇒ 学生把城市填进了「学制」；
#            真模型 op.department / op.program.level 早已存在 ⇒ 同名词、不同物，
#            docs/plans/major-track-elective-design.md:152 已列为重复 owner 隐患）
#           ⇒ 该 _inherit 整块删除，地址表单回到 Odoo 原生语义。
#       学号自助填写的写入口落在 models/partner_edu.py 的 OpStudentEduGrNo，
#       但 edu_portal / op.student 这个组合**早已存在**（models/invite_code.py 的
#       edu_pending_setup / 待分配标记）⇒ 不新增组合。
#       依据（可复算）：本文件「规则 7 外部模块清单」由 31 → 30 条，逐条 diff **只少**
#       edu_portal / res.partner（= models/partner_edu.py，现文件已无 _inherit），
#       无新增项 ⇒ 合法边界收缩（有意为之），故把边界常量跟到 30。
# r17（2026-10-04，全新库安装修复）：EXPECTED_EXTERNAL_MODELS 32 → 33。
#   新增的这一个来自 edu_brand/models/brand_digest.py 的 `_inherit = 'digest.digest'` ——
#   那是本轮把 38 条脆弱的 digest <function> 收敛成容错 ORM 方法时**有意**引入的（digest 已进 depends）。
#   该模型属 digest 模块（本仓之外）⇒ 计入「外部模块模型」这一边界，属预期变化。
# r18（2026-10-14，排课链路改造 G4 教师不可用）：EXPECTED_EXTERNAL_MODELS 33 → 34。
#   新增的这一个来自 edu_schedule/models/faculty_ext.py 的 `_inherit = 'op.faculty'`
#   （给基座教师档案接核心 resource.mixin，承载「例外不可用」）—— 是设计 §10.1 的**有意**接线
#   （docs/plans/scheduling-overhaul-design.md §10 / §19.3），op.faculty 属 openeducat_core
#   （本仓之外）⇒ 计入「外部模块模型」这一边界，属预期变化。
# r19（2026-10-14，录取后发放入学码 C-3）：EXPECTED_EXTERNAL_MODELS 34 → 36。
#   新增的两个来自新模块 edu_admit_invite —— `_inherit = 'edu.invite.code'`（加 application_id 列
#   与 unique(application_id)）与 `_inherit = 'edu.application'`（发放按钮 + 回执字段）。
#   这两个模型分别属 edu_portal / edu_apply（都不是 edu_admit_invite 自己的）⇒ 计入
#   「外部模块模型」边界，是设计 §18.2 的**有意**接线（docs/plans/admission-invite-link-design.md §18）。
EXPECTED_EXTERNAL_MODELS = 36   # r19：34→36（edu_admit_invite × edu.invite.code/edu.application）
SELFTEST_CASES = 26             # 断言条数（selftest 会自校验，防止悄悄漂移）

_LOCK_ENV = 'EDU_UPGRADE_LOCK'
_STATE_ENV = 'EDU_VIEW_XPATH_STATE'
_LIMIT_ENV = 'EDU_VIEW_XPATH_TRANSIENT_LIMIT'


def _tmp(name):
    return os.path.join(os.environ.get('TMPDIR') or '/tmp', name)


def _lock_path():
    """升级锁路径（与 safe_upgrade.sh 一致，可用 EDU_UPGRADE_LOCK 覆盖）。"""
    return os.environ.get(_LOCK_ENV) or _tmp('edu19_upgrade.lock')


def _lock_state():
    """返回 (锁路径, 'none' | 'self' | 'other')。

    'self' 仅在锁目录里存在 pid 标记、且内容等于本进程 PID 时成立
    （约定：<lock>/pid 写持有者 PID）。有了它，调用方就能把
    「自己的锁（调用顺序错）」与「他人正在升级」在输出上区分开。
    """
    lock = _lock_path()
    if not os.path.exists(lock):
        return lock, 'none'
    try:
        with open(os.path.join(lock, 'pid'), encoding='utf-8') as fh:
            if fh.read().strip() == str(os.getpid()):
                return lock, 'self'
    except Exception:
        pass
    return lock, 'other'


def _lock_bypass_ok(rc, out):
    """--ignore-lock 之后，锁**是不是真的被越过了**（t11）。

    判据三分，缺一不可：
      ① rc != 2 —— 仍是 2 就说明锁还在拦（"--ignore-lock 没生效"）；
      ② 输出里**不含** 'SKIP-ENV' —— 该文案专指「因锁跳过」，出现即等于被拦；
      ③ 输出里**含** 'RESULT=' —— 证明它把扫描跑完并给了结论，而不是提前崩掉/静默退出。
    ⚠ 刻意**不要求 rc == 0**：那会隐含「整个仓库此刻零问题」，队友正在编辑时会被瞬时
    跳过(退出码 3)或半成品(1)打成假红（t11 实测：未改动的 HEAD 副本同样红）。
    本函数只回答「锁被越过了没有」；仓库自身是否干净（OK/FAIL/INCOMPLETE）由它自己的
    判据负责 —— 两者混在一个断言里，正是那次假红的根因。
    """
    return rc != 2 and 'SKIP-ENV' not in out and 'RESULT=' in out


def _state_path():
    return os.environ.get(_STATE_ENV) or _tmp(
        'edu19_view_xpath_transient.json')


def _transient_limit():
    try:
        return max(1, int(os.environ.get(_LIMIT_ENV) or 3))
    except ValueError:
        return 3


def _load_state():
    try:
        with open(_state_path(), encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state):
    try:
        with open(_state_path(), 'w', encoding='utf-8') as fh:
            json.dump(state, fh)
    except Exception:
        pass


def _transient_track(changing):
    """连续 TRANSIENT 计数：达到 N 次即视为「从未被检查」并升级为失败。

    返回 (每文件计数, 达到阈值的文件列表)。本次稳定通过的文件计数清零。
    """
    state = _load_state()
    counts, escalated = {}, []
    limit = _transient_limit()
    for f in changing:
        n = int((state.get(f) or {}).get('count') or 0) + 1
        counts[f] = n
        state[f] = {'count': n, 'last': time.time()}
        if n >= limit:
            escalated.append(f)
    for f in list(state):
        if f not in counts:
            state.pop(f, None)
    _save_state(state)
    return counts, escalated


def _self_fingerprint():
    """自身文件的 md5 前 8 位（**运行时算**，避免手写版本常量忘记 bump）。

    自证机制本身不能依赖人的记性：brand-eng 手工记 md5 就被一次普通改动弄过期。
    """
    try:
        with open(os.path.abspath(__file__), 'rb') as fh:
            return hashlib.md5(fh.read()).hexdigest()[:8]
    except Exception:
        return '????????'


def _verdict(n_errors, n_incomplete, strict=False):
    """机器可读结论：(标签, 退出码)。退出码即契约（CI 只判码，不 grep 正文）：

        0 = OK          全绿
        1 = FAIL        有失败项（--strict 下 INCOMPLETE 也归为 1）
        2 = ENV         环境未就绪（升级锁被持有，见 main）
        3 = INCOMPLETE  无失败但存在"本该验却没验"的面（环境型跳过 / 边界漂移）

    注：**声明过的边界**（与 EXPECTED_* 常量一致）算已接受，不构成 INCOMPLETE；
    边界数字漂移才构成 INCOMPLETE —— 这样"边界变化"会迫使改动者更新常量，
    从而进入 diff 被 review。
    """
    if n_errors:
        return 'FAIL', 1
    if n_incomplete:
        return 'INCOMPLETE', (1 if strict else 3)
    return 'OK', 0


def _digest(path):
    """文件指纹（大小 + md5）；读不到返回 None。"""
    try:
        with open(path, 'rb') as fh:
            data = fh.read()
        return (len(data), hashlib.md5(data).hexdigest())
    except Exception:
        return None


def _stable_filter(paths, wait=1.0, reader=None):
    """过滤掉「两次读取内容不一致」的文件（正被他人写盘的瞬时快照）。

    门禁一旦出现误报，就是在训练大家忽略门禁 —— 所以扫描前先做一次
    稳定性对拍：1 秒后指纹仍一致才纳入扫描，否则只提示不判失败。
    """
    reader = reader or _digest
    before = {p: reader(p) for p in paths}
    if wait:
        time.sleep(wait)
    stable, changing = [], []
    for p in paths:
        (stable if reader(p) == before[p] else changing).append(p)
    return stable, changing


def _mtime_tag(path):
    # 错误项的「文件」字段可能带 :行号（规则 7），stat 前先剥掉
    path = re.sub(r':\d+$', '', str(path or ''))
    try:
        st = os.stat(path)
        return 'mtime=%s size=%d' % (
            time.strftime('%H:%M:%S', time.localtime(st.st_mtime)),
            st.st_size)
    except Exception:
        return 'mtime=?'

HASCLASS = re.compile(r"hasclass\(\s*(['\"])([^'\"]+)\1\s*\)")


def _translate(expr):
    """Odoo 扩展函数 hasclass('x') → 标准 XPath class 包含判断。"""
    return HASCLASS.sub(
        lambda m: ("contains(concat(' ', normalize-space(@class), ' '),"
                   " ' %s ')" % m.group(2)), expr)


def _module_dirs(roots):
    mods = set()
    for r in roots:
        for d in glob.glob(r + '/*'):
            if os.path.isdir(d) and os.path.exists(
                    os.path.join(d, '__manifest__.py')):
                mods.add(os.path.basename(d))
    return mods


def _local_id(xmlid):
    return (xmlid or '').split('.')[-1]


def _arch_payload(arch_field):
    kids = list(arch_field)
    if kids:
        return ''.join(etree.tostring(k, encoding='unicode') for k in kids)
    return arch_field.text or ''


def _is_directive(node, names=('t-else', 't-elif')):
    return any(node.get(n) is not None for n in names)


def _prev_element(node):
    prev = node.getprevious()
    while prev is not None and not isinstance(prev.tag, str):
        prev = prev.getprevious()
    return prev


def _next_element(node):
    nxt = node.getnext()
    while nxt is not None and not isinstance(nxt.tag, str):
        nxt = nxt.getnext()
    return nxt


def _content_type_errors(f, label, nodes, force=False):
    """t53：内容型/COW 继承的根数校验。

    判定：顶层（含 <data> 分组内一层）既无 <xpath> 也无带 position 的元素
    → 内容型继承 → 必须单根且根不能是 <data>（否则子节点会被当继承定位指令，
    渲染期炸「上级视图内找不到元素」）。含 xpath/position 的扩展型不判，避免误红。

    force=True（t57）：调用方已判定这是 COW 副本（inherit_id + mode=primary）——
    此时**不看顶层有无 xpath**，一律按内容型判：Odoo 的继承遍历遇 primary 即停
    （ir_ui_view.py:448/455），其 arch 必须是完整 arch。
    """
    directive = False
    for node in nodes:
        if node.tag == 'xpath' or node.get('position') is not None:
            directive = True
        if node.tag == 'data':
            for kid in node:
                if kid.tag == 'xpath' or kid.get('position') is not None:
                    directive = True
    if directive and not force:
        return []
    if len(nodes) != 1:
        return [('ARCH', f, label,
                 '内容型继承 arch 必须单根（顶层无 xpath/position 指令），实际 %d 个根节点'
                 % len(nodes))]
    if nodes[0].tag == 'data':
        return [('ARCH', f, label,
                 '内容型继承 arch 的根不能是 <data>（子节点会被当继承定位指令）')]
    return []


def _adjacency_errors(f, node, label=''):
    """6c：给定容器，检查其子元素的 t-else/t-elif 相邻性。"""
    out = []
    for child in node:
        if not isinstance(child.tag, str) or not _is_directive(child):
            continue
        prev = _prev_element(child)
        if prev is None:
            out.append(('QWEB-ADJ', f, label or (node.get('id') or ''),
                        't-else/t-elif 前没有兄弟元素（相邻的 t-if 不在同一层）'))
        elif prev.get('t-if') is None and prev.get('t-elif') is None:
            out.append(('QWEB-ADJ', f, label or (node.get('id') or ''),
                        't-else/t-elif 的前一个兄弟元素 <%s> 没有 t-if/t-elif '
                        '→ 渲染期 SyntaxError' % prev.tag))
    return out


def _module_paths(roots):
    """所有模块目录（含 __manifest__.py）。"""
    out = []
    for r in roots:
        # 允许直接把「单个模块目录」当扫描根（selftest 与定点排查都用得上）
        if os.path.exists(os.path.join(r, "__manifest__.py")):
            out.append(r)
        for d in sorted(glob.glob(r + "/*")):
            if os.path.isdir(d) and os.path.exists(
                    os.path.join(d, "__manifest__.py")):
                out.append(d)
    return out


def _init_import_order(init_path):
    """models/__init__.py 里的 `from . import X` 顺序（= 装载顺序）。"""
    try:
        with open(init_path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except Exception:
        return []
    order = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 \
                and not node.module:
            for alias in node.names:
                if alias.name not in order:
                    order.append(alias.name)
    return order


def _model_defs(path):
    """解析一个 models/*.py：返回 (定义的模型集合, _inherit/_inherits 的模型集合)。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except Exception:
        return None
    defined, inherited = set(), {}

    def _strings(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            out = []
            for e in node.elts:
                out += _strings(e)
            return out
        if isinstance(node, ast.Dict):
            out = []
            for k in node.keys:
                out += _strings(k)
            return out
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            for tgt in item.targets:
                if not isinstance(tgt, ast.Name):
                    continue
                if tgt.id == "_name":
                    defined.update(_strings(item.value))
                elif tgt.id in ("_inherit", "_inherits"):
                    for model in _strings(item.value):
                        # 记录行号：报错要能直接点到那一行（t38 验收）
                        inherited.setdefault(model, item.lineno)
    return defined, inherited


def _find_cycles(deps):
    """返回依赖图中的环（每个环一个节点列表）。"""
    cycles, seen, stack = [], set(), []

    def visit(node):
        if node in stack:
            cycles.append(stack[stack.index(node):])
            return
        if node in seen:
            return
        seen.add(node)
        stack.append(node)
        for nxt in deps.get(node, []):
            visit(nxt)
        stack.pop()

    for node in list(deps):
        visit(node)
    return cycles


def _model_import_scan(roots, out_external=None):
    """规则 7：models/*.py 的 _inherit 导入顺序（分层报错）。

    A 文件 _inherit 的模型若由同模块 B 文件定义，则 B 必须先于 A 被导入：
    - 违序但重排可解 → IMPORT-ORDER（给出两个导入序号与改法）
    - 依赖成环（互相 _inherit）→ CIRCULAR-INHERIT（重排无解，列环上文件与模型）

    out_external（t10 追加，可选）：非 None 时，把本次跳过的「外部模块模型」逐条
    追加为 (模块名, 模型名, "文件:行号"串)。理由是实测教训：BOUNDARY-DRIFT 只报
    「19 ≠ 常量 18」时，复核者得自己重新实现一遍口径才能知道多出来的是谁
    （t10 就是这么查的）。返回值（计数）与既有行为保持不变。
    """
    errors = []
    skipped_external = 0
    for module_dir in _module_paths(roots):
        models_dir = os.path.join(module_dir, "models")
        init = os.path.join(models_dir, "__init__.py")
        if not os.path.exists(init):
            continue
        order = _init_import_order(init)
        info, defined_by = {}, {}
        for stem in order:
            parsed = _model_defs(os.path.join(models_dir, stem + ".py"))
            if parsed is None:
                continue
            defined, inherited = parsed
            info[stem] = {"path": os.path.join(models_dir, stem + ".py"),
                          "defined": defined, "inherited": inherited}
            for model in defined:
                defined_by.setdefault(model, stem)
        external = sorted({m for meta in info.values()
                           for m in meta["inherited"]
                           if m not in defined_by})
        if external:
            skipped_external += len(external)
            if out_external is not None:
                _dmod = os.path.basename(module_dir)
                for _m in external:
                    out_external.append(
                        (_dmod, _m,
                         "、".join("%s:%s" % (info[_s]["path"],
                                             _meta["inherited"][_m])
                                   for _s, _meta in sorted(info.items())
                                   if _m in _meta["inherited"])))
        deps = {}
        for stem, meta in info.items():
            deps[stem] = sorted({defined_by[m] for m in meta["inherited"]
                                 if m in defined_by and defined_by[m] != stem})
        cycles = _find_cycles(deps)
        cyc_nodes = set()
        for cyc in cycles:
            cyc_nodes |= set(cyc)
            files = [info[s]["path"] for s in cyc]
            detail = "、".join(
                "%s:%s → %s" % (os.path.basename(info[s]["path"]),
                                info[s]["inherited"][m], m)
                for s in sorted(cyc)
                for m in sorted(info[s]["inherited"])
                if defined_by.get(m) in cyc)
            errors.append(("CIRCULAR-INHERIT", files[0],
                           "、".join(os.path.basename(p) for p in files),
                           "互相 _inherit（%s）：重排无解，需结构性调整"
                           % detail))
        idx = {stem: i for i, stem in enumerate(order)}
        for stem, dep_list in deps.items():
            if stem in cyc_nodes:
                continue
            for dep in dep_list:
                if dep in cyc_nodes or dep not in idx:
                    continue
                if idx[stem] < idx[dep]:
                    linenos = sorted({info[stem]["inherited"][m]
                                      for m in info[stem]["inherited"]
                                      if defined_by.get(m) == dep})
                    loc = "%s:%s" % (info[stem]["path"],
                                     linenos[0] if linenos else "?")
                    errors.append(("IMPORT-ORDER", loc,
                                   "第 %d 位 %s ← 依赖第 %d 位 %s"
                                   % (idx[stem] + 1, stem,
                                      idx[dep] + 1, dep),
                                   "把 %s 提到 %s 之前（%s 定义的模型必须先注册）"
                                   % (dep, stem, dep)))
    return errors, skipped_external

def _route_scan(roots):
    """规则 5：@http.route 归属歧义（AST 静态分析，不 import odoo）。"""
    def routes_of(dec):
        out = set()
        if not isinstance(dec, ast.Call):
            return out
        args = list(dec.args)
        for kw in dec.keywords:
            if kw.arg == 'route':
                args.append(kw.value)
        for a in args:
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                out.add(a.value)
            elif isinstance(a, (ast.List, ast.Tuple)):
                for e in a.elts:
                    if isinstance(e, ast.Constant) and isinstance(e.value, str):
                        out.add(e.value)
        return out

    errors = []
    classes = {}
    for r in roots:
        for f in sorted(glob.glob(r + '/**/controllers/*.py', recursive=True)):
            try:
                with open(f, encoding='utf-8') as fh:
                    tree = ast.parse(fh.read())
            except Exception as exc:
                errors.append(('PYERROR', f, '-', str(exc)))
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                rs = set()
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for dec in item.decorator_list:
                            rs |= routes_of(dec)
                classes[(f, node.name)] = {
                    'name': node.name, 'file': f,
                    'bases': [ast.unparse(b).split('.')[-1] for b in node.bases],
                    'routes': rs}

    def ancestors(name, seen=None):
        seen = set() if seen is None else seen
        for _key, info in classes.items():
            if info['name'] == name:
                for b in info['bases']:
                    if b not in seen:
                        seen.add(b)
                        ancestors(b, seen)
        return seen

    by_route = {}
    for (f, name), info in classes.items():
        for route in info['routes']:
            by_route.setdefault(route, []).append((f, name))

    for route, owners in sorted(by_route.items()):
        if len(owners) < 2:
            continue
        for i, (f1, n1) in enumerate(owners):
            for f2, n2 in owners[i + 1:]:
                if n1 == n2:
                    continue
                if n2 in ancestors(n1) or n1 in ancestors(n2):
                    continue        # 父子覆盖：Odoo 合法机制
                errors.append((
                    'ROUTE-AMBIG', f1, route,
                    '与 %s:%s 竞争（互不为父子，归属随加载顺序漂移）'
                    % (f2, n2)))
    return errors


def _scan(roots, verbose=True, out=None):
    xml_files = []
    for r in roots:
        xml_files += sorted(glob.glob(r + '/**/*.xml', recursive=True))

    # 瞬时快照防护（t36-F2）：1 秒后指纹仍一致的才纳入扫描，其余只提示
    files, changing = _stable_filter(xml_files)

    errors = []
    changing_counts, escalated_transient = {}, []
    if verbose:
        # t50：反复跳过不等于长期免检 —— 连续 N 次都跳过的文件升级为失败。
        # 注意：即使 changing 为空也要调用，否则陈旧计数永不清零，
        # 文件下次偶然再跳过就直接够阈值（假升级）。
        changing_counts, escalated_transient = _transient_track(changing)
        for f in escalated_transient:
            errors.append((
                'TRANSIENT-LIMIT', f,
                '连续 %d 次扫描期间内容都在变化' % changing_counts[f],
                '视为「从未被检查」而不是通过；请确认是否有写入方长期占用'
                '该文件，必要时用 --ignore-lock 之外的窗口复跑'))
    tpls, records, parsed = {}, {}, {}
    for f in files:
        try:
            root = etree.parse(f).getroot()
        except Exception as exc:
            errors.append(('SYNTAX', f, '', str(exc)))
            continue
        parsed[f] = root
        for t in root.iter('template'):
            if t.get('id'):
                tpls.setdefault(_local_id(t.get('id')), (t, f))
        for rec in root.iter('record'):
            if rec.get('model') == 'ir.ui.view' and rec.get('id'):
                records.setdefault(_local_id(rec.get('id')), (rec, f))

    mods = _module_dirs(roots)
    checked = skipped = extended = 0
    skip_mods = {}

    # ---- 规则 2/3/6a/6b：继承视图 ----
    for f, root in parsed.items():
        for t in root.iter('template'):
            inherit = t.get('inherit_id') or ''
            if not inherit:
                continue
            parent = (tpls.get(_local_id(inherit))
                      or records.get(_local_id(inherit)))
            if parent is None:
                mod = inherit.split('.')[0] if '.' in inherit else ''
                if mod and mod not in mods:
                    skipped += 1
                    skip_mods[mod] = skip_mods.get(mod, 0) + 1
                else:
                    errors.append(('UNRESOLVED', f, inherit,
                                   'inherit_id 指向的视图在本仓内不存在'))
                continue
            checked += 1
            pnode = parent[0]
            for xp in t.iter('xpath'):
                expr = xp.get('expr')
                if not expr:
                    continue
                pos = xp.get('position') or 'inside'
                std = _translate(expr)
                if std != expr:
                    extended += 1
                try:
                    hits = pnode.xpath(std)
                except Exception as exc:
                    errors.append(('BADEXPR', f, expr, str(exc)))
                    continue
                if not hits:
                    # 所有 position 都报：before/after 命中 0 也必须在升级前暴露
                    hint = ''
                    for attr in re.findall(r'@([A-Za-z0-9_-]+)', expr):
                        if pnode.xpath('//*[@t-attf-%s or @t-att-%s]'
                                       % (attr, attr)):
                            hint = ('父 arch 里只有 t-attf-%s / t-att-%s，'
                                    '请写 contains(@t-attf-%s, ...)'
                                    % (attr, attr, attr))
                            break
                    errors.append(('NOMATCH', f, expr, hint))
                # 规则 6a/6b：插入点会不会打断 t-if/t-else 相邻性
                for tgt in hits:
                    if pos == 'before' and _is_directive(tgt):
                        errors.append((
                            'QWEB-ADJ', f, expr,
                            'position=before 的目标 <%s> 带 t-else/t-elif：'
                            '插入会打断相邻性 → 渲染期 SyntaxError'
                            % tgt.tag))
                    else:
                        is_if = (tgt.get('t-if') is not None
                                 or tgt.get('t-elif') is not None)
                        if pos == 'after' and is_if:
                            nxt = _next_element(tgt)
                            if nxt is not None and _is_directive(nxt):
                                errors.append((
                                    'QWEB-ADJ', f, expr,
                                    'position=after 的目标 <t t-if> 之后紧跟 '
                                    't-else/t-elif：插入同样会打断相邻性'))

    # ---- 规则 4 + 6c：arch 载荷 / 主视图相邻性 ----
    for f, root in parsed.items():
        for t in root.iter('template'):
            if t.get('inherit_id'):
                # t53：继承型 template 也要分「内容型 / 扩展型」；内容型判根数，
                # 扩展型不判相邻性（合并后兄弟关系会变，见覆盖边界）
                errors += _content_type_errors(f, t.get('id') or '',
                                               list(t))
                continue
            # 逐个容器检查其子元素的 t-else/t-elif 相邻性（含嵌套层）
            for node in t.iter():
                if isinstance(node.tag, str):
                    errors += _adjacency_errors(f, node, t.get('id') or '')
        for rec in root.iter('record'):
            if rec.get('model') != 'ir.ui.view':
                continue
            rid = rec.get('id') or ''
            arch = inherit = mode_fld = None
            for fld in rec.findall('field'):
                if fld.get('name') == 'arch':
                    arch = fld
                elif fld.get('name') == 'inherit_id':
                    inherit = fld
                elif fld.get('name') == 'mode':
                    mode_fld = fld
            if arch is None:
                continue
            payload = _arch_payload(arch).strip()
            if not payload:
                continue
            try:
                wrapped = etree.fromstring('<archwrap>%s</archwrap>' % payload)
            except Exception as exc:
                errors.append(('ARCH', f, rid, str(exc)))
                continue
            nodes = list(wrapped)
            if inherit is not None:
                # t57：显式 mode=primary = COW 副本 → 按内容型判（不看 xpath）
                is_cow = (mode_fld is not None
                          and (mode_fld.text or '').strip() == 'primary')
                errors += _content_type_errors(f, rid, nodes, force=is_cow)
            if inherit is None:
                if len(nodes) != 1:
                    errors.append(('ARCH', f, rid,
                                   '主视图 arch 必须单根，实际 %d 个根节点'
                                   % len(nodes)))
                elif nodes[0].tag == 'data':
                    errors.append(('ARCH', f, rid,
                                   '主视图 arch 的根不能是 <data>'))
                else:
                    for node in wrapped.iter():
                        errors += _adjacency_errors(f, node, rid)

    errors += _route_scan(roots)
    external_rows = []          # t10：外部模块模型清单（打印用；见 _model_import_scan）
    order_errors, skipped_external = _model_import_scan(roots, external_rows)
    errors += order_errors

    if verbose:
        for f in changing:
            flag = ('已升级为失败（达阈值 %d 次）' % _transient_limit()
                    if f in escalated_transient else '本次跳过、不判失败')
            print('WARN-TRANSIENT %s :: 1 秒内内容仍在变化（疑似他人正在写盘）：'
                  '连续第 %d 次，%s；请间隔数秒复跑（%s）'
                  % (f, changing_counts.get(f, 0), flag, _mtime_tag(f)))
        for kind, f, extra, msg in errors:
            tag = ''
            if kind in ('SYNTAX', 'ARCH', 'PYERROR', 'IMPORT-ORDER',
                        'CIRCULAR-INHERIT'):
                tag = ' [%s；若该文件正被他人编辑，请间隔数秒复跑]' % _mtime_tag(f)
            print('%-15s %s :: %s%s%s' % (
                kind, f, extra, (' :: %s' % msg) if msg else '', tag))
        print('失败项合计 = %d | 继承模板检查 = %d（含 Odoo 扩展函数 %d）'
              % (len(errors), checked, extended))
        # 显式打印未覆盖范围：不能只报「检查了 N 处 / 0 失配」，那读起来像全绿
        detail = ', '.join('%s x%d' % kv for kv in sorted(skip_mods.items()))
        detail = detail or '无'
        print('未覆盖（跳过）= %d 处跨模块继承 [%s]；规则 7 跳过 %d 个外部模块模型'
              '；瞬时跳过 %d 个文件'
              % (skipped, detail, skipped_external, len(changing)))
        # t10：把「外部模块模型清单」本身打出来。只报数字时，边界漂移的复核者
        # 必须自己重实现一遍口径才知道多出来的是谁（t10 实测：查第 19 个花了一轮）；
        # 清单一行常驻 ⇒ 漂移时直接肉眼对账，漂移还附 文件:行号。
        if external_rows:
            print('规则 7 外部模块清单（%d 条 / 常量 %d）：%s'
                  % (len(external_rows), EXPECTED_EXTERNAL_MODELS,
                     '，'.join('%s/%s' % (mod, model)
                               for mod, model, _loc in sorted(external_rows))))
            if skipped_external != EXPECTED_EXTERNAL_MODELS:
                print('  ↳ 与常量不一致，逐条位置（对账用；少的那条在上面清单里找不到）：')
                for mod, model, loc in sorted(external_rows):
                    print('    EXT %-12s %-32s %s' % (mod, model, loc))
        if changing:
            print('TRANSIENT_SKIPPED = %d 个文件本次未检查：%s（连续次数，达 %d 次升级为失败）'
                  % (len(changing),
                     ', '.join('%s ×%d'
                               % (os.path.basename(f), changing_counts.get(f, 0))
                               for f in changing),
                     _transient_limit()))
        print('！！跳过项 = 未覆盖：跨模块父模板在本仓之外，规则 2/6a/6b 无法求值；'
              '本脚本不是「继承 xpath 全绿」的证明')
        transient_open = max(0, len(changing) - len(escalated_transient))
        drifts = []
        if skipped != EXPECTED_SKIPPED_INHERIT:
            drifts.append('跨模块继承跳过 %d ≠ 常量 %d'
                          % (skipped, EXPECTED_SKIPPED_INHERIT))
        if skipped_external != EXPECTED_EXTERNAL_MODELS:
            drifts.append('外部模块模型跳过 %d ≠ 常量 %d（清单与逐条位置见上方'
                          '「规则 7 外部模块清单」）'
                          % (skipped_external, EXPECTED_EXTERNAL_MODELS))
        for d in drifts:
            print('BOUNDARY-DRIFT %s —— 若边界变化是有意为之，请更新 '
                  'EXPECTED_* 常量使其进入 diff；否则视为未覆盖' % d)
        incomplete_n = transient_open + (1 if drifts else 0)
        label, _code = _verdict(len(errors), incomplete_n, False)
        print('RESULT=%s（失败项 %d / 未覆盖 %d = 环境型跳过 %d + 边界漂移 %d）'
              ' REVISION=%s · 指纹 %s · 断言 %d 条 · 运行 %s'
              % (label, len(errors), incomplete_n, transient_open,
                 len(drifts), REVISION, _self_fingerprint(), SELFTEST_CASES,
                 RUN_STAMP))
        print('契约：exit 0=OK 1=FAIL 2=ENV(升级锁) 3=INCOMPLETE；'
              '--strict 把 INCOMPLETE 归为 1；声明过的边界（EXPECTED_*）算已接受')
    if out is not None:
        transient_open = max(0, len(changing) - len(escalated_transient))
        drift_n = 0
        if skipped != EXPECTED_SKIPPED_INHERIT:
            drift_n += 1
        if skipped_external != EXPECTED_EXTERNAL_MODELS:
            drift_n += 1
        out['errors'] = len(errors)
        out['incomplete'] = transient_open + (1 if drift_n else 0)
    return errors, checked, skipped, extended, skip_mods


def _write(path, text):
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)


def _selftest():
    """双向断言：正例必须放过，反例必须报错。"""
    ok = True
    emitted = []
    import builtins
    _orig_print = builtins.print

    def _spy(*args, **kwargs):        # 统计断言条数 → 自校验 SELFTEST_CASES
        line = ' '.join(str(a) for a in args)
        if line.startswith('SELFTEST'):
            emitted.append(line)
        _orig_print(*args, **kwargs)
    print = _spy
    with tempfile.TemporaryDirectory() as d:
        _write(os.path.join(d, 'parent.xml'),
               '<odoo>\n  <template id="p_view" name="P">\n'
               '    <form role="form" class="oe_login_form">\n'
               '      <a t-attf-href="/web/reset_password?x=1">r</a>\n'
               '      <t t-foreach="items" t-as="it"><tr><td>c</td></tr></t>\n'
               '    </form>\n'
               '    <t t-if="leaves">a</t>\n'
               '    <table class="tbl" t-else="">b</table>\n'
               '  </template>\n</odoo>\n')
        cases = [
            ('good_hasclass',
             '<odoo><template id="c1" inherit_id="p_view">'
             '<xpath expr="//form[hasclass(\'oe_login_form\')]" '
             'position="inside"><span/></xpath></template></odoo>', 0),
            ('good_foreach_row',
             '<odoo><template id="c2" inherit_id="p_view">'
             '<xpath expr="//t[@t-foreach=\'items\']//tr/td[1]" '
             'position="before"><td/></xpath></template></odoo>', 0),
            ('good_insert_before_plain',
             '<odoo><template id="c7" inherit_id="p_view">'
             '<xpath expr="//form" position="before"><span/></xpath>'
             '</template></odoo>', 0),
            ('good_primary_telse_adjacent',
             '<odoo><template id="c8"><div><t t-if="a">a</t>'
             '<p t-else="">b</p></div></template></odoo>', 0),
            ('bad_insert_before_telse',
             '<odoo><template id="c9" inherit_id="p_view">'
             '<xpath expr="//table" position="before"><span/></xpath>'
             '</template></odoo>', 1),
            ('bad_primary_telse_broken',
             '<odoo><template id="c10"><div><t t-if="a">a</t><span/>'
             '<p t-else="">b</p></div></template></odoo>', 1),
            ('bad_unresolved',
             '<odoo><template id="c6" inherit_id="nope_view">'
             '<xpath expr="//form" position="inside"/></template></odoo>', 1),
            ('bad_primary_multi_root',
             '<odoo><record id="v1" model="ir.ui.view"><field name="arch" '
             'type="xml"><form/><list/></field></record></odoo>', 1),
            # t53：内容型/COW 继承（顶层无 xpath/position）两条真实反例 + 一条正例
            ('bad_cow_multi_root',
             '<odoo><template id="cc1" inherit_id="p_view">'
             '<t t-set="title">x</t><t t-call="website.layout"></t>'
             '</template></odoo>', 1),
            ('bad_cow_data_wrapper',
             '<odoo><template id="cc2" inherit_id="p_view"><data>'
             '<t t-set="title">x</t><t t-call="website.layout"></t>'
             '</data></template></odoo>', 1),
            # t57：inherit_id + mode=primary = COW 副本 → 即使有 xpath 也按内容型判
            ('bad_primary_mode_mixed_root',
             '<odoo><record id="pv1" model="ir.ui.view">'
             '<field name="inherit_id" ref="p_view"/>'
             '<field name="mode">primary</field>'
             '<field name="arch" type="xml"><form><xpath expr="//form" '
             'position="inside"><span/></xpath></form><list/></field>'
             '</record></odoo>', 1),
            ('good_primary_mode_single_root',
             '<odoo><record id="pv2" model="ir.ui.view">'
             '<field name="inherit_id" ref="p_view"/>'
             '<field name="mode">primary</field>'
             '<field name="arch" type="xml"><form><field name="name"/>'
             '</form></field></record></odoo>', 0),
            ('good_cow_single_root',
             '<odoo><template id="cc3" inherit_id="p_view">'
             '<t t-call="website.layout"><t t-set="title">x</t></t>'
             '</template></odoo>', 0),
            ('good_primary_single_root',
             '<odoo><record id="v2" model="ir.ui.view"><field name="arch" '
             'type="xml"><form><field name="name"/></form></field>'
             '</record></odoo>', 0),
        ]
        rdir = os.path.join(d, 'fakemod', 'controllers')
        os.makedirs(rdir, exist_ok=True)
        route_cases = [
            ('good_route_child_override',
             'from odoo import http\n\n'
             'class Base(http.Controller):\n'
             '    @http.route(\'/x\', type=\'http\', auth=\'user\')\n'
             '    def x(self):\n        pass\n\n'
             'class Leaf(Base):\n'
             '    @http.route(\'/x\', type=\'http\', auth=\'user\')\n'
             '    def x(self):\n        pass\n', 0),
            ('bad_route_two_owners',
             'from odoo import http\n\n'
             'class A(http.Controller):\n'
             '    @http.route(\'/y\', type=\'http\', auth=\'user\')\n'
             '    def y(self):\n        pass\n\n'
             'class B(http.Controller):\n'
             '    @http.route(\'/y\', type=\'http\', auth=\'user\')\n'
             '    def y(self):\n        pass\n', 1),
        ]
        for name, body, expect_bad in route_cases:
            target = os.path.join(rdir, name + '.py')
            _write(target, body)
            errs, _c, _s, _e, _m = _scan([d], verbose=False)
            n = len([e for e in errs if e[0].startswith('ROUTE')])
            good = (n > 0) == bool(expect_bad)
            ok = ok and good
            print('SELFTEST %s %-31s（期望%s，实际 %d 项）'
                  % ('PASS' if good else 'FAIL', name,
                     '报错' if expect_bad else '干净', n))
            os.remove(target)

        for name, body, expect_bad in cases:
            target = os.path.join(d, name + '.xml')
            _write(target, body)
            errs, _c, _s, _e, _m = _scan([d], verbose=False)
            n = len([e for e in errs if not e[0].startswith('ROUTE')])
            good = (n > 0) == bool(expect_bad)
            ok = ok and good
            print('SELFTEST %s %-31s（期望%s，实际 %d 项）'
                  % ('PASS' if good else 'FAIL', name,
                     '报错' if expect_bad else '干净', n))
            os.remove(target)
        # ---- 规则 7：导入顺序（可重排 IMPORT-ORDER vs 成环 CIRCULAR-INHERIT）----
        order_cases = [
            ('bad_import_order', 'IMPORT-ORDER', 1, {
                '__init__.py': 'from . import a\nfrom . import b\n',
                'a.py': "class A(models.Model):\n    _name = 't.a'\n"
                        "    _inherit = 't.b'\n",
                'b.py': "class B(models.Model):\n    _name = 't.b'\n",
            }),
            ('bad_circular', 'CIRCULAR-INHERIT', 1, {
                '__init__.py': 'from . import p\nfrom . import q\n',
                'p.py': "class P(models.Model):\n    _name = 't.p'\n"
                        "    _inherit = 't.q'\n",
                'q.py': "class Q(models.Model):\n    _name = 't.q'\n"
                        "    _inherit = 't.p'\n",
            }),
            ('good_import_order', 'IMPORT-ORDER', 0, {
                '__init__.py': 'from . import b\nfrom . import a\n',
                'a.py': "class A(models.Model):\n    _name = 't.a'\n"
                        "    _inherit = 't.b'\n",
                'b.py': "class B(models.Model):\n    _name = 't.b'\n",
            }),
        ]
        for name, kind, expect_bad, files_map in order_cases:
            sub = os.path.join(d, 'ord_' + name)
            mdir = os.path.join(sub, 'models')
            os.makedirs(mdir, exist_ok=True)
            _write(os.path.join(sub, '__manifest__.py'), "{'name': 'x'}")
            for fn, body in files_map.items():
                _write(os.path.join(mdir, fn), body)
            errs, _c, _s, _e, _m = _scan([sub], verbose=False)
            n = len([e for e in errs if e[0] == kind])
            good = (n > 0) == bool(expect_bad)
            ok = ok and good
            print('SELFTEST %s %-31s（期望%s %s，实际 %d 项）'
                  % ('PASS' if good else 'FAIL', name,
                     '报错' if expect_bad else '干净', kind or '无', n))

        # ---- 瞬时快照防护：reader 变化时不得计入稳定集 ----
        p1 = os.path.join(d, 'stable_probe.xml')
        p2 = os.path.join(d, 'changing_probe.xml')
        _write(p1, '<odoo/>')
        _write(p2, '<odoo/>')
        counter = {'n': 0}

        def _reader(path):
            if path.endswith('changing_probe.xml'):
                counter['n'] += 1
                return ('v%d' % counter['n'],)
            return ('same',)

        stable, moving = _stable_filter([p1, p2], wait=0, reader=_reader)
        good = (p1 in stable) and (p2 in moving)
        ok = ok and good
        print('SELFTEST %s %-31s（期望 稳定=%s / 变化=%s）'
              % ('PASS' if good else 'FAIL', 'transient_stability',
                 os.path.basename(p1), os.path.basename(p2)))
        # ---- t50：连续 TRANSIENT 升级为失败 + 锁语义（子进程跑 CLI）----
        st_path = os.path.join(d, 'transient_state.json')
        probe = os.path.join(d, 'flapping.xml')
        _write(probe, '<odoo/>')
        keys = ('EDU_VIEW_XPATH_STATE', 'EDU_VIEW_XPATH_TRANSIENT_LIMIT',
                'EDU_UPGRADE_LOCK')
        backup = {k: os.environ.get(k) for k in keys}
        os.environ['EDU_VIEW_XPATH_STATE'] = st_path
        os.environ['EDU_VIEW_XPATH_TRANSIENT_LIMIT'] = '3'
        seq = []
        for _i in range(3):
            counts, esc = _transient_track([probe])
            seq.append((counts.get(probe), bool(esc)))
        _transient_track([])          # 某次稳定 → 计数清零
        counts_after, esc_after = _transient_track([probe])
        good = (seq == [(1, False), (2, False), (3, True)]
                and counts_after.get(probe) == 1 and not esc_after)
        ok = ok and good
        print('SELFTEST %s %-31s（期望 1/2/3 且第 3 次升级，清零后回 1；实际 %s）'
              % ('PASS' if good else 'FAIL', 'transient_escalation', seq))
        lock = os.path.join(d, 'fake.lock')
        _write(lock, '')
        script = os.path.abspath(__file__)
        env_locked = dict(os.environ, EDU_UPGRADE_LOCK=lock)
        r1 = subprocess.run([sys.executable, script], capture_output=True,
                            text=True, timeout=90, env=env_locked)
        r2 = subprocess.run([sys.executable, script, '--ignore-lock'],
                            capture_output=True, text=True, timeout=90,
                            env=env_locked)
        # 自己的锁 vs 他人的锁：pid 标记等于本进程 PID 时判 self
        if os.path.exists(lock):
            os.remove(lock)          # 上面为子进程测试建的是「文件」，这里改「目录」
        os.environ['EDU_UPGRADE_LOCK'] = lock   # 进程内也要指向同一个假锁
        os.makedirs(lock, exist_ok=True)
        own = os.path.join(lock, 'pid')
        _write(own, str(os.getpid()))
        state_self = _lock_state()[1]
        _write(own, '999999')
        state_other = _lock_state()[1]
        os.remove(own)
        os.rmdir(lock)
        state_none = _lock_state()[1]
        good3 = (state_self, state_other, state_none) == ('self', 'other',
                                                          'none')
        ok = ok and good3
        print('SELFTEST %s %-31s（pid=本进程→%s / 他人 pid→%s / 无锁→%s）'
              % ('PASS' if good3 else 'FAIL', 'lock_state_distinct',
                 state_self, state_other, state_none))
        _write(lock, '')
        # t11：r2 的判据从「exit 0」改为「锁真的被越过」（_lock_bypass_ok 三分判据）。
        # 原判据把「锁语义」与「仓库此刻是否干净」耦合在一起 ⇒ 队友编辑期间假红。
        good2 = (r1.returncode == 2 and 'SKIP-ENV' in r1.stdout
                 and '他人正在升级' in r1.stdout
                 and _lock_bypass_ok(r2.returncode, r2.stdout))
        ok = ok and good2
        print('SELFTEST %s %-31s（锁→exit %d + SKIP-ENV=%s；--ignore-lock→exit %d，'
              '越锁=%s 跑完扫描=%s）'
              % ('PASS' if good2 else 'FAIL', 'lock_exit2',
                 r1.returncode, 'SKIP-ENV' in r1.stdout, r2.returncode,
                 _lock_bypass_ok(r2.returncode, r2.stdout),
                 'RESULT=' in r2.stdout))
        for k in keys:
            if backup[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = backup[k]
    # 结论词映射（机器可读）：FAIL/1、INCOMPLETE(0 或 --strict 3)、OK/0
    verdict_cases = [((0, 0, False), ('OK', 0)),
                     ((0, 3, False), ('INCOMPLETE', 3)),
                     ((0, 3, True), ('INCOMPLETE', 1)),
                     ((2, 0, False), ('FAIL', 1)),
                     ((2, 5, True), ('FAIL', 1))]
    bad = [(c, exp) for c, exp in verdict_cases
           if _verdict(c[0], c[1], strict=c[2]) != exp]
    good = not bad
    ok = ok and good
    print('SELFTEST %s %-31s（5 组输入→标签/退出码；不符 %d 组）'
          % ('PASS' if good else 'FAIL', 'verdict_mapping', len(bad)))
    # t57：运行时指纹必须真有 8 位十六进制（自证机制不依赖人的记性）
    fp = _self_fingerprint()
    good = len(fp) == 8 and all(c in '0123456789abcdef' for c in fp)
    ok = ok and good
    print('SELFTEST %s %-31s（指纹 %s）'
          % ('PASS' if good else 'FAIL', 'self_fingerprint', fp))
    # t72：运行时刻必须是**可解析的 ISO 8601 且带时区偏移**
    try:
        _parsed = datetime.datetime.fromisoformat(RUN_STAMP)
        good_stamp = _parsed.utcoffset() is not None
    except ValueError:
        good_stamp = False
    ok = ok and good_stamp
    print('SELFTEST %s %-31s（运行 %s）'
          % ('PASS' if good_stamp else 'FAIL', 'run_stamp_format', RUN_STAMP))
    counted = len(emitted)
    drift = counted != SELFTEST_CASES
    ok = ok and not drift
    print('SELFTEST 总结：%s（REVISION=%s · 指纹 %s · 断言 %d 条 · 运行 %s%s）'
          % ('全部通过' if ok else '存在失败', REVISION, _self_fingerprint(),
             counted, RUN_STAMP,
             '' if not drift else '；与常量 SELFTEST_CASES=%d 不一致（漂移）'
             % SELFTEST_CASES))
    return 0 if ok else 1


if __name__ == '__main__':
    argv = sys.argv[1:]
    if '--selftest' in argv:
        sys.exit(_selftest())
    lock, lock_state = _lock_state()
    if lock_state != 'none' and '--ignore-lock' not in argv:
        # t50：环境未就绪 ≠ 检查通过（exit 2 与「检查失败 exit 1」区分）
        if lock_state == 'self':
            print('SKIP-ENV：这是**本进程自己**持有的升级锁（%s）——调用契约应为'
                  '「先跑静态检查、再取锁」；本工具不把它当作他人升级。'
                  '确需强跑请加 --ignore-lock。' % lock)
        else:
            print('SKIP-ENV：他人正在升级（锁 %s 被持有）——环境未就绪，'
                  '本次未做检查；这不是「检查通过」（exit 2，与检查失败 exit 1 '
                  '区分）。确需离线强跑请加 --ignore-lock。' % lock)
        sys.exit(2)
    args = [a for a in argv if not a.startswith('--')]
    info = {}
    errs, _c, _s, _e, _m = _scan(args or ['custom_addons'], out=info)
    _label, code = _verdict(len(errs), info.get('incomplete', 0),
                            '--strict' in argv)
    sys.exit(code)
