# -*- coding: utf-8 -*-
{
    'name': 'Edu Student Portal (Clone)',
    'summary': '学生门户复刻：/my/home 卡片索引、课表等企业版页面自研重建',
    'description': """
以目标站抓取的参考 DOM 为蓝本，在开源 OpenEduCat 模型之上重建学生端门户：
- /my/home 功能卡片索引（对齐原站 o_portal_index_card 网格）
- /student/timetable 学生课表（服务端渲染）
- /student/attendance 考勤列表/汇总
- /student/profile 学生档案
- /student/exam 考试列表
- /student/assignment/details 作业列表
- 登录跳转 /my/home
    """,
    # 19.0.3.0.0：专业编排（学制 + 必修/选修）—— 新增 edu.course.subject 关系表 +
    # op.course.subject_ids 兼容层 + migrations/19.0.3.0.0（334 行关系搬迁 +
    # 三条自证）。版本号递增是触发 migrations/ 的唯一开关（先例 19.0.2.0.0）。
    # 19.0.4.0.0：请假单拆分 + 分级审批 + 转交审批（S1 数据层）。
    # 新增 edu.leave.transfer（UNIQUE(leave_id, stage)）+ edu.leave 分级/转交/销假/
    # 证明/提前期/配额字段 + op.batch.homeroom_teacher_id +
    # migrations/19.0.4.0.0（7 步回填与逐条自证）。
    # ⚠ 版本号递增是触发 migrations/ 的**唯一开关**（先例 19.0.2.0.0 / 19.0.3.0.0）。
    'version': '19.0.4.0.0',
    'category': 'Website',
    'depends': [
        'portal',
        'website',
        'openeducat_core',
        'openeducat_timetable',
        'openeducat_attendance',
        'openeducat_assignment',
        'openeducat_exam',
        'openeducat_library',
        # op.parent / op.student 的档案层：models/parent_link_fix.py 既 _inherit
        # 这两个模型、也直接 import 基座类（跳过缺陷层），故必须显式声明依赖。
        'openeducat_parent',
        'edu_apply',
        'edu_brand',
        'edu_schedule',
    ],
    'data': [
        'security/ir.model.access.csv',
        # 安全审计 F1：edu.* 行级权限（ir.rule）。此前本模块只有 CSV 没有
        # security.xml，门户账号一条 RPC 即可读走全校数据。
        'security/security.xml',
        # 权限分层修正：解除「教务组隐含系统管理员」（见文件内注释）
        'views/group_tuning.xml',
        # 可达性收口：把「教务看得见但打不开」的原生菜单收回到它真正需要的业务组
        # （<function> 只改菜单 group_ids，幂等、缺模块不报错）
        'data/menu_reachability.xml',
        # 班级分配与管理（需求 7）：批次菜单对教师开放（只改 ir.ui.menu 组关系，
        # 不写业务表；写法与上一条同源）
        'data/class_batch_data.xml',
        'data/timetable_params.xml',
        # 费用分类字典（校方自助增删；必须在账单视图之前加载）
        'data/fee_categories.xml',
        'views/invite_code_views.xml',
        'views/register.xml',
        'views/edu_portal_templates.xml',
        'views/my_password_views.xml',
        'views/batch1.xml',
        'views/batch2.xml',
        'views/batch3.xml',
        # 2026-10-01：enroll.xml 必须排在 roles.xml **之前**。
        #   roles.xml 里的 edu_registrar_subject_approvals_bulk 用 inherit_id 继承了
        #   enroll.xml 定义的 edu_registrar_subject_approvals（同样地 edu_enroll_catalog_bulk），
        #   装载期 id_get 找不到该 xmlid 就抛
        #     ValueError: External ID not found in the system: edu_portal.edu_registrar_subject_approvals
        #   （真实事故：重建新服务器时 -u all 在 Loading module edu_portal (133/135) 处
        #     CRITICAL + exit 255。roles.xml 自己的注释早就写着「继承 enroll.xml」，
        #     但从来没把顺序改对。）
        #   ⚠ 为什么以前一直不炸：老库的 ir_model_data 里早已存在该 xmlid（历次增量升级
        #     留下的），id_get 直接命中；**全新库 / 首次升级**才会暴露。
        #     这正是本仓反复出现的「只在无法失败的环境里测过」类缺陷。
        #   校验脚本：临时用 /tmp/order_fix.py 的算法（按 manifest 顺序求 inherit_id 的
        #     定义位置），本模块修复后 problems=0。
        'views/enroll.xml',
        'views/roles.xml',
        # 教师自助不可用时间（排课链路 §10.2）：只依赖 edu_portal_templates.xml
        # 的 edu_page 与 roles.xml 的教师身份口径，故排在两者之后。
        'views/availability.xml',
        'views/contacts.xml',
        'views/calendar.xml',
        'views/messages.xml',
        'views/approval_backend.xml',
        'views/notice_admin.xml',
        'views/certificate_report.xml',
        'views/welfare.xml',
        'views/scheduling.xml',
        'views/lms.xml',
        # 课代表（设计 §5.2 后台侧列表/任命/撤销 + §4.3 每日到期收口 cron）
        'views/course_rep.xml',
        'views/fees.xml',
        'views/assets.xml',
        'views/jobs.xml',
        'views/menu_icons.xml',
        'views/evaluation.xml',
        'views/exam_session_ext.xml',
        'views/help_center.xml',
        'views/downloads_views.xml',
        'views/downloads_portal.xml',
        'views/partner_labels.xml',
        # 班级分配与管理（需求 7）：班级列表状态列/停用恢复、学生页分班入口与
        # 待分配过滤器、已停用班级回收站
        'views/class_batch_views.xml',
        'views/fee_category.xml',
        'views/ledger.xml',
        # v3 一条龙（t6）：课程中心 /my/study + 首页 Timeline + /my/apps
        'views/study.xml',
        # 专业编排（学制 + 必修/选修）：菜单/动作改名（设计 §6.6）+
        # 专业表单 Subjects 页的「必修/选修」列（设计 §6.8）
        'views/major_track_views.xml',
        # 后台菜单/动作改名（2026-09-22 教务找「院系」落进人事表）：
        # 259「院系」→「教职员工」（它的模型是 op.faculty 人事档案，误名）、
        # 265「部门」→「院系部门」（op.department = 教务要建的院系）。
        # 机制/依据/升级顺序见该文件头注释；中文词条在 edu_zh/i18n_extra/*.po。
        'views/menu_labels.xml',
        # 教职员工（op.faculty）表单瘦身（2026-09，校长反馈「后面搞那么多无关的信息」）：
        # 首屏只留 姓名/性别/出生日期/所属院系/邮箱/电话 + 科目页签，其余字段收进
        # 「更多信息」页签，图书馆页签与「媒体」按钮整页移除。只做视图继承，
        # 不删模型字段（文件内注释写明判据与还原办法）。
        'views/faculty_form.xml',
        # 请假分级审批（设计 §9.2）：op.batch 班主任字段 + edu.leave 表单/列表扩展 +
        # 门户审批列表/详情/表单扩展 + 销假逾期提醒 cron（新记录，不改 cron 39）。
        # ⚠ 本文件由 **S4** 填充内容；S1 只建立「最小可载入的占位」并登记引用
        #   （check_manifest_tracking.py 要求 manifest 引用集 ⊆ git 跟踪集）。
        'views/leave_flow.xml',
        'views/curriculum.xml',   # 教务端「课程编排」门户入口（页面模板 + 导航继承；数据面仍是 edu.course.subject）
        # 成绩录入（2026-09-29）：教务 / 任课教师的整班矩阵录分页。**不新造成绩模型** ——
        # 数据全部落在基座既有 op.marksheet.* 链上（见 controllers/grade_entry.py 文件头）。
        'views/grade_entry.xml',
        # 成绩中心（2026-10-13）：批量 xlsx 导入导出（门户页 + 逐行回报）+ 后台只读容器列表与
        # 「打开录入页」按钮。控制器在 controllers/grade_entry_io.py —— 复用 grade_entry.py 的
        # 容器 / 权限 / 名册口径，读写都走 edu_apply_marks（不新造第二套录分路径）。
        'views/grade_entry_io.xml',
        'views/grade_admin_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'edu_portal/static/src/css/batch1.css',
            'edu_portal/static/src/css/portal.css',
            'edu_portal/static/src/css/batch3.css',
            'edu_portal/static/src/css/enterprise.css',
            'edu_portal/static/src/css/custom_home.css',
            # ux-rework（S1-S5/W1-W2）：排课/校历/工作台交互增强样式与常用区编辑
            'edu_portal/static/src/css/ux_rework.css',
            'edu_portal/static/src/css/enroll.css',
            # v3 一条龙（t6）：课程中心 / Timeline 工作台 / 应用面板
            'edu_portal/static/src/css/ux_v3.css',
            'edu_portal/static/src/js/quick_login.js',
            # home_search.js 已删（task-9 的 V5）：它只服务横幅那个「假搜索」（前端过滤卡片），
            # 而横幅那个已在 V5 去掉（与顶栏真搜索重复）⇒ 脚本成了空转的死代码。
            # 本仓纪律：不为「万一以后要用」保留死代码；要恢复就用 git 历史取回。
            'edu_portal/static/src/js/alerts_read.js',
            'edu_portal/static/src/js/msg_poll.js',
            'edu_portal/static/src/js/home_favs.js',
            'edu_portal/static/src/js/search_focus.js',
            'edu_portal/static/src/css/banner.css',
            'edu_portal/static/src/js/notice_banner.js',
            # v3 搜索可用性（2026-09-29）：顶栏「输入即出」下拉建议（渐进增强，
            # 无脚本时表单照常 GET /my/search）
            'edu_portal/static/src/css/search_suggest.css',
            'edu_portal/static/src/js/search_suggest.js',
            # 成绩录入矩阵**不新增 JS**：直接复用 edu_assess 的矩阵增强
            # （static/src/js/assess_grid.js + css/assess_grid.css，同在 web.assets_frontend）
            # —— 键盘整列录入 / 整块粘贴 / 粘性表头三件事已由它实现，本页只挂
            # .yy-assess-scroll + .yy-assess-matrix 两个类（见 views/grade_entry.xml）。
        ],
        'web.assets_backend': [
            'edu_portal/static/src/js/apps_menu_redirect.js',
            'edu_portal/static/src/js/apps_panel_chip.js',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
}
