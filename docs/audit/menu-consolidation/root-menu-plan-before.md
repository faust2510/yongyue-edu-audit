# 根菜单施工图数据源（口径 A 全部 40 行，含 inactive 1）
# 生成工具：scripts/menu_baseline.py（plan 模式，只读）｜生成时间(UTC)：2026-09-17 03:35:47
# 口径 A=parent_id IS NULL 行数；口径 B=该角色 _visible_menu_ids() 后落在根层的数
# 「可见角色」列 = 三锚点里谁看得见本根（A=admin ／ B=backoffice ／ F=faculty）
# 「组」列 = 本根的 group_ids 名称（空=全员可见）

| 序 | id | xmlid | 名称 | 启用 | A | B | F | 组 | 子树节点 | 有action | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5 | 83 | mail.menu_root_discuss | 讨论 | 是 | ✓ | ✓ | · | 后台·完整视图 | 10 | 是 | 基座/原生 |
| 10 | 357 | calendar.mail_menu_calendar | 日历 | 是 | ✓ | ✓ | · | 后台·完整视图 | 4 | 否 | 基座/原生 |
| 18 | 591 | edu_apply.menu_edu_apply_root | 招生报名 | 是 | ✓ | ✓ | ✓ | 全员 | 2 | 否 | 自研 |
| 20 | 121 | contacts.menu_contacts | 联系人 | 是 | ✓ | ✓ | · | 后台·完整视图 | 12 | 否 | 基座/原生 |
| 30 | 434 | sale.sale_menu_root | 销售 | 否 | · | · | · | 全员 | 37 | 否 | 已停用；三锚点皆不可见；基座/原生 |
| 30 | 608 | edu_portal.menu_edu_download_root | 资料下载 | 是 | ✓ | ✓ | · | 经理 | 0 | 是 | 自研 |
| 37 | 214 | spreadsheet_dashboard.spreadsheet_dashboard_menu_root | 仪表板 | 是 | ✓ | ✓ | · | 后台·完整视图 | 4 | 是 | 基座/原生 |
| 42 | 504 | edu_quiz.menu_edu_quiz_root | 测验 | 是 | ✓ | ✓ | ✓ | 全员 | 2 | 否 | 自研 |
| 55 | 142 | account.menu_finance | 发票 | 是 | ✓ | ✓ | · | 显示会计功能 - 只读、发票、后台·完整视图 | 56 | 否 | 基座/原生 |
| 65 | 497 | edu_portal.menu_edu_approval_root | 教务审批 | 是 | ✓ | ✓ | ✓ | 角色/用户 | 8 | 否 | 自研 |
| 66 | 543 | edu_portal.menu_edu_welfare_root | 日常管理 | 是 | ✓ | ✓ | ✓ | 角色/用户 | 3 | 否 | 自研 |
| 67 | 576 | edu_portal.menu_edu_lms_root | 在线课程 | 是 | ✓ | ✓ | ✓ | 角色/用户 | 2 | 否 | 自研 |
| 68 | 579 | edu_portal.menu_edu_fees_root | 财务管理 | 是 | ✓ | ✓ | · | 经理 | 4 | 否 | 自研 |
| 69 | 582 | edu_portal.menu_edu_assets_root | 资产管理 | 是 | ✓ | ✓ | ✓ | 角色/用户 | 2 | 否 | 自研 |
| 70 | 585 | edu_portal.menu_edu_jobs_root | 招聘管理 | 是 | ✓ | ✓ | ✓ | 角色/用户 | 2 | 否 | 自研 |
| 70 | 593 | edu_life.menu_edu_life_root | 灵命生活 | 是 | ✓ | ✓ | ✓ | 角色/用户 | 3 | 否 | 自研 |
| 71 | 588 | edu_portal.menu_edu_eval_root | 综合评估 | 是 | ✓ | ✓ | ✓ | 角色/用户 | 2 | 否 | 自研 |
| 72 | 597 | edu_eval.menu_edu_admin_eval_root | 行政评估 | 是 | ✓ | ✓ | ✓ | 角色/用户 | 3 | 否 | 自研 |
| 80 | 542 | edu_portal.menu_edu_invite_code_root | 邀请码 | 是 | ✓ | ✓ | · | 角色 / 管理员、经理 | 0 | 是 | 自研 |
| 81 | 606 | edu_portal.menu_edu_relink_identity | 老账号补挂身份 | 是 | ✓ | ✓ | · | 角色 / 管理员、经理 | 0 | 是 | 自研 |
| 95 | 218 | website.menu_website_configuration | 网站 | 是 | ✓ | ✓ | · | 角色/用户、后台·完整视图 | 63 | 否 | 基座/原生 |
| 100 | 547 | website_slides.website_slides_menu_root | 在线学习 | 是 | ✓ | · | · | 主管 | 16 | 是 | 基座/原生 |
| 110 | 196 | hr.menu_hr_root | 员工 | 是 | ✓ | ✓ | ✓ | 角色/用户、主管：管理所有员工、管理员、后台·完整视图 | 33 | 否 | 基座/原生 |
| 125 | 372 | event.event_main_menu | 活动 | 是 | ✓ | ✓ | · | 登记处、后台·完整视图 | 12 | 否 | 基座/原生 |
| 205 | 529 | hr_attendance.menu_hr_attendance_root | 出勤 | 是 | ✓ | · | · | 考勤管理员:管理出勤率 | 11 | 否 | 基座/原生 |
| 210 | 388 | hr_recruitment.menu_hr_recruitment_root | 招聘 | 是 | ✓ | ✓ | · | 面试官、主管：管理所有申请人、后台·完整视图 | 27 | 否 | 基座/原生 |
| 220 | 257 | openeducat_core.menu_op_school_root | 学生信息 | 是 | ✓ | ✓ | ✓ | 全员 | 28 | 否 | 基座/原生 |
| 240 | 507 | im_livechat.menu_livechat_root | 在线聊天 | 是 | ✓ | ✓ | · | 用户、后台·完整视图 | 20 | 否 | 基座/原生 |
| 250 | 566 | data_recycle.menu_data_cleaning_root | 数据清除 | 是 | ✓ | · | · | 全员 | 4 | 否 | 基座/原生 |
| 260 | 278 | openeducat_core.menu_op_student_root | 学生 | 是 | ✓ | ✓ | ✓ | 用户、经理 | 8 | 否 | 基座/原生 |
| 270 | 75 | utm.menu_link_tracker_root | 链接追踪器 | 是 | ✓ | ✓ | · | 后台·完整视图 | 4 | 否 | 基座/原生 |
| 270 | 300 | openeducat_admission.menu_op_admission_root | 招生 | 是 | ✓ | · | ✓ | 用户、经理 | 7 | 否 | 基座/原生 |
| 280 | 341 | openeducat_timetable.menu_op_timetable_root | 时间表 | 是 | ✓ | ✓ | ✓ | 用户、经理 | 10 | 是 | 基座/原生 |
| 290 | 349 | openeducat_attendance.menu_op_attendance_root | 课堂考勤 | 是 | ✓ | ✓ | ✓ | 用户、经理 | 7 | 否 | 基座/原生 |
| 300 | 288 | openeducat_assignment.menu_op_assignment_root | 作业 | 是 | ✓ | · | ✓ | 用户 | 6 | 否 | 基座/原生 |
| 310 | 325 | openeducat_exam.menu_op_exam_root | 考试 | 是 | ✓ | ✓ | ✓ | 全员 | 15 | 否 | 基座/原生 |
| 390 | 310 | openeducat_library.menu_op_library_root | 图书馆 | 是 | ✓ | ✓ | ✓ | 用户、经理 | 14 | 否 | 基座/原生 |
| 500 | 15 | base.menu_management | 应用 | 是 | ✓ | · | · | 角色 / 管理员 | 8 | 否 | 仅超管；基座/原生 |
| 550 | 1 | base.menu_administration | 设置 | 是 | ✓ | · | · | 访问权限、角色 / 管理员 | 116 | 否 | 基座/原生 |
| 1000 | 16 | base.menu_tests | 测试 | 是 | · | · | · | 全员 | 0 | 否 | 三锚点皆不可见；基座/原生 |

# 口径数字
# A 原始根菜单=40（active 39 / inactive 1）｜全库菜单 605（active 601）
# B admin 可见根=38（C 可见叶子=400，可见总数=551）
# B backoffice@local 可见根=31（C 可见叶子=279，可见总数=391）
# B faculty@local 可见根=19（C 可见叶子=115，可见总数=164）
MENU_BASELINE_OK mode=plan rc=0
